"""Maintenance bootstrap contracts, using synthetic identities and SQL doubles."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings

from app.db.rls import set_tenant_context, set_tenant_context_for_igreja
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

AUTH = {"Authorization": "Bearer good"}


def client_for(app, session):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def test_maintenance_me_uses_three_database_statements(app):
    session = FakeSession(app_user=make_app_user(), roles=["pastor"])
    response = client_for(app, session).get("/auth/me", headers=AUTH)
    assert response.status_code == 200
    assert session.execute_count == 3


def test_maintenance_bootstrap_resolves_user_and_permissions_once(app):
    session = FakeSession(app_user=make_app_user(), roles=["pastor"])
    response = client_for(app, session).get("/auth/bootstrap", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["churchId"] == str(session.app_user.igreja_id)
    assert "dashboard" in body["permissions"]["matriz"]["pastor"]
    assert session.execute_count == 4


def test_tenant_helpers_send_role_and_claim_together():
    class Session:
        def __init__(self):
            self.calls = []
        def execute(self, sql, params=None):
            self.calls.append((str(sql), params))

    for apply, value in ((set_tenant_context, "synthetic-clerk"),
                         (set_tenant_context_for_igreja, "00000000-0000-0000-0000-000000000001")):
        session = Session()
        apply(session, value)
        assert len(session.calls) == 1
        assert "set_config('role', 'authenticated', true)" in session.calls[0][0]
        assert value not in session.calls[0][0]


def test_bootstrap_rejects_revoked_identity(app):
    session = FakeSession(app_user=make_app_user(status="revogado"), roles=["pastor"])
    response = client_for(app, session).get("/auth/bootstrap", headers=AUTH)
    assert response.status_code == 403
    assert "permissions" not in response.json()


def test_bootstrap_rejects_invalid_token(app):
    session = FakeSession(app_user=make_app_user(), roles=["admin"])
    client = client_for(app, session)
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk(raise_verify=True)
    response = client.get("/auth/bootstrap", headers=AUTH)
    assert response.status_code == 401
    assert session.execute_count == 0


def test_bootstrap_preserves_permission_denials_and_tenant_filter(app):
    session = FakeSession(
        app_user=make_app_user(), roles=["lider_celula"],
        role_permissions=[("lider_celula", "dashboard"),
                          ("lider_celula", "minha-celula"),
                          ("lider_celula", "central-celula")],
    )
    response = client_for(app, session).get("/auth/bootstrap", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["permissions"]["matriz"]["lider_celula"] == ["dashboard", "minha-celula"]
    permission_query = session.executed_statements[-1]
    assert str(session.app_user.igreja_id) in {str(value) for value in permission_query.compile().params.values()}


def test_bootstrap_has_no_anonymous_fallback(app):
    session = FakeSession(app_user=make_app_user(), roles=["admin"])
    response = client_for(app, session).get("/auth/bootstrap")
    assert response.status_code == 401
    assert session.execute_count == 0


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan")])
def test_pool_idle_configuration_rejects_invalid_threshold(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, db_pool_ping_idle_seconds=value)
