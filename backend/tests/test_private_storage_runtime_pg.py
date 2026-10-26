"""Real SQL identity of private Storage maintenance on the full migration chain.

The dedicated login is a synthetic LOGIN granted only in this disposable PG.
Nothing here relaxes RLS: every refusal comes from the real policies, grants
and SECURITY DEFINER checks installed by the migration.
"""
import datetime as dt
import os
import secrets
import threading
from collections import Counter
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.privacy_storage_session import (
    PrivateStorageScopeError, PrivateStorageUnavailable, dispose_private_storage_engine,
    get_private_storage_session_factory, scope_private_storage,
)
from tests.test_private_deletion_pg import api, claim, private_data, runtime, scoped  # noqa: F401
from tests.test_uv_turmas_pg import rls_database_url, migrated_database, database  # noqa: F401

pytestmark = pytest.mark.rls_integration
ROLE = 'private_storage_runtime'
MIGRATION = '20261030_100000_private_storage_worker_identity.sql'
REFUSED = 'Runtime de Storage privado obrigatório'


def _delete_both_churches(database, v):
    """Pending tasks in both churches: admin web path for A, owner path for B."""
    with api(database, v) as client:
        assert client.delete(f"/conversations/{v['conv']}").status_code == 200
    with database.begin() as c:
        c.execute(text('select private_delete_content(:t,\'conversa\',:c,:c)'), dict(t=v['other'], c=v['conv3']))
    with database.connect() as c:
        return {row.igreja_id: row.id for row in c.execute(text(
            "select distinct on (igreja_id) igreja_id,id from private_deletion_tasks where state='pendente' order by igreja_id,id"))}


def _sqlstate(error):
    return getattr(error.value.orig, 'pgcode', None)


def test_migration_creates_minimal_nologin_identity(database):
    with database.connect() as c:
        role = c.execute(text('''select rolcanlogin,rolinherit,rolsuper,rolbypassrls,rolcreatedb,
            rolcreaterole,rolreplication,rolpassword is null as no_password from pg_authid where rolname=:r'''),
            dict(r=ROLE)).one()
        assert tuple(role) == (False, False, False, False, False, False, False, True)
        assert c.execute(text('''select count(*) from pg_auth_members m join pg_roles r on r.oid=m.member
            where r.rolname=:r'''), dict(r=ROLE)).scalar_one() == 0
        check = lambda sql, **kw: c.execute(text(sql), kw).scalar_one()
        # No domain or pastoral data: only tasks/uploads and four functions.
        for table in ('conversations', 'messages', 'pessoas', 'cell_report_audio_inputs',
                      'private_deletion_receipts', 'private_deletion_sends', 'private_deletion_event_fences'):
            for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
                assert not check('select has_table_privilege(:r,:t,:p)', r=ROLE, t=table, p=privilege)
        assert check("select has_column_privilege(:r,'private_deletion_tasks','state','UPDATE')", r=ROLE)
        assert not check("select has_column_privilege(:r,'private_deletion_tasks','storage_path','SELECT')", r=ROLE)
        assert not check("select has_table_privilege(:r,'private_deletion_tasks','INSERT')", r=ROLE)
        assert check("select has_table_privilege(:r,'private_deletion_uploads','SELECT')", r=ROLE)
        assert check("select has_table_privilege(:r,'private_deletion_uploads','DELETE')", r=ROLE)
        assert not check("select has_table_privilege(:r,'private_deletion_uploads','INSERT')", r=ROLE)
        functions = ('private_storage_runtime_session()', 'private_storage_due_tasks(timestamptz,integer)',
                     'private_storage_begin_upload(uuid,uuid,uuid,bigint)', 'private_deletion_task_path(uuid)')
        for function in functions:
            assert check("select has_function_privilege(:r,:f,'EXECUTE')", r=ROLE, f=function)
            for other in ('authenticated', 'anon', 'service_role'):
                assert not check("select has_function_privilege(:r,:f,'EXECUTE')", r=other, f=function)
        # The previous subject-less worker branch is gone; admin progress stays.
        assert not check("select has_column_privilege('authenticated','private_deletion_tasks','state','UPDATE')")
        assert check("select has_column_privilege('authenticated','private_deletion_tasks','state','SELECT')")
        assert not check("select has_table_privilege('authenticated','private_deletion_uploads','SELECT')")
        policies = set(c.execute(text('''select polname from pg_policy
            where polrelid in ('private_deletion_tasks'::regclass,'private_deletion_uploads'::regclass)''')).scalars())
        assert policies == {'task_admin_read', 'task_private_storage', 'upload_private_storage'}


