"""Auth, tenant resolution and RBAC dependencies (SPEC 3.3 / F4 / delta-033).

Pipeline per request:
  1. Extract and verify the Clerk session token  -> clerk_user_id.
  2. Resolve the app_user and its igreja_id       -> tenant.
  3. Inject the tenant into the Postgres session   -> RLS effective.
  4. Load accumulated roles (union of user_roles)  -> RBAC.

Authorization is revalidated on every endpoint (igreja_id + role), never
trusted from the client.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppUser, Celula, PlatformAdmin, RolePermission, UserRole
from app.db.rls import set_tenant_context
from app.db.session import get_db
from app.db.tenant_session import mark_cross_tenant, mark_tenant_scoped
from app.domain.permissions import can_access_screen
from app.services.clerk import ClerkAuthError, ClerkClient, ClerkIdentity, get_clerk_client

# Role that is granted access implicitly to every protected resource (F4).
ADMIN_ROLE = "admin"

# Central de Células (decisão 3.1): pastor + admin (implícito via has_any_role)
# aprovam/alteram os campos sensíveis do módulo Células. Espelha CENTRAL_ROLES de
# routers/cells.py; mantido aqui como base de autorização reutilizável pelas
# sprints de Células. `lider_central` dedicado fica para o futuro (fora do MVP).
CENTRAL_ROLES = ["pastor"]

# Igreja statuses that block panel access at login/auth time (US-35) + onboarding
# (M2): uma igreja recém-provisionada nasce 'aguardando_aprovacao' e só libera o
# acesso após o master aprovar (POST /admin/igrejas/{id}/aprovar).
BLOCKING_IGREJA_STATUSES = {"suspensa", "inadimplente", "aguardando_aprovacao"}

# app_users.status of a member whose access was revoked (RF-04 / US-03). Blocks
# panel access on every request even while a previously issued session JWT is
# still unexpired. Single source of truth, reused by the team and auth routers.
REVOKED_USER_STATUS = "revogado"

# SEC-3A / MEDIO-002: small tolerance for clock drift between whichever process
# minted the session JWT and whichever process recorded the password change —
# a token issued within this window just before `password_changed_at` is still
# accepted, so ordinary clock skew never flakes a legitimate fresh login.
_PASSWORD_CHANGE_CLOCK_SKEW = timedelta(seconds=5)

# Same generic message as an invalid/expired token — a session invalidated by
# a password change must not be distinguishable from any other bad session.
_STALE_SESSION_DETAIL = "Sessão inválida ou expirada"


@dataclass(frozen=True)
class CurrentUser:
    """Authenticated principal resolved for the current request."""

    app_user_id: str
    clerk_user_id: str
    igreja_id: str
    email: str
    nome: str
    # Nome de exibição no chat (assinatura). None = usa `nome`.
    chat_nome: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)
    # #4: é o DONO (admin principal) da igreja? Só o dono gerencia a Assinatura.
    is_owner: bool = False
    # Missão 4 (branding): nome + logo da igreja para o bootstrap do shell
    # (/auth/me). O nome é o fallback textual quando não há logo.
    igreja_nome: str | None = None
    igreja_logo_path: str | None = None

    def has_role(self, role: str) -> bool:
        """True if the user holds `role` or is an admin (implicit access)."""
        return ADMIN_ROLE in self.roles or role in self.roles

    def has_any_role(self, roles: list[str]) -> bool:
        if ADMIN_ROLE in self.roles:
            return True
        return any(r in self.roles for r in roles)


def _extract_bearer_token(authorization: str | None) -> str:
    """Parse `Authorization: Bearer <token>` or raise 401."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cabeçalho de autorização inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return parts[1].strip()


