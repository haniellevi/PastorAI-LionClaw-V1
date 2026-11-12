"""A10 rehearsal: the real orchestrator runs A1..A9 and then A10 over the same synthetic ports.

Real code: orchestrator + A10 step, observed host contract/transport/driver, read-only database
observer, migration executor, layout writer and candidate port. Simulated: Docker (legacy and
candidate), PostgreSQL (DB-API fake with pending-work counters), migration child and the two
ingress bindings. The fake candidate Docker models the product rule that matters here: a cron
started with ALLOW_REAL_SENDS closed turns the pending outbox items into ``gate_fechado``.
"""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from first_transition_a10 import A10_ORDER
from first_transition_adapter import ROLES, Refused
from first_transition_candidate import ZERO_STARTED, gate_override, restore_values
from first_transition_orchestrator import FirstTransition, MigrationExecutor, ProcessRunner
from first_transition_host_contract import ObservedHostContract
from initial_transition_files import Journal
from test_first_transition_orchestrator import (CANDIDATE_IDS, PYTHON, SECRET_URL, FakeCandidateDocker, World,
                                                no_real_processes_or_network, pinned)  # noqa: F401 (fixtures)
from test_first_transition_host_driver import LEGACY

A10_IDS = {role: ch * 32 for role, ch in zip(ROLES, ('1a', '2b', '3c', '4d'))}
PROD_LIKE = {'ALLOW_REAL_SENDS': 'true', 'ASAAS_BILLING_ENABLED': 'false', 'BREVO_SEND_MODE': 'live',
             'BROADCAST_ASYNC_ENABLED': 'false'}


class A10Docker(FakeCandidateDocker):
    """Adds the A10 recreation, start/stop and the pending-work side effect of the cron."""

    def __init__(self, spec, pg):
        super().__init__(spec)
        self.pg = pg
        self.pending_outbox = 4  # pending reminders waiting in notification_outbox
        self.cron_cancels_anyway = False  # e.g. a purpose gate in the env file differs from the legacy
        self.recreate_crash = self.start_crash = None

    def __call__(self, argv, *, timeout, max_output):
        spec = self.spec
        if argv == spec.a10_compose_argv():
            self.calls.append(argv)
            assert 0 < timeout <= 60
            gates = json.loads(Path(spec.gate_override).read_text().split('\n', 1)[1])['services']
            for ident in list(self.containers):
                del self.containers[ident]  # --force-recreate: old containers replaced
            for role in ROLES:
                self.containers[A10_IDS[role]] = dict(
                    name=spec.names()[role], service=role, status='created', running=False, started=ZERO_STARTED,
                    restarts=0, policy='always', env=[f'{k}={v}' for k, v in gates[role]['environment'].items()],
                    database_env=list(self.database_env))
            if self.recreate_crash:
                self.recreate_crash, crash = None, self.recreate_crash
                raise crash
            return 0, b''
        if argv[:3] == ('docker', 'update', '--restart=no'):
            self.calls.append(argv)
            self.containers[argv[3]]['policy'] = 'no'
            return 0, (argv[3] + '\n').encode()
        if argv[:2] == ('docker', 'stop'):
            self.calls.append(argv)
            self.containers[argv[4]].update(status='exited', running=False)
            return 0, (argv[4] + '\n').encode()
        if argv[:2] == ('docker', 'exec') and argv[2] in A10_IDS.values():
            self.calls.append(argv)
            assert argv == spec.smoke_argv(A10_IDS['backend'])
            if getattr(self, 'smoke_crash', None) is not None:
                self.smoke_crash, crash = None, self.smoke_crash
                raise crash
            return 0, (json.dumps(self.smoke) + '\n').encode()
        result = super().__call__(argv, timeout=timeout, max_output=max_output)
        if argv[:2] == ('docker', 'start') and argv[2] == A10_IDS['cron-worker']:
            env = dict(e.split('=', 1) for e in self.containers[argv[2]]['env'])
            if env['ALLOW_REAL_SENDS'].lower() != 'true' or self.cron_cancels_anyway:
                self.pg.gate_cancelled += self.pending_outbox  # terminal: never undone by reopening
                self.pending_outbox = 0
        if argv[:2] == ('docker', 'start') and self.start_crash and argv[2] == self.start_crash[0]:
            crash, self.start_crash = self.start_crash[1], None
            raise crash
        return result

    def a10_effects(self):
        return [a for a in self.calls if a[:2] in (('docker', 'start'), ('docker', 'compose'), ('docker', 'stop'),
                                                   ('docker', 'update'))]


