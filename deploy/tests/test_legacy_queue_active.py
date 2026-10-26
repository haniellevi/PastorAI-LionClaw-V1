"""Ensaio de ingestão ativa do queue-worker legado: partes puras e recusas, sem Docker real.

O ensaio físico (Postgres/Redis/worker reais) é ``deploy/rehearse_legacy_queue_active.py run``.
"""
import base64
import hashlib
import json
import sys
import uuid
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rehearse_legacy_containment as containment  # noqa: E402
import rehearse_legacy_queue_active as active  # noqa: E402

LEGACY = 'sha256:' + 'a' * 64
REDIS = 'sha256:' + 'b' * 64
PG = 'sha256:' + 'c' * 64
FILES = {'app/__init__.py': b'', 'app/workers/queue_worker.py': b'# legado\n',
         'requirements.lock': b'# --python-version 3.13\nredis==7.0.1\n'}


@pytest.fixture(autouse=True)
def local_docker(monkeypatch):
    for name in containment.REMOTE_ENV:
        monkeypatch.delenv(name, raising=False)


def _names(selected=active.EXPECTED_SELECTED, later=42):
    legacy = [f'{i:04d}_legacy.sql' for i in range(1, 8)]  # como 0001_..., 0005 seed, 0007
    early = legacy[:selected] + [f'20260101_{i:06d}_synthetic.sql' for i in range(max(selected - 7, 0))]
    tail = [f'20261015_{i:06d}_later.sql' for i in range(later)]
    return sorted([*early, *active.KNOWN_MISSING, *tail])


def _repo(tmp_path, names):
    migrations = tmp_path / 'backend' / 'migrations'
    migrations.mkdir(parents=True)
    (tmp_path / 'backend' / 'scripts').mkdir()
    (tmp_path / 'backend' / 'scripts' / 'migrate.py').write_text('# runner atual\n')
    for name in names:
        (migrations / name).write_text(f'-- {name}\nselect 1;\n')
    seen = []

    def loader(repo):
        def migration_files(directory):
            seen.append(directory)
            return list(names)
        return SimpleNamespace(migration_files=migration_files)
    return loader, seen


def test_lock_key_matches_legacy_formula_and_pg_locks_split():
    key = active.lock_key(active.TENANT_A, active.MESSAGE_ID)
    digest = hashlib.sha256(f'{uuid.UUID(active.TENANT_A)}:{active.MESSAGE_ID}'.encode()).digest()
    assert key == int.from_bytes(digest[:8], 'big', signed=True)
    classid, objid = active.lock_parts(key)
    assert 0 <= classid < 2 ** 32 and 0 <= objid < 2 ** 32
    rebuilt = (classid << 32) | objid
    assert rebuilt - (1 << 64 if rebuilt >= 1 << 63 else 0) == key


def test_baseline_uses_current_selection_excludes_known_missing(tmp_path):
    names = _names()
    loader, seen = _repo(tmp_path, names)
    baseline = active.select_baseline(tmp_path, loader=loader)
    assert seen == [tmp_path / 'backend' / 'migrations']
    assert baseline['active'] == len(names)
    assert len(baseline['selected']) == active.EXPECTED_SELECTED == len(baseline['sql'])
    assert not active.KNOWN_MISSING & set(baseline['selected'])
    assert all(name < active.CUTOFF for name in baseline['selected'])
    assert baseline['selected'] == sorted(baseline['selected'])
    assert baseline['migrate'] == '# runner atual\n'
    assert baseline['selected'][:7] == [f'{i:04d}_legacy.sql' for i in range(1, 8)]


@pytest.mark.parametrize('bad', ['001_short.sql', '12345_odd.sql', '0001-dash.sql', '0001_x.sql.bak'])
def test_baseline_name_prefix_is_four_or_eight_digits_only(tmp_path, bad):
    names = _names()
    names[names.index('0002_legacy.sql')] = bad
    loader, _ = _repo(tmp_path, sorted(names))
    with pytest.raises(containment.Refused, match='baseline-file'):
        active.select_baseline(tmp_path, loader=loader)


@pytest.mark.parametrize('mutate, code', [
    (lambda names: [n for n in names if n not in active.KNOWN_MISSING], 'baseline-known-missing-absent'),
    (lambda names: names[1:], 'baseline-count'),
    (lambda names: sorted([*names, '20261014_000000_extra.sql']), 'baseline-count'),
])
def test_baseline_refuses_drift(tmp_path, mutate, code):
    loader, _ = _repo(tmp_path, mutate(_names()))
    with pytest.raises(containment.Refused, match=code):
        active.select_baseline(tmp_path, loader=loader)


