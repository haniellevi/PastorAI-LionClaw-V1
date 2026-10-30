"""Read-only database observer/ledger proof over a fake DB-API connection; no PostgreSQL is used."""
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_database as fdb
from first_transition_adapter import Refused, baseline_digest, digest
from first_transition_database import (DatabaseExpectation, LedgerProof, ReadOnlyDatabase, require_ddl_free,
                                       require_quiet)

RLS_OFF = "SELECT set_config('row_security', 'off', true)"
SCOPE = 'c' * 64
SECRET = 'SENTINEL-DB-SECRET'
STATEMENTS = {RLS_OFF, fdb.Q_BEGIN, fdb.Q_TIMEOUT, fdb.Q_PATH, fdb.Q_READ_ONLY, fdb.Q_IDENTITY, fdb.Q_VISIBILITY,
              fdb.Q_LEDGER, fdb.Q_INVALID, fdb.Q_INDEXES, fdb.Q_BUILDS, fdb.Q_CATALOG, fdb.Q_WRITERS,
              fdb.Q_RELATION, 'ROLLBACK', *(fdb.lease_query(t, c) for t, c in fdb.LEASES)}


@pytest.fixture(autouse=True)
def no_real_processes_or_network(monkeypatch):
    def forbid(*_args, **_kwargs):
        raise AssertionError('real process/network forbidden')
    for module, names in ((subprocess, ('Popen', 'run')), (os, ('system', 'fork', 'execv', 'execve')),
                          (socket, ('socket', 'create_connection'))):
        for name in names:
            monkeypatch.setattr(module, name, forbid)


class FakePg:
    """Synthetic database state; DDL is modelled as catalog rows derived from the ledger."""

    def __init__(self, ledger):
        self.system, self.oid, self.name = '7300000000000000001', 16384, 'postgres'
        self.read_only, self.visible = 'on', True
        self.rls_applies, self.row_security = False, 'on'
        self.ledger = list(ledger)
        self.extra_ddl = []
        # Definition text per covered object; the fake "server" hashes it like md5(row(...)::text).
        self.definitions = {
            ('attribute', 'notification_outbox.claimed_until'): '(5,"timestamp with time zone",f,f,,"","",,,,p)',
            ('constraint', 'pessoas.pessoas_pkey'): '(p,f,f,t,f,"PRIMARY KEY (id)")',
            ('function', 'touch_updated_at()'): '(f,app,,,f,f,f,v,u,trigger,"CREATE FUNCTION ... BODY")',
            ('index', 'base_idx'): '("CREATE INDEX base_idx ON public.pessoas USING btree (id)",f,f,f,t,t,t,t,f,f)',
            ('policy', 'pessoas.tenant_isolation'): '(r,t,{app},"(igreja_id = current_igreja())",)',
            ('trigger', 'pessoas.pessoas_touch'): '(O,"CREATE TRIGGER pessoas_touch ...")',
            ('relation', 'pessoas'): '(r,app,,t,f,p,d,,f,-,,,,{})',
        }
        self.invalid, self.indexes, self.builds = [], ['base_idx'], 0
        self.lease_pairs = list(fdb.LEASES)
        self.writers, self.leases = 0, {t: 0 for t, _ in fdb.LEASES}
        self.missing_relations = set()
        self.executed, self.connections, self.closed = [], 0, 0
        self.fail_on = None
        self.on_connect = None

    def catalog_rows(self, ledger=None):
        names = sorted(self.ledger if ledger is None else ledger)
        definitions = {('relation', 'rel_' + name[:20]): '(r,app,' + name + ')' for name in names}
        definitions.update(self.definitions)
        definitions.update({('relation', name): '(r,rogue)' for name in self.extra_ddl})
        return sorted([kind, name, hashlib.md5(text.encode()).hexdigest()]
                      for (kind, name), text in definitions.items())

    def catalog(self, ledger=None):
        return digest(self.catalog_rows(ledger))

    def identity(self):
        return digest([self.system, self.oid, self.name])

    def expectation(self, ledger=None):
        ledger = tuple(sorted(self.ledger if ledger is None else ledger))
        return DatabaseExpectation(self.identity(), ledger, self.catalog(ledger))

    def connect(self, *, timeout):
        assert 0 < timeout <= 30
        self.connections += 1
        if self.on_connect:
            self.on_connect()
        if self.fail_on == 'connect':
            raise OSError('could not connect: password=' + SECRET)
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, pg):
        self.pg, self.autocommit = pg, False

    def cursor(self):
        return FakeCursor(self.pg)

    def close(self):
        self.pg.closed += 1


