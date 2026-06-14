"""Edge tests for the panel assistant router (POST /assistant/message — O5).

Covers the HTTP contract that runs before/around the service: auth gating (401),
input validation (422), cross-tenant rejection (403) and a success path (200)
that degrades to the deterministic reply when no LLM credential is configured.
The session is an in-memory fake; no DB or network is touched.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.models import AppUser, LlmCredential, RolePermission, UserRole
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_TENANT = "00000000-0000-0000-0000-000000000001"  # matches make_app_user igreja


class _Result:
    """Fake execute() result exposing the access shapes the code uses."""

    def __init__(self, *, scalar=None, rows=None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return _Scalars(self._rows)

    def all(self) -> list:
        return list(self._rows)


class _Scalars:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return list(self._items)


class FakeAssistantSession:
    """Routes execute() by selected entity for the assistant flow."""

    def __init__(
        self,
        *,
        app_user=None,
        roles: list[str] | None = None,
        role_permissions: list[tuple[str, str]] | None = None,
        credential: LlmCredential | None = None,
    ) -> None:
        self.app_user = app_user
        self.roles = roles or []
        self.role_permissions = role_permissions or []
        self.credential = credential

    def execute(self, statement, params=None) -> _Result:
        descriptions = getattr(statement, "column_descriptions", None)
        if not descriptions:
            # set_config(...) text clause for the RLS tenant context.
            return _Result()
        entity = descriptions[0].get("entity")
        if entity is AppUser:
            return _Result(scalar=self.app_user)
        if entity is UserRole:
            return _Result(rows=self.roles)
        if entity is RolePermission:
            return _Result(rows=self.role_permissions)
        if entity is LlmCredential:
            return _Result(scalar=self.credential)
        return _Result()

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


def _client(app, session: FakeAssistantSession) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


# ---- auth gating ----------------------------------------------------------
def test_assistant_requires_auth(app) -> None:
    client = _client(app, FakeAssistantSession(app_user=make_app_user()))
    resp = client.post(
        "/assistant/message", json={"tenantId": _TENANT, "texto": "olá"}
    )
    assert resp.status_code == 401


# ---- input validation -----------------------------------------------------
def test_assistant_rejects_blank_texto(app) -> None:
    client = _client(app, FakeAssistantSession(app_user=make_app_user(), roles=["admin"]))
    resp = client.post(
        "/assistant/message",
        json={"tenantId": _TENANT, "texto": "   "},
        headers=_AUTH,
    )
    assert resp.status_code == 422


def test_assistant_requires_tenant_id(app) -> None:
    client = _client(app, FakeAssistantSession(app_user=make_app_user(), roles=["admin"]))
    resp = client.post(
        "/assistant/message", json={"texto": "olá"}, headers=_AUTH
    )
    assert resp.status_code == 422


# ---- cross-tenant rejection (never trust the body) ------------------------
def test_assistant_rejects_tenant_mismatch(app) -> None:
    client = _client(app, FakeAssistantSession(app_user=make_app_user(), roles=["admin"]))
    resp = client.post(
        "/assistant/message",
        json={"tenantId": "99999999-9999-9999-9999-999999999999", "texto": "olá"},
        headers=_AUTH,
    )
    assert resp.status_code == 403


# ---- success path (deterministic fallback, no LLM credential) -------------
def test_assistant_replies_with_role_screens(app) -> None:
    session = FakeAssistantSession(
        app_user=make_app_user(),
        roles=["lider_celula"],
        role_permissions=[("lider_celula", "central-celula")],
        credential=None,  # no validated+active credential -> fallback reply
    )
    client = _client(app, session)
    resp = client.post(
        "/assistant/message",
        json={"tenantId": _TENANT, "texto": "preciso ver o relatorio da celula"},
        headers=_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resposta"]
    # central-celula is allowed for the role; locked/forbidden screens never leak.
    assert "central-celula" in body["telasSugeridas"]
    assert "permissoes" not in body["telasSugeridas"]


def test_assistant_papeis_cannot_widen_access(app) -> None:
    # Client claims 'admin' but the real role is only lider_celula: no widening.
    session = FakeAssistantSession(
        app_user=make_app_user(),
        roles=["lider_celula"],
        role_permissions=[("lider_celula", "central-celula")],
        credential=None,
    )
    client = _client(app, session)
    resp = client.post(
        "/assistant/message",
        json={
            "tenantId": _TENANT,
            "papeis": ["admin"],
            "texto": "quero abrir permissoes e gerentes",
        },
        headers=_AUTH,
    )
    assert resp.status_code == 200
    telas = resp.json()["telasSugeridas"]
    assert "permissoes" not in telas
    assert "gerentes" not in telas
