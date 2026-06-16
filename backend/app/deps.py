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

from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppUser, PlatformAdmin, RolePermission, UserRole
from app.db.rls import set_tenant_context
from app.db.session import get_db
from app.domain.permissions import can_access_screen
from app.services.clerk import ClerkAuthError, ClerkClient, get_clerk_client

# Role that is granted access implicitly to every protected resource (F4).
ADMIN_ROLE = "admin"

# Igreja statuses that block panel access at login/auth time (US-35).
BLOCKING_IGREJA_STATUSES = {"suspensa", "inadimplente"}


@dataclass(frozen=True)
class CurrentUser:
    """Authenticated principal resolved for the current request."""

    app_user_id: str
    clerk_user_id: str
    igreja_id: str
    email: str
    nome: str
    roles: frozenset[str] = field(default_factory=frozenset)

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

    # Inject tenant claim so RLS-backed queries are scoped automatically.
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

    return CurrentUser(
        app_user_id=str(app_user.id),
        clerk_user_id=identity.clerk_user_id,
        igreja_id=str(app_user.igreja_id),
        email=app_user.email,
        nome=app_user.nome,
        roles=frozenset(roles),
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

      1. It does NOT call ``set_tenant_context``. The session therefore keeps
         the connection role (BYPASSRLS), so the platform admin can see and
         manage every igreja. Calling it would scope every query to a single
         tenant and defeat the purpose of the console.
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

    # NOTE: intentionally no set_tenant_context — see docstring. Running as the
    # BYPASSRLS connection role is what makes the lookups (and the console)
    # cross-tenant.
    app_user = db.execute(
        select(AppUser).where(AppUser.clerk_user_id == identity.clerk_user_id)
    ).scalar_one_or_none()
    if app_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_PLATFORM_DENIED
        )

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
