from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any, Callable

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "verify_migration_history_divergence_remediation_proposal_v3.py"
)
PROPOSAL_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-divergence-remediation-proposal-v3.json"
)
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-divergence-remediation-proposal-v3.schema.json"
)


def _load_verifier() -> Any:
    spec = importlib.util.spec_from_file_location(
        "migration_epoch_v3_verifier", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verifier = _load_verifier()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _proposal() -> dict[str, Any]:
    return _load_json(PROPOSAL_PATH)


def _set_path(value: dict[str, Any], path: tuple[str, ...], replacement: Any) -> None:
    target: dict[str, Any] = value
    for key in path[:-1]:
        nested = target[key]
        assert type(nested) is dict
        target = nested
    target[path[-1]] = replacement


def test_versioned_package_verifies_but_exits_blocked(capsys: Any) -> None:
    assert verifier.main([]) == verifier.BLOCKED_EXIT == 8
    assert capsys.readouterr().out.splitlines() == [
        "RESULT=BLOCKED_MIGRATION_EPOCH_V3:PENDING_SEPARATE_EVIDENCE",
        "PROPOSAL_STRUCTURE=VERIFIED_OFFLINE_ONLY",
        "INDEPENDENT_REVIEW=PENDING",
        "ENVIRONMENT_ATTESTATION_COMPLETE=false",
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "NEXT_STAGE_AUTHORIZED=false",
    ]


def test_cli_rejects_every_argument_without_reading_an_external_path(
    capsys: Any,
) -> None:
    assert verifier.main(["--proposal", "/tmp/untrusted.json"]) == 2
    assert capsys.readouterr().out.splitlines() == [
        "RESULT=BLOCKED_MIGRATION_EPOCH_V3:USAGE",
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "NEXT_STAGE_AUTHORIZED=false",
    ]


def test_proposal_is_closed_separates_environments_and_has_one_batch_gate() -> None:
    proposal = _proposal()
    verifier.validate_proposal(proposal)

    assert set(proposal) == verifier.EXPECTED_TOP_LEVEL_KEYS
    assert proposal["current_permissions"] == {
        key: False for key in verifier.EXPECTED_PERMISSIONS
    }
    assert set(proposal["environment_tracks"]) == {"DEV", "PROD"}
    assert proposal["environment_tracks"]["DEV"] != proposal[
        "environment_tracks"
    ]["PROD"]
    assert proposal["environment_tracks"]["DEV"][
        "legacy_evidence_classification"
    ] == "BLOCKED_LEDGER_DIVERGENCE"
    assert proposal["environment_tracks"]["PROD"][
        "legacy_evidence_classification"
    ] == "BLOCKED_EVIDENCE_INSUFFICIENT"
    assert proposal["next_gate"] == {
        "authorized": False,
        "id": "REVIEW_AND_CI_OFFLINE_AGENT_FOUNDATION_BATCH_PR",
        "scope": "OFFLINE_BATCH_REVIEW_AND_CI_ONLY_NO_CUTOVER_AUTHORIZATION",
    }


def test_attestation_v1_is_only_a_blocked_envelope() -> None:
    proposal = _proposal()
    attestation = proposal["historical_evidence"]["attestation_v1"]

    assert attestation["role"] == "BLOCKED_ENVELOPE_ONLY_NOT_COMPLETION_EVIDENCE"
    assert attestation["environment_attestation_complete"] is False
    assert attestation["surfaces"] == {
        "data_api": "PLATFORM_SURFACE_REQUIRES_SEPARATE_EVIDENCE",
        "realtime": "PLATFORM_SURFACE_REQUIRES_SEPARATE_EVIDENCE",
    }
    assert proposal["historical_evidence"]["canonical_derivation"][
        "environment_attestation_complete"
    ] is False
    assert proposal["evidence_gates"]["APPEND_ONLY_BEHAVIOR"] == {
        "environment_scope": ["DEV", "PROD"],
        "snapshot_is_sufficient": False,
        "state": "PENDING_SEPARATE_EVIDENCE",
    }


def test_manual_dev_indexes_are_names_only_and_unverified() -> None:
    drift = _proposal()["manual_dev_index_drift"]

    assert drift == verifier.EXPECTED_MANUAL_DEV_DRIFT
    assert drift["basenames"] == verifier.EXPECTED_INDEX_BASENAMES
    assert len(drift["basenames"]) == len(set(drift["basenames"])) == 7
    assert drift["classification"] == "KNOWN_UNVERIFIED_DRIFT"
    assert drift["current_presence_attested"] is False
    assert drift["definition_hashes_attested"] is False
    assert drift["catalog_application_inferred"] is False
    assert drift["prod_presence_inferred"] is False
    assert not ({"definitions", "sql", "sha256", "definition_sha256"} & set(drift))


def test_legacy_ledgers_are_preserved_without_backfill_or_cross_environment_reuse() -> None:
    proposal = _proposal()

    assert proposal["epoch_strategy"]["legacy_ledgers"] == (
        "PRESERVE_AS_INDEPENDENT_HISTORICAL_RECORDS"
    )
    assert proposal["epoch_strategy"]["automatic_backfill"] == "PROHIBITED"
    assert proposal["epoch_strategy"]["historical_inference"] == "PROHIBITED"
    assert proposal["epoch_strategy"]["cross_environment_decision_reuse"] == (
        "PROHIBITED"
    )
    for track in proposal["environment_tracks"].values():
        assert track["legacy_ledgers_action"] == (
            "PRESERVE_WITHOUT_BACKFILL_OR_REWRITE"
        )


def test_schema_is_closed_and_cannot_express_authorization() -> None:
    schema = _load_json(SCHEMA_PATH)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["required"] == sorted(verifier.EXPECTED_TOP_LEVEL_KEYS)
    assert schema["properties"]["operational_authorization"] == {"const": False}
    assert schema["properties"]["next_stage_authorized"] == {"const": False}
    assert schema["properties"]["current_permissions"] == {
        "$ref": "#/$defs/false_permissions"
    }
    assert schema["$defs"]["false_permissions"]["additionalProperties"] is False
    assert all(
        definition == {"const": False}
        for definition in schema["$defs"]["false_permissions"][
            "properties"
        ].values()
    )


def test_historical_inputs_runner_and_catalog_are_byte_stable() -> None:
    expected_paths = {
        verifier.V1_PROPOSAL_PATH: "v1_proposal",
        verifier.V2_PROPOSAL_PATH: "v2_proposal",
        verifier.ATTESTATION_PROFILE_PATH: "attestation_profile",
        verifier.ATTESTATION_SCHEMA_PATH: "attestation_schema",
        verifier.CANONICAL_FINGERPRINT_PATH: "canonical_fingerprint",
        verifier.CATALOG_TEMPLATE_PATH: "catalog_template",
        verifier.RUNNER_PATH: "runner",
        verifier.RECONCILIATION_VERIFIER_PATH: "reconciliation_verifier",
    }
    for path, hash_key in expected_paths.items():
        assert _sha256(path) == verifier.EXPECTED_HASHES[hash_key]

    assert _sha256(PROPOSAL_PATH) == verifier.EXPECTED_HASHES["proposal"]
    assert _sha256(SCHEMA_PATH) == verifier.EXPECTED_HASHES["schema"]
    assert (
        "migration-history-divergence-remediation-proposal-v3"
        not in verifier.RUNNER_PATH.read_text(encoding="utf-8")
    )
    assert (
        "migration-history-divergence-remediation-proposal-v3"
        not in verifier.RECONCILIATION_VERIFIER_PATH.read_text(encoding="utf-8")
    )
    verifier._validate_catalog_unchanged()


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("artifact_state",), "OFFLINE_EPOCH_CUTOVER_DECISION_PACKAGE_READY"),
        (("contract_version",), "3.1"),
        (("repository_base_sha",), "0" * 40),
        (("operational_authorization",), True),
        (("next_stage_authorized",), True),
        (("amendment", "historical_artifacts_remain_unchanged"), False),
        (("amendment", "prior_human_records_reused_for_v3"), True),
        (("environment_tracks", "DEV", "cutover_decision"), "APPROVED"),
        (("environment_tracks", "PROD", "cutover_decision"), "APPROVED"),
        (
            ("environment_tracks", "DEV", "legacy_ledgers_action"),
            "BACKFILL",
        ),
        (
            ("environment_tracks", "PROD", "legacy_ledgers_action"),
            "BACKFILL",
        ),
        (("epoch_strategy", "automatic_backfill"), "ALLOWED"),
        (("epoch_strategy", "historical_inference"), "ALLOWED"),
        (("epoch_strategy", "cross_environment_decision_reuse"), "ALLOWED"),
        (("epoch_strategy", "status"), "APPROVED"),
        (("epoch_strategy", "target_implementation"), "IMPLEMENTED"),
        (
            ("evidence_gates", "APPEND_ONLY_BEHAVIOR", "snapshot_is_sufficient"),
            True,
        ),
        (("evidence_gates", "DATA_API", "inferred_from_database_schema"), True),
        (("evidence_gates", "REALTIME", "inferred_from_database_schema"), True),
        (
            (
                "evidence_gates",
                "ENVIRONMENT_SCHEMA_AND_DATA",
                "one_environment_can_satisfy_another",
            ),
            True,
        ),
        (
            ("evidence_gates", "INDEPENDENT_REVIEW", "prior_review_reused"),
            True,
        ),
        (
            ("evidence_gates", "MANUAL_DEV_INDEX_DRIFT", "definitions_attested"),
            True,
        ),
        (
            ("evidence_gates", "MANUAL_DEV_INDEX_DRIFT", "presence_attested"),
            True,
        ),
        (
            ("historical_evidence", "attestation_v1", "environment_attestation_complete"),
            True,
        ),
        (
            ("historical_evidence", "attestation_v1", "role"),
            "COMPLETION_EVIDENCE",
        ),
        (
            (
                "historical_evidence",
                "canonical_derivation",
                "environment_attestation_complete",
            ),
            True,
        ),
        (("manual_dev_index_drift", "catalog_application_inferred"), True),
        (("manual_dev_index_drift", "classification"), "VERIFIED_DRIFT"),
        (("manual_dev_index_drift", "current_presence_attested"), True),
        (("manual_dev_index_drift", "definition_hashes_attested"), True),
        (("manual_dev_index_drift", "environment"), "PROD"),
        (("manual_dev_index_drift", "prior_report_is_current_environment_proof"), True),
        (("manual_dev_index_drift", "provenance"), "CURRENT_ENVIRONMENT_CAPTURE"),
        (("manual_dev_index_drift", "prod_presence_inferred"), True),
        (("next_gate", "authorized"), True),
        (("next_gate", "id"), "SEPARATE_ENVIRONMENT_EXECUTION_AUTHORIZATION"),
        (("review", "current_independent_review_complete"), True),
        (("review", "current_review_state"), "APPROVED"),
        (("review", "human_cutover_decision"), "APPROVED"),
        (("review", "prior_human_records_reused_for_v3"), True),
        (("runner_contract", "proposal_is_not_a_runner_input"), False),
        (("runner_contract", "must_remain_unchanged_in_this_mission"), False),
    ],
)
def test_adversarial_state_mutations_fail_closed(
    path: tuple[str, ...], replacement: Any
) -> None:
    proposal = copy.deepcopy(_proposal())
    _set_path(proposal, path, replacement)

    with pytest.raises(verifier.VerificationError):
        verifier.validate_proposal(proposal)


