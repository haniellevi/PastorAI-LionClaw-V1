from contextlib import contextmanager
from types import MappingProxyType, SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest


@pytest.mark.parametrize(
    ('text', 'target_code', 'target_person', 'expect_route'),
    (
        ('Quero confirmar minha presença na próxima reunião da minha célula.',
         'marcar_presenca', UUID(int=104), True),
        ('Quero confirmar minha presença na próxima reunião da minha célula.',
         None, None, False),
        ('Quero confirmar minha presença na próxima reunião da minha célula.',
         'marcar_presenca', UUID(int=999), False),
        ('Quero confirmar minha presença na próxima reunião da minha célula.',
         'registrar_decisao', UUID(int=104), False),
        ('Qual a próxima reunião da minha célula?',
         'consultar_vinculo', None, False),
    ),
)
def test_public_lookup_yields_only_to_current_own_attendance_target(
    monkeypatch, text, target_code, target_person, expect_route,
):
    from app.agent import privileged_turn, runtime
    from app.agent.read_only_info import canonical_public_info_request
    from app.domain.agent_reply import AGENT_REPLY_RESERVED
    from app.services import (
        agent_privilege_catalog, agent_privilege_routing, cell_report_whatsapp,
        crypto, llm, semantic_triage, whatsapp_privilege,
    )
    from app.services.agent_privilege_catalog import CatalogTarget
    from app.services.agent_privilege_routing import CandidateOption, RoutingDecision, ToolOption
    from app.services.semantic_routing import RouteChoice
    from app.services.whatsapp_privilege import PrivilegeContext
    from app.workers import queue_worker

    # Keep the public classifier real: both phrases trigger its cell lookup.
    assert canonical_public_info_request(text) is not None
    context = PrivilegeContext(
        igreja_id=UUID(int=101), conversation_id=UUID(int=102),
        inbound_message_id=UUID(int=103), pessoa_id=UUID(int=104),
        app_user_id=UUID(int=105), roles=frozenset(), role_snapshot=(),
        owned_cell_ids=(), credential_fingerprint='1' * 64,
        phone_fingerprint='2' * 64, authorization_fingerprint='3' * 64,
        proof_id=None, proof_until=None, sensitive=False,
        scope_fingerprint='4' * 64, context_fingerprint='5' * 64,
    )
    outcome = SimpleNamespace(
        igreja_id=context.igreja_id, conversation_id=context.conversation_id,
        inbound_message_id=context.inbound_message_id, provider_message_id='synthetic',
        texto=text,
    )
    preflight = SimpleNamespace(
        current_text=text, credential_provedor='synthetic',
        credential_key_encrypted='synthetic', credential_model='synthetic',
    )
    arguments = {} if target_person is None else {
        'pessoa_id': str(target_person), 'reuniao_id': str(UUID(int=106)),
    }
    target = CatalogTarget(target_code, MappingProxyType(arguments), 'Resumo sintético')
    catalog = () if target_code is None else (
        ToolOption(target_code, RouteChoice.RESTRITA, 'Sintético',
                   (CandidateOption('h1', 'Resumo sintético'),)),
    )
    mapping = {} if target_code is None else {(target_code, 'h1'): target}
    calls = []

    class Session:
        def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace())

        def commit(self):
            pass

    @contextmanager
    def session_scope(*_args, **_kwargs):
        yield Session()

    def current_catalog(_session, current):
        assert current is context
        calls.append('catalog')
        return catalog, mapping

    def route(_client, *, texto, catalog, deadline_monotonic):
        assert texto == text and catalog and deadline_monotonic > 0
        calls.append('route')
        return RoutingDecision('selected', RouteChoice.RESTRITA, target_code, 'h1', ())

    def apply(_session, current, selected, _message, *, current_text, conversation):
        assert current is context and selected is target and current_text == text
        calls.append('apply')
        return True

    monkeypatch.setattr(privileged_turn, '_session', session_scope)
    monkeypatch.setattr(runtime, 'process_inbound_message',
                        lambda *_a, **_k: SimpleNamespace(reason=None, preflight=preflight))
    monkeypatch.setattr(runtime, '_load_tier_a_plan_state', lambda *_a, **_k: (None, None, None))
    monkeypatch.setattr(whatsapp_privilege, 'resolve_whatsapp_privilege_context', lambda *_a, **_k: context)
    monkeypatch.setattr(agent_privilege_catalog, 'consolidation_routing_projection', lambda *_a, **_k: None)
    monkeypatch.setattr(agent_privilege_catalog, 'build_catalog', current_catalog)
    monkeypatch.setattr(semantic_triage, 'tier_a_enabled_from_environment', lambda _tenant: False)
    monkeypatch.setattr(cell_report_whatsapp, 'cell_report_enabled_from_environment', lambda _tenant: False)
    monkeypatch.setattr(queue_worker, '_agent_reply_idempotency_key', lambda _outcome: 'synthetic-reply')
    monkeypatch.setattr(queue_worker, '_load_agent_reply_intent', lambda *_a, **_k: None)
    monkeypatch.setattr(queue_worker, '_reserve_agent_reply_intent', lambda *_a, **_k: object())
    monkeypatch.setattr(queue_worker, '_persist_tier_a_handoff',
                        Mock(side_effect=AssertionError('unexpected handoff')))
    monkeypatch.setattr(privileged_turn, '_lock_reply',
                        lambda *_a, **_k: SimpleNamespace(agent_reply_state=AGENT_REPLY_RESERVED))
    monkeypatch.setattr(privileged_turn, '_local_audio_consent', lambda *_a, **_k: False)
    monkeypatch.setattr(privileged_turn, '_local_confirmation', lambda *_a, **_k: False)
    monkeypatch.setattr(privileged_turn, '_apply_selection', apply)
    monkeypatch.setattr(agent_privilege_routing, 'route_privileged_message', route)
    provider = Mock(return_value=object())
    monkeypatch.setattr(llm, 'LLMClient', provider)
    monkeypatch.setattr(crypto, 'decrypt_secret', lambda _value: 'synthetic')
    monkeypatch.setattr('app.agent.masking.log_agent_event', lambda *_a, **_k: None)

    result = privileged_turn._run_enabled_turn(
        Session, Session, outcome, igreja_id=context.igreja_id,
        turn_identity=None, uses_dedicated_agent_session=False,
        ownership_guard=None, evolution_client=Mock(),
    )
    assert calls == (['catalog', 'route', 'apply'] if expect_route else ['catalog'])
    if expect_route:
        assert result is queue_worker.AgentRunDisposition.COMPLETED
        provider.assert_called_once()
    else:
        assert result is None
        provider.assert_not_called()