@pytest.mark.parametrize('later', [0, 1, 42, 45, 50])
def test_baseline_ignores_migrations_after_cutoff(tmp_path, later):
    # Migrations novas depois do corte não mudam a seleção nem o bundle, e nunca são lidas.
    reference_root = tmp_path / 'reference'
    reference_loader, _ = _repo(reference_root, _names(later=0))
    reference = active.select_baseline(reference_root, loader=reference_loader)
    names = _names(later=later)
    loader, _ = _repo(tmp_path / 'repo', names)
    for name in names:
        if name >= active.CUTOFF:
            path = tmp_path / 'repo' / 'backend' / 'migrations' / name
            path.unlink()
            path.symlink_to(tmp_path / 'absent')
    baseline = active.select_baseline(tmp_path / 'repo', loader=loader)
    assert baseline['active'] == len(names)
    assert baseline['selected'] == reference['selected']
    assert baseline['sql'] == reference['sql']
    assert not any(name >= active.CUTOFF for name in baseline['sql'])
    assert active.bundle_args(baseline) == active.bundle_args(reference)


def test_baseline_refuses_symlinked_sql(tmp_path):
    names = _names()
    loader, _ = _repo(tmp_path, names)
    target = tmp_path / 'backend' / 'migrations' / names[0]
    target.unlink()
    target.symlink_to(tmp_path / 'backend' / 'scripts' / 'migrate.py')
    with pytest.raises(containment.Refused, match='baseline-file'):
        active.select_baseline(tmp_path, loader=loader)


def test_bundle_round_trips_only_runner_and_selected_sql():
    baseline = dict(migrate='# runner\n', selected=['20260101_000000_a.sql'],
                    sql={'20260101_000000_a.sql': ''.join(hashlib.sha256(b'%d' % i).hexdigest()
                                                          for i in range(4000))})
    digest, chunks = active.bundle_args(baseline)
    assert len(chunks) > 1 and all(len(chunk) <= active.CHUNK for chunk in chunks)
    blob = base64.b64decode(''.join(chunks))
    assert hashlib.sha256(blob).hexdigest() == digest
    assert json.loads(zlib.decompress(blob)) == dict(migrate='# runner\n', order=baseline['selected'],
                                                     sql=baseline['sql'])


def test_probe_sources_compile():
    for code in (active.MIGRATE_PROBE, active.ENQUEUE_PROBE, active.HOLDER_PROBE, active.RLS_PROBE):
        compile(code, '<probe>', 'exec')
    assert '{classid}' in active.LOCKS_SQL and "'synthetic'" in active.LOCKS_SQL


def test_payload_forges_tenant_b_but_targets_instance_a():
    assert active.PAYLOAD['igreja_id'] == active.TENANT_B
    assert active.PAYLOAD['instance'] == active.INSTANCE_A
    assert active.PAYLOAD['data']['key'] == {'id': active.MESSAGE_ID, 'fromMe': False,
                                             'remoteJid': '5500000000011@s.whatsapp.net'}
    assert active.ACTIVE_ENV['WHATSAPP_PILOTO_IGREJA_IDS'] == ''
    assert active.ACTIVE_ENV['ALLOW_REAL_SENDS'] == 'false'
    assert '@postgres:5432/' in active.ACTIVE_ENV['DATABASE_URL']


def _state(**overrides):
    b = [{'id': 'b-person', 'igreja_id': active.TENANT_B, 'consentimento': False}]
    state = dict(
        messages=[dict(igreja=active.TENANT_A, direcao='in', autor='contato', provider=active.MESSAGE_ID,
                       texto_ok=True, conversation='c1')],
        pessoas_a=[dict(id='p1', telefone=active.CONTACT, nome_ok=True, consentimento=True)],
        conversations=[dict(id='c1', igreja=active.TENANT_A, pessoa='p1', nao_lidas=1)], b=b)
    state.update(overrides)
    return state, b


def test_ingested_state_accepts_exactly_one_effect_in_tenant_a():
    state, b = _state()
    assert active.ingested_ok(state, b)


