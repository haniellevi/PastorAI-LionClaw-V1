#!/usr/bin/env python3
"""Verify the blocked, source-only private-runtime policy package V5."""

from __future__ import annotations

import json
import hashlib
import importlib.util
from pathlib import Path
import sys

try:
    from private_runtime_policy_v5_pins import V4_ANCHORS, V5_ARTIFACT_PINS
except ImportError:  # pragma: no cover - direct source loading
    _pins_spec = importlib.util.spec_from_file_location(
        "private_runtime_policy_v5_pins_isolated", Path(__file__).with_name("private_runtime_policy_v5_pins.py")
    )
    if _pins_spec is None or _pins_spec.loader is None:
        raise
    _pins_module = importlib.util.module_from_spec(_pins_spec)
    sys.modules[_pins_spec.name] = _pins_module
    _pins_spec.loader.exec_module(_pins_module)
    V4_ANCHORS = _pins_module.V4_ANCHORS
    V5_ARTIFACT_PINS = _pins_module.V5_ARTIFACT_PINS


REPO_ROOT = Path(__file__).absolute().parents[2]
PROPOSAL_PATH = REPO_ROOT / "docs" / "governance" / "migrations" / "migration-history-divergence-remediation-proposal-v5.json"
SCHEMA_PATH = REPO_ROOT / "docs" / "governance" / "migrations" / "migration-history-divergence-remediation-proposal-v5.schema.json"
PINS_PATH = REPO_ROOT / "backend" / "scripts" / "private_runtime_policy_v5_pins.py"
RESULT = "RESULT=BLOCKED_MIGRATION_DIVERGENCE_V5:PRIVATE_RUNTIME_POLICY_ONLY"

EXPECTED_TOP_LEVEL_KEYS = {
    "proposal_id", "extends_proposal_id", "status", "operational_authorization",
    "next_stage_authorized", "source_only", "catalog_migration_created", "anchors",
    "private_runtime",
}
EXPECTED_ANCHOR_KEYS = {
    "v4_proposal_sha256", "v4_schema_sha256", "v4_verifier_sha256",
    "intent_v2_sha256", "author_sha256", "replay_sha256", "tests_sha256",
    "v5_schema_sha256", "v5_verifier_sha256", "workflow_sha256",
}
EXPECTED_RUNTIME_KEYS = {
    "intent_artifact_id", "intent_prefix", "scope", "authoring_script", "replay_script",
    "replay_implemented", "pg17_evidence", "cross_tenant_evidence",
    "policy_directory", "schema", "runtime_role", "tenant_function",
    "helper_function_security", "projection_function", "projection_function_security",
    "function_volatility", "helper_function_search_path", "projection_function_search_path",
    "direct_public_grants_allowed", "runtime_write_privileges_allowed", "memberships_allowed", "gates",
}


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError from exc


def _sha256(relative_path: str) -> str:
    path = REPO_ROOT / relative_path
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise RuntimeError from exc
    return hashlib.sha256(content).hexdigest()


def _validate_schema_shape(schema: dict[str, object]) -> None:
    """Validate the checked-in schema's closed-object promise without extras."""

    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise RuntimeError
    if set(schema.get("required", [])) != EXPECTED_TOP_LEVEL_KEYS:
        raise RuntimeError
    properties = schema.get("properties")
    if not isinstance(properties, dict) or set(properties) != EXPECTED_TOP_LEVEL_KEYS:
        raise RuntimeError
    anchors = properties.get("anchors")
    runtime = properties.get("private_runtime")
    if not isinstance(anchors, dict) or anchors.get("additionalProperties") is not False:
        raise RuntimeError
    if set(anchors.get("required", [])) != EXPECTED_ANCHOR_KEYS:
        raise RuntimeError
    if not isinstance(anchors.get("properties"), dict) or set(anchors["properties"]) != EXPECTED_ANCHOR_KEYS:
        raise RuntimeError
    if not isinstance(runtime, dict) or runtime.get("additionalProperties") is not False:
        raise RuntimeError
    if set(runtime.get("required", [])) != EXPECTED_RUNTIME_KEYS:
        raise RuntimeError
    if not isinstance(runtime.get("properties"), dict) or set(runtime["properties"]) != EXPECTED_RUNTIME_KEYS:
        raise RuntimeError


