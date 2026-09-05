#!/usr/bin/env python3
"""Source-only ``draft``/``prepare-head`` authoring for V2 private SQL.

This authoring path deliberately does not call or modify the V1 authoring
script.  Public migrations remain in the byte-pinned V1 catalog; private
runtime migrations are authored below ``backend/migrations/private_runtime``
and published only through the separate private head manifest.
"""

from __future__ import annotations

import base64
import copy
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from types import ModuleType


REPO_ROOT = Path(__file__).absolute().parents[2]
PRIVATE_DIR = REPO_ROOT / "backend" / "migrations" / "private_runtime"
PRIVATE_HEAD_PATH = (
    REPO_ROOT / "docs" / "governance" / "migrations" / "private-runtime-catalog-head-v1.json"
)
PUBLIC_HEAD_PATH = (
    REPO_ROOT / "docs" / "governance" / "migrations" / "migration-catalog-head-v1.json"
)
PUBLIC_MIGRATIONS_DIR = REPO_ROOT / "backend" / "migrations"
GIT_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})$")
MAX_DESCRIPTION_CHARS = 160
MAX_SLUG_CHARS = 120
V2_INTENT_PREFIX = "-- PASTORAI_MIGRATION_INTENT_V2="
OPERATIONAL_BLOCK = "-- OPERATIONAL_AUTHORIZATION=BLOCKED"
NEXT_STAGE_BLOCK = "-- NEXT_STAGE_AUTHORIZED=false"
INCOMPLETE_MARKER = "-- PRIVATE_RUNTIME_MIGRATION_DRAFT_INCOMPLETE"


