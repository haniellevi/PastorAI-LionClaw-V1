"""Edge-validation and auth-wiring tests for the relatorios/equipe/config sprint.

These exercise the HTTP contracts that run before persistence: authentication
gating (401), webhook token gating (401) and input validation (422). Business
rules that touch the database are covered by the pure unit tests in
test_broadcast_domain.py / test_billing_domain.py.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}


def _client(app) -> TestClient:
    app.dependency_overrides[get_db] = lambda: FakeSession(
        app_user=make_app_user(), roles=["admin"]
    )
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


# ---- auth gating ----------------------------------------------------------
def test_reports_requires_auth(app) -> None:
    assert _client(app).get("/reports").status_code == 401


def test_broadcasts_requires_auth(app) -> None:
    assert _client(app).get("/broadcasts").status_code == 401


def test_events_requires_auth(app) -> None:
    assert _client(app).get("/events").status_code == 401


def test_team_invite_requires_auth(app) -> None:
    assert _client(app).post("/team/invite", json={}).status_code == 401


def test_roles_permissions_requires_auth(app) -> None:
    assert _client(app).get("/roles/permissions").status_code == 401


def test_subscription_requires_auth(app) -> None:
    assert _client(app).get("/subscription").status_code == 401


# ---- broadcast validation -------------------------------------------------
def test_broadcast_rejects_invalid_modo(app) -> None:
    resp = _client(app).post(
        "/broadcasts",
        json={
            "titulo": "Aviso",
            "mensagem": "Olá",
            "segmentos": ["todos"],
            "modo": "ja",
        },
        headers=_AUTH,
    )
    assert resp.status_code == 422


def test_broadcast_requires_segmentos(app) -> None:
    resp = _client(app).post(
        "/broadcasts",
        json={"titulo": "Aviso", "mensagem": "Olá", "segmentos": [], "modo": "agora"},
        headers=_AUTH,
    )
    assert resp.status_code == 422


# ---- events validation ----------------------------------------------------
def test_event_requires_data(app) -> None:
    resp = _client(app).post("/events", json={"titulo": "Culto"}, headers=_AUTH)
    assert resp.status_code == 422


# ---- team validation ------------------------------------------------------
def test_team_invite_rejects_invalid_email(app) -> None:
    resp = _client(app).post(
        "/team/invite",
        json={
            "pessoaId": "00000000-0000-0000-0000-0000000000b1",
            "email": "invalido",
        },
        headers=_AUTH,
    )
    assert resp.status_code == 422


def test_team_invite_requires_pessoa(app) -> None:
    # Convites não escolhem papéis e exigem uma pessoa já cadastrada (delta-049).
    resp = _client(app).post(
        "/team/invite",
        json={"email": "novo@ex.com"},
        headers=_AUTH,
    )
    assert resp.status_code == 422


def test_team_roles_rejects_invalid_role(app) -> None:
    resp = _client(app).put(
        "/team/00000000-0000-0000-0000-0000000000ff/roles",
        json={"papeis": ["arcanjo"]},
        headers=_AUTH,
    )
    assert resp.status_code == 422


# ---- roles/permissions validation -----------------------------------------
def test_roles_permissions_rejects_invalid_role(app) -> None:
    resp = _client(app).put(
        "/roles/permissions",
        json={"matriz": {"arcanjo": ["dashboard"]}},
        headers=_AUTH,
    )
    assert resp.status_code == 422


# ---- subscription validation + webhook gating -----------------------------
def test_subscription_checkout_rejects_invalid_plano(app) -> None:
    resp = _client(app).post(
        "/subscription", json={"plano": "ilimitado"}, headers=_AUTH
    )
    assert resp.status_code == 422


def test_subscription_webhook_rejects_missing_token(app) -> None:
    resp = _client(app).post(
        "/subscription/webhook", json={"event": "PAYMENT_CONFIRMED"}
    )
    assert resp.status_code == 401


# ---- agent config + crons validation --------------------------------------
def test_agent_config_put_forbidden_for_admin(app) -> None:
    # #10b Fase 1 (delta-043): a config do agente é exclusiva do master; o admin
    # não edita por aqui (antes este PUT salvava o comportamento — brecha).
    resp = _client(app).put(
        "/agent/config", json={"comportamento": "x"}, headers=_AUTH
    )
    assert resp.status_code == 403


def test_agent_cron_rejects_invalid_gatilho(app) -> None:
    resp = _client(app).post(
        "/agent/crons",
        json={"nome": "X", "frequencia": "daily", "gatilhoEstado": "voar"},
        headers=_AUTH,
    )
    assert resp.status_code == 422
