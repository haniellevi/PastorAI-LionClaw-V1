#!/usr/bin/env python3
"""Ensaio INTEGRADO local da primeira transição legado ``07a3f4d`` -> candidato.

``run --repo R --report P [--fixtures main,pre-ddl,post-ddl,broadcast]``

Cada fixture cria, com UUID próprio, uma instalação legada sintética que
reproduz a FORMA observada (não o hash nem a topologia exata de PROD): três
serviços por ``docker compose`` gerado (projeto prefixado) e o
``broadcast-worker`` avulso por ``docker run``, todos ``restart: always``,
imagem legada local com a fonte exata de ``07a3f4d``; Postgres com as 78
migrations, Redis, Evolution/Brevo falsos e redes ``--internal`` (app e borda),
sem portas do host. O controlador real ``initial_transition.py`` roda como
subprocesso; o ensaio só observa, segura barreiras e mata o CONTROLADOR
(SIGKILL) em fronteiras, nunca um worker.

Fixtures: ``main`` (in-flight do queue-worker, backlog, reconciliação, crash
na contenção/no aplicador ativo/no candidato, promoção real e ingestão nova);
``pre-ddl`` (recusa antes do DDL e retomada confirmada do legado);
``post-ddl`` (índice CONCURRENTLY inválido: contenção mantida, legado nunca
religado, decisão humana e recuperação adiante); ``broadcast`` (gates
ALLOW/BROADCAST ``true`` só nesta fixture, ``config_mirror=false``: envio em
curso no provedor falso durante SIGTERM, pendência preservada e enviada uma vez
pelo candidato). ``production_ready=false``.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import zlib
from pathlib import Path

from initial_transition import CATALOG_PROBE, PHASES, git_tree
from initial_transition_ops import BACKFILL_SQL, COMPOSE_PROJECT
from rehearse_legacy_containment import OWNER_LABEL, ROLE_LABEL, SCOPE, SCOPE_LABEL, Refused, Rehearsal
from rehearse_legacy_queue import LEGACY_SHA
from rehearse_legacy_queue_active import (
    DEFAULT_IMAGES, MIGRATE_PROBE, PG_DB, PG_ENV, PG_PASSWORD, PG_TMPFS, PG_USER, bundle_args, select_baseline,
)

HERE = Path(__file__).resolve().parent
CANDIDATE_SHA = '6b0b302bd1c1f84dfef7516babee2b7767d3219c'
CANDIDATE_IMAGE = 'sha256:d9fea6b701aea2b22cb847538881a92b3ea4726dd525fdc1b1e09cc00a960c45'
ROLES = ('backend', 'queue-worker', 'cron-worker', 'broadcast-worker')
PROD_NAMES = dict(backend='pastorai_backend', **{'queue-worker': 'pastorai_queue_worker',
                  'cron-worker': 'pastorai_cron_worker', 'broadcast-worker': 'pastorai_broadcast_worker'})
COMMANDS = {'backend': (['uvicorn'], ['app.main:app', '--host', '0.0.0.0', '--port', '8000']),
            'queue-worker': (['python'], ['-m', 'app.workers.queue_worker']),
            'cron-worker': (['python'], ['-m', 'app.workers.cron_worker']),
            'broadcast-worker': (['python'], ['-m', 'app.workers.broadcast_worker'])}
DSN = f'postgresql://postgres:{PG_PASSWORD}@postgres:5432/{PG_DB}'
TENANT_A, TENANT_B = '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000b1'
INSTANCE_A, CONTACT = 'synthetic-transition-a', '5500000000011'
WEBHOOK_TOKEN = 'synthetic-webhook-token-not-a-secret'
HEARTBEATS = {r: f'pastorai:{r}:heartbeat:v1' for r in ('queue-worker', 'cron-worker', 'broadcast-worker')}
QUEUE = 'pastorai:webhooks'
PROCESSING = 'pastorai:webhooks:processing:'
NOT_PROVEN = [
    'producao (nenhum adaptador de PROD; Supabase, VPS e workflow reais nao tocados)',
    'reinicio-real-do-daemon-ou-host (politica persistida so provada por inspect)',
    'retry-real-da-evolution (provedor falso; webhooks recusados durante a janela nao sao reconciliados)',
    'imagem-oficial (candidata derivada local nao oficial; legada sintetica com /opt/legacy e uid 65534)',
    'topologia-exata-de-producao (compose gerado e prefixado; mesma forma 3+1, nao o mesmo arquivo)',
    'papeis-pooler-e-timeouts-do-supabase (login sintetico postgres)',
    'turno-completo-do-agente (lista de piloto vazia; capacidade de produto inalterada)',
    'adocao-pelo-backend-release.sh (workflow nao passa o projeto Compose do candidato)',
    'escritores-fora-do-escopo-observado (so rede propria, IPs, pg_stat_activity e CLIENT LIST)',
    'compose-up-manual-no-projeto-legado (recriaria com restart always; so procedimento impede)',
    'igualdade-de-chaves-redis-com-ttl (heartbeats e marcadores dedup efemeros ficam fora do snapshot; '
    'filas criticas esperadas sao exigidas sem TTL e comparadas item a item)',
    'docker-kill-marca-parada-manual (restart always so reiniciaria no boot do daemon; o controle negativo '
    'usa saida nao manual de dentro do container)',
]

EVOLUTION_CODE = (HERE / 'synthetic_evolution.py').read_text(encoding='utf-8')
POST_WEBHOOK = r'''
import json, sys, urllib.error, urllib.request
request = urllib.request.Request('http://backend:8000/whatsapp/webhook?token=' + sys.argv[1],
    data=bytes.fromhex(sys.argv[2]), method='POST', headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        print(response.status)
except urllib.error.HTTPError as exc:
    print(exc.code)
except OSError as exc:
    print(type(exc).__name__)
'''
HTTP_GET = r'''
import json, sys, time, urllib.error, urllib.request
limit = time.monotonic() + float(sys.argv[2])
status = None
while time.monotonic() < limit:
    try:
        with urllib.request.urlopen(sys.argv[1], timeout=3) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except OSError:
        status = None
    if status == 200:
        break
    time.sleep(0.5)
print(json.dumps({'status': status}))
'''
TABLE_LOCK = r'''
import sys, time
import psycopg2, redis
conn = psycopg2.connect(sys.argv[1])
cur = conn.cursor()
cur.execute(sys.argv[2])
client = redis.Redis.from_url(sys.argv[3], decode_responses=True)
client.set(sys.argv[4], '1', ex=600)
limit = time.monotonic() + 300
while client.get(sys.argv[5]) != '1' and time.monotonic() < limit:
    time.sleep(0.05)
conn.rollback()
print('released')
'''
NEGATIVE = ('import signal, sys, time\nsignal.signal(signal.SIGTERM, lambda *a: sys.exit(0))\n'
            'print("handler-ready", flush=True)\nwhile True:\n    time.sleep(1)\n')


def payload(message_id):
    return {'event': 'messages.upsert', 'instance': INSTANCE_A, 'sender': '5500000000001@s.whatsapp.net',
            'data': {'key': {'id': message_id, 'remoteJid': CONTACT + '@s.whatsapp.net', 'fromMe': False},
                     'pushName': 'Contato Sintetico', 'message': {'conversation': 'Mensagem sintetica'}}}


def private_env(gates):
    """Synthetic private config (fictitious values only); written 0600, never logged."""
    env = dict(APP_ENV='synthetic-rehearsal', DATABASE_URL=DSN.replace('postgresql:', 'postgresql+psycopg2:'),
               REDIS_URL='redis://redis:6379/0', EVOLUTION_API_URL='http://evolution-api:8080',
               EVOLUTION_API_KEY='synthetic-evolution-key-not-a-secret', EVOLUTION_WEBHOOK_SECRET=WEBHOOK_TOKEN,
               EVOLUTION_WEBHOOK_CALLBACK_URL='http://backend:8000/whatsapp/webhook',
               BREVO_API_URL='http://evolution-api:8080/brevo/v3', BREVO_API_KEY='synthetic-brevo-not-a-secret',
               WHATSAPP_PILOTO_IGREJA_IDS='', AGENDA_NOTIFY_ENABLED='false', WHATSAPP_SLA_ENABLED='false',
               AGENT_TRUSTED_INBOUND_IDENTITY_ENABLED='false', CRON_TICK_SECONDS='10',
               BROADCAST_WORKER_TICK_SECONDS='10', SESSION_JWT_SECRET=secrets.token_hex(32),
               SECRETS_ENCRYPTION_KEY=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    env.update(gates)
    return env


class Fixture(Rehearsal):
    """Owned resources of one fixture; reuses the containment ledger, labels and cleanup."""

    def __init__(self, kind, *, repo, images, gates, workdir):
        super().__init__(worker_image=images['legacy'], redis_image=images['redis'])
        self.kind, self.repo, self.gates = kind, Path(repo), gates
        self.prefix = f'pastorai-synthetic-transition-{self.run_id[:12]}'
        self.images.update(postgres=images['postgres'], candidate=images['candidate'])
        self.created['tags'] = []
        self.dir = Path(tempfile.mkdtemp(prefix=f'pastorai-transition-{self.run_id[:12]}-', dir=workdir))
        self.state = self.dir / 'state'
        self.checks, self.observed, self.timings, self.probes = [], {}, {}, []
        self.legacy, self.edge, self.spec_path = {}, None, self.dir / 'spec.json'

    # -- primitives -------------------------------------------------------
    def check(self, condition, code, label=None):
        if not condition:
            raise Refused(code)
        if label:
            self.checks.append(label)

    def tag(self, image, name):
        self.docker('tag', image, name)
        self.created['tags'].append(name)
        return name

    def legacy_run(self, role, args, *, network=None, env=None, entry='python3', restart='no', alias=None,
                   name=None, user='65534:65534', workdir='/opt/legacy', image=None):
        flags = [p for k, v in sorted((env or {}).items()) for p in ('--env', f'{k}={v}')]
        if name is None:  # every container name carries this run's own prefix
            self.serial = getattr(self, 'serial', 0) + 1
            name = f'{self.prefix}-{role}-{self.serial:03d}'
        return self._record('containers', self.docker(
            'run', '-d', '--pull', 'never', '--restart', restart, '--network', network or self.network,
            *(['--network-alias', alias] if alias else []), *(['--name', name] if name else []),
            '--entrypoint', entry, '--user', user, '--workdir', workdir, '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--pids-limit', '256', '--init=false',
            '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m', *self.labels(role), *flags,
            image or self.images['worker'], *args))

    def finish(self, identifier, timeout=600, code='probe'):
        limit = self.clock() + timeout
        while (state := self.inspect(identifier).get('State') or {}).get('Running'):
            if self.clock() >= limit:
                raise Refused(code + '-timeout')
            self.sleep(0.5)
        lines = self.docker('logs', identifier).strip().splitlines()
        if state.get('ExitCode') != 0 or not lines:
            raise Refused(code)
        return lines[-1]

    def psql(self, sql):
        return self.docker('exec', '-e', 'PGAPPNAME=pastorai-rehearsal-observer', self.ids['postgres'], 'psql',
                           '-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-d', PG_DB,
                           '-c', sql).strip()

    def pjson(self, sql):
        return json.loads(self.psql(sql))

    def rcli(self, db, *args):
        return self.docker('exec', self.ids['redis'], 'redis-cli', '-n', str(db), *args).strip()

    def messages(self, *ids):
        return {i: int(self.psql(f"select count(*) from messages where provider_message_id = '{i}'")) for i in ids}

    def until(self, predicate, code, timeout=90):
        self._until(predicate, code, timeout)

    def webhook(self, message_id):
        body = json.dumps(payload(message_id)).encode().hex()
        return self.docker('exec', self.ids['evolution'], 'python3', '-I', '-c', POST_WEBHOOK, WEBHOOK_TOKEN,
                           body).strip()

    def edge_get(self, path, timeout=60):
        probe = self.legacy_run('probe', ['-I', '-c', HTTP_GET, 'http://backend:8000' + path, str(timeout)],
                                network=self.edge)
        self.probes.append(probe)
        return json.loads(self.finish(probe, timeout + 30))['status']

    def effects(self):
        raw = self.rcli(2, 'HGETALL', 'synthetic:evo:effects').splitlines()
        return {raw[i]: int(raw[i + 1]) for i in range(0, len(raw) - 1, 2)}

    # -- installation -------------------------------------------------------
    def build(self, reference_catalog):
        self.guard_local()
        for image in self.images.values():
            found = json.loads(self.docker('image', 'inspect', image))[0].get('Id')
            self.check(found == image, 'image-not-local-immutable')
        self.legacy_tag = self.tag(self.images['worker'], f'{self.prefix}-legacy:07a3f4d')
        self.candidate_tag = self.tag(self.images['candidate'], f'{self.prefix}-candidate:{CANDIDATE_SHA[:12]}')
        labels = ['--label', f'{OWNER_LABEL}={self.run_id}', '--label', f'{SCOPE_LABEL}={SCOPE}']
        self.network = self._record('networks', self.docker('network', 'create', '--internal', *labels,
                                                            f'{self.prefix}-app').strip())
        self.edge = self._record('networks', self.docker('network', 'create', '--internal', *labels,
                                                         f'{self.prefix}-edge').strip())
        self.ids['redis'] = self.start_container('redis')
        self.until(self._redis_ready, 'redis-readiness')
        self.start_postgres()
        self.apply_baseline()
        self.ids['evolution'] = self.legacy_run('evolution', ['-I', '-c', EVOLUTION_CODE], alias='evolution-api',
                                                env={'SYNTHETIC_REDIS_URL': 'redis://redis:6379/2'},
                                                name=f'{self.prefix}-evolution')
        self.until(lambda: self.rcli(2, 'GET', 'synthetic:evo:boots') == '1', 'evolution-readiness')
        self.seed()
        self.env_file = self.dir / 'synthetic-private.env'
        fd = os.open(self.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as out:
            out.write(''.join(f'{k}={v}\n' for k, v in sorted(private_env(self.gates).items())))
        self.start_legacy()
        self.reference_catalog = reference_catalog

    def start_postgres(self):
        flags = [p for path, opts in sorted(PG_TMPFS.items()) for p in ('--tmpfs', f'{path}:{opts}')]
        env = [p for k, v in sorted(PG_ENV.items()) for p in ('--env', f'{k}={v}')]
        self.ids['postgres'] = self._record('containers', self.docker(
            'run', '-d', '--pull', 'never', '--restart', 'no', '--network', self.network, '--network-alias',
            'postgres', '--name', f'{self.prefix}-postgres', '--entrypoint', 'docker-entrypoint.sh', '--user',
            PG_USER, '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', *flags,
            *self.labels('postgres'), *env, self.images['postgres'], 'postgres'))

        def ready():
            try:
                self.docker('exec', self.ids['postgres'], 'pg_isready', '-q', '-h', '127.0.0.1', '-U', 'postgres',
                            '-d', PG_DB)
                return True
            except Refused:
                return False
        self.until(ready, 'postgres-readiness', 120)

    def apply_baseline(self):
        self.baseline = select_baseline(self.repo)
        digest, chunks = bundle_args(self.baseline)
        probe = self.legacy_run('migrate', ['-I', '-B', '-c', MIGRATE_PROBE, DSN, digest, *chunks])
        self.probes.append(probe)
        result = json.loads(self.finish(probe, 600, 'baseline'))
        self.check(result.get('ok') is True and result.get('applied') == 78, 'baseline-apply')
        ledger = self.pjson("select json_agg(name order by name) from schema_migrations")
        self.check(ledger == self.baseline['selected'], 'baseline-ledger',
                   'baseline-78-by-current-migrate.py-cmd_apply-roles-acl')

    def seed(self):
        self.psql(
            f"insert into igrejas (id, nome) values ('{TENANT_A}', 'Igreja Sintetica A'), "
            f"('{TENANT_B}', 'Igreja Sintetica B');"
            f"insert into whatsapp_connections (igreja_id, instance, numero, status) values "
            f"('{TENANT_A}', '{INSTANCE_A}', '5500000000001', 'online'), "
            f"('{TENANT_B}', 'synthetic-transition-b', '5500000000002', 'online');")
        self.reconcile = None
        if self.kind in ('main', 'pre-ddl'):
            ids = {k: str(uuid.uuid4()) for k in ('pessoa', 'admin_pessoa', 'op_pessoa', 'admin', 'keep',
                                                   'target', 'operator', 'operacao')}
            sql = [f"insert into pessoas (id, igreja_id, nome, telefone) values ('{ids['pessoa']}', '{TENANT_A}', "
                   f"'Pessoa Sintetica', '5511900000101'), ('{ids['admin_pessoa']}', '{TENANT_A}', 'Admin Sintetico', "
                   f"'5511900000102'), ('{ids['op_pessoa']}', '{TENANT_B}', 'Operador Sintetico', '5511900000103');"]
            for key, tenant, pessoa, role in (('admin', TENANT_A, 'admin_pessoa', 'admin'),
                                              ('keep', TENANT_A, 'pessoa', 'pastor'),
                                              ('target', TENANT_A, 'pessoa', 'membro'),
                                              ('operator', TENANT_B, 'op_pessoa', 'admin')):
                sql.append(f"insert into app_users (id, igreja_id, status, nome, email, pessoa_id, clerk_user_id) "
                           f"values ('{ids[key]}', '{tenant}', 'ativo', 'Conta Sintetica', '{ids[key]}@example.test', "
                           f"'{ids[pessoa]}', 'clerk_{ids[key].replace('-', '')}');"
                           f"insert into user_roles (igreja_id, user_id, papel) values ('{tenant}', '{ids[key]}', "
                           f"'{role}');")
            sql.append(f"insert into platform_admins (app_user_id, email) values ('{ids['operator']}', "
                       f"'platform@example.test'); update igrejas set dono_id = '{ids['admin']}' "
                       f"where id = '{TENANT_A}';")
            self.psql(''.join(sql))
            self.reconcile = dict(igreja=TENANT_A, pessoa=ids['pessoa'], manter=ids['keep'], corrigir=ids['target'],
                                  admin_igreja=ids['admin'], operador=ids['operator'], operacao=ids['operacao'])
            self.check(self.duplicates() == 1, 'seed-duplicate', 'fixture-one-duplicate-person-link-group')
        if self.kind == 'pre-ddl':
            # A pre-existing audit row of the same action WITHOUT operation_id (SQL NULL edge, B4).
            self.psql("insert into platform_audit_log (acao, alvo_tipo, detalhe) values "
                      "('team_pessoa_reconciliar_duplicidade', 'app_user', '{\"operacao\": \"synthetic-legacy\"}')")
            # One July backfill candidate: a 'membro' whose phone is the connected number.
            self.psql(f"insert into pessoas (igreja_id, nome, telefone, tipo) values ('{TENANT_A}', "
                      f"'Numero Atendimento', '5500000000001', 'membro')")
        if self.kind == 'broadcast':
            self.deliveries = [str(uuid.uuid4()), str(uuid.uuid4())]
            people = [str(uuid.uuid4()), str(uuid.uuid4())]
            broadcast, execution = str(uuid.uuid4()), str(uuid.uuid4())
            phones = ['11900000201', '11900000202']
            self.psql(''.join(f"insert into pessoas (id, igreja_id, nome, telefone, consentimento) values ('{p}', "
                              f"'{TENANT_A}', 'Destinatario Sintetico', '{t}', true);" for p, t in zip(people, phones)))
            # Broadcast + deliveries are inserted later (seed_deliveries), when the scenario is ready to
            # hold the send: the legacy Evolution client times out at 15 s.
            self.broadcast_rows = (people, broadcast, execution, phones)
        counts = self.pjson(BACKFILL_SQL)
        self.observed['backfill_candidates'] = counts
        expected = 1 if self.kind == 'pre-ddl' else 0
        self.check(counts == {'membro_por_vinculo': 0, 'numero_atendimento': expected}, 'seed-backfill',
                   f'fixture-july-backfill-candidates-explicit-{expected}')

    def seed_deliveries(self):
        people, broadcast, execution, phones = self.broadcast_rows
        self.rcli(2, 'SET', 'synthetic:evo:hold', '1')
        self.psql(f"insert into broadcasts (id, igreja_id, titulo, mensagem, segmentos, modo, status) values "
                  f"('{broadcast}', '{TENANT_A}', 'Sintetico', 'Mensagem sintetica', '{{}}', 'agora', 'enviado');"
                  f"insert into broadcast_execucoes (id, igreja_id, broadcast_id, seq, data_nominal) values "
                  f"('{execution}', '{TENANT_A}', '{broadcast}', 1, current_date);"
                  + ''.join(f"insert into broadcast_entregas (id, igreja_id, execucao_id, pessoa_id, telefone, "
                            f"criado_em) values ('{d}', '{TENANT_A}', '{execution}', '{p}', '{t}', "
                            f"now() - interval '{10 - i} seconds');"
                            for i, (d, p, t) in enumerate(zip(self.deliveries, people, phones))))

    def duplicates(self):
        return int(self.psql("select count(*) from (select 1 from app_users where pessoa_id is not null "
                             "group by igreja_id, pessoa_id having count(*) > 1) s"))

    def service(self, role, image_tag, name, restart, extra=None):
        entry, command = COMMANDS[role]
        legacy = image_tag == self.legacy_tag
        definition = {
            'image': image_tag, 'container_name': name, 'restart': restart, 'pull_policy': 'never',
            'entrypoint': entry, 'command': command, 'env_file': [str(self.env_file)], 'read_only': True,
            'tmpfs': ['/tmp:rw,noexec,nosuid,size=32m'], 'cap_drop': ['ALL'], 'init': False,
            'security_opt': ['no-new-privileges'], 'labels': {OWNER_LABEL: self.run_id, SCOPE_LABEL: SCOPE,
                                                              ROLE_LABEL: ('legacy-' if legacy else 'candidate-') + role},
            'networks': {'app': {'aliases': [role]}} if role != 'backend' else
                        {'app': {'aliases': ['backend']}, 'edge': {'aliases': ['backend']}},
        }
        if legacy:
            definition.update(user='65534:65534', working_dir='/opt/legacy')
        definition.update(extra or {})
        return definition

    def compose_file(self, path, services):
        document = {'services': services, 'networks': {
            'app': {'external': True, 'name': f'{self.prefix}-app'},
            'edge': {'external': True, 'name': f'{self.prefix}-edge'}}}
        path.write_text(json.dumps(document, indent=2, sort_keys=True))  # JSON is valid YAML for Compose
        return path

    def start_legacy(self):
        names = {r: f'{self.prefix}-{PROD_NAMES[r]}' for r in ROLES}
        self.legacy_project = f'{self.prefix}-legacy'
        legacy_compose = self.compose_file(self.dir / 'legacy-compose.yml', {
            r: self.service(r, self.legacy_tag, names[r], 'always') for r in ROLES[:3]})
        self.docker('compose', '--project-name', self.legacy_project, '--file', str(legacy_compose), 'up', '-d',
                    '--no-build', '--pull', 'never')
        for role in ROLES[:3]:
            identifier = self.docker('ps', '-aq', '--no-trunc', '--filter', f'name=^/{names[role]}$').strip()
            self.legacy[role] = self._record('containers', identifier)
        b = self.service('broadcast-worker', self.legacy_tag, names['broadcast-worker'], 'always')
        flags = [p for line in self.env_file.read_text().splitlines() for p in ('--env', line)]
        self.legacy['broadcast-worker'] = self._record('containers', self.docker(
            'run', '-d', '--pull', 'never', '--restart', 'always', '--name', names['broadcast-worker'], '--network',
            self.network, '--network-alias', 'broadcast-worker', '--entrypoint', 'python', '--user', '65534:65534',
            '--workdir', '/opt/legacy', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--init=false', '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m', *[p for k, v in b['labels'].items()
                                                                           for p in ('--label', f'{k}={v}')],
            *flags, self.legacy_tag, *COMMANDS['broadcast-worker'][1]))
        self.legacy_names = names
        candidate_names = {r: f'{self.prefix}-cand-{r}' for r in ROLES}
        self.candidate_project = f'{self.prefix}-candidate'
        self.candidate_compose = self.compose_file(self.dir / 'candidate-compose.yml', {
            r: self.service(r, self.candidate_tag, candidate_names[r], 'no') for r in ROLES})
        self.candidate_names = candidate_names
        alive = {'ready', 'running', 'idle'}
        self.until(lambda: all(self.rcli(0, 'GET', k) in alive for k in HEARTBEATS.values()), 'legacy-heartbeats',
                   120)
        self.check(self.edge_get('/health') == 200, 'legacy-edge-health',
                   'legacy-3-compose-1-standalone-restart-always-heartbeats-and-edge-health')
        for role in ROLES:
            data = self.inspect(self.legacy[role])
            labels = data['Config']['Labels']
            compose = COMPOSE_PROJECT in labels
            self.check(compose == (role != 'broadcast-worker') and data['HostConfig']['RestartPolicy']['Name']
                       == 'always', 'legacy-topology')
        self.check(self.webhook('m0') == '202', 'legacy-webhook')
        self.until(lambda: self.messages('m0')['m0'] == 1, 'legacy-ingest', 60)
        self.checks.append('legacy-internal-ingress-evolution-to-backend-202-and-persisted-once')

    # -- controller -----------------------------------------------------------
    def write_spec(self, expect_settled, expect_candidate, pending):
        spec = dict(version=1, synthetic=True, run_id=self.run_id, prefix=self.prefix, repo=str(self.repo),
                    legacy=dict(sha=LEGACY_SHA, image=self.images['worker'], source_root='/opt/legacy',
                                project=self.legacy_project, containers=self.legacy, standalone=['broadcast-worker']),
                    candidate=dict(sha=CANDIDATE_SHA, image=self.images['candidate'], project=self.candidate_project,
                                   compose_file=str(self.candidate_compose), names=self.candidate_names,
                                   compose_sha256=hashlib.sha256(self.candidate_compose.read_bytes()).hexdigest()),
                    network=dict(app=self.network, edge=self.edge),
                    support=dict(postgres=self.ids['postgres'], redis=self.ids['redis'],
                                 evolution=self.ids['evolution']),
                    database=dict(superuser='postgres', name=PG_DB, dsn=DSN), reconcile=self.reconcile,
                    expect_settled=expect_settled, expect_candidate=expect_candidate,
                    expected_catalog=self.reference_catalog, expected_pending=pending,
                    release_root=str(self.dir / 'release-root'), declared_inert=[],
                    timeouts=dict(grace_s=30, settle_s=4, migration_s=300, job_s=240, ready_s=90, active_wait_s=5))
        self.spec_path.write_text(json.dumps(spec, sort_keys=True, indent=1))

    def controller(self, *args, background=False):
        argv = [sys.executable, str(HERE / 'initial_transition.py'), args[0], '--spec', str(self.spec_path),
                '--state', str(self.state), *[p for i in self.live_probes() for p in ('--allow-probe', i)], *args[1:]]
        if background:
            return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        done = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
        try:
            out = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            out = {'status': 'unparsed'}
        return done.returncode, out

    def live_probes(self):
        """Every rehearsal-owned container besides legacy/support, declared per invocation (journaled)."""
        return [*self.probes, *getattr(self, 'inert', [])]

    def candidate(self):
        events = [e for e in self.journal() if e['kind'] == 'done' and e.get('step') == 'candidate:create']
        return events[-1]['ids'] if events else {}

    def ledger(self):
        return self.pjson("select coalesce(json_agg(name order by name), '[]') from schema_migrations")

    def journal(self):
        path = self.state / 'journal.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def wait_journal(self, predicate, code, process=None, timeout=240):
        def ok():
            if process is not None and process.poll() is not None:
                raise Refused(code + '-controller-exited')
            return any(predicate(e) for e in self.journal())
        self.until(ok, code, timeout)

    def kill_controller(self, process):
        process.send_signal(signal.SIGKILL)
        process.wait(timeout=30)
        self.check(process.returncode == -signal.SIGKILL, 'controller-not-killed')

    def pending(self):
        manifest = [n for n in self.baseline_manifest()]
        return [n for n in manifest if n not in set(self.baseline['selected'])]

    def baseline_manifest(self):
        from initial_transition import CANDIDATE_BLOBS, CANDIDATE_PATHSPECS, migration_manifest
        files = git_tree(self.repo, CANDIDATE_SHA, CANDIDATE_PATHSPECS, CANDIDATE_BLOBS)
        sql = {p.split('/', 2)[2]: b for p, b in files.items() if re.fullmatch(r'backend/migrations/[^/]+\.sql', p)}
        return migration_manifest(files['backend/scripts/migrate.py'], sql)

    # -- post-conditions --------------------------------------------------------
    def assert_legacy_contained(self, label, restart_counts=None):
        if restart_counts:
            self.expected_restart = {**getattr(self, 'expected_restart', {}), **restart_counts}
        expected = getattr(self, 'expected_restart', {})
        for role in ROLES:
            data = self.inspect(self.legacy[role])
            labels = data['Config']['Labels']
            self.check(not data['State']['Running'] and data['HostConfig']['RestartPolicy']['Name'] == 'no'
                       and data['RestartCount'] == expected.get(role, 0) and data['Id'] == self.legacy[role]
                       and (COMPOSE_PROJECT in labels) == (role != 'broadcast-worker'), 'legacy-not-contained')
        self.checks.append(label)

    def assert_promoted(self):
        journal = self.journal()
        ids = [e for e in journal if e.get('step') == 'candidate:create' and e['kind'] == 'done'][-1]['ids']
        for role in ROLES:
            data = self.inspect(ids[role])
            self.check(data['State']['Running'] and data['HostConfig']['RestartPolicy']['Name'] == 'always'
                       and data['Config']['Labels'].get(COMPOSE_PROJECT) == self.candidate_project
                       and data['Image'] == self.images['candidate'], 'candidate-not-promoted')
        root = self.dir / 'release-root'
        current = root / 'current'
        self.check(current.is_symlink() and current.resolve() == (root / 'releases' / CANDIDATE_SHA).resolve()
                   and (current / 'deploy' / 'check_backend_schema.py').is_file()
                   and not (current / 'deploy' / '.env').exists(), 'layout')
        self.check(self.edge_get('/health') == 200, 'candidate-edge')
        self.assert_legacy_contained('legacy-preserved-stopped-restart-no-same-ids-compose-labels-intact')
        code, out = self.controller('resume-legacy', '--confirm', 'any')
        self.check(code == 3 and out.get('code') == 'post-ddl', 'legacy-resume-after-ddl')
        self.checks += ['candidate-promoted-restart-always-current-symlink-layout-without-private-config',
                        'post-ddl-legacy-resume-refused']

    def collect_owned(self):
        """Ledger additions from the controller's journal (jobs, candidate) before cleanup."""
        for event in self.journal():
            if event['kind'] == 'job' and event['id'] not in self.created['containers']:
                self.created['containers'].append(event['id'])
            if event['kind'] == 'done' and event.get('step') == 'candidate:create':
                for identifier in event['ids'].values():
                    if identifier not in self.created['containers']:
                        self.created['containers'].append(identifier)

    def cleanup(self):
        self.collect_owned()
        unprefixed = 0
        for identifier in self.created['containers']:
            try:
                name = self.inspect(identifier).get('Name', '').lstrip('/')
            except Refused:
                continue  # already gone; the ledger cleanup below reports what remains
            unprefixed += not name.startswith(self.prefix + '-')
        result = super().cleanup()
        result['unprefixed_names'] = unprefixed
        if unprefixed:
            result['status'] = 'incomplete'
        for tag in reversed(self.created['tags']):
            try:
                self.docker('image', 'rm', tag)  # untag only; the image ID stays
            except Refused:
                result['errors'].append(dict(kind='tag', code='rm-failed'))
        try:
            remaining = self.docker('ps', '-aq', '--filter', f'label={OWNER_LABEL}={self.run_id}').split()
            networks = self.docker('network', 'ls', '-q', '--filter', f'label={OWNER_LABEL}={self.run_id}').split()
        except Refused:
            remaining, networks = ['unverifiable'], []
        result['label_listing'] = dict(containers=len(remaining), networks=len(networks))
        if remaining or networks or result['errors']:
            result['status'] = 'incomplete'
        return result


