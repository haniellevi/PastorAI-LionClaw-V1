"""Real SQL identity of agent send ownership release on the full migration chain.

The dedicated login is a synthetic LOGIN granted only in this disposable PG.
Nothing here relaxes RLS or replaces authorization: every refusal comes from
the real grants, policies and SECURITY DEFINER checks of the migration, and the
queue flow runs the real intent CAS, renewal and finish with a fake provider.
"""
import logging
import os
import secrets
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db.private_send_session import (
    PrivateSendScopeError, dispose_private_send_engine, scope_private_send,
)
from tests.private_send_pg import private_send_login
from tests.test_private_deletion_pg import api, private_data, runtime, scoped, send_runtime  # noqa: F401
from tests.test_uv_turmas_pg import ROOT, rls_database_url, migrated_database, database  # noqa: F401

pytestmark = pytest.mark.rls_integration
ROLE = 'private_send_runtime'
MIGRATION = '20261030_120000_private_send_release_identity.sql'
REFUSED = 'Runtime de liberação de envio obrigatório'
STORAGE_CALLS = (('select * from private_storage_due_tasks(now(),10)', {}),
                 ('select private_deletion_task_path(:id)', dict(id=uuid4())),
                 ('select private_storage_begin_upload(:t,:s,:c,0)', None))


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


@pytest.fixture
def owned(database, private_data):
    """In-flight ownership in both churches, written as the queue's CAS would."""
    v = private_data
    v['source_b'] = uuid4()
    with database.begin() as c:
        c.execute(text('insert into private_deletion_sends(igreja_id,source_id,conversation_id,generation) values(:tenant,:message,:conv,0)'), v)
        c.execute(text('insert into private_deletion_sends(igreja_id,source_id,conversation_id,generation) values(:other,:source_b,:conv3,0)'), v)
    return v


def _events(caplog):
    return [r.event for r in caplog.records if r.name == 'app.services.private_deletion']


def _rows(database, tenant=None):
    with database.connect() as c:
        return c.execute(text('select count(*) from private_deletion_sends where :t is null or igreja_id=:t'),
                         dict(t=tenant)).scalar_one()


def test_migration_creates_minimal_nologin_identity(database):
    with database.connect() as c:
        check = lambda sql, **kw: c.execute(text(sql), kw).scalar_one()
        role = c.execute(text('''select rolcanlogin,rolinherit,rolsuper,rolbypassrls,rolcreatedb,
            rolcreaterole,rolreplication,rolpassword is null from pg_authid where rolname=:r'''), dict(r=ROLE)).one()
        assert tuple(role) == (False, False, False, False, False, False, False, True)
        assert check('select count(*) from pg_auth_members m join pg_roles r on r.oid=m.member where r.rolname=:r', r=ROLE) == 0
        # Everything the role holds in this database: schema usage + two functions.
        assert check('''select count(*) from pg_shdepend d join pg_roles r on r.oid=d.refobjid
            where d.refclassid='pg_authid'::regclass and r.rolname=:r
             and d.dbid=(select oid from pg_database where datname=current_database())''', r=ROLE) == 3
        assert check('''select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace
            where n.nspname='public' and c.relkind in ('r','v','m','p','S') and (
             has_table_privilege(:r,c.oid,'SELECT') or has_table_privilege(:r,c.oid,'INSERT') or
             has_table_privilege(:r,c.oid,'UPDATE') or has_table_privilege(:r,c.oid,'DELETE'))''', r=ROLE) == 0
        assert not check("select has_any_column_privilege(:r,'private_deletion_sends','SELECT')", r=ROLE)
        # Beyond what any role gets from PUBLIC, only the two new functions.
        extra = set(c.execute(text('''select p.proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace
            where n.nspname='public' and has_function_privilege(:r,p.oid,'EXECUTE')
             and not exists(select 1 from aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
                            where a.grantee=0 and a.privilege_type='EXECUTE')'''), dict(r=ROLE)).scalars())
        assert extra == {'private_send_runtime_session', 'private_send_release'}
        for function in ('private_send_runtime_session()', 'private_send_release(uuid,uuid)'):
            for other in ('anon', 'authenticated', 'service_role', 'private_storage_runtime'):
                assert not check("select has_function_privilege(:r,:f,'EXECUTE')", r=other, f=function)
        assert check("select prosecdef from pg_proc where proname='private_send_release'")
        assert check("select proconfig from pg_proc where proname='private_send_release'") == [
            'search_path=pg_catalog, public, pg_temp', 'row_security=off']
        # Main login keeps the domain writes; only DELETE is gone. Admin counter unchanged.
        for privilege, expected in (('SELECT', True), ('INSERT', True), ('DELETE', False)):
            assert check("select has_table_privilege('authenticated','private_deletion_sends',:p)", p=privilege) is expected
        assert check("select has_column_privilege('authenticated','private_deletion_sends','expires_at','UPDATE')")
        assert not check("select has_column_privilege('authenticated','private_deletion_sends','generation','UPDATE')")
        assert set(c.execute(text("select polname from pg_policy where polrelid='private_deletion_sends'::regclass")).scalars()) == {
            'send_admin_read', 'send_worker_select', 'send_worker_insert', 'send_worker_update'}


