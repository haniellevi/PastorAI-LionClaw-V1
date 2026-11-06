"""Runtime mount/entrypoint/PID admission on controlled Docker projections."""
from dataclasses import asdict,replace
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from first_transition_adapter import digest
from first_transition_native_candidate_ca import CandidateCAProfile
from initial_transition_ops import Refused
from test_first_transition_native_transports import bundle,rig,plan  # noqa: F401
from test_first_transition_orchestrator import world,pinned,no_real_processes_or_network  # noqa: F401


def module():
    assert importlib.util.find_spec('first_transition_native_candidate_runtime') is not None, 'native runtime integration missing'
    return importlib.import_module('first_transition_native_candidate_runtime')


@pytest.fixture
def runtime(bundle,world,tmp_path):
    m=module()
    spec=replace(world.spec,native_ca_override=str(tmp_path/'runtime-override.json'))
    root=tmp_path/'public-bundle';root.mkdir(mode=0o700)
    Path(bundle.policy.ca_file).chmod(0o644)
    request='7'*64
    profile=CandidateCAProfile(request,digest(bundle.context),bundle.policy.host,bundle.policy.hostaddr,
        bundle.policy.port,'/run/igreja12/native-ca.crt',bundle.policy.ca_sha256,bundle.policy.ca_owner,bundle.expected.identity)
    names=('first_transition_native_candidate_admission.py','first_transition_native_candidate_bootstrap.py',
           'first_transition_native_candidate_ca.py')
    pins=m.NativeCandidateRuntimePins(digest(asdict(profile)),digest(asdict(spec)),
        tuple((n,hashlib.sha256((Path(__file__).resolve().parents[1]/n).read_bytes()).hexdigest()) for n in names),10001)
    return m.NativeCandidateRuntime(spec=spec,transports=bundle,request_digest=request,root=str(root),pins=pins,owner=os.geteuid())


def test_public_bundle_preserves_pins_and_mounts_before_any_start(runtime):
    runtime.prepare()
    data=json.loads(runtime.override())['services']['backend']
    assert data['entrypoint']==['/usr/local/bin/python','-I','/run/igreja12/native-runtime/first_transition_native_candidate_bootstrap.py']
    assert data['command']==['--profile','/run/igreja12/native-runtime/profile.json','--expect-profile-sha256',runtime.pins.profile_sha256]
    assert len(data['volumes'])==2 and all(v['read_only'] for v in data['volumes'])
    assert set(p.name for p in runtime.directory.iterdir())=={'profile.json','first_transition_native_candidate_admission.py',
        'first_transition_native_candidate_bootstrap.py','first_transition_native_candidate_ca.py'}
    assert all(p.stat().st_mode&0o777==0o444 for p in runtime.directory.iterdir())
    assert runtime.directory.stat().st_mode&0o777==0o755
    assert 'SYNTHETIC-PRIVATE' not in runtime.override().decode()
    runtime.close()


@pytest.mark.parametrize('fault',['hash','symlink','hardlink','mode','directory'])
def test_bundle_drift_refuses_before_docker_or_ack(runtime,fault):
    runtime.prepare()
    file=runtime.directory/'profile.json'
    if fault=='hash':file.chmod(0o600);file.write_bytes(b'{}');file.chmod(0o444)
    elif fault=='mode':file.chmod(0o644)
    elif fault=='hardlink':os.link(file,runtime.directory/'alias')
    elif fault=='directory':runtime.directory.rename(runtime.directory.with_name('saved'));runtime.directory.mkdir(mode=0o755)
    else:
        file.rename(file.with_name('saved.json'));file.symlink_to('saved.json')
    calls=[]
    with pytest.raises(Refused):runtime.pre_start('a'*64,runner=lambda *a,**k:calls.append(a),timeout=5)
    assert calls==[]
    runtime.close()


def projection(runtime,*,running=False):
    return dict(id='a'*64,image=runtime.spec.image,configured_image=runtime.spec.image,
        entrypoint=['/usr/local/bin/python','-I','/run/igreja12/native-runtime/first_transition_native_candidate_bootstrap.py'],
        command=['--profile','/run/igreja12/native-runtime/profile.json','--expect-profile-sha256',runtime.pins.profile_sha256],
        user='appuser',privileged=False,pid_mode='',restart_policy='no',pid=23456 if running else 0,
        started='2026-11-06T03:00:00Z' if running else '0001-01-01T00:00:00Z',running=running,restarts=0,
        mounts=[['bind',runtime.transports.policy.ca_file,'/run/igreja12/native-ca.crt',False],
                ['bind',str(runtime.directory),'/run/igreja12/native-runtime',False]],
        project=runtime.spec.project,service='backend',name='/'+runtime.spec.names()['backend'],
        network_mode=runtime.spec.network_name,networks=[[runtime.spec.network_name,runtime.spec.network_id]],
        path='/usr/local/bin/python',args=['-I','/run/igreja12/native-runtime/first_transition_native_candidate_bootstrap.py',
            '--profile','/run/igreja12/native-runtime/profile.json','--expect-profile-sha256',runtime.pins.profile_sha256],
        revision=runtime.spec.sha)


