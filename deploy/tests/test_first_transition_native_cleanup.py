"""Owned Docker cleanup through a strict fake daemon boundary; no real process."""
from dataclasses import asdict,replace
import importlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from first_transition_adapter import digest
from initial_transition_ops import Refused


def module():
    path=Path(__file__).resolve().parents[1]/'first_transition_native_cleanup.py'
    assert path.exists(),'concrete parent-owned cleanup is missing'
    return importlib.import_module('first_transition_native_cleanup')


def test_concrete_owned_cleanup_is_available():
    assert callable(module().NativeDockerCleanup)


class Docker:
    def __init__(self,m,registry):
        self.m=m;self.registry=registry;self.calls=[];self.mutations=[];self.fault=None
        self.containers={c.container_id:dict(id=c.container_id,image=c.image_id,configured_image=c.image_reference,
            name='/'+c.name,labels=dict(registry.labels('container')),network_mode=registry.network_id,
            networks=[[registry.network_name,registry.network_id]],mounts=[],
            tmpfs=dict(c.tmpfs),ports={},privileged=False,publish_all_ports=False,pid_mode='',
            restart='no',running=True,pid=23456) for c in registry.containers}
        self.networks={} if registry.network_id is None else {registry.network_id:dict(id=registry.network_id,
            name=registry.network_name,internal=True,driver='bridge',labels=dict(registry.labels('network')),
            members=list(self.containers))}
    def __call__(self,argv,*,timeout,max_output):
        assert 0<timeout<=10 and max_output==65536
        self.calls.append(argv)
        if argv==('docker','info','--format','{{json .ID}}'):
            return 0,json.dumps('WRONG' if self.fault=='daemon' else self.registry.daemon_id).encode()
        if argv[:2]==('docker','ps') or argv[:3]==('docker','network','ls'):
            source=self.containers if argv[1]=='ps' else self.networks
            filters=[argv[i+1] for i,x in enumerate(argv[:-1]) if x=='--filter']
            assert filters and argv[-2:]==('--format','{{.ID}}')
            if filters[0].startswith('id='):
                selected=[i for i in source if i==filters[0][3:]]
            else:
                assert len(filters)==1 and filters[0].startswith('label=')
                key,want=filters[0][6:].split('=',1)
                selected=[i for i,row in source.items() if row['labels'].get(key)==want]
                if self.fault=='unknown' and argv[1]=='ps':selected.append('f'*64)
            return 0,('\n'.join(sorted(selected))+'\n' if selected else '').encode()
        if argv[:5]==('docker','inspect','--type','container','--format'):
            assert argv[5]==self.m.CONTAINER_VIEW
            return 0,json.dumps(self.containers[argv[-1]]).encode()
        if argv[:4]==('docker','network','inspect','--format'):
            assert argv[4]==self.m.NETWORK_VIEW
            return 0,json.dumps(self.networks[argv[-1]]).encode()
        if argv[:4]==('docker','rm','-f','-v'):
            assert len(argv)==5
            cid=argv[-1];self.mutations.append(argv)
            self.containers.pop(cid)
            for row in self.networks.values():
                if cid in row['members']:row['members'].remove(cid)
            return 0,b'arbitrary CLI output is not absence proof\n'
        if argv[:3]==('docker','network','rm'):
            assert len(argv)==4
            self.mutations.append(argv);self.networks.pop(argv[-1])
            return 0,b''
        raise AssertionError('unreviewed Docker argv')


@pytest.fixture
def rig(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess,'Popen',lambda *_a,**_k:pytest.fail('real CLI forbidden'))
    m=module();builder=m.NativeCleanupRegistry('a'*64,'b'*64,'synthetic-daemon')
    builder.created_network('1'*64)
    builder.created_container('2'*64,image_id='sha256:'+'3'*64)
    registry=builder.freeze();docker=Docker(m,registry)
    clock=lambda:100.0
    cleanup=m.NativeDockerCleanup(registry,docker_binary='/usr/bin/docker',endpoint='unix:///tmp/synthetic.sock',
        config_dir='/tmp/synthetic-private-config',runner=docker,clock=clock,wall_clock=lambda:10000.0)
    return m,builder,registry,docker,cleanup


def call(cleanup,**changes):
    return cleanup(request_digest='a'*64,context_digest='b'*64,result=None,status='worker-failed',
        deadline=130.0,worker_cleanup_uncertain=False,**changes)


def test_real_adapter_removes_only_registered_owned_ids_and_observes_absence(rig):
    m,builder,registry,docker,cleanup=rig
    observation=call(cleanup)
    assert docker.mutations==[('docker','rm','-f','-v','2'*64),('docker','network','rm','1'*64)]
    assert observation.inspected_resource_ids==observation.absent_resource_ids==('1'*64,'2'*64)
    evidence=cleanup.validate_observation(observation)
    assert evidence.observation_sha256==digest(asdict(observation))
    assert evidence.registry_digest==registry.digest and evidence.transport=='injected-boundary'
    assert evidence.source_unchanged_proven is evidence.a8_window_proven is evidence.production_ready is False
    assert evidence.cleanup_hard_deadline_verified is False
    assert not docker.containers and not docker.networks
    with pytest.raises(Refused):call(cleanup)


