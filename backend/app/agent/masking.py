"""Sensitive-data masking and AI audit logging (F8 / RNF-24 / delta-040).

Two concerns:

1. Masking — before persisting any agent payload we redact CPF, e-mail and long
   digit sequences (phone/card-like). `agent_conversation_logs.payload` must
   never store sensitive data in clear text (delta-040).
2. Logging — small writers that record one row per interaction:
     - `ai_usage_logs`  : model / tokens / cost (+ tool name when applicable).
     - `agent_conversation_logs` : event + masked payload.

The writers add rows to the session and flush; the caller owns the commit so
logging participates in the same transaction as the side effects it describes.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AgentConversationLog, AiUsageLog
from app.services.llm import LLMUsage

# CPF: 000.000.000-00 or 11 bare digits.
_CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
# E-mail address.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# Long digit runs (phones, cards) — keep last 2 digits for support reference.
_DIGITS_RE = re.compile(r"\b\d{7,}\b")

_MASK = "***"


def mask_text(value: str) -> str:
    """Redact CPF, e-mail and long digit sequences from a string."""
    masked = _CPF_RE.sub(_MASK, value)
    masked = _EMAIL_RE.sub(_MASK, masked)

    def _tail(match: re.Match[str]) -> str:
        digits = match.group(0)
        return f"{_MASK}{digits[-2:]}"

    return _DIGITS_RE.sub(_tail, masked)


def mask_value(value: Any) -> Any:
    """Recursively mask sensitive data inside strings/lists/dicts."""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {k: mask_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_value(v) for v in value]
    return value


def mask_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Mask a payload dict for safe storage in agent_conversation_logs."""
    return {k: mask_value(v) for k, v in payload.items()}


def _as_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def log_ai_usage(
    session: Session,
    *,
    igreja_id: str | uuid.UUID,
    usage: LLMUsage,
    ferramenta: str | None = None,
) -> AiUsageLog:
    """Record model / tokens / cost for one interaction (RNF-24)."""
    row = AiUsageLog(
        igreja_id=_as_uuid(igreja_id),
        modelo=usage.modelo,
        tokens_in=usage.tokens_in,
        tokens_out=usage.tokens_out,
        custo=usage.custo,
        ferramenta=ferramenta,
    )
    session.add(row)
    session.flush()
    return row


def log_agent_event(
    session: Session,
    *,
    igreja_id: str | uuid.UUID,
    evento: str,
    payload: dict[str, Any] | None = None,
    conversation_id: str | uuid.UUID | None = None,
) -> AgentConversationLog:
    """Record an agent event with its payload masked (F8/delta-040)."""
    row = AgentConversationLog(
        igreja_id=_as_uuid(igreja_id),
        conversation_id=_as_uuid(conversation_id),
        evento=evento,
        payload=mask_payload(payload) if payload else None,
    )
    session.add(row)
    session.flush()
    return row


def reserve_agent_event(
    session: Session,
    *,
    igreja_id: str | uuid.UUID,
    evento: str,
    payload: dict[str, Any] | None = None,
) -> AgentConversationLog | None:
    """Atomically reserve a dedupe marker in agent_conversation_logs (SEC-4).

    Unlike `log_agent_event` (caller owns the commit — logging shares the
    caller's transaction), this function COMMITS immediately. It exists
    specifically for the SLA-charge / autoupgrade-notice dedupe markers
    (`sla_%` / `subscription_upgrade:%`, see migration
    `20260709_204500_sec4_agent_event_idempotency_marker_uidx.sql`): the
    reservation must be durable and visible to a concurrent process BEFORE
    any outbound send is attempted, and no transaction may stay open while an
    external call (WhatsApp/Evolution) is in flight.

    Returns the created row if this call won the reservation — the caller
    should proceed to send, and may call `release_agent_event` if the send
    fails (at-least-once retry). Returns None if another process already
    holds the marker — the caller MUST NOT send (someone else already is, or
    already did).
    """
    row = AgentConversationLog(
        igreja_id=_as_uuid(igreja_id),
        evento=evento,
        payload=mask_payload(payload) if payload else None,
    )
    session.add(row)
    try:
        session.flush()
        session.commit()
    except IntegrityError:
        session.rollback()
        return None
    return row


def release_agent_event(session: Session, row: AgentConversationLog) -> None:
    """Undo a reservation after a failed send (SEC-4, at-least-once retry).

    Deletes the marker so the next sweep/call retries the send. Only call
    this after a genuine send failure to every attempted recipient — never
    after a successful send, and never for the "no recipient/no instance"
    case (that stays logged, matching the pre-existing behavior of not
    re-attempting items with no resolvable contact on every tick).
    """
    session.delete(row)
    session.commit()
