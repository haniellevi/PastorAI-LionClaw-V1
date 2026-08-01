"""Tests for the Calendar OAuth flow (OAUTH-CALENDAR-V1).

O consentimento tem dois tempos: o callback público só ESTACIONA o `code` e o
`finish` autenticado é quem consome o fluxo e troca com o Google. Os testes
abaixo provam, sobretudo, as REJEIÇÕES — é nelas que mora a segurança.

Nenhum teste chama o Google: o cliente OAuth é dublado ou o transporte httpx é
substituído por um MockTransport.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.sql.dml import Update

from app.config import Settings, get_settings
from app.db.models import AppUser, CalendarOAuthFlow, CalendarSync, Event
from app.db.session import get_db
from app.services.calendar_oauth_flows import hash_secret
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
_OUTRA_IGREJA = "00000000-0000-0000-0000-0000000000ff"
_ORIGIN = "https://admin.igreja12.com.br"
_ORIGIN_HEADERS = {**_AUTH, "Origin": _ORIGIN}
_STATE = "state-opaco-do-fluxo"
_FLOW_SECRET = "flow-secret-do-painel"


@pytest.fixture(autouse=True)
def _allowlist(monkeypatch):
    """Origem do painel liberada; a API e o console master ficam de fora."""
    monkeypatch.setattr(
        get_settings(), "calendar_oauth_return_origins", f"{_ORIGIN}, https://app.x.com"
    )
    monkeypatch.setattr(get_settings(), "frontend_url", "https://app.igreja12.com.br")
    return get_settings()


@pytest.fixture
def crypto_enabled(monkeypatch):
    """Habilita a criptografia de segredos (verifier/code/tokens cifrados)."""
    from app.services import crypto

    monkeypatch.setattr(crypto.get_settings(), "secrets_encryption_key", "k" * 32)
    crypto._get_fernet.cache_clear()  # noqa: SLF001 - rebuild Fernet with test key
    yield crypto
    crypto._get_fernet.cache_clear()  # noqa: SLF001 - don't leak the test key


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------
class _Res:
    def __init__(self, *, scalar=None, first=None, scalars=None) -> None:
        self._scalar = scalar
        self._first = first
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def first(self):
        return self._first

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class _FlowSession:
    """Sessão dublê que entende os statements dos endpoints do fluxo.

    O UPDATE do park é modelado com a MESMA semântica condicional do router: só
    "afeta linha" quando o fluxo existe, não foi consumido, não expirou e ainda
    não tem code estacionado — é assim que `first-write-wins` fica testável.
    """

    def __init__(
        self,
        *,
        app_user=None,
        roles=None,
        flow=None,
        sync=None,
        existing_gids=None,
        commit_error: Exception | None = None,
    ) -> None:
        self.app_user = app_user
        self.roles = roles or []
        self.flow = flow
        # Quantos SELECT de `calendar_oauth_flows` o endpoint disparou. Um corpo
        # sem `flowSecret` tem de morrer no schema, com este contador em ZERO —
        # nada de ler, travar ou consumir fluxo sem posse do segredo.
        self.flow_lookups = 0
        self.sync = sync
        self.existing_gids = existing_gids or []
        self.commit_error = commit_error
        self.added: list = []
        self.deleted: list = []
        self.commits = 0
        self.rollbacks = 0
        self.updates = 0
        self.info: dict = {}
        self.last_event_stmt = None

    def execute(self, statement, params=None):
        if isinstance(statement, Update):
            self.updates += 1
            flow = self.flow
            parkable = (
                flow is not None
                and flow.code_encrypted is None
                and flow.consumed_at is None
                and flow.expires_at > dt.datetime.now(dt.timezone.utc)
            )
            if parkable:
                flow.code_encrypted = "parked"
                return _Res(scalar=flow.return_origin)
            return _Res(scalar=None)

        descs = list(getattr(statement, "column_descriptions", []) or [])
        if not descs:
            return _Res()
        entity = descs[0].get("entity")
        if entity is AppUser:
            return _Res(scalar=self.app_user)
        if entity is CalendarSync:
            return _Res(scalar=self.sync)
        if entity is Event:
            self.last_event_stmt = statement
            return _Res(scalars=self.existing_gids)
        if entity is CalendarOAuthFlow:
            if len(descs) == 1:  # select(CalendarOAuthFlow) — o finish
                self.flow_lookups += 1
                # A única busca legítima é pelo hash do segredo. Se algum dia
                # voltar uma busca por identidade, este assert a denuncia.
                assert "flow_secret_hash" in str(statement.whereclause), (
                    "finish só pode localizar o fluxo pelo hash do flowSecret"
                )
                return _Res(scalar=self.flow)
            flow = self.flow  # select(return_origin, code_encrypted) — o redirect
            return _Res(
                first=None
                if flow is None
                else (flow.return_origin, flow.code_encrypted)
            )
        return _Res(scalars=self.roles)

    def add(self, obj) -> None:
        self.added.append(obj)

    def delete(self, obj) -> None:
        self.deleted.append(obj)

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:  # pragma: no cover
        pass


class _FakeOAuth:
    def __init__(
        self,
        *,
        consent="https://consent",
        tokens=None,
        calendars=None,
        events=None,
        exchange_error: Exception | None = None,
        list_error: Exception | None = None,
    ) -> None:
        self._consent = consent
        self._tokens = tokens
        self._calendars = calendars or [
            {"id": "cal@x", "summary": "X", "primary": True}
        ]
        self._events = events or []
        self._exchange_error = exchange_error
        self._list_error = list_error
        self.refreshed = False
        self.exchanges: list[tuple[str, str]] = []
        self.consent_args: dict | None = None
        self.list_events_args = None
        self.listed_tokens: list[str] = []

    def build_consent_url(self, *, state, code_challenge):
        self.consent_args = {"state": state, "code_challenge": code_challenge}
        return f"{self._consent}?state={state}&code_challenge={code_challenge}"

    def exchange_code(self, code, code_verifier):
        self.exchanges.append((code, code_verifier))
        if self._exchange_error is not None:
            raise self._exchange_error
        return self._tokens

    def refresh_access_token(self, refresh):
        self.refreshed = True
        return self._tokens

    def list_calendars(self, token):
        self.listed_tokens.append(token)
        if self._list_error is not None:
            raise self._list_error
        return self._calendars

    def list_events(self, token, calendar_id, time_min, time_max, **kwargs):
        self.list_events_args = (token, calendar_id, time_min, time_max)
        return self._events


class _NoGoogleOAuth(_FakeOAuth):
    """Falha ruidosamente se alguém tentar falar com o Google."""

    def exchange_code(self, code, code_verifier):  # pragma: no cover - deve falhar
        raise AssertionError("o callback público NUNCA pode trocar o code")

    def list_calendars(self, token):  # pragma: no cover - deve falhar
        raise AssertionError("o callback público NUNCA pode chamar o Google")


def _flow(
    *,
    app_user_id: uuid.UUID,
    igreja_id: str = _IGREJA,
    code_encrypted: str | None = None,
    verifier_encrypted: str | None = "enc-verifier",
    consumed_at=None,
    expired: bool = False,
    return_origin: str = _ORIGIN,
) -> SimpleNamespace:
    now = dt.datetime.now(dt.timezone.utc)
    return SimpleNamespace(
        state_hash=hash_secret(_STATE),
        flow_secret_hash=hash_secret(_FLOW_SECRET),
        igreja_id=uuid.UUID(igreja_id),
        app_user_id=app_user_id,
        return_origin=return_origin,
        verifier_encrypted=verifier_encrypted,
        code_encrypted=code_encrypted,
        expires_at=(
            now - dt.timedelta(minutes=1) if expired else now + dt.timedelta(minutes=9)
        ),
        consumed_at=consumed_at,
        atualizado_em=now,
    )


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


def _public_client(app, session, oauth=None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_google_oauth_client] = lambda: oauth or _NoGoogleOAuth()
    return TestClient(app)


# ---------------------------------------------------------------------------
# connect — allowlist de origem
# ---------------------------------------------------------------------------
def test_connect_requires_auth(app) -> None:
    c = _client(app, ["admin"], oauth=_FakeOAuth())
    assert c.get("/calendar/connect").status_code == 401


def test_connect_forbidden_for_non_admin(app) -> None:
    c = _client(app, ["lider_celula"], oauth=_FakeOAuth())
    assert c.get("/calendar/connect", headers=_ORIGIN_HEADERS).status_code == 403


def test_connect_rejects_missing_origin(app, crypto_enabled) -> None:
    session = _FlowSession(app_user=make_app_user(), roles=["admin"])
    c = _client(app, ["admin"], session=session, oauth=_FakeOAuth())
    assert c.get("/calendar/connect", headers=_AUTH).status_code == 400
    assert session.added == []


def test_connect_rejects_origin_outside_allowlist(app, crypto_enabled) -> None:
    """`painel.*` é o console master — não hospeda o card de Integrações."""
    session = _FlowSession(app_user=make_app_user(), roles=["admin"])
    c = _client(app, ["admin"], session=session, oauth=_FakeOAuth())
    r = c.get(
        "/calendar/connect",
        headers={**_AUTH, "Origin": "https://painel.igreja12.com.br"},
    )
    assert r.status_code == 400
    assert session.added == []


def test_connect_rejects_api_origin(app, crypto_enabled) -> None:
    """`cors_origins` inclui a API; esta allowlist é outra coisa."""
    session = _FlowSession(app_user=make_app_user(), roles=["admin"])
    c = _client(app, ["admin"], session=session, oauth=_FakeOAuth())
    r = c.get(
        "/calendar/connect",
        headers={**_AUTH, "Origin": "https://api.igreja12.com.br"},
    )
    assert r.status_code == 400
    assert session.added == []


def test_connect_rejects_origin_by_prefix_similarity(app, crypto_enabled) -> None:
    """Igualdade EXATA: um domínio que só *começa* igual não passa."""
    session = _FlowSession(app_user=make_app_user(), roles=["admin"])
    c = _client(app, ["admin"], session=session, oauth=_FakeOAuth())
    r = c.get(
        "/calendar/connect",
        headers={**_AUTH, "Origin": "https://admin.igreja12.com.br.evil.com"},
    )
    assert r.status_code == 400
    assert session.added == []


def test_connect_creates_flow_with_pkce_and_returns_flow_secret(
    app, crypto_enabled
) -> None:
    app_user = make_app_user()
    session = _FlowSession(app_user=app_user, roles=["admin"])
    oauth = _FakeOAuth()
    c = _client(app, ["admin"], session=session, oauth=oauth)

    r = c.get("/calendar/connect", headers=_ORIGIN_HEADERS)

    assert r.status_code == 200
    body = r.json()
    assert body["authUrl"].startswith("https://consent")
    assert body["flowSecret"]
    assert oauth.consent_args is not None
    assert oauth.consent_args["code_challenge"]

    assert len(session.added) == 1
    flow = session.added[0]
    assert flow.return_origin == _ORIGIN
    assert flow.igreja_id == uuid.UUID(_IGREJA)
    assert flow.app_user_id == uuid.UUID(str(app_user.id))
    # Segredos só como hash, e o flowSecret é DIFERENTE do state.
    assert flow.state_hash == hash_secret(oauth.consent_args["state"])
    assert flow.flow_secret_hash == hash_secret(body["flowSecret"])
    assert body["flowSecret"] != oauth.consent_args["state"]

    # `expiresAt` é o MESMO instante gravado na linha — o painel não deriva TTL.
    assert dt.datetime.fromisoformat(body["expiresAt"]) == flow.expires_at
    ttl = get_settings().calendar_oauth_flow_ttl_minutes
    assert flow.expires_at > dt.datetime.now(dt.timezone.utc)
    assert flow.expires_at <= dt.datetime.now(dt.timezone.utc) + dt.timedelta(
        minutes=ttl
    )
    assert flow.verifier_encrypted
    assert flow.code_encrypted is None
    assert session.commits == 1


def test_connect_returns_503_without_google_config(app, crypto_enabled) -> None:
    """Kill switch operacional: sem client_id não começa fluxo nenhum."""

    class _Unconfigured(_FakeOAuth):
        def build_consent_url(self, *, state, code_challenge):
            raise GoogleOAuthError("Google OAuth não está configurado")

    session = _FlowSession(app_user=make_app_user(), roles=["admin"])
    c = _client(app, ["admin"], session=session, oauth=_Unconfigured())
    assert c.get("/calendar/connect", headers=_ORIGIN_HEADERS).status_code == 503
    assert session.added == []


# ---------------------------------------------------------------------------
# callback — só estaciona; nunca fala com o Google
# ---------------------------------------------------------------------------
def _callback(client: TestClient, **params) -> httpx.Response:
    return client.get("/calendar/callback", params=params, follow_redirects=False)


def test_callback_parks_code_without_calling_google(app, crypto_enabled) -> None:
    app_user = make_app_user()
    flow = _flow(app_user_id=uuid.UUID(str(app_user.id)))
    session = _FlowSession(flow=flow)
    c = _public_client(app, session)

    r = _callback(c, code="abc", state=_STATE)

    assert r.status_code in (302, 307)
    assert r.headers["location"] == f"{_ORIGIN}/#integracoes/callback/ready"
    assert flow.code_encrypted is not None  # estacionado
    assert flow.consumed_at is None  # NÃO consumido
    assert session.added == []  # nada escrito em calendar_sync
    assert session.commits == 1


def test_callback_redirects_to_persisted_origin_not_frontend_url(
    app, crypto_enabled
) -> None:
    """O destino vem do fluxo, nunca de FRONTEND_URL, e nunca em #calendario."""
    app_user = make_app_user()
    flow = _flow(app_user_id=uuid.UUID(str(app_user.id)))
    c = _public_client(app, _FlowSession(flow=flow))

    location = _callback(c, code="abc", state=_STATE).headers["location"]

    assert location.startswith(_ORIGIN)
    assert "app.igreja12.com.br" not in location
    assert "#calendario" not in location
    assert location.endswith("#integracoes/callback/ready")


