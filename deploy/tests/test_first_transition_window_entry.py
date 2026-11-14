"""Window entry composition over synthetic files and IO only, never a real host or DB."""
import json
import re
import ipaddress
from pathlib import Path
import sys
import os
import stat
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_window as window
import first_transition_database as fdb
from first_transition_adapter import prepare
from first_transition_candidate import CLOSED_GATES, write_hold_override
from test_first_transition_candidate_writers import Assembly, WriterCursor, WriterConnection
from test_first_transition_orchestrator import (APPLICATION_SHA, CANDIDATE_IDS, LEGACY, SUPPORT, ROOT, SECRET_URL, World, RecordingGit,
                                                digest_bytes, no_real_processes_or_network)  # noqa: F401
from test_first_transition_window_backup import Host
import first_transition_window_backup as backup_module
import package_backend_release


@pytest.fixture(scope='module')
def pinned():
    git = RecordingGit()
    plan = prepare(ROOT, git=git)
    files = package_backend_release.source_files(ROOT, APPLICATION_SHA, git)
    return plan, git, digest_bytes(package_backend_release.release_manifest(APPLICATION_SHA, files))


class SourceCursor(WriterCursor):
    def execute(self, query, params=None):
        if query == window.Q_VERSION:
            self.rows = [(170006,)]
        elif query == window.Q_EXECUTOR:
            self.rows = [(getattr(self.pg, 'executor_user', 'postgres'), getattr(self.pg, 'executor_ready', True))]
        elif query == backup_module.Q_SOURCE_ROLES:
            self.rows = [('postgres',), ('anon',), ('authenticated',)]
        else:
            super().execute(query, params)


class SourceConnection(WriterConnection):
    def cursor(self):
        return SourceCursor(self.pg)


class BackupIO(Host):
    def __init__(self, w):
        super().__init__(w.plan)
        self.world = w

    def catalog_rows(self):
        return self.world.pg.catalog_rows(self.ledger())


