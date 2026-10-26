"""Real ``docker compose config`` (parser only, no engine) of the installation's own
``docker-compose.yml`` under the adopted topology, in the script's file order.

The base file is copied into a private temp directory with a synthetic
``configuration.fixture``, so Compose never loads any ``.env`` of the repository.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))

import release_topology as rt  # noqa: E402

SERVICES = rt.SERVICES
PROJECT, NETWORK = 'pastorai-permanent', 'pastorai_default'
ID = 'sha256:' + '2' * 64
DIGEST = 'ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:' + '3' * 64
SHA = 'b' * 40
GATES = {'ALLOW_REAL_SENDS': 'false', 'ASAAS_BILLING_ENABLED': 'false', 'BREVO_SEND_MODE': 'off',
         'BROADCAST_ASYNC_ENABLED': 'false'}
COMMANDS = {'backend': ['uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000'],
            'queue-worker': ['python', '-m', 'app.workers.queue_worker'],
            'cron-worker': ['python', '-m', 'app.workers.cron_worker'],
            'broadcast-worker': ['python', '-m', 'app.workers.broadcast_worker']}

pytestmark = pytest.mark.skipif(not shutil.which('docker'), reason='Docker Compose parser unavailable')


def contract():
    return dict(schema=rt.SCHEMA, version=1, project=PROJECT, legacy_project='pastorai',
                network=dict(name=NETWORK, id='e' * 64), containers={s: f'{PROJECT}-{s}' for s in SERVICES},
                reserved_legacy={s: str(i) * 64 for i, s in enumerate(SERVICES, 1)})


@pytest.fixture()
def work(tmp_path):
    (tmp_path / 'docker-compose.yml').write_bytes((DEPLOY / 'docker-compose.yml').read_bytes())
    (tmp_path / 'configuration.fixture').write_text(
        ''.join(f'{k}={v}\n' for k, v in GATES.items()) + 'SYNTHETIC_ONLY=1\n')
    (tmp_path / 'topology.yml').write_text(rt.overlay(contract()))
    return tmp_path


def config(work, *files, project=True, resolve=True):
    args = ['docker', 'compose', *(['-p', PROJECT] if project else []),
            *(x for f in files for x in ('-f', str(f))), 'config', '--format', 'json',
            *([] if resolve else ['--no-env-resolution'])]
    done = subprocess.run(args, cwd=work, capture_output=True, text=True,
                          env={'PATH': os.environ['PATH'], 'DOCKER_CONFIG': str(work / 'docker-config'),
                               'PASTORAI_ENV_FILE': 'configuration.fixture'})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def write_json(path, value):
    path.write_text(json.dumps(value))
    return path


def assert_topology(model, image=None):
    rt.check_config(contract(), model)
    assert model['name'] == PROJECT
    assert model['networks'] == {'default': {'name': NETWORK, 'external': True}} or (
        model['networks']['default']['external'] is True and model['networks']['default']['name'] == NETWORK)
    assert set(model['services']) == set(SERVICES)  # Redis/Evolution are never part of the project
    ports = model['services']['backend']['ports']
    assert [(p['host_ip'], str(p['published']), p['target']) for p in ports] == [('127.0.0.1', '8000', 8000)]
    for service in SERVICES:
        definition = model['services'][service]
        assert definition['container_name'] == f'{PROJECT}-{service}'
        assert set(definition['networks']) == {'default'}
        assert not definition.get('depends_on')
        assert definition.get('ports', []) == ([] if service != 'backend' else ports)
        assert definition['image'] == (image or 'pastorai-backend:latest')


@pytest.mark.parametrize('pin', [None, ID, DIGEST])
def test_runtime_order_base_topology_pin(work, pin):
    files = [work / 'docker-compose.yml', work / 'topology.yml']
    if pin:
        files.append(write_json(work / 'pin.json', {'services': {
            s: {'image': pin, 'environment': {'PASTORAI_RELEASE_SHA': SHA}} for s in SERVICES}}))
    model = config(work, *files)
    assert_topology(model, pin)
    for service in SERVICES:
        definition = model['services'][service]
        assert definition['command'] == COMMANDS[service]
        assert {k: definition['environment'].get(k) for k in GATES} == GATES
        assert definition['environment']['REDIS_URL'] == 'redis://redis:6379/0'
        assert definition['environment']['EVOLUTION_API_URL'] == 'http://evolution-api:8080'
        if pin:
            assert definition['environment']['PASTORAI_RELEASE_SHA'] == SHA
    assert model['services']['backend']['environment']['EVOLUTION_WEBHOOK_CALLBACK_URL'] == \
        'http://backend:8000/whatsapp/webhook'
    assert rt.image_name(config(work, *files[:2], resolve=False)) == 'pastorai-backend:latest'


def test_checker_between_topology_and_pin(work):
    checker = write_json(work / 'checker.json', {'services': {'backend': {
        'entrypoint': ['python', '/tmp/backend-rollback-schema.py'], 'command': [], 'restart': 'no',
        'healthcheck': {'disable': True}, 'environment': {'EXPECTED_MIGRATIONS': '["0001_synthetic.sql"]'}}}})
    pin = write_json(work / 'pin.json', {'services': {
        s: {'image': ID, 'environment': {'PASTORAI_RELEASE_SHA': SHA}} for s in SERVICES}})
    model = config(work, work / 'docker-compose.yml', work / 'topology.yml', checker, pin)
    assert_topology(model, ID)
    backend = model['services']['backend']
    assert backend['entrypoint'] == ['python', '/tmp/backend-rollback-schema.py']
    assert backend['command'] in ([], None)
    assert backend['restart'] == 'no' and backend['healthcheck']['disable'] is True
    assert backend['environment']['EXPECTED_MIGRATIONS'] == '["0001_synthetic.sql"]'
    assert model['services']['queue-worker']['command'] == COMMANDS['queue-worker']


@pytest.mark.parametrize('pin', [ID, DIGEST])
def test_persisted_override_drives_manual_maintenance_without_flags(work, pin):
    (work / 'docker-compose.override.yml').write_text(rt.overlay(contract(), pin, SHA))
    model = config(work, project=False)  # plain ``docker compose config`` as an operator would run it
    assert_topology(model, pin)
    assert {model['services'][s]['environment']['PASTORAI_RELEASE_SHA'] for s in SERVICES} == {SHA}


def test_naming_a_dependency_explicitly_is_still_its_legacy_container(work):
    # Profiles keep Redis/Evolution out of the project; asking for one by name shows it keeps the
    # legacy container_name, so a manual ``up redis`` collides instead of creating a second Redis.
    args = ['docker', 'compose', '-p', PROJECT, '-f', 'docker-compose.yml', '-f', 'topology.yml',
            '--profile', rt.DEPENDENCY_PROFILE, 'config', '--format', 'json', '--no-env-resolution']
    done = subprocess.run(args, cwd=work, capture_output=True, text=True,
                          env={'PATH': os.environ['PATH'], 'DOCKER_CONFIG': str(work / 'docker-config'),
                               'PASTORAI_ENV_FILE': 'configuration.fixture'})
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)['services']['redis']['container_name'] == 'pastorai_redis'
