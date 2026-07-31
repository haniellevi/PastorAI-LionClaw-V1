"""OAUTH-CALENDAR-V1 — segredos, PKCE, purge, contenção no cron-worker e config.

Os testes de endpoint ficam em ``test_calendar_oauth.py``; aqui estão as peças
de serviço e a disciplina operacional que o rollout depende.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib

import pytest

from app.config import Settings
from app.services.calendar_oauth_flows import (
    hash_secret,
    new_pkce_pair,
    new_secret,
    purge_expired_flows,
)
from app.workers import cron_worker as cw

_NOW = dt.datetime(2026, 7, 31, 12, 0, tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------------------
# Segredos e PKCE
# ---------------------------------------------------------------------------
def test_new_secret_is_unique_and_long() -> None:
    secrets_seen = {new_secret() for _ in range(50)}
    assert len(secrets_seen) == 50  # sem colisão em 50 sorteios
    # token_urlsafe(32) => 43 chars de base64url (256 bits de entropia).
    assert all(len(s) >= 43 for s in secrets_seen)


def test_hash_secret_is_sha256_hex_and_stable() -> None:
    assert hash_secret("abc") == hashlib.sha256(b"abc").hexdigest()
    assert len(hash_secret("abc")) == 64
    assert hash_secret("abc") != hash_secret("abd")


def test_pkce_pair_matches_s256_and_never_repeats() -> None:
    verifier, challenge = new_pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    assert challenge == expected
    assert "=" not in challenge  # base64url sem padding, como manda a RFC 7636
    assert 43 <= len(verifier) <= 128  # RFC 7636 §4.1
    assert new_pkce_pair()[0] != verifier


def test_pkce_challenge_does_not_leak_the_verifier() -> None:
    """O challenge é público (viaja na URL); o verifier não pode sair dele."""
    verifier, challenge = new_pkce_pair()
    assert verifier not in challenge


# ---------------------------------------------------------------------------
# purge_expired_flows — helper SEM commit
# ---------------------------------------------------------------------------
class _Result:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _PurgeSession:
    """Dublê mínimo: registra as chamadas e devolve um rowcount controlado."""

    def __init__(self, rowcount: int = 0, *, raise_on_execute: bool = False) -> None:
        self._rowcount = rowcount
        self._raise_on_execute = raise_on_execute
        self.info: dict = {}
        self.executed: list = []
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def execute(self, statement, params=None):
        if self._raise_on_execute:
            raise RuntimeError("boom no execute")
        self.executed.append(statement)
        return _Result(self._rowcount)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closes += 1


def test_purge_removes_expired_flows() -> None:
    session = _PurgeSession(rowcount=3)
    assert purge_expired_flows(session, now=_NOW) == 3
    where_sql = str(session.executed[0].whereclause)
    assert "calendar_oauth_flows.expires_at" in where_sql


def test_purge_leaves_live_flows() -> None:
    """Nada vencido => zero removidos, sem erro."""
    session = _PurgeSession(rowcount=0)
    assert purge_expired_flows(session, now=_NOW) == 0


def test_purge_is_idempotent() -> None:
    session = _PurgeSession(rowcount=0)
    assert purge_expired_flows(session, now=_NOW) == 0
    assert purge_expired_flows(session, now=_NOW) == 0


def test_purge_helper_does_not_commit() -> None:
    """A transação pertence ao chamador — o helper nunca commita."""
    session = _PurgeSession(rowcount=2)
    purge_expired_flows(session, now=_NOW)
    assert session.commits == 0
    assert session.rollbacks == 0


# ---------------------------------------------------------------------------
# CronWorker._purge_oauth_flows — contenção total
# ---------------------------------------------------------------------------
@pytest.fixture
def stub_tick(monkeypatch):
    """Neutraliza o sweep de SLA e os crons; conta se eles rodaram."""
    calls = {"sla": 0, "crons": 0}

    def _sla(session, engine, now, session_factory=None):
        calls["sla"] += 1
        return 7

    def _crons(session, *, engine, now, last_run):
        calls["crons"] += 1
        return 5

    monkeypatch.setattr(cw, "run_all_igrejas", _sla)
    monkeypatch.setattr(cw, "run_due_crons", _crons)
    return calls


class _SharedSession(_PurgeSession):
    """Sessão compartilhada do tick — não deve receber commit nunca."""


def _worker(sessions: list, **kwargs) -> cw.CronWorker:
    """Worker cuja factory entrega, em ordem, as sessões da lista."""
    queue = list(sessions)

    def factory():
        if not queue:
            raise AssertionError("session_factory chamada mais vezes que o esperado")
        return queue.pop(0)

    return cw.CronWorker(session_factory=factory, engine=object(), tick_seconds=60, **kwargs)


def test_purge_uses_a_fresh_cross_tenant_session(stub_tick) -> None:
    purge_session = _PurgeSession(rowcount=4)
    shared = _SharedSession()
    worker = _worker([purge_session, shared])

    counters = worker.tick(now=_NOW)

    # sessão do purge é OUTRA instância, marcada cross-tenant ANTES da query
    assert purge_session is not shared
    assert purge_session.info.get("cross_tenant") is True
    assert purge_session.info["tenant_meta"]["source"] == "worker-oauth-flow-purge"
    assert purge_session.executed, "o purge precisa ter emitido o DELETE"
    assert counters["oauth_flows_purged"] == 4
    assert purge_session.commits == 1
    assert purge_session.closes == 1


def test_purge_does_not_commit_the_shared_tick_session(stub_tick) -> None:
    shared = _SharedSession()
    worker = _worker([_PurgeSession(rowcount=1), shared])
    worker.tick(now=_NOW)
    assert shared.commits == 0
    assert shared.rollbacks == 0


def test_purge_failure_rolls_back_and_does_not_skip_sla_or_crons(stub_tick) -> None:
    purge_session = _PurgeSession(raise_on_execute=True)
    worker = _worker([purge_session, _SharedSession()])

    counters = worker.tick(now=_NOW)

    assert counters["oauth_flows_purged"] == 0
    assert purge_session.rollbacks == 1
    assert purge_session.closes == 1
    assert purge_session.commits == 0
    # o que importa: o resto do tick rodou mesmo assim
    assert stub_tick == {"sla": 1, "crons": 1}
    assert counters["sla_handled"] == 7
    assert counters["crons_run"] == 5


def test_purge_session_factory_failure_is_contained(stub_tick) -> None:
    shared = _SharedSession()
    queue = [shared]
    first = {"done": False}

    def factory():
        if not first["done"]:
            first["done"] = True
            raise RuntimeError("pool esgotado")
        return queue.pop(0)

    worker = cw.CronWorker(session_factory=factory, engine=object(), tick_seconds=60)
    counters = worker.tick(now=_NOW)

    assert counters["oauth_flows_purged"] == 0
    assert stub_tick == {"sla": 1, "crons": 1}


def test_purge_rollback_failure_is_contained(stub_tick) -> None:
    class _BadRollback(_PurgeSession):
        def rollback(self) -> None:
            super().rollback()
            raise RuntimeError("rollback falhou")

    purge_session = _BadRollback(raise_on_execute=True)
    worker = _worker([purge_session, _SharedSession()])

    counters = worker.tick(now=_NOW)

    assert counters["oauth_flows_purged"] == 0
    assert purge_session.closes == 1  # o finally ainda roda
    assert stub_tick == {"sla": 1, "crons": 1}


def test_purge_close_failure_after_success_preserves_counter(stub_tick) -> None:
    class _BadClose(_PurgeSession):
        def close(self) -> None:
            super().close()
            raise RuntimeError("close falhou")

    purge_session = _BadClose(rowcount=9)
    worker = _worker([purge_session, _SharedSession()])

    counters = worker.tick(now=_NOW)

    # o finally NÃO tem return: o valor do try sobrevive ao close quebrado
    assert counters["oauth_flows_purged"] == 9
    assert stub_tick == {"sla": 1, "crons": 1}


def test_purge_close_failure_after_error_preserves_zero(stub_tick) -> None:
    class _BadBoth(_PurgeSession):
        def close(self) -> None:
            super().close()
            raise RuntimeError("close falhou")

    worker = _worker([_BadBoth(raise_on_execute=True), _SharedSession()])
    assert worker.tick(now=_NOW)["oauth_flows_purged"] == 0
    assert stub_tick == {"sla": 1, "crons": 1}


def test_purge_mark_cross_tenant_failure_is_contained(stub_tick, monkeypatch) -> None:
    def _boom(session, *, source):
        raise cw.mark_cross_tenant.__globals__["TenantPinConflictError"](  # type: ignore[attr-defined]
            "já pinada"
        )

    purge_session = _PurgeSession(rowcount=1)
    monkeypatch.setattr(cw, "mark_cross_tenant", _boom)
    worker = _worker([purge_session, _SharedSession()])

    counters = worker.tick(now=_NOW)

    assert counters["oauth_flows_purged"] == 0
    assert purge_session.executed == []  # nenhuma query emitida
    assert purge_session.closes == 1
    assert stub_tick == {"sla": 1, "crons": 1}


def test_purge_does_not_swallow_base_exception(stub_tick) -> None:
    """`except Exception` de propósito: shutdown gracioso precisa propagar."""

    class _Interrupt(_PurgeSession):
        def execute(self, statement, params=None):
            raise KeyboardInterrupt

    worker = _worker([_Interrupt(), _SharedSession()])
    with pytest.raises(KeyboardInterrupt):
        worker.tick(now=_NOW)


def test_tick_reports_purged_counter(stub_tick) -> None:
    worker = _worker([_PurgeSession(rowcount=2), _SharedSession()])
    counters = worker.tick(now=_NOW)
    # A chave é a assinatura que o gate G7a procura no log do worker.
    assert set(counters) == {"sla_handled", "crons_run", "oauth_flows_purged"}


# ---------------------------------------------------------------------------
# Allowlist de origens de retorno
# ---------------------------------------------------------------------------
def _settings(origins: str, **kwargs) -> Settings:
    return Settings(
        session_jwt_secret="x" * 32, calendar_oauth_return_origins=origins, **kwargs
    )


def test_allowlist_parses_csv_and_normalizes_trailing_slash() -> None:
    allowlist = _settings(
        "https://admin.igreja12.com.br/ , https://outro.igreja12.com.br"
    ).calendar_oauth_return_origin_allowlist
    assert allowlist == frozenset(
        {"https://admin.igreja12.com.br", "https://outro.igreja12.com.br"}
    )


def test_allowlist_ignores_empty_entries() -> None:
    allowlist = _settings("https://a.x, ,,https://b.x").calendar_oauth_return_origin_allowlist
    assert allowlist == frozenset({"https://a.x", "https://b.x"})


def test_allowlist_is_empty_by_default() -> None:
    assert _settings("").calendar_oauth_return_origin_allowlist == frozenset()


def _prod(**kwargs) -> Settings:
    base = {
        "app_env": "production",
        "clerk_secret_key": "sk_live_x",
        "clerk_jwt_issuer": "https://clerk.igreja12.com.br",
        "supabase_url": "https://x.supabase.co",
        "supabase_service_role_key": "srk",
        "database_url": "postgresql+psycopg2://u:p@h/db",
        "secrets_encryption_key": "k" * 32,
        "evolution_api_url": "https://evo.igreja12.com.br",
        "evolution_api_key": "evo",
        "evolution_webhook_secret": "whs",
        "redis_url": "redis://r:6379/0",
        "session_jwt_secret": "s" * 40,
        "frontend_url": "https://app.igreja12.com.br",
        "app_base_url": "https://api.igreja12.com.br",
        "calendar_oauth_return_origins": "https://admin.igreja12.com.br",
    }
    base.update(kwargs)
    return Settings(**base)


def test_production_boot_accepts_a_valid_allowlist() -> None:
    _prod().assert_production_ready()  # não levanta


def test_production_boot_fails_on_empty_return_origins() -> None:
    with pytest.raises(RuntimeError, match="CALENDAR_OAUTH_RETURN_ORIGINS"):
        _prod(calendar_oauth_return_origins="").assert_production_ready()


def test_production_boot_fails_on_http_origin() -> None:
    with pytest.raises(RuntimeError, match="CALENDAR_OAUTH_RETURN_ORIGINS"):
        _prod(calendar_oauth_return_origins="http://admin.igreja12.com.br").assert_production_ready()


def test_production_boot_fails_on_localhost_origin() -> None:
    with pytest.raises(RuntimeError, match="CALENDAR_OAUTH_RETURN_ORIGINS"):
        _prod(calendar_oauth_return_origins="https://localhost:3000").assert_production_ready()


def test_production_boot_rejects_the_api_origin() -> None:
    """`cors_origins` inclui a API; esta allowlist NÃO pode incluir."""
    with pytest.raises(RuntimeError, match="must not include the API origin"):
        _prod(
            calendar_oauth_return_origins="https://api.igreja12.com.br"
        ).assert_production_ready()
