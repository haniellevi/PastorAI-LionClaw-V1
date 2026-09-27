"""Tenant context in one round trip, proved against a disposable Postgres.

`set_tenant_context`, `set_tenant_context_for_igreja` and the after_begin
listener now send the tenant GUC and `set_config('role', 'authenticated', true)`
in a single statement instead of a separate `SET LOCAL ROLE`. These tests prove
on a real server that the single statement still drops to the NOBYPASSRLS role,
that RLS isolates the tenants, that both settings revert with the transaction,
and that the role switch keeps the same membership check as `SET ROLE`.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

import app.db.session as session_module
from app.db.rls import set_tenant_context, set_tenant_context_for_igreja
from app.db.tenant_session import mark_tenant_scoped
from tests.conftest_rls import (  # noqa: F401
    CLERK_A,
    IGREJA_A,
    IGREJA_B,
    rls_database_url,
    rls_engine,
    rls_seeded,
)

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def statements(rls_engine: Engine) -> Iterator[list[str]]:
    """Every statement SQLAlchemy sends through ``rls_engine``."""
    sent: list[str] = []

    def _record(_conn, _cursor, statement, _params, _context, _many) -> None:
        sent.append(statement)

    event.listen(rls_engine, "before_cursor_execute", _record)
    try:
        yield sent
    finally:
        event.remove(rls_engine, "before_cursor_execute", _record)


@pytest.fixture
def session(rls_engine: Engine, rls_seeded: dict[str, str]) -> Iterator[Session]:
    db = sessionmaker(bind=rls_engine, future=True)()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def _identity(db: Session) -> tuple[str, str, str | None]:
    row = db.execute(
        text(
            "select current_user::text, current_setting('role'), "
            "nullif(current_setting('app.tenant_igreja_id', true), '')"
        )
    ).one()
    return row[0], row[1], row[2]


def _visible_igrejas(db: Session) -> set[str]:
    rows = db.execute(text("select igreja_id::text from pessoas")).scalars().all()
    return set(rows)


def test_clerk_context_is_one_statement_and_enforces_rls(
    session: Session, statements: list[str]
) -> None:
    connection_role = session.execute(text("select current_user::text")).scalar_one()
    before = len(statements)

    set_tenant_context(session, CLERK_A)

    assert len(statements) - before == 1
    assert "set_config('role', 'authenticated', true)" in statements[-1]
    assert _identity(session)[:2] == ("authenticated", "authenticated")
    assert _visible_igrejas(session) == {IGREJA_A}

    session.rollback()
    assert _identity(session) == (connection_role, "none", None)
    assert len(_visible_igrejas(session)) >= 2  # back on BYPASSRLS, not leaked


def test_igreja_context_is_one_statement_and_enforces_rls(
    session: Session, statements: list[str]
) -> None:
    connection_role = session.execute(text("select current_user::text")).scalar_one()
    before = len(statements)

    set_tenant_context_for_igreja(session, IGREJA_B)

    assert len(statements) - before == 1
    assert _identity(session) == ("authenticated", "authenticated", IGREJA_B)
    assert _visible_igrejas(session) == {IGREJA_B}

    session.commit()
    assert _identity(session) == (connection_role, "none", None)


def test_listener_reapplies_scope_in_one_statement_after_commit(
    session: Session, statements: list[str]
) -> None:
    mark_tenant_scoped(session, IGREJA_A, source="test")
    session.commit()  # SET LOCAL/set_config(..., true) revert here
    before = len(statements)

    visible = _visible_igrejas(session)

    # The new transaction starts with the listener's single context statement,
    # then the query itself.
    assert len(statements) - before == 2
    assert "set_config('role', 'authenticated', true)" in statements[before]
    assert visible == {IGREJA_A}
    assert _identity(session) == ("authenticated", "authenticated", IGREJA_A)


@pytest.fixture
def unprivileged_login(rls_database_url: str, rls_seeded) -> Iterator[SimpleNamespace]:
    """A LOGIN role without superuser, like Supabase's `postgres` connection."""
    name = f"rt_login_{uuid.uuid4().hex[:8]}"
    password = uuid.uuid4().hex
    admin = create_engine(rls_database_url, future=True)
    with admin.begin() as conn:
        conn.exec_driver_sql(
            f"create role {name} login nosuperuser nobypassrls password '{password}'"
        )
        conn.exec_driver_sql(f"grant usage on schema public to {name}")
    url = admin.url.set(username=name, password=password)
    login_engine = create_engine(url, future=True)
    try:
        yield SimpleNamespace(name=name, admin=admin, engine=login_engine)
    finally:
        login_engine.dispose()
        with admin.begin() as conn:
            conn.exec_driver_sql(f"revoke authenticated from {name}")
            conn.exec_driver_sql(f"revoke usage on schema public from {name}")
            conn.exec_driver_sql(f"drop role {name}")
        admin.dispose()


