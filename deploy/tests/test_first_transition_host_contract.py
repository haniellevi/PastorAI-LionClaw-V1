"""Host effects are in-memory only; no Docker/SSH/Redis/application is used."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from first_transition_adapter import ROLES, Refused
from first_transition_host_contract import LocalHostContract
from initial_transition_files import Journal


class FakeHost:
    def __init__(self):
        self.calls = []
        self.timeout = False
        self.crash_after_signal = False
        self.data = dict(mode='local-simulation', ingress_blocked=False,
                         support_digest='a' * 64, unknown_writers=0, services={})
        for number, role in enumerate(ROLES, 1):
            compose = role != 'broadcast-worker'
            self.data['services'][role] = dict(
                id=str(number) * 64, image='sha256:' + 'b' * 64, revision=None,
                compose_project='synthetic-legacy' if compose else None,
                compose_service=role if compose else None,
                started='synthetic-start', restart_count=0, restart_policy='always',
                running=True, exit_code=None, gates_digest='c' * 64,
                mounts_digest='d' * 64, networks_digest='e' * 64,
            )

    def snapshot(self):
        return deepcopy(self.data)

    def block_ingress(self):
        self.calls.append(('ingress', None))
        self.data['ingress_blocked'] = True

    def _role(self, identifier):
        return next(role for role, state in self.data['services'].items() if state['id'] == identifier)

    def disable_restart(self, identifier):
        role = self._role(identifier)
        self.calls.append(('restart-no', role))
        self.data['services'][role]['restart_policy'] = 'no'

    def signal_term(self, identifier):
        role = self._role(identifier)
        self.calls.append(('term', role))
        self.data['services'][role].update(running=False, exit_code=0)
        if self.crash_after_signal:
            self.crash_after_signal = False
            raise KeyboardInterrupt()

    def wait_stopped(self, identifier, timeout):
        role = self._role(identifier)
        self.calls.append(('wait', role))
        assert timeout == 30
        if self.timeout:
            raise TimeoutError('synthetic wait')


def test_containment_is_ordered_idempotent_and_keeps_legacy_revision_unknown(tmp_path):
    port = FakeHost()
    with Journal(tmp_path / 'journal') as journal:
        host = LocalHostContract(port, journal)
        receipt = host.contain()
        assert receipt['mode'] == 'local-simulation'
        assert port.calls == [('ingress', None)] + [
            operation for role in ROLES for operation in [('restart-no', role), ('term', role), ('wait', role)]]
        assert all(s['revision'] is None for s in port.data['services'].values())
        count = len(port.calls)
        assert host.contain() == receipt
        assert len(port.calls) == count


@pytest.mark.parametrize('mutation', ['unknown-writer', 'support', 'gate', 'project', 'broadcast-compose'])
def test_bad_scope_or_topology_is_refused_without_effects(tmp_path, mutation):
    port = FakeHost()
    with Journal(tmp_path / 'journal') as journal:
        host = LocalHostContract(port, journal)
        if mutation in ('support', 'gate'):
            host.contain()
            port.calls.clear()
            if mutation == 'support':
                port.data['support_digest'] = 'f' * 64
            else:
                port.data['services']['backend']['gates_digest'] = 'f' * 64
        elif mutation == 'unknown-writer':
            port.data['unknown_writers'] = 1
        elif mutation == 'project':
            port.data['services']['cron-worker']['compose_project'] = 'different-project'
        else:
            port.data['services']['broadcast-worker']['compose_project'] = 'synthetic-legacy'
        with pytest.raises(Refused):
            host.contain()
        assert port.calls == []


def test_signal_committed_before_controller_crash_is_adopted_without_resignal(tmp_path):
    port = FakeHost()
    port.crash_after_signal = True
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(KeyboardInterrupt):
            LocalHostContract(port, journal).contain()
    with Journal(tmp_path / 'journal') as journal:
        LocalHostContract(port, journal).contain()
        assert port.calls.count(('term', 'backend')) == 1


def test_timeout_holds_and_never_restarts_a_service(tmp_path):
    port = FakeHost()
    port.timeout = True
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused, match='local-host-timeout'):
            LocalHostContract(port, journal).contain()
        assert not journal.find('local-host-contained')
        assert port.data['services']['backend']['restart_policy'] == 'no'
        assert all(operation not in ('start', 'restart') for operation, _ in port.calls)


def test_non_simulated_transport_refused_before_effects(tmp_path):
    port = FakeHost()
    port.data['mode'] = 'production'
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused):
            LocalHostContract(port, journal).contain()
        assert port.calls == []


def test_crash_before_signal_is_not_blindly_resignalled(tmp_path, monkeypatch):
    port = FakeHost()
    with Journal(tmp_path / 'journal') as journal:
        append = journal.append
        def crash(kind, **fields):
            event = append(kind, **fields)
            if kind == 'local-host-intent' and fields.get('step') == 'term:backend':
                raise KeyboardInterrupt()
            return event
        monkeypatch.setattr(journal, 'append', crash)
        with pytest.raises(KeyboardInterrupt):
            LocalHostContract(port, journal).contain()
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused, match='local-host-exit-not-clean'):
            LocalHostContract(port, journal).contain()
        assert ('term', 'backend') not in port.calls
        assert not journal.last('local-host-contained')


class SimulatedCommandDriver:
    mode = 'local-simulation'

    def __init__(self):
        self.host = FakeHost()
        self.commands = []

    def request(self, argv, *, timeout):
        self.commands.append((argv, timeout))
        if argv == ('snapshot-metadata',):
            return self.host.snapshot()
        if argv == ('block-ingress',):
            self.host.block_ingress()
            return True
        if argv[:3] == ('docker', 'update', '--restart=no'):
            self.host.disable_restart(argv[3])
            return True
        if argv[:3] == ('docker', 'kill', '--signal=TERM'):
            self.host.signal_term(argv[3])
            return True
        if argv[:2] == ('docker', 'wait'):
            self.host.wait_stopped(argv[2], timeout)
            return self.host.data['services'][self.host._role(argv[2])]['exit_code']
        raise AssertionError('unapproved simulated command')


def test_command_transport_drives_real_contract_without_processes(tmp_path, monkeypatch):
    import subprocess
    from first_transition_host_transport import SimulatedHostTransport
    monkeypatch.setattr(subprocess, 'Popen', lambda *_a, **_k: pytest.fail('no process transport'))
    driver = SimulatedCommandDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = LocalHostContract(SimulatedHostTransport(driver), journal)
        assert contract.contain()['host_verified'] is False
        effects = [item for item in driver.commands if item[0] != ('snapshot-metadata',)]
        expected = [(('block-ingress',), 5)]
        for role in ROLES:
            identifier = driver.host.data['services'][role]['id']
            expected.extend([(('docker', 'update', '--restart=no', identifier), 5),
                             (('docker', 'kill', '--signal=TERM', identifier), 5),
                             (('docker', 'wait', identifier), 30)])
        assert effects == expected
        contract.contain()
        assert [item for item in driver.commands if item[0] != ('snapshot-metadata',)] == effects


@pytest.mark.parametrize('method', ['disable_restart', 'signal_term', 'wait_stopped'])
def test_transport_refuses_arbitrary_targets_and_replaced_identity(method):
    from first_transition_host_transport import SimulatedHostTransport
    driver = SimulatedCommandDriver()
    transport = SimulatedHostTransport(driver)
    transport.snapshot()
    args = (30,) if method == 'wait_stopped' else ()
    with pytest.raises(Refused, match='transport-target'):
        getattr(transport, method)('other; shell-command', *args)
    identifier = driver.host.data['services']['backend']['id']
    driver.host.data['services']['backend']['id'] = 'f' * 64
    with pytest.raises(Refused, match='transport-identity-changed'):
        getattr(transport, method)(identifier, *args)
    assert all(command == ('snapshot-metadata',) for command, _ in driver.commands)


def test_transport_refuses_real_driver_before_any_call():
    from first_transition_host_transport import SimulatedHostTransport
    driver = SimulatedCommandDriver()
    driver.mode = 'remote'
    with pytest.raises(Refused, match='transport-simulation-required'):
        SimulatedHostTransport(driver)
    assert driver.commands == []


def test_transport_timeout_holds_without_resignal(tmp_path):
    from first_transition_host_transport import SimulatedHostTransport
    driver = SimulatedCommandDriver()
    driver.host.timeout = True
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused, match='local-host-timeout'):
            LocalHostContract(SimulatedHostTransport(driver), journal).contain()
        assert not journal.last('local-host-contained')
        assert driver.host.calls.count(('term', 'backend')) == 1
        assert all(command[:2] not in (('docker', 'start'), ('docker', 'restart'))
                   for command, _ in driver.commands)


def test_transport_sanitizes_errors_and_bounds_wait():
    from first_transition_host_transport import SimulatedHostTransport
    driver = SimulatedCommandDriver()
    transport = SimulatedHostTransport(driver)
    transport.snapshot()
    with pytest.raises(Refused, match='transport-wait-bound'):
        transport.wait_stopped('1' * 64, 31)
    def fail(*_args, **_kwargs):
        raise ValueError('synthetic-private-payload')
    driver.request = fail
    with pytest.raises(Refused, match='simulated-transport-failed') as failure:
        transport.snapshot()
    assert 'synthetic-private-payload' not in str(failure.value)



def test_transport_timeout_is_sanitized_even_without_contract():
    from first_transition_host_transport import SimulatedHostTransport
    driver = SimulatedCommandDriver()
    def timeout(*_args, **_kwargs):
        raise TimeoutError('synthetic-private-timeout-details')
    driver.request = timeout
    with pytest.raises(TimeoutError, match='^simulated-transport-timeout$'):
        SimulatedHostTransport(driver).snapshot()


NETWORK = '9' * 64


class ObservedDriver:
    supports_resume = True
    scope_digest = 'f' * 64
    mode = 'observed-host'

    def __init__(self):
        self.host = FakeHost()
        self.commands = []
        self.crash_after_start = None
        self.on_start = None
        self.on_inspect = None
        # The fake moves both ingress entries together via host.data['ingress_blocked'];
        # partial_ingress explicitly models one entry diverging (neither blocked nor open).
        self.partial_ingress = False
        self.queues = {'pastorai:webhooks': 3, 'pastorai:webhooks:dead': 1}
        self.support = {role: dict(id=str(number) * 64, image='sha256:' + 'b' * 64,
                                   compose_project='synthetic-legacy', compose_service=role, running=True,
                                   restart_policy='always', health=None if role == 'evolution-api' else 'healthy',
                                   networks_digest='e' * 64)
                        for number, role in zip((5, 6, 7), ('redis', 'evolution-postgres', 'evolution-api'))}

    def request(self, argv, *, timeout):
        self.commands.append((argv, timeout))
        host = self.host
        if argv == ('inspect-host',):
            if self.on_inspect:
                self.on_inspect()
            data = host.snapshot()
            blocked, partial = data['ingress_blocked'], self.partial_ingress
            return dict(scope_digest=self.scope_digest, ingress_blocked=blocked and not partial,
                        ingress_open=not blocked and not partial, unknown_writers=data['unknown_writers'],
                        network_id=NETWORK, services=data['services'], support=deepcopy(self.support))
        if argv[0] == 'redis-meta':
            command, key = argv[1:]
            if command == 'TYPE':
                return 'zset' if key.endswith('retry-scheduled') else 'list'
            if command == 'PTTL':
                return -1
            if command in ('LLEN', 'ZCARD'):
                return self.queues.get(key, 0)
            raise AssertionError('content reads and key enumeration are prohibited')
        if argv == ('block-ingress',):
            host.block_ingress()
            return True
        if argv == ('open-ingress',):
            host.calls.append(('open-ingress', None))
            host.data['ingress_blocked'], self.partial_ingress = False, False
            return True
        if argv[:3] == ('docker', 'update', '--restart=no'):
            host.disable_restart(argv[3])
            return True
        if argv[:3] == ('docker', 'update', '--restart=always'):
            role = host._role(argv[3])
            host.calls.append(('restart-always', role))
            host.data['services'][role]['restart_policy'] = 'always'
            return True
        if argv[:3] == ('docker', 'kill', '--signal=TERM'):
            host.signal_term(argv[3])
            return True
        if argv[:2] == ('docker', 'wait'):
            host.wait_stopped(argv[2], timeout)
            return host.data['services'][host._role(argv[2])]['exit_code']
        if argv[:2] == ('docker', 'start'):
            role = host._role(argv[2])
            host.calls.append(('start', role))
            host.data['services'][role].update(running=True, exit_code=None, restart_count=0,
                                               started='resumed-' + role)
            if self.on_start:
                self.on_start(role)
            if self.crash_after_start == role:
                self.crash_after_start = None
                raise KeyboardInterrupt()
            return True
        raise AssertionError('unapproved observed command')


def observed_transport(driver, **overrides):
    from first_transition_host_transport import ObservedHostTransport
    options = dict(legacy_project='synthetic-legacy', network_id=NETWORK,
                   service_ids={role: driver.host.data['services'][role]['id'] for role in ROLES},
                   support_ids={role: state['id'] for role, state in driver.support.items()})
    options.update(overrides)
    return ObservedHostTransport(driver, **options)


def observed_contract(driver, journal):
    from first_transition_host_contract import ObservedHostContract
    return ObservedHostContract(observed_transport(driver), journal)


def effects(driver):
    return [command for command, _ in driver.commands if command[0] not in ('inspect-host', 'redis-meta')]


def test_host_command_encodes_resume_operations_and_refuses_others():
    from first_transition_host_transport import host_command
    identifier = '1' * 64
    assert host_command('restart-always', identifier) == ('docker', 'update', '--restart=always', identifier)
    assert host_command('start', identifier) == ('docker', 'start', identifier)
    for operation in ('restart', 'rm', 'stop'):
        with pytest.raises(Refused, match='transport-operation'):
            host_command(operation, identifier)


@pytest.mark.parametrize('override, code', [
    (dict(legacy_project='bad project'), 'transport-project'),
    (dict(network_id='X' * 64), 'transport-network'),
    (dict(service_ids={role: '1' * 64 for role in ROLES}), 'transport-identities'),
    (dict(service_ids={'backend': '1' * 64}), 'transport-identities'),
    (dict(support_ids={'redis': '5' * 64, 'evolution-postgres': '6' * 64, 'evolution-api': '1' * 64}),
     'transport-support-identities'),
    (dict(support_ids={'redis': '5' * 64}), 'transport-support-identities'),
])
def test_observed_transport_validates_scope_before_any_call(override, code):
    driver = ObservedDriver()
    with pytest.raises(Refused, match=code):
        observed_transport(driver, **override)
    driver.mode = 'local-simulation'
    with pytest.raises(Refused, match='transport-observed-required'):
        observed_transport(driver)
    assert driver.commands == []


def test_observed_transport_snapshot_is_sanitized_metadata():
    driver = ObservedDriver()
    data = observed_transport(driver).snapshot()
    assert set(data) == {'mode', 'scope_digest', 'ingress_blocked', 'ingress_open', 'support_digest',
                         'unknown_writers', 'queue_digest', 'queue_counts', 'services'}
    assert data['mode'] == 'observed-host' and data['queue_counts']['pastorai:webhooks'] == 3
    assert {command for command, _ in driver.commands} <= {('inspect-host',)} | {
        ('redis-meta', c, k) for c in ('TYPE', 'PTTL', 'LLEN', 'ZCARD') for k in data['queue_counts']}
    assert effects(driver) == []


@pytest.mark.parametrize('change', [
    lambda raw: raw.pop('ingress_open'), lambda raw: raw.update(ingress_open=None),
    lambda raw: raw.update(ingress_blocked=True, ingress_open=True),
])
def test_observed_transport_never_derives_ingress_open_from_not_blocked(change):
    driver = ObservedDriver()
    original = driver.request
    def request(argv, *, timeout):
        raw = original(argv, timeout=timeout)
        if argv == ('inspect-host',):
            change(raw)
        return raw
    driver.request = request
    with pytest.raises(Refused, match='^transport-snapshot$'):
        observed_transport(driver).snapshot()


def _support(driver, role, **changes):
    driver.support[role].update(changes)


@pytest.mark.parametrize('mutation, code', [
    (lambda d: d.support.pop('redis'), 'transport-support-scope'),
    (lambda d: d.support['redis'].pop('health'), 'transport-support-shape'),
    (lambda d: _support(d, 'redis', id='8' * 64), 'transport-support-identity-changed'),
    (lambda d: _support(d, 'redis', image='redis:latest'), 'transport-support-image'),
    (lambda d: _support(d, 'evolution-api', compose_project='other'), 'transport-support-compose'),
    (lambda d: _support(d, 'evolution-postgres', running=False), 'transport-support-not-running'),
    (lambda d: _support(d, 'redis', restart_policy='no'), 'transport-support-not-running'),
    (lambda d: _support(d, 'redis', health=None), 'transport-support-unhealthy'),
    (lambda d: _support(d, 'evolution-api', health='unhealthy'), 'transport-support-unhealthy'),
    (lambda d: _support(d, 'redis', networks_digest='bad'), 'transport-support-network'),
    (lambda d: d.host.data['services']['backend'].update(id='8' * 64), 'transport-identity-changed'),
    (lambda d: d.host.data['services']['cron-worker'].update(compose_project='other'), 'transport-compose'),
    (lambda d: d.host.data.update(unknown_writers=-1), 'transport-snapshot'),
])
def test_observed_transport_refuses_bad_support_or_scope(mutation, code):
    driver = ObservedDriver()
    transport = observed_transport(driver)
    mutation(driver)
    with pytest.raises(Refused, match=code):
        transport.snapshot()


def test_observed_transport_binds_network_and_support_digest():
    driver = ObservedDriver()
    transport = observed_transport(driver)
    first = transport.snapshot()['support_digest']
    _support(driver, 'evolution-api', health='healthy')
    with pytest.raises(Refused, match='transport-support-changed'):
        transport.snapshot()
    _support(driver, 'evolution-api', health=None)
    assert transport.snapshot()['support_digest'] == first
    with pytest.raises(Refused, match='transport-network-mismatch'):
        observed_transport(driver, network_id='8' * 64).snapshot()


@pytest.mark.parametrize('method', ['disable_restart', 'enable_restart', 'signal_term', 'wait_stopped',
                                    'start_service'])
def test_observed_transport_refuses_arbitrary_targets_and_replaced_identity(method):
    driver = ObservedDriver()
    transport = observed_transport(driver)
    args = {'disable_restart': (lambda _final: None,), 'signal_term': (lambda _final: None,),
            'wait_stopped': (30,), 'enable_restart': (lambda _final: None,),
            'start_service': (lambda _final: None,)}.get(method, ())
    with pytest.raises(Refused, match='transport-target'):
        getattr(transport, method)('other; shell-command', *args)
    with pytest.raises(Refused, match='transport-target'):
        getattr(transport, method)(driver.support['redis']['id'], *args)
    identifier = driver.host.data['services']['backend']['id']
    driver.host.data['services']['backend']['id'] = 'f' * 64
    with pytest.raises(Refused, match='transport-identity-changed'):
        getattr(transport, method)(identifier, *args)
    assert effects(driver) == []


def test_observed_transport_sanitizes_errors_and_bounds_wait():
    driver = ObservedDriver()
    transport = observed_transport(driver)
    with pytest.raises(Refused, match='transport-wait-bound'):
        transport.wait_stopped('1' * 64, 31)
    def fail(*_args, **_kwargs):
        raise Refused('synthetic-private-payload')
    driver.request = fail
    with pytest.raises(Refused, match='^observed-transport-failed$'):
        transport.snapshot()
    def timeout(*_args, **_kwargs):
        raise TimeoutError('synthetic-private-timeout-details')
    driver.request = timeout
    with pytest.raises(TimeoutError, match='^observed-transport-timeout$'):
        transport.block_ingress(lambda _final: None)
    driver.mode = 'remote'
    with pytest.raises(Refused, match='transport-observed-required'):
        transport.snapshot()


def test_observed_containment_binds_settled_queue_and_is_idempotent(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', lambda *_a, **_k: pytest.fail('no process transport'))
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        receipt = contract.contain()
        assert receipt['mode'] == 'observed-host' and receipt['host_verified'] is False
        assert receipt['evidence'] == 'driver-reported' and receipt['quiescence_proven'] is False
        assert receipt['stopped_roles'] == ROLES
        assert journal.last('observed-host-init')['host_verified'] is False
        assert journal.last('observed-host-contained')['host_verified'] is False
        expected = [('block-ingress',)]
        for role in ROLES:
            identifier = driver.host.data['services'][role]['id']
            expected.extend([('docker', 'update', '--restart=no', identifier),
                             ('docker', 'kill', '--signal=TERM', identifier), ('docker', 'wait', identifier)])
        assert effects(driver) == expected
        settled = journal.last('observed-host-settled')
        assert settled['queue_digest'] == receipt['queue_digest']
        assert settled['queue_counts']['pastorai:webhooks'] == 3
        assert journal.last('observed-host-init')['initial_started'] == dict.fromkeys(ROLES, 'synthetic-start')
        assert journal.last('observed-host-init')['initial_restarts'] == dict.fromkeys(ROLES, 0)
        assert observed_contract(driver, journal).contain() == receipt
        assert effects(driver) == expected


def test_observed_containment_refuses_queue_drift(tmp_path):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        observed_contract(driver, journal).contain()
        driver.queues['pastorai:webhooks'] = 4
        contract = observed_contract(driver, journal)
        with pytest.raises(Refused, match='observed-host-queue-drift'):
            contract.assert_contained()
        with pytest.raises(Refused, match='observed-host-queue-drift'):
            contract.resume_legacy(contract.resume_token())
        assert not [c for c in effects(driver) if c[:2] == ('docker', 'start') or '--restart=always' in c]


def test_observed_containment_refuses_unknown_writer_or_external_restart(tmp_path):
    driver = ObservedDriver()
    driver.host.data['unknown_writers'] = 1
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused, match='observed-host-unknown-writer'):
            observed_contract(driver, journal).contain()
        assert effects(driver) == []
        driver.host.data['unknown_writers'] = 0
        observed_contract(driver, journal).contain()
        driver.host.data['services']['backend'].update(running=False, started='external-restart')
        with pytest.raises(Refused, match='observed-host-identity-or-support-changed'):
            observed_contract(driver, journal).assert_contained()


@pytest.mark.parametrize('mutation', [
    lambda d: d.support.pop('evolution-api'),
    lambda d: _support(d, 'redis', health='starting'),
    lambda d: _support(d, 'evolution-postgres', running=False),
])
def test_observed_containment_refuses_missing_or_unhealthy_support_without_effects(tmp_path, mutation):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        mutation(driver)
        with pytest.raises(Refused, match='observed-host-effect-failed'):
            contract.contain()
        assert effects(driver) == []
        assert not journal.last('observed-host-init')


def test_pre_ddl_resume_restarts_in_order_then_reopens_ingress(tmp_path):
    from first_transition_host_contract import START_ORDER
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        contained = len(effects(driver))
        token = contract.resume_token()
        assert token == 'RESUME:' + journal.last('observed-host-init')['fingerprint']
        for confirmation in (None, 'wrong', token.lower()):
            with pytest.raises(Refused, match='observed-host-resume-confirmation'):
                contract.resume_legacy(confirmation, token)
        for expected in ('', 'RESUME:' + 'f' * 64):
            with pytest.raises(Refused, match='observed-host-resume-confirmation'):
                contract.resume_legacy(expected, expected)
        assert len(effects(driver)) == contained
        result = contract.resume_legacy(token, token)
        assert result == dict(mode='observed-host', status='legacy-resumed', resumed_roles=START_ORDER,
                              ingress_blocked=False, evidence='driver-reported', host_verified=False)
        expected = []
        for role in START_ORDER:
            identifier = driver.host.data['services'][role]['id']
            expected.extend([('docker', 'start', identifier), ('docker', 'update', '--restart=always', identifier)])
        assert effects(driver)[contained:] == expected + [('open-ingress',)]
        assert all(s['running'] and s['restart_policy'] == 'always' for s in driver.host.data['services'].values())
        assert driver.host.data['ingress_blocked'] is False
        assert journal.last('observed-host-resumed')
        count = len(effects(driver))
        assert observed_contract(driver, journal).resume_legacy(None, token) == result
        assert len(effects(driver)) == count
        with pytest.raises(Refused, match='observed-host-resume-started'):
            observed_contract(driver, journal).contain()


def test_resume_replay_after_crash_never_restarts_a_resumed_role(tmp_path):
    driver = ObservedDriver()
    driver.crash_after_start = 'queue-worker'
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        with pytest.raises(KeyboardInterrupt):
            contract.resume_legacy(contract.resume_token())
        assert driver.host.data['ingress_blocked'] is True
    with Journal(tmp_path / 'journal') as journal:
        observed_contract(driver, journal).resume_legacy(None)
        assert [c for c in driver.host.calls if c[0] == 'start'] == [
            ('start', 'backend'), ('start', 'queue-worker'), ('start', 'broadcast-worker'), ('start', 'cron-worker')]
        assert driver.host.calls[-1] == ('open-ingress', None)
        assert journal.last('observed-host-done', 'legacy-resume:queue-worker')['started'] == 'resumed-queue-worker'


def test_resume_replay_refuses_when_resumed_role_was_restarted(tmp_path):
    driver = ObservedDriver()
    driver.crash_after_start = 'queue-worker'
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        with pytest.raises(KeyboardInterrupt):
            contract.resume_legacy(contract.resume_token())
        driver.host.data['services']['backend'].update(started='restarted-again', restart_count=1)
        with pytest.raises(Refused, match='observed-host-resumed-state-changed'):
            observed_contract(driver, journal).resume_legacy(None)
        assert driver.host.data['ingress_blocked'] is True


@pytest.mark.parametrize('marker', ['adapter-ddl-marker', 'ddl-marker'])
def test_post_ddl_resume_is_refused_before_any_call(tmp_path, marker):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        observed_contract(driver, journal).contain()
        journal.append(marker, irrevocable=True)
        driver.commands.clear()
        with pytest.raises(Refused, match='^post-ddl-resume-forbidden$'):
            observed_contract(driver, journal).resume_legacy('RESUME:' + 'f' * 64)
        assert driver.commands == []
        assert all(s['restart_policy'] == 'no' and not s['running'] for s in driver.host.data['services'].values())


def test_resume_requires_observed_containment(tmp_path):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused, match='observed-host-not-contained'):
            observed_contract(driver, journal).resume_legacy('RESUME:' + 'f' * 64)
        assert driver.commands == []


class UntouchableDatabase:
    identity = 'synthetic-untouched'

    def __getattr__(self, name):
        pytest.fail('local database touched: ' + name)


def test_observed_evidence_is_only_an_envelope_and_never_drives_local_transition(tmp_path):
    import dataclasses
    from first_transition_adapter import LocalEvidence, LocalTransition
    LocalEvidence.synthetic('a' * 64, 'b' * 64).validate('a' * 64, 'b' * 64)
    for host_digest in (None, 'X' * 64):
        with pytest.raises(Refused, match='local-evidence-mismatch'):
            LocalEvidence.observed('a' * 64, 'b' * 64, host_digest=host_digest).validate('a' * 64, 'b' * 64)
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        fingerprint = contract.contain()['fingerprint']
        evidence = LocalEvidence.observed('a' * 64, 'b' * 64, host_digest=fingerprint)
        assert evidence.kind == 'observed-host'
        evidence.validate('a' * 64, 'b' * 64)  # envelope shape only, no authorization
        with pytest.raises(Refused, match='local-evidence-mismatch'):
            dataclasses.replace(evidence, kind='production').validate('a' * 64, 'b' * 64)
        before = list(journal.events)
        with pytest.raises(Refused, match='local-transition-simulated-host-required'):
            LocalTransition(None, UntouchableDatabase(), journal, host=contract)
        with pytest.raises(Refused, match='local-transition-observed-journal'):
            LocalTransition(None, UntouchableDatabase(), journal)
        assert journal.events == before
        assert resume_effects(driver) == []
    with Journal(tmp_path / 'clean') as clean:
        with pytest.raises(Refused, match='local-transition-simulated-evidence-required'):
            LocalTransition(None, UntouchableDatabase(), clean).run(evidence)
        synthetic = LocalEvidence.synthetic('a' * 64, 'b' * 64, host_digest=fingerprint)
        with pytest.raises(Refused, match='local-host-evidence-unbound'):
            LocalTransition(None, UntouchableDatabase(), clean).run(synthetic)
        assert clean.events == []

    port = FakeHost()
    with Journal(tmp_path / 'local') as journal:
        local = LocalHostContract(port, journal)
        fingerprint = local.contain()['fingerprint']
        before = list(journal.events)
        observed = LocalEvidence.observed('a' * 64, 'b' * 64, host_digest=fingerprint)
        with pytest.raises(Refused, match='local-transition-simulated-evidence-required'):
            LocalTransition(None, UntouchableDatabase(), journal, host=local).run(observed)
        LocalTransition(None, UntouchableDatabase(), journal, host=local)._check_host(
            LocalEvidence.synthetic('a' * 64, 'b' * 64, host_digest=fingerprint))
        assert journal.events == before
        with pytest.raises(Refused, match='local-host-journal-mismatch'):
            LocalTransition(None, UntouchableDatabase(), None, host=LocalHostContract(port, None))


def test_local_transition_refuses_an_observed_receipt_from_a_local_contract(tmp_path, monkeypatch):
    from first_transition_adapter import LocalEvidence, LocalTransition
    with Journal(tmp_path / 'journal') as journal:
        local = LocalHostContract(FakeHost(), journal)
        receipt = local.contain()
        monkeypatch.setattr(local, 'assert_contained', lambda: dict(receipt, mode='observed-host'))
        evidence = LocalEvidence.synthetic('a' * 64, 'b' * 64, host_digest=receipt['fingerprint'])
        before = list(journal.events)
        with pytest.raises(Refused, match='local-host-evidence-mismatch'):
            LocalTransition(None, UntouchableDatabase(), journal, host=local).run(evidence)
        assert journal.events == before


def resume_effects(driver):
    return [c for c in effects(driver) if c[:2] == ('docker', 'start') or '--restart=always' in c
            or c == ('open-ingress',)]


@pytest.mark.parametrize('mutation', [
    lambda s: s.update(debug_env='synthetic-private'),
    lambda s: s.pop('exit_code'),
])
def test_observed_transport_refuses_and_never_leaks_undeclared_service_fields(mutation):
    from first_transition_host_transport import SERVICE_FIELDS
    driver = ObservedDriver()
    transport = observed_transport(driver)
    assert all(set(state) == SERVICE_FIELDS for state in transport.snapshot()['services'].values())
    mutation(driver.host.data['services']['queue-worker'])
    with pytest.raises(Refused, match='transport-service-shape'):
        transport.snapshot()


def test_restart_count_drift_before_resume_intent_is_refused(tmp_path):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        token = contract.resume_token()
        driver.host.data['services']['cron-worker']['restart_count'] = 1
        with pytest.raises(Refused, match='observed-host-identity-or-support-changed'):
            contract.assert_contained()
        with pytest.raises(Refused, match='observed-host-identity-or-support-changed'):
            contract.resume_legacy(token)
        assert journal.last('observed-host-intent', 'legacy-resume') is None
        assert resume_effects(driver) == []


def test_crash_between_start_and_restart_always_replays_without_second_start(tmp_path):
    driver = ObservedDriver()
    driver.crash_after_start = 'backend'
    identifier = driver.host.data['services']['backend']['id']
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        with pytest.raises(KeyboardInterrupt):
            contract.resume_legacy(contract.resume_token())
        backend = driver.host.data['services']['backend']
        assert backend['running'] is True and backend['restart_policy'] == 'no'
        assert journal.last('observed-host-done', 'legacy-resume:backend') is None
        before = len(effects(driver))
    with Journal(tmp_path / 'journal') as journal:
        observed_contract(driver, journal).resume_legacy(None)
        replay = effects(driver)[before:]
        assert replay[0] == ('docker', 'update', '--restart=always', identifier)
        assert ('docker', 'start', identifier) not in replay
        assert driver.host.calls.count(('start', 'backend')) == 1
        assert journal.last('observed-host-done', 'legacy-resume:backend')['started'] == 'resumed-backend'


def test_resumed_role_restart_while_later_role_starts_is_refused_before_ingress(tmp_path):
    driver = ObservedDriver()
    def restart_backend(role):
        if role == 'queue-worker':
            driver.host.data['services']['backend'].update(started='restarted-again', restart_count=1)
    driver.on_start = restart_backend
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        with pytest.raises(Refused, match='observed-host-resumed-state-changed'):
            contract.resume_legacy(contract.resume_token())
        assert driver.host.data['ingress_blocked'] is True
        assert ('open-ingress',) not in effects(driver)
        assert journal.last('observed-host-done', 'legacy-resume:queue-worker') is None
        assert ('start', 'broadcast-worker') not in driver.host.calls


def test_ingress_reopened_externally_during_partial_resume_is_refused(tmp_path):
    driver = ObservedDriver()
    driver.crash_after_start = 'queue-worker'
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        with pytest.raises(KeyboardInterrupt):
            contract.resume_legacy(contract.resume_token())
        driver.host.data['ingress_blocked'] = False
        before = len(effects(driver))
        with pytest.raises(Refused, match='observed-host-ingress-open'):
            observed_contract(driver, journal).resume_legacy(None)
        assert effects(driver)[before:] == []
        assert ('start', 'broadcast-worker') not in driver.host.calls


@pytest.mark.parametrize('mutation, code', [
    (lambda d: d.host.data.update(ingress_blocked=True), 'observed-host-ingress-still-blocked'),
    (lambda d: d.host.data['services']['cron-worker'].update(started='restarted-again', restart_count=1),
     'observed-host-resumed-state-changed'),
    (lambda d: d.host.data['services']['backend'].update(running=False, exit_code=1),
     'observed-host-resumed-state-changed'),
])
def test_terminal_resume_replay_reproves_host_instead_of_returning_stale_receipt(tmp_path, mutation, code):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        contract.resume_legacy(contract.resume_token())
        assert journal.last('observed-host-resumed')
        mutation(driver)
        before = len(effects(driver))
        with pytest.raises(Refused, match=code):
            observed_contract(driver, journal).resume_legacy(None)
        assert effects(driver)[before:] == []


def test_resume_intent_permanently_revokes_containment_evidence(tmp_path, monkeypatch):
    from first_transition_adapter import LocalTransition
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        append = journal.append
        def crash(kind, **fields):
            event = append(kind, **fields)
            if kind == 'observed-host-intent' and fields.get('step') == 'legacy-resume':
                raise KeyboardInterrupt()
            return event
        monkeypatch.setattr(journal, 'append', crash)
        with pytest.raises(KeyboardInterrupt):
            contract.resume_legacy(contract.resume_token())
    assert resume_effects(driver) == []
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        with pytest.raises(Refused, match='observed-host-resume-started'):
            contract.assert_contained()
        with pytest.raises(Refused, match='observed-host-resume-started'):
            contract.contain()
        with pytest.raises(Refused, match='local-transition-simulated-host-required'):
            LocalTransition(None, UntouchableDatabase(), journal, host=contract)
        assert journal.last('adapter-ddl-marker') is None
        assert journal.last('adapter-init') is None
        assert contract.resume_legacy(None)['status'] == 'legacy-resumed'


def test_local_transition_refuses_host_bound_to_another_journal(tmp_path):
    from first_transition_adapter import LocalTransition
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal, Journal(tmp_path / 'other') as other:
        contract = observed_contract(driver, journal)
        with pytest.raises(Refused, match='local-host-journal-mismatch'):
            LocalTransition(None, None, other, host=contract)
        with pytest.raises(Refused, match='local-host-journal-mismatch'):
            LocalTransition(None, None, journal, host=object())
        assert driver.commands == []


def test_queue_drift_before_first_start_requires_explicit_acceptance(tmp_path):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        settled = journal.last('observed-host-settled')['queue_digest']
        driver.queues['pastorai:webhooks'] = 4
        token = contract.resume_token()
        with pytest.raises(Refused, match='observed-host-queue-drift'):
            contract.resume_legacy(token)
        assert journal.last('observed-host-intent', 'legacy-resume') is None
        assert journal.last('observed-host-queue-drift-accepted') is None
        assert resume_effects(driver) == []
        assert contract.resume_legacy(token, allow_queue_drift=True)['status'] == 'legacy-resumed'
        accepted = journal.find('observed-host-queue-drift-accepted')
        assert len(accepted) == 1 and accepted[0]['settled_digest'] == settled
        assert accepted[0]['current_digest'] != settled
        assert accepted[0]['seq'] < journal.last('observed-host-intent', 'legacy-resume')['seq']
        contract.resume_legacy(None)
        assert len(journal.find('observed-host-queue-drift-accepted')) == 1


def no_progress_after(driver, journal, role):
    from first_transition_host_contract import START_ORDER
    identifier = driver.host.data['services'][role]['id']
    later = START_ORDER[START_ORDER.index(role) + 1:]
    assert ('docker', 'update', '--restart=always', identifier) not in effects(driver)
    assert all(('start', other) not in driver.host.calls for other in later)
    assert ('open-ingress',) not in effects(driver)
    assert journal.last('observed-host-done', 'legacy-resume:' + role) is None
    assert journal.last('observed-host-intent', 'open-ingress') is None


@pytest.mark.parametrize('role', ['backend', 'cron-worker'])
def test_ingress_reopened_inside_start_service_is_refused_before_further_effects(tmp_path, role):
    driver = ObservedDriver()
    def reopen(started):
        if started == role:
            driver.host.data['ingress_blocked'] = False
    driver.on_start = reopen
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        with pytest.raises(Refused, match='^observed-host-ingress-open$'):
            contract.resume_legacy(contract.resume_token())
        no_progress_after(driver, journal, role)
        assert journal.last('observed-host-resumed') is None
        before = len(effects(driver))
        with pytest.raises(Refused, match='^observed-host-ingress-open$'):
            observed_contract(driver, journal).resume_legacy(None)
        assert effects(driver)[before:] == []


def test_ingress_reopened_before_its_authorization_is_refused(tmp_path, monkeypatch):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        append = journal.append
        def reopen(kind, **fields):
            event = append(kind, **fields)
            if kind == 'observed-host-done' and fields.get('step') == 'legacy-resume:cron-worker':
                driver.host.data['ingress_blocked'] = False
            return event
        monkeypatch.setattr(journal, 'append', reopen)
        with pytest.raises(Refused, match='^observed-host-ingress-open$'):
            contract.resume_legacy(contract.resume_token())
        assert journal.last('observed-host-intent', 'open-ingress') is None
        assert ('open-ingress',) not in effects(driver)
        assert journal.last('observed-host-resumed') is None


def test_queue_drift_after_first_start_intent_is_refused_before_the_effect(tmp_path, monkeypatch):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        token = contract.resume_token()
        append = journal.append
        def drift(kind, **fields):
            event = append(kind, **fields)
            if kind == 'observed-host-intent' and fields.get('step') == 'legacy-resume:backend':
                driver.queues['pastorai:webhooks'] = 4
            return event
        monkeypatch.setattr(journal, 'append', drift)
        with pytest.raises(Refused, match='^observed-host-queue-drift$'):
            contract.resume_legacy(token)
        assert journal.last('observed-host-intent', 'legacy-resume:backend') is not None
        assert resume_effects(driver) == []
        assert journal.last('observed-host-queue-drift-accepted') is None
        # Replay without any prior start still requires explicit, journaled acceptance.
        with pytest.raises(Refused, match='^observed-host-queue-drift$'):
            observed_contract(driver, journal).resume_legacy(None)
        assert resume_effects(driver) == []
        assert observed_contract(driver, journal).resume_legacy(None, allow_queue_drift=True)['status'] == \
            'legacy-resumed'
        accepted = journal.last('observed-host-queue-drift-accepted')
        first_start = journal.last('observed-host-done', 'legacy-resume:backend')
        assert accepted['current_digest'] != accepted['settled_digest']
        assert accepted['seq'] < first_start['seq']


def test_queue_drift_during_replay_without_prior_start_is_refused_before_the_effect(tmp_path, monkeypatch):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        append = journal.append
        def crash(kind, **fields):
            event = append(kind, **fields)
            if kind == 'observed-host-intent' and fields.get('step') == 'legacy-resume:backend':
                raise KeyboardInterrupt()
            return event
        monkeypatch.setattr(journal, 'append', crash)
        with pytest.raises(KeyboardInterrupt):
            contract.resume_legacy(contract.resume_token())
    assert resume_effects(driver) == []
    inspections = []
    def drift_after_entry():
        inspections.append(None)
        if len(inspections) == 2:  # after the entry snapshot, before the replayed start
            driver.queues['pastorai:webhooks'] = 4
    driver.on_inspect = drift_after_entry
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused, match='^observed-host-queue-drift$'):
            observed_contract(driver, journal).resume_legacy(None)
        assert len(inspections) >= 2
        assert resume_effects(driver) == []
        assert journal.last('observed-host-queue-drift-accepted') is None


@pytest.mark.parametrize('crash', [False, True])
def test_queue_change_after_an_actual_start_is_legitimate(tmp_path, crash):
    driver = ObservedDriver()
    def consume(role):
        if role == 'backend':
            driver.queues['pastorai:webhooks'] = 0
    driver.on_start = consume
    if crash:
        driver.crash_after_start = 'backend'
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        token = contract.resume_token()
        if crash:
            with pytest.raises(KeyboardInterrupt):
                contract.resume_legacy(token)
            result = observed_contract(driver, journal).resume_legacy(None)
        else:
            result = contract.resume_legacy(token)
        assert result['status'] == 'legacy-resumed'
        assert journal.last('observed-host-queue-drift-accepted') is None
        assert driver.host.calls.count(('start', 'backend')) == 1


@pytest.mark.parametrize('role', ['backend', 'cron-worker'])
@pytest.mark.parametrize('marker', ['adapter-ddl-marker', 'ddl-marker'])
def test_ddl_marker_appearing_during_resume_blocks_every_later_effect(tmp_path, role, marker):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        def ddl(started):
            if started == role:
                journal.append(marker, irrevocable=True)
        driver.on_start = ddl
        contract = observed_contract(driver, journal)
        contract.contain()
        with pytest.raises(Refused, match='^post-ddl-resume-forbidden$'):
            contract.resume_legacy(contract.resume_token())
        no_progress_after(driver, journal, role)
        driver.commands.clear()
        with pytest.raises(Refused, match='^post-ddl-resume-forbidden$'):
            observed_contract(driver, journal).resume_legacy(None)
        assert driver.commands == []


def _abnormal_exit(driver, role, code):
    term = driver.host.signal_term
    def signal(identifier):
        term(identifier)
        if driver.host._role(identifier) == role:
            driver.host.data['services'][role]['exit_code'] = code
    driver.host.signal_term = signal


@pytest.mark.parametrize('failure', ['exit-143-backend', 'exit-143-broadcast', 'wait-timeout'])
def test_partial_containment_is_refused_fail_closed_and_resume_has_no_effect(tmp_path, failure):
    driver = ObservedDriver()
    if failure == 'exit-143-backend':
        _abnormal_exit(driver, 'backend', 143)
    elif failure == 'exit-143-broadcast':
        _abnormal_exit(driver, 'broadcast-worker', 143)
    else:
        driver.host.timeout = True
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        with pytest.raises(Refused):
            contract.contain()
        assert journal.last('observed-host-contained') is None
        with pytest.raises(Refused):  # replay never re-signals, escalates or recovers
            observed_contract(driver, journal).contain()
        assert all(driver.host.calls.count(('term', role)) <= 1 for role in ROLES)
        token = 'RESUME:' + journal.last('observed-host-init')['fingerprint']
        driver.commands.clear()
        with pytest.raises(Refused, match='^observed-host-not-contained$'):
            observed_contract(driver, journal).resume_legacy(token)
        assert driver.commands == []
        assert resume_effects(driver) == []
        assert journal.last('observed-host-intent', 'legacy-resume') is None
        assert driver.host.data['ingress_blocked'] is True


def inside_final_observation(contract, driver, method, mutate, role=None):
    """Mutates the host during the transport's own snapshot inside an effect call."""
    transport = contract.port
    original = getattr(transport, method)
    def wrapped(*args):
        if role is None or args[0] == driver.host.data['services'][role]['id']:
            fired = []
            def once():
                if not fired:
                    fired.append(None)
                    mutate()
            driver.on_inspect = once
        try:
            return original(*args)
        finally:
            driver.on_inspect = None
    setattr(transport, method, wrapped)