class Docker:
    def __init__(self,runtime,cid='a'*64):
        self.runtime=runtime;self.row=projection(runtime);self.row['id']=cid;self.cid=cid;self.calls=[];self.ack=None
    def __call__(self,argv,**kwargs):
        self.calls.append(argv)
        from first_transition_host_driver import INFO_ARGV
        if argv==INFO_ARGV:return 0,json.dumps(self.runtime.spec.daemon_id).encode()
        if argv==self.runtime.spec.network_argv():
            return 0,(json.dumps([self.runtime.spec.network_id,self.runtime.spec.network_name])+'\n').encode()*2
        if argv==self.runtime.inspect_argv(self.cid):return 0,json.dumps(self.row).encode()
        if argv==self.runtime.admission_argv(self.cid):return 0,json.dumps(self.ack).encode()
        if self.runtime._receipt is not None and argv==self.runtime.observe_argv(self.cid):
            keys=('pid','process_start_ticks','device','inode','size','seals','ca_sha256')
            return 0,json.dumps({k:self.ack[k] for k in keys}).encode()
        if argv==self.runtime.stop_argv(self.cid):
            self.row['running']=False;self.row['pid']=0
            return 0,(self.cid+'\n').encode()
        raise AssertionError('unallowed projection')


@pytest.mark.parametrize('key,value',[('entrypoint',['uvicorn']),('command',[]),('privileged',True),
    ('pid',True),('image','sha256:'+'f'*64),('project','foreign'),('mounts',[]),('path','sh'),('user','root')])
def test_foreign_mount_entrypoint_identity_or_pid_refuses_before_start(runtime,key,value):
    runtime.prepare();docker=Docker(runtime);docker.row[key]=value
    with pytest.raises(Refused):runtime.pre_start('a'*64,runner=docker,timeout=5)
    assert docker.calls[-1]==runtime.inspect_argv('a'*64) and runtime.admission_argv('a'*64) not in docker.calls
    runtime.close()


def test_live_admission_is_bound_to_actual_main_pid_start_and_kernel_fd(runtime):
    runtime.prepare();docker=Docker(runtime)
    runtime.pre_start('a'*64,runner=docker,timeout=5)
    docker.row=projection(runtime,running=True)
    docker.ack=dict(schema='igreja12.native-candidate-admission/1',request_digest=runtime.profile.request_digest,
        context_digest=runtime.profile.context_digest,profile_sha256=runtime.pins.profile_sha256,
        ca_sha256=runtime.profile.ca_sha256,pid=1,process_start_ticks=991,fd=7,device=1,inode=777,size=1212,seals=15,peer_uid=10001)
    proof=runtime.after_start('a'*64,runner=docker,timeout=10)
    assert proof['host_pid']==23456 and proof['container_id']=='a'*64
    assert proof['ca_lifecycle_admitted'] is True and proof['source_unchanged_proven'] is False
    assert runtime.observe_live('a'*64,runner=docker,timeout=10)['host_pid']==23456
    assert docker.calls[-1]==runtime.inspect_argv('a'*64)
    runtime.close()


@pytest.mark.parametrize('fault',['peer_pid','profile','fd','restart_during_ack'])
def test_bad_ack_or_restarted_main_process_never_yields_admission(runtime,fault):
    runtime.prepare();docker=Docker(runtime);runtime.pre_start('a'*64,runner=docker,timeout=5)
    docker.row=projection(runtime,running=True)
    docker.ack=dict(schema='igreja12.native-candidate-admission/1',request_digest=runtime.profile.request_digest,
        context_digest=runtime.profile.context_digest,profile_sha256=runtime.pins.profile_sha256,
        ca_sha256=runtime.profile.ca_sha256,pid=1,process_start_ticks=991,fd=7,device=1,inode=777,size=1212,seals=15,peer_uid=10001)
    if fault=='peer_pid':docker.ack['pid']=2
    elif fault=='profile':docker.ack['profile_sha256']='0'*64
    elif fault=='fd':docker.ack['fd']=True
    original=docker.__call__
    def call(argv,**kw):
        result=original(argv,**kw)
        if fault=='restart_during_ack' and argv==runtime.admission_argv('a'*64):docker.row['pid']+=1
        return result
    with pytest.raises(Refused):runtime.after_start('a'*64,runner=call,timeout=10)
    runtime.close()


def test_native_candidate_cannot_bypass_runtime_by_calling_start_directly(world,bundle,tmp_path):
    from first_transition_candidate import CandidatePort
    from test_first_transition_orchestrator import CANDIDATE_IDS
    world.cdocker(world.spec.compose_argv(),timeout=5,max_output=65536)
    spec=replace(world.spec,native_ca_override=str(tmp_path/'override.json'))
    port=CandidatePort(spec,runner=world.cdocker,source_transports=bundle)
    with pytest.raises(Refused):port.start_backend(CANDIDATE_IDS['backend'])
    assert world.cdocker.starts==0


