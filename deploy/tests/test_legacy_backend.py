"""Ensaio do backend ASGI legado com HTTP em curso: avaliações puras e guardas do roteiro, sem Docker real.

O ensaio físico (uvicorn real, Redis e probes) é ``deploy/rehearse_legacy_backend.py run``.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rehearse_legacy_backend as backend  # noqa: E402
import rehearse_legacy_containment as containment  # noqa: E402

LEGACY = 'sha256:' + 'a' * 64
REDIS = 'sha256:' + 'b' * 64
FILES = {'app/__init__.py': b'', 'app/main.py': b'# legado\n', 'app/config.py': b'# legado\n',
         'app/routers/whatsapp.py': b'# legado\n', 'app/workers/queue_worker.py': b'# legado\n',
         'requirements.lock': b'# --python-version 3.13\nuvicorn==0.49.0\n'}
BACKEND_IP, PROBE_IP, PROBE_PORT = '172.30.0.2', '172.30.0.5', 41000
PEER = f'{PROBE_IP}:{PROBE_PORT}'
INTERPRETER, SCRIPT = '/usr/local/bin/python3.13', '/usr/local/bin/uvicorn'
ENVELOPE = json.dumps({'payload': backend.IGNORED_PAYLOAD, 'attempts': 0, 'claim_id': 'c' * 32})


@pytest.fixture(autouse=True)
def local_docker(monkeypatch):
    for name in containment.REMOTE_ENV:
        monkeypatch.delenv(name, raising=False)


def _rehearsal(runner=lambda argv: '', files=FILES, **kwargs):
    return backend.BackendRehearsal(legacy_image=LEGACY, redis_image=REDIS, files=files, runner=runner,
                                    sleep=lambda _: None, **kwargs)


# -- avaliações puras -------------------------------------------------------
UVICORN_OK = dict(backend.UVICORN_EXPECTED, script=SCRIPT, interpreter=INTERPRETER)


def test_uvicorn_runtime_matches_expectations():
    assert backend.uvicorn_mismatch(UVICORN_OK) == {}


@pytest.mark.parametrize('change', [
    dict(version='0.30.0'),
    dict(entry_points=[['uvicorn', 'evil:main']]),
    dict(record_ok=False),                         # script alterado depois do pip
    dict(http='H11Protocol'),                      # premissas de httptools não valem
    dict(keeps_inflight=False),
    dict(waits_connections=False),
    dict(script=None),
    dict(interpreter='/bin/sh -c'),                # shebang com argumentos
])
def test_uvicorn_runtime_mismatch_is_reported(change):
    assert backend.uvicorn_mismatch(dict(UVICORN_OK, **change))


PID1 = dict(cmdline=[INTERPRETER, SCRIPT, *backend.ARGS], ppid=['0'], uid=['65534', '65534'], others=[])


def test_pid1_is_uvicorn_console_script_without_init():
    assert backend.pid1_ok(PID1, INTERPRETER, SCRIPT)


@pytest.mark.parametrize('change', [
    dict(cmdline=['/sbin/docker-init', '--', SCRIPT, *backend.ARGS]),
    dict(cmdline=[INTERPRETER, '-m', 'uvicorn', *backend.ARGS]),
    dict(cmdline=[INTERPRETER, SCRIPT, *backend.ARGS, '--reload']),
    dict(ppid=['7']),
    dict(uid=['0', '0']),
    dict(others=[12]),                              # segundo processo (worker, shell)
])
def test_pid1_rejects_init_other_command_or_extra_process(change):
    assert not backend.pid1_ok(dict(PID1, **change), INTERPRETER, SCRIPT)


def _tcp(listening=True, **conn):
    base = dict(remote=PEER, st='01', tx=0, rx=0, owned=True)
    base.update(conn)
    return dict(listen=[dict(owned=True)] if listening else [], conns=[base], orphans=1, tcp6=0)


def test_tcp_held_before_and_after_signal():
    assert backend.tcp_held(_tcp(), PEER, listening=True)
    assert backend.tcp_held(_tcp(listening=False), PEER, listening=False)
    assert backend.tcp_held(_tcp(listening=False), PEER, listening=None)
    assert backend.tcp_held(_tcp(), PEER, listening=None)


@pytest.mark.parametrize('snapshot, listening', [
    (_tcp(rx=12), True),                            # bytes ainda não lidos pelo uvicorn
    (_tcp(tx=5), True),                             # resposta já em envio
    (_tcp(owned=False), True),                      # socket não pertence ao PID 1
    (_tcp(st='08'), True),                          # CLOSE_WAIT: cliente fechou
    (_tcp(remote=f'{PROBE_IP}:1'), True),           # outra conexão
    (_tcp(listening=False), True),                  # listener ausente antes do sinal
    (_tcp(), False),                                # listener ainda aberto durante a drenagem
    (dict(_tcp(), tcp6=1), True),
    (dict(_tcp(), conns=[]), None),
    (dict(_tcp(), conns=_tcp()['conns'] * 2), None),
    (dict(_tcp(), listen=[dict(owned=False)]), True),
])
def test_tcp_held_rejects_anything_but_the_single_held_connection(snapshot, listening):
    assert not backend.tcp_held(snapshot, PEER, listening=listening)


def _ready(**fields):
    return json.dumps(dict(dict(ip=PROBE_IP, port=PROBE_PORT, outq=0), **fields))


def test_stream_peer_requires_client_ack_outq_exactly_int_zero():
    assert backend.stream_peer(_ready(), PROBE_IP) == PEER


@pytest.mark.parametrize('raw', [
    json.dumps(dict(ip=PROBE_IP, port=PROBE_PORT)),   # sem campo
    _ready(outq=1), _ready(outq=-1), _ready(outq='0'), _ready(outq=False), _ready(outq=0.0), _ready(outq=None),
    'nao-json', '', '[]',
])
def test_stream_peer_refuses_ready_without_exact_ack(raw):
    with pytest.raises(containment.Refused, match='stream-not-acked'):
        backend.stream_peer(raw, PROBE_IP)


@pytest.mark.parametrize('raw', [_ready(ip='172.30.0.9'), _ready(port=0), _ready(port='41000'), _ready(port=True)])
def test_stream_peer_refuses_other_peer(raw):
    with pytest.raises(containment.Refused, match='stream-peer'):
        backend.stream_peer(raw, PROBE_IP)


GOOD_RESPONSE = dict(early=None, status=202, body={'status': 'queued'}, eof=True, length_ok=True, chunked=False,
                     connection=None)


def test_response_must_be_202_queued_and_closed_by_server():
    assert backend.response_ok(GOOD_RESPONSE)
    for change in (dict(status=503), dict(body={'status': 'other'}), dict(eof=False), dict(length_ok=False),
                   dict(chunked=True), dict(early='eof'), dict(early='data')):
        assert not backend.response_ok(dict(GOOD_RESPONSE, **change))


def test_envelope_is_single_real_enqueue_of_fictitious_payload():
    assert backend.envelope_ok([ENVELOPE])
    assert not backend.envelope_ok([ENVELOPE, ENVELOPE])
    assert not backend.envelope_ok([])
    assert not backend.envelope_ok(['not-json'])
    for change in (dict(attempts=1), dict(attempts=False), dict(claim_id='x'), dict(payload={'event': 'outro'}),
                   dict(retry_at=1.0)):
        data = dict(json.loads(ENVELOPE), **change)
        assert not backend.envelope_ok([json.dumps(data)])


# -- logs -------------------------------------------------------------------
UV = {marker: message for message, marker in backend.UVICORN_MARKERS.items()}
APP = {marker: key for key, marker in backend.APP_MARKERS.items()}


def _line(marker, duration):
    if marker.startswith('request '):
        method, route, status = marker.split()[1:]
        message = (f'http_request request_id={"a" * 32} method={method} route={route} status={status} '
                   f'duration_ms={duration if status == "202" else "1.00"} release=')
        return f'2026-10-25 12:00:00,000 INFO pastorai {message}'
    if marker in APP:
        level, name, message = APP[marker]
        return f'2026-10-25 12:00:00,000 {level} {name} {message}'
    return f'INFO:     {UV[marker]}'


def _logs(stage='final', duration='5000.00', extra_err=(), extra_out=()):
    sequence, access = backend.STAGES[stage]
    stderr = [_line(marker, duration) for marker in sequence] + list(extra_err)
    stdout = [f'INFO:     {PROBE_IP}:4000{i} - "{key.split()[0]} {key.split()[1]} HTTP/1.1" {key.split()[2]} OK'
              for key, count in access.items() for i in range(count)] + list(extra_out)
    return '\n'.join(stdout) + '\n', '\n'.join(stderr) + '\n'


def test_log_summary_of_expected_runs():
    for stage in backend.STAGES:
        summary = backend.log_summary(*_logs(stage))
        assert backend.stage_ok(summary, stage), stage
    final = backend.log_summary(*_logs())
    assert final['inflight_duration_ms'] == [5000.0] and final['token_hits'] == 0
    # INFO de telemetria da app fica fora da sequência; "background tasks" só depois da drenagem
    noisy = _logs(extra_err=['2026-10-25 12:00:00,000 INFO pastorai performance_histogram x=1',
                             f'INFO:     {backend.WAITING_TASKS}'])
    assert backend.stage_ok(backend.log_summary(*noisy), 'final')


def _swap(sequence, a, b):
    sequence = list(sequence)
    i, j = sequence.index(a), sequence.index(b)
    sequence[i], sequence[j] = sequence[j], sequence[i]
    return sequence


@pytest.mark.parametrize('stage, logs', [
    ('final', _logs(extra_err=['2026-10-25 12:00:00,000 WARNING pastorai Outro aviso'])),
    ('final', _logs(extra_err=['2026-10-25 12:00:00,000 ERROR pastorai Unhandled request error'])),
    ('final', _logs(extra_err=['Traceback (most recent call last):'])),
    ('final', _logs(extra_err=['WARNING:  Invalid HTTP request received.'])),
    ('final', _logs(extra_err=['INFO:     Started reloader process [1]'])),
    ('final', _logs(extra_err=[f'2026-10-25 12:00:00,000 INFO pastorai token={backend.WEBHOOK_TOKEN}'])),
    ('final', _logs(extra_out=[f'INFO:     {PROBE_IP}:1 - "POST /whatsapp/webhook?token=x HTTP/1.1" 202 Accepted'])),
    ('final', _logs(extra_out=['qualquer coisa'])),
    ('final', _logs(extra_err=[_line('request ' + backend.ACCEPT_REQ, '1.00')])),   # segundo 202
    ('draining', _logs('draining', extra_err=[f'INFO:     {backend.WAITING_TASKS}'])),
    ('draining', _logs('stopped')),                                                 # lifespan já encerrou
])
def test_log_summary_rejects_unexpected_lines(stage, logs):
    assert not backend.stage_ok(backend.log_summary(*logs), stage)


@pytest.mark.parametrize('a, b', [
    ('waiting-connections', 'request ' + backend.ACCEPT_REQ),     # 202 antes de esperar conexões
    ('shutting-down', 'request ' + backend.REJECT_REQ),
    ('request ' + backend.ACCEPT_REQ, 'shutdown'),                # lifespan antes da resposta
    ('db-disposed', 'shutdown-complete'),
])
def test_stderr_order_is_exact(a, b, monkeypatch):
    sequence = _swap(backend.FIRST_RUN, a, b)
    stderr = '\n'.join(_line(m, '5000.00') for m in sequence) + '\n'
    stdout = _logs('stopped')[0]
    assert not backend.stage_ok(backend.log_summary(stdout, stderr), 'stopped')


def test_missing_lifespan_close_is_rejected():
    sequence = [m for m in backend.FIRST_RUN if m != 'db-disposed']
    stderr = '\n'.join(_line(m, '5000.00') for m in sequence) + '\n'
    assert not backend.stage_ok(backend.log_summary(_logs('stopped')[0], stderr), 'stopped')


# -- configuração e probes ----------------------------------------------------
def test_body_split_has_full_length_but_incomplete_json():
    assert backend.FIRST + backend.REST == backend.BODY and backend.FIRST and backend.REST
    assert json.loads(backend.BODY) == backend.IGNORED_PAYLOAD
    with pytest.raises(ValueError):
        json.loads(backend.FIRST)


def test_probes_compile_use_header_token_and_never_import_the_app():
    for code in (backend.UVICORN_PROBE, backend.HTTP_PROBE, backend.STREAM_PROBE, backend.PID_PROBE,
                 backend.TCP_PROBE):
        compile(code, '<probe>', 'exec')
        assert 'import app' not in code and 'from app' not in code
    assert 'X-Webhook-Token' in backend.STREAM_PROBE and 'X-Webhook-Token' in backend.HTTP_PROBE
    assert '?' not in backend.WEBHOOK_PATH and 'token=' not in backend.STREAM_PROBE
    assert 'Content-Length: %d' in backend.STREAM_PROBE and 'len(first) + len(rest)' in backend.STREAM_PROBE
    for code in (backend.PID_PROBE, backend.TCP_PROBE):
        assert 'kill' not in code and 'signal' not in code and 'open(' in code


def test_backend_env_has_closed_gates_dead_db_and_fictitious_secret():
    env = backend.BACKEND_ENV
    assert env['ALLOW_REAL_SENDS'] == 'false' and env['ASAAS_BILLING_ENABLED'] == 'false'
    assert env['BREVO_SEND_MODE'] == 'off' and env['BROADCAST_ASYNC_ENABLED'] == 'false'
    assert env['WHATSAPP_PILOTO_IGREJA_IDS'] == '' and env['APP_ENV'] != 'production'
    assert '127.0.0.1:9' in env['DATABASE_URL'] and env['EVOLUTION_API_URL'] == 'http://127.0.0.1:9'
    assert env['EVOLUTION_WEBHOOK_SECRET'] == backend.WEBHOOK_TOKEN != backend.WRONG_TOKEN
    assert backend.PROBE_ENV == {'REDIS_URL': env['REDIS_URL']}
    assert backend.HOLD_S < backend.HOLD_BUDGET_S and backend.EXIT_BUDGET_S == backend.GRACE_S


def test_backend_argv_is_real_uvicorn_pid1_hardened_without_host_exposure():
    rehearsal = _rehearsal()
    rehearsal.network = 'e' * 64
    args = rehearsal.backend_argv()
    assert args[-6:] == [LEGACY, 'app.main:app', '--host', '0.0.0.0', '--port', '8000']
    assert '--init=false' in args and args[args.index('--entrypoint') + 1] == 'uvicorn'
    assert args[args.index('--pull') + 1] == 'never' and args[args.index('--restart') + 1] == 'no'
    assert args[args.index('--network-alias') + 1] == 'backend' and '--read-only' in args
    assert args[args.index('--workdir') + 1] == backend.SOURCE_ROOT
    assert f'{containment.ROLE_LABEL}=backend' in args
    assert f'EVOLUTION_WEBHOOK_SECRET={backend.WEBHOOK_TOKEN}' in args and 'ALLOW_REAL_SENDS=false' in args
    assert not {'-p', '--publish', '-P', '--publish-all', '-v', '--volume', '--mount', '--privileged',
                '--init'} & set(args)
    assert args[args.index('--name') + 1].startswith('pastorai-synthetic-legacy-backend-')


def test_source_without_main_is_refused_before_docker():
    calls = []
    with pytest.raises(containment.Refused, match='source-incomplete'):
        _rehearsal(calls.append, files={k: v for k, v in FILES.items() if k != 'app/main.py'})
    assert calls == []


def test_remote_docker_refused_before_any_resource(monkeypatch):
    calls = []
    monkeypatch.setenv('DOCKER_HOST', 'tcp://203.0.113.1:2376')
    rehearsal = _rehearsal(lambda argv: calls.append(argv) or '')
    with pytest.raises(containment.Refused, match='remote-docker'):
        rehearsal.preflight()
    assert not any(argv[1] in ('run', 'network') for argv in calls)


# -- check_backend com inspect falso ------------------------------------------
RUN_ID = '1' * 32
NET, REDIS_ID, BACKEND_ID, STREAM_ID = 'e' * 64, '2' * 64, '3' * 64, '4' * 64


class Inspect:
    def __init__(self, rehearsal):
        self.r = rehearsal
        prefix = rehearsal.prefix
        common = lambda role, image, ident: dict(  # noqa: E731
            Id=ident, Image=image, RestartCount=0,
            HostConfig=dict(NetworkMode=NET, ReadonlyRootfs=True, Init=False),
            NetworkSettings=dict(Ports={}, Networks={prefix: dict(Aliases=['backend'], IPAddress='x')}),
            State=dict(Running=True), Mounts=[],
            Config=dict(Labels={containment.OWNER_LABEL: RUN_ID, containment.ROLE_LABEL: role,
                                containment.SCOPE_LABEL: containment.SCOPE}, User=containment.USER))
        self.data = {
            REDIS_ID: common('redis', REDIS, REDIS_ID),
            BACKEND_ID: common('backend', LEGACY, BACKEND_ID),
            STREAM_ID: common('stream-probe', LEGACY, STREAM_ID),
        }
        self.data[REDIS_ID]['Config'].update(Entrypoint=['redis-server'])
        env = [f'{k}={v}' for k, v in {'PATH': '/usr/bin', **backend.BACKEND_ENV}.items()]
        self.data[BACKEND_ID].update(Path='uvicorn', Args=list(backend.ARGS))
        self.data[BACKEND_ID]['Config'].update(Entrypoint=['uvicorn'], Cmd=list(backend.ARGS), Env=env,
                                               WorkingDir=backend.SOURCE_ROOT)
        self.data[STREAM_ID].update(Path='python', Args=rehearsal.stream_args())
        self.data[STREAM_ID]['Config'].update(Entrypoint=['python'],
                                              Env=['PATH=/usr/bin', f"REDIS_URL={backend.PROBE_ENV['REDIS_URL']}"])
        self.owned = {REDIS_ID, BACKEND_ID, STREAM_ID}
        self.attached = {REDIS_ID, BACKEND_ID, STREAM_ID}

    def __call__(self, argv):
        args = argv[1:]
        if args[:2] == ['context', 'inspect']:
            return json.dumps([{'Endpoints': {'docker': {'Host': 'unix:///var/run/docker.sock'}}}])
        if args[0] == 'ps':
            return '\n'.join(sorted(self.owned))
        if args[:2] == ['network', 'inspect']:
            return json.dumps([dict(Internal=True, Labels={containment.OWNER_LABEL: RUN_ID,
                                                           containment.SCOPE_LABEL: containment.SCOPE},
                                    Containers={i: {} for i in self.attached})])
        if args[0] == 'inspect':
            return json.dumps([self.data[args[1]]])
        raise AssertionError(argv)


def _checked():
    rehearsal = _rehearsal(run_id=RUN_ID)
    fake = Inspect(rehearsal)
    rehearsal.runner = fake
    rehearsal.network, rehearsal.image_env = NET, {'PATH'}
    rehearsal.ids.update(redis=REDIS_ID, backend=BACKEND_ID, **{'stream-probe': STREAM_ID})
    rehearsal.created['containers'] += [REDIS_ID, BACKEND_ID, STREAM_ID]
    return rehearsal, fake


def test_check_backend_accepts_exact_set():
    rehearsal, _ = _checked()
    rehearsal.check_backend(running=True, stream=True)


@pytest.mark.parametrize('mutate, code', [
    (lambda f: f.data[BACKEND_ID]['HostConfig'].update(Init=None), 'init'),
    (lambda f: f.data[BACKEND_ID]['HostConfig'].update(Init=True), 'init'),
    (lambda f: f.data[BACKEND_ID].update(Path='python', Args=['-m', 'uvicorn', *backend.ARGS]), 'entrypoint'),
    (lambda f: f.data[BACKEND_ID]['Config'].update(Cmd=[*backend.ARGS, '--workers', '2']), 'entrypoint'),
    (lambda f: f.data[BACKEND_ID]['Config']['Env'].append('ALLOW_REAL_SENDS=true'), 'gate-config-changed'),
    (lambda f: f.data[BACKEND_ID]['Config']['Env'].append('EXTRA=1'), 'gate-config-changed'),
    (lambda f: f.data[BACKEND_ID]['HostConfig'].update(PortBindings={'8000/tcp': [{}]}), 'host-exposure'),
    (lambda f: f.data[BACKEND_ID].update(Mounts=[{'Type': 'bind'}]), 'host-exposure'),
    (lambda f: f.data[BACKEND_ID]['NetworkSettings']['Networks'][f.r.prefix].update(Aliases=[]), 'network'),
    (lambda f: f.data[STREAM_ID]['Config']['Env'].append('EVOLUTION_WEBHOOK_SECRET=x'), 'probe-config'),
    (lambda f: f.data[STREAM_ID].update(Args=['-c', 'outro']), 'entrypoint'),
    (lambda f: f.owned.add('5' * 64), 'unexpected-container'),
    (lambda f: f.attached.add('5' * 64), 'unexpected-container'),
])
def test_check_backend_refuses_any_deviation(mutate, code):
    rehearsal, fake = _checked()
    mutate(fake)
    with pytest.raises(containment.Refused, match=code):
        rehearsal.check_backend(running=True, stream=True)


# -- roteiro com mundo falso -----------------------------------------------
class World(backend.BackendRehearsal):
    """Substitui só as primitivas de Docker/Redis/proc/logs; o roteiro ``rehearse`` é o real."""

    def __init__(self, **faults):
        super().__init__(legacy_image=LEGACY, redis_image=REDIS, files=FILES, runner=self._no_docker,
                         sleep=lambda _: None)
        self.faults, self.events, self.now = faults, [], 0.0
        self.run = 0
        self.streamed = self.signalled = self.released = self.exited = self.deleted = False
        self.drain_calls = 0
        self.clock = self._tick
        self.uvicorn = dict(interpreter=INTERPRETER, script=SCRIPT)
        self.ids['redis'] = 'redis-id'

    def _no_docker(self, argv):
        raise AssertionError(argv)

    def _tick(self):
        self.now += 0.05
        return self.now

    def fault(self, name):
        return self.faults.get(name) and self.signalled and not self.released

    # primitivas
    def preflight(self):
        self.events.append('preflight')

    def create_support(self):
        self.phase = 'running'

    def start_backend(self):
        self.ids['backend'], self.run = 'backend-id', 1
        self.events.append('start')

    def http_probe(self, mode, *args):
        if mode == 'health':
            self.events.append('health')
            return dict(backend.HEALTHY)
        if mode == 'post':
            assert args == (backend.WEBHOOK_PATH, backend.WRONG_TOKEN, backend.BODY.hex())
            self.events.append('reject')
            self.rejected = True
            return dict(backend.REJECTED)
        assert mode == 'connect' and args == (BACKEND_IP,) and self.signalled
        self.events.append('connect')
        return {'connect': 'accepted' if self.fault('accepts') else 'refused'}

    def ip(self, identifier):
        return {'backend-id': BACKEND_IP, 'stream-id': PROBE_IP}[identifier]

    def spawn_stream(self):
        self.ids['stream-probe'] = 'stream-id'
        self.streamed = True
        self.events.append('stream')
        return 'stream-id'

    def running(self, role='backend'):
        if role == 'stream-probe':
            return not self.released and not self.fault('stream_closed')
        return not self.exited and not self.fault('dies')

    def keys(self):
        if not self.streamed:
            return set()
        if not self.released:
            return {backend.READY_KEY, backend.QUEUE} if self.fault('enqueued') else {backend.READY_KEY}
        return {backend.QUEUE} if self.deleted else {backend.READY_KEY, backend.RELEASE_KEY, backend.QUEUE}

    def queue_items(self):
        if self.faults.get('duplicate'):
            return [ENVELOPE, ENVELOPE]
        if self.run == 2 and self.faults.get('restart_changes'):
            return [ENVELOPE.replace('c' * 32, 'd' * 32)]
        return [ENVELOPE]

    def redis(self, *args):
        if args == ('GET', backend.READY_KEY):
            return self.faults.get('ready', json.dumps({'ip': PROBE_IP, 'port': PROBE_PORT, 'outq': 0}))
        if args == ('SET', backend.RELEASE_KEY, '1'):
            self.released, self.released_at = True, self.now
            self.events.append('release')
            return 'OK'
        if args == ('DEL', backend.READY_KEY, backend.RELEASE_KEY):
            self.deleted = True
            return '2'
        raise AssertionError(args)

    def tcp(self):
        listening = not self.signalled or self.fault('listener')
        conns = [] if self.fault('tcp_lost') else [dict(remote=PEER, st='01', tx=0, rx=0, owned=True)]
        return dict(listen=[dict(owned=True)] if listening else [], conns=conns, orphans=0, tcp6=0)

    def summary(self):
        if self.run == 2:
            stage = 'final' if self.exited else 'restarted'
        elif self.exited:
            stage = 'stopped'
        elif self.signalled:
            self.drain_calls += 1
            stage = 'signalled' if self.drain_calls == 1 or self.faults.get('no_drain') else 'draining'
            if self.fault('slow') and self.drain_calls == 2:
                self.now += backend.HOLD_BUDGET_S
            if self.fault('lifespan_early') and self.drain_calls > 3:
                stage = 'stopped'
        elif getattr(self, 'rejected', False):
            stage = 'rejected'
        else:
            stage = 'ready'
        stdout, stderr = _logs(stage, duration=self._duration())
        return backend.log_summary(stdout, stderr)

    def _duration(self):
        if not self.released:
            return '1.00'
        if self.faults.get('short_duration'):
            return '10.00'
        return '%.2f' % ((self.released_at - self.signalled_at) * 1000 + 100)

    def check_backend(self, *, running, stream=False):
        assert running == (not self.exited) and stream == (self.streamed and not self.released)
        if self.signalled and stream and (advance := self.faults.get('final_check_advance')):
            self.now += advance
        if self.signalled and stream and (elapsed := self.faults.get('final_elapsed')) is not None:
            # ``signalled`` do roteiro é signalled_at + 1 tick; o próximo clock() mede exatamente ``elapsed``
            self.now = self.signalled_at + elapsed

    def pid1(self):
        self.events.append('pid1')

    def docker(self, *args):
        if args == ('kill', '--signal', 'SIGTERM', 'backend-id'):
            assert not self.exited
            if not self.signalled:  # o request retido só existe no primeiro ciclo
                self.signalled_at = self.now
            self.signalled = True
            self.events.append('sigterm')
            return ''
        assert args == ('start', 'backend-id') and self.exited
        self.run, self.exited = 2, False
        self.events.append('restart')
        return ''

    def collect(self, identifier, timeout, refusal):
        assert identifier == 'stream-id' and self.released
        return json.dumps(dict(GOOD_RESPONSE, **self.faults.get('response', {})))

    def _await_exit(self, role, grace_s):
        assert role == 'backend' and (self.released or self.run == 2) and grace_s == backend.EXIT_BUDGET_S
        self.exited = True
        self.events.append('exit')


def test_script_holds_inflight_request_through_sigterm_then_releases_on_same_connection():
    world = World()
    backend.rehearse(world)
    assert world.events == ['preflight', 'start', 'health', 'pid1', 'reject', 'stream', 'pid1', 'sigterm',
                            'connect', 'connect', 'pid1', 'release', 'exit', 'restart', 'health', 'pid1',
                            'sigterm', 'exit']
    assert world.checks[-1].startswith('queue-bytes-preserved-after-stop-and-restart')
    assert backend.stage_ok(world.log, 'final') and backend.stage_ok(world.log_first_stop, 'stopped')
    assert world.timings['held_after_sigterm_s'] < backend.HOLD_BUDGET_S


@pytest.mark.parametrize('fault, code', [
    ('dies', 'backend-exited-while-held'),
    ('stream_closed', 'inflight-closed-before-release'),
    ('enqueued', 'queue-before-release'),
    ('tcp_lost', 'drain-not-observed'),
    ('listener', 'barrier-lost'),
    ('accepts', 'new-connection-accepted-while-draining'),
    ('no_drain', 'drain-not-observed'),
    ('lifespan_early', 'backend-log-while-held'),
    ('slow', 'hold-too-long'),
])
def test_script_never_releases_when_the_held_state_is_not_proven(fault, code):
    world = World(**{fault: True})
    with pytest.raises(containment.Refused, match=code):
        backend.rehearse(world)
    assert 'sigterm' in world.events and 'release' not in world.events and not world.exited


@pytest.mark.parametrize('ready', [_ready(outq=3), json.dumps(dict(ip=PROBE_IP, port=PROBE_PORT))])
def test_script_refuses_unacked_stream_before_any_signal(ready):
    world = World(ready=ready)
    with pytest.raises(containment.Refused, match='stream-not-acked'):
        backend.rehearse(world)
    assert 'stream' in world.events and 'sigterm' not in world.events and 'release' not in world.events


def test_final_check_that_consumes_the_budget_refuses_without_release():
    world = World(final_check_advance=backend.HOLD_BUDGET_S)
    with pytest.raises(containment.Refused, match='hold-too-long'):
        backend.rehearse(world)
    assert 'release' not in world.events and not world.exited


@pytest.mark.parametrize('offset, released', [(-0.0004, True), (0.0004, False)])
def test_hold_budget_decision_uses_unrounded_elapsed_time(offset, released):
    world = World(final_elapsed=backend.HOLD_BUDGET_S + offset)
    if released:
        backend.rehearse(world)
        assert 'release' in world.events
    else:
        with pytest.raises(containment.Refused, match='hold-too-long'):
            backend.rehearse(world)
        assert 'release' not in world.events
    assert world.timings['held_after_sigterm_s'] == backend.HOLD_BUDGET_S


@pytest.mark.parametrize('faults, code', [
    (dict(response=dict(status=503)), 'inflight-response'),
    (dict(response=dict(eof=False)), 'inflight-response'),        # conexão reaproveitável
    (dict(duplicate=True), 'enqueue-envelope'),
    (dict(short_duration=True), 'inflight-duration-inconsistent'),
    (dict(restart_changes=True), 'queue-changed-by-restart'),
])
def test_script_refuses_wrong_outcome_after_release(faults, code):
    world = World(**faults)
    with pytest.raises(containment.Refused, match=code):
        backend.rehearse(world)
    assert 'release' in world.events


def test_report_is_written_with_production_ready_false_on_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'legacy_sources', lambda repo: {k: v for k, v in FILES.items()
                                                                  if k != 'app/main.py'})
    report = tmp_path / 'report.json'
    assert backend.main(['run', '--repo', str(tmp_path), '--report', str(report)]) == 1
    data = json.loads(report.read_text())
    assert data['status'] == 'refused' and data['reason'] == 'source-incomplete'
    assert data['production_ready'] is False and data['legacy_sha'] == backend.LEGACY_SHA
    assert data['entrypoint'] == 'uvicorn app.main:app --host 0.0.0.0 --port 8000'
    assert any('readiness' in item for item in data['not_proven'])