def _restart_backend(driver):
    driver.host.data['services']['backend'].update(started='restarted-again', restart_count=1)


@pytest.mark.parametrize('role, change, code', [
    ('backend', 'ddl', 'post-ddl-resume-forbidden'),
    ('backend', 'ingress', 'observed-host-ingress-open'),
    ('backend', 'queue', 'observed-host-queue-drift'),
    ('cron-worker', 'ddl', 'post-ddl-resume-forbidden'),
    ('cron-worker', 'ingress', 'observed-host-ingress-open'),
    ('cron-worker', 'identity', 'observed-host-resumed-state-changed'),
])
def test_change_in_the_transport_final_observation_blocks_the_start(tmp_path, role, change, code):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        mutate = {'ddl': lambda: journal.append('adapter-ddl-marker', irrevocable=True),
                  'ingress': lambda: driver.host.data.update(ingress_blocked=False),
                  'queue': lambda: driver.queues.update({'pastorai:webhooks': 4}),
                  'identity': lambda: _restart_backend(driver)}[change]
        inside_final_observation(contract, driver, 'start_service', mutate, role)
        with pytest.raises(Refused, match='^' + code + '$'):
            contract.resume_legacy(contract.resume_token())
        assert ('start', role) not in driver.host.calls
        no_progress_after(driver, journal, role)
        assert journal.last('observed-host-queue-drift-accepted') is None
        if change == 'queue':
            # Replay stays crash-safe: only an explicit, journaled acceptance proceeds.
            assert resume_effects(driver) == []
            result = observed_contract(driver, journal).resume_legacy(None, allow_queue_drift=True)
            assert result['status'] == 'legacy-resumed'
            accepted = journal.last('observed-host-queue-drift-accepted')
            assert accepted['seq'] < journal.last('observed-host-done', 'legacy-resume:backend')['seq']
            assert driver.host.calls.count(('start', 'backend')) == 1


