"""Composed native job: actual custody/executor, synthetic source/Docker/PG IO."""
from copy import deepcopy
from dataclasses import asdict, replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import select
import threading
import time
from types import SimpleNamespace

import pytest


def test_legacy_owned_clone_cleanup_reconstruction_keeps_original_name_semantics(rig):
    kwargs=dict(run=rig.docker.run,clone_connect=rig.docker.connect,owner=os.geteuid(),
        work_deadline=time.monotonic()+30,cleanup_deadline=time.monotonic()+30)
    original=job.OwnedClone(rig.cfg,rig.worker.plan,rig.source.expected,digest(rig.request),
        rig.docker.daemon,'synthetic-source-system',**kwargs)
    original.__enter__()
    recovery=job.OwnedClone(rig.cfg,rig.worker.plan,rig.source.expected,digest(rig.request),
        rig.docker.daemon,'synthetic-source-system',**kwargs)
    recovery.container,recovery.network,recovery.image=original.container,original.network,original.image
    recovery.name,recovery.token=original.name,original.token
    recovery.close()
    assert recovery.cleaned and not rig.docker.have_container and not rig.docker.have_network


@pytest.mark.parametrize('fault',['image','nonce','privileged','ports','tmpfs','running','handoff-fd'])
def test_parent_scope_drift_refuses_before_source_login_or_child_start(rig,fault):
    owner,handle,boundary=parent_mode(rig)
    try:
        row=boundary.containers[rig.docker.container]
        if fault=='image':row['image']='sha256:'+'f'*64
        elif fault=='nonce':row['labels']['igreja12.native-cleanup.nonce']='f'*32
        elif fault=='privileged':row['privileged']=True
        elif fault=='ports':row['ports']={'5432/tcp':[{'HostPort':'5432'}]}
        elif fault=='tmpfs':row['tmpfs']={'/tmp':'rw'}
        elif fault=='running':
            row['running']=True;row['pid']=23456
            row['networks']=[[owner.registry.network_name,rig.docker.network]]
            boundary.networks[rig.docker.network]['members']=[rig.docker.container]
        else:os.close(handle._fd)
        with pytest.raises(Refused):rig.worker.execute(rig.request)
        assert rig.source.connections==[] and rig.requests==[]
        assert ('start',rig.docker.container) not in rig.docker.calls
        assert boundary.containers and boundary.networks
    finally:handle.close();owner.close()


def parent_mode(rig):
    """One shared fake daemon: actual parent CLI records, child may only start."""
    import first_transition_native_cleanup as cleanup
    from test_first_transition_native_cleanup import ProvisionDocker
    docker=rig.docker
    boundary=ProvisionDocker(cleanup,image=docker.image,reference=rig.cfg.clone_image)
    boundary.daemon=docker.daemon;boundary.network_id=docker.network;boundary.container_id=docker.container
    def parent_cli(argv,**kwargs):
        rc,raw=boundary(argv,**kwargs)
        docker.have_network=docker.network in boundary.networks
        docker.have_container=docker.container in boundary.containers
        return rc,raw
    owner=cleanup.NativeParentCloneProvisioner(rig.cfg,request_digest=digest(rig.request),
        context_digest=digest(rig.worker.context),daemon_id=docker.daemon,image_id=docker.image,
        runner=parent_cli,clock=rig.worker.clock,wall_clock=rig.worker.wall_clock)
    owner.provision(deadline=rig.worker.clock()+30)
    handle=cleanup.NativeParentCloneHandle.from_fd(owner.handoff_fd,expected_registry_digest=owner.registry.digest,
        request_digest=digest(rig.request),context_digest=digest(rig.worker.context),
        config_digest=digest(asdict(rig.cfg)),daemon_id=docker.daemon)
    docker.name=owner.registry.network_name;docker.request=digest(rig.request);docker.token=owner.registry.nonce
    docker.password=boundary.password
    original=docker.run
    def child_cli(argv,**kwargs):
        args=tuple(argv[5:])
        assert args[:2] not in (('network','create'),('run','-d')) and args[:1]!=('create',),'child tried resource creation'
        assert args[:1]!=('rm',) and args[:2]!=('network','rm'),'child tried parent-owned deletion'
        if args==('start',docker.container):
            assert all(c.closed for c in rig.source.connections)
            row=boundary.containers[docker.container];assert row['running'] is False
            row['running']=True;row['pid']=23456;row['networks']=[[owner.registry.network_name,docker.network]]
            boundary.networks[docker.network]['members']=[docker.container]
            docker.calls.append(args)
            return SimpleNamespace(returncode=0,stdout=b'non-authoritative start text\n')
        if (args[:5]==('inspect','--type','container','--format',cleanup.CONTAINER_VIEW)
            or args[:4]==('network','inspect','--format',cleanup.NETWORK_VIEW)
            or any(a.startswith(('label=','id=')) for a in args) and '--no-trunc' in args):
            rc,raw=parent_cli(('docker',*args),timeout=min(10,kwargs['timeout']),max_output=65536)
            return SimpleNamespace(returncode=rc,stdout=raw)
        result=original(argv,**kwargs)
        if args==('inspect','--format',job.CONTAINER_VIEW,docker.container):
            row=json.loads(result.stdout)
            running=boundary.containers[docker.container]['running']
            row[9]=running
            if not running:row[12]='0001-01-01T00:00:00Z';row[4][0][1]=''
            result.stdout=json.dumps(row).encode()
        return result
    rig.worker.run=child_cli;rig.worker.parent_clone=handle
    return owner,handle,boundary


