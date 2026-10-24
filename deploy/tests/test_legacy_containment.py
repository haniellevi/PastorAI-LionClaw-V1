"""Contenção sintética: operações e recusas do controlador, sem Docker real.

O Docker é um duplo em memória que registra cada chamada. O ensaio físico é o
comando separado ``deploy/rehearse_legacy_containment.py``.
"""
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rehearse_legacy_containment as containment  # noqa: E402
import synthetic_legacy_worker as worker  # noqa: E402

WORKER_IMAGE = 'sha256:' + 'a' * 64
REDIS_IMAGE = 'sha256:' + 'b' * 64
RUN_ID = 'c' * 32
VALUED = {'--pull', '--restart', '--name', '--network', '--network-alias', '--security-opt', '--label',
          '--env', '--tmpfs', '--cap-drop', '--entrypoint', '--user'}


class FakeDocker:
    def __init__(self, host='unix:///var/run/docker.sock'):
        self.host = host
        self.images = {WORKER_IMAGE, REDIS_IMAGE}
        self.containers, self.networks, self.calls = {}, {}, []
        self.probe_output = 'accepted'
        self.fail_start_role = None
        self.fail_rm, self.fail_inspect, self.fail_list = set(), set(), False
        self.timeout_on = None  # (comando, ID): passa pelo run() real, com subprocess que expira

    @staticmethod
    def new_id():
        return uuid.uuid4().hex + uuid.uuid4().hex

    def add_container(self, *, labels, network, image=WORKER_IMAGE, env=(), entrypoint=('python3',),
                      user=containment.USER, ignore_term=False):
        cid = self.new_id()
        name = self.networks[network]['name'] if network in self.networks else 'outra-rede'
        self.containers[cid] = dict(
            Id=cid, Image=image, RestartCount=0, ignore_term=ignore_term, boots=1,
            Config=dict(Labels=dict(labels), Env=list(env), Entrypoint=list(entrypoint), User=user),
            HostConfig=dict(PortBindings={}, PublishAllPorts=False, Privileged=False, Binds=None,
                            NetworkMode=network),
            Mounts=[], NetworkSettings=dict(Networks={name: {'NetworkID': network}}, Ports={}),
            State=dict(Running=True, ExitCode=0))
        return cid

    def role(self, cid):
        return self.containers[cid]['Config']['Labels'].get(containment.ROLE_LABEL)

    def __call__(self, argv):
        self.calls.append(argv)
        assert argv[0] == 'docker'
        command, args = argv[1], argv[2:]
        if self.timeout_on and command == self.timeout_on[0] and self.timeout_on[1] in args:
            return containment.run(argv)
        if command == 'context':
            return json.dumps([{'Endpoints': {'docker': {'Host': self.host}}}])
        if command == 'image':
            if args[1] not in self.images:
                raise containment.Refused('docker-step')
            return json.dumps([{'Id': args[1]}])
        if command == 'network':
            return self._network(args)
        if command == 'run':
            return self._run(args)
        if command == 'container':
            assert args == ['ls', '-aq', '--no-trunc'], 'listagem sem filtro de label'
            if self.fail_list:
                raise containment.Refused('docker-step')
            return '\n'.join(self.containers)
        if command == 'inspect':
            if args[0] not in self.containers or args[0] in self.fail_inspect:
                raise containment.Refused('docker-step')
            hidden = {'ignore_term', 'boots'}
            return json.dumps([{k: v for k, v in self.containers[args[0]].items() if k not in hidden}])
        if command == 'ps':
            name, value = args[args.index('--filter') + 1].removeprefix('label=').split('=', 1)
            return '\n'.join(cid for cid, c in self.containers.items() if c['Config']['Labels'].get(name) == value)
        if command == 'kill':
            assert args[:2] == ['--signal', 'SIGTERM'], 'somente SIGTERM'
            container = self.containers[args[2]]
            if not container['ignore_term']:
                container['State'] = dict(Running=False, ExitCode=0)
            return ''
        if command == 'start':
            if self.role(args[0]) == self.fail_start_role:
                raise containment.Refused('docker-step')
            container = self.containers[args[0]]
            container['State'] = dict(Running=True, ExitCode=0)
            container['boots'] += 1
            return ''
        if command == 'wait':
            self.containers[args[0]]['State'] = dict(Running=False, ExitCode=0)
            return '0'
        if command == 'logs':
            return self.probe_output
        if command == 'exec':
            if args[2] == 'PING':
                return 'PONG'
            if args[2] == 'GET' and args[3].startswith('synthetic:boots:'):
                role = args[3].removeprefix('synthetic:boots:')
                found = [c for cid, c in self.containers.items() if self.role(cid) == role]
                return str(found[-1]['boots']) if found else ''
            return ''
        if command == 'rm':
            if args[-1] not in self.containers or args[-1] in self.fail_rm:
                raise containment.Refused('docker-step')
            self.containers.pop(args[-1])
            return ''
        raise AssertionError(f'comando inesperado: {command}')

    def _network(self, args):
        if args[0] == 'create':
            nid = self.new_id()
            labels = dict(args[i + 1].split('=', 1) for i, a in enumerate(args) if a == '--label')
            self.networks[nid] = dict(name=args[-1], internal='--internal' in args, labels=labels)
            return nid
        if args[0] == 'ls':
            assert args[1:] == ['-q', '--no-trunc'], 'listagem sem filtro de label'
            if self.fail_list:
                raise containment.Refused('docker-step')
            return '\n'.join(self.networks)
        if args[0] == 'inspect':
            if args[1] not in self.networks:
                raise containment.Refused('docker-step')
            net = self.networks[args[1]]
            attached = {cid: {} for cid, c in self.containers.items()
                        if c['HostConfig']['NetworkMode'] == args[1] and c['State']['Running']}
            return json.dumps([{'Internal': net['internal'], 'Labels': net['labels'], 'Containers': attached}])
        if args[0] == 'rm':
            self.networks.pop(args[1])
            return ''
        raise AssertionError('rede inesperada')

    def _run(self, args):
        labels, env, options, i = {}, [], {}, 0
        while args[i].startswith('-'):
            flag = args[i]
            if flag in VALUED:
                value = args[i + 1]
                if flag == '--label':
                    labels.update([value.split('=', 1)])
                elif flag == '--env':
                    env.append(value)
                else:
                    options[flag] = value
                i += 2
            else:
                i += 1
        return self.add_container(labels=labels, network=options.get('--network'), image=args[i], env=env,
                                  entrypoint=(options.get('--entrypoint'),), user=options.get('--user'),
                                  ignore_term='SYNTHETIC_IGNORE_TERM=1' in env)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def rehearsal(docker):
    clock = Clock()
    return containment.Rehearsal(worker_image=WORKER_IMAGE, redis_image=REDIS_IMAGE, runner=docker,
                                 clock=clock, sleep=clock.sleep, run_id=RUN_ID)


