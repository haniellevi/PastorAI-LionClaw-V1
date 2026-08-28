"""Contrato PostgreSQL 17 da migration D2B2A de consentimento por finalidade."""

from __future__ import annotations

import pathlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from psycopg2 import Error as PsycopgError
from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.db.tenant_session import mark_tenant_scoped
from app.domain.purpose_consent import (
    OpaquePurposeConsentIdempotencyKey,
    PurposeConsentEventState,
    PurposeConsentPurpose,
    PurposeConsentSource,
    TrustedTermVersion,
)
from app.services.purpose_consent import (
    PurposeConsentIdempotencyConflictError,
    append_purpose_consent_event,
)
from tests.conftest_rls import assert_disposable_database, rls_database_url  # noqa: F401


_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260828_045213_d2b2_consentimento_finalidade_evento.sql"
)
_SCHEMA = "d2b2_consentimento_finalidade"
_TABLE = f"{_SCHEMA}.consentimento_finalidade_evento"

IGREJA_A = "2a000000-0000-0000-0000-000000000001"
IGREJA_B = "2b000000-0000-0000-0000-000000000001"
PESSOA_A = "2a000000-0000-0000-0000-000000000002"
PESSOA_A2 = "2a000000-0000-0000-0000-000000000004"
PESSOA_B = "2b000000-0000-0000-0000-000000000002"
USER_A = "2a000000-0000-0000-0000-000000000003"
USER_B = "2b000000-0000-0000-0000-000000000003"


def _migration_sql() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def _schema_migration_sql() -> str:
    return _migration_sql().replace("public.", f"{_SCHEMA}.")


def _execute_script(engine: Engine, sql: str) -> None:
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute(sql)
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            cursor.close()
    finally:
        raw.close()


def _apply_migration(engine: Engine) -> None:
    _execute_script(engine, _schema_migration_sql())


def _setup_base(engine: Engine, *, schema: str = _SCHEMA) -> None:
    if not schema.replace("_", "").isalnum():
        raise AssertionError("schema sintético inválido")
    ddl = f"""
    do $$ begin
      if to_regrole('anon') is null then
        create role anon nologin noinherit nobypassrls;
      end if;
      if to_regrole('authenticated') is null then
        create role authenticated nologin noinherit nobypassrls;
      end if;
      if to_regrole('service_role') is null then
        create role service_role nologin noinherit;
      end if;
      if to_regrole('agent_runtime') is null then
        create role agent_runtime nologin noinherit nobypassrls;
      end if;
    end $$;

    drop schema if exists {schema} cascade;
    create schema {schema};
    grant usage on schema {schema} to authenticated;

    create table {schema}.igrejas (
      id uuid primary key,
      nome text not null
    );
    create table {schema}.pessoas (
      id uuid primary key,
      igreja_id uuid not null references {schema}.igrejas(id) on delete cascade,
      nome text not null,
      constraint pessoas_igreja_id_id_key unique (igreja_id, id)
    );
    create table {schema}.app_users (
      id uuid primary key,
      igreja_id uuid not null references {schema}.igrejas(id) on delete cascade,
      pessoa_id uuid,
      clerk_user_id text unique,
      constraint app_users_igreja_id_id_key unique (igreja_id, id)
    );

    create function {schema}.current_igreja_id()
    returns uuid
    language sql
    stable
    security definer
    set search_path = {schema}, pg_temp
    as $function$
      select coalesce(
        nullif(current_setting('app.tenant_igreja_id', true), '')::uuid,
        (
          select app_user.igreja_id
            from {schema}.app_users app_user
           where app_user.clerk_user_id = nullif(
             current_setting('request.jwt.claim.sub', true), ''
           )
           limit 1
        )
      )
    $function$;
    grant execute on function {schema}.current_igreja_id() to authenticated;
    grant select, update on table {schema}.pessoas to authenticated;
    grant select on table {schema}.app_users to authenticated;

    insert into {schema}.igrejas (id, nome) values
      ('{IGREJA_A}', 'Igreja A'), ('{IGREJA_B}', 'Igreja B');
    insert into {schema}.pessoas (id, igreja_id, nome) values
      ('{PESSOA_A}', '{IGREJA_A}', 'Pessoa A'),
      ('{PESSOA_B}', '{IGREJA_B}', 'Pessoa B');
    insert into {schema}.app_users (
      id, igreja_id, pessoa_id, clerk_user_id
    ) values
      ('{USER_A}', '{IGREJA_A}', '{PESSOA_A}', 'clerk-a'),
      ('{USER_B}', '{IGREJA_B}', '{PESSOA_B}', 'clerk-b');
    """
    _execute_script(engine, ddl)


