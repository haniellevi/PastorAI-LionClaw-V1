"""Health endpoint and app boot smoke tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


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
