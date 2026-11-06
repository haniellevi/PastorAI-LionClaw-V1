"""Pinned native source consumers, exercised only under the isolated supervisor.

These transports are implementation, never authority to write to a database.
The operational factory remains blocked until all consumers, the external
supervisor, source fence and receipt evidence are admitted together. No CLI,
credential discovery, connection or filesystem mutation occurs at construction.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import ipaddress
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
from types import ModuleType
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import first_transition_database as db
import first_transition_auth_preflight as authenticated
from first_transition_adapter import APPLICATION_SHA,EXECUTOR_SHA,Plan,digest
from first_transition_candidate import DATABASE_NAMES
from first_transition_orchestrator import MigrationExecutor
from first_transition_window_backup import NativeSourceConnector, NativeSourcePolicy, NativeWindowArtifacts, clone_state
from initial_transition_ops import Refused, require

HEX = re.compile('[0-9a-f]{64}')
CANDIDATE_CA = '/run/igreja12/native-ca.crt'
CANDIDATE_OPTIONS = ('-c default_transaction_read_only=off -c search_path=pg_catalog,public '
                     '-c row_security=on -c statement_timeout=8000')
SOURCE_WRITE_OPTIONS = 'SET default_transaction_read_only = off'
SOURCE_READ_OPTIONS = 'SET default_transaction_read_only = on'
MIGRATION_PATH = 'SET search_path TO "$user",public'
PROBE_PATH = 'SET search_path TO pg_catalog,public'


@dataclass(frozen=True)
class NativeTransportPins:
    context_sha256: str
    source_policy_sha256: str
    plan_digest: str
    source_identity: str


class NativeSourceTransports:
    """One lazy frozen provider and policy shared by native consumers.

