"""Dedicated database login for the normal queue worker's whole unit of work.

``queue_worker_runtime`` is a real LOGIN (NOSUPERUSER NOBYPASSRLS NOINHERIT,
no CREATEDB/CREATEROLE/REPLICATION) with exactly one membership: the builtin
``authenticated`` WITH INHERIT FALSE, SET TRUE, no ADMIN. Ingestion, turns,
fences, resume and send ownership keep their transactions; the existing seam
(``tenant_session``) still drops each scoped transaction to ``authenticated``
with the church GUC. Before the seam the login has no table privilege at all:
only ``public.queue_resolve_instance`` discovers the church of an instance.

This module only builds the dedicated factory; it never returns the main
session and never falls back to ``DATABASE_URL``. The mode selector lives in
``app.workers.queue_worker``. Proofs (no ``SET ROLE`` stands in for the login):

* connect: the session ``search_path`` is fixed (``pg_temp`` last);
* every pool checkout, including the raw connection of the agent execution
  lease: login, both roles' live attributes, the exact membership, nothing
  owned or granted directly to the login beyond its contract, no role,
  tenant, JWT claims, path drift, ``row_security`` change or temporary relation
  left on the connection; otherwise it is discarded (new backend);
* every outer BEGIN, before the seam: the same login state;
* after the seam (savepoints included): effective ``authenticated`` with exactly
  the pinned church, or the login state when the session is unscoped.

URL user: ``queue_worker_runtime`` (direct) or the Supabase shared-pooler form
``queue_worker_runtime.<project-ref>``. The advisory lease is session-scoped, so
the URL must be direct or a session-mode pooler; the known Supabase transaction
pooler port is refused, and no URL proves the mode of an unknown proxy.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DisconnectionError
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from app.config import get_settings
from app.db import dedicated_login
from app.db.tenant_session import TENANT_IGREJA_KEY, register_after_begin_listener

QUEUE_WORKER_ROLE = "queue_worker_runtime"
QUEUE_WORKER_SEARCH_PATH = "pg_catalog, public, pg_temp"
QUEUE_WORKER_SESSION_FLAG = "queue_worker_session"
_TENANT_ROLE = "authenticated"
_LABEL = "queue worker"
# Supabase shared pooler in transaction mode (port 6543): a session advisory
# lock does not survive there. Other proxies are not guessed.
_SUPABASE_POOLER_SUFFIX = ".pooler.supabase.com"
_SUPABASE_TRANSACTION_PORT = 6543
_KEEPALIVE_ARGS = {"keepalives": 1, "keepalives_idle": 30,
                   "keepalives_interval": 10, "keepalives_count": 3}

# One round trip, pg_catalog only. Membership options are read through
# to_jsonb so PostgreSQL 15 (no inherit_option/set_option columns) is never
# queried for absent columns; there NOINHERIT on the login governs inheritance.
_IDENTITY_PROBE = (
    "select session_user::text, current_user::text, pg_catalog.current_setting('role'), "
    "r.rolcanlogin, r.rolinherit, r.rolsuper, r.rolbypassrls, r.rolcreatedb, "
    "r.rolcreaterole, r.rolreplication, "
    "exists(select 1 from pg_catalog.pg_auth_members m where m.member = r.oid) "
    "and not exists(select 1 from pg_catalog.pg_auth_members m where m.member = r.oid "
    " and (m.roleid <> a.oid or m.admin_option "
    "  or coalesce((pg_catalog.to_jsonb(m) ->> 'inherit_option')::boolean, false) "
    "  or not coalesce((pg_catalog.to_jsonb(m) ->> 'set_option')::boolean, true))), "
    # No member may SET or inherit the login. PostgreSQL 16+ gives a
    # non-superuser creator ADMIN with INHERIT/SET FALSE: accepted as operator
    # authority, which stays outside the covered threat.
    "not exists(select 1 from pg_catalog.pg_auth_members m where m.roleid = r.oid "
    " and (coalesce((pg_catalog.to_jsonb(m) ->> 'inherit_option')::boolean, true) "
    "  or coalesce((pg_catalog.to_jsonb(m) ->> 'set_option')::boolean, true))), "
    # Nothing owned or granted directly to the login in this database (or on
    # shared objects) beyond the contract: USAGE on schema public and EXECUTE
    # on the two queue functions, neither with GRANT OPTION.
    "not exists(select 1 from pg_catalog.pg_shdepend d "
    " where d.refclassid = 'pg_catalog.pg_authid'::pg_catalog.regclass and d.refobjid = r.oid "
    "  and (d.dbid = db.oid or (d.dbid = 0 and (d.deptype = 'o' "
    "   or (d.classid = 'pg_catalog.pg_database'::pg_catalog.regclass and d.objid = db.oid) "
    "   or d.classid in ('pg_catalog.pg_parameter_acl'::pg_catalog.regclass, "
    "                    'pg_catalog.pg_tablespace'::pg_catalog.regclass)))) "
    # IS NOT TRUE: an absent queue function makes to_regprocedure() NULL, and
    # NOT(NULL) would silently hide any other dependency.
    "  and (d.deptype = 'a' and ("
    "   (d.classid = 'pg_catalog.pg_namespace'::pg_catalog.regclass "
    "    and d.objid = pg_catalog.to_regnamespace('public')) "
    "   or (d.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass and d.objid in ("
    "    pg_catalog.to_regprocedure('public.queue_worker_runtime_session()'), "
    "    pg_catalog.to_regprocedure('public.queue_resolve_instance(text)'))))) is not true) "
    "and not exists(select 1 from pg_catalog.pg_namespace n, pg_catalog.aclexplode(n.nspacl) x "
    " where n.nspname = 'public' and x.grantee = r.oid "
    "  and (x.privilege_type <> 'USAGE' or x.is_grantable)) "
    "and not exists(select 1 from pg_catalog.pg_proc p, pg_catalog.aclexplode(p.proacl) x "
    " where p.oid in (pg_catalog.to_regprocedure('public.queue_worker_runtime_session()'), "
    "  pg_catalog.to_regprocedure('public.queue_resolve_instance(text)')) "
    "  and x.grantee = r.oid and (x.privilege_type <> 'EXECUTE' or x.is_grantable)), "
    "a.rolsuper, a.rolbypassrls, a.rolcreatedb, a.rolcreaterole, a.rolreplication, "
    "not exists(select 1 from pg_catalog.pg_auth_members m where m.member = a.oid), "
    # An owner reads its tables past RLS unless FORCE is set.
    "not exists(select 1 from pg_catalog.pg_class c where c.relowner = a.oid "
    " and c.relkind in ('r', 'p', 'f', 'm') and not c.relforcerowsecurity), "
    "nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), ''), "
    "nullif(pg_catalog.current_setting('request.jwt.claims', true), ''), "
    "nullif(pg_catalog.current_setting('request.jwt.claim.sub', true), ''), "
    "pg_catalog.current_setting('search_path'), pg_catalog.current_setting('row_security'), "
    "not exists(select 1 from pg_catalog.pg_class c "
    " where c.relnamespace = pg_catalog.pg_my_temp_schema()) "
    "from pg_catalog.pg_roles r, pg_catalog.pg_roles a, pg_catalog.pg_database db "
    "where r.rolname = session_user and a.rolname = 'authenticated' "
    "and db.datname = pg_catalog.current_database()"
)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


class QueueWorkerUnavailable(RuntimeError):
    """The queue worker database mode or dedicated login is invalid or unsafe."""


class QueueWorkerIdentityError(QueueWorkerUnavailable):
    """A connection or transaction did not prove the dedicated identity."""


def _identity_problem(row: Any, *, tenant: str | None) -> str | None:
    """None when proven; otherwise a closed reason code (never a value)."""
    if row is None:
        return "no_role_row"
    (login, effective, role, can_login, inherits, superuser, bypass, createdb, createrole,
     replication, membership_exact, members_safe, login_objects_safe, a_super, a_bypass,
     a_createdb, a_createrole, a_replication, a_no_memberships, a_owns_no_table, guc,
     jwt_claims, jwt_sub, path, row_security, no_temp_relations) = row
    if login != QUEUE_WORKER_ROLE:
        return "session_user"
    if not can_login:
        return "nologin"
    for flag, name in ((inherits, "inherit"), (superuser, "superuser"), (bypass, "bypassrls"),
                       (createdb, "createdb"), (createrole, "createrole"),
                       (replication, "replication")):
        if flag:
            return name
    if not membership_exact:
        return "membership"
    if not members_safe:
        return "login_members"
    if not login_objects_safe:
        return "login_privileges"
    for flag, name in ((a_super, "superuser"), (a_bypass, "bypassrls"), (a_createdb, "createdb"),
                       (a_createrole, "createrole"), (a_replication, "replication")):
        if flag:
            return f"authenticated_{name}"
    if not a_no_memberships:
        return "authenticated_memberships"
    if not a_owns_no_table:
        return "authenticated_owns_tables"
    if jwt_claims is not None:
        return "jwt_claims"
    if jwt_sub is not None:
        return "jwt_claim_sub"
    if path != QUEUE_WORKER_SEARCH_PATH:
        return "search_path"
    if row_security != "on":
        return "row_security"
    if not no_temp_relations:
        return "temp_relations"
    if tenant is None:
        if effective != QUEUE_WORKER_ROLE or role != "none":
            return "effective_not_login"
        if guc is not None:
            return "tenant_guc_before_scope"
        return None
    if effective != _TENANT_ROLE or role != _TENANT_ROLE:
        return "effective_not_authenticated"
    if guc != tenant:
        return "tenant_mismatch"
    return None


def _fix_search_path(dbapi_connection: Any, _record: Any) -> None:
    """Pin the session path once per physical connection, before any use."""
    previous = dbapi_connection.autocommit
    dbapi_connection.autocommit = True
    try:
        with dbapi_connection.cursor() as cursor:
            cursor.execute("select pg_catalog.set_config('search_path', %s, false)",
                           (QUEUE_WORKER_SEARCH_PATH,))
    finally:
        dbapi_connection.autocommit = previous


def _checkout_guard(dbapi_connection: Any, _record: Any, _proxy: Any) -> None:
    """Discard a pooled connection that does not carry exactly the login state."""
    cursor = None
    try:
        previous = dbapi_connection.autocommit
        dbapi_connection.autocommit = True
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute(_IDENTITY_PROBE)
            row = cursor.fetchone()
        finally:
            if cursor is not None:
                cursor.close()
            if not previous and not dbapi_connection.closed:
                dbapi_connection.autocommit = previous
    except BaseException as exc:
        raise DisconnectionError(f"{_LABEL} checkout verification failed") from exc
    problem = _identity_problem(row, tenant=None)
    if problem is not None:
        raise DisconnectionError(f"{_LABEL} checkout rejected: {problem}")


def _prove(connection: Any, tenant: str | None, stage: str) -> None:
    row = connection.exec_driver_sql(_IDENTITY_PROBE).one_or_none()
    problem = _identity_problem(row, tenant=tenant)
    if problem is not None:
        raise QueueWorkerIdentityError(f"{_LABEL} {stage} proof failed: {problem}")


def _prove_login(session: Session, transaction: SessionTransaction, connection: Any) -> None:
    """Outer BEGIN, before the tenant seam: still the bare login, no tenant."""
    if not session.info.get(QUEUE_WORKER_SESSION_FLAG):
        return
    if transaction.nested or transaction.parent is not None:
        return  # A savepoint does not reset the role; _prove_scope re-proves it.
    _prove(connection, None, "begin")


def _prove_scope(session: Session, _transaction: SessionTransaction, connection: Any) -> None:
    """After the tenant seam: exactly the pinned church as ``authenticated``."""
    if not session.info.get(QUEUE_WORKER_SESSION_FLAG):
        return
    tenant = session.info.get(TENANT_IGREJA_KEY)
    _prove(connection, str(tenant) if tenant else None, "scope")


def is_queue_worker_url_user(username: object) -> bool:
    return dedicated_login.is_login_user(username, QUEUE_WORKER_ROLE)


def _validated_url() -> str:
    settings = get_settings()
    url = settings.queue_worker_database_url
    if not url:
        raise QueueWorkerUnavailable("QUEUE_WORKER_DATABASE_URL is not configured")
    parsed = dedicated_login.parse_url(url, "QUEUE_WORKER_DATABASE_URL", QueueWorkerUnavailable)
    if not is_queue_worker_url_user(parsed.username):
        raise QueueWorkerUnavailable("QUEUE_WORKER_DATABASE_URL must authenticate as queue_worker_runtime")
    host = (parsed.host or "").lower()
    if host.endswith(_SUPABASE_POOLER_SUFFIX) and parsed.port == _SUPABASE_TRANSACTION_PORT:
        raise QueueWorkerUnavailable("QUEUE_WORKER_DATABASE_URL must not use the transaction pooler")
    for name, other in (("DATABASE_URL", settings.database_url),
                        ("AGENT_RUNTIME_DATABASE_URL", settings.agent_runtime_database_url),
                        ("PRIVATE_STORAGE_DATABASE_URL", settings.private_storage_database_url),
                        ("PRIVATE_SEND_DATABASE_URL", settings.private_send_database_url),
                        ("PRIVATE_SUMMARY_DATABASE_URL", settings.private_summary_database_url)):
        if other and dedicated_login.parse_url(other, name, QueueWorkerUnavailable) == parsed:
            raise QueueWorkerUnavailable(f"QUEUE_WORKER_DATABASE_URL must differ from {name}")
    return url


def get_queue_worker_session_factory() -> sessionmaker[Session]:
    """Lazy factory bound only to the dedicated login; no privileged fallback."""
    global _engine, _SessionFactory
    if _SessionFactory is None:
        url = _validated_url()
        # The seam must run between the two proofs; registering is idempotent.
        register_after_begin_listener()
        engine = create_engine(
            url,
            # Ingestion, turn sessions and an agent lease held through HTTP.
            pool_size=5,
            max_overflow=10,
            pool_timeout=dedicated_login.POOL_CHECKOUT_TIMEOUT_SECONDS,
            pool_recycle=1800,
            connect_args={"connect_timeout": dedicated_login.POSTGRES_CONNECT_TIMEOUT_SECONDS,
                          **_KEEPALIVE_ARGS},
            future=True,
        )
        event.listen(engine, "connect", _fix_search_path)
        event.listen(engine, "checkout", _checkout_guard)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                               expire_on_commit=False, future=True,
                               info={QUEUE_WORKER_SESSION_FLAG: True})
        event.listen(factory, "after_begin", _prove_login, insert=True)
        event.listen(factory, "after_begin", _prove_scope)
        _engine, _SessionFactory = engine, factory
    return _SessionFactory


def dispose_queue_worker_engine() -> None:
    """Drop the cached engine (configuration change or test teardown)."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = _SessionFactory = None


def is_queue_worker_session(session: Session) -> bool:
    return bool(session.info.get(QUEUE_WORKER_SESSION_FLAG))


def resolve_queue_instance(session: Session, instance: str | None) -> Any | None:
    """Church and official number of an instance, before any tenant scope.

    Exact match, same transaction as the later ``promote_to_tenant``; at most
    one row (``igreja_id``, ``numero``), ``None`` when not registered.
    """
    return session.execute(
        text("select igreja_id, numero from public.queue_resolve_instance(:instance)"),
        {"instance": instance},
    ).one_or_none()


__all__ = [
    "QUEUE_WORKER_ROLE",
    "QUEUE_WORKER_SEARCH_PATH",
    "QUEUE_WORKER_SESSION_FLAG",
    "QueueWorkerIdentityError",
    "QueueWorkerUnavailable",
    "dispose_queue_worker_engine",
    "get_queue_worker_session_factory",
    "is_queue_worker_session",
    "is_queue_worker_url_user",
    "resolve_queue_instance",
]
