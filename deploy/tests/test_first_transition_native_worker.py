"""External supervisor tests launch only tiny local synthetic Python workers."""
import fcntl
import os
from pathlib import Path
import signal
import sys
import time
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_window_backup as backup
from initial_transition_ops import Refused


def command(code):
    return (sys.executable, '-I', '-c', code)


def test_real_worker_success_is_bounded_and_cannot_repeat():
    supervisor = backup.NativeWorkerSupervisor()
    assert supervisor.run(command('print("synthetic-result")'), timeout=2) == b'synthetic-result\n'
    assert not supervisor.unreaped
    with pytest.raises(Refused, match='worker-used'):
        supervisor.run(command('print("never")'), timeout=2)


def test_external_timeout_stops_a_worker_blocked_without_cooperative_checks(monkeypatch):
    processes=[];popen=backup.subprocess.Popen
    def spawn(*args,**kwargs):
        process=popen(*args,**kwargs);processes.append(process);return process
    monkeypatch.setattr(backup.subprocess,'Popen',spawn)
    supervisor = backup.NativeWorkerSupervisor(cleanup_wait=1)
    start = time.monotonic()
    with pytest.raises(Refused, match='worker-failed'):
        supervisor.run(command('import time; time.sleep(30)'), timeout=.2)
    assert time.monotonic() - start < 3 and not supervisor.unreaped
    assert len(processes)==1
    with pytest.raises(ProcessLookupError):
        os.kill(processes[0].pid, 0)


@pytest.mark.parametrize('code', ['print("x"*1000)', 'import sys; print("PRIVATE-SYNTHETIC"); sys.exit(7)'])
def test_oversize_or_nonzero_worker_does_not_return_private_output(code):
    supervisor = backup.NativeWorkerSupervisor()
    with pytest.raises(Refused, match='^window-origin-worker-failed$') as error:
        supervisor.run(command(code), timeout=2, max_output=20)
    assert 'PRIVATE' not in str(error.value) and not supervisor.unreaped


def test_closed_stdout_does_not_escape_wait_deadline():
    supervisor = backup.NativeWorkerSupervisor(cleanup_wait=1)
    start = time.monotonic()
    with pytest.raises(Refused):
        supervisor.run(command('import os,time; os.close(1); time.sleep(30)'), timeout=.2)
    assert time.monotonic() - start < 3 and not supervisor.unreaped


def test_minimal_environment_and_stderr_do_not_leak_parent_state(monkeypatch):
    monkeypatch.setenv('PGPASSWORD', 'SYNTHETIC-PRIVATE')
    monkeypatch.setenv('SYNTHETIC_PARENT_ONLY', 'SYNTHETIC-PRIVATE')
    code = ('import os,sys; assert not any(k.startswith("PG") for k in os.environ); '
            'assert "SYNTHETIC_PARENT_ONLY" not in os.environ; '
            'print("PRIVATE-SYNTHETIC",file=sys.stderr); print("ok")')
    assert backup.NativeWorkerSupervisor().run(command(code), timeout=2) == b'ok\n'


