"""The normal queue worker on its real dedicated LOGIN, full migration chain.

``queue_worker_runtime`` is created NOLOGIN by the migration; each test grants
LOGIN with a random password on this disposable PG only (tests/queue_worker_pg)
and the worker picks its factory through the real QUEUE_WORKER_DATABASE_MODE
selector. Catalog, router, authorization, domain services, RLS and SQL helpers
are the real ones; only LLM, Jev and Evolution are fakes. No SET ROLE stands in
for the LOGIN; the setup superuser only seeds, tampers and verifies.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, DisconnectionError, InvalidRequestError
from sqlalchemy.pool import NullPool

from app.agent import runtime
from app.db import queue_worker_session as qws
from app.db.models import Message, WhatsappConnection
from app.db.tenant_session import TenantPinConflictError, mark_tenant_scoped
from app.services import private_summaries as summaries
from app.services.llm import LLMClient, LLMUsage, TypedChoiceResult, TypedLLMResult
from app.workers import queue_worker as worker
from tests.private_send_pg import private_send_login
from tests.queue_worker_pg import ROLE, queue_worker_login
from tests.test_agent_privileged_turn_pg import (  # noqa: F401
    _HttpProtocolQueue, _IGREJA, _PHONE, _fake_choices, _inbound, _revoke_role, _rows, s3_turn,
)
from tests.test_messages_inbound_idempotency import _ClassifiedEvolution
from tests.test_private_resume_pg import memory, msg_engine_fx  # noqa: F401
from tests.test_uv_turmas_pg import ROOT, database, migrated_database  # noqa: F401

pytestmark = pytest.mark.rls_integration

MIGRATION = '20261030_160000_queue_worker_runtime_identity.sql'
INSTANCE = 's3-synthetic'
_IGREJA_B = uuid.UUID('4b4b4b4b-0000-4000-8000-000000000002')
INSTANCE_B = 'queue-runtime-b-synthetic'
# Instances provisioned out of band are plain TEXT; no length limit is invented.
LONG_INSTANCE = 'legacy-out-of-band-' + 'x' * 200
FIXED_PATH = qws.QUEUE_WORKER_SEARCH_PATH
SEND = 'private_send_runtime'
OTHER_DB = 'queue_runtime_other_test'
EVIDENCE = os.environ.get('QUEUE_WORKER_RUNTIME_EVIDENCE')
PROBE_PREFIX = "select session_user::text, current_user::text, pg_catalog.current_setting('role')"
QUEUE_HELPERS = ('queue_resolve_instance(text)', 'queue_worker_runtime_session()')
REFUSED = (DBAPIError, DisconnectionError, InvalidRequestError, qws.QueueWorkerIdentityError)


@pytest.fixture(scope='module')
def rls_database_url():
    from tests.conftest_rls import assert_disposable_database
    url = os.environ['UV_TURMAS_DATABASE_URL']  # Missing local PG is failure, never skip.
    assert_disposable_database(url)
    parsed = urlsplit(url)
    assert parsed.hostname in {'localhost', '127.0.0.1', '::1'}
    assert parsed.path == '/uv_turmas_test'
    return url


def _save(name, value):
    """Sanitized evidence (labels and counts, no secrets) only when the runner asks."""
    if not EVIDENCE:
        return
    path = os.path.join(EVIDENCE, 'json', name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(value, fh, ensure_ascii=False, indent=1, default=str)


def _pgcode(exc):
    return getattr(getattr(exc, 'orig', None), 'pgcode', None)


def _migration_sql():
    from scripts import migrate
    return migrate.strip_outer_transaction((migrate.MIGRATIONS_DIR / MIGRATION).read_text())


def _rollback_sql():
    """The migration's own commented rollback, uncommented, without BEGIN/COMMIT."""
    from scripts import migrate
    block = (migrate.MIGRATIONS_DIR / MIGRATION).read_text().split('-- BEGIN;\n', 1)[1].split('-- COMMIT;', 1)[0]
    return '\n'.join(line[3:] if line.startswith('-- ') else line[2:] for line in block.splitlines())


# The role is cluster-global: after the rollback it may survive because another
# database of the same cluster (e.g. another suite's chain) still depends on it.
ENSURE_SAFE_ROLE = (f"do $$ begin if not exists(select 1 from pg_roles where rolname='{ROLE}') then "
                    f"create role {ROLE} nologin noinherit; "
                    f"grant authenticated to {ROLE} with inherit false, set true; end if; end $$")
FOREIGN_DEPENDENCIES = '''select count(*) from pg_shdepend d join pg_roles r on r.oid=d.refobjid
    where r.rolname=:r and d.dbid not in (0, (select oid from pg_database where datname=current_database()))'''


