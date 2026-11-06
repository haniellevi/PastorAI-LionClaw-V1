"""Real Unix sockets, peer credentials and sealed CA; no TCP or database."""
from dataclasses import asdict
import importlib.util
import json
import os
from pathlib import Path
import selectors
import socket
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_first_transition_native_candidate_ca import rig  # noqa: F401


@pytest.fixture
def tmp_path():
    # AF_UNIX has a 107-byte pathname budget on Linux. Keep these owned
    # fixtures independent of pytest's potentially long --basetemp/test names.
    with TemporaryDirectory(prefix='i12-adm-',dir='/tmp') as root:
        yield Path(root)


def admission():
    path=Path(__file__).resolve().parents[1]/'first_transition_native_candidate_admission.py'
    assert path.exists(),'pre-app admission barrier is not implemented'
    spec=importlib.util.spec_from_file_location('candidate_admission_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_no_client_times_out_without_starting_app_and_removes_owned_socket(rig,tmp_path):
    module=admission();module.SOCKET_PATH=str(tmp_path/'admission.sock')
    with rig.custody:
        with pytest.raises(module.Refused):module.serve_admission(rig.custody,timeout=.05)
    assert not (tmp_path/'admission.sock').exists()


def test_foreign_socket_is_never_adopted_or_removed(rig,tmp_path):
    module=admission();path=tmp_path/'foreign.sock';module.SOCKET_PATH=str(path)
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as foreign:
        foreign.bind(str(path));inode=path.stat().st_ino
        with rig.custody:
            with pytest.raises(module.Refused):module.serve_admission(rig.custody,timeout=.05)
        assert path.stat().st_ino==inode


SERVER = """import importlib.util,json,sys,os
p=sys.argv[1]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path)
 m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
a=load('admission_server',p)
a.SOCKET_PATH=sys.argv[2]
c=load('ca_server',os.path.join(os.path.dirname(p),'first_transition_native_candidate_ca.py'))
profile=c.CandidateCAProfile.from_dict(json.loads(sys.argv[3]))
try:
 with c.NativeCandidateCA(profile,sys.argv[4]) as owned:
  mode=sys.argv[5] if len(sys.argv)>5 else ''
  original=a._send
  replacements=[]
  def send(sock,value,deadline):
   if mode=='spoof' and value.get('schema')==a.HELLO:
    value={**value,'marker':{**value['marker'],'pid':os.getppid()}}
   original(sock,value,deadline)
   if value.get('schema')==a.HELLO:
    if mode=='fd-loss':os.close(owned._sealed)
    if mode=='replacement':
     import socket
     os.unlink(a.SOCKET_PATH)
     foreign=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);foreign.bind(a.SOCKET_PATH);replacements.append(foreign)
  a._send=send
  print('ready',flush=True)
  try:
   a.serve_admission(owned,timeout=2)
   print('admitted',flush=True)
  except a.Refused:print('refused',flush=True)
except c.Refused:print('custody-refused',flush=True)
"""


def start_server(rig,tmp_path,mode=''):
    module=admission();path=tmp_path/'barrier.sock';module.SOCKET_PATH=str(path)
    profile=asdict(rig.profile)
    # Public profile only; no credentials in args/environment.
    process=subprocess.Popen((sys.executable,'-I','-c',SERVER,str(Path(module.__file__).resolve()),
        str(path),json.dumps(profile),module.profile_digest(profile),mode),
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,close_fds=True,
        env={'PATH':'/usr/bin:/bin','LC_ALL':'C','PYTHONDONTWRITEBYTECODE':'1'})
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout,selectors.EVENT_READ)
        assert selector.select(5),'own server did not start'
    assert process.stdout.readline()==b'ready\n'
    # Fixture setup waits for its own socket; the production client never retries.
    import time
    deadline=time.monotonic()+2
    while not path.exists():
        assert process.poll() is None and time.monotonic()<deadline
        time.sleep(.005)
    return module,process,path,profile


def stop(process):
    if process.poll() is None:process.kill()
    process.wait(timeout=5)


