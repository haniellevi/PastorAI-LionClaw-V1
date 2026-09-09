#!/usr/bin/env python3
"""Verify the exact receipt emitted by the private PG17 replay.

The replay receipt is evidence, not an authorization token.  This verifier
binds every source-derived field to the authenticated private head and then
requires the complete ordered byte sequence.  It deliberately has no
database client dependency and never opens a database connection.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from types import ModuleType
from typing import NoReturn, Sequence


REPO_ROOT = Path(__file__).absolute().parents[2]
PRIVATE_CATALOG_PATH = (
    REPO_ROOT / "backend" / "scripts" / "private_runtime_catalog_v1.py"
)
PRIVATE_CATALOG_SHA256 = (
    "e957748a6e195466e132c9d5623daab2926a5d1fd2852476d74721fe1f5061c4"
)
PUBLIC_SNAPSHOT_PATH = (
    REPO_ROOT / "backend" / "scripts" / "validated_migration_catalog_snapshot.py"
)
PUBLIC_SNAPSHOT_SHA256 = (
    "c3b88dd7f2b520e9de9353f2c220b5a2f07aaadc42661e8f2d9bb03a955d1d3f"
)
TRUSTED_SNAPSHOT_PATH = (
    REPO_ROOT / "backend" / "scripts" / "trusted_repository_snapshot.py"
)
TRUSTED_SNAPSHOT_SHA256 = (
    "43dd9161cda2fc3cb7e1800a1b756f5595facbcc5c15274f282f6e763252d392"
)
PRIVATE_HEAD_RELATIVE = "docs/governance/migrations/private-runtime-catalog-head-v1.json"
PRIVATE_DIRECTORY_RELATIVE = "backend/migrations/private_runtime"
PRIVATE_HEAD_PATH = REPO_ROOT / PRIVATE_HEAD_RELATIVE
PRIVATE_DIRECTORY = REPO_ROOT / PRIVATE_DIRECTORY_RELATIVE
MAX_LOCAL_MODULE_BYTES = 4_194_304
MAX_RECEIPT_BYTES = 16_384
HISTORICAL_COUNT = 75
HISTORICAL_LAST_BASENAME = "20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql"
HISTORICAL_DIGEST_SHA256 = (
    "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f"
)
EXPECTED_RESULT = "RESULT=PRIVATE_RUNTIME_PROJECTION_REPLAYED_PG17_DISPOSABLE"
EXPECTED_LINES_PREFIX = (
    "OPERATIONAL_AUTHORIZATION=BLOCKED",
    "NEXT_STAGE_AUTHORIZED=false",
    "SHARED_ENVIRONMENT_ATTESTATION=false",
    EXPECTED_RESULT,
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z", re.I)
PUBLIC_INTENT_PREFIX = b"-- PASTORAI_MIGRATION_INTENT_V1="
PUBLIC_MIGRATION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,255}\.sql$")
BASENAME_RE = re.compile(
    r"^[0-9]{8}_[0-9]{6}_[a-z][a-z0-9_]{0,119}\.sql$"
)
PUBLIC_CURRENT_COUNT = HISTORICAL_COUNT + 1
PUBLIC_APPEND_COUNT = 1
COMPOSITION_PUBLIC_APPEND_THEN_PRIVATE = "PUBLIC_APPEND_THEN_PRIVATE"
COMPOSITION_PRIVATE_THEN_PUBLIC_APPEND = "PRIVATE_THEN_PUBLIC_APPEND"
COMPOSITION_ORDERS = (
    COMPOSITION_PUBLIC_APPEND_THEN_PRIVATE,
    COMPOSITION_PRIVATE_THEN_PUBLIC_APPEND,
)
# These are only compatibility defaults for callers that build a receipt
# fixture without an authenticated public snapshot.  The executable verifier
# always supplies values derived from the snapshot and GITHUB_SHA.
DEFAULT_PUBLIC_DIGEST = "a" * 64
DEFAULT_PUBLIC_APPEND_SHA = "b" * 64
DEFAULT_SOURCE_GIT_SHA = "c" * 40
DEFAULT_PUBLIC_APPEND_BASENAME = "20260909_004005_consent_evidence_store_lab.sql"


class ReceiptVerificationError(RuntimeError):
    """Raised when a receipt or its authenticated source is invalid."""


class SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise ReceiptVerificationError


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


def _read_pinned_source(path: Path, expected_sha256: str) -> bytes:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        or any(part in {"", ".", ".."} for part in path.parts[1:])
        or any(
            not hasattr(os, flag)
            for flag in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK")
        )
    ):
        raise ReceiptVerificationError
    descriptor: int | None = None
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > MAX_LOCAL_MODULE_BYTES
        ):
            raise ReceiptVerificationError
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise ReceiptVerificationError
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            _stable_stat(before) != _stable_stat(after)
            or hashlib.sha256(content).hexdigest() != expected_sha256
        ):
            raise ReceiptVerificationError
        return content
    except (OSError, TypeError, ValueError) as exc:
        raise ReceiptVerificationError from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _load_private_catalog() -> ModuleType:
    name = "_pastorai_private_catalog_for_pg17_receipt"
    if name in sys.modules:
        raise ReceiptVerificationError
    content = _read_pinned_source(PRIVATE_CATALOG_PATH, PRIVATE_CATALOG_SHA256)
    try:
        code = compile(content, os.fspath(PRIVATE_CATALOG_PATH), "exec", dont_inherit=True)
        module = ModuleType(name)
        module.__file__ = os.fspath(PRIVATE_CATALOG_PATH)
        module.__package__ = ""
        module.__spec__ = None
        sys.modules[name] = module
        exec(code, module.__dict__)
    except Exception as exc:
        sys.modules.pop(name, None)
        raise ReceiptVerificationError from exc
    return module


def _load_pinned_module(*, name: str, path: Path, expected_sha256: str) -> ModuleType:
    """Load a source dependency only after authenticating its exact bytes."""

    if name in sys.modules:
        raise ReceiptVerificationError
    content = _read_pinned_source(path, expected_sha256)
    try:
        code = compile(content, os.fspath(path), "exec", dont_inherit=True)
        module = ModuleType(name)
        module.__file__ = os.fspath(path)
        module.__package__ = ""
        module.__spec__ = None
        sys.modules[name] = module
        exec(code, module.__dict__)
    except Exception as exc:
        sys.modules.pop(name, None)
        raise ReceiptVerificationError from exc
    return module


def _load_public_snapshot() -> ModuleType:
    """Load the already-pinned public snapshot API in an isolated namespace."""

    return _load_pinned_module(
        name="_pastorai_public_catalog_snapshot_for_pg17_receipt",
        path=PUBLIC_SNAPSHOT_PATH,
        expected_sha256=PUBLIC_SNAPSHOT_SHA256,
    )


def _unload_public_snapshot(module: ModuleType) -> None:
    """Remove this invocation's snapshot modules without touching callers."""

    names = {"_pastorai_public_catalog_snapshot_for_pg17_receipt"}
    catalog = getattr(module, "catalog", None)
    catalog_name = getattr(catalog, "__name__", None)
    if type(catalog_name) is str:
        names.add(catalog_name)
    for name in names:
        sys.modules.pop(name, None)


