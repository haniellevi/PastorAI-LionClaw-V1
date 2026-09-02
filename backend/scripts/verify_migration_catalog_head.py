#!/usr/bin/env python3
"""Verify the append-only migration catalog head without external effects.

This verifier reads only the two versioned contract files and the local SQL
catalog.  It never reads process configuration, invokes another process,
connects to a database, or uses the network.  A valid result is source-level
evidence only and keeps every operational gate closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
from typing import Any, NoReturn


REPO_ROOT = Path(__file__).absolute().parents[2]
GOVERNANCE_DIR = REPO_ROOT / "docs" / "governance" / "migrations"
HEAD_PATH = GOVERNANCE_DIR / "migration-catalog-head-v1.json"
SCHEMA_PATH = GOVERNANCE_DIR / "migration-catalog-head-v1.schema.json"
MIGRATIONS_DIR = REPO_ROOT / "backend" / "migrations"

ARTIFACT_ID = "migration-catalog-head-v1"
CONTRACT_VERSION = "1.0"
ARTIFACT_STATE = "OFFLINE_MIGRATION_CATALOG_HEAD_BLOCKED"
CATALOG_PATH = "backend/migrations"
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
MAX_JSON_DEPTH = 16
MAX_JSON_NODES = 100_000
MAX_JSON_STRING = 65_536

MIGRATION_BASENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.sql$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BATCH_ID_RE = re.compile(r"^migration-catalog-append-[0-9]{4}$")

VERIFIED_RESULT = "RESULT=MIGRATION_CATALOG_HEAD_VERIFIED_OFFLINE"
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
NEXT_STAGE_BLOCK = "NEXT_STAGE_AUTHORIZED=false"

TOP_LEVEL_KEYS = {
    "append_only_batches",
    "artifact_id",
    "artifact_state",
    "catalog_algorithm",
    "catalog_path",
    "contract_version",
    "current_head",
    "historical_prefix",
    "limits",
    "next_stage_authorized",
    "operational_authorization",
    "previous_approved_head_sha256",
}
ENTRY_KEYS = {"name", "position", "sha256", "size_bytes"}
BATCH_KEYS = {
    "batch_id",
    "entries",
    "previous_catalog_digest_sha256",
    "resulting_catalog_digest_sha256",
    "sequence",
}
HEAD_SUMMARY_KEYS = {"digest_sha256", "last_basename", "migration_count"}
HISTORICAL_PREFIX_KEYS = HEAD_SUMMARY_KEYS | {"entries"}
LIMITS = {
    "max_catalog_bytes": MAX_CATALOG_BYTES,
    "max_catalog_files": MAX_CATALOG_FILES,
    "max_migration_bytes": MAX_MIGRATION_BYTES,
    "max_migrations_per_batch": MAX_MIGRATIONS_PER_BATCH,
}


class VerificationError(RuntimeError):
    exit_code = 4
    reason = "CONTRACT_INVALID"


class UsageError(VerificationError):
    exit_code = 2
    reason = "USAGE"


class ArtifactIoError(VerificationError):
    exit_code = 3
    reason = "ARTIFACT_IO_INVALID"


class CatalogDriftError(VerificationError):
    exit_code = 5
    reason = "CATALOG_DRIFT"


@dataclass(frozen=True)
class FileSnapshot:
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
    def from_stat(cls, value: os.stat_result) -> "FileSnapshot":
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


@dataclass(frozen=True)
class StableFile:
    content: bytes
    file: FileSnapshot
    parent: FileSnapshot


@dataclass(frozen=True)
class OpenedDirectory:
    descriptor: int
    chain: tuple[FileSnapshot, ...]


@dataclass(frozen=True)
class StableInput:
    content: bytes
    file: FileSnapshot


@dataclass(frozen=True)
class ApprovedPriorHead:
    content_sha256: str
    head: dict[str, Any]


def _frame(tag: bytes, payload: bytes) -> bytes:
    if len(tag) != 1:
        raise VerificationError
    return tag + struct.pack(">Q", len(payload)) + payload


def _encode_framed(value: Any) -> bytes:
    if value is None:
        return _frame(b"N", b"")
    if type(value) is bool:
        return _frame(b"B", b"\x01" if value else b"\x00")
    if type(value) is int:
        return _frame(b"I", str(value).encode("ascii"))
    if type(value) is str:
        return _frame(b"S", value.encode("utf-8"))
    if type(value) is list:
        payload = struct.pack(">Q", len(value))
        payload += b"".join(_encode_framed(item) for item in value)
        return _frame(b"L", payload)
    if type(value) is dict:
        items: list[tuple[bytes, bytes]] = []
        for key, item in value.items():
            if type(key) is not str:
                raise VerificationError
            items.append((key.encode("utf-8"), _encode_framed(item)))
        items.sort(key=lambda pair: pair[0])
        payload = struct.pack(">Q", len(items))
        for key, encoded in items:
            payload += _frame(b"K", key) + encoded
        return _frame(b"O", payload)
    raise VerificationError


def _catalog_digest(entries: list[dict[str, Any]]) -> str:
    material = b"PASTORAI-MIGRATION-HISTORY\x00\x01"
    material += _frame(b"D", b"pastorai/migration-history/catalog/v1")
    material += _encode_framed(
        {"algorithm": CATALOG_ALGORITHM, "entries": entries}
    )
    return hashlib.sha256(material).hexdigest()


def _directory_flags() -> int:
    required = ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
    if any(not hasattr(os, name) for name in required):
        raise ArtifactIoError
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _read_flags() -> int:
    required = ("O_NOFOLLOW", "O_CLOEXEC", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required):
        raise ArtifactIoError
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def _open_directory(
    path: Path, error_type: type[VerificationError]
) -> OpenedDirectory:
    if not path.is_absolute() or any(
        component in {"", ".", ".."} for component in path.parts[1:]
    ):
        raise error_type
    try:
        descriptor = os.open(os.sep, _directory_flags())
    except (OSError, ValueError) as exc:
        raise error_type from exc
    try:
        chain = [FileSnapshot.from_stat(os.fstat(descriptor))]
        for component in path.parts[1:]:
            child = os.open(component, _directory_flags(), dir_fd=descriptor)
            try:
                opened = FileSnapshot.from_stat(os.fstat(child))
                named = FileSnapshot.from_stat(
                    os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                )
                if opened != named or not stat.S_ISDIR(opened.mode):
                    raise error_type
                chain.append(opened)
            except Exception:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        return OpenedDirectory(descriptor=descriptor, chain=tuple(chain))
    except Exception as exc:
        os.close(descriptor)
        if isinstance(exc, VerificationError):
            raise
        raise error_type from exc


def _verify_directory_chain(
    path: Path,
    expected: tuple[FileSnapshot, ...],
    error_type: type[VerificationError],
) -> None:
    reopened = _open_directory(path, error_type)
    try:
        if reopened.chain != expected:
            raise error_type
    finally:
        os.close(reopened.descriptor)


def _read_exact_file(
    descriptor: int,
    expected_size: int,
    maximum_size: int,
    error_type: type[VerificationError],
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            chunk = os.read(descriptor, min(65_536, maximum_size + 1 - total))
        except OSError as exc:
            raise error_type from exc
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum_size:
            raise error_type
    if total != expected_size:
        raise error_type
    return b"".join(chunks)


def _read_regular_at(
    directory_fd: int,
    basename: str,
    *,
    maximum_size: int,
    error_type: type[VerificationError],
) -> tuple[bytes, FileSnapshot]:
    try:
        descriptor = os.open(basename, _read_flags(), dir_fd=directory_fd)
    except (OSError, ValueError) as exc:
        raise error_type from exc
    try:
        before = FileSnapshot.from_stat(os.fstat(descriptor))
        if (
            not stat.S_ISREG(before.mode)
            or before.links != 1
            or before.size <= 0
            or before.size > maximum_size
        ):
            raise error_type
        content = _read_exact_file(
            descriptor, before.size, maximum_size, error_type
        )
        after = FileSnapshot.from_stat(os.fstat(descriptor))
        named = FileSnapshot.from_stat(
            os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
        )
        if before != after or before != named:
            raise error_type
        return content, before
    except OSError as exc:
        raise error_type from exc
    finally:
        os.close(descriptor)


def _read_stable_file(
    path: Path,
    *,
    maximum_size: int = MAX_JSON_BYTES,
    error_type: type[VerificationError] = ArtifactIoError,
) -> StableFile:
    opened = _open_directory(path.parent, error_type)
    directory_fd = opened.descriptor
    parent_before = opened.chain[-1]
    try:
        content, snapshot = _read_regular_at(
            directory_fd,
            path.name,
            maximum_size=maximum_size,
            error_type=error_type,
        )
        parent_after = FileSnapshot.from_stat(os.fstat(directory_fd))
        if parent_before != parent_after:
            raise error_type
        _verify_directory_chain(path.parent, opened.chain, error_type)
        return StableFile(content=content, file=snapshot, parent=parent_after)
    except OSError as exc:
        raise error_type from exc
    finally:
        os.close(directory_fd)


def _read_stable_fd(
    source_fd: int,
    *,
    maximum_size: int = MAX_JSON_BYTES,
) -> StableInput:
    if type(source_fd) is not int or source_fd < 3 or not hasattr(os, "pread"):
        raise ArtifactIoError
    try:
        descriptor = os.dup(source_fd)
    except (OSError, ValueError) as exc:
        raise ArtifactIoError from exc
    try:
        before = FileSnapshot.from_stat(os.fstat(descriptor))
        if (
            not stat.S_ISREG(before.mode)
            or before.links != 1
            or before.size <= 0
            or before.size > maximum_size
        ):
            raise ArtifactIoError
        chunks: list[bytes] = []
        offset = 0
        while offset < before.size:
            try:
                chunk = os.pread(
                    descriptor,
                    min(65_536, before.size - offset),
                    offset,
                )
            except OSError as exc:
                raise ArtifactIoError from exc
            if not chunk:
                raise ArtifactIoError
            chunks.append(chunk)
            offset += len(chunk)
        after = FileSnapshot.from_stat(os.fstat(descriptor))
        if before != after:
            raise ArtifactIoError
        return StableInput(content=b"".join(chunks), file=after)
    except OSError as exc:
        raise ArtifactIoError from exc
    finally:
        os.close(descriptor)


def _approved_prior_head(record: StableInput) -> ApprovedPriorHead:
    return ApprovedPriorHead(
        content_sha256=hashlib.sha256(record.content).hexdigest(),
        head=_decode_json(record.content),
    )


def _bounded_directory_listing(directory_fd: int) -> list[str]:
    names: list[str] = []
    try:
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                if len(names) >= MAX_CATALOG_FILES:
                    raise CatalogDriftError
                names.append(entry.name)
    except CatalogDriftError:
        raise
    except (OSError, ValueError) as exc:
        raise CatalogDriftError from exc
    return sorted(names)


def _scan_catalog(path: Path | None = None) -> list[dict[str, Any]]:
    catalog_path = MIGRATIONS_DIR if path is None else path
    opened = _open_directory(catalog_path, CatalogDriftError)
    directory_fd = opened.descriptor
    directory_before = opened.chain[-1]
    try:
        first_listing = _bounded_directory_listing(directory_fd)
        names = sorted(name for name in first_listing if name.endswith(".sql"))
        if not names or len(names) > MAX_CATALOG_FILES:
            raise CatalogDriftError
        if any(
            not name.isascii() or not MIGRATION_BASENAME_RE.fullmatch(name)
            for name in names
        ):
            raise CatalogDriftError
        if len(names) != len(set(names)) or len(names) != len(
            {name.casefold() for name in names}
        ):
            raise CatalogDriftError

        snapshots: dict[str, FileSnapshot] = {}
        total_size = 0
        for name in names:
            try:
                snapshot = FileSnapshot.from_stat(
                    os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                )
            except OSError as exc:
                raise CatalogDriftError from exc
            if (
                not stat.S_ISREG(snapshot.mode)
                or snapshot.links != 1
                or snapshot.size <= 0
                or snapshot.size > MAX_MIGRATION_BYTES
            ):
                raise CatalogDriftError
            total_size += snapshot.size
            if total_size > MAX_CATALOG_BYTES:
                raise CatalogDriftError
            snapshots[name] = snapshot

        entries: list[dict[str, Any]] = []
        for position, name in enumerate(names):
            content, snapshot = _read_regular_at(
                directory_fd,
                name,
                maximum_size=MAX_MIGRATION_BYTES,
                error_type=CatalogDriftError,
            )
            if snapshot != snapshots[name]:
                raise CatalogDriftError
            entries.append(
                {
                    "position": position,
                    "name": name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": snapshot.size,
                }
            )

        if _bounded_directory_listing(directory_fd) != first_listing:
            raise CatalogDriftError
        for name, expected in snapshots.items():
            actual = FileSnapshot.from_stat(
                os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            )
            if actual != expected:
                raise CatalogDriftError
        if FileSnapshot.from_stat(os.fstat(directory_fd)) != directory_before:
            raise CatalogDriftError
        _verify_directory_chain(
            catalog_path, opened.chain, CatalogDriftError
        )
        return entries
    except OSError as exc:
        raise CatalogDriftError from exc
    finally:
        os.close(directory_fd)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError
        result[key] = value
    return result


def _reject_number(_value: str) -> NoReturn:
    raise VerificationError


def _decode_json(content: bytes) -> dict[str, Any]:
    if not content or content.startswith(b"\xef\xbb\xbf"):
        raise VerificationError
    try:
        value = json.loads(
            content.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except VerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise VerificationError from exc
    stack: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise VerificationError
        if type(item) is str:
            if len(item) > MAX_JSON_STRING or not item.isascii():
                raise VerificationError
        elif type(item) is list:
            stack.extend((nested, depth + 1) for nested in item)
        elif type(item) is dict:
            if any(type(key) is not str for key in item):
                raise VerificationError
            stack.extend((nested, depth + 1) for nested in item.values())
        elif item is not None and type(item) not in (bool, int):
            raise VerificationError
    if type(value) is not dict:
        raise VerificationError
    return value


def _exact_json(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return set(actual) == set(expected) and all(
            _exact_json(actual[key], value) for key, value in expected.items()
        )
    if type(expected) is list:
        return len(actual) == len(expected) and all(
            _exact_json(item, expected_item)
            for item, expected_item in zip(actual, expected, strict=True)
        )
    return actual == expected


def _require_exact(actual: Any, expected: Any) -> None:
    if not _exact_json(actual, expected):
        raise VerificationError


def _entry_schema() -> dict[str, Any]:
    return {
        "additionalProperties": False,
        "properties": {
            "name": {
                "maxLength": 255,
                "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.sql$",
                "type": "string",
            },
            "position": {
                "maximum": MAX_CATALOG_FILES - 1,
                "minimum": 0,
                "type": "integer",
            },
            "sha256": {
                "pattern": "^[0-9a-f]{64}$",
                "type": "string",
            },
            "size_bytes": {
                "maximum": MAX_MIGRATION_BYTES,
                "minimum": 1,
                "type": "integer",
            },
        },
        "required": sorted(ENTRY_KEYS),
        "type": "object",
    }


def _head_summary_schema() -> dict[str, Any]:
    return {
        "additionalProperties": False,
        "properties": {
            "digest_sha256": {
                "pattern": "^[0-9a-f]{64}$",
                "type": "string",
            },
            "last_basename": {
                "maxLength": 255,
                "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.sql$",
                "type": "string",
            },
            "migration_count": {
                "maximum": MAX_CATALOG_FILES,
                "minimum": HISTORICAL_COUNT,
                "type": "integer",
            },
        },
        "required": sorted(HEAD_SUMMARY_KEYS),
        "type": "object",
    }


def _expected_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://igreja12.invalid/schemas/migration-catalog-head-v1.json"
        ),
        "$defs": {
            "append_batch": {
                "additionalProperties": False,
                "properties": {
                    "batch_id": {
                        "pattern": r"^migration-catalog-append-[0-9]{4}$",
                        "type": "string",
                    },
                    "entries": {
                        "items": {"$ref": "#/$defs/migration_entry"},
                        "maxItems": MAX_MIGRATIONS_PER_BATCH,
                        "minItems": MAX_MIGRATIONS_PER_BATCH,
                        "type": "array",
                    },
                    "previous_catalog_digest_sha256": {
                        "pattern": "^[0-9a-f]{64}$",
                        "type": "string",
                    },
                    "resulting_catalog_digest_sha256": {
                        "pattern": "^[0-9a-f]{64}$",
                        "type": "string",
                    },
                    "sequence": {
                        "maximum": MAX_CATALOG_FILES - HISTORICAL_COUNT,
                        "minimum": 1,
                        "type": "integer",
                    },
                },
                "required": sorted(BATCH_KEYS),
                "type": "object",
            },
            "current_head": _head_summary_schema(),
            "migration_entry": _entry_schema(),
        },
        "additionalProperties": False,
        "properties": {
            "append_only_batches": {
                "items": {"$ref": "#/$defs/append_batch"},
                "maxItems": MAX_CATALOG_FILES - HISTORICAL_COUNT,
                "type": "array",
            },
            "artifact_id": {"const": ARTIFACT_ID},
            "artifact_state": {"const": ARTIFACT_STATE},
            "catalog_algorithm": {"const": CATALOG_ALGORITHM},
            "catalog_path": {"const": CATALOG_PATH},
            "contract_version": {"const": CONTRACT_VERSION},
            "current_head": {"$ref": "#/$defs/current_head"},
            "historical_prefix": {
                "additionalProperties": False,
                "properties": {
                    "digest_sha256": {"const": HISTORICAL_DIGEST_SHA256},
                    "entries": {
                        "items": {"$ref": "#/$defs/migration_entry"},
                        "maxItems": HISTORICAL_COUNT,
                        "minItems": HISTORICAL_COUNT,
                        "type": "array",
                    },
                    "last_basename": {"const": HISTORICAL_LAST_BASENAME},
                    "migration_count": {"const": HISTORICAL_COUNT},
                },
                "required": sorted(HISTORICAL_PREFIX_KEYS),
                "type": "object",
            },
            "limits": {
                "additionalProperties": False,
                "properties": {
                    key: {"const": value} for key, value in LIMITS.items()
                },
                "required": sorted(LIMITS),
                "type": "object",
            },
            "next_stage_authorized": {"const": False},
            "operational_authorization": {"const": False},
            "previous_approved_head_sha256": {
                "description": (
                    "SHA-256 of independently supplied prior head bytes; "
                    "evidence only and never operational authorization."
                ),
                "oneOf": [
                    {"type": "null"},
                    {
                        "pattern": "^[0-9a-f]{64}$",
                        "type": "string",
                    },
                ]
            },
        },
        "required": sorted(TOP_LEVEL_KEYS),
        "title": "Migration catalog append-only head v1",
        "type": "object",
    }


def _validate_entry(
    entry: Any,
    *,
    expected_position: int,
) -> dict[str, Any]:
    if type(entry) is not dict or set(entry) != ENTRY_KEYS:
        raise VerificationError
    position = entry["position"]
    name = entry["name"]
    digest = entry["sha256"]
    size = entry["size_bytes"]
    if type(position) is not int or position != expected_position:
        raise VerificationError
    if (
        type(name) is not str
        or len(name) > 255
        or not name.isascii()
        or not MIGRATION_BASENAME_RE.fullmatch(name)
    ):
        raise VerificationError
    if type(digest) is not str or not SHA256_RE.fullmatch(digest):
        raise VerificationError
    if (
        type(size) is not int
        or size < 1
        or size > MAX_MIGRATION_BYTES
    ):
        raise VerificationError
    return {
        "position": position,
        "name": name,
        "sha256": digest,
        "size_bytes": size,
    }


def _validate_entries(entries: Any, *, expected_start: int) -> list[dict[str, Any]]:
    if type(entries) is not list:
        raise VerificationError
    validated = [
        _validate_entry(entry, expected_position=expected_start + offset)
        for offset, entry in enumerate(entries)
    ]
    names = [entry["name"] for entry in validated]
    if names != sorted(names):
        raise VerificationError
    if len(names) != len(set(names)) or len(names) != len(
        {name.casefold() for name in names}
    ):
        raise VerificationError
    return validated


def validate_head(
    head: dict[str, Any],
    *,
    scanned_catalog: list[dict[str, Any]] | None = None,
    approved_prior: ApprovedPriorHead | None = None,
    _approved_snapshot: bool = False,
) -> list[dict[str, Any]]:
    """Validate and reconstruct every catalog entry represented by the head."""

    if type(head) is not dict or set(head) != TOP_LEVEL_KEYS:
        raise VerificationError
    _require_exact(head["artifact_id"], ARTIFACT_ID)
    _require_exact(head["artifact_state"], ARTIFACT_STATE)
    _require_exact(head["catalog_algorithm"], CATALOG_ALGORITHM)
    _require_exact(head["catalog_path"], CATALOG_PATH)
    _require_exact(head["contract_version"], CONTRACT_VERSION)
    _require_exact(head["limits"], LIMITS)
    if head["operational_authorization"] is not False:
        raise VerificationError
    if head["next_stage_authorized"] is not False:
        raise VerificationError

    historical = head["historical_prefix"]
    if type(historical) is not dict or set(historical) != HISTORICAL_PREFIX_KEYS:
        raise VerificationError
    if type(historical["migration_count"]) is not int:
        raise VerificationError
    if historical["migration_count"] != HISTORICAL_COUNT:
        raise VerificationError
    if historical["digest_sha256"] != HISTORICAL_DIGEST_SHA256:
        raise VerificationError
    if historical["last_basename"] != HISTORICAL_LAST_BASENAME:
        raise VerificationError
    entries = _validate_entries(historical["entries"], expected_start=0)
    if len(entries) != HISTORICAL_COUNT:
        raise VerificationError
    if entries[-1]["name"] != HISTORICAL_LAST_BASENAME:
        raise VerificationError
    if _catalog_digest(entries) != HISTORICAL_DIGEST_SHA256:
        raise VerificationError

    batches = head["append_only_batches"]
    if type(batches) is not list or len(batches) > (
        MAX_CATALOG_FILES - HISTORICAL_COUNT
    ):
        raise VerificationError
    prior_anchor = head["previous_approved_head_sha256"]
    if not batches:
        if prior_anchor is not None:
            raise VerificationError
    elif type(prior_anchor) is not str or not SHA256_RE.fullmatch(prior_anchor):
        raise VerificationError
    reconstructed = list(entries)
    known_names = {entry["name"] for entry in reconstructed}
    known_casefold = {name.casefold() for name in known_names}
    previous_digest = HISTORICAL_DIGEST_SHA256
    previous_name = HISTORICAL_LAST_BASENAME
    for sequence, batch in enumerate(batches, start=1):
        if type(batch) is not dict or set(batch) != BATCH_KEYS:
            raise VerificationError
        if type(batch["sequence"]) is not int or batch["sequence"] != sequence:
            raise VerificationError
        expected_batch_id = f"migration-catalog-append-{sequence:04d}"
        if (
            type(batch["batch_id"]) is not str
            or not BATCH_ID_RE.fullmatch(batch["batch_id"])
            or batch["batch_id"] != expected_batch_id
        ):
            raise VerificationError
        if batch["previous_catalog_digest_sha256"] != previous_digest:
            raise VerificationError
        additions = batch["entries"]
        if type(additions) is not list or len(additions) != 1:
            raise VerificationError
        addition = _validate_entry(
            additions[0], expected_position=len(reconstructed)
        )
        name = addition["name"]
        if (
            name <= previous_name
            or name in known_names
            or name.casefold() in known_casefold
        ):
            raise VerificationError
        reconstructed.append(addition)
        known_names.add(name)
        known_casefold.add(name.casefold())
        resulting_digest = _catalog_digest(reconstructed)
        if batch["resulting_catalog_digest_sha256"] != resulting_digest:
            raise VerificationError
        previous_digest = resulting_digest
        previous_name = name

    total_declared = sum(entry["size_bytes"] for entry in reconstructed)
    if len(reconstructed) > MAX_CATALOG_FILES or total_declared > MAX_CATALOG_BYTES:
        raise VerificationError
    current = head["current_head"]
    if type(current) is not dict or set(current) != HEAD_SUMMARY_KEYS:
        raise VerificationError
    expected_current = {
        "migration_count": len(reconstructed),
        "last_basename": previous_name,
        "digest_sha256": previous_digest,
    }
    _require_exact(current, expected_current)
    if not _approved_snapshot:
        if batches:
            if type(approved_prior) is not ApprovedPriorHead:
                raise VerificationError
            if prior_anchor != approved_prior.content_sha256:
                raise VerificationError
            validate_head(
                approved_prior.head,
                _approved_snapshot=True,
            )
            approved_batches = approved_prior.head["append_only_batches"]
            if len(batches) != len(approved_batches) + 1:
                raise VerificationError
            if not _exact_json(
                head["historical_prefix"],
                approved_prior.head["historical_prefix"],
            ):
                raise VerificationError
            if not _exact_json(batches[:-1], approved_batches):
                raise VerificationError
        elif approved_prior is not None:
            raise VerificationError
    if scanned_catalog is not None and not _exact_json(
        scanned_catalog, reconstructed
    ):
        raise CatalogDriftError
    return reconstructed


def verify_versioned_head(
    *, approved_prior: ApprovedPriorHead | None = None
) -> dict[str, Any]:
    head_record = _read_stable_file(HEAD_PATH)
    schema_record = _read_stable_file(SCHEMA_PATH)
    head = _decode_json(head_record.content)
    schema = _decode_json(schema_record.content)
    _require_exact(schema, _expected_schema())
    scanned = _scan_catalog()
    validate_head(
        head,
        scanned_catalog=scanned,
        approved_prior=approved_prior,
    )
    if _read_stable_file(HEAD_PATH) != head_record:
        raise ArtifactIoError
    if _read_stable_file(SCHEMA_PATH) != schema_record:
        raise ArtifactIoError
    return head


def _validated_snapshot_for_historical_consumers(
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return one stable local snapshot without approving a new catalog head.

    Historical consumers need to prove that their immutable 75-file prefix is
    still present even after the current catalog grows.  They must not turn
    that compatibility check into approval of a newly appended batch.  This
    helper therefore validates the complete local chain and its exact match to
    the directory, while deliberately skipping only the longitudinal
    ``approved_prior`` proof owned by :func:`verify_versioned_head`.

    The returned data is suitable only for read-only historical verification.
    It never changes the two closed authorization fields in the head artifact.
    """

    head_record = _read_stable_file(HEAD_PATH)
    schema_record = _read_stable_file(SCHEMA_PATH)
    head = _decode_json(head_record.content)
    schema = _decode_json(schema_record.content)
    _require_exact(schema, _expected_schema())
    scanned = _scan_catalog()
    reconstructed = validate_head(
        head,
        scanned_catalog=scanned,
        _approved_snapshot=True,
    )
    if _read_stable_file(HEAD_PATH) != head_record:
        raise ArtifactIoError
    if _read_stable_file(SCHEMA_PATH) != schema_record:
        raise ArtifactIoError
    return head, reconstructed


