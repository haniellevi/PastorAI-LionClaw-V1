"""Independent reminder outbox, privacy and retention tests on disposable PG17."""
from __future__ import annotations
import datetime as dt
import uuid
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app.config import Settings
from app.db.models import (CellReportDraft, CellReportReminder, CellReportReminderPreference,
    CelulaReuniao, ConsentRecord, Conversation, Pessoa, WhatsappConnection)
from app.db.rls import set_tenant_context_for_igreja
from app.services import cell_report_whatsapp
from tests.test_cell_report_v1a_worker_pg import report_turn, _run, _REPORT  # noqa: F401
from tests.test_agent_privileged_turn_pg import (  # noqa: F401
    _ClassifiedEvolution, _IGREJA, _TERM, _inbound, _rows, msg_engine_fx, rls_database_url, s3_turn,
)
pytestmark = pytest.mark.rls_integration
_NOW = dt.datetime(2026, 9, 27, 18, tzinfo=dt.timezone.utc)
_REAL_PILOT_GATE = Settings.whatsapp_piloto


@pytest.fixture
def reminder_turn(report_turn, monkeypatch):
    from app.config import get_settings
    # The shared autouse fixture enables every church; restore the real gate.
    monkeypatch.setattr(Settings, 'whatsapp_piloto', _REAL_PILOT_GATE)
    monkeypatch.setenv('AGENT_TERM_VERSION', _TERM)
    monkeypatch.setenv('ALLOW_REAL_SENDS', 'true')
    monkeypatch.setenv('WHATSAPP_PILOTO_IGREJA_IDS', str(_IGREJA))
    get_settings.cache_clear()
    from app.workers import queue_worker
    monkeypatch.setattr(queue_worker, "_whatsapp_reply_enabled", lambda tenant: get_settings().whatsapp_piloto(tenant))
    with report_turn.factory.begin() as session:
        meeting = session.get(CelulaReuniao, report_turn.meeting_id)
        meeting.data = _NOW.date()
        meeting.hora = '10:00'
        connection = session.execute(select(WhatsappConnection).where(WhatsappConnection.igreja_id == _IGREJA)).scalar_one()
        connection.status = 'online'
        for consent in session.execute(select(ConsentRecord).where(ConsentRecord.igreja_id == _IGREJA)).scalars():
            consent.aceite_em = _NOW - dt.timedelta(days=1)
    yield report_turn
    get_settings.cache_clear()


class _ReminderTransport(_ClassifiedEvolution):
    def __init__(self, turn, *statuses):
        super().__init__(*statuses)
        self.turn = turn
    def send_text_classificado(self, instance, telefone, texto):
        assert self.turn.engine.pool.checkedout() == 0
        # A separate DB session sees a committed claim before any provider I/O.
        claims = [r for r in _rows(self.turn, CellReportReminder) if r.state == 'em_envio']
        assert len(claims) == 1 and claims[0].claim_token is not None
        assert claims[0].claimed_until is not None
        return super().send_text_classificado(instance, telefone, texto)


def test_reminder_is_deduplicated_and_notice_recorded_before_or_after_delivery(reminder_turn):
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 1
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 0
    provider = _ReminderTransport(turn)
    reminders.dispatch_cell_report_reminders(turn.factory, provider, worker_id='synthetic-reminder-worker', now=_NOW)
    rows = _rows(turn, CellReportReminder)
    assert len(rows) == 1 and rows[0].state == 'enviado'
    assert rows[0].notice_recorded_at is not None and rows[0].sent_at is not None
    assert len(provider.calls) == 1 and 'PARAR LEMBRETES' in provider.calls[0][2]
    reminders.dispatch_cell_report_reminders(turn.factory, provider, worker_id='synthetic-reminder-worker', now=_NOW + dt.timedelta(minutes=1))
    assert len(provider.calls) == 1


