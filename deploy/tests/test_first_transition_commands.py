"""Offline doubles only: never start Docker fixtures during this test suite."""
import json
from pathlib import Path
import subprocess
import sys
import signal
import socket
import traceback
import types

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from first_transition_host_transport import host_command
from initial_transition_ops import Refused
from rehearse_first_transition_commands import CommandProbe, OWNER, main, plan, Interrupts, Interrupted, docker_request

IMAGE = 'sha256:' + 'a'*64
RUN = 'b'*32
DAEMON = 'd'*64


@pytest.fixture(autouse=True)
def no_real_effects(monkeypatch):
    def blocked(*_a, **_k):
        pytest.fail('real process/network forbidden')
    monkeypatch.setattr(subprocess, 'Popen', blocked)
    monkeypatch.setattr(socket, 'socket', blocked)
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH', 'CONTAINER_HOST', 'CONTAINER_CONNECTION'):
        monkeypatch.delenv(key, raising=False)



class DockerDouble:
    def __init__(self):
        self.containers = {}
        self.calls = []
        self.lost_create = False
        self.timeout_wait = False
        self.volumes = 'null'

    def __call__(self, args, *, timeout):
        self.calls.append(args)
        assert 0 < timeout <= 30
        if args[:2] == ('docker', 'info'):
            return {'{{.ID}}': DAEMON, '{{.OSType}}': 'linux', '{{json .SecurityOptions}}': '[]'}[args[-1]]
        if args[:3] == ('docker', 'image', 'inspect'):
            return IMAGE if args[4] == '{{.Id}}' else self.volumes
        if args[:2] == ('docker', 'create'):
            identifier = str(len(self.containers)+1)*64
            name = args[args.index('--name')+1]
            self.containers[identifier] = dict(name=name, owner=RUN, running=False, policy='always')
            cidfile = Path(args[args.index('--cidfile')+1])
            if self.lost_create:
                cidfile.write_text('')  # Daemon may create before the CLI records its ID.
                raise Refused('simulated-lost-create-response')
            cidfile.write_text(identifier)
            return identifier
        if args[:2] == ('docker', 'ps'):
            if args[-1].startswith('label='):
                return '\n'.join(i for i, c in self.containers.items() if c['owner'] == RUN)
            name = args[-1].removeprefix('name=^/').removesuffix('$')
            return '\n'.join(i for i, c in self.containers.items() if c['name'] == name)
        identifier = args[-1]
        state = self.containers[identifier]
        if args[:2] == ('docker', 'inspect'):
            field = args[3]
            if field == '{{.Name}}':
                return '/' + state['name']
            if OWNER in field:
                return state['owner']
            if 'RestartPolicy' in field:
                return state['policy']
            if 'Running' in field:
                return str(state['running']).lower()
            if 'RestartCount' in field:
                return '0'
        if args[:2] == ('docker', 'start'):
            state['running'] = True
        elif args[:2] == ('docker', 'logs'):
            return 'fixture-ready'
        elif args[:2] == ('docker', 'update'):
            state['policy'] = 'no'
        elif args[:2] == ('docker', 'kill'):
            assert state['policy'] == 'no'
            state['running'] = False
        elif args[:2] == ('docker', 'wait'):
            if self.timeout_wait:
                raise Refused('simulated-wait-timeout')
            return '0'
        elif args[:3] == ('docker', 'rm', '-f'):
            del self.containers[identifier]
        else:
            raise AssertionError('unexpected fake command')
        return identifier


def test_plan_default_has_no_process_or_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(subprocess, 'Popen', lambda *_a, **_k: pytest.fail('plan cannot start processes'))
    report = tmp_path / 'report.json'
    assert main(['--image', IMAGE, '--run-id', RUN, '--report', str(report)]) == 0
    spec = json.loads(capsys.readouterr().out)
    assert len(spec['creates']) == 4 and spec['host_verified'] is False
    for command in spec['creates'].values():
        assert '--network=none' in command and '--pull=never' in command and '--read-only' in command
        assert '--no-healthcheck' in command
        assert '--log-opt=compress=false' in command
        assert not any(flag in command for flag in ('-v', '--volume', '-p', '--publish', '--privileged'))
    assert not report.exists()


