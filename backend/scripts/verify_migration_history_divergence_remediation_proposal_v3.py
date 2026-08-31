#!/usr/bin/env python3
"""Verify the blocked migration epoch-cutover v3 decision package offline.

The verifier reads only fixed, versioned local files. It never consults an
environment, database, process environment, network service, subprocess, or
runner. A valid package still exits blocked because review and all environment
evidence remain pending.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_DIR = REPO_ROOT / "docs" / "governance" / "migrations"
PROPOSAL_PATH = (
    GOVERNANCE_DIR
    / "migration-history-divergence-remediation-proposal-v3.json"
)
SCHEMA_PATH = (
    GOVERNANCE_DIR
    / "migration-history-divergence-remediation-proposal-v3.schema.json"
)
V1_PROPOSAL_PATH = (
    GOVERNANCE_DIR
    / "migration-history-divergence-remediation-proposal-v1.json"
)
V2_PROPOSAL_PATH = (
    GOVERNANCE_DIR
    / "migration-history-divergence-remediation-proposal-v2.json"
)
ATTESTATION_PROFILE_PATH = (
    GOVERNANCE_DIR / "migration-history-environment-attestation-profile-v1.json"
)
ATTESTATION_SCHEMA_PATH = (
    GOVERNANCE_DIR / "migration-history-environment-attestation.schema.json"
)
CANONICAL_FINGERPRINT_PATH = (
    GOVERNANCE_DIR / "migration-history-canonical-schema-fingerprint-v1.json"
)
CATALOG_TEMPLATE_PATH = (
    GOVERNANCE_DIR
    / "packets"
    / "migration-history-reconciliation-template-v1.json"
)
MIGRATIONS_DIR = REPO_ROOT / "backend" / "migrations"
RUNNER_PATH = REPO_ROOT / "backend" / "scripts" / "apply_migrations.py"
RECONCILIATION_VERIFIER_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "verify_migration_history_reconciliation.py"
)

MAX_JSON_BYTES = 1_048_576
MAX_MIGRATION_BYTES = 4_194_304
MAX_CATALOG_BYTES = 67_108_864
MAX_SCHEMA_DEPTH = 64
BLOCKED_EXIT = 8
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
NEXT_STAGE_BLOCK = "NEXT_STAGE_AUTHORIZED=false"
VERIFIED_RESULT = "RESULT=BLOCKED_MIGRATION_EPOCH_V3:PENDING_SEPARATE_EVIDENCE"

EXPECTED_HASHES = {
    "attestation_profile": (
        "0734ba9302bf9d20f0b5770745124390350d231650fdb95ef915ee1b526d5147"
    ),
    "attestation_schema": (
        "6286f68864ff935156c4c19be74123bfdd06043d50bdfc4ad34844df321d9964"
    ),
    "canonical_fingerprint": (
        "dfe84378ed13e7f8fe66210503d91f3c5015603cfd6a559b8862e7dc3e096c7a"
    ),
    "catalog_template": (
        "8841de3546241c1975bbf1fd3f99185b043de7f02de4925b6e12dadaeab0eb32"
    ),
    "proposal": (
        "076d04ed179c5128c4707c07cacd8240896101a9bea62e328d2d0569900cd10e"
    ),
    "reconciliation_verifier": (
        "9451cbe5054d8c0d7e2754d09dea7f3a9761e8585269ca783eea943dd785dfae"
    ),
    "runner": (
        "36e63cde6751cd0cb33e1511091068b0b04f10029ace06703eead82e0e836c65"
    ),
    "schema": (
        "88f7972780f07c7071bb4e4292e1f21c258fff47daf2ab207fc709ff34631b38"
    ),
    "v1_proposal": (
        "84614e0b140e38d07c11ed4ceb10025b3dbc85b121684da1e1ebdca6d0104e7d"
    ),
    "v2_proposal": (
        "f1db4a0f1b6a5045fefa674d6092ecb8afe90a0c03c70044b53a1d021b2b8340"
    ),
}

EXPECTED_TOP_LEVEL_KEYS = {
    "amendment",
    "artifact_state",
    "contract_version",
    "current_permissions",
    "environment_tracks",
    "epoch_strategy",
    "evidence_gates",
    "historical_evidence",
    "manual_dev_index_drift",
    "next_gate",
    "next_stage_authorized",
    "operational_authorization",
    "proposal_id",
    "repository_base_sha",
    "review",
    "runner_contract",
}

EXPECTED_AMENDMENT = {
    "amendment_reason": (
        "ATTESTATION_V1_RECLASSIFIED_AS_BLOCKED_ENVELOPE_AND_KNOWN_DEV_INDEX_"
        "DRIFT_REQUIRES_SEPARATE_EVIDENCE"
    ),
    "historical_artifacts_remain_unchanged": True,
    "prior_human_records_apply_to_proposal_id": (
        "migration-history-divergence-remediation-proposal-v1"
    ),
    "prior_human_records_reused_for_v3": False,
    "supersedes_proposal_id": (
        "migration-history-divergence-remediation-proposal-v2"
    ),
    "supersedes_sha256": EXPECTED_HASHES["v2_proposal"],
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
    "migration_application_allowed": False,
    "runner_change_allowed": False,
    "runner_execution_allowed": False,
    "runtime_change_allowed": False,
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

EXPECTED_EPOCH_STRATEGY = {
    "automatic_backfill": "PROHIBITED",
    "cross_environment_decision_reuse": "PROHIBITED",
    "historical_inference": "PROHIBITED",
    "legacy_ledgers": "PRESERVE_AS_INDEPENDENT_HISTORICAL_RECORDS",
    "manual_dev_drift_treatment": (
        "PRESERVE_AND_VERSION_FORWARD_ONLY_AFTER_SEPARATE_ATTESTATION_REVIEW_"
        "AND_HUMAN_DECISION"
    ),
    "recommended": "CONTROLLED_EPOCH_CUTOVER_AFTER_COMPLETE_SEPARATE_EVIDENCE",
    "status": "RECOMMENDATION_ONLY_NOT_APPROVED",
    "target_implementation": "NOT_DESIGNED_OR_AUTHORIZED",
}

EXPECTED_EVIDENCE_GATES = {
    "APPEND_ONLY_BEHAVIOR": {
        "environment_scope": ["DEV", "PROD"],
        "snapshot_is_sufficient": False,
        "state": "PENDING_SEPARATE_EVIDENCE",
    },
    "DATA_API": {
        "environment_scope": ["DEV", "PROD"],
        "inferred_from_database_schema": False,
        "state": "PENDING_SEPARATE_PLATFORM_EVIDENCE",
    },
    "ENVIRONMENT_SCHEMA_AND_DATA": {
        "environment_scope": ["DEV", "PROD"],
        "one_environment_can_satisfy_another": False,
        "state": "PENDING_SEPARATE_ENVIRONMENT_EVIDENCE",
    },
    "INDEPENDENT_REVIEW": {
        "prior_review_reused": False,
        "state": "PENDING_INDEPENDENT_REVIEW_OF_V3",
    },
    "MANUAL_DEV_INDEX_DRIFT": {
        "definitions_attested": False,
        "environment_scope": ["DEV"],
        "presence_attested": False,
        "state": "KNOWN_UNVERIFIED_DRIFT",
    },
    "REALTIME": {
        "environment_scope": ["DEV", "PROD"],
        "inferred_from_database_schema": False,
        "state": "PENDING_SEPARATE_PLATFORM_EVIDENCE",
    },
}

EXPECTED_HISTORICAL_EVIDENCE = {
    "attestation_v1": {
        "environment_attestation_complete": False,
        "profile_id": "migration-history-environment-attestation-profile-v1",
        "profile_sha256": EXPECTED_HASHES["attestation_profile"],
        "role": "BLOCKED_ENVELOPE_ONLY_NOT_COMPLETION_EVIDENCE",
        "schema_sha256": EXPECTED_HASHES["attestation_schema"],
        "surfaces": {
            "data_api": "PLATFORM_SURFACE_REQUIRES_SEPARATE_EVIDENCE",
            "realtime": "PLATFORM_SURFACE_REQUIRES_SEPARATE_EVIDENCE",
        },
    },
    "canonical_derivation": {
        "artifact_sha256": EXPECTED_HASHES["canonical_fingerprint"],
        "canonical_schema_fingerprint_sha256": (
            "8ac17d4352a77fb3c5885f9c1a55813a5b7dfcd6fb84c4bd4e9117c1c7883370"
        ),
        "environment_attestation_complete": False,
        "scope": "OFFLINE_PG17_LAB_SOURCE_EXPECTATION_ONLY",
    },
    "source_catalog": {
        "digest_sha256": (
            "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f"
        ),
        "migration_count": 75,
        "scope": "VERSIONED_SOURCE_BASELINE_ONLY",
    },
    "v1_proposal_sha256": EXPECTED_HASHES["v1_proposal"],
    "v2_proposal_sha256": EXPECTED_HASHES["v2_proposal"],
}

EXPECTED_INDEX_BASENAMES = [
    "idx_pessoas_igreja_ativa_created",
    "idx_pessoas_igreja_ativa_tipo",
    "idx_celulas_igreja_ativo_lider",
    "idx_work_queue_igreja_status_responsavel",
    "idx_conversations_igreja_assumido",
    "idx_app_users_igreja_nome",
    "idx_user_roles_igreja_user",
]

EXPECTED_MANUAL_DEV_DRIFT = {
    "basenames": EXPECTED_INDEX_BASENAMES,
    "catalog_application_inferred": False,
    "classification": "KNOWN_UNVERIFIED_DRIFT",
    "current_presence_attested": False,
    "definition_hashes_attested": False,
    "environment": "DEV",
    "forward_only_requirement": (
        "PRESERVE_AND_VERSION_ONLY_AFTER_SEPARATE_EVIDENCE_AND_APPROVAL"
    ),
    "prior_report_is_current_environment_proof": False,
    "provenance": "PRIOR_OPERATOR_REPORT_ONLY",
    "prod_presence_inferred": False,
}

EXPECTED_NEXT_GATE = {
    "authorized": False,
    "id": "REVIEW_AND_CI_OFFLINE_AGENT_FOUNDATION_BATCH_PR",
    "scope": "OFFLINE_BATCH_REVIEW_AND_CI_ONLY_NO_CUTOVER_AUTHORIZATION",
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

EXPECTED_RUNNER_CONTRACT = {
    "apply_migrations_sha256": EXPECTED_HASHES["runner"],
    "commands_remain_blocked": [
        "bootstrap-ledger",
        "harden-ledger",
        "status",
        "apply",
    ],
    "must_remain_unchanged_in_this_mission": True,
    "proposal_is_not_a_runner_input": True,
    "reconciliation_verifier_sha256": EXPECTED_HASHES[
        "reconciliation_verifier"
    ],
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


class HistoricalDriftError(VerificationError):
    exit_code = 5
    reason = "HISTORICAL_OR_CATALOG_DRIFT"


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
    max_bytes: int = MAX_JSON_BYTES,
    drift_error: bool = False,
) -> bytes:
    error_type = HistoricalDriftError if drift_error else ArtifactIoError
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise error_type
        if before.st_size <= 0 or before.st_size > max_bytes:
            raise error_type
        content = path.read_bytes()
        after = path.lstat()
    except OSError as exc:
        raise error_type from exc
    if (
        len(content) != before.st_size
        or _stat_snapshot(before) != _stat_snapshot(after)
        or hashlib.sha256(content).hexdigest() != expected_sha256
    ):
        raise error_type
    return content


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise VerificationError
        value[key] = item
    return value


def _decode_json(content: bytes) -> dict[str, Any]:
    if content.startswith(b"\xef\xbb\xbf"):
        raise VerificationError
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=lambda _value: (_ for _ in ()).throw(
                VerificationError()
            ),
            parse_constant=lambda _value: (_ for _ in ()).throw(
                VerificationError()
            ),
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
    """Validate the in-memory v3 proposal without any external effects."""

    if type(proposal) is not dict or set(proposal) != EXPECTED_TOP_LEVEL_KEYS:
        raise VerificationError
    if proposal["artifact_state"] != (
        "OFFLINE_EPOCH_CUTOVER_DECISION_PACKAGE_BLOCKED"
    ):
        raise VerificationError
    if proposal["contract_version"] != "3.0":
        raise VerificationError
    if proposal["proposal_id"] != (
        "migration-history-divergence-remediation-proposal-v3"
    ):
        raise VerificationError
    if proposal["repository_base_sha"] != (
        "0f8c6a77bf489f9080743ab3f7ce71097d361aea"
    ):
        raise VerificationError
    if proposal["operational_authorization"] is not False:
        raise VerificationError
    if proposal["next_stage_authorized"] is not False:
        raise VerificationError

    _require_exact(proposal["amendment"], EXPECTED_AMENDMENT)
    _require_exact(proposal["current_permissions"], EXPECTED_PERMISSIONS)
    _require_exact(proposal["environment_tracks"], EXPECTED_ENVIRONMENT_TRACKS)
    _require_exact(proposal["epoch_strategy"], EXPECTED_EPOCH_STRATEGY)
    _require_exact(proposal["evidence_gates"], EXPECTED_EVIDENCE_GATES)
    _require_exact(
        proposal["historical_evidence"], EXPECTED_HISTORICAL_EVIDENCE
    )
    _require_exact(proposal["manual_dev_index_drift"], EXPECTED_MANUAL_DEV_DRIFT)
    _require_exact(proposal["next_gate"], EXPECTED_NEXT_GATE)
    _require_exact(proposal["review"], EXPECTED_REVIEW)
    _require_exact(proposal["runner_contract"], EXPECTED_RUNNER_CONTRACT)

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
    expected_keys = {
        "$schema",
        "$id",
        "$defs",
        "additionalProperties",
        "properties",
        "required",
        "title",
        "type",
    }
    if set(schema) != expected_keys:
        raise VerificationError
    required = sorted(EXPECTED_TOP_LEVEL_KEYS)
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise VerificationError
    if schema.get("$id") != (
        "https://igreja12.invalid/schemas/"
        "migration-history-divergence-remediation-proposal-v3.json"
    ):
        raise VerificationError
    if schema.get("title") != (
        "Migration history divergence remediation proposal v3"
    ):
        raise VerificationError
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
    ):
        raise VerificationError
    if schema.get("required") != required:
        raise VerificationError
    definitions = schema.get("$defs")
    if type(definitions) is not dict or set(definitions) != {
        "dev_environment_track",
        "false_permissions",
        "prod_environment_track",
    }:
        raise VerificationError
    properties = schema.get("properties")
    if type(properties) is not dict or set(properties) != EXPECTED_TOP_LEVEL_KEYS:
        raise VerificationError
    if properties.get("operational_authorization") != {"const": False}:
        raise VerificationError
    if properties.get("next_stage_authorized") != {"const": False}:
        raise VerificationError
    if properties.get("artifact_state") != {
        "const": "OFFLINE_EPOCH_CUTOVER_DECISION_PACKAGE_BLOCKED"
    }:
        raise VerificationError
    manual = properties.get("manual_dev_index_drift")
    if type(manual) is not dict or manual.get("additionalProperties") is not False:
        raise VerificationError
    if manual.get("properties", {}).get("classification") != {
        "const": "KNOWN_UNVERIFIED_DRIFT"
    }:
        raise VerificationError


def _resolve_schema_ref(
    root_schema: dict[str, Any], reference: Any
) -> dict[str, Any]:
    prefix = "#/$defs/"
    if (
        type(reference) is not str
        or not reference.startswith(prefix)
        or "/" in reference[len(prefix) :]
        or not reference[len(prefix) :]
    ):
        raise VerificationError
    definitions = root_schema.get("$defs")
    if type(definitions) is not dict:
        raise VerificationError
    target = definitions.get(reference[len(prefix) :])
    if type(target) is not dict:
        raise VerificationError
    return target


def _validate_schema_instance(
    instance: Any,
    schema_node: dict[str, Any],
    root_schema: dict[str, Any],
    *,
    depth: int = 0,
) -> None:
    """Validate the proposal with the closed stdlib-only schema subset."""

    if depth > MAX_SCHEMA_DEPTH or type(schema_node) is not dict:
        raise VerificationError
    if "$ref" in schema_node:
        if set(schema_node) != {"$ref"}:
            raise VerificationError
        _validate_schema_instance(
            instance,
            _resolve_schema_ref(root_schema, schema_node["$ref"]),
            root_schema,
            depth=depth + 1,
        )
        return
    if "const" in schema_node:
        if set(schema_node) != {"const"} or not _exact_json(
            instance, schema_node["const"]
        ):
            raise VerificationError
        return
    if schema_node.get("type") != "object" or type(instance) is not dict:
        raise VerificationError
    properties = schema_node.get("properties")
    required = schema_node.get("required")
    if (
        type(properties) is not dict
        or type(required) is not list
        or any(type(key) is not str for key in required)
        or len(required) != len(set(required))
        or schema_node.get("additionalProperties") is not False
    ):
        raise VerificationError
    required_keys = set(required)
    if not required_keys.issubset(instance):
        raise VerificationError
    if not set(instance).issubset(properties):
        raise VerificationError
    for key, value in instance.items():
        child_schema = properties.get(key)
        if type(child_schema) is not dict:
            raise VerificationError
        _validate_schema_instance(
            value,
            child_schema,
            root_schema,
            depth=depth + 1,
        )


def _assert_schema_verifier_parity(
    expected_instance: Any,
    schema_node: dict[str, Any],
    root_schema: dict[str, Any],
    *,
    depth: int = 0,
    root: bool = False,
) -> None:
    """Require the schema to encode exactly the verifier's expected value."""

    if depth > MAX_SCHEMA_DEPTH or type(schema_node) is not dict:
        raise VerificationError
    if "$ref" in schema_node:
        if set(schema_node) != {"$ref"}:
            raise VerificationError
        _assert_schema_verifier_parity(
            expected_instance,
            _resolve_schema_ref(root_schema, schema_node["$ref"]),
            root_schema,
            depth=depth + 1,
        )
        return
    if type(expected_instance) is not dict:
        if set(schema_node) != {"const"} or not _exact_json(
            schema_node["const"], expected_instance
        ):
            raise VerificationError
        return

    allowed_keys = {
        "additionalProperties",
        "properties",
        "required",
        "type",
    }
    if root:
        allowed_keys.update({"$defs", "$id", "$schema", "title"})
    if set(schema_node) != allowed_keys:
        raise VerificationError
    properties = schema_node.get("properties")
    required = schema_node.get("required")
    if (
        schema_node.get("type") != "object"
        or schema_node.get("additionalProperties") is not False
        or type(properties) is not dict
        or set(properties) != set(expected_instance)
        or type(required) is not list
        or len(required) != len(set(required))
        or set(required) != set(expected_instance)
    ):
        raise VerificationError
    for key, value in expected_instance.items():
        child_schema = properties.get(key)
        if type(child_schema) is not dict:
            raise VerificationError
        _assert_schema_verifier_parity(
            value,
            child_schema,
            root_schema,
            depth=depth + 1,
        )


