"""Semantic separation and sanitization for liveness/readiness."""

from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.services.readiness import ReadinessReport, collect_readiness


def _settings(*, evolution_url: str = "http://evolution-api:8080"):
    return SimpleNamespace(
        redis_url="redis://redis:6379/0",
        evolution_api_url=evolution_url,
        evolution_api_key="secret-evolution-key",
    )


def _install_probes(monkeypatch, *, database=None, redis=None, evolution=None):
    import app.services.readiness as readiness

    monkeypatch.setattr(readiness, "_check_database", database or (lambda: None))
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
    assert report.optional == {"evolution": "ok"}
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
        time.sleep(0.05)

    _install_probes(monkeypatch, evolution=slow_evolution)

    async def run_probe():
        started = time.perf_counter()
        report = await collect_readiness(_settings(), timeout_seconds=0.001)
        elapsed = time.perf_counter() - started
        # Let the cancelled to_thread call finish before asyncio.run shuts its
        # executor down; the endpoint itself already returned at ``elapsed``.
        await asyncio.sleep(0.06)
        return report, elapsed

    report, elapsed = asyncio.run(run_probe())

    assert elapsed < 0.04
    assert report.status == "degraded"
    assert report.http_status == 200
    assert report.optional["evolution"] == "timeout"


def test_dependency_timeouts_run_concurrently(monkeypatch) -> None:
    def slow(*_args) -> None:
        time.sleep(0.05)

    _install_probes(monkeypatch, database=slow, redis=slow, evolution=slow)

    async def run_probes():
        started = time.perf_counter()
        report = await collect_readiness(_settings(), timeout_seconds=0.001)
        elapsed = time.perf_counter() - started
        await asyncio.sleep(0.06)
        return report, elapsed

    report, elapsed = asyncio.run(run_probes())

    assert elapsed < 0.04
    assert report.status == "not_ready"
    assert set(report.required.values()) == {"timeout"}
    assert report.optional == {"evolution": "timeout"}


def test_disabled_evolution_is_not_a_failure(monkeypatch) -> None:
    _install_probes(
        monkeypatch,
        evolution=lambda _settings: (_ for _ in ()).throw(
            AssertionError("disabled probe must not run")
        ),
    )

    report = asyncio.run(collect_readiness(_settings(evolution_url="")))

    assert report.status == "ready"
    assert report.optional == {"evolution": "disabled"}


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
