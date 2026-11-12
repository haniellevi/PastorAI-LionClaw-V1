"""Window backup provider and window entry point: synthetic Docker/PostgreSQL only, no socket."""
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import subprocess
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
LISTING = '\n'.join([
    ';', '; Archive created at 2026-11-12 00:00:00 UTC', ';     dbname: synthetic', ';',
    '4001; 2615 2200 SCHEMA - public pg_database_owner',
    '4002; 3079 16385 EXTENSION - supabase_vault postgres',
    '4003; 0 0 COMMENT - EXTENSION supabase_vault postgres',
    '4004; 0 0 ACL - SCHEMA vault supabase_admin',
    '4005; 0 0 ACL vault FUNCTION create_secret(text) supabase_admin',
    '4006; 1259 16390 TABLE public igrejas postgres',
    '4007; 0 16390 TABLE DATA public igrejas postgres',
    '4008; 1255 16400 FUNCTION extensions grant_pg_net_access() supabase_admin',
    '4009; 3466 16410 EVENT TRIGGER - issue_pg_net_access supabase_admin',
    '4010; 0 0 COMMENT - EVENT TRIGGER issue_pg_net_access supabase_admin',
    '4011; 3466 16411 EVENT TRIGGER - ensure_rls postgres',
    '4012; 6104 16420 PUBLICATION - supabase_realtime postgres',
    '4013; 6106 16421 PUBLICATION TABLE public igrejas postgres',
]) + '\n'
DUMP_BODY = b'synthetic custom archive'
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
        self.listing, self.copied, self.restore_args = LISTING, {}, None
        self.restore_stderr = b'pg_restore: from TOC entry 4002; 3079 16385 EXTENSION - supabase_vault postgres\n'
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
        stderr_out, tail = b'', ()
        if verb == 'exec':
            tail = tuple(args[[a.startswith('igreja12-window-clone-') for a in args].index(True) + 1:])
            if tail == ('pg_restore', '-l'):
                assert stdin.read().startswith(b'PGDMP')
                stdout.write(self.listing.encode())
            elif tail[:2] == ('sh', '-c'):
                self.copied[tail[-1]] = stdin.read()
            else:
                assert stdin is subprocess.DEVNULL and '-L' in tail and self.copied.get(tail[-1]) == DUMP
                self.restore_args = tail
                self.restored = 'restore' not in self.fail
                if 'restore' in self.fail:
                    stderr.write(self.restore_stderr)
        out = b''
        if verb == 'dump' and 'dump' not in self.fail:
            stdout.write(DUMP)
        if verb == 'inspect':
            out = b'172.30.0.2\n'
        if verb == 'ps' and self.leftover:
            out = b'abc123\n'
        failed = {'dump': 'dump', 'clone': 'clone'}.get(verb) in self.fail
        if verb == 'exec':
            failed = ('list' if tail == ('pg_restore', '-l') else 'restore' if tail[:1] == ('pg_restore',)
                      else '') in self.fail
        return types.SimpleNamespace(returncode=1 if failed else 0, stdout=out, stderr=stderr_out)

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


def sub(tmp_path, name):
    path = tmp_path / name
    path.mkdir()
    return path


def expectation(plan, rows=RESTORED_ROWS):
    return fdb.DatabaseExpectation('c' * 64, plan.baseline, digest([list(r) for r in rows]))


def request(plan, expected, **overrides):
    value = dict(schema=BACKUP_REQUEST_SCHEMA, nonce='d' * 64, plan_digest=plan.digest,
                 source_identity=expected.identity, baseline_digest=expected.baseline_digest,
                 config_digest='e' * 64, quiescence_digest='f' * 64)
    value.update(overrides)
    return value


PINNED = (('event_trigger_names', ('issue_pg_net_access',)), ('event_triggers', 2), ('vault_extension', 2),
          ('vault_schema', 2))


def provider(plan, tmp_path, host, expected=None, **overrides):
    overrides.setdefault('restore_excluded_expected', PINNED)
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


@pytest.mark.parametrize('verb,image', [('--rm', IMAGE), ('-d', CLONE_IMAGE)])
def test_dump_and_clone_never_pull_images(plan, tmp_path, verb, image):
    host = Host(plan)
    provider(plan, tmp_path, host)(request(plan, expectation(plan)))
    args = next(args for args, _ in host.calls if args[:2] == ('run', verb))
    assert args.count('--pull=never') == 1
    assert args.index('--pull=never') < args.index(image)
    assert not any(a in ('pull', '--pull=always', '--pull=missing') for a in args)


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
    (dict(fail={'restore'}), 'window-backup-restore-failed-extension'),
    (dict(fail={'list'}), 'window-backup-restore-list-failed'),
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


