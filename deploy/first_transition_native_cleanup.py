"""Cleanup of a frozen trusted-parent registry, never resource discovery/adoption.

The parent creator alone records IDs returned by its explicit new isolated-clone
creations. Worker JSON, labels, names and successful command output never add an
ID to this registry. Child-created unregistered resources cause refusal. There
is no source/production role, CLI entrypoint, credential/config discovery or
claim of an outer hard deadline. A dedicated outer process is still required.
"""
from dataclasses import asdict,dataclass,field
from copy import deepcopy
import base64
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
import time

from first_transition_adapter import digest
from first_transition_host_driver import PopenRunner,_absolute
from initial_transition_ops import Refused,require

CODE='native-cleanup-refused'
REQUEST_LABEL='igreja12.native-cleanup.request'
JOB_OWNER_LABEL='igreja12.native-window'
JOB_TOKEN_LABEL='igreja12.native-token'
CONTEXT_LABEL='igreja12.native-cleanup.context'
NONCE_LABEL='igreja12.native-cleanup.nonce'
KIND_LABEL='igreja12.native-cleanup.kind'
PURPOSE_LABEL='igreja12.native-cleanup.purpose'
PURPOSE='isolated-recovery-clone'
DATA_TMPFS=(('/var/lib/postgresql/data','rw,nosuid,nodev,noexec,size=536870912'),)
TMP_TMPFS=('/tmp','rw,nosuid,nodev,noexec,size=33554432')
_SEAL=object()
_REAL_MONOTONIC=time.monotonic
_REAL_WALL=time.time
CONTAINER_FIELDS=dict(id='.Id',image='.Image',configured_image='.Config.Image',name='.Name',
    labels='.Config.Labels',network_mode='.HostConfig.NetworkMode',tmpfs='.HostConfig.Tmpfs',
    ports='.HostConfig.PortBindings',privileged='.HostConfig.Privileged',
    publish_all_ports='.HostConfig.PublishAllPorts',pid_mode='.HostConfig.PidMode',
    restart='.HostConfig.RestartPolicy.Name',running='.State.Running',pid='.State.Pid')
CONTAINER_VIEW=('{'+','.join('"'+k+'":{{json ('+v+')}}' for k,v in CONTAINER_FIELDS.items())+
    ',"mounts":[{{range .Mounts}}[{{json .Type}},{{json .Source}},{{json .Destination}}],{{end}}null]'+
    ',"networks":[{{range $name,$net := .NetworkSettings.Networks}}[{{json $name}},{{json $net.NetworkID}}],{{end}}null]}')
NETWORK_FIELDS=dict(id='.Id',name='.Name',internal='.Internal',driver='.Driver',labels='.Labels')
NETWORK_VIEW=('{'+','.join('"'+k+'":{{json ('+v+')}}' for k,v in NETWORK_FIELDS.items())+
    ',"members":[{{range $id,$container := .Containers}}{{json $id}},{{end}}null]}')