# -- reference catalogue (independent of the target) ----------------------
def reference_catalog(fixture):
    """124 active migrations of the candidate SHA, from Git blobs, in a separate owned cluster."""
    files = git_tree(fixture.repo, CANDIDATE_SHA, ('backend/migrations', 'backend/scripts/migrate.py'),
                     re.compile(r'backend/migrations/[^/]+\.sql|backend/scripts/migrate\.py'))
    from initial_transition import migration_manifest
    sql = {p.split('/', 2)[2]: b for p, b in files.items() if p.endswith('.sql')}
    order = migration_manifest(files['backend/scripts/migrate.py'], sql)
    baseline = dict(migrate=files['backend/scripts/migrate.py'].decode(), selected=order,
                    sql={n: sql[n].decode() for n in order})
    digest, chunks = bundle_args(baseline)
    fixture.guard_local()
    labels = ['--label', f'{OWNER_LABEL}={fixture.run_id}', '--label', f'{SCOPE_LABEL}={SCOPE}']
    fixture.network = fixture._record('networks', fixture.docker('network', 'create', '--internal', *labels,
                                                                 f'{fixture.prefix}-app').strip())
    fixture.start_postgres()
    probe = fixture.legacy_run('migrate', ['-I', '-B', '-c', MIGRATE_PROBE, DSN, digest, *chunks],
                               image=fixture.images['candidate'], user='10001:10001', workdir='/app')
    result = json.loads(fixture.finish(probe, 900, 'reference-migrate'))
    fixture.check(result.get('ok') is True and result.get('applied') == len(order) == 124, 'reference-migrate')
    module = base64.b64encode(zlib.compress(files_for_catalog(fixture), 9)).decode()
    probe = fixture.legacy_run('catalog', ['-I', '-c', CATALOG_PROBE, DSN, module],
                               image=fixture.images['candidate'], user='10001:10001', workdir='/app')
    return json.loads(fixture.finish(probe, 300, 'reference-catalog'))


