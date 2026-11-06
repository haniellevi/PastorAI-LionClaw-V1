"""Own memfds/fork/process custody; fake driver, no database/network."""
from contextlib import contextmanager
from dataclasses import asdict,replace
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import selectors
import socket
import subprocess
import sys
from types import ModuleType,SimpleNamespace

import psycopg2
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import first_transition_native_candidate_ca as ca

IDENTITY=['7300000000000000001',16384,'postgres']
PRIVATE='SYNTHETIC-PRIVATE-PASSWORD'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_a,**_k):pytest.fail('network forbidden')
    for name in ('socket','getaddrinfo','create_connection'):monkeypatch.setattr(socket,name,denied)
    for key in list(os.environ):
        if key.upper().startswith('PG'):monkeypatch.delenv(key)


class Cursor:
    def __init__(self,conn):self.conn=conn
    def __enter__(self):return self
    def __exit__(self,*_a):return False
    def execute(self,query):
        c=self.conn;c.queries.append(query)
        if query=='BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY':
            assert c.autocommit is True and c.info.transaction_status==0
            c.info.transaction_status=2
        elif query==ca.IDENTITY_SQL:assert c.info.transaction_status==2
        elif query=='ROLLBACK':
            if c.driver.fault=='probe-rollback':raise RuntimeError(PRIVATE)
            c.info.transaction_status=0
        else:pytest.fail('unreviewed SQL')
    def fetchall(self):
        row=[*IDENTITY,'postgres','postgres','on','repeatable read','off','on']
        fault=self.conn.driver.fault
        if fault=='identity':row[0]='7400000000000000001'
        if fault=='role':row[3]='other'
        if fault=='startup':row[-1]='off'
        if fault=='shape':row.append('extra')
        return [tuple(row)]


class Connection:
    def __init__(self,driver,params):
        self.driver=driver;self.closed=0;self.autocommit=False;self.queries=[];self.rollbacks=0;self.closes=0
        self.info=SimpleNamespace(used_password=True,ssl_in_use=True,server_version=170006,
            transaction_status=0,dsn_parameters={k:v for k,v in params.items() if k!='password'},
            ssl_attribute=lambda _:'TLSv1.3')
        if driver.fault=='password':self.info.used_password=False
        if driver.fault=='tls':self.info.ssl_in_use=False
        if driver.fault=='protocol':self.info.ssl_attribute=lambda _:'TLSv1.1'
        if driver.fault=='version':self.info.server_version=170011
        if driver.fault=='route':self.info.dsn_parameters['hostaddr']='192.0.2.99'
        if driver.fault=='transaction':self.info.transaction_status=2
    def cursor(self):return Cursor(self)
    def rollback(self):
        self.rollbacks+=1
        if self.driver.fault=='rollback':raise RuntimeError(PRIVATE)
        self.info.transaction_status=0
    def close(self):
        self.closes+=1
        if self.driver.fault=='close':raise RuntimeError(PRIVATE)
        self.closed=1


class Driver:
    def __init__(self):self.calls=[];self.connections=[];self.fault=None;self.after=None
    def __call__(self,**params):
        self.calls.append(params)
        fd=int(params['sslrootcert'].rsplit('/',1)[1])
        assert fcntl.fcntl(fd,ca.GET_SEALS)&ca.SEALS==ca.SEALS
        if self.fault=='driver':raise RuntimeError(PRIVATE)
        conn=Connection(self,params);self.connections.append(conn)
        if self.after:self.after()
        return conn


@pytest.fixture
def rig(tmp_path,monkeypatch):
    path=tmp_path/'effective-ca.crt';path.write_bytes(b'SYNTHETIC PUBLIC CA');path.chmod(0o600)
    profile=ca.CandidateCAProfile('a'*64,'b'*64,'source.synthetic.invalid','192.0.2.10',5432,
        str(path),hashlib.sha256(path.read_bytes()).hexdigest(),os.geteuid(),ca.digest(IDENTITY))
    driver=Driver();monkeypatch.setattr(psycopg2,'connect',driver)
    params=dict(host=profile.host,hostaddr=profile.hostaddr,dbname='postgres',user='postgres',password=PRIVATE,
        sslmode='verify-full',sslrootcert=str(path),sslcertmode='disable',channel_binding='require',gssencmode='disable',
        ssl_min_protocol_version='TLSv1.2',connect_timeout=5,application_name='igreja12-native-candidate',options=ca.OPTIONS,
        keepalives=1,keepalives_idle=30,keepalives_interval=10,keepalives_count=3)
    value=SimpleNamespace(path=path,profile=profile,driver=driver,params=params,
        custody=ca.NativeCandidateCA(profile,ca.digest(asdict(profile))))
    yield value
    # Recover only fake close faults so irreversible at-fork registrations from
    # this test cannot poison unrelated later tests; no live driver is used.
    driver.fault=None
    for conn in driver.connections:
        if not conn.closed:conn.close()
    if value.custody._fork_state is not None:value.custody._fork_state['armed']=False


