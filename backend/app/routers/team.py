"""Team router — invites, accumulated-role management and access revocation.

Endpoints (RF-40 / RF-04 / F3):
  - POST   /team/invite           create a convidado app_user + Brevo activation
  - PUT    /team/{usuarioId}/roles  edit accumulated roles (union)
  - DELETE /team/{usuarioId}      revoke access (soft: status -> 'revogado')

A duplicate email in the tenant is rejected (409). Roles are stored as the union
of user_roles (F3). Removing/demoting (roles) or revoking (access) the LAST
active admin is blocked so a tenant never loses its administrator. Config screens
are admin-only (delta-005).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AppUser, Celula, Pessoa, UserRole
from app.db.session import get_db
from app.deps import (
    ADMIN_ROLE,
    REVOKED_USER_STATUS,
    CurrentUser,
    get_current_user,
    require_role,
)
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

# Papel atribuído automaticamente a quem é convidado: convites não escolhem
# papéis — somente pessoas já cadastradas têm os papéis editados (delta-049).
MEMBRO_ROLE = "membro"


class InviteRequest(BaseModel):
    """Convite = acesso ao painel + vínculo de célula como MEMBRO (delta-049).

    O convite NÃO escolhe papéis: o convidado entra como ``membro``. Papéis só
    são editados depois, para pessoas já cadastradas (PUT .../roles). A célula é
    de quem convida: um líder traz para a SUA célula; um admin/pastor marca em
    ``celulaId``. Dois modos:

    - Parte A — ``pessoaId``: a pessoa JÁ está cadastrada (tem telefone) e ainda
      não pertence a nenhuma célula;
    - Parte B — ``nome``: a pessoa é NOVA; completa o cadastro (telefone) na
      ativação e só então vira a Pessoa-membro (a célula fica pendente até lá).
    """

    pessoaId: str | None = Field(default=None)  # noqa: N815 - Parte A
    nome: str | None = Field(default=None, max_length=200)  # Parte B
    email: str = Field(min_length=3, max_length=320)
    celulaId: str | None = Field(default=None)  # noqa: N815 - admin/pastor marca

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.split("@")[-1]:
            raise ValueError("e-mail inválido")
        return value

    @field_validator("nome")
    @classmethod
    def _nome(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def _target(self) -> "InviteRequest":
        if not self.pessoaId and not self.nome:
            raise ValueError(
                "Informe a pessoa a convidar (pessoaId) ou o nome para cadastrar"
            )
        return self


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


class RevokeResponse(BaseModel):
    usuarioId: str  # noqa: N815
    status: str  # revogado


class TeamMemberOut(BaseModel):
    """A panel user with its accumulated roles (for assignment pickers)."""

    usuarioId: str  # noqa: N815
    nome: str
    email: str
    status: str | None = None
    papeis: list[str]
    pessoaId: str | None = None  # noqa: N815 - liga ao registro de Pessoa


def _activation_link(app_user_id: uuid.UUID, clerk: ClerkClient) -> str:
    """Link de ativação com token de convite assinado (expira em 7 dias)."""
    token = clerk.mint_invite_token(str(app_user_id))
    base = get_settings().frontend_url.rstrip("/")
    return f"{base}/#ativar/{token}"


def _active_admin_user_ids(db: Session, igreja_id: uuid.UUID) -> set[uuid.UUID]:
    """User ids holding the admin role whose account is NOT revoked.

    The revoke guard counts active admins only: a revoked admin keeps its admin
    user_role (soft revoke preserves history) but must not count toward the
    administrator floor, otherwise the second-to-last admin could be revoked and
    leave the tenant with no usable administrator. NULL status counts as active.
    """
    rows = db.execute(
        select(UserRole.user_id)
        .join(AppUser, AppUser.id == UserRole.user_id)
        .where(
            UserRole.igreja_id == igreja_id,
            UserRole.papel == ADMIN_ROLE,
            AppUser.status.is_distinct_from(REVOKED_USER_STATUS),
        )
    ).scalars().all()
    return set(rows)


@router.get("", response_model=Page[TeamMemberOut])
def list_members(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(
        require_role(["admin", "pastor", "lider_g12"])
    ),
) -> Page[TeamMemberOut]:
    """List tenant members with e-mail and accumulated roles (F3).

    Restrita a quem enxerga a tela Equipe (admin/pastor/lider_g12): a resposta
    expõe e-mail (PII) e o mapa de papéis. O painel usa GET /team/lookup (enxuto,
    sem e-mail) para resolver nomes — não este endpoint. Paginado (RNF-09).
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
                pessoaId=str(u.pessoa_id) if u.pessoa_id else None,
            )
            for u in users
        ],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