def files_for_catalog(fixture):
    blob = git_tree(fixture.repo, CANDIDATE_SHA, ('deploy/schema_compatibility.py',),
                    re.compile(r'deploy/schema_compatibility\.py'))
    return blob['deploy/schema_compatibility.py']


def runner_status(self, argv):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return -1, ''
    return done.returncode, done.stdout


Fixture.runner_status = runner_status


COMPLETE_SUITE = ('main', 'pre-ddl', 'post-ddl', 'broadcast')


def run_fixture(name, function, gates, mirror, args, images, catalog, workdir, report):
    fixture = Fixture(name, repo=args.repo, images=images, gates=gates, workdir=workdir)
    entry = report['fixtures'][name] = dict(run_id=fixture.run_id, config_mirror=mirror, gates=gates, status='fail')
    t0 = time.monotonic()
    try:
        fixture.build(catalog)
        function(fixture)
        entry.update(status='pass', reason=None)
    except Refused as exc:
        entry['reason'] = str(exc)
    except (subprocess.TimeoutExpired, ValueError, KeyError, TypeError, IndexError, OSError) as exc:
        entry['reason'] = 'unexpected:' + type(exc).__name__
    except KeyboardInterrupt:
        entry['reason'] = 'interrupted'
        raise
    finally:
        journal = fixture.journal()
        entry.update(checks=fixture.checks, observed=fixture.observed, timings=fixture.timings,
                     phases=[e['name'] for e in journal if e['kind'] == 'phase'], journal_events=len(journal),
                     refusals=[e['code'] for e in journal if e['kind'] == 'refused'],
                     contained_epochs=len([e for e in journal if e['kind'] == 'candidate-contained']),
                     seconds=round(time.monotonic() - t0, 1), cleanup=fixture.cleanup())