def _reject_session_predating_password_change(
    app_user: AppUser, identity: ClerkIdentity
) -> None:
    """401 if this session JWT was issued before the account's last password
    change/reset (SEC-3A / MEDIO-002).

    `password_changed_at` NULL means the account has never gone through
    change-password/reset-password since this field shipped — every existing
    session stays valid, so the fix does not log out the whole user base on
    deploy. Once set, any token whose `iat` is more than
    `_PASSWORD_CHANGE_CLOCK_SKEW` earlier is rejected with the same generic
    401 as any other invalid session (never reveals *why* it was rejected).
    """
    changed_at = app_user.password_changed_at
    if changed_at is None:
        return
    issued_at_raw = identity.claims.get("iat")
    if issued_at_raw is None:
        # A PastorAI-minted token always carries iat; its absence means the
        # token is malformed/foreign — fail closed like any other bad session.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_STALE_SESSION_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        )
    issued_at = datetime.fromtimestamp(float(issued_at_raw), tz=timezone.utc)
    if issued_at < changed_at - _PASSWORD_CHANGE_CLOCK_SKEW:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_STALE_SESSION_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    clerk: ClerkClient = Depends(get_clerk_client),
) -> CurrentUser:
    """Authenticate the request and resolve tenant + accumulated roles.

    - 401 when the Clerk token is missing or invalid.
    - 403 when the Clerk identity has no linked app_user (US-02 / F1).
    - 403 (billing) when the igreja is suspended/delinquent (US-35).
    """
    token = _extract_bearer_token(authorization)

    try:
        identity = clerk.verify_session_token(token)
    except ClerkAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão inválida ou expirada",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # Ovo-e-galinha (OQ#1, opção A documentada): a resolução do app_user precisa
    # de uma sessão escopada, mas o igreja_id só é conhecido DEPOIS de resolvê-lo.
    # Semeamos o escopo via o `sub` do Clerk APENAS para esta query de resolução
    # (current_igreja_id() deriva o tenant do claim). Assim que o igreja_id for
    # conhecido, promovemos a sessão ao seam com mark_tenant_scoped e o GUC passa
    # a governar — a sessão final nunca fica não-escopada.
    set_tenant_context(db, identity.clerk_user_id)

    app_user = db.execute(
        select(AppUser).where(AppUser.clerk_user_id == identity.clerk_user_id)
    ).scalar_one_or_none()

    if app_user is None:
        # Authenticated at Clerk but not linked to any igreja.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sua conta não está vinculada a nenhuma igreja",
        )

    if app_user.status == REVOKED_USER_STATUS:
        # Access revoked by an admin (RF-04): block even on a still-valid JWT.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seu acesso foi revogado. Contate o administrador da igreja.",
        )

    # SEC-3A / MEDIO-002: a session minted before the last password change is
    # a stale credential — reject it like any other invalid session.
    _reject_session_predating_password_change(app_user, identity)

    igreja_status = app_user.igreja.status if app_user.igreja else None
    if igreja_status in BLOCKING_IGREJA_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "billing_blocked",
                "message": "Acesso bloqueado por pendência de assinatura",
                "igrejaStatus": igreja_status,
            },
        )

    roles = db.execute(
        select(UserRole.papel).where(UserRole.user_id == app_user.id)
    ).scalars().all()

    # #4: dono = quando o app_user é o dono_id da própria igreja.
    dono_id = app_user.igreja.dono_id if app_user.igreja else None
    is_owner = dono_id is not None and dono_id == app_user.id

    igreja_id = str(app_user.igreja_id)

    # Seam profundo de tenant (PR2 D2/D3 → PR3-A): a partir daqui a sessão é
    # OFICIALMENTE tenant-scoped no igreja_id resolvido. mark_tenant_scoped grava
    # o pin em session.info — o listener after_begin (D2) reaplica o escopo em
    # TODA transação futura desta sessão, inclusive leituras pós-commit — e
    # reafirma o escopo agora. current_igreja_id() prioriza o GUC, então daqui em
    # diante o GUC (não mais a semente via `sub`) governa o tenant efetivo, que
    # permanece o MESMO. actor_sub/actor_role viajam só como metadado de auditoria.
    mark_tenant_scoped(
        db,
        igreja_id,
        actor_sub=identity.clerk_user_id,
        actor_role=(",".join(sorted(roles)) or None),
        source="http",
    )

    return CurrentUser(
        app_user_id=str(app_user.id),
        clerk_user_id=identity.clerk_user_id,
        igreja_id=igreja_id,
        email=app_user.email,
        nome=app_user.nome,
        chat_nome=app_user.chat_nome,
        roles=frozenset(roles),
        is_owner=is_owner,
        igreja_nome=app_user.igreja.nome if app_user.igreja else None,
        igreja_logo_path=app_user.igreja.logo_path if app_user.igreja else None,
    )


