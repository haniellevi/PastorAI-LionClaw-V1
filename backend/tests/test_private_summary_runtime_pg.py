"""Real SQL identity of private summary generation on the full migration chain.

The dedicated login is a synthetic LOGIN granted only in this disposable PG.
Every refusal comes from the migration's real grants, policies and SECURITY
DEFINER checks; the cycle runs the real service with a fake provider only.
No SET ROLE stands in for the LOGIN.
"""
import logging
import os
import secrets
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.private_summary_session import (
    PrivateSummaryScopeError, dispose_private_summary_engine, get_private_summary_session_factory,
    scope_private_summary,
)
from tests.conftest_rls import assert_disposable_database
from tests.private_summary_pg import ROLE, private_summary_login
from tests.test_private_deletion_pg import api, private_data, scoped  # noqa: F401
from tests.test_private_summaries_pg import generate, get_summary, ready  # noqa: F401
from tests.test_uv_turmas_pg import ROOT, rls_database_url, migrated_database, database  # noqa: F401

pytestmark = pytest.mark.rls_integration
MIGRATION = '20261030_140000_private_summary_runtime_identity.sql'
REFUSED = 'Runtime de resumo privado obrigatório'
SCOPE = 'Igreja fora do escopo'
HELPERS = {
    'private_summary_runtime_session()': 'select private_summary_runtime_session()',
    'private_summary_runtime_due_tasks(text[],integer)': 'select * from private_summary_runtime_due_tasks(array[:ts],20)',
    'private_summary_runtime_snapshot(uuid,uuid)': 'select * from private_summary_runtime_snapshot(:t,:c)',
    'private_summary_runtime_sources(uuid,uuid)': 'select * from private_summary_runtime_sources(:t,:c)',
    'private_summary_runtime_requester(uuid,uuid)': 'select private_summary_runtime_requester(:t,:u)',
    'private_summary_runtime_credential(uuid)': 'select * from private_summary_runtime_credential(:t)',
    'private_summary_runtime_reserve(uuid)': 'select private_summary_runtime_reserve(:t)',
}
TENANT_HELPERS = tuple(sig for sig in HELPERS if '(uuid' in sig)
# Exactly the grants of the design: four private tables, minimal columns.
EXPECTED_TABLE_RIGHTS = {
    ('private_summary_settings', 'SELECT'), ('private_summary_tasks', 'SELECT'),
    ('private_conversation_summaries', 'SELECT'), ('private_summary_sources', 'SELECT'),
    ('private_summary_sources', 'INSERT'), ('private_summary_sources', 'DELETE'),
}
EXPECTED_COLUMN_RIGHTS = {
    ('private_summary_tasks', 'UPDATE'): {'state', 'started_at', 'error_code'},
    ('private_conversation_summaries', 'INSERT'): {
        'igreja_id', 'conversation_id', 'pessoa_id', 'source_revision', 'deletion_generation', 'state',
        'summary', 'human_correction'},
    ('private_conversation_summaries', 'UPDATE'): {
        'source_revision', 'deletion_generation', 'state', 'summary', 'version', 'updated_at'},
}
CENTRAL = ('messages', 'conversations', 'pessoas', 'llm_credentials', 'app_users', 'user_roles',
           'role_permissions', 'igrejas', 'private_summary_budget', 'private_erasure_requests',
           'private_deletion_receipts', 'private_deletion_sends', 'pedido_oracao_mensagem',
           'cell_report_audio_inputs')


def _sqlstate(error):
    return getattr(error.value.orig, 'pgcode', None)


def _migration_sql():
    from scripts import migrate
    return migrate.strip_outer_transaction((migrate.MIGRATIONS_DIR / MIGRATION).read_text())


def _rollback_sql():
    """The migration's own commented rollback, uncommented, without BEGIN/COMMIT."""
    from scripts import migrate
    block = (migrate.MIGRATIONS_DIR / MIGRATION).read_text().split('-- BEGIN;\n', 1)[1].split('-- COMMIT;', 1)[0]
    return '\n'.join(line[3:] if line.startswith('-- ') else line[2:] for line in block.splitlines())


def _count(database, table, tenant=None):
    with database.connect() as c:
        return c.execute(text(f'select count(*) from {table} where :t is null or igreja_id=:t'),
                         dict(t=tenant)).scalar_one()


def _task(database, tenant):
    with database.connect() as c:
        return c.execute(text('select state,error_code from private_summary_tasks where igreja_id=:t'),
                         dict(t=tenant)).one_or_none()


def _budget(database, tenant):
    with database.connect() as c:
        return c.execute(text('select coalesce(sum(reserved_microusd),0) from private_summary_budget where igreja_id=:t'),
                         dict(t=tenant)).scalar_one()


def _enqueue(database, v):
    from app.services import private_summaries as mem
    with scoped(database, v['tenant']) as s:
        job = mem.enqueue(s, v['tenant'], v['conv'])
        s.commit()
    assert job is not None
    return job


@contextmanager
def _main_login_spy(database):
    """Counts every statement the main login issues while the cycle runs."""
    statements = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)
    event.listen(database, 'before_cursor_execute', record)
    try:
        yield statements
    finally:
        event.remove(database, 'before_cursor_execute', record)


@pytest.fixture
def runtime(ready):
    return get_private_summary_session_factory()


@pytest.fixture
def church_b(database, ready):
    """Church B with its own queued task, summary and credential, written by the owner."""
    v = ready
    with database.begin() as c:
        c.execute(text("update pessoas set telefone='550000000003' where id=:person3"), v)
        c.execute(text("update conversations set telefone='550000000003' where id=:conv3"), v)
        c.execute(text("update messages set texto='Qual o horário do culto?',media_path=null where conversation_id=:conv3"), v)
        c.execute(text('insert into private_summary_settings(igreja_id,enabled,monthly_limit_microusd) values(:other,true,1000000)'), v)
        c.execute(text("""insert into llm_credentials(id,igreja_id,provedor,api_key_encrypted,modelo,validado,ativo)
            values(gen_random_uuid(),:other,'openai','synthetic','gpt-5.6-luna',true,true)"""), v)
        revision = c.execute(text('select private_summary_revision from conversations where id=:conv3'), v).scalar_one()
        c.execute(text("""insert into private_summary_tasks(igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation)
            values(:other,:conv3,:person3,:r,0)"""), dict(v, r=revision))
        c.execute(text("""insert into private_conversation_summaries
            (igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation,state,summary)
            values(:other,:conv3,:person3,:r,0,'available','Assunto operacional: horários dos cultos. Dúvida em aberto: qual o horário do culto.')"""),
            dict(v, r=revision))
        c.execute(text('''insert into private_summary_sources(igreja_id,conversation_id,message_id)
            select igreja_id,conversation_id,id from messages where conversation_id=:conv3'''), v)
    return v


