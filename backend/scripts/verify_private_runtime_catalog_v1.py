#!/usr/bin/env python3
"""Verify the source contract for the separate private-runtime stream.

This verifier is intentionally narrower than a replay runner.  It proves that
the private head is closed, append-only, bound to the byte-pinned public
75-migration history, and that every referenced candidate is a V2 private
candidate.  It does *not* prove PostgreSQL ACL/RLS behaviour; the PG17 replay
must perform that check before this stream is treated as executable evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType


REPO_ROOT = Path(__file__).absolute().parents[2]
PRIVATE_HEAD_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "private-runtime-catalog-head-v1.json"
)
PRIVATE_SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "private-runtime-catalog-head-v1.schema.json"
)
PRIVATE_MIGRATIONS_DIR = REPO_ROOT / "backend" / "migrations" / "private_runtime"
HISTORICAL_COUNT = 75
HISTORICAL_DIGEST_SHA256 = (
    "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f"
)
HISTORICAL_LAST_BASENAME = (
    "20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql"
)
MAX_PUBLIC_APPEND_BATCHES = 1
PUBLIC_INTENT_PREFIX = b"-- PASTORAI_MIGRATION_INTENT_V1="
VERIFIED_RESULT = "RESULT=PRIVATE_RUNTIME_CATALOG_SOURCE_VERIFIED"
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
NEXT_STAGE_BLOCK = "NEXT_STAGE_AUTHORIZED=false"


class PrivateRuntimeVerificationError(RuntimeError):
    """Raised when the private source contract cannot be authenticated."""


@dataclass(frozen=True)
class PublicCatalogEntry:
    """Stable metadata for one public migration in the authenticated head."""

    position: int
    name: str
    sha256: str
    size_bytes: int
    scope: str | None


@dataclass(frozen=True)
class PublicCatalogCompatibility:
    """The full public head plus its immutable historical-prefix proof."""

    migration_count: int
    digest_sha256: str
    historical_count: int
    historical_digest_sha256: str
    append_count: int
    entries: tuple[PublicCatalogEntry, ...]


@dataclass(frozen=True)
class PrivateRuntimeVerificationResult:
    public_migration_count: int
    public_digest_sha256: str
    public_append_count: int
    private_migration_count: int
    private_digest_sha256: str
    private_last_basename: str


def _load_sibling(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        name,
        Path(__file__).with_name(filename),
    )
    if spec is None or spec.loader is None:
        raise PrivateRuntimeVerificationError("verification dependency unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


private_catalog = _load_sibling(
    "private_runtime_catalog_v1_for_private_verifier",
    "private_runtime_catalog_v1.py",
)
adapter = _load_sibling(
    "private_runtime_adapter_v1_for_private_verifier",
    "private_runtime_catalog_adapter_v1.py",
)
validated_public_catalog = _load_sibling(
    "validated_public_catalog_for_private_verifier",
    "validated_migration_catalog_snapshot.py",
)
# ``validated_migration_catalog_snapshot`` authenticates and loads the
# byte-pinned public head verifier before exposing this API.  Keep the
# authenticated module as the only source for stable file reads and digest
# calculation below; do not import the mutable verifier a second time.
public_catalog = validated_public_catalog.catalog


def _schema_is_closed(schema: object) -> None:
    """Require the private schema's nested objects to be closed as well."""

    if type(schema) is not dict:
        raise PrivateRuntimeVerificationError("private schema is not an object")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise PrivateRuntimeVerificationError("private schema top level is open")
    defs = schema.get("$defs")
    if type(defs) is not dict:
        raise PrivateRuntimeVerificationError("private schema definitions are missing")
    required_defs = {"entry", "batch", "currentHead", "limits"}
    if set(defs) != required_defs:
        raise PrivateRuntimeVerificationError("private schema definitions are not closed")
    for name in required_defs:
        value = defs[name]
        if (
            type(value) is not dict
            or value.get("type") != "object"
            or value.get("additionalProperties") is not False
            or type(value.get("required")) is not list
            or type(value.get("properties")) is not dict
            or set(value["required"]) != set(value["properties"])
        ):
            raise PrivateRuntimeVerificationError(
                f"private schema definition is open: {name}"
            )