@pytest.mark.parametrize('overrides', [
    dict(messages=[]),
    dict(pessoas_a=[dict(id='p1', telefone=active.CONTACT, nome_ok=True, consentimento=False)]),
    dict(conversations=[dict(id='c1', igreja=active.TENANT_A, pessoa='p1', nao_lidas=2)]),
    dict(conversations=[dict(id='c1', igreja=active.TENANT_B, pessoa='p1', nao_lidas=1)]),
    dict(messages=[dict(igreja=active.TENANT_B, direcao='in', autor='contato', provider=active.MESSAGE_ID,
                        texto_ok=True, conversation='c1')]),
    dict(b=[{'id': 'b-person', 'igreja_id': active.TENANT_B, 'consentimento': True}]),
])
def test_ingested_state_rejects_duplicates_wrong_tenant_or_touched_b(overrides):
    state, b = _state(**overrides)
    assert not active.ingested_ok(state, b)


class FakeDatabase:
    """Responde aos SQLs de ``migrate_and_seed`` com o bootstrap real das migrations 0005/0007."""

    def __init__(self, bootstrap=None):
        self.counts = dict(bootstrap or active.BOOTSTRAP_COUNTS)
        self.statements = []

    def psql(self, sql):
        self.statements.append(sql)
        if sql == active.SEED_SQL:
            for key, delta in dict(igrejas=2, pessoas=1, connections=2).items():
                self.counts[key] += delta
        return ''

    def psql_json(self, sql):
        if sql == active.LEDGER_SQL:
            return dict(ledger=['0001_legacy.sql'], roles={'anon': False, 'authenticated': False,
                                                          'service_role': True}, acl=['r', 'S', 'f'])
        if sql == active.EMPTY_SQL:
            return dict(self.counts)
        assert sql == active.STATE_SQL
        seeded = self.counts['igrejas'] > active.BOOTSTRAP_COUNTS['igrejas']
        return dict(messages=[], pessoas_a=[], conversations=[], b=[{'id': 'b'}] if seeded else [],
                    bootstrap_igrejas='d1', bootstrap_pessoas='d2', bootstrap_whatsapp_connections='d3')


def _seedable(monkeypatch, database):
    rehearsal = _rehearsal(FakeDocker())
    rehearsal.baseline['selected'] = ['0001_legacy.sql']
    monkeypatch.setattr(active, 'EXPECTED_SELECTED', 1)
    rehearsal.probe = lambda *args, **kwargs: json.dumps(dict(ok=True, applied=1))
    rehearsal.psql, rehearsal.psql_json = database.psql, database.psql_json
    return rehearsal


def test_seed_expects_bootstrap_and_preserves_it(monkeypatch):
    database = FakeDatabase()
    rehearsal = _seedable(monkeypatch, database)
    rehearsal.migrate_and_seed()
    assert database.counts == active.SEEDED_COUNTS == dict(igrejas=3, pessoas=2, conversations=0,
                                                            messages=0, connections=3)
    assert database.statements == [active.SEED_SQL]
    assert 'delete' not in active.SEED_SQL.lower() and 'truncate' not in active.SEED_SQL.lower()
    assert set(rehearsal.bootstrap) == {'bootstrap_igrejas', 'bootstrap_pessoas', 'bootstrap_whatsapp_connections'}
    assert all(f'bootstrap_{t}' in active.STATE_SQL for t in ('igrejas', 'pessoas', 'whatsapp_connections'))


@pytest.mark.parametrize('bootstrap', [
    dict(igrejas=0, pessoas=0, conversations=0, messages=0, connections=0),  # suposição antiga: vazio
    dict(igrejas=1, pessoas=1, conversations=0, messages=1, connections=1),
])
def test_seed_refuses_unexpected_bootstrap_before_writing(monkeypatch, bootstrap):
    database = FakeDatabase(bootstrap)
    with pytest.raises(containment.Refused, match='unexpected-bootstrap'):
        _seedable(monkeypatch, database).migrate_and_seed()
    assert database.statements == []


def test_rls_expectation_requires_positive_control_and_rls_diagnostic():
    expected = active.RLS_EXPECTED
    assert expected['write_a'] == 'accepted' and expected['read_a_after_rollback'] == expected['read_a'] == 1
    assert expected['write_b'] == '42501' and expected['write_b_rls'] is True and expected['read_b'] == 0
    assert "'row-level security' in" in active.RLS_PROBE and 'message_primary' in active.RLS_PROBE
    assert 'str(exc' not in active.RLS_PROBE  # só código e booleano no relatório
    assert any('antes de Pessoa/Conversation/Message'.lower() in item.lower() for item in active.NOT_PROVEN)


