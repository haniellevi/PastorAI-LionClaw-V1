"""Prova PG17 descartável do contrato da projeção privada."""

from __future__ import annotations

from collections.abc import Iterator
import hashlib
import ipaddress
import json
import pathlib
import uuid

import psycopg2
from psycopg2 import Error as PsycopgError
from psycopg2 import sql as pg_sql
import pytest
from sqlalchemy.engine import make_url

from tests.conftest_rls import assert_disposable_database, rls_database_url


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRIVATE_HEAD_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "private-runtime-catalog-head-v1.json"
)
PRIVATE_MIGRATIONS_DIR = REPO_ROOT / "backend" / "migrations" / "private_runtime"


def _load_canonical_sql() -> str:
    head = json.loads(PRIVATE_HEAD_PATH.read_text(encoding="utf-8"))
    current = head["current_head"]
    entries = head["private_entries"]
    assert isinstance(current, dict)
    assert isinstance(entries, list) and entries
    basename = current["last_basename"]
    assert isinstance(basename, str)
    entry = next(item for item in entries if item["name"] == basename)
    assert entry == entries[-1]
    path = PRIVATE_MIGRATIONS_DIR / basename
    assert path.parent == PRIVATE_MIGRATIONS_DIR
    assert path.name == basename
    assert not path.is_symlink()
    content = path.read_bytes()
    assert len(content) == entry["size_bytes"]
    assert hashlib.sha256(content).hexdigest() == entry["sha256"]
    return content.decode("utf-8")


CANONICAL_SQL = _load_canonical_sql()

A = "0a0a0a0a-0000-0000-0000-00000000000a"
B = "0b0b0b0b-0000-0000-0000-00000000000b"
PERSON_A = "aaaaaaaa-1111-1111-1111-111111111111"
PERSON_B = "bbbbbbbb-2222-2222-2222-222222222222"
CONVERSATION_A = "aaaaaaaa-3333-3333-3333-333333333333"
CONVERSATION_B = "bbbbbbbb-4444-4444-4444-444444444444"
CONVERSATION_CROSS = "aaaaaaaa-5555-5555-5555-555555555555"


