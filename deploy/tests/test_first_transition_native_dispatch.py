"""C2 lifecycle + actual supervised child, over fictional host/DB boundaries."""
from dataclasses import replace
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from first_transition_adapter import prepare,digest,adapter_sources
from first_transition_database import DatabaseExpectation,LedgerProof
from first_transition_native_events import NativeWindowEvents
from first_transition_native_supervision import NativeSupervisedWindow,NativeSupervisionPins,NativeCleanupObservation
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA
from initial_transition_ops import Refused
from c2_lifecycle_fixture import SessionFixture
from test_first_transition_native_supervision import WORKER,PRIVATE,input_fd,job_result


@pytest.fixture
def tmp_path():
    with tempfile.TemporaryDirectory(prefix='i12-dispatch-',dir='/tmp') as directory:
        yield Path(directory)


def feature():
    try:return importlib.import_module('first_transition_native_dispatch')
    except ModuleNotFoundError:pytest.fail('native C2 dispatcher is not implemented')


@pytest.fixture
def case(tmp_path,request):
    from first_transition_native_gates import NativeDispatchGates,NativeDispatchPins
    concrete=getattr(request,'param',False)
    p=prepare(Path(__file__).resolve().parents[2]);f=SessionFixture(tmp_path);g=f.guards
    g.expected=DatabaseExpectation('a'*64,p.baseline,'b'*64)
    g.ledger=LedgerProof(g.db,g.expected,scope=g.scope)
    request=dict(schema=BACKUP_REQUEST_SCHEMA,nonce='0'*64,plan_digest=p.digest,source_identity=g.expected.identity,
        baseline_digest=g.expected.baseline_digest,config_digest='3'*64,quiescence_digest='4'*64)
    context=dict(schema='synthetic-dispatch-context/1',source_identity=g.expected.identity,plan_digest=p.digest,
        baseline_digest=g.expected.baseline_digest,config_digest='3'*64)
    wall=lambda:1000+(g.now-100)
    g.wall_clock=wall
    g.nonce=request['nonce']
    g.admission=replace(g.admission,request_digest=digest(request),nonce=request['nonce'])
    for doc in g.docs.values():
        doc['request_digest']=digest(request)
        doc['nonce']=request['nonce']
        if 'baseline_digest' in doc:doc['baseline_digest']=g.expected.baseline_digest
    g.write_receipts();g.guard=g.make_guard()
    session=f.session();calls=[]
    def cleanup(**args):
        calls.append(args)
        result=args['result'];ids=() if result is None else (result['binding']['container_id'],result['binding']['network_id'])
        return NativeCleanupObservation(args['request_digest'],args['context_digest'],None if result is None else result['binding_digest'],
            args['status'],f.world.manifest.daemon_id,ids,ids)
    docker=registry=None
    if concrete:
        import first_transition_native_cleanup as module
        from test_first_transition_native_cleanup import Docker
        builder=module.NativeCleanupRegistry(digest(request),digest(context),f.world.manifest.daemon_id)
        builder.created_network('fe'*32)
        builder.created_container('dc'*32,image_id='sha256:'+'8'*64)
        registry=builder.freeze();docker=Docker(module,registry)
        cleanup=module.NativeDockerCleanup(registry,docker_binary='/usr/bin/docker',endpoint='unix:///tmp/fictional.sock',
            config_dir='/tmp/fictional-private-config',runner=docker,clock=f.clock,wall_clock=wall)
    argv=(sys.executable,'-I','-c',WORKER)
    sup=NativeSupervisedWindow(argv,NativeSupervisionPins(digest(request),digest(context),digest(dict(p.adapter_sources)),
        digest(argv),'0'*64,'1'*64,parent_registry_sha256=registry.digest if concrete=='parent' else None),
        plan=p,runtime_sources=adapter_sources,cleanup=cleanup,
        timeout_s=3,cleanup_budget_s=1,clock=f.clock,wall_clock=wall)
    gates=NativeDispatchGates(request,context,p,f.world.manifest,
        NativeDispatchPins(digest(request),digest(context),p.digest,digest(dict(p.adapter_sources)),f.world.manifest.digest,g.expected.identity),
        c2_session=session,supervisor=sup,runtime_sources=adapter_sources,clock=f.clock,wall_clock=wall)
    value=job_result(p,request);value['binding']['context_digest']=digest(context)
    value['binding']['daemon_id']=f.world.manifest.daemon_id
    if registry is not None:
        value['binding'].update(container_id=registry.containers[0].container_id,network_id=registry.network_id,
            image_id=registry.containers[0].image_id)
        if concrete=='parent':
            value['binding']['parent_registry_digest']=registry.digest
            value.update(cleanup_verified=False,parent_cleanup_required=True)
    events=NativeWindowEvents(digest(request),digest(context),clock=f.clock,wall_clock=wall)
    for method in ('capture_start','source_frontends_closed','capture_finish','recovery_start','recovery_finish','cleanup_finish','result'):
        getattr(events,method)()
    value['events']=events.public();value['binding']['events_sha256']=events.digest
    value['binding_digest']=digest(value['binding'])
    fd=input_fd(dict(private=PRIVATE,job=value))
    try:yield dict(f=f,g=g,gates=gates,sup=sup,calls=calls,fd=fd,request=request,context=context,docker=docker)
    finally:
        try:os.close(fd)
        except OSError:pass


