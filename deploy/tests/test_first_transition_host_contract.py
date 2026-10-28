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
