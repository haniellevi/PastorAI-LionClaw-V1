"""Contact-only V4 turn using the existing durable reply fence and transport."""

import datetime as dt
import uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.agent.nodes import is_handoff_request
from app.db.models import (
    AgentConfig,
    Igreja,
    LlmCredential,
    Message,
    WhatsappConnection,
)
from app.domain import consent
from app.domain.agent_reply import (
    AGENT_REPLY_PENDING,
    AGENT_REPLY_RESERVED,
    AGENT_REPLY_EXECUTING,
)
from app.prayer import catalog, policy, service
from app.prayer.models import PrayerProposal


def _source(db, outcome):
    return db.execute(
        select(Message).where(
            Message.id == outcome.inbound_message_id,
            Message.igreja_id == outcome.igreja_id,
            Message.conversation_id == outcome.conversation_id,
            Message.provider_message_id == outcome.provider_message_id,
            Message.direcao == "in",
            Message.autor == "contato",
        )
    ).scalar_one_or_none()


def _contact(db, outcome):
    source = _source(db, outcome)
    if source is None:
        return None
    settings = service.get_settings()
    if not settings.external_sends_enabled:
        return None
    church = db.execute(
        select(Igreja).where(Igreja.id == outcome.igreja_id)
    ).scalar_one_or_none()
    config = db.execute(
        select(AgentConfig).where(
            AgentConfig.igreja_id == outcome.igreja_id, AgentConfig.ativo.is_(True)
        )
    ).scalar_one_or_none()
    credential = db.execute(
        select(LlmCredential.id).where(
            LlmCredential.igreja_id == outcome.igreja_id,
            LlmCredential.provedor == "openai",
            LlmCredential.validado.is_(True),
            LlmCredential.ativo.is_(True),
        )
    ).first()
    connection = db.execute(
        select(WhatsappConnection.id).where(
            WhatsappConnection.igreja_id == outcome.igreja_id,
            WhatsappConnection.instance == outcome.instance,
        )
    ).first()
    from app.deps import BLOCKING_IGREJA_STATUSES

    if (
        church is None
        or church.status in BLOCKING_IGREJA_STATUSES
        or config is None
        or credential is None
        or connection is None
    ):
        return None
    return service.resolve_contact(
        db,
        igreja_id=outcome.igreja_id,
        conversation_id=outcome.conversation_id,
        inbound_message_id=source.id,
        provider_id=source.provider_message_id,
        phone=outcome.telefone,
    )


def _active(db, contact, *, include_expired=False):
    statement = select(PrayerProposal).where(
        PrayerProposal.igreja_id == contact.igreja_id,
        PrayerProposal.conversation_id == contact.conversation_id,
        PrayerProposal.state.in_(("collecting", "pending")),
    )
    if not include_expired:
        statement = statement.where(PrayerProposal.expires_at > service.now(db))
    return db.execute(statement.with_for_update()).scalar_one_or_none()


def _handle(db, contact, inbound, reply):
    # The real current router delegates to the closed contact catalog, not Jev.
    from app.agent.nodes import route_prayer_intent

    # Include expired active-state rows here only to retire them before a new draft.
    proposal = _active(db, contact, include_expired=True)
    command = route_prayer_intent(inbound.texto or "", pending=proposal is not None)
    timestamp = service.now(db)
    if proposal is not None and (
        proposal.term_version != contact.term_version
        or proposal.expires_at <= timestamp
    ):
        proposal.state = "expired"
        db.flush()
        proposal = None
        if catalog.normalized(inbound.texto or "") == "sim":
            return "A confirmação expirou. Envie novamente seu pedido.", None
    if command == "start":
        summary = catalog.own_summary(inbound.texto or "")
        if summary is None:
            return catalog.OWN_QUESTION, None
        if proposal is not None:
            proposal.state = "cancelled"
            db.flush()
        proposal = PrayerProposal(
            igreja_id=contact.igreja_id,
            pessoa_id=contact.pessoa_id,
            conversation_id=contact.conversation_id,
            source_message_id=inbound.id,
            summary=summary,
            term_version=contact.term_version,
            expires_at=timestamp + dt.timedelta(minutes=10),
        )
        db.add(proposal)
        db.flush()
        return catalog.AUDIENCE_QUESTION + " " + catalog.DISCLOSURE, proposal
    if proposal is None:
        return "Não há confirmação de oração pendente. " + catalog.OWN_QUESTION, None
    if command == "cancel":
        proposal.state = "cancelled"
        return (
            "Registro cancelado. A conversa continua visível à equipe que atende o WhatsApp.",
            proposal,
        )
    if command in ("pastoral", "pastoral_lider"):
        if not service.has_pastoral_team(db, contact.igreja_id):
            return (
                "A equipe pastoral precisa ser configurada antes do registro. Procure o atendimento humano.",
                proposal,
            )
        leader = (
            service.current_leader(db, contact) if command == "pastoral_lider" else None
        )
        if command == "pastoral_lider" and leader is None:
            return (
                "Não encontrei um único líder atual autorizado. "
                + catalog.AUDIENCE_QUESTION,
                proposal,
            )
        proposal.audience = command
        proposal.cell_id = leader[0] if leader else None
        proposal.leader_id = leader[1] if leader else None
        proposal.authorization_text = catalog.presentation(
            proposal.summary, command, leader[2] if leader else None
        )
        proposal.summary_message_id = reply.id
        proposal.delivered_at = None
        proposal.expires_at = timestamp + dt.timedelta(minutes=10)
        proposal.state = "pending"
        return proposal.authorization_text, proposal
    if command == "confirm" and proposal.state == "pending":
        try:
            # Authorization failure rolls back only this attempted registration.
            with db.begin_nested():
                catalog.execute(db, contact, proposal, inbound)
        except HTTPException:
            proposal.state = "cancelled"
            return (
                "Não foi possível confirmar: a autorização expirou ou o vínculo mudou. Envie novamente seu pedido.",
                proposal,
            )
        return (
            "Pedido de oração registrado para os destinatários que você autorizou.",
            proposal,
        )
    return (
        catalog.AUDIENCE_QUESTION
        if proposal.state == "collecting"
        else "Para autorizar o resumo e os destinatários exibidos, responda somente SIM ou NÃO.",
        proposal,
    )


