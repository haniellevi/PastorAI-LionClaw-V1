"""Guided read-only lookup on the existing durable reply/transport pipeline."""

import datetime as dt
import uuid
from types import SimpleNamespace
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.db.models import Message
from app.domain import consent
from app.domain.agent_reply import (
    AGENT_REPLY_PENDING,
    AGENT_REPLY_RESERVED,
    AGENT_REPLY_EXECUTING,
)
from app.agent.nodes import is_handoff_request

# Reuse the existing server-owned contact/consent/config boundary unchanged.
from app.prayer.turn import _source, _contact
from app.prayer.service import now
from app.cell_suggest import catalog, policy, service


def _live_prompt(db, contact, source):
    latest = db.scalars(
        select(Message)
        .where(
            Message.igreja_id == contact.igreja_id,
            Message.conversation_id == contact.conversation_id,
            Message.direcao == "out",
            Message.criado_em < source.criado_em,
        )
        .order_by(Message.criado_em.desc(), Message.id.desc())
        .limit(1)
    ).first()
    if latest is None or latest.agent_reply_state != "ia":
        return False
    raw = latest.agent_privilege_context
    return (
        isinstance(raw, dict)
        and raw.get("kind") == "cell_suggest"
        and raw.get("stage") == "ask"
        and latest.criado_em > now(db) - dt.timedelta(minutes=15)
    )


def run_cell_suggest_turn(
    session_factory,
    runtime_session_factory,
    outcome,
    *,
    igreja_id,
    uses_dedicated_agent_session,
    ownership_guard,
    evolution_client,
):
    if not policy.enabled(igreja_id):
        return None  # No session, table or provider.
    from app.workers import queue_worker as w
    from app.agent.nodes import route_cell_suggest_intent
    from app.domain.agent_reply import AGENT_REPLY_NO_RESPONSE

    provider_id = w._agent_reply_idempotency_key(outcome)
    if provider_id is None or outcome.inbound_message_id is None:
        return None
    with runtime_session_factory() as db:
        w._scope_agent_execution_session(
            db, outcome, dedicated=uses_dedicated_agent_session
        )
        source = _source(db, outcome)
        if source is None or source.tipo != "texto" or not source.texto:
            return None
        # Keep opt-out and crisis on the existing priority paths, before this flow.
        if consent.is_optout_request(source.texto) or is_handoff_request(source.texto):
            return None
        contact = _contact(db, outcome)
        if contact is None:
            return None
        pending = _live_prompt(db, contact, source)
        command, bairro = route_cell_suggest_intent(source.texto, pending=pending)
        candidate = command != "none"
        if not candidate:
            return None
    intent = w._reserve_agent_reply_intent(
        session_factory, outcome, intent_provider_message_id=provider_id
    )
    if intent is None:
        return w.AgentRunDisposition.COMPLETED
    lease = w._AgentExecutionLease(session_factory, outcome, provider_id)
    if not lease.acquire():
        return w.AgentRunDisposition.IN_FLIGHT
    try:
        intent = w._load_agent_reply_intent(
            session_factory, outcome, intent_provider_message_id=provider_id
        )
        if intent is None:
            return w.AgentRunDisposition.COMPLETED
        if intent.state == AGENT_REPLY_EXECUTING:
            w._quarantine_agent_execution(session_factory, outcome, intent)
            return w.AgentRunDisposition.COMPLETED
        if intent.state == AGENT_REPLY_RESERVED:
            if ownership_guard is not None:
                ownership_guard()
            with runtime_session_factory() as db:
                w._scope_agent_execution_session(
                    db, outcome, dedicated=uses_dedicated_agent_session
                )
                contact = _contact(db, outcome)
                reply = db.execute(
                    select(Message)
                    .where(
                        Message.id == intent.id,
                        Message.igreja_id == igreja_id,
                        Message.agent_reply_state == AGENT_REPLY_RESERVED,
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                if reply is None:
                    return w.AgentRunDisposition.COMPLETED
                if contact is None or not policy.enabled(igreja_id):
                    reply.agent_reply_state = AGENT_REPLY_NO_RESPONSE
                else:
                    source = _source(db, outcome)
                    command, bairro = route_cell_suggest_intent(
                        source.texto, pending=_live_prompt(db, contact, source)
                    )
                    response, stage, bairro = service.resolve(
                        db, igreja_id=igreja_id, bairro=bairro
                    )
                    if command == "none":
                        reply.agent_reply_state = AGENT_REPLY_NO_RESPONSE
                        db.commit()
                        return w.AgentRunDisposition.COMPLETED
                    reply.texto = response
                    reply.agent_reply_state = AGENT_REPLY_PENDING
                    reply.public_info_reply = False
                    reply.agent_privilege_context = {
                        "kind": "cell_suggest",
                        "inbound_message_id": str(source.id),
                        "person_id": str(contact.pessoa_id),
                        "bairro": bairro,
                        "stage": stage,
                    }
                if ownership_guard is not None:
                    ownership_guard()
                db.commit()  # Workflow reply commits before delivery.
            intent = w._load_agent_reply_intent(
                session_factory, outcome, intent_provider_message_id=provider_id
            )
        if intent is not None:
            w._deliver_agent_reply_intent(
                session_factory,
                outcome,
                intent,
                ownership_guard,
                evolution_client=evolution_client,
            )
    except SQLAlchemyError:
        # DBAPI exceptions contain bound pastoral text; never let them reach logs.
        raise RuntimeError("Cell suggestion storage operation failed") from None
    finally:
        lease.close()
    return w.AgentRunDisposition.COMPLETED


def reply_still_authorized(db, message, *, conversation, recipient_phone, instance):
    raw = message.agent_privilege_context
    if (
        type(raw) is not dict
        or set(raw) != {"kind", "inbound_message_id", "person_id", "bairro", "stage"}
        or raw.get("kind") != "cell_suggest"
        or not policy.enabled(message.igreja_id)
    ):
        return False
    try:
        source_id, person_id = (
            uuid.UUID(raw["inbound_message_id"]),
            uuid.UUID(raw["person_id"]),
        )
    except (ValueError, TypeError, AttributeError):
        return False
    source = db.get(Message, source_id)
    if source is None:
        return False
    outcome = SimpleNamespace(
        igreja_id=message.igreja_id,
        conversation_id=conversation.id,
        inbound_message_id=source_id,
        provider_message_id=source.provider_message_id,
        telefone=recipient_phone,
        instance=instance,
    )
    contact = _contact(db, outcome)
    if contact is None or contact.pessoa_id != person_id:
        return False
    response, stage, bairro = service.resolve(
        db, igreja_id=message.igreja_id, bairro=raw["bairro"]
    )
    if raw["stage"] == "ask":
        return raw["bairro"] is None and message.texto in {
            catalog.ASK,
            catalog.AMBIGUOUS,
        }
    # Re-read public permission and facts before every delivery/retry.
    return (
        message.texto == response and raw["stage"] == stage and raw["bairro"] == bairro
    )


def mark_delivered(db, message):
    if message.agent_privilege_context.get("stage") == "handoff":
        from app.db.models import Conversation
        from app.services.conversation_handoff import (
            mark_conversation_for_handoff_locked,
        )

        conv = db.scalar(
            select(Conversation)
            .where(
                Conversation.id == message.conversation_id,
                Conversation.igreja_id == message.igreja_id,
            )
            .with_for_update()
        )
        if conv is not None:
            mark_conversation_for_handoff_locked(db, conversation=conv)
