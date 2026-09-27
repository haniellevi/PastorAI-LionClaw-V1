"""Independent V1a contract through the real worker, fake providers and local PG."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import AgentActionProposal, AgentActionReceipt, CelulaReuniao, ConsentRecord, Conversation
from app.domain.cell_report_snapshot import validate_cell_report_snapshot_v2
from app.services import cell_report_whatsapp
from app.services.llm import LLMClient
from app.workers import queue_worker as worker_module
from tests.test_agent_privileged_turn_pg import (  # noqa: F401 - fixtures
    _ClassifiedEvolution, _IGREJA, _TERM, _inbound, _rows, msg_engine_fx,
    rls_database_url, s3_turn,
)

pytestmark = pytest.mark.rls_integration
_REPORT = 'Relatório da célula: presentes: 10; visitantes: 2; decisões: 1; oferta: 30,00'


@pytest.fixture
def report_turn(s3_turn, monkeypatch):
    monkeypatch.setattr(cell_report_whatsapp, 'CELL_REPORT_APPROVED_RELEASE_ID', 'synthetic-approved-v1a')
    monkeypatch.setenv('CELL_REPORT_ENABLED_IGREJA_IDS', str(_IGREJA))
    with s3_turn.factory.begin() as session:
        meeting = session.get(CelulaReuniao, s3_turn.meeting_id)
        meeting.data = dt.date.today() - dt.timedelta(days=1)
        meeting.hora = '19:00'
    def unexpected_llm(*_args, **_kwargs):
        pytest.fail('A complete numeric report must use the deterministic path')
    monkeypatch.setattr(LLMClient, 'generate_typed', unexpected_llm)
    return s3_turn


def _run(turn, provider_id, text, evolution):
    outcome = _inbound(turn, provider_id, text)
    disposition = worker_module.run_agent_for_message(turn.factory, outcome, evolution_client=evolution)
    assert disposition is worker_module.AgentRunDisposition.COMPLETED
    return outcome


def _snapshot(turn):
    with turn.factory() as session:
        meeting = session.get(CelulaReuniao, turn.meeting_id)
        return meeting.relatorio_status, meeting.relatorio_snapshot


class _CommittedReceiptEvolution(_ClassifiedEvolution):
    def __init__(self, turn):
        super().__init__()
        self.turn = turn
        self.committed_receipts = 0

    def send_text_classificado(self, instance, telefone, texto):
        if 'Comprovante:' in texto:
            # A separate transaction must observe the effect BEFORE provider I/O.
            assert _snapshot(self.turn)[0] == 'enviado'
            assert len(_rows(self.turn, AgentActionReceipt)) == 1
            self.committed_receipts += 1
        return super().send_text_classificado(instance, telefone, texto)


def test_v1a_summary_then_new_sim_commits_report_and_receipt_once(report_turn):
    turn = report_turn
    evolution = _CommittedReceiptEvolution(turn)
    request = _run(turn, 'V1A-REPORT', _REPORT, evolution)
    proposals = _rows(turn, AgentActionProposal)
    assert len(proposals) == 1
    assert proposals[0].action == 'enviar_relatorio_celula'
    assert proposals[0].state == 'pendente'
    assert proposals[0].delivered_at is not None
    assert _snapshot(turn)[0] == 'pendente'
    assert _rows(turn, AgentActionReceipt) == []
    assert len(evolution.calls) == 1
    assert '10' in evolution.calls[0][2] and '30,00' in evolution.calls[0][2]

    confirmation = _run(turn, 'V1A-SIM', 'SIM', evolution)
    state, raw = _snapshot(turn)
    assert state == 'enviado'
    report = validate_cell_report_snapshot_v2(raw)
    assert (report.totals.presentes, report.totals.visitantes, report.totals.decisoes) == (10, 2, 1)
    assert report.oferta_valor == Decimal('30.00')
    assert report.observacoes is None
    assert raw['presencas'] == raw['visitantes'] == raw['records'] == []
    assert len(_rows(turn, AgentActionReceipt)) == 1
    assert evolution.committed_receipts == 1
    assert 'Relatório confirmado.' in evolution.calls[-1][2]
    for outcome in (request, confirmation, confirmation):
        worker_module.run_agent_for_message(turn.factory, outcome, evolution_client=evolution)
    assert len(_rows(turn, AgentActionReceipt)) == 1
    assert len(evolution.calls) == 2
    from app.db.rls import set_tenant_context_for_igreja
    from app.deps import CurrentUser
    from app.routers import cell_meetings
    actor = CurrentUser(app_user_id=str(turn.app_user_id), clerk_user_id='clerk-s3-synthetic',
        igreja_id=str(_IGREJA), email='synthetic@example.test', nome='Operador Sintético',
        roles=frozenset({'pastor'}))
    with turn.factory() as session:
        set_tenant_context_for_igreja(session, str(_IGREJA))
        panel = cell_meetings.get_report(str(turn.meeting_id), session, actor)
        assert panel.relatorio_status == 'enviado'
        assert (panel.totals.presentes, panel.totals.visitantes, panel.totals.decisoes) == (10, 2, 1)
        assert panel.oferta_valor == 30.0
        assert panel.presencas == panel.visitantes == panel.records == []


def test_v1a_correction_replaces_delivered_summary_before_confirmation(report_turn):
    turn = report_turn
    evolution = _CommittedReceiptEvolution(turn)
    _run(turn, 'V1A-CORRECTION-REPORT', _REPORT, evolution)
    original = _rows(turn, AgentActionProposal)[0].id
    _run(turn, 'V1A-CORRECTION', 'Correção: presentes: 12; oferta: 35,50', evolution)
    pending = [p for p in _rows(turn, AgentActionProposal) if p.state == 'pendente']
    assert len(pending) == 1 and pending[0].id != original
    assert _snapshot(turn)[0] == 'pendente'
    _run(turn, 'V1A-CORRECTED-SIM', 'SIM', evolution)
    report = validate_cell_report_snapshot_v2(_snapshot(turn)[1])
    assert (report.totals.presentes, report.totals.visitantes, report.totals.decisoes) == (12, 2, 1)
    assert report.oferta_valor == Decimal('35.50')
    assert len(_rows(turn, AgentActionReceipt)) == 1


@pytest.mark.parametrize('revocation', ('term', 'meeting_cancelled', 'release'))
def test_v1a_authorization_revoked_before_sim_prevents_effect(report_turn, monkeypatch, revocation):
    turn = report_turn
    evolution = _ClassifiedEvolution()
    _run(turn, 'V1A-REVOKE-REPORT', _REPORT, evolution)
    assert _rows(turn, AgentActionProposal)[0].state == 'pendente'
    with turn.factory.begin() as session:
        if revocation == 'term':
            actor = session.get(Conversation, turn.conversation_id).pessoa_id
            session.add(ConsentRecord(igreja_id=_IGREJA, pessoa_id=actor, termo_versao='optout:' + _TERM, aceite_em=dt.datetime.now(dt.timezone.utc)))
        elif revocation == 'meeting_cancelled':
            session.get(CelulaReuniao, turn.meeting_id).status = 'cancelada'
    if revocation == 'release':
        monkeypatch.setattr(cell_report_whatsapp, 'CELL_REPORT_APPROVED_RELEASE_ID', None)
    _run(turn, 'V1A-REVOKED-SIM', 'SIM', evolution)
    assert _snapshot(turn)[0] == 'pendente'
    assert _rows(turn, AgentActionReceipt) == []


def test_v1a_sim_after_ten_minute_expiry_cannot_commit(report_turn):
    turn = report_turn
    evolution = _ClassifiedEvolution()
    _run(turn, 'V1A-TTL-REPORT', _REPORT, evolution)
    with turn.factory.begin() as session:
        proposal = session.execute(select(AgentActionProposal).where(AgentActionProposal.igreja_id == _IGREJA)).scalar_one()
        proposal.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
    _run(turn, 'V1A-TTL-SIM', 'SIM', evolution)
    assert _snapshot(turn)[0] == 'pendente'
    assert _rows(turn, AgentActionReceipt) == []
    assert _rows(turn, AgentActionProposal)[0].state == 'expirada'


@pytest.mark.parametrize('replace_digest', (False, True))
def test_v1a_changed_draft_cannot_execute_different_values_than_delivered_summary(report_turn, replace_digest):
    import hashlib
    import json
    from app.db.models import CellReportDraft
    turn = report_turn
    evolution = _ClassifiedEvolution()
    _run(turn, 'V1A-HASH-REPORT', _REPORT, evolution)
    with turn.factory.begin() as session:
        draft = session.execute(select(CellReportDraft).where(CellReportDraft.igreja_id == _IGREJA)).scalar_one()
        changed = dict(draft.candidate_json)
        changed['presentes'] = 99
        draft.candidate_json = changed
        if replace_digest:
            draft.candidate_sha256 = hashlib.sha256(json.dumps(changed, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    _run(turn, 'V1A-HASH-SIM', 'SIM', evolution)
    assert _snapshot(turn)[0] == 'pendente'
    assert _rows(turn, AgentActionReceipt) == []


def test_v1a_two_simultaneous_confirmations_have_one_domain_effect(report_turn, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from app.services.agent_privilege_routing import ChoiceSelection
    turn = report_turn
    evolution = _ClassifiedEvolution()
    _run(turn, 'V1A-RACE-REPORT', _REPORT, evolution)
    first = _inbound(turn, 'V1A-RACE-SIM-1', 'SIM')
    second = _inbound(turn, 'V1A-RACE-SIM-2', 'SIM')
    # The losing inbound may reach the closed router after no proposal remains.
    monkeypatch.setattr(LLMClient, 'generate_typed', lambda *_a, **_kw: ChoiceSelection('handoff'))
    barrier = threading.Barrier(2)
    def confirm(outcome):
        barrier.wait(timeout=5)
        return worker_module.run_agent_for_message(turn.factory, outcome, evolution_client=evolution)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(confirm, outcome) for outcome in (first, second)]
        for future in futures:
            assert future.result(timeout=20) is worker_module.AgentRunDisposition.COMPLETED
    assert _snapshot(turn)[0] == 'enviado'
    assert len(_rows(turn, AgentActionReceipt)) == 1
    assert len([p for p in _rows(turn, AgentActionProposal) if p.state == 'executada']) == 1
    assert sum('Comprovante:' in text for _, _, text in evolution.calls) <= 1


def test_v1a_partial_correction_cannot_revalidate_a_corrupted_draft(report_turn):
    from app.db.models import CellReportDraft
    turn = report_turn
    evolution = _ClassifiedEvolution()
    _run(turn, 'V1A-CORRUPT-REPORT', _REPORT, evolution)
    with turn.factory.begin() as session:
        draft = session.execute(select(CellReportDraft).where(CellReportDraft.igreja_id == _IGREJA)).scalar_one()
        draft.candidate_json = dict(draft.candidate_json, presentes=99)
    _run(turn, 'V1A-CORRUPT-CORRECTION', 'Correção: oferta: 35,50', evolution)
    assert len(_rows(turn, AgentActionProposal)) == 1
    assert len(evolution.calls) == 1
    draft = _rows(turn, CellReportDraft)[0]
    assert draft.state == 'cancelado' and draft.candidate_json is None
    worker_module.run_agent_for_message(turn.factory, _inbound(turn, 'V1A-CORRUPT-SIM', 'SIM'), evolution_client=evolution)
    assert _snapshot(turn)[0] == 'pendente'
    assert _rows(turn, AgentActionReceipt) == []


def test_v1a_env_alone_is_inert_without_any_v1a_table(report_turn, monkeypatch):
    from sqlalchemy import event
    from app.services.agent_privilege_routing import ChoiceSelection
    turn = report_turn
    tables = ('cell_report_ai_reservations', 'cell_report_ai_daily_budgets', 'cell_report_reminders', 'cell_report_reminder_preferences', 'cell_report_drafts')
    with turn.engine.begin() as connection:
        for name in tables:
            connection.exec_driver_sql(f'DROP TABLE {name} CASCADE')
    statements = []
    def record(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    event.listen(turn.engine, 'before_cursor_execute', record)
    monkeypatch.setattr(cell_report_whatsapp, 'CELL_REPORT_APPROVED_RELEASE_ID', None)
    monkeypatch.setattr(LLMClient, 'generate_typed', lambda *_a, **_kw: ChoiceSelection('handoff'))
    try:
        evolution = _ClassifiedEvolution()
        _run(turn, 'V1A-INERT-ENV', _REPORT, evolution)
        assert _snapshot(turn)[0] == 'pendente'
        assert _rows(turn, AgentActionProposal) == []
        assert _rows(turn, AgentActionReceipt) == []
        assert evolution.calls == []
        assert not any('cell_report_' in statement.lower() for statement in statements)
    finally:
        event.remove(turn.engine, 'before_cursor_execute', record)


def test_v1a_missing_values_stay_null_until_explicitly_supplied(report_turn):
    from app.db.models import CellReportDraft
    turn = report_turn
    provider = _CommittedReceiptEvolution(turn)
    _run(turn, 'V1A-PARTIAL-1', 'Relatório: presentes: 10', provider)
    draft = _rows(turn, CellReportDraft)[0]
    assert draft.state == 'coletando'
    assert draft.candidate_json['presentes'] == 10
    assert draft.candidate_json['visitantes'] is None
    assert draft.candidate_json['decisoes'] is None
    assert draft.candidate_json['oferta_centavos'] is None
    assert _rows(turn, AgentActionProposal) == []
    _run(turn, 'V1A-PARTIAL-2', 'visitantes: 2; decisões: 0; oferta: 0,00', provider)
    assert len(_rows(turn, AgentActionProposal)) == 1
    assert _snapshot(turn)[0] == 'pendente'
    _run(turn, 'V1A-PARTIAL-SIM', 'SIM', provider)
    report = validate_cell_report_snapshot_v2(_snapshot(turn)[1])
    assert (report.totals.presentes, report.totals.visitantes, report.totals.decisoes) == (10, 2, 0)
    assert report.oferta_valor == Decimal('0.00')


@pytest.mark.parametrize('revoke', ('release', 'meeting'))
def test_v1a_summary_retry_cannot_send_after_authority_is_revoked(report_turn, monkeypatch, revoke):
    turn = report_turn
    provider = _ClassifiedEvolution('falhou_retentavel', 'aceito')
    request = _inbound(turn, 'V1A-SUMMARY-RETRY', _REPORT)
    with pytest.raises(worker_module.AgentReplyRetryable):
        worker_module.run_agent_for_message(turn.factory, request, evolution_client=provider)
    assert len(provider.calls) == 1
    if revoke == 'release':
        monkeypatch.setattr(cell_report_whatsapp, 'CELL_REPORT_APPROVED_RELEASE_ID', None)
    else:
        with turn.factory.begin() as session:
            session.get(CelulaReuniao, turn.meeting_id).status = 'cancelada'
    worker_module.run_agent_for_message(turn.factory, request, evolution_client=provider)
    assert len(provider.calls) == 1
    assert _rows(turn, AgentActionProposal)[0].state == 'cancelada'
    assert _rows(turn, AgentActionReceipt) == []
    assert _snapshot(turn)[0] == 'pendente'


def test_report_and_receipt_roll_back_together_before_any_success_message(report_turn):
    from sqlalchemy import event
    turn = report_turn
    provider = _CommittedReceiptEvolution(turn)
    _run(turn, 'V1A-ROLLBACK-REPORT', _REPORT, provider)
    confirmation = _inbound(turn, 'V1A-ROLLBACK-SIM', 'SIM')
    intercepted = []

    def fail_receipt_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('INSERT INTO') and 'agent_action_receipts' in statement:
            intercepted.append(True)
            raise RuntimeError('synthetic receipt persistence failure')

    event.listen(turn.engine, 'before_cursor_execute', fail_receipt_insert)
    try:
        try:
            worker_module.run_agent_for_message(turn.factory, confirmation, evolution_client=provider)
        except RuntimeError as error:
            assert str(error) == 'synthetic receipt persistence failure'
    finally:
        event.remove(turn.engine, 'before_cursor_execute', fail_receipt_insert)
    assert intercepted == [True]
    assert _snapshot(turn)[0] == 'pendente'
    assert _rows(turn, AgentActionReceipt) == []
    assert provider.committed_receipts == 0
    assert not any('Comprovante:' in call[2] for call in provider.calls)


def test_human_submit_and_whatsapp_sim_have_one_immutable_winner(report_turn):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    from app.db.rls import set_tenant_context_for_igreja
    from app.deps import CurrentUser
    from app.routers import cell_meetings
    turn = report_turn
    provider = _ClassifiedEvolution()
    _run(turn, 'V1A-HUMAN-RACE-REPORT', _REPORT, provider)
    confirmation = _inbound(turn, 'V1A-HUMAN-RACE-SIM', 'SIM')
    actor = CurrentUser(app_user_id=str(turn.app_user_id), clerk_user_id='clerk-s3-synthetic',
        igreja_id=str(_IGREJA), email='synthetic@example.test', nome='Operador Sintético',
        roles=frozenset({'pastor'}))
    barrier = Barrier(2)

    def human_submit():
        barrier.wait(timeout=5)
        with turn.factory() as session:
            set_tenant_context_for_igreja(session, str(_IGREJA))
            try:
                cell_meetings.submit_report(str(turn.meeting_id), session, actor)
                return session.get(CelulaReuniao, turn.meeting_id).relatorio_snapshot
            except HTTPException as error:
                assert error.status_code == 409
                session.rollback()
                return None

    def whatsapp_submit():
        barrier.wait(timeout=5)
        return worker_module.run_agent_for_message(turn.factory, confirmation, evolution_client=provider)

    with ThreadPoolExecutor(max_workers=2) as pool:
        web = pool.submit(human_submit)
        whatsapp = pool.submit(whatsapp_submit)
        human_snapshot = web.result(timeout=20)
        assert whatsapp.result(timeout=20) is worker_module.AgentRunDisposition.COMPLETED
    status, snapshot = _snapshot(turn)
    assert status == 'enviado'
    receipts = _rows(turn, AgentActionReceipt)
    if human_snapshot is not None:
        assert receipts == []
        assert snapshot == human_snapshot
    else:
        assert len(receipts) == 1
        assert validate_cell_report_snapshot_v2(snapshot).totals.presentes == 10


@pytest.mark.parametrize('signal', ('handoff', 'optout'))
def test_new_report_preserves_active_tier_a_handoff_gate(report_turn, monkeypatch, signal):
    from types import SimpleNamespace
    from app.db.models import CellReportDraft
    from app.services import semantic_triage
    turn = report_turn
    calls = []
    optout_calls = []
    monkeypatch.setattr(semantic_triage, 'tier_a_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(worker_module, '_tier_a_effective_settings', lambda *_: SimpleNamespace())

    def classified_handoff(*args, **kwargs):
        assert turn.engine.pool.checkedout() == 0
        calls.append(True)
        return SimpleNamespace(handoff=signal == 'handoff', pede_optout=signal == 'optout')

    monkeypatch.setattr(worker_module, '_run_tier_a_batch', classified_handoff)
    def optout_confirmation(*args, **kwargs):
        optout_calls.append(True)
        return worker_module.AgentRunDisposition.COMPLETED
    monkeypatch.setattr(worker_module, '_run_active_tier_a_turn', optout_confirmation)
    provider = _ClassifiedEvolution()
    _run(turn, 'V1A-TIER-A-HANDOFF', _REPORT, provider)
    assert calls == [True]
    assert provider.calls == []
    assert _rows(turn, CellReportDraft) == []
    assert _rows(turn, AgentActionProposal) == []
    assert _snapshot(turn)[0] == 'pendente'
    if signal == 'handoff':
        with turn.factory() as session:
            assert session.get(Conversation, turn.conversation_id).estado == 'humano'
    else:
        assert optout_calls == [True]


def test_report_confirmation_remains_deterministic_before_tier_a(report_turn, monkeypatch):
    from app.services import semantic_triage
    turn = report_turn
    _run(turn, 'V1A-LOCAL-CONFIRM-REPORT', _REPORT, _ClassifiedEvolution())
    monkeypatch.setattr(semantic_triage, 'tier_a_enabled_from_environment', lambda _tenant: True)
    def must_not_classify(*args, **kwargs):
        pytest.fail('A pending confirmation must be resolved before Tier A')
    monkeypatch.setattr(worker_module, '_run_tier_a_batch', must_not_classify)
    _run(turn, 'V1A-LOCAL-CONFIRM-SIM', 'SIM', _CommittedReceiptEvolution(turn))
    assert _snapshot(turn)[0] == 'enviado'
    assert len(_rows(turn, AgentActionReceipt)) == 1


def test_human_submit_preserves_terminal_status_in_the_frozen_read_model(report_turn):
    from app.db.rls import set_tenant_context_for_igreja
    from app.deps import CurrentUser
    from app.routers import cell_meetings
    turn = report_turn
    actor = CurrentUser(app_user_id=str(turn.app_user_id), clerk_user_id='clerk-s3-synthetic',
        igreja_id=str(_IGREJA), email='synthetic@example.test', nome='Operador Sintético',
        roles=frozenset({'pastor'}))
    with turn.factory.begin() as session:
        meeting = session.get(CelulaReuniao, turn.meeting_id)
        meeting.oferta_valor = Decimal('25.00')
        meeting.observacoes = 'Observação sintética do painel'
    with turn.factory() as session:
        set_tenant_context_for_igreja(session, str(_IGREJA))
        submitted = cell_meetings.submit_report(str(turn.meeting_id), session, actor)
        assert submitted.relatorio_status == 'enviado'
    with turn.factory() as session:
        set_tenant_context_for_igreja(session, str(_IGREJA))
        report = cell_meetings.get_report(str(turn.meeting_id), session, actor)
        assert report.relatorio_status == 'enviado'
        assert report.oferta_valor == 25.0
        assert report.observacoes == 'Observação sintética do painel'


@pytest.mark.parametrize('phase', ('stage', 'retry', 'execute'))
def test_v1a_worker_does_not_hold_draft_ahead_of_budget_meeting_lock(report_turn, phase):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from sqlalchemy import event, text
    from sqlalchemy.exc import OperationalError
    from app.db.models import CellReportDraft
    from app.db.rls import set_tenant_context_for_igreja
    turn = report_turn
    if phase == 'retry':
        request = _inbound(turn, 'V1A-LOCK-RETRY', _REPORT)
        with pytest.raises(worker_module.AgentReplyRetryable):
            worker_module.run_agent_for_message(turn.factory, request,
                evolution_client=_ClassifiedEvolution('falhou_retentavel'))
    else:
        _run(turn, 'V1A-LOCK-INITIAL', 'Relatório: presentes: 10' if phase == 'stage' else _REPORT,
            _ClassifiedEvolution())
        request = _inbound(turn, 'V1A-LOCK-NEXT', 'visitantes: 2' if phase == 'stage' else 'SIM')
    draft_id = _rows(turn, CellReportDraft)[0].id
    at_meeting = Event()
    locking_error = None

    def observe_meeting(conn, cursor, statement, parameters, context, executemany):
        sql = statement.lower()
        if current_thread().name.startswith('v1a-lock-order') and 'celula_reuniao' in sql and 'for update' in sql:
            at_meeting.set()

    event.listen(turn.engine, 'before_cursor_execute', observe_meeting)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='v1a-lock-order') as pool:
            with turn.factory() as budget_session:
                set_tenant_context_for_igreja(budget_session, str(_IGREJA))
                budget_session.execute(text("SET LOCAL lock_timeout = '500ms'"))
                budget_session.execute(select(CelulaReuniao).where(
                    CelulaReuniao.id == turn.meeting_id).with_for_update()).scalar_one()
                worker = pool.submit(worker_module.run_agent_for_message, turn.factory, request,
                    evolution_client=_ClassifiedEvolution())
                assert at_meeting.wait(5)
                try:
                    cell_report_whatsapp.reserve_v1a_extraction_budget(budget_session,
                        igreja_id=_IGREJA, draft_id=draft_id, model='gpt-5.6-luna',
                        estimate_cost=lambda *_: Decimal('0.01'))
                except cell_report_whatsapp.CellReportWhatsappError:
                    assert phase != 'stage'  # Ready drafts correctly reject a new paid extraction.
                except OperationalError as error:
                    locking_error = error.orig.pgcode
                finally:
                    budget_session.rollback()
            assert worker.result(timeout=15) is worker_module.AgentRunDisposition.COMPLETED
    finally:
        event.remove(turn.engine, 'before_cursor_execute', observe_meeting)
    assert locking_error is None, f'Worker held Draft while waiting for Meeting: {locking_error}'