def created(docker=None, **create):
    docker = docker or FakeDocker()
    r = rehearsal(docker)
    r.create(**create)
    docker.calls.clear()
    return docker, r


def effects(calls):
    return [c for c in calls if c[1] in {'run', 'kill', 'start', 'stop', 'rm', 'restart'}
            or c[1:3] in (['network', 'create'], ['network', 'rm'])]


@pytest.mark.parametrize('image', ['python:3.13', 'sha256:abc', 'repo@sha256:' + 'a' * 64, None])
def test_mutable_or_malformed_image_refused_without_docker(image):
    docker = FakeDocker()
    with pytest.raises(containment.Refused, match='image-not-local-immutable'):
        containment.Rehearsal(worker_image=image, redis_image=REDIS_IMAGE, runner=docker)
    assert docker.calls == []


@pytest.mark.parametrize('host,env', [
    ('tcp://10.0.0.5:2376', None), ('ssh://operador@host', None),
    ('unix:///var/run/docker.sock', 'DOCKER_HOST'), ('unix:///var/run/docker.sock', 'DOCKER_CONTEXT'),
])
def test_remote_docker_refused_before_any_effect(monkeypatch, host, env):
    for name in containment.REMOTE_ENV:
        monkeypatch.delenv(name, raising=False)
    if env:
        monkeypatch.setenv(env, 'qualquer')
    docker = FakeDocker(host=host)
    with pytest.raises(containment.Refused, match='remote-docker'):
        rehearsal(docker).create()
    assert effects(docker.calls) == []


