"""Visitor RED against ROOT's disposable PG and existing ASGI transport.

No execution during authoring. Fixtures use msg_idemp1 without RLS policies;
these tests prove backend scoping, not RLS or external WhatsApp delivery.
Only HTTP queue, LLM/triage and Evolution providers are doubles. Resolver,
worker, catalog, proposals, human writer, ledger and persisted rows stay real.
The separate public CHECK test executes the future migration UP verbatim.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
from pathlib import Path
import re
from threading import Barrier, Lock, current_thread
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.agent import runtime as runtime_module
from app.db.models import (
    AgentActionProposal, AgentActionReceipt, AiUsageLog, AppUser, Celula,
    CelulaExpectativaVisitante, CelulaMembro, CelulaPresenca, CelulaReuniao,
    CelulaReuniaoRegistro, NotificationOutbox, Pessoa,
)
from app.deps import CurrentUser
from app.domain import cell_meetings_schedule as schedule
from app.routers.cell_discipulo import (
    _my_visitor_names, get_my_next_meeting, indicate_my_visitor,
)
from app.routers.cell_meetings import RegisterExpectativaRequest, register_expectativa_visitante
from app.services.agent_action_proposals import ProposalContractError
from app.services.agent_privilege_catalog import build_catalog
from app.services.llm import LLMClient, LLMUsage, TypedChoiceResult, TypedLLMResult
from app.services.ministerial_actions import register_own_visitor_expectation
from app.services.whatsapp_privilege import PrivilegeContext, resolve_whatsapp_privilege_context
from app.workers import queue_worker as worker_module
from tests import test_agent_privileged_turn_pg as presence
from tests.conftest_rls import rls_database_url  # noqa: F401 - full dependency chain
from tests.test_messages_inbound_idempotency import (
    msg_engine_fx, _seed_igreja_with_connection,
)
from tests.test_agent_privileged_turn_pg import (  # noqa: F401 - imported fixtures
    s3_turn, own_member_turn, own_member_unique_turn, own_http_turn,
)

pytestmark = pytest.mark.rls_integration
_IGREJA = presence._IGREJA
_ACTION = 'registrar_expectativa_visitante'
_NAME = 'Visitante Sintético'
_COMMAND = f'indicar {_NAME} como visitante na próxima reunião da minha célula'
_MIGRATIONS = Path(__file__).resolve().parents[1] / 'migrations'
_SQL = _MIGRATIONS / '20261002_173000_visitor_expectation_whatsapp.sql'
_LEGACY = (
    ('registrar_decisao', 'pessoa'), ('marcar_presenca', 'pessoa'),
    ('enviar_relatorio_celula', 'reuniao'), ('configurar_lembrete_agenda', 'evento'),
    ('configurar_lembrete_consolidacao', 'pessoa'),
    ('marcar_fonovisita_feita', 'pendencia_consolidacao'),
    ('atribuir_consolidacao', 'consolidacao'),
)


def _migration():
    # Missing SQL is an assertion in the TEST BODY, never an import/fixture error.
    assert _SQL.is_file(), 'visitor migration not implemented'
    source = _SQL.read_bytes().decode('utf-8')
    begin, end = '-- ROLLBACK-BEGIN', '-- ROLLBACK-END'
    assert source.count(begin) == source.count(end) == 1
    assert source.index(begin) < source.index(end)
    block = source.split(begin, 1)[1].split(end, 1)[0]
    lines = block.splitlines(keepends=True)
    assert all(not line.strip() or line.startswith('--') for line in lines)
    down = ''.join(line[2:] if line.startswith('--') else line for line in lines)
    assert down.strip(), 'empty rollback'
    # UP retains every original byte after UTF-8 decoding, including comments.
    return source, down


@pytest.fixture
def public_proposal_checks(msg_engine_fx, rls_database_url):
    """Single owner of a bare public table, without touching unknown tables.

    Reuse the nominal engine, no DSN/engine creation here. The advisory lock
    guards this test owner only; it is not proof of application serialization.
    """
    with msg_engine_fx.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        assert connection.exec_driver_sql('SELECT current_database()').scalar_one() == make_url(rls_database_url).database
        version = int(connection.exec_driver_sql('SHOW server_version_num').scalar_one())
        assert 170000 <= version < 180000, 'PostgreSQL 17 required'
        locked = connection.exec_driver_sql('SELECT pg_try_advisory_lock(20261002173000)').scalar_one()
        assert locked is True, 'public CHECK test already has an owner'
        created = False
        try:
            assert connection.exec_driver_sql(
                "SELECT to_regclass('public.agent_action_proposals')").scalar_one() is None, 'unknown/preexisting public table'
            connection.exec_driver_sql("SET lock_timeout = '2s'")
            connection.exec_driver_sql("SET statement_timeout = '8s'")
            connection.exec_driver_sql(
                'CREATE TABLE public.agent_action_proposals (action text NOT NULL, target_kind text NOT NULL)')
            created = True
            legacy = (_MIGRATIONS / '20260928_080000_whatsapp_consolidation_v3.sql').read_text(encoding='utf-8')
            start = legacy.index('alter table public.agent_action_proposals')
            stop = legacy.index('alter table public.agent_action_receipts', start)
            # EXACT versioned first two CHECK statements, before receipt DDL.
            connection.exec_driver_sql(legacy[start:stop])
            yield connection
        finally:
            # A rejected transactional DOWN may leave BEGIN aborted.
            try:
                connection.exec_driver_sql('ROLLBACK')
                if created:
                    connection.exec_driver_sql('DROP TABLE public.agent_action_proposals')
            finally:
                try:
                    connection.exec_driver_sql('RESET lock_timeout')
                    connection.exec_driver_sql('RESET statement_timeout')
                finally:
                    connection.exec_driver_sql('SELECT pg_advisory_unlock(20261002173000)')


def _insert_check(connection, action, kind):
    connection.exec_driver_sql(
        'INSERT INTO public.agent_action_proposals(action, target_kind) VALUES (%s, %s)', (action, kind))


def _reject_check(connection, action, kind):
    with pytest.raises(IntegrityError) as error:
        _insert_check(connection, action, kind)
    assert error.value.orig.pgcode == '23514'


def _contract(connection):
    return connection.exec_driver_sql(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint "
        "WHERE conrelid = 'public.agent_action_proposals'::regclass AND contype = 'c' ORDER BY conname").all()


def test_public_migration_up_up_down_up_preserves_closed_legacy(public_proposal_checks):
    up, down = _migration()
    connection = public_proposal_checks
    baseline = _contract(connection)
    assert {row[0] for row in baseline} == {
        'agent_action_proposals_action_closed', 'agent_action_proposals_target_kind_closed'}
    for action, kind in _LEGACY:
        _insert_check(connection, action, kind)
    _reject_check(connection, _ACTION, 'reuniao')
    connection.exec_driver_sql(up)
    enlarged = _contract(connection)
    connection.exec_driver_sql(up)
    assert _contract(connection) == enlarged
    _insert_check(connection, _ACTION, 'reuniao')
    assert connection.exec_driver_sql('SELECT count(*) FROM public.agent_action_proposals').scalar_one() == 8
    for action, kind in _LEGACY:
        _reject_check(connection, action, 'reuniao' if kind == 'pessoa' else 'pessoa')
    _reject_check(connection, _ACTION, 'pessoa')
    _reject_check(connection, _ACTION, 'evento')
    _reject_check(connection, 'acao_desconhecida', 'reuniao')
    _reject_check(connection, 'registrar_decisao', 'alvo_desconhecido')
    connection.exec_driver_sql('DELETE FROM public.agent_action_proposals WHERE action = %s', (_ACTION,))
    connection.exec_driver_sql(down)
    assert _contract(connection) == baseline
    assert connection.exec_driver_sql(
        'SELECT action, target_kind FROM public.agent_action_proposals ORDER BY action').all() == sorted(_LEGACY)
    _reject_check(connection, _ACTION, 'reuniao')
    connection.exec_driver_sql(up)
    _insert_check(connection, _ACTION, 'reuniao')
    assert _contract(connection) == enlarged


def test_public_down_after_use_raises_without_changing_contract_or_rows(public_proposal_checks):
    up, down = _migration()
    connection = public_proposal_checks
    connection.exec_driver_sql(up)
    for action, kind in (*_LEGACY, (_ACTION, 'reuniao')):
        _insert_check(connection, action, kind)
    before = _contract(connection)
    rows = connection.exec_driver_sql('SELECT action, target_kind FROM public.agent_action_proposals ORDER BY action').all()
    with pytest.raises(DBAPIError) as error:
        connection.exec_driver_sql(down)
    assert error.value.orig.pgcode == 'P0001'  # genuine RAISE EXCEPTION
    connection.exec_driver_sql('ROLLBACK')
    assert _contract(connection) == before
    assert connection.exec_driver_sql(
        'SELECT action, target_kind FROM public.agent_action_proposals ORDER BY action').all() == rows
    assert len(rows) == 8
    _insert_check(connection, _ACTION, 'reuniao')


def test_public_up_real_table_contention_uses_its_own_local_timeout(public_proposal_checks, msg_engine_fx):
    up, _ = _migration()  # missing source remains an assertion in this body
    active_up = up.split('-- ROLLBACK-BEGIN', 1)[0]
    begin = re.search(r'^\s*begin\s*;', active_up, re.IGNORECASE | re.MULTILINE)
    timeout = re.search(r"^\s*set\s+local\s+lock_timeout\s*=\s*'2s'\s*;",
                        active_up, re.IGNORECASE | re.MULTILINE)
    alter = re.search(r'^\s*alter\s+table\s+public\.agent_action_proposals\b',
                      active_up, re.IGNORECASE | re.MULTILINE)
    commit = re.search(r'^\s*commit\s*;', active_up, re.IGNORECASE | re.MULTILINE)
    assert begin is not None and timeout is not None and alter is not None and commit is not None
    assert begin.start() < timeout.start() < alter.start() < commit.start()
    connection_a = public_proposal_checks
    baseline = _contract(connection_a)
    pid_a = connection_a.exec_driver_sql('SELECT pg_backend_pid()').scalar_one()
    connection_a.exec_driver_sql('BEGIN')
    try:
        connection_a.exec_driver_sql('LOCK TABLE public.agent_action_proposals IN ACCESS EXCLUSIVE MODE')
        # A holds its real lock while B executes; no threads or scheduling
        # double is needed to establish this interleaving.
        with msg_engine_fx.connect().execution_options(isolation_level='AUTOCOMMIT') as connection_b:
            assert connection_b.exec_driver_sql('SELECT pg_backend_pid()').scalar_one() != pid_a
            try:
                # Disable B's inherited harness lock timeout. Only the exact
                # UP can set its 2s LOCAL bound; 8s is the independent safety cap.
                connection_b.exec_driver_sql("SET lock_timeout = '0'")
                connection_b.exec_driver_sql("SET statement_timeout = '8s'")
                assert connection_b.exec_driver_sql('SHOW lock_timeout').scalar_one() == '0'
                with pytest.raises(DBAPIError) as error:
                    connection_b.exec_driver_sql(up)  # original source, no rewrite
                assert error.value.orig.pgcode == '55P03'
            finally:
                try:
                    connection_b.exec_driver_sql('ROLLBACK')
                finally:
                    connection_b.exec_driver_sql('RESET lock_timeout')
                    connection_b.exec_driver_sql('RESET statement_timeout')
    finally:
        connection_a.exec_driver_sql('ROLLBACK')
    assert _contract(connection_a) == baseline
    for action, kind in _LEGACY:
        _insert_check(connection_a, action, kind)
    _reject_check(connection_a, _ACTION, 'reuniao')


@pytest.fixture
def visitor_http_turn(own_http_turn, monkeypatch, caplog):
    turn = own_http_turn
    turn.visitor_provider_calls = []
    turn.visitor_logs = caplog
    turn.original_active_tier_a_turn = worker_module._run_active_tier_a_turn

    def forbidden(*_args, **_kwargs):
        turn.visitor_provider_calls.append('unexpected-provider')
        raise AssertionError('local visitor stage called a provider')

    monkeypatch.setattr(LLMClient, 'generate_typed', forbidden)
    monkeypatch.setattr(LLMClient, 'complete_typed', forbidden)
    monkeypatch.setattr(worker_module, '_run_tier_a_batch', forbidden)
    monkeypatch.setattr(worker_module, '_run_active_tier_a_turn', forbidden)
    # The public fallback in the dedicated relink case also stays synthetic.
    monkeypatch.setattr(runtime_module, 'decrypt_secret', lambda _cipher: 'synthetic-key')
    return turn


def _member(turn, tenant=_IGREJA):
    return CurrentUser(app_user_id=str(turn.app_user_id), igreja_id=str(tenant),
        clerk_user_id='clerk-s3-synthetic', email='', nome='', roles=frozenset())


def _no_effect(turn):
    assert presence._rows(turn, CelulaExpectativaVisitante) == presence._rows(turn, AgentActionReceipt) == []
    assert presence._rows(turn, CelulaPresenca) == []
    assert all('Comprovante:' not in call[2] for call in turn.http_evolution.calls)


def _private_egress(turn, *, allow_usage=False):
    assert all(_NAME not in call[2] for call in turn.http_evolution.calls)
    assert all(_NAME not in (row.texto or '') for row in presence._rows(turn, presence.Message) if row.direcao == 'out')
    assert all(_NAME not in json.dumps(row.agent_privilege_context or {}, ensure_ascii=False)
               for row in presence._rows(turn, presence.Message))
    assert all(_NAME not in row.receipt_text for row in presence._rows(turn, AgentActionReceipt))
    usage = presence._rows(turn, AiUsageLog)
    assert all(_NAME not in json.dumps({key: value for key, value in vars(row).items()
               if not key.startswith('_')}, ensure_ascii=False, default=str) for row in usage)
    if not allow_usage:
        assert usage == []
    assert turn.http_calls == turn.http_prompts == []
    assert all(_NAME not in record.getMessage() for record in turn.visitor_logs.records)


def _pending(turn):
    counts = {model: len(presence._rows(turn, model)) for model in (
        Pessoa, CelulaPresenca, CelulaReuniaoRegistro, NotificationOutbox)}
    envelope = presence._http_enqueue(turn, 'VISITOR-PG-REQUEST', _COMMAND)
    assert turn.http_worker.handle_envelope(envelope) is worker_module.IngestionResult.REGISTERED
    proposals = presence._rows(turn, AgentActionProposal)
    assert len(proposals) == 1
    proposal = proposals[0]
    assert (proposal.action, proposal.target_kind, proposal.target_id, proposal.state) == (
        _ACTION, 'reuniao', turn.meeting_id, 'pendente')
    assert proposal.arguments_json == {'reuniao_id': str(turn.meeting_id), 'nome_visitante': _NAME}
    assert proposal.actor_pessoa_id == turn.actor_id and proposal.actor_app_user_id == turn.app_user_id
    assert proposal.delivered_at is not None and proposal.expires_at > proposal.delivered_at
    summary = next(row for row in presence._rows(turn, presence.Message) if row.id == proposal.summary_message_id)
    assert summary.agent_reply_state == worker_module._AGENT_REPLY_CONFIRMED
    assert (summary.agent_privilege_context or {}).get('kind') == 'summary'
    assert 'Responda SIM ou NÃO' in summary.texto
    request = turn.http_outcomes[-1]
    with turn.factory() as session:
        worker_module._scope_agent_execution_session(session, request, dedicated=False)
        context = resolve_whatsapp_privilege_context(session, igreja_id=_IGREJA,
            conversation_id=turn.conversation_id, inbound_message_id=request.inbound_message_id)
        assert type(context) is PrivilegeContext and context.roles == frozenset()
        assert context.pessoa_id == turn.actor_id and context.owned_cell_ids == ()
        catalog, mapping = build_catalog(session, context)
        targets = [target for target in mapping.values() if target.code == _ACTION]
        assert len(targets) == 1 and dict(targets[0].arguments) == {'reuniao_id': str(turn.meeting_id)}
        assert _NAME not in repr(catalog) and _NAME not in repr(mapping)
    _no_effect(turn)
    assert all(len(presence._rows(turn, model)) == count for model, count in counts.items())
    assert len(turn.http_evolution.calls) == 1 and turn.visitor_provider_calls == []
    _private_egress(turn)
    return proposal, counts


def _confirmed(turn, proposal):
    expectations, receipts = presence._rows(turn, CelulaExpectativaVisitante), presence._rows(turn, AgentActionReceipt)
    assert len(expectations) == len(receipts) == 1
    row, receipt = expectations[0], receipts[0]
    assert (row.igreja_id, row.pessoa_id, row.reuniao_id, row.nome_visitante, row.observacao_oracao) == (
        _IGREJA, turn.actor_id, turn.meeting_id, _NAME, None)
    assert receipt.proposal_id == proposal.id and receipt.effect_reference == str(row.id)
    assert receipt.receipt_text == 'Registro confirmado.'
    assert presence._rows(turn, AgentActionProposal)[0].state == 'executada'
    assert presence._rows(turn, CelulaPresenca) == []
    _private_egress(turn)
    return row, receipt


def test_visitor_http_pg_summary_sim_replay_and_private_human_source(visitor_http_turn):
    turn = visitor_http_turn
    proposal, counts = _pending(turn)
    confirmation = presence._http_enqueue(turn, 'VISITOR-PG-SIM', 'SIM')
    assert turn.http_worker.handle_envelope(confirmation) is worker_module.IngestionResult.REGISTERED
    row, receipt = _confirmed(turn, proposal)
    assert receipt.confirmation_message_id == turn.http_outcomes[-1].inbound_message_id
    assert len([call for call in turn.http_evolution.calls if 'Comprovante:' in call[2]]) == 1
    duplicate = presence._http_enqueue(turn, 'VISITOR-PG-SIM', 'SIM')
    assert turn.http_worker.handle_envelope(duplicate) is worker_module.IngestionResult.DUPLICATE
    again = presence._http_enqueue(turn, 'VISITOR-PG-SIM-NEW', 'SIM')
    assert turn.http_worker.handle_envelope(again) is worker_module.IngestionResult.REGISTERED
    same_row, same_receipt = _confirmed(turn, proposal)
    assert same_row.id == row.id and same_receipt.id == receipt.id
    assert len([call for call in turn.http_evolution.calls if 'Comprovante:' in call[2]]) == 1
    with turn.factory() as session:
        projection = get_my_next_meeting(db=session, current_user=_member(turn))
        assert projection.meeting is not None and projection.meeting.id == str(turn.meeting_id)
        # NextMeetingBody has no visitor-name field: use its REAL private source helper.
        assert _my_visitor_names(session, _IGREJA, turn.meeting_id, turn.actor_id) == [_NAME]
        assert _my_visitor_names(session, _IGREJA, turn.meeting_id, turn.target_id) == []
    assert all(len(presence._rows(turn, model)) == count for model, count in counts.items())


def test_visitor_http_pg_invalid_hmac_does_not_enqueue_or_touch_db(visitor_http_turn):
    turn = visitor_http_turn
    body = json.dumps({'event': 'messages.upsert', 'instance': 's3-synthetic',
        'data': {'message': {'conversation': _COMMAND}}}).encode('utf-8')
    statements = []
    def observe(*_args):
        statements.append(True)
    event.listen(turn.engine, 'before_cursor_execute', observe)
    try:
        response = turn.http_client.post('/whatsapp/webhook', content=body,
            headers={'content-type': 'application/json', 'x-evolution-signature': 'invalid-synthetic'})
    finally:
        event.remove(turn.engine, 'before_cursor_execute', observe)
    assert response.status_code == 401 and statements == []
    assert turn.http_queue.enqueued == turn.http_outcomes == turn.http_evolution.calls == []
    assert turn.visitor_provider_calls == []
    _no_effect(turn)


@pytest.mark.parametrize('revocation', ('actor_relink', 'cell', 'membership', 'meeting_passed'))
def test_visitor_http_pg_revalidation_after_delivered_offer(visitor_http_turn, monkeypatch, revocation):
    turn = visitor_http_turn
    _pending(turn)  # positive delivered proposal and real private context before alteration
    if revocation == 'meeting_passed':
        turn.own_clock[0] = dt.datetime(2030, 1, 1, 23, 1, tzinfo=dt.timezone.utc)
    else:
        with turn.factory.begin() as session:
            if revocation == 'actor_relink':
                statement = update(AppUser).where(AppUser.igreja_id == _IGREJA,
                    AppUser.id == turn.app_user_id, AppUser.pessoa_id == turn.actor_id).values(pessoa_id=turn.target_id)
            elif revocation == 'cell':
                statement = update(Celula).where(Celula.igreja_id == _IGREJA,
                    Celula.id == turn.cell_id, Celula.ativo.is_(True)).values(ativo=False)
            else:
                statement = update(CelulaMembro).where(CelulaMembro.igreja_id == _IGREJA,
                    CelulaMembro.celula_id == turn.cell_id, CelulaMembro.pessoa_id == turn.actor_id,
                    CelulaMembro.ativo.is_(True)).values(ativo=False)
            assert session.execute(statement).rowcount == 1
    if revocation == 'actor_relink':
        # An ordinary SIM after loss of identity can take the public fallback.
        # Only its providers are faked; resolver/dispatcher remain unchanged.
        monkeypatch.setattr(worker_module, '_run_active_tier_a_turn', turn.original_active_tier_a_turn)
        usage = LLMUsage(modelo='synthetic', tokens_in=2, tokens_out=1, custo=0.0001)
        def no_action(_self, system, user, *, choices, **_kwargs):
            assert _NAME not in system and _NAME not in user and 'nenhuma' in choices
            return TypedChoiceResult('nenhuma', usage)
        def safe_reply(_self, system, user, **_kwargs):
            assert _NAME not in system and _NAME not in user
            return TypedLLMResult(False, 'Resposta sintética segura.', usage)
        monkeypatch.setattr(LLMClient, 'generate_typed', no_action)
        monkeypatch.setattr(LLMClient, 'complete_typed', safe_reply)
    confirmation = presence._http_enqueue(turn, 'VISITOR-PG-REVOKED-SIM', 'SIM')
    turn.http_worker.handle_envelope(confirmation)
    _no_effect(turn)
    assert presence._rows(turn, AgentActionProposal)[0].state != 'executada'
    # Only the relinked public SIM may produce synthetic provider usage.
    _private_egress(turn, allow_usage=revocation == 'actor_relink')
    assert turn.visitor_provider_calls == []


def test_visitor_pg_foreign_meeting_denied_by_real_service_and_confirmation(visitor_http_turn):
    turn = visitor_http_turn
    proposal, _ = _pending(turn)
    tenant, person, cell, meeting = (uuid.UUID(int=n) for n in range(970, 974))
    _seed_igreja_with_connection(turn.factory, igreja_id=tenant, instance='visitor-foreign-synthetic')
    with turn.factory.begin() as session:
        session.add(Pessoa(id=person, igreja_id=tenant, nome='Outro Sintético', telefone='5500000000002'))
        session.flush()
        session.add(Celula(id=cell, igreja_id=tenant, nome='Outra Célula Sintética', lider_id=person,
            cobertura_espiritual='Cobertura sintética', ativo=True))
        session.flush()
        session.add(CelulaReuniao(id=meeting, igreja_id=tenant, celula_id=cell,
            data=dt.date(2030, 1, 1), hora='20:00', status='planejada'))
    with turn.factory() as session:
        request = turn.http_outcomes[0]
        worker_module._scope_agent_execution_session(session, request, dedicated=False)
        context = resolve_whatsapp_privilege_context(session, igreja_id=_IGREJA,
            conversation_id=turn.conversation_id, inbound_message_id=request.inbound_message_id)
        assert type(context) is PrivilegeContext and context.pessoa_id == turn.actor_id
        catalog, mapping = build_catalog(session, context)
        targets = [target for target in mapping.values() if target.code == _ACTION]
        assert len(targets) == 1 and dict(targets[0].arguments) == {'reuniao_id': str(turn.meeting_id)}
        assert all(marker not in repr(catalog) + repr(mapping) for marker in (
            'Outro Sintético', str(turn.target_id), str(tenant), str(person), str(cell), str(meeting)))
    with turn.factory() as session:
        with pytest.raises(HTTPException) as error:
            register_own_visitor_expectation(session, _member(turn), reuniao_id=meeting,
                nome_visitante=_NAME, expected_actor_pessoa_id=turn.actor_id)
        assert error.value.status_code == 404
        session.rollback()
        with pytest.raises(HTTPException) as error:
            register_own_visitor_expectation(session, _member(turn), reuniao_id=turn.meeting_id,
                nome_visitante=_NAME, expected_actor_pessoa_id=turn.target_id)
        assert error.value.status_code == 403
        session.rollback()
    with turn.factory.begin() as session:
        stored = session.get(AgentActionProposal, proposal.id)
        stored.target_id = meeting
        stored.arguments_json = {'reuniao_id': str(meeting), 'nome_visitante': _NAME}
    with pytest.raises(ProposalContractError, match='^proposta persistida divergente$'):
        turn.http_worker.handle_envelope(presence._http_enqueue(turn, 'VISITOR-PG-FOREIGN-SIM', 'SIM'))
    _no_effect(turn)
    assert presence._rows(turn, AgentActionProposal)[0].state != 'executada'
    with turn.factory() as session:
        assert session.execute(select(func.count()).select_from(CelulaExpectativaVisitante).where(
            CelulaExpectativaVisitante.igreja_id == tenant)).scalar_one() == 0
    _private_egress(turn)
    assert turn.visitor_provider_calls == []


def test_visitor_http_pg_passed_before_offer_has_no_proposal(visitor_http_turn):
    turn = visitor_http_turn
    with turn.factory() as session:
        meeting = session.get(CelulaReuniao, turn.meeting_id)
        assert not schedule.meeting_has_passed(data=meeting.data, hora=meeting.hora, now=turn.own_clock[0])
    turn.own_clock[0] = dt.datetime(2030, 1, 1, 23, 1, tzinfo=dt.timezone.utc)
    turn.http_worker.handle_envelope(presence._http_enqueue(turn, 'VISITOR-PG-PAST-REQUEST', _COMMAND))
    assert presence._rows(turn, AgentActionProposal) == []
    _no_effect(turn)
    _private_egress(turn)
    assert turn.visitor_provider_calls == []


def test_visitor_http_pg_e4_equal_meeting_start_allows_confirmation(visitor_http_turn):
    turn = visitor_http_turn
    proposal, _ = _pending(turn)
    turn.own_clock[0] = dt.datetime(2030, 1, 1, 23, 0, tzinfo=dt.timezone.utc)
    turn.http_worker.handle_envelope(presence._http_enqueue(turn, 'VISITOR-PG-E4-SIM', 'SIM'))
    _confirmed(turn, proposal)
    assert turn.visitor_provider_calls == []


def test_visitor_http_pg_before_commit_failure_rolls_back_and_same_sim_recovers(visitor_http_turn):
    turn = visitor_http_turn
    proposal, _ = _pending(turn)
    confirmation = presence._http_enqueue(turn, 'VISITOR-PG-COMMIT-SIM', 'SIM')
    intercepted = []
    def fail_before_commit(session):
        if session.get_bind() is not turn.engine or session.in_nested_transaction():
            return
        with session.no_autoflush:
            effects = session.execute(select(func.count()).select_from(CelulaExpectativaVisitante).where(
                CelulaExpectativaVisitante.igreja_id == _IGREJA,
                CelulaExpectativaVisitante.reuniao_id == turn.meeting_id,
                CelulaExpectativaVisitante.pessoa_id == turn.actor_id)).scalar_one()
            receipts = session.execute(select(func.count()).select_from(AgentActionReceipt).where(
                AgentActionReceipt.igreja_id == _IGREJA, AgentActionReceipt.proposal_id == proposal.id)).scalar_one()
        if effects == receipts == 1:
            intercepted.append(True)
            raise RuntimeError('SYNTHETIC_VISITOR_BEFORE_COMMIT')
    event.listen(turn.factory.class_, 'before_commit', fail_before_commit)
    try:
        with pytest.raises(RuntimeError, match='^SYNTHETIC_VISITOR_BEFORE_COMMIT$'):
            turn.http_worker.handle_envelope(confirmation)
    finally:
        event.remove(turn.factory.class_, 'before_commit', fail_before_commit)
    assert intercepted == [True] and turn.engine.pool.checkedout() == 0
    _no_effect(turn)
    assert presence._rows(turn, AgentActionProposal)[0].state == 'pendente'
    assert len(turn.http_evolution.calls) == 1
    assert turn.http_worker.handle_envelope(confirmation) is worker_module.IngestionResult.DUPLICATE
    _confirmed(turn, proposal)
    assert len([call for call in turn.http_evolution.calls if 'Comprovante:' in call[2]]) == 1
    # BEFORE COMMIT only, never an assertion about ambiguous driver/network outcomes.


def test_visitor_http_pg_two_sim_workers_two_physical_pids_one_effect_and_receipt(visitor_http_turn):
    turn = visitor_http_turn
    proposal, _ = _pending(turn)
    envelopes = [presence._http_enqueue(turn, f'VISITOR-PG-DUAL-SIM-{n}', 'SIM') for n in (1, 2)]
    ingestion_gate, runner_gate = Barrier(2, timeout=8), Barrier(2, timeout=8)
    observation_lock = Lock()
    ingestion_pids, runner_pids, runner_threads = {}, {}, set()
    prefix = 'VISITOR-PG-DUAL'
    def observe_transaction(_session, _transaction, connection):
        name = current_thread().name
        if connection.engine is not turn.engine or not name.startswith(prefix):
            return
        with observation_lock:
            if name in runner_threads and name not in runner_pids:
                # Passive observation at the first real privileged transaction.
                runner_pids[name] = connection.connection.driver_connection.get_backend_pid()
        connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '8s'")
        with observation_lock:
            first = name not in ingestion_pids
            if first:
                ingestion_pids[name] = connection.connection.driver_connection.get_backend_pid()
        if first:
            ingestion_gate.wait(timeout=8)
    def real_runner(factory, outcome, ownership_guard):
        runner_gate.wait(timeout=8)
        with observation_lock:
            runner_threads.add(current_thread().name)
        return worker_module.run_agent_for_message(factory, outcome, ownership_guard,
            evolution_client=turn.http_evolution)
    workers = [worker_module.QueueWorker(queue=turn.http_queue, session_factory=turn.factory,
        agent_runner=real_runner, media_resolver=None, worker_id=f'VISITOR-PG-{n}',
        heartbeat_publisher=lambda *_args: None) for n in (1, 2)]
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix=prefix)
    event.listen(turn.factory.class_, 'after_begin', observe_transaction)
    try:
        futures = [pool.submit(worker.handle_envelope, envelope) for worker, envelope in zip(workers, envelopes)]
        results = [future.result(timeout=25) for future in futures]
    finally:
        ingestion_gate.abort()
        runner_gate.abort()
        try:
            pool.shutdown(wait=True, cancel_futures=True)
        finally:
            event.remove(turn.factory.class_, 'after_begin', observe_transaction)
    assert results == [worker_module.IngestionResult.REGISTERED] * 2
    assert len(ingestion_pids) == len(set(ingestion_pids.values())) == 2
    assert set(runner_pids) == runner_threads and len(set(runner_pids.values())) == 2
    assert turn.engine.pool.checkedout() == 0
    _, receipt = _confirmed(turn, proposal)
    sims = [row for row in presence._rows(turn, presence.Message)
            if row.provider_message_id in {'VISITOR-PG-DUAL-SIM-1', 'VISITOR-PG-DUAL-SIM-2'}]
    assert len(sims) == 2 and all(row.direcao == 'in' for row in sims)
    assert receipt.confirmation_message_id in {row.id for row in sims}
    assert len([call for call in turn.http_evolution.calls if 'Comprovante:' in call[2]]) == 1
    assert turn.visitor_provider_calls == []
    # Future.result propagates genuine errors. No forced 23505, SQL/lock mock,
    # sleep, polling, or requirement on the second confirmation's extra text.


def test_visitor_pg_both_human_endpoints_allow_multiple_same_names_and_optional_note(own_member_turn):
    turn = own_member_turn
    with turn.factory.begin() as session:
        session.get(CelulaReuniao, turn.meeting_id).data = dt.date(2029, 12, 30)
    payload = RegisterExpectativaRequest(nomeVisitante=_NAME, observacaoOracao='Nota sintética privada')
    outputs = []
    for endpoint in (indicate_my_visitor, register_expectativa_visitante):
        with turn.factory() as session:
            outputs.append(endpoint(str(turn.meeting_id), payload, db=session, current_user=_member(turn)))
    rows = presence._rows(turn, CelulaExpectativaVisitante)
    assert len(rows) == 2 and len({row.id for row in rows}) == 2
    assert len(outputs) == 2
    assert all(row.nome_visitante == _NAME and row.observacao_oracao == 'Nota sintética privada'
               and row.pessoa_id == turn.actor_id for row in rows)
    assert presence._rows(turn, AgentActionProposal) == presence._rows(turn, AgentActionReceipt) == []
    assert presence._rows(turn, CelulaPresenca) == []
    # Direct endpoint functions prove domain/DTO compatibility, not HTTP 201/auth.