@pytest.fixture
def d2b2_engine(rls_database_url: str) -> Engine:
    assert_disposable_database(rls_database_url)
    engine = create_engine(rls_database_url, future=True, pool_size=5)
    _setup_base(engine)
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade")
        engine.dispose()


@pytest.fixture
def d2b2_exact_public_engine(rls_database_url: str) -> Engine:
    """Create a fresh database and execute the migration bytes unchanged."""

    assert_disposable_database(rls_database_url)
    source_url = make_url(rls_database_url)
    database_name = f"d2b2_exact_{uuid.uuid4().hex[:12]}"
    exact_url = source_url.set(database=database_name)
    assert_disposable_database(exact_url.render_as_string(hide_password=False))
    maintenance = create_engine(
        source_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        future=True,
    )
    exact_engine: Engine | None = None
    try:
        with maintenance.connect() as connection:
            connection.exec_driver_sql(f'create database "{database_name}" template template0')
        exact_engine = create_engine(exact_url, future=True)
        _setup_base(exact_engine, schema="public")
        yield exact_engine
    finally:
        if exact_engine is not None:
            exact_engine.dispose()
        with maintenance.connect() as connection:
            connection.exec_driver_sql(
                "select pg_terminate_backend(pid) from pg_stat_activity "
                "where datname=%s and pid <> pg_backend_pid()",
                (database_name,),
            )
            connection.exec_driver_sql(f'drop database if exists "{database_name}"')
        maintenance.dispose()


def _set_authenticated_tenant(connection: Connection, tenant: str) -> None:
    connection.exec_driver_sql("set local role authenticated")
    connection.exec_driver_sql(
        "select set_config('app.tenant_igreja_id', %s, true)", (tenant,)
    )


def _insert_event(
    connection: Connection,
    *,
    igreja_id: str,
    pessoa_id: str,
    finalidade: str = "atendimento_solicitado",
    estado: str = "concedido",
    versao_termo: str = "v1",
    fonte: str = "whatsapp_inbound",
    operador: str | None = None,
    chave: str | None = None,
) -> tuple[str, int, str]:
    chave = chave or f"evt:{uuid.uuid4()}"
    row = connection.exec_driver_sql(
        f"insert into {_TABLE} ("
        "igreja_id, pessoa_id, finalidade, estado, versao_termo, fonte, "
        "registrado_por_app_user_id, chave_idempotencia"
        ") values (%s, %s, %s, %s, %s, %s, %s, %s) "
        "returning id::text, sequencia, registrado_em::text",
        (
            igreja_id,
            pessoa_id,
            finalidade,
            estado,
            versao_termo,
            fonte,
            operador,
            chave,
        ),
    ).one()
    return str(row[0]), int(row[1]), str(row[2])


def test_sql_estatico_declara_fatia_inativa_e_fronteira_fechada() -> None:
    sql = _migration_sql().lower()

    assert sql.lstrip().startswith("-- pastorai d2b2a")
    assert "begin;" in sql
    assert sql.rstrip().endswith("commit;")
    assert "set transaction isolation level serializable" in sql
    assert "set local lock_timeout = '5s'" in sql
    assert "set local statement_timeout = '120s'" in sql
    assert "create table public.consentimento_finalidade_evento" in sql
    assert (
        "alter table public.consentimento_finalidade_evento\n"
        "      force row level security"
    ) in sql
    assert "as restrictive for all to public" in sql
    assert "current_setting('app.tenant_igreja_id'" in sql
    assert "grant select on table public.consentimento_finalidade_evento" in sql
    assert "grant insert (" in sql
    assert "on delete set null" in sql
    assert "pg_advisory_xact_lock" in sql
    assert "security invoker" in sql
    assert "sem backfill" in sql
    assert "insert into public.consentimento_finalidade_evento" not in sql
    assert "consent_records" in sql  # somente declaracao explicita de nao-backfill
    assert "service_role;" in sql  # somente revoke/preflight, nunca grant
    assert "grant all" not in sql
    assert "create role" not in sql
    assert "agent_private" not in sql

    app_root = pathlib.Path(__file__).resolve().parents[1] / "app"
    allowed = {
        app_root / "db" / "models.py",
        app_root / "domain" / "purpose_consent.py",
        app_root / "domain" / "purpose_consent_security.py",
        app_root / "services" / "purpose_consent.py",
    }
    unexpected_callers = [
        path.relative_to(app_root).as_posix()
        for path in app_root.rglob("*.py")
        if path not in allowed
        and (
            "purpose_consent" in path.read_text(encoding="utf-8")
            or "ConsentimentoFinalidadeEvento"
            in path.read_text(encoding="utf-8")
        )
    ]
    assert unexpected_callers == []