def test_worker_uncertainty_refuses_before_any_cli_or_delete(rig):
    _,_,_,docker,cleanup=rig
    with pytest.raises(Refused):
        cleanup(request_digest='a'*64,context_digest='b'*64,result=None,status='worker-failed',
            deadline=130,worker_cleanup_uncertain=True)
    assert docker.calls==[]


@pytest.mark.parametrize('fault',['daemon','unknown','image','labels','privileged','ports','mounts','tmpfs','internal','member'])
def test_foreign_or_unisolated_resources_refuse_before_first_delete(rig,fault):
    _,_,_,docker,cleanup=rig
    if fault in ('daemon','unknown'):docker.fault=fault
    elif fault=='internal':docker.networks['1'*64]['internal']=False
    elif fault=='member':docker.networks['1'*64]['members'].append('e'*64)
    elif fault=='image':docker.containers['2'*64]['image']='sha256:'+'f'*64
    elif fault=='labels':docker.containers['2'*64]['labels']={}
    elif fault=='privileged':docker.containers['2'*64]['privileged']=True
    elif fault=='ports':docker.containers['2'*64]['ports']={'5432/tcp':[{'HostPort':'5432'}]}
    elif fault=='mounts':docker.containers['2'*64]['mounts']=[['bind','/private','/data']]
    elif fault=='tmpfs':docker.containers['2'*64]['tmpfs']['/tmp']='rw'
    with pytest.raises(Refused):call(cleanup)
    assert docker.mutations==[]


def test_registry_is_frozen_before_worker_and_nonce_is_not_caller_input(rig):
    _,builder,registry,_,_=rig
    assert len(registry.nonce)==32
    with pytest.raises(Refused):builder.created_network('4'*64)
    with pytest.raises(Refused):builder.created_container('4'*64,image_id='sha256:'+'5'*64)
    with pytest.raises(TypeError):type(builder)('a'*64,'b'*64,'daemon',nonce='caller')


def test_result_ids_never_grant_delete_authority(rig):
    _,_,_,docker,cleanup=rig
    binding=dict(request_digest='a'*64,context_digest='b'*64,daemon_id='synthetic-daemon',
        container_id='f'*64,network_id='1'*64,image_id='sha256:'+'3'*64)
    with pytest.raises(Refused):
        cleanup(request_digest='a'*64,context_digest='b'*64,result=dict(binding=binding,binding_digest=digest(binding)),
            status='validated',deadline=130,worker_cleanup_uncertain=False)
    assert docker.mutations==[]


def test_already_absent_resources_need_no_mutation_but_fresh_inventory(rig):
    _,_,_,docker,cleanup=rig
    docker.containers={};docker.networks={}
    observation=call(cleanup)
    assert observation.absent_resource_ids==('1'*64,'2'*64)
    assert docker.calls and docker.mutations==[]


def test_forged_observation_does_not_validate_as_issued(rig):
    _,_,_,_,cleanup=rig
    value=call(cleanup)
    with pytest.raises(Refused):cleanup.validate_observation(replace(value,status='validated'))


def test_swapping_default_native_transport_for_fake_cannot_issue_native_daemon_evidence(rig):
    m,_,registry,docker,_=rig
    native=m.NativeDockerCleanup(registry,docker_binary='/usr/bin/docker',endpoint='unix:///tmp/synthetic.sock',
        config_dir='/tmp/synthetic-private-config',clock=lambda:100.0,wall_clock=lambda:10000.0)
    native._runner=docker
    with pytest.raises(Refused):call(native)
    assert docker.calls==[]


@pytest.mark.parametrize('deadline',[100,99,True,float('nan'),float('inf')])
def test_invalid_deadline_refuses_before_cli(rig,deadline):
    _,_,_,docker,cleanup=rig
    with pytest.raises(Refused):
        cleanup(request_digest='a'*64,context_digest='b'*64,result=None,status='worker-failed',
            deadline=deadline,worker_cleanup_uncertain=False)
    assert docker.calls==[]


def test_cli_uses_only_remaining_budget_and_late_mutation_never_claims_absence(rig):
    m,_,registry,docker,_=rig
    now=[100.0]
    original=docker.__call__
    def delayed(argv,**kwargs):
        assert kwargs['timeout']<=130-now[0]
        result=original(argv,**kwargs)
        if argv[:2]==('docker','rm'):now[0]=131
        return result
    cleanup=m.NativeDockerCleanup(registry,docker_binary='/usr/bin/docker',endpoint='unix:///tmp/synthetic.sock',
        config_dir='/tmp/synthetic-private-config',runner=delayed,clock=lambda:now[0],wall_clock=lambda:10000.0)
    with pytest.raises(Refused):call(cleanup)
    assert docker.mutations==[('docker','rm','-f','-v','2'*64)]
    assert '1'*64 in docker.networks and cleanup.daemon_evidence is None


