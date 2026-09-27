"""Durable outbound-agent fence for a conversation handed to a human."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import case, update
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message
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
    # An action summary that was already delivered is also revoked. Returning
    # the chat to IA must never revive an old confirmation opportunity.
    from app.db.models import AgentActionProposal
    session.execute(
        update(AgentActionProposal)
        .where(
            AgentActionProposal.igreja_id == igreja_id,
            AgentActionProposal.conversation_id == conversation_id,
            AgentActionProposal.state.in_(("preparada", "pendente")),
        )
        .values(state="cancelada", terminal_reason="handoff_or_optout")
    )
    # An existing public-cell offer cannot survive an explicit human handoff or
    # opt-out fence.  This update runs under the caller's Conversation lock and
    # deliberately does not create a response marker for a different inbound.
    session.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.igreja_id == igreja_id,
            Conversation.secretaria_oferta_estado.in_(
                ("preparada", "aceite_aguardando_ancora", "pendente")
            ),
        )
        .values(
            secretaria_oferta_estado="cancelada",
            secretaria_oferta_expira_em=None,
        )
    )
    # V1b's private transcript is not conversation history.  The caller holds
    # the Conversation fence, so the audio service can clear it and cancel any
    # undelivered summary without retaining private content through handoff.
    from app.services.cell_report_audio_service import cancel_audio_inputs_for_conversation

    cancel_audio_inputs_for_conversation(
        session,
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        reason="handoff_or_optout",
    )


def mark_conversation_for_handoff_locked(
    session: Session,
    *,
    conversation: Conversation,
) -> None:
    """Mark an already locked conversation human and fence unsent replies."""

    conversation.estado = "humano"
    fence_agent_replies_for_handoff(
        session,
        igreja_id=conversation.igreja_id,
        conversation_id=conversation.id,
    )
    if conversation.assumido_por is None and conversation.espera_desde is None:
        conversation.espera_desde = dt.datetime.now(dt.UTC)
