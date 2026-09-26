"""Executa a migration de identidade sem tenant em PostgreSQL descartável."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import uuid

import psycopg2
import pytest
from psycopg2.errors import CheckViolation, LockNotAvailable, NotNullViolation
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from scripts import migrate

from tests.conftest_rls import rls_database_url  # noqa: F401


MIGRATION = Path(__file__).parents[1] / "migrations" / (
    "20260925_183811_preserve_platform_admins_on_tenant_deletion.sql"
)
A = "10000000-0000-0000-0000-000000000001"
B = "10000000-0000-0000-0000-000000000002"
ADMIN = "20000000-0000-0000-0000-000000000001"
USER_A = "20000000-0000-0000-0000-000000000002"
USER_B = "20000000-0000-0000-0000-000000000003"

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def migrated_db(rls_database_url):
    engine = create_engine(rls_database_url)
    schema = "detach_test_" + uuid.uuid4().hex
    connection = engine.raw_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("show server_version_num")
        assert 170000 <= int(cursor.fetchone()[0]) < 180000
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
            create table igrejas (id uuid primary key);
            create table app_users (
              id uuid primary key, igreja_id uuid not null
                references igrejas(id) on delete cascade,
              clerk_user_id text unique, pessoa_id uuid, celula_pendente_id uuid,
              unique(igreja_id,id)
            );
            create table platform_admins (
              app_user_id uuid primary key references app_users(id) on delete cascade
            );
            create table user_roles (
              igreja_id uuid not null references igrejas(id) on delete cascade,
              user_id uuid not null references app_users(id) on delete cascade,
              foreign key (igreja_id,user_id) references app_users(igreja_id,id)
            );
            create function current_igreja_id() returns uuid language sql stable
              as $$ select nullif(current_setting('app.tenant_igreja_id',true),'')::uuid $$;
            alter table app_users enable row level security;
            create policy tenant_isolation on app_users for all
              using(igreja_id=current_igreja_id())
              with check(igreja_id=current_igreja_id());
            grant usage on schema {schema} to authenticated;
            grant select,insert,update,delete on app_users to authenticated;
            grant select on app_users to public;
            grant select on app_users to anon;
        """)
        cursor.execute("select rolbypassrls,rolsuper from pg_roles where rolname='authenticated'")
        assert cursor.fetchone() == (False, False)
        cursor.execute("insert into igrejas values (%s),(%s)", (A, B))
        cursor.executemany(
            "insert into app_users(id,igreja_id,clerk_user_id) values(%s,%s,%s)",
            [(ADMIN, A, "synthetic-admin"), (USER_A, A, "synthetic-a"), (USER_B, B, "synthetic-b")],
        )
        cursor.execute("insert into platform_admins values(%s)", (ADMIN,))
        cursor.execute("insert into user_roles values(%s,%s)", (A, ADMIN))
        sql = MIGRATION.read_text().replace("public.", schema + ".")
        cursor.execute(sql)
        cursor.execute(sql)
        yield cursor, schema
    finally:
        connection.rollback()
        cursor.close()
        connection.close()
        engine.dispose()


def _detach(cursor):
    cursor.execute("delete from user_roles where user_id=%s", (ADMIN,))
    cursor.execute("update app_users set igreja_id=null where id=%s", (ADMIN,))


def test_migration_preserves_admin_when_church_is_deleted(migrated_db):
    cursor, _ = migrated_db
    _detach(cursor)
    cursor.execute("delete from igrejas where id=%s", (A,))
    cursor.execute("select id::text,igreja_id::text from app_users order by id")
    assert cursor.fetchall() == [(ADMIN, None), (USER_B, B)]
    cursor.execute("select app_user_id::text from platform_admins")
    assert cursor.fetchall() == [(ADMIN,)]
    cursor.execute("select count(*) from user_roles")
    assert cursor.fetchone() == (0,)


