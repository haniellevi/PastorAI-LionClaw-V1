"""A9 writer identity and PG guards; only external IO is simulated."""
import json
from pathlib import Path
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from first_transition_adapter import Refused
from first_transition_candidate import CANDIDATE_TEMPLATE, DATABASE_TEMPLATE, CandidatePort
import first_transition_window_bindings as wb
from first_transition_orchestrator import assemble, load_config
from initial_transition_files import Journal
from test_first_transition_database import FakeConnection, FakeCursor
from first_transition_host_driver import INFO_ARGV
from test_first_transition_host_driver import LEGACY, FakeProc
from test_first_transition_window_bindings import DB, Nft, Proc, _nginx, _tcp, _writers
from test_first_transition_orchestrator import (CANDIDATE_IDS, EXAMPLE, PYTHON, ROOT, SECRET_URL, pinned, world,
                                                no_real_processes_or_network)  # noqa: F401


def test_active_pg_before_start_refuses_without_start_intent(world):
    transition = world.transition()
    world.cdocker.on_create = lambda: setattr(world.pg, 'writers', 1)
    with pytest.raises(Refused, match='^database-writing-session$'):
        transition.run()
    assert world.journal.last('transition-intent', 'a9:start-backend') is None
    assert world.cdocker.starts == 0
    assert world.journal.last('transition-a9-complete') is None
    world.assert_legacy_contained()


@pytest.mark.parametrize('checkpoint', ['after-start', 'after-smoke'])
def test_active_pg_after_start_cannot_complete_a9(world, checkpoint):
    transition = world.transition()
    if checkpoint == 'after-start':
        world.cdocker.on_start = lambda: setattr(world.pg, 'writers', 1)
    else:
        docker = transition.candidate.runner

        def external_io(argv, **kwargs):
            answer = docker(argv, **kwargs)
            if argv[:2] == ('docker', 'exec'):
                world.pg.writers = 1
            return answer
        transition.candidate.runner = external_io
    with pytest.raises(Refused, match='^database-writing-session$'):
        transition.run()
    assert world.journal.last('ddl-marker') is not None
    assert world.journal.last('transition-a9-complete') is None
    assert world.journal.last('transition-failed')['legacy_resume_allowed'] is False
    world.consumers_held()
    world.assert_legacy_contained()


def test_candidate_inspection_shares_one_timeout_budget(world):
    calls = []
    candidate = CandidatePort(world.spec, runner=lambda argv, **kwargs: calls.append(kwargs) or (0, b''))
    with pytest.raises(Refused, match='^candidate-daemon-mismatch$'):
        candidate.inspect((CANDIDATE_IDS['backend'],), timeout=0.25)
    assert calls and calls[0]['timeout'] <= 0.25


class WriterCursor(FakeCursor):
    """DB-API IO shared by the real PG observer and real unknown-writer binding."""

    def execute(self, query, params=None):
        if query == wb.Q_STATS:
            self.rows = [(True,)]
        elif query == wb.Q_READONLY:
            self.rows = []
        elif query == wb.Q_ACTIVE:
            self.rows = [('postgres', self.pg.writers)]
        elif query.startswith('BEGIN TRANSACTION'):
            self.rows = []
        else:
            super().execute(query, params)


class WriterConnection(FakeConnection):
    def cursor(self):
        return WriterCursor(self.pg)