BASE_SQL = """
do $roles$
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'anon') then
    create role anon nologin noinherit nosuperuser nobypassrls
      nocreatedb nocreaterole noreplication;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles where rolname = 'authenticated'
  ) then
    create role authenticated nologin noinherit nosuperuser nobypassrls
      nocreatedb nocreaterole noreplication;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles where rolname = 'service_role'
  ) then
    create role service_role nologin noinherit nosuperuser bypassrls
      nocreatedb nocreaterole noreplication;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles where rolname = 'agent_runtime'
  ) then
    create role agent_runtime nologin noinherit nosuperuser nobypassrls
      nocreatedb nocreaterole noreplication;
  end if;
end
$roles$;

alter role agent_runtime nologin noinherit nosuperuser nobypassrls
  nocreatedb nocreaterole noreplication;
alter role agent_runtime set row_security = on;
alter role agent_runtime set search_path = pg_catalog, agent_private;

create type conversation_estado as enum ('ia', 'humano', 'aguardando');

create table igrejas (id uuid primary key, nome text not null);
create table app_users (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id),
  clerk_user_id text unique
);
create table pessoas (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id),
  nome text not null,
  optout boolean not null default false,
  sem_interesse boolean not null default false
);
create table conversations (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id),
  pessoa_id uuid references pessoas(id),
  telefone text not null default 'synthetic',
  estado conversation_estado
);

create or replace function public.current_igreja_id()
returns uuid
language sql
stable
security definer
set search_path = public, pg_temp
as $function$
  select coalesce(
    nullif(current_setting('app.tenant_igreja_id', true), '')::uuid,
    (
      select au.igreja_id
        from public.app_users au
       where au.clerk_user_id = nullif(
         coalesce(
           nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
           current_setting('request.jwt.claim.sub', true)
         ),
         ''
       )
       limit 1
    )
  );
$function$;
revoke execute on function public.current_igreja_id() from public, anon;
grant execute on function public.current_igreja_id() to authenticated, service_role;

create schema agent_private;
revoke all on schema agent_private from public, anon, authenticated, service_role;
grant usage on schema agent_private to agent_runtime;
create function agent_private.current_tenant_id()
returns uuid
language sql
stable
security invoker
set search_path = pg_catalog
as $function$
  select nullif(
    pg_catalog.current_setting('app.tenant_igreja_id', true), ''
  )::pg_catalog.uuid
$function$;
revoke all on function agent_private.current_tenant_id()
  from public, anon, authenticated, service_role;
grant execute on function agent_private.current_tenant_id() to agent_runtime;

alter table pessoas enable row level security;
create policy tenant_isolation on pessoas
  as permissive for all to public
  using (igreja_id = public.current_igreja_id())
  with check (igreja_id = public.current_igreja_id());
alter table conversations enable row level security;
create policy tenant_isolation on conversations
  as permissive for all to public
  using (igreja_id = public.current_igreja_id())
  with check (igreja_id = public.current_igreja_id());

grant usage on schema public to authenticated;
grant select, insert, update, delete on table pessoas to authenticated;
grant select, insert, update, delete on table conversations to authenticated;
grant select on table app_users to authenticated;

insert into igrejas (id, nome) values
  ('0a0a0a0a-0000-0000-0000-00000000000a', 'Igreja A'),
  ('0b0b0b0b-0000-0000-0000-00000000000b', 'Igreja B');
insert into app_users (id, igreja_id, clerk_user_id) values
  ('aaaaaaaa-0000-0000-0000-000000000001',
   '0a0a0a0a-0000-0000-0000-00000000000a', 'clerk-a'),
  ('bbbbbbbb-0000-0000-0000-000000000002',
   '0b0b0b0b-0000-0000-0000-00000000000b', 'clerk-b');
insert into pessoas (id, igreja_id, nome, optout, sem_interesse) values
  ('aaaaaaaa-1111-1111-1111-111111111111',
   '0a0a0a0a-0000-0000-0000-00000000000a', 'Pessoa A', false, false),
  ('bbbbbbbb-2222-2222-2222-222222222222',
   '0b0b0b0b-0000-0000-0000-00000000000b', 'Pessoa B', true, true);
insert into conversations (id, igreja_id, pessoa_id, telefone, estado) values
  ('aaaaaaaa-3333-3333-3333-333333333333',
   '0a0a0a0a-0000-0000-0000-00000000000a',
   'aaaaaaaa-1111-1111-1111-111111111111', 'a', 'ia'),
  ('bbbbbbbb-4444-4444-4444-444444444444',
   '0b0b0b0b-0000-0000-0000-00000000000b',
   'bbbbbbbb-2222-2222-2222-222222222222', 'b', 'humano'),
  ('aaaaaaaa-5555-5555-5555-555555555555',
   '0a0a0a0a-0000-0000-0000-00000000000a',
   'bbbbbbbb-2222-2222-2222-222222222222', 'cross', 'ia');
"""


def _assert_disposable_pg17(connection: psycopg2.extensions.connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "select current_setting('server_version_num')::integer, "
            "pg_catalog.inet_server_addr()::text"
        )
        version_num, server_address = cursor.fetchone()
    assert version_num // 10_000 == 17
    if server_address is not None:
        assert not ipaddress.ip_interface(server_address).ip.is_global


def _plain_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg2://", "postgresql://", 1)


