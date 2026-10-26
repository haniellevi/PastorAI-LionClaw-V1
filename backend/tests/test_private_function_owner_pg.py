"""Owner of the private SECURITY DEFINER functions vs FORCE RLS, on real paths.

Disposable PG only. A synthetic NOLOGIN role without memberships takes over a
representative set of functions; between the positive and the negative control
only its BYPASSRLS attribute changes, with the same owner, grants and data
shape. The baseline is the unchanged chain (owner = the migration's superuser).
Each path runs through the real service, login and API; no function, identity
or authorization is mocked. Observations are recorded as JUnit suite
properties (counts, SQLSTATEs and closed event codes only). The last section
runs the read-only release preflight against the same chain and owners.

Limits: nested SECURITY DEFINER helpers (``current_igreja_id``,
``private_deletion_admin``, the summary/prayer triggers) keep their original
owner; invoker triggers run as the synthetic owner. The synthetic role owns the
functions, not the tables, so RLS also applies to it on RLS-enabled tables
without FORCE (a production owner that also owns those tables would bypass
them); on FORCE tables both cases are the same.
"""
import json
import logging
import secrets
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.private_send_session import dispose_private_send_engine
from app.db.privacy_storage_session import dispose_private_storage_engine
from tests.conftest_rls import assert_disposable_database
from tests.private_send_pg import private_send_login
from tests.private_storage_pg import private_storage_login
from tests.test_private_deletion_pg import api
from tests.test_uv_turmas_pg import rls_database_url, migrated_database, database  # noqa: F401

pytestmark = pytest.mark.rls_integration

SEND = 'private_send_release(uuid,uuid)'
DUE = 'private_storage_due_tasks(timestamp with time zone,integer)'
CONTENT = 'private_delete_content(uuid,text,uuid,uuid)'
SCOPE = 'private_delete_scope(uuid,text,uuid,uuid)'
OUTBOX = 'operations_notification_outbox_pending_metrics(uuid,timestamp with time zone)'
# Summary helpers that also declare row_security=off but read only tables
# without FORCE RLS directly (proved in test_private_summary_runtime_pg.py):
# not contracts, so a NOBYPASS owner on them is never a finding.
SUMMARY_NON_CONTRACTS = ('private_summary_runtime_snapshot(uuid,uuid)', 'private_summary_runtime_requester(uuid,uuid)',
                         'private_summary_runtime_credential(uuid)')
COUNTED = ('messages', 'conversations', 'cell_report_audio_inputs', 'private_deletion_receipts',
           'private_deletion_members', 'private_deletion_tasks', 'private_deletion_event_fences',
           'private_deletion_sends')

# What each function body (and the invoker triggers it fires) needs, so that a
# missing ACL never passes for RLS. The BYPASSRLS control proves sufficiency
# (ON CONFLICT needs SELECT on the arbiter; FOR KEY SHARE needs UPDATE).
SEND_ACL = dict(tables={'private_deletion_sends': 'select,delete'},
                helpers=('private_send_runtime_session()',))
DUE_ACL = dict(tables={'private_deletion_tasks': 'select', 'private_deletion_uploads': 'select'},
               helpers=('private_storage_runtime_session()',))
CONTENT_ACL = dict(
    tables={'private_deletion_receipts': 'select,insert,update', 'private_deletion_dependencies': 'insert',
            'private_deletion_members': 'insert', 'private_deletion_event_fences': 'select,insert',
            'private_deletion_tasks': 'insert', 'private_deletion_sends': 'select',
            'conversations': 'select,update,delete', 'messages': 'select,delete', 'pessoas': 'select,update',
            'igrejas': 'select,update', 'cell_report_audio_inputs': 'select,update,delete',
            'agent_conversation_logs': 'select,update,delete', 'private_conversation_summaries': 'select,delete',
            'private_summary_tasks': 'select,delete', 'pedido_oracao_proposta': 'select', 'pedido_oracao': 'select',
            'pedido_oracao_mensagem': 'select', 'agent_identity_challenges': 'select',
            'agent_identity_proofs': 'select', 'agent_action_proposals': 'select', 'agent_action_receipts': 'select',
            'cell_report_drafts': 'select', 'cell_report_audio_notices': 'select',
            'cell_report_audio_consent_events': 'select'},
    helpers=('current_igreja_id()', 'private_deletion_phone_key(text)'))