class WriterDocker:
    """Docker and /proc IO only; the binding's namespace/TCP attribution is real."""

    def __init__(self, world):
        self.world = world
        self.proc = Proc(world.tmp / 'proc')
        self.proc.process(1, 0, 'host')
        self.proc.process(500, 1, 'host')
        self.ids, self.extra = {}, {}
        self.pool = 2
        self.shared = False

    def _running(self):
        return [i for i, c in self.world.rig.docker.containers.items() if c['State']['Running']] + [
            i for i, c in self.world.cdocker.containers.items() if c['running']] + list(self.extra)

    def __call__(self, argv, *, timeout, stdin=None):
        assert timeout > 0 and stdin is None
        if argv[5:] == ('ps', '-q', '--no-trunc'):
            for ident in self._running():
                if ident not in self.ids:
                    pid = self.ids[ident] = 1000 + len(self.ids)
                    ns = 'candidate-shared' if self.shared and ident in {CANDIDATE_IDS['backend'], *self.extra} else ident
                    self.proc.process(pid, 1, ns)
                rows = [(DB, 5432, '01', 20 + n) for n in range(self.pool)] if ident == CANDIDATE_IDS['backend'] else []
                (self.proc.root / str(self.ids[ident]) / 'net' / 'tcp').write_text(_tcp(rows))
            return 0, '\n'.join(self._running()).encode()
        assert argv[5:8] == ('inspect', '--format', '{{json .Id}} {{json .State.Pid}}')
        return 0, '\n'.join(f'"{i}" {self.ids[i]}' for i in argv[8:]).encode()


class Assembly:
    def __init__(self, world):
        self.world = world
        (world.tmp / 'nginx').mkdir()
        nginx, self.nginx_io = _nginx(world.tmp / 'nginx')
        nginx.scope = world.rig.manifest.digest
        bridge = wb.BridgeConfig(nft_binary='/usr/sbin/nft', bridge='br-' + world.rig.manifest.network_id[:12])
        self.bridge_io = Nft(bridge)
        self.ingress = {'external': nginx, 'evolution-backend': wb.BridgePortIngress(
            bridge, scope=world.rig.manifest.digest, run=self.bridge_io)}
        self.docker = WriterDocker(world)
        self.config = replace(load_config(EXAMPLE), repo=str(ROOT), state_dir=str(world.tmp / 'state'),
                              migration_workdir=str(world.tmp / 'work'), python=PYTHON,
                              manifest=world.rig.manifest, candidate=world.spec, identity=world.expected.identity,
                              catalog=world.expected.catalog, package_manifest_sha256=world.package)
        world.journal = Journal(world.tmp / 'assembled-journal').open()
        self.popen_calls = []
        self.on_popen = None

    def connect(self, *, timeout):
        self.world.pg.connect(timeout=timeout)  # exercises existing connection failures/counters
        return WriterConnection(self.world.pg)

    def popen(self, argv, **kwargs):
        self.popen_calls.append((argv, kwargs))
        assert SECRET_URL not in str(argv) and 'MIGRATION_DATABASE_URL' not in kwargs['env']
        logical = ('docker', *argv[5:])
        candidate = logical in (self.world.spec.ps_argv(), self.world.spec.compose_argv(),
                                self.world.spec.network_argv()) or (
            logical[:2] in (('docker', 'start'), ('docker', 'exec')) and logical[2] in CANDIDATE_IDS.values()) or (
            logical[:5] == ('docker', 'inspect', '--type', 'container', '--format')
            and logical[5] in (CANDIDATE_TEMPLATE, DATABASE_TEMPLATE))
        runner = self.world.cdocker if candidate else self.world.rig.docker
        rc, out = runner(logical, timeout=30, max_output=65536)
        if self.on_popen:
            self.on_popen(logical)
        return FakeProc(out, returncode=rc)

    def transition(self, *, declared_containers=None, writer_docker=None):
        writers = wb.UnknownWriters(scope=self.world.rig.manifest.digest, connect=self.connect,
                                    endpoint=(frozenset({wb.ipaddress.ip_address(DB)}), 5432),
                                    declared_containers=declared_containers or tuple(LEGACY.values()),
                                    docker=self.config.docker if writer_docker is None else writer_docker,
                                    proc=str(self.docker.proc.root), run=self.docker, own_pid=500)
        transition = assemble(self.config, plan=self.world.plan, journal=self.world.journal, connect=self.connect,
                              secret=lambda: SECRET_URL, ingress=self.ingress, writers=writers,
                              backup_proof=self.world.provide_backup, popen=self.popen, run=self.world.migrate,
                              sleep=lambda _: None, git=self.world.git)
        return transition, writers


@pytest.fixture
def composed(world):
    return Assembly(world)