def _create_database(base_url: str, name: str) -> tuple[str, str]:
    base = make_url(base_url)
    assert base.host in {"127.0.0.1", "::1", "localhost"}
    target_url = base.set(database=name).render_as_string(hide_password=False)
    admin_url = _plain_dsn(
        base.set(database="postgres").render_as_string(hide_password=False)
    )
    assert_disposable_database(target_url)
    connection = psycopg2.connect(admin_url)
    try:
        connection.autocommit = True
        _assert_disposable_pg17(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                pg_sql.SQL("create database {} template template0").format(
                    pg_sql.Identifier(name)
                )
            )
    finally:
        connection.close()
    return _plain_dsn(target_url), admin_url


def _drop_database(admin_url: str, name: str) -> None:
    connection = psycopg2.connect(admin_url)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                "select pg_catalog.pg_terminate_backend(pid) "
                "from pg_catalog.pg_stat_activity "
                "where datname = %s and pid <> pg_catalog.pg_backend_pid()",
                (name,),
            )
            cursor.execute(
                pg_sql.SQL("drop database if exists {} with (force)").format(
                    pg_sql.Identifier(name)
                )
            )
    finally:
        connection.close()


@pytest.fixture
def projection_database(rls_database_url: str) -> Iterator[str]:
    name = f"private_projection_{uuid.uuid4().hex[:12]}"
    target_url, admin_url = _create_database(rls_database_url, name)
    try:
        with psycopg2.connect(target_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(BASE_SQL)
            connection.commit()
        yield target_url
    finally:
        _drop_database(admin_url, name)


def _apply_fixture(database_url: str) -> None:
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(CANONICAL_SQL)
        connection.commit()


def _set_context(cursor, tenant: str, claims: str) -> None:
    cursor.execute(
        "select set_config('app.tenant_igreja_id', %s, false)",
        (tenant,),
    )
    cursor.execute(
        "select set_config('request.jwt.claims', %s, false)",
        (claims,),
    )


def _web_helper_snapshot(
    database_url: str,
) -> tuple[str, tuple[tuple[str, str, bool], ...]]:
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "select pg_catalog.pg_get_functiondef("
                "'public.current_igreja_id()'::pg_catalog.regprocedure)"
            )
            body = cursor.fetchone()[0]
            cursor.execute(
                "select case when acl.grantee = 0 then 'PUBLIC' "
                "else acl.grantee::pg_catalog.regrole::text end, "
                "acl.privilege_type, acl.is_grantable "
                "from pg_catalog.pg_proc function_record "
                "cross join lateral pg_catalog.aclexplode(coalesce("
                "function_record.proacl, "
                "pg_catalog.acldefault('f', function_record.proowner)"
                ")) acl "
                "where function_record.oid = "
                "'public.current_igreja_id()'::pg_catalog.regprocedure "
                "order by 1, 2"
            )
            acl = tuple(cursor.fetchall())
    return body, acl


