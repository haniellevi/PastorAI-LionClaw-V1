"""Ensaio do tick ativo do cron-worker legado: avaliações puras e guardas do roteiro, sem Docker real.

O ensaio físico (Postgres/Redis/worker reais) é ``deploy/rehearse_legacy_cron_active.py run``.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rehearse_legacy_containment as containment  # noqa: E402
import rehearse_legacy_cron_active as cron  # noqa: E402

LEGACY = 'sha256:' + 'a' * 64
REDIS = 'sha256:' + 'b' * 64
PG = 'sha256:' + 'c' * 64
FILES = {'app/__init__.py': b'', 'app/workers/queue_worker.py': b'# legado\n',
         'app/workers/cron_worker.py': b'# legado\n', 'app/services/calendar_oauth_flows.py': b'# legado\n',
         'requirements.lock': b'# --python-version 3.13\nredis==7.0.1\n'}
BASELINE = dict(active=1, selected=['20260101_000000_a.sql'], sql={'20260101_000000_a.sql': ''}, migrate='')
WORKER_IP, HOLDER_IP, XID = '172.30.0.4', '172.30.0.5', '731'


@pytest.fixture(autouse=True)
def local_docker(monkeypatch):
    for name in containment.REMOTE_ENV:
        monkeypatch.delenv(name, raising=False)


def _rehearsal(runner=lambda argv: '', cls=cron.CronRehearsal, files=FILES, **kwargs):
    return cls(legacy_image=LEGACY, redis_image=REDIS, postgres_image=PG, files=files, baseline=dict(BASELINE),
               runner=runner, sleep=lambda _: None, **kwargs)


# -- avaliações puras -------------------------------------------------------
def _snapshot(**worker):
    w = dict(pid=20, addr=WORKER_IP, state='active', wait_type='Lock', wait='transactionid', xid=None,
             delete=True, blockers=[10])
    w.update(worker)
    holder = dict(pid=10, addr=HOLDER_IP, state='idle in transaction', wait_type='Client', wait='ClientRead',
                  xid=XID, delete=False, blockers=[])
    return dict(backends=[holder, w], waits=[dict(pid=20, locktype='transactionid', xid=XID, mode='ShareLock')])


def test_blocked_on_holder_accepts_delete_waiting_on_holder_xid():
    assert cron.blocked_on_holder(_snapshot(), WORKER_IP, HOLDER_IP, XID)


@pytest.mark.parametrize('mutate', [
    lambda s: s['backends'][1].update(blockers=[]),                          # sem bloqueador
    lambda s: s['backends'][1].update(blockers=[10, 99]),                    # outro bloqueador
    lambda s: s['backends'][1].update(delete=False),                        # outra consulta
    lambda s: s['backends'][1].update(wait='tuple'),                        # espera diferente
    lambda s: s['backends'][1].update(state='idle'),                        # worker não ativo
    lambda s: s['backends'][0].update(state='idle'),                        # holder já sem transação
    lambda s: s['backends'][0].update(xid='999'),                           # xid diferente do publicado
    lambda s: s['backends'].append(dict(s['backends'][1], pid=21)),          # segundo backend do worker
    lambda s: s['backends'].append(dict(s['backends'][0], pid=30, addr='172.30.0.9')),  # backend estranho
    lambda s: s.update(waits=[]),                                            # nenhum lock pendente
    lambda s: s['waits'].append(dict(pid=21, locktype='relation', xid=None, mode='AccessExclusiveLock')),
    lambda s: s['waits'][0].update(xid='999'),
])
def test_blocked_on_holder_rejects_any_other_lock_picture(mutate):
    snapshot = _snapshot()
    mutate(snapshot)
    assert not cron.blocked_on_holder(snapshot, WORKER_IP, HOLDER_IP, XID)


def _flow(identifier, expired, **row):
    base = dict(id=identifier, igreja_id=cron.TENANT, app_user_id=cron.APP_USER, consumed_at=None,
                finish_result=None, expires_at='t')
    base.update(row)
    return dict(row=base, expired=expired)


SEEDED = [_flow(cron.EXPIRED, True), _flow(cron.VALID, False)]


def test_seeded_flows_are_one_expired_and_one_valid_in_own_tenant():
    assert cron.seeded_ok(SEEDED)
    assert not cron.seeded_ok(SEEDED[:1])
    assert not cron.seeded_ok([_flow(cron.EXPIRED, True, consumed_at='x'), SEEDED[1]])
    assert not cron.seeded_ok([SEEDED[0], _flow(cron.VALID, True)])
    assert not cron.seeded_ok([_flow(cron.EXPIRED, True, igreja_id='00000000-0000-0000-0000-000000000001'),
                               SEEDED[1]])


def test_purge_must_remove_only_expired_and_keep_valid_identical():
    assert cron.purged_ok([SEEDED[1]], SEEDED)
    assert not cron.purged_ok([], SEEDED)
    assert not cron.purged_ok(SEEDED, SEEDED)
    assert not cron.purged_ok([_flow(cron.VALID, False, expires_at='renovado')], SEEDED)


def test_seed_may_touch_only_seeded_tables():
    before = dict(igrejas='1', app_users='2', pessoas='3', crons='4')
    assert cron.seed_touched_only(before, dict(before, igrejas='x', app_users='y'))
    assert not cron.seed_touched_only(before, dict(before, pessoas='x'))
    assert not cron.seed_touched_only(before, dict(before, nova='x'))
    assert 'calendar_oauth_flows' not in cron.SEEDED_TABLES and "<> 'calendar_oauth_flows'" in cron.DIGEST_SQL


def _log(*messages, logger='pastorai.cron_worker', level='INFO'):
    return '\n'.join(f'2026-10-25 12:00:0{i},000 {level} {logger} {m}' for i, m in enumerate(messages)) + '\n'


STARTED = 'Cron worker started (tick=10s)'
DONE = 'Cron tick done (sla=0, crons=0, plan_changes=0, oauth_flows_purged=1)'
FULL_LOG = _log(STARTED, 'Cron worker shutdown requested', DONE, 'Cron worker stopped')


def test_log_summary_of_expected_run():
    assert cron.log_summary(FULL_LOG) == cron.EXPECTED_LOG
    assert cron.log_summary(FULL_LOG + _log('pool ok', logger='pastorai.performance')) == cron.EXPECTED_LOG


@pytest.mark.parametrize('text', [
    _log(STARTED, 'Cron worker shutdown requested', DONE, DONE, 'Cron worker stopped'),        # segundo tick
    _log(STARTED, DONE, 'Cron worker shutdown requested', 'Cron worker stopped'),              # sinal após o tick
    _log(STARTED, 'Cron worker shutdown requested',
         'Cron tick done (sla=0, crons=0, plan_changes=0, oauth_flows_purged=0)', 'Cron worker stopped'),
    _log(STARTED, 'Cron worker shutdown requested',
         'Cron tick done (sla=1, crons=0, plan_changes=0, oauth_flows_purged=1)', 'Cron worker stopped'),
    FULL_LOG + _log('OAuth flow purge failed', level='ERROR'),
    FULL_LOG + _log('Cron worker stalled; heartbeat renewal stopped', level='ERROR'),
    FULL_LOG + 'Traceback (most recent call last):\n',
    FULL_LOG + _log('Cron worker started (tick=10s)'),                                          # reinício
    _log('Cron worker started (tick=300s)', 'Cron worker shutdown requested', DONE, 'Cron worker stopped'),
])
def test_log_summary_rejects_extra_ticks_errors_or_unparsed_output(text):
    assert cron.log_summary(text) != cron.EXPECTED_LOG


def test_worker_config_is_real_entrypoint_with_closed_gates():
    assert cron.ENTRY == ['-m', 'app.workers.cron_worker'] and cron.ROLE == 'cron-worker'
    assert cron.CRON_ENV['CRON_TICK_SECONDS'] == '10'
    assert cron.CRON_ENV['ALLOW_REAL_SENDS'] == 'false' and cron.CRON_ENV['ASAAS_BILLING_ENABLED'] == 'false'
    assert cron.CRON_ENV['WHATSAPP_PILOTO_IGREJA_IDS'] == '' and cron.CRON_ENV['BREVO_SEND_MODE'] == 'off'
    assert cron.CRON_ENV['EVOLUTION_API_URL'] == 'http://127.0.0.1:9'
    assert cron.PROGRESS_BUDGET_S < 30 and cron.HOLD_S < cron.PROGRESS_BUDGET_S
    for code in (cron.HOLDER_PROBE,):
        compile(code, '<probe>', 'exec')
    assert 'for update' in cron.HOLDER_PROBE and 'import app' not in cron.HOLDER_PROBE
    assert 'delete' not in cron.SEED_SQL.lower() and 'update ' not in cron.SEED_SQL.lower()


def test_source_without_cron_worker_is_refused_before_docker():
    calls = []
    files = {k: v for k, v in FILES.items() if k != 'app/workers/cron_worker.py'}
    with pytest.raises(containment.Refused, match='source-incomplete'):
        _rehearsal(calls.append, files=files)
    assert calls == []


def test_remote_docker_refused_before_any_resource(monkeypatch):
    calls = []
    monkeypatch.setenv('DOCKER_HOST', 'tcp://203.0.113.1:2376')
    rehearsal = _rehearsal(lambda argv: calls.append(argv) or '')
    with pytest.raises(containment.Refused, match='remote-docker'):
        rehearsal.preflight()
    assert not any(argv[1] in ('run', 'network') for argv in calls)


def test_start_worker_runs_pid1_cron_entrypoint_hardened_without_host_exposure():
    calls = []
    rehearsal = _rehearsal(lambda argv: calls.append(argv) or 'f' * 64)
    rehearsal.network = 'e' * 64
    rehearsal.start_worker()
    args = calls[-1][2:]
    assert rehearsal.ids['cron-worker'] == 'f' * 64 and 'f' * 64 in rehearsal.created['containers']
    assert args[-3:] == [LEGACY, '-m', 'app.workers.cron_worker']
    assert args[args.index('--entrypoint') + 1] == 'python' and args[args.index('--pull') + 1] == 'never'
    assert args[args.index('--network') + 1] == 'e' * 64 and '--read-only' in args
    assert f'{containment.ROLE_LABEL}=cron-worker' in args and 'CRON_TICK_SECONDS=10' in args
    assert not {'-p', '--publish', '-P', '--publish-all', '-v', '--volume', '--mount', '--privileged'} & set(args)
    assert args[args.index('--name') + 1].startswith('pastorai-synthetic-legacy-cron-')


# -- roteiro com mundo falso -----------------------------------------------
class World(cron.CronRehearsal):
    """Substitui só as primitivas de Docker/SQL/Redis; o roteiro ``rehearse`` é o real."""

    def __init__(self, **faults):
        super().__init__(legacy_image=LEGACY, redis_image=REDIS, postgres_image=PG, files=FILES,
                         baseline=dict(BASELINE), runner=self._no_docker, sleep=lambda _: None)
        self.faults, self.events, self.now = faults, [], 0.0
        self.signalled = self.released = self.exited = self.final_checked = False
        self.clock = self._tick

    def _no_docker(self, argv):
        raise AssertionError(argv)

    def _tick(self):
        self.now += 0.05
        return self.now

    def fault(self, name):
        return self.faults.get(name) and (self.signalled or self.faults.get('early'))

    # primitivas
    def preflight(self):
        self.events.append('preflight')

    def create_support(self):
        self.phase = 'running'

    def apply_baseline(self):
        self.events.append('baseline')

    def seed(self):
        self.seeded, self.before = list(SEEDED), dict(igrejas='d1', pessoas='d2')

    def spawn(self, role, python_args, env=None):
        assert role == 'holder' and python_args[:3] == ['-I', '-c', cron.HOLDER_PROBE]
        self.events.append('holder')
        return 'holder-id'

    def start_worker(self):
        self.started_at = self.now  # ``started`` do roteiro é o clock() imediatamente anterior
        self.ids[self.role] = 'worker-id'
        self.events.append('start')

    def ip(self, identifier):
        return WORKER_IP if identifier == 'worker-id' else HOLDER_IP

    def running(self):
        return not self.exited and not self.fault('dies')

    def flows(self):
        if self.released:
            return [_flow(cron.VALID, False, expires_at='renovado')] if self.faults.get('touch_valid') else [SEEDED[1]]
        return SEEDED[1:] if self.fault('purged') else list(SEEDED)

    def digest(self):
        changed = self.fault('digest') or (self.released and self.faults.get('tick_effect'))
        return dict(self.before, pessoas='changed') if changed else dict(self.before)

    def psql_json(self, sql):
        assert sql == cron.BLOCK_SQL and not self.released
        return _snapshot(blockers=[]) if self.fault('lock_lost') else _snapshot()

    def redis(self, *args):
        if args == ('GET', cron.HELD):
            return XID
        if args == ('GET', cron.HEARTBEAT):
            if self.final_checked and not self.released and self.faults.get('heartbeat_final'):
                return self.faults['heartbeat_final']
            return 'stopped' if self.exited else 'running'
        if args == ('SET', cron.RELEASE, '1'):
            self.released = True
            self.events.append('release')
            return 'OK'
        if args == ('DEL', cron.RELEASE, cron.HELD):
            return '2'
        raise AssertionError(args)

    def keys(self):
        return {cron.HEARTBEAT}

    def check_worker(self, *, running, extra=()):
        assert running == (not self.exited)
        if not (self.signalled and running):
            return
        # Só o check imediatamente anterior ao RELEASE tem worker vivo depois do sinal.
        self.final_checked = True
        if (advance := self.faults.get('final_check_advance')):
            self.now += advance
        if (elapsed := self.faults.get('final_elapsed')) is not None:
            self.now = self.started_at + elapsed - 0.05  # o próximo clock() mede exatamente ``elapsed``

    def docker(self, *args):
        assert args == ('kill', '--signal', 'SIGTERM', 'worker-id')
        self.signalled = True
        self.events.append('sigterm')
        if self.faults.get('slow'):
            self.now += cron.PROGRESS_BUDGET_S

    def collect(self, identifier, timeout, refusal):
        assert identifier == 'holder-id' and self.released
        return f'released {XID}'

    def _await_exit(self, role, grace_s):
        assert role == 'cron-worker' and self.released
        self.exited = True
        self.events.append('exit')
        if self.faults.get('slow_exit'):
            self.now += cron.CRON_TICK_S

    def worker_logs(self):
        if not self.released:
            return _log(STARTED)
        return FULL_LOG + (_log(DONE) if self.faults.get('second_tick') else '')


def test_script_signals_while_blocked_then_releases_and_proves_single_purge():
    world = World()
    cron.rehearse(world)
    assert world.events == ['preflight', 'baseline', 'holder', 'start', 'sigterm', 'release', 'exit']
    assert world.checks[-1] == 'no-second-tick-exit-before-tick-interval-and-state-stable-after-exit'
    assert world.log == cron.EXPECTED_LOG and world.observed['shutdown_logged_while_blocked'] is False
    assert world.timings['blocked_s'] < cron.PROGRESS_BUDGET_S


@pytest.mark.parametrize('fault, code', [
    ('dies', 'worker-exited-during-barrier'),
    ('purged', 'purged-through-barrier'),
    ('lock_lost', 'barrier-lost'),
    ('digest', 'barrier-lost'),
    ('slow', 'barrier-too-long'),
])
def test_script_never_releases_when_the_held_state_is_not_proven(fault, code):
    world = World(**{fault: True})
    with pytest.raises(containment.Refused, match=code):
        cron.rehearse(world)
    assert 'sigterm' in world.events and 'release' not in world.events and not world.exited


def test_final_check_that_consumes_the_budget_refuses_without_release():
    world = World(final_check_advance=cron.PROGRESS_BUDGET_S)
    with pytest.raises(containment.Refused, match='barrier-too-long'):
        cron.rehearse(world)
    assert 'release' not in world.events and not world.exited


@pytest.mark.parametrize('offset, released', [(-0.0004, True), (0.0004, False)])
def test_budget_decision_uses_unrounded_elapsed_time(offset, released):
    """Os dois lados arredondam para 20.000 no relatório; só o valor exato decide."""
    world = World(final_elapsed=cron.PROGRESS_BUDGET_S + offset)
    if released:
        cron.rehearse(world)
        assert 'release' in world.events
    else:
        with pytest.raises(containment.Refused, match='barrier-too-long'):
            cron.rehearse(world)
        assert 'release' not in world.events
    assert world.timings['blocked_s'] == cron.PROGRESS_BUDGET_S


def test_heartbeat_not_running_right_before_release_refuses():
    world = World(heartbeat_final='error')
    with pytest.raises(containment.Refused, match='barrier-lost'):
        cron.rehearse(world)
    assert 'release' not in world.events and not world.exited


def test_script_refuses_when_barrier_never_forms():
    world = World(lock_lost=True, early=True)
    with pytest.raises(containment.Refused, match='barrier-timeout'):
        cron.rehearse(world)
    assert 'sigterm' not in world.events and 'release' not in world.events


@pytest.mark.parametrize('fault, code', [
    ('touch_valid', 'purge-state'),
    ('tick_effect', 'unexpected-tick-effects'),
    ('second_tick', 'worker-log'),
    ('slow_exit', 'exit-not-before-next-tick'),
])
def test_script_refuses_wrong_outcome_after_release(fault, code):
    world = World(**{fault: True})
    with pytest.raises(containment.Refused, match=code):
        cron.rehearse(world)
    assert world.events[-2:] == ['release', 'exit']


def test_report_is_written_with_production_ready_false_on_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(cron, 'legacy_sources', lambda repo: {k: v for k, v in FILES.items()
                                                               if k != 'app/workers/cron_worker.py'})
    monkeypatch.setattr(cron, 'select_baseline', lambda repo: dict(BASELINE))
    report = tmp_path / 'report.json'
    assert cron.main(['run', '--repo', str(tmp_path), '--report', str(report)]) == 1
    data = json.loads(report.read_text())
    assert data['status'] == 'refused' and data['reason'] == 'source-incomplete'
    assert data['production_ready'] is False and data['legacy_sha'] == cron.LEGACY_SHA