def main(argv=None):
    from rehearse_initial_transition_scenarios import FIXTURES
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('run')
    command.add_argument('--repo', type=Path, required=True)
    command.add_argument('--report', type=Path, required=True)
    command.add_argument('--fixtures', default=','.join(COMPLETE_SUITE))
    command.add_argument('--legacy-image', default=DEFAULT_IMAGES['legacy'])
    command.add_argument('--redis-image', default=DEFAULT_IMAGES['redis'])
    command.add_argument('--postgres-image', default=DEFAULT_IMAGES['postgres'])
    command.add_argument('--candidate-image', default=CANDIDATE_IMAGE)
    args = parser.parse_args(argv)
    selection = [n for n in args.fixtures.split(',') if n]
    if not selection or any(n not in FIXTURES for n in selection) or len(selection) != len(set(selection)):
        parser.error('unknown or repeated fixture')
    images = dict(legacy=args.legacy_image, redis=args.redis_image, postgres=args.postgres_image,
                  candidate=args.candidate_image)
    complete = tuple(selection) == COMPLETE_SUITE
    report = dict(kind='synthetic-initial-legacy-transition-integrated-rehearsal', status='fail',
                  production_ready=False, legacy_sha=LEGACY_SHA, candidate_sha=CANDIDATE_SHA, images=images,
                  selection=selection, complete_suite=complete,
                  candidate_image_note='derivada local NAO oficial (camadas de 8fbc14c5; app/lock/migrations/runner '
                                       'do HEAD; README de migrations ausente nao afeta o manifesto SQL)',
                  not_proven=NOT_PROVEN, fixtures={})
    workdir = Path(tempfile.mkdtemp(prefix='pastorai-transition-rehearsal-'))
    started = time.monotonic()
    try:
        reference = Fixture('reference', repo=args.repo, images=images, gates={}, workdir=workdir)
        entry = report['fixtures']['reference'] = dict(run_id=reference.run_id, status='fail')
        catalog = None
        try:
            catalog = reference_catalog(reference)
            entry.update(status='pass', catalog_kinds=len(catalog))
        except Refused as exc:
            entry['reason'] = str(exc)
        finally:
            entry['cleanup'] = reference.cleanup()
        if catalog is not None:
            for name in selection:
                function, gates, mirror = FIXTURES[name]
                run_fixture(name, function, gates, mirror, args, images, catalog, workdir, report)
    except KeyboardInterrupt:
        report['reason'] = 'interrupted'
    finally:
        entries = report['fixtures'].values()
        clean = bool(entries) and all(e.get('cleanup', {}).get('status') == 'clean' for e in entries)
        passed = bool(entries) and all(e['status'] == 'pass' for e in entries)
        covered = set(report['fixtures']) == {'reference', *selection}
        # PASS only for the complete integrated suite + reference, every cleanup clean.
        report['status'] = 'pass' if passed and clean and covered and complete else (
            'partial-pass' if passed and clean and covered else 'fail')
        report['cleanup_all_clean'] = clean
        report['seconds'] = round(time.monotonic() - started, 1)
        report['phases_expected'] = list(PHASES)
        args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
