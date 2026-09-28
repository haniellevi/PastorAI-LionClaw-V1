"""The real cron tick must reach V1a maintenance without a global DB lease."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.db.models import CellReportDraft
from app.services.evolution import EvolutionClient
from app.workers import cron_worker
from tests.test_cell_report_v1a_reminder_pg import (  # noqa: F401 - fixtures
    _NOW, _ReminderTransport, reminder_turn, report_turn, s3_turn,
    msg_engine_fx, rls_database_url, _rows, _run, _ClassifiedEvolution,
    _v1a_outbox_rows,
)

pytestmark = pytest.mark.rls_integration


def _cron(turn, monkeypatch, provider):
    def legacy_sweep(session, *_args, **_kwargs):
        session.execute(text('SELECT 1'))
        assert turn.engine.pool.checkedout() == 1
        return 0
    monkeypatch.setattr(cron_worker, 'run_all_igrejas', legacy_sweep)
    monkeypatch.setattr(cron_worker, 'run_due_crons', lambda *_a, **_k: 0)
    monkeypatch.setattr(cron_worker, 'run_pending_plan_changes', lambda *_a, **_k: 0)
    monkeypatch.setattr(cron_worker.CronWorker, '_purge_oauth_flows', lambda *_: 0)
    monkeypatch.setattr(EvolutionClient, '__init__', lambda *_a, **_k: None)
    monkeypatch.setattr(EvolutionClient, 'close', lambda *_: None)
    monkeypatch.setattr(EvolutionClient, 'send_text_classificado',
        lambda _self, instance, phone, content: provider.send_text_classificado(instance, phone, content))
    return cron_worker.CronWorker(session_factory=turn.factory, engine=SimpleNamespace(),
        settings=SimpleNamespace(cron_tick_seconds=30, redis_url=''))


def test_cron_schedules_and_delivers_only_after_global_session_is_closed(reminder_turn, monkeypatch):
    turn = reminder_turn
    provider = _ReminderTransport(turn)
    worker = _cron(turn, monkeypatch, provider)
    worker.tick(now=_NOW)
    assert len(provider.calls) == 1
    rows = _v1a_outbox_rows(turn)
    assert len(rows) == 1 and rows[0].state == 'enviado'
    worker.tick(now=_NOW + dt.timedelta(minutes=1))
    assert len(provider.calls) == 1
    assert turn.engine.pool.checkedout() == 0


def test_cron_purges_expired_draft_even_with_feature_gate_disabled(reminder_turn, monkeypatch):
    turn = reminder_turn
    _run(turn, 'V1A-CRON-DRAFT', 'Relatório: presentes: 10', _ClassifiedEvolution())
    with turn.factory.begin() as session:
        draft = session.execute(select(CellReportDraft)).scalar_one()
        draft.started_at = _NOW - dt.timedelta(hours=25)
        draft.expires_at = _NOW - dt.timedelta(hours=1)
    monkeypatch.setenv('CELL_REPORT_ENABLED_IGREJA_IDS', '')
    provider = _ReminderTransport(turn)
    _cron(turn, monkeypatch, provider).tick(now=_NOW)
    draft = _rows(turn, CellReportDraft)[0]
    assert draft.content_purged_at is not None
    assert draft.candidate_json is None and draft.candidate_sha256 is None
    assert provider.calls == []


def test_cron_works_before_v1a_schema_and_sends_nothing(reminder_turn, monkeypatch):
    turn = reminder_turn
    with turn.engine.begin() as connection:
        for table in ('cell_report_ai_reservations', 'cell_report_ai_daily_budgets',
                      'cell_report_reminders', 'cell_report_reminder_preferences', 'cell_report_drafts'):
            connection.exec_driver_sql(f'DROP TABLE {table} CASCADE')
    provider = _ReminderTransport(turn)
    _cron(turn, monkeypatch, provider).tick(now=_NOW)
    assert provider.calls == []
    assert turn.engine.pool.checkedout() == 0


@pytest.mark.parametrize('legacy_step', ('run_all_igrejas', 'run_due_crons'))
def test_legacy_cron_failure_does_not_starve_private_draft_purge(reminder_turn, monkeypatch, legacy_step):
    turn = reminder_turn
    _run(turn, 'V1A-CRON-LEGACY-FAIL', 'Relatório: presentes: 10', _ClassifiedEvolution())
    with turn.factory.begin() as session:
        draft = session.execute(select(CellReportDraft)).scalar_one()
        draft.started_at = _NOW - dt.timedelta(hours=25)
        draft.expires_at = _NOW - dt.timedelta(hours=1)
    monkeypatch.setenv('CELL_REPORT_ENABLED_IGREJA_IDS', '')
    provider = _ReminderTransport(turn)
    worker = _cron(turn, monkeypatch, provider)
    def unavailable(session, *_args, **_kwargs):
        session.execute(text('SELECT 1'))
        raise RuntimeError('synthetic legacy failure')
    monkeypatch.setattr(cron_worker, legacy_step, unavailable)
    with pytest.raises(RuntimeError, match='synthetic legacy failure'):
        worker.tick(now=_NOW)
    draft = _rows(turn, CellReportDraft)[0]
    assert draft.content_purged_at is not None
    assert draft.candidate_json is None
    assert turn.engine.pool.checkedout() == 0
    assert provider.calls == []
