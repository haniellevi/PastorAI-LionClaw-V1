"""A10 of the first transition: consumers up with the PRE-WINDOW gates, separately authorized.

Mixed into ``first_transition_orchestrator.FirstTransition``; it shares its journal and ports.

Snapshot (taken by ``run()``, never by A10):

* ``transition-gate-snapshot``: immediately BEFORE ``contain()``, while the legacy still runs,
  the exact ``NAME=value`` of the four mandatory gates of each pinned legacy role
  (``ObservedHostDriver.legacy_gates``) and the per-role restore map
  (``first_transition_candidate.restore_values``: an absent gate restores to the closed default,
  so nothing closed before the window is ever opened; unknown values refuse BEFORE containment);
* ``transition-pending-baseline``: right after quiescence (legacy stopped, database quiet), the
  read-only counts of ``gate_fechado`` cancellations and V3 activations observed closed.

``a10(token)``, only after ``transition-a9-complete`` and with the operator's token
(``a10_token()``: digest of plan, config, A9 receipt and snapshot; printed, never inferred):

1. preconditions, before any effect: snapshot and baseline present; a fresh re-read of the
   legacy gates equals the snapshot (``a10-gate-snapshot-divergent`` otherwise); A9 state
   intact (backend smoked, consumers held, legacy contained, ingress blocked, final ledger,
   database quiet). Any refusal here changes nothing: gates stay closed, consumers held;
2. ``a10:recreate``: public gate file (restored values only) + ONE ``up --no-start
   --force-recreate``; the four new containers must carry exactly the restored gates;
3. ``a10:start:<role>`` in ``A10_ORDER``: backend (smoked again with the restored gates), then
   queue-worker, broadcast-worker and cron-worker LAST. The new cron never runs with a gate
   different from the legacy's, so the transition itself cannot turn pending work into
   ``cancelado/gate_fechado`` (the product rule "closed gate cancels" is untouched: if the gate
   was already closed before the window it stays closed and keeps that behaviour);
4. ``a10:ingress``: Evolution->backend first, then external;
5. verification (also on every replay): the four running since their receipts with restart
   count 0 and exactly the restored gates; legacy still stopped; ingress open; final ledger;
   legacy gates still equal to the snapshot; and, when ALLOW_REAL_SENDS of the cron was open
   before the window, no new ``gate_fechado`` cancellation nor V3 activation observed closed
   since the baseline.

A definite refusal after the first A10 effect triggers containment (``transition-a10-contained``):
both ingress entries blocked, then cron, broadcast, queue and backend set restart=no and
stopped. Every sending process is down, so nothing is sent and nothing is cancelled; the
gates are NOT rewritten closed, because a cron started later with closed gates would cancel
pending work. There is never a legacy resume after the DDL marker and never an automatic
reopen: a contained A10 refuses until a human decision (new journal or forward fix).

Replays are idempotent: receipted steps are re-verified, never repeated. An intent without a
receipt (interruption) is adopted only when a fresh inspection proves the exact expected
outcome; anything else refuses as ambiguous and, since an A10 effect may have happened, contains.
An interruption (signal) never contains: the next invocation resumes from the journal.
"""
from __future__ import annotations

from first_transition_adapter import ROLES, digest
from first_transition_candidate import (check_created, check_identity, check_restored_running,
                                        gate_is_open, restore_values, write_gate_override)
from first_transition_database import require_same_database
from first_transition_host_driver import ENTRIES
from initial_transition_ops import Refused, require

A10_ORDER = ('backend', 'queue-worker', 'broadcast-worker', 'cron-worker')
CONTAIN_ORDER = ('cron-worker', 'broadcast-worker', 'queue-worker', 'backend')
PENDING_KEYS = ('gate_cancelled', 'v3_gate_closed')