def verify() -> dict[str, object]:
    proposal = _load(PROPOSAL_PATH)
    schema = _load(SCHEMA_PATH)
    if not isinstance(proposal, dict) or not isinstance(schema, dict):
        raise RuntimeError
    _validate_schema_shape(schema)
    if set(proposal) != EXPECTED_TOP_LEVEL_KEYS:
        raise RuntimeError
    if proposal["proposal_id"] != "migration-history-divergence-remediation-proposal-v5":
        raise RuntimeError
    if proposal["extends_proposal_id"] != "migration-history-divergence-remediation-proposal-v4":
        raise RuntimeError
    if proposal["status"] != "POLICY_ONLY_NOT_APPROVED":
        raise RuntimeError
    if proposal["operational_authorization"] is not False or proposal["next_stage_authorized"] is not False:
        raise RuntimeError
    if proposal["source_only"] is not True or proposal["catalog_migration_created"] is not False:
        raise RuntimeError
    anchors = proposal["anchors"]
    if not isinstance(anchors, dict) or set(anchors) != EXPECTED_ANCHOR_KEYS:
        raise RuntimeError
    anchor_paths = {
        "v4_proposal_sha256": "docs/governance/migrations/migration-history-divergence-remediation-proposal-v4.json",
        "v4_schema_sha256": "docs/governance/migrations/migration-history-divergence-remediation-proposal-v4.schema.json",
        "v4_verifier_sha256": "backend/scripts/verify_migration_history_divergence_remediation_proposal_v4.py",
        "intent_v2_sha256": "backend/scripts/private_runtime_intent_v2.py",
        "author_sha256": "backend/scripts/new_private_runtime_migration.py",
        "replay_sha256": "backend/scripts/replay_private_runtime_migration_pg17.py",
        "tests_sha256": "backend/tests/test_private_runtime_migration_policy.py",
        "v5_schema_sha256": "docs/governance/migrations/migration-history-divergence-remediation-proposal-v5.schema.json",
        "v5_verifier_sha256": "backend/scripts/verify_migration_history_divergence_remediation_proposal_v5.py",
        "workflow_sha256": ".github/workflows/private-runtime-policy-v5.yml",
    }
    if any(type(value) is not str or len(value) != 64 for value in anchors.values()):
        raise RuntimeError
    for key, value in V4_ANCHORS.items():
        if anchors[key] != value:
            raise RuntimeError
    if set(V5_ARTIFACT_PINS) != {
        "intent_v2_sha256", "author_sha256", "replay_sha256", "tests_sha256",
        "v5_schema_sha256", "v5_verifier_sha256", "workflow_sha256",
    }:
        raise RuntimeError
    if any(anchors[key] != V5_ARTIFACT_PINS[key] for key in V5_ARTIFACT_PINS):
        raise RuntimeError
    if any(anchors[key] != _sha256(path) for key, path in anchor_paths.items()):
        raise RuntimeError
    runtime = proposal["private_runtime"]
    if not isinstance(runtime, dict):
        raise RuntimeError
    expected = {
        "intent_artifact_id": "migration-authoring-intent-v2",
        "intent_prefix": "PASTORAI_MIGRATION_INTENT_V2",
        "scope": "PRIVATE_RUNTIME",
        "authoring_script": "backend/scripts/new_private_runtime_migration.py",
        "replay_script": "backend/scripts/replay_private_runtime_migration_pg17.py",
        "replay_implemented": False,
        "pg17_evidence": False,
        "cross_tenant_evidence": False,
        "policy_directory": "docs/governance/migrations/private-runtime",
        "schema": "agent_private",
        "runtime_role": "agent_runtime",
        "tenant_function": "agent_private.current_tenant_id()",
        "helper_function_security": "SECURITY INVOKER",
        "projection_function": "agent_private.load_turn_context(uuid)",
        "projection_function_security": "SECURITY DEFINER",
        "function_volatility": "STABLE",
        "helper_function_search_path": ["pg_catalog"],
        "projection_function_search_path": ["pg_catalog", "agent_private"],
        "direct_public_grants_allowed": False,
        "runtime_write_privileges_allowed": False,
        "memberships_allowed": False,
        "gates": {"operational_authorization": False, "next_stage_authorized": False},
    }
    if set(runtime) != EXPECTED_RUNTIME_KEYS or runtime != expected or schema.get("$id") != "https://igreja12.invalid/schemas/migration-history-divergence-remediation-proposal-v5.json":
        raise RuntimeError
    return proposal


def main() -> int:
    try:
        verify()
    except Exception:
        print("RESULT=BLOCKED_MIGRATION_DIVERGENCE_V5:SOURCE_PACKAGE_INVALID", file=sys.stderr)
        return 4
    print(RESULT)
    print("OPERATIONAL_AUTHORIZATION=BLOCKED")
    print("NEXT_STAGE_AUTHORIZED=false")
    print("CATALOG_MIGRATION_CREATED=false")
    return 8


if __name__ == "__main__":
    raise SystemExit(main())