def test_parent_registered_clone_is_only_started_by_child_and_cleaned_by_parent(rig):
    owner,handle,boundary=parent_mode(rig)
    try:
        result=rig.worker.execute(rig.request)
        assert result['cleanup_verified'] is False and result['parent_cleanup_required'] is True
        assert result['binding']['parent_registry_digest']==owner.registry.digest
        assert result['binding']['container_id']==owner.registry.containers[0].container_id
        assert result['binding']['network_id']==owner.registry.network_id
        assert result['clone_rehearsal']['final_ledger']==129 and len(rig.docker.applied)==51
        assert boundary.containers and boundary.networks
        assert ('start',rig.docker.container) in rig.docker.calls
        assert not any(args[:1]==('rm',) for args in rig.docker.calls)
        proof=owner.cleanup(request_digest=digest(rig.request),context_digest=digest(rig.worker.context),
            result=result,status='validated',deadline=rig.worker.clock()+30,worker_cleanup_uncertain=False)
        assert proof.absent_resource_ids==tuple(sorted((rig.docker.container,rig.docker.network)))
        assert not boundary.containers and not boundary.networks
    finally:handle.close();owner.close()


def test_worker_failure_leaves_only_registered_resources_for_parent_cleanup(rig):
    owner,handle,boundary=parent_mode(rig)
    rig.docker.fault='migration'
    try:
        with pytest.raises(Refused):rig.worker.execute(rig.request)
        assert len(rig.docker.applied)==2 and boundary.containers and boundary.networks
        assert all(c.closed for c in rig.docker.connections) and all(c.closed for c in rig.source.connections)
        owner.cleanup(request_digest=digest(rig.request),context_digest=digest(rig.worker.context),result=None,
            status='worker-failed',deadline=rig.worker.clock()+30,worker_cleanup_uncertain=False)
        assert not boundary.containers and not boundary.networks
    finally:handle.close();owner.close()

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import first_transition_database as db
import first_transition_native_job as job
import first_transition_native_readers as readers
import first_transition_window_backup as wb
from first_transition_adapter import digest,prepare
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA
from initial_transition_ops import Refused
from test_first_transition_native_snapshot import Driver,Connection,Cursor,SECRET,NOW
from test_first_transition_native_readers import CollectCursor,payload
from test_first_transition_orchestrator import no_real_processes_or_network  # noqa: F401
from test_first_transition_window_backup import config


class DumpProcess:
    def __init__(self,data,code=0,delay=0):
        read,write=os.pipe2(os.O_NONBLOCK|os.O_CLOEXEC)
        self.stdout=os.fdopen(read,'rb',buffering=0)
        self.code,self.killed=code,False
        self.stop=threading.Event()
        def emit():
            try:
                if self.stop.wait(delay):return
                offset=0
                while offset<len(data) and not self.stop.is_set():
                    if select.select((),(write,),(),.05)[1]:
                        offset+=os.write(write,data[offset:offset+4096])
            finally:os.close(write)
        self.thread=threading.Thread(target=emit,daemon=True);self.thread.start()
    def wait(self,timeout=None):
        self.thread.join(timeout)
        if self.thread.is_alive():raise TimeoutError('synthetic producer timeout')
        return self.code
    def poll(self):return None if self.thread.is_alive() else self.code
    def kill(self):self.killed=True;self.stop.set()


class SourceCursor(Cursor):
    def execute(self,query,params=None):
        c=self.connection
        if query==db.Q_BEGIN and not c.importer:
            c.inventory=deepcopy(c.driver.inventory)
        if query==wb.NativeSourceSnapshot.Q_IMPORT:
            c.inventory=deepcopy(c.driver.snapshots[params[0]])
        if query==wb.NativeSourceSnapshot.Q_EXPORT:
            c.driver.snapshots['00000003-00000001-1']=deepcopy(c.inventory)
        if query==db.Q_IDENTITY:
            c.log.append((query,params));self.rows=[('7300000000000000001',16384,'postgres')];return
        if not hasattr(c,'inventory'):return super().execute(query,params)
        data=CollectCursor(c.inventory['v2'],c.inventory['v3'])
        try:data.execute(query)
        except AssertionError:return super().execute(query,params)
        assert c.importer and c.imported
        c.log.append((query,params));self.rows=data.rows


class CloneConnection:
    def __init__(self,docker,database):
        self.docker,self.database=docker,database
        self._autocommit,self.closed,self.probed=False,False,False
        self.info=SimpleNamespace(used_password=True,user='postgres',server_version=170006,transaction_status=0)
        self.search_path='pg_catalog,public'
        self._saved_path=None
        self._local_path=False
    @property
    def autocommit(self):return self._autocommit
    @autocommit.setter
    def autocommit(self,value):
        assert self.info.transaction_status==0, 'autocommit changed in an open transaction'
        self.docker.autocommit_states.append(self.info.transaction_status)
        self._autocommit=value
    def begin(self):
        assert self.info.transaction_status==0
        self._saved_path=self.search_path
        self._local_path=False
        self.info.transaction_status=2
    def end(self):
        if self._local_path:self.search_path=self._saved_path
        self._saved_path=None
        self._local_path=False
        self.info.transaction_status=0
    def cursor(self):return CloneCursor(self)
    def close(self):self.closed=True
    def commit(self):self.end()
    def rollback(self):self.end()