def test_callback_app_surface_uses_gestao_path(app, crypto_enabled) -> None:
    app_user = make_app_user()
    flow = _flow(
        app_user_id=uuid.UUID(str(app_user.id)), return_origin="https://app.x.com"
    )
    c = _public_client(app, _FlowSession(flow=flow))

    location = _callback(c, code="abc", state=_STATE).headers["location"]

    assert location == "https://app.x.com/gestao#integracoes/callback/ready"


def test_callback_unknown_state_is_noop(app, crypto_enabled) -> None:
    session = _FlowSession(flow=None)
    c = _public_client(app, session)

    r = _callback(c, code="abc", state="desconhecido")

    assert r.status_code in (302, 307)
    assert r.headers["location"].endswith("#integracoes/callback/cancelled")
    assert session.added == []


def test_callback_without_state_is_cancelled(app, crypto_enabled) -> None:
    session = _FlowSession(flow=None)
    c = _public_client(app, session)
    r = _callback(c, code="abc")
    assert r.headers["location"].endswith("#integracoes/callback/cancelled")
    assert session.updates == 0


def test_callback_duplicate_park_is_ignored(app, crypto_enabled) -> None:
    """Primeira escrita vence: o segundo park não sobrepõe o código já lá."""
    app_user = make_app_user()
    flow = _flow(app_user_id=uuid.UUID(str(app_user.id)))
    session = _FlowSession(flow=flow)
    c = _public_client(app, session)

    _callback(c, code="primeiro", state=_STATE)
    parked = flow.code_encrypted
    r2 = _callback(c, code="segundo", state=_STATE)

    assert flow.code_encrypted == parked
    assert r2.headers["location"].endswith("#integracoes/callback/ready")