def observe(rig,marker):
    return ca.observe_candidate_ca(marker,expected_pid=marker['pid'],expected_profile_sha256=ca.digest(asdict(rig.profile)),
                                  expected_ca_sha256=rig.profile.ca_sha256)


@contextmanager
def refused_shutdown(custody):
    with pytest.raises(ca.Refused,match='native-candidate-ca-close'):
        with custody as owned:yield owned


def test_lifetime_sealed_ca_and_fresh_probed_connections(rig):
    with rig.custody as owned:
        marker=owned.marker();fd=marker['fd']
        actual=observe(rig,marker)
        assert actual['inode']==os.fstat(fd).st_ino and actual['seals']&15==15
        assert os.get_inheritable(fd) is False
        first=psycopg2.connect(**rig.params);second=psycopg2.connect(**rig.params)
        assert first is not second and not first.closed and not second.closed
        assert first.info.transaction_status==0 and first.autocommit is False
        assert first.queries==['BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY',ca.IDENTITY_SQL,'ROLLBACK']
        assert rig.driver.calls[0]['sslrootcert']==f'/proc/self/fd/{fd}'
        assert owned.marker()==marker
        first.close()
    assert second.closed and second.rollbacks==1
    with pytest.raises(OSError):os.fstat(fd)
    with pytest.raises(ca.Refused):psycopg2.connect(**rig.params)
    with pytest.raises(ca.Refused):observe(rig,marker)


def test_constructor_is_pure_and_profile_has_no_credential(rig,monkeypatch):
    monkeypatch.setattr(os,'open',lambda *_a,**_k:pytest.fail('constructor IO'))
    profile=ca.CandidateCAProfile.from_dict(asdict(rig.profile))
    assert ca.NativeCandidateCA(profile,ca.digest(asdict(profile)))
    assert PRIVATE not in json.dumps(asdict(profile)) and PRIVATE not in repr(rig.custody)
    with pytest.raises(ca.Refused):ca.NativeCandidateCA(profile,'f'*64)


@pytest.mark.parametrize('field,value',[('hostaddr','localhost'),('port',True),('ca_file','/tmp/../ca'),
    ('ca_owner',True),('user','dedicated'),('server_version',170011),('process_model','multiprocess')])
def test_invalid_public_profile_refuses(rig,field,value):
    profile=replace(rig.profile,**{field:value})
    with pytest.raises(ca.Refused):ca.NativeCandidateCA(profile,ca.digest(asdict(profile)))


@pytest.mark.parametrize('fault',['hash','symlink','directory','fifo','mode','owner','hardlink','empty','large'])
def test_invalid_effective_ca_refuses_before_any_driver(rig,fault,tmp_path):
    if fault=='hash':rig.path.write_bytes(b'WRONG CA')
    elif fault=='symlink':
        target=tmp_path/'target';rig.path.rename(target);rig.path.symlink_to(target)
    elif fault=='directory':rig.path.unlink();rig.path.mkdir()
    elif fault=='fifo':rig.path.unlink();os.mkfifo(rig.path)
    elif fault=='mode':rig.path.chmod(0o666)
    elif fault=='owner':
        profile=replace(rig.profile,ca_owner=os.geteuid()+1)
        rig.custody=ca.NativeCandidateCA(profile,ca.digest(asdict(profile)))
    elif fault=='hardlink':os.link(rig.path,tmp_path/'alias')
    elif fault=='empty':rig.path.write_bytes(b'')
    elif fault=='large':rig.path.write_bytes(b'X'*65537)
    with pytest.raises(ca.Refused):
        with rig.custody:pytest.fail('CA admitted')
    assert rig.driver.calls==[]


@pytest.mark.parametrize('fault',['replace','bytes','mode','parent-rename','memfd-close','source-fd-close','inheritable'])
def test_changed_custody_refuses_before_next_login(rig,fault,tmp_path):
    with refused_shutdown(rig.custody) as owned:
        if fault=='replace':
            rig.path.rename(tmp_path/'old-ca');rig.path.write_bytes(b'SYNTHETIC PUBLIC CA');rig.path.chmod(0o600)
        elif fault=='bytes':rig.path.write_bytes(b'WRONG CA')
        elif fault=='mode':rig.path.chmod(0o644)
        elif fault=='parent-rename':tmp_path.rename(tmp_path.with_name(tmp_path.name+'-moved'));tmp_path.mkdir()
        elif fault=='memfd-close':os.close(owned._sealed)
        elif fault=='source-fd-close':os.close(owned._source)
        elif fault=='inheritable':os.set_inheritable(owned._sealed,True)
        with pytest.raises(ca.Refused):psycopg2.connect(**rig.params)
        with pytest.raises(ca.Refused):owned.marker()
    assert rig.driver.calls==[]


