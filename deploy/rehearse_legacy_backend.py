#!/usr/bin/env python3
"""Ensaio sintético LOCAL: SIGTERM no backend ASGI legado real com HTTP em curso.

``run --repo R --report P [--legacy-image/--redis-image sha256:...]``

Reusa ``rehearse_legacy_queue`` (fonte Git exata de ``07a3f4d``, runtime do
lock, guarda de Docker local, ledger, Redis próprio em rede ``--internal`` sem
portas/montagens e limpeza por posse). O PID 1 do backend é o console script
real ``uvicorn app.main:app --host 0.0.0.0 --port 8000`` (``--init=false``),
sem patch, mock, rota ou instrumentação da aplicação; o preflight confere o
script contra o RECORD da distribuição ``uvicorn`` e as premissas de shutdown
do Uvicorn instalado. Gates fechados, segredo do webhook fictício, banco em
loopback morto (só o aviso de warmup é esperado; ``/health`` 200 não é
readiness) e nenhum consumidor da fila.

Barreira HTTP real: um probe separado (mesma imagem, só stdlib + redis-py)
abre o socket, envia ``POST /whatsapp/webhook`` com ``Content-Length`` do corpo
inteiro, ``X-Webhook-Token`` (header, nunca query) e só a primeira metade do
JSON, e só publica o READY depois do ACK do kernel do servidor (``TIOCOUTQ``
= 0, sem ``recv``). O handler legado lê o corpo inteiro antes de autenticar.
Antes do SIGTERM, pelo ``/proc`` do container do backend (``docker exec`` só
leitura), a conexão do IP/porta do probe está ESTABLISHED, pertence ao PID 1
e tem ``Recv-Q``/``Send-Q`` zero: bytes confirmados e lidos pelo processo, sem
resposta; a fila está vazia. Isso, mais a conexão retida durante a drenagem,
sustenta um ciclo HTTP aberto, não a linha exata do handler. Depois do
SIGTERM: backend vivo, log do Uvicorn esperando conexões, listener fechado,
conexão nova recusada, a mesma conexão retida e o lifespan ainda não
encerrado. Só então o restante do corpo é liberado na conexão existente →
202 ``{"status":"queued"}``, conexão encerrada pelo servidor, evento uma vez
no ``WebhookQueue`` real, lifespan fechando os pools, saída 0, bytes da fila
preservados depois da parada e de um reinício sem consumidor.

``production_ready=false``: não prova consumo pelo worker, turno do agente,
RLS, supervisor/topologia viva, pós-DDL nem produção.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from rehearse_legacy_containment import OWNER_LABEL, SCOPE, SCOPE_LABEL, USER, Refused
from rehearse_legacy_cron_active import LOG_LINE
from rehearse_legacy_queue import (
    GRACE_S, IGNORED_PAYLOAD, LEGACY_SHA, QUEUE, READY_S, SOURCE_ROOT, SURVIVE_S, SYNTHETIC_ENV, QueueRehearsal,
    legacy_sources, manifest, manifest_digest,
)
from rehearse_legacy_queue_active import DEFAULT_IMAGES, PROBE_S, ActiveRehearsal

ROLE = 'backend'
STREAM = 'stream-probe'
PORT = 8000
# CMD do backend/Dockerfile de 07a3f4d, executado pelo mesmo console script.
ENTRYPOINT = 'uvicorn'
ARGS = ['app.main:app', '--host', '0.0.0.0', '--port', str(PORT)]
REQUIRED = frozenset({'app/main.py', 'app/config.py', 'app/routers/whatsapp.py', 'app/workers/queue_worker.py'})
UVICORN_VERSION = '0.49.0'
UVICORN_EXPECTED = dict(version=UVICORN_VERSION, entry_points=[['uvicorn', 'uvicorn.main:main']], record_ok=True,
                        http='HttpToolsProtocol', uvloop=True, keeps_inflight=True, waits_connections=True)
ABS_PATH = re.compile(r'/[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*')
# -- configuração sintética -------------------------------------------------
WEBHOOK_PATH = '/whatsapp/webhook'
WEBHOOK_TOKEN = 'synthetic-webhook-token-not-a-secret'
WRONG_TOKEN = 'synthetic-wrong-token-not-a-secret'
BACKEND_ENV = {**SYNTHETIC_ENV, 'EVOLUTION_WEBHOOK_SECRET': WEBHOOK_TOKEN}
PROBE_ENV = {'REDIS_URL': SYNTHETIC_ENV['REDIS_URL']}
BODY = json.dumps(IGNORED_PAYLOAD, separators=(',', ':'), sort_keys=True).encode('ascii')
FIRST, REST = BODY[:len(BODY) // 2], BODY[len(BODY) // 2:]
READY_KEY = 'synthetic:backend:stream-ready'
RELEASE_KEY = 'synthetic:backend:release'
REJECTED = dict(status=401, body={'detail': 'Assinatura do webhook inválida'})
HEALTHY = dict(status=200, body={'status': 'ok'})
CLAIM = re.compile(r'[0-9a-f]{32}')
# -- prazos ---------------------------------------------------------------
BARRIER_S = 20       # do start do probe à prova TCP no lado do servidor
DRAIN_LOG_S = 10     # do SIGTERM ao log "Waiting for connections to close"
HOLD_S = 3           # janela observada com o request retido depois do sinal
HOLD_BUDGET_S = 20   # SIGTERM → liberação, medido depois do último check
EXIT_BUDGET_S = GRACE_S  # liberação → saída; sem SIGKILL em nenhum caminho de sucesso
COMMAND_EQUIVALENCE = dict(
    dockerfile_cmd=['uvicorn', *ARGS], executed=[ENTRYPOINT, *ARGS],
    console_script='uvicorn do PATH da imagem, conferido contra RECORD e entry point uvicorn.main:main',
    differences=['workdir /opt/legacy em vez de /app (app-dir "." do uvicorn poe o workdir no sys.path)',
                 'usuario 65534 em vez de appuser 10001', 'rootfs read-only com /tmp tmpfs',
                 'sem backend/migrations na imagem', 'sem healthcheck do Compose',
                 '--init=false explicito (PID 1 direto)'],
)
NOT_PROVEN = [
    'posicao-interna-do-handler-em-request.stream (ACK do cliente, Recv-Q 0 no servidor e conexao retida '
    'durante a drenagem sustentam ciclo HTTP aberto, nao a linha exata do handler)',
    'inicio-do-asgi-antes-do-sigterm (inferido do ciclo aberto; a duracao da telemetria e so consistencia)',
    'consumo-pelo-queue-worker (nenhum consumidor; ver ensaios queue/active)',
    'turno-completo-do-agente',
    'banco-e-rls (DATABASE_URL em loopback morto; /health 200 nao e readiness nem /ready)',
    'retries-da-evolution-e-provedor-real',
    'supervisor-restart-policy-compose-e-reinicio-do-host',
    'topologia-atual-de-producao (proxy, init, timeouts e stop_grace vivos)',
    'exit-0-sob-init (o uvicorn re-levanta o SIGTERM; so PID 1 direto o ignora)',
    'cliente-que-nunca-completa-o-corpo (sem timeout-graceful-shutdown o uvicorn espera indefinidamente)',
    'sigkill-ou-timeout-gracioso',
    'compatibilidade-pos-ddl',
    'integridade-de-wheels-sitecustomize-e-pth (so nome/versao e o script uvicorn conferidos)',
    'producao',
]

# -- probes (imagem legada; nada montado do host, nenhum import de app) -----
UVICORN_PROBE = r'''
import base64, hashlib, importlib.util, inspect, json, os, shutil
from importlib import metadata
dist = metadata.distribution('uvicorn')
script = shutil.which('uvicorn')
real = os.path.realpath(script) if script else None
record = None
for item in dist.files or []:
    if item.hash and real and os.path.realpath(item.locate()) == real:
        record = item.hash
data = b''
if real and os.path.isfile(real):
    with open(real, 'rb') as handle:
        data = handle.read()
ok = bool(record) and base64.urlsafe_b64encode(
    hashlib.new(record.mode, data).digest()).rstrip(b'=').decode() == record.value
first = data.split(b'\n', 1)[0].decode('utf-8', 'replace')
from uvicorn import server
from uvicorn.protocols.http import httptools_impl
from uvicorn.protocols.http.auto import AutoHTTPProtocol
print(json.dumps(dict(
    version=dist.version, script=script, record_ok=ok,
    entry_points=[[e.name, e.value] for e in dist.entry_points if e.group == 'console_scripts'],
    interpreter=first[2:].strip() if first.startswith('#!') else None,
    http=AutoHTTPProtocol.__name__, uvloop=importlib.util.find_spec('uvloop') is not None,
    keeps_inflight='keep_alive = False' in inspect.getsource(httptools_impl.HttpToolsProtocol.shutdown),
    waits_connections='Waiting for connections to close' in inspect.getsource(server.Server),
), sort_keys=True))
'''

HTTP_PROBE = r'''
import json, socket, sys, time, urllib.error, urllib.request
mode = sys.argv[1]
def fetch(request):
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
if mode == 'connect':
    try:
        socket.create_connection((sys.argv[2], 8000), timeout=3).close()
        print(json.dumps({'connect': 'accepted'}))
    except ConnectionRefusedError:
        print(json.dumps({'connect': 'refused'}))
    except OSError as exc:
        print(json.dumps({'connect': type(exc).__name__}))
    sys.exit(0)
if mode == 'health':
    limit = time.monotonic() + float(sys.argv[2])
    while True:
        try:
            status, body = fetch(urllib.request.Request('http://backend:8000/health'))
            break
        except OSError:
            if time.monotonic() > limit:
                print(json.dumps({'status': None, 'body': None}))
                sys.exit(0)
            time.sleep(0.2)
else:
    status, body = fetch(urllib.request.Request(
        'http://backend:8000' + sys.argv[2], data=bytes.fromhex(sys.argv[4]), method='POST',
        headers={'Content-Type': 'application/json', 'X-Webhook-Token': sys.argv[3]}))
try:
    parsed = json.loads(body)
except ValueError:
    parsed = None
print(json.dumps({'status': status, 'body': parsed}, sort_keys=True))
'''

# Headers completos + metade do corpo; o restante só depois do comando no Redis.
STREAM_PROBE = r'''
import json, os, select, socket, sys, time
import redis
host, path, token, first, rest, ready, release = sys.argv[1:8]
first, rest = bytes.fromhex(first), bytes.fromhex(rest)
client = redis.Redis.from_url(os.environ['REDIS_URL'], decode_responses=True)
head = ('POST %s HTTP/1.1\r\nHost: backend:8000\r\nContent-Type: application/json\r\n'
        'X-Webhook-Token: %s\r\nContent-Length: %d\r\n\r\n' % (path, token, len(first) + len(rest))).encode('ascii')
sock = socket.create_connection((host, 8000), timeout=5)
sock.sendall(head + first)
# ACK do kernel do servidor antes do READY: TIOCOUTQ (enviado e ainda não confirmado) chega a 0, sem recv.
try:
    import fcntl, struct, termios
    acked = time.monotonic() + 5
    while (outq := struct.unpack('i', fcntl.ioctl(sock.fileno(), termios.TIOCOUTQ, b'\0' * 4))[0]) != 0:
        if time.monotonic() > acked:
            break
        time.sleep(0.01)
except (OSError, AttributeError, ImportError):
    print(json.dumps({'early': 'outq-unavailable'}))
    sys.exit(3)
if outq != 0:
    print(json.dumps({'early': 'not-acked'}))
    sys.exit(3)
ip, port = sock.getsockname()[:2]
client.set(ready, json.dumps({'ip': ip, 'port': port, 'outq': outq}), ex=300)
out = {'early': None}
limit = time.monotonic() + 150
while client.get(release) != '1':
    if select.select([sock], [], [], 0.05)[0]:
        out['early'] = 'data' if sock.recv(65536) else 'eof'
        break
    if time.monotonic() > limit:
        out['early'] = 'timeout'
        break
if out['early']:
    print(json.dumps(out, sort_keys=True))
    sys.exit(3)
sock.sendall(rest)
sock.settimeout(20)
data, eof = b'', False
try:
    while (chunk := sock.recv(65536)):
        data += chunk
    eof = True
except OSError:
    pass
sock.close()
head_raw, _, body = data.partition(b'\r\n\r\n')
lines = head_raw.decode('latin-1').split('\r\n')
fields = {}
for line in lines[1:]:
    name, _, value = line.partition(':')
    fields[name.strip().lower()] = value.strip()
status = lines[0].split(' ')
try:
    parsed = json.loads(body)
except ValueError:
    parsed = None
print(json.dumps({'early': None, 'status': int(status[1]) if len(status) > 1 and status[1].isdigit() else None,
                  'body': parsed, 'eof': eof, 'length_ok': fields.get('content-length') == str(len(body)),
                  'chunked': 'transfer-encoding' in fields, 'connection': fields.get('connection')}, sort_keys=True))
'''

# ``docker exec`` só leitura no backend: processos e sockets, sem sinal nem import de app.
PID_PROBE = r'''
import json, os
def cmdline(pid):
    with open('/proc/%s/cmdline' % pid, 'rb') as handle:
        return [part.decode('utf-8', 'replace') for part in handle.read().split(b'\0') if part]
fields = {}
with open('/proc/1/status') as handle:
    for line in handle:
        name, _, value = line.partition(':')
        fields[name] = value.split()
me = os.getpid()
print(json.dumps({'cmdline': cmdline(1), 'ppid': fields.get('PPid'), 'uid': fields.get('Uid', [])[:2],
                  'others': sorted(int(p) for p in os.listdir('/proc') if p.isdigit() and int(p) not in (1, me))}))
'''

TCP_PROBE = r'''
import json, os, socket, struct, sys
port = int(sys.argv[1])
def endpoint(text):
    ip, _, value = text.partition(':')
    return socket.inet_ntoa(struct.pack('=I', int(ip, 16))), int(value, 16)
owned = set()
for fd in os.listdir('/proc/1/fd'):
    try:
        target = os.readlink('/proc/1/fd/' + fd)
    except OSError:
        continue
    if target.startswith('socket:['):
        owned.add(target[8:-1])
listen, conns, orphans = [], [], 0
with open('/proc/net/tcp') as handle:
    next(handle)
    for line in handle:
        f = line.split()
        (_, lport), (rip, rport), state = endpoint(f[1]), endpoint(f[2]), f[3]
        if lport != port:
            continue
        tx, rx = (int(x, 16) for x in f[4].split(':'))
        if state == '0A':
            listen.append({'owned': f[9] in owned})
        elif f[9] == '0':
            orphans += 1  # TIME_WAIT/FIN_WAIT sem dono: conexões anteriores já encerradas
        else:
            conns.append({'remote': '%s:%d' % (rip, rport), 'st': state, 'tx': tx, 'rx': rx, 'owned': f[9] in owned})
v6 = 0
try:
    with open('/proc/net/tcp6') as handle:
        next(handle)
        v6 = sum(1 for line in handle if int(line.split()[1].rsplit(':', 1)[1], 16) == port)
except FileNotFoundError:
    pass
print(json.dumps({'listen': listen, 'conns': conns, 'orphans': orphans, 'tcp6': v6}, sort_keys=True))
'''


# -- avaliações puras -------------------------------------------------------
def uvicorn_mismatch(observed):
    """Diferenças (só valores públicos) entre o Uvicorn instalado e as premissas do ensaio."""
    problems = {key: observed.get(key) for key, value in UVICORN_EXPECTED.items() if observed.get(key) != value}
    for key in ('script', 'interpreter'):
        value = observed.get(key)
        if not (isinstance(value, str) and ABS_PATH.fullmatch(value)):
            problems[key] = 'invalid'
    return problems


def pid1_ok(observed, interpreter, script):
    """PID 1 é o console script uvicorn com o CMD do Dockerfile, sem init nem outro processo."""
    return observed == dict(cmdline=[interpreter, script, *ARGS], ppid=['0'], uid=[USER.split(':')[0]] * 2, others=[])


def tcp_held(snapshot, peer, *, listening):
    """Só a conexão do probe, do PID 1, ESTABLISHED e sem bytes pendentes; listener conforme a fase."""
    if listening is not None and snapshot.get('listen') != ([dict(owned=True)] if listening else []):
        return False
    return (snapshot.get('tcp6') == 0
            and snapshot.get('conns') == [dict(remote=peer, st='01', tx=0, rx=0, owned=True)])


def stream_peer(raw, probe_ip):
    """``ip:porta`` do probe só com headers + corpo parcial confirmados por ACK (``outq`` int 0 exato)."""
    try:
        ready = json.loads(raw or '{}')
    except ValueError:
        ready = None
    if not isinstance(ready, dict) or type(ready.get('outq')) is not int or ready['outq'] != 0:
        raise Refused('stream-not-acked')
    port = ready.get('port')
    if ready.get('ip') != probe_ip or type(port) is not int or not 0 < port < 65536:
        raise Refused('stream-peer')
    return f'{probe_ip}:{port}'


def response_ok(result):
    """202 com o corpo do legado, tamanho exato e conexão encerrada pelo servidor (sem reuso)."""
    return (result.get('early') is None and result.get('status') == 202 and result.get('body') == {'status': 'queued'}
            and result.get('eof') is True and result.get('length_ok') is True and result.get('chunked') is False)


def envelope_ok(items):
    """Exatamente um envelope do ``WebhookQueue.enqueue`` real com o payload fictício."""
    if len(items) != 1:
        return False
    try:
        data = json.loads(items[0])
    except ValueError:
        return False
    return (isinstance(data, dict) and set(data) == {'payload', 'attempts', 'claim_id'}
            and data['payload'] == IGNORED_PAYLOAD and type(data['attempts']) is int and data['attempts'] == 0
            and isinstance(data['claim_id'], str) and bool(CLAIM.fullmatch(data['claim_id'])))


# -- logs -------------------------------------------------------------------
UVICORN_LINE = re.compile(r'(DEBUG|INFO|WARNING|ERROR|CRITICAL):\s+(.*)')
ACCESS_LINE = re.compile(r'\S+ - "([A-Z]+) (\S+) HTTP/1\.1" (\d{3})(?: [A-Za-z\' -]+)?')
REQUEST_LINE = re.compile(r'http_request request_id=\S+ method=(\S+) route=(\S+) status=(\d{3}) '
                          r'duration_ms=(\d+\.\d+) release=\S*')
UVICORN_MARKERS = {
    'Started server process [1]': 'started',
    'Waiting for application startup.': 'startup',
    'Application startup complete.': 'startup-complete',
    f'Uvicorn running on http://0.0.0.0:{PORT} (Press CTRL+C to quit)': 'listening',
    'Shutting down': 'shutting-down',
    'Waiting for connections to close. (CTRL+C to force quit)': 'waiting-connections',
    'Waiting for application shutdown.': 'shutdown',
    'Application shutdown complete.': 'shutdown-complete',
    'Finished server process [1]': 'finished',
}
WAITING_TASKS = 'Waiting for background tasks to complete. (CTRL+C to force quit)'
# Allowlist exata de mensagens da aplicação; WARNING+ fora dela é recusa.
APP_MARKERS = {
    ('INFO', 'pastorai', f"PastorAI backend starting (env={SYNTHETIC_ENV['APP_ENV']})"): 'app-starting',
    ('WARNING', 'pastorai', 'Database warmup unavailable; startup continuing'): 'warmup-unavailable',
    ('WARNING', 'pastorai.whatsapp', 'Rejected webhook with invalid signature/token'): 'auth-rejected',
    ('INFO', 'pastorai', 'Clerk HTTP connection pool closed'): 'clerk-closed',
    ('INFO', 'pastorai', 'Google HTTP connection pools closed'): 'google-closed',
    ('INFO', 'pastorai', 'Database connection pool disposed'): 'db-disposed',
}
HEALTH_REQ, REJECT_REQ, ACCEPT_REQ = 'GET /health 200', f'POST {WEBHOOK_PATH} 401', f'POST {WEBHOOK_PATH} 202'
BOOT = ['started', 'startup', 'app-starting', 'warmup-unavailable', 'startup-complete', 'listening',
        'request ' + HEALTH_REQ]
CLOSE = ['shutdown', 'clerk-closed', 'google-closed', 'db-disposed', 'shutdown-complete', 'finished']
# Ordem em stderr (Uvicorn e logging da app no mesmo fd); o access log vai para stdout e só é contado.
FIRST_RUN = [*BOOT, 'auth-rejected', 'request ' + REJECT_REQ, 'shutting-down', 'waiting-connections',
             'request ' + ACCEPT_REQ, *CLOSE]
SECOND_RUN = [*BOOT, 'shutting-down', *CLOSE]
HELD = len(BOOT) + 4  # até 'waiting-connections'
_REJECTED_ACCESS = {HEALTH_REQ: 1, REJECT_REQ: 1}
STAGES = dict(
    ready=(FIRST_RUN[:len(BOOT)], {HEALTH_REQ: 1}),
    rejected=(FIRST_RUN[:len(BOOT) + 2], _REJECTED_ACCESS),
    signalled=(FIRST_RUN[:len(BOOT) + 3], _REJECTED_ACCESS),
    draining=(FIRST_RUN[:HELD], _REJECTED_ACCESS),
    stopped=(FIRST_RUN, {**_REJECTED_ACCESS, ACCEPT_REQ: 1}),
    restarted=(FIRST_RUN + BOOT, {HEALTH_REQ: 2, REJECT_REQ: 1, ACCEPT_REQ: 1}),
    final=(FIRST_RUN + SECOND_RUN, {HEALTH_REQ: 2, REJECT_REQ: 1, ACCEPT_REQ: 1}),
)
ZERO_FIELDS = ('problems', 'unparsed', 'uvicorn_other', 'token_hits', 'query_strings')


def log_summary(stdout, stderr):
    """Só marcadores próprios, contagens e a duração do request retido; nenhum texto do log sai daqui."""
    sequence, durations = [], []
    counts = dict.fromkeys(ZERO_FIELDS, 0)
    waiting_tasks = 0
    for line in stderr.splitlines():
        if not line.strip():
            continue
        if (found := LOG_LINE.fullmatch(line)):
            level, name, message = found.groups()
            request = REQUEST_LINE.fullmatch(message)
            if request and (level, name) == ('INFO', 'pastorai'):
                method, route, status, duration = request.groups()
                sequence.append(f'request {method} {route} {status}')
                if f'{method} {route} {status}' == ACCEPT_REQ:
                    durations.append(float(duration))
            elif (level, name, message) in APP_MARKERS:
                sequence.append(APP_MARKERS[level, name, message])
            elif level in ('WARNING', 'ERROR', 'CRITICAL'):
                counts['problems'] += 1
            # demais INFO da app (ex.: performance_histogram): fora da sequência
        elif (found := UVICORN_LINE.fullmatch(line)):
            level, message = found.groups()
            if level != 'INFO':
                counts['problems'] += 1
            elif message == WAITING_TASKS:
                waiting_tasks += 1
            elif message in UVICORN_MARKERS:
                sequence.append(UVICORN_MARKERS[message])
            else:
                counts['uvicorn_other'] += 1
        else:
            counts['unparsed'] += 1  # traceback, warnings.warn, print: incerteza
    access = {}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        found = UVICORN_LINE.fullmatch(line)
        hit = found and found[1] == 'INFO' and ACCESS_LINE.fullmatch(found[2])
        if not hit:
            counts['unparsed'] += 1
            continue
        method, path, status = hit.groups()
        access[f'{method} {path} {status}'] = access.get(f'{method} {path} {status}', 0) + 1
        counts['query_strings'] += '?' in path
    counts['token_hits'] = sum((stdout + stderr).count(token) for token in (WEBHOOK_TOKEN, WRONG_TOKEN))
    return dict(counts, sequence=sequence, access=access, waiting_tasks=waiting_tasks,
                inflight_duration_ms=durations)


def stage_ok(summary, stage):
    """Sequência e contagens exatas da fase; "background tasks" só pode aparecer depois da drenagem."""
    sequence, access = STAGES[stage]
    late = stage in ('stopped', 'restarted', 'final')
    return (summary.get('sequence') == sequence and summary.get('access') == access
            and summary.get('waiting_tasks', 0) <= (1 if late else 0)
            and not any(summary.get(key) for key in ZERO_FIELDS))


def docker_streams(argv):
    """``docker logs`` com stdout e stderr separados (access log em stdout; ordem só em stderr)."""
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        completed = None
    if completed is None or completed.returncode:
        raise Refused('docker-logs')
    return completed.stdout, completed.stderr


# -- ensaio -----------------------------------------------------------------
class BackendRehearsal(QueueRehearsal):
    # Validação comum, coleta de probe e IP vêm do ensaio ativo (sem Postgres aqui).
    _check_common = ActiveRehearsal._check_common
    collect = ActiveRehearsal.collect
    ip = ActiveRehearsal.ip

    def __init__(self, *, files, log_runner=docker_streams, **kwargs):
        if not REQUIRED <= set(files):
            raise Refused('source-incomplete')
        super().__init__(files=files, **kwargs)
        self.prefix = 'pastorai-synthetic-legacy-backend-' + self.run_id[:12]
        self.log_runner = log_runner
        self.uvicorn: dict = {}
        self.timings: dict[str, float] = {}
        self.observed: dict = {}

    # -- preflight e containers -------------------------------------------
    def preflight(self):
        super().preflight()
        observed = json.loads(self.legacy_probe(['-I', '-c', UVICORN_PROBE], network='none', env={},
                                                refusal='uvicorn-probe'))
        problems = uvicorn_mismatch(observed)
        if problems:
            self.mismatch = dict(uvicorn=problems)
            raise Refused('uvicorn-runtime')
        self.uvicorn = {key: observed[key] for key in ('version', 'script', 'interpreter', 'http', 'uvloop')}
        self.checks.append('uvicorn-console-script-matches-record-httptools-shutdown-keeps-inflight')

    def backend_argv(self):
        flags = [part for name, value in sorted(BACKEND_ENV.items()) for part in ('--env', f'{name}={value}')]
        return ['run', '-d', '--pull', 'never', '--restart', 'no', '--init=false', '--network', self.network,
                '--network-alias', ROLE, '--name', f'{self.prefix}-{ROLE}', '--entrypoint', ENTRYPOINT,
                '--user', USER, '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--no-healthcheck', '--pids-limit', '256', '--workdir', SOURCE_ROOT,
                '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m', *self.labels(ROLE), *flags, self.images['worker'], *ARGS]

    def start_backend(self):
        self.ids[ROLE] = self._record('containers', self.docker(*self.backend_argv()))

    def spawn(self, role, python_args, env):
        return self._record('containers', self.docker(*self._legacy_argv(role, self.network, env), *python_args))

    def http_probe(self, *args):
        return json.loads(self.collect(self.spawn('http-probe', ['-I', '-c', HTTP_PROBE, *args], {}),
                                       PROBE_S, 'http-probe'))

    def stream_args(self):
        return ['-I', '-c', STREAM_PROBE, ROLE, WEBHOOK_PATH, WEBHOOK_TOKEN, FIRST.hex(), REST.hex(),
                READY_KEY, RELEASE_KEY]

    def spawn_stream(self):
        self.ids[STREAM] = self.spawn(STREAM, self.stream_args(), PROBE_ENV)
        return self.ids[STREAM]

    def _check_stream(self):
        data = self.inspect(self.ids[STREAM])
        config, _ = self._check_common(data, STREAM, self.images['worker'])
        if (data.get('Path') != 'python' or data.get('Args') != self.stream_args()
                or config.get('Entrypoint') != ['python'] or config.get('User') != USER):
            raise Refused('entrypoint')
        env = dict(item.split('=', 1) for item in config.get('Env') or [] if '=' in item)
        if set(env) != self.image_env | set(PROBE_ENV) or any(env[k] != v for k, v in PROBE_ENV.items()):
            raise Refused('probe-config')
        if not (data.get('State') or {}).get('Running'):
            raise Refused('unexpected-state')

    def check_backend(self, *, running, stream=False):
        """Conjunto exato (Redis, backend e o probe de stream), uvicorn PID 1 sem init, gates e isolamento."""
        self.guard_local()
        expected = {self.ids['redis'], self.ids[ROLE], *([self.ids[STREAM]] if stream else [])}
        owned = set(self.docker('ps', '-aq', '--no-trunc', '--filter', f'label={OWNER_LABEL}={self.run_id}').split())
        if owned != expected:
            raise Refused('unexpected-container')
        self._validate_one('redis', running=True)
        data = self.inspect(self.ids[ROLE])
        config, host = self._check_common(data, ROLE, self.images['worker'])
        if (data.get('Path') != ENTRYPOINT or data.get('Args') != ARGS or config.get('Entrypoint') != [ENTRYPOINT]
                or config.get('Cmd') != ARGS or config.get('User') != USER
                or config.get('WorkingDir') != SOURCE_ROOT):
            raise Refused('entrypoint')
        if host.get('Init') is not False:
            raise Refused('init')
        env = dict(item.split('=', 1) for item in config.get('Env') or [] if '=' in item)
        if set(env) != self.image_env | set(BACKEND_ENV) or any(env[k] != v for k, v in BACKEND_ENV.items()):
            raise Refused('gate-config-changed')
        if bool((data.get('State') or {}).get('Running')) != running:
            raise Refused('unexpected-state')
        if running:
            aliases = ((data.get('NetworkSettings') or {}).get('Networks') or {}).get(self.prefix, {}).get('Aliases')
            if ROLE not in (aliases or []):
                raise Refused('network')
        if stream:
            self._check_stream()
        network = json.loads(self.docker('network', 'inspect', self.network))[0]
        if not network.get('Internal') or (network.get('Labels') or {}).get(OWNER_LABEL) != self.run_id \
                or (network.get('Labels') or {}).get(SCOPE_LABEL) != SCOPE:
            raise Refused('network')
        attached = {self.ids['redis'], *([self.ids[ROLE]] if running else []), *([self.ids[STREAM]] if stream else [])}
        if set(network.get('Containers') or {}) != attached:
            raise Refused('unexpected-container')

    # -- observação -------------------------------------------------------
    def exec_json(self, code, *args):
        out = self.docker('exec', '--user', USER, self.ids[ROLE], 'python', '-I', '-c', code, *args)
        return json.loads(out.strip().splitlines()[-1])

    def pid1(self):
        if not pid1_ok(self.exec_json(PID_PROBE), self.uvicorn.get('interpreter'), self.uvicorn.get('script')):
            raise Refused('pid1')

    def tcp(self):
        return self.exec_json(TCP_PROBE, str(PORT))

    def summary(self):
        return log_summary(*self.log_runner(['docker', 'logs', self.ids[ROLE]]))

    def running(self, role=ROLE):
        return bool((self.inspect(self.ids[role]).get('State') or {}).get('Running'))

    def queue_items(self):
        return self.redis('LRANGE', QUEUE, '0', '-1').splitlines()

    def wait_health(self, stage):
        if self.http_probe('health', str(READY_S)) != HEALTHY:
            raise Refused('health' if self.running() else 'backend-exited-before-ready')
        if not stage_ok(self.summary(), stage):
            raise Refused('backend-log-' + stage)

    def wait_stream(self, stream):
        # Probe que sai (ACK ausente, ioctl indisponível) deixa READY vazio: recusa; limpeza pelo ledger.
        self._until(lambda: self.redis('GET', READY_KEY) != '' or not self.running(STREAM),
                    'stream-probe-not-ready', PROBE_S)
        return stream_peer(self.redis('GET', READY_KEY), self.ip(stream))

    def held(self, peer, stages, listening):
        """Retido: backend e probe vivos, fila vazia e log numa das fases aceitas; devolve (fase, TCP ok)."""
        if not self.running():
            raise Refused('backend-exited-while-held')
        if not self.running(STREAM):
            raise Refused('inflight-closed-before-release')
        if self.keys() != {READY_KEY}:
            raise Refused('queue-before-release')
        summary = self.summary()
        stage = next((stage for stage in stages if stage_ok(summary, stage)), None)
        if stage is None:
            raise Refused('backend-log-while-held')
        return stage, tcp_held(self.tcp(), peer, listening=listening)

    def fresh_connection_refused(self):
        return self.http_probe('connect', self.ip(self.ids[ROLE])) == {'connect': 'refused'}


def _stop_idle(r, items):
    r.check_backend(running=True)
    r.docker('kill', '--signal', 'SIGTERM', r.ids[ROLE])
    signalled = r.clock()
    r._await_exit(ROLE, EXIT_BUDGET_S)
    r.timings['idle_exit_after_sigterm_s'] = round(r.clock() - signalled, 3)
    if r.queue_items() != items or r.keys() != {QUEUE}:
        raise Refused('queue-changed-by-restart')
    r.check_backend(running=False)


def rehearse(r):
    r.preflight()
    r.create_support()
    r.start_backend()
    r.wait_health('ready')
    r.check_backend(running=True)
    r.pid1()
    r.checks.append('real-uvicorn-pid1-init-false-health-200-only-db-warmup-warning (health nao e readiness)')

    if r.http_probe('post', WEBHOOK_PATH, WRONG_TOKEN, BODY.hex()) != REJECTED:
        raise Refused('auth-not-rejected')
    if r.keys() or not stage_ok(r.summary(), 'rejected'):
        raise Refused('queue-or-log-after-rejection')
    r.checks.append('real-header-auth-wrong-token-401-after-full-body-queue-empty')

    # Barreira: headers completos + corpo parcial consumidos pelo PID 1, sem resposta nem enqueue.
    stream = r.spawn_stream()
    started = r.clock()
    peer = r.wait_stream(stream)
    while r.held(peer, ('rejected',), listening=True) != ('rejected', True):
        if r.clock() - started >= BARRIER_S:
            raise Refused('barrier-timeout')
        r.sleep(0.2)
    r.timings['barrier_proved_s'] = round(r.clock() - started, 3)
    r.check_backend(running=True, stream=True)
    r.pid1()
    r.checks.append('stream-probe-partial-body-client-acked-outq-0-established-owned-by-pid1-recv-q-0-send-q-0-'
                    'queue-empty')

    r.docker('kill', '--signal', 'SIGTERM', r.ids[ROLE])
    signalled = r.clock()
    while r.held(peer, ('rejected', 'signalled', 'draining'), listening=None) != ('draining', True):
        if r.clock() - signalled >= DRAIN_LOG_S:
            raise Refused('drain-not-observed')
        r.sleep(0.2)
    r.timings['waiting_connections_after_sigterm_s'] = round(r.clock() - signalled, 3)
    if not r.fresh_connection_refused():
        raise Refused('new-connection-accepted-while-draining')
    observed = r.clock()
    while r.clock() - observed < HOLD_S:
        if r.held(peer, ('draining',), listening=False) != ('draining', True):
            raise Refused('barrier-lost')
        r.sleep(0.2)
    if not r.fresh_connection_refused():
        raise Refused('new-connection-accepted-while-draining')
    r.check_backend(running=True, stream=True)
    r.pid1()
    if r.held(peer, ('draining',), listening=False) != ('draining', True):
        raise Refused('barrier-lost')
    # Medida depois do último check, sem arredondar na decisão: só o SET separa a recusa da liberação.
    held = r.clock() - signalled
    r.timings['held_after_sigterm_s'] = round(held, 3)
    if held >= HOLD_BUDGET_S:
        raise Refused('hold-too-long')
    r.redis('SET', RELEASE_KEY, '1')
    released = r.clock()
    r.checks.append('sigterm-backend-alive-waiting-connections-listener-closed-new-connection-refused-'
                    'inflight-request-held-lifespan-not-shut-down')

    result = json.loads(r.collect(stream, PROBE_S, 'stream-probe'))
    r.observed['response_connection_header'] = result.get('connection')
    if not response_ok(result):
        raise Refused('inflight-response')
    r._await_exit(ROLE, EXIT_BUDGET_S)
    exited = r.clock() - released
    r.timings['exit_after_release_s'] = round(exited, 3)
    if exited >= EXIT_BUDGET_S:
        raise Refused('exit-too-slow')
    if r.redis('DEL', READY_KEY, RELEASE_KEY) != '2':
        raise Refused('synthetic-keys')
    if r.keys() != {QUEUE}:
        raise Refused('unexpected-redis-state')
    items = r.queue_items()
    if not envelope_ok(items):
        raise Refused('enqueue-envelope')
    del r.ids[STREAM]
    r.check_backend(running=False)
    stopped = r.summary()
    r.log_first_stop = stopped
    if not stage_ok(stopped, 'stopped'):
        raise Refused('backend-log-after-stop')
    # Só consistência: a duração inclui o processamento pós-liberação e a latência do kill, então
    # não prova que o app recebeu o request antes do SIGTERM (isso vem de ACK, Recv-Q 0 e drenagem).
    duration = stopped['inflight_duration_ms']
    if len(duration) != 1 or duration[0] / 1000 < released - signalled:
        raise Refused('inflight-duration-inconsistent')
    r.checks += ['released-rest-on-same-connection-202-queued-server-closed-connection-no-reuse',
                 'single-real-webhookqueue-envelope-ignored-payload-attempts-0',
                 'lifespan-closed-pools-after-response-exit-0-no-sigkill',
                 'telemetry-duration-consistent-with-hold (consistencia, nao prova de ordem)']

    r.sleep(SURVIVE_S)
    if r.queue_items() != items or r.keys() != {QUEUE}:
        raise Refused('queue-changed-after-stop')
    r.check_backend(running=False)
    r.docker('start', r.ids[ROLE])
    r.wait_health('restarted')
    r.check_backend(running=True)
    r.pid1()
    if r.queue_items() != items or r.keys() != {QUEUE}:
        raise Refused('queue-changed-by-restart')
    _stop_idle(r, items)
    r.log = r.summary()
    if not stage_ok(r.log, 'final'):
        raise Refused('backend-log-final')
    r.checks.append('queue-bytes-preserved-after-stop-and-restart-without-consumer-second-sigterm-exit-0')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    reh = sub.add_parser('run')
    reh.add_argument('--repo', type=Path, required=True)
    reh.add_argument('--legacy-image', default=DEFAULT_IMAGES['legacy'])
    reh.add_argument('--redis-image', default=DEFAULT_IMAGES['redis'])
    reh.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    report = dict(kind='synthetic-legacy-backend-inflight-http-rehearsal', status='fail', production_ready=False,
                  legacy_sha=LEGACY_SHA, entrypoint=' '.join([ENTRYPOINT, *ARGS]),
                  command_equivalence=COMMAND_EQUIVALENCE, not_proven=NOT_PROVEN,
                  scope='backend ASGI legado real (uvicorn PID 1), Redis efemero, banco em loopback morto, '
                        'POST de webhook em curso durante SIGTERM; sem consumidor/provedor/producao',
                  note='health 200 prova so liveness do processo; nao e readiness nem prontidao de producao',
                  images=dict(legacy=args.legacy_image, redis=args.redis_image),
                  expected=dict(first_run=FIRST_RUN, second_run=SECOND_RUN, access=STAGES['final'][1]),
                  checks=[])
    rehearsal = None
    try:
        files = legacy_sources(args.repo)
        report['source'] = dict(files=len(files), manifest_sha256=manifest_digest(manifest(files)))
        rehearsal = BackendRehearsal(legacy_image=args.legacy_image, redis_image=args.redis_image, files=files)
        rehearse(rehearsal)
        report.update(status='pass', reason=None)
    except Refused as exc:
        preflight = rehearsal is None or rehearsal.phase == 'preflight'
        report.update(status='refused' if preflight else 'fail', reason=str(exc))
    except KeyboardInterrupt:
        report['reason'] = 'interrupted'
    except OSError:
        report['reason'] = 'os-error'
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        report['reason'] = 'unexpected-output'
    finally:
        if rehearsal is not None:
            report.update(checks=rehearsal.checks, mismatch=rehearsal.mismatch, timings=rehearsal.timings,
                          uvicorn=rehearsal.uvicorn, observed=rehearsal.observed,
                          log_first_stop=getattr(rehearsal, 'log_first_stop', None),
                          log=getattr(rehearsal, 'log', None), cleanup=rehearsal.cleanup())
            if report['cleanup']['status'] != 'clean' and report['status'] == 'pass':
                report.update(status='fail', reason='cleanup-incomplete')
        args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