def test_callback_expired_flow_is_noop(app, crypto_enabled) -> None:
    app_user = make_app_user()
    flow = _flow(app_user_id=uuid.UUID(str(app_user.id)), expired=True)
    c = _public_client(app, _FlowSession(flow=flow))

    r = _callback(c, code="abc", state=_STATE)

    assert flow.code_encrypted is None
    assert r.headers["location"].endswith("#integracoes/callback/cancelled")


def test_callback_error_does_not_burn_flow(app, crypto_enabled) -> None:
    """`error` é terminal para a jornada, mas NÃO mata o fluxo.

    Queimar aqui daria a quem tivesse um `state` vazado um DoS sobre um
    consentimento em andamento.
    """
    app_user = make_app_user()
    flow = _flow(app_user_id=uuid.UUID(str(app_user.id)))
    session = _FlowSession(flow=flow)
    c = _public_client(app, session)

    r = _callback(c, state=_STATE, error="access_denied")

    assert flow.consumed_at is None
    assert flow.verifier_encrypted is not None
    assert session.updates == 0  # nenhuma mutação
    assert r.headers["location"].endswith("#integracoes/callback/cancelled")


def test_callback_error_after_park_returns_ready(app, crypto_enabled) -> None:
    """`error` tardio de um state vazado não pode 'cancelar' um fluxo pronto."""
    app_user = make_app_user()
    flow = _flow(
        app_user_id=uuid.UUID(str(app_user.id)), code_encrypted="ja-parkeado"
    )
    c = _public_client(app, _FlowSession(flow=flow))

    r = _callback(c, state=_STATE, error="access_denied")

    assert r.headers["location"].endswith("#integracoes/callback/ready")
    assert flow.consumed_at is None