def test_unknown_resource_appearing_after_first_delete_is_never_deleted(rig):
    m,_,registry,docker,_=rig
    original=docker.__call__
    def changed(argv,**kwargs):
        result=original(argv,**kwargs)
        if argv[:2]==('docker','rm'):docker.fault='unknown'
        return result
    cleanup=m.NativeDockerCleanup(registry,docker_binary='/usr/bin/docker',endpoint='unix:///tmp/synthetic.sock',
        config_dir='/tmp/synthetic-private-config',runner=changed,clock=lambda:100.0,wall_clock=lambda:10000.0)
    with pytest.raises(Refused):call(cleanup)
    assert docker.mutations==[('docker','rm','-f','-v','2'*64)]


def test_validated_result_association_is_checked_without_adopting_ids(rig):
    _,_,_,docker,cleanup=rig
    binding=dict(request_digest='a'*64,context_digest='b'*64,daemon_id='synthetic-daemon',
        container_id='2'*64,network_id='1'*64,image_id='sha256:'+'3'*64)
    value=cleanup(request_digest='a'*64,context_digest='b'*64,result=dict(binding=binding,binding_digest=digest(binding)),
        status='validated',deadline=130,worker_cleanup_uncertain=False)
    assert value.job_binding_digest==digest(binding) and value.status=='validated'
    assert len(docker.mutations)==2


def test_constructor_does_not_discover_files_or_start_processes(rig,monkeypatch):
    import os
    m,_,registry,_,_=rig
    monkeypatch.setattr(os,'open',lambda *_a,**_k:pytest.fail('constructor filesystem IO'))
    value=m.NativeDockerCleanup(registry,docker_binary='/usr/bin/docker',endpoint='unix:///tmp/synthetic.sock',
        config_dir='/tmp/synthetic-private-config')
    assert value.observation is None and value.daemon_evidence is None


def test_same_request_other_nonce_is_unknown_and_never_filtered_out(rig):
    m,_,_,docker,cleanup=rig
    docker.containers['f'*64]={'labels':{m.REQUEST_LABEL:'a'*64,m.NONCE_LABEL:'0'*32}}
    with pytest.raises(Refused):call(cleanup)
    assert docker.mutations==[]


def test_empty_registry_cannot_claim_absence_when_request_has_unknown_ids(rig):
    m,_,_,_,_=rig
    registry=m.NativeCleanupRegistry('a'*64,'b'*64,'synthetic-daemon').freeze()
    docker=Docker(m,registry)
    docker.containers['f'*64]={'labels':{m.REQUEST_LABEL:'a'*64,m.NONCE_LABEL:'0'*32}}
    cleanup=m.NativeDockerCleanup(registry,docker_binary='/usr/bin/docker',endpoint='unix:///tmp/synthetic.sock',
        config_dir='/tmp/synthetic-private-config',runner=docker,clock=lambda:100.0,wall_clock=lambda:10000.0)
    with pytest.raises(Refused):call(cleanup)
    assert docker.mutations==[]


@pytest.mark.parametrize('field,value',[('endpoint','unix:///tmp/other.sock'),('config_dir','/tmp/other'),
    ('docker_binary','/other/docker'),('popen',lambda:None),('resume',True)])
def test_native_cli_identity_config_drift_refuses_before_cli(rig,field,value):
    m,_,registry,_,_=rig
    cleanup=m.NativeDockerCleanup(registry,docker_binary='/usr/bin/docker',endpoint='unix:///tmp/synthetic.sock',
        config_dir='/tmp/synthetic-private-config',clock=lambda:100.0,wall_clock=lambda:10000.0)
    setattr(cleanup._runner,field,value)
    with pytest.raises(Refused):call(cleanup)
    assert cleanup.daemon_evidence is None


@pytest.mark.parametrize('exception',[RuntimeError('SYNTHETIC-PRIVATE'),KeyboardInterrupt('SYNTHETIC-PRIVATE')])
def test_cli_failure_is_sanitized_and_no_observation_is_emitted(rig,exception):
    m,_,registry,_,_=rig
    def broken(*_a,**_k):raise exception
    cleanup=m.NativeDockerCleanup(registry,docker_binary='/usr/bin/docker',endpoint='unix:///tmp/synthetic.sock',
        config_dir='/tmp/synthetic-private-config',runner=broken,clock=lambda:100.0,wall_clock=lambda:10000.0)
    with pytest.raises(KeyboardInterrupt if isinstance(exception,KeyboardInterrupt) else Refused) as result:call(cleanup)
    assert 'SYNTHETIC-PRIVATE' not in str(result.value)
    assert cleanup.observation is cleanup.daemon_evidence is None


