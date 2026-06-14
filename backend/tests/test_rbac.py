"""Tests for Clerk auth, tenant resolution and require_role RBAC."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.deps import CurrentUser, get_current_user, require_role
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user


@pytest.fixture
def protected_app():
    """A tiny app exposing routes guarded by get_current_user/require_role."""
    app = FastAPI()

    @app.get("/me")
    def me(user: CurrentUser = Depends(get_current_user)) -> dict:
        return {"igrejaId": user.igreja_id, "roles": sorted(user.roles)}

    @app.get("/admin-only")
    def admin_only(user: CurrentUser = Depends(require_role(["admin"]))) -> dict:
        return {"ok": True}

    @app.get("/pastor-area")
    def pastor_area(user: CurrentUser = Depends(require_role(["pastor"]))) -> dict:
        return {"ok": True}

    return app


def _wire(app, *, session: FakeSession, clerk: FakeClerk) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    return TestClient(app)


def test_request_without_token_is_401(protected_app) -> None:
    client = _wire(
        protected_app,
        session=FakeSession(app_user=make_app_user(), roles=["admin"]),
        clerk=FakeClerk(),
    )
    resp = client.get("/me")
    assert resp.status_code == 401


def test_invalid_token_is_401(protected_app) -> None:
    client = _wire(
        protected_app,
        session=FakeSession(app_user=make_app_user(), roles=["admin"]),
        clerk=FakeClerk(raise_verify=True),
    )
    resp = client.get("/me", headers={"Authorization": "Bearer bad"})
    assert resp.status_code == 401


def test_valid_token_resolves_tenant_and_roles(protected_app) -> None:
    client = _wire(
        protected_app,
        session=FakeSession(app_user=make_app_user(), roles=["pastor", "lider_celula"]),
        clerk=FakeClerk(clerk_user_id="clerk_user_1"),
    )
    resp = client.get("/me", headers={"Authorization": "Bearer good"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["igrejaId"] == "00000000-0000-0000-0000-000000000001"
    assert body["roles"] == ["lider_celula", "pastor"]


def test_authenticated_without_app_user_returns_clear_error(protected_app) -> None:
    client = _wire(
        protected_app,
        session=FakeSession(app_user=None),
        clerk=FakeClerk(clerk_user_id="clerk_unlinked"),
    )
    resp = client.get("/me", headers={"Authorization": "Bearer good"})
    assert resp.status_code == 403
    assert "não está vinculada" in resp.json()["detail"]


def test_require_role_blocks_user_without_role(protected_app) -> None:
    client = _wire(
        protected_app,
        session=FakeSession(app_user=make_app_user(), roles=["lider_celula"]),
        clerk=FakeClerk(),
    )
    resp = client.get("/admin-only", headers={"Authorization": "Bearer good"})
    assert resp.status_code == 403


def test_admin_has_implicit_access(protected_app) -> None:
    client = _wire(
        protected_app,
        session=FakeSession(app_user=make_app_user(), roles=["admin"]),
        clerk=FakeClerk(),
    )
    # admin passes a pastor-gated route via implicit access.
    resp = client.get("/pastor-area", headers={"Authorization": "Bearer good"})
    assert resp.status_code == 200


def test_role_union_grants_access(protected_app) -> None:
    client = _wire(
        protected_app,
        session=FakeSession(
            app_user=make_app_user(), roles=["membro", "pastor"]
        ),
        clerk=FakeClerk(),
    )
    resp = client.get("/pastor-area", headers={"Authorization": "Bearer good"})
    assert resp.status_code == 200


def test_blocked_church_denies_protected_access(protected_app) -> None:
    client = _wire(
        protected_app,
        session=FakeSession(
            app_user=make_app_user(igreja_status="inadimplente"), roles=["admin"]
        ),
        clerk=FakeClerk(),
    )
    resp = client.get("/admin-only", headers={"Authorization": "Bearer good"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "billing_blocked"
