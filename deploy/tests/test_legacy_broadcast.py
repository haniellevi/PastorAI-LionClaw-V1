"""Ensaio do broadcast-worker legado ocioso: avaliações puras, guardas e roteiro, sem Docker real.

O mundo falso imita só o contrato observável do worker legado desligado
(heartbeat ``idle``/``stopped`` com TTL, log, saída). O ensaio físico é
``deploy/rehearse_legacy_broadcast.py run``.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rehearse_legacy_broadcast as broadcast  # noqa: E402
import rehearse_legacy_containment as containment  # noqa: E402
import rehearse_legacy_queue as legacy  # noqa: E402

LEGACY = 'sha256:' + 'a' * 64
REDIS = 'sha256:' + 'b' * 64
FILES = {'app/__init__.py': b'', 'app/workers/queue_worker.py': b'# legado\n',
         'app/workers/broadcast_worker.py': b'# legado\n', 'app/services/broadcast_health.py': b'# legado\n',
         'app/services/worker_health.py': b'# legado\n',
         'requirements.lock': b'# --python-version 3.13\nredis==7.0.1\n'}
NET, REDIS_ID, WORKER_ID = 'e' * 64, '1' * 64, '2' * 64


@pytest.fixture(autouse=True)
def local_docker(monkeypatch):
    for name in containment.REMOTE_ENV:
        monkeypatch.delenv(name, raising=False)


def _rehearsal(runner=lambda argv: '', files=FILES, **kwargs):
    return broadcast.BroadcastRehearsal(legacy_image=LEGACY, redis_image=REDIS, files=files, runner=runner,
                                        sleep=lambda _: None, **kwargs)


def _log(*entries):
    """``entries``: mensagem do logger legado ou ``(nível, logger, mensagem)``."""
    lines = []
    for i, entry in enumerate(entries):
        level, name, message = entry if isinstance(entry, tuple) else ('INFO', broadcast.LOGGER, entry)
        lines.append(f'2026-10-25 12:00:{i:02d},000 {level} {name} {message}')
    return ''.join(line + '\n' for line in lines)


WARN = ('WARNING', broadcast.LOGGER, broadcast.IDLE_WARNING)
BOOT = (broadcast.STARTED, WARN)
STOP = ('Broadcast worker shutdown requested', 'Broadcast worker stopped')


# -- avaliações puras -------------------------------------------------------
def test_log_summary_accepts_idle_boots_with_only_the_exact_idle_warning():
    running = broadcast.log_summary(_log(*BOOT))
    assert broadcast.log_ok(running, cycles=0, running=True)
    assert not broadcast.log_ok(running, cycles=0, running=False)
    one = broadcast.log_summary(_log(*BOOT, 'Broadcast worker idle heartbeat', *STOP))
    assert broadcast.log_ok(one, cycles=1, running=False) and one['idle_heartbeats'] == 1
    two = _log(*BOOT, *STOP, *BOOT, *STOP)
    assert broadcast.log_ok(broadcast.log_summary(two), cycles=2, running=False)
    assert broadcast.log_ok(broadcast.log_summary(_log(*BOOT, *STOP, *BOOT)), cycles=1, running=True)
    # INFO de outro logger não é do worker nem problema.
    assert broadcast.log_ok(broadcast.log_summary(two + _log(('INFO', 'httpx', 'x'))), cycles=2, running=False)


@pytest.mark.parametrize('text', [
    _log(*BOOT, 'Broadcast tick done reaped=0 materialized=0 actions=0', *STOP),             # tick
    _log(*BOOT, ('ERROR', broadcast.LOGGER, 'Broadcast dispatch paused: heartbeat unavailable'), *STOP),
    _log(*BOOT, 'Broadcast shutdown requested; transport already in progress', STOP[1]),     # transporte
    _log('Broadcast worker started enabled=True tick=10s', *STOP),                          # habilitado
    _log(broadcast.STARTED, *STOP),                                                          # sem OCIOSO
    _log(*BOOT, ('WARNING', broadcast.LOGGER, 'Broadcast worker heartbeat failed error_type=X'), *STOP),
    _log(*BOOT, *STOP, ('WARNING', 'pastorai.outro', broadcast.IDLE_WARNING)),               # aviso de outro logger
    _log(*BOOT, ('INFO', broadcast.LOGGER, broadcast.IDLE_WARNING), *STOP),                  # nível trocado
    _log(*BOOT, *STOP) + 'Traceback (most recent call last):\n',
    _log(*BOOT, STOP[1]),                                                                    # sem shutdown
    _log(*BOOT, *STOP, STOP[1]),                                                             # stop duplicado
    _log('Broadcast worker started enabled=False tick=300s', WARN, *STOP),
])
def test_log_summary_rejects_ticks_sends_other_warnings_or_disorder(text):
    assert not broadcast.log_ok(broadcast.log_summary(text), cycles=1, running=False)


def test_worker_config_is_real_entrypoint_with_closed_gates_and_dead_database():
    env = broadcast.BROADCAST_ENV
    assert broadcast.ENTRY == ['-m', 'app.workers.broadcast_worker'] and broadcast.ROLE == 'broadcast-worker'
    assert env['ALLOW_REAL_SENDS'] == 'false' and env['BROADCAST_ASYNC_ENABLED'] == 'false'
    assert env['BREVO_SEND_MODE'] == 'off' and env['ASAAS_BILLING_ENABLED'] == 'false'
    assert env['WHATSAPP_PILOTO_IGREJA_IDS'] == '' and env['REDIS_URL'] == 'redis://redis:6379/0'
    assert '@127.0.0.1:9/' in env['DATABASE_URL'] and env['EVOLUTION_API_URL'] == 'http://127.0.0.1:9'
    assert not any('KEY' in name or 'SECRET' in name or 'TOKEN' in name for name in env)
    assert broadcast.HEARTBEAT_TTL_S == 30 and broadcast.RENEW_S > broadcast.TICK_S


def test_source_without_broadcast_modules_is_refused_before_docker():
    for missing in broadcast.REQUIRED:
        calls = []
        with pytest.raises(containment.Refused, match='source-incomplete'):
            _rehearsal(calls.append, files={k: v for k, v in FILES.items() if k != missing})
        assert calls == []


def test_remote_docker_refused_before_any_resource(monkeypatch):
    calls = []
    monkeypatch.setenv('DOCKER_HOST', 'tcp://203.0.113.1:2376')
    rehearsal = _rehearsal(lambda argv: calls.append(argv) or '')
    with pytest.raises(containment.Refused, match='remote-docker'):
        broadcast.rehearse(rehearsal)
    assert not any(argv[1] in ('run', 'network') for argv in calls)


def test_start_worker_runs_pid1_broadcast_entrypoint_hardened_without_host_exposure():
    calls = []
    rehearsal = _rehearsal(lambda argv: calls.append(argv) or WORKER_ID)
    rehearsal.network = NET
    rehearsal.start_worker()
    args = calls[-1][2:]
    assert rehearsal.ids['broadcast-worker'] == WORKER_ID and WORKER_ID in rehearsal.created['containers']
    assert args[-3:] == [LEGACY, '-m', 'app.workers.broadcast_worker']
    assert args.count('--init=false') == 1 and args.index('--init=false') < len(args) - 3  # flag, antes da imagem
    assert args[args.index('--entrypoint') + 1] == 'python' and args[args.index('--pull') + 1] == 'never'
    assert args[args.index('--network') + 1] == NET and '--read-only' in args
    assert f'{containment.ROLE_LABEL}=broadcast-worker' in args
    env = dict(args[i + 1].split('=', 1) for i, a in enumerate(args) if a == '--env')
    assert env == broadcast.BROADCAST_ENV
    assert not {'-p', '--publish', '-P', '--publish-all', '-v', '--volume', '--mount', '--privileged'} & set(args)
    assert args[args.index('--name') + 1].startswith('pastorai-synthetic-legacy-broadcast-')


# -- check_worker real contra inspect enlatado ------------------------------
_ABSENT = object()


def _canned(r, *, env=None, args=None, extra=(), init=False):
    labels = lambda role: {containment.OWNER_LABEL: r.run_id, containment.ROLE_LABEL: role,  # noqa: E731
                           containment.SCOPE_LABEL: containment.SCOPE}
    host = dict(NetworkMode=NET, ReadonlyRootfs=True, **({} if init is _ABSENT else dict(Init=init)))
    common = dict(RestartCount=0, Mounts=[], NetworkSettings=dict(Ports={}, Networks={r.prefix: {}}),
                  HostConfig=host, State=dict(Running=True))
    env = broadcast.BROADCAST_ENV if env is None else env
    found = {
        REDIS_ID: dict(common, Id=REDIS_ID, Image=REDIS, Config=dict(Labels=labels('redis'), User=containment.USER,
                                                                      Entrypoint=['redis-server'])),
        WORKER_ID: dict(common, Id=WORKER_ID, Image=LEGACY, Path='python', Args=args or broadcast.ENTRY,
                        Config=dict(Labels=labels(broadcast.ROLE), Entrypoint=['python'], Cmd=args or broadcast.ENTRY,
                                    User=containment.USER, WorkingDir=legacy.SOURCE_ROOT,
                                    Env=['PATH=/usr/bin', *(f'{k}={v}' for k, v in env.items())])),
    }

    def runner(argv):
        command, rest = argv[1], argv[2:]
        if command == 'context':
            return json.dumps([{'Endpoints': {'docker': {'Host': 'unix:///var/run/docker.sock'}}}])
        if command == 'ps':
            return '\n'.join([REDIS_ID, WORKER_ID, *extra])
        if command == 'inspect':
            return json.dumps([found[rest[0]]])
        if command == 'network':
            return json.dumps([dict(Internal=True, Labels={containment.OWNER_LABEL: r.run_id},
                                    Containers={REDIS_ID: {}, WORKER_ID: {}})])
        raise AssertionError(argv)

    r.runner, r.network, r.image_env = runner, NET, {'PATH'}
    r.ids.update(redis=REDIS_ID, **{broadcast.ROLE: WORKER_ID})
    r.created['containers'] += [REDIS_ID, WORKER_ID]
    return r


@pytest.mark.parametrize('options, code', [
    (dict(env={**broadcast.BROADCAST_ENV, 'ALLOW_REAL_SENDS': 'true'}), 'gate-config-changed'),
    (dict(env={**broadcast.BROADCAST_ENV, 'BROADCAST_ASYNC_ENABLED': 'true'}), 'gate-config-changed'),
    (dict(env={k: v for k, v in broadcast.BROADCAST_ENV.items() if k != 'BROADCAST_ASYNC_ENABLED'}),
     'gate-config-changed'),
    (dict(env={**broadcast.BROADCAST_ENV, 'EVOLUTION_API_KEY': 'x'}), 'gate-config-changed'),
    (dict(args=legacy.ENTRY), 'entrypoint'),
    (dict(extra=['3' * 64]), 'unexpected-container'),  # p.ex. um Postgres: este ensaio não tem banco
    (dict(init=None), 'pid1-init'),       # default do daemon: pode ser ``init: true``
    (dict(init=True), 'pid1-init'),       # docker-init seria o PID 1
    (dict(init=_ABSENT), 'pid1-init'),
])
def test_check_worker_refuses_opened_gates_other_entrypoint_or_extra_container(options, code):
    r = _canned(_rehearsal(), **options)
    with pytest.raises(containment.Refused, match=code):
        r.check_worker(running=True)


def test_check_worker_accepts_exact_closed_gate_set():
    _canned(_rehearsal()).check_worker(running=True)


# -- roteiro com mundo falso -----------------------------------------------
class World(broadcast.BroadcastRehearsal):
    """Substitui só as primitivas de Docker/Redis/log; o roteiro ``rehearse`` é o real."""

    def __init__(self, **faults):
        super().__init__(legacy_image=LEGACY, redis_image=REDIS, files=FILES, runner=self._no_docker,
                         sleep=self._sleep, clock=self._clock)
        self.faults, self.events, self.now = faults, [], 0.0
        self.running, self.exit_at, self.exit_code, self.boots = False, None, 0, 0
        self.hb = self.next_publish = None
        self.text, self.reads_after_stop = '', 0

    def _no_docker(self, argv):
        raise AssertionError(argv)

    def _clock(self):
        self.now += 0.001
        self._advance()
        return self.now

    def _sleep(self, seconds):
        self.now += seconds
        self._advance()

    def _advance(self):
        if self.running and self.exit_at is not None and self.now >= self.exit_at:
            self.running, self.exit_at = False, None
            self.text += _log(*STOP)
            if not self.faults.get('no_stopped'):
                self.hb = ['stopped', self.now + broadcast.HEARTBEAT_TTL_S]
            # Dentro da janela observada (SURVIVE_S) depois da saída.
            self.next_publish = self.now + 1 if self.faults.get('renew_after_stop') else None
        while self.next_publish is not None and self.now >= self.next_publish:
            value = 'stopped' if not self.running else ('running' if self.faults.get('enabled') else 'idle')
            self.hb = [value, self.next_publish + broadcast.HEARTBEAT_TTL_S]
            once = self.running and self.faults.get('no_renew') and self.next_publish > self.boot_at
            self.next_publish = None if once else self.next_publish + broadcast.TICK_S
        if self.hb and self.now >= self.hb[1]:
            self.hb = None

    def _boot(self):
        self.boots += 1
        self.running, self.boot_at, self.next_publish = True, self.now, self.now + 0.5
        self.text += _log(*BOOT)
        if self.faults.get('tick_log'):
            self.text += _log('Broadcast tick done reaped=0 materialized=0 actions=0')

    # primitivas
    def preflight(self):
        self.events.append('preflight')

    def create_support(self):
        self.phase = 'running'

    def start_worker(self):
        self.ids[self.role] = WORKER_ID
        self.events.append('start')
        self._boot()

    def check_worker(self, *, running):
        assert running == self.running

    def inspect(self, identifier):
        assert identifier == WORKER_ID
        same = self.faults.get('same_started') and self.boots > 1
        return dict(State=dict(Running=self.running, ExitCode=0 if self.running else self.exit_code,
                               StartedAt='t1' if same else f't{self.boots}'))

    def docker(self, *args):
        if args == ('kill', '--signal', 'SIGTERM', WORKER_ID):
            self.events.append('sigterm')
            if not self.faults.get('stuck'):
                self.exit_at = self.now + (broadcast.TICK_S if self.faults.get('slow_exit') else 0.5)
            self.exit_code = self.faults.get('exit_code', 0)
            return ''
        assert args == ('start', WORKER_ID) and not self.running
        self.events.append('start')
        self._boot()
        return ''

    def redis(self, *args):
        self._advance()
        if args == ('GET', broadcast.HEARTBEAT):
            return self.hb[0] if self.hb else ''
        if args == ('PTTL', broadcast.HEARTBEAT):
            return str(int((self.hb[1] - self.now) * 1000)) if self.hb else '-2'
        raise AssertionError(args)

    def keys(self):
        self._advance()
        extra = {'pastorai:broadcast:outra'} if self.faults.get('extra_key') else set()
        return ({broadcast.HEARTBEAT} if self.hb else set()) | extra

    def worker_logs(self):
        if not self.running and self.faults.get('log_after_stop'):
            self.reads_after_stop += 1
            if self.reads_after_stop == 2:  # 1ª leitura vê o stop; a linha nova vem depois
                self.text += _log('Broadcast worker idle heartbeat')
        return self.text


def test_script_proves_idle_renewal_stop_restart_and_second_stop():
    world = World()
    broadcast.rehearse(world)
    assert world.events == ['preflight', 'start', 'sigterm', 'start', 'sigterm']
    assert world.boots == 2 and world.started_at == ['t1', 't2']
    assert len(world.checks) == 8 and world.checks[-1] == 'no-activity-after-second-stop'
    assert broadcast.log_ok(world.observed['log_after_stop_2'], cycles=2, running=False)
    assert all(world.timings[f'exit_after_sigterm_{n}_s'] < broadcast.TICK_S for n in (1, 2))
    assert all(world.timings[f'renewed_after_{n}_s'] > 0 for n in (1, 2))
    assert world.hb[0] == 'stopped' and world.keys() == {broadcast.HEARTBEAT}


@pytest.mark.parametrize('fault, value, code, sigterms', [
    ('enabled', True, 'heartbeat-not-idle', 0),           # running = broadcast ativo
    ('no_renew', True, 'heartbeat-not-renewed', 0),
    ('extra_key', True, 'unexpected-redis-state', 0),
    ('tick_log', True, 'worker-log-while-idle', 0),
    ('stuck', True, 'graceful-timeout', 1),               # sem SIGKILL
    ('exit_code', 1, 'ungraceful-exit', 1),
    ('slow_exit', True, 'exit-not-before-next-tick', 1),
    ('no_stopped', True, 'heartbeat-not-stopped', 1),
    ('renew_after_stop', True, 'activity-after-stop', 1),
    ('log_after_stop', True, 'activity-after-stop', 1),
    ('same_started', True, 'not-a-new-execution', 1),
])
def test_script_refuses_any_deviation_from_the_idle_contract(fault, value, code, sigterms):
    world = World(**{fault: value})
    with pytest.raises(containment.Refused, match=code):
        broadcast.rehearse(world)
    assert world.events.count('sigterm') == sigterms


def test_report_is_written_with_production_ready_false_on_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(broadcast, 'legacy_sources', lambda repo: {k: v for k, v in FILES.items()
                                                                   if k != 'app/workers/broadcast_worker.py'})
    report = tmp_path / 'report.json'
    assert broadcast.main(['run', '--repo', str(tmp_path), '--report', str(report)]) == 1
    data = json.loads(report.read_text())
    assert data['status'] == 'refused' and data['reason'] == 'source-incomplete'
    assert data['production_ready'] is False and data['worker_state'] == 'idle'
    assert any(item.startswith('broadcast-ativo') for item in data['not_proven'])