class A10World(World):
    def __init__(self, pinned, tmp_path, legacy_gates=PROD_LIKE):
        super().__init__(pinned, tmp_path)
        self.cdocker = A10Docker(self.spec, self.pg)
        self.set_legacy_gates(legacy_gates)

    def set_legacy_gates(self, gates, roles=ROLES):
        for role in roles:
            c = self.rig.docker.containers[LEGACY[role]]
            others = [e for e in c['Env'] if e.split('=', 1)[0] not in PROD_LIKE]
            c['Env'] = [*others, *(f'{k}={v}' for k, v in gates.items())]

    def transition(self, journal=None, *, ports=True):
        if not ports:
            return super().transition(journal)
        self.journal = journal or Journal(self.tmp / 'journal').open()
        executor = MigrationExecutor(self.plan, python=PYTHON, workdir=str(self.tmp / 'work'),
                                     secret=lambda: SECRET_URL,
                                     runner=ProcessRunner(binaries=(PYTHON,), run=self.migrate))
        from first_transition_candidate import CandidatePort

        def sleep(seconds):
            self.clock[0] += seconds
        return FirstTransition(plan=self.plan, journal=self.journal,
                               host=ObservedHostContract(self.transport, self.journal), database=self.database,
                               expected=self.expected, backup_proof=self.provide_backup, executor=executor,
                               layout=self.layout, candidate=CandidatePort(self.spec, runner=self.cdocker),
                               config_digest='f' * 64, clock=lambda: self.clock[0], sleep=sleep,
                               legacy_gates=self.driver.legacy_gates, ingress=self.rig.ingress,
                               pending_counts=self.database.pending_outcomes)

    def reopen(self, **kwargs):
        self.journal.close()
        return self.transition(**kwargs)

    def candidate(self, role):
        return self.cdocker.containers[A10_IDS[role]]

    def gates_of(self, role):
        return dict(e.split('=', 1) for e in self.candidate(role)['env'])


@pytest.fixture
def world(pinned, tmp_path):
    w = A10World(pinned, tmp_path)
    yield w
    if w.journal is not None:
        w.journal.close()


def a9(world, **kwargs):
    transition = world.transition(**kwargs)
    result = transition.run()
    assert result['status'] == 'a9-backend-smoked'
    return transition, result


def assert_a9_hold_intact(world):
    """Nothing moved: A9 backend running with closed gates, consumers held, ingress blocked."""
    world.consumers_held()
    backend = world.cdocker.containers[CANDIDATE_IDS['backend']]
    assert backend['running'] and backend['policy'] == 'no'
    assert all(i.state == 'blocked' for i in world.rig.ingress.values())
    assert not any(a[:2] in (('docker', 'stop'), ('docker', 'update')) for a in world.cdocker.calls)
    assert world.spec.a10_compose_argv() not in world.cdocker.calls


# --- happy path ---------------------------------------------------------------------------------

def test_a9_then_a10_restores_pre_window_gates_and_starts_cron_last(world):
    transition, result = a9(world)
    snapshot = world.journal.last('transition-gate-snapshot')
    order = [e['kind'] for e in world.journal.events]
    assert order.index('transition-gate-snapshot') < order.index('observed-host-init')
    assert snapshot['restore'] == {role: PROD_LIKE for role in ROLES}
    assert result['a10'] == 'separate-authorization' and result['a10_token'] == transition.a10_token()
    assert world.journal.last('transition-pending-baseline')['gate_cancelled'] == 0
    a9_effects = list(world.cdocker.effects())

    done = transition.a10(result['a10_token'])

    assert done['status'] == 'a10-complete' and done['workers'] == 'running' and done['ingress_open'] is True
    assert done['pending_guard'] == 'no-gate-cancellation-since-baseline' and done['production_ready'] is False
    # Exactly: one recreation, then backend, queue, broadcast and cron LAST; no stop, no update.
    effects = world.cdocker.a10_effects()[len(a9_effects):]
    assert effects == [world.spec.a10_compose_argv(), *(('docker', 'start', A10_IDS[r]) for r in A10_ORDER)]
    assert A10_ORDER[-1] == 'cron-worker'
    assert world.spec.hold_override not in effects[0] and world.spec.gate_override in effects[0]
    assert '--force-recreate' in effects[0] and '--no-start' in effects[0]
    for role in ROLES:
        c = world.candidate(role)
        assert world.gates_of(role) == PROD_LIKE  # never values from code: the legacy snapshot
        assert c['running'] and c['policy'] == 'always' and c['restarts'] == 0
    assert Path(world.spec.gate_override).read_text() == gate_override({r: PROD_LIKE for r in ROLES})
    # Pending reminders survive: no gate_fechado cancellation by the transition.
    assert world.pg.gate_cancelled == 0 and world.cdocker.pending_outbox == 4
    assert all(i.state == 'open' for i in world.rig.ingress.values())
    for ident in LEGACY.values():
        c = world.rig.docker.containers[ident]
        assert c['State']['Running'] is False and c['RestartPolicy'] == 'no'
    assert transition.recovery()['state'] == 'a10-complete'
    assert transition.recovery()['legacy_resume_allowed'] is False
    text = world.text()
    assert 'postgresql://' not in text and 'SENTINEL' not in text