def test_closed_fd_reused_for_different_sealed_memfd_is_rejected_and_not_closed_as_owned(rig):
    replacement=None
    try:
        with refused_shutdown(rig.custody) as owned:
            original=owned._sealed;os.close(original)
            replacement=os.memfd_create('unrelated',os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING)
            os.write(replacement,b'SYNTHETIC PUBLIC CA');fcntl.fcntl(replacement,ca.ADD_SEALS,ca.SEALS)
            if replacement!=original:os.dup2(replacement,original,inheritable=False)
            with pytest.raises(ca.Refused):psycopg2.connect(**rig.params)
        assert os.fstat(original)
        if original!=replacement:os.close(original)
    finally:
        if replacement is not None:os.close(replacement)


def test_failed_write_cannot_change_sealed_ca_and_conservatively_invalidates_metadata_pin(rig):
    with refused_shutdown(rig.custody) as owned:
        fd=owned.marker()['fd']
        with pytest.raises(OSError):os.pwrite(fd,b'X',0)
        assert hashlib.sha256(os.pread(fd,65537,0)).hexdigest()==rig.profile.ca_sha256
        # Linux updates timestamps even for the seal-refused write attempt.
        with pytest.raises(ca.Refused):psycopg2.connect(**rig.params)
    assert rig.driver.calls==[]


@pytest.mark.parametrize('field,value',[('hostaddr','192.0.2.99'),('ca_sha256','f'*64)])
def test_runtime_profile_mutation_refuses_before_driver(rig,field,value):
    with refused_shutdown(rig.custody) as owned:
        owned.profile=replace(rig.profile,**{field:value})
        with pytest.raises(ca.Refused):psycopg2.connect(**rig.params)
    assert rig.driver.calls==[]


def test_ambient_libpq_override_refuses_before_login(rig,monkeypatch):
    with refused_shutdown(rig.custody):
        monkeypatch.setenv('PGSERVICE','unbound')
        with pytest.raises(ca.Refused):psycopg2.connect(**rig.params)
    assert rig.driver.calls==[]


def test_app_import_before_enter_refuses(rig,monkeypatch):
    monkeypatch.setitem(sys.modules,'app.synthetic_prior_import',ModuleType('app.synthetic_prior_import'))
    with pytest.raises(ca.Refused):rig.custody.__enter__()
    assert rig.driver.calls==[]


@pytest.mark.parametrize('field,value',[('host','other.synthetic.invalid'),('hostaddr','192.0.2.99'),('port',6543),
    ('dbname','other'),('user','other'),('sslmode','require'),('sslrootcert','/other/ca'),('sslcertmode','allow'),
    ('channel_binding','prefer'),('gssencmode','prefer'),('ssl_min_protocol_version','TLSv1.1'),
    ('options','-c search_path=public'),('connect_timeout',10),('application_name','other'),('service','other'),
    ('connection_factory',object),('async_',True),('keepalives_idle',300),('password','')])
def test_wrong_first_conninfo_never_calls_driver_and_consumes_guard(rig,field,value):
    with refused_shutdown(rig.custody):
        with pytest.raises(ca.Refused):psycopg2.connect(**{**rig.params,field:value})
        with pytest.raises(ca.Refused):psycopg2.connect(**rig.params)
    assert rig.driver.calls==[]


def test_keyword_dsn_uses_same_strict_effective_parameter_contract(rig):
    with rig.custody:assert not psycopg2.connect(psycopg2.extensions.make_dsn(**rig.params)).closed


def test_credential_rotation_refuses_before_second_driver(rig):
    with refused_shutdown(rig.custody):
        psycopg2.connect(**rig.params)
        with pytest.raises(ca.Refused):psycopg2.connect(**{**rig.params,'password':'ROTATED-SYNTHETIC'})
    assert len(rig.driver.calls)==1