def assert_no_window_effects(composed, candidate_effects=()):
    w = composed.world
    assert w.rig.docker.effects() == [] and w.requests == [] and w.migrate.applied == []
    assert w.cdocker.effects() == list(candidate_effects) and w.cdocker.starts == 0
    assert w.journal.last('ddl-marker') is None
    assert w.journal.last('transition-intent', 'a9:start-backend') is None
    assert not composed.ingress['external'].snippet.exists() and composed.nginx_io.live is False
    assert all(a[0].endswith('curl') or a[1:] == ('-T',) for a in composed.nginx_io.calls)
    assert composed.bridge_io.table is None
    assert all(a[1:3] == ('-j', 'list') for a in composed.bridge_io.calls)


def test_created_stopped_project_refuses_before_any_window_effect(composed):
    w = composed.world
    w.cdocker(w.spec.compose_argv(), timeout=5, max_output=65536)
    site = Path(composed.ingress['external'].config.site_path)
    before_site = site.read_bytes()
    transition, _ = composed.transition()
    with pytest.raises(Refused, match='^candidate-project-not-empty$'):
        transition.candidate_writer(timeout=5)
    # The existing contract sanitizes driver/provider errors at its public boundary.
    with pytest.raises(Refused, match='^observed-host-effect-failed$'):
        transition.run()
    assert transition.host.port.driver.refusals[-1] == 'driver-binding-failed'
    assert site.read_bytes() == before_site
    assert_no_window_effects(composed, (w.spec.compose_argv(),))


@pytest.mark.parametrize('component,value', [
    (0, '/usr/local/bin/docker'), (1, 'unix:///run/other/docker.sock'), (2, '/srv/other-docker-config'),
])
def test_assembly_rejects_each_mismatched_writer_docker_component(composed, component, value):
    docker = list(composed.config.docker)
    docker[component] = value
    with pytest.raises(Refused, match='^transition-writer-docker$'):
        composed.transition(writer_docker=tuple(docker))
    assert composed.popen_calls == [] and composed.world.pg.connections == 0
    assert composed.docker.ids == {} and composed.nginx_io.calls == [] and composed.bridge_io.calls == []
    assert_no_window_effects(composed)


def test_assemble_real_writer_candidate_path_replay_and_secret_isolation(composed):
    transition, writers = composed.transition()
    result = transition.run()
    assert result['status'] == 'a9-backend-smoked' and result['production_ready'] is False
    assert writers.declared == frozenset(LEGACY.values())
    assert writers.observe(writers.scope, timeout=5) == 0
    with pytest.raises(Refused, match='window-writers-candidate-binding'):
        writers.bind_candidate(transition.candidate_writer)
    world = composed.world
    starts, requests = world.cdocker.starts, len(world.requests)
    replay, fresh_writers = composed.transition()
    with pytest.raises(Refused, match='^transition-stopped$'):
        replay.run()
    assert replay.recovery()['state'] == 'a9-complete'
    assert world.cdocker.starts == starts == 1 and len(world.requests) == requests == 1
    assert fresh_writers.declared == frozenset(LEGACY.values())
    world.consumers_held()
    assert all(b.observe(b.scope, timeout=5) == 'blocked' for b in composed.ingress.values())
    assert 'SENTINEL' not in (world.tmp / 'assembled-journal' / 'journal.jsonl').read_text()
    assert 'SENTINEL' not in json.dumps(result)


def test_pool_masks_remote_session_but_pg_guard_stops_a9(composed):
    transition, writers = composed.transition()
    composed.world.cdocker.on_start = lambda: setattr(composed.world.pg, 'writers', 1)
    with pytest.raises(Refused, match='^database-writing-session$'):
        transition.run()
    # Two idle backend sockets hide one remote session in attribution, never in the PG guard.
    assert writers.observe(writers.scope, timeout=5) == 0
    assert composed.world.journal.last('transition-a9-complete') is None
    assert composed.world.journal.last('transition-failed')['legacy_resume_allowed'] is False
    composed.world.consumers_held()