SCOPE_ACL = dict(tables={'private_deletion_receipts': 'select', 'app_users': 'select',
                         'private_erasure_requests': 'select,update'},
                 helpers=('current_igreja_id()', 'private_deletion_admin()', 'prayer_jwt_sub()'))


def _merge(*acls):
    tables, helpers = {}, set()
    for acl in acls:
        for table, privileges in acl['tables'].items():
            tables[table] = ','.join(sorted(set(filter(None, tables.get(table, '').split(','))) | set(privileges.split(','))))
        helpers |= set(acl['helpers'])
    return dict(tables=tables, helpers=tuple(sorted(helpers)))


def _function_acl(c, functions):
    """Owner plus every non-owner (grantee, privilege, grantable); grantor follows the owner."""
    result = {}
    for function in functions:
        owner, acl = c.execute(text('''select p.proowner::regrole::text, coalesce(array_agg(
              (case when a.grantee=0 then 'PUBLIC' else a.grantee::regrole::text end)||':'||a.privilege_type||':'||a.is_grantable
              order by 1) filter (where a.grantee<>p.proowner), '{}')
            from pg_proc p left join lateral aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a on true
            where p.oid=cast(:f as regprocedure) group by p.proowner'''), dict(f=function)).one()
        result[function] = (owner, tuple(acl))
    return result


def _raw_acl(c, functions):
    return {f: c.execute(text("select proowner, proacl::text from pg_proc where oid=cast(:f as regprocedure)"),
                         dict(f=f)).one() for f in functions}


def _role_rights(c, role):
    return (c.execute(text('''select coalesce(array_agg(c.relname||':'||p order by c.relname, p), '{}')
            from pg_class c join pg_namespace n on n.oid=c.relnamespace
            cross join unnest(array['SELECT','INSERT','UPDATE','DELETE']) p
            where n.nspname='public' and c.relkind='r' and has_table_privilege(:r, c.oid, p)'''),
            dict(r=role)).scalar_one(),
            c.execute(text('''select rolsuper,rolinherit,rolcanlogin,rolcreaterole,rolcreatedb,rolreplication,
                (select count(*) from pg_auth_members m where m.member=r.oid or m.roleid=r.oid)
                from pg_roles r where rolname=:r'''), dict(r=role)).one())


@contextmanager
def synthetic_definer(engine, functions, acl):
    """Transfer ``functions`` to a fresh NOLOGIN role; restore owner and drop it."""
    assert_disposable_database(engine.url.render_as_string(hide_password=False))
    role = f'pfo_definer_{secrets.token_hex(6)}'
    with engine.connect() as c:
        original_acl, original_raw = _function_acl(c, functions), _raw_acl(c, functions)
    with engine.begin() as c:
        c.exec_driver_sql(f'create role {role} nologin noinherit nosuperuser nobypassrls '
                          'nocreatedb nocreaterole noreplication')
    try:
        with engine.begin() as c:
            c.exec_driver_sql(f'grant usage on schema public to {role}')
            for table, privileges in acl['tables'].items():
                c.exec_driver_sql(f'grant {privileges} on public.{table} to {role}')
            for helper in acl['helpers']:
                c.exec_driver_sql(f'grant execute on function public.{helper} to {role}')
            for function in functions:
                c.exec_driver_sql(f'alter function public.{function} owner to {role}')
        with engine.connect() as c:
            transferred = _function_acl(c, functions)
            rights = _role_rights(c, role)
        # Same grantees/privileges; only the owner (and so the grantor) moved.
        assert {f: acl_ for f, (_, acl_) in transferred.items()} == {f: acl_ for f, (_, acl_) in original_acl.items()}
        assert {owner for owner, _ in transferred.values()} == {role}
        assert rights[1] == (False, False, False, False, False, False, 0)

        def set_bypass(bypass):
            with engine.begin() as c:
                assert c.execute(text('select not rolsuper from pg_roles where rolname=:r'), dict(r=role)).scalar_one()
                c.exec_driver_sql(f"alter role {role} {'bypassrls' if bypass else 'nobypassrls'}")
            # A local probe (PG 17.6, plpgsql, same connection) kept using the
            # plan cached under the previous attribute after ALTER ROLE. Every
            # phase therefore starts on fresh connections of the main and both
            # dedicated logins; this proves new sessions, not warm ones.
            engine.dispose()
            dispose_private_send_engine()
            dispose_private_storage_engine()
            with engine.connect() as c:
                assert c.execute(text('select rolbypassrls from pg_roles where rolname=:r'), dict(r=role)).scalar_one() is bypass
                # Between controls nothing but the attribute changes.
                assert _function_acl(c, functions) == transferred and _role_rights(c, role) == rights
        yield SimpleNamespace(role=role, set_bypass=set_bypass)
    finally:
        with engine.begin() as c:
            for function in functions:
                owner = original_acl[function][0]
                c.exec_driver_sql(f'alter function public.{function} owner to {owner}')
            c.exec_driver_sql(f'drop owned by {role}')  # Only its grants remain here.
            c.exec_driver_sql(f'drop role {role}')
    with engine.connect() as c:
        assert _raw_acl(c, functions) == original_raw
        assert c.execute(text('select count(*) from pg_roles where rolname=:r'), dict(r=role)).scalar_one() == 0


