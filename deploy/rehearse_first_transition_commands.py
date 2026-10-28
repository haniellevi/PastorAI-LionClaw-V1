"""Plan-only by default. Execute only after human approval of the printed scope.

Four new networkless Python signal fixtures, not application workers. Exercises
only the command encoder used by SimulatedHostTransport. Does not connect a
real driver to the simulation-only contract or certify ingress/queues/Compose.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
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
                creates=creates, socket=SOCKET, execution_seconds=180, cleanup_seconds_per_command=5,
                production_ready=False, host_verified=False,
                not_proven=['application-workers', 'Compose', 'ingress', 'Redis', 'provider-delivery',
                            'quiescence', 'database', 'daemon-restart', 'production'])


class CommandProbe:
    def __init__(self, spec, request, *, clock=time.monotonic, sleep=time.sleep):
        self.spec, self.request, self.clock, self.sleep = spec, request, clock, sleep
        self.names, self.ids = [], []
        self.deadline = clock() + spec['execution_seconds']

    def call(self, argv, *, timeout=30, cleanup=False):
        limit = 5 if cleanup else min(timeout, self.deadline - self.clock())
        require(limit > 0, 'probe-deadline')
        return self.request(tuple(argv), timeout=limit).strip()

    def inspect(self, identifier, field, *, cleanup=False):
        return self.call(('docker', 'inspect', '--format', field, identifier), cleanup=cleanup)

    def owned(self, identifier, *, cleanup=False):
        require(self.inspect(identifier, '{{ index .Config.Labels "' + OWNER + '" }}', cleanup=cleanup)
                == self.spec['run_id'], 'probe-ownership-changed')

    def execute(self):
        image = self.spec['image']
        require(self.call(('docker', 'image', 'inspect', '--format', '{{.Id}}', image)) == image,
                'probe-image-unavailable')
        require(self.call(('docker', 'image', 'inspect', '--format', '{{json (index .Config "Volumes")}}', image))
                in ('null', '{}'), 'probe-image-volumes')
        for name, command in self.spec['creates'].items():
            self.names.append(name)  # Also clean a create whose CLI response is lost.
            identifier = self.call(command)
            require(re.fullmatch('[0-9a-f]{64}', identifier), 'probe-container-id')
            self.ids.append(identifier)
            self.owned(identifier)
            self.call(('docker', 'start', identifier))  # Fixture setup only.
            ready_by = min(self.deadline, self.clock() + 15)
            while self.call(('docker', 'logs', identifier)) != 'fixture-ready':
                require(self.clock() < ready_by, 'probe-readiness-timeout')
                self.sleep(.1)
        for identifier in self.ids:
            self.owned(identifier)
            require(self.inspect(identifier, '{{.State.Running}}') == 'true', 'probe-not-running')
            self.call(host_command('restart-no', identifier))
            require(self.inspect(identifier, '{{.HostConfig.RestartPolicy.Name}}') == 'no', 'probe-restart-policy')
            self.owned(identifier)
            self.call(host_command('term', identifier))
            require(self.call(host_command('wait', identifier)) == '0', 'probe-exit')
            require(self.inspect(identifier, '{{.State.Running}}') == 'false', 'probe-still-running')
            require(self.inspect(identifier, '{{.RestartCount}}') == '0', 'probe-restarted')
        return dict(status='pass', fixtures=len(self.ids), production_ready=False, host_verified=False)

    def cleanup(self):
        failures = 0
        for name in reversed(self.names):
            try:
                found = self.call(('docker', 'ps', '-aq', '--no-trunc', '--filter', 'name=^/' + name + '$'),
                                  cleanup=True)
                if not found:
                    continue
                require(re.fullmatch('[0-9a-f]{64}', found), 'probe-cleanup-identity')
                self.owned(found, cleanup=True)
                self.call(('docker', 'rm', '-f', found), cleanup=True)
                require(not self.call(('docker', 'ps', '-aq', '--no-trunc', '--filter', 'name=^/' + name + '$'),
                                      cleanup=True), 'probe-cleanup-remnant')
            except Exception:
                failures += 1
        return dict(status='clean' if not failures else 'incomplete', failures=failures)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--run-id', default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true', help='only after explicit human approval')
    mode.add_argument('--cleanup-only', action='store_true', help='remove only matching owned fixtures after approval')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    spec = plan(args.image, uuid4().hex if args.run_id is None else args.run_id)
    if not (args.execute or args.cleanup_only):
        print(json.dumps(spec, indent=2))
        return 0  # No subprocess, Docker inspection, report file or resources.
    require(args.run_id is not None, 'probe-run-id-required')
    require(args.report is not None, 'probe-report-required')
    os.umask(0o022)
    with args.report.open('x') as report_file, tempfile.TemporaryDirectory(prefix='igreja12-probe-config-') as config:
        def request(command, *, timeout):
            require(command[0] == 'docker', 'probe-command')
            try:
                result = subprocess.run(['docker', '-H', SOCKET, '--config', config, *command[1:]],
                                        env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True,
                                        timeout=timeout)
                require(result.returncode == 0, 'probe-docker-failed')
                return result.stdout
            except (OSError, subprocess.TimeoutExpired):
                raise Refused('probe-command-failed') from None
        probe = CommandProbe(spec, request)
        report = dict(status='fail', reason='interrupted', production_ready=False, host_verified=False)
        try:
            if args.cleanup_only:
                probe.names = list(spec['creates'])
                report = dict(status='pass', production_ready=False, host_verified=False)
            else:
                report = probe.execute()
        except Exception as exc:
            report['reason'] = str(exc) if isinstance(exc, Refused) else 'probe-failed'
        finally:
            report['cleanup'] = probe.cleanup()
            report['scope'] = spec
            if report['cleanup']['status'] != 'clean':
                report['status'] = 'fail'
            json.dump(report, report_file, indent=2)
            report_file.write('\n')
        return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
