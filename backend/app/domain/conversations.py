"""Pure conversation/handoff rules and Evolution webhook parsing (no I/O).

Three concerns, all deterministic and unit-testable:

1. Inbox access gating (US-11): conversations/inbox are restricted to
   privileged roles. Cell leaders never get access. `admin` passes implicitly.
2. Handoff state machine (US-12/US-13): assuming a conversation moves it to
   `humano`; returning it moves it back to `ia`. The set of valid states is
   {ia, humano, aguardando}.
3. Webhook parsing: turn a raw Evolution `messages.upsert` payload into a small
   typed value, extracting the contact phone, the text and the provider message
   id used for idempotency.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.domain.phone import normalize_phone

ADMIN_ROLE = "admin"

# Roles privileged to open the inbox / human handoff (US-11). Cell leaders
# (lider_celula) are intentionally excluded. Mirrors the work-queue
# "atendimento" resolvers (pastor / lider_g12), plus admin (implicit).
INBOX_ROLES: frozenset[str] = frozenset({"pastor", "lider_g12"})

# Conversation states (conversation_estado enum).
VALID_ESTADOS: frozenset[str] = frozenset({"ia", "humano", "aguardando"})

# Provider event that carries a chat message.
MESSAGE_EVENT = "messages.upsert"


def can_access_inbox(roles: Iterable[str]) -> bool:
    """True if the caller may access conversations/inbox (US-11).

    `admin` always passes; cell leaders and members never do.
    """
    role_set = set(roles)
    if ADMIN_ROLE in role_set:
        return True
    return bool(role_set & INBOX_ROLES)


@dataclass(frozen=True)
class HandoffTarget:
    """Resolved target of a handoff request."""

    estado: str
    # True when a human is taking over (records assumido_por/assumido_em).
    assumes: bool
    # True when control returns to the IA (clears assumido_por/assumido_em).
    releases: bool


def resolve_handoff(to: str) -> HandoffTarget:
    """Map a handoff direction (`human`|`ia`) to its target state.

    Raises ValueError for an unknown direction (validated at the HTTP edge).
    """
    if to == "human":
        return HandoffTarget(estado="humano", assumes=True, releases=False)
    if to == "ia":
        return HandoffTarget(estado="ia", assumes=False, releases=True)
    raise ValueError(f"invalid handoff target: {to!r}")


@dataclass(frozen=True)
class ParsedMessage:
    """Normalized view of an inbound Evolution chat message."""

    instance: str
    provider_message_id: str
    telefone: str  # canonical digits-only key (dedupe by telefone+igreja)
    telefone_raw: str
    texto: str | None
    push_name: str | None
    from_me: bool


def _extract_text(message: dict[str, Any]) -> str | None:
    """Pull the human-readable text out of an Evolution `message` object."""
    if not isinstance(message, dict):
        return None
    if isinstance(message.get("conversation"), str):
        return message["conversation"]
    extended = message.get("extendedTextMessage")
    if isinstance(extended, dict) and isinstance(extended.get("text"), str):
        return extended["text"]
    # Captions on media messages.
    for media_key in ("imageMessage", "videoMessage", "documentMessage"):
        media = message.get(media_key)
        if isinstance(media, dict) and isinstance(media.get("caption"), str):
            return media["caption"]
    return None


def _phone_from_jid(remote_jid: str) -> str:
    """Strip the WhatsApp JID suffix (`@s.whatsapp.net` / `@g.us`)."""
    if not remote_jid:
        return ""
    return remote_jid.split("@", 1)[0]


def parse_message_event(payload: dict[str, Any]) -> ParsedMessage | None:
    """Parse an Evolution webhook payload into a ParsedMessage.

    Returns None when the payload is not a single chat message (e.g. a status
    update, a group message or a malformed body), so callers can safely skip
    it. Group messages (`@g.us`) are ignored — only direct chats are captured.
    """
    if not isinstance(payload, dict):
        return None
    if payload.get("event") != MESSAGE_EVENT:
        return None

    instance = payload.get("instance")
    data = payload.get("data")
    if not isinstance(instance, str) or not instance or not isinstance(data, dict):
        return None

    key = data.get("key")
    if not isinstance(key, dict):
        return None

    remote_jid = key.get("remoteJid") or ""
    if not isinstance(remote_jid, str) or "@g.us" in remote_jid:
        # Skip group chats; only 1:1 conversations are captured.
        return None

    provider_message_id = key.get("id")
    if not isinstance(provider_message_id, str) or not provider_message_id:
        return None

    telefone_raw = _phone_from_jid(remote_jid)
    telefone = normalize_phone(telefone_raw)
    if not telefone:
        return None

    return ParsedMessage(
        instance=instance,
        provider_message_id=provider_message_id,
        telefone=telefone,
        telefone_raw=telefone_raw,
        texto=_extract_text(data.get("message") or {}),
        push_name=data.get("pushName") if isinstance(data.get("pushName"), str) else None,
        from_me=bool(key.get("fromMe", False)),
    )
