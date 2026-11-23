"""Real dump -> isolated clone -> replay of the 52, with Docker and the owned synthetic first_transition_test.

Opt-in only: FIRST_TRANSITION_LOCAL_URL/NONCE (owned disposable database, see
test_first_transition_adapter_pg), FIRST_TRANSITION_WINDOW_DOCKER=1 and a digest-pinned
PostgreSQL 17 image in FIRST_TRANSITION_WINDOW_IMAGE already present locally. Synthetic data only.
"""
from contextlib import closing, contextmanager
import hashlib
import multiprocessing
import os
from pathlib import Path
import stat
import subprocess
import sys
import json
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import first_transition_database as fdb
import first_transition_window_backup as wb
from first_transition_adapter import LocalDatabase, Refused, digest, validate_clone_receipt
from first_transition_candidate import CLOSED_GATES, CandidatePort
from first_transition_host_contract import ObservedHostContract
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA, FirstTransition, MigrationExecutor, ProcessRunner
from initial_transition_files import Journal
from test_first_transition_adapter_pg import database, plan  # noqa: F401  (shared fixtures)
from test_first_transition_host_driver import LEGACY
from test_first_transition_orchestrator import World, pinned  # noqa: F401  (shared fixtures)

IMAGE = os.environ.get('FIRST_TRANSITION_WINDOW_IMAGE', '')
DOCKER = '/usr/bin/docker'


def _docker(*args):
    return subprocess.run([DOCKER, *args], capture_output=True, text=True, timeout=60, check=False)


@pytest.fixture
def window_backup(plan, database, tmp_path):  # noqa: F811
    if os.environ.get('FIRST_TRANSITION_WINDOW_DOCKER') != '1' or not wb.PINNED_IMAGE.fullmatch(IMAGE):
        pytest.skip('requires FIRST_TRANSITION_WINDOW_DOCKER=1 and a pinned local PostgreSQL 17 image')
    import psycopg2
    url, nonce = database
    # Role names survive the fixture's public-schema reset. Seed only this guarded,
    # owned synthetic cluster, never alter source/preexisting role attributes.
    from psycopg2 import sql
    with LocalDatabase(url, nonce) as owned:
        with owned.conn.cursor() as cur:
            for role in ('private_storage_runtime', 'private_send_runtime', 'private_summary_runtime',
                         'queue_worker_runtime'):
                cur.execute('SELECT rolcanlogin, rolinherit, rolsuper, rolcreatedb, rolcreaterole, rolreplication, '
                            'rolbypassrls FROM pg_roles WHERE rolname=%s', (role,))
                flags = cur.fetchone()
                if flags is None:
                    cur.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOINHERIT').format(sql.Identifier(role)))
                else:
                    assert flags == (False,) * 7
    with closing(psycopg2.connect(url)) as source:
        before = wb.clone_state(source)
    system, oid, name = before['identity']
    expected = fdb.DatabaseExpectation(digest([system, oid, name]), plan.baseline, before['catalog'])
    root, work, cli = tmp_path / 'window-root', tmp_path / 'clone-work', tmp_path / 'docker-cli'
    for path in (root, work, cli):
        path.mkdir(mode=0o700)
    config = wb.WindowBackupConfig(
        docker_binary=DOCKER, docker_endpoint='unix:///var/run/docker.sock', docker_config_dir=str(cli),
        backup_root=str(root), clone_workdir=str(work), python=sys.executable, dump_image=IMAGE,
        clone_image=IMAGE, dump_network='host',
        # The owned synthetic database has no vault schema and no event triggers: the window request still
        # requires the pin, so it states that nothing is excluded.
        restore_excluded_expected=(('event_trigger_names', ()), ('event_triggers', 0), ('vault_extension', 0),
                                   ('vault_schema', 0)))
    backup = wb.WindowBackup(config, plan, expected, secret=lambda: url,
                             connect=fdb.psycopg2_connector(lambda: url))
    return backup, before


