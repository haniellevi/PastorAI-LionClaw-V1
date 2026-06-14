"""Cron worker: drive the SLA engine and run crons/state triggers (O5).

A standalone long-running process (`python -m app.workers.cron_worker`) that, on
each tick:

  1. Runs the SLA engine sweep across tenants (charge/escalate blown deadlines).
  2. Executes the rows of the `crons` table: recurring jobs (by `frequencia`) and
     state-driven triggers (`gatilho_estado`), dispatching the configured `acao`.

Cron actions are idempotent (the SLA engine dedupes its own dispatches), so a
double tick never double-charges. Frequency scheduling uses an in-process
last-run map; state-driven crons (those with a `gatilho_estado`) run every tick
because they re-evaluate current state and act idempotently.

Graceful shutdown mirrors the queue worker: SIGTERM/SIGINT stop the loop and the
DB session is released after each tick.
"""

from __future__ import annotations

import datetime as dt
import logging
import signal
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Cron
from app.db.session import get_session_factory
from app.services.sla_engine import SlaEngine, run_all_igrejas

logger = logging.getLogger("pastorai.cron_worker")

# Named frequencies mapped to an interval. Anything not matched is parsed as a
# compact "<n><unit>" form (e.g. "5m", "2h", "30s", "1d").
_NAMED_INTERVALS: dict[str, dt.timedelta] = {
    "continuo": dt.timedelta(0),
    "tick": dt.timedelta(0),
    "minutely": dt.timedelta(minutes=1),
    "hourly": dt.timedelta(hours=1),
    "daily": dt.timedelta(days=1),
    "weekly": dt.timedelta(weeks=1),
}

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_interval(frequencia: str | None) -> dt.timedelta | None:
    """Parse a cron `frequencia` into an interval, or None when unrecognised.

    Recognises named frequencies and a compact "<n><unit>" form. A None result
    means the row is not a simple recurring job (it may still be state-driven).
    """
    if not frequencia:
        return None
    value = frequencia.strip().lower()
    if value in _NAMED_INTERVALS:
        return _NAMED_INTERVALS[value]
    unit = value[-1:]
    if unit in _UNIT_SECONDS and value[:-1].isdigit():
        return dt.timedelta(seconds=int(value[:-1]) * _UNIT_SECONDS[unit])
    return None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------------------
# Cron action handlers
# ---------------------------------------------------------------------------
def _action_sla(session: Session, cron: Cron, engine: SlaEngine) -> int:
    """Run the SLA engine for the cron's igreja (idempotent)."""
    return len(engine.run_for_igreja(session, cron.igreja_id))


def _is_sla_action(acao: str | None) -> bool:
    if not acao:
        return False
    a = acao.lower()
    return any(token in a for token in ("sla", "cobranca", "cobrança", "prazo"))


def run_due_crons(
    session: Session,
    *,
    engine: SlaEngine,
    now: dt.datetime | None = None,
    last_run: dict[str, dt.datetime] | None = None,
) -> int:
    """Execute active crons that are due (recurring) or state-driven.

    `last_run` is an in-process map {cron_id: instant} used only to throttle
    recurring jobs; state-driven crons (with a `gatilho_estado`) always run.
    Returns the number of cron rows actually dispatched.
    """
    now = now or _now()
    last_run = last_run if last_run is not None else {}

    crons = session.execute(
        select(Cron).where(Cron.ativo.is_(True))
    ).scalars().all()

    dispatched = 0
    for cron in crons:
        if not _should_run(cron, now, last_run):
            continue
        try:
            if _is_sla_action(cron.acao):
                _action_sla(session, cron, engine)
            else:
                logger.info(
                    "Cron '%s' has no executable action handler (acao=%s); skipped",
                    cron.nome,
                    cron.acao,
                )
            last_run[str(cron.id)] = now
            dispatched += 1
        except Exception:  # noqa: BLE001 - one cron must not break the others
            logger.exception("Cron '%s' execution failed", cron.nome)
            session.rollback()
    return dispatched


def _should_run(
    cron: Cron, now: dt.datetime, last_run: dict[str, dt.datetime]
) -> bool:
    """Decide whether a cron row is due this tick."""
    # State-driven triggers re-evaluate every tick (idempotent handlers).
    if cron.gatilho_estado:
        return True
    interval = parse_interval(cron.frequencia)
    if interval is None:
        return False
    previous = last_run.get(str(cron.id))
    if previous is None:
        return True
    return (now - previous) >= interval


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------
class CronWorker:
    """Long-running worker that ticks the SLA engine and the crons table."""

    def __init__(
        self,
        session_factory: Callable[[], Session] | None = None,
        engine: SlaEngine | None = None,
        tick_seconds: int | None = None,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._engine = engine or SlaEngine()
        self._tick_seconds = tick_seconds or get_settings().cron_tick_seconds
        self._last_run: dict[str, dt.datetime] = {}
        self._running = False

    def stop(self, *_: Any) -> None:
        """Request a graceful shutdown (SIGTERM/SIGINT handler)."""
        logger.info("Cron worker shutdown requested")
        self._running = False

    def tick(self, now: dt.datetime | None = None) -> dict[str, int]:
        """Run one full cycle: global SLA sweep + due crons. Returns counters."""
        now = now or _now()
        session: Session = self._session_factory()
        try:
            sla_handled = run_all_igrejas(session, self._engine, now)
            crons_run = run_due_crons(
                session, engine=self._engine, now=now, last_run=self._last_run
            )
        finally:
            session.close()
        return {"sla_handled": sla_handled, "crons_run": crons_run}

    def run(self) -> None:
        """Block ticking on the configured interval until stopped."""
        self._running = True
        logger.info("Cron worker started (tick=%ss)", self._tick_seconds)
        while self._running:
            try:
                counters = self.tick()
                logger.info(
                    "Cron tick done (sla=%d, crons=%d)",
                    counters["sla_handled"],
                    counters["crons_run"],
                )
            except Exception:  # noqa: BLE001 - never let a tick kill the loop
                logger.exception("Cron tick failed")
            # Sleep in small slices so shutdown stays responsive.
            slept = 0
            while self._running and slept < self._tick_seconds:
                time.sleep(min(1, self._tick_seconds - slept))
                slept += 1
        logger.info("Cron worker stopped")


def main() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = CronWorker()
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run()


if __name__ == "__main__":  # pragma: no cover
    main()