class FakeCursor:
    def __init__(self, pg):
        self.pg, self.rows = pg, None

    def execute(self, query, params=None):
        pg = self.pg
        lease = {fdb.lease_query(t, c): t for t, c in pg.lease_pairs}
        assert query in STATEMENTS or query in lease, query
        pg.executed.append((query, params))
        if pg.fail_on == query:
            raise RuntimeError('server error near ' + SECRET)
        if query == RLS_OFF:
            pg.row_security = 'off'
            self.rows = [('off',)]
            return
        answers = {
            fdb.Q_TIMEOUT: lambda: [(params[0],)], fdb.Q_PATH: lambda: [('pg_catalog,public',)],
            fdb.Q_READ_ONLY: lambda: [(pg.read_only,)], fdb.Q_IDENTITY: lambda: [(pg.system, pg.oid, pg.name)],
            fdb.Q_VISIBILITY: lambda: [(pg.visible,)], fdb.Q_LEDGER: lambda: [(n,) for n in sorted(pg.ledger)],
            fdb.Q_INVALID: lambda: [(n,) for n in pg.invalid], fdb.Q_INDEXES: lambda: [(n,) for n in pg.indexes],
            fdb.Q_BUILDS: lambda: [(pg.builds,)], fdb.Q_CATALOG: lambda: [tuple(r) for r in pg.catalog_rows()],
            fdb.Q_WRITERS: lambda: [(pg.writers,)],
            fdb.Q_RELATION: lambda: [(params[0].removeprefix('public.') not in pg.missing_relations,)],
        }
        if query in lease:
            if pg.rls_applies and pg.row_security != 'off':
                self.rows = [(0,)]  # a filtered empty view must not prove absence
            else:
                self.rows = [(pg.leases[lease[query]],)]
        else:
            self.rows = answers.get(query, lambda: None)()

    def fetchall(self):
        return self.rows


LEDGER = ['0001_base.sql', '0002_more.sql']


def make():
    pg = FakePg(LEDGER)
    return pg, ReadOnlyDatabase(pg.connect)


def test_observation_is_read_only_aggregate_and_always_rolled_back_and_closed():
    pg, database = make()
    observation = database.observe(timeout=5)
    assert observation['ledger'] == tuple(LEDGER) and observation['identity'] == pg.identity()
    assert observation['catalog'] == pg.catalog() and observation['writing_sessions'] == 0
    assert baseline_digest(observation) == pg.expectation().baseline_digest
    queries = [q for q, _ in pg.executed]
    assert queries[0] == fdb.Q_BEGIN and queries[-1] == 'ROLLBACK' and pg.closed == 1
    assert ('5000ms',) in [p for q, p in pg.executed if q == fdb.Q_TIMEOUT]
    text = ' '.join(queries).lower()
    for forbidden in ('insert ', 'update ', 'delete ', 'create ', 'alter ', 'drop ', 'truncate', ' query',
                      'client_addr', 'usename', 'select *'):
        assert forbidden not in text
    # Writers exclude only the observer's own PID: no application name is passed or exempted.
    assert [p for q, p in pg.executed if q == fdb.Q_WRITERS] == [None]


def test_writer_and_visibility_predicates_cannot_be_bypassed_by_names():
    writers = fdb.Q_WRITERS
    assert 'application_name' not in writers and '%s' not in writers
    assert "pid<>pg_backend_pid()" in writers and "state IS DISTINCT FROM 'idle'" in writers
    assert 'backend_xid IS NOT NULL OR' in writers and 'AND NOT' not in writers
    assert "'pg_read_all_stats', 'USAGE')" in fdb.Q_VISIBILITY and 'MEMBER' not in fdb.Q_VISIBILITY
    # A configured observer name is still validated, yet changes neither the SQL nor its parameters.
    pg = FakePg(LEDGER)
    pg.writers = 1  # e.g. an active session labelled with an observer name, no xid yet
    observation = ReadOnlyDatabase(pg.connect, observer_applications=('ops-observer',)).observe(timeout=5)
    assert observation['writing_sessions'] == 1
    assert [p for q, p in pg.executed if q == fdb.Q_WRITERS] == [None]
    with pytest.raises(Refused, match='^database-writing-session$'):
        require_quiet(observation)