def _seed(engine):
    """Same synthetic graph as ``test_private_deletion_pg.private_data``, plus a provider id."""
    with engine.begin() as c:
        c.exec_driver_sql('delete from igrejas; delete from private_deletion_tasks; delete from private_deletion_event_fences; '
                          'delete from private_deletion_uploads; delete from private_deletion_sends; '
                          'delete from private_deletion_dependencies; delete from private_deletion_members; '
                          'delete from private_deletion_receipts')
    v = {k: uuid4() for k in ('tenant', 'other', 'person', 'person3', 'admin', 'conv', 'conv3', 'message', 'message3',
                              'audio', 'source_b')}
    with engine.begin() as c:
        for tenant in (v['tenant'], v['other']):
            c.execute(text("insert into igrejas(id,nome) values(:id,'Synthetic church')"), dict(id=tenant))
        for person, tenant in ((v['person'], v['tenant']), (v['person3'], v['other'])):
            c.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:id,:t,'Synthetic',:phone)"),
                      dict(id=person, t=tenant, phone=str(person.int)[-12:]))
        c.execute(text("insert into app_users(id,igreja_id,nome,email,status,clerk_user_id) values(:admin,:tenant,'Synthetic','synthetic@example.invalid','ativo','deletion-admin')"), v)
        c.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:tenant,:admin,'admin')"), v)
        for conv, message, person, tenant in ((v['conv'], v['message'], v['person'], v['tenant']),
                                              (v['conv3'], v['message3'], v['person3'], v['other'])):
            c.execute(text("insert into conversations(id,igreja_id,pessoa_id,telefone) values(:c,:t,:p,'000000000000')"),
                      dict(c=conv, t=tenant, p=person))
            c.execute(text("""insert into messages(id,igreja_id,conversation_id,direcao,autor,texto,media_path,provider_message_id)
                values(:m,:t,:c,'in','contato','Synthetic private text',:path,:provider)"""),
                      dict(m=message, t=tenant, c=conv, path=f'{tenant}/{conv}/synthetic.png', provider=f'synthetic-{uuid4()}'))
        c.execute(text("""insert into cell_report_audio_inputs
            (id,igreja_id,conversation_id,pessoa_id,inbound_message_id,live_conversation_id,live_pessoa_id,live_message_id,
             provider_message_sha256,storage_path,state,transcription_attempts,purge_state,purge_attempts,
             transcript_text,transcript_sha256,content_sha256,received_at,expires_at,updated_at)
            values(:audio,:tenant,:conv,:person,:message,NULL,:person,NULL,repeat('a',64),
            :path,'transcrita',1,'ativa',0,'Synthetic transcript',repeat('b',64),repeat('c',64),now(),now()+interval '24 hours',now())"""),
            dict(v, path=f"{v['tenant']}/cell-report-audio/synthetic.ogg"))
        # Church B keeps an in-flight send ownership, written as the queue's CAS would.
        c.execute(text('insert into private_deletion_sends(igreja_id,source_id,conversation_id,generation) values(:other,:source_b,:conv3,0)'), v)
        c.execute(text("""insert into private_erasure_requests(igreja_id,pessoa_id,conversation_id,inbound_id)
            values(:tenant,:person,:conv,:message),(:other,:person3,:conv3,:message3)"""), v)
    return v


