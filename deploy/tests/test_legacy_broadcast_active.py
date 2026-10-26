"""Ensaio do broadcast-worker legado com envio ativo: avaliações puras e guardas do roteiro, sem Docker real.

O ensaio físico (Postgres/Redis/Evolution falsa/worker reais) é ``deploy/rehearse_legacy_broadcast_active.py run``.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rehearse_legacy_broadcast_active as bc  # noqa: E402
import rehearse_legacy_containment as containment  # noqa: E402
import rehearse_legacy_queue_active as active  # noqa: E402

LEGACY = 'sha256:' + 'a' * 64
REDIS = 'sha256:' + 'b' * 64
PG = 'sha256:' + 'c' * 64
FILES = {'app/__init__.py': b'', 'app/workers/queue_worker.py': b'# legado\n',
         'app/workers/broadcast_worker.py': b'# legado\n', 'app/services/broadcast_delivery.py': b'# legado\n',
         'app/services/evolution.py': b'# legado\n', 'app/services/broadcast_health.py': b'# legado\n',
         'requirements.lock': b'# --python-version 3.13\nredis==7.0.1\n'}
BASELINE = dict(active=1, selected=['20260101_000000_a.sql'], sql={'20260101_000000_a.sql': ''}, migrate='')
A, B = bc.TENANT_A, bc.TENANT_B
A1, A2 = bc.CHURCHES[A]['phones']
(B1,) = bc.CHURCHES[B]['phones']
CLAIM = 'broadcast-1-0123abcd'
T0, T1, T2, T3 = '2026-10-26T12:00:00+00:00', '2026-10-26T12:00:01+00:00', '2026-10-26T12:02:01+00:00', \
    '2026-10-26T12:00:05+00:00'


@pytest.fixture(autouse=True)
def local_docker(monkeypatch):
    for name in containment.REMOTE_ENV:
        monkeypatch.delenv(name, raising=False)


# -- ledgers fictícios --------------------------------------------------------
def _seed():
    broadcasts, executions, deliveries = [], [], []
    for tenant, church in bc.CHURCHES.items():
        bid, xid = 'b-' + church['label'], 'x-' + church['label']
        broadcasts.append(dict(id=bid, igreja_id=tenant, titulo='Comunicado sintetico', mensagem=church['text'],
                               segmentos=['todos'], modo='agora', status='agendado', alcance=len(church['phones']),
                               proxima_execucao=None, claim_ate=None, claim_por=None, created_at=T0))
        executions.append(dict(row=dict(id=xid, igreja_id=tenant, broadcast_id=bid, seq=1, data_nominal='2026-10-26',
                                        hora_nominal='09:00', iniciada_em=None, finalizada_em=None, lease_ate=None,
                                        claim_por=None, criado_em=T0), lease_live=None))
        for phone in church['phones']:
            deliveries.append(dict(row=dict(id='e-' + phone, igreja_id=tenant, execucao_id=xid, pessoa_id='p-' + phone,
                                            telefone=phone, status='pendente', tentativas=0, retry_budget_used=0,
                                            lease_ate=None, next_attempt_at=None, claim_por=None,
                                            ultimo_erro_classe=None, criado_em=T0, atualizado_em=T0),
                                   lease_live=None, lease_s=None))
    return dict(deliveries=sorted(deliveries, key=lambda d: d['row']['telefone']),
                executions=executions, broadcasts=broadcasts)


SEED = _seed()


def _rows(ledger, phone):
    return next(d for d in ledger['deliveries'] if d['row']['telefone'] == phone)


def _execution(ledger, tenant):
    return next(x for x in ledger['executions'] if x['row']['igreja_id'] == tenant)


def _broadcast(ledger, tenant):
    return next(b for b in ledger['broadcasts'] if b['igreja_id'] == tenant)


def _held(phone=A1, claim=CLAIM):
    ledger = copy.deepcopy(SEED)
    item = _rows(ledger, phone)
    item['row'].update(status='em_envio', tentativas=1, lease_ate=T2, claim_por=claim, atualizado_em=T1)
    item.update(lease_live=True, lease_s=120.0)
    x = _execution(ledger, bc.PHONES[phone])
    x['row'].update(iniciada_em=T1, lease_ate=T2, claim_por=claim)
    x['lease_live'] = True
    return ledger


def _stopped(phone=A1, status=200):
    ledger = _held(phone)
    final, error = bc.OUTCOMES[status]
    item = _rows(ledger, phone)
    item['row'].update(status=final, ultimo_erro_classe=error, lease_ate=None, claim_por=None, atualizado_em=T3)
    item.update(lease_live=None, lease_s=None)
    tenant = bc.PHONES[phone]
    if len(bc.CHURCHES[tenant]['phones']) == 1:
        x = _execution(ledger, tenant)
        x['row'].update(finalizada_em=T3, lease_ate=None, claim_por=None)
        x['lease_live'] = None
        _broadcast(ledger, tenant)['status'] = 'enviado'
    return ledger


def _drained(phone=A1, status=200):
    ledger = _stopped(phone, status)
    for other in bc.PHONES:
        if other != phone:
            _rows(ledger, other)['row'].update(status='aceito', tentativas=1, atualizado_em='later')
    for x in ledger['executions']:
        x['row'].update(iniciada_em=x['row']['iniciada_em'] or 'later', finalizada_em='later', lease_ate=None,
                        claim_por=None)
        x['lease_live'] = None
    for b in ledger['broadcasts']:
        b['status'] = 'enviado'
    return ledger


def _request(phone):
    tenant = bc.PHONES[phone]
    return dict(instance=bc.CHURCHES[tenant]['instance'], number='55' + phone, text=bc.CHURCHES[tenant]['text'])


# -- configuração e guardas -------------------------------------------------
def test_gates_open_only_in_worker_env_and_legacy_defaults_untouched():
    env = bc.BROADCAST_ENV
    assert bc.ENTRY == ['-m', 'app.workers.broadcast_worker'] and bc.ROLE == 'broadcast-worker'
    assert env['ALLOW_REAL_SENDS'] == 'true' and env['BROADCAST_ASYNC_ENABLED'] == 'true'
    assert env['EVOLUTION_API_URL'] == 'http://fake-evolution:8080' and env['EVOLUTION_API_KEY'] == bc.EVOLUTION_KEY
    assert env['BREVO_SEND_MODE'] == 'off' and env['ASAAS_BILLING_ENABLED'] == 'false'
    assert env['WHATSAPP_PILOTO_IGREJA_IDS'] == '' and env['APP_ENV'] != 'production'
    # Lease, intervalo, tentativas e claim ficam nos defaults legados (nada encurtado para facilitar).
    assert not {k for k in env if k.startswith('BROADCAST_') and k not in (
        'BROADCAST_ASYNC_ENABLED', 'BROADCAST_WORKER_TICK_SECONDS')}
    # Probes e seed continuam com gates fechados.
    assert active.ACTIVE_ENV['ALLOW_REAL_SENDS'] == 'false' and active.ACTIVE_ENV['BROADCAST_ASYNC_ENABLED'] == 'false'


def test_partial_deadlines_stay_below_http_timeout_and_heartbeat_ttl():
    # Guardas parciais; o total comando SIGTERM -> saída é recusado à parte (ver teste do roteiro).
    assert bc.HOLD_S < bc.RELEASE_BUDGET_S < bc.HTTP_TIMEOUT_S < bc.HEARTBEAT_TTL_S
    assert bc.HELD_MS_MAX < bc.HTTP_TIMEOUT_S * 1000 and bc.LEASE_S == 120
    assert bc.OBSERVE_S > bc.SEND_INTERVAL_S + bc.TICK_S


def test_probes_compile_and_phones_are_fictitious():
    for code in (bc.FAKE_EVOLUTION, bc.SEED_PROBE):
        compile(code, '<probe>', 'exec')
    assert all(len(p) == 11 and p.startswith('009') for p in bc.PHONES)  # fictícios, DDD inexistente


def test_source_without_broadcast_delivery_is_refused_before_docker():
    calls = []
    files = {k: v for k, v in FILES.items() if k != 'app/services/broadcast_delivery.py'}
    with pytest.raises(containment.Refused, match='source-incomplete'):
        _rehearsal(calls.append, files=files)
    with pytest.raises(containment.Refused, match='held-status'):
        _rehearsal(calls.append, held_status=429)
    assert calls == []


def _rehearsal(runner=lambda argv: '', files=FILES, **kwargs):
    return bc.BroadcastActiveRehearsal(legacy_image=LEGACY, redis_image=REDIS, postgres_image=PG, files=files,
                                       baseline=dict(BASELINE), runner=runner, sleep=lambda _: None, **kwargs)


def test_worker_and_fake_are_hardened_pid1_without_init_or_host_exposure():
    calls = []
    rehearsal = _rehearsal(lambda argv: calls.append(argv) or 'f' * 64)
    rehearsal.network = 'e' * 64
    rehearsal.start_worker()
    worker = calls[-1][2:]
    assert worker[-3:] == [LEGACY, '-m', 'app.workers.broadcast_worker'] and '--init=false' in worker
    assert 'ALLOW_REAL_SENDS=true' in worker and f'EVOLUTION_API_KEY={bc.EVOLUTION_KEY}' in worker
    rehearsal._check_fake = lambda: None
    rehearsal.redis = lambda *args: '1' if args == ('GET', bc.READY) else '0'
    rehearsal.start_fake()
    fake = next(argv[2:] for argv in calls if bc.FAKE_EVOLUTION in argv)
    assert fake[fake.index(LEGACY) + 1:fake.index(LEGACY) + 4] == ['-I', '-c', bc.FAKE_EVOLUTION]
    assert fake[fake.index('--network-alias') + 1] == 'fake-evolution' and '--init=false' in fake
    assert 'REDIS_URL=redis://redis:6379/0' in fake and not any(a.startswith('ALLOW_REAL_SENDS') for a in fake)
    for args in (worker, fake):
        assert args[args.index('--network') + 1] == 'e' * 64 and '--read-only' in args
        assert args[args.index('--pull') + 1] == 'never' and args[args.index('--cap-drop') + 1] == 'ALL'
        assert not {'-p', '--publish', '-P', '--publish-all', '-v', '--volume', '--mount', '--privileged'} & set(args)


def test_remote_docker_refused_before_any_resource(monkeypatch):
    calls = []
    monkeypatch.setenv('DOCKER_HOST', 'tcp://203.0.113.1:2376')
    rehearsal = _rehearsal(lambda argv: calls.append(argv) or '')
    with pytest.raises(containment.Refused, match='remote-docker'):
        rehearsal.preflight()
    assert not any(argv[1] in ('run', 'network') for argv in calls)


# -- avaliações puras -------------------------------------------------------
def test_seeded_ledger_is_two_immediate_broadcasts_and_three_pending():
    assert bc.seeded_ok(SEED)


@pytest.mark.parametrize('mutate', [
    lambda s: s['deliveries'].pop(),                                             # entrega a menos
    lambda s: _rows(s, A1)['row'].update(status='em_envio'),
    lambda s: _rows(s, A2)['row'].update(tentativas=1),
    lambda s: _rows(s, B1)['row'].update(igreja_id=A),                            # outra igreja
    lambda s: _rows(s, B1)['row'].update(execucao_id='x-A'),
    lambda s: _execution(s, A)['row'].update(iniciada_em=T1),
    lambda s: _broadcast(s, A).update(proxima_execucao=T0),                      # tick materializaria de novo
    lambda s: _broadcast(s, B).update(mensagem='Comunicado sintetico A'),
])
def test_seeded_ledger_rejects_anything_else(mutate):
    ledger = copy.deepcopy(SEED)
    mutate(ledger)
    assert not bc.seeded_ok(ledger)


def _with_extra(ledger, table, before):
    """Linha extra com ID distinto e a MESMA chave da primeira linha, antes ou depois da original."""
    items = ledger[table]
    extra = copy.deepcopy(items[0])
    (extra if table == 'broadcasts' else extra['row'])['id'] = 'extra-' + table
    items.insert(0 if before else 1, extra)
    return ledger


PHASES = {
    'seed': (lambda: copy.deepcopy(SEED), lambda ledger: bc.seeded_ok(ledger)),
    'held': (lambda: _held(A1), lambda ledger: bc.held_claim(ledger, SEED, A1) is not None),
    'stopped': (lambda: _stopped(A1), lambda ledger: bc.stopped_ok(ledger, SEED, A1, CLAIM, 200)),
    'drained': (lambda: _drained(A1), lambda ledger: bc.drained_ok(ledger, SEED, _stopped(A1), A1)),
}


@pytest.mark.parametrize('phase', sorted(PHASES))
@pytest.mark.parametrize('table', ['broadcasts', 'executions', 'deliveries'])
@pytest.mark.parametrize('before', [True, False])
def test_extra_row_with_same_key_is_refused_in_every_phase(phase, table, before):
    build, accepts = PHASES[phase]
    assert accepts(build())
    assert not accepts(_with_extra(build(), table, before))


@pytest.mark.parametrize('phase', ['held', 'stopped', 'drained'])
@pytest.mark.parametrize('table', ['broadcasts', 'executions', 'deliveries'])
def test_row_replaced_by_other_id_is_refused_after_seed(phase, table):
    build, accepts = PHASES[phase]
    ledger = build()
    first = ledger[table][0]
    (first if table == 'broadcasts' else first['row'])['id'] = 'replaced'
    assert not accepts(ledger)


def test_ledger_shape_reports_counts_and_uniqueness_only():
    shape = bc.ledger_shape(_with_extra(_stopped(A1), 'broadcasts', True), SEED)
    assert shape['broadcasts'] == dict(count=3, keys_exact_unique=False, ids_unique=True, seed_ids=False)
    assert shape['deliveries'] == dict(count=3, keys_exact_unique=True, ids_unique=True, seed_ids=True)


def test_held_identity_comes_from_received_number_instance_and_text():
    assert bc.held_identity([_request(B1)]) == (B1, B)
    assert bc.held_identity([_request(A2)]) == (A2, A)
    assert bc.held_identity([]) is None and bc.held_identity([_request(A1), _request(A2)]) is None
    assert bc.held_identity([dict(_request(B1), instance=bc.CHURCHES[A]['instance'])]) is None
    assert bc.held_identity([dict(_request(B1), text='outro')]) is None
    assert bc.held_identity([dict(_request(B1), number='5500900000999')]) is None


@pytest.mark.parametrize('phone', [A1, A2, B1])
def test_held_claim_accepts_only_the_held_delivery_in_flight(phone):
    assert bc.held_claim(_held(phone), SEED, phone) == CLAIM


def test_held_claim_requires_worker_id_of_pid1():
    # ``broadcast-{os.getpid()}-...``: outro PID (docker-init como PID 1) é recusa, mesmo coerente na ocorrência.
    assert bc.held_claim(_held(A1, claim='broadcast-7-0123abcd'), SEED, A1) is None
    assert bc.held_claim(_held(A1, claim='broadcast-1-0123'), SEED, A1) is None


@pytest.mark.parametrize('mutate', [
    lambda s: _rows(s, A1)['row'].update(tentativas=2),                           # nova tentativa
    lambda s: _rows(s, A1).update(lease_s=30.0),                                  # lease encurtado
    lambda s: _rows(s, A1).update(lease_live=False),                              # lease vencido
    lambda s: _rows(s, A2)['row'].update(status='em_envio'),                      # segunda em voo
    lambda s: _rows(s, B1)['row'].update(atualizado_em=T1),                       # outra tocada
    lambda s: _execution(s, A)['row'].update(iniciada_em=None),
    lambda s: _execution(s, B)['row'].update(iniciada_em=T1),
    lambda s: _broadcast(s, A).update(status='enviado'),
])
def test_held_claim_rejects_any_other_in_flight_picture(mutate):
    ledger = _held(A1)
    mutate(ledger)
    assert bc.held_claim(ledger, SEED, A1) is None
    assert bc.held_claim(_held(A1), SEED, A2) is None  # retida identificada por número, não por ordem


@pytest.mark.parametrize('phone', [A1, B1])
@pytest.mark.parametrize('status', [200, 500])
def test_stopped_accepts_truthful_result_in_both_church_shapes(phone, status):
    assert bc.stopped_ok(_stopped(phone, status), SEED, phone, CLAIM, status)
    assert not bc.stopped_ok(_stopped(phone, status), SEED, phone, CLAIM, 700 - status)


@pytest.mark.parametrize('mutate', [
    lambda s: _rows(s, A1)['row'].update(claim_por=CLAIM),                        # claim não limpo
    lambda s: _rows(s, A1)['row'].update(status='em_envio'),                      # resultado não commitado
    lambda s: _rows(s, A1)['row'].update(tentativas=2),
    lambda s: _rows(s, A2)['row'].update(status='falhou_retentavel', tentativas=0),  # cancelada pelo sinal
    lambda s: _rows(s, B1)['row'].update(status='aceito', tentativas=1),         # rodízio seguiu após o sinal
    lambda s: _execution(s, A)['row'].update(finalizada_em=T3),                  # finalizou com pendência
    lambda s: _broadcast(s, B).update(status='enviado'),
])
def test_stopped_rejects_second_send_or_untruthful_state(mutate):
    ledger = _stopped(A1)
    mutate(ledger)
    assert not bc.stopped_ok(ledger, SEED, A1, CLAIM, 200)


def test_stopped_single_delivery_church_must_finalize_its_occurrence():
    ledger = _stopped(B1)
    _execution(ledger, B)['row']['finalizada_em'] = None
    assert not bc.stopped_ok(ledger, SEED, B1, CLAIM, 200)


@pytest.mark.parametrize('phone', [A1, B1])
def test_drained_accepts_two_pending_accepted_and_held_untouched(phone):
    assert bc.drained_ok(_drained(phone), SEED, _stopped(phone), phone)
    assert bc.drained_ok(_drained(phone, 500), SEED, _stopped(phone, 500), phone)


@pytest.mark.parametrize('mutate', [
    lambda s: _rows(s, A1)['row'].update(tentativas=2, atualizado_em='later'),   # retida reenviada
    lambda s: _rows(s, A1)['row'].update(atualizado_em='later'),                 # retida reescrita
    lambda s: _rows(s, A2)['row'].update(status='pendente', tentativas=0),       # não drenada
    lambda s: _rows(s, B1)['row'].update(tentativas=2),
    lambda s: _execution(s, A)['row'].update(finalizada_em=None),
    lambda s: _broadcast(s, B).update(status='agendado'),
])
def test_drained_rejects_resend_or_incomplete_drain(mutate):
    ledger = _drained(A1)
    mutate(ledger)
    assert not bc.drained_ok(ledger, SEED, _stopped(A1), A1)


def test_restart_requests_must_be_exactly_the_two_pending():
    assert bc.restart_requests_ok([_request(A1), _request(B1), _request(A2)], A1)
    assert bc.restart_requests_ok([_request(B1), _request(A2), _request(A1)], B1)
    assert not bc.restart_requests_ok([_request(A1), _request(A1), _request(B1)], A1)  # retida repetida
    assert not bc.restart_requests_ok([_request(A1), _request(A2), _request(A2)], A1)  # duplicata
    assert not bc.restart_requests_ok([_request(A1), _request(A2)], A1)
    assert not bc.restart_requests_ok([_request(A1), _request(A2), dict(_request(B1), text='x')], A1)


def test_responses_in_order_and_held_within_http_timeout_margin():
    ok = [dict(seq=1, status=200, held_ms=4400), dict(seq=2, status=200, held_ms=1), dict(seq=3, status=200, held_ms=1)]
    assert bc.responses_ok(ok[:1], [200]) and bc.responses_ok(ok, [200, 200, 200])
    assert not bc.responses_ok(ok[:1], [500]) and not bc.responses_ok(ok[:2], [200, 200, 200])
    assert not bc.responses_ok([dict(ok[0], held_ms=bc.HELD_MS_MAX)], [200])
    assert not bc.responses_ok([dict(seq=1, status=None)], [200])


def _log(*lines):
    return ''.join(f'2026-10-26 12:00:{i:02d},000 {level} {name} {message}\n'
                   for i, (level, name, message) in enumerate(lines))


def _w(message, level='INFO'):
    return (level, bc.LOGGER, message)


def _http(instance, code, reason='OK'):
    return ('INFO', 'httpx', f'HTTP Request: POST http://fake-evolution:8080/message/sendText/{instance} '
                             f'"HTTP/1.1 {code} {reason}"')


INST_A, INST_B = bc.CHURCHES[A]['instance'], bc.CHURCHES[B]['instance']
FIRST = [_w('Broadcast worker started enabled=True tick=10s'),
         _w('Broadcast shutdown requested; transport already in progress'), _http(INST_A, 200),
         _w('Broadcast tick done reaped=0 materialized=0 actions=1'), _w('Broadcast worker stopped')]
RESTART = [_w('Broadcast worker started enabled=True tick=10s'), _http(INST_B, 200), _http(INST_A, 200),
           _w('Broadcast tick done reaped=0 materialized=0 actions=2'),
           _w('Broadcast tick done reaped=0 materialized=0 actions=0'),
           _w('Broadcast worker shutdown requested'), _w('Broadcast worker stopped')]


def test_log_events_of_first_run_and_restart():
    summary = bc.log_events(_log(*FIRST, *RESTART))
    runs = bc.split_runs(summary['events'])
    assert bc.clean_log(summary) and runs[0] == bc.first_run_events(INST_A, 200)
    assert bc.restart_events_ok(runs[1], [INST_A, INST_B], stopped=True)
    assert bc.restart_events_ok(runs[1][:-2], [INST_A, INST_B], stopped=False)
    variant = [*FIRST[:2], _http(INST_A, 500, 'Internal Server Error'),
               ('WARNING', 'pastorai.evolution', 'Evolution broadcast sendText returned HTTP 500'), *FIRST[3:]]
    summary = bc.log_events(_log(*variant))
    assert bc.clean_log(summary) and summary['events'] == bc.first_run_events(INST_A, 500)


@pytest.mark.parametrize('lines', [
    [*FIRST[:1], _w('Broadcast worker shutdown requested'), *FIRST[2:]],          # sem transporte em curso
    [FIRST[0], FIRST[2], FIRST[1], *FIRST[3:]],                                   # sinal depois da resposta
    [*FIRST[:3], _http(INST_B, 200), *FIRST[3:]],                                 # segundo envio após o sinal
    [*FIRST[:3], _w('Broadcast tick done reaped=0 materialized=0 actions=2'), FIRST[4]],
    [*FIRST, _w('Broadcast worker tick failed', 'ERROR')],
    [*FIRST, _w('Broadcast dispatch paused: heartbeat unavailable', 'ERROR')],
    [*FIRST, ('WARNING', 'pastorai.evolution', 'Evolution broadcast sendText has ambiguous outcome: ReadTimeout')],
])
def test_first_run_log_rejects_other_shapes(lines):
    summary = bc.log_events(_log(*lines))
    assert summary['events'] != bc.first_run_events(INST_A, 200) or not bc.clean_log(summary)


def test_unparsed_output_makes_log_unclean():
    assert not bc.clean_log(bc.log_events(_log(*FIRST) + 'Traceback (most recent call last):\n'))


@pytest.mark.parametrize('events', [
    ['started', 'http:%s:200' % INST_A, 'http:%s:200' % INST_A, 'tick:0:0:2', 'tick:0:0:0', 'shutdown', 'stopped'],
    ['started', 'http:%s:200' % INST_A, 'http:%s:200' % INST_B, 'tick:1:0:2', 'tick:0:0:0', 'shutdown', 'stopped'],
    ['started', 'http:%s:200' % INST_A, 'http:%s:200' % INST_B, 'tick:0:0:2', 'shutdown', 'stopped'],
    ['started', 'http:%s:200' % INST_A, 'http:%s:200' % INST_B, 'tick:0:0:2', 'tick:0:0:0', 'shutdown-inflight',
     'stopped'],
    ['started', 'http:%s:200' % INST_A, 'http:%s:200' % INST_B, 'tick:0:0:2', 'tick:0:0:0', 'shutdown',
     'tick:0:0:1', 'stopped'],
])
def test_restart_log_rejects_resend_reaper_or_no_idle_tick(events):
    assert not bc.restart_events_ok(events, [INST_A, INST_B], stopped=True)


# -- roteiro com mundo falso -----------------------------------------------
class World(bc.BroadcastActiveRehearsal):
    """Substitui só as primitivas de Docker/SQL/Redis; o roteiro ``rehearse`` é o real."""

    def __init__(self, held_status=200, phone=A1, **faults):
        super().__init__(legacy_image=LEGACY, redis_image=REDIS, postgres_image=PG, files=FILES,
                         baseline=dict(BASELINE), held_status=held_status, runner=self._no_docker,
                         sleep=self._sleep)
        self.faults, self.events, self.now, self.target = faults, [], 0.0, phone
        self.signalled = self.released = self.exited = self.restarted = self.final = False
        self.clock = self._tick

    def _no_docker(self, argv):
        raise AssertionError(argv)

    def _tick(self):
        self.now += 0.05
        return self.now

    def _sleep(self, seconds):
        self.now += min(seconds, 1)

    def fault(self, name):
        return self.faults.get(name) and self.signalled and not self.released

    # primitivas
    def preflight(self):
        self.events.append('preflight')

    def create_support(self):
        self.phase = 'running'

    def apply_baseline(self):
        self.events.append('baseline')

    def seed(self):
        self.seeded, self.before = copy.deepcopy(SEED), dict(pessoas='d')
        self.observed['ledger_shape'] = dict(seed=bc.ledger_shape(self.seeded))

    def start_fake(self):
        self.ids[bc.FAKE] = 'fake-id'

    def start_worker(self):
        self.ids[self.role] = 'worker-id'
        self.events.append('start')

    def new_execution(self):
        pass

    def running(self):
        return not self.exited and not self.fault('dies')

    def check_worker(self, *, running, extra=()):
        assert running == (not self.exited)

    def ledger(self):
        if self.final or self.restarted:
            return _drained(self.target, self.held_status)
        if self.released:
            if self.faults.get('not_committed'):
                return _held(self.target)
            if self.faults.get('extra_broadcast'):
                return _with_extra(_stopped(self.target, self.held_status), 'broadcasts', True)
            if self.faults.get('next_sent'):
                ledger = _stopped(self.target, self.held_status)
                _rows(ledger, B1)['row'].update(status='aceito', tentativas=1)
                return ledger
            return _stopped(self.target, self.held_status)
        ledger = _held(self.target)
        if self.fault('ledger_change'):
            _rows(ledger, A2)['row'].update(status='em_envio')
        return ledger

    def digest(self):
        return dict(self.before)

    def requests(self):
        held = [_request(self.target)]
        if self.restarted or self.final:
            pending = [_request(p) for p in bc.PHONES if p != self.target]
            if self.faults.get('resend'):
                pending[0] = _request(self.target)
            return held + pending
        if self.fault('second_request') or (self.released and self.faults.get('late_request')):
            return held + [_request(B1)]
        return held

    def responses(self):
        if not self.released:
            return []
        out = [dict(seq=1, status=self.held_status, held_ms=4400)]
        return out + ([dict(seq=2, status=200, held_ms=1), dict(seq=3, status=200, held_ms=1)]
                      if self.restarted or self.final else [])

    def rejected(self):
        return False

    def heartbeat(self):
        if self.exited:
            return 'stopped'
        return 'ready' if self.restarted else 'running'

    def fake_keys(self):
        return set(bc.FAKE_KEYS)

    def redis(self, *args):
        if args == ('GET', bc.HELD):
            return '55' + self.target
        if args[:2] == ('SET', bc.RELEASE):
            assert args[2] == str(self.held_status)
            self.released = True
            self.events.append('release')
            return 'OK'
        raise AssertionError(args)

    def docker(self, *args):
        if args == ('kill', '--signal', 'SIGTERM', 'worker-id'):
            self.signalled = True
            self.events.append('sigterm' if not self.restarted else 'idle-sigterm')
            if not self.restarted:
                self.now += bc.RELEASE_BUDGET_S if self.faults.get('slow') else self.faults.get('kill_delay', 0)
            return ''
        if args == ('start', 'worker-id'):
            assert self.exited
            self.exited, self.restarted = False, True
            self.events.append('restart')
            return ''
        raise AssertionError(args)

    def _await_exit(self, role, grace_s):
        assert role == bc.ROLE and (self.released or self.restarted)
        self.exited = True
        if self.restarted:
            self.final = True
        else:
            self.now += self.faults.get('exit_delay', 0)
        self.events.append('exit')

    def worker_logs(self):
        first = FIRST if not self.faults.get('no_inflight_log') else [FIRST[0]]
        if not self.signalled:
            return _log(FIRST[0])
        if not self.released:
            return _log(*first[:2])
        if not self.restarted:
            return _log(*FIRST)
        lines = RESTART[:4] if self.faults.get('no_idle_tick') else RESTART
        return _log(*FIRST, *(lines if self.final else lines[:-2]))


def test_script_holds_signals_then_releases_and_proves_no_second_send():
    world = World()
    bc.rehearse(world)
    assert world.events == ['preflight', 'baseline', 'start', 'sigterm', 'release', 'exit', 'restart',
                            'idle-sigterm', 'exit']
    assert world.checks[-1] == 'idle-sigterm-exit-0-heartbeat-stopped-no-further-request'
    assert world.observed['held_church'] == 'A' and world.timings['held_observed_to_release_s'] < bc.RELEASE_BUDGET_S
    assert world.timings['sigterm_command_to_exit_s'] < bc.COMPOSE_GRACE_S
    assert sorted(world.observed['ledger_shape']) == ['drained', 'final', 'held', 'seed', 'stopped']


@pytest.mark.parametrize('fault, code', [
    ('dies', 'worker-exited-while-held'),
    ('second_request', 'second-request-while-held'),
    ('ledger_change', 'ledger-changed-while-held'),
    ('no_inflight_log', 'transport-in-progress-not-logged'),
    ('slow', 'hold-too-long'),
])
def test_script_never_releases_when_the_held_state_is_not_proven(fault, code):
    world = World(**{fault: True})
    with pytest.raises(containment.Refused, match=code):
        bc.rehearse(world)
    assert 'sigterm' in world.events and 'release' not in world.events and not world.exited


@pytest.mark.parametrize('fault, code', [
    ('not_committed', 'result-state'),
    ('extra_broadcast', 'result-state'),
    ('next_sent', 'result-state'),
    ('late_request', 'transport-after-release'),
    ('resend', 'restart-transport'),
    ('no_idle_tick', 'drain-timeout'),
])
def test_script_refuses_wrong_outcome_after_release(fault, code):
    world = World(**{fault: True})
    with pytest.raises(containment.Refused, match=code):
        bc.rehearse(world)
    assert world.events[3:5] == ['sigterm', 'release']


def test_total_sigterm_to_exit_refused_even_when_each_partial_guard_fits():
    world = World(kill_delay=4, exit_delay=3)
    with pytest.raises(containment.Refused, match='sigterm-to-exit-over-compose-grace'):
        bc.rehearse(world)
    assert world.events[3:6] == ['sigterm', 'release', 'exit']
    assert world.timings['held_observed_to_release_s'] < bc.RELEASE_BUDGET_S
    assert world.timings['exit_after_release_s'] < bc.TICK_S
    assert world.timings['sigterm_command_to_exit_s'] >= bc.COMPOSE_GRACE_S


def test_variant_500_requires_unknown_and_no_resend():
    world = World(held_status=500)
    world.worker_logs = lambda: _log(*FIRST)  # resposta 200 no log para quem esperava 500
    with pytest.raises(containment.Refused, match='worker-log'):
        bc.rehearse(world)


def test_report_is_written_with_production_ready_false_on_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, 'legacy_sources', lambda repo: {k: v for k, v in FILES.items()
                                                             if k != 'app/services/evolution.py'})
    monkeypatch.setattr(bc, 'select_baseline', lambda repo: dict(BASELINE))
    report = tmp_path / 'report.json'
    assert bc.main(['run', '--repo', str(tmp_path), '--held-status', '500', '--report', str(report)]) == 1
    data = json.loads(report.read_text())
    assert data['status'] == 'refused' and data['reason'] == 'source-incomplete' and data['held_status'] == 500
    assert data['production_ready'] is False and data['legacy_sha'] == bc.LEGACY_SHA