@pytest.mark.parametrize('fault',['password','tls','protocol','version','route','transaction','identity','role','startup','shape','driver','probe-rollback'])
def test_failed_authentication_or_identity_closes_connection_and_sanitizes(rig,fault,capsys):
    rig.driver.fault=fault
    with refused_shutdown(rig.custody):
        with pytest.raises(ca.Refused) as error:psycopg2.connect(**rig.params)
        assert PRIVATE not in str(error.value)
    assert all(conn.closed for conn in rig.driver.connections)
    if fault in ('password','tls','protocol','version','route','transaction'):
        assert all(conn.queries==[] for conn in rig.driver.connections)
    assert capsys.readouterr()==('','')


@pytest.mark.parametrize('fault',['rollback','close'])
def test_shutdown_failure_is_not_success_and_still_closes_ca(rig,fault):
    with pytest.raises(ca.Refused,match='native-candidate-ca-close'):
        with rig.custody as owned:
            fd=owned.marker()['fd'];psycopg2.connect(**rig.params);rig.driver.fault=fault
    with pytest.raises(OSError):os.fstat(fd)
    assert rig.driver.connections[0].rollbacks>=1 and rig.driver.connections[0].closes>=1


def test_fd_change_during_login_closes_just_opened_connection(rig):
    with refused_shutdown(rig.custody) as owned:
        rig.driver.after=lambda:os.close(owned._sealed)
        with pytest.raises(ca.Refused):psycopg2.connect(**rig.params)
        assert rig.driver.connections[0].closed


@pytest.mark.parametrize('failure',[OSError('PRIVATE'),KeyboardInterrupt('PRIVATE')])
def test_seal_failure_releases_fds_and_never_installs_guard(rig,monkeypatch,failure):
    original=fcntl.fcntl;created=[];memfd=os.memfd_create
    def opened(*args,**kwargs):
        value=memfd(*args,**kwargs);created.append(value);return value
    def broken(fd,command,*args):
        if command==ca.ADD_SEALS:raise failure
        return original(fd,command,*args)
    monkeypatch.setattr(os,'memfd_create',opened);monkeypatch.setattr(fcntl,'fcntl',broken)
    with pytest.raises(KeyboardInterrupt if isinstance(failure,KeyboardInterrupt) else ca.Refused) as error:
        with rig.custody:pytest.fail('unsealed CA admitted')
    assert 'PRIVATE' not in str(error.value) and psycopg2.connect is rig.driver
    for fd in created:
        with pytest.raises(OSError):os.fstat(fd)


def test_inherited_child_refuses_before_login_without_touching_parent_db(rig):
    with rig.custody as owned:
        conn=psycopg2.connect(**rig.params);marker=owned.marker()
        pid=os.fork()
        if pid==0:os._exit(99)  # the at-fork refusal must run before user code
        waited,status=os.waitpid(pid,0)
        assert waited==pid and os.waitstatus_to_exitcode(status)==ca.FORK_EXIT_CODE
        assert not conn.closed and len(rig.driver.calls)==1 and owned.marker()==marker


def test_atfork_never_finalizes_the_sole_inherited_handle(rig):
    parent=os.getpid();read_fd,write_fd=os.pipe()
    class SoleHandle:
        closed=0
        def rollback(self):pass
        def close(self):self.closed=1
        def __del__(self):
            if os.getpid()!=parent:os.write(write_fd,b'child-destructor')
    try:
        with rig.custody as owned:
            owned._connections.append(SoleHandle())  # deliberately no other owner
            pid=os.fork()
            if pid==0:
                owned.__exit__(None,None,None)
                os._exit(99)
            _,status=os.waitpid(pid,0)
            assert os.waitstatus_to_exitcode(status)==ca.FORK_EXIT_CODE
        os.close(write_fd);write_fd=None
        assert os.read(read_fd,1024)==b''
    finally:
        os.close(read_fd)
        if write_fd is not None:os.close(write_fd)


def test_closed_context_atfork_callback_does_not_kill_unrelated_future_child(rig):
    with rig.custody:psycopg2.connect(**rig.params)
    pid=os.fork()
    if pid==0:os._exit(0)  # no adoption, reconnect or inherited driver use
    _,status=os.waitpid(pid,0)
    assert os.waitstatus_to_exitcode(status)==0


@pytest.mark.parametrize('fault',['sealed-close','source-close','path-replace','path-bytes','profile'])
def test_final_exit_checks_custody_after_last_good_connection_without_another_probe(rig,fault,tmp_path):
    with pytest.raises(ca.Refused,match='native-candidate-ca-close'):
        with rig.custody as owned:
            conn=psycopg2.connect(**rig.params)
            if fault=='sealed-close':os.close(owned._sealed)
            elif fault=='source-close':os.close(owned._source)
            elif fault=='path-replace':
                rig.path.rename(tmp_path/'old');rig.path.write_bytes(b'SYNTHETIC PUBLIC CA')
            elif fault=='path-bytes':rig.path.write_bytes(b'CHANGED CA')
            elif fault=='profile':owned.profile=replace(rig.profile,hostaddr='192.0.2.99')
    assert conn.closed
    for fd in (owned._sealed,owned._source):
        with pytest.raises(OSError):os.fstat(fd)


