"""Contrato D2A do papel e contexto PostgreSQL privado do agente."""

from __future__ import annotations

import pathlib
import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from psycopg2 import Error as PsycopgError
from psycopg2 import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.db import agent_runtime_session
from tests.conftest_rls import rls_database_url  # noqa: F401


_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260827_230003_d2a_agent_runtime_private_context.sql"
)
_SYNTHETIC_RUNTIME_PASSWORD = "d2a-only-disposable-runtime-password"
_SYNTHETIC_EXECUTOR_ROLE = "d2a_migration_executor"
_SYNTHETIC_EXECUTOR_PASSWORD = "d2a-only-disposable-executor-password"

_SUPABASE_ROLES_SQL = """
do $roles$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin noinherit nobypassrls nocreaterole;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin noinherit nobypassrls nocreaterole;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin noinherit bypassrls nocreaterole;
  end if;
end
$roles$;
"""

_CLEANUP_SQL = """
drop schema if exists agent_private cascade;

do $cleanup$
declare
  membership record;
begin
  if exists (select 1 from pg_roles where rolname = 'agent_runtime') then
    for membership in
      select granted.rolname as granted_role, member.rolname as member_role
        from pg_auth_members edge
        join pg_roles granted on granted.oid = edge.roleid
        join pg_roles member on member.oid = edge.member
       where granted.rolname = 'agent_runtime'
          or member.rolname = 'agent_runtime'
    loop
      execute format(
        'revoke %I from %I',
        membership.granted_role,
        membership.member_role
      );
    end loop;
    drop role agent_runtime;
  end if;
end
$cleanup$;
"""


def _migration_sql() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def _apply_migration(engine: Engine) -> None:
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute(_migration_sql())
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            cursor.close()
    finally:
        raw.close()


def _cleanup(engine: Engine) -> None:
    # O bloco contém placeholders ``format('%I', ...)`` do próprio PostgreSQL.
    # Enviar pela camada SQLAlchemy faria o psycopg2 tentar interpretá-los como
    # parâmetros do cliente. O cursor cru preserva o script exatamente como foi
    # escrito, do mesmo modo que o executor real de migrations.
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute(_CLEANUP_SQL)
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            cursor.close()
    finally:
        raw.close()


def _provision_synthetic_runtime_login(owner_engine: Engine) -> Engine:
    """Habilita login somente no PG descartável e devolve pool dedicado.

    A migration deixa a role NOLOGIN. O teste precisa simular o gate futuro
    para provar a identidade real da conexão, sem depender de SET ROLE do
    executor administrativo, que no PostgreSQL 17 não recebe SET OPTION.
    """

    with owner_engine.begin() as connection:
        connection.exec_driver_sql(
            "alter role agent_runtime login password "
            f"'{_SYNTHETIC_RUNTIME_PASSWORD}'"
        )
    runtime_url = owner_engine.url.set(
        username="agent_runtime",
        password=_SYNTHETIC_RUNTIME_PASSWORD,
    )
    return create_engine(
        runtime_url,
        pool_size=1,
        max_overflow=0,
        future=True,
    )


def _provision_non_superuser_executor(owner_engine: Engine) -> Engine:
    raw = owner_engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute(
                sql.SQL(
                    "create role {} login password %s nosuperuser createrole "
                    "nocreatedb noinherit noreplication nobypassrls"
                ).format(sql.Identifier(_SYNTHETIC_EXECUTOR_ROLE)),
                (_SYNTHETIC_EXECUTOR_PASSWORD,),
            )
            cursor.execute(
                sql.SQL("grant create on database {} to {}").format(
                    sql.Identifier(owner_engine.url.database),
                    sql.Identifier(_SYNTHETIC_EXECUTOR_ROLE),
                )
            )
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            cursor.close()
    finally:
        raw.close()

    return create_engine(
        owner_engine.url.set(
            username=_SYNTHETIC_EXECUTOR_ROLE,
            password=_SYNTHETIC_EXECUTOR_PASSWORD,
        ),
        future=True,
    )


