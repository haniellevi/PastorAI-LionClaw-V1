"""CONTRACT ONLY: the layout left by the initial transition vs the real ``backend-release.sh``.

Uses the existing command doubles of ``test_backend_release`` (no Docker, no
network). It proves the layout satisfies the script's preconditions for a
LATER release with all gates closed, and that preserved open gates do NOT
satisfy its guards. It is not a physical promotion, nor production evidence:
the real workflow still does not pass the candidate's Compose project.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import initial_transition as it  # noqa: E402
import initial_transition_files as itf  # noqa: E402
import test_backend_release as harness  # noqa: E402  (module, so its tests are not collected twice)

CANDIDATE_SHA = '6b0b302bd1c1f84dfef7516babee2b7767d3219c'


class LayoutContractTest(unittest.TestCase):
    setUp_harness = harness.BackendReleaseTest.setUp
    run_release = harness.BackendReleaseTest.run_release
    calls = harness.BackendReleaseTest.calls
    config_with_open_gate = harness.BackendReleaseTest.config_with_open_gate

    def setUp(self):
        self.setUp_harness()
        files = itf.git_tree(DEPLOY.parent, CANDIDATE_SHA, it.CANDIDATE_PATHSPECS, it.CANDIDATE_BLOBS)
        sql = {p.split('/', 2)[2]: b for p, b in files.items() if p.count('/') == 2 and p.startswith('backend/migrations/')}
        self.manifest = itf.migration_manifest(files['backend/scripts/migrate.py'], sql)
        os.unlink(self.root / 'current')
        itf.write_layout(self.root, CANDIDATE_SHA, files, 'pastorai-synthetic-candidate', self.manifest)
        self.layout = self.root / 'releases' / CANDIDATE_SHA
        # Operator step outside the repository: private config of the active release (fixture only).
        (self.layout / 'deploy' / 'configuration.fixture').write_text('SYNTHETIC=1\n')
        itf.activate(self.root, CANDIDATE_SHA)
        self.checker_digest = hashlib.sha256((self.layout / 'deploy' / 'check_backend_schema.py').read_bytes()).hexdigest()

    def test_layout_is_accepted_as_active_release_for_a_later_closed_gate_release(self):
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'current').resolve(), self.new.parent)
        active = str(self.layout.resolve() / 'deploy')
        self.assertIn(f'preflight-checker|{active}|{self.checker_digest}', self.calls())
        manifest = json.dumps(self.manifest, separators=(',', ':'))
        self.assertTrue(any(c.startswith(f'docker|{active}|compose exec -T -e EXPECTED_MIGRATIONS={manifest}')
                            for c in self.calls()))
        self.assertEqual(len(self.manifest), 124)

    def test_preserved_open_gates_do_not_satisfy_the_release_guards(self):
        result = self.run_release(ACTIVE_CONFIG_JSON=self.config_with_open_gate())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / 'current').resolve(), self.layout.resolve())
        self.assertFalse(any('compose build' in c or 'compose up' in c for c in self.calls()))

    def test_layout_without_private_config_is_refused_before_effects(self):
        (self.layout / 'deploy' / 'configuration.fixture').unlink()
        result = self.run_release()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c.startswith('docker|') for c in self.calls()))


if __name__ == '__main__':
    unittest.main()