def _load_trusted_snapshot() -> ModuleType:
    """Load the trusted repository snapshot implementation by pinned bytes."""

    name = "_pastorai_trusted_snapshot_for_pg17_receipt"
    existing = sys.modules.get(name)
    if isinstance(existing, ModuleType):
        return existing
    return _load_pinned_module(
        name=name,
        path=TRUSTED_SNAPSHOT_PATH,
        expected_sha256=TRUSTED_SNAPSHOT_SHA256,
    )


def _authenticated_source_git_sha() -> str:
    """Authenticate the workflow source SHA with the local Git snapshot tool.

    ``GITHUB_SHA`` is metadata supplied by the checkout event, but is not
    accepted merely because it has a hexadecimal shape.  The pinned trusted
    snapshot implementation must resolve that exact commit from this local
    repository and verify its commit/tree/archive before the SHA is emitted in
    a receipt.  The temporary snapshot is immediately removed; it is only a
    source-authentication witness here.
    """

    value = os.environ.get("GITHUB_SHA")
    if (
        type(value) is not str
        or GIT_SHA_RE.fullmatch(value) is None
        or set(value.casefold()) == {"0"}
    ):
        raise ReceiptVerificationError
    value = value.casefold()
    trusted = _load_trusted_snapshot()
    snapshot = None
    try:
        snapshot = trusted.create_trusted_repository_snapshot(
            repository_root=REPO_ROOT,
            git_sha=value,
        )
        if snapshot.git_sha != value or snapshot.repository != snapshot.root / "repo":
            raise ReceiptVerificationError
        return value
    except ReceiptVerificationError:
        raise
    except Exception as exc:
        raise ReceiptVerificationError from exc
    finally:
        if snapshot is not None:
            try:
                snapshot.cleanup()
            except Exception as exc:
                raise ReceiptVerificationError from exc