@pytest.mark.parametrize('change, code', [
    ('ddl', 'post-ddl-resume-forbidden'),
    ('ingress', 'observed-host-ingress-open'),
])
def test_change_in_the_transport_final_observation_blocks_restart_always(tmp_path, change, code):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        mutate = {'ddl': lambda: journal.append('ddl-marker', irrevocable=True),
                  'ingress': lambda: driver.host.data.update(ingress_blocked=False)}[change]
        inside_final_observation(contract, driver, 'enable_restart', mutate, 'queue-worker')
        with pytest.raises(Refused, match='^' + code + '$'):
            contract.resume_legacy(contract.resume_token())
        assert driver.host.calls.count(('start', 'queue-worker')) == 1
        no_progress_after(driver, journal, 'queue-worker')


@pytest.mark.parametrize('change, code', [
    ('ddl', 'post-ddl-resume-forbidden'),
    ('identity', 'observed-host-resumed-state-changed'),
])
def test_change_in_the_transport_final_observation_blocks_open_ingress(tmp_path, change, code):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        mutate = {'ddl': lambda: journal.append('adapter-ddl-marker', irrevocable=True),
                  'identity': lambda: _restart_backend(driver)}[change]
        inside_final_observation(contract, driver, 'open_ingress', mutate)
        with pytest.raises(Refused, match='^' + code + '$'):
            contract.resume_legacy(contract.resume_token())
        assert ('open-ingress',) not in effects(driver)
        assert driver.host.data['ingress_blocked'] is True
        assert journal.last('observed-host-done', 'open-ingress') is None
        assert journal.last('observed-host-resumed') is None


