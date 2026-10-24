#!/usr/bin/env python3
"""Ensaio sintético do entrypoint REAL do queue-worker legado de ``07a3f4d``.

Dois subcomandos, ambos sem rede externa e sem alvo existente:

``materialize --repo R --out D``
    Lê do Git, no SHA fixo ``LEGACY_SHA``, só os blobs rastreados
    ``backend/app/**/*.py`` e ``backend/requirements.lock`` (``ls-tree`` +
    ``cat-file``, hash do blob conferido). Nunca usa ``archive``/checkout e
    nunca lê outro caminho. Escreve em ``D`` (precisa não existir).

``run --repo R --legacy-image sha256:... --redis-image sha256:... --report P``
    Exige uma imagem local preparada à parte com o conteúdo de ``D`` em
    ``/opt/legacy`` e as dependências de ``requirements.lock``. Antes de criar
    qualquer recurso, um probe ``--network none`` compara arquivo a arquivo a
    fonte da imagem com o Git e as distribuições com o lock; divergência é
    recusa registrada. Depois, numa rede ``--internal`` própria com Redis
    efêmero, roda ``python -m app.workers.queue_worker`` (sem mock) e prova:
    heartbeat ``ready`` e registro; SIGTERM → saída 0, heartbeat ``stopped``,
    lease e registro removidos; evento enfileirado pelo ``WebhookQueue.enqueue``
    real sobrevive com o worker parado; ``docker start`` do MESMO container →
    novo worker consome o evento deliberadamente ignorado pelo parser real e
    faz ACK; segundo SIGTERM limpo.

Configuração sintética com gates fechados e sem segredos; banco e Evolution
apontam para loopback morto do container. Não prova turno ativo do agente,
ingestão no banco, provedor, nem produção: ``production_ready=false``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from rehearse_legacy_containment import OWNER_LABEL, ROLE_LABEL, SCOPE, SCOPE_LABEL, USER, Refused, Rehearsal

LEGACY_SHA = '07a3f4d9a4fe510cf83fd48d5deaa52dcfbb7e02'
LOCK_PATH = 'backend/requirements.lock'
# Componentes só com identificadores: exclui dotfiles, '..' e qualquer não-.py.
APP_PY = re.compile(r'backend/app/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*\.py')
REQUIRED = frozenset({'app/workers/queue_worker.py', 'requirements.lock'})
# Qualquer componente com "secret" é recusado antes de ler qualquer blob (o SHA fixo não tem nenhum).
PROTECTED = re.compile(r'secret', re.IGNORECASE)
SOURCE_ROOT = '/opt/legacy'
WORKER = 'queue-worker'
ENTRY = ['-m', 'app.workers.queue_worker']
# Chaves do código legado (queue_worker.py / worker_health.py em 07a3f4d).
QUEUE = 'pastorai:webhooks'
REGISTRY = 'pastorai:webhooks:workers'
LEASE = 'pastorai:webhooks:worker-lease:'
PROCESSING = 'pastorai:webhooks:processing:'
HEARTBEAT = 'pastorai:queue-worker:heartbeat:v1'
ALIVE = frozenset({'ready', 'running', 'idle'})
# Evento que o parser real precisa devolver como None (conferido na imagem antes do enqueue).
IGNORED_PAYLOAD = {'event': 'synthetic.rehearsal.ignored', 'data': {}}
# Configuração SINTÉTICA: gates fechados, nenhuma credencial, banco/Evolution em loopback morto.
SYNTHETIC_ENV = {
    'APP_ENV': 'synthetic-rehearsal',
    'ALLOW_REAL_SENDS': 'false',
    'ASAAS_BILLING_ENABLED': 'false',
    'BREVO_SEND_MODE': 'off',
    'BROADCAST_ASYNC_ENABLED': 'false',
    'AGENDA_NOTIFY_ENABLED': 'false',
    'WHATSAPP_SLA_ENABLED': 'false',
    'WHATSAPP_PILOTO_IGREJA_IDS': '',
    'AGENT_TRUSTED_INBOUND_IDENTITY_ENABLED': 'false',
    'REDIS_URL': 'redis://redis:6379/0',
    'DATABASE_URL': 'postgresql+psycopg2://synthetic@127.0.0.1:9/synthetic',
    'EVOLUTION_API_URL': 'http://127.0.0.1:9',
}
# Settings é case-insensitive e lê o ambiente inteiro: a imagem só pode trazer estes nomes.
IMAGE_ENV_ALLOWED = frozenset({
    'PATH', 'LANG', 'LC_ALL', 'GPG_KEY', 'PYTHON_VERSION', 'PYTHON_SHA256', 'PYTHON_PIP_VERSION',
    'PYTHON_SETUPTOOLS_VERSION', 'PYTHON_GET_PIP_URL', 'PYTHON_GET_PIP_SHA256',
    'PYTHONDONTWRITEBYTECODE', 'PYTHONUNBUFFERED', 'VIRTUAL_ENV',
    # Herdados da imagem de runtime preparada; nomes exatos, sem prefixo.
    'PASTORAI_RELEASE_SHA', 'PIP_DISABLE_PIP_VERSION_CHECK', 'PIP_NO_CACHE_DIR',
})
RUNTIME_EXTRAS = frozenset({'pip', 'setuptools', 'wheel'})
GRACE_S = 30      # BRPOP 2 s + join do heartbeat <= 8 s
READY_S = 60
SURVIVE_S = 6     # > 2 x BRPOP_TIMEOUT com o worker parado
NOT_PROVEN = [
    'turno-ativo-do-agente-durante-sigterm',
    'ingestao-no-banco-e-caminho-registered',
    'evolution-provedor-e-envio',
    'sigkill-ou-timeout-do-worker-real',
    'queda-do-redis',
    'entrypoint-compose-de-producao',
    'hash-das-wheels-instaladas (so nome/versao conferidos)',
    'integridade-de-sitecustomize-e-pth-instalados (site-packages nao varrido)',
    'producao',
]


# -- fonte legada --------------------------------------------------------
def git(argv):
    try:
        done = subprocess.run(['git', *argv], capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        done = None
    if done is None or done.returncode:
        raise Refused('git-step')
    return done.stdout


def legacy_sources(repo, git_runner=git):
    """``{caminho relativo a backend/: bytes}`` só dos blobs selecionados de ``LEGACY_SHA``."""
    base = ['-C', str(repo)]
    commit = git_runner([*base, 'rev-parse', '--verify', '--quiet', '--end-of-options',
                         LEGACY_SHA + '^{commit}']).decode().strip()
    if commit != LEGACY_SHA:
        raise Refused('legacy-sha')
    listing = git_runner([*base, 'ls-tree', '-r', '-z', '--full-tree', LEGACY_SHA, '--',
                          'backend/app', LOCK_PATH])
    files = {}
    for entry in filter(None, listing.split(b'\0')):
        meta, _, raw_path = entry.partition(b'\t')
        try:
            mode, kind, oid = meta.decode('ascii').split(' ')
            path = raw_path.decode('utf-8')
        except ValueError:
            raise Refused('source-entry') from None
        if any(PROTECTED.search(part) for part in path.split('/')):
            raise Refused('source-protected-path')
        if path != LOCK_PATH and not APP_PY.fullmatch(path):
            continue  # nunca lido
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise Refused('source-entry-type')
        data = git_runner([*base, 'cat-file', 'blob', oid])
        algo = hashlib.sha1 if len(oid) == 40 else hashlib.sha256
        if algo(b'blob %d\0' % len(data) + data).hexdigest() != oid:
            raise Refused('source-blob-hash')
        files[path.removeprefix('backend/')] = data
    if not REQUIRED <= set(files):
        raise Refused('source-incomplete')
    return files


def manifest(files):
    return {path: hashlib.sha256(data).hexdigest() for path, data in sorted(files.items())}


def manifest_digest(entries):
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()


def materialize(repo, out, git_runner=git):
    files = legacy_sources(repo, git_runner)
    out = Path(out)
    try:
        out.mkdir(mode=0o755)
    except FileExistsError:
        raise Refused('out-exists') from None
    for rel, data in sorted(files.items()):
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
    return manifest(files)


# -- correspondência com requirements.lock -------------------------------
LOCK_LINE = re.compile(r'([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)\s*(?:;\s*(.*?))?\s*\\?\s*')


def canonical(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def lock_python(text):
    found = re.search(r'--python-version (\d+)\.(\d+)', text)
    if not found:
        raise Refused('lock-format')
    return [int(found[1]), int(found[2])]


def lock_entries(text):
    entries = []
    for line in text.splitlines():
        if not line or line[0] in ' \t#':
            continue
        found = LOCK_LINE.fullmatch(line)
        if not found:
            raise Refused('lock-format')
        entries.append([canonical(found[1]), found[2], found[3] or None])
    if not entries:
        raise Refused('lock-format')
    return entries


def runtime_mismatch(lock_text, observed):
    """Diferenças (só nomes/versões públicos) entre o runtime observado e o lock."""
    entries = lock_entries(lock_text)
    applicable = observed.get('applicable') or {}
    expected = {n: v for n, v, m in entries if m is None or applicable.get(m) is True}
    dists = observed.get('dists') or {}
    problems = dict(
        python=None if observed.get('python') == lock_python(lock_text) else observed.get('python'),
        unevaluated_markers=sorted({m for _, _, m in entries if m and not isinstance(applicable.get(m), bool)}),
        missing=sorted(n for n in expected if n not in dists),
        wrong_version=sorted(n for n in expected if n in dists and dists[n] != expected[n]),
        extra=sorted(set(dists) - set(expected) - RUNTIME_EXTRAS),
        duplicates=sorted(observed.get('duplicates') or []),
    )
    return {key: value for key, value in problems.items() if value}


# Enumera só metadados (scandir/lstat); qualquer caminho fora do manifesto, link ou não
# regular é rejeitado sem abrir. Só abre arquivos aprovados, e só se nada foi rejeitado.
RUNTIME_PROBE = r'''
import hashlib, json, os, re, stat, sys
from importlib import metadata
root, markers, expected = sys.argv[1], json.loads(sys.argv[2]), set(json.loads(sys.argv[3]))
parents = {'/'.join(p.split('/')[:i]) for p in expected for i in range(1, p.count('/') + 1)}
approved, rejected = set(), []
def unreadable(error):  # fail-closed: diretório não listável nunca é pulado em silêncio
    rejected.append('unreadable:' + os.path.relpath(error.filename or root, root))
for top, dirs, names in os.walk(root, onerror=unreadable):
    for name in list(dirs):
        rel = os.path.relpath(os.path.join(top, name), root)
        if rel not in parents or not stat.S_ISDIR(os.lstat(os.path.join(top, name)).st_mode):
            rejected.append(rel)
            dirs.remove(name)
    for name in names:
        rel = os.path.relpath(os.path.join(top, name), root)
        if rel in expected and stat.S_ISREG(os.lstat(os.path.join(top, name)).st_mode):
            approved.add(rel)
        else:
            rejected.append(rel)
files = {}
if not rejected:
    for rel in sorted(approved):
        fd = os.open(os.path.join(root, rel), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as handle:
            files[rel] = hashlib.sha256(handle.read()).hexdigest()
applicable = {}
if markers:
    try:
        from packaging.markers import Marker
    except ImportError:
        from pip._vendor.packaging.markers import Marker
    applicable = {m: Marker(m).evaluate() for m in markers}
dists, dups = {}, set()
for dist in metadata.distributions():
    name = re.sub(r'[-_.]+', '-', dist.metadata['Name']).lower()
    if name in dists:  # mesmo nome duas vezes é ambíguo, ainda que na mesma versão
        dups.add(name)
    dists[name] = dist.version
print(json.dumps(dict(python=list(sys.version_info[:2]), files=files, rejected=sorted(rejected),
                      missing=sorted(expected - approved), dists=dists, duplicates=sorted(dups),
                      applicable=applicable), sort_keys=True))
'''

ENQUEUE_PROBE = r'''
import json, sys
from app.domain.conversations import parse_message_event
from app.workers.queue_worker import WebhookQueue
payload = json.loads(sys.argv[1])
if parse_message_event(payload) is not None:
    print('not-ignored')
else:
    WebhookQueue().enqueue(payload)
    print('enqueued')
'''


# -- ensaio ---------------------------------------------------------------
class QueueRehearsal(Rehearsal):
    """Reusa da contenção: guarda local, ledger, Redis próprio, espera de saída e limpeza."""

    def __init__(self, *, legacy_image, redis_image, files, **kwargs):
        super().__init__(worker_image=legacy_image, redis_image=redis_image, **kwargs)
        self.prefix = 'pastorai-synthetic-legacy-queue-' + self.run_id[:12]
        self.expected = manifest(files)
        self.lock_text = files['requirements.lock'].decode('utf-8')
        self.image_env: set[str] = set()
        self.checks: list[str] = []
        self.mismatch: dict = {}
        self.phase = 'preflight'

    def _image(self, image):
        try:
            data = json.loads(self.docker('image', 'inspect', image))[0]
        except (Refused, ValueError, IndexError):
            data = {}
        if data.get('Id') != image:
            raise Refused('image-not-local-immutable')
        return data.get('Config') or {}

    def _legacy_argv(self, role, network, env):
        flags = [part for name, value in sorted(env.items()) for part in ('--env', f'{name}={value}')]
        return ['run', '-d', '--pull', 'never', '--restart', 'no', '--network', network,
                '--entrypoint', 'python', '--user', USER, '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--no-healthcheck', '--pids-limit', '256',
                '--workdir', SOURCE_ROOT, '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m',
                *self.labels(role), *flags, self.images['worker']]

    def legacy_probe(self, python_args, *, network, env, refusal):
        """Container efêmero e registrado da imagem legada; devolve só a última linha do stdout."""
        identifier = self._record('containers', self.docker(
            *self._legacy_argv('probe', network, env), *python_args))
        try:
            status = self.docker('wait', identifier).strip()
            output = self.docker('logs', identifier).strip().splitlines()
        finally:
            self.docker('rm', '-f', '-v', identifier)
        if status != '0' or not output:
            raise Refused(refusal)
        return output[-1]

    def preflight(self):
        """Antes de qualquer rede ou serviço: imagens, fonte exata e runtime do lock."""
        self.guard_local()
        self._image(self.images['redis'])
        config = self._image(self.images['worker'])
        self.image_env = {item.split('=', 1)[0] for item in config.get('Env') or []}
        if not self.image_env <= IMAGE_ENV_ALLOWED:
            self.mismatch = dict(image_env=sorted(self.image_env - IMAGE_ENV_ALLOWED))
            raise Refused('image-env')
        if config.get('Volumes'):
            raise Refused('image-volumes')
        markers = sorted({m for _, _, m in lock_entries(self.lock_text) if m})
        observed = json.loads(self.legacy_probe(
            ['-I', '-c', RUNTIME_PROBE, SOURCE_ROOT, json.dumps(markers), json.dumps(sorted(self.expected))],
            network='none', env={}, refusal='runtime-probe'))
        if observed.get('rejected') or observed.get('missing') or observed.get('files') != self.expected:
            self.mismatch = dict(rejected=observed.get('rejected') or [], missing=observed.get('missing') or [],
                                 content=not observed.get('rejected') and not observed.get('missing'))
            raise Refused('source-mismatch')
        self.mismatch = runtime_mismatch(self.lock_text, observed)
        if self.mismatch:
            raise Refused('runtime-mismatch')
        self.checks += ['legacy-source-exact-git-blobs-07a3f4d (sem .env no workdir)',
                        'runtime-matches-requirements.lock']

    def create_support(self):
        self.phase = 'running'
        self.network = self._record('networks', self.docker(
            'network', 'create', '--internal', '--label', f'{OWNER_LABEL}={self.run_id}',
            '--label', f'{SCOPE_LABEL}={SCOPE}', self.prefix))
        self.ids['redis'] = self.start_container('redis')
        self._until(self._redis_ready, 'redis-readiness')
        if self.keys():
            raise Refused('redis-not-empty')

    def keys(self):
        # Redis próprio e descartável: o conjunto inteiro, não só o prefixo legado.
        return set(self.redis('KEYS', '*').split())

    def start_worker(self):
        self.ids[WORKER] = self._record('containers', self.docker(
            *self._legacy_argv(WORKER, self.network, SYNTHETIC_ENV)[:-1],
            '--name', f'{self.prefix}-{WORKER}', self.images['worker'], *ENTRY))

    def check_worker(self, *, running):
        """Conjunto exato (Redis + worker), identidade, entrypoint real, isolamento e gates."""
        self.guard_local()
        owned = set(self.docker('ps', '-aq', '--no-trunc', '--filter', f'label={OWNER_LABEL}={self.run_id}').split())
        if owned != {self.ids['redis'], self.ids[WORKER]}:
            raise Refused('unexpected-container')
        self._validate_one('redis', running=True)
        data = self.inspect(self.ids[WORKER])
        config, host = data.get('Config') or {}, data.get('HostConfig') or {}
        labels = config.get('Labels') or {}
        if (labels.get(OWNER_LABEL) != self.run_id or labels.get(ROLE_LABEL) != WORKER
                or labels.get(SCOPE_LABEL) != SCOPE):
            raise Refused('ownership')
        if data.get('Id') != self.ids[WORKER] or data.get('Image') != self.images['worker']:
            raise Refused('identity')
        if (data.get('Path') != 'python' or data.get('Args') != ENTRY or config.get('Entrypoint') != ['python']
                or config.get('Cmd') != ENTRY or config.get('User') != USER
                or config.get('WorkingDir') != SOURCE_ROOT):
            raise Refused('entrypoint')
        ports = (data.get('NetworkSettings') or {}).get('Ports') or {}
        if (host.get('PortBindings') or host.get('PublishAllPorts') or host.get('Privileged')
                or host.get('Binds') or data.get('Mounts') or any(ports.values())
                or not host.get('ReadonlyRootfs')):
            raise Refused('host-exposure')
        networks = (data.get('NetworkSettings') or {}).get('Networks') or {}
        if host.get('NetworkMode') != self.network or set(networks) != {self.prefix}:
            raise Refused('network')
        env = dict(item.split('=', 1) for item in config.get('Env') or [] if '=' in item)
        if set(env) != self.image_env | set(SYNTHETIC_ENV) or any(env[k] != v for k, v in SYNTHETIC_ENV.items()):
            raise Refused('gate-config-changed')
        state = data.get('State') or {}
        if bool(state.get('Running')) != running or data.get('RestartCount', 0):
            raise Refused('unexpected-state')
        network = json.loads(self.docker('network', 'inspect', self.network))[0]
        if not network.get('Internal') or (network.get('Labels') or {}).get(OWNER_LABEL) != self.run_id:
            raise Refused('network')
        expected = {self.ids['redis'], *([self.ids[WORKER]] if running else [])}
        if set(network.get('Containers') or {}) != expected:
            raise Refused('unexpected-container')

    def wait_ready(self, previous):
        """Novo worker_id registrado com lease própria e heartbeat vivo; recusa se o processo sair."""
        limit = self.clock() + READY_S
        while True:
            if not (self.inspect(self.ids[WORKER]).get('State') or {}).get('Running'):
                raise Refused('worker-exited-before-ready')
            members = set(self.redis('SMEMBERS', REGISTRY).split())
            if len(members) == 1 and not members & previous and self.redis('GET', HEARTBEAT) in ALIVE:
                worker_id = members.pop()
                if self.redis('GET', LEASE + worker_id) != worker_id:
                    raise Refused('lease')
                self.check_worker(running=True)
                return worker_id
            if self.clock() >= limit:
                raise Refused('readiness-timeout')
            self.sleep(0.2)

    def stop_worker(self):
        """SIGTERM sem SIGKILL; saída 0; heartbeat ``stopped``; nada do worker sobra no Redis."""
        self.check_worker(running=True)
        self.docker('kill', '--signal', 'SIGTERM', self.ids[WORKER])
        self._await_exit(WORKER, GRACE_S)
        if self.redis('GET', HEARTBEAT) != 'stopped':
            raise Refused('heartbeat-not-stopped')
        if self.keys() - {HEARTBEAT}:
            raise Refused('not-deregistered')
        self.check_worker(running=False)


def rehearse(r):
    r.preflight()
    r.create_support()
    r.start_worker()
    first = r.wait_ready(set())
    r.checks.append('real-entrypoint-ready-heartbeat-lease-registry')
    r.stop_worker()
    r.checks.append('sigterm-exit-0-heartbeat-stopped-lease-and-registry-removed')

    outcome = r.legacy_probe(['-c', ENQUEUE_PROBE, json.dumps(IGNORED_PAYLOAD)], network=r.network,
                             env=SYNTHETIC_ENV, refusal='enqueue-probe')
    if outcome != 'enqueued':
        raise Refused('ignored-payload')
    pending = r.redis('LRANGE', QUEUE, '0', '-1').splitlines()
    envelope = json.loads(pending[0]) if len(pending) == 1 else {}
    if envelope.get('payload') != IGNORED_PAYLOAD or envelope.get('attempts') != 0:
        raise Refused('enqueue-envelope')
    r.sleep(SURVIVE_S)
    if r.redis('LRANGE', QUEUE, '0', '-1').splitlines() != pending or r.keys() - {HEARTBEAT} != {QUEUE}:
        raise Refused('pending-lost-while-stopped')
    r.check_worker(running=False)
    r.checks.append('real-webhookqueue-enqueue-of-parser-ignored-event-survives-while-stopped')

    r.docker('start', r.ids[WORKER])
    second = r.wait_ready({first})
    done = {HEARTBEAT, REGISTRY, LEASE + second}
    allowed = done | {QUEUE, PROCESSING + second}
    limit = r.clock() + READY_S
    while (found := r.keys()) != done:
        # Retry, dead-letter, marcador de idempotência ou recovery = evento não ignorado.
        if found - allowed:
            raise Refused('unexpected-queue-state')
        if r.clock() >= limit:
            raise Refused('ignored-event-not-acked')
        r.sleep(0.2)
    if r.redis('GET', HEARTBEAT) not in ALIVE:
        raise Refused('heartbeat-not-alive')
    # Defesa adicional (o claim do legado já é BRPOPLPUSH atômico): o estado pós-ACK se mantém.
    r.sleep(SURVIVE_S)
    if (r.keys() != done or r.redis('GET', LEASE + second) != second
            or set(r.redis('SMEMBERS', REGISTRY).split()) != {second}):
        raise Refused('unstable-after-ack')
    r.check_worker(running=True)
    r.checks.append('restart-same-container-new-worker-id-consumed-and-acked-ignored-event')
    r.stop_worker()
    r.checks.append('second-sigterm-exit-0-heartbeat-stopped-deregistered')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    mat = sub.add_parser('materialize')
    mat.add_argument('--repo', type=Path, required=True)
    mat.add_argument('--out', type=Path, required=True)
    reh = sub.add_parser('run')
    reh.add_argument('--repo', type=Path, required=True)
    reh.add_argument('--legacy-image', required=True, help='ID local sha256:... (fonte em /opt/legacy + lock)')
    reh.add_argument('--redis-image', required=True, help='ID local sha256:... com redis-server >= 6.2')
    reh.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'materialize':
        try:
            entries = materialize(args.repo, args.out)
        except Refused as exc:
            print(json.dumps(dict(status='refused', reason=str(exc))))
            return 1
        print(json.dumps(dict(status='ok', legacy_sha=LEGACY_SHA, files=len(entries),
                              manifest_sha256=manifest_digest(entries))))
        return 0

    report = dict(kind='synthetic-legacy-queue-entrypoint-rehearsal', status='fail', production_ready=False,
                  legacy_sha=LEGACY_SHA, entrypoint='python ' + ' '.join(ENTRY),
                  scope='processo real do queue-worker legado, Redis efemero, evento ignorado; sem banco/provedor',
                  not_proven=NOT_PROVEN, images=dict(legacy=args.legacy_image, redis=args.redis_image),
                  checks=[])
    rehearsal = None
    try:
        files = legacy_sources(args.repo)
        report['source'] = dict(files=len(files), manifest_sha256=manifest_digest(manifest(files)))
        rehearsal = QueueRehearsal(legacy_image=args.legacy_image, redis_image=args.redis_image, files=files)
        rehearse(rehearsal)
        report.update(status='pass', reason=None)
    except Refused as exc:
        preflight = rehearsal is None or rehearsal.phase == 'preflight'
        report.update(status='refused' if preflight else 'fail', reason=str(exc))
    except KeyboardInterrupt:
        report['reason'] = 'interrupted'
    except OSError:
        report['reason'] = 'os-error'  # código fixo; sem caminho nem mensagem do sistema
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        report['reason'] = 'unexpected-output'
    finally:
        if rehearsal is not None:
            report.update(checks=rehearsal.checks, mismatch=rehearsal.mismatch, cleanup=rehearsal.cleanup())
            if report['cleanup']['status'] != 'clean' and report['status'] == 'pass':
                report.update(status='fail', reason='cleanup-incomplete')
        args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
