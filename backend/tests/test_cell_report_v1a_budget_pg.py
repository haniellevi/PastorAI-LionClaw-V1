"""Independent bounded-cost and concurrency tests on disposable PG17."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from sqlalchemy import select

from app.db.models import CellReportAiDailyBudget, CellReportAiReservation, CellReportDraft
from app.db.rls import set_tenant_context_for_igreja
from tests.test_cell_report_v1a_worker_pg import report_turn, _run  # noqa: F401
from tests.test_agent_privileged_turn_pg import (  # noqa: F401
    _ClassifiedEvolution, _IGREJA, _rows, msg_engine_fx, rls_database_url, s3_turn,
)

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def budget_service():
    from app.services import cell_report_whatsapp
    return cell_report_whatsapp


def _draft(turn):
    _run(turn, 'V1A-BUDGET-DRAFT', 'Relatório: presentes: 10', _ClassifiedEvolution())
    return _rows(turn, CellReportDraft)[0].id


def _reserve(turn, service, draft_id, usd):
    with turn.factory() as session:
        set_tenant_context_for_igreja(session, str(_IGREJA))
        result = service.reserve_v1a_extraction_budget(session, igreja_id=_IGREJA,
            draft_id=draft_id, model='gpt-5.6-luna',
            estimate_cost=lambda _model, _input, _output: Decimal(usd))
        session.commit()
        return result


@pytest.mark.parametrize('usd,allowed', [('0.02', 4), ('0.04', 2)])
def test_v1a_budget_stops_at_call_or_report_cap(report_turn, budget_service, usd, allowed):
    turn = report_turn
    draft_id = _draft(turn)
    for _ in range(allowed):
        _reserve(turn, budget_service, draft_id, usd)
    with pytest.raises(ValueError):
        _reserve(turn, budget_service, draft_id, usd)
    rows = _rows(turn, CellReportAiReservation)
    assert len(rows) == allowed
    assert sum(row.estimated_microusd for row in rows) <= 100_000
    assert _rows(turn, CellReportAiDailyBudget)[0].reserved_microusd == sum(row.estimated_microusd for row in rows)


def test_v1a_budget_serializes_two_competing_reservations(report_turn, budget_service):
    turn = report_turn
    draft_id = _draft(turn)
    _reserve(turn, budget_service, draft_id, '0.04')
    barrier = Barrier(2)

    def reserve():
        barrier.wait(timeout=5)
        try:
            _reserve(turn, budget_service, draft_id, '0.04')
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(reserve) for _ in range(2)]
        assert sum(result.result(timeout=15) for result in results) == 1
    assert len(_rows(turn, CellReportAiReservation)) == 2
    assert _rows(turn, CellReportAiDailyBudget)[0].reserved_microusd == 80_000


def test_v1a_daily_cap_is_checked_even_when_report_has_capacity(report_turn, budget_service):
    turn = report_turn
    draft_id = _draft(turn)
    _reserve(turn, budget_service, draft_id, '0.005')
    with turn.factory.begin() as session:
        daily = session.execute(select(CellReportAiDailyBudget)).scalar_one()
        # Represents other reports already reserved during the same UTC day.
        daily.reserved_microusd = 1_990_000
    with pytest.raises(ValueError):
        _reserve(turn, budget_service, draft_id, '0.02')
    assert len(_rows(turn, CellReportAiReservation)) == 1
    assert _rows(turn, CellReportAiDailyBudget)[0].reserved_microusd == 1_990_000


def test_v1a_cost_settlement_is_idempotent(report_turn, budget_service):
    turn = report_turn
    draft_id = _draft(turn)
    _reserve(turn, budget_service, draft_id, '0.02')
    reservation = _rows(turn, CellReportAiReservation)[0]
    for _ in range(2):
        with turn.factory() as session:
            set_tenant_context_for_igreja(session, str(_IGREJA))
            budget_service.settle_v1a_extraction_budget(session, igreja_id=_IGREJA,
                reservation_id=reservation.id, actual_microusd=1_000)
            session.commit()
    daily = _rows(turn, CellReportAiDailyBudget)[0]
    assert daily.reserved_microusd == 0
    assert daily.settled_microusd == 1_000
    settled = _rows(turn, CellReportAiReservation)[0]
    assert settled.state == 'liquidada' and settled.actual_microusd == 1_000


def test_different_reports_compete_for_the_same_daily_budget(report_turn, budget_service):
    from app.db.models import CelulaReuniao, Conversation, Message
    turn = report_turn
    first_id = _draft(turn)
    _reserve(turn, budget_service, first_id, '0.04')
    with turn.factory.begin() as session:
        first = session.get(CellReportDraft, first_id)
        original = session.get(Conversation, turn.conversation_id)
        conversation = Conversation(igreja_id=_IGREJA, pessoa_id=original.pessoa_id,
            telefone=original.telefone, estado='ia')
        session.add(conversation)
        session.flush()
        message = Message(igreja_id=_IGREJA, conversation_id=conversation.id,
            direcao='in', autor='contato', texto='Relatório: presentes: 10')
        session.add(message)
        session.flush()
        first_meeting = session.get(CelulaReuniao, turn.meeting_id)
        second_meeting = CelulaReuniao(igreja_id=_IGREJA, celula_id=first_meeting.celula_id,
            data=first_meeting.data, hora='20:00', status='planejada', relatorio_status='pendente')
        session.add(second_meeting)
        session.flush()
        second = CellReportDraft(igreja_id=_IGREJA, conversation_id=conversation.id,
            reuniao_id=second_meeting.id, actor_pessoa_id=original.pessoa_id,
            source_message_id=message.id, state='coletando', revision=1,
            candidate_json=dict(first.candidate_json), candidate_sha256=first.candidate_sha256,
            started_at=first.started_at, expires_at=first.expires_at, updated_at=first.updated_at)
        session.add(second)
        session.flush()
        second_id = second.id
        session.execute(select(CellReportAiDailyBudget)).scalar_one().reserved_microusd = 1_940_000
    barrier = Barrier(2)

    def reserve(draft_id):
        barrier.wait(timeout=5)
        try:
            _reserve(turn, budget_service, draft_id, '0.04')
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(reserve, draft_id) for draft_id in (first_id, second_id)]
        assert sum(attempt.result(timeout=15) for attempt in attempts) == 1
    assert len(_rows(turn, CellReportAiReservation)) == 2
    assert _rows(turn, CellReportAiDailyBudget)[0].reserved_microusd == 1_980_000


def test_preloaded_daily_balance_is_refreshed_after_another_reservation(report_turn, budget_service):
    turn = report_turn
    draft_id = _draft(turn)
    _reserve(turn, budget_service, draft_id, '0.01')
    with turn.factory.begin() as session:
        session.execute(select(CellReportAiDailyBudget)).scalar_one().reserved_microusd = 1_950_000
    with turn.factory() as stale_session:
        set_tenant_context_for_igreja(stale_session, str(_IGREJA))
        preloaded = stale_session.execute(select(CellReportAiDailyBudget)).scalar_one()
        assert preloaded.reserved_microusd == 1_950_000
        _reserve(turn, budget_service, draft_id, '0.04')
        with pytest.raises(ValueError):
            budget_service.reserve_v1a_extraction_budget(stale_session, igreja_id=_IGREJA,
                draft_id=draft_id, model='gpt-5.6-luna',
                estimate_cost=lambda *_: Decimal('0.04'))
        stale_session.rollback()
    assert len(_rows(turn, CellReportAiReservation)) == 2
    assert _rows(turn, CellReportAiDailyBudget)[0].reserved_microusd == 1_990_000


@pytest.mark.parametrize('usd,count', [('0.01', 4), ('0.05', 2)])
def test_cancelled_draft_does_not_reset_the_meeting_cost_or_call_limit(report_turn, budget_service, usd, count):
    import datetime as dt
    turn = report_turn
    first_id = _draft(turn)
    for _ in range(count):
        _reserve(turn, budget_service, first_id, usd)
    with turn.factory.begin() as session:
        first = session.get(CellReportDraft, first_id)
        first.state = 'cancelado'
        first.candidate_json = None
        first.candidate_sha256 = None
        first.terminal_at = first.content_purged_at = dt.datetime.now(dt.timezone.utc)
    _run(turn, 'V1A-BUDGET-NEW-CYCLE', 'Relatório: presentes: 12', _ClassifiedEvolution())
    second = next(row for row in _rows(turn, CellReportDraft) if row.id != first_id)
    assert second.reuniao_id == turn.meeting_id and second.state == 'coletando'
    with pytest.raises(ValueError):
        _reserve(turn, budget_service, second.id, '0.01')
    assert len(_rows(turn, CellReportAiReservation)) == count
