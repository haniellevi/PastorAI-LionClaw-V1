#!/usr/bin/env python3
"""Public, versioned release topology adopted by ``backend-release.sh``.

``deploy/release-topology.json`` is written by the initial transition
(``write_layout``) and then copied forward by each healthy release; it never
comes from the Git tarball. It holds only public identifiers: permanent
Compose project, existing external network (name + ID), container name of the
four services and the IDs of the four contained legacy containers. No secret,
environment or arbitrary Compose configuration is accepted.

``validate``/``overlay``/``persist`` are pure (no Docker). ``check-config``
reads an effective ``compose config --format json`` on stdin. ``guard`` reads
Docker state with templates that never print ``Config.Env``: network
identity, labels, restart policy, running state, health status, network
attachments/aliases and image revision label.

``owned`` prints the IDs safe to stop (contracted name for its own service,
never a reserved legacy ID) and exits 3 when a stranger member exists, which
is left untouched. ``image-name`` prints the build tag shared by the four
services in an effective model read on stdin.

Exit status 0 = accepted; 1 = refused with a fixed code on stderr (values are
never echoed); 2 = usage; 3 = stranger project member (``owned`` only).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys

SCHEMA = 'pastorai.release-topology'
VERSION = 1
SERVICES = ('backend', 'queue-worker', 'cron-worker', 'broadcast-worker')
# Base services that live only in the legacy project: kept out of the
# permanent project (inactive profile) and required to run on the network.
BASE_ONLY = ('redis', 'evolution-postgres', 'evolution-api')
DEPENDENCY_ALIASES = ('redis', 'evolution-api')
DEPENDENCY_PROFILE = 'pastorai-legacy-dependencies'
# The base file's own ``name:``; adopting it would target the legacy install.
BASE_PROJECT = 'pastorai'
PROJECT = re.compile(r'[a-z0-9][a-z0-9_-]{0,62}')
NETWORK = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')
CONTAINER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')
RESOURCE_ID = re.compile(r'[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{40}')
IMAGE_REF = re.compile(r'ghcr\.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:[0-9a-f]{64}')
IMAGE_ID = re.compile(r'sha256:[0-9a-f]{64}')
LOCAL_TAG = re.compile(r'[a-z0-9][a-z0-9._/-]{0,127}(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?')
MAX_BYTES = 16 * 1024
PHASES = ('predecessor', 'replace', 'created', 'checker')
PROJECT_LABEL = 'com.docker.compose.project'
SERVICE_LABEL = 'com.docker.compose.service'
ONEOFF_LABEL = 'com.docker.compose.oneoff'
REVISION_LABEL = 'org.opencontainers.image.revision'
# One JSON array per container; Config.Env is never part of the template.
INSPECT = ('[{{json .Id}},{{json .Name}},{{json .State.Running}},{{json .HostConfig.RestartPolicy.Name}},'
           '{{json (index .Config.Labels "' + PROJECT_LABEL + '")}},'
           '{{json (index .Config.Labels "' + SERVICE_LABEL + '")}},'
           '{{json (index .Config.Labels "' + ONEOFF_LABEL + '")}},'
           # ``index`` tolerates the absent Health key; only its status is printed, never the log.
           '{{with index .State "Health"}}{{json .Status}}{{else}}null{{end}},'
           '{{json .Image}},{{json .NetworkSettings.Networks}}]')


class Refused(Exception):
    """Fixed refusal code; never carries command output or values."""


def require(condition, code):
    if not condition:
        raise Refused(code)


def _no_duplicates(pairs):
    keys = [key for key, _ in pairs]
    require(len(keys) == len(set(keys)), 'contract-duplicate-key')
    return dict(pairs)


def validate(data):
    require(isinstance(data, dict) and set(data) == {
        'schema', 'version', 'project', 'legacy_project', 'network', 'containers', 'reserved_legacy'},
        'contract-keys')
    require(data['schema'] == SCHEMA and type(data['version']) is int and data['version'] == VERSION,
            'contract-schema')
    for key in ('project', 'legacy_project'):
        require(isinstance(data[key], str) and PROJECT.fullmatch(data[key]), 'contract-project')
    require(data['project'] not in (data['legacy_project'], BASE_PROJECT), 'contract-project-is-legacy')
    network = data['network']
    require(isinstance(network, dict) and set(network) == {'name', 'id'}
            and isinstance(network['name'], str) and NETWORK.fullmatch(network['name'])
            and isinstance(network['id'], str) and RESOURCE_ID.fullmatch(network['id']), 'contract-network')
    for key, pattern in (('containers', CONTAINER), ('reserved_legacy', RESOURCE_ID)):
        values = data[key]
        require(isinstance(values, dict) and set(values) == set(SERVICES)
                and all(isinstance(v, str) and pattern.fullmatch(v) for v in values.values())
                and len(set(values.values())) == len(SERVICES), 'contract-' + key.replace('_', '-'))
    require(not set(data['containers'].values()) & set(SERVICES), 'contract-containers')
    return data


def load(path):
    """Regular file, final component never followed, bounded, strict JSON."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise Refused('contract-unreadable') from None
    with os.fdopen(fd, 'rb') as handle:
        require(stat.S_ISREG(os.fstat(handle.fileno()).st_mode), 'contract-not-regular')
        raw = handle.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, 'contract-too-large')
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError):
        raise Refused('contract-invalid-json') from None
    return validate(data)