# --- 1. Migration: minimal NOLOGIN identity, exact grants, old paths intact.

def test_migration_creates_minimal_nologin_identity(database):
    with database.connect() as c:
        check = lambda sql, **kw: c.execute(text(sql), kw).scalar_one()
        role = c.execute(text('''select rolcanlogin,rolinherit,rolsuper,rolbypassrls,rolcreatedb,
            rolcreaterole,rolreplication,rolpassword is null from pg_authid where rolname=:r'''), dict(r=ROLE)).one()
        assert tuple(role) == (False, False, False, False, False, False, False, True)
        assert check('select count(*) from pg_auth_members m join pg_roles r on r.oid=m.member or r.oid=m.roleid where r.rolname=:r', r=ROLE) == 0
        tables = set(c.execute(text('''select c.relname, p from pg_class c join pg_namespace n on n.oid=c.relnamespace
            cross join unnest(array['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) p
            where n.nspname='public' and c.relkind in ('r','v','m','p','S','f') and has_table_privilege(:r,c.oid,p)'''),
            dict(r=ROLE)).all())
        assert {tuple(t) for t in tables} == EXPECTED_TABLE_RIGHTS
        columns = {}
        for table, column, privilege in c.execute(text('''select c.relname, a.attname, p from pg_class c
            join pg_namespace n on n.oid=c.relnamespace join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
            cross join unnest(array['INSERT','UPDATE','REFERENCES']) p
            where n.nspname='public' and has_column_privilege(:r,c.oid,a.attnum,p)
             and not has_table_privilege(:r,c.oid,p)'''), dict(r=ROLE)):
            columns.setdefault((table, privilege), set()).add(column)
        assert columns == EXPECTED_COLUMN_RIGHTS
        for table in CENTRAL:
            assert not check("select has_any_column_privilege(:r,cast(:t as regclass),'SELECT')", r=ROLE, t=table), table
        # Beyond what PUBLIC gets, only the seven new functions.
        extra = set(c.execute(text('''select p.oid::regprocedure::text from pg_proc p join pg_namespace n on n.oid=p.pronamespace
            where n.nspname='public' and has_function_privilege(:r,p.oid,'EXECUTE')
             and not exists(select 1 from aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
                            where a.grantee=0 and a.privilege_type='EXECUTE')'''), dict(r=ROLE)).scalars())
        assert extra == set(HELPERS)
        for function in HELPERS:
            for other in ('anon', 'authenticated', 'service_role', 'private_send_runtime', 'private_storage_runtime'):
                assert not check("select has_function_privilege(:r,:f,'EXECUTE')", r=other, f=function), (other, function)
            config, secdef = c.execute(text('select proconfig, prosecdef from pg_proc where oid=cast(:f as regprocedure)'),
                                       dict(f=function)).one()
            if function == 'private_summary_runtime_session()':
                assert (config, secdef) == (['search_path=pg_catalog, public, pg_temp'], False)
            else:
                assert (config, secdef) == (['search_path=pg_catalog, public, pg_temp', 'row_security=off'], True)
        # Budget has no direct path: the reservation is the only function and has no cost argument.
        assert check("select count(*) from pg_proc where proname='private_summary_runtime_reserve'") == 1
        # Old authenticated grants and policies are untouched by this slice.
        for table in ('private_summary_settings', 'private_summary_budget', 'private_conversation_summaries',
                      'private_summary_sources', 'private_summary_tasks'):
            for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
                assert check("select has_table_privilege('authenticated',cast(:t as regclass),:p)", t=table, p=privilege)
            assert check('select relforcerowsecurity from pg_class where oid=cast(:t as regclass)', t=table)
            assert check("select count(*) from pg_policy where polname='summary_worker' and polrelid=cast(:t as regclass)", t=table) == 1
        for function in ('private_summary_enqueue(uuid)', 'private_summary_correct(uuid,bigint,text,boolean)'):
            assert check("select has_function_privilege('authenticated',:f,'EXECUTE')", f=function)
        runtime_policies = set(c.execute(text('''select c.relname::text||':'||p.polcmd::text from pg_policy p join pg_class c on c.oid=p.polrelid
            where p.polroles=array[(select oid from pg_roles where rolname=:r)]'''), dict(r=ROLE)).scalars())
        assert runtime_policies == {
            'private_summary_settings:r', 'private_summary_tasks:r', 'private_summary_tasks:w',
            'private_conversation_summaries:r', 'private_conversation_summaries:a', 'private_conversation_summaries:w',
            'private_summary_sources:r', 'private_summary_sources:a', 'private_summary_sources:d'}


@pytest.mark.parametrize('tamper', ('bypassrls', 'inherit', 'membership', 'direct_grant', 'default_acl'))
def test_unsafe_preexisting_role_is_refused(database, tamper):
    attribute = tamper in ('bypassrls', 'inherit', 'membership')
    with database.connect() as c:
        tx = c.begin()
        try:
            if not attribute:
                c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
                c.exec_driver_sql(f"do $$ begin if not exists(select 1 from pg_roles where rolname='{ROLE}') then "
                                  f"create role {ROLE} nologin noinherit; end if; end $$")
            c.exec_driver_sql({
                'bypassrls': f'alter role {ROLE} bypassrls', 'inherit': f'alter role {ROLE} inherit',
                'membership': f'grant authenticated to {ROLE}',
                'direct_grant': f'grant select on public.messages to {ROLE}',
                'default_acl': f'alter default privileges in schema public grant select on tables to {ROLE}',
            }[tamper])
            with pytest.raises(DBAPIError) as error:
                c.exec_driver_sql(_migration_sql(), execution_options={'no_parameters': True})
            assert ('atributos inseguros' if attribute else 'objetos ou privilégios') in str(error.value.orig)
        finally:
            tx.rollback()


# --- 2. The whole cycle on the dedicated login; the main login is never used.

