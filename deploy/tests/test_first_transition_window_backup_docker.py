"""Real dump -> isolated clone -> replay of the 51, with Docker and the owned synthetic first_transition_test.

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

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import first_transition_database as fdb
import first_transition_window_backup as wb
from first_transition_adapter import digest, validate_clone_receipt
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
    url, _ = database
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
        clone_image=IMAGE, dump_network='host')
    request = dict(schema=BACKUP_REQUEST_SCHEMA, nonce='a' * 64, plan_digest=plan.digest,
                   source_identity=expected.identity, baseline_digest=expected.baseline_digest,
                   config_digest='b' * 64, quiescence_digest='c' * 64)
    backup = wb.WindowBackup(config, plan, expected, secret=lambda: url,
                             connect=fdb.psycopg2_connector(lambda: url))
    receipt = backup(request)

    validate_clone_receipt(receipt, plan, expected.identity, expected.baseline_digest)
    clone = receipt['clone_rehearsal']
    assert receipt['request_digest'] == digest(request) and clone['restored_catalog'] == before['catalog']
    assert (clone['applied'], clone['final_ledger'], clone['concurrent']) == (51, 129, 8)
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
