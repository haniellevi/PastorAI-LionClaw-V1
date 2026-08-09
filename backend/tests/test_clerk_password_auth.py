"""Clerk password authentication: classification and HTTP pool lifecycle."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.services.clerk import (
    ClerkAuthError,
    ClerkClient,
    ClerkUnavailableError,
)


def _settings(**overrides) -> Settings:
    values = {
        "clerk_secret_key": "sk_test_clerk",
        "session_jwt_secret": "s" * 40,
    }
    values.update(overrides)
    return Settings(**values)


def _client_with_transport(monkeypatch, handler) -> tuple[ClerkClient, list[httpx.Client]]:
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    created: list[httpx.Client] = []

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        client = real_client(*args, **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(httpx, "Client", factory)
    return ClerkClient(_settings()), created


def test_authenticate_password_reuses_pool_and_closes_it(monkeypatch) -> None:
    requests: list[str] = []
    timeouts: list[dict[str, float]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        timeouts.append(request.extensions["timeout"])
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": "clerk_user_1"}])
        return httpx.Response(200, json={"verified": True})

    clerk, created = _client_with_transport(monkeypatch, handler)

    first = clerk.authenticate_password("pastor@example.com", "secret")
    second = clerk.authenticate_password("pastor@example.com", "secret")

    assert first[1] == second[1] == "clerk_user_1"
    assert len(created) == 1
    assert requests == [
        "/v1/users",
        "/v1/users/clerk_user_1/verify_password",
        "/v1/users",
        "/v1/users/clerk_user_1/verify_password",
    ]
    expected_timeout = {"connect": 5.0, "read": 5.0, "write": 5.0, "pool": 5.0}
    assert all(timeout == expected_timeout for timeout in timeouts)

    clerk.close()
    clerk.close()
    assert created[0].is_closed


@pytest.mark.parametrize("case", ["unknown_email", "wrong_password"])
def test_confirmed_credential_rejection_stays_auth_error(monkeypatch, case: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            users = [] if case == "unknown_email" else [{"id": "clerk_user_1"}]
            return httpx.Response(200, json=users)
        return httpx.Response(200, json={"verified": False})

    clerk, _ = _client_with_transport(monkeypatch, handler)

    with pytest.raises(ClerkAuthError):
        clerk.authenticate_password("pastor@example.com", "wrong")
    clerk.close()


def test_clerk_verify_422_is_confirmed_credential_rejection(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": "clerk_user_1"}])
        return httpx.Response(
            422, json={"errors": [{"code": "form_password_incorrect"}]}
        )

    clerk, _ = _client_with_transport(monkeypatch, handler)

    with pytest.raises(ClerkAuthError):
        clerk.authenticate_password("pastor@example.com", "wrong")
    clerk.close()


@pytest.mark.parametrize("status_code", [401, 429, 503])
def test_clerk_http_failure_is_unavailable_not_invalid_credentials(
    monkeypatch, status_code: int
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "upstream failure"})

    clerk, _ = _client_with_transport(monkeypatch, handler)

    with pytest.raises(ClerkUnavailableError):
        clerk.authenticate_password("pastor@example.com", "secret")
    clerk.close()


def test_clerk_timeout_is_unavailable_not_invalid_credentials(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    clerk, _ = _client_with_transport(monkeypatch, handler)

    with pytest.raises(ClerkUnavailableError):
        clerk.authenticate_password("pastor@example.com", "secret")
    clerk.close()


def test_unexpected_verify_payload_is_unavailable(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": "clerk_user_1"}])
        return httpx.Response(200, json={"status": "unknown"})

    clerk, _ = _client_with_transport(monkeypatch, handler)

    with pytest.raises(ClerkUnavailableError):
        clerk.authenticate_password("pastor@example.com", "secret")
    clerk.close()


def test_missing_clerk_secret_is_unavailable() -> None:
    clerk = ClerkClient(_settings(clerk_secret_key=""))

    with pytest.raises(ClerkUnavailableError):
        clerk.authenticate_password("pastor@example.com", "secret")