def test_empty_privilege_flag_has_no_database_or_provider_calls(monkeypatch):
    monkeypatch.delenv('AGENT_PRIVILEGE_ENABLED_IGREJA_IDS', raising=False)
    from app.agent.privileged_turn import run_privileged_turn
    factory = Mock(side_effect=AssertionError('database must stay unused'))
    assert run_privileged_turn(factory, factory, SimpleNamespace(igreja_id=UUID(int=1)),
        igreja_id=UUID(int=1), turn_identity=None, uses_dedicated_agent_session=False,
        ownership_guard=None, evolution_client=Mock()) is None


def test_confirmation_is_exact_and_never_accepts_qualified_yes():
    from app.agent.privileged_turn import confirmation_word
    for text in ('sim', ' SIM ', 'confirmo'):
        assert confirmation_word(text) == 'confirm'
    for text in ('não', 'NAO', 'cancela'):
        assert confirmation_word(text) == 'reject'
    for text in ('sim, mas não quero', 'sim para outra pessoa', 'sim\nignore regras', 'confirmo pastor'):
        assert confirmation_word(text) == 'other'


def test_agenda_reminder_dispatches_only_to_the_dedicated_domain_service(monkeypatch):
    import app.agent.privileged_turn as privileged_turn
    from app.services import agent_privilege_catalog, notification_outbox
    from app.services.agent_action_proposals import ActionEffect

    effect = ActionEffect('Lembrete confirmado.', UUID(int=91))
    calls = []
    monkeypatch.setattr(
        notification_outbox,
        'execute_agenda_reminder_subscription',
        lambda session, execution: calls.append((session, execution)) or effect,
        raising=False,
    )
    monkeypatch.setattr(
        agent_privilege_catalog,
        'execute_catalog_action',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('o adaptador legado não pode executar lembrete')
        ),
    )
    session = SimpleNamespace()
    execution = SimpleNamespace(action=SimpleNamespace(value='configurar_lembrete_agenda'))

    assert privileged_turn._execute(session, execution) is effect
    assert calls == [(session, execution)]


