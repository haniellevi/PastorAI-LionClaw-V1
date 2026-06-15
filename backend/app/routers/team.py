"""Team router — invites and accumulated-role management (RF-40 / F3).

Endpoints:
  - POST /team/invite          create a convidado app_user + Brevo activation
  - PUT  /team/{usuarioId}/roles  edit accumulated roles (union)

A duplicate email in the tenant is rejected (409). Roles are stored as the union
of user_roles (F3). Removing or demoting the LAST admin is blocked so a tenant
never loses its only administrator. Config screens are admin-only (delta-005).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AppUser, Pessoa, UserRole
from app.db.session import get_db
from app.deps import ADMIN_ROLE, CurrentUser, get_current_user, require_role
from app.routers._common import Page, PaginationParams, ensure_tenant_context
from app.services.brevo import BrevoClient, BrevoError, get_brevo_client
from app.services.clerk import ClerkClient, get_clerk_client

logger = logging.getLogger("pastorai.team")

router = APIRouter(prefix="/team", tags=["team"])

VALID_ROLES = {
    "admin",
    "operador",
    "pastor",
    "lider_g12",
    "lider_consol",
    "lider_celula",
    "lider_mult",
    "membro",
}


class InviteRequest(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    papeis: list[str] = Field(default_factory=list)
    pessoaId: str | None = Field(default=None)  # noqa: N815

    @field_validator("nome")
    @classmethod
    def _nome(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("nome obrigatório")
        return value

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.split("@")[-1]:
            raise ValueError("e-mail inválido")
        return value

    @field_validator("papeis")
    @classmethod
    def _papeis(cls, value: list[str]) -> list[str]:
        normalized = []
        for raw in value:
            role = (raw or "").strip().lower()
            if role not in VALID_ROLES:
                raise ValueError(f"papel inválido: {raw}")
            if role not in normalized:
                normalized.append(role)
        return normalized


class InviteResponse(BaseModel):
    usuarioId: str  # noqa: N815
    status: str  # convidado
    emailEnviado: bool  # noqa: N815


class RolesRequest(BaseModel):
    papeis: list[str] = Field(min_length=1)

    @field_validator("papeis")
    @classmethod
    def _papeis(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in value:
            role = (raw or "").strip().lower()
            if role not in VALID_ROLES:
                raise ValueError(f"papel inválido: {raw}")
            if role not in normalized:
                normalized.append(role)
        return normalized


class RolesResponse(BaseModel):
    usuarioId: str  # noqa: N815
    papeis: list[str]


class TeamMemberOut(BaseModel):
    """A panel user with its accumulated roles (for assignment pickers)."""

    usuarioId: str  # noqa: N815
    nome: str
    email: str
    status: str | None = None
    papeis: list[str]


def _activation_link(app_user_id: uuid.UUID, clerk: ClerkClient) -> str:
    """Link de ativação com token de convite assinado (expira em 7 dias)."""
    token = clerk.mint_invite_token(str(app_user_id))
    base = get_settings().frontend_url.rstrip("/")
    return f"{base}/#ativar/{token}"


def _admin_user_ids(db: Session, igreja_id: uuid.UUID) -> set[uuid.UUID]:
    rows = db.execute(
        select(UserRole.user_id).where(
            UserRole.igreja_id == igreja_id, UserRole.papel == ADMIN_ROLE
        )
    ).scalars().all()
    return set(rows)


@router.get("", response_model=Page[TeamMemberOut])
def list_members(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Page[TeamMemberOut]:
    """List tenant members and their accumulated roles (F3).

    Tenant-scoped via RLS; used by the dashboard to populate the "assign"
    picker and the "next actions by responsible" panel. Paginated (RNF-09).
    """
    ensure_tenant_context(db, current_user)

    total = db.execute(
        select(func.count()).select_from(AppUser)
    ).scalar_one()
    users = db.execute(
        select(AppUser)
        .order_by(AppUser.nome.asc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()

    role_rows = db.execute(
        select(UserRole.user_id, UserRole.papel)
    ).all()
    roles_by_user: dict[uuid.UUID, list[str]] = {}
    for user_id, papel in role_rows:
        roles_by_user.setdefault(user_id, []).append(papel)

    return Page[TeamMemberOut](
        items=[
            TeamMemberOut(
                usuarioId=str(u.id),
                nome=u.nome,
                email=u.email,
                status=u.status,
                papeis=sorted(roles_by_user.get(u.id, [])),
            )
            for u in users
        ],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


@router.post("/invite", response_model=InviteResponse)
def invite_member(
    payload: InviteRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
    mailer: BrevoClient = Depends(get_brevo_client),
    clerk: ClerkClient = Depends(get_clerk_client),
) -> InviteResponse:
    """Create a convidado app_user and email the activation link.

    A duplicate email within the tenant is rejected (409). The email send is
    best-effort: the user is still created if Brevo fails (emailEnviado=false),
    so an invite can be re-sent without re-creating the account.
    """
    ensure_tenant_context(db, current_user)
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    email = str(payload.email).strip().lower()

    existing = db.execute(
        select(AppUser).where(func.lower(AppUser.email) == email)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um usuário com este e-mail",
        )

    # Link the panel access to an existing Pessoa when provided (Fase 1): the
    # invited user IS a registered person, not a parallel identity. RLS scopes
    # the lookup to the tenant, so an id from another igreja resolves to None.
    pessoa_uuid: uuid.UUID | None = None
    if payload.pessoaId:
        try:
            pessoa_uuid = uuid.UUID(payload.pessoaId)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="pessoaId inválido",
            ) from exc
        pessoa = db.execute(
            select(Pessoa).where(Pessoa.id == pessoa_uuid)
        ).scalar_one_or_none()
        if pessoa is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pessoa não encontrada",
            )
        # Uma pessoa não pode ter dois logins: bloqueia conceder acesso a quem
        # já tem um app_user vinculado (evita identidade de painel duplicada).
        linked = db.execute(
            select(AppUser).where(AppUser.pessoa_id == pessoa_uuid)
        ).scalar_one_or_none()
        if linked is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Esta pessoa já possui acesso ao painel",
            )
        # A Pessoa é a fonte de verdade: se ainda não tinha e-mail, guarda o
        # informado no convite para o cadastro não divergir do login.
        if not (pessoa.email or "").strip():
            pessoa.email = email

    app_user = AppUser(
        igreja_id=igreja_uuid,
        nome=payload.nome,
        email=email,
        status="convidado",
        pessoa_id=pessoa_uuid,
    )
    db.add(app_user)
    db.flush()  # assign id

    for role in payload.papeis:
        db.add(
            UserRole(igreja_id=igreja_uuid, user_id=app_user.id, papel=role)
        )

    db.refresh(app_user)
    db.commit()

    email_sent = False
    try:
        mailer.send_invite(
            to_email=email,
            nome=payload.nome,
            activation_link=_activation_link(app_user.id, clerk),
        )
        email_sent = True
    except BrevoError:
        logger.warning("Invite created but activation email failed to send")

    return InviteResponse(
        usuarioId=str(app_user.id), status="convidado", emailEnviado=email_sent
    )


@router.put("/{usuario_id}/roles", response_model=RolesResponse)
def update_roles(
    usuario_id: str,
    payload: RolesRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> RolesResponse:
    """Replace a user's accumulated roles (union), guarding the last admin.

    Removing/demoting the last admin of the tenant is blocked (409) so a church
    is never left without an administrator.
    """
    ensure_tenant_context(db, current_user)
    igreja_uuid = uuid.UUID(current_user.igreja_id)

    try:
        user_uuid = uuid.UUID(usuario_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado"
        ) from exc

    app_user = db.execute(
        select(AppUser).where(AppUser.id == user_uuid)
    ).scalar_one_or_none()
    if app_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado"
        )

    new_roles = set(payload.papeis)
    admin_ids = _admin_user_ids(db, igreja_uuid)
    # Block if this user is the last admin and the new roles drop admin.
    if (
        user_uuid in admin_ids
        and ADMIN_ROLE not in new_roles
        and len(admin_ids) <= 1
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não é possível remover/rebaixar o último administrador",
        )

    current_roles = db.execute(
        select(UserRole).where(UserRole.user_id == user_uuid)
    ).scalars().all()
    current_by_role = {r.papel: r for r in current_roles}

    # Drop roles no longer present.
    for role, row in current_by_role.items():
        if role not in new_roles:
            db.delete(row)
    # Add newly granted roles.
    for role in new_roles:
        if role not in current_by_role:
            db.add(
                UserRole(igreja_id=igreja_uuid, user_id=user_uuid, papel=role)
            )

    db.commit()

    return RolesResponse(usuarioId=str(user_uuid), papeis=sorted(new_roles))


@router.post("/{usuario_id}/resend", response_model=InviteResponse)
def resend_invite(
    usuario_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
    mailer: BrevoClient = Depends(get_brevo_client),
    clerk: ClerkClient = Depends(get_clerk_client),
) -> InviteResponse:
    """Re-send the activation email to an existing member (best-effort).

    For an invited (convidado) user whose activation e-mail did not arrive. The
    send is best-effort: emailEnviado=false when the provider fails, so the
    invite can be re-sent again without side effects.
    """
    ensure_tenant_context(db, current_user)

    try:
        user_uuid = uuid.UUID(usuario_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado"
        ) from exc

    app_user = db.execute(
        select(AppUser).where(AppUser.id == user_uuid)
    ).scalar_one_or_none()
    if app_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado"
        )

    email_sent = False
    try:
        mailer.send_invite(
            to_email=app_user.email,
            nome=app_user.nome,
            activation_link=_activation_link(app_user.id, clerk),
        )
        email_sent = True
    except BrevoError:
        logger.warning("Resend invite: activation email failed to send")

    return InviteResponse(
        usuarioId=str(app_user.id),
        status=app_user.status or "convidado",
        emailEnviado=email_sent,
    )


@router.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_member(
    usuario_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> None:
    """Revoke a member's panel access (deletes the app_user and its roles).

    Removing the last admin of the tenant is blocked (409) so a church is never
    left without an administrator. The user's user_roles are removed by FK
    cascade (and the linked Pessoa is preserved — only the login is revoked).
    """
    ensure_tenant_context(db, current_user)
    igreja_uuid = uuid.UUID(current_user.igreja_id)

    try:
        user_uuid = uuid.UUID(usuario_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado"
        ) from exc

    app_user = db.execute(
        select(AppUser).where(AppUser.id == user_uuid)
    ).scalar_one_or_none()
    if app_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado"
        )

    admin_ids = _admin_user_ids(db, igreja_uuid)
    if user_uuid in admin_ids and len(admin_ids) <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não é possível remover o último administrador",
        )

    db.delete(app_user)
    db.commit()
