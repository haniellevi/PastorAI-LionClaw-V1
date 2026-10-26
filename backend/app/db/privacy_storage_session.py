"""Dedicated database login for private Storage maintenance.

Only private deletion tasks and audio upload ownership use this boundary. It
never falls back to ``DATABASE_URL`` and never issues ``SET ROLE``: the login
itself is the identity, proven at the start of every transaction together with
a fixed transaction-local ``search_path`` and tenant GUC. The tenant GUC scopes
rows; it is not the identity. The pool checkout only rejects a persisted tenant
GUC; identity is proven at BEGIN. Sends, event fences and summary tasks are
outside this boundary.

The URL user may be ``private_storage_runtime`` (direct connection) or the
Supabase shared-pooler form ``private_storage_runtime.<project-ref>``. The URL
is never the proof: every transaction requires ``session_user`` and
``current_user`` to be exactly ``private_storage_runtime``. Which hosted
endpoint/mode is used must still be validated in the release.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.exc import ArgumentError, DisconnectionError
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from app.config import get_settings

PRIVATE_STORAGE_ROLE = "private_storage_runtime"
PRIVATE_STORAGE_TENANT_KEY = "private_storage_tenant_igreja_id"
# Fixed name resolution for every transaction (pg_temp explicitly last, so a
# TEMP table cannot shadow public relations); never taken from the URL, the
# role defaults or the environment. Isolated-schema test harnesses may adapt it.
PRIVATE_STORAGE_SEARCH_PATH = "pg_catalog, public, pg_temp"
_POOLER_USER = re.compile(rf"\A{PRIVATE_STORAGE_ROLE}\.[a-z0-9]{{20}}\Z")

_POOL_CHECKOUT_TIMEOUT_SECONDS = 5
_POSTGRES_CONNECT_TIMEOUT_SECONDS = 5

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None

# Both settings first, through pg_catalog explicitly: nothing resolves through
# a caller-controlled search_path before it is fixed.
_SET_TRANSACTION = (
    "select pg_catalog.set_config('search_path', %s, true), "
    "pg_catalog.set_config('app.tenant_igreja_id', %s, true)"
)
# One round trip: the login, the effective user and its attributes, and the
# settings as seen by this transaction. Membership-free login, no SET ROLE.
_IDENTITY_PROBE = (
    "select session_user::text, current_user::text, r.rolcanlogin, r.rolinherit, "
    "r.rolsuper, r.rolbypassrls, r.rolcreatedb, r.rolcreaterole, r.rolreplication, "
    "not exists(select 1 from pg_catalog.pg_auth_members m where m.member = r.oid), "
    "pg_catalog.current_setting('row_security'), "
    "pg_catalog.current_setting('search_path'), "
    "nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '') "
    "from pg_catalog.pg_roles r where r.rolname = session_user"
)


class PrivateStorageUnavailable(RuntimeError):
    """The dedicated login is not configured, unsafe or unproven."""


class PrivateStorageScopeError(PrivateStorageUnavailable):
    """A transaction did not prove the dedicated identity and its tenant."""


def _identity_matches(row: Any, tenant_id: str | None) -> bool:
    (login, effective, can_login, inherits, superuser, bypass, createdb,
     createrole, replication, no_memberships, row_security, search_path, tenant) = row
    return (
        login == PRIVATE_STORAGE_ROLE
        and effective == PRIVATE_STORAGE_ROLE
        and bool(can_login)
        and not inherits and not superuser and not bypass
        and not createdb and not createrole and not replication
        and bool(no_memberships)
        and row_security == "on"
        and search_path == PRIVATE_STORAGE_SEARCH_PATH
        and tenant == tenant_id
    )


def _prove_transaction(session: Session, _transaction: SessionTransaction,
                       connection: Any) -> None:
    """Fix search_path and tenant, then prove the login on every BEGIN.

    Runs post-commit too. Fail-closed: any mismatch raises and the transaction
    never runs a service query.
    """
    if not session.info.get("private_storage_session"):
        return
    tenant_id = session.info.get(PRIVATE_STORAGE_TENANT_KEY)
    connection.exec_driver_sql(_SET_TRANSACTION, (PRIVATE_STORAGE_SEARCH_PATH, tenant_id or ""))
    row = connection.exec_driver_sql(_IDENTITY_PROBE).one_or_none()
    if row is None or not _identity_matches(row, tenant_id):
        raise PrivateStorageScopeError("private storage identity verification failed")


def _guard_checkout(dbapi_connection: Any, _record: Any, _proxy: Any) -> None:
    """Discard a pooled connection that carries a persistent tenant GUC."""
    cursor = None
    try:
        previous = dbapi_connection.autocommit
        dbapi_connection.autocommit = True
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("select nullif(pg_catalog.current_setting("
                           "'app.tenant_igreja_id', true), '')")
            (persisted,) = cursor.fetchone()
        finally:
            if cursor is not None:
                cursor.close()
            if not previous and not dbapi_connection.closed:
                dbapi_connection.autocommit = previous
    except BaseException as exc:
        raise DisconnectionError("private storage checkout verification failed") from exc
    if persisted is not None:
        raise DisconnectionError("private storage checkout rejected persistent tenant state")


def _parse(value: str, name: str) -> URL:
    try:
        return make_url(value)
    except (ArgumentError, ValueError):
        raise PrivateStorageUnavailable(f"{name} is invalid") from None


def is_private_storage_url_user(username: object) -> bool:
    """Direct ``private_storage_runtime`` or pooler ``private_storage_runtime.<ref>``.

    Only a shape check before connecting; the SQL probe is the identity proof.
    """
    return type(username) is str and (
        username == PRIVATE_STORAGE_ROLE or _POOLER_USER.fullmatch(username) is not None)


def _validated_url() -> str:
    settings = get_settings()
    url = settings.private_storage_database_url
    if not url:
        raise PrivateStorageUnavailable("PRIVATE_STORAGE_DATABASE_URL is not configured")
    parsed = _parse(url, "PRIVATE_STORAGE_DATABASE_URL")
    if not is_private_storage_url_user(parsed.username):
        raise PrivateStorageUnavailable(
            "PRIVATE_STORAGE_DATABASE_URL must authenticate as private_storage_runtime")
    for name, other in (("DATABASE_URL", settings.database_url),
                        ("AGENT_RUNTIME_DATABASE_URL", settings.agent_runtime_database_url)):
        if other and _parse(other, name) == parsed:
            raise PrivateStorageUnavailable(f"PRIVATE_STORAGE_DATABASE_URL must differ from {name}")
    return url


def get_private_storage_session_factory() -> sessionmaker[Session]:
    """Lazy factory bound only to the dedicated login; no privileged fallback."""
    global _engine, _SessionFactory
    if _SessionFactory is None:
        engine = create_engine(
            _validated_url(),
            pool_size=1,
            max_overflow=2,
            pool_timeout=_POOL_CHECKOUT_TIMEOUT_SECONDS,
            pool_recycle=1800,
            connect_args={"connect_timeout": _POSTGRES_CONNECT_TIMEOUT_SECONDS},
            future=True,
        )
        event.listen(engine, "checkout", _guard_checkout)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                               expire_on_commit=False, future=True,
                               info={"private_storage_session": True})
        event.listen(factory, "after_begin", _prove_transaction)
        _engine, _SessionFactory = engine, factory
    return _SessionFactory


def dispose_private_storage_engine() -> None:
    """Drop the cached engine (configuration change or test teardown)."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = _SessionFactory = None


def scope_private_storage(session: Session, igreja_id: Any) -> str:
    """Pin a fresh dedicated session to one tenant; every BEGIN re-proves it."""
    if not session.info.get("private_storage_session"):
        raise PrivateStorageScopeError("session is not bound to the private storage login")
    try:
        tenant_id = str(uuid.UUID(str(igreja_id).strip()))
    except (AttributeError, TypeError, ValueError):
        raise PrivateStorageScopeError("igreja_id invalid for private storage scope") from None
    existing = session.info.get(PRIVATE_STORAGE_TENANT_KEY)
    if existing is not None and existing != tenant_id:
        raise PrivateStorageScopeError("private storage session already pinned to another tenant")
    if existing is None and session.in_transaction():
        raise PrivateStorageScopeError("private storage scope requires a fresh transaction")
    session.info[PRIVATE_STORAGE_TENANT_KEY] = tenant_id
    return tenant_id


__all__ = [
    "PRIVATE_STORAGE_ROLE",
    "PRIVATE_STORAGE_SEARCH_PATH",
    "PrivateStorageScopeError",
    "PrivateStorageUnavailable",
    "dispose_private_storage_engine",
    "get_private_storage_session_factory",
    "is_private_storage_url_user",
    "scope_private_storage",
]
