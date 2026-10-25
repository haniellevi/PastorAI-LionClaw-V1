"""Docker/PostgreSQL/Redis operations of the initial legacy -> current transition.

Only this module talks to Docker. The controller in ``initial_transition.py``
calls the narrow ``DockerOps`` interface below, so its state machine can be
exercised with an in-memory double. Every refusal is a fixed code: no command,
output, DSN or row content leaves this module in an exception.

Scope is local and synthetic: the endpoint must be the local Unix socket and no
``DOCKER_*``/``COMPOSE_*`` override is inherited. Observation SQL/Redis runs by
``docker exec`` in the owned support containers; anything that executes product
code (migrations, checker, reconciliation, preflight, readiness) runs in a job
container created from the candidate image, never ``--rm``, restart ``no``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import zlib

SHA = re.compile(r'[0-9a-f]{40}')
IMAGE_ID = re.compile(r'sha256:[0-9a-f]{64}')
RESOURCE_ID = re.compile(r'[0-9a-f]{64}')
LOCAL_DOCKER = re.compile(r'unix:///var/run/docker\.sock|unix:///run/user/[0-9]+/docker\.sock')
SAFE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')
MIGRATION = re.compile(r'(?:[0-9]{4}|[0-9]{8}_[0-9]{6})_[A-Za-z0-9_]+\.sql')
MESSAGE_ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}')
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
OWNER_LABEL = 'pastorai.synthetic.owner'
ROLE_LABEL = 'pastorai.synthetic.role'
SCOPE_LABEL = 'pastorai.scope'
SCOPE = 'dev-sintetico'
COMPOSE_PROJECT = 'com.docker.compose.project'
COMPOSE_SERVICE = 'com.docker.compose.service'
REVISION_LABEL = 'org.opencontainers.image.revision'
GATES = ('ALLOW_REAL_SENDS', 'ASAAS_BILLING_ENABLED', 'BREVO_SEND_MODE', 'BROADCAST_ASYNC_ENABLED')
CHUNK = 96_000
# Read-only observers over the owned container's local socket (controller and
# rehearsal). Any other local session, or any remote one from an unexpected IP,
# is a fifth writer.
RECONCILE_ACTION = 'team_pessoa_reconciliar_duplicidade'  # backend/app/services/team_pessoa.py
DSN = re.compile(r'postgresql://([a-z_][a-z0-9_]*):[A-Za-z0-9_.-]+@postgres:5432/([a-z_][a-z0-9_]*)')
SUPPORT_ALIASES = {'postgres': 'postgres', 'redis': 'redis', 'evolution': 'evolution-api'}
OBSERVER_APP = 'pastorai-transition-observer'
OBSERVER_APPS = frozenset({OBSERVER_APP, 'pastorai-rehearsal-observer'})


class Refused(RuntimeError):
    """Sanitized refusal; ``str(exc)`` is a fixed code."""


def require(condition, code):
    if not condition:
        raise Refused(code)


def bundle(source: bytes):
    """Compressed source in argv chunks (no host mount) and its digest."""
    blob = zlib.compress(source, 9)
    text = base64.b64encode(blob).decode('ascii')
    return hashlib.sha256(blob).hexdigest(), [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or ['']


# Executes one reviewed script (Git blob of the candidate SHA) as if it lived at
# ``target`` inside the image, so its sibling imports resolve to the image's
# own verified files (``/app/scripts/migrate.py``, ``/app/app``).
RUN_SCRIPT = r'''
import base64, hashlib, os, sys, zlib
target, digest, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
blob = base64.b64decode(''.join(sys.argv[4:4 + count]))
if hashlib.sha256(blob).hexdigest() != digest:
    sys.exit(97)
sys.argv = [target] + sys.argv[4 + count:]
sys.path.insert(0, os.path.dirname(target))
code = compile(zlib.decompress(blob).decode('utf-8'), target, 'exec')
exec(code, {'__name__': '__main__', '__file__': target, '__builtins__': __builtins__})
'''

READY_PROBE = r'''
import json, sys, time, urllib.error, urllib.request
url, limit = sys.argv[1], time.monotonic() + float(sys.argv[2])
last = {'status': None, 'body': None}
while time.monotonic() < limit:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            last = {'status': response.status, 'body': json.loads(response.read() or b'null')}
    except urllib.error.HTTPError as exc:
        last = {'status': exc.code, 'body': None}
    except (OSError, ValueError):
        last = {'status': None, 'body': None}
    if last['status'] == 200 and (sys.argv[3] == 'any' or (last['body'] or {}).get('status') == sys.argv[3]):
        break
    time.sleep(0.5)
print(json.dumps(last, sort_keys=True))
'''

# Row digests per public table via query_to_xml (dynamic SQL without functions).
SNAPSHOT_SQL = (
    "select coalesce(json_object_agg(c.relname, md5(coalesce((xpath('/row/d/text()', query_to_xml(format("
    "'select string_agg(t::text, %L order by t::text) as d from public.%I t', E'\\n', c.relname), "
    "false, true, '')))[1]::text, ''))), '{}') from pg_class c join pg_namespace n on n.oid = c.relnamespace "
    "where n.nspname = 'public' and c.relkind in ('r', 'p')"
)
# Persistent keys only (no TTL): queues/backlog and durable state. Keys with a
# TTL (heartbeats, processed markers) expire without any writer and are not
# part of the stability proof: they are excluded, never compared.
REDIS_SNAPSHOT = r'''
local out = {}
for _, k in ipairs(redis.call('KEYS', '*')) do
  if redis.call('PTTL', k) == -1 then
  local t = redis.call('TYPE', k).ok
  local v
  if t == 'string' then v = redis.call('GET', k)
  elseif t == 'list' then v = table.concat(redis.call('LRANGE', k, 0, -1), '\n')
  elseif t == 'set' then local m = redis.call('SMEMBERS', k); table.sort(m); v = table.concat(m, '\n')
  elseif t == 'hash' then local m = redis.call('HGETALL', k); local p = {}
    for i = 1, #m, 2 do table.insert(p, m[i] .. '=' .. m[i + 1]) end; table.sort(p); v = table.concat(p, '\n')
  elseif t == 'zset' then v = table.concat(redis.call('ZRANGE', k, 0, -1, 'WITHSCORES'), '\n')
  else v = '?' end
  table.insert(out, k .. '\t' .. t .. '\t' .. redis.sha1hex(v))
  end
end
return out
'''
ZSET_DIGEST = ("local o = {} local m = redis.call('ZRANGE', KEYS[1], 0, -1, 'WITHSCORES') "
               "for i = 1, #m, 2 do table.insert(o, redis.sha1hex(m[i])) table.insert(o, m[i + 1]) end return o")
VOLATILE_COUNT = ("local n = 0 for _, k in ipairs(redis.call('KEYS', '*')) do "
                  "if redis.call('PTTL', k) ~= -1 then n = n + 1 end end return n")
LIST_DIGEST = ("local o = {} for _, v in ipairs(redis.call('LRANGE', KEYS[1], 0, -1)) do "
               "table.insert(o, redis.sha1hex(v)) end return o")
SESSIONS_SQL = (
    "select coalesce(json_agg(json_build_object('addr', host(client_addr), 'app', application_name, "
    "'state', state, 'wait', wait_event_type) order by pid), '[]') from pg_stat_activity "
    "where backend_type = 'client backend' and pid <> pg_backend_pid()"
)
INVALID_INDEX_SQL = (
    "select coalesce(json_agg(c.relname order by c.relname), '[]') from pg_index i "
    "join pg_class c on c.oid = i.indexrelid join pg_namespace n on n.oid = c.relnamespace "
    "where n.nspname = 'public' and not (i.indisvalid and i.indisready)"
)
PROGRESS_SQL = (
    "select coalesce(json_agg(a.application_name), '[]') from pg_stat_progress_create_index p "
    "join pg_stat_activity a on a.pid = p.pid"
)
# The two July backfills, as counts of the runbook's read-only candidate queries.
BACKFILL_SQL = r'''
select json_build_object('membro_por_vinculo', (select count(*) from public.pessoas p
  where (p.tipo is null or p.tipo::text in ('contato','visitante'))
    and exists (select 1 from public.celula_membro cm
                where cm.pessoa_id = p.id and cm.igreja_id = p.igreja_id and cm.ativo is true)),
 'numero_atendimento', (with p as (
  select id, igreja_id, tipo, case when length(d) > 11 and left(d, 2) = '55' then substr(d, 3) else d end as d
  from (select id, igreja_id, tipo, regexp_replace(coalesce(telefone, ''), '\D', '', 'g') as d
        from public.pessoas) s),
 pn as (select *, case when length(d) = 10 then substr(d, 1, 2) || '9' || substr(d, 3) else d end as k from p),
 w as (select igreja_id, case when length(d) > 11 and left(d, 2) = '55' then substr(d, 3) else d end as d
       from (select igreja_id, regexp_replace(coalesce(numero, ''), '\D', '', 'g') as d
             from public.whatsapp_connections where numero is not null) s),
 wn as (select igreja_id, case when length(d) = 10 then substr(d, 1, 2) || '9' || substr(d, 3) else d end as k
        from w)
 select count(*) from pn p where p.tipo = 'membro' and p.k <> ''
   and not exists (select 1 from public.celula_membro cm
                   where cm.pessoa_id = p.id and cm.igreja_id = p.igreja_id and cm.ativo is true)
   and exists (select 1 from wn w where w.igreja_id = p.igreja_id and w.k = p.k)))
'''


def run(argv, *, input=None, timeout=120):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('DOCKER_', 'COMPOSE_'))}
    try:
        done = subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        done = None
    except OSError:
        raise Refused('docker-unavailable') from None
    if done is None:
        raise Refused('docker-timeout')  # outside except: no chained command/output
    return done.returncode, done.stdout


class DockerOps:
    """Real operations against owned synthetic resources named in the spec."""

    def __init__(self, spec, runner=run):
        self.spec, self.runner = spec, runner
        self.net = spec['network']['app']
        self.pg = spec['support']['postgres']
        self.redis_id = spec['support']['redis']

    # -- primitives -------------------------------------------------------
    def docker(self, *args, input=None, timeout=120, code='docker-step'):
        status, out = self.runner(['docker', *args], input=input, timeout=timeout)
        require(status == 0, code)
        return out

    def guard_local(self):
        require(not any(os.environ.get(n) for n in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY',
                                                    'DOCKER_CERT_PATH')), 'remote-docker')
        host = json.loads(self.docker('context', 'inspect'))[0]['Endpoints']['docker']['Host']
        require(LOCAL_DOCKER.fullmatch(host), 'remote-docker')

    def inspect(self, identifier):
        status, out = self.runner(['docker', 'inspect', identifier])
        if status:
            return None
        try:
            rows = json.loads(out)
        except ValueError:
            raise Refused('inspect-malformed') from None
        require(isinstance(rows, list) and len(rows) == 1, 'inspect-ambiguous')
        return rows[0]

    def image(self, image):
        status, out = self.runner(['docker', 'image', 'inspect', image])
        require(status == 0, 'image-not-local')
        row = json.loads(out)[0]
        require(row.get('Id') == image, 'image-not-local-immutable')
        return row

    def verify_topology(self):
        """Owned internal networks, owned support containers and an unhijacked DSN, before any SQL.

        The DSN must be exactly ``postgresql://<superuser>:<pw>@postgres:5432/<db>``
        and ``postgres``/``redis``/``evolution-api`` must resolve only to the
        owned support containers on the owned app network.
        """
        spec, run_id = self.spec, self.spec['run_id']
        db = spec['database']
        found = DSN.fullmatch(db.get('dsn', ''))
        require(found and found[1] == db['superuser'] and found[2] == db['name'], 'dsn-not-owned-alias')
        names = {}
        for key in ('app', 'edge'):
            row, _ = self.network_members(spec['network'][key])
            require(row.get('Id') == spec['network'][key] and row.get('Internal') is True
                    and (row.get('Labels') or {}).get(OWNER_LABEL) == run_id
                    and str(row.get('Name', '')).startswith(spec['prefix'] + '-'), 'network-not-owned-internal')
            names[key] = row['Name']
        for role, alias in SUPPORT_ALIASES.items():
            identifier = spec['support'][role]
            data = self.inspect(identifier)
            require(data and data.get('Id') == identifier, 'support-identity')
            labels = (data.get('Config') or {}).get('Labels') or {}
            networks = (data.get('NetworkSettings') or {}).get('Networks') or {}
            require(labels.get(OWNER_LABEL) == run_id and labels.get(ROLE_LABEL) == role
                    and data.get('Name', '').lstrip('/').startswith(spec['prefix'] + '-')
                    and (data.get('State') or {}).get('Running') and not host_exposed(data)
                    and set(networks) == {names['app']} and alias in aliases(networks[names['app']]),
                    'support-not-owned')
        _, members = self.network_members(spec['network']['app'])
        for identifier in members:
            data = self.inspect(identifier) or {}
            mine = {v for v in aliases(((data.get('NetworkSettings') or {}).get('Networks') or {})
                                       .get(names['app']) or {})}
            for role, alias in SUPPORT_ALIASES.items():
                require(alias not in mine or identifier == spec['support'][role], 'support-alias-hijack')

    def job_matches(self, data, *, image, args, env, network):
        """The container is exactly the intended job: image, command, env, network, isolation."""
        host = data.get('HostConfig') or {}
        current = env_map(data)
        return (data.get('Image') == image and data.get('Path') == 'python' and data.get('Args') == list(args)
                and all(current.get(k) == v for k, v in env.items())
                and (host.get('RestartPolicy') or {}).get('Name') == 'no' and host.get('NetworkMode') == network
                and host.get('ReadonlyRootfs') is True and host.get('AutoRemove') is False
                and not host_exposed(data))

    def index_exists(self, names):
        require(all(re.fullmatch(r'[a-z0-9_]{1,63}', n) for n in names), 'index-name')
        if not names:
            return []
        values = ','.join("'" + n + "'" for n in names)
        return self.psql_json("select coalesce(json_agg(c.relname order by c.relname), '[]') from pg_class c "
                              "join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'public' "
                              f"and c.relkind = 'i' and c.relname in ({values})")

    def owned_containers(self, run_id):
        out = self.docker('ps', '-aq', '--no-trunc', '--filter', f'label={OWNER_LABEL}={run_id}')
        return set(out.split())

    def network_members(self, network):
        row = json.loads(self.docker('network', 'inspect', network))[0]
        return row, set(row.get('Containers') or {})

    def update_restart(self, identifier, policy):
        require(policy in ('no', 'always'), 'restart-policy')
        self.docker('update', '--restart', policy, identifier)

    def signal(self, identifier):
        self.docker('kill', '--signal', 'SIGTERM', identifier)

    def start(self, identifier):
        self.docker('start', identifier)

    # -- observation in owned support containers ---------------------------
    def psql(self, sql, *, stdin=None):
        db = self.spec['database']
        args = ['exec', '-e', f'PGAPPNAME={OBSERVER_APP}', *(['-i'] if stdin is not None else []), self.pg,
                'psql', '-X', '-q', '-A', '-t',
                '-v', 'ON_ERROR_STOP=1', '-U', db['superuser'], '-d', db['name']]
        return self.docker(*args, *(['-c', sql] if stdin is None else ['-f', '-']), input=stdin,
                           code='psql').strip()

    def psql_json(self, sql):
        try:
            return json.loads(self.psql(sql))
        except ValueError:
            raise Refused('psql-output') from None

    def redis(self, *args, db=0):
        return self.docker('exec', self.redis_id, 'redis-cli', '-n', str(db), *args, code='redis').strip()

    def pg_sessions(self):
        return self.psql_json(SESSIONS_SQL)

    def redis_clients(self):
        clients = []
        for line in self.redis('CLIENT', 'LIST').splitlines():
            fields = dict(part.split('=', 1) for part in line.split() if '=' in part)
            addr = fields.get('addr', '')
            clients.append({'addr': addr.rsplit(':', 1)[0], 'db': fields.get('db'), 'cmd': fields.get('cmd')})
        return clients

    def ledger(self):
        return self.psql_json("select coalesce(json_agg(name order by name), '[]') from public.schema_migrations")

    def invalid_indexes(self):
        return self.psql_json(INVALID_INDEX_SQL)

    def index_builds(self):
        return self.psql_json(PROGRESS_SQL)

    def backfill_candidates(self):
        return self.psql_json(BACKFILL_SQL)

    def db_snapshot(self):
        return self.psql_json(SNAPSHOT_SQL)

    def redis_snapshot(self):
        lines = self.redis('EVAL', REDIS_SNAPSHOT, '0').splitlines()
        return dict(sorted((line.split('\t', 1)[0], line.split('\t', 1)[1]) for line in lines if '\t' in line))

    def redis_list(self, key):
        """SHA-1 of each item, in order; values never leave Redis."""
        require(re.fullmatch(r'[A-Za-z0-9:_-]+', key), 'redis-key')
        return self.redis('EVAL', LIST_DIGEST, '1', key).split()

    def redis_zset(self, key):
        """``[[sha1(member), score], ...]`` in score order; members never leave Redis."""
        require(re.fullmatch(r'[A-Za-z0-9:_-]+', key), 'redis-key')
        flat = self.redis('EVAL', ZSET_DIGEST, '1', key).split()
        return [[flat[i], flat[i + 1]] for i in range(0, len(flat) - 1, 2)]

    def redis_pttl(self, key):
        require(re.fullmatch(r'[A-Za-z0-9:_-]+', key), 'redis-key')
        value = self.redis('PTTL', key)
        require(value.lstrip('-').isdigit(), 'redis-output')
        return int(value)

    def redis_volatile_count(self):
        """Keys with a TTL: excluded from the snapshot (they expire without a writer); only counted."""
        return int(self.redis('EVAL', VOLATILE_COUNT, '0'))

    def redis_keys(self, prefix):
        require(re.fullmatch(r'[A-Za-z0-9:_-]+', prefix), 'redis-prefix')
        return sorted(self.redis('--scan', '--pattern', prefix + '*').split())

    def message_counts(self, ids):
        require(all(MESSAGE_ID.fullmatch(i) for i in ids), 'expect-format')
        values = ','.join("'" + i + "'" for i in ids) or "''"
        rows = self.psql_json("select coalesce(json_object_agg(provider_message_id, n), '{}') from (select "
                              f"provider_message_id, count(*) n from public.messages where provider_message_id "
                              f"in ({values}) group by 1) s")
        return {i: rows.get(i, 0) for i in ids}

    def delivery_states(self, ids):
        require(all(UUID.fullmatch(i) for i in ids), 'expect-format')
        values = ','.join("'" + i + "'" for i in ids) or "'00000000-0000-0000-0000-000000000000'"
        rows = self.psql_json("select coalesce(json_object_agg(id, status), '{}') from public.broadcast_entregas "
                              f"where id in ({values})")
        return {i: rows.get(i) for i in ids}

    def reconcile_scope(self, *, target, operation, operator, detail):
        """Digests and counts (never values) delimiting the ONE effect the reconciliation may have.

        Per-table digests; ``app_users`` without the corrected account; that
        account without ``pessoa_id`` (the only column the service changes);
        its current ``pessoa_id``; the audit log without this operation
        (``IS NOT TRUE``: rows of the same action without ``operation_id`` stay
        included); and, for this operation, the total of audit rows and of rows
        EXACTLY as the service writes them (actor, target, NULL email/name,
        complete ``detalhe``).
        """
        require(all(UUID.fullmatch(v) for v in (target, operation, operator)), 'reconcile-scope')
        require(isinstance(detail, dict) and all(isinstance(v, str) and re.fullmatch(r'[0-9a-z_-]{1,64}', v)
                                                 for v in detail.values()), 'reconcile-scope')
        expected = json.dumps(detail, sort_keys=True)
        rows = "md5(coalesce(string_agg(t::text, E'\\n' order by t::text), ''))"
        mine = f"(t.acao = '{RECONCILE_ACTION}' and t.detalhe->>'operation_id' = '{operation}')"
        exact = (f"{mine} is true and t.actor_id = '{operator}' and t.alvo_tipo = 'app_user' "
                 f"and t.alvo_id = '{target}' and t.actor_email is null and t.alvo_nome is null "
                 f"and t.detalhe = '{expected}'::jsonb")
        return self.psql_json(
            f"select json_build_object('tables', ({SNAPSHOT_SQL}), "
            f"'app_users_others', (select {rows} from public.app_users t where t.id <> '{target}'), "
            f"'target_row', (select md5((to_jsonb(t) - 'pessoa_id')::text) from public.app_users t "
            f"where t.id = '{target}'), "
            f"'target_pessoa', (select pessoa_id from public.app_users where id = '{target}'), "
            f"'audit_others', (select {rows} from public.platform_audit_log t where {mine} is not true), "
            f"'audit_op_total', (select count(*) from public.platform_audit_log t where {mine} is true), "
            f"'audit_op_exact', (select count(*) from public.platform_audit_log t where {exact}))")

    def duplicate_groups(self):
        return int(self.psql("select count(*) from (select 1 from public.app_users where pessoa_id is not null "
                             "group by igreja_id, pessoa_id having count(*) > 1) s"))

    # -- jobs (candidate image, product code) -------------------------------
    def job_find(self, name):
        out = self.docker('ps', '-aq', '--no-trunc', '--filter', f'name=^/{name}$')
        return out.split()

    def job_create(self, *, name, kind, image, args, env, stdin=False, network):
        require(SAFE_NAME.fullmatch(name), 'job-name')
        require(network == 'none' or network in self.spec['network'].values(), 'job-network')
        flags = [p for key, value in sorted(env.items()) for p in ('--env', f'{key}={value}')]
        labels = ['--label', f'{OWNER_LABEL}={self.spec["run_id"]}', '--label', f'{ROLE_LABEL}=job-{kind}',
                  '--label', f'{SCOPE_LABEL}={SCOPE}', '--label', f'pastorai.transition.job={name}']
        identifier = self.docker(
            'create', '--name', name, '--restart', 'no', '--pull', 'never',
            '--network', network, *(['-i'] if stdin else []),
            '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--pids-limit', '256', '--no-healthcheck', *labels, *flags,
            '--entrypoint', 'python', image, *args).strip()
        require(RESOURCE_ID.fullmatch(identifier), 'job-create')
        return identifier

    def job_start(self, identifier, *, input=None, timeout=120):
        if input is None:
            self.docker('start', identifier)
            return None
        status, out = self.runner(['docker', 'start', '-a', '-i', identifier], input=input, timeout=timeout)
        return status, out

    def job_logs(self, identifier):
        return self.docker('logs', identifier)

    def script_args(self, target, source, extra=()):
        digest, chunks = bundle(source)
        return ['-I', '-c', RUN_SCRIPT, target, digest, str(len(chunks)), *chunks, *extra]

    # -- compose (candidate project only; never the legacy project) ---------
    def compose_create(self, project, compose_file):
        require(SAFE_NAME.fullmatch(project), 'compose-project')
        self.docker('compose', '--project-name', project, '--file', compose_file, 'up', '--no-start',
                    '--no-build', '--pull', 'never', timeout=180, code='compose-create')

    def compose_ids(self, project):
        out = self.docker('ps', '-aq', '--no-trunc', '--filter', f'label={COMPOSE_PROJECT}={project}')
        found = {}
        for identifier in out.split():
            data = self.inspect(identifier) or {}
            service = ((data.get('Config') or {}).get('Labels') or {}).get(COMPOSE_SERVICE)
            require(service and service not in found, 'compose-ambiguous')
            found[service] = identifier
        return found


def env_map(data):
    entries = (data.get('Config') or {}).get('Env') or []
    env = dict(item.split('=', 1) for item in entries if '=' in item)
    require(len(env) == len(entries), 'duplicate-env')
    return env


def gates_of(data):
    env = env_map(data)
    return {name: env.get(name) for name in GATES}


def aliases(endpoint):
    return set(endpoint.get('Aliases') or []) | set(endpoint.get('DNSNames') or [])


def ip_of(data, network):
    networks = (data.get('NetworkSettings') or {}).get('Networks') or {}
    for value in networks.values():
        if value.get('NetworkID') == network:
            return value.get('IPAddress') or None
    return None


def host_exposed(data):
    host = data.get('HostConfig') or {}
    ports = (data.get('NetworkSettings') or {}).get('Ports') or {}
    return bool(host.get('PortBindings') or host.get('PublishAllPorts') or host.get('Privileged')
                or host.get('Binds') or any(ports.values())
                or any('docker.sock' in str(m.get('Source', '')) or m.get('Type') == 'bind'
                       for m in data.get('Mounts') or []))