@router.get("/lookup", response_model=Page[TeamMemberOut])
def list_members_lookup(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Page[TeamMemberOut]:
    """Lista ENXUTA de membros (id, nome, papéis) para o painel.

    Acessível a qualquer usuário autenticado do tenant: o dashboard precisa
    resolver o NOME (e o papel) do responsável de cada item da fila — para todos
    os papéis. O e-mail (PII) é OMITIDO de propósito; a lista completa com e-mail
    vive em GET /team, restrita a admin/pastor/lider_g12.
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

    role_rows = db.execute(select(UserRole.user_id, UserRole.papel)).all()
    roles_by_user: dict[uuid.UUID, list[str]] = {}
    for user_id, papel in role_rows:
        roles_by_user.setdefault(user_id, []).append(papel)

    return Page[TeamMemberOut](
        items=[
            TeamMemberOut(
                usuarioId=str(u.id),
                nome=u.nome,
                email="",  # PII omitida na busca enxuta do painel
                status=None,
                papeis=sorted(roles_by_user.get(u.id, [])),
                pessoaId=str(u.pessoa_id) if u.pessoa_id else None,
            )
            for u in users
        ],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


def _actor_pessoa_id(db: Session, current_user: CurrentUser) -> uuid.UUID | None:
    """Resolve the acting user's linked pessoa_id (to find the cell they lead)."""
    return db.execute(
        select(AppUser.pessoa_id).where(
            AppUser.id == uuid.UUID(current_user.app_user_id)
        )
    ).scalar_one_or_none()


def _get_cell_in_tenant(db: Session, cell_id: str) -> Celula:
    """Load a cell by id within the tenant (RLS-scoped) or raise 404."""
    try:
        cell_uuid = uuid.UUID(cell_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
        ) from exc
    cell = db.execute(
        select(Celula).where(Celula.id == cell_uuid)
    ).scalar_one_or_none()
    if cell is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
        )
    return cell


def _resolve_invite_cell(
    db: Session, current_user: CurrentUser, celula_id: str | None
) -> Celula:
    """Determine which cell the invited member joins (delta-049).

    Admin and pastor MARK any cell (``celulaId``). A cell leader may only invite
    into a cell they actually lead: an explicit ``celulaId`` is honored when it
    is theirs (403 otherwise), and omitting it derives their own active cell.
    A non-leader with no cell to derive — or an admin/pastor who picked none —
    gets a clear error.
    """
    marks_cell = ADMIN_ROLE in current_user.roles or "pastor" in current_user.roles
    actor = _actor_pessoa_id(db, current_user)

    if celula_id:
        cell = _get_cell_in_tenant(db, celula_id)
        # Admin/pastor escolhem qualquer célula; um líder só a que ele lidera.
        if marks_cell or (actor is not None and cell.lider_id == actor):
            return cell
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você só pode convidar para a sua própria célula",
        )

    # Sem id explícito: deriva a célula ativa que o próprio usuário lidera.
    if actor is not None:
        led = db.execute(
            select(Celula)
            .where(Celula.lider_id == actor, Celula.ativo.is_(True))
            .order_by(Celula.created_at.asc())
        ).scalars().first()
        if led is not None:
            return led

    if marks_cell:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selecione a célula do convidado",
        )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Você não lidera nenhuma célula para convidar membros",
    )