def test_callback_missing_code_without_park_is_cancelled(app, crypto_enabled) -> None:
    app_user = make_app_user()
    flow = _flow(app_user_id=uuid.UUID(str(app_user.id)))
    session = _FlowSession(flow=flow)
    c = _public_client(app, session)

    r = _callback(c, state=_STATE, code="")

    assert session.updates == 0
    assert r.headers["location"].endswith("#integracoes/callback/cancelled")


def test_callback_status_and_body_are_uniform(app, crypto_enabled) -> None:
    """Conhecido, duplicado, `error` e desconhecido: mesmo status, mesmo corpo."""
    app_user = make_app_user()
    flow = _flow(app_user_id=uuid.UUID(str(app_user.id)))
    c = _public_client(app, _FlowSession(flow=flow))
    known = _callback(c, code="a", state=_STATE)
    dup = _callback(c, code="b", state=_STATE)
    err = _callback(c, state=_STATE, error="access_denied")
    unknown = _public_client(app, _FlowSession(flow=None))
    other = _callback(unknown, code="c", state="nope")

    assert len({r.status_code for r in (known, dup, err, other)}) == 1
    assert len({r.content for r in (known, dup, err, other)}) == 1


def test_callback_db_error_still_redirects(app, crypto_enabled) -> None:
    """O callback nunca devolve 5xx ao navegador que voltou do Google."""
    app_user = make_app_user()
    flow = _flow(app_user_id=uuid.UUID(str(app_user.id)))
    session = _FlowSession(flow=flow, commit_error=RuntimeError("banco fora"))
    c = _public_client(app, session)

    r = _callback(c, code="abc", state=_STATE)

    assert r.status_code in (302, 307)
    assert session.rollbacks == 1


# ---------------------------------------------------------------------------
# finish — identidade, consumo, troca
# ---------------------------------------------------------------------------
def _finish(client: TestClient, secret: str = _FLOW_SECRET) -> httpx.Response:
    return client.post(
        "/calendar/connect/finish", json={"flowSecret": secret}, headers=_AUTH
    )


def _tokens(refresh: str | None = "rt", scope: str | None = None) -> OAuthTokens:
    return OAuthTokens(
        access_token="at", refresh_token=refresh, expires_in=3600, scope=scope
    )


def test_finish_requires_auth(app) -> None:
    c = _client(app, ["admin"], oauth=_FakeOAuth())
    r = c.post("/calendar/connect/finish", json={"flowSecret": _FLOW_SECRET})
    assert r.status_code == 401


def test_finish_forbidden_for_non_admin(app, crypto_enabled) -> None:
    app_user = make_app_user()
    flow = _flow(app_user_id=uuid.UUID(str(app_user.id)), code_encrypted="x")
    session = _FlowSession(app_user=app_user, roles=["lider_celula"], flow=flow)
    c = _client(app, ["lider_celula"], session=session, oauth=_FakeOAuth())
    assert _finish(c).status_code == 403


def test_finish_unknown_flow_secret_is_rejected(app, crypto_enabled) -> None:
    session = _FlowSession(app_user=make_app_user(), roles=["admin"], flow=None)
    c = _client(app, ["admin"], session=session, oauth=_FakeOAuth())
    assert _finish(c).status_code == 409


def test_finish_rejects_other_admin_same_igreja(app, crypto_enabled) -> None:
    """T2: outro admin da MESMA igreja não conclui o fluxo do colega."""
    app_user = make_app_user()
    flow = _flow(app_user_id=uuid.uuid4(), code_encrypted="x")  # iniciado por outro
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow)
    oauth = _FakeOAuth(tokens=_tokens())
    c = _client(app, ["admin"], session=session, oauth=oauth)

    r = _finish(c)

    assert r.status_code == 409
    assert oauth.exchanges == []  # nunca falou com o Google
    assert flow.consumed_at is not None  # e queimou o fluxo
    assert flow.verifier_encrypted is None
    assert session.added == []


def test_finish_rejects_other_igreja(app, crypto_enabled) -> None:
    app_user = make_app_user()
    flow = _flow(
        app_user_id=uuid.UUID(str(app_user.id)),
        igreja_id=_OUTRA_IGREJA,
        code_encrypted="x",
    )
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow)
    oauth = _FakeOAuth(tokens=_tokens())
    c = _client(app, ["admin"], session=session, oauth=oauth)

    r = _finish(c)

    assert r.status_code == 409
    assert oauth.exchanges == []
    assert flow.consumed_at is not None


def test_finish_replay_is_rejected(app, crypto_enabled) -> None:
    app_user = make_app_user()
    flow = _flow(
        app_user_id=uuid.UUID(str(app_user.id)),
        code_encrypted="x",
        consumed_at=dt.datetime.now(dt.timezone.utc),
    )
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow)
    oauth = _FakeOAuth(tokens=_tokens())
    c = _client(app, ["admin"], session=session, oauth=oauth)

    assert _finish(c).status_code == 409
    assert oauth.exchanges == []


def test_finish_rejects_expired_flow(app, crypto_enabled) -> None:
    app_user = make_app_user()
    flow = _flow(
        app_user_id=uuid.UUID(str(app_user.id)), code_encrypted="x", expired=True
    )
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow)
    oauth = _FakeOAuth(tokens=_tokens())
    c = _client(app, ["admin"], session=session, oauth=oauth)

    assert _finish(c).status_code == 409
    assert oauth.exchanges == []
    assert flow.consumed_at is not None  # queimado