def _sqlstate(engine: Engine, sql: str) -> str | None:
    with engine.connect() as conn:
        try:
            conn.exec_driver_sql(sql)
        except DBAPIError as exc:
            return exc.orig.pgcode
        finally:
            conn.rollback()
    return None


def test_role_set_config_has_the_same_membership_check_as_set_role(
    unprivileged_login: SimpleNamespace,
) -> None:
    set_role = "set local role authenticated"
    set_config = "select set_config('role', 'authenticated', true)"

    # Not a member: both forms are refused with insufficient_privilege.
    assert _sqlstate(unprivileged_login.engine, set_role) == "42501"
    assert _sqlstate(unprivileged_login.engine, set_config) == "42501"

    with unprivileged_login.admin.begin() as conn:
        conn.exec_driver_sql(f"grant authenticated to {unprivileged_login.name}")

    # Member (the Supabase setup): both succeed, the role applies only to the
    # transaction and RLS scopes the tenant.
    assert _sqlstate(unprivileged_login.engine, set_role) is None
    login_session = sessionmaker(bind=unprivileged_login.engine, future=True)()
    try:
        set_tenant_context_for_igreja(login_session, IGREJA_A)
        assert _identity(login_session) == ("authenticated", "authenticated", IGREJA_A)
        assert _visible_igrejas(login_session) == {IGREJA_A}
        login_session.rollback()
        assert login_session.execute(
            text("select current_user::text")
        ).scalar_one() == unprivileged_login.name
    finally:
        login_session.rollback()
        login_session.close()


def test_idle_ping_replaces_a_connection_killed_while_idle(
    rls_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        session_module,
        "get_settings",
        lambda: SimpleNamespace(
            database_url=rls_database_url, db_pool_ping_idle_seconds=0.2
        ),
    )
    monkeypatch.setattr(session_module, "_engine", None)
    engine = session_module.get_engine()
    pings: list[int] = []
    real_ping = engine.dialect.do_ping

    def counting_ping(dbapi_connection):
        pings.append(1)
        return real_ping(dbapi_connection)

    monkeypatch.setattr(engine.dialect, "do_ping", counting_ping)
    pid_sql = "select pg_backend_pid()"
    try:
        with engine.connect() as conn:
            first_pid = conn.exec_driver_sql(pid_sql).scalar_one()
        with engine.connect() as conn:  # reused at once: no ping
            assert conn.exec_driver_sql(pid_sql).scalar_one() == first_pid
        assert pings == []

        admin = create_engine(rls_database_url, future=True)
        try:
            with admin.begin() as conn:
                conn.exec_driver_sql(f"select pg_terminate_backend({first_pid})")
        finally:
            admin.dispose()
        time.sleep(0.4)

        # Idle past the threshold: the ping finds the dead connection and the
        # pool hands out a fresh one instead of failing the request.
        with engine.connect() as conn:
            new_pid = conn.exec_driver_sql(pid_sql).scalar_one()
        assert new_pid != first_pid
        assert pings == [1]
    finally:
        engine.dispose()
