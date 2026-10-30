"""Observation/containment/resume driver behind ObservedHostTransport.

``ObservedHostDriver.request(argv, *, timeout)`` answers the transport's
semantic commands from an injected runner plus explicit callbacks:

* inspect-host: pinned daemon, pinned network and the seven pinned containers
  through restricted ``--format`` stdout projections to Python, plus both ingress entries and the
  unknown-writer callback; ``ingress_blocked`` means BOTH entries blocked and ``ingress_open``
  BOTH open, so a partial state (one entry open) reports neither;
* redis-meta: TYPE/PTTL/LLEN/ZCARD on explicit keys via ``redis-cli`` inside the
  pinned, label-verified Redis container; no KEYS/SCAN/values/auth in argv, and
  an auth error is a refusal;
* block-ingress, ``docker update --restart=no``, ``docker kill --signal=TERM``
  and ``docker wait`` on the four legacy IDs only;
* resume (``docker start``, ``docker update --restart=always`` on the four
  legacy IDs and open-ingress through both bound entries) ONLY when a
  ``ledger_proof`` bound to this manifest is injected: a fresh read-only
  PostgreSQL proof (identity, exact baseline ledger, catalog; see
  first_transition_database.LedgerProof) runs inside every resume request,
  immediately before its effect. Without it, resume refuses before any call.

The writer binding reports UNKNOWN writers only, i.e. UNDECLARED sources, and
must report 0 on every observation. The four legacy roles of the manifest are
declared sources throughout (their stop is verified separately by the host
states), as are the transition's own observer/migration child and, only from
the A9 backend start, the configured candidate backend; see
first_transition_orchestrator.assemble. Zero database writers is a separate
pre-DDL requirement of the orchestrator.

Every other operation refuses before any runner call. Ingress/writer values are
callback-reported scope-bound answers, not independent proof, and no token or
boolean stands for a human approval. Docker values are CLI-reported for an
operator-configured endpoint; nothing here certifies the host or quiescence.
Real bindings/manifest values are Phase 3 inputs.

The Docker CLI applies --format client-side; only its restricted stdout
projection enters Python/journals. Tests use synthetic data only.

Errors carry fixed codes only; runner output never enters exceptions, logs or
receipts. No retry: a timeout or refusal is final for that request. Each
request has a cooperative deadline, checked after injected calls return; per-command output caps are acceptance limits.
PopenRunner reads at most cap + 1 byte; joining buffers temporarily duplicates
that bounded storage (plus Python overhead), so this is not a cap on process RSS; an
injected runner's own buffering is its responsibility. Nothing runs at import
or construction; there is no command-line entry point.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
import re
import select
import subprocess
import time

from first_transition_adapter import ROLES, digest
from first_transition_host_transport import SUPPORT_ROLES, _ids, host_command
from initial_transition_ops import Refused, require

SCHEMA = 'igreja12.first-transition-host-manifest/1'
MANIFEST_KEYS = frozenset({'schema', 'daemon_id', 'legacy_project', 'network_id', 'service_ids', 'support_ids',
                           'processing_keys', 'gate_names'})
ENTRIES = ('external', 'evolution-backend')
QUEUE_KEYS = ('pastorai:webhooks', 'pastorai:webhooks:processing', 'pastorai:webhooks:dead',
              'pastorai:webhooks:retry-scheduled')
REDIS_COMMANDS = ('TYPE', 'PTTL', 'LLEN', 'ZCARD')
REDIS_TYPES = ('none', 'string', 'list', 'set', 'zset', 'hash', 'stream')
EFFECTS = ('restart-no', 'term', 'wait')
RESUME_EFFECTS = ('start', 'restart-always')
# Acceptance caps (bytes of stdout) per command; also PopenRunner's memory bound.
LIMITS = dict(info=256, network=1024, inspect=64 * 1024, redis=64, effect=256, wait=16)
MAX_OUTPUT = 1024 * 1024

HEX64 = re.compile('[0-9a-f]{64}')
DAEMON = re.compile('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[A-Z0-9]{4}(?::[A-Z0-9]{4}){11}')
PROJECT = re.compile(r'[A-Za-z0-9_-]{1,63}')
PROCESSING = re.compile(r'pastorai:webhooks:processing:[A-Za-z0-9_-]{1,80}')
MANDATORY_GATES = ('ALLOW_REAL_SENDS', 'ASAAS_BILLING_ENABLED', 'BREVO_SEND_MODE', 'BROADCAST_ASYNC_ENABLED')
NETWORK_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')
IMAGE = re.compile('sha256:[0-9a-f]{64}')
STARTED = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})')
STATUSES = ('created', 'running', 'exited')
HEALTH = ('starting', 'healthy', 'unhealthy')
RUNNER_CODES = frozenset({'runner-argv', 'runner-bounds', 'runner-spawn-failed', 'runner-output-oversize',
                          'runner-close-failed', 'runner-failed', 'runner-pending-cli'})
PROJECT_LABEL = 'com.docker.compose.project'
SERVICE_LABEL = 'com.docker.compose.service'
REVISION_LABEL = 'org.opencontainers.image.revision'
INFO_ARGV = ('docker', 'info', '--format', '{{json .ID}}')
NETWORK_TEMPLATE = '[{{json .Id}},{{json .Name}}]'


def _gate_names(names):
    require(isinstance(names, (list, tuple)) and len(names) == len(MANDATORY_GATES)
            and all(isinstance(n, str) for n in names) and set(names) == set(MANDATORY_GATES),
            'manifest-gate-names')
    return tuple(sorted(names))


def _label(key):
    # A nil label map prints null and a missing key prints ""; both normalize to None.
    return '{{with .Config.Labels}}{{json (index . "' + key + '")}}{{else}}null{{end}}'


def inspect_template(gate_names):
    """One JSON array per container; the trusted Docker CLI filters env by name before stdout."""
    quoted = ' '.join('"' + name + '"' for name in _gate_names(gate_names))
    return ('[{{json .Id}},{{json .Image}},' + ','.join(_label(k) for k in (
            PROJECT_LABEL, SERVICE_LABEL, REVISION_LABEL)) + ','
            '{{json .State.Status}},{{json .State.Running}},{{json .State.Paused}},{{json .State.Restarting}},'
            '{{json .State.ExitCode}},{{json .State.StartedAt}},'
            '{{with .State.Health}}{{json .Status}}{{else}}null{{end}},'
            '{{json .RestartCount}},{{json .HostConfig.RestartPolicy.Name}},{{json .HostConfig.NetworkMode}},'
            '[{{range .Config.Env}}{{if eq (index (split . "=") 0) ' + quoted + '}}{{json .}},{{end}}{{end}}null],'
            '[{{range .Mounts}}[{{json .Type}},{{json .Name}},{{json .Source}},{{json .Destination}},'
            '{{json .RW}}],{{end}}null],'
            '[{{range $name, $net := .NetworkSettings.Networks}}[{{json $name}},{{json $net.Aliases}},'
            '{{json $net.NetworkID}}],{{end}}null]]')


@dataclass(frozen=True)
class HostManifest:
    """Sanitized, immutable scope; unknown keys (e.g. any secret) are refused."""
    daemon_id: str
    legacy_project: str
    network_id: str
    service_ids: tuple
    support_ids: tuple
    processing_keys: tuple
    gate_names: tuple
    digest: str

    @classmethod
    def from_dict(cls, data):
        require(isinstance(data, Mapping) and set(data) == MANIFEST_KEYS, 'manifest-keys')
        require(data['schema'] == SCHEMA, 'manifest-schema')
        require(isinstance(data['daemon_id'], str) and DAEMON.fullmatch(data['daemon_id']), 'manifest-daemon')
        require(isinstance(data['legacy_project'], str) and PROJECT.fullmatch(data['legacy_project']),
                'manifest-project')
        services, support = data['service_ids'], data['support_ids']
        require(_ids(services, ROLES) and _ids(support, SUPPORT_ROLES)
                and not set(services.values()) & set(support.values()), 'manifest-identities')
        require(isinstance(data['network_id'], str) and HEX64.fullmatch(data['network_id'])
                and data['network_id'] not in {*services.values(), *support.values()}, 'manifest-network')
        keys = data['processing_keys']
        require(isinstance(keys, (list, tuple)) and len(keys) <= 64 and all(isinstance(k, str) and PROCESSING.fullmatch(k) for k in keys)
                and len(set(keys)) == len(keys), 'manifest-processing-keys')
        values = dict(daemon_id=data['daemon_id'], legacy_project=data['legacy_project'],
                      network_id=data['network_id'], service_ids=tuple((r, services[r]) for r in ROLES),
                      support_ids=tuple((r, support[r]) for r in SUPPORT_ROLES), processing_keys=tuple(keys),
                      gate_names=_gate_names(data['gate_names']))
        return cls(**values, digest=digest([SCHEMA, values]))

    def validated(self):
        require(all(type(v) is tuple for v in (
            self.service_ids, self.support_ids, self.processing_keys, self.gate_names)), 'manifest-values')
        ok, canonical = _attempt(type(self).from_dict, {
            'schema': SCHEMA, 'daemon_id': self.daemon_id, 'legacy_project': self.legacy_project,
            'network_id': self.network_id, 'service_ids': dict(self.service_ids),
            'support_ids': dict(self.support_ids), 'processing_keys': self.processing_keys,
            'gate_names': self.gate_names})
        require(ok and self == canonical, 'manifest-integrity')
        return canonical

    def transport_scope(self):
        return dict(legacy_project=self.legacy_project, network_id=self.network_id,
                    service_ids=dict(self.service_ids), support_ids=dict(self.support_ids),
                    processing_keys=self.processing_keys)


def _strict_json(text):
    def constant(_):
        raise ValueError('constant')
    return json.loads(text, parse_constant=constant)


def _lines(out):
    text = out.decode('utf-8')
    if not text.endswith('\n'):
        raise ValueError('unterminated')
    return [_strict_json(line) for line in text[:-1].split('\n')]


def _attempt(function, *args):
    # The failure is reported after the except block: no exception context can
    # carry runner output into a later traceback.
    try:
        return True, function(*args)
    except (ValueError, UnicodeDecodeError, RecursionError, TypeError):
        return False, None


def _tail(value, code):
    require(isinstance(value, list) and value and value[-1] is None, code)
    return value[:-1]


class ObservedHostDriver:
    mode = 'observed-host'

    def __init__(self, manifest, *, runner, ingress, writers, ledger_proof=None):
        require(isinstance(manifest, HostManifest), 'driver-manifest')
        manifest = manifest.validated()
        require(callable(runner), 'driver-runner')
        require(isinstance(ingress, Mapping) and set(ingress) == set(ENTRIES)
                and ingress['external'] is not ingress['evolution-backend']
                and all(self._bound(ingress[e], manifest, e, 'observe', 'block') for e in ENTRIES),
                'driver-ingress-binding')
        require(self._bound(writers, manifest, None, 'observe'), 'driver-writer-binding')
        require(ledger_proof is None or self._bound(ledger_proof, manifest, None, 'prove'), 'driver-ledger-binding')
        self.manifest, self.runner = manifest, runner
        self.ingress, self.writers, self.ledger_proof = dict(ingress), writers, ledger_proof
        self.template = inspect_template(manifest.gate_names)
        self.roles = {ident: role for role, ident in (*manifest.service_ids, *manifest.support_ids)}
        self.legacy = tuple(ident for _, ident in manifest.service_ids)
        self.redis_id = dict(manifest.support_ids)['redis']
        self.redis_verified = False
        self.refusals = []  # fixed codes only, for diagnosis; never output
        self._bindings_fixed = (self.ingress['external'], self.ingress['evolution-backend'], self.writers,
                                ledger_proof)

    @property
    def supports_resume(self):
        # Resume needs the database proof and an opener on both ingress entries.
        return (self.ledger_proof is not None and self._bound(self.ledger_proof, self.manifest, None, 'prove')
                and all(self._bound(self.ingress[e], self.manifest, e, 'open') for e in ENTRIES))

    @staticmethod
    def _bound(binding, manifest, entry, *methods):
        return (binding is not None and getattr(binding, 'scope', None) == manifest.digest
                and (entry is None or getattr(binding, 'entry', None) == entry)
                and all(callable(getattr(binding, method, None)) for method in methods))

    def transport_scope(self):
        return self.manifest.transport_scope()

    def request(self, argv, *, timeout):
        try:
            self._assert_bindings()
            result = self._dispatch(argv, timeout)
            self._assert_bindings()
            return result
        except Refused as exc:
            self.refusals = [*self.refusals[-63:], str(exc)]
            raise

    def _assert_bindings(self):
        require(isinstance(self.ingress, dict) and set(self.ingress) == set(ENTRIES), 'driver-ingress-binding')
        for index, entry in enumerate(ENTRIES):
            require(self.ingress[entry] is self._bindings_fixed[index]
                    and self._bound(self.ingress[entry], self.manifest, entry, 'observe', 'block'),
                    'driver-ingress-binding')
        require(self.writers is self._bindings_fixed[2]
                and self._bound(self.writers, self.manifest, None, 'observe'), 'driver-writer-binding')
        require(self.ledger_proof is self._bindings_fixed[3], 'driver-ledger-binding')

    def _dispatch(self, argv, timeout):
        require(type(timeout) in (int, float) and 0 < timeout <= 30, 'driver-timeout-bound')
        require(type(argv) is tuple and argv and all(type(a) is str for a in argv), 'driver-operation-forbidden')
        deadline = time.monotonic() + timeout
        if argv == ('inspect-host',):
            return self._inspect_host(deadline)
        if argv[0] == 'redis-meta':
            require(len(argv) == 3 and argv[1] in REDIS_COMMANDS
                    and argv[2] in QUEUE_KEYS + self.manifest.processing_keys, 'driver-redis-scope')
            return self._redis_meta(argv[1], argv[2], deadline)
        if argv == ('block-ingress',):
            return self._block_ingress(deadline)
        if argv == ('open-ingress',):
            require(self.supports_resume, 'driver-operation-forbidden')
            return self._open_ingress(deadline)
        for kind in (*EFFECTS, *RESUME_EFFECTS):
            for ident in self.legacy:
                if argv == host_command(kind, ident):
                    require(kind in EFFECTS or self.supports_resume, 'driver-operation-forbidden')
                    return self._effect(kind, ident, argv, deadline)
        raise Refused('driver-operation-forbidden')

    @staticmethod
    def _remaining(deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('driver-timeout')
        return remaining

    def _run(self, argv, deadline, limit):
        outcome = None
        try:
            result = self.runner(argv, timeout=self._remaining(deadline), max_output=limit)
        except TimeoutError:
            outcome = 'timeout'
        except Refused as exc:
            outcome = str(exc) if str(exc) in RUNNER_CODES else 'driver-runner-failed'
        except Exception:
            outcome = 'driver-runner-failed'
        if outcome == 'timeout':
            raise TimeoutError('driver-timeout')
        require(outcome is None, outcome)
        require(isinstance(result, tuple) and len(result) == 2 and type(result[0]) is int
                and type(result[1]) is bytes, 'driver-runner-failed')
        self._remaining(deadline)
        self._assert_bindings()
        require(len(result[1]) <= limit, 'driver-output-oversize')
        return result

    def _callback(self, binding, method, deadline, entry, code, failed='driver-binding-failed'):
        require(self._bound(binding, self.manifest, entry, method), code)
        outcome = None
        try:
            value = getattr(binding, method)(self.manifest.digest, timeout=self._remaining(deadline))
        except TimeoutError:
            outcome = 'timeout'
        except Exception:
            outcome = failed
        if outcome == 'timeout':
            raise TimeoutError('driver-timeout')
        self._remaining(deadline)
        require(self._bound(binding, self.manifest, entry, method), code)
        self._assert_bindings()
        require(outcome is None, outcome)
        return value

    def _daemon(self, deadline):
        rc, out = self._run(INFO_ARGV, deadline, LIMITS['info'])
        require(rc == 0, 'driver-daemon-failed')
        ok, value = _attempt(_lines, out)
        require(ok and len(value) == 1 and isinstance(value[0], str) and DAEMON.fullmatch(value[0]),
                'driver-daemon-malformed')
        require(value[0] == self.manifest.daemon_id, 'driver-daemon-mismatch')

    def _network(self, deadline):
        rc, out = self._run(('docker', 'network', 'inspect', '--format', NETWORK_TEMPLATE, self.manifest.network_id),
                            deadline, LIMITS['network'])
        require(rc == 0, 'driver-network-failed')
        ok, value = _attempt(_lines, out)
        require(ok and len(value) == 1 and isinstance(value[0], list) and len(value[0]) == 2
                and all(isinstance(v, str) for v in value[0]) and HEX64.fullmatch(value[0][0])
                and NETWORK_NAME.fullmatch(value[0][1]), 'driver-network-malformed')
        require(value[0][0] == self.manifest.network_id, 'driver-network-mismatch')
        return value[0]

    def _ingress(self, deadline):
        states = {}
        for entry in ENTRIES:
            value = self._callback(self.ingress[entry], 'observe', deadline, entry, 'driver-ingress-binding')
            require(type(value) is str and value in ('blocked', 'open'), 'driver-ingress-shape')
            states[entry] = value
        return states

    def _row(self, row, network_name):
        (ident, image, project, service, revision, status, running, paused, restarting, exit_code, started,
         health, restarts, policy, mode, gates, mounts, networks) = row
        labels = [None if value in (None, '') else value for value in (project, service, revision)]
        require(all(v is None or isinstance(v, str) and len(v) <= 128 for v in labels), 'driver-inspect-labels')
        require(isinstance(image, str) and IMAGE.fullmatch(image) and type(running) is bool
                and isinstance(status, str) and status in STATUSES and running == (status == 'running')
                and paused is False and restarting is False
                and type(exit_code) is int and 0 <= exit_code <= 255
                and isinstance(started, str) and STARTED.fullmatch(started)
                and (health is None or isinstance(health, str) and health in HEALTH)
                and type(restarts) is int and 0 <= restarts <= 10**6
                and isinstance(policy, str) and policy in ('always', 'no', '')
                and isinstance(mode, str) and len(mode) <= 128, 'driver-inspect-state')
        gates = _tail(gates, 'driver-inspect-gates')
        names = [g.split('=', 1)[0] if isinstance(g, str) and '=' in g else None for g in gates]
        require(all(n in self.manifest.gate_names for n in names) and len(set(names)) == len(names)
                and all(len(g) <= 512 for g in gates), 'driver-inspect-gates')
        mounts = _tail(mounts, 'driver-inspect-mounts')
        require(len(mounts) <= 64 and all(
            isinstance(m, list) and len(m) == 5 and type(m[4]) is bool
            and all(v is None or isinstance(v, str) and len(v) <= 4096 for v in m[:4]) for m in mounts),
            'driver-inspect-mounts')
        networks = _tail(networks, 'driver-inspect-networks')
        require(len(networks) <= 16 and all(
            isinstance(n, list) and len(n) == 3 and isinstance(n[0], str) and NETWORK_NAME.fullmatch(n[0])
            and (n[1] is None or isinstance(n[1], list) and all(isinstance(a, str) for a in n[1]))
            and isinstance(n[2], str) and HEX64.fullmatch(n[2]) for n in networks)
            and len({n[0] for n in networks}) == len(networks), 'driver-inspect-networks')
        require(network_name in {n[0] for n in networks}, 'driver-network-detached')
        require(any(n[0] == network_name and n[2] == self.manifest.network_id for n in networks),
                'driver-network-mismatch')
        # Stable configuration only: attachments by name/ID with configured aliases; IPAM is operational on some engines,
        # never IP, endpoint, gateway or MAC, which Docker clears on stop.
        attachments = [[n[0], sorted(n[1] or []), n[2]] for n in sorted(networks, key=lambda n: n[0])]
        return dict(
            id=ident, image=image, compose_project=labels[0], compose_service=labels[1], revision=labels[2],
            started=started, restart_count=restarts, restart_policy=policy or 'no', running=running,
            exit_code=None if running else exit_code, health=health,
            gates_digest=digest(['gates', sorted(gates)]),
            mounts_digest=digest(['mounts', sorted(mounts, key=json.dumps)]),
            networks_digest=digest(['networks', mode, attachments]))

    def _inspect_host(self, deadline):
        self.redis_verified = False
        self._daemon(deadline)
        network_id, network_name = self._network(deadline)
        ids = tuple(self.roles)
        rc, out = self._run(('docker', 'inspect', '--type', 'container', '--format', self.template, *ids),
                            deadline, LIMITS['inspect'])
        require(rc == 0, 'driver-inspect-failed')
        ok, rows = _attempt(_lines, out)
        require(ok and all(isinstance(r, list) and len(r) == 18 and isinstance(r[0], str) for r in rows),
                'driver-inspect-malformed')
        require(len(rows) == len(ids) and {r[0] for r in rows} == set(ids), 'driver-inspect-scope')
        services, support = {}, {}
        for row in rows:
            state, role = self._row(row, network_name), self.roles[row[0]]
            if role in ROLES:
                state.pop('health')
                services[role] = state
            else:
                support[role] = {key: state[key] for key in (
                    'id', 'image', 'compose_project', 'compose_service', 'running', 'restart_policy', 'health',
                    'networks_digest')}
        ingress = self._ingress(deadline)
        writers = self._callback(self.writers, 'observe', deadline, None, 'driver-writer-binding')
        require(type(writers) is int and 0 <= writers <= 10**6, 'driver-writer-shape')
        redis = support['redis']
        self.redis_verified = (redis['compose_project'] == self.manifest.legacy_project
                               and redis['compose_service'] == 'redis' and redis['running'] is True)
        # Two separate facts: a mixed state (one entry open) is neither blocked nor open.
        return dict(scope_digest=self.manifest.digest,
                    ingress_blocked=all(v == 'blocked' for v in ingress.values()),
                    ingress_open=all(v == 'open' for v in ingress.values()), unknown_writers=writers,
                    network_id=network_id, services=services, support=support)

    def _redis_meta(self, command, key, deadline):
        # Only into the Redis container this driver just verified by label; no auth in argv.
        require(self.redis_verified, 'driver-redis-unverified')
        self._daemon(deadline)
        rc, out = self._run(('docker', 'exec', self.redis_id, 'redis-cli', '--raw', command, key),
                            deadline, LIMITS['redis'])
        ok, text = _attempt(bytes.decode, out, 'ascii')
        require(ok, 'driver-redis-output')
        require(not text.startswith(('NOAUTH', 'WRONGPASS', 'NOPERM')), 'driver-redis-auth-required')
        require(rc == 0, 'driver-redis-failed')
        require(text.endswith('\n'), 'driver-redis-output')
        value = text[:-1]
        if command == 'TYPE':
            require(value in REDIS_TYPES, 'driver-redis-output')
            return value
        require(re.fullmatch('-?[0-9]{1,19}', value), 'driver-redis-output')
        return int(value)

    def _block_ingress(self, deadline):
        # Both entries are checked; one blocked entry never stands for the other.
        for entry, state in self._ingress(deadline).items():
            if state == 'open':
                require(self._callback(self.ingress[entry], 'block', deadline, entry,
                                       'driver-ingress-binding') is True, 'driver-ingress-receipt')
        require(all(v == 'blocked' for v in self._ingress(deadline).values()), 'driver-ingress-still-open')
        return True

    def _prove_ledger(self, deadline):
        # Fresh read-only database proof inside this very request, before its effect.
        proof = self._callback(self.ledger_proof, 'prove', deadline, None, 'driver-ledger-binding',
                               'driver-ledger-proof')
        require(isinstance(proof, dict) and proof.get('scope') == self.manifest.digest
                and proof.get('read_only') is True and proof.get('ddl_free') is True, 'driver-ledger-proof')

    def _open_ingress(self, deadline):
        # Internal Evolution->backend first, external last; both must end open.
        self._prove_ledger(deadline)
        for entry in reversed(ENTRIES):
            if self._ingress(deadline)[entry] == 'blocked':
                require(self._callback(self.ingress[entry], 'open', deadline, entry,
                                       'driver-ingress-binding') is True, 'driver-ingress-receipt')
        require(all(v == 'open' for v in self._ingress(deadline).values()), 'driver-ingress-still-blocked')
        return True

    def _effect(self, kind, ident, argv, deadline):
        if kind in RESUME_EFFECTS:
            self._prove_ledger(deadline)
        self._daemon(deadline)
        if kind == 'wait':
            rc, out = self._run(argv, deadline, LIMITS['wait'])
            ok, text = _attempt(bytes.decode, out, 'ascii')
            require(ok and rc == 0 and re.fullmatch('[0-9]{1,3}\n', text), 'driver-wait-receipt')
            return int(text)
        rc, out = self._run(argv, deadline, LIMITS['effect'])
        require(rc == 0 and out == (ident + '\n').encode(), 'driver-effect-receipt')
        return True


GLOBAL_FLAGS = frozenset({'-H', '--host', '--context', '-c', '--config', '--tls', '--tlsverify', '--tlscacert',
                          '--tlscert', '--tlskey', '-D', '--debug', '-l', '--log-level'})
ENV = {'LC_ALL': 'C', 'LANG': 'C'}
ABS_PATH = re.compile('/[A-Za-z0-9._/-]{1,255}')


def _absolute(path):
    return (isinstance(path, str) and ABS_PATH.fullmatch(path) is not None
            and all(part not in ('', '.', '..') for part in path[1:].split('/')))


def _runner_argv(argv, resume=False):
    if not (type(argv) is tuple and 2 <= len(argv) <= 32 and argv[0] == 'docker'
            and all(type(a) is str and 0 < len(a) <= 16384 and '\x00' not in a for a in argv)):
        return False
    if argv == INFO_ARGV:
        return True
    if len(argv) == 6 and argv[:5] == ('docker', 'network', 'inspect', '--format', NETWORK_TEMPLATE):
        return HEX64.fullmatch(argv[5]) is not None
    if 7 <= len(argv) <= 13 and argv[:6] == (
            'docker', 'inspect', '--type', 'container', '--format', inspect_template(MANDATORY_GATES)):
        return all(HEX64.fullmatch(i) for i in argv[6:]) and len(set(argv[6:])) == len(argv[6:])
    if len(argv) == 7 and argv[:2] == ('docker', 'exec'):
        return (HEX64.fullmatch(argv[2]) is not None and argv[3:5] == ('redis-cli', '--raw')
                and argv[5] in REDIS_COMMANDS and (argv[6] in QUEUE_KEYS or PROCESSING.fullmatch(argv[6])))
    if len(argv) == 4 and argv[:3] in (('docker', 'update', '--restart=no'),
                                     ('docker', 'kill', '--signal=TERM')):
        return HEX64.fullmatch(argv[3]) is not None
    if resume and (len(argv) == 4 and argv[:3] == ('docker', 'update', '--restart=always')
                   or len(argv) == 3 and argv[:2] == ('docker', 'start')):
        return HEX64.fullmatch(argv[-1]) is not None
    return len(argv) == 3 and argv[:2] == ('docker', 'wait') and HEX64.fullmatch(argv[2]) is not None


class PopenRunner:
    """Bounded docker CLI runner for a future authorized operator; never used by tests unmocked.

    The endpoint (``unix://`` socket), docker binary and an operator-provided
    config directory are explicit; the child gets a minimal environment, so no
    inherited DOCKER_HOST/DOCKER_CONTEXT/credentials/HOME apply. Only block-A
    read/containment subcommands are accepted, plus ``start``/``restart=always``
    by ID only when constructed with ``resume=True``. On timeout, oversize or error it
    ends only its own CLI process, waits at most ``cleanup_wait`` and never
    retries; an unreaped CLI is counted, not escalated. Killing the CLI does not
    undo a request the daemon already received. Compatibility with a real
    Docker CLI/daemon is unverified here.
    """

    def __init__(self, *, docker_binary, endpoint, config_dir, popen=None, cleanup_wait=2.0, chunk=4096,
                 resume=False):
        require(_absolute(docker_binary) and docker_binary.endswith('/docker')
                and isinstance(endpoint, str) and endpoint.startswith('unix://')
                and _absolute(endpoint[len('unix://'):]) and endpoint.endswith('.sock')
                and _absolute(config_dir) and (popen is None or callable(popen))
                and type(cleanup_wait) in (int, float) and 0 < cleanup_wait <= 10
                and type(chunk) is int and 0 < chunk <= 65536 and type(resume) is bool, 'runner-config')
        self.resume = resume
        self.docker_binary, self.endpoint, self.config_dir = docker_binary, endpoint, config_dir
        self.popen, self.cleanup_wait, self.chunk = popen, cleanup_wait, chunk
        self.unreaped = 0

    def _allowed(self, argv):
        return _runner_argv(argv, self.resume)

    def _env(self):
        return dict(ENV)

    def __call__(self, argv, *, timeout, max_output):
        require(self.unreaped == 0, 'runner-pending-cli')
        require(self._allowed(argv), 'runner-argv')
        require(type(timeout) in (int, float) and 0 < timeout <= 60
                and type(max_output) is int and 0 < max_output <= MAX_OUTPUT, 'runner-bounds')
        deadline = time.monotonic() + timeout
        popen = self.popen or subprocess.Popen  # resolved per call, never at import/construction
        command = [self.docker_binary, '--config', self.config_dir, '--host', self.endpoint, *argv[1:]]
        proc = None
        try:
            proc = popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         env=self._env(), cwd='/', close_fds=True, shell=False, start_new_session=True)
        except Exception:
            pass
        require(proc is not None, 'runner-spawn-failed')
        outcome = 'runner-failed'
        try:
            out = self._read(proc, deadline, max_output)
            rc = proc.wait(timeout=max(deadline - time.monotonic(), 0))
            outcome = None
        except (TimeoutError, subprocess.TimeoutExpired):
            outcome = 'timeout'
        except Refused as exc:
            outcome = str(exc)
        except Exception:
            pass
        except BaseException:
            self._cleanup(proc)
            raise
        finally:
            try:
                proc.stdout.close()
            except Exception:
                if outcome is None:
                    outcome = 'runner-close-failed'
        if outcome is None and time.monotonic() > deadline:
            outcome = 'timeout'
        if outcome is not None:
            self._cleanup(proc)
            if outcome == 'timeout':
                raise TimeoutError('runner-timeout')
            raise Refused(outcome)
        return rc, out

    def _read(self, proc, deadline, limit):
        fd, chunks, size = proc.stdout.fileno(), [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                raise TimeoutError('runner-timeout')
            chunk = os.read(fd, min(self.chunk, limit + 1 - size))
            if not chunk:
                return b''.join(chunks)
            size += len(chunk)
            chunks.append(chunk)
            require(size <= limit, 'runner-output-oversize')

    def _cleanup(self, proc):
        # Ends only this runner's own CLI child; never a container, never a retry.
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=self.cleanup_wait)
        except Exception:
            self.unreaped += 1