def test_inherited_exit_fallback_without_atfork_also_skips_destructors_in_own_subprocess():
    script="""import importlib.util,sys,os
spec=importlib.util.spec_from_file_location('candidate_fallback',sys.argv[1])
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
parent=os.getpid();r,w=os.pipe()
class Sole:
 def __del__(self):
  if os.getpid()!=parent:os.write(w,b'BAD')
owned=object.__new__(m.NativeCandidateCA);owned._pid=parent;owned._connections=[Sole()]
pid=os.fork()
if pid==0:
 owned.__exit__(None,None,None)
 os._exit(99)
_,status=os.waitpid(pid,0);os.close(w)
assert os.waitstatus_to_exitcode(status)==78 and os.read(r,16)==b''
os.close(r)
"""
    result=subprocess.run((sys.executable,'-I','-c',script,str(Path(ca.__file__).resolve())),
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5,
        env={'PATH':'/usr/bin:/bin','LC_ALL':'C','PYTHONDONTWRITEBYTECODE':'1'},check=False)
    assert result.returncode==0 and result.stdout==b'' and result.stderr==b''


def test_live_process_marker_is_reprobed_through_proc(rig):
    script="""import importlib.util,json,sys,os
spec=importlib.util.spec_from_file_location('candidate_fixture',sys.argv[1])
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
p=m.CandidateCAProfile.from_dict(json.loads(sys.argv[2]))
with m.NativeCandidateCA(p,sys.argv[3]) as owned:
 print(json.dumps(owned.marker()),flush=True)
 os.read(0,1)
"""
    process=subprocess.Popen((sys.executable,'-I','-c',script,str(Path(ca.__file__).resolve()),json.dumps(asdict(rig.profile)),
        ca.digest(asdict(rig.profile))),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        env={'PATH':'/usr/bin:/bin','LC_ALL':'C','PYTHONDONTWRITEBYTECODE':'1'},close_fds=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ)
            assert selector.select(5),'own fixture did not emit marker'
        marker=json.loads(process.stdout.readline())
        assert marker['pid']==process.pid and observe(rig,marker)['ca_sha256']==rig.profile.ca_sha256
        with pytest.raises(ca.Refused):observe(rig,{**marker,'inode':marker['inode']+1})
        _,err=process.communicate(b'X',timeout=5)
        assert process.returncode==0 and err==b''
        with pytest.raises(ca.Refused):observe(rig,marker)
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=5)


def test_fixed_bootstrap_enters_guard_before_app_runtime_and_keeps_one_worker(rig,tmp_path,monkeypatch):
    monkeypatch.setattr(sys,'path',list(sys.path))
    spec=importlib.util.spec_from_file_location('candidate_bootstrap_fixture',
        Path(ca.__file__).with_name('first_transition_native_candidate_bootstrap.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    profile=tmp_path/'profile.json';profile.write_text(json.dumps(asdict(rig.profile)));profile.chmod(0o600)
    seen=[];uvicorn=ModuleType('uvicorn')
    original_spec=importlib.util.spec_from_file_location
    def admission_spec(name,path,*args,**kwargs):
        if str(path).endswith('first_transition_native_candidate_admission.py'):
            from importlib.machinery import ModuleSpec
            class Loader:
                def create_module(self,spec):return None
                def exec_module(self,value):
                    def admitted(custody,*,timeout):
                        assert custody.marker()['profile_sha256']==ca.digest(asdict(rig.profile))
                        seen.append('admitted')
                    value.serve_admission=admitted
            return ModuleSpec(name,Loader())
        return original_spec(name,path,*args,**kwargs)
    monkeypatch.setattr(importlib.util,'spec_from_file_location',admission_spec)
    def run(target,**kwargs):
        assert seen==['admitted']
        assert target=='app.main:app' and kwargs==dict(host='0.0.0.0',port=8000,workers=1,reload=False)
        assert sys.path[0]=='/app'
        assert psycopg2.connect is not rig.driver
        assert not psycopg2.connect(**rig.params).closed
        seen.append(True)
    uvicorn.run=run;monkeypatch.setitem(sys.modules,'uvicorn',uvicorn)
    assert module.main(['--profile',str(profile),'--expect-profile-sha256',ca.digest(asdict(rig.profile))])==0
    assert seen==['admitted',True] and rig.driver.connections[0].closed