class Entry:
    def __init__(self, pinned, tmp_path):
        w = self.world = World(pinned, tmp_path)
        self.secret_path, self.candidate_path = tmp_path / 'operator.conf', tmp_path / 'candidate.conf'
        self.env_var = 'MIGRATION_DATABASE_URL'
        self.secret_path.write_text('MIGRATION_DATABASE_URL=' + SECRET_URL + '\n')
        self.candidate_path.write_text('\n'.join(k + '=' + v for k, v in CLOSED_GATES.items()) + '\n')
        self.secret_path.chmod(0o600)
        self.candidate_path.chmod(0o600)
        w.spec = replace(w.spec, env_file=str(self.candidate_path))
        w.cdocker.spec = w.spec
        self.assembly = Assembly(w)
        self.backup_io = BackupIO(w)
        w.layout()
        write_hold_override(w.spec)
        raw = json.loads((ROOT / 'deploy/first-transition.example.json').read_text())
        c = self.assembly.config
        for key in ('repo', 'state_dir', 'migration_workdir', 'python', 'package_manifest_sha256'):
            raw[key] = getattr(c, key)
        cdir = tmp_path / 'docker-cli'
        cdir.mkdir()
        raw['docker'] = dict(binary=c.docker[0], endpoint=c.docker[1], config_dir=str(cdir))
        raw['database'].update(identity=c.identity, catalog=c.catalog)
        from test_first_transition_host_driver import MANIFEST
        raw['host'] = json.loads(json.dumps(MANIFEST))
        raw['candidate'] = dict(sha=w.spec.sha, image=w.spec.image, project=w.spec.project,
                                containers=w.spec.names(), network_name=w.spec.network_name,
                                release_root=w.spec.release_root, hold_override=w.spec.hold_override,
                                env_file=w.spec.env_file, smoke_seconds=w.spec.smoke_seconds)
        self.raw = raw
        self.bindings = dict(scope=c.manifest.digest, nginx=asdict(self.assembly.ingress['external'].config),
                             bridge=asdict(self.assembly.ingress['evolution-backend'].config),
                             writers=dict(declared_containers=[i for _, i in c.manifest.service_ids],
                                          docker=[raw['docker'][k] for k in ('binary', 'endpoint', 'config_dir')],
                                          readonly_roles=[]))
        for name in ('backups', 'clone-work'):
            (tmp_path / name).mkdir(mode=0o700)
        self.backup = dict(docker_binary=c.docker[0], docker_endpoint=c.docker[1], docker_config_dir=str(cdir),
                           backup_root=str(tmp_path / 'backups'), clone_workdir=str(tmp_path / 'clone-work'),
                           python=c.python, dump_image='registry.invalid/dump@sha256:' + '1' * 64,
                           clone_image='registry.invalid/clone@sha256:' + '2' * 64,
                           clone_command=['postgres', '-c', 'shared_preload_libraries='],
                           restore_excluded_expected=dict(vault_extension=2, vault_schema=2, event_triggers=2,
                                                          event_trigger_names=['issue_pg_net_access']))
        self.paths = {k: tmp_path / (k + '.json') for k in ('config', 'backup', 'bindings')}
        self.write()
        self.calls, self.connections = [], []
        self.failure = None
        self.effective_site = True
        self.io = dict(git=pinned[1], run=self.run, popen=self.assembly.popen,
                       connect=self.connect, clone_connect=self.backup_io.clone_connect,
                       binding_run=self.binding_run, proc=str(self.assembly.docker.proc.root),
                       endpoint=lambda _: (frozenset({ipaddress.ip_address('10.20.30.40')}), 5432),
                       secret_fstat=self.secret_stat, nginx_owner_uid=os.getuid(),
                       stat=lambda p: SimpleNamespace(st_mode=(stat.S_IFDIR if p.startswith('/sys/class/net/')
                                                               else stat.S_IFREG) | 0o755), sleep=lambda _: None)

    @staticmethod
    def secret_stat(fd):
        actual = os.fstat(fd)
        return SimpleNamespace(st_mode=actual.st_mode, st_size=actual.st_size, st_uid=0)

    def write(self):
        for key, data in (('config', self.raw), ('backup', self.backup), ('bindings', self.bindings)):
            self.paths[key].write_text(json.dumps(data))

    def args(self, mode):
        return [mode, '--config', str(self.paths['config']), '--env-file', str(self.secret_path),
                '--env-var', self.env_var, '--backup-config', str(self.paths['backup']),
                '--bindings-config', str(self.paths['bindings'])]

    def prepare(self):
        lines = []
        assert window.main(self.args('prepare'), out=lines.append, io=self.io) == 0, lines
        return json.loads(lines[-1])

    def execute(self, digests=None):
        d = digests or self.prepare()
        lines = []
        code = window.main([*self.args('run'), '--expect-plan-digest', d['plan_digest'],
                            '--expect-window-digest', d['window_digest']], out=lines.append, io=self.io)
        return code, [json.loads(line) for line in lines]

    def journal_text(self):
        return (Path(self.raw['state_dir']) / 'journal' / 'journal.jsonl').read_text()

    def assert_no_journal_or_effects(self):
        assert not (Path(self.raw['state_dir']) / 'journal').exists()
        assert self.world.legacy_effects() == [] and self.world.cdocker.effects() == []
        assert self.world.migrate.applied == [] and self.backup_io.calls == []
        assert not self.assembly.ingress['external'].snippet.exists() and self.assembly.bridge_io.table is None
        assert all(a[0].endswith('curl') or a[1:] == ('-T',) for a in self.assembly.nginx_io.calls)
        assert all(a[1:3] == ('-j', 'list') for a in self.assembly.bridge_io.calls)

    def connect(self, url, **kwargs):
        assert url == SECRET_URL and 'read_only=on' in kwargs['options']
        self.connections.append(url)
        self.world.pg.connect(timeout=10)
        return SourceConnection(self.world.pg)

    def binding_run(self, argv, **kwargs):
        if argv == (self.bindings['nginx']['nginx_binary'], '-T'):
            site = self.bindings['nginx']['site_path']
            return 0, (('# configuration file ' + site + ':\n' + Path(site).read_text()).encode()
                       if self.effective_site else b'# configuration file /other/site:\n')
        if argv[0].endswith('curl') or argv[0].endswith('nginx') or argv[0].endswith('systemctl'):
            return self.assembly.nginx_io(argv, **kwargs)
        if argv[0].endswith('nft'):
            return self.assembly.bridge_io(argv, **kwargs)
        return self.assembly.docker(argv, **kwargs)

    def model(self):
        s = self.world.spec
        return dict(name=s.project, networks={'default': {'external': True, 'name': s.network_name}}, services={
            role: dict(container_name=name, networks={'default': {}}, image=s.image, restart='no',
                       environment={**CLOSED_GATES, 'PASTORAI_RELEASE_SHA': s.sha, 'DATABASE_URL': SECRET_URL},
                       ports=[dict(host_ip='127.0.0.1', published='8000', target=8000)] if role == 'backend' else [])
            for role, name in s.names().items()})

    def run(self, argv, **kwargs):
        self.calls.append(tuple(argv))
        assert SECRET_URL not in str(argv)
        if argv[:3] == [self.raw['python'], '-I', '-c']:
            value = [[3, 13], '2.9.12']
        elif argv[0] == self.raw['python']:
            if str(kwargs['cwd']).startswith(self.backup['clone_workdir']):
                return self.backup_io.migrate(argv, **kwargs)
            return self.world.migrate(argv, **kwargs)
        elif argv[5:6] == ['info']:
            value = ['linux', 'x86_64']
        elif argv[5:7] == ['network', 'inspect']:
            value = [self.world.spec.network_id, self.world.spec.network_name, 'bridge', None]
        elif argv[5:7] == ['image', 'inspect']:
            image = argv[-1]
            value = [image if image == self.world.spec.image else 'sha256:' + 'f' * 64,
                     [image], 'linux', self.world.spec.sha, ['PG_MAJOR=17', None], 'amd64']
        elif argv[5] == 'compose':
            assert argv[argv.index('--env-file') + 1] == '/dev/null' and kwargs['cwd'] == '/'
            value = self.model()
        else:
            translated = ['/usr/bin/docker', '--config', '/state/docker-cli', '--host', 'unix:///run/docker.sock',
                          *argv[5:]]
            return self.backup_io.run(translated, **kwargs)
        if self.failure:
            value = self.failure(argv, value)
        return SimpleNamespace(returncode=0, stdout=json.dumps(value).encode())


@pytest.fixture
def entry(pinned, tmp_path):
    e = Entry(pinned, tmp_path)
    yield e
    e.world.journal.close()


