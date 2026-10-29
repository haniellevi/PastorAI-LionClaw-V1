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