def test_cycle_runs_only_on_the_dedicated_login(database, ready):
    from app.services import private_summaries as mem
    v = ready
    job = _enqueue(database, v)  # Python enqueue: requester NULL, still trusted.
    with database.connect() as c:
        assert c.execute(text('select requester_id from private_summary_tasks where id=:j'), dict(j=job)).scalar_one() is None
    calls = []
    with _main_login_spy(database) as statements:
        assert mem.process_tasks(provider=lambda **kw: calls.append(kw) or {'topic': 'uv'}) == 1
    assert statements == []
    assert len(calls) == 1 and calls[0]['topics'] == ('uv',) and calls[0]['credential'].igreja_id == v['tenant']
    assert set(calls[0]) == {'credential', 'topics'}
    assert _task(database, v['tenant']) == ('done', None)
    assert _budget(database, v['tenant']) == mem.RESERVATION_MICROUSD
    summary = get_summary(database, v)
    assert summary['summary'] == mem.TOPIC_TEXT['uv'] and summary['state'] == 'available'
    assert [s['message_id'] for s in summary['sources']] == [str(v['message'])]


def test_model_outside_allowlist_refuses_without_reservation(database, ready, monkeypatch):
    from app.services import private_summaries as mem
    v = ready
    # The DB CHECK admits the same three models; a narrowed allowlist (e.g. a
    # price change) must still refuse in Python before any reservation.
    monkeypatch.setattr(mem, 'MODEL_ALLOWLIST', frozenset({'gpt-5.6-sol'}))
    _enqueue(database, v)
    calls = []
    assert mem.process_tasks(provider=lambda **kw: calls.append(kw)) == 0
    assert calls == [] and _task(database, v['tenant']) == ('refused', 'budget_or_credential')
    assert _budget(database, v['tenant']) == 0


# --- 3. Two churches and tenant pinning.

def test_runtime_pinned_to_one_church_never_sees_or_locks_another(database, church_b, runtime):
    from app.services import private_summaries as mem
    v = church_b
    with runtime() as s:
        scope_private_summary(s, v['tenant'])
        for table in ('private_summary_tasks', 'private_conversation_summaries', 'private_summary_sources',
                      'private_summary_settings'):
            assert s.execute(text(f'select count(*) from {table} where igreja_id=:other'), v).scalar_one() == 0, table
        assert s.execute(text('select count(*) from private_summary_settings')).scalar_one() == 1
        assert s.execute(text('select id from private_summary_tasks where igreja_id=:other for update'), v).all() == []
        assert s.execute(text("update private_summary_tasks set state='refused' where igreja_id=:other"), v).rowcount == 0
        assert s.execute(text("update private_conversation_summaries set state='incorrect',summary=null where igreja_id=:other"), v).rowcount == 0
        assert s.execute(text('delete from private_summary_sources where igreja_id=:other'), v).rowcount == 0
        for sql in ("insert into private_conversation_summaries(igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation,state,summary) "
                    "values(:other,:conv3,:person3,0,0,'available','x')",
                    'insert into private_summary_sources(igreja_id,conversation_id,message_id) values(:other,:conv3,:message)'):
            with pytest.raises(DBAPIError) as error:
                s.execute(text(sql), v)
            assert _sqlstate(error) == '42501'
            s.rollback()
            scope_private_summary(s, v['tenant'])
        for signature in TENANT_HELPERS:
            with pytest.raises(DBAPIError) as error:  # Another church's id under this church's GUC.
                s.execute(text(HELPERS[signature]), dict(t=v['other'], c=v['conv3'], u=None))
            assert _sqlstate(error) == '42501' and SCOPE in str(error.value.orig), signature
            s.rollback()
            scope_private_summary(s, v['tenant'])
    with runtime() as s:  # Unpinned: no tenant GUC, every tenant helper refuses.
        for signature in TENANT_HELPERS:
            with pytest.raises(DBAPIError) as error:
                s.execute(text(HELPERS[signature]), dict(t=v['tenant'], c=v['conv'], u=None))
            assert _sqlstate(error) == '42501' and SCOPE in str(error.value.orig), signature
            s.rollback()
        assert s.execute(text('select count(*) from private_summary_tasks')).scalar_one() == 0
        # Discovery is the only cross-church read: ids only, approved list only.
        rows = s.execute(text('select * from private_summary_runtime_due_tasks(array[:a,:b],20)'),
                         dict(a=str(v['tenant']), b=str(v['other']))).mappings().all()
        assert {r['igreja_id'] for r in rows} == {v['other']} and set(rows[0]) == {'igreja_id', 'id', 'conversation_id'}
        assert s.execute(text('select count(*) from private_summary_runtime_due_tasks(array[:a],20)'),
                         dict(a=str(v['tenant']))).scalar_one() == 0
        for params in (dict(a=[], n=20), dict(a=None, n=20), dict(a=[str(v['tenant'])], n=0), dict(a=[str(v['tenant'])], n=101)):
            with pytest.raises(DBAPIError) as error:
                s.execute(text('select * from private_summary_runtime_due_tasks(cast(:a as text[]),:n)'), params)
            assert _sqlstate(error) == '22023'
            s.rollback()
    _enqueue(database, v)
    assert mem.process_tasks(provider=lambda **kw: {'topic': 'uv'}) == 1  # Only church A is approved.
    assert _task(database, v['other']) == ('queued', None)
    with database.connect() as c:
        assert c.execute(text('select summary from private_conversation_summaries where igreja_id=:other'), v).scalar_one().startswith('Assunto operacional: horários')


# --- 4. Negative privileges of the dedicated login.