@pytest.mark.parametrize('tamper', ('bypassrls', 'superuser', 'inherit', 'createdb', 'createrole',
                                    'replication', 'membership'))
def test_unsafe_preexisting_role_is_refused(database, tamper):
    from scripts import migrate
    sql = migrate.strip_outer_transaction((migrate.MIGRATIONS_DIR / MIGRATION).read_text())
    with database.connect() as c:
        tx = c.begin()
        try:
            c.exec_driver_sql(f'grant authenticated to {ROLE}' if tamper == 'membership'
                              else f'alter role {ROLE} {tamper}')
            with pytest.raises(DBAPIError) as error:
                c.exec_driver_sql(sql, execution_options={'no_parameters': True})
            assert 'atributos inseguros' in str(error.value.orig)
        finally:
            tx.rollback()
    with database.connect() as c:
        assert not c.execute(text('select rolsuper or rolbypassrls or rolinherit from pg_roles where rolname=:r'),
                             dict(r=ROLE)).scalar_one()


def test_login_is_the_identity_and_definer_sees_owner(database, private_data, runtime):
    v = private_data
    tasks = _delete_both_churches(database, v)
    with runtime() as s:
        assert tuple(s.execute(text('select session_user::text, current_user::text')).one()) == (ROLE, ROLE)
        due = s.execute(text('select * from private_storage_due_tasks(now(),500)')).mappings().all()
        assert set(due[0].keys()) == {'id', 'igreja_id', 'receipt_id'}  # IDs only, never paths.
        assert {row['igreja_id'] for row in due} == {v['tenant'], v['other']}
    with database.begin() as c:
        c.exec_driver_sql('''create function public.synthetic_definer_identity() returns text[]
            language sql security definer set search_path=pg_catalog,public as
            $$ select array[current_user::text, session_user::text, public.private_storage_runtime_session()::text] $$''')
        c.exec_driver_sql(f'grant execute on function public.synthetic_definer_identity() to {ROLE}')
    try:
        with runtime() as s:
            # Inside SECURITY DEFINER current_user is the owner; session_user stays the login.
            owner, login, accepted = s.execute(text('select public.synthetic_definer_identity()')).scalar_one()
            assert (owner, login, accepted) == ('postgres', ROLE, 'true')
    finally:
        with database.begin() as c:
            c.exec_driver_sql('drop function public.synthetic_definer_identity()')
    # Tenant scope: A sees and changes only A; B's task and path stay hidden.
    with runtime() as s:
        scope_private_storage(s, v['tenant'])
        assert s.execute(text('select count(*) from private_deletion_tasks where igreja_id=:o'), dict(o=v['other'])).scalar_one() == 0
        assert s.execute(text('update private_deletion_tasks set attempts=attempts where id=:id'), dict(id=tasks[v['other']])).rowcount == 0
        assert s.execute(text('select private_deletion_task_path(:id)'), dict(id=tasks[v['other']])).scalar_one() is None
        assert s.execute(text('select private_deletion_task_path(:id)'), dict(id=tasks[v['tenant']])).scalar_one()
        with pytest.raises(DBAPIError) as error:
            s.execute(text('select private_storage_begin_upload(:t,:s,:c,0)'), dict(t=v['other'], s=uuid4(), c=v['conv3']))
        assert _sqlstate(error) == '42501'
    # No tenant GUC, no rows: the GUC scopes, it never authorizes by itself.
    with runtime() as s:
        assert s.execute(text('select count(*) from private_deletion_tasks')).scalar_one() == 0


