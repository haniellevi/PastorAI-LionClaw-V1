"""Supervised native jobs over own real workers and synthetic private input."""
from copy import deepcopy
import fcntl
import importlib
import json
import os
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from first_transition_adapter import adapter_sources,digest,prepare
from first_transition_native_events import NativeWindowEvents
from first_transition_capture_contract import V3_CATEGORIES
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA
from initial_transition_ops import Refused
from test_first_transition_native_job import plan,rig  # noqa: F401
from test_first_transition_native_joint import tls  # noqa: F401

ROOT=Path(__file__).resolve().parents[2]
CONTEXT=dict(schema='synthetic-context',source_identity='a'*64)
PRIVATE='SYNTHETIC-PRIVATE-MEMFD-ONLY'


def feature():
    try:return importlib.import_module('first_transition_native_supervision')
    except ModuleNotFoundError:pytest.fail('native supervision feature is not implemented')


def job_result(plan,request):
    events=NativeWindowEvents(digest(request),digest(CONTEXT))
    for phase in ('capture_start','source_frontends_closed','capture_finish','recovery_start','recovery_finish',
                  'cleanup_finish','result'):getattr(events,phase)()
    summary=dict(v2_observed_sha256='1'*64,v2_clone_expected_sha256='2'*64,v3_sha256='3'*64,
        row_counts_sha256='4'*64,settings_inventory_sha256='5'*64,v3_counts={key:0 for key in V3_CATEGORIES})
    clone=dict(migrations_verified=True,clone_identity='b'*64,cluster_global_ddl_possible=True,
        applied=len(plan.pending),final_ledger=len(plan.migrations),concurrent=sum(m.concurrent for m in plan.pending),
        sql_digest=digest([(m.name,m.sha256) for m in plan.pending]),final_schema_digest='c'*64)
    binding=dict(request_digest=digest(request),context_digest=digest(CONTEXT),dump_sha256='d'*64,
        companion_sha256='e'*64,snapshot_sha256='f'*64,sample_summary=summary,container_id='6'*64,
        network_id='7'*64,clone_identity=clone['clone_identity'],daemon_id='fixture-daemon',image_id='sha256:'+'8'*64,
        clone_system_sha256='9'*64,code_pins_sha256=digest(dict(plan.adapter_sources)),
        effective_source_policy_sha256='0'*64,dump_spec_sha256='1'*64,events_sha256=events.digest,
        source_unchanged_proven=False,clone_rehearsal_digest=digest(clone))
    comparison=dict(equal=True,v2=dict(catalog=True,row_counts=True,settings=True),
        v3_categories={key:dict(expected=0,actual=0,missing=0,extra=0,changed=0,equal=True)
                       for key in V3_CATEGORIES},automatic_repair=False,
        v2_login_projection='canonical-isolated-clone',raw_source_settings_equal_claimed=False)
    return dict(schema='igreja12.native-window-job-result/1',binding=binding,binding_digest=digest(binding),
        clone_rehearsal=clone,comparison=comparison,cleanup_verified=True,events=events.public(),
        source_unchanged_proven=False,a8_window_proven=False,operational_ready=False)


@pytest.fixture
def case():
    plan=prepare(ROOT)
    request=dict(schema=BACKUP_REQUEST_SCHEMA,nonce='0'*64,plan_digest=plan.digest,source_identity='a'*64,
        baseline_digest='2'*64,config_digest='3'*64,quiescence_digest='4'*64)
    return plan,request


def input_fd(data):
    fd=os.memfd_create('supervised-private-fixture',os.MFD_ALLOW_SEALING|os.MFD_CLOEXEC)
    os.write(fd,json.dumps(data,allow_nan=False).encode())
    fcntl.fcntl(fd,1033,15)
    return fd


WORKER=('import os,fcntl,json;fd=int(os.environ["IGREJA12_NATIVE_INPUT_FD"]);'
    'assert fcntl.fcntl(fd,1034)&15==15;assert not any(k.startswith("PG") for k in os.environ);'
    'value=json.loads(os.pread(fd,2097153,0));assert len(value["private"])>0;'
    'print(json.dumps(value["job"],allow_nan=False))')


