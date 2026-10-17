"""G12 PR5: synthetic meeting-to-report lifecycle on disposable PostgreSQL."""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db.models import CelulaReuniao, Conversation, Pessoa
from app.services import cell_report_reminders as reminders, cell_report_whatsapp
from tests.test_cell_report_v1a_reminder_pg import (  # noqa: F401
    _NOW, _IGREJA, _TERM, _REPORT, _run, _rows, _v1a_outbox_rows,
    _ReminderTransport, _ClassifiedEvolution, reminder_turn, report_turn,
    s3_turn, msg_engine_fx, rls_database_url,
)

pytestmark = pytest.mark.rls_integration


@pytest.mark.parametrize('blocked', ('global', 'pilot', 's3', 'optout', 'handoff', 'refusal', 'access'))
def test_due_suppression_is_terminal_and_scoped_to_occurrence(reminder_turn, monkeypatch, blocked):
    from app.db.models import AppUser, CellReportReminderPreference
    turn = reminder_turn
    if blocked == 'global':
        monkeypatch.setenv('ALLOW_REAL_SENDS', 'false')
    elif blocked == 'pilot':
        monkeypatch.setenv('WHATSAPP_PILOTO_IGREJA_IDS', '')
    elif blocked == 's3':
        monkeypatch.setenv('AGENT_PRIVILEGE_ENABLED_IGREJA_IDS', '')
    else:
        with turn.factory.begin() as session:
            conversation = session.get(Conversation, turn.conversation_id)
            if blocked == 'optout':
                session.get(Pessoa, conversation.pessoa_id).optout = True
            elif blocked == 'handoff':
                conversation.estado = 'humano'
            elif blocked == 'refusal':
                session.add(CellReportReminderPreference(igreja_id=_IGREJA,
                    pessoa_id=conversation.pessoa_id, disabled_at=_NOW, updated_at=_NOW))
            elif blocked == 'access':
                session.get(AppUser, turn.app_user_id).status = 'inativo'
    get_settings.cache_clear()
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 1
    rows = _v1a_outbox_rows(turn)
    assert len(rows) == 1 and rows[0].state == 'cancelado'
    expected = {'global': 'gate_fechado', 'pilot': 'gate_fechado', 's3': 'gate_fechado',
        'optout': 'pessoa_revogada', 'handoff': 'atendimento_humano',
        'refusal': 'lembretes_recusados', 'access': 'lideranca_revogada'}
    assert rows[0].terminal_reason == expected[blocked]
    assert rows[0].transport_started_at is None and rows[0].sent_at is None
    provider = _ClassifiedEvolution()
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 0
    reminders.dispatch_cell_report_reminders(turn.factory, provider, worker_id='g12-suppressed', now=_NOW)
    assert provider.calls == []
    # Restoring the source eligibility cannot resurrect this terminal occurrence.
    if blocked == 'optout':
        with turn.factory.begin() as session:
            session.get(Pessoa, rows[0].pessoa_id).optout = False
        assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 0


@pytest.mark.parametrize('outside', ('list', 'release', 'malformed_list'))
def test_outside_v1a_scope_creates_no_row(reminder_turn, monkeypatch, outside):
    if outside == 'list':
        monkeypatch.setenv('CELL_REPORT_ENABLED_IGREJA_IDS', '')
    elif outside == 'malformed_list':
        monkeypatch.setenv('CELL_REPORT_ENABLED_IGREJA_IDS', str(_IGREJA) + ',')
    else:
        monkeypatch.setattr(cell_report_whatsapp, 'CELL_REPORT_APPROVED_RELEASE_ID', None)
    monkeypatch.setenv('ALLOW_REAL_SENDS', 'false')
    get_settings.cache_clear()
    assert reminders.schedule_due_cell_report_reminders(reminder_turn.factory, now=_NOW) == 0
    assert _v1a_outbox_rows(reminder_turn) == []