def canonical(contract):
    return json.dumps(validate(contract), indent=2, sort_keys=True) + '\n'


def overlay(contract, image=None, sha=None):
    """Compose overlay (YAML flow): project name, single external default network,
    container names, ``depends_on`` reset and the legacy-only services profiled out.

    ``depends_on`` must be reset: with the dependencies outside the project,
    ``compose start`` refuses ``backend is missing dependency redis`` even after
    ``up --no-deps``. Only ``networks.default`` is redefined (no service-level
    ``networks``), so Compose cannot union a second network.
    """
    validate(contract)
    require((image is None) == (sha is None), 'overlay-pin')
    require(image is None or ((IMAGE_REF.fullmatch(image) or IMAGE_ID.fullmatch(image)) and SHA.fullmatch(sha)),
            'overlay-pin')
    q = json.dumps
    services = []
    for role in SERVICES:
        fields = [f'"container_name": {q(contract["containers"][role])}', '"depends_on": !reset {}']
        if image is not None:
            fields += [f'"image": {q(image)}', f'"environment": {{"PASTORAI_RELEASE_SHA": {q(sha)}}}']
        services.append(f'    {q(role)}: {{{", ".join(fields)}}}')
    services += [f'    {q(name)}: {{"profiles": [{q(DEPENDENCY_PROFILE)}]}}' for name in BASE_ONLY]
    return ('# Generated from the validated release topology; public data only.\n'
            f'{{"name": {q(contract["project"])},\n'
            f' "networks": {{"default": {{"name": {q(contract["network"]["name"])}, "external": true}}}},\n'
            ' "services": {\n' + ',\n'.join(services) + '}}\n')


def check_config(contract, model):
    """The effective model is the adopted topology and nothing else."""
    require(isinstance(model, dict) and model.get('name') == contract['project'], 'config-project')
    networks = model.get('networks')
    require(isinstance(networks, dict) and set(networks) == {'default'}
            and networks['default'].get('external') is True
            and networks['default'].get('name') == contract['network']['name']
            and set(networks['default']) <= {'name', 'external', 'ipam'}
            and not networks['default'].get('ipam'), 'config-network')
    services = model.get('services')
    require(isinstance(services, dict) and set(services) == set(SERVICES), 'config-services')
    for role in SERVICES:
        service = services[role]
        require(service.get('container_name') == contract['containers'][role], 'config-container-name')
        require(set(service.get('networks') or {}) == {'default'} and 'network_mode' not in service,
                'config-service-network')
        require(not service.get('depends_on') and not service.get('links')
                and not service.get('external_links'), 'config-dependencies')