def test_success_uses_shared_encoder_then_cleans_only_owned_resources(tmp_path):
    docker = DockerDouble()
    probe = CommandProbe(plan(IMAGE, RUN), docker, tmp_path)
    result = probe.execute()
    assert result['status'] == 'pass' and result['fixtures'] == 4
    for identifier in probe.ids:
        assert docker.calls.index(host_command('restart-no', identifier)) < docker.calls.index(host_command('term', identifier))
        assert host_command('wait', identifier) in docker.calls
    assert probe.cleanup() == dict(status='clean', failures=0, details=[])
    assert not docker.containers


def test_lost_create_without_cid_requires_nominal_recovery(tmp_path):
    docker = DockerDouble()
    docker.lost_create = True
    probe = CommandProbe(plan(IMAGE, RUN), docker, tmp_path)
    with pytest.raises(Refused, match='simulated-lost-create-response'):
        probe.execute()
    assert len(docker.containers) == 1
    assert probe.cleanup()['status'] == 'incomplete'
    assert len(docker.containers) == 1
    assert not any(c[:2] == ('docker', 'rm') for c in docker.calls)


def test_wait_timeout_cleans_without_restart(tmp_path):
    docker = DockerDouble()
    docker.timeout_wait = True
    probe = CommandProbe(plan(IMAGE, RUN), docker, tmp_path)
    with pytest.raises(Refused, match='simulated-wait-timeout'):
        probe.execute()
    assert probe.cleanup()['status'] == 'clean'
    assert not docker.containers
    assert not any(command[:2] == ('docker', 'restart') for command in docker.calls)


def test_changed_ownership_is_preserved_and_cleanup_is_incomplete(tmp_path):
    docker = DockerDouble()
    probe = CommandProbe(plan(IMAGE, RUN), docker, tmp_path)
    probe.execute()
    kept = probe.ids[0]
    docker.containers[kept]['owner'] = 'another-owner'
    result = probe.cleanup()
    assert result['status'] == 'incomplete' and result['failures'] == 1
    assert result['details'][0]['code'] == 'probe-ownership-changed'
    assert set(docker.containers) == {kept}
    assert ('docker', 'rm', '-f', kept) not in docker.calls


def test_image_volumes_refused_before_create(tmp_path):
    docker = DockerDouble()
    docker.volumes = '{"/data":{}}'
    probe = CommandProbe(plan(IMAGE, RUN), docker, tmp_path)
    with pytest.raises(Refused, match='probe-image-volumes'):
        probe.execute()
    assert not docker.containers


@pytest.mark.parametrize('image', ['postgres:latest', 'sha256:short', 'registry.example/image:tag'])
def test_plan_rejects_mutable_or_remote_image_reference(image):
    with pytest.raises(Refused, match='image-must-be-local-id'):
        plan(image, RUN)


@pytest.mark.parametrize('mode', ['--execute', '--cleanup-only'])
@pytest.mark.parametrize('scope', [[], ['--run-id', '']])
def test_effect_modes_require_explicit_run_id_before_any_effect(mode, scope, tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *_a, **_k: pytest.fail('missing scope cannot start processes'))
    report = tmp_path / 'report.json'
    with pytest.raises(Refused, match='probe-run-id'):
        main(['--image', IMAGE, mode, '--report', str(report), *scope])
    assert not report.exists()


def test_main_execution_pins_socket_and_environment_and_preserves_report(tmp_path, monkeypatch):
    docker = DockerDouble()

    install_process_double(monkeypatch, docker)
    report = tmp_path / 'report.json'
    args = effect_args(tmp_path)
    assert main(args) == 0
    result = json.loads(report.read_text())
    assert result['status'] == 'pass' and result['cleanup']['status'] == 'clean'
    assert len(result['scope']['creates']) == 4 and not docker.containers
    calls = len(docker.calls)
    with pytest.raises(FileExistsError):
        main(args)
    assert len(docker.calls) == calls