@pytest.mark.parametrize('tamper', ('bypassrls', 'inherit', 'membership', 'direct_grant', 'default_acl'))
def test_unsafe_preexisting_role_is_refused(database, tamper):
    attribute = tamper in ('bypassrls', 'inherit', 'membership')
    with database.connect() as c:
        tx = c.begin()
        try:
            if not attribute:
                # Pre-migration state with a preexisting role that already holds rights here.
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


def test_main_login_keeps_domain_writes_but_cannot_release(database, owned):
    v = owned
    with api(database, v) as client:
        receipt = client.delete(f"/conversations/{v['conv']}").json()
    assert receipt['estado'] == 'pendente_envio' and receipt['camadas']['envios']['pendentes'] == 1
    for admin in (False, True):
        with scoped(database, v['tenant'], admin=admin) as s:
            assert s.execute(text('select count(*) from private_deletion_sends')).scalar_one() == 1
            for sql in ('delete from private_deletion_sends',
                        'update private_deletion_sends set generation=generation+1',
                        'select private_send_release(:t,:s)'):
                with pytest.raises(DBAPIError) as error:
                    s.execute(text(sql), dict(t=v['tenant'], s=v['message']))
                assert _sqlstate(error) == '42501'
                s.rollback()
    with scoped(database, v['tenant']) as s:  # INSERT and renewal stay on the main login.
        s.execute(text('insert into private_deletion_sends(igreja_id,source_id,conversation_id,generation) values(:tenant,:audio,:conv2,0)'), v)
        assert s.execute(text("update private_deletion_sends set expires_at=clock_timestamp()+interval '60 seconds'")).rowcount == 2
        s.commit()
    assert _rows(database, v['other']) == 1
    with api(database, v) as client:
        after = client.get(f"/igreja/private-deletions/{receipt['id']}").json()
    assert after['estado'] == 'pendente_envio' and after['camadas']['envios']['pendentes'] == 1


