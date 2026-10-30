"""Candidate release layout and the A9 held start of the first transition.

``write_candidate_release`` writes ``<release_root>/<sha>`` (configured root,
e.g. ``/opt/pastorai-releases``) from the exact package blobs of ``sha`` plus
``deploy/release-topology.json``, reusing initial_transition_files. The
package identity (``release-manifest.json`` digest of package_backend_release)
and the migration manifest are checked first; an existing release is verified,
never overwritten.

``CandidatePort`` builds every Docker argv itself and runs it through an
injected runner (``(argv, *, timeout, max_output) -> (rc, stdout)``):

* ``create_held``: ONE ``docker compose ... up --no-start --no-deps`` for the four
  services of the candidate project, with an extra hold file forcing
  ``restart: "no"``; nothing is started, no dependency is touched;
* ``start_backend``: ``docker start`` of the backend ID only, after a fresh
  inspect proves that ID is this spec's backend (image, revision, project,
  service, name, network, closed gates) and still held;
* ``smoke``: same identity check plus running, then a bounded /health + /ready
  probe executed inside the backend, printing only status codes and fixed flags;
* ``inspect``: restricted projection (gates by name only, never full Env).

There is no operation to start a consumer, change a gate, open ingress, remove
or recreate a container: A10 is a separate, not implemented step. Every call is
preceded by a daemon identity check. Compatibility with a real Docker
CLI/Compose is unverified; tests use fixtures only.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from first_transition_adapter import ROLES
from first_transition_host_driver import (DAEMON, HEX64, IMAGE, INFO_ARGV, MANDATORY_GATES, NETWORK_NAME, STARTED,
                                          STATUSES, PopenRunner, _absolute, _attempt, _lines, _tail,
                                          inspect_template)
from initial_transition_files import migration_manifest, no_symlink, write_release
from initial_transition_ops import Refused, require
import package_backend_release
import release_topology

CONSUMERS = ('queue-worker', 'cron-worker', 'broadcast-worker')
ZERO_STARTED = '0001-01-01T00:00:00Z'
# Closed value of each gate (backend/app/config.py defaults); absence keeps the closed default.
CLOSED_GATES = {'ALLOW_REAL_SENDS': 'false', 'ASAAS_BILLING_ENABLED': 'false', 'BREVO_SEND_MODE': 'off',
                'BROADCAST_ASYNC_ENABLED': 'false'}
CANDIDATE_TEMPLATE = '[{{json .Name}},' + inspect_template(MANDATORY_GATES)[1:]
HOLD_OVERRIDE = ('# A9 hold: candidate containers are created with restart "no" and never started here.\n'
                 '{"services": {' + ', '.join(f'"{r}": {{"restart": "no"}}' for r in ROLES) + '}}\n')
LIMITS = dict(info=256, compose=64 * 1024, ps=4096, inspect=64 * 1024, effect=256, smoke=1024)
PROJECT_LABEL = 'com.docker.compose.project'
SMOKE_PROBE = r'''
import json, sys, time, urllib.error, urllib.request
limit = time.monotonic() + float(sys.argv[1])
def get(path):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000' + path, timeout=5) as response:
            return response.status, json.loads(response.read(65536) or b'null')
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (OSError, ValueError):
        return None, None
while True:
    health, body = get('/health')
    ready, report = get('/ready') if health == 200 else (None, None)
    report = report if isinstance(report, dict) else {}
    required = report.get('required') if isinstance(report.get('required'), dict) else {}
    result = {'health': health, 'health_ok': isinstance(body, dict) and body.get('status') == 'ok',
              'ready': ready, 'required_ok': bool(required) and all(v == 'ok' for v in required.values()),
              'ready_status': report.get('status') if report.get('status') in ('ready', 'degraded', 'not_ready') else None}
    if (result['health_ok'] and ready == 200 and result['required_ok']) or time.monotonic() >= limit:
        break
    time.sleep(1)
print(json.dumps(result, sort_keys=True))
'''
SMOKE_KEYS = frozenset({'health', 'health_ok', 'ready', 'required_ok', 'ready_status'})


@dataclass(frozen=True)
class CandidateSpec:
    """Public candidate scope from configuration; no secret, only the private config PATH."""
    sha: str
    image: str
    project: str
    containers: tuple
    network_id: str
    network_name: str
    release_root: str
    hold_override: str
    env_file: str
    daemon_id: str
    smoke_seconds: int = 60

    def validated(self):
        names = dict(self.containers) if isinstance(self.containers, tuple) else {}
        require(isinstance(self.sha, str) and re.fullmatch('[0-9a-f]{40}', self.sha)
                and isinstance(self.image, str) and IMAGE.fullmatch(self.image)
                and isinstance(self.project, str) and release_topology.PROJECT.fullmatch(self.project)
                and self.project != release_topology.BASE_PROJECT
                and set(names) == set(ROLES) and len(names) == len(self.containers)
                and all(isinstance(v, str) and release_topology.CONTAINER.fullmatch(v) for v in names.values())
                and len(set(names.values())) == 4
                and isinstance(self.network_id, str) and HEX64.fullmatch(self.network_id)
                and isinstance(self.network_name, str) and NETWORK_NAME.fullmatch(self.network_name)
                and all(_absolute(p) for p in (self.release_root, self.hold_override, self.env_file))
                and isinstance(self.daemon_id, str) and DAEMON.fullmatch(self.daemon_id)
                and type(self.smoke_seconds) is int and 5 <= self.smoke_seconds <= 50, 'candidate-spec')
        return self

    @property
    def deploy_dir(self):
        return f'{self.release_root}/{self.sha}/deploy'

    def names(self):
        return dict(self.containers)

    def compose_argv(self):
        deploy = self.deploy_dir
        return ('docker', 'compose', '--project-name', self.project, '--project-directory', deploy,
                '--file', deploy + '/docker-compose.yml', '--file', deploy + '/docker-compose.override.yml',
                '--file', self.hold_override, 'up', '--no-start', '--no-deps', '--no-build', '--no-recreate',
                '--pull', 'never', *ROLES)

    def ps_argv(self):
        return ('docker', 'ps', '--all', '--quiet', '--no-trunc', '--filter', f'label={PROJECT_LABEL}={self.project}')

    def smoke_argv(self, backend_id):
        return ('docker', 'exec', backend_id, 'python', '-I', '-c', SMOKE_PROBE, str(self.smoke_seconds))


def topology_contract(spec, manifest):
    """Public release topology: candidate project/names, existing network, contained legacy IDs."""
    return dict(schema=release_topology.SCHEMA, version=release_topology.VERSION, project=spec.project,
                legacy_project=manifest.legacy_project, network=dict(name=spec.network_name, id=manifest.network_id),
                containers=spec.names(), reserved_legacy=dict(manifest.service_ids))


def write_candidate_release(repo, spec, manifest, *, package_manifest_sha256, migrations, git=None):
    """Exact package blobs of ``spec.sha`` -> ``<release_root>/<sha>``; returns the file count."""
    spec = spec.validated()
    require(isinstance(package_manifest_sha256, str) and HEX64.fullmatch(package_manifest_sha256),
            'package-identity-missing')
    files = package_backend_release.source_files(repo, spec.sha, git)
    require(hashlib.sha256(package_backend_release.release_manifest(spec.sha, files)).hexdigest()
            == package_manifest_sha256, 'package-identity-mismatch')
    sql = {p.split('/', 2)[2]: b for p, b in files.items() if re.fullmatch(r'backend/migrations/[^/]+\.sql', p)}
    names = migration_manifest(files['backend/scripts/migrate.py'], sql)
    require(list(names) == list(migrations), 'layout-migrations-differ-from-plan')
    return write_release(spec.release_root, spec.sha, files, topology_contract(spec, manifest), names, spec.image)


def write_hold_override(spec):
    """Exclusive creation of the public hold file; an existing file must be identical."""
    path = no_symlink(Path(spec.hold_override))
    data = HOLD_OVERRIDE.encode()
    if os.path.lexists(path):
        require(stat.S_ISREG(os.lstat(path).st_mode) and path.read_bytes() == data, 'candidate-hold-mismatch')
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)


class CandidateRunner(PopenRunner):
    """PopenRunner whose allowlist is exactly the argv this spec's CandidatePort builds."""

    def __init__(self, spec, **kwargs):
        self.spec = spec.validated()
        super().__init__(**kwargs)

    def _allowed(self, argv):
        if argv in (INFO_ARGV, self.spec.compose_argv(), self.spec.ps_argv()):
            return True
        if len(argv) == 3 and argv[:2] == ('docker', 'start'):
            return HEX64.fullmatch(argv[2]) is not None
        if len(argv) == 8 and HEX64.fullmatch(argv[2]):
            return argv == self.spec.smoke_argv(argv[2])
        return (6 < len(argv) <= 10 and argv[:6] == ('docker', 'inspect', '--type', 'container', '--format',
                                                     CANDIDATE_TEMPLATE)
                and all(HEX64.fullmatch(i) for i in argv[6:]) and len(set(argv[6:])) == len(argv[6:]))

    def _env(self):
        # Path of the private configuration only; Compose reads it, this process never does.
        return {**super()._env(), 'PASTORAI_ENV_FILE': self.spec.env_file}


