"""Controller preflight over synthetic metadata; no source/TLS/backup attestation."""
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_capture_contract as c
import first_transition_origin as origin
import first_transition_window as window
from first_transition_adapter import digest
from first_transition_database import DatabaseExpectation
from initial_transition_ops import Refused
from test_first_transition_window_entry import Entry, pinned  # noqa: F401
from test_first_transition_orchestrator import no_real_processes_or_network  # noqa: F401

BASE = 1794000000.0


def fixture():
    plan=c.pending_plan()
    plan['state']='pinned-contract-only'
    plan['expected_source']=dict(state='pinned-for-review',identity_sha256='1'*64,
        descriptor_sha256='2'*64)
    plan['tls_policy'].update(ca_sha256='3'*64,endpoint_identity_sha256='4'*64)
    plan['protocol_pins']={key:format(i+5,'x')*64 for i,key in enumerate(plan['protocol_pins'])}
    def tls(at,evidence):
        return dict(sslmode='verify-full',full_verification=True,ca_sha256='3'*64,
            endpoint_identity_sha256='4'*64,evidence_sha256=evidence*64,observed_at=at)
    def collect(version,at,counts):
        return dict(source_identity_sha256='1'*64,snapshot_id='00000001-00000002-1',
            holder_state_sha256='a'*64,reader_sha256=plan['protocol_pins'][version+'_reader_sha256'],
            payload_sha256=('b' if version=='v2' else 'c')*64,captured_at=at,counts=counts)
    def pin(path,sha,size,ino):
        return dict(path=c.ROOT+'/'+path,sha256=sha,size=size,dev=2049,ino=ino,
            mtime_ns=int((BASE+16)*1e9),ctime_ns=int((BASE+16)*1e9),owner=0,mode=0o600,
            nlink=1,retention_deadline=c.RETENTION_DEADLINE)
    metadata=dict(schema='igreja12.origin-capture-observation/2',capture_id='d'*64,
        plan_digest=c.digest(plan),scope=plan['scope'],origin_kind='nominal-origin-fresh',
        project=c.PROJECT,host=c.HOST,daemon=c.DAEMON,database='postgres',role='postgres',
        source_identity_sha256='1'*64,source_descriptor_sha256='2'*64,
        provider_adapter_sha256=plan['protocol_pins']['provider_adapter_sha256'],
        source_observation=dict(identity_sha256='1'*64,descriptor_sha256='2'*64,observed_at=BASE-1),
        started_at=BASE,finished_at=BASE+18,tls=dict(holder=tls(BASE+.5,'e'),dump=tls(BASE+15,'f')),
        holder=dict(backend_pid=123,read_only=True,isolation='repeatable-read',
            exported_snapshot_id='00000001-00000002-1',rr_snapshot_sha256='0'*64,
            opened_at=BASE+1,exported_at=BASE+2,alive_after_dump_at=BASE+16,
            before_state_sha256='a'*64,before_dump_state_sha256='a'*64,after_dump_state_sha256='a'*64),
        v2=collect('v2',BASE+3,dict(roles=32,memberships=24,extensions=5,events=7,tables=80)),
        v3=collect('v3',BASE+4,{key:1 for key in c.V3_CATEGORIES}),
        dump=dict(source_identity_sha256='1'*64,imported_snapshot_id='00000001-00000002-1',
            runner_sha256=plan['protocol_pins']['dump_runner_sha256'],tls_evidence_sha256='f'*64,
            started_at=BASE+5,finished_at=BASE+15,exit_code=0,sha256='9'*64,bytes=1000),
        dump_pin=pin('full.dump','9'*64,1000,10001),
        companion=dict(protocol='v2-plus-v3-shared-exported-snapshot',capture_id='d'*64,
            snapshot_id='00000001-00000002-1',dump_sha256='9'*64,dump_bytes=1000,
            v2_payload_sha256='b'*64,v3_payload_sha256='c'*64,sha256='8'*64),
        companion_pin=pin('private-manifest.json','8'*64,1500,10002),
        closure=dict(holder_backend_pid=123,rollback_observed=True,connection_closed_observed=True,
            closed_at=BASE+17,evidence_sha256='7'*64,keepalive_calls=10,
            maximum_keepalive_gap_seconds=1,last_keepalive_at=BASE+14))
    return plan,metadata


def resign(plan, metadata):
    plan['execution_request_digest'] = digest({k: v for k, v in plan.items()
                                               if k != 'execution_request_digest'})
    metadata['capture_id'] = plan['execution_request_digest']
    metadata['companion']['capture_id'] = plan['execution_request_digest']
    metadata['plan_digest'] = c.digest(plan['capture'])


