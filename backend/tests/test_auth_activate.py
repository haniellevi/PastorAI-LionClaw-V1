"""Tests for the invite activation flow (POST /auth/activate + GET /auth/invite).

The invited app_user starts without a Clerk account (clerk_user_id NULL).
Activation verifies the signed invite token, creates the Clerk user with the
chosen password and links it, flipping the account to 'ativo'. Validated offline.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk

_AID = "00000000-0000-0000-0000-0000000000a1"


class _Result:
    def __init__(self, scalar=None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class InviteSession:
    """Minimal session: returns the invited app_user and records commit."""

    def __init__(self, app_user=None) -> None:
        self.app_user = app_user
        self.committed = False

    def execute(self, statement, params=None) -> _Result:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _Result(scalar=self.app_user)
        return _Result()

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


def make_invited(
    *,
    clerk_user_id=None,
    email: str = "novo@igreja.org",
    nome: str = "Pastor Novo",
    igreja: str = "Igreja Nova",
):
    return SimpleNamespace(
        id=_AID,
        clerk_user_id=clerk_user_id,
        email=email,
        nome=nome,
        status="convidado",
        igreja=SimpleNamespace(nome=igreja),
    )


def _wire(app, *, session, clerk) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    return TestClient(app)


# ---- GET /auth/invite/{token} ---------------------------------------------
def test_invite_info_returns_data(app) -> None:
    client = _wire(app, session=InviteSession(make_invited()), clerk=FakeClerk(invite_app_user_id=_AID))
    resp = client.get("/auth/invite/sometoken")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "novo@igreja.org"
    assert body["nome"] == "Pastor Novo"
    assert body["igreja"] == "Igreja Nova"


def test_invite_info_invalid_token(app) -> None:
    client = _wire(app, session=InviteSession(make_invited()), clerk=FakeClerk(raise_invite=True))
    assert client.get("/auth/invite/bad").status_code == 400


def test_invite_info_already_activated(app) -> None:
    client = _wire(
        app,
        session=InviteSession(make_invited(clerk_user_id="clerk_existing")),
        clerk=FakeClerk(invite_app_user_id=_AID),
    )
    assert client.get("/auth/invite/tok").status_code == 409


# ---- POST /auth/activate ---------------------------------------------------
def test_activate_creates_access(app) -> None:
    invited = make_invited()
    session = InviteSession(invited)
    client = _wire(
        app,
        session=session,
        clerk=FakeClerk(invite_app_user_id=_AID, created_clerk_id="clerk_brand_new"),
    )
    resp = client.post("/auth/activate", json={"token": "tok", "password": "umaSenha123"})
    assert resp.status_code == 200
    assert invited.clerk_user_id == "clerk_brand_new"
    assert invited.status == "ativo"
    assert session.committed is True


def test_activate_invalid_token(app) -> None:
    client = _wire(app, session=InviteSession(make_invited()), clerk=FakeClerk(raise_invite=True))
    resp = client.post("/auth/activate", json={"token": "bad", "password": "umaSenha123"})
    assert resp.status_code == 400


def test_activate_already_activated(app) -> None:
    client = _wire(
        app,
        session=InviteSession(make_invited(clerk_user_id="clerk_x")),
        clerk=FakeClerk(invite_app_user_id=_AID),
    )
    resp = client.post("/auth/activate", json={"token": "tok", "password": "umaSenha123"})
    assert resp.status_code == 409


def test_activate_rejects_short_password(app) -> None:
    client = _wire(app, session=InviteSession(make_invited()), clerk=FakeClerk(invite_app_user_id=_AID))
    resp = client.post("/auth/activate", json={"token": "tok", "password": "curta"})
    assert resp.status_code == 422


def test_activate_clerk_failure_is_502(app) -> None:
    client = _wire(
        app,
        session=InviteSession(make_invited()),
        clerk=FakeClerk(invite_app_user_id=_AID, raise_create=True),
    )
    resp = client.post("/auth/activate", json={"token": "tok", "password": "umaSenha123"})
    assert resp.status_code == 502
