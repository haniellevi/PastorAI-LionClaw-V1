#!/usr/bin/env python3
"""Verify the migration catalog in GitHub CI without external effects.

The current and prior commits are first authenticated and materialized as
private snapshots.  Validation then runs only against those snapshots.  Raw
commit bytes provide the ancestry proof, so replace refs, grafts, repository
configuration, config includes and alternate object locations never become
authority.  No fetch, network, database, migration runner, or process
environment secret is used by this script.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from types import ModuleType
from typing import Callable, Iterator


REPO_ROOT = Path(__file__).absolute().parents[2]
SCRIPT_PATH = Path(__file__).absolute()
SCRIPTS_DIR = SCRIPT_PATH.parent
HEAD_RELATIVE_PATH = (
    "docs/governance/migrations/migration-catalog-head-v1.json"
)
CATALOG_VERIFIER_RELATIVE_PATH = (
    "backend/scripts/verify_migration_catalog_head.py"
)
AUTHORING_RELATIVE_PATH = "backend/scripts/new_migration.py"
SOURCE_MANIFEST_VERIFIER_RELATIVE_PATH = (
    "backend/scripts/verify_migration_history_schema_expectation_manifest.py"
)
EPOCH_V3_VERIFIER_RELATIVE_PATH = (
    "backend/scripts/verify_migration_history_divergence_remediation_proposal_v3.py"
)
TRUSTED_SNAPSHOT_RELATIVE_PATH = (
    "backend/scripts/trusted_repository_snapshot.py"
)
CATALOG_VERIFIER_PATH = REPO_ROOT / CATALOG_VERIFIER_RELATIVE_PATH
TRUSTED_SNAPSHOT_PATH = REPO_ROOT / TRUSTED_SNAPSHOT_RELATIVE_PATH

MAX_BOOTSTRAP_MODULE_BYTES = 4_194_304
MAX_ANCESTRY_COMMITS = 20_000
GIT_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
PROTECTED_DIRECTORY_NAMES = frozenset(
    {
        "backup",
        "backups",
        "dump",
        "dumps",
        "export",
        "exports",
        "media",
        "secrets",
    }
)
CATALOG_VERIFIER_SHA256 = (
    "2fe1a93bf9c9116426683e7fd86c4f7b7c20753f7ce11a8282d9ca06087ac30d"
)
TRUSTED_SNAPSHOT_SHA256 = (
    "43dd9161cda2fc3cb7e1800a1b756f5595facbcc5c15274f282f6e763252d392"
)

VERIFIED_RESULT = "RESULT=MIGRATION_CATALOG_CI_VERIFIED_OFFLINE"
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
NEXT_STAGE_BLOCK = "NEXT_STAGE_AUTHORIZED=false"


def _reject_protected_snapshot_manifest(content: bytes) -> None:
    """Reject sensitive tracked paths before Git may archive their blobs."""

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
            or relative.as_posix() != value
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


def _stable_stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_nlink),
        int(value.st_uid),
        int(value.st_gid),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _read_python_source(
    path: Path, *, expected_sha256: str | None
) -> bytes:
    """Read once by descriptor; execute exactly these bytes, never the path."""

    if (
        not path.is_absolute()
        or any(component in {"", ".", ".."} for component in path.parts[1:])
        or (
            expected_sha256 is not None
            and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        )
    ):
        raise RuntimeError("verification module unavailable")
    required = ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required):
        raise RuntimeError("verification module unavailable")
    flags = os.O_RDONLY
    for name in required:
        flags |= getattr(os, name)
    try:
        descriptor = os.open(path, flags)
    except (OSError, ValueError) as exc:
        raise RuntimeError("verification module unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > MAX_BOOTSTRAP_MODULE_BYTES
        ):
            raise RuntimeError("verification module unavailable")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise RuntimeError("verification module unavailable")
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if _stable_stat_identity(before) != _stable_stat_identity(after):
            raise RuntimeError("verification module unavailable")
        if (
            expected_sha256 is not None
            and hashlib.sha256(content).hexdigest() != expected_sha256
        ):
            raise RuntimeError("verification module unavailable")
        return content
    except OSError as exc:
        raise RuntimeError("verification module unavailable") from exc
    finally:
        os.close(descriptor)


def _load_python_module(
    *,
    module_name: str,
    path: Path,
    expected_sha256: str | None = None,
) -> ModuleType:
    """Compile and execute only source bytes already authenticated in memory."""

    content = _read_python_source(path, expected_sha256=expected_sha256)
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


trusted_snapshot = _load_python_module(
    module_name="_pastorai_trusted_repository_snapshot_for_catalog_ci",
    path=TRUSTED_SNAPSHOT_PATH,
    expected_sha256=TRUSTED_SNAPSHOT_SHA256,
)

# This reference module exists for pure helpers and tests.  Its exact bytes are
# authenticated before execution.  Production verification loads another copy
# from the already authenticated current-commit snapshot.
catalog_head = _load_python_module(
    module_name="_pastorai_pinned_migration_catalog_head_reference_for_ci",
    path=CATALOG_VERIFIER_PATH,
    expected_sha256=CATALOG_VERIFIER_SHA256,
)


class CiVerificationError(RuntimeError):
    exit_code = 4
    reason = "CI_CONTRACT_INVALID"


class UsageError(CiVerificationError):
    exit_code = 2
    reason = "USAGE"


class GitEvidenceError(CiVerificationError):
    exit_code = 3
    reason = "LOCAL_GIT_EVIDENCE_INVALID"


class CurrentCatalogError(CiVerificationError):
    exit_code = 4
    reason = "CURRENT_CATALOG_INVALID"


class CandidateIntentError(CiVerificationError):
    exit_code = 6
    reason = "MIGRATION_INTENT_INVALID"


class HistoricalSourceManifestError(CiVerificationError):
    exit_code = 4
    reason = "HISTORICAL_SOURCE_MANIFEST_INVALID"


class HistoricalEpochError(CiVerificationError):
    exit_code = 4
    reason = "HISTORICAL_EPOCH_V3_INVALID"


@dataclass(frozen=True)
class CiEventContext:
    event_name: str
    current_sha: str
    prior_sha: str


@dataclass(frozen=True)
class CiVerificationResult:
    event_name: str
    migration_count: int
    catalog_digest_sha256: str
    prior_head_required: bool


@dataclass(frozen=True)
class VerificationModules:
    catalog_head: ModuleType
    migration_authoring: ModuleType
    source_manifest: ModuleType
    epoch_v3: ModuleType


SnapshotFactory = Callable[[str], object]
CommitParentReader = Callable[[str], tuple[str, ...]]
ModuleLoader = Callable[[Path], VerificationModules]
RepositoryWitness = Callable[[Path], str]


def _validated_sha(value: object) -> str:
    if (
        type(value) is not str
        or GIT_SHA_RE.fullmatch(value) is None
        or set(value) == {"0"}
    ):
        raise UsageError
    return value


def _event_context(
    *,
    event_name: object,
    current_sha: object,
    pull_request_base_sha: object,
    push_before_sha: object,
) -> CiEventContext:
    current = _validated_sha(current_sha)
    if event_name == "pull_request":
        if push_before_sha != "":
            raise UsageError
        prior = _validated_sha(pull_request_base_sha)
    elif event_name == "push":
        if pull_request_base_sha != "":
            raise UsageError
        prior = _validated_sha(push_before_sha)
    else:
        raise UsageError
    if prior == current or len(prior) != len(current):
        raise UsageError
    return CiEventContext(
        event_name=event_name,
        current_sha=current,
        prior_sha=prior,
    )


def _lexical_git_path(base: Path, raw: str) -> Path:
    if not raw or "\x00" in raw or any(ord(character) < 32 for character in raw):
        raise GitEvidenceError
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = base / candidate
    normalized = Path(os.path.normpath(os.fspath(candidate)))
    if not normalized.is_absolute() or any(
        part in {"", ".", ".."} for part in normalized.parts[1:]
    ):
        raise GitEvidenceError
    return normalized


def _read_git_pointer(path: Path, *, prefix: bytes | None = None) -> str:
    content = _read_python_source(path, expected_sha256=None)
    if len(content) > 4_096:
        raise GitEvidenceError
    if prefix is not None:
        if not content.startswith(prefix):
            raise GitEvidenceError
        content = content[len(prefix) :]
    try:
        value = content.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise GitEvidenceError from exc
    if not value or "\n" in value or "\r" in value:
        raise GitEvidenceError
    return value


def _reject_object_alternates(object_fd: int) -> None:
    try:
        info_fd = os.open(
            "info", catalog_head._directory_flags(), dir_fd=object_fd
        )
    except FileNotFoundError:
        return
    except OSError as exc:
        raise GitEvidenceError from exc
    try:
        for basename in ("alternates", "http-alternates"):
            try:
                os.stat(basename, dir_fd=info_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise GitEvidenceError from exc
            raise GitEvidenceError
    finally:
        os.close(info_fd)


def _repository_object_directory(repository_root: Path) -> int:
    dot_git = repository_root / ".git"
    try:
        dot_git_info = os.lstat(dot_git)
    except OSError as exc:
        raise GitEvidenceError from exc
    if stat.S_ISDIR(dot_git_info.st_mode):
        git_dir = dot_git
    elif stat.S_ISREG(dot_git_info.st_mode) and dot_git_info.st_nlink == 1:
        git_dir = _lexical_git_path(
            repository_root,
            _read_git_pointer(dot_git, prefix=b"gitdir:"),
        )
    else:
        raise GitEvidenceError
    opened_git_dir = catalog_head._open_directory(git_dir, GitEvidenceError)
    os.close(opened_git_dir.descriptor)

    commondir_path = git_dir / "commondir"
    try:
        commondir_info = os.lstat(commondir_path)
    except FileNotFoundError:
        common_dir = git_dir
    except OSError as exc:
        raise GitEvidenceError from exc
    else:
        if not stat.S_ISREG(commondir_info.st_mode) or commondir_info.st_nlink != 1:
            raise GitEvidenceError
        common_dir = _lexical_git_path(
            git_dir,
            _read_git_pointer(commondir_path),
        )
    opened_objects = catalog_head._open_directory(
        common_dir / "objects", GitEvidenceError
    )
    object_fd = opened_objects.descriptor
    try:
        _reject_object_alternates(object_fd)
    except Exception:
        os.close(object_fd)
        raise
    return object_fd


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        try:
            written = os.write(descriptor, content[offset:])
        except OSError as exc:
            raise GitEvidenceError from exc
        if written <= 0:
            raise GitEvidenceError
        offset += written


def _write_private_control_file(directory_fd: int, name: str, content: bytes) -> None:
    required = ("O_CLOEXEC", "O_NOFOLLOW")
    if any(not hasattr(os, item) for item in required):
        raise GitEvidenceError
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
            raise GitEvidenceError
    except (OSError, ValueError) as exc:
        raise GitEvidenceError from exc
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
        object_fd = _repository_object_directory(repository_root)
        root: Path | None = None
        root_identity: object | None = None
        root_fd: int | None = None
        git_dir_fd: int | None = None
        try:
            root, root_identity, root_fd = trusted_snapshot._create_private_root()
            os.mkdir("git-control", 0o700, dir_fd=root_fd)
            git_dir = root / "git-control"
            git_dir_fd = os.open(
                "git-control", catalog_head._directory_flags(), dir_fd=root_fd
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
            or GIT_SHA_RE.fullmatch(git_sha) is None
            or len(git_sha) != (40 if self.object_format == "sha1" else 64)
            or type(archive_fd) is not int
            or archive_fd < 3
        ):
            raise trusted_snapshot.ArchiveError
        _reject_object_alternates(self.object_fd)
        try:
            completed = subprocess.run(
                self._command(
                    ("-c", "tar.umask=0022", "archive", "--format=tar", git_sha)
                ),
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


def _authenticated_commit_parents(
    commit_sha: str,
    *,
    object_format: str,
    git_control: Callable[[Path, tuple[str, ...], int], bytes],
) -> tuple[str, ...]:
    raw = git_control(
        REPO_ROOT,
        ("cat-file", "commit", commit_sha),
        trusted_snapshot.MAX_COMMIT_BYTES,
    )
    trusted_snapshot._validated_commit_tree(
        object_format=object_format,
        expected_commit_id=commit_sha,
        content=raw,
    )
    header_end = raw.find(b"\n\n")
    if header_end < 0:
        raise GitEvidenceError
    headers = raw[:header_end].split(b"\n")
    parents: list[str] = []
    parent_prefix = b"parent "
    index = 1
    while index < len(headers) and headers[index].startswith(parent_prefix):
        raw_parent = headers[index][len(parent_prefix) :]
        try:
            parent = raw_parent.decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise GitEvidenceError from exc
        if (
            len(parent) != len(commit_sha)
            or GIT_SHA_RE.fullmatch(parent) is None
            or parent in parents
        ):
            raise GitEvidenceError
        parents.append(parent)
        index += 1
    if any(header.startswith(parent_prefix) for header in headers[index:]):
        raise GitEvidenceError
    return tuple(parents)


def _require_authenticated_ancestor(
    context: CiEventContext, parent_reader: CommitParentReader
) -> None:
    pending = [context.current_sha]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if len(seen) > MAX_ANCESTRY_COMMITS:
            raise GitEvidenceError
        parents = parent_reader(current)
        if context.prior_sha in parents:
            return
        pending.extend(parent for parent in parents if parent not in seen)
    raise GitEvidenceError


@contextmanager
def _catalog_import_alias(module: ModuleType) -> Iterator[None]:
    package_name = "scripts"
    qualified = f"{package_name}.verify_migration_catalog_head"
    package = sys.modules.get(package_name)
    created_package = package is None
    if package is None:
        package = ModuleType(package_name)
        package.__path__ = []  # type: ignore[attr-defined]
        sys.modules[package_name] = package
    old_attribute = getattr(package, "verify_migration_catalog_head", None)
    had_attribute = hasattr(package, "verify_migration_catalog_head")
    old_qualified = sys.modules.get(qualified)
    old_direct = sys.modules.get("verify_migration_catalog_head")
    setattr(package, "verify_migration_catalog_head", module)
    sys.modules[qualified] = module
    sys.modules["verify_migration_catalog_head"] = module
    try:
        yield
    finally:
        if had_attribute:
            setattr(package, "verify_migration_catalog_head", old_attribute)
        else:
            delattr(package, "verify_migration_catalog_head")
        if old_qualified is None:
            sys.modules.pop(qualified, None)
        else:
            sys.modules[qualified] = old_qualified
        if old_direct is None:
            sys.modules.pop("verify_migration_catalog_head", None)
        else:
            sys.modules["verify_migration_catalog_head"] = old_direct
        if created_package:
            sys.modules.pop(package_name, None)


def _load_verification_modules(repository: Path) -> VerificationModules:
    catalog = _load_python_module(
        module_name="_pastorai_catalog_head_from_trusted_ci_snapshot",
        path=repository / CATALOG_VERIFIER_RELATIVE_PATH,
        expected_sha256=CATALOG_VERIFIER_SHA256,
    )
    authoring = _load_python_module(
        module_name="_pastorai_authoring_from_trusted_ci_snapshot",
        path=repository / AUTHORING_RELATIVE_PATH,
    )
    with _catalog_import_alias(catalog):
        source = _load_python_module(
            module_name="_pastorai_source_manifest_from_trusted_ci_snapshot",
            path=repository / SOURCE_MANIFEST_VERIFIER_RELATIVE_PATH,
        )
        epoch = _load_python_module(
            module_name="_pastorai_epoch_v3_from_trusted_ci_snapshot",
            path=repository / EPOCH_V3_VERIFIER_RELATIVE_PATH,
        )
    if authoring.CATALOG_VERIFIER_SHA256 != CATALOG_VERIFIER_SHA256:
        raise GitEvidenceError
    return VerificationModules(
        catalog_head=catalog,
        migration_authoring=authoring,
        source_manifest=source,
        epoch_v3=epoch,
    )


def _read_witness_file(path: Path) -> tuple[bytes, os.stat_result]:
    required = ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required):
        raise GitEvidenceError
    flags = os.O_RDONLY
    for name in required:
        flags |= getattr(os, name)
    try:
        descriptor = os.open(path, flags)
    except (OSError, ValueError) as exc:
        raise GitEvidenceError from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 0
            or before.st_size > trusted_snapshot.MAX_FILE_BYTES
        ):
            raise GitEvidenceError
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise GitEvidenceError
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if _stable_stat_identity(before) != _stable_stat_identity(after):
            raise GitEvidenceError
        return b"".join(chunks), after
    except OSError as exc:
        raise GitEvidenceError from exc
    finally:
        os.close(descriptor)


def _repository_witness(repository: Path) -> str:
    """Bind the complete private tree before and after all validators run."""

    try:
        root = os.lstat(repository)
    except OSError as exc:
        raise GitEvidenceError from exc
    if (
        not stat.S_ISDIR(root.st_mode)
        or stat.S_IMODE(root.st_mode) != 0o700
        or root.st_uid != os.geteuid()
        or root.st_gid != os.getegid()
    ):
        raise GitEvidenceError
    digest = hashlib.sha256(b"PASTORAI-CI-SNAPSHOT-WITNESS-V1\x00")
    count = 0
    total = 0
    for directory, directory_names, file_names in os.walk(
        repository, topdown=True, followlinks=False
    ):
        directory_names.sort()
        file_names.sort()
        current_directory = Path(directory)
        directory_info = os.lstat(current_directory)
        if (
            not stat.S_ISDIR(directory_info.st_mode)
            or stat.S_IMODE(directory_info.st_mode) != 0o700
            or directory_info.st_uid != os.geteuid()
            or directory_info.st_gid != os.getegid()
        ):
            raise GitEvidenceError
        relative_directory = current_directory.relative_to(repository).as_posix()
        digest.update(b"D\x00" + relative_directory.encode("utf-8") + b"\x00")
        for name in directory_names:
            child = os.lstat(current_directory / name)
            if not stat.S_ISDIR(child.st_mode):
                raise GitEvidenceError
        for name in file_names:
            path = current_directory / name
            content, info = _read_witness_file(path)
            if (
                stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid()
                or info.st_gid != os.getegid()
            ):
                raise GitEvidenceError
            count += 1
            total += len(content)
            if (
                count > trusted_snapshot.MAX_ENTRIES
                or total > trusted_snapshot.MAX_TOTAL_FILE_BYTES
            ):
                raise GitEvidenceError
            relative = path.relative_to(repository).as_posix().encode("utf-8")
            digest.update(b"F\x00" + relative + b"\x00")
            digest.update(hashlib.sha256(content).digest())
            digest.update(str(len(content)).encode("ascii") + b"\x00")
            digest.update(str(info.st_ino).encode("ascii") + b"\x00")
            digest.update(str(info.st_ctime_ns).encode("ascii") + b"\x00")
    return digest.hexdigest()


def _verify_snapshot_catalog(
    *,
    context: CiEventContext,
    current_repository: Path,
    prior_repository: Path,
    modules: VerificationModules,
) -> CiVerificationResult:
    current_catalog = modules.catalog_head
    authoring = modules.migration_authoring
    source_manifest = modules.source_manifest
    epoch_v3 = modules.epoch_v3
    prior_path = prior_repository.joinpath(*Path(HEAD_RELATIVE_PATH).parts)
    try:
        prior_record = current_catalog._read_stable_file(
            prior_path,
            maximum_size=current_catalog.MAX_JSON_BYTES,
            error_type=current_catalog.ArtifactIoError,
        )
        snapshot, _catalog = (
            current_catalog._validated_snapshot_for_historical_consumers()
        )
        batches = snapshot.get("append_only_batches")
        if type(batches) is not list:
            raise CurrentCatalogError
        prior_head_required = bool(batches)
        current_record = current_catalog._read_stable_file(
            current_catalog.HEAD_PATH
        )
        appended_now = False
        if not batches:
            if current_record.content != prior_record.content:
                raise GitEvidenceError
            strict_head = current_catalog.verify_versioned_head()
        elif current_record.content == prior_record.content:
            # A non-migration change after the first append is bound by exact
            # head bytes; it must not manufacture another append batch.
            strict_head = snapshot
        else:
            appended_now = True
            approved_prior = current_catalog.ApprovedPriorHead(
                content_sha256=hashlib.sha256(prior_record.content).hexdigest(),
                head=current_catalog._decode_json(prior_record.content),
            )
            strict_head = current_catalog.verify_versioned_head(
                approved_prior=approved_prior
            )
        if not current_catalog._exact_json(snapshot, strict_head):
            raise CurrentCatalogError

        candidate_record = None
        if appended_now:
            entry = strict_head["append_only_batches"][-1]["entries"][0]
            candidate_record = current_catalog._read_stable_file(
                current_catalog.MIGRATIONS_DIR / entry["name"],
                maximum_size=current_catalog.MAX_MIGRATION_BYTES,
            )
            try:
                authoring._validate_candidate_intent(
                    candidate_record,
                    basename=entry["name"],
                    expected_sha=context.prior_sha,
                )
            except authoring.DraftIncompleteError as exc:
                raise CandidateIntentError from exc
            if not current_catalog._stable_file_unchanged(
                current_catalog._read_stable_file(
                    current_catalog.MIGRATIONS_DIR / entry["name"],
                    maximum_size=current_catalog.MAX_MIGRATION_BYTES,
                ),
                candidate_record,
            ):
                raise GitEvidenceError

        source_manifest_path = (
            source_manifest.MANIFEST_DIR / source_manifest.MANIFEST_BASENAME
        )
        try:
            source_manifest.verify_manifest(source_manifest_path)
        except source_manifest.ManifestError as exc:
            raise HistoricalSourceManifestError from exc
        try:
            epoch_v3.verify_versioned_package()
        except epoch_v3.VerificationError as exc:
            raise HistoricalEpochError from exc

        # This is deliberately the last read of every explicitly retained
        # record.  The complete repository witness in ``verify_ci`` surrounds
        # this function and closes mutation windows in indirect inputs too.
        if not current_catalog._stable_file_unchanged(
            current_catalog._read_stable_file(current_catalog.HEAD_PATH),
            current_record,
        ):
            raise GitEvidenceError
        if not current_catalog._stable_file_unchanged(
            current_catalog._read_stable_file(prior_path),
            prior_record,
        ):
            raise GitEvidenceError
    except CiVerificationError:
        raise
    except current_catalog.VerificationError as exc:
        raise CurrentCatalogError from exc

    current = strict_head["current_head"]
    return CiVerificationResult(
        event_name=context.event_name,
        migration_count=current["migration_count"],
        catalog_digest_sha256=current["digest_sha256"],
        prior_head_required=prior_head_required,
    )


def verify_ci(
    *,
    event_name: object,
    current_sha: object,
    pull_request_base_sha: object,
    push_before_sha: object,
    snapshot_factory: SnapshotFactory | None = None,
    commit_parent_reader: CommitParentReader | None = None,
    module_loader: ModuleLoader = _load_verification_modules,
    repository_witness: RepositoryWitness = _repository_witness,
) -> CiVerificationResult:
    context = _event_context(
        event_name=event_name,
        current_sha=current_sha,
        pull_request_base_sha=pull_request_base_sha,
        push_before_sha=push_before_sha,
    )
    if (snapshot_factory is None) != (commit_parent_reader is None):
        raise UsageError

    control_plane: _SanitizedGitControlPlane | None = None
    current_snapshot: object | None = None
    prior_snapshot: object | None = None
    try:
        if snapshot_factory is None:
            control_plane = _SanitizedGitControlPlane.create(
                repository_root=REPO_ROOT,
                expected_sha=context.current_sha,
            )

            def create_snapshot(git_sha: str) -> object:
                return trusted_snapshot.create_trusted_repository_snapshot(
                    repository_root=REPO_ROOT,
                    git_sha=git_sha,
                    git_control=control_plane.control,
                    archive_writer=control_plane.archive,
                )

            def read_parents(git_sha: str) -> tuple[str, ...]:
                return _authenticated_commit_parents(
                    git_sha,
                    object_format=control_plane.object_format,
                    git_control=control_plane.control,
                )

            active_snapshot_factory = create_snapshot
            active_parent_reader = read_parents
        else:
            active_snapshot_factory = snapshot_factory
            active_parent_reader = commit_parent_reader

        current_snapshot = active_snapshot_factory(context.current_sha)
        prior_snapshot = active_snapshot_factory(context.prior_sha)
        if (
            current_snapshot.git_sha != context.current_sha
            or prior_snapshot.git_sha != context.prior_sha
        ):
            raise GitEvidenceError
        _require_authenticated_ancestor(context, active_parent_reader)
        current_before = repository_witness(current_snapshot.repository)
        prior_before = repository_witness(prior_snapshot.repository)
        modules = module_loader(current_snapshot.repository)
        result = _verify_snapshot_catalog(
            context=context,
            current_repository=current_snapshot.repository,
            prior_repository=prior_snapshot.repository,
            modules=modules,
        )
        if (
            repository_witness(current_snapshot.repository) != current_before
            or repository_witness(prior_snapshot.repository) != prior_before
        ):
            raise GitEvidenceError
        return result
    except CiVerificationError:
        raise
    except Exception as exc:
        raise GitEvidenceError from exc
    finally:
        cleanup_failed = False
        for snapshot in (prior_snapshot, current_snapshot):
            if snapshot is None:
                continue
            try:
                snapshot.cleanup()
            except Exception:
                cleanup_failed = True
        if control_plane is not None:
            try:
                control_plane.close()
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            raise GitEvidenceError


def _parse_args(args: list[str]) -> dict[str, str]:
    keys = {
        "--current-sha": "current_sha",
        "--event-name": "event_name",
        "--pull-request-base-sha": "pull_request_base_sha",
        "--push-before-sha": "push_before_sha",
    }
    if len(args) != len(keys) * 2:
        raise UsageError
    parsed: dict[str, str] = {}
    for index in range(0, len(args), 2):
        option = args[index]
        if option not in keys or keys[option] in parsed:
            raise UsageError
        parsed[keys[option]] = args[index + 1]
    if set(parsed) != set(keys.values()):
        raise UsageError
    return parsed


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        parsed = _parse_args(args)
        result = verify_ci(**parsed)
    except CiVerificationError as exc:
        print(f"RESULT=BLOCKED_MIGRATION_CATALOG_CI:{exc.reason}")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return exc.exit_code
    except Exception:
        reason = "INTERNAL_ERROR"
    else:
        print(VERIFIED_RESULT)
        print(f"EVENT_NAME={result.event_name}")
        print(f"CATALOG_MIGRATION_COUNT={result.migration_count}")
        print(f"CATALOG_DIGEST_SHA256={result.catalog_digest_sha256}")
        prior = str(result.prior_head_required).lower()
        print(f"PRIOR_HEAD_REQUIRED={prior}")
        print("HISTORICAL_CONSUMERS=VERIFIED_BLOCKED_ONLY")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return 0
    print(f"RESULT=BLOCKED_MIGRATION_CATALOG_CI:{reason}")
    print(OPERATIONAL_BLOCK)
    print(NEXT_STAGE_BLOCK)
    return 10


if __name__ == "__main__":
    raise SystemExit(main())