def test_matching_peer_and_real_fd_observation_acknowledge_one_process(rig,tmp_path):
    module,process,path,profile=start_server(rig,tmp_path)
    try:
        result=module.acknowledge_candidate(profile,module.profile_digest(profile),
            expected_main_pid=process.pid,expected_uid=os.geteuid(),timeout=1)
        assert result['schema']=='igreja12.native-candidate-admission/1' and result['pid']==process.pid
        assert result['ca_sha256']==profile['ca_sha256'] and result['peer_uid']==os.geteuid()
        assert set(result)=={'schema','request_digest','context_digest','profile_sha256','ca_sha256','pid',
            'process_start_ticks','fd','device','inode','size','seals','peer_uid'}
        out,err=process.communicate(timeout=5)
        assert out==b'admitted\n' and err==b'' and process.returncode==0
        assert not path.exists()
    finally:stop(process)


@pytest.mark.parametrize('fault',['request','context','profile','marker','extra','trailing','duplicate','oversize'])
def test_each_ack_binding_or_framing_error_prevents_admission(rig,tmp_path,fault):
    module,process,path,_=start_server(rig,tmp_path)
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
            client.settimeout(1);client.connect(str(path))
            length=struct.unpack('!I',client.recv(4))[0]
            hello=b''
            while len(hello)<length:hello+=client.recv(length-len(hello))
            marker=json.loads(hello)['marker']
            import hashlib
            sha=hashlib.sha256(json.dumps(marker,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            ack=dict(schema='igreja12.candidate-admission-ack/1',request_digest=marker['request_digest'],
                context_digest=marker['context_digest'],profile_sha256=marker['profile_sha256'],marker_sha256=sha)
            if fault in ('request','context','profile','marker'):
                ack[{'request':'request_digest','context':'context_digest','profile':'profile_sha256',
                     'marker':'marker_sha256'}[fault]]='f'*64
            if fault=='extra':ack['allowed']=True
            body=json.dumps(ack).encode()
            if fault=='duplicate':body=body[:-1]+b',"schema":"igreja12.candidate-admission-ack/1"}'
            if fault=='oversize':body=b' '*8193
            try:
                client.sendall(struct.pack('!I',len(body))+body+(b'X' if fault=='trailing' else b''))
                client.shutdown(socket.SHUT_WR)
            except BrokenPipeError:pass
        out,err=process.communicate(timeout=5)
        assert out==b'refused\n' and err==b'' and not path.exists()
    finally:stop(process)


@pytest.mark.parametrize('mode',['fd-loss','replacement','spoof'])
def test_live_fd_loss_foreign_replacement_and_json_pid_spoof_never_admit(rig,tmp_path,mode):
    module,process,path,profile=start_server(rig,tmp_path,mode)
    try:
        with pytest.raises(module.Refused):
            module.acknowledge_candidate(profile,module.profile_digest(profile),
                expected_main_pid=os.getpid() if mode=='spoof' else process.pid,
                expected_uid=os.geteuid(),timeout=1)
        out,err=process.communicate(timeout=5)
        assert b'admitted' not in out and b'refused' in out and err==b''
        if mode=='replacement':
            assert path.exists()  # server did not unlink a foreign inode
            path.unlink()  # only this fixture created it
        else:assert not path.exists()
    finally:stop(process)


@pytest.mark.parametrize('timeout',[0,-1,True,float('nan'),float('inf'),30.01])
def test_invalid_budget_refuses_before_creating_socket(rig,tmp_path,timeout):
    module=admission();path=tmp_path/'budget.sock';module.SOCKET_PATH=str(path)
    with rig.custody:
        with pytest.raises(module.Refused):module.serve_admission(rig.custody,timeout=timeout)
    assert not path.exists()



def test_profile_loader_returns_checked_public_profile_and_rejects_symlink(rig,tmp_path):
    module=admission()
    assert callable(getattr(module,'load_profile',None)),'strict public profile loader is missing'
    path=tmp_path/'profile.json';path.write_text(json.dumps(asdict(rig.profile)));path.chmod(0o400)
    profile=module.load_profile(path)
    assert profile.host=='source.synthetic.invalid' and profile.hostaddr=='192.0.2.10'
    alias=tmp_path/'profile-link.json';alias.symlink_to(path)
    with pytest.raises(module.Refused):module.load_profile(alias)


@pytest.mark.parametrize('fault',['duplicates','oversize','writable','directory','fifo','parent-symlink'])
def test_invalid_profile_is_refused_without_socket_or_app(rig,tmp_path,fault):
    module=admission()
    assert callable(getattr(module,'load_profile',None)),'strict public profile loader is missing'
    path=tmp_path/'profile.json';raw=json.dumps(asdict(rig.profile))
    if fault=='duplicates':raw=raw[:-1]+',"host":"source.synthetic.invalid"}'
    if fault=='oversize':raw=' '*16385
    if fault=='directory':path.mkdir()
    elif fault=='fifo':os.mkfifo(path)
    elif fault=='parent-symlink':
        actual=tmp_path/'real';actual.mkdir();(actual/'profile.json').write_text(raw)
        (tmp_path/'alias').symlink_to(actual,target_is_directory=True);path=tmp_path/'alias'/'profile.json'
    else:path.write_text(raw);path.chmod(0o666 if fault=='writable' else 0o400)
    with pytest.raises(module.Refused):module.load_profile(path)



def test_bootstrap_does_not_import_app_before_kernel_verified_ack(rig,tmp_path):
    module=admission()
    assert not os.path.lexists(module.SOCKET_PATH),'foreign fixed admission socket exists'
    profile=tmp_path/'profile.json';profile.write_text(json.dumps(asdict(rig.profile)));profile.chmod(0o600)
    script="""import importlib.util,sys,types
spec=importlib.util.spec_from_file_location('bootstrap_fixture',sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
u=types.ModuleType('uvicorn')
def run(*a,**kw):print('APP_STARTED',flush=True)
u.run=run;sys.modules['uvicorn']=u
m.main(['--profile',sys.argv[2],'--expect-profile-sha256',sys.argv[3]])
"""
    process=subprocess.Popen((sys.executable,'-I','-c',script,
        str(Path(module.__file__).with_name('first_transition_native_candidate_bootstrap.py')),
        str(profile),module.profile_digest(asdict(rig.profile))),stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,env={'PATH':'/usr/bin:/bin','LC_ALL':'C','PYTHONDONTWRITEBYTECODE':'1'})
    try:
        import time
        deadline=time.monotonic()+2
        while not os.path.exists(module.SOCKET_PATH):
            assert process.poll() is None,'bootstrap started/finished app without admission barrier'
            assert time.monotonic()<deadline
            time.sleep(.005)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ)
            assert selector.select(.05)==[],'app imported before ACK'
        result=module.acknowledge_candidate(asdict(rig.profile),module.profile_digest(asdict(rig.profile)),
            expected_main_pid=process.pid,expected_uid=os.geteuid(),timeout=1)
        assert result['pid']==process.pid
        out,err=process.communicate(timeout=5)
        assert out==b'APP_STARTED\n' and err==b'' and process.returncode==0
        assert not os.path.exists(module.SOCKET_PATH)
    finally:stop(process)



@pytest.mark.parametrize('fault',['pid','uid','profile','context'])
def test_independent_identity_mismatch_never_admits_app(rig,tmp_path,fault):
    module,process,path,profile=start_server(rig,tmp_path)
    try:
        selected=dict(profile)
        if fault=='context':selected['context_digest']='f'*64
        expected=module.profile_digest(selected) if fault!='profile' else 'f'*64
        with pytest.raises(module.Refused):
            module.acknowledge_candidate(selected,expected,
                expected_main_pid=process.pid+(1 if fault=='pid' else 0),
                expected_uid=os.geteuid()+(1 if fault=='uid' else 0),timeout=.5)
        out,err=process.communicate(timeout=5)
        assert out==b'refused\n' and err==b''
    finally:stop(process)


def test_wrong_ack_is_not_authority_and_socket_is_cleaned(rig,tmp_path):
    module,process,path,_=start_server(rig,tmp_path)
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
            client.settimeout(1);client.connect(str(path))
            size=struct.unpack('!I',client.recv(4))[0]
            raw=b''
            while len(raw)<size:raw+=client.recv(size-len(raw))
            assert json.loads(raw)['marker']['pid']==process.pid
            body=b'{"allowed":true}'
            client.sendall(struct.pack('!I',len(body))+body);client.shutdown(socket.SHUT_WR)
        out,err=process.communicate(timeout=5)
        assert out==b'refused\n' and err==b'' and not path.exists()
    finally:stop(process)
