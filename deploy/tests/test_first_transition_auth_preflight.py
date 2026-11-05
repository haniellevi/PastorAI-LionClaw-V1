"""Synthetic public proof graphs only. No native/authenticated source operation."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import first_transition_auth_preflight as c
import first_transition_window as window
from first_transition_adapter import digest
from first_transition_database import DatabaseExpectation
from test_first_transition_window_entry import Entry,pinned  # noqa: F401
from test_first_transition_orchestrator import no_real_processes_or_network  # noqa: F401

BASE=1793786400.0


def fixture(entry):
    expected=DatabaseExpectation(entry.raw['database']['identity'],entry.world.plan.baseline,
                                  entry.raw['database']['catalog']).validated()
    endpoint='3'*64
    request=dict(schema=c.REQUEST_SCHEMA,nonce='a'*64,controller_plan_digest=entry.world.plan.digest,
        source_identity_sha256=expected.identity,baseline_v1_digest=expected.baseline_digest,
        catalog_sha256=expected.catalog,ledger_names_sha256=c.LEDGER_SHA,
        endpoint_identity_sha256=endpoint,
        source_descriptor_sha256=digest(dict(protocol='minimal-provider-fd-json/1',endpoint=endpoint)),
        ca_sha256='4'*64,code_bundle_sha256='5'*64,expected_ledger_names=list(expected.ledger),
        project=c.PROJECT,database='postgres',role='postgres',limits=dict(c.LIMITS),startup_profile='supabase-17.6.1.127',expected_server_version_num=170006)
    report={k:request[k] for k in ('controller_plan_digest','source_identity_sha256','baseline_v1_digest',
        'catalog_sha256','ledger_names_sha256','endpoint_identity_sha256','source_descriptor_sha256','ca_sha256')}
    report.update(schema='igreja12.auth-source-report/2',outcome='passed',request_digest=c.validate_request(request),
        safety_evidence_sha256='6'*64,safety_observed_at=BASE-1,started_at=BASE,finished_at=BASE+1,
        server_version_num=170006,startup_profile='supabase-17.6.1.127',managed_profile_conformant=True,
        managed_server_binary_attested=False,ssl_protocol='TLSv1.3',login_calls=1,reason=None,phase='completed')
    report.update({k:True for k in ('role_matches','session_role_matches','read_only','repeatable_read',
        'tls_verify_full','rollback_observed','transaction_idle_before_close','frontend_closed','database_authenticated',
        'credential_supplied_to_native_driver','source_authenticated_via_provider','password_authentication_observed')})
    report.update({k:False for k in ('server_backend_absence_proven','capture_snapshot_exported','backup_created',
        'credential_returned','credential_hashed','a8_receipt_issued','production_go','operational_ready')})
    return request,report


def prepare_entry(pinned,tmp_path,monkeypatch):
    e=Entry(pinned,tmp_path);request,report=fixture(e)
    paths=[tmp_path/'source-request.json',tmp_path/'source-report.json']
    for path,value in zip(paths,(request,report)):path.write_text(json.dumps(value))
    monkeypatch.setattr(window.time,'time',lambda:BASE+2)
    flags=['--source-request',str(paths[0]),'--source-report',str(paths[1])]
    return e,request,report,paths,flags


def test_cli_checks_metadata_only_and_binds_exact_controller(pinned,tmp_path,monkeypatch):
    e,request,report,_,flags=prepare_entry(pinned,tmp_path,monkeypatch);lines=[]
    assert window.main(e.args('check-source-preflight')+flags,out=lines.append,io=e.io)==0,lines
    assessed=json.loads(lines[-1]);assert assessed['request_digest']==digest(request)
    assert assessed['report_digest']==digest(report)
    assert assessed['controller_plan_digest']==e.world.plan.digest
    for key in ('provider_opened_by_contract','execution_authorized','capture_proven','a8_window_proven',
                'receipt_emitted','production_go'):assert assessed[key]is False
    assert e.calls==[] and e.connections==[]


def test_prepare_binds_source_proof_and_clock_alone_does_not_change_digest(pinned,tmp_path,monkeypatch):
    e,_,report,paths,flags=prepare_entry(pinned,tmp_path,monkeypatch)
    def prepared(extra):
        lines=[];assert window.main(e.args('prepare')+extra,out=lines.append,io=e.io)==0,lines
        return json.loads(lines[-1])
    legacy=prepared([]);bound=prepared(flags)
    assert legacy['window_digest']!=bound['window_digest']
    monkeypatch.setattr(window.time,'time',lambda:BASE+3)
    assert prepared(flags)['window_digest']==bound['window_digest']
    report['safety_evidence_sha256']='7'*64;paths[1].write_text(json.dumps(report))
    assert prepared(flags)['window_digest']!=bound['window_digest']
    assert e.calls==[] and e.connections==[]


@pytest.mark.parametrize('mode',['run','check','check-bindings','rehearse-backup','check-origin'])
def test_operational_modes_never_ignore_auth_profile_or_read_provider(pinned,tmp_path,monkeypatch,mode):
    e,_,_,paths,flags=prepare_entry(pinned,tmp_path,monkeypatch)
    e.secret_path.unlink()
    for path in paths:path.unlink()
    lines=[];assert window.main(e.args(mode)+flags,out=lines.append,io=e.io)==2
    expected='window-source-auth-preflight-only' if mode=='run' else 'window-source-auth-mode'
    assert json.loads(lines[-1])=={'refused':expected}
    assert e.calls==[] and e.connections==[]
    assert not(Path(e.raw['state_dir'])/'journal').exists()


@pytest.mark.parametrize('flags',[[],['--source-request','/missing'],['--source-report','/missing']])
def test_partial_or_absent_selection_never_implicitly_opens_database(flags):
    lines=[];assert window.main(['check-source-preflight','--config','/missing']+flags,out=lines.append)==2
    assert json.loads(lines[-1])=={'refused':'window-source-auth-arguments'}


@pytest.mark.parametrize('change',['identity','controller','baseline','closure','write','tls','loginbool','authority','stale','extra'])
def test_invalid_source_binding_fails_closed(pinned,tmp_path,monkeypatch,change):
    e,request,report,paths,flags=prepare_entry(pinned,tmp_path,monkeypatch)
    if change=='identity':request['source_identity_sha256']='0'*64
    elif change=='controller':request['controller_plan_digest']='0'*64
    elif change=='baseline':request['baseline_v1_digest']='0'*64
    elif change=='closure':report['frontend_closed']=False
    elif change=='write':report['read_only']=False
    elif change=='tls':report['tls_verify_full']=False
    elif change=='loginbool':report['login_calls']=True
    elif change=='authority':report['a8_receipt_issued']=True
    elif change=='stale':monkeypatch.setattr(window.time,'time',lambda:BASE+62)
    else:report['password']='SYNTHETIC-DO-NOT-PRINT'
    for path,value in zip(paths,(request,report)):path.write_text(json.dumps(value))
    lines=[];assert window.main(e.args('check-source-preflight')+flags,out=lines.append,io=e.io)==2
    assert json.loads(lines[-1])=={'refused':'window-source-auth-binding'}
    assert e.calls==[] and e.connections==[]


def test_capture_and_authenticated_profiles_cannot_be_mixed(pinned,tmp_path,monkeypatch):
    e,_,_,_,flags=prepare_entry(pinned,tmp_path,monkeypatch)
    flags+=['--origin-contract','2','--origin-plan','/missing','--origin-observation','/missing']
    lines=[];assert window.main(e.args('prepare')+flags,out=lines.append,io=e.io)==2
    assert json.loads(lines[-1])=={'refused':'window-source-auth-arguments'}


@pytest.mark.parametrize('change',['request_schema','report_schema','profile','version'])
def test_legacy_or_other_managed_profile_refuses(pinned,tmp_path,monkeypatch,change):
    e,request,report,paths,flags=prepare_entry(pinned,tmp_path,monkeypatch)
    if change=='request_schema':request['schema']='igreja12.auth-source-request/1'
    elif change=='report_schema':report['schema']='igreja12.auth-source-report/1'
    elif change=='profile':request['startup_profile']='other-profile'
    else:request['expected_server_version_num']=170011
    for path,value in zip(paths,(request,report)):path.write_text(json.dumps(value))
    lines=[];assert window.main(e.args('check-source-preflight')+flags,out=lines.append,io=e.io)==2
    assert json.loads(lines[-1])=={'refused':'window-source-auth-binding'}
    assert e.calls==[] and e.connections==[]