def test_prepare_is_pure_and_run_composes_real_backup_and_controller(entry):
    d = entry.prepare()
    assert d['assertions_are_authorization'] is False
    assert entry.calls == [] and entry.connections == [] and entry.assembly.popen_calls == []
    code, lines = entry.execute(d)
    assert code == 0, lines
    assert lines[-1]['production_ready'] is False and lines[-1]['a10'] == 'separate-authorization'
    assert re.fullmatch('[0-9a-f]{64}', lines[-1]['a10_token'])
    assert entry.world.migrate.applied == [m.name for m in entry.world.plan.pending]
    assert len(entry.backup_io.migrations) == 52
    assert sum('--no-transaction' in argv for argv, _ in entry.backup_io.migrations) == 8
    entry.world.consumers_held()
    assert all(binding.observe(binding.scope, timeout=5) == 'blocked'
               for binding in entry.assembly.ingress.values())
    assert entry.assembly.nginx_io.live is True
    journal = Path(entry.raw['state_dir']) / 'journal' / 'journal.jsonl'
    assert 'SENTINEL' not in journal.read_text() and 'SENTINEL' not in json.dumps(lines)
    assert entry.world.cdocker.starts == 1


def test_run_refuses_topology_drift_after_readiness_without_containment(entry):
    """Real entry/controller/ingress composition, with mutation at the probe IO boundary."""
    original = entry.io['binding_run']
    probes = []

    def io(argv, **kwargs):
        answer = original(argv, **kwargs)
        if argv[0] == entry.bindings['nginx']['curl_binary']:
            probes.append(argv)
            site = Path(entry.bindings['nginx']['site_path'])
            site.write_text(site.read_text().replace('    location / {',
                                                    '    include /other/site.conf;\n    location / {'))
        return answer

    entry.io['binding_run'] = io
    status, lines = entry.execute()
    assert len(probes) == 1  # Readiness passed before the synthetic topology drift.
    assert status == 2 and lines[-1]['refused'] == 'window-transition-refused'
    assert entry.world.legacy_effects() == [] and entry.world.cdocker.effects() == []
    assert entry.world.migrate.applied == [] and entry.backup_io.calls == []
    assert not entry.assembly.ingress['external'].snippet.exists()
    assert entry.assembly.nginx_io.live is False and entry.assembly.bridge_io.table is None
    assert all(a[0].endswith('curl') for a in entry.assembly.nginx_io.calls)
    assert all(a[1:3] == ('-j', 'list') for a in entry.assembly.bridge_io.calls)
    journal = entry.journal_text()
    assert 'ddl-marker' not in journal and 'a9:start-backend' not in journal
    assert 'SENTINEL' not in journal and 'SENTINEL' not in json.dumps(lines)


@pytest.mark.parametrize('fault,code', [
    ('scope', 'window-bindings-scope'), ('bridge', 'window-bindings-bridge'), ('port', 'window-bindings-bridge'),
    ('ids', 'window-bindings-declarations'), ('docker', 'window-bindings-docker'),
    ('backup-docker', 'window-backup-docker'), ('backup-python', 'window-backup-python'),
    ('sensitive-backup', 'window-backup-config-keys'), ('unknown-bindings', 'window-bindings-config'),
    ('unknown-transition', 'window-refused'), ('clone-jobs', 'window-backup-isolation'),
])
def test_public_mismatch_refuses_before_secret_or_io(entry, fault, code):
    d = entry.prepare()
    if fault == 'scope':
        entry.bindings['scope'] = '0' * 64
    elif fault == 'bridge':
        entry.bindings['bridge']['bridge'] = 'br-' + 'f' * 12
    elif fault == 'port':
        entry.bindings['bridge']['port'] = 8001
    elif fault == 'ids':
        entry.bindings['writers']['declared_containers'][0] = CANDIDATE_IDS['backend']
    elif fault == 'docker':
        entry.bindings['writers']['docker'][1] = 'unix:///run/other.sock'
    elif fault == 'backup-docker':
        entry.backup['docker_endpoint'] = 'unix:///run/other.sock'
    elif fault == 'backup-python':
        entry.backup['python'] = '/usr/local/bin/other-python'
    elif fault == 'sensitive-backup':
        entry.backup['password'] = 'SENTINEL-NEVER-OUTPUT'
    elif fault == 'unknown-bindings':
        entry.bindings['token'] = 'SENTINEL-NEVER-OUTPUT'
    elif fault == 'clone-jobs':
        entry.backup['clone_command'] = ['postgres', '-c', 'shared_preload_libraries=pg_cron']
    else:
        entry.raw['database_url'] = SECRET_URL
    entry.write()
    exit_code, lines = entry.execute(d)
    assert exit_code == 2 and lines == [{'refused': code}]
    assert entry.calls == [] and entry.connections == [] and entry.assembly.popen_calls == []
    entry.assert_no_journal_or_effects()
    assert 'SENTINEL' not in json.dumps(lines)


@pytest.mark.parametrize('field,code', [('plan_digest', 'window-plan-digest'),
                                      ('window_digest', 'window-window-digest')])
def test_wrong_expected_digest_has_zero_io(entry, field, code):
    d = entry.prepare()
    d[field] = '0' * 64
    status, lines = entry.execute(d)
    assert status == 2 and lines == [{'refused': code}]
    assert entry.calls == [] and entry.connections == []
    entry.assert_no_journal_or_effects()


