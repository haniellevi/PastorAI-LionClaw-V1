"""S3 turn boundary: local confirmations, external choices, atomic effects.

All provider calls happen between closed database sessions. The existing
outbound ledger remains the only transport; proposals never send directly.
"""
from __future__ import annotations

import hashlib
import time
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any


def confirmation_word(text: object) -> str:
    if type(text) is not str:
        return 'other'
    normalized = ''.join(c for c in unicodedata.normalize('NFKD', text).casefold()
                         if not unicodedata.combining(c)).strip()
    if normalized in {'sim', 'confirmo'}:
        return 'confirm'
    if normalized in {'nao', 'cancela', 'cancelar'}:
        return 'reject'
    return 'other'


def _enabled(igreja_id: object) -> bool:
    from app.services.whatsapp_privilege import privilege_enabled_from_environment
    return privilege_enabled_from_environment(igreja_id)


@contextmanager
def _session(factory, outcome, *, dedicated=False):
    from app.workers.queue_worker import _scope_agent_execution_session
    session = factory()
    try:
        _scope_agent_execution_session(session, outcome, dedicated=dedicated)
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def reply_metadata(
    context,
    *,
    kind: str,
    proposal_id: uuid.UUID | None = None,
    audio_input_id: uuid.UUID | None = None,
    agenda: dict[str, object] | None = None,
    consolidation: dict[str, object] | None = None,
) -> dict:
    result = dict(inbound_message_id=str(context.inbound_message_id),
                  context_fingerprint=context.context_fingerprint,
                  sensitive=context.sensitive, kind=kind)
    if proposal_id is not None:
        result['proposal_id'] = str(proposal_id)
    if audio_input_id is not None:
        result['audio_input_id'] = str(audio_input_id)
    if kind == 'agenda':
        from app.services.whatsapp_agenda import valid_agenda_reply_metadata
        if not valid_agenda_reply_metadata({'agenda': agenda}):
            raise ValueError('agenda metadata')
        result['agenda'] = dict(agenda)
    elif agenda is not None:
        raise ValueError('agenda metadata')
    if kind == 'consolidation':
        from app.services.consolidation_privileged import (
            valid_pending_consolidation_reply_metadata,
        )

        if not valid_pending_consolidation_reply_metadata(consolidation):
            raise ValueError('consolidation metadata')
        result['consolidation'] = dict(consolidation)
    elif consolidation is not None:
        raise ValueError('consolidation metadata')
    if context.proof_id is not None:
        result['proof_id'] = str(context.proof_id)
    return result


def reply_still_authorized(session, message, *, conversation, recipient_phone, instance) -> bool:
    """Revalidate every S3 reply immediately before transport, including retry."""
    raw = message.agent_privilege_context
    if raw is None:
        return False
    if not _enabled(message.igreja_id):
        return False
    from sqlalchemy import select
    from app.db.models import WhatsappConnection
    from app.domain.phone import normalize_phone
    if (not normalize_phone(recipient_phone or '')
        or normalize_phone(recipient_phone or '') != normalize_phone(conversation.telefone or '')):
        return False
    connection = session.execute(select(WhatsappConnection.id).where(
        WhatsappConnection.igreja_id == message.igreja_id,
        WhatsappConnection.instance == instance,
    )).scalar_one_or_none()
    if connection is None:
        return False
    from app.services.whatsapp_privilege import PrivilegeContext, resolve_whatsapp_privilege_context
    required = {'inbound_message_id','context_fingerprint','sensitive','kind'}
    try:
        if (
            type(raw) is not dict
            or not required <= raw.keys()
            or type(raw['sensitive']) is not bool
            or raw['kind'] not in {
                'summary', 'receipt', 'readonly', 'challenge', 'clarify', 'audio_notice',
                'agenda', 'consolidation',
            }
        ):
            return False
        if raw['kind'] == 'agenda':
            from app.services.whatsapp_agenda import valid_agenda_reply_metadata
            if (
                raw.keys() - required - {'proof_id', 'agenda'}
                or not valid_agenda_reply_metadata({'agenda': raw.get('agenda')})
            ):
                return False
        elif raw['kind'] == 'consolidation':
            from app.services.consolidation_privileged import (
                valid_pending_consolidation_reply_metadata,
            )

            if (
                raw.keys() - required - {'proof_id', 'consolidation'}
                or not valid_pending_consolidation_reply_metadata(raw.get('consolidation'))
            ):
                return False
        elif raw.keys() - required - {'proposal_id','proof_id','audio_input_id'}:
            return False
        context = resolve_whatsapp_privilege_context(session, igreja_id=message.igreja_id,
            conversation_id=message.conversation_id,
            inbound_message_id=uuid.UUID(raw['inbound_message_id']), sensitive=raw['sensitive'])
        valid = (type(context) is PrivilegeContext
                and context.context_fingerprint == raw['context_fingerprint']
                and (str(context.proof_id) if context.proof_id else None) == raw.get('proof_id'))
        if valid and raw['kind'] == 'challenge':
            from sqlalchemy import func
            from app.db.models import AgentIdentityChallenge
            latest = session.execute(select(AgentIdentityChallenge).where(
                AgentIdentityChallenge.igreja_id == message.igreja_id,
                AgentIdentityChallenge.conversation_id == message.conversation_id,
            ).order_by(AgentIdentityChallenge.sequence.desc()).limit(1)).scalar_one_or_none()
            return (latest is not None and latest.pessoa_id == context.pessoa_id
                and latest.issued_from_message_id == context.inbound_message_id
                and latest.challenge_expires_at > session.execute(select(func.clock_timestamp())).scalar_one())
        if valid and raw['kind'] == 'audio_notice':
            from app.services.cell_report_audio_service import audio_notice_still_pending
            return audio_notice_still_pending(
                session,
                igreja_id=message.igreja_id,
                pessoa_id=context.pessoa_id,
                conversation_id=message.conversation_id,
                notice_message_id=message.id,
            )
        if valid and raw['kind'] == 'agenda':
            from app.services.whatsapp_agenda import (
                agenda_enabled_from_environment,
                agenda_reply_still_authorized,
            )
            return (
                agenda_enabled_from_environment(message.igreja_id)
                and agenda_reply_still_authorized(
                    session,
                    message=message,
                    conversation=conversation,
                    context=context,
                )
            )
        if valid and raw['kind'] == 'consolidation':
            from app.services.consolidation_privileged import (
                consolidation_pending_reply_still_authorized,
            )

            return consolidation_pending_reply_still_authorized(
                session,
                context=context,
                response=message.texto,
                projection_sha256=raw['consolidation']['projection_sha256'],
            )
        audio_input_id = raw.get('audio_input_id')
        if audio_input_id is not None:
            try:
                parsed_audio_input_id = uuid.UUID(audio_input_id)
            except (TypeError, ValueError, AttributeError):
                return False
            from app.services.cell_report_audio_service import audio_summary_still_authorized

            if not audio_summary_still_authorized(
                session,
                igreja_id=message.igreja_id,
                conversation_id=message.conversation_id,
                pessoa_id=context.pessoa_id,
                audio_input_id=parsed_audio_input_id,
            ):
                return False
        if not valid or raw['kind'] != 'summary':
            return valid
        # Revalidate the target as well as the actor before every summary send.
        # A member may have left the cell while transport was awaiting retry.
        from app.db.models import AgentActionProposal
        from app.services.agent_action_proposals import canonical_arguments_sha256
        from app.services.agent_privilege_catalog import build_catalog
        proposal = session.execute(select(AgentActionProposal).where(
            AgentActionProposal.id == uuid.UUID(raw['proposal_id']),
            AgentActionProposal.igreja_id == message.igreja_id,
            AgentActionProposal.conversation_id == message.conversation_id,
            AgentActionProposal.summary_message_id == message.id,
            AgentActionProposal.source_message_id == context.inbound_message_id,
            AgentActionProposal.state.in_(('preparada', 'pendente')),
        )).scalar_one_or_none()
        if (proposal is None or proposal.scope_fingerprint != context.scope_fingerprint
            or canonical_arguments_sha256(proposal.arguments_json) != proposal.arguments_sha256
            or hashlib.sha256((message.texto or '').encode()).hexdigest() != proposal.summary_sha256):
            return False
        if proposal.action == 'enviar_relatorio_celula':
            from app.services.cell_report_v1a_service import v1a_summary_still_authorized
            return v1a_summary_still_authorized(
                session,
                proposal=proposal,
                context=context,
                summary_message=message,
            )
        _, targets = build_catalog(session, context)
        return any(target.code == proposal.action
            and dict(target.arguments) == proposal.arguments_json
            and _action_summary(target.summary) == message.texto for target in targets.values())
    except (ValueError, TypeError, KeyError):
        return False