def _load_sibling(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        name,
        Path(__file__).with_name(filename),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("private authoring dependency unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


intent = _load_sibling(
    "private_runtime_intent_runtime_v1_for_private_authoring",
    "private_runtime_intent_runtime_v1.py",
)
adapter = _load_sibling(
    "private_runtime_adapter_v1_for_private_authoring",
    "private_runtime_catalog_adapter_v1.py",
)
private_catalog = _load_sibling(
    "private_runtime_catalog_v1_for_private_authoring",
    "private_runtime_catalog_v1.py",
)
public_catalog = _load_sibling(
    "public_catalog_v1_for_private_authoring",
    "verify_migration_catalog_head.py",
)


class PrivateRuntimeAuthoringError(RuntimeError):
    exit_code = 4


class UsageError(PrivateRuntimeAuthoringError):
    exit_code = 2


class CollisionError(PrivateRuntimeAuthoringError):
    exit_code = 5


class RepositoryBindingError(PrivateRuntimeAuthoringError):
    exit_code = 7


class DraftIncompleteError(PrivateRuntimeAuthoringError):
    exit_code = 6


@dataclass(frozen=True)
class PreparedPrivateHead:
    batch_id: str
    previous_private_digest_sha256: str
    content: bytes
    content_sha256: str


def _validated_sha(value: object) -> str:
    if type(value) is not str or GIT_SHA_RE.fullmatch(value) is None or set(value) == {"0"}:
        raise UsageError
    return value


def _git_head() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        value = completed.stdout.decode("ascii", errors="strict").strip()
    except (OSError, UnicodeDecodeError, subprocess.SubprocessError) as exc:
        raise RepositoryBindingError from exc
    if GIT_SHA_RE.fullmatch(value) is None:
        raise RepositoryBindingError
    return value


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


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = private_catalog.read_json(path)
    except private_catalog.PrivateRuntimeCatalogError as exc:
        raise PrivateRuntimeAuthoringError from exc
    return value


def _verify_public_baseline() -> None:
    """Require the immutable public 75-prefix without editing its verifier."""

    try:
        head = public_catalog.verify_versioned_head()
    except public_catalog.VerificationError as exc:
        raise RepositoryBindingError from exc
    current = head.get("current_head")
    if (
        type(current) is not dict
        or current.get("migration_count") != private_catalog.HISTORICAL_COUNT
        or current.get("last_basename") != private_catalog.HISTORICAL_LAST_BASENAME
        or current.get("digest_sha256") != private_catalog.HISTORICAL_DIGEST_SHA256
        or head.get("append_only_batches") != []
    ):
        raise RepositoryBindingError
    if PUBLIC_HEAD_PATH != public_catalog.HEAD_PATH:
        raise RepositoryBindingError
    # Keep the direct public directory separate from the private suffix.  This
    # catches an accidental V2 file placed in the V1 directory before writing.
    if any(path.is_file() for path in PUBLIC_MIGRATIONS_DIR.glob("*.private.sql")):
        raise RepositoryBindingError


def _load_private_head() -> dict[str, object]:
    head = _load_json(PRIVATE_HEAD_PATH)
    try:
        # A draft is intentionally the one allowed unrepresented file.  The
        # caller compares the scan either to the current head (before draft)
        # or to exactly one appended candidate (prepare-head).
        private_catalog.validate_head(head)
    except private_catalog.PrivateRuntimeCatalogError as exc:
        raise RepositoryBindingError from exc
    return head


def _write_exclusive(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    for name in ("O_CLOEXEC", "O_NOFOLLOW"):
        if not hasattr(os, name):
            raise PrivateRuntimeAuthoringError
        flags |= getattr(os, name)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        written = 0
        while written < len(content):
            amount = os.write(descriptor, content[written:])
            if amount <= 0:
                raise PrivateRuntimeAuthoringError
            written += amount
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        if info.st_nlink != 1 or info.st_size != len(content) or (info.st_mode & 0o777) != 0o600:
            raise PrivateRuntimeAuthoringError
    except FileExistsError as exc:
        raise CollisionError from exc
    except OSError as exc:
        raise PrivateRuntimeAuthoringError from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


class _AuthoringLock:
    def __init__(self) -> None:
        self._descriptors: list[int] = []

    def __enter__(self) -> "_AuthoringLock":
        try:
            PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
            for path in (PRIVATE_DIR, PRIVATE_HEAD_PATH.parent):
                descriptor = private_catalog._open_directory(path)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except Exception:
                    os.close(descriptor)
                    raise
                self._descriptors.append(descriptor)
        except (OSError, ValueError, BlockingIOError) as exc:
            self.__exit__(type(exc), exc, exc.__traceback__)
            raise PrivateRuntimeAuthoringError from exc
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        for descriptor in reversed(self._descriptors):
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        self._descriptors.clear()


def _draft_content(basename: str, expected_sha: str) -> bytes:
    value = intent.default_intent(
        basename=basename,
        base_repository_sha=expected_sha,
    )
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return (
        (V2_INTENT_PREFIX + encoded + "\n").encode("ascii")
        + ("-- " + "=" * 76 + "\n").encode("ascii")
        + f"-- PastorAI PRIVATE_RUNTIME migration candidate: {basename}\n".encode("ascii")
        + (INCOMPLETE_MARKER + "\n").encode("ascii")
        + b"-- Complete the closed V2 intent and add reviewed SQL only.\n"
        + b"-- This candidate is source-only; no catalog or database is changed.\n"
        + (OPERATIONAL_BLOCK + "\n" + NEXT_STAGE_BLOCK + "\n").encode("ascii")
        + b"-- Run private_runtime_migration_authoring_v1.py prepare-head after review.\n"
    )


def create_draft(description: str, *, expected_sha: str) -> str:
    expected_sha = _validated_sha(expected_sha)
    if _git_head() != expected_sha:
        raise RepositoryBindingError
    slug = slugify(description)
    with _AuthoringLock():
        _verify_public_baseline()
        head = _load_private_head()
        last = head["current_head"]["last_basename"]
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        basename = f"{timestamp}_{slug}.sql"
        if (
            not isinstance(last, str)
            or basename <= last
            or private_catalog.MIGRATION_BASENAME_RE.fullmatch(basename) is None
        ):
            raise PrivateRuntimeAuthoringError
        _write_exclusive(PRIVATE_DIR / basename, _draft_content(basename, expected_sha))
        scanned = private_catalog.scan_directory(PRIVATE_DIR)
        if len(scanned) != len(head["private_entries"]) + 1 or scanned[-1]["name"] != basename:
            raise PrivateRuntimeAuthoringError
        return basename


def _serialize_head(head: dict[str, object]) -> bytes:
    return (json.dumps(head, ensure_ascii=True, indent=2) + "\n").encode("ascii")


def prepare_head(basename: str, *, expected_sha: str) -> PreparedPrivateHead:
    expected_sha = _validated_sha(expected_sha)
    if _git_head() != expected_sha:
        raise RepositoryBindingError
    if (
        type(basename) is not str
        or private_catalog.MIGRATION_BASENAME_RE.fullmatch(basename) is None
    ):
        raise UsageError
    with _AuthoringLock():
        _verify_public_baseline()
        head = _load_private_head()
        scanned = private_catalog.scan_directory(PRIVATE_DIR)
        entries = head["private_entries"]
        if (
            type(entries) is not list
            or len(scanned) != len(entries) + 1
            or scanned[:-1] != entries
            or scanned[-1]["name"] != basename
        ):
            raise DraftIncompleteError
        record = PRIVATE_DIR / basename
        try:
            content = private_catalog.read_file(record)
        except private_catalog.PrivateRuntimeCatalogError as exc:
            raise DraftIncompleteError from exc
        try:
            candidate = adapter.validate_private_runtime_candidate(
                content,
                basename=basename,
                expected_sha=expected_sha,
            )
        except adapter.PrivateRuntimeCatalogAdapterError as exc:
            raise DraftIncompleteError from exc
        if candidate.content_sha256 != scanned[-1]["sha256"] or len(content) != scanned[-1]["size_bytes"]:
            raise DraftIncompleteError
        previous_digest = head["current_head"]["private_digest_sha256"]
        sequence = len(head["append_only_batches"]) + 1
        new_entries = copy.deepcopy(entries)
        new_entries.append(copy.deepcopy(scanned[-1]))
        resulting_digest = private_catalog.private_digest(new_entries)
        new_head = copy.deepcopy(head)
        new_head["private_entries"] = new_entries
        new_head["append_only_batches"].append(
            {
                "batch_id": f"private-runtime-catalog-append-{sequence:04d}",
                "entries": [copy.deepcopy(scanned[-1])],
                "previous_private_digest_sha256": previous_digest,
                "resulting_private_digest_sha256": resulting_digest,
                "sequence": sequence,
            }
        )
        new_head["current_head"] = {
            "last_basename": basename,
            "private_digest_sha256": resulting_digest,
            "private_migration_count": len(new_entries),
        }
        try:
            private_catalog.validate_head(new_head, scanned_entries=new_entries)
        except private_catalog.PrivateRuntimeCatalogError as exc:
            raise PrivateRuntimeAuthoringError from exc
        serialized = _serialize_head(new_head)
        return PreparedPrivateHead(
            batch_id=new_head["append_only_batches"][-1]["batch_id"],
            previous_private_digest_sha256=previous_digest,
            content=serialized,
            content_sha256=hashlib.sha256(serialized).hexdigest(),
        )


def _usage() -> None:
    print(
        "usage: python scripts/private_runtime_migration_authoring_v1.py draft "
        '--expected-repository-sha <sha> "description"',
        file=sys.stderr,
    )
    print(
        "   or: python scripts/private_runtime_migration_authoring_v1.py prepare-head "
        "--expected-repository-sha <sha> <basename.sql>",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 4 or args[1] != "--expected-repository-sha":
            raise UsageError
        if args[0] == "draft":
            basename = create_draft(args[3], expected_sha=args[2])
            print("RESULT=PRIVATE_RUNTIME_MIGRATION_DRAFT_CREATED")
            print(f"MIGRATION_BASENAME={basename}")
            print(f"EXPECTED_REPOSITORY_SHA={args[2]}")
            print("CATALOG_HEAD_UPDATE_REQUIRED=true")
        elif args[0] == "prepare-head":
            candidate = prepare_head(args[3], expected_sha=args[2])
            print("RESULT=PRIVATE_RUNTIME_MIGRATION_APPEND_CANDIDATE_PREPARED")
            print(f"MIGRATION_BASENAME={args[3]}")
            print(f"EXPECTED_REPOSITORY_SHA={args[2]}")
            print(f"APPEND_BATCH_ID={candidate.batch_id}")
            print(
                "PREVIOUS_PRIVATE_DIGEST_SHA256="
                f"{candidate.previous_private_digest_sha256}"
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
        print(f"RESULT=BLOCKED_PRIVATE_RUNTIME_AUTHORING:USAGE")
        print("OPERATIONAL_AUTHORIZATION=BLOCKED")
        print("NEXT_STAGE_AUTHORIZED=false")
        return exc.exit_code
    except PrivateRuntimeAuthoringError as exc:
        print(f"RESULT=BLOCKED_PRIVATE_RUNTIME_AUTHORING:{exc.__class__.__name__}")
        print("OPERATIONAL_AUTHORIZATION=BLOCKED")
        print("NEXT_STAGE_AUTHORIZED=false")
        return exc.exit_code
    except Exception:
        print("RESULT=BLOCKED_PRIVATE_RUNTIME_AUTHORING:INTERNAL_ERROR")
        print("OPERATIONAL_AUTHORIZATION=BLOCKED")
        print("NEXT_STAGE_AUTHORIZED=false")
        return 10
    print("OPERATIONAL_AUTHORIZATION=BLOCKED")
    print("NEXT_STAGE_AUTHORIZED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
