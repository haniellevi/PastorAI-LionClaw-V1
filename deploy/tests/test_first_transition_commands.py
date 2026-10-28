"""Offline doubles only: never start Docker fixtures during this test suite."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from first_transition_host_transport import host_command
from initial_transition_ops import Refused
from rehearse_first_transition_commands import CommandProbe, OWNER, main, plan

IMAGE = 'sha256:' + 'a'*64
RUN = 'b'*32


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
        if args[:3] == ('docker', 'image', 'inspect'):
            return IMAGE if args[4] == '{{.Id}}' else self.volumes
        if args[:2] == ('docker', 'create'):
            identifier = str(len(self.containers)+1)*64
            name = args[args.index('--name')+1]
            self.containers[identifier] = dict(name=name, owner=RUN, running=False, policy='always')
            if self.lost_create:
                raise Refused('simulated-lost-create-response')
            return identifier
        if args[:2] == ('docker', 'ps'):
            name = args[-1].removeprefix('name=^/').removesuffix('$')
            return '\n'.join(i for i, c in self.containers.items() if c['name'] == name)
        identifier = args[-1]
        state = self.containers[identifier]
        if args[:2] == ('docker', 'inspect'):
            field = args[3]
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


def test_success_uses_shared_encoder_then_cleans_only_owned_resources():
    docker = DockerDouble()
    probe = CommandProbe(plan(IMAGE, RUN), docker)
    result = probe.execute()
    assert result['status'] == 'pass' and result['fixtures'] == 4
    for identifier in probe.ids:
        assert docker.calls.index(host_command('restart-no', identifier)) < docker.calls.index(host_command('term', identifier))
        assert host_command('wait', identifier) in docker.calls
    assert probe.cleanup() == dict(status='clean', failures=0)
    assert not docker.containers


def test_lost_create_response_still_cleans_by_owned_name():
    docker = DockerDouble()
    docker.lost_create = True
    probe = CommandProbe(plan(IMAGE, RUN), docker)
    with pytest.raises(Refused, match='simulated-lost-create-response'):
        probe.execute()
    assert len(docker.containers) == 1
    assert probe.cleanup()['status'] == 'clean'
    assert not docker.containers


def test_wait_timeout_cleans_without_restart():
    docker = DockerDouble()
    docker.timeout_wait = True
    probe = CommandProbe(plan(IMAGE, RUN), docker)
    with pytest.raises(Refused, match='simulated-wait-timeout'):
        probe.execute()
    assert probe.cleanup()['status'] == 'clean'
    assert not docker.containers
    assert not any(command[:2] == ('docker', 'restart') for command in docker.calls)


def test_changed_ownership_is_preserved_and_cleanup_is_incomplete():
    docker = DockerDouble()
    probe = CommandProbe(plan(IMAGE, RUN), docker)
    probe.execute()
    kept = probe.ids[0]
    docker.containers[kept]['owner'] = 'another-owner'
    assert probe.cleanup() == dict(status='incomplete', failures=1)
    assert set(docker.containers) == {kept}
    assert ('docker', 'rm', '-f', kept) not in docker.calls


def test_image_volumes_refused_before_create():
    docker = DockerDouble()
    docker.volumes = '{"/data":{}}'
    probe = CommandProbe(plan(IMAGE, RUN), docker)
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

    def run(args, **kwargs):
        assert args[:3] == ['docker', '-H', 'unix:///var/run/docker.sock']
        assert args[3] == '--config' and Path(args[4]).is_dir()
        assert kwargs['env'] == {'PATH': '/usr/bin:/bin'}
        return subprocess.CompletedProcess(args, 0, docker(tuple(['docker', *args[5:]]), timeout=kwargs['timeout']), '')

    monkeypatch.setattr(subprocess, 'run', run)
    report = tmp_path / 'report.json'
    args = ['--image', IMAGE, '--run-id', RUN, '--execute', '--report', str(report)]
    assert main(args) == 0
    result = json.loads(report.read_text())
    assert result['status'] == 'pass' and result['cleanup']['status'] == 'clean'
    assert len(result['scope']['creates']) == 4 and not docker.containers
    calls = len(docker.calls)
    with pytest.raises(FileExistsError):
        main(args)
    assert len(docker.calls) == calls