def test_contrast_a9_closed_gates_would_cancel_pending_work(world):
    """Why A10 never starts the cron with the A9 (closed) gates: that start is terminal for pending items."""
    world.cdocker.pending_outbox = 3
    a9(world)
    # Starting the held A9 cron (gates closed) is exactly what the fake models as cancelling:
    held = world.cdocker.containers[CANDIDATE_IDS['cron-worker']]
    assert dict(e.split('=', 1) for e in held['env'])['ALLOW_REAL_SENDS'] == 'false'
    # A10 instead recreates it with the legacy value before its first start.
    transition = world.reopen()
    transition.a10(transition.a10_token())
    assert world.gates_of('cron-worker')['ALLOW_REAL_SENDS'] == 'true'
    assert world.pg.gate_cancelled == 0 and world.cdocker.pending_outbox == 3


# --- authorization and snapshot refusals --------------------------------------------------------

@pytest.mark.parametrize('token', [None, '', '0' * 64, 'not-a-token'])
def test_a10_needs_the_exact_operator_token(world, token):
    transition, _ = a9(world)
    with pytest.raises(Refused, match='^a10-confirmation$'):
        transition.a10(token)
    assert_a9_hold_intact(world)
    assert transition.recovery()['state'] == 'a9-complete'


def test_a10_before_a9_refuses_without_effect(world):
    transition = world.transition()
    with pytest.raises(Refused, match='^a10-a9-incomplete$'):
        transition.a10('0' * 64)
    assert world.cdocker.calls == [] and world.legacy_effects() == []


def test_missing_snapshot_refuses_and_keeps_everything_closed(world):
    _, result = a9(world, ports=False)  # A9 run without the snapshot port: no pre-window values exist
    assert result['a10'] == 'gate-snapshot-missing' and result['a10_token'] is None
    assert world.journal.last('transition-gate-snapshot') is None
    transition = world.reopen()
    with pytest.raises(Refused, match='^a10-gate-snapshot-missing$'):
        transition.a10('0' * 64)
    assert_a9_hold_intact(world)
    assert not Path(world.spec.gate_override).exists()


def test_snapshot_with_closed_or_absent_gate_stays_closed(world):
    closed = {'ALLOW_REAL_SENDS': 'false', 'ASAAS_BILLING_ENABLED': 'false', 'BREVO_SEND_MODE': 'off',
              'BROADCAST_ASYNC_ENABLED': 'false'}
    world.set_legacy_gates(closed)
    # The standalone legacy broadcast-worker has no BREVO_SEND_MODE at all: absent = closed default.
    c = world.rig.docker.containers[LEGACY['broadcast-worker']]
    c['Env'] = [e for e in c['Env'] if not e.startswith('BREVO_SEND_MODE=')]
    transition, result = a9(world)
    done = transition.a10(result['a10_token'])
    for role in ROLES:
        assert world.gates_of(role) == closed  # never opened
    assert world.journal.last('transition-gate-snapshot')['open_gates'] == {r: [] for r in ROLES}
    # The gate was closed before the window: the product rule (closed gate cancels) is unchanged.
    assert done['pending_guard'] == 'not-applicable-gate-closed-before-window'
    assert world.pg.gate_cancelled == 4


