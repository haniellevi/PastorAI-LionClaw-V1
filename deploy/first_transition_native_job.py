"""Explicit native capture/recovery composition; no operational CLI/factory.

Run this trusted job inside NativeWorkerSupervisor in a dedicated runtime.
The result is NOT an OriginWindowBackup receipt and never unlocks A8. Local
fixtures exercise the actual composition with synthetic PostgreSQL/Docker IO.
"""
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time
from types import ModuleType

import first_transition_database as db
from first_transition_native_events import NativeWindowEvents
import first_transition_native_readers as readers
from first_transition_adapter import Plan, APPLICATION_SHA, EXECUTOR_SHA, digest
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA, CLONE_FIELDS, MigrationExecutor
from first_transition_host_driver import STARTED
from first_transition_window_backup import (
    CLONE_DB, CLONE_ENV, RESTORE_ENV, MEMFD_ADD_SEALS, MEMFD_GET_SEALS, MEMFD_SEALS,
    WINDOW_REQUEST_FIELDS, NativeSourceConnector, NativeSourceSnapshot,
    NativeWindowArtifacts, WindowBackup, WindowBackupConfig,
)
from initial_transition_ops import Refused, require

HEX = re.compile('[0-9a-f]{64}')
COMPANION_SCHEMA = 'igreja12.native-window-companion/1'
JOB_SCHEMA = 'igreja12.native-window-job-result/1'
OWNER_LABEL = 'igreja12.native-window'
TOKEN_LABEL = 'igreja12.native-token'
CONTAINER_VIEW = ('[{{json .Id}},{{json .Image}},{{json .Config.Image}},{{json .HostConfig.NetworkMode}},'
    '[{{range $name,$net := .NetworkSettings.Networks}}[{{json $name}},{{json $net.NetworkID}},'
    '{{json $net.IPAddress}}],{{end}}null],'
    '[{{range .Mounts}}[{{json .Type}},{{json .Destination}}],{{end}}null],'
    '{{json .HostConfig.PortBindings}},{{json (index .Config.Labels "'+OWNER_LABEL+'")}},'
    '{{json (index .Config.Labels "'+TOKEN_LABEL+'")}},{{json .State.Running}},'
    '{{json .State.Restarting}},{{json .RestartCount}},{{json .State.StartedAt}},'
    '{{json .HostConfig.RestartPolicy.Name}},{{json .HostConfig.Privileged}},{{json .HostConfig.Tmpfs}}]')
NETWORK_VIEW = ('[{{json .Id}},{{json .Name}},{{json .Internal}},{{json .Driver}},'
    '{{json (index .Labels "'+OWNER_LABEL+'")}},{{json (index .Labels "'+TOKEN_LABEL+'")}},'
    '[{{range $id,$container := .Containers}}{{json $id}},{{end}}null]]')
IMAGE_VIEW = '[{{json .Id}}]'
CLONE_COMMAND = ('postgres','-c','shared_preload_libraries=','-c','session_preload_libraries=',
                 '-c','local_preload_libraries=')
CLONE_TMPFS = {'/var/lib/postgresql/data': 'rw,nosuid,nodev,noexec,size=536870912'}
ROLE_QUERY = 'SELECT current_user, session_user'
MIGRATION_PATH_SQL = 'SET search_path TO "$user",public'
PROBE_PATH_SQL = 'SET search_path TO pg_catalog,public'


def _sealed(name, data):
    fd = os.memfd_create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        for offset in range(0, len(data), 65536):
            chunk = data[offset:offset + 65536]
            require(os.write(fd, chunk) == len(chunk), 'native-job-fd')
        fcntl.fcntl(fd, MEMFD_ADD_SEALS, MEMFD_SEALS)
        require(fcntl.fcntl(fd, MEMFD_GET_SEALS) & MEMFD_SEALS == MEMFD_SEALS, 'native-job-fd')
        return fd
    except BaseException:
        os.close(fd)
        raise