def promote_delivered_proposal(session, message) -> None:
    raw = message.agent_privilege_context
    if type(raw) is not dict:
        return
    if raw.get('kind') == 'audio_notice':
        from app.services.cell_report_audio_service import mark_audio_consent_notice_delivered
        mark_audio_consent_notice_delivered(
            session,
            igreja_id=message.igreja_id,
            conversation_id=message.conversation_id,
            notice_message_id=message.id,
        )
        return
    if raw.get('kind') == 'receipt':
        try:
            proposal_id = uuid.UUID(raw['proposal_id'])
        except (KeyError, TypeError, ValueError, AttributeError):
            return
        from app.services.cell_report_audio_service import (
            clear_audio_transcript_after_official_report,
        )

        clear_audio_transcript_after_official_report(
            session,
            igreja_id=message.igreja_id,
            conversation_id=message.conversation_id,
            proposal_id=proposal_id,
        )
        return
    if raw.get('kind') != 'summary':
        return
    from app.services.agent_action_proposals import promote_action_proposal_after_delivery
    promote_action_proposal_after_delivery(session, igreja_id=message.igreja_id,
        conversation_id=message.conversation_id, proposal_id=uuid.UUID(raw['proposal_id']),
        summary_message_id=message.id)



def invalidate_undelivered_proposal(session, message) -> None:
    raw = message.agent_privilege_context
    if type(raw) is not dict:
        return
    if raw.get('kind') == 'audio_notice':
        from app.services.cell_report_audio_service import invalidate_audio_consent_notice
        invalidate_audio_consent_notice(
            session,
            igreja_id=message.igreja_id,
            conversation_id=message.conversation_id,
            notice_message_id=message.id,
        )
        return
    if raw.get('kind') == 'agenda':
        from sqlalchemy import select
        from app.db.models import Conversation
        from app.services.secretaria_offer import cancel_secretaria_offer_for_delivery
        conversation = session.execute(select(Conversation).where(
            Conversation.id == message.conversation_id,
            Conversation.igreja_id == message.igreja_id,
        ).with_for_update()).scalar_one_or_none()
        if conversation is not None:
            cancel_secretaria_offer_for_delivery(
                conversation,
                outbound_message_id=message.id,
            )
        return
    audio_input_id = raw.get('audio_input_id')
    if audio_input_id is not None:
        try:
            uuid.UUID(audio_input_id)
        except (TypeError, ValueError, AttributeError):
            return
        from app.services.cell_report_audio_service import cancel_audio_inputs_for_conversation

        cancel_audio_inputs_for_conversation(
            session,
            igreja_id=message.igreja_id,
            conversation_id=message.conversation_id,
            reason="audio_reply_suppressed",
        )
        return
    if raw.get('kind') != 'summary':
        return
    from app.services.agent_action_proposals import invalidate_action_proposal_for_delivery
    invalidate_action_proposal_for_delivery(session, igreja_id=message.igreja_id,
        conversation_id=message.conversation_id, proposal_id=uuid.UUID(raw['proposal_id']))


def run_privileged_turn(session_factory, runtime_session_factory, outcome, *,
        igreja_id, turn_identity, uses_dedicated_agent_session,
        ownership_guard, evolution_client):
    audio_result = _run_audio_local_turn(
        session_factory,
        runtime_session_factory,
        outcome,
        igreja_id=igreja_id,
        uses_dedicated_agent_session=uses_dedicated_agent_session,
        ownership_guard=ownership_guard,
        evolution_client=evolution_client,
    )
    if audio_result is not None:
        return audio_result
    if not _enabled(igreja_id):
        return None
    return _run_enabled_turn(session_factory, runtime_session_factory, outcome,
        igreja_id=igreja_id, turn_identity=turn_identity,
        uses_dedicated_agent_session=uses_dedicated_agent_session,
        ownership_guard=ownership_guard, evolution_client=evolution_client)


def _lock_reply(session, outcome, provider_id):
    from sqlalchemy import select
    from app.db.models import Message
    return session.execute(select(Message).where(Message.igreja_id == outcome.igreja_id,
        Message.conversation_id == outcome.conversation_id, Message.provider_message_id == provider_id,
        Message.direcao == 'out', Message.autor == 'ia').with_for_update()).scalar_one_or_none()


def _store_response(
    message,
    context,
    response,
    *,
    kind,
    proposal_id=None,
    agenda=None,
    consolidation=None,
):
    from app.domain.agent_reply import AGENT_REPLY_PENDING, AGENT_REPLY_NO_RESPONSE
    message.texto = response or ''
    message.agent_reply_state = AGENT_REPLY_PENDING if response else AGENT_REPLY_NO_RESPONSE
    message.public_info_reply = False
    message.agent_privilege_context = reply_metadata(
        context,
        kind=kind,
        proposal_id=proposal_id,
        agenda=agenda,
        consolidation=consolidation,
    )


def _stored_receipt_response(message, proposal_id) -> str | None:
    """Reuse the committed receipt text instead of rebuilding it on retry."""

    response = getattr(message, 'texto', None)
    metadata = getattr(message, 'agent_privilege_context', None)
    if (
        type(response) is str
        and response
        and type(metadata) is dict
        and metadata.get('kind') == 'receipt'
        and metadata.get('proposal_id') == str(proposal_id)
    ):
        return response
    return None


