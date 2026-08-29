from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-divergence-remediation-proposal-v1.json"
)
ADR_PATH = (
    REPO_ROOT
    / "docs"
    / "decisions"
    / "2026-08-29-migration-history-divergence-remediation.md"
)
PACKETS_DIR = REPO_ROOT / "docs" / "governance" / "migrations" / "packets"
RUNNER_PATH = REPO_ROOT / "backend" / "scripts" / "apply_migrations.py"
VERIFIER_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "verify_migration_history_reconciliation.py"
)

EXPECTED_TOP_LEVEL_KEYS = {
    "artifact_state",
    "contract_version",
    "current_permissions",
    "findings",
    "next_gates",
    "operational_authorization",
    "proposal_id",
    "repository_base_sha",
    "review_records",
    "runner_contract",
    "source_evidence",
    "strategy",
}
EXPECTED_PERMISSIONS = {
    "database_access_allowed": False,
    "database_mutation_allowed": False,
    "deploy_allowed": False,
    "environment_operation_allowed": False,
    "ledger_backfill_allowed": False,
    "migration_application_allowed": False,
    "runner_change_allowed": False,
    "runner_execution_allowed": False,
}
EXPECTED_PACKAGE_HASHES = {
    "DEV": {
        "package_sha256": (
            "c2c9c29acaf469e1e560e9fb858c260b3fa8742c0b4b5fe692c6b763755db44c"
        ),
        "receipt_sha256": {
            "native": (
                "136b3938c62c80b0882dd084abc43bfdc58465f957a1040502b0e40aa11481fa"
            ),
            "public": (
                "aa79b4f52a2c152f8a1451596f37d0479f3e336bba304a8e34f579f1f39a767f"
            ),
        },
    },
    "PROD": {
        "package_sha256": (
            "a4ba967570985682bcff19ea5c0c9dc78f2ed96a07377cbdad3dcddf8f6dceda"
        ),
        "receipt_sha256": {
            "native": (
                "34123027ab1b64108a9fb8d6c97da327306acd5ca49a11de2208eb699debc135"
            ),
            "public": (
                "067377258893391c10a20da1e80c5b37154b2073d4060a8bda6c9628aa753524"
            ),
        },
    },
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_path(environment: str, suffix: str = "") -> Path:
    return PACKETS_DIR / (
        f"migration-history-reconciliation-{environment.lower()}-evidence-v1"
        f"{suffix}.json"
    )


def test_remediation_proposal_is_closed_and_operationally_blocked() -> None:
    plan = _load_json(PLAN_PATH)

    assert set(plan) == EXPECTED_TOP_LEVEL_KEYS
    assert plan["contract_version"] == "1.0"
    assert plan["proposal_id"] == (
        "migration-history-divergence-remediation-proposal-v1"
    )
    assert plan["artifact_state"] == "OFFLINE_REMEDIATION_PROPOSAL_BLOCKED"
    assert plan["operational_authorization"] is False
    assert plan["current_permissions"] == EXPECTED_PERMISSIONS
    assert plan["repository_base_sha"] == (
        "f73a631c632a1b37cea07073c91fe6ad2a81e995"
    )

    assert plan["strategy"] == {
        "alternatives": [
            {
                "id": "FORENSIC_RECONSTRUCTION",
                "status": "BLOCKED_WITHOUT_EXTERNAL_EVIDENCE",
            },
            {
                "id": "CONTROLLED_EPOCH_CUTOVER_AFTER_SCHEMA_ATTESTATION",
                "status": "RECOMMENDED_FOR_FUTURE_HUMAN_DECISION",
            },
            {
                "id": "ENVIRONMENT_REBUILD_FROM_CATALOG",
                "status": "FALLBACK_REQUIRING_SEPARATE_BUSINESS_AND_DATA_PLAN",
            },
        ],
        "automatic_backfill": "PROHIBITED",
        "historical_inference": "PROHIBITED",
        "recommended": "CONTROLLED_EPOCH_CUTOVER_AFTER_SCHEMA_ATTESTATION",
        "status": "RECOMMENDATION_ONLY_NOT_APPROVED",
    }


def test_remediation_proposal_binds_exact_human_and_capture_records() -> None:
    plan = _load_json(PLAN_PATH)

    assert plan["review_records"] == {
        "independent_review_sha256": (
            "18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133"
        ),
        "owner_decision_sha256": (
            "0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240"
        ),
        "owner_reference": "OWNER-01",
        "reviewer_reference": "REVIEWER-01",
    }
    assert plan["review_records"]["owner_reference"] != plan["review_records"][
        "reviewer_reference"
    ]
    assert plan["source_evidence"]["packages"] == EXPECTED_PACKAGE_HASHES

    for environment, expected in EXPECTED_PACKAGE_HASHES.items():
        assert _sha256(_package_path(environment)) == expected["package_sha256"]
        assert _sha256(_package_path(environment, "-native-capture-receipt-v1")) == (
            expected["receipt_sha256"]["native"]
        )
        assert _sha256(_package_path(environment, "-public-capture-receipt-v1")) == (
            expected["receipt_sha256"]["public"]
        )


def test_remediation_findings_are_derived_only_from_sanitized_artifacts() -> None:
    plan = _load_json(PLAN_PATH)
    dev = _load_json(_package_path("DEV"))
    prod = _load_json(_package_path("PROD"))

    dev_public = dev["inventories"]["public_ledger"]["rows"]
    dev_catalog = dev["catalog"]["entries"]
    mismatches = [
        position
        for position, row in enumerate(dev_public)
        if row["name"] != dev_catalog[position]["name"]
    ]
    assert mismatches == list(range(25, 33))
    assert plan["findings"]["DEV"] == {
        "classification": "LEDGER_DIVERGENCE_CONFIRMED",
        "first_catalog_prefix_mismatch_position": 25,
        "mismatched_public_positions": mismatches,
        "native_ledger_rows": len(dev["inventories"]["native_ledger"]["rows"]),
        "public_ledger_rows": len(dev_public),
    }

    prod_public = prod["inventories"]["public_ledger"]
    prod_native = prod["inventories"]["native_ledger"]
    assert all(row["name"] is None for row in prod_native["rows"])
    assert plan["findings"]["PROD"] == {
        "classification": "EVIDENCE_INSUFFICIENT_CONFIRMED",
        "native_ledger_names_redacted_to_null": True,
        "native_ledger_rows": len(prod_native["rows"]),
        "public_ledger_rows": len(prod_public["rows"]),
        "public_ledger_state": prod_public["capture_state"],
    }


def test_remediation_proposal_cannot_unlock_or_modify_the_runner() -> None:
    plan = _load_json(PLAN_PATH)
    runner_text = RUNNER_PATH.read_text(encoding="utf-8")
    verifier_text = VERIFIER_PATH.read_text(encoding="utf-8")

    assert _sha256(RUNNER_PATH) == plan["runner_contract"][
        "apply_migrations_sha256"
    ]
    assert plan["runner_contract"] == {
        "apply_migrations_sha256": (
            "36e63cde6751cd0cb33e1511091068b0b04f10029ace06703eead82e0e836c65"
        ),
        "commands_remain_blocked": [
            "bootstrap-ledger",
            "harden-ledger",
            "status",
            "apply",
        ],
        "must_remain_unchanged_in_this_mission": True,
        "proposal_is_not_a_runner_input": True,
        "reconciliation_verifier_sha256": (
            "9451cbe5054d8c0d7e2754d09dea7f3a9761e8585269ca783eea943dd785dfae"
        ),
    }
    assert "migration-history-divergence-remediation" not in runner_text
    assert _sha256(VERIFIER_PATH) == plan["runner_contract"][
        "reconciliation_verifier_sha256"
    ]
    assert "migration-history-divergence-remediation" not in verifier_text
    assert not any(
        "divergence_remediation" in path.name
        for path in (REPO_ROOT / "backend" / "migrations").glob("*.sql")
    )


def test_remediation_proposal_requires_separate_fail_closed_gates() -> None:
    plan = _load_json(PLAN_PATH)

    assert plan["next_gates"] == [
        "STATIC_SCHEMA_EXPECTATION_MANIFEST",
        "INDEPENDENT_SECURITY_AND_DATABASE_ARCHITECTURE_REVIEW",
        "SEPARATE_READ_ONLY_ENVIRONMENT_ATTESTATION",
        "HUMAN_CUTOVER_DECISION",
        "SEPARATE_IMPLEMENTATION_PR",
        "SEPARATE_ENVIRONMENT_EXECUTION_AUTHORIZATION",
    ]


def test_remediation_public_files_are_sanitized_and_external_records_stay_external() -> None:
    public_text = PLAN_PATH.read_text(encoding="utf-8") + ADR_PATH.read_text(
        encoding="utf-8"
    )
    lowered = public_text.casefold()

    assert "@" not in public_text
    assert "database_url" not in lowered
    assert "postgresql://" not in lowered
    assert "service_role" not in lowered
    assert not re.search(r"\beyj[a-z0-9_-]{10,}\b", lowered)
    assert not list(REPO_ROOT.rglob("reviewer-01-independent-review-v1.json"))
    assert not list(REPO_ROOT.rglob("owner-01-decision-v1.json"))
    assert "operational_authorization=blocked" in lowered
    assert "não acessa dev ou prod" in lowered