class CloneCursor:
    def __init__(self,c):self.c,self.rows=c,[]
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def fetchall(self):return self.rows
    def fetchone(self):return self.rows[0]
    def execute(self,q,params=None):
        d=self.c.docker
        assert not self.c.closed
        if q==db.Q_BEGIN:
            assert self.c.search_path=='pg_catalog,public', 'probe transaction began with the migration path'
            self.c.begin()
            d.sql.append(q)
            return
        if q=='ROLLBACK':
            self.c.rollback()
            d.sql.append(q)
            return
        if not self.c.autocommit and self.c.info.transaction_status==0:self.c.begin()
        if not isinstance(q,(str,bytes)):
            from psycopg2 import sql
            assert self.c.probed
            assert type(q) is sql.Composed and len(q.seq)==3, 'unmocked bootstrap SQL'
            prefix,identifier,suffix=q.seq
            assert type(prefix) is sql.SQL and type(identifier) is sql.Identifier and type(suffix) is sql.SQL
            assert len(identifier.strings)==1
            name=identifier.strings[0]
            roles=d.inventory['v2']['manifest']['roles']
            if prefix.string in ('CREATE ROLE ','ALTER ROLE '):
                assert name!='postgres' and not name.startswith('pg_'), 'builtin role altered'
            if prefix.string=='CREATE ROLE ':
                assert suffix.string==' NOLOGIN NOINHERIT' and all(role['name']!=name for role in roles)
                roles.append(dict(name=name,can_login=False,
                    superuser=False,inherit=False,create_role=False,create_db=False,replication=False,bypass_rls=False))
                d.role_statements.append(('create',name))
            elif prefix.string=='ALTER ROLE ':
                words=suffix.string.split()
                flags=(('superuser','SUPERUSER','NOSUPERUSER'),('inherit','INHERIT','NOINHERIT'),
                    ('create_role','CREATEROLE','NOCREATEROLE'),('create_db','CREATEDB','NOCREATEDB'),
                    ('replication','REPLICATION','NOREPLICATION'),('bypass_rls','BYPASSRLS','NOBYPASSRLS'))
                assert len(words)==7 and words[-1] in ('LOGIN','NOLOGIN')
                observed=next(role for role in roles if role['name']==name)
                for word,(key,yes,no) in zip(words,flags):
                    assert word in (yes,no)
                    observed[key]=word==yes
                observed['can_login']=words[-1]=='LOGIN'
                d.role_statements.append(('alter',name))
            else:
                assert prefix.string=='CREATE DATABASE ' and name==wb.CLONE_DB
                assert suffix.string==' TEMPLATE template0'
            d.bootstrap.append(repr(q))
            return
        d.sql.append(q)
        if q in (job.MIGRATION_PATH_SQL,job.PROBE_PATH_SQL):
            assert self.c.autocommit is True and self.c.info.transaction_status==0
            d.path_switches.append(q)
            self.c.search_path='"$user",public' if q==job.MIGRATION_PATH_SQL else 'pg_catalog,public'
            return
        if q in (job.ROLE_QUERY,db.Q_IDENTITY,db.Q_LEDGER,db.Q_CATALOG,db.Q_INVALID):
            assert self.c.search_path=='pg_catalog,public', 'metadata probe used the migration path'
            d.probe_paths.append(self.c.search_path)
        if q==db.Q_IDENTITY:
            self.rows=[(getattr(self.c,'system_override',d.system),16384,self.c.database)];self.c.probed=True
        elif q==job.ROLE_QUERY:self.rows=[('postgres','postgres')]
        elif q==db.Q_LEDGER:self.rows=[(name,) for name in sorted(d.ledger)]
        elif q==db.Q_CATALOG:self.rows=d.catalog_rows if not d.applied else [('relation','final','b'*32)]
        elif q==db.Q_INVALID:self.rows=[]
        elif q==db.Q_PATH:
            self.c.search_path='pg_catalog,public';self.c._local_path=True
            self.rows=[('ok',)]
        elif q==db.Q_TIMEOUT:self.rows=[('ok',)]
        elif q=='SELECT rolname FROM pg_roles':self.rows=[(r['name'],) for r in d.inventory['v2']['manifest']['roles']]
        elif q=='SELECT to_regclass(%s)':self.rows=[('public.schema_migrations',)]
        elif q=='SELECT name FROM public.schema_migrations':self.rows=[(n,) for n in sorted(d.ledger)]
        elif q=='SHOW lock_timeout':self.rows=[('2s',)]
        elif q=='INSERT INTO public.schema_migrations (name) VALUES (%s)':
            assert self.c.probed
            name=params[0]
            if d.fault=='migration' and len(d.applied)==2:raise RuntimeError('SYNTHETIC-PRIVATE-MIGRATION')
            d.applied.append(name);d.ledger.append(name)
        else:
            data=CollectCursor(d.inventory['v2'],d.inventory['v3'])
            try:data.execute(q)
            except AssertionError:
                if q in d.allowed_sql:
                    assert self.c.probed
                    assert self.c.search_path=='"$user",public', 'migration did not inherit the CLI default path'
                    d.migration_paths.append((self.c,self.c.search_path,self.c.autocommit,self.c.info.transaction_status))
                    d.payload_sql.append(q)
                    return
                assert q=='SET LOCAL lock_timeout = %s' or q in d.allowed_utilities, 'unmocked clone SQL'
                return
            if q==readers.sql.V3_PATH:
                self.c.search_path='pg_catalog';self.c._local_path=True
            self.rows=data.rows