def test_image_not_present_locally_refused_before_network_or_container():
    docker = FakeDocker()
    docker.images.discard(REDIS_IMAGE)
    with pytest.raises(containment.Refused, match='image-not-local-immutable'):
        rehearsal(docker).create()
    assert effects(docker.calls) == []


def test_create_order_redis_ready_then_workers_then_http_readiness():
    docker = FakeDocker()
    r = rehearsal(docker)
    r.create()
    calls = docker.calls
    runs = [i for i, c in enumerate(calls) if c[1] == 'run']
    ping = next(i for i, c in enumerate(calls) if c[1] == 'exec' and 'PING' in c)
    assert runs[0] < ping < runs[1], 'Redis pronto antes de provedor e workers'
    labels = [next(a for a in calls[i] if a.startswith(containment.ROLE_LABEL + '=')) for i in runs]
    assert labels[:6] == [f'{containment.ROLE_LABEL}={role}' for role in ('redis', 'provider', *containment.CONTAIN_ORDER)]
    probe = runs[6]
    assert labels[6] == f'{containment.ROLE_LABEL}=probe' and calls[probe][-2:] == ['ready', '']
    last_boot = max(i for i, c in enumerate(calls) if c[1] == 'exec' and 'GET' in c)
    first_ps = next(i for i, c in enumerate(calls) if c[1] == 'ps')
    assert last_boot < probe < first_ps, 'HTTP real depois dos marcadores e antes da validação'
    assert r.state['status'] == 'running'


def test_every_container_has_explicit_entrypoint_user_and_isolation():
    docker = FakeDocker()
    r = rehearsal(docker)
    r.create()
    r.probe('post', '{}')
    for argv in (c for c in docker.calls if c[1] == 'run'):
        entrypoint = argv[argv.index('--entrypoint') + 1]
        is_redis = f'{containment.ROLE_LABEL}=redis' in argv
        assert entrypoint == ('redis-server' if is_redis else 'python3')
        assert argv[argv.index('--user') + 1] == containment.USER
        assert argv[argv.index('--pull') + 1] == 'never' and '--read-only' in argv
        assert argv[argv.index('--cap-drop') + 1] == 'ALL'
        assert not {'-p', '--publish', '-P', '-v', '--volume', '--mount', '--privileged'} & set(argv)
        assert not any('docker.sock' in part or 'com.docker.compose' in part for part in argv)
        if is_redis:
            assert '--protected-mode' in argv and argv[argv.index('--dir') + 1] == '/data'
            assert argv[argv.index('--tmpfs') + 1].startswith('/data:')
    assert '--internal' in next(c for c in docker.calls if c[1:3] == ['network', 'create'])


def test_ledger_records_every_created_resource_including_probes():
    docker = FakeDocker()
    r = rehearsal(docker)
    r.create()
    r.probe('post', '{}')
    r.start_container('intruder')
    runs = len([c for c in docker.calls if c[1] == 'run'])
    assert len(r.created['containers']) == runs and r.created['networks'] == [r.network]