def _public_entry_mapping(entry: object) -> dict[str, object]:
    try:
        position = entry.position  # type: ignore[attr-defined]
        name = entry.name  # type: ignore[attr-defined]
        sha256 = entry.sha256  # type: ignore[attr-defined]
        size_bytes = entry.size_bytes  # type: ignore[attr-defined]
    except AttributeError as exc:
        raise ReceiptVerificationError from exc
    if (
        type(position) is not int
        or type(name) is not str
        or PUBLIC_MIGRATION_NAME_RE.fullmatch(name) is None
        or type(sha256) is not str
        or SHA256_RE.fullmatch(sha256) is None
        or type(size_bytes) is not int
        or size_bytes < 1
    ):
        raise ReceiptVerificationError
    return {
        "position": position,
        "name": name,
        "sha256": sha256,
        "size_bytes": size_bytes,
    }


def _authenticated_public_fields(
    public_snapshot: ModuleType,
) -> dict[str, object]:
    """Validate the complete public head before checking its 75-entry prefix."""

    try:
        snapshot = public_snapshot.validated_local_catalog_snapshot()
        entries = tuple(snapshot.entries)
        if (
            snapshot.operational_authorization is not False
            or snapshot.next_stage_authorized is not False
            or len(entries) != PUBLIC_CURRENT_COUNT
        ):
            raise ReceiptVerificationError
        if [entry.position for entry in entries] != list(range(PUBLIC_CURRENT_COUNT)):
            raise ReceiptVerificationError
        prefix = entries[:HISTORICAL_COUNT]
        append = entries[HISTORICAL_COUNT:]
        if len(append) != PUBLIC_APPEND_COUNT:
            raise ReceiptVerificationError
        historical_last = prefix[-1]
        candidate = append[0]
        if (
            historical_last.name
            != "20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql"
            or candidate.name <= historical_last.name
        ):
            raise ReceiptVerificationError
        public_catalog = public_snapshot.catalog
        historical_digest = public_catalog._catalog_digest(
            [_public_entry_mapping(entry) for entry in prefix]
        )
        if historical_digest != HISTORICAL_DIGEST_SHA256:
            raise ReceiptVerificationError
        current_digest = snapshot.catalog_digest_sha256
        if (
            type(current_digest) is not str
            or SHA256_RE.fullmatch(current_digest) is None
            or current_digest == HISTORICAL_DIGEST_SHA256
        ):
            raise ReceiptVerificationError
        append_sha = candidate.sha256
        if type(append_sha) is not str or SHA256_RE.fullmatch(append_sha) is None:
            raise ReceiptVerificationError
        candidate_path = public_catalog.MIGRATIONS_DIR / candidate.name
        candidate_record = public_catalog._read_stable_file(
            candidate_path,
            maximum_size=public_catalog.MAX_MIGRATION_BYTES,
            error_type=public_catalog.CatalogDriftError,
        )
        first_line, separator, _rest = candidate_record.content.partition(b"\n")
        if not separator or not first_line.startswith(PUBLIC_INTENT_PREFIX):
            raise ReceiptVerificationError
        intent = public_catalog._decode_json(first_line[len(PUBLIC_INTENT_PREFIX) :])
        if (
            type(intent) is not dict
            or intent.get("scope") != "TENANT"
            or intent.get("operational_authorization") is not False
            or intent.get("next_stage_authorized") is not False
            or intent.get("migration_basename") != candidate.name
            or len(candidate_record.content) != candidate.size_bytes
            or hashlib.sha256(candidate_record.content).hexdigest() != append_sha
        ):
            raise ReceiptVerificationError
        return {
            "public_migration_count": len(entries),
            "public_digest_sha256": current_digest,
            "public_append_count": len(append),
            "public_append_last_basename": candidate.name,
            "public_append_last_sha256": append_sha,
        }
    except ReceiptVerificationError:
        raise
    except Exception as exc:
        raise ReceiptVerificationError from exc


