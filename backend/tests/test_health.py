"""Health endpoint and app boot smoke tests."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, call

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError


def test_health_returns_200(app) -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert resp.headers["x-request-id"]
    assert resp.headers["server-timing"].startswith("app;dur=")


def test_request_id_reuses_only_log_safe_values(app) -> None:
    client = TestClient(app)

    accepted = client.get("/health", headers={"X-Request-ID": "trace-123:child"})
    rejected = client.get("/health", headers={"X-Request-ID": "unsafe value\n"})

    assert accepted.headers["x-request-id"] == "trace-123:child"
    assert rejected.headers["x-request-id"] != "unsafe value\n"
    assert len(rejected.headers["x-request-id"]) == 32


def test_unhandled_500_keeps_observability_headers() -> None:
    from app.main import create_app

    local_app = create_app()

    @local_app.get("/_test/unhandled-error")
    def _boom() -> None:
        raise RuntimeError("test failure")

    client = TestClient(local_app, raise_server_exceptions=False)
    response = client.get(
        "/_test/unhandled-error",
        headers={"X-Request-ID": "trace-unhandled-500"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Erro interno do servidor."}
    assert response.headers["x-request-id"] == "trace-unhandled-500"
    assert response.headers["server-timing"].startswith("app;dur=")


def test_openapi_exposes_login_route(app) -> None:
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    assert "/auth/login" in schema["paths"]


def test_lifespan_warms_database_before_serving_health(monkeypatch) -> None:
    import app.main as main

    engine = MagicMock()
    connection = engine.connect.return_value
    result = connection.exec_driver_sql.return_value
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    local_app = main.create_app()

    with TestClient(local_app) as client:
        engine.connect.assert_called_once_with()
        connection.exec_driver_sql.assert_called_once_with("SELECT 1")
        result.scalar_one.assert_called_once_with()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()
        assert connection.method_calls == [
            call.exec_driver_sql("SELECT 1"),
            call.rollback(),
            call.close(),
        ]
        assert client.get("/health").status_code == 200

    engine.dispose.assert_called_once_with()


@pytest.mark.parametrize(
    "warmup_error",
    [RuntimeError("secret database URL"), SQLAlchemyError("secret database URL")],
    ids=["runtime-error", "sqlalchemy-error"],
)
def test_lifespan_database_warmup_is_best_effort_and_sanitized(
    monkeypatch, caplog, warmup_error
) -> None:
    import app.main as main

    engine = MagicMock()
    engine.connect.side_effect = warmup_error
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    local_app = main.create_app()

    with caplog.at_level(logging.WARNING, logger="pastorai"):
        with TestClient(local_app) as client:
            assert client.get("/health").status_code == 200

    assert "Database warmup unavailable; startup continuing" in caplog.messages
    assert all("secret database URL" not in message for message in caplog.messages)


def test_lifespan_closes_application_clerk_pool(monkeypatch) -> None:
    import app.main as main

    created: list[object] = []
    closed: list[bool] = []

    class FakeClerkClient:
        def __init__(self, *, settings) -> None:
            self.settings = settings
            created.append(self)

        def close(self) -> None:
            closed.append(True)

    engine = MagicMock()
    monkeypatch.setattr(main, "ClerkClient", FakeClerkClient)
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    local_app = main.create_app()

    for _ in range(2):
        with TestClient(local_app) as client:
            assert client.get("/health").status_code == 200

    assert len(created) == 2
    assert created[0] is not created[1]
    assert closed == [True, True]
