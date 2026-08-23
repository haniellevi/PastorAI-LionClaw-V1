"""Team router — invites, accumulated-role management and access revocation.

Endpoints (RF-40 / RF-04 / F3):
  - POST   /team/invite           create a convidado app_user + Brevo activation
  - PUT    /team/{usuarioId}/roles  edit accumulated roles (union)
  - DELETE /team/{usuarioId}      revoke access (soft: status -> 'revogado')

A duplicate e-mail anywhere in the platform is rejected (409), matching Clerk's
global identity namespace. Roles are stored as the union of user_roles (F3).
Removing/demoting (roles) or revoking (access) the LAST active admin is blocked
so a tenant never loses its administrator. Config screens are admin-only
(delta-005).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db.models import AppUser, Celula, Igreja, Pessoa, UserRole
from app.db.session import get_db
from app.deps import (
    ADMIN_ROLE,
    REVOKED_USER_STATUS,
    CurrentUser,
    get_current_user,
    require_role,
)
from app.domain.conversations import INBOX_ROLES, can_access_inbox
from app.domain.work_queue import TIPO_RESOLVER_ROLES, resolvable_tipos
from app.routers._common import Page, PaginationParams
from app.services.brevo import BrevoClient, BrevoError, get_brevo_client
from app.services.clerk import ClerkClient, get_clerk_client
from app.services.cell_leadership import resolve_effective_access
from app.services.frontend_auth_links import build_frontend_auth_link
from app.services.invite_identity import (
    assert_invite_email_available,
    get_invite_identity_db,
)

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
    """Convite concede somente acesso ao painel, sempre com papel base membro.

    Vínculo e liderança de célula são operações independentes. ``extra=forbid``
    rejeita inclusive o antigo ``celulaId`` em novos convites. Na ativação,
    ``celula_pendente_id`` legado é descartado sem criar vínculo.
    """

    model_config = ConfigDict(extra="forbid")

    pessoaId: str | None = Field(default=None)  # noqa: N815 - Parte A
    nome: str | None = Field(default=None, max_length=200)  # Parte B
    email: str = Field(min_length=3, max_length=320)

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
    papeis: list[str]

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


class TeamLookupOut(TeamMemberOut):
    """Minimal assignment-picker projection with server-derived capabilities."""

    tiposFila: list[str] = Field(default_factory=list)  # noqa: N815


class InboxLookupOut(BaseModel):
    """Minimal transfer destination, without e-mail or person data."""

    usuarioId: str  # noqa: N815
    nome: str
    papeis: list[str]


def _activation_link(app_user_id: uuid.UUID, clerk: ClerkClient) -> str:
    """Link de ativação com token de convite assinado (expira em 7 dias)."""
    token = clerk.mint_invite_token(str(app_user_id))
    return build_frontend_auth_link(
        get_settings().frontend_url,
        "ativar",
        token,
    )


def _active_admin_user_ids(db: Session, igreja_id: uuid.UUID) -> set[uuid.UUID]:
    """Admins que possuem acesso utilizável, não apenas um papel persistido.

    ``status IS NULL`` é legado ativo. Convidado/revogado e conta sem Clerk não
    sustentam o piso de último administrador.
    """
    rows = db.execute(
        select(UserRole.user_id)
        .join(AppUser, AppUser.id == UserRole.user_id)
        .where(
            UserRole.igreja_id == igreja_id,
            UserRole.papel == ADMIN_ROLE,
            AppUser.igreja_id == igreja_id,
            AppUser.clerk_user_id.is_not(None),
            or_(AppUser.status.is_(None), AppUser.status == "ativo"),
        )
    ).scalars().all()
    return set(rows)


def _lock_target_identity(
    db: Session, *, igreja_id: uuid.UUID, app_user: AppUser
) -> AppUser:
    """Serializa gestão de acesso/papéis com atribuição de liderança.

    O caller já deve ter travado a Igreja. A ordem comum das mutações
    administrativas é Igreja -> Pessoa -> AppUser -> UserRole. Dentro da
    identidade, Pessoa -> AppUser também coincide com ``cell_leadership``.
    Assim revoke/roles não podem observar "sem liderança" e commitar depois que
    outra transação criou uma célula ativa para a mesma pessoa.
    """

    pessoa_id = getattr(app_user, "pessoa_id", None)
    if pessoa_id is not None:
        pessoa_exists = db.execute(
            select(Pessoa.id)
            .where(Pessoa.id == pessoa_id, Pessoa.igreja_id == igreja_id)
            .with_for_update()
        ).scalar_one_or_none()
        if pessoa_exists is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="O acesso possui um vínculo de pessoa inconsistente",
            )
    locked = db.execute(
        select(AppUser)
        .where(AppUser.id == app_user.id, AppUser.igreja_id == igreja_id)
        .with_for_update(of=AppUser)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if locked is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado"
        )
    return locked


def _lock_admin_floor(db: Session, igreja_id: uuid.UUID) -> None:
    """Serializa por igreja antes de recontar e reduzir administradores."""

    locked = db.execute(
        select(Igreja.id)
        .where(Igreja.id == igreja_id)
        .with_for_update()
    ).scalar_one_or_none()
    if locked is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não foi possível validar o piso administrativo da igreja",
        )


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


@router.get("/lookup", response_model=Page[TeamLookupOut])
def list_members_lookup(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(
        require_role(["admin", "pastor", "lider_g12", "lider_consol"])
    ),
) -> Page[TeamLookupOut]:
    """Lista ENXUTA de destinos para o modal de atribuição da fila.

    Usa o mesmo gate da ação ``assign``: admin, pastor, líder G12 e líder de
    consolidação. Usuários que só assumem itens não recebem o diretório do
    tenant. Contagem e paginação já excluem contas sem capacidade para qualquer
    tipo de fila; o cliente percorre as páginas e filtra ``tiposFila`` para o
    item atual, enquanto o POST revalida o tipo. O e-mail (PII) continua omitido.
    """

    igreja_id = uuid.UUID(current_user.igreja_id)
    assignable_roles = {ADMIN_ROLE}
    for roles in TIPO_RESOLVER_ROLES.values():
        assignable_roles.update(roles)
    assignable_user_ids = select(UserRole.user_id).where(
        UserRole.igreja_id == igreja_id,
        UserRole.papel.in_(tuple(sorted(assignable_roles))),
    )
    lookup_filters = (
        AppUser.igreja_id == igreja_id,
        or_(AppUser.status.is_(None), AppUser.status == "ativo"),
        AppUser.id.in_(assignable_user_ids),
    )

    total = db.execute(
        select(func.count()).select_from(AppUser).where(*lookup_filters)
    ).scalar_one()
    users = db.execute(
        select(AppUser)
        .options(joinedload(AppUser.roles))
        .where(*lookup_filters)
        .order_by(AppUser.nome.asc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).unique().scalars().all()

    return Page[TeamLookupOut](
        items=[
            TeamLookupOut(
                usuarioId=str(u.id),
                nome=u.nome,
                email="",  # PII omitida na busca enxuta do painel
                status=None,
                papeis=sorted(role.papel for role in u.roles),
                pessoaId=str(u.pessoa_id) if u.pessoa_id else None,
                tiposFila=sorted(
                    resolvable_tipos(role.papel for role in u.roles)
                ),
            )
            for u in users
        ],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


def _require_inbox_lookup(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Gate the transfer directory with the canonical inbox role policy."""

    if not can_access_inbox(current_user.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para acessar destinos do inbox",
        )
    return current_user