def test_real_window_backup_restores_and_replays_in_an_isolated_clone(window_backup, plan, database, tmp_path):  # noqa: F811
    import psycopg2
    url, _ = database
    backup, before = window_backup
    expected = backup.expected
    request = dict(schema=BACKUP_REQUEST_SCHEMA, nonce='a' * 64, plan_digest=plan.digest,
                   source_identity=expected.identity, baseline_digest=expected.baseline_digest,
                   config_digest='b' * 64, quiescence_digest='c' * 64)
    receipt = backup(request)

    validate_clone_receipt(receipt, plan, expected.identity, expected.baseline_digest)
    clone = receipt['clone_rehearsal']
    assert receipt['request_digest'] == digest(request) and clone['restored_catalog'] == before['catalog']
    assert '20261112_160000_celula_alerta_regras.sql' in [m.name for m in plan.pending]
    assert (clone['applied'], clone['final_ledger'], clone['concurrent']) == (52, 130, 8)
    assert clone['restore_excluded'] == dict(vault_extension=0, vault_schema=0, event_triggers=0,
                                             event_trigger_names=[])
    assert clone['final_schema_digest'] != before['catalog']
    assert isinstance(receipt['dump_seconds'], float) and isinstance(receipt['restore_seconds'], float)
    assert isinstance(receipt['migrations_seconds'], float) and isinstance(receipt['max_migration_seconds'], float)
    assert receipt['max_migration_seconds'] <= 60.0
    assert len(clone['migration_timings']) == 52
    assert all(isinstance(t['seconds'], float) and 0 <= t['seconds'] <= 60.0 for t in clone['migration_timings'])
    assert clone['applicator_role'] == dict(
        role='postgres', restore_role='clone_admin', rolsuper=False, rolbypassrls=True, rolcreaterole=True,
        rolcreatedb=True, rolinherit=True, rolcanlogin=True, rolreplication=False, statement_timeout='2min')
    rls = clone['rls_grants_verified']
    assert rls['service_role_bypassrls'] is True and rls['non_service_roles_bypassrls'] is False
    assert set(rls['tables']) == {'cell_alerts', 'celula_alerta_regras', 'private_deletion_uploads',
                                  'private_summary_tasks'}
    assert all(info['rls'] and info['force_rls'] for info in rls['tables'].values())
    print(json.dumps({
        'dump_seconds': receipt['dump_seconds'],
        'restore_seconds': receipt['restore_seconds'],
        'migrations_seconds': receipt['migrations_seconds'],
        'max_migration_seconds': receipt['max_migration_seconds'],
        'total_seconds': receipt['seconds'],
        'applicator_role': clone['applicator_role'],
        'rls_grants_verified': clone['rls_grants_verified'],
        'slowest_5_migrations': sorted(clone['migration_timings'], key=lambda m: m['seconds'], reverse=True)[:5],
    }, sort_keys=True))
    dump = Path(receipt['backup_path'])
    assert dump.read_bytes()[:5] == b'PGDMP' and stat.S_IMODE(os.lstat(dump).st_mode) == 0o600
    # The source is untouched (still the baseline) and no clone resource is left behind.
    with closing(psycopg2.connect(url)) as source:
        after = wb.clone_state(source)
    assert after['ledger'] == plan.baseline and after['catalog'] == before['catalog']
    label = 'label=igreja12.window-backup=igreja12-window-clone-' + digest(request)[:16]
    assert _docker('ps', '-aq', '--filter', label).stdout.strip() == ''
    assert _docker('network', 'ls', '-q', '--filter', label).stdout.strip() == ''
    # Apply the 52 pending migrations to source (starting without btree_gist) and prove Q_CATALOG parity with clone.
    source_work = tmp_path / 'source-migrate'
    source_work.mkdir(mode=0o700)
    executor = MigrationExecutor(plan, python=sys.executable, workdir=str(source_work), secret=lambda: url,
                                 runner=ProcessRunner(binaries=(sys.executable,)))
    for index, migration in enumerate(plan.pending, 1):
        assert executor.apply(index, migration) == 0
    with closing(psycopg2.connect(url)) as source:
        migrated_source = wb.clone_state(source)
    assert migrated_source['ledger'] == tuple(sorted(m.name for m in plan.migrations))
    assert migrated_source['invalid'] == 0
    assert migrated_source['catalog'] == clone['final_schema_digest']