@pytest.mark.rls_integration
def test_aplica_bytes_exatos_da_migration_duas_vezes_em_public(
    d2b2_exact_public_engine: Engine,
) -> None:
    sql = _migration_sql()
    _execute_script(d2b2_exact_public_engine, sql)
    _execute_script(d2b2_exact_public_engine, sql)

    with d2b2_exact_public_engine.begin() as connection:
        relation = connection.exec_driver_sql(
            "select relkind, relrowsecurity, relforcerowsecurity "
            "from pg_class where oid='public.consentimento_finalidade_evento'::regclass"
        ).one()
        assert tuple(relation) == ("r", True, True)
        assert connection.exec_driver_sql(
            "select count(*) from public.consentimento_finalidade_evento"
        ).scalar_one() == 0


@pytest.mark.rls_integration
def test_aplica_variante_isolada_duas_vezes_e_prova_catalogo_acl(
    d2b2_engine: Engine,
) -> None:
    _apply_migration(d2b2_engine)
    _apply_migration(d2b2_engine)

    with d2b2_engine.begin() as connection:
        relation = connection.exec_driver_sql(
            "select relkind, relrowsecurity, relforcerowsecurity "
            "from pg_class where oid = %s::regclass",
            (_TABLE,),
        ).one()
        columns = connection.exec_driver_sql(
            "select attname, format_type(atttypid, atttypmod), attnotnull "
            "from pg_attribute where attrelid = %s::regclass "
            "and attnum > 0 and not attisdropped order by attnum",
            (_TABLE,),
        ).all()
        constraints = connection.exec_driver_sql(
            "select conname, contype, confdeltype, convalidated "
            "from pg_constraint where conrelid = %s::regclass order by conname",
            (_TABLE,),
        ).all()
        indexes = connection.exec_driver_sql(
            "select c.relname, i.indnkeyatts, i.indnatts, am.amname, "
            "i.indisvalid, i.indisready, i.indislive, i.indisunique, "
            "i.indisprimary, array_agg(a.attname order by k.ordinality) "
            "from pg_index i join pg_class c on c.oid=i.indexrelid "
            "join pg_am am on am.oid=c.relam "
            "cross join lateral unnest(i.indkey) with ordinality k(attnum, ordinality) "
            "join pg_attribute a on a.attrelid=i.indrelid and a.attnum=k.attnum "
            "where i.indrelid=%s::regclass "
            "group by c.relname, i.indnkeyatts, i.indnatts, am.amname, "
            "i.indisvalid, i.indisready, i.indislive, i.indisunique, i.indisprimary "
            "order by c.relname",
            (_TABLE,),
        ).all()
        policies = connection.exec_driver_sql(
            "select polname, polcmd, polpermissive, polroles "
            "from pg_policy where polrelid=%s::regclass order by polname",
            (_TABLE,),
        ).all()
        triggers = connection.exec_driver_sql(
            "select tgname, tgtype from pg_trigger "
            "where tgrelid=%s::regclass and not tgisinternal order by tgname",
            (_TABLE,),
        ).all()
        table_acl = connection.exec_driver_sql(
            "select has_table_privilege('authenticated', %s, 'SELECT'), "
            "has_table_privilege('authenticated', %s, 'INSERT'), "
            "has_table_privilege('authenticated', %s, 'UPDATE'), "
            "has_table_privilege('anon', %s, 'SELECT'), "
            "has_table_privilege('service_role', %s, 'SELECT'), "
            "has_table_privilege('agent_runtime', %s, 'SELECT')",
            (_TABLE, _TABLE, _TABLE, _TABLE, _TABLE, _TABLE),
        ).one()
        all_columns = tuple(row.attname for row in columns)
        column_acl = {
            (column, privilege): connection.exec_driver_sql(
                "select has_column_privilege('authenticated', %s, %s, %s)",
                (_TABLE, column, privilege),
            ).scalar_one()
            for column in all_columns
            for privilege in ("INSERT", "UPDATE", "REFERENCES")
        }
        function_acl = {
            (role, function): connection.exec_driver_sql(
                "select has_function_privilege(%s, %s, 'EXECUTE')",
                (role, f"{_SCHEMA}.{function}()"),
            ).scalar_one()
            for role in ("anon", "authenticated", "service_role", "agent_runtime")
            for function in (
                "consentimento_finalidade_evento_prepare_insert",
                "consentimento_finalidade_evento_append_only",
            )
        }
        authenticated_oid = connection.exec_driver_sql(
            "select 'authenticated'::regrole::oid"
        ).scalar_one()
        table_privileges = {
            (role, privilege): connection.exec_driver_sql(
                "select has_table_privilege(%s, %s, %s)",
                (role, _TABLE, privilege),
            ).scalar_one()
            for role in ("anon", "authenticated", "service_role", "agent_runtime")
            for privilege in (
                "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE",
                "REFERENCES", "TRIGGER", "MAINTAIN",
            )
        }

    assert tuple(relation) == ("r", True, True)
    assert [tuple(row) for row in columns] == [
        ("id", "uuid", True),
        ("igreja_id", "uuid", True),
        ("pessoa_id", "uuid", True),
        ("finalidade", "text", True),
        ("estado", "text", True),
        ("versao_termo", "text", True),
        ("fonte", "text", True),
        ("registrado_por_app_user_id", "uuid", False),
        ("chave_idempotencia", "text", True),
        ("sequencia", "bigint", True),
        ("registrado_em", "timestamp with time zone", True),
    ]
    constraint_contract = {
        row.conname: (row.contype, row.confdeltype, row.convalidated)
        for row in constraints
    }
    assert set(constraint_contract) == {
        "consentimento_finalidade_evento_pkey",
        "consentimento_finalidade_evento_igreja_fkey",
        "consentimento_finalidade_evento_tenant_id_key",
        "consentimento_finalidade_evento_idempotencia_key",
        "consentimento_finalidade_evento_stream_seq_key",
        "consentimento_finalidade_evento_tenant_pessoa_fkey",
        "consentimento_finalidade_evento_registrado_por_fkey",
        "consentimento_finalidade_evento_tenant_registrado_por_fkey",
        "consentimento_finalidade_evento_finalidade_check",
        "consentimento_finalidade_evento_estado_check",
        "consentimento_finalidade_evento_fonte_check",
        "consentimento_finalidade_evento_versao_termo_check",
        "consentimento_finalidade_evento_chave_idempotencia_check",
    }
    assert all(contract[2] for contract in constraint_contract.values())
    assert constraint_contract["consentimento_finalidade_evento_igreja_fkey"][:2] == ("f", "c")
    assert constraint_contract["consentimento_finalidade_evento_tenant_pessoa_fkey"][:2] == ("f", "c")
    assert constraint_contract["consentimento_finalidade_evento_registrado_por_fkey"][:2] == ("f", "n")
    assert constraint_contract["consentimento_finalidade_evento_tenant_registrado_por_fkey"][:2] == ("f", "a")
    assert len(indexes) == 5
    actor_index = next(
        row
        for row in indexes
        if row[0] == "consentimento_finalidade_evento_registrado_por_idx"
    )
    assert tuple(actor_index[1:9]) == (
        2,
        2,
        "btree",
        True,
        True,
        True,
        False,
        False,
    )
    assert tuple(actor_index[9]) == (
        "registrado_por_app_user_id",
        "igreja_id",
    )
    policy_contract = {
        row.polname: (row.polcmd, row.polpermissive, tuple(row.polroles))
        for row in policies
    }
    assert policy_contract == {
        "consentimento_finalidade_evento_insert_tenant": (
            "a", True, (authenticated_oid,),
        ),
        "consentimento_finalidade_evento_select_tenant": (
            "r", True, (authenticated_oid,),
        ),
        "consentimento_finalidade_evento_tenant_context_barrier": (
            "*", False, (0,),
        ),
    }
    assert [tuple(row) for row in triggers] == [
        ("trg_consentimento_finalidade_evento_append_only", 27),
        ("trg_consentimento_finalidade_evento_prepare_insert", 7),
    ]
    assert tuple(table_acl) == (True, False, False, False, False, False)
    allowed_insert_columns = {
        "igreja_id", "pessoa_id", "finalidade", "estado", "versao_termo",
        "fonte", "registrado_por_app_user_id", "chave_idempotencia",
    }
    assert column_acl == {
        (column, privilege): privilege == "INSERT"
        and column in allowed_insert_columns
        for column in (
            "id", "igreja_id", "pessoa_id", "finalidade", "estado",
            "versao_termo", "fonte", "registrado_por_app_user_id",
            "chave_idempotencia", "sequencia", "registrado_em",
        )
        for privilege in ("INSERT", "UPDATE", "REFERENCES")
    }
    assert not any(function_acl.values())
    assert table_privileges == {
        (role, privilege): role == "authenticated" and privilege == "SELECT"
        for role in ("anon", "authenticated", "service_role", "agent_runtime")
        for privilege in (
            "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE",
            "REFERENCES", "TRIGGER", "MAINTAIN",
        )
    }