def _public_entry_dict(entry: PublicCatalogEntry) -> dict[str, object]:
    return {
        "position": entry.position,
        "name": entry.name,
        "sha256": entry.sha256,
        "size_bytes": entry.size_bytes,
    }


def _public_scope(entry: PublicCatalogEntry, catalog_directory: Path) -> str | None:
    """Read the candidate intent after the full validated snapshot is frozen."""

    if entry.position < HISTORICAL_COUNT:
        return None
    try:
        record = public_catalog._read_stable_file(
            catalog_directory / entry.name,
            maximum_size=public_catalog.MAX_MIGRATION_BYTES,
            error_type=public_catalog.CatalogDriftError,
        )
        if (
            len(record.content) != entry.size_bytes
            or hashlib.sha256(record.content).hexdigest() != entry.sha256
        ):
            raise PrivateRuntimeVerificationError("public candidate bytes drifted")
        first_line, separator, _rest = record.content.partition(b"\n")
        if not separator or not first_line.startswith(PUBLIC_INTENT_PREFIX):
            raise PrivateRuntimeVerificationError("public candidate intent missing")
        intent = public_catalog._decode_json(first_line[len(PUBLIC_INTENT_PREFIX) :])
        if (
            type(intent) is not dict
            or intent.get("scope") != "TENANT"
            or intent.get("operational_authorization") is not False
            or intent.get("next_stage_authorized") is not False
            or intent.get("migration_basename") != entry.name
        ):
            raise PrivateRuntimeVerificationError("public candidate scope invalid")
        return "TENANT"
    except PrivateRuntimeVerificationError:
        raise
    except Exception as exc:
        raise PrivateRuntimeVerificationError("public candidate intent invalid") from exc


