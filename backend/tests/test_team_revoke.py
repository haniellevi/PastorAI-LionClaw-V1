"""Tests for team access revocation (RF-04 / US-03): DELETE /team/{usuario_id}.

The endpoint marks app_users.status='revogado' (soft revoke — preserves the row
for auditability), guards the last *active* admin (409), and is tenant-isolated:
a cross-tenant id is invisible under RLS and surfaces as 404 (S4 — never reveal
existence). That a revoked user is then blocked at auth time is covered by the
deps/auth tests.

The endpoint runs two queries (the target AppUser, then the active-admin ids);
`_RevokeSession` routes them by entity so the logic can be exercised offline,
the same approach the existing router tests use (conftest.FakeSession).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_TARGET_ID = "00000000-0000-0000-0000-0000000000b1"
_ADMIN_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_ADMIN_B = uuid.UUID("00000000-0000-0000-0000-0000000000a2")
_OTHER_ADMIN = uuid.UUID("00000000-0000-0000-0000-0000000000c9")
_AUTH = {"Authorization": "Bearer good"}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _Result:
    def __init__(self, *, scalar=None, scalars_list=None) -> None:
        self._scalar = scalar
        self._scalars_list = scalars_list or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars_list))


class _RevokeSession:
    """Routes the endpoint's two selects: target AppUser, then active-admin ids."""

    def __init__(self, *, target=None, admin_ids=None) -> None:
        self.target = target
        self.admin_ids = admin_ids or []
        self.committed = False

    def execute(self, statement, params=None) -> _Result:
        descriptions = getattr(statement, "column_descriptions", None)
        if not descriptions:
            # text() clause from set_tenant_context (RLS GUC / SET LOCAL ROLE).
            return _Result()
        if descriptions[0].get("entity") is AppUser:
            return _Result(scalar=self.target)
        # UserRole.user_id projection (active admins).
        return _Result(scalars_list=self.admin_ids)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


def _admin(roles=("admin",)) -> CurrentUser:
    return CurrentUser(
        app_user_id="00000000-0000-0000-0000-0000000000a1",
        clerk_user_id="clerk_admin",
        igreja_id=_IGREJA_ID,
        email="admin@igreja.com.br",
        nome="Admin",
        roles=frozenset(roles),
    )


def _target(*, status="ativo", uid: str = _TARGET_ID):
    return SimpleNamespace(
        id=uuid.UUID(uid),
        igreja_id=uuid.UUID(_IGREJA_ID),
        clerk_user_id="clerk_target",
        status=status,
    )


def _client(app, *, session, current_user) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_revoke_member_marks_status_revogado(app) -> None:
    target = _target(status="ativo")
    # Target is not an admin; some other admin keeps the tenant covered.
    session = _RevokeSession(target=target, admin_ids=[_OTHER_ADMIN])
    client = _client(app, session=session, current_user=_admin())

    resp = client.delete(f"/team/{_TARGET_ID}", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json() == {"usuarioId": _TARGET_ID, "status": "revogado"}
    assert target.status == "revogado"
    assert session.committed is True


def test_revoke_non_last_admin_is_allowed(app) -> None:
    # Revoking one admin while another active admin remains is fine.
    target = _target(status="ativo", uid=str(_ADMIN_A))
    session = _RevokeSession(target=target, admin_ids=[_ADMIN_A, _ADMIN_B])
    client = _client(app, session=session, current_user=_admin())

    resp = client.delete(f"/team/{_ADMIN_A}", headers=_AUTH)

    assert resp.status_code == 200
    assert target.status == "revogado"
    assert session.committed is True


# ---------------------------------------------------------------------------
# Last-admin guard
# ---------------------------------------------------------------------------
def test_revoke_last_active_admin_is_blocked(app) -> None:
    target = _target(status="ativo", uid=str(_ADMIN_A))
    session = _RevokeSession(target=target, admin_ids=[_ADMIN_A])
    client = _client(app, session=session, current_user=_admin())

    resp = client.delete(f"/team/{_ADMIN_A}", headers=_AUTH)

    assert resp.status_code == 409
    assert "último administrador" in resp.json()["detail"]
    assert target.status == "ativo"  # unchanged
    assert session.committed is False


# ---------------------------------------------------------------------------
# Tenant isolation (S4): cross-tenant id is invisible under RLS -> 404
# ---------------------------------------------------------------------------
def test_revoke_cross_tenant_returns_404(app) -> None:
    # RLS hides the other tenant's row, so the select resolves to None.
    session = _RevokeSession(target=None)
    client = _client(app, session=session, current_user=_admin())

    resp = client.delete(
        "/team/00000000-0000-0000-0000-0000000000ff", headers=_AUTH
    )

    assert resp.status_code == 404
    assert session.committed is False


def test_revoke_invalid_uuid_returns_404(app) -> None:
    session = _RevokeSession(target=_target())
    client = _client(app, session=session, current_user=_admin())

    resp = client.delete("/team/not-a-uuid", headers=_AUTH)

    assert resp.status_code == 404
    assert session.committed is False


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------
def test_revoke_already_revoked_is_idempotent(app) -> None:
    target = _target(status="revogado")
    session = _RevokeSession(target=target)
    client = _client(app, session=session, current_user=_admin())

    resp = client.delete(f"/team/{_TARGET_ID}", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["status"] == "revogado"
    assert session.committed is False  # no write on a no-op


# ---------------------------------------------------------------------------
# Authorization gating
# ---------------------------------------------------------------------------
def test_revoke_requires_admin_role(app) -> None:
    session = _RevokeSession(target=_target())
    client = _client(app, session=session, current_user=_admin(roles=("lider_celula",)))

    resp = client.delete(f"/team/{_TARGET_ID}", headers=_AUTH)

    assert resp.status_code == 403
    assert session.committed is False


def test_revoke_requires_auth(app) -> None:
    app.dependency_overrides[get_db] = lambda: FakeSession(
        app_user=make_app_user(), roles=["admin"]
    )
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    client = TestClient(app)

    # No Authorization header -> 401 before any tenant work.
    assert client.delete(f"/team/{_TARGET_ID}").status_code == 401
