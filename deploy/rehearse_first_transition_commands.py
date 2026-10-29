"""Plan-only by default. Execute only after human approval of the printed scope.

Four new networkless Python signal fixtures, not application workers. Exercises
only the command encoder used by SimulatedHostTransport. Does not connect a
real driver to the simulation-only contract or certify ingress/queues/Compose.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
from contextlib import contextmanager
import subprocess
import tempfile
import time
from uuid import uuid4

from first_transition_adapter import ROLES
from first_transition_host_transport import host_command
from initial_transition_ops import Refused, require

OWNER = 'igreja12.transport-rehearsal'
FIXTURE = "import signal,sys,time; signal.signal(signal.SIGTERM,lambda *_:sys.exit(0)); print('fixture-ready',flush=True); exec('while True: time.sleep(0.1)')"
SOCKET = 'unix:///var/run/docker.sock'


def plan(image, run_id):
    require(isinstance(image, str) and re.fullmatch('sha256:[0-9a-f]{64}', image), 'image-must-be-local-id')
    require(isinstance(run_id, str) and re.fullmatch('[0-9a-f]{32}', run_id), 'probe-run-id')
    creates = {}
    for role in ROLES:
        name = 'igreja12-transport-probe-' + run_id + '-' + role
        creates[name] = ('docker', 'create', '--pull=never', '--name', name,
                        '--label', OWNER + '=' + run_id, '--label', 'igreja12.fixture-role=' + role,
                        '--network=none', '--no-healthcheck', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                        '--pids-limit=32', '--memory=128m', '--memory-swap=128m', '--cpus=0.25',
                        '--log-driver=local', '--log-opt=max-size=1m', '--log-opt=max-file=1', '--log-opt=compress=false', '--restart=always',
                        '--user=65534:65534', '--entrypoint=python3', image, '-I', '-u', '-c', FIXTURE)
    return dict(kind='local-disposable-command-probe', run_id=run_id, image=image,
                creates=creates, socket=SOCKET, execution_seconds=180, cleanup_seconds_per_command=5, cleanup_seconds=60,
                production_ready=False, host_verified=False,
                not_proven=['application-workers', 'Compose', 'ingress', 'Redis', 'provider-delivery',
                            'quiescence', 'database', 'daemon-restart', 'production'])


class Interrupted(BaseException):
    def __init__(self, signum):
        self.signum = signum


class Interrupts:
    def __init__(self):
        self.signum, self.count, self.protected = None, 0, False
        self.phase = 'execute'
        self.abortable = False

    def receive(self, signum, _frame=None):
        self.signum = self.signum or signum
        self.count += 1
        if not self.protected and self.phase == 'execute':
            self.phase = 'stopping'  # Outside a request, defer to the next safe point.
            if self.abortable and sys.exception() is None:
                self.abortable = False
                raise Interrupted(signum)
        if (not self.protected and self.phase == 'cleanup' and self.count >= 2
                and self.abortable and sys.exception() is None):
            self.abortable = False
            raise Interrupted(signum)

    @contextmanager
    def installed(self):
        previous = {}
        try:
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                previous[sig] = signal.signal(sig, self.receive)
            yield self
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def local_environment(environ):
    # No personal Docker config is read. Reject overrides rather than silently
    # redirecting a request intended for another host/context to this machine.
    require(environ.get('DOCKER_HOST', SOCKET) == SOCKET, 'probe-host-refused')
    require(not any(environ.get(k) for k in
                    ('DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH',
                     'CONTAINER_HOST', 'CONTAINER_CONNECTION')), 'probe-context-refused')


def exclusive_json(path, data):
    # Atomic, exclusive publication: a partial temp file is never an intent.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.state-', delete=False) as file:
            temporary = Path(file.name)
            os.chmod(temporary, 0o600)
            json.dump(data, file, sort_keys=True)
            file.flush()
            os.fsync(file.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_state(path):
    # Only operator-owned synthetic state, never a Docker config/credential.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as file:
        metadata = os.fstat(file.fileno())
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid()
                and metadata.st_size <= 8192, 'probe-state-size')
        return file.read()


def state_scope(spec, daemon):
    return dict(run_id=spec['run_id'], image=spec['image'], daemon=daemon,
                names=list(spec['creates']), socket=SOCKET, version=1)


@contextmanager
def state_lock(state):
    fd = os.open(state / 'run.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        metadata = os.fstat(fd)
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid(),
                'probe-lock-owner')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused('probe-state-busy') from None
        yield
    finally:
        os.close(fd)


def docker_request(config, interrupts):
    def request(command, *, timeout):
        require(command[0] == 'docker', 'probe-command')
        child = None
        try:
            before = interrupts.count
            interrupts.protected = True
            try:
                child = subprocess.Popen(
                    ['docker', '-H', SOCKET, '--config', config, *command[1:]],
                    env={'PATH': '/usr/bin:/bin'}, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, start_new_session=True)
            finally:
                interrupts.protected = False
            if interrupts.count != before and (interrupts.phase == 'execute' or interrupts.count >= 2):
                if interrupts.phase == 'execute':
                    interrupts.phase = 'stopping'
                raise Interrupted(interrupts.signum)
            interrupts.abortable = True
            try:
                stdout, _ = child.communicate(timeout=timeout)
            finally:
                interrupts.abortable = False
            require(child.returncode == 0, 'probe-docker-failed')
            return stdout
        except (OSError, subprocess.TimeoutExpired):
            raise Refused('probe-command-failed') from None
        finally:
            # Protect before poll too: signals must not interrupt error unwinding.
            interrupts.abortable = False
            interrupts.protected = True
            try:
                if child is not None and child.poll() is None:
                    child.terminate()
                    try:
                        child.communicate(timeout=1)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.communicate(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                raise Refused('probe-reap-failed') from None
            finally:
                interrupts.protected = False
    return request


class CommandProbe:
    def __init__(self, spec, request, state_dir, *, clock=time.monotonic, sleep=time.sleep, interrupts=None):
        self.spec, self.request, self.clock, self.sleep = spec, request, clock, sleep
        self.names, self.ids = [], []
        self.state_dir = Path(state_dir)
        self.interrupts = interrupts or Interrupts()
        self.cleanup_deadline = None
        self.deadline = clock() + spec['execution_seconds']

    def call(self, argv, *, timeout=30, cleanup=False):
        if not cleanup and self.interrupts.signum:
            self.interrupts.phase = 'stopping'
            raise Interrupted(self.interrupts.signum)
        if cleanup:
            require(self.interrupts.count < 2, 'probe-cleanup-interrupted')
            limit = min(5, self.cleanup_deadline - self.clock())
        else:
            limit = min(timeout, self.deadline - self.clock())
        require(limit > 0, 'probe-deadline')
        pending = None
        if argv[1] in ('create', 'start', 'update', 'kill', 'rm'):
            pending = self.state_dir / (uuid4().hex + '.pending')
            exclusive_json(pending, self.mutation_record(argv))
        if not cleanup and self.interrupts.signum:
            self.interrupts.phase = 'stopping'
            raise Interrupted(self.interrupts.signum)
        result = self.request(tuple(argv), timeout=limit).strip()
        if pending is not None:
            pending.unlink()
        return result

    def mutation_record(self, argv):
        names = list(self.spec['creates'])
        if argv[1] == 'create':
            name = argv[argv.index('--name') + 1]
            require(name in names, 'probe-mutation-scope')
            return dict(operation=argv[1], index=names.index(name), name=name)
        identifier = argv[-1]
        for index, name in enumerate(names):
            try:
                recorded = read_state(self.state_dir / f'{index}.cid').strip()
            except (OSError, Refused):
                continue  # An invalid sibling CID cannot authorize this mutation.
            if recorded == identifier and re.fullmatch('[0-9a-f]{64}', identifier):
                return dict(operation=argv[1], index=index, name=name, identifier=identifier)
        raise Refused('probe-mutation-scope')

    def pending_details(self):
        details = []
        names = list(self.spec['creates'])
        for path in sorted(self.state_dir.glob('*.pending')):
            try:
                record = json.loads(read_state(path))
                operation, index = record['operation'], record['index']
                require(operation in ('create', 'start', 'update', 'kill', 'rm')
                        and type(index) is int and 0 <= index < len(names)
                        and record['name'] == names[index], 'probe-pending-invalid')
                details.append(dict(code='pending-' + operation, index=index, name=names[index]))
            except Exception:
                # Old/incomplete/untrusted records still block cleanup; never echo them.
                details.append(dict(code='pending-unverified'))
        return details

    def inspect(self, identifier, field, *, cleanup=False):
        return self.call(('docker', 'inspect', '--format', field, identifier), cleanup=cleanup)

    def owned(self, identifier, name, *, cleanup=False):
        require(self.inspect(identifier, '{{ index .Config.Labels "' + OWNER + '" }}', cleanup=cleanup)
                == self.spec['run_id'], 'probe-ownership-changed')
        require(self.inspect(identifier, '{{.Name}}', cleanup=cleanup) == '/' + name,
                'probe-name-changed')

    def execute(self):
        image = self.spec['image']
        require(self.call(('docker', 'image', 'inspect', '--format', '{{.Id}}', image)) == image,
                'probe-image-unavailable')
        require(self.call(('docker', 'image', 'inspect', '--format', '{{json (index .Config "Volumes")}}', image))
                in ('null', '{}'), 'probe-image-volumes')
        require(not self.call(('docker', 'ps', '-aq', '--no-trunc', '--filter',
                               'label=' + OWNER + '=' + self.spec['run_id'])), 'probe-run-in-use')
        for index, (name, command) in enumerate(self.spec['creates'].items()):
            exclusive_json(self.state_dir / f'{index}.intent', {'name': name})
            self.names.append(name)
            cidfile = self.state_dir / f'{index}.cid'
            identifier = self.call((*command[:2], '--cidfile', str(cidfile), *command[2:]))
            require(read_state(cidfile).strip() == identifier, 'probe-cid-mismatch')
            require(re.fullmatch('[0-9a-f]{64}', identifier), 'probe-container-id')
            self.ids.append(identifier)
            self.owned(identifier, name)
            self.call(('docker', 'start', identifier))  # Fixture setup only.
            ready_by = min(self.deadline, self.clock() + 15)
            while self.call(('docker', 'logs', identifier)) != 'fixture-ready':
                require(self.clock() < ready_by, 'probe-readiness-timeout')
                self.sleep(.1)
        for name, identifier in zip(self.names, self.ids, strict=True):
            self.owned(identifier, name)
            require(self.inspect(identifier, '{{.State.Running}}') == 'true', 'probe-not-running')
            self.call(host_command('restart-no', identifier))
            require(self.inspect(identifier, '{{.HostConfig.RestartPolicy.Name}}') == 'no', 'probe-restart-policy')
            self.owned(identifier, name)
            self.call(host_command('term', identifier))
            require(self.call(host_command('wait', identifier)) == '0', 'probe-exit')
            require(self.inspect(identifier, '{{.State.Running}}') == 'false', 'probe-still-running')
            require(self.inspect(identifier, '{{.RestartCount}}') == '0', 'probe-restarted')
        return dict(status='pass', fixtures=len(self.ids), production_ready=False, host_verified=False)

    def cleanup(self):
        details = []
        self.interrupts.phase = 'cleanup'
        self.cleanup_deadline = self.clock() + self.spec['cleanup_seconds']
        try:
            for index, name in reversed(list(enumerate(self.spec['creates']))):
                try:
                    intent = self.state_dir / f'{index}.intent'
                    if not intent.exists():
                        continue
                    require(json.loads(read_state(intent)) == {'name': name}, 'probe-intent-mismatch')
                    found = self.call(('docker', 'ps', '-aq', '--no-trunc', '--filter',
                                       'name=^/' + name + '$'), cleanup=True)
                    if not found:
                        continue
                    cid = self.state_dir / f'{index}.cid'
                    require(cid.exists(), 'probe-cid-missing')
                    identifier = read_state(cid).strip()
                    require(bool(identifier), 'probe-cid-empty')
                    require(re.fullmatch('[0-9a-f]{64}', identifier) and found == identifier,
                            'probe-cleanup-identity')
                    self.owned(identifier, name, cleanup=True)
                    self.call(('docker', 'rm', '-f', identifier), cleanup=True)
                    require(not self.call(('docker', 'ps', '-aq', '--no-trunc', '--filter',
                                            'name=^/' + name + '$'), cleanup=True), 'probe-cleanup-remnant')
                except Exception as exc:
                    allowed = {'probe-cid-missing', 'probe-cid-empty', 'probe-cleanup-identity',
                               'probe-ownership-changed', 'probe-name-changed', 'probe-intent-mismatch',
                               'probe-cleanup-remnant', 'probe-cleanup-interrupted', 'probe-deadline'}
                    code = str(exc) if isinstance(exc, Refused) and str(exc) in allowed else 'probe-resource-failed'
                    details.append(dict(code=code, index=index, name=name))
            # Detect unknown resources; never remove them by label alone.
            require(not self.call(('docker', 'ps', '-aq', '--no-trunc', '--filter',
                                    'label=' + OWNER + '=' + self.spec['run_id']), cleanup=True),
                    'probe-label-remnant')
        except (Exception, Interrupted, KeyboardInterrupt) as exc:
            allowed = {'probe-label-remnant', 'probe-cleanup-interrupted', 'probe-deadline'}
            code = str(exc) if isinstance(exc, Refused) and str(exc) in allowed else 'probe-cleanup-failed'
            details.append(dict(code=code))
        finally:
            self.interrupts.protected = True
        details.extend(self.pending_details())  # Empty ps cannot disprove a late effect.
        return dict(status='clean' if not details else 'incomplete', failures=len(details), details=details)


def artifact_path(path, kind):
    require('..' not in path.parts, 'probe-' + kind + '-parent-traversal')
    path = path.absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'probe-' + kind + '-symlink')
    require(not any((parent / '.git').exists() for parent in (path, *path.parents)),
            'probe-' + kind + '-in-checkout')
    return path


@contextmanager
def private_report(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as report:
        yield report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--run-id', default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true', help='only after explicit human approval')
    mode.add_argument('--cleanup-only', action='store_true', help='remove only matching owned fixtures after approval')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--state-dir', type=Path, help='exclusive persistent synthetic run state')
    parser.add_argument('--daemon-id', help='nominally approved local disposable daemon ID')
    args = parser.parse_args(argv)
    spec = plan(args.image, uuid4().hex if args.run_id is None else args.run_id)
    if not (args.execute or args.cleanup_only):
        print(json.dumps(spec, indent=2))
        return 0  # No subprocess, Docker inspection, report file or resources.
    require(args.run_id is not None, 'probe-run-id-required')
    require(args.report is not None, 'probe-report-required')
    require(args.state_dir is not None, 'probe-state-required')
    require(args.daemon_id is not None and re.fullmatch('[A-Za-z0-9:-]{12,128}', args.daemon_id),
            'probe-daemon-required')
    local_environment(os.environ)
    os.umask(0o022)
    if args.report.exists():
        raise FileExistsError('probe-report-exists')
    state = artifact_path(args.state_dir, 'state')
    report_path = artifact_path(args.report, 'report')
    scope = state_scope(spec, args.daemon_id)
    if args.cleanup_only:
        metadata = state.stat()
        require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.getuid()
                and stat.S_IMODE(metadata.st_mode) == 0o700, 'probe-state-owner')
        require(json.loads(read_state(state / 'scope.json')) == scope, 'probe-state-scope')
    else:
        state.mkdir(mode=0o700)  # Exclusive run directory; never reuse another run.
        exclusive_json(state / 'scope.json', scope)
    interrupts = Interrupts()
    with state_lock(state), private_report(report_path) as report_file, tempfile.TemporaryDirectory(prefix='igreja12-probe-config-') as config:
        request = docker_request(config, interrupts)
        probe = CommandProbe(spec, request, state, interrupts=interrupts)
        report = dict(status='fail', reason='probe-interrupted', production_ready=False, host_verified=False)
        failed = False
        verified = False
        interrupts.phase = 'stopping'
        with interrupts.installed():
            try:
                interrupts.phase = 'execute'
                # No mutation before the nominal daemon identity/platform check.
                require(probe.call(('docker', 'info', '--format', '{{.ID}}')) == args.daemon_id,
                        'probe-daemon-mismatch')
                require(probe.call(('docker', 'info', '--format', '{{.OSType}}')) == 'linux',
                        'probe-platform-refused')
                options = probe.call(('docker', 'info', '--format', '{{json .SecurityOptions}}'))
                parsed = json.loads(options)
                require(isinstance(parsed, list) and all(isinstance(item, str) for item in parsed)
                        and 'rootless' not in options.lower() and 'podman' not in options.lower(),
                        'probe-platform-refused')
                verified = True
                report = (dict(status='pass', production_ready=False, host_verified=False)
                          if args.cleanup_only else probe.execute())
            except (Interrupted, KeyboardInterrupt) as exc:
                interrupts.phase = 'stopping'
                if isinstance(exc, KeyboardInterrupt):
                    interrupts.signum = interrupts.signum or signal.SIGINT
                    interrupts.count += 1
            except Exception as exc:
                failed = True
                known = {'probe-command-failed', 'probe-reap-failed', 'probe-docker-failed', 'probe-daemon-mismatch',
                         'probe-platform-refused', 'probe-image-unavailable', 'probe-image-volumes',
                         'probe-run-in-use', 'probe-cid-mismatch', 'probe-container-id',
                         'probe-ownership-changed', 'probe-name-changed', 'probe-readiness-timeout',
                         'probe-not-running', 'probe-restart-policy', 'probe-exit',
                         'probe-still-running', 'probe-restarted', 'probe-deadline'}
                report['reason'] = str(exc) if isinstance(exc, Refused) and str(exc) in known else 'probe-failed'  # Never serialize arbitrary driver/exception text.
            finally:
                report['cleanup'] = (probe.cleanup() if verified else
                                     dict(status='not-attempted', failures=0))
                interrupts.protected = True  # A further signal cannot truncate the report.
                report['scope'] = spec
                report['daemon_id'] = args.daemon_id
                if interrupts.signum:
                    report['signal'] = interrupts.signum
                    report['status'] = 'fail'
                if report['cleanup']['status'] != 'clean':
                    report['status'] = 'fail'
                json.dump(report, report_file, indent=2)
                report_file.write('\n')
                report_file.flush()
                os.fsync(report_file.fileno())
        return (1 if failed else 128 + interrupts.signum) if interrupts.signum else (0 if report['status'] == 'pass' else 1)


if __name__ == '__main__':
    raise SystemExit(main())
