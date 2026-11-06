"""Window backup provider of the first transition (A8): fresh dump, restore and clone replay.

``WindowBackup`` is the ``backup_proof`` injected into
first_transition_orchestrator.assemble. Called once per window, after quiescence:

1. dumps the SOURCE with a digest-pinned ``pg_dump`` image in a throwaway container
   (custom format, ``--lock-wait-timeout``), streamed into a NEW 0600 file of an exclusive
   0700 run directory; the source URL travels only in the child environment (``-e NAME``),
   never in argv, output, exceptions or the receipt;
2. starts a disposable clone cluster from a digest-pinned image in a NEW ``--internal``
   Docker network (no egress), mirrors the source role NAMES only (NOLOGIN NOINHERIT, no password),
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

from copy import deepcopy
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import ipaddress
import math
import os
from pathlib import Path
import re
import secrets
import select
import signal
import stat
import subprocess
import sys
import time
from urllib.parse import parse_qsl, urlsplit

import first_transition_database as fdb
import first_transition_auth_preflight as authenticated
from first_transition_adapter import Plan, digest, validate_clone_receipt
from first_transition_capture_contract import V3_CATEGORIES
from first_transition_host_driver import _absolute
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA, CLONE_FIELDS, MigrationExecutor, ProcessRunner
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
ORIGIN_RECEIPT_SCHEMA = 'igreja12.first-transition-origin-window-backup/1'
ORIGIN_PROOF_SCHEMA = 'igreja12.window-origin-proof/1'
ORIGIN_PROOF_BUDGET_S = 1200
ORIGIN_CAPTURE_BUDGET_S = 240
ORIGIN_PHASE_GAP_S = 60
ORIGIN_PROOF_MAX_AGE_S = 60
WINDOW_REQUEST_FIELDS = frozenset(('schema', 'nonce', 'plan_digest', 'source_identity', 'baseline_digest',
                                   'config_digest', 'quiescence_digest'))
# Linux UAPI (linux/fcntl.h). Some Python builds omit the symbolic constants;
# the kernel must still confirm all four seals. No unsealed/platform fallback.
MEMFD_ADD_SEALS = getattr(fcntl, 'F_ADD_SEALS', 1033)
MEMFD_GET_SEALS = getattr(fcntl, 'F_GET_SEALS', 1034)
MEMFD_SEALS = 0x01 | 0x02 | 0x04 | 0x08  # SEAL, SHRINK, GROW, WRITE


class NativeWorkerSupervisor:
    """External Linux deadline for one explicitly launched, trusted local worker.

    The worker gets a fresh session, minimal environment and optional sealed
    input FD, never a URI/secret in argv. stdout is bounded private metadata;
    stderr is discarded. A pidfd observes exit WITHOUT reaping the leader, so
    the owned process-group ID cannot be recycled before group termination.
    Every outcome kills that own group before reaping, including success.

    Requires a dedicated single-thread parent with no foreign child reaper.
    pidfd observes identity/exit; it is NOT a numeric process-group lock.
    Worker subprocesses must remain in this group; daemon/container resources
    are NOT local descendants and require separate owned cleanup/verification.
    An uninterruptible worker may remain unreaped: no retry/receipt is allowed.
    Process creation itself is not interruptible by this deadline; a trusted
    local launcher/runtime and its startup verification remain prerequisites.
    This is no sandbox, source authorization, recovery receipt or CLI entry.
    """
    def __init__(self, *, cleanup_wait=2):
        require(sys.platform == 'linux' and hasattr(os, 'pidfd_open')
                and type(cleanup_wait) in (int, float) and math.isfinite(cleanup_wait)
                and 0 < cleanup_wait <= 10, 'window-origin-worker-config')
        self.cleanup_wait, self.used, self.unreaped = cleanup_wait, False, False
        self.leaked_descendants = False

    @staticmethod
    def _remaining(deadline):
        remaining = deadline - time.monotonic()
        require(remaining > 0, 'window-origin-worker-timeout')
        return remaining

    def _stop(self, process):
        # waitid WNOWAIT proves this is still our unreaped child. Do not poll/
        # reap before killing the group: that would permit PID/PGID reuse.
        try:
            os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            require(os.getpgid(process.pid) == process.pid, 'window-origin-worker-ownership')
            self.leaked_descendants = any(pid != process.pid for pid in self._active_group(process.pid))
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + self.cleanup_wait
            while self._active_group(process.pid):
                self._remaining(deadline)
                time.sleep(min(.01, self._remaining(deadline)))
            return process.wait(timeout=max(.001, self._remaining(deadline)))
        except BaseException:
            self.unreaped = True
            raise Refused('window-origin-worker-cleanup-failed') from None

    @staticmethod
    def _active_group(pgid):
        """Own group only, process-state metadata; never cmdline/environment.

        Leader remains unreaped throughout this check, under the dedicated
        reaper precondition. Disappearing /proc entries are benign; inability
        to inspect other process-state entries refuses rather than guessing.
        """
        active = []
        with os.scandir('/proc') as entries:
            for entry in entries:
                if not entry.name.isdecimal():
                    continue
                try:
                    fields = (Path(entry.path) / 'stat').read_bytes().rsplit(b')', 1)[1].split()
                except FileNotFoundError:
                    continue
                if int(fields[2]) != pgid:
                    continue
                if fields[0] not in (b'Z', b'X'):
                    active.append(int(entry.name))
                else:
                    # A dead thread-group leader alone does not prove that
                    # every native thread has stopped. A disappearing task
                    # must not hide its still-active siblings.
                    try:
                        tasks = list((Path(entry.path) / 'task').iterdir())
                    except FileNotFoundError:
                        require(not Path(entry.path).exists(), 'window-origin-worker-cleanup-unknown')
                        continue
                    require(tasks, 'window-origin-worker-cleanup-unknown')
                    seen = False
                    for task in tasks:
                        try:
                            state = (task / 'stat').read_bytes().rsplit(b')', 1)[1].split()[0]
                        except FileNotFoundError:
                            continue
                        seen = True
                        if state not in (b'Z', b'X'):
                            active.append(int(entry.name))
                            break
                    require(seen, 'window-origin-worker-cleanup-unknown')
        return active

    def run(self, argv, *, timeout, max_output=131072, input_fd=None):
        require(not self.used and not self.unreaped, 'window-origin-worker-used')
        self.used = True
        process = pidfd = None
        result, failed, interrupted = None, False, False
        try:
            require(type(argv) is tuple and argv and _absolute(argv[0])
                    and all(type(arg) is str and 0 < len(arg) <= 4096
                            and not any(c in arg for c in '\r\n\x00')
                            and not re.search(r'postgres(?:ql)?://|password=|PGPASSWORD', arg, re.I)
                            for arg in argv)
                    and type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 1200
                    and type(max_output) is int and 0 < max_output <= 131072
                    and signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL
                    and len(os.listdir('/proc/self/task')) == 1,
                    'window-origin-worker-config')
            env = dict(PATH='/usr/bin:/bin', LC_ALL='C', PYTHON_DOTENV_DISABLED='1')
            if input_fd is not None:
                require(type(input_fd) is int and input_fd > 2
                        and stat.S_ISREG(os.fstat(input_fd).st_mode)
                        and 0 < os.fstat(input_fd).st_size <= 2097152
                        and fcntl.fcntl(input_fd, MEMFD_GET_SEALS) & MEMFD_SEALS == MEMFD_SEALS,
                        'window-origin-worker-config')
                env['IGREJA12_NATIVE_INPUT_FD'] = str(input_fd)
            deadline = time.monotonic() + timeout
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, close_fds=True, shell=False, cwd='/',
                                       env=env, start_new_session=True,
                                       pass_fds=() if input_fd is None else (input_fd,))
            pidfd = os.pidfd_open(process.pid)
            require(os.getpgid(process.pid) == process.pid, 'window-origin-worker-ownership')
            outfd = process.stdout.fileno()
            os.set_blocking(outfd, False)
            chunks, total = [], 0
            while True:
                ready, _, _ = select.select((outfd,), (), (), self._remaining(deadline))
                require(ready, 'window-origin-worker-timeout')
                try:
                    chunk = os.read(outfd, min(65536, max_output + 1 - total))
                except BlockingIOError:
                    continue
                if not chunk:
                    break
                total += len(chunk)
                require(total <= max_output, 'window-origin-worker-output-bound')
                chunks.append(chunk)
            ready, _, _ = select.select((pidfd,), (), (), self._remaining(deadline))
            require(ready, 'window-origin-worker-timeout')
            result = b''.join(chunks)
            self._remaining(deadline)
        except Exception:
            failed = True
        except BaseException:
            failed = interrupted = True
        finally:
            code = None
            try:
                if process is not None:
                    try:
                        code = self._stop(process)
                    except BaseException:
                        failed = True
                    if process.stdout is not None:
                        try:
                            process.stdout.close()
                        except BaseException:
                            failed = True
            finally:
                if pidfd is not None:
                    os.close(pidfd)
        require(not self.unreaped, 'window-origin-worker-cleanup-failed')
        if interrupted:
            raise KeyboardInterrupt from None
        require(not failed and not self.leaked_descendants and code == 0 and result is not None,
                'window-origin-worker-failed')
        return result


@dataclass(frozen=True)
class NativeSourcePolicy:
    """Independent native pins, not caller metadata or permission for a login.

    Only the managed postgres/postgres 17.6 profile is supported. No factory
    binds this policy to OriginWindowPorts yet; direct URI consumers still need
    their own complete admission. Native observation is not an A8 receipt.
    """
    host: str
    hostaddr: str
    port: int
    ca_file: str
    ca_sha256: str
    ca_owner: int = 0

    def validated(self):
        try:
            require(type(self.host) is str and len(self.host) <= 253
                    and re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)*', self.host)
                    and type(self.hostaddr) is str and str(ipaddress.ip_address(self.hostaddr)) == self.hostaddr
                    and type(self.port) is int and 0 < self.port < 65536
                    and _absolute(self.ca_file) and type(self.ca_sha256) is str
                    and re.fullmatch('[0-9a-f]{64}', self.ca_sha256)
                    and type(self.ca_owner) is int and self.ca_owner >= 0, 'window-origin-source-policy')
            return self
        except (TypeError, ValueError):
            raise Refused('window-origin-source-policy') from None


class NativeSourceConnector:
    """Explicit authenticated libpq reader connection; no SQL at connection time.

    Startup/role/identity are checked by NativeSourceSnapshot after BEGIN/import.
    No safety query may run on an importer before SET TRANSACTION SNAPSHOT.
    Native IO needs an external worker deadline; connect_timeout alone cannot
    bound local filesystem or every authentication/driver path.
    """
    OPTIONS = ('-c default_transaction_read_only=on -c search_path=pg_catalog,public '
               '-c row_security=off -c statement_timeout=8000')

    def __init__(self, policy, *, secret, driver=None):
        require(type(policy) is NativeSourcePolicy and callable(secret)
                and (driver is None or callable(driver)), 'window-origin-source-policy')
        self.policy, self.secret, self.driver = policy.validated(), secret, driver

    def _ca(self):
        """Hash a bounded public CA in a private, symlink-free provisioned directory."""
        parent = NativeWindowArtifacts._directory(str(Path(self.policy.ca_file).parent))
        fd = None
        try:
            s = os.fstat(parent)
            require(s.st_uid == self.policy.ca_owner and stat.S_IMODE(s.st_mode) == 0o700,
                    'window-origin-source-policy')
            fd = os.open(Path(self.policy.ca_file).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                         | os.O_NONBLOCK, dir_fd=parent)
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_uid == self.policy.ca_owner
                    and stat.S_IMODE(before.st_mode) in (0o600, 0o644) and before.st_nlink == 1
                    and 0 < before.st_size <= 65536, 'window-origin-source-policy')
            data = os.read(fd, 65537)
            after = os.fstat(fd)
            fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_uid', 'st_nlink')
            pin = tuple(getattr(before, key) for key in fields)
            require(len(data) == before.st_size and hashlib.sha256(data).hexdigest() == self.policy.ca_sha256
                    and pin == tuple(getattr(after, key) for key in fields), 'window-origin-source-policy')
            return pin, data
        finally:
            if fd is not None:
                os.close(fd)
            os.close(parent)

    def validated_uri(self):
        """One explicit credential/route for native readers AND the dump child."""
        try:
            fdb.require_explicit_environment()
            from psycopg2.extensions import parse_dsn
            require(parse_dsn('sslcertmode=disable') == {'sslcertmode': 'disable'},
                    'window-origin-source-policy')
            value = self.secret()
            require(type(value) is str and len(value) <= 4096 and value.startswith('postgresql://')
                    and not any(c in value for c in '\r\n\x00'), 'window-origin-source-policy')
            uri = urlsplit(value)
            options = parse_qsl(uri.query, keep_blank_values=True)
            require(not uri.fragment and len(options) == len(dict(options))
                    and {key for key, _ in options} <= {'sslmode', 'connect_timeout', 'application_name'},
                    'window-origin-source-policy')
            dsn = parse_dsn(value)
            require(set(dsn) <= {'host', 'port', 'dbname', 'user', 'password', 'sslmode',
                                  'connect_timeout', 'application_name'}
                    and dsn.get('host') == self.policy.host and int(dsn.get('port', '5432')) == self.policy.port
                    and dsn.get('dbname') == dsn.get('user') == 'postgres' and bool(dsn.get('password'))
                    and dsn.get('sslmode', 'verify-full') == 'verify-full', 'window-origin-source-policy')
            return value, dsn
        except Exception:
            raise Refused('window-origin-source-failed') from None
        except BaseException:
            raise KeyboardInterrupt from None

    def connect(self, *, timeout):
        connection = ca_fd = None
        try:
            fdb.require_explicit_environment()
            require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 8,
                    'window-origin-source-policy')
            import psycopg2
            from psycopg2.extensions import parse_dsn
            # Refuse unsupported client-cert disabling before any login. No
            # inherited ~/.postgresql client certificate/key may be selected.
            require(parse_dsn('sslcertmode=disable') == {'sslcertmode': 'disable'},
                    'window-origin-source-policy')
            value, _ = self.validated_uri()
            ca_pin, ca_bytes = self._ca()
            ca_fd = os.memfd_create('igreja12-native-ca', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            require(os.write(ca_fd, ca_bytes) == len(ca_bytes), 'window-origin-source-policy')
            fcntl.fcntl(ca_fd, MEMFD_ADD_SEALS, MEMFD_SEALS)
            require(fcntl.fcntl(ca_fd, MEMFD_GET_SEALS) & MEMFD_SEALS == MEMFD_SEALS,
                    'window-origin-source-policy')
            required = dict(host=self.policy.host, hostaddr=self.policy.hostaddr, port=str(self.policy.port),
                            dbname='postgres', user='postgres', sslmode='verify-full',
                            sslrootcert=f'/proc/self/fd/{ca_fd}', options=self.OPTIONS, gssencmode='disable',
                            channel_binding='require', ssl_min_protocol_version='TLSv1.2', sslcertmode='disable')
            connection = (self.driver or psycopg2.connect)(value, **required,
                          connect_timeout=max(1, int(timeout)), application_name='igreja12-native-source')
            info = connection.info
            require(not connection.closed and info.used_password is True and info.ssl_in_use is True
                    and info.ssl_attribute('protocol') in ('TLSv1.2', 'TLSv1.3')
                    and info.server_version == 170006 and type(info.server_version) is int
                    and info.transaction_status == 0
                    and all(info.dsn_parameters.get(key) == value for key, value in required.items())
                    and self._ca()[0] == ca_pin, 'window-origin-source-authentication')
            return connection
        except Exception:
            if connection is not None:
                try:
                    connection.close()
                except BaseException:
                    pass
            raise Refused('window-origin-source-failed') from None
        except BaseException:
            if connection is not None:
                try:
                    connection.close()
                except BaseException:
                    pass
            raise KeyboardInterrupt from None
        finally:
            if ca_fd is not None:
                os.close(ca_fd)


class NativeSourceSnapshot:
    """Single-use RR/read-only holder and sequential imported reader sessions.

    Explicit enter authenticates and exports; each reader imports BEFORE any
    SELECT, proves managed startup/role/identity/V1 baseline and snapshot equality.
    Callers must supply reviewed V2/V3 collectors and a bounded dump worker in a
    later slice. This class does not claim source-unchanged, physical dump usage,
    server-backend absence, recovery fidelity or A8 readiness.
    """
    Q_CONTEXT = ("SELECT current_setting('transaction_read_only'), "
                 "current_setting('transaction_isolation'), pg_current_snapshot()::text")
    Q_EXPORT = 'SELECT pg_export_snapshot()'
    Q_IMPORT = 'SET TRANSACTION SNAPSHOT %s'
    Q_HOLDER = ("SELECT pg_catalog.jsonb_build_object("
        "'database',pg_catalog.current_database(),'readonly',pg_catalog.current_setting('transaction_read_only'),"
        "'isolation',pg_catalog.current_setting('transaction_isolation'),'snapshot',pg_catalog.pg_current_snapshot()::text,"
        "'backend',pg_catalog.pg_backend_pid(),'role',current_user,'session_role',session_user,"
        "'transaction_start',extract(epoch from pg_catalog.transaction_timestamp())::text)")
    HOLDER_FIELDS = frozenset(('database','readonly','isolation','snapshot','backend','role','session_role','transaction_start'))

    def __init__(self, connector, expected, *, clock=None, wall_clock=None):
        require(type(connector) is NativeSourceConnector and isinstance(expected, fdb.DatabaseExpectation),
                'window-origin-snapshot-config')
        self.connector, self.expected = connector, expected.validated()
        self.clock, self.wall_clock = clock or time.monotonic, wall_clock or time.time
        self._used = self._failed = False
        self._holder = self._reader = None
        self._snapshot = self._state = None
        self._holder_state = self._holder_cursor = None
        self._deadline = None

    def _remaining(self):
        value = self._deadline - self.clock()
        require(math.isfinite(value) and value > 0, 'window-origin-snapshot-timeout')
        return value

    @staticmethod
    def _finish(connection):
        if connection is None:
            return
        try:
            with connection.cursor() as cursor:
                cursor.execute('ROLLBACK')
            require(connection.info.transaction_status == 0, 'window-origin-snapshot-closure')
        finally:
            connection.close()
        require(connection.closed, 'window-origin-snapshot-closure')

    def _observe(self, connection, *, imported=None):
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(fdb.Q_BEGIN)
            if imported is not None:
                cursor.execute(self.Q_IMPORT, (imported,))
            # First SELECT comes only after the imported snapshot is selected.
            cursor.execute(fdb.Q_TIMEOUT, (f'{max(1, int(min(8, self._remaining()) * 1000))}ms',))
            cursor.fetchall()
            cursor.execute(self.Q_CONTEXT)
            context = cursor.fetchall()
            require(len(context) == 1 and context[0][:2] == ('on', 'repeatable read')
                    and type(context[0][2]) is str and 0 < len(context[0][2]) <= 65536,
                    'window-origin-snapshot-context')
            cursor.execute(authenticated.QUERY)
            rows = cursor.fetchall()
            require(len(rows) == 1 and cursor.description is not None
                    and len(cursor.description) == len(rows[0]), 'window-origin-snapshot-context')
            safety = dict(zip((column[0] for column in cursor.description), rows[0]))
            authenticated._validate_safety_row(safety, expected_identity=self.expected.identity,
                                               now=self.wall_clock())
            require(safety['server_version_num'] == 170006, 'window-origin-snapshot-context')
            cursor.execute(fdb.Q_LEDGER)
            ledger = tuple(row[0] for row in cursor.fetchall())
            catalog = fdb._catalog(cursor)
            require(ledger == self.expected.ledger and catalog == self.expected.catalog,
                    'window-origin-snapshot-baseline')
        self._remaining()
        return digest(context[0][2])

    def __enter__(self):
        require(not self._used, 'window-origin-snapshot-used')
        self._used = True
        self._deadline = self.clock() + ORIGIN_CAPTURE_BUDGET_S
        try:
            self._holder = self.connector.connect(timeout=min(8, self._remaining()))
            self._state = self._observe(self._holder)
            with self._holder.cursor() as cursor:
                cursor.execute(self.Q_EXPORT)
                rows = cursor.fetchall()
                require(len(rows) == 1 and len(rows[0]) == 1 and type(rows[0][0]) is str
                        and re.fullmatch(r'[0-9A-F]{8}-[0-9A-F]{8}-[1-9][0-9]*', rows[0][0]),
                        'window-origin-snapshot-export')
                self._snapshot = rows[0][0]
            self._holder_state = self._read_holder_state()
            self._remaining()
            return self
        except Exception:
            self._failed = True
            self.close()
            raise Refused('window-origin-snapshot-failed') from None
        except BaseException:
            self._failed = True
            self.close()
            raise KeyboardInterrupt from None

    def _live(self):
        require(not self._failed and self._holder is not None and self._reader is None
                and not self._holder.closed,
                'window-origin-snapshot-used')
        self._assert_snapshot(self._holder)
        require(self._read_holder_state() == self._holder_state, 'window-origin-holder-changed')

    def _read_holder_state(self):
        self._remaining()
        with self._holder.cursor() as cursor:
            cursor.execute(self.Q_HOLDER)
            rows = cursor.fetchall()
        require(len(rows) == 1 and len(rows[0]) == 1 and type(rows[0][0]) is dict,
                'window-origin-holder-context')
        value = rows[0][0]
        require(set(value) == self.HOLDER_FIELDS and value['database'] == 'postgres'
                and value['role'] == value['session_role'] == 'postgres'
                and value['readonly'] == 'on' and value['isolation'] == 'repeatable read'
                and type(value['snapshot']) is str and digest(value['snapshot']) == self._state
                and type(value['backend']) is int and value['backend'] > 0
                and type(value['transaction_start']) is str and len(value['transaction_start']) <= 64,
                'window-origin-holder-context')
        require(re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', value['transaction_start'])
                and math.isfinite(float(value['transaction_start'])) and float(value['transaction_start']) > 0,
                'window-origin-holder-context')
        self._remaining()
        return dict(value)

    @contextmanager
    def holder_cursor(self):
        """Sequential collector on the actual exporter, with eight-field checks.

        No connection escapes. A pending result must be consumed atomically;
        keepalive probes use a separate cursor on this SAME backend. These
        observations prove continuity, never a fence against other writers.
        """
        handle = None
        try:
            self._live()
            require(self._holder_cursor is None, 'window-origin-holder-used')
            with self._holder.cursor() as cursor:
                handle = _NativeHolderCursor(self, cursor)
                self._holder_cursor = handle
                yield handle
                require(not handle.pending, 'window-origin-holder-pending')
                self._live()
        except Exception:
            self._failed = True
            self.close()
            raise Refused('window-origin-snapshot-failed') from None
        except BaseException:
            self._failed = True
            self.close()
            raise KeyboardInterrupt from None
        finally:
            if handle is not None:
                handle.active = False
            self._holder_cursor = None

    def _assert_snapshot(self, connection):
        require(not connection.closed and type(connection.info.transaction_status) is int
                and connection.info.transaction_status == 2, 'window-origin-snapshot-context')
        self._remaining()
        with connection.cursor() as cursor:
            cursor.execute(self.Q_CONTEXT)
            rows = cursor.fetchall()
            require(len(rows) == 1 and rows[0][:2] == ('on', 'repeatable read')
                    and digest(rows[0][2]) == self._state, 'window-origin-snapshot-context')
        self._remaining()

    def snapshot_id(self):
        """Live token for a future pinned pg_dump --snapshot invocation; not proof of its use."""
        try:
            self._live()
            return self._snapshot
        except Exception:
            self._failed = True
            self.close()
            raise Refused('window-origin-snapshot-failed') from None
        except BaseException:
            self._failed = True
            self.close()
            raise KeyboardInterrupt from None

    def cluster_system_id(self):
        try:
            self._live()
            with self._holder.cursor() as cursor:
                cursor.execute(fdb.Q_IDENTITY)
                rows = cursor.fetchall()
                require(len(rows) == 1 and len(rows[0]) == 3, 'window-origin-snapshot-context')
                system, oid, name = rows[0]
                require(type(system) is str and system.isdigit() and type(oid) is int and oid > 0
                        and name == 'postgres' and digest([system, oid, name]) == self.expected.identity,
                        'window-origin-snapshot-context')
            self._live()
            return system
        except Exception:
            self._failed = True
            self.close()
            raise Refused('window-origin-snapshot-failed') from None
        except BaseException:
            self._failed = True
            self.close()
            raise KeyboardInterrupt from None

    @contextmanager
    def reader(self):
        try:
            self._live()
            require(self._holder_cursor is None, 'window-origin-holder-used')
            self._reader = self.connector.connect(timeout=min(8, self._remaining()))
            require(self._observe(self._reader, imported=self._snapshot) == self._state,
                    'window-origin-snapshot-context')
            with self._reader.cursor() as cursor:
                yield cursor
            self._assert_snapshot(self._reader)
            self._finish(self._reader)
            self._reader = None
            self._live()
        except Exception:
            self._failed = True
            self.close()
            raise Refused('window-origin-snapshot-failed') from None
        except BaseException:
            self._failed = True
            self.close()
            raise KeyboardInterrupt from None

    def close(self):
        failed = False
        for connection in (self._reader, self._holder):
            try:
                self._finish(connection)
            except BaseException:
                failed = True
        self._reader = self._holder = None
        if failed:
            self._failed = True
            raise Refused('window-origin-snapshot-failed') from None

    def __exit__(self, *_exc):
        self.close()


class _NativeHolderCursor:
    """Private live exporter cursor; no reusable or caller-declared evidence."""
    def __init__(self, snapshot, cursor):
        self._snapshot, self._cursor = snapshot, cursor
        self.active, self.pending = True, False

    def _guard(self):
        require(self.active and self._snapshot._holder_cursor is self, 'window-origin-holder-used')
        try:
            self._snapshot._live()
        except BaseException:
            self.active = False
            self._snapshot._failed = True
            self._snapshot.close()
            raise

    def state(self):
        self._guard()
        require(not self.pending, 'window-origin-holder-pending')
        return dict(self._snapshot._holder_state)

    def execute(self, sql):
        self._guard()
        require(not self.pending and type(sql) in (str, bytes) and 0 < len(sql) <= 65536,
                'window-origin-holder-pending')
        self._cursor.execute(sql)
        self.pending = True

    def fetchone(self):
        require(self.active and self.pending, 'window-origin-holder-pending')
        row = self._cursor.fetchone()
        self.pending = False
        self._guard()
        return row


class NativeWindowArtifacts:
    """Linux artifact custody only; no source login, capture claim or A8 receipt.

    Explicit enter creates a request-exclusive directory in a preprovisioned
    private root. Capture consumes a nonblocking pipe; verified copy writes to
    a nonblocking pipe ONLY after building and sealing a complete memfd copy.
    Thus a restore consumer never sees an unverified prefix. Original artifacts
    remain private on disk for retention, including partial failure evidence.

    Pipe waits have monotonic deadlines. Local filesystem operations/fsync may
    block in the kernel: the future native runner must also bound this worker's
    lifetime. This is drift detection, not a defense against malicious root.
    No construction of OriginWindowPorts or operational unlock is provided.
    """
    FILES = {'dump': ('window.dump', 104857600), 'companion': ('companion.json', 2097152)}
    BLOCK = 65536

    def __init__(self, root, request_digest, *, owner=0, clock=None):
        require(sys.platform == 'linux' and _absolute(root) and type(request_digest) is str
                and re.fullmatch('[0-9a-f]{64}', request_digest)
                and type(owner) is int and owner >= 0, 'window-origin-artifact-config')
        self.root, self.request_digest, self.owner = root, request_digest, owner
        self.clock = clock or time.monotonic
        self._root_fd = self._run_fd = None
        self._root_inode = self._run_inode = None
        self._artifacts = {}
        self._entered = self._failed = False

    @staticmethod
    def _directory(path):
        """Open each ancestor relative to a pinned dirfd, rejecting symlinks."""
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open('/', flags)
        try:
            for part in Path(path).parts[1:]:
                next_fd = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _private_dir(self, fd):
        s = os.fstat(fd)
        require(stat.S_ISDIR(s.st_mode) and s.st_uid == self.owner and stat.S_IMODE(s.st_mode) == 0o700,
                'window-origin-artifact-invalid')
        return s.st_dev, s.st_ino

    def __enter__(self):
        require(not self._entered and not self._failed, 'window-origin-artifact-used')
        self._entered = True
        try:
            self._root_fd = self._directory(self.root)
            self._root_inode = self._private_dir(self._root_fd)
            os.mkdir(self.request_digest, mode=0o700, dir_fd=self._root_fd)
            self._run_fd = os.open(self.request_digest, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                   | os.O_CLOEXEC, dir_fd=self._root_fd)
            self._run_inode = self._private_dir(self._run_fd)
            os.fsync(self._run_fd)
            os.fsync(self._root_fd)
            return self
        except Exception:
            self._failed = True
            self.close()
            raise Refused('window-origin-artifact-failed') from None
        except BaseException:
            self._failed = True
            self.close()
            raise KeyboardInterrupt from None

    def close(self):
        for fd in [*(item['fd'] for item in self._artifacts.values()), self._run_fd, self._root_fd]:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass  # close all remaining owned descriptors, even after an externally closed FD
        self._artifacts.clear()
        self._run_fd = self._root_fd = None

    def __exit__(self, *_exc):
        self.close()

    def _deadline(self, timeout):
        require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 240,
                'window-origin-artifact-bounds')
        return self.clock() + timeout

    def _remaining(self, deadline):
        remaining = deadline - self.clock()
        require(math.isfinite(remaining) and remaining > 0, 'window-origin-artifact-timeout')
        return remaining

    @staticmethod
    def _pipe(fd):
        require(type(fd) is int and fd >= 0 and stat.S_ISFIFO(os.fstat(fd).st_mode)
                and not os.get_blocking(fd), 'window-origin-artifact-pipe')

    def _links(self):
        require(not self._failed and self._run_fd is not None and self._root_fd is not None,
                'window-origin-artifact-used')
        fresh_root = self._directory(self.root)
        try:
            require(self._private_dir(fresh_root) == self._root_inode
                    and self._private_dir(self._root_fd) == self._root_inode
                    and self._private_dir(self._run_fd) == self._run_inode, 'window-origin-artifact-invalid')
            s = os.stat(self.request_digest, dir_fd=self._root_fd, follow_symlinks=False)
            require(stat.S_ISDIR(s.st_mode) and (s.st_dev, s.st_ino) == self._run_inode,
                    'window-origin-artifact-invalid')
        finally:
            os.close(fresh_root)

    def _pin(self, s):
        require(stat.S_ISREG(s.st_mode) and s.st_uid == self.owner and stat.S_IMODE(s.st_mode) == 0o600
                and s.st_nlink == 1, 'window-origin-artifact-invalid')
        return tuple(getattr(s, key) for key in ('st_dev', 'st_ino', 'st_uid', 'st_mode', 'st_nlink', 'st_size',
                                                'st_mtime_ns', 'st_ctime_ns'))

    def _check(self, kind, deadline, *, copy_fd=None):
        """Positional reads leave the original FD's offset untouched."""
        self._links()
        item = self._artifacts[kind]
        name = self.FILES[kind][0]
        require(self._pin(os.fstat(item['fd'])) == item['pin']
                == self._pin(os.stat(name, dir_fd=self._run_fd, follow_symlinks=False)),
                'window-origin-artifact-invalid')
        total, hashed = 0, hashlib.sha256()
        while True:
            self._remaining(deadline)
            chunk = os.pread(item['fd'], self.BLOCK, total)
            if not chunk:
                break
            total += len(chunk)
            require(total <= item['size'], 'window-origin-artifact-invalid')
            hashed.update(chunk)
            if copy_fd is not None:
                require(os.write(copy_fd, chunk) == len(chunk), 'window-origin-artifact-invalid')
        require(total == item['size'] and hashed.hexdigest() == item['sha256']
                and self._pin(os.fstat(item['fd'])) == item['pin']
                == self._pin(os.stat(name, dir_fd=self._run_fd, follow_symlinks=False)),
                'window-origin-artifact-invalid')
        self._remaining(deadline)
        self._links()
        self._remaining(deadline)

    def capture(self, kind, source_fd, *, timeout, pulse=None):
        """Stream one bounded opaque artifact from a native worker's stdout pipe."""
        fd = None
        try:
            deadline = self._deadline(timeout)
            self._links()
            require(kind in self.FILES and kind not in self._artifacts, 'window-origin-artifact-used')
            self._pipe(source_fd)
            require(pulse is None or callable(pulse), 'window-origin-artifact-config')
            name, maximum = self.FILES[kind]
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=self._run_fd)
            total, hashed, header = 0, hashlib.sha256(), b''
            while True:
                self._remaining(deadline)
                if pulse is not None:
                    pulse()
                interval = self._remaining(deadline)
                readable, _, _ = select.select((source_fd,), (), (), min(interval, 1) if pulse else interval)
                if not readable and pulse is not None:
                    continue
                require(readable, 'window-origin-artifact-timeout')
                try:
                    chunk = os.read(source_fd, self.BLOCK)
                except BlockingIOError:
                    continue
                if not chunk:
                    break
                total += len(chunk)
                require(total <= maximum, 'window-origin-artifact-bounds')
                header = (header + chunk)[:5]
                hashed.update(chunk)
                require(os.write(fd, chunk) == len(chunk), 'window-origin-artifact-invalid')
            require(total > (5 if kind == 'dump' else 0) and (kind != 'dump' or header == b'PGDMP'),
                    'window-origin-artifact-invalid')
            self._remaining(deadline)
            os.fsync(fd)
            self._artifacts[kind] = dict(fd=fd, pin=self._pin(os.fstat(fd)), size=total, sha256=hashed.hexdigest())
            fd = None
            os.fsync(self._run_fd)
            self._check(kind, deadline)
        except Exception:
            self._failed = True
            raise Refused('window-origin-artifact-failed') from None
        except BaseException:
            self._failed = True
            raise KeyboardInterrupt from None
        finally:
            if fd is not None:
                os.close(fd)

    def _pair(self, deadline):
        require(set(self._artifacts) == set(self.FILES), 'window-origin-artifact-incomplete')
        for kind in self.FILES:
            self._check(kind, deadline)

    def metadata(self, *, timeout=10):
        """Hashes/sizes only. Does not claim origin, companion semantics or A8."""
        try:
            self._pair(self._deadline(timeout))
            return dict(request_digest=self.request_digest,
                        artifacts={key: {k: item[k] for k in ('sha256', 'size')}
                                   for key, item in self._artifacts.items()})
        except Exception:
            self._failed = True
            raise Refused('window-origin-artifact-failed') from None
        except BaseException:
            self._failed = True
            raise KeyboardInterrupt from None

    def write_companion(self, data, *, timeout=10):
        """Finalize private metadata after source closure; never overwrite/reuse."""
        self._write_private('companion', data, timeout=timeout)

    def _write_private(self, kind, data, *, timeout=10, pulse=None):
        """Bounded local write shared by fixed, reviewed artifact classes."""
        fd = None
        try:
            deadline = self._deadline(timeout)
            self._links()
            require(kind in self.FILES and kind not in self._artifacts and type(data) is bytes
                    and 0 < len(data) <= self.FILES[kind][1] and (pulse is None or callable(pulse)),
                    'window-origin-artifact-bounds')
            fd = os.open(self.FILES[kind][0], os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                         | os.O_CLOEXEC, 0o600, dir_fd=self._run_fd)
            for offset in range(0, len(data), self.BLOCK):
                self._remaining(deadline)
                if pulse is not None:
                    pulse()
                chunk = data[offset:offset + self.BLOCK]
                require(os.write(fd, chunk) == len(chunk), 'window-origin-artifact-invalid')
            os.fsync(fd)
            self._artifacts[kind] = dict(fd=fd, pin=self._pin(os.fstat(fd)), size=len(data),
                                               sha256=hashlib.sha256(data).hexdigest())
            fd = None
            os.fsync(self._run_fd)
            self._check(kind, deadline)
            if pulse is not None:
                pulse()
        except Exception:
            self._failed = True
            raise Refused('window-origin-artifact-failed') from None
        except BaseException:
            self._failed = True
            raise KeyboardInterrupt from None
        finally:
            if fd is not None:
                os.close(fd)

    @contextmanager
    def verified_fd(self, kind, *, timeout=10):
        """Borrow a complete sealed copy; native restore never reopens a path."""
        staged = None
        try:
            deadline = self._deadline(timeout)
            self._pair(deadline)
            require(kind in self.FILES, 'window-origin-artifact-invalid')
            staged = os.memfd_create('igreja12-native-restore', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            self._check(kind, deadline, copy_fd=staged)
            fcntl.fcntl(staged, MEMFD_ADD_SEALS, MEMFD_SEALS)
            require(fcntl.fcntl(staged, MEMFD_GET_SEALS) & MEMFD_SEALS == MEMFD_SEALS,
                    'window-origin-artifact-invalid')
            self._pair(deadline)
            os.lseek(staged, 0, os.SEEK_SET)
            yield staged
            self._pair(deadline)
        except Exception:
            self._failed = True
            raise Refused('window-origin-artifact-failed') from None
        except BaseException:
            self._failed = True
            raise KeyboardInterrupt from None
        finally:
            if staged is not None:
                os.close(staged)

    def copy_verified(self, kind, target_fd, *, timeout):
        """Deliver a fully checked, sealed snapshot to a nonblocking restore pipe.

        Linux memfd sealing bounds immutable staging to the artifact's size
        (100 MiB dump/2 MiB companion). There is no unsealed fallback.
        """
        staged = None
        try:
            deadline = self._deadline(timeout)
            self._pair(deadline)
            require(kind in self.FILES, 'window-origin-artifact-invalid')
            self._pipe(target_fd)
            staged = os.memfd_create('igreja12-window-artifact', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            self._check(kind, deadline, copy_fd=staged)
            fcntl.fcntl(staged, MEMFD_ADD_SEALS, MEMFD_SEALS)
            require(fcntl.fcntl(staged, MEMFD_GET_SEALS) & MEMFD_SEALS == MEMFD_SEALS,
                    'window-origin-artifact-invalid')
            self._pair(deadline)  # no bytes reach the consumer before all checks and sealing
            offset = 0
            while offset < self._artifacts[kind]['size']:
                self._remaining(deadline)
                chunk = os.pread(staged, self.BLOCK, offset)
                require(chunk, 'window-origin-artifact-invalid')
                while chunk:
                    _, writable, _ = select.select((), (target_fd,), (), self._remaining(deadline))
                    require(writable, 'window-origin-artifact-timeout')
                    try:
                        written = os.write(target_fd, chunk)
                    except BlockingIOError:
                        continue
                    require(written > 0, 'window-origin-artifact-invalid')
                    offset += written
                    chunk = chunk[written:]
            self._pair(deadline)
            return offset
        except Exception:
            self._failed = True
            raise Refused('window-origin-artifact-failed') from None
        except BaseException:
            self._failed = True
            raise KeyboardInterrupt from None
        finally:
            if staged is not None:
                os.close(staged)


@dataclass(frozen=True)
class OriginWindowPorts:
    """Trusted Python composition only, NOT a caller JSON proof or authorization.

    ``context_digest`` is independently pinned by the reviewed native adapter.
    ``admit`` is a bounded local policy check, without login or mutation. It
    must independently admit the SAME raw URI for every consumer,
    including source MigrationExecutor/candidate paths that do not call the
    observer connector. Freezing a URI does not propagate TLS/CA policy: if those
    paths cannot enforce the pinned route/startup/TLS policy, admission MUST fail.
    ``connect`` must freshly enforce that policy and read-only authentication on
    every login. ``backup`` must physically capture, recover,
    compare V2/all V3 categories/counts/projected settings and replay the clone
    for the supplied request and shared snapshot. No such native adapter is
    installed by this contract. The CLI cannot construct these ports from flags.
    """
    context_digest: str
    admit: object
    connect: object
    backup: object
    consumers: object = None

    def validate(self, context):
        require(type(self.context_digest) is str and re.fullmatch('[0-9a-f]{64}', self.context_digest)
                and self.context_digest == digest(context) and callable(self.connect)
                and callable(self.backup) and callable(self.admit), 'window-origin-capability-binding')
        if self.consumers is not None:
            from first_transition_native_transports import NativeSourceTransports
            require(type(self.consumers) is NativeSourceTransports,'window-origin-capability-binding')
            self.consumers.validate(context)


class OriginWindowBackup:
    """Single-use bridge from a journaled A8 request to a trusted native port.

    This validates reported evidence; the port, not a dataclass/hash/boolean,
    is the provenance boundary. Historical schema-2 metadata and the legacy V1
    receipt cannot satisfy it. No fallback, discovery or native implementation
    is provided. Capture starts after the actual request reaches this adapter.
    """

    def __init__(self, config, plan, expected, context, ports, *, secret, clock=None):
        require(type(ports) is OriginWindowPorts, 'window-origin-window-proof-pending')
        ports.validate(context)
        require(isinstance(config, WindowBackupConfig) and isinstance(plan, Plan)
                and isinstance(expected, fdb.DatabaseExpectation) and callable(secret),
                'window-origin-capability-binding')
        require(context['plan_digest'] == plan.digest and context['source_identity'] == expected.identity
                and expected.ledger == plan.baseline
                and context['baseline_digest'] == expected.baseline_digest
                and context['backup_config_digest'] == digest(asdict(config)),
                'window-origin-capability-binding')
        self.config, self.plan, self.expected = config.validated(), plan, expected.validated()
        self.context, self.ports, self.secret = deepcopy(context), ports, secret
        self.clock = clock or time.time
        self.used, self.received_at, self.admitted, self.admission_attempted = False, None, False, False

    def admit_source_consumers(self):
        """Trusted native policy check before any connection, containment or journal.

        No generic native implementation exists here. A JSON success flag cannot
        replace this callable, and failure cannot be retried on this instance.
        """
        require(not self.admission_attempted and not self.used, 'window-origin-already-used')
        self.admission_attempted = True
        try:
            result = self.ports.admit(secret=self.secret, context=deepcopy(self.context))
            require(result is None, 'window-origin-provider-failed')
        except Refused as exc:
            if str(exc) in ('window-origin-native-factory-binding','window-origin-native-admission-incomplete'):
                raise
            raise Refused('window-origin-provider-failed') from None
        except Exception:
            raise Refused('window-origin-provider-failed') from None
        except BaseException:
            raise KeyboardInterrupt from None
        self.admitted = True

    def connect(self, *, timeout):
        # A trusted native adapter receives the SAME frozen explicit provider as
        # capture/migration/bindings; it cannot infer another provider from JSON.
        require(self.admitted, 'window-origin-provider-not-admitted')
        fdb.require_explicit_environment()
        try:
            return self.ports.connect(secret=self.secret, context=deepcopy(self.context), timeout=timeout)
        except Exception:
            raise Refused('window-origin-provider-failed') from None
        except BaseException:
            raise KeyboardInterrupt from None

    @staticmethod
    def _shape(value, keys):
        require(type(value) is dict and set(value) == set(keys), 'window-origin-proof-invalid')

    @staticmethod
    def _time(value):
        return type(value) in (int, float) and math.isfinite(value) and value > 0

    def _request(self, request):
        self._shape(request, WINDOW_REQUEST_FIELDS)
        require(request['schema'] == BACKUP_REQUEST_SCHEMA
                and all(type(request[key]) is str and re.fullmatch('[0-9a-f]{64}', request[key])
                        for key in WINDOW_REQUEST_FIELDS - {'schema'})
                and request['plan_digest'] == self.plan.digest
                and request['source_identity'] == self.expected.identity
                and request['baseline_digest'] == self.expected.baseline_digest
                and request['config_digest'] == self.context['config_digest'], 'window-origin-request')

    def validate_receipt(self, receipt, request_digest):
        """Sanitized proof retained and revalidated by _stored_backup before DDL."""
        try:
            validate_clone_receipt(receipt, self.plan, self.expected.identity, self.expected.baseline_digest)
            require(receipt.get('request_digest') == request_digest, 'window-origin-proof-invalid')
            proof = receipt['origin_window']
            self._shape(proof, ('schema', 'context_digest', 'request_digest', 'request_received_at',
                                'capture', 'recovery'))
            require(proof['schema'] == ORIGIN_PROOF_SCHEMA and proof['context_digest'] == digest(self.context)
                    and proof['request_digest'] == request_digest, 'window-origin-proof-invalid')
            received = proof['request_received_at']
            now = self.clock()
            require(self._time(received) and self._time(now)
                    and (self.received_at is None or received == self.received_at), 'window-origin-proof-invalid')
            capture, recovery = proof['capture'], proof['recovery']
            hashes = ('source_identity', 'baseline_digest', 'dump_sha256', 'companion_sha256', 'snapshot_sha256',
                      'v2_sha256', 'v3_sha256', 'row_counts_sha256', 'settings_projection_sha256')
            flags = ('source_authenticated', 'tls_verify_full', 'read_only', 'repeatable_read', 'same_snapshot',
                     'source_unchanged', 'all_connections_closed', 'artifact_bytes_verified')
            self._shape(capture, (*hashes, *flags, 'started_at', 'finished_at'))
            require(all(type(capture[key]) is str and re.fullmatch('[0-9a-f]{64}', capture[key]) for key in hashes)
                    and all(capture[key] is True for key in flags)
                    and capture['source_identity'] == self.expected.identity
                    and capture['baseline_digest'] == self.expected.baseline_digest
                    and capture['dump_sha256'] == receipt['backup_id'], 'window-origin-proof-invalid')
            self._shape(recovery, ('capture_digest', 'dump_sha256', 'companion_sha256', 'snapshot_sha256',
                                  'v2_sha256', 'v3_sha256', 'row_counts_sha256', 'settings_projection_sha256',
                                  'restored_catalog', 'v3_categories', 'restore_verified', 'started_at', 'finished_at',
                                  'clone_identity', 'clone_rehearsal_digest', 'restored_invalid_indexes',
                                  'final_invalid_indexes', 'clone_isolated', 'cleanup_verified',
                                  'owned_resources_remaining'))
            require(recovery['capture_digest'] == digest(capture)
                    and recovery['restored_catalog'] == self.expected.catalog and recovery['restore_verified'] is True
                    and recovery['clone_identity'] == receipt['clone_rehearsal']['clone_identity']
                    and recovery['clone_rehearsal_digest'] == digest({key: receipt['clone_rehearsal'][key]
                                                                    for key in CLONE_FIELDS})
                    and recovery['clone_isolated'] is True and recovery['cleanup_verified'] is True
                    and all(type(recovery[key]) is int and recovery[key] == 0 for key in
                            ('restored_invalid_indexes', 'final_invalid_indexes', 'owned_resources_remaining'))
                    and all(recovery[key] == capture[key] for key in (
                        'dump_sha256', 'companion_sha256', 'snapshot_sha256', 'v2_sha256', 'v3_sha256',
                        'row_counts_sha256', 'settings_projection_sha256')), 'window-origin-proof-invalid')
            self._shape(recovery['v3_categories'], V3_CATEGORIES)
            for delta in recovery['v3_categories'].values():
                self._shape(delta, ('missing', 'extra', 'changed'))
                require(all(type(value) is int and value == 0 for value in delta.values()),
                        'window-origin-proof-invalid')
            times = (capture['started_at'], capture['finished_at'], recovery['started_at'], recovery['finished_at'])
            require(all(self._time(value) for value in times)
                    and received <= times[0] < times[1] <= times[2] < times[3] <= now
                    and now - received <= ORIGIN_PROOF_BUDGET_S
                    and times[0] - received <= ORIGIN_PHASE_GAP_S
                    and times[2] - times[1] <= ORIGIN_PHASE_GAP_S
                    and now - times[3] <= ORIGIN_PROOF_MAX_AGE_S
                    and times[1] - received <= ORIGIN_CAPTURE_BUDGET_S
                    and times[1] - times[0] <= self.config.timeout('dump_s')
                    and times[3] - times[2] <= self.config.timeout('restore_s')
                    + len(self.plan.pending) * self.config.timeout('migration_s'), 'window-origin-proof-invalid')
            return deepcopy(proof)
        except (KeyError, TypeError, ValueError, OverflowError, RecursionError, Refused):
            raise Refused('window-origin-proof-invalid') from None

    def __call__(self, request):
        require(not self.used, 'window-origin-already-used')
        self.used = True  # failure/interruption consumes this instance too
        require(self.admitted, 'window-origin-provider-not-admitted')
        self._request(request)
        self.received_at = self.clock()
        try:
            receipt = self.ports.backup(deepcopy(request), context=deepcopy(self.context), secret=self.secret,
                                      connect=self.connect, config=self.config, plan=self.plan, expected=self.expected)
        except Exception:
            raise Refused('window-origin-provider-failed') from None
        except BaseException:
            raise KeyboardInterrupt from None
        self._shape(receipt, ('schema', 'plan_digest', 'source_identity', 'baseline_digest', 'restore_verified',
                              'request_digest', 'backup_id', 'clone_rehearsal', 'origin_window'))
        require(receipt['schema'] == ORIGIN_RECEIPT_SCHEMA, 'window-origin-proof-invalid')
        proof = deepcopy(receipt['origin_window'])
        self._shape(proof, ('schema', 'context_digest', 'request_digest', 'capture', 'recovery'))
        proof['request_received_at'] = self.received_at
        bound = {**receipt, 'origin_window': proof}
        normalized = self.validate_receipt(bound, digest(request))
        return {**{key: bound[key] for key in ('plan_digest', 'source_identity', 'baseline_digest',
                                             'restore_verified', 'request_digest', 'backup_id')},
                'clone_rehearsal': {key: bound['clone_rehearsal'][key] for key in CLONE_FIELDS},
                'origin_window': normalized}


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
            rc, _ = self._docker(('run', '--rm', '--pull=never', '--network', self.config.dump_network, '-e', SOURCE_ENV,
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
        self._ok(('run', '-d', '--pull=never', '--name', name, '--network', name, '--label', 'igreja12.window-backup=' + name,
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
                    cur.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOINHERIT').format(sql.Identifier(role)))
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