@pytest.mark.parametrize("tenant,expected", [(A, USER_A), (B, USER_B)])
def test_null_admin_is_invisible_to_both_tenants(migrated_db, tenant, expected):
    cursor, _ = migrated_db
    _detach(cursor)
    cursor.execute("select set_config('app.tenant_igreja_id',%s,true)", (tenant,))
    cursor.execute("set local role authenticated")
    cursor.execute("select id::text from app_users")
    assert cursor.fetchall() == [(expected,)]
    cursor.execute("update app_users set clerk_user_id='forbidden' where id=%s", (ADMIN,))
    assert cursor.rowcount == 0


def test_tenant_cannot_create_identity_without_church(migrated_db):
    cursor, _ = migrated_db
    cursor.execute("select set_config('app.tenant_igreja_id',%s,true)", (A,))
    cursor.execute("set local role authenticated")
    with pytest.raises(CheckViolation):
        cursor.execute("insert into app_users(id,igreja_id) values(%s,null)", (str(uuid.uuid4()),))


def test_tenant_cannot_detach_its_own_user(migrated_db):
    cursor, _ = migrated_db
    cursor.execute("select set_config('app.tenant_igreja_id',%s,true)", (A,))
    cursor.execute("set local role authenticated")
    with pytest.raises(CheckViolation):
        cursor.execute("update app_users set igreja_id=null where id=%s", (USER_A,))


def test_absent_tenant_context_reads_nothing(migrated_db):
    cursor, _ = migrated_db
    _detach(cursor)
    cursor.execute("select set_config('app.tenant_igreja_id','',true)")
    cursor.execute("set local role authenticated")
    cursor.execute("select count(*) from app_users")
    assert cursor.fetchone() == (0,)


def test_migration_keeps_rls_without_forcing_owner_and_public_without_access(migrated_db):
    cursor, schema = migrated_db
    cursor.execute(
        "select relrowsecurity,relforcerowsecurity from pg_class where oid=%s::regclass",
        (schema + ".app_users",),
    )
    assert cursor.fetchone() == (True, False)
    cursor.execute("select has_table_privilege('anon',%s,'SELECT')", (schema + ".app_users",))
    assert cursor.fetchone() == (False,)
    cursor.execute(
        "select count(*) from pg_class c, lateral aclexplode(c.relacl) a "
        "where c.oid=%s::regclass and a.grantee=0",
        (schema + ".app_users",),
    )
    assert cursor.fetchone() == (0,)
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        cursor.execute(
            "select has_table_privilege('authenticated',%s,%s)",
            (schema + ".app_users", privilege),
        )
        assert cursor.fetchone() == (True,)


def test_rollback_refuses_to_invent_a_church_for_preserved_admin(migrated_db):
    cursor, _ = migrated_db
    _detach(cursor)
    with pytest.raises(NotNullViolation):
        cursor.execute("alter table app_users alter column igreja_id set not null")


def test_rollback_succeeds_before_any_identity_is_detached(migrated_db):
    cursor, _ = migrated_db
    cursor.execute("alter table app_users alter column igreja_id set not null")
    cursor.execute("select count(*) from app_users")
    assert cursor.fetchone() == (3,)


@pytest.fixture
def simple_runner_connection(rls_database_url):
    """Apply the unmodified public SQL in a database owned only by this test."""
    url = make_url(rls_database_url)
    assert url.host in {"127.0.0.1", "localhost", "::1"}
    database = "detach_runner_" + uuid.uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    connection = None
    created = False
    try:
        with admin.connect() as setup:
            setup.exec_driver_sql(f"CREATE DATABASE {database}")
            created = True
        dsn = url.set(drivername="postgresql", database=database)
        connection = psycopg2.connect(dsn.render_as_string(hide_password=False))
        with connection.cursor() as cursor:
            cursor.execute("""
                create table public.app_users (
                    id uuid primary key, igreja_id uuid not null
                );
                create table public.platform_admins (
                    app_user_id uuid primary key references public.app_users(id) on delete cascade
                );
                create table public.schema_migrations (name text primary key);
            """)
        connection.commit()
        yield connection
    finally:
        if connection is not None:
            connection.close()
        if created:
            with admin.connect() as cleanup:
                cleanup.exec_driver_sql(f"DROP DATABASE {database}")
        admin.dispose()