def _validate_historical_contracts() -> None:
    historical_paths = {
        V1_PROPOSAL_PATH: "v1_proposal",
        V2_PROPOSAL_PATH: "v2_proposal",
        ATTESTATION_PROFILE_PATH: "attestation_profile",
        ATTESTATION_SCHEMA_PATH: "attestation_schema",
        CANONICAL_FINGERPRINT_PATH: "canonical_fingerprint",
        CATALOG_TEMPLATE_PATH: "catalog_template",
        RUNNER_PATH: "runner",
        RECONCILIATION_VERIFIER_PATH: "reconciliation_verifier",
    }
    contents: dict[Path, bytes] = {}
    for path, hash_key in historical_paths.items():
        contents[path] = _read_stable_bytes(
            path,
            expected_sha256=EXPECTED_HASHES[hash_key],
            max_bytes=(MAX_MIGRATION_BYTES if path.suffix == ".py" else MAX_JSON_BYTES),
            drift_error=True,
        )

    profile = _decode_json(contents[ATTESTATION_PROFILE_PATH])
    if profile.get("profile_id") != (
        "migration-history-environment-attestation-profile-v1"
    ):
        raise HistoricalDriftError
    if profile.get("surfaces") != {
        "data_api": "PLATFORM_SURFACES_UNATTESTED",
        "realtime": "PLATFORM_SURFACES_UNATTESTED",
    }:
        raise HistoricalDriftError
    invariants = profile.get("data_invariants")
    if type(invariants) is not list or [
        item.get("id") for item in invariants if type(item) is dict
    ].count("APPEND_ONLY_AUDIT_INTEGRITY") != 1:
        raise HistoricalDriftError

    attestation_schema = _decode_json(contents[ATTESTATION_SCHEMA_PATH])
    attestation_properties = attestation_schema.get("properties")
    if type(attestation_properties) is not dict:
        raise HistoricalDriftError
    if attestation_properties.get("environment_attestation_complete") != {
        "const": False
    }:
        raise HistoricalDriftError
    if attestation_properties.get("operational_authorization") != {"const": False}:
        raise HistoricalDriftError
    append_only_schema = (
        attestation_properties.get("data_invariants", {})
        .get("prefixItems", [{}, {}, {}])[2]
    )
    if "UNKNOWN" not in json.dumps(append_only_schema, sort_keys=True):
        raise HistoricalDriftError

    canonical = _decode_json(contents[CANONICAL_FINGERPRINT_PATH])
    if canonical.get("artifact_state") != (
        "OFFLINE_CANONICAL_SCHEMA_DERIVED_ENVIRONMENTS_UNATTESTED"
    ):
        raise HistoricalDriftError
    if canonical.get("environment_attestation_complete") is not False:
        raise HistoricalDriftError
    if canonical.get("operational_authorization") is not False:
        raise HistoricalDriftError
    if canonical.get("canonical_schema_fingerprint_sha256") != (
        EXPECTED_HISTORICAL_EVIDENCE["canonical_derivation"][
            "canonical_schema_fingerprint_sha256"
        ]
    ):
        raise HistoricalDriftError

    forbidden_reference = b"migration-history-divergence-remediation-proposal-v3"
    if forbidden_reference in contents[RUNNER_PATH]:
        raise HistoricalDriftError
    if forbidden_reference in contents[RECONCILIATION_VERIFIER_PATH]:
        raise HistoricalDriftError


