"""Offline RED for a nominal visitor expectation, never an attendance.

Reuse the presence fixture's direct-SELECT predicate double and synthetic
server context. Catalog, dispatcher, proposal/confirmation and human writer
stay real. No absent enum or future service is accessed during fixture setup.
The preflight snapshot builder is real; process_inbound_message, identity,
scope and worker delivery are explicit doubles. Thus this is not a proof of
preflight authorization/egress, HTTP ingestion, SQL rollback, locks, constraints,
RLS, concurrency, provider delivery or the panel's HTTP/201 contract.
Only ROOT's pinned isolated offline launcher may execute this file.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import datetime as dt
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi import HTTPException

from tests import test_member_presence_whatsapp as presence
from tests.test_member_presence_whatsapp import world
from app.agent import privileged_turn as turn
from app.db.models import (
    AgentActionProposal, AgentActionReceipt, AppUser, Celula, CelulaMembro,
    CelulaExpectativaVisitante, CelulaPresenca, CelulaReuniao, Message, Pessoa,
)
from app.domain import cell_meetings_schedule as schedule
from app.domain.agent_reply import AGENT_REPLY_CONFIRMED, AGENT_REPLY_RESERVED
from app.services import agent_action_proposals as proposals
from app.services import agent_privilege_catalog as catalog
from app.services import ministerial_actions as human
from app.services.whatsapp_privilege import PublicWhatsappContext


TENANT, ACTOR, PERSON, CELL, MEETING = (
    presence.TENANT, presence.ACTOR, presence.PERSON, presence.CELL, presence.MEETING,
)
NOW, OTHER = presence.NOW, presence.OTHER
ACTION = 'registrar_expectativa_visitante'
NAME = 'VISITANTE-FICTÍCIO-Áurea'


def _command(name=NAME):
    return f'indicar {name} como visitante na próxima reunião da minha célula'


def _action():
    # Called only inside tests, so the baseline fails for absent behavior,
    # rather than failing collection/setup on an enum not implemented yet.
    try:
        return proposals.parse_agent_action(ACTION)
    except proposals.ProposalContractError:
        pytest.fail('closed visitor action is not implemented')


def _service():
    writer = getattr(human, 'register_own_visitor_expectation', None)
    assert callable(writer), 'shared own visitor writer is not implemented'
    return writer


@pytest.fixture
def visitor_world(world, monkeypatch):
    world.context = replace(world.context, roles=frozenset(), role_snapshot=())
    world.current = replace(world.current, roles=frozenset(), role_snapshot=())
    world.actor.status = 'ativo'
    world.request.texto = _command()
    world.summary.provider_message_id = 'VISITOR-SUMMARY'
    world.reply.provider_message_id = 'VISITOR-REPLY'
    world.db.tables[CelulaExpectativaVisitante] = []
    world.db.committed_expectations = ()
    world.logs, world.deliveries, world.preflights = [], [], []
    original_add, original_commit = world.db.add, world.db.commit

    def add(row):
        model = type(row)
        assert model in (CelulaExpectativaVisitante, AgentActionProposal, AgentActionReceipt), (
            'visitor indication must not write Person, attendance, prayer, contact or outbox'
        )
        if model is not CelulaExpectativaVisitante:
            return original_add(row)
        if row.id is None:
            row.id = UUID(int=world.db.next_id)
            world.db.next_id += 1
        world.db.tables[model].append(row)
        world.db.events.append(('add', model.__name__))

    def commit():
        original_commit()  # Failure happens before the synthetic snapshot.
        world.db.committed_expectations = tuple(
            (row.id, row.igreja_id, row.reuniao_id, row.pessoa_id,
             row.nome_visitante, row.observacao_oracao)
            for row in world.db.tables[CelulaExpectativaVisitante]
        )

    monkeypatch.setattr(world.db, 'add', add)
    monkeypatch.setattr(world.db, 'commit', commit)
    return world


def _targets(world):
    options, mapping = catalog.build_catalog(world.db, world.context)
    return options, mapping, [item for item in mapping.values() if item.code == ACTION]


def _no_effect(world):
    assert world.db.tables[CelulaExpectativaVisitante] == []
    assert world.db.tables[AgentActionReceipt] == []
    assert world.db.tables[CelulaPresenca] == []


def _private_surfaces(world, name=NAME):
    # The inbound and protected proposal arguments/domain row may keep the
    # name. Outbound messages, metadata and logs may never repeat it.
    outbound = [(row.texto, row.agent_privilege_context)
                for row in world.db.tables[Message] if row.direcao == 'out']
    rendered = repr((outbound, world.logs, world.deliveries))
    assert name not in rendered and repr(name)[1:-1] not in rendered


def _turn(world, monkeypatch, *, request=False, outcome_text=None):
    """Drive the existing public dispatcher with declared local seams only."""
    from app.agent import runtime
    from app.services import (
        agent_privilege_routing, cell_report_whatsapp, llm, semantic_triage,
        whatsapp_privilege,
    )
    from app.workers import queue_worker as qw

    inbound, outbound = (world.request, world.summary) if request else (world.confirmation, world.reply)
    context = world.context if request else world.current
    outcome = SimpleNamespace(
        igreja_id=TENANT, conversation_id=presence.CONVERSATION,
        inbound_message_id=inbound.id, provider_message_id='VISITOR-INBOUND',
        texto=inbound.texto if outcome_text is None else outcome_text,
    )

    def preflight(_session, **kwargs):
        assert kwargs['tier_a_preflight'] is True
        assert kwargs['inbound_message_id'] == inbound.id
        world.preflights.append(inbound.id)
        snapshot = runtime._build_tier_a_preflight(
            igreja_id=TENANT, conversation_id=presence.CONVERSATION, pessoa_id=PERSON,
            inbound_message_id=inbound.id, provider_message_id='VISITOR-INBOUND',
            current_text=inbound.texto,
            config=SimpleNamespace(id=UUID(int=80), comportamento='SINTÉTICO'),
            cred=SimpleNamespace(id=UUID(int=81), provedor='synthetic',
                                 modelo='synthetic', api_key_encrypted='synthetic'),
            accepted_consent_version='lgpd-v2', term_version='lgpd-v2',
        )
        assert snapshot is not None
        return SimpleNamespace(reason=None, preflight=snapshot)

    def forbidden(label):
        return Mock(side_effect=AssertionError(f'local visitor stage reached {label}'))

    provider, router, triage, active_triage, general = (
        forbidden(label) for label in ('LLM', 'S3 router', 'Tier A', 'active Tier A', 'general answer')
    )
    world.providers = (provider, router, triage, active_triage, general)
    monkeypatch.setattr(turn, '_run_audio_local_turn', lambda *_a, **_k: None)
    monkeypatch.setattr(turn, '_local_audio_consent', lambda *_a: False)
    monkeypatch.setattr(turn, '_enabled', lambda _tenant: True)
    monkeypatch.setattr(turn, 'time', SimpleNamespace(monotonic=lambda: 1000.0))
    monkeypatch.setattr(runtime, 'process_inbound_message', preflight)
    monkeypatch.setattr(runtime, '_load_tier_a_plan_state', lambda *_a: (None, None, None))
    monkeypatch.setattr(whatsapp_privilege, 'resolve_whatsapp_privilege_context', lambda *_a, **_k: context)
    monkeypatch.setattr(qw, '_scope_agent_execution_session', lambda *_a, **_k: None)
    monkeypatch.setattr(qw, '_agent_reply_idempotency_key', lambda _outcome: outbound.provider_message_id)
    monkeypatch.setattr(qw, '_reserve_agent_reply_intent', lambda *_a: outbound)
    monkeypatch.setattr(qw, '_load_agent_reply_intent', lambda *_a:
                        None if outbound.agent_reply_state == AGENT_REPLY_RESERVED
                        else SimpleNamespace(state=outbound.agent_reply_state))
    monkeypatch.setattr(semantic_triage, 'tier_a_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(qw, '_tier_a_effective_settings', lambda *_a: SimpleNamespace())
    monkeypatch.setattr(qw, '_run_tier_a_batch', triage)
    monkeypatch.setattr(qw, '_run_active_tier_a_turn', active_triage)
    monkeypatch.setattr(qw, '_persist_tier_a_handoff', forbidden('handoff instead of local staging'))
    monkeypatch.setattr(cell_report_whatsapp, 'cell_report_enabled_from_environment', lambda _tenant: False)
    monkeypatch.setattr(llm, 'LLMClient', provider)
    monkeypatch.setattr(agent_privilege_routing, 'route_privileged_message', router)
    monkeypatch.setattr(turn, '_general_answer', general)
    monkeypatch.setattr('app.agent.masking.log_agent_event',
                        lambda *_a, **kwargs: world.logs.append(kwargs))
    monkeypatch.setattr('app.agent.masking.log_ai_usage',
                        lambda *_a, **kwargs: world.logs.append(kwargs))

    def deliver(*_a, **_k):
        assert world.db.events[-1] == ('commit',), 'delivery before successful commit'
        world.db.events.append(('deliver',))
        world.deliveries.append(outbound.texto)

    monkeypatch.setattr(qw, '_deliver_agent_reply_intent', deliver)
    result = turn.run_privileged_turn(
        lambda: world.db, lambda: world.db, outcome, igreja_id=TENANT,
        turn_identity=None, uses_dedicated_agent_session=False,
        ownership_guard=None, evolution_client=object(),
    )
    for spy in world.providers:
        spy.assert_not_called()
    return result


def _prepared(world, monkeypatch):
    _turn(world, monkeypatch, request=True)
    rows = world.db.tables[AgentActionProposal]
    assert len(rows) == 1, 'local visitor command did not prepare its proposal'
    row = rows[0]
    assert (row.action, row.target_kind, row.target_id) == (ACTION, 'reuniao', MEETING)
    assert (row.actor_app_user_id, row.actor_pessoa_id) == (ACTOR, PERSON)
    assert row.state == 'preparada' and row.summary_message_id == presence.SUMMARY
    assert row.arguments_json == {'reuniao_id': str(MEETING), 'nome_visitante': NAME}
    assert world.summary.agent_privilege_context['kind'] == 'summary'
    assert 'SIM' in world.summary.texto
    assert world.preflights == [presence.REQUEST]
    _no_effect(world)
    _private_surfaces(world)
    return row


def _pending(world, monkeypatch):
    row = _prepared(world, monkeypatch)
    # Acknowledge fake worker delivery using the real promotion contract.
    # The HTTP/PG transport will prove this acknowledgement separately.
    world.summary.agent_reply_state = AGENT_REPLY_CONFIRMED
    proposals.promote_action_proposal_after_delivery(
        world.db, igreja_id=TENANT, conversation_id=presence.CONVERSATION,
        proposal_id=row.id, summary_message_id=presence.SUMMARY,
        now=NOW + dt.timedelta(seconds=1),
    )
    assert row.state == 'pendente'
    return row


@pytest.mark.parametrize('name', ['A', 'V' * 200, 'FICTÍCIO-Érica', '架空訪問者', 'FICTÍCIO-e\u0301'])
def test_closed_action_preserves_valid_nominal_unicode(name):
    action = _action()
    target = proposals.ProposalTarget('reuniao', MEETING)
    args = {'reuniao_id': str(MEETING), 'nome_visitante': name}
    assert proposals.canonical_action_arguments(action, target, args) == args
    assert catalog.validated_action_arguments(ACTION, args) == args


@pytest.mark.parametrize('extra', [
    'igreja_id', 'pessoa_id', 'app_user_id', 'roles', 'celula_id',
    'observacao_oracao', 'oracao', 'expected_actor_pessoa_id', 'contador',
])
def test_proposal_and_adapter_reject_every_extra_claim(extra):
    action = _action()
    args = {'reuniao_id': str(MEETING), 'nome_visitante': NAME, extra: str(OTHER)}
    with pytest.raises(proposals.ProposalContractError):
        proposals.canonical_action_arguments(action, proposals.ProposalTarget('reuniao', MEETING), args)
    with pytest.raises(ValueError):
        catalog.validated_action_arguments(ACTION, args)


@pytest.mark.parametrize('missing', ['reuniao_id', 'nome_visitante'])
def test_closed_arguments_require_both_fields(missing):
    action = _action()
    args = {'reuniao_id': str(MEETING), 'nome_visitante': NAME}
    del args[missing]
    with pytest.raises(proposals.ProposalContractError):
        proposals.canonical_action_arguments(action, proposals.ProposalTarget('reuniao', MEETING), args)
    with pytest.raises(ValueError):
        catalog.validated_action_arguments(ACTION, args)


@pytest.mark.parametrize('name', [
    '', '   ', 'V' * 201, None, True, 123, {}, 'FICTÍCIO\x00',
    'FICTÍCIO\nOutro', 'FICTÍCIO\tOutro', 'FICTÍCIO\x7f', 'FICTÍCIO\u202e',
])
def test_nominal_name_validation_is_closed_and_errors_are_private(name):
    action = _action()
    args = {'reuniao_id': str(MEETING), 'nome_visitante': name}
    with pytest.raises(proposals.ProposalContractError) as error:
        proposals.canonical_action_arguments(action, proposals.ProposalTarget('reuniao', MEETING), args)
    with pytest.raises(ValueError) as adapter_error:
        catalog.validated_action_arguments(ACTION, args)
    if isinstance(name, str) and name.strip():
        assert name not in str(error.value) and name not in str(adapter_error.value)


@pytest.mark.parametrize('meeting_id', [None, True, str(UUID(int=0)), MEETING.hex, str(OTHER)])
def test_proposal_meeting_id_must_be_canonical_and_match_target(meeting_id):
    action = _action()
    with pytest.raises(proposals.ProposalContractError):
        proposals.canonical_action_arguments(action, proposals.ProposalTarget('reuniao', MEETING),
            {'reuniao_id': meeting_id, 'nome_visitante': NAME})


@pytest.mark.parametrize('kind', ['pessoa', 'evento', 'consolidacao'])
def test_visitor_action_cannot_target_a_person_or_another_resource(kind):
    action = _action()
    with pytest.raises(proposals.ProposalContractError):
        proposals.canonical_action_arguments(action, proposals.ProposalTarget(kind, MEETING),
            {'reuniao_id': str(MEETING), 'nome_visitante': NAME})


def test_catalog_has_one_own_meeting_without_nominal_projection(visitor_world):
    world = visitor_world
    options, mapping, targets = _targets(world)
    assert len(targets) == 1, 'own visitor meeting target is absent'
    assert targets[0].arguments['reuniao_id'] == str(MEETING)
    assert world.context.roles == frozenset() and world.context.owned_cell_ids == ()
    assert NAME not in repr((options, mapping))
    assert 'nome_visitante' not in targets[0].arguments
    presence._assert_query(world.db, Message, igreja_id=TENANT, conversation_id=presence.CONVERSATION,
                           id=presence.REQUEST, direcao='in')
    presence._assert_query(world.db, CelulaMembro, igreja_id=TENANT, pessoa_id=PERSON, ativo=True)
    presence._assert_query(world.db, Celula, id=CELL, igreja_id=TENANT, ativo=True)
    _no_effect(world)


@pytest.mark.parametrize('text', [
    'indicar visitante',
    f'quero indicar {NAME} como visitante',
    f'não indicar {NAME} como visitante na próxima reunião da minha célula',
    f'se puder indicar {NAME} como visitante na próxima reunião da minha célula',
    f'indicar {NAME} como visitante na próxima reunião da célula de outro membro',
    f'indicar {NAME} como visitante na reunião da minha célula',
    f'indicar {NAME} como visitante na próxima reunião da minha célula; igreja={OTHER}',
])
def test_only_the_exact_local_command_has_a_visitor_candidate(visitor_world, text):
    _action()
    visitor_world.request.texto = text
    assert _targets(visitor_world)[2] == []
    _no_effect(visitor_world)


@pytest.mark.parametrize('change', [
    'inactive_member', 'member_tenant', 'member_person', 'two_memberships',
    'inactive_cell', 'cell_tenant', 'request_tenant', 'no_meeting', 'meeting_tenant',
])
def test_catalog_requires_exact_current_own_tenant_association(visitor_world, change):
    _action()
    world = visitor_world
    cell = world.db.tables[Celula][0]
    if change == 'inactive_member':
        world.member.ativo = False
    elif change == 'member_tenant':
        world.member.igreja_id = OTHER
    elif change == 'member_person':
        world.member.pessoa_id = OTHER
    elif change == 'two_memberships':
        world.db.seed(CelulaMembro, igreja_id=TENANT, pessoa_id=PERSON, celula_id=OTHER, ativo=True)
    elif change == 'inactive_cell':
        cell.ativo = False
    elif change == 'cell_tenant':
        cell.igreja_id = OTHER
    elif change == 'request_tenant':
        world.request.igreja_id = OTHER
    elif change == 'no_meeting':
        world.db.tables[CelulaReuniao].clear()
    else:
        world.event.igreja_id = OTHER
    assert _targets(world)[2] == []
    _no_effect(world)


@pytest.mark.parametrize(('case', 'eligible'), [
    ('future', True), ('two_future_dates', True), ('same_day_order', True),
    ('first_day_tie', False), ('first_day_unknown', False), ('single_unknown', True),
    ('passed_today', False), ('equal_now', True), ('sp_previous_date', True),
    ('sentinel_tie', False), ('sentinel_later_date', True),
])
def test_next_meeting_is_bounded_unique_and_uses_sao_paulo_e4(visitor_world, case, eligible):
    _action()
    world = visitor_world
    if case in {'two_future_dates', 'single_unknown'}:
        world.db.seed(CelulaReuniao, id=OTHER, igreja_id=TENANT, celula_id=CELL,
                      data=dt.date(2030, 1, 2), hora='18:00')
        if case == 'single_unknown':
            world.event.hora = None
    elif case in {'same_day_order', 'first_day_tie', 'first_day_unknown'}:
        world.db.seed(CelulaReuniao, id=OTHER, igreja_id=TENANT, celula_id=CELL,
                      data=world.event.data,
                      hora='22:00' if case == 'same_day_order' else '20:00' if case == 'first_day_tie' else None)
    elif case in {'passed_today', 'equal_now', 'sp_previous_date'}:
        world.event.data = dt.date(2029, 12, 31)
        world.event.hora = {'passed_today': '21:29', 'equal_now': '21:30', 'sp_previous_date': '22:00'}[case]
    elif case.startswith('sentinel'):
        world.db.tables[CelulaReuniao].clear()
        for number in range(65):
            world.db.seed(CelulaReuniao, id=UUID(int=300 + number), igreja_id=TENANT, celula_id=CELL,
                          data=dt.date(2030, 1, 1) if case == 'sentinel_tie' or number == 0
                          else dt.date(2030, 1, 2), hora='20:00')
    targets = _targets(world)[2]
    assert len(targets) == (1 if eligible else 0)
    if eligible:
        expected = UUID(int=300) if case.startswith('sentinel') else MEETING
        assert targets[0].arguments['reuniao_id'] == str(expected)
    meetings = [stmt for stmt in world.db.statements
                if stmt.column_descriptions[0]['entity'] is CelulaReuniao]
    assert meetings and all(stmt._limit_clause is not None and stmt._limit_clause.value == 65 for stmt in meetings)
    presence._assert_query(world.db, CelulaReuniao, igreja_id=TENANT, celula_id=CELL)
    _no_effect(world)


def test_local_command_stages_private_arguments_after_local_preflight_without_provider_calls(visitor_world, monkeypatch):
    _prepared(visitor_world, monkeypatch)


@pytest.mark.parametrize('outcome_text', [
    'não indicar OUTCOME-FICTÍCIO-DIVERGENTE como visitante na próxima reunião da minha célula',
    _command('OUTCOME-FICTÍCIO-DIVERGENTE'),
])
def test_local_stage_uses_snapshot_name_even_when_outcome_negates_or_names_another_visitor(
    visitor_world, monkeypatch, outcome_text,
):
    world = visitor_world
    assert world.request.texto == _command() and world.request.texto != outcome_text
    _turn(world, monkeypatch, request=True, outcome_text=outcome_text)
    rows = world.db.tables[AgentActionProposal]
    assert len(rows) == 1, 'canonical persisted snapshot must win over divergent outcome'
    assert rows[0].source_message_id == presence.REQUEST
    assert rows[0].arguments_json == {'reuniao_id': str(MEETING), 'nome_visitante': NAME}
    assert 'OUTCOME-FICTÍCIO-DIVERGENTE' not in repr(rows[0].arguments_json)
    assert world.request.texto == _command() and world.preflights == [presence.REQUEST]
    _private_surfaces(world)
    _private_surfaces(world, 'OUTCOME-FICTÍCIO-DIVERGENTE')
    _no_effect(world)


def test_valid_outcome_cannot_authorize_an_invalid_persisted_snapshot(visitor_world, monkeypatch):
    _action()
    world = visitor_world
    invalid_name = 'V' * 201
    invalid_snapshot = _command(invalid_name)
    world.request.texto = invalid_snapshot
    assert invalid_snapshot != _command()
    # Invalid local input must close locally. All later LLM/triage branches
    # stay blocked by the existing _turn spies, not by a mocked parser.
    _turn(world, monkeypatch, request=True, outcome_text=_command())
    assert world.request.texto == invalid_snapshot and world.preflights == [presence.REQUEST]
    assert world.db.tables[AgentActionProposal] == []
    _private_surfaces(world)
    _private_surfaces(world, invalid_name)
    _no_effect(world)


@pytest.mark.parametrize('name', ['FICTÍCIO-Érica', 'V' * 200, 'FICTÍCIO-架空-e\u0301'])
def test_local_stage_preserves_valid_name_only_in_private_arguments(visitor_world, monkeypatch, name):
    world = visitor_world
    world.request.texto = _command(name)
    _turn(world, monkeypatch, request=True)
    assert len(world.db.tables[AgentActionProposal]) == 1
    assert world.db.tables[AgentActionProposal][0].arguments_json['nome_visitante'] == name
    _private_surfaces(world, name)
    _no_effect(world)


@pytest.mark.parametrize('name', ['', '   ', 'V' * 201, 'FICTÍCIO\nOutro', 'FICTÍCIO\x00', 'FICTÍCIO\u202e'])
def test_invalid_local_nominal_command_has_no_provider_or_proposal(visitor_world, monkeypatch, name):
    _action()
    world = visitor_world
    world.request.texto = _command(name)
    _turn(world, monkeypatch, request=True)
    assert world.db.tables[AgentActionProposal] == []
    _no_effect(world)
    _private_surfaces(world, name if name.strip() else NAME)


@pytest.mark.parametrize('word', ['SIM', 'CONFIRMO'])
def test_exact_confirmation_runs_shared_writer_then_commits_one_receipt(visitor_world, monkeypatch, word):
    writer = _service()
    spy = Mock(wraps=writer)
    monkeypatch.setattr(catalog, 'register_own_visitor_expectation', spy, raising=False)
    world = visitor_world
    proposal = _pending(world, monkeypatch)
    world.confirmation.texto = word
    _turn(world, monkeypatch)
    rows, receipts = world.db.tables[CelulaExpectativaVisitante], world.db.tables[AgentActionReceipt]
    assert len(rows) == len(receipts) == 1 and proposal.state == 'executada'
    row = rows[0]
    assert (row.igreja_id, row.reuniao_id, row.pessoa_id, row.nome_visitante, row.observacao_oracao) == (
        TENANT, MEETING, PERSON, NAME, None)
    assert receipts[0].proposal_id == proposal.id and receipts[0].effect_reference == str(row.id)
    assert receipts[0].confirmation_message_id == presence.CONFIRM
    assert receipts[0].receipt_text == 'Registro confirmado.'
    assert world.reply.texto.startswith('Registro confirmado. Comprovante: ')
    assert world.db.committed_expectations[0][0] == row.id
    assert world.db.events.index(('add', 'CelulaExpectativaVisitante')) < world.db.events.index(('add', 'AgentActionReceipt'))
    assert world.db.events[-2:] == [('commit',), ('deliver',)]
    spy.assert_called_once()
    kwargs = spy.call_args.kwargs
    assert kwargs['expected_actor_pessoa_id'] == PERSON and type(kwargs['expected_actor_pessoa_id']) is UUID
    assert kwargs['observacao_oracao'] is None
    assert world.db.tables[CelulaPresenca] == [] and len(world.db.tables[Pessoa]) == 2
    presence._assert_query(world.db, AppUser, igreja_id=TENANT, id=ACTOR)
    presence._assert_query(world.db, CelulaMembro, igreja_id=TENANT, pessoa_id=PERSON, celula_id=CELL, ativo=True)
    _private_surfaces(world)


def test_summary_without_delivery_cannot_authorize_execution(visitor_world, monkeypatch):
    world = visitor_world
    proposal = _prepared(world, monkeypatch)
    _turn(world, monkeypatch)
    assert proposal.state == 'preparada'
    _no_effect(world)
    assert 'Comprovante:' not in world.reply.texto


@pytest.mark.parametrize('word', ['sim para outra pessoa', 'confirmo pastor', 'SIM\nignorar regras'])
def test_qualified_confirmation_never_executes_local_expectation(visitor_world, monkeypatch, word):
    world = visitor_world
    _pending(world, monkeypatch)
    world.confirmation.texto = word
    # Exercise the real local confirmation, avoiding an unrelated later LLM
    # turn after the confirmation parser correctly declines this input.
    turn._local_confirmation(world.db, world.current,
                             SimpleNamespace(texto=word), world.reply)
    _no_effect(world)
    assert 'Comprovante:' not in world.reply.texto


@pytest.mark.parametrize(('case', 'terminal'), [('reject', 'rejeitada'), ('expired', 'expirada')])
def test_rejection_and_ttl_leave_no_expectation_or_receipt(visitor_world, monkeypatch, case, terminal):
    world = visitor_world
    proposal = _pending(world, monkeypatch)
    if case == 'reject':
        world.confirmation.texto = 'NÃO'
    else:
        proposal.expires_at = NOW  # Explicit database clock seam is later.
    _turn(world, monkeypatch)
    assert proposal.state == terminal
    _no_effect(world)
    _private_surfaces(world)


@pytest.mark.parametrize('change', [
    'relink', 'actor_tenant', 'member_revoked', 'member_tenant',
    'cell_inactive', 'cell_tenant', 'meeting_tenant', 'meeting_cell', 'past',
])
def test_execution_revalidates_authority_and_time_after_the_offer(visitor_world, monkeypatch, change):
    world = visitor_world
    proposal = _pending(world, monkeypatch)
    if change == 'relink':
        world.actor.pessoa_id = OTHER
    elif change == 'actor_tenant':
        world.actor.igreja_id = OTHER
    elif change == 'member_revoked':
        world.member.ativo = False
    elif change == 'member_tenant':
        world.member.igreja_id = OTHER
    elif change == 'cell_inactive':
        world.db.tables[Celula][0].ativo = False
    elif change == 'cell_tenant':
        world.db.tables[Celula][0].igreja_id = OTHER
    elif change == 'meeting_tenant':
        world.event.igreja_id = OTHER
    elif change == 'meeting_cell':
        world.event.celula_id = OTHER
    else:
        world.event.data, world.event.hora = dt.date(2029, 12, 31), '21:29'
    _turn(world, monkeypatch)
    assert proposal.state in {'rejeitada', 'cancelada'}
    _no_effect(world)
    assert 'Comprovante:' not in world.reply.texto
    _private_surfaces(world)


@pytest.mark.parametrize('change', ['public_optout', 'actor', 'fingerprint'])
def test_current_server_context_controls_pending_confirmation(visitor_world, monkeypatch, change):
    world = visitor_world
    _pending(world, monkeypatch)
    if change == 'public_optout':
        world.current = PublicWhatsappContext(igreja_id=TENANT,
            conversation_id=presence.CONVERSATION, inbound_message_id=presence.CONFIRM)
    elif change == 'actor':
        world.current = replace(world.current, app_user_id=OTHER, pessoa_id=OTHER)
    else:
        world.current = replace(world.current, scope_fingerprint='9' * 64)
    _turn(world, monkeypatch)
    _no_effect(world)
    assert 'Comprovante:' not in world.reply.texto


def test_same_confirmation_and_a_new_sim_do_not_reexecute_the_writer(visitor_world, monkeypatch):
    world = visitor_world
    proposal = _pending(world, monkeypatch)
    prior_commits = world.db.events.count(('commit',))
    kwargs = dict(igreja_id=TENANT, conversation_id=presence.CONVERSATION,
                  confirmation_message_id=presence.CONFIRM, disposition=proposals.ProposalDisposition.CONFIRM,
                  execute=lambda execution: turn._execute(world.db, execution), now=NOW + dt.timedelta(seconds=3))
    first = proposals.resolve_and_execute_action_proposal(world.db, **kwargs)
    assert first.status.value == 'executed'
    second = proposals.resolve_and_execute_action_proposal(world.db, **kwargs)
    assert second.status.value == 'receipt' and second.receipt_id == first.receipt_id
    new_id = UUID(int=200)
    world.db.seed(Message, id=new_id, igreja_id=TENANT, conversation_id=presence.CONVERSATION,
                  texto='SIM', direcao='in', autor='pessoa', criado_em=NOW + dt.timedelta(seconds=4))
    world.current = replace(world.current, inbound_message_id=new_id)
    third = proposals.resolve_and_execute_action_proposal(world.db, **{**kwargs, 'confirmation_message_id': new_id})
    assert third.status.value == 'no_pending'
    assert proposal.state == 'executada'
    assert len(world.db.tables[CelulaExpectativaVisitante]) == len(world.db.tables[AgentActionReceipt]) == 1
    assert world.db.events.count(('commit',)) == prior_commits
    _private_surfaces(world)


def test_before_commit_failure_never_delivers_a_success_receipt(visitor_world, monkeypatch):
    world = visitor_world
    _pending(world, monkeypatch)
    prior_deliveries = list(world.deliveries)
    world.db.fail_commit = True
    with pytest.raises(RuntimeError, match='^SYNTHETIC_COMMIT_FAILURE$'):
        _turn(world, monkeypatch)
    assert world.deliveries == prior_deliveries
    assert world.db.committed_expectations == ()
    assert ('rollback',) in world.db.events
    # The direct-select double records rollback but cannot prove SQL undo.


@pytest.mark.parametrize('expected_actor', [True, str(PERSON), UUID(int=0), OTHER])
def test_trusted_writer_parameter_does_not_accept_claims_or_relinked_identity(visitor_world, expected_actor):
    writer = _service()
    world = visitor_world
    with pytest.raises((HTTPException, ValueError)):
        writer(world.db, catalog._user(world.context), reuniao_id=MEETING,
               nome_visitante=NAME, observacao_oracao=None, expected_actor_pessoa_id=expected_actor)
    _no_effect(world)


def test_structural_claims_never_grant_catalog_execution_authority(visitor_world):
    _action()
    world = visitor_world
    claims = SimpleNamespace(igreja_id=TENANT, app_user_id=ACTOR, pessoa_id=PERSON,
                             roles=frozenset({'pastor'}), owned_cell_ids=(CELL,))
    before = len(world.db.statements)
    with pytest.raises(HTTPException) as error:
        catalog.execute_catalog_action(world.db, claims, ACTION,
            {'reuniao_id': str(MEETING), 'nome_visitante': NAME})
    assert error.value.status_code == 403 and len(world.db.statements) == before
    _no_effect(world)


def test_writer_rechecks_clock_after_member_lookup_before_insert(visitor_world, monkeypatch):
    writer = _service()
    world = visitor_world
    original = world.db.execute
    clock = [NOW]

    def lookup(statement):
        rows = original(statement)
        if statement.column_descriptions[0]['entity'] is CelulaMembro:
            clock[0] = dt.datetime(2030, 1, 1, 23, 1, tzinfo=dt.timezone.utc)
        return rows

    monkeypatch.setattr(world.db, 'execute', lookup)
    monkeypatch.setattr(schedule, 'now_in_sao_paulo', lambda now=None:
                        (now or clock[0]).astimezone(schedule.SAO_PAULO_TZ))
    with pytest.raises(HTTPException):
        writer(world.db, catalog._user(world.context), reuniao_id=MEETING,
               nome_visitante=NAME, observacao_oracao=None, expected_actor_pessoa_id=PERSON)
    _no_effect(world)


def test_legacy_human_writer_preserves_multiple_rows_optional_note_and_no_commit(visitor_world):
    writer = _service()
    world = visitor_world
    world.event.data = dt.date(2029, 12, 30)
    note = 'OBSERVAÇÃO-FICTÍCIA'
    first = writer(world.db, catalog._user(world.context), reuniao_id=MEETING,
                   nome_visitante=NAME, observacao_oracao=note)
    second = writer(world.db, catalog._user(world.context), reuniao_id=MEETING,
                    nome_visitante=NAME, observacao_oracao=None)
    assert first.id != second.id and len(world.db.tables[CelulaExpectativaVisitante]) == 2
    assert first.observacao_oracao == note and second.observacao_oracao is None
    assert first.pessoa_id == second.pessoa_id == PERSON
    assert ('commit',) not in world.db.events
    assert world.db.tables[AgentActionReceipt] == world.db.tables[CelulaPresenca] == []


@pytest.mark.parametrize('name', [NAME, 'V' * 201])
def test_public_local_visitor_attempt_completes_without_worker_fallback_or_reply(
    visitor_world, monkeypatch, name,
):
    from app.workers import queue_worker as qw

    world = visitor_world
    world.request.texto = _command(name)
    world.context = PublicWhatsappContext(
        igreja_id=TENANT, conversation_id=presence.CONVERSATION,
        inbound_message_id=presence.REQUEST,
    )
    before_messages = tuple(world.db.tables[Message])
    before_outbound = [(row.id, row.texto, row.agent_reply_state, row.agent_privilege_context)
                       for row in before_messages if row.direcao == 'out']
    assert all(text == '' and metadata is None for _id, text, _state, metadata in before_outbound)
    result = _turn(world, monkeypatch, request=True)
    # None hands control back to the worker's Tier A/general path. Denial
    # must finish the turn, including for invalid private nominal input.
    assert result is qw.AgentRunDisposition.COMPLETED
    for spy in world.providers:
        spy.assert_not_called()
    _no_effect(world)
    assert world.db.tables[AgentActionProposal] == []
    assert world.deliveries == world.logs == world.db.events == []
    assert tuple(world.db.tables[Message]) == before_messages
    assert [(row.id, row.texto, row.agent_reply_state, row.agent_privilege_context)
            for row in world.db.tables[Message] if row.direcao == 'out'] == before_outbound
    _private_surfaces(world, name)


def test_summary_revalidation_rejects_tampered_persisted_target_kind(visitor_world, monkeypatch):
    import hashlib
    from app.db.models import WhatsappConnection
    from app.services import whatsapp_privilege

    world = visitor_world
    # Keep real staging: currently R1 can fail here before this kind oracle
    # is reached. Do not construct a replacement proposal or weaken hashes.
    proposal = _prepared(world, monkeypatch)
    phone, instance = '5500000000000', 'VISITOR-SYNTHETIC-INSTANCE'
    world.conversation.telefone = phone
    world.db.tables[WhatsappConnection] = []
    world.db.seed(WhatsappConnection, id=UUID(int=901), igreja_id=TENANT, instance=instance)

    def source_context(session, **kwargs):
        assert session is world.db
        assert kwargs['igreja_id'] == TENANT and kwargs['conversation_id'] == presence.CONVERSATION
        assert kwargs['inbound_message_id'] == presence.REQUEST and kwargs['sensitive'] is False
        return world.context  # Source REQUEST, never the confirmation context.

    resolver = Mock(side_effect=source_context)
    monkeypatch.setattr(whatsapp_privilege, 'resolve_whatsapp_privilege_context', resolver)
    assert proposal.arguments_sha256 == proposals.canonical_arguments_sha256(proposal.arguments_json)
    assert proposal.summary_sha256 == hashlib.sha256(world.summary.texto.encode('utf-8')).hexdigest()
    kwargs = dict(conversation=world.conversation, recipient_phone=phone, instance=instance)
    assert turn.reply_still_authorized(world.db, world.summary, **kwargs) is True
    resolver.assert_called()
    before_deliveries, before_logs = list(world.deliveries), list(world.logs)
    proposal.target_kind = 'pessoa'
    assert proposal.arguments_sha256 == proposals.canonical_arguments_sha256(proposal.arguments_json)
    assert proposal.summary_sha256 == hashlib.sha256(world.summary.texto.encode('utf-8')).hexdigest()
    assert turn.reply_still_authorized(world.db, world.summary, **kwargs) is False
    assert world.deliveries == before_deliveries and world.logs == before_logs
    _no_effect(world)
    _private_surfaces(world)