def require_role(roles: list[str]):
    """Dependency factory enforcing accumulated-role authorization (F4).

    `require_role(["admin"])` blocks (403) users without the role; admins
    always pass (implicit access). Roles are evaluated as the union of the
    user's user_roles, revalidated here on every request.
    """

    def _checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not current_user.has_any_role(roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para acessar este recurso",
            )
        return current_user

    return _checker


def require_central(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Dependency: só a Central de Células (pastor + admin implícito) passa (403).

    Igual em espírito a ``require_role(CENTRAL_ROLES)``, exposto com nome próprio
    porque a Central é um conceito de domínio recorrente nas telas de Células. O
    papel é reavaliado a cada request a partir do contexto autenticado — nunca do
    payload do cliente.
    """
    if not current_user.has_any_role(CENTRAL_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ação restrita à Central de Células",
        )
    return current_user


def resolve_actor_pessoa_id(db: Session, current_user: CurrentUser) -> str | None:
    """Resolve a Pessoa vinculada ao app_user autenticado (ou None).

    Base para as checagens de hierarquia/ownership de célula: o vínculo
    app_user→pessoa é a ponte entre a identidade Clerk e a árvore de liderança
    (``pessoas.lider_id`` / ``celulas.lider_id``). igreja_id/pessoa derivam sempre
    do contexto autenticado.
    """
    pessoa_id = db.execute(
        select(AppUser.pessoa_id).where(
            AppUser.id == uuid.UUID(current_user.app_user_id)
        )
    ).scalar_one_or_none()
    return str(pessoa_id) if pessoa_id else None


def get_current_cell_for_leader(
    db: Session, current_user: CurrentUser, cell_id: str
) -> Celula:
    """Resolve a célula ``cell_id`` exigindo que o usuário seja seu LÍDER.

    "É líder desta célula" deriva SEMPRE de ``celulas.lider_id`` ligado à Pessoa
    do app_user autenticado (E9/6.6) — nunca de flag do cliente nem de
    ``celula_membro.papel``. O ``igreja_id`` vem do contexto autenticado (RLS +
    filtro explícito de tenant, defesa em profundidade).

    Um recurso de OUTRA célula/igreja, um id malformado, uma célula sem líder ou
    liderada por outra pessoa resultam TODOS no mesmo 404 — não se distingue
    "não existe" de "não é sua", para não vazar a existência do recurso.
    """
    not_found = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
    )
    try:
        cell_uuid = uuid.UUID(cell_id)
    except (ValueError, AttributeError) as exc:
        raise not_found from exc

    cell = db.execute(
        select(Celula).where(
            Celula.id == cell_uuid,
            Celula.igreja_id == uuid.UUID(current_user.igreja_id),
        )
    ).scalar_one_or_none()
    if cell is None or cell.lider_id is None:
        raise not_found

    actor_pessoa = resolve_actor_pessoa_id(db, current_user)
    if actor_pessoa is None or str(cell.lider_id) != actor_pessoa:
        raise not_found
    return cell


def require_owner(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Só o DONO (admin principal) da igreja passa — gating da Assinatura (#4).

    Diferente de require_role(['admin']): admin NÃO basta. Outros admins (não
    donos) recebem 403. Se a igreja está sem dono (dono_id NULL), ninguém passa
    até o master reatribuir o dono pelo console.
    """
    if not current_user.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o dono da igreja pode acessar a assinatura",
        )
    return current_user


