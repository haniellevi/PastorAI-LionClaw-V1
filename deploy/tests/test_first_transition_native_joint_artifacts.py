"""Private 16 MiB joint custody on local synthetic files; no source/HTTP IO."""
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import first_transition_native_joint_artifacts as joint
import first_transition_window_backup as backup
from initial_transition_ops import Refused
from test_first_transition_orchestrator import no_real_processes_or_network  # noqa: F401

REQUEST, SOURCE, WINDOW, DUMP = ('a'*64,'b'*64,'c'*64,'d'*64)
TOKEN = '00000003-00000001-1'
BINDING = dict(request_sha256=REQUEST,source_sha256=SOURCE,window_sha256=WINDOW,snapshot_token=TOKEN,dump_sha256=DUMP)
PROJECTION = b'COPY storage.objects (id) FROM stdin;\nSYNTHETIC-PRIVATE\n\\.\n'


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


def manifest(projection=PROJECTION):
    return dict(schema=joint.SCHEMA,request_sha256=REQUEST,source_sha256=SOURCE,window_sha256=WINDOW,
        capture_started_at=1793786400.,snapshot=dict(exported_id=TOKEN,holder=dict(database='postgres',readonly='on',
            isolation='repeatable read',snapshot='10:20:11,12',backend=1001,role='postgres',session_role='postgres',
            transaction_start='1793786400.000')),
        dump=dict(exit_code=0,imported_snapshot=TOKEN,sha256=DUMP,bytes=100),
        sql_projection_sha256=hashlib.sha256(projection).hexdigest(),objects=[dict(bucket='synthetic',key='PRIVATE/key',
            id='synthetic-id',version='version1',bytes=7,etag='etag',sha256='e'*64)],
        authority_verified=False,provider_immutability_verified=False)


@pytest.fixture
def custody(tmp_path):
    root = tmp_path / 'joint-private'
    root.mkdir(mode=0o700)
    with joint.NativeJointArtifacts(str(root),REQUEST,owner=os.geteuid()) as store:
        yield store,root,root/REQUEST


def capture(store, *, projection=PROJECTION, value=None, binding=None, sha=None, pulse=None):
    value = manifest(projection) if value is None else value
    return store.capture_material(projection=projection,manifest=value,
        manifest_sha256=sha or hashlib.sha256(encoded(value)).hexdigest(),
        expected_binding=deepcopy(BINDING) if binding is None else binding,timeout=10,pulse=pulse or (lambda:None))


def test_pair_is_separate_private_sealed_and_keeps_false_authority(custody):
    store,root,run = custody
    value, calls = manifest(),[]
    result = capture(store,value=value,pulse=lambda:calls.append(True))
    assert len(calls) >= 6
    assert result == store.metadata() == dict(request_digest=REQUEST,artifacts={
        'projection':dict(sha256=hashlib.sha256(PROJECTION).hexdigest(),size=len(PROJECTION)),
        'manifest':dict(sha256=hashlib.sha256(encoded(value)).hexdigest(),size=len(encoded(value)))})
    assert set(p.name for p in run.iterdir()) == {'storage-projection.sql','storage-manifest.json'}
    assert root.stat().st_mode & 0o777 == run.stat().st_mode & 0o777 == 0o700
    for kind,data in (('projection',PROJECTION),('manifest',encoded(value))):
        assert (run/store.FILES[kind][0]).stat().st_mode & 0o777 == 0o600
        with store.verified_fd(kind) as fd:
            assert fcntl.fcntl(fd,backup.MEMFD_GET_SEALS) & backup.MEMFD_SEALS == backup.MEMFD_SEALS
            assert os.pread(fd,len(data)+1,0) == data
            with pytest.raises(PermissionError):os.write(fd,b'corrupt')
        with pytest.raises(OSError):os.fstat(fd)
    restored = json.loads((run/'storage-manifest.json').read_bytes())
    assert restored['authority_verified'] is restored['provider_immutability_verified'] is False
    assert 'PRIVATE' not in repr(result) and str(root) not in repr(result)
    assert set(restored) == joint.MANIFEST_FIELDS


def test_exact_16_mib_projection_is_preserved_without_companion_expansion(custody):
    store,_,_ = custody
    data = b'x'*16777216
    result = capture(store,projection=data)
    assert result['artifacts']['projection']['size'] == 16777216
    with store.verified_fd('projection') as fd:
        assert hashlib.sha256(os.pread(fd,len(data)+1,0)).hexdigest() == hashlib.sha256(data).hexdigest()
    assert backup.NativeWindowArtifacts.FILES['companion'][1] == 2097152


@pytest.mark.parametrize('size',[0,16777217])
def test_projection_out_of_bounds_refuses_before_files(custody,size):
    store,_,run = custody
    with pytest.raises(Refused,match='^native-joint-artifact-failed$'):
        capture(store,projection=b'x'*size)
    assert list(run.iterdir()) == []


@pytest.mark.parametrize('field',['request_sha256','source_sha256','window_sha256','snapshot_token','dump_sha256'])
def test_wrong_independent_binding_refuses_before_files(custody,field):
    store,_,run = custody
    binding = deepcopy(BINDING)
    binding[field] = 'f'*64 if field != 'snapshot_token' else '00000003-00000002-1'
    with pytest.raises(Refused):capture(store,binding=binding)
    assert list(run.iterdir()) == []


@pytest.mark.parametrize('fault',['schema','extra','digest','projection-hash','authority','immutability','boolean-authority',
    'boolean-exit','exit','dump-snapshot','dump-size','holder-field','holder-backend','holder-isolation','objects-extra',
    'objects-duplicate','objects-bytes','object-hash','oversize-manifest','nan-time','boolean-time'])
