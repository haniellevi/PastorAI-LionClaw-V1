"""Ordered gates over real C2 lifecycle and own bounded synthetic worker."""
from dataclasses import asdict,replace
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c2_lifecycle_fixture import SessionFixture
from first_transition_adapter import adapter_sources,digest,prepare
from first_transition_database import DatabaseExpectation,LedgerProof
from first_transition_native_supervision import NativeCleanupObservation,NativeSupervisionPins,NativeSupervisedWindow
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA
from initial_transition_ops import Refused
from test_first_transition_native_supervision import WORKER,PRIVATE,input_fd,job_result

ROOT=Path(__file__).resolve().parents[2]


def feature():
    try:return importlib.import_module('first_transition_native_gates')
    except ModuleNotFoundError:pytest.fail('ordered native dispatch gates are not implemented')


@pytest.fixture
def case(monkeypatch):
    with tempfile.TemporaryDirectory(prefix='i12-gates-',dir='/tmp') as directory:
        fx=SessionFixture(Path(directory));g=fx.guards;plan=prepare(ROOT)
        g.expected=DatabaseExpectation('a'*64,plan.baseline,'b'*64)
        g.ledger=LedgerProof(g.db,g.expected,scope=g.scope)
        request=dict(schema=BACKUP_REQUEST_SCHEMA,nonce='0'*64,plan_digest=plan.digest,
            source_identity=g.expected.identity,baseline_digest=g.expected.baseline_digest,
            config_digest='3'*64,quiescence_digest='4'*64)
        context=dict(schema='synthetic-dispatch-context',plan_digest=plan.digest,source_identity=g.expected.identity,
            baseline_digest=g.expected.baseline_digest,config_digest=request['config_digest'])
        g.wall=time.time()
        g.admission=replace(g.admission,request_digest=digest(request),nonce=request['nonce'])
        for doc in g.docs.values():
            doc.update(request_digest=digest(request),nonce=request['nonce'],issued_at=g.wall-1,expires_at=g.wall+10)
            if 'baseline_digest' in doc:doc['baseline_digest']=g.expected.baseline_digest
        g.write_receipts();g.guard=g.make_guard()
        session=fx.session()
        argv=(sys.executable,'-I','-c',WORKER)
        pins=NativeSupervisionPins(digest(request),digest(context),digest(dict(plan.adapter_sources)),digest(argv),'0'*64,'1'*64)
        def cleanup(**args):
            job=args['result']
            ids=() if job is None else (job['binding']['container_id'],job['binding']['network_id'])
            return NativeCleanupObservation(args['request_digest'],args['context_digest'],
                None if job is None else job['binding_digest'],args['status'],'fixture-daemon',ids,ids)
        supervisor=NativeSupervisedWindow(argv,pins,plan=plan,runtime_sources=adapter_sources,cleanup=cleanup,
            timeout_s=3,cleanup_budget_s=1,clock=fx.clock,wall_clock=g.wall_clock)
        # Existing helper's canonical job constructor uses this public context;
        # override only its clock-producing dependency for a coherent fixture.
        import test_first_transition_native_supervision as helper
        monkeypatch.setattr(helper,'CONTEXT',context)
        yield dict(fixture=fx,plan=plan,request=request,context=context,session=session,supervisor=supervisor)


def gates(case):
    module=feature();p=case['plan'];m=case['fixture'].world.manifest
    pins=module.NativeDispatchPins(digest(case['request']),digest(case['context']),p.digest,
        digest(dict(p.adapter_sources)),m.digest,case['request']['source_identity'])
    return module.NativeDispatchGates(case['request'],case['context'],p,m,pins,c2_session=case['session'],
        supervisor=case['supervisor'],runtime_sources=adapter_sources,clock=case['fixture'].clock,
        wall_clock=case['fixture'].guards.wall_clock)


def held(case,gate):
    gate.c2_start();result=case['session'].run();admission=case['session'].guard.admission
    gate.c2_held(result,admission.scope,admission.target_id,admission.nonce)


def captured(case,gate):
    gate.capture_start()
    fd=input_fd(dict(private=PRIVATE,job=fixture_job(case)))
    try:result=case['supervisor'].run(case['request'],case['context'],input_fd=fd)
    finally:os.close(fd)
    gate.capture_validated(result)
    return result