def test_release_is_scoped_by_key_and_tenant_without_table_access(database, owned, send_runtime, runtime):
    v = owned
    with send_runtime() as s:
        assert tuple(s.execute(text('select session_user::text, current_user::text')).one()) == (ROLE, ROLE)
        with pytest.raises(DBAPIError) as error:  # No tenant GUC, nothing is released.
            s.execute(text('select private_send_release(:t,:s)'), dict(t=v['tenant'], s=v['message']))
        assert _sqlstate(error) == '42501'
    with send_runtime() as s:
        scope_private_send(s, v['tenant'])
        # Another church's key under this church's GUC matches nothing.
        assert s.execute(text('select private_send_release(:t,:s)'), dict(t=v['tenant'], s=v['source_b'])).scalar_one() is False
        for params, state in ((dict(t=v['other'], s=v['source_b']), '42501'),
                              (dict(t=None, s=v['message']), '42501'),
                              (dict(t=v['tenant'], s=None), '22004')):
            with pytest.raises(DBAPIError) as error:
                s.execute(text('select private_send_release(:t,:s)'), params)
            assert _sqlstate(error) == state
            s.rollback()
        for sql in ('select count(*) from private_deletion_sends', 'delete from private_deletion_sends',
                    'select count(*) from messages', 'select count(*) from conversations',
                    'select count(*) from private_deletion_tasks', 'select count(*) from private_deletion_receipts'):
            with pytest.raises(DBAPIError) as error:
                s.execute(text(sql))
            assert _sqlstate(error) == '42501'
            s.rollback()
        for sql, params in STORAGE_CALLS:
            with pytest.raises(DBAPIError) as error:
                s.execute(text(sql), params or dict(t=v['tenant'], s=uuid4(), c=v['conv']))
            assert _sqlstate(error) == '42501'
            s.rollback()
        assert s.execute(text('select private_send_release(:t,:s)'), dict(t=v['tenant'], s=v['message'])).scalar_one() is True
        assert s.execute(text('select private_send_release(:t,:s)'), dict(t=v['tenant'], s=v['message'])).scalar_one() is False
        s.commit()
    assert (_rows(database, v['tenant']), _rows(database, v['other'])) == (0, 1)
    with runtime() as s:  # The Storage login cannot release either.
        with pytest.raises(DBAPIError) as error:
            s.execute(text('select private_send_release(:t,:s)'), dict(t=v['other'], s=v['source_b']))
        assert _sqlstate(error) == '42501'


def test_owner_set_role_and_other_worker_are_refused(database, owned):
    v = owned
    for set_role in (False, True):
        with database.connect() as c, c.begin():
            c.execute(text("select set_config('app.tenant_igreja_id',:t,true)"), dict(t=str(v['tenant'])))
            if set_role:
                c.exec_driver_sql(f'set local role {ROLE}')
            with pytest.raises(DBAPIError) as error:
                c.execute(text('select private_send_release(:t,:s)'), dict(t=v['tenant'], s=v['message']))
            assert REFUSED in str(error.value.orig)
    password = secrets.token_urlsafe(24)
    with database.begin() as c:
        c.exec_driver_sql(f"create role synthetic_send_worker login password '{password}' noinherit")
        c.exec_driver_sql('grant authenticated to synthetic_send_worker')
        c.exec_driver_sql('grant usage on schema public to synthetic_send_worker')
        c.exec_driver_sql('grant execute on function private_send_release(uuid,uuid) to synthetic_send_worker')
    other = create_engine(database.url.set(username='synthetic_send_worker', password=password))
    try:
        with other.connect() as c, c.begin():
            c.execute(text("select set_config('app.tenant_igreja_id',:t,true)"), dict(t=str(v['tenant'])))
            with pytest.raises(DBAPIError) as error:
                c.execute(text('select private_send_release(:t,:s)'), dict(t=v['tenant'], s=v['message']))
            assert REFUSED in str(error.value.orig)
    finally:
        other.dispose()
        with database.begin() as c:
            c.exec_driver_sql('drop owned by synthetic_send_worker')
            c.exec_driver_sql('drop role synthetic_send_worker')
    assert _rows(database) == 2


