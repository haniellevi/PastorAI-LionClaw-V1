"""Local filesystem proof. Executors are synthetic; no SSH or cloud activity."""
import importlib.util
import json
import multiprocessing as mp
import signal
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location('dev_coordination', Path(__file__).parents[1] / 'dev_coordination.py')
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
Coordinator, Error = _mod.DevCoordinator, _mod.DevCoordinationError


def package(sequence=1, *, seed='synthetic-v1'):
    return dict(sha=f'{sequence:040x}', frontend_sha=f'{sequence:040x}', backend_digest='sha256:'+'a'*64,
                frontend_origin='https://synthetic-dev.example.test', api_origin='https://synthetic-api.example.test',
                frontend_digest='sha256:'+'c'*64, schema='b'*64, seed=seed,
                sequence=sequence, environment='dev-sintetico')


def deploy(coordinator, candidate):
    coordinator.transition(candidate, operation='deploy', execute=lambda _p: None)


def test_reservation_reset_expiry_and_receipts(tmp_path):
    now = [100]
    c = Coordinator(tmp_path, clock=lambda: now[0])
    deploy(c, package())
    first = c.reserve(owner='owner', ttl=10)
    with pytest.raises(Error, match='acceptance reserved'):
        deploy(c, package(2))
    with pytest.raises(Error, match='owned by another'):
        c.finish(token=first, owner='other')
    now[0] = 110
    with pytest.raises(Error, match='expired'):
        c.finish(token=first, owner='owner')
    second = c.reserve(owner='owner')
    c.finish(token=second, owner='owner')
    third = c.reserve(owner='owner')
    c.transition(package(seed='synthetic-v2'), operation='reset', execute=lambda _p: None)
    with pytest.raises(Error):
        c.finish(token=third, owner='owner')
    state = json.loads((tmp_path/'state.json').read_text())
    assert state['invalidated'][first] == 'expired' and state['invalidated'][third] == 'reset'
    assert state['receipts'][second]['package'] == _mod.package_id(package())
    deploy(c, package(2))
    with pytest.raises(Error, match='older'):
        deploy(c, package())


def test_failure_after_swap_demands_proven_recovery(tmp_path):
    c = Coordinator(tmp_path)
    deploy(c, package())
    accepted = c.reserve(owner='owner')
    c.finish(token=accepted, owner='owner')
    def failed(_p):
        raise RuntimeError('synthetic-after-swap')
    with pytest.raises(RuntimeError):
        c.transition(package(2), operation='deploy', execute=failed)
    with pytest.raises(Error, match='unavailable'):
        c.reserve(owner='owner')
    with pytest.raises(Error, match='recovery proof'):
        deploy(c, package(3))
    with pytest.raises(Error, match='not proven'):
        c.record_recovery(package(), verify=lambda _p: False)
    c.record_recovery(package(), verify=lambda _p: True)
    assert accepted in json.loads((tmp_path/'state.json').read_text())['receipts']
    deploy(c, package(2))


def _slow_deploy(path, entered, release):
    def execute(_p):
        entered.set()
        assert release.wait(8)
    Coordinator(path).transition(package(), operation='deploy', execute=execute)


def _reserve(path, started, finished, result):
    started.set()
    result.put(Coordinator(path).reserve(owner='second-process'))
    finished.set()


def test_reservation_and_transition_use_same_real_process_mutex(tmp_path):
    context = mp.get_context('fork')
    entered, release, started, finished = [context.Event() for _ in range(4)]
    result = context.Queue()
    first = context.Process(target=_slow_deploy, args=(tmp_path, entered, release))
    second = context.Process(target=_reserve, args=(tmp_path, started, finished, result))
    first.start()
    try:
        assert entered.wait(8)
        second.start()
        assert started.wait(8)
        # The executor deliberately holds the mutex. Reservation cannot finish
        # before release; bounded wait tests exclusion rather than readiness.
        assert not finished.wait(0.15)
        release.set()
        assert finished.wait(8)
        assert result.get(timeout=1)
    finally:
        release.set()
        first.join(8)
        if second.pid is not None:
            second.join(8)
    assert first.exitcode == second.exitcode == 0


@pytest.mark.parametrize('change', [
    {'frontend_sha':'f'*40}, {'frontend_digest':'latest'}, {'api_origin':'https://api.igreja12.com.br'}, {'backend_digest':'latest'}, {'schema':'unknown'},
    {'sequence':True}, {'environment':'production'}, {'frontend_origin':'https://api.igreja12.com.br'},
])
def test_invalid_package_never_runs_executor(tmp_path, change):
    candidate = package() | change
    called = []
    with pytest.raises(Error):
        Coordinator(tmp_path).transition(candidate, operation='deploy', execute=lambda _p: called.append(True))
    assert not called and not (tmp_path/'state.json').exists()


def _interrupted_deploy(path, entered):
    def execute(_p):
        entered.set()
        signal.pause()  # disposable child awaits the test's explicit signal
    Coordinator(path).transition(package(), operation='deploy', execute=execute)


def test_interrupted_executor_cannot_leave_false_acceptance_state(tmp_path):
    context = mp.get_context('fork')
    entered = context.Event()
    worker = context.Process(target=_interrupted_deploy, args=(tmp_path, entered))
    worker.start()
    try:
        assert entered.wait(8)
        worker.kill()  # only the disposable process created by this test
        worker.join(8)
        state = json.loads((tmp_path/'state.json').read_text())
        assert state['recovery_required'] and state['package'] is None
        with pytest.raises(Error, match='unavailable'):
            Coordinator(tmp_path).reserve(owner='after-crash')
        Coordinator(tmp_path).record_recovery(package(), verify=lambda _p: True)
        assert Coordinator(tmp_path).reserve(owner='after-recovery')
    finally:
        if worker.is_alive():
            worker.terminate()
        worker.join(8)