def _prior_from_cli(
    args: list[str],
) -> tuple[ApprovedPriorHead | None, StableInput | None, int | None]:
    if not args:
        return None, None, None
    if (
        len(args) != 2
        or args[0] != "--prior-head-fd"
        or not re.fullmatch(r"[0-9]{1,7}", args[1])
    ):
        raise UsageError
    descriptor = int(args[1], 10)
    if descriptor < 3 or descriptor > 1_000_000:
        raise UsageError
    record = _read_stable_fd(descriptor)
    return _approved_prior_head(record), record, descriptor


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        approved_prior, prior_record, prior_fd = _prior_from_cli(args)
        head = verify_versioned_head(approved_prior=approved_prior)
        if (
            prior_fd is not None
            and _read_stable_fd(prior_fd) != prior_record
        ):
            raise ArtifactIoError
    except VerificationError as exc:
        print(f"RESULT=BLOCKED_MIGRATION_CATALOG_HEAD:{exc.reason}")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return exc.exit_code
    except Exception:
        print("RESULT=BLOCKED_MIGRATION_CATALOG_HEAD:INTERNAL_ERROR")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return 10
    print(VERIFIED_RESULT)
    print(f"CATALOG_MIGRATION_COUNT={head['current_head']['migration_count']}")
    print(f"CATALOG_DIGEST_SHA256={head['current_head']['digest_sha256']}")
    print(OPERATIONAL_BLOCK)
    print(NEXT_STAGE_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