def test_bare_observed_transport_refuses_resume_effects_without_a_guard():
    driver = ObservedDriver()
    transport = observed_transport(driver)
    identifier = driver.host.data['services']['backend']['id']
    for call in (lambda: transport.start_service(identifier), lambda: transport.enable_restart(identifier),
                 transport.open_ingress, lambda: transport.open_ingress('not-callable')):
        with pytest.raises(Refused, match='^transport-guard-required$'):
            call()
    assert driver.commands == []
    seen = []
    def refuse(final):
        seen.append(final)
        raise Refused('synthetic-guard-refusal')
    with pytest.raises(Refused, match='^synthetic-guard-refusal$'):
        transport.start_service(identifier, refuse)
    assert seen and seen[0]['mode'] == 'observed-host'
    assert effects(driver) == []


def test_port_that_skips_the_guard_is_refused_before_further_effects(tmp_path, monkeypatch):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        monkeypatch.setattr(contract.port, '_guarded', lambda guard, identifier=None: None)
        with pytest.raises(Refused, match='^observed-host-guard-skipped$'):
            contract.resume_legacy(contract.resume_token())
        no_progress_after(driver, journal, 'backend')


def test_running_role_without_a_fresh_start_never_counts_as_the_first_start(tmp_path, monkeypatch):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        append = journal.append
        def crash(kind, **fields):
            event = append(kind, **fields)
            if kind == 'observed-host-intent' and fields.get('step') == 'legacy-resume:backend':
                raise KeyboardInterrupt()
            return event
        monkeypatch.setattr(journal, 'append', crash)
        with pytest.raises(KeyboardInterrupt):
            contract.resume_legacy(contract.resume_token())
    # Inconsistent driver: running, but 'started' unchanged and no intent for the role.
    driver.host.data['services']['cron-worker']['running'] = True
    driver.queues['pastorai:webhooks'] = 4  # would bypass the queue gate if it counted as a start
    with Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused, match='^observed-host-resume-not-fresh$'):
            observed_contract(driver, journal).resume_legacy(None)
        assert resume_effects(driver) == []
        assert journal.last('observed-host-queue-drift-accepted') is None
        # Same for the intended role itself: an unchanged 'started' is no fresh start.
        driver.host.data['services']['cron-worker']['running'] = False
        driver.host.data['services']['backend']['running'] = True
        with pytest.raises(Refused, match='^observed-host-resume-not-fresh$'):
            observed_contract(driver, journal).resume_legacy(None, allow_queue_drift=True)
        assert resume_effects(driver) == []
        assert journal.last('observed-host-queue-drift-accepted') is None