@pytest.mark.rls_integration
def test_rls_exige_guc_mesmo_com_jwt_e_isola_dois_tenants_e_pool(
    d2b2_engine: Engine,
) -> None:
    _apply_migration(d2b2_engine)

    with d2b2_engine.begin() as connection:
        _set_authenticated_tenant(connection, IGREJA_A)
        _, sequence, _ = _insert_event(
            connection,
            igreja_id=IGREJA_A,
            pessoa_id=PESSOA_A,
            chave="tenant-a:1",
        )
        assert sequence == 1
        visible = connection.exec_driver_sql(
            f"select igreja_id::text from {_TABLE}"
        ).scalars().all()
        assert visible == [IGREJA_A]

    with pytest.raises(DBAPIError):
        with d2b2_engine.begin() as connection:
            _set_authenticated_tenant(connection, IGREJA_A)
            _insert_event(
                connection,
                igreja_id=IGREJA_B,
                pessoa_id=PESSOA_B,
                chave="cross-tenant:denied",
            )

    with d2b2_engine.begin() as connection:
        connection.exec_driver_sql("set local role authenticated")
        connection.exec_driver_sql(
            "select set_config('request.jwt.claim.sub', 'clerk-a', true)"
        )
        assert connection.exec_driver_sql(
            f"select count(*) from {_TABLE}"
        ).scalar_one() == 0

    with pytest.raises(DBAPIError):
        with d2b2_engine.begin() as connection:
            connection.exec_driver_sql("set local role authenticated")
            connection.exec_driver_sql(
                "select set_config('request.jwt.claim.sub', 'clerk-a', true)"
            )
            _insert_event(
                connection,
                igreja_id=IGREJA_A,
                pessoa_id=PESSOA_A,
                chave="jwt-only:denied",
            )

    with pytest.raises(DBAPIError):
        with d2b2_engine.begin() as connection:
            connection.exec_driver_sql("set local role authenticated")
            connection.exec_driver_sql(
                "select set_config('app.tenant_igreja_id', 'not-a-uuid', true)"
            )
            connection.exec_driver_sql(f"select count(*) from {_TABLE}").scalar_one()

    with d2b2_engine.begin() as connection:
        _set_authenticated_tenant(connection, IGREJA_B)
        _, sequence, _ = _insert_event(
            connection,
            igreja_id=IGREJA_B,
            pessoa_id=PESSOA_B,
            chave="tenant-b:1",
        )
        assert sequence == 1
        assert connection.exec_driver_sql(
            f"select array_agg(igreja_id::text) from {_TABLE}"
        ).scalar_one() == [IGREJA_B]

    # Nova transacao em conexao reutilizavel nao herda o GUC transacional.
    with d2b2_engine.begin() as connection:
        connection.exec_driver_sql("set local role authenticated")
        assert connection.exec_driver_sql(
            f"select count(*) from {_TABLE}"
        ).scalar_one() == 0


