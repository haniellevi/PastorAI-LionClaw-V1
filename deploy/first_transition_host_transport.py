"""Command encoding for caller-supplied host drivers; no process or network executor.

The mandatory driver supplies sanitized metadata, not raw Docker inspect/env.
Ingress remains a semantic operation: no guessed Nginx/Evolution command.
The simulated transport cannot certify a real host. The observed transport only
restarts the four pinned legacy identities; it provides no deploy operation.
It validates shape and binds identities, but every value is driver-reported:
it is no real executor, inventory or ingress implementation, and queue counts
prove neither contents nor quiescence. A reviewed real driver remains pending.
The resume effects (start, restart=always, open-ingress) require a caller guard:
the transport hands it its own final snapshot and emits the command only after
the guard returns. Without a guard they refuse before any call; the bare
transport is an unauthorized encoder, never a resume authority.
"""
from __future__ import annotations

from copy import deepcopy
import re

from first_transition_adapter import ROLES, digest, queue_metadata
from initial_transition_ops import Refused, require

SUPPORT_ROLES = ('redis', 'evolution-postgres', 'evolution-api')
SUPPORT_FIELDS = frozenset({'id', 'image', 'compose_project', 'compose_service', 'running',
                            'restart_policy', 'health', 'networks_digest'})
SERVICE_FIELDS = frozenset({'id', 'image', 'revision', 'compose_project', 'compose_service', 'started',
                            'restart_count', 'restart_policy', 'running', 'exit_code', 'gates_digest',
                            'mounts_digest', 'networks_digest'})


def host_command(operation, identifier):
    """Pure encoder shared with the separately authorized disposable probe."""
    require(isinstance(identifier, str) and re.fullmatch('[0-9a-f]{64}', identifier), 'transport-target')
    commands = {'restart-no': ('docker', 'update', '--restart=no', identifier),
                'term': ('docker', 'kill', '--signal=TERM', identifier),
                'wait': ('docker', 'wait', identifier),
                'restart-always': ('docker', 'update', '--restart=always', identifier),
                'start': ('docker', 'start', identifier)}
    require(operation in commands, 'transport-operation')
    return commands[operation]


class SimulatedHostTransport:
    def __init__(self, driver):
        require(getattr(driver, 'mode', None) == 'local-simulation', 'transport-simulation-required')
        self.driver = driver
        self.identities = None

    def _request(self, argv, timeout):
        require(getattr(self.driver, 'mode', None) == 'local-simulation', 'transport-simulation-required')
        try:
            return self.driver.request(tuple(argv), timeout=timeout)
        except TimeoutError:
            raise TimeoutError('simulated-transport-timeout') from None
        except Exception:
            raise Refused('simulated-transport-failed') from None

    def snapshot(self):
        data = self._request(('snapshot-metadata',), 5)
        require(isinstance(data, dict) and data.get('mode') == 'local-simulation', 'transport-snapshot')
        services = data.get('services')
        require(isinstance(services, dict) and set(services) == set(ROLES), 'transport-scope')
        identities = {role: state.get('id') if isinstance(state, dict) else None
                      for role, state in services.items()}
        require(all(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
                    for value in identities.values()) and len(set(identities.values())) == 4,
                'transport-identities')
        if self.identities is None:
            self.identities = identities
        require(identities == self.identities, 'transport-identity-changed')
        # Full shape/topology/gates validation remains in LocalHostContract.
        return deepcopy(data)

    def _target(self, identifier):
        require(self.identities is not None and identifier in self.identities.values(), 'transport-target')
        self.snapshot()  # Detect replacement immediately before a simulated effect.

    def block_ingress(self):
        require(self.identities is not None, 'transport-unobserved')
        self.snapshot()
        require(self._request(('block-ingress',), 5) is True, 'transport-ingress-receipt')

    def disable_restart(self, identifier):
        self._target(identifier)
        require(self._request(host_command('restart-no', identifier), 5) is True,
                'transport-restart-receipt')

    def signal_term(self, identifier):
        self._target(identifier)
        require(self._request(host_command('term', identifier), 5) is True,
                'transport-signal-receipt')

    def wait_stopped(self, identifier, timeout):
        require(type(timeout) is int and 0 < timeout <= 30, 'transport-wait-bound')
        self._target(identifier)
        status = self._request(host_command('wait', identifier), timeout)
        require(type(status) is int and status == 0, 'transport-exit-not-clean')


def _ids(value, roles):
    return (isinstance(value, dict) and set(value) == set(roles)
            and all(isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v) for v in value.values())
            and len(set(value.values())) == len(roles))