def test_per_role_snapshot_restores_each_role_as_it_was(world):
    world.set_legacy_gates({**PROD_LIKE, 'BROADCAST_ASYNC_ENABLED': 'true'}, roles=('broadcast-worker',))
    transition, result = a9(world)
    transition.a10(result['a10_token'])
    assert world.gates_of('broadcast-worker')['BROADCAST_ASYNC_ENABLED'] == 'true'
    assert all(world.gates_of(r)['BROADCAST_ASYNC_ENABLED'] == 'false' for r in ROLES if r != 'broadcast-worker')


@pytest.mark.parametrize('bad', ['ALLOW_REAL_SENDS=yes', 'BREVO_SEND_MODE=LIVE ', 'BREVO_SEND_MODE=on'])
def test_unparseable_legacy_gate_refuses_before_containment(world, bad):
    name = bad.split('=')[0]
    c = world.rig.docker.containers[LEGACY['cron-worker']]
    c['Env'] = [e for e in c['Env'] if not e.startswith(name + '=')] + [bad]
    transition = world.transition()
    with pytest.raises(Refused, match='^a10-gate-snapshot-invalid$'):
        transition.run()
    assert world.legacy_effects() == [] and world.migrate.applied == []
    assert all(i.state == 'open' for i in world.rig.ingress.values())


def test_divergent_legacy_gates_refuse_without_effect(world):
    transition, result = a9(world)
    # Someone edited a legacy container after the snapshot: there is no single "as it was" anymore.
    world.set_legacy_gates({**PROD_LIKE, 'ASAAS_BILLING_ENABLED': 'true'}, roles=('queue-worker',))
    with pytest.raises(Refused, match='^a10-gate-snapshot-divergent$'):
        transition.a10(result['a10_token'])
    assert_a9_hold_intact(world)
    assert world.journal.last('transition-a10-containment') is None


def test_tampered_gate_file_refuses_before_recreation(world):
    transition, result = a9(world)
    Path(world.spec.gate_override).write_text(gate_override({r: {**PROD_LIKE, 'ASAAS_BILLING_ENABLED': 'true'}
                                                              for r in ROLES}))
    with pytest.raises(Refused, match='^a10-gate-file-mismatch$'):
        transition.a10(result['a10_token'])
    assert_a9_hold_intact(world)


# --- verification failure: containment ----------------------------------------------------------

def test_failed_pending_verification_contains_and_never_reopens(world):
    world.cdocker.cron_cancels_anyway = True  # e.g. a purpose gate of the env file differs from the legacy
    transition, result = a9(world)
    with pytest.raises(Refused, match='^a10-pending-cancelled$'):
        transition.a10(result['a10_token'])
    contained = world.journal.last('transition-a10-contained')
    assert contained['complete'] is True and contained['gates_rewritten'] is False
    assert contained['legacy_resume_allowed'] is False
    assert all(i.state == 'blocked' for i in world.rig.ingress.values())
    for role in ROLES:
        c = world.candidate(role)
        assert c['running'] is False and c['policy'] == 'no'
        assert world.gates_of(role) == PROD_LIKE  # not rewritten closed: a later cron would cancel
    stops = [a for a in world.cdocker.calls if a[:2] == ('docker', 'stop')]
    assert [a[4] for a in stops] == [A10_IDS[r] for r in ('cron-worker', 'broadcast-worker', 'queue-worker',
                                                            'backend')]
    for ident in LEGACY.values():
        assert world.rig.docker.containers[ident]['State']['Running'] is False
    recovery = transition.recovery()
    assert recovery['state'] == 'a10-contained' and recovery['legacy_resume_allowed'] is False
    effects = list(world.cdocker.calls)
    with pytest.raises(Refused, match='^a10-contained$'):
        world.reopen().a10(result['a10_token'])
    with pytest.raises(Refused, match='^transition-a10-started$'):
        world.reopen().run()
    assert [a for a in world.cdocker.calls[len(effects):] if a[:2] in (('docker', 'start'), ('docker', 'compose'))] == []
    with pytest.raises(Refused, match='^observed-host-resume-started$|^post-ddl-resume-forbidden$'):
        world.reopen().resume_legacy('x')


def test_unhealthy_restored_backend_contains(world):
    transition, result = a9(world)
    world.cdocker.smoke = dict(world.cdocker.smoke, ready=503, required_ok=False)
    with pytest.raises(Refused, match='^candidate-ready-failed$'):
        transition.a10(result['a10_token'])
    assert world.journal.last('transition-a10-contained')['complete'] is True
    # The backend was stopped before any consumer started; ingress never opened.
    assert [a for a in world.cdocker.calls if a[:2] == ('docker', 'start')][-1] == ('docker', 'start',
                                                                                    A10_IDS['backend'])
    assert all(not world.candidate(r)['running'] for r in ROLES)
    assert all(i.opens == 0 for i in world.rig.ingress.values())


