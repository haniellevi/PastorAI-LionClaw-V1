"""Guardas estruturais e prova PostgreSQL da migration RLS da Missão 06."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from psycopg2 import Error as PsycopgError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError

from tests.conftest_rls import rls_database_url  # noqa: F401


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
POLICIES = MIGRATIONS / "20260810_031050_explicit_deny_policies_for_closed_tables.sql"
POLICY_NAME = "service_role_bypass_only"
POLICY_TABLES = (
    "password_reset_tokens",
    "platform_admins",
    "platform_audit_log",
    "platform_orchestrator",
)
TEST_ROLES = ("anon", "authenticated", "service_role")
CORE_TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)
COLUMN_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "REFERENCES",
)
_M06_DATABASE = "m06_hardening_disposable"
_AUXILIARY_ROLE_PREFIX = "m06_"


def _sql(path: Path) -> str:
    executable_lines = (
        line.split("--", 1)[0]
        for line in path.read_text(encoding="utf-8").lower().splitlines()
    )
    return " ".join("\n".join(executable_lines).split())


def test_closed_tables_migration_is_structurally_fail_closed() -> None:
    sql = _sql(POLICIES)

    for table in POLICY_TABLES:
        assert f"'{table}'" in sql

    assert "required table public.%i is missing" in sql
    assert "lock table public.%i in access exclusive mode" in sql
    assert "unexpected policy state on public.%i" in sql
    assert "alter table public.%i enable row level security" in sql
    assert "create policy service_role_bypass_only" in sql
    assert "as restrictive for all to public" in sql
    assert "using (false) with check (false)" in sql
    assert "p.polcmd = '*'" in sql
    assert "p.polpermissive is false" in sql
    assert "p.polroles = array[0::oid]" in sql
    assert "pg_get_expr(p.polqual, p.polrelid) = 'false'" in sql
    assert "pg_get_expr(p.polwithcheck, p.polrelid) = 'false'" in sql
    assert "set transaction isolation level serializable" in sql
    assert "revoke all privileges on table public.%i from public, anon, authenticated" in sql
    assert "revoke select (%i), insert (%i), update (%i), references (%i)" in sql
    assert "has_table_privilege(target_role, target_oid, target_privilege)" in sql
    assert "has_column_privilege(" in sql
    assert "with recursive set_reachable" in sql
    assert "membership.set_option" in sql
    assert "rolbypassrls" in sql
    assert "c.relowner = reachable_role.oid" in sql
    assert "service_role_before" in sql
    assert "from pg_policy" in sql
    assert "policy_count <> 0" in sql
    assert "policy_count <> 1 or exact_policy_count <> 1" in sql
    assert sql.index("lock table") < sql.index("enable row level security")
    assert sql.index("unexpected policy state") < sql.index(
        "enable row level security"
    )
    assert sql.count("create policy") == 1

    # Grants e RLS continuam independentes: a migration só fecha anon/authenticated.
    assert "grant " not in sql
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


def _drop_auxiliary_roles(connection) -> None:
    """Remove somente roles de testes criadas nesta base descartável."""
    raw_connection = connection.connection.driver_connection
    with raw_connection.cursor() as cursor:
        cursor.execute(
            """
        do $cleanup$
        declare
          role_record record;
        begin
          for role_record in
            select rolname
            from pg_roles
            where rolname like 'm06\\_%' escape '\\'
          loop
            execute format('drop owned by %I', role_record.rolname);
            execute format('drop role %I', role_record.rolname);
          end loop;
        end
        $cleanup$;
        """
        )


@pytest.fixture(scope="module")
def m06_engine(rls_database_url: str) -> Iterator[Engine]:  # noqa: F811
    """Banco dedicado; o guard de ``rls_database_url`` veta DEV/PROD."""
    base = make_url(rls_database_url)
    admin_url = base.set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin.connect() as conn:
            _drop_auxiliary_roles(conn)
    finally:
        admin.dispose()
    _drop_and_create_database(admin_url, _M06_DATABASE)
    engine = create_engine(base.set(database=_M06_DATABASE), future=True)

    roles = """
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
    """
    with engine.begin() as conn:
        conn.exec_driver_sql(roles)

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
                _drop_auxiliary_roles(conn)
        finally:
            admin.dispose()


def _reset_tables(engine: Engine) -> None:
    drop_sql = "\n".join(
        f"drop table if exists public.{table} cascade;" for table in POLICY_TABLES
    )
    create_sql = "\n".join(
        f"create table public.{table} (id integer primary key, payload text);"
        for table in POLICY_TABLES
    )
    grants_and_seed = "\n".join(
        f"grant all privileges on table public.{table} "
        "to anon, authenticated, service_role;\n"
        f"insert into public.{table} (id, payload) values (1, 'seed');"
        for table in POLICY_TABLES
    )
    with engine.begin() as conn:
        conn.exec_driver_sql("drop schema if exists m06_grant_probe cascade")
        conn.exec_driver_sql(drop_sql)
        _drop_auxiliary_roles(conn)
        conn.exec_driver_sql(create_sql)
        conn.exec_driver_sql("grant usage on schema public to anon, authenticated, service_role")
        conn.exec_driver_sql("create schema m06_grant_probe")
        conn.exec_driver_sql(
            "grant usage, create on schema m06_grant_probe "
            "to anon, authenticated, service_role"
        )
        conn.exec_driver_sql(
            """
            create function m06_grant_probe.noop_trigger()
            returns trigger
            language plpgsql
            as $$
            begin
              return new;
            end
            $$
            """
        )
        conn.exec_driver_sql(
            "grant execute on function m06_grant_probe.noop_trigger() "
            "to anon, authenticated, service_role"
        )
        conn.exec_driver_sql(grants_and_seed)


@pytest.fixture
def m06_tables(m06_engine: Engine) -> Engine:
    """Quatro tabelas limpas antes de cada cenário adversarial."""
    _reset_tables(m06_engine)
    return m06_engine


def _applicable_table_privileges(connection) -> tuple[str, ...]:
    version = int(connection.exec_driver_sql("show server_version_num").scalar_one())
    if version >= 170000:
        return (*CORE_TABLE_PRIVILEGES, "MAINTAIN")
    return CORE_TABLE_PRIVILEGES


def _grant_matrix(engine: Engine) -> dict[tuple[str, str, str], bool]:
    with engine.connect() as conn:
        privileges = _applicable_table_privileges(conn)
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
            for privilege in privileges
        }


def _table_columns(connection, table: str) -> tuple[str, ...]:
    return tuple(
        connection.execute(
            text(
                """
                select a.attname
                from pg_attribute a
                join pg_class c on c.oid = a.attrelid
                join pg_namespace n on n.oid = c.relnamespace
                where n.nspname = 'public'
                  and c.relname = :table
                  and a.attnum > 0
                  and not a.attisdropped
                order by a.attnum
                """
            ),
            {"table": table},
        ).scalars()
    )


def _column_grant_matrix(engine: Engine) -> dict[tuple[str, str, str, str], bool]:
    with engine.connect() as conn:
        return {
            (table, column, role, privilege): bool(
                conn.execute(
                    text(
                        "select has_column_privilege("
                        ":role, :table, :column, :privilege)"
                    ),
                    {
                        "role": role,
                        "table": f"public.{table}",
                        "column": column,
                        "privilege": privilege,
                    },
                ).scalar_one()
            )
            for table in POLICY_TABLES
            for column in _table_columns(conn, table)
            for role in TEST_ROLES
            for privilege in COLUMN_PRIVILEGES
        }


def _assert_table_privilege_denied(
    engine: Engine,
    role: str,
    table: str,
    statement: str,
) -> None:
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.exec_driver_sql(f"set local role {role}")
            with pytest.raises(DBAPIError) as error:
                conn.exec_driver_sql(statement)
            assert f"permission denied for table {table}" in str(error.value).lower()
        finally:
            transaction.rollback()


def _assert_table_privilege_allowed(
    engine: Engine,
    role: str,
    statement: str,
) -> None:
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.exec_driver_sql(f"set local role {role}")
            conn.exec_driver_sql(statement)
        finally:
            transaction.rollback()


def _reference_probe_statement(table: str, suffix: str) -> str:
    return (
        f"create table m06_grant_probe.reference_probe_{suffix} "
        f"(target_id integer references public.{table}(id))"
    )


def _trigger_probe_statement(table: str, suffix: str) -> str:
    return (
        f"create trigger m06_trigger_probe_{suffix} before insert "
        f"on public.{table} for each row execute function "
        "m06_grant_probe.noop_trigger()"
    )


def _apply_migration(engine: Engine, migration: str) -> None:
    """Usa o cursor DBAPI para não tratar ``%I`` do PL/pgSQL como parâmetro."""
    connection = engine.raw_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(migration)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _create_policy(engine: Engine, table: str, definition: str) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"create policy {POLICY_NAME} on public.{table} {definition}"
        )


def _create_expected_policy(engine: Engine, table: str) -> None:
    _create_policy(
        engine,
        table,
        "as restrictive for all to public using (false) with check (false)",
    )


def _security_snapshot(engine: Engine) -> dict[str, dict[str, object]]:
    snapshot: dict[str, dict[str, object]] = {}
    with engine.connect() as conn:
        for table in POLICY_TABLES:
            relation = conn.execute(
                text(
                    """
                    select c.oid, c.relrowsecurity
                         , coalesce(c.relacl::text, '') as table_acl
                    from pg_class c
                    join pg_namespace n on n.oid = c.relnamespace
                    where n.nspname = 'public' and c.relname = :table
                    """
                ),
                {"table": table},
            ).mappings().one_or_none()
            if relation is None:
                snapshot[table] = {
                    "exists": False,
                    "rls": None,
                    "policies": (),
                    "grants": (),
                    "table_acl": None,
                    "column_acls": (),
                }
                continue

            policies = conn.execute(
                text(
                    """
                    select p.polname,
                           p.polcmd,
                           p.polpermissive,
                           p.polroles::text as polroles,
                           pg_get_expr(p.polqual, p.polrelid) as using_expr,
                           pg_get_expr(p.polwithcheck, p.polrelid) as check_expr
                    from pg_policy p
                    where p.polrelid = :oid
                    order by p.polname
                    """
                ),
                {"oid": relation["oid"]},
            ).mappings().all()
            column_acls = conn.execute(
                text(
                    """
                    select a.attname, coalesce(a.attacl::text, '') as attacl
                    from pg_attribute a
                    where a.attrelid = :oid
                      and a.attnum > 0
                      and not a.attisdropped
                    order by a.attnum
                    """
                ),
                {"oid": relation["oid"]},
            ).all()
            snapshot[table] = {
                "exists": True,
                "rls": relation["relrowsecurity"],
                "table_acl": relation["table_acl"],
                "column_acls": tuple(column_acls),
                "policies": tuple(
                    (
                        row["polname"],
                        row["polcmd"],
                        row["polpermissive"],
                        row["polroles"],
                        row["using_expr"],
                        row["check_expr"],
                    )
                    for row in policies
                ),
                "grants": tuple(
                    (
                        role,
                        privilege,
                        bool(
                            conn.execute(
                                text(
                                    "select has_table_privilege("
                                    ":role, :table, :privilege)"
                                ),
                                {
                                    "role": role,
                                    "table": f"public.{table}",
                                    "privilege": privilege,
                                },
                            ).scalar_one()
                        ),
                    )
                    for role in TEST_ROLES
                    for privilege in _applicable_table_privileges(conn)
                ),
            }
    return snapshot


def _assert_migration_rejected_without_changes(
    engine: Engine,
    migration: str,
    message: str,
) -> None:
    before = _security_snapshot(engine)
    with pytest.raises(PsycopgError, match=message):
        _apply_migration(engine, migration)
    assert _security_snapshot(engine) == before


def _assert_exact_closed_policy(engine: Engine, table: str) -> None:
    state = _security_snapshot(engine)[table]
    assert state["exists"] is True
    assert state["rls"] is True
    assert state["policies"] == (
        (POLICY_NAME, "*", False, "{0}", "false", "false"),
    )


def _assert_closed_grants(engine: Engine) -> None:
    matrix = _grant_matrix(engine)
    for table in POLICY_TABLES:
        for role in TEST_ROLES:
            for privilege in {
                key[2] for key in matrix if key[0] == table and key[1] == role
            }:
                assert matrix[(table, role, privilege)] is (role == "service_role")

    column_matrix = _column_grant_matrix(engine)
    for table in POLICY_TABLES:
        for column in {key[1] for key in column_matrix if key[0] == table}:
            for role in TEST_ROLES:
                for privilege in COLUMN_PRIVILEGES:
                    assert column_matrix[(table, column, role, privilege)] is (
                        role == "service_role"
                    )


def _create_auxiliary_role(engine: Engine, role: str, attributes: str = "nologin") -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(f"create role {role} {attributes}")


def _grant_membership(
    engine: Engine,
    granted_role: str,
    member_role: str,
    *,
    inherit: bool,
    set_role: bool,
) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"grant {granted_role} to {member_role} "
            f"with inherit {'true' if inherit else 'false'}, "
            f"set {'true' if set_role else 'false'}"
        )


def _assert_can_set_role(engine: Engine, role: str, target_role: str) -> None:
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            # SET ROLE decide a permissão pelo session_user. Como a conexão de
            # teste é superuser, usar somente SET ROLE daria um falso positivo.
            conn.exec_driver_sql(f"set local session authorization {role}")
            conn.exec_driver_sql(f"set local role {target_role}")
            assert conn.exec_driver_sql("select session_user").scalar_one() == role
            assert conn.exec_driver_sql("select current_user").scalar_one() == target_role
        finally:
            transaction.rollback()


def _assert_cannot_set_role(engine: Engine, role: str, target_role: str) -> None:
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.exec_driver_sql(f"set local session authorization {role}")
            with pytest.raises(DBAPIError, match="permission denied to set role"):
                conn.exec_driver_sql(f"set local role {target_role}")
        finally:
            transaction.rollback()


@pytest.mark.rls_integration
def test_valid_first_apply_and_reapply_are_closed_and_idempotent(
    m06_tables: Engine,
) -> None:
    """Aplica/reaplica SQL real e prova grants, RLS e bypass do backend."""
    migration = POLICIES.read_text(encoding="utf-8")
    grants_before = _grant_matrix(m06_tables)
    assert all(grants_before.values())

    _apply_migration(m06_tables, migration)
    first_state = _security_snapshot(m06_tables)
    _apply_migration(m06_tables, migration)

    assert _security_snapshot(m06_tables) == first_state
    _assert_closed_grants(m06_tables)

    with m06_tables.connect() as conn:
        role_bypass = dict(
            conn.execute(
                text(
                    "select rolname, rolbypassrls from pg_roles "
                    "where rolname = any(:roles)"
                ),
                {"roles": list(TEST_ROLES)},
            ).all()
        )

    assert role_bypass == {
        "anon": False,
        "authenticated": False,
        "service_role": True,
    }

    for table in POLICY_TABLES:
        _assert_exact_closed_policy(m06_tables, table)
        for role in ("anon", "authenticated"):
            for statement in (
                f"select count(*) from public.{table}",
                f"insert into public.{table} (id, payload) values (2, 'blocked')",
                f"update public.{table} set payload = 'blocked' where id = 1",
                f"delete from public.{table} where id = 1",
                f"truncate table public.{table}",
                _reference_probe_statement(table, f"after_{role}"),
            ):
                _assert_table_privilege_denied(m06_tables, role, table, statement)

        with m06_tables.connect() as conn:
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


@pytest.mark.rls_integration
def test_references_and_trigger_operations_are_effectively_revoked(
    m06_tables: Engine,
) -> None:
    """A ACL de tabela permitia os dois DDLs antes; após M06 ambos falham."""
    migration = POLICIES.read_text(encoding="utf-8")
    table = "password_reset_tokens"

    _assert_table_privilege_allowed(
        m06_tables,
        "anon",
        _reference_probe_statement(table, "before"),
    )
    _assert_table_privilege_allowed(
        m06_tables,
        "anon",
        _trigger_probe_statement(table, "before"),
    )

    _apply_migration(m06_tables, migration)

    _assert_table_privilege_denied(
        m06_tables,
        "anon",
        table,
        _reference_probe_statement(table, "after"),
    )
    _assert_table_privilege_denied(
        m06_tables,
        "anon",
        table,
        _trigger_probe_statement(table, "after"),
    )


@pytest.mark.rls_integration
@pytest.mark.parametrize(
    "grant_sql",
    (
        "grant select (id) on table public.password_reset_tokens to public",
        "grant references (id) on table public.password_reset_tokens to public",
        "grant select (id), insert (payload), update (payload), references (id) "
        "on table public.password_reset_tokens to anon",
        "grant select (id), insert (payload), update (payload), references (id) "
        "on table public.password_reset_tokens to authenticated",
    ),
    ids=("public-select", "public-references", "anon-columns", "authenticated-columns"),
)
def test_column_grants_to_closed_roles_are_revoked(
    m06_tables: Engine,
    grant_sql: str,
) -> None:
    migration = POLICIES.read_text(encoding="utf-8")
    with m06_tables.begin() as conn:
        conn.exec_driver_sql(grant_sql)

    _apply_migration(m06_tables, migration)
    _assert_closed_grants(m06_tables)


@pytest.mark.rls_integration
def test_mixed_table_and_column_grants_are_revoked(m06_tables: Engine) -> None:
    migration = POLICIES.read_text(encoding="utf-8")
    with m06_tables.begin() as conn:
        conn.exec_driver_sql(
            "revoke all privileges on table public.password_reset_tokens "
            "from anon, authenticated, public"
        )
        conn.exec_driver_sql(
            "grant select on table public.password_reset_tokens to authenticated"
        )
        conn.exec_driver_sql(
            "grant references (id), update (payload) "
            "on table public.password_reset_tokens to public"
        )
        conn.exec_driver_sql(
            "grant select (id), insert (payload) "
            "on table public.password_reset_tokens to anon"
        )

    _apply_migration(m06_tables, migration)
    _assert_closed_grants(m06_tables)


@pytest.mark.rls_integration
def test_public_table_grant_is_revoked(
    m06_tables: Engine,
) -> None:
    """PUBLIC é uma ACL explícita que M06 deve fechar, não ignorar."""
    migration = POLICIES.read_text(encoding="utf-8")
    with m06_tables.begin() as conn:
        conn.exec_driver_sql(
            "grant select on table public.platform_orchestrator to public"
        )

    _apply_migration(m06_tables, migration)
    _assert_closed_grants(m06_tables)


@pytest.mark.rls_integration
def test_service_role_privilege_lost_by_public_revoke_aborts_and_rolls_back(
    m06_tables: Engine,
) -> None:
    """M06 não cria grant novo para service_role nem pode remover o já efetivo."""
    migration = POLICIES.read_text(encoding="utf-8")
    with m06_tables.begin() as conn:
        conn.exec_driver_sql(
            "revoke all privileges on table public.password_reset_tokens "
            "from service_role"
        )
        conn.exec_driver_sql(
            "grant select on table public.password_reset_tokens to public"
        )

    _assert_migration_rejected_without_changes(
        m06_tables,
        migration,
        r"service_role lost effective SELECT table privilege "
        r"on public\.password_reset_tokens",
    )


@pytest.mark.rls_integration
def test_inherited_membership_table_grant_aborts_and_rolls_back(
    m06_tables: Engine,
) -> None:
    """INHERIT dá privilégio efetivo direto ao papel fechado e deve abortar."""
    migration = POLICIES.read_text(encoding="utf-8")
    _create_auxiliary_role(m06_tables, "m06_inherited_table", "nologin noinherit")
    with m06_tables.begin() as conn:
        conn.exec_driver_sql(
            "grant select on table public.password_reset_tokens to m06_inherited_table"
        )
    _grant_membership(
        m06_tables,
        "m06_inherited_table",
        "anon",
        inherit=True,
        set_role=False,
    )

    _assert_migration_rejected_without_changes(
        m06_tables,
        migration,
        r"unexpected effective SELECT privilege for role anon "
        r"on public\.password_reset_tokens",
    )


@pytest.mark.rls_integration
def test_direct_set_role_path_with_table_grant_aborts_and_rolls_back(
    m06_tables: Engine,
) -> None:
    migration = POLICIES.read_text(encoding="utf-8")
    _create_auxiliary_role(m06_tables, "m06_direct_set_table", "nologin noinherit")
    with m06_tables.begin() as conn:
        conn.exec_driver_sql(
            "grant select on table public.password_reset_tokens to m06_direct_set_table"
        )
    _grant_membership(
        m06_tables,
        "m06_direct_set_table",
        "anon",
        inherit=False,
        set_role=True,
    )
    _assert_can_set_role(m06_tables, "anon", "m06_direct_set_table")

    _assert_migration_rejected_without_changes(
        m06_tables,
        migration,
        r"SET ROLE-reachable role m06_direct_set_table has effective SELECT "
        r"table privilege on public\.password_reset_tokens",
    )


@pytest.mark.rls_integration
def test_transitive_set_role_path_with_table_grant_aborts_and_rolls_back(
    m06_tables: Engine,
) -> None:
    migration = POLICIES.read_text(encoding="utf-8")
    _create_auxiliary_role(m06_tables, "m06_set_middle", "nologin noinherit")
    _create_auxiliary_role(m06_tables, "m06_set_leaf", "nologin noinherit")
    with m06_tables.begin() as conn:
        conn.exec_driver_sql(
            "grant select on table public.password_reset_tokens to m06_set_leaf"
        )
    _grant_membership(
        m06_tables,
        "m06_set_leaf",
        "m06_set_middle",
        inherit=False,
        set_role=True,
    )
    _grant_membership(
        m06_tables,
        "m06_set_middle",
        "authenticated",
        inherit=False,
        set_role=True,
    )
    _assert_can_set_role(m06_tables, "authenticated", "m06_set_middle")

    _assert_migration_rejected_without_changes(
        m06_tables,
        migration,
        r"SET ROLE-reachable role m06_set_leaf has effective SELECT table privilege "
        r"on public\.password_reset_tokens",
    )


@pytest.mark.rls_integration
def test_noinherit_set_role_path_to_bypassrls_aborts_and_rolls_back(
    m06_tables: Engine,
) -> None:
    migration = POLICIES.read_text(encoding="utf-8")
    _create_auxiliary_role(
        m06_tables,
        "m06_set_bypass",
        "nologin noinherit bypassrls",
    )
    _grant_membership(
        m06_tables,
        "m06_set_bypass",
        "anon",
        inherit=False,
        set_role=True,
    )
    _assert_can_set_role(m06_tables, "anon", "m06_set_bypass")

    _assert_migration_rejected_without_changes(
        m06_tables,
        migration,
        r"SET ROLE-reachable role m06_set_bypass has BYPASSRLS or SUPERUSER",
    )


@pytest.mark.rls_integration
def test_set_role_path_to_table_owner_aborts_and_rolls_back(
    m06_tables: Engine,
) -> None:
    migration = POLICIES.read_text(encoding="utf-8")
    _create_auxiliary_role(m06_tables, "m06_set_owner", "nologin noinherit")
    with m06_tables.begin() as conn:
        conn.exec_driver_sql(
            "alter table public.password_reset_tokens owner to m06_set_owner"
        )
    _grant_membership(
        m06_tables,
        "m06_set_owner",
        "authenticated",
        inherit=False,
        set_role=True,
    )

    _assert_migration_rejected_without_changes(
        m06_tables,
        migration,
        r"SET ROLE-reachable role m06_set_owner owns public\.password_reset_tokens",
    )


@pytest.mark.rls_integration
def test_set_role_path_with_column_grant_aborts_and_rolls_back(
    m06_tables: Engine,
) -> None:
    migration = POLICIES.read_text(encoding="utf-8")
    _create_auxiliary_role(m06_tables, "m06_set_column", "nologin noinherit")
    with m06_tables.begin() as conn:
        conn.exec_driver_sql(
            "grant references (id) on table public.password_reset_tokens "
            "to m06_set_column"
        )
    _grant_membership(
        m06_tables,
        "m06_set_column",
        "authenticated",
        inherit=False,
        set_role=True,
    )

    _assert_migration_rejected_without_changes(
        m06_tables,
        migration,
        r"SET ROLE-reachable role m06_set_column has effective REFERENCES column privilege "
        r"on public\.password_reset_tokens\.id",
    )


@pytest.mark.rls_integration
def test_membership_without_set_role_and_without_inheritance_is_not_false_positive(
    m06_tables: Engine,
) -> None:
    migration = POLICIES.read_text(encoding="utf-8")
    _create_auxiliary_role(m06_tables, "m06_no_set", "nologin noinherit")
    with m06_tables.begin() as conn:
        conn.exec_driver_sql(
            "grant select on table public.password_reset_tokens to m06_no_set"
        )
    _grant_membership(
        m06_tables,
        "m06_no_set",
        "anon",
        inherit=False,
        set_role=False,
    )
    _assert_cannot_set_role(m06_tables, "anon", "m06_no_set")

    _apply_migration(m06_tables, migration)
    _assert_closed_grants(m06_tables)


@pytest.mark.rls_integration
@pytest.mark.parametrize("missing_table", POLICY_TABLES)
def test_each_missing_required_table_aborts_the_whole_migration(
    m06_tables: Engine,
    missing_table: str,
) -> None:
    migration = POLICIES.read_text(encoding="utf-8")
    with m06_tables.begin() as conn:
        conn.exec_driver_sql(f"drop table public.{missing_table}")

    _assert_migration_rejected_without_changes(
        m06_tables,
        migration,
        rf"required table public\.{missing_table} is missing",
    )


@pytest.mark.rls_integration
def test_unexpected_policy_name_aborts_without_changes(m06_tables: Engine) -> None:
    migration = POLICIES.read_text(encoding="utf-8")
    with m06_tables.begin() as conn:
        conn.exec_driver_sql(
            "create policy unexpected_policy on public.password_reset_tokens "
            "as restrictive for all to public using (false) with check (false)"
        )

    _assert_migration_rejected_without_changes(
        m06_tables,
        migration,
        r"unexpected policy state on public\.password_reset_tokens",
    )


@pytest.mark.rls_integration
def test_additional_policy_beside_expected_aborts_without_changes(
    m06_tables: Engine,
) -> None:
    migration = POLICIES.read_text(encoding="utf-8")
    _create_expected_policy(m06_tables, "password_reset_tokens")
    with m06_tables.begin() as conn:
        conn.exec_driver_sql(
            "create policy unexpected_extra on public.password_reset_tokens "
            "as restrictive for all to public using (false) with check (false)"
        )

    _assert_migration_rejected_without_changes(
        m06_tables,
        migration,
        r"unexpected policy state on public\.password_reset_tokens",
    )


@pytest.mark.rls_integration
def test_expected_policy_that_is_permissive_aborts_without_changes(
    m06_tables: Engine,
) -> None:
    migration = POLICIES.read_text(encoding="utf-8")
    _create_policy(
        m06_tables,
        "password_reset_tokens",
        "for all to public using (false) with check (false)",
    )

    _assert_migration_rejected_without_changes(
        m06_tables,
        migration,
        r"unexpected policy state on public\.password_reset_tokens",
    )


@pytest.mark.rls_integration
@pytest.mark.parametrize(
    "definition",
    (
        "as restrictive for select to public using (false)",
        "as restrictive for all to authenticated using (false) with check (false)",
        "as restrictive for all to public using (true) with check (false)",
        "as restrictive for all to public using (false) with check (true)",
        "as restrictive for all to public using (false)",
    ),
    ids=("command", "roles", "using", "with-check", "missing-with-check"),
)
def test_expected_policy_with_divergent_semantics_aborts_without_changes(
    m06_tables: Engine,
    definition: str,
) -> None:
    migration = POLICIES.read_text(encoding="utf-8")
    _create_policy(m06_tables, "password_reset_tokens", definition)

    _assert_migration_rejected_without_changes(
        m06_tables,
        migration,
        r"unexpected policy state on public\.password_reset_tokens",
    )


@pytest.mark.rls_integration
def test_partial_existing_state_rolls_back_all_tables(m06_tables: Engine) -> None:
    migration = POLICIES.read_text(encoding="utf-8")
    _create_expected_policy(m06_tables, "password_reset_tokens")
    with m06_tables.begin() as conn:
        conn.exec_driver_sql(
            "create policy unexpected_policy on public.platform_audit_log "
            "as restrictive for all to public using (false) with check (false)"
        )

    _assert_migration_rejected_without_changes(
        m06_tables,
        migration,
        r"unexpected policy state on public\.platform_audit_log",
    )