def test_cleanup_removes_only_ledger_ids_never_label_lookalikes():
    docker, r = created()
    lookalike = docker.add_container(labels={containment.OWNER_LABEL: RUN_ID, containment.ROLE_LABEL: 'queue-worker'},
                                     network=r.network)
    foreign_net = docker._network(['create', '--label', f'{containment.OWNER_LABEL}={RUN_ID}', 'falsa'])
    result = r.cleanup()
    removed = {c[-1] for c in docker.calls if c[1] == 'rm'}
    assert removed == set(r.ids.values())
    assert set(docker.containers) == {lookalike} and set(docker.networks) == {foreign_net}
    assert not any(c[1] == 'ps' for c in docker.calls), 'limpeza não procura por label'
    assert result == {'status': 'clean', 'errors': [], 'leftovers': {'containers': [], 'networks': []}}


def test_cleanup_attempts_every_ledger_id_when_one_rm_fails():
    docker, r = created()
    stuck = r.ids['queue-worker']
    docker.fail_rm.add(stuck)
    result = r.cleanup()
    assert {c[-1] for c in docker.calls if c[1] == 'rm'} == set(r.ids.values())
    assert ['docker', 'network', 'rm', r.network] in docker.calls
    assert set(docker.containers) == {stuck} and not docker.networks
    assert result == {'status': 'incomplete',
                      'errors': [{'kind': 'containers', 'id': stuck, 'code': 'rm-failed'}],
                      'leftovers': {'containers': [stuck], 'networks': []}}


def test_cleanup_inspect_failure_is_a_leftover_not_absence():
    docker, r = created()
    hidden = r.ids['backend']
    docker.fail_inspect.add(hidden)
    result = r.cleanup()
    assert ['docker', 'rm', '-f', '-v', hidden] not in docker.calls and hidden in docker.containers
    assert {c[-1] for c in docker.calls if c[1] == 'rm'} == set(r.ids.values()) - {hidden}
    assert result['status'] == 'incomplete'
    assert result['errors'] == [{'kind': 'containers', 'id': hidden, 'code': 'inspect-failed'}]
    assert result['leftovers']['containers'] == [hidden]


def test_cleanup_unavailable_docker_is_never_reported_as_absent():
    docker, r = created()
    docker.fail_list = True
    result = r.cleanup()
    assert not [c for c in docker.calls if c[1] in {'rm', 'inspect'} or c[1:3] == ['network', 'rm']]
    assert result['status'] == 'incomplete'
    assert {e['code'] for e in result['errors']} == {'list-unavailable'}
    assert result['leftovers'] == {'containers': list(reversed(r.created['containers'])),
                                   'networks': [r.network]}


@pytest.mark.parametrize('outcome', ['refused', 'pass'])
def test_cleanup_failure_fails_report_without_erasing_original_reason(monkeypatch, tmp_path, outcome):
    docker, make = FakeDocker(), containment.Rehearsal
    clock = Clock()
    monkeypatch.setattr(containment, 'Rehearsal', lambda **_kw: make(
        worker_image=WORKER_IMAGE, redis_image=REDIS_IMAGE, runner=docker, clock=clock,
        sleep=clock.sleep, run_id=RUN_ID))

    def scenario(r):
        r.create()
        docker.fail_rm.add(r.ids['queue-worker'])
        if outcome == 'refused':
            raise containment.Refused('graceful-timeout')
        return ['ok']

    monkeypatch.setattr(containment, 'SCENARIOS', {'primeiro': scenario, 'seguinte': scenario})
    path = tmp_path / 'report.json'
    assert containment.main(['--worker-image', WORKER_IMAGE, '--redis-image', REDIS_IMAGE,
                             '--report', str(path)]) == 1
    report = json.loads(path.read_text())
    entry = report['scenarios']['primeiro']
    assert report['status'] == 'fail' and 'seguinte' not in report['scenarios']
    assert entry['result'] == 'fail' and entry['cleanup']['status'] == 'incomplete'
    assert entry['reason'] == ('graceful-timeout' if outcome == 'refused' else 'cleanup-incomplete')
    assert entry['cleanup']['leftovers']['containers']