def _hex(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None
def _image(value):return type(value) is str and re.fullmatch('sha256:[0-9a-f]{64}',value) is not None
def _number(value):return type(value) in (int,float) and math.isfinite(value)
def _tail(value):
    require(type(value) is list,CODE)
    return value[:-1] if value[-1:]==[None] else value


def _labels(request,context,nonce,kind):
    require(kind in ('container','network'),CODE)
    return {REQUEST_LABEL:request,JOB_OWNER_LABEL:request,JOB_TOKEN_LABEL:nonce,CONTEXT_LABEL:context,NONCE_LABEL:nonce,
            KIND_LABEL:kind,PURPOSE_LABEL:PURPOSE}


@dataclass(frozen=True)
class NativeCleanupContainer:
    container_id:str
    image_id:str
    image_reference:str
    name:str
    tmpfs:tuple


@dataclass(frozen=True)
class NativeFrozenCleanupRegistry:
    request_digest:str
    context_digest:str
    daemon_id:str
    nonce:str
    network_id:str|None
    network_name:str
    containers:tuple
    _seal:object=field(repr=False,compare=False)

    def labels(self,kind):return _labels(self.request_digest,self.context_digest,self.nonce,kind)
    def public(self):
        return dict(request_digest=self.request_digest,context_digest=self.context_digest,daemon_id=self.daemon_id,
            nonce=self.nonce,network_id=self.network_id,network_name=self.network_name,
            containers=[asdict(c) for c in self.containers],purpose=PURPOSE)
    @property
    def digest(self):return digest(self.public())


class NativeCleanupRegistry:
    """Trusted parent creation journal. Registration is not an adoption API.

    Creating Docker resources is deliberately external to this small adapter.
    Supply only freshly returned IDs from the parent's own creation operations,
    with these pre-generated names/labels; never load records from worker JSON.
    """
    def __init__(self,request_digest,context_digest,daemon_id):
        require(_hex(request_digest) and _hex(context_digest) and type(daemon_id) is str
            and re.fullmatch('[A-Za-z0-9_.:-]{1,128}',daemon_id),CODE)
        self._request,self._context,self._daemon=request_digest,context_digest,daemon_id
        self._nonce=secrets.token_hex(16);self._network=None;self._containers=[];self._frozen=False

    @property
    def network_name(self):return 'igreja12-cleanup-'+self._nonce
    def container_name(self,index=0):
        require(type(index) is int and 0<=index<16,CODE)
        return self.network_name+'-'+str(index)
    def labels(self,kind):return _labels(self._request,self._context,self._nonce,kind)

    def created_network(self,network_id):
        require(not self._frozen and self._network is None and _hex(network_id),CODE)
        self._network=network_id

    def created_container(self,container_id,*,image_id,image_reference=None,tmpfs=DATA_TMPFS):
        reference=image_id if image_reference is None else image_reference
        require(not self._frozen and self._network is not None and _hex(container_id)
            and container_id!=self._network and container_id not in {c.container_id for c in self._containers}
            and len(self._containers)<16 and _image(image_id) and type(reference) is str
            and re.fullmatch(r'(?:sha256:|[A-Za-z0-9._/-]+@sha256:)[0-9a-f]{64}',reference)
            and type(tmpfs) is tuple and tmpfs in (DATA_TMPFS,DATA_TMPFS+(TMP_TMPFS,)),CODE)
        self._containers.append(NativeCleanupContainer(container_id,image_id,reference,self.container_name(len(self._containers)),tmpfs))

    def freeze(self):
        require(not self._frozen,CODE);self._frozen=True
        return NativeFrozenCleanupRegistry(self._request,self._context,self._daemon,self._nonce,self._network,
            self.network_name,tuple(self._containers),_SEAL)


@dataclass(frozen=True)
class NativeCleanupDaemonEvidence:
    request_digest:str
    context_digest:str
    job_binding_digest:str|None
    status:str
    daemon_id:str
    registry_digest:str
    observation_sha256:str
    inspected_resource_ids:tuple
    absent_resource_ids:tuple
    started_at:float
    finished_at:float
    elapsed_s:float
    transport:str
    daemon_cleanup_authoritative:bool=False
    cleanup_hard_deadline_verified:bool=False
    source_unchanged_proven:bool=False
    a8_window_proven:bool=False
    production_ready:bool=False

    @property
    def digest(self):return digest(asdict(self))


class _CleanupCLI(PopenRunner):
    def __init__(self,owner,**kwargs):
        self.owner=owner
        super().__init__(**kwargs)
    def _allowed(self,argv):return argv in self.owner.allowed_argv()


class NativeDockerCleanup:
    """Single cleanup attempt; only frozen registered IDs may be removed."""
    def __init__(self,registry,*,docker_binary,endpoint,config_dir,runner=None,clock=None,wall_clock=None):
        require(type(registry) is NativeFrozenCleanupRegistry and registry._seal is _SEAL
            and _absolute(docker_binary) and docker_binary.endswith('/docker')
            and type(endpoint) is str and endpoint.startswith('unix://') and _absolute(endpoint[7:])
            and endpoint.endswith('.sock') and _absolute(config_dir)
            and (runner is None or callable(runner)) and (clock is None or callable(clock))
            and (wall_clock is None or callable(wall_clock)),CODE)
        self.registry=registry;self._registry_digest=registry.digest
        self._ids=tuple(sorted(([registry.network_id] if registry.network_id else [])+
                              [c.container_id for c in registry.containers]))
        self._runner=runner if runner is not None else _CleanupCLI(self,docker_binary=docker_binary,
            endpoint=endpoint,config_dir=config_dir,cleanup_wait=.1)
        self._transport='bounded-docker-cli' if runner is None else 'injected-boundary'
        self._runner_origin=self._runner;self._transport_origin=self._transport
        self._cli_binding=(docker_binary,endpoint,config_dir,.1,4096)
        self.clock,self.wall_clock=clock or time.monotonic,wall_clock or time.time
        self._used=False;self._observation=self._evidence=None

    @property
    def observation(self):return self._observation
    @property
    def daemon_evidence(self):return self._evidence

    def _binding(self):
        require(type(self.registry) is NativeFrozenCleanupRegistry and self.registry._seal is _SEAL
            and self.registry.digest==self._registry_digest and self._runner is self._runner_origin
            and self._transport==self._transport_origin,CODE)
        if self._transport_origin=='bounded-docker-cli':
            runner=self._runner
            require(type(runner) is _CleanupCLI and runner.owner is self and runner.popen is None
                and runner.resume is False and (runner.docker_binary,runner.endpoint,runner.config_dir,
                    runner.cleanup_wait,runner.chunk)==self._cli_binding,CODE)

    def _inventory_argv(self,kind,label,value):
        prefix=('docker','ps','-a','--no-trunc') if kind=='container' else ('docker','network','ls','--no-trunc')
        return (*prefix,'--filter','label='+label+'='+value,'--format','{{.ID}}')
    def _presence_argv(self,kind,ident):
        prefix=('docker','ps','-a','--no-trunc') if kind=='container' else ('docker','network','ls','--no-trunc')
        return (*prefix,'--filter','id='+ident,'--format','{{.ID}}')
    def _inspect_argv(self,kind,ident):
        return (('docker','inspect','--type','container','--format',CONTAINER_VIEW,ident) if kind=='container'
                else ('docker','network','inspect','--format',NETWORK_VIEW,ident))

    def allowed_argv(self):
        r=self.registry
        values={('docker','info','--format','{{json .ID}}')}
        for kind in ('container','network'):
            for key,value in ((REQUEST_LABEL,r.request_digest),(JOB_OWNER_LABEL,r.request_digest),(NONCE_LABEL,r.nonce)):
                values.add(self._inventory_argv(kind,key,value))
        for c in r.containers:
            values.update((self._presence_argv('container',c.container_id),self._inspect_argv('container',c.container_id),
                           ('docker','rm','-f','-v',c.container_id)))
        if r.network_id:
            values.update((self._presence_argv('network',r.network_id),self._inspect_argv('network',r.network_id),
                           ('docker','network','rm',r.network_id)))
        return frozenset(values)

    def _remaining(self):
        value=self._deadline-self.clock()
        require(_number(value) and value>0,CODE);return min(10,value)
    def _call(self,argv):
        self._binding();require(argv in self.allowed_argv(),CODE)
        rc,raw=self._runner(argv,timeout=self._remaining(),max_output=65536)
        require(type(rc) is int and rc==0 and type(raw) is bytes and len(raw)<=65536
            and getattr(self._runner,'unreaped',0)==0,CODE)
        self._remaining()
        return raw

    @staticmethod
    def _pairs(items):
        value={}
        for key,item in items:
            require(key not in value,CODE);value[key]=item
        return value
    def _json(self,argv):return json.loads(self._call(argv),object_pairs_hook=self._pairs)
    def _lines(self,argv):
        values=self._call(argv).decode('ascii').splitlines()
        require(len(values)==len(set(values)) and all(_hex(v) for v in values),CODE)
        return set(values)
    def _daemon(self):
        require(self._json(('docker','info','--format','{{json .ID}}'))==self.registry.daemon_id,CODE)
    def _inventory(self):
        r=self.registry;result={}
        for kind,known in (('container',{c.container_id for c in r.containers}),('network',{r.network_id} if r.network_id else set())):
            found=set()
            for key,value in ((REQUEST_LABEL,r.request_digest),(JOB_OWNER_LABEL,r.request_digest),(NONCE_LABEL,r.nonce)):
                found|=self._lines(self._inventory_argv(kind,key,value))
            require(found<=known,CODE);result[kind]=found
        return result
    def _present(self,kind,ident):
        values=self._lines(self._presence_argv(kind,ident))
        require(values in (set(),{ident}),CODE)
        return bool(values)
    def _labels_valid(self,value,kind):
        require(type(value) is dict and all(type(k) is str and type(v) is str for k,v in value.items())
                and all(value.get(k)==v for k,v in self.registry.labels(kind).items()),CODE)

    def _preflight(self):
        self._daemon();inventory=self._inventory();r=self.registry
        containers={};network=None
        network_present=r.network_id is not None and self._present('network',r.network_id)
        for c in r.containers:
            if not self._present('container',c.container_id):continue
            row=self._json(self._inspect_argv('container',c.container_id))
            require(type(row) is dict and set(row)==set(CONTAINER_FIELDS)|{'mounts','networks'},CODE)
            self._labels_valid(row['labels'],'container')
            require(network_present and row['id']==c.container_id and row['image']==c.image_id
                and row['configured_image']==c.image_reference and row['name']=='/'+c.name
                and row['network_mode']==r.network_id and row['tmpfs']==dict(c.tmpfs)
                and row['ports'] in (None,{}) and row['privileged'] is False and row['publish_all_ports'] is False
                and row['pid_mode']=='' and row['restart']=='no' and type(row['running']) is bool
                and type(row['pid']) is int and (row['pid']>0 if row['running'] else row['pid']==0),CODE)
            mounts=_tail(row['mounts']);networks=_tail(row['networks'])
            require(all(type(m) is list and len(m)==3 and m[0]=='tmpfs' and m[1] in ('',None)
                        and m[2] in dict(c.tmpfs) for m in mounts)
                    and len({m[2] for m in mounts})==len(mounts),CODE)
            require(networks==[[r.network_name,r.network_id]] or not row['running']
                    and networks==[[r.network_name,'']],CODE)
            containers[c.container_id]=row
        require(set(containers)==inventory['container'],CODE)
        if network_present:
            network=self._json(self._inspect_argv('network',r.network_id))
            require(type(network) is dict and set(network)==set(NETWORK_FIELDS)|{'members'},CODE)
            self._labels_valid(network['labels'],'network')
            members=_tail(network['members'])
            require(network['id']==r.network_id and network['name']==r.network_name and network['internal'] is True
                    and network['driver']=='bridge' and len(members)==len(set(members))
                    and all(_hex(v) for v in members) and set(members)<=set(containers)
                    and {cid for cid,row in containers.items() if row['running']}<=set(members),CODE)
        require(inventory['network']==({r.network_id} if network_present else set()),CODE)
        return set(containers),network_present

    def inspect_registered(self,*,deadline):
        """Read-only ownership/isolation check, never discovery or cleanup proof."""
        self._binding()
        require(not self._used and _number(deadline) and deadline>self.clock(),CODE)
        self._deadline=min(deadline,self.clock()+30)
        return self._preflight()

    def __call__(self,*,request_digest,context_digest,result,status,deadline,worker_cleanup_uncertain):
        require(not self._used,CODE);self._used=True
        try:
            require(worker_cleanup_uncertain is False and request_digest==self.registry.request_digest
                and context_digest==self.registry.context_digest and status in ('worker-failed','invalid-result','validated')
                and _number(deadline),CODE)
            self._binding()
            start=self.clock();wall=self.wall_clock()
            require(_number(start) and start>=0 and _number(wall) and wall>0 and deadline>start,CODE)
            self._deadline=min(deadline,start+30)
            job_binding=None
            if result is not None:
                require(type(result) is dict and type(result.get('binding')) is dict
                    and _hex(result.get('binding_digest')) and digest(result['binding'])==result['binding_digest'],CODE)
                b=result['binding'];known={c.container_id:c for c in self.registry.containers}
                require(b.get('request_digest')==request_digest and b.get('context_digest')==context_digest
                    and b.get('daemon_id')==self.registry.daemon_id and b.get('container_id') in known
                    and b.get('network_id')==self.registry.network_id
                    and b.get('image_id')==known[b['container_id']].image_id,CODE)
                job_binding=result['binding_digest']
            require(status!='validated' or result is not None,CODE)
            present,_=self._preflight()
            for c in self.registry.containers:
                if c.container_id not in present:continue
                current,_=self._preflight()
                if c.container_id in current:
                    self._call(('docker','rm','-f','-v',c.container_id))
                    require(not self._present('container',c.container_id),CODE)
            _,network=self._preflight()
            if network:self._call(('docker','network','rm',self.registry.network_id))
            require(self._preflight()==(set(),False),CODE)
            self._daemon()
            end=self.clock();finished=self.wall_clock()
            require(_number(end) and start<=end<self._deadline and _number(finished) and finished>=wall
                    and abs((finished-wall)-(end-start))<=2,CODE)
            self._binding()
            from first_transition_native_supervision import NativeCleanupObservation
            observation=NativeCleanupObservation(request_digest,context_digest,job_binding,status,self.registry.daemon_id,self._ids,self._ids)
            evidence=NativeCleanupDaemonEvidence(request_digest,context_digest,job_binding,status,self.registry.daemon_id,
                self._registry_digest,digest(asdict(observation)),self._ids,self._ids,wall,finished,end-start,self._transport)
            self._observation,self._evidence=observation,evidence
            self._evidence_digest=evidence.digest
            return observation
        except Exception:
            raise Refused(CODE) from None
        except BaseException:
            raise KeyboardInterrupt from None

    def validate_observation(self,value):
        from first_transition_native_supervision import NativeCleanupObservation
        self._binding()
        require(type(value) is NativeCleanupObservation and self._observation is not None and self._evidence is not None
            and digest(asdict(value))==digest(asdict(self._observation))==self._evidence.observation_sha256
            and self._evidence.digest==self._evidence_digest and self.registry.digest==self._registry_digest,CODE)
        return self._evidence


PARENT_HANDOFF_SCHEMA='igreja12.native-parent-clone-handoff/1'
PARENT_CLONE_COMMAND=('postgres','-c','shared_preload_libraries=','-c','session_preload_libraries=',
                      '-c','local_preload_libraries=')


def _fd_pin(info):
    return (info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_uid,info.st_nlink,info.st_mtime_ns,info.st_ctime_ns)


def _seal_private(raw):
    fd=os.memfd_create('igreja12-parent-clone-private',os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING)
    try:
        os.fchmod(fd,0o400);offset=0
        while offset<len(raw):
            count=os.write(fd,raw[offset:]);require(count>0,CODE);offset+=count
        fcntl.fcntl(fd,1033,15)
        require(fcntl.fcntl(fd,1034)&15==15,CODE)
        return fd
    except BaseException:
        os.close(fd);raise


class NativeParentCloneHandle:
    """Receiver of a sealed parent capability plus an independent registry pin.

    The seal prevents mutation, not forgery: expected_registry_digest MUST come
    from trusted launch policy, outside this private input. No from-dict API,
    result-JSON adoption, Docker discovery or resource creation is provided.
    """
    def __init__(self):raise Refused('native-parent-clone-use-sealed-fd')
    def __repr__(self):return '<NativeParentCloneHandle private>'

    @classmethod
    def from_fd(cls,fd,*,expected_registry_digest,request_digest,context_digest,config_digest,daemon_id,envelope_key=None):
        duplicate=None
        try:
            require(type(fd) is int and fd>2 and _hex(expected_registry_digest)
                and all(_hex(v) for v in (request_digest,context_digest,config_digest))
                and envelope_key in (None,'parent_clone'),CODE)
            info=os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and 0<info.st_size<=2097152 and fcntl.fcntl(fd,1034)&15==15,CODE)
            raw=os.pread(fd,2097153,0)
            require(len(raw)==info.st_size and _fd_pin(os.fstat(fd))==_fd_pin(info),CODE)
            value=json.loads(raw,object_pairs_hook=NativeDockerCleanup._pairs)
            if envelope_key is not None:
                require(type(value) is dict and envelope_key in value,CODE);value=value[envelope_key]
            require(type(value) is dict and set(value)=={'schema','registry','registry_digest','config_digest','password'}
                and value['schema']==PARENT_HANDOFF_SCHEMA and value['registry_digest']==expected_registry_digest
                and value['config_digest']==config_digest
                and type(value['password']) is str and re.fullmatch('[0-9a-f]{48}',value['password']),CODE)
            r=value['registry']
            require(type(r) is dict and set(r)=={'request_digest','context_digest','daemon_id','nonce','network_id',
                    'network_name','containers','purpose'} and digest(r)==expected_registry_digest
                and r['request_digest']==request_digest and r['context_digest']==context_digest and r['daemon_id']==daemon_id
                and r['purpose']==PURPOSE and type(r['nonce']) is str and re.fullmatch('[0-9a-f]{32}',r['nonce'])
                and r['network_name']=='igreja12-cleanup-'+r['nonce'] and _hex(r['network_id'])
                and type(r['containers']) is list and len(r['containers'])==1,CODE)
            c=r['containers'][0]
            require(type(c) is dict and set(c)=={'container_id','image_id','image_reference','name','tmpfs'}
                and _hex(c['container_id']) and c['container_id']!=r['network_id'] and _image(c['image_id'])
                and type(c['image_reference']) is str
                and re.fullmatch(r'(?:sha256:|[A-Za-z0-9._/-]+@sha256:)[0-9a-f]{64}',c['image_reference'])
                and c['name']==r['network_name']+'-0' and c['tmpfs']==[list(v) for v in DATA_TMPFS],CODE)
            record=NativeCleanupContainer(c['container_id'],c['image_id'],c['image_reference'],c['name'],DATA_TMPFS)
            registry=NativeFrozenCleanupRegistry(request_digest,context_digest,daemon_id,r['nonce'],r['network_id'],
                r['network_name'],(record,),_SEAL)
            require(registry.digest==expected_registry_digest,CODE)
            duplicate=os.dup(fd)
            require(_fd_pin(os.fstat(duplicate))==_fd_pin(info),CODE)
            obj=object.__new__(cls)
            obj.registry,obj.registry_digest,obj.config_digest=registry,expected_registry_digest,config_digest
            obj._password=value['password'];obj._fd=duplicate;obj._fd_pin=_fd_pin(info)
            obj._input_sha=hashlib.sha256(raw).hexdigest();obj._used=False;obj._pid=os.getpid()
            obj._metadata_pin=digest(dict(registry=registry.public(),registry_digest=expected_registry_digest,
                config_digest=config_digest,password=value['password']))
            return obj
        except Exception:
            if duplicate is not None:os.close(duplicate)
            raise Refused('native-parent-clone-handoff') from None
        except BaseException:
            if duplicate is not None:os.close(duplicate)
            raise KeyboardInterrupt from None

    def validate(self):
        try:
            require(os.getpid()==self._pid and self.registry.digest==self.registry_digest and self._fd is not None
                and digest(dict(registry=self.registry.public(),registry_digest=self.registry_digest,
                    config_digest=self.config_digest,password=self._password))==self._metadata_pin
                and _fd_pin(os.fstat(self._fd))==self._fd_pin and fcntl.fcntl(self._fd,1034)&15==15
                and hashlib.sha256(os.pread(self._fd,2097153,0)).hexdigest()==self._input_sha,CODE)
        except Exception:raise Refused('native-parent-clone-handoff') from None

    def consume(self):
        self.validate();require(not self._used,'native-parent-clone-used');self._used=True

    def __enter__(self):self.validate();return self
    def __exit__(self,*_exc):self.close()


    def close(self):
        if self._fd is not None:
            try:
                info=os.fstat(self._fd)
                if (info.st_dev,info.st_ino)==self._fd_pin[:2]:os.close(self._fd)
            except OSError:pass
            self._fd=None
        self._password=None