class ProcessDouble:
    def __init__(self, args, docker, **kwargs):
        assert args[:3] == ['docker', '-H', 'unix:///var/run/docker.sock']
        assert args[3] == '--config' and Path(args[4]).is_dir()
        assert kwargs['env'] == {'PATH': '/usr/bin:/bin'}
        assert kwargs['stderr'] == subprocess.DEVNULL
        assert kwargs['start_new_session'] is True
        self.command = tuple(['docker', *args[5:]])
        self.docker = docker
        self.returncode = None

    def communicate(self, timeout):
        if self.returncode is not None:
            return '', None
        output = self.docker(self.command, timeout=timeout)
        self.returncode = 0
        return output, None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


def install_process_double(monkeypatch, docker):
    monkeypatch.setattr(subprocess, 'Popen', lambda args, **kw: ProcessDouble(args, docker, **kw))


def effect_args(tmp_path, mode='--execute'):
    return ['--image', IMAGE, '--run-id', RUN, mode, '--report', str(tmp_path / 'report.json'),
            '--state-dir', str(tmp_path / 'state'), '--daemon-id', DAEMON]


@pytest.mark.parametrize('key,value', [('DOCKER_HOST', 'tcp://remote:2375'),
    ('DOCKER_HOST', 'ssh://remote'), ('DOCKER_HOST', 'unix:///run/user/1000/docker.sock'),
    ('DOCKER_CONTEXT', 'other'), ('CONTAINER_HOST', 'podman'), ('DOCKER_TLS_VERIFY', '1')])