def full_fixture(entry):
    cap, metadata = fixture()
    identity = entry.raw['database']['identity']
    cap['expected_source']['identity_sha256'] = identity
    for part in (metadata, metadata['source_observation'], metadata['v2'], metadata['v3'], metadata['dump']):
        for key in ('identity_sha256', 'source_identity_sha256'):
            if key in part:
                part[key] = identity
    cap['daemon'] = entry.raw['host']['daemon_id'] = c.DAEMON
    ledger = entry.world.plan.baseline
    expected = DatabaseExpectation(identity, ledger, entry.raw['database']['catalog']).validated()
    plan = dict(schema=origin.PLAN_SCHEMA, capture=cap,
                baseline_v1_digest=expected.baseline_digest, baseline_ledger_names=list(ledger),
                safety_preflight=dict(evidence_sha256='7' * 64, source_identity_sha256=identity,
                                      observed_at=BASE-1, logging_none=True, preload_empty=True),
                execution_request_digest=None)
    resign(plan, metadata)
    return plan, metadata, expected


def setup_entry(pinned, tmp_path, monkeypatch):
    entry = Entry(pinned, tmp_path)
    plan, metadata, expected = full_fixture(entry)
    from first_transition_orchestrator import parse_config
    entry.bindings['scope'] = parse_config(entry.raw).manifest.digest
    entry.write()
    paths = [tmp_path / name for name in ('origin-plan.json', 'origin-observation.json')]
    for path, value in zip(paths, (plan, metadata)):
        path.write_text(json.dumps(value))
    monkeypatch.setattr(window.time, 'time', lambda: BASE+19)
    flags = ['--origin-contract', '2', '--origin-plan', str(paths[0]),
             '--origin-observation', str(paths[1])]
    return entry, plan, metadata, expected, paths, flags


def test_controller_check_origin_binds_full_plan_without_authority(pinned, tmp_path, monkeypatch):
    entry, plan, metadata, expected, _, flags = setup_entry(pinned, tmp_path, monkeypatch)
    lines = []
    assert window.main(entry.args('check-origin') + flags, out=lines.append, io=entry.io) == 0
    result = json.loads(lines[-1])
    assert result['origin_plan_digest'] == digest(plan)
    assert result['capture_observation_digest'] == c.digest(metadata)
    assert result['baseline_digest'] == expected.baseline_digest
    for key in ('origin_authenticated', 'artifact_bytes_verified', 'provider_opened',
                'execution_authorized', 'a8_window_proven', 'receipt_emitted', 'production_ready'):
        assert result[key] is False
    assert entry.calls == [] and entry.connections == []
    assert not (Path(entry.raw['state_dir']) / 'journal').exists()


def test_selection_and_both_metadata_digests_change_window_identity(pinned, tmp_path, monkeypatch):
    entry, plan, metadata, _, paths, flags = setup_entry(pinned, tmp_path, monkeypatch)

    def prepared(extra):
        lines = []
        assert window.main(entry.args('prepare') + extra, out=lines.append, io=entry.io) == 0, lines
        return json.loads(lines[-1])

    legacy = prepared([])
    selected = prepared(flags)
    assert selected['window_digest'] != legacy['window_digest']
    monkeypatch.setattr(window.time, 'time', lambda: BASE+20)
    assert prepared(flags)['window_digest'] == selected['window_digest']
    metadata['closure']['evidence_sha256'] = '6' * 64
    paths[1].write_text(json.dumps(metadata))
    changed_observation = prepared(flags)
    assert changed_observation['window_digest'] != selected['window_digest']
    plan['safety_preflight']['evidence_sha256'] = '5' * 64
    resign(plan, metadata)
    for path, value in zip(paths, (plan, metadata)):
        path.write_text(json.dumps(value))
    assert prepared(flags)['window_digest'] != changed_observation['window_digest']
    assert entry.calls == [] and entry.connections == []


@pytest.mark.parametrize('mode', ['run', 'check', 'rehearse-backup', 'check-bindings'])
def test_no_mode_silently_downgrades_v2_or_reads_provider(pinned, tmp_path, monkeypatch, mode):
    entry, _, _, _, paths, flags = setup_entry(pinned, tmp_path, monkeypatch)
    # No dependence on readable evidence/provider to refuse unsupported execution.
    for path in paths:
        path.unlink()
    entry.secret_path.unlink()
    lines = []
    assert window.main(entry.args(mode) + flags, out=lines.append, io=entry.io) == 2
    code = 'window-origin-window-proof-pending' if mode == 'run' else 'window-origin-mode'
    assert json.loads(lines[-1]) == {'refused': code}
    assert entry.calls == [] and entry.connections == []
    assert not (Path(entry.raw['state_dir']) / 'journal').exists()


