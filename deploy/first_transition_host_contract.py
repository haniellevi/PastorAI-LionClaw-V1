"""Containment contract tested only through a caller-supplied host simulator.

No real host transport, SSH, Docker client, gate setter or start operation is
provided. This proves the orchestration contract, not real host containment.
"""
from __future__ import annotations

import re

from first_transition_adapter import ROLES, digest
from initial_transition_ops import Refused, require

FIELDS = frozenset({'id', 'image', 'revision', 'compose_project', 'compose_service',
                    'started', 'restart_count', 'restart_policy', 'running', 'exit_code',
                    'gates_digest', 'mounts_digest', 'networks_digest'})
DYNAMIC = frozenset({'restart_policy', 'running', 'exit_code'})
HEX = re.compile('[0-9a-f]{64}')


class LocalHostContract:
    def __init__(self, port, journal):
        self.port, self.j = port, journal

    def _call(self, operation, *args):
        try:
            return getattr(self.port, operation)(*args)
        except TimeoutError:
            raise Refused('local-host-timeout') from None
        except Exception:
            raise Refused('local-host-effect-failed') from None

    def _snapshot(self):
        data = self._call('snapshot')
        require(isinstance(data, dict) and set(data) == {
            'mode', 'ingress_blocked', 'support_digest', 'unknown_writers', 'services'}, 'local-host-shape')
        require(data['mode'] == 'local-simulation', 'local-host-simulation-required')
        require(type(data['ingress_blocked']) is bool
                and isinstance(data['support_digest'], str) and HEX.fullmatch(data['support_digest']),
                'local-host-shape')
        require(type(data['unknown_writers']) is int and data['unknown_writers'] == 0,
                'local-host-unknown-writer')
        services = data['services']
        require(isinstance(services, dict) and set(services) == set(ROLES), 'local-host-services')
        for role, state in services.items():
            require(isinstance(state, dict) and set(state) == FIELDS, 'local-host-service-shape')
            require(isinstance(state['id'], str) and HEX.fullmatch(state['id'])
                    and isinstance(state['image'], str) and re.fullmatch(r'sha256:[0-9a-f]{64}', state['image'])
                    and (state['revision'] is None or isinstance(state['revision'], str)
                         and re.fullmatch('[0-9a-f]{40}', state['revision'])), 'local-host-identity')
            require(type(state['running']) is bool and type(state['restart_count']) is int
                    and state['restart_count'] >= 0 and state['restart_policy'] in ('always', 'no')
                    and (state['exit_code'] is None or type(state['exit_code']) is int)
                    and isinstance(state['started'], str)
                    and re.fullmatch(r'[A-Za-z0-9_.:+-]{1,64}', state['started']), 'local-host-state')
            require(all(isinstance(state[key], str) and HEX.fullmatch(state[key])
                        for key in ('gates_digest', 'mounts_digest', 'networks_digest')), 'local-host-digest')
            if role == 'broadcast-worker':
                require(state['compose_project'] is None and state['compose_service'] is None,
                        'local-host-broadcast-must-be-standalone')
            else:
                require(state['compose_service'] == role and isinstance(state['compose_project'], str)
                        and re.fullmatch('[A-Za-z0-9_-]{1,63}', state['compose_project']), 'local-host-compose')
        require(len({s['id'] for s in services.values()}) == 4, 'local-host-duplicate-identity')
        require(len({s['compose_project'] for role, s in services.items() if role != 'broadcast-worker'}) == 1,
                'local-host-compose-projects')
        fingerprint = digest([data['support_digest'], {
            role: {key: state[key] for key in sorted(FIELDS - DYNAMIC)} for role, state in services.items()}])
        baseline = self.j.last('local-host-init')
        if baseline:
            require(fingerprint == baseline['fingerprint'], 'local-host-identity-or-support-changed')
        return data, fingerprint

    def _intent(self, step):
        if self.j.last('local-host-intent', step) is None:
            self.j.append('local-host-intent', step=step)

    def _done(self, step):
        if self.j.last('local-host-done', step) is None:
            self.j.append('local-host-done', step=step)

    def assert_contained(self):
        require(self.j.last('local-host-init') is not None, 'local-host-unobserved')
        data, fingerprint = self._snapshot()
        require(data['ingress_blocked'], 'local-host-ingress-open')
        for state in data['services'].values():
            require(state['restart_policy'] == 'no' and not state['running'] and state['exit_code'] == 0,
                    'local-host-not-cleanly-contained')
        return dict(mode='local-simulation', fingerprint=fingerprint, stopped_roles=ROLES,
                    host_verified=False)

    def contain(self):
        data, fingerprint = self._snapshot()
        if self.j.last('local-host-init') is None:
            require(all(s['running'] and s['restart_policy'] == 'always' for s in data['services'].values()),
                    'local-host-baseline-state')
            self.j.append('local-host-init', fingerprint=fingerprint, mode='local-simulation')
        if self.j.last('local-host-done', 'ingress'):
            require(data['ingress_blocked'], 'local-host-ingress-reopened')
        if not data['ingress_blocked']:
            self._intent('ingress')
            self._call('block_ingress')
        require(self._snapshot()[0]['ingress_blocked'], 'local-host-ingress-open')
        self._done('ingress')
        for role in ROLES:
            state = self._snapshot()[0]['services'][role]
            step = 'restart-no:' + role
            if self.j.last('local-host-done', step):
                require(state['restart_policy'] == 'no', 'local-host-restart-reenabled')
            if state['restart_policy'] != 'no':
                self._intent(step)
                self._call('disable_restart', state['id'])
            require(self._snapshot()[0]['services'][role]['restart_policy'] == 'no',
                    'local-host-restart-not-disabled')
            self._done(step)
            state = self._snapshot()[0]['services'][role]
            step = 'term:' + role
            if self.j.last('local-host-done', step):
                require(not state['running'], 'local-host-restarted')
            if state['running']:
                # An unreceipted SIGTERM may already have been delivered. Wait;
                # do not blindly signal again or escalate to SIGKILL/restart.
                if self.j.last('local-host-intent', step) is None:
                    self._intent(step)
                    self._call('signal_term', state['id'])
                self._call('wait_stopped', state['id'], 30)
            state = self._snapshot()[0]['services'][role]
            require(not state['running'] and state['exit_code'] == 0, 'local-host-exit-not-clean')
            self._done(step)
        receipt = self.assert_contained()
        if self.j.last('local-host-contained') is None:
            self.j.append('local-host-contained', **receipt)
        return receipt