def test_runtime_has_no_path_to_central_tables_budget_or_old_functions(database, church_b, runtime):
    v = church_b
    generate(database, v)
    with database.begin() as c:
        c.execute(text("update private_summary_tasks set state='refused',error_code='provider_outcome_unknown' where igreja_id=:tenant"), v)
    denied = [
        'select count(*) from messages', 'select count(*) from conversations', 'select count(*) from llm_credentials',
        'select count(*) from app_users', 'select count(*) from pessoas', 'select count(*) from private_summary_budget',
        'select count(*) from private_erasure_requests',
        'update private_summary_budget set reserved_microusd=0',
        "insert into private_summary_budget(igreja_id,month,reserved_microusd) values(:tenant,date_trunc('month',now())::date,0)",
        'delete from private_summary_budget',
        'update private_summary_settings set monthly_limit_microusd=999999999',
        'insert into private_summary_tasks(igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation) values(:tenant,:conv,:person,99,0)',
        'update private_summary_tasks set requester_id=null', 'update private_summary_tasks set source_revision=source_revision+1',
        'delete from private_summary_tasks',
        "update private_conversation_summaries set human_correction='Qual o horário do culto?'",
        'update private_conversation_summaries set pessoa_id=:person2', 'delete from private_conversation_summaries',
        'select private_summary_enqueue(:conv)', "select private_summary_correct(:conv,1,'Qual o horário do culto?',false)",
        'select private_summary_origin_valid(:tenant,:conv,:person)',
        "select private_erasure_request(:tenant,:person,:conv,:message)", "select private_delete_content(:tenant,'conversa',:conv,:conv)",
        'select private_send_release(:tenant,:message)', 'select * from private_storage_due_tasks(now(),10)',
        'select current_igreja_id()', 'set role authenticated', 'set role postgres',
    ]
    with runtime() as s:
        scope_private_summary(s, v['tenant'])
        for sql in denied:
            with pytest.raises(DBAPIError) as error:
                s.execute(text(sql), v)
            assert _sqlstate(error) == '42501', (sql, _sqlstate(error))
            s.rollback()
            scope_private_summary(s, v['tenant'])
        # An abandoned or refused task can never be re-queued nor reopened by this login.
        for target in ('queued', 'running', 'done'):
            try:
                rows = s.execute(text('update private_summary_tasks set state=:s,error_code=null where igreja_id=:t'),
                                 dict(s=target, t=v['tenant'])).rowcount
                assert rows == 0, target
            except DBAPIError as exc:
                assert getattr(exc.orig, 'pgcode', None) == '42501'
            s.rollback()
            scope_private_summary(s, v['tenant'])
    with database.begin() as c:
        c.execute(text("update private_summary_tasks set state='running',error_code=null,started_at=now() where igreja_id=:tenant"), v)
    with runtime() as s:
        scope_private_summary(s, v['tenant'])
        with pytest.raises(DBAPIError) as error:
            s.execute(text("update private_summary_tasks set state='queued' where igreja_id=:tenant"), v)
        assert _sqlstate(error) == '42501'
    assert _task(database, v['tenant']) == ('running', None)
    assert _budget(database, v['tenant']) == 100_000


def test_owner_set_role_and_other_logins_cannot_use_the_helpers(database, church_b, monkeypatch):
    from tests.private_send_pg import private_send_login
    v = church_b
    params = dict(t=v['tenant'], c=v['conv'], u=None, ts=str(v['tenant']))
    for set_role in (False, True):
        for signature, sql in HELPERS.items():
            if signature == 'private_summary_runtime_session()':
                continue
            with database.connect() as c, c.begin():
                c.execute(text("select set_config('app.tenant_igreja_id',:t,true)"), dict(t=str(v['tenant'])))
                if set_role:
                    c.exec_driver_sql(f'set local role {ROLE}')
                with pytest.raises(DBAPIError) as error:
                    c.execute(text(sql), params)
                assert REFUSED in str(error.value.orig), (signature, set_role)
    with private_send_login(database, monkeypatch) as send:  # Another dedicated login: no EXECUTE.
        with send() as s:
            for signature, sql in HELPERS.items():
                with pytest.raises(DBAPIError) as error:
                    s.execute(text(sql), params)
                assert _sqlstate(error) == '42501', signature
                s.rollback()
    password = secrets.token_urlsafe(24)
    with database.begin() as c:  # A login granted EXECUTE and authenticated membership still fails the check.
        c.exec_driver_sql(f"create role synthetic_summary_worker login password '{password}' noinherit")
        c.exec_driver_sql('grant authenticated to synthetic_summary_worker')
        c.exec_driver_sql('grant usage on schema public to synthetic_summary_worker')
        for signature in HELPERS:
            c.exec_driver_sql(f'grant execute on function public.{signature} to synthetic_summary_worker')
    other = create_engine(database.url.set(username='synthetic_summary_worker', password=password))
    try:
        for signature, sql in HELPERS.items():
            if signature == 'private_summary_runtime_session()':
                with other.connect() as c:
                    assert c.execute(text(sql)).scalar_one() is False
                continue
            with other.connect() as c, c.begin():
                c.execute(text("select set_config('app.tenant_igreja_id',:t,true)"), dict(t=str(v['tenant'])))
                with pytest.raises(DBAPIError) as error:
                    c.execute(text(sql), params)
                assert REFUSED in str(error.value.orig), signature
    finally:
        other.dispose()
        with database.begin() as c:
            c.exec_driver_sql('drop owned by synthetic_summary_worker')
            c.exec_driver_sql('drop role synthetic_summary_worker')
    assert _budget(database, v['tenant']) == 0 and _task(database, v['other']) == ('queued', None)


# --- 5. Identity changed between the claim and the publication.

@pytest.mark.parametrize('change', ('nologin', 'bypassrls', 'membership'))
def test_identity_changed_during_http_refuses_publication_without_new_call(database, ready, caplog, change):
    from app.services import private_summaries as mem
    v = ready
    _enqueue(database, v)
    alter = {'nologin': f'alter role {ROLE} nologin', 'bypassrls': f'alter role {ROLE} bypassrls',
             'membership': f'grant authenticated to {ROLE}'}[change]
    restore = {'nologin': f'alter role {ROLE} login', 'bypassrls': f'alter role {ROLE} nobypassrls',
               'membership': f'revoke authenticated from {ROLE}'}[change]
    calls = []

    def external(**kw):
        calls.append(kw)
        with database.begin() as c:
            c.exec_driver_sql(alter)
        return {'topic': 'uv'}
    try:
        with caplog.at_level(logging.WARNING, logger='app.services.private_summaries'):
            assert mem.process_tasks(provider=external) == 0
    finally:
        with database.begin() as c:
            c.exec_driver_sql(restore)
    assert len(calls) == 1
    assert [r.event for r in caplog.records] == ['private_summary_runtime_unavailable']
    assert caplog.records[0].error_type == 'PrivateSummaryScopeError'
    assert _task(database, v['tenant']) == ('running', None)
    assert _count(database, 'private_conversation_summaries', v['tenant']) == 0
    assert _budget(database, v['tenant']) == mem.RESERVATION_MICROUSD  # Never refunded.
    dispose_private_summary_engine()
    assert mem.process_tasks(provider=lambda **kw: calls.append(kw)) == 0  # Not yet abandoned.
    with database.begin() as c:
        c.execute(text("update private_summary_tasks set started_at=now()-interval '5 minutes' where igreja_id=:tenant"), v)
    assert mem.process_tasks(provider=lambda **kw: calls.append(kw)) == 0
    assert len(calls) == 1 and _task(database, v['tenant']) == ('refused', 'provider_outcome_unknown')
    assert _budget(database, v['tenant']) == mem.RESERVATION_MICROUSD