def _panel_actor(turn):
    from app.deps import CurrentUser
    return CurrentUser(app_user_id=str(turn.app_user_id), clerk_user_id='clerk-s3-synthetic',
        igreja_id=str(_IGREJA), email='synthetic@example.test', nome='Operador Sintético',
        roles=frozenset({'pastor'}))


def _pending(turn):
    from app.db.rls import set_tenant_context_for_igreja
    from app.routers import cell_central
    with turn.factory() as session:
        set_tenant_context_for_igreja(session, str(_IGREJA))
        return cell_central.get_pending_reports(page=1, page_size=20,
            db=session, current_user=_panel_actor(turn))


def _submit(turn, channel, provider):
    from app.db.rls import set_tenant_context_for_igreja
    from app.routers import cell_meetings
    if channel == 'agent':
        _run(turn, 'G12-REPORT', _REPORT, provider)
        with turn.factory() as session:
            assert session.get(CelulaReuniao, turn.meeting_id).relatorio_status == 'pendente'
        _run(turn, 'G12-CONFIRM', 'SIM', provider)
    else:
        with turn.factory() as session:
            set_tenant_context_for_igreja(session, str(_IGREJA))
            cell_meetings.submit_report(str(turn.meeting_id), session, _panel_actor(turn))


@pytest.mark.parametrize('channel', ('agent', 'panel'))
def test_meeting_overdue_cron_reminder_report_and_central_closure(reminder_turn, monkeypatch, channel):
    from app.db.models import AgentActionProposal, AgentActionReceipt, Message
    from app.workers import cron_worker
    turn = reminder_turn
    assert _pending(turn).total == 1
    class Provider(_ReminderTransport):
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
    reminder_provider = Provider(turn)
    monkeypatch.setattr(cron_worker, 'EvolutionClient', lambda: reminder_provider)
    worker = cron_worker.CronWorker(session_factory=turn.factory)
    assert worker._run_cell_report_reminder_cycle(now=_NOW)[1:] == (1, 1)
    assert len(reminder_provider.calls) == 1
    assert _v1a_outbox_rows(turn)[0].state == 'enviado'
    reply_provider = _ClassifiedEvolution()
    _submit(turn, channel, reply_provider)
    with turn.factory() as session:
        meeting = session.get(CelulaReuniao, turn.meeting_id)
        assert meeting.relatorio_status == 'enviado' and meeting.relatorio_snapshot
        assert meeting.relatorio_enviado_em is not None
    if channel == 'agent':
        proposals = _rows(turn, AgentActionProposal)
        assert len(proposals) == 1 and proposals[0].state == 'executada'
        assert len(_rows(turn, AgentActionReceipt)) == 1
        messages = _rows(turn, Message)
        assert any(m.direcao == 'in' and m.texto == _REPORT for m in messages)
        assert any(m.direcao == 'out' and 'Comprovante:' in (m.texto or '')
            and m.agent_reply_state == 'ia' for m in messages)
        assert len(reply_provider.calls) == 2
    assert _pending(turn).total == 0
    assert worker._run_cell_report_reminder_cycle(now=_NOW + dt.timedelta(minutes=1))[1:] == (0, 0)
    assert len(_v1a_outbox_rows(turn)) == 1 and len(reminder_provider.calls) == 1


@pytest.mark.parametrize('channel', ('agent', 'panel'))
def test_report_committed_between_claim_and_transport_fences_reminder(reminder_turn, monkeypatch, channel):
    from app.services import notification_outbox
    turn = reminder_turn
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 1
    original_claim = notification_outbox._claim_next_notification
    reply_provider = _ClassifiedEvolution()
    def claim_then_submit(*args, **kwargs):
        claim = original_claim(*args, **kwargs)
        if claim is not None:
            _submit(turn, channel, reply_provider)
        return claim
    monkeypatch.setattr(notification_outbox, '_claim_next_notification', claim_then_submit)
    provider = _ClassifiedEvolution()
    reminders.dispatch_cell_report_reminders(turn.factory, provider, worker_id='g12-race', now=_NOW)
    assert provider.calls == []
    assert _v1a_outbox_rows(turn)[0].state == 'obsoleto'
    assert _pending(turn).total == 0
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 0