def test_native_database_projection_is_in_runner_allowlist(runtime):
    from first_transition_candidate import CandidateRunner,NATIVE_DATABASE_TEMPLATE
    runner=CandidateRunner(runtime.spec,docker_binary='/usr/bin/docker',endpoint='unix:///var/run/docker.sock',config_dir='/tmp/synthetic-runtime-cli')
    assert runner._allowed(('docker','inspect','--type','container','--format',NATIVE_DATABASE_TEMPLATE,'a'*64))


@pytest.mark.parametrize('bad_ack',[False,True,'interrupt'])
def test_candidate_port_waits_for_live_admission_or_stops_own_backend(runtime,world,bad_ack):
    from first_transition_candidate import CandidatePort,NATIVE_DATABASE_TEMPLATE
    from test_first_transition_orchestrator import CANDIDATE_IDS
    runtime.prepare();runtime.transports.bind_candidate_runtime(runtime)
    cid=CANDIDATE_IDS['backend'];docker=Docker(runtime,cid)
    world.cdocker(world.spec.compose_argv(),timeout=5,max_output=65536)
    docker.ack=dict(schema='igreja12.native-candidate-admission/1',request_digest=runtime.profile.request_digest,
        context_digest=runtime.profile.context_digest,profile_sha256=runtime.pins.profile_sha256,
        ca_sha256=runtime.profile.ca_sha256,pid=2 if bad_ack else 1,process_start_ticks=991,
        fd=7,device=1,inode=777,size=1212,seals=15,peer_uid=10001)
    def runner(argv,**kw):
        if argv[:6]==('docker','inspect','--type','container','--format',NATIVE_DATABASE_TEMPLATE):
            return 0,json.dumps([cid,['DATABASE_URL='+runtime.transports.candidate_uri(),None],
                runtime._mounts()+[None]]).encode()
        if argv in (runtime.inspect_argv(cid),runtime.admission_argv(cid),runtime.stop_argv(cid)) or \
                runtime._receipt is not None and argv==runtime.observe_argv(cid):
            if bad_ack=='interrupt' and argv==runtime.admission_argv(cid):raise KeyboardInterrupt('PRIVATE')
            return docker(argv,**kw)
        result=world.cdocker(argv,**kw)
        if argv==('docker','start',cid):
            docker.row=projection(runtime,running=True);docker.row['id']=cid
        return result
    port=CandidatePort(runtime.spec,runner=runner,source_transports=runtime.transports,database_secret=runtime.transports._secret)
    if bad_ack=='interrupt':
        with pytest.raises(KeyboardInterrupt) as error:port.start_backend(cid)
        assert str(error.value)=='' and docker.row['running'] is False
    elif bad_ack:
        with pytest.raises(Refused,match='runtime-start-failed'):port.start_backend(cid)
        assert runtime.stop_argv(cid) in docker.calls and docker.row['running'] is False
    else:
        result=port.start_backend(cid)
        assert result['ca_lifecycle_admitted'] and runtime.stop_argv(cid) not in docker.calls
    assert world.cdocker.starts==1
    runtime.close()


@pytest.mark.parametrize('fault',['spec','profile','pins','directory'])
def test_mutated_runtime_binding_refuses_before_docker(runtime,fault):
    runtime.prepare()
    if fault=='spec':runtime.spec=replace(runtime.spec,image='sha256:'+'f'*64)
    elif fault=='profile':runtime.profile=replace(runtime.profile,source_identity='0'*64)
    elif fault=='pins':runtime.pins=replace(runtime.pins,uid=0)
    else:runtime.directory=runtime.directory.with_name('other')
    calls=[]
    def runner(*a,**kw):calls.append(a);return 0,b'{}'
    with pytest.raises(Refused):runtime.pre_start('a'*64,runner=runner,timeout=5)
    assert calls==[]
    runtime.close()


def test_abort_accepts_fresh_already_exited_own_backend(runtime):
    runtime.prepare();docker=Docker(runtime);runtime.pre_start('a'*64,runner=docker,timeout=5)
    docker.row['started']='2026-11-06T03:00:00Z'
    runtime.abort('a'*64,runner=docker,timeout=5)
    assert runtime.stop_argv('a'*64) not in docker.calls
    runtime.close()


def test_stop_stdout_is_not_a_substitute_for_fresh_owned_pid_absence(runtime):
    runtime.prepare();docker=Docker(runtime);runtime.pre_start('a'*64,runner=docker,timeout=5)
    docker.row=projection(runtime,running=True)
    def runner(argv,**kw):
        result=docker(argv,**kw)
        return (0,b'') if argv==runtime.stop_argv('a'*64) else result
    runtime.abort('a'*64,runner=runner,timeout=5)
    assert docker.row['running'] is False and docker.calls[-1]==runtime.inspect_argv('a'*64)
    runtime.close()
