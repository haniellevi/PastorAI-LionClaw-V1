"""Stable identities shared by ingestion and durable reply recovery."""
from hashlib import sha256
from typing import Any


def provider_message_lock_key(igreja_id: Any, provider_message_id: str) -> int:
    material = f"{igreja_id}:{provider_message_id}".encode("utf-8")
    return int.from_bytes(sha256(material).digest()[:8], "big", signed=True)


def agent_reply_key(igreja_id: Any, provider_message_id: str, claim_id: str) -> str:
    material = f"{igreja_id}:{provider_message_id}:{claim_id}".encode("utf-8")
    return f"agent-reply:{sha256(material).hexdigest()}"
