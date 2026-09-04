#!/usr/bin/env python3
"""Materialize one verified, private snapshot of an exact local Git commit.

The command deliberately accepts a full commit object id rather than a ref.
It reads only the local Git object database, invokes ``git archive`` without a
shell, and never inherits the process environment.  The resulting checkout is
source evidence only; it grants no permission to run operational tooling.

Successful CLI invocations leave the verified snapshot in ``/tmp`` for the
caller.  Library callers can remove it with :meth:`RepositorySnapshot.cleanup`.
Every failed creation attempts to remove only the random directory created by
that invocation, after checking its filesystem identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
from typing import BinaryIO, Callable


REPO_ROOT = Path(__file__).absolute().parents[2]
TEMP_ROOT = Path("/tmp")
SNAPSHOT_PREFIX = "pastorai-trusted-repository-"
SNAPSHOT_REPOSITORY_BASENAME = "repo"
ARCHIVE_BASENAME = ".repository-archive.tar"

MAX_CONTROL_OUTPUT_BYTES = 8_192
MAX_COMMIT_BYTES = 8 * 1_048_576
MAX_MANIFEST_BYTES = 32 * 1_048_576
MAX_ENTRIES = 100_000
MAX_PATH_BYTES = 4_096
MAX_FILE_BYTES = 128 * 1_048_576
MAX_TOTAL_FILE_BYTES = 1_073_741_824
GIT_TIMEOUT_SECONDS = 60

FULL_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
OBJECT_FORMATS = {"sha1": 40, "sha256": 64}
SAFE_MODES = {"040000", "100644", "100755"}

RESULT_CREATED = "RESULT=TRUSTED_REPOSITORY_SNAPSHOT_CREATED_OFFLINE"
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=false"
NEXT_STAGE_BLOCK = "NEXT_STAGE_AUTHORIZED=false"


class SnapshotError(RuntimeError):
    exit_code = 4
    reason = "SNAPSHOT_INVALID"


class UsageError(SnapshotError):
    exit_code = 2
    reason = "USAGE"


class GitEvidenceError(SnapshotError):
    exit_code = 3
    reason = "LOCAL_GIT_EVIDENCE_INVALID"


class ArchiveError(SnapshotError):
    exit_code = 4
    reason = "ARCHIVE_INVALID"


class FilesystemError(SnapshotError):
    exit_code = 5
    reason = "SNAPSHOT_FILESYSTEM_INVALID"


class CleanupError(SnapshotError):
    exit_code = 6
    reason = "SNAPSHOT_CLEANUP_INVALID"


@dataclass(frozen=True, slots=True)
class ObjectIdentity:
    device: int
    inode: int
    uid: int
    gid: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> "ObjectIdentity":
        return cls(
            device=int(value.st_dev),
            inode=int(value.st_ino),
            uid=int(value.st_uid),
            gid=int(value.st_gid),
        )


@dataclass(frozen=True, slots=True)
class StableStat:
    device: int
    inode: int
    mode: int
    links: int
    uid: int
    gid: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> "StableStat":
        return cls(
            device=int(value.st_dev),
            inode=int(value.st_ino),
            mode=int(value.st_mode),
            links=int(value.st_nlink),
            uid=int(value.st_uid),
            gid=int(value.st_gid),
            size=int(value.st_size),
            mtime_ns=int(value.st_mtime_ns),
            ctime_ns=int(value.st_ctime_ns),
        )


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    path: str
    mode: str
    object_type: str
    object_id: str
    size: int | None


@dataclass(frozen=True, slots=True)
class RepositoryManifest:
    git_sha: str
    object_format: str
    root_tree_id: str
    entries: tuple[ManifestEntry, ...]
    total_file_bytes: int

    @property
    def file_count(self) -> int:
        return sum(entry.object_type == "blob" for entry in self.entries)

    @property
    def tree_count(self) -> int:
        return sum(entry.object_type == "tree" for entry in self.entries)


@dataclass(slots=True)
class RepositorySnapshot:
    root: Path
    repository: Path
    git_sha: str
    file_count: int
    tree_count: int
    _root_identity: ObjectIdentity = field(repr=False)
    _cleaned: bool = field(default=False, init=False, repr=False)

    def cleanup(self) -> None:
        """Remove this snapshot without following links or another root."""

        if self._cleaned:
            return
        _cleanup_created_root(self.root, self._root_identity)
        self._cleaned = True


GitControl = Callable[[Path, tuple[str, ...], int], bytes]
ArchiveWriter = Callable[[Path, str, int], None]


def _minimal_git_environment() -> dict[str, str]:
    """Return a fixed environment with lazy fetch and network protocols off."""

    return {
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PROTOCOL_FROM_USER": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.defpath,
    }


def _safe_repository_path(repository_root: object) -> Path:
    if not isinstance(repository_root, Path) or not repository_root.is_absolute():
        raise UsageError
    if any(part in {"", ".", ".."} for part in repository_root.parts[1:]):
        raise UsageError
    try:
        encoded = os.fsencode(repository_root)
    except (TypeError, UnicodeError, ValueError) as exc:
        raise UsageError from exc
    if not encoded or b"\x00" in encoded or any(byte < 32 for byte in encoded):
        raise UsageError
    try:
        snapshot = os.lstat(repository_root)
    except OSError as exc:
        raise GitEvidenceError from exc
    if not stat.S_ISDIR(snapshot.st_mode):
        raise GitEvidenceError
    return repository_root


def _validated_sha(value: object) -> str:
    if (
        type(value) is not str
        or FULL_SHA_RE.fullmatch(value) is None
        or set(value) == {"0"}
    ):
        raise UsageError
    return value


def _git_control_args_allowed(args: tuple[str, ...]) -> bool:
    if args in {
        ("rev-parse", "--show-object-format"),
        ("rev-parse", "--show-toplevel"),
    }:
        return True
    if (
        len(args) == 3
        and args[:2] == ("rev-parse", "--verify")
        and re.fullmatch(
            r"(?:[0-9a-f]{40}|[0-9a-f]{64})\^\{(?:commit|tree)\}",
            args[2],
        )
    ):
        return True
    if (
        len(args) == 3
        and args[:2] == ("cat-file", "commit")
        and FULL_SHA_RE.fullmatch(args[2]) is not None
    ):
        return True
    return (
        len(args) == 7
        and args[:6]
        == ("ls-tree", "-r", "-t", "-l", "-z", "--full-tree")
        and FULL_SHA_RE.fullmatch(args[6]) is not None
    )


def _run_git_control(
    repository_root: Path,
    args: tuple[str, ...],
    maximum: int,
) -> bytes:
    if (
        type(args) is not tuple
        or not _git_control_args_allowed(args)
        or type(maximum) is not int
        or maximum < 1
        or maximum > MAX_MANIFEST_BYTES
    ):
        raise GitEvidenceError
    command = [
        "git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "protocol.allow=never",
        "-C",
        str(repository_root),
        *args,
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            cwd=repository_root,
            env=_minimal_git_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise GitEvidenceError from exc
    if completed.returncode != 0 or len(completed.stdout) > maximum:
        raise GitEvidenceError
    return completed.stdout


def _run_git_archive(
    repository_root: Path,
    git_sha: str,
    archive_fd: int,
) -> None:
    _validated_sha(git_sha)
    if type(archive_fd) is not int or archive_fd < 3:
        raise ArchiveError
    command = [
        "git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "protocol.allow=never",
        "-c",
        "tar.umask=0022",
        "-C",
        str(repository_root),
        "archive",
        "--format=tar",
        git_sha,
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            cwd=repository_root,
            env=_minimal_git_environment(),
            stdin=subprocess.DEVNULL,
            stdout=archive_fd,
            stderr=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ArchiveError from exc
    if completed.returncode != 0:
        raise ArchiveError


def _single_ascii_line(content: bytes, pattern: re.Pattern[str]) -> str:
    if type(content) is not bytes or len(content) > MAX_CONTROL_OUTPUT_BYTES:
        raise GitEvidenceError
    try:
        value = content.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise GitEvidenceError from exc
    if pattern.fullmatch(value) is None:
        raise GitEvidenceError
    return value


def _validated_relative_path(raw: bytes | str) -> str:
    if type(raw) is bytes:
        if not raw or len(raw) > MAX_PATH_BYTES:
            raise GitEvidenceError
        try:
            value = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise GitEvidenceError from exc
    elif type(raw) is str:
        try:
            encoded = raw.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ArchiveError from exc
        if not encoded or len(encoded) > MAX_PATH_BYTES:
            raise ArchiveError
        value = raw
    else:
        raise ArchiveError
    if (
        value.startswith("/")
        or value.endswith("/")
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ArchiveError if type(raw) is str else GitEvidenceError
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ArchiveError if type(raw) is str else GitEvidenceError
    return value


def _is_protected_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    basename = parts[-1]
    lowered = basename.lower()
    if "secrets" in {part.lower() for part in parts}:
        return True
    if lowered == ".env" or (
        lowered.startswith(".env.") and not lowered.endswith(".example")
    ):
        return True
    if lowered.endswith((".pem", ".key")):
        return True
    if lowered.startswith(("id_rsa", "id_ed25519")):
        return True
    if len(parts) == 3 and parts[:2] == ("backend", "scripts"):
        if basename.startswith("clerk_"):
            return True
        if basename.startswith("target_users") and lowered.endswith(".json"):
            return True
        if basename == "migrate_clerk_production.py":
            return True
    return False


def _hash_git_object(object_format: str, object_type: str, content: bytes) -> str:
    if object_format not in OBJECT_FORMATS or object_type not in {
        "blob",
        "commit",
        "tree",
    }:
        raise GitEvidenceError
    digest = hashlib.new(object_format)
    digest.update(object_type.encode("ascii"))
    digest.update(b" ")
    digest.update(str(len(content)).encode("ascii"))
    digest.update(b"\x00")
    digest.update(content)
    return digest.hexdigest()


def _validated_commit_tree(
    *,
    object_format: str,
    expected_commit_id: str,
    content: bytes,
) -> str:
    """Authenticate raw commit bytes and return their single initial tree."""

    object_length = OBJECT_FORMATS.get(object_format)
    if (
        object_length is None
        or type(content) is not bytes
        or not content
        or len(content) > MAX_COMMIT_BYTES
        or len(expected_commit_id) != object_length
        or FULL_SHA_RE.fullmatch(expected_commit_id) is None
        or _hash_git_object(object_format, "commit", content)
        != expected_commit_id
    ):
        raise GitEvidenceError
    header_end = content.find(b"\n\n")
    if header_end < 0:
        raise GitEvidenceError
    headers = content[:header_end].split(b"\n")
    expected_prefix = b"tree "
    if not headers or not headers[0].startswith(expected_prefix):
        raise GitEvidenceError
    raw_tree_id = headers[0][len(expected_prefix) :]
    object_re = re.compile(
        rb"[0-9a-f]{" + str(object_length).encode("ascii") + rb"}"
    )
    if object_re.fullmatch(raw_tree_id) is None:
        raise GitEvidenceError
    if any(header.startswith(expected_prefix) for header in headers[1:]):
        raise GitEvidenceError
    return raw_tree_id.decode("ascii")


def _git_tree_sort_key(entry: ManifestEntry) -> bytes:
    name = PurePosixPath(entry.path).name.encode("utf-8")
    return name + (b"/" if entry.object_type == "tree" else b"\x00")


def _validate_tree_ids(manifest: RepositoryManifest) -> None:
    children: dict[str, list[ManifestEntry]] = {"": []}
    entries = {entry.path: entry for entry in manifest.entries}
    for entry in manifest.entries:
        parent = str(PurePosixPath(entry.path).parent)
        if parent == ".":
            parent = ""
        if parent and (
            parent not in entries or entries[parent].object_type != "tree"
        ):
            raise GitEvidenceError
        children.setdefault(parent, []).append(entry)
        if entry.object_type == "tree":
            children.setdefault(entry.path, [])

    computed: dict[str, str] = {}
    directories = sorted(children, key=lambda value: value.count("/"), reverse=True)
    for directory in directories:
        payload = bytearray()
        for child in sorted(children[directory], key=_git_tree_sort_key):
            mode = b"40000" if child.object_type == "tree" else child.mode.encode("ascii")
            object_id = computed.get(child.path, child.object_id)
            payload.extend(mode)
            payload.extend(b" ")
            payload.extend(PurePosixPath(child.path).name.encode("utf-8"))
            payload.extend(b"\x00")
            try:
                payload.extend(bytes.fromhex(object_id))
            except ValueError as exc:
                raise GitEvidenceError from exc
        tree_id = _hash_git_object(manifest.object_format, "tree", bytes(payload))
        if directory:
            if tree_id != entries[directory].object_id:
                raise GitEvidenceError
            computed[directory] = tree_id
        elif tree_id != manifest.root_tree_id:
            raise GitEvidenceError


def _parse_manifest(
    *,
    git_sha: str,
    object_format: str,
    root_tree_id: str,
    content: bytes,
) -> RepositoryManifest:
    expected_length = OBJECT_FORMATS.get(object_format)
    if expected_length is None or len(root_tree_id) != expected_length:
        raise GitEvidenceError
    records = content.split(b"\x00")
    if not records or records[-1] != b"":
        raise GitEvidenceError
    records.pop()
    if not records or len(records) > MAX_ENTRIES:
        raise GitEvidenceError

    entries: list[ManifestEntry] = []
    seen: set[str] = set()
    seen_casefold: set[str] = set()
    total = 0
    object_re = re.compile(rb"[0-9a-f]{" + str(expected_length).encode("ascii") + rb"}")
    for record in records:
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode_raw, type_raw, object_raw, size_raw = metadata.split()
        except ValueError as exc:
            raise GitEvidenceError from exc
        if mode_raw.decode("ascii", errors="strict") not in SAFE_MODES:
            raise GitEvidenceError
        mode = mode_raw.decode("ascii")
        object_type = type_raw.decode("ascii", errors="strict")
        if object_type not in {"blob", "tree"} or object_re.fullmatch(object_raw) is None:
            raise GitEvidenceError
        path = _validated_relative_path(raw_path)
        if path in seen or path.casefold() in seen_casefold or _is_protected_path(path):
            raise GitEvidenceError
        seen.add(path)
        seen_casefold.add(path.casefold())
        if object_type == "tree":
            if mode != "040000" or size_raw != b"-":
                raise GitEvidenceError
            size = None
        else:
            if mode not in {"100644", "100755"} or not size_raw.isdigit():
                raise GitEvidenceError
            size = int(size_raw, 10)
            if size > MAX_FILE_BYTES:
                raise GitEvidenceError
            total += size
            if total > MAX_TOTAL_FILE_BYTES:
                raise GitEvidenceError
        entries.append(
            ManifestEntry(
                path=path,
                mode=mode,
                object_type=object_type,
                object_id=object_raw.decode("ascii"),
                size=size,
            )
        )
    manifest = RepositoryManifest(
        git_sha=git_sha,
        object_format=object_format,
        root_tree_id=root_tree_id,
        entries=tuple(entries),
        total_file_bytes=total,
    )
    _validate_tree_ids(manifest)
    return manifest


def _source_identity(path: Path) -> tuple[int, int, int, int, int]:
    try:
        value = os.lstat(path)
    except OSError as exc:
        raise GitEvidenceError from exc
    if not stat.S_ISDIR(value.st_mode):
        raise GitEvidenceError
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_uid),
        int(value.st_gid),
    )


def _load_manifest(
    repository_root: Path,
    git_sha: str,
    git_control: GitControl,
) -> RepositoryManifest:
    supplied = _validated_sha(git_sha)
    top_level = git_control(
        repository_root,
        ("rev-parse", "--show-toplevel"),
        MAX_CONTROL_OUTPUT_BYTES,
    )
    try:
        reported_root = Path(top_level.decode("utf-8", errors="strict").strip())
    except UnicodeDecodeError as exc:
        raise GitEvidenceError from exc
    if reported_root != repository_root:
        raise GitEvidenceError

    object_format = _single_ascii_line(
        git_control(
            repository_root,
            ("rev-parse", "--show-object-format"),
            MAX_CONTROL_OUTPUT_BYTES,
        ),
        re.compile(r"sha1|sha256"),
    )
    if len(supplied) != OBJECT_FORMATS[object_format]:
        raise UsageError
    resolved = _single_ascii_line(
        git_control(
            repository_root,
            ("rev-parse", "--verify", f"{supplied}^{{commit}}"),
            MAX_CONTROL_OUTPUT_BYTES,
        ),
        FULL_SHA_RE,
    )
    if resolved != supplied:
        raise GitEvidenceError
    raw_commit = git_control(
        repository_root,
        ("cat-file", "commit", supplied),
        MAX_COMMIT_BYTES,
    )
    authenticated_tree_id = _validated_commit_tree(
        object_format=object_format,
        expected_commit_id=supplied,
        content=raw_commit,
    )
    root_tree_id = _single_ascii_line(
        git_control(
            repository_root,
            ("rev-parse", "--verify", f"{supplied}^{{tree}}"),
            MAX_CONTROL_OUTPUT_BYTES,
        ),
        FULL_SHA_RE,
    )
    if (
        len(root_tree_id) != OBJECT_FORMATS[object_format]
        or root_tree_id != authenticated_tree_id
    ):
        raise GitEvidenceError
    raw_manifest = git_control(
        repository_root,
        ("ls-tree", "-r", "-t", "-l", "-z", "--full-tree", supplied),
        MAX_MANIFEST_BYTES,
    )
    return _parse_manifest(
        git_sha=supplied,
        object_format=object_format,
        root_tree_id=root_tree_id,
        content=raw_manifest,
    )


def _directory_flags() -> int:
    required = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW")
    if any(not hasattr(os, name) for name in required):
        raise FilesystemError
    return os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW


def _file_create_flags() -> int:
    required = ("O_CLOEXEC", "O_NOFOLLOW")
    if any(not hasattr(os, name) for name in required):
        raise FilesystemError
    return os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW


def _archive_create_flags() -> int:
    return (
        _file_create_flags()
        & ~os.O_WRONLY
        | os.O_RDWR
    )


def _open_directory_at(parent_fd: int, name: str) -> int:
    try:
        descriptor = os.open(name, _directory_flags(), dir_fd=parent_fd)
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except (OSError, ValueError) as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        raise FilesystemError from exc
    if (
        not stat.S_ISDIR(opened.st_mode)
        or ObjectIdentity.from_stat(opened) != ObjectIdentity.from_stat(named)
    ):
        os.close(descriptor)
        raise FilesystemError
    return descriptor


def _open_parent(repository_fd: int, path: str) -> int:
    descriptor = os.dup(repository_fd)
    try:
        parts = PurePosixPath(path).parts[:-1]
        for part in parts:
            child = _open_directory_at(descriptor, part)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _create_manifest_directories(
    repository_fd: int,
    manifest: RepositoryManifest,
) -> None:
    directories = sorted(
        (entry.path for entry in manifest.entries if entry.object_type == "tree"),
        key=lambda value: (value.count("/"), value),
    )
    for path in directories:
        parent_fd = _open_parent(repository_fd, path)
        try:
            name = PurePosixPath(path).name
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            child_fd = _open_directory_at(parent_fd, name)
            try:
                os.fchmod(child_fd, 0o700)
            finally:
                os.close(child_fd)
        except (OSError, ValueError) as exc:
            raise FilesystemError from exc
        finally:
            os.close(parent_fd)


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        try:
            written = os.write(descriptor, content[offset:])
        except OSError as exc:
            raise FilesystemError from exc
        if written <= 0:
            raise FilesystemError
        offset += written


def _archive_upper_bound(manifest: RepositoryManifest) -> int:
    overhead = 1_048_576 + sum(
        4_096 + len(entry.path.encode("utf-8")) for entry in manifest.entries
    )
    return manifest.total_file_bytes + overhead


def _extract_archive(
    archive_file: BinaryIO,
    repository_fd: int,
    manifest: RepositoryManifest,
) -> None:
    expected = {entry.path: entry for entry in manifest.entries}
    seen: set[str] = set()
    try:
        archive = tarfile.open(
            fileobj=archive_file,
            mode="r:",
            ignore_zeros=True,
        )
    except (OSError, tarfile.TarError, ValueError) as exc:
        raise ArchiveError from exc
    try:
        for member in archive:
            path = _validated_relative_path(member.name)
            if path in seen or path not in expected:
                raise ArchiveError
            seen.add(path)
            entry = expected[path]
            if member.linkname or member.sparse is not None:
                raise ArchiveError
            if entry.object_type == "tree":
                if not member.isdir() or member.mode != 0o755 or member.size != 0:
                    raise ArchiveError
                continue
            archive_mode = 0o755 if entry.mode == "100755" else 0o644
            if (
                not member.isreg()
                or member.mode != archive_mode
                or member.size != entry.size
            ):
                raise ArchiveError
            source = archive.extractfile(member)
            if source is None:
                raise ArchiveError
            parent_fd = _open_parent(repository_fd, path)
            descriptor: int | None = None
            try:
                descriptor = os.open(
                    PurePosixPath(path).name,
                    _file_create_flags(),
                    0o600,
                    dir_fd=parent_fd,
                )
                digest = hashlib.new(manifest.object_format)
                header = f"blob {member.size}\0".encode("ascii")
                digest.update(header)
                remaining = member.size
                while remaining:
                    chunk = source.read(min(65_536, remaining))
                    if not chunk:
                        raise ArchiveError
                    remaining -= len(chunk)
                    digest.update(chunk)
                    _write_all(descriptor, chunk)
                if source.read(1) != b"" or digest.hexdigest() != entry.object_id:
                    raise ArchiveError
                os.fchmod(descriptor, 0o600)
                file_stat = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(file_stat.st_mode)
                    or stat.S_IMODE(file_stat.st_mode) != 0o600
                    or file_stat.st_nlink != 1
                    or file_stat.st_size != entry.size
                    or file_stat.st_uid != os.geteuid()
                    or file_stat.st_gid != os.getegid()
                ):
                    raise FilesystemError
            except (OSError, ValueError) as exc:
                raise FilesystemError from exc
            finally:
                source.close()
                if descriptor is not None:
                    os.close(descriptor)
                os.close(parent_fd)
    except (OSError, tarfile.TarError) as exc:
        raise ArchiveError from exc
    finally:
        archive.close()
    if seen != set(expected):
        raise ArchiveError


def _read_and_hash_file(
    parent_fd: int,
    name: str,
    entry: ManifestEntry,
    object_format: str,
) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except (OSError, ValueError) as exc:
        raise FilesystemError from exc
    try:
        before = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or ObjectIdentity.from_stat(before) != ObjectIdentity.from_stat(named)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or before.st_gid != os.getegid()
            or before.st_size != entry.size
        ):
            raise FilesystemError
        chunks: list[bytes] = []
        total = 0
        while total < before.st_size:
            chunk = os.read(descriptor, min(65_536, before.st_size - total))
            if not chunk:
                raise FilesystemError
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        if StableStat.from_stat(before) != StableStat.from_stat(after):
            raise FilesystemError
        if _hash_git_object(object_format, "blob", b"".join(chunks)) != entry.object_id:
            raise FilesystemError
    except OSError as exc:
        raise FilesystemError from exc
    finally:
        os.close(descriptor)


def _validate_materialized_directory(
    directory_fd: int,
    relative: str,
    expected: dict[str, ManifestEntry],
    object_format: str,
) -> None:
    current = os.fstat(directory_fd)
    if (
        not stat.S_ISDIR(current.st_mode)
        or stat.S_IMODE(current.st_mode) != 0o700
        or current.st_uid != os.geteuid()
        or current.st_gid != os.getegid()
        or current.st_nlink < 1
    ):
        raise FilesystemError
    try:
        with os.scandir(directory_fd) as iterator:
            names = sorted(entry.name for entry in iterator)
    except (OSError, ValueError) as exc:
        raise FilesystemError from exc
    expected_names = sorted(
        PurePosixPath(path).name
        for path in expected
        if str(PurePosixPath(path).parent) == (relative or ".")
    )
    if names != expected_names:
        raise FilesystemError
    for name in names:
        path = f"{relative}/{name}" if relative else name
        entry = expected[path]
        try:
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as exc:
            raise FilesystemError from exc
        if entry.object_type == "tree":
            if not stat.S_ISDIR(named.st_mode):
                raise FilesystemError
            child_fd = _open_directory_at(directory_fd, name)
            try:
                _validate_materialized_directory(
                    child_fd,
                    path,
                    expected,
                    object_format,
                )
            finally:
                os.close(child_fd)
        else:
            _read_and_hash_file(directory_fd, name, entry, object_format)


def _validate_snapshot_root(
    root_fd: int,
    repository_fd: int,
    manifest: RepositoryManifest,
) -> None:
    root_stat = os.fstat(root_fd)
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_IMODE(root_stat.st_mode) != 0o700
        or root_stat.st_uid != os.geteuid()
        or root_stat.st_gid != os.getegid()
    ):
        raise FilesystemError
    try:
        with os.scandir(root_fd) as iterator:
            if sorted(entry.name for entry in iterator) != [
                SNAPSHOT_REPOSITORY_BASENAME
            ]:
                raise FilesystemError
    except (OSError, ValueError) as exc:
        raise FilesystemError from exc
    expected = {entry.path: entry for entry in manifest.entries}
    _validate_materialized_directory(repository_fd, "", expected, manifest.object_format)


def _same_identity(value: os.stat_result, expected: ObjectIdentity) -> bool:
    return ObjectIdentity.from_stat(value) == expected and stat.S_ISDIR(value.st_mode)


def _open_trusted_temp_root() -> int:
    """Open the real system ``/tmp`` under a fail-closed ownership contract.

    On a normal host both ``/`` and ``/tmp`` are ``root:root``.  User-
    namespace sandboxes can expose the host owner through an overflow uid;
    that equivalent is accepted only when both directories have the same
    non-caller owner, ``/`` is not group/other-writable, and ``/tmp`` is the
    direct, non-symlink child with exact mode ``01777``.
    """

    if TEMP_ROOT != Path("/tmp"):
        raise FilesystemError
    root_fd: int | None = None
    temp_fd: int | None = None
    try:
        root_fd = os.open(Path("/"), _directory_flags())
        filesystem_root = os.fstat(root_fd)
        named_temp = os.stat("tmp", dir_fd=root_fd, follow_symlinks=False)
        temp_fd = os.open("tmp", _directory_flags(), dir_fd=root_fd)
        opened_temp = os.fstat(temp_fd)
    except (OSError, ValueError) as exc:
        if temp_fd is not None:
            os.close(temp_fd)
        if root_fd is not None:
            os.close(root_fd)
        raise FilesystemError from exc
    os.close(root_fd)
    caller_uid = os.geteuid()
    ownership_is_safe = (
        filesystem_root.st_uid == 0
        and named_temp.st_uid == 0
        and filesystem_root.st_gid == 0
        and named_temp.st_gid == 0
    ) or (
        caller_uid != 0
        and filesystem_root.st_uid != caller_uid
        and named_temp.st_uid == filesystem_root.st_uid
        and named_temp.st_gid == filesystem_root.st_gid
    )
    if (
        not stat.S_ISDIR(filesystem_root.st_mode)
        or stat.S_IMODE(filesystem_root.st_mode) & 0o022
        or not stat.S_ISDIR(named_temp.st_mode)
        or stat.S_IMODE(named_temp.st_mode) != 0o1777
        or named_temp.st_nlink < 1
        or ObjectIdentity.from_stat(named_temp)
        != ObjectIdentity.from_stat(opened_temp)
        or not ownership_is_safe
    ):
        os.close(temp_fd)
        raise FilesystemError
    return temp_fd


def _remove_tree_contents(directory_fd: int, root_device: int) -> None:
    try:
        with os.scandir(directory_fd) as iterator:
            names = [entry.name for entry in iterator]
    except (OSError, ValueError) as exc:
        raise CleanupError from exc
    for name in names:
        try:
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(named.st_mode):
                if named.st_dev != root_device:
                    raise CleanupError
                child_fd = _open_directory_at(directory_fd, name)
                try:
                    _remove_tree_contents(child_fd, root_device)
                    after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if ObjectIdentity.from_stat(after) != ObjectIdentity.from_stat(named):
                        raise CleanupError
                finally:
                    os.close(child_fd)
                os.rmdir(name, dir_fd=directory_fd)
            else:
                os.unlink(name, dir_fd=directory_fd)
        except CleanupError:
            raise
        except (OSError, ValueError) as exc:
            raise CleanupError from exc


def _cleanup_created_root(root: Path, identity: ObjectIdentity) -> None:
    if (
        not isinstance(root, Path)
        or root.parent != TEMP_ROOT
        or not root.name.startswith(SNAPSHOT_PREFIX)
        or "/" in root.name
    ):
        raise CleanupError
    parent_fd: int | None = None
    root_fd: int | None = None
    try:
        parent_fd = _open_trusted_temp_root()
        named = os.stat(root.name, dir_fd=parent_fd, follow_symlinks=False)
        if not _same_identity(named, identity):
            raise CleanupError
        root_fd = _open_directory_at(parent_fd, root.name)
        if not _same_identity(os.fstat(root_fd), identity):
            raise CleanupError
        _remove_tree_contents(root_fd, identity.device)
        os.close(root_fd)
        root_fd = None
        final = os.stat(root.name, dir_fd=parent_fd, follow_symlinks=False)
        if not _same_identity(final, identity):
            raise CleanupError
        os.rmdir(root.name, dir_fd=parent_fd)
    except CleanupError:
        raise
    except (OSError, ValueError) as exc:
        raise CleanupError from exc
    finally:
        if root_fd is not None:
            os.close(root_fd)
        if parent_fd is not None:
            os.close(parent_fd)


def _remove_empty_created_directory_at(
    parent_fd: int,
    name: str,
    identity: ObjectIdentity,
) -> None:
    """Remove a just-created empty directory only if its inode still matches."""

    try:
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not _same_identity(named, identity):
            raise CleanupError
        os.rmdir(name, dir_fd=parent_fd)
    except CleanupError:
        raise
    except (OSError, ValueError) as exc:
        raise CleanupError from exc


def _create_random_directory_at(temp_fd: int) -> tuple[str, ObjectIdentity]:
    """Create a private random child and capture its identity immediately."""

    for _attempt in range(128):
        try:
            name = f"{SNAPSHOT_PREFIX}{os.urandom(16).hex()}"
        except (OSError, ValueError) as exc:
            raise FilesystemError from exc
        try:
            os.mkdir(name, 0o700, dir_fd=temp_fd)
        except FileExistsError:
            continue
        except (OSError, ValueError) as exc:
            raise FilesystemError from exc
        try:
            named = os.stat(name, dir_fd=temp_fd, follow_symlinks=False)
        except (OSError, ValueError) as exc:
            # The name was created by the immediately preceding mkdirat and
            # has never been opened or populated.  rmdir-at cannot follow a
            # substituted symlink and therefore is the only safe fallback
            # when the kernel will not disclose an inode for comparison.
            try:
                os.rmdir(name, dir_fd=temp_fd)
            except OSError as cleanup_exc:
                raise CleanupError from cleanup_exc
            raise FilesystemError from exc
        identity = ObjectIdentity.from_stat(named)
        if (
            not stat.S_ISDIR(named.st_mode)
            or stat.S_IMODE(named.st_mode) != 0o700
            or named.st_uid != os.geteuid()
            or named.st_gid != os.getegid()
        ):
            _remove_empty_created_directory_at(temp_fd, name, identity)
            raise FilesystemError
        return name, identity
    raise FilesystemError


def _create_private_root() -> tuple[Path, ObjectIdentity, int]:
    temp_fd = _open_trusted_temp_root()
    root: Path | None = None
    root_name: str | None = None
    root_fd: int | None = None
    identity: ObjectIdentity | None = None
    try:
        root_name, identity = _create_random_directory_at(temp_fd)
        root = TEMP_ROOT / root_name
        root_fd = _open_directory_at(temp_fd, root_name)
        os.fchmod(root_fd, 0o700)
        root_stat = os.fstat(root_fd)
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or ObjectIdentity.from_stat(root_stat) != identity
            or stat.S_IMODE(root_stat.st_mode) != 0o700
            or root_stat.st_uid != os.geteuid()
            or root_stat.st_gid != os.getegid()
        ):
            raise FilesystemError
        return root, ObjectIdentity.from_stat(root_stat), root_fd
    except BaseException as exc:
        if root_fd is not None:
            os.close(root_fd)
        if root_name is not None and identity is not None:
            try:
                _remove_empty_created_directory_at(
                    temp_fd,
                    root_name,
                    identity,
                )
            except CleanupError as cleanup_exc:
                raise cleanup_exc from exc
        if isinstance(exc, (OSError, ValueError)):
            raise FilesystemError from exc
        raise
    finally:
        os.close(temp_fd)


def create_trusted_repository_snapshot(
    *,
    repository_root: Path = REPO_ROOT,
    git_sha: object,
    git_control: GitControl = _run_git_control,
    archive_writer: ArchiveWriter = _run_git_archive,
) -> RepositorySnapshot:
    """Create and verify a private snapshot of ``git_sha`` under ``/tmp``."""

    source = _safe_repository_path(repository_root)
    supplied_sha = _validated_sha(git_sha)
    source_before = _source_identity(source)
    manifest = _load_manifest(source, supplied_sha, git_control)
    if _source_identity(source) != source_before:
        raise GitEvidenceError

    root: Path | None = None
    identity: ObjectIdentity | None = None
    root_fd: int | None = None
    repository_fd: int | None = None
    archive_fd: int | None = None
    archive_name_present = False
    try:
        root, identity, root_fd = _create_private_root()
        os.mkdir(SNAPSHOT_REPOSITORY_BASENAME, 0o700, dir_fd=root_fd)
        repository_fd = _open_directory_at(root_fd, SNAPSHOT_REPOSITORY_BASENAME)
        os.fchmod(repository_fd, 0o700)
        _create_manifest_directories(repository_fd, manifest)

        archive_fd = os.open(
            ARCHIVE_BASENAME,
            _archive_create_flags(),
            0o600,
            dir_fd=root_fd,
        )
        archive_name_present = True
        os.fchmod(archive_fd, 0o600)
        archive_writer(source, supplied_sha, archive_fd)
        archive_stat = os.fstat(archive_fd)
        if (
            not stat.S_ISREG(archive_stat.st_mode)
            or stat.S_IMODE(archive_stat.st_mode) != 0o600
            or archive_stat.st_nlink != 1
            or archive_stat.st_uid != os.geteuid()
            or archive_stat.st_gid != os.getegid()
            or archive_stat.st_size <= 0
            or archive_stat.st_size > _archive_upper_bound(manifest)
        ):
            raise ArchiveError
        os.lseek(archive_fd, 0, os.SEEK_SET)
        with os.fdopen(os.dup(archive_fd), "rb", closefd=True) as archive_file:
            _extract_archive(archive_file, repository_fd, manifest)
        os.close(archive_fd)
        archive_fd = None
        os.unlink(ARCHIVE_BASENAME, dir_fd=root_fd)
        archive_name_present = False
        if _source_identity(source) != source_before:
            raise GitEvidenceError
        _validate_snapshot_root(root_fd, repository_fd, manifest)
        return RepositorySnapshot(
            root=root,
            repository=root / SNAPSHOT_REPOSITORY_BASENAME,
            git_sha=supplied_sha,
            file_count=manifest.file_count,
            tree_count=manifest.tree_count,
            _root_identity=identity,
        )
    except BaseException as exc:
        if archive_fd is not None:
            os.close(archive_fd)
        if archive_name_present and root_fd is not None:
            try:
                os.unlink(ARCHIVE_BASENAME, dir_fd=root_fd)
            except OSError:
                pass
        if repository_fd is not None:
            os.close(repository_fd)
        if root_fd is not None:
            os.close(root_fd)
        if root is not None and identity is not None:
            try:
                _cleanup_created_root(root, identity)
            except CleanupError as cleanup_exc:
                raise cleanup_exc from exc
        raise
    finally:
        if repository_fd is not None:
            try:
                os.close(repository_fd)
            except OSError:
                pass
        if root_fd is not None:
            try:
                os.close(root_fd)
            except OSError:
                pass


def _parse_args(args: list[str]) -> str:
    if len(args) != 2 or args[0] != "--git-sha":
        raise UsageError
    return _validated_sha(args[1])


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        git_sha = _parse_args(args)
        snapshot = create_trusted_repository_snapshot(git_sha=git_sha)
    except SnapshotError as exc:
        print(f"RESULT=BLOCKED_TRUSTED_REPOSITORY_SNAPSHOT:{exc.reason}")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return exc.exit_code
    except Exception:
        print("RESULT=BLOCKED_TRUSTED_REPOSITORY_SNAPSHOT:INTERNAL_ERROR")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return 10
    print(RESULT_CREATED)
    print(f"SOURCE_GIT_SHA={snapshot.git_sha}")
    print(f"SNAPSHOT_ROOT={snapshot.root}")
    print(f"SNAPSHOT_REPOSITORY={snapshot.repository}")
    print(f"REGULAR_FILE_COUNT={snapshot.file_count}")
    print(f"TREE_COUNT={snapshot.tree_count}")
    print(OPERATIONAL_BLOCK)
    print(NEXT_STAGE_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
