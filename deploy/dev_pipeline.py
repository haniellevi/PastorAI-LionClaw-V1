#!/usr/bin/env python3
"""Physical synthetic DEV executor, sharing deploy/reset/acceptance mutex.

No provisioning or production profile. Online activation requires a nominal
host configuration and a schema receipt reconstructed outside that target.
No secret value or command output is written to the deployment journal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from dev_coordination import DevCoordinator, package_id

HERE = Path(__file__).resolve().parent
CONSUMERS = ['queue-worker', 'cron-worker', 'broadcast-worker']


class PipelineRefused(ValueError):
    pass


def run(argv, *, env=None):
    completed = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=240)
    if completed.returncode:
        for line in completed.stderr.splitlines():
            if re.fullmatch(r'synthetic database operation refused: [A-Za-z]+ at [A-Za-z_]+:[0-9]+', line):
                raise PipelineRefused(line)
        raise PipelineRefused('executor step failed')
    return completed.stdout


def schema_id(receipt):
    if type(receipt) is not dict or set(receipt) != {'catalog', 'migrations'}:
        raise PipelineRefused('invalid independent schema receipt')
    return hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class Executor:
    def __init__(self, config, package, *, runner=run):
        package_id(package)
        required = {'project', 'profile', 'approved_project', 'runtime_env_file', 'state_dir',
                    'backend_repository', 'frontend_repository', 'api_port', 'frontend_port'}
        if type(config) is not dict or set(config) != required:
            raise PipelineRefused('invalid nominal executor configuration')
        if not re.fullmatch(r'pastorai-synthetic-[a-z0-9-]{1,40}', config['project']):
            raise PipelineRefused('synthetic Compose project required')
        if config['profile'] not in {'online', 'rehearsal'}:
            raise PipelineRefused('production profile refused')
        if any(type(config[key]) is not int or not 1024 <= config[key] <= 65535 for key in ('api_port', 'frontend_port')) or config['api_port'] == config['frontend_port']:
            raise PipelineRefused('invalid loopback ports')
        if config['profile'] == 'online':
            if config['state_dir'] != '/var/lib/pastorai-dev' or config['runtime_env_file'] != '/etc/pastorai-dev/runtime.conf':
                raise PipelineRefused('nominal DEV controller paths required')
            if not re.fullmatch('[a-z]{20}', config['approved_project']) or config['approved_project'] == 'pffafnchtxbimpwyaczq':
                raise PipelineRefused('approved DEV resource required')
            for key in ('backend_repository', 'frontend_repository'):
                if not re.fullmatch(r'ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+', config[key]):
                    raise PipelineRefused('immutable registry repository required')
        elif config['approved_project'] != 'disposable':
            raise PipelineRefused('disposable rehearsal required')
        self.config, self.package, self.runner = config, package, runner
        self.state = Path(config['state_dir']).resolve()
        self.receipts = self.state / 'schemas'
        self.receipts.mkdir(parents=True, exist_ok=True)
        # The controller does not read private runtime configuration.
        if not Path(config['runtime_env_file']).is_absolute():
            raise PipelineRefused('absolute runtime configuration path required')
        self.env = dict(os.environ, RELEASE_PROFILE=config['profile'],
            DEV_APPROVED_PROJECT=config['approved_project'], DEV_RUNTIME_ENV_FILE=config['runtime_env_file'],
            DEV_CONTROL_DIR=str(HERE), DEV_RECEIPTS_DIR=str(self.receipts),
            FRONTEND_ORIGIN=package['frontend_origin'], API_ORIGIN=package['api_origin'],
            API_PORT=str(config['api_port']), FRONTEND_PORT=str(config['frontend_port']))
        for key in ('DEV_RESET_APPROVED_PROJECT','DEV_RESET_EMPTY_SCHEMA','REHEARSAL_FRESH_DATABASE'):
            self.env.pop(key,None)
        for key, digest in (('BACKEND_IMAGE', 'backend_digest'), ('FRONTEND_IMAGE', 'frontend_digest')):
            repository = config['backend_repository' if key == 'BACKEND_IMAGE' else 'frontend_repository']
            self.env[key] = repository + '@' + package[digest] if config['profile'] == 'online' else package[digest]
        self.compose = ['docker', 'compose', '--project-name', config['project'], '-f', str(HERE/'docker-compose.synthetic.yml')]
        if config['profile'] == 'rehearsal':
            self.compose += ['-f', str(HERE/'docker-compose.rehearsal.yml')]

    def call(self, *args):
        return self.runner(self.compose + list(args), env=self.env)

    def journal(self, step):
        # Only static stages and reviewed package identity, never stdout/PII.
        with (self.state/'stages.jsonl').open('a') as output:
            output.write(json.dumps({'package': package_id(self.package), 'step': step})+'\n')
            output.flush()
            os.fsync(output.fileno())

    def preflight(self, expected):
        if schema_id(expected) != self.package['schema']:
            raise PipelineRefused('independent schema receipt mismatch')
        endpoint = json.loads(self.runner(['docker', 'context', 'inspect']))[0]['Endpoints']['docker']['Host']
        if endpoint != 'unix:///var/run/docker.sock' or os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
            raise PipelineRefused('local authorized executor required')
        for key in ('BACKEND_IMAGE', 'FRONTEND_IMAGE'):
            if self.config['profile'] == 'online':
                self.runner(['docker', 'pull', self.env[key]])
            image = json.loads(self.runner(['docker', 'image', 'inspect', self.env[key]]))[0]
            labels = image['Config'].get('Labels') or {}
            if labels.get('org.opencontainers.image.revision') != self.package['sha']:
                raise PipelineRefused('image revision mismatch')
            if key == 'FRONTEND_IMAGE' and (labels.get('pastorai.api-origin') != self.package['api_origin'] or labels.get('pastorai.frontend-origin') != self.package['frontend_origin']):
                raise PipelineRefused('frontend build target mismatch')
        # Existing project ownership is checked without exposing its env values.
        ids = self.runner(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project='+self.config['project']]).split()
        for identifier in ids:
            data = json.loads(self.runner(['docker', 'inspect', identifier]))[0]
            if (data['Config'].get('Labels') or {}).get('pastorai.scope') != 'dev-sintetico':
                raise PipelineRefused('existing resource ownership mismatch')
        if self.config['profile'] == 'rehearsal':
            self.call('up', '-d', '--wait', 'postgres', 'redis')
        else:
            self.call('up', '-d', '--wait', 'redis')
        self.call('run', '--rm', '-T', 'control', 'verify-target')

    def contain(self):
        self.journal('contain')
        # Physical stop, keeping Redis volumes and in-flight records. Gates are
        # not used as a pause. Every subsequent failure keeps consumers stopped.
        self.call('stop', '-t', '120', 'backend', *CONSUMERS)
        for service in ['backend', *CONSUMERS]:
            if self.call('ps', '--status', 'running', '-q', service).strip():
                raise PipelineRefused('consumer containment failed')

    def database(self, action, *args):
        self.journal(action)
        return self.call('run', '--rm', '-T', 'control', action, *args)

    def health(self, *, require_workers=True):
        for attempt in range(45):
            try:
                if self.config['profile']=='rehearsal':
                    # An internal Docker network has no published ingress on
                    # every engine. Probe real HTTP from the runtime processes.
                    payload=json.loads(self.call('exec','-T','backend','python','-c',
                        "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/ready',timeout=3).read().decode())"))
                    frontend_ok=self.call('exec','-T','frontend','node','-e',
                        "fetch('http://127.0.0.1:3000/privacidade').then(r=>{if(r.status!==200||!r.headers.get('content-security-policy')?.includes(\"frame-ancestors 'none'\"))process.exit(1);console.log('ok')}).catch(()=>process.exit(1))").strip()=='ok'
                else:
                    with urlopen(self.package['api_origin']+'/ready',timeout=3) as response:
                        payload=json.load(response)
                    with urlopen(self.package['frontend_origin']+'/privacidade',timeout=3) as response:
                        frontend_ok=response.status==200 and "frame-ancestors 'none'" in response.headers.get('Content-Security-Policy','')
                if (payload['required'].get('database') == 'ok' and payload['required'].get('redis') == 'ok'
                    and (not require_workers or (payload['workers'] and all(value == 'ok' for value in payload['workers'].values()))) and frontend_ok):
                    return True
            except (OSError, KeyError, ValueError):
                pass
            time.sleep(1)
        raise PipelineRefused('candidate readiness or frontend smoke failed')

    def promote(self, expected):
        self.preflight(expected)
        target = self.receipts/(self.package['schema']+'.json')
        target.write_text(json.dumps(expected, sort_keys=True))
        previous_path = self.state/'current-schema.json'
        previous = json.loads(previous_path.read_text()) if previous_path.exists() else expected
        (self.receipts/'previous.json').write_text(json.dumps(previous, sort_keys=True))
        self.contain()
        try:
            self.database('migrate')
            self.database('verify', '/receipts/previous.json', '/receipts/'+target.name)
            self.database('seed')
            self.journal('start-candidate')
            self.call('up', '-d', '--no-deps', '--force-recreate', 'simulador-whatsapp', 'backend', 'frontend')
            self.health(require_workers=False)
            self.journal('resume-consumers')
            self.call('up','-d','--no-deps','--force-recreate',*CONSUMERS)
            self.health()
            # Includes tenant/RLS/login/turn checks supplied by the immutable
            # test suite separately; infrastructure success is never their proof.
            self.journal('infrastructure-ready')
            temporary = previous_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(expected, sort_keys=True))
            os.replace(temporary, previous_path)
        except BaseException:
            self.contain()
            raise

    def recover(self, expected):
        """Restart previous code only on its proven additive schema envelope.

        expected is the independently reconstructed candidate catalogue, even
        when recovering old code. Never run old migrations against this ledger.
        """
        old = json.loads((self.state/'current-schema.json').read_text())
        if not (self.receipts/(schema_id(expected)+'.json')).exists():
            raise PipelineRefused('candidate schema evidence absent')
        # Validate old image/frontend identity against its package. Catalogue
        # identity belongs to the additive candidate, not the old image.
        schema_for_package = json.loads((self.receipts/(self.package['schema']+'.json')).read_text())
        self.preflight(schema_for_package)
        (self.receipts/'recovery-old.json').write_text(json.dumps(old,sort_keys=True))
        self.contain()
        try:
            self.database('verify','/receipts/recovery-old.json','/receipts/'+schema_id(expected)+'.json')
            self.call('up','-d','--no-deps','--force-recreate','simulador-whatsapp','backend','frontend')
            self.health(require_workers=False)
            self.call('up','-d','--no-deps','--force-recreate',*CONSUMERS)
            self.health()
            self.journal('recovery-verified')
            return True
        except BaseException:
            self.contain()
            raise


    def reset(self, expected, confirmation):
        if confirmation != package_id(self.package):
            raise PipelineRefused('exact synthetic reset package confirmation required')
        self.preflight(expected)
        self.contain()
        current=self.receipts/(self.package['schema']+'.json')
        if not current.exists():
            raise PipelineRefused('current schema evidence required before reset')
        self.database('verify','/receipts/'+current.name,'/receipts/'+current.name)
        self.env['DEV_RESET_APPROVED_PROJECT']=self.config['approved_project']
        self.env['DEV_RESET_EMPTY_SCHEMA']='true'
        try:
            self.database('reset')
            self.call('exec','-T','redis','redis-cli','FLUSHDB')
            self.promote(expected)
        except BaseException:
            self.contain()
            raise
        finally:
            self.env.pop('DEV_RESET_APPROVED_PROJECT',None)
            self.env.pop('DEV_RESET_EMPTY_SCHEMA',None)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--config', type=Path, required=True)
    sub = parser.add_subparsers(dest='action', required=True)
    deploy = sub.add_parser('deploy')
    deploy.add_argument('--package', type=Path, required=True)
    deploy.add_argument('--schema', type=Path, required=True)
    recover = sub.add_parser('recover')
    recover.add_argument('--package', type=Path, required=True)
    recover.add_argument('--schema', type=Path, required=True)
    reset=sub.add_parser('reset')
    reset.add_argument('--package',type=Path,required=True)
    reset.add_argument('--schema',type=Path,required=True)
    reset.add_argument('--confirm-synthetic-reset',required=True)
    reserve = sub.add_parser('reserve')
    reserve.add_argument('--owner', required=True)
    reserve.add_argument('--ttl', type=int, default=1800)
    finish = sub.add_parser('finish')
    finish.add_argument('--owner', required=True)
    finish.add_argument('--token', required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.action in {'deploy','recover','reset'}:
        package, schema = json.loads(args.package.read_text()), json.loads(args.schema.read_text())
        executor = Executor(config, package)
        coordinator=DevCoordinator(executor.state)
        if args.action=='deploy':
            coordinator.transition(package, operation='deploy', execute=lambda _p: executor.promote(schema))
        elif args.action=='reset':
            if args.confirm_synthetic_reset != package_id(package):
                raise PipelineRefused('exact synthetic reset package confirmation required')
            coordinator.transition(package,operation='reset',execute=lambda _p: executor.reset(schema,args.confirm_synthetic_reset))
        else:
            recorded=json.loads((executor.state/'state.json').read_text())
            if recorded['package'] != package:
                raise PipelineRefused('only previous package can recover')
            coordinator.record_recovery(package,verify=lambda _p: executor.recover(schema))
    else:
        coordinator = DevCoordinator(Path(config['state_dir']))
        if args.action == 'reserve':
            print(coordinator.reserve(owner=args.owner, ttl=args.ttl))
        else:
            print(coordinator.finish(token=args.token, owner=args.owner))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('synthetic pipeline refused; inspect sanitized stage journal', file=sys.stderr)
        sys.exit(1)