def build(case,cleanup,*,code=WORKER,timeout=3,cleanup_budget=1):
    module=feature();plan,request=case
    argv=(sys.executable,'-I','-c',code)
    pins=module.NativeSupervisionPins(digest(request),digest(CONTEXT),digest(dict(plan.adapter_sources)),
        digest(argv),'0'*64,'1'*64)
    return module.NativeSupervisedWindow(argv,pins,plan=plan,runtime_sources=adapter_sources,cleanup=cleanup,
        timeout_s=timeout,cleanup_budget_s=cleanup_budget)


def observation(module,request,context,result,status,**_ignored):
    ids=() if result is None else (result['binding']['container_id'],result['binding']['network_id'])
    return module.NativeCleanupObservation(request,context,None if result is None else result['binding_digest'],
        status,'fixture-daemon',ids,ids)


def test_real_worker_binds_sealed_private_input_and_never_promotes_cleanup_claim(case):
    # Break caught: trusting child flags or skipping parent cleanup/FD passing.
    module=feature();plan,request=case
    observed=[]
    def cleanup(**args):
        observed.append(args)
        return observation(module,args['request_digest'],args['context_digest'],args['result'],args['status'])
    owned=build(case,cleanup)
    fd=input_fd(dict(private=PRIVATE,job=job_result(plan,request)))
    try:result=owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert len(observed)==1 and observed[0]['status']=='validated'
    assert observed[0]['worker_cleanup_uncertain'] is False
    assert result['schema']=='igreja12.native-supervised-window/1'
    assert result['source_unchanged_proven'] is result['a8_window_proven'] is result['operational_ready'] is False
    assert result['daemon_cleanup_authoritative'] is result['cleanup_hard_deadline_verified'] is False
    assert result['requires_dedicated_outer_process'] is True
    assert [event['phase'] for event in result['parent_events']['events']]==[
        'request-received','supervisor-start','worker-reaped','cleanup-start','cleanup-finish','revalidated']
    assert PRIVATE not in json.dumps(result) and result['job']['binding']['dump_sha256']=='d'*64
    with pytest.raises(Refused):owned.origin_receipt()
    with pytest.raises(Refused):owned.run(request,CONTEXT,input_fd=fd)


def test_deadline_expiry_after_worker_still_invokes_parent_cleanup(case):
    # Break caught: observation failure bypasses the finally cleanup callback.
    module=feature();plan,request=case;calls=[]
    def cleanup(**args):
        calls.append(args)
        return observation(module,args['request_digest'],args['context_digest'],args['result'],args['status'])
    owned=build(case,cleanup)
    original=owned.clock;count=0
    def moved():
        nonlocal count
        count+=1
        return original()+(100 if count>=4 else 0)
    owned.clock=moved
    fd=input_fd(dict(private=PRIVATE,job=job_result(plan,request)))
    try:
        with pytest.raises(Refused):owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert len(calls)==1


@pytest.mark.parametrize('code,status',[
    ('import time;time.sleep(30)','worker-failed'),
    ('import sys;print("private child failure",file=sys.stderr);sys.exit(9)','worker-failed'),
    ('print("not-json")','invalid-result'),
    ('print("{}")','invalid-result')])
def test_timeout_or_invalid_output_requires_cleanup_without_reusing_worker(case,code,status):
    # Break caught: accepting flags/garbage or skipping cleanup after termination.
    module=feature();plan,request=case;calls=[]
    def cleanup(**args):
        calls.append(args)
        return observation(module,args['request_digest'],args['context_digest'],args['result'],args['status'])
    owned=build(case,cleanup,code=code,timeout=.6,cleanup_budget=.2)
    fd=input_fd(dict(private=PRIVATE,job=job_result(plan,request)))
    started=time.monotonic()
    try:
        with pytest.raises(Refused,match='^native-supervised-window-failed$') as error:
            owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert time.monotonic()-started<3 and len(calls)==1 and calls[0]['status']==status
    assert calls[0]['result'] is None and PRIVATE not in str(error.value)
    with pytest.raises(Refused):owned.run(request,CONTEXT,input_fd=fd)


@pytest.mark.parametrize('fault',['schema','unknown','binding-digest','binding-request','binding-runtime','dump',
    'clone-count-bool','clone-sql','clone-binding','comparison-bool','category-count-bool','events-bool',
    'events-order','events-binding','events-digest','source-unchanged','a8','operational','cleanup-bool','joint'])
