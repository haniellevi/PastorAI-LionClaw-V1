"""Confirmed Enviar requests on the existing durable reply and transport pipeline."""

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
from app.enviar_whatsapp import catalog, policy, service
from fastapi import HTTPException


def run_enviar_turn(
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
    from app.agent.nodes import route_enviar_intent
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
        pending = _proposal(db, contact, source)
        command, _ = route_enviar_intent(source.texto, pending=pending is not None)
        if source.texto.strip().casefold() == 'sim' and _recent_receipt(db, contact, source) is not None:
            command = 'confirm'
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
                    response, metadata = _handle(db, contact, source)
                    reply.texto = response
                    reply.agent_reply_state = AGENT_REPLY_PENDING
                    reply.public_info_reply = False
                    reply.agent_privilege_context = dict(kind="enviar", inbound_message_id=str(source.id),
                        person_id=str(contact.pessoa_id), **metadata)
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
        raise RuntimeError("Enviar storage operation failed") from None
    finally:
        lease.close()
    return w.AgentRunDisposition.COMPLETED


def _latest(db, contact, source):
    latest = db.scalars(select(Message).where(
        Message.igreja_id == contact.igreja_id, Message.conversation_id == contact.conversation_id,
        Message.direcao == 'out', Message.criado_em < source.criado_em,
    ).order_by(Message.criado_em.desc(), Message.id.desc()).limit(1)).first()
    return latest


def _recent_receipt(db, contact, source):
    latest = _latest(db, contact, source)
    if latest is None or latest.agent_reply_state not in {'ia', AGENT_REPLY_PENDING}:
        return None
    raw = latest.agent_privilege_context or {}
    if (raw.get('kind') == 'enviar' and raw.get('stage') in {'receipt', 'consumed'}
        and raw.get('person_id') == str(contact.pessoa_id)
        and latest.criado_em > now(db) - dt.timedelta(minutes=10)):
        return dict(raw, delivery_pending=latest.agent_reply_state == AGENT_REPLY_PENDING)
    return None


def _proposal(db, contact, source):
    # Contact resolution already holds the conversation lock: concurrent SIMs serialize.
    latest = _latest(db, contact, source)
    if latest is None or latest.agent_reply_state != 'ia':
        return None
    raw = latest.agent_privilege_context or {}
    if (raw.get('kind') != 'enviar' or raw.get('stage') != 'proposal'
        or raw.get('person_id') != str(contact.pessoa_id)
        or raw.get('term_version') != contact.term_version
        or latest.criado_em <= now(db) - dt.timedelta(minutes=10)):
        return None
    try:
        delivered = dt.datetime.fromisoformat(raw['delivered_at'])
        if not delivered.tzinfo or not delivered < source.criado_em <= delivered + dt.timedelta(minutes=10):
            return None
    except (KeyError, ValueError, TypeError):
        return None
    return latest


def mark_delivered(db, message):
    raw = message.agent_privilege_context or {}
    if raw.get('kind') == 'enviar' and raw.get('stage') == 'proposal' and not raw.get('delivered_at'):
        message.agent_privilege_context = dict(raw, delivered_at=now(db).isoformat())


def _handle(db, contact, source):
    from app.agent.nodes import route_enviar_intent
    pending = _proposal(db, contact, source)
    recent = _recent_receipt(db, contact, source) if source.texto.strip().casefold() == 'sim' else None
    command, args = route_enviar_intent(source.texto, pending=pending is not None)
    if recent is not None:
        command = 'confirm'
    meta = dict(stage='result', actor_id=None)
    try:
        user = service.actor(db, contact)
        meta['actor_id'] = user.app_user_id
        if command in {'list', 'read', 'history'}:
            response = service.read(db, user, command, args)
            return response, dict(meta, stage='read', query=dict(command=command, args=args))
        if command in {'nominate', 'open'}:
            response, proposal = service.propose(db, user, command, args)
            return response, dict(meta, stage='proposal', proposal=proposal,
                term_version=contact.term_version)
        if command == 'clarify' and pending is not None:
            raw = pending.agent_privilege_context
            # Keep the original delivery deadline; clarification never confirms
            # or extends the proposal and creates no domain request.
            return ('Para registrar a solicitação, responda somente SIM ou NÃO em até 10 minutos da proposta original.',
                dict(meta, stage='proposal', actor_id=raw['actor_id'], proposal=raw['proposal'],
                    term_version=raw['term_version'], delivered_at=raw['delivered_at']))
        if command == 'confirm' and pending is not None:
            raw = pending.agent_privilege_context
            if raw['actor_id'] != user.app_user_id:
                raise HTTPException(403, 'Usuário mudou')
            with db.begin_nested():
                result = catalog.execute(db, user, raw['proposal'])
            pending.agent_privilege_context = dict(raw, stage='consumed')
            return 'Solicitação registrada; aguardando aprovação no painel autenticado.', dict(meta, stage='receipt', request_id=result.id)
        if command == 'confirm' and recent is not None:
            if recent['actor_id'] != user.app_user_id:
                raise HTTPException(403, 'Usuário mudou')
            service.request_visible(db, user, recent['request_id'])
            return ('Solicitação já registrada; aguarde o recibo.' if recent.get('delivery_pending')
                else 'Solicitação já registrada. Nenhuma nova gravação.'), dict(meta, stage='receipt', request_id=recent['request_id'])
        if command == 'cancel' and pending is not None:
            pending.agent_privilege_context = dict(pending.agent_privilege_context, stage='cancelled')
            return 'Proposta cancelada.', meta
        return catalog.HELP, meta
    except ValueError:
        return 'Solicitação inválida. Consulte o painel autenticado.', meta
    except HTTPException as exc:
        if pending is not None:
            pending.agent_privilege_context = dict(pending.agent_privilege_context, stage='cancelled')
        if exc.status_code in {403,404}:
            return 'Sem permissão para esta consulta ou ação no Enviar.', dict(meta, stage='denied')
        return str(exc.detail), meta


def reply_still_authorized(db, message, *, conversation, recipient_phone, instance):
    raw = message.agent_privilege_context or {}
    if raw.get('kind') != 'enviar' or not policy.enabled(message.igreja_id):
        return False
    try:
        source_id = uuid.UUID(raw['inbound_message_id'])
        source = db.get(Message, source_id)
        if source is None:
            return False
        outcome = SimpleNamespace(igreja_id=message.igreja_id, conversation_id=conversation.id,
            inbound_message_id=source_id, provider_message_id=source.provider_message_id,
            telefone=recipient_phone, instance=instance)
        contact = _contact(db, outcome)
        if contact is None or str(contact.pessoa_id) != raw['person_id']:
            return False
        if raw['stage'] == 'denied':
            return message.texto == 'Sem permissão para esta consulta ou ação no Enviar.'
        user = service.actor(db, contact)
        if user.app_user_id != raw['actor_id']:
            return False
        if raw['stage'] == 'read':
            return message.texto == service.read(db, user, **raw['query'])
        if raw['stage'] == 'receipt':
            service.request_visible(db, user, raw['request_id'])
        if raw['stage'] == 'proposal':
            # Clarifications carry the original delivery time. A transport
            # retry must not invite confirmation after that proposal expires.
            deadline_start = message.criado_em
            if raw.get('delivered_at'):
                deadline_start = dt.datetime.fromisoformat(raw['delivered_at'])
                if not deadline_start.tzinfo:
                    return False
            if deadline_start <= now(db) - dt.timedelta(minutes=10):
                return False
            savepoint = db.begin_nested()
            try:
                catalog.execute(db, user, raw['proposal'])
            finally:
                savepoint.rollback()
        return True
    except (HTTPException, KeyError, ValueError, TypeError):
        return False
