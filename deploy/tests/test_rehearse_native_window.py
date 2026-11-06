"""Rehearsal provenance and cleanup refusal without any real network/process."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import rehearse_native_window as rehearsal
from initial_transition_ops import Refused


@pytest.fixture
def source(monkeypatch):
    nonce = 'a'*32
    cid,nid = 'b'*64,'c'*64
    name = 'igreja12-native-source-'+nonce
    root = '/synthetic/native-only'
    data = dict(source_descriptor=dict(root=root,nonce=nonce,network=nid,container=cid,daemon='synthetic-daemon',
        name=name,address='172.30.0.2',started='2026-11-06T05:00:00Z'),daemon='synthetic-daemon',
        config=dict(docker_binary='/usr/bin/docker',docker_endpoint='unix:///var/run/docker.sock',
            docker_config_dir=root+'/docker',backup_root=root+'/artifacts',clone_workdir=root+'/replay',
            clone_image=rehearsal.CLONE_IMAGE,dump_image=rehearsal.CLONE_IMAGE),
        policy=dict(host=rehearsal.HOST,hostaddr='172.30.0.2',port=5432,ca_file=root+'/tls/server.crt',
            ca_owner=rehearsal.os.geteuid()))
    network = [nid,name,True,'bridge',{rehearsal.LABEL:nonce},{cid:{}}]
    mounts = [dict(Destination='/var/lib/postgresql/data',Type='tmpfs'),dict(Destination='/tmp',Type='tmpfs'),
        dict(Destination='/synthetic-tls',Type='bind',Source=root+'/tls',RW=False)]
    container = [cid,rehearsal.SOURCE_IMAGE,['sh'],['-c',rehearsal.START],{rehearsal.LABEL:nonce},True,
        data['source_descriptor']['started'],None,{name:dict(NetworkID=nid,IPAddress='172.30.0.2')},mounts,False,
        {'/tmp':'rw,nosuid,nodev,noexec,size=33554432','/var/lib/postgresql/data':'rw,nosuid,nodev,noexec,size=536870912'}]
    calls = []
    def run(argv,**kwargs):
        calls.append(argv)
        assert argv[:5] == ('/usr/bin/docker','--config',root+'/docker','--host','unix:///var/run/docker.sock')
        assert kwargs['stdin'] == rehearsal.subprocess.DEVNULL and kwargs['timeout'] == 10
        if argv[5] == 'info':value = 'synthetic-daemon'
        elif argv[5:7] == ('network','inspect'):
            assert argv[-1] == nid;value = network
        elif argv[5] == 'inspect':
            assert argv[-1] == cid;value = container
        else:pytest.fail('mutating or unexpected Docker operation')
        return SimpleNamespace(returncode=0,stdout=json.dumps(value).encode())
    monkeypatch.setattr(rehearsal.subprocess,'run',run)
    import psycopg2
    monkeypatch.setattr(psycopg2,'connect',lambda *_a,**_k:pytest.fail('provenance must precede source login'))
    return data,network,container,calls


def test_worker_source_requires_actual_owned_synthetic_container_before_login(source):
    data,_,_,calls = source
    rehearsal.verify_worker_source(data)
    assert len(calls) == 3


def test_worker_proves_exact_tmpfs_even_when_mounts_omits_them(source):
    data,_,container,_ = source
    container[9] = [container[9][2]]
    rehearsal.verify_worker_source(data)


def test_worker_refuses_mutable_input_before_any_docker_or_login(source,monkeypatch):
    _,_,_,calls = source
    fd = rehearsal.os.memfd_create('synthetic-unsealed-input',rehearsal.os.MFD_ALLOW_SEALING)
    try:
        rehearsal.os.write(fd,b'{}')
        monkeypatch.setenv('IGREJA12_NATIVE_INPUT_FD',str(fd))
        with pytest.raises(Refused,match='^physical-worker-input$'):
            rehearsal.worker()
        assert calls == []
    finally:
        rehearsal.os.close(fd)


@pytest.mark.parametrize('fault',[
    'remote-ip','remote-host','remote-ca','remote-daemon','docker-endpoint','backup-root','source-image',
    'command','entrypoint','source-label','source-start','ports','privileged','network-id','extra-network',
    'non-internal','other-member','network-label','data-bind','tls-writable','extra-mount','integer-running',
    'tmpfs-flags','extra-tmpfs','missing-tmpfs',
])
def test_worker_cannot_retarget_sealed_input_to_another_source(source,fault):
    data,network,c,calls = source
    if fault == 'remote-ip':data['policy']['hostaddr'] = '203.0.113.20'
    elif fault == 'remote-host':data['policy']['host'] = 'real.invalid'
    elif fault == 'remote-ca':data['policy']['ca_file'] = '/outside/real-ca.crt'
    elif fault == 'remote-daemon':data['daemon'] = 'other'
    elif fault == 'docker-endpoint':data['config']['docker_endpoint'] = 'tcp://203.0.113.20:2375'
    elif fault == 'backup-root':data['config']['backup_root'] = '/outside/artifacts'
    elif fault == 'source-image':c[1] = rehearsal.CLONE_IMAGE
    elif fault == 'command':c[3] = ['-c','postgres -D /existing']
    elif fault == 'entrypoint':c[2] = ['postgres']
    elif fault == 'source-label':c[4][rehearsal.LABEL] = 'other'
    elif fault == 'source-start':c[6] = '2026-11-06T06:00:00Z'
    elif fault == 'ports':c[7] = {'5432/tcp':[{'HostPort':'5432'}]}
    elif fault == 'privileged':c[10] = True
    elif fault == 'network-id':next(iter(c[8].values()))['NetworkID'] = 'd'*64
    elif fault == 'extra-network':c[8]['other'] = {}
    elif fault == 'non-internal':network[2] = False
    elif fault == 'other-member':network[5]['e'*64] = {}
    elif fault == 'network-label':network[4][rehearsal.LABEL] = 'other'
    elif fault == 'data-bind':c[9][0]['Type'] = 'bind'
    elif fault == 'tls-writable':c[9][2]['RW'] = True
    elif fault == 'extra-mount':c[9].append(deepcopy(c[9][0]))
    elif fault == 'integer-running':c[5] = 1
    elif fault == 'tmpfs-flags':c[11]['/var/lib/postgresql/data'] = 'rw,exec'
    elif fault == 'extra-tmpfs':c[11]['/other'] = 'rw'
    elif fault == 'missing-tmpfs':c[11] = {}
    with pytest.raises(Refused,match='^physical-worker-(source|config|network|container|mounts|policy)$'):
        rehearsal.verify_worker_source(data)
    assert len(calls) <= 3


def test_parent_cleanup_reuses_id_and_label_guarded_clone_cleanup(tmp_path,monkeypatch):
    source = rehearsal.SyntheticSource(tmp_path)
    request = '1'*64;network='2'*64;container='3'*64;token='4'*32
    before = dict(containers=[container],networks=[network]);after = dict(containers=[],networks=[])
    results = iter([before,after])
    source.daemon = 'synthetic-daemon'
    monkeypatch.setattr(source,'job_resources',lambda value:next(results) if value == request else pytest.fail('wrong request'))
    def call(*args,**kwargs):
        if args[:2] == ('network','inspect'):
            assert args[-1] == network
            return json.dumps(['igreja12-native-'+request[:12]+'-'+token[:12],token])
        assert args[:2] == ('image','inspect') and args[-1] == rehearsal.CLONE_IMAGE
        return json.dumps('sha256:'+'5'*64)
    monkeypatch.setattr(source,'call',call)
    seen = []
    class Clone:
        def __init__(self,*args,**kwargs):
            assert args[3:5] == (request,'synthetic-daemon')
        def close(self):
            seen.append((self.network,self.container,self.token,self.image))
    monkeypatch.setattr(rehearsal,'OwnedClone',Clone)
    source.cleanup_job(request,object(),object(),object())
    assert seen == [(network,container,token,'sha256:'+'5'*64)]


def test_parent_refuses_cleanup_of_container_without_owned_network(tmp_path,monkeypatch):
    source = rehearsal.SyntheticSource(tmp_path)
    monkeypatch.setattr(source,'job_resources',lambda _:dict(containers=['c'*64],networks=[]))
    monkeypatch.setattr(rehearsal,'OwnedClone',lambda *_a,**_k:pytest.fail('must not remove ambiguous resource'))
    with pytest.raises(Refused,match='^physical-job-cleanup-pending$'):
        source.cleanup_job('d'*64,object(),object(),object())


@pytest.fixture
def client(monkeypatch):
    descriptor=dict(root='/synthetic/private',nonce='a'*32,network='b'*64,container='c'*64,
        daemon='synthetic-daemon',name='synthetic-network')
    request='d'*64;cid='e'*64
    value=rehearsal.NativeClient(descriptor,request)
    row=[cid,rehearsal.CLIENT_IMAGE,{rehearsal.CLIENT_LABEL:request,rehearsal.LABEL:descriptor['nonce']},
        descriptor['network'],None,[dict(Type='bind',Source=descriptor['root']+'/tls/server.crt',
            Destination=rehearsal.CANDIDATE_CA,RW=False)],['python'],['-I','-c',rehearsal.CLIENT_WAIT],
        {descriptor['name']:dict(NetworkID=descriptor['network'],IPAddress='172.30.0.3')}]
    calls=[]
    def call(*args,**kwargs):
        calls.append(args)
        if args[0]=='info':return json.dumps(descriptor['daemon'])
        assert args[0]=='inspect' and args[-1]==cid
        return json.dumps(row)
    monkeypatch.setattr(value,'call',call)
    return value,row,calls


def test_physical_client_identity_is_the_new_isolated_sleep_process(client):
    value,row,calls=client
    assert value.owned(row[0])==row
    assert len(calls)==2


@pytest.mark.parametrize('fault',['image','label','nonce','network','entrypoint','command','ports',
    'ca-source','ca-target','ca-writable','extra-mount','extra-network','network-id'])
def test_physical_client_refuses_unrelated_or_unisolated_container(client,fault):
    value,row,_=client
    if fault=='image':row[1]=rehearsal.SOURCE_IMAGE
    elif fault=='label':row[2][rehearsal.CLIENT_LABEL]='0'*64
    elif fault=='nonce':row[2][rehearsal.LABEL]='0'*32
    elif fault=='network':row[3]='0'*64
    elif fault=='entrypoint':row[6]=['uvicorn']
    elif fault=='command':row[7]=['main:app']
    elif fault=='ports':row[4]={'8000/tcp':[dict(HostPort='8000')]}
    elif fault=='ca-source':row[5][0]['Source']='/outside/ca.crt'
    elif fault=='ca-target':row[5][0]['Destination']='/other/ca.crt'
    elif fault=='ca-writable':row[5][0]['RW']=True
    elif fault=='extra-mount':row[5].append(deepcopy(row[5][0]))
    elif fault=='extra-network':row[8]['other']={}
    elif fault=='network-id':row[8][value.source['name']]['NetworkID']='0'*64
    with pytest.raises(Refused,match='^physical-client-(owner|isolation)$'):
        value.owned(row[0])


def test_client_cleanup_requires_fresh_ownership_before_any_mutation(client):
    value,row,calls=client
    row[2][rehearsal.CLIENT_LABEL]='wrong'
    with pytest.raises(Refused,match='^physical-client-owner$'):
        value.remove(row[0])
    assert all(args[0] in ('info','inspect') for args in calls)