class CandidatePort:
    def __init__(self, spec, *, runner):
        require(isinstance(spec, CandidateSpec), 'candidate-spec')
        require(callable(runner), 'candidate-runner')
        self.spec, self.runner = spec.validated(), runner

    def _run(self, argv, timeout, limit):
        outcome = None
        try:
            result = self.runner(argv, timeout=timeout, max_output=limit)
        except TimeoutError:
            outcome = 'candidate-timeout'
        except Exception:
            outcome = 'candidate-runner-failed'
        require(outcome is None, outcome)
        require(isinstance(result, tuple) and len(result) == 2 and type(result[0]) is int
                and type(result[1]) is bytes and len(result[1]) <= limit, 'candidate-runner-failed')
        return result

    def _daemon(self):
        rc, out = self._run(INFO_ARGV, 10, LIMITS['info'])
        ok, value = _attempt(_lines, out)
        require(rc == 0 and ok and value == [self.spec.daemon_id], 'candidate-daemon-mismatch')

    def project_ids(self):
        self._daemon()
        rc, out = self._run(self.spec.ps_argv(), 10, LIMITS['ps'])
        ok, text = _attempt(bytes.decode, out, 'ascii')
        require(rc == 0 and ok and (text == '' or text.endswith('\n')), 'candidate-ps-failed')
        ids = text.split()
        require(all(HEX64.fullmatch(i) for i in ids) and len(set(ids)) == len(ids), 'candidate-ps-failed')
        return tuple(sorted(ids))

    def create_held(self):
        self._daemon()
        rc, _ = self._run(self.spec.compose_argv(), 60, LIMITS['compose'])
        require(rc == 0, 'candidate-create-failed')

    def inspect(self, ids):
        require(isinstance(ids, (tuple, list)) and 1 <= len(ids) <= 4
                and all(isinstance(i, str) and HEX64.fullmatch(i) for i in ids), 'candidate-ids')
        self._daemon()
        rc, out = self._run(('docker', 'inspect', '--type', 'container', '--format', CANDIDATE_TEMPLATE, *ids),
                            10, LIMITS['inspect'])
        require(rc == 0, 'candidate-inspect-failed')
        ok, rows = _attempt(_lines, out)
        require(ok and all(isinstance(r, list) and len(r) == 19 for r in rows)
                and [r[1] for r in rows] == list(ids), 'candidate-inspect-malformed')
        return {row[1]: self._row(row) for row in rows}

    @staticmethod
    def _row(row):
        (name, ident, image, project, service, revision, status, running, paused, restarting, exit_code, started,
         health, restarts, policy, _mode, gates, mounts, networks) = row
        require(isinstance(name, str) and name.startswith('/') and isinstance(image, str)
                and isinstance(status, str) and status in STATUSES and type(running) is bool
                and running == (status == 'running') and paused is False and restarting is False
                and type(exit_code) is int and isinstance(started, str) and STARTED.fullmatch(started)
                and (health is None or isinstance(health, str))
                and type(restarts) is int and restarts >= 0 and isinstance(policy, str),
                'candidate-inspect-state')
        gates = _tail(gates, 'candidate-inspect-gates')
        require(all(isinstance(g, str) and '=' in g for g in gates), 'candidate-inspect-gates')
        values = dict(g.split('=', 1) for g in gates)
        require(len(values) == len(gates) and set(values) <= set(MANDATORY_GATES), 'candidate-inspect-gates')
        networks = _tail(networks, 'candidate-inspect-networks')
        require(all(isinstance(n, list) and len(n) == 3 and isinstance(n[2], str) for n in networks),
                'candidate-inspect-networks')
        _tail(mounts, 'candidate-inspect-mounts')
        labels = [None if v in (None, '') else v for v in (project, service, revision)]
        return dict(id=ident, name=name[1:], image=image, project=labels[0], service=labels[1], revision=labels[2],
                    status=status, running=running, exit_code=exit_code, started=started, health=health,
                    restart_count=restarts, restart_policy=policy or 'no', gates=values,
                    networks=sorted(n[2] for n in networks))

    def _backend(self, backend_id):
        """Fresh inspect of the given ID: it must be THIS spec's backend (image, project, name, network, gates)."""
        require(isinstance(backend_id, str) and HEX64.fullmatch(backend_id), 'candidate-ids')
        state = self.inspect((backend_id,))[backend_id]
        check_identity(self.spec, 'backend', state)
        return state

    def start_backend(self, backend_id):
        # A consumer, a foreign project or a foreign image refuses before any start is issued.
        check_held(self._backend(backend_id), code='candidate-backend-not-held')
        self._daemon()
        rc, out = self._run(('docker', 'start', backend_id), 30, LIMITS['effect'])
        require(rc == 0 and out == (backend_id + '\n').encode(), 'candidate-start-receipt')

    def smoke(self, backend_id):
        check_backend_running(self._backend(backend_id))
        self._daemon()
        rc, out = self._run(self.spec.smoke_argv(backend_id), self.spec.smoke_seconds + 10, LIMITS['smoke'])
        ok, value = _attempt(_lines, out)
        require(rc == 0 and ok and len(value) == 1 and isinstance(value[0], dict)
                and set(value[0]) == SMOKE_KEYS, 'candidate-smoke-malformed')
        result = value[0]
        require(result['health'] == 200 and result['health_ok'] is True, 'candidate-health-failed')
        require(result['ready'] == 200 and result['required_ok'] is True
                and result['ready_status'] in ('ready', 'degraded'), 'candidate-ready-failed')
        return dict(health=200, ready=200, ready_status=result['ready_status'])