def test_local_transition_refuses_a_journal_holding_observed_host_events(tmp_path):
    from first_transition_adapter import LocalEvidence, LocalTransition
    evidence = LocalEvidence.synthetic('a' * 64, 'b' * 64)
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        early = LocalTransition(None, UntouchableDatabase(), journal)  # built before the mixture
        observed_contract(driver, journal).contain()
        before = list(journal.events)
        for _attempt in range(2):  # refused on every run, not only at construction
            with pytest.raises(Refused, match='^local-transition-observed-journal$'):
                early.run(evidence, retry=True)
        with pytest.raises(Refused, match='^local-transition-observed-journal$'):
            LocalTransition(None, UntouchableDatabase(), journal)
        with pytest.raises(Refused, match='^local-transition-observed-journal$'):
            LocalTransition(None, UntouchableDatabase(), journal, host=LocalHostContract(FakeHost(), journal))
        assert journal.events == before
    with Journal(tmp_path / 'journal') as journal:  # reopened journal
        with pytest.raises(Refused, match='^local-transition-observed-journal$'):
            LocalTransition(None, UntouchableDatabase(), journal)
        assert len(journal.events) == len(before)
        assert journal.last('adapter-init') is None and journal.last('adapter-ddl-marker') is None


@pytest.mark.parametrize('kind', ['adapter-init', 'adapter-database-verified', 'local-host-init',
                                  'local-host-contained'])