class Docker:
    daemon='synthetic-daemon'
    network='1'*64
    container='2'*64
    image='sha256:'+'3'*64
    system='7400000000000000001'
    def __init__(self,source,plan,clone_image):
        self.source,self.plan,self.clone_image=source,plan,clone_image
        self.name=self.request=self.token=self.password=None
        self.have_network=self.have_container=False
        self.report_tmpfs_mount=False
        self.calls,self.sql,self.bootstrap,self.applied,self.connections=[],[],[],[],[]
        self.role_statements=[]
        self.payload_sql=[]
        self.probe_paths,self.migration_paths,self.path_switches,self.autocommit_states=[],[],[],[]
        parser={'__name__':'fixture_pinned_parser','__file__':'/synthetic/scripts/migrate.py'}
        exec(compile(plan.executor,'<fixture-pinned-parser>','exec'),parser)
        self.allowed_sql=set();self.allowed_utilities=set()
        for migration in plan.pending:
            text=parser['strip_outer_transaction'](migration.sql.decode())
            setting=parser['_SESSION_LOCK_TIMEOUT'].match(text) if migration.concurrent else None
            self.allowed_sql.add(text[setting.end():] if setting else text)
            if setting:self.allowed_utilities.add(setting.group())
        self.ledger=[];self.fault=None;self.catalog_rows=[];self.restore_bytes=None
        # Independent clean image template: no source globals are copied.
        roles=[dict(name='postgres',can_login=True,superuser=True,inherit=True,create_role=True,
                    create_db=True,replication=True,bypass_rls=True)]
        for name in ('pg_monitor','pg_read_all_stats'):
            roles.append(dict(name=name,can_login=False,superuser=False,inherit=True,
                         create_role=False,create_db=False,replication=False,bypass_rls=False))
        self.inventory=dict(v2=dict(manifest=dict(roles=roles,
            memberships=[dict(role='pg_read_all_stats',member='pg_monitor',grantor='postgres',admin=False,inherit=True,set_role=True)],
            extensions=[],events=[],schemas=[],default_acl=[],functions=[],catalog=[]),
            row_counts={},settings=[]),v3={key:[] for key in readers.coverage_compare.KEYS})

    def connect(self,*,host,dbname,user,password,timeout):
        assert self.have_container and host=='172.30.0.2' and user=='postgres' and password==self.password
        assert self.have_network
        c=CloneConnection(self,dbname);self.connections.append(c);return c
    def run(self,argv,*,stdin,stdout,stderr,env,timeout,close_fds,shell,check):
        assert close_fds and not shell and timeout>0
        args=tuple(argv[5:]);self.calls.append(args)
        out='';rc=0
        if args[:1]==('info',):out=json.dumps('other-daemon' if self.fault=='daemon' else self.daemon)
        elif args[:2]==('image','inspect'):out=json.dumps([self.image])
        elif args[:2]==('network','create'):
            assert all(c.closed for c in self.source.connections)
            self.name=args[-1]
            labels=[args[i+1] for i,a in enumerate(args) if a=='--label']
            self.request=labels[0].split('=',1)[1];self.token=labels[1].split('=',1)[1]
            self.have_network=True;out=self.network
            if self.fault=='network-ambiguous':rc=1;out=''
        elif args[:2]==('run','-d'):
            assert '--pull=never' in args and '--restart=no' in args and '--tmpfs' in args
            self.password=env[wb.CLONE_ENV]
            self.have_container=True;out=self.container
            if self.fault=='container-ambiguous':rc=1;out=''
        elif args[:2]==('network','inspect'):
            assert args[-1]==self.network
            out=json.dumps([self.network,self.name,(1 if self.fault=='internal-int' else self.fault!='egress'),'bridge',self.request,self.token,
                            ([self.container] if self.have_container else [])+[None]])
        elif args[:1]==('inspect',):
            assert args[-1]==self.container
            mounts=([['tmpfs','/var/lib/postgresql/data']] if self.report_tmpfs_mount else [])+[None]
            tmpfs={'/var/lib/postgresql/data':'rw,nosuid,nodev,noexec,size=536870912'}
            if self.fault=='wrong-tmpfs-flags':tmpfs['/var/lib/postgresql/data']='rw,size=536870912'
            elif self.fault=='extra-tmpfs':tmpfs['/tmp']='rw,nosuid,nodev,noexec,size=33554432'
            elif self.fault=='missing-tmpfs':tmpfs=None
            elif self.fault=='empty-tmpfs':tmpfs={}
            elif self.fault=='bind-mount':mounts=[['bind','/var/lib/postgresql/data'],None]
            elif self.fault=='volume-mount':mounts=[['volume','/var/lib/postgresql/data'],None]
            elif self.fault=='extra-mount':mounts=[['tmpfs','/var/lib/postgresql/data'],['tmpfs','/tmp'],None]
            out=json.dumps([self.container,self.image,self.clone_image,self.network,
                [[self.name,self.network,'172.30.0.2'],None],mounts,
                None,self.request,'other-token' if self.fault=='label' else self.token,True,False,0,('0001-01-01T00:00:00Z' if self.fault=='zero-start' else '2026-11-06T00:00:00Z'),'no',(0 if self.fault=='privileged-int' else self.fault=='privileged'),tmpfs])
        elif args[:1]==('exec',):
            assert args[4]==self.container and stdin is not None
            assert fcntl.fcntl(stdin.fileno(),wb.MEMFD_GET_SEALS)&wb.MEMFD_SEALS==wb.MEMFD_SEALS
            self.restore_bytes=stdin.read()
            archive=json.loads(self.restore_bytes[5:])
            self.catalog_rows=archive['catalog']
            assert env[wb.RESTORE_ENV]==self.password
            self.ledger=archive['ledger']
            roles=self.inventory['v2']['manifest']['roles']
            memberships=self.inventory['v2']['manifest']['memberships']
            configured=self.inventory['v2']['settings']
            self.inventory=archive['inventory']
            self.inventory['v2']['manifest']['roles']=roles
            self.inventory['v2']['manifest']['memberships']=memberships
            self.inventory['v2']['settings']=configured
            if self.fault=='missing-v3':self.inventory['v3']['initial_privileges']=[]
            elif self.fault=='roles':self.inventory['v2']['manifest']['roles'][-1]['can_login']=True
            elif self.fault=='settings':self.inventory['v2']['settings']=[dict(scope='all',role=None,key='statement_timeout',value='8s')]
            elif self.fault=='acl':self.inventory['v2']['manifest']['schemas'][0]['acl']='{}'
            elif self.fault=='count':self.inventory['v2']['row_counts']['public.synthetic_table']+=1
            elif self.fault=='identity-after-restore':self.system='7500000000000000001'
        elif args[:1]==('rm',):
            assert args[-1]==self.container
            if self.fault!='cleanup':self.have_container=False
        elif args[:2]==('network','rm'):
            assert args[-1]==self.network
            if not self.have_container:self.have_network=False
        elif args[:2]==('network','ls'):
            if any(a.startswith('id=') for a in args) and self.have_network:out=self.network
        elif args[:1]==('ps',):
            if self.fault=='preexisting' and any(a.startswith('name=') for a in args):out='9'*64
            if any(a.startswith('id=') for a in args) and self.have_container:out=self.container
        else:raise AssertionError('unexpected Docker command')
        return SimpleNamespace(returncode=rc,stdout=out.encode())