def test_simple_runner_commits_exact_migration_and_ledger_together(simple_runner_connection):
    connection = simple_runner_connection
    assert migrate.cmd_apply(connection, MIGRATION.name, transactional=True) == 0
    with connection.cursor() as cursor:
        cursor.execute("select name from public.schema_migrations")
        assert cursor.fetchall() == [(MIGRATION.name,)]
        cursor.execute("""
            select is_nullable from information_schema.columns
            where table_schema='public' and table_name='app_users'
              and column_name='igreja_id'
        """)
        assert cursor.fetchone() == ("YES",)
        cursor.execute("""
            select relrowsecurity, relforcerowsecurity from pg_class
            where oid='public.app_users'::regclass
        """)
        assert cursor.fetchone() == (True, False)
    with pytest.raises(SystemExit, match="já está registrada"):
        migrate.cmd_apply(connection, MIGRATION.name, transactional=True)


def test_simple_runner_reverts_ddl_when_ledger_write_fails(simple_runner_connection):
    connection = simple_runner_connection
    with connection.cursor() as cursor:
        cursor.execute("""
            create function public.reject_synthetic_ledger_write()
            returns trigger language plpgsql as $$
            begin
                raise exception 'synthetic ledger failure';
            end;
            $$;
            create trigger reject_synthetic_ledger_write
            before insert on public.schema_migrations
            for each row execute function public.reject_synthetic_ledger_write();
        """)
    connection.commit()
    with pytest.raises(psycopg2.errors.RaiseException, match="synthetic ledger failure"):
        migrate.cmd_apply(connection, MIGRATION.name, transactional=True)
    with connection.cursor() as cursor:
        cursor.execute("select count(*) from public.schema_migrations")
        assert cursor.fetchone() == (0,)
        cursor.execute("""
            select is_nullable from information_schema.columns
            where table_schema='public' and table_name='app_users'
              and column_name='igreja_id'
        """)
        assert cursor.fetchone() == ("NO",)
        cursor.execute("""
            select relrowsecurity, relforcerowsecurity from pg_class
            where oid='public.app_users'::regclass
        """)
        assert cursor.fetchone() == (False, False)


def test_owner_without_bypass_resolves_real_jwt_helper(migrated_db):
    cursor, schema = migrated_db
    owner = "detach_owner_" + uuid.uuid4().hex
    cursor.execute(f"create role {owner} nologin nosuperuser nobypassrls")
    cursor.execute(f"grant usage, create on schema {schema} to {owner}")
    helper = MIGRATION.parent / "20260624_090102_current_igreja_id_guard_empty_claims.sql"
    sql = migrate.strip_outer_transaction(helper.read_text())
    sql = sql.replace("public.", schema + ".").replace(
        "search_path = public, pg_temp", f"search_path = {schema}, pg_temp"
    )
    cursor.execute(sql)
    cursor.execute(f"alter table app_users owner to {owner}")
    cursor.execute(f"alter function current_igreja_id() owner to {owner}")
    cursor.execute("select set_config('app.tenant_igreja_id','',true)")
    cursor.execute("select set_config('request.jwt.claims',%s,true)",
                   ('{"sub":"synthetic-a"}',))
    cursor.execute("set local role authenticated")
    cursor.execute("select current_igreja_id()::text")
    assert cursor.fetchone() == (A,)
    cursor.execute("select id::text from app_users order by id")
    assert cursor.fetchall() == [(ADMIN,), (USER_A,)]


@pytest.mark.parametrize("operation", ("insert", "update"))
def test_privileged_writer_cannot_create_null_non_admin(migrated_db, operation):
    cursor, _ = migrated_db
    with pytest.raises(CheckViolation):
        if operation == "insert":
            cursor.execute("insert into app_users(id,igreja_id) values(%s,null)",
                           (str(uuid.uuid4()),))
        else:
            cursor.execute("update app_users set igreja_id=null where id=%s", (USER_A,))


