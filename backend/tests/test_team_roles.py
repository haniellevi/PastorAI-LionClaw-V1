"""Tests for the last-active-admin guard on PUT /team/{usuario_id}/roles.

update_roles blocks demoting/removing the last admin (409) so a tenant never
loses its administrator. Since access revocation (status='revogado') landed, that
count must exclude revoked admins: a revoked admin keeps its admin user_role but
can no longer administer anything. The guard therefore uses
_active_admin_user_ids (JOIN app_users, status != 'revogado') — the same helper
the revoke endpoint uses — instead of a raw admin count.

Like the other router tests, this runs offline against a fake session
(conftest.FakeSession style). _RolesSession models the admin roster *with status*
and applies the revoked filter only to the active-admin query (the one that JOINs
app_users), so a regression back to the unfiltered count would surface here as a
missing 409.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser
from app.db.session import get_db
from app.deps import REVOKED_USER_STATUS, CurrentUser, get_current_user

_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_ADMIN_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_ADMIN_B = uuid.UUID("00000000-0000-0000-0000-0000000000a2")
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


class _RolesSession:
    """Routes update_roles' selects: target AppUser, admin ids, current roles.

    `admins` is a list of (user_id, status). The active-admin query JOINs
    app_users to drop revoked accounts; we mirror that by filtering on status
    only for that query (detected by the app_users join in the compiled SQL).
    The plain projection — were the guard to regress to it — would count every
    admin and the revoked-peer case would stop raising 409.
    """

    def __init__(self, *, target, admins, current_roles=()) -> None:
        self.target = target
        self.admins = list(admins)
        self.current_roles = list(current_roles)
        self.committed = False
        self.deleted: list = []
        self.added: list = []

    def execute(self, statement, params=None) -> _Result:
        descriptions = getattr(statement, "column_descriptions", None)
        if not descriptions:
            # text() clause from set_tenant_context (RLS GUC / SET LOCAL ROLE).
            return _Result()
        first = descriptions[0]
        if first.get("entity") is AppUser:
            return _Result(scalar=self.target)
        if first.get("name") == "user_id":
            if "app_users" in str(statement):  # active-admin query: drop revoked
                ids = [uid for uid, st in self.admins if st != REVOKED_USER_STATUS]
            else:  # unfiltered admin count (pre-fix behaviour)
                ids = [uid for uid, _ in self.admins]
            return _Result(scalars_list=ids)
        # select(UserRole) -> the target's current roles
        return _Result(scalars_list=self.current_roles)

    def delete(self, obj) -> None:
        self.deleted.append(obj)

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


def _admin(roles=("admin",)) -> CurrentUser:
    return CurrentUser(
        app_user_id=str(_ADMIN_A),
        clerk_user_id="clerk_admin",
        igreja_id=_IGREJA_ID,
        email="admin@igreja.com.br",
        nome="Admin",
        roles=frozenset(roles),
    )


def _target(uid: uuid.UUID, *, status="ativo"):
    return SimpleNamespace(
        id=uid,
        igreja_id=uuid.UUID(_IGREJA_ID),
        clerk_user_id="clerk_target",
        status=status,
    )


def _client(app, *, session, current_user) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


# ---------------------------------------------------------------------------
# Last-active-admin guard (corner case introduced by access revocation)
# ---------------------------------------------------------------------------
def test_demote_last_active_admin_with_revoked_peer_is_blocked(app) -> None:
    # Tenant has two admins but one is revoked; demoting the only active admin
    # would leave zero usable administrators, so it must be blocked (409).
    target = _target(_ADMIN_A, status="ativo")
    session = _RolesSession(
        target=target,
        admins=[(_ADMIN_A, "ativo"), (_ADMIN_B, REVOKED_USER_STATUS)],
    )
    client = _client(app, session=session, current_user=_admin())

    resp = client.put(
        f"/team/{_ADMIN_A}/roles", json={"papeis": ["membro"]}, headers=_AUTH
    )

    assert resp.status_code == 409
    assert "último administrador" in resp.json()["detail"]
    assert session.committed is False


def test_demote_admin_with_another_active_admin_is_allowed(app) -> None:
    # Two active admins: demoting one keeps the tenant covered, so it succeeds.
    # Guards against a false 409 (proves the guard discriminates on the count).
    target = _target(_ADMIN_A, status="ativo")
    session = _RolesSession(
        target=target,
        admins=[(_ADMIN_A, "ativo"), (_ADMIN_B, "ativo")],
        current_roles=[SimpleNamespace(papel="admin")],
    )
    client = _client(app, session=session, current_user=_admin())

    resp = client.put(
        f"/team/{_ADMIN_A}/roles", json={"papeis": ["membro"]}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert resp.json() == {"usuarioId": str(_ADMIN_A), "papeis": ["membro"]}
    assert session.committed is True