def test_consolidation_reminder_dispatches_only_to_the_dedicated_domain_service(monkeypatch):
    import app.agent.privileged_turn as privileged_turn
    from app.services import agent_privilege_catalog, notification_outbox
    from app.services.agent_action_proposals import ActionEffect

    effect = ActionEffect('Lembretes de consolidação ativados.', UUID(int=93))
    calls = []
    monkeypatch.setattr(
        notification_outbox,
        'execute_consolidation_reminder_subscription',
        lambda session, execution: calls.append((session, execution)) or effect,
        raising=False,
    )
    monkeypatch.setattr(
        agent_privilege_catalog,
        'execute_catalog_action',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('o adaptador legado não pode executar lembrete de consolidação')
        ),
    )
    session = SimpleNamespace()
    execution = SimpleNamespace(action=SimpleNamespace(value='configurar_lembrete_consolidacao'))

    assert privileged_turn._execute(session, execution) is effect
    assert calls == [(session, execution)]


def test_agenda_reminder_selection_stages_an_event_target(monkeypatch):
    import app.agent.privileged_turn as privileged_turn
    from app.services import agent_action_proposals, agent_privilege_catalog

    event_id = UUID('00000000-0000-0000-0000-0000000000e5')
    selected = agent_privilege_catalog.CatalogTarget(
        'configurar_lembrete_agenda',
        MappingProxyType({
            'event_id': str(event_id),
            'occurrence_at': '2026-10-02T13:00:00.000000+00:00',
            'term_version': 'lgpd-v2',
        }),
        'Ativar lembretes da Agenda para Culto em 02/10/2026 às 10:00',
    )
    context = SimpleNamespace(
        igreja_id=UUID(int=1), conversation_id=UUID(int=2), inbound_message_id=UUID(int=3),
    )
    captured = {}
    monkeypatch.setattr(
        agent_privilege_catalog,
        'build_catalog',
        lambda *_args, **_kwargs: ((), MappingProxyType({('configurar_lembrete_agenda', 'h1'): selected})),
    )
    monkeypatch.setattr(
        agent_action_proposals,
        'prepare_action_proposal',
        lambda *_args, **kwargs: captured.update(kwargs) or SimpleNamespace(proposal_id=UUID(int=92)),
    )
    monkeypatch.setattr(privileged_turn, '_store_response', lambda *_args, **_kwargs: None)

    assert privileged_turn._apply_selection(
        SimpleNamespace(), context, selected, SimpleNamespace(id=UUID(int=4)),
        current_text='Quero lembrete do culto.', conversation=SimpleNamespace(),
    )
    assert captured['target'].kind == 'evento'
    assert captured['target'].id == event_id
    assert captured['arguments'] == dict(selected.arguments)
    assert captured['summary'] == (
        'Ativar lembretes da Agenda para Culto em 02/10/2026 às 10:00. '
        'Confirma esta ação? Responda SIM ou NÃO. A proposta vale por 10 minutos.'
    )