def test_finish_without_parked_code_is_non_consuming(app, crypto_enabled) -> None:
    """202: reload/back antes do callback. NÃO consome e não vira polling."""
    app_user = make_app_user()
    flow = _flow(app_user_id=uuid.UUID(str(app_user.id)), code_encrypted=None)
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow)
    oauth = _FakeOAuth(tokens=_tokens())
    c = _client(app, ["admin"], session=session, oauth=oauth)

    r = _finish(c)

    assert r.status_code == 202
    assert r.json()["status"] == "aguardando_callback"
    assert r.json()["connected"] is False
    assert flow.consumed_at is None
    assert flow.verifier_encrypted is not None
    assert oauth.exchanges == []


def test_finish_non_consuming_only_after_identity_check(app, crypto_enabled) -> None:
    """Sem code E identidade errada => 409, nunca 202 (senão vira oráculo)."""
    app_user = make_app_user()
    flow = _flow(app_user_id=uuid.uuid4(), code_encrypted=None)
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow)
    c = _client(app, ["admin"], session=session, oauth=_FakeOAuth(tokens=_tokens()))

    assert _finish(c).status_code == 409


def test_finish_burns_before_exchange(app, crypto_enabled) -> None:
    """O fluxo é consumido ANTES da chamada de 15s ao Google."""
    app_user = make_app_user()
    flow = _flow(
        app_user_id=uuid.UUID(str(app_user.id)),
        verifier_encrypted=crypto_enabled.encrypt_secret("verifier-real"),
        code_encrypted=crypto_enabled.encrypt_secret("code-real"),
    )
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow)
    seen: dict = {}

    class _Checking(_FakeOAuth):
        def exchange_code(self, code, code_verifier):
            seen["consumed_at"] = flow.consumed_at
            seen["verifier_encrypted"] = flow.verifier_encrypted
            return super().exchange_code(code, code_verifier)

    oauth = _Checking(tokens=_tokens())
    c = _client(app, ["admin"], session=session, oauth=oauth)

    assert _finish(c).status_code == 200
    assert seen["consumed_at"] is not None
    assert seen["verifier_encrypted"] is None
    # o verifier decifrado é o que vai ao Google, junto do code decifrado
    assert oauth.exchanges == [("code-real", "verifier-real")]


def test_finish_persists_encrypted_tokens(app, crypto_enabled) -> None:
    app_user = make_app_user()
    flow = _flow(
        app_user_id=uuid.UUID(str(app_user.id)),
        verifier_encrypted=crypto_enabled.encrypt_secret("v"),
        code_encrypted=crypto_enabled.encrypt_secret("c"),
    )
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow)
    c = _client(app, ["admin"], session=session, oauth=_FakeOAuth(tokens=_tokens()))

    r = _finish(c)

    assert r.status_code == 200
    assert r.json() == {"status": "conectado", "connected": True, "calendarId": None}
    assert len(session.added) == 1
    sync = session.added[0]
    assert sync.refresh_token_encrypted and sync.refresh_token_encrypted != "rt"
    assert sync.access_token_encrypted and sync.access_token_encrypted != "at"


def test_finish_google_failure_does_not_write(app, crypto_enabled) -> None:
    app_user = make_app_user()
    flow = _flow(
        app_user_id=uuid.UUID(str(app_user.id)),
        verifier_encrypted=crypto_enabled.encrypt_secret("v"),
        code_encrypted=crypto_enabled.encrypt_secret("c"),
    )
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow)
    oauth = _FakeOAuth(
        tokens=_tokens(), exchange_error=GoogleOAuthError("invalid_grant")
    )
    c = _client(app, ["admin"], session=session, oauth=oauth)

    assert _finish(c).status_code == 409
    assert session.added == []  # nada em calendar_sync
    assert flow.consumed_at is not None  # o fluxo morreu junto


def test_finish_rejects_when_calendar_list_forbidden(app, crypto_enabled) -> None:
    """Probe de capacidade: `connected` só é verdade se der para LER."""
    app_user = make_app_user()
    flow = _flow(
        app_user_id=uuid.UUID(str(app_user.id)),
        verifier_encrypted=crypto_enabled.encrypt_secret("v"),
        code_encrypted=crypto_enabled.encrypt_secret("c"),
    )
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow)
    oauth = _FakeOAuth(
        tokens=_tokens(), list_error=GoogleOAuthError("Falha ao listar as agendas")
    )
    c = _client(app, ["admin"], session=session, oauth=oauth)

    assert _finish(c).status_code == 409
    assert session.added == []


def test_finish_accepts_when_scope_field_absent(app, crypto_enabled) -> None:
    """`scope` ausente NUNCA reprova sozinho — a semântica não é garantida."""
    app_user = make_app_user()
    flow = _flow(
        app_user_id=uuid.UUID(str(app_user.id)),
        verifier_encrypted=crypto_enabled.encrypt_secret("v"),
        code_encrypted=crypto_enabled.encrypt_secret("c"),
    )
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow)
    c = _client(
        app, ["admin"], session=session, oauth=_FakeOAuth(tokens=_tokens(scope=None))
    )

    assert _finish(c).status_code == 200


def test_finish_first_connection_without_refresh_token_does_not_persist(
    app, crypto_enabled
) -> None:
    """Primeira conexão sem refresh_token: nada de linha meia-conectada."""
    app_user = make_app_user()
    flow = _flow(
        app_user_id=uuid.UUID(str(app_user.id)),
        verifier_encrypted=crypto_enabled.encrypt_secret("v"),
        code_encrypted=crypto_enabled.encrypt_secret("c"),
    )
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow, sync=None)
    c = _client(
        app, ["admin"], session=session, oauth=_FakeOAuth(tokens=_tokens(refresh=None))
    )

    assert _finish(c).status_code == 409
    assert session.added == []


