"""SEC-3A: invalidação de sessão após troca/reset de senha (MEDIO-002).

Cobre o helper `_reject_session_predating_password_change` isoladamente (com
claims/`app_user` controlados) e os endpoints reais via `TestClient`: um token
com `iat` anterior a `password_changed_at` é rejeitado, um posterior é aceito,
`password_changed_at = None` mantém compatibilidade com sessões antigas
(ninguém é deslogado no deploy), troca/reset gravam o carimbo, um skew pequeno
de relógio não invalida um login recém-feito, e um token só inválido (sem
relação com troca de senha) continua 401 como antes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.deps import _reject_session_predating_password_change
from app.routers.auth import _mark_password_changed
from app.services.clerk import ClerkIdentity, get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}


def _wire(app, *, session, clerk) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    return TestClient(app)


def _identity(iat: float | None) -> ClerkIdentity:
    claims: dict = {"sub": "clerk_user_1"}
    if iat is not None:
        claims["iat"] = iat
    return ClerkIdentity(clerk_user_id="clerk_user_1", claims=claims)


class _ClerkWithIat(FakeClerk):
    """FakeClerk que injeta um `iat` controlável nas claims da sessão."""

    def __init__(self, *, iat: float, **kwargs) -> None:
        super().__init__(**kwargs)
        self._iat = iat

    def verify_session_token(self, token: str) -> ClerkIdentity:
        identity = super().verify_session_token(token)
        return ClerkIdentity(
            clerk_user_id=identity.clerk_user_id,
            claims={**identity.claims, "iat": self._iat},
        )


class _ResetTokenClerk:
    """Stub mínimo: token de reset sempre válido pro clerk_user_id dado."""

    def __init__(self, clerk_user_id: str = "clerk_user_1") -> None:
        self._clerk_user_id = clerk_user_id

    def verify_reset_token(self, token: str) -> str:
        return self._clerk_user_id

    def set_user_password(self, clerk_user_id: str, password: str) -> None:
        pass


# ---- Unit: _reject_session_predating_password_change -------------------------


def test_token_before_password_change_is_rejected() -> None:
    changed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    issued_at = (changed_at - timedelta(hours=1)).timestamp()
    user = make_app_user(password_changed_at=changed_at)
    with pytest.raises(HTTPException) as exc_info:
        _reject_session_predating_password_change(user, _identity(issued_at))
    assert exc_info.value.status_code == 401


def test_token_after_password_change_is_accepted() -> None:
    changed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    issued_at = (changed_at + timedelta(minutes=1)).timestamp()
    user = make_app_user(password_changed_at=changed_at)
    _reject_session_predating_password_change(user, _identity(issued_at))  # não levanta


def test_null_password_changed_at_keeps_legacy_sessions_valid() -> None:
    # Token bem antigo, mas a conta nunca passou pelo campo novo — compat.
    issued_at = datetime(2000, 1, 1, tzinfo=timezone.utc).timestamp()
    user = make_app_user(password_changed_at=None)
    _reject_session_predating_password_change(user, _identity(issued_at))  # não levanta


def test_small_clock_skew_does_not_invalidate_fresh_token() -> None:
    changed_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    issued_at = (changed_at - timedelta(seconds=2)).timestamp()  # dentro da tolerância (5s)
    user = make_app_user(password_changed_at=changed_at)
    _reject_session_predating_password_change(user, _identity(issued_at))  # não levanta


def test_skew_beyond_tolerance_is_still_rejected() -> None:
    changed_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    issued_at = (changed_at - timedelta(seconds=30)).timestamp()  # além da tolerância
    user = make_app_user(password_changed_at=changed_at)
    with pytest.raises(HTTPException) as exc_info:
        _reject_session_predating_password_change(user, _identity(issued_at))
    assert exc_info.value.status_code == 401


def test_missing_iat_claim_fails_closed() -> None:
    user = make_app_user(password_changed_at=datetime.now(timezone.utc))
    with pytest.raises(HTTPException) as exc_info:
        _reject_session_predating_password_change(user, _identity(None))
    assert exc_info.value.status_code == 401


# ---- Endpoint: /auth/me (get_current_user real, não sobrescrito) -------------


def test_me_rejects_session_issued_before_password_change(app) -> None:
    changed_at = datetime.now(timezone.utc) - timedelta(hours=1)
    stale_iat = (changed_at - timedelta(hours=1)).timestamp()
    user = make_app_user(password_changed_at=changed_at)
    client = _wire(
        app,
        session=FakeSession(app_user=user, roles=["pastor"]),
        clerk=_ClerkWithIat(iat=stale_iat),
    )
    resp = client.get("/auth/me", headers=_AUTH)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Sessão inválida ou expirada"


def test_me_accepts_session_issued_after_password_change(app) -> None:
    changed_at = datetime.now(timezone.utc) - timedelta(hours=1)
    fresh_iat = datetime.now(timezone.utc).timestamp()
    user = make_app_user(password_changed_at=changed_at)
    client = _wire(
        app,
        session=FakeSession(app_user=user, roles=["pastor"]),
        clerk=_ClerkWithIat(iat=fresh_iat),
    )
    resp = client.get("/auth/me", headers=_AUTH)
    assert resp.status_code == 200


def test_invalid_token_still_401_unrelated_to_password_change(app) -> None:
    client = _wire(
        app,
        session=FakeSession(app_user=None),
        clerk=FakeClerk(raise_verify=True),
    )
    resp = client.get("/auth/me", headers=_AUTH)
    assert resp.status_code == 401


# ---- Endpoint: troca/reset gravam password_changed_at ------------------------


def test_change_password_sets_password_changed_at(app) -> None:
    user = make_app_user()
    assert user.password_changed_at is None
    client = _wire(app, session=FakeSession(app_user=user, roles=["pastor"]), clerk=FakeClerk())
    resp = client.post(
        "/auth/change-password",
        headers=_AUTH,
        json={"currentPassword": "atual", "newPassword": "novaSenha123"},
    )
    assert resp.status_code == 200
    assert user.password_changed_at is not None


def test_reset_password_sets_password_changed_at(app) -> None:
    user = make_app_user()
    assert user.password_changed_at is None
    client = _wire(app, session=FakeSession(app_user=user), clerk=_ResetTokenClerk())
    resp = client.post(
        "/auth/reset-password",
        json={"token": "tok-valido", "password": "novaSenha123"},
    )
    assert resp.status_code == 200
    assert user.password_changed_at is not None


def test_mark_password_changed_noop_when_account_not_linked() -> None:
    # Conta Clerk sem app_user vinculado: nada pra invalidar, sem erro.
    session = FakeSession(app_user=None)
    _mark_password_changed(session, "clerk_user_desconhecido")
