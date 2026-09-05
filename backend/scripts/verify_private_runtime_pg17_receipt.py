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
PRIVATE_HEAD_RELATIVE = "docs/governance/migrations/private-runtime-catalog-head-v1.json"
PRIVATE_DIRECTORY_RELATIVE = "backend/migrations/private_runtime"
PRIVATE_HEAD_PATH = REPO_ROOT / PRIVATE_HEAD_RELATIVE
PRIVATE_DIRECTORY = REPO_ROOT / PRIVATE_DIRECTORY_RELATIVE
MAX_LOCAL_MODULE_BYTES = 4_194_304
MAX_RECEIPT_BYTES = 16_384
HISTORICAL_COUNT = 75
HISTORICAL_DIGEST_SHA256 = (
    "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f"
)
EXPECTED_RESULT = "RESULT=PRIVATE_RUNTIME_PROJECTION_REPLAYED_PG17_DISPOSABLE"
EXPECTED_LINES_PREFIX = (
    "OPERATIONAL_AUTHORIZATION=BLOCKED",
    "NEXT_STAGE_AUTHORIZED=false",
    "SHARED_ENVIRONMENT_ATTESTATION=false",
    EXPECTED_RESULT,
    "PUBLIC_CATALOG_MIGRATION_COUNT=75",
    f"PUBLIC_CATALOG_DIGEST_SHA256={HISTORICAL_DIGEST_SHA256}",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BASENAME_RE = re.compile(
    r"^[0-9]{8}_[0-9]{6}_[a-z][a-z0-9_]{0,119}\.sql$"
)


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


def expected_receipt_lines(
    *,
    private_migration_count: int,
    private_digest_sha256: str,
    private_last_basename: str,
    private_last_sha256: str,
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
    ):
        raise ReceiptVerificationError
    return EXPECTED_LINES_PREFIX + (
        "PRIVATE_CATALOG_MIGRATION_COUNT=1",
        f"PRIVATE_CATALOG_DIGEST_SHA256={private_digest_sha256}",
        f"PRIVATE_CATALOG_LAST_BASENAME={private_last_basename}",
        f"PRIVATE_CATALOG_LAST_SHA256={private_last_sha256}",
        "COMBINED_CATALOG_MIGRATION_COUNT=76",
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


def _authenticated_expected(catalog: ModuleType) -> tuple[str, ...]:
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
    return expected_receipt_lines(
        private_migration_count=count,
        private_digest_sha256=digest,
        private_last_basename=last_name,
        private_last_sha256=entry_sha,
    )


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
        catalog = _load_private_catalog()
        expected = _authenticated_expected(catalog)
        validate_receipt_bytes(
            _read_stable_receipt(Path(args.receipt).absolute(), catalog), expected
        )
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
