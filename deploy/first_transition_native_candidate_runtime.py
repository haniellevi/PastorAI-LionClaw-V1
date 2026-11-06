"""Pinned mounts/entrypoint and main-PID admission for the native candidate.

Only the backend may start. Consumers stay held. Preparation is public data;
live CA proof comes from the pinned probe's kernel FD observation and Unix
peer PID, while the bootstrap waits before importing the app. This adapter
does not admit a source fence, A8 or the production factory.
"""
from dataclasses import asdict,dataclass
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time

from first_transition_adapter import digest,ROLES
from first_transition_host_driver import INFO_ARGV
from first_transition_native_candidate_ca import CandidateCAProfile
from first_transition_window_backup import NativeWindowArtifacts
from initial_transition_ops import Refused,require

CODE='native-candidate-runtime-refused'
TARGET='/run/igreja12/native-runtime'
CA='/run/igreja12/native-ca.crt'
MODULES=('first_transition_native_candidate_admission.py','first_transition_native_candidate_bootstrap.py',
         'first_transition_native_candidate_ca.py')
FIELDS=dict(id='.Id',image='.Image',configured_image='.Config.Image',entrypoint='.Config.Entrypoint',
    command='.Config.Cmd',user='.Config.User',privileged='.HostConfig.Privileged',
    restart_policy='.HostConfig.RestartPolicy.Name',pid_mode='.HostConfig.PidMode',pid='.State.Pid',started='.State.StartedAt',
    running='.State.Running',restarts='.RestartCount',project='index .Config.Labels "com.docker.compose.project"',
    service='index .Config.Labels "com.docker.compose.service"',name='.Name',network_mode='.HostConfig.NetworkMode',
    path='.Path',args='.Args',revision='index .Config.Labels "org.opencontainers.image.revision"')
TEMPLATE=('{'+','.join('"'+k+'":{{json ('+v+')}}' for k,v in FIELDS.items())+
    ',"mounts":[{{range .Mounts}}[{{json .Type}},{{json .Source}},{{json .Destination}},{{json .RW}}],{{end}}null]'+
    ',"networks":[{{range $name,$net := .NetworkSettings.Networks}}[{{json $name}},{{json $net.NetworkID}}],{{end}}null]}')
PROBE=r'''
import importlib.util,json,sys,os
from pathlib import Path
assert {v for v in os.listdir('/proc') if v.isdecimal()}=={'1',str(os.getpid())}
root=Path('/run/igreja12/native-runtime')
spec=importlib.util.spec_from_file_location('igreja12_candidate_admission_runtime',root/'first_transition_native_candidate_admission.py')
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
profile=module.load_profile(root/'profile.json')
value=module.acknowledge_candidate(profile,sys.argv[1],expected_main_pid=1,expected_uid=int(sys.argv[2]),timeout=8)
print(json.dumps(value,sort_keys=True,separators=(',',':')))
'''
OBSERVE=r'''
import importlib.util,json,sys
from pathlib import Path
root=Path('/run/igreja12/native-runtime')
spec=importlib.util.spec_from_file_location('igreja12_candidate_ca_observer',root/'first_transition_native_candidate_ca.py')
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
marker=json.loads(sys.argv[3])
value=module.observe_candidate_ca(marker,expected_pid=1,expected_profile_sha256=sys.argv[1],expected_ca_sha256=sys.argv[2])
print(json.dumps(value,sort_keys=True,separators=(',',':')))
'''


@dataclass(frozen=True)
class NativeCandidateRuntimePins:
    profile_sha256:str
    candidate_spec_sha256:str
    module_sha256:tuple
    uid:int