@pytest.mark.parametrize('contained_first', [False, True])
def test_observed_contract_refuses_a_journal_holding_local_adapter_events(tmp_path, kind, contained_first):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        early = observed_contract(driver, journal)  # built before the mixture
        if contained_first:
            early.contain()
        journal.append(kind, synthetic=True)
        before = list(journal.events)
        driver.commands.clear()
        for call in (early.contain, early.assert_contained,
                     lambda: early.resume_legacy('RESUME:' + journal.last('observed-host-init')['fingerprint']
                                                 if contained_first else None)):
            with pytest.raises(Refused, match='^observed-host-journal-mixed$'):
                call()
        assert driver.commands == [] and journal.events == before
    with Journal(tmp_path / 'journal') as journal:  # reopened journal
        contract = observed_contract(driver, journal)
        for call in (contract.contain, contract.assert_contained, lambda: contract.resume_legacy(None)):
            with pytest.raises(Refused, match='^observed-host-journal-mixed$'):
                call()
        journal.append('adapter-ddl-marker', irrevocable=True)
        with pytest.raises(Refused, match='^post-ddl-resume-forbidden$'):  # keeps priority
            contract.resume_legacy(None)
        assert driver.commands == []


@pytest.mark.parametrize('method', ['start_service', 'enable_restart'])
@pytest.mark.parametrize('mutation, code', [
    (dict(restart_policy='always'), 'observed-host-not-cleanly-contained'),
    (dict(exit_code=143), 'observed-host-not-cleanly-contained'),
    (dict(running=True), 'observed-host-resume-not-fresh'),
])
def test_final_guard_revalidates_every_role_before_each_effect(tmp_path, method, mutation, code):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        contract.contain()
        inside_final_observation(contract, driver, method,
            lambda: driver.host.data['services']['cron-worker'].update(mutation), 'backend')
        with pytest.raises(Refused, match='^' + code + '$'):
            contract.resume_legacy(contract.resume_token())
        if method == 'start_service':
            assert resume_effects(driver) == []
        else:
            assert driver.host.calls.count(('start', 'backend')) == 1
            assert ('restart-always', 'backend') not in driver.host.calls
        assert all(('start', role) not in driver.host.calls for role in ROLES if role != 'backend')
        assert ('open-ingress',) not in effects(driver)
        assert journal.last('observed-host-resumed') is None