@pytest.mark.parametrize(
    ('code', 'arguments', 'target_kind', 'target_id'),
    (
        (
            'marcar_fonovisita_feita',
            {
                'work_queue_item_id': str(UUID('00000000-0000-0000-0000-0000000000e5')),
                'consolidacao_id': str(UUID('00000000-0000-0000-0000-0000000000c3')),
                'assignment_revision': 4,
            },
            'pendencia_consolidacao',
            UUID('00000000-0000-0000-0000-0000000000e5'),
        ),
        (
            'atribuir_consolidacao',
            {
                'consolidacao_id': str(UUID('00000000-0000-0000-0000-0000000000c3')),
                'responsavel_id': str(UUID('00000000-0000-0000-0000-0000000000b2')),
                'assignment_revision': 4,
            },
            'consolidacao',
            UUID('00000000-0000-0000-0000-0000000000c3'),
        ),
    ),
)
def test_consolidation_mutation_selection_stages_only_its_closed_target(
    monkeypatch,
    code,
    arguments,
    target_kind,
    target_id,
):
    import app.agent.privileged_turn as privileged_turn
    from app.services import agent_action_proposals, agent_privilege_catalog

    selected = agent_privilege_catalog.CatalogTarget(
        code,
        MappingProxyType(arguments),
        'Resumo opaco da pendência',
    )
    context = SimpleNamespace(
        igreja_id=UUID(int=1), conversation_id=UUID(int=2), inbound_message_id=UUID(int=3),
    )
    captured = {}
    monkeypatch.setattr(
        agent_privilege_catalog,
        'build_catalog',
        lambda *_args, **_kwargs: ((), MappingProxyType({(code, 'h1'): selected})),
    )
    monkeypatch.setattr(
        agent_action_proposals,
        'prepare_action_proposal',
        lambda *_args, **kwargs: captured.update(kwargs) or SimpleNamespace(proposal_id=UUID(int=92)),
    )
    monkeypatch.setattr(privileged_turn, '_store_response', lambda *_args, **_kwargs: None)

    assert privileged_turn._apply_selection(
        SimpleNamespace(),
        context,
        selected,
        SimpleNamespace(id=UUID(int=4)),
        current_text='Confirmar pendência.',
        conversation=SimpleNamespace(),
    )
    assert captured['target'].kind == target_kind
    assert captured['target'].id == target_id
    assert captured['arguments'] == arguments


@pytest.mark.parametrize(
    ('action', 'arguments', 'receipt_text', 'result_field'),
    (
        (
            'marcar_fonovisita_feita',
            {
                'work_queue_item_id': str(UUID('00000000-0000-0000-0000-0000000000e5')),
                'consolidacao_id': str(UUID('00000000-0000-0000-0000-0000000000c3')),
                'assignment_revision': 4,
            },
            'Fonovisita confirmada.',
            'work_queue_item',
        ),
        (
            'atribuir_consolidacao',
            {
                'consolidacao_id': str(UUID('00000000-0000-0000-0000-0000000000c3')),
                'responsavel_id': str(UUID('00000000-0000-0000-0000-0000000000b2')),
                'assignment_revision': 4,
            },
            'Consolidação atribuída.',
            'consolidacao',
        ),
    ),
)
def test_consolidation_mutation_execution_reuses_the_shared_human_service(
    monkeypatch,
    action,
    arguments,
    receipt_text,
    result_field,
):
    import app.agent.privileged_turn as privileged_turn
    from app.services import agent_privilege_catalog, consolidation_workflow

    effect_id = UUID('00000000-0000-0000-0000-0000000000e5')
    calls = []
    result = SimpleNamespace(**{result_field: SimpleNamespace(id=effect_id)})
    if action == 'marcar_fonovisita_feita':
        monkeypatch.setattr(
            consolidation_workflow,
            'complete_fonovisita',
            lambda *args, **kwargs: calls.append((args, kwargs)) or result,
        )
    else:
        monkeypatch.setattr(
            consolidation_workflow,
            'assign_consolidacao',
            lambda *args, **kwargs: calls.append((args, kwargs)) or result,
        )
    monkeypatch.setattr(
        agent_privilege_catalog,
        'execute_catalog_action',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('ação V3 não pode usar o adaptador legado')
        ),
    )
    context = SimpleNamespace(
        igreja_id=UUID(int=1),
        app_user_id=UUID(int=2),
        roles=frozenset({'pastor'}),
    )
    execution = SimpleNamespace(
        action=SimpleNamespace(value=action),
        arguments=arguments,
        privilege_context=context,
    )

    effect = privileged_turn._execute(SimpleNamespace(), execution)

    assert effect.receipt_text == receipt_text
    assert effect.opaque_effect_id == effect_id
    assert len(calls) == 1
    assert calls[0][1]['whatsapp'] is True
    assert calls[0][1]['expected_assignment_revision'] == 4


