"""Local-only database slice of the first-transition adapter.

Exact Git blobs, the reviewed migration CLI and the durable transition journal
are reused. There is deliberately no host/SSH/Redis/deploy transport here.
Containment/backup evidence is labelled local simulation, never production
proof. Completion holds at database-verified; it cannot start an application,
resume the legacy or change a gate. See the existing release runbook.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from uuid import UUID

from initial_transition_files import Journal, git_tree, read_regular
from initial_transition_ops import BACKFILL_SQL, Refused, require

APPLICATION_SHA = 'afdfb78d71a53f2861632806e13cdda4662d7d63'
EXECUTOR_SHA = '37c7d68d60b6f86cfb1fe75d4c720530537845d6'
ROLES = ('backend', 'cron-worker', 'broadcast-worker', 'queue-worker')
MISSING = frozenset({
    '20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql',
    '20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql',
    '20260925_183811_preserve_platform_admins_on_tenant_deletion.sql',
    '20260926_120446_platform_jev_settings.sql',
})
REVIEWED_CONCURRENT = {'20261023_100001_ai_usage_tenant_created_idx.sql': ('ai_usage_logs_igreja_created_at_idx',), '20261023_110001_notification_outbox_pending_created_idx.sql': ('notification_outbox_pending_igreja_created_idx',), '20261023_110002_notification_outbox_retry_created_idx.sql': ('notification_outbox_retry_igreja_created_idx',), '20261023_110003_notification_outbox_expired_lease_idx.sql': ('notification_outbox_lease_igreja_claimed_idx',), '20261023_110004_messages_pending_agent_created_idx.sql': ('messages_pending_agent_igreja_created_idx',), '20261023_110005_work_queue_pending_created_idx.sql': ('work_queue_pending_igreja_created_idx',), '20261028_100001_private_erasure_requests_overview_idx.sql': ('private_erasure_requests_overview_idx',), '20261028_100002_private_resume_delivered_overview_idx.sql': ('private_resume_delivered_overview_idx',)}

SQL_PATH = re.compile(r'backend/migrations/[A-Za-z0-9_.-]+\.sql')
INDEX = re.compile(r'create\s+(?:unique\s+)?index\s+concurrently\s+(?:if\s+not\s+exists\s+)?'
                   r'(?:public\.)?"?([a-z0-9_]+)"?', re.I)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def adapter_sources():
    root = Path(__file__).resolve().parent
    return tuple((name, hashlib.sha256(read_regular(root / name)).hexdigest()) for name in (
        'first_transition_adapter.py', 'first_transition_local_backup.py',
        'first_transition_host_contract.py', 'first_transition_host_transport.py', 'initial_transition_files.py',
        'initial_transition_ops.py', 'release_topology.py'))


PREFLIGHT_PROBE = r'''
import json,os,sys
try:
    import psycopg2
    sys.path.insert(0,sys.argv[1])
    import release_preflight
    connection=psycopg2.connect(os.environ['MIGRATION_DATABASE_URL'],connect_timeout=3,hostaddr='127.0.0.1',
        sslmode='disable',application_name='igreja12-local-preflight',
        options='-c search_path=pg_catalog,public -c statement_timeout=5000 -c lock_timeout=2000 -c row_security=off')
    try:
        connection.autocommit=True
        with connection.cursor() as cursor:
            cursor.execute("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()")
            if cursor.fetchone()[0]!='igreja12-local-disposable:'+os.environ['FIRST_TRANSITION_LOCAL_NONCE']:
                raise RuntimeError('unowned disposable database')
        connection.autocommit=False
        report=release_preflight.inspect_connection(connection)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('transaction_read_only')")
            readonly=cursor.fetchone()[0]=='on'
        output=dict(status='ok',read_only=readonly,files=len(report.migrations),
            applied=sum(row.state=='APLICADA' for row in report.migrations),
            pending=sum(row.state=='PENDENTE' for row in report.migrations),
            unknown=report.unknown_applied_count,fk_findings=len(report.fk_findings),
            duplicates=len(report.duplicate_findings),missing_tables=len(report.missing_backup_tables),
            definer_examined=len(report.definer_examined),
            definer_unverified=len(report.definer_unverified),definer_findings=len(report.definer_findings))
        print(json.dumps(output,sort_keys=True))
    finally:
        connection.rollback()
        connection.close()
except BaseException:
    print('{"status":"refused","code":"full-preflight-failed"}')
    sys.exit(3)
'''

PREFLIGHT_COUNTS = frozenset({'files', 'applied', 'pending', 'unknown', 'fk_findings',
                            'duplicates', 'missing_tables', 'definer_examined',
                            'definer_unverified', 'definer_findings'})


def preflight_summary(raw, files, applied):
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise Refused('full-preflight-output') from None
    require(isinstance(data, dict) and set(data) == PREFLIGHT_COUNTS | {'status', 'read_only'},
            'full-preflight-output')
    require(data['status'] == 'ok' and data['read_only'] is True
            and all(type(data[k]) is int and 0 <= data[k] <= 10**9 for k in PREFLIGHT_COUNTS),
            'full-preflight-output')
    require(data['files'] == files and data['applied'] == applied
            and data['pending'] == files - applied, 'full-preflight-output')
    return data


def require_clean_preflight(summary, *, complete):
    require(all(summary[key] == 0 for key in ('unknown', 'fk_findings', 'duplicates',
                                            'missing_tables', 'definer_findings')),
            'full-preflight-findings')
    if complete:
        require(summary['definer_unverified'] == 0, 'full-preflight-unverified')


@dataclass(frozen=True)
class Migration:
    name: str
    sql: bytes = field(repr=False)

    @property
    def sha256(self):
        return hashlib.sha256(self.sql).hexdigest()

    @property
    def indexes(self):
        code = '\n'.join(line for line in self.sql.decode().splitlines()
                         if not line.lstrip().startswith('--'))
        return tuple(sorted(set(match.lower() for match in INDEX.findall(code))))

    @property
    def concurrent(self):
        return bool(self.indexes)


@dataclass(frozen=True)
class Plan:
    application_sha: str
    executor_sha: str
    migrations: tuple[Migration, ...]
    baseline: tuple[str, ...]
    executor: bytes = field(repr=False)
    preflight: bytes = field(repr=False)
    adapter_sources: tuple[tuple[str, str], ...]

    @property
    def pending(self):
        return tuple(m for m in self.migrations if m.name not in self.baseline)

    @property
    def digest(self):
        return digest([self.application_sha, self.executor_sha, self.adapter_sources,
                       hashlib.sha256(self.executor).hexdigest(), hashlib.sha256(self.preflight).hexdigest(),
                       hashlib.sha256(PREFLIGHT_PROBE.encode()).hexdigest(), self.baseline,
                       [(m.name, m.sha256) for m in self.migrations]])

    def report(self):
        return dict(application_sha=self.application_sha, executor_sha=self.executor_sha,
                    plan_digest=self.digest, baseline=len(self.baseline), pending=len(self.pending),
                    active=len(self.migrations), concurrent=sum(m.concurrent for m in self.pending),
                    production_ready=False, stops_at='database-verified',
                    preflight_sha256=hashlib.sha256(self.preflight).hexdigest(),
                    adapter_sources_digest=digest(self.adapter_sources))


def prepare(repo: Path, application_sha=APPLICATION_SHA, executor_sha=EXECUTOR_SHA):
    require(application_sha == APPLICATION_SHA and executor_sha == EXECUTOR_SHA, 'unreviewed-release')
    files = git_tree(repo, application_sha, ('backend/migrations',), SQL_PATH)
    migrations = tuple(Migration(Path(name).name, sql) for name, sql in sorted(files.items())
                       if b'OPERATIONAL_AUTHORIZATION=BLOCKED' not in sql)
    baseline = tuple(m.name for m in migrations if m.name < '20261015' and m.name not in MISSING)
    runner = 'backend/scripts/migrate.py'
    executor = git_tree(repo, executor_sha, (runner,), re.compile(re.escape(runner)))
    require(runner in executor, 'executor-missing')
    probe = 'backend/scripts/release_preflight.py'
    probes = git_tree(repo, application_sha, (probe,), re.compile(re.escape(probe)))
    require(probe in probes, 'preflight-missing')
    plan = Plan(application_sha, executor_sha, migrations, baseline, executor[runner], probes[probe], adapter_sources())
    require((len(migrations), len(baseline), len(plan.pending)) == (129, 78, 51), 'release-shape')
    require(MISSING <= {m.name for m in migrations}, 'baseline-missing-set')
    require(all(not re.search(r'\bconcurrently\b', '\n'.join(
        line for line in m.sql.decode().splitlines() if not line.lstrip().startswith('--')), re.I)
        or m.name in REVIEWED_CONCURRENT for m in plan.pending), 'unreviewed-concurrent-form')
    require({m.name: m.indexes for m in plan.pending if m.concurrent} == REVIEWED_CONCURRENT,
            'concurrent-set')
    return plan


def local_endpoint(url, *, restore=False):
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == 'postgresql' and parsed.hostname == '127.0.0.1'
                 and parsed.username == 'postgres' and parsed.password == 'synthetic-only'
                 and (bool(re.fullmatch(r'/first_transition_restore_[0-9a-f]{32}', parsed.path))
                      if restore else parsed.path == '/first_transition_test')
                 and not parsed.query and not parsed.fragment
                 and parsed.port is not None and 0 < parsed.port < 65536)
    except (TypeError, ValueError):
        valid = False
    require(valid, 'local-disposable-endpoint-required')


def _full_preflight_at(plan, url, applied, nonce):
    # Both accepted database names are exclusively local disposable targets.
    local_endpoint(url, restore=bool(re.fullmatch(
        r'/first_transition_restore_[0-9a-f]{32}', urlsplit(url).path)))
    with tempfile.TemporaryDirectory(prefix='igreja12-first-transition-preflight-') as directory:
        root = Path(directory)
        scripts = root / 'scripts'
        scripts.mkdir()
        (root / 'migrations').mkdir()
        (scripts / 'migrate.py').write_bytes(plan.executor)
        (scripts / 'release_preflight.py').write_bytes(plan.preflight)
        for migration in plan.migrations:
            (root / 'migrations' / migration.name).write_bytes(migration.sql)
        env = dict(PATH='/usr/bin:/bin', PYTHON_DOTENV_DISABLED='1',
                   MIGRATION_DATABASE_URL=url, FIRST_TRANSITION_LOCAL_NONCE=nonce)
        try:
            result = subprocess.run([sys.executable, '-c', PREFLIGHT_PROBE, str(scripts)],
                                    cwd=root, env=env, capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            raise Refused('full-preflight-failed') from None
        require(result.returncode == 0, 'full-preflight-failed')
        return preflight_summary(result.stdout, len(plan.migrations), applied)


@dataclass(frozen=True)
class LocalEvidence:
    """A test receipt, bound to plan/catalog/ledger. Never a real backup receipt."""
    plan_digest: str
    baseline_digest: str
    stopped_roles: tuple[str, ...] = ROLES
    ingress_blocked: bool = True
    backup_rehearsal_requested: bool = True
    queue_preservation_assumed: bool = True
    support_preserved: bool = True
    gates_preserved: bool = True
    kind: str = 'local-simulation'
    host_digest: str | None = None

    @classmethod
    def synthetic(cls, plan_digest, baseline_digest, *, host_digest=None):
        return cls(plan_digest, baseline_digest, host_digest=host_digest)

    def validate(self, plan_digest, baseline_digest):
        require(self.kind == 'local-simulation' and self.plan_digest == plan_digest
                and self.baseline_digest == baseline_digest and self.stopped_roles == ROLES
                and (self.host_digest is None or isinstance(self.host_digest, str)
                     and re.fullmatch('[0-9a-f]{64}', self.host_digest))
                and all(value is True for value in (self.ingress_blocked, self.backup_rehearsal_requested,
                        self.queue_preservation_assumed, self.support_preserved, self.gates_preserved)),
                'local-evidence-mismatch')


class LocalDatabase:
    """Literal loopback, dedicated DB and caller-owned disposable marker, before DDL.

    Reads return ledger, catalog metadata and aggregate findings only. No row
    payloads, queue contents or row digests are read. Another client connection
    is refused, even idle. This plus a DB advisory lock is a local test boundary,
    not a proof of production quiescence or full data preservation.
    """
    def __init__(self, url, nonce, *, restore=False):
        local_endpoint(url, restore=restore)
        try:
            require(str(UUID(nonce)) == nonce, 'disposable-marker')
        except (ValueError, TypeError, AttributeError):
            raise Refused('disposable-marker') from None
        self._url, self._nonce, self.conn = url, nonce, None

    def __enter__(self):
        import psycopg2
        try:
            self.conn = psycopg2.connect(self._url, connect_timeout=3,hostaddr='127.0.0.1', sslmode='disable', options='',
                                         application_name='igreja12-first-transition-local')
            self.conn.autocommit = True
            with self.conn.cursor() as cur:
                cur.execute("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()")
                require(cur.fetchone()[0] == 'igreja12-local-disposable:' + self._nonce, 'disposable-marker')
                cur.execute("SELECT system_identifier::text, (SELECT oid FROM pg_database WHERE datname=current_database()) FROM pg_control_system()")
                system, database_oid = cur.fetchone()
                self.identity = digest([system, database_oid, self._nonce])
                cur.execute('SELECT pg_try_advisory_lock(12712951)')
                require(cur.fetchone()[0] is True, 'adapter-busy')
            return self
        except BaseException as exc:
            self.__exit__(None, None, None)
            if isinstance(exc, Exception) and not isinstance(exc, Refused):
                raise Refused('local-database-unavailable-or-unowned') from None
            raise

    def __exit__(self, *_):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def observe(self):
        try:
            return self._observe()
        except Refused:
            raise
        except Exception:
            raise Refused('database-observation-failed') from None

    def _observe(self):
        with self.conn.cursor() as cur:
            cur.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
            try:
                cur.execute("SET LOCAL statement_timeout='3s'")
                cur.execute('SET LOCAL search_path=pg_catalog,public')
                cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datid=(SELECT oid FROM pg_database WHERE datname=current_database()) AND pid<>pg_backend_pid() AND backend_type='client backend'")
                require(cur.fetchone()[0] == 0, 'other-database-client')
                cur.execute('SELECT name FROM public.schema_migrations ORDER BY name COLLATE "C"')
                ledger = tuple(row[0] for row in cur.fetchall())
                cur.execute("SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT (i.indisvalid AND i.indisready) ORDER BY c.relname")
                invalid = tuple(row[0] for row in cur.fetchall())
                cur.execute("SELECT c.oid,c.relname,c.relkind,a.attnum,a.attname,a.atttypid,a.attnotnull FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped WHERE n.nspname='public' ORDER BY c.oid,a.attnum")
                catalog = digest(cur.fetchall())
                cur.execute("SELECT c.relname,pg_get_indexdef(i.indexrelid) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname")
                indexes = {name: digest(definition) for name, definition in cur.fetchall()}
                cur.execute('SELECT count(*) FROM (SELECT 1 FROM public.app_users WHERE pessoa_id IS NOT NULL GROUP BY igreja_id,pessoa_id HAVING count(*)>1) s')
                duplicates = cur.fetchone()[0]
                cur.execute('SELECT count(*) FROM public.celula_solicitacao r WHERE r.celula_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.celulas c WHERE c.id=r.celula_id AND c.igreja_id=r.igreja_id)')
                invalid_links = cur.fetchone()[0]
                cur.execute('SELECT count(*) FROM public.pessoas WHERE apto_proxima_cd IS TRUE')
                aptitude_backfill = cur.fetchone()[0]
                cur.execute(BACKFILL_SQL)
                backfills = cur.fetchone()[0]
                cur.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname")
                relations = tuple(row[0] for row in cur.fetchall())
                return dict(ledger=ledger, invalid=invalid, catalog=catalog, relations=relations, indexes=indexes,
                            duplicates=duplicates, invalid_links=invalid_links,
                            aptitude_backfill=aptitude_backfill, backfills=backfills)
            finally:
                cur.execute('ROLLBACK')

    def full_preflight(self, plan, applied):
        return _full_preflight_at(plan, self._url, applied, self._nonce)

    def rehearse_backup(self, plan):
        from first_transition_local_backup import rehearse_backup
        return rehearse_backup(self, plan)

    def apply(self, plan, migration, *, timeout=300):
        """One exact SQL blob through the exact reviewed CLI, fresh connection.

        The environment is constructed, never inherited. stdout/stderr remain
        captured in this process and are discarded; errors expose fixed codes.
        """
        with tempfile.TemporaryDirectory(prefix='igreja12-first-transition-sql-') as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            (root / 'migrations').mkdir()
            (root / 'scripts/migrate.py').write_bytes(plan.executor)
            (root / 'migrations' / migration.name).write_bytes(migration.sql)
            args = [sys.executable, str(root / 'scripts/migrate.py'), 'apply', migration.name, '--yes']
            if migration.concurrent:
                args.append('--no-transaction')
            env = dict(PATH='/usr/bin:/bin', PYTHON_DOTENV_DISABLED='1',
                       MIGRATION_DATABASE_URL=self._url, PGAPPNAME='igreja12-local-migration')
            try:
                result = subprocess.run(args, cwd=root, env=env, capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                raise Refused('migration-timeout') from None
            except OSError:
                raise Refused('migration-executor-unavailable') from None
            require(result.returncode == 0, 'migration-failed')


def reviewed_indexes(migration, observation):
    require(set(migration.indexes) <= observation['indexes'].keys(), 'reviewed-index-missing')
    return {name: observation['indexes'][name] for name in migration.indexes}


def baseline_digest(observation):
    return digest([observation['ledger'], observation['catalog']])


def step_invariants(observation):
    require(not observation['invalid'], 'invalid-index')
    require(observation['duplicates'] == 0 and observation['invalid_links'] == 0,
            'aggregate-preflight-finding')


def pre_ddl_findings(observation):
    step_invariants(observation)
    remaining_pre_ddl_gates(observation)


def remaining_pre_ddl_gates(observation):
    applied = set(observation['ledger'])
    gates = (
        ('20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql',
         observation['backfills']['membro_por_vinculo']),
        ('20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql',
         observation['backfills']['numero_atendimento']),
        ('20261017_230000_uv_marcos_conclusao.sql', observation['aptitude_backfill']),
    )
    require(all(name in applied or candidates == 0 for name, candidates in gates),
            'pre-ddl-backfill-candidate')


def validate_clone_receipt(backup, plan, identity, baseline):
    require(isinstance(backup, dict) and backup.get('plan_digest') == plan.digest
            and backup.get('source_identity') == identity and backup.get('baseline_digest') == baseline
            and backup.get('restore_verified') is True, 'clone-receipt-invalid')
    clone = backup.get('clone_rehearsal')
    require(isinstance(clone, dict) and clone.get('migrations_verified') is True
            and type(clone.get('applied')) is int and clone['applied'] == len(plan.pending)
            and type(clone.get('final_ledger')) is int and clone['final_ledger'] == len(plan.migrations)
            and type(clone.get('concurrent')) is int and clone['concurrent'] == sum(m.concurrent for m in plan.pending)
            and clone.get('sql_digest') == digest([(m.name, m.sha256) for m in plan.pending])
            and all(isinstance(clone.get(key), str) and re.fullmatch('[0-9a-f]{64}', clone[key])
                    for key in ('final_schema_digest', 'clone_identity')),
            'clone-receipt-invalid')


class LocalTransition:
    """Durable local DB sequence; incomplete post-marker runs need explicit retry.

    adapter-failed is diagnostic; run-start/complete determine recovery consent.
    Completed replay is read-only. Concurrent migrations committed without an
    index receipt refuse recovery; no automatic adoption of their definitions.
    No service promotion or legacy resume.
    """
    def __init__(self, plan, database, journal: Journal, *, host=None):
        self.plan, self.db, self.j, self.host = plan, database, journal, host

    def _check_host(self, evidence):
        if self.host is None:
            require(evidence.host_digest is None, 'local-host-evidence-unbound')
        else:
            receipt = self.host.assert_contained()
            require(evidence.host_digest == receipt['fingerprint'], 'local-host-evidence-mismatch')

    def run(self, evidence: LocalEvidence, *, retry=False):
        self._check_host(evidence)
        init = self.j.last('adapter-init')
        if init:
            require(init['plan_digest'] == self.plan.digest, 'plan-changed')
            require(init['database_identity'] == self.db.identity, 'database-changed')
        else:
            self.j.append('adapter-init', plan_digest=self.plan.digest,
                          database_identity=self.db.identity, adapter_sources=dict(self.plan.adapter_sources),
                          production_ready=False)
        observed = self.db.observe()
        step_invariants(observed)
        marker = self.j.last('adapter-ddl-marker')
        previous = self.j.last('adapter-run-start')
        complete = self.j.last('adapter-run-complete')
        interrupted = previous and (complete is None or complete.get('start_seq') != previous['seq'])
        unreceipted = any(not self.j.last('done', event['step']) for event in self.j.find('intent')
                          if str(event.get('step', '')).startswith('adapter-migration:'))
        needs_retry = marker is not None and bool(interrupted or unreceipted)
        if needs_retry:
            require(retry is True, 'explicit-local-retry-required')
            self.j.append('adapter-retry', previous_start=previous['seq'] if previous else None)
        run_start = self.j.append('adapter-run-start')['seq']
        if marker is None:
            pre_ddl_findings(observed)
            pending_indexes = {name for migration in self.plan.pending for name in migration.indexes}
            require(not pending_indexes.intersection(observed['relations']), 'concurrent-index-without-ledger')
            require(observed['ledger'] == self.plan.baseline, 'baseline-ledger')
            evidence.validate(self.plan.digest, baseline_digest(observed))
            preflight = self.db.full_preflight(self.plan, len(observed['ledger']))
            require_clean_preflight(preflight, complete=False)
            self.j.append('adapter-preflight', phase='before-ddl', **preflight)
            backup = self.db.rehearse_backup(self.plan)
            validate_clone_receipt(backup, self.plan, self.db.identity, baseline_digest(observed))
            backup_event = self.j.append('adapter-local-restore', **backup)
            self._check_host(evidence)
            # Re-observe immediately before the irrevocable marker; no row hashes.
            fresh = self.db.observe()
            pre_ddl_findings(fresh)
            require(not pending_indexes.intersection(fresh['relations']), 'concurrent-index-without-ledger')
            require(baseline_digest(fresh) == baseline_digest(observed), 'baseline-changed')
            self.j.append('adapter-ddl-marker', baseline_digest=baseline_digest(fresh),
                          evidence_kind=evidence.kind, pending=len(self.plan.pending), irrevocable=True,
                          restore_seq=backup_event['seq'], restore_digest=digest(backup))
        else:
            evidence.validate(self.plan.digest, marker['baseline_digest'])
            restored = next((event for event in self.j.find('adapter-local-restore')
                             if event['seq'] == marker.get('restore_seq')), None)
            require(restored is not None and digest({k: v for k, v in restored.items()
                    if k not in ('seq', 'at', 'kind')}) == marker.get('restore_digest'), 'restore-receipt-changed')
            backup = {k: v for k, v in restored.items() if k not in ('seq', 'at', 'kind')}
            validate_clone_receipt(backup, self.plan, self.db.identity, marker['baseline_digest'])
            preflight = self.db.full_preflight(self.plan, len(observed['ledger']))
            require_clean_preflight(preflight, complete=len(observed['ledger']) == len(self.plan.migrations))
        ledger = list(observed['ledger'])
        completed = [m.name for m in self.plan.pending if m.name in ledger]
        require(set(ledger) == set(self.plan.baseline) | set(completed)
                and completed == [m.name for m in self.plan.pending[:len(completed)]], 'ledger-not-prefix')
        require(all(e['step'].removeprefix('adapter-migration:') in ledger
                    for e in self.j.find('done') if e['step'].startswith('adapter-migration:')),
                'ledger-regressed')
        try:
            for migration in self.plan.pending:
                self._check_host(evidence)
                step = 'adapter-migration:' + migration.name
                require(all(e.get('sql_sha256') == migration.sha256 for e in self.j.find('intent', step)),
                        'migration-intent-changed')
                if migration.name in ledger:
                    require(self.j.last('intent', step) is not None, 'unjournaled-migration')
                    index_receipt = reviewed_indexes(migration, observed)
                    done = self.j.last('done', step)
                    if done:
                        require(done.get('indexes') == index_receipt, 'reviewed-index-changed')
                    else:
                        require(not migration.indexes, 'reviewed-index-receipt-missing')
                        self.j.append('done', step=step, recovered=True, indexes=index_receipt)
                    continue
                current = self.db.observe()
                step_invariants(current)
                remaining_pre_ddl_gates(current)
                require(set(current['ledger']) == set(ledger), 'ledger-changed')
                require(not (set(migration.indexes) & set(current['relations'])), 'concurrent-index-without-ledger')
                self.j.append('intent', step=step, sql_sha256=migration.sha256)
                self.db.apply(self.plan, migration)
                self._check_host(evidence)
                after = self.db.observe()
                step_invariants(after)
                require(set(after['ledger']) == set(ledger) | {migration.name}, 'migration-ledger-mismatch')
                self.j.append('done', step=step, indexes=reviewed_indexes(migration, after))
                ledger.append(migration.name)
            require(set(ledger) == {m.name for m in self.plan.migrations}, 'final-ledger')
            preflight = self.db.full_preflight(self.plan, len(ledger))
            require_clean_preflight(preflight, complete=True)
            from first_transition_local_backup import snapshot
            require(snapshot(self.db.conn)['catalog'] == backup['clone_rehearsal']['final_schema_digest'],
                    'clone-source-schema-divergence')
            self._check_host(evidence)
            final = self.db.observe()
            step_invariants(final)
            require(set(final['ledger']) == set(ledger), 'ledger-changed')
            for migration in self.plan.pending:
                done = self.j.last('done', 'adapter-migration:' + migration.name)
                require(done is not None and done.get('indexes') == reviewed_indexes(migration, final),
                        'reviewed-index-changed')
            self.j.append('adapter-preflight', phase='after-ddl', **preflight)
            if self.j.last('adapter-database-verified') is None:
                self.j.append('adapter-database-verified', ledger=len(ledger), production_ready=False)
            self.j.append('adapter-run-complete', start_seq=run_start)
            return dict(status='database-verified', ledger=len(ledger), production_ready=False,
                        services='simulated-held', host_verified=False, legacy_resume_allowed=False)
        except BaseException as exc:
            self.j.append('adapter-failed', code=str(exc) if isinstance(exc, Refused) else 'interrupted',
                          legacy_resume_allowed=False)
            raise


def queue_metadata(read, *, processing_keys=()):
    """Metadata only, over an explicitly supplied command port (no Redis client).

    Callers must already know the scoped processing lists; no KEYS/SCAN, value
    reads or row hashes. Equal lengths cannot prove equal contents, and the
    result expressly does not certify preservation or quiescence. Tests use a
    simulator; binding a real transport requires the separate host review.
    """
    require(isinstance(processing_keys, (tuple, list)) and len(processing_keys) <= 64,
            'queue-scope')
    require(all(isinstance(key, str) and re.fullmatch(
        r'pastorai:webhooks:processing:[A-Za-z0-9_-]{1,80}', key) for key in processing_keys),
        'queue-scope')
    require(len(set(processing_keys)) == len(processing_keys), 'queue-scope')
    kinds = {'pastorai:webhooks': 'list', 'pastorai:webhooks:processing': 'list',
             'pastorai:webhooks:dead': 'list', 'pastorai:webhooks:retry-scheduled': 'zset',
             **dict.fromkeys(processing_keys, 'list')}
    counts = {}
    def command(name, key):
        try:
            return read(name, key)
        except Exception:
            raise Refused('queue-observation-failed') from None
    for key, expected in sorted(kinds.items()):
        kind = command('TYPE', key)
        require(kind in (expected, 'none'), 'queue-type')
        ttl = command('PTTL', key)
        require(type(ttl) is int and (ttl == -1 if kind != 'none' else ttl == -2),
                'queue-not-persistent')
        count = command('LLEN' if expected == 'list' else 'ZCARD', key)
        require(type(count) is int and 0 <= count <= 2**63 - 1, 'queue-count')
        require(kind != 'none' or count == 0, 'queue-count')
        counts[key] = count
    return dict(counts=counts, metadata_digest=digest(counts), content_verified=False)
