"""Integrated native exporter/dump/HTTPS fixture; loopback TLS only."""
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import first_transition_native_joint as joint
import first_transition_native_joint_capture as core
import first_transition_native_joint_artifacts as custody
import first_transition_native_job as job
import first_transition_window_backup as wb
from first_transition_adapter import digest
from initial_transition_ops import Refused
from test_first_transition_native_job import rig, plan, SourceCursor  # noqa: F401
from test_first_transition_native_snapshot import Connection, NOW


class Server:
    def __init__(self,context,*,body=b'AB',delay=0):
        self.context,self.body,self.delay = context,body,delay
        self.stop = threading.Event()
        self.requests = []
        self.connection = None

    def __enter__(self):
        self.listener = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        self.listener.bind(('127.0.0.1',0))
        self.listener.listen(1)
        self.listener.settimeout(.05)
        self.port = self.listener.getsockname()[1]
        def serve():
            raw = secured = None
            try:
                while not self.stop.is_set():
                    try:raw,_ = self.listener.accept();break
                    except socket.timeout:continue
                if raw is None:return
                raw.settimeout(3)
                secured = self.context.wrap_socket(raw,server_side=True)
                self.connection = secured
                request = b''
                while b'\r\n\r\n' not in request:
                    chunk = secured.recv(1024)
                    if not chunk:return
                    request += chunk
                self.requests.append(request)
                secured.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nETag: fixture-etag\r\n\r\n')
                if not self.stop.wait(self.delay):secured.sendall(self.body)
            except (OSError,ssl.SSLError):pass
            finally:
                if secured is not None:secured.close()
                if raw is not None:raw.close()
        self.thread = threading.Thread(target=serve,daemon=True)
        self.thread.start()
        return self

    def __exit__(self,*_exc):
        self.stop.set()
        if self.connection is not None:self.connection.close()
        self.listener.close()
        self.thread.join(4)
        assert not self.thread.is_alive()