def test_main_login_set_role_http_and_other_worker_are_refused(database, private_data, runtime):
    v = private_data
    tasks = _delete_both_churches(database, v)
    calls = (('select * from private_storage_due_tasks(now(),10)', {}),
             ('select private_deletion_task_path(:id)', dict(id=tasks[v['tenant']])),
             ('select private_storage_begin_upload(:t,:s,:c,0)', dict(t=v['tenant'], s=uuid4(), c=v['conv'])))
    # Main/owner login (superuser here) and the same login after SET ROLE.
    for set_role in (False, True):
        for sql, params in calls:
            with database.connect() as c, c.begin():
                c.execute(text("select set_config('app.tenant_igreja_id',:t,true)"), dict(t=str(v['tenant'])))
                if set_role:
                    c.exec_driver_sql(f'set local role {ROLE}')
                with pytest.raises(DBAPIError) as error:
                    c.execute(text(sql), params)
                assert REFUSED in str(error.value.orig)
        if set_role:
            with database.connect() as c, c.begin():
                c.execute(text("select set_config('app.tenant_igreja_id',:t,true)"), dict(t=str(v['tenant'])))
                c.exec_driver_sql(f'set local role {ROLE}')
                assert c.execute(text('select count(*) from private_deletion_tasks')).scalar_one() == 0
    # HTTP-like sessions (tenant scope, with or without an admin subject).
    for admin in (False, True):
        for sql in ('update private_deletion_tasks set attempts=attempts', 'select count(*) from private_deletion_uploads',
                    'select * from private_storage_due_tasks(now(),10)'):
            with scoped(database, v['tenant'], admin=admin) as s:
                with pytest.raises(DBAPIError) as error:
                    s.execute(text(sql))
                assert _sqlstate(error) == '42501'
    with api(database, v) as client:  # Admin progress is unchanged.
        receipt = client.get(f"/conversations/{v['conv']}/deletion-receipt").json()
        assert receipt['estado'] == 'pendente' and receipt['camadas']['midias']['pendentes'] == 2
    # Another worker login, even with SET ROLE authenticated and an EXECUTE grant.
    password = secrets.token_urlsafe(24)
    with database.begin() as c:
        c.exec_driver_sql(f"create role synthetic_other_worker login password '{password}' noinherit")
        c.exec_driver_sql('grant authenticated to synthetic_other_worker')
        c.exec_driver_sql('grant usage on schema public to synthetic_other_worker')
        c.exec_driver_sql('grant execute on function private_storage_due_tasks(timestamptz,integer) to synthetic_other_worker')
    other = create_engine(database.url.set(username='synthetic_other_worker', password=password))
    try:
        with other.connect() as c, c.begin():
            with pytest.raises(DBAPIError) as error:
                c.execute(text('select * from private_storage_due_tasks(now(),10)'))
            assert REFUSED in str(error.value.orig)
        with other.connect() as c, c.begin():
            c.execute(text("select set_config('app.tenant_igreja_id',:t,true)"), dict(t=str(v['tenant'])))
            c.exec_driver_sql('set local role authenticated')
            with pytest.raises(DBAPIError) as error:
                c.execute(text('select count(*) from private_deletion_uploads'))
            assert _sqlstate(error) == '42501'
    finally:
        other.dispose()
        with database.begin() as c:
            c.exec_driver_sql('drop owned by synthetic_other_worker')
            c.exec_driver_sql('drop role synthetic_other_worker')