@pytest.mark.parametrize('change, code', [
    (lambda pg: setattr(pg, 'read_only', 'off'), 'database-not-read-only'),
    (lambda pg: setattr(pg, 'visible', False), 'database-activity-not-visible'),
    (lambda pg: pg.missing_relations.add('notification_outbox'), 'database-lease-relation'),
    (lambda pg: setattr(pg, 'fail_on', fdb.Q_LEDGER), 'database-observation-failed'),
    (lambda pg: setattr(pg, 'fail_on', 'connect'), 'database-observation-failed'),
    (lambda pg: setattr(pg, 'builds', -1), 'database-observation-shape'),
    (lambda pg: pg.ledger.append('bad name'), 'database-ledger-shape'),
])
def test_observation_failures_are_fixed_codes_without_secret(change, code):
    pg, database = make()
    change(pg)
    with pytest.raises(Refused, match='^' + code + '$') as raised:
        database.observe(timeout=5)
    assert SECRET not in repr(raised.value) and raised.value.__cause__ is None
    assert pg.closed == pg.connections - (pg.fail_on == 'connect')


@pytest.mark.parametrize('change, code', [
    (lambda pg: pg.ledger.append('0003_new.sql'), 'database-ledger-drift'),
    (lambda pg: pg.extra_ddl.append('rogue_table'), 'database-ddl-drift'),
    (lambda pg: setattr(pg, 'system', '7300000000000000002'), 'database-identity-mismatch'),
    (lambda pg: setattr(pg, 'name', 'other_db'), 'database-identity-mismatch'),
    (lambda pg: pg.invalid.append('half_built_idx'), 'database-ddl-in-progress'),
    (lambda pg: setattr(pg, 'builds', 1), 'database-ddl-in-progress'),
])
def test_ledger_proof_rejects_any_ddl_or_ledger_drift(change, code):
    pg, database = make()
    proof = LedgerProof(database, pg.expectation(), scope=SCOPE)
    assert proof.prove(SCOPE, timeout=5)['ddl_free'] is True
    change(pg)
    with pytest.raises(Refused, match='^' + code + '$'):
        proof.prove(SCOPE, timeout=5)


def _define(kind, name, text):
    return lambda pg: pg.definitions.__setitem__((kind, name), text)


# Out-of-journal DDL that keeps relations, attribute names/types, ledger and index names unchanged.
CATALOG_ONLY_DDL = {
    'column-default': _define('attribute', 'notification_outbox.claimed_until',
                              '(5,"timestamp with time zone",f,t,now(),"","",,,,p)'),
    'function-body': _define('function', 'touch_updated_at()', '(f,app,,,f,f,f,v,u,trigger,"CREATE ... OTHER")'),
    'function-security-definer': _define('function', 'touch_updated_at()',
                                         '(f,app,,,t,f,f,v,u,trigger,"CREATE FUNCTION ... BODY")'),
    'policy-qual': _define('policy', 'pessoas.tenant_isolation', '(r,t,{app},true,)'),
    'policy-roles': _define('policy', 'pessoas.tenant_isolation', '(r,t,{-},"(igreja_id = current_igreja())",)'),
    'constraint-def': _define('constraint', 'pessoas.pessoas_pkey', '(p,f,f,t,f,"PRIMARY KEY (id, igreja_id)")'),
    'constraint-not-valid': _define('constraint', 'pessoas.pessoas_pkey', '(p,f,f,f,f,"PRIMARY KEY (id)")'),
    'index-definition': _define('index', 'base_idx',
                                '("CREATE UNIQUE INDEX base_idx ON public.pessoas USING btree (id)",t,f,f,t,t,t,t,f,f)'),
    'trigger-disabled': _define('trigger', 'pessoas.pessoas_touch', '(D,"CREATE TRIGGER pessoas_touch ...")'),
    'rls-disabled': _define('relation', 'pessoas', '(r,app,,f,f,p,d,,f,-,,,,{})'),
    'new-policy': _define('policy', 'pessoas.allow_all', '(*,t,{-},true,true)'),
}


