#!/usr/bin/env python3
"""Controller of the FIRST transition from the unversioned legacy install to the candidate.

``run --spec S --state D [--until PHASE] [--allow-probe ID]... [--decision D] [--pause-at CP]``
``status --spec S --state D`` / ``resume-legacy --spec S --state D --confirm TOKEN``

``backend-release.sh`` refuses the legacy install (no release tree, no checker,
no revision label); this controller performs only that first turn and leaves a
release layout behind. It runs on owned synthetic Docker resources only
(``rehearse_initial_transition.py``): ``production_ready`` is false, there is
no production adapter. The layout carries the public topology contract that
``backend-release.sh`` adopts for the next release (``release_topology.py``).

Every invocation re-validates the local Docker endpoint, owned networks and
support containers (before any SQL), legacy identity/policy/state, gates and
scope, whatever phase the journal records. Every effect is preceded by a
durable intent; replay inspects real state and refuses when the outcome is
ambiguous. The ``ddl-marker`` is irrevocable: afterwards the legacy is never
restarted, and any failure before promotion contains the candidate (restart
``no`` persisted, SIGTERM, exit observed) until a human ``retry-candidate``.
Gates are never changed: the candidate must carry exactly the legacy values.

Phases: observed -> contained -> settled -> reconciled -> preflighted ->
ddl-started -> migrated -> schema-verified -> candidate-ready -> promoted.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
import zlib
from pathlib import Path

from initial_transition_files import (
    Journal, git_tree, migration_manifest, no_symlink, read_regular, sha256,
)
from initial_transition_ops import (
    COMPOSE_PROJECT, COMPOSE_SERVICE, DSN, IMAGE_ID, OBSERVER_APPS, OWNER_LABEL, RESOURCE_ID,
    REVISION_LABEL, SHA, DockerOps, Refused, gates_of, host_exposed, ip_of, require,
)

PHASES = ('observed', 'contained', 'settled', 'reconciled', 'preflighted', 'ddl-started', 'migrated',
          'schema-verified', 'candidate-ready', 'promoted')
CANDIDATE_PHASES = frozenset({'candidate-ready', 'promoted'})
TERMINAL = 'legacy-resumed'
ROLES = ('backend', 'queue-worker', 'cron-worker', 'broadcast-worker')
CONTAIN_ORDER = ('backend', 'cron-worker', 'broadcast-worker', 'queue-worker')
START_ORDER = ('backend', 'queue-worker', 'broadcast-worker', 'cron-worker')
EXIT_REFUSED, EXIT_WAIT, EXIT_USAGE, EXIT_BUSY = 3, 4, 2, 5
RETRIABLE = frozenset({'migration-failed', 'concurrent-index-invalid', 'concurrent-failed-decision',
                       'concurrent-index-present-ledger-absent'})
WAIT_CODES = frozenset({'job-active', 'migration-job-active', 'migration-session-active'})
CANDIDATE_TREE = re.compile(r'backend/(?:app/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*\.py'
                            r'|migrations/(?:[A-Za-z0-9_]+/)?[A-Za-z0-9_.-]+\.sql|requirements\.lock'
                            r'|scripts/migrate\.py)')
# Exact allowlist of candidate blobs ever read (image tree + reviewed tools).
TOOLS = ('backend/scripts/reconcile_team_pessoa.py', 'backend/scripts/release_preflight.py',
         *(f'deploy/{name}' for name in ('backend-release.sh', 'check_backend_schema.py', 'emit_schema_check.py',
                                         'schema_compatibility.py', 'docker-compose.yml', 'release_topology.py')))
CANDIDATE_PATHSPECS = ('backend/app', 'backend/migrations', 'backend/requirements.lock',
                       'backend/scripts/migrate.py', *TOOLS)
CANDIDATE_BLOBS = re.compile(CANDIDATE_TREE.pattern + '|' + '|'.join(re.escape(p) for p in TOOLS))
CONCURRENT_INDEX = re.compile(r'create\s+(?:unique\s+)?index\s+concurrently\s+(?:if\s+not\s+exists\s+)?'
                              r'(?:public\.)?"?([a-z0-9_]+)"?', re.IGNORECASE)
DEFAULT_TIMEOUTS = dict(grace_s=30, settle_s=4, migration_s=300, job_s=180, ready_s=120, active_wait_s=5)

CATALOG_PROBE = r'''
import base64, hashlib, json, sys, types, zlib
from sqlalchemy import create_engine
source = zlib.decompress(base64.b64decode(sys.argv[2])).decode('utf-8')
module = types.ModuleType('schema_compatibility')
exec(compile(source, 'schema_compatibility.py', 'exec'), module.__dict__)
engine = create_engine(sys.argv[1])
with engine.connect() as connection:
    connection.exec_driver_sql('SET TRANSACTION READ ONLY')
    catalog = module.capture_catalog(connection)
engine.dispose()
digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
print(json.dumps({kind: digest(value) for kind, value in catalog.items()}, sort_keys=True))
'''


def canonical(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def code_lines(body):
    return [line for line in body.decode('utf-8').splitlines() if not line.lstrip().startswith('--')]


def concurrent_indexes(body):
    """Index names a CONCURRENTLY migration creates (non-comment lines); empty if transactional."""
    return sorted({m.lower() for line in code_lines(body) for m in CONCURRENT_INDEX.findall(line)})


def verify_contained_exit(observed, data):
    """Refusal code for a container that did not stay stopped after SIGTERM, else ``None``."""
    state, host = data.get('State') or {}, data.get('HostConfig') or {}
    if data.get('RestartCount', 0) != observed['restart_count'] or state.get('StartedAt') != observed['started']:
        return 'restarted-after-signal'
    if (host.get('RestartPolicy') or {}).get('Name') != 'no':
        return 'restart-policy-not-persisted'
    if state.get('Running'):
        return 'still-running'
    if state.get('ExitCode') != 0:
        return 'ungraceful-exit'
    return None


def check_expect(ops, expect):
    """Names (never values) of every expected effect that does not hold exactly."""
    problems = []
    if expect.get('messages'):
        counts = ops.message_counts(sorted(expect['messages']))
        problems += ['messages' for k, n in expect['messages'].items() if counts.get(k) != n][:1]
    # Critical queues (list or zset) must be persistent (no TTL): the stability
    # snapshot excludes TTL keys, so a TTL would hide their loss. Absent = empty.
    for kind, read in (('redis_lists', ops.redis_list), ('redis_zsets', ops.redis_zset)):
        for key, expected in sorted((expect.get(kind) or {}).items()):
            ttl = ops.redis_pttl(key)
            if ttl != -1 and not (ttl == -2 and not expected):
                problems.append('redis-volatile-or-missing:' + key)
            elif read(key) != expected:
                problems.append(kind.removesuffix('s').replace('_', '-') + ':' + key)
    for prefix in expect.get('redis_absent_prefixes') or []:
        if ops.redis_keys(prefix):
            problems.append('redis-present:' + prefix)
    if expect.get('deliveries'):
        states = ops.delivery_states(sorted(expect['deliveries']))
        problems += ['deliveries' for k, v in expect['deliveries'].items() if states.get(k) != v][:1]
    return problems


class Transition:
    def __init__(self, spec, journal, ops, *, probes=(), decision=None, pause_at=None, clock=time.monotonic,
                 sleep=time.sleep, git=None):
        self.spec, self.j, self.ops = spec, journal, ops
        self.probes, self.decision, self.pause_at = list(probes), decision, pause_at
        self.clock, self.sleep, self.git = clock, sleep, git
        self.t = {**DEFAULT_TIMEOUTS, **(spec.get('timeouts') or {})}
        self.run12, self.prefix = spec['run_id'][:12], spec['prefix']
        self._files, self.inv, self.probe_count = None, 0, 0

    # -- journal views ------------------------------------------------------
    def checkpoint(self, name):
        if self.pause_at == name:
            self.j.append('paused', checkpoint=name)
            (self.j.dir / 'paused').write_text(name + '\n')
            while True:  # synthetic test hook: the rehearsal SIGKILLs this process here
                self.sleep(1)

    def epoch(self):
        """Seq of the last candidate containment: candidate steps before it no longer count."""
        last = self.j.last('candidate-contained')
        return last['seq'] if last else 0

    def done(self, step, since=0):
        return self.j.last('done', step, since) is not None

    def cdone(self, step):
        return self.done(step, self.epoch())

    def reached(self, name):
        since = self.epoch() if name in CANDIDATE_PHASES else 0
        return any(e.get('name') == name for e in self.j.find('phase', since=since))

    def phase(self, name):
        if not self.reached(name):
            self.j.append('phase', name=name)

    def refuse(self, code, step=None, **fields):
        self.j.append('refused', code=code, step=step, **fields)
        raise Refused(code)

    def wait(self, code, step, **fields):
        """Transient (active job/session): journaled, never sticky, exit code 4."""
        self.j.append('waiting', code=code, step=step, **fields)
        raise Refused(code)

    def observed(self):
        event = self.j.last('done', 'observe')
        require(event is not None, 'not-observed')
        return event

    def legacy(self):
        return self.observed()['legacy']

    def candidate_ids(self):
        event = self.j.last('done', 'candidate:create')
        return event['ids'] if event else {}

    def job_ids(self):
        return {e['id'] for e in self.j.find('job')}

    def files(self):
        if self._files is None:
            self._files = git_tree(self.spec['repo'], self.spec['candidate']['sha'], CANDIDATE_PATHSPECS,
                                   CANDIDATE_BLOBS, self.git)
        return self._files

    def manifest(self):
        files = self.files()
        sql = {p.split('/', 2)[2]: b for p, b in files.items() if re.fullmatch(r'backend/migrations/[^/]+\.sql', p)}
        return migration_manifest(files['backend/scripts/migrate.py'], sql)

    def dsn(self):
        return self.spec['database']['dsn']

    # -- validation on EVERY invocation ---------------------------------------
    def base_checks(self):
        """Local endpoint and owned topology, before any SQL or effect (every invocation)."""
        self.ops.guard_local()
        self.ops.verify_topology()

    def check_expectations(self, key):
        return check_expect(self.ops, self.spec[key])

    def revalidate(self):
        """Legacy and candidate identity/state/gates, every invocation, whatever the journal says."""
        if not self.done('observe'):
            return
        observed = self.observed()
        for role, item in self.legacy().items():
            data = self.ops.inspect(item['id']) or {}
            labels = (data.get('Config') or {}).get('Labels') or {}
            if (data.get('Id') != item['id'] or data.get('Image') != self.spec['legacy']['image']
                    or labels.get(OWNER_LABEL) != self.spec['run_id'] or (COMPOSE_PROJECT in labels) != item['compose']
                    or (item['compose'] and labels.get(COMPOSE_PROJECT) != self.spec['legacy']['project'])
                    or gates_of(data) != item['gates'] or host_exposed(data)):
                self.refuse('legacy-identity-changed', 'revalidate', role=role)
            resumed = self.j.last('done', f'legacy-resume:{role}')
            if resumed:
                # Back on purpose: same execution, original policy, no restart since.
                if (not (data.get('State') or {}).get('Running')
                        or (data.get('State') or {}).get('StartedAt') != resumed['started']
                        or data.get('RestartCount', 0) != resumed.get('restart_count', 0)
                        or ((data.get('HostConfig') or {}).get('RestartPolicy') or {}).get('Name') != item['policy']):
                    self.refuse('legacy-resumed-state-changed', 'revalidate', role=role)
            elif self.j.last('intent', f'legacy-resume:{role}'):
                pass  # start intended before a crash: running or not, identity/gates checked above
            elif self.done(f'exit:{role}'):
                code = verify_contained_exit(item, data)
                if code:
                    self.refuse('legacy-' + code, 'revalidate', role=role)
            else:
                # Not yet exited: same execution; policy original, or ``no`` once its change is intended.
                allowed = {item['policy']} if not self.j.last('intent', f'policy:{role}') else {item['policy'], 'no'}
                if self.done(f'policy:{role}'):
                    allowed = {'no'}
                if (data.get('RestartCount', 0) != item['restart_count']
                        or (data.get('State') or {}).get('StartedAt') != item['started']
                        or ((data.get('HostConfig') or {}).get('RestartPolicy') or {}).get('Name') not in allowed):
                    self.refuse('legacy-state-changed', 'revalidate', role=role)
        if observed.get('ledger_count') is None:
            self.refuse('observe-incomplete', 'revalidate')
        for role, identifier in self.candidate_ids().items():
            data = self.ops.inspect(identifier) or {}
            labels = (data.get('Config') or {}).get('Labels') or {}
            if (data.get('Id') != identifier or data.get('Image') != self.spec['candidate']['image']
                    or labels.get(COMPOSE_PROJECT) != self.spec['candidate']['project']
                    or labels.get(OWNER_LABEL) != self.spec['run_id'] or host_exposed(data)
                    or gates_of(data) != self.legacy()[role]['gates']):
                self.refuse('candidate-identity-changed', 'revalidate', role=role)

    def ip_map(self, ids):
        found = {}
        for identifier in ids:
            data = self.ops.inspect(identifier)
            address = data and ip_of(data, self.spec['network']['app'])
            if address:
                found[address] = identifier
        return found

    def check_scope(self, *, legacy_running, candidate_running=()):
        """Every owned container is known; only expected processes on networks, DB and Redis."""
        legacy = self.legacy()
        known = ({v['id'] for v in legacy.values()} | set(self.spec['support'].values())
                 | set(self.candidate_ids().values()) | self.job_ids() | set(self.probes))
        if self.ops.owned_containers(self.spec['run_id']) - known:
            self.refuse('orphan-owned-container')
        writers = ({legacy[r]['id'] for r in legacy_running} | set(self.probes)
                   | {self.candidate_ids()[r] for r in candidate_running})
        support = set(self.spec['support'].values())
        for name in ('app', 'edge'):
            _, members = self.ops.network_members(self.spec['network'][name])
            if members - (writers | (support if name == 'app' else set())):
                self.refuse('fifth-writer-network')
        ips = self.ip_map(writers)
        evolution_ip = next(iter(self.ip_map([self.spec['support']['evolution']])), None)
        for session in self.ops.pg_sessions():
            if session.get('addr') is None and session.get('app') in OBSERVER_APPS:
                continue  # read-only observer inside the owned Postgres container
            if session.get('addr') not in ips:
                self.refuse('fifth-writer-database')
        for client in self.ops.redis_clients():
            if client['addr'] == '127.0.0.1':
                continue  # ``docker exec redis-cli`` observers inside the owned Redis container
            if client['addr'] == evolution_ip and client.get('db') != '0':
                continue  # fake provider bookkeeping, never db0
            if client['addr'] not in ips:
                self.refuse('fifth-writer-redis')

    # -- jobs -------------------------------------------------------------------
    def job(self, step, name, *, image, args, env=None, network='app', stdin=None, wait=None):
        """Create (intent first) and run one owned job; replay adopts only the identical container.

        A job already running (left by a killed controller) is never signalled
        or restarted: awaited briefly, then reported active (exit 4).
        """
        network, env = self.spec['network'].get(network, network), env or {}
        ids = self.ops.job_find(name)
        recorded = [e['id'] for e in self.j.find('job', step) if e.get('name') == name]
        if len(ids) > 1 or (recorded and ids != recorded[-1:]):
            self.refuse('job-ambiguous', step)
        if ids:
            identifier = ids[0]
            data = self.ops.inspect(identifier) or {}
            labels = (data.get('Config') or {}).get('Labels') or {}
            if (labels.get(OWNER_LABEL) != self.spec['run_id'] or labels.get('pastorai.transition.job') != name
                    or not self.ops.job_matches(data, image=image, args=args, env=env, network=network)):
                self.refuse('job-mismatch', step)
            if not recorded:
                if not [e for e in self.j.find('intent', step) if e.get('name') == name]:
                    self.refuse('job-without-intent', step)
                self.j.append('job', step=step, name=name, id=identifier, adopted=True)
        else:
            self.j.append('intent', step=step, name=name)
            identifier = self.ops.job_create(name=name, kind=step.split(':', 1)[0], image=image, args=args,
                                             env=env, stdin=stdin is not None, network=network)
            self.j.append('job', step=step, name=name, id=identifier)
        state = (self.ops.inspect(identifier) or {}).get('State') or {}
        budget = wait if wait is not None else self.t['job_s']
        if state.get('Running'):
            budget = self.t['active_wait_s']  # adopted live job: observe, never take over
        elif state.get('Status') == 'created':
            self.checkpoint(f'job:{name}:before-start')
            if stdin is not None:
                self.ops.job_start(identifier, input=stdin, timeout=self.t['job_s'])
            else:
                self.ops.job_start(identifier)
        limit = self.clock() + budget
        while (state := (self.ops.inspect(identifier) or {}).get('State') or {}).get('Running'):
            if self.clock() >= limit:
                self.wait('job-active', step, job=identifier)
            self.sleep(0.5)
        return identifier, state.get('ExitCode'), self.ops.job_logs(identifier)

    def probe_name(self, kind):
        """Read-only probes are fresh per invocation: a stale exit/log is never reused."""
        self.probe_count += 1
        return f'{self.prefix}-job-{kind}-i{self.inv}-{self.probe_count}'

    def script(self, step, name, target, path, extra=(), env=None, stdin=None):
        args = self.ops.script_args(target, self.files()[path], extra)
        return self.job(step, name, image=self.spec['candidate']['image'], args=args, env=env, stdin=stdin)

    def source_probe(self, step, image, root, files):
        from rehearse_legacy_queue import RUNTIME_PROBE, lock_entries, runtime_mismatch
        expected = {path: sha256(data) for path, data in files.items()}
        lock = files['requirements.lock'].decode('utf-8')
        markers = sorted({m for _, _, m in lock_entries(lock) if m})
        _, code, out = self.job(step, self.probe_name(step.replace(':', '-')), image=image, network='none',
                                args=['-I', '-c', RUNTIME_PROBE, root, json.dumps(markers), json.dumps(sorted(expected))])
        if code != 0 or not out.strip():
            self.refuse('source-probe', step)
        observed = json.loads(out.strip().splitlines()[-1])
        if observed.get('rejected') or observed.get('missing') or observed.get('files') != expected:
            self.refuse('source-mismatch', step)
        if runtime_mismatch(lock, observed):
            self.refuse('runtime-mismatch', step)
        return canonical(expected)

    # -- legacy side ------------------------------------------------------------
    def observe(self):
        if not self.done('observe'):
            self.identify()
        if not self.reached('observed'):
            self.check_scope(legacy_running=ROLES)
            self.phase('observed')

    def identify(self):
        spec, ops = self.spec, self.ops
        legacy_image, candidate = spec['legacy']['image'], spec['candidate']
        ops.image(legacy_image)
        if (ops.image(candidate['image']).get('Config', {}).get('Labels') or {}).get(REVISION_LABEL) != candidate['sha']:
            self.refuse('candidate-revision-label')
        identities = {}
        for role in ROLES:
            identifier = spec['legacy']['containers'][role]
            data = ops.inspect(identifier)
            if not data or data.get('Id') != identifier or not RESOURCE_ID.fullmatch(identifier):
                self.refuse('legacy-identity')
            labels, host = (data.get('Config') or {}).get('Labels') or {}, data.get('HostConfig') or {}
            compose = role not in spec['legacy']['standalone']
            if (labels.get(OWNER_LABEL) != spec['run_id'] or data.get('Image') != legacy_image
                    or compose != (COMPOSE_PROJECT in labels)
                    or (compose and (labels.get(COMPOSE_PROJECT) != spec['legacy']['project']
                                     or labels.get(COMPOSE_SERVICE) != role))):
                self.refuse('legacy-topology')
            policy = (host.get('RestartPolicy') or {}).get('Name')
            if policy != 'always':
                self.refuse('legacy-restart-policy-unexpected')
            if host_exposed(data) or not (data.get('State') or {}).get('Running'):
                self.refuse('legacy-state')
            identities[role] = dict(id=identifier, name=data.get('Name', '').lstrip('/'), policy=policy,
                                    started=data['State']['StartedAt'], restart_count=data.get('RestartCount', 0),
                                    gates=gates_of(data), compose=compose)
        if ({identities[r]['name'] for r in ROLES} & set(candidate['names'].values())
                or ops.compose_ids(candidate['project']) or candidate['project'] == spec['legacy']['project']):
            self.refuse('candidate-name-or-project-conflict')
        from rehearse_legacy_queue import legacy_sources
        legacy_files = legacy_sources(spec['repo'])
        legacy_digest = self.source_probe('source:legacy', legacy_image, spec['legacy']['source_root'], legacy_files)
        tree = {p.removeprefix('backend/'): b for p, b in self.files().items() if CANDIDATE_TREE.fullmatch(p)}
        candidate_digest = self.source_probe('source:candidate', candidate['image'], '/app', tree)
        ledger = self.ops.ledger()
        self.j.append('done', step='observe', legacy=identities, ledger_count=len(ledger),
                      ledger_digest=canonical(ledger),
                      legacy_source=dict(sha=spec['legacy']['sha'], files=len(legacy_files), digest=legacy_digest),
                      candidate_source=dict(sha=candidate['sha'], files=len(tree), digest=candidate_digest))

    def contain(self):
        if self.reached('contained'):
            return
        for role in CONTAIN_ORDER:
            if self.done(f'exit:{role}'):
                continue
            item = self.legacy()[role]
            if not self.done(f'policy:{role}'):
                self.j.append('intent', step=f'policy:{role}')
                self.checkpoint(f'contain:{role}:before-policy')
                self.ops.update_restart(item['id'], 'no')
                self.checkpoint(f'contain:{role}:after-policy')
                policy = ((self.ops.inspect(item['id']) or {}).get('HostConfig') or {}).get('RestartPolicy') or {}
                if policy.get('Name') != 'no':
                    self.refuse('restart-policy-not-persisted', f'policy:{role}')
                self.j.append('done', step=f'policy:{role}', persisted='no')
            if not self.done(f'signal:{role}'):
                running = ((self.ops.inspect(item['id']) or {}).get('State') or {}).get('Running')
                if self.j.last('intent', f'signal:{role}') is None:
                    self.j.append('intent', step=f'signal:{role}')
                    self.ops.signal(item['id'])
                    self.checkpoint(f'contain:{role}:after-signal')
                elif running and self.decision == f'resignal:{role}':
                    self.j.append('decision', value=self.decision)
                    self.ops.signal(item['id'])
                elif running and not self.await_exit(role, item, self.t['grace_s']):
                    # Delivery unknown after a crash: never resend blindly (a second
                    # SIGTERM force-quits Uvicorn). Human ``resignal:<role>``.
                    self.refuse('signal-ambiguous', f'signal:{role}')
                self.j.append('done', step=f'signal:{role}')
            if not self.await_exit(role, item, self.t['grace_s']):
                self.refuse('graceful-timeout', f'exit:{role}')  # no SIGKILL: human decision
            data = self.ops.inspect(item['id']) or {}
            code = verify_contained_exit(item, data)
            if code:
                self.refuse(code, f'exit:{role}')
            self.j.append('done', step=f'exit:{role}', finished=data['State'].get('FinishedAt'))
        self.check_scope(legacy_running=())
        self.phase('contained')

    def await_exit(self, role, item, timeout):
        limit = self.clock() + timeout
        while True:
            data = self.ops.inspect(item['id']) or {}
            state = data.get('State') or {}
            if data.get('RestartCount', 0) != item['restart_count'] or state.get('StartedAt') != item['started']:
                self.refuse('restarted-after-signal', f'exit:{role}')
            if not state.get('Running'):
                return True
            if self.clock() >= limit:
                return False
            self.sleep(0.2)

    def snapshot(self):
        """Domain rows + PERSISTENT Redis db0 keys. TTL keys (heartbeats, dedup markers) are not
        compared; critical queues are separately required to be persistent by the expectations."""
        return dict(db=canonical(self.ops.db_snapshot()), redis=canonical(self.ops.redis_snapshot()))

    def baseline_snapshot(self):
        event = self.j.last('snapshot')
        return {k: event[k] for k in ('db', 'redis')} if event else None

    def settle(self):
        """Expected effects of the drain first (exactly once per item), only then stability."""
        if self.reached('settled'):
            return
        problems = self.check_expectations('expect_settled')
        if problems:
            self.refuse('expectation-mismatch', 'settle', problems=problems)
        first = self.snapshot()
        self.sleep(self.t['settle_s'])
        if self.snapshot() != first:
            self.refuse('unstable-after-drain', 'settle')
        self.check_scope(legacy_running=())
        self.j.append('done', step='settle')
        self.j.append('snapshot', reason='settled', redis_volatile_excluded=self.ops.redis_volatile_count(), **first)
        self.phase('settled')

    def critical_state(self, step):
        """Re-run the settled expectations (critical queues incl. TTL guard) at an effect boundary."""
        problems = self.check_expectations('expect_settled')
        if problems:
            self.refuse('expectation-mismatch', step, problems=problems)

    # -- reconciliation (initial_transition_reconcile) ---------------------------
    def reconcile(self):
        from initial_transition_reconcile import reconcile
        reconcile(self)

    def recover_reconciliation(self):
        from initial_transition_reconcile import recover_reconciliation
        recover_reconciliation(self)

    def preflight(self):
        if self.reached('preflighted'):
            return
        counts = self.ops.backfill_candidates()
        if counts != {'membro_por_vinculo': 0, 'numero_atendimento': 0}:
            self.refuse('backfill-candidates', 'preflight', counts=counts)
        _, code, _ = self.script('preflight', self.probe_name('release-preflight'), '/app/scripts/release_preflight.py',
                                 'backend/scripts/release_preflight.py', env={'MIGRATION_DATABASE_URL': self.dsn()})
        if code != 0:
            self.refuse('release-preflight', 'preflight', exit_code=code)
        self.pre_ddl_state('preflight')
        self.j.append('done', step='preflight')
        self.phase('preflighted')

    def pre_ddl_state(self, step):
        """Fresh: baseline ledger, exact pending set, last snapshot, no DDL trace, legacy contained, scope."""
        manifest, ledger = self.manifest(), self.ops.ledger()
        if (len(ledger) != self.observed()['ledger_count'] or canonical(ledger) != self.observed()['ledger_digest']
                or set(ledger) - set(manifest)):
            self.refuse('ledger-not-baseline', step)
        if [n for n in manifest if n not in set(ledger)] != self.spec['expected_pending']:
            self.refuse('pending-set-mismatch', step)
        if self.ops.invalid_indexes() or self.ops.index_builds() or self.migration_sessions():
            self.refuse('ddl-trace-before-marker', step)
        if [e for e in self.j.find('job') if e.get('step', '').startswith('migration:')] or self.candidate_ids():
            self.refuse('ddl-trace-before-marker', step)
        if self.baseline_snapshot() != self.snapshot():
            self.refuse('writer-after-settle', step)
        self.critical_state(step)
        for role, item in self.legacy().items():
            if verify_contained_exit(item, self.ops.inspect(item['id']) or {}):
                self.refuse('legacy-not-contained', step, role=role)
        self.check_scope(legacy_running=())

    def migration_sessions(self):
        return [s for s in self.ops.pg_sessions() if (s.get('app') or '').startswith('pastorai-mig-')]

    # -- DDL ----------------------------------------------------------------------
    def migrate(self):
        if self.reached('migrated'):
            return
        manifest = self.manifest()
        if not self.j.find('ddl-marker'):
            self.pre_ddl_state('ddl-marker')  # immediately before the irrevocable marker
            ledger = set(self.ops.ledger())
            self.j.append('ddl-marker', pending=[n for n in manifest if n not in ledger], irrevocable=True)
            self.phase('ddl-started')
        pending = self.j.last('ddl-marker')['pending']
        for index, name in enumerate(pending, 1):
            if not self.done(f'migration:{name}'):
                self.migration(index, name)
        if self.ops.ledger() != sorted(manifest):
            self.refuse('ledger-not-manifest', 'migrate')
        self.phase('migrated')

    def migration(self, index, name):
        """One ``migrate.py apply`` per job; any doubt about the outcome is a sticky refusal.

        Retry only by human ``retry-migration:<name>`` and only when nothing of
        the failed attempt remains: no invalid index, none of its CONCURRENTLY
        indexes exists at all (a valid index without ledger row is NOT proof of
        application), no build, no session, no running job, ledger still absent.
        """
        step = f'migration:{name}'
        body = self.files()['backend/migrations/' + name]
        indexes = concurrent_indexes(body)
        is_concurrent = any('index concurrently' in line.lower() for line in code_lines(body))
        attempt = 1 + len([e for e in self.j.find('decision') if e.get('value') == f'retry-migration:{name}'])
        last = next((e for e in reversed(self.j.find('refused', step)) if e['code'] != 'retry-precondition'), None)
        if last and last.get('attempt') == attempt:
            if self.decision != f'retry-migration:{name}' or last['code'] not in RETRIABLE:
                self.refuse(last['code'], step, attempt=attempt)
            if (self.ops.invalid_indexes() or self.ops.index_exists(indexes) or name in self.ops.ledger()
                    or self.ops.index_builds() or self.migration_sessions() or self.running_migration_jobs()):
                self.refuse('retry-precondition', step, attempt=attempt)
            self.j.append('decision', value=self.decision, step=step, previous_attempt=attempt)
            attempt += 1
        job = f'{self.prefix}-mig-{index:02d}-a{attempt}'
        app = f'pastorai-mig-{self.run12}-{index:02d}-a{attempt}'
        if not self.ops.job_find(job) and not [e for e in self.j.find('job', step) if e['name'] == job]:
            if name in self.ops.ledger():
                self.refuse('ledger-ahead-of-journal', step, attempt=attempt)
            if self.migration_sessions() or self.running_migration_jobs():
                self.wait('migration-session-active', step, attempt=attempt)
            self.check_scope(legacy_running=())
            self.j.append('migration', step=step, attempt=attempt, job=job, app=app, concurrent=is_concurrent)
        args = ['scripts/migrate.py', 'apply', name, '--yes', *(['--no-transaction'] if is_concurrent else [])]
        identifier, code, _ = self.job(step, job, image=self.spec['candidate']['image'], args=args,
                                       env={'MIGRATION_DATABASE_URL': self.dsn(), 'PGAPPNAME': app},
                                       wait=self.t['migration_s'])
        if [s for s in self.ops.pg_sessions() if s.get('app') == app] or app in self.ops.index_builds():
            self.wait('migration-session-active', step, attempt=attempt)
        applied = name in self.ops.ledger()
        if code == 0 and applied:
            self.j.append('done', step=step, attempt=attempt, job=identifier)
            return
        if applied:
            self.refuse('migration-ambiguous-ledger-without-success', step, attempt=attempt)
        if is_concurrent:
            if self.ops.invalid_indexes():
                self.refuse('concurrent-index-invalid', step, attempt=attempt, exit_code=code)
            if self.ops.index_exists(indexes):
                self.refuse('concurrent-index-present-ledger-absent', step, attempt=attempt, exit_code=code)
            self.refuse('concurrent-failed-decision', step, attempt=attempt, exit_code=code)
        self.refuse('migration-ambiguous-exit0-no-ledger' if code == 0 else 'migration-failed', step,
                    attempt=attempt, exit_code=code)

    def running_migration_jobs(self):
        return [e['id'] for e in self.j.find('job') if e.get('step', '').startswith('migration:')
                and ((self.ops.inspect(e['id']) or {}).get('State') or {}).get('Running')]

    def verify_schema(self):
        """Candidate checker + catalogue vs the independent reference, fresh on every invocation."""
        manifest = self.manifest()
        _, code, _ = self.script('checker', self.probe_name('schema-checker'), '/tmp/check_backend_schema.py',
                                 'deploy/check_backend_schema.py',
                                 env={'DATABASE_URL': self.dsn(), 'EXPECTED_MIGRATIONS': json.dumps(manifest)})
        if code != 0:
            self.refuse('candidate-checker', 'checker', exit_code=code)
        module = base64.b64encode(zlib.compress(self.files()['deploy/schema_compatibility.py'], 9)).decode()
        _, code, out = self.job('catalog', self.probe_name('catalog'), image=self.spec['candidate']['image'],
                                args=['-I', '-c', CATALOG_PROBE, self.dsn(), module])
        if code != 0 or not out.strip():
            self.refuse('catalog-probe', 'catalog')
        live, expected = json.loads(out.strip().splitlines()[-1]), self.spec['expected_catalog']
        if live != expected:
            self.refuse('catalog-drift', 'catalog', kinds=sorted(k for k in expected if live.get(k) != expected[k]))
        self.j.append('done', step='schema', digest=canonical(live), invocation=self.inv)
        self.phase('schema-verified')

    # -- candidate side -------------------------------------------------------------
    def candidate(self):
        from initial_transition_candidate import run_candidate
        run_candidate(self)

    def promote(self):
        from initial_transition_candidate import run_promote
        run_promote(self)

    def contain_candidate(self, reason):
        from initial_transition_candidate import contain_candidate
        contain_candidate(self, reason)

    # -- entry points -----------------------------------------------------------------
    def run(self, until=None):
        if self.reached(TERMINAL):
            self.refuse('legacy-resumed-terminal', 'run')
        if self.j.find('intent', 'legacy-resume'):
            # The decision to resume the legacy is exclusive and durable: only
            # ``resume-legacy`` may continue; nothing here may move towards DDL.
            self.refuse('legacy-resume-in-progress', 'run')
        self.base_checks()  # a refusal here performs no containment either: the endpoint is untrusted
        steps = (('observed', self.observe), ('contained', self.contain), ('settled', self.settle),
                 ('reconciled', self.reconcile), ('preflighted', self.preflight), ('migrated', self.migrate),
                 ('schema-verified', self.verify_schema), ('candidate-ready', self.candidate),
                 ('promoted', self.promote))
        try:
            self.revalidate()
            for name, function in steps:
                if name == 'schema-verified' and self.reached('promoted'):
                    continue
                function()
                if name == until:
                    return name
        except Refused as exc:
            if (str(exc) not in WAIT_CODES | {'candidate-contained-decision-required'} and self.j.find('ddl-marker')
                    and not self.reached('promoted') and self.candidate_ids()):
                self.contain_candidate(str(exc))  # post-DDL: candidate stopped, never the legacy back
            raise
        return 'promoted'

    def resume_token(self):
        return f'RETOMAR-LEGADO-PRE-DDL:{self.spec["run_id"]}:{self.j.digest()}'

    def resume_legacy(self, confirmation, expected_token):
        from initial_transition_resume import resume_legacy
        resume_legacy(self, confirmation, expected_token)

    def resume_preconditions(self):
        from initial_transition_resume import resume_preconditions
        resume_preconditions(self)


# -- CLI ----------------------------------------------------------------------
def load_spec(path):
    spec = json.loads(read_regular(path))
    require(isinstance(spec, dict) and spec.get('version') == 1 and spec.get('synthetic') is True, 'spec')
    require(re.fullmatch(r'[0-9a-f]{32}', spec.get('run_id', '')), 'spec')
    require(spec.get('prefix') == 'pastorai-synthetic-transition-' + spec['run_id'][:12], 'spec-prefix')
    require(SHA.fullmatch(spec['candidate']['sha']) and SHA.fullmatch(spec['legacy']['sha']), 'spec')
    require(IMAGE_ID.fullmatch(spec['legacy']['image']) and IMAGE_ID.fullmatch(spec['candidate']['image']), 'spec')
    require(DSN.fullmatch(spec['database']['dsn']), 'dsn-not-owned-alias')
    require(all(RESOURCE_ID.fullmatch(i) for i in (*spec['support'].values(), *spec['network'].values(),
                                                   *spec['legacy']['containers'].values())), 'spec-ids')
    for key in ('release_root', 'repo'):
        no_symlink(spec[key])
    spec['_compose_bytes'] = read_regular(spec['candidate']['compose_file'])
    require(sha256(spec['_compose_bytes']) == spec['candidate']['compose_sha256'], 'candidate-compose-changed')
    return spec


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('run', 'status', 'resume-legacy'):
        command = sub.add_parser(name)
        command.add_argument('--spec', type=Path, required=True)
        command.add_argument('--state', type=Path, required=True)
        command.add_argument('--allow-probe', action='append', default=[])
        if name == 'run':
            command.add_argument('--until', choices=PHASES)
            command.add_argument('--decision')
            command.add_argument('--pause-at')
        if name == 'resume-legacy':
            command.add_argument('--confirm', required=True)
            command.add_argument('--pause-at')
    args = parser.parse_args(argv)
    try:
        spec = load_spec(args.spec)
        journal = Journal(args.state).open()
    except Refused as exc:
        print(json.dumps({'status': 'refused', 'code': str(exc)}))
        return EXIT_BUSY if str(exc) == 'controller-busy' else EXIT_USAGE
    try:
        return dispatch(args, spec, journal)
    finally:
        journal.close()


def dispatch(args, spec, journal):
    digest = canonical({k: v for k, v in spec.items() if k != '_compose_bytes'})
    init = journal.last('init')
    if init is None:
        journal.append('init', spec_sha256=digest, run_id=spec['run_id'])
    elif init['spec_sha256'] != digest:
        print(json.dumps({'status': 'refused', 'code': 'spec-changed'}))
        return EXIT_USAGE
    transition = Transition(spec, journal, DockerOps(spec), probes=args.allow_probe,
                            decision=getattr(args, 'decision', None), pause_at=getattr(args, 'pause_at', None))
    phases = lambda: [e['name'] for e in journal.find('phase')]
    if args.command == 'status':
        pre_ddl = not journal.find('ddl-marker') and transition.reached('contained')
        print(json.dumps({'status': 'ok', 'phases': phases(), 'epoch': transition.epoch(),
                          'last_refusal': (journal.last('refused') or {}).get('code'),
                          'resume_token': transition.resume_token() if pre_ddl else None}, sort_keys=True))
        return 0
    expected_token = transition.resume_token()  # before this invocation is journaled
    transition.inv = journal.append('invocation', command=args.command, probes=args.allow_probe,
                                    decision=getattr(args, 'decision', None),
                                    pause_at=getattr(args, 'pause_at', None))['seq']
    try:
        if args.command == 'run':
            reached = transition.run(getattr(args, 'until', None))
        else:
            transition.resume_legacy(args.confirm, expected_token)
            reached = TERMINAL
    except Refused as exc:
        code = str(exc)
        print(json.dumps({'status': 'waiting' if code in WAIT_CODES else 'refused', 'code': code,
                          'phases': phases(), 'epoch': transition.epoch()}))
        return EXIT_WAIT if code in WAIT_CODES else EXIT_REFUSED
    print(json.dumps({'status': 'ok', 'reached': reached, 'phases': phases()}))
    return 0


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
