#!/usr/bin/env python3
"""Ensaio sintético LOCAL: SIGTERM com envio ATIVO do broadcast-worker legado real.

``run --repo R --report P [--held-status 200|500] [--legacy-image/--redis-image/--postgres-image sha256:...]``

Reusa ``rehearse_legacy_queue_active`` (fonte Git exata de ``07a3f4d``, runtime
do lock, guarda de Docker local, ledger, limpeza por posse, Redis e Postgres
efêmeros em rede ``--internal`` sem portas/montagens, baseline de 78 migrations
pelo ``cmd_apply`` ATUAL de ``migrate.py``). O PID 1 é
``python -m app.workers.broadcast_worker`` sem patch nem mock (``--init=false``
conferido como ``HostConfig.Init`` ``False``), com ``ALLOW_REAL_SENDS`` e
``BROADCAST_ASYNC_ENABLED`` abertos SÓ neste container sintético, Evolution em
``http://fake-evolution:8080`` e chave pública fictícia. Lease (120 s), intervalo
de envio (1 s), tentativas e timeout HTTP (15 s) ficam nos defaults legados.

A única peça falsa é a Evolution: container da própria imagem legada, só
stdlib ``http.server`` + ``redis``, na mesma rede interna. Aceita apenas
``POST /message/sendText/<instância semeada>`` com a chave e corpo esperados
(o resto é registrado como recusa), grava cada requisição no Redis ANTES de
responder e retém a primeira até o ensaio liberar com 200 (ou 500).

Seed: duas igrejas fictícias com conexão ``online``; a audiência é resolvida
por ``resolve_recipient_snapshot`` numa sessão ``mark_tenant_scoped`` e o envio
imediato é materializado por ``materialize_immediate_broadcast`` legado (3
entregas ``pendente``: duas na igreja A, uma na B). Sem router nem API.

Prova: a falsa registra e retém a 1ª requisição, observada ANTES do sinal; a
entrega retida é identificada pelo número recebido (não pela ordem de UUID) e
está ``em_envio``, ``tentativas=1``, lease de 120 s vivo e ``claim_por`` do PID
1; as outras duas seguem idênticas ao seed. SIGTERM real (``docker kill``):
log legado de transporte em andamento, processo vivo, uma única requisição e
banco inalterado durante a janela. Liberação: saída 0 com o total medido do
comando SIGTERM até a saída confirmada abaixo de 10 s (grace padrão do Docker;
limite superior do trecho observado, não prova de ``docker stop``), resultado
verdadeiro commitado pelo próprio worker (``aceito``; na variante 500,
``desconhecido``/``http_500``), demais entregas intactas, heartbeat
``stopped``. ``docker start`` do MESMO container: nova execução drena
exatamente as duas pendentes, sem repetir a retida; ocorrências finalizadas,
reaper 0, tick ocioso seguinte sem envio e SIGTERM ocioso com saída 0. Em
todas as fases o ledger tem exatamente 2 broadcasts, 2 execuções e 3
entregas, com chaves únicas e os IDs do seed (conferido antes de mapear).

O ``stop()`` legado não espera o HTTP (``RLock`` reentrante na própria thread)
e há janela entre a checagem de parada e o POST: o ensaio prova que nenhum
SEGUNDO envio ocorre após o sinal, não que nenhuma requisição possa começar
depois dele. ``production_ready=false``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from rehearse_legacy_containment import OWNER_LABEL, Refused
from rehearse_legacy_cron_active import LOG_LINE, docker_logs
from rehearse_legacy_queue import GRACE_S, LEGACY_SHA, SURVIVE_S, legacy_sources, manifest, manifest_digest
from rehearse_legacy_queue_active import (
    ACTIVE_ENV, BOOTSTRAP_COUNTS, CUTOFF, DEFAULT_IMAGES, EMPTY_SQL, KNOWN_MISSING, ActiveRehearsal,
    bundle_args, select_baseline,
)

ROLE = 'broadcast-worker'
ENTRY = ['-m', 'app.workers.broadcast_worker']
FAKE = 'fake-evolution'
# Loop/gate, entrega e cliente Evolution vêm destes blobs; a fonte selecionada precisa contê-los.
REQUIRED = frozenset({'app/workers/broadcast_worker.py', 'app/services/broadcast_delivery.py',
                      'app/services/evolution.py', 'app/services/broadcast_health.py'})
HEARTBEAT = 'pastorai:broadcast-worker:heartbeat:v1'
TICK_S = 10
EVOLUTION_KEY = 'synthetic-public-not-a-secret-evolution'
# Gates abertos SÓ neste container; lease/intervalo/tentativas/timeout nos defaults do legado.
BROADCAST_ENV = {**ACTIVE_ENV, 'ALLOW_REAL_SENDS': 'true', 'BROADCAST_ASYNC_ENABLED': 'true',
                 'EVOLUTION_API_URL': f'http://{FAKE}:8080', 'EVOLUTION_API_KEY': EVOLUTION_KEY,
                 'BROADCAST_WORKER_TICK_SECONDS': str(TICK_S)}
LEASE_S = 120               # DEFAULT_DELIVERY_LEASE_SECONDS legado; conferido no banco
HTTP_TIMEOUT_S = 15         # httpx.Client(timeout=15.0) do EvolutionClient legado
COMPOSE_GRACE_S = 10        # sem stop_grace_period no compose legado
HEARTBEAT_TTL_S = 30        # max(30, tick * 3)
SEND_INTERVAL_S = 1         # DEFAULT_SEND_INTERVAL_MS / 1000
# -- dados sintéticos -------------------------------------------------------
TENANT_A = '00000000-0000-0000-0000-00000000ba0a'
TENANT_B = '00000000-0000-0000-0000-00000000ba0b'
CHURCHES = {TENANT_A: dict(label='A', instance='synthetic-broadcast-a', numero='00900000001',
                           text='Comunicado sintetico A', phones=('00900000101', '00900000102')),
            TENANT_B: dict(label='B', instance='synthetic-broadcast-b', numero='00900000002',
                           text='Comunicado sintetico B', phones=('00900000201',))}
PHONES = {phone: tenant for tenant, church in CHURCHES.items() for phone in church['phones']}
SEED_SQL = (
    f"insert into igrejas (id, nome) values ('{TENANT_A}', 'Igreja Sintetica Broadcast A'), "
    f"('{TENANT_B}', 'Igreja Sintetica Broadcast B');"
    "insert into whatsapp_connections (igreja_id, instance, numero, status) values "
    + ", ".join(f"('{t}', '{c['instance']}', '{c['numero']}', 'online')" for t, c in CHURCHES.items()) + ";"
    "insert into pessoas (igreja_id, nome, telefone, tipo, consentimento, optout) values "
    + ", ".join(f"('{t}', 'Pessoa Sintetica {p[-3:]}', '{p}', 'membro', true, false)"
                for p, t in sorted(PHONES.items())) + ";"
)
SEEDED_COUNTS = dict(BOOTSTRAP_COUNTS, igrejas=BOOTSTRAP_COUNTS['igrejas'] + 2,
                     pessoas=BOOTSTRAP_COUNTS['pessoas'] + 3, connections=BOOTSTRAP_COUNTS['connections'] + 2)
# -- Redis da Evolution falsa ---------------------------------------------
P = 'synthetic:evolution:'
REQUESTS, RESPONSES, REJECTED = P + 'requests', P + 'responses', P + 'rejected'
HELD, RELEASE, READY = P + 'held', P + 'release', P + 'ready'
FAKE_KEYS = frozenset({REQUESTS, RESPONSES, HELD, RELEASE, READY})
OUTCOMES = {200: ('aceito', None), 500: ('desconhecido', 'http_500')}
# -- prazos ---------------------------------------------------------------
HELD_S = 60                 # do start do container à requisição retida
HOLD_S = 3                  # janela observada com SIGTERM entregue e resposta retida
RELEASE_BUDGET_S = 8        # guarda parcial: retido observado -> liberação (< timeout HTTP 15 s < TTL 30 s)
# O total comando SIGTERM -> saída confirmada é medido à parte e recusado se >= COMPOSE_GRACE_S.
HELD_MS_MAX = 10_000        # tempo de retenção medido pela falsa, folga sob o timeout HTTP
OBSERVE_S = SEND_INTERVAL_S + TICK_S + 1
DRAIN_S = 60
NOT_PROVEN = [
    'requisicao-iniciada-apos-o-sinal (janela legada entre a checagem de parada e o POST; '
    'so nenhum SEGUNDO envio apos o sinal e provado)',
    'docker-stop-com-grace-vencido-ou-sigkill-durante-o-http (lease vencido, reaper, desconhecido no boot); '
    'o total comando SIGTERM->saida < 10 s medido aqui nao prova docker stop automatico, supervisor nem SLA',
    'ponto-exato-do-handler-durante-o-recv (PEP 475; log so observado antes da liberacao)',
    'broadcast-agendado-materializacao-e-claim-de-broadcast-durante-sigterm',
    'respostas-429-retry-after-e-caminhos-retentaveis',
    'multiplos-workers-e-cerca-entre-processos',
    'supervisor-restart-policy-e-reinicio-do-host',
    'queda-do-redis-ou-do-postgres',
    'router-api-e-autorizacao (seed pela funcao de dominio)',
    'papeis-de-login-e-timeouts-de-producao (login sintetico postgres + SET LOCAL ROLE)',
    'compatibilidade-pos-ddl (schema >= 20261015 e as quatro ausentes nao aplicados)',
    'evolution-real-credencial-e-entrega-ao-aparelho (Evolution falsa, aceito = HTTP 2xx)',
    'ausencia-de-trafego-externo-por-captura (inferida: rede --internal, falsa unica receptora e contagens)',
    'integridade-de-wheels-sitecustomize-e-pth (so nome/versao das distribuicoes conferidos)',
    'estado-atual-de-producao (leitura de 24/10 nao revalidada) e producao',
]

# -- Evolution falsa (imagem legada; stdlib + redis; nenhum import de app) ---
FAKE_EVOLUTION = r'''
import json, os, re, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import redis
apikey, instances, prefix = sys.argv[1], set(json.loads(sys.argv[2])), sys.argv[3]
client = redis.Redis.from_url(os.environ['REDIS_URL'], decode_responses=True)
PATH = re.compile(r'/message/sendText/([A-Za-z0-9-]+)')
HOLD_MAX_S = 60
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def reject(self, why):
        client.rpush(prefix + 'rejected', why)
        self.send_response(404)
        self.send_header('Content-Length', '0')
        self.end_headers()
    def do_GET(self):
        self.reject('method')
    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_GET
    def do_POST(self):
        found = PATH.fullmatch(self.path)
        length = int(self.headers.get('Content-Length') or 0)
        try:
            body = json.loads(self.rfile.read(length)) if 0 < length <= 65536 else None
        except ValueError:
            body = None
        if not found or found[1] not in instances:
            return self.reject('path')
        if self.headers.get('apikey') != apikey:
            return self.reject('apikey')
        if (not isinstance(body, dict) or set(body) != {'number', 'text'}
                or not re.fullmatch(r'55[0-9]{11}', str(body['number']))):
            return self.reject('body')
        received = time.monotonic()
        seq = client.rpush(prefix + 'requests', json.dumps(
            dict(instance=found[1], number=body['number'], text=body['text']), sort_keys=True))
        status = 200
        if seq == 1:
            client.set(prefix + 'held', body['number'])
            while (value := client.get(prefix + 'release')) not in ('200', '500'):
                if time.monotonic() - received > HOLD_MAX_S:
                    client.rpush(prefix + 'responses', json.dumps(dict(seq=seq, status=None)))
                    self.close_connection = True
                    return
                time.sleep(0.02)
            status = int(value)
        payload = json.dumps({'key': {'id': 'synthetic-%d' % seq}, 'status': 'PENDING'}).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        client.rpush(prefix + 'responses', json.dumps(
            dict(seq=seq, status=status, held_ms=round((time.monotonic() - received) * 1000)), sort_keys=True))
server = ThreadingHTTPServer(('0.0.0.0', 8080), Handler)
client.set(prefix + 'ready', '1')
server.serve_forever()
'''

# -- seed pela função de domínio legada (sem router) -------------------------
SEED_PROBE = r'''
import datetime as dt, json, sys, uuid
from sqlalchemy import select
from app.db.models import Broadcast, Celula, Pessoa
from app.db.session import get_session_factory
from app.db.tenant_session import mark_tenant_scoped
from app.services.broadcast_delivery import materialize_immediate_broadcast, resolve_recipient_snapshot
igreja, mensagem = uuid.UUID(sys.argv[1]), sys.argv[2]
session = get_session_factory()()
try:
    mark_tenant_scoped(session, igreja, source='synthetic-broadcast-seed')
    # Mesmas leituras do router: o escopo por igreja vem da RLS.
    people = session.execute(select(Pessoa).where(Pessoa.arquivada_em.is_(None))).scalars().all()
    leaders = set(session.execute(select(Celula.lider_id).where(
        Celula.ativo.is_(True), Celula.lider_id.is_not(None))).scalars().all())
    audience = resolve_recipient_snapshot(people, leaders, ['todos'])
    now = dt.datetime.now(dt.timezone.utc)
    broadcast = Broadcast(igreja_id=igreja, titulo='Comunicado sintetico', mensagem=mensagem, segmentos=['todos'],
                          modo='agora', repeticao='once', ignorados_optout=audience.ignored_optout,
                          proxima_execucao=now, alcance=audience.reach, status='agendado')
    session.add(broadcast)
    session.flush()
    execution = materialize_immediate_broadcast(session, broadcast, audience.recipients, now=now)
    session.refresh(broadcast)
    session.commit()
    print(json.dumps(dict(execucao=str(execution), phones=sorted(r.telefone for r in audience.recipients))))
finally:
    session.close()
'''

# -- SQL de observação (superusuário via socket do container próprio) ------
BROADCAST_COUNTS_SQL = ("select json_build_object('broadcasts', (select count(*) from broadcasts), "
                        "'execucoes', (select count(*) from broadcast_execucoes), "
                        "'entregas', (select count(*) from broadcast_entregas))")
LEDGER_SQL = (
    "select json_build_object("
    "'deliveries', (select coalesce(json_agg(json_build_object('row', row_to_json(e), "
    "'lease_live', e.lease_ate > now(), 'lease_s', extract(epoch from e.lease_ate - e.atualizado_em)) "
    "order by e.telefone), '[]') from broadcast_entregas e), "
    "'executions', (select coalesce(json_agg(json_build_object('row', row_to_json(x), "
    "'lease_live', x.lease_ate > now()) order by x.igreja_id), '[]') from broadcast_execucoes x), "
    "'broadcasts', (select coalesce(json_agg(row_to_json(b) order by b.igreja_id), '[]') from broadcasts b))"
)
LEDGER_TABLES = ('broadcasts', 'broadcast_execucoes', 'broadcast_entregas')
# md5 por tabela de public fora do ledger de broadcast; superusuário ignora RLS.
DIGEST_SQL = (
    "select coalesce(json_object_agg(c.relname, (xpath('/row/d/text()', query_to_xml(format("
    "'select md5(coalesce(string_agg(t::text, chr(10) order by t::text), %L)) as d from public.%I t', "
    "'', c.relname), false, true, '')))[1]::text order by c.relname), '{}') "
    "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
    "where n.nspname = 'public' and c.relkind = 'r' and c.relname not in ("
    + ", ".join(f"'{name}'" for name in LEDGER_TABLES) + ")"
)
CLAIM_ID = re.compile(r'broadcast-1-[0-9a-f]{8}')  # f"broadcast-{os.getpid()}-..." com o worker como PID 1


# -- avaliações puras -------------------------------------------------------
# Tabela do ledger -> (chave única por linha, chaves esperadas). Conferido ANTES de mapear por chave.
SHAPE = dict(broadcasts=('igreja_id', frozenset(CHURCHES)), executions=('igreja_id', frozenset(CHURCHES)),
             deliveries=('telefone', frozenset(PHONES)))


def _rows_of(ledger, table):
    return [item if table == 'broadcasts' else item['row'] for item in ledger[table]]


def ledger_shape(ledger, seed=None):
    """Por tabela: contagem, chaves exatas e únicas, IDs únicos e (com ``seed``) mesmo ID por chave."""
    shape = {}
    for table, (key, expected) in SHAPE.items():
        rows = _rows_of(ledger, table)
        keys, ids = [row.get(key) for row in rows], [row.get('id') for row in rows]
        found = dict(count=len(rows), keys_exact_unique=len(set(keys)) == len(keys) and set(keys) == expected,
                     ids_unique=len(set(ids)) == len(ids))
        if seed is not None:
            found['seed_ids'] = sorted(ids) == sorted(row.get('id') for row in _rows_of(seed, table)) and \
                {row.get(key): row.get('id') for row in rows} == {row.get(key): row.get('id')
                                                                  for row in _rows_of(seed, table)}
        shape[table] = found
    return shape


def shape_ok(ledger, seed=None):
    """Exatamente 2 broadcasts, 2 execuções e 3 entregas, chaves únicas e (com ``seed``) os IDs do seed."""
    return all(found['count'] == len(SHAPE[table][1]) and found['keys_exact_unique'] and found['ids_unique']
               and found.get('seed_ids', True) for table, found in ledger_shape(ledger, seed).items())


def _by_phone(ledger):
    return {item['row']['telefone']: item for item in ledger['deliveries']}


def _by_tenant(items, row=True):
    return {(item['row'] if row else item)['igreja_id']: item for item in items}


def _same_except(row, seed, changed):
    return {k: v for k, v in row.items() if k not in changed} == {k: v for k, v in seed.items() if k not in changed}


def seeded_ok(ledger):
    """Dois envios imediatos materializados, um por igreja, e 3 entregas ``pendente`` exatas."""
    if not shape_ok(ledger):
        return False
    broadcasts = _by_tenant(ledger['broadcasts'], row=False)
    executions = _by_tenant(ledger['executions'])
    deliveries = _by_phone(ledger)
    if set(broadcasts) != set(CHURCHES) or set(executions) != set(CHURCHES) or set(deliveries) != set(PHONES):
        return False
    for tenant, church in CHURCHES.items():
        b, x = broadcasts[tenant], executions[tenant]['row']
        if (b['status'] != 'agendado' or b['modo'] != 'agora' or b['proxima_execucao'] is not None
                or b['claim_ate'] is not None or b['claim_por'] is not None or b['segmentos'] != ['todos']
                or b['mensagem'] != church['text'] or b['alcance'] != len(church['phones'])):
            return False
        if (x['broadcast_id'] != b['id'] or x['seq'] != 1 or executions[tenant]['lease_live'] is not None
                or any(x[k] is not None for k in ('iniciada_em', 'finalizada_em', 'lease_ate', 'claim_por'))):
            return False
    for phone, item in deliveries.items():
        row = item['row']
        if (row['igreja_id'] != PHONES[phone] or row['execucao_id'] != executions[PHONES[phone]]['row']['id']
                or row['pessoa_id'] is None or row['status'] != 'pendente' or row['tentativas'] != 0
                or row['retry_budget_used'] != 0 or item['lease_live'] is not None
                or any(row[k] is not None for k in ('lease_ate', 'next_attempt_at', 'claim_por', 'ultimo_erro_classe'))):
            return False
    return True


def held_identity(requests):
    """(telefone canônico, igreja) da requisição retida, conferindo instância e texto da própria igreja."""
    if len(requests) != 1:
        return None
    request = requests[0]
    number = str(request.get('number') or '')
    phone = number[2:] if number.startswith('55') else ''
    tenant = PHONES.get(phone)
    if tenant is None or request != dict(instance=CHURCHES[tenant]['instance'], number=number,
                                          text=CHURCHES[tenant]['text']):
        return None
    return phone, tenant


def held_claim(ledger, seed, phone):
    """``claim_por`` se só a entrega retida está ``em_envio`` (tentativa 1, lease de 120 s vivo); senão None."""
    if not shape_ok(ledger, seed):
        return None
    rows, seeded = _by_phone(ledger), _by_phone(seed)
    held = rows.get(phone)
    if set(rows) != set(seeded) or held is None:
        return None
    row = held['row']
    claim = row['claim_por'] or ''
    if not (row['status'] == 'em_envio' and row['tentativas'] == 1 and row['retry_budget_used'] == 0
            and CLAIM_ID.fullmatch(claim) and held['lease_live'] is True and held['lease_s'] == LEASE_S
            and row['next_attempt_at'] is None and row['ultimo_erro_classe'] is None
            and _same_except(row, seeded[phone]['row'], {'status', 'tentativas', 'lease_ate', 'claim_por',
                                                           'atualizado_em'})):
        return None
    if any(rows[p] != seeded[p] for p in rows if p != phone):
        return None
    tenant = PHONES[phone]
    executions, seeded_x = _by_tenant(ledger['executions']), _by_tenant(seed['executions'])
    x = executions[tenant]
    if not (x['row']['iniciada_em'] and x['row']['finalizada_em'] is None and x['lease_live'] is True
            and x['row']['claim_por'] == claim
            and _same_except(x['row'], seeded_x[tenant]['row'], {'iniciada_em', 'lease_ate', 'claim_por'})):
        return None
    if any(executions[t] != seeded_x[t] for t in executions if t != tenant) or ledger['broadcasts'] != seed['broadcasts']:
        return None
    return claim


def stopped_ok(ledger, seed, phone, claim, held_status):
    """Resultado verdadeiro commitado só na retida; demais entregas idênticas ao seed."""
    if not shape_ok(ledger, seed):
        return False
    status, error = OUTCOMES[held_status]
    rows, seeded = _by_phone(ledger), _by_phone(seed)
    if set(rows) != set(seeded):
        return False
    held = rows[phone]
    row = held['row']
    if not (row['status'] == status and row['ultimo_erro_classe'] == error and row['tentativas'] == 1
            and row['retry_budget_used'] == 0 and held['lease_live'] is None
            and all(row[k] is None for k in ('lease_ate', 'next_attempt_at', 'claim_por'))
            and _same_except(row, seeded[phone]['row'], {'status', 'tentativas', 'ultimo_erro_classe',
                                                           'atualizado_em'})):
        return False
    if any(rows[p] != seeded[p] for p in rows if p != phone):
        return False
    tenant = PHONES[phone]
    executions, seeded_x = _by_tenant(ledger['executions']), _by_tenant(seed['executions'])
    broadcasts, seeded_b = _by_tenant(ledger['broadcasts'], row=False), _by_tenant(seed['broadcasts'], row=False)
    x = executions[tenant]['row']
    if len(CHURCHES[tenant]['phones']) > 1:  # ainda há pendência na igreja: ocorrência aberta, lease do worker
        if not (x['iniciada_em'] and x['finalizada_em'] is None and executions[tenant]['lease_live'] is True
                and x['claim_por'] == claim and broadcasts[tenant] == seeded_b[tenant]
                and _same_except(x, seeded_x[tenant]['row'], {'iniciada_em', 'lease_ate', 'claim_por'})):
            return False
    elif not (x['iniciada_em'] and x['finalizada_em'] and x['lease_ate'] is None and x['claim_por'] is None
              and broadcasts[tenant]['status'] == 'enviado'
              and _same_except(x, seeded_x[tenant]['row'], {'iniciada_em', 'finalizada_em'})
              and _same_except(broadcasts[tenant], seeded_b[tenant], {'status'})):
        return False
    return all(executions[t] == seeded_x[t] and broadcasts[t] == seeded_b[t] for t in CHURCHES if t != tenant)


def drained_ok(ledger, seed, stopped, phone):
    """Retida byte-idêntica ao fim da 1ª execução; as duas pendentes ``aceito`` em 1 tentativa; tudo finalizado."""
    if not (shape_ok(ledger, seed) and shape_ok(stopped, seed)):
        return False
    rows, seeded, before = _by_phone(ledger), _by_phone(seed), _by_phone(stopped)
    if set(rows) != set(seeded) or rows[phone] != before[phone]:
        return False
    for p in rows:
        if p == phone:
            continue
        row = rows[p]['row']
        if not (row['status'] == 'aceito' and row['tentativas'] == 1 and row['retry_budget_used'] == 0
                and rows[p]['lease_live'] is None
                and all(row[k] is None for k in ('lease_ate', 'next_attempt_at', 'claim_por', 'ultimo_erro_classe'))
                and _same_except(row, seeded[p]['row'], {'status', 'tentativas', 'atualizado_em'})):
            return False
    seeded_b = _by_tenant(seed['broadcasts'], row=False)
    for tenant, b in _by_tenant(ledger['broadcasts'], row=False).items():
        if b['status'] != 'enviado' or not _same_except(b, seeded_b[tenant], {'status'}):
            return False
    return all(x['row']['iniciada_em'] and x['row']['finalizada_em'] and x['row']['lease_ate'] is None
               and x['row']['claim_por'] is None for x in ledger['executions']) and len(ledger['executions']) == 2


def restart_requests_ok(requests, phone):
    """Exatamente +2 requisições, números distintos = as duas pendentes; a retida nunca repetida."""
    if len(requests) != 3 or held_identity(requests[:1]) is None:
        return False
    expected = {'55' + p: dict(instance=CHURCHES[t]['instance'], number='55' + p, text=CHURCHES[t]['text'])
                for p, t in PHONES.items() if p != phone}
    later = requests[1:]
    return sorted(r['number'] for r in later) == sorted(expected) and all(r == expected[r['number']] for r in later)


def responses_ok(responses, statuses):
    """Uma resposta por requisição, na ordem; a retida dentro da folga sob o timeout HTTP."""
    return (len(responses) == len(statuses)
            and all(r.get('seq') == i and r.get('status') == s for i, (r, s) in enumerate(zip(responses, statuses), 1))
            and isinstance(responses[0].get('held_ms'), int) and responses[0]['held_ms'] < HELD_MS_MAX)


LOGGER = 'pastorai.broadcast_worker'
TICK_DONE = re.compile(r'Broadcast tick done reaped=(\d+) materialized=(\d+) actions=(\d+)')
HTTP_LINE = re.compile(r'HTTP Request: POST http://fake-evolution:8080/message/sendText/([A-Za-z0-9-]+) '
                       r'"HTTP/1\.[01] (\d{3}) [^"]*"')
TOKENS = {('INFO', LOGGER, f'Broadcast worker started enabled=True tick={TICK_S}s'): 'started',
          ('INFO', LOGGER, 'Broadcast shutdown requested; transport already in progress'): 'shutdown-inflight',
          ('INFO', LOGGER, 'Broadcast worker shutdown requested'): 'shutdown',
          ('INFO', LOGGER, 'Broadcast worker stopped'): 'stopped',
          ('WARNING', 'pastorai.evolution', 'Evolution broadcast sendText returned HTTP 500'): 'http-warning-500'}


def log_events(text):
    """Sequência de marcos do legado e contagens de incerteza; nenhum texto livre vai ao relatório."""
    events, problems, forbidden, unparsed = [], 0, 0, 0
    for line in text.splitlines():
        found = LOG_LINE.fullmatch(line)
        if not found:
            unparsed += bool(line.strip())  # traceback, warnings.warn, print: incerteza
            continue
        level, name, message = found.groups()
        token = TOKENS.get((level, name, message))
        if token is None and level == 'INFO' and name == LOGGER and (tick := TICK_DONE.fullmatch(message)):
            token = 'tick:' + ':'.join(tick.groups())
        if token is None and level == 'INFO' and name == 'httpx' and (http := HTTP_LINE.fullmatch(message)):
            token = f'http:{http[1]}:{http[2]}'
        if token:
            events.append(token)
            continue
        problems += level in ('WARNING', 'ERROR', 'CRITICAL')
        forbidden += name == LOGGER  # falha de tick, dispatch pausado, cerca/transporte, boot desligado
    return dict(events=events, problems=problems, forbidden=forbidden, unparsed=unparsed)


def first_run_events(instance, held_status):
    tail = ['http-warning-500'] if held_status == 500 else []
    return ['started', 'shutdown-inflight', f'http:{instance}:{held_status}', *tail, 'tick:0:0:1', 'stopped']


def restart_events_ok(events, pending_instances, *, stopped):
    """Boot, as duas pendentes num tick, ticks ociosos e (se ``stopped``) shutdown ocioso e stopped."""
    http = sorted(f'http:{i}:200' for i in pending_instances)
    if events[:1] != ['started'] or sorted(events[1:3]) != http or events[3:4] != ['tick:0:0:2']:
        return False
    rest = events[4:]
    idle = 0
    while idle < len(rest) and rest[idle] == 'tick:0:0:0':
        idle += 1
    if not idle:
        return False  # nenhum tick ocioso observado depois da drenagem
    tail = rest[idle:]
    if not stopped:
        return tail == []
    return tail in (['shutdown', 'stopped'], ['shutdown', 'tick:0:0:0', 'stopped'])


def split_runs(events):
    """Marcos de cada execução do mesmo container (``docker logs`` acumula as execuções)."""
    runs = []
    for event in events:
        if event == 'started' or not runs:
            runs.append([])
        runs[-1].append(event)
    return runs


def clean_log(summary):
    return not summary['problems'] and not summary['forbidden'] and not summary['unparsed']


# -- ensaio -----------------------------------------------------------------
class BroadcastActiveRehearsal(ActiveRehearsal):
    role, entry, worker_env = ROLE, ENTRY, BROADCAST_ENV

    def __init__(self, *, files, held_status=200, log_runner=docker_logs, **kwargs):
        if not REQUIRED <= set(files):
            raise Refused('source-incomplete')
        if held_status not in OUTCOMES:
            raise Refused('held-status')
        super().__init__(files=files, **kwargs)
        self.prefix = 'pastorai-synthetic-legacy-bcast-active-' + self.run_id[:12]
        self.held_status = held_status
        self.log_runner = log_runner
        self.observed: dict = {}
        self.started_at: list[str] = []

    def _legacy_argv(self, role, network, env):
        # ``init: true`` no daemon injetaria docker-init como PID 1 sem mudar Path/Args do inspect.
        argv = super()._legacy_argv(role, network, env)
        return [*argv[:-1], '--init=false', argv[-1]]

    # -- observação --------------------------------------------------------
    def ledger(self):
        return self.psql_json(LEDGER_SQL)

    def digest(self):
        return self.psql_json(DIGEST_SQL)

    def worker_logs(self):
        return self.log_runner(['docker', 'logs', self.ids[self.role]])

    def requests(self):
        return [json.loads(item) for item in self.redis('LRANGE', REQUESTS, '0', '-1').splitlines()]

    def responses(self):
        return [json.loads(item) for item in self.redis('LRANGE', RESPONSES, '0', '-1').splitlines()]

    def rejected(self):
        return self.redis('LLEN', REJECTED) != '0'

    def heartbeat(self):
        return self.redis('GET', HEARTBEAT)

    # -- seed --------------------------------------------------------------
    def seed(self):
        if self.psql_json(BROADCAST_COUNTS_SQL) != dict(broadcasts=0, execucoes=0, entregas=0):
            raise Refused('bootstrap-has-broadcasts')
        self.psql(SEED_SQL)  # só INSERT; o bootstrap é preservado
        if self.psql_json(EMPTY_SQL) != SEEDED_COUNTS:
            raise Refused('seed')
        for tenant, church in CHURCHES.items():
            out = json.loads(self.probe('seed', ['-c', SEED_PROBE, tenant, church['text']], 'seed-probe'))
            if out.get('phones') != sorted(church['phones']):
                raise Refused('seed-audience')  # RLS deixou passar outra igreja ou audiência errada
        self.seeded = self.ledger()
        self.observed['ledger_shape'] = dict(seed=ledger_shape(self.seeded))
        if not seeded_ok(self.seeded):
            raise Refused('seed')
        self.before = self.digest()
        self.checks.append('seed-two-fictitious-churches-online-legacy-materialize_immediate_broadcast-3-pending')

    # -- Evolution falsa ---------------------------------------------------
    def start_fake(self):
        argv = self._legacy_argv(FAKE, self.network, {'REDIS_URL': ACTIVE_ENV['REDIS_URL']})
        self.ids[FAKE] = self._record('containers', self.docker(
            *argv[:-1], '--network-alias', FAKE, '--name', f'{self.prefix}-{FAKE}', argv[-1],
            '-I', '-c', FAKE_EVOLUTION, EVOLUTION_KEY,
            json.dumps(sorted(c['instance'] for c in CHURCHES.values())), P))
        self._until(lambda: self.redis('GET', READY) == '1', 'fake-evolution-readiness')
        self._check_fake()
        if self.redis('EXISTS', REQUESTS, RESPONSES, REJECTED, HELD, RELEASE) != '0':
            raise Refused('fake-evolution-state')
        self.checks.append('fake-evolution-only-on-internal-network-no-ports-legacy-image-stdlib')

    def _check_fake(self):
        data = self.inspect(self.ids[FAKE])
        config, _ = self._check_common(data, FAKE, self.images['worker'])
        if data.get('Path') != 'python' or (data.get('Args') or [])[:3] != ['-I', '-c', FAKE_EVOLUTION]:
            raise Refused('entrypoint')
        if not (data.get('State') or {}).get('Running'):
            raise Refused('fake-evolution-exited')

    def check_worker(self, *, running, extra=()):
        super().check_worker(running=running, extra={self.ids[FAKE], *extra})
        self._check_fake()
        # ``None`` = default do daemon (pode ser init); só ``False`` explícito garante o worker como PID 1.
        if (self.inspect(self.ids[self.role]).get('HostConfig') or {}).get('Init') is not False:
            raise Refused('pid1-init')

    def fake_keys(self):
        return self.keys() - {HEARTBEAT}

    # -- fases -------------------------------------------------------------
    def wait_held(self, started):
        """Primeira requisição retida pela falsa, observada de fora, antes de qualquer sinal."""
        while not self.redis('GET', HELD):
            if not self.running():
                raise Refused('worker-exited-before-transport')
            if self.rejected() or len(self.requests()) > 1:
                raise Refused('unexpected-transport')
            if self.clock() - started >= HELD_S:
                raise Refused('transport-not-observed')
            self.sleep(0.2)
        observed = self.clock()
        identity = held_identity(self.requests())
        if identity is None or self.redis('GET', HELD) != '55' + identity[0]:
            raise Refused('held-request')
        return identity, observed

    def assert_holding(self, snapshot, claim):
        """Vivo, uma requisição sem resposta, ledger igual ao pré-sinal, heartbeat do tick."""
        if not self.running():
            raise Refused('worker-exited-while-held')
        if len(self.requests()) != 1 or self.responses() or self.rejected():
            raise Refused('second-request-while-held')
        ledger = self.ledger()
        if ledger != snapshot or held_claim(ledger, self.seeded, self.phone) != claim:
            raise Refused('ledger-changed-while-held')
        if self.heartbeat() != 'running':
            raise Refused('heartbeat-while-held')

    def new_execution(self):
        started = (self.inspect(self.ids[self.role]).get('State') or {}).get('StartedAt')
        if not started or started in self.started_at:
            raise Refused('not-a-new-execution')
        self.started_at.append(started)


def rehearse(r):
    r.preflight()
    r.create_support()
    r.apply_baseline()
    r.seed()
    r.start_fake()

    started = r.clock()
    r.start_worker()
    r.new_execution()
    (r.phone, tenant), observed = r.wait_held(started)
    instance = CHURCHES[tenant]['instance']
    r.observed.update(held_church=CHURCHES[tenant]['label'], held_status=r.held_status)
    r.timings['held_after_start_s'] = round(observed - started, 3)
    snapshot = r.ledger()
    r.observed['ledger_shape']['held'] = ledger_shape(snapshot, r.seeded)
    claim = held_claim(snapshot, r.seeded, r.phone)
    if claim is None:
        raise Refused('held-delivery-state')
    early = log_events(r.worker_logs())
    if early['events'] != ['started'] or not clean_log(early):
        raise Refused('worker-log-before-sigterm')
    r.check_worker(running=True)
    r.assert_holding(snapshot, claim)
    r.checks += ['real-broadcast-pid1-gates-open-only-in-synthetic-container-first-request-held-before-sigterm',
                 'held-delivery-identified-by-received-number-em_envio-attempt-1-lease-120s-claim-pid1',
                 'other-two-deliveries-identical-to-seed-before-signal']

    stop_command = r.clock()  # antes do comando: inclui qualquer latência até a entrega do sinal
    r.docker('kill', '--signal', 'SIGTERM', r.ids[ROLE])
    signalled = r.clock()
    inflight_logged = False
    while r.clock() - signalled < HOLD_S or not inflight_logged:
        r.assert_holding(snapshot, claim)
        summary = log_events(r.worker_logs())
        if summary['events'] not in (['started'], ['started', 'shutdown-inflight']) or not clean_log(summary):
            raise Refused('worker-log-while-held')
        inflight_logged = summary['events'] == ['started', 'shutdown-inflight']
        if r.clock() - observed >= RELEASE_BUDGET_S:
            break
        r.sleep(0.2)
    if not inflight_logged:
        raise Refused('transport-in-progress-not-logged')
    r.assert_holding(snapshot, claim)
    r.check_worker(running=True)
    if r.digest() != r.before:
        raise Refused('database-changed-while-held')
    # Medida depois do último check, sem arredondar na decisão: nada além do SET separa a recusa da liberação.
    held = r.clock() - observed
    r.timings['held_observed_to_release_s'] = round(held, 3)
    if held >= RELEASE_BUDGET_S:
        raise Refused('hold-too-long')
    r.redis('SET', RELEASE, str(r.held_status))
    released = r.clock()
    r.checks.append('sigterm-transport-in-progress-logged-worker-alive-one-request-ledger-unchanged')

    r._await_exit(ROLE, GRACE_S)
    confirmed = r.clock()
    exited = confirmed - released
    r.timings['exit_after_release_s'] = round(exited, 3)
    # Limite superior conservador do trecho observado (inclui o polling da saída); não é docker stop.
    total = confirmed - stop_command
    r.timings['sigterm_command_to_exit_s'] = round(total, 3)
    if exited >= TICK_S:
        raise Refused('exit-not-before-next-tick')
    if total >= COMPOSE_GRACE_S:
        raise Refused('sigterm-to-exit-over-compose-grace')
    responses = r.responses()
    r.timings['fake_held_ms'] = responses[0].get('held_ms') if responses else None
    if not responses_ok(responses, [r.held_status]) or len(r.requests()) != 1 or r.rejected():
        raise Refused('transport-after-release')
    stopped = r.ledger()
    r.observed['ledger_shape']['stopped'] = ledger_shape(stopped, r.seeded)
    if not stopped_ok(stopped, r.seeded, r.phone, claim, r.held_status):
        raise Refused('result-state')
    if r.heartbeat() != 'stopped' or r.fake_keys() != FAKE_KEYS:
        raise Refused('heartbeat-or-redis-state')
    r.check_worker(running=False)
    if r.digest() != r.before:
        raise Refused('unexpected-database-effects')
    logs = r.worker_logs()
    first = r.observed['log_first_run'] = log_events(logs)
    expected_first = first_run_events(instance, r.held_status)
    if first['events'] != expected_first or not clean_log(first):
        raise Refused('worker-log')
    status = OUTCOMES[r.held_status][0]
    r.checks += [f'released-{r.held_status}-sigterm-command-to-exit-under-{COMPOSE_GRACE_S}s-exit-0-heartbeat-stopped',
                 f'held-result-{status}-committed-by-worker-lease-and-claim-cleared',
                 'other-two-deliveries-still-identical-to-seed-pending-attempts-0',
                 'no-second-request-after-sigterm-rest-of-database-unchanged']

    r.sleep(OBSERVE_S)  # > intervalo de envio + tick: o processo já saiu, nada pode surgir
    if (r.worker_logs() != logs or r.ledger() != stopped or len(r.requests()) != 1
            or r.heartbeat() != 'stopped' or r.digest() != r.before):
        raise Refused('activity-after-exit')
    r.check_worker(running=False)
    r.checks.append('state-stable-after-exit-longer-than-send-interval-plus-tick')

    r.docker('start', r.ids[ROLE])
    r.new_execution()
    pending = [CHURCHES[PHONES[p]]['instance'] for p in PHONES if p != r.phone]
    restarted = r.clock()
    while True:
        if not r.running():
            raise Refused('worker-exited-during-drain')
        if r.rejected() or len(r.requests()) > 3:
            raise Refused('unexpected-transport')
        summary = log_events(r.worker_logs())
        runs = split_runs(summary['events'])
        if runs[:1] != [expected_first] or len(runs) > 2:
            raise Refused('worker-log-after-restart')
        if len(runs) == 2 and runs[1][4:5] == ['tick:0:0:0']:
            break
        if r.clock() - restarted >= DRAIN_S:
            raise Refused('drain-timeout')
        r.sleep(0.5)
    r.timings['drained_after_restart_s'] = round(r.clock() - restarted, 3)
    if not restart_events_ok(runs[1], pending, stopped=False) or not clean_log(summary):
        raise Refused('worker-log-after-restart')
    if not restart_requests_ok(r.requests(), r.phone) or not responses_ok(r.responses(), [r.held_status, 200, 200]):
        raise Refused('restart-transport')
    drained = r.ledger()
    r.observed['ledger_shape']['drained'] = ledger_shape(drained, r.seeded)
    if not drained_ok(drained, r.seeded, stopped, r.phone):
        raise Refused('drain-state')
    if r.heartbeat() not in ('running', 'ready') or r.digest() != r.before:
        raise Refused('restart-state')
    r.check_worker(running=True)
    r.checks += ['restart-same-container-new-execution-drained-exactly-two-pending-reaped-0',
                 f'held-delivery-never-resent-still-{status}-byte-identical',
                 'executions-finalized-broadcasts-enviado-next-tick-idle-without-request']

    stop_command = r.clock()
    r.docker('kill', '--signal', 'SIGTERM', r.ids[ROLE])
    r._await_exit(ROLE, GRACE_S)
    total = r.clock() - stop_command
    r.timings['idle_sigterm_command_to_exit_s'] = round(total, 3)
    if total >= COMPOSE_GRACE_S:
        raise Refused('idle-sigterm-to-exit-over-compose-grace')
    final = log_events(r.worker_logs())
    runs = split_runs(final['events'])
    r.observed['log_restart'] = dict(final, events=runs[1:])
    if (len(runs) != 2 or runs[0] != expected_first or not restart_events_ok(runs[1], pending, stopped=True)
            or not clean_log(final)):
        raise Refused('worker-log-final')
    final_ledger = r.ledger()
    r.observed['ledger_shape']['final'] = ledger_shape(final_ledger, r.seeded)
    if (r.heartbeat() != 'stopped' or r.fake_keys() != FAKE_KEYS or len(r.requests()) != 3
            or final_ledger != drained or r.digest() != r.before):
        raise Refused('final-state')
    r.check_worker(running=False)
    r.sleep(SURVIVE_S)
    if len(r.requests()) != 3 or r.ledger() != drained or r.heartbeat() != 'stopped':
        raise Refused('activity-after-final-exit')
    r.checks.append('idle-sigterm-exit-0-heartbeat-stopped-no-further-request')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    reh = sub.add_parser('run')
    reh.add_argument('--repo', type=Path, required=True)
    reh.add_argument('--legacy-image', default=DEFAULT_IMAGES['legacy'])
    reh.add_argument('--redis-image', default=DEFAULT_IMAGES['redis'])
    reh.add_argument('--postgres-image', default=DEFAULT_IMAGES['postgres'])
    reh.add_argument('--held-status', type=int, choices=sorted(OUTCOMES), default=200)
    reh.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    report = dict(kind='synthetic-legacy-broadcast-active-transport-rehearsal', status='fail', production_ready=False,
                  legacy_sha=LEGACY_SHA, entrypoint='python ' + ' '.join(ENTRY), held_status=args.held_status,
                  not_proven=NOT_PROVEN,
                  scope='broadcast-worker legado real com gates abertos so no container sintetico, Evolution falsa '
                        'na rede interna, Redis e Postgres efemeros; sem provedor real/producao',
                  images=dict(legacy=args.legacy_image, redis=args.redis_image, postgres=args.postgres_image),
                  expected=dict(seeded=SEEDED_COUNTS, lease_s=LEASE_S, http_timeout_s=HTTP_TIMEOUT_S,
                                compose_grace_s=COMPOSE_GRACE_S, heartbeat_ttl_s=HEARTBEAT_TTL_S,
                                release_budget_s=RELEASE_BUDGET_S, outcome=OUTCOMES[args.held_status][0]),
                  checks=[])
    rehearsal = None
    try:
        files = legacy_sources(args.repo)
        report['source'] = dict(files=len(files), manifest_sha256=manifest_digest(manifest(files)))
        baseline = select_baseline(args.repo)
        report['baseline'] = dict(cutoff=CUTOFF, active=baseline['active'], selected=len(baseline['selected']),
                                  excluded_known_missing=sorted(KNOWN_MISSING),
                                  first=baseline['selected'][0], last=baseline['selected'][-1],
                                  bundle_sha256=bundle_args(baseline)[0])
        rehearsal = BroadcastActiveRehearsal(legacy_image=args.legacy_image, redis_image=args.redis_image,
                                             postgres_image=args.postgres_image, files=files, baseline=baseline,
                                             held_status=args.held_status)
        rehearse(rehearsal)
        report.update(status='pass', reason=None)
    except Refused as exc:
        preflight = rehearsal is None or rehearsal.phase == 'preflight'
        report.update(status='refused' if preflight else 'fail', reason=str(exc))
    except KeyboardInterrupt:
        report['reason'] = 'interrupted'
    except OSError:
        report['reason'] = 'os-error'
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        report['reason'] = 'unexpected-output'
    finally:
        if rehearsal is not None:
            report.update(checks=rehearsal.checks, mismatch=rehearsal.mismatch, timings=rehearsal.timings,
                          migration=getattr(rehearsal, 'migration', None), observed=rehearsal.observed,
                          cleanup=rehearsal.cleanup())
            if report['cleanup']['status'] != 'clean' and report['status'] == 'pass':
                report.update(status='fail', reason='cleanup-incomplete')
        args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
