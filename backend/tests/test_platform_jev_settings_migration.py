"""Executa a migration da configuração do Jev em PostgreSQL descartável."""

from pathlib import Path
import uuid

import psycopg2
import pytest
from psycopg2.errors import CheckViolation, InsufficientPrivilege
from sqlalchemy import create_engine

from tests.conftest_rls import rls_database_url  # noqa: F401


MIGRATION = Path(__file__).parents[1] / "migrations" / (
    "20260926_120446_platform_jev_settings.sql"
)

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def migrated_db(rls_database_url):
    engine = create_engine(rls_database_url)
    schema = "jev_settings_test_" + uuid.uuid4().hex
    connection = engine.raw_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(f"create schema {schema}")
        cursor.execute(f"set local search_path = {schema}, public")
        cursor.execute(f"""
            do $$ begin
              if not exists (select 1 from pg_roles where rolname='authenticated') then
                create role authenticated nologin nobypassrls;
              end if;
              if not exists (select 1 from pg_roles where rolname='anon') then
                create role anon nologin nobypassrls;
              end if;
            end $$;
            grant usage on schema {schema} to authenticated, anon;
            alter default privileges in schema {schema}
              grant select, insert, update, delete on tables to authenticated, anon;
        """)
        sql = MIGRATION.read_text().replace("public.", schema + ".")
        cursor.execute(sql)
        cursor.execute(sql)
        yield cursor, schema
    finally:
        connection.rollback()
        cursor.close()
        connection.close()
        engine.dispose()


def _violates(cursor, statement: str, params=()) -> type[Exception] | None:
    cursor.execute("savepoint tentativa")
    try:
        cursor.execute(statement, params)
    except psycopg2.Error as exc:
        cursor.execute("rollback to savepoint tentativa")
        return type(exc)
    cursor.execute("release savepoint tentativa")
    return None


def test_tabela_fica_fechada_para_anon_e_authenticated(migrated_db):
    cursor, schema = migrated_db
    tabela = f"{schema}.platform_jev_settings"
    cursor.execute(
        "select relrowsecurity from pg_class where oid = %s::regclass", (tabela,)
    )
    assert cursor.fetchone() == (True,)
    cursor.execute(
        "select polname, polpermissive, polcmd from pg_policy where polrelid = %s::regclass",
        (tabela,),
    )
    assert cursor.fetchall() == [("service_role_bypass_only", False, "*")]
    for role in ("anon", "authenticated"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            cursor.execute(
                "select has_table_privilege(%s, %s, %s)", (role, tabela, privilege)
            )
            assert cursor.fetchone() == (False,), (role, privilege)


def test_authenticated_nao_le_a_chave_cifrada(migrated_db):
    cursor, _ = migrated_db
    cursor.execute(
        "insert into platform_jev_settings(id, api_key_encrypted) values (1, 'cifrada')"
    )
    cursor.execute("set local role authenticated")
    with pytest.raises(InsufficientPrivilege):
        cursor.execute("select api_key_encrypted from platform_jev_settings")


def test_linha_unica_e_travas_de_valor(migrated_db):
    cursor, _ = migrated_db
    igreja = str(uuid.uuid4())

    assert _violates(cursor, "insert into platform_jev_settings(id) values (2)") is CheckViolation
    assert (
        _violates(
            cursor,
            "insert into platform_jev_settings(igreja_ids) values (array[%s]::uuid[])",
            (igreja,),
        )
        is CheckViolation
    )
    assert (
        _violates(cursor, "insert into platform_jev_settings(modelo) values ('gpt-5.6-luna')")
        is CheckViolation
    )
    assert (
        _violates(cursor, "insert into platform_jev_settings(timeout_seconds) values (11)")
        is CheckViolation
    )
    assert (
        _violates(
            cursor,
            "insert into platform_jev_settings(modelo, timeout_seconds, igreja_ids,"
            " dpa_assinado_em) values ('jev-1.13', 1.5, array[%s]::uuid[], date '2026-09-20')",
            (igreja,),
        )
        is None
    )
    cursor.execute("select id, modelo, cardinality(igreja_ids) from platform_jev_settings")
    assert cursor.fetchall() == [(1, "jev-1.13", 1)]