@pytest.fixture(scope='module')
def plan():return prepare(Path(__file__).resolve().parents[2])


@pytest.fixture
def rig(plan,tmp_path,monkeypatch):
    for key in list(os.environ):
        if key.startswith('PG'):monkeypatch.delenv(key)
    ca=tmp_path/'ca.crt';ca.write_bytes(b'SYNTHETIC-PUBLIC-CA');ca.chmod(0o600)
    binary=tmp_path/'pg_dump';binary.write_bytes(b'\x7fELF-SYNTHETIC-TOOL');binary.chmod(0o755)
    policy=wb.NativeSourcePolicy('origin.synthetic.invalid','192.0.2.10',5432,str(ca),
                                hashlib.sha256(ca.read_bytes()).hexdigest(),os.geteuid())
    source=Driver(ca.read_bytes())
    v2,v3=payload()
    v2['manifest']['roles'].append(dict(name='anon',can_login=True,superuser=False,inherit=False,
        create_role=False,create_db=False,replication=False,bypass_rls=False))
    for name in ('pg_monitor','pg_read_all_stats'):
        v2['manifest']['roles'].append(dict(name=name,can_login=False,superuser=False,inherit=True,
            create_role=False,create_db=False,replication=False,bypass_rls=False))
    v2['manifest']['memberships']=[dict(role='pg_read_all_stats',member='pg_monitor',grantor='postgres',admin=False,inherit=True,set_role=True)]
    v2['manifest']['extensions']=[dict(name='synthetic_ext',version='1.0',schema='synthetic_graphql',owner='postgres')]
    v2['manifest']['events']=[dict(name='synthetic_evt',owner='postgres',enabled='O')]
    v2['manifest']['default_acl']=[dict(owner='postgres',schema='public',kind='r',acl='{anon=r/postgres}')]
    v2['manifest']['functions']=[dict(schema='synthetic_graphql',name='synthetic_fn',args='document text',owner='postgres',security_definer=False,acl='{anon=X/postgres}')]
    v2['settings']=[]
    v3['relations']=[dict(schema='public',name='synthetic_table',kind='r',owner='postgres',rls=False,force_rls=False,acl=None)]
    v3['columns']=[dict(schema='public',relation='synthetic_table',name='church_id',acl=None)]
    v3['types']=[dict(schema='public',name='synthetic_enum',kind='e',owner='postgres',acl=None)]
    v3['default_acl']=[dict(owner='postgres',schema='public',kind='r',acl=[dict(grantor='postgres',grantee='anon',privilege='SELECT',grant_option=False)])]
    v3['policies']=[dict(schema='public',relation='synthetic_table',name='synthetic_policy',command='r',permissive=True,roles=[None],using_sha256='d'*64,check_sha256=None)]
    v3['indexes']=[dict(schema='public',relation='synthetic_table',name='synthetic_pk',valid=True,ready=True,live=True,definition_sha256='c'*64)]
    source.inventory=dict(v2=v2,v3=v3)
    source.snapshots={};source.producer=None;source.dump_fault=None
    source.expected=db.DatabaseExpectation(digest(['7300000000000000001',16384,'postgres']),plan.baseline,digest(source.catalog))
    monkeypatch.setattr(Connection,'cursor',lambda c:SourceCursor(c))
    connector=wb.NativeSourceConnector(policy,secret=lambda:SECRET,driver=source)
    cfg=config(tmp_path,python=sys.executable)
    docker=Docker(source,plan,cfg.clone_image)
    spec=job.NativeDumpSpec(str(binary),hashlib.sha256(binary.read_bytes()).hexdigest(),os.geteuid())
    context=dict(plan_digest=plan.digest,source_identity=source.expected.identity,
        baseline_digest=source.expected.baseline_digest,backup_config_digest=digest(asdict(cfg)),
        ca_sha256=policy.ca_sha256,config_digest='d'*64)
    requests=[]
    def popen(argv,**kwargs):
        assert argv[-1]=='--snapshot=00000003-00000001-1'
        assert '--format=custom' in argv and '--no-password' in argv
        assert kwargs['start_new_session'] is False and kwargs['shell'] is False
        env=kwargs['env']
        assert env['PGHOSTADDR']==policy.hostaddr and env['PGSSLMODE']=='verify-full'
        assert env['PGSSLCERTMODE']=='disable' and env['PGPASSWORD']=='SYNTHETIC-PRIVATE'
        servicefd=int(env['PGSERVICEFILE'].rsplit('/',1)[1])
        assert servicefd in kwargs['pass_fds'] and fcntl.fcntl(servicefd,wb.MEMFD_GET_SEALS)&wb.MEMFD_SEALS==wb.MEMFD_SEALS
        service=os.pread(servicefd,65536,0).decode()
        assert 'sslcertmode=disable' in service and 'channel_binding=require' in service
        assert 'sslrootcert='+env['PGSSLROOTCERT'] in service and 'hostaddr='+policy.hostaddr in service
        assert 'SYNTHETIC-PRIVATE' not in service and '--dbname=service=igreja12_native' in argv
        assert fcntl.fcntl(int(env['PGSSLROOTCERT'].rsplit('/',1)[1]),wb.MEMFD_GET_SEALS)&wb.MEMFD_SEALS==wb.MEMFD_SEALS
        assert all('SYNTHETIC-PRIVATE' not in arg for arg in argv)
        requests.append(argv)
        captured=deepcopy(source.snapshots[argv[-1].split('=',1)[1]])
        data=b'PGDMP'+readers.raw(dict(catalog=source.catalog,ledger=list(plan.baseline),inventory=captured))
        if source.dump_fault=='header':data=b'BAD!!'+data[5:]
        source.dump_bytes=data
        source.producer=DumpProcess(data,code=1 if source.dump_fault=='exit' else 0,
                                   delay=1.1 if source.dump_fault=='silent' else 0)
        return source.producer
    worker=job.NativeWindowJob(cfg,plan,source.expected,context,connector,spec,docker.daemon,
        job.NativeJobPins(digest(context),digest(asdict(policy)),digest(asdict(spec))),
        owner=os.geteuid(),dump_popen=popen,run=docker.run,clone_connect=docker.connect,wall_clock=lambda:NOW)
    request=dict(schema=BACKUP_REQUEST_SCHEMA,nonce='e'*64,plan_digest=plan.digest,source_identity=source.expected.identity,
        baseline_digest=source.expected.baseline_digest,config_digest='d'*64,quiescence_digest='f'*64)
    return SimpleNamespace(worker=worker,request=request,docker=docker,source=source,cfg=cfg,requests=requests)