def _counts(engine, v):
    with engine.connect() as c:
        def per(tenant):
            row = {t: c.execute(text(f'select count(*) from {t} where igreja_id=:t'), dict(t=tenant)).scalar_one() for t in COUNTED}
            row['tasks_pending'] = c.execute(text("""select count(*) from private_deletion_tasks
                where igreja_id=:t and state='pendente' and attempts=0 and error_code is null and storage_path is not null"""),
                dict(t=tenant)).scalar_one()
            row['erasure_pending'] = c.execute(text("select count(*) from private_erasure_requests where igreja_id=:t and state='pendente'"),
                                               dict(t=tenant)).scalar_one()
            return row
        return dict(tenant=per(v['tenant']), other=per(v['other']))


def _error(exc):
    orig = getattr(exc, 'orig', None)
    first = str(orig or exc).splitlines()[0]
    return dict(type=type(exc).__name__, sqlstate=getattr(orig, 'pgcode', None), message=first)


@pytest.fixture
def record(record_testsuite_property, request):
    """Observed outcome per test in the JUnit suite properties (xunit2-compatible)."""
    return lambda observed: record_testsuite_property(
        request.node.name, json.dumps(observed, sort_keys=True, default=str))


def _api_delete(database, v, path, **kwargs):
    """Real router and service as the synthetic admin; DB errors surface as the exception."""
    client = api(database, v)
    try:
        response = client.request('DELETE', path, **kwargs)
    except DBAPIError as exc:
        return dict(error=_error(exc))
    finally:
        client.close()
    body = response.json()
    return dict(status=response.status_code, estado=body.get('estado'), id=body.get('id'),
                camadas={k: body['camadas'][k] for k in ('mensagens', 'midias', 'envios')} if 'camadas' in body else None,
                detail=body.get('detail'))


# --- 1. Send ownership release (row_security=off): real queue flow + dedicated login.

def _deliver_with_deletion_during_http(database, v):
    from app.workers import queue_worker as worker
    factory = lambda: Session(database)
    outcome = worker.IngestionOutcome(result=worker.IngestionResult.REGISTERED, conversation_id=v['conv'],
        instance='synthetic', telefone='000000000000', texto='synthetic', inbound=True,
        igreja_id=v['tenant'], inbound_message_id=v['message'], provider_message_id=f'synthetic-{uuid4()}',
        claim_id='synthetic-owner')
    intent = worker._prepare_agent_reply_intent(factory, outcome, 'Synthetic reply', public_info_reply=False)
    during = {}

    class Transport:
        def send_text_classificado(self, *args):
            during.update(_api_delete(database, v, f"/conversations/{v['conv']}"))
            return SimpleNamespace(status='aceito')
    worker._deliver_agent_reply_intent(factory, outcome, intent, None, evolution_client=Transport())
    return during


def _send_phase(database, v, caplog):
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger='app.services.private_deletion'):
        during = _deliver_with_deletion_during_http(database, v)
    with TestClient(api(database, v).app) as client:
        after = client.get(f"/conversations/{v['conv']}/deletion-receipt").json()
    return dict(during=dict(estado=during['estado'], envios=during['camadas']['envios']),
                after=dict(estado=after['estado'], envios=after['camadas']['envios']),
                events=[(r.event, r.error_type) for r in caplog.records
                        if r.name == 'app.services.private_deletion' and getattr(r, 'event', '').startswith('private_send_release')],
                sends=_counts(database, v)['tenant']['private_deletion_sends'],
                other_sends=_counts(database, v)['other']['private_deletion_sends'])


