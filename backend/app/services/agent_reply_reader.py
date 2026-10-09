"""Read-only reply application seam; ownership and delivery stay with the worker."""
from dataclasses import dataclass
from typing import Any
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Message
from app.db.rls_observability import require_tenant_scope
from app.domain.agent_reply import AGENT_REPLY_CONFIRMED
from app.domain.provider_identity import provider_message_lock_key


@dataclass(frozen=True)
class AgentReplyIntent:
    """Sanitized snapshot of one durable outbound agent intent.

    ``ia_em_transporte`` is deliberately treated as unresolved by a later
    recovery: the first process may have crossed the provider boundary before
    crashing.  Only ``ia_pendente`` can start a new call automatically.
    """

    id: Any
    state: str
    response: str
    provider_message_id: str
    public_info_reply: bool | None
    privileged_reply: bool = False


@dataclass(frozen=True)
class ReplyReadContext:
    igreja_id: uuid.UUID
    provider_message_id: str


def fenced_reply_message(
    db: Session, igreja_id: Any, provider_message_id: str
) -> Message | None:
    """Fence one reply plan and return its existing durable row, if any.

    The ``:<response-hash>`` suffix was part of the pre-single-flight key.
    Read it only for recovery compatibility: all new plans use the exact,
    stable claim-derived key above.
    """

    get_bind = getattr(db, "get_bind", None)
    if get_bind is not None and get_bind().dialect.name == "postgresql":
        db.execute(
            select(
                func.pg_advisory_xact_lock(
                    provider_message_lock_key(igreja_id, provider_message_id)
                )
            )
        ).scalar_one_or_none()
    return db.execute(
        select(Message)
        .where(
            Message.igreja_id == igreja_id,
            Message.direcao == "out",
            or_(
                Message.provider_message_id == provider_message_id,
                Message.provider_message_id.like(f"{provider_message_id}:%"),
            ),
        )
        .order_by(Message.criado_em.asc(), Message.id.asc())
        .limit(1)
    ).scalar_one_or_none()


def intent_from_message(message: Message) -> AgentReplyIntent:
    # Confirmed rows written before the dedicated state column have NULL here;
    # their ``autor='ia'`` remains sufficient recovery evidence. Other states
    # could never be persisted by the three-value production enum.
    state = message.agent_reply_state
    if state is None and message.autor == "ia":
        state = AGENT_REPLY_CONFIRMED
    public_info_reply = getattr(message, "public_info_reply", None)
    return AgentReplyIntent(
        id=message.id,
        state=state or "",
        response=message.texto or "",
        provider_message_id=message.provider_message_id or "",
        privileged_reply=type(getattr(message, "agent_privilege_context", None)) is dict,
        public_info_reply=(
            public_info_reply
            if type(public_info_reply) is bool
            else None
        ),
    )


def load_agent_reply_intent(session: Session, context: ReplyReadContext) -> AgentReplyIntent | None:
    """Read under an existing tenant scope and transaction fence, without commit.

    The caller composes and closes the session. The context is server-resolved,
    never supplied by a model or an untrusted request.
    """
    require_tenant_scope(session, expected_igreja_id=context.igreja_id, source="agent_reply_reader")
    row = fenced_reply_message(session, context.igreja_id, context.provider_message_id)
    return intent_from_message(row) if row is not None else None
