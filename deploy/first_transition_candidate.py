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
* ``inspect``: restricted projection (gates by name only, never full Env), bracketed
  by fresh network lookups binding both its full ID and its configured name.

There is no operation to start a consumer, change a gate, open ingress, remove
or recreate a container: A10 is a separate, not implemented step. Every call is
preceded by a daemon identity check. A never-started container may expose network
intent without an effective NetworkID; only that held state can use the freshly
verified name/ID binding. A running backend always requires the effective ID.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import parse_qsl, unquote, urlsplit

from first_transition_adapter import ROLES
from first_transition_host_driver import (DAEMON, HEX64, IMAGE, INFO_ARGV, MANDATORY_GATES, NETWORK_NAME, NETWORK_TEMPLATE, STARTED,
                                          STATUSES, PopenRunner, _absolute, _attempt, _lines, _tail,
                                          inspect_template)
from initial_transition_files import inventory, layout_files, migration_manifest, no_symlink, read_regular, write_release
from initial_transition_ops import Refused, require
import package_backend_release
import release_topology

CONSUMERS = ('queue-worker', 'cron-worker', 'broadcast-worker')
ZERO_STARTED = '0001-01-01T00:00:00Z'
# Closed value of each gate (backend/app/config.py defaults); absence keeps the closed default.
CLOSED_GATES = {'ALLOW_REAL_SENDS': 'false', 'ASAAS_BILLING_ENABLED': 'false', 'BREVO_SEND_MODE': 'off',
                'BROADCAST_ASYNC_ENABLED': 'false'}
CANDIDATE_TEMPLATE = '[{{json .Name}},' + inspect_template(MANDATORY_GATES)[1:]
# Private projection is consumed only in memory; never put it in candidate states or receipts.
DATABASE_NAMES = ('DATABASE_URL', 'AGENT_RUNTIME_DATABASE_URL', 'PRIVATE_STORAGE_DATABASE_URL',
                  'PRIVATE_SEND_DATABASE_URL', 'PRIVATE_SUMMARY_DATABASE_URL', 'QUEUE_WORKER_DATABASE_URL')
PG_OVERRIDES = ('PGHOST', 'PGHOSTADDR', 'PGPORT', 'PGDATABASE', 'PGSERVICE', 'PGSERVICEFILE',
                'PGOPTIONS', 'PGSYSCONFDIR')
DATABASE_TEMPLATE = ('[{{json .Id}},[{{range .Config.Env}}{{if eq (lower (index (split . "=") 0)) '
                     + ' '.join('"' + n.lower() + '"' for n in (*DATABASE_NAMES, *PG_OVERRIDES))
                     + '}}{{json .}},{{end}}{{end}}null]]')
NATIVE_DATABASE_TEMPLATE = (
    '[{{json .Id}},[{{range .Config.Env}}{{$k := upper (index (split . "=") 0)}}'
    '{{if or (and (ge (len $k) 2) (eq (slice $k 0 2) "PG")) (eq $k '
    + ' '.join('"'+name+'"' for name in DATABASE_NAMES)
    + ')}}{{json .}},{{end}}{{end}}null],'
    '[{{range .Mounts}}[{{json .Type}},{{json .Source}},{{json .Destination}},{{json .RW}}],{{end}}null]]')
SAFE_QUERY = frozenset({'sslmode', 'connect_timeout', 'application_name', 'channel_binding', 'gssencmode',
                        'target_session_attrs'})


def check_closed_gates(items, *, code):
    """Case-insensitive discovery, canonical unique names, app-compatible closed values only."""
    seen = set()
    for name, value in items:
        require(isinstance(name, str), code)
        upper = name.upper()
        if upper in CLOSED_GATES:
            require(name == upper and upper not in seen and str(value).lower() == CLOSED_GATES[upper], code)
            seen.add(upper)


