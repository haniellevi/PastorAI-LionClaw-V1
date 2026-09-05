#!/usr/bin/env python3
"""Closed append-only manifest for private-runtime migrations.

The public ``migration-catalog-head-v1`` is intentionally left untouched.  A
private-runtime suffix lives under its own directory and is anchored to the
public catalog's immutable 75-migration digest.  This module verifies only
that suffix; callers still have to run the historical V1 verifier separately
and the PG17 replay before treating an append as executable evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any


REPO_ROOT = Path(__file__).absolute().parents[2]
GOVERNANCE_DIR = REPO_ROOT / "docs" / "governance" / "migrations"
HEAD_PATH = GOVERNANCE_DIR / "private-runtime-catalog-head-v1.json"
SCHEMA_PATH = GOVERNANCE_DIR / "private-runtime-catalog-head-v1.schema.json"
MIGRATIONS_DIR = REPO_ROOT / "backend" / "migrations" / "private_runtime"

ARTIFACT_ID = "private-runtime-catalog-head-v1"
CONTRACT_VERSION = "1.0"
ARTIFACT_STATE = "OFFLINE_PRIVATE_RUNTIME_CATALOG_HEAD_BLOCKED"
CATALOG_PATH = "backend/migrations/private_runtime"
CATALOG_ALGORITHM = "basename-ascii-ascending+sha256-raw-bytes-v1"
HISTORICAL_COUNT = 75
HISTORICAL_DIGEST_SHA256 = (
    "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f"
)
HISTORICAL_LAST_BASENAME = (
    "20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql"
)
MAX_JSON_BYTES = 1_048_576
MAX_CATALOG_FILES = 2_048
MAX_MIGRATION_BYTES = 4_194_304
MAX_CATALOG_BYTES = 67_108_864
MAX_MIGRATIONS_PER_BATCH = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MIGRATION_BASENAME_RE = re.compile(
    r"^[0-9]{8}_[0-9]{6}_[a-z][a-z0-9_]{0,119}\.sql$"
)
BATCH_ID_RE = re.compile(r"^private-runtime-catalog-append-[0-9]{4}$")
_STABLE_STAT_FIELDS = (
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

TOP_LEVEL_KEYS = {
    "append_only_batches",
    "artifact_id",
    "artifact_state",
    "catalog_algorithm",
    "catalog_path",
    "contract_version",
    "current_head",
    "historical_public_catalog_digest_sha256",
    "historical_public_last_basename",
    "historical_public_migration_count",
    "limits",
    "next_stage_authorized",
    "operational_authorization",
    "private_entries",
}
ENTRY_KEYS = {"name", "position", "sha256", "size_bytes"}
BATCH_KEYS = {
    "batch_id",
    "entries",
    "previous_private_digest_sha256",
    "resulting_private_digest_sha256",
    "sequence",
}
HEAD_SUMMARY_KEYS = {
    "last_basename",
    "private_digest_sha256",
    "private_migration_count",
}
LIMIT_KEYS = {
    "max_catalog_bytes",
    "max_catalog_files",
    "max_migration_bytes",
    "max_migrations_per_batch",
}


class PrivateRuntimeCatalogError(RuntimeError):
    """Raised for a malformed, drifting, or unauthorised private manifest."""


@dataclass(frozen=True)
class FileEntry:
    position: int
    name: str
    sha256: str
    size_bytes: int


def _catalog_io_error() -> PrivateRuntimeCatalogError:
    return PrivateRuntimeCatalogError("private catalog source is not stable")


def _stable_stat(before: os.stat_result, after: os.stat_result) -> bool:
    return all(
        getattr(before, field) == getattr(after, field)
        for field in _STABLE_STAT_FIELDS
    )


def _open_directory(path: Path) -> int:
    """Open every absolute path component with O_NOFOLLOW."""

    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or path == Path("/")
        or any(part in {"", ".", ".."} for part in path.parts[1:])
        or any(
            not hasattr(os, flag)
            for flag in ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW")
        )
    ):
        raise _catalog_io_error()
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open("/", flags)
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise _catalog_io_error()
        return descriptor
    except PrivateRuntimeCatalogError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except (OSError, TypeError, ValueError) as exc:
        if descriptor is not None:
            os.close(descriptor)
        if isinstance(exc, PrivateRuntimeCatalogError):
            raise
        raise _catalog_io_error() from exc


def _read_stable_fd(directory_fd: int, name: str) -> bytes:
    """Read one direct child through a no-follow descriptor."""

    if (
        type(name) is not str
        or not name
        or "/" in name
        or any(
            not hasattr(os, flag)
            for flag in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK")
        )
    ):
        raise _catalog_io_error()
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor: int | None = None
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > MAX_MIGRATION_BYTES
        ):
            raise _catalog_io_error()
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise _catalog_io_error()
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if not _stable_stat(before, after) or len(content) != before.st_size:
            raise _catalog_io_error()
        return content
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, PrivateRuntimeCatalogError):
            raise
        raise _catalog_io_error() from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def read_json(path: Path) -> dict[str, object]:
    """Read a governance JSON object with stable-file guarantees."""

    if not isinstance(path, Path) or not path.is_absolute() or "/" in path.name:
        raise _catalog_io_error()
    content = read_file(path)
    if len(content) > MAX_JSON_BYTES:
        raise _catalog_io_error()
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _catalog_io_error() from exc
    if type(value) is not dict:
        raise PrivateRuntimeCatalogError("private catalog JSON is not an object")
    return value


def read_file(path: Path) -> bytes:
    """Read one absolute file through a stable, no-follow parent descriptor."""

    if not isinstance(path, Path) or not path.is_absolute() or "/" in path.name:
        raise _catalog_io_error()
    directory_fd = _open_directory(path.parent)
    try:
        before = os.fstat(directory_fd)
        content = _read_stable_fd(directory_fd, path.name)
        after = os.fstat(directory_fd)
        if not _stable_stat(before, after):
            raise _catalog_io_error()
    finally:
        os.close(directory_fd)
    return content


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def private_digest(entries: list[dict[str, Any]]) -> str:
    """Hash canonical private entries without incorporating filesystem paths."""

    encoded = json.dumps(
        entries,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return _sha256(encoded)


def default_head() -> dict[str, object]:
    return {
        "append_only_batches": [],
        "artifact_id": ARTIFACT_ID,
        "artifact_state": ARTIFACT_STATE,
        "catalog_algorithm": CATALOG_ALGORITHM,
        "catalog_path": CATALOG_PATH,
        "contract_version": CONTRACT_VERSION,
        "current_head": {
            "last_basename": HISTORICAL_LAST_BASENAME,
            "private_digest_sha256": private_digest([]),
            "private_migration_count": 0,
        },
        "historical_public_catalog_digest_sha256": HISTORICAL_DIGEST_SHA256,
        "historical_public_last_basename": HISTORICAL_LAST_BASENAME,
        "historical_public_migration_count": HISTORICAL_COUNT,
        "limits": {
            "max_catalog_bytes": MAX_CATALOG_BYTES,
            "max_catalog_files": MAX_CATALOG_FILES,
            "max_migration_bytes": MAX_MIGRATION_BYTES,
            "max_migrations_per_batch": MAX_MIGRATIONS_PER_BATCH,
        },
        "next_stage_authorized": False,
        "operational_authorization": False,
        "private_entries": [],
    }


def _exact(value: object, expected: object) -> None:
    if value != expected:
        raise PrivateRuntimeCatalogError("private catalog value is not exact")


def _entry(value: object, expected_position: int) -> dict[str, Any]:
    if type(value) is not dict or set(value) != ENTRY_KEYS:
        raise PrivateRuntimeCatalogError("private catalog entry is not closed")
    if (
        type(value["position"]) is not int
        or value["position"] != expected_position
        or type(value["name"]) is not str
        or MIGRATION_BASENAME_RE.fullmatch(value["name"]) is None
        or type(value["sha256"]) is not str
        or SHA256_RE.fullmatch(value["sha256"]) is None
        or type(value["size_bytes"]) is not int
        or value["size_bytes"] <= 0
        or value["size_bytes"] > MAX_MIGRATION_BYTES
    ):
        raise PrivateRuntimeCatalogError("private catalog entry is invalid")
    return value


def validate_head(
    head: object,
    *,
    scanned_entries: list[dict[str, Any]] | None = None,
    approved_prior: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Validate one private head and optionally its exact directory scan."""

    if type(head) is not dict or set(head) != TOP_LEVEL_KEYS:
        raise PrivateRuntimeCatalogError("private catalog head is not closed")
    _exact(head["artifact_id"], ARTIFACT_ID)
    _exact(head["artifact_state"], ARTIFACT_STATE)
    _exact(head["catalog_algorithm"], CATALOG_ALGORITHM)
    _exact(head["catalog_path"], CATALOG_PATH)
    _exact(head["contract_version"], CONTRACT_VERSION)
    _exact(head["historical_public_catalog_digest_sha256"], HISTORICAL_DIGEST_SHA256)
    _exact(head["historical_public_last_basename"], HISTORICAL_LAST_BASENAME)
    _exact(head["historical_public_migration_count"], HISTORICAL_COUNT)
    if head["operational_authorization"] is not False or head["next_stage_authorized"] is not False:
        raise PrivateRuntimeCatalogError("private catalog gates are open")
    limits = head["limits"]
    if type(limits) is not dict or set(limits) != LIMIT_KEYS:
        raise PrivateRuntimeCatalogError("private catalog limits are not closed")
    _exact(
        limits,
        {
            "max_catalog_bytes": MAX_CATALOG_BYTES,
            "max_catalog_files": MAX_CATALOG_FILES,
            "max_migration_bytes": MAX_MIGRATION_BYTES,
            "max_migrations_per_batch": MAX_MIGRATIONS_PER_BATCH,
        },
    )
    raw_entries = head["private_entries"]
    if type(raw_entries) is not list or len(raw_entries) > MAX_CATALOG_FILES:
        raise PrivateRuntimeCatalogError("private catalog entries are invalid")
    entries = [_entry(value, index) for index, value in enumerate(raw_entries)]
    names = [entry["name"] for entry in entries]
    if names != sorted(names) or len(names) != len(set(names)):
        raise PrivateRuntimeCatalogError("private catalog order is invalid")
    if sum(entry["size_bytes"] for entry in entries) > MAX_CATALOG_BYTES:
        raise PrivateRuntimeCatalogError("private catalog is too large")

    batches = head["append_only_batches"]
    if type(batches) is not list or len(batches) > MAX_CATALOG_FILES:
        raise PrivateRuntimeCatalogError("private append batches are invalid")
    reconstructed: list[dict[str, Any]] = []
    known_names: set[str] = set()
    previous_digest = private_digest([])
    previous_name = HISTORICAL_LAST_BASENAME
    for sequence, batch in enumerate(batches, start=1):
        if type(batch) is not dict or set(batch) != BATCH_KEYS:
            raise PrivateRuntimeCatalogError("private append batch is not closed")
        if (
            type(batch["batch_id"]) is not str
            or BATCH_ID_RE.fullmatch(batch["batch_id"]) is None
            or batch["sequence"] != sequence
            or batch["previous_private_digest_sha256"] != previous_digest
        ):
            raise PrivateRuntimeCatalogError("private append sequence is invalid")
        batch_entries = batch["entries"]
        if type(batch_entries) is not list or len(batch_entries) != MAX_MIGRATIONS_PER_BATCH:
            raise PrivateRuntimeCatalogError("private append batch size is invalid")
        for raw_entry in batch_entries:
            if type(raw_entry) is not dict:
                raise PrivateRuntimeCatalogError("private append entry is invalid")
            entry = _entry(raw_entry, len(reconstructed))
            if entry["name"] <= previous_name or entry["name"] in known_names:
                raise PrivateRuntimeCatalogError("private append order is invalid")
            reconstructed.append(entry)
            known_names.add(entry["name"])
            previous_name = entry["name"]
        resulting = private_digest(reconstructed)
        if batch["resulting_private_digest_sha256"] != resulting:
            raise PrivateRuntimeCatalogError("private append digest is invalid")
        previous_digest = resulting

    # The manifest's flat entry list is the source of current truth.  It must
    # equal the append reconstruction, including the empty initial suffix.
    _exact(entries, reconstructed)
    current = head["current_head"]
    if type(current) is not dict or set(current) != HEAD_SUMMARY_KEYS:
        raise PrivateRuntimeCatalogError("private current head is not closed")
    _exact(
        current,
        {
            "last_basename": previous_name,
            "private_digest_sha256": previous_digest,
            "private_migration_count": len(reconstructed),
        },
    )
    if approved_prior is not None:
        if type(approved_prior) is not dict:
            raise PrivateRuntimeCatalogError("private prior head is invalid")
        prior_entries = validate_head(approved_prior)
        prior_batches = approved_prior["append_only_batches"]
        if (
            type(prior_batches) is not list
            or len(entries) < len(prior_entries)
            or entries[: len(prior_entries)] != prior_entries
            or len(batches) < len(prior_batches)
            or batches[: len(prior_batches)] != prior_batches
        ):
            raise PrivateRuntimeCatalogError(
                "private catalog evolution is not append-only"
            )
        if (
            len(entries) == len(prior_entries)
            and (
                current != approved_prior["current_head"]
                or len(batches) != len(prior_batches)
            )
        ):
            raise PrivateRuntimeCatalogError(
                "private catalog changed without an append"
            )
    if scanned_entries is not None:
        if scanned_entries != entries:
            raise PrivateRuntimeCatalogError("private catalog directory drifted")
    return entries