def test_native_default_cli_uses_explicit_route_minimal_env_and_bounded_reader(rig,monkeypatch):
    import os
    import subprocess
    m,_,registry,docker,_=rig
    commands=[]
    class Process:
        def __init__(self,raw):
            read_fd,write_fd=os.pipe()
            os.write(write_fd,raw);os.close(write_fd)
            self.stdout=os.fdopen(read_fd,'rb',buffering=0)
        def wait(self,timeout):assert timeout>=0;return 0
        def poll(self):return 0
        def kill(self):pytest.fail('successful fixture CLI must not be killed')
    def popen(command,**kwargs):
        assert command[:5]==['/usr/bin/docker','--config','/tmp/synthetic-private-config','--host','unix:///tmp/synthetic.sock']
        assert kwargs['shell'] is False and kwargs['close_fds'] is True and kwargs['cwd']=='/'
        assert kwargs['stdin'] is subprocess.DEVNULL and kwargs['stderr'] is subprocess.DEVNULL
        assert not any(k in kwargs['env'] for k in ('HOME','DOCKER_HOST','DOCKER_CONTEXT','PGPASSWORD'))
        commands.append(command)
        rc,raw=docker(('docker',*command[5:]),timeout=10,max_output=65536)
        assert rc==0
        return Process(raw)
    monkeypatch.setattr(subprocess,'Popen',popen)
    cleanup=m.NativeDockerCleanup(registry,docker_binary='/usr/bin/docker',endpoint='unix:///tmp/synthetic.sock',
        config_dir='/tmp/synthetic-private-config',clock=lambda:100.0,wall_clock=lambda:10000.0)
    value=call(cleanup)
    assert commands and value.absent_resource_ids==('1'*64,'2'*64)
    assert cleanup.validate_observation(value).transport=='bounded-docker-cli'
    assert not cleanup._runner._allowed(('docker','rm','-f','-v','f'*64))


def test_legacy_job_owner_label_orphan_cannot_hide_from_empty_registry(rig):
    m,_,_,_,_=rig
    registry=m.NativeCleanupRegistry('a'*64,'b'*64,'synthetic-daemon').freeze()
    docker=Docker(m,registry)
    docker.containers['e'*64]={'labels':{'igreja12.native-window':'a'*64,'igreja12.native-token':'other-nonce'}}
    cleanup=m.NativeDockerCleanup(registry,docker_binary='/usr/bin/docker',endpoint='unix:///tmp/synthetic.sock',
        config_dir='/tmp/synthetic-private-config',runner=docker,clock=lambda:100.0,wall_clock=lambda:10000.0)
    with pytest.raises(Refused):call(cleanup)
    assert docker.mutations==[]


class ProvisionDocker:
    """Strict parent-creation boundary; derives inspected metadata from argv."""
    def __init__(self,m,image='sha256:'+'3'*64,reference=None):
        self.m=m;self.image=image;self.reference=reference or image
        self.calls=[];self.mutations=[];self.containers={};self.networks={};self.password=None;self.fault=None
        self.network_id='1'*64;self.container_id='2'*64;self.daemon='synthetic-daemon'
    def __call__(self,argv,*,timeout,max_output,env=None):
        assert 0<timeout<=10 and max_output==65536
        self.calls.append(argv)
        if argv==('docker','info','--format','{{json .ID}}'):return 0,json.dumps(self.daemon).encode()
        if argv[:3]==('docker','image','inspect'):
            assert argv[-1]==self.reference
            return 0,json.dumps([self.image]).encode()
        if (argv[:2]==('docker','ps') or argv[:3]==('docker','network','ls')) and any(v.startswith('name=') for v in argv):
            assert argv[-2:]==('--format','{{.ID}}')
            return 0,b''
        if argv[:3]==('docker','network','create'):
            assert '--internal' in argv and argv[-1].startswith('igreja12-cleanup-')
            labels=dict(argv[i+1].split('=',1) for i,v in enumerate(argv[:-1]) if v=='--label')
            self.networks[self.network_id]=dict(id=self.network_id,name=argv[-1],internal=True,driver='bridge',labels=labels,members=[])
            return 0,self.network_id.encode()
        if argv[:2]==('docker','create'):
            assert '--pull=never' in argv and '--restart=no' in argv and '--tmpfs' in argv
            assert env and set(env)=={'POSTGRES_PASSWORD'} and all(env['POSTGRES_PASSWORD'] not in value for value in argv)
            assert argv[argv.index('--network')+1]==self.network_id
            assert self.reference in argv
            self.password=env['POSTGRES_PASSWORD']
            labels=dict(argv[i+1].split('=',1) for i,v in enumerate(argv[:-1]) if v=='--label')
            name=argv[argv.index('--name')+1]
            self.containers[self.container_id]=dict(id=self.container_id,image=self.image,configured_image=self.reference,
                name='/'+name,labels=labels,network_mode=self.network_id,
                networks=[[self.networks[self.network_id]['name'],'']],mounts=[],tmpfs=dict(self.m.DATA_TMPFS),
                ports={},privileged=False,publish_all_ports=False,pid_mode='',restart='no',running=False,pid=0)
            if self.fault=='created-return-failure':return 1,b''
            return 0,self.container_id.encode()
        # The original strict cleanup boundary needs no creation privileges.
        helper=object.__new__(Docker);helper.m=self.m;helper.registry=type('R',(),{'daemon_id':self.daemon})()
        helper.calls=self.calls;helper.mutations=self.mutations;helper.fault=self.fault
        helper.containers=self.containers;helper.networks=self.networks
        return helper(argv,timeout=timeout,max_output=max_output)


