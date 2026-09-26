"""Durable outbound-agent fence for a conversation handed to a human."""

from __future__ import annotations

import uuid

from sqlalchemy import case, update
from sqlalchemy.orm import Session

from app.db.models import Message
from app.domain.agent_reply import (
    AGENT_REPLY_AMBIGUOUS,
    AGENT_REPLY_EXECUTING,
    AGENT_REPLY_IN_FLIGHT,
    AGENT_REPLY_PENDING,
    AGENT_REPLY_RESERVED,
    AGENT_REPLY_SUPPRESSED,
)


def fence_agent_replies_for_handoff(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> None:
    """Terminally fence unsent replies while the caller holds Conversation lock.

    A provider request may already have started from ``ia_em_transporte``. Keep
    that result manually reconcilable; rows which never reached transport are
    safe to suppress.
    """
    base = (
        Message.igreja_id == igreja_id,
        Message.conversation_id == conversation_id,
        Message.direcao == "out",
        Message.autor == "ia",
    )
    session.execute(
        update(Message)
        .where(
            *base,
            Message.agent_reply_state.in_(
                (
                    AGENT_REPLY_RESERVED,
                    AGENT_REPLY_EXECUTING,
                    AGENT_REPLY_PENDING,
                    AGENT_REPLY_IN_FLIGHT,
                )
            ),
        )
        .values(
            agent_reply_state=case(
                (Message.agent_reply_state == AGENT_REPLY_IN_FLIGHT, AGENT_REPLY_AMBIGUOUS),
                else_=AGENT_REPLY_SUPPRESSED,
            )
        )
    )