def test_local_transition_requires_an_open_journal_even_without_a_host(tmp_path):
    from first_transition_adapter import LocalTransition
    for journal in (None, Journal(tmp_path / 'closed')):
        with pytest.raises(Refused, match='^local-transition-journal-required$'):
            LocalTransition(None, UntouchableDatabase(), journal)


@pytest.mark.parametrize('method', ['disable_restart', 'signal_term'])
@pytest.mark.parametrize('change', ['writer', 'gate'])
def test_containment_checks_its_final_transport_observation(tmp_path, method, change):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        def mutate():
            if change == 'writer':
                driver.host.data['unknown_writers'] = 1
            else:
                driver.host.data['services']['cron-worker']['gates_digest'] = 'f' * 64
        inside_final_observation(contract, driver, method, mutate, 'backend')
        with pytest.raises(Refused):
            contract.contain()
        effect = 'restart-no' if method == 'disable_restart' else 'term'
        assert (effect, 'backend') not in driver.host.calls
        assert journal.last('observed-host-contained') is None


@pytest.mark.parametrize('change', [dict(running=False, exit_code=143),
                                   dict(running=False, exit_code=0), dict(restart_policy='no')])
def test_containment_rejects_unintended_phase_change_in_another_role(tmp_path, change):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        inside_final_observation(contract, driver, 'disable_restart',
            lambda: driver.host.data['services']['cron-worker'].update(change), 'backend')
        with pytest.raises(Refused):
            contract.contain()
        assert ('restart-no', 'backend') not in driver.host.calls
        assert ('term', 'backend') not in driver.host.calls