def test_replaced_leader_only_new_eligible_leader_receives_remaining_window(reminder_turn):
    from app.db.models import AppUser, Celula, ConsentRecord, UserRole
    turn = reminder_turn
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 1
    old = _v1a_outbox_rows(turn)[0]
    with turn.factory.begin() as session:
        user = AppUser(igreja_id=_IGREJA, pessoa_id=turn.target_id, nome='Novo líder sintético',
            email='new-leader@example.test', clerk_user_id='g12-new-leader', status='ativo')
        session.add(user)
        session.flush()
        session.add(UserRole(igreja_id=_IGREJA, user_id=user.id, papel='pastor'))
        session.add(ConsentRecord(igreja_id=_IGREJA, pessoa_id=turn.target_id,
            termo_versao=_TERM, aceite_em=_NOW - dt.timedelta(days=1)))
        meeting = session.get(CelulaReuniao, turn.meeting_id)
        session.get(Celula, meeting.celula_id).lider_id = turn.target_id
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW + dt.timedelta(minutes=1)) == 1
    provider = _ReminderTransport(turn)
    reminders.dispatch_cell_report_reminders(turn.factory, provider, worker_id='g12-new-leader',
        now=_NOW + dt.timedelta(minutes=1))
    rows = {r.pessoa_id: r for r in _v1a_outbox_rows(turn)}
    assert rows[old.pessoa_id].state == 'obsoleto'
    assert rows[old.pessoa_id].terminal_reason == 'lideranca_revogada'
    assert rows[turn.target_id].state == 'enviado'
    assert len(provider.calls) == 1 and provider.calls[0][1] == '00000000001'
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW + dt.timedelta(minutes=2)) == 0


def test_cancelled_meeting_cannot_transport_or_reschedule(reminder_turn):
    turn = reminder_turn
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 1
    with turn.factory.begin() as session:
        session.get(CelulaReuniao, turn.meeting_id).status = 'cancelada'
    provider = _ClassifiedEvolution()
    reminders.dispatch_cell_report_reminders(turn.factory, provider, worker_id='g12-cancelled', now=_NOW)
    assert provider.calls == []
    assert _v1a_outbox_rows(turn)[0].state == 'obsoleto'
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 0


def test_real_worker_refuses_report_without_ministerial_permission(reminder_turn):
    from sqlalchemy import delete
    from app.db.models import AgentActionProposal, AgentActionReceipt, Celula, UserRole
    turn = reminder_turn
    with turn.factory.begin() as session:
        session.execute(delete(UserRole).where(UserRole.igreja_id == _IGREJA,
            UserRole.user_id == turn.app_user_id))
        meeting = session.get(CelulaReuniao, turn.meeting_id)
        session.get(Celula, meeting.celula_id).lider_id = turn.target_id
    provider = _ClassifiedEvolution()
    _run(turn, 'G12-UNAUTHORIZED-REPORT', _REPORT, provider)
    _run(turn, 'G12-UNAUTHORIZED-CONFIRM', 'SIM', provider)
    assert all(p.state != 'executada' for p in _rows(turn, AgentActionProposal))
    assert _rows(turn, AgentActionReceipt) == []
    with turn.factory() as session:
        assert session.get(CelulaReuniao, turn.meeting_id).relatorio_status == 'pendente'
    assert _pending(turn).total == 1


@pytest.mark.parametrize('offset', (-dt.timedelta(hours=6), dt.timedelta(days=1)))
def test_suppression_only_records_due_meetings_inside_recovery_window(reminder_turn, monkeypatch, offset):
    monkeypatch.setenv('ALLOW_REAL_SENDS', 'false')
    get_settings.cache_clear()
    assert reminders.schedule_due_cell_report_reminders(reminder_turn.factory, now=_NOW + offset) == 0
    assert _v1a_outbox_rows(reminder_turn) == []


