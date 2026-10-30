"""First-transition orchestration over injected ports, up to A9 (never A10).

Sequence (one durable journal, shared with ObservedHostContract):

1. fresh read-only database baseline equal to the configured expectation;
2. ObservedHostContract.contain(): ingress blocked, four legacy restart=no,
   SIGTERM, clean exit 0;
3. two consecutive bounded fresh observations, each with the host still
   contained and zero writing sessions and zero active leases in the database;
4. the WINDOW backup, acquired exactly once AFTER quiescence: a durable
   ``transition-backup-request`` (fresh nonce, plan, identity, baseline, config
   and the digest of this run's ``transition-quiescent`` event) is journaled,
   then the injected provider must return a receipt attesting that exact
   request (``request_digest``) plus a new backup with restore and clone
   rehearsal (first_transition_adapter.validate_clone_receipt). An older (A6)
   receipt cannot attest it. A request without a receipt is ambiguous and never
   re-issued automatically; a later invocation never reuses that window;
5. final pre-DDL re-check of the stored receipt and of containment/quiescence
   (no second backup call), then the durable irrevocable ``ddl-marker``, which
   binds the window backup id;
6. the 51 pending migrations (43 transactional, 8 CONCURRENTLY) one by one via
   the exact pinned ``backend/scripts/migrate.py`` bytes of the Plan, each with
   a durable intent first; the first failure or doubt stops for good;
7. candidate release layout ``<release_root>/<sha>`` (first_transition_candidate);
8. A9: four candidate containers created held (restart=no, gates closed), ONLY
   the backend started and smoked; consumers proven never started; legacy
   stopped, support preserved and ingress blocked throughout. From its A9
   start the candidate backend is a declared source for the injected writer
   binding (see ``assemble``), never an unknown writer.

Recovery is objective (``recovery()``), never automatic: no undo, no retry of a
destructive operation, no legacy resume once the DDL marker exists. A
pre-DDL legacy resume goes through ObservedHostContract.resume_legacy, whose
driver requires a fresh read-only ledger proof before every effect.

Configuration (``load_config``) holds public values only; secrets reach the
migration child exclusively through its isolated environment. Nothing runs at
import; there is no command-line entry point and no production operation here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import time

from first_transition_adapter import APPLICATION_SHA, EXECUTOR_SHA, ROLES, Plan, digest, validate_clone_receipt
from first_transition_candidate import (CONSUMERS, CandidatePort, CandidateRunner, CandidateSpec, check_backend_running,
                                        check_held, check_identity, write_candidate_release, write_hold_override)
from first_transition_database import (LEASES, DatabaseExpectation, LedgerProof, ReadOnlyDatabase, lease_scope,
                                       require_ddl_free, require_quiet, require_same_database, summary)
from first_transition_host_contract import ObservedHostContract
from first_transition_host_driver import HostManifest, ObservedHostDriver, PopenRunner, _absolute
from first_transition_host_transport import ObservedHostTransport
from initial_transition_files import Journal, no_symlink, read_regular
from initial_transition_ops import Refused, require

CONFIG_SCHEMA = 'igreja12.first-transition-config/1'
CONFIG_KEYS = frozenset({'schema', 'repo', 'state_dir', 'migration_workdir', 'python', 'docker', 'database',
                         'host', 'candidate', 'package_manifest_sha256', 'timeouts'})
TIMEOUTS = dict(migration_s=300, observe_s=10, quiescence_interval_s=5, quiescence_budget_s=60)
SHAPE = (51, 43, 8)  # pending, transactional, CONCURRENTLY
PROCEDURES = {
    'not-started': 'nothing intended: no recovery action',
    'containment-partial': 'replay run(): contain() never re-signals; an unclean exit stays refused for a human',
    'contained-pre-ddl': 'replay run() or resume_legacy(token): fresh ledger proof before every effect',
    'backup-window-used': 'stop: the window backup is never re-requested or reused (pending request = ambiguous); '
                          'resume_legacy(token) with fresh ledger proofs, then a new journal for a later attempt',
    'resume-partial': 'replay resume_legacy(token): receipted roles re-proven, ledger proof per effect',
    'legacy-resumed': 'legacy back with ingress open: start a new journal for any later attempt',
    'ddl-ambiguous': 'stop: no retry, no legacy; inspect ledger/indexes read-only and decide a restore of the WINDOW '
                     'backup bound in the ddl-marker (window_backup_id, never the A6 one) or completion; '
                     'no automatic restore',
    'ddl-failed': 'stop: no retry, no legacy; restore the WINDOW backup bound in the ddl-marker (window_backup_id, '
                  'never the A6 one) or fix forward by a new decision; no automatic restore',
    'post-ddl-failed': 'stop: no legacy; keep ingress blocked and inspect the failure read-only before a decision',
    'candidate-ambiguous': 'stop: no undo; inspect the candidate project read-only, nothing restarted or removed',
    'candidate-failed': 'stop: no undo; consumers stay held, ingress blocked; human decision on the backend',
    'a9-complete': 'hold: backend smoked, consumers held, ingress blocked; A10 needs its own authorization',
}
BACKUP_REQUEST_SCHEMA = 'igreja12.first-transition-window-backup-request/1'
CLONE_FIELDS = ('migrations_verified', 'clone_identity', 'cluster_global_ddl_possible', 'applied', 'final_ledger',
                'concurrent', 'sql_digest', 'final_schema_digest')
PROCESS_ENV = frozenset({'PATH', 'LC_ALL', 'LANG', 'PYTHON_DOTENV_DISABLED', 'MIGRATION_DATABASE_URL', 'PGAPPNAME',
                         'PGCONNECT_TIMEOUT'})


class ProcessRunner:
    """Generic safe runner: allowlisted absolute binaries, constructed env, no shell, output discarded.

    The environment is the only channel for secrets: argv never carries one and
    no output is captured, so nothing can reach logs or exceptions.
    """

    def __init__(self, *, binaries, run=None):
        require(isinstance(binaries, tuple) and binaries and all(_absolute(b) for b in binaries)
                and (run is None or callable(run)), 'process-runner-config')
        self.binaries, self.run = binaries, run

    def __call__(self, argv, *, env, cwd, timeout):
        require(type(argv) is tuple and argv and argv[0] in self.binaries
                and all(type(a) is str and 0 < len(a) <= 4096 and '\x00' not in a for a in argv), 'process-argv')
        require(isinstance(env, dict) and set(env) <= PROCESS_ENV
                and all(type(v) is str and '\x00' not in v for v in env.values()), 'process-env')
        require(_absolute(cwd) and type(timeout) in (int, float) and 0 < timeout <= 3600, 'process-bounds')
        run = self.run or subprocess.run  # resolved per call, never at import/construction
        outcome = None
        try:
            done = run(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       env=dict(env), cwd=cwd, timeout=timeout, close_fds=True, shell=False, check=False)
        except subprocess.TimeoutExpired:
            outcome = 'timeout'
        except Exception:
            outcome = 'process-spawn-failed'
        if outcome == 'timeout':
            raise TimeoutError('process-timeout')
        require(outcome is None and type(getattr(done, 'returncode', None)) is int, outcome or 'process-failed')
        return done.returncode


class MigrationExecutor:
    """One pending migration through the exact pinned migrate.py bytes of the Plan.

    ``python <dir>/scripts/migrate.py apply <name> --yes [--no-transaction]``
    in a fresh exclusive directory under the configured workdir; the database
    URL comes from ``secret()`` straight into the child environment.
    """

    def __init__(self, plan, *, python, workdir, secret, runner, timeout=300):
        require(isinstance(plan, Plan) and plan.application_sha == APPLICATION_SHA
                and plan.executor_sha == EXECUTOR_SHA, 'migration-plan')
        require(_absolute(python) and _absolute(workdir) and callable(secret) and callable(runner)
                and type(timeout) is int and 0 < timeout <= 3600, 'migration-executor-config')
        self.plan, self.python, self.workdir = plan, python, workdir
        self.secret, self.runner, self.timeout = secret, runner, timeout

    @staticmethod
    def command(python, directory, migration):
        return (python, '-I', f'{directory}/scripts/migrate.py', 'apply', migration.name, '--yes',
                *(('--no-transaction',) if migration.concurrent else ()))

    def _materialize(self, index, migration):
        root = no_symlink(Path(self.workdir))
        require(os.path.lexists(root) and stat.S_ISDIR(os.lstat(root).st_mode), 'migration-workdir-missing')
        directory = root / f'{index:02d}-{self.plan.digest[:16]}'
        try:
            directory.mkdir(mode=0o700)  # exclusive: a previous attempt's directory refuses
        except FileExistsError:
            raise Refused('migration-workdir-exists') from None
        (directory / 'scripts').mkdir(mode=0o700)
        (directory / 'migrations').mkdir(mode=0o700)
        for path, data in (('scripts/migrate.py', self.plan.executor), ('migrations/' + migration.name, migration.sql)):
            fd = os.open(directory / path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data)
        return str(directory)

    def apply(self, index, migration):
        require(migration in self.plan.pending and self.plan.pending[index - 1] is migration, 'migration-not-pending')
        directory = self._materialize(index, migration)
        url = self.secret()
        require(isinstance(url, str) and url.startswith('postgresql://') and '\n' not in url, 'migration-secret')
        env = dict(PATH='/usr/bin:/bin', LC_ALL='C', PYTHON_DOTENV_DISABLED='1', MIGRATION_DATABASE_URL=url,
                   PGAPPNAME=f'pastorai-first-transition-{index:02d}', PGCONNECT_TIMEOUT='10')
        return self.runner(self.command(self.python, directory, migration), env=env, cwd=directory,
                           timeout=self.timeout)


class FirstTransition:
    def __init__(self, *, plan, journal, host, database, expected, backup_proof, executor, layout, candidate,
                 config_digest, clock=time.monotonic, sleep=time.sleep, timeouts=None):
        for value, kind, code in ((plan, Plan, 'plan'), (journal, Journal, 'journal'),
                                  (host, ObservedHostContract, 'host'), (database, ReadOnlyDatabase, 'database'),
                                  (expected, DatabaseExpectation, 'expectation'),
                                  (executor, MigrationExecutor, 'executor'), (candidate, CandidatePort, 'candidate')):
            require(isinstance(value, kind), 'transition-' + code + '-missing')
        require(callable(backup_proof), 'transition-backup-missing')
        require(callable(layout), 'transition-layout-missing')
        require(journal.lock_fd is not None and host.j is journal, 'transition-journal')
        require(executor.plan is plan and candidate.spec.sha == plan.application_sha, 'transition-plan-binding')
        pending = plan.pending
        require((len(pending), sum(not m.concurrent for m in pending), sum(m.concurrent for m in pending)) == SHAPE,
                'transition-release-shape')
        require(expected.validated().ledger == plan.baseline, 'transition-expectation-baseline')
        require(isinstance(config_digest, str) and re.fullmatch('[0-9a-f]{64}', config_digest), 'transition-config')
        self.t = {**TIMEOUTS, **(timeouts or {})}
        self.plan, self.j, self.host, self.db, self.expected = plan, journal, host, database, expected
        self.backup_proof, self.executor, self.layout, self.candidate = backup_proof, executor, layout, candidate
        self.config_digest, self.clock, self.sleep = config_digest, clock, sleep

    # -- journal helpers -------------------------------------------------------------------
    def _intent(self, step, **fields):
        return self.j.append('transition-intent', step=step, **fields)

    def _done(self, step, **fields):
        return self.j.append('transition-done', step=step, **fields)

    def _open(self, step):
        """Intent without receipt: the outcome is unknown and never retried automatically."""
        return (self.j.last('transition-intent', step) is not None
                and self.j.last('transition-done', step) is None)

    def _observe(self):
        return self.db.observe(timeout=self.t['observe_s'])

    def _init(self):
        init = self.j.last('transition-init')
        values = dict(plan_digest=self.plan.digest, config_digest=self.config_digest,
                      baseline_digest=self.expected.baseline_digest, application_sha=self.plan.application_sha,
                      executor_sha=self.plan.executor_sha, candidate_image=self.candidate.spec.image)
        if init is None:
            self.j.append('transition-init', production_ready=False, **values)
        else:
            require(all(init.get(k) == v for k, v in values.items()), 'transition-inputs-changed')

    # -- entry points --------------------------------------------------------------------------
    def run(self):
        self._init()
        require(self.j.last('observed-host-intent', 'legacy-resume') is None, 'transition-legacy-resume-started')
        require(self.j.last('transition-failed') is None, 'transition-stopped')  # first failure is final
        try:
            if self.j.last('ddl-marker') is None:
                self._window_unused()
                self._baseline()
                self.host.contain()
                self._quiesce()
                self._backup()
                self._mark_ddl()
            self._migrate()
            self._release_layout()
            return self._a9()
        except BaseException as exc:
            if self.j.last('ddl-marker') is not None:
                self.j.append('transition-failed', code=str(exc) if isinstance(exc, Refused) else 'interrupted',
                              legacy_resume_allowed=False)
            raise

    def resume_legacy(self, confirmation, *, allow_queue_drift=False):
        """Pre-DDL only; the contract and the driver's ledger proof re-check everything."""
        require(self.j.last('ddl-marker') is None and not self.j.find('transition-intent'),
                'post-ddl-resume-forbidden')
        return self.host.resume_legacy(confirmation, allow_queue_drift=allow_queue_drift)

    # -- pre-DDL ---------------------------------------------------------------------------------
    def _baseline(self):
        observation = self._observe()
        require_ddl_free(observation, self.expected)
        if self.j.last('transition-baseline') is None:
            self.j.append('transition-baseline', evidence='database-read-only', **summary(observation))

    def _quiet_observation(self):
        receipt = self.host.assert_contained()
        observation = self._observe()
        require_ddl_free(observation, self.expected)
        require_quiet(observation)
        return receipt['fingerprint'], receipt['queue_digest'], summary(observation)

    def _quiesce(self):
        start = self.clock()
        first = self._quiet_observation()
        self.sleep(self.t['quiescence_interval_s'])
        second = self._quiet_observation()
        require(self.clock() - start <= self.t['quiescence_budget_s'], 'transition-quiescence-unbounded')
        require(first == second, 'transition-quiescence-changed')
        self.j.append('transition-quiescent', observations=2, writing_sessions=0, active_leases=0,
                      host_fingerprint=first[0], queue_digest=first[1], evidence='database-read-only')

    def _window_unused(self):
        """A backup window is used once: a pending request is ambiguous, a receipted one stale."""
        request = self.j.last('transition-backup-request')
        if request is not None:
            receipted = self.j.last('transition-backup') is not None
            raise Refused('transition-backup-window-used' if receipted else 'transition-backup-ambiguous')

    def _backup_request(self):
        quiescent = self.j.last('transition-quiescent')
        require(quiescent is not None, 'transition-not-quiescent')
        return dict(schema=BACKUP_REQUEST_SCHEMA, nonce=secrets.token_hex(32), plan_digest=self.plan.digest,
                    source_identity=self.expected.identity, baseline_digest=self.expected.baseline_digest,
                    config_digest=self.config_digest, quiescence_digest=digest(quiescent))

    def _window_receipt(self, receipt, request_digest):
        """Validated, sanitized copy: only the attested fields, never paths or provider extras."""
        validate_clone_receipt(receipt, self.plan, self.expected.identity, self.expected.baseline_digest)
        require(receipt.get('request_digest') == request_digest, 'transition-backup-unbound')
        require(isinstance(receipt.get('backup_id'), str) and re.fullmatch('[0-9a-f]{64}', receipt['backup_id']),
                'transition-backup-unbound')
        clone = receipt['clone_rehearsal']
        return dict(plan_digest=receipt['plan_digest'], source_identity=receipt['source_identity'],
                    baseline_digest=receipt['baseline_digest'], restore_verified=True,
                    request_digest=request_digest, backup_id=receipt['backup_id'],
                    clone_rehearsal={key: clone[key] for key in CLONE_FIELDS})

    def _backup(self):
        """The window backup, requested exactly once after this run's quiescence."""
        request = self._backup_request()
        request_digest = digest(request)
        self.j.append('transition-backup-request', request=request, request_digest=request_digest)
        try:
            receipt = self.backup_proof(dict(request))
        except Refused:
            raise
        except Exception:
            raise Refused('transition-backup-failed') from None
        require(isinstance(receipt, dict), 'clone-receipt-invalid')
        record = self._window_receipt(receipt, request_digest)
        self.j.append('transition-backup', request_digest=request_digest, receipt=record,
                      receipt_digest=digest(record), backup_id=record['backup_id'], restore_verified=True)

    def _stored_backup(self):
        """Re-validates the journaled receipt against this window; never calls the provider."""
        quiescent, request = self.j.last('transition-quiescent'), self.j.last('transition-backup-request')
        backup = self.j.last('transition-backup')
        require(quiescent is not None, 'transition-not-quiescent')
        require(request is not None and backup is not None and request['seq'] > quiescent['seq']
                and backup['seq'] > request['seq'] and request['request_digest'] == digest(request['request'])
                and request['request']['quiescence_digest'] == digest(quiescent)
                and backup['request_digest'] == request['request_digest'], 'transition-backup-unbound')
        record = self._window_receipt(backup['receipt'], request['request_digest'])
        require(record == backup['receipt'] and digest(record) == backup['receipt_digest'], 'transition-backup-changed')
        return quiescent, backup

    def _mark_ddl(self):
        quiescent, backup = self._stored_backup()
        # Immediately before the irrevocable marker: contained, read-only baseline, still the same quiet window.
        fingerprint, queue, _ = self._quiet_observation()
        require((fingerprint, queue) == (quiescent['host_fingerprint'], quiescent['queue_digest']),
                'transition-quiescence-changed')
        self.j.append('ddl-marker', irrevocable=True, pending=[m.name for m in self.plan.pending],
                      baseline_digest=self.expected.baseline_digest, backup_digest=backup['receipt_digest'],
                      window_backup_id=backup['backup_id'], backup_request_digest=backup['request_digest'],
                      legacy_resume_allowed=False)

    # -- DDL ----------------------------------------------------------------------------------------
    def _migrate(self):
        ledger = list(self.plan.baseline)
        for index, migration in enumerate(self.plan.pending, 1):
            step = 'migration:' + migration.name
            if self.j.last('transition-done', step) is not None:
                ledger.append(migration.name)
                continue
            require(self.j.last('transition-intent', step) is None, 'migration-outcome-ambiguous')
            before = self._observe()
            require_same_database(before, self.expected)
            require(list(before['ledger']) == sorted(ledger), 'migration-ledger-not-prefix')
            require(not before['invalid'] and before['index_builds'] == 0, 'database-ddl-in-progress')
            require_quiet(before)
            self.host.assert_contained()
            self._intent(step, index=index, sql_sha256=migration.sha256, concurrent=migration.concurrent)
            try:
                code = self.executor.apply(index, migration)
            except TimeoutError:
                code = None
            after = self._observe()
            failure = self._migration_failure(migration, code, ledger, after, self.expected)
            if failure is not None:
                # Definite only for a transactional rollback with no trace; anything else is ambiguous.
                definite = (failure == 'migration-failed' and not migration.concurrent
                            and not after['invalid'] and after['index_builds'] == 0)
                self.j.append('transition-migration-failed', step=step, code=failure, definite=definite)
                raise Refused(failure)
            self._done(step, ledger_digest=after['ledger_digest'])
            ledger.append(migration.name)
        final = self._observe()
        require_same_database(final, self.expected)  # before transition-migrated, layout and A9
        require(list(final['ledger']) == sorted(m.name for m in self.plan.migrations), 'final-ledger')
        if self.j.last('transition-migrated') is None:
            self.j.append('transition-migrated', ledger=len(final['ledger']), catalog=final['catalog'])
        else:
            require(self.j.last('transition-migrated')['catalog'] == final['catalog'], 'database-ddl-drift')

    @staticmethod
    def _migration_failure(migration, code, ledger, after, expected):
        # A ledger read from another (or not read-only/visible) database proves nothing: ambiguous.
        try:
            require_same_database(after, expected)
        except Refused as exc:
            return str(exc)
        applied = list(after['ledger']) == sorted([*ledger, migration.name])
        if code is None:
            return 'migration-timeout'
        if code != 0:
            return 'migration-ambiguous-ledger-without-success' if applied else 'migration-failed'
        if not applied:
            return 'migration-ambiguous-exit0-no-ledger'
        if after['invalid'] or after['index_builds'] or not set(migration.indexes) <= set(after['indexes']):
            return 'migration-index-invalid'
        return None

    def _release_layout(self):
        if self.j.last('transition-done', 'layout') is None:
            self._intent('layout')
        files = self.layout()  # exclusive or byte-for-byte verification, on every invocation
        if self.j.last('transition-done', 'layout') is None:
            self._done('layout', files=files)

    # -- A9 ----------------------------------------------------------------------------------------
    def _candidate_states(self, ids):
        states = self.candidate.inspect(tuple(ids[r] for r in ROLES))
        result = {role: states[ids[role]] for role in ROLES}
        for role, state in result.items():
            check_identity(self.candidate.spec, role, state)
        return result

    def _held(self, ids, created, backend_started):
        """Consumers never started, legacy contained, support preserved, ingress blocked."""
        states = self._candidate_states(ids)
        for role in CONSUMERS:
            check_held(states[role], created[role])
        if backend_started is None:
            check_held(states['backend'], created['backend'])
        else:
            check_backend_running(states['backend'], backend_started)
        self.host.assert_contained()
        return states

    def _a9(self):
        created = self.j.last('transition-done', 'a9:create')
        if created is None:
            require(not self._open('a9:create'), 'candidate-create-ambiguous')
            self.host.assert_contained()
            require(self.candidate.project_ids() == (), 'candidate-project-not-empty')
            write_hold_override(self.candidate.spec)
            self._intent('a9:create', project=self.candidate.spec.project)
            self.candidate.create_held()
            found = self.candidate.project_ids()
            require(len(found) == 4, 'candidate-create-scope')
            states = self.candidate.inspect(found)
            ids = {state['service']: ident for ident, state in states.items()}
            require(set(ids) == set(ROLES), 'candidate-create-scope')
            for role in ROLES:
                check_identity(self.candidate.spec, role, states[ids[role]])
                check_held(states[ids[role]])
            created = self._done('a9:create', ids=ids, created={
                role: dict(started=states[ids[role]]['started'], restart_count=states[ids[role]]['restart_count'])
                for role in ROLES})
        ids, snapshot = created['ids'], created['created']
        require(self.candidate.project_ids() == tuple(sorted(ids.values())), 'candidate-project-changed')
        started = self.j.last('transition-done', 'a9:start-backend')
        if started is None:
            require(not self._open('a9:start-backend'), 'candidate-start-ambiguous')
            self._held(ids, snapshot, None)
            self._intent('a9:start-backend', id=ids['backend'])
            self.candidate.start_backend(ids['backend'])
            state = self._candidate_states(ids)['backend']
            check_backend_running(state)
            started = self._done('a9:start-backend', started=state['started'])
        self._held(ids, snapshot, started['started'])
        smoke = self.candidate.smoke(ids['backend'])  # fresh read-only probe on every invocation
        self._held(ids, snapshot, started['started'])
        if self.j.last('transition-a9-complete') is None:
            self.j.append('transition-a9-complete', smoke=smoke, consumers='held', ingress_blocked=True,
                          a10='not-implemented')
        return dict(status='a9-backend-smoked', smoke=smoke, consumers='held', ingress_blocked=True,
                    legacy_resume_allowed=False, a10='not-implemented', production_ready=False)

    # -- recovery --------------------------------------------------------------------------------
    def recovery(self):
        """Objective classification of the journal; never performs an action."""
        j = self.j
        open_steps = [e['step'] for e in j.find('transition-intent') if self._open(e['step'])]
        failed = j.last('transition-failed')
        if j.last('transition-a9-complete') is not None and failed is None:
            state = 'a9-complete'
        elif j.last('ddl-marker') is not None:
            migrations = [s for s in open_steps if s.startswith('migration:')]
            if migrations:
                outcome = j.last('transition-migration-failed', migrations[-1])
                state = 'ddl-failed' if outcome is not None and outcome['definite'] is True else 'ddl-ambiguous'
            elif any(s.startswith('a9:') for s in open_steps):
                state = 'candidate-ambiguous'
            elif j.last('transition-done', 'layout') is not None and failed is not None:
                state = 'candidate-failed'
            else:
                state = 'post-ddl-failed'
        elif j.last('observed-host-resumed') is not None:
            state = 'legacy-resumed'
        elif j.last('observed-host-intent', 'legacy-resume') is not None:
            state = 'resume-partial'
        elif j.last('transition-backup-request') is not None:
            state = 'backup-window-used'
        elif j.last('observed-host-contained') is not None:
            state = 'contained-pre-ddl'
        elif j.find('observed-host-intent'):
            state = 'containment-partial'
        else:
            state = 'not-started'
        marker = j.last('ddl-marker')
        return dict(state=state, procedure=PROCEDURES[state], open_steps=open_steps,
                    legacy_resume_allowed=state in ('contained-pre-ddl', 'backup-window-used', 'resume-partial'),
                    window_backup_id=None if marker is None else marker.get('window_backup_id'),
                    automatic_undo=False, destructive_retry=False, automatic_restore=False)


