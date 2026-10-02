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


def test_requests_have_bounded_histograms_and_explicit_backend_release(app) -> None:
    response = TestClient(app).get("/health")

    assert hasattr(app.state, "performance")
    assert response.headers["x-backend-release"] == "unknown"
    records = app.state.performance.snapshot()
    health = next(item for item in records if item["route"] == "/health")
    assert health["method"] == "GET"
    assert health["status_class"] == "2xx"
    assert health["request_ms"]["count"] >= 1


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


def test_lifespan_shares_and_closes_google_provider_pools(monkeypatch) -> None:
    import app.main as main

    closed = []

    class FakeClient:
        def __init__(self, *, settings) -> None:
            self.settings = settings

        def close(self) -> None:
            closed.append(self)

    monkeypatch.setattr(main, "GoogleOAuthClient", FakeClient, raising=False)
    monkeypatch.setattr(main, "GoogleCalendarClient", FakeClient, raising=False)
    monkeypatch.setattr(main, "get_engine", lambda: MagicMock())
    local_app = main.create_app()

    with TestClient(local_app) as client:
        assert hasattr(local_app.state, "google_oauth_client")
        assert hasattr(local_app.state, "google_calendar_client")
        oauth = local_app.state.google_oauth_client
        calendar = local_app.state.google_calendar_client
        assert client.get("/health").status_code == 200
        assert closed == []

    assert closed == [oauth, calendar]


def test_lifespan_storage_pool_has_no_shared_auth_or_proxy_and_closes(monkeypatch) -> None:
    import app.main as main

    monkeypatch.setattr(main, "get_engine", lambda: MagicMock())
    local_app = main.create_app()

    with TestClient(local_app):
        pool = local_app.state.storage_http_client
        assert pool.is_closed is False
        assert pool.trust_env is False
        assert pool.follow_redirects is False
        assert "authorization" not in pool.headers
        assert "apikey" not in pool.headers
        # A private provider cookie must never be inherited by another request.
        import httpx
        first_request = pool.build_request("GET", "https://synthetic.example.invalid/storage")
        pool.cookies.extract_cookies(httpx.Response(200, request=first_request,
            headers={"set-cookie": "private_session=synthetic; Path=/"}))
        second_request = pool.build_request("GET", "https://synthetic.example.invalid/storage")
        assert "cookie" not in second_request.headers
        assert len(pool.cookies) == 0

    assert pool.is_closed is True