def run_prayer_turn(
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
    from app.agent.nodes import route_prayer_intent
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
        # Keep opt-out and crisis on the existing priority paths, before prayer.
        if consent.is_optout_request(source.texto) or is_handoff_request(source.texto):
            return None
        contact = _contact(db, outcome)
        if contact is None:
            return None
        pending = _active(db, contact)
        candidate = (
            route_prayer_intent(source.texto, pending=pending is not None) != "none"
        )
        if not candidate and catalog.normalized(source.texto) == "sim":
            # Keep the existing expiry notice for just one minute after timeout.
            # Terminal proposals never reserve SIM; older timeouts yield to S3.
            recent = _active(db, contact, include_expired=True)
            candidate = recent is not None and recent.expires_at > (
                service.now(db) - dt.timedelta(minutes=1)
            )
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
                    response, proposal = _handle(db, contact, source, reply)
                    reply.texto = response
                    reply.agent_reply_state = AGENT_REPLY_PENDING
                    reply.public_info_reply = False
                    reply.agent_privilege_context = {
                        "kind": "prayer",
                        "inbound_message_id": str(source.id),
                        "person_id": str(contact.pessoa_id),
                        "proposal_id": str(proposal.id) if proposal else None,
                    }
                if ownership_guard is not None:
                    ownership_guard()
                db.commit()  # Request and pending reply are one atomic transaction.
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
        raise RuntimeError("Prayer storage operation failed") from None
    finally:
        lease.close()
    return w.AgentRunDisposition.COMPLETED


def reply_still_authorized(db, message, *, conversation, recipient_phone, instance):
    """Fresh contact/config/flag/recipient checks at every existing send fence."""
    raw = message.agent_privilege_context
    if (
        type(raw) is not dict
        or set(raw) != {"kind", "inbound_message_id", "person_id", "proposal_id"}
        or raw.get("kind") != "prayer"
        or not policy.enabled(message.igreja_id)
    ):
        return False
    try:
        source_id = uuid.UUID(raw["inbound_message_id"])
        person_id = uuid.UUID(raw["person_id"])
    except (ValueError, TypeError, AttributeError):
        return False
    source = db.execute(
        select(Message).where(
            Message.id == source_id,
            Message.igreja_id == message.igreja_id,
            Message.conversation_id == conversation.id,
        )
    ).scalar_one_or_none()
    if source is None:
        return False
    from types import SimpleNamespace

    outcome = SimpleNamespace(
        igreja_id=message.igreja_id,
        conversation_id=conversation.id,
        inbound_message_id=source.id,
        provider_message_id=source.provider_message_id,
        telefone=recipient_phone,
        instance=instance,
    )
    contact = _contact(db, outcome)
    if contact is None or contact.pessoa_id != person_id:
        return False
    if raw["proposal_id"]:
        try:
            pid = uuid.UUID(raw["proposal_id"])
        except (ValueError, TypeError):
            return False
        proposal = db.execute(
            select(PrayerProposal).where(
                PrayerProposal.id == pid,
                PrayerProposal.igreja_id == message.igreja_id,
                PrayerProposal.conversation_id == conversation.id,
                PrayerProposal.pessoa_id == person_id,
            )
        ).scalar_one_or_none()
        if proposal is None:
            return False
        if message.id == proposal.summary_message_id:
            if (
                proposal.state != "pending"
                or proposal.expires_at <= service.now(db)
                or message.texto != proposal.authorization_text
            ):
                return False
            if proposal.audience == "pastoral_lider":
                leader = service.current_leader(db, contact)
                if leader is None or leader[:2] != (
                    proposal.cell_id,
                    proposal.leader_id,
                ):
                    return False
    return True


def invalidate_reply(db, message):
    raw = message.agent_privilege_context or {}
    if raw.get("kind") != "prayer" or not raw.get("proposal_id"):
        return
    try:
        pid = uuid.UUID(raw["proposal_id"])
    except (ValueError, TypeError):
        return
    row = db.execute(
        select(PrayerProposal)
        .where(
            PrayerProposal.id == pid,
            PrayerProposal.igreja_id == message.igreja_id,
            PrayerProposal.conversation_id == message.conversation_id,
            PrayerProposal.state.in_(("collecting", "pending")),
        )
        .with_for_update()
    ).scalar_one_or_none()
    if row is not None:
        row.state = "cancelled"


def mark_delivered(db, message):
    """Start confirmation window only after durable accepted transport."""
    proposal = db.execute(
        select(PrayerProposal)
        .where(
            PrayerProposal.igreja_id == message.igreja_id,
            PrayerProposal.conversation_id == message.conversation_id,
            PrayerProposal.summary_message_id == message.id,
            PrayerProposal.state == "pending",
        )
        .with_for_update()
    ).scalar_one_or_none()
    if proposal is not None and proposal.delivered_at is None:
        proposal.delivered_at = service.now(db)
        proposal.expires_at = proposal.delivered_at + dt.timedelta(minutes=10)