def test_stop_reminders_is_scoped_and_global_sair_still_wins(reminder_turn):
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW)
    reply = _ClassifiedEvolution()
    _run(turn, 'V1A-STOP-REMINDERS', 'PARAR LEMBRETES', reply)
    preferences = _rows(turn, CellReportReminderPreference)
    assert len(preferences) == 1 and preferences[0].disabled_at is not None
    with turn.factory() as session:
        actor = session.get(Conversation, turn.conversation_id).pessoa_id
        assert session.get(Pessoa, actor).optout is not True
    provider = _ReminderTransport(turn)
    reminders.dispatch_cell_report_reminders(turn.factory, provider, worker_id='synthetic-reminder-worker', now=_NOW)
    assert provider.calls == []
    _run(turn, 'V1A-GLOBAL-SAIR', 'SAIR', reply)
    with turn.factory() as session:
        assert session.get(Pessoa, actor).optout is True


@pytest.mark.parametrize('revoke', ('term', 'humano', 'release'))
def test_reminder_revalidates_authority_before_sending(reminder_turn, monkeypatch, revoke):
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 1
    with turn.factory.begin() as session:
        conversation = session.get(Conversation, turn.conversation_id)
        if revoke == 'humano':
            conversation.estado = 'humano'
        elif revoke == 'term':
            session.add(ConsentRecord(igreja_id=_IGREJA, pessoa_id=conversation.pessoa_id, termo_versao='optout:' + _TERM, aceite_em=_NOW - dt.timedelta(seconds=1)))
    if revoke == 'release':
        monkeypatch.setattr(cell_report_whatsapp, 'CELL_REPORT_APPROVED_RELEASE_ID', None)
    provider = _ReminderTransport(turn)
    reminders.dispatch_cell_report_reminders(turn.factory, provider, worker_id='synthetic-reminder-worker', now=_NOW)
    assert provider.calls == []
    assert _rows(turn, CellReportReminder)[0].state in {'cancelado', 'obsoleto'}


def test_ambiguous_reminder_is_not_resent(reminder_turn):
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW)
    provider = _ReminderTransport(turn, 'ambiguo')
    reminders.dispatch_cell_report_reminders(turn.factory, provider, worker_id='synthetic-reminder-worker', now=_NOW)
    assert _rows(turn, CellReportReminder)[0].state == 'ambiguo'
    reminders.dispatch_cell_report_reminders(turn.factory, provider, worker_id='synthetic-reminder-worker', now=_NOW + dt.timedelta(minutes=10))
    assert len(provider.calls) == 1


def test_draft_purge_runs_after_feature_is_turned_off(reminder_turn, monkeypatch):
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    _run(turn, 'V1A-PURGE-DRAFT', 'Relatório: presentes: 10', _ClassifiedEvolution())
    with turn.factory.begin() as session:
        draft = session.execute(select(CellReportDraft).where(CellReportDraft.igreja_id == _IGREJA)).scalar_one()
        draft.started_at = _NOW - dt.timedelta(hours=25)
        draft.expires_at = _NOW - dt.timedelta(hours=1)
    monkeypatch.setenv('CELL_REPORT_ENABLED_IGREJA_IDS', '')
    reminders.purge_expired_cell_report_state(turn.factory, now=_NOW)
    draft = _rows(turn, CellReportDraft)[0]
    assert draft.state == 'expirado'
    assert draft.candidate_json is None and draft.candidate_sha256 is None
    assert draft.content_purged_at is not None


