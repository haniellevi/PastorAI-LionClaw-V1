#!/usr/bin/env python3
"""Ensaio sintético LOCAL: SIGTERM durante ingestão REAL do queue-worker legado.

``run --repo R --report P [--legacy-image/--redis-image/--postgres-image sha256:...]``

Reusa ``rehearse_legacy_queue`` (fonte Git exata de ``07a3f4d``, runtime do
lock, guarda de Docker local, ledger e limpeza por posse). Numa rede
``--internal`` própria, sem portas nem montagens do host, sobe Redis e Postgres
efêmeros (tmpfs), aplica com o ``cmd_apply`` ATUAL de ``backend/scripts/migrate.py``
só as migrations ativas anteriores a ``20261015`` (menos quatro sabidamente
ausentes), com papéis Supabase reais, ACL padrão e ledger, e então roda
``python -m app.workers.queue_worker`` sem mock, com gates fechados, lista de
piloto vazia e provedor em loopback morto.

Barreira: uma conexão de probe segura o advisory lock real
``_provider_message_lock_key(A, msgid)``; com o worker comprovadamente
esperando nesse lock (``pg_locks``) e com o claim de processamento no Redis,
o worker recebe SIGTERM. Exige processo vivo e zero mensagens durante a
barreira, libera em bem menos que o limite de progresso de 60 s e prova: saída
0, heartbeat ``stopped``, registro e lease removidos, ACK sem retry/dead-letter
e exatamente uma mensagem/pessoa/conversa no tenant resolvido pela instância
(não pelo ``igreja_id`` forjado), consentimento pelo trigger e tenant B
intacto. Reinício: o mesmo evento é descartado pelo marcador Redis e, sem o
marcador, pela deduplicação do Postgres. Probe RLS separado: papel
``authenticated`` com GUC de A lê e insere no próprio tenant (com rollback), mas
não lê B e a escrita em B é recusada por RLS (SQLSTATE 42501); o bootstrap das
migrations oficiais é preservado e comparado por digest.

Não prova turno completo do agente, efeitos de provedor, pós-DDL nem
produção: ``production_ready=false``.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import re
import sys
import zlib
from pathlib import Path

from rehearse_legacy_containment import IMAGE_ID, OWNER_LABEL, ROLE_LABEL, SCOPE, SCOPE_LABEL, USER, Refused
from rehearse_legacy_queue import (
    ALIVE, ENTRY, GRACE_S, HEARTBEAT, LEASE, LEGACY_SHA, PROCESSING, QUEUE, READY_S, REGISTRY,
    SOURCE_ROOT, SURVIVE_S, SYNTHETIC_ENV, WORKER, QueueRehearsal, legacy_sources, manifest, manifest_digest,
)

DEFAULT_IMAGES = dict(
    legacy='sha256:34083a4f8d5a412da4c900f8a6b6ebbe08ea0f0ff587d2fc9dad1a42071a6562',
    redis='sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf',
    postgres='sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929',
)
# -- baseline de schema ----------------------------------------------------
CUTOFF = '20261015'
KNOWN_MISSING = frozenset({
    '20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql',
    '20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql',
    '20260925_183811_preserve_platform_admins_on_tenant_deletion.sql',
    '20260926_120446_platform_jev_settings.sql',
})
EXPECTED_ACTIVE = 124   # total de migration_files() atual
EXPECTED_SELECTED = 78
# Prefixo de 4 dígitos (legado 0001_...) ou de data com 8 dígitos; nada mais.
MIGRATION_NAME = re.compile(r'(?:[0-9]{4}|[0-9]{8})_[A-Za-z0-9_.-]+\.sql')
# As migrations oficiais 0005 (seed) e 0007 deixam este bootstrap; é preservado, nunca apagado.
BOOTSTRAP_COUNTS = dict(igrejas=1, pessoas=1, conversations=0, messages=0, connections=1)
SEEDED_COUNTS = dict(igrejas=3, pessoas=2, conversations=0, messages=0, connections=3)
CHUNK = 96_000          # < MAX_ARG_STRLEN (128 KiB) por argumento
MAX_BUNDLE = 1_500_000  # base64 total, abaixo de ARG_MAX
# -- Postgres efêmero (credenciais sintéticas e públicas) ------------------
PG_USER = '999:999'
PG_DB = 'synthetic'
PG_PASSWORD = 'synthetic-public-not-a-secret'
PG_ENV = {'PGDATA': '/data', 'POSTGRES_DB': PG_DB, 'POSTGRES_PASSWORD': PG_PASSWORD, 'POSTGRES_USER': 'postgres'}
PG_TMPFS = {
    '/data': 'rw,nosuid,nodev,size=1g,uid=999,gid=999,mode=0700',
    '/var/run/postgresql': 'rw,nosuid,nodev,size=8m,uid=999,gid=999,mode=0775',
    '/tmp': 'rw,noexec,nosuid,nodev,size=64m',
}
VOLUME_PATH = re.compile(r'/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*')
DSN = f'postgresql://postgres:{PG_PASSWORD}@postgres:5432/{PG_DB}'
ACTIVE_ENV = {**SYNTHETIC_ENV, 'DATABASE_URL': f'postgresql+psycopg2://postgres:{PG_PASSWORD}@postgres:5432/{PG_DB}'}
# -- dados sintéticos -----------------------------------------------------
TENANT_A = '00000000-0000-0000-0000-00000000000a'
TENANT_B = '00000000-0000-0000-0000-00000000000b'
INSTANCE_A = 'synthetic-active-a'
MESSAGE_ID = 'synthetic-active-message-1'
CONTACT = '5500000000011'
PAYLOAD = {
    'event': 'messages.upsert', 'instance': INSTANCE_A, 'sender': '5500000000001@s.whatsapp.net',
    'igreja_id': TENANT_B,  # forjado: o tenant real vem de whatsapp_connections.instance
    'data': {'key': {'id': MESSAGE_ID, 'remoteJid': CONTACT + '@s.whatsapp.net', 'fromMe': False},
             'pushName': 'Contato Sintético', 'message': {'conversation': 'Mensagem sintética'}},
}
PROCESSED = 'pastorai:processed:' + MESSAGE_ID
HELD = 'synthetic:active:held'
RELEASE = 'synthetic:active:release'
# -- prazos ---------------------------------------------------------------
PG_READY_S = 120
MIGRATE_S = 600
PROBE_S = 120
BARRIER_S = 60
HOLD_S = 3              # janela observada com SIGTERM entregue e lock retido
PROGRESS_BUDGET_S = 40  # < WORKER_PROGRESS_TIMEOUT_SECONDS (60) do legado
MARKER_SAMPLE_MAX_MS = 250  # amostra de PTTL mais lenta que isto é observação incerta
EXPIRY_TOLERANCE_MS = 10    # arredondamento de PTTL e deriva entre relógios
NOT_PROVEN = [
    'sigterm-apos-escritas-na-transacao (a barreira e o advisory lock, ANTES de Pessoa/Conversation/Message)',
    'turno-completo-do-agente (lista de piloto vazia)',
    'efeitos-de-provedor-evolution-e-midia',
    'compatibilidade-pos-ddl (schema >= 20261015 e as quatro ausentes nao aplicados)',
    'papeis-de-login-e-timeouts-de-producao (login sintetico postgres + promote real para authenticated)',
    'sigkill-ou-timeout-do-worker-real',
    'queda-do-redis-ou-do-postgres',
    'entrypoint-compose-e-supabase-de-producao',
    'integridade-de-wheels-sitecustomize-e-pth (so nome/versao das distribuicoes conferidos)',
    'producao',
]
RLS_EXPECTED = dict(current_user='authenticated', guc=TENANT_A, read_a=1, read_b=0, write_a='accepted',
                    read_a_after_rollback=1, write_b='42501', write_b_rls=True,
                    after_rollback_user='authenticated')


def lock_key(igreja_id, message_id):
    """Mesma fórmula de ``_provider_message_lock_key`` (conferida contra a real no probe)."""
    material = f'{igreja_id}:{message_id}'.encode('utf-8')
    return int.from_bytes(hashlib.sha256(material).digest()[:8], 'big', signed=True)


def lock_parts(key):
    """(classid, objid) de ``pg_locks`` para um advisory lock de um bigint."""
    unsigned = key & 0xFFFFFFFFFFFFFFFF
    return unsigned >> 32, unsigned & 0xFFFFFFFF


# -- baseline (só migrate.py + SQL selecionado, nunca o repo inteiro) ------
def load_migrate(repo):
    path = Path(repo) / 'backend' / 'scripts' / 'migrate.py'
    spec = importlib.util.spec_from_file_location('pastorai_current_migrate', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def select_baseline(repo, loader=load_migrate):
    """Seleção ativa do ``migration_files()`` atual, nomes < CUTOFF, menos as quatro ausentes."""
    migrate = loader(repo)
    directory = Path(repo) / 'backend' / 'migrations'
    active = list(migrate.migration_files(directory))
    eligible = [name for name in active if name < CUTOFF]
    if not KNOWN_MISSING <= set(eligible):
        raise Refused('baseline-known-missing-absent')
    selected = [name for name in eligible if name not in KNOWN_MISSING]
    if len(active) != EXPECTED_ACTIVE or len(selected) != EXPECTED_SELECTED:
        raise Refused('baseline-count')
    sql = {}
    for name in selected:
        path = directory / name
        if not MIGRATION_NAME.fullmatch(name) or path.is_symlink() or not path.is_file():
            raise Refused('baseline-file')
        sql[name] = path.read_text(encoding='utf-8')
    runner = Path(repo) / 'backend' / 'scripts' / 'migrate.py'
    if runner.is_symlink():
        raise Refused('baseline-file')
    return dict(active=len(active), selected=selected, sql=sql, migrate=runner.read_text(encoding='utf-8'))


def bundle_args(baseline):
    """Bundle comprimido em argumentos (sem montagem do host) e seu digest."""
    data = json.dumps(dict(migrate=baseline['migrate'], order=baseline['selected'], sql=baseline['sql']),
                      sort_keys=True).encode('utf-8')
    blob = zlib.compress(data, 9)
    text = base64.b64encode(blob).decode('ascii')
    if len(text) > MAX_BUNDLE:
        raise Refused('bundle-too-large')
    return hashlib.sha256(blob).hexdigest(), [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)]


def ingested_ok(state, b_snapshot):
    """Uma mensagem/pessoa/conversa em A, contador 1, consentimento do trigger, B intacto."""
    messages, people, conversations = state['messages'], state['pessoas_a'], state['conversations']
    if not (len(messages) == len(people) == len(conversations) == 1):
        return False
    message, person, conversation = messages[0], people[0], conversations[0]
    return (message == dict(igreja=TENANT_A, direcao='in', autor='contato', provider=MESSAGE_ID,
                            texto_ok=True, conversation=conversation['id'])
            and person['telefone'] == CONTACT and person['nome_ok'] is True
            and person['consentimento'] is True
            and conversation == dict(id=conversation['id'], igreja=TENANT_A, pessoa=person['id'], nao_lidas=1)
            and state['b'] == b_snapshot)


# -- código dos probes (imagem legada; nada montado do host) ---------------
MIGRATE_PROBE = r'''
import base64, contextlib, hashlib, importlib.util, io, json, pathlib, sys, zlib
import psycopg2
dsn, digest, blob = sys.argv[1], sys.argv[2], base64.b64decode(''.join(sys.argv[3:]))
out = {'ok': False, 'applied': 0}
def emit(**kw):
    out.update(kw)
    print(json.dumps(out, sort_keys=True))
    sys.exit(0)
if hashlib.sha256(blob).hexdigest() != digest:
    emit(stage='digest')
bundle = json.loads(zlib.decompress(blob))
root = pathlib.Path('/tmp/bundle')
(root / 'scripts').mkdir(parents=True)
(root / 'migrations').mkdir()
(root / 'scripts' / 'migrate.py').write_text(bundle['migrate'], encoding='utf-8')
for name, body in bundle['sql'].items():
    (root / 'migrations' / name).write_text(body, encoding='utf-8')
spec = importlib.util.spec_from_file_location('migrate', root / 'scripts' / 'migrate.py')
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)
files = migrate.migration_files()
if files != bundle['order']:
    emit(stage='selection')
conn = psycopg2.connect(dsn)
conn.autocommit = True
with conn.cursor() as cur:
    for role, bypass in (('anon', False), ('authenticated', False), ('service_role', True)):
        cur.execute(f"CREATE ROLE {role} NOLOGIN {'BYPASSRLS' if bypass else 'NOBYPASSRLS'}")
    for obj in ('TABLES', 'SEQUENCES', 'FUNCTIONS'):
        cur.execute('ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public '
                    f'GRANT ALL ON {obj} TO anon, authenticated, service_role')
    cur.execute('CREATE TABLE public.schema_migrations '
                '(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())')
conn.close()
for name in files:
    body = (root / 'migrations' / name).read_text(encoding='utf-8')
    concurrent = any('index concurrently' in line.lower() for line in body.splitlines()
                     if not line.lstrip().startswith('--'))
    connection = psycopg2.connect(dsn)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            migrate.cmd_apply(connection, name, transactional=not concurrent)
    except BaseException as exc:  # nome público do arquivo e classe; nunca a mensagem
        emit(stage='apply', failed=name, error_class=type(exc).__name__, sqlstate=getattr(exc, 'pgcode', None))
    finally:
        connection.close()
    out['applied'] += 1
emit(ok=True)
'''

ENQUEUE_PROBE = r'''
import json, sys
from app.domain.conversations import parse_message_event
from app.workers.queue_worker import WebhookQueue
payload = json.loads(sys.argv[1])
parsed = parse_message_event(payload)
if parsed is None or parsed.instance != sys.argv[2] or parsed.provider_message_id != sys.argv[3] or parsed.from_me:
    print('not-parsed')
else:
    WebhookQueue().enqueue(payload)
    print('enqueued')
'''

HOLDER_PROBE = r'''
import sys, time, uuid
import psycopg2
from app.workers.queue_worker import _build_redis, _provider_message_lock_key
dsn, igreja, message_id, held, release = sys.argv[1:6]
key = _provider_message_lock_key(uuid.UUID(igreja), message_id)
conn = psycopg2.connect(dsn)
conn.cursor().execute('SELECT pg_advisory_xact_lock(%s)', (key,))
redis = _build_redis()
redis.set(held, str(key), ex=300)
limit = time.monotonic() + 150
while redis.get(release) != '1':
    if time.monotonic() > limit:
        conn.rollback()
        print('timeout')
        sys.exit(3)
    time.sleep(0.05)
conn.rollback()
conn.close()
print('released %d' % key)
'''

RLS_PROBE = r'''
import json, sys, uuid
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.db.session import get_session_factory
from app.db.tenant_session import mark_cross_tenant, promote_to_tenant
a, b = sys.argv[1], sys.argv[2]
out = {}
session = get_session_factory()()
try:
    mark_cross_tenant(session, source='synthetic-rls-probe')
    promote_to_tenant(session, uuid.UUID(a), source='synthetic-rls-probe')
    scalar = lambda sql, **kw: session.execute(text(sql), kw).scalar_one()
    out['current_user'] = scalar('select current_user')
    out['guc'] = scalar("select current_setting('app.tenant_igreja_id', true)")
    out['read_a'] = scalar('select count(*) from pessoas where igreja_id = :t', t=a)
    out['read_b'] = scalar('select count(*) from pessoas where igreja_id = :t', t=b)
    insert = text("insert into pessoas (igreja_id, nome, telefone) values (:t, 'Sintetico controle', :f)")
    try:  # controle positivo: o mesmo papel/GUC escreve no próprio tenant
        session.execute(insert, {'t': a, 'f': '5500000000098'})
        out['write_a'] = 'accepted'
    except DBAPIError as exc:
        out['write_a'] = getattr(exc.orig, 'pgcode', None)
    session.rollback()
    out['read_a_after_rollback'] = scalar('select count(*) from pessoas where igreja_id = :t', t=a)
    session.rollback()
    try:
        session.execute(insert, {'t': b, 'f': '5500000000099'})
        out['write_b'] = 'accepted'
    except DBAPIError as exc:  # só código e booleano; nunca o texto do erro
        out['write_b'] = getattr(exc.orig, 'pgcode', None)
        diag = getattr(exc.orig, 'diag', None)
        out['write_b_rls'] = 'row-level security' in (getattr(diag, 'message_primary', None) or '')
    session.rollback()
    out['after_rollback_user'] = scalar('select current_user')
    session.rollback()
finally:
    session.close()
print(json.dumps(out, sort_keys=True))
'''

# -- SQL de observação (superusuário via socket do container próprio) ------
EMPTY_SQL = ("select json_build_object('igrejas', (select count(*) from igrejas), 'pessoas', "
             "(select count(*) from pessoas), 'conversations', (select count(*) from conversations), "
             "'messages', (select count(*) from messages), 'connections', "
             "(select count(*) from whatsapp_connections))")
SEED_SQL = (
    f"insert into igrejas (id, nome) values ('{TENANT_A}', 'Igreja Sintetica A'), "
    f"('{TENANT_B}', 'Igreja Sintetica B');"
    f"insert into whatsapp_connections (igreja_id, instance, numero) values "
    f"('{TENANT_A}', '{INSTANCE_A}', '5500000000001'), ('{TENANT_B}', 'synthetic-active-b', '5500000000002');"
    f"insert into pessoas (igreja_id, nome, telefone) values ('{TENANT_B}', 'Contato Sintetico B', '{CONTACT}');"
)
LEDGER_SQL = ("select json_build_object('ledger', (select coalesce(json_agg(name order by name), '[]') "
              "from public.schema_migrations), 'roles', (select json_object_agg(rolname, rolbypassrls) "
              "from pg_roles where rolname in ('anon', 'authenticated', 'service_role')), 'acl', "
              "(select coalesce(json_agg(distinct d.defaclobjtype), '[]') from pg_default_acl d join "
              "pg_namespace n on n.oid = d.defaclnamespace where n.nspname = 'public' "
              "and d.defaclrole = 'postgres'::regrole))")
STATE_SQL = (
    "select json_build_object("
    "'messages', (select coalesce(json_agg(json_build_object('igreja', igreja_id, 'direcao', direcao, "
    "'autor', autor, 'provider', provider_message_id, 'texto_ok', texto = U&'Mensagem sint\\00e9tica', "
    "'conversation', conversation_id)), '[]') from messages), "
    f"'pessoas_a', (select coalesce(json_agg(json_build_object('id', id, 'telefone', telefone, "
    f"'nome_ok', nome = U&'Contato Sint\\00e9tico', 'consentimento', consentimento)), '[]') "
    f"from pessoas where igreja_id = '{TENANT_A}'), "
    "'conversations', (select coalesce(json_agg(json_build_object('id', id, 'igreja', igreja_id, "
    "'pessoa', pessoa_id, 'nao_lidas', nao_lidas)), '[]') from conversations), "
    f"'b', (select coalesce(json_agg(row_to_json(p) order by p.id), '[]') from pessoas p "
    f"where p.igreja_id = '{TENANT_B}'), "
    # Bootstrap das migrations (fora de A/B): só digests ASCII, comparados do seed ao fim.
    + ", ".join(
        f"'bootstrap_{table}', (select md5(coalesce(json_agg(row_to_json(t) order by t.{key})::text, '')) "
        f"from {table} t where t.{tenant} not in ('{TENANT_A}', '{TENANT_B}'))"
        for table, key, tenant in (('igrejas', 'id', 'id'), ('pessoas', 'id', 'igreja_id'),
                                   ('whatsapp_connections', 'igreja_id', 'igreja_id')))
    + ")"
)
LOCKS_SQL = (
    "select coalesce(json_agg(json_build_object('granted', l.granted, 'addr', host(a.client_addr), "
    "'wait', a.wait_event)), '[]') from pg_locks l join pg_stat_activity a on a.pid = l.pid "
    f"where l.locktype = 'advisory' and l.database = (select oid from pg_database where datname = '{PG_DB}') "
    "and l.classid = {classid} and l.objid = {objid} and l.objsubid = 1"
)


class ActiveRehearsal(QueueRehearsal):
    def __init__(self, *, legacy_image, redis_image, postgres_image, files, baseline, **kwargs):
        super().__init__(legacy_image=legacy_image, redis_image=redis_image, files=files, **kwargs)
        if not IMAGE_ID.fullmatch(str(postgres_image or '')):
            raise Refused('image-not-local-immutable')
        self.images['postgres'] = postgres_image
        self.prefix = 'pastorai-synthetic-legacy-active-' + self.run_id[:12]
        self.baseline = baseline
        self.pg_volumes: set[str] = set()
        self.timings: dict[str, float] = {}

    # -- preflight e suporte ----------------------------------------------
    def preflight(self):
        super().preflight()
        volumes = set(self._image(self.images['postgres']).get('Volumes') or {})
        if not all(VOLUME_PATH.fullmatch(p) and '..' not in p.split('/') for p in volumes):
            raise Refused('postgres-image-volumes')
        self.pg_volumes = volumes  # cobertos por tmpfs: nenhum volume anônimo é criado
        self.checks.append('postgres-image-local-immutable')

    def create_support(self):
        super().create_support()
        tmpfs = dict(PG_TMPFS)
        for path in sorted(self.pg_volumes - set(tmpfs)):
            tmpfs[path] = 'rw,noexec,nosuid,nodev,size=1m,uid=999,gid=999,mode=0700'
        flags = [p for path, opts in sorted(tmpfs.items()) for p in ('--tmpfs', f'{path}:{opts}')]
        env = [p for name, value in sorted(PG_ENV.items()) for p in ('--env', f'{name}={value}')]
        self.ids['postgres'] = self._record('containers', self.docker(
            'run', '-d', '--pull', 'never', '--restart', 'no', '--network', self.network,
            '--network-alias', 'postgres', '--name', f'{self.prefix}-postgres',
            '--entrypoint', 'docker-entrypoint.sh', '--user', PG_USER, '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--pids-limit', '256', *flags,
            *self.labels('postgres'), *env, self.images['postgres'], 'postgres'))
        self._until(self._pg_ready, 'postgres-readiness', PG_READY_S)
        self._check_postgres()

    def _pg_ready(self):
        try:
            self.docker('exec', self.ids['postgres'], 'pg_isready', '-q', '-h', '127.0.0.1',
                        '-U', 'postgres', '-d', PG_DB)
            return True
        except Refused:
            return False

    def psql(self, sql):
        return self.docker('exec', self.ids['postgres'], 'psql', '-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1',
                           '-U', 'postgres', '-d', PG_DB, '-c', sql).strip()

    def psql_json(self, sql):
        return json.loads(self.psql(sql))

    def keys(self):
        return set(self.redis('KEYS', '*').split())

    # -- probes registrados -----------------------------------------------
    def spawn(self, role, python_args, env=ACTIVE_ENV):
        return self._record('containers', self.docker(
            *self._legacy_argv(role, self.network, env), *python_args))

    def collect(self, identifier, timeout, refusal):
        """Espera a saída sem o limite de 120 s do ``docker wait``; devolve a última linha."""
        limit = self.clock() + timeout
        try:
            while (state := self.inspect(identifier).get('State') or {}).get('Running'):
                if self.clock() >= limit:
                    raise Refused(refusal + '-timeout')
                self.sleep(0.5)
            output = self.docker('logs', identifier).strip().splitlines()
        finally:
            self.docker('rm', '-f', '-v', identifier)
        if state.get('ExitCode') != 0 or not output:
            raise Refused(refusal)
        return output[-1]

    def probe(self, role, python_args, refusal, timeout=PROBE_S):
        return self.collect(self.spawn(role, python_args), timeout, refusal)

    def ip(self, identifier):
        networks = (self.inspect(identifier).get('NetworkSettings') or {}).get('Networks') or {}
        address = (networks.get(self.prefix) or {}).get('IPAddress')
        if not address:
            raise Refused('network')
        return address

    # -- schema e seed ----------------------------------------------------
    def migrate_and_seed(self):
        digest, chunks = bundle_args(self.baseline)
        result = json.loads(self.probe('migrate', ['-I', '-B', '-c', MIGRATE_PROBE, DSN, digest, *chunks],
                                       'migrate-probe', MIGRATE_S))
        self.migration = {k: result.get(k) for k in ('ok', 'stage', 'applied', 'failed', 'error_class', 'sqlstate')}
        if result.get('ok') is not True or result.get('applied') != EXPECTED_SELECTED:
            raise Refused('migration-apply')
        found = self.psql_json(LEDGER_SQL)
        if found['ledger'] != self.baseline['selected']:
            raise Refused('migration-ledger')
        if found['roles'] != {'anon': False, 'authenticated': False, 'service_role': True}:
            raise Refused('supabase-roles')
        if not {'r', 'S', 'f'} <= set(found['acl']):
            raise Refused('default-acl')
        self.checks.append(f'current-cmd_apply-{EXPECTED_SELECTED}-active-migrations-before-{CUTOFF}-ledger-roles-acl')
        if self.psql_json(EMPTY_SQL) != BOOTSTRAP_COUNTS:
            raise Refused('unexpected-bootstrap')
        before = self.psql_json(STATE_SQL)
        self.psql(SEED_SQL)  # só INSERT; o bootstrap é preservado
        if self.psql_json(EMPTY_SQL) != SEEDED_COUNTS:
            raise Refused('seed')
        state = self.psql_json(STATE_SQL)
        if (state['messages'] or state['pessoas_a'] or state['conversations'] or len(state['b']) != 1
                or any(state[k] != before[k] for k in state if k.startswith('bootstrap_'))):
            raise Refused('seed')
        self.b_snapshot = state['b']
        self.bootstrap = {k: v for k, v in state.items() if k.startswith('bootstrap_')}
        self.checks.append('seed-two-tenants-instance-a-and-b-same-contact-in-b-bootstrap-preserved')

    # -- validação de conjunto ---------------------------------------------
    def _check_common(self, data, role, image):
        config, host = data.get('Config') or {}, data.get('HostConfig') or {}
        labels = config.get('Labels') or {}
        if (labels.get(OWNER_LABEL) != self.run_id or labels.get(ROLE_LABEL) != role
                or labels.get(SCOPE_LABEL) != SCOPE):
            raise Refused('ownership')
        if data.get('Id') != self.ids[role] or data.get('Image') != image:
            raise Refused('identity')
        ports = (data.get('NetworkSettings') or {}).get('Ports') or {}
        if (host.get('PortBindings') or host.get('PublishAllPorts') or host.get('Privileged')
                or host.get('Binds') or data.get('Mounts') or any(ports.values())
                or not host.get('ReadonlyRootfs')):
            raise Refused('host-exposure')
        networks = (data.get('NetworkSettings') or {}).get('Networks') or {}
        if host.get('NetworkMode') != self.network or set(networks) != {self.prefix}:
            raise Refused('network')
        if data.get('RestartCount', 0):
            raise Refused('unexpected-state')
        return config, host

    def _check_postgres(self):
        data = self.inspect(self.ids['postgres'])
        config, host = self._check_common(data, 'postgres', self.images['postgres'])
        if (config.get('Entrypoint') != ['docker-entrypoint.sh'] or config.get('Cmd') != ['postgres']
                or config.get('User') != PG_USER):
            raise Refused('entrypoint')
        env = dict(item.split('=', 1) for item in config.get('Env') or [] if '=' in item)
        if any(env.get(k) != v for k, v in PG_ENV.items()) or not set(PG_TMPFS) <= set(host.get('Tmpfs') or {}):
            raise Refused('postgres-config')
        if not (data.get('State') or {}).get('Running'):
            raise Refused('unexpected-state')

    def check_worker(self, *, running, extra=()):
        """Conjunto exato (Redis, Postgres, worker e probes esperados) e worker real com gates."""
        self.guard_local()
        owned = set(self.docker('ps', '-aq', '--no-trunc', '--filter', f'label={OWNER_LABEL}={self.run_id}').split())
        if owned != {self.ids['redis'], self.ids['postgres'], self.ids[WORKER], *extra}:
            raise Refused('unexpected-container')
        self._validate_one('redis', running=True)
        self._check_postgres()
        data = self.inspect(self.ids[WORKER])
        config, _ = self._check_common(data, WORKER, self.images['worker'])
        if (data.get('Path') != 'python' or data.get('Args') != ENTRY or config.get('Entrypoint') != ['python']
                or config.get('Cmd') != ENTRY or config.get('User') != USER
                or config.get('WorkingDir') != SOURCE_ROOT):
            raise Refused('entrypoint')
        env = dict(item.split('=', 1) for item in config.get('Env') or [] if '=' in item)
        if set(env) != self.image_env | set(ACTIVE_ENV) or any(env[k] != v for k, v in ACTIVE_ENV.items()):
            raise Refused('gate-config-changed')
        if bool((data.get('State') or {}).get('Running')) != running:
            raise Refused('unexpected-state')
        network = json.loads(self.docker('network', 'inspect', self.network))[0]
        if not network.get('Internal') or (network.get('Labels') or {}).get(OWNER_LABEL) != self.run_id:
            raise Refused('network')
        expected = {self.ids['redis'], self.ids['postgres'], *([self.ids[WORKER]] if running else []), *extra}
        if set(network.get('Containers') or {}) != expected:
            raise Refused('unexpected-container')

    # -- worker -----------------------------------------------------------
    def start_worker(self):
        self.ids[WORKER] = self._record('containers', self.docker(
            *self._legacy_argv(WORKER, self.network, ACTIVE_ENV)[:-1],
            '--name', f'{self.prefix}-{WORKER}', self.images['worker'], *ENTRY))

    def running(self):
        return bool((self.inspect(self.ids[WORKER]).get('State') or {}).get('Running'))

    def assert_stopped(self, residual):
        if self.redis('GET', HEARTBEAT) != 'stopped':
            raise Refused('heartbeat-not-stopped')
        if self.keys() != {HEARTBEAT, *residual}:
            raise Refused('not-deregistered-or-pending')
        self.check_worker(running=False)

    def stop_worker(self, residual=(PROCESSED,)):
        self.check_worker(running=True)
        self.docker('kill', '--signal', 'SIGTERM', self.ids[WORKER])
        self._await_exit(WORKER, GRACE_S)
        self.assert_stopped(residual)

    def enqueue(self):
        outcome = self.probe('enqueue', ['-c', ENQUEUE_PROBE, json.dumps(PAYLOAD), INSTANCE_A, MESSAGE_ID],
                             'enqueue-probe')
        if outcome != 'enqueued':
            raise Refused('payload-not-parsed')

    def claim_of(self, worker_id):
        """claim_id se o worker tem exatamente nosso envelope e o marcador ``processing`` dele."""
        items = self.redis('LRANGE', PROCESSING + worker_id, '0', '-1').splitlines()
        if len(items) != 1 or self.redis('LLEN', QUEUE) != '0':
            return None
        envelope = json.loads(items[0])
        claim = envelope.get('claim_id')
        if (envelope.get('payload') != PAYLOAD or envelope.get('attempts') != 0 or not claim
                or self.redis('GET', PROCESSED) != 'processing:' + claim):
            return None
        return claim

    def locks(self, classid, objid):
        rows = self.psql_json(LOCKS_SQL.format(classid=classid, objid=objid))
        return sorted((row['granted'], row['addr'] or '', '' if row['granted'] else row['wait'] or '')
                      for row in rows)

    def wait_barrier(self, worker_id, holder):
        """Worker esperando no advisory lock exato (pg_locks) com o claim real no Redis."""
        classid, objid = lock_parts(lock_key(TENANT_A, MESSAGE_ID))
        worker_ip, holder_ip = self.ip(self.ids[WORKER]), self.ip(holder)
        expected = sorted([(True, holder_ip, ''), (False, worker_ip, 'advisory')])
        limit = self.clock() + BARRIER_S
        while True:
            if not self.running():
                raise Refused('worker-exited-before-barrier')
            if self.psql('select count(*) from messages') != '0':
                raise Refused('ingested-through-barrier')
            claim = self.claim_of(worker_id)
            if claim and self.locks(classid, objid) == expected:
                return claim, (classid, objid, expected)
            if self.clock() >= limit:
                raise Refused('barrier-timeout')
            self.sleep(0.2)

    def drain(self, worker_id, refusal):
        """Espera o ACK: só heartbeat, registro, lease e marcador ``done`` sobram."""
        done = {HEARTBEAT, REGISTRY, LEASE + worker_id, PROCESSED}
        allowed = done | {QUEUE, PROCESSING + worker_id}
        limit = self.clock() + READY_S
        while (found := self.keys()) != done or self.redis('GET', PROCESSED) != 'done':
            if found - allowed:
                raise Refused('unexpected-queue-state')
            if self.clock() >= limit:
                raise Refused(refusal)
            self.sleep(0.2)
        if self.redis('GET', HEARTBEAT) not in ALIVE:
            raise Refused('heartbeat-not-alive')
        # Estado pós-ACK estável: nenhum retry/dead-letter tardio, lease e registro só deste worker.
        self.sleep(SURVIVE_S)
        if (self.keys() != done or self.redis('GET', PROCESSED) != 'done'
                or self.redis('GET', LEASE + worker_id) != worker_id
                or set(self.redis('SMEMBERS', REGISTRY).split()) != {worker_id}
                or self.redis('GET', HEARTBEAT) not in ALIVE):
            raise Refused('unstable-after-ack')
        self.check_worker(running=True)

    def marker_pttl(self):
        """PTTL do marcador; o legado sempre grava com EX, então sem TTL (-1) ou ausente (-2) é recusa."""
        value = self.redis('PTTL', PROCESSED)
        ttl = int(value) if value.lstrip('-').isdigit() else -2
        if ttl <= 0:
            raise Refused('marker-ttl')
        return ttl

    def marker_expiry_window(self):
        """Janela (ms, relógio monotônico) que contém a expiração absoluta do marcador."""
        start = self.clock()
        ttl = self.marker_pttl()
        end = self.clock()
        if (end - start) * 1000 > MARKER_SAMPLE_MAX_MS:
            raise Refused('marker-ttl-uncertain')
        return start * 1000 + ttl, end * 1000 + ttl


def expiry_renewed(before, after):
    """Expiração posterior à janela anterior = novo SET EX (independe do tempo do drain)."""
    return after[0] > before[1] + EXPIRY_TOLERANCE_MS


def rehearse(r):
    r.preflight()
    r.create_support()
    r.migrate_and_seed()
    r.start_worker()
    first = r.wait_ready(set())
    r.checks.append('real-entrypoint-ready-with-live-postgres')

    expected_key = lock_key(TENANT_A, MESSAGE_ID)
    holder = r.spawn('holder', ['-c', HOLDER_PROBE, DSN, TENANT_A, MESSAGE_ID, HELD, RELEASE])
    r._until(lambda: r.redis('GET', HELD) != '', 'holder-not-ready', PROBE_S)
    if r.redis('GET', HELD) != str(expected_key):
        raise Refused('lock-key-mismatch')
    r.checks.append('actual-_provider_message_lock_key-held-by-separate-connection')
    started = r.clock()  # o orçamento cobre enqueue, espera no lock, SIGTERM e janela observada
    r.enqueue()
    claim, (classid, objid, expected_locks) = r.wait_barrier(first, holder)
    r.checks.append('worker-waiting-on-exact-advisory-lock-with-redis-processing-claim')

    r.check_worker(running=True, extra={holder})
    r.docker('kill', '--signal', 'SIGTERM', r.ids[WORKER])
    signalled = r.clock()
    while r.clock() - signalled < HOLD_S:
        if not r.running():
            raise Refused('worker-exited-during-barrier')
        if r.psql('select count(*) from messages') != '0':
            raise Refused('ingested-through-barrier')
        if r.locks(classid, objid) != expected_locks or r.claim_of(first) != claim:
            raise Refused('barrier-lost')
        r.sleep(0.2)
    r.timings['barrier_s'] = round(r.clock() - started, 3)
    if r.timings['barrier_s'] >= PROGRESS_BUDGET_S:
        raise Refused('barrier-too-long')
    # Imediatamente antes de liberar: a lease ainda é do mesmo worker (sem fence nem recuperação).
    if r.redis('GET', LEASE + first) != first or r.claim_of(first) != claim:
        raise Refused('lease-lost-at-release')
    r.redis('SET', RELEASE, '1')
    released = r.clock()
    r.checks.append('sigterm-during-ingestion-worker-alive-zero-messages-while-held')
    if r.collect(holder, PROBE_S, 'holder-probe') != f'released {expected_key}':
        raise Refused('holder-release')
    r._await_exit(WORKER, GRACE_S)
    r.timings['exit_after_release_s'] = round(r.clock() - released, 3)
    if r.redis('DEL', RELEASE, HELD) != '2':
        raise Refused('synthetic-keys')
    r.assert_stopped({PROCESSED})
    if r.redis('GET', PROCESSED) != 'done':
        raise Refused('marker-not-done')
    state = r.psql_json(STATE_SQL)
    if not ingested_ok(state, r.b_snapshot) or any(state[k] != v for k, v in r.bootstrap.items()):
        raise Refused('ingestion-state')
    r.checks += ['released-under-progress-limit-exit-0-heartbeat-stopped-lease-registry-removed',
                 'acked-no-pending-retry-or-dead-letter-marker-done',
                 'one-message-person-conversation-in-instance-tenant-a-unread-1-consent-trigger',
                 'forged-payload-tenant-b-ignored-b-unchanged']

    r.docker('start', r.ids[WORKER])
    second = r.wait_ready({first})
    before = r.marker_expiry_window()
    r.enqueue()
    r.drain(second, 'redis-marker-duplicate-not-acked')
    if expiry_renewed(before, r.marker_expiry_window()):
        raise Refused('marker-rewritten')  # um novo SET EX renovaria a expiração: o gate Redis não segurou
    if r.psql_json(STATE_SQL) != state:
        raise Refused('redis-dedup-changed-db')
    r.checks.append('restart-same-event-dropped-by-redis-marker-ttl-not-renewed-counts-unchanged')
    if r.redis('GET', PROCESSED) != 'done' or r.redis('DEL', PROCESSED) != '1':
        raise Refused('marker-delete')
    r.enqueue()
    r.drain(second, 'postgres-duplicate-not-acked')
    if r.psql_json(STATE_SQL) != state:
        raise Refused('postgres-dedup-changed-db')
    r.checks.append('without-own-marker-same-event-deduplicated-by-postgres-counts-unchanged')
    r.stop_worker()
    r.checks.append('second-sigterm-exit-0-heartbeat-stopped-deregistered')

    rls = json.loads(r.probe('rls', ['-c', RLS_PROBE, TENANT_A, TENANT_B], 'rls-probe'))
    r.rls = rls
    if rls != RLS_EXPECTED:
        raise Refused('rls')
    if r.psql_json(STATE_SQL) != state:
        raise Refused('rls-probe-changed-db')
    r.check_worker(running=False)
    r.checks += ['actual-mark_cross_tenant-promote_to_tenant-authenticated-guc-a',
                 'same-tenant-read-and-insert-accepted-then-rolled-back',
                 'tenant-b-read-0-insert-42501-row-level-security',
                 'database-snapshot-unchanged-after-rls-rollbacks']


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
    report = dict(kind='synthetic-legacy-queue-active-ingestion-rehearsal', status='fail', production_ready=False,
                  legacy_sha=LEGACY_SHA, entrypoint='python ' + ' '.join(ENTRY), not_proven=NOT_PROVEN,
                  scope='worker legado real, Redis e Postgres efemeros, ingestao com SIGTERM; sem agente/provedor',
                  images=dict(legacy=args.legacy_image, redis=args.redis_image, postgres=args.postgres_image),
                  expected=dict(bootstrap=BOOTSTRAP_COUNTS, seeded=SEEDED_COUNTS, rls=RLS_EXPECTED),
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
        rehearsal = ActiveRehearsal(legacy_image=args.legacy_image, redis_image=args.redis_image,
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
                          migration=getattr(rehearsal, 'migration', None), rls=getattr(rehearsal, 'rls', None),
                          cleanup=rehearsal.cleanup())
            if report['cleanup']['status'] != 'clean' and report['status'] == 'pass':
                report.update(status='fail', reason='cleanup-incomplete')
        args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
