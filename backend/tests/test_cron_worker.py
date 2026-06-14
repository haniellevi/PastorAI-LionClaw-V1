"""Tests for the cron worker: interval parsing, scheduling and dispatch (O5).

Uses in-memory fakes (no DB, no Evolution). Verifies frequency parsing, the
"is this cron due?" decision (recurring vs state-driven), that SLA-action crons
invoke the engine while unknown actions are skipped, and that CronWorker.tick
runs the global SLA sweep plus due crons and always releases the session.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from app.workers.cron_worker import (
    CronWorker,
    parse_interval,
    run_due_crons,
    _should_run,
)

_T0 = dt.datetime(2026, 6, 13, 12, 0, tzinfo=dt.timezone.utc)


def _cron(
    *,
    nome: str = "cron",
    frequencia: str | None = None,
    gatilho_estado: str | None = None,
    acao: str | None = None,
    ativo: bool = True,
):
    cron = SimpleNamespace(
        id=uuid.uuid4(),
        igreja_id=uuid.uuid4(),
        nome=nome,
        frequencia=frequencia,
        gatilho_estado=gatilho_estado,
        acao=acao,
        ativo=ativo,
    )
    return cron


class _FakeScalars:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return list(self._items)


class _FakeResult:
    def __init__(self, items: list) -> None:
        self._items = items

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._items)


class FakeCronSession:
    """Serves active crons for the select(Cron) query; tracks rollback/close."""

    def __init__(self, crons: list) -> None:
        self._crons = crons
        self.rolled_back = False
        self.closed = False

    def execute(self, statement, params=None) -> _FakeResult:
        return _FakeResult(self._crons)

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class FakeEngine:
    """Counts run_for_igreja calls; returns a fixed handled list."""

    def __init__(self, handled: int = 1) -> None:
        self.calls: list[uuid.UUID] = []
        self._handled = handled

    def run_for_igreja(self, session, igreja_id, now=None) -> list:
        self.calls.append(igreja_id)
        return [object()] * self._handled


# ---------------------------------------------------------------------------
# parse_interval
# ---------------------------------------------------------------------------
def test_parse_named_intervals() -> None:
    assert parse_interval("hourly") == dt.timedelta(hours=1)
    assert parse_interval("DAILY") == dt.timedelta(days=1)
    assert parse_interval("continuo") == dt.timedelta(0)


def test_parse_compact_intervals() -> None:
    assert parse_interval("5m") == dt.timedelta(minutes=5)
    assert parse_interval("2h") == dt.timedelta(hours=2)
    assert parse_interval("30s") == dt.timedelta(seconds=30)
    assert parse_interval("1d") == dt.timedelta(days=1)


def test_parse_unknown_returns_none() -> None:
    assert parse_interval(None) is None
    assert parse_interval("") is None
    assert parse_interval("sometimes") is None
    assert parse_interval("xh") is None


# ---------------------------------------------------------------------------
# _should_run
# ---------------------------------------------------------------------------
def test_state_driven_runs_every_tick() -> None:
    cron = _cron(gatilho_estado="sla_vencido", frequencia=None)
    last_run: dict[str, dt.datetime] = {str(cron.id): _T0}
    assert _should_run(cron, _T0, last_run) is True


def test_recurring_runs_first_time_then_throttles() -> None:
    cron = _cron(frequencia="hourly")
    last_run: dict[str, dt.datetime] = {}
    assert _should_run(cron, _T0, last_run) is True
    last_run[str(cron.id)] = _T0
    # 30 min later: not due yet.
    assert _should_run(cron, _T0 + dt.timedelta(minutes=30), last_run) is False
    # 60 min later: due again.
    assert _should_run(cron, _T0 + dt.timedelta(hours=1), last_run) is True


def test_unparseable_recurring_never_runs() -> None:
    cron = _cron(frequencia="weirdly", gatilho_estado=None)
    assert _should_run(cron, _T0, {}) is False


# ---------------------------------------------------------------------------
# run_due_crons
# ---------------------------------------------------------------------------
def test_sla_action_cron_invokes_engine() -> None:
    cron = _cron(acao="rodar_sla_cobranca", frequencia="continuo")
    session = FakeCronSession([cron])
    engine = FakeEngine()
    dispatched = run_due_crons(session, engine=engine, now=_T0, last_run={})
    assert dispatched == 1
    assert engine.calls == [cron.igreja_id]


def test_non_sla_action_is_skipped_but_counted() -> None:
    cron = _cron(acao="enviar_relatorio_semanal", frequencia="continuo")
    session = FakeCronSession([cron])
    engine = FakeEngine()
    dispatched = run_due_crons(session, engine=engine, now=_T0, last_run={})
    # It is "dispatched" (marked as run) but the engine is not touched.
    assert dispatched == 1
    assert engine.calls == []


def test_not_due_cron_is_not_dispatched() -> None:
    cron = _cron(acao="rodar_sla", frequencia="hourly")
    session = FakeCronSession([cron])
    engine = FakeEngine()
    last_run = {str(cron.id): _T0}
    dispatched = run_due_crons(
        session, engine=engine, now=_T0 + dt.timedelta(minutes=1), last_run=last_run
    )
    assert dispatched == 0
    assert engine.calls == []


def test_failing_cron_rolls_back_and_does_not_break_others() -> None:
    class _BoomEngine(FakeEngine):
        def run_for_igreja(self, session, igreja_id, now=None):
            raise RuntimeError("boom")

    cron = _cron(acao="rodar_sla", frequencia="continuo")
    session = FakeCronSession([cron])
    dispatched = run_due_crons(
        session, engine=_BoomEngine(), now=_T0, last_run={}
    )
    assert dispatched == 0
    assert session.rolled_back is True


# ---------------------------------------------------------------------------
# CronWorker.tick
# ---------------------------------------------------------------------------
def test_tick_runs_sla_sweep_and_due_crons(monkeypatch) -> None:
    cron = _cron(acao="rodar_sla", frequencia="continuo")
    session = FakeCronSession([cron])
    engine = FakeEngine()

    # Stub the global sweep so tick() does not need a real tenant set.
    import app.workers.cron_worker as worker_module

    monkeypatch.setattr(
        worker_module, "run_all_igrejas", lambda s, e, now: 3
    )

    worker = CronWorker(
        session_factory=lambda: session, engine=engine, tick_seconds=300
    )
    counters = worker.tick(now=_T0)

    assert counters["sla_handled"] == 3
    assert counters["crons_run"] == 1
    assert session.closed is True