def test_send_release_needs_owner_that_bypasses_rls(database, monkeypatch, caplog, record):
    from app.db.private_send_session import get_private_send_session_factory, scope_private_send
    with private_send_login(database, monkeypatch):
        observed = {'original': _send_phase(database, _seed(database), caplog)}
        with synthetic_definer(database, (SEND,), SEND_ACL) as definer:
            for phase, bypass in (('bypassrls', True), ('nobypassrls', False)):
                definer.set_bypass(bypass)
                v = _seed(database)
                observed[phase] = _send_phase(database, v, caplog)
                if not bypass:  # SQLSTATE of the same call, same login (the service logs only the class).
                    with get_private_send_session_factory()() as s:
                        scope_private_send(s, v['tenant'])
                        try:
                            s.execute(text('select private_send_release(:t,:s)'), dict(t=v['tenant'], s=v['message']))
                        except DBAPIError as exc:
                            observed[phase]['direct'] = _error(exc)
                        s.rollback()
    record(observed)
    released = dict(during=dict(estado='pendente_envio', envios=dict(encontradas=1, apagadas=0, pendentes=1, falhas=0)),
                    after=dict(estado='pendente', envios=dict(encontradas=1, apagadas=1, pendentes=0, falhas=0)),
                    events=[], sends=0, other_sends=1)
    assert observed['original'] == released
    assert observed['bypassrls'] == released
    negative = observed['nobypassrls']
    assert negative['during'] == released['during']
    assert negative['after'] == dict(estado='pendente_envio', envios=dict(encontradas=1, apagadas=0, pendentes=1, falhas=0))
    assert negative['events'] == [('private_send_release_failed', 'ProgrammingError')]
    assert (negative['sends'], negative['other_sends']) == (1, 1)  # Ownership retained, B untouched.
    assert negative['direct']['sqlstate'] == '42501'
    assert 'row-level security' in negative['direct']['message'] and 'private_deletion_sends' in negative['direct']['message']


# --- 2. Storage discovery (row_security=off): process_storage_tasks + Storage login.

def _storage_phase(database, v):
    from app.db.privacy_storage_session import get_private_storage_session_factory
    from app.services.private_deletion import process_storage_tasks
    assert _api_delete(database, v, f"/conversations/{v['conv']}")['status'] == 200
    with database.begin() as c:  # Church B via the owner path, as the storage suite does.
        c.execute(text("select private_delete_content(:t,'conversa',:c,:c)"), dict(t=v['other'], c=v['conv3']))
    before = _counts(database, v)
    calls = []
    storage = SimpleNamespace(remove_tenant_media=lambda tenant, paths: calls.append((tenant == v['tenant'], len(paths))))
    try:
        # As the cron does: the factory is resolved per run, so each phase gets a fresh session.
        result = dict(done=process_storage_tasks(get_private_storage_session_factory(), storage=storage))
    except DBAPIError as exc:
        result = dict(error=_error(exc))
    after = _counts(database, v)
    return dict(result, calls=sorted(calls),
                tasks_before=(before['tenant']['tasks_pending'], before['other']['tasks_pending']),
                tasks_after=(after['tenant']['tasks_pending'], after['other']['tasks_pending']),
                tasks_total_after=(after['tenant']['private_deletion_tasks'], after['other']['private_deletion_tasks']))


def test_storage_discovery_needs_owner_that_bypasses_rls(database, monkeypatch, record):
    with private_storage_login(database, monkeypatch):
        observed = {'original': _storage_phase(database, _seed(database))}
        with synthetic_definer(database, (DUE,), DUE_ACL) as definer:
            for phase, bypass in (('bypassrls', True), ('nobypassrls', False)):
                definer.set_bypass(bypass)
                observed[phase] = _storage_phase(database, _seed(database))
    record(observed)
    cleaned = dict(done=3, calls=[(False, 1), (True, 1), (True, 1)], tasks_before=(2, 1),
                   tasks_after=(0, 0), tasks_total_after=(2, 1))
    assert observed['original'] == cleaned
    assert observed['bypassrls'] == cleaned
    negative = observed['nobypassrls']
    assert negative['error']['sqlstate'] == '42501'
    # Either FORCE table the discovery reads may be reported first (PG17 reports uploads).
    assert 'row-level security' in negative['error']['message']
    assert any(f'"{t}"' in negative['error']['message'] for t in ('private_deletion_tasks', 'private_deletion_uploads'))
    # Fail-closed: nothing removed, every task still pending with its path and no attempt.
    assert (negative['calls'], negative['tasks_before'], negative['tasks_after']) == ([], (2, 1), (2, 1))