def verify_public_catalog_compatibility() -> PublicCatalogCompatibility:
    """Validate the complete public head and then its pinned 75-file prefix.

    The public snapshot API authenticates the historical verifier and performs
    stable reads of the head, schema, and every catalog file.  Only after that
    complete validation do we apply the private-runtime compatibility rule:
    the first 75 entries must remain the pinned prefix and this transition may
    contain at most one public TENANT append.
    """

    try:
        snapshot = validated_public_catalog.validated_local_catalog_snapshot()
    except Exception as exc:
        raise PrivateRuntimeVerificationError("public catalog snapshot unavailable") from exc

    if (
        snapshot.operational_authorization is not False
        or snapshot.next_stage_authorized is not False
        or len(snapshot.entries) < HISTORICAL_COUNT
        or len(snapshot.entries) > HISTORICAL_COUNT + MAX_PUBLIC_APPEND_BATCHES
    ):
        raise PrivateRuntimeVerificationError("public head outside transition bound")

    entries: list[PublicCatalogEntry] = []
    for expected_position, raw_entry in enumerate(snapshot.entries):
        try:
            entry = PublicCatalogEntry(
                position=raw_entry.position,
                name=raw_entry.name,
                sha256=raw_entry.sha256,
                size_bytes=raw_entry.size_bytes,
                scope=None,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise PrivateRuntimeVerificationError("public snapshot entry malformed") from exc
        if entry.position != expected_position:
            raise PrivateRuntimeVerificationError("public positions are not contiguous")
        entries.append(entry)

    prefix = entries[:HISTORICAL_COUNT]
    if (
        len(prefix) != HISTORICAL_COUNT
        or prefix[-1].name != HISTORICAL_LAST_BASENAME
        or public_catalog._catalog_digest([_public_entry_dict(entry) for entry in prefix])
        != HISTORICAL_DIGEST_SHA256
    ):
        raise PrivateRuntimeVerificationError("public historical prefix drifted")

    catalog_directory = Path(snapshot.catalog_directory)
    appended: list[PublicCatalogEntry] = []
    for entry in entries[HISTORICAL_COUNT:]:
        scope = _public_scope(entry, catalog_directory)
        if scope != "TENANT":
            raise PrivateRuntimeVerificationError("public append is not TENANT")
        appended.append(
            PublicCatalogEntry(
                position=entry.position,
                name=entry.name,
                sha256=entry.sha256,
                size_bytes=entry.size_bytes,
                scope=scope,
            )
        )

    return PublicCatalogCompatibility(
        migration_count=len(entries),
        digest_sha256=snapshot.catalog_digest_sha256,
        historical_count=HISTORICAL_COUNT,
        historical_digest_sha256=HISTORICAL_DIGEST_SHA256,
        append_count=len(appended),
        entries=tuple(prefix + appended),
    )


def verify() -> PrivateRuntimeVerificationResult:
    """Verify both closed source manifests without opening a database."""

    public_state = verify_public_catalog_compatibility()
    try:
        schema = private_catalog.read_json(PRIVATE_SCHEMA_PATH)
        _schema_is_closed(schema)
        head = private_catalog.read_json(PRIVATE_HEAD_PATH)
        scanned = private_catalog.scan_directory(PRIVATE_MIGRATIONS_DIR)
        entries = private_catalog.validate_head(head, scanned_entries=scanned)
    except Exception as exc:
        raise PrivateRuntimeVerificationError("private catalog source is invalid") from exc

    # The separate stream is deliberately not a V1 append.  Its immutable
    # anchor is checked again here so callers cannot accidentally substitute a
    # different public snapshot between the two verifiers.
    if (
        head.get("historical_public_migration_count") != HISTORICAL_COUNT
        or head.get("historical_public_catalog_digest_sha256") != HISTORICAL_DIGEST_SHA256
        or head.get("historical_public_last_basename") != HISTORICAL_LAST_BASENAME
    ):
        raise PrivateRuntimeVerificationError("private history anchor is invalid")

    for entry in entries:
        try:
            content = private_catalog.read_file(PRIVATE_MIGRATIONS_DIR / entry["name"])
            candidate = adapter.validate_private_runtime_candidate(
                content,
                basename=entry["name"],
                expected_sha=None,
            )
        except Exception as exc:
            raise PrivateRuntimeVerificationError(
                "private candidate is not a closed V2 migration"
            ) from exc
        if (
            candidate.content_sha256 != entry["sha256"]
            or len(content) != entry["size_bytes"]
        ):
            raise PrivateRuntimeVerificationError("private candidate bytes drifted")

    private_current = head["current_head"]
    return PrivateRuntimeVerificationResult(
        public_migration_count=public_state.migration_count,
        public_digest_sha256=public_state.digest_sha256,
        public_append_count=public_state.append_count,
        private_migration_count=private_current["private_migration_count"],
        private_digest_sha256=private_current["private_digest_sha256"],
        private_last_basename=private_current["last_basename"],
    )


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
        result = verify()
    except PrivateRuntimeVerificationError:
        print("RESULT=BLOCKED_PRIVATE_RUNTIME_CATALOG_SOURCE")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return 4
    except Exception:
        print("RESULT=BLOCKED_PRIVATE_RUNTIME_CATALOG_SOURCE:INTERNAL_ERROR")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return 10
    print(VERIFIED_RESULT)
    print(f"PUBLIC_CATALOG_MIGRATION_COUNT={result.public_migration_count}")
    print(f"PUBLIC_CATALOG_DIGEST_SHA256={result.public_digest_sha256}")
    print(f"PUBLIC_CATALOG_APPEND_COUNT={result.public_append_count}")
    print(f"PRIVATE_CATALOG_MIGRATION_COUNT={result.private_migration_count}")
    print(f"PRIVATE_CATALOG_DIGEST_SHA256={result.private_digest_sha256}")
    print(f"PRIVATE_CATALOG_LAST_BASENAME={result.private_last_basename}")
    print(OPERATIONAL_BLOCK)
    print(NEXT_STAGE_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