def fixture_job(case):
    value=job_result(case['plan'],case['request'])
    value['binding'].update(container_id='a1'*32,network_id='b2'*32)
    value['binding_digest']=digest(value['binding'])
    return value


def concrete_cleanup(case,*,container_id='a1'*32,network_id='b2'*32):
    from first_transition_native_cleanup import NativeCleanupRegistry,NativeDockerCleanup
    import first_transition_native_cleanup as cleanup_module
    from test_first_transition_native_cleanup import Docker
    builder=NativeCleanupRegistry(digest(case['request']),digest(case['context']),'fixture-daemon')
    builder.created_network(network_id);builder.created_container(container_id,image_id='sha256:'+'8'*64)
    registry=builder.freeze();docker=Docker(cleanup_module,registry)
    cleanup=NativeDockerCleanup(registry,docker_binary='/usr/bin/docker',endpoint='unix:///tmp/synthetic.sock',
        config_dir='/tmp/synthetic-config',runner=docker,clock=case['fixture'].clock,
        wall_clock=case['fixture'].guards.wall_clock)
    case['supervisor'].cleanup=cleanup
    return cleanup,docker


def test_real_stage_sequence_emits_only_bound_nonoperational_hash_receipt(case):
    # Break caught: skipped stage/JSON assertions promote a window or leak payload.
    gate=gates(case);held(case,gate);result=captured(case,gate)
    gate.cleanup_validated(NativeCleanupObservation(**result['cleanup_observation']))
    receipt=gate.finish()
    assert [v['phase'] for v in receipt['events']]==[
        'request-admitted','c2-start','c2-held','capture-start','capture-validated','cleanup-validated','result']
    assert receipt['schema']=='igreja12.native-dispatch-stages/1'
    assert receipt['request_digest']==digest(case['request'])
    assert receipt['context_digest']==digest(case['context'])
    assert receipt['plan_digest']==case['plan'].digest
    assert receipt['supervised_result_digest']==digest(result)
    assert all(receipt[k] is False for k in ('source_unchanged_proven','authoritative_fence_verified',
        'ddl_authorized','a8_window_proven','operational_dispatch_enabled','operational_ready'))
    assert PRIVATE not in json.dumps(receipt) and 'job' not in receipt and 'manifest' not in receipt
    with pytest.raises(Refused):gate.origin_receipt()
    with pytest.raises(Refused):gate.admit_operational()
    with pytest.raises(Refused):gate.finish()


@pytest.mark.parametrize('operation',['held','capture-start','capture-validated','cleanup','finish'])
def test_wrong_stage_order_poison_prevents_later_effects(case,operation):
    # Break caught: out-of-order validation quietly skips containment/capture.
    gate=gates(case)
    action={'held':lambda:gate.c2_held({},'a'*64,'b'*64,'0'*64),
        'capture-start':gate.capture_start,'capture-validated':lambda:gate.capture_validated({}),
        'cleanup':lambda:gate.cleanup_validated(True),'finish':gate.finish}[operation]
    with pytest.raises(Refused):action()
    with pytest.raises(Refused):gate.c2_start()
    assert case['fixture'].effects==[] and case['session'].used is False and case['supervisor'].used is False


@pytest.mark.parametrize('fault',['request','context','pins','clock','timing-clock','timing-reset','session','supervisor',
                                 'cleanup-alias','runtime-reader'])
def test_mutated_binding_is_refused_before_dispatch(case,fault):
    # Break caught: accepting a replaced alias or reset timing component.
    gate=gates(case)
    if fault=='request':case['request']['config_digest']='f'*64
    elif fault=='context':case['context']['config_digest']='f'*64
    elif fault=='pins':object.__setattr__(gate.pins,'source_identity','f'*64)
    elif fault=='clock':gate.clock=lambda:case['fixture'].guards.now
    elif fault=='timing-clock':gate._timing._clock=lambda:case['fixture'].guards.now
    elif fault=='timing-reset':
        from first_transition_native_events import NativeWindowEvents
        gate._timing=NativeWindowEvents(digest(case['request']),digest(case['context']),
            clock=gate.clock,wall_clock=gate.wall_clock)
    elif fault=='session':gate.c2_session=case['fixture'].session()
    elif fault=='supervisor':gate.supervisor=object()
    elif fault=='cleanup-alias':case['supervisor'].cleanup=lambda **_args:True
    else:gate.runtime_sources=lambda:case['plan'].adapter_sources
    with pytest.raises(Refused):gate.c2_start()
    assert case['fixture'].effects==[]