def _drainable(late=lambda store: None, pttl='604799000'):
    """Só o Redis observável do pós-ACK; ``late`` muda o estado durante a espera SURVIVE_S."""
    rehearsal, wid = _rehearsal(FakeDocker()), 'w1'
    store = {active.HEARTBEAT: 'ready', active.REGISTRY: {wid}, active.LEASE + wid: wid, active.PROCESSED: 'done'}

    def redis(command, key):
        if command == 'SMEMBERS':
            return '\n'.join(sorted(store.get(key, set())))
        if command == 'PTTL':
            return pttl() if callable(pttl) else pttl
        value = store.get(key)
        return value if isinstance(value, str) else ''
    rehearsal.redis, rehearsal.keys = redis, lambda: set(store)
    rehearsal.clock, rehearsal.check_worker = lambda: 0.0, lambda **kw: None
    rehearsal.sleep = lambda seconds: late(store) if seconds == active.SURVIVE_S else None
    return rehearsal, wid, store


def test_drain_accepts_stable_post_ack_state():
    rehearsal, wid, _ = _drainable()
    rehearsal.drain(wid, 'not-acked')


@pytest.mark.parametrize('late', [
    lambda s: s.update({'pastorai:webhooks:dead': 'x'}),                  # dead-letter tardio
    lambda s: s.update({'pastorai:webhooks:retry-scheduled': 'x'}),       # retry tardio
    lambda s: s.update({active.PROCESSED: 'processing:outro-claim'}),     # marcador reescrito
    lambda s: s.update({active.LEASE + 'w1': 'outro-worker'}),            # lease trocada
    lambda s: s.update({active.REGISTRY: {'w1', 'w2'}}),                  # segundo registro
    lambda s: s.update({active.HEARTBEAT: 'error'}),                      # heartbeat não vivo
])
def test_drain_refuses_late_keys_or_lease_change(late):
    rehearsal, wid, _ = _drainable(late)
    with pytest.raises(containment.Refused, match='unstable-after-ack'):
        rehearsal.drain(wid, 'not-acked')


@pytest.mark.parametrize('pttl', ['-1', '-2', '0', ''])
def test_marker_without_positive_ttl_is_refused(pttl):
    rehearsal, _, _ = _drainable(pttl=pttl)
    with pytest.raises(containment.Refused, match='marker-ttl'):
        rehearsal.marker_pttl()
    assert _drainable()[0].marker_pttl() == 604799000


def _windows(expiry_before, expiry_after, *, after_start=110.0, sample=0.004):
    """Duas amostras com relógio falso: PTTL = expiração absoluta - instante do servidor (meio da amostra)."""
    samples = [(100.0, expiry_before), (after_start, expiry_after)]
    times, ttls = [], []
    for start, expiry in samples:
        times += [start, start + sample]
        ttls.append(str(round(expiry - (start + sample / 2) * 1000)))
    rehearsal = _drainable(pttl=lambda: ttls.pop(0))[0]
    clock = iter(times)
    rehearsal.clock = lambda: next(clock)
    return rehearsal.marker_expiry_window(), rehearsal.marker_expiry_window(), ttls


ORIGINAL_EXPIRY = 100_000 + 604_800_000 - 2_000  # marcador gravado 2 s antes da 1ª amostra


def test_unchanged_expiry_passes_even_after_drain_time():
    before, after, _ = _windows(ORIGINAL_EXPIRY, ORIGINAL_EXPIRY)
    assert not active.expiry_renewed(before, after)


def test_rewrite_with_lower_raw_ttl_is_still_detected_by_absolute_expiry():
    rewritten = 104_000 + 604_800_000  # novo SET EX 4 s depois da 1ª amostra (marcador com menos de 6 s)
    before, after, _ = _windows(ORIGINAL_EXPIRY, rewritten)
    raw_before = before[0] - 100_000
    raw_after = after[0] - 110_000
    assert raw_after < raw_before  # a comparação antiga de PTTL bruto não detectava
    assert active.expiry_renewed(before, after)


def test_slow_pttl_sample_is_uncertain():
    rehearsal = _drainable()[0]
    clock = iter([100.0, 100.0 + (active.MARKER_SAMPLE_MAX_MS + 1) / 1000])
    rehearsal.clock = lambda: next(clock)
    with pytest.raises(containment.Refused, match='marker-ttl-uncertain'):
        rehearsal.marker_expiry_window()


def _rehearsal(runner, **kwargs):
    baseline = dict(active=1, selected=['20260101_000000_a.sql'], sql={'20260101_000000_a.sql': ''}, migrate='')
    return active.ActiveRehearsal(legacy_image=LEGACY, redis_image=REDIS, postgres_image=kwargs.pop('pg', PG),
                                  files=FILES, baseline=baseline, runner=runner, sleep=lambda _: None, **kwargs)