def expected_receipt_lines(
    *,
    private_migration_count: int,
    private_digest_sha256: str,
    private_last_basename: str,
    private_last_sha256: str,
    public_migration_count: int = PUBLIC_CURRENT_COUNT,
    public_digest_sha256: str = DEFAULT_PUBLIC_DIGEST,
    public_append_count: int = PUBLIC_APPEND_COUNT,
    public_append_last_basename: str = DEFAULT_PUBLIC_APPEND_BASENAME,
    public_append_last_sha256: str = DEFAULT_PUBLIC_APPEND_SHA,
    source_git_sha: str = DEFAULT_SOURCE_GIT_SHA,
    composition_order: str = COMPOSITION_PUBLIC_APPEND_THEN_PRIVATE,
) -> tuple[str, ...]:
    """Build the closed receipt contract from authenticated source values."""

    if (
        type(private_migration_count) is not int
        or private_migration_count != 1
        or type(private_digest_sha256) is not str
        or SHA256_RE.fullmatch(private_digest_sha256) is None
        or type(private_last_basename) is not str
        or BASENAME_RE.fullmatch(private_last_basename) is None
        or type(private_last_sha256) is not str
        or SHA256_RE.fullmatch(private_last_sha256) is None
        or type(public_migration_count) is not int
        or public_migration_count != PUBLIC_CURRENT_COUNT
        or type(public_digest_sha256) is not str
        or SHA256_RE.fullmatch(public_digest_sha256) is None
        or public_digest_sha256 == HISTORICAL_DIGEST_SHA256
        or type(public_append_count) is not int
        or public_append_count != PUBLIC_APPEND_COUNT
        or type(public_append_last_basename) is not str
        or BASENAME_RE.fullmatch(public_append_last_basename) is None
        or public_append_last_basename <= HISTORICAL_LAST_BASENAME
        or type(public_append_last_sha256) is not str
        or SHA256_RE.fullmatch(public_append_last_sha256) is None
        or type(source_git_sha) is not str
        or GIT_SHA_RE.fullmatch(source_git_sha) is None
        or set(source_git_sha.casefold()) == {"0"}
        or composition_order not in COMPOSITION_ORDERS
    ):
        raise ReceiptVerificationError
    return EXPECTED_LINES_PREFIX + (
        f"PUBLIC_HISTORICAL_MIGRATION_COUNT={HISTORICAL_COUNT}",
        f"PUBLIC_HISTORICAL_DIGEST_SHA256={HISTORICAL_DIGEST_SHA256}",
        f"PUBLIC_HISTORICAL_LAST_BASENAME={HISTORICAL_LAST_BASENAME}",
        f"PUBLIC_CATALOG_MIGRATION_COUNT={public_migration_count}",
        f"PUBLIC_CATALOG_DIGEST_SHA256={public_digest_sha256}",
        f"PUBLIC_CATALOG_APPEND_COUNT={public_append_count}",
        f"PUBLIC_CATALOG_APPEND_LAST_BASENAME={public_append_last_basename}",
        f"PUBLIC_CATALOG_APPEND_LAST_SHA256={public_append_last_sha256}",
        f"PRIVATE_CATALOG_MIGRATION_COUNT={private_migration_count}",
        f"PRIVATE_CATALOG_DIGEST_SHA256={private_digest_sha256}",
        f"PRIVATE_CATALOG_LAST_BASENAME={private_last_basename}",
        f"PRIVATE_CATALOG_LAST_SHA256={private_last_sha256}",
        f"COMPOSITION_ORDER={composition_order}",
        f"SOURCE_GIT_SHA={source_git_sha.casefold()}",
        f"COMBINED_CATALOG_MIGRATION_COUNT={public_migration_count + private_migration_count}",
        "POSTGRESQL_MAJOR=17",
        "PG17_REPLAY_EXECUTED=true",
        "CROSS_TENANT_EVIDENCE=true",
        "DIRECT_SELECT_DENIED=true",
        "DML_DENIED=true",
        "CATALOG_DELTA_VERIFIED=true",
    )