def test_contain_sends_only_sigterm_hook_between_signal_and_wait():
    docker, r = created()
    seen = []

    def hook(role):
        seen.append((role, docker.calls[-1]))

    r.contain(on_signal=hook)
    kills = [c for c in docker.calls if c[1] == 'kill']
    assert [c[4] for c in kills] == [r.ids[role] for role in containment.CONTAIN_ORDER]
    assert all(c[2:4] == ['--signal', 'SIGTERM'] for c in kills)
    assert [(role, call[1]) for role, call in seen] == [(role, 'kill') for role in containment.CONTAIN_ORDER]
    assert not [c for c in effects(docker.calls) if c[1] != 'kill']
    assert all(docker.containers[r.ids[role]]['State']['Running'] for role in containment.SUPPORT)
    assert r.state['status'] == 'contained'


def test_graceful_timeout_never_kills_and_blocks_ddl_and_resume():
    docker, r = created(ignore_term={'queue-worker'})
    with pytest.raises(containment.Refused, match='graceful-timeout'):
        r.contain(grace_s=3)
    assert docker.containers[r.ids['queue-worker']]['State']['Running']
    assert not [c for c in effects(docker.calls) if c[1] != 'kill']
    assert r.state == {'status': 'refused', 'ddl_marked': False, 'reason': 'graceful-timeout'}
    with pytest.raises(containment.Refused, match='not-contained'):
        r.mark_ddl()
    with pytest.raises(containment.Refused, match='not-contained'):
        r.resume(r.resume_token())
    assert not [c for c in docker.calls if c[1] == 'start']


@pytest.mark.parametrize('grace', [0, -1, 121])
def test_grace_outside_range_refused_before_signal(grace):
    docker, r = created()
    with pytest.raises(containment.Refused, match='grace'):
        r.contain(grace_s=grace)
    assert effects(docker.calls) == []


def test_interruption_stops_sequence_without_further_signals():
    docker, r = created()

    def interrupt(_role):
        raise KeyboardInterrupt

    with pytest.raises(containment.Refused, match='interrupted'):
        r.contain(on_signal=interrupt)
    assert len([c for c in docker.calls if c[1] == 'kill']) == 1
    assert r.state['reason'] == 'interrupted'
    with pytest.raises(containment.Refused, match='not-contained'):
        r.resume(r.resume_token())


@pytest.mark.parametrize('intruder', ['owned', 'foreign'])
def test_fifth_writer_refused_before_any_signal(intruder):
    docker, r = created()
    labels = {containment.OWNER_LABEL: RUN_ID if intruder == 'owned' else 'outro', containment.ROLE_LABEL: 'intruder'}
    docker.add_container(labels=labels, network=r.network)
    with pytest.raises(containment.Refused, match='unexpected-container'):
        r.contain()
    assert effects(docker.calls) == []


def test_swapped_identity_refused_before_any_signal():
    docker, r = created()
    labels = docker.containers.pop(r.ids['queue-worker'])['Config']['Labels']
    docker.add_container(labels=labels, network=r.network, env=[f'{k}={v}' for k, v in containment.GATES.items()])
    with pytest.raises(containment.Refused, match='unexpected-container'):
        r.contain()
    assert effects(docker.calls) == []


@pytest.mark.parametrize('mutation,code', [
    (lambda c: c['HostConfig'].update(PortBindings={'8000/tcp': [{'HostPort': '8000'}]}), 'host-exposure'),
    (lambda c: c.update(Mounts=[{'Type': 'bind', 'Source': '/var/run/docker.sock'}]), 'host-exposure'),
    (lambda c: c['HostConfig'].update(Binds=['/srv:/srv']), 'host-exposure'),
    (lambda c: c.update(Image='sha256:' + 'd' * 64), 'image'),
    (lambda c: c['Config'].update(Entrypoint=['/docker-entrypoint.sh']), 'entrypoint'),
    (lambda c: c['Config'].update(User='0:0'), 'entrypoint'),
    (lambda c: c['Config']['Labels'].update({containment.OWNER_LABEL: 'outro'}), 'unexpected-container'),
    (lambda c: c['HostConfig'].update(NetworkMode='outra-rede'), 'network'),
    (lambda c: c.update(RestartCount=1), 'unexpected-state'),
])
def test_invalid_container_refused_before_any_signal(mutation, code):
    docker, r = created()
    mutation(docker.containers[r.ids['backend']])
    with pytest.raises(containment.Refused, match=code):
        r.contain()
    assert effects(docker.calls) == []


