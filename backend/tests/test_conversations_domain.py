"""Unit tests for conversation/handoff rules and webhook parsing (no I/O)."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.domain.conversations import (
    can_access_inbox,
    parse_message_event,
    resolve_handoff,
)
from app.services.evolution import map_connection_state, verify_webhook_signature


# ---- inbox access (US-11) -------------------------------------------------
def test_admin_and_privileged_roles_access_inbox() -> None:
    assert can_access_inbox(["admin"]) is True
    assert can_access_inbox(["pastor"]) is True
    assert can_access_inbox(["lider_g12"]) is True
    assert can_access_inbox(["operador"]) is True


def test_cell_leader_cannot_access_inbox() -> None:
    assert can_access_inbox(["lider_celula"]) is False
    assert can_access_inbox(["membro"]) is False
    assert can_access_inbox([]) is False


# ---- handoff state machine (US-12/US-13) ----------------------------------
def test_resolve_handoff_to_human() -> None:
    target = resolve_handoff("human")
    assert target.estado == "humano"
    assert target.assumes is True
    assert target.releases is False


def test_resolve_handoff_to_ia() -> None:
    target = resolve_handoff("ia")
    assert target.estado == "ia"
    assert target.assumes is False
    assert target.releases is True


def test_resolve_handoff_invalid() -> None:
    with pytest.raises(ValueError):
        resolve_handoff("bot")


# ---- webhook parsing ------------------------------------------------------
def _message_payload(text: str = "Olá", from_me: bool = False) -> dict:
    return {
        "event": "messages.upsert",
        "instance": "igreja-1",
        "data": {
            "key": {
                "remoteJid": "5511999990000@s.whatsapp.net",
                "fromMe": from_me,
                "id": "MSG123",
            },
            "pushName": "Maria",
            "message": {"conversation": text},
        },
    }


def test_parse_message_event_extracts_fields() -> None:
    parsed = parse_message_event(_message_payload())
    assert parsed is not None
    assert parsed.instance == "igreja-1"
    assert parsed.provider_message_id == "MSG123"
    assert parsed.telefone == "11999990000"  # canonical: +55 dropped
    assert parsed.texto == "Olá"
    assert parsed.push_name == "Maria"
    assert parsed.from_me is False


def test_parse_message_event_extended_text() -> None:
    payload = _message_payload()
    payload["data"]["message"] = {"extendedTextMessage": {"text": "mundo"}}
    parsed = parse_message_event(payload)
    assert parsed is not None
    assert parsed.texto == "mundo"


def test_parse_message_event_ignores_non_message_event() -> None:
    assert parse_message_event({"event": "connection.update"}) is None


def test_parse_message_event_ignores_group_chats() -> None:
    payload = _message_payload()
    payload["data"]["key"]["remoteJid"] = "120363@g.us"
    assert parse_message_event(payload) is None


def test_parse_message_event_requires_message_id() -> None:
    payload = _message_payload()
    payload["data"]["key"].pop("id")
    assert parse_message_event(payload) is None


def test_parse_message_event_handles_malformed() -> None:
    assert parse_message_event(None) is None  # type: ignore[arg-type]
    assert parse_message_event({}) is None


# ---- signature verification -----------------------------------------------
def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_webhook_signature_valid() -> None:
    body = b'{"event":"x"}'
    sig = _sign("topsecret", body)
    assert verify_webhook_signature("topsecret", body, sig) is True
    assert verify_webhook_signature("topsecret", body, f"sha256={sig}") is True


def test_verify_webhook_signature_invalid() -> None:
    body = b'{"event":"x"}'
    assert verify_webhook_signature("topsecret", body, "deadbeef") is False
    assert verify_webhook_signature("", body, _sign("x", body)) is False
    assert verify_webhook_signature("topsecret", body, None) is False


# ---- connection-state mapping ---------------------------------------------
def test_map_connection_state() -> None:
    assert map_connection_state("open") == "online"
    assert map_connection_state("connecting") == "reconectando"
    assert map_connection_state("close") == "offline"
    assert map_connection_state(None) == "offline"
    assert map_connection_state("weird") == "offline"
