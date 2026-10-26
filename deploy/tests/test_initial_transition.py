"""Unit tests of the initial transition controller with an in-memory Docker/PG/Redis double.

Complements the physical rehearsal (``rehearse_initial_transition.py``); these
tests prove decision logic, replay and refusals, not Docker behaviour.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))

import initial_transition as it  # noqa: E402
import initial_transition_files as itf  # noqa: E402
import initial_transition_ops as ops_mod  # noqa: E402
import initial_transition_reconcile as itr  # noqa: E402
from initial_transition_ops import Refused  # noqa: E402

REPO = DEPLOY.parent
CANDIDATE_SHA = '6b0b302bd1c1f84dfef7516babee2b7767d3219c'
LEGACY_SHA = '07a3f4d9a4fe510cf83fd48d5deaa52dcfbb7e02'
RUN = 'ab' * 16
PREFIX = 'pastorai-synthetic-transition-' + RUN[:12]
LEGACY_IMAGE, CANDIDATE_IMAGE = 'sha256:' + '1' * 64, 'sha256:' + '2' * 64
APP, EDGE = 'a' * 64, 'e' * 64
GATES = {'ALLOW_REAL_SENDS': 'true', 'ASAAS_BILLING_ENABLED': None, 'BREVO_SEND_MODE': 'live',
         'BROADCAST_ASYNC_ENABLED': 'false'}
_FILES = {}


def candidate_files():
    if not _FILES:
        _FILES.update(itf.git_tree(REPO, CANDIDATE_SHA, it.CANDIDATE_PATHSPECS, it.CANDIDATE_BLOBS))
    return _FILES


def manifest():
    files = candidate_files()
    sql = {p.split('/', 2)[2]: b for p, b in files.items() if p.count('/') == 2 and p.startswith('backend/migrations/')}
    return itf.migration_manifest(files['backend/scripts/migrate.py'], sql)


MISSING = {'20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql',
           '20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql',
           '20260925_183811_preserve_platform_admins_on_tenant_deletion.sql', '20260926_120446_platform_jev_settings.sql'}


IMAGE = 'sha256:' + 'c' * 64


def layout_topology(**changes):
    contract = dict(schema='pastorai.release-topology', version=1, project=PREFIX + '-cand',
                    legacy_project=PREFIX + '-legacy', network=dict(name=PREFIX + '-app', id='e' * 64),
                    containers={r: f'{PREFIX}-cand-{r}' for r in ('backend', 'queue-worker', 'cron-worker',
                                                                   'broadcast-worker')},
                    reserved_legacy={r: str(i) * 64 for i, r in enumerate(
                        ('backend', 'queue-worker', 'cron-worker', 'broadcast-worker'), 1)})
    contract.update(changes)
    return contract


def hexid(n):
    return format(n, '064x')


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Killed(BaseException):
    """Simulates SIGKILL of the controller at a pause checkpoint."""


class FakeOps:
    """Minimal state machine for containers, jobs, ledger, sessions and indexes."""

    def __init__(self, clock):
        self.clock = clock
        self.containers, self.jobs, self.signals, self.starts = {}, {}, [], []
        self.ledger_rows = sorted(n for n in manifest() if n < '20261015' and n not in MISSING)
        self.invalid, self.indexes, self.builds, self.sessions, self.clients = [], set(), [], [], []
        self.snap = {'db': 1, 'redis': 1}
        self.migration_behaviour, self.ready_status, self.restart_on_term = {}, 'ready', set()
        self.ignore_term, self.duplicates, self.external = set(), 0, set()
        self.compose_created, self.ttl, self.lists, self.zsets = False, {}, {}, {}
        self.recon = dict(tables={'app_users': 'u0', 'platform_audit_log': 'a0', 'pessoas': 'p0',
                                  'schema_migrations': 's0'}, others='o0', target_row='t0',
                          target_pessoa=None, audit_others='x0', audit_op=[])
        self.recon_payload, self.scope_calls = None, []
        n = 0
        for role in it.ROLES:
            n += 1
            labels = {ops_mod.OWNER_LABEL: RUN}
            if role != 'broadcast-worker':
                labels.update({ops_mod.COMPOSE_PROJECT: PREFIX + '-legacy', ops_mod.COMPOSE_SERVICE: role})
            self.add(hexid(n), image=LEGACY_IMAGE, name=f'{PREFIX}-{role}-legacy', labels=labels, policy='always',
                     running=True, nets={'app': APP, **({'edge': EDGE} if role == 'backend' else {})})
        self.legacy_ids = {role: hexid(i + 1) for i, role in enumerate(it.ROLES)}
        for i, role in enumerate(('postgres', 'redis', 'evolution'), 10):
            self.add(hexid(i), image='sha256:' + '9' * 64, name=f'{PREFIX}-{role}',
                     labels={ops_mod.OWNER_LABEL: RUN, ops_mod.ROLE_LABEL: role}, policy='no', running=True,
                     nets={'app': APP})
        self.support = {'postgres': hexid(10), 'redis': hexid(11), 'evolution': hexid(12)}

    def add(self, identifier, *, image, name, labels, policy, running, nets, env=None):
        env = dict(env or {k: v for k, v in GATES.items() if v is not None})
        self.containers[identifier] = dict(
            Id=identifier, Image=image, Name='/' + name, Path='python', Args=[],
            Config=dict(Labels=labels, Env=[f'{k}={v}' for k, v in env.items()]),
            HostConfig=dict(RestartPolicy=dict(Name=policy), ReadonlyRootfs=True, AutoRemove=False, PortBindings={}),
            State=dict(Running=running, Status='running' if running else 'created', StartedAt='t0' if running else '',
                       ExitCode=0, FinishedAt=''),
            RestartCount=0, Mounts=[],
            NetworkSettings=dict(Ports={}, Networks={f'{PREFIX}-{k}': dict(NetworkID=v, IPAddress=f'10.0.0.{len(self.containers) + 2}',
                                                                         Aliases=[]) for k, v in nets.items()}))

    # -- docker ---------------------------------------------------------------
    def guard_local(self):
        pass

    def verify_topology(self):
        pass

    def image(self, image):
        return {'Id': image, 'Config': {'Labels': {ops_mod.REVISION_LABEL: CANDIDATE_SHA}}}

    def inspect(self, identifier):
        data = self.containers.get(identifier)
        return json.loads(json.dumps(data)) if data else None

    def owned_containers(self, run_id):
        return {i for i, c in self.containers.items() if c['Config']['Labels'].get(ops_mod.OWNER_LABEL) == run_id}

    def network_members(self, network):
        name = PREFIX + ('-app' if network == APP else '-edge')
        members = {i for i, c in self.containers.items() if c['State']['Running']
                   and any(v['NetworkID'] == network for v in c['NetworkSettings']['Networks'].values())}
        return {'Id': network, 'Name': name, 'Internal': True, 'Labels': {ops_mod.OWNER_LABEL: RUN}}, members

    def update_restart(self, identifier, policy):
        self.containers[identifier]['HostConfig']['RestartPolicy']['Name'] = policy

    def signal(self, identifier):
        self.signals.append(identifier)
        state = self.containers[identifier]
        if identifier in self.ignore_term:
            return
        state['State'].update(Running=False, Status='exited', ExitCode=0, FinishedAt='t-end')
        if identifier in self.restart_on_term or state['HostConfig']['RestartPolicy']['Name'] == 'always':
            state['RestartCount'] += 1
            state['State'].update(Running=True, Status='running', StartedAt='t-restarted')

    def start(self, identifier):
        self.starts.append(identifier)
        state = self.containers[identifier]['State']
        state.update(Running=True, Status='running', StartedAt=f't-start-{len(self.starts)}')

    # -- SQL / Redis ------------------------------------------------------------
    def pg_sessions(self):
        return list(self.sessions)

    def redis_clients(self):
        return list(self.clients)

    def ledger(self):
        return sorted(self.ledger_rows)

    def invalid_indexes(self):
        return list(self.invalid)

    def index_builds(self):
        return list(self.builds)

    def index_exists(self, names):
        return sorted(set(names) & self.indexes)

    def backfill_candidates(self):
        return {'membro_por_vinculo': 0, 'numero_atendimento': 0}

    def db_snapshot(self):
        return dict(self.recon['tables'], db=self.snap['db'])

    def reconcile_scope(self, *, target, operation, operator, detail):
        r = self.recon
        self.scope_calls.append(dict(target=target, operation=operation, operator=operator, detail=detail))
        exact = sum(1 for row in r['audit_op'] if row == (operator, target, json.dumps(detail, sort_keys=True)))
        return dict(tables=dict(r['tables'], db=self.snap['db']), app_users_others=r['others'],
                    target_row=r['target_row'], target_pessoa=r['target_pessoa'], audit_others=r['audit_others'],
                    audit_op_total=len(r['audit_op']), audit_op_exact=exact)

    def redis_snapshot(self):
        return {'redis': self.snap['redis']}

    def redis_list(self, key):
        return list(self.lists.get(key, []))

    def redis_zset(self, key):
        return [list(x) for x in self.zsets.get(key, [])]

    def redis_keys(self, prefix):
        return []

    def redis_pttl(self, key):
        return self.ttl.get(key, -2)

    def redis_volatile_count(self):
        return 2

    def message_counts(self, ids):
        return {i: 1 for i in ids}

    def delivery_states(self, ids):
        return {}

    def duplicate_groups(self):
        return self.duplicates

    # -- jobs -------------------------------------------------------------------
    def job_find(self, name):
        return [i for i, j in self.jobs.items() if j['name'] == name]

    def job_create(self, *, name, kind, image, args, env, stdin=False, network):
        identifier = hexid(1000 + len(self.jobs))
        self.jobs[identifier] = dict(name=name, kind=kind, image=image, args=list(args), env=env, network=network)
        self.add(identifier, image=image, name=name, labels={ops_mod.OWNER_LABEL: RUN, 'pastorai.transition.job': name},
                 policy='no', running=False, nets={})
        self.containers[identifier]['State'].update(Status='created')
        return identifier

    def job_matches(self, data, *, image, args, env, network):
        job = self.jobs[data['Id']]
        return job['image'] == image and job['args'] == list(args) and job['network'] == network and job['env'] == env

    def script_args(self, target, source, extra=()):
        return ['script', target, *extra]

    def job_start(self, identifier, input=None, timeout=120):
        job = self.jobs[identifier]
        state = self.containers[identifier]['State']
        state.update(Running=True, Status='running', StartedAt='job')
        code, out = 0, ''
        args = job['args']
        if args[:2] == ['scripts/migrate.py', 'apply']:
            name = args[2]
            behaviour = self.migration_behaviour.get(name, 'ok')
            if behaviour == 'hang':
                return None
            if behaviour == 'ok':
                self.ledger_rows.append(name)
                self.indexes.update(it.concurrent_indexes(candidate_files()['backend/migrations/' + name]))
            elif behaviour == 'fail':
                code = 1
            elif behaviour == 'invalid':
                code, self.invalid = 1, ['broken_idx']
            elif behaviour == 'valid-no-ledger':
                code = 1
                self.indexes.update(it.concurrent_indexes(candidate_files()['backend/migrations/' + name]))
        elif args and args[0] == 'script':
            out = 'RESULTADO=PREVIA_OK x\nCONFIRMACAO=DESVINCULAR:abc' if 'reconcile' in args[1] else 'ok'
            if '--aplicar' in args:
                if self.recon['audit_op']:
                    out = 'RESULTADO=JA_APLICADA x'
                else:  # commit of the authorized effect: target unlinked + one audit row
                    self.recon['target_pessoa'] = None
                    self.recon['audit_op'] = [self.recon_payload]  # (actor, target, detail) as the service writes
                    self.recon['tables'].update(app_users='u1', platform_audit_log='a1')
                    self.duplicates = 0
                    out = 'RESULTADO=APLICADA x'
        elif '/ready' in ' '.join(args):
            body = {'status': self.ready_status, 'required': {'database': 'ok', 'redis': 'ok'},
                    'workers': {'queue-worker': 'ok', 'cron-worker': 'ok', 'broadcast-worker': 'ok'}}
            out = json.dumps({'status': 200 if self.ready_status != 'not_ready' else 503, 'body': body})
        elif '/health' in ' '.join(args):
            out = json.dumps({'status': 200})
        elif it.CATALOG_PROBE in args:
            out = json.dumps({'kind': 'x'})
        job['out'] = out
        state.update(Running=False, Status='exited', ExitCode=code)
        return None

    def finish(self, identifier, *, ledger=True):
        job = self.jobs[identifier]
        if ledger:
            self.ledger_rows.append(job['args'][2])
        self.containers[identifier]['State'].update(Running=False, Status='exited', ExitCode=0)

    def job_logs(self, identifier):
        return self.jobs[identifier].get('out', '')

    def compose_create(self, project, compose_file):
        if self.compose_created:
            return
        self.compose_created = True
        for i, role in enumerate(it.ROLES):
            self.add(hexid(50 + i), image=CANDIDATE_IMAGE, name=f'{PREFIX}-cand-{role}',
                     labels={ops_mod.OWNER_LABEL: RUN, ops_mod.COMPOSE_PROJECT: project, ops_mod.COMPOSE_SERVICE: role},
                     policy='no', running=False, nets={'app': APP, **({'edge': EDGE} if role == 'backend' else {})})

    def compose_ids(self, project):
        return {c['Config']['Labels'][ops_mod.COMPOSE_SERVICE]: i for i, c in self.containers.items()
                if c['Config']['Labels'].get(ops_mod.COMPOSE_PROJECT) == project}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='initial-transition-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.clock = Clock()
        self.ops = FakeOps(self.clock)
        compose = self.root / 'candidate.yml'
        compose.write_text('services: {}\n')
        pending = [n for n in manifest() if n not in set(self.ops.ledger_rows)]
        self.spec = dict(
            version=1, synthetic=True, run_id=RUN, prefix=PREFIX, repo=str(REPO),
            legacy=dict(sha=LEGACY_SHA, image=LEGACY_IMAGE, source_root='/opt/legacy', project=PREFIX + '-legacy',
                        containers=self.ops.legacy_ids, standalone=['broadcast-worker']),
            candidate=dict(sha=CANDIDATE_SHA, image=CANDIDATE_IMAGE, project=PREFIX + '-candidate',
                           compose_file=str(compose), compose_sha256=itf.sha256(compose.read_bytes()),
                           names={r: f'{PREFIX}-cand-{r}' for r in it.ROLES}),
            network=dict(app=APP, edge=EDGE), support=self.ops.support,
            database=dict(superuser='postgres', name='synthetic',
                          dsn='postgresql://postgres:synthetic-pw@postgres:5432/synthetic'),
            reconcile=None, expect_settled={}, expect_candidate={}, expected_catalog={'kind': 'x'},
            expected_pending=pending, release_root=str(self.root / 'release-root'), timeouts=dict(settle_s=1))
        self.state = self.root / 'state'

    def transition(self, journal, **kwargs):
        t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep, **kwargs)
        t._files = candidate_files()
        t.inv = journal.append('invocation', command='run')['seq']
        return t

    def observed(self, journal):
        legacy = {}
        for role, identifier in self.ops.legacy_ids.items():
            data = self.ops.inspect(identifier)
            legacy[role] = dict(id=identifier, name=data['Name'][1:], policy='always', started='t0', restart_count=0,
                                gates=ops_mod.gates_of(data), compose=role != 'broadcast-worker')
        ledger = self.ops.ledger()
        journal.append('done', step='observe', legacy=legacy, ledger_count=len(ledger), ledger_digest=it.canonical(ledger))

    def run_until(self, until=None, **kwargs):
        with itf.Journal(self.state) as journal:
            if not journal.find('done', 'observe'):
                self.observed(journal)
            t = self.transition(journal, **kwargs)
            try:
                return t.run(until)
            finally:
                self.events = list(journal.events)

    def refused(self, code, until=None, **kwargs):
        with self.assertRaises(Refused) as caught:
            self.run_until(until, **kwargs)
        self.assertEqual(str(caught.exception), code)

    def die_at(self, t, checkpoint):
        """Simulate SIGKILL exactly at ``checkpoint`` (and assert it was reached)."""
        self.hit = []

        def hook(name):
            if name == checkpoint:
                self.hit.append(name)
                raise Killed()
        t.checkpoint = hook

    def tearDown(self):
        if getattr(self, 'hit', None) is not None:
            self.assertTrue(self.hit, 'crash checkpoint never reached')

    def kinds(self, kind, step_prefix=''):
        return [e for e in self.events if e['kind'] == kind and str(e.get('step', '')).startswith(step_prefix)]


class ReconcileRecoveryTest(Base):
    def setUp(self):
        super().setUp()
        ids = {k: str(__import__('uuid').UUID(int=i + 1)) for i, k in enumerate(
            ('igreja', 'pessoa', 'manter', 'corrigir', 'admin_igreja', 'operador', 'operacao'))}
        self.spec['reconcile'] = ids
        self.ops.duplicates = 1
        self.ops.recon['target_pessoa'] = ids['pessoa']
        self.ops.recon_payload = (ids['operador'], ids['corrigir'],
                                  json.dumps(itr.expected_audit_detail(self.spec), sort_keys=True))

    def crash_after_apply_commit(self):
        real = self.ops.job_start

        def start(identifier, input=None, timeout=120):
            real(identifier, input=input, timeout=timeout)
            if '--aplicar' in self.ops.jobs[identifier]['args']:
                raise Killed()  # committed; controller dies before done/snapshot/phase
        self.ops.job_start = start
        with itf.Journal(self.state) as journal:
            self.observed(journal)
            with self.assertRaises(Killed):
                self.transition(journal).run('reconciled')
        self.ops.job_start = real

    def apply_jobs(self):
        return [j for j in self.ops.jobs.values() if '--aplicar' in j['args']]

    def kill_at(self, checkpoint):
        hit = []

        def checkpoint_hook(name):
            if name == checkpoint:
                hit.append(name)
                raise Killed()
        with itf.Journal(self.state) as journal:
            self.observed(journal)
            t = self.transition(journal)
            t.checkpoint = checkpoint_hook
            with self.assertRaises(Killed):
                t.run('reconciled')
        self.assertEqual(hit, [checkpoint])

    def assert_refused_without_reapply(self, mutate, code='reconcile-delta-mismatch'):
        self.crash_after_apply_commit()
        mutate()
        self.refused(code, 'preflighted')
        self.assertEqual(len(self.apply_jobs()), 1)
        self.assertFalse(self.kinds('ddl-marker'))

    def test_foreign_write_in_other_table_refused(self):
        self.assert_refused_without_reapply(lambda: self.ops.recon['tables'].update(pessoas='p-foreign'))

    def test_foreign_write_in_other_app_user_refused(self):
        self.assert_refused_without_reapply(lambda: self.ops.recon.update(others='o-foreign'))

    def test_other_change_on_corrected_account_refused(self):
        self.assert_refused_without_reapply(lambda: self.ops.recon.update(target_row='t-foreign'))

    def test_foreign_audit_row_refused(self):
        self.assert_refused_without_reapply(lambda: self.ops.recon.update(audit_others='x-foreign'))

    def test_ledger_change_refused(self):
        self.assert_refused_without_reapply(lambda: self.ops.recon['tables'].update(schema_migrations='s-foreign'))

    def test_redis_change_refused(self):
        self.assert_refused_without_reapply(lambda: self.ops.snap.update(redis=7))

    def test_audit_row_with_altered_field_refused(self):
        payload = self.ops.recon_payload
        self.assert_refused_without_reapply(lambda: self.ops.recon.update(audit_op=[(payload[0], payload[1], '{}')]))

    def test_second_audit_row_of_the_operation_refused(self):
        payload = self.ops.recon_payload
        self.assert_refused_without_reapply(lambda: self.ops.recon.update(audit_op=[payload, payload]))

    def test_expected_detail_matches_service_fields(self):
        detail = itr.expected_audit_detail(self.spec)
        self.assertEqual(sorted(detail), sorted(['operation_id', 'payload_sha256', 'operacao', 'igreja_id', 'pessoa_id',
                                                 'conta_mantida', 'conta_corrigida', 'admin_igreja', 'release_sha']))
        self.assertEqual(detail['operacao'], 'desvincular')

    def resume_after(self, checkpoint):
        self.kill_at(checkpoint)
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            token = t.resume_token()
            t.resume_legacy(token, token)
            done = [e for e in journal.find('done', 'reconcile')]
            snaps = [e for e in journal.find('snapshot') if e.get('reason') == 'reconciled']
        self.assertEqual(len(self.apply_jobs()), 1)
        self.assertEqual(len(done), 1)
        self.assertEqual(len(snaps), 1)
        self.assertEqual(sum(self.ops.inspect(i)['State']['Running'] for i in self.ops.legacy_ids.values()), 4)

    def test_resume_after_apply_done_or_snapshot_completes_once(self):
        for checkpoint in ('reconcile:after-apply', 'reconcile:after-done', 'reconcile:after-snapshot'):
            with self.subTest(checkpoint=checkpoint):
                self.setUp()
                self.resume_after(checkpoint)

    def test_run_after_apply_done_or_snapshot_completes_once(self):
        for checkpoint in ('reconcile:after-apply', 'reconcile:after-done', 'reconcile:after-snapshot'):
            with self.subTest(checkpoint=checkpoint):
                self.setUp()
                self.kill_at(checkpoint)
                self.assertEqual(self.run_until('preflighted'), 'preflighted')
                self.assertEqual(len(self.apply_jobs()), 1)
                self.assertEqual(len([e for e in self.events if e['kind'] == 'done' and e.get('step') == 'reconcile']), 1)
                self.assertEqual(len([e for e in self.events if e['kind'] == 'snapshot'
                                      and e.get('reason') == 'reconciled']), 1)

    def test_write_between_verification_and_journal_is_not_absorbed(self):
        original = itr.verify_reconciliation

        def verified_then_foreign_write(t, base):
            verified = original(t, base)
            self.ops.recon['tables']['pessoas'] = 'p-foreign-after-verify'
            return verified
        itr.verify_reconciliation = verified_then_foreign_write
        try:
            self.refused('writer-after-settle', 'preflighted')
        finally:
            itr.verify_reconciliation = original
        self.assertFalse(self.kinds('ddl-marker'))

    def test_redis_changed_before_baseline_is_not_absorbed(self):
        original = self.ops.reconcile_scope

        def change_then_scope(**kwargs):
            self.ops.snap['redis'] = 'foreign-redis'
            return original(**kwargs)
        self.ops.reconcile_scope = change_then_scope
        self.refused('writer-after-settle', 'preflighted')
        self.assertFalse(self.kinds('reconcile-baseline'))
        self.assertFalse(self.apply_jobs())

    def test_duplicates_reappearing_refused(self):
        self.assert_refused_without_reapply(lambda: setattr(self.ops, 'duplicates', 1))

    def test_resume_legacy_recovers_committed_reconciliation_pre_ddl(self):
        self.crash_after_apply_commit()
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            token = t.resume_token()
            t.resume_legacy(token, token)
            self.assertTrue(journal.last('done', 'reconcile')['recovered'])
            self.assertIn('legacy-resumed', [e['name'] for e in journal.find('phase')])
        self.assertEqual(len(self.apply_jobs()), 1)
        self.assertEqual(len([i for i in self.ops.starts if i in self.ops.legacy_ids.values()]), 4)

    def test_resume_legacy_refuses_committed_reconciliation_with_foreign_write(self):
        self.crash_after_apply_commit()
        self.ops.recon['tables']['pessoas'] = 'p-foreign'
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            token = t.resume_token()
            with self.assertRaises(Refused) as caught:
                t.resume_legacy(token, token)
            self.assertEqual(str(caught.exception), 'reconcile-delta-mismatch')
        self.assertFalse(set(self.ops.starts) & set(self.ops.legacy_ids.values()))

    def test_resume_legacy_never_creates_or_starts_apply_job(self):
        for drop in (False, True):
            with self.subTest(dropped=drop):
                self.setUp()
                self.kill_at('job:' + PREFIX + '-job-reconcile-apply:before-start')  # created, never started
                if drop:
                    for identifier in [i for i, j in self.ops.jobs.items() if '--aplicar' in j['args']]:
                        del self.ops.jobs[identifier], self.ops.containers[identifier]
                with itf.Journal(self.state) as journal:
                    t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
                    token = t.resume_token()
                    t.resume_legacy(token, token)  # no effect happened: settled snapshot holds
                self.assertEqual(self.ops.recon['audit_op'], [])
                self.assertEqual(len(self.apply_jobs()), 0 if drop else 1)
                for j in self.apply_jobs():
                    self.assertNotIn(j.get('out'), ('RESULTADO=APLICADA x',))

    def test_committed_reconciliation_is_recovered_without_reapply(self):
        self.crash_after_apply_commit()
        self.assertEqual(self.run_until('preflighted'), 'preflighted')
        self.assertEqual(len(self.apply_jobs()), 1)
        self.assertEqual(self.kinds('done', 'reconcile')[-1].get('recovered'), True)


class JournalTest(Base):
    def test_reopen_validates_sequence_and_refuses_torn_tail(self):
        with itf.Journal(self.state) as journal:
            journal.append('a')
            journal.append('b')
        with itf.Journal(self.state) as journal:
            self.assertEqual([e['seq'] for e in journal.events], [1, 2])
        with open(self.state / 'journal.jsonl', 'ab') as out:
            out.write(b'{"seq": 3, "kind"')
        with self.assertRaises(Refused) as caught:
            itf.Journal(self.state).open()
        self.assertEqual(str(caught.exception), 'journal-torn')

    def test_out_of_order_sequence_is_invalid(self):
        self.state.mkdir()
        (self.state / 'journal.jsonl').write_text('{"seq": 2, "kind": "x"}\n')
        with self.assertRaises(Refused) as caught:
            itf.Journal(self.state).open()
        self.assertEqual(str(caught.exception), 'journal-invalid')

    def test_short_writes_are_completed_before_fsync(self):
        calls = []

        def short(fd, data):
            calls.append(len(data))
            return os.write(fd, bytes(data[:3]))
        with itf.Journal(self.state, writer=short) as journal:
            journal.append('x', step='long-step-name')
        with itf.Journal(self.state) as journal:
            self.assertEqual(journal.events[0]['step'], 'long-step-name')
        self.assertGreater(len(calls), 3)

    def test_single_writer_lock_released_on_close(self):
        first = itf.Journal(self.state).open()
        with self.assertRaises(Refused) as caught:
            itf.Journal(self.state).open()
        self.assertEqual(str(caught.exception), 'controller-busy')
        first.close()
        itf.Journal(self.state).open().close()

    def test_symlinked_state_or_journal_refused(self):
        target = self.root / 'elsewhere'
        target.mkdir()
        (self.root / 'link').symlink_to(target)
        with self.assertRaises(Refused):
            itf.Journal(self.root / 'link').open()
        self.state.mkdir()
        (self.state / 'journal.jsonl').symlink_to(self.root / 'nowhere')
        with self.assertRaises(Refused):
            itf.Journal(self.state).open()


class FilesTest(Base):
    def test_protected_component_refused_before_any_blob_read(self):
        reads = []

        def git(args):
            if args[0] == 'rev-parse':
                return (CANDIDATE_SHA + '\n').encode()
            if args[0] == 'ls-tree':
                return b'100644 blob ' + b'0' * 40 + b'\tbackend/app/ok.py\0100644 blob ' + b'1' * 40 + \
                    b'\tbackend/app/secrets/token.py\0'
            reads.append(args)
            return b''
        with self.assertRaises(Refused) as caught:
            itf.git_tree(REPO, CANDIDATE_SHA, ('backend/app',), it.CANDIDATE_BLOBS, git)
        self.assertEqual(str(caught.exception), 'source-protected-path')
        self.assertEqual(reads, [])

    def test_layout_is_idempotent_and_refuses_links_and_extras_unread(self):
        files = candidate_files()
        root = self.root / 'release-root'
        count = itf.write_layout(root, CANDIDATE_SHA, files, layout_topology(), manifest(), IMAGE)
        self.assertEqual(itf.write_layout(root, CANDIDATE_SHA, files, layout_topology(), manifest(), IMAGE), count)
        target = root / 'releases' / CANDIDATE_SHA
        self.assertFalse(list(target.rglob('.env*')))
        secret = self.root / 'outside.env'
        secret.write_text('X=1\n')
        (target / 'deploy' / 'extra').symlink_to(secret)
        with mock.patch.object(itf, 'read_regular', side_effect=AssertionError('read before inventory')):
            with self.assertRaises(Refused) as caught:
                itf.write_layout(root, CANDIDATE_SHA, files, layout_topology(), manifest(), IMAGE)
        self.assertEqual(str(caught.exception), 'layout-unsafe-entry')
        (target / 'deploy' / 'extra').unlink()
        (target / 'deploy' / 'extra.txt').write_text('x')
        with mock.patch.object(itf, 'read_regular', side_effect=AssertionError('read before inventory')):
            with self.assertRaises(Refused):
                itf.write_layout(root, CANDIDATE_SHA, files, layout_topology(), manifest(), IMAGE)

    def test_layout_writes_public_topology_contract_and_refuses_invalid_one(self):
        files = candidate_files()
        root = self.root / 'release-root'
        itf.write_layout(root, CANDIDATE_SHA, files, layout_topology(), manifest(), IMAGE)
        deploy = root / 'releases' / CANDIDATE_SHA / 'deploy'
        self.assertEqual(json.loads((deploy / 'release-topology.json').read_text()), layout_topology())
        self.assertFalse((deploy / 'compose-project.name').exists())
        override = (deploy / 'docker-compose.override.yml').read_text()
        self.assertIn(f'"image": "{IMAGE}"', override)
        self.assertIn(f'"PASTORAI_RELEASE_SHA": "{CANDIDATE_SHA}"', override)
        for image in ('pastorai-backend:latest', None):
            with self.assertRaises(Refused) as caught:
                itf.write_layout(self.root / 'image-root', CANDIDATE_SHA, files, layout_topology(), manifest(), image)
            self.assertEqual(str(caught.exception), 'layout-topology')
        # A runner that needs the helper is refused without its exact blob.
        needing = {**files, 'deploy/backend-release.sh': files['deploy/backend-release.sh'] + b'# release_topology.py\n'}
        with self.assertRaises(Refused) as caught:
            itf.write_layout(self.root / 'helper-root', CANDIDATE_SHA, needing, layout_topology(), manifest(), IMAGE)
        self.assertEqual(str(caught.exception), 'layout-helper-missing')
        helper = (DEPLOY / 'release_topology.py').read_bytes()
        itf.write_layout(self.root / 'helper-root', CANDIDATE_SHA, {**needing, 'deploy/release_topology.py': helper},
                         layout_topology(), manifest(), IMAGE)
        self.assertEqual((self.root / 'helper-root' / 'releases' / CANDIDATE_SHA / 'deploy'
                          / 'release_topology.py').read_bytes(), helper)
        for bad in (layout_topology(project=PREFIX + '-legacy'), layout_topology(extra='x'),
                    layout_topology(project='pastorai')):
            with self.assertRaises(Refused) as caught:
                itf.write_layout(self.root / 'other-root', CANDIDATE_SHA, files, bad, manifest(), IMAGE)
            self.assertEqual(str(caught.exception), 'layout-topology')
        # A contract different from the one already written is a layout mismatch, never a rewrite.
        with self.assertRaises(Refused) as caught:
            itf.write_layout(root, CANDIDATE_SHA, files, layout_topology(project=PREFIX + '-other'), manifest(), IMAGE)
        self.assertEqual(str(caught.exception), 'layout-mismatch')

    def test_protected_components_refused_before_any_open_or_mkdir(self):
        paths = [self.root / '.env', self.root / 'secrets' / 'spec.json', self.root / 'x.pem',
                 self.root / 'backups' / 'state']
        with mock.patch.object(itf.os, 'open', side_effect=AssertionError('opened')), \
                mock.patch.object(itf.os, 'lstat', side_effect=AssertionError('stat')), \
                mock.patch.object(Path, 'mkdir', side_effect=AssertionError('mkdir')):
            for path in paths[:3]:
                with self.assertRaises(Refused) as caught:
                    itf.read_regular(path)
                self.assertEqual(str(caught.exception), 'protected-path')
            with self.assertRaises(Refused) as caught:
                itf.Journal(paths[3]).open()
            self.assertEqual(str(caught.exception), 'protected-path')
            with self.assertRaises(Refused):
                it.load_spec(paths[0])

    def test_clerk_admin_scripts_refused_before_any_io_app_service_allowed(self):
        with mock.patch.object(itf.os, 'open', side_effect=AssertionError('opened')), \
                mock.patch.object(itf.os, 'lstat', side_effect=AssertionError('stat')):
            for path in ('/tmp/backend/scripts/clerk_review_fixture', '/tmp/backend/scripts/migrate_clerk_production.py',
                         '/tmp/x/scripts/sub/sync_clerk.py'):
                with self.assertRaises(Refused) as caught:
                    itf.read_regular(path)
                self.assertEqual(str(caught.exception), 'protected-path')
        self.assertFalse(itf.is_protected('backend/app/services/clerk.py'.split('/')))
        reads = []

        def git(args):
            if args[0] == 'rev-parse':
                return (CANDIDATE_SHA + '\n').encode()
            if args[0] == 'ls-tree':
                return b'100644 blob ' + b'0' * 40 + b'\tbackend/scripts/clerk_users.py\0'
            reads.append(args)
            return b''
        with self.assertRaises(Refused):
            itf.git_tree(REPO, CANDIDATE_SHA, ('backend/scripts',), it.CANDIDATE_BLOBS, git)
        self.assertEqual(reads, [])

    def test_activate_refuses_foreign_current(self):
        root = self.root / 'r'
        (root / 'releases' / CANDIDATE_SHA).mkdir(parents=True)
        (root / 'current').symlink_to(root / 'releases')
        with self.assertRaises(Refused):
            itf.activate(root, CANDIDATE_SHA)


class ControllerTest(Base):
    def test_happy_path_order_marker_before_jobs_layout_before_policy_link_last(self):
        self.assertEqual(self.run_until(), 'promoted')
        kinds = [(e['kind'], e.get('step') or e.get('name')) for e in self.events]
        marker = kinds.index(('ddl-marker', None))
        first_job = next(i for i, k in enumerate(kinds) if k[0] == 'intent' and str(k[1]).startswith('migration:'))
        self.assertLess(marker, first_job)
        layout = kinds.index(('done', 'promote:layout'))
        policy = kinds.index(('intent', 'promote:policy:backend'))
        link = kinds.index(('done', 'promote:current'))
        self.assertLess(layout, policy)
        self.assertLess(policy, link)
        self.assertEqual(len(self.kinds('done', 'migration:')), 46)
        self.assertEqual(self.ops.ledger(), sorted(manifest()))
        self.assertTrue(os.path.islink(self.root / 'release-root' / 'current'))
        for role, identifier in self.ops.legacy_ids.items():
            self.assertEqual(self.ops.inspect(identifier)['HostConfig']['RestartPolicy']['Name'], 'no')
            self.assertFalse(self.ops.inspect(identifier)['State']['Running'])
        contract = json.loads((self.root / 'release-root' / 'releases' / CANDIDATE_SHA / 'deploy'
                               / 'release-topology.json').read_text())
        self.assertEqual(contract['project'], self.spec['candidate']['project'])
        self.assertEqual(contract['legacy_project'], self.spec['legacy']['project'])
        self.assertEqual(contract['containers'], self.spec['candidate']['names'])
        self.assertEqual(contract['reserved_legacy'], self.ops.legacy_ids)
        self.assertEqual(contract['network']['id'], self.spec['network']['app'])
        override = (self.root / 'release-root' / 'releases' / CANDIDATE_SHA / 'deploy'
                    / 'docker-compose.override.yml').read_text()
        self.assertIn(f'"image": "{self.spec["candidate"]["image"]}"', override)

    def test_candidate_readiness_failure_is_contained_and_needs_decision(self):
        self.ops.ready_status = 'degraded'
        self.refused('candidate-not-ready')
        cand = self.ops.compose_ids(self.spec['candidate']['project'])
        for identifier in cand.values():
            data = self.ops.inspect(identifier)
            self.assertFalse(data['State']['Running'])
            self.assertEqual(data['HostConfig']['RestartPolicy']['Name'], 'no')
        self.assertFalse(set(self.ops.starts) & set(self.ops.legacy_ids.values()))
        self.ops.ready_status = 'ready'
        self.refused('candidate-contained-decision-required')
        self.assertEqual(self.run_until(decision='retry-candidate'), 'promoted')

    def test_crash_between_policy_and_link_replays_fresh_readiness_without_false_success(self):
        with itf.Journal(self.state) as journal:
            self.observed(journal)
            t = self.transition(journal)
            self.die_at(t, 'promote:after-policy')
            with self.assertRaises(Killed):
                t.run()
            self.assertFalse(journal.find('phase') and 'promoted' in [e['name'] for e in journal.find('phase')])
            ready_before = len([j for j in self.ops.jobs.values() if 'job-ready' in j['name']])
        self.assertFalse(os.path.lexists(self.root / 'release-root' / 'current'))
        self.assertEqual(self.run_until(), 'promoted')
        ready_after = len([j for j in self.ops.jobs.values() if 'job-ready' in j['name']])
        self.assertGreater(ready_after, ready_before)

    def test_candidate_dying_after_ready_is_refused_and_contained_on_replay(self):
        self.run_until('candidate-ready')
        backend = self.ops.compose_ids(self.spec['candidate']['project'])['backend']
        self.ops.containers[backend]['State'].update(Running=False, ExitCode=1)
        self.refused('candidate-not-running')
        self.assertTrue(self.kinds('candidate-contained'))
        for identifier in self.ops.compose_ids(self.spec['candidate']['project']).values():
            self.assertEqual(self.ops.inspect(identifier)['HostConfig']['RestartPolicy']['Name'], 'no')
            self.assertFalse(self.ops.inspect(identifier)['State']['Running'])
        self.assertFalse(os.path.lexists(self.root / 'release-root' / 'current'))

    def test_candidate_identity_changed_before_replay_is_refused_and_contained(self):
        self.run_until('candidate-ready')
        queue = self.ops.compose_ids(self.spec['candidate']['project'])['queue-worker']
        self.ops.containers[queue]['Image'] = 'sha256:' + '7' * 64
        self.refused('candidate-identity-changed')
        self.assertTrue(self.kinds('candidate-contained'))
        self.assertFalse(set(self.ops.starts) & set(self.ops.legacy_ids.values()))

    def test_probes_are_fresh_per_invocation(self):
        self.run_until('schema-verified')
        self.run_until('schema-verified')
        names = [j['name'] for j in self.ops.jobs.values() if 'job-catalog' in j['name']]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 2)

    def test_external_ledger_change_after_preflight_refused_without_marker(self):
        self.run_until('preflighted')
        self.ops.ledger_rows.append('29990101_000000_external.sql')
        self.refused('ledger-not-baseline', 'migrated')
        self.assertFalse(self.kinds('ddl-marker'))

    def test_writer_after_settle_refused_before_marker(self):
        self.run_until('preflighted')
        self.ops.snap['db'] = 2
        self.refused('writer-after-settle', 'migrated')
        self.assertFalse(self.kinds('ddl-marker'))

    def test_active_migration_job_after_crash_is_awaited_never_duplicated(self):
        first = self.spec['expected_pending'][0]
        self.ops.migration_behaviour[first] = 'hang'
        self.refused('job-active', 'migrated')
        jobs = dict(self.ops.jobs)
        self.refused('job-active', 'migrated')
        self.assertEqual(self.ops.jobs.keys(), jobs.keys())
        identifier = next(i for i, j in self.ops.jobs.items() if j['args'][2:3] == [first])
        self.ops.finish(identifier)
        self.assertEqual(self.run_until('migrated'), 'migrated')

    def test_failed_migration_sticky_until_decision_then_attempt_two(self):
        name = self.spec['expected_pending'][1]
        self.ops.migration_behaviour[name] = 'fail'
        self.refused('migration-failed', 'migrated')
        self.refused('migration-failed', 'migrated')
        self.ops.migration_behaviour[name] = 'ok'
        self.assertEqual(self.run_until('migrated', decision=f'retry-migration:{name}'), 'migrated')
        self.assertTrue(any(j['name'].endswith('-a2') for j in self.ops.jobs.values()))

    def test_valid_concurrent_index_without_ledger_blocks_retry_and_new_job(self):
        name = '20261023_110001_notification_outbox_pending_created_idx.sql'
        self.ops.migration_behaviour[name] = 'valid-no-ledger'
        self.refused('concurrent-index-present-ledger-absent', 'migrated')
        jobs = set(self.ops.jobs)
        self.refused('retry-precondition', 'migrated', decision=f'retry-migration:{name}')
        self.assertEqual(set(self.ops.jobs), jobs)
        self.ops.indexes -= set(it.concurrent_indexes(candidate_files()['backend/migrations/' + name]))
        self.ops.migration_behaviour[name] = 'ok'
        self.assertEqual(self.run_until('migrated', decision=f'retry-migration:{name}'), 'migrated')

    def test_invalid_concurrent_index_refused(self):
        name = '20261023_100001_ai_usage_tenant_created_idx.sql'
        self.ops.migration_behaviour[name] = 'invalid'
        self.refused('concurrent-index-invalid', 'migrated')
        self.refused('retry-precondition', 'migrated', decision=f'retry-migration:{name}')

    def test_adopted_job_must_match_intended_command(self):
        self.run_until('reconciled')
        with itf.Journal(self.state) as journal:
            t = self.transition(journal)
            journal.append('intent', step='x', name='j1')
            identifier = self.ops.job_create(name='j1', kind='x', image=CANDIDATE_IMAGE, args=['a'], env={},
                                             network=APP)
            with self.assertRaises(Refused) as caught:
                t.job('x', 'j1', image=CANDIDATE_IMAGE, args=['b'])
            self.assertEqual(str(caught.exception), 'job-mismatch')
            self.ops.job_create(name='j2', kind='y', image=CANDIDATE_IMAGE, args=['a'], env={}, network=APP)
            with self.assertRaises(Refused) as caught:
                t.job('y', 'j2', image=CANDIDATE_IMAGE, args=['a'])
            self.assertEqual(str(caught.exception), 'job-without-intent')
            self.assertTrue(identifier)

    def test_legacy_restarted_externally_after_containment_refused(self):
        self.run_until('contained')
        backend = self.ops.legacy_ids['backend']
        self.ops.containers[backend]['State'].update(Running=True, StartedAt='external')
        self.refused('legacy-restarted-after-signal')

    def test_crash_between_policy_update_and_done_replays(self):
        with itf.Journal(self.state) as journal:
            self.observed(journal)
            t = self.transition(journal)
            self.die_at(t, 'contain:cron-worker:after-policy')
            with self.assertRaises(Killed):
                t.run()
        cron = self.ops.legacy_ids['cron-worker']
        self.assertEqual(self.ops.inspect(cron)['HostConfig']['RestartPolicy']['Name'], 'no')
        self.assertEqual(self.run_until('contained'), 'contained')
        self.assertEqual(self.ops.signals.count(cron), 1)

    def test_crash_after_policy_intent_before_update_replays(self):
        with itf.Journal(self.state) as journal:
            self.observed(journal)
            t = self.transition(journal)
            self.die_at(t, 'contain:queue-worker:before-policy')
            with self.assertRaises(Killed):
                t.run()
            self.assertTrue(journal.find('intent', 'policy:queue-worker'))
        queue = self.ops.legacy_ids['queue-worker']
        self.assertEqual(self.ops.inspect(queue)['HostConfig']['RestartPolicy']['Name'], 'always')
        self.assertNotIn(queue, self.ops.signals)
        self.assertEqual(self.run_until('contained'), 'contained')
        self.assertEqual(self.ops.inspect(queue)['HostConfig']['RestartPolicy']['Name'], 'no')
        self.assertEqual(self.ops.signals.count(queue), 1)

    def test_policy_reverted_externally_after_done_is_refused(self):
        with itf.Journal(self.state) as journal:
            self.observed(journal)
            t = self.transition(journal)
            self.die_at(t, 'contain:cron-worker:after-signal')
            with self.assertRaises(Killed):
                t.run()
        self.ops.update_restart(self.ops.legacy_ids['backend'], 'always')
        self.refused('legacy-restart-policy-not-persisted')

    def test_restart_policy_kept_always_is_refused(self):
        backend = self.ops.legacy_ids['backend']
        self.ops.update_restart = lambda identifier, policy: None
        self.refused('restart-policy-not-persisted', 'contained')
        self.assertNotIn(backend, self.ops.signals)

    def test_graceful_timeout_never_kills(self):
        cron = self.ops.legacy_ids['cron-worker']
        self.ops.ignore_term.add(cron)
        self.refused('graceful-timeout', 'contained')
        self.assertEqual(self.ops.signals.count(cron), 1)

    def test_signal_intent_without_delivery_proof_needs_resignal_decision(self):
        cron = self.ops.legacy_ids['cron-worker']
        self.ops.ignore_term.add(cron)
        self.refused('graceful-timeout', 'contained')
        self.refused('graceful-timeout', 'contained')  # no blind second SIGTERM
        self.assertEqual(self.ops.signals.count(cron), 1)

    def test_scope_refuses_orphans_unknown_members_and_sessions(self):
        self.run_until('observed')
        self.ops.add(hexid(900), image=LEGACY_IMAGE, name='x', labels={ops_mod.OWNER_LABEL: RUN}, policy='no',
                     running=False, nets={})
        self.refused('orphan-owned-container')
        del self.ops.containers[hexid(900)]
        self.ops.sessions.append({'addr': None, 'app': 'pastorai-transition-observer'})
        self.run_until('contained')
        self.ops.sessions.append({'addr': '192.0.2.9', 'app': 'unknown'})
        self.refused('fifth-writer-database', 'settled')

    def test_resume_legacy_pre_ddl_only_and_with_unchanged_baseline(self):
        self.run_until('preflighted')
        with itf.Journal(self.state) as journal:
            t = self.transition(journal)
            token = t.resume_token()
            with self.assertRaises(Refused):
                t.resume_legacy('wrong', token)
        self.ops.ledger_rows.append('29990101_000000_external.sql')
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            token = t.resume_token()
            with self.assertRaises(Refused) as caught:
                t.resume_legacy(token, token)
            self.assertEqual(str(caught.exception), 'ledger-not-baseline')
        self.ops.ledger_rows.remove('29990101_000000_external.sql')
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            token = t.resume_token()
            t.resume_legacy(token, token)
            self.assertIn('legacy-resumed', [e['name'] for e in journal.find('phase')])
        order = [i for i in self.ops.starts if i in self.ops.legacy_ids.values()]
        self.assertEqual(order[0], self.ops.legacy_ids['backend'])
        for identifier in self.ops.legacy_ids.values():
            self.assertEqual(self.ops.inspect(identifier)['HostConfig']['RestartPolicy']['Name'], 'always')

    def test_resume_replay_after_crash_revalidates_ledger_before_any_further_start(self):
        self.run_until('preflighted')
        real_start, calls = self.ops.start, []

        def start_then_crash(identifier):
            calls.append(identifier)
            real_start(identifier)
            if len(calls) == 2:
                raise Killed()
        self.ops.start = start_then_crash
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            token = t.resume_token()
            with self.assertRaises(Killed):
                t.resume_legacy(token, token)
        self.ops.start = real_start
        self.ops.ledger_rows.append('29990101_000000_external.sql')  # external DDL trace after the crash
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            with self.assertRaises(Refused) as caught:
                t.resume_legacy('anything', 'other')
            self.assertEqual(str(caught.exception), 'ledger-not-baseline')
        legacy_starts = [i for i in self.ops.starts if i in self.ops.legacy_ids.values()]
        self.assertEqual(len(legacy_starts), 2)  # nothing started after the external change
        self.ops.ledger_rows.remove('29990101_000000_external.sql')
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            t.resume_legacy('anything', 'other')  # replay of a confirmed resume; consumers back => no snapshot gate
            self.assertIn('legacy-resumed', [e['name'] for e in journal.find('phase')])
        self.assertEqual(len([i for i in self.ops.starts if i in self.ops.legacy_ids.values()]), 4)

    def test_recorded_resume_intent_never_skips_ledger_check(self):
        self.run_until('preflighted')
        with itf.Journal(self.state) as journal:
            journal.append('intent', step='legacy-resume', reconciliation_kept=False)
        self.ops.ledger_rows.append('29990101_000000_external.sql')
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            with self.assertRaises(Refused) as caught:
                t.resume_legacy('x', 'y')
            self.assertEqual(str(caught.exception), 'ledger-not-baseline')
        self.assertFalse(set(self.ops.starts) & set(self.ops.legacy_ids.values()))

    def test_resume_replay_refuses_resumed_role_restarted_or_changed(self):
        self.run_until('preflighted')
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep, pause_at=None)
            token = t.resume_token()
            t.checkpoint = lambda name: (_ for _ in ()).throw(Killed()) if name.endswith('queue-worker:before-update') else None
            with self.assertRaises(Killed):
                t.resume_legacy(token, token)
        backend = self.ops.legacy_ids['backend']
        self.ops.containers[backend]['RestartCount'] += 1
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            with self.assertRaises(Refused) as caught:
                t.resume_legacy('x', 'y')
            self.assertEqual(str(caught.exception), 'legacy-resumed-state-changed')

    def test_critical_queue_with_ttl_is_not_hidden_by_the_snapshot(self):
        self.spec['expect_settled'] = {'redis_lists': {'pastorai:webhooks': []}}
        self.ops.ttl['pastorai:webhooks'] = 30000
        self.refused('expectation-mismatch', 'settled')
        self.ops.ttl['pastorai:webhooks'] = -1
        self.assertEqual(self.run_until('settled'), 'settled')
        snap = [e for e in self.events if e['kind'] == 'snapshot'][-1]
        self.assertEqual(snap['redis_volatile_excluded'], 2)

    def test_resume_intent_makes_run_refuse_without_marker_or_jobs(self):
        self.run_until('preflighted')
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            token = t.resume_token()
            real = self.ops.update_restart
            self.ops.update_restart = lambda *_a: (_ for _ in ()).throw(Killed())  # crash before first update
            with self.assertRaises(Killed):
                t.resume_legacy(token, token)
            self.ops.update_restart = real
        self.refused('legacy-resume-in-progress', 'migrated')
        self.assertFalse(self.kinds('ddl-marker'))
        self.assertFalse([j for j in self.ops.jobs.values() if j['args'][:1] == ['scripts/migrate.py']])
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            t.resume_legacy('x', 'y')  # only completing the resume is allowed
            self.assertIn('legacy-resumed', [e['name'] for e in journal.find('phase')])

    def test_critical_queue_gaining_ttl_after_settle_blocks_ddl_with_zero_jobs(self):
        queue = 'pastorai:webhooks'
        self.spec['expect_settled'] = {'redis_lists': {queue: []}}
        self.run_until('preflighted')
        self.ops.ttl[queue], self.ops.lists[queue] = 30000, ['d1']  # invisible to the persistent snapshot
        self.refused('expectation-mismatch', 'migrated')
        self.assertFalse(self.kinds('ddl-marker'))
        self.assertFalse([j for j in self.ops.jobs.values() if j['args'][:1] == ['scripts/migrate.py']])

    def test_critical_queue_change_blocks_first_resume(self):
        queue = 'pastorai:webhooks:dead'
        self.spec['expect_settled'] = {'redis_lists': {queue: ['dlq']}}
        self.ops.ttl[queue], self.ops.lists[queue] = -1, ['dlq']
        self.run_until('preflighted')
        self.ops.lists[queue] = []
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            token = t.resume_token()
            with self.assertRaises(Refused) as caught:
                t.resume_legacy(token, token)
            self.assertEqual(str(caught.exception), 'expectation-mismatch')
        self.assertFalse(set(self.ops.starts) & set(self.ops.legacy_ids.values()))

    def test_dead_letter_and_scheduled_retry_contents_and_persistence(self):
        dlq, retry = 'pastorai:webhooks:dead', 'pastorai:webhooks:retry-scheduled'
        self.spec['expect_settled'] = {'redis_lists': {dlq: ['a']}, 'redis_zsets': {retry: [['b', '9999999999']]}}
        self.ops.ttl.update({dlq: -1, retry: -1})
        self.ops.lists[dlq], self.ops.zsets[retry] = ['a'], [['b', '9999999999']]
        self.assertEqual(self.run_until('settled'), 'settled')
        self.ops.zsets[retry] = [['b', '1']]  # same member, different score
        self.refused('expectation-mismatch', 'reconciled')
        self.ops.zsets[retry], self.ops.ttl[retry] = [['b', '9999999999']], 60000
        self.refused('expectation-mismatch', 'reconciled')

    def crash_resume(self, where):
        """Run a confirmed resume that dies at ``where`` on the FIRST role (backend)."""
        self.spec['expect_settled'] = {'redis_lists': {'pastorai:webhooks': []}}
        self.run_until('preflighted')
        real_update, real_start = self.ops.update_restart, self.ops.start

        def update(identifier, policy):
            if where == 'before-update':
                raise Killed()
            real_update(identifier, policy)
            if where == 'after-update':
                raise Killed()

        def start(identifier):
            real_start(identifier)
            if where == 'after-start':
                raise Killed()
        self.ops.update_restart, self.ops.start = update, start
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            token = t.resume_token()
            with self.assertRaises(Killed):
                t.resume_legacy(token, token)
            self.assertTrue(journal.find('intent', 'legacy-resume:backend'))
        self.ops.update_restart, self.ops.start = real_update, real_start
        self.ops.ttl['pastorai:webhooks'], self.ops.lists['pastorai:webhooks'] = 30000, ['d1']
        self.ops.snap['db'] = 99
        return len([i for i in self.ops.starts if i in self.ops.legacy_ids.values()])

    def resume_again(self):
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            t.resume_legacy('x', 'y')

    def test_resume_crash_before_update_never_relaxes_gates(self):
        before = self.crash_resume('before-update')
        with self.assertRaises(Refused) as caught:
            self.resume_again()
        self.assertEqual(str(caught.exception), 'writer-after-settle')
        self.assertEqual(len([i for i in self.ops.starts if i in self.ops.legacy_ids.values()]), before)
        self.assertEqual(before, 0)

    def test_resume_crash_after_update_before_start_never_relaxes_gates(self):
        before = self.crash_resume('after-update')
        self.ops.snap['db'] = 1  # only the critical queue changed: still refused
        with self.assertRaises(Refused) as caught:
            self.resume_again()
        self.assertEqual(str(caught.exception), 'expectation-mismatch')
        self.assertEqual(len([i for i in self.ops.starts if i in self.ops.legacy_ids.values()]), before)
        self.assertEqual(before, 0)

    def test_resume_crash_after_real_start_before_done_continues(self):
        before = self.crash_resume('after-start')
        self.assertEqual(before, 1)
        self.resume_again()  # backend observed running a new execution: data may legitimately change
        self.assertEqual(len([i for i in self.ops.starts if i in self.ops.legacy_ids.values()]), 4)

    def test_resume_started_without_done_then_restarted_is_ambiguous(self):
        self.crash_resume('after-start')
        self.ops.containers[self.ops.legacy_ids['backend']]['RestartCount'] += 1
        with self.assertRaises(Refused) as caught:
            self.resume_again()
        self.assertEqual(str(caught.exception), 'legacy-resume-ambiguous')

    def test_resume_started_then_exited_is_ambiguous(self):
        self.crash_resume('after-start')
        backend = self.ops.legacy_ids['backend']
        self.ops.containers[backend]['State'].update(Running=False, ExitCode=1)
        with self.assertRaises(Refused) as caught:
            self.resume_again()
        self.assertEqual(str(caught.exception), 'legacy-resume-ambiguous')
        self.assertEqual(len([i for i in self.ops.starts if i in self.ops.legacy_ids.values()]), 1)

    def test_resume_refused_after_marker(self):
        self.run_until('migrated')
        with itf.Journal(self.state) as journal:
            t = it.Transition(self.spec, journal, self.ops, clock=self.clock, sleep=self.clock.sleep)
            with self.assertRaises(Refused) as caught:
                t.resume_legacy('x', 'x')
            self.assertEqual(str(caught.exception), 'post-ddl')
        self.assertFalse(set(self.ops.starts) & set(self.ops.legacy_ids.values()))

    def test_verify_contained_exit_negative_control(self):
        observed = dict(restart_count=0, started='t0')
        data = dict(RestartCount=1, State=dict(Running=True, StartedAt='t1'), HostConfig=dict(RestartPolicy=dict(Name='always')))
        self.assertEqual(it.verify_contained_exit(observed, data), 'restarted-after-signal')


class OpsTest(unittest.TestCase):
    def spec(self):
        return dict(run_id=RUN, prefix=PREFIX, network=dict(app=APP, edge=EDGE),
                    support={'postgres': hexid(10), 'redis': hexid(11), 'evolution': hexid(12)},
                    database=dict(superuser='postgres', name='synthetic',
                                  dsn='postgresql://postgres:pw@postgres:5432/synthetic'))

    def test_job_network_is_preserved_and_unknown_refused(self):
        calls = []

        def runner(argv, input=None, timeout=120):
            calls.append(argv)
            return 0, hexid(5) + '\n'
        ops = ops_mod.DockerOps(self.spec(), runner)
        for network in ('none', APP, EDGE):
            ops.job_create(name='j', kind='k', image=CANDIDATE_IMAGE, args=[], env={}, network=network)
            self.assertEqual(calls[-1][calls[-1].index('--network') + 1], network)
        with self.assertRaises(Refused):
            ops.job_create(name='j', kind='k', image=CANDIDATE_IMAGE, args=[], env={}, network='bridge')

    def test_topology_refuses_hijacked_alias_and_foreign_dsn(self):
        def runner(argv, input=None, timeout=120):
            if argv[1:3] == ['network', 'inspect']:
                key = 'app' if argv[3] == APP else 'edge'
                members = {hexid(10): {}, hexid(11): {}, hexid(12): {}, hexid(99): {}} if key == 'app' else {}
                return 0, json.dumps([{'Id': argv[3], 'Name': f'{PREFIX}-{key}', 'Internal': True,
                                       'Labels': {ops_mod.OWNER_LABEL: RUN}, 'Containers': members}])
            identifier = argv[2]
            role = {hexid(10): 'postgres', hexid(11): 'redis', hexid(12): 'evolution'}.get(identifier, 'x')
            alias = ops_mod.SUPPORT_ALIASES.get(role, 'postgres')
            return 0, json.dumps([{'Id': identifier, 'Name': f'/{PREFIX}-{role}', 'State': {'Running': True},
                                   'Config': {'Labels': {ops_mod.OWNER_LABEL: RUN, ops_mod.ROLE_LABEL: role}},
                                   'HostConfig': {}, 'Mounts': [],
                                   'NetworkSettings': {'Ports': {}, 'Networks': {f'{PREFIX}-app': {'Aliases': [alias]}}}}])
        with self.assertRaises(Refused) as caught:
            ops_mod.DockerOps(self.spec(), runner).verify_topology()
        self.assertEqual(str(caught.exception), 'support-alias-hijack')
        spec = self.spec()
        spec['database']['dsn'] = 'postgresql://postgres:pw@db.example.test:5432/synthetic'
        with self.assertRaises(Refused) as caught:
            ops_mod.DockerOps(spec, runner).verify_topology()
        self.assertEqual(str(caught.exception), 'dsn-not-owned-alias')


class SpecTest(Base):
    def write(self, spec):
        path = self.root / 'spec.json'
        path.write_text(json.dumps(spec))
        return path

    def test_foreign_dsn_symlink_and_changed_compose_refused(self):
        spec = json.loads(json.dumps(self.spec))
        spec['database']['dsn'] = 'postgresql://postgres:pw@prod.example.test:5432/postgres'
        with self.assertRaises(Refused):
            it.load_spec(self.write(spec))
        good = self.write(self.spec)
        link = self.root / 'spec-link.json'
        link.symlink_to(good)
        with self.assertRaises(Refused):
            it.load_spec(link)
        Path(self.spec['candidate']['compose_file']).write_text('services: {changed: {}}\n')
        with self.assertRaises(Refused):
            it.load_spec(good)


if __name__ == '__main__':
    unittest.main()