@pytest.mark.rls_integration
def test_private_runtime_projection_pg17(projection_database: str) -> None:
    with psycopg2.connect(projection_database) as connection:
        _assert_disposable_pg17(connection)

    web_helper_before = _web_helper_snapshot(projection_database)
    _apply_fixture(projection_database)
    _apply_fixture(projection_database)
    web_helper_after = _web_helper_snapshot(projection_database)
    assert web_helper_after[0] == web_helper_before[0]
    assert set(web_helper_after[1]) == {
        ("authenticated", "EXECUTE", False),
        ("agent_projection_owner", "EXECUTE", False),
        ("postgres", "EXECUTE", False),
        ("service_role", "EXECUTE", False),
    }

    with psycopg2.connect(projection_database) as admin:
        with admin.cursor() as cursor:
            cursor.execute(
                "select has_schema_privilege('agent_runtime', 'agent_private', 'USAGE'), "
                "has_schema_privilege('agent_runtime', 'agent_private', 'CREATE'), "
                "has_function_privilege('agent_runtime', "
                "'agent_private.load_turn_context(uuid)', 'EXECUTE'), "
                "has_function_privilege('agent_runtime', "
                "'public.current_igreja_id()', 'EXECUTE')"
            )
            assert cursor.fetchone() == (True, False, True, False)
            cursor.execute(
                "select has_function_privilege('agent_projection_owner', "
                "'agent_private.current_tenant_id()', 'EXECUTE'), "
                "has_function_privilege('agent_projection_owner', "
                "'public.current_igreja_id()', 'EXECUTE')"
            )
            assert cursor.fetchone() == (True, True)

        runtime_url = projection_database
    try:
        with psycopg2.connect(runtime_url) as runtime:
            with runtime.cursor() as cursor:
                cursor.execute("set local role agent_runtime")
                _set_context(cursor, A, '{"sub":"clerk-b"}')
                cursor.execute(
                    "select * from agent_private.load_turn_context(%s)",
                    (CONVERSATION_A,),
                )
                assert cursor.fetchall() == [
                    (A, CONVERSATION_A, PERSON_A, "ia", False, False)
                ]
                cursor.execute(
                    "select * from agent_private.load_turn_context(%s)",
                    (CONVERSATION_B,),
                )
                assert cursor.fetchall() == []
                cursor.execute(
                    "select * from agent_private.load_turn_context(%s)",
                    (CONVERSATION_CROSS,),
                )
                assert cursor.fetchall() == []

                _set_context(cursor, B, '{"sub":"clerk-a"}')
                cursor.execute(
                    "select * from agent_private.load_turn_context(%s)",
                    (CONVERSATION_B,),
                )
                assert cursor.fetchall() == [
                    (B, CONVERSATION_B, PERSON_B, "humano", True, True)
                ]

                _set_context(cursor, "", '{"sub":"clerk-b"}')
                cursor.execute(
                    "select * from agent_private.load_turn_context(%s)",
                    (CONVERSATION_B,),
                )
                assert cursor.fetchall() == []
                cursor.execute(
                    "select * from agent_private.load_turn_context(NULL::uuid)"
                )
                assert cursor.fetchall() == []

                cursor.execute(
                    "select set_config('request.jwt.claims', '', false)"
                )
                cursor.execute(
                    "select * from agent_private.load_turn_context(%s)",
                    (CONVERSATION_B,),
                )
                assert cursor.fetchall() == []

                cursor.execute(
                    "select set_config('app.tenant_igreja_id', 'invalid-guc', false)"
                )
                with pytest.raises(PsycopgError) as invalid:
                    cursor.execute(
                        "select * from agent_private.load_turn_context(%s)",
                        (CONVERSATION_A,),
                    )
                runtime.rollback()
                assert invalid.value.pgcode == "22023"
                assert invalid.value.diag.message_primary == "invalid tenant context"
                cursor.execute("set local role agent_runtime")

                for operation, statement in (
                    ("select", "select id from public.pessoas"),
                    (
                        "insert",
                        "insert into public.pessoas (id, igreja_id, nome) values "
                        "('aaaaaaaa-9999-9999-9999-999999999999', "
                        "'0a0a0a0a-0000-0000-0000-00000000000a', 'denied')",
                    ),
                    ("update", "update public.pessoas set nome = 'denied'"),
                    ("delete", "delete from public.pessoas"),
                    ("select conversations", "select id from public.conversations"),
                    (
                        "insert conversations",
                        "insert into public.conversations "
                        "(id, igreja_id, pessoa_id, estado) values "
                        "('aaaaaaaa-9999-9999-9999-999999999999', "
                        "'0a0a0a0a-0000-0000-0000-00000000000a', "
                        "'aaaaaaaa-1111-1111-1111-111111111111', 'ia')",
                    ),
                    (
                        "update conversations",
                        "update public.conversations set estado = 'humano'",
                    ),
                    ("delete conversations", "delete from public.conversations"),
                ):
                    try:
                        cursor.execute(statement)
                    except PsycopgError:
                        runtime.rollback()
                        cursor.execute("set local role agent_runtime")
                    else:
                        pytest.fail(f"runtime {operation} unexpectedly permitted")
    finally:
        with psycopg2.connect(projection_database) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    "select rolcanlogin, rolinherit, rolsuper, rolbypassrls, "
                    "rolconfig from pg_catalog.pg_roles "
                    "where rolname = 'agent_runtime'"
                )
                assert cursor.fetchone() == (
                    False,
                    False,
                    False,
                    False,
                    ["row_security=on", "search_path=pg_catalog, agent_private"],
                )