def test_env_file_secret_requires_root_only_file_and_single_value(tmp_path, monkeypatch):
    # This test's files are fictional and user-owned; simulate only root ownership metadata.
    real_fstat = os.fstat

    def root_stat(fd):
        values = list(real_fstat(fd))
        values[4] = 0
        return os.stat_result(values)
    monkeypatch.setattr(window.os, 'fstat', root_stat)
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
    assert json.loads(lines[-1]) == {'refused': 'window-run-prerequisites'}

    def boom(*args, **kwargs):
        raise RuntimeError('connection to ' + SOURCE_URL + ' failed')
    monkeypatch.setattr(window, 'load_config', boom)
    assert window.main(['check', '--config', '/x', '--env-file', '/y'], out=lines.append) == 2
    assert json.loads(lines[-1]) == {'refused': 'window-failed'} and SOURCE_URL not in ''.join(lines)


def test_check_bindings_only_observes_and_reports_refusals_by_code(tmp_path, monkeypatch):
    lines = []
    assert window.main(['check-bindings', '--config', '/x', '--env-file', '/y'], out=lines.append) == 2
    assert json.loads(lines[-1]) == {'refused': 'window-bindings-config-missing'}

    class Binding:
        scope = 'a' * 64

        def __init__(self, answer):
            self.answer, self.calls = answer, []

        def observe(self, scope, *, timeout):
            self.calls.append(scope)
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

        def block(self, *args, **kwargs):
            raise AssertionError('check-bindings must never block')
        open = block

    bindings = {'external': Binding(Refused('window-nginx-include-missing')),
                'evolution-backend': Binding('open')}
    writers = Binding(0)
    config = type('Config', (), {'timeouts': ()})()
    database = type('Database', (), {'connect': None})()
    monkeypatch.setattr(window, '_load', lambda args: (config, None, None, lambda: SOURCE_URL, database))
    monkeypatch.setattr(window, 'read_regular', lambda path, limit: b'{}')
    monkeypatch.setattr(window, '_bindings', lambda data, config, secret, database, io: (bindings, writers))
    assert window.main(['check-bindings', '--config', '/x', '--env-file', '/y', '--bindings-config', '/z'],
                       out=lines.append) == 1
    assert json.loads(lines[-1]) == {'evolution-backend': 'open', 'external': 'refused:window-nginx-include-missing',
                                     'unknown_writers': 0}
    assert writers.calls == ['a' * 64]


def test_new_clone_roles_are_minimal_noinherit_without_altering_existing_roles(plan, tmp_path):
    host = Host(plan)
    backup = provider(plan, tmp_path, host)
    assert backup._prepare_clone(Conn(host, host.sql), ('postgres', 'private_storage_runtime'), 'fictional') == 1
    creates = [q for q in host.sql if 'CREATE ROLE' in str(q)]
    assert len(creates) == 1 and 'NOLOGIN NOINHERIT' in str(creates[0])
    assert 'private_storage_runtime' in str(creates[0]) and 'postgres' not in str(creates[0])
    assert not any('ALTER ROLE' in str(q) and 'private_storage_runtime' in str(q) for q in host.sql)
    assert any('SUPERUSER' in str(q) and 'postgres' in str(q) for q in host.sql)


def test_restore_uses_a_filtered_list_without_vault_and_foreign_owned_event_triggers(plan, tmp_path):
    host, expected = Host(plan), expectation(plan)
    receipt = provider(plan, tmp_path, host, expected)(request(plan, expected))
    kept = host.copied[wb.CLONE_LIST].decode().splitlines()
    text = '\n'.join(kept)
    assert 'supabase_vault' not in text and 'SCHEMA vault' not in text and 'ACL vault' not in text
    assert 'issue_pg_net_access' not in text  # owned by a role that is not a clone superuser
    # Everything else stays: public objects, data, policies/functions, own event trigger, publication.
    for entry in ('TABLE public igrejas', 'TABLE DATA public igrejas', 'FUNCTION extensions grant_pg_net_access()',
                  'EVENT TRIGGER - ensure_rls postgres', 'PUBLICATION - supabase_realtime',
                  'PUBLICATION TABLE public igrejas', 'SCHEMA - public'):
        assert entry in text
    assert host.restore_args[-3:] == ('-L', wb.CLONE_LIST, wb.CLONE_DUMP)
    assert '--exit-on-error' in host.restore_args and '--single-transaction' in host.restore_args
    assert receipt['clone_rehearsal']['restore_excluded'] == dict(vault_extension=2, vault_schema=2, event_triggers=2,
                                                                       event_trigger_names=['issue_pg_net_access'])
    assert host.copied[wb.CLONE_DUMP] == DUMP