@pytest.mark.parametrize('fault',['wall-back','mono-back','drift','c2-late-start'])
def test_clock_regression_drift_or_expired_stage_refuses(case,fault):
    # Break caught: elapsed or wall-clock drift permits a late stage.
    gate=gates(case);g=case['fixture'].guards
    if fault=='wall-back':g.wall-=.01
    elif fault=='mono-back':g.now-=.01
    elif fault=='drift':g.wall+=2.01
    else:g.now+=60.01;g.wall+=60.01
    with pytest.raises(Refused):gate.c2_start()
    with pytest.raises(Refused):gate.remaining_s()


def test_c2_duration_late_is_refused_after_real_containment(case):
    # Break caught: successful fixture result bypasses the parent C2 60s limit.
    gate=gates(case);gate.c2_start();result=case['session'].run();g=case['fixture'].guards
    g.now+=60.01;g.wall+=60.01;a=case['session'].guard.admission
    with pytest.raises(Refused):gate.c2_held(result,a.scope,a.target_id,a.nonce)


@pytest.mark.parametrize('fault',['boolean','unknown','wrong-scope','wrong-target','wrong-nonce','unrun'])
def test_c2_json_alone_or_wrong_binding_cannot_validate_held_stage(case,fault):
    # Break caught: raw held flags stand in for the actual bound lifecycle.
    gate=gates(case);gate.c2_start();a=case['session'].guard.admission
    if fault=='unrun':
        result=dict(status='broadcast-held',production_ready=False,original_removed=False,replacement_started=False,
                    operational_dispatch_enabled=False,lease_released=True)
    else:result=case['session'].run()
    scope,target,nonce=a.scope,a.target_id,a.nonce
    if fault=='boolean':result['lease_released']=1
    elif fault=='unknown':result['allowed']=True
    elif fault=='wrong-scope':scope='f'*64
    elif fault=='wrong-target':target='f'*64
    elif fault=='wrong-nonce':nonce='f'*64
    with pytest.raises(Refused):gate.c2_held(result,scope,target,nonce)


def test_raw_supervision_json_without_bound_actual_worker_is_refused(case):
    # Break caught: accepting an arbitrary report on an unrun supervisor.
    gate=gates(case);held(case,gate);gate.capture_start()
    with pytest.raises(Refused):gate.capture_validated({'worker_reaped':True})
    assert case['supervisor'].used is False


def test_changed_completed_supervisor_report_is_not_accepted(case):
    # Break caught: arbitrary JSON is accepted after any successful worker run.
    gate=gates(case);held(case,gate);gate.capture_start()
    fd=input_fd(dict(private=PRIVATE,job=fixture_job(case)))
    try:report=case['supervisor'].run(case['request'],case['context'],input_fd=fd)
    finally:os.close(fd)
    report['job']['binding']['dump_sha256']='f'*64
    report['job']['binding_digest']=digest(report['job']['binding'])
    report['job_digest']=digest(report['job'])
    with pytest.raises(Refused):gate.capture_validated(report)


@pytest.mark.parametrize('fault',['wrong-binding','boolean','json','late','report-alias'])
def test_cleanup_requires_exact_issued_report_association_and_freshness(case,fault):
    # Break caught: accepting cleanup claims or changed aliases as evidence.
    gate=gates(case);held(case,gate);report=captured(case,gate)
    observation=NativeCleanupObservation(**report['cleanup_observation'])
    if fault=='wrong-binding':observation=replace(observation,request_digest='f'*64)
    elif fault=='boolean':observation=True
    elif fault=='json':observation=asdict(observation)
    elif fault=='late':
        g=case['fixture'].guards;g.now+=60.01;g.wall+=60.01
    else:report['runtime_sha256']='f'*64
    with pytest.raises(Refused):gate.cleanup_validated(observation)