def test_consolidation_pending_selection_uses_the_revalidated_projection(monkeypatch):
    import app.agent.privileged_turn as privileged_turn
    from app.services import agent_privilege_catalog, consolidation_privileged

    selected = agent_privilege_catalog.CatalogTarget(
        'consultar_pendencias_consolidacao',
        MappingProxyType({}),
        'Consultar pendências de consolidação autorizadas',
    )
    context = SimpleNamespace(
        igreja_id=UUID(int=1), conversation_id=UUID(int=2), inbound_message_id=UUID(int=3),
    )
    reply = consolidation_privileged.PendingConsolidationReply(
        'Há 1 pendência de consolidação no seu escopo.', 'a' * 64,
    )
    captured = {}
    monkeypatch.setattr(
        agent_privilege_catalog,
        'build_catalog',
        lambda *_args, **_kwargs: (
            (),
            MappingProxyType({('consultar_pendencias_consolidacao', None): selected}),
        ),
    )
    monkeypatch.setattr(
        consolidation_privileged,
        'consolidation_pending_reply',
        lambda _session, *, context: reply,
    )
    monkeypatch.setattr(
        privileged_turn,
        '_store_response',
        lambda _message, _context, response, **kwargs: captured.update(
            response=response, **kwargs
        ),
    )

    assert privileged_turn._apply_selection(
        SimpleNamespace(), context, selected, SimpleNamespace(id=UUID(int=4)),
        current_text='Quais pendências de consolidação existem?', conversation=SimpleNamespace(),
    )
    assert captured == {
        'response': reply.response,
        'kind': 'consolidation',
        'consolidation': {'projection_sha256': 'a' * 64},
    }


