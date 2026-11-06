"""Factory binding/admission only; every process, provider and network path is forbidden."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_native_factory as factory
from first_transition_adapter import APPLICATION_SHA, EXECUTOR_SHA, Migration, Plan, digest
from first_transition_database import DatabaseExpectation
from first_transition_native_job import NativeDump, NativeDumpSpec, NativeJobPins, NativeWindowJob
from first_transition_window_backup import (
    NativeSourceConnector, NativeSourcePolicy, NativeWindowArtifacts, OriginWindowBackup,
    OriginWindowPorts, WindowBackupConfig,
)
from initial_transition_files import Journal
from initial_transition_ops import Refused


@pytest.fixture(autouse=True)
def forbid_native_io(monkeypatch):
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError('unexpected native IO')

    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(NativeSourceConnector, 'connect', forbidden)
    monkeypatch.setattr(NativeWindowJob, 'execute', forbidden)
    monkeypatch.setattr(NativeDump, 'run', forbidden)
    monkeypatch.setattr(NativeWindowArtifacts, '__enter__', forbidden)
    monkeypatch.setattr(Journal, 'open', forbidden)
    yield forbidden
    assert calls == []


@pytest.fixture(params=['source_auth_preflight', 'origin_preflight'])
def inputs(request):
    baseline = ('20260101_synthetic.sql',)
    plan = Plan(APPLICATION_SHA, EXECUTOR_SHA,
                (Migration(baseline[0], b'SELECT 1;'), Migration('20270101_synthetic.sql', b'SELECT 1;')),
                baseline, b'synthetic executor never executed', b'synthetic preflight never executed',
                (('synthetic-reader.py', 'f' * 64),))
    expected = DatabaseExpectation('c' * 64, baseline, 'd' * 64)
    config = WindowBackupConfig('/synthetic/docker', 'unix:///synthetic/docker.sock',
                               '/synthetic/docker-config', '/synthetic/private/artifacts',
                               '/synthetic/clone-work', '/synthetic/python',
                               'registry.invalid/dump@sha256:' + 'a' * 64,
                               'registry.invalid/clone@sha256:' + 'b' * 64)
    policy = NativeSourcePolicy('source.synthetic.invalid', '192.0.2.10', 5432,
                                '/synthetic/private/ca.crt', 'a' * 64)
    spec = NativeDumpSpec('/synthetic/runtime/pg_dump', 'b' * 64)
    source = request.param == 'source_auth_preflight'
    context = dict(schema='igreja12.window-origin-context/1', profile=request.param,
                   profile_digest='1' * 64, window_digest='2' * 64, plan_digest=plan.digest,
                   config_digest='3' * 64, backup_config_digest=digest(asdict(config)),
                   source_identity=expected.identity, baseline_digest=expected.baseline_digest,
                   provider_descriptor_sha256='4' * 64, endpoint_identity_sha256='5' * 64,
                   ca_sha256=policy.ca_sha256,
                   protocol_pins=({'code_bundle_sha256': '6' * 64} if source else
                                  {key: '6' * 64 for key in factory.CAPTURE_PINS}),
                   startup_profile='supabase-17.6.1.127' if source else 'origin-schema-2')
    pins = NativeJobPins(digest(context), digest(asdict(policy)), digest(asdict(spec)))
    return dict(config=config, plan=plan, expected=expected, context=context,
                policy=policy, dump_spec=spec, pins=pins)


def test_constructor_diagnostic_and_ports_are_pure_and_report_real_gaps(inputs, monkeypatch):
    import builtins
    import os

    def no_files(*_args, **_kwargs):
        raise AssertionError('constructor or diagnostic opened a file')

    with monkeypatch.context() as local:
        local.setattr(os, 'open', no_files)
        local.setattr(builtins, 'open', no_files)
        value = factory.NativeWindowFactory(**inputs)
        report = value.diagnostics()
        assert type(value.ports) is OriginWindowPorts
        value.ports.validate(inputs['context'])
    assert report['status'] == 'blocked'
    assert report['context_digest'] == inputs['pins'].context_sha256
    codes = {item['code'] for item in report['blockers']}
    assert {'source-migration-transport-unbound', 'candidate-transports-unbound',
            'writer-endpoint-unbound', 'source-unchanged-unproven', 'phase-timing-unbound',
            'job-result-not-origin-receipt'} <= codes
    assert all(report[key] is False for key in (
        'admission_granted', 'provider_opened', 'job_executed', 'receipt_emitted',
        'execution_authorized', 'operational_ready', 'a8_window_proven'))
    public = json.dumps(report)
    assert inputs['policy'].host not in public and inputs['policy'].ca_file not in public
    assert inputs['dump_spec'].binary not in public
    report['blockers'].clear()
    assert value.diagnostics()['blockers']


def test_all_ports_refuse_even_if_called_directly_or_after_rejected_admission(inputs, forbid_native_io):
    value = factory.NativeWindowFactory(**inputs)
    arguments = dict(secret=forbid_native_io, context=inputs['context'])
    for _ in range(2):
        with pytest.raises(Refused, match='^' + factory.BLOCKED_CODE + '$'):
            value.ports.admit(**arguments)
        with pytest.raises(Refused, match='^' + factory.BLOCKED_CODE + '$'):
            value.ports.connect(**arguments, timeout=10)
        with pytest.raises(Refused, match='^' + factory.BLOCKED_CODE + '$'):
            value.ports.backup({'source_unchanged': True, 'operational_ready': True},
                               **arguments, connect=forbid_native_io, config=inputs['config'],
                               plan=inputs['plan'], expected=inputs['expected'])


def test_existing_backup_bridge_stays_unadmitted_before_any_provider_or_job(inputs, forbid_native_io):
    value = factory.NativeWindowFactory(**inputs)
    bridge = OriginWindowBackup(inputs['config'], inputs['plan'], inputs['expected'],
                                inputs['context'], value.ports, secret=forbid_native_io)
    with pytest.raises(Refused, match='^' + factory.BLOCKED_CODE + '$'):
        bridge.admit_source_consumers()
    assert bridge.admitted is False
    with pytest.raises(Refused, match='provider-not-admitted'):
        bridge.connect(timeout=10)
    with pytest.raises(Refused, match='provider-not-admitted'):
        bridge({'schema': 'not-a-window-request'})


def test_available_native_consumers_do_not_replace_fence_or_receipt_admission(inputs,forbid_native_io):
    from first_transition_native_transports import NativeSourceTransports,NativeTransportPins
    pins=NativeTransportPins(digest(inputs['context']),digest(asdict(inputs['policy'])),
        inputs['plan'].digest,inputs['expected'].identity)
    consumers=NativeSourceTransports(plan=inputs['plan'],expected=inputs['expected'],context=inputs['context'],
        policy=inputs['policy'],pins=pins,secret=forbid_native_io)
    value=factory.NativeWindowFactory(**inputs,transports=consumers)
    assert value.ports.consumers is consumers
    value.ports.validate(inputs['context'])
    assert value.diagnostics()['implementations']['source_consumers']=='native-transports-unadmitted'
    with pytest.raises(Refused,match='^'+factory.BLOCKED_CODE+'$'):
        value.ports.admit(secret=forbid_native_io,context=inputs['context'])


@pytest.mark.parametrize('field', ['context', 'policy', 'dump_spec', 'config', 'plan', 'expected', 'pins'])
def test_independent_binding_mismatches_refuse_without_io(inputs, field):
    changed = dict(inputs)
    if field == 'context':
        changed[field] = {**inputs[field], 'config_digest': '0' * 64}
    elif field == 'policy':
        changed[field] = replace(inputs[field], hostaddr='192.0.2.11')
    elif field == 'dump_spec':
        changed[field] = replace(inputs[field], sha256='0' * 64)
    elif field == 'config':
        changed[field] = replace(inputs[field], backup_root='/synthetic/other-root')
    elif field == 'plan':
        changed[field] = replace(inputs[field], adapter_sources=(('different.py', '0' * 64),))
    elif field == 'expected':
        changed[field] = replace(inputs[field], identity='0' * 64)
    else:
        changed[field] = replace(inputs[field], context_sha256='0' * 64)
    with pytest.raises(Refused, match='^' + factory.CONFIG_CODE + '$'):
        factory.NativeWindowFactory(**changed)


@pytest.mark.parametrize('pretend', ['boolean-pins', 'json-pins', 'extra-capability', 'boolean-protocol'])
def test_caller_flags_and_json_cannot_supply_missing_capabilities(inputs, pretend):
    changed = dict(inputs)
    if pretend == 'boolean-pins':
        changed['pins'] = True
    elif pretend == 'json-pins':
        changed['pins'] = {**asdict(inputs['pins']), 'admitted': True}
    else:
        changed['context'] = {**inputs['context']}
        if pretend == 'extra-capability':
            changed['context']['source_unchanged'] = True
        else:
            changed['context']['protocol_pins'] = {key: True for key in inputs['context']['protocol_pins']}
        changed['pins'] = replace(inputs['pins'], context_sha256=digest(changed['context']))
    with pytest.raises(Refused, match='^' + factory.CONFIG_CODE + '$'):
        factory.NativeWindowFactory(**changed)


def test_callback_context_replacement_cannot_fall_back_or_adopt_new_pins(inputs, forbid_native_io):
    value = factory.NativeWindowFactory(**inputs)
    changed = {**inputs['context'], 'window_digest': '0' * 64}
    with pytest.raises(Refused, match='^' + factory.CONFIG_CODE + '$'):
        value.ports.admit(secret=forbid_native_io, context=changed)
    with pytest.raises(Refused, match='^' + factory.CONFIG_CODE + '$'):
        value.ports.backup({}, secret=forbid_native_io, context=inputs['context'], connect=forbid_native_io,
                           config=replace(inputs['config'], backup_root='/synthetic/other-root'),
                           plan=inputs['plan'], expected=inputs['expected'])
