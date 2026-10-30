"""Integrated first transition: real orchestrator, contract, transport, driver, database observer,
migration executor, layout writer and candidate port over fixtures only.

Simulated: Docker (legacy + candidate runners), PostgreSQL (DB-API fake), the
migration child (fake ``subprocess.run`` behind ProcessRunner) and ingress/writer
bindings. Git blobs of the pinned SHAs are read once per module, before the
process/network guard is installed; nothing else touches the host.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from first_transition_adapter import (APPLICATION_SHA, EXECUTOR_SHA, ROLES, LocalTransition, Refused, digest,
                                      prepare)
from first_transition_candidate import (CANDIDATE_TEMPLATE, CLOSED_GATES, HOLD_OVERRIDE, ZERO_STARTED,
                                        CandidatePort, CandidateRunner, CandidateSpec, write_candidate_release)
from first_transition_database import LedgerProof, ReadOnlyDatabase
from first_transition_host_contract import ObservedHostContract
from first_transition_host_driver import INFO_ARGV, ObservedHostDriver
from first_transition_host_transport import ObservedHostTransport, host_command
from first_transition_orchestrator import (PROCEDURES, FirstTransition, MigrationExecutor, ProcessRunner, assemble,
                                           load_config, parse_config)
from initial_transition_files import Journal, git_tree
import package_backend_release
from test_first_transition_database import FakePg
from first_transition_host_driver import ENTRIES
from test_first_transition_host_driver import (DAEMON, LEGACY, NET_NAME, NETWORK, SUPPORT, FakeIngress, FakeWriters,
                                               Rig)

ROOT = Path(__file__).resolve().parents[2]
PYTHON = '/usr/bin/python3'
SECRET_URL = 'postgresql://owner:SENTINEL-MIGRATION-SECRET@db.example.invalid/app'
IMAGE = 'sha256:' + '9' * 64
CANDIDATE_IDS = {role: ch * 64 for role, ch in zip(ROLES, 'abcd')}
NAMES = {role: 'release_' + role.replace('-', '_') for role in ROLES}
EXAMPLE = Path(__file__).resolve().parents[1] / 'first-transition.example.json'


class RecordingGit:
    """Real ``git`` once (module setup), then served from the recording: no process per test."""

    def __init__(self):
        self.answers = {}

    def __call__(self, args):
        key = tuple(args)
        if key not in self.answers:
            done = subprocess.run(['git', '-C', str(ROOT), *args], capture_output=True, timeout=60)
            assert done.returncode == 0
            self.answers[key] = done.stdout
        return self.answers[key]


@pytest.fixture(scope='module')
def pinned():
    git = RecordingGit()
    plan = prepare(ROOT)
    files = package_backend_release.source_files(ROOT, APPLICATION_SHA, git)
    package = digest_bytes(package_backend_release.release_manifest(APPLICATION_SHA, files))
    return plan, git, package


def digest_bytes(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(autouse=True)
def no_real_processes_or_network(monkeypatch):
    hits = []

    def forbid(label):
        def blocked(*_args, **_kwargs):
            hits.append(label)
            raise AssertionError('real process/network forbidden: ' + label)
        return blocked
    for module, names in ((subprocess, ('Popen', 'run', 'call', 'check_call', 'check_output')),
                          (os, ('system', 'popen', 'execv', 'execve', 'fork', 'posix_spawn')),
                          (socket, ('socket', 'create_connection', 'getaddrinfo'))):
        for name in names:
            monkeypatch.setattr(module, name, forbid(module.__name__ + '.' + name))
    yield
    assert hits == []


class Done:
    def __init__(self, returncode):
        self.returncode = returncode


class FakeMigrate:
    """Stands in for ``subprocess.run`` of the pinned migrate.py; applies to FakePg."""

    def __init__(self, pg, plan):
        self.pg, self.plan, self.applied, self.faults, self.argv = pg, plan, [], {}, []
        self.after = None

    def __call__(self, argv, *, stdin, stdout, stderr, env, cwd, timeout, close_fds, shell, check):
        assert stdin is stdout is stderr is subprocess.DEVNULL and shell is False and close_fds is True
        assert argv[:2] == [PYTHON, '-I'] and argv[2] == cwd + '/scripts/migrate.py' and argv[3:4] == ['apply']
        name = argv[4]
        migration = next(m for m in self.plan.pending if m.name == name)
        assert argv[5:] == ['--yes', *(['--no-transaction'] if migration.concurrent else [])]
        assert Path(argv[2]).read_bytes() == self.plan.executor
        assert (Path(cwd) / 'migrations' / name).read_bytes() == migration.sql
        assert sorted(os.listdir(Path(cwd) / 'migrations')) == [name]
        assert env['MIGRATION_DATABASE_URL'] == SECRET_URL and SECRET_URL not in ' '.join(argv)
        self.applied.append(name)
        self.argv.append(argv)
        mode = self.faults.get(name)
        if mode == 'timeout':
            raise subprocess.TimeoutExpired(argv, timeout)
        if mode == 'fail':
            return Done(1)
        if mode == 'exit0-no-ledger':
            return Done(0)
        if mode == 'crash':
            raise KeyboardInterrupt
        self.pg.ledger.append(name)
        self.pg.indexes.extend(migration.indexes)
        if mode == 'invalid-index':
            self.pg.invalid.append(migration.indexes[0])
        if self.after:
            self.after(name)
        return Done(1 if mode == 'fail-with-ledger' else 0)


class FakeCandidateDocker:
    """Candidate-side Docker CLI answers for exactly the argv CandidatePort builds."""

    def __init__(self, spec):
        self.spec, self.calls, self.containers = spec, [], {}
        self.gates = [f'{k}={v}' for k, v in CLOSED_GATES.items()]
        self.hold_applied, self.autostart, self.start_also = True, set(), set()
        self.smoke = dict(health=200, health_ok=True, ready=200, required_ok=True, ready_status='degraded')
        self.on_create = self.on_start = None
        self.starts = 0

    def __call__(self, argv, *, timeout, max_output):
        assert type(argv) is tuple and 0 < timeout <= 60
        self.calls.append(argv)
        spec = self.spec
        if argv == INFO_ARGV:
            return 0, (json.dumps(DAEMON) + '\n').encode()
        if argv == spec.compose_argv():
            for role in ROLES:
                self.containers[CANDIDATE_IDS[role]] = dict(
                    name=spec.names()[role], service=role, status='created', running=False, started=ZERO_STARTED,
                    restarts=0, policy='no' if self.hold_applied else 'always', env=list(self.gates))
            for role in self.autostart:
                self._run(CANDIDATE_IDS[role])
            if self.on_create:
                self.on_create()
            return 0, b''
        if argv == spec.ps_argv():
            return 0, ''.join(i + '\n' for i in sorted(self.containers)).encode()
        if argv[:6] == ('docker', 'inspect', '--type', 'container', '--format', CANDIDATE_TEMPLATE):
            return 0, ''.join(json.dumps(self._render(i)) + '\n' for i in argv[6:]).encode()
        if argv[:2] == ('docker', 'start'):
            self._run(argv[2])
            for role in self.start_also:
                self._run(CANDIDATE_IDS[role])
            if self.on_start:
                self.on_start()
            return 0, (argv[2] + '\n').encode()
        if argv[:2] == ('docker', 'exec'):
            assert argv == spec.smoke_argv(CANDIDATE_IDS['backend'])
            return 0, (json.dumps(self.smoke) + '\n').encode()
        raise AssertionError('unexpected candidate argv')

    def _run(self, ident):
        self.starts += 1
        self.containers[ident].update(status='running', running=True,
                                      started='2026-10-30T13:00:%02d.000000001Z' % self.starts)

    def _render(self, ident):
        c, spec = self.containers[ident], self.spec
        return ['/' + c['name'], ident, c.get('image', spec.image), c.get('project', spec.project), c['service'],
                spec.sha, c['status'], c['running'],
                False, False, 0, c['started'], None, c['restarts'], c['policy'], NET_NAME, [*c['env'], None],
                [None], [[NET_NAME, [c['service']], spec.network_id], None]]

    def effects(self):
        return [a for a in self.calls if a[:2] == ('docker', 'start') or a[:2] == ('docker', 'compose')]


class World:
    def __init__(self, pinned, tmp_path):
        plan, git, package = pinned
        self.plan, self.tmp = plan, tmp_path
        self.pg = FakePg(plan.baseline)
        self.pg.indexes = []
        self.rig = Rig()
        self.expected = self.pg.expectation()
        self.database = ReadOnlyDatabase(self.pg.connect)
        self.proof = LedgerProof(self.database, self.expected, scope=self.rig.manifest.digest)
        self.driver = ObservedHostDriver(self.rig.manifest, runner=self.rig.docker, ingress=self.rig.ingress,
                                         writers=self.rig.writers, ledger_proof=self.proof)
        self.transport = ObservedHostTransport(self.driver, **self.rig.manifest.transport_scope())
        (tmp_path / 'releases').mkdir()
        (tmp_path / 'work').mkdir()
        (tmp_path / 'state').mkdir()
        self.spec = CandidateSpec(
            sha=APPLICATION_SHA, image=IMAGE, project='pastorai-release', containers=tuple(NAMES.items()),
            network_id=NETWORK, network_name=NET_NAME, release_root=str(tmp_path / 'releases'),
            hold_override=str(tmp_path / 'state' / 'a9-hold.override.yml'),
            env_file='/srv/synthetic-private/backend.conf', daemon_id=DAEMON, smoke_seconds=20)
        self.cdocker = FakeCandidateDocker(self.spec)
        self.migrate = FakeMigrate(self.pg, plan)
        self.layouts = []
        self.backup = self.receipt()
        self.requests = []
        self.on_backup = None
        self.git, self.package = git, package
        self.clock = [0.0]
        self.journal = None

    def receipt(self):
        plan = self.plan
        return dict(plan_digest=plan.digest, source_identity=self.expected.identity,
                    baseline_digest=self.expected.baseline_digest, restore_verified=True,
                    clone_rehearsal=dict(migrations_verified=True, clone_identity='8' * 64,
                                         cluster_global_ddl_possible=True, applied=51, final_ledger=129,
                                         concurrent=8, final_schema_digest='7' * 64,
                                         sql_digest=digest([(m.name, m.sha256) for m in plan.pending])))

    def provide_backup(self, request):
        """Trusted provider: a NEW backup + restore + clone per call (fresh ids), bound to the request."""
        self.requests.append(request)
        if self.on_backup:
            self.on_backup(request)
        if self.backup is None:
            return None
        n = len(self.requests)
        receipt = json.loads(json.dumps(self.backup))
        if isinstance(receipt['clone_rehearsal'].get('clone_identity'), str):  # keep invalid templates invalid
            receipt['clone_rehearsal']['clone_identity'] = format(n, 'x').rjust(64, '8')
        return {'request_digest': digest(request), 'backup_id': format(n, 'x').rjust(64, 'b'),
                'archive_path': '/srv/synthetic-private/window.dump', **receipt}

    def layout(self):
        self.layouts.append(1)
        return write_candidate_release(ROOT, self.spec, self.rig.manifest, package_manifest_sha256=self.package,
                                       migrations=[m.name for m in self.plan.migrations], git=self.git)

    def transition(self, journal=None):
        self.journal = journal or Journal(self.tmp / 'journal').open()
        host = ObservedHostContract(self.transport, self.journal)
        executor = MigrationExecutor(self.plan, python=PYTHON, workdir=str(self.tmp / 'work'),
                                     secret=lambda: SECRET_URL,
                                     runner=ProcessRunner(binaries=(PYTHON,), run=self.migrate))

        def sleep(seconds):
            self.clock[0] += seconds
        return FirstTransition(plan=self.plan, journal=self.journal, host=host, database=self.database,
                               expected=self.expected, backup_proof=self.provide_backup, executor=executor,
                               layout=self.layout, candidate=CandidatePort(self.spec, runner=self.cdocker),
                               config_digest='f' * 64, clock=lambda: self.clock[0], sleep=sleep)

    def legacy_effects(self):
        return self.rig.docker.effects()

    def text(self):
        return (self.tmp / 'journal' / 'journal.jsonl').read_text()

    def assert_legacy_contained(self):
        for ident in LEGACY.values():
            c = self.rig.docker.containers[ident]
            assert c['State']['Running'] is False and c['RestartPolicy'] == 'no'
        for ident in SUPPORT.values():
            c = self.rig.docker.containers[ident]
            assert c['State']['Running'] is True and c['RestartPolicy'] == 'always'
        assert all(i.state == 'blocked' for i in self.rig.ingress.values())

    def consumers_held(self):
        for role in ('queue-worker', 'cron-worker', 'broadcast-worker'):
            c = self.cdocker.containers[CANDIDATE_IDS[role]]
            assert (c['status'], c['running'], c['restarts'], c['started'], c['policy']) == (
                'created', False, 0, ZERO_STARTED, 'no')


@pytest.fixture
def world(pinned, tmp_path):
    w = World(pinned, tmp_path)
    yield w
    if w.journal is not None:
        w.journal.close()


def kinds(journal):
    return [e['kind'] + (':' + e['step'] if 'step' in e else '') for e in journal.events]


# --- happy path ---------------------------------------------------------------------------------

def test_full_a9_sequence_through_real_ports(world):
    transition = world.transition()
    result = transition.run()
    assert result == dict(status='a9-backend-smoked', smoke=dict(health=200, ready=200, ready_status='degraded'),
                          consumers='held', ingress_blocked=True, legacy_resume_allowed=False,
                          a10='not-implemented', production_ready=False)
    j = world.journal
    order = kinds(j)
    marker = order.index('ddl-marker')
    assert order.index('observed-host-contained') < order.index('transition-quiescent') < order.index(
        'transition-backup') < marker < order.index('transition-intent:migration:' + world.plan.pending[0].name)
    assert j.last('transition-quiescent')['observations'] == 2 and world.pg.connections >= 4
    # 51 migrations one by one in plan order, 8 without transaction, exact pinned executor bytes.
    assert world.migrate.applied == [m.name for m in world.plan.pending]
    assert sum('--no-transaction' in a for a in world.migrate.argv) == 8
    assert sorted(world.pg.ledger) == sorted(m.name for m in world.plan.migrations)
    for m in world.plan.pending:
        step = 'migration:' + m.name
        assert order.index('transition-intent:' + step) < order.index('transition-done:' + step)
    # Legacy contained throughout, never resumed; support untouched; ingress never opened.
    assert world.legacy_effects() == [host_command(op, LEGACY[role]) for role in ROLES
                                      for op in ('restart-no', 'term', 'wait')]
    world.assert_legacy_contained()
    assert all(i.blocks == 1 for i in world.rig.ingress.values())
    # A9: one held creation, only backend started, consumers created/never started/restart=no.
    effects = world.cdocker.effects()
    assert effects == [world.spec.compose_argv(), ('docker', 'start', CANDIDATE_IDS['backend'])]
    assert '--no-start' in effects[0] and '--no-deps' in effects[0] and world.spec.hold_override in effects[0]
    assert Path(world.spec.hold_override).read_text() == HOLD_OVERRIDE
    world.consumers_held()
    backend = world.cdocker.containers[CANDIDATE_IDS['backend']]
    assert backend['running'] and backend['policy'] == 'no' and backend['restarts'] == 0
    # Layout written under the configured root with the topology contract.
    release = world.tmp / 'releases' / APPLICATION_SHA / 'deploy'
    topology = json.loads((release / 'release-topology.json').read_text())
    assert topology['project'] == 'pastorai-release' and topology['reserved_legacy'] == LEGACY
    assert topology['network'] == dict(name=NET_NAME, id=NETWORK)
    assert not (release / '.env').exists()
    text = world.text()
    assert 'SENTINEL' not in text and 'postgresql://' not in text
    assert transition.recovery()['state'] == 'a9-complete'


def test_replay_after_a9_re_proves_and_repeats_no_effect(world):
    world.transition().run()
    world.journal.close()
    effects = (list(world.legacy_effects()), list(world.cdocker.effects()), list(world.migrate.applied))
    smokes = sum(1 for a in world.cdocker.calls if a[:2] == ('docker', 'exec'))
    result = world.transition().run()
    assert result['status'] == 'a9-backend-smoked'
    assert (world.legacy_effects(), world.cdocker.effects(), world.migrate.applied) == effects
    assert sum(1 for a in world.cdocker.calls if a[:2] == ('docker', 'exec')) == smokes + 1
    assert len(world.layouts) == 2  # verified byte for byte, not rewritten


# --- pre-DDL refusals ------------------------------------------------------------------------------

def test_baseline_drift_refuses_before_any_host_effect(world):
    world.pg.ledger.append(world.plan.pending[0].name)
    transition = world.transition()
    with pytest.raises(Refused, match='^database-ledger-drift$'):
        transition.run()
    assert world.legacy_effects() == [] and world.migrate.applied == []
    assert transition.recovery()['state'] == 'not-started'


@pytest.mark.parametrize('fault, code', [
    ('writer', 'database-writing-session'), ('lease', 'database-active-lease'), ('ddl', 'database-ddl-drift'),
])
def test_quiescence_needs_two_consecutive_quiet_observations(world, fault, code):
    def change():
        if fault == 'writer':
            world.pg.writers = 1
        elif fault == 'lease':
            world.pg.leases['broadcast_entregas'] = 1
        else:
            world.pg.extra_ddl.append('rogue_table')
    transition = world.transition()
    original = transition.sleep
    transition.sleep = lambda seconds: (original(seconds), change())
    with pytest.raises(Refused, match='^' + code + '$'):
        transition.run()
    j = world.journal
    assert j.last('ddl-marker') is None and j.last('transition-quiescent') is None
    assert world.migrate.applied == [] and world.cdocker.calls == []
    recovery = transition.recovery()
    assert recovery['state'] == 'contained-pre-ddl' and recovery['legacy_resume_allowed'] is True


def test_unbounded_quiescence_is_refused(world):
    transition = world.transition()
    transition.t['quiescence_budget_s'] = 3
    with pytest.raises(Refused, match='^transition-quiescence-unbounded$'):
        transition.run()
    assert world.journal.last('ddl-marker') is None


@pytest.mark.parametrize('change', [
    lambda r: r.update(plan_digest='0' * 64), lambda r: r['clone_rehearsal'].update(applied=50),
    lambda r: r.update(restore_verified=False), lambda r: r.update(source_identity='0' * 64),
    lambda r: r['clone_rehearsal'].update(clone_identity=None),
])
def test_invalid_backup_proof_refuses_before_the_ddl_marker(world, change):
    change(world.backup)
    transition = world.transition()
    with pytest.raises(Refused, match='^clone-receipt-invalid$'):
        transition.run()
    assert world.journal.last('ddl-marker') is None and world.migrate.applied == []


# --- window backup: once, after quiescence, bound to the exact request ---------------------

def test_window_backup_is_requested_once_after_quiescence_and_bound_in_the_marker(world):
    transition = world.transition()
    transition.run()
    j = world.journal
    assert len(world.requests) == 1  # the provider makes a new clone id per call, yet runs once
    request, quiescent = j.last('transition-backup-request'), j.last('transition-quiescent')
    assert world.requests[0] == request['request'] and request['seq'] > quiescent['seq']
    assert request['request']['quiescence_digest'] == digest(quiescent)
    assert request['request']['plan_digest'] == world.plan.digest and len(request['request']['nonce']) == 64
    backup, marker = j.last('transition-backup'), j.last('ddl-marker')
    assert backup['receipt']['request_digest'] == request['request_digest'] == digest(world.requests[0])
    assert marker['window_backup_id'] == backup['backup_id'] == 'b' * 63 + '1'
    assert marker['backup_digest'] == backup['receipt_digest'] == digest(backup['receipt'])
    assert 'archive_path' not in backup['receipt'] and 'synthetic-private' not in world.text()
    recovery = transition.recovery()
    assert recovery['window_backup_id'] == marker['window_backup_id'] and recovery['automatic_restore'] is False
    assert 'A6' not in PROCEDURES['ddl-failed'].replace('never the A6', '')
    assert 'window_backup_id' in PROCEDURES['ddl-failed'] and 'window_backup_id' in PROCEDURES['ddl-ambiguous']


def a6_receipt(world):
    """A valid-looking older receipt: same plan/identity/schema baseline, made before this window."""
    return {'request_digest': digest(dict(schema='a6', nonce='0' * 64)), 'backup_id': 'a' * 64,
            **json.loads(json.dumps(world.backup))}


@pytest.mark.parametrize('stale', ['a6', 'no-request', 'other-nonce', 'other-quiescence', 'no-backup-id'])
def test_stale_or_foreign_window_receipt_is_refused_with_zero_ddl(world, stale):
    def provider(request):
        world.requests.append(request)
        if stale == 'a6':
            return a6_receipt(world)
        receipt = {'request_digest': digest(request), 'backup_id': 'c' * 64, **json.loads(json.dumps(world.backup))}
        if stale == 'no-request':
            receipt.pop('request_digest')
        elif stale == 'other-nonce':
            receipt['request_digest'] = digest({**request, 'nonce': '1' * 64})
        elif stale == 'other-quiescence':
            receipt['request_digest'] = digest({**request, 'quiescence_digest': '2' * 64})
        else:
            receipt.pop('backup_id')
        return receipt
    transition = world.transition()
    transition.backup_proof = provider
    with pytest.raises(Refused, match='^transition-backup-unbound$'):
        transition.run()
    j = world.journal
    assert j.last('ddl-marker') is None and j.last('transition-backup') is None
    assert world.migrate.applied == [] and world.cdocker.calls == [] and len(world.requests) == 1
    assert transition.recovery()['state'] == 'backup-window-used'


@pytest.mark.parametrize('when', ['pending', 'receipted'])
def test_interrupted_window_is_never_reacquired_or_reused(world, when):
    transition = world.transition()
    if when == 'pending':
        world.on_backup = lambda _request: (_ for _ in ()).throw(KeyboardInterrupt)
    else:
        original = world.journal.append

        def append(kind, **fields):
            if kind == 'ddl-marker':
                raise KeyboardInterrupt  # dies after the receipt, before the marker
            return original(kind, **fields)
        world.journal.append = append
    with pytest.raises(KeyboardInterrupt):
        transition.run()
    world.journal.close()
    world.on_backup = None
    effects, connections = list(world.legacy_effects()), world.pg.connections
    replay = world.transition()
    code = 'transition-backup-ambiguous' if when == 'pending' else 'transition-backup-window-used'
    with pytest.raises(Refused, match='^' + code + '$'):
        replay.run()
    # Refused before any observation or effect: no second request, no stale quiescence reused.
    assert len(world.requests) == 1 and world.pg.connections == connections
    assert world.legacy_effects() == effects and world.journal.last('ddl-marker') is None
    assert len(world.journal.find('transition-backup-request')) == 1 and world.migrate.applied == []
    recovery = replay.recovery()
    assert recovery['state'] == 'backup-window-used' and recovery['legacy_resume_allowed'] is True
    assert replay.resume_legacy(replay.host.resume_token())['status'] == 'legacy-resumed'


def test_tampered_stored_receipt_or_changed_window_blocks_the_marker(world):
    transition = world.transition()
    original = transition._mark_ddl

    def tamper():
        world.journal.last('transition-backup')['receipt']['backup_id'] = 'd' * 64
        return original()
    transition._mark_ddl = tamper
    with pytest.raises(Refused, match='^transition-backup-changed$'):
        transition.run()
    assert world.journal.last('ddl-marker') is None and world.migrate.applied == [] and len(world.requests) == 1


def test_queue_change_after_the_window_backup_blocks_the_marker(world):
    transition = world.transition()
    world.on_backup = lambda _request: world.rig.docker.redis.update({'pastorai:webhooks': ('list', 9)})
    with pytest.raises(Refused, match='^observed-host-queue-drift$'):
        transition.run()
    assert world.journal.last('ddl-marker') is None and world.migrate.applied == [] and len(world.requests) == 1


# --- writer binding semantics: undeclared sources only ----------------------------------------

class DeclaredSourceWriters:
    """Realistic binding: lists writing sources and counts only UNDECLARED ones."""

    def __init__(self, world):
        self.world, self.extra = world, []
        self.scope = world.rig.manifest.digest

    def sources(self):
        legacy = [('legacy', i) for i in LEGACY.values() if self.world.rig.docker.containers[i]['State']['Running']]
        candidate = [('candidate', i) for i, c in self.world.cdocker.containers.items() if c['running']]
        return legacy + candidate + self.extra

    def declared(self, source):
        kind, ident = source
        journal = self.world.journal
        backend_started = journal is not None and journal.last('transition-intent', 'a9:start-backend') is not None
        return (kind == 'legacy' and ident in LEGACY.values()
                or kind == 'candidate' and ident == CANDIDATE_IDS['backend'] and backend_started)

    def observe(self, scope, *, timeout):
        assert scope == self.scope and timeout > 0
        return sum(not self.declared(source) for source in self.sources())


def _declared_writers(world):
    binding = DeclaredSourceWriters(world)
    world.rig.writers.observe = binding.observe  # same bound object; only its observation changes
    return binding


def test_realistic_writer_binding_accepts_four_running_legacy_and_reaches_a9(world):
    binding = _declared_writers(world)
    assert len(binding.sources()) == 4  # the four declared legacy roles are running at the baseline
    result = world.transition().run()
    assert result['status'] == 'a9-backend-smoked'
    assert world.journal.last('observed-host-init') is not None
    assert binding.sources() == [('candidate', CANDIDATE_IDS['backend'])]


@pytest.mark.parametrize('when', ['baseline', 'a9'])
def test_realistic_writer_binding_refuses_an_unexpected_fifth_writer(world, when):
    binding = _declared_writers(world)
    if when == 'baseline':
        binding.extra.append(('foreign', 'f' * 64))
    else:
        world.cdocker.on_start = lambda: binding.extra.append(('foreign', 'f' * 64))
    transition = world.transition()
    with pytest.raises(Refused, match='^observed-host-unknown-writer$'):
        transition.run()
    if when == 'baseline':
        assert world.journal.last('observed-host-init') is None and world.legacy_effects() == []
    else:
        assert world.journal.last('transition-a9-complete') is None
        assert world.journal.last('transition-failed')['code'] == 'observed-host-unknown-writer'


def test_pre_ddl_failure_allows_legacy_resume_with_fresh_ledger_proofs(world):
    world.backup = None
    transition = world.transition()
    with pytest.raises(Refused, match='^clone-receipt-invalid$'):
        transition.run()
    proofs = world.pg.connections
    result = transition.resume_legacy(transition.host.resume_token())
    assert result['status'] == 'legacy-resumed'
    assert world.pg.connections - proofs >= 9  # one read-only proof per resume effect, plus observations
    assert all(i.state == 'open' for i in world.rig.ingress.values())
    assert transition.recovery()['state'] == 'legacy-resumed'
    with pytest.raises(Refused, match='^transition-legacy-resume-started$'):
        transition.run()


def test_missing_injections_fail_closed(world):
    transition = world.transition()
    base = dict(plan=world.plan, journal=world.journal, host=transition.host, database=world.database,
                expected=world.expected, backup_proof=world.provide_backup, executor=transition.executor,
                layout=world.layout, candidate=transition.candidate, config_digest='f' * 64)
    for key in ('host', 'database', 'expected', 'backup_proof', 'executor', 'layout', 'candidate', 'plan'):
        with pytest.raises(Refused, match='^transition-'):
            FirstTransition(**{**base, key: None})
    other = Journal(world.tmp / 'other').open()
    try:
        with pytest.raises(Refused, match='^transition-journal$'):
            FirstTransition(**{**base, 'journal': other})
    finally:
        other.close()
    assert world.legacy_effects() == [] and world.pg.connections == 0


# --- DDL failures: first failure stops for good, never the legacy -----------------------------

@pytest.mark.parametrize('mode, code', [
    ('fail', 'migration-failed'), ('timeout', 'migration-timeout'),
    ('exit0-no-ledger', 'migration-ambiguous-exit0-no-ledger'),
    ('fail-with-ledger', 'migration-ambiguous-ledger-without-success'),
])
def test_migration_failure_stops_without_retry_or_legacy_resume(world, mode, code):
    failing = world.plan.pending[5]
    world.migrate.faults[failing.name] = mode
    transition = world.transition()
    with pytest.raises(Refused, match='^' + code + '$'):
        transition.run()
    assert world.migrate.applied == [m.name for m in world.plan.pending[:6]]
    assert world.journal.last('transition-failed')['legacy_resume_allowed'] is False
    assert world.cdocker.calls == []
    with pytest.raises(Refused, match='^transition-stopped$'):
        transition.run()
    with pytest.raises(Refused, match='^post-ddl-resume-forbidden$'):
        transition.resume_legacy(transition.host.resume_token())
    with pytest.raises(Refused, match='^post-ddl-resume-forbidden$'):
        transition.host.resume_legacy(transition.host.resume_token())
    assert world.migrate.applied == [m.name for m in world.plan.pending[:6]]
    assert not any(a[:2] == ('docker', 'start') for a in world.rig.docker.calls)
    recovery = transition.recovery()
    assert recovery['state'] == ('ddl-failed' if mode == 'fail' else 'ddl-ambiguous')
    assert recovery['legacy_resume_allowed'] is False
    assert recovery['automatic_undo'] is False and recovery['destructive_retry'] is False
    world.assert_legacy_contained()


def test_invalid_concurrent_index_stops(world):
    concurrent = next(m for m in world.plan.pending if m.concurrent)
    world.migrate.faults[concurrent.name] = 'invalid-index'
    with pytest.raises(Refused, match='^migration-index-invalid$'):
        world.transition().run()
    assert world.migrate.applied[-1] == concurrent.name


def test_controller_killed_after_intent_is_ambiguous_on_replay(world):
    victim = world.plan.pending[2]
    world.migrate.faults[victim.name] = 'crash'
    transition = world.transition()
    original = world.journal.append

    def append(kind, **fields):
        if kind == 'transition-failed':
            raise KeyboardInterrupt  # the controller dies before recording the failure
        return original(kind, **fields)
    world.journal.append = append
    with pytest.raises(KeyboardInterrupt):
        transition.run()
    world.journal.close()
    applied = list(world.migrate.applied)
    replay = world.transition()
    with pytest.raises(Refused, match='^migration-outcome-ambiguous$'):
        replay.run()
    assert world.migrate.applied == applied
    recovery = replay.recovery()
    assert recovery['state'] == 'ddl-ambiguous' and recovery['open_steps'] == ['migration:' + victim.name]
    with pytest.raises(Refused, match='^post-ddl-resume-forbidden$'):
        replay.resume_legacy(replay.host.resume_token())


def test_wrong_database_after_apply_is_ambiguous_and_stops_before_next_ddl(world):
    first = world.plan.pending[0]
    world.migrate.after = lambda name: name == first.name and setattr(world.pg, 'name', 'other_db')
    transition = world.transition()
    with pytest.raises(Refused, match='^database-identity-mismatch$'):
        transition.run()
    j = world.journal
    assert world.migrate.applied == [first.name] and j.last('transition-done', 'migration:' + first.name) is None
    outcome = j.last('transition-migration-failed')
    assert outcome['code'] == 'database-identity-mismatch' and outcome['definite'] is False
    assert world.layouts == [] and world.cdocker.calls == []
    assert transition.recovery()['state'] == 'ddl-ambiguous'


def test_wrong_database_at_final_observation_blocks_layout_and_a9(world):
    last = world.plan.pending[-1]

    def swap():
        if world.journal.last('transition-done', 'migration:' + last.name) is not None:
            world.pg.name = 'other_db'
    world.pg.on_connect = swap
    transition = world.transition()
    with pytest.raises(Refused, match='^database-identity-mismatch$'):
        transition.run()
    assert world.migrate.applied == [m.name for m in world.plan.pending]
    assert world.journal.last('transition-migrated') is None and world.journal.last('transition-intent', 'layout') is None
    assert world.layouts == [] and world.cdocker.calls == []
    assert transition.recovery()['state'] == 'post-ddl-failed'


def test_writer_appearing_between_migrations_stops_before_next_ddl(world):
    first = world.plan.pending[0]
    world.migrate.after = lambda name: name == first.name and setattr(world.pg, 'writers', 1)
    with pytest.raises(Refused, match='^database-writing-session$'):
        world.transition().run()
    assert world.migrate.applied == [first.name]


# --- A9 failures: no undo, consumers held, ingress blocked -------------------------------------

@pytest.mark.parametrize('fault, code', [
    ('gate', 'candidate-gate-open'), ('restart-always', 'candidate-consumer-not-held'),
    ('autostart', 'candidate-consumer-not-held'), ('start-dependency', 'candidate-consumer-not-held'),
    ('smoke-ready', 'candidate-ready-failed'), ('smoke-health', 'candidate-health-failed'),
    ('ingress-opened', 'observed-host-ingress-reopened'), ('legacy-restarted', 'observed-host-identity-or-support-changed'),
    ('support-stopped', 'observed-host-effect-failed'),
])
def test_a9_failures_stop_without_undo(world, fault, code):
    c = world.cdocker
    if fault == 'gate':
        c.gates = ['ALLOW_REAL_SENDS=true', *c.gates[1:]]
    elif fault == 'restart-always':
        c.hold_applied = False
    elif fault == 'autostart':
        c.autostart = {'cron-worker'}
    elif fault == 'start-dependency':
        c.start_also = {'queue-worker'}
    elif fault == 'smoke-ready':
        c.smoke = dict(c.smoke, ready=503, ready_status='not_ready', required_ok=False)
    elif fault == 'smoke-health':
        c.smoke = dict(c.smoke, health=None, health_ok=False, ready=None, ready_status=None, required_ok=False)
    elif fault == 'ingress-opened':
        c.on_start = lambda: setattr(world.rig.ingress['evolution-backend'], 'state', 'open')
    elif fault == 'legacy-restarted':
        def restart():
            state = world.rig.docker.containers[LEGACY['cron-worker']]['State']
            state.update(Status='running', Running=True, StartedAt='2026-10-30T14:00:00.000000001Z')
        c.on_start = restart
    else:
        c.on_create = lambda: world.rig.docker.containers[SUPPORT['redis']]['State'].update(
            Status='exited', Running=False)
    transition = world.transition()
    with pytest.raises(Refused, match='^' + code + '$'):
        transition.run()
    assert world.journal.last('transition-failed')['code'] == code
    assert not any(a[:2] == ('docker', 'start') and a[2] != CANDIDATE_IDS['backend'] for a in c.calls)
    assert not any(a[1] in ('rm', 'stop', 'kill', 'update', 'restart') for a in c.calls)
    assert not any(a[:2] == ('docker', 'start') for a in world.rig.docker.calls)
    recovery = transition.recovery()
    assert recovery['state'] in ('candidate-failed', 'candidate-ambiguous')
    assert recovery['legacy_resume_allowed'] is False
    calls = len(c.calls)
    with pytest.raises(Refused, match='^transition-stopped$'):
        transition.run()
    assert len(c.calls) == calls


def test_a9_refuses_a_non_empty_candidate_project_before_creating(world):
    world.cdocker.containers['e' * 63 + 'f'] = dict(name='stale', service='backend', status='exited', running=False,
                                                     started=ZERO_STARTED, restarts=0, policy='no', env=[])
    with pytest.raises(Refused, match='^candidate-project-not-empty$'):
        world.transition().run()
    assert world.cdocker.effects() == []


def _foreign(world, **fields):
    ident = 'e' * 64
    world.cdocker.containers[ident] = dict(name=NAMES['backend'], service='backend', status='created', running=False,
                                           started=ZERO_STARTED, restarts=0, policy='no',
                                           env=list(world.cdocker.gates), **fields)
    return ident


@pytest.mark.parametrize('target, code', [
    ('consumer', 'candidate-identity-mismatch'), ('foreign-project', 'candidate-identity-mismatch'),
    ('foreign-image', 'candidate-image-mismatch'),
])
def test_candidate_port_refuses_a_non_backend_id_with_zero_starts_or_smokes(world, target, code):
    port = CandidatePort(world.spec, runner=world.cdocker)
    world.cdocker(world.spec.compose_argv(), timeout=60, max_output=64)
    ident = {'consumer': lambda: CANDIDATE_IDS['queue-worker'],
             'foreign-project': lambda: _foreign(world, project='other-project'),
             'foreign-image': lambda: _foreign(world, image='sha256:' + '1' * 64)}[target]()
    with pytest.raises(Refused, match='^' + code + '$'):
        port.start_backend(ident)
    world.cdocker.containers[ident].update(status='running', running=True, started='2026-10-30T13:00:01.000000001Z')
    with pytest.raises(Refused, match='^' + code + '$'):
        port.smoke(ident)
    assert world.cdocker.starts == 0
    assert not any(a[:2] in (('docker', 'start'), ('docker', 'exec')) for a in world.cdocker.calls)


def test_candidate_port_refuses_starting_a_backend_that_is_not_held(world):
    port = CandidatePort(world.spec, runner=world.cdocker)
    world.cdocker.hold_applied = False
    world.cdocker(world.spec.compose_argv(), timeout=60, max_output=64)
    with pytest.raises(Refused, match='^candidate-backend-not-held$'):
        port.start_backend(CANDIDATE_IDS['backend'])
    with pytest.raises(Refused, match='^candidate-backend-not-running$'):
        port.smoke(CANDIDATE_IDS['backend'])
    assert world.cdocker.starts == 0
    assert not any(a[:2] in (('docker', 'start'), ('docker', 'exec')) for a in world.cdocker.calls)


def test_crash_after_backend_start_intent_is_ambiguous(world):
    transition = world.transition()
    world.cdocker.on_start = lambda: (_ for _ in ()).throw(KeyboardInterrupt)
    original = world.journal.append

    def append(kind, **fields):
        if kind == 'transition-failed':
            raise KeyboardInterrupt
        return original(kind, **fields)
    world.journal.append = append
    with pytest.raises(KeyboardInterrupt):
        transition.run()
    world.journal.close()
    world.cdocker.on_start = None
    replay = world.transition()
    starts = len(world.cdocker.effects())
    with pytest.raises(Refused, match='^candidate-start-ambiguous$'):
        replay.run()
    assert len(world.cdocker.effects()) == starts
    assert replay.recovery()['state'] == 'candidate-ambiguous'


def test_layout_is_exclusive_and_package_bound(world):
    count = world.layout()
    target = world.tmp / 'releases' / APPLICATION_SHA
    assert count == len([p for p in target.rglob('*') if p.is_file()]) and world.layout() == count
    (target / 'deploy' / 'docker-compose.yml').write_text('tampered\n')
    with pytest.raises(Refused, match='^layout-mismatch$'):
        world.layout()
    assert (target / 'deploy' / 'docker-compose.yml').read_text() == 'tampered\n'  # never overwritten
    with pytest.raises(Refused, match='^package-identity-mismatch$'):
        write_candidate_release(ROOT, world.spec, world.rig.manifest, package_manifest_sha256='0' * 64,
                                migrations=[m.name for m in world.plan.migrations], git=world.git)
    with pytest.raises(Refused, match='^layout-migrations-differ-from-plan$'):
        write_candidate_release(ROOT, world.spec, world.rig.manifest, package_manifest_sha256=world.package,
                                migrations=[], git=world.git)
    missing = CandidateSpec(**{**world.spec.__dict__, 'release_root': str(world.tmp / 'absent')})
    with pytest.raises(Refused, match='^release-root-missing$'):
        write_candidate_release(ROOT, missing, world.rig.manifest, package_manifest_sha256=world.package,
                                migrations=[m.name for m in world.plan.migrations], git=world.git)
    assert not (world.tmp / 'absent').exists()


# --- ports, runners and configuration -------------------------------------------------------------

def test_migration_executor_builds_the_canonical_command_and_isolates_the_secret(world):
    tx = next(m for m in world.plan.pending if not m.concurrent)
    nt = next(m for m in world.plan.pending if m.concurrent)
    assert MigrationExecutor.command(PYTHON, '/w', tx) == (PYTHON, '-I', '/w/scripts/migrate.py', 'apply', tx.name,
                                                           '--yes')
    assert MigrationExecutor.command(PYTHON, '/w', nt)[-1] == '--no-transaction'
    executor = world.transition().executor
    index = world.plan.pending.index(tx) + 1
    world.pg.ledger = list(world.plan.baseline)
    assert executor.apply(index, tx) == 0
    with pytest.raises(Refused, match='^migration-workdir-exists$'):
        executor.apply(index, tx)
    with pytest.raises(Refused, match='^migration-not-pending$'):
        executor.apply(index, nt)
    with pytest.raises(Refused, match='^migration-plan$'):
        MigrationExecutor(object(), python=PYTHON, workdir='/w', secret=lambda: SECRET_URL, runner=lambda *a: 0)


@pytest.mark.parametrize('argv, env', [
    (('/usr/bin/sh', '-c', 'x'), {}), ((PYTHON, 'x'), {'HOME': '/root'}), ((PYTHON, 'a\x00b'), {}),
    ([PYTHON, 'x'], {}),
])
def test_process_runner_refuses_unlisted_binary_env_or_shape_before_spawn(argv, env):
    calls = []
    runner = ProcessRunner(binaries=(PYTHON,), run=lambda *a, **k: calls.append(1))
    with pytest.raises(Refused, match='^process-'):
        runner(argv, env=env, cwd='/w', timeout=5)
    assert calls == []


def test_process_runner_sanitizes_spawn_failure():
    def explode(*_a, **_k):
        raise OSError(SECRET_URL)
    with pytest.raises(Refused, match='^process-spawn-failed$') as raised:
        ProcessRunner(binaries=(PYTHON,), run=explode)((PYTHON, 'x'), env={}, cwd='/w', timeout=5)
    assert 'SENTINEL' not in repr(raised.value) and raised.value.__cause__ is None


@pytest.mark.parametrize('argv', [
    ('docker', 'compose', 'up', '-d'), ('docker', 'start', 'x'), ('docker', 'rm', 'a' * 64),
    ('docker', 'exec', 'a' * 64, 'sh', '-c', 'x'), ('docker', 'update', '--restart=always', 'a' * 64),
    ('docker', 'compose', '--project-name', 'pastorai-release', 'start'),
])
def test_candidate_runner_allows_only_the_ports_own_argv(world, argv):
    from test_first_transition_host_driver import FakePopen, FakeProc
    popen = FakePopen(FakeProc())
    runner = CandidateRunner(world.spec, docker_binary='/usr/bin/docker', endpoint='unix:///run/x/docker.sock',
                             config_dir='/etc/synthetic-docker', popen=popen)
    with pytest.raises(Refused, match='^runner-argv$'):
        runner(argv, timeout=5, max_output=64)
    assert popen.calls == []
    runner(world.spec.compose_argv(), timeout=5, max_output=64)
    env = popen.calls[0][1]['env']
    assert env['PASTORAI_ENV_FILE'] == world.spec.env_file and set(env) == {'LC_ALL', 'LANG', 'PASTORAI_ENV_FILE'}


def test_example_config_is_sanitized_and_assembles_without_contacting_anything(world):
    config = load_config(EXAMPLE)
    assert config.candidate.release_root == '/opt/pastorai-releases'
    raw = json.loads(EXAMPLE.read_text())
    for forbidden in ('password', 'postgresql://', 'token', 'secret', 'key='):
        assert forbidden not in EXAMPLE.read_text().lower()
    with pytest.raises(Refused, match='^config-keys$'):
        parse_config({**raw, 'database_url': 'postgresql://x'})
    with pytest.raises(Refused, match='^config-candidate-sha$'):
        parse_config({**raw, 'candidate': {**raw['candidate'], 'sha': 'a' * 40}})
    journal = Journal(world.tmp / 'assembled').open()
    touched = []
    ingress = {entry: FakeIngress(config.manifest.digest, entry) for entry in ENTRIES}
    try:
        common = dict(plan=world.plan, journal=journal, secret=lambda: touched.append('secret'),
                      ingress=ingress, writers=FakeWriters(config.manifest.digest),
                      backup_proof=lambda request: touched.append('backup'), popen=lambda *a, **k: touched.append('popen'),
                      run=lambda *a, **k: touched.append('run'))
        with pytest.raises(Refused, match='^transition-database-missing$'):
            assemble(config, connect=None, **common)
        # Example IDs are not this plan's baseline expectation, yet assembling contacts nothing.
        transition = assemble(config, connect=lambda **k: touched.append('connect'), **common)
        assert isinstance(transition, FirstTransition) and touched == []
        assert transition.host.port.driver.supports_resume is True and touched == []
        for binding in ingress.values():
            binding.open = None  # without openers the same assembly cannot resume
        assert transition.host.port.driver.supports_resume is False
    finally:
        journal.close()


@pytest.mark.parametrize('leases', [
    [['notification_outbox', 'claimed_until']],
    [['broadcast_execucoes', 'lease_ate'], ['notification_outbox', 'claimed_until'],
     ['cell_report_audio_inputs', 'lease_until']],
    [['notification_outbox', 'claimed_until'], ['notification_outbox', 'claimed_until']],
])
def test_config_with_incomplete_lease_coverage_refuses_before_any_io(leases):
    raw = json.loads(EXAMPLE.read_text())
    with pytest.raises(Refused, match='^config-database-leases$'):
        parse_config({**raw, 'database': {**raw['database'], 'lease_columns': leases}})


def test_config_lease_columns_default_to_and_extend_the_mandatory_set():
    from first_transition_database import LEASES
    raw = json.loads(EXAMPLE.read_text())
    assert parse_config({**raw, 'database': {**raw['database'], 'lease_columns': []}}).lease_columns == LEASES
    extra = [*map(list, LEASES), ['outbox_extra', 'lease_until']]
    config = parse_config({**raw, 'database': {**raw['database'], 'lease_columns': extra}})
    assert config.lease_columns == (*LEASES, ('outbox_extra', 'lease_until'))


def test_observed_orchestrator_journal_stays_out_of_the_local_adapter(world):
    world.backup = None
    with pytest.raises(Refused):
        world.transition().run()

    class Database:
        identity = 'x'
    with pytest.raises(Refused, match='^local-transition-observed-journal$'):
        LocalTransition(world.plan, Database(), world.journal)


def test_partial_containment_is_classified_and_never_resumable(world):
    world.rig.docker.term_exit[LEGACY['cron-worker']] = 143
    transition = world.transition()
    with pytest.raises(Refused, match='^observed-host-'):
        transition.run()
    recovery = transition.recovery()
    assert recovery['state'] == 'containment-partial' and recovery['legacy_resume_allowed'] is False
    with pytest.raises(Refused, match='^observed-host-not-contained$'):
        transition.resume_legacy(transition.host.resume_token())
    assert EXECUTOR_SHA and world.migrate.applied == []


def test_failed_concurrent_migration_is_never_classified_as_definite(world):
    concurrent = next(m for m in world.plan.pending if m.concurrent)
    world.migrate.faults[concurrent.name] = 'fail'
    transition = world.transition()
    with pytest.raises(Refused, match='^migration-failed$'):
        transition.run()
    outcome = world.journal.last('transition-migration-failed')
    assert outcome['definite'] is False and outcome['step'] == 'migration:' + concurrent.name
    assert transition.recovery()['state'] == 'ddl-ambiguous'