def test_parent_provisioning_creates_held_registered_resources_and_seals_private_handoff(tmp_path):
    m=module()
    assert hasattr(m,'NativeParentCloneProvisioner'),'parent provisioning is missing'
    from test_first_transition_window_backup import config
    cfg=config(tmp_path,python=sys.executable)
    docker=ProvisionDocker(m,reference=cfg.clone_image)
    owner=m.NativeParentCloneProvisioner(cfg,request_digest='a'*64,context_digest='b'*64,daemon_id=docker.daemon,
        image_id=docker.image,runner=docker,clock=lambda:100.0,wall_clock=lambda:10000.0)
    owner.provision(deadline=130)
    import fcntl,os
    assert fcntl.fcntl(owner.handoff_fd,1034)&15==15
    assert owner.registry.network_id=='1'*64 and owner.registry.containers[0].container_id=='2'*64
    assert not docker.containers['2'*64]['running']
    handle=m.NativeParentCloneHandle.from_fd(owner.handoff_fd,expected_registry_digest=owner.registry.digest,
        request_digest='a'*64,context_digest='b'*64,config_digest=digest(asdict(cfg)),daemon_id=docker.daemon)
    assert handle.registry_digest==owner.registry.digest
    assert docker.password not in repr(handle) and docker.password not in repr(owner)
    observation=owner.cleanup(request_digest='a'*64,context_digest='b'*64,result=None,status='worker-failed',
        deadline=130,worker_cleanup_uncertain=False)
    assert observation.absent_resource_ids==('1'*64,'2'*64)
    assert not docker.containers and not docker.networks
    handle.close();owner.close()


def provision_rig(tmp_path):
    m=module()
    from test_first_transition_window_backup import config
    cfg=config(tmp_path,python=sys.executable)
    docker=ProvisionDocker(m,reference=cfg.clone_image)
    owner=m.NativeParentCloneProvisioner(cfg,request_digest='a'*64,context_digest='b'*64,daemon_id=docker.daemon,
        image_id=docker.image,runner=docker,clock=lambda:100.0,wall_clock=lambda:10000.0)
    owner.provision(deadline=130)
    return m,cfg,docker,owner


@pytest.mark.parametrize('field',['config_digest','registry_digest','password'])
def test_received_handle_metadata_cannot_diverge_from_its_sealed_parent_input(tmp_path,field):
    m,cfg,_,owner=provision_rig(tmp_path)
    handle=m.NativeParentCloneHandle.from_fd(owner.handoff_fd,expected_registry_digest=owner.registry.digest,
        request_digest='a'*64,context_digest='b'*64,config_digest=digest(asdict(cfg)),daemon_id='synthetic-daemon')
    try:
        if field=='config_digest':handle.config_digest='f'*64
        elif field=='registry_digest':
            handle.registry=replace(handle.registry,daemon_id='other-daemon')
            handle.registry_digest=handle.registry.digest
        else:handle._password='0'*48
        with pytest.raises(Refused):handle.validate()
    finally:handle.close();owner.close()


def test_pre_worker_refusal_can_cleanup_registered_resources_and_context_closes_capsule(tmp_path):
    m=module()
    from test_first_transition_window_backup import config
    cfg=config(tmp_path,python=sys.executable);docker=ProvisionDocker(m,reference=cfg.clone_image)
    with m.NativeParentCloneProvisioner(cfg,request_digest='a'*64,context_digest='b'*64,daemon_id=docker.daemon,
            image_id=docker.image,runner=docker,clock=lambda:100.0,wall_clock=lambda:10000.0) as owner:
        owner.provision(deadline=130);fd=owner.handoff_fd
        # The dispatcher refuses preflight BEFORE launching a child.
        try:raise Refused('synthetic-input-preflight')
        except Refused:
            owner.cleanup(request_digest='a'*64,context_digest='b'*64,result=None,status='worker-failed',
                deadline=130,worker_cleanup_uncertain=False)
    import os
    with pytest.raises(OSError):os.fstat(fd)
    assert not docker.containers and not docker.networks