@pytest.mark.parametrize("permission", sorted(verifier.EXPECTED_PERMISSIONS))
def test_every_permission_is_independently_fail_closed(permission: str) -> None:
    proposal = copy.deepcopy(_proposal())
    proposal["current_permissions"][permission] = True

    with pytest.raises(verifier.VerificationError):
        verifier.validate_proposal(proposal)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("operational_authorization",), 0),
        (("next_stage_authorized",), 0),
        (("review", "current_independent_review_complete"), 0),
        (("current_permissions", "database_access_allowed"), 0),
        (("historical_evidence", "source_catalog", "migration_count"), 75.0),
    ],
)
def test_json_type_confusion_is_rejected(
    path: tuple[str, ...], replacement: Any
) -> None:
    proposal = copy.deepcopy(_proposal())
    _set_path(proposal, path, replacement)

    with pytest.raises(verifier.VerificationError):
        verifier.validate_proposal(proposal)


def test_extra_missing_or_redefined_index_evidence_is_rejected() -> None:
    mutations: list[Callable[[dict[str, Any]], None]] = [
        lambda value: value.__setitem__("unexpected_authorization", True),
        lambda value: value.pop("review"),
        lambda value: value["manual_dev_index_drift"].__setitem__(
            "definitions", ["create index unsafe"]
        ),
        lambda value: value["manual_dev_index_drift"].__setitem__(
            "definition_sha256", "0" * 64
        ),
        lambda value: value["manual_dev_index_drift"]["basenames"].pop(),
        lambda value: value["manual_dev_index_drift"]["basenames"].__setitem__(
            0, "idx_unreported"
        ),
        lambda value: value["manual_dev_index_drift"]["basenames"].__setitem__(
            1, value["manual_dev_index_drift"]["basenames"][0]
        ),
    ]
    for mutate in mutations:
        proposal = copy.deepcopy(_proposal())
        mutate(proposal)
        with pytest.raises(verifier.VerificationError):
            verifier.validate_proposal(proposal)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"a":1,"a":2}',
        b'{"a":1.0}',
        b'{"a":NaN}',
        b"\xef\xbb\xbf{}",
        b"[]",
    ],
)
def test_ambiguous_or_non_object_json_is_rejected(payload: bytes) -> None:
    with pytest.raises(verifier.VerificationError):
        verifier._decode_json(payload)


def test_stable_reader_rejects_symlink_and_hardlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    content = b"{}\n"
    target.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()

    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(target)
    with pytest.raises(verifier.ArtifactIoError):
        verifier._read_stable_bytes(symlink, expected_sha256=digest)

    hardlink = tmp_path / "hardlink.json"
    os.link(target, hardlink)
    with pytest.raises(verifier.ArtifactIoError):
        verifier._read_stable_bytes(hardlink, expected_sha256=digest)


def test_verifier_source_has_no_environment_network_database_or_subprocess_imports() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint(
        {
            "asyncpg",
            "httpx",
            "os",
            "psycopg",
            "psycopg2",
            "requests",
            "socket",
            "sqlalchemy",
            "subprocess",
            "urllib",
        }
    )


def test_runtime_verification_cannot_write_or_open_network_or_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("forbidden side effect")

    for method in (
        "chmod",
        "mkdir",
        "rename",
        "replace",
        "rmdir",
        "touch",
        "unlink",
        "write_bytes",
        "write_text",
    ):
        monkeypatch.setattr(Path, method, forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "check_call", forbidden)
    monkeypatch.setattr(subprocess, "check_output", forbidden)

    verifier.verify_versioned_package()
