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
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any


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
VERIFIED_RESULT = "RESULT=PRIVATE_RUNTIME_CATALOG_SOURCE_VERIFIED"
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
NEXT_STAGE_BLOCK = "NEXT_STAGE_AUTHORIZED=false"


class PrivateRuntimeVerificationError(RuntimeError):
    """Raised when the private source contract cannot be authenticated."""


@dataclass(frozen=True)
class PrivateRuntimeVerificationResult:
    public_migration_count: int
    public_digest_sha256: str
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
public_catalog = _load_sibling(
    "public_catalog_v1_for_private_verifier",
    "verify_migration_catalog_head.py",
)


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


def _verify_public_history() -> dict[str, Any]:
    try:
        head = public_catalog.verify_versioned_head()
    except Exception as exc:
        raise PrivateRuntimeVerificationError("historical public catalog is invalid") from exc
    current = head.get("current_head")
    if (
        type(current) is not dict
        or current.get("migration_count") != HISTORICAL_COUNT
        or current.get("digest_sha256") != HISTORICAL_DIGEST_SHA256
        or current.get("last_basename") != HISTORICAL_LAST_BASENAME
        or head.get("append_only_batches") != []
    ):
        raise PrivateRuntimeVerificationError("public history is not the pinned 75 prefix")
    return head


def verify() -> PrivateRuntimeVerificationResult:
    """Verify both closed source manifests without opening a database."""

    public_head = _verify_public_history()
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

    current = public_head["current_head"]
    private_current = head["current_head"]
    return PrivateRuntimeVerificationResult(
        public_migration_count=current["migration_count"],
        public_digest_sha256=current["digest_sha256"],
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
    print(f"PRIVATE_CATALOG_MIGRATION_COUNT={result.private_migration_count}")
    print(f"PRIVATE_CATALOG_DIGEST_SHA256={result.private_digest_sha256}")
    print(f"PRIVATE_CATALOG_LAST_BASENAME={result.private_last_basename}")
    print(OPERATIONAL_BLOCK)
    print(NEXT_STAGE_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