@router.get("/inbox-lookup", response_model=Page[InboxLookupOut])
def list_inbox_transfer_targets(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_require_inbox_lookup),
) -> Page[InboxLookupOut]:
    """List active same-tenant users eligible to receive a conversation.

    This endpoint is deliberately separate from ``/team/lookup``. Restricted
    inbox roles may discover only valid transfer destinations, never the queue
    assignment directory or user e-mails.
    """

    igreja_id = uuid.UUID(current_user.igreja_id)
    eligible_roles = tuple(sorted({ADMIN_ROLE, *INBOX_ROLES}))
    eligible_user_ids = select(UserRole.user_id).where(
        UserRole.igreja_id == igreja_id,
        UserRole.papel.in_(eligible_roles),
    )
    filters = (
        AppUser.igreja_id == igreja_id,
        or_(AppUser.status.is_(None), AppUser.status == "ativo"),
        AppUser.id.in_(eligible_user_ids),
    )

    total = db.execute(
        select(func.count()).select_from(AppUser).where(*filters)
    ).scalar_one()
    users = db.execute(
        select(AppUser)
        .options(joinedload(AppUser.roles))
        .where(*filters)
        .order_by(AppUser.nome.asc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).unique().scalars().all()

    items: list[InboxLookupOut] = []
    for user in users:
        roles = sorted(role.papel for role in user.roles)
        # Defense in depth if storage ever contains a role outside the SQL set.
        if not can_access_inbox(roles):
            continue
        items.append(
            InboxLookupOut(
                usuarioId=str(user.id),
                nome=user.chat_nome or user.nome,
                papeis=roles,
            )
        )

    return Page[InboxLookupOut](
        items=items,
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


@router.post("/invite", response_model=InviteResponse)
def invite_member(
    payload: InviteRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
    identity_db: Session = Depends(get_invite_identity_db),
    mailer: BrevoClient = Depends(get_brevo_client),
    clerk: ClerkClient = Depends(get_clerk_client),
) -> InviteResponse:
    """Cria somente acesso convidado + papel base membro e envia ativação.

    Parte A aponta para Pessoa já cadastrada, mesmo vinculada ou líder. Parte B
    coleta telefone na ativação, mas não escolhe nem altera célula. A Pessoa é
    travada na Parte A para impedir dois convites concorrentes com e-mails
    diferentes de vincularem dois AppUsers ao mesmo cadastro.
    """
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    email = str(payload.email).strip().lower()

    # A sessão dedicada mantém a trava até esta rota terminar e enxerga todos
    # os tenants sem desfazer o pin RLS da sessão principal.
    assert_invite_email_available(identity_db, clerk, email)

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
            select(Pessoa)
            .where(Pessoa.id == pessoa_uuid, Pessoa.igreja_id == igreja_uuid)
            .with_for_update()
        ).scalar_one_or_none()
        if pessoa is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada"
            )
        if pessoa.arquivada_em is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Reative a pessoa antes de conceder acesso ao painel",
            )
        if pessoa.sem_interesse:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Pessoa sem interesse ministerial não pode receber acesso",
            )

        # Uma pessoa não pode ter dois logins.
        linked = db.execute(
            select(AppUser).where(
                AppUser.igreja_id == igreja_uuid,
                AppUser.pessoa_id == pessoa_uuid,
            )
        ).scalar_one_or_none()
        if linked is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Esta pessoa já possui acesso ao painel",
            )

        nome = pessoa.nome
        app_user = AppUser(
            igreja_id=igreja_uuid,
            nome=nome,
            email=email,
            status="convidado",
            pessoa_id=pessoa_uuid,
        )
    else:
        # Parte B — acesso convidado sem Pessoa; ativação coleta o telefone.
        nome = str(payload.nome)  # garantido pelo validador (Parte A ou B)
        app_user = AppUser(
            igreja_id=igreja_uuid,
            nome=nome,
            email=email,
            status="convidado",
            pessoa_id=None,
            celula_pendente_id=None,
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
    """Substitui apenas papéis editáveis e deriva ``lider_celula`` da célula.

    Removing/demoting the last *active* admin of the tenant is blocked (409) so a
    church is never left without an administrator; revoked admins don't count
    toward that floor (mirrors the revoke guard). O cliente deve omitir
    ``lider_celula``: se a Pessoa lidera célula ativa, o backend o preserva ou
    adiciona; se não lidera, tentar incluí-lo manualmente retorna 409 e uma
    gravação explícita remove eventual papel legado divergente.
    """
    igreja_uuid = uuid.UUID(current_user.igreja_id)

    try:
        user_uuid = uuid.UUID(usuario_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado"
        ) from exc

    # Ordem global das mutações de admin/owner: Igreja -> identidade -> papel.
    # Além de serializar o piso do último admin, a trava faz set_dono observar
    # sempre a mesma versão das roles/status deste acesso.
    _lock_admin_floor(db, igreja_uuid)
    app_user = db.execute(
        select(AppUser).where(
            AppUser.id == user_uuid, AppUser.igreja_id == igreja_uuid
        )
    ).scalar_one_or_none()
    if app_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado"
        )
    app_user = _lock_target_identity(
        db, igreja_id=igreja_uuid, app_user=app_user
    )

    requested_roles = set(payload.papeis)
    leads_active_cell = False
    if getattr(app_user, "pessoa_id", None) is not None:
        leads_active_cell = (
            db.execute(
                select(Celula.id)
                .where(
                    Celula.igreja_id == igreja_uuid,
                    Celula.lider_id == app_user.pessoa_id,
                    Celula.ativo.is_(True),
                )
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )
    if leads_active_cell:
        effective_access = resolve_effective_access(
            db,
            igreja_id=igreja_uuid,
            pessoa_id=app_user.pessoa_id,
        )
        if str(effective_access.id) != str(app_user.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A liderança ativa pertence a outro acesso da pessoa",
            )
    if "lider_celula" in requested_roles and not leads_active_cell:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O papel líder de célula é derivado de uma liderança ativa",
        )
    new_roles = requested_roles - {"lider_celula"}
    if leads_active_cell:
        new_roles.add("lider_celula")
    if not new_roles:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O usuário precisa manter ao menos um papel efetivo",
        )
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
        select(UserRole)
        .where(
            UserRole.user_id == user_uuid,
            UserRole.igreja_id == igreja_uuid,
        )
        .with_for_update()
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

    # #4: se o DONO perdeu o papel admin, a igreja fica sem dono — um dono_id
    # velho daria acesso à Assinatura a quem não é mais admin. O master reatribui.
    if ADMIN_ROLE not in new_roles:
        igreja = db.get(Igreja, igreja_uuid)
        if igreja is not None and igreja.dono_id == user_uuid:
            igreja.dono_id = None

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

    if app_user.status != "convidado" or app_user.clerk_user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Somente convites pendentes podem ser reenviados",
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
    igreja_uuid = uuid.UUID(current_user.igreja_id)

    try:
        user_uuid = uuid.UUID(usuario_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado"
        ) from exc

    # Mesma ordem de update_roles e platform_admin: Igreja -> identidade -> papel.
    _lock_admin_floor(db, igreja_uuid)
    app_user = db.execute(
        select(AppUser).where(
            AppUser.id == user_uuid, AppUser.igreja_id == igreja_uuid
        )
    ).scalar_one_or_none()
    if app_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado"
        )

    app_user = _lock_target_identity(
        db, igreja_id=igreja_uuid, app_user=app_user
    )

    if app_user.status == REVOKED_USER_STATUS:
        return RevokeResponse(usuarioId=str(user_uuid), status=REVOKED_USER_STATUS)

    if getattr(app_user, "pessoa_id", None) is not None:
        leads_active = db.execute(
            select(Celula.id)
            .where(
                Celula.igreja_id == igreja_uuid,
                Celula.lider_id == app_user.pessoa_id,
                Celula.ativo.is_(True),
            )
            .limit(1)
        ).scalar_one_or_none()
        if leads_active is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Transfira ou encerre a liderança da célula antes de "
                    "revogar este acesso"
                ),
            )

    active_admins = _active_admin_user_ids(db, igreja_uuid)
    if user_uuid in active_admins and len(active_admins) <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não é possível revogar o último administrador",
        )

    app_user.status = REVOKED_USER_STATUS
    igreja = db.get(Igreja, igreja_uuid)
    if igreja is not None and igreja.dono_id == user_uuid:
        igreja.dono_id = None
    db.commit()

    return RevokeResponse(usuarioId=str(user_uuid), status=REVOKED_USER_STATUS)