def test_structured_result_is_validated_before_cleanup_gets_known_resource_ids(case,fault):
    # Break caught: hash-only acceptance without strict nested typed semantics.
    module=feature();plan,request=case;value=job_result(plan,request);calls=[]
    if fault=='schema':value['schema']='igreja12.first-transition-origin-window-backup/1'
    elif fault=='unknown':value['raw_output']='private child payload'
    elif fault=='binding-digest':value['binding_digest']='f'*64
    elif fault=='binding-request':value['binding']['request_digest']='f'*64
    elif fault=='binding-runtime':value['binding']['code_pins_sha256']='f'*64
    elif fault=='dump':value['binding']['dump_sha256']=True
    elif fault=='clone-count-bool':value['clone_rehearsal']['applied']=True
    elif fault=='clone-sql':value['clone_rehearsal']['sql_digest']='f'*64
    elif fault=='clone-binding':value['binding']['clone_identity']='f'*64
    elif fault=='comparison-bool':value['comparison']['equal']=1
    elif fault=='category-count-bool':value['comparison']['v3_categories']['schemas']['expected']=False
    elif fault=='events-bool':value['events']['events'][0]['sequence']=False
    elif fault=='events-order':value['events']['events'][0]['phase']='result'
    elif fault=='events-binding':value['events']['request_digest']='f'*64
    elif fault=='events-digest':value['binding']['events_sha256']='f'*64
    elif fault=='source-unchanged':value['source_unchanged_proven']=True
    elif fault=='a8':value['a8_window_proven']=True
    elif fault=='operational':value['operational_ready']=True
    elif fault=='cleanup-bool':value['cleanup_verified']=1
    else:value['joint']={'fixture_scope_only':True}
    # Rebind hashes so semantic validation is exercised independently of hashes.
    if fault!='events-digest':value['binding']['events_sha256']=digest(value['events'])
    value['binding']['clone_rehearsal_digest']=digest(value['clone_rehearsal'])
    if fault!='binding-digest':value['binding_digest']=digest(value['binding'])
    def cleanup(**args):
        calls.append(args)
        return observation(module,args['request_digest'],args['context_digest'],args['result'],args['status'])
    owned=build(case,cleanup);fd=input_fd(dict(private=PRIVATE,job=value))
    try:
        with pytest.raises(Refused):owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert len(calls)==1 and calls[0]['result'] is None and calls[0]['status']=='invalid-result'


@pytest.mark.parametrize('fault',['bool','json','wrong-request','missing-id','not-absent','exception'])
def test_untrusted_cleanup_flag_cannot_validate_own_resource_absence(case,fault):
    # Break caught: trusting a child JSON cleanup flag or mismatched inspector.
    module=feature();plan,request=case
    def cleanup(**args):
        if fault=='bool':return True
        if fault=='json':return {'cleanup_verified':True}
        if fault=='exception':raise RuntimeError(PRIVATE)
        value=observation(module,args['request_digest'],args['context_digest'],args['result'],args['status'])
        from dataclasses import replace
        if fault=='wrong-request':return replace(value,request_digest='f'*64)
        if fault=='missing-id':return replace(value,inspected_resource_ids=(),absent_resource_ids=())
        return replace(value,absent_resource_ids=())
    owned=build(case,cleanup);fd=input_fd(dict(private=PRIVATE,job=job_result(plan,request)))
    try:
        with pytest.raises(Refused,match='^native-supervised-window-failed$') as error:
            owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert PRIVATE not in str(error.value)


def test_preflight_runtime_mismatch_refuses_before_worker_or_cleanup(case):
    # Break caught: accepting a caller's mapping without checking real files.
    plan,request=case;calls=[]
    owned=build(case,lambda **args:calls.append(args))
    values=list(plan.adapter_sources);values[0]=(values[0][0],'f'*64)
    owned.runtime_sources=lambda:tuple(values)
    fd=input_fd(dict(private=PRIVATE,job=job_result(plan,request)))
    try:
        with pytest.raises(Refused):owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert calls==[] and [e['phase'] for e in owned.diagnostics()['parent_events']]==['request-received']