def test_identity_is_reproven_every_transaction(database, ready, runtime):
    v = ready
    with runtime() as s:
        scope_private_summary(s, v['tenant'])
        assert s.execute(text('select private_summary_runtime_session()')).scalar_one()
        s.commit()
        assert s.execute(text("select current_setting('app.tenant_igreja_id', true)")).scalar_one() == str(v['tenant'])
        with pytest.raises(PrivateSummaryScopeError):
            scope_private_summary(s, v['other'])
    with runtime() as s:  # A persisted tenant GUC never reaches the next checkout.
        leaked = s.execute(text("select pg_backend_pid() from (select set_config('app.tenant_igreja_id', :t, false)) g"),
                           dict(t=str(v['tenant']))).scalar_one()
        s.commit()
    with runtime() as s:
        assert s.execute(text('select pg_backend_pid()')).scalar_one() != leaked
        assert s.execute(text("select current_setting('app.tenant_igreja_id', true)")).scalar_one() in (None, '')
    with database.begin() as c:
        c.exec_driver_sql(f'alter role {ROLE} createdb')
    raw = create_engine(os.environ['PRIVATE_SUMMARY_DATABASE_URL'])
    try:
        with runtime() as s, pytest.raises(PrivateSummaryScopeError):
            s.execute(text('select 1'))  # The client probe refuses at BEGIN.
        with raw.connect() as c, c.begin():  # Without the client probe, SQL refuses too.
            c.execute(text("select set_config('app.tenant_igreja_id',:t,true)"), dict(t=str(v['tenant'])))
            with pytest.raises(DBAPIError) as error:
                c.execute(text('select private_summary_runtime_reserve(:t)'), dict(t=v['tenant']))
            assert REFUSED in str(error.value.orig)
        with raw.connect() as c, c.begin():  # Table policies need the live session check too, not only the GUC.
            c.execute(text("select set_config('app.tenant_igreja_id',:t,true)"), dict(t=str(v['tenant'])))
            assert c.execute(text('select count(*) from private_summary_settings')).scalar_one() == 0
    finally:
        raw.dispose()
        with database.begin() as c:
            c.exec_driver_sql(f'alter role {ROLE} nocreatedb')
    assert _budget(database, v['tenant']) == 0


def test_search_path_is_fixed_against_url_and_role_schema(database, ready, monkeypatch):
    from app.services import private_summaries as mem
    v = ready
    shadow = ROLE  # First in the default "$user", public.
    with database.begin() as c:
        c.exec_driver_sql(f'create schema {shadow}')
        c.exec_driver_sql(f'''create function {shadow}.private_summary_runtime_reserve(uuid) returns boolean
            language sql as $$ select true $$''')
        c.exec_driver_sql(f'grant usage on schema {shadow} to {ROLE}')
        c.exec_driver_sql(f'grant execute on all functions in schema {shadow} to {ROLE}')
        c.exec_driver_sql('update private_summary_settings set monthly_limit_microusd=1')
    try:
        with private_summary_login(database, monkeypatch, url_options=f'-c search_path={shadow},public'):
            _enqueue(database, v)
            calls = []
            assert mem.process_tasks(provider=lambda **kw: calls.append(kw)) == 0
            assert calls == [] and _task(database, v['tenant']) == ('refused', 'budget_or_credential')
    finally:
        with database.begin() as c:
            c.exec_driver_sql(f'drop schema {shadow} cascade')


# --- 6. Changes during the provider call (gate, erasure request, opt-out).

@pytest.mark.parametrize('change', (
    'update private_summary_settings set enabled=false where igreja_id=:tenant',
    'update private_summary_settings set monthly_limit_microusd=0 where igreja_id=:tenant',
    "insert into private_erasure_requests(igreja_id,pessoa_id,conversation_id,inbound_id) values(:tenant,:person,:conv,:message)",
    'update pessoas set optout=true where id=:person',
    "update llm_credentials set modelo='gpt-5.6-terra' where igreja_id=:tenant",
))
def test_change_during_provider_is_never_published(database, ready, change):
    from app.services import private_summaries as mem
    v = ready
    _enqueue(database, v)
    calls = []

    def external(**kw):
        calls.append(kw)
        with database.begin() as c:
            c.execute(text(change), v)
        return {'topic': 'uv'}
    assert mem.process_tasks(provider=external) == 0
    assert len(calls) == 1
    assert _count(database, 'private_conversation_summaries', v['tenant']) == 0
    assert _budget(database, v['tenant']) == mem.RESERVATION_MICROUSD
    task = _task(database, v['tenant'])
    assert task is None or task == ('refused', 'origin_changed')  # Opt-out trigger removes the task.


def test_pending_erasure_request_refuses_claim_before_provider(database, ready):
    from app.services import private_summaries as mem
    v = ready
    _enqueue(database, v)
    with database.begin() as c:
        c.execute(text("insert into private_erasure_requests(igreja_id,pessoa_id,conversation_id,inbound_id) values(:tenant,:person,:conv,:message)"), v)
    calls = []
    assert mem.process_tasks(provider=lambda **kw: calls.append(kw)) == 0
    assert calls == [] and _task(database, v['tenant']) == ('refused', 'origin_invalid') and _budget(database, v['tenant']) == 0


# --- 7. Locks: barrier and conversation lock held until COMMIT of the dedicated TX.

def _blocked(database, sql, params):
    """Run ``sql`` on the main login with a short lock_timeout; True when it waits."""
    with database.connect() as c:
        tx = c.begin()
        try:
            c.exec_driver_sql("set local lock_timeout='300ms'")
            c.execute(text(sql), params)
        except DBAPIError as exc:
            if getattr(exc.orig, 'pgcode', None) == '55P03':
                return True
            raise
        finally:
            tx.rollback()  # A probe never commits.
        return False