def test_composed_job_binds_capture_restore_sample_and_replay_to_own_clone(rig):
    result=rig.worker.execute(rig.request)
    assert result['schema']==job.JOB_SCHEMA and result['a8_window_proven'] is False
    assert result['cleanup_verified'] is True and result['operational_ready'] is False
    assert len(rig.requests)==1 and len(rig.docker.applied)==51 and len(rig.docker.payload_sql)==51
    assert result['clone_rehearsal']['final_ledger']==129 and result['clone_rehearsal']['concurrent']==8
    assert result['binding_digest']==digest(result['binding'])
    assert result['binding']['request_digest']==digest(rig.request)
    assert result['binding']['container_id']==rig.docker.container and result['binding']['network_id']==rig.docker.network
    assert not rig.docker.have_container and not rig.docker.have_network
    assert all(c.closed for c in rig.docker.connections) and all(c.closed for c in rig.source.connections)
    assert 'SYNTHETIC-PRIVATE' not in json.dumps(result) and str(rig.cfg.backup_root) not in json.dumps(result)
    assert rig.source.expected.ledger==rig.worker.plan.baseline
    with pytest.raises(Refused,match='native-job-used'):rig.worker.execute(rig.request)


def test_replay_uses_cli_path_for_each_file_and_protected_idle_path_for_probes(rig):
    result=rig.worker.execute(rig.request)
    assert result['cleanup_verified'] is True
    paths=rig.docker.migration_paths
    assert len(paths)==51 and len({id(row[0]) for row in paths})==51
    assert all(path=='"$user",public' for _,path,_,_ in paths)
    assert sum(not autocommit and status==2 for _,_,autocommit,status in paths)==43
    assert sum(autocommit and status==0 for _,_,autocommit,status in paths)==8
    assert rig.docker.path_switches==[job.MIGRATION_PATH_SQL,job.PROBE_PATH_SQL]*51
    assert rig.docker.probe_paths and set(rig.docker.probe_paths)=={'pg_catalog,public'}
    assert rig.docker.autocommit_states and set(rig.docker.autocommit_states)=={0}
    assert all(connection.closed for connection in rig.docker.connections)


@pytest.mark.parametrize('reported_mount',[False,True])
def test_exact_tmpfs_is_required_whether_docker_reports_it_in_mounts_or_not(rig,reported_mount):
    rig.docker.report_tmpfs_mount=reported_mount
    assert '{{json .HostConfig.Tmpfs}}' in job.CONTAINER_VIEW
    assert rig.worker.execute(rig.request)['cleanup_verified'] is True
    assert len(rig.docker.applied)==51
    assert not rig.docker.have_container and not rig.docker.have_network


@pytest.mark.parametrize('fault',['wrong-tmpfs-flags','extra-tmpfs','missing-tmpfs','empty-tmpfs',
                                  'bind-mount','volume-mount','extra-mount'])
def test_tmpfs_or_mount_drift_refuses_before_sql_but_still_cleans_owned_ids(rig,fault):
    rig.docker.fault=fault
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert rig.docker.connections==[] and rig.docker.bootstrap==[] and rig.docker.applied==[]
    assert not rig.docker.have_container and not rig.docker.have_network
    removals=[args for args in rig.docker.calls if args[:1]==('rm',) or args[:2]==('network','rm')]
    assert removals==[('rm','-f','-v',rig.docker.container),('network','rm',rig.docker.network)]


@pytest.mark.parametrize('name,extra', [('service_role',dict(bypass_rls=True)),
    ('synthetic"reader',dict(inherit=True,create_role=True,create_db=True,replication=True,bypass_rls=True))])