def test_sealed_private_input_fd_is_the_only_extra_descriptor():
    fd = os.memfd_create('synthetic-worker-input', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        os.write(fd, b'SYNTHETIC-PRIVATE-INPUT')
        fcntl.fcntl(fd, backup.MEMFD_ADD_SEALS, backup.MEMFD_SEALS)
        code = ('import os; n=int(os.environ["IGREJA12_NATIVE_INPUT_FD"]); '
                'assert os.pread(n,100,0)==b"SYNTHETIC-PRIVATE-INPUT"; print("input-checked")')
        assert backup.NativeWorkerSupervisor().run(command(code), timeout=2, input_fd=fd) == b'input-checked\n'
        assert os.pread(fd,100,0) == b'SYNTHETIC-PRIVATE-INPUT'
    finally:
        os.close(fd)


@pytest.mark.parametrize('bad', [('relative',),('/bin/true','postgresql://synthetic:private@invalid/db'),
                                ('/bin/true','password=synthetic'),('/bin/true','bad\narg')])
def test_invalid_command_never_spawns(monkeypatch, bad):
    def forbidden(*_args, **_kwargs):
        pytest.fail('spawn after invalid argv')
    monkeypatch.setattr(backup.subprocess, 'Popen', forbidden)
    with pytest.raises(Refused):
        backup.NativeWorkerSupervisor().run(bad, timeout=1)


def test_unsealed_input_never_spawns(monkeypatch):
    fd = os.memfd_create('synthetic-unsealed', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        os.write(fd, b'not-sealed')
        def forbidden(*_args, **_kwargs):
            pytest.fail('spawn after unsealed input')
        monkeypatch.setattr(backup.subprocess, 'Popen', forbidden)
        with pytest.raises(Refused):
            backup.NativeWorkerSupervisor().run(command('print("never")'), timeout=1, input_fd=fd)
    finally:
        os.close(fd)


def test_cleanup_reaps_child_before_returning_and_never_uses_poll(monkeypatch):
    waitid, killpg, wait = os.waitid, os.killpg, backup.subprocess.Popen.wait
    events = []
    def observed_waitid(*args):
        events.append('waitid')
        return waitid(*args)
    def observed_killpg(*args):
        assert events[-1] == 'waitid'
        events.append('killpg')
        return killpg(*args)
    def observed_wait(process, *args, **kwargs):
        assert 'killpg' in events
        events.append('reap')
        return wait(process, *args, **kwargs)
    monkeypatch.setattr(backup.os, 'waitid', observed_waitid)
    monkeypatch.setattr(backup.os, 'killpg', observed_killpg)
    monkeypatch.setattr(backup.subprocess.Popen, 'wait', observed_wait)
    assert backup.NativeWorkerSupervisor().run(command('print("done")'), timeout=2) == b'done\n'
    assert events == ['waitid','killpg','reap']


def test_nondefault_sigchld_reaper_is_refused_before_spawn(monkeypatch):
    original = signal.getsignal(signal.SIGCHLD)
    try:
        signal.signal(signal.SIGCHLD, lambda *_: None)
        def forbidden(*_args, **_kwargs):
            pytest.fail('spawn under external reaper')
        monkeypatch.setattr(backup.subprocess, 'Popen', forbidden)
        with pytest.raises(Refused):
            backup.NativeWorkerSupervisor().run(command('print("never")'), timeout=1)
    finally:
        signal.signal(signal.SIGCHLD, original)


def test_multithread_parent_is_refused_before_spawn(monkeypatch):
    release=threading.Event()
    thread=threading.Thread(target=lambda:release.wait(2))
    thread.start()
    try:
        calls=[]
        monkeypatch.setattr(backup.subprocess,'Popen',lambda *a,**kw:calls.append(True))
        with pytest.raises(Refused):
            backup.NativeWorkerSupervisor().run(command('print("never")'),timeout=1)
        assert calls==[]
    finally:
        release.set();thread.join(timeout=2)


@pytest.mark.parametrize('failure',['pidfd','echild','pgid','kill','wait','interrupt','active-uncertain'])
def test_external_worker_failure_ownership_and_cleanup_paths(monkeypatch,failure):
    original_popen,real_wait=backup.subprocess.Popen,backup.subprocess.Popen.wait
    original_getpgid,original_select=backup.os.getpgid,backup.select.select
    processes,signals=[],[]
    def spawn(*args,**kwargs):
        process=original_popen(*args,**kwargs);processes.append(process);return process
    monkeypatch.setattr(backup.subprocess,'Popen',spawn)
    supervisor=backup.NativeWorkerSupervisor(cleanup_wait=.5)
    if failure=='pidfd':
        def fail_pidfd(*_):raise OSError('SYNTHETIC-PRIVATE')
        monkeypatch.setattr(backup.os,'pidfd_open',fail_pidfd)
    elif failure=='echild':
        def not_child(*_):raise ChildProcessError('SYNTHETIC-PRIVATE')
        monkeypatch.setattr(backup.os,'waitid',not_child)
    elif failure=='pgid':
        monkeypatch.setattr(backup.os,'getpgid',lambda pid:original_getpgid(pid)+1)
    elif failure=='kill':
        def denied(*_):raise PermissionError('SYNTHETIC-PRIVATE')
        monkeypatch.setattr(backup.os,'killpg',denied)
    elif failure=='wait':
        def uncertain(*_args,**_kwargs):raise backup.subprocess.TimeoutExpired('synthetic',.1)
        monkeypatch.setattr(original_popen,'wait',uncertain)
    elif failure=='interrupt':
        calls=[]
        def interrupted(*args):
            if not calls:
                calls.append(True);raise KeyboardInterrupt('SYNTHETIC-PRIVATE')
            return original_select(*args)
        monkeypatch.setattr(backup.select,'select',interrupted)
    else:
        monkeypatch.setattr(supervisor,'_active_group',lambda pid:[pid])
    if failure in ('echild','pgid'):
        monkeypatch.setattr(backup.os,'killpg',lambda *args:signals.append(args))
    try:
        with pytest.raises(KeyboardInterrupt if failure=='interrupt' else Refused) as error:
            supervisor.run(command('print("private-result")'),timeout=2)
        assert 'SYNTHETIC' not in str(error.value) and len(processes)==1
        if failure in ('echild','pgid'):
            assert signals==[]
        assert supervisor.unreaped is (failure not in ('pidfd','interrupt'))
        with pytest.raises(Refused,match='worker-used'):
            supervisor.run(command('print("never")'),timeout=1)
    finally:
        # Test-injected ownership failures must not leave even a synthetic
        # zombie. Reap only the exact Popen child created by this test.
        for process in processes:
            real_wait(process,timeout=2)


def test_successful_leader_with_live_owned_grandchild_is_not_accepted(tmp_path):
    marker=tmp_path/'synthetic-grandchild-pid'
    child='import os,time; os.close(1); os.close(2); time.sleep(30)'
    code=('import subprocess,sys; p=subprocess.Popen([sys.executable,"-I","-c",'+repr(child)+']); '
          'open('+repr(str(marker))+',"w").write(str(p.pid)); print("leader-done")')
    supervisor=backup.NativeWorkerSupervisor(cleanup_wait=1)
    with pytest.raises(Refused):
        supervisor.run(command(code),timeout=3)
    assert supervisor.leaked_descendants and not supervisor.unreaped
    path=Path('/proc')/marker.read_text()/'stat'
    if path.exists():
        assert path.read_bytes().rsplit(b')',1)[1].split()[0] in (b'Z',b'X')


def test_disappearing_task_cannot_hide_an_active_sibling(tmp_path,monkeypatch):
    root=tmp_path/'synthetic-proc';leader=root/'123';tasks=leader/'task'
    tasks.mkdir(parents=True)
    (leader/'stat').write_bytes(b'123 (synthetic) Z 1 123 0')
    (tasks/'124').mkdir()  # this enumerated task disappeared before stat read
    (tasks/'125').mkdir()
    (tasks/'125'/'stat').write_bytes(b'125 (synthetic) D 1 123 0')
    scandir=os.scandir
    monkeypatch.setattr(backup.os,'scandir',lambda path:scandir(root if path=='/proc' else path))
    assert backup.NativeWorkerSupervisor._active_group(123)==[123]


def test_missing_task_directory_of_existing_zombie_leader_is_uncertain(tmp_path,monkeypatch):
    root=tmp_path/'synthetic-proc';leader=root/'123';leader.mkdir(parents=True)
    (leader/'stat').write_bytes(b'123 (synthetic) Z 1 123 0')
    scandir=os.scandir
    monkeypatch.setattr(backup.os,'scandir',lambda path:scandir(root if path=='/proc' else path))
    with pytest.raises(Refused,match='cleanup-unknown'):
        backup.NativeWorkerSupervisor._active_group(123)


def test_all_disappeared_tasks_are_not_proof_of_stopped_threads(tmp_path,monkeypatch):
    root=tmp_path/'synthetic-proc';leader=root/'123';tasks=leader/'task'
    tasks.mkdir(parents=True)
    (leader/'stat').write_bytes(b'123 (synthetic) Z 1 123 0')
    (tasks/'124').mkdir()
    scandir=os.scandir
    monkeypatch.setattr(backup.os,'scandir',lambda path:scandir(root if path=='/proc' else path))
    with pytest.raises(Refused,match='cleanup-unknown'):
        backup.NativeWorkerSupervisor._active_group(123)


def test_supervised_worker_executes_the_composed_job_using_only_isolated_fixtures(tmp_path):
    import json
    root=Path(__file__).resolve().parents[2]
    child=tmp_path/'owned-fixture';child.mkdir(mode=0o700)
    program=(
        'import sys,json\n'
        'from pathlib import Path\n'
        'sys.path[:0]=['+repr(str(root/'deploy'))+','+repr(str(root/'deploy'/'tests'))+']\n'
        'import pytest,psycopg2\n'
        'from first_transition_adapter import prepare\n'
        'from test_first_transition_native_job import rig\n'
        'from test_first_transition_orchestrator import no_real_processes_or_network\n'
        'plan=prepare(Path('+repr(str(root))+'))\n'
        'patch=pytest.MonkeyPatch()\n'
        'def forbidden(*args,**kwargs): raise AssertionError("unmocked native IO")\n'
        'try:\n'
        ' no_real_processes_or_network.__wrapped__(patch)\n'
        ' patch.setattr(psycopg2,"connect",forbidden)\n'
        ' fixture=rig.__wrapped__(plan,Path('+repr(str(child))+'),patch)\n'
        ' result=fixture.worker.execute(fixture.request)\n'
        ' print(json.dumps(result,sort_keys=True))\n'
        'finally: patch.undo()\n')
    supervisor=backup.NativeWorkerSupervisor()
    result=json.loads(supervisor.run((sys.executable,'-I','-c','exec('+repr(program)+')'),timeout=20))
    assert result['cleanup_verified'] is True and result['a8_window_proven'] is False
    assert result['clone_rehearsal']['applied']==51 and result['clone_rehearsal']['final_ledger']==129
    assert not supervisor.unreaped and not supervisor.leaked_descendants
