"""Tests for Clerk auth, tenant resolution and require_role RBAC."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.deps import (
    CurrentUser,
    get_billing_recovery_user,
    get_current_user,
    require_billing_recovery_owner,
    require_role,
)
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

    @app.get("/billing-recovery")
    def billing_recovery(
        user: CurrentUser = Depends(get_billing_recovery_user),
    ) -> dict:
        return {"ok": True, "owner": user.is_owner}

    @app.get("/billing-owner")
    def billing_owner(
        user: CurrentUser = Depends(require_billing_recovery_owner),
    ) -> dict:
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


def test_revoked_user_is_blocked(protected_app) -> None:
    # A revoked app_user is denied even with a still-valid session token (RF-04).
    client = _wire(
        protected_app,
        session=FakeSession(
            app_user=make_app_user(status="revogado"), roles=["admin"]
        ),
        clerk=FakeClerk(),
    )
    resp = client.get("/me", headers={"Authorization": "Bearer good"})
    assert resp.status_code == 403
    assert "revogado" in resp.json()["detail"]


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


def test_delinquent_owner_can_reach_only_billing_recovery(protected_app) -> None:
    session = FakeSession(
        app_user=make_app_user(igreja_status="inadimplente"), roles=["admin"]
    )
    client = _wire(protected_app, session=session, clerk=FakeClerk())

    assert client.get("/me", headers={"Authorization": "Bearer good"}).status_code == 403
    recovery = client.get(
        "/billing-owner", headers={"Authorization": "Bearer good"}
    )
    assert recovery.status_code == 200


@pytest.mark.parametrize("igreja_status", ["suspensa", "aguardando_aprovacao"])
def test_other_church_blocks_still_deny_billing_recovery(
    protected_app, igreja_status: str
) -> None:
    client = _wire(
        protected_app,
        session=FakeSession(
            app_user=make_app_user(igreja_status=igreja_status), roles=["admin"]
        ),
        clerk=FakeClerk(),
    )

    resp = client.get(
        "/billing-owner", headers={"Authorization": "Bearer good"}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "billing_blocked"


def test_delinquent_non_owner_cannot_recover_billing(protected_app) -> None:
    client = _wire(
        protected_app,
        session=FakeSession(
            app_user=make_app_user(
                igreja_status="inadimplente",
                dono_id="00000000-0000-0000-0000-000000000099",
            ),
            roles=["admin"],
        ),
        clerk=FakeClerk(),
    )

    resp = client.get(
        "/billing-owner", headers={"Authorization": "Bearer good"}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "billing_blocked"