@pytest.mark.rls_integration
def test_checks_idempotencia_fks_e_timestamp_server_side(
    d2b2_engine: Engine,
) -> None:
    _apply_migration(d2b2_engine)

    with d2b2_engine.begin() as connection:
        _set_authenticated_tenant(connection, IGREJA_A)
        _insert_event(
            connection,
            igreja_id=IGREJA_A,
            pessoa_id=PESSOA_A,
            fonte="painel_autenticado",
            operador=USER_A,
            chave="same-key",
        )

    with pytest.raises(DBAPIError):
        with d2b2_engine.begin() as connection:
            _set_authenticated_tenant(connection, IGREJA_A)
            _insert_event(
                connection,
                igreja_id=IGREJA_A,
                pessoa_id=PESSOA_A,
                chave="same-key",
            )

    invalid_cases = (
        {"finalidade": "desconhecida", "chave": "invalid:purpose"},
        {"estado": "pendente", "chave": "invalid:state"},
        {"fonte": "modelo", "chave": "invalid:source"},
        {"versao_termo": " v1", "chave": "invalid:term"},
        {"chave": "INVALID KEY"},
        {"fonte": "painel_autenticado", "chave": "invalid:panel-without-actor"},
        {"operador": USER_A, "chave": "invalid:whatsapp-with-actor"},
        {"operador": USER_B, "fonte": "painel_autenticado", "chave": "cross:actor"},
    )
    for case in invalid_cases:
        with pytest.raises(DBAPIError):
            with d2b2_engine.begin() as connection:
                _set_authenticated_tenant(connection, IGREJA_A)
                _insert_event(
                    connection,
                    igreja_id=IGREJA_A,
                    pessoa_id=PESSOA_A,
                    **case,
                )

    with d2b2_engine.begin() as connection:
        _set_authenticated_tenant(connection, IGREJA_B)
        _insert_event(
            connection,
            igreja_id=IGREJA_B,
            pessoa_id=PESSOA_B,
            chave="same-key",
        )

    # Um executor privilegiado ainda atravessa o trigger, que valida sequencia e
    # substitui qualquer instante fornecido pelo relogio do servidor.
    with pytest.raises(DBAPIError):
        with d2b2_engine.begin() as connection:
            connection.exec_driver_sql(
                f"insert into {_TABLE} (id, igreja_id, pessoa_id, finalidade, estado, "
                "versao_termo, fonte, chave_idempotencia, sequencia, registrado_em) "
                "values (gen_random_uuid(), %s, %s, 'comunicados', 'concedido', "
                "'v1', 'whatsapp_inbound', 'manual:bad-seq', 9, '2000-01-01')",
                (IGREJA_A, PESSOA_A),
            )

    with d2b2_engine.begin() as connection:
        server_values = connection.exec_driver_sql(
            f"insert into {_TABLE} (igreja_id, pessoa_id, finalidade, estado, "
            "versao_termo, fonte, chave_idempotencia, registrado_em) "
            "values (%s, %s, 'comunicados', 'concedido', 'v1', "
            "'whatsapp_inbound', 'manual:server-values', '2000-01-01') "
            "returning sequencia, registrado_em <> timestamptz '2000-01-01'",
            (IGREJA_A, PESSOA_A),
        ).one()
        assert tuple(server_values) == (1, True)


