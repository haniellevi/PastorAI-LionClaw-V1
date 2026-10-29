"""Run only first-transition DB tests on an owned disposable PostgreSQL 17.6.

Requires an existing Python 3.13 test environment and local postgres:17.6 image.
No installation, registry push, application container or real Redis is used.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4


DOCKER = ('docker', '-H', 'unix:///var/run/docker.sock')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', default=sys.executable,
                        help='existing Python 3.13 with pytest and psycopg2')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    name = 'igreja12-first-transition-' + uuid4().hex[:10]
    nonce = str(uuid4())
    created = False
    with tempfile.TemporaryDirectory(prefix='igreja12-first-transition-docker-') as config:
        docker_env = dict(PATH='/usr/bin:/bin', DOCKER_CONFIG=config)

        def docker(*command, **kwargs):
            return subprocess.run([*DOCKER, *command], check=True, env=docker_env, **kwargs)

        try:
            docker('run', '--pull=never', '-d', '--name', name,
                   '--label', 'igreja12.task=first-transition-local',
                   '--tmpfs', '/var/lib/postgresql/data', '-p', '127.0.0.1::5432',
                   '-e', 'POSTGRES_DB=first_transition_test',
                   '-e', 'POSTGRES_PASSWORD=synthetic-only', 'postgres:17.6',
                   stdout=subprocess.DEVNULL)
            created = True
            for _ in range(50):
                ready = subprocess.run([*DOCKER, 'exec', name, 'pg_isready', '-q',
                                        '-h', '127.0.0.1', '-U', 'postgres'], env=docker_env)
                if ready.returncode == 0:
                    break
                time.sleep(.2)
            else:
                raise RuntimeError('disposable PostgreSQL readiness failed')
            docker('exec', '-i', name, 'psql', '-q', '-U', 'postgres',
                   '-d', 'first_transition_test', '-v', 'ON_ERROR_STOP=1', text=True,
                   input=f"COMMENT ON DATABASE first_transition_test IS 'igreja12-local-disposable:{nonce}'")
            address = docker('port', name, '5432/tcp', capture_output=True, text=True).stdout.strip()
            port = address.split(':')[-1]
            env = dict(PATH='/usr/bin:/bin', PYTHON_DOTENV_DISABLED='1',
                       PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONDONTWRITEBYTECODE='1',
                       FIRST_TRANSITION_LOCAL_URL=f'postgresql://postgres:synthetic-only@127.0.0.1:{port}/first_transition_test',
                       FIRST_TRANSITION_LOCAL_NONCE=nonce)
            with tempfile.TemporaryDirectory(prefix='igreja12-first-transition-client-') as client:
                result = subprocess.run([
                    args.python, '-m', 'pytest', '-p', 'no:cacheprovider', '-o', 'addopts=', '-q', '--tb=short',
                    str(root / 'deploy/tests/test_first_transition_adapter.py'),
                    str(root / 'deploy/tests/test_first_transition_adapter_pg.py'),
                    str(root / 'deploy/tests/test_first_transition_host_contract.py'),
                ], cwd=client, env=env, timeout=600)
                return result.returncode
        finally:
            if created:
                # Only the UUID-named resource created by this invocation.
                docker('rm', '-f', name, stdout=subprocess.DEVNULL)
                print('Owned disposable PostgreSQL removed.', flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
