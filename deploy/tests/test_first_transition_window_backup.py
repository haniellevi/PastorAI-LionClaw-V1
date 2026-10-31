"""Window backup provider and window entry point: synthetic Docker/PostgreSQL only, no socket."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import types

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_database as fdb
import first_transition_window as window
import first_transition_window_backup as wb
from first_transition_adapter import digest, prepare, validate_clone_receipt
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA
from initial_transition_ops import Refused

ROOT = Path(__file__).resolve().parents[2]
SOURCE_URL = 'postgresql://postgres.synthetic:source-secret-value@source.invalid:5432/postgres'
IMAGE = 'registry.invalid/postgres@sha256:' + 'a' * 64
CLONE_IMAGE = 'registry.invalid/clone@sha256:' + 'b' * 64
DUMP = b'PGDMP' + b'synthetic custom archive'
RESTORED_ROWS = [('relation', 'igrejas', '0' * 32), ('policy', 'igrejas.tenant', '1' * 32)]
FINAL_ROWS = RESTORED_ROWS + [('relation', 'novas', '2' * 32)]


@pytest.fixture(scope='module')
def plan():
    return prepare(ROOT)


class Cursor:
    def __init__(self, clone, log):
        self.clone, self.log, self.rows = clone, log, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        text = query if isinstance(query, str) else repr(query)
        self.log.append(text)
        clone = self.clone
        if query == fdb.Q_IDENTITY:
            self.rows = [('7000000000000000001', 16384, wb.CLONE_DB)]
        elif query == fdb.Q_LEDGER:
            self.rows = [(n,) for n in clone.ledger()]
        elif query == fdb.Q_INVALID:
            self.rows = [('broken_idx',)] if clone.invalid else []
        elif query == fdb.Q_CATALOG:
            self.rows = clone.catalog_rows()
        elif query == fdb.Q_PATH or query == fdb.Q_TIMEOUT:
            self.rows = [('ok',)]
        elif query == wb.Q_SOURCE_ROLES:
            self.rows = [('anon',), ('authenticated',), ('postgres',), ('service_role',)]
        elif text == 'SELECT rolname FROM pg_roles':
            self.rows = [('postgres',)]
        else:
            self.rows = []

    def fetchall(self):
        return list(self.rows)


class Conn:
    def __init__(self, clone, log):
        self.clone, self.log, self.autocommit, self.closed = clone, log, False, False

    def cursor(self):
        return Cursor(self.clone, self.log)

    def close(self):
        self.closed = True


class Host:
    """Synthetic Docker CLI + clone cluster + migrate.py child, recording every call."""

    def __init__(self, plan, *, fail=None, catalog=None, invalid=False, leftover=False):
        self.plan, self.fail, self.invalid, self.leftover = plan, fail or set(), invalid, leftover
        self.calls, self.migrations, self.sql, self.restored = [], [], [], False
        self.catalog_override = catalog

    def ledger(self):
        if not self.restored:
            return ()
        return tuple(sorted([*self.plan.baseline, *(m.name for m in self.plan.pending[:len(self.migrations)])]))

    def catalog_rows(self):
        if self.catalog_override is not None:
            return self.catalog_override
        return FINAL_ROWS if self.migrations else RESTORED_ROWS

    def run(self, argv, *, stdin, stdout, stderr, env, timeout, close_fds, shell, check):
        assert argv[:5] == ['/usr/bin/docker', '--config', '/state/docker-cli', '--host', 'unix:///run/docker.sock']
        assert shell is False and close_fds is True and set(env) >= {'PATH', 'LC_ALL'}
        args = argv[5:]
        self.calls.append((tuple(args), dict(env)))
        verb = 'dump' if args[:2] == ['run', '--rm'] else 'clone' if args[:2] == ['run', '-d'] else args[0]
        if verb == 'exec':
            assert stdin.read().startswith(b'PGDMP')
            self.restored = 'restore' not in self.fail
        out = b''
        if verb == 'dump' and 'dump' not in self.fail:
            stdout.write(DUMP)
        if verb == 'inspect':
            out = b'172.30.0.2\n'
        if verb == 'ps' and self.leftover:
            out = b'abc123\n'
        failed = {'dump': 'dump', 'clone': 'clone', 'exec': 'restore'}.get(verb) in self.fail
        return types.SimpleNamespace(returncode=1 if failed else 0, stdout=out)

    def migrate(self, argv, **kwargs):
        self.migrations.append((tuple(argv), dict(kwargs['env'])))
        failed = 'migration' in self.fail and len(self.migrations) == 3
        return types.SimpleNamespace(returncode=1 if failed else 0)

    def clone_connect(self, *, host, dbname, user, password, timeout):
        assert host == '172.30.0.2' and password and password not in SOURCE_URL
        return Conn(self, self.sql)


def source_connect(*, timeout):
    return Conn(None, [])


def config(tmp_path, **overrides):
    root, work = tmp_path / 'backups', tmp_path / 'clone-work'
    root.mkdir(mode=0o700, exist_ok=True)
    work.mkdir(mode=0o700, exist_ok=True)
    values = dict(docker_binary='/usr/bin/docker', docker_endpoint='unix:///run/docker.sock',
                  docker_config_dir='/state/docker-cli', backup_root=str(root), clone_workdir=str(work),
                  python='/opt/venv/bin/python',
                  dump_image=IMAGE, clone_image=CLONE_IMAGE, clone_superusers=('postgres',))
    values.update(overrides)
    return wb.WindowBackupConfig(**values)


def expectation(plan, rows=RESTORED_ROWS):
    return fdb.DatabaseExpectation('c' * 64, plan.baseline, digest([list(r) for r in rows]))


def request(plan, expected, **overrides):
    value = dict(schema=BACKUP_REQUEST_SCHEMA, nonce='d' * 64, plan_digest=plan.digest,
                 source_identity=expected.identity, baseline_digest=expected.baseline_digest,
                 config_digest='e' * 64, quiescence_digest='f' * 64)
    value.update(overrides)
    return value


def provider(plan, tmp_path, host, expected=None, **overrides):
    return wb.WindowBackup(config(tmp_path, **overrides), plan, expected or expectation(plan),
                           secret=lambda: SOURCE_URL, connect=source_connect, run=host.run,
                           clone_connect=host.clone_connect, migrate_run=host.migrate, sleep=lambda s: None)


def verbs(host):
    return [c[0][:2] for c in host.calls]


def test_receipt_attests_request_and_passes_the_orchestrator_validation(plan, tmp_path):
    host, expected = Host(plan), expectation(plan)
    backup = provider(plan, tmp_path, host, expected)
    req = request(plan, expected)
    receipt = backup(req)
    validate_clone_receipt(receipt, plan, expected.identity, expected.baseline_digest)
    assert receipt['request_digest'] == digest(req) and receipt['restore_verified'] is True
    clone = receipt['clone_rehearsal']
    assert clone['applied'] == 51 and clone['final_ledger'] == 129 and clone['concurrent'] == 8
    assert clone['final_schema_digest'] == digest([list(r) for r in FINAL_ROWS])
    assert clone['restored_catalog'] == expected.catalog and clone['roles_created'] == 3
    dump = Path(receipt['backup_path'])
    assert dump.read_bytes() == DUMP and receipt['backup_id'] == hashlib.sha256(DUMP).hexdigest()
    assert stat.S_IMODE(os.lstat(dump).st_mode) == 0o600 and stat.S_IMODE(os.lstat(dump.parent).st_mode) == 0o700
    assert dump.parent.name == digest(req)


def test_secrets_never_reach_argv_receipt_or_the_clone(plan, tmp_path):
    host = Host(plan)
    receipt = provider(plan, tmp_path, host)(request(plan, expectation(plan)))
    assert all(SOURCE_URL not in ' '.join(args) for args, _ in host.calls)
    dumps = [(args, env) for args, env in host.calls if args[:2] == ('run', '--rm')]
    assert len(dumps) == 1 and dumps[0][1][wb.SOURCE_ENV] == SOURCE_URL and '-e' in dumps[0][0]
    assert all(wb.SOURCE_ENV not in env for args, env in host.calls if args[:2] != ('run', '--rm'))
    password = next(env[wb.CLONE_ENV] for args, env in host.calls if args[:2] == ('run', '-d'))
    assert all(password not in ' '.join(args) for args, _ in host.calls)
    assert all(password not in ' '.join(argv) and SOURCE_URL not in env['MIGRATION_DATABASE_URL']
               for argv, env in host.migrations)
    text = json.dumps(receipt)
    assert SOURCE_URL not in text and 'source-secret-value' not in text and password not in text


def test_clone_is_isolated_and_only_own_resources_are_removed(plan, tmp_path):
    host, expected = Host(plan), expectation(plan)
    req = request(plan, expected)
    provider(plan, tmp_path, host, expected)(req)
    name = 'igreja12-window-clone-' + digest(req)[:16]
    calls = [args for args, _ in host.calls]
    assert ('network', 'create', '--internal', '--label', 'igreja12.window-backup=' + name, name) in calls
    clone = next(a for a in calls if a[:2] == ('run', '-d'))
    assert clone[clone.index('--network') + 1] == name and CLONE_IMAGE in clone
    assert calls[-3:] == [('rm', '-f', '-v', name), ('network', 'rm', name),
                          ('ps', '-a', '--filter', 'label=igreja12.window-backup=' + name, '--format', '{{.ID}}')]
    assert not any('prune' in a or 'pastorai' in ' '.join(a) for a in calls)


def test_pending_migrations_replay_one_per_invocation_with_pinned_executor(plan, tmp_path):
    host = Host(plan)
    provider(plan, tmp_path, host)(request(plan, expectation(plan)))
    names = [argv[4] for argv, _ in host.migrations]
    assert names == [m.name for m in plan.pending]
    assert sum('--no-transaction' in argv for argv, _ in host.migrations) == 8
    assert all(argv[0] == '/opt/venv/bin/python' and argv[1] == '-I' for argv, _ in host.migrations)
    scripts = {Path(argv[2]).read_bytes() for argv, _ in host.migrations}
    assert scripts == {plan.executor}


def test_provider_is_single_use_and_never_reuses_a_run_directory(plan, tmp_path):
    host, expected = Host(plan), expectation(plan)
    backup = provider(plan, tmp_path, host, expected)
    backup(request(plan, expected))
    with pytest.raises(Refused, match='^window-backup-already-used$'):
        backup(request(plan, expected))
    other = Host(plan)
    with pytest.raises(Refused, match='^window-backup-run-exists$'):
        provider(plan, tmp_path, other, expected)(request(plan, expected))
    assert other.calls == []


@pytest.mark.parametrize('field, value', [('schema', 'other/1'), ('source_identity', '0' * 64),
                                          ('baseline_digest', '0' * 64), ('plan_digest', '0' * 64),
                                          ('nonce', 'short')])
def test_foreign_request_refuses_before_any_effect(plan, tmp_path, field, value):
    host, expected = Host(plan), expectation(plan)
    with pytest.raises(Refused, match='^window-backup-request$'):
        provider(plan, tmp_path, host, expected)(request(plan, expected, **{field: value}))
    assert host.calls == [] and not any((tmp_path / 'backups').iterdir())


def test_dump_failure_starts_no_clone(plan, tmp_path):
    host = Host(plan, fail={'dump'})
    with pytest.raises(Refused, match='^window-backup-dump-failed$'):
        provider(plan, tmp_path, host)(request(plan, expectation(plan)))
    assert verbs(host) == [('run', '--rm')] and host.migrations == []


@pytest.mark.parametrize('kwargs, code', [
    (dict(fail={'restore'}), 'window-backup-restore-failed'),
    (dict(catalog=[('relation', 'outra', '9' * 32)]), 'window-backup-restore-catalog'),
    (dict(invalid=True), 'window-backup-restore-invalid-index'),
    (dict(fail={'migration'}), 'window-backup-clone-migration-failed'),
])
def test_clone_failures_refuse_and_still_remove_the_clone(plan, tmp_path, kwargs, code):
    host = Host(plan, **kwargs)
    with pytest.raises(Refused, match='^' + code + '$'):
        provider(plan, tmp_path, host)(request(plan, expectation(plan)))
    assert [a[:2] for a, _ in host.calls][-3:] == [('rm', '-f'), ('network', 'rm'), ('ps', '-a')]
    if code != 'window-backup-clone-migration-failed':
        assert host.migrations == []
    else:
        assert len(host.migrations) == 3


def test_leftover_clone_after_cleanup_refuses(plan, tmp_path):
    with pytest.raises(Refused, match='^window-backup-cleanup-failed$'):
        provider(plan, tmp_path, Host(plan, leftover=True))(request(plan, expectation(plan)))


def test_config_refuses_unpinned_images_secrets_and_bad_values(tmp_path):
    base = dict(docker_binary='/usr/bin/docker', docker_endpoint='unix:///run/docker.sock',
                docker_config_dir='/state/docker-cli', backup_root='/state/backups', clone_workdir='/state/work',
                python='/opt/venv/bin/python',
                dump_image=IMAGE, clone_image=CLONE_IMAGE)
    assert wb.WindowBackupConfig.from_dict(dict(base, clone_command=['postgres', '-c', 'fsync=on'])).clone_command
    for bad, code in ((dict(dump_image='postgres:17'), 'window-backup-image-unpinned'),
                      (dict(password='x'), 'window-backup-config-keys'),
                      (dict(clone_command=['sh', '-c', 'rm -rf /']), 'window-backup-command'),
                      (dict(dump_network='pastorai_default'), 'window-backup-network'),
                      (dict(backup_root='relative'), 'window-backup-paths'),
                      (dict(clone_superusers=['bad name']), 'window-backup-roles'),
                      (dict(timeouts={'dump_s': 0}), 'window-backup-timeouts')):
        with pytest.raises(Refused, match='^' + code + '$'):
            wb.WindowBackupConfig.from_dict(dict(base, **bad))


def test_env_file_secret_requires_root_only_file_and_single_value(tmp_path):
    path = tmp_path / '.env'
    path.write_text('A=1\nDATABASE_URL="' + SOURCE_URL + '"\n')
    path.chmod(0o600)
    assert window.env_file_secret(str(path))() == SOURCE_URL
    path.chmod(0o644)
    with pytest.raises(Refused, match='^window-env-file-mode$'):
        window.env_file_secret(str(path))()
    path.chmod(0o600)
    path.write_text('DATABASE_URL=' + SOURCE_URL + '\nDATABASE_URL=' + SOURCE_URL + '\n')
    with pytest.raises(Refused, match='^window-env-secret$'):
        window.env_file_secret(str(path))()


def test_entry_point_run_is_refused_and_errors_leak_no_text(tmp_path, monkeypatch):
    lines = []
    assert window.main(['run', '--config', '/x', '--env-file', '/y'], out=lines.append) == 2
    assert json.loads(lines[-1]) == {'refused': 'window-bindings-pending'}

    def boom(*args, **kwargs):
        raise RuntimeError('connection to ' + SOURCE_URL + ' failed')
    monkeypatch.setattr(window, 'load_config', boom)
    assert window.main(['check', '--config', '/x', '--env-file', '/y'], out=lines.append) == 2
    assert json.loads(lines[-1]) == {'refused': 'window-failed'} and SOURCE_URL not in ''.join(lines)