def database_target(value):
    """Conservative routing comparison only, not proof of a live connection. No secret escapes."""
    code = 'window-candidate-database'
    try:
        require(isinstance(value, str) and 0 < len(value) <= 16384
                and not any(ord(c) < 33 or ord(c) == 127 for c in value), code)
        uri = urlsplit(value)
        require(uri.scheme in ('postgresql', 'postgresql+psycopg2') and not uri.fragment, code)
        host = (uri.hostname or '').lower()
        require(re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) is not None
                and '..' not in host and not host.endswith('.'), code)
        port = uri.port if uri.port is not None else 5432
        db = unquote(uri.path[1:]) if uri.path.startswith('/') else ''
        require(0 < port < 65536 and db and not any(c in db for c in '/\\')
                and not any(ord(c) < 33 or ord(c) == 127 for c in db), code)
        query = parse_qsl(uri.query, keep_blank_values=True, strict_parsing=True)
        require(len({k for k, _ in query}) == len(query) and {k for k, _ in query} <= SAFE_QUERY
                and all(not any(ord(c) < 32 or ord(c) == 127 for c in v) for _, v in query), code)
        project = None
        if host.endswith('.pooler.supabase.com'):
            user = unquote(uri.username or '')
            role, sep, project = user.rpartition('.')
            require(bool(role and sep) and re.fullmatch(r'[a-z0-9]{1,63}', project) is not None, code)
        return host, port, db, project
    except (ValueError, TypeError):
        raise Refused(code) from None


def check_candidate_database(items, source):
    """Compare explicit candidate URLs to the single provider, discard values and return a count only.

    Empty optional URLs are not evaluated; no fallback or credential provisioning is inferred.
    """
    code = 'window-candidate-database'
    target, urls = database_target(source), {}
    for name, value in items:
        require(isinstance(name, str), code)
        upper = name.upper()
        require(upper not in PG_OVERRIDES, code)
        if upper in DATABASE_NAMES:
            require(name == upper and upper not in urls and isinstance(value, str), code)
            urls[upper] = value
    require(bool(urls.get('DATABASE_URL')), code)
    for value in urls.values():
        if value:
            require(database_target(value) == target, code)
    return sum(not urls.get(name) for name in DATABASE_NAMES[1:])


HOLD_OVERRIDE = ('# A9 hold: candidate containers are created with restart "no" and never started here.\n'
                 '{"services": {' + ', '.join(f'"{r}": {{"restart": "no"}}' for r in ROLES) + '}}\n')
LIMITS = dict(info=256, network=1024, compose=64 * 1024, ps=4096, inspect=64 * 1024, effect=256, smoke=1024)
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
    native_ca_override: str | None = None

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
                and type(self.smoke_seconds) is int and 5 <= self.smoke_seconds <= 50
                and (self.native_ca_override is None or _absolute(self.native_ca_override)), 'candidate-spec')
        return self

    @property
    def deploy_dir(self):
        return f'{self.release_root}/{self.sha}/deploy'

    def names(self):
        return dict(self.containers)

    def compose_argv(self):
        deploy = self.deploy_dir
        return ('docker', 'compose', '--project-name', self.project, '--env-file', '/dev/null', '--project-directory', deploy,
                '--file', deploy + '/docker-compose.yml', '--file', deploy + '/docker-compose.override.yml',
                '--file', self.hold_override,
                *(('--file',self.native_ca_override) if self.native_ca_override is not None else ()),
                'up', '--no-start', '--no-deps', '--no-build', '--no-recreate',
                '--pull', 'never', *ROLES)

    def ps_argv(self):
        return ('docker', 'ps', '--all', '--quiet', '--no-trunc', '--filter', f'label={PROJECT_LABEL}={self.project}')

    def network_argv(self):
        # Resolve both selectors: a recycled/ambiguous name cannot stand in for the pinned ID.
        return ('docker', 'network', 'inspect', '--format', NETWORK_TEMPLATE, self.network_id, self.network_name)

    def smoke_argv(self, backend_id):
        return ('docker', 'exec', backend_id, 'python', '-I', '-c', SMOKE_PROBE, str(self.smoke_seconds))


