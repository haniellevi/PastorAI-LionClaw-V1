#!/usr/bin/env python3
"""Ensaio EXCLUSIVAMENTE sintético de contenção dos quatro serviços e retomada pré-DDL.

Cria seus próprios recursos descartáveis (prefixo aleatório e label de posse
com UUID da execução): rede ``--internal`` sem portas, Redis, provedor falso
com barreira e quatro processos SIMULADOS (``synthetic_legacy_worker.py``)
como containers avulsos, sem labels de Compose, inclusive o
``broadcast-worker``. Entrypoint e usuário são explícitos; o ENTRYPOINT da
imagem nunca é usado. Não aceita nome, ID, DSN nem host de alvo existente;
aceita só IDs de imagem locais (``sha256:...``) e o caminho do relatório.
Nunca baixa imagem, reinicia daemon/host nem toca recurso que não criou.

O relatório prova a TOPOLOGIA e o CONTROLADOR sintéticos (posse, identidade,
SIGTERM com prazo sem SIGKILL, recusas e retomada explícita). Os workers são
simulados e a marca de DDL não executa SQL: não prova o tratamento de SIGTERM
dos workers reais de ``07a3f4d``, retries da Evolution, reinício do Docker nem
compatibilidade pós-DDL. Não é um controlador de PROD.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKER_CODE = HERE / 'synthetic_legacy_worker.py'
# Contenção: ingresso e produtores antes dos consumidores.
CONTAIN_ORDER = ('backend', 'cron-worker', 'broadcast-worker', 'queue-worker')
# Retomada: API primeiro, depois os consumidores, um a um.
RESUME_ORDER = ('backend', 'queue-worker', 'broadcast-worker', 'cron-worker')
SERVICES = frozenset(CONTAIN_ORDER)
SUPPORT = ('redis', 'provider')
OWNER_LABEL = 'pastorai.synthetic.owner'
ROLE_LABEL = 'pastorai.synthetic.role'
SCOPE_LABEL = 'pastorai.scope'
SCOPE = 'dev-sintetico'
USER = '65534:65534'
IMAGE_ID = re.compile(r'sha256:[0-9a-f]{64}')
RESOURCE_ID = re.compile(r'[0-9a-f]{64}')
LOCAL_DOCKER = re.compile(r'unix:///var/run/docker\.sock|unix:///run/user/[0-9]+/docker\.sock')
REMOTE_ENV = ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH')
# Configuração de gate SINTÉTICA, com valores fictícios e ilustrativos; nunca muda.
# Não é espelho de PROD: lá não há variável ASAAS real e o default não foi verificado.
GATES = {
    'SYNTHETIC_ALLOW_REAL_SENDS': 'true',
    'SYNTHETIC_ASAAS_BILLING_ENABLED': 'false',
    'SYNTHETIC_BREVO_SEND_MODE': 'live',
    'SYNTHETIC_BROADCAST_ASYNC_ENABLED': 'false',
}
# Prazos dos cenários físicos: resposta do provedor < prazo gracioso < expiração.
PROVIDER_TIMEOUT_S = 15
GRACE_S = 30
EXPIRY_S = 50
NOT_PROVEN = [
    'sigterm-dos-workers-reais-07a3f4d',
    'retries-da-evolution',
    'reinicio-do-docker-ou-do-host',
    'compatibilidade-pos-ddl',
    'semantica-dos-workers-legados',
    'ddl-real (a marca de DDL nao executa SQL)',
]
HOLD = 'synthetic:provider:hold'
EFFECTS = 'synthetic:provider:effects'
SCHEDULED = 'synthetic:cron:scheduled'


class Refused(RuntimeError):
    """Recusa com código fixo; nunca carrega saída de comando ou valores."""


def run(argv):
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        completed = None
    if completed is None:
        # Fora do except: a recusa não encadeia o TimeoutExpired, que carrega comando e saída.
        raise Refused('docker-timeout')
    if completed.returncode:
        raise Refused('docker-step')
    return completed.stdout


class Rehearsal:
    def __init__(self, *, worker_image, redis_image, runner=run, clock=time.monotonic,
                 sleep=time.sleep, run_id=None):
        if not all(IMAGE_ID.fullmatch(str(image or '')) for image in (worker_image, redis_image)):
            raise Refused('image-not-local-immutable')
        self.run_id = run_id or uuid.uuid4().hex
        if not re.fullmatch(r'[0-9a-f]{32}', self.run_id):
            raise Refused('run-id')
        self.prefix = 'pastorai-synthetic-containment-' + self.run_id[:12]
        self.images = {'worker': worker_image, 'redis': redis_image}
        self.runner, self.clock, self.sleep = runner, clock, sleep
        self.ids: dict[str, str] = {}
        self.network: str | None = None
        # Ledger: todo ID criado por esta execução, registrado assim que o Docker devolve.
        self.created: dict[str, list[str]] = {'containers': [], 'networks': []}
        self.gate_env: dict[str, dict[str, str]] = {}
        self.state = {'status': 'new', 'ddl_marked': False, 'reason': None}

    # -- infraestrutura ---------------------------------------------------
    def docker(self, *args):
        return self.runner(['docker', *args])

    def guard_local(self):
        if any(os.environ.get(name) for name in REMOTE_ENV):
            raise Refused('remote-docker')
        host = json.loads(self.docker('context', 'inspect'))[0]['Endpoints']['docker']['Host']
        if not LOCAL_DOCKER.fullmatch(host):
            raise Refused('remote-docker')

    def labels(self, role):
        return ['--label', f'{OWNER_LABEL}={self.run_id}', '--label', f'{ROLE_LABEL}={role}',
                '--label', f'{SCOPE_LABEL}={SCOPE}']

    def _record(self, kind, identifier):
        identifier = identifier.strip()
        if not RESOURCE_ID.fullmatch(identifier):
            raise Refused('docker-step')
        self.created[kind].append(identifier)
        return identifier

    def _hardened(self, role, entrypoint):
        return ['run', '-d', '--pull', 'never', '--restart', 'no', '--network', self.network,
                '--entrypoint', entrypoint, '--user', USER, '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', *self.labels(role)]

    def start_container(self, role, *, ignore_term=False):
        """Cria um container próprio; sem portas, montagens do host nem socket."""
        named = ['--name', f'{self.prefix}-{role}', '--network-alias', role]
        if role == 'redis':
            argv = [*self._hardened(role, 'redis-server'), *named,
                    '--tmpfs', '/data:rw,noexec,nosuid,size=16m,mode=1777', self.images['redis'],
                    '--save', '', '--appendonly', 'no', '--dir', '/data',
                    '--protected-mode', 'no', '--bind', '0.0.0.0']
        else:
            env = dict(GATES) if role in SERVICES else {}
            if role in ('queue-worker', 'broadcast-worker'):
                env['SYNTHETIC_PROVIDER_TIMEOUT_S'] = str(PROVIDER_TIMEOUT_S)
            if ignore_term:
                env['SYNTHETIC_IGNORE_TERM'] = '1'
            flags = [part for name, value in sorted(env.items()) for part in ('--env', f'{name}={value}')]
            argv = [*self._hardened(role, 'python3'), *named, '--env', 'PYTHONDONTWRITEBYTECODE=1',
                    *flags, self.images['worker'], '-u', '-c', WORKER_CODE.read_text(), role]
        return self._record('containers', self.docker(*argv))

    def probe(self, mode, payload=''):
        """Cliente interno efêmero e registrado; único acesso ao ingresso, na rede própria."""
        identifier = self._record('containers', self.docker(
            *self._hardened('probe', 'python3'), self.images['worker'], '-c', PROBE, mode, payload))
        try:
            self.docker('wait', identifier)
            return self.docker('logs', identifier).strip()
        finally:
            self.docker('rm', '-f', '-v', identifier)

    def create(self, *, ignore_term=()):
        self.guard_local()
        for image in self.images.values():
            # Imagem ausente (inspect falha) é recusada como tal, antes de qualquer efeito.
            try:
                found = json.loads(self.docker('image', 'inspect', image))[0].get('Id')
            except (Refused, ValueError, IndexError, AttributeError):
                found = None
            if found != image:
                raise Refused('image-not-local-immutable')
        self.network = self._record('networks', self.docker(
            'network', 'create', '--internal', '--label', f'{OWNER_LABEL}={self.run_id}',
            '--label', f'{SCOPE_LABEL}={SCOPE}', self.prefix))
        self.ids['redis'] = self.start_container('redis')
        self._until(lambda: self._redis_ready(), 'redis-readiness')
        for role in ('provider', *CONTAIN_ORDER):
            self.ids[role] = self.start_container(role, ignore_term=role in ignore_term)
        self.wait_boots({role: 0 for role in ('provider', *CONTAIN_ORDER)})
        # HTTP real do backend e do provedor antes de qualquer probe de ingresso.
        self._until(lambda: self.probe('ready') == 'accepted', 'http-readiness')
        self.validate(running={*SUPPORT, *SERVICES})
        self.state['status'] = 'running'

    def _until(self, predicate, code, timeout=60):
        limit = self.clock() + timeout
        while not predicate():
            if self.clock() >= limit:
                raise Refused(code)
            self.sleep(0.2)

    def redis(self, *args):
        return self.docker('exec', self.ids['redis'], 'redis-cli', *args).strip()

    def _redis_ready(self):
        try:
            return self.redis('PING') == 'PONG'
        except Refused:
            return False

    def boots(self, role):
        value = self.redis('GET', f'synthetic:boots:{role}')
        return int(value) if value.isdigit() else 0

    def wait_boots(self, previous, timeout=60):
        self._until(lambda: all(self.boots(role) > count for role, count in previous.items()),
                    'readiness-timeout', timeout)

    # -- validação --------------------------------------------------------
    def inspect(self, identifier):
        try:
            return json.loads(self.docker('inspect', identifier))[0]
        except (Refused, ValueError, IndexError) as exc:
            raise Refused('identity') from exc

    def _validate_one(self, role, *, running):
        identifier = self.ids.get(role)
        if not identifier:
            raise Refused('identity')
        data = self.inspect(identifier)
        config = data.get('Config') or {}
        labels = config.get('Labels') or {}
        if (labels.get(OWNER_LABEL) != self.run_id or labels.get(ROLE_LABEL) != role
                or labels.get(SCOPE_LABEL) != SCOPE):
            raise Refused('ownership')
        if data.get('Id') != identifier or identifier not in self.created['containers']:
            raise Refused('identity')
        if data.get('Image') != self.images['redis' if role == 'redis' else 'worker']:
            raise Refused('image')
        if (config.get('Entrypoint') or []) != ['redis-server' if role == 'redis' else 'python3'] \
                or config.get('User') != USER:
            raise Refused('entrypoint')
        host = data.get('HostConfig') or {}
        mounts = data.get('Mounts') or []
        ports = (data.get('NetworkSettings') or {}).get('Ports') or {}
        if (host.get('PortBindings') or host.get('PublishAllPorts') or host.get('Privileged')
                or host.get('Binds') or any(ports.values())
                or any(m.get('Type') not in {'tmpfs', 'volume'} or 'docker.sock' in str(m.get('Source', ''))
                       for m in mounts)
                or (role != 'redis' and mounts)):
            raise Refused('host-exposure')
        # NetworkMode guarda o ID passado em --network, mesmo com o container parado.
        networks = (data.get('NetworkSettings') or {}).get('Networks') or {}
        if host.get('NetworkMode') != self.network or set(networks) != {self.prefix}:
            raise Refused('network')
        state = data.get('State') or {}
        if bool(state.get('Running')) != running or data.get('RestartCount', 0):
            raise Refused('unexpected-state')
        if role in SERVICES:
            env = dict(item.split('=', 1) for item in config.get('Env') or [] if '=' in item)
            gates = {name: env.get(name) for name in GATES}
            if gates != GATES or self.gate_env.setdefault(role, gates) != gates:
                raise Refused('gate-config-changed')

    def validate(self, *, running):
        """Conjunto exato: seis containers próprios, nenhum quinto writer na rede."""
        self.guard_local()
        owned = set(self.docker('ps', '-aq', '--no-trunc', '--filter', f'label={OWNER_LABEL}={self.run_id}').split())
        if owned != set(self.ids.values()) or set(self.ids) != {*SUPPORT, *SERVICES}:
            raise Refused('unexpected-container')
        for role in (*SUPPORT, *CONTAIN_ORDER):
            self._validate_one(role, running=role in running)
        network = json.loads(self.docker('network', 'inspect', self.network))[0]
        if not network.get('Internal') or (network.get('Labels') or {}).get(OWNER_LABEL) != self.run_id:
            raise Refused('network')
        if set(network.get('Containers') or {}) != {self.ids[role] for role in running}:
            raise Refused('unexpected-container')

    # -- contenção e retomada --------------------------------------------
    def _refuse(self, code):
        self.state.update(status='refused', reason=code)
        return Refused(code)

    def _await_exit(self, role, grace_s):
        limit = self.clock() + grace_s
        while True:
            state = self.inspect(self.ids[role]).get('State') or {}
            if not state.get('Running'):
                if state.get('ExitCode') != 0:
                    raise Refused('ungraceful-exit')
                return
            if self.clock() >= limit:
                # Sem SIGKILL: o processo continua vivo para decisão humana.
                raise Refused('graceful-timeout')
            self.sleep(0.2)

    def contain(self, *, grace_s=GRACE_S, on_signal=None):
        """SIGTERM com prazo, um serviço por vez; ``on_signal`` roda entre o sinal e a espera."""
        if self.state['status'] != 'running':
            raise self._refuse('not-running')
        if not 0 < grace_s <= 120:
            raise self._refuse('grace')
        self.state['status'] = 'containing'
        try:
            self.validate(running={*SUPPORT, *SERVICES})
            for role in CONTAIN_ORDER:
                # Identidade revalidada imediatamente antes de cada sinal.
                self._validate_one(role, running=True)
                self.docker('kill', '--signal', 'SIGTERM', self.ids[role])
                if on_signal:
                    on_signal(role)
                self._await_exit(role, grace_s)
            self.validate(running=set(SUPPORT))
        except KeyboardInterrupt:
            raise self._refuse('interrupted') from None
        except Refused as exc:
            raise self._refuse(str(exc)) from None
        self.state['status'] = 'contained'

    def mark_ddl(self):
        """Marca o ponto sem volta do ensaio; nenhum SQL é executado."""
        if self.state['status'] != 'contained':
            raise Refused('not-contained')
        self.state.update(status='ddl-marked', ddl_marked=True)

    def resume_token(self):
        return f'RETOMAR-PRE-DDL:{self.run_id}'

    def resume(self, confirmation):
        if self.state['ddl_marked']:
            raise Refused('post-ddl')
        if self.state['status'] != 'contained':
            raise Refused('not-contained')
        if confirmation != self.resume_token():
            raise Refused('confirmation')
        self.state['status'] = 'resuming'
        try:
            self.validate(running=set(SUPPORT))
            running = set(SUPPORT)
            for role in RESUME_ORDER:
                # Revalida o conjunto antes de cada partida; os mesmos containers,
                # portanto a mesma imagem e a mesma configuração de gate.
                self.validate(running=running)
                previous = self.boots(role)
                self.docker('start', self.ids[role])
                self.wait_boots({role: previous})
                running.add(role)
            self.validate(running=running)
        except KeyboardInterrupt:
            raise self._refuse('interrupted') from None
        except Refused as exc:
            # Sem novo start nem retomada automática: decisão humana.
            raise self._refuse('resume-failed:' + str(exc)) from None
        self.state['status'] = 'resumed'

    def _list_ids(self, kind):
        """Listagem read-only de todos os IDs existentes; ``None`` se o Docker não responder."""
        argv = ('container', 'ls', '-aq', '--no-trunc') if kind == 'containers' else ('network', 'ls', '-q', '--no-trunc')
        try:
            return set(self.docker(*argv).split())
        except Exception:  # noqa: BLE001 - indisponibilidade não é ausência
            return None

    def _remove_owned(self, kind, identifier):
        try:
            if kind == 'containers':
                labels = (json.loads(self.docker('inspect', identifier))[0].get('Config') or {}).get('Labels') or {}
            else:
                labels = json.loads(self.docker('network', 'inspect', identifier))[0].get('Labels') or {}
        except Exception:  # noqa: BLE001 - listado e sem inspect: sobra, não inexistente
            return 'inspect-failed'
        if labels.get(OWNER_LABEL) != self.run_id:
            return 'not-owned'
        try:
            self.docker(*(('rm', '-f', '-v') if kind == 'containers' else ('network', 'rm')), identifier)
        except Exception:  # noqa: BLE001
            return 'rm-failed'
        return None

    def cleanup(self):
        """Tenta remover TODOS os IDs do ledger que ainda tenham o label de posse; nunca levanta.

        Ausência só é concluída por listagem read-only bem-sucedida, nunca por
        falha de inspect. Erros e sobras vão para o resultado, que só é
        ``clean`` sem nenhum dos dois.
        """
        errors, leftovers = [], {'containers': [], 'networks': []}
        try:
            self.guard_local()
        except Exception as exc:  # noqa: BLE001
            code = str(exc) if isinstance(exc, Refused) else 'docker-unavailable'
            leftovers = {kind: list(reversed(ids)) for kind, ids in self.created.items()}
            return dict(status='incomplete', errors=[dict(kind='docker', code=code)], leftovers=leftovers)
        for kind in ('containers', 'networks'):
            ledger = list(reversed(self.created[kind]))
            existing = self._list_ids(kind)
            if existing is None:
                errors.append(dict(kind=kind, code='list-unavailable'))
                leftovers[kind] = ledger
                continue
            for identifier in ledger:
                if identifier in existing:
                    code = self._remove_owned(kind, identifier)
                    if code:
                        errors.append(dict(kind=kind, id=identifier, code=code))
            remaining = self._list_ids(kind)
            if remaining is None:
                errors.append(dict(kind=kind, code='verify-unavailable'))
                remaining = set(ledger)
            leftovers[kind] = [identifier for identifier in ledger if identifier in remaining]
        clean = not errors and not any(leftovers.values())
        return dict(status='clean' if clean else 'incomplete', errors=errors, leftovers=leftovers)


PROBE = (
    "import sys,urllib.request\n"
    "def go(url,data=None):\n"
    " r=urllib.request.Request(url,data=data,method='POST' if data else 'GET',"
    "headers={'Content-Type':'application/json'})\n"
    " urllib.request.urlopen(r,timeout=3)\n"
    "try:\n"
    " if sys.argv[1]=='ready':\n"
    "  go('http://backend:8000/ready');go('http://provider:8080/ready')\n"
    " else:\n"
    "  go('http://backend:8000/webhook',sys.argv[2].encode())\n"
    " print('accepted')\n"
    "except Exception:\n"
    " print('refused')\n"
)


# -- cenários físicos -----------------------------------------------------
def _item(key, deadline):
    return json.dumps({'deadline': float(deadline), 'key': key}, separators=(',', ':'), sort_keys=True)


def ingress(r, key, deadline):
    return r.probe('post', json.dumps({'key': key, 'deadline': float(deadline)}))


def _wait(predicate, r, timeout=60):
    limit = r.clock() + timeout
    while not predicate():
        if r.clock() >= limit:
            raise AssertionError('synthetic condition not reached')
        r.sleep(0.2)


def _int(r, *args):
    value = r.redis(*args)
    return int(value) if value.isdigit() else 0


def _list(r, name):
    return [line for line in r.redis('LRANGE', name, '0', '-1').splitlines() if line]


def _expect_refused(code, action):
    try:
        action()
    except Refused as exc:
        if str(exc) != code:
            raise AssertionError(f'expected {code}, got {exc}') from None
        return
    raise AssertionError(f'{code} not refused')


def _blocked_after_refusal(r):
    _expect_refused('not-contained', r.mark_ddl)
    _expect_refused('not-contained', lambda: r.resume(r.resume_token()))


def _seed_parked(r, t):
    """Broadcast pendente e cron agendado no futuro; com os gates inalterados, ficam parados."""
    raws = dict(broadcast=_item('broadcast-pending', t + 600),
                scheduled=json.dumps({'deadline': float(t + 600), 'due': float(t + 3600), 'key': 'cron-future'},
                                     separators=(',', ':'), sort_keys=True))
    r.redis('RPUSH', 'synthetic:broadcast:pending', raws['broadcast'])
    r.redis('RPUSH', SCHEDULED, raws['scheduled'])
    return raws


def _assert_parked(r, raws):
    """Mesmos bytes no Redis; nada consumido, promovido ou enviado."""
    assert _list(r, 'synthetic:broadcast:pending') == [raws['broadcast']]
    assert _list(r, SCHEDULED) == [raws['scheduled']]
    assert not any(_list(r, f'synthetic:broadcast:{state}') for state in ('processing', 'done', 'ambiguous', 'expired'))
    assert _int(r, 'HGET', EFFECTS, 'broadcast-pending') == 0
    assert _int(r, 'HGET', EFFECTS, 'cron-future') == 0


def _prime_real_in_flight(r):
    """Envio real em curso e pendências reais, tudo ANTES de qualquer SIGTERM.

    A barreira segura a resposta do provedor depois de contar o efeito; como o
    consumidor processa um item por vez, as pendências seguintes ficam na fila.
    """
    r.redis('SET', HOLD, '1')
    t = time.time()
    raws = dict(in_flight=_item('in-flight', t + 600), future=_item('pending-future', t + 600),
                expiring=_item('pending-expiring', t + EXPIRY_S), expiry=t + EXPIRY_S)
    raws.update(_seed_parked(r, t))
    assert ingress(r, 'in-flight', t + 600) == 'accepted'
    _wait(lambda: _int(r, 'GET', 'synthetic:provider:arrived') == 1, r)
    assert ingress(r, 'pending-future', t + 600) == 'accepted'
    assert ingress(r, 'pending-expiring', t + EXPIRY_S) == 'accepted'
    assert _list(r, 'synthetic:queue:processing') == [raws['in_flight']]
    assert _list(r, 'synthetic:queue:pending') == [raws['future'], raws['expiring']]
    assert _int(r, 'HGET', 'synthetic:provider:effects', 'in-flight') == 1
    _assert_parked(r, raws)
    return raws


def _resume_and_check(r, raws):
    _assert_parked(r, raws)  # depois da contenção, antes da retomada
    _wait(lambda: time.time() > raws['expiry'] + 1, r, timeout=EXPIRY_S + 10)  # vence na pausa
    r.resume(r.resume_token())
    _wait(lambda: _int(r, 'HGET', 'synthetic:provider:effects', 'pending-future') == 1
          and _list(r, 'synthetic:queue:expired') == [raws['expiring']], r)
    assert not _list(r, 'synthetic:queue:pending') and not _list(r, 'synthetic:queue:processing')
    assert _int(r, 'HGET', 'synthetic:provider:effects', 'pending-expiring') == 0
    assert _int(r, 'HGET', 'synthetic:provider:effects', 'in-flight') == 1  # nunca reenviado
    _assert_parked(r, raws)
    assert all(r.gate_env[role] == GATES for role in SERVICES)  # gates não abertos para enviar


def scenario_in_flight_completes_after_sigterm(r):
    """A: SIGTERM com envio em curso; a barreira é liberada entre o sinal e a espera."""
    r.create()
    raws = _prime_real_in_flight(r)

    def release(role):
        if role == 'queue-worker':
            r.redis('DEL', HOLD)

    r.contain(on_signal=release)
    assert time.time() < raws['expiry'], 'pendência expirou antes da pausa'
    assert _list(r, 'synthetic:queue:done') == [raws['in_flight']]
    assert not _list(r, 'synthetic:queue:processing') and not _list(r, 'synthetic:queue:ambiguous')
    assert _list(r, 'synthetic:queue:pending') == [raws['future'], raws['expiring']]
    assert ingress(r, 'ingress-during', time.time() + 600) == 'refused'
    _resume_and_check(r, raws)
    assert _int(r, 'HGET', 'synthetic:provider:effects', 'ingress-during') == 0
    return ['real-send-in-flight-before-sigterm', 'pending-queued-before-stop',
            'in-flight-completed-after-sigterm', 'graceful-exit-0-no-sigkill',
            'backend-stopped-internal-probe-refused', 'expiry-during-pause-keeps-bytes',
            'api-first-explicit-resume-same-containers', 'effect-count-1',
            'broadcast-and-future-cron-bytes-unchanged-gates-unchanged']


def scenario_in_flight_response_lost(r):
    """B: efeito ocorreu e a resposta não chega; timeout leva a ambiguous, sem retry."""
    r.create()
    raws = _prime_real_in_flight(r)
    r.contain()  # a barreira segue fechada: o worker desiste após PROVIDER_TIMEOUT_S
    assert time.time() < raws['expiry'], 'pendência expirou antes da pausa'
    assert _list(r, 'synthetic:queue:ambiguous') == [raws['in_flight']]
    assert not _list(r, 'synthetic:queue:done') and not _list(r, 'synthetic:queue:processing')
    assert _list(r, 'synthetic:queue:pending') == [raws['future'], raws['expiring']]
    r.redis('DEL', HOLD)
    _resume_and_check(r, raws)
    assert _list(r, 'synthetic:queue:ambiguous') == [raws['in_flight']]
    return ['effect-without-response-goes-ambiguous', 'no-retry', 'graceful-exit-0-no-sigkill',
            'pending-preserved', 'expiry-during-pause-keeps-bytes', 'effect-count-1-after-resume',
            'broadcast-and-future-cron-bytes-unchanged-gates-unchanged']


def scenario_post_ddl(r):
    r.create()
    r.contain()
    r.mark_ddl()
    _expect_refused('post-ddl', lambda: r.resume(r.resume_token()))
    r.validate(running=set(SUPPORT))
    return ['legacy-resume-refused-after-ddl-mark (sem SQL)']


def scenario_graceful_timeout(r):
    r.create(ignore_term={'queue-worker'})
    _expect_refused('graceful-timeout', lambda: r.contain(grace_s=3))
    assert r.inspect(r.ids['queue-worker'])['State']['Running']  # sem SIGKILL
    _blocked_after_refusal(r)
    return ['timeout-refused-without-sigkill', 'no-ddl-or-resume-after-refusal']


def scenario_identity_swapped(r):
    r.create()
    r.docker('rm', '-f', '-v', r.ids['queue-worker'])  # recurso próprio, do ledger
    r.start_container('queue-worker')  # substituto também entra no ledger
    _expect_refused('unexpected-container', r.contain)
    _blocked_after_refusal(r)
    return ['swapped-identity-refused-before-signal', 'no-ddl-or-resume-after-refusal']


def scenario_fifth_writer(r):
    r.create()
    r.start_container('intruder')
    _expect_refused('unexpected-container', r.contain)
    assert all(r.inspect(r.ids[role])['State']['Running'] for role in SERVICES)
    _blocked_after_refusal(r)
    return ['fifth-writer-refused-before-signal', 'no-ddl-or-resume-after-refusal']


def scenario_interrupted(r):
    r.create()

    def interrupt(role):
        if role == 'backend':
            raise KeyboardInterrupt

    _expect_refused('interrupted', lambda: r.contain(on_signal=interrupt))
    _wait(lambda: not r.inspect(r.ids['backend'])['State']['Running'], r, timeout=GRACE_S)
    assert all(r.inspect(r.ids[role])['State']['Running'] for role in CONTAIN_ORDER[1:])
    _blocked_after_refusal(r)
    return ['interruption-stops-sequence', 'no-ddl-or-resume-after-refusal']


SCENARIOS = {
    'in-flight-completes-after-sigterm': scenario_in_flight_completes_after_sigterm,
    'in-flight-response-lost': scenario_in_flight_response_lost,
    'post-ddl-mark': scenario_post_ddl,
    'graceful-timeout': scenario_graceful_timeout,
    'identity-swapped': scenario_identity_swapped,
    'fifth-writer': scenario_fifth_writer,
    'interrupted': scenario_interrupted,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--worker-image', required=True, help='ID local sha256:... com python3')
    parser.add_argument('--redis-image', required=True, help='ID local sha256:... com redis-server >= 6.2')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    report = dict(kind='synthetic-legacy-containment-rehearsal', status='fail', production_ready=False,
                  topology='controlador-sintetico + 4 processos SIMULADOS + redis e provedor falsos',
                  workers='simulados (deploy/synthetic_legacy_worker.py), nao os workers da aplicacao',
                  ddl='marca de estado do controlador, sem SQL',
                  not_proven=NOT_PROVEN, images=dict(worker=args.worker_image, redis=args.redis_image),
                  scenarios={})
    try:
        for name, scenario in SCENARIOS.items():
            try:
                rehearsal = Rehearsal(worker_image=args.worker_image, redis_image=args.redis_image)
            except Refused as exc:
                report['scenarios'][name] = dict(result='fail', reason=str(exc))
                break
            outcome = dict(result='fail', reason='aborted')
            try:
                outcome = dict(result='pass', checks=scenario(rehearsal), final_state=rehearsal.state['status'])
            except (AssertionError, Refused) as exc:
                outcome = dict(result='fail', reason=str(exc) if isinstance(exc, Refused) else 'assertion')
            finally:
                # A limpeza nunca levanta nem substitui o motivo original; sobra nunca é PASS.
                outcome['cleanup'] = rehearsal.cleanup()
                if outcome['cleanup']['status'] != 'clean' and outcome['result'] == 'pass':
                    outcome.update(result='fail', reason='cleanup-incomplete')
                report['scenarios'][name] = outcome
            if outcome['result'] != 'pass':
                break
        else:
            report['status'] = 'pass'
    finally:
        args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