@pytest.mark.parametrize('fault,code', [
    ('hash', 'package-identity-mismatch'), ('layout', 'layout-mismatch'),
    ('executable', 'window-prerequisite'), ('image', 'window-image'),
    ('runtime', 'window-runtime'), ('network', 'window-network'), ('version', 'window-backup-version'),
    ('gate', 'window-compose'), ('compose-port', 'window-compose'), ('root-directory', 'window-prerequisite'),
    ('architecture', 'window-image'),
])
def test_readiness_failure_never_creates_journal_or_contains(entry, fault, code):
    if fault == 'hash':
        entry.raw['package_manifest_sha256'] = '0' * 64
        entry.write()
    elif fault == 'layout':
        (Path(entry.world.spec.deploy_dir) / 'docker-compose.yml').write_text('not the pinned layout')
    elif fault == 'executable':
        entry.io['stat'] = lambda _: SimpleNamespace(st_mode=stat.S_IFREG | 0o644)
    elif fault == 'root-directory':
        Path(entry.backup['backup_root']).rmdir()
    else:
        def damage(argv, value):
            if fault == 'runtime' and argv[:3] == [entry.raw['python'], '-I', '-c']:
                return [[3, 12], '2.9.12']
            if fault in ('image', 'version') and argv[5:7] == ['image', 'inspect']:
                if fault == 'image':
                    value[0] = 'sha256:' + '0' * 64
                else:
                    value[4] = ['PG_MAJOR=16', None]
            if fault == 'architecture' and argv[5:7] == ['image', 'inspect']:
                value[5] = 'arm64'
            if fault == 'network' and argv[5:7] == ['network', 'inspect']:
                value[0] = '0' * 64
            if fault in ('gate', 'compose-port') and argv[5:6] == ['compose']:
                if fault == 'gate':
                    value['services']['backend']['environment']['ALLOW_REAL_SENDS'] = 'true'
                else:
                    value['services']['backend']['ports'][0]['target'] = 9999
            return value
        entry.failure = damage
    status, lines = entry.execute()
    assert status == 2 and lines == [{'refused': code}]
    entry.assert_no_journal_or_effects()


@pytest.mark.parametrize('fault', ['owner', 'mode', 'symlink', 'wrong-variable'])
def test_credential_has_no_alternate_channel(entry, monkeypatch, fault):
    monkeypatch.setenv('MIGRATION_DATABASE_URL', SECRET_URL)
    monkeypatch.setenv('DATABASE_URL', SECRET_URL)
    if fault == 'owner':
        entry.io['secret_fstat'] = os.fstat
    elif fault == 'mode':
        entry.secret_path.chmod(0o644)
    elif fault == 'symlink':
        real = entry.secret_path.with_name('fictional-target.conf')
        entry.secret_path.rename(real)
        entry.secret_path.symlink_to(real)
    else:
        entry.secret_path.write_text('DATABASE_URL=' + SECRET_URL + '\n')
    status, lines = entry.execute()
    expected = {'owner': 'window-env-file-mode', 'mode': 'window-env-file-mode',
                'symlink': 'window-env-file', 'wrong-variable': 'window-env-secret'}[fault]
    assert status == 2 and lines == [{'refused': expected}]
    assert entry.calls == [] and entry.connections == []
    entry.assert_no_journal_or_effects()


def test_prepare_does_not_hash_or_read_secret_bytes(entry):
    before = entry.prepare()
    entry.secret_path.write_text('MIGRATION_DATABASE_URL=postgresql://different:fictional@other.invalid/test\n')
    assert entry.prepare() == before
    assert entry.calls == [] and entry.connections == []


def test_replay_held_ingress_revalidates_without_repeating_effects(entry):
    assert entry.execute()[0] == 0
    before = (list(entry.world.legacy_effects()), list(entry.world.cdocker.effects()),
              list(entry.world.migrate.applied), list(entry.backup_io.calls))
    status, lines = entry.execute()
    assert status == 2 and lines[-1]['refused'] == 'window-transition-refused'
    assert lines[-1]['recovery']['state'] == 'a9-complete'
    assert (entry.world.legacy_effects(), entry.world.cdocker.effects(), entry.world.migrate.applied,
            entry.backup_io.calls) == before
    entry.world.consumers_held()


@pytest.mark.parametrize('changed', ['transition', 'backup', 'bindings', 'provider', 'provider-variable'])
def test_window_init_prevents_config_adoption_on_replay(entry, changed):
    assert entry.execute()[0] == 0
    journal = entry.journal_text()
    before = (list(entry.world.legacy_effects()), list(entry.world.cdocker.effects()),
              list(entry.world.migrate.applied), list(entry.backup_io.calls))
    if changed == 'backup':
        entry.backup['timeouts'] = {'dump_s': 121}
    elif changed == 'bindings':
        entry.bindings['writers']['readonly_roles'] = ['fictional_readonly']
    elif changed == 'transition':
        entry.raw['timeouts']['observe_s'] = 11
    elif changed == 'provider':
        new = entry.secret_path.with_name('same-secret-new-explicit-path.conf')
        new.write_bytes(entry.secret_path.read_bytes())
        new.chmod(0o600)
        entry.secret_path = new
    else:
        entry.env_var = 'EXPLICIT_OWNER_DSN'
        entry.secret_path.write_text('EXPLICIT_OWNER_DSN=' + SECRET_URL + '\n')
    entry.write()
    status, lines = entry.execute()
    assert status == 2 and lines == [{'refused': 'window-inputs-changed'}]
    assert entry.journal_text() == journal
    assert (entry.world.legacy_effects(), entry.world.cdocker.effects(), entry.world.migrate.applied,
            entry.backup_io.calls) == before


def test_old_journal_cannot_be_adopted(entry):
    from initial_transition_files import Journal
    with Journal(Path(entry.raw['state_dir']) / 'journal') as journal:
        journal.append('older-controller-event')
    before = entry.journal_text()
    assert entry.execute()[1] == [{'refused': 'window-journal-unbound'}]
    assert entry.journal_text() == before and entry.world.legacy_effects() == []


