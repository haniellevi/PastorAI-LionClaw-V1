"""Lifecycle tests for the dedicated broadcast worker."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from app.services.broadcast_delivery import BroadcastCycleStats
from app.services.broadcast_health import broadcast_worker_ready
from app.workers.broadcast_worker import BroadcastWorker


def _settings(enabled: bool, *, sends_enabled: bool | None = None):
    return SimpleNamespace(
        broadcast_async_enabled=enabled,
        external_sends_enabled=(enabled if sends_enabled is None else sends_enabled),
        broadcast_worker_tick_seconds=1,
        broadcast_max_broadcasts_por_ciclo=5,
        broadcast_max_entregas_por_ciclo=10,
        broadcast_max_tentativas=3,
        broadcast_claim_seconds=60,
        broadcast_entrega_lease_seconds=120,
        broadcast_send_interval_ms=0,
    )


class _ClosingEvolution:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def test_disabled_worker_tick_is_idle_without_db_or_cycle() -> None:
    calls = 0

    def runner(*args, **kwargs):  # pragma: no cover - must stay unused
        nonlocal calls
        calls += 1
        raise AssertionError("disabled worker cannot run a cycle")

    worker = BroadcastWorker(
        settings=_settings(False),
        cycle_runner=runner,
        evolution=object(),
    )

    assert worker.enabled is False
    assert worker.tick() == BroadcastCycleStats()
    assert calls == 0


def test_invalid_redis_url_is_controlled_unavailable() -> None:
    assert broadcast_worker_ready("not-a-redis-url") is False


def test_disabled_worker_stays_alive_and_exits_only_on_stop(caplog) -> None:
    caplog.set_level(logging.INFO)
    holder = {}

    def sleeper(_seconds):
        holder["worker"].stop()

    worker = BroadcastWorker(
        settings=_settings(False),
        cycle_runner=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("disabled worker cannot run a cycle")
        ),
        evolution=object(),
        sleeper=sleeper,
        tick_seconds=1,
        heartbeat_publisher=lambda *_args: None,
    )
    holder["worker"] = worker

    worker.run()

    assert "Broadcast worker OCIOSO" in caplog.text
    assert caplog.text.count("Broadcast worker OCIOSO") == 1
    assert "Broadcast worker stopped" in caplog.text


def test_worker_closes_evolution_it_created(monkeypatch) -> None:
    import app.workers.broadcast_worker as worker_module

    evolution = _ClosingEvolution()
    monkeypatch.setattr(
        worker_module,
        "EvolutionClient",
        lambda _settings: evolution,
    )
    holder = {}

    def sleeper(_seconds):
        holder["worker"].stop()

    worker = BroadcastWorker(
        settings=_settings(False),
        sleeper=sleeper,
        heartbeat_publisher=lambda *_args: None,
    )
    holder["worker"] = worker

    worker.run()

    assert evolution.close_calls == 1


def test_worker_does_not_close_injected_evolution() -> None:
    evolution = _ClosingEvolution()
    holder = {}

    def sleeper(_seconds):
        holder["worker"].stop()

    worker = BroadcastWorker(
        settings=_settings(False),
        evolution=evolution,
        sleeper=sleeper,
        heartbeat_publisher=lambda *_args: None,
    )
    holder["worker"] = worker

    worker.run()

    assert evolution.close_calls == 0


def test_worker_publishes_ready_only_after_successful_tick() -> None:
    heartbeats = []
    holder = {}

    def publish(enabled, ttl):
        heartbeats.append((enabled, ttl))

    def sleeper(_seconds):
        holder["worker"].stop()

    worker = BroadcastWorker(
        settings=_settings(True),
        session_factory=lambda: object(),
        evolution=object(),
        cycle_runner=lambda *args, **kwargs: BroadcastCycleStats(),
        sleeper=sleeper,
        tick_seconds=1,
        heartbeat_publisher=publish,
    )
    holder["worker"] = worker

    worker.run()

    assert heartbeats == [("running", 30), ("ready", 30), ("stopped", 30)]


def test_next_tick_keeps_last_proven_ready_until_a_real_failure(caplog) -> None:
    caplog.set_level(logging.ERROR)
    heartbeats = []
    holder = {}
    cycles = {"count": 0}

    def publish(ready, ttl):
        heartbeats.append((ready, ttl))

    def runner(*args, **kwargs):
        cycles["count"] += 1
        if cycles["count"] == 2:
            assert heartbeats[-1] == ("running", 30)
            raise RuntimeError("database unavailable")
        return BroadcastCycleStats()

    def sleeper(_seconds):
        if cycles["count"] == 2:
            holder["worker"].stop()

    worker = BroadcastWorker(
        settings=_settings(True),
        session_factory=lambda: object(),
        evolution=object(),
        cycle_runner=runner,
        sleeper=sleeper,
        tick_seconds=1,
        heartbeat_publisher=publish,
    )
    holder["worker"] = worker

    worker.run()

    assert heartbeats == [
        ("running", 30),
        ("ready", 30),
        ("running", 30),
        ("error", 30),
        ("stopped", 30),
    ]
    assert "Broadcast worker tick failed" in caplog.text


def test_enabled_worker_pauses_dispatch_when_heartbeat_fails(caplog) -> None:
    caplog.set_level(logging.ERROR)
    holder = {}
    cycles = 0

    def publish(_enabled, _ttl):
        raise RuntimeError("redis unavailable")

    def runner(*args, **kwargs):  # pragma: no cover - must stay unused
        nonlocal cycles
        cycles += 1

    def sleeper(_seconds):
        holder["worker"].stop()

    worker = BroadcastWorker(
        settings=_settings(True),
        session_factory=lambda: object(),
        evolution=object(),
        cycle_runner=runner,
        sleeper=sleeper,
        tick_seconds=1,
        heartbeat_publisher=publish,
    )
    holder["worker"] = worker

    worker.run()

    assert cycles == 0
    assert "dispatch paused: heartbeat unavailable" in caplog.text


def test_failed_tick_stays_unready_until_a_later_tick_succeeds(caplog) -> None:
    caplog.set_level(logging.ERROR)
    heartbeats = []
    holder = {}
    cycles = {"count": 0}

    def publish(ready, ttl):
        heartbeats.append((ready, ttl))

    def sleeper(_seconds):
        if cycles["count"] == 2:
            holder["worker"].stop()

    def runner(*args, **kwargs):
        cycles["count"] += 1
        if cycles["count"] == 1:
            raise RuntimeError("database unavailable")
        return BroadcastCycleStats()

    worker = BroadcastWorker(
        settings=_settings(True),
        session_factory=lambda: object(),
        evolution=object(),
        cycle_runner=runner,
        sleeper=sleeper,
        tick_seconds=1,
        heartbeat_publisher=publish,
    )
    holder["worker"] = worker

    worker.run()

    assert heartbeats == [
        ("running", 30),
        ("error", 30),
        ("running", 30),
        ("ready", 30),
        ("stopped", 30),
    ]
    assert "Broadcast worker tick failed" in caplog.text


def test_enabled_worker_runs_persistent_cycle_with_configured_limits() -> None:
    seen = {}

    def runner(session_factory, evolution, **kwargs):
        seen["session_factory"] = session_factory
        seen["evolution"] = evolution
        seen.update(kwargs)
        return BroadcastCycleStats(reaped=1, materialized=2, delivery_actions=3)

    factory = lambda: object()
    evolution = object()
    worker = BroadcastWorker(
        settings=_settings(True),
        session_factory=factory,
        evolution=evolution,
        cycle_runner=runner,
        worker_id="worker-test",
    )

    result = worker.tick()

    assert result == BroadcastCycleStats(1, 2, 3)
    assert seen["session_factory"] is factory
    assert seen["evolution"] is evolution
    assert seen["worker_id"] == "worker-test"
    assert seen["max_broadcasts"] == 5
    assert seen["max_deliveries"] == 10
    assert seen["max_attempts"] == 3
    assert seen["send_interval_ms"] == 0


def test_async_worker_stays_idle_while_external_sends_are_blocked() -> None:
    worker = BroadcastWorker(
        settings=_settings(True, sends_enabled=False),
        cycle_runner=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("outbound-disabled worker cannot run a cycle")
        ),
        evolution=object(),
    )

    assert worker.enabled is False
    assert worker.tick() == BroadcastCycleStats()


def test_async_flag_is_read_once_at_worker_boot() -> None:
    class SettingsSpy:
        def __init__(self) -> None:
            self.reads = 0
            self.value = False
            self.broadcast_worker_tick_seconds = 1

        @property
        def broadcast_async_enabled(self):
            self.reads += 1
            return self.value

    settings = SettingsSpy()
    worker = BroadcastWorker(
        settings=settings,
        evolution=object(),
        session_factory=lambda: object(),
    )
    settings.value = True

    assert settings.reads == 1
    assert worker.enabled is False
    assert worker.tick() == BroadcastCycleStats()
    assert settings.reads == 1