# --- 3. Deletion (no row_security=off): admin API -> private_delete_scope -> private_delete_content.

def _deletion_phase(database, v, scope):
    path = f"/conversations/{v['conv']}" if scope == 'conversa' else f"/contacts/{v['person']}/private-content"
    kwargs = {} if scope == 'conversa' else dict(json=dict(operation_id=str(uuid4()), confirmacao='EXCLUIR CONTEUDO PRIVADO'))
    before = _counts(database, v)
    first = _api_delete(database, v, path, **kwargs)
    after = _counts(database, v)
    return dict(first=first, before=before, after=after)


def _replay_phase(database, v, scope, definer):
    """Receipt created while the owner bypasses; the same request replayed with
    BYPASSRLS (positive control) and then after NOBYPASSRLS."""
    path = f"/conversations/{v['conv']}" if scope == 'conversa' else f"/contacts/{v['person']}/private-content"
    kwargs = {} if scope == 'conversa' else dict(json=dict(operation_id=str(uuid4()), confirmacao='EXCLUIR CONTEUDO PRIVADO'))
    definer.set_bypass(True)
    first = _api_delete(database, v, path, **kwargs)
    bypass_before = _counts(database, v)
    bypass_replay = _api_delete(database, v, path, **kwargs)
    bypass_after = _counts(database, v)
    definer.set_bypass(False)
    before = _counts(database, v)
    replay = _api_delete(database, v, path, **kwargs)
    return dict(first=first, bypass_replay=bypass_replay, bypass_before=bypass_before, bypass_after=bypass_after,
                replay=replay, before=before, after=_counts(database, v))


def _strip(observed):
    """Receipt ids differ per run; compare the rest."""
    return {k: ({kk: vv for kk, vv in val.items() if kk != 'id'} if isinstance(val, dict) else val)
            for k, val in observed.items()}


@pytest.mark.parametrize('scope', ('conversa', 'pessoa'))
@pytest.mark.parametrize('owned', ('content', 'scope_and_content'))
def test_deletion_with_owner_without_bypass(database, record, owned, scope):
    functions = (CONTENT,) if owned == 'content' else (SCOPE, CONTENT)
    acl = CONTENT_ACL if owned == 'content' else _merge(CONTENT_ACL, SCOPE_ACL)
    observed = {'original': _deletion_phase(database, _seed(database), scope)}
    with synthetic_definer(database, functions, acl) as definer:
        for phase, bypass in (('bypassrls', True), ('nobypassrls', False)):
            definer.set_bypass(bypass)
            observed[phase] = _deletion_phase(database, _seed(database), scope)
        observed['replay_nobypassrls'] = _replay_phase(database, _seed(database), scope, definer)
    record(observed)
    original, positive, negative = (_strip(observed[k]) for k in ('original', 'bypassrls', 'nobypassrls'))
    for phase in (original, positive):
        assert phase['first']['status'] == 200 and phase['first']['estado'] == 'pendente'
    assert positive == original
    # Church B is never touched, in any phase.
    for phase in ('original', 'bypassrls', 'nobypassrls', 'replay_nobypassrls'):
        assert observed[phase]['after']['other'] == observed[phase]['before']['other']
    # Without bypass: closed error, nothing deleted, no receipt or fence, request still pending.
    assert negative['first'] == {'error': negative['first']['error']}
    assert negative['first']['error']['sqlstate'] == '42501'
    assert 'row-level security' in negative['first']['error']['message']
    assert 'private_deletion_receipts' in negative['first']['error']['message']
    assert negative['after'] == negative['before']
    # Replaying a request whose receipt exists. Positive control: with
    # BYPASSRLS the same receipt comes back and nothing changes.
    replay = observed['replay_nobypassrls']
    assert replay['first']['status'] == 200
    assert replay['bypass_replay'] == replay['first'] and replay['bypass_after'] == replay['bypass_before']
    # Without it the receipt is hidden: nothing changes either.
    assert replay['after'] == replay['before']
    if scope == 'conversa':  # Conversation already gone: NULL -> 404, never a new or green receipt.
        assert replay['replay'] == dict(status=404, estado=None, id=None, camadas=None, detail='Alvo não encontrado')
    else:  # Person still exists: a fresh erasure is attempted and refused like the first one.
        assert replay['replay']['error']['sqlstate'] == '42501'
        assert 'private_deletion_receipts' in replay['replay']['error']['message']