@pytest.mark.parametrize(
    ('inbound_text', 'selected_code', 'selected_handle', 'expect_handoff'),
    (
        (
            'Quais pendências de consolidação existem?',
            'consultar_pendencias_consolidacao',
            None,
            False,
        ),
        (
            'Atribuir P-1234567890 para Mária Łucía.',
            'atribuir_consolidacao',
            'h1',
            False,
        ),
        (
            'Atribuir P-1234567890 para Mária Łucía.',
            'consultar_pendencias_consolidacao',
            None,
            True,
        ),
        (
            'Quais pendências de consolidação? hoje planejo desaparecer para sempre.',
            'consultar_pendencias_consolidacao',
            None,
            True,
        ),
    ),
)
def test_v3_turn_routes_only_an_opaque_projection_without_inbound_person_names(
    monkeypatch,
    inbound_text,
    selected_code,
    selected_handle,
    expect_handoff,
):
    """Tier A, V1a and S3 never receive a V3 inbound name or free text."""

    import unicodedata

    from app.agent import runtime
    from app.agent import privileged_turn
    from app.domain.agent_reply import AGENT_REPLY_RESERVED
    from app.services import (
        agent_privilege_catalog,
        agent_privilege_routing,
        cell_report_v1a_service,
        cell_report_whatsapp,
        crypto,
        llm,
        semantic_triage,
        whatsapp_privilege,
    )
    from app.services.agent_privilege_routing import (
        CandidateOption,
        RoutingDecision,
        ToolOption,
    )
    from app.services.agent_privilege_catalog import CatalogTarget
    from app.services.semantic_routing import RouteChoice
    from app.services.whatsapp_privilege import PrivilegeContext
    from app.workers import queue_worker

    tenant = UUID(int=101)
    conversation_id = UUID(int=102)
    inbound_id = UUID(int=103)
    pessoa_id = UUID(int=104)
    actor_id = UUID(int=105)
    context = PrivilegeContext(
        igreja_id=tenant,
        conversation_id=conversation_id,
        inbound_message_id=inbound_id,
        pessoa_id=pessoa_id,
        app_user_id=actor_id,
        roles=frozenset({'pastor'}),
        role_snapshot=(),
        owned_cell_ids=(),
        credential_fingerprint='1' * 64,
        phone_fingerprint='2' * 64,
        authorization_fingerprint='3' * 64,
        proof_id=None,
        proof_until=None,
        sensitive=False,
        scope_fingerprint='4' * 64,
        context_fingerprint='5' * 64,
    )
    preflight = runtime.TierATurnPreflight(
        igreja_id=tenant,
        conversation_id=conversation_id,
        pessoa_id=pessoa_id,
        inbound_message_id=inbound_id,
        provider_message_id='inbound-synthetic',
        current_text=inbound_text,
        tier_a_input_within_limit=True,
        config_id=UUID(int=106),
        config_comportamento='Sintético.',
        credential_id=UUID(int=107),
        credential_provedor='synthetic',
        credential_model='synthetic',
        credential_key_encrypted='synthetic',
        accepted_consent_version='lgpd-v2',
        term_version='lgpd-v2',
    )
    outcome = SimpleNamespace(
        igreja_id=tenant,
        conversation_id=conversation_id,
        inbound_message_id=inbound_id,
        provider_message_id='inbound-synthetic',
        texto=inbound_text,
    )
    selected = CatalogTarget(
        selected_code,
        MappingProxyType({}),
        'Resumo opaco de consolidação',
    )
    candidates = (
        ()
        if selected_handle is None
        else (CandidateOption('h1', 'Resumo opaco de consolidação'),)
    )
    catalog = (
        ToolOption(
            selected_code,
            RouteChoice.RESTRITA,
            'Ação de consolidação autorizada',
            candidates,
        ),
    )
    mapping = MappingProxyType({(selected_code, selected_handle): selected})
    message = SimpleNamespace(agent_reply_state=AGENT_REPLY_RESERVED)

    class _Result:
        def scalar_one_or_none(self):
            return inbound_text

    class _Session:
        def execute(self, _statement):
            return _Result()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    @contextmanager
    def fake_session(*_args, **_kwargs):
        yield _Session()

    captured = {}
    handoff_result = object()
    monkeypatch.setattr(privileged_turn, '_session', fake_session)
    monkeypatch.setattr(
        runtime,
        'process_inbound_message',
        lambda *_args, **_kwargs: SimpleNamespace(reason=None, preflight=preflight),
    )
    monkeypatch.setattr(runtime, '_load_tier_a_plan_state', lambda *_args, **_kwargs: (None, None, None))
    monkeypatch.setattr(
        whatsapp_privilege,
        'resolve_whatsapp_privilege_context',
        lambda *_args, **_kwargs: context,
    )
    monkeypatch.setattr(
        agent_privilege_catalog,
        'consolidation_enabled_from_environment',
        lambda _tenant: True,
    )
    monkeypatch.setattr(
        agent_privilege_catalog,
        '_eligible_consolidation_users',
        lambda *_args, **_kwargs: {actor_id: 'Mária Łucía'},
    )
    monkeypatch.setattr(
        agent_privilege_catalog,
        'build_consolidation_catalog',
        lambda *_args, **_kwargs: (catalog, mapping),
    )
    monkeypatch.setattr(
        agent_privilege_catalog,
        'build_catalog',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('pedido V3 não abre catálogo geral com nomes')
        ),
    )
    monkeypatch.setattr(queue_worker, '_agent_reply_idempotency_key', lambda _outcome: 'reply-synthetic')
    monkeypatch.setattr(queue_worker, '_load_agent_reply_intent', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(queue_worker, '_reserve_agent_reply_intent', lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        queue_worker,
        '_run_tier_a_batch',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('Tier A não pode receber texto V3')
        ),
    )
    monkeypatch.setattr(semantic_triage, 'tier_a_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(cell_report_whatsapp, 'cell_report_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(
        cell_report_v1a_service,
        'stage_v1a_cell_report_turn',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('V1a não pode receber texto V3')
        ),
    )
    monkeypatch.setattr(
        'app.agent.read_only_info.canonical_public_info_request',
        lambda _text: (_ for _ in ()).throw(
            AssertionError('consulta pública não processa texto V3')
        ),
    )
    monkeypatch.setattr(privileged_turn, '_lock_reply', lambda *_args, **_kwargs: message)
    monkeypatch.setattr(privileged_turn, '_local_audio_consent', lambda *_args, **_kwargs: False)
    monkeypatch.setattr(privileged_turn, '_local_confirmation', lambda *_args, **_kwargs: False)
    monkeypatch.setattr(privileged_turn, '_apply_selection', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(llm, 'LLMClient', lambda *_args, **_kwargs: object())
    monkeypatch.setattr(crypto, 'decrypt_secret', lambda _value: 'synthetic')
    monkeypatch.setattr(
        agent_privilege_routing,
        'route_privileged_message',
        lambda _client, *, texto, catalog, deadline_monotonic: captured.update(
            texto=texto,
            catalog=catalog,
            deadline_monotonic=deadline_monotonic,
        ) or RoutingDecision(
            'selected',
            RouteChoice.RESTRITA,
            selected_code,
            selected_handle,
            (),
        ),
    )
    monkeypatch.setattr('app.agent.masking.log_agent_event', lambda *_args, **_kwargs: None)
    monkeypatch.setattr('app.agent.masking.log_ai_usage', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        queue_worker,
        '_persist_tier_a_handoff',
        (
            lambda *_args, **_kwargs: handoff_result
            if expect_handoff
            else (_ for _ in ()).throw(AssertionError('não deve handoff'))
        ),
    )

    result = privileged_turn._run_enabled_turn(
        lambda: _Session(),
        lambda: _Session(),
        outcome,
        igreja_id=tenant,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=Mock(),
    )
    if expect_handoff:
        assert result is handoff_result
        assert not captured
        return
    assert result is queue_worker.AgentRunDisposition.COMPLETED

    rendered = unicodedata.normalize(
        'NFKD',
        repr((captured['texto'], captured['catalog'])).casefold(),
    )
    assert 'maria' not in rendered
    assert 'lucia' not in rendered
    assert inbound_text.casefold() not in captured['texto'].casefold()
    assert {option.code for option in captured['catalog']} == {selected_code}


def test_agenda_reply_metadata_keeps_only_bounded_snapshot_controls():
    from app.agent.privileged_turn import reply_metadata

    context = SimpleNamespace(
        inbound_message_id=UUID(int=4),
        context_fingerprint='context',
        sensitive=False,
        proof_id=None,
    )
    metadata = reply_metadata(
        context,
        kind='agenda',
        agenda={
            'days': 7,
            'page': 1,
            'include_drafts': False,
            'snapshot_sha256': 'a' * 64,
        },
    )
    assert metadata['kind'] == 'agenda'
    assert metadata['agenda'] == {
        'days': 7,
        'page': 1,
        'include_drafts': False,
        'snapshot_sha256': 'a' * 64,
    }
    assert set(metadata) == {'inbound_message_id', 'context_fingerprint', 'sensitive', 'kind', 'agenda'}


def test_consolidation_reply_metadata_keeps_only_a_technical_projection_fence():
    from app.agent.privileged_turn import reply_metadata

    context = SimpleNamespace(
        inbound_message_id=UUID(int=4),
        context_fingerprint='context',
        sensitive=False,
        proof_id=None,
    )
    metadata = reply_metadata(
        context,
        kind='consolidation',
        consolidation={'projection_sha256': 'a' * 64},
    )

    assert metadata == {
        'inbound_message_id': str(UUID(int=4)),
        'context_fingerprint': 'context',
        'sensitive': False,
        'kind': 'consolidation',
        'consolidation': {'projection_sha256': 'a' * 64},
    }


def test_store_consolidation_reply_persists_the_projection_fence():
    from app.agent.privileged_turn import _store_response
    from app.domain.agent_reply import AGENT_REPLY_PENDING

    context = SimpleNamespace(
        inbound_message_id=UUID(int=4),
        context_fingerprint='context',
        sensitive=False,
        proof_id=None,
    )
    message = SimpleNamespace()

    _store_response(
        message,
        context,
        'Há 1 pendência de consolidação no seu escopo.',
        kind='consolidation',
        consolidation={'projection_sha256': 'a' * 64},
    )

    assert message.agent_reply_state == AGENT_REPLY_PENDING
    assert message.agent_privilege_context['consolidation'] == {
        'projection_sha256': 'a' * 64
    }


def test_non_pastoral_draft_request_does_not_issue_clerk_challenge(monkeypatch):
    import app.agent.privileged_turn as privileged_turn
    from app.services import agent_identity, agent_privilege_catalog, whatsapp_agenda

    tenant = UUID(int=1)
    selected = agent_privilege_catalog.CatalogTarget(
        'consultar_agenda',
        MappingProxyType({}),
        'Consultar agenda autorizada da igreja',
    )
    context = SimpleNamespace(
        igreja_id=tenant,
        conversation_id=UUID(int=2),
        inbound_message_id=UUID(int=3),
        roles=frozenset({'membro'}),
        sensitive=False,
        proof_id=None,
    )
    monkeypatch.setattr(whatsapp_agenda, 'agenda_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(
        agent_privilege_catalog,
        'build_catalog',
        lambda *_args, **_kwargs: ((), MappingProxyType({('consultar_agenda', 'h1'): selected})),
    )
    monkeypatch.setattr(
        agent_identity,
        'issue_identity_challenge',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('challenge must stay unavailable')),
    )

    assert not privileged_turn._apply_selection(
        SimpleNamespace(),
        context,
        selected,
        SimpleNamespace(id=UUID(int=4)),
        current_text='agenda rascunhos',
        conversation=SimpleNamespace(),
    )


