#!/usr/bin/env python3
"""Ensaio sintético LOCAL: SIGTERM durante tick ATIVO do cron-worker legado real.

``run --repo R --report P [--legacy-image/--redis-image/--postgres-image sha256:...]``

Reusa ``rehearse_legacy_queue_active`` (fonte Git exata de ``07a3f4d``, runtime
do lock, guarda de Docker local, ledger, limpeza por posse, Redis e Postgres
efêmeros em rede ``--internal`` sem portas/montagens, baseline de 78 migrations
pelo ``cmd_apply`` ATUAL de ``migrate.py`` com bootstrap oficial preservado).
O PID 1 do worker é ``python -m app.workers.cron_worker`` sem patch nem mock,
gates fechados, lista de piloto vazia, provedores em loopback morto e
``CRON_TICK_SECONDS=10``.

Barreira: o primeiro tick começa pela purga real de ``calendar_oauth_flows``
(``DELETE`` cross-tenant). Antes do worker subir, uma conexão de probe separada
segura ``SELECT ... FOR UPDATE`` só no fluxo fictício EXPIRADO; o fluxo
fictício VÁLIDO fica livre. O bloqueio é identificado em
``pg_stat_activity``/``pg_locks`` pelos IPs dos dois containers: o único
backend do worker executa o ``DELETE`` e espera ``transactionid`` exatamente
no xid do único backend do holder (``pg_blocking_pids``). Com o worker
bloqueado, SIGTERM; durante a janela observada o processo segue vivo, o
bloqueio é o mesmo e nenhuma linha do banco muda. Só então libera e prova:
remoção única do expirado, válido byte-idêntico, tick concluído (log real:
``sla=0, crons=0, plan_changes=0, oauth_flows_purged=1``), shutdown pedido
antes do fim do tick, heartbeat ``stopped``, saída 0, nenhum segundo tick e o
restante do banco inalterado por digest.

O ``stop()`` legado só faz ``_running=False``: o tick em curso continua (SLA,
crons e billing) depois do sinal. Contenção só vale após a saída; nada aqui
alega o contrário. Não prova supervisor/restart do host, produção, pós-DDL nem
outros serviços: ``production_ready=false``.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from rehearse_legacy_containment import Refused
from rehearse_legacy_queue import GRACE_S, LEGACY_SHA, SURVIVE_S, legacy_sources, manifest, manifest_digest
from rehearse_legacy_queue_active import (
    ACTIVE_ENV, BOOTSTRAP_COUNTS, CUTOFF, DEFAULT_IMAGES, DSN, EMPTY_SQL, KNOWN_MISSING, PG_DB, PROBE_S,
    ActiveRehearsal, bundle_args, select_baseline,
)

ROLE = 'cron-worker'
ENTRY = ['-m', 'app.workers.cron_worker']
# Purga e loop vêm destes blobs; a fonte selecionada precisa contê-los.
REQUIRED = frozenset({'app/workers/cron_worker.py', 'app/services/calendar_oauth_flows.py'})
HEARTBEAT = 'pastorai:cron-worker:heartbeat:v1'
CRON_TICK_S = 10        # mínimo do Settings legado (ge=10): um segundo tick exigiria >= 10 s de sono
CRON_ENV = {**ACTIVE_ENV, 'CRON_TICK_SECONDS': str(CRON_TICK_S)}
# -- dados sintéticos (fora do bootstrap 0005/0007) -------------------------
TENANT = '00000000-0000-0000-0000-00000000c001'
APP_USER = '00000000-0000-0000-0000-00000000c002'
EXPIRED = '00000000-0000-0000-0000-00000000c0e1'
VALID = '00000000-0000-0000-0000-00000000c0f1'
HELD = 'synthetic:cron:held'
RELEASE = 'synthetic:cron:release'
SEEDED_TABLES = frozenset({'igrejas', 'app_users'})  # além de calendar_oauth_flows, fora do digest
SEEDED_COUNTS = dict(BOOTSTRAP_COUNTS, igrejas=BOOTSTRAP_COUNTS['igrejas'] + 1)
# Nada para o resto do tick fazer: sem crons ativos, fila, consolidação ou troca de plano.
IDLE = dict(crons=0, work_queue_items=0, consolidacoes=0, plan_changes=0)
# -- prazos ---------------------------------------------------------------
BARRIER_S = 15          # do start do container ao bloqueio observado
HOLD_S = 3              # janela observada com SIGTERM entregue e row lock retido
PROGRESS_BUDGET_S = 20  # < 30 s de progress timeout do legado (heartbeat vira error e para o loop)
EXPECTED_LOG = dict(started=['Cron worker started (tick=%ds)' % CRON_TICK_S], shutdown=1,
                    ticks=[dict(sla=0, crons=0, plan_changes=0, oauth_flows_purged=1)], stopped=1,
                    shutdown_before_tick_done=True, problems=0, unparsed=0)
NOT_PROVEN = [
    'contencao-antes-da-saida (stop() legado so faz _running=False; SLA/crons/billing do tick seguem apos o sinal)',
    'sigterm-durante-sla-crons-ou-billing-com-trabalho-real (bootstrap e seed sem trabalho para essas fases)',
    'handler-python-durante-o-bloqueio (psycopg2 sincrono adia o handler ate o DELETE voltar; so observado)',
    'supervisor-restart-policy-e-reinicio-do-host',
    'papeis-de-login-e-timeouts-de-producao (login sintetico postgres, sem lock_timeout/statement_timeout)',
    'sigkill-ou-timeout-do-worker-real',
    'queda-do-redis-ou-do-postgres',
    'compatibilidade-pos-ddl (schema >= 20261015 e as quatro ausentes nao aplicados)',
    'outros-servicos (backend, queue-worker, broadcast-worker)',
    'efeitos-de-provedor (Evolution/Asaas/Brevo em loopback morto, gates fechados)',
    'integridade-de-wheels-sitecustomize-e-pth (so nome/versao das distribuicoes conferidos)',
    'producao',
]

# -- probe (imagem legada; nada montado do host, nenhum import de app) -----
HOLDER_PROBE = r'''
import os, sys, time
import psycopg2, redis
dsn, flow, held, release = sys.argv[1:5]
client = redis.Redis.from_url(os.environ['REDIS_URL'], decode_responses=True)
conn = psycopg2.connect(dsn)
cur = conn.cursor()
cur.execute('select id::text from calendar_oauth_flows where id = %s for update', (flow,))
locked = cur.fetchall()
cur.execute('select txid_current_if_assigned()::text')
xid = cur.fetchone()[0]
if locked != [(flow,)] or not xid:
    conn.rollback()
    print('not-locked')
    sys.exit(3)
client.set(held, xid, ex=300)
limit = time.monotonic() + 150
while client.get(release) != '1':
    if time.monotonic() > limit:
        conn.rollback()
        print('timeout')
        sys.exit(3)
    time.sleep(0.05)
conn.rollback()
conn.close()
print('released ' + xid)
'''

# -- SQL de observação (superusuário via socket do container próprio) ------
SEED_SQL = (
    f"insert into igrejas (id, nome) values ('{TENANT}', 'Igreja Sintetica Cron');"
    f"insert into app_users (id, igreja_id, nome, email) values "
    f"('{APP_USER}', '{TENANT}', 'Usuario Sintetico Cron', 'cron@example.invalid');"
    "insert into calendar_oauth_flows (id, state_hash, flow_secret_hash, igreja_id, app_user_id, "
    "return_origin, expires_at) values "
    f"('{EXPIRED}', repeat('1', 64), repeat('2', 64), '{TENANT}', '{APP_USER}', 'http://127.0.0.1:9', "
    "now() - interval '1 hour'), "
    f"('{VALID}', repeat('3', 64), repeat('4', 64), '{TENANT}', '{APP_USER}', 'http://127.0.0.1:9', "
    "now() + interval '6 hours');"
)
IDLE_SQL = ("select json_build_object('crons', (select count(*) from crons where ativo), "
            "'work_queue_items', (select count(*) from work_queue_items), "
            "'consolidacoes', (select count(*) from consolidacoes), "
            "'plan_changes', (select count(*) from billing_plan_change_operations))")
# Linhas inteiras (só dados fictícios); ``expired`` avaliado pelo relógio do banco.
FLOWS_SQL = ("select coalesce(json_agg(json_build_object('row', row_to_json(f), 'expired', f.expires_at <= now()) "
             "order by f.id), '[]') from calendar_oauth_flows f")
# md5 por tabela de public (exceto os fluxos); superusuário ignora RLS.
DIGEST_SQL = (
    "select coalesce(json_object_agg(c.relname, (xpath('/row/d/text()', query_to_xml(format("
    "'select md5(coalesce(string_agg(t::text, chr(10) order by t::text), %L)) as d from public.%I t', "
    "'', c.relname), false, true, '')))[1]::text order by c.relname), '{}') "
    "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
    "where n.nspname = 'public' and c.relkind = 'r' and c.relname <> 'calendar_oauth_flows'"
)
BOOTSTRAP_SQL = (
    "select json_build_object("
    f"'igrejas', (select md5(coalesce(json_agg(row_to_json(t) order by t.id)::text, '')) from igrejas t "
    f"where t.id <> '{TENANT}'), "
    f"'app_users', (select md5(coalesce(json_agg(row_to_json(t) order by t.id)::text, '')) from app_users t "
    f"where t.igreja_id is distinct from '{TENANT}'))"
)
BLOCK_SQL = (
    "select json_build_object("
    "'backends', (select coalesce(json_agg(json_build_object('pid', a.pid, 'addr', host(a.client_addr), "
    "'state', a.state, 'wait_type', a.wait_event_type, 'wait', a.wait_event, 'xid', a.backend_xid::text, "
    "'delete', a.query ilike 'delete from calendar_oauth_flows%', "
    "'blockers', to_json(pg_blocking_pids(a.pid))) order by a.pid), '[]') from pg_stat_activity a "
    f"where a.datname = '{PG_DB}' and a.backend_type = 'client backend' and a.pid <> pg_backend_pid()), "
    "'waits', (select coalesce(json_agg(json_build_object('pid', l.pid, 'locktype', l.locktype, "
    "'xid', l.transactionid::text, 'mode', l.mode) order by l.pid), '[]') from pg_locks l where not l.granted))"
)


# -- avaliações puras -------------------------------------------------------
def blocked_on_holder(snapshot, worker_ip, holder_ip, holder_xid):
    """Um backend por container; o do worker no DELETE, esperando só o xid do holder."""
    by_addr = {}
    for backend in snapshot.get('backends') or []:
        by_addr.setdefault(backend.get('addr'), []).append(backend)
    if set(by_addr) != {worker_ip, holder_ip} or any(len(found) != 1 for found in by_addr.values()):
        return False
    worker, holder = by_addr[worker_ip][0], by_addr[holder_ip][0]
    return (holder.get('state') == 'idle in transaction' and holder.get('xid') == holder_xid
            and holder.get('blockers') == []
            and worker.get('state') == 'active' and worker.get('wait_type') == 'Lock'
            and worker.get('wait') == 'transactionid' and worker.get('delete') is True
            and worker.get('blockers') == [holder.get('pid')]
            and snapshot.get('waits') == [dict(pid=worker.get('pid'), locktype='transactionid',
                                               xid=holder_xid, mode='ShareLock')])


def seeded_ok(flows):
    """Exatamente o expirado (não consumido) e o válido, ambos do tenant sintético."""
    rows = [flow.get('row') or {} for flow in flows]
    return ([row.get('id') for row in rows] == [EXPIRED, VALID]
            and [flow.get('expired') for flow in flows] == [True, False]
            and all(row.get('igreja_id') == TENANT and row.get('app_user_id') == APP_USER
                    and row.get('consumed_at') is None and row.get('finish_result') is None for row in rows))


def purged_ok(after, seeded):
    """Só o válido sobra, idêntico ao seed."""
    return len(seeded) == 2 and after == [seeded[1]]


def seed_touched_only(before, after):
    """Fora das tabelas semeadas, nenhuma tabela mudou nem surgiu/sumiu."""
    if set(before) != set(after) or not SEEDED_TABLES <= set(before):
        return False
    return all(before[name] == after[name] for name in before if name not in SEEDED_TABLES)


LOG_LINE = re.compile(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} (DEBUG|INFO|WARNING|ERROR|CRITICAL) (\S+) (.*)')
TICK_DONE = re.compile(r'Cron tick done \(sla=(\d+), crons=(\d+), plan_changes=(\d+), oauth_flows_purged=(\d+)\)')


def log_summary(text):
    """Só contagens/ordem das mensagens do logger legado; nenhum texto vai para o relatório."""
    events, problems, unparsed = [], 0, 0
    for line in text.splitlines():
        found = LOG_LINE.fullmatch(line)
        if not found:
            unparsed += bool(line.strip())  # traceback, warnings.warn, print: incerteza
            continue
        level, name, message = found.groups()
        problems += level in ('WARNING', 'ERROR', 'CRITICAL')
        if name == 'pastorai.cron_worker':
            events.append(message)
    ticks, order = [], []
    for message in events:
        if (tick := TICK_DONE.fullmatch(message)):
            ticks.append(dict(zip(('sla', 'crons', 'plan_changes', 'oauth_flows_purged'), map(int, tick.groups()))))
            order.append('tick')
        elif message == 'Cron worker shutdown requested':
            order.append('shutdown')
    return dict(started=[m for m in events if m.startswith('Cron worker started')],
                shutdown=order.count('shutdown'), ticks=ticks,
                stopped=events.count('Cron worker stopped'),
                shutdown_before_tick_done='shutdown' in order and 'tick' in order
                and order.index('shutdown') < order.index('tick'),
                problems=problems, unparsed=unparsed)


def docker_logs(argv):
    """``docker logs`` com stdout E stderr (o logging legado escreve em stderr)."""
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        completed = None
    if completed is None or completed.returncode:
        raise Refused('docker-logs')
    return completed.stdout + completed.stderr


# -- ensaio -----------------------------------------------------------------
class CronRehearsal(ActiveRehearsal):
    role, entry, worker_env = ROLE, ENTRY, CRON_ENV

    def __init__(self, *, files, log_runner=docker_logs, **kwargs):
        if not REQUIRED <= set(files):
            raise Refused('source-incomplete')
        super().__init__(files=files, **kwargs)
        self.prefix = 'pastorai-synthetic-legacy-cron-' + self.run_id[:12]
        self.log_runner = log_runner
        self.observed: dict = {}

    def flows(self):
        return self.psql_json(FLOWS_SQL)

    def digest(self):
        return self.psql_json(DIGEST_SQL)

    def worker_logs(self):
        return self.log_runner(['docker', 'logs', self.ids[self.role]])

    def seed(self):
        """Só INSERT em tenant próprio; bootstrap e demais tabelas comprovadamente intactos."""
        before, bootstrap = self.digest(), self.psql_json(BOOTSTRAP_SQL)
        self.psql(SEED_SQL)
        if self.psql_json(EMPTY_SQL) != SEEDED_COUNTS:
            raise Refused('seed')
        self.seeded = self.flows()
        self.before = self.digest()
        if (not seeded_ok(self.seeded) or not seed_touched_only(before, self.before)
                or self.psql_json(BOOTSTRAP_SQL) != bootstrap):
            raise Refused('seed')
        if self.psql_json(IDLE_SQL) != IDLE:
            raise Refused('tick-would-have-other-work')
        self.checks.append('seed-expired-and-valid-fictitious-flows-own-tenant-bootstrap-preserved-no-other-work')

    def assert_blocked(self, worker_ip, holder_ip, xid):
        """Vivo, heartbeat ``running``, fluxos como no seed e o DELETE preso no xid do holder."""
        if not self.running():
            raise Refused('worker-exited-during-barrier')
        if self.flows() != self.seeded:
            raise Refused('purged-through-barrier')
        return (self.redis('GET', HEARTBEAT) == 'running'
                and blocked_on_holder(self.psql_json(BLOCK_SQL), worker_ip, holder_ip, xid))

    def wait_blocked(self, holder, xid, started):
        worker_ip, holder_ip = self.ip(self.ids[self.role]), self.ip(holder)
        while not self.assert_blocked(worker_ip, holder_ip, xid):
            if self.clock() - started >= BARRIER_S:
                raise Refused('barrier-timeout')
            self.sleep(0.2)
        return worker_ip, holder_ip


def rehearse(r):
    r.preflight()
    r.create_support()
    r.apply_baseline()
    r.seed()

    holder = r.spawn('holder', ['-I', '-c', HOLDER_PROBE, DSN, EXPIRED, HELD, RELEASE])
    r._until(lambda: r.redis('GET', HELD) != '', 'holder-not-ready', PROBE_S)
    xid = r.redis('GET', HELD)
    if not xid.isdigit():
        raise Refused('holder-xid')
    r.checks.append('separate-connection-row-lock-on-expired-flow-only')

    started = r.clock()  # o orçamento de progresso cobre boot, bloqueio, SIGTERM e janela observada
    r.start_worker()
    worker_ip, holder_ip = r.wait_blocked(holder, xid, started)
    r.timings['blocked_after_start_s'] = round(r.clock() - started, 3)
    r.checks.append('real-cron-pid1-first-tick-delete-waits-on-holder-xid-by-ip-in-pg_locks')

    r.check_worker(running=True, extra={holder})
    r.docker('kill', '--signal', 'SIGTERM', r.ids[ROLE])
    signalled = r.clock()
    while r.clock() - signalled < HOLD_S:
        if not r.assert_blocked(worker_ip, holder_ip, xid):
            raise Refused('barrier-lost')
        r.sleep(0.2)
    # Imediatamente antes de liberar: mesmo bloqueio, banco inteiro como no seed, um só boot e nenhum tick.
    if not r.assert_blocked(worker_ip, holder_ip, xid) or r.digest() != r.before:
        raise Refused('barrier-lost')
    early = r.observed['log_before_release'] = log_summary(r.worker_logs())
    if (early['started'] != EXPECTED_LOG['started'] or early['ticks'] or early['stopped']
            or early['problems'] or early['unparsed'] or early['shutdown'] > 1):
        raise Refused('worker-log-before-release')
    r.observed['shutdown_logged_while_blocked'] = early['shutdown'] == 1  # observação, não requisito
    r.check_worker(running=True, extra={holder})
    if r.redis('GET', HEARTBEAT) != 'running':
        raise Refused('barrier-lost')
    # Medida depois do último check, sem arredondar na decisão: nada além do SET separa a recusa da liberação.
    blocked = r.clock() - started
    r.timings['blocked_s'] = round(blocked, 3)
    if blocked >= PROGRESS_BUDGET_S:
        raise Refused('barrier-too-long')
    r.redis('SET', RELEASE, '1')
    released = r.clock()
    r.checks.append('sigterm-while-delete-blocked-worker-alive-database-unchanged-before-release')

    if r.collect(holder, PROBE_S, 'holder-probe') != f'released {xid}':
        raise Refused('holder-release')
    r._await_exit(ROLE, GRACE_S)
    exited = r.clock() - released
    r.timings['exit_after_release_s'] = round(exited, 3)
    if exited >= CRON_TICK_S:
        raise Refused('exit-not-before-next-tick')
    if r.redis('DEL', RELEASE, HELD) != '2':
        raise Refused('synthetic-keys')
    if r.redis('GET', HEARTBEAT) != 'stopped':
        raise Refused('heartbeat-not-stopped')
    if r.keys() != {HEARTBEAT}:
        raise Refused('unexpected-redis-state')
    r.check_worker(running=False)
    final = r.flows()
    if not purged_ok(final, r.seeded):
        raise Refused('purge-state')
    if r.digest() != r.before:
        raise Refused('unexpected-tick-effects')
    logs = r.worker_logs()
    r.log = log_summary(logs)
    if r.log != EXPECTED_LOG:
        raise Refused('worker-log')
    r.checks += ['released-single-expired-flow-deleted-valid-flow-byte-identical',
                 'tick-completed-after-sigterm-sla-0-crons-0-plan-changes-0-purged-1',
                 'shutdown-requested-before-tick-done-exit-0-heartbeat-stopped',
                 'rest-of-database-unchanged-by-digest-redis-only-heartbeat']

    r.sleep(SURVIVE_S)
    if (r.worker_logs() != logs or r.flows() != final or r.digest() != r.before
            or r.redis('GET', HEARTBEAT) != 'stopped' or r.keys() != {HEARTBEAT}):
        raise Refused('activity-after-exit')
    r.check_worker(running=False)
    r.checks.append('no-second-tick-exit-before-tick-interval-and-state-stable-after-exit')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    reh = sub.add_parser('run')
    reh.add_argument('--repo', type=Path, required=True)
    reh.add_argument('--legacy-image', default=DEFAULT_IMAGES['legacy'])
    reh.add_argument('--redis-image', default=DEFAULT_IMAGES['redis'])
    reh.add_argument('--postgres-image', default=DEFAULT_IMAGES['postgres'])
    reh.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    report = dict(kind='synthetic-legacy-cron-active-tick-rehearsal', status='fail', production_ready=False,
                  legacy_sha=LEGACY_SHA, entrypoint='python ' + ' '.join(ENTRY), not_proven=NOT_PROVEN,
                  scope='cron-worker legado real, Redis e Postgres efemeros, SIGTERM com DELETE bloqueado; '
                        'sem provedor/producao',
                  images=dict(legacy=args.legacy_image, redis=args.redis_image, postgres=args.postgres_image),
                  expected=dict(seeded=SEEDED_COUNTS, idle=IDLE, log=EXPECTED_LOG), checks=[])
    rehearsal = None
    try:
        files = legacy_sources(args.repo)
        report['source'] = dict(files=len(files), manifest_sha256=manifest_digest(manifest(files)))
        baseline = select_baseline(args.repo)
        report['baseline'] = dict(cutoff=CUTOFF, active=baseline['active'], selected=len(baseline['selected']),
                                  excluded_known_missing=sorted(KNOWN_MISSING),
                                  first=baseline['selected'][0], last=baseline['selected'][-1],
                                  bundle_sha256=bundle_args(baseline)[0])
        rehearsal = CronRehearsal(legacy_image=args.legacy_image, redis_image=args.redis_image,
                                  postgres_image=args.postgres_image, files=files, baseline=baseline)
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
                          log=getattr(rehearsal, 'log', None), cleanup=rehearsal.cleanup())
            if report['cleanup']['status'] != 'clean' and report['status'] == 'pass':
                report.update(status='fail', reason='cleanup-incomplete')
        args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
