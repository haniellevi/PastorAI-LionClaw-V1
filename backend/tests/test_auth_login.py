"""Tests for POST /auth/login (api-login contract + US-01/US-02/US-35)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user


def _client(app, *, session: FakeSession, clerk: FakeClerk) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    return TestClient(app)


def test_login_success_returns_token_and_church_id(app) -> None:
    user = make_app_user()
    client = _client(
        app,
        session=FakeSession(app_user=user, roles=["admin", "pastor"]),
        clerk=FakeClerk(login_result=("token_xyz", "clerk_user_1")),
    )
    resp = client.post(
        "/auth/login",
        json={"email": "pastor@igrejapiloto.com", "password": "secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"] == "token_xyz"
    assert body["churchId"] == "00000000-0000-0000-0000-000000000001"


def test_login_invalid_credentials_is_generic(app) -> None:
    client = _client(
        app,
        session=FakeSession(app_user=None),
        clerk=FakeClerk(raise_login=True),
    )
    resp = client.post(
        "/auth/login",
        json={"email": "unknown@example.com", "password": "wrong"},
    )
    assert resp.status_code == 401
    # Must not reveal whether the email exists.
    assert resp.json()["detail"] == "E-mail ou senha inválidos"


def test_login_clerk_ok_but_no_app_user_is_generic(app) -> None:
    client = _client(
        app,
        session=FakeSession(app_user=None),
        clerk=FakeClerk(login_result=("token_xyz", "clerk_user_unlinked")),
    )
    resp = client.post(
        "/auth/login",
        json={"email": "ghost@example.com", "password": "secret"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "E-mail ou senha inválidos"


def test_login_blocked_for_suspended_church(app) -> None:
    user = make_app_user(igreja_status="suspensa")
    client = _client(
        app,
        session=FakeSession(app_user=user, roles=["admin"]),
        clerk=FakeClerk(login_result=("token_xyz", "clerk_user_1")),
    )
    resp = client.post(
        "/auth/login",
        json={"email": "pastor@igrejapiloto.com", "password": "secret"},
    )
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["error"] == "billing_blocked"
    assert detail["igrejaStatus"] == "suspensa"


def test_login_rejects_malformed_email(app) -> None:
    client = _client(
        app,
        session=FakeSession(app_user=None),
        clerk=FakeClerk(),
    )
    resp = client.post("/auth/login", json={"email": "not-an-email", "password": "x"})
    assert resp.status_code == 422