def check_identity(spec, role, state):
    """Pinned image/revision, own project/service/name, single network, every gate closed."""
    require(state['image'] == spec.image and state['revision'] == spec.sha, 'candidate-image-mismatch')
    require(state['project'] == spec.project and state['service'] == role
            and state['name'] == spec.names()[role], 'candidate-identity-mismatch')
    require(state['networks'] == [spec.network_id], 'candidate-network-mismatch')
    require(all(state['gates'].get(g, CLOSED_GATES[g]) == CLOSED_GATES[g] for g in MANDATORY_GATES),
            'candidate-gate-open')


def check_held(state, created=None, *, code='candidate-consumer-not-held'):
    """Created, never started, restart=no; unchanged since its creation receipt when given."""
    require(state['status'] == 'created' and state['running'] is False and state['restart_count'] == 0
            and state['started'] == ZERO_STARTED and state['restart_policy'] == 'no', code)
    if created is not None:
        require(state['started'] == created['started'] and state['restart_count'] == created['restart_count'], code)


def check_backend_running(state, started=None):
    require(state['status'] == 'running' and state['running'] is True and state['restart_count'] == 0
            and state['started'] != ZERO_STARTED and state['restart_policy'] == 'no', 'candidate-backend-not-running')
    if started is not None:
        require(state['started'] == started, 'candidate-backend-restarted')