def _execute_admin(database_url: str, statement: str) -> None:
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(statement)
        connection.commit()


@pytest.mark.rls_integration
@pytest.mark.parametrize(
    ("adversary", "mutation", "expected_message"),
    (
        (
            "extra owner column",
            "grant select (telefone) on table public.conversations "
            "to agent_projection_owner",
            "projection column ACL",
        ),
        (
            "broad owner table grant",
            "grant select on table public.pessoas to agent_projection_owner",
            "projection table ACL",
        ),
        (
            "broad runtime table grant",
            "grant select on table public.pessoas to agent_runtime",
            "public relation ACL",
        ),
        (
            "removed restrictive barrier",
            "drop policy agent_projection_owner_tenant_barrier_pessoas "
            "on public.pessoas",
            "policy set",
        ),
        (
            "altered restrictive barrier",
            "alter policy agent_projection_owner_tenant_barrier_pessoas "
            "on public.pessoas using (true)",
            "owner policy",
        ),
        (
            "weakened restrictive barrier",
            "alter policy agent_projection_owner_tenant_barrier_pessoas "
            "on public.pessoas using "
            "(igreja_id = agent_private.current_tenant_id() or true)",
            "owner policy",
        ),
        (
            "runtime web-helper execute",
            "grant execute on function public.current_igreja_id() "
            "to agent_runtime",
            "web tenant helper ACL",
        ),
        (
            "owner membership",
            "grant authenticated to agent_projection_owner",
            "projection owner memberships",
        ),
        (
            "owner bypassrls",
            "alter role agent_projection_owner bypassrls",
            "projection owner attributes",
        ),
    ),
)
def test_private_runtime_projection_security_adversaries(
    projection_database: str,
    adversary: str,
    mutation: str,
    expected_message: str,
) -> None:
    _apply_fixture(projection_database)
    _execute_admin(projection_database, mutation)
    try:
        with pytest.raises(PsycopgError) as drift:
            _apply_fixture(projection_database)
        assert drift.value.pgcode == "P0001"
        error_phase = (
            "private runtime postcondition"
            if adversary == "runtime web-helper execute"
            else "private runtime conflict"
        )
        assert drift.value.diag.message_primary == (
            f"{error_phase}: {expected_message}"
        )
    finally:
        if adversary == "owner membership":
            _execute_admin(
                projection_database,
                "revoke authenticated from agent_projection_owner",
            )
        elif adversary == "owner bypassrls":
            _execute_admin(
                projection_database,
                "alter role agent_projection_owner nobypassrls",
            )


