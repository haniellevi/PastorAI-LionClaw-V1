"""Semantic separation and sanitization for liveness/readiness."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.services.readiness import ReadinessReport, collect_readiness


def _settings(*, evolution_url: str = "http://evolution-api:8080"):
    return SimpleNamespace(
        redis_url="redis://redis:6379/0",
        evolution_api_url=evolution_url,
        evolution_api_key="secret-evolution-key",
    )


@pytest.fixture(autouse=True)
def _isolate_probe_runtime(monkeypatch):
    """Do not reuse worker threads across the event loop created by each test."""
    import app.services.readiness as readiness

    executor = ThreadPoolExecutor(max_workers=readiness._PROBE_CONCURRENCY_LIMIT)
    monkeypatch.setattr(readiness, "_PROBE_EXECUTOR", executor)
    monkeypatch.setattr(
        readiness,
        "_PROBE_SLOTS",
        threading.BoundedSemaphore(readiness._PROBE_CONCURRENCY_LIMIT),
    )
    yield
    executor.shutdown(wait=True, cancel_futures=True)


def _install_probes(monkeypatch, *, database=None, redis=None, evolution=None):
    import app.services.readiness as readiness

    monkeypatch.setattr(
        readiness,
        "_check_database",
        database or (lambda: None),
    )
    monkeypatch.setattr(
        readiness,
        "_check_redis_and_workers",
        redis
        or (
            lambda _settings: {
                "queue-worker": "ready",
                "cron-worker": "running",
                "broadcast-worker": "idle",
            }
        ),
    )
    monkeypatch.setattr(
        readiness,
        "_check_evolution",
        evolution or (lambda _settings: None),
    )


def test_all_required_dependencies_ready_and_idle_optional_worker_is_healthy(
    monkeypatch,
) -> None:
    _install_probes(monkeypatch)

    report = asyncio.run(collect_readiness(_settings()))

    assert report.status == "ready"
    assert report.http_status == 200
    assert report.required == {"database": "ok", "redis": "ok"}
    assert report.optional == {
        "evolution": "ok",
        "billing_operations": "ok",
    }
    assert report.workers == {
        "queue-worker": "ok",
        "cron-worker": "ok",
        "broadcast-worker": "ok",
    }


def test_required_database_failure_returns_503_without_secret_leak(
    monkeypatch, caplog
) -> None:
    def fail_database() -> None:
        raise RuntimeError("probe credential super-secret-value")

    _install_probes(monkeypatch, database=fail_database)

    with caplog.at_level(logging.WARNING, logger="pastorai.readiness"):
        report = asyncio.run(collect_readiness(_settings()))

    assert report.status == "not_ready"
    assert report.http_status == 503
    assert report.required["database"] == "unavailable"
    assert "super-secret-value" not in str(report.public_payload())
    assert "super-secret-value" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


def test_required_redis_failure_hides_worker_detail_and_returns_503(
    monkeypatch,
) -> None:
    def fail_redis(_settings) -> None:
        raise ConnectionError("redis://user:secret@redis.internal/0")

    _install_probes(monkeypatch, redis=fail_redis)

    report = asyncio.run(collect_readiness(_settings()))

    assert report.status == "not_ready"
    assert report.http_status == 503
    assert report.required["redis"] == "unavailable"
    assert set(report.workers.values()) == {"unknown"}
    assert "redis.internal" not in str(report.public_payload())


def test_optional_evolution_failure_is_degraded_but_still_200(monkeypatch) -> None:
    def fail_evolution(_settings) -> None:
        raise RuntimeError("optional provider unavailable")

    _install_probes(monkeypatch, evolution=fail_evolution)

    report = asyncio.run(collect_readiness(_settings()))

    assert report.status == "degraded"
    assert report.http_status == 200
    assert report.required_failures == 0
    assert report.optional["evolution"] == "unavailable"


def test_optional_evolution_timeout_is_bounded_and_degraded(monkeypatch) -> None:
    def slow_evolution(_settings) -> None:
        time.sleep(0.2)

    _install_probes(monkeypatch, evolution=slow_evolution)

    async def run_probe():
        started = time.perf_counter()
        report = await collect_readiness(_settings(), timeout_seconds=0.05)
        elapsed = time.perf_counter() - started
        # Let the cancelled to_thread call finish before asyncio.run shuts its
        # executor down; the endpoint itself already returned at ``elapsed``.
        await asyncio.sleep(0.21)
        return report, elapsed

    report, elapsed = asyncio.run(run_probe())

    assert elapsed < 0.15
    assert report.status == "degraded"
    assert report.http_status == 200
    assert report.optional["evolution"] == "timeout"


def test_dependency_timeouts_run_concurrently(monkeypatch) -> None:
    def slow(*_args) -> None:
        time.sleep(0.3)

    _install_probes(monkeypatch, database=slow, redis=slow, evolution=slow)

    async def run_probes():
        started = time.perf_counter()
        report = await collect_readiness(_settings(), timeout_seconds=0.05)
        elapsed = time.perf_counter() - started
        await asyncio.sleep(0.31)
        return report, elapsed

    report, elapsed = asyncio.run(run_probes())

    # Three sequential 50 ms deadlines would take at least 150 ms. The probes
    # are launched together and must return comfortably below that bound.
    assert elapsed < 0.12
    assert report.status == "not_ready"
    assert set(report.required.values()) == {"timeout"}
    assert report.optional == {
        "evolution": "timeout",
        "billing_operations": "unknown",
    }


def test_database_probe_sets_driver_deadlines(monkeypatch) -> None:
    import app.services.readiness as readiness

    seen: dict[str, object] = {"sql": []}

    class _Url:
        query = {"sslmode": "require"}

        @staticmethod
        def translate_connect_args(**names):
            seen["translated_names"] = names
            return {
                "host": "db.internal",
                names["username"]: "app_user",
                names["database"]: "app",
            }

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql):
            seen["sql"].append(sql)

        def fetchone(self):
            return (1,) if len(seen["sql"]) == 1 else (False,)

    class _Connection:
        closed = False

        @staticmethod
        def cursor():
            return _Cursor()

        def close(self):
            self.closed = True

    connection = _Connection()
    monkeypatch.setattr(readiness, "get_engine", lambda: SimpleNamespace(url=_Url()))
    monkeypatch.setattr(
        readiness.psycopg2,
        "connect",
        lambda **kwargs: seen.update(kwargs) or connection,
    )

    readiness._check_database()

    assert seen["connect_timeout"] == readiness._DATABASE_CONNECT_TIMEOUT_SECONDS
    assert (
        f"statement_timeout={readiness._DATABASE_STATEMENT_TIMEOUT_SECONDS * 1000}"
        in str(seen["options"])
    )
    assert seen["sslmode"] == "require"
    assert seen["user"] == "app_user"
    assert seen["dbname"] == "app"
    assert seen["translated_names"] == {
        "username": "user",
        "database": "dbname",
    }
    assert seen["sql"][0] == "SELECT 1"
    assert "billing_payment_operations" in seen["sql"][1]
    assert "billing_subscription_operations" in seen["sql"][1]
    assert connection.closed is True


def test_default_probe_budget_covers_database_driver_deadlines() -> None:
    import app.services.readiness as readiness

    driver_budget = (
        readiness._DATABASE_CONNECT_TIMEOUT_SECONDS
        + readiness._DATABASE_STATEMENT_TIMEOUT_SECONDS
    )

    assert readiness._DATABASE_PROBE_TIMEOUT_SECONDS > driver_budget


def test_database_gets_extended_budget_without_relaxing_other_probes(
    monkeypatch,
) -> None:
    import app.services.readiness as readiness

    seen: dict[str, float] = {}

    async def capture_probe(name, _probe, *, timeout_seconds):
        seen[name] = timeout_seconds
        payload = (
            {
                "queue-worker": "ready",
                "cron-worker": "running",
                "broadcast-worker": "idle",
            }
            if name == "redis"
            else None
        )
        return "ok", payload

    monkeypatch.setattr(readiness, "_bounded_probe", capture_probe)

    report = asyncio.run(collect_readiness(_settings()))

    assert report.status == "ready"
    assert seen == {
        "database": readiness._DATABASE_PROBE_TIMEOUT_SECONDS,
        "redis": readiness._PROBE_TIMEOUT_SECONDS,
        "evolution": readiness._PROBE_TIMEOUT_SECONDS,
    }


def test_slow_healthy_database_beyond_general_timeout_is_ready(monkeypatch) -> None:
    import app.services.readiness as readiness

    def slow_database() -> None:
        # Exercise the production incident boundary: a healthy Supavisor
        # connection that takes longer than the normal dependency budget.
        time.sleep(readiness._PROBE_TIMEOUT_SECONDS + 0.1)

    _install_probes(monkeypatch, database=slow_database)

    report = asyncio.run(collect_readiness(_settings()))

    assert report.status == "ready"
    assert report.http_status == 200


def test_repeated_timeouts_have_strict_concurrency_limit_and_recover(
    monkeypatch,
) -> None:
    import app.services.readiness as readiness

    release = threading.Event()
    counter_lock = threading.Lock()
    active = 0
    max_active = 0

    def slow(*_args) -> None:
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            release.wait(timeout=1)
        finally:
            with counter_lock:
                active -= 1

    _install_probes(monkeypatch, database=slow, redis=slow, evolution=slow)
    slots = threading.BoundedSemaphore(3)
    monkeypatch.setattr(readiness, "_PROBE_SLOTS", slots)

    async def exercise():
        reports = await asyncio.gather(
            *(collect_readiness(_settings(), timeout_seconds=0.001) for _ in range(8))
        )
        release.set()
        for _ in range(100):
            acquired = 0
            while acquired < 3 and slots.acquire(blocking=False):
                acquired += 1
            for _slot in range(acquired):
                slots.release()
            if acquired == 3:
                break
            await asyncio.sleep(0.01)
        assert acquired == 3
        _install_probes(monkeypatch)
        recovered = await collect_readiness(_settings(), timeout_seconds=0.1)
        return reports, recovered

    reports, recovered = asyncio.run(exercise())

    assert max_active <= 3
    assert any(
        "busy" in set(report.required.values()) | set(report.optional.values())
        for report in reports
    )
    assert recovered.status == "ready", recovered.public_payload()


def test_cancelled_queued_probe_releases_exact_slot_and_recovers(
    monkeypatch,
) -> None:
    import app.services.readiness as readiness

    executor_blocked = threading.Event()
    release_executor = threading.Event()
    probe_started = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1)

    def occupy_executor() -> None:
        executor_blocked.set()
        release_executor.wait(timeout=2)

    blocker = executor.submit(occupy_executor)
    assert executor_blocked.wait(timeout=1)
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(readiness, "_PROBE_EXECUTOR", executor)
    monkeypatch.setattr(readiness, "_PROBE_SLOTS", slots)

    async def exercise() -> None:
        for index in range(3):
            task = asyncio.create_task(
                readiness._bounded_probe(  # noqa: SLF001
                    f"queued-{index}",
                    lambda: probe_started.set(),
                    timeout_seconds=1,
                )
            )
            await asyncio.sleep(0)
            assert slots.acquire(blocking=False) is False
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert slots.acquire(blocking=False) is True
            slots.release()

        result = await readiness._bounded_probe(  # noqa: SLF001
            "queued-recovery",
            lambda: "should-not-run-yet",
            timeout_seconds=0.001,
        )
        assert result[0] == "timeout"

    try:
        asyncio.run(exercise())
        assert probe_started.is_set() is False
    finally:
        release_executor.set()
        blocker.result(timeout=1)
        executor.shutdown(wait=True, cancel_futures=True)


def test_cancelled_running_probe_holds_slot_until_real_completion(
    monkeypatch,
) -> None:
    import app.services.readiness as readiness

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1)
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(readiness, "_PROBE_EXECUTOR", executor)
    monkeypatch.setattr(readiness, "_PROBE_SLOTS", slots)

    def running_probe() -> None:
        started.set()
        try:
            release.wait(timeout=2)
        finally:
            finished.set()

    async def wait_for_event(event: threading.Event) -> bool:
        for _ in range(100):
            if event.is_set():
                return True
            await asyncio.sleep(0.01)
        return event.is_set()

    async def exercise() -> None:
        task = asyncio.create_task(
            readiness._bounded_probe(  # noqa: SLF001
                "running",
                running_probe,
                timeout_seconds=1,
            )
        )
        assert await wait_for_event(started)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        busy = await readiness._bounded_probe(  # noqa: SLF001
            "busy-while-running",
            lambda: None,
            timeout_seconds=0.1,
        )
        assert busy == ("busy", None)

        release.set()
        assert await wait_for_event(finished)
        for _ in range(10):
            recovered = await readiness._bounded_probe(  # noqa: SLF001
                "running-recovery",
                lambda: "ok",
                timeout_seconds=0.1,
            )
            if recovered == ("ok", "ok"):
                break
            await asyncio.sleep(0)
        assert recovered == ("ok", "ok")

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_disabled_evolution_is_not_a_failure(monkeypatch) -> None:
    _install_probes(
        monkeypatch,
        evolution=lambda _settings: (_ for _ in ()).throw(
            AssertionError("disabled probe must not run")
        ),
    )

    report = asyncio.run(collect_readiness(_settings(evolution_url="")))

    assert report.status == "ready"
    assert report.optional == {
        "evolution": "disabled",
        "billing_operations": "ok",
    }


def test_stale_billing_operation_degrades_readiness(monkeypatch) -> None:
    _install_probes(
        monkeypatch,
        database=lambda: {"billing_operations": "stale"},
    )

    report = asyncio.run(collect_readiness(_settings()))

    assert report.status == "degraded"
    assert report.http_status == 200
    assert report.optional["billing_operations"] == "stale"


def test_health_remains_live_when_readiness_is_not_ready(monkeypatch, app) -> None:
    import app.main as main

    async def not_ready():
        return ReadinessReport(
            status="not_ready",
            required={"database": "unavailable", "redis": "ok"},
            optional={"evolution": "ok"},
            workers={
                "queue-worker": "ok",
                "cron-worker": "ok",
                "broadcast-worker": "ok",
            },
        )

    monkeypatch.setattr(main, "collect_readiness", not_ready)
    client = TestClient(app)

    liveness = client.get("/health")
    readiness = client.get("/ready", headers={"X-Request-ID": "ready-test"})

    assert liveness.status_code == 200
    assert liveness.json() == {"status": "ok"}
    assert readiness.status_code == 503
    assert readiness.headers["x-request-id"] == "ready-test"
    assert readiness.json()["status"] == "not_ready"
