"""Release packaging from exact Git blobs; fixtures contain only synthetic data."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_backend_release as package


class ReleasePackageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='release-package-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.files = {
            'backend/Dockerfile': b'FROM scratch\nCOPY app /app\n',
            'backend/.dockerignore': b'**\n!app/**\n',
            'backend/requirements.lock': b'# synthetic empty dependency lock\n',
            'backend/scripts/migrate.py': b'# synthetic migration runner\n',
            'backend/app/main.py': b'original = "$Format:%H$"\n',
            'backend/app/services/__init__.py': b'',
            'backend/migrations/0001_example.sql': b'SELECT 1;\n',
            'deploy/backend-release.sh': b'BACKEND_RELEASE_SAFETY_VERSION=3\n',
            'deploy/check_backend_schema.py': b'# synthetic checker\n',
            'deploy/emit_schema_check.py': b'# synthetic emitter\n',
            'deploy/schema_compatibility.py': b'# synthetic schema\n',
            'deploy/release_topology.py': b'# synthetic topology\n',
            'deploy/docker-compose.yml': b'services: {}\n',
        }
        for name, data in self.files.items():
            self.write(name, data)
        # Explicitly fake fixtures: none is a real secret, export or environment.
        for name in ('backend/.env', 'backend/scripts/target_users_fixture.json',
                     'backend/scripts/admin_fixture.py', 'deploy/id_rsa_fixture',
                     'deploy/exports/fixture.json', '.env.example'):
            self.write(name, b'SYNTHETIC_EXCLUDED_CONTENT\n')
        self.write('.gitattributes', b'backend/app/main.py export-ignore export-subst\n')
        self.sha = self.commit()
        self.output = self.root / 'release.tar.gz'

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.DEVNULL)

    def write(self, name, data):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
                 'commit', '-qm', 'synthetic package fixture')
        return self.git('rev-parse', 'HEAD').decode().strip()

    def test_exact_blobs_ignore_dirty_worktree_attributes_and_untracked_files(self):
        self.write('backend/app/main.py', b'SYNTHETIC_DIRTY_WORKTREE\n')
        self.write('backend/app/untracked.py', b'SYNTHETIC_UNTRACKED\n')
        result = package.build(self.repo, self.sha, self.output)
        self.assertTrue(self.output.is_file(), 'the reviewed archive must be created')
        with tarfile.open(self.output, 'r:gz') as tar:
            self.assertEqual(set(tar.getnames()), {*self.files, 'release-manifest.json'})
            for name, data in self.files.items():
                self.assertEqual(tar.extractfile(name).read(), data)
            manifest = json.load(tar.extractfile('release-manifest.json'))
            self.assertEqual(manifest['commit'], self.sha)
            self.assertEqual(manifest['files'], {n: hashlib.sha256(d).hexdigest() for n, d in self.files.items()})
            for member in tar.getmembers():
                self.assertTrue(member.isfile())
                self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 0))
                self.assertEqual(member.mode, 0o755 if member.name == 'deploy/backend-release.sh' else 0o644)
        self.assertEqual(result['sha256'], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(result['files'], len(self.files))

    def test_archive_is_reproducible(self):
        package.build(self.repo, self.sha, self.output)
        second = self.root / 'second.tar.gz'
        package.build(self.repo, self.sha, second)
        self.assertEqual(self.output.read_bytes(), second.read_bytes())

    def test_branch_short_sha_and_invalid_sha_refused_without_output(self):
        for sha in ('HEAD', self.sha[:8], '0' * 40, '../main'):
            with self.subTest(sha=sha), self.assertRaises(package.Refused):
                package.build(self.repo, sha, self.output)
            self.assertFalse(self.output.exists())

    def test_required_runtime_file_missing_refuses(self):
        (self.repo / 'deploy/release_topology.py').unlink()
        sha = self.commit()
        with self.assertRaisesRegex(package.Refused, 'package-required-files'):
            package.build(self.repo, sha, self.output)
        self.assertFalse(self.output.exists())

    def test_selected_symlink_refused(self):
        (self.repo / 'backend/app/linked.py').symlink_to('../.env')
        sha = self.commit()
        with self.assertRaisesRegex(package.Refused, 'source-entry-type'):
            package.build(self.repo, sha, self.output)
        self.assertFalse(self.output.exists())

    def test_nested_protected_path_refused_before_any_blob_is_read(self):
        self.write('backend/app/secrets/fixture.py', b'SYNTHETIC_PROTECTED\n')
        sha = self.commit()
        real_run = subprocess.run
        calls = []

        def recorded(args, **kwargs):
            calls.append(args)
            return real_run(args, **kwargs)

        with patch('initial_transition_files.subprocess.run', side_effect=recorded):
            with self.assertRaisesRegex(package.Refused, 'source-protected-path'):
                package.build(self.repo, sha, self.output)
        self.assertFalse(any('cat-file' in args for args in calls))
        self.assertFalse(self.output.exists())

    def test_unselected_protected_files_are_never_read(self):
        forbidden = {self.git('rev-parse', self.sha + ':' + p).decode().strip() for p in
                     ('backend/.env', 'backend/scripts/target_users_fixture.json', 'deploy/id_rsa_fixture')}
        real_run = subprocess.run
        read = []

        def recorded(args, **kwargs):
            if 'cat-file' in args:
                read.append(args[-1])
            return real_run(args, **kwargs)

        with patch('initial_transition_files.subprocess.run', side_effect=recorded):
            package.build(self.repo, self.sha, self.output)
        self.assertTrue(read)
        self.assertFalse(forbidden.intersection(read))

    def test_existing_archive_and_symlink_are_not_overwritten(self):
        target = self.root / 'keep'
        target.write_bytes(b'KEEP_SYNTHETIC')
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                if symlink:
                    self.output.symlink_to(target)
                else:
                    self.output.write_bytes(b'KEEP_SYNTHETIC')
                with self.assertRaises(package.Refused):
                    package.build(self.repo, self.sha, self.output)
                self.assertEqual(self.output.read_bytes(), b'KEEP_SYNTHETIC')
                self.assertEqual(target.read_bytes(), b'KEEP_SYNTHETIC')
                self.output.unlink()

    def test_cli_outputs_only_metadata_and_sanitizes_errors(self):
        command = [sys.executable, str(Path(package.__file__)), '--repo', str(self.repo),
                   '--sha', self.sha, '--output', str(self.output)]
        done = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)['commit'], self.sha)
        refused = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertNotIn(str(self.root), refused.stderr)
        self.assertNotIn('SYNTHETIC_EXCLUDED_CONTENT', done.stdout + done.stderr + refused.stderr)


if __name__ == '__main__':
    unittest.main()