def _validate_catalog_unchanged() -> None:
    template_content = _read_stable_bytes(
        CATALOG_TEMPLATE_PATH,
        expected_sha256=EXPECTED_HASHES["catalog_template"],
        drift_error=True,
    )
    template = _decode_json(template_content)
    catalog = template.get("catalog")
    if type(catalog) is not dict:
        raise HistoricalDriftError
    if catalog.get("digest_sha256") != (
        EXPECTED_HISTORICAL_EVIDENCE["source_catalog"]["digest_sha256"]
    ):
        raise HistoricalDriftError
    entries = catalog.get("entries")
    if type(entries) is not list or len(entries) != 75:
        raise HistoricalDriftError

    try:
        names = sorted(
            path.name
            for path in MIGRATIONS_DIR.iterdir()
            if path.suffix == ".sql"
        )
    except OSError as exc:
        raise HistoricalDriftError from exc
    expected_names = [entry.get("name") for entry in entries]
    if names != expected_names:
        raise HistoricalDriftError

    total_bytes = 0
    for position, entry in enumerate(entries):
        if type(entry) is not dict or set(entry) != {
            "name",
            "position",
            "sha256",
            "size_bytes",
        }:
            raise HistoricalDriftError
        if entry["position"] != position:
            raise HistoricalDriftError
        path = MIGRATIONS_DIR / entry["name"]
        content = _read_stable_bytes(
            path,
            expected_sha256=entry["sha256"],
            max_bytes=MAX_MIGRATION_BYTES,
            drift_error=True,
        )
        if len(content) != entry["size_bytes"]:
            raise HistoricalDriftError
        total_bytes += len(content)
        if total_bytes > MAX_CATALOG_BYTES:
            raise HistoricalDriftError