@dataclass(frozen=True)
class NativeDumpSpec:
    """Independently approved local pg_dump ELF; never discover/download one."""
    binary: str
    sha256: str
    owner: int = 0

    @contextmanager
    def executable(self):
        directory = fd = sealed = None
        try:
            path = Path(self.binary)
            require(path.is_absolute() and '..' not in path.parts and HEX.fullmatch(self.sha256)
                    and type(self.owner) is int and self.owner >= 0, 'native-dump-spec')
            directory = NativeWindowArtifacts._directory(str(path.parent))
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_uid == self.owner and before.st_nlink == 1
                    and stat.S_IMODE(before.st_mode) in (0o755, 0o555) and 4 < before.st_size <= 33554432,
                    'native-dump-spec')
            data = bytearray()
            while len(data) <= before.st_size:
                chunk = os.read(fd, min(65536, before.st_size + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            fields = ('st_dev','st_ino','st_size','st_uid','st_mode','st_nlink','st_mtime_ns','st_ctime_ns')
            require(len(data) == before.st_size and data[:4] == b'\x7fELF'
                    and hashlib.sha256(data).hexdigest() == self.sha256
                    and all(getattr(before,k) == getattr(os.fstat(fd),k) for k in fields), 'native-dump-spec')
            sealed = _sealed('igreja12-pinned-pg-dump', data)
            yield sealed
        finally:
            for opened in (sealed, fd, directory):
                if opened is not None:
                    os.close(opened)


@dataclass(frozen=True)
class NativeJobPins:
    """Independent review-time pins; never derive these from a report flag."""
    context_sha256: str
    source_policy_sha256: str
    dump_spec_sha256: str


class _Pulse:
    def __init__(self, snapshot, token, clock):
        self.snapshot, self.token, self.clock = snapshot, token, clock
        self.last, self.calls, self.maximum = clock(), 0, 0.0

    def __call__(self):
        now = self.clock()
        self.maximum = max(self.maximum, now - self.last)
        require(0 <= now - self.last <= 2, 'native-dump-keepalive-gap')
        if now - self.last >= 1:
            require(self.snapshot.snapshot_id() == self.token, 'native-dump-snapshot')
            now = self.clock()
            self.maximum = max(self.maximum, now - self.last)
            require(0 <= now - self.last <= 2, 'native-dump-keepalive-gap')
            self.last, self.calls = now, self.calls + 1


class NativeDump:
    def __init__(self, spec, connector, *, popen=None, clock=None):
        require(type(spec) is NativeDumpSpec and type(connector) is NativeSourceConnector, 'native-dump-config')
        self.spec, self.connector, self.popen = spec, connector, popen or subprocess.Popen
        self.clock, self.used = clock or time.monotonic, False
        self._pulse = None

    def keepalive(self, snapshot):
        """The SAME successful dump pulse, without resetting its elapsed gap."""
        require(self._pulse is not None and self._pulse.snapshot is snapshot, 'native-dump-keepalive-unavailable')
        self._pulse()
        return self._pulse

    def run(self, snapshot, artifacts):
        require(not self.used, 'native-dump-used')
        self.used = True
        process = ca_fd = service_fd = completed = None
        try:
            token = snapshot.snapshot_id()
            _, dsn = self.connector.validated_uri()
            ca_pin, ca_bytes = self.connector._ca()
            ca_fd = _sealed('igreja12-pg-dump-ca', ca_bytes)
            p = self.connector.policy
            env = dict(PATH='/usr/bin:/bin', LC_ALL='C', PGHOST=p.host, PGHOSTADDR=p.hostaddr,
                       PGPORT=str(p.port), PGDATABASE='postgres', PGUSER='postgres', PGPASSWORD=dsn['password'],
                       PGSSLMODE='verify-full', PGSSLROOTCERT=f'/proc/self/fd/{ca_fd}',
                       PGGSSENCMODE='disable', PGCHANNELBINDING='require', PGSSLCERTMODE='disable',
                       PGSSLMINPROTOCOLVERSION='TLSv1.2', PGCONNECT_TIMEOUT='8',
                       PGOPTIONS=self.connector.OPTIONS, PGAPPNAME='igreja12-native-dump')
            # Conninfo service keywords are mandatory: an old libpq refuses
            # unknown sslcertmode/etc instead of silently ignoring newer env
            # variables. No password is stored in the service or argv.
            service = dict(host=p.host, hostaddr=p.hostaddr, port=str(p.port), dbname='postgres',user='postgres',
                sslmode='verify-full',sslrootcert=env['PGSSLROOTCERT'],gssencmode='disable',channel_binding='require',
                sslcertmode='disable',ssl_min_protocol_version='TLSv1.2',connect_timeout='8',
                options=self.connector.OPTIONS,application_name='igreja12-native-dump')
            require(all(not any(c in v for c in '\r\n\x00') for v in service.values()), 'native-dump-service')
            service_fd = _sealed('igreja12-pg-dump-service',
                ('[igreja12_native]\n'+''.join(k+'='+v+'\n' for k,v in service.items())).encode())
            env['PGSERVICEFILE'],env['PGSERVICE'] = f'/proc/self/fd/{service_fd}','igreja12_native'
            deadline = self.clock() + min(90, snapshot._remaining())
            pulse = _Pulse(snapshot, token, self.clock)
            with self.spec.executable() as executable:
                require(self.clock() < deadline and snapshot.snapshot_id() == token,'native-dump-boundary')
                pulse()
                process = self.popen((f'/proc/self/fd/{executable}', '--format=custom', '--no-password',
                                      '--lock-wait-timeout=1s','--dbname=service=igreja12_native','--snapshot='+token),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    env=env, shell=False, close_fds=True, start_new_session=False,
                    pass_fds=(executable, ca_fd, service_fd))
                os.set_blocking(process.stdout.fileno(), False)
                artifacts.capture('dump', process.stdout.fileno(), timeout=deadline-self.clock(), pulse=pulse)
                require(process.wait(timeout=max(.001, deadline-self.clock())) == 0, 'native-dump-exit')
            pulse()
            require(self.clock() < deadline and snapshot.snapshot_id() == token
                    and self.connector._ca()[0] == ca_pin, 'native-dump-boundary')
            item = artifacts._artifacts['dump']
            completed = pulse
            return dict(sha256=item['sha256'], size=item['size'], snapshot_id=token,
                        pulse_calls=pulse.calls, maximum_pulse_gap_s=pulse.maximum,
                        binary_sha256=self.spec.sha256)
        except Exception:
            self._pulse = None
            raise Refused('native-dump-failed') from None
        except BaseException:
            self._pulse = None
            raise KeyboardInterrupt from None
        finally:
            cleanup_failed = False
            if process is not None:
                try:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=2)
                except BaseException:
                    cleanup_failed = True
                try:
                    process.stdout.close()
                except BaseException:
                    cleanup_failed = True
            try:
                for fd in (ca_fd,service_fd):
                    if fd is not None:
                        os.close(fd)
            finally:
                if cleanup_failed:
                    self._pulse = None
                require(not cleanup_failed, 'native-dump-cleanup-failed')
            self._pulse = completed


class OwnedClone:
    """One private container/network by returned IDs; no adoption by name.

    Legacy bootstrap is intentionally limited. Missing globals/settings/ACLs
    MUST fail the strict comparison; this class never weakens observed data.
    Database identity probes and SQL use the SAME native connection per step.
    """
    def __init__(self, config, plan, expected, request_digest, daemon_id, source_system,
                 *, run=None, clone_connect=None, clock=None, work_deadline=None, cleanup_deadline=None, owner=0):
        self.config, self.plan, self.expected = config, plan, expected
        self.request, self.daemon, self.source_system = request_digest, daemon_id, source_system
        self.clock = clock or time.monotonic
        self.work_deadline, self.cleanup_deadline = work_deadline, cleanup_deadline
        self.owner = owner
        self.transport = WindowBackup(config, plan, expected, secret=lambda: '', connect=lambda **_: None,
                                      run=run, clone_connect=clone_connect or self._default_connect)
        self.token = secrets.token_hex(16)
        self.name = 'igreja12-native-'+request_digest[:12]+'-'+self.token[:12]
        self.container = self.network = self.image = self.address = self.started = self.system = self.identity = None
        self.password = secrets.token_hex(24)
        self.ambiguous = self.cleaned = self.cleaning = False

    def _default_connect(self, *, host, dbname, user, password, timeout):
        import psycopg2
        db.require_explicit_environment()
        return psycopg2.connect(host=host, port=5432, dbname=dbname, user=user, password=password,
            connect_timeout=max(1,int(timeout)), sslmode='disable', application_name='igreja12-owned-native-clone',
            options=('-c search_path=pg_catalog,public -c row_security=off -c session_preload_libraries= '
                     '-c local_preload_libraries= -c statement_timeout='+str(self.config.timeout('migration_s')*1000)))

    def _remaining(self):
        remaining = (self.cleanup_deadline if self.cleaning else self.work_deadline) - self.clock()
        require(remaining > 0, 'native-clone-timeout')
        return remaining

    def _call(self, args, *, capture=False, env=None, stdin=None):
        return self.transport._docker(args, timeout=min(self.config.timeout('docker_s'), self._remaining()),
                                      capture=capture, env=env, stdin=stdin)

    def _ok(self, args, **kwargs):
        rc, out = self._call(args, **kwargs)
        require(rc == 0, 'native-clone-command')
        return out

    def _daemon(self):
        require(json.loads(self._ok(('info','--format','{{json .ID}}'), capture=True)) == self.daemon,
                'native-clone-daemon')

    def _owned(self, *, ready=False, isolation=True):
        network_name=getattr(self,'network_name',self.name)
        self._daemon()
        network = json.loads(self._ok(('network','inspect','--format',NETWORK_VIEW,self.network),capture=True))
        require(type(network) is list and len(network) == 7
                and network[:2] == [self.network,network_name] and network[4:6] == [self.request,self.token]
                and type(network[6]) is list and network[6][-1:] == [None]
                and set(network[6][:-1]) <= ({self.container} if self.container else set()), 'native-clone-network')
        if isolation:
            require(network[2] is True and network[3] == 'bridge', 'native-clone-network')
        if self.container is None:
            return
        c = json.loads(self._ok(('inspect','--format',CONTAINER_VIEW,self.container),capture=True))
        require(type(c) is list and len(c) == 16 and c[:4] == [self.container,self.image,self.config.clone_image,self.network]
                and c[7:9] == [self.request,self.token], 'native-clone-container')
        if isolation:
            require(c[4][-1:] == [None] and len(c[4]) == 2 and c[4][0][:2] == [network_name,self.network]
                    # Docker can omit --tmpfs entries from .Mounts. The exact
                    # HostConfig.Tmpfs declaration is mandatory in both forms.
                    and type(c[15]) is dict and c[15] == CLONE_TMPFS
                    and c[5] in ([None], [['tmpfs','/var/lib/postgresql/data'],None]) and c[6] in (None,{})
                    and c[10] is False and type(c[11]) is int and c[11] == 0 and c[13] == 'no'
                    and c[14] is False, 'native-clone-container')
        if ready:
            require(c[9] is True and type(c[12]) is str and STARTED.fullmatch(c[12])
                    and not c[12].startswith(('0000-','0001-')) and
                    (self.started is None or c[12] == self.started), 'native-clone-running')
            address = c[4][0][2]
            ip = ipaddress.ip_address(address)
            require(ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_link_local
                    and (self.address is None or address == self.address), 'native-clone-address')
            self.address, self.started = address, c[12]

    def __enter__(self):
        try:
            require(self.config.admin_user == self.config.restore_user == self.config.migration_user == 'postgres',
                    'native-clone-profile')
            require(self.config.clone_command in ((), CLONE_COMMAND), 'native-clone-profile')
            self._daemon()
            self.image = json.loads(self._ok(('image','inspect','--format',IMAGE_VIEW,self.config.clone_image),capture=True))[0]
            require(type(self.image) is str and re.fullmatch('sha256:[0-9a-f]{64}',self.image), 'native-clone-image')
            require(self._ok(('ps','-a','--filter','name=^/'+self.name+'$','--format','{{.ID}}'),capture=True) == ''
                    and self._ok(('network','ls','--filter','name=^'+self.name+'$','--format','{{.ID}}'),capture=True) == '',
                    'native-clone-preexisting')
            self.ambiguous = True
            self.network = self._ok(('network','create','--internal','--label',OWNER_LABEL+'='+self.request,
                '--label',TOKEN_LABEL+'='+self.token,self.name),capture=True)
            require(HEX.fullmatch(self.network), 'native-clone-network')
            self._owned(isolation=False)
            self.ambiguous = False
            self._owned()
            self.ambiguous = True
            self.container = self._ok(('run','-d','--pull=never','--name',self.name,'--network',self.network,
                '--restart=no','--tmpfs','/var/lib/postgresql/data:rw,nosuid,nodev,noexec,size=536870912',
                '--label',OWNER_LABEL+'='+self.request,'--label',TOKEN_LABEL+'='+self.token,
                '-e',CLONE_ENV,'-e','PGDATA=/var/lib/postgresql/data',self.config.clone_image,*CLONE_COMMAND),
                capture=True,env={CLONE_ENV:self.password})
            require(HEX.fullmatch(self.container), 'native-clone-container')
            self._owned(isolation=False)
            self.ambiguous = False
            self._owned(ready=True)
            return self
        except BaseException:
            self.close()
            raise

    def _probe(self, conn, database):
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(db.Q_BEGIN)
            try:
                cur.execute(ROLE_QUERY)
                require(cur.fetchall() == [('postgres','postgres')], 'native-clone-role')
                cur.execute(db.Q_IDENTITY)
                rows = cur.fetchall()
                require(len(rows) == 1 and len(rows[0]) == 3, 'native-clone-identity')
                system, oid, name = rows[0]
                require(type(system) is str and system.isdigit() and system != self.source_system
                        and type(oid) is int and oid > 0 and name == database
                        and (self.system is None or self.system == system), 'native-clone-identity')
                self.system = system
                if database == CLONE_DB:
                    identity = (system,oid,name)
                    require(self.identity is None or self.identity == identity, 'native-clone-identity')
                    self.identity = identity
            finally:
                cur.execute('ROLLBACK')

    @contextmanager
    def connection(self, database):
        self._owned(ready=True)
        conn = None
        try:
            deadline = self.clock() + min(self.config.timeout('ready_s'),self._remaining())
            while conn is None:
                try:
                    conn = self.transport.clone_connect(host=self.address, dbname=database, user='postgres',
                        password=self.password, timeout=max(1,min(5,int(self._remaining()))))
                except Exception:
                    require(self.clock() < deadline, 'native-clone-not-ready')
                    time.sleep(min(.1,self._remaining()))
                    self._owned(ready=True)
            require(conn.info.used_password is True and conn.info.user == 'postgres'
                    and type(conn.info.server_version) is int and 170000 <= conn.info.server_version < 180000,
                    'native-clone-authentication')
            self._probe(conn,database)
            self._owned(ready=True)
            yield conn
            self._owned(ready=True)
        finally:
            if conn is not None:
                conn.close()

    def bootstrap(self, sample):
        from psycopg2 import sql
        fields = (('superuser','SUPERUSER','NOSUPERUSER'), ('inherit','INHERIT','NOINHERIT'),
                  ('create_role','CREATEROLE','NOCREATEROLE'), ('create_db','CREATEDB','NOCREATEDB'),
                  ('replication','REPLICATION','NOREPLICATION'), ('bypass_rls','BYPASSRLS','NOBYPASSRLS'))
        roles = json.loads(sample._encoded)['v2']['manifest']['roles']
        by_name = {}
        # Validate the entire requested role policy before any clone DDL. The
        # source inventory never grants permission to add a clone superuser.
        for role in roles:
            require(type(role) is dict and set(role) == {'name','can_login',*(key for key,_,_ in fields)}
                    and type(role['name']) is str and 0 < len(role['name'].encode()) <= 63
                    and '\x00' not in role['name'] and role['name'] not in by_name
                    and all(type(role[key]) is bool for key in ('can_login',*(key for key,_,_ in fields))),
                    'native-clone-role-policy')
            by_name[role['name']] = role
        allowed = set(self.config.clone_superusers)
        require(all(name in by_name and by_name[name]['superuser'] is True
                    and not name.startswith('pg_') for name in allowed)
                and all(not role['superuser'] or name == 'postgres' or name in allowed
                        for name,role in by_name.items()), 'native-clone-role-policy')
        with self.connection('postgres') as admin:
            with admin.cursor() as cur:
                cur.execute('SELECT rolname FROM pg_roles')
                existing = {row[0] for row in cur.fetchall()}
                require(all(name in existing for name in by_name if name == 'postgres' or name.startswith('pg_')),
                        'native-clone-role-policy')
                for name,role in by_name.items():
                    if name == 'postgres' or name.startswith('pg_'):
                        continue
                    if name not in existing:
                        cur.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOINHERIT').format(sql.Identifier(name)))
                    attributes = [yes if role[key] else no for key,yes,no in fields]
                    attributes.append('LOGIN' if name == 'supabase_admin' else 'NOLOGIN')
                    cur.execute(sql.SQL('ALTER ROLE {} '+' '.join(attributes)).format(sql.Identifier(name)))
                cur.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(CLONE_DB)))

    def restore(self, artifacts):
        self._owned(ready=True)
        with artifacts.verified_fd('dump',timeout=min(240,self._remaining())) as fd:
            with os.fdopen(os.dup(fd),'rb') as stream:
                self._ok(('exec','-i','-e',RESTORE_ENV,self.container,'pg_restore','-h','127.0.0.1','-U','postgres',
                    '-d',CLONE_DB,'--exit-on-error','--single-transaction','--no-password'),
                    env={RESTORE_ENV:self.password},stdin=stream)
        self._owned(ready=True)

    @staticmethod
    def _state(cur):
        cur.execute(db.Q_PATH);cur.fetchall()
        cur.execute(db.Q_IDENTITY);identity = tuple(cur.fetchall()[0])
        cur.execute(db.Q_LEDGER);ledger = tuple(r[0] for r in cur.fetchall())
        cur.execute(db.Q_INVALID);invalid = len(cur.fetchall())
        return dict(identity=identity,ledger=ledger,invalid=invalid,catalog=db._catalog(cur))

    def pair(self):
        with self.connection(CLONE_DB) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(db.Q_BEGIN)
                try:
                    before = self._state(cur)
                    sample = readers.collect_on_cursor(cur)
                    require(self._state(cur) == before and before['identity'] == self.identity, 'native-clone-pair')
                    return sample,before
                finally:
                    cur.execute('ROLLBACK')

    def state(self):
        with self.connection(CLONE_DB) as conn:
            from first_transition_window_backup import clone_state
            result = clone_state(conn)
            require(result['identity'] == self.identity, 'native-clone-identity')
            return result

    def replay(self):
        # The pinned executor receives the SAME checked connection, instead of
        # reconnecting by an IP-only URI between identity proof and DDL.
        root = Path(self.config.clone_workdir)
        root_fd = NativeWindowArtifacts._directory(str(root))
        try:
            s = os.fstat(root_fd)
            require(s.st_uid == self.owner and stat.S_IMODE(s.st_mode) == 0o700, 'native-clone-workdir')
        finally:
            os.close(root_fd)
        directory = root/self.request
        directory.mkdir(mode=0o700)
        materializer = MigrationExecutor(self.plan,python=self.config.python,workdir=str(directory),
            secret=lambda:'',runner=lambda *_a,**_k:None)
        namespace = ModuleType('igreja12_pinned_migrate')
        namespace.__file__ = str(directory/'scripts'/'migrate.py')
        namespace.__dict__['print'] = lambda *_a,**_k:None
        exec(compile(self.plan.executor,'<pinned-migrate.py>','exec'),namespace.__dict__)
        ledger = list(self.plan.baseline)
        for index,migration in enumerate(self.plan.pending,1):
            step = materializer._materialize(index,migration)
            with self.connection(CLONE_DB) as conn:
                from first_transition_window_backup import clone_state
                before = clone_state(conn)
                require(before['identity'] == self.identity and before['ledger'] == tuple(sorted(ledger))
                        and before['invalid'] == 0, 'native-clone-replay-state')
                # The CLI starts with PostgreSQL's default path. In particular,
                # CREATE EXTENSION without SCHEMA must not target pg_catalog.
                require(type(conn.info.transaction_status) is int and conn.info.transaction_status == 0,
                        'native-clone-replay-state')
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(MIGRATION_PATH_SQL)
                conn.autocommit = False
                namespace.MIGRATIONS_DIR = Path(step)/'migrations'
                require(namespace.cmd_apply(conn,migration.name,transactional=not migration.concurrent,
                    lock_timeout=0 if migration.concurrent else 2000) == 0, 'native-clone-replay')
                require(type(conn.info.transaction_status) is int and conn.info.transaction_status == 0,
                        'native-clone-replay-state')
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(PROBE_PATH_SQL)
                after = clone_state(conn)
                ledger.append(migration.name)
                require(after['identity'] == self.identity and after['ledger'] == tuple(sorted(ledger))
                        and after['invalid'] == 0, 'native-clone-replay-state')
        return len(self.plan.pending)

    def close(self):
        self.cleaning = True
        require(not self.ambiguous, 'native-clone-cleanup-ambiguous')
        if self.network is None:
            self.cleaned = True
            return
        self._owned(isolation=False)
        for args in ((('rm','-f','-v',self.container),) if self.container else ()) + (('network','rm',self.network),):
            try:
                self._call(args)
            except Exception:
                pass  # exactly one attempt; only fresh absence below can prove cleanup
        self._daemon()
        require((self.container is None or self._ok(('ps','-a','--filter','id='+self.container,'--format','{{.ID}}'),capture=True) == '')
                and self._ok(('network','ls','--filter','id='+self.network,'--format','{{.ID}}'),capture=True) == '',
                'native-clone-cleanup-incomplete')
        self.cleaned = True

    def __exit__(self,*_exc):
        self.close()