@pytest.mark.parametrize('ddl', sorted(CATALOG_ONLY_DDL))
def test_catalog_fingerprint_covers_definitions_beyond_relation_identity(ddl):
    pg, database = make()
    proof = LedgerProof(database, pg.expectation(), scope=SCOPE)
    before = database.observe(timeout=5)
    proof.prove(SCOPE, timeout=5)
    CATALOG_ONLY_DDL[ddl](pg)
    after = database.observe(timeout=5)
    assert (after['ledger'], after['indexes'], after['invalid'], after['index_builds']) == (
        before['ledger'], before['indexes'], before['invalid'], before['index_builds'])
    assert after['catalog'] != before['catalog']
    with pytest.raises(Refused, match='^database-ddl-drift$'):
        proof.prove(SCOPE, timeout=5)


def test_catalog_query_hashes_every_definition_server_side():
    query = fdb.Q_CATALOG
    assert query.startswith('SELECT kind, name, md5(definition) AS hash FROM (')
    for kind in fdb.CATALOG_KINDS:
        assert "'" + kind + "'" in query
    for covered in ('pg_get_expr(d.adbin, d.adrelid)', 'attidentity', 'attgenerated', 'pg_get_constraintdef',
                    'convalidated', 'pg_get_indexdef', 'indisvalid', 'indisready', 'pg_get_triggerdef', 'tgenabled',
                    'pg_get_expr(p.polqual', 'pg_get_expr(p.polwithcheck', 'polroles', 'pg_get_functiondef',
                    'proconfig', 'proacl', 'prosecdef', 'relacl', 'relowner', 'relrowsecurity',
                    'relforcerowsecurity', 'pg_get_viewdef', 'pg_enum', 'pg_sequence', 'nspacl', 'pg_default_acl',
                    'pg_get_ruledef', 'pg_aggregate'):
        assert covered in query, covered
    # pg_get_functiondef is never called on an aggregate; only kind/name/md5 leave the server.
    assert "CASE WHEN p.prokind <> 'a' THEN pg_get_functiondef(p.oid) END" in query
    assert query.count('pg_get_functiondef') == 1 and '%' not in query and ';' not in query
    for forbidden in ('pg_dump', 'insert ', 'update ', 'delete ', 'create ', 'alter ', 'drop ', 'truncate'):
        assert forbidden not in query.lower()


@pytest.mark.parametrize('rows', [
    [], [('relation', 'x')], [('relation', 'x', 'CREATE FUNCTION f() ... secret body')],
    [('relation', 'x', 'A' * 32)], [('bogus', 'x', 'a' * 32)], [('relation', '', 'a' * 32)],
])
def test_catalog_rows_must_be_kind_name_md5_only(rows):
    pg, database = make()
    pg.catalog_rows = lambda ledger=None: rows
    with pytest.raises(Refused, match='^database-catalog-shape$') as raised:
        database.observe(timeout=5)
    assert 'secret' not in repr(raised.value)


@pytest.mark.parametrize('field, value, code', [
    ('identity', '0' * 64, 'database-identity-mismatch'), ('read_only', False, 'database-not-read-only'),
    ('activity_visible', None, 'database-not-read-only'),
])
def test_same_database_requires_identity_read_only_and_visible_activity(field, value, code):
    pg, database = make()
    observation = database.observe(timeout=5)
    fdb.require_same_database(observation, pg.expectation())
    with pytest.raises(Refused, match='^' + code + '$'):
        fdb.require_same_database({**observation, field: value}, pg.expectation())


