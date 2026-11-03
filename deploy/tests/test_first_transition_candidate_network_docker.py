"""Opt-in real Docker/Compose rehearsal with an owned internal network and synthetic processes.

No application, database server, real data, provider, published port or image pull.
Only the synthetic backend is started; all three consumers stay never-started.
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from first_transition_candidate import (CLOSED_GATES, CONSUMERS, CandidatePort, CandidateRunner, CandidateSpec,
                                        check_backend_running, check_held, check_identity, write_hold_override)
from first_transition_adapter import ROLES
from initial_transition_ops import Refused

IMAGE = 'postgres@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929'
LABEL = 'igreja12.synthetic.candidate-network'


def test_real_compose_created_network_and_backend_start(tmp_path, record_property):
    if os.environ.get('FIRST_TRANSITION_CANDIDATE_DOCKER') != '1':
        pytest.skip('requires explicit local synthetic Docker opt-in')
    config_dir = tmp_path / 'docker-config'
    config_dir.mkdir()
    endpoint = 'unix:///var/run/docker.sock'
    docker = ['/usr/bin/docker', '--host', endpoint, '--config', str(config_dir)]
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}

    def run(*args):
        proc = subprocess.run([*docker, *args], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=40, env=env)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.strip()

    token = 'candidate-net-' + uuid4().hex
    project = 'igreja12-' + token
    network_name = project + '-net'
    network_id = None

    def owned_ids():
        return run('ps', '--all', '--quiet', '--no-trunc', '--filter', 'label=' + LABEL + '=' + token).split()

    try:
        record_property('engine_version', json.loads(run('version', '--format', '{{json .Server.Version}}')))
        record_property('compose_version', run('compose', 'version', '--short'))
        image_id = json.loads(run('image', 'inspect', '--format', '{{json .Id}}', IMAGE))
        daemon = json.loads(run('info', '--format', '{{json .ID}}'))
        network_id = run('network', 'create', '--internal', '--label', LABEL + '=' + token, network_name)
        sha = '0' * 40  # Fictional revision label: not an application provenance claim.
        release_root = tmp_path / 'releases'
        deploy = release_root / sha / 'deploy'
        deploy.mkdir(parents=True)
        names = {role: project + '-' + role for role in ROLES}
        services = {}
        for role in ROLES:
            services[role] = {
                'image': IMAGE, 'container_name': names[role], 'restart': 'no', 'read_only': True,
                'entrypoint': ['/bin/sh', '-c', "trap 'exit 0' TERM INT; while :; do sleep 0.2; done"],
                'cap_drop': ['ALL'], 'tmpfs': ['/var/lib/postgresql/data:rw,noexec,nosuid,size=1048576'],
                'labels': {LABEL: token, 'org.opencontainers.image.revision': sha},
                'environment': dict(CLOSED_GATES), 'networks': ['isolated']}
        (deploy / 'docker-compose.yml').write_text(json.dumps({'services': services,
            'networks': {'isolated': {'external': True, 'name': network_name}}}))
        (deploy / 'docker-compose.override.yml').write_text('{"services":{}}')
        private = tmp_path / 'synthetic.env'
        private.write_text('')
        spec = CandidateSpec(sha=sha, image=image_id, project=project, containers=tuple(names.items()),
            network_id=network_id, network_name=network_name, release_root=str(release_root),
            hold_override=str(tmp_path / 'hold.json'), env_file=str(private), daemon_id=daemon, smoke_seconds=5)

        def port_for(scope):
            return CandidatePort(scope, runner=CandidateRunner(scope, docker_binary='/usr/bin/docker',
                endpoint=endpoint, config_dir=str(config_dir)))

        port = port_for(spec)
        write_hold_override(spec)
        port.create_held()  # Production port/runner argv, synthetic Compose payload.
        ids = port.project_ids()
        assert len(ids) == 4 and sorted(owned_ids()) == list(ids)
        states = port.inspect(ids)
        by_role = {state['service']: ident for ident, state in states.items()}
        assert set(by_role) == set(ROLES)
        for role, ident in by_role.items():
            check_held(states[ident])
            check_identity(spec, role, states[ident])
        record_property('created_raw_network_ids', json.dumps([states[i]['networks'] for i in ids]))
        assert all(state['network_binding'] == [network_id, network_name] for state in states.values())

        # Same real daemon/containers, but an unbound network name: refusal before start.
        wrong = port_for(replace(spec, network_name=network_name + '-missing'))
        with pytest.raises(Refused, match='candidate-network-binding'):
            wrong.start_backend(by_role['backend'])
        with pytest.raises(Refused, match='candidate-identity-mismatch'):
            port.start_backend(by_role[CONSUMERS[0]])
        assert all(state['status'] == 'created' for state in port.inspect(ids).values())

        port.start_backend(by_role['backend'])
        for fresh in (port, port_for(spec)):
            after = fresh.inspect(ids)
            for role, ident in by_role.items():
                check_identity(spec, role, after[ident])
                if role == 'backend':
                    check_backend_running(after[ident])
                    assert after[ident]['networks'] == [network_id]
                else:
                    check_held(after[ident])
        record_property('backend_starts', 1)
        record_property('consumer_starts', 0)
        record_property('application_or_database_server_started', False)
    finally:
        removed = 0
        for ident in owned_ids():
            def state():
                return json.loads(run('inspect', '--format',
                    '[{{json .State.Running}},{{json .State.Status}},'
                    '{{json (index .Config.Labels "' + LABEL + '")}}]', ident))
            current = state()
            assert current[2] == token
            if current[0]:
                run('kill', '--signal=SIGTERM', ident)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and state()[0]:
                    time.sleep(0.1)
            current = state()
            assert current[0] is False and current[1] in ('created', 'exited') and current[2] == token
            run('rm', '--volumes', ident)
            removed += 1
        if network_id:
            data = json.loads(run('network', 'inspect', '--format',
                '[{{json .Internal}},{{json (index .Labels "' + LABEL + '")}},{{len .Containers}}]', network_id))
            assert data == [True, token, 0]
            run('network', 'rm', network_id)
        assert owned_ids() == []
        record_property('owned_containers_removed', removed)
        record_property('owned_network_removed', network_id is not None)
