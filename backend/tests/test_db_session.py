"""Focused regression coverage for the application database engine."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import InvalidatePoolError

from app.db import session as session_module

_DATABASE_URL = "postgresql+psycopg2://app:private-test-value@db.invalid/app"


def _capture_engine(monkeypatch, *, idle_seconds: float):
    """Build the engine against fakes; return (create_engine kwargs, listeners)."""
    engine = SimpleNamespace(dialect=object())
    captured: dict[str, object] = {"calls": 0}
    listeners: list[tuple[object, str, object]] = []

    def fake_create_engine(url: str, **kwargs):
        captured["calls"] = int(captured["calls"]) + 1
        captured["url"] = url
        captured["kwargs"] = kwargs
        return engine

    monkeypatch.setattr(
        session_module,
        "get_settings",
        lambda: SimpleNamespace(
            database_url=_DATABASE_URL, db_pool_ping_idle_seconds=idle_seconds
        ),
    )
    monkeypatch.setattr(session_module, "create_engine", fake_create_engine)
    monkeypatch.setattr(
        session_module.event,
        "listen",
        lambda target, name, fn: listeners.append((target, name, fn)),
    )
    monkeypatch.setattr(session_module, "_engine", None)
    return engine, captured, listeners


def test_get_engine_bounds_pool_and_pings_only_idle_connections(
    monkeypatch, caplog
) -> None:
    engine, captured, listeners = _capture_engine(monkeypatch, idle_seconds=60)

    with caplog.at_level(logging.DEBUG):
        assert session_module.get_engine() is engine
        assert session_module.get_engine() is engine

    assert captured["calls"] == 1
    assert captured["url"] == _DATABASE_URL
    assert captured["kwargs"] == {
        "pool_pre_ping": False,
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 5,
        "pool_recycle": 1800,
        "connect_args": {
            "connect_timeout": 5,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
        },
        "future": True,
    }
    assert [(target, name) for target, name, _ in listeners] == [
        (engine, "checkin"),
        (engine, "checkout"),
        (engine, "before_cursor_execute"),
        (engine, "after_cursor_execute"),
        (engine, "handle_error"),
        (engine, "checkout"),
        (engine, "checkin"),
        (engine, "invalidate"),
        (engine, "detach"),
    ]
    assert "private-test-value" not in caplog.text


def test_zero_idle_seconds_keeps_ping_on_every_checkout(monkeypatch) -> None:
    engine, captured, listeners = _capture_engine(monkeypatch, idle_seconds=0)

    assert session_module.get_engine() is engine

    assert captured["kwargs"]["pool_pre_ping"] is True
    assert [name for _, name, _ in listeners] == [
        "before_cursor_execute", "after_cursor_execute", "handle_error",
        "checkout", "checkin", "invalidate", "detach",
    ]


def test_get_engine_installs_timing_listeners_only_on_its_own_engine(monkeypatch) -> None:
    engine, captured, listeners = _capture_engine(monkeypatch, idle_seconds=60)

    session_module.get_engine()
    session_module.get_engine()

    assert captured["calls"] == 1
    assert [name for _, name, _ in listeners] == [
        "checkin", "checkout",  # Existing idle-ping contract, before timing.
        "before_cursor_execute", "after_cursor_execute", "handle_error",
        "checkout", "checkin", "invalidate", "detach",
    ]
    assert all(target is engine for target, _, _ in listeners)


class _DbapiError(Exception):
    pass


class _FakeDialect:
    loaded_dbapi = SimpleNamespace(Error=_DbapiError)

    def __init__(self, *, error: Exception | None = None, disconnect: bool = True):
        self.pings = 0
        self._error = error
        self._disconnect = disconnect

    def do_ping(self, _dbapi_connection) -> bool:
        self.pings += 1
        if self._error is not None:
            raise self._error
        return True

    def is_disconnect(self, _error, _connection, _cursor) -> bool:
        return self._disconnect


def _install(monkeypatch, dialect: _FakeDialect, *, idle_seconds: float = 60):
    listeners: dict[str, object] = {}
    monkeypatch.setattr(
        session_module.event,
        "listen",
        lambda _target, name, fn: listeners.__setitem__(name, fn),
    )
    session_module._install_idle_pre_ping(
        SimpleNamespace(dialect=dialect), idle_seconds
    )
    return listeners["checkin"], listeners["checkout"]


def test_idle_ping_skips_fresh_and_recent_connections(monkeypatch) -> None:
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(session_module.time, "monotonic", lambda: clock.now)
    dialect = _FakeDialect()
    checkin, checkout = _install(monkeypatch, dialect)
    record = SimpleNamespace(info={})

    checkout("dbapi", record, None)  # fresh: connect itself proved the link
    checkin("dbapi", record)
    clock.now += 59.9
    checkout("dbapi", record, None)  # reused within the window

    assert dialect.pings == 0


def test_idle_ping_pings_connection_idle_past_threshold(monkeypatch) -> None:
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(session_module.time, "monotonic", lambda: clock.now)
    dialect = _FakeDialect()
    checkin, checkout = _install(monkeypatch, dialect)
    record = SimpleNamespace(info={})

    checkin("dbapi", record)
    clock.now += 60
    checkout("dbapi", record, None)

    assert dialect.pings == 1


def test_idle_ping_disconnect_invalidates_pool(monkeypatch) -> None:
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(session_module.time, "monotonic", lambda: clock.now)
    dialect = _FakeDialect(error=_DbapiError("server closed the connection"))
    checkin, checkout = _install(monkeypatch, dialect)
    record = SimpleNamespace(info={})

    checkin("dbapi", record)
    clock.now += 120
    # SQLAlchemy discards the pool's older connections and retries the
    # checkout on a fresh one, as pool_pre_ping does.
    with pytest.raises(InvalidatePoolError):
        checkout("dbapi", record, None)


def test_idle_ping_non_disconnect_error_propagates(monkeypatch) -> None:
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(session_module.time, "monotonic", lambda: clock.now)
    error = _DbapiError("permission denied")
    dialect = _FakeDialect(error=error, disconnect=False)
    checkin, checkout = _install(monkeypatch, dialect)
    record = SimpleNamespace(info={})

    checkin("dbapi", record)
    clock.now += 120
    with pytest.raises(_DbapiError) as raised:
        checkout("dbapi", record, None)
    assert raised.value is error