def test_clone_restores_nonbuiltin_role_flags_without_changing_builtins_or_source(rig,name,extra):
    role=dict(name=name,can_login=True,superuser=False,inherit=False,create_role=False,
              create_db=False,replication=False,bypass_rls=False)
    role.update(extra)
    rig.source.inventory['v2']['manifest']['roles'].append(role)
    original=deepcopy(role)
    builtins=deepcopy(rig.docker.inventory['v2']['manifest']['roles'])
    assert rig.worker.execute(rig.request)['cleanup_verified'] is True
    observed={row['name']:row for row in rig.docker.inventory['v2']['manifest']['roles']}
    assert observed[name]=={**original,'can_login':False}
    assert role==original
    assert all(observed[row['name']]==row for row in builtins)
    assert all(target!='postgres' and not target.startswith('pg_') for _,target in rig.docker.role_statements)
    assert len(rig.docker.applied)==51


def test_nonallowlisted_source_superuser_refuses_before_any_clone_ddl(rig):
    rig.source.inventory['v2']['manifest']['roles'].append(dict(name='forbidden_admin',can_login=True,
        superuser=True,inherit=True,create_role=True,create_db=True,replication=True,bypass_rls=True))
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert rig.docker.bootstrap==[] and rig.docker.connections==[] and rig.docker.applied==[]
    assert not rig.docker.have_container and not rig.docker.have_network


@pytest.mark.parametrize('source_superuser',[False,True])
def test_clone_superuser_allowlist_also_requires_corresponding_source_flag(rig,source_superuser):
    role=dict(name='supabase_admin',can_login=False,superuser=source_superuser,inherit=True,
              create_role=True,create_db=True,replication=False,bypass_rls=True)
    rig.source.inventory['v2']['manifest']['roles'].append(role)
    config=replace(rig.worker.config,clone_superusers=('postgres','supabase_admin'))
    context={**rig.worker.context,'backup_config_digest':digest(asdict(config))}
    rig.worker.config,rig.worker.context=config,context
    rig.worker.pins=replace(rig.worker.pins,context_sha256=digest(context))
    if source_superuser:
        assert rig.worker.execute(rig.request)['cleanup_verified'] is True
        observed=next(row for row in rig.docker.inventory['v2']['manifest']['roles'] if row['name']=='supabase_admin')
        assert observed=={**role,'can_login':True}
    else:
        with pytest.raises(Refused):rig.worker.execute(rig.request)
        assert rig.docker.bootstrap==[] and rig.docker.connections==[] and rig.docker.applied==[]
    assert not rig.docker.have_container and not rig.docker.have_network


@pytest.mark.parametrize('change',['nonce','plan_digest','source_identity','baseline_digest','config_digest','quiescence_digest','schema','extra'])
def test_invalid_request_is_consumed_before_any_source_or_clone_io(rig,change):
    request=dict(rig.request);request[change]='invalid'
    with pytest.raises(Refused):rig.worker.execute(request)
    assert rig.source.connections==[] and rig.docker.calls==[] and rig.requests==[]
    with pytest.raises(Refused,match='native-job-used'):rig.worker.execute(rig.request)


@pytest.mark.parametrize('fault',['header','exit'])
def test_dump_failure_never_creates_clone(rig,fault):
    rig.source.dump_fault=fault
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert rig.docker.calls==[] and all(c.closed for c in rig.source.connections)
    assert rig.source.producer is not None and not rig.source.producer.thread.is_alive()


def test_silent_dump_has_real_foreground_keepalive(rig):
    rig.source.dump_fault='silent'
    result=rig.worker.execute(rig.request)
    path=Path(rig.cfg.backup_root)/digest(rig.request)/'companion.json'
    companion=json.loads(path.read_bytes())
    assert companion['dump']['pulse_calls']>=1 and companion['dump']['maximum_pulse_gap_s']<=2
    assert result['cleanup_verified'] is True


def test_keepalive_gap_refuses_before_clone(rig,monkeypatch):
    def fail(_self):raise Refused('native-dump-keepalive-gap')
    monkeypatch.setattr(job._Pulse,'__call__',fail)
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert rig.docker.calls==[] and all(c.closed for c in rig.source.connections)


@pytest.mark.parametrize('fault',['missing-v3','roles','settings','acl','count','identity-after-restore'])
def test_strict_restore_or_clone_identity_gap_never_reaches_replay(rig,fault):
    rig.docker.fault=fault
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert rig.docker.applied==[]
    assert not rig.docker.have_container and not rig.docker.have_network
    assert all(c.closed for c in rig.docker.connections)


def test_source_cluster_cannot_be_bootstrapped_even_inside_container_scope(rig):
    rig.docker.system='7300000000000000001'
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert rig.docker.bootstrap==[] and rig.docker.applied==[]
    assert not rig.docker.have_container and not rig.docker.have_network


@pytest.mark.parametrize('fault',['preexisting','daemon','egress','label','privileged','network-ambiguous','container-ambiguous','internal-int','privileged-int','zero-start'])
def test_unowned_ambiguous_or_unisolated_resources_are_not_adopted_or_removed_by_name(rig,fault):
    rig.docker.fault=fault
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert rig.docker.applied==[]
    removals=[args for args in rig.docker.calls if args[:1]==('rm',) or args[:2]==('network','rm')]
    assert all(args[-1] in (rig.docker.container,rig.docker.network) for args in removals)
    if fault in ('preexisting','daemon','network-ambiguous','container-ambiguous','label'):
        assert removals==[]


def test_cleanup_incomplete_never_returns_result_and_cannot_retry(rig):
    rig.docker.fault='cleanup'
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert len(rig.docker.applied)==51 and rig.docker.have_container and rig.docker.have_network
    calls=len(rig.docker.calls)
    with pytest.raises(Refused,match='native-job-used'):rig.worker.execute(rig.request)
    assert len(rig.docker.calls)==calls