@pytest.mark.parametrize('field',['clock','wall_clock'])
def test_parent_constructor_rejects_invalid_clock_without_io(tmp_path,field):
    m=module()
    from test_first_transition_window_backup import config
    cfg=config(tmp_path,python=sys.executable)
    with pytest.raises(Refused):
        m.NativeParentCloneProvisioner(cfg,request_digest='a'*64,context_digest='b'*64,
            daemon_id='synthetic-daemon',image_id='sha256:'+'3'*64,**{field:False})


@pytest.mark.parametrize('fault',['pin','request','context','config','daemon','unsealed','closed','registry','password'])
def test_handoff_requires_live_sealed_input_and_independent_parent_bindings(tmp_path,fault):
    import os
    m,cfg,_,owner=provision_rig(tmp_path)
    options=dict(expected_registry_digest=owner.registry.digest,request_digest='a'*64,context_digest='b'*64,
        config_digest=digest(asdict(cfg)),daemon_id='synthetic-daemon')
    fd=owner.handoff_fd;created=None
    if fault in ('pin','request','context','config'):
        options[{'pin':'expected_registry_digest','request':'request_digest','context':'context_digest','config':'config_digest'}[fault]]='f'*64
    elif fault=='daemon':options['daemon_id']='other'
    elif fault=='unsealed':
        created=os.memfd_create('unsealed-fixture');os.write(created,os.pread(fd,65536,0));fd=created
    elif fault=='closed':created=os.dup(fd);os.close(created);fd=created;created=None
    else:
        value=json.loads(os.pread(fd,65536,0))
        if fault=='registry':value['registry']['network_id']='f'*64
        else:value['password']='invalid'
        created=m._seal_private(json.dumps(value).encode());fd=created
    try:
        with pytest.raises(Refused):m.NativeParentCloneHandle.from_fd(fd,**options)
    finally:
        if created is not None:os.close(created)
        owner.close()


def test_handoff_inside_sealed_job_input_preserves_caller_fd_and_single_use(tmp_path):
    import os,fcntl
    m,cfg,_,owner=provision_rig(tmp_path)
    value=json.loads(os.pread(owner.handoff_fd,65536,0))
    fd=m._seal_private(json.dumps(dict(parent_clone=value,other_private_job_input='synthetic')).encode())
    try:
        with m.NativeParentCloneHandle.from_fd(fd,expected_registry_digest=owner.registry.digest,
                request_digest='a'*64,context_digest='b'*64,config_digest=digest(asdict(cfg)),
                daemon_id='synthetic-daemon',envelope_key='parent_clone') as handle:
            handle.consume()
            with pytest.raises(Refused):handle.consume()
        assert fcntl.fcntl(fd,1034)&15==15
    finally:os.close(fd);owner.close()


def test_unknown_container_from_unacknowledged_parent_creation_is_not_adopted(tmp_path):
    m=module()
    from test_first_transition_window_backup import config
    cfg=config(tmp_path,python=sys.executable)
    docker=ProvisionDocker(m,reference=cfg.clone_image);docker.fault='created-return-failure'
    owner=m.NativeParentCloneProvisioner(cfg,request_digest='a'*64,context_digest='b'*64,daemon_id=docker.daemon,
        image_id=docker.image,runner=docker,clock=lambda:100.0,wall_clock=lambda:10000.0)
    with pytest.raises(Refused):owner.provision(deadline=130)
    assert owner.registry.network_id=='1'*64 and owner.registry.containers==()
    with pytest.raises(Refused):_ = owner.handoff_fd
    with pytest.raises(Refused):
        owner.cleanup(request_digest='a'*64,context_digest='b'*64,result=None,status='worker-failed',
            deadline=130,worker_cleanup_uncertain=False)
    assert docker.mutations==[]


def test_wrong_pinned_image_refuses_before_parent_resource_creation(tmp_path):
    m=module()
    from test_first_transition_window_backup import config
    cfg=config(tmp_path,python=sys.executable);docker=ProvisionDocker(m,reference=cfg.clone_image)
    owner=m.NativeParentCloneProvisioner(cfg,request_digest='a'*64,context_digest='b'*64,daemon_id=docker.daemon,
        image_id='sha256:'+'f'*64,runner=docker,clock=lambda:100.0)
    with pytest.raises(Refused):owner.provision(deadline=130)
    assert not docker.containers and not docker.networks and owner.registry.containers==()