@pytest.mark.parametrize('tamper', ('createdb', 'bypassrls', 'membership'))
def test_tampered_login_is_refused_by_client_and_sql(database, private_data, runtime, tamper):
    v = private_data
    _delete_both_churches(database, v)
    change, restore = ((f'grant authenticated to {ROLE}', f'revoke authenticated from {ROLE}')
                       if tamper == 'membership' else (f'alter role {ROLE} {tamper}', f'alter role {ROLE} no{tamper}'))
    with database.begin() as c:
        c.exec_driver_sql(change)
    raw = create_engine(os.environ['PRIVATE_STORAGE_DATABASE_URL'])
    try:
        with runtime() as s, pytest.raises(PrivateStorageScopeError):
            s.execute(text('select 1'))  # The BEGIN probe refuses before any query.
        with raw.connect() as c, c.begin():  # Without the client probe, SQL refuses too.
            with pytest.raises(DBAPIError) as error:
                c.execute(text('select * from private_storage_due_tasks(now(),10)'))
            assert REFUSED in str(error.value.orig)
    finally:
        raw.dispose()
        with database.begin() as c:
            c.exec_driver_sql(restore)
    with runtime() as s:
        # Restored: both churches' pending tasks (A: image + audio, B: image).
        assert s.execute(text('select count(*) from private_storage_due_tasks(now(),500)')).scalar_one() == 3


def test_scope_is_reproven_after_commit_and_pool_never_leaks_tenant(database, private_data, runtime):
    v = private_data
    _delete_both_churches(database, v)
    with runtime() as s:
        scope_private_storage(s, v['tenant'])
        first = s.execute(text('select count(*) from private_deletion_tasks')).scalar_one()
        assert first == 2
        s.commit()
        assert s.execute(text("select current_setting('app.tenant_igreja_id', true)")).scalar_one() == str(v['tenant'])
        assert s.execute(text('select count(*) from private_deletion_tasks')).scalar_one() == first
        with pytest.raises(PrivateStorageScopeError):
            scope_private_storage(s, v['other'])
    with runtime() as s:
        # Persist the GUC at session level, in the same transaction as the pid:
        # the next checkout must discard this connection instead of reusing it.
        leaked = s.execute(text("select pg_backend_pid() from (select set_config('app.tenant_igreja_id', :t, false)) g"),
                           dict(t=str(v['tenant']))).scalar_one()
        s.commit()
    with runtime() as s:
        assert s.execute(text('select pg_backend_pid()')).scalar_one() != leaked
        assert s.execute(text("select current_setting('app.tenant_igreja_id', true)")).scalar_one() in (None, '')
        assert s.execute(text('select count(*) from private_deletion_tasks')).scalar_one() == 0


def test_two_concurrent_cleanups_delete_each_object_once(database, private_data, runtime):
    from app.services.private_deletion import process_storage_tasks
    v = private_data
    with api(database, v) as client:
        receipt = client.delete(f"/conversations/{v['conv']}").json()['id']
    first_inside, second_done, calls = threading.Event(), threading.Event(), []
    def remove(tenant, paths):
        assert tenant == v['tenant']
        calls.extend(paths)
        if not first_inside.is_set():
            first_inside.set()
            assert second_done.wait(10)
    storage = SimpleNamespace(remove_tenant_media=remove)
    results = {}
    def run(name):
        results[name] = process_storage_tasks(runtime, storage=storage)
    first = threading.Thread(target=run, args=('first',))
    first.start()
    assert first_inside.wait(10)
    run('second')  # The receipt lock is held: no duplicate DELETE, no false completion.
    second_done.set()
    first.join(10)
    assert results == {'first': 2, 'second': 0}
    assert sorted(Counter(calls).values()) == [1, 1]
    with api(database, v) as client:
        assert client.get(f'/igreja/private-deletions/{receipt}').json()['estado'] == 'concluido'