def legacy_simulator(pipe, endpoint, gates, effects):
    """A separate local service with private IPC, real read-only DB requests and a fake send sink."""
    import psycopg2
    with pipe:
        while True:
            request = pipe.recv()
            if request == 'stop':
                return
            if request == 'send':
                if gates != CLOSED_GATES:
                    effects.write_text('synthetic delivery\n')
                pipe.send('blocked' if gates == CLOSED_GATES else 'sent')
                continue
            assert request == 'ready'
            with closing(psycopg2.connect(**endpoint, connect_timeout=5)) as conn:
                conn.set_session(readonly=True)
                with conn.cursor() as cursor:
                    cursor.execute("""SELECT i.nome, p.nome, p.telefone, p.tipo, f.payload
                        FROM public.first_transition_fixture f JOIN public.igrejas i ON i.id=f.igreja_id
                        JOIN public.pessoas p ON p.igreja_id=i.id ORDER BY i.id, p.id""")
                    data = cursor.fetchall()
                    cursor.execute(fdb.Q_LEDGER)
                    pipe.send((data, tuple(row[0] for row in cursor.fetchall()), gates))


@contextmanager
def legacy_service(endpoint, gates, effects):
    ctx = multiprocessing.get_context('spawn')
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=legacy_simulator, args=(child, endpoint, gates, effects))
    proc.start()
    child.close()

    def request(command):
        parent.send(command)
        if command != 'stop':
            assert parent.poll(10), 'synthetic legacy service did not respond'
            return parent.recv()

    try:
        yield proc, request
    finally:
        if proc.is_alive():
            proc.terminate()
        proc.join(10)
        parent.close()
        assert not proc.is_alive()


class LoseMigrationResult(MigrationExecutor):
    """Execute the real pinned DDL, then inject lost acknowledgement after commit."""

    applied = 0

    def apply(self, index, migration):
        result = super().apply(index, migration)
        assert result == 0
        self.applied += 1
        if migration.name == '20261016_180000_prayer_requests.sql':
            raise TimeoutError('synthetic result lost after commit')
        return result


