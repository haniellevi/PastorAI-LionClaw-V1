"""Dedicated persistent worker for scheduled and immediate broadcasts."""

from __future__ import annotations

import datetime as dt
import logging
import os
import signal
import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_session_factory
from app.services.broadcast_delivery import (
    BroadcastCycleStats,
    run_delivery_cycle,
)
from app.services.evolution import EvolutionClient

logger = logging.getLogger("pastorai.broadcast_worker")

CycleRunner = Callable[..., BroadcastCycleStats]
SessionFactory = Callable[[], Session]


class BroadcastWorker:
    """Long-running broadcast dispatcher with a boot-time activation gate.

    When ``BROADCAST_ASYNC_ENABLED`` is false the process remains alive and
    idle. It never exits just because the flag is off, avoiding a restart loop
    under ``restart: always``. Changing the flag requires recreating the
    process, matching the cached settings lifecycle used by the application.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        evolution: EvolutionClient | None = None,
        settings: Any | None = None,
        cycle_runner: CycleRunner = run_delivery_cycle,
        sleeper: Callable[[float], None] = time.sleep,
        worker_id: str | None = None,
        tick_seconds: int | None = None,
    ) -> None:
        boot_settings = settings or get_settings()
        self._enabled = bool(
            getattr(boot_settings, "broadcast_async_enabled", False)
        ) and bool(getattr(boot_settings, "external_sends_enabled", False))
        configured_tick = getattr(
            boot_settings, "broadcast_worker_tick_seconds", 10
        )
        self._tick_seconds = max(
            1, int(configured_tick if tick_seconds is None else tick_seconds)
        )
        self._max_broadcasts = max(
            1,
            int(
                getattr(
                    boot_settings,
                    "broadcast_max_broadcasts_por_ciclo",
                    20,
                )
            ),
        )
        self._max_deliveries = max(
            1,
            int(
                getattr(
                    boot_settings,
                    "broadcast_max_entregas_por_ciclo",
                    200,
                )
            ),
        )
        self._max_attempts = max(
            1, int(getattr(boot_settings, "broadcast_max_tentativas", 3))
        )
        self._claim_seconds = max(
            1, int(getattr(boot_settings, "broadcast_claim_seconds", 60))
        )
        self._lease_seconds = max(
            1,
            int(
                getattr(
                    boot_settings,
                    "broadcast_entrega_lease_seconds",
                    120,
                )
            ),
        )
        self._send_interval_ms = max(
            0, int(getattr(boot_settings, "broadcast_send_interval_ms", 1000))
        )
        # Resolve the DB factory lazily so an accidentally started, disabled
        # worker can stay healthy without touching the database at all.
        self._session_factory = session_factory
        self._evolution = evolution or EvolutionClient(boot_settings)
        self._cycle_runner = cycle_runner
        self._sleeper = sleeper
        self._worker_id = worker_id or (
            f"broadcast-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        )
        self._running = False
        self._inside_run = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def stop(self, *_: Any) -> None:
        """Request graceful shutdown; an in-flight result is still recorded."""
        logger.info("Broadcast worker shutdown requested")
        self._running = False

    def _should_continue(self) -> bool:
        return self._running if self._inside_run else True

    def tick(self, now: dt.datetime | None = None) -> BroadcastCycleStats:
        """Run one persistent delivery cycle, or a zero-work idle tick."""
        if not self._enabled:
            return BroadcastCycleStats()
        session_factory = self._session_factory or get_session_factory()
        return self._cycle_runner(
            session_factory,
            self._evolution,
            worker_id=self._worker_id,
            now=now,
            max_broadcasts=self._max_broadcasts,
            max_deliveries=self._max_deliveries,
            max_attempts=self._max_attempts,
            claim_seconds=self._claim_seconds,
            lease_seconds=self._lease_seconds,
            send_interval_ms=self._send_interval_ms,
            should_continue=self._should_continue,
        )

    def _sleep_interruptibly(self) -> None:
        remaining = self._tick_seconds
        while self._running and remaining > 0:
            step = min(1, remaining)
            self._sleeper(step)
            remaining -= step

    def run(self) -> None:
        """Stay alive until SIGTERM/SIGINT, processing only when boot-enabled."""
        self._running = True
        self._inside_run = True
        idle_ticks = 0
        logger.info(
            "Broadcast worker started enabled=%s tick=%ss",
            self._enabled,
            self._tick_seconds,
        )
        if not self._enabled:
            logger.warning(
                "Broadcast worker OCIOSO: exige BROADCAST_ASYNC_ENABLED=true "
                "e ALLOW_REAL_SENDS=true; recrie o processo após ativar"
            )

        try:
            while self._running:
                if self._enabled:
                    try:
                        counters = self.tick()
                        logger.info(
                            "Broadcast tick done reaped=%d materialized=%d actions=%d",
                            counters.reaped,
                            counters.materialized,
                            counters.delivery_actions,
                        )
                    except Exception:  # noqa: BLE001 - one tick cannot kill worker
                        logger.exception("Broadcast worker tick failed")
                else:
                    idle_ticks += 1
                    heartbeat_every = max(1, 60 // self._tick_seconds)
                    if idle_ticks % heartbeat_every == 0:
                        logger.info("Broadcast worker idle heartbeat")
                self._sleep_interruptibly()
        finally:
            self._inside_run = False
            logger.info("Broadcast worker stopped")


def main() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = BroadcastWorker()
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run()


if __name__ == "__main__":  # pragma: no cover
    main()