def test_begin_upload_waits_for_the_deletion_generation_lock(database, private_data, runtime):
    from app.services.private_deletion import begin_audio_upload
    v = private_data
    holder = Session(database)
    holder.execute(text('select id from conversations where id=:c for update'), dict(c=v['conv']))
    result = {}
    worker = threading.Thread(target=lambda: result.update(accepted=begin_audio_upload(runtime, claim(v))))
    worker.start()
    worker.join(1.0)
    assert worker.is_alive()  # Blocked on the same row lock deletion takes.
    holder.execute(text('update conversations set deletion_generation=deletion_generation+1 where id=:c'), dict(c=v['conv']))
    holder.commit()
    holder.close()
    worker.join(10)
    assert result == {'accepted': False}  # The generation moved: no ownership.
    with database.connect() as c:
        assert c.execute(text('select count(*) from private_deletion_uploads')).scalar_one() == 0


def test_missing_or_wrong_dsn_fails_closed_without_fallback(database, private_data, monkeypatch):
    from app.config import get_settings
    v = private_data
    with api(database, v) as client:
        receipt = client.delete(f"/conversations/{v['conv']}").json()['id']
    main = database.url.render_as_string(hide_password=False)
    cases = (None, main, database.url.set(username=ROLE).render_as_string(hide_password=False))
    for value in cases:
        if value is None:
            monkeypatch.delenv('PRIVATE_STORAGE_DATABASE_URL', raising=False)
        else:
            monkeypatch.setenv('PRIVATE_STORAGE_DATABASE_URL', value)
        monkeypatch.setenv('DATABASE_URL', cases[2] if value == cases[2] else main)
        get_settings.cache_clear()
        dispose_private_storage_engine()
        with pytest.raises(PrivateStorageUnavailable):
            get_private_storage_session_factory()
    dispose_private_storage_engine()
    get_settings.cache_clear()
    with database.connect() as c:
        assert c.execute(text("select count(*) from private_deletion_tasks where state='pendente' and attempts=0")).scalar_one() == 2
    with api(database, v) as client:
        assert client.get(f'/igreja/private-deletions/{receipt}').json()['estado'] == 'pendente'


# --- Review findings: preexisting dependencies, live NOLOGIN, NULLs, search_path,
# --- rollback rehearsal. All against the real chain and the real login.

OTHER_DB = 'private_storage_other_test'


def _migration_sql():
    from scripts import migrate
    return migrate.strip_outer_transaction((migrate.MIGRATIONS_DIR / MIGRATION).read_text())


def _rollback_sql():
    """The migration's own commented rollback, uncommented, without BEGIN/COMMIT."""
    from scripts import migrate
    block = (migrate.MIGRATIONS_DIR / MIGRATION).read_text().split('-- BEGIN;\n', 1)[1].split('-- COMMIT;', 1)[0]
    return '\n'.join(line[3:] if line.startswith('-- ') else line[2:] for line in block.splitlines())


def _current_db_dependencies(c):
    return c.execute(text('''select count(*) from pg_shdepend d join pg_roles r on r.oid=d.refobjid
        where d.refclassid='pg_authid'::regclass and r.rolname=:r
         and d.dbid=(select oid from pg_database where datname=current_database())'''), dict(r=ROLE)).scalar_one()


@pytest.fixture(scope='module')
def other_database(migrated_database):
    """Another database of the cluster that depends on the role (grant on a table)."""
    url = migrated_database.url
    with migrated_database.connect().execution_options(isolation_level='AUTOCOMMIT') as c:
        c.exec_driver_sql(f'drop database if exists {OTHER_DB}')
        c.exec_driver_sql(f'create database {OTHER_DB}')
    other = create_engine(url.set(database=OTHER_DB))
    with other.begin() as c:
        c.exec_driver_sql('create table synthetic_other(id int)')
        c.exec_driver_sql(f'grant select on synthetic_other to {ROLE}')
    yield other
    other.dispose()
    with migrated_database.connect().execution_options(isolation_level='AUTOCOMMIT') as c:
        c.exec_driver_sql(f'drop database {OTHER_DB}')


