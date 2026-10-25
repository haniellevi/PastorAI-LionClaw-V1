"""Pure contract, overlay and Docker-state rules of ``release_topology`` (fictitious data, no Docker)."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import release_topology as rt  # noqa: E402

SERVICES = rt.SERVICES
PROJECT, NETWORK = 'pastorai-permanent', 'pastorai_default'
IMAGE_OLD, IMAGE_NEW = 'sha256:' + '1' * 64, 'sha256:' + '2' * 64


def contract(**changes):
    value = dict(schema=rt.SCHEMA, version=1, project=PROJECT, legacy_project='pastorai',
                 network=dict(name=NETWORK, id='e' * 64),
                 containers={s: f'{PROJECT}-{s}' for s in SERVICES},
                 reserved_legacy={s: str(i) * 64 for i, s in enumerate(SERVICES, 1)})
    value.update(changes)
    return value


def container(cid, name, *, running=True, project=PROJECT, service=None, policy='always', health=None,
              image=IMAGE_OLD, networks=None, oneoff='False'):
    return dict(id=cid, name=name, running=running, policy=policy, project=project, service=service,
                oneoff=oneoff if project else None, health=health, image=image,
                networks={NETWORK: {'Aliases': [name]}} if networks is None else networks)


def world(running=True, image=IMAGE_OLD):
    c = contract()
    rows = [container(cid, 'legacy-' + s, running=False, project='pastorai' if s != 'broadcast-worker' else None,
                      service=s if s != 'broadcast-worker' else None, policy='no')
            for s, cid in c['reserved_legacy'].items()]
    rows += [container('d' * 63 + str(i), 'legacy-' + alias, project='pastorai', service=alias,
                       health='healthy' if alias == 'redis' else None,
                       networks={NETWORK: {'Aliases': [alias]}}) for i, alias in enumerate(rt.DEPENDENCY_ALIASES)]
    rows += [container('a' * 63 + str(i), c['containers'][s], running=running, service=s, image=image,
                       networks={NETWORK: {'Aliases': [c['containers'][s], s]}}) for i, s in enumerate(SERVICES)]
    return dict(network=dict(id='e' * 64, name=NETWORK), containers=rows)


class ContractTest(unittest.TestCase):
    def test_valid_contract_round_trips_canonically(self):
        self.assertEqual(json.loads(rt.canonical(contract())), contract())

    def test_invalid_contracts_are_refused(self):
        for bad in (contract(project='pastorai'), contract(project='pastorai-legacy', legacy_project='pastorai-legacy'),
                    contract(version=True), contract(schema='other'), {**contract(), 'environment': {}},
                    contract(network=dict(name=NETWORK)), contract(project='Upper'),
                    contract(containers={**contract()['containers'], 'backend': 'backend'}),
                    contract(containers={s: 'same' for s in SERVICES}),
                    contract(reserved_legacy={**contract()['reserved_legacy'], 'backend': 'short'})):
            with self.subTest(bad=bad), self.assertRaises(rt.Refused):
                rt.validate(bad)

    def test_load_refuses_duplicate_keys_symlink_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'release-topology.json'
            path.write_text(json.dumps(contract())[:-1] + ', "project": "pastorai-other"}')
            with self.assertRaises(rt.Refused):
                rt.load(path)
            real = Path(directory) / 'real.json'
            real.write_text(json.dumps(contract()))
            path.unlink()
            path.symlink_to(real)
            with self.assertRaises(rt.Refused):
                rt.load(path)
            path.unlink()
            path.write_text(' ' * (rt.MAX_BYTES + 1))
            with self.assertRaises(rt.Refused):
                rt.load(path)

    def test_overlay_pins_only_verified_ids_or_nominal_digest(self):
        text = rt.overlay(contract(), IMAGE_NEW, 'b' * 40)
        self.assertIn('"depends_on": !reset {}', text)
        self.assertIn(f'"image": "{IMAGE_NEW}"', text)
        rt.overlay(contract(), 'ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:' + '3' * 64, 'b' * 40)
        for image, sha in (('pastorai-backend:latest', 'b' * 40), (IMAGE_NEW, None), (None, 'b' * 40)):
            with self.subTest(image=image), self.assertRaises(rt.Refused):
                rt.overlay(contract(), image, sha)


class StateTest(unittest.TestCase):
    def refused(self, phase, state, code, revision='a' * 40):
        with self.assertRaises(rt.Refused) as caught:
            rt.evaluate(contract(), phase, state, {IMAGE_OLD: 'a' * 40, IMAGE_NEW: 'b' * 40}, revision)
        self.assertEqual(str(caught.exception), code)

    def test_true_predecessor_is_accepted(self):
        rt.evaluate(contract(), 'predecessor', world(), {IMAGE_OLD: 'a' * 40}, 'a' * 40)

    def test_replace_refuses_uncontracted_member_even_without_contracted_ones(self):
        # Reproduces the review case: a running ``backend`` service named unexpected-backend-copy.
        state = world()
        state['containers'] = [c for c in state['containers'] if c['project'] != PROJECT]
        state['containers'].append(container('b' * 64, 'unexpected-backend-copy', service='backend'))
        self.refused('replace', state, 'project-foreign-member')

    def test_replace_refuses_duplicate_member_of_a_role(self):
        state = world()
        state['containers'].append(container('b' * 64, 'unexpected-backend-copy', service='backend'))
        for phase in rt.PHASES:
            with self.subTest(phase=phase):
                self.refused(phase, state, 'project-foreign-member')

    def test_replace_admits_zero_or_one_owned_member_per_role(self):
        state = world()
        state['containers'] = [c for c in state['containers']
                               if not (c['project'] == PROJECT and c['service'] in ('queue-worker', 'cron-worker'))]
        rt.evaluate(contract(), 'replace', state)

    def test_replace_does_not_depend_on_dependency_health(self):
        state = world()
        state['containers'] = [c for c in state['containers'] if c['service'] not in rt.DEPENDENCY_ALIASES]
        rt.evaluate(contract(), 'replace', state)
        self.refused('predecessor', state, 'dependency-not-running')

    def test_one_off_and_reserved_ids_are_never_owned(self):
        state = world()
        state['containers'].append(container('c' * 64, 'run-backend', service='backend', oneoff='True'))
        legacy = next(c for c in state['containers'] if c['id'] == '1' * 64)
        legacy.update(project=PROJECT, name=contract()['containers']['backend'] + '-x')
        owned, strangers = rt.ownership(contract(), state)
        self.assertEqual({c['id'] for c in strangers}, {'c' * 64, '1' * 64})
        self.assertEqual(len(owned), 4)
        self.assertNotIn('1' * 64, {c['id'] for c in owned})

    def test_ownership_ignores_network_and_dependencies(self):
        state = world()
        state['network'] = dict(id='f' * 64, name='other')
        state['containers'] = [c for c in state['containers'] if c['service'] not in rt.DEPENDENCY_ALIASES]
        owned, strangers = rt.ownership(contract(), state)
        self.assertEqual((len(owned), strangers), (4, []))

    def test_readiness_and_identity_refusals(self):
        def mutate(change):
            state = copy.deepcopy(world())
            change(state)
            return state
        rogue = lambda alias: lambda s: s['containers'].append(container(
            'f' * 64, 'rogue', project='other', service='x', networks={NETWORK: {'DNSNames': [alias]}}))
        cases = (
            (lambda s: s['containers'][0].update(running=True), 'legacy-reserved-not-contained'),
            (lambda s: s['containers'][1].update(policy='always'), 'legacy-reserved-not-contained'),
            (lambda s: s['containers'].pop(2), 'legacy-reserved-missing'),
            (rogue('backend'), 'alias-conflict'), (rogue('cron-worker'), 'alias-conflict'),
            (lambda s: s['containers'][4].update(health='unhealthy'), 'dependency-unhealthy'),
            (lambda s: s['containers'].append(dict(s['containers'][5], id='9' * 64, name='evo-2')),
             'dependency-not-running'),
            (lambda s: s.update(network=dict(id='f' * 64, name=NETWORK)), 'network-identity'),
            (lambda s: s['containers'][-1].update(running=False), 'predecessor-not-running'),
            (lambda s: s['containers'][-1].update(image=IMAGE_NEW), 'image-identity-inconsistent'),
            (lambda s: s['containers'].append(container('8' * 64, contract()['containers']['backend'],
                                                        project='other', service='backend')),
             'container-name-not-owned'),
        )
        for change, code in cases:
            with self.subTest(code=code):
                self.refused('predecessor', mutate(change), code)
        self.refused('predecessor', world(), 'image-revision-mismatch', revision='c' * 40)

    def test_created_requires_single_network_and_stopped_members(self):
        state = world(running=False, image=IMAGE_NEW)
        rt.evaluate(contract(), 'created', state, {IMAGE_NEW: 'b' * 40}, 'b' * 40)
        state['containers'][-1]['networks']['second'] = {}
        self.refused('created', state, 'created-network-union', revision='b' * 40)
        self.refused('created', world(image=IMAGE_NEW), 'created-container-running', revision='b' * 40)

    def test_checker_requires_other_consumers_stopped(self):
        state = world(running=False)
        rt.evaluate(contract(), 'checker', state, {IMAGE_OLD: 'a' * 40}, 'a' * 40)
        state['containers'][-1]['running'] = True
        self.refused('checker', state, 'checker-consumer-running')


class ConfigTest(unittest.TestCase):
    def model(self):
        return {'name': PROJECT, 'networks': {'default': {'name': NETWORK, 'external': True}},
                'services': {s: {'container_name': f'{PROJECT}-{s}', 'networks': {'default': None},
                                 'image': 'pastorai-backend:latest'} for s in SERVICES}}

    def test_effective_model_and_build_tag(self):
        rt.check_config(contract(), self.model())
        self.assertEqual(rt.image_name(self.model()), 'pastorai-backend:latest')
        model = self.model()
        model['services']['cron-worker']['image'] = 'other:latest'
        with self.assertRaises(rt.Refused):
            rt.image_name(model)


class CommandTest(unittest.TestCase):
    """``owned`` against a scripted ``docker`` on PATH: exit 3 keeps strangers untouched."""

    def run_owned(self, extra_rows):
        import subprocess
        state = world()
        state['containers'] += extra_rows
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'c.json').write_text(json.dumps(contract()))
            rows = [json.dumps([c['id'], '/' + c['name'], c['running'], c['policy'], c['project'] or '',
                                c['service'] or '', c['oneoff'] or '', c['health'], c['image'], c['networks']])
                    for c in state['containers']]
            (root / 'rows').write_text('\n'.join(rows) + '\n')
            (root / 'ids').write_text('\n'.join(c['id'] for c in state['containers']) + '\n')
            docker = root / 'docker'
            docker.write_text('#!/bin/sh\ncase "$2" in ls) cat "$(dirname "$0")/ids" ;; '
                              'inspect) cat "$(dirname "$0")/rows" ;; *) exit 9 ;; esac\n')
            docker.chmod(0o755)
            env = {**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}'}
            done = subprocess.run([sys.executable, '-I', str(Path(rt.__file__)), 'owned', '--contract',
                                   str(root / 'c.json')], env=env, capture_output=True, text=True)
        return done.returncode, done.stdout.split()

    def test_owned_lists_only_contracted_members(self):
        code, ids = self.run_owned([])
        self.assertEqual((code, len(ids)), (0, 4))
        code, ids = self.run_owned([container('b' * 64, 'unexpected-backend-copy', service='backend')])
        self.assertEqual(code, 3)
        self.assertEqual(len(ids), 4)
        self.assertNotIn('b' * 64, ids)
        self.assertFalse(set(ids) & set(contract()['reserved_legacy'].values()))


if __name__ == '__main__':
    unittest.main()
