"""Real dump -> isolated clone -> replay of the 52, with Docker and the owned synthetic first_transition_test.

Opt-in only: FIRST_TRANSITION_LOCAL_URL/NONCE (owned disposable database, see
test_first_transition_adapter_pg), FIRST_TRANSITION_WINDOW_DOCKER=1 and a digest-pinned
PostgreSQL 17 image in FIRST_TRANSITION_WINDOW_IMAGE already present locally. Synthetic data only.
"""
from contextlib import closing
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
from first_transition_adapter import LocalDatabase, digest, validate_clone_receipt
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA
from test_first_transition_adapter_pg import database, plan  # noqa: F401  (shared fixtures)

IMAGE = os.environ.get('FIRST_TRANSITION_WINDOW_IMAGE', '')
DOCKER = '/usr/bin/docker'


def _docker(*args):
    return subprocess.run([DOCKER, *args], capture_output=True, text=True, timeout=60, check=False)


def test_real_window_backup_restores_and_replays_in_an_isolated_clone(plan, database, tmp_path):  # noqa: F811
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
    request = dict(schema=BACKUP_REQUEST_SCHEMA, nonce='a' * 64, plan_digest=plan.digest,
                   source_identity=expected.identity, baseline_digest=expected.baseline_digest,
                   config_digest='b' * 64, quiescence_digest='c' * 64)
    backup = wb.WindowBackup(config, plan, expected, secret=lambda: url,
                             connect=fdb.psycopg2_connector(lambda: url))
    receipt = backup(request)

    validate_clone_receipt(receipt, plan, expected.identity, expected.baseline_digest)
    clone = receipt['clone_rehearsal']
    assert receipt['request_digest'] == digest(request) and clone['restored_catalog'] == before['catalog']
    assert '20261112_160000_celula_alerta_regras.sql' in [m.name for m in plan.pending]
    assert (clone['applied'], clone['final_ledger'], clone['concurrent']) == (52, 130, 8)
    assert clone['restore_excluded'] == dict(vault_extension=0, vault_schema=0, event_triggers=0,
                                             event_trigger_names=[])
    assert clone['final_schema_digest'] != before['catalog']
    dump = Path(receipt['backup_path'])
    assert dump.read_bytes()[:5] == b'PGDMP' and stat.S_IMODE(os.lstat(dump).st_mode) == 0o600
    # The source is untouched (still the baseline) and no clone resource is left behind.
    with closing(psycopg2.connect(url)) as source:
        after = wb.clone_state(source)
    assert after['ledger'] == plan.baseline and after['catalog'] == before['catalog']
    label = 'label=igreja12.window-backup=igreja12-window-clone-' + digest(request)[:16]
    assert _docker('ps', '-aq', '--filter', label).stdout.strip() == ''
    assert _docker('network', 'ls', '-q', '--filter', label).stdout.strip() == ''


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