@pytest.mark.parametrize('dependency', ('owned_table', 'direct_grant', 'default_acl', 'owned_database',
                                        'create_on_this_database', 'set_on_parameter', 'create_on_tablespace'))
def test_preexisting_role_with_objects_or_grants_is_refused(database, other_database, dependency):
    # Each case runs in one transaction that is rolled back: no order dependency.
    tamper = {
        'owned_table': f'create table public.synthetic_owned(id int); alter table public.synthetic_owned owner to {ROLE}',
        'direct_grant': f'grant select on public.messages to {ROLE}',
        'default_acl': f'alter default privileges in schema public grant select on tables to {ROLE}',
        'owned_database': f'alter database {OTHER_DB} owner to {ROLE}',
        # Shared ACLs (pg_shdepend dbid=0, deptype=a) that widen the identity here.
        'create_on_this_database': f'grant create on database {database.url.database} to {ROLE}',
        'set_on_parameter': f'grant set on parameter log_statement to {ROLE}',
        'create_on_tablespace': f'grant create on tablespace pg_default to {ROLE}',
    }[dependency]
    with database.connect() as c:
        tx = c.begin()
        try:
            # Back to the pre-migration state; the other database keeps the role.
            c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
            assert c.execute(text('select count(*) from pg_roles where rolname=:r'), dict(r=ROLE)).scalar_one() == 1
            assert _current_db_dependencies(c) == 0
            c.exec_driver_sql(tamper)
            with pytest.raises(DBAPIError) as error:
                c.exec_driver_sql(_migration_sql(), execution_options={'no_parameters': True})
            assert 'objetos ou privilégios' in str(error.value.orig)
        finally:
            tx.rollback()


def test_role_kept_by_another_database_is_accepted_and_its_grant_untouched(database, other_database):
    with database.connect() as c:
        tx = c.begin()
        try:
            c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
            # A shared grant on ANOTHER database belongs to it: accepted, never changed.
            c.exec_driver_sql(f'grant create on database {OTHER_DB} to {ROLE}')
            c.exec_driver_sql(_migration_sql(), execution_options={'no_parameters': True})
            assert _current_db_dependencies(c) > 0
            assert c.execute(text("select has_database_privilege(:r,:d,'CREATE')"), dict(r=ROLE, d=OTHER_DB)).scalar_one()
        finally:
            tx.rollback()
    with other_database.connect() as c:
        assert c.execute(text("select has_table_privilege(:r,'synthetic_other','SELECT')"), dict(r=ROLE)).scalar_one()