class ParentOwnedClone(OwnedClone):
    """Use the parent's sealed, independently pinned IDs; never create/delete.

    Child close confirms only release of local use. Daemon absence MUST be
    established by the parent's original cleanup after the worker is reaped.
    """
    def __init__(self,config,plan,expected,request_digest,daemon_id,source_system,*,parent_clone,**kwargs):
        from first_transition_native_cleanup import NativeDockerCleanup,NativeParentCloneHandle
        require(type(parent_clone) is NativeParentCloneHandle,'native-parent-clone-handoff')
        parent_clone.validate()
        require(parent_clone.config_digest==digest(asdict(config)) and parent_clone.registry.request_digest==request_digest
            and parent_clone.registry.daemon_id==daemon_id and len(parent_clone.registry.containers)==1,
            'native-parent-clone-handoff')
        super().__init__(config,plan,expected,request_digest,daemon_id,source_system,**kwargs)
        self.parent_clone=parent_clone
        r=parent_clone.registry;c=r.containers[0]
        require(c.image_reference==config.clone_image and dict(c.tmpfs)==CLONE_TMPFS,'native-parent-clone-handoff')
        self.token,self.name,self.network_name=r.nonce,c.name,r.network_name
        self.container,self.network,self.image=c.container_id,r.network_id,c.image_id
        self.password=parent_clone._password
        self.child_finished=self._entered=False
        self._inspector=NativeDockerCleanup(r,docker_binary=config.docker_binary,endpoint=config.docker_endpoint,
            config_dir=config.docker_config_dir,runner=self._read_parent if self.transport.run is not None else None,
            clock=self.clock)

    def _read_parent(self,argv,*,timeout,max_output):
        rc,out=self.transport._docker(argv[1:],timeout=min(timeout,self._remaining()),capture=True)
        raw=out.encode();require(len(raw)<=max_output,'native-parent-clone-inspect')
        return rc,raw

    def verify_held(self):
        self.parent_clone.validate()
        present,network=self._inspector.inspect_registered(deadline=self.work_deadline)
        require(present=={self.container} and network,'native-parent-clone-held')
        row=json.loads(self._ok(('inspect','--format',CONTAINER_VIEW,self.container),capture=True))
        require(type(row) is list and len(row)==16 and row[:4]==[self.container,self.image,self.config.clone_image,self.network]
            and row[7:9]==[self.request,self.token] and row[9] is False and row[10] is False
            and type(row[11]) is int and row[11]==0 and row[12]=='0001-01-01T00:00:00Z','native-parent-clone-held')

    def _owned(self,*,ready=False,isolation=True):
        self.parent_clone.validate()
        present,network=self._inspector.inspect_registered(deadline=self.work_deadline)
        require(present=={self.container} and network,'native-parent-clone-inspect')
        super()._owned(ready=ready,isolation=isolation)

    def __enter__(self):
        require(not self._entered and type(self.source_system) is str and self.source_system.isdigit(),
            'native-parent-clone-used')
        self._entered=True
        self.verify_held()
        self._ok(('start',self.container),capture=True)
        self._owned(ready=True)
        return self

    def close(self):
        # No daemon mutation, even on failure. Connection contexts above close
        # their handles; parent cleanup runs independently after worker reaping.
        self.child_finished=True
        self.cleaned=False