def test_host_overrides_refused_before_files_or_process(tmp_path, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(Refused, match='probe-(host|context)-refused'):
        main(effect_args(tmp_path))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('field,value', [('{{.ID}}', 'other'), ('{{.OSType}}', 'windows'),
    ('{{json .SecurityOptions}}', '["name=rootless"]')])
def test_daemon_identity_platform_mismatch_has_no_mutation(tmp_path, monkeypatch, field, value):
    docker = DockerDouble()
    def request(args, **kw):
        if args[:2] == ('docker', 'info') and args[-1] == field:
            return value
        return docker(args, **kw)
    install_process_double(monkeypatch, request)
    assert main(effect_args(tmp_path)) == 1
    assert not docker.containers
    assert all(c[:2] == ('docker', 'info') for c in docker.calls)


@pytest.mark.parametrize('sig', [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
@pytest.mark.parametrize('phase', ['create', 'wait', 'rm'])
def test_injected_signal_reports_and_cleans_without_real_signals(tmp_path, monkeypatch, sig, phase):
    docker = DockerDouble()
    original = docker.__call__
    fired = False
    def request(args, **kwargs):
        nonlocal fired
        result = original(args, **kwargs)
        if args[1] == phase and not fired:
            fired = True
            signal.getsignal(sig)(sig, None)  # Direct injection; no os.kill.
        return result
    before = signal.getsignal(sig)
    install_process_double(monkeypatch, request)
    assert main(effect_args(tmp_path)) == 128 + sig
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['status'] == 'fail' and report['signal'] == sig
    assert signal.getsignal(sig) == before
    # Create interrupted after daemon side-effect has unknown completion; keep
    # an uncertainty record even if the known ID was successfully removed.
    assert report['cleanup']['status'] == ('incomplete' if phase == 'create' else 'clean')
    assert not docker.containers


def test_second_signal_aborts_cleanup_and_preserves_report(tmp_path, monkeypatch):
    docker = DockerDouble()
    fired = set()
    def request(args, **kwargs):
        result = docker(args, **kwargs)
        if args[1] in ('wait', 'rm') and args[1] not in fired:
            fired.add(args[1])
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return result
    install_process_double(monkeypatch, request)
    assert main(effect_args(tmp_path)) == 143
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['cleanup']['status'] == 'incomplete'
    assert docker.containers


def test_replaced_id_or_unknown_label_never_deleted(tmp_path):
    docker = DockerDouble()
    probe = CommandProbe(plan(IMAGE, RUN), docker, tmp_path)
    probe.execute()
    first = probe.ids[0]
    docker.containers['e'*64] = docker.containers.pop(first)
    result = probe.cleanup()
    assert result['status'] == 'incomplete'
    assert set(docker.containers) == {'e'*64}
    assert ('docker', 'rm', '-f', 'e'*64) not in docker.calls


def test_total_cleanup_budget_is_bounded(tmp_path):
    docker = DockerDouble()
    clock = [0]
    def request(args, **kw):
        result = docker(args, **kw)
        if args[1] == 'ps':
            clock[0] += 61
        return result
    probe = CommandProbe(plan(IMAGE, RUN), request, tmp_path, clock=lambda: clock[0])
    probe.execute()
    before = len(docker.calls)
    result = probe.cleanup()
    assert result['status'] == 'incomplete', (clock, result, docker.calls[before:])
    assert len(docker.calls) - before == 1
    assert not any(c[:2] == ('docker', 'rm') for c in docker.calls)


def test_cleanup_only_uses_original_state_and_refuses_forged_scope(tmp_path, monkeypatch):
    docker = DockerDouble()
    docker.timeout_wait = True
    install_process_double(monkeypatch, docker)
    assert main(effect_args(tmp_path)) == 1
    args = effect_args(tmp_path, '--cleanup-only')
    args[args.index('--report')+1] = str(tmp_path / 'recovery.json')
    assert main(args) == 0
    scope = tmp_path / 'state' / 'scope.json'
    changed = json.loads(scope.read_text())
    changed['daemon'] = 'other'
    scope.write_text(json.dumps(changed))
    args[args.index('--report')+1] = str(tmp_path / 'refused.json')
    with pytest.raises(Refused, match='probe-state-scope'):
        main(args)


def test_private_driver_error_not_in_report(tmp_path, monkeypatch):
    docker = DockerDouble()
    def request(args, **kw):
        if args[1] == 'wait':
            raise RuntimeError('SYNTHETIC-SECRET-SENTINEL')
        return docker(args, **kw)
    install_process_double(monkeypatch, request)
    assert main(effect_args(tmp_path)) == 1
    report = (tmp_path / 'report.json').read_text()
    assert 'SYNTHETIC-SECRET-SENTINEL' not in report
    assert json.loads(report)['cleanup']['status'] == 'clean'


def test_request_timeout_reaps_only_own_child(monkeypatch):
    calls = []
    class Child:
        returncode = None
        def communicate(self, timeout):
            calls.append(('wait', timeout))
            if self.returncode is None:
                raise subprocess.TimeoutExpired('private', timeout)
            return '', None
        def poll(self): return self.returncode
        def terminate(self): calls.append('terminate')
        def kill(self): calls.append('kill'); self.returncode = -9
    monkeypatch.setattr(subprocess, 'Popen', lambda *_a, **_kw: Child())
    with pytest.raises(Refused, match='probe-command-failed'):
        docker_request('/unused', Interrupts())(('docker', 'info'), timeout=2)
    assert calls == [('wait', 2), 'terminate', ('wait', 1), 'kill', ('wait', 1)]



def test_state_lock_prevents_concurrent_recovery(tmp_path):
    from rehearse_first_transition_commands import state_lock
    with state_lock(tmp_path):
        with pytest.raises(Refused, match='probe-state-busy'):
            with state_lock(tmp_path):
                pytest.fail('concurrent recovery entered')
    with state_lock(tmp_path):
        pass


def test_missing_cid_preserves_resource_and_reports_incomplete(tmp_path):
    docker = DockerDouble()
    probe = CommandProbe(plan(IMAGE, RUN), docker, tmp_path)
    probe.execute()
    (tmp_path / '0.cid').unlink()
    assert probe.cleanup()['status'] == 'incomplete'
    assert set(docker.containers) == {probe.ids[0]}


def test_primary_failure_survives_interrupt_during_cleanup(tmp_path, monkeypatch):
    docker = DockerDouble()
    fired = False
    def request(args, **kwargs):
        nonlocal fired
        if args[1] == 'wait':
            raise RuntimeError('SYNTHETIC-PRIVATE-PRIMARY')
        result = docker(args, **kwargs)
        if args[1] == 'rm' and not fired:
            fired = True
            signal.getsignal(signal.SIGHUP)(signal.SIGHUP, None)
        return result
    install_process_double(monkeypatch, request)
    assert main(effect_args(tmp_path)) == 1
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['reason'] == 'probe-failed'
    assert report['signal'] == signal.SIGHUP
    assert report['cleanup']['status'] == 'clean'


def test_broken_stdout_does_not_prevent_cleanup_or_file_report(tmp_path, monkeypatch):
    docker = DockerDouble()
    install_process_double(monkeypatch, docker)
    class BrokenStream:
        def write(self, _text): raise BrokenPipeError('synthetic stream')
        def flush(self): raise BrokenPipeError('synthetic stream')
    monkeypatch.setattr(sys, 'stdout', BrokenStream())
    monkeypatch.setattr(sys, 'stderr', BrokenStream())
    assert main(effect_args(tmp_path)) == 0
    assert json.loads((tmp_path / 'report.json').read_text())['cleanup']['status'] == 'clean'
    assert not docker.containers


def test_default_plan_ignores_runtime_env_without_inspection(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('DOCKER_HOST', 'ssh://not-used')
    assert main(['--image', IMAGE]) == 0
    assert json.loads(capsys.readouterr().out)['host_verified'] is False
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('failure', [RuntimeError, ValueError, OSError])
def test_initial_snapshot_failure_is_sanitized_before_any_ddl(monkeypatch, capsys, failure):
    import first_transition_local_backup as backup
    driver = types.ModuleType('psycopg2')
    driver.sql = types.SimpleNamespace()
    driver.connect = lambda *_a, **_kw: pytest.fail('no real database')
    monkeypatch.setitem(sys.modules, 'psycopg2', driver)
    secret = 'SYNTHETIC-SECRET-NOT-A-REAL-DSN'
    class Connection:
        def cursor(self):
            pytest.fail('no SQL after snapshot refusal')
    db = types.SimpleNamespace(
        _url='postgresql://postgres:synthetic-only@127.0.0.1:5432/first_transition_test',
        conn=Connection(), observe=lambda: {'ledger': ('baseline',)})
    def fail(_connection):
        raise failure(secret)
    monkeypatch.setattr(backup, 'snapshot', fail)
    with pytest.raises(Refused, match='^local-backup-initial-snapshot-failed$') as caught:
        backup.rehearse_backup(db, types.SimpleNamespace(baseline=('baseline',)))
    assert caught.value.__suppress_context__
    assert secret not in repr(caught.value)
    assert secret not in ''.join(traceback.format_exception(caught.value))
    assert secret not in str(capsys.readouterr())


@pytest.mark.parametrize('cid', ['missing', 'empty'])
def test_uncertain_create_never_adopted_by_cleanup_only(tmp_path, monkeypatch, cid):
    docker = DockerDouble()
    docker.lost_create = True
    install_process_double(monkeypatch, docker)
    assert main(effect_args(tmp_path)) == 1
    if cid == 'missing':
        (tmp_path / 'state' / '0.cid').unlink()
    args = effect_args(tmp_path, '--cleanup-only')
    args[args.index('--report')+1] = str(tmp_path / 'recover.json')
    assert main(args) == 1
    assert len(docker.containers) == 1
    assert json.loads((tmp_path / 'recover.json').read_text())['cleanup']['status'] == 'incomplete'
    assert not any(c[:2] == ('docker', 'rm') for c in docker.calls)


def test_empty_observation_cannot_confirm_unknown_create(tmp_path):
    docker = DockerDouble()
    def request(args, **kw):
        if args[1] == 'create':
            # No visible container yet; daemon may complete later.
            raise Refused('probe-command-failed')
        return docker(args, **kw)
    probe = CommandProbe(plan(IMAGE, RUN), request, tmp_path)
    with pytest.raises(Refused, match='probe-command-failed'):
        probe.execute()
    assert not docker.containers
    assert probe.cleanup()['status'] == 'incomplete'
    assert list(tmp_path.glob('*.pending'))


def test_report_collision_leaves_bytes_and_no_new_state(tmp_path):
    report = tmp_path / 'report.json'
    report.write_text('existing synthetic report')
    with pytest.raises(FileExistsError):
        main(effect_args(tmp_path))
    assert report.read_text() == 'existing synthetic report'
    assert not (tmp_path / 'state').exists()


def test_signal_during_spawn_is_deferred_until_child_recorded(monkeypatch):
    interrupts = Interrupts()
    calls = []
    class Child:
        returncode = None
        def poll(self): return self.returncode
        def terminate(self): calls.append('terminate'); self.returncode = -15
        def communicate(self, timeout): calls.append(('reaped', timeout)); return '', None
    def spawn(*_a, **_kw):
        interrupts.receive(signal.SIGTERM)
        return Child()
    monkeypatch.setattr(subprocess, 'Popen', spawn)
    with pytest.raises(Interrupted):
        docker_request('/unused', interrupts)(('docker', 'info'), timeout=2)
    assert calls == ['terminate', ('reaped', 1)]


def test_interrupted_atomic_intent_is_not_published(tmp_path, monkeypatch):
    import rehearse_first_transition_commands as module
    def fail(*_a, **_kw): raise Interrupted(signal.SIGTERM)
    monkeypatch.setattr(module.json, 'dump', fail)
    with pytest.raises(Interrupted):
        module.exclusive_json(tmp_path / 'intent', {'name': 'synthetic'})
    assert not list(tmp_path.iterdir())



def test_second_signal_before_cleanup_cannot_escape_report(tmp_path, monkeypatch):
    docker = DockerDouble()
    fired = False
    def request(args, **kwargs):
        nonlocal fired
        result = docker(args, **kwargs)
        if args[1] == 'wait' and not fired:
            fired = True
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return result
    cleanup = CommandProbe.cleanup
    def between(probe):
        signal.getsignal(signal.SIGHUP)(signal.SIGHUP, None)
        return cleanup(probe)
    monkeypatch.setattr(CommandProbe, 'cleanup', between)
    install_process_double(monkeypatch, request)
    assert main(effect_args(tmp_path)) == 143
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['cleanup']['status'] == 'incomplete'
    assert report['status'] == 'fail'


def test_parent_traversal_state_refused_before_files(tmp_path):
    args = effect_args(tmp_path)
    args[args.index('--state-dir')+1] = str(tmp_path / 'elsewhere' / '..' / 'state')
    with pytest.raises(Refused, match='probe-state-parent-traversal'):
        main(args)
    assert not list(tmp_path.iterdir())


def test_state_inside_another_checkout_refused(tmp_path):
    (tmp_path / '.git').write_text('synthetic worktree marker')
    with pytest.raises(Refused, match='probe-state-in-checkout'):
        main(effect_args(tmp_path))
    assert not (tmp_path / 'state').exists()


def test_read_state_rejects_symlink(tmp_path):
    from rehearse_first_transition_commands import read_state
    target = tmp_path / 'target'
    target.write_text('synthetic')
    link = tmp_path / 'link'
    link.symlink_to(target)
    with pytest.raises(OSError):
        read_state(link)


def test_recovery_rejects_nonprivate_state_before_docker(tmp_path, monkeypatch):
    docker = DockerDouble()
    install_process_double(monkeypatch, docker)
    assert main(effect_args(tmp_path)) == 0
    (tmp_path / 'state').chmod(0o755)
    args = effect_args(tmp_path, '--cleanup-only')
    args[args.index('--report')+1] = str(tmp_path / 'recover.json')
    count = len(docker.calls)
    with pytest.raises(Refused, match='probe-state-owner'):
        main(args)
    assert len(docker.calls) == count


def test_reaping_failure_is_sanitized_and_bounded(monkeypatch):
    calls = []
    class Child:
        def communicate(self, timeout):
            calls.append(timeout)
            raise subprocess.TimeoutExpired('SYNTHETIC-PRIVATE', timeout)
        def poll(self): return None
        def terminate(self): pass
        def kill(self): pass
    monkeypatch.setattr(subprocess, 'Popen', lambda *_a, **_kw: Child())
    with pytest.raises(Refused, match='^probe-reap-failed$') as exc:
        docker_request('/unused', Interrupts())(('docker', 'info'), timeout=2)
    assert calls == [2, 1, 1]
    assert 'SYNTHETIC-PRIVATE' not in ''.join(traceback.format_exception(exc.value))



def test_signal_between_intent_and_request_prevents_mutation(tmp_path, monkeypatch):
    import rehearse_first_transition_commands as module
    docker = DockerDouble()
    interrupts = Interrupts()
    save = module.exclusive_json
    def interrupted_intent(path, data):
        save(path, data)
        if path.suffix == '.pending':
            interrupts.receive(signal.SIGTERM)
    monkeypatch.setattr(module, 'exclusive_json', interrupted_intent)
    probe = CommandProbe(plan(IMAGE, RUN), docker, tmp_path, interrupts=interrupts)
    with pytest.raises(Interrupted):
        probe.execute()
    assert not any(c[1] == 'create' for c in docker.calls)
    assert probe.cleanup()['status'] == 'incomplete'


def test_signal_outside_request_is_deferred_and_has_no_exception_context():
    interrupts = Interrupts()
    try:
        raise RuntimeError('SYNTHETIC-PRIVATE')
    except RuntimeError:
        interrupts.receive(signal.SIGHUP)  # Must not chain/replace the primary error.
    assert interrupts.phase == 'stopping'
    assert interrupts.signum == signal.SIGHUP


@pytest.mark.parametrize('phase', ['execute', 'cleanup'])
def test_signal_during_timeout_unwinding_and_poll_preserves_error_and_reaps(monkeypatch, phase):
    interrupts = Interrupts()
    interrupts.phase = phase
    interrupts.count = 1 if phase == 'cleanup' else 0
    calls = []
    class Child:
        returncode = None
        def communicate(self, timeout):
            if self.returncode is not None:
                calls.append('reaped')
                return '', None
            try:
                raise subprocess.TimeoutExpired('SYNTHETIC-PRIVATE', timeout)
            finally:
                interrupts.receive(signal.SIGTERM)
                interrupts.receive(signal.SIGHUP)
        def poll(self):
            interrupts.receive(signal.SIGTERM)
            return self.returncode
        def terminate(self):
            calls.append('terminate')
            self.returncode = -15
    monkeypatch.setattr(subprocess, 'Popen', lambda *_a, **_kw: Child())
    with pytest.raises(Refused, match='^probe-command-failed$'):
        docker_request('/unused', interrupts)(('docker', 'wait'), timeout=2)
    assert calls == ['terminate', 'reaped']
    assert interrupts.signum == signal.SIGTERM


def test_signal_after_nonzero_return_preserves_primary_failure(monkeypatch):
    interrupts = Interrupts()
    class Child:
        @property
        def returncode(self):
            interrupts.receive(signal.SIGHUP)
            return 1
        def communicate(self, timeout): return '', None
        def poll(self): return 1
    monkeypatch.setattr(subprocess, 'Popen', lambda *_a, **_kw: Child())
    with pytest.raises(Refused, match='^probe-docker-failed$'):
        docker_request('/unused', interrupts)(('docker', 'info'), timeout=2)
    assert interrupts.signum == signal.SIGHUP


def test_handler_raises_at_most_once_per_wait():
    interrupts = Interrupts()
    interrupts.phase = 'cleanup'
    interrupts.count = 1
    interrupts.abortable = True
    with pytest.raises(Interrupted):
        try:
            interrupts.receive(signal.SIGTERM)
        finally:
            interrupts.receive(signal.SIGHUP)
    assert interrupts.abortable is False
    assert interrupts.count == 3


@pytest.mark.parametrize('kind', ['state', 'report'])
@pytest.mark.parametrize('location', ['leaf', 'ancestor'])
def test_artifact_symlink_refused_before_process_or_state(tmp_path, kind, location):
    target = tmp_path / 'real'
    target.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(target, target_is_directory=True)
    args = effect_args(tmp_path)
    args[args.index('--' + ('state-dir' if kind == 'state' else 'report'))+1] = str(link if location == 'leaf' else link / 'new')
    # Existing report is rejected even before its symlink validation.
    expected = FileExistsError if kind == 'report' and location == 'leaf' else Refused
    with pytest.raises(expected):
        main(args)
    assert not (tmp_path / 'state').exists()
    assert not list(target.iterdir())


@pytest.mark.parametrize('case', ['parent', 'checkout'])
def test_report_path_refused_before_state(tmp_path, case):
    args = effect_args(tmp_path)
    if case == 'parent':
        path = tmp_path / 'other' / '..' / 'report.json'
        code = 'probe-report-parent-traversal'
    else:
        checkout = tmp_path / 'other'
        checkout.mkdir()
        (checkout / '.git').write_text('synthetic')
        path = checkout / 'report.json'
        code = 'probe-report-in-checkout'
    args[args.index('--report')+1] = str(path)
    with pytest.raises(Refused, match=code):
        main(args)
    assert not (tmp_path / 'state').exists()


def test_report_private_and_never_overwrites_symlink(tmp_path, monkeypatch):
    import stat
    from rehearse_first_transition_commands import private_report
    install_process_double(monkeypatch, DockerDouble())
    assert main(effect_args(tmp_path)) == 0
    assert stat.S_IMODE((tmp_path / 'report.json').stat().st_mode) == 0o600
    link = tmp_path / 'late-link'
    link.symlink_to(tmp_path / 'report.json')
    before = (tmp_path / 'report.json').read_bytes()
    with pytest.raises(FileExistsError):
        with private_report(link):
            pytest.fail('symlink opened')
    assert (tmp_path / 'report.json').read_bytes() == before


def test_lock_symlink_refused_without_touching_target(tmp_path):
    from rehearse_first_transition_commands import state_lock
    target = tmp_path / 'target'
    target.write_text('synthetic')
    (tmp_path / 'run.lock').symlink_to(target)
    with pytest.raises(OSError):
        with state_lock(tmp_path):
            pytest.fail('symlink lock opened')
    assert target.read_text() == 'synthetic'


def test_lock_other_owner_refused_with_simulated_metadata(tmp_path, monkeypatch):
    import rehearse_first_transition_commands as module
    original = module.os.fstat
    def foreign(fd):
        metadata = original(fd)
        return types.SimpleNamespace(st_mode=metadata.st_mode, st_uid=module.os.getuid()+1)
    monkeypatch.setattr(module.os, 'fstat', foreign)
    with pytest.raises(Refused, match='probe-lock-owner'):
        with module.state_lock(tmp_path):
            pytest.fail('foreign lock used')


def test_cid_symlink_preserves_resource(tmp_path):
    docker = DockerDouble()
    probe = CommandProbe(plan(IMAGE, RUN), docker, tmp_path)
    probe.execute()
    cid = tmp_path / '0.cid'
    cid.rename(tmp_path / 'original-cid')
    cid.symlink_to(tmp_path / 'original-cid')
    result = probe.cleanup()
    assert result['status'] == 'incomplete'
    assert set(docker.containers) == {probe.ids[0]}
    assert any(d.get('index') == 0 and d['code'] == 'probe-resource-failed' for d in result['details'])


@pytest.mark.parametrize('missing', [True, False])
def test_recovery_identifies_missing_or_empty_cid_and_pending_create(tmp_path, missing):
    docker = DockerDouble()
    docker.lost_create = True
    probe = CommandProbe(plan(IMAGE, RUN), docker, tmp_path)
    with pytest.raises(Refused):
        probe.execute()
    if missing:
        (tmp_path / '0.cid').unlink()
    result = probe.cleanup()
    codes = {d['code'] for d in result['details']}
    assert ('probe-cid-missing' if missing else 'probe-cid-empty') in codes
    assert 'pending-create' in codes
    pending = json.loads(next(tmp_path.glob('*.pending')).read_text())
    assert pending == dict(operation='create', index=0, name=next(iter(probe.spec['creates'])))
    assert result['failures'] == len(result['details'])
    assert docker.containers


def test_pending_mutation_correlates_id_and_sanitizes_untrusted_records(tmp_path):
    docker = DockerDouble()
    probe = CommandProbe(plan(IMAGE, RUN), docker, tmp_path)
    probe.execute()
    target = probe.ids[0]
    def lost(args, **kw):
        result = docker(args, **kw)
        if args[1] == 'update':
            raise RuntimeError('SYNTHETIC-PRIVATE')
        return result
    probe.request = lost
    with pytest.raises(RuntimeError):
        probe.call(host_command('restart-no', target))
    record = json.loads(next(tmp_path.glob('*.pending')).read_text())
    assert record['index'] == 0 and record['identifier'] == target
    (tmp_path / 'bad.pending').write_text('{"operation":"SYNTHETIC-PRIVATE"}')
    result = probe.cleanup()
    assert result['status'] == 'incomplete' and not docker.containers
    assert 'pending-update' in {d['code'] for d in result['details']}
    assert 'pending-unverified' in {d['code'] for d in result['details']}
    assert 'SYNTHETIC-PRIVATE' not in json.dumps(result)