class FileProvisionDocker:
    """Cross-fork synthetic daemon state; never a real Docker invocation."""
    def __init__(self,m,path,reference,mode=''):
        self.m,self.path,self.reference,self.mode=m,Path(path),reference,mode
        import os
        self.parent_pid=os.getpid()
    @property
    def unreaped(self):
        import os
        if self.mode=='guard-runner-properties':
            assert os.getpid()!=self.parent_pid,'runner property executed in monitoring parent'
        return 0
    def __call__(self,argv,*,timeout,max_output,env=None):
        import time
        state=json.loads(self.path.read_text()) if self.path.exists() else dict(networks={},containers={},calls=[],mutations=[],blocked=False)
        docker=ProvisionDocker(self.m,reference=self.reference)
        docker.networks=state['networks'];docker.containers=state['containers']
        docker.calls=[tuple(v) for v in state['calls']];docker.mutations=[tuple(v) for v in state['mutations']]
        if self.mode=='unacknowledged-invisible' and argv[:3]==('docker','network','create'):
            time.sleep(30)  # Async daemon creation may not yet be visible to inventory.
        if argv[:5]==('docker','inspect','--type','container','--format'):
            if self.mode=='always-block-inspect' or self.mode=='block-inspect-once' and not state['blocked']:
                state['blocked']=True;self.path.write_text(json.dumps(state));time.sleep(30)
        rc,raw=docker(argv,timeout=timeout,max_output=max_output,env=env)
        state.update(networks=docker.networks,containers=docker.containers,calls=docker.calls,mutations=docker.mutations)
        self.path.write_text(json.dumps(state))
        if self.mode=='lost-network-id' and argv[:3]==('docker','network','create'):time.sleep(30)
        if self.mode=='lost-container-id' and argv[:2]==('docker','create'):time.sleep(30)
        return rc,raw


def bounded_owner(tmp_path,mode=''):
    m=module()
    from test_first_transition_window_backup import config
    cfg=config(tmp_path,python=sys.executable)
    boundary=FileProvisionDocker(m,tmp_path/'daemon-state.json',cfg.clone_image,mode)
    return m,m.NativeParentCloneProvisioner(cfg,request_digest='a'*64,context_digest='b'*64,daemon_id='synthetic-daemon',
        image_id='sha256:'+'3'*64,runner=boundary),boundary


def test_bounded_provision_records_ids_in_parent_and_returns_live_sealed_capsule(tmp_path):
    m,owner,boundary=bounded_owner(tmp_path)
    assert callable(getattr(owner,'provision_bounded',None)),'total provisioning deadline is missing'
    try:
        owner.provision_bounded(timeout_s=3,cleanup_budget_s=.7,stop_budget_s=.1)
        assert owner.registry.network_id=='1'*64 and owner.registry.containers[0].container_id=='2'*64
        assert owner.handoff_fd>2
        diag=owner.bounded_diagnostics()
        assert diag['staged_complete'] is True and diag['process_cleanup_verified'] is True
        assert diag['source_unchanged_proven'] is diag['a8_window_proven'] is False
        assert diag['authoritative_fence_proven'] is diag['daemon_cleanup_authoritative'] is False
        assert diag['cleanup_hard_deadline_verified'] is diag['production_ready'] is False
        state=json.loads(boundary.path.read_text())
        assert state['containers']['2'*64]['running'] is False and state['mutations']==[]
        owner.cleanup(request_digest='a'*64,context_digest='b'*64,result=None,status='worker-failed',
            deadline=owner.clock()+2,worker_cleanup_uncertain=False)
    finally:owner.close()


@pytest.mark.parametrize('mode',['block-inspect-once','always-block-inspect','lost-network-id',
    'lost-container-id','unacknowledged-invisible'])
def test_total_provision_timeout_bounds_creation_and_reserved_cleanup_without_adoption(tmp_path,mode):
    import time
    _,owner,boundary=bounded_owner(tmp_path,mode)
    assert callable(getattr(owner,'provision_bounded',None)),'total provisioning deadline is missing'
    started=time.monotonic()
    with pytest.raises(Refused):owner.provision_bounded(timeout_s=1.4,cleanup_budget_s=.5,stop_budget_s=.1)
    assert time.monotonic()-started<2
    diag=owner.bounded_diagnostics()
    assert diag['process_cleanup_verified'] is True and diag['cleanup_reaped'] is True
    assert diag['staged_complete'] is False
    state=json.loads(boundary.path.read_text())
    if mode=='block-inspect-once':
        assert not state['containers'] and not state['networks'] and diag['parent_cleanup_completed'] is True
    elif mode=='lost-network-id':
        assert owner.registry.network_id is None and state['networks'] and state['mutations']==[]
        assert diag['unknown_resources_possible'] is True and diag['parent_cleanup_completed'] is False
    elif mode=='unacknowledged-invisible':
        assert not state['networks'] and not state['containers']
        assert diag['unknown_resources_possible'] is True and diag['parent_cleanup_completed'] is False
    elif mode=='lost-container-id':
        assert owner.registry.network_id=='1'*64 and owner.registry.containers==()
        assert state['containers'] and state['networks'] and state['mutations']==[]
        assert diag['unknown_resources_possible'] is True and diag['parent_cleanup_completed'] is False
    else:assert state['containers'] and state['mutations']==[] and diag['parent_cleanup_completed'] is False
    with pytest.raises(Refused):_ = owner.handoff_fd