@pytest.mark.parametrize('failure', ['backup', 'migration', 'create', 'start'])
def test_failures_keep_containment_and_never_repeat_ambiguous_effect(entry, failure):
    if failure == 'backup':
        entry.backup_io.fail = {'dump'}
    elif failure == 'migration':
        tx = next(m for m in entry.world.plan.pending if not m.concurrent)
        entry.world.migrate.faults[tx.name] = 'fail'
    elif failure == 'create':
        entry.world.cdocker.on_create = lambda: (_ for _ in ()).throw(KeyboardInterrupt)
    else:
        entry.world.cdocker.on_start = lambda: (_ for _ in ()).throw(KeyboardInterrupt)
    status, lines = entry.execute()
    assert status == 2 and lines[-1]['recovery']['automatic_undo'] is False
    assert lines[-1]['recovery']['automatic_restore'] is False
    assert lines[-1]['recovery']['legacy_resume_allowed'] is (failure == 'backup')
    if failure in ('create', 'start'):
        assert lines[-1]['recovery']['state'] == 'candidate-ambiguous'
        entry.world.consumers_held()
    effects = (list(entry.world.legacy_effects()), list(entry.world.cdocker.effects()),
               list(entry.world.migrate.applied), list(entry.backup_io.calls))
    assert entry.execute()[0] == 2
    assert (entry.world.legacy_effects(), entry.world.cdocker.effects(), entry.world.migrate.applied,
            entry.backup_io.calls) == effects
    assert 'SENTINEL' not in entry.journal_text() and 'SENTINEL' not in json.dumps(lines)


@pytest.mark.parametrize('writers,exit_code', [(0, 0), (1, 1)])
def test_check_bindings_observes_without_quiescence_or_mutation(entry, writers, exit_code):
    entry.world.pg.writers = writers
    lines = []
    assert window.main(entry.args('check-bindings'), out=lines.append, io=entry.io) == exit_code
    assert json.loads(lines[-1]) == {'external': 'open', 'evolution-backend': 'open', 'unknown_writers': writers}
    entry.assert_no_journal_or_effects()


def test_check_bindings_validates_scope_before_io(entry):
    entry.bindings['scope'] = '0' * 64
    entry.write()
    lines = []
    assert window.main(entry.args('check-bindings'), out=lines.append, io=entry.io) == 2
    assert json.loads(lines[-1]) == {'refused': 'window-bindings-scope'}
    assert entry.calls == [] and entry.connections == []
    entry.assert_no_journal_or_effects()


@pytest.mark.parametrize('value', [True, -1, '1'])
def test_check_bindings_invalid_external_count_refuses(entry, value):
    entry.world.pg.writers = value
    lines = []
    assert window.main(entry.args('check-bindings'), out=lines.append, io=entry.io) == 1
    assert json.loads(lines[-1])['unknown_writers'] == 'refused:window-refused'
    entry.assert_no_journal_or_effects()


def test_duplicate_public_json_keys_refuse_without_io(entry):
    d = entry.prepare()
    data = entry.paths['bindings'].read_text()
    entry.paths['bindings'].write_text('{"scope":"' + '0' * 64 + '",' + data[1:])
    assert entry.execute(d) == (2, [{'refused': 'window-config-invalid'}])
    assert entry.calls == [] and entry.connections == []
    entry.assert_no_journal_or_effects()


def test_missing_explicit_variable_refuses_even_with_inherited_dsn(entry, monkeypatch):
    monkeypatch.setenv('MIGRATION_DATABASE_URL', SECRET_URL)
    args = entry.args('run')
    pos = args.index('--env-var')
    del args[pos:pos + 2]
    args += ['--expect-plan-digest', '0' * 64, '--expect-window-digest', '0' * 64]
    lines = []
    assert window.main(args, out=lines.append, io=entry.io) == 2
    assert json.loads(lines[-1]) == {'refused': 'window-run-prerequisites'}
    entry.assert_no_journal_or_effects()


def test_private_io_failure_cannot_print_exception_text(entry):
    def fail(_url, **kwargs):
        raise RuntimeError('failure with ' + SECRET_URL)
    entry.io['connect'] = fail
    code, lines = entry.execute()
    assert code == 2 and 'SENTINEL' not in json.dumps(lines)
    entry.assert_no_journal_or_effects()


@pytest.mark.parametrize('fault', ['missing-layout', 'hold', 'nginx-port', 'backup-image', 'image-missing'])
def test_remaining_read_prerequisites_refuse_before_journal(entry, fault):
    if fault == 'missing-layout':
        directory = Path(entry.world.spec.release_root) / entry.world.spec.sha
        directory.rename(directory.with_name(directory.name + '-fixture-moved'))
    elif fault == 'hold':
        Path(entry.world.spec.hold_override).write_text('wrong hold')
    elif fault == 'nginx-port':
        p = Path(entry.assembly.ingress['external'].config.site_path)
        p.write_text(p.read_text().replace('127.0.0.1:8000', '127.0.0.1:9000'))
    else:
        def bad_image(argv, value):
            if argv[5:7] == ['image', 'inspect']:
                if fault == 'image-missing':
                    raise FileNotFoundError('fictional missing image')
                if argv[-1] == entry.backup['dump_image']:
                    value[1] = []
            return value
        entry.failure = bad_image
    code, lines = entry.execute()
    expected = {'missing-layout': 'candidate-layout-not-prepared', 'hold': 'candidate-hold-mismatch',
                'nginx-port': 'window-nginx-topology', 'backup-image': 'window-image',
                'image-missing': 'window-prerequisite'}[fault]
    assert code == 2 and lines == [{'refused': expected}]
    entry.assert_no_journal_or_effects()