@pytest.mark.parametrize("operation", ("delete", "update"))
def test_cannot_remove_allowlist_membership_from_detached_admin(migrated_db, operation):
    cursor, _ = migrated_db
    _detach(cursor)
    with pytest.raises(CheckViolation):
        if operation == "delete":
            cursor.execute("delete from platform_admins where app_user_id=%s", (ADMIN,))
        else:
            cursor.execute("update platform_admins set app_user_id=%s where app_user_id=%s",
                           (USER_B, ADMIN))


def test_allowlist_removal_after_reassociation_is_allowed(migrated_db):
    cursor, _ = migrated_db
    _detach(cursor)
    cursor.execute("update app_users set igreja_id=%s where id=%s", (B, ADMIN))
    cursor.execute("delete from platform_admins where app_user_id=%s", (ADMIN,))
    assert cursor.rowcount == 1


def test_deleting_detached_identity_can_cascade_its_allowlist_entry(migrated_db):
    cursor, _ = migrated_db
    _detach(cursor)
    cursor.execute("delete from app_users where id=%s", (ADMIN,))
    cursor.execute("select count(*) from platform_admins")
    assert cursor.fetchone() == (0,)


def test_truncate_cannot_orphan_detached_admin(migrated_db):
    cursor, _ = migrated_db
    _detach(cursor)
    with pytest.raises(CheckViolation):
        cursor.execute("truncate platform_admins")


@pytest.mark.parametrize("first_operation", ("detach", "remove_allowlist"))
def test_detach_and_allowlist_removal_are_serialized(
    simple_runner_connection, first_operation, rls_database_url
):
    first = simple_runner_connection
    migrate.cmd_apply(first, MIGRATION.name, transactional=True)
    with first.cursor() as cur:
        cur.execute("insert into public.app_users values(%s,%s)", (ADMIN, A))
        cur.execute("insert into public.platform_admins values(%s)", (ADMIN,))
    first.commit()
    url = make_url(rls_database_url).set(drivername="postgresql", database=first.info.dbname)
    second = psycopg2.connect(url.render_as_string(hide_password=False))
    detach = "update public.app_users set igreja_id=null where id=%s"
    remove = "delete from public.platform_admins where app_user_id=%s"
    first_sql, second_sql = (detach, remove) if first_operation == "detach" else (remove, detach)
    try:
        with first.cursor() as cur:
            cur.execute(first_sql, (ADMIN,))
        with second.cursor() as cur:
            cur.execute("set local lock_timeout='100ms'")
            with pytest.raises(LockNotAvailable):
                cur.execute(second_sql, (ADMIN,))
        second.rollback()
        first.commit()
        with second.cursor() as cur:
            with pytest.raises(CheckViolation):
                cur.execute(second_sql, (ADMIN,))
        second.rollback()
    finally:
        second.close()


def test_competing_identity_guards_reject_one_transaction_without_orphans(
    simple_runner_connection, rls_database_url
):
    first = simple_runner_connection
    migrate.cmd_apply(first, MIGRATION.name, transactional=True)
    with first.cursor() as cur:
        cur.execute("insert into public.app_users values(%s,%s)", (ADMIN, A))
        cur.execute("insert into public.platform_admins values(%s)", (ADMIN,))
    first.commit()
    url = make_url(rls_database_url).set(drivername="postgresql", database=first.info.dbname)
    second = psycopg2.connect(url.render_as_string(hide_password=False))
    barrier = Barrier(2)

    def compete(connection, sql):
        barrier.wait(timeout=5)
        try:
            with connection.cursor() as cur:
                cur.execute(sql, (ADMIN,))
            connection.commit()
            return "committed"
        except (CheckViolation, LockNotAvailable):
            connection.rollback()
            return "rolled_back"

    try:
        for connection, table, column in (
            (first, "app_users", "id"), (second, "platform_admins", "app_user_id")
        ):
            with connection.cursor() as cur:
                cur.execute("set local deadlock_timeout='100ms'")
                cur.execute("set local lock_timeout='5s'")
                cur.execute(f"select 1 from public.{table} where {column}=%s for update", (ADMIN,))
        with ThreadPoolExecutor(max_workers=2) as pool:
            detach = pool.submit(compete, first,
                                 "update public.app_users set igreja_id=null where id=%s")
            revoke = pool.submit(compete, second,
                                 "delete from public.platform_admins where app_user_id=%s")
            assert sorted((detach.result(timeout=10), revoke.result(timeout=10))) == [
                "committed", "rolled_back"
            ]
        with first.cursor() as cur:
            cur.execute("""
                select count(*) from public.app_users u
                where u.igreja_id is null and not exists (
                    select 1 from public.platform_admins a where a.app_user_id=u.id
                )
            """)
            assert cur.fetchone() == (0,)
    finally:
        second.close()