class A10Step:
    """Requires from the host class: j, plan, config_digest, host, db, candidate, sleep, t,
    legacy_gates, ingress, pending, _observe, _open, _intent, _done, _held, _init."""

    # -- snapshot, taken by run() ------------------------------------------------------------------
    def _gate_snapshot(self):
        if self.legacy_gates is None or self.j.last('transition-gate-snapshot') is not None:
            return
        # Only meaningful while the legacy is the effective state: never after containment began.
        if self.j.last('observed-host-init') is not None:
            return
        roles = self._read_legacy_gates()
        restore = {role: restore_values(roles[role]) for role in ROLES}
        self.j.append('transition-gate-snapshot', captured='before-containment', roles=roles, restore=restore,
                      gates_digest={role: digest(['gates', roles[role]]) for role in ROLES},
                      open_gates={role: sorted(n for n, v in restore[role].items() if gate_is_open(n, v))
                                  for role in ROLES})

    def _read_legacy_gates(self):
        try:
            roles = self.legacy_gates(timeout=20)
        except Refused:
            raise
        except Exception:  # noqa: BLE001 - qualquer falha de leitura vira recusa fechada
            raise Refused('a10-gate-snapshot-unreadable') from None
        require(isinstance(roles, dict) and set(roles) == set(ROLES)
                and all(isinstance(v, list) and all(isinstance(g, str) for g in v) for v in roles.values()),
                'a10-gate-snapshot-unreadable')
        return {role: sorted(roles[role]) for role in ROLES}

    def _pending_baseline(self):
        if self.pending is None or self.j.last('transition-pending-baseline') is not None:
            return
        if self.j.last('transition-gate-snapshot') is None:
            return
        counts = self._pending_counts()
        self.j.append('transition-pending-baseline', evidence='database-read-only',
                      **{k: counts[k] for k in PENDING_KEYS})

    def _pending_counts(self):
        counts = self.pending(timeout=self.t['observe_s'])
        require(isinstance(counts, dict) and counts.get('identity') == self.expected.identity
                and all(counts.get(k) is None or type(counts.get(k)) is int and counts[k] >= 0
                        for k in PENDING_KEYS), 'a10-pending-unreadable')
        return counts

    # -- authorization -----------------------------------------------------------------------------
    def a10_token(self):
        a9, snapshot = self.j.last('transition-a9-complete'), self.j.last('transition-gate-snapshot')
        require(a9 is not None, 'a10-a9-incomplete')
        require(snapshot is not None, 'a10-gate-snapshot-missing')
        return digest(['a10', self.plan.digest, self.config_digest, digest(a9), digest(snapshot)])

    def _a10_started(self):
        return any(e['step'].startswith('a10:') for e in self.j.find('transition-intent'))

    # -- entry ---------------------------------------------------------------------------------------
    def a10(self, confirmation):
        self._init()
        require(self.j.last('transition-failed') is None, 'transition-stopped')
        require(self.j.last('transition-a10-contained') is None
                and self.j.last('transition-a10-containment') is None, 'a10-contained')
        require(self.legacy_gates is not None and self.ingress is not None and self.pending is not None,
                'a10-ports-missing')
        require(isinstance(confirmation, str) and confirmation == self.a10_token(), 'a10-confirmation')
        try:
            return self._a10()
        except Exception as exc:
            if self._a10_started():
                self._a10_contain(str(exc) if isinstance(exc, Refused) else 'a10-failed')
            raise

    def _a10_inputs(self):
        snapshot = self.j.last('transition-gate-snapshot')
        baseline = self.j.last('transition-pending-baseline')
        require(snapshot is not None, 'a10-gate-snapshot-missing')
        require(baseline is not None, 'a10-pending-baseline-missing')
        marker, contained = self.j.last('ddl-marker'), self.j.last('observed-host-contained')
        require(contained is not None and snapshot['seq'] < contained['seq'], 'a10-gate-snapshot-missing')
        require(marker is not None and snapshot['seq'] < baseline['seq'] < marker['seq'],
                'a10-pending-baseline-missing')
        roles = snapshot['roles']
        restore = {role: restore_values(roles[role]) for role in ROLES}
        require(restore == snapshot['restore'], 'a10-gate-snapshot-invalid')
        # The legacy containers still exist (stopped): their configuration must still be the snapshot.
        require(self._read_legacy_gates() == roles, 'a10-gate-snapshot-divergent')
        return restore, baseline

    def _a10_final_database(self):
        observation = self._observe()
        require_same_database(observation, self.expected)
        require(observation['ledger'] == tuple(sorted(m.name for m in self.plan.migrations)), 'final-ledger')
        require(observation['catalog'] == self.j.last('transition-migrated')['catalog'], 'database-ddl-drift')
        require(not observation['invalid'] and observation['index_builds'] == 0, 'database-ddl-in-progress')

    def _a10(self):
        restore, baseline = self._a10_inputs()
        created9 = self.j.last('transition-done', 'a9:create')
        started9 = self.j.last('transition-done', 'a9:start-backend')
        require(created9 is not None and started9 is not None, 'a10-a9-incomplete')
        recreated = self.j.last('transition-done', 'a10:recreate')
        if recreated is None and self._open('a10:recreate'):
            recreated = self._adopt_recreate(created9['ids'], restore)
        if recreated is None:
            # Full A9 hold proof right before the first A10 effect (ingress blocked, DB quiet).
            self._held(created9['ids'], created9['created'], started9['started'])
            write_gate_override(self.candidate.spec, restore)
            self._intent('a10:recreate', project=self.candidate.spec.project)
            self.candidate.recreate_restored()
            recreated = self._recreated(created9['ids'], restore, adopt=False)
        ids, created = recreated['ids'], recreated['created']
        require(self.candidate.project_ids() == tuple(sorted(ids.values())), 'a10-project-changed')
        smoke = None
        for role in A10_ORDER:
            step = 'a10:start:' + role
            if role != 'backend' and smoke is None:
                # Backend readiness gates every later effect, on replay too (start receipt != smoke passed).
                smoke = self.candidate.smoke(ids['backend'], restore['backend'])
            if self.j.last('transition-done', step) is not None:
                continue
            state = self.candidate.inspect((ids[role],))[ids[role]]
            check_identity(self.candidate.spec, role, state, restore[role])
            if self._open(step):
                # Interrupted start: adopt only a clean first run of this very container.
                check_restored_running(state, code='a10-start-ambiguous')
            else:
                check_created(state, created[role])
                if role == 'backend':
                    self._a10_final_database()
                # Never two of a kind: the legacy twin of this role must still be stopped (restart=no).
                self.host.legacy_stopped()
                self._intent(step, id=ids[role])
                self.candidate.start_restored(role, ids[role], restore[role])
                state = self.candidate.inspect((ids[role],))[ids[role]]
                check_restored_running(state)
            self._done(step, started=state['started'])
        if self.j.last('transition-done', 'a10:ingress') is None:
            self.host.legacy_stopped()
            self._intent('a10:ingress')
            self._open_ingress()
            self._done('a10:ingress')
        if smoke is None:
            smoke = self.candidate.smoke(ids['backend'], restore['backend'])  # fresh on every invocation
        self.sleep(self.t['a10_settle_s'])
        verification = self._a10_verify(ids, restore, baseline)
        if self.j.last('transition-a10-complete') is None:
            self.j.append('transition-a10-complete', smoke=smoke, **verification)
        return dict(status='a10-complete', smoke=smoke, workers='running', ingress_open=True,
                    gates='restored-from-pre-window-snapshot', legacy_resume_allowed=False,
                    production_ready=False, **verification)

    def _recreated(self, ids9, restore, *, adopt):
        found = self.candidate.project_ids()
        code = 'a10-recreate-ambiguous' if adopt else 'a10-recreate-scope'
        require(len(found) == 4 and not set(found) & set(ids9.values()), code)
        states = self.candidate.inspect(found)
        ids = {state['service']: ident for ident, state in states.items()}
        require(set(ids) == set(ROLES), code)
        for role in ROLES:
            check_identity(self.candidate.spec, role, states[ids[role]], restore[role])
            check_created(states[ids[role]], code=code)
        return self._done('a10:recreate', ids=ids, created={
            role: dict(started=states[ids[role]]['started'], restart_count=states[ids[role]]['restart_count'])
            for role in ROLES})

    def _adopt_recreate(self, ids9, restore):
        """Interrupted recreation: adopt only four fresh, never-started containers with the restored gates."""
        return self._recreated(ids9, restore, adopt=True)

    def _ingress_states(self):
        states = {}
        for entry in ENTRIES:
            binding = self.ingress[entry]
            value = binding.observe(binding.scope, timeout=10)
            require(type(value) is str and value in ('open', 'blocked'), 'a10-ingress-shape')
            states[entry] = value
        return states

    def _open_ingress(self):
        # Internal Evolution->backend first, external last; both must end open.
        for entry in reversed(ENTRIES):
            if self._ingress_states()[entry] == 'blocked':
                binding = self.ingress[entry]
                require(binding.open(binding.scope, timeout=30) is True, 'a10-ingress-receipt')
        require(all(v == 'open' for v in self._ingress_states().values()), 'a10-ingress-still-blocked')

    def _a10_verify(self, ids, restore, baseline):
        states = self.candidate.inspect(tuple(ids[r] for r in ROLES))
        for role in ROLES:
            state = states[ids[role]]
            check_identity(self.candidate.spec, role, state, restore[role])
            check_restored_running(state, self.j.last('transition-done', 'a10:start:' + role)['started'])
        legacy = self.host.legacy_stopped()
        require(legacy['ingress_open'] is True, 'a10-ingress-not-open')
        require(all(v == 'open' for v in self._ingress_states().values()), 'a10-ingress-not-open')
        self._a10_final_database()
        require(self._read_legacy_gates() == self.j.last('transition-gate-snapshot')['roles'],
                'a10-gate-snapshot-divergent')
        counts = self._pending_counts()
        cron_sends = gate_is_open('ALLOW_REAL_SENDS', restore['cron-worker']['ALLOW_REAL_SENDS'])
        if cron_sends:
            for key in PENDING_KEYS:
                require((counts[key] or 0) == (baseline[key] or 0), 'a10-pending-cancelled')
            guard = 'no-gate-cancellation-since-baseline'
        else:
            # The gate was already closed before the window: the product rule keeps cancelling, as before.
            guard = 'not-applicable-gate-closed-before-window'
        return dict(gates_equal_snapshot=True, pending_guard=guard,
                    gate_cancelled=counts['gate_cancelled'], v3_gate_closed=counts['v3_gate_closed'],
                    baseline_gate_cancelled=baseline['gate_cancelled'],
                    baseline_v3_gate_closed=baseline['v3_gate_closed'])

    # -- containment ---------------------------------------------------------------------------------
    def _a10_contain(self, code):
        """Block both entries, then stop every candidate container (cron first). Never resumes legacy."""
        self.j.append('transition-a10-containment', code=code, legacy_resume_allowed=False)
        problems = []
        for entry in ENTRIES:
            try:
                binding = self.ingress[entry]
                if binding.observe(binding.scope, timeout=10) != 'blocked':
                    require(binding.block(binding.scope, timeout=30) is True, 'a10-contain-ingress')
                require(binding.observe(binding.scope, timeout=10) == 'blocked', 'a10-contain-ingress')
            except Exception:  # noqa: BLE001 - contenção é best effort e registra o problema
                problems.append('ingress:' + entry)
        try:
            ids = self.candidate.project_ids()
            try:
                states = self.candidate.inspect(ids) if ids else {}
                by_role = {state['service']: ident for ident, state in states.items()}
            except Exception:  # noqa: BLE001 - contenção é best effort e registra o problema
                by_role = {}
            ordered = [by_role[r] for r in CONTAIN_ORDER if r in by_role]
            ordered += [i for i in ids if i not in ordered]
            for ident in ordered:
                try:
                    self.candidate.stop(ident)
                except Exception:  # noqa: BLE001 - contenção é best effort e registra o problema
                    problems.append('stop')
            states = self.candidate.inspect(ids) if ids else {}
            if any(state['running'] for state in states.values()):
                problems.append('running')
        except Exception:  # noqa: BLE001 - contenção é best effort e registra o problema
            problems.append('inspect')
        self.j.append('transition-a10-contained', code=code, complete=not problems, problems=sorted(problems),
                      ingress_blocked=not any(p.startswith('ingress:') for p in problems),
                      gates_rewritten=False, legacy_resume_allowed=False)

    # -- writers binding -----------------------------------------------------------------------------
    def _a10_writers(self, states):
        """Declared candidate IDs after the A10 recreation: exactly those with a start receipt."""
        recreated = self.j.last('transition-done', 'a10:recreate')
        require(recreated is not None, 'a10-recreate-ambiguous')
        ids = recreated['ids']
        snapshot = self.j.last('transition-gate-snapshot')
        restore = snapshot['restore']
        contained = self.j.last('transition-a10-containment') is not None
        declared = []
        for role in ROLES:
            state = states[ids[role]]
            check_identity(self.candidate.spec, role, state, restore[role])
            done = self.j.last('transition-done', 'a10:start:' + role)
            require(not self._open('a10:start:' + role), 'a10-start-ambiguous')
            if contained:
                require(not state['running'], 'a10-contained-running')
            elif done is not None:
                check_restored_running(state, done['started'])
                declared.append(ids[role])
            else:
                require(not state['running'], 'candidate-premature-running')
        return tuple(declared)

    def _a10_recovery(self):
        return a10_recovery_state(self.j)


def a10_recovery_state(journal):
    """Objective A10 phase from journal events alone; None if A10 never started."""
    if journal.last('transition-a10-contained') is not None:
        return 'a10-contained' if journal.last('transition-a10-contained')['complete'] else 'a10-containment-incomplete'
    if journal.last('transition-a10-containment') is not None:
        return 'a10-containment-incomplete'
    if journal.last('transition-a10-complete') is not None:
        return 'a10-complete'
    if any(e['step'].startswith('a10:') for e in journal.find('transition-intent')):
        return 'a10-partial'
    return None


A10_PROCEDURES = {
    'a10-partial': 'replay a10(token): receipted steps re-verified; an interrupted step is adopted only on exact '
                   'proof, otherwise it refuses as ambiguous without effect',
    'a10-complete': 'done: workers running with the pre-window gates, ingress open; replay only re-verifies',
    'a10-contained': 'stop: ingress blocked, every candidate container stopped (restart=no), gates not rewritten; '
                     'no legacy, no automatic reopen; fix forward by a new decision',
    'a10-containment-incomplete': 'urgent human action: block both ingress entries and stop the candidate '
                                  'cron, broadcast, queue and backend by hand; no legacy, no reopen',
}