def test_scheduling_closed_gate_does_not_cancel_existing_pending_rows(reminder_turn, monkeypatch):
    turn = reminder_turn
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 1
    monkeypatch.setenv('ALLOW_REAL_SENDS', 'false')
    get_settings.cache_clear()
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 0
    assert _v1a_outbox_rows(turn)[0].state == 'pendente'


def test_two_schedulers_deduplicate_suppression_under_real_pg_locks(reminder_turn, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    turn = reminder_turn
    monkeypatch.setenv('ALLOW_REAL_SENDS', 'false')
    get_settings.cache_clear()
    barrier = Barrier(2)
    def schedule():
        barrier.wait(timeout=5)
        return reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(schedule) for _ in range(2)]
        assert sum(f.result(timeout=15) for f in futures) == 1
    rows = _v1a_outbox_rows(turn)
    assert len(rows) == 1 and rows[0].state == 'cancelado'


def test_suppression_leaves_other_church_meeting_and_outbox_untouched(reminder_turn, monkeypatch):
    import uuid
    from app.db.models import Celula, Igreja, NotificationOutbox
    turn = reminder_turn
    other = uuid.uuid4()
    person = uuid.uuid4()
    cell = uuid.uuid4()
    meeting_id = uuid.uuid4()
    with turn.factory.begin() as session:
        session.add(Igreja(id=other, nome='Outra Igreja Sintética'))
        session.add(Pessoa(id=person, igreja_id=other, nome='Outro Líder Sintético', telefone='5500000000099'))
        session.flush()
        session.add(Celula(id=cell, igreja_id=other, nome='Outra Célula', lider_id=person,
            cobertura_espiritual='Cobertura sintética', ativo=True))
        session.flush()
        session.add(CelulaReuniao(id=meeting_id, igreja_id=other, celula_id=cell,
            data=_NOW.date(), hora='10:00', status='planejada', relatorio_status='pendente'))
    monkeypatch.setenv('ALLOW_REAL_SENDS', 'false')
    get_settings.cache_clear()
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 1
    with turn.factory() as session:
        rows = session.execute(select(NotificationOutbox)).scalars().all()
        assert len(rows) == 1 and rows[0].igreja_id == _IGREJA
        assert session.get(CelulaReuniao, meeting_id).relatorio_status == 'pendente'


@pytest.mark.parametrize('closed_gate', (False, True))
def test_offline_connection_remains_schedulable_unless_gate_is_closed(reminder_turn, monkeypatch, closed_gate):
    from app.db.models import WhatsappConnection
    turn = reminder_turn
    with turn.factory.begin() as session:
        connection = session.execute(select(WhatsappConnection).where(
            WhatsappConnection.igreja_id == _IGREJA)).scalar_one()
        connection.status = 'offline'
    if closed_gate:
        monkeypatch.setenv('ALLOW_REAL_SENDS', 'false')
        get_settings.cache_clear()
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == int(closed_gate)
    rows = _v1a_outbox_rows(turn)
    if closed_gate:
        assert len(rows) == 1 and rows[0].state == 'cancelado'
        assert rows[0].terminal_reason == 'gate_fechado'
    else:
        assert rows == []
    with turn.factory.begin() as session:
        connection = session.execute(select(WhatsappConnection).where(
            WhatsappConnection.igreja_id == _IGREJA)).scalar_one()
        connection.status = 'online'
    assert reminders.schedule_due_cell_report_reminders(turn.factory,
        now=_NOW + dt.timedelta(minutes=1)) == int(not closed_gate)
    rows = _v1a_outbox_rows(turn)
    assert len(rows) == 1
    if not closed_gate:
        provider = _ReminderTransport(turn)
        reminders.dispatch_cell_report_reminders(turn.factory, provider,
            worker_id='g12-connection-recovered', now=_NOW + dt.timedelta(minutes=1))
        assert len(provider.calls) == 1
        assert provider.calls[0][2] == reminders.cell_report_reminder_text()
