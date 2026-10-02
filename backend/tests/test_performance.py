"""Synthetic instrumentation tests; no shared DB, provider or tenant data."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, TimeoutError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app import performance


@pytest.fixture
def measured_database():
    # An ephemeral in-memory DB exercises actual public SQLAlchemy events. No
    # application schema or RLS assertions are substituted by this fixture.
    engine = create_engine(
        "sqlite://", poolclass=QueuePool, pool_size=1, max_overflow=0,
        pool_timeout=0.02, connect_args={"check_same_thread": False},
    )
    performance.instrument_engine(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    performance.instrument_session_factory(factory)
    try:
        yield engine, factory
    finally:
        engine.dispose()


def test_execute_checkout_and_checkin_measure_actual_work(measured_database):
    _engine, factory = measured_database

    with performance.capture_request(sampled=True) as timing:
        with factory() as db:
            assert db.execute(text("SELECT :private_value"), {"private_value": "SYNTHETIC-PRIVATE"}).scalar_one() == "SYNTHETIC-PRIVATE"
            assert db.execute(text("SELECT 2")).scalar_one() == 2

    values = timing.snapshot()
    assert values["sql_count"] == 2
    assert values["db_acquire_count"] == 1
    assert values["db_checkout_count"] == values["db_hold_count"] == 1
    assert values["sql_ms"] > 0
    assert values["db_acquire_ms"] > 0
    assert values["db_hold_ms"] >= values["sql_ms"]
    assert "SYNTHETIC-PRIVATE" not in repr(values)


def test_unsampled_and_outside_request_work_has_no_payload_buffers(measured_database):
    _engine, factory = measured_database
    with factory() as db:
        assert db.execute(text("SELECT 1")).scalar_one() == 1
    with performance.capture_request(sampled=False) as timing:
        with factory() as db:
            assert db.execute(text("SELECT 2")).scalar_one() == 2
        with performance.timed_span("provider"):
            pass
    assert timing.snapshot() == {}


def test_failed_sql_finishes_measurement_and_does_not_contaminate_next_query(measured_database):
    _engine, factory = measured_database
    with performance.capture_request(sampled=True) as timing:
        with factory() as db:
            with pytest.raises(OperationalError):
                db.execute(text("SELECT nonexistent_column"))
        with factory() as db:
            assert db.execute(text("SELECT 3")).scalar_one() == 3
    assert timing.snapshot()["sql_count"] == 2
    assert timing.snapshot()["sql_errors"] == 1
    assert timing.snapshot()["db_acquire_count"] == 2
    assert timing.snapshot()["db_hold_count"] == 2


def test_pool_exhaustion_is_timed_and_counted_as_a_failure(measured_database):
    engine, factory = measured_database
    held = engine.connect()
    try:
        with performance.capture_request(sampled=True) as timing:
            with factory() as db:
                with pytest.raises(TimeoutError):
                    db.execute(text("SELECT 1"))
        values = timing.snapshot()
        assert values["db_acquire_errors"] == values["db_acquire_count"] == 1
        assert values["db_acquire_ms"] >= 15
        assert values.get("sql_count", 0) == values.get("db_checkout_count", 0) == 0
    finally:
        held.close()


def test_span_context_propagates_to_thread_and_resets():
    with performance.capture_request(sampled=True) as first:
        def execute():
            with performance.timed_span("auth"):
                with performance.timed_span("provider"):
                    raise ValueError("SYNTHETIC-PRIVATE")

        with ThreadPoolExecutor(max_workers=1) as executor:
            with pytest.raises(ValueError):
                executor.submit(copy_context().run, execute).result()
    with performance.capture_request(sampled=True) as second:
        with performance.timed_span("auth"):
            pass
    assert first.snapshot()["auth_errors"] == first.snapshot()["provider_errors"] == 1
    assert second.snapshot()["auth_count"] == 1
    assert "auth_errors" not in second.snapshot()
    with pytest.raises(ValueError, match="unsupported performance span"):
        with performance.timed_span("user-SYNTHETIC-PRIVATE"):
            pass


def test_late_checkin_never_attaches_previous_lease_to_a_new_request(measured_database):
    engine, _factory = measured_database
    with performance.capture_request(sampled=True) as first:
        connection = engine.connect()
    with performance.capture_request(sampled=True) as second:
        connection.close()
    assert first.snapshot()["db_checkout_count"] == 1
    assert first.snapshot().get("db_hold_count", 0) == 0  # Explicit missing coverage.
    assert second.snapshot() == {}


def test_histograms_include_failed_requests_and_keep_sample_denominators():
    registry = performance.PerformanceRegistry()
    with performance.capture_request(sampled=False) as timing:
        registry.observe("/cells", "GET", 503, 1500, timing)
    with performance.capture_request(sampled=True) as timing:
        timing.add("db_checkout_count")  # No acquisition start or completed hold.
        registry.observe("/cells", "GET", 200, 100, timing)
    rows = registry.snapshot()
    failure = next(row for row in rows if row["status_class"] == "5xx")
    success = next(row for row in rows if row["status_class"] == "2xx")
    assert failure["request_ms"]["count"] == failure["read_budget_exceeded"] == 1
    assert failure["sample_count"] == 0
    assert "sql_ms" not in failure
    assert success["sample_count"] == 1
    assert "db_acquire_ms" not in success and "db_hold_ms" not in success
    assert success["db_checkout_count"] == 1
    assert sum(sum(row["request_ms"]["buckets"]) for row in rows) == 2
    success["request_ms"]["buckets"][0] = 999
    assert registry.snapshot() != rows


def test_asgi_cleanup_records_hold_and_normalizes_private_paths(measured_database, monkeypatch, caplog):
    from app.main import create_app
    _engine, factory = measured_database
    monkeypatch.setattr(performance, "should_sample", lambda: True)
    local_app = create_app()

    def dependency():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    @local_app.get("/_test/private/{item_id}")
    def endpoint(item_id: str, db: Session = Depends(dependency)):
        with performance.timed_span("auth"):
            assert db.execute(text("SELECT 1")).scalar_one() == 1
        return {"ok": True}

    with caplog.at_level(logging.INFO, logger="pastorai"):
        client = TestClient(local_app)
        for identifier in ("SYNTHETIC-PRIVATE-A", "SYNTHETIC-PRIVATE-B"):
            response = client.get(f"/_test/private/{identifier}?token=SYNTHETIC-PRIVATE")
            assert response.status_code == 200
            assert ", sql;dur=" in response.headers["server-timing"]
    row, = local_app.state.performance.snapshot()
    assert row["route"] == "/_test/private/{item_id}"
    assert row["request_ms"]["count"] == row["sample_count"] == 2
    assert row["db_checkout_count"] == row["db_hold_count"] == 2
    assert row["auth_ms"]["count"] == 2
    messages = "\n".join(record.message for record in caplog.records if record.name == "pastorai")
    assert "SYNTHETIC-PRIVATE" not in messages
    assert "SELECT" not in messages


def test_asgi_failure_is_counted_without_exception_payload(monkeypatch, caplog):
    from app.main import create_app
    monkeypatch.setattr(performance, "should_sample", lambda: True)
    local_app = create_app()

    @local_app.get("/_test/error")
    def endpoint():
        raise ValueError("SYNTHETIC-PRIVATE")

    with caplog.at_level(logging.INFO, logger="pastorai"):
        response = TestClient(local_app, raise_server_exceptions=False).get("/_test/error")
    row, = local_app.state.performance.snapshot()
    assert response.status_code == 500
    assert response.headers["x-backend-release"] == "unknown"
    assert row["status_class"] == "5xx" and row["request_ms"]["count"] == 1
    messages = "\n".join(record.message for record in caplog.records if record.name == "pastorai")
    assert "SYNTHETIC-PRIVATE" not in messages
    assert "ValueError" in messages


def test_unknown_urls_and_methods_do_not_create_unbounded_labels(monkeypatch):
    from app.main import create_app
    monkeypatch.setattr(performance, "should_sample", lambda: False)
    local_app = create_app()
    client = TestClient(local_app)
    for index in range(20):
        assert client.get(f"/_test/unknown/{index}").status_code == 404
        assert client.request(f"PRIVATE-{index}", f"/_test/unknown/{index}").status_code == 404
    rows = local_app.state.performance.snapshot()
    assert len(rows) == 2
    assert {row["route"] for row in rows} == {"<unmatched>"}
    assert {row["method"] for row in rows} == {"GET", "<other>"}
    assert sum(row["request_ms"]["count"] for row in rows) == 40


@pytest.mark.parametrize("value,expected", [
    ("a" * 40, "a" * 40), ("A" * 40, "unknown"),
    ("SYNTHETIC-PRIVATE\n", "unknown"), ("", "unknown"),
])
def test_release_headers_use_only_explicit_valid_backend_revision(monkeypatch, value, expected):
    from app.main import create_app
    monkeypatch.setenv("PASTORAI_RELEASE_SHA", value)
    local_app = create_app()
    response = TestClient(local_app).get("/health")
    assert response.headers["x-backend-release"] == expected
    assert local_app.state.performance.snapshot()[0]["release"] == expected