def test_ledger_proof_is_fresh_per_call_and_scope_bound():
    pg, database = make()
    proof = LedgerProof(database, pg.expectation(), scope=SCOPE)
    for _ in range(3):
        proof.prove(SCOPE, timeout=5)
    assert pg.connections == 3
    with pytest.raises(Refused, match='^database-proof-scope$'):
        proof.prove('d' * 64, timeout=5)
    assert pg.connections == 3
    with pytest.raises(Refused, match='^database-proof-source$'):
        LedgerProof(object(), pg.expectation(), scope=SCOPE)
    with pytest.raises(Refused, match='^database-expectation$'):
        LedgerProof(database, DatabaseExpectation('x', (), 'y'), scope=SCOPE)


@pytest.mark.parametrize('field, value, code', [
    ('writers', 1, 'database-writing-session'),
    ('leases', {'notification_outbox': 2}, 'database-active-lease'),
])
def test_quiet_requires_zero_writers_and_zero_leases(field, value, code):
    pg, database = make()
    require_quiet(database.observe(timeout=5))
    if field == 'leases':
        pg.leases.update(value)
    else:
        setattr(pg, field, value)
    observation = database.observe(timeout=5)
    require_ddl_free(observation, pg.expectation())  # quiet is a separate requirement
    with pytest.raises(Refused, match='^' + code + '$'):
        require_quiet(observation)


@pytest.mark.parametrize('kwargs', [
    dict(lease_columns=(('bad-name', 'x'),)), dict(lease_columns=()), dict(observer_applications=('a b',)),
    dict(lease_columns=(('t', 'c'), ('t', 'c'))), dict(lease_columns=(('notification_outbox', 'claimed_until'),)),
    dict(lease_columns=tuple(p for p in fdb.LEASES if p[0] != 'broadcast_entregas')),
    *(dict(lease_columns=tuple(p for p in fdb.LEASES if p != omitted)) for omitted in fdb.LEASES),
])
def test_configuration_is_validated_before_any_connection(kwargs):
    pg = FakePg(LEDGER)
    with pytest.raises(Refused, match='^database-'):
        ReadOnlyDatabase(pg.connect, **kwargs)
    with pytest.raises(Refused, match='^database-connect-missing$'):
        ReadOnlyDatabase(None)
    assert pg.connections == 0


def test_mandatory_lease_columns_cannot_be_dropped_but_extras_are_counted():
    pg = FakePg(LEDGER)
    with pytest.raises(Refused, match='^database-lease-mandatory$'):
        ReadOnlyDatabase(pg.connect, lease_columns=(('notification_outbox', 'claimed_until'),))
    assert pg.connections == 0
    extra = ('outbox_extra', 'lease_until')
    pg.lease_pairs.append(extra)
    pg.leases['outbox_extra'] = 0
    database = ReadOnlyDatabase(pg.connect, lease_columns=(*fdb.LEASES, extra))
    require_quiet(database.observe(timeout=5))
    assert fdb.lease_query(*extra) in [q for q, _ in pg.executed]
    pg.leases['broadcast_entregas'] = 1  # a future broadcast lease is always observed
    with pytest.raises(Refused, match='^database-active-lease$'):
        require_quiet(database.observe(timeout=5))
    pg.leases.update(broadcast_entregas=0, outbox_extra=2)
    with pytest.raises(Refused, match='^database-active-lease$'):
        require_quiet(database.observe(timeout=5))


def test_psycopg2_connector_needs_a_secret_provider_and_is_inert():
    with pytest.raises(Refused, match='^database-connect-missing$'):
        fdb.psycopg2_connector(None)
    calls = []
    connect = fdb.psycopg2_connector(lambda: calls.append(1) or 'postgresql://x')
    assert callable(connect) and calls == []


def test_rls_filtered_empty_lease_count_cannot_prove_quiet():
    pg, database = make()
    pg.rls_applies = True
    pg.leases['notification_outbox'] = 1
    observation = database.observe()
    assert observation['active_leases'] == 1
    with pytest.raises(Refused, match='^database-active-lease$'):
        require_quiet(observation)


def test_row_security_refusal_stops_observation_and_closes_connection():
    pg, database = make()
    pg.fail_on = RLS_OFF
    with pytest.raises(Refused, match='^database-observation-failed$'):
        database.observe()
    assert pg.closed == 1
    assert all(q != fdb.Q_WRITERS for q, _ in pg.executed)
