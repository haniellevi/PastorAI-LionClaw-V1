"""Health endpoint and app boot smoke tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_200(app) -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_openapi_exposes_login_route(app) -> None:
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    assert "/auth/login" in schema["paths"]
