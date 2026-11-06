"""Native source/snapshot orchestration over a fake driver. No source/network IO."""
from dataclasses import replace
import fcntl
import hashlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_auth_preflight as auth
import first_transition_database as db
import first_transition_window_backup as backup
from first_transition_adapter import digest
from initial_transition_ops import Refused
from test_first_transition_orchestrator import no_real_processes_or_network  # noqa: F401

SECRET = 'postgresql://postgres:SYNTHETIC-PRIVATE@origin.synthetic.invalid:5432/postgres?sslmode=verify-full'
TOKEN = '00000003-00000001-1'
NOW = 1793786400.0


class Driver:
    def __init__(self, ca_bytes):
        self.ca_bytes, self.connections, self.kwargs = ca_bytes, [], []
        self.fault = self.after = None
        self.catalog = [('relation', 'synthetic', '1' * 32)]
        self.expected = db.DatabaseExpectation('a' * 64, ('20260101_a.sql',), digest(self.catalog)).validated()

    def __call__(self, value, **kwargs):
        assert value == SECRET
        assert Path(kwargs['sslrootcert']).read_bytes() == self.ca_bytes
        fd = int(kwargs['sslrootcert'].rsplit('/', 1)[1])
        assert fcntl.fcntl(fd, backup.MEMFD_GET_SEALS) & backup.MEMFD_SEALS == backup.MEMFD_SEALS
        self.kwargs.append(kwargs)
        connection = Connection(self, kwargs, importer=bool(self.connections))
        self.connections.append(connection)
        if self.fault:
            self.fault(connection)
        if self.after:
            self.after()
        return connection


class Connection:
    def __init__(self, driver, kwargs, *, importer):
        self.driver, self.importer = driver, importer
        self.closed, self.autocommit, self.imported = 0, False, False
        self.log, self.fail_query = [], None
        self.rollback_error = self.close_error = False
        self.context = ('on', 'repeatable read', '10:20:11,12')
        self.info = SimpleNamespace(used_password=True, ssl_in_use=True, server_version=170006,
                                    transaction_status=0, dsn_parameters=dict(kwargs),
                                    ssl_attribute=lambda _: 'TLSv1.3')

    def cursor(self):
        assert not self.closed
        return Cursor(self)

    def close(self):
        self.closed = 1
        if self.close_error:
            raise RuntimeError('SYNTHETIC-PRIVATE-CLOSE')


class Cursor:
    def __init__(self, connection):
        self.connection, self.description = connection, None
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, query, params=None):
        c = self.connection
        assert not c.closed
        c.log.append((query, params))
        if query == c.fail_query:
            raise RuntimeError('SYNTHETIC-PRIVATE-QUERY')
        if query == db.Q_BEGIN:
            assert c.info.transaction_status == 0
            c.info.transaction_status = 2
        elif query == backup.NativeSourceSnapshot.Q_IMPORT:
            assert len(c.log) == 2 and c.log[0][0] == db.Q_BEGIN
            assert params == (TOKEN,) and not c.driver.connections[0].closed
            assert c.driver.connections[0].info.transaction_status == 2
            c.imported = True
        elif query == 'ROLLBACK':
            c.info.transaction_status = 0
            if c.rollback_error:
                raise RuntimeError('SYNTHETIC-PRIVATE-ROLLBACK')
        else:
            assert c.info.transaction_status == 2
            assert not c.importer or c.imported, 'SELECT before importer snapshot'
            if query == db.Q_TIMEOUT:
                assert 0 < int(params[0].removesuffix('ms')) <= 8000
                self.rows = [(params[0],)]
            elif query == backup.NativeSourceSnapshot.Q_CONTEXT:
                self.rows = [c.context]
            elif query == backup.NativeSourceSnapshot.Q_EXPORT:
                self.rows = [(TOKEN,)]
            elif query == backup.NativeSourceSnapshot.Q_HOLDER:
                value = dict(database='postgres',readonly=c.context[0],isolation=c.context[1],snapshot=c.context[2],
                             backend=1001,role='postgres',session_role='postgres',transaction_start=str(NOW))
                value.update(getattr(c,'holder_fault',{}))
                self.rows = [(value,)]
            elif query == auth.QUERY:
                row = dict(database_ok=True, current_role_ok=True, session_role_ok=True,
                    managed_profile_conformant=True, authentication_state_unmasked=True,
                    target_count=1, effective_setting_count=3, masked_or_unknown_sources=0,
                    authenticated_backend_count=1, unsafe_persisted_entries=0, duplicate_persisted_groups=0,
                    relevant_persisted_entries=0, source_identity_sha256=c.driver.expected.identity,
                    observed_at=NOW, server_version_num=170006, startup_profile='supabase-17.6.1.127')
                if hasattr(c, 'safety_fault'):
                    row.update(c.safety_fault)
                self.description = [(key,) for key in row]
                self.rows = [tuple(row.values())]
            elif query == db.Q_LEDGER:
                self.rows = [(name,) for name in getattr(c, 'ledger', c.driver.expected.ledger)]
            elif query == db.Q_CATALOG:
                self.rows = getattr(c, 'catalog', c.driver.catalog)
            elif query == 'SELECT synthetic_reader':
                self.rows = [(7,)]
            else:
                raise AssertionError('unlisted query')

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