def test_snapshot_lock_and_barrier_persist_until_commit(database, ready, runtime):
    v = ready
    _enqueue(database, v)
    contenders = (
        ('select id from conversations where igreja_id=:tenant and id=:conv for update', v),
        ("insert into messages(id,igreja_id,conversation_id,direcao,autor,texto) values(gen_random_uuid(),:tenant,:conv,'in','contato','Qual o horário do culto?')", v),
        ("select private_delete_content(:tenant,'conversa',:conv,:conv)", v),
    )
    with runtime() as s:
        scope_private_summary(s, v['tenant'])
        row = s.execute(text('select * from private_summary_runtime_snapshot(:t,:c)'), dict(t=v['tenant'], c=v['conv'])).mappings().one()
        assert set(row) == {'id', 'pessoa_id', 'private_summary_revision', 'deletion_generation'} and row['id'] == v['conv']
        for sql, params in contenders:
            assert _blocked(database, sql, params), sql
        # Another church is never serialized by this lock.
        assert not _blocked(database, 'select id from conversations where igreja_id=:other for update', v)
        s.commit()
    with runtime() as s:  # Same through the sources projection alone, and it returns no text.
        scope_private_summary(s, v['tenant'])
        rows = s.execute(text('select * from private_summary_runtime_sources(:t,:c)'), dict(t=v['tenant'], c=v['conv'])).mappings().all()
        assert [dict(r) for r in rows] == [dict(message_id=v['message'], topic='uv')]
        assert _blocked(database, *contenders[0])
        s.rollback()
    assert not _blocked(database, *contenders[0])


def test_deletion_and_ingestion_serialize_with_claim_and_publication(database, ready):
    """Real cycle: a contender started during each locked phase waits for it."""
    from app.services import private_summaries as mem
    v = ready
    _enqueue(database, v)
    observed = {}
    from app.services import private_summaries as module
    original = module._runtime_snapshot

    def snapshot_then_probe(db, tenant, conversation):
        result = original(db, tenant, conversation)
        phase = 'claim' if 'claim' not in observed else 'publish'
        observed[phase] = [_blocked(database, "select private_delete_content(:tenant,'conversa',:conv,:conv)", v),
                           _blocked(database, "insert into messages(id,igreja_id,conversation_id,direcao,autor,texto) values(gen_random_uuid(),:tenant,:conv,'in','contato','Qual o horário do culto?')", v),
                           _blocked(database, 'select id from conversations where igreja_id=:tenant and id=:conv for update', v)]
        return result
    monkey = pytest.MonkeyPatch()
    monkey.setattr(module, '_runtime_snapshot', snapshot_then_probe)
    try:
        assert mem.process_tasks(provider=lambda **kw: {'topic': 'uv'}) == 1
    finally:
        monkey.undo()
    assert observed == {'claim': [True, True, True], 'publish': [True, True, True]}
    assert get_summary(database, v)['state'] == 'available'


def test_concurrent_reservations_are_atomic_fixed_and_not_resettable(database, ready, runtime):
    from app.services import private_summaries as mem
    v = ready
    with database.begin() as c:
        c.execute(text('update private_summary_settings set monthly_limit_microusd=:l'), dict(l=mem.RESERVATION_MICROUSD))
    barrier = threading.Barrier(2)

    def reserve():
        with runtime() as s:
            scope_private_summary(s, v['tenant'])
            barrier.wait()
            result = s.execute(text('select private_summary_runtime_reserve(:t)'), dict(t=v['tenant'])).scalar_one()
            s.commit()
            return result
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(lambda _: reserve(), range(2))) == [False, True]
    assert _budget(database, v['tenant']) == 100_000
    with database.begin() as c:
        c.execute(text('update private_summary_settings set monthly_limit_microusd=250000'))
    with runtime() as s:
        scope_private_summary(s, v['tenant'])
        assert s.execute(text('select private_summary_runtime_reserve(:t)'), dict(t=v['tenant'])).scalar_one() is True
        assert s.execute(text('select private_summary_runtime_reserve(:t)'), dict(t=v['tenant'])).scalar_one() is False
        s.commit()
    assert _budget(database, v['tenant']) == 200_000  # Fixed 100,000 each, never parameterized.
    with database.begin() as c:
        c.execute(text('update private_summary_settings set enabled=false'))
    with runtime() as s:
        scope_private_summary(s, v['tenant'])
        assert s.execute(text('select private_summary_runtime_reserve(:t)'), dict(t=v['tenant'])).scalar_one() is False


def test_replay_and_concurrent_workers_call_the_provider_once(database, ready):
    from app.services import private_summaries as mem
    v = ready
    _enqueue(database, v)
    calls = []
    lock = threading.Lock()

    def provider(**kw):
        with lock:
            calls.append(kw)
        return {'topic': 'uv'}
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: mem.process_tasks(provider=provider), range(2)))
    assert sorted(results) == [0, 1]
    assert len(calls) == 1
    assert mem.process_tasks(provider=provider) == 0 and len(calls) == 1
    assert _budget(database, v['tenant']) == mem.RESERVATION_MICROUSD


def test_projections_refuse_invalid_origin_and_never_return_text(database, ready, runtime):
    """Called out of order, the projections still validate the whole origin."""
    v = ready  # conv2 keeps free text and a media path: never a valid origin.
    with runtime() as s:
        scope_private_summary(s, v['tenant'])
        assert s.execute(text('select * from private_summary_runtime_snapshot(:t,:c)'), dict(t=v['tenant'], c=v['conv2'])).all() == []
        with pytest.raises(DBAPIError) as error:
            s.execute(text('select * from private_summary_runtime_sources(:t,:c)'), dict(t=v['tenant'], c=v['conv2']))
        assert _sqlstate(error) == '55000' and 'Synthetic private text' not in str(error.value.orig)
        s.rollback()
        scope_private_summary(s, v['tenant'])
        rows = s.execute(text('select * from private_summary_runtime_sources(:t,:c)'), dict(t=v['tenant'], c=v['conv'])).mappings().all()
        assert [dict(r) for r in rows] == [dict(message_id=v['message'], topic='uv')]
        assert s.execute(text('select * from private_summary_runtime_credential(:t)'), dict(t=v['tenant'])).mappings().one()['modelo'] == 'gpt-5.6-luna'