def _migrate(url, filename=MIGRATION):
    env = dict(os.environ, MIGRATION_DATABASE_URL=url.render_as_string(hide_password=False)
               .replace('postgresql+psycopg2:', 'postgresql:'))
    return subprocess.run([sys.executable, str(ROOT / 'scripts/migrate.py'), 'apply', filename, '--yes'],
                          env=env, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Recorder: per-login SQL (statement text only), transactions and provider calls.
# ---------------------------------------------------------------------------
class Recorder:
    def __init__(self, observer):
        self.lock = threading.Lock()
        self.events = []
        self.tx = iter(range(1, 10**6))
        self.active = False
        self.observer = observer

    def add(self, *item):
        with self.lock:
            self.events.append(item)

    def of(self, kind):
        return [e for e in self.events if e[0] == kind]

    def users(self):
        counts = {}
        for e in self.of('sql'):
            counts[e[1]] = counts.get(e[1], 0) + 1
        return counts

    def tx_statements(self, user):
        grouped = {}
        for e in self.of('sql'):
            if e[1] == user:
                grouped.setdefault(e[2], []).append(e[3])
        return grouped

    def index(self, predicate):
        return next(i for i, e in enumerate(self.events) if predicate(e))


@contextmanager
def recording(rec):
    def begin(conn):
        if rec.active and conn.engine is not rec.observer:
            conn.info['qw_tx'] = next(rec.tx)
            rec.add('begin', conn.engine.url.username, conn.info['qw_tx'])

    def commit(conn):
        if rec.active and conn.engine is not rec.observer:
            rec.add('commit', conn.engine.url.username, conn.info.get('qw_tx'))

    def rollback(conn):
        if rec.active and conn.engine is not rec.observer:
            rec.add('rollback', conn.engine.url.username, conn.info.get('qw_tx'))

    def before(conn, _cursor, statement, _params, _context, _many):
        if rec.active and conn.engine is not rec.observer:
            rec.add('sql', conn.engine.url.username, conn.info.get('qw_tx'), ' '.join(statement.split())[:400])
    handlers = (('begin', begin), ('commit', commit), ('rollback', rollback), ('before_cursor_execute', before))
    for name, fn in handlers:
        event.listen(Engine, name, fn)
    rec.active = True
    try:
        yield rec
    finally:
        rec.active = False
        for name, fn in handlers:
            event.remove(Engine, name, fn)


@pytest.fixture
def queue_login(database, monkeypatch):
    observer = create_engine(database.url, poolclass=NullPool, future=True,
                             connect_args={'application_name': 'queue-runtime-observer'})
    with queue_worker_login(database, monkeypatch) as url:
        yield SimpleNamespace(url=url, admin=database, observer=observer, rec=Recorder(observer))
    observer.dispose()
    with database.begin() as c:
        c.exec_driver_sql("do $$ begin if exists(select 1 from pg_roles where rolname='queue_runtime_other_login') then "
                          "revoke usage on schema public from queue_runtime_other_login; "
                          "drop owned by queue_runtime_other_login; drop role queue_runtime_other_login; end if; end $$")
        c.exec_driver_sql('drop role if exists queue_runtime_third_role')


def _factory():
    factory = worker.select_queue_session_factory()
    assert factory is qws.get_queue_worker_session_factory()
    return factory


def _state_rows(login):
    """Observer only: queue-login backends and their locks (verification, not execution)."""
    with login.observer.connect() as c:
        backends = c.execute(text('''select pid,state,xact_start is not null from pg_stat_activity
            where usename=:r and datname=current_database()'''), dict(r=ROLE)).all()
        locks = c.execute(text('''select l.pid,l.locktype,l.mode,l.granted from pg_locks l
            join pg_stat_activity a on a.pid=l.pid where a.usename=:r and l.locktype<>'virtualxid' '''),
            dict(r=ROLE)).all()
    return [tuple(b) for b in backends], [tuple(x) for x in locks]


def _envelope(provider_id, body, *, phone=_PHONE, instance=INSTANCE, name='Contato sintético'):
    payload = {'event': 'messages.upsert', 'instance': instance, 'data': {
        'key': {'remoteJid': f'{phone}@s.whatsapp.net', 'fromMe': False, 'id': provider_id},
        'pushName': name, 'message': {'conversation': body}}}
    return worker._Envelope(payload=json.loads(json.dumps(payload)), claim_id=f'QUEUE-RT-{provider_id}')


def _queue_worker(evolution=None, *, worker_id='QUEUE-RUNTIME'):
    """No session_factory: the real QUEUE_WORKER_DATABASE_MODE selector decides."""
    runner = None
    if evolution is not None:
        def runner(f, o, g):
            return worker.run_agent_for_message(f, o, g, evolution_client=evolution)
    return worker.QueueWorker(queue=_HttpProtocolQueue(), agent_runner=runner, media_resolver=None,
                              worker_id=worker_id, heartbeat_publisher=lambda *_a: None)


def _seed_b(admin, instance=INSTANCE_B):
    with admin.begin() as c:
        c.execute(text("insert into igrejas(id,nome) values(:t,'Igreja B sintética') on conflict do nothing"), dict(t=_IGREJA_B))
        c.execute(text('insert into whatsapp_connections(igreja_id,instance,numero) values(:t,:i,:n) '
                       'on conflict (igreja_id) do update set instance=excluded.instance'),
                  dict(t=_IGREJA_B, i=instance, n='5500000000900'))
        if not c.execute(text('select count(*) from messages where igreja_id=:t'), dict(t=_IGREJA_B)).scalar_one():
            p = c.execute(text("insert into pessoas(igreja_id,nome,telefone) values(:t,'Pessoa B sintética','5500000000901') returning id"),
                          dict(t=_IGREJA_B)).scalar_one()
            cid = c.execute(text("insert into conversations(igreja_id,pessoa_id,telefone,estado) values(:t,:p,'5500000000901','ia') returning id"),
                            dict(t=_IGREJA_B, p=p)).scalar_one()
            c.execute(text("insert into messages(igreja_id,conversation_id,direcao,autor,texto,tipo) values(:t,:c,'in','contato','Mensagem B sintética','texto')"),
                      dict(t=_IGREJA_B, c=cid))


def _llm(monkeypatch, login, prompts, marks):
    usage = LLMUsage(modelo='synthetic', tokens_in=2, tokens_out=1, custo=0)

    def choose(*_a, **_kw):
        login.rec.add('provider', 'llm_choice')
        marks.append(('llm_choice', _state_rows(login)))
        return TypedChoiceResult('nenhuma', usage)

    def answer(_self, _system, user, **_kw):
        login.rec.add('provider', 'llm_answer')
        marks.append(('llm_answer', _state_rows(login)))
        prompts.append(user)
        return TypedLLMResult(False, 'Resposta sintética segura.', usage)
    monkeypatch.setattr(LLMClient, 'generate_typed', choose)
    monkeypatch.setattr(LLMClient, 'complete_typed', answer)
    monkeypatch.setattr(runtime, 'decrypt_secret', lambda _: 'synthetic-key')


class _ObservedEvolution(_ClassifiedEvolution):
    def __init__(self, login, marks, *statuses):
        super().__init__(*statuses)
        self.login, self.marks = login, marks

    def send_text_classificado(self, instance, telefone, texto):
        self.login.rec.add('provider', 'evolution_send')
        self.marks.append(('evolution_send', _state_rows(self.login)))
        return super().send_text_classificado(instance, telefone, texto)


def _assert_no_main_login(rec, allowed=(ROLE, SEND)):
    users = rec.users()
    assert users.get(ROLE, 0) > 0
    assert set(users) <= set(allowed), users  # Any other engine (main/setup login) would show here.
    return users


def _assert_no_tx_at_providers(marks, *, lease_only=False):
    for name, (backends, locks) in marks:
        assert not [b for b in backends if b[2]], name  # No open queue-login transaction.
        if lease_only:
            assert all(x[1] == 'advisory' for x in locks), name
        else:
            assert locks == [], name


def _assert_every_begin_proven(rec):
    """Each Session BEGIN ran the identity probe before and after the tenant seam."""
    for tx, statements in rec.tx_statements(ROLE).items():
        probes = [s for s in statements if s.startswith(PROBE_PREFIX)]
        if any('pg_try_advisory_lock' in s or 'pg_advisory_unlock' in s or 'lease harness' in s for s in statements):
            continue  # Raw lease connection: proven at checkout instead.
        assert len(probes) >= 2 and statements[0].startswith(PROBE_PREFIX), (tx, statements[:3])


# ---------------------------------------------------------------------------
# 1. Migration: NOLOGIN login, one safe membership, two typed functions.
# ---------------------------------------------------------------------------
def test_migration_creates_nologin_login_with_one_safe_membership(database):
    import psycopg2
    from scripts import release_preflight
    with database.connect() as c:
        def check(sql, **kw):
            return c.execute(text(sql), kw).scalar_one()
        role = c.execute(text('''select rolcanlogin,rolinherit,rolsuper,rolbypassrls,rolcreatedb,
            rolcreaterole,rolreplication,rolpassword is null from pg_authid where rolname=:r'''), dict(r=ROLE)).one()
        assert tuple(role) == (False, False, False, False, False, False, False, True)
        members = c.execute(text('''select g.rolname,m.admin_option,m.inherit_option,m.set_option from pg_auth_members m
            join pg_roles g on g.oid=m.roleid where m.member=cast(:r as regrole)'''), dict(r=ROLE)).all()
        assert [tuple(m) for m in members] == [('authenticated', False, False, True)]
        assert check('select count(*) from pg_auth_members where roleid=cast(:r as regrole)', r=ROLE) == 0
        # No table, view, sequence or column privilege of its own (INHERIT FALSE).
        assert c.execute(text('''select c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace
            cross join unnest(array['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) p
            where n.nspname='public' and c.relkind in ('r','v','m','p','S','f') and has_table_privilege(:r,c.oid,p)'''),
            dict(r=ROLE)).all() == []
        assert not check('''select exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace
            where n.nspname='public' and c.relkind in ('r','v','m','p','f') and has_any_column_privilege(:r,c.oid,'SELECT,INSERT,UPDATE'))''', r=ROLE)
        assert not check("select has_schema_privilege(:r,'public','CREATE')", r=ROLE)
        assert not check("select has_database_privilege(:r,current_database(),'CREATE')", r=ROLE)
        extra = set(c.execute(text('''select p.oid::regprocedure::text from pg_proc p join pg_namespace n on n.oid=p.pronamespace
            where n.nspname='public' and has_function_privilege(:r,p.oid,'EXECUTE')
             and not exists(select 1 from aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
                            where a.grantee=0 and a.privilege_type='EXECUTE')'''), dict(r=ROLE)).scalars())
        assert extra == set(QUEUE_HELPERS)
        for function in QUEUE_HELPERS:
            for other in ('anon', 'authenticated', 'service_role', 'private_send_runtime',
                          'private_storage_runtime', 'private_summary_runtime'):
                assert not check("select has_function_privilege(:r,:f,'EXECUTE')", r=other, f=function), (other, function)
            config, secdef = c.execute(text('select proconfig, prosecdef from pg_proc where oid=cast(:f as regprocedure)'),
                                       dict(f=function)).one()
            if function == 'queue_worker_runtime_session()':
                assert (config, secdef) == (['search_path=pg_catalog, public, pg_temp'], False)
            else:
                assert (config, secdef) == (['search_path=pg_catalog, public, pg_temp', 'row_security=off'], True)
        assert check('select count(*) from pg_policy p where cast(:r as regrole) = any(p.polroles)', r=ROLE) == 0
        # The builtin effective role is validated, not changed.
        assert tuple(c.execute(text('''select rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication
            from pg_roles where rolname='authenticated' ''')).one()) == (False,) * 5
        assert check("select count(*) from pg_auth_members where member='authenticated'::regrole") == 0
        # The helper reads a table without FORCE RLS: its owner needs no BYPASSRLS.
        assert tuple(c.execute(text("select relrowsecurity, relforcerowsecurity from pg_class "
                                    "where oid='public.whatsapp_connections'::regclass")).one()) == (True, False)
    assert not [s for s, _ in release_preflight.PRIVATE_DEFINER_CONTRACTS if 'queue_' in s]
    connection = psycopg2.connect(database.url.set(drivername='postgresql').render_as_string(hide_password=False))
    try:
        report = release_preflight.inspect_connection(connection)
    finally:
        connection.rollback()
        connection.close()
    assert report.definer_findings == ()


TAMPER = {
    'login': f'alter role {ROLE} login',
    'bypassrls': f'alter role {ROLE} bypassrls',
    'inherit': f'alter role {ROLE} inherit',
    'createrole': f'alter role {ROLE} createrole',
    'superuser': f'alter role {ROLE} superuser',
    'extra_membership': f'grant anon to {ROLE} with inherit false, set true',
    'admin_option': f'grant authenticated to {ROLE} with admin option',
    'inherit_true_grant': f'grant authenticated to {ROLE} with inherit true',
    'set_false_grant': f'grant authenticated to {ROLE} with set false',
    'has_member': f'create role queue_runtime_third_role nologin; grant {ROLE} to queue_runtime_third_role',
    'direct_grant': f'grant select on public.messages to {ROLE}',
    'default_acl': f'alter default privileges in schema public grant select on tables to {ROLE}',
    'auth_bypassrls': 'alter role authenticated bypassrls',
    'auth_createrole': 'alter role authenticated createrole',
    'auth_chain': 'grant service_role to authenticated',
    'auth_owns_table': 'create table public.queue_runtime_owned(igreja_id uuid); '
                       'alter table public.queue_runtime_owned enable row level security; '
                       'alter table public.queue_runtime_owned owner to authenticated',
}


@pytest.mark.parametrize('tamper', sorted(TAMPER))
def test_unsafe_preexisting_role_or_builtin_is_refused_never_repaired(database, tamper):
    with database.connect() as c:
        tx = c.begin()
        try:
            if tamper in ('direct_grant', 'default_acl'):
                # A known NOLOGIN role whose only problem is a privilege in this database.
                c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
                c.exec_driver_sql(ENSURE_SAFE_ROLE)
            c.exec_driver_sql(TAMPER[tamper])
            with pytest.raises(DBAPIError) as error:
                c.exec_driver_sql(_migration_sql(), execution_options={'no_parameters': True})
            expected = ('authenticated com atributos' if tamper.startswith('auth_') else
                        'objetos ou privilégios' if tamper in ('direct_grant', 'default_acl') else 'atributos inseguros')
            assert expected in str(error.value.orig) and _pgcode(error.value) == '42501'
        finally:
            tx.rollback()


# PostgreSQL 16+ makes a non-superuser creator (Supabase's `postgres`) an
# ADMIN-only member of the new role: it may administer it, never SET/inherit it.
CREATOR_MEMBER = (f'create role queue_runtime_third_role nologin; grant {ROLE} to queue_runtime_third_role '
                  'with admin option, inherit false, set false')


def test_migration_accepts_the_preexisting_shape_left_by_another_database(database):
    with database.connect() as c:
        tx = c.begin()
        try:
            c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
            c.exec_driver_sql(ENSURE_SAFE_ROLE)
            c.exec_driver_sql(CREATOR_MEMBER)
            c.exec_driver_sql(_migration_sql(), execution_options={'no_parameters': True})
            rows = c.execute(text('''select g.rolname,u.rolname,m.admin_option,m.inherit_option,m.set_option
                from pg_auth_members m join pg_roles g on g.oid=m.roleid join pg_roles u on u.oid=m.member
                where cast(:r as regrole) in (m.member, m.roleid) order by 1'''), dict(r=ROLE)).all()
            assert [tuple(r) for r in rows] == [('authenticated', ROLE, False, False, True),
                                                (ROLE, 'queue_runtime_third_role', True, False, False)]
        finally:
            tx.rollback()


def test_admin_only_member_of_the_login_does_not_block_the_runtime(s3_turn, queue_login):
    with queue_login.admin.begin() as a:
        a.exec_driver_sql(CREATOR_MEMBER)
    factory = _factory()
    with factory() as s:
        mark_tenant_scoped(s, _IGREJA, source='queue_runtime_creator_member')
        assert s.execute(text('select current_user')).scalar_one() == 'authenticated'
    with factory.kw['bind'].connect() as c:
        assert len(c.execute(text('select * from queue_resolve_instance(:i)'), dict(i=INSTANCE)).all()) == 1


def test_rollback_guard_global_membership_across_databases_and_reapply(database, monkeypatch, caplog):
    def membership(c):
        return [tuple(r) for r in c.execute(text('''select g.rolname,m.admin_option,m.inherit_option,m.set_option
            from pg_auth_members m join pg_roles g on g.oid=m.roleid where m.member=cast(:r as regrole)'''), dict(r=ROLE))]
    _seed_b(database)
    with queue_worker_login(database, monkeypatch):  # LOGIN provisioned: rollback refuses.
        with database.connect() as c:
            tx = c.begin()
            with pytest.raises(DBAPIError) as error:
                c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
            assert 'LOGIN provisionado' in str(error.value.orig)
            tx.rollback()
    with caplog.at_level(logging.INFO, logger='sqlalchemy.dialects.postgresql'), database.connect() as c:
        # Dropped (with its membership) only when no other database depends on it; otherwise kept and said so.
        foreign = c.execute(text(FOREIGN_DEPENDENCIES), dict(r=ROLE)).scalar_one()
        c.rollback()
        tx = c.begin()
        c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
        kept = c.execute(text('select count(*) from pg_roles where rolname=:r'), dict(r=ROLE)).scalar_one()
        tx.rollback()
    assert kept == (1 if foreign else 0) and ('queue_worker_runtime mantido' in caplog.text) == bool(foreign)
    caplog.clear()
    with database.connect() as c:  # Local drift left on the role: the rollback stops, never looks clean.
        tx = c.begin()
        c.exec_driver_sql(f'grant select on public.schema_migrations to {ROLE}')
        with pytest.raises(DBAPIError) as error:
            c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
        assert 'ainda tem objetos ou privilégios neste banco' in str(error.value.orig) and _pgcode(error.value) == '55000'
        tx.rollback()
    with database.connect().execution_options(isolation_level='AUTOCOMMIT') as c:
        c.exec_driver_sql(f'drop database if exists {OTHER_DB}')
        c.exec_driver_sql(f'create database {OTHER_DB}')
    other = create_engine(database.url.set(database=OTHER_DB))
    out = {}
    try:
        with other.begin() as c:  # Another database with its own ledger and the same global roles.
            c.exec_driver_sql('create table public.schema_migrations(name text primary key)')
        result = _migrate(other.url)
        assert result.returncode == 0, result.stderr
        with database.connect() as c:
            out['membership_after_other_db'] = membership(c)
            assert out['membership_after_other_db'] == [('authenticated', False, False, True)]  # Kept, never duplicated.
        # SQLAlchemy's psycopg2 dialect forwards server NOTICEs to this logger.
        with caplog.at_level(logging.INFO, logger='sqlalchemy.dialects.postgresql'), database.begin() as c:
            c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
        assert 'queue_worker_runtime mantido' in caplog.text  # Kept, and said so.
        with database.connect() as c:
            def check(sql, **kw):
                return c.execute(text(sql), kw).scalar_one()
            assert check('select count(*) from pg_roles where rolname=:r', r=ROLE) == 1  # Other database depends on it.
            assert membership(c) == [('authenticated', False, False, True)]
            assert check("select count(*) from pg_proc where proname in ('queue_resolve_instance','queue_worker_runtime_session')") == 0
            assert check('''select count(*) from pg_shdepend d join pg_roles r on r.oid=d.refobjid where r.rolname=:r
                and d.dbid=(select oid from pg_database where datname=current_database())''', r=ROLE) == 0
            assert check('select count(*) from schema_migrations where name=:n', n=MIGRATION) == 0
            assert check('select count(*) from messages where igreja_id=:b', b=_IGREJA_B) == 1  # Data untouched.
        with other.connect() as c:
            assert c.execute(text("select has_function_privilege(:r,'public.queue_resolve_instance(text)','EXECUTE')"),
                             dict(r=ROLE)).scalar_one()
        result = _migrate(database.url)  # Reapply through migrate.py over the surviving safe membership.
        assert result.returncode == 0, result.stderr
        with other.begin() as c:  # Rolling back the other database keeps the role used here.
            c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
        with database.connect() as c:
            out['membership_after_reapply'] = membership(c)
            assert out['membership_after_reapply'] == [('authenticated', False, False, True)]
            assert c.execute(text('select count(*) from schema_migrations where name=:n'), dict(n=MIGRATION)).scalar_one() == 1
    finally:
        other.dispose()
        with database.connect().execution_options(isolation_level='AUTOCOMMIT') as c:
            c.exec_driver_sql(f'drop database if exists {OTHER_DB}')
        with database.connect() as c:
            applied = c.execute(text('select count(*) from schema_migrations where name=:n'), dict(n=MIGRATION)).scalar_one()
        if not applied:  # A failure mid-rehearsal never leaves later tests on the rolled-back schema.
            _migrate(database.url)
    with queue_worker_login(database, monkeypatch):  # The reapplied identity still works end to end.
        with _factory()() as s:
            mark_tenant_scoped(s, _IGREJA, source='queue_runtime_reapply')
            assert s.execute(text('select session_user, current_user')).one() == (ROLE, 'authenticated')
    _save('rollback_multi_db.json', out)


# ---------------------------------------------------------------------------
# 2. Factory proofs on the real LOGIN.
# ---------------------------------------------------------------------------
STATE = "select session_user, current_user, current_setting('role'), current_setting('search_path'), " \
        "nullif(current_setting('app.tenant_igreja_id', true), '')"


def test_factory_proves_login_before_and_church_after_the_seam(s3_turn, queue_login):
    from app.db.tenant_session import TENANT_IGREJA_KEY
    factory = _factory()
    with recording(queue_login.rec) as rec, factory() as s:
        assert tuple(s.execute(text(STATE)).one()) == (ROLE, ROLE, 'none', FIXED_PATH, None)
        s.rollback()
        mark_tenant_scoped(s, _IGREJA, source='queue_runtime_test')
        assert tuple(s.execute(text(STATE)).one()) == (ROLE, 'authenticated', 'authenticated', FIXED_PATH, str(_IGREJA))
        s.commit()
        # A new transaction is proven and scoped again; a savepoint keeps the scope.
        assert s.execute(text('select current_user')).scalar_one() == 'authenticated'
        with s.begin_nested():
            assert tuple(s.execute(text(STATE)).one())[1:] == ('authenticated', 'authenticated', FIXED_PATH, str(_IGREJA))
        with pytest.raises(TenantPinConflictError):
            mark_tenant_scoped(s, _IGREJA_B, source='queue_runtime_test')
        # Hook order is load-bearing: the login proof refuses an already scoped transaction.
        with pytest.raises(qws.QueueWorkerIdentityError, match='effective_not_login'):
            qws._prove_login(s, SimpleNamespace(nested=False, parent=None), s.connection())
        # And the scope proof refuses a transaction whose GUC is not the pinned church.
        s.execute(text("select set_config('app.tenant_igreja_id', :b, true)"), dict(b=str(_IGREJA_B)))
        with pytest.raises(qws.QueueWorkerIdentityError, match='tenant_mismatch'):
            qws._prove_scope(s, None, s.connection())
        assert s.info[TENANT_IGREJA_KEY] == str(_IGREJA)
        s.rollback()
    statements = rec.tx_statements(ROLE)
    outer = sorted(t for t, st in statements.items() if st and st[0].startswith(PROBE_PREFIX))
    assert len(outer) == 3 and all(len([x for x in statements[t] if x.startswith(PROBE_PREFIX)]) >= 2 for t in outer)
    # Real listener order on PostgreSQL: login proof -> tenant seam -> scope proof.
    for t in outer[1:]:
        first = statements[t][:3]
        assert first[0].startswith(PROBE_PREFIX) and first[2].startswith(PROBE_PREFIX), first
        assert first[1].startswith("select set_config('app.tenant_igreja_id'") and 'authenticated' in first[1], first
    assert set(rec.users()) == {ROLE}


def test_actor_claims_written_by_the_seam_are_refused_on_the_queue_login(s3_turn, queue_login):
    """The queue never scopes with an actor; if it did, the seam's JWT claim fails closed."""
    with _factory()() as s, pytest.raises(qws.QueueWorkerIdentityError, match='jwt_claims'):
        mark_tenant_scoped(s, _IGREJA, actor_sub='clerk-synthetic', source='queue_runtime_actor')


DRIFTS = {
    'nologin': (f'alter role {ROLE} nologin', f'alter role {ROLE} login'),
    'bypassrls': (f'alter role {ROLE} bypassrls', f'alter role {ROLE} nobypassrls'),
    'inherit_role': (f'alter role {ROLE} inherit', f'alter role {ROLE} noinherit'),
    'createrole': (f'alter role {ROLE} createrole', f'alter role {ROLE} nocreaterole'),
    'createdb': (f'alter role {ROLE} createdb', f'alter role {ROLE} nocreatedb'),
    'superuser': (f'alter role {ROLE} superuser', f'alter role {ROLE} nosuperuser'),
    'extra_membership': (f'grant anon to {ROLE} with inherit false, set true', f'revoke anon from {ROLE}'),
    'admin_option': (f'grant authenticated to {ROLE} with admin option', f'revoke admin option for authenticated from {ROLE}'),
    'inherit_true_grant': (f'grant authenticated to {ROLE} with inherit true', f'grant authenticated to {ROLE} with inherit false'),
    'set_false_grant': (f'grant authenticated to {ROLE} with set false', f'grant authenticated to {ROLE} with set true'),
    'has_member': (f'create role queue_runtime_third_role nologin; grant {ROLE} to queue_runtime_third_role',
                   'drop role queue_runtime_third_role'),
    'auth_chain': ('grant service_role to authenticated', 'revoke service_role from authenticated'),
    'auth_bypassrls': ('alter role authenticated bypassrls', 'alter role authenticated nobypassrls'),
    'auth_superuser': ('alter role authenticated superuser', 'alter role authenticated nosuperuser'),
    'auth_createrole': ('alter role authenticated createrole', 'alter role authenticated nocreaterole'),
    'auth_createdb': ('alter role authenticated createdb', 'alter role authenticated nocreatedb'),
    'auth_replication': ('alter role authenticated replication', 'alter role authenticated noreplication'),
    # Synthetic RLS table (never a domain table: ALTER OWNER would drop its ACL).
    'auth_owns_table': ('create table public.queue_runtime_owned(igreja_id uuid not null); '
                        'alter table public.queue_runtime_owned enable row level security; '
                        'alter table public.queue_runtime_owned owner to authenticated',
                        'drop table public.queue_runtime_owned'),
    # Direct ownership/ACL of the LOGIN itself in this database, after bootstrap.
    'login_owns_table': ('create table public.queue_runtime_owned(igreja_id uuid not null); '
                         'alter table public.queue_runtime_owned enable row level security; '
                         f'alter table public.queue_runtime_owned owner to {ROLE}',
                         'drop table public.queue_runtime_owned'),
    'login_direct_grant': (f'grant select on public.schema_migrations to {ROLE}',  # A real table without RLS.
                           f'revoke select on public.schema_migrations from {ROLE}'),
    'login_schema_create': (f'grant create on schema public to {ROLE}', f'revoke create on schema public from {ROLE}'),
    'login_usage_grant_option': (f'grant usage on schema public to {ROLE} with grant option',
                                 f'revoke grant option for usage on schema public from {ROLE}'),
    'login_execute_grant_option': (f'grant execute on function public.queue_resolve_instance(text) to {ROLE} with grant option',
                                   f'revoke grant option for execute on function public.queue_resolve_instance(text) from {ROLE}'),
    'login_default_acl': (f'alter default privileges in schema public grant select on tables to {ROLE}',
                          f'alter default privileges in schema public revoke select on tables from {ROLE}'),
}

SNAPSHOT = """select (select row(rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolreplication,rolcanlogin,rolinherit)::text
   from pg_roles where rolname='authenticated'),
 (select row(rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolreplication,rolinherit)::text from pg_roles where rolname='queue_worker_runtime'),
 (select string_agg(g.rolname||'>'||u.rolname||':'||m.admin_option||m.inherit_option||m.set_option, ',' order by g.rolname, u.rolname)
   from pg_auth_members m join pg_roles g on g.oid=m.roleid join pg_roles u on u.oid=m.member
   where u.rolname in ('queue_worker_runtime','authenticated') or g.rolname='queue_worker_runtime'),
 (select count(*) from pg_class where relowner='authenticated'::regrole),
 (select md5(string_agg(c.relname||':'||c.relowner::regrole::text||':'||coalesce(c.relacl::text,'-'), ',' order by c.relname))
   from pg_class c where c.relnamespace='public'::regnamespace),
 (select nspacl::text from pg_namespace where nspname='public'),
 (select string_agg(coalesce(proacl::text,'-'), ',' order by proname) from pg_proc
   where proname in ('queue_resolve_instance','queue_worker_runtime_session')),
 (select count(*) from pg_default_acl)"""


def _snapshot(admin):
    with admin.connect() as a:
        return tuple(a.exec_driver_sql(SNAPSHOT).one())


@pytest.mark.parametrize('drift', sorted(DRIFTS))
def test_drift_between_transactions_refuses_begin_checkout_raw_lease_and_sql_helper(s3_turn, queue_login, drift):
    login = queue_login
    factory = _factory()
    engine = factory.kw['bind']
    apply_sql, restore_sql = DRIFTS[drift]
    out = dict(drift=drift)
    baseline = _snapshot(login.admin)
    conn = engine.connect()
    try:
        s = factory(bind=conn)
        mark_tenant_scoped(s, _IGREJA, source='queue_runtime_drift')
        assert s.execute(text('select count(*) from messages')).scalar_one() > 0
        s.commit()
        with login.admin.begin() as a:
            a.exec_driver_sql(apply_sql)
        try:
            with pytest.raises(qws.QueueWorkerIdentityError) as exc:
                s.execute(text('select count(*) from messages'))
            out['same_connection_begin'] = str(exc.value).rsplit(': ', 1)[-1]
            s.rollback()
            s.close()
            conn.rollback()
            try:
                conn.execute(text('select * from queue_resolve_instance(:i)'), dict(i=INSTANCE)).all()
                out['sql_helper_same_connection'] = 'ran'
            except DBAPIError as error:
                out['sql_helper_same_connection'] = _pgcode(error)
            conn.rollback()
            for name in ('fresh_session', 'fresh_raw_connection'):
                try:
                    if name == 'fresh_session':
                        with factory() as fresh:
                            fresh.execute(text('select 1'))
                    else:  # The agent lease's raw connection, not only Session BEGIN.
                        engine.connect().close()
                    out[name] = 'accepted'
                except REFUSED as error:
                    out[name] = type(error).__name__
        finally:
            with login.admin.begin() as a:
                a.exec_driver_sql(restore_sql)
    finally:
        conn.close()
    out['restored_exactly'] = _snapshot(login.admin) == baseline
    _save(f'drift/{drift}.json', out)
    assert out['restored_exactly'], 'drift fixture did not restore the exact role/ownership state'
    if drift.startswith('login_'):
        assert out['same_connection_begin'] == 'login_privileges'
    assert out['same_connection_begin']
    assert out['sql_helper_same_connection'] == '42501'  # The SQL helper also checks both roles.
    assert out['fresh_session'] != 'accepted' and out['fresh_raw_connection'] != 'accepted'
    engine.dispose()
    with _factory()() as fresh:  # Restored: a fresh checkout proves again.
        assert fresh.execute(text('select session_user')).scalar_one() == ROLE


_RESOLVER = 'public.queue_resolve_instance(text)'


def test_unexpected_function_grant_is_refused_even_with_a_queue_function_absent(s3_turn, queue_login):
    """An absent queue function makes to_regprocedure() NULL: the allow-list must
    not turn that NULL into acceptance of an unexpected EXECUTE grant."""
    login = queue_login
    factory = _factory()
    engine = factory.kw['bind']
    out = {}
    baseline = _snapshot(login.admin)
    with login.admin.connect() as a:
        resolver = a.exec_driver_sql(
            f"select pg_get_functiondef('{_RESOLVER}'::regprocedure), "
            f"(select proowner::regrole::text from pg_proc where oid='{_RESOLVER}'::regprocedure)").one()
        grants = a.exec_driver_sql(
            "select case x.grantee when 0 then 'public' else x.grantee::regrole::text end, x.is_grantable "
            f"from pg_proc p, aclexplode(p.proacl) x where p.oid='{_RESOLVER}'::regprocedure "
            "and x.grantee<>p.proowner order by 1").all()
    conn = engine.connect()
    try:
        s = factory(bind=conn)
        mark_tenant_scoped(s, _IGREJA, source='queue_runtime_absent_function')
        assert s.execute(text('select count(*) from messages')).scalar_one() > 0
        s.commit()
        with login.admin.begin() as a:  # Committed: the LOGIN's connections must see it.
            a.exec_driver_sql(f'drop function {_RESOLVER}')
            a.exec_driver_sql("create function public.queue_runtime_unexpected() returns integer "
                              "language sql as 'select 1'")
            a.exec_driver_sql(f'grant execute on function public.queue_runtime_unexpected() to {ROLE}')
        try:
            with pytest.raises(qws.QueueWorkerIdentityError) as exc:
                s.execute(text('select count(*) from messages'))
            out['same_connection_begin'] = str(exc.value).rsplit(': ', 1)[-1]
            s.rollback()
            s.close()
            conn.rollback()
            out['sql_helper_same_connection'] = conn.execute(
                text('select public.queue_worker_runtime_session()')).scalar_one()
            conn.rollback()
            for name in ('fresh_session', 'fresh_raw_connection'):
                try:
                    if name == 'fresh_session':
                        with factory() as fresh:
                            fresh.execute(text('select 1'))
                    else:
                        engine.connect().close()
                    out[name] = 'accepted'
                except REFUSED as error:
                    out[name] = type(error).__name__
        finally:
            definition, owner = resolver
            with login.admin.begin() as a:
                a.exec_driver_sql('drop function public.queue_runtime_unexpected()')
                a.exec_driver_sql(definition)
                a.exec_driver_sql(f'alter function {_RESOLVER} owner to {owner}')
                # Default privileges grant the recreated function again; drop them all first.
                fresh_grantees = a.exec_driver_sql(
                    "select distinct case x.grantee when 0 then 'public' else x.grantee::regrole::text end "
                    f"from pg_proc p, aclexplode(p.proacl) x where p.oid='{_RESOLVER}'::regprocedure "
                    "and x.grantee<>p.proowner").scalars().all()
                a.exec_driver_sql(f"revoke all on function {_RESOLVER} from {', '.join({'public', *fresh_grantees})}")
                for grantee, grantable in grants:
                    a.exec_driver_sql(f"grant execute on function {_RESOLVER} to {grantee}"
                                      f"{' with grant option' if grantable else ''}")
    finally:
        conn.close()
    with login.admin.connect() as a:
        restored = a.exec_driver_sql(
            f"select pg_get_functiondef('{_RESOLVER}'::regprocedure), "
            f"(select proowner::regrole::text from pg_proc where oid='{_RESOLVER}'::regprocedure)").one()
    out['restored_exactly'] = _snapshot(login.admin) == baseline and tuple(restored) == tuple(resolver)
    _save('drift/login_unexpected_function_with_resolver_absent.json', out)
    assert out['restored_exactly'], 'fixture did not restore the resolver definition, owner and ACL'
    assert out['same_connection_begin'] == 'login_privileges'
    assert out['sql_helper_same_connection'] is False
    assert out['fresh_session'] != 'accepted' and out['fresh_raw_connection'] != 'accepted'
    engine.dispose()
    with _factory()() as fresh:
        assert fresh.execute(text('select session_user')).scalar_one() == ROLE


_TEMP = ['create temp table messages(id uuid, igreja_id uuid) on commit preserve rows',
         "insert into pg_temp.messages select gen_random_uuid(), '{t}' from generate_series(1,7)"]
CONTAMINATION = {
    'session_role': ['set role authenticated'],
    'tenant_guc': ["select set_config('app.tenant_igreja_id','{t}',false)"],
    'jwt_claims': ["""select set_config('request.jwt.claims','{{"sub":"forged"}}',false)"""],
    'jwt_claim_sub': ["select set_config('request.jwt.claim.sub','forged-legacy-sub',false)"],
    'search_path': ['set search_path = pg_temp, public'],
    'row_security_off': ['set row_security = off'],
    'temp_relation': _TEMP,
    'temp_relation_as_authenticated': ['set role authenticated', *_TEMP, 'reset role'],
}


@pytest.mark.parametrize('name', sorted(CONTAMINATION))
def test_pool_discards_persistent_connection_state(s3_turn, queue_login, name):
    factory = _factory()
    engine = factory.kw['bind']
    with factory() as s:
        s.execute(text('select 1'))
    raw = engine.raw_connection()
    cur = raw.cursor()
    cur.execute('select pg_backend_pid()')
    dirty = cur.fetchone()[0]
    for statement in CONTAMINATION[name]:
        cur.execute(statement.format(t=_IGREJA))
    raw.commit()
    cur.close()
    raw.close()  # Back to the pool still carrying session-level state.
    with factory() as s:
        mark_tenant_scoped(s, _IGREJA, source='queue_runtime_contamination')
        effects = dict(zip(('pid', 'prayer_jwt_sub', 'private_summary_worker', 'search_path', 'row_security',
                            'messages_resolves_to', 'unqualified', 'qualified'),
                           s.execute(text("""select pg_backend_pid(), prayer_jwt_sub(), private_summary_worker(),
                               current_setting('search_path'), current_setting('row_security'),
                               to_regclass('messages')::text, (select count(*) from messages),
                               (select count(*) from public.messages)""")).one()))
    _save(f'checkout/{name}.json', dict(effects, pid=None, reused_dirty=effects['pid'] == dirty))
    assert effects['pid'] != dirty
    assert (effects['prayer_jwt_sub'], effects['private_summary_worker'], effects['search_path'],
            effects['row_security'], effects['messages_resolves_to']) == (None, True, FIXED_PATH, 'on', 'messages')
    assert effects['unqualified'] == effects['qualified']


@pytest.mark.parametrize('option', ('-c role=authenticated', f'-c app.tenant_igreja_id={_IGREJA}',
                                    '-c row_security=off'))
def test_url_session_options_are_refused_at_every_checkout(s3_turn, database, monkeypatch, option):
    with queue_worker_login(database, monkeypatch, url_options=option):
        factory = _factory()
        with pytest.raises(REFUSED):
            with factory() as s:
                s.execute(text('select 1'))
        with pytest.raises(REFUSED):
            factory.kw['bind'].connect()


# ---------------------------------------------------------------------------
# 3. Negatives before and after the seam, churches A x B, the SQL helper.
# ---------------------------------------------------------------------------
def _denied(c, sql, params=None, prelude=()):
    """One attempt per fresh transaction; (sqlstate, first line) or None if it ran."""
    c.rollback()
    try:
        for statement in prelude:
            c.exec_driver_sql(statement)
        c.execute(text(sql), params or {})
    except DBAPIError as exc:
        return _pgcode(exc), str(exc.orig).splitlines()[0]
    finally:
        c.rollback()
    return None


def test_login_has_no_privilege_before_the_seam_and_cannot_escalate(s3_turn, queue_login):
    login = queue_login
    _seed_b(login.admin)
    engine = _factory().kw['bind']
    out = {}
    with login.admin.begin() as a:
        a.exec_driver_sql('create role queue_runtime_third_role nologin')
    with engine.connect() as c:
        tables = [r[0] for r in c.exec_driver_sql("""select c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace
            where n.nspname='public' and c.relkind in ('r','p','v','m') order by 1""")]
        out['tables_with_dml'] = [t for t in tables if c.execute(text(
            "select has_table_privilege(session_user, 'public.'||quote_ident(:t), 'select,insert,update,delete')"), dict(t=t)).scalar_one()]
        out['definers_executable'] = [r[0] for r in c.exec_driver_sql("""select p.oid::regprocedure::text from pg_proc p
            join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.prosecdef
             and has_function_privilege(session_user,p.oid,'execute') order by 1""")]
        out['scope'] = 'schema public of the local synthetic PG only'
        c.rollback()
        for table in ('messages', 'whatsapp_connections', 'conversations', 'pessoas', 'private_conversation_summaries',
                      'private_deletion_sends', 'private_deletion_event_fences', 'platform_jev_settings', 'app_users', 'igrejas'):
            out[f'select_{table}'] = _denied(c, f'select count(*) from {table}')
        for name, sql in (('set_role_postgres', 'set role postgres'), ('set_role_service_role', 'set role service_role'),
                          ('set_role_anon', 'set role anon'), ('set_config_role', "select set_config('role','service_role',true)"),
                          ('session_authorization', 'set session authorization postgres'),
                          ('grant_to_third', 'grant authenticated to queue_runtime_third_role'),
                          ('create_role', 'create role queue_runtime_never'),
                          ('alter_self', f'alter role {ROLE} bypassrls'),
                          ('create_function', 'create function public.queue_runtime_never() returns int language sql as $$select 1$$')):
            out[name] = _denied(c, sql)
        auth = ("select set_config('role','authenticated',true)",)
        out['as_authenticated'] = {
            'set_role_service_role': _denied(c, 'set local role service_role', prelude=auth),
            'set_role_postgres': _denied(c, 'set local role postgres', prelude=auth),
            'grant_to_third': _denied(c, 'grant authenticated to queue_runtime_third_role', prelude=auth),
            'resolve_instance': _denied(c, 'select * from queue_resolve_instance(:i)', dict(i=INSTANCE), prelude=auth),
            'row_security_off': _denied(c, 'select count(*) from messages', prelude=auth + ('set local row_security = off',)),
        }
        c.exec_driver_sql(auth[0])
        out['authenticated_without_church'] = {t: c.exec_driver_sql(f'select count(*) from {t}').scalar_one()
                                               for t in ('messages', 'conversations', 'pessoas', 'whatsapp_connections')}
        c.rollback()
    _save('negative_catalog.json', out)
    assert out['tables_with_dml'] == [] and out['definers_executable'] == ['queue_resolve_instance(text)']
    refusals = {k: v for k, v in out.items() if k.startswith('select_') or k in (
        'set_role_postgres', 'set_role_service_role', 'set_role_anon', 'set_config_role', 'session_authorization',
        'grant_to_third', 'create_role', 'alter_self', 'create_function')}
    refusals.update(out['as_authenticated'])
    for key, value in refusals.items():
        assert value is not None and value[0] == '42501', (key, value)
    assert set(out['authenticated_without_church'].values()) == {0}


def test_scoped_churches_never_see_or_write_each_other(s3_turn, queue_login):
    _seed_b(queue_login.admin)
    factory = _factory()
    out = {}
    for mine, other in ((_IGREJA, _IGREJA_B), (_IGREJA_B, _IGREJA)):
        with factory() as s:
            mark_tenant_scoped(s, mine, source='queue_runtime_ab')
            own = s.execute(text('select count(*) from messages where igreja_id=:t'), dict(t=mine)).scalar_one()
            foreign = {t: s.execute(text(f'select count(*) from {t} where igreja_id=:t'), dict(t=other)).scalar_one()
                       for t in ('messages', 'conversations', 'pessoas', 'whatsapp_connections')}
            insert = None
            try:
                with s.begin_nested():
                    s.execute(text("insert into messages(igreja_id,conversation_id,direcao,autor,texto,tipo) "
                                   "select :o, id, 'in','contato','x','texto' from conversations limit 1"), dict(o=other))
            except DBAPIError as exc:
                insert = _pgcode(exc)
        out['A' if mine == _IGREJA else 'B'] = dict(own=own, foreign=foreign, insert=insert)
        assert own > 0 and set(foreign.values()) == {0} and insert == '42501'
    _save('scope_a_b.json', out)


def test_resolve_instance_exact_match_single_row_and_only_this_login(s3_turn, queue_login, monkeypatch):
    from tests.private_summary_pg import private_summary_login
    login = queue_login
    _seed_b(login.admin, LONG_INSTANCE)
    engine = _factory().kw['bind']
    out = {}
    with engine.connect() as c:
        rows = c.execute(text('select * from queue_resolve_instance(:i)'), dict(i=INSTANCE)).mappings().all()
        assert len(rows) == 1 and set(rows[0]) == {'igreja_id', 'numero'} and rows[0]['igreja_id'] == _IGREJA
        assert len(LONG_INSTANCE) > 128
        assert c.execute(text('select igreja_id from queue_resolve_instance(:i)'), dict(i=LONG_INSTANCE)).scalar_one() == _IGREJA_B
        for label, value in (('unknown', 'nao-existe'), ('prefix', LONG_INSTANCE[:128]), ('suffix_space', INSTANCE + ' '),
                             ('upper', INSTANCE.upper()), ('empty', ''), ('injection', "x' or '1'='1")):
            out[label] = len(c.execute(text('select * from queue_resolve_instance(:i)'), dict(i=value)).all())
        out['null'] = len(c.execute(text('select * from queue_resolve_instance(null)')).all())
        out['original_orm_lookup'] = _denied(c, str(select(WhatsappConnection).where(WhatsappConnection.instance == 'x')
                                                    .compile(compile_kwargs={'literal_binds': True})))
        out['with_church_guc'] = _denied(c, 'select * from queue_resolve_instance(:i)', dict(i=INSTANCE),
                                         prelude=(f"select set_config('app.tenant_igreja_id', '{_IGREJA}', true)",))
    assert set(v for k, v in out.items() if isinstance(v, int)) == {0}
    assert out['original_orm_lookup'][0] == '42501' and out['with_church_guc'][0] == '42501'
    password = secrets.token_urlsafe(24)
    with login.admin.begin() as a:  # Same shape as the queue login, other name.
        a.exec_driver_sql(f"create role queue_runtime_other_login login noinherit nobypassrls password '{password}'")
        a.exec_driver_sql('grant authenticated to queue_runtime_other_login with inherit false, set true')
        a.exec_driver_sql('grant usage on schema public to queue_runtime_other_login')
    other = create_engine(login.url.set(username='queue_runtime_other_login', password=password), poolclass=NullPool)
    try:
        with other.connect() as c:
            out['other_login_without_execute'] = _denied(c, 'select * from queue_resolve_instance(:i)', dict(i=INSTANCE))
        with login.admin.begin() as a:
            a.exec_driver_sql('grant execute on function public.queue_resolve_instance(text) to queue_runtime_other_login')
        with other.connect() as c:
            out['other_login_with_execute'] = _denied(c, 'select * from queue_resolve_instance(:i)', dict(i=INSTANCE))
    finally:
        other.dispose()
    with login.admin.connect() as a:
        out['setup_superuser'] = _denied(a, 'select * from queue_resolve_instance(:i)', dict(i=INSTANCE))
    with private_summary_login(login.admin, monkeypatch):
        from app.config import get_settings
        summary = create_engine(get_settings().private_summary_database_url, poolclass=NullPool)
        try:
            with summary.connect() as c:
                out['private_summary_runtime'] = _denied(c, 'select * from queue_resolve_instance(:i)', dict(i=INSTANCE))
        finally:
            summary.dispose()
    _save('resolve_instance.json', out)
    for key in ('other_login_without_execute', 'other_login_with_execute', 'setup_superuser', 'private_summary_runtime'):
        assert out[key] and out[key][0] == '42501', key


# ---------------------------------------------------------------------------
# 4. End to end: real ingestion through the real selector, fake providers only.
# ---------------------------------------------------------------------------
def test_dedicated_ingestion_resume_turn_and_delivery_on_the_login(memory, queue_login, monkeypatch):
    turn, login = memory, queue_login
    prompts, marks = [], []
    _llm(monkeypatch, login, prompts, marks)
    with private_send_login(turn.engine, monkeypatch):
        evolution = _ObservedEvolution(login, marks)
        qw = _queue_worker(evolution)
        assert qw._session_factory is qws.get_queue_worker_session_factory()
        with recording(login.rec) as rec:
            result = qw.handle_envelope(_envelope('QUEUE-RESUME-1', 'retomar conversa'))
        after = _state_rows(login)
    assert result is worker.IngestionResult.REGISTERED
    inbound = [m for m in _rows(turn, Message) if m.provider_message_id == 'QUEUE-RESUME-1']
    assert len(inbound) == 1 and inbound[0].conversation_id == turn.conversation_id
    assert len(prompts) == 1 and 'Memória privada' in prompts[0] and summaries.TOPIC_TEXT['cultos'] in prompts[0]
    assert evolution.calls == [(INSTANCE, _PHONE, 'Resposta sintética segura.')]
    replies = [m for m in _rows(turn, Message) if m.direcao == 'out' and m.texto == 'Resposta sintética segura.']
    assert len(replies) == 1 and replies[0].agent_reply_state == 'ia'
    assert (replies[0].agent_privilege_context or {}).get('private_resume')
    with turn.engine.connect() as c:
        assert c.execute(text('select count(*) from private_deletion_sends where source_id=:s'),
                         dict(s=replies[0].id)).scalar_one() == 0  # Released by private_send_runtime.
    users = _assert_no_main_login(rec)
    tx = rec.tx_statements(ROLE)
    committed = {e[2] for e in rec.of('commit') if e[1] == ROLE}

    def tx_with(*needles):
        return [t for t, st in tx.items() if all(any(n in s for s in st) for n in needles)]
    ingest = tx_with('queue_resolve_instance', 'pg_advisory_xact_lock', 'private_deletion_event_fences', 'INSERT INTO messages')
    assert len(ingest) == 1 and ingest[0] in committed
    assert not any('FROM whatsapp_connections' in s for s in tx[ingest[0]])
    cas = tx_with('UPDATE messages SET agent_reply_state', 'INSERT INTO private_deletion_sends')
    renew = tx_with('UPDATE private_deletion_sends SET expires_at')
    assert len(cas) == 1 and cas[0] in committed and len(renew) == 1 and renew[0] in committed and renew[0] > cas[0]
    send_at = rec.index(lambda e: e[:2] == ('provider', 'evolution_send'))
    answer_at = rec.index(lambda e: e[:2] == ('provider', 'llm_answer'))
    assert rec.index(lambda e: e[0] == 'commit' and e[2] == cas[0]) < send_at
    assert rec.index(lambda e: e[0] == 'commit' and e[2] == renew[0]) < send_at
    resume = tx_with('private_conversation_summaries')
    last_before_answer = max(e[2] for e in rec.events[:answer_at] if e[0] == 'begin')
    assert [t for t in resume if t <= last_before_answer] and [t for t in resume if t > last_before_answer]
    assert any(e[0] == 'commit' and e[1] == SEND for e in rec.events[send_at:])
    _assert_no_tx_at_providers(marks)
    assert not [b for b in after[0] if b[2]] and after[1] == []
    _assert_every_begin_proven(rec)
    _save('e2e_resume.json', dict(result=result.value, sql_by_login=users, transactions=len(tx),
          ingestion_tx=tx[ingest[0]], cas_tx=tx[cas[0]], renewal_tx=tx[renew[0]],
          provider_marks=[(n, b, x) for n, (b, x) in marks], evolution_calls=len(evolution.calls)))


def test_dedicated_new_contact_holds_only_the_session_lease_through_transport(s3_turn, queue_login, monkeypatch):
    turn, login = s3_turn, queue_login
    prompts, marks, lease = [], [], []
    _llm(monkeypatch, login, prompts, marks)
    original = worker._AgentExecutionLease.acquire

    def acquire(self):
        ok = original(self)
        if ok and self._connection is not None:
            lease.append(self._connection.exec_driver_sql(
                "select current_setting('search_path'), session_user /* lease harness */").one())
            self._connection.commit()  # Back to an idle backend holding only the session lock.
        lease.append(('held', ok, _state_rows(login)))
        return ok
    monkeypatch.setattr(worker._AgentExecutionLease, 'acquire', acquire)
    with private_send_login(turn.engine, monkeypatch):
        evolution = _ObservedEvolution(login, marks)
        qw = _queue_worker(evolution, worker_id='QUEUE-RUNTIME-PUBLIC')
        with recording(login.rec) as rec:
            result = qw.handle_envelope(_envelope('QUEUE-PUBLIC-1', 'Oi, qual o horário do culto?',
                                                  phone='5500000000077', name='Visitante sintético'))
    assert result is worker.IngestionResult.REGISTERED
    inbound = [m for m in _rows(turn, Message) if m.provider_message_id == 'QUEUE-PUBLIC-1']
    assert len(inbound) == 1 and inbound[0].conversation_id != turn.conversation_id  # New person/conversation.
    _assert_no_main_login(rec)
    raw = [e for e in rec.of('sql') if e[1] == ROLE and ('pg_try_advisory_lock' in e[3] or 'pg_advisory_unlock' in e[3])]
    assert [e for e in raw if 'pg_try_advisory_lock' in e[3]] and [e for e in raw if 'pg_advisory_unlock' in e[3]]
    assert tuple(lease[0]) == (FIXED_PATH, ROLE)  # The raw lease connection passed the checkout guard.
    held_backends, held_locks = lease[1][2]
    assert lease[1][1] is True and [x for x in held_locks if x[1] == 'advisory' and x[3]]
    assert all(not b[2] for b in held_backends)
    _assert_no_tx_at_providers(marks, lease_only=True)
    outbound = [m for m in _rows(turn, Message) if m.direcao == 'out' and m.conversation_id == inbound[0].conversation_id and m.texto]
    assert len(evolution.calls) == 1 and len(outbound) == 1 and outbound[0].agent_reply_state == 'ia'
    assert evolution.calls[0][2] == outbound[0].texto
    assert _state_rows(login)[1] == []
    _assert_every_begin_proven(rec)


def test_dedicated_lease_competes_and_a_blocked_worker_retries_once(s3_turn, queue_login, monkeypatch):
    turn, login = s3_turn, queue_login
    factory = _factory()
    outcome = _inbound(turn, 'LEASE-RUNTIME', 'Oi')
    first = worker._AgentExecutionLease(factory, outcome, 'agent-reply:LEASE-RUNTIME')
    second = worker._AgentExecutionLease(factory, outcome, 'agent-reply:LEASE-RUNTIME')
    assert first.acquire() is True
    try:
        assert second.acquire() is False and second._connection is None
        assert len([x for x in _state_rows(login)[1] if x[1] == 'advisory']) == 1
    finally:
        first.close()
    assert second.acquire() is True
    second.close()
    assert _state_rows(login)[1] == []
    # A worker whose lease key is held elsewhere never sends; after release it sends once.
    prompts, marks = [], []
    _llm(monkeypatch, login, prompts, marks)
    holder = {}
    original = worker._AgentExecutionLease.acquire

    def acquire(self):
        if 'lease' not in holder:
            holder['lease'] = worker._AgentExecutionLease(factory, self._outcome, self._key)
            assert original(holder['lease']) is True
        ok = original(self)
        holder.setdefault('attempts', []).append(ok)
        return ok
    monkeypatch.setattr(worker._AgentExecutionLease, 'acquire', acquire)
    with private_send_login(turn.engine, monkeypatch):
        evolution = _ObservedEvolution(login, marks)
        qw = _queue_worker(evolution, worker_id='QUEUE-RUNTIME-LEASE')
        envelope = _envelope('QUEUE-LEASE-1', 'Oi, qual o horário do culto?', phone='5500000000078', name='Visitante sintético')
        with recording(login.rec) as rec:
            with pytest.raises(worker.ClaimOwnershipLost):
                qw.handle_envelope(envelope)
            assert evolution.calls == [] and holder['attempts'] == [False]
            holder['lease'].close()
            resumed = qw.handle_envelope(envelope)
            qw.handle_envelope(envelope)  # A replay after delivery never resends.
    assert resumed.value in ('duplicate', 'registered')
    assert holder['attempts'][-1] is True and len(evolution.calls) == 1
    assert _state_rows(login)[1] == []
    _assert_no_main_login(rec)


def test_dedicated_ingestion_of_a_fenced_event_is_ignored_and_unknown_instance_skipped(s3_turn, queue_login):
    turn, login = s3_turn, queue_login
    provider_id = 'QUEUE-FENCED-1'
    digest = hashlib.sha256(provider_id.encode()).hexdigest()
    with login.admin.begin() as c:  # Setup: a deletion receipt already fenced this provider event.
        receipt = c.execute(text("""insert into private_deletion_receipts(igreja_id,scope,target_id,generation,counts,operation_id)
            values(:t,'conversa',gen_random_uuid(),1,'{}'::jsonb,gen_random_uuid()) returning id"""), dict(t=_IGREJA)).scalar_one()
        c.execute(text('insert into private_deletion_event_fences(igreja_id,event_token,receipt_id) '
                       "values(:t, md5(:t || ':' || :d)::uuid, :r)"), dict(t=str(_IGREJA), d=digest, r=receipt))
    _seed_b(login.admin, LONG_INSTANCE)
    before = len(_rows(turn, Message))
    qw = _queue_worker()
    with recording(login.rec) as rec:
        fenced = qw.handle_envelope(_envelope(provider_id, 'mensagem já excluída', phone='5500000000079'))
        unknown = qw.handle_envelope(_envelope('QUEUE-UNKNOWN-1', 'Oi', instance='nao-registrada'))
        long_name = qw.handle_envelope(_envelope('QUEUE-LONG-1', 'Oi', phone='5500000000902', instance=LONG_INSTANCE))
    assert fenced is worker.IngestionResult.IGNORED and unknown is worker.IngestionResult.SKIPPED_NOT_OFFICIAL
    assert long_name is worker.IngestionResult.REGISTERED
    assert len(_rows(turn, Message)) == before
    with login.admin.connect() as c:
        assert c.execute(text("select count(*) from messages where provider_message_id='QUEUE-LONG-1' and igreja_id=:b"),
                         dict(b=_IGREJA_B)).scalar_one() == 1
        assert c.execute(text("select count(*) from pessoas where telefone='5500000000079'")).scalar_one() == 0
    _assert_no_main_login(rec, allowed=(ROLE,))
    assert any('private_deletion_event_fences' in e[3] for e in rec.of('sql') if e[1] == ROLE)


@pytest.mark.parametrize('revoked', (False, True))
def test_dedicated_operational_action_authorized_and_refused_without_role(s3_turn, queue_login, monkeypatch, revoked):
    from app.db.models import AgentActionProposal, AgentActionReceipt, CelulaPresenca
    turn, login = s3_turn, queue_login
    calls = _fake_choices(monkeypatch, turn, 'marcar_presenca')
    with private_send_login(turn.engine, monkeypatch):
        evolution = _ClassifiedEvolution()
        qw = _queue_worker(evolution, worker_id='QUEUE-RUNTIME-S3')
        with recording(login.rec) as rec:
            assert qw.handle_envelope(_envelope('QUEUE-S3-REQ', 'Confirme presença de Alvo Sintético')).value == 'registered'
            rec.active = False  # Setup login reads/changes between turns are not part of the queue run.
            assert [p.state for p in _rows(turn, AgentActionProposal)] == ['pendente']
            if revoked:
                _revoke_role(turn)
            rec.active = True
            assert qw.handle_envelope(_envelope('QUEUE-S3-SIM', 'SIM')).value == 'registered'
    effects = len(_rows(turn, CelulaPresenca))
    receipts = _rows(turn, AgentActionReceipt)
    assert calls == ['s3_route', 's3_tool', 's3_handle']
    if revoked:
        assert effects == 0 and receipts == []
    else:
        assert effects == 1 and len(receipts) == 1 and 'Comprovante:' in evolution.calls[-1][2]
    _assert_no_main_login(rec)


@pytest.fixture
def prayer_gate(s3_turn, monkeypatch):
    """SYNTHETIC in-process prayer release for this church only; no real gate is opened."""
    from app.config import get_settings
    from app.prayer import policy
    from app.services import evolution as evolution_module

    def forbidden(*_a, **_kw):
        raise AssertionError('prayer turn reached an LLM')
    for name in ('complete', 'complete_typed', 'generate_typed'):
        monkeypatch.setattr(LLMClient, name, forbidden)

    def no_real_transport(*_a, **_kw):
        raise AssertionError('real EvolutionClient must never be constructed')
    monkeypatch.setattr(evolution_module, 'EvolutionClient', no_real_transport)
    # Same in-process setting as tests/test_prayer_requests_pg.py (fake provider only).
    monkeypatch.setenv('ALLOW_REAL_SENDS', 'true')
    monkeypatch.setenv('AGENT_TERM_VERSION', 's3-test-v1')
    monkeypatch.setenv('PRAYER_REQUEST_ENABLED_IGREJA_IDS', str(_IGREJA))
    monkeypatch.setattr(policy, 'PRAYER_REQUEST_APPROVED_RELEASE_ID', 'synthetic-queue-runtime')
    get_settings.cache_clear()
    yield s3_turn
    get_settings.cache_clear()


def test_dedicated_prayer_request_and_third_party_refusal(prayer_gate, queue_login, monkeypatch):
    from app.prayer.models import PrayerProposal, PrayerRequest
    turn, login = prayer_gate, queue_login
    marks, steps = [], []
    with private_send_login(turn.engine, monkeypatch):
        evolution = _ObservedEvolution(login, marks)
        qw = _queue_worker(evolution, worker_id='QUEUE-RUNTIME-PRAYER')
        with recording(login.rec) as rec:
            for key, body in (('PRAYER-OTHER', 'Peço oração pela Maria: estou preocupado com ela.'),
                              ('PRAYER-1', 'Peço oração por mim: preciso de força nesta semana.'),
                              ('PRAYER-2', 'Só pastores'), ('PRAYER-3', 'SIM')):
                steps.append(qw.handle_envelope(_envelope('QUEUE-' + key, body)).value)
                if key == 'PRAYER-OTHER':
                    rec.active = False  # Verification on the setup login, between turns.
                    with turn.engine.connect() as c:
                        refused = (c.execute(select(func.count()).select_from(PrayerRequest)).scalar_one(),
                                   c.execute(select(func.count()).select_from(PrayerProposal)).scalar_one())
                    rec.active = True
    sim = [m for m in _rows(turn, Message) if m.provider_message_id == 'QUEUE-PRAYER-3']
    with turn.engine.connect() as c:
        requests = c.execute(select(PrayerRequest.confirmation_message_id, PrayerRequest.audience)).all()
    assert steps == ['registered'] * 4 and refused == (0, 0)
    assert 'pedido próprio' in evolution.calls[0][2]
    assert len(evolution.calls) == 4 and evolution.calls[3][2].startswith('Pedido de oração registrado')
    assert len(requests) == 1 and requests[0][0] == sim[0].id and requests[0][1] == 'pastoral'
    assert [e for e in rec.of('sql') if e[1] == ROLE and 'pedido_oracao' in e[3]]
    _assert_no_main_login(rec)
    _assert_no_tx_at_providers(marks, lease_only=True)


def test_dedicated_unreadable_jev_settings_hand_off_without_egress(memory, queue_login, monkeypatch):
    """Privileged turn, synthetic in-process Tier A list: the platform settings are
    unreadable to the queue login (no grant, no key); the turn hands off canonically."""
    from app.services import semantic_triage
    turn, login = memory, queue_login
    monkeypatch.setattr(semantic_triage, 'TIER_A_APPROVED_RELEASE_ID', 'synthetic-queue-runtime')
    monkeypatch.setattr(semantic_triage, 'tier_a_enabled_from_environment', lambda _id: True)
    transport = []

    def no_transport(*_a, **_kw):
        transport.append(1)
        raise AssertionError('Jev transport must never be reached')
    monkeypatch.setattr(worker, '_run_tier_a_batch', no_transport)
    prompts, marks = [], []
    _llm(monkeypatch, login, prompts, marks)
    with private_send_login(turn.engine, monkeypatch):
        evolution = _ObservedEvolution(login, marks)
        qw = _queue_worker(evolution, worker_id='QUEUE-RUNTIME-JEV')
        with recording(login.rec) as rec:
            result = qw.handle_envelope(_envelope('QUEUE-JEV-1', 'Qual o horário do culto?'))
    states = [(m.direcao, m.agent_reply_state) for m in _rows(turn, Message) if m.conversation_id == turn.conversation_id]
    with turn.engine.connect() as c:
        estado = c.execute(text('select estado from conversations where id=:c'), dict(c=turn.conversation_id)).scalar_one()
    _save('jev_unreadable.json', dict(result=result.value, states=states, estado=estado, prompts=len(prompts),
                                      evolution=len(evolution.calls), transport=len(transport)))
    assert result is worker.IngestionResult.REGISTERED
    assert transport == [] and prompts == []
    # Canonical persisted handoff (suppressed reply, human conversation); no orphan ia_reservada.
    assert [s for d, s in states if d == 'out'] == ['ia_suprimida'] and estado == 'humano'
    assert evolution.calls == []
    denied = [e for e in rec.of('sql') if e[1] == ROLE and 'platform_jev_settings' in e[3]]
    assert denied  # The short settings session was attempted on the login and refused.
    _assert_no_main_login(rec)


def test_legacy_mode_keeps_the_main_session_and_orm_lookup(s3_turn, monkeypatch):
    """Default mode: the main factory and the original lookup, with the migration installed."""
    turn = s3_turn
    monkeypatch.setattr(worker.get_settings(), 'queue_worker_database_mode', 'legacy', raising=False)
    monkeypatch.setattr(worker, 'get_session_factory', lambda: turn.factory)

    def dedicated():
        raise AssertionError('legacy mode resolved the dedicated factory')
    monkeypatch.setattr(qws, 'get_queue_worker_session_factory', dedicated)
    observer = create_engine(turn.engine.url, poolclass=NullPool)
    rec = Recorder(observer)
    qw = _queue_worker()
    assert qw._session_factory is turn.factory
    with recording(rec):
        result = qw.handle_envelope(_envelope('QUEUE-LEGACY-1', 'Oi', phone='5500000000080'))
    observer.dispose()
    assert result is worker.IngestionResult.REGISTERED
    statements = [e[3] for e in rec.of('sql')]
    assert ROLE not in rec.users() and any('FROM whatsapp_connections' in s for s in statements)
    assert not any('queue_resolve_instance' in s or s.startswith(PROBE_PREFIX) for s in statements)