def _snapshot_projection_baseline(database_url: str) -> tuple[object, ...]:
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "select pg_catalog.pg_get_functiondef("
                "pg_catalog.to_regprocedure('agent_private.current_tenant_id()')), "
                "pg_catalog.pg_get_functiondef("
                "pg_catalog.to_regprocedure('public.current_igreja_id()'))"
            )
            helper_bodies = cursor.fetchone()

            cursor.execute(
                "select polrelid::pg_catalog.regclass::text, polname, "
                "polpermissive, polcmd, polroles::text, "
                "pg_catalog.pg_get_expr(polqual, polrelid), "
                "pg_catalog.pg_get_expr(polwithcheck, polrelid) "
                "from pg_catalog.pg_policy "
                "where polrelid in ('public.pessoas'::pg_catalog.regclass, "
                "'public.conversations'::pg_catalog.regclass) "
                "order by polrelid, polname"
            )
            web_policies = cursor.fetchall()

            cursor.execute(
                "select nspacl::text from pg_catalog.pg_namespace "
                "where nspname = 'agent_private'"
            )
            schema_acl = cursor.fetchone()

            cursor.execute(
                "select c.oid::pg_catalog.regclass::text, c.relacl::text "
                "from pg_catalog.pg_class c "
                "where c.oid in ('public.pessoas'::pg_catalog.regclass, "
                "'public.conversations'::pg_catalog.regclass) "
                "order by c.oid"
            )
            relation_acls = cursor.fetchall()

            cursor.execute(
                "select c.oid::pg_catalog.regclass::text, a.attname, "
                "a.attacl::text "
                "from pg_catalog.pg_class c "
                "join pg_catalog.pg_attribute a on a.attrelid = c.oid "
                "where c.oid in ('public.pessoas'::pg_catalog.regclass, "
                "'public.conversations'::pg_catalog.regclass) "
                "and a.attnum > 0 and not a.attisdropped "
                "order by c.oid, a.attnum"
            )
            column_acls = cursor.fetchall()

            cursor.execute(
                "select p.oid::pg_catalog.regprocedure::text, p.proacl::text "
                "from pg_catalog.pg_proc p "
                "where p.oid in ("
                "pg_catalog.to_regprocedure('agent_private.current_tenant_id()'), "
                "pg_catalog.to_regprocedure('public.current_igreja_id()')) "
                "order by p.oid"
            )
            function_acls = cursor.fetchall()

            cursor.execute(
                "select d.defaclobjtype, d.defaclnamespace::pg_catalog.regnamespace::text, "
                "d.defaclacl::text "
                "from pg_catalog.pg_default_acl d "
                "where d.defaclrole = pg_catalog.to_regrole(current_user) "
                "and d.defaclnamespace = 'agent_private'::pg_catalog.regnamespace "
                "order by d.defaclobjtype"
            )
            default_acls = cursor.fetchall()

            cursor.execute(
                "select rolname, rolcanlogin, rolinherit, rolsuper, "
                "rolbypassrls, rolcreatedb, rolcreaterole, rolreplication, "
                "rolconnlimit, rolvaliduntil, rolconfig::text "
                "from pg_catalog.pg_roles "
                "where rolname in ('agent_runtime', 'agent_projection_owner') "
                "order by rolname"
            )
            role_state = cursor.fetchall()

    return (
        helper_bodies,
        web_policies,
        schema_acl,
        relation_acls,
        column_acls,
        function_acls,
        default_acls,
        role_state,
    )


def _apply_fixture_with_failure(database_url: str) -> None:
    prefix, separator, _ = CANONICAL_SQL.rpartition("commit;")
    assert separator == "commit;"
    failing_sql = prefix + "select 1 / 0;"
    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(failing_sql)
        pytest.fail("fixture failure injection unexpectedly committed")
    except PsycopgError as failure:
        assert failure.pgcode == "22012"
        connection.rollback()
    finally:
        connection.close()


@pytest.mark.rls_integration
def test_private_runtime_projection_rollback_atomicity(
    projection_database: str,
) -> None:
    baseline = _snapshot_projection_baseline(projection_database)
    _apply_fixture_with_failure(projection_database)

    assert _snapshot_projection_baseline(projection_database) == baseline
    with psycopg2.connect(projection_database) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "select pg_catalog.to_regprocedure("
                "'agent_private.load_turn_context(uuid)'), "
                "count(*) filter (where polname like 'agent_projection_owner%') "
                "from pg_catalog.pg_policy "
                "where polrelid in ('public.pessoas'::pg_catalog.regclass, "
                "'public.conversations'::pg_catalog.regclass)"
            )
            assert cursor.fetchone() == (None, 0)

    # A rolled-back replay remains retryable, proving that the failed batch did
    # not leave a hidden transaction-aborted connection or global role drift.
    _apply_fixture(projection_database)
