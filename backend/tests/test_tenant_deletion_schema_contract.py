"""Compare the deletion plan with foreign keys installed by the real SQL."""

from pathlib import Path

import pytest
from sqlalchemy import text

from app.db.models import Pessoa
from app.services import tenant_deletion
from tests.conftest_rls import rls_database_url  # noqa: F401
from tests.test_d1a_tenant_runtime_integrity_migration import (
    _SCHEMA,
    _apply_real_migration,
    d1a_engine,  # noqa: F401
)

pytestmark = pytest.mark.rls_integration


def test_pre_detach_cleanup_covers_composite_fks_from_real_migrations(d1a_engine):
    _apply_real_migration(d1a_engine)
    with d1a_engine.begin() as connection:
        connection.exec_driver_sql(f"""
            do $$ begin
              if not exists (select 1 from pg_roles where rolname='authenticated') then
                create role authenticated nologin nobypassrls;
              end if;
              if not exists (select 1 from pg_roles where rolname='anon') then
                create role anon nologin nobypassrls;
              end if;
              if not exists (select 1 from pg_roles where rolname='service_role') then
                create role service_role nologin nobypassrls;
              end if;
            end $$;
            create function {_SCHEMA}.current_igreja_id() returns uuid
            language sql stable security definer set search_path=pg_catalog
            as $$ select nullif(current_setting('app.tenant_igreja_id',true),'')::uuid $$;
        """)
    migration = Path(__file__).parents[1] / "migrations" / (
        "20260828_045213_d2b2_consentimento_finalidade_evento.sql"
    )
    # Redirect only the disposable namespace; execute the complete migration,
    # including its constraints, policies and append-only trigger guards.
    sql = migration.read_text().replace("public.", f"{_SCHEMA}.")
    sql = sql.replace("'public'", f"'{_SCHEMA}'")
    raw = d1a_engine.raw_connection()
    try:
        with raw.cursor() as cursor:
            cursor.execute(sql)
        raw.commit()
    finally:
        raw.close()

    with d1a_engine.connect() as connection:
        rows = connection.execute(text("""
            select rel.relname, array(
                select a.attname from unnest(c.conkey) with ordinality k(n,ord)
                join pg_attribute a on a.attrelid=c.conrelid and a.attnum=k.n
                order by k.ord
            ) as columns
            from pg_constraint c join pg_class rel on rel.oid=c.conrelid
            where c.contype='f' and c.confrelid=cast(:parent as regclass)
              and cardinality(c.conkey)>1
            order by rel.relname
        """), {"parent": f"{_SCHEMA}.app_users"}).all()
        actual = {row.relname for row in rows}
        direct = {model.__tablename__ for model in tenant_deletion._PRE_DETACH_DELETE_MODELS}
        # Pessoa is explicitly removed before detach; its ledger follows the
        # real ON DELETE CASCADE FK instead of a forbidden direct ledger DELETE.
        assert actual == direct | {Pessoa.__tablename__, "consentimento_finalidade_evento"}
        assert all(row.columns[0] == "igreja_id" for row in rows)
        cascade = connection.execute(text("""
            select confdeltype from pg_constraint
            where contype='f' and cardinality(conkey)=2
              and conrelid=cast(:ledger as regclass) and confrelid=cast(:person as regclass)
        """), {
            "ledger": f"{_SCHEMA}.consentimento_finalidade_evento",
            "person": f"{_SCHEMA}.pessoas",
        }).scalar_one()
        assert cascade == "c"
