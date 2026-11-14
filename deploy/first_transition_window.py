"""First-transition entry: prepare/observe, an explicitly configured run ending at A9, or A10.

``a10`` is its own invocation: same inputs and journal as ``run``, plus ``--a10-token`` (printed
by the A9 result). It brings the three consumers up with the gates captured from the legacy
before the window (first_transition_a10); the token is a typo/binding guard, NOT authorization.

Expected digests are typo guards, NOT human authorization. Operations require the
operator's separate nominal approval. Nothing is contacted at import. Secrets are
read only from the explicitly selected private file/variable, never inherited.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time
from urllib.parse import parse_qsl, urlsplit

from first_transition_candidate import check_closed_gates, check_candidate_database
import first_transition_database as fdb
from first_transition_adapter import digest, prepare
from first_transition_candidate import (CLOSED_GATES, CandidatePort, CandidateRunner, topology_contract,
                                        verify_candidate_release, write_candidate_release, write_hold_override)
from first_transition_orchestrator import assemble, classify_recovery, load_config
from first_transition_window_backup import BACKUP_CODES, REHEARSAL_SCHEMA, WindowBackup, WindowBackupConfig
from first_transition_window_bindings import (UnknownWriters, bindings_from_dict, validate_bindings_config)
from initial_transition_files import Journal, read_regular
from initial_transition_ops import Refused, require
import release_topology

ENV_NAME = re.compile(r'[A-Z_][A-Z0-9_]{0,62}')
IMAGE_TEMPLATE = ('[{{json .Id}},{{json .RepoDigests}},{{json .Os}},'
                  '{{with .Config.Labels}}{{index . "org.opencontainers.image.revision" | json}}'
                  '{{else}}null{{end}},'
                  '[{{range .Config.Env}}{{if eq (index (split . "=") 0) "PG_MAJOR"}}{{json .}},{{end}}{{end}}null],'
                  '{{json .Architecture}}]')
PLATFORM_TEMPLATE = '[{{json .OSType}},{{json .Architecture}}]'
NETWORK_TEMPLATE = ('[{{json .Id}},{{json .Name}},{{json .Driver}},'
                    '{{with .Options}}{{index . "com.docker.network.bridge.name" | json}}'
                    '{{else}}null{{end}}]')
RUNTIME_PROBE = 'import sys,psycopg2,json; print(json.dumps([list(sys.version_info[:2]),psycopg2.__version__]))'
Q_VERSION = "SELECT current_setting('server_version_num')::int"
Q_EXECUTOR = ("SELECT current_user, c.relowner=r.oid AND has_schema_privilege('public','CREATE') "
              "AND (r.rolsuper OR r.rolcreaterole) FROM pg_class c CROSS JOIN pg_roles r "
              "WHERE c.oid='public.schema_migrations'::regclass AND r.rolname=current_user")
# Only literal codes owned by this entry or explicitly safe binding diagnostics may leave it.
CODES = frozenset({
    'window-arguments', 'window-run-prerequisites', 'window-bindings-config-missing', 'window-backup-config-missing',
    'window-config-invalid', 'window-bindings-config', 'window-bindings-scope', 'window-bindings-bridge',
    'window-bindings-declarations', 'window-bindings-docker', 'window-backup-docker', 'window-backup-python',
    'window-plan-digest', 'window-window-digest', 'window-env-file', 'window-env-file-mode', 'window-env-secret',
    'window-inputs-changed', 'window-journal-unbound', 'window-prerequisite', 'window-runtime',
    'window-image', 'window-network', 'window-compose', 'window-source-version', 'window-backup-version',
    'window-nginx-topology', 'window-nginx-include-missing', 'window-bindings-shape', 'window-new-ingress',
    'window-writer-required', 'window-bindings-refused', 'window-backup-config-keys',
    'window-backup-isolation',
    'window-executor-role', 'window-candidate-database', 'database-libpq-environment',
    'window-backup-image-unpinned', 'window-backup-paths', 'window-backup-timeouts',
    'package-identity-mismatch', 'candidate-layout-not-prepared', 'candidate-hold-mismatch', 'layout-mismatch',
    'window-a10-token', 'window-resume-token', 'journal-torn', 'journal-invalid', 'state-not-directory',
    'clone-source-schema-divergence',
}) | BACKUP_CODES  # literal, secret-free codes of the backup provider (cause of a failed rehearsal/window)


def _code(exc):
    return str(exc) if isinstance(exc, Refused) and str(exc) in CODES else 'window-refused'


def _private_file(path, fstat=None):
    require(isinstance(path, str) and os.path.isabs(path) and '\x00' not in path, 'window-env-file')
    try:
        for part in (Path(path), *Path(path).parents):
            require(not stat.S_ISLNK(os.lstat(part).st_mode), 'window-env-file')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as handle:
            info = (fstat or os.fstat)(handle.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
                    and stat.S_IMODE(info.st_mode) in (0o400, 0o600) and info.st_size <= 256 * 1024,
                    'window-env-file-mode')
            data = handle.read(256 * 1024 + 1)
        require(len(data) <= 256 * 1024, 'window-env-file-mode')
        return data.decode('utf-8')
    except (OSError, UnicodeError):
        raise Refused('window-env-file') from None


def env_file_secret(path, name='DATABASE_URL', *, fstat=None):
    """One root-owned 0400/0600 regular file, no symlink; no fallback to environment."""
    require(isinstance(path, str) and os.path.isabs(path) and ENV_NAME.fullmatch(name), 'window-env-file')

    def secret():
        values = []
        for line in _private_file(path, fstat).splitlines():
            match = re.match(r'\s*(?:export\s+)?' + name + r'\s*=(.*)', line)
            if match:
                values.append(match.group(1).strip().strip('"\''))
        require(len(values) == 1 and values[0].startswith('postgresql://')
                and not any(c in values[0] for c in '\r\n\x00'), 'window-env-secret')
        try:
            uri = urlsplit(values[0])
            options = parse_qsl(uri.query, keep_blank_values=True)
            require(uri.hostname and uri.username and uri.password and uri.path.startswith('/')
                    and len(uri.path) > 1 and not uri.fragment and 0 < (uri.port or 5432) < 65536
                    and len(dict(options)) == len(options) and {k for k, _ in options} <= {
                        'sslmode', 'connect_timeout', 'application_name', 'channel_binding', 'gssencmode',
                        'target_session_attrs'}, 'window-env-secret')
        except ValueError:
            raise Refused('window-env-secret') from None
        return values[0]
    return secret


def _json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'window-config-invalid')
            result[key] = value
        return result
    try:
        return json.loads(read_regular(Path(path), 64 * 1024), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Refused('window-config-invalid')))
    except (ValueError, OSError, TypeError):
        raise Refused('window-config-invalid') from None


@dataclass(frozen=True)
class Prepared:
    config: object
    plan: object
    backup: WindowBackupConfig
    bindings: dict
    record: dict

    @property
    def window_digest(self):
        return digest(self.record)


def prepare_window(args):
    require(all(getattr(args, k, None) for k in ('config', 'backup_config', 'bindings_config', 'env_file', 'env_var')),
            'window-run-prerequisites')
    io = getattr(args, '_io', {})
    raw = _json(args.config)
    config = load_config(Path(args.config))
    require(config.digest == digest(raw), 'window-config-invalid')
    plan = prepare(Path(config.repo), git=io.get('git'))
    backup = WindowBackupConfig.from_dict(_json(args.backup_config))
    bindings = validate_bindings_config(_json(args.bindings_config), config=config)
    require((backup.docker_binary, backup.docker_endpoint, backup.docker_config_dir) == config.docker,
            'window-backup-docker')
    require(backup.python == config.python, 'window-backup-python')
    CandidateRunner(config.candidate, docker_binary=config.docker[0], endpoint=config.docker[1],
                    config_dir=config.docker[2])  # pure constructor validation, no CLI invocation
    require(backup.clone_command in (
        ('postgres', '-c', 'shared_preload_libraries='),
        ('postgres', '-c', 'shared_preload_libraries=pg_stat_statements'),
        ('postgres', '-c', 'shared_preload_libraries=pgsodium,pg_stat_statements'),
    ), 'window-backup-isolation')
    require(os.path.isabs(args.env_file) and '\x00' not in args.env_file and ENV_NAME.fullmatch(args.env_var),
            'window-env-file')
    record = dict(schema='igreja12.window/1', plan_digest=plan.digest, transition_digest=config.digest,
                  backup_digest=digest(asdict(backup)), bindings_digest=digest(bindings),
                  provider_digest=digest(dict(path=args.env_file, variable=args.env_var)))
    return Prepared(config, plan, backup, bindings, record)


def _load(args):
    fdb.require_explicit_environment()
    io = getattr(args, '_io', {})
    config = load_config(Path(args.config))
    plan = prepare(Path(config.repo), git=io.get('git'))
    expected = fdb.DatabaseExpectation(config.identity, plan.baseline, config.catalog).validated()
    secret = env_file_secret(args.env_file, getattr(args, 'env_var', None) or 'DATABASE_URL',
                             fstat=io.get('secret_fstat'))
    database = fdb.ReadOnlyDatabase(fdb.psycopg2_connector(secret, connect=io.get('connect')),
                                    lease_columns=config.lease_columns,
                                    observer_applications=config.observer_applications)
    return config, plan, expected, secret, database


def _bindings(data, config, secret, database, io):
    normalized = validate_bindings_config(data, config=config)
    return bindings_from_dict(normalized, secret=secret, connect=database.connect, run=io.get('binding_run'),
                              proc=io.get('proc', '/proc'), owner_uid=io.get('nginx_owner_uid', 0),
                              endpoint=io.get('endpoint'))


def _observe_bindings(ingress, writers, timeout):
    result = {}
    for name, binding in (*ingress.items(), ('unknown_writers', writers)):
        try:
            value = binding.observe(binding.scope, timeout=timeout)
            require(type(value) is int and 0 <= value <= 10**6 if name == 'unknown_writers'
                    else type(value) is str and value in ('open', 'blocked'), 'window-bindings-shape')
            result[name] = value
        except Exception as exc:
            result[name] = 'refused:' + (_code(exc) if isinstance(exc, Refused) else 'window-bindings-refused')
    return result


def check_bindings(args, out=print):
    config, _, _, secret, database = _load(args)
    ingress, writers = _bindings(_json(args.bindings_config), config, secret, database, args._io)
    result = _observe_bindings(ingress, writers, dict(config.timeouts).get('observe_s', 10))
    out(json.dumps(result, sort_keys=True))
    return 0 if result['unknown_writers'] == 0 and all(result[k] in ('open', 'blocked') for k in ingress) else 1


def _read_command(args, argv, *, env=None):
    io = args._io
    run = io.get('run') or subprocess.run
    try:
        done = run(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                   env=env or {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'PYTHON_DOTENV_DISABLED': '1'},
                   cwd='/', timeout=30, close_fds=True, shell=False, check=False)
        require(done.returncode == 0 and type(done.stdout) is bytes and len(done.stdout) <= 256 * 1024,
                'window-prerequisite')
        return json.loads(done.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise Refused('window-prerequisite') from None


def _source_version(connect, expected_user):
    conn = connect(timeout=10)
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(fdb.Q_BEGIN)
        try:
            cur.execute(fdb.Q_TIMEOUT, ('10000ms',))
            cur.fetchall()
            cur.execute(fdb.Q_PATH)
            cur.fetchall()
            cur.execute(Q_VERSION)
            rows = cur.fetchall()
            cur.execute(Q_EXECUTOR)
            privileges = cur.fetchall()
        finally:
            cur.execute('ROLLBACK')
    finally:
        conn.close()
    require(len(rows) == 1 and type(rows[0][0]) is int and rows[0][0] >= 100000, 'window-source-version')
    require(privileges == [(expected_user, True)] and type(privileges[0][1]) is bool, 'window-executor-role')
    return rows[0][0] // 10000


def _readiness(args, prepared, secret, database, ingress):
    c, b, io = prepared.config, prepared.backup, args._io
    verify_candidate_release(c.repo, c.candidate, c.manifest, package_manifest_sha256=c.package_manifest_sha256,
                             git=io.get('git'))
    for path in (c.state_dir, c.migration_workdir, c.candidate.release_root, c.docker[2], b.backup_root, b.clone_workdir):
        # Runtime backup directories may be named "backups": inspect only metadata,
        # never pass their contents to the artifact reader or generate anything here.
        try:
            for part in (Path(path), *Path(path).parents):
                require(stat.S_ISDIR(os.lstat(part).st_mode), 'window-prerequisite')
        except OSError:
            raise Refused('window-prerequisite') from None
    stat_file = io.get('stat', os.stat)
    binaries = (c.python, c.docker[0], *(prepared.bindings['nginx'][k] for k in (
        'nginx_binary', 'systemctl_binary', 'curl_binary')), prepared.bindings['bridge']['nft_binary'])
    for path in binaries:
        mode = stat_file(path).st_mode
        require(stat.S_ISREG(mode) and mode & 0o111, 'window-prerequisite')
    runtime = _read_command(args, (c.python, '-I', '-c', RUNTIME_PROBE))
    require(isinstance(runtime, list) and len(runtime) == 2 and runtime[0] == [3, 13]
            and isinstance(runtime[1], str) and runtime[1].startswith('2.'), 'window-runtime')
    # Require a private candidate configuration and validate all occurrences of every gate.
    file_env = []
    for line in _private_file(c.candidate.env_file, io.get('secret_fstat')).splitlines():
        match = re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)', line)
        if match:
            file_env.append((match[1], match[2].strip().strip('"\'')))
    check_closed_gates(file_env, code='window-compose')
    prefix = (c.docker[0], '--config', c.docker[2], '--host', c.docker[1])
    CandidatePort(c.candidate, runner=CandidateRunner(c.candidate, docker_binary=c.docker[0], endpoint=c.docker[1],
                                                     config_dir=c.docker[2], popen=io.get('popen'))).project_ids()
    platform = _read_command(args, (*prefix, 'info', '--format', PLATFORM_TEMPLATE))
    architectures = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}
    require(isinstance(platform, list) and len(platform) == 2 and platform[0] == 'linux'
            and isinstance(platform[1], str) and platform[1] in architectures, 'window-runtime')
    network = _read_command(args, (*prefix, 'network', 'inspect', '--format', NETWORK_TEMPLATE, c.manifest.network_id))
    require(isinstance(network, list) and len(network) == 4
            and network[:3] == [c.manifest.network_id, c.candidate.network_name, 'bridge']
            and network[3] in (None, '', prepared.bindings['bridge']['bridge']), 'window-network')
    require(stat.S_ISDIR(stat_file('/sys/class/net/' + prepared.bindings['bridge']['bridge'] + '/bridge').st_mode),
            'window-network')
    fdb.require_same_database(database.observe(), fdb.DatabaseExpectation(
        c.identity, prepared.plan.baseline, c.catalog).validated())
    source_major = _source_version(database.connect, b.migration_user)
    majors = []
    for image in (c.candidate.image, b.dump_image, b.clone_image):
        meta = _read_command(args, (*prefix, 'image', 'inspect', '--format', IMAGE_TEMPLATE, image))
        require(isinstance(meta, list) and len(meta) == 6 and meta[2] == 'linux'
                and meta[5] == architectures[platform[1]]
                and isinstance(meta[0], str) and re.fullmatch(r'sha256:[0-9a-f]{64}', meta[0]), 'window-image')
        if image == c.candidate.image:
            require(meta[0] == image and meta[3] == c.candidate.sha, 'window-image')
        else:
            require(isinstance(meta[1], list) and image in meta[1] and isinstance(meta[4], list)
                    and len(meta[4]) == 2 and meta[4][-1] is None
                    and isinstance(meta[4][0], str) and re.fullmatch(r'PG_MAJOR=\d{2}', meta[4][0]), 'window-image')
            majors.append(int(meta[4][0].split('=')[1]))
    require(majors[1] >= majors[0] >= source_major, 'window-backup-version')
    # Hold/layout must already exist: this read-only command cannot repair or pull anything.
    compose = c.candidate.compose_argv()
    compose = (*compose[:compose.index('up')], 'config', '--format', 'json')
    model = _read_command(args, (*prefix, *compose[1:]), env={
        'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'PASTORAI_ENV_FILE': c.candidate.env_file})
    try:
        release_topology.check_config(topology_contract(c.candidate, c.manifest), model)
    except release_topology.Refused:
        raise Refused('window-compose') from None
    for role, service in model['services'].items():
        env = service.get('environment', {})
        require(service.get('image') == c.candidate.image and service.get('restart') == 'no'
                and isinstance(env, dict) and env.get('PASTORAI_RELEASE_SHA') == c.candidate.sha, 'window-compose')
        check_closed_gates(env.items(), code='window-compose')
        check_candidate_database(env.items(), secret())
        ports = service.get('ports', [])
        require(ports == [] if role != 'backend' else isinstance(ports, list) and len(ports) == 1
                and ports[0].get('host_ip') == '127.0.0.1' and str(ports[0].get('published')) == '8000'
                and ports[0].get('target') == 8000 and ports[0].get('protocol', 'tcp') == 'tcp', 'window-compose')
    ingress['external'].verify_topology()
    for binding in ingress.values():
        require(binding.observe(binding.scope, timeout=10) in ('open', 'blocked'), 'window-bindings-shape')


def prepare_layout(args, out=print):
    """Eve of the window: write (or verify byte for byte) ``<release_root>/<sha>`` and the A9 hold file.

    ``run`` refuses unless both already exist (``_readiness``), and the same writers run again inside
    ``run`` as an exclusive-or-identical check. Public configuration only: no secret, database,
    Docker daemon, journal, ingress or legacy process is touched. Writing files on the target host
    still needs the operator's separate approval.
    """
    io = args._io
    raw = _json(args.config)
    config = load_config(Path(args.config))
    require(config.digest == digest(raw), 'window-config-invalid')
    plan = prepare(Path(config.repo), git=io.get('git'))
    files = write_candidate_release(config.repo, config.candidate, config.manifest,
                                    migrations=[m.name for m in plan.migrations],
                                    package_manifest_sha256=config.package_manifest_sha256, git=io.get('git'))
    write_hold_override(config.candidate)
    verify_candidate_release(config.repo, config.candidate, config.manifest,
                             package_manifest_sha256=config.package_manifest_sha256, git=io.get('git'))
    out(json.dumps(dict(layout=str(Path(config.candidate.release_root) / config.candidate.sha), files=files,
                        hold_override=config.candidate.hold_override, plan_digest=plan.digest,
                        assertions_are_authorization=False, production_ready=False), sort_keys=True))
    return 0


def _init_inputs(args):
    fdb.require_explicit_environment()
    require(args.expect_plan_digest and args.expect_window_digest, 'window-run-prerequisites')
    prepared = prepare_window(args)
    require(args.expect_plan_digest == prepared.plan.digest, 'window-plan-digest')
    require(args.expect_window_digest == prepared.window_digest, 'window-window-digest')
    return prepared


def _open_bindings(args, prepared):
    io, c = args._io, prepared.config
    secret = env_file_secret(args.env_file, args.env_var, fstat=io.get('secret_fstat'))
    secret()  # Validate the one explicit provider before any journal or host effect.
    database = fdb.ReadOnlyDatabase(fdb.psycopg2_connector(secret, connect=io.get('connect')),
                                    lease_columns=c.lease_columns, observer_applications=c.observer_applications)
    ingress, writers = _bindings(prepared.bindings, c, secret, database, io)
    return secret, database, ingress, writers


def _assemble_transition(args, prepared, journal, secret, database, ingress, writers):
    io, c = args._io, prepared.config
    expected = fdb.DatabaseExpectation(c.identity, prepared.plan.baseline, c.catalog).validated()
    backup = WindowBackup(prepared.backup, prepared.plan, expected, secret=secret, connect=database.connect,
                          run=io.get('run'), clone_connect=io.get('clone_connect'), migrate_run=io.get('run'),
                          sleep=io.get('sleep'))
    return assemble(c, plan=prepared.plan, journal=journal, connect=database.connect, secret=secret,
                    ingress=ingress, writers=writers, backup_proof=backup, popen=io.get('popen'),
                    run=io.get('run'), sleep=io.get('sleep') or time.sleep, git=io.get('git'))


def run(args, out=print, *, a10=False):
    prepared = _init_inputs(args)
    token = getattr(args, 'a10_token', None)
    require(bool(token) == a10 and (not a10 or re.fullmatch('[0-9a-f]{64}', token)), 'window-a10-token')
    c = prepared.config
    # Before any journal, quiescence or host effect: a window without the pinned restore exclusions is lost late.
    require(prepared.backup.restore_excluded_expected, 'window-backup-restore-excluded')
    secret, database, ingress, writers = _open_bindings(args, prepared)
    require(isinstance(writers, UnknownWriters) and callable(writers.bind_candidate), 'window-writer-required')
    _readiness(args, prepared, secret, database, ingress)
    with Journal(Path(c.state_dir) / 'journal') as journal:
        init = journal.last('window-init')
        values = {**prepared.record, 'window_digest': prepared.window_digest}
        if init is None:
            require(not journal.events, 'window-journal-unbound')
            journal.append('window-init', **values)
        else:
            require(journal.events[0] is init and all(init.get(k) == v for k, v in values.items()),
                    'window-inputs-changed')
        transition = _assemble_transition(args, prepared, journal, secret, database, ingress, writers)
        try:
            result = transition.a10(token) if a10 else transition.run()
        except BaseException as exc:
            code = 'window-transition-refused' if isinstance(exc, Exception) else 'window-transition-interrupted'
            out(json.dumps(dict(refused=code, recovery=transition.recovery(),
                                assertions_are_authorization=False), sort_keys=True))
            return 2
    out(json.dumps({**result, 'assertions_are_authorization': False}, sort_keys=True))
    return 0


def status(args, out=print):
    """Read-only journal state and recovery classification; touches no DB, host, or journal."""
    raw = _json(args.config)
    config = load_config(Path(args.config))
    require(config.digest == digest(raw), 'window-config-invalid')
    journal = Journal(Path(config.state_dir) / 'journal').read()
    recovery = classify_recovery(journal)
    init = journal.last('observed-host-init')
    token = ('RESUME:' + init['fingerprint']) if (recovery['legacy_resume_allowed'] and init is not None) else None
    out(json.dumps({**recovery, 'resume_token': token, 'journal_present': os.path.lexists(journal.path),
                    'assertions_are_authorization': False}, sort_keys=True))
    return 0


def resume_legacy(args, out=print):
    """Pre-DDL resume of the legacy containers through the same journal."""
    token = getattr(args, 'resume_token', None)
    require(isinstance(token, str) and bool(token), 'window-resume-token')
    prepared = _init_inputs(args)
    c = prepared.config
    secret, database, ingress, writers = _open_bindings(args, prepared)
    journal_dir = Path(c.state_dir) / 'journal'
    require(Journal(journal_dir).read().last('window-init') is not None, 'window-journal-unbound')
    with Journal(journal_dir) as journal:
        init = journal.last('window-init')
        values = {**prepared.record, 'window_digest': prepared.window_digest}
        require(init is not None, 'window-journal-unbound')
        require(journal.events[0] is init and all(init.get(k) == v for k, v in values.items()),
                'window-inputs-changed')
        transition = _assemble_transition(args, prepared, journal, secret, database, ingress, writers)
        try:
            result = transition.resume_legacy(token, allow_queue_drift=bool(getattr(args, 'allow_queue_drift', False)))
        except BaseException as exc:  # noqa: BLE001 - surface interruption as CLI exit 2 with recovery diagnostics
            code = 'window-transition-refused' if isinstance(exc, Exception) else 'window-transition-interrupted'
            out(json.dumps(dict(refused=code, recovery=transition.recovery(),
                                assertions_are_authorization=False), sort_keys=True))
            return 2
    out(json.dumps({**result, 'assertions_are_authorization': False}, sort_keys=True))
    return 0


def check(args, out=print):
    config, plan, expected, _, database = _load(args)
    out(json.dumps(dict(plan_digest=plan.digest, baseline=len(plan.baseline), pending=len(plan.pending))))
    results = []
    for attempt in (1, 2):
        observation = database.observe(timeout=dict(config.timeouts).get('observe_s', 10))
        checks = {}
        for label, function in (('same_database', fdb.require_same_database), ('ddl_free', fdb.require_ddl_free)):
            try:
                function(observation, expected)
                checks[label] = 'ok'
            except Refused as exc:
                checks[label] = _code(exc)
        try:
            fdb.require_quiet(observation)
            checks['quiet'] = 'ok'
        except Refused as exc:
            checks['quiet'] = _code(exc)
        results.append(checks)
        out(json.dumps(dict(observation=attempt, summary=fdb.summary(observation), checks=checks), sort_keys=True))
    return 0 if all(c['same_database'] == 'ok' and c['ddl_free'] == 'ok' for c in results) else 1


def rehearse_backup(args, out=print):
    config, plan, expected, secret, database = _load(args)
    backup_config = WindowBackupConfig.from_dict(_json(args.backup_config))
    fdb.require_ddl_free(database.observe(), expected)
    request = dict(schema=REHEARSAL_SCHEMA, nonce=secrets.token_hex(32), plan_digest=plan.digest,
                   source_identity=expected.identity, baseline_digest=expected.baseline_digest)
    receipt = WindowBackup(backup_config, plan, expected, secret=secret, connect=database.connect)(request)
    out(json.dumps(receipt, sort_keys=True, indent=1))
    return 0


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused('window-arguments')


def main(argv=None, out=print, *, io=None):
    parser = _Parser(prog='first_transition_window', description='Expected digests are NOT human authorization.')
    parser.add_argument('mode', choices=('prepare', 'prepare-layout', 'check', 'rehearse-backup', 'check-bindings',
                                         'status', 'resume-legacy', 'run', 'a10'))
    parser.add_argument('--config', required=True)
    parser.add_argument('--env-file')
    parser.add_argument('--env-var', help='Explicit variable in the private file; required for prepare/run.')
    parser.add_argument('--backup-config')
    parser.add_argument('--bindings-config')
    parser.add_argument('--expect-plan-digest', help='Exact typo guard, NOT human authorization.')
    parser.add_argument('--expect-window-digest', help='Exact typo guard, NOT human authorization.')
    parser.add_argument('--a10-token', help='Only for a10: token printed by the A9 result, NOT human authorization.')
    parser.add_argument('--resume-token', help='Only for resume-legacy: token from status/journal, NOT human authorization.')
    parser.add_argument('--allow-queue-drift', action='store_true',
                        help='Only for resume-legacy: accept queue drift observed since settlement.')
    try:
        args = parser.parse_args(argv)
        args._io = io or {}
        if args.mode == 'prepare':
            p = prepare_window(args)
            out(json.dumps(dict(plan_digest=p.plan.digest, window_digest=p.window_digest,
                                restore_excluded_pinned=bool(p.backup.restore_excluded_expected),
                                assertions_are_authorization=False, production_ready=False), sort_keys=True))
            return 0
        if args.mode == 'prepare-layout':
            return prepare_layout(args, out)
        if args.mode == 'status':
            return status(args, out)
        if args.mode == 'resume-legacy':
            return resume_legacy(args, out)
        if args.mode in ('run', 'a10'):
            return run(args, out, a10=args.mode == 'a10')
        if args.mode == 'check-bindings':
            require(args.bindings_config is not None, 'window-bindings-config-missing')
            return check_bindings(args, out)
        if args.mode == 'rehearse-backup':
            require(args.backup_config is not None, 'window-backup-config-missing')
            return rehearse_backup(args, out)
        return check(args, out)
    except Refused as exc:
        out(json.dumps(dict(refused=_code(exc))))
        return 2
    except Exception:
        out(json.dumps(dict(refused='window-failed')))
        return 2


if __name__ == '__main__':
    sys.exit(main())