def write_new(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write(text)
    os.chmod(path, 0o644)


# -- Docker state (guard) -------------------------------------------------------
def docker(*args):
    try:
        done = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        raise Refused('docker-unavailable') from None
    require(done.returncode == 0, 'docker-read-failed:' + '-'.join(args[:2]))  # fixed verb, never values
    return done.stdout


def parse_row(line):
    cid, name, running, policy, project, service, oneoff, health, image, networks = json.loads(line)
    return dict(id=cid, name=(name or '').lstrip('/'), running=running is True, policy=policy,
                project=project or None, service=service or None, oneoff=oneoff or None,
                health=health, image=image, networks=networks or {})


def list_containers(attempts=3):
    """Every container on the engine, one consistent listing + inspect.

    A container removed between ``ls`` and ``inspect`` (another process) makes
    the inspect fail; the whole read is retried a bounded number of times and
    then refused, never partially accepted.
    """
    for _ in range(attempts):
        ids = docker('container', 'ls', '-aq', '--no-trunc').split()
        if not ids:
            return []
        try:
            rows = docker('container', 'inspect', '--format', INSPECT, *ids).splitlines()
        except Refused:
            continue
        try:
            containers = [parse_row(line) for line in rows]
        except (TypeError, ValueError):
            raise Refused('docker-state-unparseable') from None
        require({c['id'] for c in containers} == set(ids) and len(containers) == len(ids), 'docker-state-changed')
        return containers
    raise Refused('docker-read-failed')


def read_state(contract):
    network = docker('network', 'inspect', '--format', '[{{json .Id}},{{json .Name}}]', contract['network']['name'])
    try:
        network_id, network_name = json.loads(network)
    except (TypeError, ValueError):
        raise Refused('docker-state-unparseable') from None
    return dict(network=dict(id=network_id, name=network_name), containers=list_containers())


def names_on(container, network):
    attached = container['networks'].get(network) or {}
    return set(attached.get('Aliases') or ()) | set(attached.get('DNSNames') or ()) | {container['name']}


def ownership(contract, state):
    """``(owned, strangers)`` among members of the adopted project.

    Owned = carries the contracted container name for its own service label,
    is not a one-off and is not a reserved legacy ID. Every other member is a
    stranger: never stopped, recreated or started by the release. Pure; used by
    containment, which must not depend on network or dependency health.
    """
    project = contract['project']
    reserved = set(contract['reserved_legacy'].values())
    owned, strangers = [], []
    for c in state['containers']:
        if c['project'] != project:
            continue
        if (c['id'] not in reserved and c['service'] in SERVICES and c['oneoff'] in (None, 'False')
                and c['name'] == contract['containers'][c['service']]):
            owned.append(c)
        else:
            strangers.append(c)
    return owned, strangers


def check_targets(contract, state):
    """Strict ownership before any recreate/start: network identity, reserved legacy
    contained and outside the project, contracted names owned, no stranger member."""
    project, net = contract['project'], contract['network']
    require(state['network'] == {'id': net['id'], 'name': net['name']}, 'network-identity')
    by_id = {c['id']: c for c in state['containers']}
    names = {name: role for role, name in contract['containers'].items()}
    for cid in contract['reserved_legacy'].values():
        legacy = by_id.get(cid)
        require(legacy is not None, 'legacy-reserved-missing')
        require(not legacy['running'] and legacy['policy'] == 'no', 'legacy-reserved-not-contained')
        require(legacy['project'] != project and legacy['name'] not in names, 'legacy-reserved-in-project')
    for c in state['containers']:
        if c['name'] in names:
            require(c['project'] == project and c['service'] == names[c['name']], 'container-name-not-owned')
    owned, strangers = ownership(contract, state)
    require(not strangers, 'project-foreign-member')
    return {c['service']: c for c in owned}  # names are unique, so at most one per role


def check_readiness(contract, state):
    """Before any start: no running container outside the project answers to a service
    alias on the network, and exactly one healthy Redis and Evolution are running."""
    project, network = contract['project'], contract['network']['name']
    names = set(SERVICES) | set(contract['containers'].values())
    outside = [c for c in state['containers'] if c['project'] != project and c['running']
               and network in c['networks']]
    for c in outside:
        require(not names_on(c, network) & names, 'alias-conflict')
    for alias in DEPENDENCY_ALIASES:
        found = [c for c in outside if alias in names_on(c, network)]
        require(len(found) == 1, 'dependency-not-running')
        require(found[0]['health'] in (None, 'healthy'), 'dependency-unhealthy')


def evaluate(contract, phase, state, revisions=None, revision=None):
    """Refuse unless Docker state matches ``phase``; ``revisions`` maps image ID -> revision label.

    ``replace`` (before a recreate) is ownership only and admits 0/1 owned member per
    role; the other phases precede a start and also require readiness and identity.
    """
    require(phase in PHASES, 'guard-phase')
    members = check_targets(contract, state)
    if phase == 'replace':
        return
    check_readiness(contract, state)
    network = contract['network']['name']
    roles = SERVICES if phase != 'checker' else ('backend',)
    images = set()
    for role in roles:
        c = members.get(role)
        require(c is not None, 'project-service-identity')
        if phase == 'predecessor':
            require(c['running'] and network in c['networks'], 'predecessor-not-running')
        else:
            require(not c['running'], 'created-container-running')
            require(set(c['networks']) == {network}, 'created-network-union')
        images.add(c['image'])
    if phase == 'checker':
        require(not any(members[r]['running'] for r in SERVICES[1:] if r in members), 'checker-consumer-running')
    require(len(images) == 1, 'image-identity-inconsistent')
    require(revision is not None and (revisions or {}).get(images.pop()) == revision, 'image-revision-mismatch')


def guard(contract, phase, revision=None):
    state = read_state(contract)
    revisions = {}
    if phase != 'replace':
        require(revision is not None and SHA.fullmatch(revision), 'guard-revision')
        for image in {c['image'] for c in state['containers'] if c['project'] == contract['project']}:
            require(isinstance(image, str) and IMAGE_ID.fullmatch(image), 'image-identity')
            revisions[image] = docker('image', 'inspect', '--format',
                                      '{{index .Config.Labels "' + REVISION_LABEL + '"}}', image).strip()
    evaluate(contract, phase, state, revisions, revision)


def owned_ids(contract):
    """IDs safe to stop. Reads only container listing/inspect; network and dependencies
    are irrelevant here, so a degraded Redis/Evolution never blocks containment."""
    owned, strangers = ownership(contract, dict(containers=list_containers()))
    require(all(RESOURCE_ID.fullmatch(c['id']) for c in owned), 'docker-state-unparseable')
    return [c['id'] for c in owned], len(strangers)


def image_name(model):
    """The single image the four services share in the effective model (the build tag)."""
    services = (model or {}).get('services') if isinstance(model, dict) else None
    require(isinstance(services, dict) and set(SERVICES) <= set(services), 'config-services')
    images = {services[role].get('image') for role in SERVICES}
    require(len(images) == 1, 'config-image')
    image = images.pop()
    require(isinstance(image, str) and LOCAL_TAG.fullmatch(image), 'config-image')
    return image


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('validate', 'overlay', 'persist', 'check-config', 'guard', 'owned', 'image-name'):
        command = sub.add_parser(name)
        command.add_argument('--contract', required=True)
        if name == 'validate':
            command.add_argument('--marker')
        if name in ('overlay', 'persist'):
            command.add_argument('--out', required=True)
        if name == 'overlay':
            command.add_argument('--image')
            command.add_argument('--sha')
        if name == 'guard':
            command.add_argument('--phase', required=True, choices=PHASES)
            command.add_argument('--revision')
    args = parser.parse_args(argv)
    try:
        contract = load(args.contract)
        if args.command == 'validate':
            if args.marker:
                try:
                    fd = os.open(args.marker, os.O_RDONLY | os.O_NOFOLLOW)
                except OSError:
                    raise Refused('marker-unreadable') from None
                with os.fdopen(fd, 'rb') as handle:
                    require(stat.S_ISREG(os.fstat(handle.fileno()).st_mode), 'marker-unreadable')
                    marker = handle.read(256)
                require(marker == (contract['project'] + '\n').encode(), 'marker-project-mismatch')
            print(contract['project'])
        elif args.command == 'overlay':
            write_new(args.out, overlay(contract, args.image, args.sha))
        elif args.command == 'persist':
            write_new(args.out, canonical(contract))
        elif args.command == 'check-config':
            try:
                model = json.load(sys.stdin)
            except ValueError:
                raise Refused('config-unparseable') from None
            check_config(contract, model)
        elif args.command == 'image-name':
            try:
                model = json.load(sys.stdin)
            except ValueError:
                raise Refused('config-unparseable') from None
            print(image_name(model))
        elif args.command == 'owned':
            ids, strangers = owned_ids(contract)
            print('\n'.join(ids))
            if strangers:
                print('release topology refused: project-foreign-member left untouched', file=sys.stderr)
                return 3
        else:
            guard(contract, args.phase, args.revision)
    except Refused as exc:
        print(f'release topology refused: {exc}', file=sys.stderr)
        return 1
    except OSError:
        print('release topology refused: file-operation', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