def test_invalid_canonical_manifest_refuses_without_persisting(custody,fault):
    store,_,run = custody
    value, sha = manifest(),None
    if fault == 'schema':value['schema'] = 'invented'
    elif fault == 'extra':value['a8_window_proven'] = True
    elif fault == 'digest':sha = 'f'*64
    elif fault == 'projection-hash':value['sql_projection_sha256'] = 'f'*64
    elif fault == 'authority':value['authority_verified'] = True
    elif fault == 'immutability':value['provider_immutability_verified'] = True
    elif fault == 'boolean-authority':value['authority_verified'] = 0
    elif fault == 'boolean-exit':value['dump']['exit_code'] = False
    elif fault == 'exit':value['dump']['exit_code'] = 1
    elif fault == 'dump-snapshot':value['dump']['imported_snapshot'] = '00000003-00000002-1'
    elif fault == 'dump-size':value['dump']['bytes'] = 104857601
    elif fault == 'holder-field':del value['snapshot']['holder']['transaction_start']
    elif fault == 'holder-backend':value['snapshot']['holder']['backend'] = True
    elif fault == 'holder-isolation':value['snapshot']['holder']['isolation'] = 'read committed'
    elif fault == 'objects-extra':value['objects'][0]['body'] = 'private bytes forbidden'
    elif fault == 'objects-duplicate':value['objects'] *= 2
    elif fault == 'objects-bytes':value['objects'][0]['bytes'] = 1000000001
    elif fault == 'object-hash':value['objects'][0]['sha256'] = 'invented'
    elif fault == 'oversize-manifest':value['objects'][0]['key'] = 'x'*2097152
    elif fault == 'boolean-time':value['capture_started_at'] = True
    else:
        value['capture_started_at'] = float('nan')
        # The caller's digest calculation must not hide the custody refusal.
        sha = 'f'*64
    with pytest.raises(Refused,match='^native-joint-artifact-failed$'):
        capture(store,value=value,sha=sha)
    assert list(run.iterdir()) == []


@pytest.mark.parametrize('mutation',['symlink','hardlink','replace','rewrite','run-rename','root-rename','mode'])
def test_drift_refuses_before_any_consumer_prefix(custody,mutation):
    store,root,run = custody
    capture(store)
    path = run/'storage-projection.sql'
    if mutation == 'symlink':
        path.rename(run/'old');path.symlink_to(run/'old')
    elif mutation == 'hardlink':os.link(path,run/'alias')
    elif mutation == 'replace':
        path.rename(run/'old');path.write_bytes(PROJECTION);path.chmod(0o600)
    elif mutation == 'rewrite':path.write_bytes(b'changed')
    elif mutation == 'run-rename':
        run.rename(root/('f'*64));run.mkdir(mode=0o700)
    elif mutation == 'root-rename':
        root.rename(root.parent/'old-root');root.mkdir(mode=0o700)
    else:path.chmod(0o644)
    read,write = os.pipe2(os.O_NONBLOCK|os.O_CLOEXEC)
    try:
        with pytest.raises(Refused):store.copy_verified('projection',write,timeout=1)
        with pytest.raises(BlockingIOError):os.read(read,1024)
    finally:os.close(read);os.close(write)


def test_drift_during_staging_delivers_no_unverified_prefix(custody,monkeypatch):
    store,_,run = custody
    capture(store)
    original = backup.os.memfd_create
    def changed(*args):
        fd = original(*args)
        (run/'storage-manifest.json').write_bytes(b'changed-private-manifest')
        return fd
    monkeypatch.setattr(backup.os,'memfd_create',changed)
    read,write = os.pipe2(os.O_NONBLOCK|os.O_CLOEXEC)
    try:
        with pytest.raises(Refused):store.copy_verified('projection',write,timeout=1)
        with pytest.raises(BlockingIOError):os.read(read,1024)
    finally:os.close(read);os.close(write)


def test_second_pair_and_unvalidated_capture_cannot_overwrite(custody):
    store,_,run = custody
    capture(store)
    with pytest.raises(Refused):store.capture('projection',123,timeout=1)
    with pytest.raises(Refused):capture(store)
    assert (run/'storage-projection.sql').read_bytes() == PROJECTION


def test_request_directory_never_adopted_or_reused(custody):
    store,root,_ = custody
    capture(store)
    with pytest.raises(Refused):
        with joint.NativeJointArtifacts(str(root),REQUEST,owner=os.geteuid()):pytest.fail('adopted request')


def test_failed_pulse_retains_only_private_partial_evidence(custody):
    store,_,run = custody
    calls = []
    def pulse():
        calls.append(True)
        if len(calls) == 4:raise RuntimeError('PRIVATE-secret')
    with pytest.raises(Refused,match='^native-joint-artifact-failed$') as error:capture(store,pulse=pulse)
    assert 'PRIVATE' not in str(error.value)
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in run.iterdir())
    with pytest.raises(Refused):store.metadata()


def test_symlink_ancestor_and_wrong_owner_refuse_before_request(tmp_path):
    actual = tmp_path/'actual';actual.mkdir(mode=0o700)
    link = tmp_path/'link';link.symlink_to(actual,target_is_directory=True)
    for root,owner in ((link,os.geteuid()),(actual,os.geteuid()+1)):
        with pytest.raises(Refused):
            with joint.NativeJointArtifacts(str(root),REQUEST,owner=owner):pytest.fail('unsafe root')
    assert list(actual.iterdir()) == []
