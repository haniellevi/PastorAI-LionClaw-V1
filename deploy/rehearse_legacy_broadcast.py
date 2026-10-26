#!/usr/bin/env python3
"""Ensaio sintético LOCAL: ciclo de vida OCIOSO do broadcast-worker legado real.

``run --repo R --report P [--legacy-image/--redis-image sha256:...]``

Reusa ``rehearse_legacy_queue`` (fonte Git exata de ``07a3f4d``, runtime do
lock, guarda de Docker local, ledger e limpeza por posse) numa rede
``--internal`` própria, só com Redis efêmero, sem portas nem montagens do
host. Não há Postgres: ``DATABASE_URL`` e Evolution apontam para loopback
morto do container. O PID 1 é ``python -m app.workers.broadcast_worker`` sem
patch nem mock (``--init=false`` explícito, conferido como ``HostConfig.Init``
``False``: um daemon com ``init: true`` não troca o PID 1), com ``ALLOW_REAL_SENDS=false``, ``BROADCAST_ASYNC_ENABLED=false``,
Brevo ``off``, Asaas ``false`` e lista de piloto vazia.

Com esses gates o legado decide ``enabled=False`` no boot e fica ocioso: nunca
chama ``tick()``/``run_delivery_cycle`` nem resolve a sessão do banco. O ensaio
prova só esse estado: heartbeat ``idle`` publicado e RENOVADO (instante de
expiração posterior), log ``enabled=False`` com o aviso OCIOSO exato e nenhum
tick/envio, Redis só com o heartbeat; SIGTERM → saída 0 antes do próximo tick,
heartbeat ``stopped`` e nenhuma atividade depois (log idêntico, TTL não
renovado). ``docker start`` do MESMO container = nova execução (outro
``StartedAt``, segundo boot no log) com ``idle`` substituindo ``stopped``;
segundo SIGTERM limpo.

"Sem rede" é inferência, não captura: destino em loopback morto, gates
``false`` e, no código legado, o caminho ocioso não cria cliente HTTP
(``EvolutionClient`` é preguiçoso e ``close()`` sem cliente não conecta).

Não prova broadcast ativo, trabalho ou transporte em curso, pendências no
banco, supervisor/restart do host, backend, pós-DDL, RLS nem produção:
``production_ready=false``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rehearse_legacy_containment import Refused
from rehearse_legacy_cron_active import LOG_LINE, docker_logs
from rehearse_legacy_queue import (
    GRACE_S, LEGACY_SHA, SURVIVE_S, SYNTHETIC_ENV, QueueRehearsal, legacy_sources, manifest, manifest_digest,
)
from rehearse_legacy_queue_active import DEFAULT_IMAGES, EXPIRY_TOLERANCE_MS, MARKER_SAMPLE_MAX_MS, expiry_renewed

ROLE = 'broadcast-worker'
ENTRY = ['-m', 'app.workers.broadcast_worker']
# Loop, gate de boot e heartbeat vêm destes blobs; a fonte selecionada precisa contê-los.
REQUIRED = frozenset({'app/workers/broadcast_worker.py', 'app/services/broadcast_health.py',
                      'app/services/worker_health.py'})
HEARTBEAT = 'pastorai:broadcast-worker:heartbeat:v1'
TICK_S = 10                     # default do Settings legado, explícito para o ensaio não depender dele
HEARTBEAT_TTL_S = max(30, TICK_S * 3)  # mesma fórmula de _publish_heartbeat
BROADCAST_ENV = {**SYNTHETIC_ENV, 'BROADCAST_WORKER_TICK_SECONDS': str(TICK_S)}
READY_S = 60
RENEW_S = 2 * TICK_S + 5        # ao menos uma publicação nova do loop ocioso
# -- log do logger legado ``pastorai.broadcast_worker`` ---------------------
LOGGER = 'pastorai.broadcast_worker'
STARTED = f'Broadcast worker started enabled=False tick={TICK_S}s'
# Único aviso aceito: o OCIOSO exato do boot desligado. Qualquer outro WARNING+ é recusa.
IDLE_WARNING = ('Broadcast worker OCIOSO: exige BROADCAST_ASYNC_ENABLED=true e ALLOW_REAL_SENDS=true; '
                'recrie o processo após ativar')
TOKENS = {('INFO', STARTED): 'started', ('WARNING', IDLE_WARNING): 'idle-warning',
          ('INFO', 'Broadcast worker idle heartbeat'): 'idle-heartbeat',
          ('INFO', 'Broadcast worker shutdown requested'): 'shutdown',
          ('INFO', 'Broadcast worker stopped'): 'stopped'}
# Máquina de estados de um boot ocioso: started → idle-warning → idle-heartbeat* → shutdown → stopped.
TRANSITIONS = {('out', 'started'): 'booted', ('booted', 'idle-warning'): 'idle',
               ('idle', 'idle-heartbeat'): 'idle', ('idle', 'shutdown'): 'stopping',
               ('stopping', 'stopped'): 'out'}
NOT_PROVEN = [
    'broadcast-ativo (enabled=False no boot: tick, claim, materializacao e entregas nunca executados)',
    'trabalho-ou-transporte-evolution-em-curso-durante-sigterm (_transport_gate nao exercitado)',
    'pendencias-de-broadcast-no-banco (sem Postgres; DATABASE_URL em loopback morto, nunca resolvido)',
    'fechar-gate-como-pausa-de-fila (idle com gate fechado nada diz sobre pendencias existentes)',
    'supervisor-restart-policy-e-reinicio-do-host',
    'sigkill-ou-timeout-do-worker-real',
    'queda-do-redis',
    'compatibilidade-pos-ddl',
    'rls-e-isolamento-por-igreja',
    'outros-servicos (backend, queue-worker, cron-worker)',
    'entrypoint-compose-de-producao',
    'integridade-de-wheels-sitecustomize-e-pth (so nome/versao das distribuicoes conferidos)',
    'ausencia-de-tentativa-de-rede-por-captura (inferida: loopback morto, gates false, caminho ocioso do codigo)',
    'producao',
]


# -- avaliações puras -------------------------------------------------------
def log_summary(text):
    """Só contagens/ordem das mensagens do logger legado; nenhum texto vai para o relatório."""
    tokens, problems, forbidden, unparsed = [], 0, 0, 0
    for line in text.splitlines():
        found = LOG_LINE.fullmatch(line)
        if not found:
            unparsed += bool(line.strip())  # traceback, warnings.warn, print: incerteza
            continue
        level, name, message = found.groups()
        token = TOKENS.get((level, message)) if name == LOGGER else None
        if token:
            tokens.append(token)
            continue
        problems += level in ('WARNING', 'ERROR', 'CRITICAL')
        # Tick, falha de tick, dispatch pausado, transporte em curso ou boot habilitado.
        forbidden += name == LOGGER
    state, cycles, ordered = 'out', 0, True
    for token in tokens:
        following = TRANSITIONS.get((state, token))
        if following is None:
            ordered = False
            break
        cycles += (state, following) == ('stopping', 'out')
        state = following
    return dict(boots=tokens.count('started'), cycles=cycles, state=state if ordered else None,
                idle_warnings=tokens.count('idle-warning'), idle_heartbeats=tokens.count('idle-heartbeat'),
                forbidden=forbidden, problems=problems, unparsed=unparsed)


def log_ok(summary, *, cycles, running):
    """``cycles`` boots completos e, se ``running``, mais um boot ocioso em aberto."""
    boots = cycles + running
    return (summary['state'] == ('idle' if running else 'out') and summary['cycles'] == cycles
            and summary['boots'] == boots and summary['idle_warnings'] == boots
            and not summary['forbidden'] and not summary['problems'] and not summary['unparsed'])


# -- ensaio -----------------------------------------------------------------
class BroadcastRehearsal(QueueRehearsal):
    role, entry, worker_env = ROLE, ENTRY, BROADCAST_ENV

    def __init__(self, *, files, log_runner=docker_logs, **kwargs):
        if not REQUIRED <= set(files):
            raise Refused('source-incomplete')
        super().__init__(files=files, **kwargs)
        self.prefix = 'pastorai-synthetic-legacy-broadcast-' + self.run_id[:12]
        self.log_runner = log_runner
        self.timings: dict[str, float] = {}
        self.observed: dict = {}
        self.started_at: list[str] = []

    def _legacy_argv(self, role, network, env):
        # ``init: true`` no daemon injetaria docker-init como PID 1 sem mudar Path/Args do inspect.
        argv = super()._legacy_argv(role, network, env)
        return [*argv[:-1], '--init=false', argv[-1]]

    def check_worker(self, *, running):
        super().check_worker(running=running)
        # ``None`` = default do daemon (pode ser init); só ``False`` explícito garante o worker como PID 1.
        if (self.inspect(self.ids[self.role]).get('HostConfig') or {}).get('Init') is not False:
            raise Refused('pid1-init')

    def worker_logs(self):
        return self.log_runner(['docker', 'logs', self.ids[self.role]])

    def worker_state(self):
        return self.inspect(self.ids[self.role]).get('State') or {}

    def heartbeat(self):
        return self.redis('GET', HEARTBEAT)

    def only_heartbeat(self, refusal):
        # Redis próprio e descartável: o conjunto inteiro, não só o prefixo legado.
        if not self.keys() <= {HEARTBEAT}:
            raise Refused(refusal)

    def expiry_window(self):
        """Janela (ms, relógio monotônico) que contém a expiração absoluta do heartbeat."""
        start = self.clock()
        value = self.redis('PTTL', HEARTBEAT)
        end = self.clock()
        ttl = int(value) if value.lstrip('-').isdigit() else -2
        if not 0 < ttl <= HEARTBEAT_TTL_S * 1000:
            raise Refused('heartbeat-ttl')
        if (end - start) * 1000 > MARKER_SAMPLE_MAX_MS:
            raise Refused('heartbeat-ttl-uncertain')
        return start * 1000 + ttl, end * 1000 + ttl

    def wait_idle(self, previous):
        """Nova execução do processo publicando ``idle``; ``previous`` é o único outro valor aceito."""
        limit = self.clock() + READY_S
        while (value := self.heartbeat()) != 'idle':
            if value != previous:
                raise Refused('heartbeat-not-idle')  # running/ready/error = não ocioso
            if not self.worker_state().get('Running'):
                raise Refused('worker-exited-before-idle')
            if self.clock() >= limit:
                raise Refused('idle-timeout')
            self.sleep(0.2)
        started = self.worker_state().get('StartedAt')
        if not started or started in self.started_at:
            raise Refused('not-a-new-execution')
        self.started_at.append(started)
        self.only_heartbeat('unexpected-redis-state')
        self.check_worker(running=True)

    def wait_renewed(self):
        """O loop ocioso republica ``idle``: a expiração avança além da amostra inicial."""
        first = self.expiry_window()
        limit = self.clock() + RENEW_S
        while True:
            self.sleep(0.5)
            if not self.worker_state().get('Running'):
                raise Refused('worker-exited-while-idle')
            if self.heartbeat() != 'idle':
                raise Refused('heartbeat-not-idle')
            self.only_heartbeat('unexpected-redis-state')
            current = self.expiry_window()
            if expiry_renewed(first, current):
                return round((current[0] - first[1]) / 1000, 3)
            if self.clock() >= limit:
                raise Refused('heartbeat-not-renewed')

    def stop(self, cycles):
        """SIGTERM sem SIGKILL; saída 0 antes do próximo tick; ``stopped``; nada depois."""
        if not log_ok(log_summary(self.worker_logs()), cycles=cycles - 1, running=True):
            raise Refused('worker-log-while-idle')
        self.check_worker(running=True)
        self.docker('kill', '--signal', 'SIGTERM', self.ids[self.role])
        signalled = self.clock()
        self._await_exit(self.role, GRACE_S)
        exited = self.clock() - signalled
        self.timings[f'exit_after_sigterm_{cycles}_s'] = round(exited, 3)
        if exited >= TICK_S:
            raise Refused('exit-not-before-next-tick')
        if self.heartbeat() != 'stopped':
            raise Refused('heartbeat-not-stopped')
        if self.keys() != {HEARTBEAT}:
            raise Refused('unexpected-redis-state')
        self.check_worker(running=False)
        logs = self.worker_logs()
        summary = self.observed[f'log_after_stop_{cycles}'] = log_summary(logs)
        if not log_ok(summary, cycles=cycles, running=False):
            raise Refused('worker-log')
        window = self.expiry_window()
        self.sleep(SURVIVE_S)
        if (self.worker_logs() != logs or self.heartbeat() != 'stopped' or self.keys() != {HEARTBEAT}
                or expiry_renewed(window, self.expiry_window()) or self.worker_state().get('Running')):
            raise Refused('activity-after-stop')
        self.check_worker(running=False)


def rehearse(r):
    r.preflight()
    r.create_support()
    r.start_worker()
    r.wait_idle('')
    r.checks.append('real-broadcast-pid1-enabled-false-heartbeat-idle-redis-only-heartbeat')
    r.timings['renewed_after_1_s'] = r.wait_renewed()
    r.checks.append('idle-heartbeat-renewed-by-loop-no-tick-no-send-logged')
    r.stop(1)
    r.checks += ['sigterm-exit-0-before-next-tick-heartbeat-stopped-only-heartbeat-in-redis',
                 'log-one-boot-idle-warning-shutdown-stopped-no-other-warning',
                 'no-activity-after-stop-log-identical-stopped-ttl-not-renewed']

    r.docker('start', r.ids[ROLE])
    r.wait_idle('stopped')
    r.checks.append('restart-same-container-new-execution-idle-replaces-stopped')
    r.timings['renewed_after_2_s'] = r.wait_renewed()
    r.stop(2)
    r.checks += ['second-sigterm-exit-0-heartbeat-stopped-log-two-boots-two-stops',
                 'no-activity-after-second-stop']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    reh = sub.add_parser('run')
    reh.add_argument('--repo', type=Path, required=True)
    reh.add_argument('--legacy-image', default=DEFAULT_IMAGES['legacy'])
    reh.add_argument('--redis-image', default=DEFAULT_IMAGES['redis'])
    reh.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    report = dict(kind='synthetic-legacy-broadcast-idle-lifecycle-rehearsal', status='fail', production_ready=False,
                  legacy_sha=LEGACY_SHA, entrypoint='python ' + ' '.join(ENTRY), worker_state='idle',
                  not_proven=NOT_PROVEN,
                  scope='broadcast-worker legado real ocioso (gates fechados), Redis efemero, sem Postgres; '
                        'sem broadcast ativo/provedor/producao',
                  images=dict(legacy=args.legacy_image, redis=args.redis_image),
                  expected=dict(started=STARTED, tick_s=TICK_S, heartbeat_ttl_s=HEARTBEAT_TTL_S,
                                expiry_tolerance_ms=EXPIRY_TOLERANCE_MS), checks=[])
    rehearsal = None
    try:
        files = legacy_sources(args.repo)
        report['source'] = dict(files=len(files), manifest_sha256=manifest_digest(manifest(files)))
        rehearsal = BroadcastRehearsal(legacy_image=args.legacy_image, redis_image=args.redis_image, files=files)
        rehearse(rehearsal)
        report.update(status='pass', reason=None)
    except Refused as exc:
        preflight = rehearsal is None or rehearsal.phase == 'preflight'
        report.update(status='refused' if preflight else 'fail', reason=str(exc))
    except KeyboardInterrupt:
        report['reason'] = 'interrupted'
    except OSError:
        report['reason'] = 'os-error'  # código fixo; sem caminho nem mensagem do sistema
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        report['reason'] = 'unexpected-output'
    finally:
        if rehearsal is not None:
            report.update(checks=rehearsal.checks, mismatch=rehearsal.mismatch, timings=rehearsal.timings,
                          observed=rehearsal.observed, cleanup=rehearsal.cleanup())
            if report['cleanup']['status'] != 'clean' and report['status'] == 'pass':
                report.update(status='fail', reason='cleanup-incomplete')
        args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
