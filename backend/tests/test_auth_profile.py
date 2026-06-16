"""Tests for self-service profile: PATCH /auth/me + POST /auth/change-password."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}


def _wire(app, *, session, clerk) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    return TestClient(app)


def test_update_me_changes_nome(app) -> None:
    user = make_app_user(nome="Antigo")
    client = _wire(app, session=FakeSession(app_user=user, roles=["pastor"]), clerk=FakeClerk())
    resp = client.patch("/auth/me", headers=_AUTH, json={"nome": "Nome Novo"})
    assert resp.status_code == 200
    assert resp.json()["nome"] == "Nome Novo"
    assert user.nome == "Nome Novo"


def test_update_me_rejects_empty(app) -> None:
    client = _wire(
        app, session=FakeSession(app_user=make_app_user(), roles=["pastor"]), clerk=FakeClerk()
    )
    resp = client.patch("/auth/me", headers=_AUTH, json={"nome": "   "})
    assert resp.status_code == 422


# ---- nome de exibição no chat (assinatura) — Parte A ----------------------
def test_me_includes_chat_nome(app) -> None:
    user = make_app_user(chat_nome="Pastor Raniel")
    client = _wire(app, session=FakeSession(app_user=user, roles=["pastor"]), clerk=FakeClerk())
    resp = client.get("/auth/me", headers=_AUTH)
    assert resp.status_code == 200
    assert resp.json()["chatNome"] == "Pastor Raniel"


def test_update_me_sets_chat_nome(app) -> None:
    user = make_app_user()
    client = _wire(app, session=FakeSession(app_user=user, roles=["pastor"]), clerk=FakeClerk())
    resp = client.patch("/auth/me", headers=_AUTH, json={"chatNome": "Pastor Raniel"})
    assert resp.status_code == 200
    assert resp.json()["chatNome"] == "Pastor Raniel"
    assert user.chat_nome == "Pastor Raniel"


def test_update_me_clears_chat_nome(app) -> None:
    user = make_app_user(chat_nome="Antigo")
    client = _wire(app, session=FakeSession(app_user=user, roles=["pastor"]), clerk=FakeClerk())
    resp = client.patch("/auth/me", headers=_AUTH, json={"chatNome": ""})
    assert resp.status_code == 200
    assert resp.json()["chatNome"] is None
    assert user.chat_nome is None


def test_update_me_nome_only_keeps_chat_nome(app) -> None:
    # PATCH só com nome não mexe na assinatura (semântica PATCH).
    user = make_app_user(nome="Antigo", chat_nome="Assinatura")
    client = _wire(app, session=FakeSession(app_user=user, roles=["pastor"]), clerk=FakeClerk())
    resp = client.patch("/auth/me", headers=_AUTH, json={"nome": "Novo"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["nome"] == "Novo"
    assert body["chatNome"] == "Assinatura"
    assert user.chat_nome == "Assinatura"


def test_change_password_ok(app) -> None:
    client = _wire(
        app, session=FakeSession(app_user=make_app_user(), roles=["pastor"]), clerk=FakeClerk()
    )
    resp = client.post(
        "/auth/change-password",
        headers=_AUTH,
        json={"currentPassword": "atual", "newPassword": "novaSenha123"},
    )
    assert resp.status_code == 200


def test_change_password_wrong_current_is_400(app) -> None:
    # raise_login=True faz authenticate_password (verificação da senha atual) falhar.
    client = _wire(
        app,
        session=FakeSession(app_user=make_app_user(), roles=["pastor"]),
        clerk=FakeClerk(raise_login=True),
    )
    resp = client.post(
        "/auth/change-password",
        headers=_AUTH,
        json={"currentPassword": "errada", "newPassword": "novaSenha123"},
    )
    assert resp.status_code == 400


def test_change_password_rejects_short_new(app) -> None:
    client = _wire(
        app, session=FakeSession(app_user=make_app_user(), roles=["pastor"]), clerk=FakeClerk()
    )
    resp = client.post(
        "/auth/change-password",
        headers=_AUTH,
        json={"currentPassword": "atual", "newPassword": "curta"},
    )
    assert resp.status_code == 422