def validate_receipt_bytes(raw: bytes, expected: Sequence[str]) -> None:
    """Require exact bytes, order, uniqueness, and closed receipt fields."""

    if type(raw) is not bytes or len(raw) < 1 or len(raw) > MAX_RECEIPT_BYTES:
        raise ReceiptVerificationError
    if not raw.endswith(b"\n") or b"\r" in raw or b"\x00" in raw:
        raise ReceiptVerificationError
    try:
        decoded = raw.decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise ReceiptVerificationError from exc
    lines = decoded.splitlines()
    if any(not line or line.strip() != line for line in lines):
        raise ReceiptVerificationError
    if len(lines) != len(set(lines)):
        raise ReceiptVerificationError
    if type(expected) not in {tuple, list} or not expected:
        raise ReceiptVerificationError
    if any(type(line) is not str or not line or line.strip() != line for line in expected):
        raise ReceiptVerificationError
    if len(expected) != len(set(expected)) or tuple(lines) != tuple(expected):
        raise ReceiptVerificationError


def _read_stable_receipt(path: Path, catalog: ModuleType) -> bytes:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or path == Path("/")
        or not path.name
        or "/" in path.name
    ):
        raise ReceiptVerificationError
    try:
        parent_fd = catalog._open_directory(path.parent)
    except Exception as exc:
        raise ReceiptVerificationError from exc
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
        descriptor = os.open(path.name, flags, dir_fd=parent_fd)
        before_parent = os.fstat(parent_fd)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size < 1
            or before.st_size > MAX_RECEIPT_BYTES
        ):
            raise ReceiptVerificationError
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise ReceiptVerificationError
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        after_parent = os.fstat(parent_fd)
        if (
            _stable_stat(before) != _stable_stat(after)
            or _stable_stat(before_parent) != _stable_stat(after_parent)
            or len(content) != before.st_size
        ):
            raise ReceiptVerificationError
        return content
    except (OSError, TypeError, ValueError) as exc:
        raise ReceiptVerificationError from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)