def scan_directory(path: Path = MIGRATIONS_DIR) -> list[dict[str, Any]]:
    """Scan direct private SQL files through stable no-follow descriptors."""

    directory_fd = _open_directory(path)
    try:
        directory_before = os.fstat(directory_fd)
        names = sorted(os.listdir(directory_fd))
        # Do not silently ignore an unexpected file.  A non-SQL payload (or a
        # symlink whose suffix is not ``.sql``) could otherwise sit beside the
        # reviewed stream and evade the manifest comparison.
        if len(names) > MAX_CATALOG_FILES or any(
            MIGRATION_BASENAME_RE.fullmatch(name) is None for name in names
        ):
            raise PrivateRuntimeCatalogError("private migration directory is invalid")
        entries: list[dict[str, Any]] = []
        total_bytes = 0
        for position, name in enumerate(names):
            content = _read_stable_fd(directory_fd, name)
            total_bytes += len(content)
            if total_bytes > MAX_CATALOG_BYTES:
                raise PrivateRuntimeCatalogError("private catalog is too large")
            entries.append(
                {
                    "position": position,
                    "name": name,
                    "sha256": _sha256(content),
                    "size_bytes": len(content),
                }
            )
        directory_after = os.fstat(directory_fd)
        names_after = sorted(
            name for name in os.listdir(directory_fd) if name.endswith(".sql")
        )
        if (
            not _stable_stat(directory_before, directory_after)
            or names_after != names
        ):
            raise _catalog_io_error()
        return entries
    except OSError as exc:
        raise _catalog_io_error() from exc
    finally:
        os.close(directory_fd)