@pytest.mark.parametrize("detach_first", (False, True))
def test_truncate_and_detach_preserve_invariant_without_reverse_row_lock(
    simple_runner_connection, rls_database_url, detach_first
):
    first = simple_runner_connection
    migrate.cmd_apply(first, MIGRATION.name, transactional=True)
    with first.cursor() as cur:
        cur.execute("insert into public.app_users values(%s,%s)", (ADMIN, A))
        cur.execute("insert into public.platform_admins values(%s)", (ADMIN,))
    first.commit()
    url = make_url(rls_database_url).set(drivername="postgresql", database=first.info.dbname)
    second = psycopg2.connect(url.render_as_string(hide_password=False))
    try:
        with first.cursor() as cur:
            cur.execute("select 1 from public.app_users where id=%s for update", (ADMIN,))
            if detach_first:
                cur.execute("update public.app_users set igreja_id=null where id=%s", (ADMIN,))
        with second.cursor() as cur:
            cur.execute("set local lock_timeout='100ms'")
            if detach_first:
                with pytest.raises(LockNotAvailable):
                    cur.execute("truncate public.platform_admins")
            else:
                with pytest.raises(CheckViolation):
                    cur.execute("truncate public.platform_admins")
        if detach_first:
            second.rollback()
            first.commit()
            with second.cursor() as cur:
                with pytest.raises(CheckViolation):
                    cur.execute("truncate public.platform_admins")
            second.rollback()
        else:
            second.rollback()
            with first.cursor() as cur:
                cur.execute("update public.app_users set igreja_id=null where id=%s", (ADMIN,))
            first.commit()
    finally:
        second.close()


def test_truncate_empty_allowlist_is_also_rejected(migrated_db):
    cursor, _ = migrated_db
    cursor.execute("delete from platform_admins")
    with pytest.raises(CheckViolation):
        cursor.execute("truncate platform_admins")


def test_repeatable_read_cannot_detach_after_concurrent_allowlist_removal(
    simple_runner_connection, rls_database_url
):
    first = simple_runner_connection
    migrate.cmd_apply(first, MIGRATION.name, transactional=True)
    with first.cursor() as cur:
        cur.execute("insert into public.app_users values(%s,%s)", (ADMIN, A))
        cur.execute("insert into public.platform_admins values(%s)", (ADMIN,))
    first.commit()
    url = make_url(rls_database_url).set(drivername="postgresql", database=first.info.dbname)
    second = psycopg2.connect(url.render_as_string(hide_password=False))
    try:
        with first.cursor() as cur:
            cur.execute("set transaction isolation level repeatable read")
            cur.execute("select count(*) from public.platform_admins")
            assert cur.fetchone() == (1,)
        with second.cursor() as cur:
            cur.execute("delete from public.platform_admins where app_user_id=%s", (ADMIN,))
        second.commit()
        with first.cursor() as cur:
            with pytest.raises((CheckViolation, psycopg2.errors.SerializationFailure)):
                cur.execute("update public.app_users set igreja_id=null where id=%s", (ADMIN,))
        first.rollback()
    finally:
        second.close()
