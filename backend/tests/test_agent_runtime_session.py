"""Offline contract tests for the dedicated D2A agent database boundary."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.db import agent_runtime_session as runtime_session

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"
RUNTIME_URL = (
    "postgresql+psycopg2://agent_runtime:private-runtime-value@db.invalid/app"
)
PRIMARY_URL = "postgresql+psycopg2://postgres:private-owner-value@db.invalid/app"


@pytest.fixture(autouse=True)
def _reset_runtime_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_session, "_agent_runtime_engine", None)
    monkeypatch.setattr(runtime_session, "_AgentRuntimeSessionFactory", None)


def _settings(**overrides: str) -> SimpleNamespace:
    values = {
        "agent_runtime_database_url": RUNTIME_URL,
        "database_url": PRIMARY_URL,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_settings_normalize_both_postgres_urls_without_requiring_runtime_url() -> None:
    empty = Settings(_env_file=None)
    assert empty.agent_runtime_database_url == ""

    settings = Settings(
        _env_file=None,
        database_url="postgresql://postgres:owner@db.invalid/app",
        agent_runtime_database_url=(
            "postgresql://agent_runtime:runtime@db.invalid/app"
        ),
    )
    assert settings.database_url.startswith("postgresql+psycopg2://")
    assert settings.agent_runtime_database_url.startswith(
        "postgresql+psycopg2://"
    )


def test_engine_rejects_missing_runtime_url_without_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_session,
        "get_settings",
        lambda: _settings(agent_runtime_database_url=""),
    )
    monkeypatch.setattr(
        runtime_session,
        "create_engine",
        lambda *_args, **_kwargs: pytest.fail("engine must not be created"),
    )

    with pytest.raises(
        runtime_session.AgentRuntimeConfigurationError,
        match="AGENT_RUNTIME_DATABASE_URL is not configured",
    ):
        runtime_session.get_agent_runtime_engine()


@pytest.mark.parametrize(
    "runtime_url",
    [
        "postgresql+psycopg2://postgres:secret@db.invalid/app",
        "postgresql+psycopg2://authenticated:secret@db.invalid/app",
    ],
)
def test_engine_rejects_any_username_other_than_agent_runtime(
    monkeypatch: pytest.MonkeyPatch,
    runtime_url: str,
) -> None:
    monkeypatch.setattr(
        runtime_session,
        "get_settings",
        lambda: _settings(agent_runtime_database_url=runtime_url),
    )

    with pytest.raises(
        runtime_session.AgentRuntimeConfigurationError,
        match="must authenticate as agent_runtime",
    ):
        runtime_session.get_agent_runtime_engine()


def test_engine_rejects_runtime_url_equal_to_primary_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_session,
        "get_settings",
        lambda: _settings(
            agent_runtime_database_url=RUNTIME_URL,
            database_url=RUNTIME_URL,
        ),
    )

    with pytest.raises(
        runtime_session.AgentRuntimeConfigurationError,
        match="must be distinct from DATABASE_URL",
    ):
        runtime_session.get_agent_runtime_engine()


def test_invalid_runtime_url_does_not_leak_its_secret(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "private-invalid-value"
    invalid_url = f"not a database url {secret}"
    monkeypatch.setattr(
        runtime_session,
        "get_settings",
        lambda: _settings(agent_runtime_database_url=invalid_url),
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(
        runtime_session.AgentRuntimeConfigurationError,
        match="AGENT_RUNTIME_DATABASE_URL is invalid",
    ) as raised:
        runtime_session.get_agent_runtime_engine()

    assert raised.value.__cause__ is None
    assert secret not in str(raised.value)
    assert secret not in caplog.text


def test_engine_is_lazy_bounded_and_never_logs_the_dsn(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinel = object()
    captured: dict[str, object] = {}
    calls = 0
    listeners: list[tuple[object, str, object]] = []

    def fake_create_engine(url: str, **kwargs):
        nonlocal calls
        calls += 1
        captured["url"] = url
        captured["kwargs"] = kwargs
        return sentinel

    monkeypatch.setattr(runtime_session, "get_settings", lambda: _settings())
    monkeypatch.setattr(runtime_session, "create_engine", fake_create_engine)
    monkeypatch.setattr(
        runtime_session.event,
        "listen",
        lambda engine, name, callback: listeners.append((engine, name, callback)),
    )

    with caplog.at_level(logging.DEBUG):
        assert runtime_session.get_agent_runtime_engine() is sentinel
        assert runtime_session.get_agent_runtime_engine() is sentinel

    assert calls == 1
    assert listeners == [
        (sentinel, "checkout", runtime_session._guard_agent_runtime_checkout)
    ]
    assert captured == {
        "url": RUNTIME_URL,
        "kwargs": {
            "pool_pre_ping": True,
            "pool_size": 2,
            "max_overflow": 3,
            "pool_timeout": 5,
            "pool_recycle": 1800,
            "connect_args": {"connect_timeout": 5},
            "future": True,
        },
    }
    assert "private-runtime-value" not in caplog.text
    assert RUNTIME_URL not in caplog.text


def test_factory_is_lazy_and_bound_only_to_runtime_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = object()
    factory = object()
    captured: dict[str, object] = {}
    calls = 0

    def fake_sessionmaker(**kwargs):
        nonlocal calls
        calls += 1
        captured.update(kwargs)
        return factory

    monkeypatch.setattr(runtime_session, "get_agent_runtime_engine", lambda: engine)
    monkeypatch.setattr(runtime_session, "sessionmaker", fake_sessionmaker)

    assert runtime_session.get_agent_runtime_session_factory() is factory
    assert runtime_session.get_agent_runtime_session_factory() is factory
    assert calls == 1
    assert captured == {
        "bind": engine,
        "autoflush": False,
        "autocommit": False,
        "expire_on_commit": False,
        "future": True,
    }


class _Result:
    def __init__(self, row: SimpleNamespace) -> None:
        self._row = row

    def one(self) -> SimpleNamespace:
        return self._row


class _FakeSession:
    def __init__(
        self,
        row: SimpleNamespace | None = None,
        *,
        persisted_tenant: str | None = None,
        baseline_search_path: str = runtime_session.AGENT_RUNTIME_SEARCH_PATH,
    ) -> None:
        self.info: dict[str, str] = {}
        self._in_transaction = False
        self.begin_calls = 0
        self.rollback_calls = 0
        self.calls: list[tuple[str, dict | None]] = []
        self.row = row or _identity_row()
        self.persisted_tenant = persisted_tenant
        self.baseline_search_path = baseline_search_path
        self.invalidated = False

    def in_transaction(self) -> bool:
        return self._in_transaction

    def begin(self) -> None:
        self.begin_calls += 1
        self._in_transaction = True

    def commit(self) -> None:
        self._in_transaction = False

    def rollback(self) -> None:
        self.rollback_calls += 1
        self._in_transaction = False

    def execute(self, statement, params=None) -> _Result:
        sql = str(statement)
        self.calls.append((sql, params))
        if "as persisted_tenant" in sql:
            return _Result(
                SimpleNamespace(
                    persisted_tenant=self.persisted_tenant,
                    search_path=self.baseline_search_path,
                )
            )
        return _Result(self.row)

    def connection(self):
        return self

    def invalidate(self) -> None:
        self.invalidated = True


def _identity_row(**overrides) -> SimpleNamespace:
    values = {
        "login_role": "agent_runtime",
        "effective_role": "agent_runtime",
        "can_login": True,
        "inherits_roles": False,
        "is_superuser": False,
        "bypass_rls": False,
        "can_create_database": False,
        "can_create_role": False,
        "can_replicate": False,
        "has_no_memberships": True,
        "row_security": "on",
        "search_path": runtime_session.AGENT_RUNTIME_SEARCH_PATH,
        "tenant_id": TENANT_A,
        "tenant_guc": TENANT_A,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_scope_begins_transaction_sets_local_tenant_and_probes_private_helper() -> None:
    session = _FakeSession()

    assert runtime_session.scope_agent_runtime_session(session, TENANT_A) == TENANT_A

    assert session.begin_calls == 1
    assert session.rollback_calls == 0
    assert session.info[runtime_session.AGENT_RUNTIME_TENANT_KEY] == TENANT_A
    statements = [sql for sql, _params in session.calls]
    assert "as persisted_tenant" in statements[0]
    assert "set_config('app.tenant_igreja_id', :igreja_id, true)" in statements[1]
    assert session.calls[1][1] == {"igreja_id": TENANT_A}
    assert "agent_private.current_tenant_id()" in statements[2]
    assert "session_user" in statements[2]
    assert "current_user" in statements[2]
    assert all("set role" not in sql.lower() for sql in statements)


def test_scope_rejects_active_transaction_before_any_sql() -> None:
    session = _FakeSession()
    session._in_transaction = True

    with pytest.raises(
        runtime_session.AgentRuntimeScopeError,
        match="requires a fresh transaction",
    ):
        runtime_session.scope_agent_runtime_session(session, TENANT_A)

    assert session.calls == []
    assert session.begin_calls == 0


@pytest.mark.parametrize(
    "session",
    [
        _FakeSession(persisted_tenant=TENANT_A),
        _FakeSession(baseline_search_path="public"),
    ],
)
def test_scope_invalidates_contaminated_connection_before_setting_tenant(
    session: _FakeSession,
) -> None:
    with pytest.raises(
        runtime_session.AgentRuntimeScopeError,
        match="baseline verification failed",
    ):
        runtime_session.scope_agent_runtime_session(session, TENANT_B)

    assert session.invalidated is True
    assert session.rollback_calls == 1
    assert len(session.calls) == 1
    assert "set_config" not in session.calls[0][0]


def test_scope_pin_is_reusable_for_same_tenant_but_never_another() -> None:
    session = _FakeSession()
    runtime_session.scope_agent_runtime_session(session, TENANT_A)
    session.commit()

    runtime_session.scope_agent_runtime_session(session, TENANT_A)
    session.commit()
    begin_calls = session.begin_calls

    with pytest.raises(runtime_session.AgentRuntimeTenantPinError):
        runtime_session.scope_agent_runtime_session(session, TENANT_B)

    assert session.begin_calls == begin_calls
    assert session.info[runtime_session.AGENT_RUNTIME_TENANT_KEY] == TENANT_A


def test_verify_reproves_identity_and_tenant_inside_active_transaction() -> None:
    session = _FakeSession()
    runtime_session.scope_agent_runtime_session(session, TENANT_A)

    assert runtime_session.verify_agent_runtime_scope(session, TENANT_A) == TENANT_A
    assert "agent_private.current_tenant_id()" in session.calls[-1][0]
    assert session.rollback_calls == 0


def test_verify_rejects_unpinned_or_inactive_session_before_sql() -> None:
    unpinned = _FakeSession()
    with pytest.raises(
        runtime_session.AgentRuntimeTenantPinError,
        match="not pinned",
    ):
        runtime_session.verify_agent_runtime_scope(unpinned, TENANT_A)
    assert unpinned.calls == []

    inactive = _FakeSession()
    runtime_session.scope_agent_runtime_session(inactive, TENANT_A)
    inactive.commit()
    with pytest.raises(
        runtime_session.AgentRuntimeScopeError,
        match="active transaction",
    ):
        runtime_session.verify_agent_runtime_scope(inactive, TENANT_A)
    assert len(inactive.calls) == 3


def test_verify_rolls_back_when_identity_or_tenant_drifts() -> None:
    session = _FakeSession(row=_identity_row())
    runtime_session.scope_agent_runtime_session(session, TENANT_A)
    session.row = _identity_row(tenant_id=TENANT_B)
    with pytest.raises(
        runtime_session.AgentRuntimeScopeError,
        match="identity or tenant verification failed",
    ):
        runtime_session.verify_agent_runtime_scope(session, TENANT_A)
    assert session.rollback_calls == 1
    assert not session.in_transaction()


@pytest.mark.parametrize(
    "row",
    [
        _identity_row(login_role="postgres"),
        _identity_row(effective_role="authenticated"),
        _identity_row(can_login=False),
        _identity_row(inherits_roles=True),
        _identity_row(is_superuser=True),
        _identity_row(bypass_rls=True),
        _identity_row(can_create_database=True),
        _identity_row(can_create_role=True),
        _identity_row(can_replicate=True),
        _identity_row(has_no_memberships=False),
        _identity_row(row_security="off"),
        _identity_row(search_path="public"),
        _identity_row(tenant_id=TENANT_B),
        _identity_row(tenant_guc=TENANT_B),
    ],
)
def test_scope_rolls_back_on_role_privilege_or_tenant_mismatch(
    row: SimpleNamespace,
) -> None:
    session = _FakeSession(row)

    with pytest.raises(
        runtime_session.AgentRuntimeScopeError,
        match="identity or tenant verification failed",
    ):
        runtime_session.scope_agent_runtime_session(session, TENANT_A)

    assert session.rollback_calls == 1
    assert not session.in_transaction()
    assert runtime_session.AGENT_RUNTIME_TENANT_KEY not in session.info


@pytest.mark.parametrize("bad_tenant", [None, "", "not-a-uuid"])
def test_scope_rejects_invalid_tenant_before_begin_or_sql(bad_tenant) -> None:
    session = _FakeSession()

    with pytest.raises(runtime_session.AgentRuntimeScopeError, match="igreja_id"):
        runtime_session.scope_agent_runtime_session(session, bad_tenant)

    assert session.begin_calls == 0
    assert session.calls == []