def _action_summary(summary: str) -> str:
    return f'{summary}. Confirma esta ação? Responda SIM ou NÃO. A proposta vale por 10 minutos.'


def _execute(session, execution):
    from app.services.agent_action_proposals import ActionEffect, ProposalExecutionDenied
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError
    if execution.action.value == 'enviar_relatorio_celula':
        from app.services.cell_report_v1a_service import execute_v1a_cell_report_proposal
        return execute_v1a_cell_report_proposal(session, execution)
    if execution.action.value == 'configurar_lembrete_agenda':
        from app.services.notification_outbox import execute_agenda_reminder_subscription
        return execute_agenda_reminder_subscription(session, execution)
    if execution.action.value == 'configurar_lembrete_consolidacao':
        from app.services.notification_outbox import execute_consolidation_reminder_subscription
        return execute_consolidation_reminder_subscription(session, execution)
    if execution.action.value == 'marcar_fonovisita_feita':
        from app.services.agent_privilege_catalog import _user
        from app.services.consolidation_workflow import complete_fonovisita

        try:
            result = complete_fonovisita(
                session,
                _user(execution.privilege_context),
                consolidacao_id=uuid.UUID(execution.arguments['consolidacao_id']),
                work_queue_item_id=uuid.UUID(execution.arguments['work_queue_item_id']),
                expected_assignment_revision=execution.arguments['assignment_revision'],
                whatsapp=True,
            )
        except HTTPException as exc:
            if exc.status_code >= 500:
                raise
            raise ProposalExecutionDenied('domain_denied') from None
        except (KeyError, TypeError, ValueError):
            raise ProposalExecutionDenied('domain_denied') from None
        return ActionEffect(
            receipt_text='Fonovisita confirmada.',
            opaque_effect_id=result.work_queue_item.id,
        )
    if execution.action.value == 'atribuir_consolidacao':
        from app.services.agent_privilege_catalog import _user
        from app.services.consolidation_workflow import assign_consolidacao

        try:
            result = assign_consolidacao(
                session,
                _user(execution.privilege_context),
                consolidacao_id=uuid.UUID(execution.arguments['consolidacao_id']),
                responsavel_id=uuid.UUID(execution.arguments['responsavel_id']),
                expected_assignment_revision=execution.arguments['assignment_revision'],
                whatsapp=True,
            )
        except HTTPException as exc:
            if exc.status_code >= 500:
                raise
            raise ProposalExecutionDenied('domain_denied') from None
        except (KeyError, TypeError, ValueError):
            raise ProposalExecutionDenied('domain_denied') from None
        return ActionEffect(
            receipt_text='Consolidação atribuída.',
            opaque_effect_id=result.consolidacao.id,
        )
    from app.services.agent_privilege_catalog import execute_catalog_action
    try:
        effect_id = execute_catalog_action(session, execution.privilege_context,
            execution.action.value, execution.arguments)
    except HTTPException as exc:
        if exc.status_code >= 500:
            raise
        raise ProposalExecutionDenied('domain_denied') from None
    except IntegrityError as exc:
        if getattr(exc.orig, 'pgcode', None) != '23505':
            raise
        raise ProposalExecutionDenied('domain_conflict') from None
    return ActionEffect(receipt_text='Registro confirmado.', opaque_effect_id=uuid.UUID(effect_id))


def _local_confirmation(session, context, outcome, message):
    from app.services.agent_action_proposals import (
        ProposalDisposition, resolve_and_execute_action_proposal,
    )
    word = confirmation_word(outcome.texto)
    disposition = {'confirm': ProposalDisposition.CONFIRM,
                   'reject': ProposalDisposition.REJECT}.get(word, ProposalDisposition.OTHER)
    resolution = resolve_and_execute_action_proposal(session, igreja_id=context.igreja_id,
        conversation_id=context.conversation_id, confirmation_message_id=context.inbound_message_id,
        disposition=disposition, execute=lambda execution: _execute(session, execution))
    if resolution.status == 'no_pending':
        if word in {'confirm', 'reject'}:
            # A second SIM may race the successful commit or retry after it.
            # It cannot become a fresh model-selected action.
            _store_response(message, context, None, kind='clarify')
            return True
        return False
    if resolution.status == 'continue':
        if word != 'confirm':
            return False
        _store_response(message, context, None, kind='clarify', proposal_id=resolution.proposal_id)
        return True
    if resolution.status in {'executed', 'receipt'}:
        receipt_text = (
            resolution.receipt.receipt_text
            if resolution.receipt is not None
            else 'Registro confirmado.'
        )
        response = _stored_receipt_response(message, resolution.proposal_id)
        if response is None:
            if resolution.status == 'executed' and receipt_text == 'Relatório confirmado.':
                from app.services.cell_report_v1a_service import v1a_receipt_text_after_execution

                detailed_receipt = v1a_receipt_text_after_execution(
                    session,
                    context=context,
                    proposal_id=resolution.proposal_id,
                )
                if detailed_receipt is not None:
                    receipt_text = detailed_receipt
            response = f'{receipt_text} Comprovante: {resolution.receipt_id}.'
        kind = 'receipt'
    elif resolution.status == 'delivery_uncertain':
        response = None
        kind = 'clarify'
    else:
        response = 'A proposta foi encerrada sem executar a ação. Envie um novo pedido se desejar.'
        kind = 'clarify'
    _store_response(message, context, response, kind=kind, proposal_id=resolution.proposal_id)
    return True


def _local_audio_consent(session, context, outcome, message):
    """Handle only V1b's explicit audio commands and delivered-notice staging.

    This runs after the existing LGPD, opt-out and human gates have produced a
    current server-resolved context.  It never treats ``SIM`` as audio consent
    and never promotes an audio that arrived before an explicit acceptance.
    """

    from app.services.cell_report_audio import (
        AudioConsentCommand,
        cell_report_audio_enabled_from_environment,
        parse_audio_consent_command,
    )
    from app.services.cell_report_audio_service import (
        AUDIO_CONSENT_NOTICE_TEXT,
        audio_schema_available,
        prepare_audio_consent_notice,
        record_audio_consent_command,
    )

    command = parse_audio_consent_command(outcome.texto)
    enabled = cell_report_audio_enabled_from_environment(context.igreja_id)
    if command is None and not enabled:
        return False
    schema_ready = audio_schema_available(session)
    if command is AudioConsentCommand.REVOKE and schema_ready:
        result = record_audio_consent_command(
            session,
            igreja_id=context.igreja_id,
            pessoa_id=context.pessoa_id,
            conversation_id=context.conversation_id,
            source_message_id=context.inbound_message_id,
            command=command,
        )
        if result.handled:
            _store_response(message, context, None, kind='clarify')
            return True
    if (
        command is AudioConsentCommand.ACCEPT
        and schema_ready
        and enabled
    ):
        result = record_audio_consent_command(
            session,
            igreja_id=context.igreja_id,
            pessoa_id=context.pessoa_id,
            conversation_id=context.conversation_id,
            source_message_id=context.inbound_message_id,
            command=command,
        )
        if result.handled:
            _store_response(message, context, None, kind='clarify')
            return True
    if not (
        schema_ready
        and enabled
    ):
        return False
    notice = prepare_audio_consent_notice(
        session,
        igreja_id=context.igreja_id,
        pessoa_id=context.pessoa_id,
        conversation_id=context.conversation_id,
        inbound_message_id=context.inbound_message_id,
        notice_message_id=message.id,
    )
    if notice is None:
        return False
    _store_response(message, context, AUDIO_CONSENT_NOTICE_TEXT, kind='audio_notice')
    return True