# --- 4. Release preflight: read-only catalog check of the private definer contracts.

def _preflight(database, monkeypatch, capsys):
    import psycopg2
    from scripts import release_preflight
    url = database.url.set(drivername='postgresql').render_as_string(hide_password=False)
    connection = psycopg2.connect(url)
    try:
        report = release_preflight.inspect_connection(connection)
        with connection.cursor() as cursor:
            cursor.execute("select current_setting('transaction_read_only')")
            assert cursor.fetchone()[0] == 'on'
            with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
                cursor.execute("insert into public.schema_migrations(name) values ('write_attempt')")
    finally:
        connection.rollback()
        connection.close()
    monkeypatch.setenv(release_preflight.DATABASE_URL_ENV, url)
    capsys.readouterr()
    code = release_preflight.main()
    return report, code, capsys.readouterr().out


def _contracts():
    from scripts import release_preflight
    return tuple(signature for signature, _ in release_preflight.PRIVATE_DEFINER_CONTRACTS)


# Definers with row_security=off deliberately outside the contract, with reason.
EXCLUDED_DEFINERS = (
    # Operations metrics over the notification outbox, not private data (see the constant).
    'public.operations_notification_outbox_pending_metrics(pg_catalog.uuid,pg_catalog.timestamptz)',
    # Summary helpers whose own body reads only tables without FORCE RLS: an owner that
    # also owns those tables reads them without BYPASSRLS (otherwise they fail closed).
    # test_private_summary_runtime_pg proves the split on real PG. Nested definers such
    # as private_summary_origin_valid inherit row_security=off and are not examined here.
    'public.private_summary_runtime_snapshot(pg_catalog.uuid,pg_catalog.uuid)',
    'public.private_summary_runtime_requester(pg_catalog.uuid,pg_catalog.uuid)',
    'public.private_summary_runtime_credential(pg_catalog.uuid)',
)
# The two #584 definers over FORCE RLS tables, declared here, not derived from the constant.
UPLOAD_ATTEMPT = 'private_storage_begin_upload_attempt(uuid,uuid,uuid,bigint)'
WITNESS_DUE = 'private_storage_upload_witness_due(timestamp with time zone,integer)'


def test_every_row_security_off_definer_is_a_contract_or_an_explicit_exclusion(database):
    """A new private definer must be declared in the contract or excluded on purpose."""
    from scripts import release_preflight
    declared = [regprocedure for _, regprocedure in release_preflight.PRIVATE_DEFINER_CONTRACTS]
    with database.connect() as c:
        resolved = c.execute(text('select r, to_regprocedure(r)::oid from unnest(cast(:r as text[])) r'),
                             dict(r=declared + list(EXCLUDED_DEFINERS))).all()
        catalog = set(c.execute(text("""
            select p.oid from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.prosecdef
              and 'row_security=off' = any(coalesce(p.proconfig, '{}'))""")).scalars())
        expected = {oid for _, oid in resolved if oid is not None}

        def names(oids):
            if not oids:
                return []
            return sorted(c.execute(text('select cast(o as regprocedure)::text from unnest(cast(:o as oid[])) o'),
                                    dict(o=sorted(oids))).scalars())
        undeclared, stale = names(catalog - expected), names(expected - catalog)
    assert [name for name, oid in resolved if oid is None] == []
    assert (undeclared, stale) == ([], [])


