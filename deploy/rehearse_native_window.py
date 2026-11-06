"""Explicit local physical rehearsal, new synthetic PGDATA only; never A8.

Only cached images by digest, own internal source network and no published port.
Synthetic TLS keys/password never leave the private workspace/container. The
production connector/profile and strict comparator are used without substitution.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time
from types import ModuleType

import first_transition_database as db
from first_transition_adapter import digest, prepare
from first_transition_native_job import NativeDumpSpec, NativeJobPins, NativeWindowJob, OwnedClone, OWNER_LABEL, _sealed
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA
from first_transition_window_backup import NativeSourceConnector, NativeSourcePolicy, NativeWorkerSupervisor, WindowBackupConfig
from first_transition_native_transports import CANDIDATE_CA,NativeSourceTransports,NativeTransportPins
from initial_transition_ops import Refused, require


SOURCE_IMAGE = 'public.ecr.aws/supabase/postgres@sha256:658d1c9b09ae4f61b8e95087b6859181b4b7d6940d769cf7b605609c8aad43e9'
CLONE_IMAGE = 'postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3'
HOST = 'native-source.example.test'
LABEL = 'igreja12.synthetic-native'
CLIENT_LABEL = 'igreja12.synthetic-native-client'
CLIENT_IMAGE = 'sha256:b795374e8d4d6bec2c7df034d94eb57afd0c345d9aaa2a19f9232bbbdef9501c'
CLIENT_WAIT = 'import time; time.sleep(180)'
ENV = dict(PATH='/usr/bin:/bin', LC_ALL='C', PYTHON_DOTENV_DISABLED='1')
CLIENT_PROBE = r'''
import fcntl,hashlib,json,os,stat,sys,time
from urllib.parse import parse_qsl,quote,urlencode,urlsplit,urlunsplit
import psycopg2
from psycopg2.extensions import make_dsn,parse_dsn
expected=json.loads(os.environ['SYNTHETIC_CLIENT_EXPECTED'])
url=os.environ['DATABASE_URL'];parsed=parse_dsn(url)
assert all(parsed.get(k)==v for k,v in expected['parameters'].items())
fd=os.open(parsed['sslrootcert'],os.O_RDONLY|os.O_NOFOLLOW)
try:
 s=os.fstat(fd);assert stat.S_ISREG(s.st_mode) and s.st_size<=65536
 ca=os.read(fd,65537);assert hashlib.sha256(ca).hexdigest()==expected['ca_sha256']
finally:os.close(fd)
sealed=os.memfd_create('synthetic-client-ca',os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING)
os.write(sealed,ca);fcntl.fcntl(sealed,1033,15);assert fcntl.fcntl(sealed,1034)&15==15
uri=urlsplit(url);query=dict(parse_qsl(uri.query));query['sslrootcert']='/proc/self/fd/'+str(sealed)
os.environ['DATABASE_URL']=urlunsplit((uri.scheme,uri.netloc,uri.path,urlencode(query,quote_via=quote),''))
native_connect=psycopg2.connect
def checked_connect(*args,**kwargs):
 assert len(args)<=1
 actual=parse_dsn(make_dsn(args[0] if args else None,**kwargs))
 assert all(actual.get(k)==parsed.get(k) for k in ('host','port','dbname','user','password'))
 assert all(actual.get(k)==v for k,v in query.items())
 return native_connect(*args,**kwargs)
psycopg2.connect=checked_connect
sys.path.insert(0,'/app')  # exact COPY/WORKDIR of the pinned application image
from app.db.session import get_engine
engine=get_engine();deadline=time.monotonic()+10
while True:
 try:connection=engine.connect();break
 except Exception:
  if time.monotonic()>=deadline:raise
  time.sleep(.1)
try:
 raw=connection.connection.driver_connection;info=raw.info
 assert info.used_password is True and info.ssl_in_use is True and info.server_version==170006
 assert info.ssl_attribute('protocol') in ('TLSv1.2','TLSv1.3')
 assert all(info.dsn_parameters.get(k)==v for k,v in query.items())
 with raw.cursor() as cur:
  cur.execute("SELECT s.system_identifier::text,d.oid::bigint,d.datname FROM pg_catalog.pg_control_system() s,pg_catalog.pg_database d WHERE d.datname=pg_catalog.current_database()")
  identity=list(cur.fetchone())
  digest=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  assert digest==expected['source_identity']
  cur.execute("SELECT current_user,session_user,pg_catalog.current_setting('default_transaction_read_only'),pg_catalog.current_setting('row_security')")
  assert cur.fetchone()==('postgres','postgres','off','on')
  cur.execute('SELECT count(*) FROM public.schema_migrations');ledger=cur.fetchone()[0];assert ledger==129
 print(json.dumps(dict(schema='igreja12.synthetic-candidate-client/1',application_engine_used=True,
  application_started=False,full_candidate_admission=False,source_identity=digest,ledger=ledger,
  driver=psycopg2.__version__,libpq=psycopg2.__libpq_version__,tls_protocol=info.ssl_attribute('protocol'),
  ca_sha256=expected['ca_sha256'],ca_custody='sealed-private-fd-for-probe',password_authentication=True)))
finally:
 connection.close();engine.dispose();os.close(sealed)
'''
START = r'''
set -eu
install -d -o postgres -g postgres -m 700 "$PGDATA"
printf '%s' "$POSTGRES_PASSWORD" > /tmp/synthetic-password
chmod 644 /tmp/synthetic-password
gosu postgres initdb -D "$PGDATA" --no-locale -E UTF8 --username=postgres --auth-local=trust --auth-host=scram-sha-256 --pwfile=/tmp/synthetic-password >/dev/null
rm /tmp/synthetic-password
printf 'hostssl postgres postgres %s/32 scram-sha-256\n' "$SYNTHETIC_GATEWAY" >> "$PGDATA/pg_hba.conf"
cp /synthetic-tls/server.crt "$PGDATA/server.crt"
cp /synthetic-tls/server.key "$PGDATA/server.key"
chown postgres:postgres "$PGDATA/server.crt" "$PGDATA/server.key"
chmod 600 "$PGDATA/server.key"
cat >> "$PGDATA/postgresql.conf" <<'CONFIG'
listen_addresses = '*'
ssl = on
ssl_cert_file = 'server.crt'
ssl_key_file = 'server.key'
log_statement = 'ddl'
session_preload_libraries = 'supautils'
CONFIG
exec gosu postgres postgres -D "$PGDATA"
'''


class SyntheticSource:
    """Cleanup needs returned IDs AND fresh matching labels; never adopt by name."""
    def __init__(self, root):
        self.root = root
        self.nonce = secrets.token_hex(16)
        self.name = 'igreja12-native-source-' + self.nonce
        self.network = self.container = self.address = self.daemon = None
        self.ambiguous = False
        self.password = secrets.token_hex(24)
        (root/'docker').mkdir(mode=0o700)
        self.argv = ('/usr/bin/docker', '--config', str(root/'docker'), '--host', 'unix:///var/run/docker.sock')

    def call(self, *args, env=None, timeout=20):
        result = subprocess.run((*self.argv,*args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env={**ENV,**(env or {})}, timeout=timeout, check=False)
        require(result.returncode == 0 and len(result.stdout) <= 65536, 'physical-docker-command')
        return result.stdout.decode().strip()

    def owned(self):
        require(json.loads(self.call('info','--format','{{json .ID}}')) == self.daemon, 'physical-daemon')
        if self.network:
            row = json.loads(self.call('network','inspect','--format',
                '[{{json .Id}},{{json .Internal}},{{json (index .Labels "'+LABEL+'")}}]',self.network))
            require(row == [self.network,True,self.nonce], 'physical-network-owner')
        if self.container:
            row = json.loads(self.call('inspect','--format',
                '[{{json .Id}},{{json (index .Config.Labels "'+LABEL+'")}},{{json .HostConfig.PortBindings}}]',self.container))
            require(row[:2] == [self.container,self.nonce] and row[2] in (None,{}), 'physical-source-owner')

    def start(self):
        self.daemon = json.loads(self.call('info','--format','{{json .ID}}'))
        for image in (SOURCE_IMAGE,CLONE_IMAGE):
            row = json.loads(self.call('image','inspect','--format','[{{json .Id}},{{json .RepoDigests}}]',image))
            require(re.fullmatch('sha256:[0-9a-f]{64}',row[0]) and image in row[1], 'physical-image')
        require(self.call('ps','-a','--filter','name=^/'+self.name+'$','--format','{{.ID}}') == ''
            and self.call('network','ls','--filter','name=^'+self.name+'$','--format','{{.ID}}') == '', 'physical-preexisting')
        self.ambiguous = True
        self.network = self.call('network','create','--internal','--label',LABEL+'='+self.nonce,self.name)
        require(re.fullmatch('[0-9a-f]{64}',self.network), 'physical-network-owner')
        self.owned();self.ambiguous = False
        gateway = self.call('network','inspect','--format','{{(index .IPAM.Config 0).Gateway}}',self.network)
        import ipaddress
        require(ipaddress.ip_address(gateway).is_private, 'physical-source-route')
        self.ambiguous = True
        self.container = self.call('run','-d','--pull=never','--name',self.name,'--network',self.network,
            '--restart=no','--label',LABEL+'='+self.nonce,
            '--tmpfs','/var/lib/postgresql/data:rw,nosuid,nodev,noexec,size=536870912',
            '--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=33554432',
            '--mount','type=bind,src='+str(self.root/'tls')+',dst=/synthetic-tls,readonly',
            '-e','PGDATA=/var/lib/postgresql/data','-e','POSTGRES_PASSWORD','-e','SYNTHETIC_GATEWAY',
            '--entrypoint','sh',SOURCE_IMAGE,'-c',START,
            env={'POSTGRES_PASSWORD':self.password,'SYNTHETIC_GATEWAY':gateway})
        require(re.fullmatch('[0-9a-f]{64}',self.container), 'physical-source-owner')
        self.owned();self.ambiguous = False
        metadata = self.call('inspect','--format',
            '[{{json .Mounts}},{{json .HostConfig.Tmpfs}},{{json .NetworkSettings.Networks}},'
            '{{json .Config.Entrypoint}},{{json .Config.Cmd}}]',self.container)
        path = self.root/'source-isolation-metadata.json'
        path.write_text(metadata);path.chmod(0o600)
        self.address = self.call('inspect','--format','{{(index .NetworkSettings.Networks "'+self.name+'").IPAddress}}',self.container)
        require(ipaddress.ip_address(self.address).is_private, 'physical-source-route')
        return self

    def connect(self):
        import psycopg2
        self.owned()
        deadline = time.monotonic()+45
        while True:
            try:
                connection = psycopg2.connect(host=HOST,hostaddr=self.address,port=5432,dbname='postgres',user='postgres',
                    password=self.password,sslmode='verify-full',sslrootcert=str(self.root/'tls'/'server.crt'),
                    sslcertmode='disable',gssencmode='disable',channel_binding='require',connect_timeout=2,
                    options='-c search_path=public,pg_catalog -c statement_timeout=30000')
                require(connection.info.used_password and connection.info.ssl_in_use
                    and connection.info.server_version == 170006, 'physical-source-profile')
                return connection
            except psycopg2.OperationalError:
                require(time.monotonic()<deadline,'physical-source-ready')
                time.sleep(.2)
                self.owned()

    def close(self):
        require(not self.ambiguous,'physical-cleanup-ambiguous')
        if self.network is None:
            return
        self.owned()
        if self.container:
            self.call('rm','-f','-v',self.container)
        self.call('network','rm',self.network)
        require((self.container is None or not self.call('ps','-a','--filter','id='+self.container,'--format','{{.ID}}'))
            and not self.call('network','ls','--filter','id='+self.network,'--format','{{.ID}}'), 'physical-cleanup')

    def descriptor(self):
        self.owned()
        return dict(root=str(self.root),nonce=self.nonce,network=self.network,container=self.container,
            daemon=self.daemon,name=self.name,address=self.address,
            started=json.loads(self.call('inspect','--format','{{json .State.StartedAt}}',self.container)))

    def job_resources(self, request_digest):
        result = {}
        for kind,command in [('containers',('ps','-a','--no-trunc')),('networks',('network','ls','--no-trunc'))]:
            ids = self.call(*command,'--filter','label='+OWNER_LABEL+'='+request_digest,'--format','{{.ID}}').splitlines()
            require(len(ids)<=32 and all(re.fullmatch('[0-9a-f]{64}',value) for value in ids),'physical-job-resources')
            result[kind] = ids
        return result

    def client_resources(self, request_digest):
        values=self.call('ps','-a','--no-trunc','--filter','label='+CLIENT_LABEL+'='+request_digest,'--format','{{.ID}}').splitlines()
        require(len(values)<=1 and all(re.fullmatch('[0-9a-f]{64}',v) for v in values),'physical-client-resources')
        return values

    def cleanup_client(self, request_digest):
        values=self.client_resources(request_digest)
        if values:
            NativeClient(self.descriptor(),request_digest).remove(values[0])
        require(self.client_resources(request_digest)==[],'physical-client-cleanup')

    def cleanup_job(self, request_digest, config, plan, expected):
        ids = self.job_resources(request_digest)
        if not ids['containers'] and not ids['networks']:
            return
        require(len(ids['networks']) == 1 and len(ids['containers']) <= 1,'physical-job-cleanup-pending')
        network = ids['networks'][0]
        row = json.loads(self.call('network','inspect','--format',
            '[{{json .Name}},{{json (index .Labels "igreja12.native-token")}}]',network))
        require(type(row) is list and len(row) == 2 and type(row[1]) is str
            and re.fullmatch('[0-9a-f]{32}',row[1]) and row[0] == 'igreja12-native-'+request_digest[:12]+'-'+row[1][:12],
            'physical-job-owner')
        clone = OwnedClone(config,plan,expected,request_digest,self.daemon,'synthetic-parent-cleanup',
            work_deadline=time.monotonic()+40,cleanup_deadline=time.monotonic()+40,owner=os.geteuid())
        clone.network,clone.container = network,ids['containers'][0] if ids['containers'] else None
        clone.name,clone.token = row
        clone.image = json.loads(self.call('image','inspect','--format','{{json .Id}}',CLONE_IMAGE))
        clone.close()  # reuse full fresh ID/label/daemon ownership checks
        require(self.job_resources(request_digest) == dict(containers=[],networks=[]),'physical-job-cleanup-pending')


def verify_worker_source(data):
    """A sealed payload alone must never turn this rehearsal into a remote client."""
    d = data['source_descriptor']
    root = Path(d['root'])
    require(root.is_absolute() and type(d['nonce']) is str and re.fullmatch('[0-9a-f]{32}',d['nonce'])
        and all(re.fullmatch('[0-9a-f]{64}',d[k]) for k in ('network','container'))
        and d['name'] == 'igreja12-native-source-'+d['nonce'], 'physical-worker-source')
    cfg = data['config']
    require(cfg['docker_binary'] == '/usr/bin/docker' and cfg['docker_endpoint'] == 'unix:///var/run/docker.sock'
        and cfg['docker_config_dir'] == str(root/'docker') and cfg['backup_root'] == str(root/'artifacts')
        and cfg['clone_workdir'] == str(root/'replay') and cfg['clone_image'] == cfg['dump_image'] == CLONE_IMAGE,
        'physical-worker-config')
    prefix = ('/usr/bin/docker','--config',str(root/'docker'),'--host','unix:///var/run/docker.sock')
    def read(*args):
        result = subprocess.run((*prefix,*args),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,env=ENV,check=False,timeout=10)
        require(result.returncode == 0 and len(result.stdout)<=65536,'physical-worker-source')
        return json.loads(result.stdout)
    require(read('info','--format','{{json .ID}}') == d['daemon'] == data['daemon'],'physical-worker-source')
    network = read('network','inspect','--format',
        '[{{json .Id}},{{json .Name}},{{json .Internal}},{{json .Driver}},{{json .Labels}},{{json .Containers}}]',d['network'])
    require(network[:4] == [d['network'],d['name'],True,'bridge'] and network[2] is True
        and network[4].get(LABEL) == d['nonce'] and set(network[5]) == {d['container']},'physical-worker-network')
    row = read('inspect','--format',
        '[{{json .Id}},{{json .Config.Image}},{{json .Config.Entrypoint}},{{json .Config.Cmd}},'
        '{{json .Config.Labels}},{{json .State.Running}},{{json .State.StartedAt}},{{json .HostConfig.PortBindings}},'
        '{{json .NetworkSettings.Networks}},{{json .Mounts}},{{json .HostConfig.Privileged}},{{json .HostConfig.Tmpfs}}]',d['container'])
    require(row[:4] == [d['container'],SOURCE_IMAGE,['sh'],['-c',START]] and row[4].get(LABEL) == d['nonce']
        and row[5] is True and row[6] == d['started'] and row[7] in (None,{}) and row[10] is False
        and set(row[8]) == {d['name']} and row[8][d['name']]['NetworkID'] == d['network']
        and row[8][d['name']]['IPAddress'] == d['address'],'physical-worker-container')
    mounts = {m['Destination']:m for m in row[9]}
    tmpfs = {'/tmp':'rw,nosuid,nodev,noexec,size=33554432',
             '/var/lib/postgresql/data':'rw,nosuid,nodev,noexec,size=536870912'}
    require(row[11] == tmpfs and len(row[9]) == len(mounts)
        and '/synthetic-tls' in mounts and set(mounts) <= {*tmpfs,'/synthetic-tls'}
        and all(mounts[p]['Type'] == 'tmpfs' for p in tmpfs if p in mounts)
        and mounts['/synthetic-tls']['Type'] == 'bind' and mounts['/synthetic-tls']['Source'] == str(root/'tls')
        and mounts['/synthetic-tls']['RW'] is False,'physical-worker-mounts')
    require(data['policy']['host'] == HOST and data['policy']['hostaddr'] == d['address']
        and data['policy']['port'] == 5432 and data['policy']['ca_file'] == str(root/'tls'/'server.crt')
        and data['policy']['ca_owner'] == os.geteuid(),'physical-worker-policy')


class NativeClient:
    """A Python client from the cached application image; never start the app."""
    def __init__(self, descriptor, request_digest):
        self.source,self.request=descriptor,request_digest
        self.name='igreja12-native-client-'+request_digest[:12]+'-'+descriptor['nonce'][:12]
        self.cid=None
        self.argv=('/usr/bin/docker','--config',descriptor['root']+'/docker','--host','unix:///var/run/docker.sock')

    def call(self,*args,env=None,timeout=20):
        result=subprocess.run((*self.argv,*args),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,env={**ENV,**(env or {})},timeout=timeout,check=False)
        require(result.returncode==0 and len(result.stdout)<=65536,'physical-client-command')
        return result.stdout.decode().strip()

    def owned(self,cid,*,isolation=True):
        require(json.loads(self.call('info','--format','{{json .ID}}'))==self.source['daemon'],'physical-client-daemon')
        row=json.loads(self.call('inspect','--format',
            '[{{json .Id}},{{json .Config.Image}},{{json .Config.Labels}},{{json .HostConfig.NetworkMode}},'
            '{{json .HostConfig.PortBindings}},{{json .Mounts}},{{json .Config.Entrypoint}},{{json .Config.Cmd}},'
            '{{json .NetworkSettings.Networks}}]',cid))
        require(row[0:2]==[cid,CLIENT_IMAGE] and row[2].get(CLIENT_LABEL)==self.request
            and row[2].get(LABEL)==self.source['nonce'] and row[3]==self.source['network']
            and row[6:8]==[['python'],['-I','-c',CLIENT_WAIT]],'physical-client-owner')
        if isolation:
            mounts=row[5]
            require(row[4] in (None,{}) and len(mounts)==1 and mounts[0]['Type']=='bind'
                and mounts[0]['Source']==self.source['root']+'/tls/server.crt'
                and mounts[0]['Destination']==CANDIDATE_CA and mounts[0]['RW'] is False
                and set(row[8])=={self.source['name']}
                and row[8][self.source['name']]['NetworkID']==self.source['network'],'physical-client-isolation')
        return row

    def remove(self,cid):
        self.owned(cid,isolation=False)
        self.call('rm','-f','-v',cid)
        require(self.call('ps','-a','--no-trunc','--filter','id='+cid,'--format','{{.ID}}')=='','physical-client-cleanup')

    def run(self, consumers):
        require(self.call('ps','-a','--no-trunc','--filter','label='+CLIENT_LABEL+'='+self.request,'--format','{{.ID}}')=='',
            'physical-client-preexisting')
        candidate=consumers.candidate_uri()
        consumers.candidate_environment([('DATABASE_URL',candidate)],consumers.connector.validated_uri()[0])
        self.cid=self.call('run','-d','--pull=never','--name',self.name,'--network',self.source['network'],'--restart=no',
            '--label',CLIENT_LABEL+'='+self.request,'--label',LABEL+'='+self.source['nonce'],
            '--mount','type=bind,src='+self.source['root']+'/tls/server.crt,dst='+CANDIDATE_CA+',readonly',
            '-e','DATABASE_URL','-e','PYTHON_DOTENV_DISABLED=1','-e','ALLOW_REAL_SENDS=false',
            '-e','ASAAS_BILLING_ENABLED=false','-e','BREVO_SEND_MODE=off','-e','BROADCAST_ASYNC_ENABLED=false',
            '--entrypoint','python',CLIENT_IMAGE,'-I','-c',CLIENT_WAIT,env={'DATABASE_URL':candidate})
        require(re.fullmatch('[0-9a-f]{64}',self.cid),'physical-client-owner')
        marker=Path(self.source['root'])/'candidate-client-ownership.json'
        marker.write_text(json.dumps(dict(container=self.cid,request_digest=self.request)));marker.chmod(0o600)
        try:
            row=self.owned(self.cid)
            from first_transition_candidate import NATIVE_DATABASE_TEMPLATE
            private=json.loads(self.call('inspect','--format',NATIVE_DATABASE_TEMPLATE,self.cid))
            require(private[0]==self.cid and private[1][-1:] == [None],'physical-client-environment')
            consumers.candidate_environment((entry.split('=',1) for entry in private[1][:-1]),
                consumers.connector.validated_uri()[0])
            peer=row[8][self.source['name']]['IPAddress']
            import ipaddress
            require(ipaddress.ip_address(peer).is_private,'physical-client-peer')
            # Only this new peer is added to the own synthetic HBA. The client
            # has not logged in: its sole initial process sleeps until exec.
            self.call('exec','-e','SYNTHETIC_ALLOWED_PEER',self.source['container'],'sh','-c',
                'printf "hostssl postgres postgres %s/32 scram-sha-256\\n" "$SYNTHETIC_ALLOWED_PEER" >> "$PGDATA/pg_hba.conf"; '
                'exec gosu postgres pg_ctl reload -D "$PGDATA"',env={'SYNTHETIC_ALLOWED_PEER':peer})
            expected=dict(parameters=consumers.candidate_parameters(),source_identity=consumers.expected.identity,
                ca_sha256=consumers.policy.ca_sha256)
            output=self.call('exec','-e','SYNTHETIC_CLIENT_EXPECTED',self.cid,'python','-I','-c',CLIENT_PROBE,
                env={'SYNTHETIC_CLIENT_EXPECTED':json.dumps(expected)},timeout=30)
            result=json.loads(output)
            require(result.get('source_identity')==consumers.expected.identity and result.get('ledger')==129
                and result.get('full_candidate_admission') is False,'physical-client-probe')
            return result
        finally:
            self.remove(self.cid)


def seed(source, plan, root, *, recreate_public=False):
    namespace = ModuleType('synthetic_pinned_migrate')
    namespace.__file__ = str(root/'scripts'/'migrate.py')
    namespace.__dict__['print'] = lambda *_a,**_k: None
    exec(compile(plan.executor,'<synthetic-pinned-executor>','exec'),namespace.__dict__)
    migrations = root/'seed-migrations';migrations.mkdir(mode=0o700)
    namespace.MIGRATIONS_DIR = migrations
    for migration in plan.migrations:
        (migrations/migration.name).write_bytes(migration.sql)
    conn = source.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT (SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'),"
                "(SELECT count(*) FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public')")
            require(cur.fetchone() == (0,0),'physical-source-not-empty')
            if recreate_public:
                # Explicit negative fixture: removes initdb's public-schema
                # initial privileges, which ordinary pg_restore may not retain.
                # The strict comparator must refuse; never repair the catalog.
                cur.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public')
            for role in ('anon','authenticated','service_role'):
                cur.execute('CREATE ROLE '+role+' NOLOGIN NOINHERIT'+(' BYPASSRLS' if role == 'service_role' else ''))
            for kind in ('TABLES','SEQUENCES','FUNCTIONS'):
                cur.execute('ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON '+kind+' TO anon,authenticated,service_role')
            cur.execute('CREATE TABLE public.schema_migrations(name text PRIMARY KEY)')
        conn.commit()
    finally:
        conn.close()
    for name in plan.baseline:
        migration = next(m for m in plan.migrations if m.name == name)
        conn = source.connect()
        try:
            require(namespace.cmd_apply(conn,name,transactional=not migration.concurrent,
                lock_timeout=0 if migration.concurrent else 5000) == 0,'physical-baseline-migration')
        finally:
            conn.close()
    conn = source.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO igrejas(id,nome) VALUES ('dddddddd-0000-4000-8000-000000000001','Synthetic native restore fixture')")
            cur.execute("CREATE TABLE public.native_restore_fixture(id integer PRIMARY KEY,payload text NOT NULL)")
            cur.execute("INSERT INTO public.native_restore_fixture VALUES (1,'Synthetic payload only')")
        conn.commit()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(db.Q_BEGIN)
            cur.execute(db.Q_PATH);cur.fetchall()
            cur.execute(db.Q_IDENTITY);identity = digest(list(cur.fetchone()))
            catalog = db._catalog(cur)
            cur.execute(db.Q_LEDGER);ledger = tuple(r[0] for r in cur.fetchall())
            cur.execute('ROLLBACK')
        return db.DatabaseExpectation(identity,ledger,catalog).validated()
    finally:
        conn.close()


def worker():
    """Private input is accepted only through the supervisor's sealed FD."""
    import fcntl
    from first_transition_window_backup import MEMFD_GET_SEALS, MEMFD_SEALS
    fd = int(os.environ['IGREJA12_NATIVE_INPUT_FD'])
    require(fcntl.fcntl(fd,MEMFD_GET_SEALS)&MEMFD_SEALS == MEMFD_SEALS,'physical-worker-input')
    data = json.loads(os.pread(fd,2097153,0))
    verify_worker_source(data)  # strictly before constructing any source login
    config = WindowBackupConfig.from_dict(data['config'])
    expected = db.DatabaseExpectation(data['expected']['identity'],tuple(data['expected']['ledger']),data['expected']['catalog'])
    policy = NativeSourcePolicy(**data['policy'])
    connector = NativeSourceConnector(policy,secret=lambda:data['source_uri'])
    plan = prepare(Path(__file__).resolve().parents[1])
    require(plan.digest == data['context']['plan_digest'],'physical-worker-plan')
    codes = []
    comparison = []
    def trace(frame,event,arg):
        if event == 'return' and frame.f_code is OwnedClone.pair.__code__ and arg is not None:
            path = Path(data['source_descriptor']['root'])/'restored-synthetic-sample.json'
            with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as handle:
                handle.write(arg[0]._encoded)
        if data.get('kill_after_clone') is True and event == 'return' and frame.f_code is OwnedClone.__enter__.__code__ and arg is not None:
            marker = dict(container=arg.container,network=arg.network,request_digest=digest(data['request']),fault='SIGKILL-after-owned-clone')
            marker_fd = os.open(Path(data['source_descriptor']['root'])/'worker-kill-marker.json',
                os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(marker_fd,'w') as handle:json.dump(marker,handle)
            os.kill(os.getpid(),signal.SIGKILL)
        if event == 'exception' and isinstance(arg[1],Refused):
            code = str(arg[1])
            if re.fullmatch('[a-z][a-z0-9-]{0,100}',code) and code not in codes:
                codes.append(code)
            if code == 'window-origin-recovery-mismatch' and frame.f_code.co_name == 'require_recovery_match':
                comparison.append(frame.f_locals['result'])
        return trace
    sys.settrace(trace)
    try:
        result = NativeWindowJob(config,plan,expected,data['context'],connector,NativeDumpSpec(**data['spec']),
            data['daemon'],NativeJobPins(**data['pins']),owner=os.geteuid()).execute(data['request'])
        if data.get('exercise_transports') is True:
            verify_worker_source(data)
            pins=NativeTransportPins(digest(data['context']),digest(asdict(policy)),plan.digest,expected.identity)
            consumers=NativeSourceTransports(plan=plan,expected=expected,context=data['context'],policy=policy,
                pins=pins,secret=lambda:data['source_uri'],owner=os.geteuid())
            addresses,port=consumers.endpoint(data['source_uri'])
            probe=consumers.read_connect(timeout=10)
            try:
                with probe.cursor() as cur:
                    cur.execute('SHOW default_transaction_read_only')
                    require(cur.fetchone()==('on',),'physical-native-reader')
            finally:
                probe.rollback()
                probe.close()
            executor=consumers.migration_executor(python=sys.executable,
                workdir=str(Path(data['source_descriptor']['root'])/'source-executor'))
            for index,migration in enumerate(plan.pending,1):
                require(executor.apply(index,migration)==0,'physical-native-migration')
            require(executor.catalog==result['clone_rehearsal']['final_schema_digest'],'physical-source-clone-final')
            client=NativeClient(data['source_descriptor'],digest(data['request'])).run(consumers)
            result['isolated_source_execution']=dict(applied=len(executor.receipts),receipts=executor.receipts,
                final_catalog=executor.catalog,writer_endpoint=dict(addresses=sorted(str(a) for a in addresses),port=port),
                writer_dns_used=False,candidate_client=client,source_unchanged_proven=False,operational_ready=False)
        output = dict(passed=True,result=result)
    except Exception as exc:
        output = dict(passed=False,reason=str(exc) if isinstance(exc,Refused) else type(exc).__name__,refusal_codes=codes,
            comparison=comparison[-1] if comparison else None)
    finally:
        sys.settrace(None)
    print(json.dumps(output,sort_keys=True))
    return 0


def main(argv=None):
    if argv == ['--worker']:
        try:
            return worker()
        except Exception as exc:
            # Keep pre-job refusal diagnosable even though the supervisor
            # deliberately discards worker stderr. Never include driver text.
            reason = str(exc) if isinstance(exc,Refused) else type(exc).__name__
            print(json.dumps(dict(passed=False,phase='worker-preflight',reason=reason)))
            return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,help='new absolute private output directory, no existing data')
    parser.add_argument('--pg-dump',required=True,help='explicit already installed PostgreSQL17 ELF')
    parser.add_argument('--kill-after-clone',action='store_true',help='negative cleanup test: SIGKILL only the own worker after its clone starts')
    parser.add_argument('--probe-only',action='store_true',help='verify only the new synthetic source isolation, then clean it')
    parser.add_argument('--recreate-public',action='store_true',help='negative restore fixture with public ACL NULL and no initial privilege')
    parser.add_argument('--exercise-transports',action='store_true',help='after clone proof, migrate only this new synthetic source and probe the cached app client')
    args = parser.parse_args(argv)
    db.require_explicit_environment()
    root = Path(args.root)
    require(root.is_absolute() and '..' not in root.parts,'physical-root')
    root.mkdir(mode=0o700)
    for name in ('tls','artifacts','replay','source-executor'):
        (root/name).mkdir(mode=0o700)
    report = dict(schema='igreja12.synthetic-native-rehearsal/1',phase='tls',passed=False,
        production_contacted=False,a8_window_proven=False,operational_ready=False,cleanup_verified=False)
    if args.kill_after_clone:
        report['injected_fault'] = 'SIGKILL-after-owned-clone'
    report['source_fixture'] = 'recreated-public-null-acl' if args.recreate_public else 'fresh-initdb-public'
    source = SyntheticSource(root)
    request_digest = config = plan = expected = supervisor = None
    started = time.monotonic()
    try:
        subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
            '-subj','/CN='+HOST,'-addext','subjectAltName=DNS:'+HOST,
            '-keyout',str(root/'tls'/'server.key'),'-out',str(root/'tls'/'server.crt')],
            env=ENV,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=15)
        for p in (root/'tls').iterdir():p.chmod(0o600)
        (root/'tls'/'server.crt').chmod(0o644)  # public CA, readable in the private read-only bind
        report['phase'] = 'source-start';source.start()
        if args.probe_only:
            report['phase'] = 'source-isolation-probe'
            descriptor = source.descriptor()
            verify_worker_source(dict(source_descriptor=descriptor,daemon=source.daemon,
                config=dict(docker_binary='/usr/bin/docker',docker_endpoint='unix:///var/run/docker.sock',
                    docker_config_dir=str(root/'docker'),backup_root=str(root/'artifacts'),clone_workdir=str(root/'replay'),
                    clone_image=CLONE_IMAGE,dump_image=CLONE_IMAGE),
                policy=dict(host=HOST,hostaddr=source.address,port=5432,ca_file=str(root/'tls'/'server.crt'),ca_owner=os.geteuid())))
            report.update(passed=True,phase='source-probe-completed',scope='source-provenance-only')
            return 0
        plan = prepare(Path(__file__).resolve().parents[1])
        report['phase'] = 'baseline-seed';expected = seed(source,plan,root,recreate_public=args.recreate_public)
        ca = root/'tls'/'server.crt'
        policy = NativeSourcePolicy(HOST,source.address,5432,str(ca),hashlib.sha256(ca.read_bytes()).hexdigest(),os.geteuid())
        connector = NativeSourceConnector(policy,secret=lambda:'postgresql://postgres:'+source.password+'@'+HOST+':5432/postgres')
        binary = Path(args.pg_dump)
        spec = NativeDumpSpec(str(binary),hashlib.sha256(binary.read_bytes()).hexdigest(),binary.stat().st_uid)
        config = WindowBackupConfig('/usr/bin/docker','unix:///var/run/docker.sock',str(root/'docker'),
            str(root/'artifacts'),str(root/'replay'),sys.executable,CLONE_IMAGE,CLONE_IMAGE)
        context = dict(plan_digest=plan.digest,source_identity=expected.identity,baseline_digest=expected.baseline_digest,
            backup_config_digest=digest(asdict(config)),ca_sha256=policy.ca_sha256,config_digest=digest({'synthetic':source.nonce}))
        pins = NativeJobPins(digest(context),digest(asdict(policy)),digest(asdict(spec)))
        request = dict(schema=BACKUP_REQUEST_SCHEMA,nonce=secrets.token_hex(32),plan_digest=plan.digest,
            source_identity=expected.identity,baseline_digest=expected.baseline_digest,
            config_digest=context['config_digest'],quiescence_digest=digest({'synthetic':True}))
        report['phase'] = 'native-job'
        private = dict(config=asdict(config),expected=asdict(expected),context=context,policy=asdict(policy),
            source_uri=connector.validated_uri()[0],spec=asdict(spec),daemon=source.daemon,pins=asdict(pins),request=request,
            source_descriptor=source.descriptor(),kill_after_clone=args.kill_after_clone,
            exercise_transports=args.exercise_transports)
        private['config']['timeouts'] = dict(config.timeouts)
        request_digest = digest(request)
        report['request_digest'] = request_digest
        report['source_descriptor'] = private['source_descriptor']
        require(source.job_resources(request_digest) == dict(containers=[],networks=[]),'physical-job-preexisting')
        fd = _sealed('synthetic-physical-job',json.dumps(private).encode())
        supervisor = NativeWorkerSupervisor()
        try:
            output = supervisor.run((sys.executable,str(Path(__file__).resolve()),'--worker'),timeout=1200,input_fd=fd)
        finally:
            os.close(fd)
        observed = json.loads(output)
        report['worker'] = {k:v for k,v in observed.items() if k != 'result'}
        require(observed['passed'] is True,'physical-native-job-refused')
        result = observed['result']
        report.update(passed=True,phase='completed',job=result,plan_digest=plan.digest,source_version=170006,
            controller_sources=dict(plan.adapter_sources),baseline=78,pending=51)
    except Exception as exc:
        # Local synthetic diagnostics remain private; no traceback/URI/driver
        # details enter the public aggregate report.
        report['reason'] = str(exc) if isinstance(exc,Refused) else type(exc).__name__
        raise
    finally:
        try:
            if request_digest is not None:
                report['job_resources_before_parent_cleanup'] = source.job_resources(request_digest)
                require(supervisor is not None and not supervisor.unreaped,'physical-job-worker-still-active')
                source.cleanup_job(request_digest,config,plan,expected)
                report['parent_job_cleanup_verified'] = True
                report['client_resources_before_parent_cleanup'] = source.client_resources(request_digest)
                source.cleanup_client(request_digest)
                report['parent_client_cleanup_verified'] = True
        finally:
            try:
                source.close();report['source_cleanup_verified'] = True
                report['cleanup_verified'] = request_digest is None or (report.get('parent_job_cleanup_verified') is True
                    and report.get('parent_client_cleanup_verified') is True)
            finally:
                report['elapsed_s'] = round(time.monotonic()-started,3)
                if report['cleanup_verified'] is not True:
                    report.update(passed=False,phase='cleanup-pending')
                path = root/'report.json'
                with path.open('x') as handle:json.dump(report,handle,sort_keys=True,indent=2)
                path.chmod(0o600)
                print(json.dumps({k:v for k,v in report.items() if k not in ('job','controller_sources')},sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
