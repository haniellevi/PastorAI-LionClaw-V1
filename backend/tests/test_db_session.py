"""Focused regression coverage for the application database engine."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from app.db import session as session_module


def test_get_engine_bounds_pool_checkout_and_postgres_connect(
    monkeypatch, caplog
) -> None:
    database_url = "postgresql+psycopg2://app:private-test-value@db.invalid/app"
    sentinel = object()
    captured: dict[str, object] = {}
    create_calls = 0

    def fake_create_engine(url: str, **kwargs):
        nonlocal create_calls
        create_calls += 1
        captured["url"] = url
        captured["kwargs"] = kwargs
        return sentinel

    monkeypatch.setattr(
        session_module,
        "get_settings",
        lambda: SimpleNamespace(database_url=database_url),
    )
    monkeypatch.setattr(session_module, "create_engine", fake_create_engine)
    monkeypatch.setattr(session_module, "_engine", None)

    with caplog.at_level(logging.DEBUG):
        assert session_module.get_engine() is sentinel
        assert session_module.get_engine() is sentinel

    assert create_calls == 1
    assert captured["url"] == database_url
    assert captured["kwargs"] == {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 5,
        "pool_recycle": 1800,
        "connect_args": {"connect_timeout": 5},
        "future": True,
    }
    assert "private-test-value" not in caplog.text