def _drop_non_superuser_executor(owner_engine: Engine) -> None:
    raw = owner_engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute(
                sql.SQL("revoke create on database {} from {}").format(
                    sql.Identifier(owner_engine.url.database),
                    sql.Identifier(_SYNTHETIC_EXECUTOR_ROLE),
                )
            )
            cursor.execute(
                sql.SQL("drop role if exists {}").format(
                    sql.Identifier(_SYNTHETIC_EXECUTOR_ROLE)
                )
            )
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            cursor.close()
    finally:
        raw.close()


@pytest.fixture
def d2a_engine(rls_database_url: str) -> Iterator[Engine]:
    engine = create_engine(rls_database_url, future=True)
    try:
        _cleanup(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(_SUPABASE_ROLES_SQL)
        yield engine
    finally:
        _cleanup(engine)
        engine.dispose()


def test_migration_estatica_e_estreita() -> None:
    sql = _migration_sql().lower()

    assert sql.lstrip().startswith("-- pastorai d2a")
    assert "begin;" in sql
    assert sql.rstrip().endswith("commit;")
    assert "create role agent_runtime" in sql
    assert "nologin" in sql
    assert "alter role agent_runtime nologin password null" in sql
    assert "nobypassrls" in sql
    assert "nosuperuser" in sql
    assert "create schema agent_private" in sql
    assert "security invoker" in sql
    assert "set search_path = pg_catalog" in sql
    assert "set_config('app.tenant_igreja_id'" not in sql
    assert "current_setting('app.tenant_igreja_id'" in sql
    assert "create table" not in sql
    assert "checkpointer" in sql  # apenas a declaracao explicita de ausencia
    assert "public.current_igreja_id" not in sql
    assert "pg_authid" not in sql
    assert "password '" not in sql
    assert "password \"" not in sql


@pytest.mark.rls_integration
def test_aplica_duas_vezes_e_prova_catalogo_acl_e_ausencia_de_tabelas(
    d2a_engine: Engine,
) -> None:
    _apply_migration(d2a_engine)
    _apply_migration(d2a_engine)

    with d2a_engine.begin() as connection:
        role = connection.exec_driver_sql(
            "select rolcanlogin, rolinherit, rolsuper, rolbypassrls, "
            "rolcreatedb, rolcreaterole, rolreplication, rolconfig "
            "from pg_roles where rolname = 'agent_runtime'"
        ).one()
        memberships = connection.exec_driver_sql(
            "select granted.rolname, member.rolname, edge.admin_option, "
            "edge.inherit_option, edge.set_option "
            "from pg_auth_members edge "
            "join pg_roles granted on granted.oid = edge.roleid "
            "join pg_roles member on member.oid = edge.member "
            "where edge.roleid = 'agent_runtime'::regrole "
            "or edge.member = 'agent_runtime'::regrole"
        ).all()
        schema_privileges = {
            role_name: connection.exec_driver_sql(
                "select has_schema_privilege(%s, 'agent_private', 'USAGE'), "
                "has_schema_privilege(%s, 'agent_private', 'CREATE')",
                (role_name, role_name),
            ).one()
            for role_name in (
                "agent_runtime",
                "anon",
                "authenticated",
                "service_role",
            )
        }
        function_privileges = {
            role_name: connection.exec_driver_sql(
                "select has_function_privilege(%s, "
                "'agent_private.current_tenant_id()', 'EXECUTE')",
                (role_name,),
            ).scalar_one()
            for role_name in (
                "agent_runtime",
                "anon",
                "authenticated",
                "service_role",
            )
        }
        function_contract = connection.exec_driver_sql(
            "select p.prosecdef, p.provolatile, l.lanname, p.proconfig, "
            "p.prorettype = 'uuid'::regtype "
            "from pg_proc p join pg_language l on l.oid = p.prolang "
            "where p.oid = 'agent_private.current_tenant_id()'::regprocedure"
        ).one()
        public_acl = connection.exec_driver_sql(
            "select "
            "exists(select 1 from aclexplode(n.nspacl) a where a.grantee = 0), "
            "exists(select 1 from aclexplode(p.proacl) a where a.grantee = 0) "
            "from pg_namespace n cross join pg_proc p "
            "where n.nspname = 'agent_private' "
            "and p.oid = 'agent_private.current_tenant_id()'::regprocedure"
        ).one()
        private_relations = connection.exec_driver_sql(
            "select count(*) from pg_class "
            "where relnamespace = 'agent_private'::regnamespace"
        ).scalar_one()

    assert tuple(role[:7]) == (False, False, False, False, False, False, False)
    assert set(role.rolconfig) == {
        "row_security=on",
        "search_path=pg_catalog, agent_private",
    }
    # PostgreSQL 17 concede automaticamente ao criador não-superuser ADMIN
    # OPTION sobre a nova role, sem INHERIT nem SET. Um executor superuser pode
    # não receber essa aresta. Nenhum dos casos dá privilégios ao runtime; toda
    # associação diferente da aresta segura opcional é rejeitada pela migration.
    assert [tuple(row) for row in memberships] in (
        [],
        [("agent_runtime", "postgres", True, False, False)],
    )
    assert tuple(schema_privileges["agent_runtime"]) == (True, False)
    for role_name in ("anon", "authenticated", "service_role"):
        assert tuple(schema_privileges[role_name]) == (False, False)
        assert function_privileges[role_name] is False
    assert function_privileges["agent_runtime"] is True
    assert tuple(function_contract) == (
        False,
        "s",
        "sql",
        ["search_path=pg_catalog"],
        True,
    )
    assert tuple(public_acl) == (False, False)
    assert private_relations == 0


@pytest.mark.rls_integration
def test_executor_createrole_nonsuperuser_aplica_e_reaplica_com_aresta_segura(
    d2a_engine: Engine,
) -> None:
    executor_engine = _provision_non_superuser_executor(d2a_engine)
    try:
        _apply_migration(executor_engine)
        _apply_migration(executor_engine)

        with d2a_engine.begin() as connection:
            executor = connection.exec_driver_sql(
                "select rolsuper, rolcreaterole, rolinherit, rolbypassrls "
                "from pg_roles where rolname = %s",
                (_SYNTHETIC_EXECUTOR_ROLE,),
            ).one()
            memberships = connection.exec_driver_sql(
                "select granted.rolname, member.rolname, edge.admin_option, "
                "edge.inherit_option, edge.set_option "
                "from pg_auth_members edge "
                "join pg_roles granted on granted.oid = edge.roleid "
                "join pg_roles member on member.oid = edge.member "
                "where edge.roleid = 'agent_runtime'::regrole "
                "or edge.member = 'agent_runtime'::regrole"
            ).all()

        assert tuple(executor) == (False, True, False, False)
        assert [tuple(row) for row in memberships] == [
            (
                "agent_runtime",
                _SYNTHETIC_EXECUTOR_ROLE,
                True,
                False,
                False,
            )
        ]
    finally:
        _cleanup(executor_engine)
        executor_engine.dispose()
        _drop_non_superuser_executor(d2a_engine)


@pytest.mark.rls_integration
def test_helper_e_transacional_fail_closed_em_conexao_reutilizada(
    d2a_engine: Engine,
) -> None:
    _apply_migration(d2a_engine)
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    runtime_engine = _provision_synthetic_runtime_login(d2a_engine)
    raw = runtime_engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            for expected in (tenant_a, tenant_b):
                cursor.execute("begin")
                cursor.execute(
                    "select set_config('app.tenant_igreja_id', %s, true)",
                    (expected,),
                )
                cursor.execute(
                    "select current_user, "
                    "agent_private.current_tenant_id()::text"
                )
                assert cursor.fetchone() == ("agent_runtime", expected)
                raw.commit()

            cursor.execute("begin")
            cursor.execute("select agent_private.current_tenant_id()")
            assert cursor.fetchone() == (None,)
            raw.commit()

            cursor.execute("begin")
            cursor.execute(
                "select set_config("
                "'app.tenant_igreja_id', 'tenant-invalido', true)"
            )
            with pytest.raises(
                PsycopgError,
                match="invalid input syntax for type uuid",
            ):
                cursor.execute("select agent_private.current_tenant_id()")
            raw.rollback()

            cursor.execute("begin")
            cursor.execute("select agent_private.current_tenant_id()")
            assert cursor.fetchone() == (None,)
            raw.commit()
        finally:
            cursor.close()
    finally:
        raw.close()
        runtime_engine.dispose()


@pytest.mark.rls_integration
def test_role_nao_pode_setar_papel_privilegiado(d2a_engine: Engine) -> None:
    _apply_migration(d2a_engine)
    runtime_engine = _provision_synthetic_runtime_login(d2a_engine)
    raw = runtime_engine.raw_connection()
    cursor = raw.cursor()
    try:
        cursor.execute("select session_user, current_user")
        assert cursor.fetchone() == ("agent_runtime", "agent_runtime")
        with pytest.raises(PsycopgError, match="permission denied to set role"):
            cursor.execute("set role service_role")
    finally:
        raw.rollback()
        cursor.close()
        raw.close()
        runtime_engine.dispose()


@pytest.mark.rls_integration
def test_factory_real_reutiliza_pool_sem_vazar_tenant(
    d2a_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _apply_migration(d2a_engine)
    provisioned_engine = _provision_synthetic_runtime_login(d2a_engine)
    runtime_url = provisioned_engine.url.render_as_string(hide_password=False)
    provisioned_engine.dispose()

    monkeypatch.setattr(
        agent_runtime_session,
        "get_settings",
        lambda: SimpleNamespace(
            agent_runtime_database_url=runtime_url,
            database_url=d2a_engine.url.render_as_string(hide_password=False),
        ),
    )
    monkeypatch.setattr(agent_runtime_session, "_agent_runtime_engine", None)
    monkeypatch.setattr(agent_runtime_session, "_AgentRuntimeSessionFactory", None)

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    factory = agent_runtime_session.get_agent_runtime_session_factory()
    pool_engine = agent_runtime_session._agent_runtime_engine
    assert pool_engine is not None
    try:
        first = factory()
        try:
            agent_runtime_session.scope_agent_runtime_session(first, tenant_a)
            first_pid = first.connection().exec_driver_sql(
                "select pg_backend_pid()"
            ).scalar_one()
            assert first.connection().exec_driver_sql(
                "select agent_private.current_tenant_id()::text"
            ).scalar_one() == tenant_a
            first.commit()
        finally:
            first.close()

        second = factory()
        try:
            second_pid = second.connection().exec_driver_sql(
                "select pg_backend_pid()"
            ).scalar_one()
            leaked = second.connection().exec_driver_sql(
                "select nullif(current_setting("
                "'app.tenant_igreja_id', true), '')"
            ).scalar_one_or_none()
            assert second_pid == first_pid
            assert leaked is None
            second.rollback()

            agent_runtime_session.scope_agent_runtime_session(second, tenant_b)
            assert second.connection().exec_driver_sql(
                "select agent_private.current_tenant_id()::text"
            ).scalar_one() == tenant_b
            second.commit()
        finally:
            second.close()

        poisoned = pool_engine.raw_connection()
        poisoned_cursor = poisoned.cursor()
        try:
            poisoned_cursor.execute(
                "select set_config('app.tenant_igreja_id', %s, false)",
                (tenant_a,),
            )
            poisoned_cursor.execute("select pg_backend_pid()")
            poisoned_pid = poisoned_cursor.fetchone()[0]
            poisoned.commit()
        finally:
            poisoned_cursor.close()
            poisoned.close()

        recovered = factory()
        try:
            agent_runtime_session.scope_agent_runtime_session(recovered, tenant_b)
            recovered_pid = recovered.connection().exec_driver_sql(
                "select pg_backend_pid()"
            ).scalar_one()
            assert recovered_pid != poisoned_pid
            assert recovered.connection().exec_driver_sql(
                "select agent_private.current_tenant_id()::text"
            ).scalar_one() == tenant_b
            recovered.commit()
        finally:
            recovered.close()
    finally:
        engine = agent_runtime_session._agent_runtime_engine
        if engine is not None:
            engine.dispose()
        agent_runtime_session._agent_runtime_engine = None
        agent_runtime_session._AgentRuntimeSessionFactory = None


@pytest.mark.rls_integration
def test_role_homonima_insegura_aborta_sem_criar_schema(
    d2a_engine: Engine,
) -> None:
    with d2a_engine.begin() as connection:
        connection.exec_driver_sql(
            "create role agent_runtime nologin inherit nobypassrls "
            "nocreatedb nocreaterole noreplication"
        )

    with pytest.raises(PsycopgError, match="role agent_runtime has unsafe attributes"):
        _apply_migration(d2a_engine)

    with d2a_engine.begin() as connection:
        assert connection.exec_driver_sql(
            "select rolinherit from pg_roles where rolname = 'agent_runtime'"
        ).scalar_one() is True
        assert connection.exec_driver_sql(
            "select to_regnamespace('agent_private')"
        ).scalar_one_or_none() is None


@pytest.mark.rls_integration
def test_reaplicacao_depois_de_provisioning_aborta_sem_revogar_login(
    d2a_engine: Engine,
) -> None:
    _apply_migration(d2a_engine)
    runtime_engine = _provision_synthetic_runtime_login(d2a_engine)
    try:
        with pytest.raises(PsycopgError, match="already provisioned"):
            _apply_migration(d2a_engine)

        with runtime_engine.connect() as runtime_connection:
            assert runtime_connection.exec_driver_sql(
                "select current_user"
            ).scalar_one() == "agent_runtime"

        with d2a_engine.begin() as connection:
            assert connection.exec_driver_sql(
                "select rolcanlogin from pg_roles "
                "where rolname = 'agent_runtime'"
            ).scalar_one() is True
    finally:
        runtime_engine.dispose()


@pytest.mark.rls_integration
def test_membership_inesperada_falha_fechado(d2a_engine: Engine) -> None:
    _apply_migration(d2a_engine)
    with d2a_engine.begin() as connection:
        connection.exec_driver_sql("grant service_role to agent_runtime")

    with pytest.raises(PsycopgError, match="role agent_runtime has unsafe memberships"):
        _apply_migration(d2a_engine)

    with d2a_engine.begin() as connection:
        assert connection.exec_driver_sql(
            "select count(*) from pg_auth_members "
            "where roleid = 'service_role'::regrole "
            "and member = 'agent_runtime'::regrole"
        ).scalar_one() == 1


@pytest.mark.rls_integration
def test_acl_inesperada_nao_e_auto_corrigida(d2a_engine: Engine) -> None:
    _apply_migration(d2a_engine)
    with d2a_engine.begin() as connection:
        connection.exec_driver_sql(
            "grant usage on schema agent_private to authenticated"
        )

    with pytest.raises(PsycopgError, match="schema agent_private has unsafe"):
        _apply_migration(d2a_engine)

    with d2a_engine.begin() as connection:
        assert connection.exec_driver_sql(
            "select has_schema_privilege("
            "'authenticated', 'agent_private', 'USAGE')"
        ).scalar_one() is True


@pytest.mark.rls_integration
def test_funcao_homonima_insegura_nao_e_sobrescrita(d2a_engine: Engine) -> None:
    _apply_migration(d2a_engine)
    with d2a_engine.begin() as connection:
        connection.exec_driver_sql(
            "create or replace function agent_private.current_tenant_id() "
            "returns uuid language sql stable security definer "
            "set search_path = pg_catalog as 'select null::uuid'"
        )

    with pytest.raises(PsycopgError, match="function agent_private.current_tenant_id"):
        _apply_migration(d2a_engine)

    with d2a_engine.begin() as connection:
        assert connection.exec_driver_sql(
            "select prosecdef from pg_proc "
            "where oid = 'agent_private.current_tenant_id()'::regprocedure"
        ).scalar_one() is True