def require_screen(screen: str):
    """Dependency factory: autoriza pela MATRIZ de telas (role_permissions) que o
    admin edita em #permissoes — não por listas fixas de papéis (delta-010 / M0c).

    Admin tem acesso implícito. Para os demais, libera se ALGUM papel do usuário
    concede ``screen`` na matriz do tenant; quando a igreja nunca customizou a
    matriz (sem linhas), cai nos defaults (app/domain/permissions.py). 403 caso
    contrário. ``dashboard`` é sempre liberado.

    Lê role_permissions na MESMA sessão (RLS já escopada por get_current_user),
    então a matriz é a do próprio tenant — um admin não afeta outra igreja.
    """

    def _checker(
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if ADMIN_ROLE in current_user.roles:
            return current_user
        rows = db.execute(
            select(RolePermission.papel, RolePermission.tela)
        ).all()
        tenant_matrix: dict[str, set[str]] = {}
        for papel, tela in rows:
            tenant_matrix.setdefault(papel, set()).add(tela)
        if not can_access_screen(current_user.roles, screen, tenant_matrix):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem acesso a esta tela",
            )
        return current_user

    return _checker


# ---------------------------------------------------------------------------
# Platform plane (Super-Admin / console multi-tenant — Onda 1, US-42/43)
# ---------------------------------------------------------------------------
# Mensagem genérica e única: não revela se a identidade existe nem por que foi
# negada (não vaza a existência da allowlist de plataforma).
_PLATFORM_DENIED = "Acesso restrito à administração da plataforma"


@dataclass(frozen=True)
class PlatformAdminUser:
    """A platform-level principal (SaaS provider) authorized cross-tenant."""

    app_user_id: str
    clerk_user_id: str
    email: str
    nome: str


def get_platform_admin(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    clerk: ClerkClient = Depends(get_clerk_client),
) -> PlatformAdminUser:
    """Authorize a Super-Admin request — cross-tenant administration plane.

    A deliberately PARALLEL pipeline to ``get_current_user``, with two crucial
    differences:

      1. It does NOT scope the session to a tenant; instead it marks the
         session cross-tenant EXPLICITLY (``mark_cross_tenant``, D4). The
         session therefore keeps the connection role (BYPASSRLS), so the
         platform admin can see and manage every igreja, and the ``after_begin``
         listener never re-scopes it. Scoping it would defeat the console; the
         explicit mark makes the cross-tenant access greppable and auditable.
      2. It is NOT subject to the per-tenant billing gate (a suspended home
         church must not lock the provider out of the platform console).

    Authorization is the ``platform_admins`` allowlist: the verified identity
    must resolve to an app_user that has a row there. 401 on a bad/missing
    token; 403 for any authenticated identity that is not a platform admin.
    """
    token = _extract_bearer_token(authorization)

    try:
        identity = clerk.verify_session_token(token)
    except ClerkAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão inválida ou expirada",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # Saída cross-tenant EXPLÍCITA e nomeada (D4): sem escopo de tenant, o
    # listener after_begin (D2) NÃO reaplica escopo algum e a sessão segue no
    # papel de conexão (BYPASSRLS) — é o que torna o console cross-tenant. Sem
    # mudança de comportamento em relação ao "simplesmente não chamar
    # set_tenant_context": marcar apenas torna o acesso cross-tenant greppável
    # pela API nomeada e provável pelo listener (que respeita a flag cross_tenant).
    mark_cross_tenant(db, actor_sub=identity.clerk_user_id, source="platform_admin")

    app_user = db.execute(
        select(AppUser).where(AppUser.clerk_user_id == identity.clerk_user_id)
    ).scalar_one_or_none()
    if app_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_PLATFORM_DENIED
        )

    # SEC-3A / MEDIO-002: same stale-session rejection as the tenant plane.
    _reject_session_predating_password_change(app_user, identity)

    is_platform_admin = db.execute(
        select(PlatformAdmin.id).where(PlatformAdmin.app_user_id == app_user.id)
    ).scalar_one_or_none()
    if is_platform_admin is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_PLATFORM_DENIED
        )

    return PlatformAdminUser(
        app_user_id=str(app_user.id),
        clerk_user_id=identity.clerk_user_id,
        email=app_user.email,
        nome=app_user.nome,
    )