class NativeWindowJob:
    """Functional native composition, deliberately not installed as A8 capability.

    Input is the durable request supplied by the controller. Run under the
    external supervisor; no source/clone URI may be inferred from metadata.
    The clone's legacy bootstrap can still refuse richer managed globals; no
    comparator relaxation or automatic ACL/initial-privilege repair is allowed.
    """
    def __init__(self, config, plan, expected, context, connector, dump_spec, daemon_id,
                 pins, *, owner=0, dump_popen=None, run=None, clone_connect=None, clock=None, wall_clock=None, joint=None,
                 parent_clone=None):
        require(type(config) is WindowBackupConfig and isinstance(plan,Plan) and isinstance(expected,db.DatabaseExpectation)
                and plan.application_sha == APPLICATION_SHA and plan.executor_sha == EXECUTOR_SHA
                and expected.validated().ledger == plan.baseline and type(connector) is NativeSourceConnector
                and type(dump_spec) is NativeDumpSpec and type(daemon_id) is str and 0 < len(daemon_id) <= 128
                and context['plan_digest'] == plan.digest and context['source_identity'] == expected.identity
                and context['baseline_digest'] == expected.baseline_digest
                and context['backup_config_digest'] == digest(asdict(config))
                and context['ca_sha256'] == connector.policy.ca_sha256
                and type(pins) is NativeJobPins
                and all(type(v) is str and HEX.fullmatch(v) for v in asdict(pins).values())
                and pins.context_sha256 == digest(context)
                and pins.source_policy_sha256 == digest(asdict(connector.policy))
                and pins.dump_spec_sha256 == digest(asdict(dump_spec))
                and type(owner) is int and owner >= 0 and sys.version_info[:2] == (3,13)
                and Path(config.python).resolve() == Path(sys.executable).resolve(), 'native-job-config')
        self.config,self.plan,self.expected,self.context = config.validated(),plan,expected,deepcopy(context)
        self.connector,self.dump_spec,self.daemon,self.owner = connector,dump_spec,daemon_id,owner
        self.pins = pins
        self.dump_popen,self.run,self.clone_connect = dump_popen,run,clone_connect
        self.clock,self.wall_clock,self.used = clock or time.monotonic,wall_clock or time.time,False
        if joint is not None:
            from first_transition_native_joint import NativeSyntheticJointCapture
            require(type(joint) is NativeSyntheticJointCapture, 'native-job-joint-config')
        self.joint = joint
        if parent_clone is not None:
            from first_transition_native_cleanup import NativeParentCloneHandle
            require(type(parent_clone) is NativeParentCloneHandle,'native-parent-clone-handoff')
        self.parent_clone=parent_clone

    def execute(self, request):
        require(not self.used,'native-job-used')
        self.used = True
        try:
            require(type(request) is dict and set(request) == WINDOW_REQUEST_FIELDS
                    and request['schema'] == BACKUP_REQUEST_SCHEMA
                    and all(type(v) is str and HEX.fullmatch(v) for k,v in request.items() if k != 'schema')
                    and request['plan_digest'] == self.plan.digest and request['source_identity'] == self.expected.identity
                    and request['baseline_digest'] == self.expected.baseline_digest
                    and request['config_digest'] == self.context['config_digest'], 'native-job-request')
            request_digest = digest(request)
            events = NativeWindowEvents(request_digest,digest(self.context),clock=self.clock,wall_clock=self.wall_clock)
            start = self.clock()
            require(self.pins.context_sha256 == digest(self.context)
                    and self.pins.source_policy_sha256 == digest(asdict(self.connector.policy))
                    and self.pins.dump_spec_sha256 == digest(asdict(self.dump_spec)), 'native-job-config')
            parent=None
            if self.parent_clone is not None:
                from first_transition_native_cleanup import NativeParentCloneHandle
                require(type(self.parent_clone) is NativeParentCloneHandle
                    and self.parent_clone.registry.context_digest==digest(self.context),'native-parent-clone-handoff')
                self.parent_clone.consume()
                parent=ParentOwnedClone(self.config,self.plan,self.expected,request_digest,self.daemon,None,
                    parent_clone=self.parent_clone,run=self.run,clone_connect=self.clone_connect,clock=self.clock,
                    work_deadline=start+1100,cleanup_deadline=start+1200,owner=self.owner)
                parent.verify_held()  # refuse unbound/used resources before source/provider IO
            if self.joint is not None:
                self.joint.preflight(request=request,context=self.context,policy=self.connector.policy,plan=self.plan)
            events.capture_start()
            capture_wall = self.wall_clock()
            value,_ = self.connector.validated_uri()
            frozen = NativeSourceConnector(self.connector.policy,secret=lambda:value,driver=self.connector.driver)
            with NativeWindowArtifacts(self.config.backup_root,request_digest,owner=self.owner) as artifacts, \
                    (self.joint.custody() if self.joint is not None else nullcontext()) as joint_artifacts:
                joint_result = None
                with NativeSourceSnapshot(frozen,self.expected,clock=self.clock,wall_clock=self.wall_clock) as snapshot:
                    system = snapshot.cluster_system_id()
                    captured = readers.collect_source(snapshot)
                    dumper = NativeDump(self.dump_spec,frozen,popen=self.dump_popen,clock=self.clock)
                    dump = dumper.run(snapshot,artifacts)
                    if self.joint is not None:
                        joint_result = self.joint.capture(snapshot=snapshot,dumper=dumper,dump=dump,
                            artifacts=joint_artifacts,deadline=min(snapshot._deadline,start+240),
                            capture_started_at=capture_wall)
                    envelope = dict(schema=COMPANION_SCHEMA,request_digest=request_digest,context_digest=digest(self.context),
                        source_identity=self.expected.identity,baseline_digest=self.expected.baseline_digest,
                        snapshot_sha256=snapshot._state,dump=dump,sample=json.loads(captured._encoded),
                        sample_summary=captured.summary(),code_pins=dict(self.plan.adapter_sources))
                    envelope['native_pins'] = asdict(self.pins)
                    if joint_result is not None:
                        envelope['joint'] = joint_result
                    require(snapshot.snapshot_id() == dump['snapshot_id'],'native-job-snapshot')
                events.source_frontends_closed()
                artifacts.write_companion(readers.raw(envelope))  # source already closed
                pins = artifacts.metadata()
                with artifacts.verified_fd('companion') as fd:
                    sealed_envelope = json.loads(os.read(fd,2097153))
                require(sealed_envelope == envelope and sealed_envelope['request_digest'] == request_digest
                        and pins['artifacts']['dump']['sha256'] == sealed_envelope['dump']['sha256'], 'native-job-companion')
                captured = readers.NativeCatalogSample(**sealed_envelope['sample'])
                if joint_result is not None:
                    require(joint_artifacts.metadata() == joint_result['artifacts'], 'native-job-joint-artifacts')
                events.capture_finish()
                if parent is None:
                    clone = OwnedClone(self.config,self.plan,self.expected,request_digest,self.daemon,system,
                        run=self.run,clone_connect=self.clone_connect,clock=self.clock,
                        work_deadline=start+1100,cleanup_deadline=start+1200,owner=self.owner)
                else:
                    clone=parent;clone.source_system=system
                events.recovery_start()
                with clone:
                    clone.bootstrap(captured)
                    clone.restore(artifacts)
                    restored,before = clone.pair()
                    gate = readers.NativeRecoveryGate(self.plan,self.expected,captured,request_digest)
                    observations = [before]
                    result = gate.run(restored,observe=lambda:observations.pop() if observations else clone.state(),replay=clone.replay)
                    require(artifacts.metadata() == pins,'native-job-artifacts-changed')
                    events.recovery_finish()
                require((clone.cleaned if parent is None else clone.child_finished and not clone.cleaned)
                    and artifacts.metadata() == pins and self.clock()-start <= 1200,'native-job-final')
                if joint_result is not None:
                    require(joint_artifacts.metadata() == joint_result['artifacts'], 'native-job-joint-artifacts')
                # In parent mode this event means local handles/use released,
                # NEVER Docker absence; the result requires parent cleanup.
                events.cleanup_finish()
                events.result()
                public_events = events.public()
                binding = dict(request_digest=request_digest,context_digest=digest(self.context),
                    dump_sha256=pins['artifacts']['dump']['sha256'],companion_sha256=pins['artifacts']['companion']['sha256'],
                    snapshot_sha256=envelope['snapshot_sha256'],sample_summary=captured.summary(),
                    container_id=clone.container,network_id=clone.network,clone_identity=result['clone_rehearsal']['clone_identity'],
                    daemon_id=clone.daemon,image_id=clone.image,clone_system_sha256=digest(clone.system),
                    code_pins_sha256=digest(dict(self.plan.adapter_sources)),
                    effective_source_policy_sha256=self.pins.source_policy_sha256,
                    dump_spec_sha256=self.pins.dump_spec_sha256,
                    events_sha256=events.digest,source_unchanged_proven=False,
                    clone_rehearsal_digest=digest({k:result['clone_rehearsal'][k] for k in CLONE_FIELDS}))
                if joint_result is not None:
                    binding['joint_capture_digest'] = digest(joint_result)
                if parent is not None:
                    binding['parent_registry_digest']=self.parent_clone.registry_digest
                public = dict(schema=JOB_SCHEMA,binding=binding,binding_digest=digest(binding),
                    clone_rehearsal=result['clone_rehearsal'],comparison=result['comparison'],cleanup_verified=parent is None,
                    events=public_events,source_unchanged_proven=False,a8_window_proven=False,operational_ready=False)
                if parent is not None:
                    public['parent_cleanup_required']=True
                if joint_result is not None:
                    public['joint'] = joint_result
                return public
        except Exception:
            raise Refused('native-job-failed') from None
        except BaseException:
            raise KeyboardInterrupt from None
