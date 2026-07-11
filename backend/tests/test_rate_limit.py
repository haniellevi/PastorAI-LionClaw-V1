"""SEC-2: rate limiting nos endpoints de autenticação (ALTO-002).

Cobre o ``RateLimiter`` isoladamente (com um Redis fake em memória) e os
endpoints reais via ``TestClient`` (login/forgot-password): abaixo do limite
passa, acima devolve 429 com ``Retry-After``, o kill switch desliga tudo sem
tocar Redis, a resposta de 429 nunca revela se a conta existe, e uma falha do
Redis nunca derruba o login (fail-open — infra instável não é motivo pra
travar autenticação).
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from app.services.rate_limit import (
    RateLimiter,
    RateLimitExceeded,
    client_ip,
    get_rate_limiter,
)
from tests.conftest import FakeClerk, FakeSession, make_app_user
from tests.test_platform_admin import PlatformDB


class FakeRedis:
    """Redis fake em memória — só o subconjunto usado pelo RateLimiter."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttl: dict[str, int] = {}

    def incr(self, key: str) -> int:
        value = int(self._store.get(key, "0")) + 1
        self._store[key] = str(value)
        return value

    def expire(self, key: str, seconds: int) -> None:
        self._ttl[key] = seconds

    def ttl(self, key: str) -> int:
        return self._ttl.get(key, -1) if key in self._store else -2

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value
        if ex is not None:
            self._ttl[key] = ex

    def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._ttl.pop(key, None)


class BrokenRedis:
    """Simula Redis indisponível — todo comando explode."""

    def _boom(self, *_args, **_kwargs):
        raise ConnectionError("redis down")

    incr = _boom
    expire = _boom
    ttl = _boom
    set = _boom
    delete = _boom


def _fake_request(ip: str = "203.0.113.9") -> Request:
    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", ip.encode())],
        "client": (ip, 12345),
    }
    return Request(scope)


def _enable(monkeypatch, **overrides) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_auth_enabled", True, raising=False)
    for name, value in overrides.items():
        monkeypatch.setattr(settings, name, value, raising=False)


# ---- Unit: client_ip ---------------------------------------------------------


def test_client_ip_uses_last_hop_not_client_supplied_first_hop() -> None:
    # O primeiro valor (1.2.3.4) é o que o cliente mandou — forjável. O nosso
    # proxy acrescenta o peer real ao final; é esse o valor confiável.
    request = _fake_request(ip="1.2.3.4, 10.0.0.9, 203.0.113.7")
    assert client_ip(request) == "203.0.113.7"


# ---- Unit: RateLimiter ------------------------------------------------------


def test_below_limit_passes(monkeypatch) -> None:
    _enable(monkeypatch)
    limiter = RateLimiter(redis_client=FakeRedis())
    request = _fake_request()
    for _ in range(3):
        limiter.enforce_ip(request, "scope", limit=3)  # não levanta


def test_above_ip_limit_raises_with_retry_after(monkeypatch) -> None:
    _enable(monkeypatch)
    limiter = RateLimiter(redis_client=FakeRedis())
    request = _fake_request()
    for _ in range(3):
        limiter.enforce_ip(request, "scope", limit=3)
    with pytest.raises(RateLimitExceeded) as exc_info:
        limiter.enforce_ip(request, "scope", limit=3)
    assert exc_info.value.retry_after >= 1


def test_account_block_persists_once_triggered(monkeypatch) -> None:
    _enable(monkeypatch)
    limiter = RateLimiter(redis_client=FakeRedis())
    for _ in range(2):
        limiter.enforce_account("a@b.com", "scope", limit=2)
    with pytest.raises(RateLimitExceeded):
        limiter.enforce_account("a@b.com", "scope", limit=2)
    # Bloqueio ativo: a tentativa seguinte continua barrada, não reabre janela.
    with pytest.raises(RateLimitExceeded):
        limiter.enforce_account("a@b.com", "scope", limit=2)


