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

# Visão COMPLETA do inbox: enxerga todas as conversas do tenant (#5). admin tem
# acesso implícito; pastor é o único papel não-admin com visão completa.
FULL_INBOX_ROLES: frozenset[str] = frozenset({"pastor"})

# Visão RESTRITA ("responsável", #5): acessa o inbox mas só vê as conversas
# atribuídas a si (assumido_por). Inclui líder G12, líder de consolidação,
# líder de célula e o operador de atendimento.
RESTRICTED_INBOX_ROLES: frozenset[str] = frozenset(
    {"lider_g12", "lider_consol", "lider_celula", "operador"}
)

# Todos os papéis (não-admin) com ALGUM acesso ao inbox = união dos dois. É a
# fonte de verdade para "quem pode ser destino de transferência" e para o gate
# de tela no front; a VISIBILIDADE (completa × só as suas) é decidida por
# has_full_inbox + o filtro por assumido_por no router.
INBOX_ROLES: frozenset[str] = FULL_INBOX_ROLES | RESTRICTED_INBOX_ROLES

# Conversation states (conversation_estado enum).
VALID_ESTADOS: frozenset[str] = frozenset({"ia", "humano", "aguardando"})

# Provider event that carries a chat message.
MESSAGE_EVENT = "messages.upsert"


def media_snippet(kind: str | None) -> str:
    """Short list label for media that arrives without a caption (Etapa 2)."""
    return {"imagem": "📷 Imagem", "arquivo": "📎 Arquivo", "audio": "🎤 Áudio"}.get(
        kind or "", ""
    )


def can_access_inbox(roles: Iterable[str]) -> bool:
    """True if the caller may access conversations/inbox at all (US-11/#5).

    `admin` always passes; membro and papéis sem inbox nunca passam. Inclui os
    "responsáveis" (visão restrita) — eles acessam, mas só veem as suas.
    """
    role_set = set(roles)
    if ADMIN_ROLE in role_set:
        return True
    return bool(role_set & INBOX_ROLES)


def has_full_inbox(roles: Iterable[str]) -> bool:
    """True se o usuário vê TODAS as conversas do tenant (#5).

    `admin` (implícito) e `pastor` têm visão completa. Os demais papéis com
    acesso ao inbox são "responsáveis": veem só as conversas atribuídas a eles.
    """
    role_set = set(roles)
    if ADMIN_ROLE in role_set:
        return True
    return bool(role_set & FULL_INBOX_ROLES)


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
    # Canonical number of the instance owner (the church's own official number),
    # when the provider includes it. Used to never ingest the church's own
    # number as a contact (self-chat / history sync on connect).
    owner: str | None = None
    # Media (Etapa 2): when the message carries an image/document/audio, the
    # kind (imagem|arquivo|audio) plus its mimetype and original filename. The
    # bytes are NOT here — the worker pulls them from Evolution on demand and
    # uploads to Storage. None for plain-text messages.
    media_kind: str | None = None
    media_mime: str | None = None
    media_nome: str | None = None


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
    # documentWithCaptionMessage wraps a documentMessage one level down.
    wrapped = message.get("documentWithCaptionMessage")
    if isinstance(wrapped, dict):
        inner = (wrapped.get("message") or {}).get("documentMessage")
        if isinstance(inner, dict) and isinstance(inner.get("caption"), str):
            return inner["caption"]
    return None


def _extract_media(message: dict[str, Any]) -> tuple[str, str | None, str | None] | None:
    """Detect a media payload on an Evolution `message` object.

    Returns ``(kind, mimetype, filename)`` where kind is imagem|arquivo|audio,
    or None for a plain-text message. The bytes are fetched later (worker) via
    the message key — here we only classify and read the metadata.
    """
    if not isinstance(message, dict):
        return None
    img = message.get("imageMessage")
    if isinstance(img, dict):
        return ("imagem", img.get("mimetype") or "image/jpeg", None)
    aud = message.get("audioMessage")
    if isinstance(aud, dict):
        return ("audio", aud.get("mimetype") or "audio/ogg", None)
    doc = message.get("documentMessage")
    if isinstance(doc, dict):
        return (
            "arquivo",
            doc.get("mimetype") or "application/octet-stream",
            doc.get("fileName") or doc.get("title"),
        )
    wrapped = message.get("documentWithCaptionMessage")
    if isinstance(wrapped, dict):
        inner = (wrapped.get("message") or {}).get("documentMessage")
        if isinstance(inner, dict):
            return (
                "arquivo",
                inner.get("mimetype") or "application/octet-stream",
                inner.get("fileName") or inner.get("title"),
            )
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

    # The instance owner (church's own number) — Evolution puts it in `sender`.
    sender = payload.get("sender")
    owner = normalize_phone(_phone_from_jid(sender)) if isinstance(sender, str) else None

    message = data.get("message") or {}
    media = _extract_media(message)

    return ParsedMessage(
        instance=instance,
        provider_message_id=provider_message_id,
        telefone=telefone,
        telefone_raw=telefone_raw,
        texto=_extract_text(message),
        push_name=data.get("pushName") if isinstance(data.get("pushName"), str) else None,
        from_me=bool(key.get("fromMe", False)),
        owner=owner or None,
        media_kind=media[0] if media else None,
        media_mime=media[1] if media else None,
        media_nome=media[2] if media else None,
    )