def test_resume_api_first_then_consumers_with_validation_before_each_start():
    docker, r = created()
    with pytest.raises(containment.Refused, match='not-contained'):
        r.resume(r.resume_token())
    r.contain()
    for wrong in ('', 'RETOMAR-PRE-DDL:' + 'd' * 32, r.resume_token() + ' '):
        with pytest.raises(containment.Refused, match='confirmation'):
            r.resume(wrong)
    assert not [c for c in docker.calls if c[1] == 'start']
    docker.calls.clear()
    r.resume(r.resume_token())
    starts = [i for i, c in enumerate(docker.calls) if c[1] == 'start']
    assert [docker.calls[i][2] for i in starts] == [r.ids[role] for role in containment.RESUME_ORDER]
    assert containment.RESUME_ORDER[0] == 'backend'
    previous = 0
    for index in starts:
        assert any(c[1] == 'ps' for c in docker.calls[previous:index]), 'validação antes de cada start'
        previous = index
    assert r.state['status'] == 'resumed'
    assert not [c for c in effects(docker.calls) if c[1] != 'start']


@pytest.mark.parametrize('failing', ['backend', 'broadcast-worker'])
def test_failed_start_records_refusal_without_retry(failing):
    docker, r = created()
    r.contain()
    docker.calls.clear()
    docker.fail_start_role = failing
    with pytest.raises(containment.Refused, match='resume-failed:docker-step'):
        r.resume(r.resume_token())
    starts = [c[2] for c in docker.calls if c[1] == 'start']
    position = containment.RESUME_ORDER.index(failing)
    assert starts == [r.ids[role] for role in containment.RESUME_ORDER[:position + 1]]
    assert r.state == {'status': 'refused', 'ddl_marked': False, 'reason': 'resume-failed:docker-step'}
    with pytest.raises(containment.Refused, match='not-contained'):
        r.resume(r.resume_token())
    assert len([c for c in docker.calls if c[1] == 'start']) == position + 1


def test_post_ddl_mark_refuses_legacy_resume():
    docker, r = created()
    r.contain()
    r.mark_ddl()
    with pytest.raises(containment.Refused, match='post-ddl'):
        r.resume(r.resume_token())
    assert not [c for c in docker.calls if c[1] == 'start']


def test_changed_gate_config_refuses_resume():
    docker, r = created()
    r.contain()
    env = docker.containers[r.ids['broadcast-worker']]['Config']['Env']
    env[env.index('SYNTHETIC_BROADCAST_ASYNC_ENABLED=false')] = 'SYNTHETIC_BROADCAST_ASYNC_ENABLED=true'
    with pytest.raises(containment.Refused, match='gate-config-changed'):
        r.resume(r.resume_token())
    assert not [c for c in docker.calls if c[1] == 'start']


def _expiring_subprocess(monkeypatch):
    def expire(argv, **_kwargs):
        raise subprocess.TimeoutExpired(argv, 120, output='SAIDA-SENSIVEL', stderr='ERRO-SENSIVEL')
    monkeypatch.setattr(containment.subprocess, 'run', expire)


def test_docker_timeout_is_fixed_refusal_without_command_or_output(monkeypatch):
    _expiring_subprocess(monkeypatch)
    with pytest.raises(containment.Refused) as caught:
        containment.run(['docker', 'kill', '--signal', 'SIGTERM', 'x'])
    assert str(caught.value) == 'docker-timeout' and caught.value.args == ('docker-timeout',)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize('phase', ['contain', 'resume'])