def test_identity_is_reproven_every_transaction(database, owned, send_runtime):
    v = owned
    with send_runtime() as s:
        scope_private_send(s, v['tenant'])
        assert s.execute(text('select private_send_runtime_session()')).scalar_one()
        s.commit()
        assert s.execute(text("select current_setting('app.tenant_igreja_id', true)")).scalar_one() == str(v['tenant'])
        with pytest.raises(PrivateSendScopeError):
            scope_private_send(s, v['other'])
    with send_runtime() as s:  # A persisted tenant GUC never reaches the next checkout.
        leaked = s.execute(text("select pg_backend_pid() from (select set_config('app.tenant_igreja_id', :t, false)) g"),
                           dict(t=str(v['tenant']))).scalar_one()
        s.commit()
    with send_runtime() as s:
        assert s.execute(text('select pg_backend_pid()')).scalar_one() != leaked
        assert s.execute(text("select current_setting('app.tenant_igreja_id', true)")).scalar_one() in (None, '')
    with database.begin() as c:
        c.exec_driver_sql(f'alter role {ROLE} createdb')
    raw = create_engine(os.environ['PRIVATE_SEND_DATABASE_URL'])
    try:
        with send_runtime() as s, pytest.raises(PrivateSendScopeError):
            s.execute(text('select 1'))  # The client probe refuses at BEGIN.
        with raw.connect() as c, c.begin():  # Without the client probe, SQL refuses too.
            c.execute(text("select set_config('app.tenant_igreja_id',:t,true)"), dict(t=str(v['tenant'])))
            with pytest.raises(DBAPIError) as error:
                c.execute(text('select private_send_release(:t,:s)'), dict(t=v['tenant'], s=v['message']))
            assert REFUSED in str(error.value.orig)
    finally:
        with database.begin() as c:
            c.exec_driver_sql(f'alter role {ROLE} nocreatedb')
    try:
        with raw.connect() as c, send_runtime() as pooled:
            c.execute(text('select 1')).scalar_one()
            c.commit()
            pooled.execute(text('select 1'))
            pooled.commit()
            with database.begin() as admin:
                admin.exec_driver_sql(f'alter role {ROLE} nologin')
            with pytest.raises(PrivateSendScopeError):
                pooled.execute(text('select 1'))  # Open pooled connection, next BEGIN.
            pooled.rollback()
            c.execute(text("select set_config('app.tenant_igreja_id',:t,true)"), dict(t=str(v['tenant'])))
            with pytest.raises(DBAPIError) as error:  # Open raw connection, SQL check.
                c.execute(text('select private_send_release(:t,:s)'), dict(t=v['tenant'], s=v['message']))
            assert REFUSED in str(error.value.orig)
    finally:
        raw.dispose()
    assert _rows(database) == 2


def test_search_path_is_fixed_against_url_and_role_schema(database, owned, monkeypatch):
    v = owned
    shadow = ROLE  # First in the default "$user", public.
    with database.begin() as c:
        c.exec_driver_sql(f'create schema {shadow}')
        c.exec_driver_sql(f'''create function {shadow}.private_send_release(uuid, uuid) returns boolean
            language sql as $$ select true $$''')
        c.exec_driver_sql(f'grant usage on schema {shadow} to {ROLE}')
        c.exec_driver_sql(f'grant execute on all functions in schema {shadow} to {ROLE}')
    try:
        with private_send_login(database, monkeypatch, url_options=f'-c search_path={shadow},public') as factory:
            with factory() as s:
                scope_private_send(s, v['tenant'])
                assert s.execute(text("select pg_catalog.current_setting('search_path')")).scalar_one() == 'pg_catalog, public, pg_temp'
                assert s.execute(text('select private_send_release(:t,:s)'), dict(t=v['tenant'], s=v['message'])).scalar_one()
                s.commit()
    finally:
        with database.begin() as c:
            c.exec_driver_sql(f'drop schema {shadow} cascade')
    assert (_rows(database, v['tenant']), _rows(database, v['other'])) == (0, 1)


# --- Real queue flow: intent CAS + renewal + fake provider + finish.

def _deliver(database, v, status, *, caplog=None):
    from app.workers import queue_worker as worker
    factory = lambda: Session(database)
    outcome = worker.IngestionOutcome(result=worker.IngestionResult.REGISTERED, conversation_id=v['conv'],
        instance='synthetic', telefone='000000000000', texto='synthetic', inbound=True,
        igreja_id=v['tenant'], inbound_message_id=v['message'], provider_message_id=f'synthetic-{uuid4()}',
        claim_id='synthetic-claim')
    intent = worker._prepare_agent_reply_intent(factory, outcome, 'Synthetic reply', public_info_reply=False)
    calls, during = [], []
    guard_calls = []

    def guard():
        guard_calls.append(True)
        if status == 'ownership_lost' and len(guard_calls) == 2:
            raise worker.ClaimOwnershipLost('synthetic')

    class Transport:
        def send_text_classificado(self, *args):
            calls.append(True)
            during.append(_rows(database, v['tenant']))
            return SimpleNamespace(status=status)
    raised = None
    try:
        worker._deliver_agent_reply_intent(factory, outcome, intent, guard, evolution_client=Transport())
    except (worker.AgentReplyRetryable, worker.ClaimOwnershipLost) as exc:
        raised = type(exc).__name__
    with database.connect() as c:
        state = c.execute(text('select agent_reply_state from messages where id=:id'), dict(id=intent.id)).scalar_one()
    return SimpleNamespace(outcome=outcome, intent=intent, transport=Transport(), guard=guard,
                           calls=calls, during=during, raised=raised, state=state, factory=factory)