# -- configuration ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class FirstTransitionConfig:
    repo: str
    state_dir: str
    migration_workdir: str
    python: str
    docker: tuple
    catalog: str
    identity: str
    lease_columns: tuple
    observer_applications: tuple
    manifest: HostManifest
    candidate: CandidateSpec
    package_manifest_sha256: str
    timeouts: tuple
    digest: str


def parse_config(data):
    """Public values only: unknown keys (a password, a URL) refuse."""
    require(isinstance(data, dict) and set(data) == CONFIG_KEYS and data['schema'] == CONFIG_SCHEMA, 'config-keys')
    docker, database, candidate, timeouts = data['docker'], data['database'], data['candidate'], data['timeouts']
    require(isinstance(docker, dict) and set(docker) == {'binary', 'endpoint', 'config_dir'}, 'config-docker')
    require(isinstance(database, dict) and set(database) == {
        'identity', 'catalog', 'lease_columns', 'observer_applications'}, 'config-database')
    require(isinstance(candidate, dict) and set(candidate) == {
        'sha', 'image', 'project', 'containers', 'network_name', 'release_root', 'hold_override', 'env_file',
        'smoke_seconds'}, 'config-candidate')
    require(isinstance(timeouts, dict) and set(timeouts) <= set(TIMEOUTS)
            and all(type(v) is int and 0 < v <= 3600 for v in timeouts.values())
            and timeouts.get('observe_s', TIMEOUTS['observe_s']) <= 30, 'config-timeouts')
    require(all(_absolute(data[k]) for k in ('repo', 'state_dir', 'migration_workdir', 'python')), 'config-paths')
    require(isinstance(database['lease_columns'], list) and isinstance(database['observer_applications'], list)
            and all(isinstance(p, list) for p in database['lease_columns']), 'config-database')
    # An empty list means exactly the mandatory LEASES; a non-empty one may add columns, never drop one.
    lease_columns = tuple(tuple(p) for p in database['lease_columns']) or LEASES
    try:
        lease_scope(lease_columns)
    except Refused:
        raise Refused('config-database-leases') from None
    manifest = HostManifest.from_dict(data['host'])
    containers = candidate['containers']
    require(isinstance(containers, dict) and set(containers) == set(ROLES), 'config-candidate')
    spec = CandidateSpec(sha=candidate['sha'], image=candidate['image'], project=candidate['project'],
                         containers=tuple((r, containers[r]) for r in ROLES), network_id=manifest.network_id,
                         network_name=candidate['network_name'], release_root=candidate['release_root'],
                         hold_override=candidate['hold_override'], env_file=candidate['env_file'],
                         daemon_id=manifest.daemon_id, smoke_seconds=candidate['smoke_seconds']).validated()
    require(spec.sha == APPLICATION_SHA, 'config-candidate-sha')
    require(isinstance(data['package_manifest_sha256'], str)
            and re.fullmatch('[0-9a-f]{64}', data['package_manifest_sha256']), 'config-package')
    canonical = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
    return FirstTransitionConfig(
        repo=data['repo'], state_dir=data['state_dir'], migration_workdir=data['migration_workdir'],
        python=data['python'], docker=(docker['binary'], docker['endpoint'], docker['config_dir']),
        catalog=database['catalog'], identity=database['identity'],
        lease_columns=lease_columns,
        observer_applications=tuple(database['observer_applications']), manifest=manifest, candidate=spec,
        package_manifest_sha256=data['package_manifest_sha256'], timeouts=tuple(sorted(timeouts.items())),
        digest=hashlib.sha256(canonical).hexdigest())


