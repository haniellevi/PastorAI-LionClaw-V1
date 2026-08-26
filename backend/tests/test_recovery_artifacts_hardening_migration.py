"""Guardas estruturais e prova PostgreSQL do hardening de recuperação."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from psycopg2 import Error as PsycopgError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError

from tests.conftest_rls import rls_database_url  # noqa: F401


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260826_094317_harden_recovery_artifacts_retention.sql"
)
RUNBOOK = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "ops"
    / "RECOVERY-ARTIFACT-RETENTION.md"
)
CLERK_TABLE = "_clerk_migration_rollback_20260823_032220"
RECOVERY_TABLE = "encrypted_credentials_backup_20260805"
POLICY = "recovery_artifact_deny_all"
DATABASE = "recovery_artifacts_hardening_disposable"
CLIENT_ROLES = ("anon", "authenticated")
CORE_TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)
COLUMN_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")


def _executable_sql() -> str:
    executable_lines = (
        line.split("--", 1)[0]
        for line in MIGRATION.read_text(encoding="utf-8").lower().splitlines()
    )
    return " ".join("\n".join(executable_lines).split())


def test_migration_is_structurally_forward_only_and_fail_closed() -> None:
    sql = _executable_sql()

    assert CLERK_TABLE in sql
    assert RECOVERY_TABLE in sql
    assert "set transaction isolation level serializable" in sql
    assert "lock table %i.%i in access exclusive mode" in sql
    assert "unexpected policy state on %i.%i" in sql
    assert "create policy recovery_artifact_deny_all" in sql
    assert "as restrictive for all to public" in sql
    assert "using (false) with check (false)" in sql
    assert "revoke all privileges on table %i.%i" in sql
    assert "revoke all privileges on schema recovery" in sql
    assert "alter table %i.%i enable row level security" in sql
    assert "row count changed on %i.%i" in sql
    assert "2026-11-03" in sql
    assert "2026-11-21" in sql
    assert "drop table" not in sql
    assert "set schema" not in sql
    assert "current_igreja_id" not in sql


def test_runbook_defines_review_gates_without_automatic_deletion() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    migration_hash = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()

    assert MIGRATION.name in runbook
    assert migration_hash in runbook
    assert CLERK_TABLE in runbook
    assert RECOVERY_TABLE in runbook
    assert "2026-11-03" in runbook
    assert "2026-11-21" in runbook
    assert "não disparam exclusão automática" in runbook
    assert "autorização humana nominal" in runbook


def _drop_and_create_database(admin_url: object) -> None:
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f"drop database if exists {DATABASE} with (force)")
            conn.exec_driver_sql(f"create database {DATABASE}")
    finally:
        admin.dispose()


def _ensure_roles(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            do $roles$
            begin
              if not exists (select 1 from pg_roles where rolname = 'anon') then
                create role anon nologin nobypassrls;
              end if;
              if not exists (
                select 1 from pg_roles where rolname = 'authenticated'
              ) then
                create role authenticated nologin nobypassrls;
              end if;
              if not exists (
                select 1 from pg_roles where rolname = 'service_role'
              ) then
                create role service_role nologin bypassrls;
              end if;
            end
            $roles$;

            alter role anon nobypassrls;
            alter role authenticated nobypassrls;
            alter role service_role bypassrls;
            """
        )