def test_event_triggers_owned_by_a_clone_superuser_are_kept(plan, tmp_path):
    host, expected = Host(plan), expectation(plan)
    provider(plan, tmp_path, host, expected, clone_superusers=('postgres', 'supabase_admin'),
             restore_excluded_expected=(('event_trigger_names', ()), ('event_triggers', 0), ('vault_extension', 2),
                                        ('vault_schema', 2)))(request(plan, expected))
    text = host.copied[wb.CLONE_LIST].decode()
    assert 'EVENT TRIGGER - issue_pg_net_access supabase_admin' in text and 'supabase_vault' not in text


def test_filter_never_removes_other_entries_and_refuses_an_empty_result():
    lines, removed = wb.filter_restore_list(LISTING, frozenset({'postgres'}))
    assert len(lines) == len(LISTING.splitlines()) - 6 and sum(v for v in removed.values() if isinstance(v, int)) == 6
    with pytest.raises(Refused, match='^window-backup-restore-list$'):
        wb.filter_restore_list('; only comments\n', frozenset())


@pytest.mark.parametrize('stderr,code', [
    (b'pg_restore: from TOC entry 9; 1 2 TABLE DATA public secret_name owner\nDETAIL: Failing row (SENTINEL)',
     'window-backup-restore-failed-table-data'),
    (b'pg_restore: from TOC entry 9; 1 2 EVENT TRIGGER - x supabase_admin', 'window-backup-restore-failed-event-trigger'),
    (b'pg_restore: from TOC entry 9; 1 2 ALIEN thing x', 'window-backup-restore-failed'),
    (b'ERROR: SENTINEL only', 'window-backup-restore-failed'), (b'', 'window-backup-restore-failed'),
])
def test_restore_failure_reduces_stderr_to_a_fixed_kind_code(plan, tmp_path, stderr, code):
    host = Host(plan, fail={'restore'})
    host.restore_stderr = stderr
    with pytest.raises(Refused) as caught:
        provider(plan, tmp_path, host)(request(plan, expectation(plan)))
    assert str(caught.value) == code and 'SENTINEL' not in str(caught.value) and code in wb.BACKUP_CODES


def test_every_backup_code_literal_is_published_and_escapes_the_entry_point():
    source = (ROOT / 'deploy' / 'first_transition_window_backup.py').read_text()
    literals = set(re.findall(r"'(window-backup-[a-z-]+)'", source)) - {'window-backup-restore-failed-'}
    assert literals <= wb.BACKUP_CODES and wb.BACKUP_CODES <= window.CODES
    for code in ('window-backup-restore-failed-extension', 'window-backup-dump-failed', 'window-backup-clone-failed'):
        assert window._code(Refused(code)) == code
    assert window._code(Refused('window-backup-injected-SENTINEL')) == 'window-refused'
    assert window._code(ValueError('window-backup-dump-failed')) == 'window-refused'


def test_unparseable_listing_line_refuses_instead_of_staying(plan):
    forged = LISTING + 'fragment of a name\n4002; 0 0 EXTENSION - supabase_vault x\n'
    with pytest.raises(Refused, match='^window-backup-restore-list$'):
        wb.filter_restore_list(forged.replace('4013;', 'broken\n4013;', 1), frozenset({'postgres'}))


def test_restore_stderr_is_bounded_when_read(plan, tmp_path):
    host = Host(plan, fail={'restore'})
    host.restore_stderr = b'pg_restore: from TOC entry 9; 1 2 EXTENSION - x y\n' + b'x' * (wb.STDERR_BOUND * 3)
    with pytest.raises(Refused, match='^window-backup-restore-failed-extension$'):
        provider(plan, tmp_path, host)(request(plan, expectation(plan)))


def test_vault_namespace_entries_are_removed_but_lookalikes_stay():
    listing = LISTING + '\n'.join([
        '4020; 0 16500 TABLE DATA vault secrets supabase_admin',
        '4021; 0 0 SEQUENCE SET vault secrets_id_seq supabase_admin',
        '4022; 1259 16501 TABLE public vault_notes postgres',
        '4023; 0 16501 TABLE DATA public vault_notes postgres',
        '4024; 1259 16502 TABLE public vault postgres',
        '4025; 1255 16503 FUNCTION public vault vault_helper() postgres',
    ]) + '\n'
    lines, removed = wb.filter_restore_list(listing, frozenset({'postgres'}))
    text = '\n'.join(lines)
    assert removed['vault_schema'] == 4 and 'DATA vault secrets' not in text and 'secrets_id_seq' not in text
    for stays in ('TABLE public vault_notes', 'TABLE DATA public vault_notes', 'TABLE public vault postgres'):
        assert stays in text