def load_config(path):
    try:
        data = json.loads(read_regular(path, 64 * 1024))
    except ValueError:
        raise Refused('config-invalid-json') from None
    return parse_config(data)


def assemble(config, *, plan, journal, connect, secret, ingress, writers, backup_proof, popen=None, run=None,
             clock=time.monotonic, sleep=time.sleep, git=None):
    """Wire real ports from configuration plus injected providers; any absent provider refuses.

    Providers (database connection, secret, ingress/writer bindings, backup
    receipt) are Phase 3 inputs; nothing is contacted while assembling.

    ``writers.observe()`` returns the number of UNKNOWN writers, i.e. writing
    sources that are UNDECLARED. It must be 0 on every observation, from the
    first ``contain()`` baseline (when the four legacy services are still
    running) through A9. Declared sources, never counted at any time:

    * the four legacy roles of the manifest (backend, queue-worker,
      broadcast-worker, cron-worker): their stop is verified separately by the
      host states (restart=no, clean exit 0), not by this binding;
    * this tool's own observer and migration child;
    * from the A9 backend start on only, the candidate backend of
      ``config.candidate`` (its project/container name).

    Anything else (a candidate consumer, another container or a foreign client)
    counts and refuses. Independently of this binding, zero writing sessions
    and zero active leases in PostgreSQL are required before the DDL marker
    and before every migration (``require_quiet``).

    ``backup_proof(request)`` receives the journaled window request (see the
    module docstring, step 4) and must return a receipt for a NEW backup made
    after that request, carrying ``request_digest`` (``digest(request)``), a
    64-hex ``backup_id`` and the restore/clone rehearsal fields; it is called
    once per window and never retried.
    """
    require(isinstance(config, FirstTransitionConfig), 'transition-config')
    for value, code in ((connect, 'database'), (secret, 'secret'), (backup_proof, 'backup')):
        require(callable(value), 'transition-' + code + '-missing')
    require(ingress is not None and writers is not None, 'transition-host-bindings-missing')
    binary, endpoint, config_dir = config.docker
    database = ReadOnlyDatabase(connect, lease_columns=config.lease_columns,
                                observer_applications=config.observer_applications)
    expected = DatabaseExpectation(config.identity, plan.baseline, config.catalog).validated()
    proof = LedgerProof(database, expected, scope=config.manifest.digest)
    driver = ObservedHostDriver(config.manifest, ingress=ingress, writers=writers, ledger_proof=proof,
                                runner=PopenRunner(docker_binary=binary, endpoint=endpoint, config_dir=config_dir,
                                                   popen=popen, resume=True))
    host = ObservedHostContract(ObservedHostTransport(driver, **config.manifest.transport_scope()), journal)
    candidate = CandidatePort(config.candidate, runner=CandidateRunner(
        config.candidate, docker_binary=binary, endpoint=endpoint, config_dir=config_dir, popen=popen))
    executor = MigrationExecutor(plan, python=config.python, workdir=config.migration_workdir, secret=secret,
                                 runner=ProcessRunner(binaries=(config.python,), run=run),
                                 timeout=dict(config.timeouts).get('migration_s', TIMEOUTS['migration_s']))
    migrations = [m.name for m in plan.migrations]

    def layout():
        return write_candidate_release(config.repo, config.candidate, config.manifest, migrations=migrations,
                                       package_manifest_sha256=config.package_manifest_sha256, git=git)
    return FirstTransition(plan=plan, journal=journal, host=host, database=database, expected=expected,
                           backup_proof=backup_proof, executor=executor, layout=layout, candidate=candidate,
                           config_digest=config.digest, clock=clock, sleep=sleep, timeouts=dict(config.timeouts))
