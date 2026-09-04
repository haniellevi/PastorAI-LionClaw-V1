#!/usr/bin/env python3
"""Prepare one append-only migration candidate without touching a database.

The authoring flow is deliberately split in two local-only steps:

1. ``draft`` creates exactly one timestamped SQL file with operational gates
   closed;
2. ``prepare-head`` renders, but does not install, exactly one new terminal
   append batch for independent review and controlled publication.

Neither command approves or applies a migration. The longitudinal CI verifier
must still compare the candidate head with the approved head from the base
commit, and every database action remains subject to its own human gate.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import datetime as dt
import base64
import fcntl
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import unicodedata
from types import ModuleType


REPO_ROOT = Path(__file__).absolute().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "backend" / "migrations"
GOVERNANCE_DIR = REPO_ROOT / "docs" / "governance" / "migrations"
HEAD_PATH = GOVERNANCE_DIR / "migration-catalog-head-v1.json"
SCHEMA_PATH = GOVERNANCE_DIR / "migration-catalog-head-v1.schema.json"
VERIFIER_PATH = Path(__file__).absolute().with_name(
    "verify_migration_catalog_head.py"
)
TRUSTED_SNAPSHOT_PATH = Path(__file__).absolute().with_name(
    "trusted_repository_snapshot.py"
)

MAX_DESCRIPTION_CHARS = 160
MAX_SLUG_CHARS = 120
GIT_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
MAX_BOOTSTRAP_MODULE_BYTES = 4_194_304
CATALOG_VERIFIER_SHA256 = (
    "2fe1a93bf9c9116426683e7fd86c4f7b7c20753f7ce11a8282d9ca06087ac30d"
)
TRUSTED_SNAPSHOT_SHA256 = (
    "43dd9161cda2fc3cb7e1800a1b756f5595facbcc5c15274f282f6e763252d392"
)
HEAD_RELATIVE_PATH = "docs/governance/migrations/migration-catalog-head-v1.json"
SCHEMA_RELATIVE_PATH = (
    "docs/governance/migrations/migration-catalog-head-v1.schema.json"
)
AUTHORING_RELATIVE_PATH = "backend/scripts/new_migration.py"
VERIFIER_RELATIVE_PATH = "backend/scripts/verify_migration_catalog_head.py"
TRUSTED_SNAPSHOT_RELATIVE_PATH = (
    "backend/scripts/trusted_repository_snapshot.py"
)
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
NEXT_STAGE_BLOCK = "NEXT_STAGE_AUTHORIZED=false"
INTENT_PREFIX = "-- PASTORAI_MIGRATION_INTENT_V1="
INTENT_ARTIFACT_ID = "migration-authoring-intent-v1"
INTENT_KEYS = {
    "affected_relations",
    "artifact_id",
    "base_repository_sha",
    "cross_tenant_test_nodeids",
    "decision_refs",
    "global_justification",
    "migration_basename",
    "next_stage_authorized",
    "operational_authorization",
    "pg17_test_nodeids",
    "recovery",
    "scope",
    "tenant_controls",
}
TENANT_CONTROL_KEYS = {
    "acl_review",
    "enable_rls",
    "force_rls",
    "igreja_id_column",
    "policy_context",
}
RECOVERY_KEYS = {"kind", "reference"}
DECISION_REFERENCE_RE = re.compile(
    r"^docs/decisions/[0-9]{4}-[0-9]{2}-[0-9]{2}-"
    r"[a-z0-9][a-z0-9_.-]{0,159}\.md$"
)
RECOVERY_REFERENCE_RE = re.compile(
    r"^(?:docs/decisions/[0-9]{4}-[0-9]{2}-[0-9]{2}-"
    r"[a-z0-9][a-z0-9_.-]{0,159}|"
    r"docs/ops/[A-Za-z0-9][A-Za-z0-9_.-]{0,159})\.md$"
)
TEST_NODEID_RE = re.compile(
    r"^(backend/tests/test_[A-Za-z0-9_]+\.py)::(test_[A-Za-z0-9_]+)$"
)
AFFECTED_RELATION_RE = re.compile(r"^public\.[a-z][a-z0-9_]{0,62}$")
PROTECTED_DIRECTORY_NAMES = frozenset(
    {"backup", "backups", "dump", "dumps", "export", "exports", "media", "secrets"}
)
PROTECTED_MEDIA_SUFFIXES = frozenset(
    {
        ".aac",
        ".avi",
        ".flac",
        ".gif",
        ".jpeg",
        ".jpg",
        ".m4a",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".ogg",
        ".png",
        ".wav",
        ".webm",
        ".webp",
    }
)
_LOADER_NAMESPACE = hashlib.sha256(__name__.encode("utf-8")).hexdigest()[:16]


def _read_pinned_python_source(path: Path, expected_sha256: str) -> bytes:
    """Read one module once and authenticate the exact bytes to be executed."""

    if (
        not path.is_absolute()
        or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        or any(component in {"", ".", ".."} for component in path.parts[1:])
    ):
        raise RuntimeError("bootstrap module unavailable")
    required = ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required):
        raise RuntimeError("bootstrap module unavailable")
    flags = os.O_RDONLY
    for name in required:
        flags |= getattr(os, name)
    try:
        descriptor = os.open(path, flags)
    except (OSError, ValueError) as exc:
        raise RuntimeError("bootstrap module unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > MAX_BOOTSTRAP_MODULE_BYTES
        ):
            raise RuntimeError("bootstrap module unavailable")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise RuntimeError("bootstrap module unavailable")
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_uid",
            "st_gid",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if (
            any(
                getattr(before, field) != getattr(after, field)
                for field in stable_fields
            )
            or hashlib.sha256(content).hexdigest() != expected_sha256
        ):
            raise RuntimeError("bootstrap module unavailable")
        return content
    except OSError as exc:
        raise RuntimeError("bootstrap module unavailable") from exc
    finally:
        os.close(descriptor)


def _load_pinned_python_module(
    *, module_name: str, path: Path, expected_sha256: str
) -> ModuleType:
    """Execute only the in-memory source bytes authenticated above."""

    content = _read_pinned_python_source(path, expected_sha256)
    try:
        code = compile(content, str(path), "exec", dont_inherit=True)
        module = ModuleType(module_name)
        module.__file__ = str(path)
        module.__package__ = ""
        module.__spec__ = None
        sys.modules[module_name] = module
        exec(code, module.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


trusted_snapshot = _load_pinned_python_module(
    module_name=(
        "_pastorai_trusted_repository_snapshot_for_authoring_"
        + _LOADER_NAMESPACE
    ),
    path=TRUSTED_SNAPSHOT_PATH,
    expected_sha256=TRUSTED_SNAPSHOT_SHA256,
)


def _load_catalog_verifier() -> ModuleType:
    return _load_pinned_python_module(
        module_name=(
            "_pastorai_migration_catalog_head_verifier_for_authoring_"
            + _LOADER_NAMESPACE
        ),
        path=VERIFIER_PATH,
        expected_sha256=CATALOG_VERIFIER_SHA256,
    )


catalog = _load_catalog_verifier()


class AuthoringError(RuntimeError):
    exit_code = 4
    reason = "AUTHORING_STATE_INVALID"


class UsageError(AuthoringError):
    exit_code = 2
    reason = "USAGE"


class AuthoringIoError(AuthoringError):
    exit_code = 3
    reason = "AUTHORING_IO_INVALID"


class DraftCollisionError(AuthoringError):
    exit_code = 5
    reason = "DRAFT_COLLISION"


class DraftIncompleteError(AuthoringError):
    exit_code = 6
    reason = "DRAFT_INCOMPLETE"


class RepositoryBindingError(AuthoringError):
    exit_code = 7
    reason = "LOCAL_GIT_BINDING_INVALID"


@dataclass(frozen=True)
class CatalogState:
    head: dict[str, object]
    head_record: object
    schema_record: object
    authoring_record: object
    verifier_record: object
    represented: list[dict[str, object]]
    scanned: list[dict[str, object]]


@dataclass(frozen=True)
class PreparedHeadCandidate:
    batch_id: str
    previous_approved_head_sha256: str
    content: bytes
    content_sha256: str


class _AuthoringLock:
    """Kernel-managed cooperative lock on the governance directory inode."""

    def __init__(self) -> None:
        self._directory: object | None = None

    def __enter__(self) -> "_AuthoringLock":
        opened = catalog._open_directory(GOVERNANCE_DIR, AuthoringIoError)
        try:
            fcntl.flock(
                opened.descriptor,
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except (BlockingIOError, OSError, ValueError) as exc:
            os.close(opened.descriptor)
            raise AuthoringError from exc
        self._directory = opened
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        opened = self._directory
        if opened is None:
            return
        try:
            fcntl.flock(opened.descriptor, fcntl.LOCK_UN)
        except OSError as error:
            if exc_type is None:
                raise AuthoringIoError from error
        finally:
            os.close(opened.descriptor)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def slugify(description: str) -> str:
    if (
        type(description) is not str
        or not description.strip()
        or len(description) > MAX_DESCRIPTION_CHARS
        or any(unicodedata.category(char).startswith("C") for char in description)
    ):
        raise UsageError
    normalized = unicodedata.normalize("NFKD", description)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    if not slug or len(slug) > MAX_SLUG_CHARS:
        raise UsageError
    return slug


def _validated_repository_sha(expected_sha: object) -> str:
    if (
        type(expected_sha) is not str
        or GIT_SHA_RE.fullmatch(expected_sha) is None
        or set(expected_sha) == {"0"}
    ):
        raise UsageError
    return expected_sha


def _lexical_git_path(base: Path, raw: str) -> Path:
    if (
        not raw
        or "\x00" in raw
        or any(ord(character) < 32 for character in raw)
    ):
        raise RepositoryBindingError
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = base / candidate
    normalized = Path(os.path.normpath(os.fspath(candidate)))
    if not normalized.is_absolute() or any(
        part in {"", ".", ".."} for part in normalized.parts[1:]
    ):
        raise RepositoryBindingError
    return normalized


def _read_git_pointer(path: Path, *, prefix: bytes | None = None) -> str:
    record = catalog._read_stable_file(
        path,
        maximum_size=4_096,
        error_type=RepositoryBindingError,
    )
    content = record.content
    if prefix is not None:
        if not content.startswith(prefix):
            raise RepositoryBindingError
        content = content[len(prefix) :]
    try:
        value = content.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise RepositoryBindingError from exc
    if not value or "\n" in value or "\r" in value:
        raise RepositoryBindingError
    return value


def _repository_object_directory(repository_root: Path) -> tuple[Path, int]:
    """Resolve only Git administrative pointers, never repository config."""

    dot_git = repository_root / ".git"
    try:
        dot_git_info = os.lstat(dot_git)
    except OSError as exc:
        raise RepositoryBindingError from exc
    if stat.S_ISDIR(dot_git_info.st_mode):
        git_dir = dot_git
    elif stat.S_ISREG(dot_git_info.st_mode) and dot_git_info.st_nlink == 1:
        git_dir = _lexical_git_path(
            repository_root,
            _read_git_pointer(dot_git, prefix=b"gitdir:"),
        )
    else:
        raise RepositoryBindingError

    opened_git_dir = catalog._open_directory(git_dir, RepositoryBindingError)
    os.close(opened_git_dir.descriptor)
    commondir_path = git_dir / "commondir"
    try:
        commondir_info = os.lstat(commondir_path)
    except FileNotFoundError:
        common_dir = git_dir
    except OSError as exc:
        raise RepositoryBindingError from exc
    else:
        if not stat.S_ISREG(commondir_info.st_mode) or commondir_info.st_nlink != 1:
            raise RepositoryBindingError
        common_dir = _lexical_git_path(
            git_dir,
            _read_git_pointer(commondir_path),
        )

    objects = common_dir / "objects"
    opened_objects = catalog._open_directory(objects, RepositoryBindingError)
    object_fd = opened_objects.descriptor
    try:
        _reject_object_alternates(object_fd)
    except Exception:
        os.close(object_fd)
        raise
    return objects, object_fd


def _reject_object_alternates(object_fd: int) -> None:
    try:
        info_fd = os.open("info", catalog._directory_flags(), dir_fd=object_fd)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RepositoryBindingError from exc
    try:
        for basename in ("alternates", "http-alternates"):
            try:
                os.stat(basename, dir_fd=info_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise RepositoryBindingError from exc
            raise RepositoryBindingError
    finally:
        os.close(info_fd)


def _write_private_control_file(directory_fd: int, name: str, content: bytes) -> None:
    required = ("O_CLOEXEC", "O_NOFOLLOW")
    if any(not hasattr(os, item) for item in required):
        raise RepositoryBindingError
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    for item in required:
        flags |= getattr(os, item)
    descriptor: int | None = None
    try:
        descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
        _write_all(descriptor, content)
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or info.st_size != len(content)
        ):
            raise RepositoryBindingError
    except AuthoringIoError as exc:
        raise RepositoryBindingError from exc
    except (OSError, ValueError) as exc:
        raise RepositoryBindingError from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


@dataclass
class _SanitizedGitControlPlane:
    repository_root: Path
    git_dir: Path
    root: Path
    root_identity: object
    object_fd: int
    object_format: str
    _closed: bool = False

    @classmethod
    def create(
        cls, *, repository_root: Path, expected_sha: str
    ) -> "_SanitizedGitControlPlane":
        object_format = "sha1" if len(expected_sha) == 40 else "sha256"
        _objects_path, object_fd = _repository_object_directory(repository_root)
        root: Path | None = None
        root_identity: object | None = None
        root_fd: int | None = None
        git_dir_fd: int | None = None
        try:
            root, root_identity, root_fd = trusted_snapshot._create_private_root()
            os.mkdir("git-control", 0o700, dir_fd=root_fd)
            git_dir = root / "git-control"
            git_dir_fd = os.open(
                "git-control", catalog._directory_flags(), dir_fd=root_fd
            )
            for directory in ("objects", "refs", "info"):
                os.mkdir(directory, 0o700, dir_fd=git_dir_fd)
            config = (
                b"[core]\n\trepositoryformatversion = "
                + (b"0" if object_format == "sha1" else b"1")
                + b"\n\tbare = false\n"
            )
            if object_format == "sha256":
                config += b"[extensions]\n\tobjectformat = sha256\n"
            _write_private_control_file(git_dir_fd, "config", config)
            _write_private_control_file(
                git_dir_fd, "HEAD", b"ref: refs/heads/unborn\n"
            )
            os.fsync(git_dir_fd)
            os.close(git_dir_fd)
            git_dir_fd = None
            os.close(root_fd)
            root_fd = None
            return cls(
                repository_root=repository_root,
                git_dir=git_dir,
                root=root,
                root_identity=root_identity,
                object_fd=object_fd,
                object_format=object_format,
            )
        except Exception:
            if git_dir_fd is not None:
                os.close(git_dir_fd)
            if root_fd is not None:
                os.close(root_fd)
            os.close(object_fd)
            if root is not None and root_identity is not None:
                trusted_snapshot._cleanup_created_root(root, root_identity)
            raise

    def _environment(self) -> dict[str, str]:
        return {
            "GIT_ALLOW_PROTOCOL": "",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": "",
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_COMMON_DIR": str(self.git_dir),
            "GIT_CONFIG_COUNT": "0",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_DIR": str(self.git_dir),
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OBJECT_DIRECTORY": f"/proc/self/fd/{self.object_fd}",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PROTOCOL_FROM_USER": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_WORK_TREE": str(self.repository_root),
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": os.defpath,
        }

    def _command(self, args: tuple[str, ...]) -> list[str]:
        return [
            "git",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "protocol.allow=never",
            "--git-dir",
            str(self.git_dir),
            "--work-tree",
            str(self.repository_root),
            *args,
        ]

    def control(
        self, repository_root: Path, args: tuple[str, ...], maximum: int
    ) -> bytes:
        if (
            self._closed
            or repository_root != self.repository_root
            or not trusted_snapshot._git_control_args_allowed(args)
            or type(maximum) is not int
            or maximum < 1
            or maximum > trusted_snapshot.MAX_MANIFEST_BYTES
        ):
            raise trusted_snapshot.GitEvidenceError
        _reject_object_alternates(self.object_fd)
        try:
            completed = subprocess.run(
                self._command(args),
                check=False,
                cwd=self.repository_root,
                env=self._environment(),
                pass_fds=(self.object_fd,),
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=trusted_snapshot.GIT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise trusted_snapshot.GitEvidenceError from exc
        _reject_object_alternates(self.object_fd)
        if completed.returncode != 0 or len(completed.stdout) > maximum:
            raise trusted_snapshot.GitEvidenceError
        if args[:6] == (
            "ls-tree",
            "-r",
            "-t",
            "-l",
            "-z",
            "--full-tree",
        ):
            _reject_protected_snapshot_manifest(completed.stdout)
        return completed.stdout

    def archive(
        self, repository_root: Path, git_sha: str, archive_fd: int
    ) -> None:
        if (
            self._closed
            or repository_root != self.repository_root
            or git_sha != _validated_repository_sha(git_sha)
            or type(archive_fd) is not int
            or archive_fd < 3
        ):
            raise trusted_snapshot.ArchiveError
        _reject_object_alternates(self.object_fd)
        command = self._command(
            ("-c", "tar.umask=0022", "archive", "--format=tar", git_sha)
        )
        try:
            completed = subprocess.run(
                command,
                check=False,
                cwd=self.repository_root,
                env=self._environment(),
                pass_fds=(self.object_fd,),
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=archive_fd,
                stderr=subprocess.DEVNULL,
                timeout=trusted_snapshot.GIT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise trusted_snapshot.ArchiveError from exc
        _reject_object_alternates(self.object_fd)
        if completed.returncode != 0:
            raise trusted_snapshot.ArchiveError

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        os.close(self.object_fd)
        trusted_snapshot._cleanup_created_root(self.root, self.root_identity)


def _create_repository_snapshot(*, repository_root: Path, git_sha: str) -> object:
    control_plane: _SanitizedGitControlPlane | None = None
    snapshot: object | None = None
    try:
        control_plane = _SanitizedGitControlPlane.create(
            repository_root=repository_root,
            expected_sha=git_sha,
        )
        snapshot = trusted_snapshot.create_trusted_repository_snapshot(
            repository_root=repository_root,
            git_sha=git_sha,
            git_control=control_plane.control,
            archive_writer=control_plane.archive,
        )
        return snapshot
    except Exception:
        if snapshot is not None:
            snapshot.cleanup()
        raise
    finally:
        if control_plane is not None:
            control_plane.close()


def _snapshot_contract_file(
    repository: Path, relative_path: str, *, maximum_size: int
) -> bytes:
    relative = Path(relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise RepositoryBindingError
    record = catalog._read_stable_file(
        repository.joinpath(*relative.parts),
        maximum_size=maximum_size,
        error_type=RepositoryBindingError,
    )
    return record.content


def _repository_contract(
    expected_sha: str,
) -> tuple[bytes, bytes, bytes, bytes]:
    """Authenticate one exact commit and read its contract from a private tree.

    Git configuration, includes, grafts, replace refs and alternate object
    locations are deliberately not evidence.  The pinned snapshot primitive
    authenticates the raw commit, tree and every blob by object bytes before
    this function consumes any versioned contract file.
    """

    supplied = _validated_repository_sha(expected_sha)
    snapshot: object | None = None
    try:
        snapshot = _create_repository_snapshot(
            repository_root=REPO_ROOT,
            git_sha=supplied,
        )
        if snapshot.git_sha != supplied:
            raise RepositoryBindingError
        repository = snapshot.repository
        head = _snapshot_contract_file(
            repository,
            HEAD_RELATIVE_PATH,
            maximum_size=catalog.MAX_JSON_BYTES,
        )
        schema = _snapshot_contract_file(
            repository,
            SCHEMA_RELATIVE_PATH,
            maximum_size=catalog.MAX_JSON_BYTES,
        )
        authoring = _snapshot_contract_file(
            repository,
            AUTHORING_RELATIVE_PATH,
            maximum_size=catalog.MAX_MIGRATION_BYTES,
        )
        verifier = _snapshot_contract_file(
            repository,
            VERIFIER_RELATIVE_PATH,
            maximum_size=catalog.MAX_MIGRATION_BYTES,
        )
        snapshot_primitive = _snapshot_contract_file(
            repository,
            TRUSTED_SNAPSHOT_RELATIVE_PATH,
            maximum_size=catalog.MAX_MIGRATION_BYTES,
        )
        if (
            hashlib.sha256(verifier).hexdigest() != CATALOG_VERIFIER_SHA256
            or hashlib.sha256(snapshot_primitive).hexdigest()
            != TRUSTED_SNAPSHOT_SHA256
        ):
            raise RepositoryBindingError
        return head, schema, authoring, verifier
    except UsageError:
        raise
    except RepositoryBindingError:
        raise
    except Exception as exc:
        raise RepositoryBindingError from exc
    finally:
        if snapshot is not None:
            try:
                snapshot.cleanup()
            except Exception as exc:
                raise RepositoryBindingError from exc


def _state(
    *, expected_sha: str, require_exact_catalog: bool
) -> CatalogState:
    git_head, git_schema, git_authoring, git_verifier = _repository_contract(
        expected_sha
    )
    head_record = catalog._read_stable_file(
        HEAD_PATH, error_type=AuthoringIoError
    )
    schema_record = catalog._read_stable_file(
        SCHEMA_PATH, error_type=AuthoringIoError
    )
    authoring_record = catalog._read_stable_file(
        Path(__file__).absolute(),
        maximum_size=catalog.MAX_MIGRATION_BYTES,
        error_type=AuthoringIoError,
    )
    verifier_record = catalog._read_stable_file(
        VERIFIER_PATH,
        maximum_size=catalog.MAX_MIGRATION_BYTES,
        error_type=AuthoringIoError,
    )
    if (
        head_record.content != git_head
        or schema_record.content != git_schema
        or authoring_record.content != git_authoring
        or verifier_record.content != git_verifier
    ):
        raise RepositoryBindingError
    head = catalog._decode_json(head_record.content)
    schema = catalog._decode_json(schema_record.content)
    catalog._require_exact(schema, catalog._expected_schema())
    represented = catalog.validate_head(head, _approved_snapshot=True)
    scanned = catalog._scan_catalog(MIGRATIONS_DIR)
    if require_exact_catalog and not catalog._exact_json(scanned, represented):
        raise AuthoringError
    if not catalog._stable_file_unchanged(
        catalog._read_stable_file(HEAD_PATH, error_type=AuthoringIoError),
        head_record,
    ):
        raise AuthoringIoError
    if not catalog._stable_file_unchanged(
        catalog._read_stable_file(SCHEMA_PATH, error_type=AuthoringIoError),
        schema_record,
    ):
        raise AuthoringIoError
    return CatalogState(
        head=head,
        head_record=head_record,
        schema_record=schema_record,
        authoring_record=authoring_record,
        verifier_record=verifier_record,
        represented=represented,
        scanned=scanned,
    )


def _require_contract_unchanged(
    state: CatalogState, expected_sha: str
) -> None:
    git_head, git_schema, git_authoring, git_verifier = _repository_contract(
        expected_sha
    )
    current_head = catalog._read_stable_file(
        HEAD_PATH, error_type=AuthoringIoError
    )
    current_schema = catalog._read_stable_file(
        SCHEMA_PATH, error_type=AuthoringIoError
    )
    current_authoring = catalog._read_stable_file(
        Path(__file__).absolute(),
        maximum_size=catalog.MAX_MIGRATION_BYTES,
        error_type=AuthoringIoError,
    )
    current_verifier = catalog._read_stable_file(
        VERIFIER_PATH,
        maximum_size=catalog.MAX_MIGRATION_BYTES,
        error_type=AuthoringIoError,
    )
    if (
        state.head_record.content != git_head
        or state.schema_record.content != git_schema
        or state.authoring_record.content != git_authoring
        or state.verifier_record.content != git_verifier
        or not catalog._stable_file_unchanged(
            current_head, state.head_record
        )
        or not catalog._stable_file_unchanged(
            current_schema, state.schema_record
        )
        or not catalog._stable_file_unchanged(
            current_authoring, state.authoring_record
        )
        or not catalog._stable_file_unchanged(
            current_verifier, state.verifier_record
        )
    ):
        raise RepositoryBindingError


def _draft_intent(basename: str, expected_sha: str) -> dict[str, object]:
    return {
        "affected_relations": ["TODO"],
        "artifact_id": INTENT_ARTIFACT_ID,
        "base_repository_sha": expected_sha,
        "cross_tenant_test_nodeids": ["TODO"],
        "decision_refs": ["TODO"],
        "global_justification": "TODO",
        "migration_basename": basename,
        "next_stage_authorized": False,
        "operational_authorization": False,
        "pg17_test_nodeids": ["TODO"],
        "recovery": {"kind": "TODO", "reference": "TODO"},
        "scope": "TODO",
        "tenant_controls": {
            "acl_review": "TODO",
            "enable_rls": False,
            "force_rls": False,
            "igreja_id_column": "TODO",
            "policy_context": "TODO",
        },
    }


def _draft_bytes(basename: str, expected_sha: str) -> bytes:
    header = "-- " + "=" * 76 + "\n"
    intent = json.dumps(
        _draft_intent(basename, expected_sha),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    text = (
        INTENT_PREFIX
        + intent
        + "\n"
        + header
        + f"-- PastorAI migration candidate: {basename}\n"
        + "-- MIGRATION_DRAFT_INCOMPLETE\n"
        + "-- Complete the exact JSON intent above; do not add keys.\n"
        + "-- This v1 authoring boundary accepts TENANT scope only.\n"
        + "-- TENANT requires igreja_id, ENABLE/FORCE RLS, explicit ACL review,\n"
        + "-- a restrictive FOR ALL TO PUBLIC app.tenant_igreja_id barrier and\n"
        + "-- cross-tenant test nodeids.\n"
        + "-- List every affected public relation explicitly and conservatively.\n"
        + "-- Decision/recovery refs must be canonical; declared tests must be\n"
        + "-- rls_integration tests executed by the disposable PostgreSQL job.\n"
        + "--\n"
        + f"-- {OPERATIONAL_BLOCK}\n"
        + f"-- {NEXT_STAGE_BLOCK}\n"
        + "-- This file is source-only. Never apply it manually, with db push,\n"
        + "-- a SQL editor, or any runner before its separate operational gate.\n"
        + "-- Replace every structured placeholder, remove the incomplete marker,\n"
        + "-- add reviewed SQL terminated by a semicolon, then run:\n"
        + "-- python scripts/new_migration.py prepare-head "
        + f"--expected-repository-sha {expected_sha} {basename}\n"
        + "-- ALTER TYPE ... ADD VALUE has a special transaction contract; "
        + "see README.\n"
        + header
        + "\n"
    )
    return text.encode("ascii")


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        try:
            written = os.write(descriptor, content[offset:])
        except OSError as exc:
            raise AuthoringIoError from exc
        if written <= 0:
            raise AuthoringIoError
        offset += written


def _create_file_exclusive(directory: Path, basename: str, content: bytes) -> None:
    opened = catalog._open_directory(directory, AuthoringIoError)
    descriptor: int | None = None
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        for required in ("O_NOFOLLOW", "O_CLOEXEC"):
            if not hasattr(os, required):
                raise AuthoringIoError
            flags |= getattr(os, required)
        try:
            descriptor = os.open(
                basename, flags, 0o600, dir_fd=opened.descriptor
            )
        except FileExistsError as exc:
            raise DraftCollisionError from exc
        except (OSError, ValueError) as exc:
            raise AuthoringIoError from exc
        _write_all(descriptor, content)
        os.fsync(descriptor)
        snapshot = catalog.FileSnapshot.from_stat(os.fstat(descriptor))
        named = catalog.FileSnapshot.from_stat(
            os.stat(basename, dir_fd=opened.descriptor, follow_symlinks=False)
        )
        if (
            snapshot != named
            or not stat.S_ISREG(snapshot.mode)
            or snapshot.links != 1
            or snapshot.size != len(content)
            or stat.S_IMODE(snapshot.mode) != 0o600
        ):
            raise AuthoringIoError
        os.fsync(opened.descriptor)
        catalog._verify_directory_chain(
            directory, opened.chain, AuthoringIoError
        )
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
        # Fail closed: a partial inode created by this attempt is deliberately
        # preserved for explicit inspection. Removing by pathname after a
        # failure could delete a concurrently substituted object.
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(opened.descriptor)


def _compact_entry_json(value: dict[str, object]) -> str:
    value = copy.deepcopy(value)
    replacements: list[tuple[str, dict[str, object]]] = []
    entry_lists: list[list[object]] = []
    historical = value.get("historical_prefix")
    if type(historical) is dict and type(historical.get("entries")) is list:
        entry_lists.append(historical["entries"])
    batches = value.get("append_only_batches")
    if type(batches) is list:
        for batch in batches:
            if type(batch) is dict and type(batch.get("entries")) is list:
                entry_lists.append(batch["entries"])
    for entries in entry_lists:
        for index, entry in enumerate(entries):
            if type(entry) is not dict:
                raise AuthoringError
            sentinel = f"__PASTORAI_CATALOG_ENTRY_{len(replacements):04d}__"
            replacements.append((sentinel, entry))
            entries[index] = sentinel
    rendered = json.dumps(value, ensure_ascii=True, indent=2)
    for sentinel, entry in replacements:
        encoded = json.dumps(entry, ensure_ascii=True, separators=(", ", ": "))
        marker = json.dumps(sentinel)
        if rendered.count(marker) != 1:
            raise AuthoringError
        rendered = rendered.replace(marker, encoded)
    return rendered


def _serialize_head(
    head: dict[str, object], prior_content: bytes
) -> bytes:
    """Preserve historical bytes and render only the mutable head suffix."""

    marker = b'  "append_only_batches":'
    if prior_content.count(marker) != 1:
        raise AuthoringError
    prefix = prior_content[: prior_content.index(marker)]
    mutable_keys = (
        "append_only_batches",
        "current_head",
        "previous_approved_head_sha256",
        "operational_authorization",
        "next_stage_authorized",
    )
    if any(key not in head for key in mutable_keys):
        raise AuthoringError
    mutable = {key: head[key] for key in mutable_keys}
    rendered = _compact_entry_json(mutable)
    if not rendered.startswith("{\n") or not rendered.endswith("}"):
        raise AuthoringError
    return prefix + (rendered[2:] + "\n").encode("ascii")


def _non_placeholder(value: object, *, maximum: int = 512) -> bool:
    return (
        type(value) is str
        and bool(value.strip())
        and len(value) <= maximum
        and "TODO" not in value.upper()
        and not any(unicodedata.category(char).startswith("C") for char in value)
    )


def _is_protected_repository_path(relative: Path) -> bool:
    """Classify protected paths without touching the filesystem."""

    parts = tuple(part.casefold() for part in relative.parts)
    if not parts:
        return True
    basename = parts[-1]
    suffix = Path(basename).suffix.casefold()
    if any(part in PROTECTED_DIRECTORY_NAMES for part in parts[:-1]):
        return True
    if basename.startswith(".env"):
        return True
    if suffix in {".key", ".pem", ".dump", ".backup", ".bak"}:
        return True
    if suffix in PROTECTED_MEDIA_SUFFIXES:
        return True
    if basename.startswith(("id_rsa", "id_ed25519")):
        return True
    if len(parts) >= 3 and parts[:2] == ("backend", "scripts"):
        if (
            basename.startswith("clerk_")
            or basename.startswith("target_users")
            or basename == "migrate_clerk_production.py"
        ):
            return True
    return False


def _reject_protected_snapshot_manifest(content: bytes) -> None:
    """Reject categorically sensitive tracked paths before archive creation.

    Public product imagery and explicitly sanitized design references remain
    valid tracked source.  Dedicated backup, dump, export, media and secrets
    directories, secret-like files and protected operational scripts do not.
    """

    if type(content) is not bytes or not content.endswith(b"\x00"):
        raise trusted_snapshot.GitEvidenceError
    records = content[:-1].split(b"\x00")
    if not records or len(records) > trusted_snapshot.MAX_ENTRIES:
        raise trusted_snapshot.GitEvidenceError
    for record in records:
        try:
            _metadata, raw_path = record.split(b"\t", 1)
            value = raw_path.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError) as exc:
            raise trusted_snapshot.GitEvidenceError from exc
        relative = Path(value)
        if (
            relative.is_absolute()
            or not relative.parts
            or str(relative.as_posix()) != value
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise trusted_snapshot.GitEvidenceError
        parts = tuple(part.casefold() for part in relative.parts)
        basename = parts[-1]
        suffix = Path(basename).suffix.casefold()
        protected_directory = any(
            part in PROTECTED_DIRECTORY_NAMES for part in parts[:-1]
        )
        protected_file = (
            (basename.startswith(".env") and not basename.endswith(".example"))
            or suffix in {".key", ".pem", ".dump", ".backup", ".bak"}
            or basename.startswith(("id_rsa", "id_ed25519"))
        )
        protected_script = (
            len(parts) >= 3
            and parts[:2] == ("backend", "scripts")
            and (
                basename.startswith("clerk_")
                or basename.startswith("target_users")
                or basename == "migrate_clerk_production.py"
            )
        )
        if protected_directory or protected_file or protected_script:
            raise trusted_snapshot.GitEvidenceError


def _stable_repository_reference(
    value: object, *, reference_kind: str = "decision"
) -> bool:
    if not _non_placeholder(value):
        return False
    relative = Path(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or _is_protected_repository_path(relative)
    ):
        return False
    if reference_kind == "decision":
        allowed = DECISION_REFERENCE_RE.fullmatch(value) is not None
    elif reference_kind == "recovery":
        allowed = RECOVERY_REFERENCE_RE.fullmatch(value) is not None
    else:
        return False
    if not allowed:
        return False
    path = REPO_ROOT.joinpath(*relative.parts)
    try:
        record = catalog._read_stable_file(
            path,
            maximum_size=catalog.MAX_MIGRATION_BYTES,
            error_type=AuthoringIoError,
        )
    except (AuthoringError, catalog.VerificationError):
        return False
    return record.file.links == 1 and stat.S_ISREG(record.file.mode)


def _ast_qualified_name(node: ast.AST) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        parent = _ast_qualified_name(node.value)
        return None if parent is None else (*parent, node.attr)
    return None


def _marker_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Call):
        return _marker_names(node.func)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        markers: set[str] = set()
        for item in node.elts:
            markers.update(_marker_names(item))
        return markers
    qualified = _ast_qualified_name(node)
    if qualified is not None and qualified[:2] == ("pytest", "mark"):
        if len(qualified) == 3:
            return {qualified[2]}
    return set()


def _module_pytest_markers(tree: ast.Module) -> set[str] | None:
    assignments: list[ast.AST] = []
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in statement.targets
        ):
            assignments.append(statement.value)
        elif isinstance(statement, ast.AnnAssign) and (
            isinstance(statement.target, ast.Name)
            and statement.target.id == "pytestmark"
        ):
            assignments.append(statement.value)
    if len(assignments) > 1 or any(value is None for value in assignments):
        return None
    return set() if not assignments else _marker_names(assignments[0])


def _has_runtime_skip_or_xfail(function: ast.AST) -> bool:
    forbidden = {"skip", "skipif", "xfail"}
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            qualified = _ast_qualified_name(node.func)
            if qualified in {("pytest", "skip"), ("pytest", "xfail")}:
                return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _marker_names_from_decorators(node.decorator_list) & forbidden:
                return True
    return False


def _marker_names_from_decorators(decorators: list[ast.expr]) -> set[str]:
    markers: set[str] = set()
    for decorator in decorators:
        markers.update(_marker_names(decorator))
    return markers


def _valid_test_nodeid(value: object) -> bool:
    if not _non_placeholder(value):
        return False
    match = TEST_NODEID_RE.fullmatch(value)
    if match is None:
        return False
    relative_path, function_name = match.groups()
    path = REPO_ROOT.joinpath(*Path(relative_path).parts)
    try:
        record = catalog._read_stable_file(
            path,
            maximum_size=catalog.MAX_MIGRATION_BYTES,
            error_type=AuthoringIoError,
        )
        tree = ast.parse(record.content.decode("utf-8", errors="strict"))
    except (
        AuthoringError,
        catalog.VerificationError,
        UnicodeDecodeError,
        SyntaxError,
    ):
        return False
    module_markers = _module_pytest_markers(tree)
    if module_markers is None or module_markers & {"skip", "skipif", "xfail"}:
        return False
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    if len(functions) != 1:
        return False
    function = functions[0]
    function_markers = _marker_names_from_decorators(function.decorator_list)
    if "rls_integration" not in module_markers | function_markers:
        return False
    if function_markers & {"skip", "skipif", "xfail"}:
        return False
    return not _has_runtime_skip_or_xfail(function)


def _parse_intent(
    content: bytes, *, basename: str, expected_sha: str
) -> dict[str, object]:
    if b"\x00" in content or content.count(INTENT_PREFIX.encode("ascii")) != 1:
        raise DraftIncompleteError
    first_line, separator, _body = content.partition(b"\n")
    prefix = INTENT_PREFIX.encode("ascii")
    if not separator or not first_line.startswith(prefix):
        raise DraftIncompleteError
    try:
        intent = catalog._decode_json(first_line[len(prefix):])
    except catalog.VerificationError as exc:
        raise DraftIncompleteError from exc
    if type(intent) is not dict or set(intent) != INTENT_KEYS:
        raise DraftIncompleteError
    if (
        intent["artifact_id"] != INTENT_ARTIFACT_ID
        or intent["base_repository_sha"] != expected_sha
        or intent["migration_basename"] != basename
        or intent["operational_authorization"] is not False
        or intent["next_stage_authorized"] is not False
    ):
        raise DraftIncompleteError

    decision_refs = intent["decision_refs"]
    pg17_nodeids = intent["pg17_test_nodeids"]
    cross_tenant_nodeids = intent["cross_tenant_test_nodeids"]
    affected_relations = intent["affected_relations"]
    if (
        type(decision_refs) is not list
        or not 1 <= len(decision_refs) <= 16
        or not all(
            _stable_repository_reference(item, reference_kind="decision")
            for item in decision_refs
        )
        or type(pg17_nodeids) is not list
        or not 1 <= len(pg17_nodeids) <= 32
        or len(pg17_nodeids) != len(set(pg17_nodeids))
        or not all(_valid_test_nodeid(item) for item in pg17_nodeids)
        or type(cross_tenant_nodeids) is not list
        or len(cross_tenant_nodeids) != len(set(cross_tenant_nodeids))
        or not all(_valid_test_nodeid(item) for item in cross_tenant_nodeids)
        or not set(cross_tenant_nodeids).issubset(set(pg17_nodeids))
        or type(affected_relations) is not list
        or len(affected_relations) > 32
        or affected_relations != sorted(affected_relations)
        or len(affected_relations) != len(set(affected_relations))
        or not all(
            type(item) is str and AFFECTED_RELATION_RE.fullmatch(item)
            for item in affected_relations
        )
    ):
        raise DraftIncompleteError

    recovery = intent["recovery"]
    if (
        type(recovery) is not dict
        or set(recovery) != RECOVERY_KEYS
        or recovery["kind"] not in {"REVERSIBLE", "FORWARD_COMPENSATION"}
        or not _stable_repository_reference(
            recovery["reference"], reference_kind="recovery"
        )
    ):
        raise DraftIncompleteError

    scope = intent["scope"]
    tenant = intent["tenant_controls"]
    justification = intent["global_justification"]
    if scope == "TENANT":
        expected_tenant_controls = {
            "acl_review": "EXPLICIT_GRANTS_AND_REVOKES",
            "enable_rls": True,
            "force_rls": True,
            "igreja_id_column": "igreja_id",
            "policy_context": "app.tenant_igreja_id",
        }
        if (
            type(tenant) is not dict
            or set(tenant) != TENANT_CONTROL_KEYS
            or not catalog._exact_json(tenant, expected_tenant_controls)
            or justification is not None
            or not cross_tenant_nodeids
            or not affected_relations
        ):
            raise DraftIncompleteError
    else:
        raise DraftIncompleteError
    return intent


def _validate_candidate_intent_for_replay(
    record: object, *, basename: str
) -> dict[str, object]:
    """Validate an already-versioned append without weakening its base SHA."""

    content = record.content
    first_line, separator, _body = content.partition(b"\n")
    prefix = INTENT_PREFIX.encode("ascii")
    if not separator or not first_line.startswith(prefix):
        raise DraftIncompleteError
    try:
        untrusted = catalog._decode_json(first_line[len(prefix):])
    except catalog.VerificationError as exc:
        raise DraftIncompleteError from exc
    if type(untrusted) is not dict:
        raise DraftIncompleteError
    expected_sha = untrusted.get("base_repository_sha")
    if (
        type(expected_sha) is not str
        or GIT_SHA_RE.fullmatch(expected_sha) is None
        or set(expected_sha) == {"0"}
    ):
        raise DraftIncompleteError
    return _validate_candidate_intent(
        record,
        basename=basename,
        expected_sha=expected_sha,
    )


def _has_terminated_sql_statement(text: str) -> bool:
    """Recognize a semicolon outside PostgreSQL comments and quotations."""

    index = 0
    block_depth = 0
    quote: str | None = None
    dollar_tag: str | None = None
    token_seen = False
    while index < len(text):
        if block_depth:
            if text.startswith("/*", index):
                block_depth += 1
                index += 2
            elif text.startswith("*/", index):
                block_depth -= 1
                index += 2
            else:
                index += 1
            continue
        if dollar_tag is not None:
            if text.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
            else:
                index += 1
            continue
        if quote is not None:
            if text[index] == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                else:
                    quote = None
                    index += 1
            elif quote == "'" and text[index] == "\\":
                index += 2
            else:
                index += 1
            continue
        if text.startswith("--", index):
            newline = text.find("\n", index + 2)
            index = len(text) if newline < 0 else newline + 1
            continue
        if text.startswith("/*", index):
            block_depth = 1
            index += 2
            continue
        if text[index] in {"'", '"'}:
            quote = text[index]
            token_seen = True
            index += 1
            continue
        if text[index] == "$":
            match = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", text[index:])
            if match is not None:
                dollar_tag = match.group(0)
                token_seen = True
                index += len(dollar_tag)
                continue
        if text[index] == ";":
            if token_seen:
                return True
            index += 1
            continue
        if not text[index].isspace():
            token_seen = True
        index += 1
    return False


def _validate_candidate_intent(
    record: object, *, basename: str, expected_sha: str
) -> dict[str, object]:
    content = record.content
    required = (
        OPERATIONAL_BLOCK.encode("ascii"),
        NEXT_STAGE_BLOCK.encode("ascii"),
    )
    if (
        any(content.count(marker) != 1 for marker in required)
        or b"MIGRATION_DRAFT_INCOMPLETE" in content
    ):
        raise DraftIncompleteError
    intent = _parse_intent(
        content, basename=basename, expected_sha=expected_sha
    )
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise DraftIncompleteError from exc
    if not _has_terminated_sql_statement(text.split("\n", 1)[1]):
        raise DraftIncompleteError
    return intent


def _new_head(
    state: CatalogState, candidate: dict[str, object]
) -> tuple[dict[str, object], object]:
    prior = catalog.ApprovedPriorHead(
        content_sha256=hashlib.sha256(state.head_record.content).hexdigest(),
        head=copy.deepcopy(state.head),
    )
    head = copy.deepcopy(state.head)
    batches = head["append_only_batches"]
    sequence = len(batches) + 1
    previous_digest = head["current_head"]["digest_sha256"]
    reconstructed = copy.deepcopy(state.represented)
    reconstructed.append(copy.deepcopy(candidate))
    resulting_digest = catalog._catalog_digest(reconstructed)
    batches.append(
        {
            "batch_id": f"migration-catalog-append-{sequence:04d}",
            "entries": [copy.deepcopy(candidate)],
            "previous_catalog_digest_sha256": previous_digest,
            "resulting_catalog_digest_sha256": resulting_digest,
            "sequence": sequence,
        }
    )
    head["current_head"] = {
        "digest_sha256": resulting_digest,
        "last_basename": candidate["name"],
        "migration_count": len(reconstructed),
    }
    head["previous_approved_head_sha256"] = prior.content_sha256
    catalog.validate_head(
        head,
        scanned_catalog=state.scanned,
        approved_prior=prior,
    )
    return head, prior


def create_draft(description: str, *, expected_sha: str) -> str:
    slug = slugify(description)
    with _AuthoringLock():
        state = _state(
            expected_sha=expected_sha, require_exact_catalog=True
        )
        timestamp = _utc_now().astimezone(dt.timezone.utc).strftime(
            "%Y%m%d_%H%M%S"
        )
        basename = f"{timestamp}_{slug}.sql"
        if (
            len(basename) > 255
            or not basename.isascii()
            or not catalog.MIGRATION_BASENAME_RE.fullmatch(basename)
            or basename <= state.head["current_head"]["last_basename"]
        ):
            raise AuthoringError
        _create_file_exclusive(
            MIGRATIONS_DIR, basename, _draft_bytes(basename, expected_sha)
        )
        scanned = catalog._scan_catalog(MIGRATIONS_DIR)
        expected_prefix = state.represented
        if (
            len(scanned) != len(expected_prefix) + 1
            or not catalog._exact_json(scanned[:-1], expected_prefix)
            or scanned[-1]["name"] != basename
        ):
            raise AuthoringIoError
        _require_contract_unchanged(state, expected_sha)
        return basename


def prepare_head(
    basename: str, *, expected_sha: str
) -> PreparedHeadCandidate:
    if (
        type(basename) is not str
        or not basename.isascii()
        or not catalog.MIGRATION_BASENAME_RE.fullmatch(basename)
    ):
        raise UsageError
    with _AuthoringLock():
        state = _state(
            expected_sha=expected_sha, require_exact_catalog=False
        )
        if (
            len(state.scanned) != len(state.represented) + 1
            or not catalog._exact_json(
                state.scanned[:-1], state.represented
            )
            or state.scanned[-1]["name"] != basename
            or basename <= state.head["current_head"]["last_basename"]
        ):
            raise AuthoringError
        candidate_record = catalog._read_stable_file(
            MIGRATIONS_DIR / basename,
            maximum_size=catalog.MAX_MIGRATION_BYTES,
            error_type=AuthoringIoError,
        )
        candidate = state.scanned[-1]
        if (
            hashlib.sha256(candidate_record.content).hexdigest()
            != candidate["sha256"]
            or candidate_record.file.size != candidate["size_bytes"]
        ):
            raise DraftIncompleteError
        _validate_candidate_intent(
            candidate_record,
            basename=basename,
            expected_sha=expected_sha,
        )
        new_head, prior = _new_head(state, candidate)
        serialized = _serialize_head(new_head, state.head_record.content)
        if not catalog._exact_json(catalog._decode_json(serialized), new_head):
            raise AuthoringError
        latest_candidate = catalog._read_stable_file(
            MIGRATIONS_DIR / basename,
            maximum_size=catalog.MAX_MIGRATION_BYTES,
            error_type=AuthoringIoError,
        )
        if not catalog._stable_file_unchanged(
            latest_candidate, candidate_record
        ):
            raise AuthoringIoError
        latest_scanned = catalog._scan_catalog(MIGRATIONS_DIR)
        if not catalog._exact_json(latest_scanned, state.scanned):
            raise AuthoringIoError
        _require_contract_unchanged(state, expected_sha)
        if not catalog._stable_file_unchanged(
            catalog._read_stable_file(
                HEAD_PATH, error_type=AuthoringIoError
            ),
            state.head_record,
        ):
            raise AuthoringIoError
        return PreparedHeadCandidate(
            batch_id=new_head["append_only_batches"][-1]["batch_id"],
            previous_approved_head_sha256=prior.content_sha256,
            content=serialized,
            content_sha256=hashlib.sha256(serialized).hexdigest(),
        )


def _usage() -> None:
    print(
        "usage: python scripts/new_migration.py draft "
        '--expected-repository-sha <sha> "short description"',
        file=sys.stderr,
    )
    print(
        "   or: python scripts/new_migration.py prepare-head "
        "--expected-repository-sha <sha> <basename.sql>",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if (
            len(args) != 4
            or args[1] != "--expected-repository-sha"
        ):
            raise UsageError
        if args[0] == "draft":
            basename = create_draft(args[3], expected_sha=args[2])
            print("RESULT=MIGRATION_DRAFT_CREATED")
            print(f"MIGRATION_BASENAME={basename}")
            print(f"EXPECTED_REPOSITORY_SHA={args[2]}")
            print("CATALOG_HEAD_UPDATE_REQUIRED=true")
        elif args[0] == "prepare-head":
            candidate = prepare_head(
                args[3], expected_sha=args[2]
            )
            print("RESULT=MIGRATION_APPEND_CANDIDATE_PREPARED")
            print(f"MIGRATION_BASENAME={args[3]}")
            print(f"EXPECTED_REPOSITORY_SHA={args[2]}")
            print(f"APPEND_BATCH_ID={candidate.batch_id}")
            print(
                "PREVIOUS_APPROVED_HEAD_SHA256="
                f"{candidate.previous_approved_head_sha256}"
            )
            print(f"HEAD_CANDIDATE_SHA256={candidate.content_sha256}")
            print("HEAD_CANDIDATE_ENCODING=BASE64")
            print(
                "HEAD_CANDIDATE_CONTENT_BASE64="
                + base64.b64encode(candidate.content).decode("ascii")
            )
            print("CATALOG_HEAD_UPDATE_PERFORMED=false")
        else:
            raise UsageError
    except UsageError as exc:
        _usage()
        print(f"RESULT=BLOCKED_MIGRATION_AUTHORING:{exc.reason}")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return exc.exit_code
    except AuthoringError as exc:
        print(f"RESULT=BLOCKED_MIGRATION_AUTHORING:{exc.reason}")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return exc.exit_code
    except catalog.VerificationError:
        print("RESULT=BLOCKED_MIGRATION_AUTHORING:CATALOG_INVALID")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return 4
    except Exception:
        print("RESULT=BLOCKED_MIGRATION_AUTHORING:INTERNAL_ERROR")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return 10
    print(OPERATIONAL_BLOCK)
    print(NEXT_STAGE_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