def test_pinned_executor_first_failure_stops_and_cleans_owned_clone(rig):
    rig.docker.fault='migration'
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert len(rig.docker.applied)==2
    assert not rig.docker.have_container and not rig.docker.have_network


def test_provider_rotation_after_first_login_does_not_change_dump_or_readers(rig):
    rig.source.after=lambda:setattr(rig.worker.connector,'secret',lambda:'postgresql://wrong:wrong@wrong.invalid/other')
    assert rig.worker.execute(rig.request)['cleanup_verified'] is True
    assert len(rig.requests)==1


def test_live_source_change_after_export_does_not_change_the_imported_dump_snapshot(rig):
    source=rig.source
    native=rig.worker.dump_popen
    def mutate(argv,**kwargs):
        source.inventory['v2']['row_counts']['public.synthetic_table']=1000
        return native(argv,**kwargs)
    rig.worker.dump_popen=mutate
    result=rig.worker.execute(rig.request)
    assert result['binding']['sample_summary']['row_counts_sha256']==digest({'public.synthetic_table':7})
    assert rig.docker.inventory['v2']['row_counts']=={'public.synthetic_table':7}


@pytest.mark.parametrize('which',['source_policy','dump_spec','context'])
def test_changed_runtime_policy_with_same_ca_refuses_before_first_login(rig,which):
    if which=='source_policy':rig.worker.connector.policy=replace(rig.worker.connector.policy,hostaddr='192.0.2.11')
    elif which=='dump_spec':rig.worker.dump_spec=replace(rig.worker.dump_spec,sha256='a'*64)
    else:rig.worker.context['config_digest']='0'*64
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert rig.source.connections==[] and rig.requests==[] and rig.docker.calls==[]


@pytest.mark.parametrize('global_kind',['settings','memberships'])
def test_unsupported_source_globals_are_not_preloaded_into_clone_or_normalized(rig,global_kind):
    if global_kind=='settings':
        rig.source.inventory['v2']['settings']=[dict(scope='all',role=None,key='statement_timeout',value='8s')]
    else:
        rig.source.inventory['v2']['manifest']['memberships'].append(dict(role='pg_monitor',member='anon',grantor='postgres',admin=False,inherit=True,set_role=True))
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert rig.docker.applied==[] and not rig.docker.have_container and not rig.docker.have_network


def test_clone_transport_switch_after_sampling_never_runs_any_migration(rig):
    connect=rig.worker.clone_connect
    def switched(**kwargs):
        conn=connect(**kwargs)
        if len(rig.docker.connections)>=3:conn.system_override='7500000000000000001'
        return conn
    rig.worker.clone_connect=switched
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert rig.docker.applied==[] and not rig.docker.have_container and not rig.docker.have_network


def test_companion_from_another_request_never_starts_clone(rig,monkeypatch):
    original=wb.NativeWindowArtifacts.write_companion
    def wrong(store,data,**kwargs):
        value=json.loads(data);value['request_digest']='0'*64
        return original(store,readers.raw(value),**kwargs)
    monkeypatch.setattr(wb.NativeWindowArtifacts,'write_companion',wrong)
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert rig.docker.calls==[] and rig.docker.applied==[]


@pytest.mark.parametrize('kind',['dump','companion'])
def test_path_or_bytes_changed_before_restore_never_reaches_replay(rig,monkeypatch,kind):
    from contextlib import contextmanager
    original=wb.NativeWindowArtifacts.verified_fd
    fired=[]
    @contextmanager
    def altered(store,selected,**kwargs):
        if selected=='dump' and not fired:
            fired.append(True)
            target=Path(store.root)/store.request_digest/store.FILES[kind][0]
            target.write_bytes(b'PGDMP-CHANGED' if kind=='dump' else b'{}')
        with original(store,selected,**kwargs) as fd:yield fd
    monkeypatch.setattr(wb.NativeWindowArtifacts,'verified_fd',altered)
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert rig.docker.applied==[] and not rig.docker.have_container and not rig.docker.have_network


def test_expired_elf_preparation_cannot_spawn_pg_dump(rig,monkeypatch):
    from contextlib import contextmanager
    now=[1000.0];rig.worker.clock=lambda:now[0]
    original=job.NativeDumpSpec.executable
    @contextmanager
    def delayed(spec):
        with original(spec) as fd:
            now[0]+=91
            yield fd
    monkeypatch.setattr(job.NativeDumpSpec,'executable',delayed)
    with pytest.raises(Refused):rig.worker.execute(rig.request)
    assert rig.requests==[] and rig.docker.calls==[]


def test_runtime_client_service_parser_refuses_unknown_mandatory_policy_without_endpoint(tmp_path,monkeypatch):
    # Exercise the native service parser against a deliberately nonexistent
    # socket directory we own. No real server/DNS endpoint is configured.
    import psycopg2
    for key in list(os.environ):
        if key.startswith('PG'):monkeypatch.delenv(key)
    endpoint=tmp_path/'empty';endpoint.mkdir(mode=0o700)
    service=tmp_path/'private-service.conf'
    service.write_text('[synthetic]\nhost='+str(endpoint)+'\nport=65431\ndbname=synthetic\nuser=synthetic\npassword=synthetic\nsslmode=disable\nigreja12_required_unknown_policy=must-reject\n')
    service.chmod(0o600);monkeypatch.setenv('PGSERVICEFILE',str(service))
    with pytest.raises(psycopg2.OperationalError) as error:
        psycopg2.connect(service='synthetic',connect_timeout=1)
    message=str(error.value)
    assert 'service file' in message or 'connection option' in message
    assert list(endpoint.iterdir())==[]