@pytest.mark.parametrize('revoke', ('send_flag', 'pilot', 'access', 'phone_ambiguous', 'submitted', 'leader', 'cell', 'quiet_hours'))
def test_reminder_obeys_send_identity_meeting_and_time_gates(reminder_turn, monkeypatch, revoke):
    from app.config import get_settings
    from app.db.models import AppUser, Celula
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 1
    dispatch_at = _NOW
    with turn.factory.begin() as session:
        meeting = session.get(CelulaReuniao, turn.meeting_id)
        actor_id = session.get(Conversation, turn.conversation_id).pessoa_id
        if revoke == 'access':
            session.get(AppUser, turn.app_user_id).status = 'inativo'
        elif revoke == 'phone_ambiguous':
            phone = session.get(Pessoa, actor_id).telefone
            session.add(Pessoa(igreja_id=_IGREJA, nome='Outro Contato Sintético', telefone=phone[-11:]))
        elif revoke == 'submitted':
            meeting.relatorio_status = 'enviado'
            meeting.relatorio_enviado_em = _NOW
            meeting.relatorio_enviado_por = actor_id
        elif revoke == 'leader':
            session.get(Celula, meeting.celula_id).lider_id = None
        elif revoke == 'cell':
            session.get(Celula, meeting.celula_id).ativo = False
    if revoke == 'send_flag':
        monkeypatch.setenv('ALLOW_REAL_SENDS', 'false')
    elif revoke == 'pilot':
        monkeypatch.setenv('WHATSAPP_PILOTO_IGREJA_IDS', '')
    elif revoke == 'quiet_hours':
        dispatch_at = _NOW.replace(hour=1) + dt.timedelta(days=1)  # 22h São Paulo
    get_settings.cache_clear()
    provider = _ReminderTransport(turn)
    reminders.dispatch_cell_report_reminders(turn.factory, provider, worker_id='synthetic-reminder-worker', now=dispatch_at)
    assert provider.calls == []


@pytest.mark.parametrize('changed', ('phone', 'instance'))
def test_reminder_fresh_fence_rejects_destination_changed_after_claim(reminder_turn, monkeypatch, changed):
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW)
    original_claim = reminders._claim_next_reminder
    def claim_then_change(*args, **kwargs):
        claim = original_claim(*args, **kwargs)
        if claim is not None:
            with turn.factory.begin() as session:
                if changed == 'phone':
                    actor_id = session.get(Conversation, turn.conversation_id).pessoa_id
                    session.get(Pessoa, actor_id).telefone = '5500000000008'
                else:
                    connection = session.execute(select(WhatsappConnection).where(WhatsappConnection.igreja_id == _IGREJA)).scalar_one()
                    connection.instance = 'different-synthetic-instance'
        return claim
    monkeypatch.setattr(reminders, '_claim_next_reminder', claim_then_change)
    provider = _ReminderTransport(turn)
    reminders.dispatch_cell_report_reminders(turn.factory, provider, worker_id='synthetic-reminder-worker', now=_NOW)
    assert provider.calls == []


def test_presend_failures_cannot_bypass_two_retry_limit(reminder_turn):
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 1

    class ConnectFailure(_ReminderTransport):
        def send_text_classificado(self, instance, telefone, texto):
            super().send_text_classificado(instance, telefone, texto)
            return SimpleNamespace(status='falhou_retentavel', error_class='connect_error',
                                   consume_retry_budget=False, retry_after_seconds=60)

    provider = ConnectFailure(turn)
    for minutes in (0, 1, 6, 12):
        reminders.dispatch_cell_report_reminders(turn.factory, provider,
            worker_id='synthetic-retry-worker', now=_NOW + dt.timedelta(minutes=minutes))
    assert len(provider.calls) == 3  # Initial attempt plus two pre-send retries.
    assert _rows(turn, CellReportReminder)[0].state not in {'pendente', 'retry', 'em_envio'}


@pytest.mark.parametrize('boundary', ('lease', 'quiet_hours'))
def test_real_clock_is_refreshed_between_claim_and_transport(reminder_turn, monkeypatch, boundary):
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 1
    current = [_NOW if boundary == 'lease' else _NOW.replace(hour=23, minute=59, second=50)]
    advance = dt.timedelta(seconds=60 if boundary == 'lease' else 20)
    monkeypatch.setattr(reminders, '_now', lambda supplied: supplied if supplied is not None else current[0])
    original_claim = reminders._claim_next_reminder

    def delayed_claim(*args, **kwargs):
        claim = original_claim(*args, **kwargs)
        if claim is not None:
            current[0] += advance
        return claim

    monkeypatch.setattr(reminders, '_claim_next_reminder', delayed_claim)
    provider = _ReminderTransport(turn)
    reminders.dispatch_cell_report_reminders(turn.factory, provider,
        worker_id='synthetic-clock-worker', now=None, lease_seconds=30)
    assert provider.calls == []