def topology_contract(spec, manifest):
    """Public release topology: candidate project/names, existing network, contained legacy IDs."""
    return dict(schema=release_topology.SCHEMA, version=release_topology.VERSION, project=spec.project,
                legacy_project=manifest.legacy_project, network=dict(name=spec.network_name, id=manifest.network_id),
                containers=spec.names(), reserved_legacy=dict(manifest.service_ids))


def candidate_release_files(repo, spec, *, package_manifest_sha256, git=None):
    """Read and authenticate the exact allowlisted package blobs; never materialize them."""
    spec = spec.validated()
    require(isinstance(package_manifest_sha256, str) and HEX64.fullmatch(package_manifest_sha256),
            'package-identity-missing')
    files = package_backend_release.source_files(repo, spec.sha, git)
    require(hashlib.sha256(package_backend_release.release_manifest(spec.sha, files)).hexdigest()
            == package_manifest_sha256, 'package-identity-mismatch')
    return files


def verify_candidate_release(repo, spec, manifest, *, package_manifest_sha256, git=None):
    """Read-only preflight of a previously prepared layout and hold file; never repair."""
    files = candidate_release_files(repo, spec, package_manifest_sha256=package_manifest_sha256, git=git)
    wanted = layout_files(files, topology_contract(spec, manifest), spec.image, spec.sha)
    target = no_symlink(Path(spec.release_root) / spec.sha)
    require(target.is_dir(), 'candidate-layout-not-prepared')
    require(inventory(target) == sorted(wanted), 'layout-mismatch')
    require(all(read_regular(target / p) == value for p, value in wanted.items()), 'layout-mismatch')
    require(read_regular(Path(spec.hold_override)) == HOLD_OVERRIDE.encode(), 'candidate-hold-mismatch')


def write_candidate_release(repo, spec, manifest, *, package_manifest_sha256, migrations, git=None):
    """Exact package blobs of ``spec.sha`` -> ``<release_root>/<sha>``; returns the file count."""
    files = candidate_release_files(repo, spec, package_manifest_sha256=package_manifest_sha256, git=git)
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

    def __init__(self, spec, *,native_runtime=None, **kwargs):
        self.spec = spec.validated()
        if native_runtime is not None:
            from first_transition_native_candidate_runtime import NativeCandidateRuntime
            require(type(native_runtime) is NativeCandidateRuntime and native_runtime.spec==spec,'native-candidate-runtime-binding')
        self.native_runtime=native_runtime
        super().__init__(**kwargs)

    def _allowed(self, argv):
        if self.native_runtime is not None:
            runtime=self.native_runtime
            if len(argv)>2 and HEX64.fullmatch(argv[-1]) and argv==runtime.inspect_argv(argv[-1]):return True
            if len(argv)>2 and HEX64.fullmatch(argv[2]) and argv==runtime.admission_argv(argv[2]):return True
            if len(argv)>2 and HEX64.fullmatch(argv[2]) and runtime._receipt is not None and argv==runtime.observe_argv(argv[2]):return True
            if len(argv)>2 and HEX64.fullmatch(argv[2]) and argv==runtime.smoke_argv(argv[2]):return True
            if len(argv)==5 and HEX64.fullmatch(argv[-1]) and argv==runtime.stop_argv(argv[-1]):return True
        if argv in (INFO_ARGV, self.spec.compose_argv(), self.spec.ps_argv(), self.spec.network_argv()):
            return True
        if len(argv) == 3 and argv[:2] == ('docker', 'start'):
            return HEX64.fullmatch(argv[2]) is not None
        if len(argv) == 8 and HEX64.fullmatch(argv[2]):
            return argv == self.spec.smoke_argv(argv[2])
        return (6 < len(argv) <= 10 and argv[:5] == ('docker', 'inspect', '--type', 'container', '--format')
                and argv[5] in (CANDIDATE_TEMPLATE, DATABASE_TEMPLATE,NATIVE_DATABASE_TEMPLATE)
                and all(HEX64.fullmatch(i) for i in argv[6:]) and len(set(argv[6:])) == len(argv[6:]))

    def _env(self):
        # Path of the private configuration only; Compose reads it, this process never does.
        return {**super()._env(), 'PASTORAI_ENV_FILE': self.spec.env_file}