Only the main postgres candidate URL is admitted here. Dedicated logins need
their own independently reviewed role/credential contracts; nonempty optional
URLs refuse instead of silently borrowing the main privileged login.
"""
    def __init__(self, *, plan, expected, context, policy, pins, secret, owner=0, driver=None, clock=None):
        require(isinstance(plan,Plan) and isinstance(expected,db.DatabaseExpectation)
            and plan.application_sha == APPLICATION_SHA and plan.executor_sha == EXECUTOR_SHA
            and type(policy) is NativeSourcePolicy and type(pins) is NativeTransportPins and callable(secret)
            and type(context) is dict and type(owner) is int and owner>=0, 'native-transports-config')
        policy.validated();expected.validated()
        require(all(type(v) is str and HEX.fullmatch(v) for v in asdict(pins).values())
            and pins.context_sha256 == digest(context) and pins.source_policy_sha256 == digest(asdict(policy))
            and pins.plan_digest == plan.digest == context['plan_digest']
            and pins.source_identity == expected.identity == context['source_identity']
            and expected.ledger == plan.baseline and context['baseline_digest'] == expected.baseline_digest
            and context['ca_sha256'] == policy.ca_sha256, 'native-transports-binding')
        self.plan,self.expected,self.context,self.policy,self.pins = plan,expected,deepcopy(context),policy,pins
        self.owner,self.clock = owner,clock or time.monotonic
        self._provider,self._value,self._provider_used,self._provider_failed = secret,None,False,False
        self.connector = NativeSourceConnector(policy,secret=self._secret,driver=driver)
        self._candidate_runtime = None

    @property
    def candidate_runtime(self):
        return self._candidate_runtime

    def bind_candidate_runtime(self,runtime):
        from first_transition_native_candidate_runtime import NativeCandidateRuntime
        require(type(runtime) is NativeCandidateRuntime and runtime.transports is self
                and self._candidate_runtime is None,'native-candidate-runtime-binding')
        self._candidate_runtime=runtime

    def validate(self, context):
        require(digest(context) == self.pins.context_sha256 == digest(self.context)
            and digest(asdict(self.connector.policy)) == self.pins.source_policy_sha256
            and self.policy == self.connector.policy
            and digest(asdict(self.policy)) == self.pins.source_policy_sha256
            and self.plan.digest == self.pins.plan_digest and self.expected.identity == self.pins.source_identity,
            'native-transports-binding')
        require(self.expected.baseline_digest == self.context['baseline_digest']
            and self.expected.ledger == self.plan.baseline,'native-transports-binding')

    def _secret(self):
        require(not self._provider_failed,'native-transports-provider')
        if not self._provider_used:
            self._provider_used = True
            try:
                self._value = self._provider()
            except Exception:
                self._provider_failed = True
                raise Refused('native-transports-provider') from None
        return self._value

    def read_connect(self, *, timeout):
        self.validate(self.context)
        require(type(timeout) in (int,float) and math.isfinite(timeout) and 0<timeout<=1200,
            'native-transports-budget')
        deadline = self.clock()+timeout
        conn = self.connector.connect(timeout=min(8,timeout))
        if self.clock() >= deadline:
            conn.close()
            raise Refused('native-transports-budget')
        return conn

    def port_connect(self, *, secret, context, timeout):
        self.validate(context)
        value,_ = self.connector.validated_uri()
        require(callable(secret) and secret() == value,'native-transports-provider')
        return self.read_connect(timeout=timeout)

    def endpoint(self, url):
        """Writer socket inventory uses the actual pinned route, never DNS."""
        self.validate(self.context)
        value,_ = self.connector.validated_uri()
        require(type(url) is str and url == value,'native-writers-provider')
        return frozenset({ipaddress.ip_address(self.policy.hostaddr)}),self.policy.port

    def candidate_parameters(self):
        self.validate(self.context)
        return dict(hostaddr=self.policy.hostaddr,sslmode='verify-full',sslrootcert=CANDIDATE_CA,
            sslcertmode='disable',channel_binding='require',gssencmode='disable',ssl_min_protocol_version='TLSv1.2',
            connect_timeout='5',application_name='igreja12-native-candidate',options=CANDIDATE_OPTIONS)

    def candidate_uri(self):
        self.validate(self.context)
        value,_ = self.connector.validated_uri()
        uri = urlsplit(value)
        return urlunsplit((uri.scheme,uri.netloc,uri.path,urlencode(sorted(self.candidate_parameters().items()),quote_via=quote),''))

    def candidate_environment(self, items, source):
        """Strict secret comparison stays private; only empty optional logins allowed."""
        from psycopg2.extensions import parse_dsn
        try:
            self.validate(self.context)
            value,reference = self.connector.validated_uri()
            require(source == value,'native-candidate-provider')
            urls = {}
            for name,url in items:
                require(type(name) is str and not name.upper().startswith('PG'),'native-candidate-environment')
                if name.upper() in DATABASE_NAMES:
                    require(name == name.upper() and name not in urls and type(url) is str,'native-candidate-environment')
                    urls[name] = url
            require(bool(urls.get('DATABASE_URL')) and not any(urls.get(name) for name in DATABASE_NAMES[1:]),
                'native-candidate-dedicated-unbound')
            uri = urlsplit(urls['DATABASE_URL'])
            query = parse_qsl(uri.query,keep_blank_values=True,strict_parsing=True)
            require(len(query) == len(dict(query)) and dict(query) == self.candidate_parameters()
                and uri.scheme == 'postgresql' and not uri.fragment,'native-candidate-policy')
            parsed = parse_dsn(urls['DATABASE_URL'])
            require(all(parsed.get(k) == reference.get(k) for k in ('host','port','dbname','user','password')),
                'native-candidate-provider')
            require(all(parsed.get(k) == v for k,v in self.candidate_parameters().items()),'native-candidate-policy')
            return len(DATABASE_NAMES)-1
        except Refused:
            raise
        except Exception:
            raise Refused('native-candidate-policy') from None

    def candidate_override(self):
        """Public Compose data only; never materialize credentials or app code."""
        from first_transition_adapter import ROLES
        self.validate(self.context)
        if self._candidate_runtime is not None:
            return self._candidate_runtime.override()
        mount = dict(type='bind',source=self.policy.ca_file,target=CANDIDATE_CA,read_only=True,
            bind=dict(create_host_path=False))
        return (json_bytes(dict(services={role:dict(volumes=[mount]) for role in ROLES}))+b'\n')

    def candidate_mounts(self, rows):
        self.validate(self.context)
        require(type(rows) is list and rows[-1:] == [None],'native-candidate-mounts')
        selected = []
        for row in rows[:-1]:
            require(type(row) is list and len(row)==4 and all(type(v) is str for v in row[:3])
                and type(row[3]) is bool,'native-candidate-mounts')
            target = row[2]
            if target == CANDIDATE_CA or CANDIDATE_CA.startswith(target.rstrip('/')+'/'):
                selected.append(row)
        require(selected == [['bind',self.policy.ca_file,CANDIDATE_CA,False]],'native-candidate-mounts')
        self.connector._ca()  # public CA bytes/path remain independently pinned
        # This is mount intent, not the inode/bytes actually bound into the
        # candidate. Rename/replace on the host can leave an older mounted inode.
        return dict(schema='igreja12.native-candidate-ca-intent/1',mount_intent_verified=True,
            effective_ca_verified=False,ca_sha256=self.policy.ca_sha256)

    def candidate_compose(self, service,role=None):
        require(type(service) is dict and type(service.get('volumes')) is list,'native-candidate-mounts')
        rows=[]
        for volume in service['volumes']:
            require(type(volume) is dict and type(volume.get('target')) is str,'native-candidate-mounts')
            require(type(volume.get('read_only',False)) is bool,'native-candidate-mounts')
            rows.append([volume.get('type'),volume.get('source',''),volume['target'],not volume.get('read_only',False)])
        result=self.candidate_mounts([*rows,None])
        if self._candidate_runtime is not None:
            from first_transition_adapter import ROLES
            require(role in ROLES,'native-candidate-runtime-binding')
            if role=='backend':
                runtime=self._candidate_runtime
                import json
                expected=json.loads(runtime.override())['services']['backend']
                require(service.get('entrypoint')==expected['entrypoint'] and service.get('command')==expected['command']
                    and sorted(rows)==sorted(runtime._mounts()),'native-candidate-runtime-binding')
            else:
                require(not any(row[2].startswith('/run/igreja12/native-runtime') for row in rows),
                    'native-candidate-runtime-binding')
        return result

    def migration_executor(self, *, python, workdir, plan=None):
        require(plan is None or plan == self.plan,'native-transports-binding')
        return NativeMigrationExecutor(self,python=python,workdir=workdir,plan=plan)


def json_bytes(value):
    import json
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


class NativeMigrationExecutor(MigrationExecutor):
    """Exact executor on the same freshly authenticated/probed native handle.

