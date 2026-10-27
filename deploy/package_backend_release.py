#!/usr/bin/env python3
"""Build a reproducible production tarball from exact, allowlisted Git blobs.

No worktree content, Git archive attributes, credentials or administrative
scripts enter the archive. Uses the existing protected-path/blob reader; it
never executes the candidate. This only creates a local artifact, not a release.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import tempfile

from initial_transition_files import git_tree, no_symlink
from initial_transition_ops import Refused, require

REQUIRED = (
    'backend/Dockerfile', 'backend/.dockerignore', 'backend/requirements.lock',
    'backend/scripts/migrate.py', 'backend/app/main.py',
    'deploy/backend-release.sh', 'deploy/check_backend_schema.py',
    'deploy/emit_schema_check.py', 'deploy/schema_compatibility.py',
    'deploy/release_topology.py', 'deploy/docker-compose.yml',
)
PATHSPECS = ('backend/app', 'backend/migrations', *REQUIRED)
ALLOWLIST = re.compile(
    r'backend/app/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*\.py'
    r'|backend/migrations/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_.-]+\.sql'
    r'|' + '|'.join(re.escape(name) for name in REQUIRED)
)


def build(repo: Path, sha: str, output: Path) -> dict:
    output = no_symlink(output)
    require(not output.exists(), 'package-output-exists')
    files = git_tree(repo, sha, PATHSPECS, ALLOWLIST)
    require(set(REQUIRED) <= files.keys(), 'package-required-files')
    require(any(re.fullmatch(r'backend/migrations/[^/]+\.sql', name) for name in files),
            'package-migrations-missing')
    manifest = {
        'commit': sha,
        'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
    }
    contents = {**files, 'release-manifest.json': (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()}
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w', format=tarfile.PAX_FORMAT) as tar:
        for name, data in sorted(contents.items()):
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            entry.mode = 0o755 if name == 'deploy/backend-release.sh' else 0o644
            # TarInfo defaults: regular file, uid/gid/mtime zero, no owner names.
            tar.addfile(entry, io.BytesIO(data))
    payload = gzip.compress(archive.getvalue(), mtime=0)
    # Publish atomically without overwriting an existing artifact, even if another
    # invocation created it after the early check. No partial tarball is consumed.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix='release-package-', delete=False) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o644)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output)
    except OSError:
        raise Refused('package-output') from None
    finally:
        if temporary is not None:
            temporary.unlink()
    return {'commit': sha, 'files': len(files), 'sha256': hashlib.sha256(payload).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.repo, args.sha, args.output)
    except Refused as exc:
        print(f'package refused: {exc}', file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print('package refused: invalid source or output', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