def test_parent_budget_and_supervisor_reservation_cannot_be_extended(case):
    # Break caught: resetting clocks or launching a worker past the parent budget.
    case['supervisor'].timeout=1199
    gate=gates(case);held(case,gate);g=case['fixture'].guards
    g.now+=2;g.wall+=2
    with pytest.raises(Refused):gate.capture_start()


def test_operational_admission_refuses_without_any_host_or_source_effect(case):
    # Break caught: nominal operation reaches a port before missing-fence refusal.
    gate=gates(case)
    with pytest.raises(Refused,match='authoritative-fence-missing'):gate.admit_operational()
    with pytest.raises(Refused,match='authoritative-fence-missing'):gate.origin_receipt()
    assert case['fixture'].effects==[] and case['session'].used is False and case['supervisor'].used is False


@pytest.mark.parametrize('overlap',['service','support','network'])
def test_cleanup_source_id_overlap_refuses_before_host_or_daemon_effect(case,overlap):
    # Break caught: the cleanup callback could remove source resources first.
    manifest=case['fixture'].world.manifest
    cid='a1'*32;nid='b2'*32
    if overlap=='service':cid=dict(manifest.service_ids)['backend']
    elif overlap=='support':cid=next(iter(dict(manifest.support_ids).values()))
    else:nid=manifest.network_id
    cleanup,docker=concrete_cleanup(case,container_id=cid,network_id=nid)
    with pytest.raises(Refused):gates(case)
    assert docker.calls==[] and case['fixture'].effects==[] and cleanup.observation is None


def test_cleanup_clock_alias_must_match_the_dispatch_clock(case):
    # Break caught: independent cleanup time can bypass the caller's deadline.
    cleanup,docker=concrete_cleanup(case)
    cleanup.clock=lambda:case['fixture'].guards.now
    with pytest.raises(Refused):gates(case)
    assert docker.calls==[]


def test_concrete_injected_daemon_proof_remains_non_authoritative(case):
    # Break caught: reconstructed observations gain authority without issuer checks.
    cleanup,docker=concrete_cleanup(case);gate=gates(case);held(case,gate);report=captured(case,gate)
    observation=NativeCleanupObservation(**report['cleanup_observation'])
    assert observation is not cleanup.observation
    gate.cleanup_validated(observation)
    receipt=gate.finish()
    assert receipt['daemon_evidence_digest']==cleanup.daemon_evidence.digest
    assert receipt['daemon_cleanup_verified'] is False
    assert receipt['authoritative_fence_verified'] is receipt['operational_ready'] is False
    assert not docker.containers and not docker.networks


@pytest.mark.parametrize('field',['request_sha256','context_sha256','plan_sha256','runtime_sha256',
                                 'manifest_sha256','source_identity'])
def test_wrong_independent_pin_refuses_before_any_port_effect(case,field):
    # Break caught: caller config self-attests instead of matching reviewed pins.
    module=feature();valid=gates(case);bad=replace(valid.pins,**{field:'f'*64})
    with pytest.raises(Refused):
        module.NativeDispatchGates(case['request'],case['context'],case['plan'],case['fixture'].world.manifest,bad,
            c2_session=case['session'],supervisor=case['supervisor'],runtime_sources=adapter_sources,
            clock=case['fixture'].clock,wall_clock=case['fixture'].guards.wall_clock)
    assert case['fixture'].effects==[] and case['supervisor'].used is False


def test_remaining_budget_cancellation_is_sanitized_and_poisons_gate(case):
    # Break caught: a clock cancellation leaks text and leaves a reusable gate.
    interrupted=False;g=case['fixture'].guards
    def wall():
        if interrupted:raise KeyboardInterrupt(PRIVATE)
        return g.wall
    g.wall_clock=wall;case['session'].guard.wall_clock=wall;case['supervisor'].wall_clock=wall
    gate=gates(case);interrupted=True
    with pytest.raises(KeyboardInterrupt) as error:gate.remaining_s()
    assert str(error.value)==''
    interrupted=False
    with pytest.raises(Refused):gate.c2_start()
    assert case['fixture'].effects==[]