Run only in a dedicated NativeWorkerSupervisor process. Cooperative driver
timeouts alone are insufficient; no production factory currently admits this
in-process transport. First refusal consumes the executor, including failures
after SQL or during close. A new instance never adopts a partially applied run.
"""
    def __init__(self, transports, *, python, workdir, plan=None):
        require(type(transports) is NativeSourceTransports,'native-migration-config')
        require(sys.version_info[:2] == (3,13) and Path(python).resolve() == Path(sys.executable).resolve(),
            'native-migration-runtime')
        require(plan is None or plan == transports.plan,'native-transports-binding')
        super().__init__(plan if plan is not None else transports.plan,python=python,workdir=workdir,secret=transports._secret,
            runner=lambda *_a,**_k:None)
        self.transports,self.next_index,self.stopped = transports,1,False
        self.catalog = transports.expected.catalog
        self.receipts = []

    def _check_state(self, state, ledger):
        require(digest(list(state['identity'])) == self.transports.expected.identity
            and state['ledger'] == tuple(sorted(ledger)) and state['invalid'] == 0,'native-migration-state')

    def _safety(self, conn):
        conn.autocommit = True
        with conn.cursor() as cursor:
            cursor.execute(db.Q_BEGIN)
            try:
                cursor.execute(db.Q_PATH);cursor.fetchall()
                cursor.execute(authenticated.QUERY)
                rows = cursor.fetchall()
                require(len(rows) == 1 and cursor.description is not None
                    and len(rows[0]) == len(cursor.description),'native-migration-authentication')
                safety = dict(zip((column[0] for column in cursor.description),rows[0]))
                authenticated._validate_safety_row(safety,expected_identity=self.transports.expected.identity,now=time.time())
                for query in (db.Q_WRITERS,db.Q_BUILDS):
                    cursor.execute(query)
                    value = cursor.fetchall()
                    require(value == [(0,)] and type(value[0][0]) is int,'native-migration-not-quiet')
            finally:
                cursor.execute('ROLLBACK')

    def apply(self, index, migration):
        admitted = not self.stopped
        self.stopped = True
        require(admitted and type(index) is int and index == self.next_index
            and 1<=index<=len(self.plan.pending) and migration is self.plan.pending[index-1], 'native-migration-order')
        conn = None
        try:
            self.transports.validate(self.transports.context)
            fd = NativeWindowArtifacts._directory(self.workdir)
            try:
                info = os.fstat(fd)
                require(info.st_uid == self.transports.owner and stat.S_IMODE(info.st_mode) == 0o700,
                    'native-migration-workdir')
            finally:
                os.close(fd)
            directory = self._materialize(index,migration)
            namespace = ModuleType('igreja12_native_source_migrate')
            namespace.__file__ = str(Path(directory)/'scripts'/'migrate.py')
            namespace.__dict__['print'] = lambda *_a,**_k:None
            exec(compile(self.plan.executor,'<pinned-native-source-migrate>','exec'),namespace.__dict__)
            namespace.MIGRATIONS_DIR = Path(directory)/'migrations'
            conn = self.transports.read_connect(timeout=8)
            self._safety(conn)
            before = clone_state(conn)
            ledger = [*self.plan.baseline,*(m.name for m in self.plan.pending[:index-1])]
            self._check_state(before,ledger)
            require(before['catalog'] == self.catalog and conn.info.transaction_status == 0,'native-migration-state')
            conn.autocommit = True
            with conn.cursor() as cursor:
                cursor.execute(SOURCE_WRITE_OPTIONS)
                cursor.execute(MIGRATION_PATH)
            conn.autocommit = False
            code = namespace.cmd_apply(conn,migration.name,transactional=not migration.concurrent,
                lock_timeout=0 if migration.concurrent else 2000)
            require(code == 0 and conn.info.transaction_status == 0,'native-migration-exit')
            conn.autocommit = True
            with conn.cursor() as cursor:
                cursor.execute(SOURCE_READ_OPTIONS)
                cursor.execute(PROBE_PATH)
            after = clone_state(conn)
            self._check_state(after,[*ledger,migration.name])
            self.catalog = after['catalog']
            conn.close()
            require(conn.closed,'native-migration-close')
            conn = None
            self.receipts.append(dict(index=index,migration_sha256=migration.sha256,
                before_catalog=before['catalog'],after_catalog=after['catalog'],
                source_identity=self.transports.expected.identity,ledger_digest=digest(list(after['ledger']))))
            self.next_index += 1
            self.stopped = False
            return 0
        except Exception:
            raise Refused('native-migration-failed') from None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    raise Refused('native-migration-close') from None
