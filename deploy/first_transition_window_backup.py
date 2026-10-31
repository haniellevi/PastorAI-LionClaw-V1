"""Window backup provider of the first transition (A8): fresh dump, restore and clone replay.

``WindowBackup`` is the ``backup_proof`` injected into
first_transition_orchestrator.assemble. Called once per window, after quiescence:

1. dumps the SOURCE with a digest-pinned ``pg_dump`` image in a throwaway container
   (custom format, ``--lock-wait-timeout``), streamed into a NEW 0600 file of an exclusive
   0700 run directory; the source URL travels only in the child environment (``-e NAME``),
   never in argv, output, exceptions or the receipt;
2. starts a disposable clone cluster from a digest-pinned image in a NEW ``--internal``
   Docker network (no egress), mirrors the source role NAMES only (NOLOGIN, no password),
   restores with ``pg_restore --exit-on-error --single-transaction`` and requires the
   restored ledger and catalog fingerprint (first_transition_database.Q_CATALOG) to equal
   the expected baseline before any replay (``restore_verified``);
3. replays the pending migrations on the clone through the orchestrator's
   MigrationExecutor (exact pinned migrate.py bytes, one per invocation), then records the
   final ledger, invalid indexes and catalog fingerprint;
4. removes ONLY its own clone container and network (named and labelled by the run id),
   also on failure; the dump stays as the window backup and ``backup_id`` is its SHA-256.

The receipt satisfies first_transition_adapter.validate_clone_receipt and binds the
``request_digest`` of the journaled request. The clone holds real data only while it runs
inside the protected host; nothing is copied elsewhere. Errors are fixed codes; command
output is discarded or bounded and never enters exceptions or receipts. Nothing runs at
import or construction.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import time

import first_transition_database as fdb
from first_transition_adapter import Plan, digest
from first_transition_host_driver import _absolute
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA, MigrationExecutor, ProcessRunner
from initial_transition_ops import Refused, require

RECEIPT_SCHEMA = 'igreja12.first-transition-window-backup/1'
# A rehearsal request is never journaled, so its receipt can never attest a window request.
REHEARSAL_SCHEMA = 'igreja12.first-transition-window-backup-rehearsal/1'
REQUEST_SCHEMAS = (BACKUP_REQUEST_SCHEMA, REHEARSAL_SCHEMA)
PINNED_IMAGE = re.compile(r'[a-z0-9][a-z0-9./_-]{0,200}@sha256:[0-9a-f]{64}')
ROLE = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,62}')
ARG = re.compile(r'[A-Za-z0-9_./=:,+-]{1,256}')
SOURCE_ENV = 'PGDUMP_URL'
CLONE_ENV = 'POSTGRES_PASSWORD'
RESTORE_ENV = 'PGPASSWORD'
CLONE_DB = 'window_clone'
Q_SOURCE_ROLES = "SELECT rolname FROM pg_roles WHERE rolname !~ '^pg_' ORDER BY rolname COLLATE \"C\""
TIMEOUTS = {'dump_s': 1800, 'ready_s': 180, 'restore_s': 1800, 'migration_s': 300, 'docker_s': 120}


@dataclass(frozen=True)
class WindowBackupConfig:
    """Public values only (no URL or password): where and with which pinned images to work."""
    docker_binary: str
    docker_endpoint: str
    docker_config_dir: str
    backup_root: str
    clone_workdir: str
    python: str
    dump_image: str
    clone_image: str
    clone_command: tuple = ()
    dump_network: str = 'bridge'
    admin_user: str = 'postgres'
    restore_user: str = 'postgres'
    migration_user: str = 'postgres'
    clone_superusers: tuple = ()
    timeouts: tuple = tuple(sorted(TIMEOUTS.items()))

    def validated(self):
        require(all(_absolute(p) for p in (self.docker_binary, self.docker_config_dir, self.backup_root,
                                           self.clone_workdir, self.python))
                and isinstance(self.docker_endpoint, str) and self.docker_endpoint.startswith('unix:///')
                and _absolute(self.docker_endpoint.removeprefix('unix://')), 'window-backup-paths')
        require(all(isinstance(i, str) and PINNED_IMAGE.fullmatch(i) for i in (self.dump_image, self.clone_image)),
                'window-backup-image-unpinned')
        require(type(self.clone_command) is tuple and len(self.clone_command) <= 16
                and all(isinstance(a, str) and ARG.fullmatch(a) for a in self.clone_command), 'window-backup-command')
        require(self.dump_network in ('bridge', 'host'), 'window-backup-network')
        require(all(isinstance(r, str) and ROLE.fullmatch(r) for r in (self.admin_user, self.restore_user,
                                                                         self.migration_user, *self.clone_superusers))
                and type(self.clone_superusers) is tuple, 'window-backup-roles')
        values = dict(self.timeouts)
        require(type(self.timeouts) is tuple and set(values) == set(TIMEOUTS)
                and all(type(v) is int and 0 < v <= 3600 for v in values.values()), 'window-backup-timeouts')
        return self

    def timeout(self, key):
        return dict(self.timeouts)[key]

    @classmethod
    def from_dict(cls, data):
        """Unknown keys (a password, a URL) refuse."""
        fields = set(cls.__dataclass_fields__)
        require(isinstance(data, dict) and set(data) <= fields and {
            'docker_binary', 'docker_endpoint', 'docker_config_dir', 'backup_root', 'clone_workdir', 'python',
            'dump_image',
            'clone_image'} <= set(data), 'window-backup-config-keys')
        values = dict(data)
        for key in ('clone_command', 'clone_superusers'):
            if key in values:
                require(isinstance(values[key], list), 'window-backup-config-keys')
                values[key] = tuple(values[key])
        if 'timeouts' in values:
            require(isinstance(values['timeouts'], dict) and set(values['timeouts']) <= set(TIMEOUTS),
                    'window-backup-timeouts')
            values['timeouts'] = tuple(sorted({**TIMEOUTS, **values['timeouts']}.items()))
        return cls(**values).validated()


def source_role_names(connect, *, timeout=10):
    """Role NAMES of the source (no attributes, memberships or passwords), via a read-only connection."""
    conn = connect(timeout=timeout)
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(fdb.Q_BEGIN)
        try:
            cur.execute(fdb.Q_TIMEOUT, (f'{int(timeout * 1000)}ms',))
            cur.fetchall()
            cur.execute(Q_SOURCE_ROLES)
            names = tuple(row[0] for row in cur.fetchall())
        finally:
            cur.execute('ROLLBACK')
    finally:
        conn.close()
    require(names and all(isinstance(n, str) and ROLE.fullmatch(n) for n in names), 'window-backup-source-roles')
    return names


def clone_state(conn):
    """Clone identity, ledger, invalid indexes and catalog fingerprint in one read-only snapshot."""
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(fdb.Q_BEGIN)
    try:
        cur.execute(fdb.Q_PATH)
        cur.fetchall()
        cur.execute(fdb.Q_IDENTITY)
        rows = cur.fetchall()
        require(len(rows) == 1 and len(rows[0]) >= 3, 'window-backup-clone-shape')
        system, oid, name = rows[0][:3]
        cur.execute(fdb.Q_LEDGER)
        ledger = tuple(row[0] for row in cur.fetchall())
        cur.execute(fdb.Q_INVALID)
        invalid = len(cur.fetchall())
        catalog = fdb._catalog(cur)
    finally:
        cur.execute('ROLLBACK')
    require(all(isinstance(n, str) and fdb.LEDGER_NAME.fullmatch(n) for n in ledger), 'window-backup-clone-shape')
    return dict(identity=(str(system), int(oid), str(name)), ledger=ledger, invalid=invalid, catalog=catalog)


def _psycopg2_clone(*, host, dbname, user, password, timeout):
    import psycopg2
    return psycopg2.connect(host=host, port=5432, dbname=dbname, user=user, password=password,
                            connect_timeout=max(1, int(timeout)), sslmode='disable', options='',
                            application_name='igreja12-window-clone')


class WindowBackup:
    """``backup_proof(request) -> receipt`` for exactly one window; see the module docstring.

    ``secret()`` returns the SOURCE URL; ``connect`` is the read-only source connection factory
    (first_transition_database.psycopg2_connector). ``run``/``clone_connect``/``migrate_run``/
    ``sleep``/``clock`` are injection seams for synthetic tests.
    """

    def __init__(self, config, plan, expected, *, secret, connect, run=None, clone_connect=None,
                 migrate_run=None, sleep=None, clock=None):
        require(isinstance(config, WindowBackupConfig), 'window-backup-config')
        require(isinstance(plan, Plan) and isinstance(expected, fdb.DatabaseExpectation), 'window-backup-plan')
        require(callable(secret) and callable(connect), 'window-backup-secret')
        self.config, self.plan, self.expected = config.validated(), plan, expected.validated()
        require(self.expected.ledger == plan.baseline, 'window-backup-plan')
        self.secret, self.connect = secret, connect
        self.run, self.clone_connect, self.migrate_run = run, clone_connect or _psycopg2_clone, migrate_run
        self.sleep, self.clock = sleep or time.sleep, clock or time.monotonic
        self.used = False

    # -- process plumbing -----------------------------------------------------------------------
    def _docker(self, args, *, timeout, env=None, stdin=None, stdout=None, capture=False):
        """Docker CLI with explicit config/endpoint, constructed env, no shell; output discarded or bounded."""
        require(type(args) is tuple and args and all(type(a) is str and 0 < len(a) <= 4096 and '\x00' not in a
                                                     for a in args), 'window-backup-argv')
        child_env = dict(PATH='/usr/bin:/bin', LC_ALL='C', **(env or {}))
        argv = [self.config.docker_binary, '--config', self.config.docker_config_dir,
                '--host', self.config.docker_endpoint, *args]
        run = self.run or subprocess.run
        outcome = None
        try:
            done = run(argv, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                       stdout=stdout if stdout is not None else (subprocess.PIPE if capture else subprocess.DEVNULL),
                       stderr=subprocess.DEVNULL, env=child_env, timeout=timeout, close_fds=True, shell=False,
                       check=False)
        except subprocess.TimeoutExpired:
            outcome = 'window-backup-timeout'
        except Exception:
            outcome = 'window-backup-spawn-failed'
        require(outcome is None, outcome)
        if capture:
            out = getattr(done, 'stdout', b'') or b''
            require(isinstance(out, bytes) and len(out) <= 4096, 'window-backup-output')
            return done.returncode, out.decode('utf-8', 'replace').strip()
        return done.returncode, None

    def _ok(self, args, code, **kwargs):
        rc, out = self._docker(args, timeout=kwargs.pop('timeout', self.config.timeout('docker_s')), **kwargs)
        require(rc == 0, code)
        return out

    # -- steps ----------------------------------------------------------------------------------
    def _run_dir(self, request_digest):
        root = Path(self.config.backup_root)
        require(os.path.lexists(root) and stat.S_ISDIR(os.lstat(root).st_mode) and not root.is_symlink(),
                'window-backup-root-missing')
        run_dir = root / request_digest
        try:
            run_dir.mkdir(mode=0o700)  # exclusive: a window is never re-run into the same directory
        except FileExistsError:
            raise Refused('window-backup-run-exists') from None
        return run_dir

    def _dump(self, run_dir):
        url = self.secret()
        require(isinstance(url, str) and url.startswith('postgresql://') and '\n' not in url, 'window-backup-secret')
        path = run_dir / 'window.dump'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            rc, _ = self._docker(('run', '--rm', '--network', self.config.dump_network, '-e', SOURCE_ENV,
                                  '-e', 'PGAPPNAME=igreja12-window-backup', self.config.dump_image,
                                  'sh', '-c', 'exec pg_dump "$' + SOURCE_ENV + '" --format=custom '
                                  '--lock-wait-timeout=10s --no-password'),
                                 timeout=self.config.timeout('dump_s'), env={SOURCE_ENV: url}, stdout=handle)
            handle.flush()
            os.fsync(handle.fileno())
        require(rc == 0, 'window-backup-dump-failed')
        data_hash, size = hashlib.sha256(), 0
        with open(path, 'rb') as handle:
            head = handle.read(5)
            require(head == b'PGDMP', 'window-backup-dump-format')
            data_hash.update(head)
            size += len(head)
            for chunk in iter(lambda: handle.read(1 << 20), b''):
                data_hash.update(chunk)
                size += len(chunk)
        return path, data_hash.hexdigest(), size

    def _start_clone(self, name, password):
        self._ok(('network', 'create', '--internal', '--label', 'igreja12.window-backup=' + name, name),
                 'window-backup-network-failed')
        self._ok(('run', '-d', '--name', name, '--network', name, '--label', 'igreja12.window-backup=' + name,
                  '-e', CLONE_ENV, self.config.clone_image, *self.config.clone_command),
                 'window-backup-clone-failed', env={CLONE_ENV: password})
        address = self._ok(('inspect', '--format', '{{(index .NetworkSettings.Networks "' + name + '").IPAddress}}',
                            name), 'window-backup-clone-inspect', capture=True)
        require(re.fullmatch(r'(?:\d{1,3}\.){3}\d{1,3}', address or ''), 'window-backup-clone-inspect')
        deadline = self.clock() + self.config.timeout('ready_s')
        while True:
            try:
                conn = self.clone_connect(host=address, dbname='postgres', user=self.config.admin_user,
                                          password=password, timeout=5)
                return address, conn
            except Exception:
                require(self.clock() < deadline, 'window-backup-clone-not-ready')
                self.sleep(2)

    def _prepare_clone(self, admin, roles, password):
        from psycopg2 import sql
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute('SELECT rolname FROM pg_roles')
            existing = {row[0] for row in cur.fetchall()}
            created = 0
            for role in roles:
                if role not in existing:
                    cur.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
                    created += 1
            for role in self.config.clone_superusers:
                cur.execute(sql.SQL('ALTER ROLE {} SUPERUSER').format(sql.Identifier(role)))
            cur.execute(sql.SQL('ALTER ROLE {} LOGIN PASSWORD %s').format(
                sql.Identifier(self.config.migration_user)), (password,))
            cur.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(CLONE_DB)))
        return created

    def _restore(self, name, path, password):
        with open(path, 'rb') as handle:
            self._ok(('exec', '-i', '-e', RESTORE_ENV, name, 'pg_restore', '-h', '127.0.0.1',
                      '-U', self.config.restore_user, '-d', CLONE_DB, '--exit-on-error', '--single-transaction',
                      '--no-password'), 'window-backup-restore-failed', timeout=self.config.timeout('restore_s'),
                     env={RESTORE_ENV: password}, stdin=handle)

    def _state(self, address, password):
        conn = self.clone_connect(host=address, dbname=CLONE_DB, user=self.config.admin_user,
                                  password=password, timeout=10)
        try:
            return clone_state(conn)
        finally:
            conn.close()

    def _replay(self, request_digest, address, password):
        # Outside the backup root: protected path names (backups, *.dump) are refused by the executor.
        root = Path(self.config.clone_workdir)
        require(os.path.lexists(root) and stat.S_ISDIR(os.lstat(root).st_mode) and not root.is_symlink(),
                'window-backup-workdir-missing')
        workdir = root / request_digest
        try:
            workdir.mkdir(mode=0o700)
        except FileExistsError:
            raise Refused('window-backup-run-exists') from None
        url = (f'postgresql://{self.config.migration_user}:{password}@{address}:5432/{CLONE_DB}'
               '?sslmode=disable')
        executor = MigrationExecutor(self.plan, python=self.config.python, workdir=str(workdir),
                                     secret=lambda: url, timeout=self.config.timeout('migration_s'),
                                     runner=ProcessRunner(binaries=(self.config.python,), run=self.migrate_run))
        for index, migration in enumerate(self.plan.pending, 1):
            require(executor.apply(index, migration) == 0, 'window-backup-clone-migration-failed')
        return len(self.plan.pending)

    def _cleanup(self, name):
        # Own resources only, by exact name; a missing container/network is not an error.
        failed = False
        for args in (('rm', '-f', '-v', name), ('network', 'rm', name)):
            try:
                self._docker(args, timeout=self.config.timeout('docker_s'))
            except Refused:
                failed = True
        rc, out = self._docker(('ps', '-a', '--filter', 'label=igreja12.window-backup=' + name, '--format', '{{.ID}}'),
                               timeout=self.config.timeout('docker_s'), capture=True)
        require(not failed and rc == 0 and out == '', 'window-backup-cleanup-failed')

    def __call__(self, request):
        require(not self.used, 'window-backup-already-used')
        self.used = True
        require(isinstance(request, dict) and request.get('schema') in REQUEST_SCHEMAS
                and request.get('plan_digest') == self.plan.digest
                and request.get('source_identity') == self.expected.identity
                and request.get('baseline_digest') == self.expected.baseline_digest
                and isinstance(request.get('nonce'), str) and re.fullmatch('[0-9a-f]{64}', request['nonce']),
                'window-backup-request')
        request_digest = digest(request)
        started = self.clock()
        run_dir = self._run_dir(request_digest)
        roles = source_role_names(self.connect)
        path, backup_id, size = self._dump(run_dir)
        name = 'igreja12-window-clone-' + request_digest[:16]
        password = secrets.token_hex(24)
        admin = None
        try:
            address, admin = self._start_clone(name, password)
            created = self._prepare_clone(admin, roles, password)
            admin.close()
            admin = None
            self._restore(name, path, password)
            restored = self._state(address, password)
            require(restored['ledger'] == self.plan.baseline, 'window-backup-restore-ledger')
            require(restored['invalid'] == 0, 'window-backup-restore-invalid-index')
            require(restored['catalog'] == self.expected.catalog, 'window-backup-restore-catalog')
            applied = self._replay(request_digest, address, password)
            final = self._state(address, password)
        finally:
            if admin is not None:
                admin.close()
            self._cleanup(name)
        require(final['ledger'] == tuple(sorted(m.name for m in self.plan.migrations)), 'window-backup-final-ledger')
        require(final['invalid'] == 0, 'window-backup-final-invalid-index')
        clone_identity = digest(['window-clone', *final['identity'], request_digest])
        require(clone_identity != self.expected.identity, 'window-backup-clone-is-source')
        return dict(schema=RECEIPT_SCHEMA, plan_digest=self.plan.digest, source_identity=self.expected.identity,
                    baseline_digest=self.expected.baseline_digest, restore_verified=True,
                    request_digest=request_digest, backup_id=backup_id, backup_bytes=size, backup_path=str(path),
                    clone_rehearsal=dict(
                        migrations_verified=True, clone_identity=clone_identity, cluster_global_ddl_possible=True,
                        applied=applied, final_ledger=len(final['ledger']),
                        concurrent=sum(m.concurrent for m in self.plan.pending),
                        sql_digest=digest([(m.name, m.sha256) for m in self.plan.pending]),
                        final_schema_digest=final['catalog'], restored_catalog=restored['catalog'],
                        roles_created=created, clone_image=self.config.clone_image,
                        dump_image=self.config.dump_image),
                    seconds=round(self.clock() - started, 1))