@pytest.mark.parametrize('operation', ('stop', 'report_submitted'))
def test_reminder_waits_for_conversation_before_claiming_domain_rows(reminder_turn, operation):
    """Force the historical R→C / M→C inversion against a C-first transaction."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from sqlalchemy import event, text
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    if operation == 'stop':
        assert reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW) == 1
    conversation_locked, contender_at_lock = Event(), Event()
    provider = _ReminderTransport(turn)

    def observe_lock(conn, cursor, statement, parameters, context, executemany):
        query = statement.lower()
        if current_thread().name.startswith('reminder-contender') and 'conversations' in query and 'for update' in query:
            contender_at_lock.set()

    def bounded_factory():
        session = turn.factory()
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        return session

    def foreground_change():
        with bounded_factory() as session:
            set_tenant_context_for_igreja(session, str(_IGREJA))
            conversation = session.execute(select(Conversation).where(
                Conversation.id == turn.conversation_id).with_for_update()).scalar_one()
            conversation_locked.set()
            assert contender_at_lock.wait(5), 'background did not revalidate the conversation'
            if operation == 'stop':
                assert reminders.disable_cell_report_reminders(session, igreja_id=_IGREJA,
                    pessoa_id=conversation.pessoa_id, now=_NOW)
            else:
                meeting = session.execute(select(CelulaReuniao).where(
                    CelulaReuniao.id == turn.meeting_id).with_for_update()).scalar_one()
                meeting.relatorio_status = 'enviado'
                meeting.relatorio_enviado_em = _NOW
                meeting.relatorio_enviado_por = conversation.pessoa_id
            session.commit()

    def background_work():
        assert conversation_locked.wait(5)
        if operation == 'stop':
            return reminders.dispatch_cell_report_reminders(bounded_factory, provider,
                worker_id='synthetic-concurrent-worker', now=_NOW)
        return reminders.schedule_due_cell_report_reminders(bounded_factory, now=_NOW)

    event.listen(turn.engine, 'before_cursor_execute', observe_lock)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='foreground') as foreground:
            change = foreground.submit(foreground_change)
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix='reminder-contender') as background:
                work = background.submit(background_work)
                change.result(timeout=12)
                work.result(timeout=12)
    finally:
        event.remove(turn.engine, 'before_cursor_execute', observe_lock)
    assert provider.calls == []
    assert all(row.state not in {'pendente', 'retry', 'em_envio'} for row in _rows(turn, CellReportReminder))


def test_two_schedulers_share_one_daily_reminder_limit_per_leader(reminder_turn):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    with turn.factory.begin() as session:
        meeting = session.get(CelulaReuniao, turn.meeting_id)
        session.add(CelulaReuniao(igreja_id=_IGREJA, celula_id=meeting.celula_id,
            data=meeting.data, hora='11:00', status='planejada', relatorio_status='pendente'))
    barrier = Barrier(2)

    def schedule():
        barrier.wait(timeout=5)
        return reminders.schedule_due_cell_report_reminders(turn.factory, now=_NOW)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = [workers.submit(schedule) for _ in range(2)]
        assert sum(result.result(timeout=15) for result in results) == 1
    assert len(_rows(turn, CellReportReminder)) == 1


@pytest.mark.parametrize('terminal', ('no', 'sair', 'expired', 'humano', 'release', 'term'))
def test_terminal_proposal_content_is_purged_within_one_hour(reminder_turn, monkeypatch, terminal):
    from app.db.models import AgentActionProposal, Message
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    _run(turn, 'V1A-RETENTION-REPORT', _REPORT, _ClassifiedEvolution())
    proposal = _rows(turn, AgentActionProposal)[0]
    assert proposal.delivered_at is not None
    with turn.factory() as session:
        delivered_text = session.get(Message, proposal.summary_message_id).texto
    if terminal in {'no', 'sair'}:
        _run(turn, 'V1A-RETENTION-STOP', 'NÃO' if terminal == 'no' else 'SAIR', _ClassifiedEvolution())
    elif terminal == 'release':
        monkeypatch.setattr(cell_report_whatsapp, 'CELL_REPORT_APPROVED_RELEASE_ID', None)
    elif terminal in {'humano', 'term'}:
        with turn.factory.begin() as session:
            conversation = session.get(Conversation, turn.conversation_id)
            if terminal == 'humano':
                conversation.estado = 'humano'
            else:
                session.add(ConsentRecord(igreja_id=_IGREJA, pessoa_id=conversation.pessoa_id,
                    termo_versao='optout:' + _TERM, aceite_em=proposal.delivered_at + dt.timedelta(seconds=1)))
    terminal_at = proposal.expires_at if terminal == 'expired' else dt.datetime.now(dt.timezone.utc)
    purge_at = terminal_at + dt.timedelta(minutes=59)
    reminders.purge_expired_cell_report_state(turn.factory, now=purge_at)
    draft = _rows(turn, CellReportDraft)[0]
    assert draft.state not in {'coletando', 'pronto'}
    assert draft.candidate_json is None and draft.candidate_sha256 is None
    assert draft.content_purged_at is not None
    assert _rows(turn, AgentActionProposal)[0].state not in {'preparada', 'pendente'}
    with turn.factory() as session:
        # Delivered history is distinct from the disposable working draft.
        assert session.get(Message, proposal.summary_message_id).texto == delivered_text
        assert session.get(CelulaReuniao, turn.meeting_id).relatorio_status == 'pendente'


def test_suppressed_undelivered_summary_is_scrubbed_but_inbound_history_survives(reminder_turn, monkeypatch):
    from app.db.models import AgentActionProposal, Message
    from app.services import cell_report_reminders as reminders
    from app.workers import queue_worker
    turn = reminder_turn
    provider = _ClassifiedEvolution('falhou_retentavel', 'aceito')
    request = _inbound(turn, 'V1A-UNDLVD-SUMMARY', _REPORT)
    with pytest.raises(queue_worker.AgentReplyRetryable):
        queue_worker.run_agent_for_message(turn.factory, request, evolution_client=provider)
    proposal = _rows(turn, AgentActionProposal)[0]
    assert proposal.delivered_at is None
    monkeypatch.setattr(cell_report_whatsapp, 'CELL_REPORT_APPROVED_RELEASE_ID', None)
    queue_worker.run_agent_for_message(turn.factory, request, evolution_client=provider)
    assert len(provider.calls) == 1
    reminders.purge_expired_cell_report_state(turn.factory,
        now=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=59))
    draft = _rows(turn, CellReportDraft)[0]
    assert draft.candidate_json is None and draft.candidate_sha256 is None
    with turn.factory() as session:
        assert session.get(Message, proposal.summary_message_id).texto in (None, '')
        assert session.get(Message, proposal.source_message_id).texto == _REPORT


@pytest.mark.parametrize('revoke', ('sair', 'humano', 'release', 'term', 'access', 'meeting', 'leader', 'cell'))
def test_incomplete_draft_is_purged_after_authority_revocation(reminder_turn, monkeypatch, revoke):
    from app.db.models import AppUser, Celula
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    _run(turn, 'V1A-PARTIAL-RETENTION', 'Relatório: presentes: 10', _ClassifiedEvolution())
    assert _rows(turn, CellReportDraft)[0].state == 'coletando'
    if revoke == 'sair':
        _run(turn, 'V1A-PARTIAL-SAIR', 'SAIR', _ClassifiedEvolution())
    elif revoke == 'release':
        monkeypatch.setattr(cell_report_whatsapp, 'CELL_REPORT_APPROVED_RELEASE_ID', None)
    else:
        with turn.factory.begin() as session:
            conversation = session.get(Conversation, turn.conversation_id)
            if revoke == 'humano':
                conversation.estado = 'humano'
            elif revoke == 'term':
                session.add(ConsentRecord(igreja_id=_IGREJA, pessoa_id=conversation.pessoa_id,
                    termo_versao='optout:' + _TERM, aceite_em=dt.datetime.now(dt.timezone.utc)))
            elif revoke == 'access':
                session.get(AppUser, turn.app_user_id).status = 'inativo'
            else:
                meeting = session.get(CelulaReuniao, turn.meeting_id)
                if revoke == 'meeting':
                    meeting.status = 'cancelada'
                elif revoke == 'leader':
                    session.get(Celula, meeting.celula_id).lider_id = None
                elif revoke == 'cell':
                    session.get(Celula, meeting.celula_id).ativo = False
    reminders.purge_expired_cell_report_state(turn.factory,
        now=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=59))
    draft = _rows(turn, CellReportDraft)[0]
    assert draft.state not in {'coletando', 'pronto'}
    assert draft.candidate_json is None and draft.candidate_sha256 is None
    assert draft.content_purged_at is not None


def test_corrected_draft_uses_current_proposal_expiry_despite_history(reminder_turn):
    from app.db.models import AgentActionProposal
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    _run(turn, 'V1A-REVISION-RETENTION-1', _REPORT, _ClassifiedEvolution())
    _run(turn, 'V1A-REVISION-RETENTION-2', 'presentes: 12', _ClassifiedEvolution())
    proposals = _rows(turn, AgentActionProposal)
    assert len(proposals) == 2
    latest = next(row for row in proposals if row.state == 'pendente')
    reminders.purge_expired_cell_report_state(turn.factory,
        now=latest.expires_at + dt.timedelta(minutes=59))
    draft = _rows(turn, CellReportDraft)[0]
    assert draft.candidate_json is None and draft.candidate_sha256 is None
    assert draft.state not in {'coletando', 'pronto'}
    assert all(row.state not in {'preparada', 'pendente'} for row in _rows(turn, AgentActionProposal))


def test_undelivered_prepared_proposal_expires_with_its_draft(reminder_turn):
    from app.db.models import AgentActionProposal
    from app.services import cell_report_reminders as reminders
    from app.workers import queue_worker
    turn = reminder_turn
    request = _inbound(turn, 'V1A-PREPARED-EXPIRY', _REPORT)
    with pytest.raises(queue_worker.AgentReplyRetryable):
        queue_worker.run_agent_for_message(turn.factory, request,
            evolution_client=_ClassifiedEvolution('falhou_retentavel'))
    assert _rows(turn, AgentActionProposal)[0].state == 'preparada'
    expiry = _rows(turn, CellReportDraft)[0].expires_at
    reminders.purge_expired_cell_report_state(turn.factory, now=expiry + dt.timedelta(minutes=59))
    assert _rows(turn, CellReportDraft)[0].candidate_json is None
    assert _rows(turn, AgentActionProposal)[0].state not in {'preparada', 'pendente'}


def test_valid_older_draft_cannot_starve_expired_proposal_with_small_purge_limit(reminder_turn):
    import hashlib
    import json
    from app.db.models import AgentActionProposal, Message
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    _run(turn, 'V1A-PURGE-FAIRNESS', _REPORT, _ClassifiedEvolution())
    target = _rows(turn, CellReportDraft)[0]
    proposal = _rows(turn, AgentActionProposal)[0]
    older_start = target.started_at - dt.timedelta(hours=2)
    payload = {'presentes': 10, 'visitantes': None, 'decisoes': None, 'oferta_centavos': None}
    with turn.factory.begin() as session:
        original = session.get(Conversation, turn.conversation_id)
        older_conversation = Conversation(igreja_id=_IGREJA, pessoa_id=original.pessoa_id,
            telefone=original.telefone, estado='ia')
        session.add(older_conversation)
        session.flush()
        older_message = Message(igreja_id=_IGREJA, conversation_id=older_conversation.id,
            direcao='in', autor='contato', texto='Relatório: presentes: 10')
        session.add(older_message)
        session.flush()
        older = CellReportDraft(igreja_id=_IGREJA, conversation_id=older_conversation.id,
            reuniao_id=turn.meeting_id, actor_pessoa_id=original.pessoa_id,
            source_message_id=older_message.id, state='coletando', revision=1,
            candidate_json=payload, candidate_sha256=hashlib.sha256(json.dumps(payload,
                sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            started_at=older_start, expires_at=older_start + dt.timedelta(hours=24), updated_at=older_start)
        session.add(older)
        session.flush()
        older_id = older.id
    reminders.purge_expired_cell_report_state(turn.factory,
        now=proposal.expires_at + dt.timedelta(minutes=59), limit=1)
    with turn.factory() as session:
        assert session.get(CellReportDraft, target.id).candidate_json is None
        assert session.get(CellReportDraft, older_id).state == 'coletando'


def test_locked_undelivered_summary_is_retried_by_later_purge(reminder_turn, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    from app.db.models import AgentActionProposal, Message
    from app.services import cell_report_reminders as reminders
    from app.workers import queue_worker
    turn = reminder_turn
    request = _inbound(turn, 'V1A-LOCKED-SUMMARY', _REPORT)
    with pytest.raises(queue_worker.AgentReplyRetryable):
        queue_worker.run_agent_for_message(turn.factory, request,
            evolution_client=_ClassifiedEvolution('falhou_retentavel'))
    proposal = _rows(turn, AgentActionProposal)[0]
    monkeypatch.setattr(cell_report_whatsapp, 'CELL_REPORT_APPROVED_RELEASE_ID', None)
    purge_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=59)

    def bounded_factory():
        session = turn.factory()
        session.execute(text("SET LOCAL lock_timeout = '100ms'"))
        return session

    with turn.factory() as blocker:
        blocker.execute(select(Message).where(Message.id == proposal.summary_message_id).with_for_update()).scalar_one()
        try:
            reminders.purge_expired_cell_report_state(bounded_factory, now=purge_at)
        except OperationalError as error:
            assert error.orig.pgcode == '55P03'  # A safe rollback is also retryable.
        blocker.rollback()
    reminders.purge_expired_cell_report_state(turn.factory, now=purge_at)
    with turn.factory() as session:
        assert session.get(Message, proposal.summary_message_id).texto in (None, '')


def test_ambiguous_summary_history_is_preserved_while_draft_expires(reminder_turn):
    from app.db.models import AgentActionProposal, Message
    from app.services import cell_report_reminders as reminders
    turn = reminder_turn
    _run(turn, 'V1A-AMBIGUOUS-RETENTION', _REPORT, _ClassifiedEvolution('desconhecido'))
    proposal = _rows(turn, AgentActionProposal)[0]
    with turn.factory() as session:
        summary = session.get(Message, proposal.summary_message_id)
        assert summary.agent_reply_state == 'ia_ambigua'
        original_text = summary.texto
        assert original_text
    expiry = _rows(turn, CellReportDraft)[0].expires_at
    reminders.purge_expired_cell_report_state(turn.factory, now=expiry + dt.timedelta(minutes=59))
    assert _rows(turn, CellReportDraft)[0].candidate_json is None
    with turn.factory() as session:
        summary = session.get(Message, proposal.summary_message_id)
        assert summary.texto == original_text
        assert summary.agent_reply_state == 'ia_ambigua'