@pytest.mark.parametrize('flags', [[], ['--origin-contract', '2'], ['--origin-plan', '/missing'],
                                   ['--origin-observation', '/missing'],
                                   ['--origin-contract', '1', '--origin-plan', '/missing',
                                    '--origin-observation', '/missing']])
def test_explicit_version_and_complete_flag_set_required(flags):
    lines = []
    assert window.main(['check-origin', '--config', '/missing'] + flags, out=lines.append) == 2
    assert json.loads(lines[-1])['refused'] in ('window-origin-arguments', 'window-origin-version')


@pytest.mark.parametrize('change', ['identity', 'daemon', 'baseline', 'ledger', 'request',
                                    'capture_id', 'preflight', 'unsafe_logging', 'secret', 'legacy'])
def test_context_mismatch_refused_without_printing_input(pinned, tmp_path, change):
    entry = Entry(pinned, tmp_path)
    plan, metadata, expected = full_fixture(entry)
    daemon = c.DAEMON
    if change == 'identity':
        expected = DatabaseExpectation('0' * 64, expected.ledger, expected.catalog)
    elif change == 'daemon':
        daemon = 'wrong-daemon'
    elif change == 'baseline':
        plan['baseline_v1_digest'] = '0' * 64
    elif change == 'ledger':
        plan['baseline_ledger_names'] = plan['baseline_ledger_names'][:-1]
    elif change == 'request':
        plan['execution_request_digest'] = '0' * 64
    elif change == 'capture_id':
        metadata['capture_id'] = metadata['companion']['capture_id'] = '0' * 64
    elif change == 'preflight':
        plan['safety_preflight']['observed_at'] = BASE-2
    elif change == 'unsafe_logging':
        plan['safety_preflight']['logging_none'] = False
    elif change == 'secret':
        plan['capture']['password'] = 'SYNTHETIC-SENTINEL-NEVER-PRINT'
    else:
        metadata['schema'] = 'igreja12.origin-capture-observation/1'
    if change not in ('request', 'capture_id', 'secret'):
        resign(plan, metadata)
    with pytest.raises(Refused) as caught:
        origin.assess(plan, metadata, expected=expected, daemon_id=daemon, now=BASE+19)
    assert str(caught.value) == 'window-origin-binding'


@pytest.mark.parametrize('kind', ['synthetic', 'r2-derived-reference-v3'])
def test_synthetic_or_derived_metadata_cannot_satisfy_nominal_preflight(pinned, tmp_path, kind):
    entry = Entry(pinned, tmp_path)
    plan, metadata, expected = full_fixture(entry)
    metadata['origin_kind'] = kind
    with pytest.raises(Refused, match='window-origin-binding'):
        origin.assess(plan, metadata, expected=expected, daemon_id=c.DAEMON, now=BASE+19)


def test_pending_pins_stay_pending(pinned, tmp_path):
    entry = Entry(pinned, tmp_path)
    plan, metadata, expected = full_fixture(entry)
    plan['capture'] = c.pending_plan()
    resign(plan, metadata)
    with pytest.raises(Refused, match='window-origin-binding'):
        origin.assess(plan, metadata, expected=expected, daemon_id=c.DAEMON, now=BASE+19)


@pytest.mark.parametrize('now', [BASE+79, BASE+17, float('nan'), True])
def test_stale_future_or_invalid_assessment_cannot_enter_preflight(pinned, tmp_path, now):
    entry = Entry(pinned, tmp_path)
    plan, metadata, expected = full_fixture(entry)
    with pytest.raises(Refused, match='window-origin-binding'):
        origin.assess(plan, metadata, expected=expected, daemon_id=c.DAEMON, now=now)


@pytest.mark.parametrize('raw', ['{"schema": 1, "schema": 2}', '{"x": NaN}', '{"x": Infinity}',
                                 'x' * 131073])
def test_metadata_file_is_bounded_strict_json(tmp_path, raw):
    path = tmp_path / 'metadata.json'
    path.write_text(raw)
    with pytest.raises(Refused, match='window-origin-metadata'):
        origin.read_metadata(str(path))


@pytest.mark.parametrize('kind', ['symlink', 'fifo', 'directory'])
def test_metadata_special_files_refuse_without_blocking(tmp_path, kind):
    path = tmp_path / 'metadata.json'
    if kind == 'symlink':
        target = tmp_path / 'regular.json'
        target.write_text('{}')
        path.symlink_to(target)
    elif kind == 'fifo':
        os.mkfifo(path)
    else:
        path.mkdir()
    with pytest.raises(Refused, match='window-origin-metadata'):
        origin.read_metadata(str(path))
