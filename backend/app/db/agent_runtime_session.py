"""Dedicated database boundary for the tenant-isolated agent runtime.

The agent never falls back to the application's privileged ``DATABASE_URL``.
Its own login is verified in the same transaction that fixes the tenant GUC,
before any domain query can run.  This module intentionally does not reuse the
generic tenant-session seam: a direct ``agent_runtime`` login must not issue
``SET ROLE`` or inherit a cross-tenant mode.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.exc import ArgumentError, DisconnectionError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

AGENT_RUNTIME_ROLE = "agent_runtime"
AGENT_RUNTIME_TENANT_KEY = "agent_runtime_tenant_igreja_id"
AGENT_RUNTIME_SEARCH_PATH = "pg_catalog, agent_private"

_POOL_CHECKOUT_TIMEOUT_SECONDS = 5
_POSTGRES_CONNECT_TIMEOUT_SECONDS = 5

_agent_runtime_engine: Engine | None = None
_AgentRuntimeSessionFactory: sessionmaker[Session] | None = None


class AgentRuntimeConfigurationError(RuntimeError):
    """The dedicated runtime database configuration is absent or unsafe."""


class AgentRuntimeScopeError(RuntimeError):
    """The runtime session did not prove its role and tenant boundary."""


class AgentRuntimeTenantPinError(AgentRuntimeScopeError):
    """A runtime session was reused for a different tenant."""


def _guard_agent_runtime_checkout(
    dbapi_connection: Any,
    _connection_record: Any,
    _connection_proxy: Any,
) -> None:
    """Discard a pooled connection carrying tenant or search-path state."""

    cursor = None
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute(
            "select nullif(current_setting('app.tenant_igreja_id', true), ''), "
            "current_setting('search_path')"
        )
        persisted_tenant, search_path = cursor.fetchone()
        dbapi_connection.rollback()
    except BaseException as exc:
        try:
            dbapi_connection.rollback()
        except BaseException:
            pass
        raise DisconnectionError(
            "agent runtime checkout verification failed"
        ) from exc
    finally:
        if cursor is not None:
            cursor.close()

    if persisted_tenant is not None or search_path != AGENT_RUNTIME_SEARCH_PATH:
        raise DisconnectionError(
            "agent runtime checkout rejected persistent connection state"
        )


def _parse_runtime_url(value: str) -> URL:
    try:
        return make_url(value)
    except (ArgumentError, ValueError):
        raise AgentRuntimeConfigurationError(
            "AGENT_RUNTIME_DATABASE_URL is invalid"
        ) from None


def _validated_runtime_url() -> str:
    settings = get_settings()
    runtime_url = settings.agent_runtime_database_url
    if not runtime_url:
        raise AgentRuntimeConfigurationError(
            "AGENT_RUNTIME_DATABASE_URL is not configured"
        )

    parsed_runtime = _parse_runtime_url(runtime_url)
    if parsed_runtime.username != AGENT_RUNTIME_ROLE:
        raise AgentRuntimeConfigurationError(
            "AGENT_RUNTIME_DATABASE_URL must authenticate as agent_runtime"
        )

    database_url = settings.database_url
    if database_url and parsed_runtime == _parse_runtime_url(database_url):
        raise AgentRuntimeConfigurationError(
            "AGENT_RUNTIME_DATABASE_URL must be distinct from DATABASE_URL"
        )
    return runtime_url


def get_agent_runtime_engine() -> Engine:
    """Build the dedicated runtime engine lazily, without a privileged fallback."""

    global _agent_runtime_engine
    if _agent_runtime_engine is None:
        engine = create_engine(
            _validated_runtime_url(),
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=3,
            pool_timeout=_POOL_CHECKOUT_TIMEOUT_SECONDS,
            pool_recycle=1800,
            connect_args={"connect_timeout": _POSTGRES_CONNECT_TIMEOUT_SECONDS},
            future=True,
        )
        event.listen(engine, "checkout", _guard_agent_runtime_checkout)
        _agent_runtime_engine = engine
    return _agent_runtime_engine


def get_agent_runtime_session_factory() -> sessionmaker[Session]:
    """Return a lazy session factory bound only to the runtime engine."""

    global _AgentRuntimeSessionFactory
    if _AgentRuntimeSessionFactory is None:
        _AgentRuntimeSessionFactory = sessionmaker(
            bind=get_agent_runtime_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
    return _AgentRuntimeSessionFactory


def _normalize_tenant_id(igreja_id: Any) -> str:
    try:
        return str(uuid.UUID(str(igreja_id).strip()))
    except (AttributeError, TypeError, ValueError):
        raise AgentRuntimeScopeError(
            "igreja_id invalid for agent runtime scope"
        ) from None


def scope_agent_runtime_session(session: Session, igreja_id: Any) -> str:
    """Begin and prove one tenant-scoped transaction for the agent runtime.

    A fresh transaction is mandatory.  The transaction-local GUC is set before
    the private helper and role attributes are probed.  Any inconsistency rolls
    the transaction back; no query is allowed to continue under a privileged or
    unscoped identity.
    """

    tenant_id = _normalize_tenant_id(igreja_id)
    existing = session.info.get(AGENT_RUNTIME_TENANT_KEY)
    if existing is not None and existing != tenant_id:
        raise AgentRuntimeTenantPinError(
            "agent runtime session is already pinned to another tenant"
        )
    if session.in_transaction():
        raise AgentRuntimeScopeError(
            "agent runtime scope requires a fresh transaction"
        )

    session.begin()
    connection_to_invalidate = None
    try:
        baseline = session.execute(
            text(
                "select nullif(current_setting("
                "'app.tenant_igreja_id', true), '') as persisted_tenant, "
                "current_setting('search_path') as search_path"
            )
        ).one()
        if (
            baseline.persisted_tenant is not None
            or baseline.search_path != AGENT_RUNTIME_SEARCH_PATH
        ):
            connection_to_invalidate = session.connection()
            raise AgentRuntimeScopeError(
                "agent runtime connection baseline verification failed"
            )

        session.execute(
            text("select set_config('app.tenant_igreja_id', :igreja_id, true)"),
            {"igreja_id": tenant_id},
        )
        row = session.execute(
            text(
                "select session_user::text as login_role, "
                "current_user::text as effective_role, "
                "role.rolcanlogin as can_login, "
                "role.rolinherit as inherits_roles, "
                "role.rolsuper as is_superuser, "
                "role.rolbypassrls as bypass_rls, "
                "role.rolcreatedb as can_create_database, "
                "role.rolcreaterole as can_create_role, "
                "role.rolreplication as can_replicate, "
                "not exists ("
                "  select 1 from pg_catalog.pg_auth_members membership "
                "  where membership.member = role.oid"
                ") as has_no_memberships, "
                "current_setting('row_security') as row_security, "
                "current_setting('search_path') as search_path, "
                "agent_private.current_tenant_id()::text as tenant_id, "
                "nullif(current_setting('app.tenant_igreja_id', true), '') "
                "as tenant_guc "
                "from pg_catalog.pg_roles as role "
                "where role.rolname = current_user"
            )
        ).one()

        identity_matches = (
            row.login_role == AGENT_RUNTIME_ROLE
            and row.effective_role == AGENT_RUNTIME_ROLE
            and bool(row.can_login)
            and not bool(row.inherits_roles)
            and not bool(row.is_superuser)
            and not bool(row.bypass_rls)
            and not bool(row.can_create_database)
            and not bool(row.can_create_role)
            and not bool(row.can_replicate)
            and bool(row.has_no_memberships)
            and row.row_security == "on"
            and row.search_path == AGENT_RUNTIME_SEARCH_PATH
        )
        tenant_matches = row.tenant_id == tenant_id and row.tenant_guc == tenant_id
        if not identity_matches or not tenant_matches:
            raise AgentRuntimeScopeError(
                "agent runtime database identity or tenant verification failed"
            )
    except BaseException:
        if connection_to_invalidate is not None:
            connection_to_invalidate.invalidate()
        session.rollback()
        if existing is None:
            session.info.pop(AGENT_RUNTIME_TENANT_KEY, None)
        raise

    session.info[AGENT_RUNTIME_TENANT_KEY] = tenant_id
    return tenant_id


__all__ = [
    "AGENT_RUNTIME_ROLE",
    "AGENT_RUNTIME_SEARCH_PATH",
    "AGENT_RUNTIME_TENANT_KEY",
    "AgentRuntimeConfigurationError",
    "AgentRuntimeScopeError",
    "AgentRuntimeTenantPinError",
    "get_agent_runtime_engine",
    "get_agent_runtime_session_factory",
    "scope_agent_runtime_session",
]
