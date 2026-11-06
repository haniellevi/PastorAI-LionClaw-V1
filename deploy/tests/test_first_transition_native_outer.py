"""Whole wrapper deadlines over forked, entirely synthetic C2/daemon fixtures."""
import importlib
import json
import os
from pathlib import Path
import signal
import sys
import time

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from initial_transition_ops import Refused
from test_first_transition_native_dispatch import case,tmp_path  # noqa: F401


def test_reusable_process_boundary_reaps_each_step_and_restores_subreaper():
    m=module()
    assert hasattr(m,'NativeProcessBoundary'),'shared process boundary is missing'
    parent=os.getpid()
    with m.NativeProcessBoundary(stop_budget_s=.1) as boundary:
        value=boundary.attempt(lambda:dict(pid=os.getpid()),deadline=time.monotonic()+1)
        assert value['pid']!=parent and boundary.last_started and boundary.last_reaped
        assert boundary.attempt(lambda:dict(cleaned=True),deadline=time.monotonic()+1)=={'cleaned':True}
    assert m._subreaper()==0 and m._children()==()


def test_reusable_process_boundary_kills_blocked_step_but_allows_reserved_cleanup():
    m=module()
    assert hasattr(m,'NativeProcessBoundary'),'shared process boundary is missing'
    with m.NativeProcessBoundary(stop_budget_s=.1) as boundary:
        with pytest.raises(Refused):
            boundary.attempt(lambda:time.sleep(30),deadline=time.monotonic()+.6)
        assert boundary.last_reaped
        assert boundary.attempt(lambda:dict(cleaned=True),deadline=time.monotonic()+.5)=={'cleaned':True}
    assert m._children()==() and m._subreaper()==0


def test_reusable_process_boundary_known_fork_failure_allows_cleanup(monkeypatch):
    m=module()
    with m.NativeProcessBoundary(stop_budget_s=.1) as boundary:
        with monkeypatch.context() as patched:
            def failed():raise OSError('synthetic unavailable fork')
            patched.setattr(os,'fork',failed)
            with pytest.raises(Refused):boundary.attempt(lambda:{},deadline=time.monotonic()+1)
        assert boundary.last_started is False and boundary.last_reaped is True
        assert boundary.attempt(lambda:dict(cleaned=True),deadline=time.monotonic()+1)=={'cleaned':True}
    assert m._children()==() and m._subreaper()==0


def test_reusable_process_boundary_refuses_existing_child_without_adoption():
    m=module();pid=os.fork()
    if pid==0:os._exit(0)
    try:
        with pytest.raises(Refused):
            with m.NativeProcessBoundary():pytest.fail('adopted existing process')
        assert m._subreaper()==0
    finally:os.waitpid(pid,0)


@pytest.mark.parametrize('fault',['interrupt-after-set','get-after-set'])
def test_reusable_process_boundary_failed_acquisition_restores_prior_subreaper(monkeypatch,fault):
    m=module();original=m._subreaper;armed=False
    def failing(value=None):
        nonlocal armed
        if value is True:
            original(True);armed=True
            if fault=='interrupt-after-set':raise KeyboardInterrupt('private synthetic cancellation')
            return None
        if value is None and armed and fault=='get-after-set':return 0
        return original(value)
    boundary=m.NativeProcessBoundary()
    try:
        with monkeypatch.context() as patched:
            patched.setattr(m,'_subreaper',failing)
            expected=KeyboardInterrupt if fault=='interrupt-after-set' else Refused
            with pytest.raises(expected) as error:
                with boundary:pytest.fail('acquisition failure entered context')
            if fault=='interrupt-after-set':assert str(error.value)==''
        assert original()==0 and boundary._active is False
        assert m._children()==()
    finally:original(False)


def test_reusable_process_boundary_recovery_cannot_disable_unowned_role():
    m=module();boundary=m.NativeProcessBoundary()
    with boundary:pass
    try:
        m._subreaper(True)
        with pytest.raises(Refused):boundary.recover()
        assert m._subreaper()==1
    finally:m._subreaper(False)


def test_reusable_process_boundary_recovery_requires_original_owner_pid(monkeypatch):
    m=module();boundary=m.NativeProcessBoundary()
    with boundary:
        with monkeypatch.context() as patched:
            patched.setattr(boundary,'_owner_pid',-1)
            with pytest.raises(Refused):boundary.recover()
            assert m._subreaper()==1
    assert m._subreaper()==0


def test_reusable_process_boundary_reaps_new_session_descendant(tmp_path):
    m=module();marker=tmp_path/'helper-descendant.json'
    def blocked():
        import subprocess
        child=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(30)'],start_new_session=True)
        marker.write_text(json.dumps(dict(pid=child.pid)))
        time.sleep(30)
    with m.NativeProcessBoundary(stop_budget_s=.2) as boundary:
        with pytest.raises(Refused):boundary.attempt(blocked,deadline=time.monotonic()+.8)
        assert boundary.last_started and boundary.last_reaped
    assert not (Path('/proc')/str(json.loads(marker.read_text())['pid'])).exists()
    assert m._children()==() and m._subreaper()==0