@router.post("/invite", response_model=InviteResponse)
def invite_member(
    payload: InviteRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(
        require_role(["admin", "pastor", "lider_celula"])
    ),
    mailer: BrevoClient = Depends(get_brevo_client),
    clerk: ClerkClient = Depends(get_clerk_client),
) -> InviteResponse:
    """Invite someone as a cell MEMBER and email the activation link.

    Allowed for an admin, a pastor or a cell leader (delta-049). The invite
    grants panel access (status ``convidado``, role ``membro``) AND binds the
    member to a cell: the leader's own cell, or the cell an admin/pastor marks
    in ``celulaId``. Two modes:

    - Parte A (``pessoaId``): a registered person — bound to the cell now; must
      not already have panel access (409) nor already belong to a cell (409,
      moving is admin-only);
    - Parte B (``nome``): a NEW person — the activation collects the phone and
      creates the Pessoa-member then; the cell is held in ``celula_pendente_id``.

    Duplicate tenant e-mail is rejected (409). The e-mail send is best-effort
    (emailEnviado=false on failure), so an invite can be re-sent.
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

    # Quem convida define a célula; o convidado não a escolhe (vale p/ A e B).
    celula = _resolve_invite_cell(db, current_user, payload.celulaId)

    if payload.pessoaId:
        # Parte A — a pessoa JÁ está cadastrada (tem telefone). RLS escopa a
        # busca ao tenant, então um id de outra igreja resolve para None.
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
                status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada"
            )

        # Uma pessoa não pode ter dois logins.
        linked = db.execute(
            select(AppUser).where(AppUser.pessoa_id == pessoa_uuid)
        ).scalar_one_or_none()
        if linked is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Esta pessoa já possui acesso ao painel",
            )

        # Célula única: convite só para quem ainda não tem célula. Transferir
        # entre células é exclusivo do admin (ação à parte).
        if pessoa.celula_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Esta pessoa já faz parte de uma célula. Apenas um "
                    "administrador pode transferi-la de célula."
                ),
            )

        pessoa.celula_id = celula.id
        # A Pessoa é a fonte de verdade: se ainda não tinha e-mail, guarda o do
        # convite para o cadastro não divergir do login.
        if not (pessoa.email or "").strip():
            pessoa.email = email

        nome = pessoa.nome
        app_user = AppUser(
            igreja_id=igreja_uuid,
            nome=nome,
            email=email,
            status="convidado",
            pessoa_id=pessoa_uuid,
        )
    else:
        # Parte B — pessoa NOVA: app_user convidado sem Pessoa ainda; a célula
        # fica pendente até a ativação coletar o telefone e criar a Pessoa.
        nome = str(payload.nome)  # garantido pelo validador (Parte A ou B)
        app_user = AppUser(
            igreja_id=igreja_uuid,
            nome=nome,
            email=email,
            status="convidado",
            pessoa_id=None,
            celula_pendente_id=celula.id,
        )

    db.add(app_user)
    db.flush()  # assign id

    # Convites entram sempre como MEMBRO (papéis são editados depois).
    db.add(UserRole(igreja_id=igreja_uuid, user_id=app_user.id, papel=MEMBRO_ROLE))

    db.refresh(app_user)
    db.commit()

    email_sent = False
    try:
        mailer.send_invite(
            to_email=email,
            nome=nome,
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

    Removing/demoting the last *active* admin of the tenant is blocked (409) so a
    church is never left without an administrator; revoked admins don't count
    toward that floor (mirrors the revoke guard).
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
    admin_ids = _active_admin_user_ids(db, igreja_uuid)
    # Block if this user is the last *active* admin and the new roles drop admin.
    # A revoked admin keeps its admin user_role but doesn't count toward the
    # administrator floor, so it's excluded here too (mirrors the revoke guard).
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


@router.delete("/{usuario_id}", response_model=RevokeResponse)
def revoke_member(
    usuario_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> RevokeResponse:
    """Revoke a member's access (RF-04 / US-03). Soft: status -> 'revogado'.

    The app_user row is kept for auditability; access is blocked at auth time
    (get_current_user and /auth/login both reject a revoked app_user). The panel
    session is a PastorAI-issued JWT (not a Clerk session), so the status gate is
    what enforces revocation — there is no live Clerk session created at login to
    revoke. Revoking the last *active* admin is blocked (409) so the church is
    never left without an administrator. A cross-tenant id is invisible under RLS
    and returns 404 (S4: never reveal existence). Already-revoked is idempotent.
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

    if app_user.status == REVOKED_USER_STATUS:
        return RevokeResponse(usuarioId=str(user_uuid), status=REVOKED_USER_STATUS)

    active_admins = _active_admin_user_ids(db, igreja_uuid)
    if user_uuid in active_admins and len(active_admins) <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não é possível revogar o último administrador",
        )

    app_user.status = REVOKED_USER_STATUS
    db.commit()

    return RevokeResponse(usuarioId=str(user_uuid), status=REVOKED_USER_STATUS)
