"""Durable journal, exact Git blobs and release layout of the initial transition.

Every local path (spec, state/journal, compose, release layout) is refused
when any component is protected (``.env*``, ``secrets``, keys, dumps, ...)
before it is opened, created or even ``lstat``-ed; then symlinks are refused
for the path and every existing ancestor and files are opened ``O_NOFOLLOW``.
Git paths with a protected component are refused before any blob is read,
even when they would match the allowlist.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import runpy
import stat
import subprocess
import tempfile
import time
from pathlib import Path

from initial_transition_ops import MIGRATION, SHA, Refused, require
import release_topology

PROTECTED = re.compile(r'(?:\.env.*|secrets?|.*\.pem|.*\.key|id_rsa.*|id_ed25519.*|target_users.*|.*\.dump'
                       r'|dumps?|backups?|exports?|media|migrate_clerk_production.*|clerk_.*)', re.IGNORECASE)
CLERK = re.compile(r'.*clerk.*', re.IGNORECASE)


def is_protected(parts):
    """Protected component, or any clerk-named entry under a ``scripts`` directory (admin tooling).

    Pure string check: callers apply it before any lstat/open/cat-file.
    """
    parts = [p for p in parts if p not in ('', os.sep)]
    return any(PROTECTED.fullmatch(p) for p in parts) or any(
        CLERK.fullmatch(p) for i, p in enumerate(parts) if 'scripts' in (q.lower() for q in parts[:i]))
LAYOUT_DEPLOY = ('backend-release.sh', 'check_backend_schema.py', 'emit_schema_check.py',
                 'schema_compatibility.py', 'docker-compose.yml')
LAYOUT_SQL = re.compile(r'backend/migrations/(?:[A-Za-z0-9_]+/)?[A-Za-z0-9_.-]+\.sql')
MAX_FILE = 4 * 1024 * 1024


def no_symlink(path):
    """Refuse a protected component anywhere in ``path`` (checked on the string, before any
    filesystem access), then a symlink in ``path`` or any existing ancestor (no TOCTOU-free claim)."""
    path = Path(os.path.abspath(path))
    require(not is_protected(path.parts), 'protected-path')
    for candidate in (path, *path.parents):
        try:
            if stat.S_ISLNK(os.lstat(candidate).st_mode):
                raise Refused('symlink-refused')
        except FileNotFoundError:
            continue
    return path


def read_regular(path, limit=MAX_FILE):
    path = no_symlink(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise Refused('file-unreadable') from None
    with os.fdopen(fd, 'rb') as handle:
        require(stat.S_ISREG(os.fstat(handle.fileno()).st_mode), 'file-not-regular')
        data = handle.read(limit + 1)
    require(len(data) <= limit, 'file-too-large')
    return data


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# -- journal --------------------------------------------------------------
class Journal:
    """Append-only JSON lines, one writer (``flock``), full write + ``fsync`` per record.

    Opening validates every record (JSON object, consecutive ``seq``, ``kind``)
    and refuses a torn tail instead of guessing what the crashed writer meant.
    """

    def __init__(self, directory, *, writer=os.write):
        self.dir = Path(directory)
        self.path = self.dir / 'journal.jsonl'
        self.lock_fd = None
        self.events = []
        self.writer = writer

    def __enter__(self):
        return self.open()

    def __exit__(self, *_):
        self.close()

    def open(self):
        no_symlink(self.dir)
        self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(stat.S_ISDIR(os.lstat(self.dir).st_mode), 'state-not-directory')
        no_symlink(self.dir / 'journal.lock')
        no_symlink(self.path)
        self.lock_fd = os.open(self.dir / 'journal.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.close()
            raise Refused('controller-busy') from None
        created = not os.path.lexists(self.path)
        self.events = []
        if not created:
            raw = read_regular(self.path, 64 * 1024 * 1024)
            lines = raw.split(b'\n')
            require(lines[-1] == b'', 'journal-torn')
            for index, line in enumerate(lines[:-1], 1):
                try:
                    event = json.loads(line)
                except ValueError:
                    raise Refused('journal-torn') from None
                require(isinstance(event, dict) and event.get('seq') == index
                        and isinstance(event.get('kind'), str), 'journal-invalid')
                self.events.append(event)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        if created:
            dir_fd = os.open(self.dir, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        return self

    def close(self):
        if self.lock_fd is not None:
            os.close(self.lock_fd)  # releases the flock
            self.lock_fd = None

    def digest(self):
        return sha256(read_regular(self.path, 64 * 1024 * 1024) if os.path.lexists(self.path) else b'')

    def append(self, kind, **fields):
        require(self.lock_fd is not None, 'journal-not-locked')
        event = dict(seq=len(self.events) + 1, at=time.time(), kind=kind, **fields)
        line = memoryview((json.dumps(event, sort_keys=True, separators=(',', ':')) + '\n').encode())
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        try:
            while line:  # a short write is completed, never left as a torn record
                written = self.writer(fd, line)
                require(written > 0, 'journal-write')
                line = line[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        self.events.append(event)
        return event

    def find(self, kind, step=None, since=0):
        return [e for e in self.events if e['kind'] == kind and e['seq'] > since
                and (step is None or e.get('step') == step)]

    def last(self, kind, step=None, since=0):
        found = self.find(kind, step, since)
        return found[-1] if found else None


# -- Git ------------------------------------------------------------------
def git_tree(repo, sha, pathspecs, pattern, git=None):
    """``{path: bytes}`` of tracked blobs matching ``pattern``; blob hashes re-verified.

    Any listed path with a protected component refuses the whole read before
    the first ``cat-file``.
    """
    def call(*args):
        if git is not None:
            return git(list(args))
        try:
            done = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            raise Refused('git-step') from None
        require(done.returncode == 0, 'git-step')
        return done.stdout

    require(SHA.fullmatch(sha or ''), 'sha')
    require(call('rev-parse', '--verify', '--quiet', '--end-of-options', sha + '^{commit}').decode().strip() == sha,
            'sha')
    entries = []
    for entry in filter(None, call('ls-tree', '-r', '-z', '--full-tree', sha, '--', *pathspecs).split(b'\0')):
        meta, _, raw = entry.partition(b'\t')
        mode, kind, oid = meta.decode('ascii').split(' ')
        path = raw.decode('utf-8')
        require(not is_protected(path.split('/')), 'source-protected-path')
        entries.append((mode, kind, oid, path))
    files = {}
    for mode, kind, oid, path in entries:
        if not pattern.fullmatch(path):
            continue
        require(kind == 'blob' and mode in ('100644', '100755'), 'source-entry-type')
        data = call('cat-file', 'blob', oid)
        require(hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest() == oid, 'source-blob-hash')
        files[path] = data
    return files


def migration_manifest(migrate_source, sql):
    """The candidate's own selection rule over its exact SQL blobs, in a private temp tree."""
    with tempfile.TemporaryDirectory(prefix='pastorai-transition-manifest-') as directory:
        root = Path(directory)
        (root / 'scripts').mkdir()
        (root / 'migrations').mkdir()
        (root / 'scripts' / 'migrate.py').write_bytes(migrate_source)
        for name, body in sql.items():
            (root / 'migrations' / name).write_bytes(body)
        files = runpy.run_path(str(root / 'scripts' / 'migrate.py'))['migration_files'](root / 'migrations')
    require(files and all(MIGRATION.fullmatch(n) for n in files) and len(files) == len(set(files)), 'manifest')
    return files