def test_assembly_cannot_predeclare_a_candidate_consumer(composed):
    with pytest.raises(Refused, match='^transition-writer-declarations$'):
        composed.transition(declared_containers=(*LEGACY.values(), CANDIDATE_IDS['queue-worker']))
    assert composed.popen_calls == [] and composed.world.pg.connections == 0


def test_composed_pending_backup_stops_without_second_request(composed):
    transition, _ = composed.transition()
    composed.world.on_backup = lambda _: (_ for _ in ()).throw(KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        transition.run()
    assert composed.world.journal.last('ddl-marker') is None
    assert len(composed.world.requests) == 1
    effects = list(composed.world.legacy_effects())
    replay, _ = composed.transition()
    with pytest.raises(Refused, match='^transition-backup-ambiguous$'):
        replay.run()
    assert composed.world.legacy_effects() == effects and len(composed.world.requests) == 1
    assert composed.world.migrate.applied == []


@pytest.mark.parametrize('role', ['backend', 'cron-worker'])
def test_premature_candidate_without_sockets_refuses_before_containment(composed, role):
    w = composed.world
    w.cdocker(w.spec.compose_argv(), timeout=5, max_output=65536)
    w.cdocker._run(CANDIDATE_IDS[role])
    composed.docker.pool = 0
    transition, writers = composed.transition()
    with pytest.raises(Refused, match='^candidate-project-not-empty$'):
        transition.candidate_writer(timeout=5)
    starts = w.cdocker.starts
    with pytest.raises(Refused, match='^observed-host-effect-failed$'):
        transition.run()
    assert transition.host.port.driver.refusals[-1] == 'driver-binding-failed'
    assert w.rig.docker.effects() == [] and w.migrate.applied == [] and w.requests == []
    assert w.cdocker.effects() == [w.spec.compose_argv()] and w.cdocker.starts == starts == 1
    assert w.journal.last('ddl-marker') is None
    assert not composed.ingress['external'].snippet.exists() and composed.nginx_io.live is False
    assert all(a[0].endswith('curl') or a[1:] == ('-T',) for a in composed.nginx_io.calls)
    assert composed.bridge_io.table is None and all(a[1:3] == ('-j', 'list') for a in composed.bridge_io.calls)
    assert writers.declared == frozenset(LEGACY.values())


def test_shared_namespace_with_foreign_id_remains_unknown(composed):
    transition, writers = composed.transition()
    composed.docker.shared = True
    composed.docker.extra['e' * 64] = True
    w, before = composed.world, []

    def after_start():
        before.append((list(w.legacy_effects()), list(w.cdocker.effects()), list(w.migrate.applied), len(w.requests),
                       list(composed.nginx_io.calls), list(composed.bridge_io.calls)))
    w.cdocker.on_start = after_start
    with pytest.raises(Refused, match='^observed-host-unknown-writer$'):
        transition.run()
    assert len(before) == 1
    legacy, candidate, migrations, backups, nginx, bridge = before[0]
    assert (w.legacy_effects(), w.cdocker.effects(), w.migrate.applied, len(w.requests)) == (
        legacy, candidate, migrations, backups)
    assert [a for a in composed.nginx_io.calls[len(nginx):] if not (a[0].endswith('curl') or a[1:] == ('-T',))] == []
    assert all(a[1:3] == ('-j', 'list') for a in composed.bridge_io.calls[len(bridge):])
    assert w.journal.last('transition-a9-complete') is None
    w.consumers_held()
    assert writers.declared == frozenset(LEGACY.values())
    assert writers.observe(writers.scope, timeout=5) == 2


@pytest.mark.parametrize('fault,code', [
    ('id', 'candidate-project-changed'), ('name', 'candidate-identity-mismatch'),
    ('project', 'candidate-identity-mismatch'), ('service', 'candidate-identity-mismatch'),
    ('image', 'candidate-image-mismatch'), ('revision', 'candidate-image-mismatch'),
    ('network', 'candidate-network-mismatch'), ('gate', 'candidate-gate-open'),
    ('started', 'candidate-backend-restarted'), ('restarts', 'candidate-backend-not-running'),
    ('policy', 'candidate-backend-not-running'), ('daemon', 'candidate-daemon-mismatch'),
    ('consumer', 'candidate-premature-running'),
])
def test_journal_bound_provider_refuses_every_identity_drift(world, fault, code):
    t = world.transition()
    t.run()
    original = t.candidate.runner
    before = list(world.cdocker.effects())
    if fault == 'id':
        world.cdocker.containers['f' * 64] = world.cdocker.containers.pop(CANDIDATE_IDS['backend'])
    if fault == 'consumer':
        world.cdocker._run(CANDIDATE_IDS['queue-worker'])
    effects_before = (list(world.legacy_effects()), list(world.migrate.applied), len(world.requests),
                      world.cdocker.starts, list(world.journal.events))

    def io(argv, **kwargs):
        rc, out = original(argv, **kwargs)
        if fault == 'daemon' and argv == INFO_ARGV:
            return 0, (json.dumps('00000000-0000-4000-8000-000000000001') + '\n').encode()
        if argv[:6] == ('docker', 'inspect', '--type', 'container', '--format', CANDIDATE_TEMPLATE):
            rows = [json.loads(line) for line in out.splitlines()]
            row = next((r for r in rows if r[1] == CANDIDATE_IDS['backend']), None)
            edits = {'name': (0, '/other'), 'project': (3, 'other'), 'service': (4, 'queue-worker'),
                     'image': (2, 'sha256:' + '0' * 64), 'revision': (5, '0' * 40),
                     'network': (18, [['other', [], '0' * 64], None]),
                     'gate': (16, ['ALLOW_REAL_SENDS=true', None]),
                     'started': (11, '2026-11-02T00:00:00.000000001Z'),
                     'restarts': (13, 1), 'policy': (14, 'always')}
            if fault in edits:
                index, value = edits[fault]
                row[index] = value
            return rc, ''.join(json.dumps(r) + '\n' for r in rows).encode()
        return rc, out
    t.candidate.runner = io
    with pytest.raises(Refused, match='^' + code + '$'):
        t.candidate_writer(timeout=5)
    assert world.cdocker.effects() == before
    assert (world.legacy_effects(), world.migrate.applied, len(world.requests), world.cdocker.starts,
            world.journal.events) == effects_before


def test_open_start_intent_never_adopts_or_retries(world):
    t = world.transition()
    world.cdocker.on_start = lambda: (_ for _ in ()).throw(KeyboardInterrupt)
    append = world.journal.append

    def interrupted(kind, **fields):
        if kind == 'transition-failed':
            raise KeyboardInterrupt
        return append(kind, **fields)
    world.journal.append = interrupted
    with pytest.raises(KeyboardInterrupt):
        t.run()
    world.journal.append = append
    calls = list(world.cdocker.calls)
    with pytest.raises(Refused, match='^candidate-start-ambiguous$'):
        t.candidate_writer(timeout=5)
    with pytest.raises(Refused, match='^transition-stopped$'):
        t.run()
    assert t.recovery()['state'] == 'candidate-ambiguous'
    assert world.cdocker.calls[:len(calls)] == calls and world.cdocker.starts == 1
    assert world.journal.last('transition-done', 'a9:start-backend') is None


@pytest.mark.parametrize('fault', ['partial', 'duplicate'])
def test_writer_inspect_requires_exact_id_coverage(tmp_path, fault):
    binding, _ = _writers(tmp_path, {}, {LEGACY['backend']: []})
    io = binding._run_command

    def malformed(argv, **kwargs):
        rc, out = io(argv, **kwargs)
        if argv[5] == 'inspect':
            return rc, b'' if fault == 'partial' else out + b'\n' + out
        return rc, out
    binding._run_command = malformed
    with pytest.raises(Refused, match='^window-writers-docker$'):
        binding.observe(binding.scope, timeout=5)


@pytest.mark.parametrize('fault', ['partial', 'duplicate'])
def test_candidate_provider_requires_exact_inspect_coverage(world, fault):
    t = world.transition()
    t.run()
    source = t.candidate.runner

    def malformed(argv, **kwargs):
        rc, out = source(argv, **kwargs)
        if argv[:6] == ('docker', 'inspect', '--type', 'container', '--format', CANDIDATE_TEMPLATE):
            rows = out.splitlines(keepends=True)
            return rc, b''.join(rows[:-1] if fault == 'partial' else [*rows, rows[-1]])
        return rc, out
    t.candidate.runner = malformed
    with pytest.raises(Refused, match='^candidate-inspect-malformed$'):
        t.candidate_writer(timeout=5)


def test_provider_budget_decreases_across_project_and_inspect(world, monkeypatch):
    import first_transition_candidate as candidate_module
    import first_transition_orchestrator as orchestrator_module
    t = world.transition()
    t.run()
    clock = [0.0]
    time = SimpleNamespace(monotonic=lambda: clock[0])
    monkeypatch.setattr(candidate_module, 'time', time)
    monkeypatch.setattr(orchestrator_module, 'time', time)
    source, limits = t.candidate.runner, []

    def slow_io(argv, **kwargs):
        limits.append(kwargs['timeout'])
        out = source(argv, **kwargs)
        clock[0] += 0.05
        return out
    t.candidate.runner = slow_io
    before = list(world.cdocker.effects())
    with pytest.raises(Refused, match='^candidate-timeout$'):
        t.candidate_writer(timeout=0.16)
    assert limits == pytest.approx([0.16, 0.11, 0.06, 0.01])
    assert world.cdocker.effects() == before


def test_deadline_expires_inside_driver_callback_before_any_effect(composed, monkeypatch):
    import first_transition_candidate as candidate_module
    import first_transition_host_driver as driver_module
    import first_transition_orchestrator as orchestrator_module
    transition, writers = composed.transition()
    clock, expired = [0.0], []
    time = SimpleNamespace(monotonic=lambda: clock[0])
    for module in (candidate_module, driver_module, orchestrator_module, wb):
        monkeypatch.setattr(module, 'time', time)

    def finish_after_deadline(argv):
        if argv == composed.world.spec.ps_argv():
            expired.append(argv)
            clock[0] += 11  # inspect-host has one shared 10s deadline, including its callbacks
    composed.on_popen = finish_after_deadline
    with pytest.raises(Refused, match='^observed-host-timeout$'):
        transition.run()
    assert expired == [composed.world.spec.ps_argv()]
    assert writers.declared == frozenset(LEGACY.values())
    assert composed.world.journal.last('observed-host-intent') is None
    assert_no_window_effects(composed)


def test_open_create_intent_is_not_adopted_or_repeated(world):
    t = world.transition()
    world.cdocker.on_create = lambda: (_ for _ in ()).throw(KeyboardInterrupt)
    append = world.journal.append

    def interrupted(kind, **fields):
        if kind == 'transition-failed':
            raise KeyboardInterrupt
        return append(kind, **fields)
    world.journal.append = interrupted
    with pytest.raises(KeyboardInterrupt):
        t.run()
    world.journal.append = append
    effects = (list(world.legacy_effects()), list(world.cdocker.effects()), list(world.migrate.applied),
               len(world.requests), world.cdocker.starts)
    with pytest.raises(Refused, match='^candidate-project-not-empty$'):
        t.candidate_writer(timeout=5)
    with pytest.raises(Refused, match='^transition-stopped$'):
        t.run()
    assert t.recovery()['state'] == 'candidate-ambiguous'
    assert (world.legacy_effects(), world.cdocker.effects(), world.migrate.applied, len(world.requests),
            world.cdocker.starts) == effects
    assert world.journal.last('transition-done', 'a9:create') is None
    assert world.journal.last('transition-intent', 'a9:start-backend') is None


@pytest.mark.parametrize('fault', ['identity', 'visibility', 'read-only', 'ledger', 'catalog', 'index', 'lease'])
def test_post_start_pg_observation_keeps_identity_and_quiet_guards(world, fault):
    def corrupt():
        if fault == 'identity':
            world.pg.oid += 1
        elif fault == 'visibility':
            world.pg.visible = False
        elif fault == 'read-only':
            world.pg.read_only = 'off'
        elif fault == 'ledger':
            world.pg.ledger.pop()
        elif fault == 'catalog':
            world.pg.extra_ddl.append('unexpected')
        elif fault == 'index':
            world.pg.builds = 1
        else:
            world.pg.leases[next(iter(world.pg.leases))] = 1
    world.cdocker.on_start = corrupt
    t = world.transition()
    with pytest.raises(Refused, match='^database-|^final-ledger$'):
        t.run()
    assert world.journal.last('transition-a9-complete') is None
    assert world.journal.last('transition-failed')['legacy_resume_allowed'] is False
    world.consumers_held()


@pytest.mark.parametrize('url', [
    'postgres://u:p@db.example.invalid/app', 'postgresql:///app', 'postgresql://u:p@%2Ftmp/app',
    'postgresql://u:p@db.example.invalid,other.invalid/app', 'postgresql://u:p@db.example.invalid/app#secret',
    'postgresql://u:p@db.example.invalid/app?sslmode=require&sslmode=disable',
    *['postgresql://u:p@db.example.invalid/app?' + key + '=sentinel' for key in
      ('host', 'hostaddr', 'port', 'dbname', 'service', 'options', 'user', 'passfile', 'servicefile', 'unknown')],
    'postgresql://u:p@db.example.invalid:bad/app', 'postgresql://u:p@db.example.invalid/other',
    'postgresql://u:p@db.example.invalid/APP', 'postgresql://u:p@db.example.invalid:5433/app'])
def test_database_target_refusals_are_sanitized(url):
    from first_transition_candidate import check_candidate_database
    with pytest.raises(Refused, match='^window-candidate-database$') as error:
        check_candidate_database([('DATABASE_URL', url)], SECRET_URL)
    assert str(error.value) == 'window-candidate-database' and error.value.__cause__ is None


@pytest.mark.parametrize('name', [
    'DATABASE_url', 'agent_runtime_database_url', 'Private_Storage_Database_Url',
    'PRIVATE_SEND_DATABASE_url', 'private_summary_database_url', 'queue_worker_database_url',
    'PGHOST', 'pghostaddr', 'PgPort', 'PGDATABASE', 'PGSERVICE', 'pgservicefile', 'PGOPTIONS', 'PGSYSCONFDIR'])
def test_database_environment_noncanonical_or_retarget_refuses(name):
    from first_transition_candidate import check_candidate_database
    with pytest.raises(Refused, match='^window-candidate-database$'):
        check_candidate_database([('DATABASE_URL', SECRET_URL), (name, SECRET_URL)], SECRET_URL)


def test_optional_databases_are_counted_not_invented_and_duplicates_refuse():
    from first_transition_candidate import check_candidate_database, DATABASE_NAMES
    assert check_candidate_database([('DATABASE_URL', SECRET_URL)], SECRET_URL) == 5
    assert check_candidate_database([(name, SECRET_URL if name == 'DATABASE_URL' else '')
                                     for name in DATABASE_NAMES], SECRET_URL) == 5
    assert check_candidate_database([(name, SECRET_URL) for name in DATABASE_NAMES], SECRET_URL) == 0
    with pytest.raises(Refused, match='^window-candidate-database$'):
        check_candidate_database([('DATABASE_URL', SECRET_URL)] * 2, SECRET_URL)


@pytest.mark.parametrize('user,accepted', [('runtime.projecta', True), ('runtime.projectb', False),
                                          ('postgres', False), ('runtime.', False)])
def test_shared_supabase_pooler_requires_the_same_project_route(user, accepted):
    from first_transition_candidate import check_candidate_database
    host = 'aws-0-region.pooler.supabase.com:5432/postgres'
    source = 'postgresql://postgres.projecta:sentinel@' + host
    candidate = 'postgresql+psycopg2://' + user + ':different@' + host
    if accepted:
        assert check_candidate_database([('DATABASE_URL', candidate)], source) == 5
    else:
        with pytest.raises(Refused, match='^window-candidate-database$'):
            check_candidate_database([('DATABASE_URL', candidate)], source)