def module():
    try:return importlib.import_module('first_transition_native_outer')
    except ModuleNotFoundError:pytest.fail('whole dispatcher outer boundary is missing')


def run(case,**kwargs):
    from first_transition_native_dispatch import NativeC2Dispatcher
    return module().NativeOuterDispatch(NativeC2Dispatcher(case['gates']),**kwargs)


@pytest.mark.parametrize('case',[True,'parent'],indirect=True)
def test_whole_dispatch_and_parent_finalization_are_reaped_and_bounded(case):
    owned=run(case,timeout_s=5,cleanup_budget_s=1,stop_budget_s=.2)
    result=owned.run(input_fd=case['fd'])
    assert result['wrapper_deadline_enforced'] is result['process_cleanup_verified'] is True
    assert result['main_reaped'] is result['cleanup_reaped'] is True
    assert result['source_unchanged_proven'] is result['a8_window_proven'] is result['ddl_authorized'] is False
    assert result['daemon_cleanup_authoritative'] is result['daemon_cleanup_verified'] is False
    assert result['parent_cleanup']['observation']['job_binding_digest'] is None
    assert owned.validate_result(result)==result
    assert case['f'].effects==[]  # mutations happened only in the isolated fork
    os.fstat(case['fd'])
    with pytest.raises(Refused):owned.run(input_fd=case['fd'])


@pytest.mark.parametrize('case',[True],indirect=True)
def test_blocked_c2_is_killed_and_parent_registered_cleanup_still_runs(case):
    def blocked(*args):time.sleep(30)
    case['f'].docker.after=blocked
    owned=run(case,timeout_s=1.5,cleanup_budget_s=.5,stop_budget_s=.1);start=time.monotonic()
    with pytest.raises(Refused,match='^native-outer-dispatch-failed$'):owned.run(input_fd=case['fd'])
    assert time.monotonic()-start<2.5
    diag=owned.diagnostics()
    assert diag['main_reaped'] is diag['cleanup_reaped'] is diag['process_cleanup_verified'] is True
    assert diag['parent_cleanup_completed'] is True and diag['staged_complete'] is False
    assert diag['authoritative_fence_proven'] is False