def test_clean_but_unintended_stop_is_not_adopted_at_the_last_role(tmp_path, monkeypatch):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        contract = observed_contract(driver, journal)
        append = journal.append
        def external_stop(kind, **fields):
            result = append(kind, **fields)
            if kind == 'observed-host-done' and fields.get('step') == 'restart-no:queue-worker':
                driver.host.data['services']['queue-worker'].update(running=False, exit_code=0)
            return result
        monkeypatch.setattr(journal, 'append', external_stop)
        with pytest.raises(Refused):
            contract.contain()
        assert journal.last('observed-host-intent', 'term:queue-worker') is None
        assert journal.last('observed-host-done', 'term:queue-worker') is None
        assert journal.last('observed-host-contained') is None


def test_externally_stopped_host_after_init_is_not_adopted_on_replay(tmp_path, monkeypatch):
    driver = ObservedDriver()
    with Journal(tmp_path / 'journal') as journal:
        append = journal.append
        def crash(kind, **fields):
            result = append(kind, **fields)
            if kind == 'observed-host-init':
                raise KeyboardInterrupt()
            return result
        monkeypatch.setattr(journal, 'append', crash)
        with pytest.raises(KeyboardInterrupt):
            observed_contract(driver, journal).contain()
    driver.host.data['ingress_blocked'] = True
    for state in driver.host.data['services'].values():
        state.update(running=False, exit_code=0, restart_policy='no')
    with Journal(tmp_path / 'journal') as journal:
        before = list(journal.events)
        with pytest.raises(Refused):
            observed_contract(driver, journal).contain()
        assert journal.events == before