def test_nginx_site_must_be_in_effective_configuration(entry):
    entry.effective_site = False
    assert entry.execute() == (2, [{'refused': 'window-nginx-topology'}])
    entry.assert_no_journal_or_effects()


def test_wrong_daemon_refuses_before_journal(entry):
    entry.world.rig.docker.daemon = '00000000-0000-4000-8000-000000000099'
    status, lines = entry.execute()
    assert status == 2 and lines == [{'refused': 'window-refused'}]
    entry.assert_no_journal_or_effects()


def test_check_bindings_reports_refused_bridge_without_mutating_it(entry):
    entry.assembly.bridge_io.table = entry.assembly.bridge_io.config.expected()[:2]
    before = json.dumps(entry.assembly.bridge_io.table)
    lines = []
    assert window.main(entry.args('check-bindings'), out=lines.append, io=entry.io) == 1
    assert json.loads(lines[-1])['evolution-backend'] == 'refused:window-refused'
    assert json.dumps(entry.assembly.bridge_io.table) == before
    assert entry.world.legacy_effects() == [] and entry.world.migrate.applied == []
    assert not (Path(entry.raw['state_dir']) / 'journal').exists()


def test_partial_containment_replay_is_not_blocked_by_open_ingress_precondition(entry):
    from test_first_transition_host_driver import LEGACY
    entry.world.rig.docker.term_exit[LEGACY['backend']] = 143
    code, lines = entry.execute()
    assert code == 2 and lines[-1]['recovery']['state'] == 'containment-partial'
    before = list(entry.world.legacy_effects())
    code, lines = entry.execute()
    assert code == 2 and lines[-1]['recovery']['state'] == 'containment-partial'
    assert entry.world.legacy_effects() == before
    assert entry.backup_io.calls == [] and entry.world.migrate.applied == []
    assert 'ddl-marker' not in entry.journal_text()


@pytest.mark.parametrize('value', ['postgresql://owner@db.invalid/app',
                                  SECRET_URL + '?service=alternate', SECRET_URL + '?options=-c%20role=other'])
@pytest.mark.parametrize('ambient_password', [False, True])
def test_credential_cannot_fall_back_to_libpq_identity_or_service(entry, monkeypatch, value, ambient_password):
    if ambient_password:
        monkeypatch.setenv('PGPASSWORD', 'SENTINEL-INHERITED')
    entry.secret_path.write_text('MIGRATION_DATABASE_URL=' + value + '\n')
    expected = 'database-libpq-environment' if ambient_password else 'window-env-secret'
    assert entry.execute() == (2, [{'refused': expected}])
    assert entry.connections == []
    entry.assert_no_journal_or_effects()


@pytest.mark.parametrize('fault', ['privilege', 'owner'])
def test_actual_executor_role_is_checked_readonly_before_containment(entry, fault):
    if fault == 'owner':
        entry.world.pg.executor_user = 'different_owner'
    else:
        entry.world.pg.executor_ready = False
    assert entry.execute() == (2, [{'refused': 'window-executor-role'}])
    entry.assert_no_journal_or_effects()


def test_run_without_explicit_prerequisites_refuses_before_reading_config():
    lines = []
    assert window.main(['run', '--config', '/not-read', '--env-file', '/not-read'], out=lines.append) == 2
    assert json.loads(lines[-1]) == {'refused': 'window-run-prerequisites'}


def test_secret_owner_is_root_even_when_permissions_are_private(tmp_path):
    path = tmp_path / 'fictional.conf'
    path.write_text('MIGRATION_DATABASE_URL=postgresql://synthetic:sentinel@db.invalid/app\n')
    path.chmod(0o600)
    if path.stat().st_uid == 0:
        pytest.skip('negative owner fixture requires non-root test user')
    with pytest.raises(window.Refused, match='^window-env-file-mode$'):
        window.env_file_secret(str(path), 'MIGRATION_DATABASE_URL')()


@pytest.mark.parametrize('gate', ['allow_real_sends', 'Allow_Real_Sends'])
@pytest.mark.parametrize('value', ['true', 'false'])
@pytest.mark.parametrize('source', ['file', 'model'])
def test_case_insensitive_gate_variants_refuse_before_journal(entry, gate, value, source):
    if source == 'file':
        with entry.candidate_path.open('a') as handle:
            handle.write('export ' + gate + '=' + value + '\n')
    else:
        model = entry.model()
        model['services']['backend']['environment'][gate] = value
        entry.model = lambda: model
    assert entry.execute() == (2, [{'refused': 'window-compose'}])
    entry.assert_no_journal_or_effects()


@pytest.mark.parametrize('env', [ {}, {'DATABASE_URL': ''},
    {'DATABASE_URL': 'postgresql://owner:sentinel@other.invalid/app'},
    {'DATABASE_URL': SECRET_URL, 'PGHOST': 'other.invalid'},
    {'DATABASE_URL': SECRET_URL, 'database_url': SECRET_URL},
    {'DATABASE_URL': SECRET_URL + '?host=other.invalid'}])
def test_candidate_database_refuses_before_journal(entry, env):
    model = entry.model()
    model['services']['backend']['environment'] = {**CLOSED_GATES, 'PASTORAI_RELEASE_SHA': entry.world.spec.sha, **env}
    entry.model = lambda: model
    assert entry.execute() == (2, [{'refused': 'window-candidate-database'}])
    entry.assert_no_journal_or_effects()


