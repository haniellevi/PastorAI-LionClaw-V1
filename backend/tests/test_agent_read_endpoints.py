"""Read endpoints of the agent router (GET credential/config/crons).

These back the "reflect what's saved on open" behaviour of the #agente screen:
auth/role gating plus the empty-state happy paths (no credential / not
configured). The key is never returned (RNF-03).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}


def _client(app, roles: list[str] | None = None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: FakeSession(
        app_user=make_app_user(), roles=roles or ["admin"]
    )
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


# ---- auth gating ----------------------------------------------------------
def test_get_credential_requires_auth(app) -> None:
    assert _client(app).get("/agent/credential").status_code == 401


def test_get_agent_config_requires_auth(app) -> None:
    assert _client(app).get("/agent/config").status_code == 401


def test_get_crons_requires_auth(app) -> None:
    assert _client(app).get("/agent/crons").status_code == 401


# ---- admin-only (config screens) ------------------------------------------
def test_get_credential_forbidden_for_non_admin(app) -> None:
    resp = _client(app, roles=["lider_celula"]).get("/agent/credential", headers=_AUTH)
    assert resp.status_code == 403


# ---- empty-state happy paths (key never returned) -------------------------
def test_get_credential_reports_none_when_unset(app) -> None:
    resp = _client(app).get("/agent/credential", headers=_AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"status": "none", "provedor": None}


def test_get_agent_config_reports_unconfigured(app) -> None:
    resp = _client(app).get("/agent/config", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["ativo"] is False
