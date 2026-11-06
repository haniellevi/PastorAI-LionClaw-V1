"""Real window/controller composition; native origin evidence is SYNTHETIC.

No source capture, Docker, network, credentials or native V2/V3 recovery is
proved here. The trusted provider seam returns explicit synthetic attestations.
"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_database as fdb
import first_transition_origin as origin
import first_transition_window as window
from first_transition_adapter import digest
from first_transition_capture_contract import V3_CATEGORIES
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA, CLONE_FIELDS, FirstTransition
from first_transition_window_backup import (ORIGIN_PROOF_SCHEMA, ORIGIN_RECEIPT_SCHEMA,
                                            OriginWindowBackup, OriginWindowPorts, WindowBackup)
from initial_transition_files import Journal
from initial_transition_ops import Refused
from test_first_transition_auth_preflight import prepare_entry as prepare_auth_entry
from test_first_transition_origin import setup_entry as prepare_capture_entry
from test_first_transition_orchestrator import SECRET_URL, no_real_processes_or_network  # noqa: F401
from test_first_transition_window_entry import pinned  # noqa: F401


def args_for(entry, flags):
    options = dict(config=str(entry.paths['config']), backup_config=str(entry.paths['backup']),
                   bindings_config=str(entry.paths['bindings']), env_file=str(entry.secret_path),
                   env_var=entry.env_var, mode='prepare', _io=entry.io)
    options.update({key.removeprefix('--').replace('-', '_'): value
                    for key, value in zip(flags[::2], flags[1::2])})
    return SimpleNamespace(**options)


class NativeProofFixture:
    """Synthetic implementation ONLY; never usable as a native production port."""
    def __init__(self, entry):
        self.entry = entry
        self.now = window.time.time()
        self.requests, self.contexts, self.provider_values = [], [], []
        self.admissions = []
        self.fault = self.after = None

    def admit(self, *, secret, context):
        assert secret() == SECRET_URL
        self.admissions.append(deepcopy(context))

    def connect(self, *, secret, context, timeout):
        self.provider_values.append(secret())
        assert secret() == SECRET_URL
        self.contexts.append(deepcopy(context))
        return fdb.psycopg2_connector(secret, connect=self.entry.connect)(timeout=timeout)

    def backup(self, request, *, context, secret, connect, config, plan, expected):
        self.requests.append(deepcopy(request))
        events = [json.loads(line) for line in self.entry.journal_text().splitlines()]
        kinds = [event['kind'] for event in events]
        assert kinds.index('transition-quiescent') < kinds.index('transition-backup-request')
        assert 'ddl-marker' not in kinds
        assert [event for event in events if event['kind'] == 'transition-backup-request'][-1]['request'] == request
        assert secret() == SECRET_URL
        # Exercise the real legacy backup implementation only over fake IO; its
        # receipt alone is NOT sufficient for the new origin contract.
        base = WindowBackup(config, plan, expected, secret=secret, connect=connect,
                            run=self.entry.run, clone_connect=self.entry.backup_io.clone_connect,
                            migrate_run=self.entry.run, sleep=lambda _: None)(request)
        capture = dict(
            source_identity=expected.identity, baseline_digest=expected.baseline_digest,
            dump_sha256=base['backup_id'], companion_sha256='a' * 64, snapshot_sha256='b' * 64,
            v2_sha256='c' * 64, v3_sha256='d' * 64, row_counts_sha256='e' * 64,
            settings_projection_sha256='f' * 64, started_at=self.now + .1, finished_at=self.now + .2,
            **{key: True for key in ('source_authenticated', 'tls_verify_full', 'read_only', 'repeatable_read',
                                    'same_snapshot', 'source_unchanged', 'all_connections_closed',
                                    'artifact_bytes_verified')},
        )
        recovery = {key: capture[key] for key in ('dump_sha256', 'companion_sha256', 'snapshot_sha256',
                    'v2_sha256', 'v3_sha256', 'row_counts_sha256', 'settings_projection_sha256')}
        recovery.update(capture_digest=digest(capture), restored_catalog=expected.catalog, restore_verified=True,
                        started_at=self.now + .3, finished_at=self.now + .4,
                        clone_identity=base['clone_rehearsal']['clone_identity'],
                        clone_rehearsal_digest=digest({key: base['clone_rehearsal'][key] for key in CLONE_FIELDS}),
                        restored_invalid_indexes=0, final_invalid_indexes=0,
                        clone_isolated=True, cleanup_verified=True, owned_resources_remaining=0,
                        v3_categories={key: dict(missing=0, extra=0, changed=0) for key in V3_CATEGORIES})
        receipt = {key: base[key] for key in ('plan_digest', 'source_identity', 'baseline_digest',
                   'restore_verified', 'request_digest', 'backup_id', 'clone_rehearsal')}
        receipt.update(schema=ORIGIN_RECEIPT_SCHEMA, origin_window=dict(
            schema=ORIGIN_PROOF_SCHEMA, context_digest=digest(context), request_digest=digest(request),
            capture=capture, recovery=recovery))
        self.now += .5
        if self.fault:
            self.fault(receipt)
        if self.after:
            self.after()
        return receipt


@pytest.fixture(params=['authenticated', 'captured'])
def bound(request, pinned, tmp_path, monkeypatch):
    factory = prepare_auth_entry if request.param == 'authenticated' else prepare_capture_entry
    entry, *_parts, flags = factory(pinned, tmp_path, monkeypatch)
    # The capture contract has a nominal daemon; match the fake IO response to
    # that identity rather than weakening the real controller's daemon checks.
    entry.world.rig.docker.daemon = entry.raw['host']['daemon_id']
    prepared = window.prepare_window(args_for(entry, flags))
    context = origin.window_context(prepared.record)
    native = NativeProofFixture(entry)
    ports = OriginWindowPorts(digest(context), native.admit, native.connect, native.backup)
    entry.io.update(origin_window_ports=ports, origin_clock=lambda: native.now)
    yield SimpleNamespace(entry=entry, flags=flags, prepared=prepared, context=context, native=native, ports=ports)
    entry.world.journal.close()


def execute(bound):
    p, e = bound.prepared, bound.entry
    lines = []
    code = window.main(e.args('run') + bound.flags + ['--expect-plan-digest', p.plan.digest,
                       '--expect-window-digest', p.window_digest], out=lines.append, io=e.io)
    return code, [json.loads(line) for line in lines]


def adapter(bound):
    p = bound.prepared
    expected = fdb.DatabaseExpectation(p.config.identity, p.plan.baseline, p.config.catalog).validated()
    provider = OriginWindowBackup(p.backup, p.plan, expected, bound.context, bound.ports,
                                  secret=lambda: SECRET_URL, clock=lambda: bound.native.now)
    provider.admit_source_consumers()
    return provider


def request_for(bound):
    p = bound.prepared
    return dict(schema=BACKUP_REQUEST_SCHEMA, nonce='1' * 64, plan_digest=p.plan.digest,
                source_identity=p.config.identity, baseline_digest=digest([list(p.plan.baseline), p.config.catalog]),
                config_digest=p.config.digest, quiescence_digest='2' * 64)


def journal_kinds(entry):
    return [json.loads(line)['kind'] for line in entry.journal_text().splitlines()]


def test_actual_controller_journals_fresh_bound_origin_proof_before_ddl(bound):
    code, lines = execute(bound)
    assert code == 0, lines
    e, native = bound.entry, bound.native
    assert len(native.requests) == 1
    assert native.admissions == [bound.context]
    assert e.world.migrate.applied == [migration.name for migration in e.world.plan.pending]
    assert len(e.backup_io.migrations) == 51
    assert all(value == SECRET_URL for value in native.provider_values)
    assert all(context == bound.context for context in native.contexts)
    events = [json.loads(line) for line in e.journal_text().splitlines()]
    backup = [event for event in events if event['kind'] == 'transition-backup'][-1]
    proof = backup['receipt']['origin_window']
    assert proof['request_digest'] == backup['request_digest'] == digest(native.requests[0])
    assert proof['context_digest'] == digest(bound.context)
    assert set(backup['receipt']['clone_rehearsal']) == set(CLONE_FIELDS)
    assert 'backup_path' not in backup['receipt'] and SECRET_URL not in e.journal_text()
    assert lines[-1]['production_ready'] is False and lines[-1]['a10'] == 'not-implemented'
    e.world.consumers_held()


@pytest.mark.parametrize('kind', ['absent', 'dictionary', 'wrong-context'])
def test_no_native_capability_or_wrong_binding_refuses_before_provider_or_host(bound, kind):
    e = bound.entry
    e.secret_path.unlink()
    if kind == 'absent':
        del e.io['origin_window_ports']
    elif kind == 'dictionary':
        e.io['origin_window_ports'] = dict(context_digest=digest(bound.context), native=True)
    else:
        e.io['origin_window_ports'] = replace(bound.ports, context_digest='0' * 64)
    code, lines = execute(bound)
    assert code == 2 and lines[-1]['refused'] in ('window-source-auth-preflight-only',
           'window-origin-window-proof-pending', 'window-origin-capability-binding')
    assert e.calls == [] and e.connections == [] and bound.native.requests == []
    assert bound.native.admissions == []
    e.assert_no_journal_or_effects()


def test_capability_is_not_silently_applied_without_an_explicit_origin_profile(bound):
    e = bound.entry
    e.secret_path.unlink()
    lines = []
    assert window.main(e.args('run'), io=e.io, out=lines.append) == 2
    assert json.loads(lines[-1]) == {'refused': 'window-origin-arguments'}
    assert e.calls == [] and e.connections == []


@pytest.mark.parametrize('key', ['plan_digest', 'source_identity', 'baseline_digest', 'config_digest',
                                  'nonce', 'quiescence_digest', 'schema', 'extra'])
def test_request_must_be_exact_and_a_failure_consumes_the_capability(bound, key):
    provider = adapter(bound)
    request = request_for(bound)
    request[key] = 'wrong' if key in ('schema', 'extra') else True
    with pytest.raises(Refused):
        provider(request)
    with pytest.raises(Refused, match='window-origin-already-used'):
        provider(request_for(bound))
    assert bound.native.requests == []


def corrupt(receipt, fault):
    proof = receipt['origin_window']
    capture, recovery = proof['capture'], proof['recovery']
    if fault == 'legacy':
        receipt['schema'] = 'igreja12.first-transition-window-backup/1'
    elif fault == 'historical':
        proof['schema'] = 'igreja12.origin-capture-observation/2'
    elif fault == 'context':
        proof['context_digest'] = '0' * 64
    elif fault == 'request':
        proof['request_digest'] = '0' * 64
    elif fault == 'source':
        capture['source_identity'] = '0' * 64
    elif fault == 'before-request':
        capture['started_at'] -= 10
    elif fault in ('nan', 'boolean-time', 'future'):
        recovery['finished_at'] = {'nan': float('nan'), 'boolean-time': True,
                                   'future': recovery['finished_at'] + 100}[fault]
    elif fault == 'capture-hash':
        recovery['capture_digest'] = '0' * 64
    elif fault in ('dump', 'companion', 'snapshot', 'v2', 'v3', 'row_counts', 'settings_projection'):
        recovery[fault + '_sha256'] = '0' * 64
    elif fault == 'graphql-history':
        recovery['v3_categories']['initial_privileges']['missing'] = 2
    elif fault == 'category-omitted':
        del recovery['v3_categories']['initial_privileges']
    elif fault == 'boolean-count':
        recovery['v3_categories']['schemas']['missing'] = False
    elif fault in ('source_authenticated', 'tls_verify_full', 'same_snapshot', 'source_unchanged',
                   'all_connections_closed', 'artifact_bytes_verified'):
        capture[fault] = False
    elif fault == 'v1':
        recovery['restored_catalog'] = '0' * 64
    elif fault == 'clone-is-source':
        receipt['clone_rehearsal']['clone_identity'] = receipt['source_identity']
    elif fault == 'replay-incomplete':
        receipt['clone_rehearsal']['applied'] = 50
    elif fault == 'clone-proof-split':
        receipt['clone_rehearsal']['clone_identity'] = '0' * 64
    elif fault == 'replay-proof-split':
        receipt['clone_rehearsal']['final_schema_digest'] = '0' * 64
    elif fault in ('restored_invalid_indexes', 'final_invalid_indexes', 'owned_resources_remaining'):
        recovery[fault] = 1
    elif fault in ('clone_isolated', 'cleanup_verified'):
        recovery[fault] = False
    else:
        proof['production_ready'] = True
    if fault != 'capture-hash':
        recovery['capture_digest'] = digest(capture)


@pytest.mark.parametrize('fault', ['legacy', 'historical', 'context', 'request', 'source', 'before-request',
    'nan', 'boolean-time', 'future', 'capture-hash', 'dump', 'companion', 'snapshot', 'v2', 'v3',
    'row_counts', 'settings_projection', 'graphql-history', 'category-omitted', 'boolean-count',
    'source_authenticated', 'tls_verify_full', 'same_snapshot', 'source_unchanged',
    'all_connections_closed', 'artifact_bytes_verified', 'v1', 'clone-is-source', 'replay-incomplete',
    'clone-proof-split', 'replay-proof-split', 'restored_invalid_indexes', 'final_invalid_indexes',
    'owned_resources_remaining', 'clone_isolated', 'cleanup_verified', 'authority'])
def test_unproven_origin_never_gets_receipt_or_ddl_and_is_not_retried(bound, fault):
    bound.native.fault = lambda receipt: corrupt(receipt, fault)
    code, lines = execute(bound)
    assert code == 2 and lines[-1]['refused'] == 'window-transition-refused'
    text = bound.entry.journal_text()
    assert 'transition-backup-request' in text
    assert 'transition-backup' not in journal_kinds(bound.entry)
    assert 'ddl-marker' not in journal_kinds(bound.entry)
    assert bound.entry.world.migrate.applied == []
    assert len(bound.native.requests) == 1
    effects = len(bound.entry.world.legacy_effects())
    again, _ = execute(bound)
    assert again == 2 and len(bound.native.requests) == 1
    assert len(bound.entry.world.legacy_effects()) == effects


def test_stored_origin_proof_is_revalidated_before_ddl_even_if_receipt_hash_is_recomputed(bound, monkeypatch):
    append = Journal.append

    def tamper(journal, kind, **fields):
        result = append(journal, kind, **fields)
        if kind == 'transition-backup':
            event = journal.last(kind)
            event['receipt']['origin_window']['recovery']['v3_categories']['initial_privileges']['missing'] = 2
            event['receipt_digest'] = digest(event['receipt'])
        return result

    monkeypatch.setattr(Journal, 'append', tamper)
    code, _ = execute(bound)
    assert code == 2 and len(bound.native.requests) == 1
    assert bound.entry.world.migrate.applied == []
    assert 'ddl-marker' not in journal_kinds(bound.entry)


def test_database_drift_after_new_receipt_still_prevents_ddl(bound):
    bound.native.after = lambda: setattr(bound.entry.world.pg, 'writers', 1)
    code, _ = execute(bound)
    assert code == 2 and len(bound.native.requests) == 1
    assert bound.entry.world.migrate.applied == []
    assert 'ddl-marker' not in journal_kinds(bound.entry)


def test_origin_connections_dump_and_migration_keep_the_single_selected_provider(bound):
    native_connect = bound.native.connect

    def rotate(*, secret, context, timeout):
        bound.entry.secret_path.write_text('MIGRATION_DATABASE_URL=postgresql://other:synthetic@elsewhere/db\n')
        return native_connect(secret=secret, context=context, timeout=timeout)

    bound.entry.io['origin_window_ports'] = replace(bound.ports, connect=rotate)
    code, lines = execute(bound)
    assert code == 0, lines
    assert bound.entry.world.migrate.applied == [m.name for m in bound.prepared.plan.pending]
    assert all(value == SECRET_URL for value in bound.native.provider_values)


def test_provider_exception_is_sanitized_and_cannot_leave_a_receipt(bound):
    def fail(*_args, **_kwargs):
        raise RuntimeError('SYNTHETIC-SECRET-MUST-NOT-LEAK')

    bound.entry.io['origin_window_ports'] = replace(bound.ports, backup=fail)
    code, lines = execute(bound)
    assert code == 2
    assert 'SYNTHETIC-SECRET-MUST-NOT-LEAK' not in json.dumps(lines) + bound.entry.journal_text()
    assert 'ddl-marker' not in journal_kinds(bound.entry)


@pytest.mark.parametrize('fault', ['capture-delay', 'recovery-gap', 'proof-age', 'total-budget', 'capture-budget'])
def test_long_gaps_and_stale_proof_refuse_despite_valid_phase_order(bound, fault):
    def delay(receipt):
        capture = receipt['origin_window']['capture']
        recovery = receipt['origin_window']['recovery']
        if fault == 'capture-delay':
            for part in (capture, recovery):
                for key in ('started_at', 'finished_at'):
                    part[key] += 61
            bound.native.now += 61
        elif fault == 'recovery-gap':
            for key in ('started_at', 'finished_at'):
                recovery[key] += 61
            bound.native.now += 61
        elif fault == 'proof-age':
            bound.native.now += 61
        elif fault == 'total-budget':
            recovery['finished_at'] += 1201
            bound.native.now += 1201
        else:
            capture['finished_at'] += 241
            for key in ('started_at', 'finished_at'):
                recovery[key] += 241
            bound.native.now += 241
        recovery['capture_digest'] = digest(capture)

    bound.native.fault = delay
    code, _ = execute(bound)
    assert code == 2 and bound.entry.world.migrate.applied == []
    assert 'ddl-marker' not in journal_kinds(bound.entry)


def test_proof_age_limit_is_inclusive_and_stored_receipt_rejects_later_staleness(bound):
    code, lines = execute(bound)
    assert code == 0, lines
    event = [json.loads(line) for line in bound.entry.journal_text().splitlines()
             if json.loads(line)['kind'] == 'transition-backup'][-1]
    bound.native.now = event['receipt']['origin_window']['recovery']['finished_at'] + 60
    provider = adapter(bound)
    assert provider.validate_receipt(event['receipt'], event['request_digest'])
    bound.native.now += .01
    with pytest.raises(Refused, match='window-origin-proof-invalid'):
        provider.validate_receipt(event['receipt'], event['request_digest'])


@pytest.mark.parametrize('key', ['provider_descriptor_sha256', 'endpoint_identity_sha256', 'ca_sha256',
                                 'protocol_pins', 'window_digest', 'backup_config_digest'])
def test_native_independent_pin_is_not_replaced_by_a_changed_public_context(bound, key):
    changed = deepcopy(bound.context)
    changed[key] = {'changed': '0' * 64} if key == 'protocol_pins' else '0' * 64
    p = bound.prepared
    expected = fdb.DatabaseExpectation(p.config.identity, p.plan.baseline, p.config.catalog).validated()
    with pytest.raises(Refused, match='window-origin-capability-binding'):
        OriginWindowBackup(p.backup, p.plan, expected, changed, bound.ports, secret=lambda: SECRET_URL)
    assert bound.native.admissions == [] and bound.native.requests == []


def test_direct_composition_cannot_adopt_a_different_baseline_even_with_matching_context_hash(bound):
    p = bound.prepared
    expected = fdb.DatabaseExpectation(p.config.identity, p.plan.baseline[:-1], p.config.catalog).validated()
    changed = {**bound.context, 'baseline_digest': expected.baseline_digest}
    ports = replace(bound.ports, context_digest=digest(changed))
    with pytest.raises(Refused, match='window-origin-capability-binding'):
        OriginWindowBackup(p.backup, p.plan, expected, changed, ports, secret=lambda: SECRET_URL)
    assert bound.native.admissions == [] and bound.native.requests == []


def test_all_raw_source_consumers_need_native_admission_before_login_or_containment(bound):
    def unsupported(**_kwargs):
        raise RuntimeError('SYNTHETIC-UNBOUND-MIGRATION-TLS')

    bound.entry.io['origin_window_ports'] = replace(bound.ports, admit=unsupported)
    code, lines = execute(bound)
    assert code == 2 and lines[-1] == {'refused': 'window-origin-provider-failed'}
    assert bound.entry.connections == [] and bound.entry.calls == []
    assert bound.native.requests == []
    bound.entry.assert_no_journal_or_effects()


def test_blocked_native_factory_refuses_before_opening_provider(bound,monkeypatch):
    from dataclasses import asdict
    from first_transition_native_factory import NativeWindowFactory
    from first_transition_native_job import NativeDumpSpec, NativeJobPins
    from first_transition_window_backup import NativeSourcePolicy
    p = bound.prepared
    policy = NativeSourcePolicy('synthetic.invalid','192.0.2.10',5432,'/synthetic/ca.crt',bound.context['ca_sha256'])
    spec = NativeDumpSpec('/synthetic/pg_dump','b'*64)
    pins = NativeJobPins(digest(bound.context),digest(asdict(policy)),digest(asdict(spec)))
    expected = fdb.DatabaseExpectation(p.config.identity,p.plan.baseline,p.config.catalog).validated()
    factory = NativeWindowFactory(config=p.backup,plan=p.plan,expected=expected,context=bound.context,
        policy=policy,dump_spec=spec,pins=pins)
    bound.entry.io['origin_window_ports'] = factory.ports
    calls = []
    def provider():
        calls.append(True)
        pytest.fail('blocked native admission must precede provider access')
    monkeypatch.setattr(window,'env_file_secret',lambda *_a,**_k:provider)
    code,lines = execute(bound)
    assert code == 2 and lines[-1] == {'refused':'window-origin-native-admission-incomplete'}
    assert calls == [] and bound.entry.connections == [] and bound.entry.calls == []
    bound.entry.assert_no_journal_or_effects()


def test_unadmitted_capability_cannot_connect_or_capture(bound):
    p = bound.prepared
    expected = fdb.DatabaseExpectation(p.config.identity, p.plan.baseline, p.config.catalog).validated()
    provider = OriginWindowBackup(p.backup, p.plan, expected, bound.context, bound.ports,
                                  secret=lambda: SECRET_URL)
    with pytest.raises(Refused, match='window-origin-provider-not-admitted'):
        provider.connect(timeout=1)
    with pytest.raises(Refused, match='window-origin-provider-not-admitted'):
        provider(request_for(bound))
    with pytest.raises(Refused, match='window-origin-already-used'):
        provider.admit_source_consumers()
    assert bound.native.requests == [] and bound.native.admissions == []


def test_provider_interrupt_is_sanitized_and_the_window_cannot_be_recaptured(bound):
    calls = []

    def interrupt(*_args, **_kwargs):
        calls.append(True)
        raise KeyboardInterrupt('SYNTHETIC-SECRET-INTERRUPTION')

    bound.entry.io['origin_window_ports'] = replace(bound.ports, backup=interrupt)
    code, lines = execute(bound)
    assert code == 2 and lines[-1]['refused'] == 'window-transition-interrupted'
    assert 'SYNTHETIC-SECRET-INTERRUPTION' not in json.dumps(lines) + bound.entry.journal_text()
    assert 'ddl-marker' not in journal_kinds(bound.entry)
    effects = len(bound.entry.world.legacy_effects())
    code, _ = execute(bound)
    assert code == 2 and len(bound.entry.world.legacy_effects()) == effects
    assert bound.native.requests == []
    assert calls == [True]


def test_proof_expiring_during_final_quiet_observation_refuses_before_marker(bound, monkeypatch):
    observe = FirstTransition._quiet_observation

    def slow_final_observation(controller):
        result = observe(controller)
        if bound.native.requests:
            bound.native.now += 61
        return result

    monkeypatch.setattr(FirstTransition, '_quiet_observation', slow_final_observation)
    code, _ = execute(bound)
    assert code == 2 and len(bound.native.requests) == 1
    assert 'transition-backup' in journal_kinds(bound.entry)
    assert 'ddl-marker' not in journal_kinds(bound.entry)
    assert bound.entry.world.migrate.applied == []


def test_python_composition_cannot_silently_strip_origin_evidence_without_validator(bound, monkeypatch):
    assemble = window.assemble

    def omit_validator(*args, **kwargs):
        kwargs.pop('backup_receipt_validator')
        return assemble(*args, **kwargs)

    monkeypatch.setattr(window, 'assemble', omit_validator)
    code, _ = execute(bound)
    assert code == 2 and len(bound.native.requests) == 1
    assert 'transition-backup' not in journal_kinds(bound.entry)
    assert 'ddl-marker' not in journal_kinds(bound.entry)
    assert bound.entry.world.migrate.applied == []


def test_first_source_migration_failure_after_valid_proof_stops_without_retry(bound):
    first = bound.prepared.plan.pending[0].name
    bound.entry.world.migrate.faults[first] = 'fail'
    code, _ = execute(bound)
    assert code == 2
    assert bound.entry.world.migrate.applied == [first]
    assert 'ddl-marker' in journal_kinds(bound.entry) and 'transition-failed' in journal_kinds(bound.entry)
    assert len(bound.native.requests) == 1
    again, _ = execute(bound)
    assert again == 2 and bound.entry.world.migrate.applied == [first]
    assert len(bound.native.requests) == 1
