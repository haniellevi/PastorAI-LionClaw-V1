"""Tests for the Calendar OAuth flow (events module, Fase 1).

Pure parts (state signing, consent URL) run offline; the endpoints use the
in-memory session/clerk fakes plus a fake OAuth client (no live Google).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.models import AppUser, CalendarSync
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from app.services.google_oauth import (
    GoogleOAuthClient,
    GoogleOAuthError,
    OAuthTokens,
    get_google_oauth_client,
)
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_IGREJA = "00000000-0000-0000-0000-000000000001"


def _oauth_client(secret: str = "topsecret") -> GoogleOAuthClient:
    return GoogleOAuthClient(
        settings=Settings(
            session_jwt_secret=secret,
            google_oauth_client_id="cid",
            google_oauth_client_secret="sec",
            google_oauth_redirect_uri="https://api.igreja12.com.br/calendar/callback",
        )
    )


# ---------------------------------------------------------------------------
# state (CSRF + tenant) + consent URL — pure
# ---------------------------------------------------------------------------
def test_state_roundtrip() -> None:
    oauth = _oauth_client()
    state = oauth.sign_state(_IGREJA)
    assert oauth.verify_state(state) == _IGREJA


def test_state_tampered_is_rejected() -> None:
    oauth = _oauth_client()
    with pytest.raises(GoogleOAuthError):
        oauth.verify_state(oauth.sign_state(_IGREJA) + "x")


def test_state_wrong_secret_is_rejected() -> None:
    state = _oauth_client("topsecret").sign_state(_IGREJA)
    with pytest.raises(GoogleOAuthError):
        _oauth_client("different").verify_state(state)


def test_consent_url_forces_offline_and_carries_state() -> None:
    url = _oauth_client().build_consent_url(_IGREJA)
    assert "client_id=cid" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=" in url
    assert "redirect_uri=" in url


def test_consent_url_raises_without_config() -> None:
    oauth = GoogleOAuthClient(settings=Settings(session_jwt_secret="x"))
    with pytest.raises(GoogleOAuthError):
        oauth.build_consent_url(_IGREJA)


# ---------------------------------------------------------------------------
# fakes for the endpoints
# ---------------------------------------------------------------------------
class _Res:
    def __init__(self, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class _CalSession:
    def __init__(self, *, app_user, roles, sync) -> None:
        self.app_user = app_user
        self.roles = roles
        self.sync = sync
        self.added: list = []
        self.deleted: list = []
        self.committed = False

    def execute(self, statement, params=None) -> _Res:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _Res(scalar=self.app_user)
        if ent is CalendarSync:
            return _Res(scalar=self.sync)
        return _Res(scalars=self.roles)

    def add(self, obj) -> None:
        self.added.append(obj)

    def delete(self, obj) -> None:
        self.deleted.append(obj)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


class _FakeOAuth:
    def __init__(self, *, consent="https://consent", tokens=None, calendars=None) -> None:
        self._consent = consent
        self._tokens = tokens
        self._calendars = calendars or []
        self.state_igreja = _IGREJA

    def build_consent_url(self, igreja_id):
        return self._consent

    def verify_state(self, state):
        return self.state_igreja

    def exchange_code(self, code):
        return self._tokens

    def refresh_access_token(self, refresh):
        return self._tokens

    def list_calendars(self, token):
        return self._calendars


def _client(app, roles, *, session=None, oauth=None) -> TestClient:
    app.dependency_overrides[get_db] = (
        (lambda: session)
        if session is not None
        else (lambda: FakeSession(app_user=make_app_user(), roles=roles))
    )
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    if oauth is not None:
        app.dependency_overrides[get_google_oauth_client] = lambda: oauth
    return TestClient(app)


# ---------------------------------------------------------------------------
# connect (admin only)
# ---------------------------------------------------------------------------
def test_connect_requires_auth(app) -> None:
    c = _client(app, ["admin"], oauth=_FakeOAuth())
    assert c.get("/calendar/connect").status_code == 401


def test_connect_forbidden_for_non_admin(app) -> None:
    c = _client(app, ["lider_celula"], oauth=_FakeOAuth())
    assert c.get("/calendar/connect", headers=_AUTH).status_code == 403


def test_connect_returns_auth_url(app) -> None:
    c = _client(app, ["admin"], oauth=_FakeOAuth(consent="https://accounts.google/x"))
    r = c.get("/calendar/connect", headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["authUrl"] == "https://accounts.google/x"


# ---------------------------------------------------------------------------
# status / select / disconnect
# ---------------------------------------------------------------------------
def test_status_not_connected(app) -> None:
    session = _CalSession(app_user=make_app_user(), roles=["admin"], sync=None)
    c = _client(app, ["admin"], session=session)
    r = c.get("/calendar/status", headers=_AUTH)
    assert r.status_code == 200
    assert r.json() == {"connected": False, "calendarId": None}


def test_status_connected(app) -> None:
    sync = SimpleNamespace(refresh_token_encrypted="enc", google_calendar_id="cal@x")
    session = _CalSession(app_user=make_app_user(), roles=["admin"], sync=sync)
    c = _client(app, ["admin"], session=session)
    r = c.get("/calendar/status", headers=_AUTH)
    assert r.json() == {"connected": True, "calendarId": "cal@x"}


def test_select_calendar_sets_id(app) -> None:
    sync = SimpleNamespace(
        refresh_token_encrypted="enc", google_calendar_id=None, atualizado_em=None
    )
    session = _CalSession(app_user=make_app_user(), roles=["admin"], sync=sync)
    c = _client(app, ["admin"], session=session)
    r = c.put("/calendar", json={"calendarId": "cal@new"}, headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["calendarId"] == "cal@new"
    assert sync.google_calendar_id == "cal@new"
    assert session.committed is True


def test_select_calendar_requires_connection(app) -> None:
    session = _CalSession(app_user=make_app_user(), roles=["admin"], sync=None)
    c = _client(app, ["admin"], session=session)
    assert (
        c.put("/calendar", json={"calendarId": "x"}, headers=_AUTH).status_code == 409
    )


def test_disconnect_deletes(app) -> None:
    sync = SimpleNamespace(refresh_token_encrypted="enc")
    session = _CalSession(app_user=make_app_user(), roles=["admin"], sync=sync)
    c = _client(app, ["admin"], session=session)
    r = c.delete("/calendar", headers=_AUTH)
    assert r.status_code == 204
    assert session.deleted == [sync]
    assert session.committed is True


# ---------------------------------------------------------------------------
# callback (public; tenant from signed state)
# ---------------------------------------------------------------------------
def test_callback_bad_state_redirects_without_storing(app) -> None:
    session = _CalSession(app_user=None, roles=[], sync=None)
    oauth = _FakeOAuth()

    def boom(_state):
        raise GoogleOAuthError("bad state")

    oauth.verify_state = boom  # type: ignore[method-assign]
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_google_oauth_client] = lambda: oauth
    c = TestClient(app)
    r = c.get("/calendar/callback?code=x&state=bad", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert session.added == []
    assert session.committed is False


def test_callback_stores_encrypted_tokens(app, monkeypatch) -> None:
    from app.services import crypto

    monkeypatch.setattr(crypto.get_settings(), "secrets_encryption_key", "k" * 32)
    crypto._get_fernet.cache_clear()  # noqa: SLF001 - rebuild Fernet with test key
    try:
        session = _CalSession(app_user=None, roles=[], sync=None)
        oauth = _FakeOAuth(
            tokens=OAuthTokens(access_token="at", refresh_token="rt", expires_in=3600)
        )
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[get_google_oauth_client] = lambda: oauth
        c = TestClient(app)
        r = c.get("/calendar/callback?code=abc&state=ok", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert len(session.added) == 1
        added = session.added[0]
        # refresh token persisted ENCRYPTED (never plaintext).
        assert added.refresh_token_encrypted
        assert added.refresh_token_encrypted != "rt"
        assert session.committed is True
    finally:
        crypto._get_fernet.cache_clear()  # noqa: SLF001 - don't leak the test key
