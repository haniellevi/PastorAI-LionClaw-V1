"""Guardas estruturais e prova PostgreSQL da migration RLS da Missão 06."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError

from tests.conftest_rls import rls_database_url  # noqa: F401


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
POLICIES = MIGRATIONS / "20260810_031050_explicit_deny_policies_for_closed_tables.sql"
POLICY_TABLES = (
    "password_reset_tokens",
    "platform_admins",
    "platform_audit_log",
    "platform_orchestrator",
)
TEST_ROLES = ("anon", "authenticated", "service_role")
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE")
_M06_DATABASE = "m06_hardening_disposable"


def _sql(path: Path) -> str:
    executable_lines = (
        line.split("--", 1)[0]
        for line in path.read_text(encoding="utf-8").lower().splitlines()
    )
    return " ".join("\n".join(executable_lines).split())


def test_closed_tables_receive_only_an_explicit_deny_policy() -> None:
    sql = _sql(POLICIES)

    for table in POLICY_TABLES:
        assert f"'{table}'" in sql

    assert "alter table public.%i enable row level security" in sql
    assert "create policy service_role_bypass_only" in sql
    assert "for all to public using (false) with check (false)" in sql
    assert "from pg_policy" in sql
    assert "not exists" in sql
    assert sql.index("enable row level security") < sql.index("create policy")
    assert sql.count("create policy") == 1

    # Esta onda não muda grants nem substitui policies que possam surgir antes
    # do gate de aplicação.
    assert "grant " not in sql
    assert "revoke " not in sql
    assert "drop policy" not in sql
    assert "disable row level security" not in sql
    assert "using (true)" not in sql
    assert "with check (true)" not in sql


def _drop_and_create_database(admin_url: object, database: str) -> None:
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f"drop database if exists {database} with (force)")
            conn.exec_driver_sql(f"create database {database}")
    finally:
        admin.dispose()


@pytest.fixture(scope="module")
def m06_engine(rls_database_url: str) -> Iterator[Engine]:  # noqa: F811
    """Banco dedicado; o guard de ``rls_database_url`` veta DEV/PROD."""
    base = make_url(rls_database_url)
    admin_url = base.set(database="postgres")
    _drop_and_create_database(admin_url, _M06_DATABASE)
    engine = create_engine(base.set(database=_M06_DATABASE), future=True)

    schema = """
    do $roles$
    begin
      if not exists (select 1 from pg_roles where rolname = 'anon') then
        create role anon nologin nobypassrls;
      end if;
      if not exists (select 1 from pg_roles where rolname = 'authenticated') then
        create role authenticated nologin nobypassrls;
      end if;
      if not exists (select 1 from pg_roles where rolname = 'service_role') then
        create role service_role nologin bypassrls;
      end if;
    end
    $roles$;

    alter role anon nobypassrls;
    alter role authenticated nobypassrls;
    alter role service_role bypassrls;

    create table public.password_reset_tokens (id integer primary key, payload text);
    create table public.platform_admins (id integer primary key, payload text);
    create table public.platform_audit_log (id integer primary key, payload text);
    create table public.platform_orchestrator (id integer primary key, payload text);
    """
    grants_and_seed = "\n".join(
        f"grant select, insert, update, delete on public.{table} "
        "to anon, authenticated, service_role;\n"
        f"insert into public.{table} (id, payload) values (1, 'seed');"
        for table in POLICY_TABLES
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(schema)
        conn.exec_driver_sql(grants_and_seed)

    try:
        yield engine
    finally:
        engine.dispose()
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
        try:
            with admin.connect() as conn:
                conn.exec_driver_sql(
                    f"drop database if exists {_M06_DATABASE} with (force)"
                )
        finally:
            admin.dispose()


def _grant_matrix(engine: Engine) -> dict[tuple[str, str, str], bool]:
    with engine.connect() as conn:
        return {
            (table, role, privilege): bool(
                conn.execute(
                    text("select has_table_privilege(:role, :table, :privilege)"),
                    {
                        "role": role,
                        "table": f"public.{table}",
                        "privilege": privilege,
                    },
                ).scalar_one()
            )
            for table in POLICY_TABLES
            for role in TEST_ROLES
            for privilege in TABLE_PRIVILEGES
        }


def _row_count_as(engine: Engine, role: str, table: str) -> int:
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.exec_driver_sql(f"set local role {role}")
            return int(
                conn.exec_driver_sql(
                    f"select count(*) from public.{table}"
                ).scalar_one()
            )
        finally:
            transaction.rollback()


def _blocked_insert(engine: Engine, role: str, table: str) -> None:
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.exec_driver_sql(f"set local role {role}")
            with pytest.raises(DBAPIError) as error:
                conn.exec_driver_sql(
                    f"insert into public.{table} (id, payload) values (2, 'blocked')"
                )
            assert "row-level security policy" in str(error.value).lower()
        finally:
            transaction.rollback()


def _apply_migration(engine: Engine, migration: str) -> None:
    """Usa o cursor DBAPI para não tratar ``%I`` do PL/pgSQL como parâmetro."""
    connection = engine.raw_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(migration)
        connection.commit()
    finally:
        connection.close()


@pytest.mark.rls_integration
def test_closed_tables_migration_enforces_rls_in_postgres(
    m06_engine: Engine,
) -> None:
    """Aplica/reaplica SQL real e prova grants, RLS e bypass do backend."""
    migration = POLICIES.read_text(encoding="utf-8")
    grants_before = _grant_matrix(m06_engine)
    assert all(grants_before.values())

    for _ in range(2):
        _apply_migration(m06_engine, migration)

    assert _grant_matrix(m06_engine) == grants_before

    with m06_engine.connect() as conn:
        role_bypass = dict(
            conn.execute(
                text(
                    "select rolname, rolbypassrls from pg_roles "
                    "where rolname = any(:roles)"
                ),
                {"roles": list(TEST_ROLES)},
            ).all()
        )
        rows = conn.execute(
            text(
                """
                select c.relname,
                       c.relrowsecurity,
                       count(p.polname) as policy_count,
                       bool_and(p.polpermissive) as policies_are_permissive,
                       bool_and(pg_get_expr(p.polqual, p.polrelid) = 'false') as using_false,
                       bool_and(pg_get_expr(p.polwithcheck, p.polrelid) = 'false') as check_false
                from pg_class c
                join pg_namespace n on n.oid = c.relnamespace
                left join pg_policy p on p.polrelid = c.oid
                where n.nspname = 'public' and c.relname = any(:tables)
                group by c.relname, c.relrowsecurity
                order by c.relname
                """
            ),
            {"tables": list(POLICY_TABLES)},
        ).mappings().all()

    assert role_bypass == {
        "anon": False,
        "authenticated": False,
        "service_role": True,
    }
    assert len(rows) == len(POLICY_TABLES)
    for row in rows:
        assert row["relrowsecurity"] is True
        assert row["policy_count"] == 1
        assert row["policies_are_permissive"] is True
        assert row["using_false"] is True
        assert row["check_false"] is True

    for table in POLICY_TABLES:
        for role in ("anon", "authenticated"):
            assert _row_count_as(m06_engine, role, table) == 0
            _blocked_insert(m06_engine, role, table)
            with m06_engine.connect() as conn:
                transaction = conn.begin()
                try:
                    conn.exec_driver_sql(f"set local role {role}")
                    assert (
                        conn.exec_driver_sql(
                            f"update public.{table} set payload = 'blocked' where id = 1"
                        ).rowcount
                        == 0
                    )
                    assert (
                        conn.exec_driver_sql(
                            f"delete from public.{table} where id = 1"
                        ).rowcount
                        == 0
                    )
                finally:
                    transaction.rollback()

        with m06_engine.connect() as conn:
            transaction = conn.begin()
            try:
                conn.exec_driver_sql("set local role service_role")
                assert (
                    conn.exec_driver_sql(
                        f"select count(*) from public.{table}"
                    ).scalar_one()
                    == 1
                )
                assert (
                    conn.exec_driver_sql(
                        f"insert into public.{table} (id, payload) values (2, 'service')"
                    ).rowcount
                    == 1
                )
                assert (
                    conn.exec_driver_sql(
                        f"update public.{table} set payload = 'updated' where id = 2"
                    ).rowcount
                    == 1
                )
                assert (
                    conn.exec_driver_sql(
                        f"delete from public.{table} where id = 2"
                    ).rowcount
                    == 1
                )
            finally:
                transaction.rollback()