@pytest.mark.parametrize('gate', list(CLOSED_GATES))
@pytest.mark.parametrize('value', ['true', 'false'])
def test_gate_variant_after_creation_refuses_without_start(entry, gate, value):
    def drift():
        backend = entry.world.cdocker.containers[CANDIDATE_IDS['backend']]
        backend['env'].append(gate.lower() + '=' + value)
    entry.world.cdocker.on_create = drift
    code, lines = entry.execute()
    assert code == 2 and lines[-1]['refused'] == 'window-transition-refused'
    journal = entry.journal_text()
    assert 'candidate-inspect-gates' in journal and 'a9:start-backend' not in journal
    assert entry.world.cdocker.starts == 0 and 'transition-a9-complete' not in journal
    assert SECRET_URL not in journal + json.dumps(lines)
    entry.world.consumers_held()
    for ident in LEGACY.values():
        state = entry.world.rig.docker.containers[ident]
        assert state['State']['Running'] is False and state['RestartPolicy'] == 'no'
    for ident in SUPPORT.values():
        state = entry.world.rig.docker.containers[ident]
        assert state['State']['Running'] is True and state['RestartPolicy'] == 'always'
    assert all(binding.observe(binding.scope, timeout=5) == 'blocked'
               for binding in entry.assembly.ingress.values())


@pytest.mark.parametrize('value', ['postgresql://other:sentinel@other.invalid/app', '',
                                  SECRET_URL + '?hostaddr=127.0.0.1'])
def test_database_drift_after_creation_refuses_without_start(entry, value):
    def drift():
        entry.world.cdocker.containers[CANDIDATE_IDS['backend']]['database_env'] = ['DATABASE_URL=' + value]
    entry.world.cdocker.on_create = drift
    code, lines = entry.execute()
    assert code == 2 and lines[-1]['refused'] == 'window-transition-refused'
    journal = entry.journal_text()
    assert 'window-candidate-database' in journal and 'a9:start-backend' not in journal
    assert entry.world.cdocker.starts == 0 and 'transition-a9-complete' not in journal
    assert SECRET_URL not in journal + json.dumps(lines)
    if value:
        assert value not in journal + json.dumps(lines)
    entry.world.consumers_held()
    for ident in LEGACY.values():
        state = entry.world.rig.docker.containers[ident]
        assert state['State']['Running'] is False and state['RestartPolicy'] == 'no'
    for ident in SUPPORT.values():
        state = entry.world.rig.docker.containers[ident]
        assert state['State']['Running'] is True and state['RestartPolicy'] == 'always'
    assert all(binding.observe(binding.scope, timeout=5) == 'blocked'
               for binding in entry.assembly.ingress.values())


@pytest.mark.parametrize('url', ['postgresql://other:fictional@DB.EXAMPLE.INVALID:5432/app',
                                'postgresql+psycopg2://other:fictional@db.example.invalid/app?sslmode=require'])
def test_candidate_database_roles_and_normalization_to_a9(entry, url):
    from first_transition_candidate import DATABASE_NAMES
    model = entry.model()
    for service in model['services'].values():
        service['environment']['DATABASE_URL'] = url
        service['environment'].update({name: '' for name in DATABASE_NAMES[1:]})
    entry.model = lambda: model
    entry.world.cdocker.database_env = ['DATABASE_URL=' + url]
    code, lines = entry.execute()
    assert code == 0 and lines[-1]['production_ready'] is False
    assert lines[-1]['consumers'] == 'held' and entry.world.cdocker.starts == 1
    entry.world.consumers_held()
    text = entry.journal_text() + json.dumps(lines)
    assert url not in text and SECRET_URL not in text and 'fictional' not in text


def test_a10_mode_needs_its_token_and_a_wrong_one_changes_nothing(entry):
    code, lines = entry.execute()
    assert code == 0 and re.fullmatch('[0-9a-f]{64}', lines[-1]['a10_token'])
    d = entry.prepare()
    digests = ['--expect-plan-digest', d['plan_digest'], '--expect-window-digest', d['window_digest']]
    before = (list(entry.world.legacy_effects()), list(entry.world.cdocker.effects()))
    for argv, refused in (([*entry.args('a10'), *digests], 'window-a10-token'),
                          ([*entry.args('run'), *digests, '--a10-token', lines[-1]['a10_token']], 'window-a10-token'),
                          ([*entry.args('a10'), *digests, '--a10-token', 'abc'], 'window-a10-token')):
        out = []
        assert window.main(argv, out=out.append, io=entry.io) == 2
        assert json.loads(out[-1]) == {'refused': refused}
    out = []
    assert window.main([*entry.args('a10'), *digests, '--a10-token', '0' * 64], out=out.append, io=entry.io) == 2
    answer = json.loads(out[-1])
    assert answer['refused'] == 'window-transition-refused' and answer['recovery']['state'] == 'a9-complete'
    assert (entry.world.legacy_effects(), entry.world.cdocker.effects()) == before
    entry.world.consumers_held()


def test_prepare_layout_writes_layout_and_hold_without_secret_daemon_or_journal(entry):
    import shutil
    spec = entry.world.spec
    target = Path(spec.release_root) / spec.sha
    shutil.rmtree(target)
    Path(spec.hold_override).unlink()
    lines = []
    argv = ['prepare-layout', '--config', str(entry.paths['config'])]
    assert window.main(argv, out=lines.append, io=entry.io) == 0, lines
    result = json.loads(lines[-1])
    assert result['assertions_are_authorization'] is False and result['production_ready'] is False
    assert result['layout'] == str(target) and target.is_dir() and Path(spec.hold_override).is_file()
    assert entry.calls == [] and entry.connections == [] and entry.assembly.popen_calls == []
    entry.assert_no_journal_or_effects()
    # Idempotent: a second call only verifies; the window readiness then accepts the layout.
    assert window.main(argv, out=lines.append, io=entry.io) == 0, lines
    code, out = entry.execute()
    assert code == 0, out


