"""Synthetic regressions for the shell's single authenticated bootstrap."""

import inspect

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.routers.agent_identity import confirm_identity
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user
from tests.test_setup_checklist import SetupSession, _igreja, _wire


def test_bootstrap_matches_profile_and_effective_matrix(app):
    session = FakeSession(app_user=make_app_user(), roles=["lider_celula"])
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    client = TestClient(app)
    headers = {"Authorization": "Bearer good"}
    profile = client.get("/auth/me", headers=headers).json()
    response = client.get("/auth/bootstrap", headers=headers)
    assert response.status_code == 200
    assert response.json()["user"] == profile
    assert "central-celula" not in response.json()["permissions"]["matriz"]["lider_celula"]
    assert "dashboard" in response.json()["permissions"]["matriz"]["lider_celula"]


def test_setup_reads_configuration_in_one_projection(app):
    session = SetupSession(igreja=_igreja())
    original = session.execute
    statements = []

    def capture(statement, params=None):
        statements.append(statement)
        return original(statement, params)

    session.execute = capture
    response = _wire(app, session=session).get(
        "/setup/checklist", headers={"Authorization": "Bearer good"}
    )
    assert response.status_code == 200
    configuration = [s for s in statements if "setup_identity" in str(s)]
    assert len(configuration) == 1


def test_identity_database_work_runs_in_sync_path_operation():
    assert not inspect.iscoroutinefunction(confirm_identity)
