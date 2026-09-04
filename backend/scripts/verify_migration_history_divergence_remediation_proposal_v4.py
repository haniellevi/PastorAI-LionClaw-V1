#!/usr/bin/env python3
"""Verify the blocked, source-only migration safety extension v4.

The verifier authenticates only fixed repository artifacts and reads the
current catalog through the separately authenticated snapshot API.  It does
not accept caller-selected paths, read process configuration, contact a
database or network service, invoke subprocesses, or write files.  A valid
package remains blocked: it adds source-safety evidence without changing any
environment attestation, cutover decision, or operational permission.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from types import ModuleType
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_DIR = REPO_ROOT / "docs" / "governance" / "migrations"
PROPOSAL_PATH = (
    GOVERNANCE_DIR
    / "migration-history-divergence-remediation-proposal-v4.json"
)
SCHEMA_PATH = (
    GOVERNANCE_DIR
    / "migration-history-divergence-remediation-proposal-v4.schema.json"
)
SNAPSHOT_API_PATH = (
    REPO_ROOT / "backend" / "scripts" / "validated_migration_catalog_snapshot.py"
)
MIGRATIONS_DIR = REPO_ROOT / "backend" / "migrations"

MAX_JSON_BYTES = 1_048_576
MAX_SOURCE_BYTES = 4_194_304
BLOCKED_EXIT = 8
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
NEXT_STAGE_BLOCK = "NEXT_STAGE_AUTHORIZED=false"
VERIFIED_RESULT = (
    "RESULT=BLOCKED_MIGRATION_DIVERGENCE_V4:SOURCE_EXTENSION_VERIFIED"
)

EXPECTED_PROPOSAL_SHA256 = (
    "92b1c33ab3e2cd0a6c9b5ad486a317c229d7aefc7c60da88913716d58345e6ac"
)
EXPECTED_SCHEMA_SHA256 = (
    "e10d8922a68a6f475191330dbecf0c00b2e5ffccf03e9fb4726bdcb30c4d494f"
)
EXPECTED_REPOSITORY_COMMIT_SHA = "9b9395e29cc821d6808738a30a6afe367d4ffbea"

EXPECTED_HISTORICAL_CONTRACTS = {
    "v1_proposal": {
        "path": (
            "docs/governance/migrations/"
            "migration-history-divergence-remediation-proposal-v1.json"
        ),
        "sha256": (
            "84614e0b140e38d07c11ed4ceb10025b3dbc85b121684da1e1ebdca6d0104e7d"
        ),
    },
    "v2_proposal": {
        "path": (
            "docs/governance/migrations/"
            "migration-history-divergence-remediation-proposal-v2.json"
        ),
        "sha256": (
            "f1db4a0f1b6a5045fefa674d6092ecb8afe90a0c03c70044b53a1d021b2b8340"
        ),
    },
    "v3_proposal": {
        "path": (
            "docs/governance/migrations/"
            "migration-history-divergence-remediation-proposal-v3.json"
        ),
        "sha256": (
            "076d04ed179c5128c4707c07cacd8240896101a9bea62e328d2d0569900cd10e"
        ),
    },
    "v3_schema": {
        "path": (
            "docs/governance/migrations/"
            "migration-history-divergence-remediation-proposal-v3.schema.json"
        ),
        "sha256": (
            "88f7972780f07c7071bb4e4292e1f21c258fff47daf2ab207fc709ff34631b38"
        ),
    },
    "v3_verifier": {
        "path": (
            "backend/scripts/"
            "verify_migration_history_divergence_remediation_proposal_v3.py"
        ),
        "sha256": (
            "efcc9be299241793c74e5c4174a4dc44f3b14507d1585d9daa5a407ab38f13f8"
        ),
    },
}

EXPECTED_SOURCE_ARTIFACTS = {
    "catalog_bound_wrapper_v2": {
        "path": "backend/scripts/apply_migrations_catalog_bound_v2.py",
        "sha256": (
            "f3166fd5f770af016d6792e115a047845ad137065c35740e34da1ee3b2ea0e29"
        ),
    },
    "catalog_ci_verifier": {
        "path": "backend/scripts/verify_migration_catalog_ci.py",
        "sha256": (
            "7cf5b468e366debba3a9d23c66566b122c8e155dceb3f76ee4d755ce4410b7c8"
        ),
    },
    "catalog_snapshot_api": {
        "path": "backend/scripts/validated_migration_catalog_snapshot.py",
        "sha256": (
            "c3b88dd7f2b520e9de9353f2c220b5a2f07aaadc42661e8f2d9bb03a955d1d3f"
        ),
    },
    "current_head_pg17_replay": {
        "path": "backend/scripts/replay_migration_catalog_current_head_pg17.py",
        "sha256": (
            "753abf57747de9a28f6192617dfd7ea348cb7adf302d7acbd57f280de3d8ce3f"
        ),
    },
    "migration_authoring": {
        "path": "backend/scripts/new_migration.py",
        "sha256": (
            "83abce96e63fe676e3088c225b1e29ae89268ce97d01727bc740fa2f50001bbe"
        ),
    },
    "migration_catalog_workflow": {
        "path": ".github/workflows/migration-catalog-head.yml",
        "sha256": (
            "f2fc5ffc2943f7134a38dc251db2bffc1c7545956729862ed98a227dda2ff8c7"
        ),
    },
}

EXPECTED_PERMISSIONS = {
    "capture_allowed": False,
    "database_access_allowed": False,
    "database_mutation_allowed": False,
    "deploy_allowed": False,
    "environment_attestation_execution_allowed": False,
    "environment_operation_allowed": False,
    "index_change_allowed": False,
    "ledger_backfill_allowed": False,
    "merge_allowed": False,
    "migration_application_allowed": False,
    "network_access_allowed": False,
    "pull_request_creation_allowed": False,
    "push_allowed": False,
    "runner_change_allowed": False,
    "runner_execution_allowed": False,
    "runtime_change_allowed": False,
    "source_mutation_allowed": False,
}

EXPECTED_EXTENSION_CONTRACT = {
    "extends_proposal_id": (
        "migration-history-divergence-remediation-proposal-v3"
    ),
    "extends_sha256": EXPECTED_HISTORICAL_CONTRACTS["v3_proposal"]["sha256"],
    "historical_bytes_must_remain_unchanged": True,
    "prior_environment_and_cutover_records_remain_governed_by_v1_v2_v3": True,
    "reinterprets_environment_or_cutover_state": False,
    "scope": "SOURCE_ONLY_MIGRATION_AUTHORING_AND_CURRENT_HEAD_REPLAY_SAFETY",
    "supersedes_prior_proposals": False,
}

EXPECTED_DYNAMIC_CATALOG_VALIDATION = {
    "catalog_count_or_digest_embedded": False,
    "catalog_state_source": "VALIDATED_LOCAL_CATALOG_SNAPSHOT_API",
    "exact_snapshot_equality_required": True,
    "first_snapshot_required": True,
    "migration_application_evidence": False,
    "second_snapshot_required": True,
    "shared_environment_evidence": False,
    "validation_scope": "VERSIONED_SOURCE_ONLY",
}

EXPECTED_ENVIRONMENT_TRACKS = {
    "DEV": {
        "append_only_behavior_evidence": "PENDING_SEPARATE_EVIDENCE",
        "cutover_decision": "BLOCKED",
        "data_api_evidence": "PENDING_SEPARATE_PLATFORM_EVIDENCE",
        "environment_attestation": "NOT_COMPLETE_FOR_V3",
        "legacy_evidence_classification": "BLOCKED_LEDGER_DIVERGENCE",
        "legacy_ledgers_action": "PRESERVE_WITHOUT_BACKFILL_OR_REWRITE",
        "manual_index_drift_reference": "manual_dev_index_drift",
        "realtime_evidence": "PENDING_SEPARATE_PLATFORM_EVIDENCE",
        "schema_and_data_evidence": "PENDING_SEPARATE_ENVIRONMENT_EVIDENCE",
    },
    "PROD": {
        "append_only_behavior_evidence": "PENDING_SEPARATE_EVIDENCE",
        "cutover_decision": "BLOCKED",
        "data_api_evidence": "PENDING_SEPARATE_PLATFORM_EVIDENCE",
        "environment_attestation": "NOT_COMPLETE_FOR_V3",
        "legacy_evidence_classification": "BLOCKED_EVIDENCE_INSUFFICIENT",
        "legacy_ledgers_action": "PRESERVE_WITHOUT_BACKFILL_OR_REWRITE",
        "manual_dev_index_drift_inferred_in_prod": False,
        "realtime_evidence": "PENDING_SEPARATE_PLATFORM_EVIDENCE",
        "schema_and_data_evidence": "PENDING_SEPARATE_ENVIRONMENT_EVIDENCE",
    },
}

EXPECTED_REVIEW = {
    "current_independent_review_complete": False,
    "current_review_state": "PENDING_INDEPENDENT_REVIEW_OF_V3",
    "human_cutover_decision": "NOT_MADE",
    "prior_human_records_apply_to_proposal_id": (
        "migration-history-divergence-remediation-proposal-v1"
    ),
    "prior_human_records_reused_for_v3": False,
}

EXPECTED_PRESERVED_V3_STATE = {
    "environment_tracks": EXPECTED_ENVIRONMENT_TRACKS,
    "review": EXPECTED_REVIEW,
    "state_source_proposal_id": (
        "migration-history-divergence-remediation-proposal-v3"
    ),
    "state_source_sha256": EXPECTED_HISTORICAL_CONTRACTS["v3_proposal"][
        "sha256"
    ],
    "v4_cutover_decision_made": False,
    "v4_environment_evidence_added": False,
}

EXPECTED_REPOSITORY_ANCHOR = {
    "commit_evidence_scope": (
        "VERSIONED_SOURCE_ANCHOR_ONLY_NOT_LIVE_ENVIRONMENT_EVIDENCE"
    ),
    "repository_commit_sha": EXPECTED_REPOSITORY_COMMIT_SHA,
    "source_artifacts": EXPECTED_SOURCE_ARTIFACTS,
}

EXPECTED_NEXT_GATE = {
    "authorized": False,
    "id": "OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_SAFETY_R1",
    "scope": (
        "REMOTE_READ_PREFLIGHT_PUSH_PR_AND_CI_ONLY_NO_MERGE_OR_SHARED_ENVIRONMENT"
    ),
}

EXPECTED_PROPOSAL = {
    "artifact_state": "OFFLINE_SOURCE_SAFETY_EXTENSION_BLOCKED",
    "contract_version": "4.0",
    "current_permissions": EXPECTED_PERMISSIONS,
    "dynamic_catalog_validation": EXPECTED_DYNAMIC_CATALOG_VALIDATION,
    "extension_contract": EXPECTED_EXTENSION_CONTRACT,
    "historical_contracts": EXPECTED_HISTORICAL_CONTRACTS,
    "next_gate": EXPECTED_NEXT_GATE,
    "next_stage_authorized": False,
    "operational_authorization": False,
    "preserved_v3_state": EXPECTED_PRESERVED_V3_STATE,
    "proposal_id": "migration-history-divergence-remediation-proposal-v4",
    "repository_anchor": EXPECTED_REPOSITORY_ANCHOR,
    "verification_result": {
        "state": "BLOCKED_SOURCE_EXTENSION_VERIFIED_OFFLINE",
        "valid_exit_code": BLOCKED_EXIT,
    },
}
EXPECTED_TOP_LEVEL_KEYS = set(EXPECTED_PROPOSAL)


class VerificationError(RuntimeError):
    exit_code = 4
    reason = "CONTRACT_INVALID"


class UsageError(VerificationError):
    exit_code = 2
    reason = "USAGE"


class ArtifactIoError(VerificationError):
    exit_code = 3
    reason = "ARTIFACT_IO_INVALID"


class HistoricalDriftError(VerificationError):
    exit_code = 5
    reason = "HISTORICAL_OR_SOURCE_ANCHOR_DRIFT"


class CatalogDriftError(VerificationError):
    exit_code = 6
    reason = "DYNAMIC_CATALOG_DRIFT"


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


def _read_stable_bytes(
    path: Path,
    *,
    expected_sha256: str,
    max_bytes: int,
    drift_error: bool = False,
) -> bytes:
    """Read one fixed regular single-link file and authenticate exact bytes."""

    error_type = HistoricalDriftError if drift_error else ArtifactIoError
    if not path.is_absolute() or any(
        component in {"", ".", ".."} for component in path.parts[1:]
    ):
        raise error_type
    required_flags = ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, flag) for flag in required_flags):
        raise error_type
    flags = os.O_RDONLY
    for flag in required_flags:
        flags |= getattr(os, flag)
    try:
        descriptor = os.open(path, flags)
    except (OSError, TypeError, ValueError) as exc:
        raise error_type from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > max_bytes
        ):
            raise error_type
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise error_type
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(content) != before.st_size
            or _stat_snapshot(before) != _stat_snapshot(after)
            or hashlib.sha256(content).hexdigest() != expected_sha256
        ):
            raise error_type
        return content
    except OSError as exc:
        raise error_type from exc
    finally:
        os.close(descriptor)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise VerificationError
        value[key] = item
    return value


def _reject_non_integer_number(_value: str) -> Any:
    raise VerificationError


def _decode_json(content: bytes) -> dict[str, Any]:
    if content.startswith(b"\xef\xbb\xbf"):
        raise VerificationError
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_non_integer_number,
            parse_constant=_reject_non_integer_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError from exc
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


def validate_proposal(proposal: dict[str, Any]) -> None:
    """Require the exact deny-state v4 document, including every false gate."""

    _require_exact(proposal, EXPECTED_PROPOSAL)
    serialized = json.dumps(
        proposal, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).casefold()
    for forbidden in (
        "database_url",
        "postgres://",
        "postgresql://",
        "project_ref",
        "service_role_key",
    ):
        if forbidden in serialized:
            raise VerificationError


def _validate_schema_document(schema: dict[str, Any]) -> None:
    expected_root_keys = {
        "$id",
        "$schema",
        "additionalProperties",
        "properties",
        "required",
        "title",
        "type",
    }
    if set(schema) != expected_root_keys:
        raise VerificationError
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise VerificationError
    if schema.get("$id") != (
        "https://igreja12.invalid/schemas/"
        "migration-history-divergence-remediation-proposal-v4.json"
    ):
        raise VerificationError
    if schema.get("title") != (
        "Migration history divergence remediation proposal v4"
    ):
        raise VerificationError
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise VerificationError
    if schema.get("required") != sorted(EXPECTED_TOP_LEVEL_KEYS):
        raise VerificationError
    properties = schema.get("properties")
    if type(properties) is not dict or set(properties) != EXPECTED_TOP_LEVEL_KEYS:
        raise VerificationError
    for key, expected in EXPECTED_PROPOSAL.items():
        if not _exact_json(properties.get(key), {"const": expected}):
            raise VerificationError


def _validate_schema_instance(
    instance: dict[str, Any], schema: dict[str, Any]
) -> None:
    _validate_schema_document(schema)
    _require_exact(instance, EXPECTED_PROPOSAL)


def _load_snapshot_api() -> ModuleType:
    """Execute only the exact, source-pinned snapshot API bytes."""

    content = _read_stable_bytes(
        SNAPSHOT_API_PATH,
        expected_sha256=EXPECTED_SOURCE_ARTIFACTS["catalog_snapshot_api"][
            "sha256"
        ],
        max_bytes=MAX_SOURCE_BYTES,
        drift_error=True,
    )
    module_name = (
        "_pastorai_migration_divergence_v4_snapshot_"
        + hashlib.sha256(__name__.encode("utf-8")).hexdigest()[:16]
    )
    if module_name in sys.modules:
        raise HistoricalDriftError
    module = ModuleType(module_name)
    module.__file__ = str(SNAPSHOT_API_PATH)
    module.__package__ = ""
    module.__spec__ = None
    sys.modules[module_name] = module
    try:
        code = compile(
            content,
            str(SNAPSHOT_API_PATH),
            "exec",
            dont_inherit=True,
        )
        exec(code, module.__dict__)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise HistoricalDriftError from exc
    return module


SNAPSHOT_API: ModuleType | None = None


def _snapshot_api() -> ModuleType:
    """Load the authenticated snapshot API only after CLI validation."""

    global SNAPSHOT_API
    if SNAPSHOT_API is None:
        SNAPSHOT_API = _load_snapshot_api()
    return SNAPSHOT_API


def _catalog_snapshot_signature() -> tuple[Any, ...]:
    try:
        snapshot = _snapshot_api().validated_local_catalog_snapshot()
        entries = snapshot.entries
        if type(entries) is not tuple or not entries:
            raise CatalogDriftError
        entry_signature: list[tuple[int, str, str, int]] = []
        names: set[str] = set()
        for expected_position, entry in enumerate(entries):
            if (
                type(entry.position) is not int
                or entry.position != expected_position
                or type(entry.name) is not str
                or not entry.name
                or entry.name in names
                or type(entry.sha256) is not str
                or len(entry.sha256) != 64
                or any(character not in "0123456789abcdef" for character in entry.sha256)
                or type(entry.size_bytes) is not int
                or entry.size_bytes < 0
            ):
                raise CatalogDriftError
            names.add(entry.name)
            entry_signature.append(
                (entry.position, entry.name, entry.sha256, entry.size_bytes)
            )
        if snapshot.operational_authorization is not False:
            raise CatalogDriftError
        if snapshot.next_stage_authorized is not False:
            raise CatalogDriftError
        if Path(snapshot.catalog_directory) != MIGRATIONS_DIR.absolute():
            raise CatalogDriftError
        for digest in (
            snapshot.head_content_sha256,
            snapshot.schema_content_sha256,
            snapshot.catalog_digest_sha256,
        ):
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise CatalogDriftError
        return (
            snapshot.head_content_sha256,
            snapshot.schema_content_sha256,
            snapshot.catalog_digest_sha256,
            snapshot.catalog_directory,
            tuple(entry_signature),
            snapshot.operational_authorization,
            snapshot.next_stage_authorized,
        )
    except CatalogDriftError:
        raise
    except Exception as exc:
        raise CatalogDriftError from exc


def _validate_historical_contracts() -> None:
    contents: dict[str, bytes] = {}
    for name, contract in EXPECTED_HISTORICAL_CONTRACTS.items():
        contents[name] = _read_stable_bytes(
            REPO_ROOT / contract["path"],
            expected_sha256=contract["sha256"],
            max_bytes=MAX_SOURCE_BYTES,
            drift_error=True,
        )

    v1 = _decode_json(contents["v1_proposal"])
    v2 = _decode_json(contents["v2_proposal"])
    v3 = _decode_json(contents["v3_proposal"])
    if v1.get("proposal_id") != (
        "migration-history-divergence-remediation-proposal-v1"
    ):
        raise HistoricalDriftError
    if v2.get("proposal_id") != (
        "migration-history-divergence-remediation-proposal-v2"
    ):
        raise HistoricalDriftError
    if v3.get("proposal_id") != (
        "migration-history-divergence-remediation-proposal-v3"
    ):
        raise HistoricalDriftError
    if not _exact_json(v3.get("environment_tracks"), EXPECTED_ENVIRONMENT_TRACKS):
        raise HistoricalDriftError
    if not _exact_json(v3.get("review"), EXPECTED_REVIEW):
        raise HistoricalDriftError


def _validate_source_artifacts() -> None:
    for contract in EXPECTED_SOURCE_ARTIFACTS.values():
        _read_stable_bytes(
            REPO_ROOT / contract["path"],
            expected_sha256=contract["sha256"],
            max_bytes=MAX_SOURCE_BYTES,
            drift_error=True,
        )


def _validate_dynamic_catalog() -> tuple[Any, ...]:
    first = _catalog_snapshot_signature()
    second = _catalog_snapshot_signature()
    if first != second:
        raise CatalogDriftError
    return first


def verify_versioned_package() -> None:
    first_catalog_snapshot = _catalog_snapshot_signature()
    proposal_content = _read_stable_bytes(
        PROPOSAL_PATH,
        expected_sha256=EXPECTED_PROPOSAL_SHA256,
        max_bytes=MAX_JSON_BYTES,
    )
    schema_content = _read_stable_bytes(
        SCHEMA_PATH,
        expected_sha256=EXPECTED_SCHEMA_SHA256,
        max_bytes=MAX_JSON_BYTES,
    )
    proposal = _decode_json(proposal_content)
    schema = _decode_json(schema_content)
    validate_proposal(proposal)
    _validate_schema_instance(proposal, schema)
    _validate_historical_contracts()
    _validate_source_artifacts()
    second_catalog_snapshot = _catalog_snapshot_signature()
    if first_catalog_snapshot != second_catalog_snapshot:
        raise CatalogDriftError


def main() -> int:
    try:
        if len(sys.argv) != 1:
            raise UsageError
        verify_versioned_package()
    except VerificationError as exc:
        print(f"RESULT=BLOCKED_MIGRATION_DIVERGENCE_V4:{exc.reason}")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return exc.exit_code
    print(VERIFIED_RESULT)
    print("PROPOSAL_STRUCTURE=VERIFIED_SOURCE_ONLY")
    print("CATALOG_SNAPSHOTS=2_STABLE_EQUAL")
    print("V3_ENVIRONMENT_AND_CUTOVER_STATE=PRESERVED_UNCHANGED")
    print(OPERATIONAL_BLOCK)
    print(NEXT_STAGE_BLOCK)
    return BLOCKED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