class CandidatePort:
    def __init__(self, spec, *, runner, database_secret=None, source_transports=None):
        require(isinstance(spec, CandidateSpec), 'candidate-spec')
        require(callable(runner), 'candidate-runner')
        self.spec, self.runner = spec.validated(), runner
        self.database_secret = database_secret
        if source_transports is not None:
            from first_transition_native_transports import NativeSourceTransports
            require(type(source_transports) is NativeSourceTransports and spec.native_ca_override is not None,
                'native-candidate-transports')
        else:
            require(spec.native_ca_override is None,'native-candidate-transports')
        self.source_transports = source_transports
        self.native_runtime = source_transports.candidate_runtime if source_transports is not None else None
        if self.native_runtime is not None:
            require(self.native_runtime.spec==spec and self.native_runtime.transports is source_transports,
                'native-candidate-runtime-binding')

    def check_database(self, ident, *, timeout=20):
        """Fresh private Env projection of exactly the created backend; no URL enters public state."""
        if self.database_secret is None:  # Low-level synthetic ports need not wire a window provider.
            return
        deadline = self._deadline(timeout)
        self._daemon(timeout=self._remaining(deadline))
        require(isinstance(ident, str) and HEX64.fullmatch(ident), 'window-candidate-database')
        template = NATIVE_DATABASE_TEMPLATE if self.source_transports is not None else DATABASE_TEMPLATE
        rc, out = self._run(('docker', 'inspect', '--type', 'container', '--format', template, ident),
                            self._remaining(deadline), LIMITS['inspect'])
        self._remaining(deadline)
        require(rc == 0, 'window-candidate-database')
        try:
            row = json.loads(out)
            require(isinstance(row, list) and len(row) == (3 if self.source_transports is not None else 2)
                    and row[0] == ident, 'window-candidate-database')
            env = _tail(row[1], 'window-candidate-database')
            require(all(isinstance(v, str) and '=' in v for v in env), 'window-candidate-database')
            if self.source_transports is not None:
                self.source_transports.candidate_environment((v.split('=',1) for v in env),self.database_secret())
                proof = self.source_transports.candidate_mounts(row[2])
                if self.native_runtime is None:
                    require(proof['effective_ca_verified'] is True,'native-candidate-effective-ca-unproven')
                else:
                    if self.native_runtime._receipt is None:
                        self.native_runtime.pre_start(ident,runner=self.runner,timeout=self._remaining(deadline))
                    else:self.native_runtime.observe_live(ident,runner=self.runner,timeout=self._remaining(deadline))
            else:
                check_candidate_database((v.split('=', 1) for v in env), self.database_secret())
        except (ValueError, TypeError):
            raise Refused('window-candidate-database') from None

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

    @staticmethod
    def _deadline(timeout):
        require(type(timeout) in (int, float) and 0 < timeout <= 30, 'candidate-timeout-bound')
        return time.monotonic() + timeout

    @staticmethod
    def _remaining(deadline):
        remaining = deadline - time.monotonic()
        require(remaining > 0, 'candidate-timeout')
        return min(10, remaining)

    def _daemon(self, *, timeout=10):
        rc, out = self._run(INFO_ARGV, min(10, timeout), LIMITS['info'])
        ok, value = _attempt(_lines, out)
        require(rc == 0 and ok and value == [self.spec.daemon_id], 'candidate-daemon-mismatch')

    def _network(self, deadline):
        rc, out = self._run(self.spec.network_argv(), self._remaining(deadline), LIMITS['network'])
        self._remaining(deadline)
        ok, rows = _attempt(_lines, out)
        binding = [self.spec.network_id, self.spec.network_name]
        require(rc == 0 and ok and rows == [binding, binding], 'candidate-network-binding')
        return binding

    def project_ids(self, *, timeout=20):
        deadline = self._deadline(timeout)
        self._daemon(timeout=self._remaining(deadline))
        rc, out = self._run(self.spec.ps_argv(), self._remaining(deadline), LIMITS['ps'])
        self._remaining(deadline)
        ok, text = _attempt(bytes.decode, out, 'ascii')
        require(rc == 0 and ok and (text == '' or text.endswith('\n')), 'candidate-ps-failed')
        ids = text.split()
        require(all(HEX64.fullmatch(i) for i in ids) and len(set(ids)) == len(ids), 'candidate-ps-failed')
        return tuple(sorted(ids))

    def create_held(self):
        self._daemon()
        rc, _ = self._run(self.spec.compose_argv(), 60, LIMITS['compose'])
        require(rc == 0, 'candidate-create-failed')

    def inspect(self, ids, *, timeout=20):
        require(isinstance(ids, (tuple, list)) and 1 <= len(ids) <= 4
                and all(isinstance(i, str) and HEX64.fullmatch(i) for i in ids)
                and len(set(ids)) == len(ids), 'candidate-ids')
        deadline = self._deadline(timeout)
        self._daemon(timeout=self._remaining(deadline))
        self._network(deadline)
        rc, out = self._run(('docker', 'inspect', '--type', 'container', '--format', CANDIDATE_TEMPLATE, *ids),
                            self._remaining(deadline), LIMITS['inspect'])
        self._remaining(deadline)
        require(rc == 0, 'candidate-inspect-failed')
        ok, rows = _attempt(_lines, out)
        require(ok and all(isinstance(r, list) and len(r) == 19 for r in rows)
                and [r[1] for r in rows] == list(ids), 'candidate-inspect-malformed')
        states = {row[1]: self._row(row) for row in rows}
        binding = self._network(deadline)
        # Per-inspection evidence, never cached; keep the raw effective IDs unchanged.
        for state in states.values():
            state['network_binding'] = list(binding)
        return states

    @staticmethod
    def _row(row):
        (name, ident, image, project, service, revision, status, running, paused, restarting, exit_code, started,
         health, restarts, policy, mode, gates, mounts, networks) = row
        require(isinstance(name, str) and name.startswith('/') and isinstance(image, str)
                and isinstance(status, str) and status in STATUSES and type(running) is bool
                and running == (status == 'running') and paused is False and restarting is False
                and type(exit_code) is int and isinstance(started, str) and STARTED.fullmatch(started)
                and (health is None or isinstance(health, str))
                and type(restarts) is int and restarts >= 0 and isinstance(policy, str)
                and isinstance(mode, str) and len(mode) <= 128,
                'candidate-inspect-state')
        gates = _tail(gates, 'candidate-inspect-gates')
        require(all(isinstance(g, str) and '=' in g for g in gates), 'candidate-inspect-gates')
        values = dict(g.split('=', 1) for g in gates)
        require(len(values) == len(gates) and set(values) <= set(MANDATORY_GATES), 'candidate-inspect-gates')
        networks = _tail(networks, 'candidate-inspect-networks')
        require(len(networks) <= 16 and all(
            isinstance(n, list) and len(n) == 3 and isinstance(n[0], str) and NETWORK_NAME.fullmatch(n[0])
            and (n[1] is None or isinstance(n[1], list) and all(isinstance(a, str) for a in n[1]))
            and isinstance(n[2], str) and (n[2] == '' or HEX64.fullmatch(n[2])) for n in networks)
            and len({n[0] for n in networks}) == len(networks),
                'candidate-inspect-networks')
        _tail(mounts, 'candidate-inspect-mounts')
        labels = [None if v in (None, '') else v for v in (project, service, revision)]
        return dict(id=ident, name=name[1:], image=image, project=labels[0], service=labels[1], revision=labels[2],
                    status=status, running=running, exit_code=exit_code, started=started, health=health,
                    restart_count=restarts, restart_policy=policy or 'no', gates=values,
                    network_mode=mode, network_names=sorted(n[0] for n in networks),
                    networks=sorted(n[2] for n in networks))

    def _backend(self, backend_id):
        """Fresh inspect of the given ID: it must be THIS spec's backend (image, project, name, network, gates)."""
        require(isinstance(backend_id, str) and HEX64.fullmatch(backend_id), 'candidate-ids')
        state = self.inspect((backend_id,))[backend_id]
        check_identity(self.spec, 'backend', state)
        return state

    def start_backend(self, backend_id):
        if self.source_transports is not None:
            require(self.native_runtime is not None and callable(self.database_secret),'native-candidate-effective-ca-unproven')
            self.check_database(backend_id)
        # A consumer, a foreign project or a foreign image refuses before any start is issued.
        check_held(self._backend(backend_id), code='candidate-backend-not-held')
        self._daemon()
        try:
            rc, out = self._run(('docker', 'start', backend_id), 30, LIMITS['effect'])
            require(rc == 0 and out == (backend_id + '\n').encode(), 'candidate-start-receipt')
            if self.native_runtime is not None:
                return self.native_runtime.after_start(backend_id,runner=self.runner,timeout=15)
        except BaseException as error:
            if self.native_runtime is not None:
                try:self.native_runtime.abort(backend_id,runner=self.runner,timeout=10)
                except BaseException:raise Refused('native-candidate-runtime-cleanup-unproven') from None
                if not isinstance(error,Exception):raise KeyboardInterrupt from None
                raise Refused('native-candidate-runtime-start-failed') from None
            raise

    def smoke(self, backend_id):
        check_backend_running(self._backend(backend_id))
        if self.native_runtime is not None:self.native_runtime.observe_live(backend_id,runner=self.runner,timeout=10)
        self._daemon()
        argv=self.native_runtime.smoke_argv(backend_id) if self.native_runtime is not None else self.spec.smoke_argv(backend_id)
        rc, out = self._run(argv, self.spec.smoke_seconds + 10, LIMITS['smoke'])
        ok, value = _attempt(_lines, out)
        require(rc == 0 and ok and len(value) == 1 and isinstance(value[0], dict)
                and set(value[0]) == SMOKE_KEYS, 'candidate-smoke-malformed')
        result = value[0]
        require(result['health'] == 200 and result['health_ok'] is True, 'candidate-health-failed')
        require(result['ready'] == 200 and result['required_ok'] is True
                and result['ready_status'] in ('ready', 'degraded'), 'candidate-ready-failed')
        if self.native_runtime is not None:self.native_runtime.observe_live(backend_id,runner=self.runner,timeout=10)
        return dict(health=200, ready=200, ready_status=result['ready_status'])


def check_identity(spec, role, state):
    """Pinned image/revision, own project/service/name, single network, every gate closed."""
    require(state['image'] == spec.image and state['revision'] == spec.sha, 'candidate-image-mismatch')
    require(state['project'] == spec.project and state['service'] == role
            and state['name'] == spec.names()[role], 'candidate-identity-mismatch')
    require(state.get('network_binding') == [spec.network_id, spec.network_name]
            and state.get('network_names') == [spec.network_name]
            and state.get('network_mode') in (spec.network_id, spec.network_name), 'candidate-network-mismatch')
    if state['networks'] != [spec.network_id]:
        require(state['networks'] == [''], 'candidate-network-mismatch')
        check_held(state, code='candidate-network-mismatch')
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