def test_actual_c2_precedes_capture_and_receipt_never_admits_ddl(case):
    owned=feature().NativeC2Dispatcher(case['gates'])
    result=owned.run(input_fd=case['fd'])
    assert case['f'].effects==['restart-no','TERM']
    assert case['sup'].diagnostics()['worker_reaped'] and len(case['calls'])==1
    assert owned.stage=='staged-complete' and owned.uncertain is False
    assert result['source_unchanged_proven'] is result['a8_window_proven'] is result['operational_dispatch_enabled'] is False
    assert result['ddl_authorized'] is False and PRIVATE not in json.dumps(result)
    assert owned.validate_result(result)==result
    os.fstat(case['fd'])  # the dispatcher borrows, never closes the caller's input
    with pytest.raises(Refused):owned.run(input_fd=case['fd'])
    assert len(case['calls'])==1 and case['f'].effects==['restart-no','TERM']


@pytest.mark.parametrize('case',[True],indirect=True)
def test_concrete_registered_cleanup_composes_with_c2_and_actual_child(case):
    result=feature().NativeC2Dispatcher(case['gates']).run(input_fd=case['fd'])
    assert len(case['docker'].mutations)==2
    assert not case['docker'].containers and not case['docker'].networks
    assert result['source_unchanged_proven'] is result['operational_dispatch_enabled'] is False
    assert case['sup'].diagnostics()['daemon_cleanup_verified'] is False  # injected daemon


def test_unsealed_input_refuses_before_any_host_containment(case):
    owned=feature().NativeC2Dispatcher(case['gates']);fd=os.memfd_create('unsealed-fictional-input',os.MFD_CLOEXEC)
    try:
        os.write(fd,b'private')
        with pytest.raises(Refused):owned.run(input_fd=fd)
    finally:os.close(fd)
    assert case['f'].effects==[] and case['calls']==[]


def test_write_only_sealed_input_refuses_before_host_containment(case):
    owned=feature().NativeC2Dispatcher(case['gates'])
    fd=os.open('/proc/self/fd/'+str(case['fd']),os.O_WRONLY|os.O_CLOEXEC)
    try:
        with pytest.raises(Refused):owned.run(input_fd=fd)
    finally:os.close(fd)
    assert case['f'].effects==[] and case['calls']==[]


def test_missing_fence_refuses_operational_dispatch_without_ports(case):
    owned=feature().NativeC2Dispatcher(case['gates'])
    with pytest.raises(Refused,match='fence'):owned.admit_operational()
    assert case['f'].effects==[] and case['calls']==[] and not case['gates'].c2_session.used


def test_c2_interrupt_releases_lease_and_never_starts_worker(case):
    owned=feature().NativeC2Dispatcher(case['gates'])
    case['f'].docker.spawn_error=KeyboardInterrupt(PRIVATE)
    with pytest.raises(KeyboardInterrupt) as caught:owned.run(input_fd=case['fd'])
    assert str(caught.value)=='' and case['calls']==[]
    assert case['g'].guard.lease is None and case['g'].guard.root is None
    assert owned.stage=='refused'


def test_capture_failure_invokes_cleanup_and_consumes_dispatch(case):
    owned=feature().NativeC2Dispatcher(case['gates'])
    fd=input_fd(dict(private=PRIVATE,job={}))
    try:
        with pytest.raises(Refused):owned.run(input_fd=fd)
        with pytest.raises(Refused):owned.run(input_fd=fd)
    finally:os.close(fd)
    assert case['f'].effects==['restart-no','TERM'] and len(case['calls'])==1
    assert case['calls'][0]['status']=='invalid-result' and owned.uncertain is True


def test_input_replacement_during_c2_refuses_before_worker(case):
    owned=feature().NativeC2Dispatcher(case['gates']);done=False
    def replaced(argv,child):
        nonlocal done
        if not done:
            done=True;os.close(case['fd'])
    case['f'].docker.after=replaced
    with pytest.raises(Refused):owned.run(input_fd=case['fd'])
    assert case['calls']==[]
