"""Execute packaging shell offline, without credentials, Git writes or dispatch."""
import os
from pathlib import Path
import subprocess
import tempfile
import tarfile
import io
import unittest

WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/backend-deploy-manual.yml'

class WorkflowTest(unittest.TestCase):
    def package(self, **overrides):
        source = WORKFLOW.read_text()
        step = source.split('      - name: Package exact main commit\n', 1)[1]
        block = step.split('        run: |\n', 1)[1].split('\n      - ', 1)[0]
        script = '\n'.join(line[10:] for line in block.splitlines())
        with tempfile.TemporaryDirectory(prefix='release-workflow-fixture-') as directory:
            root = Path(directory)
            git = root / 'git'
            git.write_text('''#!/bin/sh
case "$*" in
  'merge-base --is-ancestor '* )
    if [ "$3" = "$SAFE_BASE_SHA" ]; then exit "${SAFE_BASE_ANCESTRY_EXIT:-0}"; fi
    exit "${ANCESTRY_EXIT:-0}" ;;
  'show '* )
    if [ "${LEGACY_SCRIPT:-0}" = 1 ]; then exit 0; fi
    printf '%s\\n' BACKEND_RELEASE_SAFETY_VERSION=2 ;;
  'archive '* ) touch "$RUNNER_TEMP/packaged" ;;
esac
exit 0
''')
            git.chmod(0o755)
            env = {**os.environ, 'PATH': f'{root}:'+os.environ['PATH'],
                   'RUNNER_TEMP': directory, 'RELEASE_SHA': 'b'*40,
                   'SAFE_BASE_SHA': 'a'*40, 'ALLOWED_ACTORS': 'raniel',
                   'RELEASE_ACTOR': 'raniel', 'TRIGGERING_ACTOR': 'raniel', **overrides}
            result = subprocess.run(['bash','-c',script], env=env, capture_output=True, text=True)
            return result, (root / 'packaged').exists()

    def test_missing_allowlist_refuses_packaging(self):
        result, packaged = self.package(ALLOWED_ACTORS='')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(packaged)

    def test_actor_outside_allowlist_refuses_packaging(self):
        result, packaged = self.package(RELEASE_ACTOR='outsider')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(packaged)

    def test_missing_safe_base_refuses_packaging(self):
        result, packaged = self.package(SAFE_BASE_SHA='')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(packaged)

    def test_sha_before_safe_base_refuses_packaging(self):
        result, packaged = self.package(SAFE_BASE_ANCESTRY_EXIT='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(packaged)

    def test_old_safety_layer_refuses_packaging(self):
        result, packaged = self.package(LEGACY_SCRIPT='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(packaged)

    def test_candidate_outside_main_refuses_packaging(self):
        result, packaged = self.package(ANCESTRY_EXIT='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(packaged)

    def test_reviewed_actor_and_descendant_packages(self):
        result, packaged = self.package()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(packaged)

    def test_rerun_actor_outside_allowlist_refuses(self):
        result, packaged = self.package(TRIGGERING_ACTOR='outsider')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(packaged)

    def test_substring_actor_refuses(self):
        result, packaged = self.package(RELEASE_ACTOR='ran')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(packaged)

    def transport(self, **overrides):
        source = WORKFLOW.read_text()
        step = source.split('      - name: Deploy backend with schema gate and code rollback\n',1)[1]
        block = step.split('        run: |\n',1)[1].split('\n      - ',1)[0]
        script = '\n'.join(line[10:] for line in block.splitlines())
        with tempfile.TemporaryDirectory(prefix='transport-fixture-') as directory:
            root = Path(directory)
            (root / 'releases').mkdir()
            archive = root / ('backend-release-'+ 'b'*40 + '.tar.gz')
            with tarfile.open(archive, 'w:gz') as tar:
                data = b'#!/bin/sh\nexit "${REMOTE_RELEASE_EXIT:-0}"\n'
                info = tarfile.TarInfo('deploy/backend-release.sh')
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            scp = root / 'scp'
            scp.write_text("#!/usr/bin/env python3\nimport os,shutil,sys\nif os.environ.get('SCP_EXIT') == '1': sys.exit(1)\nshutil.copyfile(sys.argv[-2], os.environ['REMOTE_TAR'])\n")
            ssh = root / 'ssh'
            ssh.write_text("#!/usr/bin/env python3\nimport os,subprocess,sys\nif os.environ.get('SSH_EXIT') == '1': sys.exit(1)\ncommand=sys.argv[-1].replace('/opt/pastorai-releases',os.environ['RUNNER_TEMP']+'/releases').replace('/tmp/pastorai-'+os.environ['RELEASE_SHA']+'.tar.gz',os.environ['REMOTE_TAR'])\nsys.exit(subprocess.run(['bash','-c',command]).returncode)\n")
            for tool in (scp,ssh): tool.chmod(0o755)
            env = {**os.environ, 'PATH': str(root)+':'+os.environ['PATH'],
                   'RUNNER_TEMP':directory,'RELEASE_SHA':'b'*40,
                   'REMOTE_TAR':str(root/'remote.tar.gz'),'DEPLOY_HOST':'synthetic.invalid',
                   'DEPLOY_USER':'synthetic','DEPLOY_SSH_KEY':'INERT_FIXTURE',
                   'DEPLOY_KNOWN_HOSTS':'INERT_FIXTURE',**overrides}
            result = subprocess.run(['bash','-c',script],env=env,capture_output=True,text=True)
            return result, archive.exists(), (root/'remote.tar.gz').exists(), (root/'backend-deploy-key').exists(), (root/'backend-deploy-known-hosts').exists()

    def test_remote_release_failure_cleans_both_tarballs_and_private_files(self):
        result, local, remote, key, hosts = self.transport(REMOTE_RELEASE_EXIT='1')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(local or remote or key or hosts)
        self.assertNotIn('INERT_FIXTURE',result.stdout+result.stderr)

    def test_success_cleans_transport_artifacts(self):
        result, local, remote, key, hosts = self.transport()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(local or remote or key or hosts)

    def test_scp_failure_cleans_runner(self):
        result, local, remote, key, hosts = self.transport(SCP_EXIT='1')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(local or remote or key or hosts)

    def test_ssh_failure_reports_remote_cleanup_limit(self):
        result, local, remote, key, hosts = self.transport(SSH_EXIT='1')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(local or key or hosts)
        self.assertTrue(remote)  # documented recovery needs the human transport gate

    def test_only_manual_trigger(self):
        triggers = WORKFLOW.read_text().split('on:\n',1)[1].split('\npermissions:',1)[0]
        self.assertEqual([line.strip() for line in triggers.splitlines() if line.startswith('  ') and not line.startswith('    ')], ['workflow_dispatch:'])