def test_excluded_pin_equal_passes_different_refuses_before_any_restore(plan, tmp_path):
    host, expected = Host(plan), expectation(plan)
    provider(plan, tmp_path, host, expected)(request(plan, expected))  # PINNED equals the synthetic dump
    for bad in ((('event_trigger_names', ('outro',)), ('event_triggers', 2), ('vault_extension', 2), ('vault_schema', 2)),
                (('event_trigger_names', ('issue_pg_net_access',)), ('event_triggers', 2), ('vault_extension', 2),
                 ('vault_schema', 1))):
        host = Host(plan)
        with pytest.raises(Refused, match='^window-backup-restore-excluded$'):
            provider(plan, sub(tmp_path, 'x%d' % len(bad[0][1][0])), host, expected, restore_excluded_expected=bad)(
                request(plan, expected))
        assert not host.restored and host.copied == {} and host.migrations == []
        assert 'window-backup-restore-excluded' in wb.BACKUP_CODES


def test_excluded_pin_is_required_for_the_window_and_optional_for_the_rehearsal(plan, tmp_path):
    expected = expectation(plan)
    host = Host(plan)
    with pytest.raises(Refused, match='^window-backup-restore-excluded$'):
        provider(plan, sub(tmp_path, 'a'), host, expected, restore_excluded_expected=())(request(plan, expected))
    assert host.calls == []  # nothing ran, not even the dump
    host = Host(plan)
    rehearsal = request(plan, expected, schema=wb.REHEARSAL_SCHEMA)
    receipt = provider(plan, sub(tmp_path, 'b'), host, expected, restore_excluded_expected=())(rehearsal)
    assert receipt['clone_rehearsal']['restore_excluded']['event_trigger_names'] == ['issue_pg_net_access']
    assert isinstance(receipt['restore_seconds'], float)
    # a pinned value is honoured in the rehearsal too
    host = Host(plan)
    with pytest.raises(Refused, match='^window-backup-restore-excluded$'):
        provider(plan, sub(tmp_path, 'c'), host, expected, restore_excluded_expected=(
            ('event_trigger_names', ()), ('event_triggers', 0), ('vault_extension', 0), ('vault_schema', 0)))(
            request(plan, expected, schema=wb.REHEARSAL_SCHEMA))


def test_excluded_pin_from_dict_validates_shape():
    base = dict(docker_binary='/usr/bin/docker', docker_endpoint='unix:///run/docker.sock',
                docker_config_dir='/state/docker-cli', backup_root='/b', clone_workdir='/c', python='/p/python',
                dump_image=IMAGE, clone_image=CLONE_IMAGE)
    good = dict(vault_extension=2, vault_schema=2, event_triggers=2, event_trigger_names=['a'])
    assert dict(wb.WindowBackupConfig.from_dict({**base, 'restore_excluded_expected': good}
                                                ).restore_excluded_expected)['event_trigger_names'] == ('a',)
    for bad in ({**good, 'extra': 1}, {**good, 'event_triggers': -1}, {**good, 'event_trigger_names': ['a b']},
                {**good, 'vault_schema': True}, 'x', {**good, 'event_trigger_names': 'a'}):
        with pytest.raises(Refused, match='^window-backup-restore-excluded$'):
            wb.WindowBackupConfig.from_dict({**base, 'restore_excluded_expected': bad})


def test_pin_must_be_sorted_unique_and_well_formed_even_when_built_directly():
    base = dict(docker_binary='/usr/bin/docker', docker_endpoint='unix:///run/docker.sock',
                docker_config_dir='/state/docker-cli', backup_root='/b', clone_workdir='/c', python='/p/python',
                dump_image=IMAGE, clone_image=CLONE_IMAGE)
    good = dict(vault_extension=0, vault_schema=0, event_triggers=2, event_trigger_names=['a', 'b'])
    wb.WindowBackupConfig.from_dict({**base, 'restore_excluded_expected': good})
    for names in (['b', 'a'], ['a', 'a']):
        with pytest.raises(Refused, match='^window-backup-restore-excluded$'):
            wb.WindowBackupConfig.from_dict({**base, 'restore_excluded_expected': {**good, 'event_trigger_names': names}})
    for direct in ('x', (1,), (('a',),), ((1, 2),)):
        with pytest.raises(Refused, match='^window-backup-restore-excluded$'):
            wb.WindowBackupConfig(**base, restore_excluded_expected=direct).validated()


def test_vault_filter_ignores_a_schema_that_merely_looks_like_a_desc_word():
    lines, removed = wb.filter_restore_list(LISTING + '4030; 0 16600 TABLE DATA SALES vault x postgres\n',
                                            frozenset({'postgres'}))
    assert 'TABLE DATA SALES vault x' in '\n'.join(lines) and removed['vault_schema'] == 2
