"""Containment contracts over caller-supplied host ports.

LocalHostContract proves the orchestration against a simulator only.
ObservedHostContract is a contract over a caller-supplied driver: every field
(ingress, unknown writers, queue counts, health, digests) is driver-reported,
never independent host evidence, so receipts carry host_verified=False. Queue
counts cannot prove contents or quiescence. It may resume the pinned legacy
only while no DDL marker is journaled; marker absence is no proof that DDL did
not run elsewhere. The resume token binds the host identity, not a human
approval. Partial containment or an abnormal exit is refused fail-closed; there
is no automatic recovery. Checks run immediately before each effect and again
after it, without any atomicity over the driver or host; each resume effect is
also judged, without new IO, on the port's own final snapshot via a guard. Its
journal is never shared with the local adapter (adapter-*/local-host-*). No SSH, Docker client,
gate setter, real executor or deploy operation is provided here.
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
RESUMABLE = frozenset({'started', 'restart_count'})
START_ORDER = ('backend', 'queue-worker', 'broadcast-worker', 'cron-worker')


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


def _observed_services(services):
    require(isinstance(services, dict) and set(services) == set(ROLES), 'observed-host-services')
    for role, state in services.items():
        require(isinstance(state, dict) and set(state) == FIELDS, 'observed-host-service-shape')
        require(isinstance(state['id'], str) and HEX.fullmatch(state['id'])
                and isinstance(state['image'], str) and re.fullmatch(r'sha256:[0-9a-f]{64}', state['image'])
                and (state['revision'] is None or isinstance(state['revision'], str)
                     and re.fullmatch('[0-9a-f]{40}', state['revision'])), 'observed-host-identity')
        require(type(state['running']) is bool and type(state['restart_count']) is int
                and state['restart_count'] >= 0 and state['restart_policy'] in ('always', 'no')
                and (state['exit_code'] is None or type(state['exit_code']) is int)
                and isinstance(state['started'], str)
                and re.fullmatch(r'[A-Za-z0-9_.:+-]{1,64}', state['started']), 'observed-host-state')
        require(all(isinstance(state[key], str) and HEX.fullmatch(state[key])
                    for key in ('gates_digest', 'mounts_digest', 'networks_digest')), 'observed-host-digest')
        if role == 'broadcast-worker':
            require(state['compose_project'] is None and state['compose_service'] is None,
                    'observed-host-broadcast-must-be-standalone')
        else:
            require(state['compose_service'] == role and isinstance(state['compose_project'], str)
                    and re.fullmatch('[A-Za-z0-9_-]{1,63}', state['compose_project']), 'observed-host-compose')
    require(len({s['id'] for s in services.values()}) == 4, 'observed-host-duplicate-identity')
    require(len({s['compose_project'] for role, s in services.items() if role != 'broadcast-worker'}) == 1,
            'observed-host-compose-projects')


class ObservedHostContract:
    def __init__(self, port, journal):
        self.port, self.j = port, journal

    def _call(self, operation, *args):
        try:
            return getattr(self.port, operation)(*args)
        except TimeoutError:
            raise Refused('observed-host-timeout') from None
        except Exception:
            raise Refused('observed-host-effect-failed') from None

    def _assert_own_journal(self):
        require(not any(event['kind'].startswith(('adapter-', 'local-host-')) for event in self.j.events),
                'observed-host-journal-mixed')

    def _snapshot(self, data=None):
        # data: a port's final snapshot handed to a pre-effect guard, validated without new IO.
        self._assert_own_journal()
        if data is None:
            data = self._call('snapshot')
        require(isinstance(data, dict) and set(data) == {
            'mode', 'ingress_blocked', 'support_digest', 'unknown_writers', 'queue_digest', 'queue_counts',
            'services'}, 'observed-host-shape')
        require(data['mode'] == 'observed-host', 'observed-host-required')
        require(type(data['ingress_blocked']) is bool
                and isinstance(data['support_digest'], str) and HEX.fullmatch(data['support_digest']),
                'observed-host-shape')
        require(type(data['unknown_writers']) is int and data['unknown_writers'] == 0,
                'observed-host-unknown-writer')
        counts = data['queue_counts']
        require(isinstance(data['queue_digest'], str) and HEX.fullmatch(data['queue_digest'])
                and isinstance(counts, dict) and counts
                and all(isinstance(k, str) and type(v) is int and v >= 0 for k, v in counts.items()),
                'observed-host-queue')
        services = data['services']
        _observed_services(services)
        # started/restart_count legitimately change on resume; un-resumed roles keep
        # their baseline and resumed roles keep their receipted fresh start.
        fingerprint = digest([data['support_digest'], {
            role: {key: state[key] for key in sorted(FIELDS - DYNAMIC - RESUMABLE)}
            for role, state in services.items()}])
        baseline = self.j.last('observed-host-init')
        if baseline:
            require(fingerprint == baseline['fingerprint'], 'observed-host-identity-or-support-changed')
            for role, state in services.items():
                step = 'legacy-resume:' + role
                if self.j.last('observed-host-intent', step) is None:
                    require(state['started'] == baseline['initial_started'][role]
                            and state['restart_count'] == baseline['initial_restarts'][role],
                            'observed-host-identity-or-support-changed')
                done = self.j.last('observed-host-done', step)
                if done:
                    require(state['running'] is True and state['restart_policy'] == 'always'
                            and state['restart_count'] == 0 and state['started'] == done['started'],
                            'observed-host-resumed-state-changed')
        return data, fingerprint

    def _intent(self, step):
        if self.j.last('observed-host-intent', step) is None:
            self.j.append('observed-host-intent', step=step)

    def _done(self, step):
        if self.j.last('observed-host-done', step) is None:
            self.j.append('observed-host-done', step=step)

    def assert_contained(self):
        self._assert_own_journal()
        # Once a resume is intended the host is never containment evidence again.
        require(self.j.last('observed-host-intent', 'legacy-resume') is None, 'observed-host-resume-started')
        settled = self.j.last('observed-host-settled')
        require(self.j.last('observed-host-init') is not None and settled is not None,
                'observed-host-unobserved')
        data, fingerprint = self._snapshot()
        require(data['ingress_blocked'] is True, 'observed-host-ingress-open')
        for state in data['services'].values():
            require(state['restart_policy'] == 'no' and not state['running'] and state['exit_code'] == 0,
                    'observed-host-not-cleanly-contained')
        require(data['queue_digest'] == settled['queue_digest'], 'observed-host-queue-drift')
        return dict(mode='observed-host', evidence='driver-reported', fingerprint=fingerprint,
                    queue_digest=settled['queue_digest'], stopped_roles=ROLES, host_verified=False,
                    quiescence_proven=False)

    def contain(self):
        self._assert_own_journal()
        require(self.j.last('observed-host-intent', 'legacy-resume') is None, 'observed-host-resume-started')
        data, fingerprint = self._snapshot()
        if self.j.last('observed-host-init') is None:
            require(all(s['running'] and s['restart_policy'] == 'always' for s in data['services'].values()),
                    'observed-host-baseline-state')
            self.j.append('observed-host-init', fingerprint=fingerprint, mode='observed-host',
                          evidence='driver-reported', host_verified=False,
                          initial_started={role: data['services'][role]['started'] for role in ROLES},
                          initial_restarts={role: data['services'][role]['restart_count'] for role in ROLES})
        if self.j.last('observed-host-done', 'ingress'):
            require(data['ingress_blocked'], 'observed-host-ingress-reopened')
        if not data['ingress_blocked']:
            self._intent('ingress')
            self._call('block_ingress')
        require(self._snapshot()[0]['ingress_blocked'] is True, 'observed-host-ingress-open')
        self._done('ingress')
        for role in ROLES:
            state = self._snapshot()[0]['services'][role]
            step = 'restart-no:' + role
            if self.j.last('observed-host-done', step):
                require(state['restart_policy'] == 'no', 'observed-host-restart-reenabled')
            if state['restart_policy'] != 'no':
                self._intent(step)
                self._call('disable_restart', state['id'])
            require(self._snapshot()[0]['services'][role]['restart_policy'] == 'no',
                    'observed-host-restart-not-disabled')
            self._done(step)
            state = self._snapshot()[0]['services'][role]
            step = 'term:' + role
            if self.j.last('observed-host-done', step):
                require(not state['running'], 'observed-host-restarted')
            if state['running']:
                # Never re-signal an unreceipted SIGTERM; wait or hold.
                if self.j.last('observed-host-intent', step) is None:
                    self._intent(step)
                    self._call('signal_term', state['id'])
                self._call('wait_stopped', state['id'], 30)
            state = self._snapshot()[0]['services'][role]
            require(not state['running'] and state['exit_code'] == 0, 'observed-host-exit-not-clean')
            self._done(step)
        settled_data = self._snapshot()[0]
        if self.j.last('observed-host-settled') is None:
            self.j.append('observed-host-settled', queue_digest=settled_data['queue_digest'],
                          queue_counts=settled_data['queue_counts'], evidence='driver-reported',
                          quiescence_proven=False)
        receipt = self.assert_contained()
        if self.j.last('observed-host-contained') is None:
            self.j.append('observed-host-contained', **receipt)
        return receipt

    def resume_token(self):
        init = self.j.last('observed-host-init')
        require(init is not None, 'observed-host-unobserved')
        return 'RESUME:' + init['fingerprint']

    def _assert_pre_ddl(self):
        # Journal-only guard, re-read before each effect and after each observation.
        # It cannot see DDL performed outside this journal; that needs a DB proof.
        require(self.j.last('adapter-ddl-marker') is None and self.j.last('ddl-marker') is None,
                'post-ddl-resume-forbidden')

    def _resume_snapshot(self, data=None):
        self._assert_pre_ddl()  # keeps priority over the mixed-journal refusal
        data, _ = self._snapshot(data)
        self._assert_pre_ddl()
        self._check_resume_roles(data)
        if self.j.last('observed-host-intent', 'open-ingress') is None:
            # Ingress stays blocked through any partial resume until its opening is intended.
            require(data['ingress_blocked'] is True, 'observed-host-ingress-open')
        return data

    def _check_resume_roles(self, data):
        # Every role must match its phase on every observation, not just the target.
        init = self.j.last('observed-host-init')
        for role, state in data['services'].items():
            step = 'legacy-resume:' + role
            if self.j.last('observed-host-done', step) is not None:
                continue  # _snapshot already proves the receipted fresh running state.
            if self.j.last('observed-host-intent', step) is None:
                require(not state['running'], 'observed-host-resume-not-fresh')
                require(state['restart_policy'] == 'no' and state['exit_code'] == 0,
                        'observed-host-not-cleanly-contained')
            elif state['running']:
                self._check_fresh(state, role, init)
            else:
                require(state['restart_policy'] == 'no' and state['exit_code'] == 0
                        and state['started'] == init['initial_started'][role]
                        and state['restart_count'] == init['initial_restarts'][role],
                        'observed-host-resume-not-fresh')

    def _effect(self, operation, check, *args):
        # The port must pass its own final snapshot to the guard and emit only after
        # it returns; a guard refusal keeps its contract code, a skipped guard refuses.
        outcome = []
        def guard(final):
            try:
                check(final)
            except Refused as exc:
                outcome.append(exc)
                raise
            outcome.append(True)
        try:
            self._call(operation, *args, guard)
        except Refused:
            refusals = [item for item in outcome if isinstance(item, Refused)]
            if refusals:
                raise refusals[0] from None
            raise
        require(True in outcome, 'observed-host-guard-skipped')

    def _start_observed(self, data, init):
        # An actual start: receipted, or intended with a verifiably fresh start.
        # A running or changed role without both is inconsistent and refused.
        observed = False
        for role in ROLES:
            step = 'legacy-resume:' + role
            if self.j.last('observed-host-done', step) is not None:
                observed = True
                continue
            state = data['services'][role]
            if state['running'] or state['started'] != init['initial_started'][role]:
                require(self.j.last('observed-host-intent', step) is not None and state['running'] is True
                        and state['restart_count'] == 0 and state['started'] != init['initial_started'][role],
                        'observed-host-resume-not-fresh')
                observed = True
        return observed

    def _check_start(self, data, role, init, settled, allow_queue_drift):
        # Only a never-started container may be started; the queue gate holds until an actual start.
        state = data['services'][role]
        require(not state['running'] and state['exit_code'] == 0 and state['started'] == init['initial_started'][role]
                and state['restart_count'] == init['initial_restarts'][role]
                and state['restart_policy'] == 'no', 'observed-host-resume-not-fresh')
        if not self._start_observed(data, init):
            self._queue_gate(data, settled, allow_queue_drift)

    def _check_fresh(self, state, role, init):
        require(state['running'] is True and state['restart_count'] == 0
                and state['started'] != init['initial_started'][role], 'observed-host-resume-not-fresh')
        return state

    def _queue_gate(self, data, settled, allow_queue_drift):
        # Before the first actual start the queue must match the settled baseline or
        # the drift is explicitly accepted and journaled before the effect.
        if data['queue_digest'] != settled['queue_digest']:
            require(allow_queue_drift is True, 'observed-host-queue-drift')
            accepted = self.j.last('observed-host-queue-drift-accepted')
            if accepted is None or accepted['current_digest'] != data['queue_digest']:
                self.j.append('observed-host-queue-drift-accepted', settled_digest=settled['queue_digest'],
                              current_digest=data['queue_digest'])

    def resume_legacy(self, confirmation, expected_token=None, *, allow_queue_drift=False):
        self._assert_pre_ddl()
        self._assert_own_journal()
        require(self.j.last('observed-host-contained') is not None, 'observed-host-not-contained')
        token = self.resume_token()  # bound to this journal's observed host; not a human approval
        require(expected_token is None or expected_token == token, 'observed-host-resume-confirmation')
        if self.j.last('observed-host-intent', 'legacy-resume') is None:
            require(confirmation == token, 'observed-host-resume-confirmation')
        init = self.j.last('observed-host-init')
        settled = self.j.last('observed-host-settled')
        data = self._resume_snapshot()
        if not self._start_observed(data, init):
            for state in data['services'].values():
                require(not state['running'] and state['exit_code'] == 0 and state['restart_policy'] == 'no',
                        'observed-host-not-cleanly-contained')
            self._queue_gate(data, settled, allow_queue_drift)
        else:
            require(self.j.last('observed-host-intent', 'legacy-resume') is not None,
                    'observed-host-not-contained')
        self._intent('legacy-resume')
        for role in START_ORDER:
            step = 'legacy-resume:' + role
            if self.j.last('observed-host-done', step) is not None:
                continue  # _snapshot() keeps re-validating the receipted fresh start
            if self.j.last('observed-host-intent', step) is None:
                state = self._resume_snapshot()['services'][role]
                require(not state['running'] and state['exit_code'] == 0 and state['restart_policy'] == 'no',
                        'observed-host-not-cleanly-contained')
                self._intent(step)
            # Re-observed after the intent, immediately before the effect (first run or replay).
            data = self._resume_snapshot()
            state = data['services'][role]
            if not state['running']:
                self._check_start(data, role, init, settled, allow_queue_drift)
                # Start before restart=always: never a stopped container with restart=always.
                self._effect('start_service', lambda final, role=role: self._check_start(
                    self._resume_snapshot(final), role, init, settled, allow_queue_drift), state['id'])
            state = self._check_fresh(self._resume_snapshot()['services'][role], role, init)
            if state['restart_policy'] != 'always':
                self._effect('enable_restart', lambda final, role=role: self._check_fresh(
                    self._resume_snapshot(final)['services'][role], role, init), state['id'])
            state = self._resume_snapshot()['services'][role]
            require(state['restart_policy'] == 'always', 'observed-host-restart-not-enabled')
            self._check_fresh(state, role, init)
            self.j.append('observed-host-done', step=step, started=state['started'])
        if self.j.last('observed-host-done', 'open-ingress') is None:
            if self.j.last('observed-host-intent', 'open-ingress') is None:
                self._resume_snapshot()  # still blocked and pre-DDL right before authorizing it
                self._intent('open-ingress')
            if self._resume_snapshot()['ingress_blocked']:
                # _snapshot() re-validates every receipted fresh start on the final observation.
                self._effect('open_ingress', self._resume_snapshot)
            require(not self._resume_snapshot()['ingress_blocked'], 'observed-host-ingress-still-blocked')
            self._done('open-ingress')
        # Every call, terminal replay included, re-proves the resumed host.
        final_data = self._resume_snapshot()
        require(final_data['ingress_blocked'] is False, 'observed-host-ingress-still-blocked')
        if self.j.last('observed-host-resumed') is None:
            self.j.append('observed-host-resumed', resumed_roles=START_ORDER, evidence='driver-reported')
        return dict(mode='observed-host', status='legacy-resumed', resumed_roles=START_ORDER,
                    ingress_blocked=False, evidence='driver-reported', host_verified=False)