def _authenticated_expected_variants(
    catalog: ModuleType,
    *, _source_git_sha: str | None = None,
) -> tuple[tuple[str, ...], ...]:
    """Build exact receipts for both approved composition orders."""

    try:
        head = catalog.read_json(PRIVATE_HEAD_PATH)
        scanned = catalog.scan_directory(PRIVATE_DIRECTORY)
        entries = catalog.validate_head(head, scanned_entries=scanned)
    except Exception as exc:
        raise ReceiptVerificationError from exc
    if len(entries) != 1:
        raise ReceiptVerificationError
    current = head["current_head"]
    if type(current) is not dict:
        raise ReceiptVerificationError
    try:
        digest = current["private_digest_sha256"]
        count = current["private_migration_count"]
        last_name = current["last_basename"]
        entry = entries[-1]
        entry_name = entry["name"]
        entry_sha = entry["sha256"]
        if (
            count != len(entries)
            or entry_name != last_name
            or catalog.private_digest(entries) != digest
        ):
            raise ReceiptVerificationError
    except (KeyError, TypeError, IndexError) as exc:
        raise ReceiptVerificationError from exc
    public_snapshot = _load_public_snapshot()
    try:
        public_fields = _authenticated_public_fields(public_snapshot)
    finally:
        _unload_public_snapshot(public_snapshot)
    source_git_sha = _source_git_sha or _authenticated_source_git_sha()
    return tuple(
        expected_receipt_lines(
            private_migration_count=count,
            private_digest_sha256=digest,
            private_last_basename=last_name,
            private_last_sha256=entry_sha,
            source_git_sha=source_git_sha,
            composition_order=composition_order,
            **public_fields,
        )
        for composition_order in COMPOSITION_ORDERS
    )


def _authenticated_expected(catalog: ModuleType) -> tuple[str, ...]:
    """Return the first approved-order receipt for compatibility callers."""

    return _authenticated_expected_variants(catalog)[0]


def build_parser() -> argparse.ArgumentParser:
    parser = SanitizedArgumentParser(add_help=False)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--catalog-head", required=True)
    parser.add_argument("--private-directory", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if (
            args.catalog_head != PRIVATE_HEAD_RELATIVE
            or args.private_directory != PRIVATE_DIRECTORY_RELATIVE
        ):
            raise ReceiptVerificationError
        if not args.receipt or args.receipt != args.receipt.strip():
            raise ReceiptVerificationError
        sha = os.environ.get("GITHUB_SHA", "")
        if GIT_SHA_RE.fullmatch(sha) is None or set(sha) == {"0"}:
            raise ReceiptVerificationError
        authoring = _load_pinned_module(
            name="_pastorai_receipt_snapshot_authoring",
            path=REPO_ROOT / "backend/scripts/new_migration.py",
            expected_sha256="83abce96e63fe676e3088c225b1e29ae89268ce97d01727bc740fa2f50001bbe",
        )
        snapshot = authoring._create_repository_snapshot(repository_root=REPO_ROOT, git_sha=sha)
        try:
            if snapshot.git_sha != sha:
                raise ReceiptVerificationError
            # Resolve every expected field from the authenticated commit, not
            # from a mutable checkout accompanied by an unrelated SHA.
            child = '''import importlib.util, sys
path, sha, receipt = sys.argv[1:]
spec = importlib.util.spec_from_file_location("receipt_snapshot_child", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
try:
    catalog = module._load_private_catalog()
    expected = module._authenticated_expected_variants(catalog, _source_git_sha=sha)
    raw = module._read_stable_receipt(module.Path(receipt), catalog)
    if not any(raw == ("\\n".join(lines) + "\\n").encode("ascii") for lines in expected):
        raise module.ReceiptVerificationError
except Exception:
    raise SystemExit(4)
'''
            completed = subprocess.run(
                [sys.executable, "-I", "-B", "-c", child,
                 str(snapshot.repository / "backend/scripts/verify_private_runtime_pg17_receipt.py"),
                 sha, str(Path(args.receipt).absolute())],
                cwd=snapshot.repository,
                env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=120,
            )
            if completed.returncode != 0:
                raise ReceiptVerificationError
        finally:
            snapshot.cleanup()
    except ReceiptVerificationError:
        print("PRIVATE_RUNTIME_RECEIPT_INVALID", file=sys.stderr)
        return 4
    except Exception:
        print("PRIVATE_RUNTIME_RECEIPT_INVALID", file=sys.stderr)
        return 10
    print("PRIVATE_RUNTIME_RECEIPT_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
