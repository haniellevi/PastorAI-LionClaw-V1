"""Observed-host driver over a fake runner only; no Docker, Redis, process or network is used.

The fake runner answers with the raw projected text Docker/redis-cli would print
for the driver's own templates; the real ObservedHostContract, ObservedHostTransport
and driver parser run on top of it. PopenRunner is exercised with a mocked Popen.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from first_transition_adapter import ROLES, Refused
from first_transition_host_contract import ObservedHostContract
from first_transition_host_driver import (ENTRIES, SCHEMA, HostManifest, ObservedHostDriver, PopenRunner,
                                          inspect_template)
from first_transition_host_transport import ObservedHostTransport, SUPPORT_ROLES, host_command
from initial_transition_files import Journal

DAEMON = '0f1e2d3c-4b5a-4968-8776-655443322110'
NETWORK = 'e' * 64
NET_NAME = 'synthetic_default'
SECRET = 'SENTINEL-SECRET-VALUE'
LEGACY = {role: str(number) * 64 for number, role in enumerate(ROLES, 1)}
SUPPORT = {role: str(number) * 64 for number, role in zip((5, 6, 7), SUPPORT_ROLES)}
GATES = ('ALLOW_REAL_SENDS', 'ASAAS_BILLING_ENABLED', 'BREVO_SEND_MODE', 'BROADCAST_ASYNC_ENABLED')
PROJECT, SERVICE = 'com.docker.compose.project', 'com.docker.compose.service'
REVISION = 'org.opencontainers.image.revision'
MANIFEST = dict(schema=SCHEMA, daemon_id=DAEMON, legacy_project='synthetic-legacy', network_id=NETWORK,
                service_ids=LEGACY, support_ids=SUPPORT,
                processing_keys=['pastorai:webhooks:processing:worker-1'], gate_names=list(GATES))


@pytest.fixture(autouse=True)
def no_real_processes_or_network(monkeypatch):
    hits = []
    def forbid(label):
        def blocked(*_args, **_kwargs):
            hits.append(label)
            raise AssertionError('real process/network forbidden: ' + label)
        return blocked
    for module, names in ((subprocess, ('Popen', 'run', 'call', 'check_call', 'check_output')),
                          (os, ('system', 'popen', 'execv', 'execve', 'execvp', 'fork', 'posix_spawn',
                                'posix_spawnp')),
                          (socket, ('socket', 'create_connection', 'getaddrinfo'))):
        for name in names:
            monkeypatch.setattr(module, name, forbid(module.__name__ + '.' + name))
    yield
    assert hits == []


def container(role, ident, *, support=False):
    number = ident[0]
    labels = {PROJECT: 'synthetic-legacy', SERVICE: role, 'maintainer': 'synthetic'}
    if role == 'broadcast-worker':
        labels = {'maintainer': 'synthetic'}  # standalone legacy: no compose labels at all
    health = None
    if support and role != 'evolution-api':
        health = {'Status': 'healthy', 'Log': [{'Output': SECRET}]}
    return dict(
        Id=ident, Image='sha256:' + 'b' * 64, Labels=labels,
        Env=['DATABASE_URL=postgres://app:' + SECRET + '@db/app', 'ALLOW_REAL_SENDS=false', 'ASAAS_BILLING_ENABLED=false', 'BREVO_SEND_MODE=off',
             'BROADCAST_ASYNC_ENABLED=false', 'PATH=/usr/bin'],
        State=dict(Status='running', Running=True, Paused=False, Restarting=False, ExitCode=0,
                   StartedAt='2026-10-01T10:00:0' + number + '.123456789Z', Health=health),
        RestartCount=0, RestartPolicy='always', NetworkMode=NET_NAME,
        Mounts=[dict(Type='volume', Name=role + '-data', Source='/var/lib/docker/volumes/' + role + '/_data',
                     Destination='/data', RW=True, Propagation='')],
        Networks={NET_NAME: dict(Aliases=[role], IPAMConfig=None, IPAddress='172.18.0.' + number,
                                 EndpointID='f' * 64, NetworkID=NETWORK, MacAddress='02:42:ac:12:00:0' + number)})


def render(c):
    """What Docker prints for inspect_template(GATES): one projected JSON array per container."""
    labels = c['Labels']
    def label(key):
        return None if labels is None else labels.get(key, '')
    state = c['State']
    return [c['Id'], c['Image'], label(PROJECT), label(SERVICE), label(REVISION), state['Status'],
            state['Running'], state['Paused'], state['Restarting'], state['ExitCode'], state['StartedAt'],
            state['Health']['Status'] if state['Health'] else None, c['RestartCount'], c['RestartPolicy'],
            c['NetworkMode'], [e for e in c['Env'] if e.split('=', 1)[0] in GATES] + [None],
            [[m['Type'], m['Name'], m['Source'], m['Destination'], m['RW']] for m in c['Mounts']] + [None],
            [[name, n['Aliases'], n['NetworkID']] for name, n in sorted(c['Networks'].items())] + [None]]


class FakeDocker:
    """Fake runner: logical argv in, (returncode, raw stdout bytes) out."""

    def __init__(self):
        self.calls = []
        self.daemon = DAEMON
        self.network = [NETWORK, NET_NAME]
        self.containers = {ident: container(role, ident) for role, ident in LEGACY.items()}
        self.containers.update({ident: container(role, ident, support=True) for role, ident in SUPPORT.items()})
        self.redis = {'pastorai:webhooks': ('list', 3), 'pastorai:webhooks:dead': ('list', 1),
                      'pastorai:webhooks:retry-scheduled': ('zset', 2)}
        self.override = {}   # kind -> callable(argv) -> (rc, bytes)
        self.after = {}      # kind -> callable(argv), run after the effect is applied
        self.ignore_term = set()
        self.term_exit = {}

    @staticmethod
    def kind(argv):
        if argv[:2] == ('docker', 'info'):
            return 'info'
        if argv[:3] == ('docker', 'network', 'inspect'):
            return 'network'
        return {'inspect': 'inspect', 'exec': 'redis', 'update': 'update', 'kill': 'kill',
                'wait': 'wait', 'start': 'start'}[argv[1]]

    def __call__(self, argv, *, timeout, max_output):
        assert type(argv) is tuple and 0 < timeout <= 30 and type(max_output) is int
        self.calls.append(argv)
        kind = self.kind(argv)
        if kind in self.override:
            return self.override[kind](argv)
        result = getattr(self, '_' + kind)(argv)
        if kind in self.after:
            self.after[kind](argv)
        return result

    def _info(self, argv):
        assert argv == ('docker', 'info', '--format', '{{json .ID}}')
        return 0, (json.dumps(self.daemon) + '\n').encode()

    def _network(self, argv):
        assert argv[:4] == ('docker', 'network', 'inspect', '--format') and argv[5:] == (NETWORK,)
        return 0, (json.dumps(self.network) + '\n').encode()

    def _inspect(self, argv):
        assert argv[:6] == ('docker', 'inspect', '--type', 'container', '--format', inspect_template(GATES))
        return 0, ''.join(json.dumps(render(self.containers[i])) + '\n' for i in argv[6:]).encode()

    def _redis(self, argv):
        assert argv[:6] == ('docker', 'exec', SUPPORT['redis'], 'redis-cli', '--raw', argv[5]) and len(argv) == 7
        command, key = argv[5:]
        kind, count = self.redis.get(key, ('none', 0))
        value = {'TYPE': kind, 'PTTL': -1 if kind != 'none' else -2, 'LLEN': count, 'ZCARD': count}[command]
        return 0, (str(value) + '\n').encode()

    def _update(self, argv):
        self.containers[argv[3]]['RestartPolicy'] = argv[2].removeprefix('--restart=')
        return 0, (argv[3] + '\n').encode()

    def _start(self, argv):
        c = self.containers[argv[2]]
        self.starts = getattr(self, 'starts', 0) + 1
        c['State'].update(Status='running', Running=True, ExitCode=0,
                          StartedAt='2026-10-30T12:00:%02d.000000001Z' % self.starts)
        return 0, (argv[2] + '\n').encode()

    def _kill(self, argv):
        c = self.containers[argv[3]]
        if argv[3] not in self.ignore_term:
            c['State'].update(Status='exited', Running=False, ExitCode=self.term_exit.get(argv[3], 0))
            for net in c['Networks'].values():  # Docker clears operational data on stop
                net.update(IPAddress='', EndpointID='', MacAddress='')
        return 0, (argv[3] + '\n').encode()

    def _wait(self, argv):
        c = self.containers[argv[2]]
        if c['State']['Running']:
            raise TimeoutError('synthetic docker wait')
        return 0, (str(c['State']['ExitCode']) + '\n').encode()

    def effects(self):
        return [argv for argv in self.calls if self.kind(argv) in ('update', 'kill', 'wait', 'start')]


class FakeIngress:
    def __init__(self, scope, entry):
        self.scope, self.entry, self.state, self.stuck, self.blocks = scope, entry, 'open', False, 0
        self.on_block = self.on_open = None
        self.opens = 0
        self.open_timeout = None  # 'before' or 'after' the opening takes effect, once

    def observe(self, scope, *, timeout):
        assert scope == self.scope and timeout > 0
        return self.state

    def block(self, scope, *, timeout):
        assert scope == self.scope and timeout > 0
        self.blocks += 1
        if not self.stuck:
            self.state = 'blocked'
        if self.on_block:
            self.on_block()
        return True

    def open(self, scope, *, timeout):
        assert scope == self.scope and timeout > 0
        self.opens += 1
        if self.on_open:
            self.on_open()
        fault, self.open_timeout = self.open_timeout, None
        if fault == 'before':
            raise TimeoutError('synthetic ingress timeout before effect')
        self.state = 'open'
        if fault == 'after':
            raise TimeoutError('synthetic ingress timeout after effect')
        return True


class FakeWriters:
    def __init__(self, scope):
        self.scope, self.count = scope, 0

    def observe(self, scope, *, timeout):
        assert scope == self.scope and timeout > 0
        return self.count


class Rig:
    def __init__(self, manifest=MANIFEST):
        self.manifest = HostManifest.from_dict(manifest)
        self.docker = FakeDocker()
        self.ingress = {entry: FakeIngress(self.manifest.digest, entry) for entry in ENTRIES}
        self.writers = FakeWriters(self.manifest.digest)
        self.driver = ObservedHostDriver(self.manifest, runner=self.docker, ingress=self.ingress,
                                         writers=self.writers)
        self.transport = ObservedHostTransport(self.driver, **self.manifest.transport_scope())

    def contract(self, journal):
        return ObservedHostContract(self.transport, journal)


def journal_text(tmp_path):
    return (tmp_path / 'journal' / 'journal.jsonl').read_text()


# --- manifest and bindings -------------------------------------------------

def _bad_manifest(change):
    data = deepcopy(MANIFEST)
    change(data)
    return data


@pytest.mark.parametrize('change', [
    lambda d: d.update(password='x'),
    lambda d: d.pop('gate_names'),
    lambda d: d.update(schema='other'),
    lambda d: d.update(daemon_id='host.example'),
    lambda d: d['support_ids'].update(redis=LEGACY['backend']),
    lambda d: d['service_ids'].update(backend='A' * 64),
    lambda d: d['service_ids'].pop('cron-worker'),
    lambda d: d.update(network_id=LEGACY['backend']),
    lambda d: d.update(processing_keys=['pastorai:*']),
    lambda d: d.update(processing_keys=['pastorai:webhooks:processing:a'] * 2),
    lambda d: d.update(gate_names=['DATABASE_PASSWORD']),
    lambda d: d.update(gate_names=['A=B']),
    lambda d: d.update(gate_names=[]),
    lambda d: d.update(legacy_project='bad project'),
])
def test_manifest_refuses_unscoped_duplicate_or_secret_bearing_input(change):
    with pytest.raises(Refused, match='^manifest-'):
        HostManifest.from_dict(_bad_manifest(change))


def test_manifest_is_immutable_and_binds_its_scope():
    manifest = HostManifest.from_dict(MANIFEST)
    with pytest.raises(Exception):
        manifest.daemon_id = 'x'
    scope = manifest.transport_scope()
    scope['service_ids']['backend'] = 'f' * 64
    assert manifest.transport_scope()['service_ids'] == LEGACY
    other = HostManifest.from_dict(_bad_manifest(lambda d: d.update(processing_keys=[])))
    assert other.digest != manifest.digest and len(manifest.digest) == 64


def _bindings(rig, mutation):
    ingress, writers = dict(rig.ingress), rig.writers
    if mutation == 'no-ingress':
        ingress = None
    elif mutation == 'one-entry':
        ingress.pop('evolution-backend')
    elif mutation == 'same-object':
        ingress['evolution-backend'] = ingress['external']
    elif mutation == 'wrong-scope':
        ingress['external'].scope = 'a' * 64
    elif mutation == 'wrong-entry':
        ingress['external'].entry = 'evolution-backend'
    elif mutation == 'not-callable':
        ingress['external'].block = None
    elif mutation == 'no-writers':
        writers = None
    elif mutation == 'writers-scope':
        writers.scope = 'a' * 64
    elif mutation == 'boolean-token':
        writers = True
    return ingress, writers


@pytest.mark.parametrize('mutation', ['no-ingress', 'one-entry', 'same-object', 'wrong-scope', 'wrong-entry',
                                      'not-callable', 'no-writers', 'writers-scope', 'boolean-token'])
def test_missing_or_unbound_bindings_refuse_before_any_runner_call(mutation):
    rig = Rig()
    ingress, writers = _bindings(rig, mutation)
    with pytest.raises(Refused, match='^driver-(ingress|writer)-binding$'):
        ObservedHostDriver(rig.manifest, runner=rig.docker, ingress=ingress, writers=writers)
    with pytest.raises(Refused, match='^driver-'):
        ObservedHostDriver(rig.manifest, runner=None, ingress=rig.ingress, writers=rig.writers)
    with pytest.raises(Refused, match='^driver-manifest$'):
        ObservedHostDriver(MANIFEST, runner=rig.docker, ingress=rig.ingress, writers=rig.writers)
    assert rig.docker.calls == []


def test_binding_rebound_after_construction_refuses_before_effects(tmp_path):
    rig = Rig()
    rig.ingress['evolution-backend'].scope = 'a' * 64
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused):
            rig.contract(journal).contain()
    assert rig.docker.effects() == [] and rig.driver.refusals[-1] == 'driver-ingress-binding'


# --- happy path through the real contract/transport/driver -----------------

def test_containment_happy_path_through_real_contract_transport_and_driver(tmp_path):
    rig = Rig()
    with Journal(tmp_path / 'journal') as journal:
        receipt = rig.contract(journal).contain()
        assert receipt['mode'] == 'observed-host' and receipt['host_verified'] is False
        assert receipt['quiescence_proven'] is False and receipt['stopped_roles'] == ROLES
        assert all(i.state == 'blocked' and i.blocks == 1 for i in rig.ingress.values())
        assert rig.docker.effects() == [
            host_command(op, LEGACY[role]) for role in ROLES for op in ('restart-no', 'term', 'wait')]
        # Every inspection and effect follows a fresh daemon check (inspect follows its network check).
        kinds = [FakeDocker.kind(argv) for argv in rig.docker.calls]
        for index, kind in enumerate(kinds):
            if kind != 'info':
                assert kinds[index - 1] == ('network' if kind == 'inspect' else 'info')
        assert not any(set(argv) & set(SUPPORT.values()) for argv in rig.docker.effects())
        assert all(c['RestartPolicy'] == 'always' and c['State']['Running']
                   for i, c in rig.docker.containers.items() if i in SUPPORT.values())
        count = len(rig.docker.effects())
        assert rig.contract(journal).contain() == receipt  # replay: no new effect
        assert len(rig.docker.effects()) == count
    text = journal_text(tmp_path)
    assert SECRET not in text and '172.18.0' not in text and 'f' * 64 not in text


def test_projection_normalizes_labels_and_carries_only_declared_fields():
    rig = Rig()
    rig.docker.containers[LEGACY['queue-worker']]['Labels'][REVISION] = 'a' * 40
    rig.docker.containers[LEGACY['broadcast-worker']]['Labels'] = None
    raw = rig.driver.request(('inspect-host',), timeout=10)
    assert set(raw) == {'scope_digest', 'ingress_blocked', 'ingress_open', 'unknown_writers', 'network_id',
                        'services', 'support'}
    services = raw['services']
    assert services['broadcast-worker']['compose_project'] is None
    assert services['broadcast-worker']['compose_service'] is None
    assert services['backend']['revision'] is None and services['queue-worker']['revision'] == 'a' * 40
    assert services['backend']['exit_code'] is None and services['backend']['started'].startswith('2026-10-01T')
    assert raw['support']['evolution-api']['health'] is None and raw['support']['redis']['health'] == 'healthy'
    assert raw['network_id'] == NETWORK and raw['ingress_blocked'] is False and raw['ingress_open'] is True
    rig.ingress['external'].state = 'blocked'
    partial = rig.driver.request(('inspect-host',), timeout=10)
    assert partial['ingress_blocked'] is False and partial['ingress_open'] is False
    text = json.dumps(raw)
    for leaked in (SECRET, '172.18.0', 'f' * 64, 'DATABASE_URL', 'Log', 'MacAddress'):
        assert leaked not in text
    snapshot = rig.transport.snapshot()  # the real transport accepts the driver's raw shape
    assert snapshot['services']['broadcast-worker']['compose_project'] is None


def test_digests_are_stable_across_stop_but_track_configuration():
    rig = Rig()
    before = rig.driver.request(('inspect-host',), timeout=10)['services']['backend']
    c = rig.docker.containers[LEGACY['backend']]
    c['State'].update(Status='exited', Running=False, ExitCode=0)
    c['Networks'][NET_NAME].update(IPAddress='', EndpointID='', MacAddress='')
    after = rig.driver.request(('inspect-host',), timeout=10)['services']['backend']
    assert {k: before[k] for k in ('gates_digest', 'mounts_digest', 'networks_digest')} == {
        k: after[k] for k in ('gates_digest', 'mounts_digest', 'networks_digest')}
    assert after['running'] is False and after['exit_code'] == 0
    c['Env'] = [e.replace('SENDS=false', 'SENDS=true') for e in c['Env']]
    assert rig.driver.request(('inspect-host',), timeout=10)['services']['backend']['gates_digest'] != (
        before['gates_digest'])
    c['Env'] = [e for e in c['Env'] if not e.startswith('DATABASE_URL')]  # non-gate env never counts
    c['Env'] = [e.replace('SENDS=true', 'SENDS=false') for e in c['Env']]
    assert rig.driver.request(('inspect-host',), timeout=10)['services']['backend']['gates_digest'] == (
        before['gates_digest'])


def test_inspect_template_never_projects_full_env_labels_state_or_dynamic_network():
    template = inspect_template(GATES)
    for forbidden in ('json .Config.Env', 'json .Config}}', 'json .Config.Labels}}', 'json .State}}',
                      'json .NetworkSettings', 'IPAddress', 'EndpointID', 'MacAddress', 'Gateway',
                      'json .Mounts}}', 'json .HostConfig}}', '.Log', '{{range .Config.Env}}{{json'):
        assert forbidden not in template
    assert template.count('.Config.Env') == 1
    with pytest.raises(Refused):
        inspect_template(('A" "B',))


# --- identity, daemon and topology ---------------------------------------

def _wrong_daemon(rig):
    rig.docker.daemon = 'ffffffff-4b5a-4968-8776-655443322110'


def _foreign_row(rig):
    rig.docker.override['inspect'] = lambda argv: rig.docker._inspect(argv[:-1] + (argv[-2],))


def _missing_row(rig):
    rig.docker.override['inspect'] = lambda argv: (0, b''.join(rig.docker._inspect(argv)[1].splitlines(True)[:-1]))


def _replaced_id(rig):
    rig.docker.containers[LEGACY['backend']]['Id'] = 'c' * 64


def _wrong_network(rig):
    rig.docker.network = ['d' * 64, NET_NAME]


def _detached(rig):
    rig.docker.containers[SUPPORT['redis']]['Networks'] = {'other': dict(Aliases=None, IPAMConfig=None, NetworkID='f' * 64)}


@pytest.mark.parametrize('mutation, code', [
    (_wrong_daemon, 'driver-daemon-mismatch'), (_foreign_row, 'driver-inspect-scope'),
    (_missing_row, 'driver-inspect-scope'), (_replaced_id, 'driver-inspect-scope'),
    (_wrong_network, 'driver-network-mismatch'), (_detached, 'driver-network-detached')])
def test_daemon_network_and_services_are_derived_from_runner_and_refused(tmp_path, mutation, code):
    rig = Rig()
    mutation(rig)
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused):
            rig.contract(journal).contain()
        assert journal.last('observed-host-init') is None
    assert rig.driver.refusals[-1] == code
    assert rig.docker.effects() == [] and all(i.blocks == 0 for i in rig.ingress.values())


@pytest.mark.parametrize('swap', [('backend', 'redis'), ('backend', 'cron-worker'),
                                  ('broadcast-worker', 'evolution-api')])
def test_swapped_support_or_target_identity_is_refused_without_effects(tmp_path, swap):
    data = deepcopy(MANIFEST)
    first, second = swap
    a = data['service_ids'] if first in LEGACY else data['support_ids']
    b = data['service_ids'] if second in LEGACY else data['support_ids']
    a[first], b[second] = b[second], a[first]
    rig = Rig(data)
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused):
            rig.contract(journal).contain()
    assert rig.docker.effects() == [] and all(i.blocks == 0 for i in rig.ingress.values())


def _drift(kind):
    def mutate(rig):
        c = rig.docker.containers[LEGACY['cron-worker']]
        if kind == 'gate':
            c['Env'] = [e.replace('ASYNC_ENABLED=false', 'ASYNC_ENABLED=true') for e in c['Env']]
        elif kind == 'gate-removed':
            c['Env'] = [e for e in c['Env'] if not e.startswith('ALLOW_REAL_SENDS=')]
        elif kind == 'mount':
            c['Mounts'][0]['Source'] = '/srv/other'
        elif kind == 'alias':
            c['Networks'][NET_NAME]['Aliases'] = ['cron-worker', 'extra']
        elif kind == 'network':
            c['Networks']['extra_net'] = dict(Aliases=None, IPAMConfig=None, NetworkID='f' * 64)
        elif kind == 'support':
            rig.docker.containers[SUPPORT['redis']]['Networks'][NET_NAME]['Aliases'] = ['cache']
        elif kind == 'image':
            c['Image'] = 'sha256:' + 'c' * 64
    return mutate


@pytest.mark.parametrize('kind', ['gate', 'gate-removed', 'mount', 'alias', 'network', 'support', 'image'])
def test_drift_after_ingress_block_refuses_before_restart_effects(tmp_path, kind):
    rig = Rig()
    rig.ingress['evolution-backend'].on_block = lambda: _drift(kind)(rig)
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused):
            rig.contract(journal).contain()
        assert journal.last('observed-host-contained') is None
    assert rig.docker.effects() == []


# --- ingress and writers --------------------------------------------------

def test_internal_ingress_still_open_after_block_is_refused_before_restart_effects(tmp_path):
    rig = Rig()
    rig.ingress['evolution-backend'].stuck = True
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused):
            rig.contract(journal).contain()
        assert journal.last('observed-host-done', 'ingress') is None
    assert rig.driver.refusals[-1] == 'driver-ingress-still-open'
    assert rig.ingress['external'].state == 'blocked' and rig.docker.effects() == []


def test_internal_ingress_reopened_after_containment_is_refused(tmp_path):
    rig = Rig()
    with Journal(tmp_path / 'journal') as journal:
        rig.contract(journal).contain()
        rig.ingress['evolution-backend'].state = 'open'
        count = len(rig.docker.effects())
        with pytest.raises(Refused, match='^observed-host-ingress-reopened$'):
            rig.contract(journal).contain()
        with pytest.raises(Refused, match='^observed-host-ingress-reopened$'):
            rig.contract(journal).assert_contained()
    assert len(rig.docker.effects()) == count and rig.ingress['evolution-backend'].blocks == 1


@pytest.mark.parametrize('value', ['blocked ', True, None, 1])
def test_ingress_callback_shape_is_strict(value):
    rig = Rig()
    rig.ingress['external'].state = value
    with pytest.raises(Refused, match='^driver-ingress-shape$'):
        rig.driver.request(('inspect-host',), timeout=10)


@pytest.mark.parametrize('when', ['before', 'after'])
def test_unexpected_writer_is_refused(tmp_path, when):
    rig = Rig()
    with Journal(tmp_path / 'journal') as journal:
        if when == 'before':
            rig.writers.count = 1
            with pytest.raises(Refused, match='^observed-host-unknown-writer$'):
                rig.contract(journal).contain()
            assert rig.docker.effects() == []
        else:
            rig.contract(journal).contain()
            rig.writers.count = 1
            with pytest.raises(Refused, match='^observed-host-unknown-writer$'):
                rig.contract(journal).assert_contained()
    for value in (True, -1, '0'):
        rig.writers.count = value
        with pytest.raises(Refused, match='^driver-writer-shape$'):
            rig.driver.request(('inspect-host',), timeout=10)


# --- runner failures ------------------------------------------------------

def _timeout(_argv):
    raise TimeoutError('docker said ' + SECRET)


def _rows(rig, edit):
    def respond(argv):
        lines = [json.loads(line) for line in rig.docker._inspect(argv)[1].decode().splitlines()]
        edit(lines)
        return 0, ''.join(json.dumps(line) + '\n' for line in lines).encode()
    return respond


FAILURES = {
    'timeout': ('inspect', lambda rig: _timeout, 'observed-host-timeout', None),
    'malformed': ('inspect', lambda rig: lambda argv: (0, b'{not json ' + SECRET.encode() + b'\n'),
                  'observed-host-effect-failed', 'driver-inspect-malformed'),
    'oversize': ('inspect', lambda rig: lambda argv: (0, b'x' * (64 * 1024 + 1)),
                 'observed-host-effect-failed', 'driver-output-oversize'),
    'exit-nonzero': ('inspect', lambda rig: lambda argv: (1, ('Error: ' + SECRET + '\n').encode()),
                     'observed-host-effect-failed', 'driver-inspect-failed'),
    'nan': ('inspect', lambda rig: lambda argv: (0, b'NaN\n' * 7), 'observed-host-effect-failed',
            'driver-inspect-malformed'),
    'exit-code-bool': ('inspect', lambda rig: _rows(rig, lambda ls: ls[0].__setitem__(9, False)),
                       'observed-host-effect-failed', 'driver-inspect-state'),
    'exit-code-range': ('inspect', lambda rig: _rows(rig, lambda ls: ls[0].__setitem__(9, 256)),
                        'observed-host-effect-failed', 'driver-inspect-state'),
    'started-at': ('inspect', lambda rig: _rows(rig, lambda ls: ls[0].__setitem__(10, 'yesterday')),
                   'observed-host-effect-failed', 'driver-inspect-state'),
    'paused': ('inspect', lambda rig: _rows(rig, lambda ls: ls[0].__setitem__(7, True)),
               'observed-host-effect-failed', 'driver-inspect-state'),
    'status-mismatch': ('inspect', lambda rig: _rows(rig, lambda ls: ls[0].__setitem__(5, 'exited')),
                        'observed-host-effect-failed', 'driver-inspect-state'),
    'policy': ('inspect', lambda rig: _rows(rig, lambda ls: ls[0].__setitem__(13, 'unless-stopped')),
               'observed-host-effect-failed', 'driver-inspect-state'),
    'extra-env': ('inspect', lambda rig: _rows(rig, lambda ls: ls[0][15].insert(0, 'DATABASE_URL=' + SECRET)),
                  'observed-host-effect-failed', 'driver-inspect-gates'),
    'info-garbage': ('info', lambda rig: lambda argv: (0, b'Client: ' + SECRET.encode() + b'\n'),
                     'observed-host-effect-failed', 'driver-daemon-malformed'),
    'runner-crash': ('info', lambda rig: lambda argv: (_ for _ in ()).throw(OSError(SECRET)),
                     'observed-host-effect-failed', 'driver-runner-failed'),
    'runner-shape': ('network', lambda rig: lambda argv: ('0', b''), 'observed-host-effect-failed',
                     'driver-runner-failed'),
    'redis-noauth': ('redis', lambda rig: lambda argv: (0, b'NOAUTH Authentication required.\n'),
                     'observed-host-effect-failed', 'driver-redis-auth-required'),
    'redis-garbage': ('redis', lambda rig: lambda argv: (0, b'(error) ' + SECRET.encode() + b'\n'),
                      'observed-host-effect-failed', 'driver-redis-output'),
}


@pytest.mark.parametrize('name', sorted(FAILURES))
def test_runner_failures_are_sanitized_refusals_without_effects(tmp_path, name):
    kind, respond, contract_code, driver_code = FAILURES[name]
    rig = Rig()
    rig.docker.override[kind] = respond(rig)
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused) as raised:
            rig.contract(journal).contain()
    assert str(raised.value) == contract_code and SECRET not in chain(raised.value)
    if driver_code:
        assert rig.driver.refusals[-1] == driver_code
    assert rig.docker.effects() == [] and all(i.blocks == 0 for i in rig.ingress.values())
    assert SECRET not in journal_text(tmp_path) and SECRET not in repr(rig.driver.refusals)


def chain(exc):
    seen = []
    while exc is not None:
        seen.append(repr(exc) + repr(getattr(exc, 'args', ())))
        exc = exc.__cause__ or exc.__context__
    return ' '.join(seen)


def test_direct_driver_errors_never_carry_runner_output():
    rig = Rig()
    rig.docker.override['inspect'] = lambda argv: (1, ('Error: ' + SECRET).encode())
    with pytest.raises(Refused) as raised:
        rig.driver.request(('inspect-host',), timeout=10)
    assert str(raised.value) == 'driver-inspect-failed' and SECRET not in chain(raised.value)
    rig.docker.override['inspect'] = _timeout
    with pytest.raises(TimeoutError) as timed:
        rig.driver.request(('inspect-host',), timeout=10)
    assert SECRET not in chain(timed.value)
    rig.docker.override['inspect'] = lambda argv: (_ for _ in ()).throw(ValueError(SECRET))
    with pytest.raises(Refused) as raised:
        rig.driver.request(('inspect-host',), timeout=10)
    assert str(raised.value) == 'driver-runner-failed' and chain(raised.value).count('Error') == 0


# --- abnormal exit, unanswered TERM and replay -----------------------------

def test_exit_143_is_refused_and_replay_never_resignals(tmp_path):
    rig = Rig()
    rig.docker.term_exit[LEGACY['cron-worker']] = 143
    with Journal(tmp_path / 'journal') as journal:
        for _ in range(2):
            with pytest.raises(Refused):
                rig.contract(journal).contain()
        assert journal.last('observed-host-contained') is None
    kills = [argv for argv in rig.docker.effects() if argv[1] == 'kill']
    assert kills.count(host_command('term', LEGACY['cron-worker'])) == 1
    assert host_command('term', LEGACY['broadcast-worker']) not in kills


def test_unanswered_term_times_out_and_replay_waits_without_resignal(tmp_path):
    rig = Rig()
    rig.docker.ignore_term.add(LEGACY['backend'])
    with Journal(tmp_path / 'journal') as journal:
        for _ in range(3):
            with pytest.raises(Refused, match='^observed-host-timeout$'):
                rig.contract(journal).contain()
    effects = rig.docker.effects()
    assert effects.count(host_command('term', LEGACY['backend'])) == 1
    assert effects.count(host_command('wait', LEGACY['backend'])) == 3
    assert rig.docker.containers[LEGACY['backend']]['State']['Running'] is True  # never killed/escalated
    assert not any(argv[1] == 'kill' and argv[2] != '--signal=TERM' for argv in effects)


def test_crash_after_signal_is_adopted_on_replay_without_resignal(tmp_path):
    rig = Rig()
    def crash(argv):
        rig.docker.after.pop('kill')
        raise KeyboardInterrupt()
    rig.docker.after['kill'] = crash
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(KeyboardInterrupt):
            rig.contract(journal).contain()
    with Journal(tmp_path / 'journal') as journal:
        Rig.contract(rig, journal).contain()
    assert rig.docker.effects().count(host_command('term', LEGACY['backend'])) == 1


# --- forbidden operations and Redis scope ----------------------------------

@pytest.mark.parametrize('argv', [
    host_command('start', LEGACY['backend']), host_command('restart-always', LEGACY['backend']),
    ('open-ingress',), ('docker', 'kill', '--signal=KILL', LEGACY['backend']),
    ('docker', 'rm', '-f', LEGACY['backend']), ('docker', 'restart', LEGACY['backend']),
    host_command('restart-no', SUPPORT['redis']), host_command('term', SUPPORT['evolution-api']),
    host_command('wait', 'c' * 64), ('inspect-host', 'extra'), ('redis-meta', 'KEYS', '*'),
    ('redis-meta', 'SCAN', '0'), ('redis-meta', 'GET', 'pastorai:webhooks'),
    ('redis-meta', 'LLEN', 'pastorai:other'), ('redis-meta', 'LLEN', 'pastorai:webhooks', 'extra'),
    ['inspect-host'], (b'inspect-host',), (),
])
def test_mutators_and_unscoped_commands_refuse_before_any_runner_call(argv):
    rig = Rig()
    with pytest.raises(Refused, match='^driver-(operation-forbidden|redis-scope)$'):
        rig.driver.request(argv, timeout=5)
    assert rig.docker.calls == []


def test_resume_through_contract_never_reaches_a_start_or_restart_always(tmp_path):
    rig = Rig()
    with Journal(tmp_path / 'journal') as journal:
        contract = rig.contract(journal)
        contract.contain()
        before, events = list(rig.docker.calls), list(journal.events)
        with pytest.raises(Refused, match='^observed-host-resume-unavailable$'):
            contract.resume_legacy(contract.resume_token())
        assert journal.events == events
        assert journal.last('observed-host-intent', 'legacy-resume') is None
        assert contract.assert_contained()['host_verified'] is False
    assert rig.driver.refusals == []
    assert not any(FakeDocker.kind(argv) in ('update', 'kill', 'wait') for argv in rig.docker.calls[len(before):])


def test_redis_metadata_uses_only_scoped_read_commands_without_auth_in_argv():
    rig = Rig()
    snapshot = rig.transport.snapshot()
    assert snapshot['queue_counts']['pastorai:webhooks'] == 3
    redis = [argv for argv in rig.docker.calls if FakeDocker.kind(argv) == 'redis']
    assert {argv[5] for argv in redis} == {'TYPE', 'PTTL', 'LLEN', 'ZCARD'}
    keys = {argv[6] for argv in redis}
    assert keys == {'pastorai:webhooks', 'pastorai:webhooks:processing', 'pastorai:webhooks:dead',
                    'pastorai:webhooks:retry-scheduled', 'pastorai:webhooks:processing:worker-1'}
    flat = ' '.join(' '.join(argv) for argv in redis)
    for forbidden in (' -a ', '--pass', '--user', 'AUTH', ' -u ', 'KEYS', 'SCAN', 'redis://'):
        assert forbidden not in flat


@pytest.mark.parametrize('state', ['unobserved', 'failed-inspect', 'mislabeled'])
def test_redis_exec_only_targets_a_container_just_verified_as_redis(state):
    rig = Rig()
    if state != 'unobserved':
        rig.driver.request(('inspect-host',), timeout=10)
        if state == 'failed-inspect':
            rig.docker.override['inspect'] = lambda argv: (1, b'')
        else:
            rig.docker.containers[SUPPORT['redis']]['Labels'][SERVICE] = 'backend'
        try:
            rig.driver.request(('inspect-host',), timeout=10)
        except Refused:
            pass
    rig.docker.calls.clear()
    with pytest.raises(Refused, match='^driver-redis-unverified$'):
        rig.driver.request(('redis-meta', 'LLEN', 'pastorai:webhooks'), timeout=5)
    assert rig.docker.calls == []


# --- PopenRunner, with a mocked Popen only ---------------------------------

class FakeProc:
    def __init__(self, data=b'', *, close=True, returncode=0, exits=True):
        read, self.write = os.pipe()
        if data:
            os.write(self.write, data)
        if close:
            os.close(self.write)
            self.write = None
        self.stdout = os.fdopen(read, 'rb', buffering=0)
        self.returncode, self.exits, self.killed, self.waits = returncode, exits, 0, []

    def poll(self):
        return self.returncode if self.exits or self.killed else None

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if not (self.exits or self.killed == 99):
            raise subprocess.TimeoutExpired('docker', timeout)
        return self.returncode

    def kill(self):
        self.killed += 1
        if self.write is not None:
            os.close(self.write)
            self.write = None


class FakePopen:
    def __init__(self, proc):
        self.proc, self.calls = proc, []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return self.proc


def runner(popen, **overrides):
    options = dict(docker_binary='/usr/bin/docker', endpoint='unix:///run/igreja12/docker.sock',
                   config_dir='/srv/igreja12/empty-docker-config', popen=popen, cleanup_wait=0.05)
    options.update(overrides)
    return PopenRunner(**options)


def test_popen_runner_uses_explicit_endpoint_minimal_env_and_no_shell(monkeypatch):
    for name in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG', 'DOCKER_CERT_PATH', 'HOME'):
        monkeypatch.setenv(name, '/inherited/' + SECRET)
    popen = FakePopen(FakeProc(b'"' + DAEMON.encode() + b'"\n'))
    rc, out = runner(popen)(('docker', 'info', '--format', '{{json .ID}}'), timeout=5, max_output=256)
    assert (rc, out) == (0, b'"' + DAEMON.encode() + b'"\n')
    [(args, kwargs)] = popen.calls
    assert args == ['/usr/bin/docker', '--config', '/srv/igreja12/empty-docker-config',
                    '--host', 'unix:///run/igreja12/docker.sock', 'info', '--format', '{{json .ID}}']
    assert kwargs['env'] == {'LC_ALL': 'C', 'LANG': 'C'}
    assert kwargs['shell'] is False and kwargs['close_fds'] is True and kwargs['start_new_session'] is True
    assert kwargs['stdin'] is subprocess.DEVNULL and kwargs['stderr'] is subprocess.DEVNULL
    assert kwargs['stdout'] is subprocess.PIPE and kwargs['cwd'] == '/'
    assert popen.proc.killed == 0 and popen.proc.stdout.closed


def test_popen_runner_timeout_ends_only_its_own_cli_with_bounded_wait():
    proc = FakeProc(b'partial', close=False, exits=False)
    with pytest.raises(TimeoutError) as raised:
        runner(FakePopen(proc))(('docker', 'wait', LEGACY['backend']), timeout=0.05, max_output=16)
    assert proc.killed == 1 and proc.waits == [0.05] and raised.value.__cause__ is None
    assert proc.stdout.closed


def test_popen_runner_process_that_never_exits_after_eof_is_bounded():
    proc = FakeProc(b'0\n', exits=False)
    with pytest.raises(TimeoutError):
        runner(FakePopen(proc))(('docker', 'wait', LEGACY['backend']), timeout=0.05, max_output=16)
    assert proc.killed == 1 and len(proc.waits) == 2


def test_popen_runner_oversize_output_is_refused_and_memory_is_capped():
    proc = FakeProc(b'y' * 4096, close=False, exits=False)
    with pytest.raises(Refused, match='^runner-output-oversize$'):
        runner(FakePopen(proc))(('docker', 'info', '--format', '{{json .ID}}'), timeout=1, max_output=16)
    assert proc.killed == 1 and proc.stdout.closed


def test_popen_runner_returns_nonzero_status_and_sanitizes_spawn_failure():
    rc, out = runner(FakePopen(FakeProc(b'', returncode=1)))(
        ('docker', 'info', '--format', '{{json .ID}}'),
        timeout=1, max_output=16)
    assert (rc, out) == (1, b'')
    def explode(*_args, **_kwargs):
        raise OSError(SECRET)
    with pytest.raises(Refused, match='^runner-spawn-failed$') as raised:
        runner(explode)(('docker', 'info', '--format', '{{json .ID}}'), timeout=1, max_output=16)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize('argv', [
    ('docker', 'start', 'a' * 64), ('docker', 'rm', 'a' * 64), ('docker', 'run', 'x'),
    ('docker', 'network', 'disconnect', 'n', 'c'), ('docker', 'exec', 'a' * 64, 'sh', '-c', 'x'),
    ('docker', '--host', 'tcp://x', 'info'), ('sh', '-c', 'docker info'), ['docker', 'info'],
    ('docker', 'info', 'a\x00b'),
])
def test_popen_runner_refuses_unapproved_argv_before_spawn(argv):
    popen = FakePopen(FakeProc())
    with pytest.raises(Refused, match='^runner-argv$'):
        runner(popen)(argv, timeout=1, max_output=16)
    assert popen.calls == []


@pytest.mark.parametrize('override', [
    dict(endpoint='tcp://10.0.0.1:2375'), dict(endpoint='ssh://root@host'), dict(endpoint=None),
    dict(endpoint='unix://relative.sock'), dict(docker_binary='docker'), dict(docker_binary='/usr/bin/../x'),
    dict(config_dir='~/.docker'), dict(config_dir=None), dict(cleanup_wait=0), dict(cleanup_wait=60),
])
def test_popen_runner_requires_explicit_nominal_configuration(override):
    popen = FakePopen(FakeProc())
    with pytest.raises(Refused, match='^runner-config$'):
        runner(popen, **override)
    assert popen.calls == []


def test_popen_runner_bounds_timeout_and_output():
    popen = FakePopen(FakeProc())
    for timeout, max_output in ((0, 16), (61, 16), (1, 0), (1, 2 * 1024 * 1024), (True, 16)):
        with pytest.raises(Refused, match='^runner-bounds$'):
            runner(popen)(('docker', 'info', '--format', '{{json .ID}}'), timeout=timeout, max_output=max_output)
    assert popen.calls == []


def test_module_import_and_construction_are_inert():
    source = (Path(__file__).resolve().parents[1] / 'first_transition_host_driver.py').read_text()
    assert '__main__' not in source and 'argparse' not in source and 'shell=True' not in source
    popen = FakePopen(FakeProc())
    runner(popen)
    Rig()
    assert popen.calls == []


@pytest.mark.parametrize('names', [['ALLOW_REAL_SENDS'], ['DB'],
                                 ['ALLOW_REAL_SENDS', 'ASAAS_BILLING_ENABLED', 'BREVO_SEND_MODE']])
def test_all_operational_gates_are_mandatory_and_arbitrary_names_forbidden(names):
    with pytest.raises(Refused, match='manifest-gate-names'):
        HostManifest.from_dict(_bad_manifest(lambda d: d.update(gate_names=names)))


def test_attachment_identity_not_only_network_name_is_observed(tmp_path):
    rig = Rig()
    rig.docker.containers[LEGACY['backend']]['Networks'][NET_NAME]['NetworkID'] = 'f' * 64
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused):
            rig.contract(journal).contain()
        assert not any(c[1] in ('update', 'kill', 'wait') for c in rig.docker.calls)
        assert rig.ingress['external'].blocks == 0


@pytest.mark.parametrize('argv', [
    ('docker', 'kill', '--signal=TERM', '--signal=KILL', LEGACY['backend']),
    ('docker', 'update', '--restart=no', '--restart=always', LEGACY['backend']),
    ('docker', 'update', '--restart=no', '--cpus=4', LEGACY['backend']),
    ('docker', 'inspect', LEGACY['backend']),
    ('docker', 'inspect', '--format', '{{json .Config.Env}}', LEGACY['backend']),
    ('docker', 'info', '--format', '{{json .}}'),
    ('docker', 'wait', LEGACY['backend'], SUPPORT['redis']),
    ('docker', 'network', 'inspect', NETWORK),
])
def test_runner_rejects_duplicate_options_and_unrestricted_acquisition(argv):
    proc = FakeProc()
    popen = FakePopen(proc)
    try:
        with pytest.raises(Refused, match='^runner-argv$'):
            runner(popen)(argv, timeout=1, max_output=256)
        assert popen.calls == []
    finally:
        proc.stdout.close()


def test_journal_cannot_be_adopted_by_another_daemon_manifest(tmp_path):
    first = Rig()
    with Journal(tmp_path / 'journal') as journal:
        first.contract(journal).contain()
    data = deepcopy(MANIFEST)
    data['daemon_id'] = 'ffffffff-4b5a-4968-8776-655443322110'
    second = Rig(data)
    second.docker.daemon = data['daemon_id']
    second.docker.containers = deepcopy(first.docker.containers)
    for entry in ENTRIES:
        second.ingress[entry].state = 'blocked'
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused):
            second.contract(journal).contain()
        assert second.docker.effects() == []


def test_a_directly_replaced_manifest_cannot_reuse_an_old_digest():
    from dataclasses import replace
    rig = Rig()
    forged = replace(rig.manifest, daemon_id='ffffffff-4b5a-4968-8776-655443322110')
    with pytest.raises(Refused):
        ObservedHostDriver(forged, runner=rig.docker, ingress=rig.ingress, writers=rig.writers)
    assert rig.docker.calls == []


def test_late_callback_response_is_not_accepted(monkeypatch):
    import first_transition_host_driver as module
    clock = [0.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    rig = Rig()
    def late(scope, *, timeout):
        clock[0] += 20
        return 0
    rig.writers.observe = late
    with pytest.raises(TimeoutError):
        rig.driver.request(('inspect-host',), timeout=10)


def test_stdout_close_failure_is_sanitized_and_cli_is_reaped():
    proc = FakeProc(b'"' + DAEMON.encode() + b'"\n')
    stream = proc.stdout
    class BadClose:
        def fileno(self):
            return stream.fileno()
        def close(self):
            stream.close()
            raise OSError(SECRET)
    proc.stdout = BadClose()
    with pytest.raises(Refused, match='^runner-close-failed$') as raised:
        runner(FakePopen(proc))(('docker', 'info', '--format', '{{json .ID}}'), timeout=1, max_output=256)
    assert SECRET not in str(raised.value) and stream.closed
    assert len(proc.waits) == 2


def test_a_callback_cannot_rebind_itself_during_observation(tmp_path):
    rig = Rig()
    original = rig.writers.observe
    def rebinding(scope, *, timeout):
        answer = original(scope, timeout=timeout)
        rig.writers.scope = 'f' * 64
        return answer
    rig.writers.observe = rebinding
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused):
            rig.contract(journal).contain()
        assert rig.docker.effects() == []


def test_injected_runner_refusals_cannot_become_secret_diagnostics():
    rig = Rig()
    def refused(*_args, **_kwargs):
        raise Refused('a' * 64)
    rig.driver.runner = refused
    with pytest.raises(Refused, match='^driver-runner-failed$'):
        rig.driver.request(('inspect-host',), timeout=10)
    assert 'a' * 64 not in rig.driver.refusals


def test_unreaped_cli_latches_runner_before_another_spawn():
    proc = FakeProc(b'', exits=False)
    popen = FakePopen(proc)
    request = runner(popen)
    with pytest.raises(TimeoutError):
        request(('docker', 'wait', LEGACY['backend']), timeout=0.01, max_output=16)
    assert request.unreaped > 0
    with pytest.raises(Refused, match='^runner-pending-cli$'):
        request(('docker', 'info', '--format', '{{json .ID}}'), timeout=1, max_output=256)
    assert len(popen.calls) == 1


@pytest.mark.parametrize('operation', ['restart-no', 'term'])
def test_daemon_runner_cannot_rebind_before_effect(operation):
    rig = Rig()
    rig.docker.after['info'] = lambda _argv: setattr(rig.writers, 'scope', 'f' * 64)
    command = ('docker', 'update', '--restart=no', LEGACY['backend']) if operation == 'restart-no' else (
        'docker', 'kill', '--signal=TERM', LEGACY['backend'])
    with pytest.raises(Refused, match='^driver-writer-binding$'):
        rig.driver.request(command, timeout=10)
    assert rig.docker.effects() == []


def test_transport_cannot_omit_manifest_processing_scope():
    rig = Rig()
    scope = rig.manifest.transport_scope()
    scope['processing_keys'] = ()
    with pytest.raises(Refused, match='^transport-driver-scope$'):
        ObservedHostTransport(rig.driver, **scope).snapshot()


def test_transport_cannot_mutate_processing_scope_after_construction():
    rig = Rig()
    rig.transport.processing_keys = ()
    with pytest.raises(Refused, match='^transport-driver-scope$'):
        rig.transport.snapshot()


# --- resume gated by a fresh read-only ledger proof (block B) ----------------

from first_transition_database import LedgerProof, ReadOnlyDatabase  # noqa: E402
from first_transition_host_contract import START_ORDER  # noqa: E402
from test_first_transition_database import CATALOG_ONLY_DDL, FakePg  # noqa: E402


class ResumeRig(Rig):
    def __init__(self, *, openers=True, proof_scope=None):
        super().__init__()
        self.pg = FakePg(['0001_base.sql', '0002_more.sql'])
        self.proofs = []  # index into docker.calls at which each fresh proof connected
        self.pg.on_connect = lambda: self.proofs.append(len(self.docker.calls))
        self.proof = LedgerProof(ReadOnlyDatabase(self.pg.connect), self.pg.expectation(),
                                 scope=proof_scope or self.manifest.digest)
        if not openers:
            for binding in self.ingress.values():
                binding.open = None
        self.driver = ObservedHostDriver(self.manifest, runner=self.docker, ingress=self.ingress,
                                         writers=self.writers, ledger_proof=self.proof)
        self.transport = ObservedHostTransport(self.driver, **self.manifest.transport_scope())

    def resume_effects(self):
        return [(i, argv) for i, argv in enumerate(self.docker.calls)
                if argv[:2] == ('docker', 'start') or argv[:3] == ('docker', 'update', '--restart=always')]


def test_resume_runs_a_fresh_ledger_proof_before_every_effect(tmp_path):
    rig = ResumeRig()
    with Journal(tmp_path / 'journal') as journal:
        contract = rig.contract(journal)
        contract.contain()
        assert rig.driver.supports_resume is True and rig.pg.connections == 0
        result = contract.resume_legacy(contract.resume_token())
        assert result['status'] == 'legacy-resumed' and result['host_verified'] is False
    effects = rig.resume_effects()
    assert [argv for _, argv in effects] == [
        host_command(op, LEGACY[role]) for role in START_ORDER for op in ('start', 'restart-always')]
    # One proof per resume request (8 container effects + open-ingress), each before its own effect.
    assert len(rig.proofs) == 9 and rig.pg.closed == 9
    previous = -1
    for (index, _), proof in zip(effects, rig.proofs):
        assert previous < proof <= index
        previous = index
    assert all(i.state == 'open' for i in rig.ingress.values())


@pytest.mark.parametrize('drift', [
    lambda pg: pg.ledger.append('0003_applied_elsewhere.sql'),
    lambda pg: pg.extra_ddl.append('rogue_table'),
    lambda pg: setattr(pg, 'system', '7300000000000000009'),
    lambda pg: pg.invalid.append('half_built_idx'),
    *(CATALOG_ONLY_DDL[name] for name in ('column-default', 'function-body', 'policy-qual', 'constraint-def',
                                          'trigger-disabled', 'rls-disabled')),
])
def test_ddl_or_ledger_drift_without_journal_marker_refuses_resume_before_any_start(tmp_path, drift):
    rig = ResumeRig()
    with Journal(tmp_path / 'journal') as journal:
        contract = rig.contract(journal)
        contract.contain()
        drift(rig.pg)
        assert journal.last('ddl-marker') is None  # journal absence alone is not accepted as proof
        with pytest.raises(Refused, match='^observed-host-effect-failed$'):
            contract.resume_legacy(contract.resume_token())
    assert rig.resume_effects() == [] and rig.driver.refusals[-1].startswith('driver-ledger-proof')
    assert all(i.state == 'blocked' for i in rig.ingress.values())
    assert all(not rig.docker.containers[i]['State']['Running'] for i in LEGACY.values())


def test_drift_after_first_start_stops_before_the_next_effect_and_replay(tmp_path):
    rig = ResumeRig()
    rig.docker.after['start'] = lambda _argv: rig.pg.extra_ddl.append('rogue_table')
    with Journal(tmp_path / 'journal') as journal:
        contract = rig.contract(journal)
        contract.contain()
        with pytest.raises(Refused):
            contract.resume_legacy(contract.resume_token())
        assert [argv for _, argv in rig.resume_effects()] == [host_command('start', LEGACY['backend'])]
        with pytest.raises(Refused):
            contract.resume_legacy(contract.resume_token())
    assert [argv for _, argv in rig.resume_effects()] == [host_command('start', LEGACY['backend'])]
    assert all(i.state == 'blocked' for i in rig.ingress.values())


def test_open_ingress_needs_its_own_fresh_proof(tmp_path):
    rig = ResumeRig()
    last = host_command('restart-always', LEGACY[START_ORDER[-1]])
    rig.docker.after['update'] = lambda argv: argv == last and rig.pg.ledger.append('0003_late.sql')
    with Journal(tmp_path / 'journal') as journal:
        contract = rig.contract(journal)
        contract.contain()
        with pytest.raises(Refused):
            contract.resume_legacy(contract.resume_token())
        assert journal.last('observed-host-intent', 'open-ingress') is not None
        assert journal.last('observed-host-done', 'open-ingress') is None
    assert all(i.state == 'blocked' for i in rig.ingress.values())


@pytest.mark.parametrize('fault', ['before', 'after'])
def test_partial_ingress_opening_is_never_recorded_as_resumed(tmp_path, fault):
    # Internal entry opens; the external opening times out before (or after) taking effect.
    rig = ResumeRig()
    rig.ingress['external'].open_timeout = fault
    with Journal(tmp_path / 'journal') as journal:
        contract = rig.contract(journal)
        contract.contain()
        with pytest.raises(Refused, match='^observed-host-timeout$'):
            contract.resume_legacy(contract.resume_token())
        assert journal.last('observed-host-done', 'open-ingress') is None
        assert journal.last('observed-host-resumed') is None
        assert rig.ingress['evolution-backend'].state == 'open'
        assert rig.ingress['external'].state == ('blocked' if fault == 'before' else 'open')
        if fault == 'before':
            # Mixed state: neither blocked nor open; replay must not take it for "all open".
            raw = rig.driver.request(('inspect-host',), timeout=10)
            assert raw['ingress_blocked'] is False and raw['ingress_open'] is False
        proofs = len(rig.proofs)
        seen = []
        rig.ingress['external'].on_open = lambda: seen.append(len(rig.proofs))
        result = rig.contract(journal).resume_legacy(None)
        assert result['status'] == 'legacy-resumed' and journal.last('observed-host-resumed') is not None
    assert all(i.state == 'open' for i in rig.ingress.values())
    assert rig.ingress['evolution-backend'].opens == 1  # an open entry is never re-opened
    if fault == 'before':
        # Only the remaining blocked entry is opened, after a fresh ledger proof of its own request.
        assert rig.ingress['external'].opens == 2 and seen == [proofs + 1]
    else:
        assert rig.ingress['external'].opens == 1 and seen == []  # already open: no new effect


def test_partial_ingress_replay_with_ddl_drift_opens_nothing(tmp_path):
    rig = ResumeRig()
    rig.ingress['external'].open_timeout = 'before'
    with Journal(tmp_path / 'journal') as journal:
        contract = rig.contract(journal)
        contract.contain()
        with pytest.raises(Refused, match='^observed-host-timeout$'):
            contract.resume_legacy(contract.resume_token())
        rig.pg.extra_ddl.append('rogue_table')
        with pytest.raises(Refused, match='^observed-host-effect-failed$'):
            rig.contract(journal).resume_legacy(None)
        assert journal.last('observed-host-resumed') is None
    assert rig.ingress['external'].state == 'blocked' and rig.ingress['external'].opens == 1
    assert rig.driver.refusals[-1] == 'driver-ledger-proof'


def test_resume_is_unavailable_without_openers_and_proof_scope_is_bound(tmp_path):
    rig = ResumeRig(openers=False)
    assert rig.driver.supports_resume is False
    with Journal(tmp_path / 'journal') as journal:
        contract = rig.contract(journal)
        contract.contain()
        with pytest.raises(Refused, match='^observed-host-resume-unavailable$'):
            contract.resume_legacy(contract.resume_token())
    with pytest.raises(Refused, match='^driver-operation-forbidden$'):
        rig.driver.request(('open-ingress',), timeout=5)
    assert rig.pg.connections == 0 and rig.resume_effects() == []
    with pytest.raises(Refused, match='^driver-ledger-binding$'):
        ResumeRig(proof_scope='a' * 64)


def test_rebound_ledger_proof_refuses_before_effects(tmp_path):
    rig = ResumeRig()
    with Journal(tmp_path / 'journal') as journal:
        contract = rig.contract(journal)
        contract.contain()
        rig.driver.ledger_proof = LedgerProof(ReadOnlyDatabase(rig.pg.connect), rig.pg.expectation(),
                                              scope=rig.manifest.digest)
        with pytest.raises(Refused):
            contract.resume_legacy(contract.resume_token())
    assert rig.resume_effects() == []


def test_popen_runner_accepts_resume_commands_only_when_configured():
    for argv in (('docker', 'start', 'a' * 64), ('docker', 'update', '--restart=always', 'a' * 64)):
        popen = FakePopen(FakeProc())
        with pytest.raises(Refused, match='^runner-argv$'):
            runner(popen)(argv, timeout=1, max_output=16)
        popen = FakePopen(FakeProc())
        runner(popen, resume=True)(argv, timeout=1, max_output=256)
        assert popen.calls and popen.calls[0][0][-len(argv) + 1:] == list(argv[1:])
    for argv in (('docker', 'start', 'x'), ('docker', 'update', '--restart=unless-stopped', 'a' * 64)):
        with pytest.raises(Refused, match='^runner-argv$'):
            runner(FakePopen(FakeProc()), resume=True)(argv, timeout=1, max_output=16)
