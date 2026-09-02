#!/usr/bin/env python3
"""Verifica offline o manifesto de expectativas do schema.

Este verificador prova somente que o manifesto continua vinculado aos bytes
versionados das migrations e ao contrato fail-closed. Ele não consulta banco,
não executa SQL e não autoriza operação.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import stat
import struct
import sys
from pathlib import Path
from typing import Any

try:
    from scripts import verify_migration_catalog_head as catalog_head
except ImportError:  # pragma: no cover - direct script execution
    import verify_migration_catalog_head as catalog_head


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "backend" / "migrations"
MANIFEST_DIR = REPO_ROOT / "docs" / "governance" / "migrations"
MANIFEST_BASENAME = "migration-history-schema-expectation-manifest-v1.json"
TARGET_REFERENCE_RELATIVE_PATH = ".github/workflows/rls-integration.yml"
TARGET_REFERENCE_PATH = REPO_ROOT / TARGET_REFERENCE_RELATIVE_PATH
TARGET_REFERENCE_SHA256 = (
    "4fac0b1ed923f3dc2298b45ff63bfe57ec849654ae6ab446facbca4b6fef891b"
)
CATALOG_ALGORITHM = "basename-ascii-ascending+sha256-raw-bytes-v1"
CATALOG_DOMAIN = "pastorai/migration-history/catalog/v1"
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
SUCCESS = "SCHEMA_EXPECTATION_MANIFEST_VERIFIED_SOURCE_ONLY"
MAX_MANIFEST_BYTES = 262_144
MAX_MIGRATION_BYTES = 4_194_304
MAX_CATALOG_BYTES = 67_108_864
MAX_CATALOG_FILES = 2_048
MIGRATION_BASENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.sql$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

TOP_LEVEL_KEYS = {
    "artifact_state",
    "attestation_contract",
    "contract_version",
    "decisions",
    "manifest_id",
    "next_gates",
    "operational_authorization",
    "repository",
    "review",
    "safety_contract",
    "source_expectation",
}
SAFETY_CONTRACT = {
    "database_access_allowed": False,
    "database_mutation_allowed": False,
    "deploy_allowed": False,
    "environment_capture_allowed": False,
    "ledger_backfill_allowed": False,
    "migration_application_allowed": False,
    "runner_change_allowed": False,
    "runner_execution_allowed": False,
    "runtime_change_allowed": False,
}
CAPABILITY_PATTERNS = {
    "ALTER_TABLE": re.compile(r"\balter\s+table\b", re.IGNORECASE),
    "ALTER_TYPE": re.compile(r"\balter\s+type\b", re.IGNORECASE),
    "CREATE_FUNCTION": re.compile(
        r"\bcreate(?:\s+or\s+replace)?\s+function\b", re.IGNORECASE
    ),
    "CREATE_INDEX": re.compile(
        r"\bcreate\s+(?:unique\s+)?index\b", re.IGNORECASE
    ),
    "CREATE_POLICY": re.compile(r"\bcreate\s+policy\b", re.IGNORECASE),
    "CREATE_ROLE": re.compile(r"\bcreate\s+role\b", re.IGNORECASE),
    "CREATE_SCHEMA": re.compile(r"\bcreate\s+schema\b", re.IGNORECASE),
    "CREATE_TABLE": re.compile(r"\bcreate\s+table\b", re.IGNORECASE),
    "CREATE_TRIGGER": re.compile(r"\bcreate\s+trigger\b", re.IGNORECASE),
    "CREATE_TYPE": re.compile(r"\bcreate\s+type\b", re.IGNORECASE),
    "DATA_MUTATION": re.compile(
        r"\b(?:insert\s+into|update|delete\s+from)\b", re.IGNORECASE
    ),
    "DROP_OBJECT": re.compile(
        r"\bdrop\s+(?:table|type|function|policy|trigger|index|schema|role)\b",
        re.IGNORECASE,
    ),
    "ENABLE_RLS": re.compile(
        r"\benable\s+row\s+level\s+security\b", re.IGNORECASE
    ),
    "FORCE_RLS": re.compile(
        r"\bforce\s+row\s+level\s+security\b", re.IGNORECASE
    ),
    "GRANT": re.compile(r"\bgrant\b", re.IGNORECASE),
    "REVOKE": re.compile(r"\brevoke\b", re.IGNORECASE),
}
EXPECTED_CAPABILITY_FILE_COUNTS = {
    "ALTER_TABLE": 46,
    "ALTER_TYPE": 18,
    "CREATE_FUNCTION": 15,
    "CREATE_INDEX": 32,
    "CREATE_POLICY": 24,
    "CREATE_ROLE": 1,
    "CREATE_SCHEMA": 1,
    "CREATE_TABLE": 25,
    "CREATE_TRIGGER": 6,
    "CREATE_TYPE": 4,
    "DATA_MUTATION": 33,
    "DROP_OBJECT": 21,
    "ENABLE_RLS": 27,
    "FORCE_RLS": 2,
    "GRANT": 11,
    "REVOKE": 18,
}
REQUIRED_DOMAINS = [
    "EXTENSIONS",
    "ENUM_TYPES_AND_VALUES",
    "ROLES_AND_MEMBERSHIPS",
    "SCHEMAS_AND_OWNERS",
    "RELATIONS_AND_PERSISTENCE",
    "COLUMNS_TYPES_DEFAULTS_IDENTITY_GENERATED",
    "CONSTRAINTS_AND_VALIDATION_STATE",
    "INDEXES_DEFINITIONS_AND_VALIDITY",
    "FUNCTIONS_SIGNATURE_LANGUAGE_VOLATILITY_SECURITY_SEARCH_PATH",
    "TRIGGERS_AND_REWRITE_RULES",
    "RLS_ENABLE_FORCE_FLAGS",
    "POLICIES_COMMAND_ROLES_USING_WITH_CHECK",
    "TABLE_COLUMN_FUNCTION_SCHEMA_PRIVILEGES",
    "DEFAULT_PRIVILEGES",
    "DATA_INVARIANTS",
]
DATA_INVARIANTS = [
    "TENANT_FOREIGN_KEY_CONSISTENCY",
    "TENANT_UNIQUENESS_GUARDS",
    "APPEND_ONLY_AUDIT_INTEGRITY",
    "IDEMPOTENCY_UNIQUENESS",
    "CONSENT_LEDGER_INTEGRITY",
    "BILLING_ISOLATION_INTEGRITY",
    "RECOVERY_ARTIFACT_RETENTION",
    "GOVERNANCE_DRAFT_INTEGRITY",
]
NEXT_GATES = [
    "INDEPENDENT_SECURITY_AND_DATABASE_ARCHITECTURE_REVIEW",
    "SEPARATE_OFFLINE_CANONICAL_SCHEMA_DERIVATION",
    "SEPARATE_READ_ONLY_ENVIRONMENT_ATTESTATION",
    "HUMAN_CUTOVER_DECISION",
    "SEPARATE_IMPLEMENTATION_PR",
    "SEPARATE_ENVIRONMENT_EXECUTION_AUTHORIZATION",
]


class ManifestError(Exception):
    exit_code = 4
    reason = "MANIFEST_INVALID"


class ManifestIoError(ManifestError):
    exit_code = 3
    reason = "MANIFEST_IO_INVALID"


class CatalogDriftError(ManifestError):
    exit_code = 5
    reason = "CATALOG_DRIFT"


class CliUsageError(ManifestError):
    exit_code = 2
    reason = "USAGE"


class SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError


def _frame(tag: bytes, payload: bytes) -> bytes:
    if len(tag) != 1:
        raise ValueError("invalid internal frame tag")
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
        encoded_items: list[tuple[bytes, bytes]] = []
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("invalid internal mapping key")
            encoded_items.append((key.encode("utf-8"), _encode_framed(item)))
        encoded_items.sort(key=lambda pair: pair[0])
        payload = struct.pack(">Q", len(encoded_items))
        for key_bytes, encoded_value in encoded_items:
            payload += _frame(b"K", key_bytes) + encoded_value
        return _frame(b"O", payload)
    raise ValueError("unsupported internal framing type")


def _framed_sha256(domain: str, value: Any) -> str:
    material = b"PASTORAI-MIGRATION-HISTORY\x00\x01"
    material += _frame(b"D", domain.encode("ascii"))
    material += _encode_framed(value)
    return hashlib.sha256(material).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ManifestError
        value[key] = item
    return value


def _stat_snapshot(value: Any) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ManifestIoError
        if info.st_size <= 0 or info.st_size > MAX_MANIFEST_BYTES:
            raise ManifestIoError
        content = path.read_bytes()
        final_info = path.lstat()
    except OSError as exc:
        raise ManifestIoError from exc
    if (
        len(content) != info.st_size
        or _stat_snapshot(info) != _stat_snapshot(final_info)
        or content.startswith(b"\xef\xbb\xbf")
    ):
        raise ManifestIoError
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=lambda _value: (_ for _ in ()).throw(ManifestError()),
            parse_constant=lambda _value: (_ for _ in ()).throw(ManifestError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError from exc
    if type(value) is not dict:
        raise ManifestError
    return value


def _scan_catalog() -> tuple[list[dict[str, Any]], dict[str, int]]:
    try:
        head, current_catalog = (
            catalog_head._validated_snapshot_for_historical_consumers()
        )
    except catalog_head.VerificationError as exc:
        raise CatalogDriftError from exc
    historical = head.get("historical_prefix")
    if type(historical) is not dict:
        raise CatalogDriftError
    expected_entries = historical.get("entries")
    if type(expected_entries) is not list:
        raise CatalogDriftError
    historical_names = [entry.get("name") for entry in expected_entries]
    current_names = [entry.get("name") for entry in current_catalog]
    try:
        directory_info = MIGRATIONS_DIR.lstat()
        if not stat.S_ISDIR(directory_info.st_mode):
            raise CatalogDriftError
        directory_entries = list(MIGRATIONS_DIR.iterdir())
        if any(
            path.suffix.casefold() == ".sql" and path.suffix != ".sql"
            for path in directory_entries
        ):
            raise CatalogDriftError
        names = sorted(
            path.name for path in directory_entries if path.suffix == ".sql"
        )
    except OSError as exc:
        raise CatalogDriftError from exc
    if not names or len(names) > MAX_CATALOG_FILES:
        raise CatalogDriftError
    if any(not MIGRATION_BASENAME_RE.fullmatch(name) for name in names):
        raise CatalogDriftError
    if len(set(names)) != len(names) or len(
        {name.casefold() for name in names}
    ) != len(names):
        raise CatalogDriftError

    if names != current_names:
        raise CatalogDriftError
    if any(type(name) is not str for name in historical_names):
        raise CatalogDriftError

    entries: list[dict[str, Any]] = []
    capability_counts = {tag: 0 for tag in CAPABILITY_PATTERNS}
    total_size = 0
    for position, name in enumerate(historical_names):
        path = MIGRATIONS_DIR / name
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise CatalogDriftError
            if info.st_size < 0 or info.st_size > MAX_MIGRATION_BYTES:
                raise CatalogDriftError
            content = path.read_bytes()
            final_info = path.lstat()
        except OSError as exc:
            raise CatalogDriftError from exc
        if len(content) != info.st_size or _stat_snapshot(info) != _stat_snapshot(
            final_info
        ):
            raise CatalogDriftError
        total_size += len(content)
        if total_size > MAX_CATALOG_BYTES:
            raise CatalogDriftError
        try:
            sql_text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CatalogDriftError from exc
        for tag, pattern in CAPABILITY_PATTERNS.items():
            if pattern.search(sql_text):
                capability_counts[tag] += 1
        entries.append(
            {
                "position": position,
                "name": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        )
    try:
        final_directory_entries = list(MIGRATIONS_DIR.iterdir())
        if any(
            path.suffix.casefold() == ".sql" and path.suffix != ".sql"
            for path in final_directory_entries
        ):
            raise CatalogDriftError
        final_names = sorted(
            path.name for path in final_directory_entries if path.suffix == ".sql"
        )
        final_directory_info = MIGRATIONS_DIR.lstat()
    except OSError as exc:
        raise CatalogDriftError from exc
    if names != final_names or _stat_snapshot(directory_info) != _stat_snapshot(
        final_directory_info
    ):
        raise CatalogDriftError
    if entries != expected_entries:
        raise CatalogDriftError
    return entries, capability_counts


def _require_exact_dict(value: Any, expected: dict[str, Any]) -> None:
    if type(value) is not dict or value != expected:
        raise ManifestError


def _validate_manifest(
    manifest: dict[str, Any],
    catalog: list[dict[str, Any]],
    capability_counts: dict[str, int],
) -> None:
    if set(manifest) != TOP_LEVEL_KEYS:
        raise ManifestError
    if manifest["contract_version"] != "1.0":
        raise ManifestError
    if manifest["manifest_id"] != "migration-history-schema-expectation-manifest-v1":
        raise ManifestError
    if manifest["artifact_state"] != (
        "SOURCE_EXPECTATION_VERIFIED_ENVIRONMENT_UNATTESTED"
    ):
        raise ManifestError
    if manifest["operational_authorization"] is not False:
        raise ManifestError
    _require_exact_dict(manifest["safety_contract"], SAFETY_CONTRACT)

    repository = manifest["repository"]
    if type(repository) is not dict or set(repository) != {
        "declared_base_sha",
        "declared_base_sha_role",
        "catalog_algorithm",
        "catalog_digest_sha256",
        "catalog_migration_count",
        "critical_migration_anchors",
        "migrations_path",
    }:
        raise ManifestError
    if repository["declared_base_sha"] != (
        "7f18f7e8b44cd50e6f6033867fb97bfa9eb9c9e6"
    ):
        raise ManifestError
    if repository["declared_base_sha_role"] != (
        "DECLARED_CONTEXT_ONLY_CATALOG_DIGEST_IS_AUTHORITATIVE_BYTE_BINDING"
    ):
        raise ManifestError
    if repository["migrations_path"] != "backend/migrations":
        raise ManifestError
    if repository["catalog_algorithm"] != CATALOG_ALGORITHM:
        raise ManifestError
    if repository["catalog_migration_count"] != len(catalog):
        raise CatalogDriftError
    actual_digest = _framed_sha256(
        CATALOG_DOMAIN,
        {"algorithm": CATALOG_ALGORITHM, "entries": catalog},
    )
    expected_digest = repository["catalog_digest_sha256"]
    if type(expected_digest) is not str or not SHA256_RE.fullmatch(expected_digest):
        raise ManifestError
    if not hmac.compare_digest(expected_digest, actual_digest):
        raise CatalogDriftError

    anchors = repository["critical_migration_anchors"]
    if type(anchors) is not list or not anchors:
        raise ManifestError
    catalog_by_name = {entry["name"]: entry for entry in catalog}
    anchor_names: list[str] = []
    for anchor in anchors:
        if type(anchor) is not dict or set(anchor) != {"name", "sha256"}:
            raise ManifestError
        name = anchor["name"]
        digest = anchor["sha256"]
        if type(name) is not str or type(digest) is not str:
            raise ManifestError
        if name not in catalog_by_name or not SHA256_RE.fullmatch(digest):
            raise ManifestError
        if not hmac.compare_digest(digest, catalog_by_name[name]["sha256"]):
            raise CatalogDriftError
        anchor_names.append(name)
    if anchor_names != sorted(anchor_names) or len(set(anchor_names)) != len(
        anchor_names
    ):
        raise ManifestError

    source = manifest["source_expectation"]
    if type(source) is not dict or set(source) != {
        "capability_file_counts",
        "derivation_method",
        "environment_attestation_complete",
        "final_schema_claim",
        "known_limitations",
        "manifest_scope",
    }:
        raise ManifestError
    if source["manifest_scope"] != "SOURCE_LEVEL_EXPECTATION_ONLY":
        raise ManifestError
    if source["derivation_method"] != "STATIC_RAW_BYTES_AND_CONSERVATIVE_TOKEN_SCAN":
        raise ManifestError
    if source["final_schema_claim"] is not False:
        raise ManifestError
    if source["environment_attestation_complete"] is not False:
        raise ManifestError
    _require_exact_dict(
        source["capability_file_counts"], EXPECTED_CAPABILITY_FILE_COUNTS
    )
    if capability_counts != EXPECTED_CAPABILITY_FILE_COUNTS:
        raise CatalogDriftError
    if source["known_limitations"] != [
        "CONDITIONAL_AND_DYNAMIC_SQL_NOT_SEMANTICALLY_EXECUTED",
        "MIGRATION_ORDER_DOES_NOT_PROVE_ENVIRONMENT_APPLICATION",
        "STATIC_TOKENS_DO_NOT_PROVE_FINAL_OBJECT_DEFINITIONS",
        "DATA_INVARIANTS_REQUIRE_SEPARATE_READ_ONLY_ATTESTATION",
    ]:
        raise ManifestError

    attestation = manifest["attestation_contract"]
    if type(attestation) is not dict or set(attestation) != {
        "comparison_rules",
        "current_environment_version_attested",
        "data_invariants",
        "environments",
        "offline_derivation_target",
        "required_domains",
        "state",
    }:
        raise ManifestError
    if attestation["state"] != "PENDING_SEPARATE_READ_ONLY_ENVIRONMENT_ATTESTATION":
        raise ManifestError
    if attestation["current_environment_version_attested"] is not False:
        raise ManifestError
    if attestation["offline_derivation_target"] != {
        "postgresql_major": 17,
        "reference_path": TARGET_REFERENCE_RELATIVE_PATH,
        "reference_sha256": TARGET_REFERENCE_SHA256,
        "selection_basis": (
            "VERSIONED_DISPOSABLE_CI_IMAGE_NOT_ENVIRONMENT_OBSERVATION"
        ),
    }:
        raise ManifestError
    try:
        target_reference_digest = hashlib.sha256(
            TARGET_REFERENCE_PATH.read_bytes()
        ).hexdigest()
    except OSError as exc:
        raise CatalogDriftError from exc
    if not hmac.compare_digest(target_reference_digest, TARGET_REFERENCE_SHA256):
        raise CatalogDriftError
    if attestation["environments"] != ["DEV", "PROD"]:
        raise ManifestError
    if attestation["required_domains"] != REQUIRED_DOMAINS:
        raise ManifestError
    if attestation["data_invariants"] != [
        {"id": item, "state": "PENDING_SEPARATE_READ_ONLY_ATTESTATION"}
        for item in DATA_INVARIANTS
    ]:
        raise ManifestError
    if attestation["comparison_rules"] != [
        "UNKNOWN_MISSING_EXTRA_OR_MISMATCH_BLOCKS",
        "NO_APPLICATION_INFERENCE_FROM_NAME_VERSION_POSITION_OR_TIMESTAMP",
        "NATIVE_AND_PUBLIC_LEDGERS_REMAIN_INDEPENDENT",
        "NO_AUTOMATIC_REPAIR_BACKFILL_OR_REAPPLICATION",
        "EACH_ENVIRONMENT_REQUIRES_DISTINCT_EVIDENCE_AND_HUMAN_DECISION",
    ]:
        raise ManifestError

    review = manifest["review"]
    if review != {
        "conclusion": "PASS_FOR_SOURCE_MANIFEST_ONLY",
        "independent_review_complete": False,
        "review_type": "TECHNICAL_SELF_REVIEW_NOT_INDEPENDENT",
        "reviewer_reference": "SYSTEM-TECHNICAL-REVIEW",
        "substantive_findings": [
            "FAIL_CLOSED_ARCHITECTURE_IS_COHERENT",
            "CONTROLLED_EPOCH_REMAINS_UNAPPROVED",
            "FINAL_SCHEMA_CANNOT_BE_PROVEN_BY_STATIC_SCAN",
            "INDEPENDENT_REVIEW_REMAINS_REQUIRED",
        ],
    }:
        raise ManifestError
    if manifest["decisions"] != {
        "independent_ledger_review_sha256": (
            "18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133"
        ),
        "owner_offline_mission_sha256": (
            "0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240"
        ),
        "controlled_epoch_cutover_approved": False,
    }:
        raise ManifestError
    if manifest["next_gates"] != NEXT_GATES:
        raise ManifestError


def verify_manifest(path: Path) -> None:
    manifest = _load_manifest(path)
    catalog, capability_counts = _scan_catalog()
    _validate_manifest(manifest, catalog, capability_counts)


def build_parser() -> argparse.ArgumentParser:
    parser = SanitizedArgumentParser(add_help=False)
    parser.add_argument("--manifest", required=True, choices=[MANIFEST_BASENAME])
    return parser


def main(argv: list[str] | None = None) -> int:
    print(OPERATIONAL_BLOCK)
    try:
        args = build_parser().parse_args(argv)
        verify_manifest(MANIFEST_DIR / args.manifest)
    except ManifestError as exc:
        print(f"SCHEMA_EXPECTATION_MANIFEST_BLOCKED:{exc.reason}", file=sys.stderr)
        return exc.exit_code
    except Exception:
        print("SCHEMA_EXPECTATION_MANIFEST_BLOCKED:INTERNAL_ERROR", file=sys.stderr)
        return 10
    print(SUCCESS)
    print("ENVIRONMENT_ATTESTATION_COMPLETE=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