def test_listed_tenant_without_approved_release_has_no_database_or_provider_calls(monkeypatch):
    from app.services import whatsapp_privilege
    from app.agent.privileged_turn import run_privileged_turn
    tenant = UUID(int=1)
    monkeypatch.setenv('AGENT_PRIVILEGE_ENABLED_IGREJA_IDS', str(tenant))
    assert whatsapp_privilege.PRIVILEGE_APPROVED_RELEASE_ID is None
    factory = Mock(side_effect=AssertionError('database must stay unused'))
    assert run_privileged_turn(factory, factory, SimpleNamespace(igreja_id=tenant),
        igreja_id=tenant, turn_identity=None, uses_dedicated_agent_session=False,
        ownership_guard=None, evolution_client=Mock()) is None


def test_consented_audio_inbound_stops_before_textual_turn_routing(monkeypatch):
    """A durable audio job has no text turn for Tier A, S3, or the LLM."""

    import app.agent.privileged_turn as privileged_turn
    from app.services import cell_report_audio
    from app.services import cell_report_audio_service
    from app.services import whatsapp_privilege
    from app.services.whatsapp_privilege import PrivilegeContext
    from app.workers import queue_worker

    tenant = UUID(int=1)
    conversation_id = UUID(int=2)
    pessoa_id = UUID(int=3)
    inbound_id = UUID(int=4)
    context = PrivilegeContext(
        igreja_id=tenant,
        conversation_id=conversation_id,
        inbound_message_id=inbound_id,
        pessoa_id=pessoa_id,
        app_user_id=UUID(int=5),
        roles=frozenset({"lider_celula"}),
        role_snapshot=(),
        owned_cell_ids=(UUID(int=6),),
        credential_fingerprint="credential",
        phone_fingerprint="phone",
        authorization_fingerprint="authorization",
        proof_id=None,
        proof_until=None,
        sensitive=False,
        scope_fingerprint="scope",
        context_fingerprint="context",
    )
    values = iter(
        (
            SimpleNamespace(pessoa_id=pessoa_id),
            "audio",
        )
    )

    class _Session:
        def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: next(values))

    @contextmanager
    def fake_session(*_args, **_kwargs):
        yield _Session()

    monkeypatch.setattr(privileged_turn, "_session", fake_session)
    monkeypatch.setattr(
        cell_report_audio,
        "cell_report_audio_enabled_from_environment",
        lambda _tenant: True,
    )
    monkeypatch.setattr(cell_report_audio_service, "audio_schema_available", lambda _session: True)
    monkeypatch.setattr(
        cell_report_audio_service,
        "audio_notice_required_for_inbound",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        whatsapp_privilege,
        "resolve_whatsapp_privilege_context",
        lambda *_args, **_kwargs: context,
    )
    monkeypatch.setattr(queue_worker, "_agent_reply_idempotency_key", lambda _outcome: "audio")
    monkeypatch.setattr(
        privileged_turn,
        "_run_enabled_turn",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("áudio pendente não entra no roteador textual")
        ),
    )

    outcome = SimpleNamespace(
        igreja_id=tenant,
        conversation_id=conversation_id,
        inbound_message_id=inbound_id,
        provider_message_id=f"audio-{uuid4()}",
        texto=None,
    )
    assert privileged_turn.run_privileged_turn(
        lambda: _Session(),
        lambda: _Session(),
        outcome,
        igreja_id=tenant,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=Mock(),
    ) is queue_worker.AgentRunDisposition.COMPLETED