def verify_versioned_package() -> None:
    proposal_content = _read_stable_bytes(
        PROPOSAL_PATH,
        expected_sha256=EXPECTED_HASHES["proposal"],
    )
    schema_content = _read_stable_bytes(
        SCHEMA_PATH,
        expected_sha256=EXPECTED_HASHES["schema"],
    )
    proposal = _decode_json(proposal_content)
    schema = _decode_json(schema_content)
    validate_proposal(proposal)
    _validate_schema_document(schema)
    _assert_schema_verifier_parity(proposal, schema, schema, root=True)
    _validate_schema_instance(proposal, schema, schema)
    _validate_historical_contracts()
    _validate_catalog_unchanged()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if args:
            raise UsageError
        verify_versioned_package()
    except VerificationError as exc:
        print(f"RESULT=BLOCKED_MIGRATION_EPOCH_V3:{exc.reason}")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return exc.exit_code
    print(VERIFIED_RESULT)
    print("PROPOSAL_STRUCTURE=VERIFIED_OFFLINE_ONLY")
    print("INDEPENDENT_REVIEW=PENDING")
    print("ENVIRONMENT_ATTESTATION_COMPLETE=false")
    print(OPERATIONAL_BLOCK)
    print(NEXT_STAGE_BLOCK)
    return BLOCKED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