def test_forged_consistent_runtime_mapping_still_requires_actual_sibling_bytes(case):
    # Break caught: checking mapping/digest consistency without opening source files.
    from dataclasses import replace
    plan,request=case;calls=[]
    owned=build(case,lambda **args:calls.append(args))
    forged=list(plan.adapter_sources);forged[0]=(forged[0][0],'f'*64)
    forged_plan=replace(plan,adapter_sources=tuple(forged))
    forged_request={**request,'plan_digest':forged_plan.digest}
    owned.plan=forged_plan
    owned.pins=replace(owned.pins,request_sha256=digest(forged_request),runtime_sha256=digest(dict(forged)))
    owned.runtime_sources=lambda:tuple(forged)
    fd=input_fd(dict(private=PRIVATE,job=job_result(forged_plan,forged_request)))
    try:
        with pytest.raises(Refused):owned.run(forged_request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert calls==[]


def test_cleanup_late_return_refuses_without_claiming_hard_preemption(case):
    # Break caught: accepting a callback's late return as timely daemon cleanup.
    module=feature();plan,request=case
    owned=None
    def cleanup(**args):
        value=observation(module,args['request_digest'],args['context_digest'],args['result'],args['status'])
        original=owned.clock
        owned.clock=lambda:original()+100
        return value
    owned=build(case,cleanup);fd=input_fd(dict(private=PRIVATE,job=job_result(plan,request)))
    try:
        with pytest.raises(Refused):owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert owned.diagnostics()['cleanup_hard_deadline_verified'] is False
def test_only_actual_successful_supervisor_return_can_be_revalidated(case):
    module=feature();plan,request=case
    def cleanup(**args):
        return observation(module,args['request_digest'],args['context_digest'],args['result'],args['status'])
    owned=build(case,cleanup)
    fd=input_fd(dict(private=PRIVATE,job=job_result(plan,request)))
    try:report=owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    validated=owned.validate_report(report)
    assert validated==report and validated is not report and validated['job'] is not report['job']
    changed=deepcopy(report);changed['job']['binding']['dump_sha256']='0'*64
    with pytest.raises(Refused):owned.validate_report(changed)
    fresh=build(case,cleanup)
    with pytest.raises(Refused):fresh.validate_report(report)
def test_concrete_cleanup_issued_evidence_is_bound_but_injected_transport_is_not_native(case):
    from first_transition_native_cleanup import NativeCleanupRegistry,NativeDockerCleanup
    import first_transition_native_cleanup as cleanup_module
    from test_first_transition_native_cleanup import Docker
    plan,request=case
    registry=NativeCleanupRegistry(digest(request),digest(CONTEXT),'fixture-daemon')
    registry.created_network('7'*64)
    registry.created_container('6'*64,image_id='sha256:'+'8'*64)
    frozen=registry.freeze();docker=Docker(cleanup_module,frozen)
    cleanup=NativeDockerCleanup(frozen,docker_binary='/usr/bin/docker',endpoint='unix:///tmp/synthetic.sock',
        config_dir='/tmp/synthetic-config',runner=docker)
    owned=build(case,cleanup)
    fd=input_fd(dict(private=PRIVATE,job=job_result(plan,request)))
    try:report=owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert not docker.containers and not docker.networks
    assert report['daemon_cleanup_verified'] is False and report['daemon_cleanup_authoritative'] is False
    assert report['daemon_evidence']['observation_sha256']==digest(report['cleanup_observation'])
    assert report['daemon_evidence']['transport']=='injected-boundary'
    assert owned.validate_report(report)==report
    cleanup._runner=lambda *_a,**_k:(0,b'')
    with pytest.raises(Refused):owned.validate_report(report)


@pytest.mark.parametrize('fault',['clock_alias','clock_rollback','wall_interrupt'])
def test_report_revalidation_keeps_issued_clock_and_cancellation_binding(case,fault):
    module=feature();plan,request=case
    def cleanup(**args):
        return observation(module,args['request_digest'],args['context_digest'],args['result'],args['status'])
    owned=build(case,cleanup);state=dict(mono=1000.0,interrupt=False)
    owned.clock=lambda:state['mono']
    def wall():
        if state['interrupt']:raise KeyboardInterrupt(PRIVATE)
        return time.time()
    owned.wall_clock=wall
    fd=input_fd(dict(private=PRIVATE,job=job_result(plan,request)))
    try:report=owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    if fault=='clock_alias':owned.clock=lambda:999.0
    elif fault=='clock_rollback':state['mono']=999.0
    else:state['interrupt']=True
    error_type=KeyboardInterrupt if fault=='wall_interrupt' else Refused
    with pytest.raises(error_type) as error:owned.validate_report(report)
    assert PRIVATE not in str(error.value)
    state['mono']=1000.0;state['interrupt']=False
    with pytest.raises(Refused):owned.validate_report(report)


def joint_job(plan,request):
    value=job_result(plan,request)
    references={table:dict(state='not_projected',rows=None,nonempty_references=None,
        missing_in_catalog=None,missing_in_preserved=None) for table in (
        'public.messages','public.igrejas','public.cell_report_audio_inputs','public.private_deletion_tasks')}
    references['public.messages']=dict(state='projected',rows=5,nonempty_references=3,
        missing_in_catalog=1,missing_in_preserved=1)
    joint=dict(schema='igreja12.native-synthetic-joint/1',
        artifacts=dict(request_digest=digest(request),artifacts={
            'projection':dict(sha256='a'*64,size=500),'manifest':dict(sha256='b'*64,size=700)}),
        aggregates=dict(schema='igreja12.joint-collector-aggregates/1',selected_objects=2,
            hashed_objects=2,hashed_bytes=4,references=references,same_holder_snapshot_observed=True,
            source_body_hashes_verified=True,authority_verified=False,native_transport_keepalive_proven=False,
            all_application_references_covered=False,a8_window_proven=False,operational_receipt=False,production_go=False),
        policy_sha256='6'*64,runtime_sha256=digest(dict(plan.adapter_sources)),maximum_pulse_gap_s=.2,pulse_calls=0,
        fixture_scope_only=True,source_unchanged_proven=False,authoritative_fence_verified=False,
        storage_body_retention_verified=False,storage_recovery_verified=False,a8_window_proven=False,operational_ready=False)
    value['joint']=joint
    value['binding']['joint_capture_digest']=digest(joint)
    value['binding_digest']=digest(value['binding'])
    return value


def build_joint(case,cleanup,**pin_changes):
    from dataclasses import replace
    owned=build(case,cleanup)
    owned.pins=replace(owned.pins,**{'joint_policy_sha256':'6'*64,**pin_changes})
    return owned


def test_strict_joint_result_is_bound_to_independent_policy_and_remains_fixture_only(case):
    # Break caught: valid real-shaped joint extension is rejected or promoted.
    module=feature();plan,request=case;calls=[]
    def cleanup(**args):
        calls.append(args)
        return observation(module,args['request_digest'],args['context_digest'],args['result'],args['status'])
    owned=build_joint(case,cleanup)
    value=joint_job(plan,request);fd=input_fd(dict(private=PRIVATE,job=value))
    try:report=owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert report['job']['joint']==value['joint'] and calls[0]['status']=='validated'
    assert report['source_unchanged_proven'] is report['a8_window_proven'] is report['operational_ready'] is False
    assert report['job']['joint']['storage_recovery_verified'] is False
    assert owned.validate_report(report)==report
    with pytest.raises(Refused):owned.origin_receipt()


def parent_mode(case,*,joint=False):
    from dataclasses import replace
    from first_transition_native_cleanup import NativeCleanupRegistry,NativeDockerCleanup
    import first_transition_native_cleanup as cleanup_module
    from test_first_transition_native_cleanup import Docker
    plan,request=case
    builder=NativeCleanupRegistry(digest(request),digest(CONTEXT),'fixture-daemon')
    builder.created_network('7'*64);builder.created_container('6'*64,image_id='sha256:'+'8'*64)
    registry=builder.freeze();docker=Docker(cleanup_module,registry)
    cleanup=NativeDockerCleanup(registry,docker_binary='/usr/bin/docker',endpoint='unix:///tmp/synthetic.sock',
        config_dir='/tmp/synthetic-config',runner=docker)
    owned=build_joint(case,cleanup) if joint else build(case,cleanup)
    owned.pins=replace(owned.pins,parent_registry_sha256=registry.digest)
    value=joint_job(plan,request) if joint else job_result(plan,request)
    value.update(cleanup_verified=False,parent_cleanup_required=True)
    value['binding']['parent_registry_digest']=registry.digest
    value['binding_digest']=digest(value['binding'])
    return owned,value,docker


@pytest.mark.parametrize('joint',[False,True])
def test_parent_mode_requires_registered_parent_cleanup_without_claiming_child_cleanup(case,joint):
    # Break caught: local cleanup claims substitute for the pinned parent registry.
    owned,value,docker=parent_mode(case,joint=joint);_,request=case
    fd=input_fd(dict(private=PRIVATE,job=value))
    try:report=owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert report['job']['cleanup_verified'] is False and report['job']['parent_cleanup_required'] is True
    assert not docker.containers and not docker.networks
    assert report['daemon_evidence']['registry_digest']==owned.pins.parent_registry_sha256
    assert report['daemon_cleanup_verified'] is report['a8_window_proven'] is report['operational_ready'] is False
    assert owned.validate_report(report)==report


def joint_rebind(value):
    value['binding']['joint_capture_digest']=digest(value['joint'])
    value['binding_digest']=digest(value['binding'])


@pytest.mark.parametrize('fault',['unknown-job','unknown-joint','unknown-aggregate','unknown-artifact','schema',
    'aggregate-schema','policy','runtime','request','joint-digest','missing-joint','missing-joint-digest',
    'projection-limit','manifest-limit','artifact-boolean','artifact-hash','objects-limit','objects-boolean',
    'hashed-count','bytes-limit','bytes-boolean','zero-objects-bytes','pulse-gap','pulse-nan','pulse-boolean',
    'pulse-inconsistent','pulse-calls-limit','reference-state','reference-boolean','reference-total','empty-references',
    'reference-missing','unprojected-count','references-unknown','fixture-boolean','observed-boolean',
    'fence','storage-recovery','storage-retention','aggregate-authority','aggregate-operational'])
def test_joint_extension_rejects_malformed_or_promoted_claims_after_rebinding_hash(case,fault):
    # Break caught: joint hashes mask invalid nested fields or forbidden authority.
    module=feature();plan,request=case;calls=[];value=joint_job(plan,request)
    j=value['joint'];a=j['aggregates'];art=j['artifacts']['artifacts'];refs=a['references']
    if fault=='unknown-job':value['private_material']='PRIVATE'
    elif fault=='unknown-joint':j['manifest']={'private':'forbidden'}
    elif fault=='unknown-aggregate':a['all_verified']=True
    elif fault=='unknown-artifact':art['dump']={'sha256':'a'*64,'size':1}
    elif fault=='schema':j['schema']='invented'
    elif fault=='aggregate-schema':a['schema']='invented'
    elif fault=='policy':j['policy_sha256']='f'*64
    elif fault=='runtime':j['runtime_sha256']='f'*64
    elif fault=='request':j['artifacts']['request_digest']='f'*64
    elif fault=='projection-limit':art['projection']['size']=16777217
    elif fault=='manifest-limit':art['manifest']['size']=2097153
    elif fault=='artifact-boolean':art['projection']['size']=True
    elif fault=='artifact-hash':art['projection']['sha256']=True
    elif fault=='objects-limit':a['selected_objects']=a['hashed_objects']=1001
    elif fault=='objects-boolean':a['selected_objects']=a['hashed_objects']=True
    elif fault=='hashed-count':a['hashed_objects']=1
    elif fault=='bytes-limit':a['hashed_bytes']=1000000001
    elif fault=='bytes-boolean':a['hashed_bytes']=True
    elif fault=='zero-objects-bytes':a['selected_objects']=a['hashed_objects']=0
    elif fault=='empty-references':
        a['selected_objects']=a['hashed_objects']=a['hashed_bytes']=0
    elif fault=='pulse-gap':j['maximum_pulse_gap_s']=2.001
    elif fault=='pulse-nan':j['maximum_pulse_gap_s']=float('nan')
    elif fault=='pulse-boolean':j['pulse_calls']=False
    elif fault=='pulse-inconsistent':j['maximum_pulse_gap_s']=1.5
    elif fault=='pulse-calls-limit':j['pulse_calls']=241
    elif fault=='reference-state':refs['public.messages']['state']='complete'
    elif fault=='reference-boolean':refs['public.messages']['rows']=True
    elif fault=='reference-total':
        refs['public.messages']['rows']=10000
        refs['public.igrejas']=dict(state='projected',rows=1,nonempty_references=0,
            missing_in_catalog=0,missing_in_preserved=0)
    elif fault=='reference-missing':refs['public.messages']['missing_in_preserved']=0
    elif fault=='unprojected-count':refs['public.igrejas']['rows']=0
    elif fault=='references-unknown':refs['unknown.table']=refs['public.igrejas']
    elif fault=='fixture-boolean':j['fixture_scope_only']=1
    elif fault=='observed-boolean':a['source_body_hashes_verified']=1
    elif fault=='fence':j['authoritative_fence_verified']=True
    elif fault=='storage-recovery':j['storage_recovery_verified']=True
    elif fault=='storage-retention':j['storage_body_retention_verified']=True
    elif fault=='aggregate-authority':a['authority_verified']=True
    elif fault=='aggregate-operational':a['operational_receipt']=True
    joint_rebind(value)
    if fault=='joint-digest':value['binding']['joint_capture_digest']='f'*64
    elif fault=='missing-joint':del value['joint']
    elif fault=='missing-joint-digest':del value['binding']['joint_capture_digest']
    value['binding_digest']=digest(value['binding'])
    def cleanup(**args):
        calls.append(args)
        return observation(module,args['request_digest'],args['context_digest'],args['result'],args['status'])
    owned=build_joint(case,cleanup)
    if fault=='pulse-nan':
        # Emit the actual non-finite JSON token; the trusted parser must refuse it.
        code=('import os,json;fd=int(os.environ["IGREJA12_NATIVE_INPUT_FD"]);'
              'print(json.dumps(json.loads(os.pread(fd,2097153,0))["job"]))')
        from dataclasses import replace
        owned.argv=(sys.executable,'-I','-c',code)
        owned.pins=replace(owned.pins,worker_argv_sha256=digest(owned.argv))
        fd=os.memfd_create('nonfinite-synthetic-input',os.MFD_ALLOW_SEALING|os.MFD_CLOEXEC)
        os.write(fd,json.dumps(dict(private=PRIVATE,job=value)).encode());fcntl.fcntl(fd,1033,15)
    else:fd=input_fd(dict(private=PRIVATE,job=value))
    try:
        with pytest.raises(Refused):owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert len(calls)==1 and calls[0]['status']=='invalid-result' and calls[0]['result'] is None


@pytest.mark.parametrize('empty',[False,True])
def test_joint_exact_public_bounds_and_empty_selection_remain_nonoperational(case,empty):
    # Break caught: maximum declared limits or legitimate zero selection refuse.
    module=feature();plan,request=case;value=joint_job(plan,request)
    j=value['joint'];a=j['aggregates']
    j['artifacts']['artifacts']['projection']['size']=16777216
    j['artifacts']['artifacts']['manifest']['size']=2097152
    j['maximum_pulse_gap_s']=2.;j['pulse_calls']=240
    a['selected_objects']=a['hashed_objects']=0 if empty else 1000
    a['hashed_bytes']=0 if empty else 1000000000
    if empty:
        a['references']['public.messages']['missing_in_catalog']=3
        a['references']['public.messages']['missing_in_preserved']=3
    a['references']['public.messages']['rows']=10000
    joint_rebind(value)
    def cleanup(**args):return observation(module,args['request_digest'],args['context_digest'],args['result'],args['status'])
    owned=build_joint(case,cleanup);fd=input_fd(dict(private=PRIVATE,job=value))
    try:report=owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert report['job']['joint']==j and report['a8_window_proven'] is False


@pytest.mark.parametrize('field',['joint_policy_sha256','parent_registry_sha256'])
@pytest.mark.parametrize('bad',[True,'invalid','f'*63])
def test_optional_expectation_pins_are_not_boolean_enable_flags(case,field,bad):
    # Break caught: optional proof expectations accept booleans or invalid hashes.
    from dataclasses import replace
    module=feature();plan,request=case
    owned=build(case,lambda **_a:pytest.fail('cleanup after invalid pin'))
    pins=replace(owned.pins,**{field:bad})
    with pytest.raises(Refused):
        module.NativeSupervisedWindow(owned.argv,pins,plan=plan,runtime_sources=adapter_sources,cleanup=owned.cleanup)


@pytest.mark.parametrize('fault',['missing-parent-flag','false-parent-flag','child-cleanup-true','wrong-registry',
                                 'unknown-container','wrong-image','wrong-network','wrong-daemon','parent-pin-absent'])
def test_parent_mode_cannot_downgrade_or_adopt_child_claimed_resources(case,fault):
    # Break caught: child result controls parent cleanup scope or legacy downgrade.
    from dataclasses import replace
    owned,value,docker=parent_mode(case);_,request=case
    if fault=='missing-parent-flag':del value['parent_cleanup_required']
    elif fault=='false-parent-flag':value['parent_cleanup_required']=1
    elif fault=='child-cleanup-true':value['cleanup_verified']=True
    elif fault=='wrong-registry':value['binding']['parent_registry_digest']='f'*64
    elif fault=='unknown-container':value['binding']['container_id']='f'*64
    elif fault=='wrong-image':value['binding']['image_id']='sha256:'+'f'*64
    elif fault=='wrong-network':value['binding']['network_id']='f'*64
    elif fault=='wrong-daemon':value['binding']['daemon_id']='other-daemon'
    else:owned.pins=replace(owned.pins,parent_registry_sha256=None)
    value['binding_digest']=digest(value['binding'])
    fd=input_fd(dict(private=PRIVATE,job=value))
    try:
        with pytest.raises(Refused):owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert docker.mutations==[('docker','rm','-f','-v','6'*64),('docker','network','rm','7'*64)]


@pytest.mark.parametrize('fault',['wrong-registry-pin','generic-callback','request-registry'])
def test_parent_mode_binding_refuses_before_worker_and_daemon_callbacks(case,fault):
    # Break caught: wrong independently provisioned registry reaches effects.
    from dataclasses import replace
    owned,value,docker=parent_mode(case);_,request=case
    if fault=='wrong-registry-pin':owned.pins=replace(owned.pins,parent_registry_sha256='f'*64)
    elif fault=='generic-callback':owned.cleanup=lambda **_args:pytest.fail('generic callback used for parent mode')
    else:owned.pins=replace(owned.pins,request_sha256='f'*64)
    fd=input_fd(dict(private=PRIVATE,job=value))
    try:
        with pytest.raises(Refused):owned.run(request,CONTEXT,input_fd=fd)
    finally:os.close(fd)
    assert docker.calls==[] and owned.diagnostics()['worker_reaped'] is False


def test_actual_joint_job_emitter_with_loopback_tls_is_accepted_without_scope_promotion(rig,tls,tmp_path,monkeypatch):
    # Break caught: a hand-shaped fixture drifts from the real job extension.
    from first_transition_native_supervision import NativeSupervisionPins,NativeSupervisedWindow
    from test_first_transition_native_joint import Server,setup
    with Server(tls[0]) as server:
        capture,_,_=setup(rig,server,tls,tmp_path,monkeypatch)
        value=rig.worker.execute(rig.request)
        assert len(server.requests)==1
    # The HTTP server/dump threads have ended before the dedicated supervisor.
    def cleanup(**args):
        result=args['result'];binding=result['binding']
        return feature().NativeCleanupObservation(args['request_digest'],args['context_digest'],result['binding_digest'],
            args['status'],binding['daemon_id'],(binding['container_id'],binding['network_id']),
            (binding['container_id'],binding['network_id']))
    argv=(sys.executable,'-I','-c',WORKER)
    pins=NativeSupervisionPins(digest(rig.request),digest(rig.worker.context),digest(dict(rig.worker.plan.adapter_sources)),
        digest(argv),rig.worker.pins.source_policy_sha256,rig.worker.pins.dump_spec_sha256,capture._pins.http_policy_sha256)
    owned=NativeSupervisedWindow(argv,pins,plan=rig.worker.plan,runtime_sources=adapter_sources,cleanup=cleanup,
        timeout_s=3,cleanup_budget_s=1,wall_clock=rig.worker.wall_clock)
    fd=input_fd(dict(private=PRIVATE,job=value))
    try:report=owned.run(rig.request,rig.worker.context,input_fd=fd)
    finally:os.close(fd)
    assert report['job']['joint']==value['joint']
    assert report['job']['joint']['aggregates']['hashed_objects']==1
    assert report['job']['joint']['aggregates']['hashed_bytes']==2
    assert owned.validate_report(report)==report
    assert report['source_unchanged_proven'] is report['a8_window_proven'] is report['operational_ready'] is False