@pytest.mark.parametrize('field',['clock','wall_clock'])
def test_bounded_provision_refuses_arbitrary_parent_clock_before_any_io(tmp_path,field):
    _,owner,boundary=bounded_owner(tmp_path)
    setattr(owner,field,lambda:pytest.fail('unbounded parent callback executed'))
    with pytest.raises(Refused):owner.provision_bounded(timeout_s=3,cleanup_budget_s=.7,stop_budget_s=.1)
    assert not boundary.path.exists()
    assert owner.bounded_diagnostics()['deadline_enforced'] is False


def test_bounded_provision_checks_injected_runner_properties_only_in_helper(tmp_path):
    _,owner,_=bounded_owner(tmp_path,'guard-runner-properties')
    try:
        owner.provision_bounded(timeout_s=3,cleanup_budget_s=.7,stop_budget_s=.1)
        assert owner.bounded_diagnostics()['staged_complete'] is True
    finally:owner.close()


@pytest.mark.parametrize('options',[
    dict(timeout_s=31),dict(timeout_s=True),dict(timeout_s=1,cleanup_budget_s=.9),
    dict(cleanup_budget_s=.1),dict(stop_budget_s=0),dict(stop_budget_s=3),
])
def test_total_budget_must_reserve_creation_and_cleanup_before_any_io(tmp_path,options):
    _,owner,boundary=bounded_owner(tmp_path)
    with pytest.raises(Refused):owner.provision_bounded(**options)
    assert not boundary.path.exists()
    assert owner.bounded_diagnostics()['deadline_enforced'] is False


@pytest.mark.parametrize('fault',['exception','interrupt'])
def test_bounded_success_exit_failure_still_uses_reserved_parent_cleanup(tmp_path,monkeypatch,fault):
    import first_transition_native_outer as outer
    _,owner,boundary=bounded_owner(tmp_path)
    original=outer._subreaper;failed=False
    def failing(value=None):
        nonlocal failed
        if value is False and not failed:
            failed=True
            if fault=='interrupt':raise KeyboardInterrupt('private synthetic exit cancellation')
            raise OSError('synthetic role restoration failed once')
        return original(value)
    try:
        with monkeypatch.context() as patched:
            patched.setattr(outer,'_subreaper',failing)
            expected=KeyboardInterrupt if fault=='interrupt' else Refused
            with pytest.raises(expected) as error:
                owner.provision_bounded(timeout_s=3,cleanup_budget_s=.7,stop_budget_s=.1)
            if fault=='interrupt':assert str(error.value)==''
        state=json.loads(boundary.path.read_text())
        assert not state['containers'] and not state['networks']
        diag=owner.bounded_diagnostics()
        assert diag['cleanup_attempted'] is diag['cleanup_reaped'] is diag['parent_cleanup_completed'] is True
        assert diag['staged_complete'] is False and original()==0
        with pytest.raises(Refused):_ = owner.handoff_fd
    finally:original(False);owner.close()


def test_bounded_parent_observation_interrupt_still_finalizes_registered_ids(tmp_path,monkeypatch):
    import first_transition_native_outer as outer
    _,owner,boundary=bounded_owner(tmp_path)
    original=outer.NativeProcessBoundary.last_reaped;failed=False
    def failing(self):
        nonlocal failed
        if not failed:
            failed=True
            raise KeyboardInterrupt('private synthetic parent observation interruption')
        return original.__get__(self)
    try:
        with monkeypatch.context() as patched:
            patched.setattr(outer.NativeProcessBoundary,'last_reaped',property(failing))
            with pytest.raises(KeyboardInterrupt) as error:
                owner.provision_bounded(timeout_s=3,cleanup_budget_s=.7,stop_budget_s=.1)
            assert str(error.value)==''
        state=json.loads(boundary.path.read_text())
        assert not state['containers'] and not state['networks']
        assert owner.bounded_diagnostics()['parent_cleanup_completed'] is True
        assert outer._subreaper()==0
    finally:outer._subreaper(False);owner.close()


def test_unprovable_role_recovery_keeps_held_resources_pending_without_cleanup(tmp_path,monkeypatch):
    import first_transition_native_outer as outer
    _,owner,boundary=bounded_owner(tmp_path)
    original=outer._subreaper
    def failing(value=None):
        if value is False:raise OSError('synthetic role restoration remains unavailable')
        return original(value)
    try:
        with monkeypatch.context() as patched:
            patched.setattr(outer,'_subreaper',failing)
            with pytest.raises(Refused):owner.provision_bounded(timeout_s=3,cleanup_budget_s=.7,stop_budget_s=.1)
        diag=owner.bounded_diagnostics()
        assert diag['held_resources_pending'] is True and diag['cleanup_attempted'] is False
        assert diag['parent_cleanup_completed'] is False and diag['staged_complete'] is False
        state=json.loads(boundary.path.read_text())
        assert state['containers'] and state['networks'] and not state['mutations']
        with pytest.raises(Refused):_ = owner.handoff_fd
    finally:original(False);owner.close()