@pytest.fixture
def source(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith('PG'):
            monkeypatch.delenv(key)
    tmp_path.chmod(0o700)
    path = tmp_path / 'synthetic-ca.crt'
    ca = b'PUBLIC-SYNTHETIC-CA-NOT-A-CERTIFICATE'
    path.write_bytes(ca)
    path.chmod(0o600)
    policy = backup.NativeSourcePolicy('origin.synthetic.invalid', '192.0.2.10', 5432,
                                       str(path), hashlib.sha256(ca).hexdigest(), os.geteuid())
    driver = Driver(ca)
    connector = backup.NativeSourceConnector(policy, secret=lambda: SECRET, driver=driver)
    return SimpleNamespace(policy=policy, driver=driver, connector=connector, path=path)


def session(source):
    return backup.NativeSourceSnapshot(source.connector, source.driver.expected, wall_clock=lambda: NOW)


def test_connector_enforces_native_policy_without_sql_and_closes_ca_fd(source):
    connection = source.connector.connect(timeout=8)
    assert connection.log == [] and connection.info.transaction_status == 0
    kwargs = source.driver.kwargs[0]
    assert kwargs['hostaddr'] == source.policy.hostaddr and kwargs['host'] == source.policy.host
    assert kwargs['sslmode'] == 'verify-full' and kwargs['gssencmode'] == 'disable'
    assert kwargs['channel_binding'] == 'require' and kwargs['sslcertmode'] == 'disable'
    assert kwargs['options'] == backup.NativeSourceConnector.OPTIONS
    assert not Path(kwargs['sslrootcert']).exists()
    connection.close()


@pytest.mark.parametrize('value', [SECRET.replace('origin.synthetic.invalid', 'other.invalid'),
    SECRET.replace(':5432', ':5433'), SECRET.replace('/postgres?', '/other?'),
    SECRET.replace('://postgres:', '://other:'), SECRET.replace('SYNTHETIC-PRIVATE', ''),
    SECRET.replace('sslmode=verify-full', 'sslmode=require'), SECRET + '&hostaddr=192.0.2.11',
    SECRET + '&options=-c+log_statement=none', SECRET + '&service=unsafe', SECRET + '#fragment',
    SECRET + '&sslmode=verify-full', SECRET + '\n', SECRET + '&sslrootcert=/other',
    SECRET.replace('origin.synthetic.invalid', 'origin.synthetic.invalid,other.invalid'),
    SECRET.replace('SYNTHETIC-PRIVATE', 'x' * 4097)])
def test_wrong_or_ambiguous_uri_refuses_before_login_or_ca_read(source, monkeypatch, value):
    calls = []
    source.connector.secret = lambda: value
    monkeypatch.setattr(source.connector, '_ca', lambda: calls.append(True))
    with pytest.raises(Refused, match='^window-origin-source-failed$'):
        source.connector.connect(timeout=8)
    assert source.driver.connections == [] and calls == []


def test_ambient_pg_refuses_before_provider(source, monkeypatch):
    monkeypatch.setenv('PGSERVICE', 'SYNTHETIC-PRIVATE')
    def forbidden():
        pytest.fail('provider read after ambient PG')
    source.connector.secret = forbidden
    with pytest.raises(Refused):
        source.connector.connect(timeout=8)
    assert source.driver.connections == []


@pytest.mark.parametrize('fault', ['hash', 'symlink', 'hardlink', 'mode', 'owner', 'empty', 'large'])
def test_ca_policy_refuses_before_login(source, fault):
    if fault == 'hash':
        source.path.write_bytes(b'other')
    elif fault == 'symlink':
        saved = source.path.with_name('saved')
        source.path.rename(saved)
        source.path.symlink_to(saved)
    elif fault == 'hardlink':
        os.link(source.path, source.path.with_name('alias'))
    elif fault == 'mode':
        source.path.chmod(0o666)
    elif fault == 'owner':
        source.connector.policy = replace(source.policy, ca_owner=source.policy.ca_owner + 1)
    elif fault == 'empty':
        source.path.write_bytes(b'')
    else:
        source.path.write_bytes(b'x' * 65537)
    with pytest.raises(Refused):
        source.connector.connect(timeout=8)
    assert source.driver.connections == []


@pytest.mark.parametrize('fault', ['password', 'tls', 'protocol', 'version', 'status', 'route', 'options', 'ca'])
def test_native_authentication_mismatch_closes_connection_without_sql(source, fault):
    def alter(c):
        if fault == 'password': c.info.used_password = False
        elif fault == 'tls': c.info.ssl_in_use = False
        elif fault == 'protocol': c.info.ssl_attribute = lambda _: 'TLSv1.1'
        elif fault == 'version': c.info.server_version = 170011
        elif fault == 'status': c.info.transaction_status = 2
        else: c.info.dsn_parameters[{'route': 'hostaddr', 'options': 'options', 'ca': 'sslrootcert'}[fault]] = 'other'
    source.driver.fault = alter
    with pytest.raises(Refused):
        source.connector.connect(timeout=8)
    assert len(source.driver.connections) == 1
    assert source.driver.connections[0].closed and source.driver.connections[0].log == []


def test_replaced_ca_during_handshake_refuses_but_driver_received_only_pinned_bytes(source):
    source.driver.after = lambda: source.path.write_bytes(b'CHANGED-CA')
    with pytest.raises(Refused):
        source.connector.connect(timeout=8)
    assert source.driver.connections[0].closed


def test_holder_and_two_readers_share_imported_snapshot_and_close(source):
    state = session(source)
    with state:
        assert state.snapshot_id() == TOKEN
        for _ in range(2):
            with state.reader() as cursor:
                cursor.execute('SELECT synthetic_reader')
                assert cursor.fetchall() == [(7,)]
        assert not source.driver.connections[0].closed
        assert all(c.closed for c in source.driver.connections[1:])
    assert len(source.driver.connections) == 3 and all(c.closed for c in source.driver.connections)
    for importer in source.driver.connections[1:]:
        assert importer.log[:2] == [(db.Q_BEGIN, None), (backup.NativeSourceSnapshot.Q_IMPORT, (TOKEN,))]
    assert all(c.log[-1] == ('ROLLBACK', None) and c.info.transaction_status == 0
               for c in source.driver.connections)
    with pytest.raises(Refused):
        with state:
            pytest.fail('reused snapshot')


@pytest.mark.parametrize('fault', ['snapshot', 'read_only', 'isolation', 'identity', 'safety', 'version', 'ledger', 'catalog'])
def test_imported_reader_mismatch_closes_reader_and_holder_without_retry(source, fault):
    def change(c):
        if not c.importer:
            return
        if fault == 'snapshot': c.context = ('on', 'repeatable read', 'different')
        elif fault == 'read_only': c.context = ('off', 'repeatable read', c.context[2])
        elif fault == 'isolation': c.context = ('on', 'read committed', c.context[2])
        elif fault == 'identity': c.safety_fault = {'source_identity_sha256': 'b' * 64}
        elif fault == 'safety': c.safety_fault = {'managed_profile_conformant': False}
        elif fault == 'version': c.safety_fault = {'server_version_num': 170011}
        elif fault == 'ledger': c.ledger = ('different.sql',)
        else: c.catalog = [('relation', 'drift', '2' * 32)]
    source.driver.fault = change
    state = session(source)
    with pytest.raises(Refused, match='^window-origin-snapshot-failed$'):
        with state:
            with state.reader():
                pytest.fail('invalid reader yielded')
    assert len(source.driver.connections) == 2 and all(c.closed for c in source.driver.connections)


@pytest.mark.parametrize('query', [db.Q_BEGIN, db.Q_TIMEOUT, auth.QUERY, db.Q_LEDGER, db.Q_CATALOG,
                                   backup.NativeSourceSnapshot.Q_EXPORT])
def test_holder_setup_query_failure_rolls_back_closes_and_sanitizes(source, query):
    source.driver.fault = lambda c: setattr(c, 'fail_query', query)
    with pytest.raises(Refused, match='^window-origin-snapshot-failed$') as error:
        with session(source):
            pytest.fail('failed holder yielded')
    assert 'PRIVATE' not in str(error.value)
    assert len(source.driver.connections) == 1 and source.driver.connections[0].closed


def test_reader_callback_interrupt_sanitizes_and_closes_both_connections(source):
    with pytest.raises(KeyboardInterrupt) as error:
        with session(source) as state:
            with state.reader():
                raise KeyboardInterrupt('SYNTHETIC-PRIVATE')
    assert str(error.value) == '' and all(c.closed for c in source.driver.connections)


@pytest.mark.parametrize('fault', ['rollback', 'close'])
def test_cleanup_failure_is_final_and_still_attempts_both_sessions(source, fault):
    state = session(source)
    with pytest.raises(Refused):
        with state:
            with state.reader():
                reader = source.driver.connections[1]
                setattr(reader, fault + '_error', True)
    assert all(c.closed for c in source.driver.connections)
    with pytest.raises(Refused):
        state.snapshot_id()


def test_expired_holder_cannot_open_or_reuse_reader(source):
    state = session(source)
    now = [1000.0]
    state.clock = lambda: now[0]
    with state:
        now[0] += 241
        with pytest.raises(Refused):
            with state.reader():
                pytest.fail('expired reader yielded')
    assert len(source.driver.connections) == 1 and source.driver.connections[0].closed


@pytest.mark.parametrize('change', ['ended', 'reopened', 'read_write', 'holder_dead'])
def test_collector_losing_transaction_or_snapshot_cannot_return_success(source, change):
    state = session(source)
    with pytest.raises(Refused):
        with state:
            with state.reader():
                reader = source.driver.connections[1]
                if change == 'ended':
                    reader.info.transaction_status = 0
                elif change == 'reopened':
                    reader.context = ('on', 'repeatable read', 'new-snapshot')
                elif change == 'read_write':
                    reader.context = ('off', 'repeatable read', reader.context[2])
                else:
                    source.driver.connections[0].info.transaction_status = 0
    assert all(c.closed for c in source.driver.connections)


def test_nested_reader_misuse_aborts_all_owned_sessions(source):
    state = session(source)
    with pytest.raises(Refused):
        with state:
            with state.reader():
                with state.reader():
                    pytest.fail('nested reader accepted')
    assert len(source.driver.connections) == 2 and all(c.closed for c in source.driver.connections)


def test_native_driver_exception_never_exposes_dsn_or_private_error(source):
    def fail(*_args, **_kwargs):
        raise RuntimeError(SECRET)
    source.connector.driver = fail
    with pytest.raises(Refused, match='^window-origin-source-failed$') as error:
        source.connector.connect(timeout=8)
    assert 'SYNTHETIC' not in str(error.value)


@pytest.mark.parametrize('interrupted', [False, True])
def test_failed_token_request_closes_holder_immediately_even_if_caller_catches(source, monkeypatch, interrupted):
    with session(source) as state:
        holder = source.driver.connections[0]
        if interrupted:
            def fail():
                raise KeyboardInterrupt('SYNTHETIC-PRIVATE')
            monkeypatch.setattr(state, '_live', fail)
        else:
            holder.fail_query = backup.NativeSourceSnapshot.Q_CONTEXT
        with pytest.raises(KeyboardInterrupt if interrupted else Refused) as error:
            state.snapshot_id()
        assert 'SYNTHETIC' not in str(error.value)
        assert holder.closed and state._holder is None


def test_controlled_holder_uses_exporter_not_an_imported_backend(source):
    with session(source) as state:
        with state.holder_cursor() as holder:
            assert set(holder.state()) == state.HOLDER_FIELDS
            assert holder.state()['backend'] == 1001
            holder.execute('SELECT synthetic_reader')
            assert holder.fetchone() == (7,)
            assert state.snapshot_id() == TOKEN
        assert len(source.driver.connections) == 1
        with pytest.raises(Refused):holder.state()
        with state.reader() as reader:
            reader.execute('SELECT synthetic_reader')
            assert reader.fetchall() == [(7,)]


@pytest.mark.parametrize('key,value', [('database','other'),('role','other'),('session_role','other'),
    ('backend',1002),('backend',True),('transaction_start',str(NOW+1)),('transaction_start','nan')])
def test_eight_field_holder_change_aborts_before_collector_query(source,key,value):
    with pytest.raises(Refused):
        with session(source) as state:
            with state.holder_cursor() as holder:
                source.driver.connections[0].holder_fault = {key:value}
                holder.execute('SELECT synthetic_reader')
    assert source.driver.connections[0].closed
    assert not any(q == 'SELECT synthetic_reader' for q,_ in source.driver.connections[0].log)


@pytest.mark.parametrize('misuse', ['nested_holder','importer','pending','double_execute'])
def test_holder_cursor_sequential_atomic_contract_closes_on_misuse(source,misuse):
    with pytest.raises(Refused):
        with session(source) as state:
            with state.holder_cursor() as holder:
                if misuse == 'nested_holder':
                    with state.holder_cursor():pass
                elif misuse == 'importer':
                    with state.reader():pass
                else:
                    holder.execute('SELECT synthetic_reader')
                    if misuse == 'double_execute':holder.execute('SELECT synthetic_reader')
    assert all(c.closed for c in source.driver.connections)


def test_caught_holder_guard_failure_cannot_be_reversed_and_reused(source):
    with pytest.raises(Refused):
        with session(source) as state:
            with state.holder_cursor() as holder:
                connection = source.driver.connections[0]
                connection.holder_fault = {'backend':1002}
                with pytest.raises(Refused):holder.state()
                assert connection.closed
                connection.holder_fault = {}
                with pytest.raises(Refused):holder.execute('SELECT synthetic_reader')
    assert not any(q == 'SELECT synthetic_reader' for q,_ in source.driver.connections[0].log)
