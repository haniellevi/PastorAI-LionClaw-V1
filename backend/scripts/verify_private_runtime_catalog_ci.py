#!/usr/bin/env python3
"""Verify the historical V1 catalog and the separate private stream in CI.

The legacy verifier remains the authority for the public catalog.  This
adapter invokes it unchanged against its authenticated current/prior Git
snapshots, then performs the same snapshot/ancestry checks for the private
stream.  It never applies SQL and never reports a PG17 replay: the required
disposable replay is a separate terminal workflow job.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
from types import ModuleType
from typing import Callable


REPO_ROOT = Path(__file__).absolute().parents[2]
PRIVATE_VERIFIER_RELATIVE_PATH = (
    "backend/scripts/verify_private_runtime_catalog_v1.py"
)
TRUSTED_SNAPSHOT_RELATIVE_PATH = (
    "backend/scripts/trusted_repository_snapshot.py"
)
LEGACY_CI_RELATIVE_PATH = "backend/scripts/verify_migration_catalog_ci.py"
HISTORICAL_COUNT = 75
HISTORICAL_DIGEST_SHA256 = (
    "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f"
)
HISTORICAL_LAST_BASENAME = (
    "20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql"
)
GIT_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
MAX_MODULE_BYTES = 4_194_304
PRIVATE_HEAD_RELATIVE_PATH = (
    "docs/governance/migrations/private-runtime-catalog-head-v1.json"
)
PRIVATE_DIRECTORY_RELATIVE_PATH = "backend/migrations/private_runtime"

# These are the already-reviewed historical CI and snapshot loaders.  The
# private verifier itself is authenticated by the exact Git archive of the
# candidate commit, so it is intentionally not pinned to a pre-commit hash.
LEGACY_CI_SHA256 = (
    "7cf5b468e366debba3a9d23c66566b122c8e155dceb3f76ee4d755ce4410b7c8"
)
TRUSTED_SNAPSHOT_SHA256 = (
    "43dd9161cda2fc3cb7e1800a1b756f5595facbcc5c15274f282f6e763252d392"
)

VERIFIED_RESULT = "RESULT=PRIVATE_RUNTIME_CATALOG_CI_SOURCE_VERIFIED"
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
NEXT_STAGE_BLOCK = "NEXT_STAGE_AUTHORIZED=false"


class PrivateRuntimeCiError(RuntimeError):
    exit_code = 4
    reason = "PRIVATE_RUNTIME_CI_INVALID"


class UsageError(PrivateRuntimeCiError):
    exit_code = 2
    reason = "USAGE"


class GitEvidenceError(PrivateRuntimeCiError):
    exit_code = 3
    reason = "AUTHENTICATED_GIT_EVIDENCE_INVALID"


class HistoricalProofError(PrivateRuntimeCiError):
    exit_code = 4
    reason = "HISTORICAL_V1_PROOF_INVALID"


class PrivateSourceError(PrivateRuntimeCiError):
    exit_code = 5
    reason = "PRIVATE_SOURCE_INVALID"


@dataclass(frozen=True)
class CiVerificationResult:
    event_name: str
    public_migration_count: int
    public_digest_sha256: str
    private_migration_count: int
    private_digest_sha256: str
    private_last_basename: str
    combined_migration_count: int
    private_append_verified: bool


def _stable_stat(value: os.stat_result) -> tuple[int, ...]:
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


def _read_verified_source(path: Path, *, expected_sha256: str | None) -> bytes:
    """Read a regular source file by descriptor and authenticate its bytes."""

    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts[1:])
        or (
            expected_sha256 is not None
            and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        )
    ):
        raise GitEvidenceError
    required = ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required):
        raise GitEvidenceError
    flags = os.O_RDONLY
    for name in required:
        flags |= getattr(os, name)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > MAX_MODULE_BYTES
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
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if _stable_stat(before) != _stable_stat(after):
            raise GitEvidenceError
        if (
            expected_sha256 is not None
            and hashlib.sha256(content).hexdigest() != expected_sha256
        ):
            raise GitEvidenceError
        return content
    except (OSError, ValueError) as exc:
        raise GitEvidenceError from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _load_module(
    *, name: str, path: Path, expected_sha256: str | None = None
) -> ModuleType:
    content = _read_verified_source(path, expected_sha256=expected_sha256)
    try:
        code = compile(content, str(path), "exec", dont_inherit=True)
        module = ModuleType(name)
        module.__file__ = str(path)
        module.__package__ = ""
        module.__spec__ = None
        sys.modules[name] = module
        exec(code, module.__dict__)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


legacy_ci = _load_module(
    name="_pastorai_legacy_migration_catalog_ci_for_private_ci",
    path=REPO_ROOT / LEGACY_CI_RELATIVE_PATH,
    expected_sha256=LEGACY_CI_SHA256,
)
if (
    getattr(legacy_ci, "TRUSTED_SNAPSHOT_RELATIVE_PATH", None)
    != TRUSTED_SNAPSHOT_RELATIVE_PATH
    or getattr(legacy_ci, "TRUSTED_SNAPSHOT_SHA256", None)
    != TRUSTED_SNAPSHOT_SHA256
):
    raise RuntimeError("legacy CI trusted-snapshot pin drifted")


def _load_private_verifier(repository: Path) -> ModuleType:
    path = repository / PRIVATE_VERIFIER_RELATIVE_PATH
    return _load_module(
        name="_pastorai_private_catalog_verifier_from_authenticated_snapshot",
        path=path,
    )


def _validated_context(
    *,
    event_name: object,
    current_sha: object,
    pull_request_base_sha: object,
    push_before_sha: object,
) -> object:
    try:
        return legacy_ci._event_context(
            event_name=event_name,
            current_sha=current_sha,
            pull_request_base_sha=pull_request_base_sha,
            push_before_sha=push_before_sha,
        )
    except Exception as exc:
        raise UsageError from exc


def _missing_or_regular(path: Path) -> bool:
    """Return true only for a genuinely absent path; reject symlink targets."""

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return True
    except OSError as exc:
        raise GitEvidenceError from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise GitEvidenceError
    return False


def _prior_private_head(
    *,
    private_module: ModuleType,
    prior_repository: Path,
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    head_path = prior_repository / PRIVATE_HEAD_RELATIVE_PATH
    directory = prior_repository / PRIVATE_DIRECTORY_RELATIVE_PATH
    if _missing_or_regular(head_path):
        try:
            os.lstat(directory)
        except FileNotFoundError:
            return None, []
        except OSError as exc:
            raise GitEvidenceError from exc
        # An unanchored directory is not an acceptable prior state, even when
        # it happens to be empty: a private stream must be born with its head.
        raise HistoricalProofError
    try:
        head = private_module.private_catalog.read_json(head_path)
        scanned = private_module.private_catalog.scan_directory(directory)
        private_module.private_catalog.validate_head(
            head,
            scanned_entries=scanned,
        )
    except Exception as exc:
        raise HistoricalProofError from exc
    return head, scanned


def _validate_private_snapshot(
    *,
    context: object,
    current_repository: Path,
    prior_repository: Path,
    private_module: ModuleType,
) -> CiVerificationResult:
    try:
        source_result = private_module.verify()
    except Exception as exc:
        raise PrivateSourceError from exc
    if (
        source_result.public_migration_count != HISTORICAL_COUNT
        or source_result.public_digest_sha256 != HISTORICAL_DIGEST_SHA256
        or source_result.private_migration_count < 0
    ):
        raise PrivateSourceError

    current_head_path = current_repository / PRIVATE_HEAD_RELATIVE_PATH
    current_directory = current_repository / PRIVATE_DIRECTORY_RELATIVE_PATH
    try:
        current_head = private_module.private_catalog.read_json(current_head_path)
        current_scanned = private_module.private_catalog.scan_directory(current_directory)
        current_entries = private_module.private_catalog.validate_head(
            current_head,
            scanned_entries=current_scanned,
        )
    except Exception as exc:
        raise PrivateSourceError from exc

    prior_head, prior_entries = _prior_private_head(
        private_module=private_module,
        prior_repository=prior_repository,
    )
    private_append_verified = False
    if prior_head is None:
        if current_entries:
            if len(current_entries) != 1 or len(current_head["append_only_batches"]) != 1:
                raise HistoricalProofError
            private_append_verified = True
    else:
        try:
            private_module.private_catalog.validate_head(
                current_head,
                scanned_entries=current_scanned,
                approved_prior=prior_head,
            )
        except Exception as exc:
            raise HistoricalProofError from exc
        if len(current_entries) > len(prior_entries):
            if len(current_entries) != len(prior_entries) + 1:
                raise HistoricalProofError
            private_append_verified = True
        elif current_entries != prior_entries:
            raise HistoricalProofError

    # A new entry must be authored against the authenticated prior commit.  A
    # no-op private stream is allowed after it has already been authenticated.
    if private_append_verified:
        entry = current_entries[-1]
        try:
            content = private_module.private_catalog.read_file(
                current_directory / entry["name"]
            )
            private_module.adapter.validate_private_runtime_candidate(
                content,
                basename=entry["name"],
                expected_sha=context.prior_sha,
            )
        except Exception as exc:
            raise PrivateSourceError from exc

    public_count = source_result.public_migration_count
    private_count = source_result.private_migration_count
    if private_count != len(current_entries) or public_count != HISTORICAL_COUNT:
        raise PrivateSourceError
    if current_entries and current_entries[0]["name"] <= HISTORICAL_LAST_BASENAME:
        raise PrivateSourceError
    if [entry["position"] for entry in current_entries] != list(range(private_count)):
        raise PrivateSourceError
    return CiVerificationResult(
        event_name=context.event_name,
        public_migration_count=public_count,
        public_digest_sha256=source_result.public_digest_sha256,
        private_migration_count=private_count,
        private_digest_sha256=source_result.private_digest_sha256,
        private_last_basename=source_result.private_last_basename,
        combined_migration_count=public_count + private_count,
        private_append_verified=private_append_verified,
    )


SnapshotFactory = Callable[[str], object]
CommitParentReader = Callable[[str], tuple[str, ...]]
ModuleLoader = Callable[[Path], ModuleType]
RepositoryWitness = Callable[[Path], str]


def verify_ci(
    *,
    event_name: object,
    current_sha: object,
    pull_request_base_sha: object,
    push_before_sha: object,
    snapshot_factory: SnapshotFactory | None = None,
    commit_parent_reader: CommitParentReader | None = None,
    module_loader: ModuleLoader = _load_private_verifier,
    repository_witness: RepositoryWitness = legacy_ci._repository_witness,
    legacy_verifier: Callable[..., object] = legacy_ci.verify_ci,
) -> CiVerificationResult:
    context = _validated_context(
        event_name=event_name,
        current_sha=current_sha,
        pull_request_base_sha=pull_request_base_sha,
        push_before_sha=push_before_sha,
    )
    if (snapshot_factory is None) != (commit_parent_reader is None):
        raise UsageError

    try:
        # This call is intentionally unconditional: V1 proof is not inferred
        # from the private adapter and cannot be replaced by a lexical check.
        legacy_result = legacy_verifier(
            event_name=event_name,
            current_sha=current_sha,
            pull_request_base_sha=pull_request_base_sha,
            push_before_sha=push_before_sha,
        )
        if (
            legacy_result.migration_count != HISTORICAL_COUNT
            or legacy_result.catalog_digest_sha256 != HISTORICAL_DIGEST_SHA256
        ):
            raise HistoricalProofError
    except HistoricalProofError:
        raise
    except Exception as exc:
        raise HistoricalProofError from exc

    control_plane: object | None = None
    current_snapshot: object | None = None
    prior_snapshot: object | None = None
    try:
        if snapshot_factory is None:
            control_plane = legacy_ci._SanitizedGitControlPlane.create(
                repository_root=REPO_ROOT,
                expected_sha=context.current_sha,
            )

            def create_snapshot(git_sha: str) -> object:
                return legacy_ci.trusted_snapshot.create_trusted_repository_snapshot(
                    repository_root=REPO_ROOT,
                    git_sha=git_sha,
                    git_control=control_plane.control,
                    archive_writer=control_plane.archive,
                )

            def read_parents(git_sha: str) -> tuple[str, ...]:
                return legacy_ci._authenticated_commit_parents(
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
        legacy_ci._require_authenticated_ancestor(context, active_parent_reader)
        current_before = repository_witness(current_snapshot.repository)
        prior_before = repository_witness(prior_snapshot.repository)
        private_module = module_loader(current_snapshot.repository)
        result = _validate_private_snapshot(
            context=context,
            current_repository=current_snapshot.repository,
            prior_repository=prior_snapshot.repository,
            private_module=private_module,
        )
        if (
            repository_witness(current_snapshot.repository) != current_before
            or repository_witness(prior_snapshot.repository) != prior_before
        ):
            raise GitEvidenceError
        return result
    except PrivateRuntimeCiError:
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
        result = verify_ci(**_parse_args(args))
    except PrivateRuntimeCiError as exc:
        print(f"RESULT=BLOCKED_PRIVATE_RUNTIME_CI:{exc.reason}")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return exc.exit_code
    except Exception:
        print("RESULT=BLOCKED_PRIVATE_RUNTIME_CI:INTERNAL_ERROR")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return 10
    print(VERIFIED_RESULT)
    print(f"EVENT_NAME={result.event_name}")
    print(f"PUBLIC_CATALOG_MIGRATION_COUNT={result.public_migration_count}")
    print(f"PUBLIC_CATALOG_DIGEST_SHA256={result.public_digest_sha256}")
    print(f"PRIVATE_CATALOG_MIGRATION_COUNT={result.private_migration_count}")
    print(f"PRIVATE_CATALOG_DIGEST_SHA256={result.private_digest_sha256}")
    print(f"PRIVATE_CATALOG_LAST_BASENAME={result.private_last_basename}")
    print(f"COMBINED_CATALOG_MIGRATION_COUNT={result.combined_migration_count}")
    print(f"PRIVATE_APPEND_VERIFIED={str(result.private_append_verified).lower()}")
    print("PG17_REPLAY_REQUIRED=true")
    print(OPERATIONAL_BLOCK)
    print(NEXT_STAGE_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