def test_recovers_legacy_service_from_marker_dump_after_committed_ddl(
    window_backup, plan, database, pinned, tmp_path,  # noqa: F811
):
    import psycopg2
    from psycopg2.extensions import parse_dsn

    url, _ = database
    backup, baseline = window_backup
    expected = backup.expected
    assert baseline['ledger'] == plan.baseline and len(plan.baseline) == 78 and baseline['invalid'] == 0
    world = World((plan, *pinned[1:]), tmp_path)
    observed = fdb.ReadOnlyDatabase(backup.connect)
    baseline_roles = wb.source_role_names(backup.connect)
    baseline_extensions = wb.source_public_extensions(backup.connect)
    queue_before = world.rig.docker.redis.copy()
    effects = tmp_path / 'effect-sink'
    receipts = []
    executor = LoseMigrationResult(plan, python=sys.executable, workdir=str(tmp_path / 'work'),
                                   secret=lambda: url, runner=ProcessRunner(binaries=(sys.executable,)))

    def take_backup(request):
        receipt = backup(request)
        receipts.append(receipt)
        return receipt

    def assert_effects_closed():
        world.assert_legacy_contained()
        assert world.rig.docker.redis == queue_before
        assert not effects.exists()
        assert world.cdocker.calls == [] and world.layouts == []

    def assemble_transition(journal):
        return FirstTransition(
            plan=plan, journal=journal, host=ObservedHostContract(world.transport, journal),
            database=observed, expected=expected, backup_proof=take_backup, executor=executor,
            layout=world.layout, candidate=CandidatePort(world.spec, runner=world.cdocker),
            config_digest='f' * 64,
        )

    with legacy_service(parse_dsn(url), CLOSED_GATES, effects) as (old_proc, old_service):
        old_ready = old_service('ready')
        assert old_ready == ([
            ('Synthetic restore fixture', 'Synthetic restore person', '550000000009', 'contato',
             'fictitious restore payload'),
        ], plan.baseline, CLOSED_GATES)
        assert old_service('send') == 'blocked'

        def stop_backend(argv):
            if argv[3] == LEGACY['backend']:
                old_service('stop')
                old_proc.join(10)
                assert old_proc.exitcode == 0

        world.rig.docker.after['kill'] = stop_backend
        with Journal(tmp_path / 'journal') as journal:
            transition = assemble_transition(journal)
            with pytest.raises(Refused, match='^migration-timeout$'):
                transition.run()
            assert not old_proc.is_alive()
            assert_effects_closed()

            marker = journal.last('ddl-marker')
            saved = journal.last('transition-backup')
            receipt, = receipts
            dump = Path(receipt['backup_path'])
            assert dump.name == 'window.dump'
            assert hashlib.sha256(dump.read_bytes()).hexdigest() == marker['window_backup_id'] == saved['backup_id']
            assert digest(saved['receipt']) == marker['backup_digest'] == saved['receipt_digest']
            assert marker['backup_request_digest'] == receipt['request_digest']
            state = transition.recovery()
            assert state['state'] == 'ddl-ambiguous'
            assert state['open_steps'] == ['migration:20261016_180000_prayer_requests.sql']
            assert not any(state[k] for k in ('legacy_resume_allowed', 'destructive_retry', 'automatic_restore'))
            changed = observed.observe()
            assert executor.applied == 5
            assert changed['ledger'] == tuple(sorted((*plan.baseline, *(m.name for m in plan.pending[:5]))))
            assert changed['catalog'] != baseline['catalog']
            with closing(psycopg2.connect(url)) as source, source.cursor() as cur:
                cur.execute("SELECT to_regclass('public.pedido_oracao') IS NOT NULL")
                assert cur.fetchone() == (True,)
            journal_path = tmp_path / 'journal' / 'journal.jsonl'
            journal_before = journal_path.read_bytes()
            journal.close()
            with Journal(journal_path.parent) as reopened:
                replay = assemble_transition(reopened)
                assert replay.recovery() == state
                with pytest.raises(Refused, match='^transition-stopped$'):
                    replay.run()
                with pytest.raises(Refused, match='^post-ddl-resume-forbidden$'):
                    replay.resume_legacy(replay.host.resume_token())
            assert journal_path.read_bytes() == journal_before
            assert executor.applied == 5 and len(receipts) == 1 and observed.observe() == changed
            assert_effects_closed()

            name = 'igreja12-window-recovery-' + uuid4().hex
            password = 'synthetic-' + uuid4().hex
            restore_work = tmp_path / 'recovery-restore'
            restore_work.mkdir(mode=0o700)
            try:
                address, admin = backup._start_clone(name, password)
                with closing(admin):
                    backup._prepare_clone(admin, baseline_roles, password)
                endpoint = dict(host=address, port=5432, dbname=wb.CLONE_DB, user=backup.config.admin_user,
                                password=password)
                with closing(psycopg2.connect(**endpoint)) as target, target.cursor() as cur:
                    cur.execute("SELECT to_regclass('public.schema_migrations') IS NULL")
                    assert cur.fetchone() == (True,)
                backup._prepare_clone_extensions(address, password, baseline_extensions)
                assert backup._restore(name, dump, password, restore_work) == receipt['clone_rehearsal']['restore_excluded']
                restored = backup._state(address, password)
                assert restored['identity'] != baseline['identity']
                assert restored['ledger'] == plan.baseline and restored['invalid'] == 0
                assert restored['catalog'] == baseline['catalog']
                with closing(psycopg2.connect(**endpoint)) as target, target.cursor() as cur:
                    cur.execute("SELECT to_regclass('public.pedido_oracao') IS NULL")
                    assert cur.fetchone() == (True,)
                    cur.execute("SELECT count(*) FROM pg_index WHERE NOT indisvalid")
                    assert cur.fetchone() == (0,)
                with legacy_service(endpoint, CLOSED_GATES, effects) as (new_proc, new_service):
                    assert new_proc.is_alive() and new_service('ready') == old_ready
                    assert new_service('send') == 'blocked'
                    assert_effects_closed()
                    new_service('stop')
                    new_proc.join(10)
                    assert new_proc.exitcode == 0
                assert observed.observe() == changed and journal_path.read_bytes() == journal_before
                print(json.dumps(dict(
                    application_sha=plan.application_sha, executor_sha=plan.executor_sha, plan_digest=plan.digest,
                    backup_sha256=marker['window_backup_id'], backup_request_digest=marker['backup_request_digest'],
                    backup_receipt_digest=marker['backup_digest'], baseline_ledger_sha256=digest(list(plan.baseline)),
                    catalog=restored['catalog'], migrated_catalog=changed['catalog'], committed_migrations=5,
                    restored_ledger=len(restored['ledger']), recovery=state['state'], invalid_indexes=0,
                    legacy_service_ready=True, gates=CLOSED_GATES, simulated_delivery_blocked=True,
                ), sort_keys=True))
            finally:
                backup._cleanup(name)
            label = 'label=igreja12.window-backup=' + name
            for args in (('ps', '-aq'), ('network', 'ls', '-q')):
                result = _docker(*args, '--filter', label)
                assert result.returncode == 0 and not result.stdout.strip()