def test_prepare_layout_never_overwrites_a_different_hold_file(entry):
    Path(entry.world.spec.hold_override).write_text('services: {}\n')
    lines = []
    assert window.main(['prepare-layout', '--config', str(entry.paths['config'])], out=lines.append,
                       io=entry.io) == 2
    assert json.loads(lines[-1]) == {'refused': 'candidate-hold-mismatch'}
    assert Path(entry.world.spec.hold_override).read_text() == 'services: {}\n'
    entry.assert_no_journal_or_effects()


def test_run_without_the_pinned_restore_exclusions_refuses_before_any_effect(entry):
    del entry.backup['restore_excluded_expected']
    entry.write()
    d = entry.prepare()  # prepare itself still works (the rehearsal needs it) but says the pin is missing
    exit_code, lines = entry.execute(d)
    assert exit_code == 2 and lines == [{'refused': 'window-backup-restore-excluded'}]
    assert entry.calls == [] and entry.connections == [] and entry.assembly.popen_calls == []
    entry.assert_no_journal_or_effects()


def test_status_is_readonly_before_and_after_failures_without_db_or_journal_writes(entry):
    lines = []
    assert window.main(['status', '--config', str(entry.paths['config'])], out=lines.append, io=entry.io) == 0
    initial = json.loads(lines[-1])
    assert initial['state'] == 'not-started'
    assert initial['journal_present'] is False and initial['legacy_resume_allowed'] is False
    assert initial['resume_token'] is None and initial['assertions_are_authorization'] is False
    entry.assert_no_journal_or_effects()
    assert entry.connections == [] and entry.calls == []

    # Pre-DDL failure: backup refuses after containment; status classifies without touching DB or journal.
    entry.backup_io.fail = {'dump'}
    assert entry.execute()[0] == 2
    before_journal = entry.journal_text()
    entry.connections.clear()
    entry.calls.clear()
    lines.clear()
    assert window.main(entry.args('status'), out=lines.append, io=entry.io) == 0
    pre_ddl = json.loads(lines[-1])
    assert pre_ddl['state'] == 'backup-window-used' and pre_ddl['journal_present'] is True
    assert pre_ddl['legacy_resume_allowed'] is True and pre_ddl['resume_token'].startswith('RESUME:')
    assert entry.journal_text() == before_journal
    assert entry.connections == [] and entry.calls == []


def test_status_after_abrupt_ddl_marker_crash_does_not_mutate_journal(entry):
    from initial_transition_files import Journal
    d = entry.prepare()
    with Journal(Path(entry.raw['state_dir']) / 'journal') as j:
        j.append('ddl-marker', irrevocable=True, window_backup_id='a' * 64)
    before_journal = entry.journal_text()
    lines = []
    assert window.main(['status', '--config', str(entry.paths['config'])], out=lines.append, io=entry.io) == 0
    report = json.loads(lines[-1])
    assert report['state'] == 'post-ddl-failed' and report['legacy_resume_allowed'] is False
    assert report['resume_token'] is None and report['window_backup_id'] == 'a' * 64
    assert entry.journal_text() == before_journal
    assert entry.connections == [] and entry.calls == [] and d['plan_digest']


def test_cli_resume_legacy_pre_marker_and_post_marker_refusal(entry):
    entry.backup_io.fail = {'dump'}
    assert entry.execute()[0] == 2
    lines = []
    assert window.main(['status', '--config', str(entry.paths['config'])], out=lines.append, io=entry.io) == 0
    tok = json.loads(lines[-1])['resume_token']
    d = entry.prepare()
    digests = ['--expect-plan-digest', d['plan_digest'], '--expect-window-digest', d['window_digest']]

    # Missing resume token fails cleanly before opening journal effects.
    bad = []
    assert window.main([*entry.args('resume-legacy'), *digests], out=bad.append, io=entry.io) == 2
    assert json.loads(bad[-1]) == {'refused': 'window-resume-token'}

    out = []
    assert window.main([*entry.args('resume-legacy'), *digests, '--resume-token', tok],
                       out=out.append, io=entry.io) == 0
    assert json.loads(out[-1])['status'] == 'legacy-resumed'

    after = []
    assert window.main(['status', '--config', str(entry.paths['config'])], out=after.append, io=entry.io) == 0
    assert json.loads(after[-1])['state'] == 'legacy-resumed'
    assert json.loads(after[-1])['legacy_resume_allowed'] is False


def test_cli_resume_legacy_refuses_after_ddl_marker(entry):
    tx = next(m for m in entry.world.plan.pending if not m.concurrent)
    entry.world.migrate.faults[tx.name] = 'fail'
    assert entry.execute()[0] == 2
    d = entry.prepare()
    digests = ['--expect-plan-digest', d['plan_digest'], '--expect-window-digest', d['window_digest']]
    out = []
    assert window.main([*entry.args('resume-legacy'), *digests, '--resume-token', 'RESUME:' + '0' * 64],
                       out=out.append, io=entry.io) == 2
    result = json.loads(out[-1])
    assert result['refused'] == 'window-transition-refused'
    assert result['recovery']['state'] == 'ddl-failed' and result['recovery']['legacy_resume_allowed'] is False
    assert all(b.observe(b.scope, timeout=5) == 'blocked' for b in entry.assembly.ingress.values())
    assert all(entry.world.rig.docker.containers[i]['State']['Running'] is False for i in LEGACY.values())
    assert not any(a[:2] == ('docker', 'start') for a in entry.world.rig.docker.calls)