@pytest.mark.parametrize('case',[True],indirect=True)
def test_blocked_cleanup_is_also_under_external_deadline(case):
    cleanup=case['gates'].supervisor.cleanup
    fake=case['docker']
    # Fixed runner identity is preserved; block inside its existing daemon port.
    fake.fault='block'
    original=type(fake).__call__
    def blocked(self,argv,**kwargs):
        if self.fault=='block':time.sleep(30)
        return original(self,argv,**kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(type(fake),'__call__',blocked)
        owned=run(case,timeout_s=1.5,cleanup_budget_s=.5,stop_budget_s=.1);start=time.monotonic()
        with pytest.raises(Refused):owned.run(input_fd=case['fd'])
    assert time.monotonic()-start<2.5 and cleanup.observation is None
    assert owned.diagnostics()['process_cleanup_verified'] is True
    assert owned.diagnostics()['parent_cleanup_completed'] is False


@pytest.mark.parametrize('case',[True],indirect=True)
def test_new_session_descendant_cannot_survive_wrapper_timeout(case,tmp_path):
    marker=tmp_path/'owned-descendant.json'
    def blocked(argv,child):
        import subprocess
        program='import os,time; os.close(1); os.close(2); time.sleep(30)'
        process=subprocess.Popen([sys.executable,'-I','-c',program],start_new_session=True)
        marker.write_text(json.dumps(dict(pid=process.pid)))
        time.sleep(30)
    case['f'].docker.after=blocked
    owned=run(case,timeout_s=1.5,cleanup_budget_s=.5,stop_budget_s=.1)
    with pytest.raises(Refused):owned.run(input_fd=case['fd'])
    pid=json.loads(marker.read_text())['pid']
    assert not (Path('/proc')/str(pid)).exists()
    assert owned.diagnostics()['process_cleanup_verified'] is True


@pytest.mark.parametrize('case',[True],indirect=True)
def test_successful_wrapper_with_escaped_live_descendant_is_refused(case,tmp_path):
    marker=tmp_path/'escaped-live.json';created=False
    def leaked(argv,child):
        nonlocal created
        if created:return
        created=True
        import subprocess
        process=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(30)'],start_new_session=True)
        marker.write_text(json.dumps(dict(pid=process.pid)))
    case['f'].docker.after=leaked
    owned=run(case,timeout_s=5,cleanup_budget_s=1,stop_budget_s=.2)
    with pytest.raises(Refused):owned.run(input_fd=case['fd'])
    assert not (Path('/proc')/str(json.loads(marker.read_text())['pid'])).exists()
    assert owned.diagnostics()['parent_cleanup_completed'] is True


@pytest.mark.parametrize('case',[True],indirect=True)
def test_unsealed_input_is_refused_without_fork_or_host_work(case,monkeypatch):
    owned=run(case,timeout_s=5,cleanup_budget_s=1,stop_budget_s=.2)
    fd=os.memfd_create('unsealed-fictional',os.MFD_CLOEXEC)
    try:
        os.write(fd,b'x')
        monkeypatch.setattr(os,'fork',lambda:pytest.fail('fork after invalid input'))
        with pytest.raises(Refused):owned.run(input_fd=fd)
    finally:os.close(fd)
    assert case['f'].effects==[]


@pytest.mark.parametrize('case',[True],indirect=True)
def test_existing_child_refuses_before_subreaper_or_cleanup(case):
    owned=run(case,timeout_s=5,cleanup_budget_s=1,stop_budget_s=.2)
    pid=os.fork()
    if pid==0:os._exit(0)
    try:
        with pytest.raises(Refused):owned.run(input_fd=case['fd'])
        assert owned.diagnostics()['main_reaped'] is False
    finally:os.waitpid(pid,0)


@pytest.mark.parametrize('case',[True],indirect=True)
def test_signal_reaper_precondition_refuses_before_work(case):
    owned=run(case,timeout_s=5,cleanup_budget_s=1,stop_budget_s=.2);old=signal.getsignal(signal.SIGCHLD)
    try:
        signal.signal(signal.SIGCHLD,lambda *_:None)
        with pytest.raises(Refused):owned.run(input_fd=case['fd'])
    finally:signal.signal(signal.SIGCHLD,old)
    assert case['f'].effects==[]


@pytest.mark.parametrize('case',[True],indirect=True)
@pytest.mark.parametrize('failure',['fork','pipe2'])
def test_failed_spawn_without_child_still_finalizes_registered_resources(case,monkeypatch,failure):
    owned=run(case,timeout_s=5,cleanup_budget_s=1,stop_budget_s=.2);original=getattr(os,failure);calls=[]
    def failed(*args):
        calls.append(True)
        if len(calls)==1:raise OSError('SYNTHETIC-PRIVATE')
        return original(*args)
    monkeypatch.setattr(os,failure,failed)
    with pytest.raises(Refused,match='^native-outer-dispatch-failed$'):owned.run(input_fd=case['fd'])
    assert owned.diagnostics()['parent_cleanup_completed'] is True
    assert owned.diagnostics()['main_process_created'] is False


@pytest.mark.parametrize('case',[True],indirect=True)
def test_parent_interrupt_is_sanitized_after_process_reap_and_cleanup(case,monkeypatch):
    owned=run(case,timeout_s=5,cleanup_budget_s=1,stop_budget_s=.2)
    m=module();original=m.select.select;parent=os.getpid();calls=[]
    def interrupt(*args):
        if os.getpid()==parent and not calls:
            calls.append(True);raise KeyboardInterrupt('SYNTHETIC-PRIVATE')
        return original(*args)
    monkeypatch.setattr(m.select,'select',interrupt)
    with pytest.raises(KeyboardInterrupt) as caught:owned.run(input_fd=case['fd'])
    assert str(caught.value)=='' and owned.diagnostics()['parent_cleanup_completed'] is True
    assert owned.diagnostics()['process_cleanup_verified'] is True and m._subreaper()==0


@pytest.mark.parametrize('case',[True],indirect=True)
def test_valid_json_but_invalid_wrapper_report_still_runs_parent_cleanup(case,monkeypatch):
    owned=run(case,timeout_s=5,cleanup_budget_s=1,stop_budget_s=.2)
    monkeypatch.setattr(owned,'_dispatch_child',lambda _:dict(dispatch={},supervised={}))
    with pytest.raises(Refused):owned.run(input_fd=case['fd'])
    assert owned.diagnostics()['main_reaped'] is owned.diagnostics()['parent_cleanup_completed'] is True
    assert owned.diagnostics()['staged_complete'] is False


@pytest.mark.parametrize('case',[True],indirect=True)
def test_runtime_gate_refusal_never_prevents_original_registry_cleanup(case,monkeypatch):
    owned=run(case,timeout_s=5,cleanup_budget_s=1,stop_budget_s=.2)
    def failed():raise Refused('synthetic-runtime-drift')
    monkeypatch.setattr(case['gates'],'_check',failed)
    with pytest.raises(Refused):owned.run(input_fd=case['fd'])
    assert owned.diagnostics()['parent_cleanup_completed'] is True
    assert owned.diagnostics()['staged_complete'] is False


@pytest.mark.parametrize('case',[True],indirect=True)
def test_forked_attempt_consumes_parent_ports_and_prevents_direct_replay(case):
    owned=run(case,timeout_s=5,cleanup_budget_s=1,stop_budget_s=.2)
    result=owned.run(input_fd=case['fd'])
    assert owned.dispatcher.used is case['sup'].used is case['gates'].c2_session.used is True
    assert owned.cleanup._used is True
    assert owned.validate_result(result)==result
    with pytest.raises(Refused):module().NativeOuterDispatch(owned.dispatcher)
    with pytest.raises(Refused):owned.dispatcher.run(input_fd=case['fd'])