# --- 8. FKs without central grants.

def test_foreign_keys_hold_without_central_grants(database, church_b, runtime):
    v = church_b
    generate(database, v)
    with database.connect() as c:
        foreign = c.execute(text('select id from messages where conversation_id=:conv3'), v).scalar_one()
        other_thread = c.execute(text('select id from messages where conversation_id=:conv2'), v).scalar_one()
    with runtime() as s:
        scope_private_summary(s, v['tenant'])
        assert s.execute(text('delete from private_summary_sources where igreja_id=:tenant and conversation_id=:conv'), v).rowcount == 1
        s.execute(text('insert into private_summary_sources(igreja_id,conversation_id,message_id) values(:tenant,:conv,:message)'), v)
        for message in (other_thread, uuid4()):
            with pytest.raises(IntegrityError) as error:  # Composite FK, checked without grants on messages.
                s.execute(text('insert into private_summary_sources(igreja_id,conversation_id,message_id) values(:tenant,:conv,:m)'), dict(v, m=message))
            assert _sqlstate(error) == '23503'
            s.rollback()
            scope_private_summary(s, v['tenant'])
        with pytest.raises(DBAPIError) as error:  # Another church's message: policy refuses first.
            s.execute(text('insert into private_summary_sources(igreja_id,conversation_id,message_id) values(:other,:conv3,:m)'), dict(v, m=foreign))
        assert _sqlstate(error) == '42501'
        s.rollback()
        scope_private_summary(s, v['tenant'])
        with pytest.raises(IntegrityError) as error:  # Summary for a conversation of another person: FK on (igreja, pessoa).
            s.execute(text("""insert into private_conversation_summaries(igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation,state,summary)
                values(:tenant,:conv2,:person3,0,0,'available','x')"""), v)
        assert _sqlstate(error) == '23503'
    assert get_summary(database, v)['state'] == 'available'


# --- 9. Rollback rehearsal and reapply through migrate.py.

OTHER_DB = 'private_summary_other_test'


