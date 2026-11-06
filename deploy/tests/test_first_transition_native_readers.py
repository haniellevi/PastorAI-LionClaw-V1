"""Canonical SQL/strict recovery executed only against synthetic cursors/clone IO."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_native_readers as readers
from first_transition_adapter import digest, prepare
from first_transition_capture_contract import V3_CATEGORIES
from initial_transition_ops import Refused
from test_first_transition_native_snapshot import Connection, Cursor, session, source  # noqa: F401
from test_first_transition_orchestrator import no_real_processes_or_network  # noqa: F401
from test_first_transition_window_backup import Host, expectation, provider


def payload():
    v2 = dict(manifest=dict(roles=[dict(name='postgres',can_login=True,superuser=True,inherit=True,create_role=True,
        create_db=True,replication=True,bypass_rls=True)], memberships=[],
        extensions=[], events=[], schemas=[dict(name='public', owner='postgres', acl=None)],
        default_acl=[], functions=[], catalog=[dict(name='synthetic_table',owner='postgres',rls=False,force=False,acl=None)]),
        row_counts={'public.synthetic_table':7}, settings=[])
    v3 = {key: [] for key in V3_CATEGORIES}
    v3['schemas'] = [dict(schema='public', owner='postgres', acl=None)]
    v3['routines'] = [dict(schema='synthetic_graphql', name='synthetic_fn', args='document text',
        kind='f', owner='postgres', security_definer=False, acl=None, definition_sha256='a' * 64)]
    v3['initial_privileges'] = [dict(category='routines', identity=['synthetic_graphql','synthetic_fn','document text','f'],
        privilege_origin='e', acl=None), dict(category='schemas', identity=['synthetic_graphql'], privilege_origin='e', acl=None)]
    return v2, v3


class CollectCursor:
    def __init__(self, v2, v3):
        self.v2, self.v3, self.log, self.rows = v2, v3, [], []

    def execute(self, query):
        self.log.append(query)
        if query == "SELECT current_setting('transaction_read_only'), current_setting('transaction_isolation')":
            self.rows = [('on','repeatable read')]
        elif query == readers.sql.V3_PATH:
            self.rows = []
        elif query == readers.sql.MANIFEST:
            self.rows = [(self.v2['manifest'],)]
        elif query == readers.sql.TABLES:
            self.rows = [([['public','synthetic_table']],)]
        elif query == readers.sql.count_table('public','synthetic_table'):
            self.rows = [(self.v2['row_counts']['public.synthetic_table'],)]
        elif query == readers.sql.SETTINGS:
            self.rows = [(self.v2['settings'],)]
        elif query == readers.coverage_sql.query().encode():
            self.rows = [(self.v3,)]
        else:
            raise AssertionError('unexpected synthetic reader query')

    def fetchall(self):
        return self.rows


def test_actual_canonical_queries_collect_all_categories_without_exposing_private_payload():
    v2,v3 = payload()
    cursor = CollectCursor(v2,v3)
    sample = readers.collect_on_cursor(cursor)
    summary = sample.summary()
    assert set(summary['v3_counts']) == set(V3_CATEGORIES) and summary['v3_counts']['initial_privileges'] == 2
    assert summary['row_counts_sha256'] == digest(v2['row_counts'])
    assert 'synthetic_table' not in repr(summary) and 'synthetic_fn' not in repr(summary)
    assert readers.sql.MANIFEST in cursor.log and readers.sql.TABLES in cursor.log
    assert readers.coverage_sql.query().encode() in cursor.log
    v2['row_counts']['public.synthetic_table'] = 100
    assert sample.summary() == summary


def test_canonical_collectors_use_the_authenticated_imported_snapshot(source, monkeypatch):
    v2,v3 = payload()
    class CombinedCursor(Cursor):
        def execute(self, query, params=None):
            data = CollectCursor(v2,v3)
            try:
                data.execute(query)
            except AssertionError:
                return super().execute(query,params)
            assert self.connection.importer and self.connection.imported
            self.connection.log.append((query,params))
            self.rows = data.rows
    monkeypatch.setattr(Connection, 'cursor', lambda c: CombinedCursor(c))
    with session(source) as state:
        sample = readers.collect_source(state)
        assert sample.summary()['v3_counts']['initial_privileges'] == 2
    assert len(source.driver.connections) == 2 and all(c.closed for c in source.driver.connections)


@pytest.mark.parametrize('change', ['missing-category', 'extra-field', 'negative-count', 'bool-count',
                                  'unknown-setting', 'duplicate-setting', 'bad-manifest'])
def test_canonical_inventory_refuses_malformed_or_unscoped_data(change):
    v2,v3 = payload()
    if change == 'missing-category':del v3['initial_privileges']
    elif change == 'extra-field':v3['schemas'][0]['extra']='SYNTHETIC-PRIVATE'
    elif change == 'negative-count':v2['row_counts']['public.synthetic_table']=-1
    elif change == 'bool-count':v2['row_counts']['public.synthetic_table']=False
    elif change == 'bad-manifest':del v2['manifest']['roles']
    else:
        row=dict(scope='role',role='postgres',key='unknown' if change=='unknown-setting' else 'log_statement',value='none')
        v2['settings']=[row] if change=='unknown-setting' else [row,row]
    with pytest.raises((Refused,ValueError)):
        readers.collect_on_cursor(CollectCursor(v2,v3))


@pytest.mark.parametrize('change', ['initial-privileges', 'acl-null-to-empty', 'v2-acl-null-to-empty',
                                  'row-counts', 'function-definition', 'role', 'settings', 'index-invalid'])
def test_strict_recovery_keeps_gaps_and_null_acl_distinctions(change):
    v2,v3 = payload()
    before = readers.NativeCatalogSample(v2,v3)
    actual_v2,actual_v3 = deepcopy(v2),deepcopy(v3)
    if change == 'initial-privileges':actual_v3['initial_privileges']=[]
    elif change == 'acl-null-to-empty':actual_v3['schemas'][0]['acl']=[]
    elif change == 'v2-acl-null-to-empty':actual_v2['manifest']['schemas'][0]['acl']='{}'
    elif change == 'row-counts':actual_v2['row_counts']['public.synthetic_table']+=1
    elif change == 'function-definition':actual_v3['routines'][0]['definition_sha256']='b'*64
    elif change == 'role':actual_v2['manifest']['roles'][0]['name']='other'
    elif change == 'settings':actual_v2['settings']=[dict(scope='role',role='postgres',key='log_statement',value='none')]
    else:actual_v3['indexes']=[dict(schema='public',relation='synthetic_table',name='bad',valid=False,ready=False,live=True,definition_sha256='c'*64)]
    actual = readers.NativeCatalogSample(actual_v2,actual_v3)
    result = readers.compare_recovery(before,actual)
    assert result['equal'] is False and result['automatic_repair'] is False
    if change == 'initial-privileges':
        assert result['v3_categories']['initial_privileges']['missing'] == 2
    with pytest.raises(Refused,match='recovery-mismatch'):
        readers.require_recovery_match(before,actual)


def test_v2_acl_order_and_v3_set_order_can_change_without_hiding_identity():
    v2,v3 = payload()
    v2['manifest']['schemas'][0]['acl']='{postgres=UC/postgres,anon=U/postgres}'
    before = readers.NativeCatalogSample(v2,v3)
    v2['manifest']['schemas'][0]['acl']='{anon=U/postgres,postgres=UC/postgres}'
    v3['initial_privileges'].reverse()
    actual = readers.NativeCatalogSample(v2,v3)
    result = readers.require_recovery_match(before,actual)
    assert result['equal'] is True and result['raw_source_settings_equal_claimed'] is False


@pytest.fixture(scope='module')
def plan():
    return prepare(Path(__file__).resolve().parents[2])


def test_strict_recovery_gate_drives_existing_pinned_51_migration_replay(plan,tmp_path):
    v2,v3 = payload();sample=readers.NativeCatalogSample(v2,v3)
    host=Host(plan);host.restored=True
    expected=expectation(plan);backup=provider(plan,tmp_path,host,expected)
    gate=readers.NativeRecoveryGate(plan,expected,sample,'d'*64)
    result=gate.run(sample,observe=lambda:backup._state('172.30.0.2','synthetic-clone-only'),
                    replay=lambda:backup._replay('d'*64,'172.30.0.2','synthetic-clone-only'))
    assert result['clone_rehearsal']['applied']==51 and result['clone_rehearsal']['final_ledger']==129
    assert result['clone_rehearsal']['concurrent']==8 and len(host.migrations)==51
    assert result['a8_window_proven'] is False
    with pytest.raises(Refused,match='recovery-used'):
        gate.run(sample,observe=lambda:None,replay=lambda:pytest.fail('repeated replay'))


def test_recovery_mismatch_stops_before_clone_observation_or_any_replay(plan):
    v2,v3=payload();sample=readers.NativeCatalogSample(v2,v3)
    v3['initial_privileges']=[]
    restored=readers.NativeCatalogSample(v2,v3)
    gate=readers.NativeRecoveryGate(plan,expectation(plan),sample,'d'*64)
    def forbidden():pytest.fail('IO before strict recovery acceptance')
    with pytest.raises(Refused,match='recovery-failed'):
        gate.run(restored,observe=forbidden,replay=forbidden)


def test_replay_failure_stops_at_first_migration_and_cannot_retry(plan,tmp_path):
    v2,v3=payload();sample=readers.NativeCatalogSample(v2,v3)
    host=Host(plan,fail={'migration'});host.restored=True
    expected=expectation(plan);backup=provider(plan,tmp_path,host,expected)
    gate=readers.NativeRecoveryGate(plan,expected,sample,'d'*64)
    with pytest.raises(Refused,match='recovery-failed'):
        gate.run(sample,observe=lambda:backup._state('172.30.0.2','synthetic-clone-only'),
                 replay=lambda:backup._replay('d'*64,'172.30.0.2','synthetic-clone-only'))
    assert len(host.migrations)==3
    with pytest.raises(Refused,match='recovery-used'):
        gate.run(sample,observe=lambda:None,replay=lambda:51)
    assert len(host.migrations)==3


@pytest.mark.parametrize('clone_login', [False, True])
def test_login_projection_applies_to_expected_source_only(clone_login):
    v2,v3=payload()
    v2['manifest']['roles'].append(dict(name='anon',can_login=True,superuser=False,inherit=False,create_role=False,
        create_db=False,replication=False,bypass_rls=False))
    expected=readers.NativeCatalogSample(v2,v3)
    v2['manifest']['roles'][-1]['can_login']=clone_login
    actual=readers.NativeCatalogSample(v2,v3)
    result=readers.compare_recovery(expected,actual)
    assert result['equal'] is (not clone_login)
    if clone_login:
        assert actual.summary()['v2_observed_sha256'] != actual.summary()['v2_clone_expected_sha256']
    else:
        assert actual.summary()['v2_observed_sha256'] == expected.summary()['v2_clone_expected_sha256']


def test_equal_invalid_nonpublic_indexes_still_block_replay(plan):
    v2,v3=payload()
    v3['indexes']=[dict(schema='synthetic_nonpublic',relation='t',name='bad',valid=False,ready=False,live=True,definition_sha256='b'*64)]
    sample=readers.NativeCatalogSample(v2,v3)
    assert readers.compare_recovery(sample,sample)['equal'] is True
    gate=readers.NativeRecoveryGate(plan,expectation(plan),sample,'d'*64)
    def forbidden():pytest.fail('replay with invalid indexes')
    with pytest.raises(Refused):
        gate.run(sample,observe=forbidden,replay=forbidden)


@pytest.mark.parametrize('category,key', [('relations','rls'),('relations','force_rls'),
    ('routines','security_definer'),('policies','permissive'),('indexes','valid'),('indexes','ready'),('indexes','live')])
@pytest.mark.parametrize('number',[0,1])
def test_boolean_json_numbers_are_never_accepted_as_native_flags(category,key,number):
    v2,v3=payload()
    rows={
      'relations':dict(schema='public',name='t',kind='r',owner='postgres',rls=True,force_rls=False,acl=None),
      'policies':dict(schema='public',relation='t',name='p',command='r',permissive=True,roles=[None],using_sha256=None,check_sha256=None),
      'indexes':dict(schema='public',relation='t',name='i',valid=True,ready=True,live=True,definition_sha256='c'*64)}
    if category in rows:v3[category]=[rows[category]]
    v3[category][0][key]=number
    with pytest.raises(Refused,match='reader-shape'):
        readers.NativeCatalogSample(v2,v3)


def test_v2_boolean_json_numbers_are_not_normalized_away():
    v2,v3=payload()
    v2['manifest']['roles'][0]['superuser']=1
    with pytest.raises(Refused,match='reader-shape'):
        readers.NativeCatalogSample(v2,v3)
