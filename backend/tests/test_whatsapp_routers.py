"""Edge tests for whatsapp/conversations routers: auth, RBAC and webhook."""

from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.session import get_db
from app.routers.whatsapp import get_webhook_queue
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}


class _FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list = []

    def enqueue(self, payload) -> None:
        self.enqueued.append(payload)


def _client(app, roles: list[str]) -> TestClient:
    app.dependency_overrides[get_db] = lambda: FakeSession(
        app_user=make_app_user(), roles=roles
    )
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


# ---- auth gating ----------------------------------------------------------
def test_conversations_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    assert client.get("/conversations").status_code == 401


def test_whatsapp_connection_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    assert client.get("/whatsapp/connection").status_code == 401


# ---- inbox RBAC (US-11) ---------------------------------------------------
def test_cell_leader_forbidden_on_conversations(app) -> None:
    client = _client(app, roles=["lider_celula"])
    assert client.get("/conversations", headers=_AUTH).status_code == 403


def test_cell_leader_forbidden_on_handoff(app) -> None:
    client = _client(app, roles=["lider_celula"])
    resp = client.post(
        "/conversations/00000000-0000-0000-0000-0000000000aa/handoff",
        json={"to": "human"},
        headers=_AUTH,
    )
    assert resp.status_code == 403


# ---- whatsapp connection RBAC (admin only) --------------------------------
def test_cell_leader_forbidden_on_whatsapp_connection(app) -> None:
    client = _client(app, roles=["lider_celula"])
    assert client.get("/whatsapp/connection", headers=_AUTH).status_code == 403


# ---- inbox messages: auth, RBAC and validation (US-13) --------------------
_CONV_MSGS = "/conversations/00000000-0000-0000-0000-0000000000aa/messages"


def test_messages_history_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    assert client.get(_CONV_MSGS).status_code == 401


def test_cell_leader_forbidden_on_messages_history(app) -> None:
    client = _client(app, roles=["lider_celula"])
    assert client.get(_CONV_MSGS, headers=_AUTH).status_code == 403


def test_send_message_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    assert client.post(_CONV_MSGS, json={"texto": "oi"}).status_code == 401


def test_cell_leader_forbidden_on_send_message(app) -> None:
    client = _client(app, roles=["lider_celula"])
    resp = client.post(_CONV_MSGS, json={"texto": "oi"}, headers=_AUTH)
    assert resp.status_code == 403


def test_send_message_rejects_empty_text(app) -> None:
    client = _client(app, roles=["admin"])
    resp = client.post(_CONV_MSGS, json={"texto": "   "}, headers=_AUTH)
    assert resp.status_code == 422


# ---- inbox media send: auth, RBAC and validation (Etapa 2) ----------------
_CONV_MEDIA = "/conversations/00000000-0000-0000-0000-0000000000aa/messages/media"


def test_send_media_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    resp = client.post(_CONV_MEDIA, json={"mime": "image/png", "base64": "Zm9v"})
    assert resp.status_code == 401


def test_cell_leader_forbidden_on_send_media(app) -> None:
    client = _client(app, roles=["lider_celula"])
    resp = client.post(
        _CONV_MEDIA, json={"mime": "image/png", "base64": "Zm9v"}, headers=_AUTH
    )
    assert resp.status_code == 403


def test_send_media_rejects_missing_fields(app) -> None:
    client = _client(app, roles=["admin"])
    resp = client.post(_CONV_MEDIA, json={"mime": "image/png"}, headers=_AUTH)
    assert resp.status_code == 422


# ---- MessageOut carrega o nome de quem respondeu (Parte A) -----------------
def test_message_out_maps_author_name() -> None:
    from types import SimpleNamespace

    from app.routers.conversations import MessageOut

    m = SimpleNamespace(
        id="m1",
        direcao="out",
        autor="humano",
        autor_nome="Pastor Raniel",
        tipo="texto",
        texto="oi",
        media_mime=None,
        media_nome=None,
        criado_em=None,
    )
    out = MessageOut.from_model(m)
    assert out.autorNome == "Pastor Raniel"
    assert out.autor == "humano"
    assert out.direcao == "out"


def test_author_caption_prefixes_name_for_whatsapp() -> None:
    # O contato precisa ver QUEM respondeu: o nome vai prefixado no texto.
    from app.routers.conversations import _author_caption

    assert _author_caption("Pastor Raniel", "oi") == "*Pastor Raniel:*\noi"
    assert _author_caption("Pastor Raniel", None) == "*Pastor Raniel:*"
    assert _author_caption("Pastor Raniel", "") == "*Pastor Raniel:*"


# ---- validation -----------------------------------------------------------
def test_handoff_rejects_invalid_target(app) -> None:
    client = _client(app, roles=["admin"])
    resp = client.post(
        "/conversations/00000000-0000-0000-0000-0000000000aa/handoff",
        json={"to": "bot"},
        headers=_AUTH,
    )
    assert resp.status_code == 422


def test_whatsapp_connection_rejects_invalid_action(app) -> None:
    client = _client(app, roles=["admin"])
    resp = client.post(
        "/whatsapp/connection", json={"action": "delete"}, headers=_AUTH
    )
    assert resp.status_code == 422


# ---- webhook signature ----------------------------------------------------
def _webhook_client(app) -> TestClient:
    app.dependency_overrides[get_webhook_queue] = lambda: _FakeQueue()
    return TestClient(app)


def test_webhook_rejects_invalid_signature(app, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "evolution_webhook_secret", "topsecret")
    client = _webhook_client(app)
    resp = client.post(
        "/whatsapp/webhook",
        content=b'{"event":"messages.upsert"}',
        headers={"x-evolution-signature": "wrong"},
    )
    assert resp.status_code == 401


def test_webhook_accepts_valid_signature(app, monkeypatch) -> None:
    secret = "topsecret"
    monkeypatch.setattr(get_settings(), "evolution_webhook_secret", secret)
    queue = _FakeQueue()
    app.dependency_overrides[get_webhook_queue] = lambda: queue
    client = TestClient(app)

    body = json.dumps({"event": "messages.upsert", "instance": "igreja-1"}).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    resp = client.post(
        "/whatsapp/webhook",
        content=body,
        headers={"x-evolution-signature": sig},
    )
    assert resp.status_code == 202
    assert len(queue.enqueued) == 1


def test_webhook_accepts_valid_query_token(app, monkeypatch) -> None:
    # Evolution v2 self-hosted authenticates via the URL query string (?token=).
    secret = "topsecret"
    monkeypatch.setattr(get_settings(), "evolution_webhook_secret", secret)
    queue = _FakeQueue()
    app.dependency_overrides[get_webhook_queue] = lambda: queue
    client = TestClient(app)

    body = json.dumps({"event": "messages.upsert", "instance": "igreja-1"}).encode()
    resp = client.post(
        f"/whatsapp/webhook?token={secret}",
        content=body,
    )
    assert resp.status_code == 202
    assert len(queue.enqueued) == 1


def test_webhook_rejects_invalid_query_token(app, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "evolution_webhook_secret", "topsecret")
    client = _webhook_client(app)
    resp = client.post(
        "/whatsapp/webhook?token=wrong",
        content=b'{"event":"messages.upsert"}',
    )
    assert resp.status_code == 401