class _ProvisionCLI(PopenRunner):
    def __init__(self,owner,**kwargs):
        self.owner=owner
        super().__init__(**kwargs)
    def _allowed(self,argv):return argv in self.owner.allowed_argv()
    def _env(self):return {**super()._env(),**self.owner._secret_env}


class NativeParentCloneProvisioner:
    """Explicit pre-worker creation, frozen registration and sealed private FD.

    provision() retains its cooperative deadline. provision_bounded() places
    every I/O callback in a reaped helper and reserves failure cleanup within
    its separate total deadline; the later worker/outer budget starts after it.
    A failed/unacknowledged create can leave an
    UNKNOWN resource: inventory refuses rather than adopting it by name/label.
    The caller must run .cleanup after worker reaping, including worker failure.
    close() closes only the private FD; it never deletes daemon resources.
    """
    def __init__(self,config,*,request_digest,context_digest,daemon_id,image_id,runner=None,
                 clock=None,wall_clock=None):
        from first_transition_window_backup import WindowBackupConfig
        require(type(config) is WindowBackupConfig and _image(image_id)
                and (runner is None or callable(runner)) and (clock is None or callable(clock))
                and (wall_clock is None or callable(wall_clock)),CODE)
        config.validated()
        require(config.clone_command in ((),PARENT_CLONE_COMMAND)
            and config.admin_user==config.restore_user==config.migration_user=='postgres',CODE)
        self.config=config;self._original_config=config;self._config_digest=digest(asdict(config))
        self._builder=NativeCleanupRegistry(request_digest,context_digest,daemon_id)
        self.image_id=image_id;self._image_pin=image_id
        self.clock,self.wall_clock=clock or time.monotonic,wall_clock or time.time
        self._injected=runner;self._secret_env={}
        self._cli=runner if runner is not None else _ProvisionCLI(self,docker_binary=config.docker_binary,
            endpoint=config.docker_endpoint,config_dir=config.docker_config_dir,cleanup_wait=.1)
        self._cli_original=self._cli;self._used=False
        self._registry=self._cleanup=None;self._fd=None;self._password=None;self._handoff_pin=None
        self._process_boundary=None;self._bounded_used=False;self._pending_creation=None
        self._bounded_diag=None;self._bounded_cleanup=None

    def __repr__(self):return '<NativeParentCloneProvisioner private>'
    def __enter__(self):return self
    def __exit__(self,*_exc):self.close()
    @property
    def registry(self):
        require(self._registry is not None,CODE);return self._registry
    @property
    def cleanup(self):
        require(self._cleanup is not None,CODE);return self._cleanup
    @property
    def handoff_fd(self):
        require(self._fd is not None and _fd_pin(os.fstat(self._fd))==self._handoff_pin
            and fcntl.fcntl(self._fd,1034)&15==15,CODE)
        return self._fd

    def _network_create(self):
        labels=tuple(value for k,v in sorted(self._builder.labels('network').items()) for value in ('--label',k+'='+v))
        return ('docker','network','create','--internal',*labels,self._builder.network_name)
    def _container_create(self):
        labels=tuple(value for k,v in sorted(self._builder.labels('container').items()) for value in ('--label',k+'='+v))
        return ('docker','create','--pull=never','--name',self._builder.container_name(),
            '--network',self._builder._network,'--restart=no','--tmpfs',
            '/var/lib/postgresql/data:rw,nosuid,nodev,noexec,size=536870912',*labels,
            '-e','POSTGRES_PASSWORD','-e','PGDATA=/var/lib/postgresql/data',self.config.clone_image,*PARENT_CLONE_COMMAND)
    def allowed_argv(self):
        return frozenset((('docker','info','--format','{{json .ID}}'),
            ('docker','image','inspect','--format','[{{json .Id}}]',self.config.clone_image),
            ('docker','ps','-a','--filter','name=^/'+self._builder.container_name()+'$','--format','{{.ID}}'),
            ('docker','network','ls','--filter','name=^'+self._builder.network_name+'$','--format','{{.ID}}'),
            self._network_create(),self._container_create()))
    def _remaining(self):
        left=self._deadline-self.clock();require(_number(left) and left>0,CODE);return min(10,left)
    def _call(self,argv,*,env=None):
        require(self._cli is self._cli_original and digest(asdict(self.config))==self._config_digest
            and self.image_id==self._image_pin and argv in self.allowed_argv(),CODE)
        if self._injected is None:
            require(type(self._cli) is _ProvisionCLI and self._cli.owner is self and self._cli.popen is None
                and (self._cli.docker_binary,self._cli.endpoint,self._cli.config_dir)==
                    (self._original_config.docker_binary,self._original_config.docker_endpoint,self._original_config.docker_config_dir),CODE)
        self._secret_env=env or {}
        try:
            if self._process_boundary is None:
                if self._injected is None:rc,raw=self._cli(argv,timeout=self._remaining(),max_output=65536)
                else:rc,raw=self._cli(argv,timeout=self._remaining(),max_output=65536,env=env)
            else:
                creating=argv[:3]==('docker','network','create') or argv[:2]==('docker','create')
                if creating:self._pending_creation=argv[1]
                def invoke():
                    if self._injected is None:code,value=self._cli(argv,timeout=self._remaining(),max_output=65536)
                    else:code,value=self._cli(argv,timeout=self._remaining(),max_output=65536,env=env)
                    require(type(code) is int and type(value) is bytes and len(value)<=65536
                        and getattr(self._cli,'unreaped',0)==0,CODE)
                    return dict(rc=code,stdout_base64=base64.b64encode(value).decode('ascii'))
                packet=self._process_boundary.attempt(invoke,deadline=self._deadline)
                require(type(packet) is dict and set(packet)=={'rc','stdout_base64'}
                    and type(packet['rc']) is int and type(packet['stdout_base64']) is str,CODE)
                rc=packet['rc'];raw=base64.b64decode(packet['stdout_base64'],validate=True)
        finally:self._secret_env={}
        require(type(rc) is int and rc==0 and type(raw) is bytes and len(raw)<=65536,CODE)
        if self._process_boundary is None:require(getattr(self._cli,'unreaped',0)==0,CODE)
        self._remaining();return raw

    def _finalize(self):
        if self._registry is None:
            self._registry=self._builder.freeze()
            cfg=self._original_config
            self._cleanup=NativeDockerCleanup(self._registry,docker_binary=cfg.docker_binary,endpoint=cfg.docker_endpoint,
                config_dir=cfg.docker_config_dir,runner=self._injected,clock=self.clock,wall_clock=self.wall_clock)

    def provision(self,*,deadline):
        require(not self._used,CODE);self._used=True
        try:
            start=self.clock();require(_number(deadline) and deadline>start,CODE);self._deadline=min(deadline,start+30)
            require(json.loads(self._call(('docker','info','--format','{{json .ID}}')))==self._builder._daemon,CODE)
            require(json.loads(self._call(('docker','image','inspect','--format','[{{json .Id}}]',self.config.clone_image)))==[self.image_id],CODE)
            require(not self._call(('docker','ps','-a','--filter','name=^/'+self._builder.container_name()+'$','--format','{{.ID}}')).strip()
                and not self._call(('docker','network','ls','--filter','name=^'+self._builder.network_name+'$','--format','{{.ID}}')).strip(),CODE)
            network=self._call(self._network_create()).decode('ascii').strip()
            self._builder.created_network(network)
            self._pending_creation=None  # ACK: only now is the returned ID registered in this parent.
            self._password=secrets.token_hex(24)
            container=self._call(self._container_create(),env={'POSTGRES_PASSWORD':self._password}).decode('ascii').strip()
            self._builder.created_container(container,image_id=self.image_id,image_reference=self.config.clone_image)
            self._pending_creation=None
            self._finalize()
            if self._process_boundary is None:
                present,network_present=self._cleanup.inspect_registered(deadline=self._deadline)
            else:
                def inspect():
                    present,network=self._cleanup.inspect_registered(deadline=self._deadline)
                    return dict(present=sorted(present),network=network)
                checked=self._process_boundary.attempt(inspect,deadline=self._deadline)
                require(type(checked) is dict and set(checked)=={'present','network'}
                    and type(checked['present']) is list and all(_hex(v) for v in checked['present'])
                    and checked['network'] is True,CODE)
                present,network_present=set(checked['present']),checked['network']
            require(present=={container} and network_present,CODE)
            raw=json.dumps(dict(schema=PARENT_HANDOFF_SCHEMA,registry=self.registry.public(),
                registry_digest=self.registry.digest,config_digest=self._config_digest,password=self._password),
                sort_keys=True,separators=(',',':'),allow_nan=False).encode()
            self._fd=_seal_private(raw);self._handoff_pin=_fd_pin(os.fstat(self._fd))
            self._remaining()
            return self
        except Exception:
            self._finalize();self.close()
            raise Refused('native-parent-clone-provisioning') from None
        except BaseException:
            self._finalize();self.close()
            raise KeyboardInterrupt from None

    def close(self):
        if self._fd is not None:
            try:
                info=os.fstat(self._fd)
                if (info.st_dev,info.st_ino)==self._handoff_pin[:2]:os.close(self._fd)
            except OSError:pass
            self._fd=None
        self._password=None;self._secret_env={}


    def bounded_diagnostics(self):
        """Parent-observed provisioning scope, never a source/A8 authorization."""
        return deepcopy(self._bounded_diag)

    def _bounded_cleanup_child(self,deadline):
        observation=self.cleanup(request_digest=self.registry.request_digest,context_digest=self.registry.context_digest,
            result=None,status='worker-failed',deadline=deadline,worker_cleanup_uncertain=False)
        evidence=self.cleanup.validate_observation(observation)
        return dict(observation=asdict(observation),evidence=asdict(evidence),evidence_digest=evidence.digest)

    def _bounded_cleanup_validate(self,value):
        ids=sorted(([self.registry.network_id] if self.registry.network_id else [])+
                   [c.container_id for c in self.registry.containers])
        require(type(value) is dict and set(value)=={'observation','evidence','evidence_digest'},CODE)
        o,e=value['observation'],value['evidence']
        require(type(o) is dict and set(o)=={'request_digest','context_digest','job_binding_digest','status','daemon_id',
            'inspected_resource_ids','absent_resource_ids'} and o['request_digest']==self.registry.request_digest
            and o['context_digest']==self.registry.context_digest and o['job_binding_digest'] is None
            and o['status']=='worker-failed' and o['daemon_id']==self.registry.daemon_id
            and o['inspected_resource_ids']==o['absent_resource_ids']==ids,CODE)
        require(type(e) is dict and set(e)==set(NativeCleanupDaemonEvidence.__dataclass_fields__)
            and e['observation_sha256']==digest(o) and e['registry_digest']==self.registry.digest
            and digest(e)==value['evidence_digest'] and e['transport']==self.cleanup._transport
            and all(e[k] is False for k in ('daemon_cleanup_authoritative','cleanup_hard_deadline_verified',
                'source_unchanged_proven','a8_window_proven','production_ready')),CODE)
        return deepcopy(value)

    def _bounded_cleanup_attempt(self,boundary,deadline,stop_budget_s):
        self._finalize()
        self._bounded_diag['cleanup_attempted']=True
        interrupted=False
        try:
            value=boundary.attempt(lambda:self._bounded_cleanup_child(deadline-stop_budget_s),deadline=deadline)
            self._bounded_cleanup=self._bounded_cleanup_validate(value)
            # Absence now cannot resolve an unacknowledged async create.
            self._bounded_diag['parent_cleanup_completed']=not self._bounded_diag['unknown_resources_possible']
        except Exception:pass
        except BaseException:interrupted=True
        finally:
            self._bounded_diag['cleanup_reaped']=boundary.last_reaped
            # Spend the original, never fabricate its fork-copy observation.
            self.cleanup._used=True
        return interrupted

    def provision_bounded(self,*,timeout_s=30,cleanup_budget_s=5,stop_budget_s=.3):
        """Total creation/handoff OR failed-attempt finalization budget.

        Only trusted bounded-size parsing, registry ACKs and sealed-memfd work
        occur in this parent. Every CLI/callback and inspection runs in a fork.
        Successful handoff intentionally leaves HELD resources for the later
        job/outer cleanup. Failure reserves a separately bounded cleanup fork.
        Unacknowledged remote creates stay UNKNOWN, never adopted by labels.
        Kernel stalls and asynchronous daemon work remain explicit limitations.
        """
        from first_transition_native_outer import NativeProcessBoundary
        require(not self._used and not self._bounded_used,CODE)
        self._bounded_used=True
        start=_REAL_MONOTONIC();deadline=start+timeout_s if _number(timeout_s) else start
        self._bounded_diag=dict(staged_complete=False,deadline_enforced=False,creation_helpers_reaped=False,
            cleanup_attempted=False,cleanup_reaped=False,parent_cleanup_completed=False,process_cleanup_verified=False,
            unknown_resources_possible=False,held_resources_pending=False,
            daemon_cleanup_authoritative=False,cleanup_hard_deadline_verified=False,
            authoritative_fence_proven=False,source_unchanged_proven=False,a8_window_proven=False,production_ready=False)
        failure=interrupted=False;boundary=None;success=False
        try:
            require(_number(timeout_s) and 0<timeout_s<=30 and _number(cleanup_budget_s)
                and _number(stop_budget_s) and 0<stop_budget_s<=2
                and cleanup_budget_s>stop_budget_s+.1
                and timeout_s-cleanup_budget_s>stop_budget_s+.2
                and self.clock is _REAL_MONOTONIC and self.wall_clock is _REAL_WALL
                and time.monotonic is _REAL_MONOTONIC and time.time is _REAL_WALL,CODE)
            boundary=NativeProcessBoundary(stop_budget_s=stop_budget_s)
            with boundary:
                self._process_boundary=boundary
                self._bounded_diag['deadline_enforced']=True
                try:
                    self.provision(deadline=deadline-cleanup_budget_s)
                    success=True
                except Exception:failure=True
                except BaseException:failure=interrupted=True
                self._bounded_diag['creation_helpers_reaped']=boundary.last_reaped
                self._bounded_diag['unknown_resources_possible']=self._pending_creation is not None and boundary.last_started
                if failure and boundary.last_reaped:
                    interrupted=self._bounded_cleanup_attempt(boundary,deadline,stop_budget_s) or interrupted
                self._bounded_diag['process_cleanup_verified']=boundary.last_reaped
        except Exception:failure=True
        except BaseException:failure=interrupted=True
        finally:
            self._process_boundary=None
            if failure and boundary is not None and self._registry is not None and not self._bounded_diag['cleanup_attempted']:
                # Context exit or parent observation can fail after HELD IDs
                # were registered. Recover only our original role and tree,
                # then finalize independently within the SAME total deadline.
                try:
                    boundary.recover()
                    self._bounded_diag['unknown_resources_possible']=self._pending_creation is not None
                    require(deadline-_REAL_MONOTONIC()>stop_budget_s,CODE)
                    with NativeProcessBoundary(stop_budget_s=stop_budget_s) as finalizer:
                        interrupted=self._bounded_cleanup_attempt(finalizer,deadline,stop_budget_s) or interrupted
                        self._bounded_diag['process_cleanup_verified']=finalizer.last_reaped
                except Exception:pass
                except BaseException:interrupted=True
            self._used=True
            self._bounded_diag['elapsed_s']=_REAL_MONOTONIC()-start
            if failure or not success:self.close()
        accepted=success and not failure and self._bounded_diag['process_cleanup_verified'] and _REAL_MONOTONIC()<deadline
        self._bounded_diag['held_resources_pending']=not accepted and not self._bounded_diag['parent_cleanup_completed'] and (
            self._registry is not None and bool(self._registry.network_id or self._registry.containers)
            or self._bounded_diag['unknown_resources_possible'])
        if not accepted:self.close()
        if interrupted:raise KeyboardInterrupt from None
        require(accepted,CODE)
        self._bounded_diag['staged_complete']=True
        return self