def _persist_rejected_audio_acceptance(session, outcome, provider_id) -> None:
    """Fence one explicit but unauthorized ``ACEITO AUDIO`` inbound.

    A reply-less ledger row is intentionally durable.  It prevents an old
    inbound retried after a human release, config reactivation or relinked
    AppUser from becoming an authorization grant it did not have when first
    processed.  It never sends a response and never changes conversation
    state, so ``PARAR AUDIO`` remains independently available.
    """

    from sqlalchemy import select
    from app.db.models import Conversation, Message
    from app.domain.agent_reply import AGENT_REPLY_NO_RESPONSE

    conversation = session.execute(
        select(Conversation)
        .where(
            Conversation.igreja_id == outcome.igreja_id,
            Conversation.id == outcome.conversation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if conversation is None:
        return
    existing = _lock_reply(session, outcome, provider_id)
    if existing is not None:
        return
    session.add(
        Message(
            id=uuid.uuid4(),
            igreja_id=conversation.igreja_id,
            conversation_id=conversation.id,
            direcao="out",
            autor="ia",
            tipo="texto",
            texto="",
            provider_message_id=provider_id,
            agent_reply_state=AGENT_REPLY_NO_RESPONSE,
            public_info_reply=False,
        )
    )


def _run_audio_local_turn(session_factory, runtime_session_factory, outcome, *,
        igreja_id, uses_dedicated_agent_session, ownership_guard, evolution_client):
    """Handle V1b's typed notice and commands before text-only planning.

    The audio inbound remains a real ``Message`` with no fabricated text.  Its
    one deterministic result is a separately ledgered consent notice.  Explicit
    commands are read again from the persisted inbound by the service before a
    consent event can be written.
    """
    from sqlalchemy import select
    from app.db.models import Conversation, Message
    from app.domain.agent_reply import AGENT_REPLY_NO_RESPONSE, AGENT_REPLY_RESERVED
    from app.services.cell_report_audio import (
        AudioConsentCommand,
        cell_report_audio_enabled_from_environment,
        parse_audio_consent_command,
    )
    from app.services.cell_report_audio_service import (
        audio_notice_required_for_inbound,
        audio_schema_available,
        record_audio_consent_command,
    )
    from app.services.whatsapp_privilege import (
        PrivilegeContext,
        resolve_whatsapp_privilege_context,
    )
    from app.workers import queue_worker as qw

    # The V1b gate must short-circuit before touching optional fields of the
    # legacy outcome.  Withdrawal is deliberately the sole exception: it is a
    # durable refusal and remains available after V1b has been switched off.
    command = parse_audio_consent_command(getattr(outcome, "texto", None))
    enabled = cell_report_audio_enabled_from_environment(igreja_id)
    if command is None and not enabled:
        return None
    if (uses_dedicated_agent_session
            or getattr(outcome, "inbound_message_id", None) is None
            or getattr(outcome, "conversation_id", None) is None):
        return None
    provider_id = qw._agent_reply_idempotency_key(outcome)
    if provider_id is None:
        return None
    stage_notice = False
    with _session(runtime_session_factory, outcome) as session:
        conversation = session.execute(
            select(Conversation).where(
                Conversation.igreja_id == igreja_id,
                Conversation.id == outcome.conversation_id,
            ).with_for_update().execution_options(populate_existing=True)
        ).scalar_one_or_none()
        pessoa_id = getattr(conversation, 'pessoa_id', None)
        if type(pessoa_id) is not uuid.UUID:
            if command is AudioConsentCommand.ACCEPT:
                _persist_rejected_audio_acceptance(session, outcome, provider_id)
                if ownership_guard is not None:
                    ownership_guard()
                session.commit()
                return qw.AgentRunDisposition.COMPLETED
            return None
        if command is None:
            source_type = session.execute(
                select(Message.tipo).where(
                    Message.igreja_id == igreja_id,
                    Message.conversation_id == outcome.conversation_id,
                    Message.id == outcome.inbound_message_id,
                    Message.direcao == 'in',
                )
            ).scalar_one_or_none()
            if source_type != 'audio':
                return None
        if not audio_schema_available(session):
            if command is AudioConsentCommand.ACCEPT:
                _persist_rejected_audio_acceptance(session, outcome, provider_id)
                if ownership_guard is not None:
                    ownership_guard()
                session.commit()
                return qw.AgentRunDisposition.COMPLETED
            return None
        if command is not None:
            # An explicit withdrawal remains available after the feature was
            # disabled; acceptance needs the current V1b deployment gate.
            if command is not AudioConsentCommand.REVOKE and not enabled:
                _persist_rejected_audio_acceptance(session, outcome, provider_id)
                if ownership_guard is not None:
                    ownership_guard()
                session.commit()
                return qw.AgentRunDisposition.COMPLETED
            if command is AudioConsentCommand.ACCEPT:
                # A prior denial writes a durable no-response row keyed to this
                # exact inbound.  Reopening the conversation or relinking an
                # AppUser later must not turn the old command into consent.
                prior = _lock_reply(session, outcome, provider_id)
                if prior is not None:
                    session.commit()
                    return qw.AgentRunDisposition.COMPLETED
                # Acceptance is an authorization grant.  Unlike withdrawal it
                # requires the complete current server-resolved actor context,
                # including active configuration, a live AppUser and a
                # non-human conversation.
                context = resolve_whatsapp_privilege_context(
                    session,
                    igreja_id=igreja_id,
                    conversation_id=outcome.conversation_id,
                    inbound_message_id=outcome.inbound_message_id,
                )
                if type(context) is not PrivilegeContext:
                    _persist_rejected_audio_acceptance(session, outcome, provider_id)
                    if ownership_guard is not None:
                        ownership_guard()
                    session.commit()
                    return qw.AgentRunDisposition.COMPLETED
                pessoa_id = context.pessoa_id
            result = record_audio_consent_command(
                session,
                igreja_id=igreja_id,
                pessoa_id=pessoa_id,
                conversation_id=outcome.conversation_id,
                source_message_id=outcome.inbound_message_id,
                command=command,
            )
            if result.handled:
                if ownership_guard is not None:
                    ownership_guard()
                session.commit()
                return qw.AgentRunDisposition.COMPLETED
            return None
        context = resolve_whatsapp_privilege_context(
            session,
            igreja_id=igreja_id,
            conversation_id=outcome.conversation_id,
            inbound_message_id=outcome.inbound_message_id,
        )
        if type(context) is not PrivilegeContext:
            return None
        stage_notice = audio_notice_required_for_inbound(
            session,
            igreja_id=igreja_id,
            pessoa_id=context.pessoa_id,
            conversation_id=outcome.conversation_id,
            inbound_message_id=outcome.inbound_message_id,
        )
    if not stage_notice:
        # This is a real V1b audio inbound whose consent is already current.
        # It is queued for the durable audio worker, never textual input for
        # Tier A, S3, or the LLM in this synchronous turn.
        return qw.AgentRunDisposition.COMPLETED

    intent = qw._reserve_agent_reply_intent(session_factory, outcome)
    if intent is None:
        return qw.AgentRunDisposition.COMPLETED
    if intent.state != AGENT_REPLY_RESERVED:
        qw._deliver_agent_reply_intent(
            session_factory,
            outcome,
            intent,
            ownership_guard,
            evolution_client=evolution_client,
        )
        return qw.AgentRunDisposition.COMPLETED

    local = False
    with _session(runtime_session_factory, outcome) as session:
        current = resolve_whatsapp_privilege_context(
            session,
            igreja_id=igreja_id,
            conversation_id=outcome.conversation_id,
            inbound_message_id=outcome.inbound_message_id,
        )
        message = _lock_reply(session, outcome, provider_id)
        if (
            type(current) is PrivilegeContext
            and message is not None
            and message.agent_reply_state == AGENT_REPLY_RESERVED
            and audio_notice_required_for_inbound(
                session,
                igreja_id=igreja_id,
                pessoa_id=current.pessoa_id,
                conversation_id=outcome.conversation_id,
                inbound_message_id=outcome.inbound_message_id,
            )
        ):
            local = _local_audio_consent(
                session,
                current,
                type('InboundAudio', (), {'texto': ''})(),
                message,
            )
        if message is not None and message.agent_reply_state == AGENT_REPLY_RESERVED:
            # A concurrent revocation, handoff, or deletion cannot leave a
            # silent reservation recoverable as a model turn.
            message.agent_reply_state = AGENT_REPLY_NO_RESPONSE
            message.texto = ''
        if ownership_guard is not None:
            ownership_guard()
        session.commit()
    if not local:
        return qw.AgentRunDisposition.COMPLETED
    intent = qw._load_agent_reply_intent(session_factory, outcome)
    if intent is not None:
        qw._deliver_agent_reply_intent(
            session_factory,
            outcome,
            intent,
            ownership_guard,
            evolution_client=evolution_client,
        )
    return qw.AgentRunDisposition.COMPLETED


def _run_enabled_turn(session_factory, runtime_session_factory, outcome, *, igreja_id,
        turn_identity, uses_dedicated_agent_session, ownership_guard, evolution_client):
    from app.workers import queue_worker as qw
    from app.agent.runtime import process_inbound_message, _load_tier_a_plan_state
    from app.agent.read_only_info import canonical_public_info_request
    from app.domain.agent_reply import AGENT_REPLY_RESERVED
    from app.services.whatsapp_privilege import (
        PrivilegeContext, PublicWhatsappContext, resolve_whatsapp_privilege_context,
    )
    from app.services.agent_privilege_catalog import (
        build_catalog,
        build_consolidation_catalog,
        consolidation_routing_projection,
    )
    from app.services.agent_privilege_routing import route_privileged_message
    from app.services.crypto import decrypt_secret
    from app.services.llm import LLMClient, LLMError, estimate_cost

    if (uses_dedicated_agent_session or outcome.inbound_message_id is None
        or outcome.conversation_id is None):
        return qw.AgentRunDisposition.COMPLETED
    started = time.monotonic()
    provider_id = qw._agent_reply_idempotency_key(outcome)
    if provider_id is None:
        return qw.AgentRunDisposition.COMPLETED
    existing = qw._load_agent_reply_intent(session_factory, outcome)
    if existing is not None and existing.state != AGENT_REPLY_RESERVED:
        qw._deliver_agent_reply_intent(session_factory, outcome, existing,
            ownership_guard, evolution_client=evolution_client)
        return qw.AgentRunDisposition.COMPLETED
    with _session(runtime_session_factory, outcome) as session:
        kwargs = dict(igreja_id=igreja_id, conversation_id=outcome.conversation_id,
            texto=outcome.texto, inbound_message_id=outcome.inbound_message_id,
            provider_message_id=outcome.provider_message_id, tier_a_preflight=True,
            tier_a_reply_provider_message_id=provider_id, tier_a_ownership_guard=ownership_guard)
        if turn_identity is not None:
            kwargs['turn_identity'] = turn_identity
        prepared = process_inbound_message(session, **kwargs)
    if prepared.reason == 'tier_a_legacy_route':
        return None
    preflight = prepared.preflight
    if preflight is None:
        return qw.AgentRunDisposition.COMPLETED

    routing_usage = ()

    def handoff(reason):
        return qw._persist_tier_a_handoff(runtime_session_factory, outcome,
            uses_dedicated_agent_session=False, plan=preflight,
            decision_payload={'erro': reason}, usage=routing_usage or None, ownership_guard=ownership_guard)

    v3_projection = None
    with _session(runtime_session_factory, outcome) as session:
        context = resolve_whatsapp_privilege_context(session, igreja_id=igreja_id,
            conversation_id=outcome.conversation_id, inbound_message_id=outcome.inbound_message_id)
        if type(context) is PrivilegeContext:
            v3_projection = consolidation_routing_projection(session, context)
    v3_recognized = v3_projection is not None
    if type(context) is PublicWhatsappContext:
        return None
    if type(context) is not PrivilegeContext:
        return handoff('privilege_identity')
    if qw._reserve_agent_reply_intent(session_factory, outcome) is None:
        return qw.AgentRunDisposition.COMPLETED
    with _session(runtime_session_factory, outcome) as session:
        _, _, error = _load_tier_a_plan_state(session, preflight)
        current = resolve_whatsapp_privilege_context(session, igreja_id=igreja_id,
            conversation_id=outcome.conversation_id, inbound_message_id=outcome.inbound_message_id)
        message = _lock_reply(session, outcome, provider_id)
        if message is None or message.agent_reply_state != AGENT_REPLY_RESERVED:
            return qw.AgentRunDisposition.COMPLETED
        if error or type(current) is not PrivilegeContext or current.context_fingerprint != context.context_fingerprint:
            invalid = True
            local = False
        else:
            invalid = False
            # Use the persisted inbound snapshot, never outcome.texto as authority.
            local_outcome = type('InboundText', (), {'texto': preflight.current_text})()
            local = _local_audio_consent(session, current, local_outcome, message)
            if not local:
                local = _local_confirmation(session, current, local_outcome, message)
        if not invalid:
            session.commit()
    if invalid:
        return handoff('privilege_changed')
    if local:
        intent = qw._load_agent_reply_intent(session_factory, outcome)
        if intent is not None:
            qw._deliver_agent_reply_intent(session_factory, outcome, intent,
                ownership_guard, evolution_client=evolution_client)
        return qw.AgentRunDisposition.COMPLETED
    if v3_projection is not None and v3_projection.handoff_only:
        return handoff('privilege_v3_unsafe')
    # Optional Tier A remains a suppression gate before routing. Local pending
    # confirmations above never call Jev. The default release is inert.
    from app.services.semantic_triage import (
        tier_a_enabled_from_environment, get_triage_settings, TIER_A_APPROVED_RELEASE_ID,
    )
    effective = None
    if v3_projection is None and tier_a_enabled_from_environment(igreja_id):
        effective = qw._tier_a_effective_settings(session_factory, get_triage_settings())
        decision = qw._run_tier_a_batch(effective, igreja_id, preflight.current_text,
            min(1.2, max(0.01, started + 9 - time.monotonic())), TIER_A_APPROVED_RELEASE_ID)
        if decision.handoff:
            return handoff('privilege_tier_a')
        if decision.pede_optout:
            return qw._run_active_tier_a_turn(session_factory, runtime_session_factory, outcome,
                igreja_id=igreja_id, turn_identity=turn_identity,
                uses_dedicated_agent_session=False, ownership_guard=ownership_guard,
                evolution_client=evolution_client)
    # V1a collection follows the optional suppression gate. Local pending
    # confirmations above remain deterministic and never call Jev.
    from app.services.cell_report_whatsapp import cell_report_enabled_from_environment
    if v3_projection is None and cell_report_enabled_from_environment(igreja_id):
        from app.services.cell_report_v1a_service import (
            CellReportStageKind,
            CellReportV1aServiceError,
            stage_v1a_cell_report_turn,
        )
        v1a_invalid = False
        v1a_handoff_reason = None
        v1a_reservation = None
        v1a_stage = None
        with _session(runtime_session_factory, outcome) as session:
            _, _, error = _load_tier_a_plan_state(session, preflight)
            current = resolve_whatsapp_privilege_context(
                session,
                igreja_id=igreja_id,
                conversation_id=outcome.conversation_id,
                inbound_message_id=outcome.inbound_message_id,
            )
            message = _lock_reply(session, outcome, provider_id)
            if (
                error
                or type(current) is not PrivilegeContext
                or current.context_fingerprint != context.context_fingerprint
                or message is None
                or message.agent_reply_state != AGENT_REPLY_RESERVED
            ):
                v1a_invalid = True
                v1a_stage = None
                v1a_handoff_reason = 'cell_report_context'
            else:
                v1a_stage = stage_v1a_cell_report_turn(
                    session,
                    context=current,
                    inbound_message_id=outcome.inbound_message_id,
                    text=preflight.current_text,
                    summary_message=message,
                )
                if v1a_stage.kind is CellReportStageKind.SUMMARY:
                    assert v1a_stage.proposal is not None
                    _store_response(
                        message,
                        current,
                        v1a_stage.response,
                        kind='summary',
                        proposal_id=v1a_stage.proposal.proposal_id,
                    )
                    session.commit()
                elif v1a_stage.kind is CellReportStageKind.CLARIFY:
                    _store_response(message, current, v1a_stage.response, kind='clarify')
                    session.commit()
                elif v1a_stage.kind is CellReportStageKind.EXTRACTION:
                    from app.services.cell_report_whatsapp import (
                        CellReportWhatsappError,
                        reserve_v1a_extraction_budget,
                    )
                    try:
                        if (
                            v1a_stage.draft_id is None
                            or v1a_stage.draft_revision is None
                            or v1a_stage.extraction_projection is None
                        ):
                            raise CellReportWhatsappError('reserva de custo indisponível')
                        v1a_reservation = reserve_v1a_extraction_budget(
                            session,
                            igreja_id=igreja_id,
                            draft_id=v1a_stage.draft_id,
                            model=preflight.credential_model,
                            estimate_cost=estimate_cost,
                        )
                        session.commit()
                    except (CellReportWhatsappError, ValueError):
                        v1a_invalid = True
                        v1a_handoff_reason = 'cell_report_budget'
                elif v1a_stage.kind is CellReportStageKind.HUMAN_REQUIRED:
                    if v1a_stage.persist_before_handoff:
                        session.commit()
                    v1a_invalid = True
                    v1a_handoff_reason = 'cell_report_context'
        if v1a_invalid:
            return handoff(v1a_handoff_reason or 'cell_report_context')
        if (
            v1a_stage is not None
            and v1a_stage.kind is CellReportStageKind.EXTRACTION
        ):
            if v1a_reservation is None:
                return handoff('cell_report_budget')
            remaining = started + 9 - time.monotonic()
            if remaining <= 0:
                return handoff('cell_report_timeout')
            try:
                if ownership_guard is not None:
                    ownership_guard()
                extraction = LLMClient(
                    preflight.credential_provedor,
                    decrypt_secret(preflight.credential_key_encrypted),
                    preflight.credential_model,
                ).extract_v1a_cell_report(
                    v1a_stage.extraction_projection or {},
                    timeout_seconds=min(4.0, remaining),
                )
                from app.services.cell_report_whatsapp import actual_v1a_extraction_microusd
                actual_microusd = actual_v1a_extraction_microusd(
                    extraction.usage,
                    estimate_cost,
                )
                routing_usage = (extraction.usage,)
            except (LLMError, ValueError, TypeError):
                return handoff('cell_report_extraction')
            with _session(runtime_session_factory, outcome) as session:
                _, _, error = _load_tier_a_plan_state(session, preflight)
                current = resolve_whatsapp_privilege_context(
                    session,
                    igreja_id=igreja_id,
                    conversation_id=outcome.conversation_id,
                    inbound_message_id=outcome.inbound_message_id,
                )
                message = _lock_reply(session, outcome, provider_id)
                if (
                    error
                    or type(current) is not PrivilegeContext
                    or current.context_fingerprint != context.context_fingerprint
                    or message is None
                    or message.agent_reply_state != AGENT_REPLY_RESERVED
                ):
                    v1a_invalid = True
                    v1a_handoff_reason = 'cell_report_context_changed'
                    v1a_stage = None
                else:
                    from app.services.cell_report_v1a_service import (
                        complete_v1a_extraction_after_provider,
                    )
                    try:
                        v1a_stage = complete_v1a_extraction_after_provider(
                            session,
                            context=current,
                            inbound_message_id=outcome.inbound_message_id,
                            summary_message=message,
                            draft_id=v1a_stage.draft_id,
                            expected_revision=v1a_stage.draft_revision,
                            projection=v1a_stage.extraction_projection,
                            extracted_payload=extraction.payload,
                            reservation_id=v1a_reservation.reservation_id,
                            actual_microusd=actual_microusd,
                        )
                    except (CellReportV1aServiceError, ValueError):
                        v1a_invalid = True
                        v1a_handoff_reason = 'cell_report_extraction_invalid'
                        v1a_stage = None
                    if v1a_stage is None:
                        pass
                    elif v1a_stage.kind is CellReportStageKind.SUMMARY:
                        assert v1a_stage.proposal is not None
                        _store_response(
                            message,
                            current,
                            v1a_stage.response,
                            kind='summary',
                            proposal_id=v1a_stage.proposal.proposal_id,
                        )
                    elif v1a_stage.kind is CellReportStageKind.CLARIFY:
                        _store_response(message, current, v1a_stage.response, kind='clarify')
                    elif v1a_stage.kind is CellReportStageKind.HUMAN_REQUIRED:
                        v1a_invalid = True
                        v1a_handoff_reason = 'cell_report_context_changed'
                    if not v1a_invalid or (
                        v1a_stage is not None and v1a_stage.persist_before_handoff
                    ):
                        from app.agent.masking import log_ai_usage
                        log_ai_usage(
                            session,
                            igreja_id=igreja_id,
                            usage=extraction.usage,
                            ferramenta='cell_report_extraction',
                        )
                        session.commit()
                        # The durable extraction audit is now committed. A
                        # following fail-safe handoff must not record it again
                        # as generic S3 routing usage.
                        routing_usage = ()
            if v1a_invalid:
                return handoff(v1a_handoff_reason or 'cell_report_context_changed')
        if v1a_stage is not None and v1a_stage.kind in {
            CellReportStageKind.SUMMARY,
            CellReportStageKind.CLARIFY,
        }:
            intent = qw._load_agent_reply_intent(session_factory, outcome)
            if intent is not None:
                qw._deliver_agent_reply_intent(
                    session_factory,
                    outcome,
                    intent,
                    ownership_guard,
                    evolution_client=evolution_client,
                )
            return qw.AgentRunDisposition.COMPLETED
    if v3_projection is None and canonical_public_info_request(preflight.current_text) is not None:
        return None
    routing_text = preflight.current_text
    with _session(runtime_session_factory, outcome) as session:
        _, _, error = _load_tier_a_plan_state(session, preflight)
        current = resolve_whatsapp_privilege_context(session, igreja_id=igreja_id,
            conversation_id=outcome.conversation_id, inbound_message_id=outcome.inbound_message_id)
        if error or type(current) is not PrivilegeContext or current.context_fingerprint != context.context_fingerprint:
            catalog, mapping = (), {}
        else:
            current_v3_projection = consolidation_routing_projection(session, current)
            if v3_recognized and (
                current_v3_projection is None or current_v3_projection.handoff_only
            ):
                catalog, mapping = (), {}
            elif current_v3_projection is None:
                catalog, mapping = build_catalog(session, current)
            else:
                v3_projection = current_v3_projection
                catalog, mapping = build_consolidation_catalog(session, current)
                if not set(v3_projection.required_codes) <= {option.code for option in catalog}:
                    catalog, mapping = (), {}
                routing_text = v3_projection.text
    if not catalog:
        return handoff('privilege_catalog')
    if ownership_guard is not None:
        ownership_guard()
    try:
        client = LLMClient(preflight.credential_provedor,
            decrypt_secret(preflight.credential_key_encrypted), preflight.credential_model)
        from app.services.semantic_routing import S3_ROUTING_APPROVED_RELEASE_ID
        if effective is not None and S3_ROUTING_APPROVED_RELEASE_ID is not None:
            from app.services.agent_privilege_routing import JevChoiceAdapter
            client = JevChoiceAdapter(effective, igreja_id,
                tier_a_release_id=TIER_A_APPROVED_RELEASE_ID, s3_release_id=S3_ROUTING_APPROVED_RELEASE_ID)
        routed = route_privileged_message(client, texto=routing_text,
            catalog=catalog, deadline_monotonic=started + 10)
    except Exception:
        return handoff('privilege_router_error')
    routing_usage = routed.usage
    if ownership_guard is not None:
        ownership_guard()
    if routed.status == 'handoff' or time.monotonic() >= started + 9:
        return handoff('privilege_router_handoff')
    general_response = None
    if v3_projection is not None and routed.status == 'clarify':
        return handoff('privilege_router_handoff')
    if routed.status == 'clarify' and routed.route is None:
        generated = _general_answer(runtime_session_factory, outcome, preflight, context, started + 9)
        if generated is not None:
            routing_usage += (generated.usage,)
        if generated is None or generated.handoff or not generated.resposta:
            return handoff('privilege_general_handoff')
        general_response = generated.resposta
    with _session(runtime_session_factory, outcome) as session:
        from sqlalchemy import select
        from app.db.models import Conversation

        # Keep the durable secretary-offer transition under the existing
        # Conversation -> outbound Message order.
        conversation = session.execute(
            select(Conversation).where(
                Conversation.id == outcome.conversation_id,
                Conversation.igreja_id == igreja_id,
            ).with_for_update()
        ).scalar_one_or_none()
        _, _, error = _load_tier_a_plan_state(session, preflight)
        current = resolve_whatsapp_privilege_context(session, igreja_id=igreja_id,
            conversation_id=outcome.conversation_id, inbound_message_id=outcome.inbound_message_id)
        message = _lock_reply(session, outcome, provider_id)
        if (
            conversation is None
            or message is None
            or message.agent_reply_state != AGENT_REPLY_RESERVED
        ):
            return qw.AgentRunDisposition.COMPLETED
        invalid = error or type(current) is not PrivilegeContext or current.context_fingerprint != context.context_fingerprint
        if not invalid:
            selected = mapping.get((routed.tool, routed.handle))
            if routed.status == 'selected' and selected is None:
                invalid = True
            elif selected is None:
                _store_response(message, current,
                    general_response or 'Não identifiquei uma ação ou alvo autorizado. Diga qual registro deseja consultar ou confirmar.',
                    kind='clarify')
            else:
                invalid = not _apply_selection(
                    session,
                    current,
                    selected,
                    message,
                    current_text=preflight.current_text,
                    conversation=conversation,
                )
            if not invalid:
                from app.agent.masking import log_agent_event, log_ai_usage
                for usage in routing_usage:
                    log_ai_usage(session, igreja_id=igreja_id, usage=usage, ferramenta='s3_routing')
                log_agent_event(session, igreja_id=igreja_id, conversation_id=outcome.conversation_id,
                    evento='agent_privilege_routing', payload={'estado': routed.status})
                session.commit()
    if invalid:
        return handoff('privilege_changed')
    intent = qw._load_agent_reply_intent(session_factory, outcome)
    if intent is not None:
        qw._deliver_agent_reply_intent(session_factory, outcome, intent,
            ownership_guard, evolution_client=evolution_client)
    return qw.AgentRunDisposition.COMPLETED


def _apply_selection(session, context, selected, message, *, current_text, conversation) -> bool:
    from app.services.agent_action_proposals import (
        AgentAction, ProposalTarget, prepare_action_proposal,
    )
    from app.services.agent_privilege_catalog import (
        PROPOSAL_ACTIONS,
        build_catalog,
        read_sensitive_catalog,
    )
    if selected.code == 'consultar_agenda':
        from app.services.whatsapp_agenda import (
            agenda_enabled_from_environment,
            agenda_reply_metadata,
            agenda_draft_role_allowed,
            agenda_drafts_allowed,
            parse_agenda_query,
            resolve_agenda_reply,
        )
        # Rebuild the generic catalog after B/C/D. It contains no Event rows,
        # but it closes a role or feature change while the model was running.
        _, current_targets = build_catalog(session, context)
        if (
            not agenda_enabled_from_environment(context.igreja_id)
            or not any(target == selected for target in current_targets.values())
        ):
            return False
        query = parse_agenda_query(current_text)
        if query is None:
            return False
        reply_context = context
        if query.include_drafts:
            # A member, operator or leader never receives a challenge for a
            # capability their role cannot use. Only pastor/admin reach the
            # separate Clerk proof flow.
            if not agenda_draft_role_allowed(context):
                return False
            from app.services.whatsapp_privilege import PrivilegeContext, resolve_whatsapp_privilege_context
            sensitive = resolve_whatsapp_privilege_context(
                session,
                igreja_id=context.igreja_id,
                conversation_id=context.conversation_id,
                inbound_message_id=context.inbound_message_id,
                sensitive=True,
            )
            if type(sensitive) is not PrivilegeContext:
                from app.services.agent_identity import issue_identity_challenge
                challenge = issue_identity_challenge(
                    session,
                    igreja_id=context.igreja_id,
                    conversation_id=context.conversation_id,
                    inbound_message_id=context.inbound_message_id,
                )
                _store_response(
                    message,
                    context,
                    ('Para consultar rascunhos, abra seu Perfil no painel e confirme o acesso ao WhatsApp '
                     f'com o código {challenge.challenge}. Ele vale por 5 minutos. Depois repita seu pedido aqui.'),
                    kind='challenge',
                )
                return True
            if not agenda_drafts_allowed(sensitive):
                return False
            reply_context = sensitive
        reply = resolve_agenda_reply(session, context=reply_context, text=current_text)
        if reply is None:
            return False
        _store_response(
            message,
            reply_context,
            reply.response,
            kind='agenda',
            agenda=agenda_reply_metadata(reply),
        )
        if reply.offers_secretary:
            from app.services.secretaria_offer import prepare_secretaria_offer
            prepare_secretaria_offer(
                conversation,
                outbound_message_id=message.id,
                replace_terminal=True,
            )
            if (
                getattr(conversation, 'secretaria_oferta_message_id', None) != message.id
                or getattr(conversation, 'secretaria_oferta_estado', None)
                not in {'preparada', 'aceite_aguardando_ancora', 'pendente'}
            ):
                return False
        return True
    if selected.code == 'consultar_pendencias_consolidacao':
        _, current_targets = build_catalog(session, context)
        if not any(target == selected for target in current_targets.values()):
            return False
        from app.services.consolidation_privileged import consolidation_pending_reply

        reply = consolidation_pending_reply(session, context=context)
        if reply is None:
            return False
        _store_response(
            message,
            context,
            reply.response,
            kind='consolidation',
            consolidation={'projection_sha256': reply.projection_sha256},
        )
        return True
    if selected.code in PROPOSAL_ACTIONS:
        # A role snapshot alone cannot authorize a target whose membership or
        # cell leadership changed while the LLM was running.
        _, current_targets = build_catalog(session, context)
        if not any(target == selected for target in current_targets.values()):
            return False
        summary = _action_summary(selected.summary)
        message.texto = summary
        try:
            if selected.code == 'configurar_lembrete_agenda':
                target = ProposalTarget(
                    kind='evento',
                    id=uuid.UUID(selected.arguments['event_id']),
                )
            elif selected.code == 'marcar_fonovisita_feita':
                target = ProposalTarget(
                    kind='pendencia_consolidacao',
                    id=uuid.UUID(selected.arguments['work_queue_item_id']),
                )
            elif selected.code == 'atribuir_consolidacao':
                target = ProposalTarget(
                    kind='consolidacao',
                    id=uuid.UUID(selected.arguments['consolidacao_id']),
                )
            else:
                target = ProposalTarget(
                    kind='pessoa',
                    id=uuid.UUID(selected.arguments['pessoa_id']),
                )
        except (KeyError, TypeError, ValueError):
            return False
        proposal = prepare_action_proposal(session, context=context,
            inbound_message_id=context.inbound_message_id, action=AgentAction(selected.code),
            target=target,
            arguments=dict(selected.arguments), summary=summary, summary_message_id=message.id)
        _store_response(message, context, summary, kind='summary', proposal_id=proposal.proposal_id)
        return True
    from app.services.whatsapp_privilege import PrivilegeContext, resolve_whatsapp_privilege_context
    sensitive = resolve_whatsapp_privilege_context(session, igreja_id=context.igreja_id,
        conversation_id=context.conversation_id, inbound_message_id=context.inbound_message_id, sensitive=True)
    if type(sensitive) is not PrivilegeContext:
        from app.services.agent_identity import issue_identity_challenge
        challenge = issue_identity_challenge(session, igreja_id=context.igreja_id,
            conversation_id=context.conversation_id, inbound_message_id=context.inbound_message_id)
        response = ('Para consultar esse dado, abra seu Perfil no painel e confirme o acesso ao WhatsApp '
                    f'com o código {challenge.challenge}. Ele vale por 5 minutos. Depois repita seu pedido aqui.')
        _store_response(message, context, response, kind='challenge')
        return True
    response = read_sensitive_catalog(session, sensitive, selected.code)
    _store_response(message, sensitive, response, kind='readonly')
    return True


def _general_answer(factory, outcome, preflight, context, deadline):
    """Preserve ordinary typed replies without executing a legacy tool route."""
    from app.agent.runtime import (
        _load_tier_a_plan_state, _load_recent_conversation_history,
        _build_tier_a_plan, reply_tier_a_plan_with_llm,
    )
    from app.agent.nodes import empty_turn_effects
    from app.services.whatsapp_privilege import PrivilegeContext, resolve_whatsapp_privilege_context
    from app.services.llm import TypedLLMResult
    with _session(factory, outcome) as session:
        _, _, error = _load_tier_a_plan_state(session, preflight)
        current = resolve_whatsapp_privilege_context(session, igreja_id=preflight.igreja_id,
            conversation_id=preflight.conversation_id, inbound_message_id=preflight.inbound_message_id)
        if error or type(current) is not PrivilegeContext or current.context_fingerprint != context.context_fingerprint:
            return None
        history = _load_recent_conversation_history(session, igreja_id=preflight.igreja_id,
            conversation_id=preflight.conversation_id, current_message_id=preflight.inbound_message_id,
            provider_message_id=preflight.provider_message_id)
        plan = _build_tier_a_plan(preflight, effects=empty_turn_effects(),
            draft_response='Como posso ajudar?', history=history)
    remaining = deadline - time.monotonic()
    if plan is None or remaining <= 0:
        return None
    result = reply_tier_a_plan_with_llm(plan, timeout_seconds=min(4.0, remaining))
    if time.monotonic() >= deadline or type(result) is not TypedLLMResult:
        return None
    return result