EXPECTED = {
    'aceito': ('ia', None, 1),
    'falhou_retentavel': ('ia_pendente', 'AgentReplyRetryable', 1),
    'desconhecido': ('ia_ambigua', None, 1),
    'suprimido': ('ia_suprimida', None, 1),
    'ownership_lost': ('ia_pendente', 'ClaimOwnershipLost', 0),
}


@pytest.mark.parametrize('release', ('login', 'missing', 'nologin'))
@pytest.mark.parametrize('status', tuple(EXPECTED))
def test_queue_flow_outcome_is_identical_and_never_masked(database, owned, monkeypatch, caplog, status, release):
    from app.config import get_settings
    v = owned
    with database.begin() as c:  # Only church B's foreign row remains in flight.
        c.execute(text('delete from private_deletion_sends where igreja_id=:tenant'), v)
    with private_send_login(database, monkeypatch):
        if release == 'missing':
            monkeypatch.delenv('PRIVATE_SEND_DATABASE_URL')
            get_settings.cache_clear()
            dispose_private_send_engine()
        elif release == 'nologin':
            with database.begin() as c:
                c.exec_driver_sql(f'alter role {ROLE} nologin')
        with caplog.at_level(logging.WARNING, logger='app.services.private_deletion'):
            result = _deliver(database, v, status)
    assert (result.state, result.raised, len(result.calls)) == EXPECTED[status]
    assert result.during == [1] * len(result.calls)  # Ownership held during HTTP.
    assert _rows(database, v['other']) == 1
    events = _events(caplog)
    if release == 'login':
        assert _rows(database, v['tenant']) == 0 and events == []
    else:
        assert _rows(database, v['tenant']) == 1
        assert events == ['private_send_release_unavailable' if release == 'missing' else 'private_send_release_failed']
        exposed = caplog.text + ''.join(repr(r.__dict__) for r in caplog.records)
        for value in (str(result.intent.id), str(v['tenant']), '000000000000', 'Synthetic reply', 'postgresql'):
            assert value not in exposed


def test_retained_ownership_blocks_retry_without_duplicate_send(database, private_data, monkeypatch):
    """Declared limit: a retryable failure without the login is never resent."""
    v = private_data
    first = _deliver(database, v, 'falhou_retentavel')
    assert (first.state, first.raised, len(first.calls)) == ('ia_pendente', 'AgentReplyRetryable', 1)
    assert _rows(database, v['tenant']) == 1
    from app.workers import queue_worker as worker
    with private_send_login(database, monkeypatch):  # Configuring it later reconciles nothing.
        with pytest.raises(IntegrityError):
            worker._deliver_agent_reply_intent(first.factory, first.outcome, first.intent, None,
                                               evolution_client=first.transport)
    assert first.calls == [True]
    with database.connect() as c:
        assert c.execute(text('select agent_reply_state from messages where id=:id'),
                         dict(id=first.intent.id)).scalar_one() == 'ia_pendente'
    assert _rows(database, v['tenant']) == 1


def test_deletion_during_http_without_login_stays_pending_envio(database, private_data, runtime):
    from app.workers import queue_worker as worker
    from app.services.private_deletion import process_storage_tasks
    v = private_data
    factory = lambda: Session(database)
    outcome = worker.IngestionOutcome(result=worker.IngestionResult.REGISTERED, conversation_id=v['conv'],
        instance='synthetic', telefone='000000000000', texto='synthetic', inbound=True,
        igreja_id=v['tenant'], inbound_message_id=v['message'], provider_message_id='synthetic-no-login',
        claim_id='synthetic-no-login')
    intent = worker._prepare_agent_reply_intent(factory, outcome, 'Synthetic reply', public_info_reply=False)

    class Transport:
        def send_text_classificado(self, *args):
            with api(database, v) as client:
                assert client.delete(f"/conversations/{v['conv']}").json()['estado'] == 'pendente_envio'
            return SimpleNamespace(status='aceito')
    worker._deliver_agent_reply_intent(factory, outcome, intent, None, evolution_client=Transport())
    process_storage_tasks(runtime, storage=SimpleNamespace(remove_tenant_media=lambda *args: None))
    with api(database, v) as client:
        result = client.get(f"/conversations/{v['conv']}/deletion-receipt").json()
    assert result['estado'] == 'pendente_envio' and result['camadas']['envios']['pendentes'] == 1