def test_rollback_guard_rehearsal_and_reapply(database, other_database, private_data, monkeypatch):
    import subprocess
    import sys
    from tests.private_storage_pg import private_storage_login
    from tests.test_uv_turmas_pg import ROOT
    v = private_data
    # A provisioned LOGIN aborts the rollback before any change.
    with database.begin() as c:
        c.exec_driver_sql(f'alter role {ROLE} login')
    try:
        with database.connect() as c:
            tx = c.begin()
            with pytest.raises(DBAPIError) as error:
                c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
            assert 'LOGIN provisionado' in str(error.value.orig)
            tx.rollback()
    finally:
        with database.begin() as c:
            c.exec_driver_sql(f'alter role {ROLE} nologin')
    with database.connect() as c:
        assert c.execute(text("select count(*) from pg_proc where proname='private_storage_due_tasks'")).scalar_one() == 1
    # Rollback for real: the previous contract is restored, nothing here depends on the role.
    with database.begin() as c:
        c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
    with database.connect() as c:
        check = lambda sql, **kw: c.execute(text(sql), kw).scalar_one()
        assert _current_db_dependencies(c) == 0
        assert check('select count(*) from pg_roles where rolname=:r', r=ROLE) == 1  # Kept by the other database.
        assert check("select count(*) from pg_proc where proname in ('private_storage_due_tasks','private_storage_begin_upload','private_storage_runtime_session')") == 0
        assert set(c.execute(text('''select polname from pg_policy where polrelid in
            ('private_deletion_tasks'::regclass,'private_deletion_uploads'::regclass)''')).scalars()) == {
            'task_admin_read', 'task_worker', 'upload_worker'}
        assert check("select has_column_privilege('authenticated','private_deletion_tasks','state','UPDATE')")
        assert check("select has_table_privilege('authenticated','private_deletion_uploads','INSERT')")
        assert check("select has_function_privilege('authenticated','private_deletion_task_path(uuid)','EXECUTE')")
        assert check('select count(*) from schema_migrations where name=:n', n=MIGRATION) == 0
    with other_database.connect() as c:  # Never dropped from here.
        assert c.execute(text("select has_table_privilege(:r,'synthetic_other','SELECT')"), dict(r=ROLE)).scalar_one()
    # Reapply through migrate.py: the identity contract returns and works.
    env = dict(os.environ, MIGRATION_DATABASE_URL=database.url.render_as_string(hide_password=False).replace('postgresql+psycopg2:', 'postgresql:'))
    result = subprocess.run([sys.executable, str(ROOT/'scripts/migrate.py'), 'apply', MIGRATION, '--yes'],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with database.connect() as c:
        assert not c.execute(text("select has_column_privilege('authenticated','private_deletion_tasks','state','UPDATE')")).scalar_one()
    with private_storage_login(database, monkeypatch) as runtime_factory:
        _delete_both_churches(database, v)
        with runtime_factory() as s:
            assert s.execute(text('select count(*) from private_storage_due_tasks(now(),500)')).scalar_one() == 3


def test_nologin_refuses_an_already_open_connection(database, private_data, runtime):
    v = private_data
    tasks = _delete_both_churches(database, v)
    raw = create_engine(os.environ['PRIVATE_STORAGE_DATABASE_URL'])
    try:
        with raw.connect() as c:
            c.execute(text('select 1')).scalar_one()
            c.commit()
            with runtime() as pooled:  # Open pooled connection before NOLOGIN.
                pooled.execute(text('select 1'))
                pooled.commit()
                with database.begin() as admin:
                    admin.exec_driver_sql(f'alter role {ROLE} nologin')
                try:
                    with pytest.raises(PrivateStorageScopeError):
                        pooled.execute(text('select 1'))  # Next BEGIN refuses.
                    pooled.rollback()
                    # Without the client probe the SQL checks refuse the open connection too.
                    with pytest.raises(DBAPIError) as error:
                        c.execute(text('select * from private_storage_due_tasks(now(),10)'))
                    assert REFUSED in str(error.value.orig)
                    c.rollback()
                    c.execute(text("select pg_catalog.set_config('app.tenant_igreja_id',:t,true)"), dict(t=str(v['tenant'])))
                    assert c.execute(text('update private_deletion_tasks set attempts=attempts+1 where id=:id'),
                                     dict(id=tasks[v['tenant']])).rowcount == 0
                    c.rollback()
                finally:
                    with database.begin() as admin:
                        admin.exec_driver_sql(f'alter role {ROLE} login')
    finally:
        raw.dispose()


@pytest.mark.parametrize('missing', ('source', 'conversation', 'generation'))
def test_begin_upload_refuses_null_identity_fields(database, private_data, runtime, missing):
    v = private_data
    params = dict(t=v['tenant'], s=uuid4(), c=v['conv'], g=0)
    params[{'source': 's', 'conversation': 'c', 'generation': 'g'}[missing]] = None
    with runtime() as s:
        scope_private_storage(s, v['tenant'])
        with pytest.raises(DBAPIError) as error:
            s.execute(text('select private_storage_begin_upload(:t,:s,:c,:g)'), params)
        assert _sqlstate(error) == '22004'
    with database.connect() as c:
        assert c.execute(text('select count(*) from private_deletion_uploads')).scalar_one() == 0


def test_search_path_is_fixed_against_url_role_schema_and_reuse(database, private_data, monkeypatch):
    from tests.private_storage_pg import private_storage_login
    v = private_data
    _delete_both_churches(database, v)
    with database.connect() as c:
        real_count = c.execute(text('select count(*) from private_deletion_tasks where igreja_id=:t'), dict(t=v['tenant'])).scalar_one()
    shadow = ROLE  # Same name as the role: first in the default "$user", public.
    with database.begin() as c:
        c.exec_driver_sql(f'create schema {shadow}')
        c.exec_driver_sql(f'create table {shadow}.private_deletion_tasks(id uuid, igreja_id uuid)')
        c.exec_driver_sql(f'''create function {shadow}.private_storage_due_tasks(timestamptz, integer)
            returns table(id uuid, igreja_id uuid, receipt_id uuid) language sql as
            $$ select gen_random_uuid(), gen_random_uuid(), gen_random_uuid() $$''')
        c.exec_driver_sql(f'''create function {shadow}.set_config(text, text, boolean) returns text
            language sql as $$ select 'shadowed' $$''')
        c.exec_driver_sql(f'grant usage on schema {shadow} to {ROLE}')
        c.exec_driver_sql(f'grant all on all tables in schema {shadow} to {ROLE}')
        c.exec_driver_sql(f'grant execute on all functions in schema {shadow} to {ROLE}')
    try:
        with private_storage_login(database, monkeypatch, url_options=f'-c search_path={shadow},public') as factory:
            with factory() as s:
                assert s.execute(text("select pg_catalog.current_setting('search_path')")).scalar_one() == 'pg_catalog, public, pg_temp'
                due = s.execute(text('select igreja_id from private_storage_due_tasks(now(),500)')).scalars().all()
                assert set(due) == {v['tenant'], v['other']}
                # Persist a hostile session-level path on this pooled connection.
                s.execute(text(f"select pg_catalog.set_config('search_path', '{shadow}, public', false)"))
                s.commit()
                scope_private_storage(s, v['tenant'])
                assert s.execute(text("select pg_catalog.current_setting('search_path')")).scalar_one() == 'pg_catalog, public, pg_temp'
                assert s.execute(text('select count(*) from private_deletion_tasks')).scalar_one() == real_count
    finally:
        with database.begin() as c:
            c.exec_driver_sql(f'drop schema {shadow} cascade')


def test_temp_table_with_the_same_name_never_shadows_public(database, private_data, runtime):
    v = private_data
    _delete_both_churches(database, v)
    with database.connect() as c:
        real_count = c.execute(text('select count(*) from private_deletion_tasks where igreja_id=:t'), dict(t=v['tenant'])).scalar_one()
    with runtime() as s:
        scope_private_storage(s, v['tenant'])
        # TEMP relations come first unless pg_temp is explicitly last in the path.
        s.execute(text('create temp table private_deletion_tasks(id uuid, igreja_id uuid) on commit preserve rows'))
        s.execute(text('create temp table private_deletion_uploads(igreja_id uuid, source_id uuid) on commit preserve rows'))
        pending = s.execute(text('select igreja_id, source_id from private_deletion_tasks limit 1')).one()
        s.execute(text('insert into pg_temp.private_deletion_uploads values(:t, :s)'), dict(t=pending[0], s=pending[1]))
        s.commit()
        assert s.execute(text('select count(*) from private_deletion_tasks')).scalar_one() == real_count
        assert s.execute(text("select count(*) from pg_temp.private_deletion_tasks")).scalar_one() == 0
        assert s.execute(text('select count(*) from private_storage_due_tasks(now(),500)')).scalar_one() == 3