def test_finish_reconnection_without_refresh_token_preserves_existing(
    app, crypto_enabled
) -> None:
    app_user = make_app_user()
    flow = _flow(
        app_user_id=uuid.UUID(str(app_user.id)),
        verifier_encrypted=crypto_enabled.encrypt_secret("v"),
        code_encrypted=crypto_enabled.encrypt_secret("c"),
    )
    sync = SimpleNamespace(
        refresh_token_encrypted="refresh-antigo",
        access_token_encrypted="access-antigo",
        access_token_expira_em=None,
        google_calendar_id="cal@x",
        atualizado_em=None,
    )
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow, sync=sync)
    c = _client(
        app, ["admin"], session=session, oauth=_FakeOAuth(tokens=_tokens(refresh=None))
    )

    r = _finish(c)

    assert r.status_code == 200
    assert r.json()["calendarId"] == "cal@x"
    assert sync.refresh_token_encrypted == "refresh-antigo"  # preservado
    assert sync.access_token_encrypted != "access-antigo"  # access atualizado
    assert session.added == []  # reusou a linha existente


def test_finish_rejection_bodies_are_identical(app, crypto_enabled) -> None:
    """Todos os 409 têm o MESMO corpo — sem oráculo de causa."""
    app_user = make_app_user()
    bodies = set()
    for flow in (
        None,
        _flow(app_user_id=uuid.uuid4(), code_encrypted="x"),
        _flow(
            app_user_id=uuid.UUID(str(app_user.id)),
            igreja_id=_OUTRA_IGREJA,
            code_encrypted="x",
        ),
        _flow(
            app_user_id=uuid.UUID(str(app_user.id)), code_encrypted="x", expired=True
        ),
    ):
        session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow)
        c = _client(app, ["admin"], session=session, oauth=_FakeOAuth(tokens=_tokens()))
        r = _finish(c)
        assert r.status_code == 409
        bodies.add(r.content)
    assert len(bodies) == 1


# ---------------------------------------------------------------------------
# finish EXIGE o flowSecret — PR222-OPTIONAL-SECRET-SECURITY-FIX-1
#
# A retomada por identidade (achar o fluxo por app_user_id + igreja_id, sem
# segredo) foi REMOVIDA. Ela transformava a posse de um `state` vazado em
# vinculação de conta SILENCIOSA: bastava um terceiro abrir a URL de autorização
# ORIGINAL noutro navegador, consentir com a conta Google dele, o callback
# público estacionar o `code` — e a vítima abrir Integrações. Sem clique, sem
# marcador de retorno. PKCE não barra isso: o code sai amarrado ao MESMO
# `code_challenge`, então a troca sucede.
#
# Identidade prova apenas QUEM finaliza, nunca QUAL conta Google consentiu.
# ---------------------------------------------------------------------------
def test_pending_flow_helper_no_longer_exists() -> None:
    """Nenhum caminho pode achar fluxo só por identidade."""
    from app.routers import calendar as calendar_router

    assert not hasattr(calendar_router, "_pending_flow_for_user")


@pytest.mark.parametrize(
    "body", [{}, {"flowSecret": None}, {"flowSecret": ""}], ids=["ausente", "nulo", "vazio"]
)
def test_finish_without_secret_never_touches_the_flow(app, crypto_enabled, body) -> None:
    """Sem segredo: 422 do schema, sem SELECT, sem lock, sem consumo."""
    app_user = make_app_user()
    parked = _flow(app_user_id=uuid.UUID(str(app_user.id)), code_encrypted="x")
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=parked)
    oauth = _FakeOAuth(tokens=_tokens())
    c = _client(app, ["admin"], session=session, oauth=oauth)

    r = c.post("/calendar/connect/finish", json=body, headers=_AUTH)

    assert r.status_code == 422
    assert session.flow_lookups == 0  # nem leu a tabela
    assert oauth.exchanges == []
    assert parked.consumed_at is None
    assert parked.code_encrypted == "x"


def test_finish_with_correct_secret_and_identity_connects(app, crypto_enabled) -> None:
    """Caminho feliz: posse do segredo + identidade correta conclui."""
    app_user = make_app_user()
    flow = _flow(
        app_user_id=uuid.UUID(str(app_user.id)),
        verifier_encrypted=crypto_enabled.encrypt_secret("verifier-real"),
        code_encrypted=crypto_enabled.encrypt_secret("code-real"),
    )
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=flow)
    oauth = _FakeOAuth(tokens=_tokens())
    c = _client(app, ["admin"], session=session, oauth=oauth)

    r = _finish(c)

    assert r.status_code == 200
    assert r.json()["status"] == "conectado"
    assert session.flow_lookups == 1
    assert oauth.exchanges == [("code-real", "verifier-real")]
    assert flow.consumed_at is not None


# ---------------------------------------------------------------------------
# REGRESSÃO DE SEGURANÇA — account-linking silencioso
# ---------------------------------------------------------------------------
def test_parked_code_is_not_consumed_when_the_panel_has_no_secret(
    app, crypto_enabled
) -> None:
    """A vítima abrir Integrações sem segredo NÃO pode concluir nada.

    Cenário: um terceiro abriu a URL de autorização da vítima noutro navegador,
    consentiu com OUTRA conta Google, e o callback público estacionou o `code` no
    fluxo da vítima. A vítima então abre a tela — o painel não tem `flowSecret`
    (PWA relançada, retorno caído no Safari, storage limpo).

    Exigido, ponto a ponto:
      * nenhum token trocado com o Google;
      * nenhum `calendar_sync` criado ou alterado;
      * o fluxo permanece NÃO consumido, com o `code` intacto (morre no TTL).
    """
    app_user = make_app_user()
    parked = _flow(
        app_user_id=uuid.UUID(str(app_user.id)),
        verifier_encrypted=crypto_enabled.encrypt_secret("verifier-da-vitima"),
        code_encrypted=crypto_enabled.encrypt_secret("code-do-terceiro"),
    )
    session = _FlowSession(app_user=app_user, roles=["admin"], flow=parked, sync=None)
    oauth = _FakeOAuth(tokens=_tokens())
    c = _client(app, ["admin"], session=session, oauth=oauth)

    r = c.post("/calendar/connect/finish", json={}, headers=_AUTH)

    assert r.status_code == 422
    assert oauth.exchanges == []  # nenhum token trocado
    assert oauth.listed_tokens == []  # nem o probe de capacidade
    assert session.added == []  # nenhum CalendarSync criado
    assert session.sync is None  # nem alterado
    assert session.commits == 0  # nada persistido
    assert parked.consumed_at is None  # fluxo intacto...
    assert parked.code_encrypted is not None  # ...com o code ainda estacionado
    assert parked.verifier_encrypted is not None
    assert session.flow_lookups == 0