def test_lost_commit_ack_is_unknown_and_pre_commit_failure_retains(database, owned, send_runtime, monkeypatch, caplog):
    from app.services import private_deletion

    def lost_ack():
        session = send_runtime()
        commit = session.commit

        def acknowledged_then_lost():
            commit()
            raise OperationalError('commit', {}, Exception('synthetic lost acknowledgement'))
        session.commit = acknowledged_then_lost
        return session
    v = owned
    monkeypatch.setattr(private_deletion, 'get_private_send_session_factory', lambda: lost_ack)
    with caplog.at_level(logging.WARNING, logger='app.services.private_deletion'):
        assert private_deletion.finish_agent_send(v['tenant'], v['message']) is False
    assert _events(caplog) == ['private_send_release_unknown']
    assert _rows(database, v['tenant']) == 0  # Reported as unknown, actually released.
    caplog.clear()
    monkeypatch.setattr(private_deletion, 'get_private_send_session_factory', lambda: send_runtime)
    with database.begin() as c:
        c.exec_driver_sql(f'revoke execute on function private_send_release(uuid,uuid) from {ROLE}')
    try:
        with caplog.at_level(logging.WARNING, logger='app.services.private_deletion'):
            assert private_deletion.finish_agent_send(v['other'], v['source_b']) is False
    finally:
        with database.begin() as c:
            c.exec_driver_sql(f'grant execute on function private_send_release(uuid,uuid) to {ROLE}')
    assert _events(caplog) == ['private_send_release_failed']
    assert _rows(database, v['other']) == 1
    assert private_deletion.finish_agent_send(v['other'], v['source_b']) is True


# --- Rollback rehearsal on the real chain, through migrate.py for the reapply.

OTHER_DB = 'private_send_other_test'


def test_rollback_guard_rehearsal_and_reapply(database, owned, monkeypatch):
    v = owned
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
    url = database.url
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
            assert check("select count(*) from pg_proc where proname in ('private_send_release','private_send_runtime_session')") == 0
            assert set(c.execute(text("select polname from pg_policy where polrelid='private_deletion_sends'::regclass")).scalars()) == {
                'send_admin_read', 'send_worker'}
            assert check("select has_table_privilege('authenticated','private_deletion_sends','DELETE')")
            assert check('select count(*) from schema_migrations where name=:n', n=MIGRATION) == 0
            assert check('select count(*) from private_deletion_sends') == 2  # Ownership preserved.
        with other.connect() as c:
            assert c.execute(text("select has_table_privilege(:r,'synthetic_other','SELECT')"), dict(r=ROLE)).scalar_one()
        env = dict(os.environ, MIGRATION_DATABASE_URL=url.render_as_string(hide_password=False).replace('postgresql+psycopg2:', 'postgresql:'))
        result = subprocess.run([sys.executable, str(ROOT/'scripts/migrate.py'), 'apply', MIGRATION, '--yes'],
                                env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    finally:
        other.dispose()
        with database.connect().execution_options(isolation_level='AUTOCOMMIT') as c:
            c.exec_driver_sql(f'drop database if exists {OTHER_DB}')
    with database.connect() as c:
        assert not c.execute(text("select has_table_privilege('authenticated','private_deletion_sends','DELETE')")).scalar_one()
        assert c.execute(text('select count(*) from schema_migrations where name=:n'), dict(n=MIGRATION)).scalar_one() == 1
    with private_send_login(database, monkeypatch) as factory, factory() as s:
        scope_private_send(s, v['tenant'])
        assert s.execute(text('select private_send_release(:t,:s)'), dict(t=v['tenant'], s=v['message'])).scalar_one()
        s.commit()
    assert (_rows(database, v['tenant']), _rows(database, v['other'])) == (0, 1)
