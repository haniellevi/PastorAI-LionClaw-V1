"""Actual Compose merging of public immutable image metadata, no engine access."""
import json
import os
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('checker', [False, True])
def test_image_pin_preserves_commands_gates_and_checker_override(tmp_path, checker):
    if not shutil.which('docker'):
        pytest.skip('Docker Compose parser unavailable')
    services = ('backend', 'queue-worker', 'cron-worker', 'broadcast-worker')
    image = 'ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:' + '1' * 64
    baseline = {'services': {s: {'image': 'synthetic:mutable', 'command': ['echo', s],
        'environment': {'ALLOW_REAL_SENDS': 'false', 'ASAAS_BILLING_ENABLED': 'false',
                        'BREVO_SEND_MODE': 'off', 'BROADCAST_ASYNC_ENABLED': 'false'}} for s in services}}
    pin = {'services': {s: {'image': image, 'environment': {'PASTORAI_RELEASE_SHA': 'a' * 40}} for s in services}}
    paths = []
    values = [baseline]
    if checker:
        values.append({'services': {'backend': {'entrypoint': ['python', '/tmp/check.py'],
            'command': [], 'restart': 'no', 'healthcheck': {'disable': True}}}})
    values.append(pin)
    for index, value in enumerate(values):
        path = tmp_path / f'public-{index}.json'
        path.write_text(json.dumps(value))
        paths += ['-f', str(path)]
    result = subprocess.run(['docker', 'compose', *paths, 'config', '--format', 'json'],
        env={'PATH': os.environ['PATH'], 'DOCKER_CONFIG': str(tmp_path / 'empty-docker-config')},
        capture_output=True, text=True, check=True)
    model = json.loads(result.stdout)['services']
    for service in services:
        assert model[service]['image'] == image
        assert model[service]['environment']['PASTORAI_RELEASE_SHA'] == 'a' * 40
        assert model[service]['environment']['ALLOW_REAL_SENDS'] == 'false'
        assert model[service]['command'] == ([] if checker and service == 'backend' else ['echo', service])
    if checker:
        assert model['backend']['entrypoint'] == ['python', '/tmp/check.py']
        assert model['backend']['healthcheck']['disable'] is True
