"""HTTP boundary tests for the S3 identity confirmation endpoint."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException
from starlette.requests import Request

from app.db.session import get_db
from app.deps import CurrentUser
from app.routers import agent_identity as identity_router
from app.services.agent_identity import AgentIdentityConfirmationDenied, IdentityConfirmation
from app.services.clerk import ClerkIdentity


_IGREJA = "00000000-0000-0000-0000-0000000000a1"
_APP_USER = "00000000-0000-0000-0000-0000000000b1"
_CHALLENGE = "00000000-0000-0000-0000-0000000000d1"


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _principal() -> identity_router.ConfirmingPanelPrincipal:
    current = CurrentUser(
        app_user_id=_APP_USER,
        clerk_user_id="clerk_synthetic_a",
        igreja_id=_IGREJA,
        email="synthetic@example.invalid",
        nome="Operador sintético",
    )
    identity = ClerkIdentity(
        clerk_user_id="clerk_synthetic_a",
        claims={"sub": "clerk_synthetic_a", "iat": 1_790_000_000, "exp": 1_790_010_000},
    )
    return identity_router.ConfirmingPanelPrincipal(current_user=current, identity=identity)


def _client(app, monkeypatch, callback):
    session = _Session()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[identity_router.get_confirming_panel_principal] = _principal
    monkeypatch.setattr(identity_router, "confirm_identity_challenge", callback)
    monkeypatch.setattr(
        identity_router,
        "get_settings",
        lambda: SimpleNamespace(effective_session_secret="synthetic-s3-secret"),
    )
    return TestClient(app), session


def _request_without_content_length(*chunks: bytes) -> Request:
    messages = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    ]

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/agent/identity-confirmations",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        },
        receive,
    )


def test_confirm_endpoint_consumes_only_server_bound_principal(app, monkeypatch) -> None:
    observed: dict[str, object] = {}

    def _confirm(*args, **kwargs):
        observed["args"] = args
        observed.update(kwargs)
        return IdentityConfirmation(
            confirmed_until=dt.datetime(2026, 9, 26, tzinfo=dt.timezone.utc)
        )

    client, session = _client(app, monkeypatch, _confirm)
    response = client.post(
        "/agent/identity-confirmations", json={"challenge": _CHALLENGE}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "confirmed"}
    assert session.commits == 1
    assert session.rollbacks == 0
    assert observed["igreja_id"] == uuid.UUID(_IGREJA)
    assert observed["app_user_id"] == uuid.UUID(_APP_USER)
    assert observed["clerk_user_id"] == "clerk_synthetic_a"
    assert observed["challenge"] == _CHALLENGE
    assert "conversation_id" not in observed
    assert "pessoa_id" not in observed


def test_confirm_endpoint_rejects_invalid_or_extra_body_without_echo(
    app, monkeypatch, caplog
) -> None:
    calls = 0

    def _confirm(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("body inválido não pode alcançar o serviço")

    client, session = _client(app, monkeypatch, _confirm)
    marker = "SENTINELA-IDENTIDADE-NAO-ECOAR"
    malformed_uuid = "00000000-0000-0000-0000-0000000000g1"
    for payload in (
        {"challenge": marker},
        {"challenge": 42},
        {"challenge": _CHALLENGE, "igrejaId": "forjada"},
        {"challenge": malformed_uuid},
        {"challenge": marker + "x" * 64},
        {},
        [marker],
    ):
        response = client.post("/agent/identity-confirmations", json=payload)
        assert response.status_code == 422
        assert response.json() == {"detail": {"error": "identity_confirmation_unavailable"}}
        assert marker not in response.text
        assert "igrejaId" not in response.text
        assert malformed_uuid not in response.text

    response = client.post(
        "/agent/identity-confirmations",
        content=("{\"challenge\":\"" + marker),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": {"error": "identity_confirmation_unavailable"}}
    assert marker not in response.text
    assert marker not in caplog.text
    assert calls == 0
    assert session.commits == 0
    assert session.rollbacks == 0


def test_confirm_endpoint_keeps_failure_generic_and_rolls_back(app, monkeypatch) -> None:
    marker = "00000000-0000-0000-0000-0000000000f1"

    def _deny(*args, **kwargs):
        raise AgentIdentityConfirmationDenied(marker)

    client, session = _client(app, monkeypatch, _deny)
    response = client.post(
        "/agent/identity-confirmations", json={"challenge": _CHALLENGE}
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"error": "identity_confirmation_unavailable"}}
    assert marker not in response.text
    assert session.commits == 0
    assert session.rollbacks == 1


def test_confirm_endpoint_commits_a_logged_generic_refusal(app, monkeypatch) -> None:
    marker = "00000000-0000-0000-0000-0000000000f2"

    def _deny(*args, **kwargs):
        raise AgentIdentityConfirmationDenied(marker, audit_logged=True)

    client, session = _client(app, monkeypatch, _deny)
    response = client.post(
        "/agent/identity-confirmations", json={"challenge": _CHALLENGE}
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"error": "identity_confirmation_unavailable"}}
    assert marker not in response.text
    assert session.commits == 1
    assert session.rollbacks == 0


def test_confirm_endpoint_bounds_declared_and_chunked_bodies_without_echo(
    app, monkeypatch
) -> None:
    calls = 0

    def _confirm(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("corpo limitado não pode alcançar o serviço")

    client, session = _client(app, monkeypatch, _confirm)
    marker = "SENTINELA-CORPO-NAO-ECOAR"
    oversized = ("{\"challenge\":\"" + marker + "x" * 512 + "\"}").encode()
    response = client.post(
        "/agent/identity-confirmations",
        content=oversized,
        headers={
            "content-type": "application/json",
            "content-length": str(len(oversized)),
        },
    )
    assert response.status_code == 422
    assert response.json() == {"detail": {"error": "identity_confirmation_unavailable"}}
    assert marker not in response.text

    request = _request_without_content_length(oversized[:16], oversized[16:])
    try:
        asyncio.run(identity_router._challenge_from_body(request))
    except HTTPException as exc:
        assert exc.status_code == 422
        assert exc.detail == {"error": "identity_confirmation_unavailable"}
    else:  # pragma: no cover - security assertion
        raise AssertionError("corpo chunked acima do teto precisa falhar fechado")
    assert calls == 0
    assert session.commits == 0
    assert session.rollbacks == 0


def test_recheck_refuses_subject_different_from_scoped_principal() -> None:
    principal = _principal().current_user

    class _Clerk:
        def verify_session_token(self, _: str) -> ClerkIdentity:
            return ClerkIdentity("clerk_other", {"sub": "clerk_other", "iat": 1})

    try:
        identity_router.get_confirming_panel_principal(
            authorization="Bearer synthetic",
            current_user=principal,
            clerk=_Clerk(),
        )
    except Exception as exc:  # FastAPI HTTPException is intentionally opaque here.
        assert getattr(exc, "status_code", None) == 401
        assert getattr(exc, "detail", None) == {
            "error": "identity_confirmation_unavailable"
        }
    else:  # pragma: no cover - security assertion
        raise AssertionError("subject divergente não pode confirmar")