# ---------------------------------------------------------------------------
# status / select / disconnect (inalterados pelo V1)
# ---------------------------------------------------------------------------
def test_status_not_connected(app) -> None:
    session = _FlowSession(app_user=make_app_user(), roles=["admin"], sync=None)
    c = _client(app, ["admin"], session=session)
    r = c.get("/calendar/status", headers=_AUTH)
    assert r.status_code == 200
    assert r.json() == {"connected": False, "calendarId": None}


def test_status_connected(app) -> None:
    sync = SimpleNamespace(refresh_token_encrypted="enc", google_calendar_id="cal@x")
    session = _FlowSession(app_user=make_app_user(), roles=["admin"], sync=sync)
    c = _client(app, ["admin"], session=session)
    assert c.get("/calendar/status", headers=_AUTH).json() == {
        "connected": True,
        "calendarId": "cal@x",
    }


def test_select_calendar_sets_id(app) -> None:
    sync = SimpleNamespace(
        refresh_token_encrypted="enc", google_calendar_id=None, atualizado_em=None
    )
    session = _FlowSession(app_user=make_app_user(), roles=["admin"], sync=sync)
    c = _client(app, ["admin"], session=session)
    r = c.put("/calendar", json={"calendarId": "cal@new"}, headers=_AUTH)
    assert r.status_code == 200
    assert sync.google_calendar_id == "cal@new"
    assert session.commits == 1


def test_select_calendar_requires_connection(app) -> None:
    session = _FlowSession(app_user=make_app_user(), roles=["admin"], sync=None)
    c = _client(app, ["admin"], session=session)
    assert c.put("/calendar", json={"calendarId": "x"}, headers=_AUTH).status_code == 409


def test_disconnect_deletes(app) -> None:
    sync = SimpleNamespace(refresh_token_encrypted="enc")
    session = _FlowSession(app_user=make_app_user(), roles=["admin"], sync=sync)
    c = _client(app, ["admin"], session=session)
    assert c.delete("/calendar", headers=_AUTH).status_code == 204
    assert session.deleted == [sync]


# ---------------------------------------------------------------------------
# import/preview + import (inalterados pelo V1)
# ---------------------------------------------------------------------------
def _connected_sync(crypto, *, calendar_id="cal@x"):
    return SimpleNamespace(
        refresh_token_encrypted=crypto.encrypt_secret("rt"),
        access_token_encrypted=None,
        access_token_expira_em=None,
        google_calendar_id=calendar_id,
        atualizado_em=None,
    )


def _preview_ev(gid, *, titulo="Culto", data="2026-07-05", hora="19:00"):
    return {
        "googleEventId": gid,
        "titulo": titulo,
        "descricao": None,
        "data": data,
        "hora": hora,
        "fim": None,
        "recorrente": False,
    }


def _import_oauth(events):
    return _FakeOAuth(tokens=_tokens(refresh=None), events=events)


def test_import_preview_forbidden_for_non_privileged(app) -> None:
    c = _client(app, ["lider_celula"], oauth=_FakeOAuth())
    assert c.get("/calendar/import/preview", headers=_AUTH).status_code == 403


def test_import_preview_not_connected_returns_409(app) -> None:
    session = _FlowSession(app_user=make_app_user(), roles=["pastor"], sync=None)
    c = _client(app, ["pastor"], session=session, oauth=_FakeOAuth())
    assert c.get("/calendar/import/preview", headers=_AUTH).status_code == 409


def test_import_preview_returns_events_without_persisting(app, crypto_enabled) -> None:
    sync = _connected_sync(crypto_enabled)
    oauth = _import_oauth([_preview_ev("g1")])
    session = _FlowSession(app_user=make_app_user(), roles=["pastor"], sync=sync)
    c = _client(app, ["pastor"], session=session, oauth=oauth)

    r = c.get("/calendar/import/preview", headers=_AUTH)

    assert r.status_code == 200
    assert r.json()["events"][0]["googleEventId"] == "g1"
    assert oauth.refreshed is True
    assert oauth.list_events_args[1] == "cal@x"
    assert session.added == []


def test_import_creates_pending_google_events(app, crypto_enabled) -> None:
    sync = _connected_sync(crypto_enabled)
    oauth = _import_oauth([_preview_ev("g1"), _preview_ev("g2", hora=None)])
    session = _FlowSession(app_user=make_app_user(), roles=["pastor"], sync=sync)
    c = _client(app, ["pastor"], session=session, oauth=oauth)

    body = c.post("/calendar/import", headers=_AUTH).json()

    assert body["created"] == 2
    for ev in session.added:
        assert ev.status == "a_confirmar"
        assert ev.origem == "google"
        assert ev.igreja_id == uuid.UUID(_IGREJA)


def test_import_skips_already_imported(app, crypto_enabled) -> None:
    sync = _connected_sync(crypto_enabled)
    oauth = _import_oauth([_preview_ev("g1"), _preview_ev("g2")])
    session = _FlowSession(
        app_user=make_app_user(), roles=["pastor"], sync=sync, existing_gids=["g1"]
    )
    c = _client(app, ["pastor"], session=session, oauth=oauth)

    body = c.post("/calendar/import", headers=_AUTH).json()

    assert (body["created"], body["skipped"]) == (1, 1)
    assert [ev.google_event_id for ev in session.added] == ["g2"]