@pytest.mark.rls_integration
def test_append_only_preserva_cascatas_legitimas(
    d2b2_engine: Engine,
) -> None:
    _apply_migration(d2b2_engine)
    with d2b2_engine.begin() as connection:
        _set_authenticated_tenant(connection, IGREJA_A)
        event_id, _, _ = _insert_event(
            connection,
            igreja_id=IGREJA_A,
            pessoa_id=PESSOA_A,
            fonte="painel_autenticado",
            operador=USER_A,
            chave="append:1",
        )

    for statement in (
        f"update {_TABLE} set estado='retirado' where id='{event_id}'",
        f"delete from {_TABLE} where id='{event_id}'",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            with d2b2_engine.begin() as connection:
                connection.exec_driver_sql(statement)

    with d2b2_engine.begin() as connection:
        connection.exec_driver_sql(
            f"delete from {_SCHEMA}.app_users where id=%s", (USER_A,)
        )
        assert connection.exec_driver_sql(
            f"select registrado_por_app_user_id from {_TABLE} where id=%s",
            (event_id,),
        ).scalar_one() is None
        connection.exec_driver_sql(
            f"delete from {_SCHEMA}.pessoas where id=%s", (PESSOA_A,)
        )
        assert connection.exec_driver_sql(
            f"select count(*) from {_TABLE} where id=%s", (event_id,)
        ).scalar_one() == 0

        _insert_event(
            connection,
            igreja_id=IGREJA_B,
            pessoa_id=PESSOA_B,
            chave="cascade:church",
        )
        connection.exec_driver_sql(
            f"delete from {_SCHEMA}.igrejas where id=%s", (IGREJA_B,)
        )
        assert connection.exec_driver_sql(
            f"select count(*) from {_TABLE} where igreja_id=%s", (IGREJA_B,)
        ).scalar_one() == 0


@pytest.mark.rls_integration
def test_concorrencia_serializa_sequencia_por_stream(
    d2b2_engine: Engine,
) -> None:
    _apply_migration(d2b2_engine)
    workers = 4
    barrier = Barrier(workers)

    def insert_one(position: int) -> int:
        with d2b2_engine.begin() as connection:
            _set_authenticated_tenant(connection, IGREJA_A)
            barrier.wait(timeout=10)
            return _insert_event(
                connection,
                igreja_id=IGREJA_A,
                pessoa_id=PESSOA_A,
                finalidade="tarefas_operacionais",
                chave=f"concurrent:{position}",
            )[1]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        sequences = list(pool.map(insert_one, range(workers)))

    assert sorted(sequences) == [1, 2, 3, 4]


@pytest.mark.rls_integration
def test_orm_e_servico_respeitam_acl_fetched_value_replay_e_transacao_externa(
    d2b2_engine: Engine,
) -> None:
    _apply_migration(d2b2_engine)
    scoped_engine = create_engine(
        d2b2_engine.url,
        connect_args={"options": f"-csearch_path={_SCHEMA},public"},
        future=True,
    )
    session = Session(scoped_engine, expire_on_commit=False)
    try:
        tenant_id = uuid.UUID(IGREJA_A)
        person_id = uuid.UUID(PESSOA_A)
        mark_tenant_scoped(
            session,
            tenant_id,
            actor_sub="synthetic-test",
            actor_role="worker",
            source="d2b2a_pg17_contract",
        )
        replay_key = OpaquePurposeConsentIdempotencyKey.generate()

        event = append_purpose_consent_event(
            session,
            igreja_id=tenant_id,
            pessoa_id=person_id,
            finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo=TrustedTermVersion("v1"),
            fonte=PurposeConsentSource.WHATSAPP_INBOUND,
            chave_idempotencia=replay_key,
        )
        replay = append_purpose_consent_event(
            session,
            igreja_id=tenant_id,
            pessoa_id=person_id,
            finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo=TrustedTermVersion("v1"),
            fonte=PurposeConsentSource.WHATSAPP_INBOUND,
            chave_idempotencia=replay_key,
        )

        assert event.id is not None
        assert event.sequencia == 1
        assert event.registrado_em is not None
        assert event.registrado_em.tzinfo is not None
        assert replay is event
        assert session.in_transaction()

        # Outra conexao nao enxerga a linha: o service fez flush, mas nao commit.
        with d2b2_engine.connect() as observer:
            assert observer.exec_driver_sql(
                f"select count(*) from {_TABLE} where chave_idempotencia=%s",
                (replay_key.value,),
            ).scalar_one() == 0

        session.commit()
        with d2b2_engine.connect() as observer:
            assert observer.exec_driver_sql(
                f"select count(*) from {_TABLE} where chave_idempotencia=%s",
                (replay_key.value,),
            ).scalar_one() == 1
    finally:
        session.close()
        scoped_engine.dispose()


@pytest.mark.rls_integration
def test_servico_serializa_replay_concorrente_e_recupera_savepoint_real(
    d2b2_engine: Engine,
) -> None:
    _apply_migration(d2b2_engine)
    with d2b2_engine.begin() as connection:
        connection.exec_driver_sql(
            f"insert into {_SCHEMA}.pessoas (id, igreja_id, nome) "
            "values (%s, %s, 'Pessoa A2')",
            (PESSOA_A2, IGREJA_A),
        )

    scoped_engine = create_engine(
        d2b2_engine.url,
        connect_args={"options": f"-csearch_path={_SCHEMA},public"},
        future=True,
        pool_size=4,
    )
    tenant_id = uuid.UUID(IGREJA_A)
    person_id = uuid.UUID(PESSOA_A)
    replay_barrier = Barrier(2)
    concurrent_replay_key = OpaquePurposeConsentIdempotencyKey.generate()
    savepoint_collision_key = OpaquePurposeConsentIdempotencyKey.generate()

    def append_same_intent() -> str:
        session = Session(scoped_engine, expire_on_commit=False)
        try:
            mark_tenant_scoped(
                session,
                tenant_id,
                actor_sub="synthetic-concurrent-replay",
                actor_role="worker",
                source="d2b2a_pg17_concurrent_replay",
            )
            replay_barrier.wait(timeout=10)
            event = append_purpose_consent_event(
                session,
                igreja_id=tenant_id,
                pessoa_id=person_id,
                finalidade=PurposeConsentPurpose.CUIDADO_PASTORAL,
                estado=PurposeConsentEventState.RETIRADO,
                versao_termo=TrustedTermVersion("v1"),
                fonte=PurposeConsentSource.WHATSAPP_INBOUND,
                chave_idempotencia=concurrent_replay_key,
            )
            event_id = str(event.id)
            session.commit()
            return event_id
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            replay_ids = list(pool.map(lambda _position: append_same_intent(), range(2)))
        assert len(set(replay_ids)) == 1
        with d2b2_engine.connect() as observer:
            assert observer.exec_driver_sql(
                f"select count(*) from {_TABLE} where chave_idempotencia=%s",
                (concurrent_replay_key.value,),
            ).scalar_one() == 1

        flush_ready = Event()
        resume_flush = Event()

        def append_divergent_loser() -> PurposeConsentIdempotencyConflictError:
            session = Session(scoped_engine, expire_on_commit=False)
            paused = False

            def pause_before_flush(
                _session: Session,
                _flush_context: object,
                _instances: object,
            ) -> None:
                nonlocal paused
                if paused:
                    return
                paused = True
                flush_ready.set()
                if not resume_flush.wait(timeout=10):
                    raise AssertionError("timeout ao sincronizar colisão de SAVEPOINT")

            sa_event.listen(session, "before_flush", pause_before_flush)
            try:
                mark_tenant_scoped(
                    session,
                    tenant_id,
                    actor_sub="synthetic-savepoint-loser",
                    actor_role="worker",
                    source="d2b2a_pg17_savepoint_collision",
                )
                with pytest.raises(PurposeConsentIdempotencyConflictError) as caught:
                    append_purpose_consent_event(
                        session,
                        igreja_id=tenant_id,
                        pessoa_id=uuid.UUID(PESSOA_A2),
                        finalidade=PurposeConsentPurpose.TAREFAS_OPERACIONAIS,
                        estado=PurposeConsentEventState.RETIRADO,
                        versao_termo=TrustedTermVersion("v1"),
                        fonte=PurposeConsentSource.WHATSAPP_INBOUND,
                        chave_idempotencia=savepoint_collision_key,
                    )
                assert isinstance(caught.value.__cause__, IntegrityError)
                session.rollback()
                return caught.value
            finally:
                sa_event.remove(session, "before_flush", pause_before_flush)
                session.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            loser = pool.submit(append_divergent_loser)
            assert flush_ready.wait(timeout=10)
            try:
                with d2b2_engine.begin() as connection:
                    _set_authenticated_tenant(connection, IGREJA_A)
                    _insert_event(
                        connection,
                        igreja_id=IGREJA_A,
                        pessoa_id=PESSOA_A,
                        finalidade="tarefas_operacionais",
                        chave=savepoint_collision_key.value,
                    )
            finally:
                resume_flush.set()
            assert isinstance(
                loser.result(timeout=15),
                PurposeConsentIdempotencyConflictError,
            )

        with d2b2_engine.connect() as observer:
            rows = observer.exec_driver_sql(
                f"select pessoa_id::text from {_TABLE} where chave_idempotencia=%s",
                (savepoint_collision_key.value,),
            ).scalars().all()
            assert rows == [PESSOA_A]
    finally:
        scoped_engine.dispose()


@pytest.mark.rls_integration
def test_conflito_homonimo_reverte_atomicamente(d2b2_engine: Engine) -> None:
    with d2b2_engine.begin() as connection:
        connection.exec_driver_sql(
            f"create table {_TABLE} (id integer primary key)"
        )

    with pytest.raises(PsycopgError, match="catalog conflict"):
        _apply_migration(d2b2_engine)

    with d2b2_engine.begin() as connection:
        columns = connection.exec_driver_sql(
            "select attname from pg_attribute where attrelid=%s::regclass "
            "and attnum > 0 and not attisdropped",
            (_TABLE,),
        ).scalars().all()
        functions = connection.exec_driver_sql(
            "select count(*) from pg_proc where pronamespace=%s::regnamespace "
            "and proname like 'consentimento_finalidade_evento_%%'",
            (_SCHEMA,),
        ).scalar_one()
        policies = connection.exec_driver_sql(
            "select count(*) from pg_policy where polrelid=%s::regclass",
            (_TABLE,),
        ).scalar_one()

    assert columns == ["id"]
    assert functions == 0
    assert policies == 0


@pytest.mark.rls_integration
def test_sobrecarga_homonima_de_funcao_aborta_sem_tabela_parcial(
    d2b2_engine: Engine,
) -> None:
    with d2b2_engine.begin() as connection:
        connection.exec_driver_sql(
            f"create function {_SCHEMA}.consentimento_finalidade_evento_prepare_insert(integer) "
            "returns integer language sql immutable as 'select $1'"
        )

    with pytest.raises(PsycopgError, match="homonymous function overload"):
        _apply_migration(d2b2_engine)

    with d2b2_engine.begin() as connection:
        assert connection.exec_driver_sql(
            "select to_regclass(%s)", (_TABLE,)
        ).scalar_one() is None
        assert connection.exec_driver_sql(
            "select count(*) from pg_proc where pronamespace=%s::regnamespace "
            "and proname='consentimento_finalidade_evento_prepare_insert'",
            (_SCHEMA,),
        ).scalar_one() == 1