def test_docker_timeout_stops_sequence_without_further_effects(monkeypatch, phase):
    _expiring_subprocess(monkeypatch)
    docker, r = created()
    order = containment.CONTAIN_ORDER if phase == 'contain' else containment.RESUME_ORDER
    command = 'kill' if phase == 'contain' else 'start'
    if phase == 'resume':
        r.contain()
        docker.calls.clear()
    docker.timeout_on = (command, r.ids[order[1]])
    with pytest.raises(containment.Refused) as caught:
        r.contain() if phase == 'contain' else r.resume(r.resume_token())
    reason = 'docker-timeout' if phase == 'contain' else 'resume-failed:docker-timeout'
    assert str(caught.value) == reason and r.state['reason'] == reason
    assert [c[-1] for c in docker.calls if c[1] == command] == [r.ids[role] for role in order[:2]]
    assert not [c for c in effects(docker.calls) if c[1] != command]
    with pytest.raises(containment.Refused, match='not-contained'):
        r.mark_ddl()
    with pytest.raises(containment.Refused, match='not-contained'):
        r.resume(r.resume_token())
    assert len([c for c in docker.calls if c[1] == command]) == 2


def test_probe_is_removed_and_reports_backend_refusal():
    docker, r = created()
    docker.probe_output = 'refused'
    assert r.probe('post', '{}') == 'refused'
    probe_id = r.created['containers'][-1]
    assert ['docker', 'rm', '-f', '-v', probe_id] in docker.calls and probe_id not in docker.containers


# -- processos simulados ---------------------------------------------------

class FakeRedis:
    def __init__(self):
        self.lists, self.keys = {}, set()

    def command(self, name, *args):
        lists = self.lists
        if name in {'LMOVE', 'BLMOVE'}:
            source, target = lists.setdefault(args[0], []), lists.setdefault(args[1], [])
            if not source:
                return None
            target.append(source.pop(0))
            return target[-1]
        if name == 'RPUSH':
            lists.setdefault(args[0], []).append(args[1])
            return len(lists[args[0]])
        if name == 'LREM':
            items = lists.setdefault(args[0], [])
            if args[2] in items:
                items.remove(args[2])
                return 1
            return 0
        if name == 'LRANGE':
            return list(lists.get(args[0], []))
        if name == 'EXISTS':
            return int(args[0] in self.keys)
        raise AssertionError(name)


def item(key, deadline):
    return json.dumps({'deadline': deadline, 'key': key}, separators=(',', ':'), sort_keys=True)


def test_in_flight_is_quarantined_and_never_resent():
    redis, sent = FakeRedis(), []
    redis.lists['synthetic:queue:processing'] = [item('em-curso', 999)]
    assert worker.quarantine_in_flight(redis, 'queue') == 1
    assert worker.process_one(redis, 'queue', send=sent.append, now=lambda: 0, gate_open=True) == 'idle'
    assert sent == [] and redis.lists['synthetic:queue:ambiguous'] == [item('em-curso', 999)]


def test_send_without_response_goes_ambiguous_without_retry():
    redis, attempts = FakeRedis(), []
    raw = item('sem-resposta', 100)
    redis.lists['synthetic:queue:pending'] = [raw]

    def send(key):
        attempts.append(key)
        raise TimeoutError('timed out')

    assert worker.process_one(redis, 'queue', send=send, now=lambda: 1, gate_open=True) == 'ambiguous'
    assert worker.process_one(redis, 'queue', send=send, now=lambda: 1, gate_open=True) == 'idle'
    assert attempts == ['sem-resposta']
    assert redis.lists['synthetic:queue:ambiguous'] == [raw] and redis.lists['synthetic:queue:processing'] == []