# --- idempotency and resumption ------------------------------------------------------------------

def test_replay_after_a10_only_reverifies(world):
    transition, result = a9(world)
    first = transition.a10(result['a10_token'])
    effects = list(world.cdocker.a10_effects())
    opens = [i.opens for i in world.rig.ingress.values()]
    again = world.reopen().a10(result['a10_token'])
    assert again == first
    assert world.cdocker.a10_effects() == effects
    assert [i.opens for i in world.rig.ingress.values()] == opens
    assert len([e for e in world.journal.events if e['kind'] == 'transition-a10-complete']) == 1
    with pytest.raises(Refused, match='^transition-a10-started$'):
        world.reopen().run()


@pytest.mark.parametrize('role', A10_ORDER)
def test_interrupted_start_resumes_without_second_start(world, role):
    transition, result = a9(world)
    world.cdocker.start_crash = (A10_IDS[role], KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        transition.a10(result['a10_token'])
    assert world.journal.last('transition-a10-containment') is None  # a signal never contains
    assert transition.recovery()['state'] == 'a10-partial'
    done = world.reopen().a10(result['a10_token'])
    assert done['status'] == 'a10-complete'
    starts = [a[2] for a in world.cdocker.calls if a[:2] == ('docker', 'start')]
    for r in ROLES:
        assert starts.count(A10_IDS[r]) == 1


def test_interrupted_recreation_is_adopted_on_exact_proof(world):
    transition, result = a9(world)
    world.cdocker.recreate_crash = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        transition.a10(result['a10_token'])
    done = world.reopen().a10(result['a10_token'])
    assert done['status'] == 'a10-complete'
    assert world.cdocker.calls.count(world.spec.a10_compose_argv()) == 1


def test_interrupted_recreation_with_wrong_outcome_contains(world):
    transition, result = a9(world)
    world.cdocker.recreate_crash = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        transition.a10(result['a10_token'])
    world.candidate('cron-worker')['env'] = [e.replace('ALLOW_REAL_SENDS=true', 'ALLOW_REAL_SENDS=false')
                                             for e in world.candidate('cron-worker')['env']]
    with pytest.raises(Refused, match='^a10-gates-differ-from-snapshot$'):
        world.reopen().a10(result['a10_token'])
    assert world.journal.last('transition-a10-contained') is not None
    assert not any(a[:2] == ('docker', 'start') and a[2] in A10_IDS.values() for a in world.cdocker.calls)


# --- unit: restore map ---------------------------------------------------------------------------

def test_restore_values_keeps_exact_strings_and_never_opens_absent_gates():
    assert restore_values([]) == {'ALLOW_REAL_SENDS': 'false', 'ASAAS_BILLING_ENABLED': 'false',
                              'BREVO_SEND_MODE': 'off', 'BROADCAST_ASYNC_ENABLED': 'false'}
    assert restore_values(['ALLOW_REAL_SENDS=True', 'BREVO_SEND_MODE=canary'])['ALLOW_REAL_SENDS'] == 'True'
    for bad in (['ALLOW_REAL_SENDS=1'], ['OTHER=true'], ['ALLOW_REAL_SENDS=true', 'ALLOW_REAL_SENDS=true'],
                ['BREVO_SEND_MODE= live'], 'ALLOW_REAL_SENDS=true'):
        with pytest.raises(Refused, match='^a10-gate-snapshot-invalid$'):
            restore_values(bad)


def test_writer_binding_declares_exactly_the_started_a10_containers(world):
    transition, result = a9(world)
    assert transition.candidate_writer(timeout=10) == CANDIDATE_IDS['backend']
    world.cdocker.start_crash = (A10_IDS['queue-worker'], KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        transition.a10(result['a10_token'])
    transition = world.reopen()
    with pytest.raises(Refused, match='^a10-start-ambiguous$'):
        transition.candidate_writer(timeout=10)  # an unreceipted start never declares a writer
    transition.a10(result['a10_token'])
    assert transition.candidate_writer(timeout=10) == tuple(A10_IDS[r] for r in ROLES)
    world.candidate('cron-worker')['restarts'] = 1  # crash loop hidden by restart=always
    with pytest.raises(Refused, match='^a10-not-running$'):
        transition.candidate_writer(timeout=10)


# --- composed rehearsal: real assemble(), real ingress/writer bindings, simulated IO only ----------

def test_composed_assembly_runs_a9_then_a10_with_real_bindings(pinned, tmp_path):
    from first_transition_candidate import CANDIDATE_TEMPLATE, DATABASE_TEMPLATE
    from test_first_transition_candidate_writers import Assembly
    from test_first_transition_host_driver import FakeProc

    world = A10World(pinned, tmp_path)
    composed = Assembly(world)
    spec = world.spec
    candidate_ids = {*CANDIDATE_IDS.values(), *A10_IDS.values()}

    def popen(argv, **kwargs):
        composed.popen_calls.append((argv, kwargs))
        assert SECRET_URL not in str(argv)
        logical = ('docker', *argv[5:])
        candidate = logical in (spec.ps_argv(), spec.compose_argv(), spec.a10_compose_argv(), spec.network_argv()) or (
            logical[:2] in (('docker', 'start'), ('docker', 'exec')) and logical[2] in candidate_ids) or (
            logical[:3] == ('docker', 'update', '--restart=no') and logical[3] in candidate_ids) or (
            logical[:2] == ('docker', 'stop')) or (
            logical[:5] == ('docker', 'inspect', '--type', 'container', '--format')
            and logical[5] in (CANDIDATE_TEMPLATE, DATABASE_TEMPLATE))
        runner = world.cdocker if candidate else world.rig.docker
        rc, out = runner(logical, timeout=30, max_output=65536)
        return FakeProc(out, returncode=rc)
    composed.popen = popen
    try:
        transition, writers = composed.transition()
        result = transition.run()
        assert result['status'] == 'a9-backend-smoked'
        snapshot = world.journal.last('transition-gate-snapshot')
        assert snapshot['restore'] == {r: PROD_LIKE for r in ROLES}
        replay, writers = composed.transition()
        done = replay.a10(result['a10_token'])
        assert done['status'] == 'a10-complete'
        assert all(b.observe(b.scope, timeout=5) == 'open' for b in composed.ingress.values())
        assert writers.observe(writers.scope, timeout=5) == 0  # the four started A10 IDs are declared
        for role in ROLES:
            assert world.gates_of(role) == PROD_LIKE and world.candidate(role)['running']
        assert world.pg.gate_cancelled == 0
        assert 'SENTINEL' not in (world.tmp / 'assembled-journal' / 'journal.jsonl').read_text()
        # Replay: verification only, no new effect.
        effects = list(world.cdocker.a10_effects())
        again, _ = composed.transition()
        assert again.a10(result['a10_token'])['status'] == 'a10-complete'
        assert world.cdocker.a10_effects() == effects
    finally:
        world.journal.close()


def test_restarted_legacy_cron_blocks_the_new_cron_start(world):
    transition, result = a9(world)
    calls = {'n': 0}
    docker = world.cdocker

    def restart_legacy_cron_after_broadcast(argv, **kwargs):
        answer = A10Docker.__call__(docker, argv, **kwargs)
        if argv == ('docker', 'start', A10_IDS['broadcast-worker']):
            calls['n'] += 1
            legacy = world.rig.docker.containers[LEGACY['cron-worker']]
            legacy['State'].update(Status='running', Running=True)
        return answer
    transition.candidate.runner = restart_legacy_cron_after_broadcast
    with pytest.raises(Refused):
        transition.a10(result['a10_token'])
    assert calls['n'] == 1
    assert ('docker', 'start', A10_IDS['cron-worker']) not in world.cdocker.calls
    assert world.journal.last('transition-a10-contained') is not None


def test_replay_after_interrupted_smoke_resmokes_before_any_consumer_or_ingress(world):
    transition, result = a9(world)
    world.cdocker.smoke_crash = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        transition.a10(result['a10_token'])
    assert world.journal.last('transition-done', 'a10:start:backend') is not None
    world.cdocker.smoke = dict(world.cdocker.smoke, ready=503, required_ok=False)
    with pytest.raises(Refused, match='^candidate-ready-failed$'):
        world.reopen().a10(result['a10_token'])
    starts = [a[2] for a in world.cdocker.calls if a[:2] == ('docker', 'start')]
    assert [i for i in starts if i in A10_IDS.values()] == [A10_IDS['backend']]
    assert all(i.opens == 0 for i in world.rig.ingress.values())
    assert world.journal.last('transition-a10-contained')['complete'] is True