def test_account_key_never_stores_plaintext_email(monkeypatch) -> None:
    _enable(monkeypatch)
    fake = FakeRedis()
    limiter = RateLimiter(redis_client=fake)
    limiter.enforce_account("someone@example.com", "scope", limit=5)
    assert not any("someone@example.com" in key for key in fake._store)


def test_disabled_flag_bypasses_ip_and_account(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_auth_enabled", False, raising=False)
    limiter = RateLimiter(redis_client=FakeRedis())
    request = _fake_request()
    for _ in range(50):
        limiter.enforce_ip(request, "scope", limit=1)
        limiter.enforce_account("a@b.com", "scope", limit=1)


def test_redis_unavailable_fails_open(monkeypatch) -> None:
    _enable(monkeypatch)
    limiter = RateLimiter(redis_client=BrokenRedis())
    request = _fake_request()
    for _ in range(5):
        limiter.enforce_ip(request, "scope", limit=1)
        limiter.enforce_account("a@b.com", "scope", limit=1)


# ---- Endpoint: /auth/login ---------------------------------------------------


def _client(app, *, session: FakeSession, clerk: FakeClerk, limiter: RateLimiter) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    return TestClient(app)


def test_login_returns_429_after_ip_limit(app, monkeypatch) -> None:
    _enable(
        monkeypatch,
        rate_limit_login_ip_limit=2,
        rate_limit_login_account_limit=100,
    )
    limiter = RateLimiter(redis_client=FakeRedis())
    client = _client(
        app,
        session=FakeSession(app_user=None),
        clerk=FakeClerk(raise_login=True),
        limiter=limiter,
    )
    body = {"email": "unknown@example.com", "password": "wrong"}
    for _ in range(2):
        assert client.post("/auth/login", json=body).status_code == 401
    resp = client.post("/auth/login", json=body)
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1
    assert resp.json()["detail"] == "Muitas tentativas. Tente novamente mais tarde."


def test_login_429_identical_for_unknown_and_known_account(app, monkeypatch) -> None:
    _enable(
        monkeypatch,
        rate_limit_login_ip_limit=1000,
        rate_limit_login_account_limit=1,
    )

    def _exhaust(email: str, *, exists: bool):
        limiter = RateLimiter(redis_client=FakeRedis())
        session = FakeSession(app_user=make_app_user() if exists else None)
        clerk = (
            FakeClerk(login_result=("tok", "clerk_user_1"))
            if exists
            else FakeClerk(raise_login=True)
        )
        client = _client(app, session=session, clerk=clerk, limiter=limiter)
        body = {"email": email, "password": "whatever1"}
        client.post("/auth/login", json=body)  # consome a única tentativa liberada
        return client.post("/auth/login", json=body)  # deve vir 429

    resp_unknown = _exhaust("ghost@example.com", exists=False)
    resp_known = _exhaust("pastor@igrejapiloto.com", exists=True)
    assert resp_unknown.status_code == resp_known.status_code == 429
    assert resp_unknown.json() == resp_known.json()


def test_login_bypasses_rate_limit_when_disabled(app, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_auth_enabled", False, raising=False)
    monkeypatch.setattr(get_settings(), "rate_limit_login_ip_limit", 1, raising=False)
    limiter = RateLimiter(redis_client=FakeRedis())
    client = _client(
        app,
        session=FakeSession(app_user=None),
        clerk=FakeClerk(raise_login=True),
        limiter=limiter,
    )
    body = {"email": "unknown@example.com", "password": "wrong"}
    for _ in range(5):
        assert client.post("/auth/login", json=body).status_code == 401


def test_login_succeeds_when_redis_down(app, monkeypatch) -> None:
    _enable(monkeypatch, rate_limit_login_ip_limit=1)
    limiter = RateLimiter(redis_client=BrokenRedis())
    user = make_app_user()
    client = _client(
        app,
        session=FakeSession(app_user=user, roles=["admin"]),
        clerk=FakeClerk(login_result=("tok", "clerk_user_1")),
        limiter=limiter,
    )
    body = {"email": "pastor@igrejapiloto.com", "password": "secret"}
    for _ in range(3):
        assert client.post("/auth/login", json=body).status_code == 200


# ---- Endpoint: /auth/forgot-password -----------------------------------------


class _UnknownEmailClerk:
    """Stub mínimo: e-mail nunca encontrado, sem tocar Clerk/Brevo de verdade."""

    def find_user_id_by_email(self, email: str) -> str | None:
        return None


def test_forgot_password_returns_429_after_account_limit(app, monkeypatch) -> None:
    _enable(
        monkeypatch,
        rate_limit_forgot_password_ip_limit=1000,
        rate_limit_forgot_password_account_limit=1,
    )
    limiter = RateLimiter(redis_client=FakeRedis())
    client = _client(
        app,
        session=FakeSession(app_user=None),
        clerk=_UnknownEmailClerk(),
        limiter=limiter,
    )
    body = {"email": "unknown@example.com"}
    assert client.post("/auth/forgot-password", json=body).status_code == 200
    resp = client.post("/auth/forgot-password", json=body)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


# ---- Endpoint: /admin/login (console master, SEC-2b) -------------------------
#
# O login do Master da plataforma (painel.igreja12.com.br) autentica senha e é
# cross-tenant/BYPASSRLS — a superfície de MAIOR privilégio. ALTO-002 só cablou
# rate limiting em /auth/*; aqui provamos que /admin/login também é limitado, em
# namespace 'platform-login' SEPARADO do login do tenant, antes de tocar o Clerk.


class _CountingClerk(FakeClerk):
    """FakeClerk que conta authenticate_password — prova que o Clerk NÃO é
    chamado quando a requisição é barrada pelo limiter (429)."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.login_calls = 0

    def authenticate_password(self, email: str, password: str):
        self.login_calls += 1
        return super().authenticate_password(email, password)


def _admin_client(app, *, db, clerk, limiter: RateLimiter) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    return TestClient(app)


def _master_db() -> PlatformDB:
    return PlatformDB(gate_app_user=make_app_user(), admin_marker="pa1")


def test_admin_login_returns_429_after_ip_limit(app, monkeypatch) -> None:
    _enable(
        monkeypatch,
        rate_limit_login_ip_limit=2,
        rate_limit_login_account_limit=100,
    )
    limiter = RateLimiter(redis_client=FakeRedis())
    clerk = _CountingClerk(raise_login=True)
    client = _admin_client(app, db=_master_db(), clerk=clerk, limiter=limiter)
    body = {"email": "master@x.com", "password": "wrong"}
    for _ in range(2):  # dentro do limite: chega ao Clerk (401 genérico)
        assert client.post("/admin/login", json=body).status_code == 401
    resp = client.post("/admin/login", json=body)  # excedente
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1
    assert resp.json()["detail"] == "Muitas tentativas. Tente novamente mais tarde."
    # Prova: o Clerk foi chamado só nas 2 liberadas, NUNCA na bloqueada.
    assert clerk.login_calls == 2


def test_admin_login_returns_429_after_account_limit(app, monkeypatch) -> None:
    # Mesma conta em IPs diferentes: o limite por conta barra mesmo trocando de IP.
    _enable(
        monkeypatch,
        rate_limit_login_ip_limit=1000,
        rate_limit_login_account_limit=1,
    )
    limiter = RateLimiter(redis_client=FakeRedis())
    clerk = _CountingClerk(raise_login=True)
    client = _admin_client(app, db=_master_db(), clerk=clerk, limiter=limiter)
    body = {"email": "master@x.com", "password": "wrong"}
    assert (
        client.post(
            "/admin/login", json=body, headers={"X-Forwarded-For": "203.0.113.1"}
        ).status_code
        == 401
    )
    resp = client.post(
        "/admin/login", json=body, headers={"X-Forwarded-For": "203.0.113.2"}
    )
    assert resp.status_code == 429
    assert clerk.login_calls == 1  # a bloqueada por conta não tocou o Clerk


def test_admin_login_namespace_separate_from_tenant_login(app, monkeypatch) -> None:
    # O contador de /admin/login NÃO pode ser compartilhado com /auth/login:
    # esgotar um não pode bloquear o outro.
    _enable(
        monkeypatch,
        rate_limit_login_ip_limit=1,
        rate_limit_login_account_limit=1000,
    )
    limiter = RateLimiter(redis_client=FakeRedis())  # MESMO limiter/redis nos dois
    body = {"email": "master@x.com", "password": "wrong"}
    admin = _admin_client(
        app, db=_master_db(), clerk=FakeClerk(raise_login=True), limiter=limiter
    )
    assert admin.post("/admin/login", json=body).status_code == 401
    assert admin.post("/admin/login", json=body).status_code == 429  # admin barrado
    # Mesmo limiter/redis, mas /auth/login usa scope 'login' (chave distinta):
    # segue liberado, provando namespaces separados.
    app.dependency_overrides[get_db] = lambda: FakeSession(app_user=None)
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk(raise_login=True)
    tenant = TestClient(app)
    assert tenant.post("/auth/login", json=body).status_code == 401


def test_admin_login_429_identical_regardless_of_account(app, monkeypatch) -> None:
    # Não-enumeração: o 429 é idêntico para conta master, conta comum ou
    # inexistente — nunca revela senha vs conta vs permissão de plataforma.
    _enable(
        monkeypatch,
        rate_limit_login_ip_limit=1000,
        rate_limit_login_account_limit=1,
    )

    def _exhaust(email: str, *, is_master: bool):
        limiter = RateLimiter(redis_client=FakeRedis())
        db = PlatformDB(
            gate_app_user=make_app_user(), admin_marker="pa1" if is_master else None
        )
        clerk = FakeClerk() if is_master else FakeClerk(raise_login=True)
        client = _admin_client(app, db=db, clerk=clerk, limiter=limiter)
        b = {"email": email, "password": "x"}
        client.post("/admin/login", json=b)  # consome a única liberada
        return client.post("/admin/login", json=b)  # 429

    resp_master = _exhaust("master@x.com", is_master=True)
    resp_other = _exhaust("random@x.com", is_master=False)
    assert resp_master.status_code == resp_other.status_code == 429
    assert resp_master.json() == resp_other.json()


def test_admin_login_bypasses_rate_limit_when_disabled(app, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_auth_enabled", False, raising=False)
    monkeypatch.setattr(get_settings(), "rate_limit_login_ip_limit", 1, raising=False)
    limiter = RateLimiter(redis_client=FakeRedis())
    client = _admin_client(
        app, db=_master_db(), clerk=FakeClerk(raise_login=True), limiter=limiter
    )
    body = {"email": "master@x.com", "password": "wrong"}
    for _ in range(5):  # com kill switch off, o fluxo anterior é preservado
        assert client.post("/admin/login", json=body).status_code == 401


def test_admin_login_succeeds_when_redis_down(app, monkeypatch) -> None:
    # Fail-open: Redis indisponível não pode derrubar o login master nem criar 500.
    _enable(monkeypatch, rate_limit_login_ip_limit=1)
    limiter = RateLimiter(redis_client=BrokenRedis())
    client = _admin_client(
        app, db=_master_db(), clerk=FakeClerk(), limiter=limiter
    )
    body = {"email": "master@x.com", "password": "secret"}
    for _ in range(3):
        assert client.post("/admin/login", json=body).status_code == 200


def test_admin_login_valid_master_still_works_under_limit(app, monkeypatch) -> None:
    _enable(
        monkeypatch,
        rate_limit_login_ip_limit=5,
        rate_limit_login_account_limit=5,
    )
    limiter = RateLimiter(redis_client=FakeRedis())
    client = _admin_client(app, db=_master_db(), clerk=FakeClerk(), limiter=limiter)
    resp = client.post("/admin/login", json={"email": "master@x.com", "password": "x"})
    assert resp.status_code == 200
    assert resp.json()["token"]