def test_expired_item_kept_byte_for_byte_and_not_sent():
    redis, sent = FakeRedis(), []
    raw = item('vencido', 10)
    redis.lists['synthetic:queue:pending'] = [raw]
    assert worker.process_one(redis, 'queue', send=sent.append, now=lambda: 11, gate_open=True) == 'expired'
    assert sent == [] and redis.lists['synthetic:queue:expired'] == [raw]
    assert redis.lists['synthetic:queue:processing'] == []


def test_pending_item_sent_once_and_acknowledged():
    redis, sent = FakeRedis(), []
    redis.lists['synthetic:queue:pending'] = [item('valido', 100)]
    assert worker.process_one(redis, 'queue', send=sent.append, now=lambda: 1, gate_open=True) == 'done'
    assert worker.process_one(redis, 'queue', send=sent.append, now=lambda: 1, gate_open=True) == 'idle'
    assert sent == ['valido'] and redis.lists['synthetic:queue:processing'] == []
    assert redis.lists['synthetic:queue:done'] == [item('valido', 100)]


def test_closed_gate_leaves_pending_untouched():
    redis, sent = FakeRedis(), []
    redis.lists['synthetic:broadcast:pending'] = [item('broadcast', 100)]
    env = dict(containment.GATES)
    assert not worker.gate_open('broadcast-worker', env) and worker.gate_open('queue-worker', env)
    assert worker.process_one(redis, 'broadcast', send=sent.append, now=lambda: 1,
                              gate_open=worker.gate_open('broadcast-worker', env)) == 'gated'
    assert sent == [] and redis.lists['synthetic:broadcast:pending'] == [item('broadcast', 100)]


def test_provider_barrier_holds_until_released_and_is_bounded():
    redis, sleeps = FakeRedis(), []
    redis.keys.add(worker.HOLD)

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            redis.keys.discard(worker.HOLD)

    assert worker.hold_until_released(redis, sleep=sleep) is True and len(sleeps) == 3
    redis.keys.add(worker.HOLD)
    assert worker.hold_until_released(redis, sleep=lambda _s: None, polls=5) is False


def test_cron_promotes_only_due_items_unchanged():
    redis = FakeRedis()
    due, later = json.dumps({'due': 5, 'deadline': 50, 'key': 'a'}), json.dumps({'due': 20, 'deadline': 50, 'key': 'b'})
    redis.lists[worker.SCHEDULED] = [due, later]
    assert worker.promote_due(redis, lambda: 10) == 1
    assert redis.lists['synthetic:queue:pending'] == [due] and redis.lists[worker.SCHEDULED] == [later]


class CliRedis:
    """Saída no formato do ``redis-cli`` sobre o FakeRedis, como ``Rehearsal.redis``."""

    def __init__(self):
        self.store = FakeRedis()

    def redis(self, *args):
        if args[0] == 'HGET':
            return ''
        result = self.store.command(*args)
        return '\n'.join(result) if isinstance(result, list) else str(result)


def test_parked_broadcast_and_future_cron_keep_bytes_under_unchanged_gates():
    stub, sent = CliRedis(), []
    raws = containment._seed_parked(stub, 1000.0)
    containment._assert_parked(stub, raws)
    env = dict(containment.GATES)
    for _ in range(3):  # antes da contenção, durante e depois da retomada
        assert worker.process_one(stub.store, 'broadcast', send=sent.append, now=lambda: 1001.0,
                                  gate_open=worker.gate_open('broadcast-worker', env)) == 'gated'
        assert worker.promote_due(stub.store, lambda: 1001.0) == 0
    assert sent == [] and env == containment.GATES
    containment._assert_parked(stub, raws)
    assert json.loads(raws['scheduled'])['due'] > 1000.0 + containment.EXPIRY_S + containment.GRACE_S


def test_physical_timeouts_are_ordered_for_deterministic_scenarios():
    assert containment.PROVIDER_TIMEOUT_S < containment.GRACE_S <= 120
    assert containment.GRACE_S < containment.EXPIRY_S
