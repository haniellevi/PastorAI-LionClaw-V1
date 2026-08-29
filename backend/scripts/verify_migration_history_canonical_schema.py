#!/usr/bin/env python3
"""Verify two offline canonical-schema artifacts without database access."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys
from typing import Any, NoReturn

try:
    from scripts import derive_migration_history_canonical_schema as derivation
except ModuleNotFoundError:  # direct execution from backend/scripts
    import derive_migration_history_canonical_schema as derivation


OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
SUCCESS = "CANONICAL_SCHEMA_REPLAYS_VERIFIED_DETERMINISTIC_OFFLINE_ONLY"
MAX_ARTIFACT_BYTES = derivation.MAX_OUTPUT_BYTES
FINGERPRINT_SUMMARY_PATH = (
    derivation.REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-canonical-schema-fingerprint-v1.json"
)
TOP_LEVEL_KEYS = {
    "artifact_id",
    "artifact_state",
    "canonical_schema_fingerprint_sha256",
    "contract_version",
    "data_api",
    "derivation_target",
    "domains",
    "environment_attestation_complete",
    "extension_version_semantics",
    "operational_authorization",
    "replay",
    "scaffold",
    "source_catalog",
}
FORBIDDEN_KEYS = {
    "captured_at",
    "created_at",
    "database_name",
    "dsn",
    "host",
    "oid",
    "row_data",
    "session_user",
    "timestamp",
    "user",
    "username",
}


class VerificationError(RuntimeError):
    exit_code = 10
    reason = "INTERNAL_ERROR"


class CliUsageError(VerificationError):
    exit_code = 2
    reason = "USAGE"


class ArtifactIoError(VerificationError):
    exit_code = 3
    reason = "ARTIFACT_IO_INVALID"


class ArtifactContractError(VerificationError):
    exit_code = 4
    reason = "ARTIFACT_CONTRACT_INVALID"


class ReplayMismatchError(VerificationError):
    exit_code = 5
    reason = "REPLAY_FINGERPRINT_MISMATCH"


class SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise CliUsageError


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ArtifactContractError
        value[key] = item
    return value


def _read_artifact(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ArtifactIoError
        if before.st_size <= 0 or before.st_size > MAX_ARTIFACT_BYTES:
            raise ArtifactIoError
        content = path.read_bytes()
        after = path.lstat()
    except OSError as exc:
        raise ArtifactIoError from exc
    if (
        len(content) != before.st_size
        or before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_mode != after.st_mode
        or before.st_nlink != after.st_nlink
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
    ):
        raise ArtifactIoError
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=lambda _value: (_ for _ in ()).throw(
                ArtifactContractError()
            ),
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ArtifactContractError()
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactContractError from exc
    if type(value) is not dict:
        raise ArtifactContractError
    return content, value


def _walk_keys(value: Any) -> None:
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str or key.casefold() in FORBIDDEN_KEYS:
                raise ArtifactContractError
            _walk_keys(item)
    elif type(value) is list:
        for item in value:
            _walk_keys(item)
    elif value is not None and type(value) not in {bool, int, str}:
        raise ArtifactContractError


def _validate_artifact(artifact: dict[str, Any]) -> None:
    if set(artifact) != TOP_LEVEL_KEYS:
        raise ArtifactContractError
    _walk_keys(artifact)
    if artifact["artifact_id"] != "migration-history-canonical-schema-derivation-v1":
        raise ArtifactContractError
    if artifact["artifact_state"] != (
        "OFFLINE_CANONICAL_SCHEMA_DERIVED_ENVIRONMENTS_UNATTESTED"
    ):
        raise ArtifactContractError
    if artifact["contract_version"] != "1.0":
        raise ArtifactContractError
    if artifact["operational_authorization"] is not False:
        raise ArtifactContractError
    if artifact["environment_attestation_complete"] is not False:
        raise ArtifactContractError
    if artifact["extension_version_semantics"] != (
        "OBSERVATIONAL_NOT_PINNED_OR_OPERATIONAL"
    ):
        raise ArtifactContractError
    if artifact["data_api"] != {
        "exposure_inferred": False,
        "state": "NOT_EVALUATED_OFFLINE",
    }:
        raise ArtifactContractError
    if artifact["derivation_target"] != {
        "container_image": derivation.POSTGRES_IMAGE,
        "disposable_database_required": True,
        "loopback_required": True,
        "postgresql_major": 17,
        "realtime_scaffolded": False,
    }:
        raise ArtifactContractError
    if artifact["source_catalog"] != {
        "algorithm": derivation.source_manifest.CATALOG_ALGORITHM,
        "digest_sha256": derivation.CATALOG_DIGEST_SHA256,
        "migration_count": 75,
        "path": "backend/migrations",
    }:
        raise ArtifactContractError
    if artifact["scaffold"] != {
        "owner_identity": "DERIVATION_OWNER",
        "path": derivation.SCAFFOLD_RELATIVE_PATH,
        "roles": ["anon", "authenticated", "service_role"],
        "sha256": derivation.SCAFFOLD_SHA256,
    }:
        raise ArtifactContractError
    if artifact["replay"] != {
        "autocommit_per_file": True,
        "complete": True,
        "migration_count": 75,
        "native_ledger_absent": True,
        "public_ledger_absent": True,
        "raw_bytes_preserved": True,
    }:
        raise ArtifactContractError

    domains = artifact["domains"]
    if type(domains) is not list or len(domains) != 15:
        raise ArtifactContractError
    if [item.get("name") for item in domains if type(item) is dict] != list(
        derivation.REQUIRED_DOMAINS
    ):
        raise ArtifactContractError
    for domain in domains:
        if type(domain) is not dict or set(domain) != {
            "entry_count", "entries", "name", "sha256"
        }:
            raise ArtifactContractError
        entries = domain["entries"]
        if type(entries) is not list or domain["entry_count"] != len(entries):
            raise ArtifactContractError
        if entries != sorted(entries, key=derivation._canonical_bytes):
            raise ArtifactContractError
        expected_digest = derivation._domain_sha256(domain["name"], entries)
        if domain["sha256"] != expected_digest:
            raise ArtifactContractError
    if artifact["canonical_schema_fingerprint_sha256"] != (
        derivation._artifact_sha256(domains)
    ):
        raise ArtifactContractError

    relations = next(
        domain["entries"] for domain in domains
        if domain["name"] == "RELATIONS_AND_PERSISTENCE"
    )
    if any(
        entry.get("relation") == "schema_migrations"
        or entry.get("schema") == "supabase_migrations"
        for entry in relations
    ):
        raise ArtifactContractError
    schemas = next(
        domain["entries"] for domain in domains
        if domain["name"] == "SCHEMAS_AND_OWNERS"
    )
    if any(entry.get("schema") == "realtime" for entry in schemas):
        raise ArtifactContractError

    serialized = derivation._canonical_bytes(artifact).decode("ascii").casefold()
    if "postgresql://" in serialized or "postgres://" in serialized:
        raise ArtifactContractError


def _expected_summary(
    artifact: dict[str, Any], full_artifact_bytes: bytes
) -> dict[str, Any]:
    return {
        "artifact_id": "migration-history-canonical-schema-fingerprint-v1",
        "artifact_state": artifact["artifact_state"],
        "canonical_schema_fingerprint_sha256": artifact[
            "canonical_schema_fingerprint_sha256"
        ],
        "contract_version": "1.0",
        "data_api": artifact["data_api"],
        "derivation_target": artifact["derivation_target"],
        "domain_fingerprints": [
            {
                "entry_count": domain["entry_count"],
                "name": domain["name"],
                "sha256": domain["sha256"],
            }
            for domain in artifact["domains"]
        ],
        "environment_attestation_complete": False,
        "extension_version_semantics": artifact["extension_version_semantics"],
        "full_artifact_bytes": len(full_artifact_bytes),
        "full_artifact_sha256": hashlib.sha256(full_artifact_bytes).hexdigest(),
        "operational_authorization": False,
        "replay": artifact["replay"],
        "scaffold": artifact["scaffold"],
        "source_catalog": artifact["source_catalog"],
    }


def verify(first_path: Path, second_path: Path) -> dict[str, Any]:
    schema = derivation._safe_regular_file(
        derivation.SCHEMA_PATH, derivation.MAX_CONTRACT_BYTES
    )
    if hashlib.sha256(schema).hexdigest() != derivation.SCHEMA_SHA256:
        raise ArtifactContractError
    first_bytes, first = _read_artifact(first_path)
    second_bytes, second = _read_artifact(second_path)
    _validate_artifact(first)
    _validate_artifact(second)
    if first_bytes != second_bytes or first != second:
        raise ReplayMismatchError
    _summary_bytes, summary = _read_artifact(FINGERPRINT_SUMMARY_PATH)
    _walk_keys(summary)
    if summary != _expected_summary(first, first_bytes):
        raise ArtifactContractError
    return first


def build_parser() -> argparse.ArgumentParser:
    parser = SanitizedArgumentParser(add_help=False)
    parser.add_argument("--artifact-a", required=True, type=Path)
    parser.add_argument("--artifact-b", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    print(OPERATIONAL_BLOCK)
    try:
        args = build_parser().parse_args(argv)
        verify(args.artifact_a, args.artifact_b)
    except VerificationError as exc:
        print(f"CANONICAL_SCHEMA_VERIFICATION_BLOCKED:{exc.reason}", file=sys.stderr)
        return exc.exit_code
    except derivation.DerivationError:
        print(
            "CANONICAL_SCHEMA_VERIFICATION_BLOCKED:ARTIFACT_CONTRACT_INVALID",
            file=sys.stderr,
        )
        return 4
    except Exception:
        print("CANONICAL_SCHEMA_VERIFICATION_BLOCKED:INTERNAL_ERROR", file=sys.stderr)
        return 10
    print("ENVIRONMENT_ATTESTATION_COMPLETE=false")
    print(SUCCESS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