class ObservedHostTransport:
    def __init__(self, driver, *, legacy_project, network_id, service_ids, support_ids, processing_keys=()):
        require(getattr(driver, 'mode', None) == 'observed-host', 'transport-observed-required')
        require(isinstance(legacy_project, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,63}', legacy_project),
                'transport-project')
        require(isinstance(network_id, str) and re.fullmatch('[0-9a-f]{64}', network_id), 'transport-network')
        require(_ids(service_ids, ROLES), 'transport-identities')
        require(_ids(support_ids, SUPPORT_ROLES) and not set(support_ids.values()) & set(service_ids.values()),
                'transport-support-identities')
        self.driver, self.legacy_project, self.network_id = driver, legacy_project, network_id
        self.identities, self.support_ids = dict(service_ids), dict(support_ids)
        self.processing_keys = processing_keys  # validated by queue_metadata on every snapshot
        self.support_digest = None

    def _request(self, argv, timeout):
        require(getattr(self.driver, 'mode', None) == 'observed-host', 'transport-observed-required')
        try:
            return self.driver.request(tuple(argv), timeout=timeout)
        except TimeoutError:
            raise TimeoutError('observed-transport-timeout') from None
        except Exception:
            raise Refused('observed-transport-failed') from None

    def snapshot(self):
        raw = self._request(('inspect-host',), 10)
        require(isinstance(raw, dict) and set(raw) == {
            'ingress_blocked', 'unknown_writers', 'network_id', 'services', 'support'}, 'transport-snapshot')
        require(raw['network_id'] == self.network_id, 'transport-network-mismatch')
        require(type(raw['ingress_blocked']) is bool and type(raw['unknown_writers']) is int
                and raw['unknown_writers'] >= 0, 'transport-snapshot')
        support = raw['support']
        require(isinstance(support, dict) and set(support) == set(SUPPORT_ROLES), 'transport-support-scope')
        for role, state in support.items():
            require(isinstance(state, dict) and set(state) == SUPPORT_FIELDS, 'transport-support-shape')
            require(state['id'] == self.support_ids[role], 'transport-support-identity-changed')
            require(isinstance(state['image'], str) and re.fullmatch(r'sha256:[0-9a-f]{64}', state['image']),
                    'transport-support-image')
            require(state['compose_project'] == self.legacy_project and state['compose_service'] == role,
                    'transport-support-compose')
            require(state['running'] is True and state['restart_policy'] == 'always',
                    'transport-support-not-running')
            require(state['health'] == 'healthy' if role in ('redis', 'evolution-postgres')
                    else state['health'] in ('healthy', None), 'transport-support-unhealthy')
            require(isinstance(state['networks_digest'], str)
                    and re.fullmatch('[0-9a-f]{64}', state['networks_digest']), 'transport-support-network')
        support_digest = digest([self.network_id, {role: support[role] for role in sorted(SUPPORT_ROLES)}])
        if self.support_digest is None:
            self.support_digest = support_digest
        require(support_digest == self.support_digest, 'transport-support-changed')
        services = raw['services']
        require(isinstance(services, dict) and set(services) == set(ROLES), 'transport-scope')
        require(all(isinstance(services[role], dict) and set(services[role]) == SERVICE_FIELDS
                    for role in ROLES), 'transport-service-shape')
        require({role: services[role]['id'] for role in ROLES} == self.identities, 'transport-identity-changed')
        require(all(services[role].get('compose_project') == self.legacy_project
                    for role in ROLES if role != 'broadcast-worker'), 'transport-compose')
        queue = queue_metadata(lambda command, key: self._request(('redis-meta', command, key), 5),
                               processing_keys=self.processing_keys)
        # Field types/topology/gates validation remains in ObservedHostContract;
        # only the declared keys leave the transport, never extra driver data.
        return dict(mode='observed-host', ingress_blocked=raw['ingress_blocked'], support_digest=support_digest,
                    unknown_writers=raw['unknown_writers'], queue_digest=queue['metadata_digest'],
                    queue_counts=queue['counts'],
                    services=deepcopy({role: {key: services[role][key] for key in SERVICE_FIELDS}
                                       for role in ROLES}))

    def _target(self, identifier):
        require(identifier in self.identities.values(), 'transport-target')
        self.snapshot()  # Detect replacement immediately before a host effect.

    def _guarded(self, guard, identifier=None):
        if identifier is not None:
            require(identifier in self.identities.values(), 'transport-target')
        require(callable(guard), 'transport-guard-required')
        # This final observation, not an earlier one, is what the guard judges.
        guard(self.snapshot())

    def block_ingress(self):
        self.snapshot()
        require(self._request(('block-ingress',), 5) is True, 'transport-ingress-receipt')

    def open_ingress(self, guard=None):
        self._guarded(guard)
        require(self._request(('open-ingress',), 5) is True, 'transport-ingress-receipt')

    def disable_restart(self, identifier):
        self._target(identifier)
        require(self._request(host_command('restart-no', identifier), 5) is True,
                'transport-restart-receipt')

    def enable_restart(self, identifier, guard=None):
        self._guarded(guard, identifier)
        require(self._request(host_command('restart-always', identifier), 5) is True,
                'transport-restart-receipt')

    def signal_term(self, identifier):
        self._target(identifier)
        require(self._request(host_command('term', identifier), 5) is True,
                'transport-signal-receipt')

    def wait_stopped(self, identifier, timeout):
        require(type(timeout) is int and 0 < timeout <= 30, 'transport-wait-bound')
        self._target(identifier)
        status = self._request(host_command('wait', identifier), timeout)
        require(type(status) is int and status == 0, 'transport-exit-not-clean')

    def start_service(self, identifier, guard=None):
        self._guarded(guard, identifier)
        require(self._request(host_command('start', identifier), 10) is True,
                'transport-start-receipt')