def test_mutable_postgres_reference_is_refused_before_docker():
    calls = []
    with pytest.raises(containment.Refused, match='image-not-local-immutable'):
        _rehearsal(calls.append, pg='postgres:18')
    assert calls == []


def test_remote_docker_refused_before_any_resource(monkeypatch):
    calls = []
    monkeypatch.setenv('DOCKER_HOST', 'tcp://203.0.113.1:2376')
    rehearsal = _rehearsal(lambda argv: calls.append(argv) or '')
    with pytest.raises(containment.Refused, match='remote-docker'):
        rehearsal.preflight()
    assert not any(argv[1] in ('run', 'network') for argv in calls)


class FakeDocker:
    """Só o suficiente para ``create_support``: rede, Redis e Postgres próprios."""

    def __init__(self):
        self.runs, self.network = {}, None

    def __call__(self, argv):
        command, args = argv[1], argv[2:]
        if command == 'context':
            return json.dumps([{'Endpoints': {'docker': {'Host': 'unix:///var/run/docker.sock'}}}])
        if command == 'network':
            assert args[0] == 'create' and '--internal' in args
            self.network = uuid.uuid4().hex * 2
            return self.network
        if command == 'run':
            cid = uuid.uuid4().hex * 2
            self.runs[cid] = args
            return cid
        if command == 'exec':
            return {'PING': 'PONG', 'KEYS': ''}.get(args[2], '') if args[1] == 'redis-cli' else ''
        if command == 'inspect':
            return json.dumps([self._inspect(args[0])])
        raise AssertionError(argv)

    def _inspect(self, cid):
        args = self.runs[cid]
        pairs = [(a, args[i + 1]) for i, a in enumerate(args) if a.startswith('--') and i + 1 < len(args)]
        image_at = next(i for i, a in enumerate(args) if a.startswith('sha256:'))
        labels = dict(v.split('=', 1) for k, v in pairs if k == '--label')
        name = next(v for k, v in pairs if k == '--name')
        return dict(Id=cid, Image=args[image_at], RestartCount=0, Mounts=[], State=dict(Running=True),
                    Config=dict(Labels=labels, User=dict(pairs)['--user'], Entrypoint=[dict(pairs)['--entrypoint']],
                                Cmd=args[image_at + 1:], Env=[v for k, v in pairs if k == '--env']),
                    HostConfig=dict(NetworkMode=self.network, ReadonlyRootfs='--read-only' in args,
                                    Tmpfs={v.split(':', 1)[0]: v.split(':', 1)[1] for k, v in pairs if k == '--tmpfs'}),
                    NetworkSettings=dict(Networks={name.rsplit('-', 1)[0]: {}}, Ports={}))


def test_postgres_is_hardened_tmpfs_only_and_owned():
    fake = FakeDocker()
    rehearsal = _rehearsal(fake)
    rehearsal.pg_volumes = {'/var/lib/postgresql'}
    rehearsal.create_support()
    args = fake.runs[rehearsal.ids['postgres']]
    assert args[:2] == ['-d', '--pull'] and args[2] == 'never'
    assert not {'-p', '--publish', '-P', '--publish-all', '-v', '--volume', '--mount', '--privileged'} & set(args)
    assert args[args.index('--user') + 1] == '999:999' and '--read-only' in args
    assert args[args.index('--network') + 1] == fake.network
    tmpfs = [args[i + 1] for i, a in enumerate(args) if a == '--tmpfs']
    assert '/data:rw,nosuid,nodev,size=1g,uid=999,gid=999,mode=0700' in tmpfs
    assert any(t.startswith('/var/run/postgresql:') for t in tmpfs)
    assert any(t.startswith('/var/lib/postgresql:') for t in tmpfs)  # sem volume anônimo
    assert 'PGDATA=/data' in args and args[-2:] == [PG, 'postgres']
    assert rehearsal.ids['postgres'] in rehearsal.created['containers']


def test_hostile_image_volume_path_is_refused(monkeypatch):
    rehearsal = _rehearsal(FakeDocker())
    monkeypatch.setattr(active.QueueRehearsal, 'preflight', lambda self: None)  # fonte/runtime: test_legacy_queue
    rehearsal._image = lambda ref: {'Volumes': {'/var/lib/../../etc': {}}}
    with pytest.raises(containment.Refused, match='postgres-image-volumes'):
        rehearsal.preflight()
    assert rehearsal.created == {'containers': [], 'networks': []}