@pytest.fixture(scope="module")
def recovery_engine(rls_database_url: str) -> Iterator[Engine]:  # noqa: F811
    """Banco dedicado; o fixture compartilhado veta destinos DEV e PROD."""
    base = make_url(rls_database_url)
    admin_url = base.set(database="postgres")
    _drop_and_create_database(admin_url)
    engine = create_engine(base.set(database=DATABASE), future=True)
    _ensure_roles(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
        try:
            with admin.connect() as conn:
                conn.exec_driver_sql(
                    f"drop database if exists {DATABASE} with (force)"
                )
        finally:
            admin.dispose()


def _reset_artifacts(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(f"drop table if exists public.{CLERK_TABLE} cascade")
        conn.exec_driver_sql("drop schema if exists recovery cascade")
        conn.exec_driver_sql(
            f"""
            create table public.{CLERK_TABLE} (
              app_user_id uuid primary key,
              email text not null,
              old_clerk_user_id text,
              new_clerk_user_id text,
              migrated_at timestamptz
            );
            create schema recovery;
            create table recovery.{RECOVERY_TABLE} (
              source text not null,
              id uuid primary key,
              igreja_id uuid not null,
              payload jsonb not null,
              backed_up_at timestamptz not null
            );
            """
        )
        conn.exec_driver_sql(
            "grant usage on schema public to anon, authenticated, service_role"
        )
        conn.exec_driver_sql(
            "grant usage, create on schema recovery "
            "to anon, authenticated, service_role"
        )
        conn.exec_driver_sql(
            f"grant all privileges on table public.{CLERK_TABLE} "
            "to anon, authenticated, service_role"
        )
        conn.exec_driver_sql(
            f"grant all privileges on table recovery.{RECOVERY_TABLE} "
            "to anon, authenticated, service_role"
        )
        conn.exec_driver_sql(
            f"""
            insert into public.{CLERK_TABLE} (
              app_user_id, email, old_clerk_user_id, new_clerk_user_id, migrated_at
            )
            select gen_random_uuid(),
                   format('synthetic-%%s@example.invalid', value),
                   format('old-%%s', value),
                   format('new-%%s', value),
                   now()
              from generate_series(1, 6) as value;

            insert into recovery.{RECOVERY_TABLE} (
              source, id, igreja_id, payload, backed_up_at
            )
            select 'synthetic', gen_random_uuid(), gen_random_uuid(),
                   jsonb_build_object('synthetic', value), now()
              from generate_series(1, 2) as value;
            """
        )


def _apply(engine: Engine) -> None:
    connection = engine.raw_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _applicable_table_privileges(connection) -> tuple[str, ...]:
    version = int(connection.exec_driver_sql("show server_version_num").scalar_one())
    if version >= 170000:
        return (*CORE_TABLE_PRIVILEGES, "MAINTAIN")
    return CORE_TABLE_PRIVILEGES


def _assert_exact_policy(connection, qualified_table: str) -> None:
    row = connection.execute(
        text(
            """
            select c.relrowsecurity,
                   p.polname,
                   p.polcmd,
                   p.polpermissive,
                   p.polroles::text,
                   pg_get_expr(p.polqual, p.polrelid),
                   pg_get_expr(p.polwithcheck, p.polrelid)
              from pg_class c
              join pg_policy p on p.polrelid = c.oid
             where c.oid = cast(:table as regclass)
            """
        ),
        {"table": qualified_table},
    ).one()
    assert row == (True, POLICY, "*", False, "{0}", "false", "false")


def _assert_no_privileges(
    connection,
    qualified_table: str,
    roles: tuple[str, ...],
) -> None:
    privileges = _applicable_table_privileges(connection)
    columns = tuple(
        connection.execute(
            text(
                """
                select attname
                  from pg_attribute
                 where attrelid = cast(:table as regclass)
                   and attnum > 0
                   and not attisdropped
                 order by attnum
                """
            ),
            {"table": qualified_table},
        ).scalars()
    )
    for role in roles:
        for privilege in privileges:
            assert not connection.execute(
                text("select has_table_privilege(:role, :table, :privilege)"),
                {
                    "role": role,
                    "table": qualified_table,
                    "privilege": privilege,
                },
            ).scalar_one()
        for column in columns:
            for privilege in COLUMN_PRIVILEGES:
                assert not connection.execute(
                    text(
                        "select has_column_privilege("
                        ":role, :table, :column, :privilege)"
                    ),
                    {
                        "role": role,
                        "table": qualified_table,
                        "column": column,
                        "privilege": privilege,
                    },
                ).scalar_one()


def _assert_role_cannot_select(
    engine: Engine,
    role: str,
    qualified_table: str,
) -> None:
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.exec_driver_sql(f"set local role {role}")
            with pytest.raises(DBAPIError, match="permission denied"):
                conn.exec_driver_sql(f"select count(*) from {qualified_table}")
        finally:
            transaction.rollback()


@pytest.mark.rls_integration
def test_apply_preserves_rows_and_closes_both_artifacts(
    recovery_engine: Engine,
) -> None:
    _reset_artifacts(recovery_engine)

    _apply(recovery_engine)
    _apply(recovery_engine)

    with recovery_engine.connect() as conn:
        assert conn.exec_driver_sql(
            f"select count(*) from public.{CLERK_TABLE}"
        ).scalar_one() == 6
        assert conn.exec_driver_sql(
            f"select count(*) from recovery.{RECOVERY_TABLE}"
        ).scalar_one() == 2

        _assert_exact_policy(conn, f"public.{CLERK_TABLE}")
        _assert_exact_policy(conn, f"recovery.{RECOVERY_TABLE}")
        _assert_no_privileges(conn, f"public.{CLERK_TABLE}", CLIENT_ROLES)
        _assert_no_privileges(
            conn,
            f"recovery.{RECOVERY_TABLE}",
            (*CLIENT_ROLES, "service_role"),
        )

        public_rls_violations = conn.exec_driver_sql(
            """
            select c.relname
              from pg_class c
              join pg_namespace n on n.oid = c.relnamespace
             where n.nspname = 'public'
               and c.relkind in ('r', 'p')
               and (
                 not c.relrowsecurity
                 or not exists (
                   select 1 from pg_policy p where p.polrelid = c.oid
                 )
               )
             order by c.relname
            """
        ).scalars().all()
        assert public_rls_violations == []

        for role in (*CLIENT_ROLES, "service_role"):
            assert not conn.execute(
                text("select has_schema_privilege(:role, 'recovery', 'usage')"),
                {"role": role},
            ).scalar_one()
            assert not conn.execute(
                text("select has_schema_privilege(:role, 'recovery', 'create')"),
                {"role": role},
            ).scalar_one()

        clerk_comment = conn.exec_driver_sql(
            f"select obj_description('public.{CLERK_TABLE}'::regclass, 'pg_class')"
        ).scalar_one()
        recovery_comment = conn.exec_driver_sql(
            f"select obj_description('recovery.{RECOVERY_TABLE}'::regclass, 'pg_class')"
        ).scalar_one()
        assert "2026-11-21" in clerk_comment
        assert "2026-11-03" in recovery_comment

        for privilege in _applicable_table_privileges(conn):
            assert conn.execute(
                text(
                    "select has_table_privilege("
                    "'service_role', :table, :privilege)"
                ),
                {
                    "table": f"public.{CLERK_TABLE}",
                    "privilege": privilege,
                },
            ).scalar_one()

    for role in CLIENT_ROLES:
        _assert_role_cannot_select(
            recovery_engine,
            role,
            f"public.{CLERK_TABLE}",
        )
    for role in (*CLIENT_ROLES, "service_role"):
        _assert_role_cannot_select(
            recovery_engine,
            role,
            f"recovery.{RECOVERY_TABLE}",
        )


@pytest.mark.rls_integration
def test_absent_optional_artifacts_are_a_safe_noop(
    recovery_engine: Engine,
) -> None:
    with recovery_engine.begin() as conn:
        conn.exec_driver_sql(f"drop table if exists public.{CLERK_TABLE} cascade")
        conn.exec_driver_sql("drop schema if exists recovery cascade")

    _apply(recovery_engine)
    _apply(recovery_engine)

    with recovery_engine.connect() as conn:
        assert conn.exec_driver_sql(
            f"select to_regclass('public.{CLERK_TABLE}')"
        ).scalar_one() is None
        assert conn.exec_driver_sql(
            f"select to_regclass('recovery.{RECOVERY_TABLE}')"
        ).scalar_one() is None


@pytest.mark.rls_integration
def test_unexpected_policy_rolls_back_all_changes(
    recovery_engine: Engine,
) -> None:
    _reset_artifacts(recovery_engine)
    with recovery_engine.begin() as conn:
        conn.exec_driver_sql(
            f"create policy unexpected_allow on public.{CLERK_TABLE} "
            "for select to authenticated using (true)"
        )

    with pytest.raises(PsycopgError, match="unexpected policy state"):
        _apply(recovery_engine)

    with recovery_engine.connect() as conn:
        public_rls = conn.exec_driver_sql(
            f"select relrowsecurity from pg_class "
            f"where oid = 'public.{CLERK_TABLE}'::regclass"
        ).scalar_one()
        recovery_rls = conn.exec_driver_sql(
            f"select relrowsecurity from pg_class "
            f"where oid = 'recovery.{RECOVERY_TABLE}'::regclass"
        ).scalar_one()
        assert public_rls is False
        assert recovery_rls is False
        assert conn.exec_driver_sql(
            f"select count(*) from public.{CLERK_TABLE}"
        ).scalar_one() == 6
        assert conn.exec_driver_sql(
            f"select count(*) from recovery.{RECOVERY_TABLE}"
        ).scalar_one() == 2