@pytest.mark.parametrize('gate', ['allow_real_sends', 'Allow_Real_Sends'])
@pytest.mark.parametrize('value', ['true', 'false'])
def test_real_gate_projection_preserves_noncanonical_names_without_other_env(gate, value):
    if os.environ.get('FIRST_TRANSITION_WINDOW_DOCKER') != '1':
        pytest.skip('requires explicit local synthetic Docker opt-in')
    from first_transition_candidate import CANDIDATE_TEMPLATE, CandidatePort
    from initial_transition_ops import Refused
    image = 'postgres@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929'
    name = 'igreja12-gate-projection-' + uuid4().hex
    sentinel = 'SENTINEL-UNRELATED-ENV'
    created = None
    try:
        created = _docker('create', '--pull=never', '--name', name, '--label', 'igreja12.gate-projection=' + name,
                          '--tmpfs', '/var/lib/postgresql/data',
                          '--env', 'ALLOW_REAL_SENDS=false', '--env', gate + '=' + value,
                          '--env', 'UNRELATED_SECRET=' + sentinel, image)
        assert created.returncode == 0
        result = _docker('inspect', '--type', 'container', '--format', CANDIDATE_TEMPLATE, name)
        assert result.returncode == 0 and sentinel not in result.stdout and 'UNRELATED_SECRET' not in result.stdout
        row = json.loads(result.stdout)
        assert row[6] == 'created' and row[7] is False  # never started
        assert row[12] is None  # Docker omits Health until a healthcheck exists.
        assert row[16][-1] is None
        assert sorted(row[16][:-1]) == sorted(['ALLOW_REAL_SENDS=false', gate + '=' + value])
        with pytest.raises(Refused, match='^candidate-inspect-gates$'):
            CandidatePort._row(row)
    finally:
        # UUID name belongs only to this test. Nothing is started or removed by label/glob.
        if created is not None and created.returncode == 0:
            assert _docker('rm', '-f', '-v', name).returncode == 0


def test_real_projection_accepts_created_container_without_optional_health_or_mount_name(tmp_path):
    if os.environ.get('FIRST_TRANSITION_WINDOW_DOCKER') != '1':
        pytest.skip('requires explicit local synthetic Docker opt-in')
    from first_transition_candidate import CANDIDATE_TEMPLATE, CandidatePort
    image = 'postgres@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929'
    name = 'igreja12-gate-projection-' + uuid4().hex
    created = None
    try:
        created = _docker('create', '--pull=never', '--name', name, '--label', 'igreja12.gate-projection=' + name,
                          '--tmpfs', '/var/lib/postgresql/data',
                          '--mount', 'type=bind,source=' + str(tmp_path) + ',destination=/synthetic,readonly',
                          '--env', 'ALLOW_REAL_SENDS=false', image)
        assert created.returncode == 0
        result = _docker('inspect', '--type', 'container', '--format', CANDIDATE_TEMPLATE, name)
        assert result.returncode == 0
        row = json.loads(result.stdout)
        assert row[6] == 'created' and row[7] is False and row[12] is None
        assert row[17] == [['bind', None, str(tmp_path), '/synthetic', False], None]
        state = CandidatePort._row(row)
        assert state['health'] is None and state['gates'] == {'ALLOW_REAL_SENDS': 'false'}
    finally:
        if created is not None and created.returncode == 0:
            assert _docker('rm', '-f', '-v', name).returncode == 0
