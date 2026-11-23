"""Clerk password authentication: classification and HTTP pool lifecycle."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.session import get_db
from app.services.clerk import (
    ClerkAuthError,
    ClerkClient,
    ClerkUnavailableError,
    get_clerk_client,
)
from tests.conftest import FakeSession, make_app_user
from tests.test_auth_activate import InviteSession, make_invited


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


def test_create_and_update_password_require_clerk_policy(monkeypatch) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"id": "clerk_user_1"})

    clerk, _ = _client_with_transport(monkeypatch, handler)
    try:
        assert clerk.create_user("pastor@example.com", "NovaSenha!123") == "clerk_user_1"
        clerk.set_user_password("clerk_user_1", "OutraSenha!123")
    finally:
        clerk.close()

    assert requests == [
        ("POST", "/v1/users", {
            "email_address": ["pastor@example.com"], "password": "NovaSenha!123",
        }),
        ("PATCH", "/v1/users/clerk_user_1", {"password": "OutraSenha!123"}),
    ]


@pytest.mark.parametrize(
    ("endpoint", "code", "message"),
    [
        ("activate", "form_password_not_strong_enough",
         "Escolha uma senha mais forte, com uma combinação menos previsível."),
        ("reset-password", "form_password_pwned",
         "Esta senha apareceu em vazamentos. Escolha uma senha diferente."),
        ("change-password", "form_password_length_too_short",
         "A senha é curta demais. Escolha uma senha com mais caracteres."),
        ("change-password", "form_password_no_number",
         "Inclua pelo menos um número na senha."),
    ],
)
def test_password_policy_rejection_preserves_account_and_session(
    app, monkeypatch, caplog, endpoint: str, code: str, message: str,
) -> None:
    rejected_password = "senha-sintetica-rejeitada"
    upstream_detail = "detalhe-interno-sintetico"
    mutations = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            users = [] if endpoint == "activate" else [{"id": "clerk_user_1"}]
            return httpx.Response(200, json=users)
        if request.url.path.endswith("/verify_password"):
            return httpx.Response(200, json={"verified": True})
        mutations.append((request.method, request.url.path))
        if json.loads(request.content)["password"] != rejected_password:
            return httpx.Response(200, json={"id": "clerk_user_1"})
        errors = [{
            "code": code, "message": upstream_detail, "meta": {"password": rejected_password},
        }]
        if endpoint == "reset-password":
            errors.append({"code": "form_password_not_strong_enough"})
        return httpx.Response(422, json={"errors": errors})

    clerk, _ = _client_with_transport(monkeypatch, handler)
    user = make_app_user()
    token, _jti, expires_at = clerk.mint_reset_token("clerk_user_1")
    row = SimpleNamespace(used_at=None, expires_at=expires_at)
    db = FakeSession(app_user=user, roles=["pastor"], reset_token=row)
    session_token = clerk._mint_session_token("clerk_user_1")
    db.auth_session.jti = clerk.verify_session_token(session_token).claims["jti"]
    headers = {"Authorization": f"Bearer {session_token}"}
    payload = {"currentPassword": "SenhaAtual!123", "newPassword": rejected_password}
    expected_mutation = ("PATCH", "/v1/users/clerk_user_1")
    if endpoint == "activate":
        user = make_invited()
        db = InviteSession(user)
        payload = {"token": clerk.mint_invite_token(user.id), "password": rejected_password}
        expected_mutation = ("POST", "/v1/users")
    elif endpoint == "reset-password":
        payload = {"token": token, "password": rejected_password}

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    path = f"/auth/{endpoint}"
    client = TestClient(app)
    try:
        response = client.post(path, json=payload, headers=headers)
        assert response.status_code == 400, response.json()
        assert response.json() == {"detail": message}
        assert "set-cookie" not in response.headers
        assert mutations == [expected_mutation]
        assert all(value not in response.text + caplog.text for value in (
            rejected_password, upstream_detail, "sk_test_clerk", token, session_token,
        ))

        if endpoint == "activate":
            assert db.rolled_back and not db.committed
            assert user.clerk_user_id is None and user.status == "convidado"
        else:
            assert user.password_changed_at is None
            assert db.auth_session.revoked_at is None
            assert not db.added
            assert client.get("/auth/me", headers=headers).status_code == 200

        if endpoint == "reset-password":
            assert db.commits == 2
            assert row.used_at is None
            assert client.post(path, json={**payload, "password": "NovaSenha!123"}).status_code == 200
            assert row.used_at is not None and user.password_changed_at is not None
            assert client.post(path, json=payload).status_code == 400
            assert mutations == [expected_mutation, expected_mutation]
    finally:
        client.close()
        clerk.close()


_POLICY_ERROR = {"code": "form_password_pwned"}
_RESOURCE_ERROR = {"code": "resource_not_found"}


@pytest.mark.parametrize(("upstream_status", "upstream_body"), [
    pytest.param(422, b"resposta invalida", id="invalid-json"),
    pytest.param(422, b'{"errors":[]}', id="empty-list"),
    pytest.param(422, b'{"errors":[{"code":"resource_not_found"}]}', id="resource"),
    pytest.param(422, b'{"errors":[{"code":"form_password_validation_failed"}]}',
                 id="generic-validation"),
    pytest.param(422, json.dumps({"errors": [_POLICY_ERROR, _RESOURCE_ERROR]}).encode(),
                 id="policy-before-resource"),
    pytest.param(422, json.dumps({"errors": [_RESOURCE_ERROR, _POLICY_ERROR]}).encode(),
                 id="resource-before-policy"),
    pytest.param(422, json.dumps({"errors": [_POLICY_ERROR, {"code": "unexpected"}]}).encode(),
                 id="unknown-code"),
    pytest.param(422, json.dumps({"errors": [{"code": "form_password_incorrect"}, _POLICY_ERROR]}).encode(),
                 id="credential-error"),
    pytest.param(422, json.dumps({"errors": [_POLICY_ERROR, None]}).encode(), id="malformed-item"),
    pytest.param(422, json.dumps({"errors": [{"code": []}, _POLICY_ERROR]}).encode(),
                 id="malformed-code"),
    pytest.param(503, json.dumps({"errors": [_POLICY_ERROR]}).encode(), id="unavailable"),
])
def test_reset_keeps_token_consumed_if_clerk_does_not_confirm_policy_rejection(
    app, monkeypatch, upstream_status: int, upstream_body: bytes,
) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        return httpx.Response(upstream_status, content=upstream_body)

    clerk, _ = _client_with_transport(monkeypatch, handler)
    token, _jti, expires_at = clerk.mint_reset_token("clerk_user_1")
    row = SimpleNamespace(used_at=None, expires_at=expires_at)
    user = make_app_user()
    db = FakeSession(app_user=user, reset_token=row)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    client = TestClient(app)
    try:
        with pytest.raises(ClerkAuthError) as creation_error:
            clerk.create_user("pastor@example.com", "NovaSenha!123")
        assert type(creation_error.value) is ClerkAuthError
        with pytest.raises(ClerkAuthError) as update_error:
            clerk.set_user_password("clerk_user_1", "NovaSenha!123")
        assert type(update_error.value) is ClerkAuthError

        payload = {"token": token, "password": "NovaSenha!123"}
        response = client.post("/auth/reset-password", json=payload)
        assert response.status_code == 502
        assert response.json() == {"detail": "Não foi possível redefinir a senha. Tente novamente."}
        assert row.used_at is not None and db.commits == 1
        assert user.password_changed_at is None
        replay = client.post("/auth/reset-password", json=payload)
        assert replay.status_code == 400
        assert replay.json() == {"detail": "Link inválido ou expirado. Peça um novo."}
        assert requests == ["POST", "PATCH", "PATCH"]
    finally:
        client.close()
        clerk.close()


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
