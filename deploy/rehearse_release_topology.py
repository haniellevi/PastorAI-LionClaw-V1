#!/usr/bin/env python3
"""Ensaio EXCLUSIVAMENTE sintético: próximo release + rollback pela topologia adotada.

Parte do layout que o ``write_layout`` REAL grava (blobs exatos de um commit de
um repositório Git sintético, contrato, override com pin do ID verificado e sem
fonte de build) e executa o ``backend-release.sh`` REAL de cada candidato,
empacotado por ``git archive`` como o workflow. Cria tudo com prefixo aleatório:
legado sintético contido (três serviços Compose + broadcast avulso, ``restart=no``),
Redis e Evolution falsa do projeto legado na rede do legado, projeto permanente.

Transformações do ``deploy/docker-compose.yml`` real, conferidas por contagem:
porta publicada 127.0.0.1:8000 -> porta livre própria (a 8000 do host pertence a
outro processo, que nunca é tocado nem consultado) e tag de build
``pastorai-backend:latest`` -> tag prefixada (não sobrescreve tag compartilhada).
O checker de schema e a aplicação são sintéticos (``/health``, ``/ready`` com
PING ao Redis, workers que saem no SIGTERM): não prova schema, app real, envio
externo nem produção. Nunca baixa imagem; build offline sobre imagem base local.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import initial_transition as it  # noqa: E402
import initial_transition_files as itf  # noqa: E402
import release_topology as rt  # noqa: E402

BASE_IMAGE = 'igreja12-queue-base-local:8fbc14c58e9a'
REDIS_IMAGE = 'redis:7-alpine'
OWNER = 'pastorai.synthetic.owner'
ROLES = rt.SERVICES
GATES = {'ALLOW_REAL_SENDS': 'false', 'ASAAS_BILLING_ENABLED': 'false', 'BREVO_SEND_MODE': 'off',
         'BROADCAST_ASYNC_ENABLED': 'false'}
NOT_PROVEN = [
    'callback-real-da-evolution (Evolution falsa: servidor HTTP sem webhooks; alias backend so conferido '
    'por inspect e pelas guardas, nenhuma entrega Evolution->backend exercitada)',
    'producao (VPS, Supabase, workflow e gates reais nao tocados)',
    'aplicacao-real (uvicorn/workers sinteticos; healthchecks reais do compose executados contra eles)',
    'schema (checker sintetico; compatibilidade coberta por outros testes)',
    'transicao-inicial-completa (o projeto permanente nasce do override do layout, nao do controlador)',
    'promocao-por-digest-ghcr (so modo build; digest coberto por doubles e Compose config)',
    'restartcount-maior-que-zero-do-legado (limitacao anterior do controlador inicial permanece)',
    'reinicio-do-daemon-ou-host',
]

UVICORN = r'''#!/usr/local/bin/python
import http.server, json, os, signal, socket, sys
REV = os.environ.get('PASTORAI_RELEASE_SHA', '')
def redis_ok():
    try:
        with socket.create_connection(('redis', 6379), timeout=2) as s:
            s.sendall(b'PING\r\n')
            return s.recv(16).startswith(b'+PONG')
    except OSError:
        return False
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/health':
            code = 200
        elif path == '/ready':
            code = 503 if os.path.exists('/synthetic/READY_FAIL') or not redis_ok() else 200
        else:
            code = 404
        body = json.dumps({'revision': REV, 'path': path}).encode()
        self.send_response(code)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass
server = http.server.ThreadingHTTPServer(('0.0.0.0', 8000), Handler)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
server.serve_forever()
'''
WORKER = '''import signal, sys, time
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
while True:
    time.sleep(1)
'''
APP = {
    '__init__.py': '', 'main.py': 'app = None\n', 'services/__init__.py': '', 'workers/__init__.py': '',
    'config.py': 'import os\nclass _S:\n    redis_url = os.environ.get("REDIS_URL", "")\n'
                 'def get_settings():\n    return _S()\n',
    'services/worker_health.py': (
        'import socket\nfrom urllib.parse import urlparse\n'
        'def worker_heartbeat_alive(url, name):\n    u = urlparse(url)\n    try:\n'
        '        with socket.create_connection((u.hostname, u.port or 6379), timeout=2) as s:\n'
        '            s.sendall(b"PING\\r\\n")\n            return s.recv(16).startswith(b"+PONG")\n'
        '    except OSError:\n        return False\n'),
    **{f'workers/{w}.py': WORKER for w in ('queue_worker', 'cron_worker', 'broadcast_worker')},
}
DOCKERFILE = f'''FROM {BASE_IMAGE}
ARG PASTORAI_RELEASE_SHA=unknown
LABEL org.opencontainers.image.revision=$PASTORAI_RELEASE_SHA
ENV PASTORAI_RELEASE_SHA=$PASTORAI_RELEASE_SHA PYTHONPATH=/synthetic
COPY --chmod=755 uvicorn /usr/local/bin/uvicorn
COPY synthetic /synthetic
WORKDIR /synthetic
'''
CHECKER = '''import json, os, sys
# SYNTHETIC schema checker: only the manifest handed over by backend-release.sh.
sys.exit(0 if json.loads(os.environ.get("EXPECTED_MIGRATIONS", "null")) == ["0001_synthetic.sql"] else 1)
'''


class Failed(RuntimeError):
    pass


def run(argv, *, check=True, timeout=300, **kwargs):
    done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **kwargs)
    if check and done.returncode != 0:
        raise Failed(f'{argv[:3]} exit {done.returncode}: {done.stderr.strip()[-400:]}')
    return done


def docker(*args, **kwargs):
    return run(['docker', *args], **kwargs).stdout.strip()


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Rehearsal:
    def __init__(self, python):
        self.run_id = uuid.uuid4().hex
        self.prefix = 'pastorai-synth-topo-' + self.run_id[:12]
        self.legacy_project = self.prefix + '-legacy'
        self.project = self.prefix + '-permanent'
        self.tag = self.prefix + '-backend:latest'
        self.port = free_port()
        self.dir = Path(tempfile.mkdtemp(prefix='igreja12-topology-rehearsal-'))
        self.root = self.dir / 'install'
        (self.root / 'releases').mkdir(parents=True)
        self.repo = self.dir / 'repo'
        self.shim = self.dir / 'bin'
        self.shim.mkdir()
        (self.shim / 'python3').write_text(f'#!/bin/sh\nexec {python} "$@"\n')
        (self.shim / 'python3').chmod(0o755)
        self.images, self.checks, self.observations, self.errors, self.shas = [], [], {}, [], []

    def check(self, condition, name):
        if not condition:
            raise Failed('check failed: ' + name)
        self.checks.append(name)

    # -- synthetic Git source (real commits; the workflow packages with git archive) --------
    def git(self, *args):
        env = {'PATH': os.environ['PATH'], 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
               'HOME': str(self.dir)}
        return run(['git', '-C', str(self.repo), '-c', 'user.name=synthetic', '-c', 'user.email=synthetic@invalid',
                    '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', *args], env=env).stdout.strip()

    def compose_source(self):
        text = (HERE / 'docker-compose.yml').read_text()
        port_from, port_to = '"127.0.0.1:8000:8000"', f'"127.0.0.1:{self.port}:8000"'
        if text.count(port_from) != 1 or text.count('image: pastorai-backend:latest') != 4:
            raise Failed('docker-compose.yml shape changed; transformation not applicable')
        return text.replace(port_from, port_to).replace('image: pastorai-backend:latest', f'image: {self.tag}')

    def commit(self, message, *, ready_fail):
        files = {
            'backend/Dockerfile': DOCKERFILE, 'backend/uvicorn': UVICORN,
            'backend/scripts/migrate.py': (HERE.parent / 'backend/scripts/migrate.py').read_text(),
            'backend/migrations/0001_synthetic.sql': '-- synthetic\nSELECT 1;\n',
            'deploy/docker-compose.yml': self.compose_source(), 'deploy/check_backend_schema.py': CHECKER,
            **{f'deploy/{n}': (HERE / n).read_text() for n in ('backend-release.sh', 'release_topology.py',
                                                              'emit_schema_check.py', 'schema_compatibility.py')},
            **{f'backend/synthetic/app/{k}': v for k, v in APP.items()},
            'backend/synthetic/COMMIT': message + '\n',
        }
        for path, body in files.items():
            target = self.repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        (self.repo / 'deploy/backend-release.sh').chmod(0o755)
        fail = self.repo / 'backend/synthetic/READY_FAIL'
        if ready_fail:
            fail.write_text('synthetic readiness failure\n')
        elif fail.exists():
            fail.unlink()
        self.git('add', '-A')
        self.git('commit', '-q', '-m', message)
        sha = self.git('rev-parse', 'HEAD')
        self.shas.append(sha)
        return sha

    def build(self, sha, tag):
        with tempfile.TemporaryDirectory(dir=self.dir) as directory:
            self.extract(sha, Path(directory))
            run(['docker', 'build', '-q', '--network', 'none', '--build-arg', f'PASTORAI_RELEASE_SHA={sha}',
                 '--label', f'{OWNER}={self.run_id}', '-t', tag, str(Path(directory) / 'backend')], timeout=600)
        image = docker('image', 'inspect', '--format', '{{.Id}}', tag)
        self.images.append(image)
        return image

    def extract(self, sha, target):
        archive = self.dir / f'{sha}.tar'
        run(['git', '-C', str(self.repo), 'archive', '--format=tar', '-o', str(archive), sha, 'backend', 'deploy'])
        with tarfile.open(archive) as tar:
            tar.extractall(target, filter='data')
        archive.unlink()

    # -- legacy and support --------------------------------------------------------------
    def legacy(self, image):
        services = {
            'redis': dict(image=REDIS_IMAGE, container_name=f'{self.prefix}-legacy-redis', restart='always',
                          command=['redis-server', '--save', '', '--appendonly', 'no'], pull_policy='never',
                          healthcheck=dict(test=['CMD', 'redis-cli', 'ping'], interval='2s', retries=10)),
            'evolution-api': dict(image=image, container_name=f'{self.prefix}-legacy-evolution', restart='always',
                                  command=['python', '-m', 'http.server', '8080'], pull_policy='never'),
        }
        commands = {'backend': ['uvicorn', 'app.main:app'], 'queue-worker': ['python', '-m', 'app.workers.queue_worker'],
                    'cron-worker': ['python', '-m', 'app.workers.cron_worker']}
        for role, command in commands.items():
            services[role] = dict(image=image, container_name=f'{self.prefix}-legacy-{role}', restart='always',
                                  command=command, pull_policy='never', environment={'REDIS_URL': 'redis://redis:6379/0'})
        for value in services.values():
            value['labels'] = {OWNER: self.run_id}
        path = self.dir / 'legacy-compose.json'
        path.write_text(json.dumps({'name': self.legacy_project, 'services': services}))
        run(['docker', 'compose', '-f', str(path), 'up', '-d', '--wait', '--wait-timeout', '120'], timeout=200)
        self.network = f'{self.legacy_project}_default'
        broadcast = docker('run', '-d', '--name', f'{self.prefix}-legacy-broadcast-worker', '--restart', 'always',
                           '--network', self.network, '--network-alias', 'broadcast-worker',
                           '--label', f'{OWNER}={self.run_id}', image, 'python', '-m', 'app.workers.broadcast_worker')
        ids = {role: docker('ps', '-aq', '--no-trunc', '--filter', f'name=^/{self.prefix}-legacy-{role}$')
               for role in commands}
        ids['broadcast-worker'] = broadcast
        # Contained exactly as the initial transition leaves it: restart=no persisted, then stopped.
        docker('update', '--restart', 'no', *ids.values())
        docker('stop', *ids.values())
        self.legacy_ids = ids
        self.dependency_ids = {name: docker('ps', '-q', '--no-trunc', '--filter', f'name=^/{self.prefix}-legacy-{name}$')
                               for name in ('redis', 'evolution')}

    def snapshot(self, ids):
        rows = json.loads(docker('inspect', *ids.values()))
        return {row['Id']: dict(running=row['State']['Running'], policy=row['HostConfig']['RestartPolicy']['Name'],
                                started=row['State']['StartedAt'], finished=row['State']['FinishedAt'],
                                restarts=row['RestartCount']) for row in rows}

    def project_state(self):
        ids = docker('ps', '-aq', '--no-trunc', '--filter', f'label=com.docker.compose.project={self.project}').split()
        rows = json.loads(docker('inspect', *ids)) if ids else []
        return {row['Config']['Labels'].get('com.docker.compose.service'): dict(
            id=row['Id'], name=row['Name'].lstrip('/'), image=row['Image'], running=row['State']['Running'],
            networks=sorted(row['NetworkSettings']['Networks'])) for row in rows}

    def assert_project(self, image, label):
        state = self.project_state()
        self.check(set(state) == set(ROLES) and len(state) == 4, f'{label}:project-exactly-four-services')
        self.check(all(v['running'] and v['image'] == image for v in state.values()), f'{label}:running-on-image-id')
        self.check(all(v['networks'] == [self.network] for v in state.values()), f'{label}:single-external-network')
        self.check(all(v['name'] == self.contract['containers'][r] for r, v in state.items()), f'{label}:contract-names')
        return state

    def assert_untouched(self, label):
        self.check(self.snapshot(self.legacy_ids) == self.legacy_baseline, f'{label}:legacy-ids-stopped-no-intact')
        self.check(self.snapshot(self.dependency_ids) == self.dependency_baseline, f'{label}:dependencies-intact')
        volumes = docker('volume', 'ls', '-q', '--filter', f'label=com.docker.compose.project={self.project}')
        self.check(volumes == '', f'{label}:no-project-volumes')

    # -- releases ------------------------------------------------------------------------
    def release(self, sha, label):
        target = self.root / 'releases' / sha
        target.mkdir()
        self.extract(sha, target)
        env = {k: v for k, v in os.environ.items() if not k.startswith('DOCKER_')}
        env.update(PATH=f'{self.shim}:{os.environ["PATH"]}', BACKEND_RELEASE_TEST_MODE='1',
                   BACKEND_RELEASE_TEST_ROOT=str(self.root), BACKEND_RELEASE_TEST_CONFIG='configuration.fixture',
                   BACKEND_RELEASE_TEST_PORT=str(self.port))
        started = time.monotonic()
        done = run(['bash', str(target / 'deploy/backend-release.sh'), sha], check=False, timeout=900,
                   cwd=self.root, env=env)
        self.observations[label] = dict(exit=done.returncode, seconds=round(time.monotonic() - started, 1),
                                        stderr=done.stderr.strip().splitlines()[-3:])
        return done

    def assert_rolled_back(self, done, previous, before_ids, label):
        """A real candidate start followed by recovery: not a refusal before effects."""
        self.check(done.returncode != 0 and self.current() == previous, f'{label}:failed-current-unchanged')
        self.check('before restart' not in done.stderr and 'release topology refused' not in done.stderr
                   and 'rollback of code is unhealthy' not in done.stderr and 'human recovery' not in done.stderr,
                   f'{label}:recovered-after-candidate-start')
        after = {r: v['id'] for r, v in self.project_state().items()}
        self.check(set(after) == set(ROLES) and not set(after.values()) & set(before_ids.values()),
                   f'{label}:all-four-recreated')

    def current(self):
        return (self.root / 'current').resolve().name

    def health_revision(self):
        import urllib.request
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/health', timeout=5) as response:
            return json.loads(response.read())['revision']

    def main(self):
        for image in (BASE_IMAGE, REDIS_IMAGE):
            docker('image', 'inspect', image)  # local only; never pulled
        (self.repo).mkdir()
        self.git('init', '-q')
        sha_a = self.commit('A transition candidate', ready_fail=False)
        sha_b = self.commit('B failing readiness', ready_fail=True)
        sha_c = self.commit('C healthy', ready_fail=False)
        sha_d = self.commit('D failing readiness', ready_fail=True)
        legacy_image = self.build(sha_a, self.prefix + '-legacy:synthetic')
        self.legacy(legacy_image)
        self.legacy_baseline = self.snapshot(self.legacy_ids)
        self.dependency_baseline = self.snapshot(self.dependency_ids)
        self.check(all(not v['running'] and v['policy'] == 'no' for v in self.legacy_baseline.values()),
                   'legacy-contained-restart-no')
        image_a = self.build(sha_a, self.prefix + '-transition:a')
        network_id = docker('network', 'inspect', '--format', '{{.Id}}', self.network)
        self.contract = dict(schema=rt.SCHEMA, version=1, project=self.project, legacy_project=self.legacy_project,
                             network=dict(name=self.network, id=network_id),
                             containers={r: f'{self.prefix}-perm-{r}' for r in ROLES}, reserved_legacy=self.legacy_ids)
        # The real layout writer over the exact blobs of commit A (no build source travels).
        files = itf.git_tree(self.repo, sha_a, it.CANDIDATE_PATHSPECS, it.CANDIDATE_BLOBS)
        sql = {p.split('/', 2)[2]: b for p, b in files.items() if p.startswith('backend/migrations/')}
        manifest = itf.migration_manifest(files['backend/scripts/migrate.py'], sql)
        itf.write_layout(self.root, sha_a, files, self.contract, manifest, image_a)
        layout = self.root / 'releases' / sha_a / 'deploy'
        self.check(not (layout.parent / 'backend' / 'Dockerfile').exists()
                   and (layout / 'release_topology.py').exists(), 'layout-has-helper-and-no-build-source')
        (layout / 'configuration.fixture').write_text(''.join(f'{k}={v}\n' for k, v in GATES.items()))
        (layout / 'configuration.fixture').chmod(0o600)
        itf.activate(self.root, sha_a)
        # The permanent project is born from the layout's own maintenance override (no -p, no -f).
        run(['docker', 'compose', 'up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait',
             '--wait-timeout', '180', *ROLES], cwd=layout, timeout=240,
            env={**os.environ, 'PASTORAI_ENV_FILE': 'configuration.fixture'})
        self.assert_project(image_a, 'layout-a')
        self.check(self.health_revision() == sha_a, 'layout-a:health-from-own-port')
        self.assert_untouched('layout-a')

        layout_ids = {r: v['id'] for r, v in self.project_state().items()}
        done = self.release(sha_b, 'release-b-fails-ready')
        self.assert_rolled_back(done, sha_a, layout_ids, 'release-b')
        # The layout has no build source: running image A again proves recovery by the pinned ID.
        self.assert_project(image_a, 'release-b:rollback-to-layout-by-image-id')
        self.check(self.health_revision() == sha_a, 'release-b:health-revision-a')
        b = self.root / 'releases' / sha_b / 'deploy'
        self.check(not any((b / n).exists() for n in ('configuration.fixture', 'release-topology.json',
                                                     'docker-compose.override.yml')), 'release-b:no-candidate-leftovers')
        self.assert_untouched('release-b')

        done = self.release(sha_c, 'release-c-healthy')
        self.check(done.returncode == 0 and self.current() == sha_c, 'release-c:promoted')
        image_c = docker('image', 'inspect', '--format', '{{.Id}}', self.tag)
        self.images.append(image_c)
        self.check(docker('image', 'inspect', '--format',
                          '{{index .Config.Labels "org.opencontainers.image.revision"}}', image_c) == sha_c,
                   'release-c:built-image-revision')
        self.assert_project(image_c, 'release-c')
        self.check(self.health_revision() == sha_c, 'release-c:health-revision-c')
        c = self.root / 'releases' / sha_c / 'deploy'
        self.check(json.loads((c / 'release-topology.json').read_text()) == self.contract, 'release-c:contract-carried')
        model = json.loads(run(['docker', 'compose', 'config', '--format', 'json', '--no-env-resolution'], cwd=c,
                               env={**os.environ, 'PASTORAI_ENV_FILE': 'configuration.fixture'}).stdout)
        rt.check_config(self.contract, model)
        self.check({model['services'][r]['image'] for r in ROLES} == {image_c}, 'release-c:manual-override-pins-id')
        self.assert_untouched('release-c')

        c_ids = {r: v['id'] for r, v in self.project_state().items()}
        done = self.release(sha_d, 'release-d-fails-ready')
        self.assert_rolled_back(done, sha_c, c_ids, 'release-d')
        self.assert_project(image_c, 'release-d:rollback-to-built-predecessor-by-id')
        self.check(self.health_revision() == sha_c, 'release-d:health-revision-c')
        self.assert_untouched('release-d')

        # Physical refusals before any effect: concurrent alias, then a stranger project member.
        before = self.project_state()
        sha_e = self.commit('E healthy, alias conflict', ready_fail=False)
        rogue = docker('run', '-d', '--name', f'{self.prefix}-rogue', '--network', self.network, '--network-alias',
                       'backend', '--label', f'{OWNER}={self.run_id}', legacy_image, 'python', '-m',
                       'app.workers.queue_worker')
        done = self.release(sha_e, 'release-e-alias-conflict')
        self.check(done.returncode != 0 and 'alias-conflict' in done.stderr, 'release-e:alias-conflict-refused')
        self.check(self.project_state() == before and self.current() == sha_c, 'release-e:project-untouched')
        docker('rm', '-f', rogue)
        sha_f = self.commit('F healthy, stranger member', ready_fail=False)
        stranger = docker('create', '--name', f'{self.prefix}-unexpected-backend-copy',
                          '--label', f'com.docker.compose.project={self.project}',
                          '--label', 'com.docker.compose.service=backend', '--label', f'{OWNER}={self.run_id}',
                          legacy_image, 'python', '-m', 'app.workers.queue_worker')
        done = self.release(sha_f, 'release-f-stranger-member')
        self.check(done.returncode != 0 and 'project-foreign-member' in done.stderr, 'release-f:stranger-refused')
        self.check(docker('inspect', '--format', '{{.State.Status}}', stranger) == 'created', 'release-f:stranger-untouched')
        docker('rm', '-f', stranger)
        after = self.project_state()
        self.check(after == before and self.current() == sha_c, 'release-f:project-untouched')
        self.assert_untouched('final')
        retained = docker('image', 'ls', '--format', '{{.Tag}}', self.prefix + '-backend-release').split()
        self.check({sha_a, sha_c} <= set(retained), 'retained-revision-tags-for-recovery')

    def cleanup(self):
        removed = []
        for project in (self.project, self.legacy_project):
            ids = docker('ps', '-aq', '--filter', f'label=com.docker.compose.project={project}', check=False).split()
            if ids:
                docker('rm', '-f', *ids, check=False)
            removed += ids
            volumes = docker('volume', 'ls', '-q', '--filter', f'label=com.docker.compose.project={project}',
                             check=False).split()
            if volumes:
                docker('volume', 'rm', *volumes, check=False)
        owned = docker('ps', '-aq', '--filter', f'label={OWNER}={self.run_id}', check=False).split()
        if owned:
            docker('rm', '-f', *owned, check=False)
        docker('network', 'rm', f'{self.legacy_project}_default', check=False)
        retained = docker('image', 'ls', '--format', '{{.Repository}}:{{.Tag}}',
                          self.prefix + '-backend-release', check=False).split()
        for tag in (self.tag, self.prefix + '-legacy:synthetic', self.prefix + '-transition:a', *retained):
            docker('rmi', tag, check=False)
        for image in set(self.images) | self.revision_images():
            docker('rmi', image, check=False)
        shutil.rmtree(self.dir, ignore_errors=True)
        # Candidates B/D (and any other) built by Compose carry no owner label: they are found
        # by the revision label of this run's own synthetic commits and by the run prefix.
        # Never a global prune.
        images = {i for i in set(self.images) if run(['docker', 'image', 'inspect', i], check=False).returncode == 0}
        images |= self.revision_images()
        images |= set(docker('image', 'ls', '-aq', '--no-trunc', '--filter', f'reference={self.prefix}*',
                             check=False).split())
        left = dict(
            containers=docker('ps', '-aq', '--filter', f'name={self.prefix}', check=False).split()
            + docker('ps', '-aq', '--filter', f'label={OWNER}={self.run_id}', check=False).split(),
            networks=docker('network', 'ls', '-q', '--filter', f'name={self.prefix}', check=False).split(),
            volumes=docker('volume', 'ls', '-q', '--filter', f'name={self.prefix}', check=False).split(),
            images=sorted(images))
        return left

    def revision_images(self):
        found = set()
        for sha in self.shas:
            found |= set(docker('image', 'ls', '-aq', '--no-trunc', '--filter',
                                f'label=org.opencontainers.image.revision={sha}', check=False).split())
        return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--python', default=sys.executable, help='Python 3.13 for backend-release.sh helpers')
    args = parser.parse_args(argv)
    os.umask(0o022)
    rehearsal = Rehearsal(args.python)
    status, error = 'pass', None
    started = time.monotonic()
    try:
        rehearsal.main()
    except (Failed, subprocess.TimeoutExpired, OSError, ValueError, KeyError) as exc:
        status, error = 'fail', f'{type(exc).__name__}: {exc}'
    finally:
        leftovers = rehearsal.cleanup()
    if any(leftovers.values()):
        status = 'fail'
    sources = {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
               for name in ('backend-release.sh', 'release_topology.py', 'rehearse_release_topology.py',
                            'initial_transition_files.py', 'docker-compose.yml')}
    report = dict(status=status, error=error, synthetic=True, production_ready=False, run_id=rehearsal.run_id,
                  source_sha256=sources, synthetic_commits=rehearsal.shas,
                  seconds=round(time.monotonic() - started, 1), port=rehearsal.port, checks=rehearsal.checks,
                  releases=rehearsal.observations, leftovers=leftovers, not_proven=NOT_PROVEN)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(status=status, checks=len(rehearsal.checks), error=error, leftovers=leftovers)))
    return 0 if status == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