def test_import_other_tenant_same_gid_not_blocked(app, crypto_enabled) -> None:
    sync = _connected_sync(crypto_enabled)
    session = _FlowSession(
        app_user=make_app_user(), roles=["pastor"], sync=sync, existing_gids=[]
    )
    c = _client(
        app, ["pastor"], session=session, oauth=_import_oauth([_preview_ev("g1")])
    )

    assert c.post("/calendar/import", headers=_AUTH).json()["created"] == 1
    where_sql = str(getattr(session.last_event_stmt, "whereclause", ""))
    assert "events.igreja_id" in where_sql
    assert "events.google_event_id" in where_sql


def test_import_skips_event_without_date(app, crypto_enabled) -> None:
    sync = _connected_sync(crypto_enabled)
    no_date = _preview_ev("g1")
    no_date["data"] = None
    session = _FlowSession(app_user=make_app_user(), roles=["pastor"], sync=sync)
    c = _client(
        app,
        ["pastor"],
        session=session,
        oauth=_import_oauth([no_date, _preview_ev("g2", data="2026-07-08")]),
    )

    body = c.post("/calendar/import", headers=_AUTH).json()

    assert (body["created"], body["skipped"]) == (1, 1)
    assert [ev.google_event_id for ev in session.added] == ["g2"]


def test_import_does_not_autoconfirm_or_notify(app, crypto_enabled) -> None:
    sync = _connected_sync(crypto_enabled)
    session = _FlowSession(app_user=make_app_user(), roles=["pastor"], sync=sync)
    c = _client(
        app, ["pastor"], session=session, oauth=_import_oauth([_preview_ev("g1")])
    )

    c.post("/calendar/import", headers=_AUTH)

    ev = session.added[0]
    assert ev.status == "a_confirmar"
    assert ev.confirmado_em is None and ev.confirmado_por is None


# ---------------------------------------------------------------------------
# GoogleOAuthClient — caminho HTTP real (transporte dublado, sem Google)
# ---------------------------------------------------------------------------
def _use_transport(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    real = httpx.Client

    def fake(*args, **kwargs):
        kwargs.pop("transport", None)
        return real(*args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "Client", fake)


def _configured_client() -> GoogleOAuthClient:
    return GoogleOAuthClient(
        settings=Settings(
            session_jwt_secret="x" * 32,
            google_oauth_client_id="cid",
            google_oauth_client_secret="sec",
            google_oauth_redirect_uri="https://api.igreja12.com.br/calendar/callback",
        )
    )


def test_consent_url_carries_pkce_and_offline_access() -> None:
    url = _configured_client().build_consent_url(state="opaco", code_challenge="chal")
    assert "client_id=cid" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=opaco" in url
    assert "code_challenge=chal" in url
    assert "code_challenge_method=S256" in url


def test_consent_url_raises_without_config() -> None:
    oauth = GoogleOAuthClient(settings=Settings(session_jwt_secret="x" * 32))
    with pytest.raises(GoogleOAuthError):
        oauth.build_consent_url(state="s", code_challenge="c")


def test_exchange_code_sends_the_verifier(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/calendar.readonly",
            },
        )

    _use_transport(monkeypatch, handler)
    tokens = _configured_client().exchange_code("the-code", "the-verifier")

    assert "code_verifier=the-verifier" in captured["body"]
    assert "the-code" in captured["body"]
    assert tokens.scope == "https://www.googleapis.com/auth/calendar.readonly"


def test_exchange_code_invalid_grant_becomes_controlled_error(monkeypatch) -> None:
    """Code injetado: o Google recusa e nós normalizamos, sem vazar detalhe."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    _use_transport(monkeypatch, handler)
    with pytest.raises(GoogleOAuthError):
        _configured_client().exchange_code("roubado", "verifier-de-outro-fluxo")


def test_list_events_is_read_only_and_normalizes(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
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
                        "start": {"dateTime": "2026-07-05T19:00:00-03:00"},
                        "end": {"dateTime": "2026-07-05T20:30:00-03:00"},
                    },
                    {
                        "id": "allday1",
                        "summary": "Feriado",
                        "start": {"date": "2026-07-09"},
                        "end": {"date": "2026-07-10"},
                    },
                    {"id": "cancelled1", "status": "cancelled", "start": {}},
                ]
            },
        )

    _use_transport(monkeypatch, handler)
    oauth = GoogleOAuthClient(
        settings=Settings(
            session_jwt_secret="x" * 32, google_calendar_access_token="GLOBAL-LEAK"
        )
    )
    out = oauth.list_events(
        "per-igreja-tok", "primary", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"
    )

    assert captured["method"] == "GET"
    assert captured["params"]["singleEvents"] == "true"
    assert captured["auth"] == "Bearer per-igreja-tok"
    assert "GLOBAL-LEAK" not in (captured["auth"] or "")
    assert captured["body"] == b""
    assert [e["googleEventId"] for e in out] == ["timed1", "allday1"]


def test_list_events_escapes_the_calendar_id(monkeypatch) -> None:
    """O calendarId vem do que o admin escolheu — não pode sair do segmento."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"items": []})

    _use_transport(monkeypatch, handler)
    oauth = GoogleOAuthClient(settings=Settings(session_jwt_secret="x" * 32))
    oauth.list_events("tok", "a/../b", "t0", "t1")

    assert "/calendars/a%2F..%2Fb/events" in captured["url"]


def test_list_events_http_error_is_controlled(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    _use_transport(monkeypatch, handler)
    oauth = GoogleOAuthClient(settings=Settings(session_jwt_secret="x" * 32))
    with pytest.raises(GoogleOAuthError):
        oauth.list_events("tok", "primary", "t0", "t1")