def test_rollback_guard_rehearsal_and_reapply(database, ready, monkeypatch):
    from app.services import private_summaries as mem
    from scripts import release_preflight
    v = ready
    generate(database, v)
    dispose_private_summary_engine()
    with database.connect() as c:  # LOGIN still provisioned by the fixture: rollback refuses.
        tx = c.begin()
        with pytest.raises(DBAPIError) as error:
            c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
        assert 'LOGIN provisionado' in str(error.value.orig)
        tx.rollback()
    with database.begin() as c:
        c.exec_driver_sql(f'alter role {ROLE} nologin password null')
        acl_before = c.execute(text('''select relname, relacl::text from pg_class where relname in
            ('private_summary_settings','private_summary_tasks','private_conversation_summaries','private_summary_sources','private_summary_budget')
            order by 1''')).all()
    url = database.url
    env = dict(os.environ, MIGRATION_DATABASE_URL=url.render_as_string(hide_password=False).replace('postgresql+psycopg2:', 'postgresql:'))
    with database.connect().execution_options(isolation_level='AUTOCOMMIT') as c:
        c.exec_driver_sql(f'drop database if exists {OTHER_DB}')
        c.exec_driver_sql(f'create database {OTHER_DB}')
    other = create_engine(url.set(database=OTHER_DB))
    try:
        with other.begin() as c:
            c.exec_driver_sql('create table synthetic_other(id int)')
            c.exec_driver_sql(f'grant select on synthetic_other to {ROLE}')
        with database.begin() as c:
            c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
        with database.connect() as c:
            check = lambda sql, **kw: c.execute(text(sql), kw).scalar_one()
            assert check('select count(*) from pg_roles where rolname=:r', r=ROLE) == 1  # Kept by the other database.
            assert check("select count(*) from pg_proc where proname like 'private_summary_runtime%'") == 0
            assert check('select count(*) from pg_policy p where cast(:r as regrole) = any(p.polroles)', r=ROLE) == 0
            assert check('''select count(*) from pg_shdepend d join pg_roles r on r.oid=d.refobjid where r.rolname=:r
                and d.dbid=(select oid from pg_database where datname=current_database())''', r=ROLE) == 0
            for table in ('private_summary_settings', 'private_summary_tasks', 'private_conversation_summaries', 'private_summary_sources'):
                assert not check("select has_any_column_privilege(:r,cast(:t as regclass),'SELECT')", r=ROLE, t=table)
                assert check("select has_table_privilege('authenticated',cast(:t as regclass),'UPDATE')", t=table)
            assert check('select count(*) from schema_migrations where name=:n', n=MIGRATION) == 0
            assert check('select count(*) from private_conversation_summaries') == 1  # Data preserved.
            assert check('select reserved_microusd from private_summary_budget') == mem.RESERVATION_MICROUSD
        # Absent contracts after rollback are unverified, never findings.
        import psycopg2
        connection = psycopg2.connect(url.set(drivername='postgresql').render_as_string(hide_password=False))
        try:
            report = release_preflight.inspect_connection(connection)
        finally:
            connection.rollback()
            connection.close()
        new = tuple(s for s, _ in release_preflight.PRIVATE_DEFINER_CONTRACTS if 'private_summary_runtime' in s)
        assert len(new) == 3 and set(new) <= set(report.definer_unverified) and report.definer_findings == ()
        with other.connect() as c:
            assert c.execute(text("select has_table_privilege(:r,'synthetic_other','SELECT')"), dict(r=ROLE)).scalar_one()
        result = subprocess.run([sys.executable, str(ROOT/'scripts/migrate.py'), 'apply', MIGRATION, '--yes'],
                                env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    finally:
        other.dispose()
        with database.connect().execution_options(isolation_level='AUTOCOMMIT') as c:
            c.exec_driver_sql(f'drop database if exists {OTHER_DB}')
        with database.connect() as c:
            applied = c.execute(text('select count(*) from schema_migrations where name=:n'), dict(n=MIGRATION)).scalar_one()
        if not applied:  # A failure mid-rehearsal never leaves later tests on the rolled-back schema.
            subprocess.run([sys.executable, str(ROOT/'scripts/migrate.py'), 'apply', MIGRATION, '--yes'],
                           env=env, capture_output=True, text=True)
    with database.connect() as c:
        assert c.execute(text('select count(*) from schema_migrations where name=:n'), dict(n=MIGRATION)).scalar_one() == 1
        assert c.execute(text('''select relname, relacl::text from pg_class where relname in
            ('private_summary_settings','private_summary_tasks','private_conversation_summaries','private_summary_sources','private_summary_budget')
            order by 1''')).all() == acl_before
    with database.begin() as c:
        c.execute(text("insert into messages(id,igreja_id,conversation_id,direcao,autor,texto) values(gen_random_uuid(),:tenant,:conv,'in','contato','Qual o horário do culto?')"), v)
    with private_summary_login(database, monkeypatch):
        assert len(generate(database, v)) == 1
    assert get_summary(database, v)['state'] == 'available'


# --- 10. Owner without BYPASSRLS: which helpers truly depend on bypass over FORCE RLS.

# Tables each helper body reads directly. Nested SECURITY DEFINER functions
# (origin_valid, current_igreja_id) keep their original owner.
HELPER_TABLES = {
    'private_summary_runtime_due_tasks(text[],integer)': ('private_summary_tasks',),
    'private_summary_runtime_snapshot(uuid,uuid)': ('conversations',),
    'private_summary_runtime_sources(uuid,uuid)': ('conversations', 'messages'),
    'private_summary_runtime_requester(uuid,uuid)': ('app_users', 'user_roles', 'pessoas', 'role_permissions'),
    'private_summary_runtime_credential(uuid)': ('llm_credentials',),
    'private_summary_runtime_reserve(uuid)': ('private_summary_settings', 'private_summary_budget'),
}
NESTED = ('private_summary_runtime_session()', 'private_summary_origin_valid(uuid,uuid,uuid)',
          'private_summary_topic(text)')


@contextmanager
def _synthetic_owner(database, function, tables):
    """A fresh NOLOGIN NOBYPASSRLS role owns ``function`` AND every table its body reads.

    As table owner it legitimately reads tables without FORCE; only FORCE RLS
    can still refuse it. Owners and ACLs are restored exactly afterwards.
    """
    assert_disposable_database(database.url.render_as_string(hide_password=False))
    role = f'psr_owner_{secrets.token_hex(5)}'
    with database.connect() as c:
        before = c.execute(text('''select c.oid::regclass::text, c.relowner, c.relacl::text from pg_class c
            where c.oid = any(cast(:t as regclass[])) order by 1'''), dict(t=list(tables))).all()
        function_before = c.execute(text('select proowner, proacl::text from pg_proc where oid=cast(:f as regprocedure)'),
                                    dict(f=function)).one()
    with database.begin() as c:
        c.exec_driver_sql(f'create role {role} nologin noinherit nosuperuser nobypassrls nocreatedb nocreaterole noreplication')
        c.exec_driver_sql(f'grant usage on schema public to {role}')
        for nested in NESTED:
            c.exec_driver_sql(f'grant execute on function public.{nested} to {role}')
        for table in tables:
            c.exec_driver_sql(f'alter table public.{table} owner to {role}')
        c.exec_driver_sql(f'alter function public.{function} owner to {role}')

    def set_bypass(bypass):
        with database.begin() as c:
            c.exec_driver_sql(f"alter role {role} {'bypassrls' if bypass else 'nobypassrls'}")
        database.dispose()
        dispose_private_summary_engine()  # Fresh sessions: no plan cached under the old attribute.
    try:
        yield set_bypass
    finally:
        with database.begin() as c:
            c.exec_driver_sql(f'alter function public.{function} owner to postgres')
            for table in tables:
                c.exec_driver_sql(f'alter table public.{table} owner to postgres')
            c.exec_driver_sql(f'drop owned by {role}')
            c.exec_driver_sql(f'drop role {role}')
        with database.connect() as c:
            assert c.execute(text('''select c.oid::regclass::text, c.relowner, c.relacl::text from pg_class c
                where c.oid = any(cast(:t as regclass[])) order by 1'''), dict(t=list(tables))).all() == before
            assert c.execute(text('select proowner, proacl::text from pg_proc where oid=cast(:f as regprocedure)'),
                             dict(f=function)).one() == function_before


def _call(runtime, v, signature):
    with runtime() as s:
        if 'due_tasks' not in signature:
            scope_private_summary(s, v['tenant'])
        try:
            rows = [tuple(r) for r in s.execute(text(HELPERS[signature]),
                                                 dict(t=v['tenant'], c=v['conv'], u=v['admin'], ts=str(v['tenant']))).all()]
        except DBAPIError as exc:
            return ('error', getattr(exc.orig, 'pgcode', None), str(exc.orig).splitlines()[0])
        finally:
            s.rollback()
    return ('ok', [tuple(str(x) for x in row) for row in rows])


@pytest.mark.parametrize('signature', tuple(HELPER_TABLES))
def test_owner_without_bypass_fails_only_where_force_rls_is_read(database, ready, signature):
    from scripts import release_preflight
    v = ready
    _enqueue(database, v)
    runtime = get_private_summary_session_factory()
    tables = HELPER_TABLES[signature]
    with database.connect() as c:
        forced = c.execute(text('select bool_or(relforcerowsecurity) from pg_class where oid = any(cast(:t as regclass[]))'),
                           dict(t=list(tables))).scalar_one()
    baseline = _call(runtime, v, signature)
    assert baseline[0] == 'ok' and baseline[1], baseline
    observed = {}
    with _synthetic_owner(database, signature, tables) as set_bypass:
        for phase, bypass in (('bypassrls', True), ('nobypassrls', False)):
            set_bypass(bypass)
            observed[phase] = _call(get_private_summary_session_factory(), v, signature)
    assert observed['bypassrls'] == baseline
    contracts = {s.removeprefix('public.') for s, _ in release_preflight.PRIVATE_DEFINER_CONTRACTS}
    if forced:
        # Fail-closed error naming a FORCE table, and listed in the preflight.
        assert observed['nobypassrls'][:2] == ('error', '42501')
        assert 'row-level security' in observed['nobypassrls'][2]
        assert signature in contracts
    else:
        # The table owner legitimately reads non-FORCE tables: no dependency,
        # so no preflight contract (no false positive).
        assert observed['nobypassrls'] == baseline
        assert signature not in contracts
    assert _budget(database, v['tenant']) == 0 and _task(database, v['tenant']) == ('queued', None)