@pytest.mark.parametrize('function', (UPLOAD_ATTEMPT, WITNESS_DUE))
def test_preflight_flags_each_584_definer_whose_owner_cannot_bypass(database, monkeypatch, capsys, function):
    """Only this function changes owner; its body is never executed."""
    with synthetic_definer(database, (function,), dict(tables={}, helpers=())) as definer:
        observed = {}
        for phase, bypass in (('nobypassrls', False), ('bypassrls', True)):
            definer.set_bypass(bypass)
            observed[phase] = _preflight(database, monkeypatch, capsys)
    report, code, output = observed['nobypassrls']
    assert [(f.function, f.owner) for f in report.definer_findings] == [(f'public.{function}', definer.role)]
    assert report.has_findings and code == 1 and 'RESULTADO=ACHADOS' in output
    assert f'private_definer_dono_sem_bypass funcao=public.{function} dono={definer.role}' in output
    report, code, output = observed['bypassrls']
    assert report.definer_findings == () and not report.has_findings and code == 0


def test_preflight_examines_all_private_contracts_on_the_migrated_chain(database, monkeypatch, capsys):
    report, code, output = _preflight(database, monkeypatch, capsys)
    assert (report.definer_examined, report.definer_unverified, report.definer_findings) == (_contracts(), (), ())
    assert not report.has_findings and code == 0
    assert f'private_definer_contracts: examinados={len(_contracts())} nao_verificados=0 dono_sem_bypass=0' in output
    assert 'RESULTADO=SEM_ACHADOS' in output


def test_preflight_flags_only_contracts_whose_owner_cannot_bypass(database, monkeypatch, capsys):
    """Contracts, the out-of-scope outbox definer and decoys share one NOBYPASS owner."""
    decoy = f'pfo_decoy_{secrets.token_hex(4)}'
    contracts = tuple(signature.removeprefix('public.') for signature in _contracts())
    with synthetic_definer(database, contracts + (OUTBOX,) + SUMMARY_NON_CONTRACTS, dict(tables={}, helpers=())) as definer:
        try:
            with database.begin() as c:
                c.exec_driver_sql(f'create schema {decoy}')
                # Same name in another schema, and an overload in public: same flags, not contracts.
                for function in (f'{decoy}.private_send_release(p_tenant uuid,p_source uuid)',
                                 'public.private_send_release(p_source text)',
                                 f'{decoy}.private_summary_runtime_reserve(p_tenant uuid)',
                                 'public.private_summary_runtime_reserve(p_tenant text)'):
                    c.exec_driver_sql(f"create function {function} returns boolean language sql security definer "
                                      "set row_security=off as 'select false'")
                    c.exec_driver_sql(f"alter function {function} owner to {definer.role}")
            observed = {}
            for phase, bypass in (('nobypassrls', False), ('bypassrls', True)):
                definer.set_bypass(bypass)
                observed[phase] = _preflight(database, monkeypatch, capsys)
        finally:
            with database.begin() as c:
                c.exec_driver_sql('drop function if exists public.private_send_release(text)')
                c.exec_driver_sql('drop function if exists public.private_summary_runtime_reserve(text)')
                c.exec_driver_sql(f'drop schema if exists {decoy} cascade')
    report, code, output = observed['nobypassrls']
    assert report.definer_examined == _contracts() and report.definer_unverified == ()
    assert [(f.function, f.owner) for f in report.definer_findings] == [(s, definer.role) for s in _contracts()]
    assert report.has_findings and code == 1 and 'RESULTADO=ACHADOS' in output
    count = len(_contracts())
    assert f'private_definer_contracts: examinados={count} nao_verificados=0 dono_sem_bypass={count}' in output
    assert f'private_definer_dono_sem_bypass funcao=public.private_send_release(uuid,uuid) dono={definer.role}' in output
    for absent in ('operations_notification_outbox', decoy, '(text)', 'postgresql',
                   'private_summary_runtime_snapshot', 'private_summary_runtime_requester',
                   'private_summary_runtime_credential'):
        assert absent not in output
    report, code, output = observed['bypassrls']
    assert report.definer_findings == () and not report.has_findings and code == 0
    assert f'private_definer_contracts: examinados={count} nao_verificados=0 dono_sem_bypass=0' in output
