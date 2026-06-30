"""Tests for the Calendar OAuth flow (events module, Fase 1).

Pure parts (state signing, consent URL) run offline; the endpoints use the
in-memory session/clerk fakes plus a fake OAuth client (no live Google).
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
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
    def __init__(
        self, *, consent="https://consent", tokens=None, calendars=None, events=None
    ) -> None:
        self._consent = consent
        self._tokens = tokens
        self._calendars = calendars or []
        self._events = events or []
        self.state_igreja = _IGREJA
        self.refreshed = False
        self.list_events_args = None

    def build_consent_url(self, igreja_id):
        return self._consent

    def verify_state(self, state):
        return self.state_igreja

    def exchange_code(self, code):
        return self._tokens

    def refresh_access_token(self, refresh):
        self.refreshed = True
        return self._tokens

    def list_calendars(self, token):
        return self._calendars

    def list_events(self, token, calendar_id, time_min, time_max, **kwargs):
        self.list_events_args = (token, calendar_id, time_min, time_max)
        return self._events


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


# ---------------------------------------------------------------------------
# import/preview (read-only; admin/pastor only) — EVT-6 PR6.1
# ---------------------------------------------------------------------------
def test_import_preview_requires_auth(app) -> None:
    c = _client(app, ["pastor"], oauth=_FakeOAuth())
    assert c.get("/calendar/import/preview").status_code == 401


def test_import_preview_forbidden_for_non_privileged(app) -> None:
    c = _client(app, ["lider_celula"], oauth=_FakeOAuth())
    assert c.get("/calendar/import/preview", headers=_AUTH).status_code == 403


def test_import_preview_not_connected_returns_409(app) -> None:
    session = _CalSession(app_user=make_app_user(), roles=["pastor"], sync=None)
    c = _client(app, ["pastor"], session=session, oauth=_FakeOAuth())
    r = c.get("/calendar/import/preview", headers=_AUTH)
    assert r.status_code == 409
    assert session.added == []  # nothing persisted


def test_import_preview_returns_events_without_persisting(app, monkeypatch) -> None:
    """Connected igreja → preview via per-igreja token, refreshing it, no writes."""
    from app.services import crypto

    monkeypatch.setattr(crypto.get_settings(), "secrets_encryption_key", "k" * 32)
    crypto._get_fernet.cache_clear()  # noqa: SLF001 - rebuild Fernet with test key
    try:
        # access token absent → forces the per-igreja refresh path.
        sync = SimpleNamespace(
            refresh_token_encrypted=crypto.encrypt_secret("rt"),
            access_token_encrypted=None,
            access_token_expira_em=None,
            google_calendar_id="cal@x",
            atualizado_em=None,
        )
        oauth = _FakeOAuth(
            tokens=OAuthTokens(access_token="fresh", refresh_token=None, expires_in=3600),
            events=[
                {
                    "googleEventId": "g1",
                    "titulo": "Culto",
                    "descricao": "domingo",
                    "data": "2026-07-05",
                    "hora": "19:00",
                    "fim": "20:30",
                    "recorrente": False,
                }
            ],
        )
        session = _CalSession(app_user=make_app_user(), roles=["pastor"], sync=sync)
        c = _client(app, ["pastor"], session=session, oauth=oauth)
        r = c.get("/calendar/import/preview", headers=_AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["calendarId"] == "cal@x"
        assert body["events"][0]["googleEventId"] == "g1"
        assert body["events"][0]["hora"] == "19:00"
        # per-igreja refresh happened with the igreja's calendar id...
        assert oauth.refreshed is True
        assert oauth.list_events_args[0] == "fresh"  # per-igreja token, not global
        assert oauth.list_events_args[1] == "cal@x"
        # ...and NOTHING was written to events (no rows added).
        assert session.added == []
    finally:
        crypto._get_fernet.cache_clear()  # noqa: SLF001 - don't leak the test key


# ---------------------------------------------------------------------------
# GoogleOAuthClient.list_events — real HTTP path (mocked transport, no Google)
# ---------------------------------------------------------------------------
def _use_transport(monkeypatch, handler) -> None:
    """Route every httpx.Client through a MockTransport with `handler`."""
    transport = httpx.MockTransport(handler)
    real = httpx.Client

    def fake(*args, **kwargs):
        kwargs.pop("transport", None)
        return real(*args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "Client", fake)


def test_list_events_is_read_only_and_normalizes(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "timed1",
                        "summary": "Culto",
                        "description": "domingo",
                        "start": {"dateTime": "2026-07-05T19:00:00-03:00"},
                        "end": {"dateTime": "2026-07-05T20:30:00-03:00"},
                    },
                    {
                        "id": "allday1",
                        "summary": "Feriado",
                        "start": {"date": "2026-07-09"},
                        "end": {"date": "2026-07-10"},
                    },
                    {
                        "id": "rec1",
                        "summary": "Reunião semanal",
                        "start": {"dateTime": "2026-07-06T08:00:00-03:00"},
                        "end": {"dateTime": "2026-07-06T09:00:00-03:00"},
                        "recurringEventId": "master",
                    },
                    {
                        "id": "cancelled1",
                        "status": "cancelled",
                        "start": {"dateTime": "2026-07-07T10:00:00-03:00"},
                    },
                ]
            },
        )

    _use_transport(monkeypatch, handler)
    # A global legacy token is set on settings to prove it is NEVER used.
    oauth = GoogleOAuthClient(
        settings=Settings(
            session_jwt_secret="x", google_calendar_access_token="GLOBAL-LEAK"
        )
    )
    out = oauth.list_events(
        "per-igreja-tok", "primary", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"
    )

    # read-only GET, right query, per-igreja bearer token, empty body
    assert captured["method"] == "GET"
    assert "/calendars/primary/events" in captured["url"]
    assert captured["params"]["singleEvents"] == "true"
    assert captured["params"]["orderBy"] == "startTime"
    assert captured["params"]["timeMin"] == "2026-07-01T00:00:00Z"
    assert captured["params"]["timeMax"] == "2026-08-01T00:00:00Z"
    assert captured["auth"] == "Bearer per-igreja-tok"  # not the global token
    assert "GLOBAL-LEAK" not in (captured["auth"] or "")
    assert captured["body"] == b""

    # cancelled dropped; timed/all-day/recurring normalized
    ids = [e["googleEventId"] for e in out]
    assert ids == ["timed1", "allday1", "rec1"]
    assert (out[0]["data"], out[0]["hora"], out[0]["fim"]) == (
        "2026-07-05",
        "19:00",
        "20:30",
    )
    assert out[0]["recorrente"] is False
    assert out[1]["hora"] is None and out[1]["fim"] is None
    assert out[1]["data"] == "2026-07-09"
    assert out[2]["recorrente"] is True


def test_list_events_http_error_is_controlled(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    _use_transport(monkeypatch, handler)
    oauth = GoogleOAuthClient(settings=Settings(session_jwt_secret="x"))
    with pytest.raises(GoogleOAuthError):
        oauth.list_events("tok", "primary", "t0", "t1")