# -- release layout -----------------------------------------------------------
def layout_files(files, topology, image, sha):
    """Exact blobs plus the public topology contract and maintenance override.

    The helper the runner needs travels with it as an exact blob. The override
    pins the candidate's verified local image ID (no registry digest invented),
    so ordinary Compose maintenance never falls back to a mutable tag. The
    layout holds no build source: recovery to it reuses that image ID.
    """
    wanted = {f'deploy/{name}': files[f'deploy/{name}'] for name in LAYOUT_DEPLOY}
    helper = 'deploy/release_topology.py'
    if helper in files:
        wanted[helper] = files[helper]
    require(helper in files or b'release_topology.py' not in files['deploy/backend-release.sh'], 'layout-helper-missing')
    wanted['backend/scripts/migrate.py'] = files['backend/scripts/migrate.py']
    wanted.update({p: b for p, b in files.items() if LAYOUT_SQL.fullmatch(p)})
    try:
        wanted['deploy/release-topology.json'] = release_topology.canonical(topology).encode()
        wanted['deploy/docker-compose.override.yml'] = release_topology.overlay(topology, image, sha).encode()
    except release_topology.Refused as exc:
        raise Refused('layout-topology') from exc
    return wanted


def inventory(root):
    """Relative regular files under ``root`` by ``lstat`` only; links/specials/protected refused unread."""
    found = []
    for top, dirs, names in os.walk(root, followlinks=False):
        for name in [*dirs, *names]:
            full = os.path.join(top, name)
            rel = os.path.relpath(full, root)
            require(not is_protected(rel.split(os.sep)), 'layout-unsafe-entry')  # before lstat
            mode = os.lstat(full).st_mode
            require(not stat.S_ISLNK(mode), 'layout-unsafe-entry')
            if name in names:
                require(stat.S_ISREG(mode), 'layout-unsafe-entry')
                found.append(rel)
    return sorted(found)


def write_layout(root, sha, files, topology, manifest, image):
    """``releases/<sha>`` from exact blobs (tooling, runner, SQL), the topology contract and
    the maintenance override pinned to ``image`` (verified ID); no private config. Idempotent."""
    releases = no_symlink(Path(root) / 'releases')
    releases.mkdir(mode=0o755, parents=True, exist_ok=True)
    require(release_topology.IMAGE_ID.fullmatch(image or ''), 'layout-topology')
    wanted = layout_files(files, topology, image, sha)
    target = releases / sha
    if os.path.lexists(target):
        require(stat.S_ISDIR(os.lstat(target).st_mode), 'layout-mismatch')
        if inventory(target) != sorted(wanted):  # decided before reading any content
            raise Refused('layout-mismatch')
        if any(read_regular(target / p) != wanted[p] for p in sorted(wanted)):
            raise Refused('layout-mismatch')
        return len(wanted)
    staging = Path(tempfile.mkdtemp(prefix=f'.{sha}.staging-', dir=releases))
    for path, data in sorted(wanted.items()):
        out = staging / path
        out.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o755 if path.endswith('.sh') else 0o644)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
    staging.chmod(0o755)
    found = runpy.run_path(str(staging / 'backend/scripts/migrate.py'))['migration_files'](staging / 'backend/migrations')
    require(found == manifest, 'layout-manifest')
    os.rename(staging, target)
    return len(wanted)


def activate(root, sha):
    root = no_symlink(Path(root))
    link, target = root / 'current', root / 'releases' / sha
    require(os.path.isdir(target) and not os.path.islink(target), 'layout-missing')
    if os.path.islink(link):
        require(os.readlink(link) == str(target), 'current-exists')
        return
    require(not os.path.lexists(link), 'current-exists')
    staging = root / f'current.next.{os.getpid()}'
    if os.path.lexists(staging):
        os.unlink(staging)
    os.symlink(target, staging)
    os.replace(staging, link)