@pytest.fixture(scope='module')
def tls(tmp_path_factory):
    root = tmp_path_factory.mktemp('synthetic-joint-tls')
    cert,key = root/'server.crt',root/'server.key'
    result = subprocess.run(('/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes',
        '-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=fixture.invalid',
        '-addext','subjectAltName=DNS:fixture.invalid'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        timeout=10,check=False)
    assert result.returncode == 0
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.minimum_version = ssl.TLSVersion.TLSv1_2
    server.load_cert_chain(cert,key)
    return server,(ssl.PEM_cert_to_DER_cert(cert.read_text()),)


def setup(rig,server,tls,tmp_path,monkeypatch):
    for name in joint.environment.__globals__['ENV_BLOCKED']:
        monkeypatch.delenv(name,raising=False)
    def forbidden(*_a,**_k):pytest.fail('DNS is forbidden in numeric loopback fixture')
    monkeypatch.setattr(socket,'getaddrinfo',forbidden)
    endpoint = joint.Endpoint('fixture.invalid',('127.0.0.1',),server.port,'synthetic')
    preserved = [dict(bucket='whatsapp-media',key='fictional/a space/áudio',id='fictional-id',
        version='fictional-version',bytes=2,etag='fixture-etag',sha256=hashlib.sha256(b'AB').hexdigest())]
    pins = joint.NativeJointPins(digest(rig.request),digest(rig.worker.context),
        digest(asdict(rig.worker.connector.policy)),digest(joint.http_policy(endpoint,tls[1],preserved)),
        digest(dict(rig.worker.plan.adapter_sources)))
    root = tmp_path/'joint-private'
    root.mkdir(mode=0o700)
    calls = []
    def guard(request,source,window,started,deadline):
        calls.append((threading.get_ident(),time.monotonic()))
        assert all(not c.closed for c in rig.source.connections[:1])
        return core.WindowEvidence(request,source,window,started-.1,time.time()+30,True)
    capture = joint.NativeSyntheticJointCapture(root=str(root),endpoint=endpoint,ca_der=tls[1],
        preserved_objects=preserved,token='SYNTHETIC-TOKEN-PRIVATE',guard=guard,pins=pins,owner=os.geteuid())
    original = SourceCursor.execute
    def execute(cursor,query,params=None):
        if query == core.CATALOG_SQL:
            c = cursor.connection
            assert not c.importer and c.info.transaction_status == 2
            c.log.append((query,params))
            cursor.rows = [([dict(id=preserved[0]['id'],bucket_id=preserved[0]['bucket'],name=preserved[0]['key'],
                version=preserved[0]['version'],metadata=dict(size=2,eTag='fixture-etag'))],)]
            return
        if query == core.PRESENCE_SQL:
            assert not cursor.connection.importer
            cursor.rows = [({table:False for table in core.REFERENCES},)]
            return
        original(cursor,query,params)
    monkeypatch.setattr(SourceCursor,'execute',execute)
    monkeypatch.setattr(Connection,'cursor',lambda c:SourceCursor(c))
    rig.worker.joint = capture
    return capture,root,calls


def test_same_native_holder_continuous_pulse_https_and_separate_custody(rig,tls,tmp_path,monkeypatch):
    with Server(tls[0],delay=1.1) as server:
        capture,root,calls = setup(rig,server,tls,tmp_path,monkeypatch)
        result = rig.worker.execute(rig.request)
        assert len(server.requests) == 1
        assert b'versionId=fictional-version' in server.requests[0]
    value = result['joint']
    assert value['fixture_scope_only'] and value['aggregates']['same_holder_snapshot_observed']
    assert value['aggregates']['hashed_objects'] == 1 and value['aggregates']['hashed_bytes'] == 2
    assert value['pulse_calls'] >= 1 and value['maximum_pulse_gap_s'] <= 2
    assert calls and {ident for ident,_ in calls} == {threading.get_ident()}
    assert all(c.closed for c in rig.source.connections) and len(rig.source.connections) == 2
    assert len(rig.docker.applied) == 51 and result['cleanup_verified']
    assert not rig.docker.have_container and not rig.docker.have_network
    assert result['binding']['joint_capture_digest'] == digest(value)
    run = root/digest(rig.request)
    assert set(p.name for p in run.iterdir()) == {'storage-projection.sql','storage-manifest.json'}
    manifest = json.loads((run/'storage-manifest.json').read_bytes())
    assert manifest['snapshot']['holder']['backend'] == 1001
    assert manifest['dump']['sha256'] == result['binding']['dump_sha256']
    assert 'storage.objects' in (run/'storage-projection.sql').read_text()
    for flag in ('source_unchanged_proven','authoritative_fence_verified','storage_body_retention_verified',
                 'storage_recovery_verified','a8_window_proven','operational_ready'):
        assert value[flag] is False
    assert 'SYNTHETIC' not in json.dumps(result) and str(root) not in json.dumps(result)
    assert capture._captured


@pytest.mark.parametrize('fault',['request','context','policy','runtime','tls'])
def test_bad_binding_refuses_before_provider_holder_http_or_artifact_dir(rig,tls,tmp_path,monkeypatch,fault):
    with Server(tls[0]) as server:
        capture,root,_ = setup(rig,server,tls,tmp_path,monkeypatch)
        if fault == 'tls':capture._context.check_hostname = False
        else:
            key = {'request':'request_sha256','context':'context_sha256','policy':'source_policy_sha256',
                   'runtime':'runtime_sha256'}[fault]
            capture._pins = replace(capture._pins,**{key:'0'*64})
        def forbidden():pytest.fail('provider opened on preflight refusal')
        rig.worker.connector.secret = forbidden
        with pytest.raises(Refused):rig.worker.execute(rig.request)
        assert server.requests == []
    assert rig.source.connections == [] and list(root.iterdir()) == [] and rig.docker.calls == []


def test_nominal_profile_cannot_substitute_fixture_window_evidence(tls,tmp_path,monkeypatch):
    for name in joint.environment.__globals__['ENV_BLOCKED']:monkeypatch.delenv(name,raising=False)
    endpoint = joint.Endpoint('pffafnchtxbimpwyaczq.supabase.co',('1.1.1.1',))
    pins = joint.NativeJointPins(*(['a'*64]*5))
    with pytest.raises(Refused,match='authoritative-fence-missing'):
        joint.NativeSyntheticJointCapture(root=str(tmp_path),endpoint=endpoint,ca_der=tls[1],preserved_objects=[],
            token='SYNTHETIC-TOKEN',guard=lambda *_:True,pins=pins)


@pytest.mark.parametrize('fault',['guard','body','holder','dump_exit','pulse_gap'])
def test_mid_capture_refusal_closes_source_and_never_starts_recovery(rig,tls,tmp_path,monkeypatch,fault):
    with Server(tls[0],body=b'XX' if fault == 'body' else b'AB') as server:
        capture,_,_ = setup(rig,server,tls,tmp_path,monkeypatch)
        if fault == 'guard':
            capture._guard = lambda r,s,w,a,d:core.WindowEvidence(r,s,w,a,time.time()+30,False)
        elif fault == 'holder':
            original = capture._guard
            def drift(*args):
                rig.source.connections[0].holder_fault = {'backend':1002}
                return original(*args)
            capture._guard = drift
        elif fault == 'dump_exit':rig.source.dump_fault = 'exit'
        elif fault == 'pulse_gap':
            original = job.NativeDump.keepalive
            def late(dumper,snapshot):
                dumper._pulse.last -= 3
                return original(dumper,snapshot)
            monkeypatch.setattr(job.NativeDump,'keepalive',late)
        with pytest.raises(Refused,match='native-job-failed'):rig.worker.execute(rig.request)
    assert all(c.closed for c in rig.source.connections) and rig.source.connections
    assert rig.docker.calls == [] and not rig.docker.have_container and not rig.docker.have_network
    if fault in ('dump_exit','pulse_gap'):assert server.requests == []


def test_dump_pulse_cannot_be_recreated_or_used_after_failed_dump(rig):
    with wb.NativeWindowArtifacts(rig.cfg.backup_root,digest(rig.request),owner=os.geteuid()) as artifacts:
        with wb.NativeSourceSnapshot(rig.worker.connector,rig.worker.expected,wall_clock=lambda:NOW) as snapshot:
            rig.source.dump_fault = 'exit'
            dumper = job.NativeDump(rig.worker.dump_spec,rig.worker.connector,popen=rig.worker.dump_popen)
            with pytest.raises(Refused):dumper.keepalive(snapshot)
            with pytest.raises(Refused):dumper.run(snapshot,artifacts)
            with pytest.raises(Refused):dumper.keepalive(snapshot)


@pytest.mark.parametrize('address',['8.8.8.8','10.1.2.3','0.0.0.0','169.254.1.1','224.0.0.1','::'])
def test_fixture_hostname_does_not_authorize_nonfixture_sql_route(rig,tls,tmp_path,monkeypatch,address):
    with Server(tls[0]) as server:
        capture,root,_ = setup(rig,server,tls,tmp_path,monkeypatch)
        policy = replace(rig.worker.connector.policy,hostaddr=address)
        capture._pins = replace(capture._pins,source_policy_sha256=digest(asdict(policy)))
        with pytest.raises(Refused):capture.preflight(request=rig.request,context=rig.worker.context,
            policy=policy,plan=rig.worker.plan)
        assert server.requests == []
    assert rig.source.connections == [] and list(root.iterdir()) == []


@pytest.mark.parametrize('fault',['revoked_guard','deadline'])
def test_custody_keeps_same_guard_and_earlier_capture_deadline(rig,tls,tmp_path,monkeypatch,fault):
    with Server(tls[0]) as server:
        capture,root,_ = setup(rig,server,tls,tmp_path,monkeypatch)
        original = custody.NativeJointArtifacts._write_private
        def write(store,kind,data,**kwargs):
            result = original(store,kind,data,**kwargs)
            if kind == 'projection':
                if fault == 'deadline':time.sleep(.3)
                else:capture._guard = lambda r,s,w,a,d:core.WindowEvidence(r,s,w,a,time.time()+30,False)
            return result
        monkeypatch.setattr(custody.NativeJointArtifacts,'_write_private',write)
        if fault == 'deadline':
            original_capture = joint.NativeSyntheticJointCapture.capture
            def short(self,**kwargs):
                kwargs['deadline'] = time.monotonic()+.2
                return original_capture(self,**kwargs)
            monkeypatch.setattr(joint.NativeSyntheticJointCapture,'capture',short)
        with pytest.raises(Refused,match='native-job-failed'):rig.worker.execute(rig.request)
    assert rig.docker.calls == [] and all(c.closed for c in rig.source.connections)
    assert (root/digest(rig.request)/'storage-projection.sql').exists()