def _hash(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None
def _bytes(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def _pin(s):return tuple(getattr(s,k) for k in ('st_dev','st_ino','st_uid','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns'))


class NativeCandidateRuntime:
    def __init__(self,*,spec,transports,request_digest,root,pins,owner=0,clock=None):
        from first_transition_candidate import CandidateSpec
        from first_transition_native_transports import NativeSourceTransports
        require(type(spec) is CandidateSpec and type(transports) is NativeSourceTransports
            and type(pins) is NativeCandidateRuntimePins and _hash(request_digest)
            and type(owner) is int and owner>=0 and type(root) is str
            and Path(root).is_absolute() and '..' not in Path(root).parts
            and type(pins.uid) is int and pins.uid==10001 and _hash(pins.profile_sha256)
            and pins.candidate_spec_sha256==digest(asdict(spec)) and type(pins.module_sha256) is tuple
            and tuple(k for k,_ in pins.module_sha256)==MODULES
            and all(_hash(v) for _,v in pins.module_sha256),CODE)
        spec.validated();transports.validate(transports.context)
        require(spec.sha==transports.plan.application_sha and spec.native_ca_override is not None,CODE)
        p=transports.policy
        self.profile=CandidateCAProfile(request_digest,digest(transports.context),p.host,p.hostaddr,p.port,CA,
            p.ca_sha256,p.ca_owner,transports.expected.identity).validated()
        require(digest(asdict(self.profile))==pins.profile_sha256,CODE)
        self.spec,self.transports,self.pins,self.owner=spec,transports,pins,owner
        self.root,self.directory=Path(root),Path(root)/request_digest
        self._binding=digest(asdict(pins));self._request=request_digest
        self._transport=transports;self._paths=(str(self.root),str(self.directory))
        self.clock=clock or time.monotonic
        self._fds={};self._root=self._dir=None;self._root_pin=self._dir_pin=None
        self._prepared=self._failed=self._attempted=False
        self._held=None;self._live=None;self._receipt=None

    def _entrypoint(self):return ['/usr/local/bin/python','-I',TARGET+'/'+MODULES[1]]
    def _command(self):return ['--profile',TARGET+'/profile.json','--expect-profile-sha256',self.pins.profile_sha256]
    def _mounts(self):return [['bind',self.transports.policy.ca_file,CA,False],['bind',str(self.directory),TARGET,False]]

    def prepare(self):
        require(not self._prepared and not self._failed,CODE)
        try:
            self._root=NativeWindowArtifacts._directory(str(self.root));s=os.fstat(self._root)
            require(stat.S_ISDIR(s.st_mode) and s.st_uid==self.owner and stat.S_IMODE(s.st_mode)==0o700,CODE)
            self._root_pin=(s.st_dev,s.st_ino,s.st_uid,s.st_mode)
            os.mkdir(self.profile.request_digest,0o755,dir_fd=self._root)
            self._dir=os.open(self.profile.request_digest,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=self._root)
            os.fchmod(self._dir,0o755);s=os.fstat(self._dir);self._dir_pin=(s.st_dev,s.st_ino,s.st_uid,s.st_mode)
            values={'profile.json':_bytes(asdict(self.profile))}
            from initial_transition_files import read_regular
            for name,pin in self.pins.module_sha256:
                raw=read_regular(Path(__file__).resolve().with_name(name),65536)
                require(hashlib.sha256(raw).hexdigest()==pin,CODE);values[name]=raw
            for name,raw in values.items():
                fd=os.open(name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=self._dir)
                self._fds[name]=dict(fd=fd,sha256=hashlib.sha256(raw).hexdigest())
                require(os.write(fd,raw)==len(raw),CODE);os.fchmod(fd,0o444);os.fsync(fd)
                self._fds[name]['pin']=_pin(os.fstat(fd))
            os.fsync(self._dir);os.fsync(self._root);self._prepared=True;self.verify()
        except Exception:
            self._failed=True;self.close();raise Refused(CODE) from None

    def verify(self):
        require(self._prepared and not self._failed,CODE)
        require(digest(asdict(self.pins))==self._binding and self.pins.candidate_spec_sha256==digest(asdict(self.spec))
            and self.pins.profile_sha256==digest(asdict(self.profile)) and self.transports is self._transport
            and self._paths==(str(self.root),str(self.directory)),CODE)
        p=self.transports.policy
        expected=CandidateCAProfile(self._request,digest(self.transports.context),p.host,p.hostaddr,p.port,CA,
            p.ca_sha256,p.ca_owner,self.transports.expected.identity)
        require(self.profile==expected and set(self._fds)==set(MODULES)|{'profile.json'},CODE)
        pins=dict(self.pins.module_sha256);pins['profile.json']=self.pins.profile_sha256
        fresh=NativeWindowArtifacts._directory(str(self.root))
        try:
            for s,pin in ((os.fstat(fresh),self._root_pin),(os.fstat(self._root),self._root_pin),
                          (os.fstat(self._dir),self._dir_pin),
                          (os.stat(self.profile.request_digest,dir_fd=self._root,follow_symlinks=False),self._dir_pin)):
                require((s.st_dev,s.st_ino,s.st_uid,s.st_mode)==pin,CODE)
            require(set(os.listdir(self._dir))==set(MODULES)|{'profile.json'},CODE)
            for name,item in self._fds.items():
                s=os.fstat(item['fd'])
                require(stat.S_ISREG(s.st_mode) and s.st_uid==self.owner and s.st_nlink==1
                    and stat.S_IMODE(s.st_mode)==0o444 and 0<s.st_size<=65536 and _pin(s)==item['pin']
                    ==_pin(os.stat(name,dir_fd=self._dir,follow_symlinks=False))
                    and hashlib.sha256(os.pread(item['fd'],65537,0)).hexdigest()==item['sha256'],CODE)
                require(item['sha256']==pins[name],CODE)
            self.transports.validate(self.transports.context);self.transports.connector._ca()
        finally:os.close(fresh)

    def override(self):
        self.verify()
        ca=dict(type='bind',source=self.transports.policy.ca_file,target=CA,read_only=True,bind=dict(create_host_path=False))
        runtime=dict(type='bind',source=str(self.directory),target=TARGET,read_only=True,bind=dict(create_host_path=False))
        services={role:dict(volumes=[ca]) for role in ROLES}
        services['backend'].update(entrypoint=self._entrypoint(),command=self._command(),volumes=[ca,runtime])
        return _bytes(dict(services=services))+b'\n'

    def inspect_argv(self,cid):return ('docker','inspect','--type','container','--format',TEMPLATE,cid)
    def admission_argv(self,cid):return ('docker','exec',cid,'/usr/local/bin/python','-I','-c',PROBE,self.pins.profile_sha256,str(self.pins.uid))
    def stop_argv(self,cid):return ('docker','stop','--time','1',cid)
    def smoke_argv(self,cid):
        argv=list(self.spec.smoke_argv(cid));argv[3]='/usr/local/bin/python';return tuple(argv)
    def observe_argv(self,cid):
        require(self._receipt is not None and digest(self._receipt)==self._receipt_digest,CODE)
        marker=dict(self._receipt['admission']);marker.pop('peer_uid');marker['schema']='igreja12.native-candidate-ca-live-fd/1'
        return ('docker','exec',cid,'/usr/local/bin/python','-I','-c',OBSERVE,self.pins.profile_sha256,
            self.profile.ca_sha256,_bytes(marker).decode())

    def _deadline(self,timeout):
        require(type(timeout) in (int,float) and math.isfinite(timeout) and 0<timeout<=30,CODE)
        return self.clock()+timeout
    def _remaining(self,deadline):
        value=deadline-self.clock();require(value>0,CODE);return min(10,value)
    def _call(self,runner,argv,deadline):
        rc,out=runner(argv,timeout=self._remaining(deadline),max_output=131072)
        require(type(rc) is int and rc==0 and type(out) is bytes and len(out)<=131072,CODE)
        self._remaining(deadline);return out

    def _inspect(self,cid,runner,deadline,*,running):
        require(_hash(cid),CODE)
        require(json.loads(self._call(runner,INFO_ARGV,deadline))==self.spec.daemon_id,CODE)
        binding=self._call(runner,self.spec.network_argv(),deadline).splitlines()
        require(len(binding)==2 and all(json.loads(v)==[self.spec.network_id,self.spec.network_name] for v in binding),CODE)
        row=json.loads(self._call(runner,self.inspect_argv(cid),deadline))
        require(type(row) is dict and set(row)==set(FIELDS)|{'mounts','networks'},CODE)
        require(row['id']==cid and row['image']==row['configured_image']==self.spec.image
            and row['project']==self.spec.project and row['service']=='backend'
            and row['name']=='/'+self.spec.names()['backend'] and row['revision']==self.spec.sha
            and row['entrypoint']==self._entrypoint() and row['command']==self._command()
            and row['path']=='/usr/local/bin/python' and row['args']==self._entrypoint()[1:]+self._command()
            and row['user'] in ('appuser','10001') and row['privileged'] is False
            and row['pid_mode']==''
            and row['restart_policy']=='no' and type(row['restarts']) is int and row['restarts']==0
            and type(row['pid']) is int and row['running'] is running
            and row['network_mode'] in (self.spec.network_name,self.spec.network_id),CODE)
        mounts=row['mounts'];networks=row['networks']
        # Docker templates have sentinel nulls; Python fixture projections may
        # use the exact same logical array without its serialization sentinel.
        if type(mounts) is list and mounts[-1:]==[None]:mounts=mounts[:-1]
        if type(networks) is list and networks[-1:]==[None]:networks=networks[:-1]
        require(type(mounts) is list and len(mounts)==2 and all(type(x) is list and len(x)==4
            and type(x[3]) is bool for x in mounts) and sorted(mounts)==sorted(self._mounts()),CODE)
        require(networks==[[self.spec.network_name,self.spec.network_id]] or not running
            and networks==[[self.spec.network_name,'']],CODE)
        if running:require(row['pid']>0 and type(row['started']) is str and row['started']!='0001-01-01T00:00:00Z',CODE)
        else:require(row['pid']==0 and row['started']=='0001-01-01T00:00:00Z',CODE)
        return row

    def pre_start(self,cid,*,runner,timeout=10):
        try:
            require(not self._attempted and (self._held is None or self._held['id']==cid),CODE);self.verify()
            self._held=self._inspect(cid,runner,self._deadline(timeout),running=False)
        except Exception:
            self._failed=True;raise Refused(CODE) from None

    def after_start(self,cid,*,runner,timeout=15):
        require(not self._attempted and self._held is not None and self._held['id']==cid,CODE)
        self._attempted=True
        try:
            self.verify();deadline=self._deadline(timeout)
            before=self._inspect(cid,runner,deadline,running=True);self._live=before
            receipt=json.loads(self._call(runner,self.admission_argv(cid),deadline))
            fields={'schema','request_digest','context_digest','profile_sha256','ca_sha256','pid','process_start_ticks',
                'fd','device','inode','size','seals','peer_uid'}
            require(type(receipt) is dict and set(receipt)==fields and receipt['schema']=='igreja12.native-candidate-admission/1'
                and receipt['request_digest']==self.profile.request_digest and receipt['context_digest']==self.profile.context_digest
                and receipt['profile_sha256']==self.pins.profile_sha256 and receipt['ca_sha256']==self.profile.ca_sha256
                and type(receipt['pid']) is int and receipt['pid']==1
                and type(receipt['peer_uid']) is int and receipt['peer_uid']==self.pins.uid
                and all(type(receipt[k]) is int and receipt[k]>0 for k in ('process_start_ticks','fd','device','inode','size','seals'))
                and receipt['seals']==15 and receipt['size']<=65536,CODE)
            after=self._inspect(cid,runner,deadline,running=True);self.verify()
            require(before['pid']==after['pid'] and before['started']==after['started'],CODE)
            self._receipt=dict(schema='igreja12.native-candidate-runtime/1',container_id=cid,host_pid=before['pid'],
                started=before['started'],profile_sha256=self.pins.profile_sha256,admission=receipt,
                bundle_sha256=digest(asdict(self.pins)),ca_lifecycle_admitted=True,
                source_unchanged_proven=False,a8_window_proven=False,operational_ready=False)
            self._receipt_digest=digest(self._receipt)
            return self.observe_live(cid,runner=runner,timeout=self._remaining(deadline))
        except Exception:
            self._failed=True;raise Refused(CODE) from None

    def observe_live(self,cid,*,runner,timeout=10):
        try:
            require(self._receipt is not None and digest(self._receipt)==self._receipt_digest
                and self._receipt['container_id']==cid,CODE)
            self.verify();deadline=self._deadline(timeout)
            before=self._inspect(cid,runner,deadline,running=True)
            require(before['pid']==self._receipt['host_pid'] and before['started']==self._receipt['started'],CODE)
            value=json.loads(self._call(runner,self.observe_argv(cid),deadline))
            keys=('pid','process_start_ticks','device','inode','size','seals','ca_sha256')
            require(type(value) is dict and set(value)==set(keys) and all(type(value[k]) is type(self._receipt['admission'][k])
                and value[k]==self._receipt['admission'][k] for k in keys),CODE)
            after=self._inspect(cid,runner,deadline,running=True);self.verify()
            require(after['pid']==before['pid'] and after['started']==before['started'],CODE)
            return deepcopy(self._receipt)
        except Exception:
            self._failed=True;raise Refused(CODE) from None

    def abort(self,cid,*,runner,timeout=10):
        """Stop only the held ID this instance bound before issuing its start."""
        require(self._held is not None and self._held['id']==cid,CODE)
        deadline=self._deadline(timeout)
        require(json.loads(self._call(runner,INFO_ARGV,deadline))==self.spec.daemon_id,CODE)
        row=json.loads(self._call(runner,self.inspect_argv(cid),deadline))
        require(row['id']==self._held['id'] and row['image']==self._held['image']
            and row['project']==self._held['project'] and row['name']==self._held['name']
            and row['service']=='backend' and type(row['running']) is bool and type(row['pid']) is int,CODE)
        if row['running']:
            require(row['pid']>0,CODE)
            self._call(runner,self.stop_argv(cid),deadline)  # exit0 is necessary; fresh PID0 below is the proof
        else:require(row['pid']==0,CODE)
        # Stopped containers retain StartedAt; never mistake them for held.
        out=json.loads(self._call(runner,self.inspect_argv(cid),deadline))
        require(out['id']==cid and out['image']==self._held['image'] and out['project']==self._held['project']
            and out['running'] is False and type(out['pid']) is int and out['pid']==0,CODE)

    def close(self):
        for item in self._fds.values():
            fd=item['fd']
            try:
                if 'pin' not in item or _pin(os.fstat(fd))[:2]==item['pin'][:2]:os.close(fd)
            except OSError:pass
        self._fds={}
        for fd in (self._dir,self._root):
            if fd is not None:
                try:os.close(fd)
                except OSError:pass
        self._dir=self._root=None
