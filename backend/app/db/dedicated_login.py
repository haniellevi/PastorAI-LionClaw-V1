"""Role-independent proof shared by the dedicated private database logins.

Two clients use it: ``privacy_storage_session`` (``private_storage_runtime``)
and ``private_send_session`` (``private_send_runtime``). Each client keeps its
own role, URL variable, cached engine, exceptions and public API; only the
mechanics live here: transaction-local ``search_path`` and tenant GUC, the SQL
identity probe, the pooled-connection tenant guard, the URL user shape and the
fresh-session tenant pin. There is no fallback URL and no ``SET ROLE``.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.exc import ArgumentError, DisconnectionError
from sqlalchemy.orm import Session

POOL_CHECKOUT_TIMEOUT_SECONDS = 5
POSTGRES_CONNECT_TIMEOUT_SECONDS = 5
_PROJECT_REF = re.compile(r"[a-z0-9]{20}")

# Both settings first, through pg_catalog explicitly: nothing resolves through
# a caller-controlled search_path before it is fixed.
SET_TRANSACTION = (
    "select pg_catalog.set_config('search_path', %s, true), "
    "pg_catalog.set_config('app.tenant_igreja_id', %s, true)"
)
# One round trip: the login, the effective user and its attributes, and the
# settings as seen by this transaction. Membership-free login, no SET ROLE.
IDENTITY_PROBE = (
    "select session_user::text, current_user::text, r.rolcanlogin, r.rolinherit, "
    "r.rolsuper, r.rolbypassrls, r.rolcreatedb, r.rolcreaterole, r.rolreplication, "
    "not exists(select 1 from pg_catalog.pg_auth_members m where m.member = r.oid), "
    "pg_catalog.current_setting('row_security'), "
    "pg_catalog.current_setting('search_path'), "
    "nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '') "
    "from pg_catalog.pg_roles r where r.rolname = session_user"
)


def identity_matches(row: Any, *, role: str, search_path: str, tenant_id: str | None) -> bool:
    (login, effective, can_login, inherits, superuser, bypass, createdb,
     createrole, replication, no_memberships, row_security, path, tenant) = row
    return (
        login == role
        and effective == role
        and bool(can_login)
        and not inherits and not superuser and not bypass
        and not createdb and not createrole and not replication
        and bool(no_memberships)
        and row_security == "on"
        and path == search_path
        and tenant == tenant_id
    )


def prove_transaction(connection: Any, *, role: str, search_path: str,
                      tenant_id: str | None) -> bool:
    """Fix search_path and tenant for this transaction, then probe the login."""
    connection.exec_driver_sql(SET_TRANSACTION, (search_path, tenant_id or ""))
    row = connection.exec_driver_sql(IDENTITY_PROBE).one_or_none()
    return row is not None and identity_matches(
        row, role=role, search_path=search_path, tenant_id=tenant_id)


def _checkout_guard(label: str):
    def guard(dbapi_connection: Any, _record: Any, _proxy: Any) -> None:
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
            raise DisconnectionError(f"{label} checkout verification failed") from exc
        if persisted is not None:
            raise DisconnectionError(f"{label} checkout rejected persistent tenant state")
    return guard


def parse_url(value: str, name: str, error: type[Exception]) -> URL:
    try:
        return make_url(value)
    except (ArgumentError, ValueError):
        raise error(f"{name} is invalid") from None


def is_login_user(username: object, role: str) -> bool:
    """Direct ``<role>`` or Supabase shared-pooler ``<role>.<project-ref>``."""
    if type(username) is not str:
        return False
    if username == role:
        return True
    prefix = role + "."
    return username.startswith(prefix) and _PROJECT_REF.fullmatch(username[len(prefix):]) is not None


def create_login_engine(url: str, label: str) -> Engine:
    engine = create_engine(
        url,
        pool_size=1,
        max_overflow=2,
        pool_timeout=POOL_CHECKOUT_TIMEOUT_SECONDS,
        pool_recycle=1800,
        connect_args={"connect_timeout": POSTGRES_CONNECT_TIMEOUT_SECONDS},
        future=True,
    )
    event.listen(engine, "checkout", _checkout_guard(label))
    return engine


def pin_tenant(session: Session, igreja_id: Any, *, info_flag: str, tenant_key: str,
               label: str, error: type[Exception]) -> str:
    """Pin a fresh dedicated session to one tenant; every BEGIN re-proves it."""
    if not session.info.get(info_flag):
        raise error(f"session is not bound to the {label} login")
    try:
        tenant_id = str(uuid.UUID(str(igreja_id).strip()))
    except (AttributeError, TypeError, ValueError):
        raise error(f"igreja_id invalid for {label} scope") from None
    existing = session.info.get(tenant_key)
    if existing is not None and existing != tenant_id:
        raise error(f"{label} session already pinned to another tenant")
    if existing is None and session.in_transaction():
        raise error(f"{label} scope requires a fresh transaction")
    session.info[tenant_key] = tenant_id
    return tenant_id
