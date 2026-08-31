from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from app.domain.purpose_consent import PurposeConsentPurpose


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "consent"
    / "d2b2b2-decision-packet.template.json"
)
ADR_PATH = (
    REPO_ROOT
    / "docs"
    / "decisions"
    / "2026-08-28-d2b2b2-consent-decision-packet-contract.md"
)
RECONCILIATION_CONTRACT_PATH = (
    REPO_ROOT
    / "docs"
    / "decisions"
    / "2026-08-28-migration-history-reconciliation-contract.md"
)
HUMAN_REVIEW_GUIDE_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-human-review-guide-v1.md"
)
SCHEMA_EXPECTATION_MANIFEST_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-schema-expectation-manifest-v1.json"
)
CANONICAL_SCHEMA_DERIVATION_ADR_PATH = (
    REPO_ROOT
    / "docs"
    / "decisions"
    / "2026-08-29-offline-canonical-schema-derivation.md"
)
ENVIRONMENT_ATTESTATION_ADR_PATH = (
    REPO_ROOT
    / "docs"
    / "decisions"
    / "2026-08-30-read-only-environment-attestation-tooling.md"
)
DEV_IDENTITY_PREFLIGHT_DIAGNOSTICS_ADR_PATH = (
    REPO_ROOT
    / "docs"
    / "decisions"
    / "2026-08-30-dev-identity-preflight-diagnostics.md"
)
DEV_PREFLIGHT_PHASE_DIAGNOSTICS_ADR_PATH = (
    REPO_ROOT
    / "docs"
    / "decisions"
    / "2026-08-30-dev-preflight-failure-phase-diagnostics.md"
)
DEV_CONNECT_TLS_AUTH_DIAGNOSTICS_ADR_PATH = (
    REPO_ROOT
    / "docs"
    / "decisions"
    / "2026-08-31-dev-connect-tls-auth-transport-probe.md"
)
DEV_CONNECT_TLS_AUTH_PROBE_PLAN_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "dev-connect-tls-auth-transport-probe-plan-v1.json"
)
ENVIRONMENT_ATTESTATION_POSTMERGE_STATE = (
    "INTEGRADO E COMPROVADO OFFLINE / AMBIENTES NÃO CONSULTADOS / "
    "OPERAÇÃO BLOQUEADA"
)
DEV_IDENTITY_PREFLIGHT_RUNNER_POSTMERGE_STATE = (
    "INTEGRADO E COMPROVADO OFFLINE / DEV/PROD NÃO CONSULTADOS / "
    "OPERAÇÃO BLOQUEADA"
)
DEV_IDENTITY_PREFLIGHT_DIAGNOSTICS_STATE = (
    "DUAS INVOCACOES DEV BLOQUEADAS / CAUSA NAO DETERMINADA / "
    "PROD NAO CONSULTADO / OPERACAO BLOQUEADA"
)
DEV_IDENTITY_PREFLIGHT_DIAGNOSTICS_POSTMERGE_STATE = (
    "INTEGRADO E COMPROVADO OFFLINE / DUAS INVOCACOES DEV BLOQUEADAS / "
    "CAUSA NAO DETERMINADA / PROD NAO CONSULTADO / OPERACAO BLOQUEADA"
)
DEV_IDENTITY_PREFLIGHT_RUNNER_CURRENT_GATE = (
    "SEPARATE_NOMINAL_DEV_FAILURE_LOGS_READ_ONLY_REVIEW_AUTHORIZATION"
)
DEV_CONNECT_TLS_AUTH_PLAN_REVIEW_GATE = (
    "REVIEW_AND_CI_DEV_CONNECT_TLS_AUTH_OFFLINE_DIAGNOSTICS_PR"
)
DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CURRENT_GATE = (
    "REVIEW_AND_CI_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_IMPLEMENTATION_PR"
)
DEV_PREFLIGHT_PHASE_DIAGNOSTICS_STALE_GATE = (
    "REVIEW_AND_INTEGRATE_DEV_PREFLIGHT_PHASE_DIAGNOSTICS_PR"
)
DEV_PREFLIGHT_PHASE_DIAGNOSTICS_STALE_CLAIMS = {
    DEV_PREFLIGHT_PHASE_DIAGNOSTICS_STALE_GATE.casefold(),
    DEV_CONNECT_TLS_AUTH_PLAN_REVIEW_GATE.casefold(),
    "review_and_ci_dev_connect_tls_auth_postmerge_reconciliation_pr",
    "review_and_ci_dev_preflight_phase_diagnostics_pr",
    DEV_IDENTITY_PREFLIGHT_RUNNER_CURRENT_GATE.casefold(),
    "eventual integracao",
    "autoriza somente revisao e integracao",
    "integracao da pr com ci do mesmo sha",
    "gate operacional futuro permanece separado apos o merge",
}
DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CANONICAL_DOCS = {
    REPO_ROOT / "SPEC.md",
    REPO_ROOT / "SPEC_PROGRESS.md",
    REPO_ROOT / "docs" / "Docs20260611_163530" / "PRD20260611_163530.md",
    REPO_ROOT / "docs" / "WIKI-IGREJA12.md",
    REPO_ROOT / "docs" / "ai" / "AI-BOOTSTRAP.md",
    REPO_ROOT / "docs" / "ai" / "PRD-COVERAGE.md",
    REPO_ROOT
    / "docs"
    / "decisions"
    / "2026-08-28-d2b2b2-consent-decision-packet-contract.md",
    REPO_ROOT
    / "docs"
    / "decisions"
    / "2026-08-28-d2b2b3-master-governance-drafts.md",
    REPO_ROOT / "docs" / "ops" / "POST-V1-MISSION-REGISTER.md",
}
DEV_CONNECT_TLS_AUTH_CURRENT_DOCS = DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CANONICAL_DOCS | {
    REPO_ROOT / "backend" / "migrations" / "README.md",
    DEV_PREFLIGHT_PHASE_DIAGNOSTICS_ADR_PATH,
    DEV_CONNECT_TLS_AUTH_DIAGNOSTICS_ADR_PATH,
}

CONSUMED_PREMERGE_DERIVATION_GATE_CLAIMS = frozenset(
    {
        "antes do merge, esta pr exige",
        "esta pr exige revisao",
        "ci dedicado verde",
        "depois da integracao, o unico gate e",
        "depois da integracao, o proximo gate unico e",
        "gate unico sera",
        "o unico gate sera",
        "o proximo gate unico sera",
        "review_and_integrate_read_only_environment_attestation_pr",
    }
)

EXPECTED_TOP_LEVEL_KEYS = {
    "metadata",
    "delivery_control",
    "master_draft_contract",
    "digest_contract",
    "lifecycle_contract",
    "approval_record_contract",
    "minor_protection_contract",
    "eligibility_rules",
    "required_sections",
    "required_retention_surfaces",
    "required_approval_roles",
    "purposes",
}
EXPECTED_PURPOSE_KEYS = {purpose.value for purpose in PurposeConsentPurpose}
EXPECTED_REQUIRED_ORDER = [
    "d2b2b1_integrated_inactive",
    "master_console_tenant_bound_drafts",
    "materialized_packet_human_legal_approved",
    "catalog_evidence_writer",
    "d2c",
]
EXPECTED_BLOCKED_NOW = {
    "catalog",
    "evidence_store",
    "writer",
    "tenant_api",
    "tenant_panel",
    "approval_api",
    "approval_panel",
    "human_attestation",
    "nominal_approval_records",
    "whatsapp",
    "webhook",
    "worker",
    "langgraph",
    "tools",
    "shared_database_migration_application",
    "supabase_dev",
    "supabase_prod",
    "memory",
    "knowledge",
    "outbox",
    "d2c",
    "deploy",
    "agent_runtime",
    "agent_activation",
    "canary",
}
EXPECTED_ALLOWED_NOW = {
    "admin_master_tenant_bound_draft_migration_artifact",
    "admin_master_tenant_bound_draft_api",
    "admin_master_tenant_bound_draft_panel",
}
EXPECTED_EXCLUDED_SCOPE = {
    "universidade_da_vida",
    "capacitacao_destino",
}
EXPECTED_RETENTION_SURFACES = {
    "ledger",
    "evidence",
    "messages",
    "media",
    "transcripts",
    "summaries",
    "checkpoints",
    "vectors",
    "logs",
    "dead_letter",
    "backups",
}
EXPECTED_REQUIRED_SECTIONS = {
    "real_processing_agents",
    "operations_and_minimum_data",
    "data_sensitivity_assessment",
    "legal_hypothesis",
    "notice_texts_by_channel_and_language",
    "refusal_rights_and_withdrawal",
    "presentation_and_manifestation_evidence_contract",
    "children_adolescents_unknown_age_and_guardian_policy",
    "validity_expiration_material_change_and_reacceptance",
    "retention_and_disposal_matrix",
    "optout_withdrawal_deletion_legal_hold_and_reactivation",
    "international_transfer_inventory_and_mechanism",
    "rights_incidents_and_periodic_review_owners",
    "rbac_and_server_side_binding",
    "durable_idempotency_receipt_policy",
    "ai_memory_and_tenant_isolation",
    "nominal_approvals",
}
EXPECTED_APPROVAL_ROLES = {
    "operation_owner",
    "security_or_architecture_reviewer",
    "privacy_or_dpo_reviewer",
    "legal_reviewer_when_designated",
    "authorized_controller_representative",
    "independent_technical_verifier",
}
PURPOSE_ENTRY_KEYS = {
    "artifact_state",
    "purpose_status",
    "decision_payload",
    "content_digest",
    "nominal_approval_record_refs",
    "facts_attested_at",
    "approved_at",
    "effective_at",
    "review_due_at",
    "controller_approved",
    "human_packet_complete",
    "catalog_ready",
    "writer_eligible",
}
DECISION_PAYLOAD_KEYS = {
    "payload_schema_version",
    "purpose",
    "package_id",
    "package_version",
    "supersedes_content_digest",
    "tenant_binding",
    "controller_identity_and_institutional_contact",
    "real_processing_agents",
    "operations_and_minimum_data",
    "data_sensitivity_assessment",
    "legal_hypothesis_common_data",
    "legal_hypothesis_sensitive_data",
    "consent_based_operation",
    "notice_texts_by_channel_and_language",
    "refusal_rights_and_withdrawal",
    "presentation_and_manifestation_evidence_contract",
    "children_adolescents_unknown_age_and_guardian_policy",
    "validity_expiration_material_change_and_reacceptance",
    "retention_and_disposal_matrix",
    "optout_withdrawal_deletion_legal_hold_and_reactivation",
    "international_transfer_inventory_and_mechanism",
    "rights_incidents_and_periodic_review_owners",
    "rbac_by_action_and_scope",
    "server_side_resource_binding_evidence",
    "durable_idempotency_receipt_policy",
    "ai_memory_and_tenant_isolation",
}
PURPOSE_BOOLEAN_KEYS = {
    "controller_approved",
    "human_packet_complete",
    "catalog_ready",
    "writer_eligible",
}
APPROVAL_RECORD_FIELDS = {
    "record_ref",
    "recorded_by_identity_ref",
    "attested_content_digest",
    "decision",
    "recorded_at",
}
CHILD_POLICY_FIELDS = {
    "applicability_status",
    "justification",
    "evidence_ref",
    "reviewer_record_ref",
    "best_interest_assessment_ref",
    "age_or_guardian_measures",
    "risk_and_impact_assessment_ref",
}
EXPECTED_LIFECYCLE_STATUSES = [
    "DRAFT_NOT_APPROVED",
    "FACTS_ATTESTED",
    "PRIVACY_REVIEWED",
    "CHANGES_REQUIRED",
    "CONTROLLER_APPROVED",
    "CATALOG_BOUND",
    "REJECTED",
    "SUSPENDED",
    "EXPIRED",
    "SUPERSEDED",
]
EXPECTED_LIFECYCLE_TRANSITIONS = {
    "DRAFT_NOT_APPROVED": ["FACTS_ATTESTED", "REJECTED"],
    "FACTS_ATTESTED": [
        "PRIVACY_REVIEWED",
        "CHANGES_REQUIRED",
        "REJECTED",
    ],
    "PRIVACY_REVIEWED": [
        "CONTROLLER_APPROVED",
        "CHANGES_REQUIRED",
        "REJECTED",
    ],
    "CHANGES_REQUIRED": ["REJECTED", "SUPERSEDED"],
    "CONTROLLER_APPROVED": [
        "CATALOG_BOUND",
        "SUSPENDED",
        "EXPIRED",
        "SUPERSEDED",
    ],
    "CATALOG_BOUND": ["SUSPENDED", "EXPIRED", "SUPERSEDED"],
    "REJECTED": [],
    "SUSPENDED": ["SUPERSEDED"],
    "EXPIRED": ["SUPERSEDED"],
    "SUPERSEDED": [],
}
EXPECTED_APPROVAL_DECISIONS = {
    "APPROVED",
    "CHANGES_REQUIRED",
    "REJECTED",
    "NOT_DESIGNATED",
}
EXPECTED_HUMAN_STAGE_ROLES = [
    "operation_owner",
    "privacy_or_dpo_reviewer",
    "legal_reviewer_when_designated",
    "authorized_controller_representative",
]
EXPECTED_WRITER_STAGE_ROLES = [
    "operation_owner",
    "security_or_architecture_reviewer",
    "privacy_or_dpo_reviewer",
    "legal_reviewer_when_designated",
    "authorized_controller_representative",
    "independent_technical_verifier",
]
EXPECTED_MINOR_STATUSES = {
    "APPLICABLE",
    "NOT_APPLICABLE",
    "UNCERTAIN",
}
EXPECTED_MINOR_REQUIRED_FIELDS = {
    "best_interest_assessment_ref",
    "age_or_guardian_measures",
    "risk_and_impact_assessment_ref",
    "reviewer_record_ref",
}
EXPECTED_HUMAN_PACKET_REQUIREMENTS = {
    "all_required_sections_complete",
    "no_pending_unknown_uncertain_or_unjustified_not_applicable",
    "content_digest_matches_digest_contract",
    "purpose_status_controller_approved",
    "human_packet_stage_approval_records_digest_bound",
    "minor_applicability_decided",
    "validity_window_active",
    "retention_and_disposal_complete",
}
EXPECTED_CATALOG_REQUIREMENTS = {
    "human_packet_complete",
    "catalog_entry_bound_to_approved_content_digest",
    "evidence_store_contract_implemented",
    "separate_technical_authorization",
}
EXPECTED_WRITER_REQUIREMENTS = {
    "catalog_ready",
    "consent_based_operation_true",
    "purpose_status_catalog_bound",
    "writer_eligibility_stage_approval_records_digest_bound",
    "presentation_and_manifestation_evidence_implemented",
    "server_side_resource_binding_implemented",
    "durable_idempotency_receipt_implemented",
    "separate_technical_authorization",
}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AssertionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_template() -> tuple[dict[str, Any], str]:
    raw = TEMPLATE_PATH.read_text(encoding="utf-8")
    parsed = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    assert type(parsed) is dict
    return parsed, raw


def _without_accents(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )


def _normalized_prose(value: str) -> str:
    return " ".join(_without_accents(value).lower().split())


def _assert_current_preflight_gate(path: Path, normalized: str) -> None:
    expected = (
        DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CURRENT_GATE
        if path in DEV_CONNECT_TLS_AUTH_CURRENT_DOCS
        else DEV_IDENTITY_PREFLIGHT_RUNNER_CURRENT_GATE
    ).casefold()
    assert expected in normalized, f"current preflight gate missing in {path}"


def _assert_unique_string_list(
    value: object,
    expected: set[str],
    *,
    ordered: list[str] | None = None,
) -> None:
    assert type(value) is list
    assert all(type(item) is str for item in value)
    assert len(value) == len(set(value))
    assert set(value) == expected
    if ordered is not None:
        assert value == ordered


def _test_digest(decision_payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        decision_payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _approval_record_is_complete(
    record: object,
    *,
    content_digest: object,
    role: str,
) -> bool:
    if type(record) is not dict or type(content_digest) is not str:
        return False
    if not re.fullmatch(r"[0-9a-f]{64}", content_digest):
        return False
    if set(record) != APPROVAL_RECORD_FIELDS:
        return False
    if any(
        type(record[field]) is not str or not record[field]
        for field in APPROVAL_RECORD_FIELDS
    ):
        return False
    if record["attested_content_digest"] != content_digest:
        return False
    if role == "legal_reviewer_when_designated":
        return record["decision"] in {"APPROVED", "NOT_DESIGNATED"}
    return record["decision"] == "APPROVED"


def _is_populated(value: object) -> bool:
    if value is None:
        return False
    if type(value) is str:
        normalized = _normalized_prose(value)
        return bool(normalized) and normalized not in {
            "desconhecido",
            "incerto",
            "n/a",
            "nao aplicavel",
            "not applicable",
            "pending",
            "pendente",
            "uncertain",
            "unknown",
        }
    if type(value) is list:
        return bool(value) and all(_is_populated(item) for item in value)
    if type(value) is dict:
        return bool(value) and all(
            type(key) is str
            and bool(key.strip())
            and _is_populated(item)
            for key, item in value.items()
        )
    return type(value) in {bool, int, float}


def _minor_decision_is_complete(policy: dict[str, Any]) -> bool:
    status = policy["applicability_status"]
    if status not in {"APPLICABLE", "NOT_APPLICABLE"}:
        return False
    if not all(
        _is_populated(policy[field])
        for field in {"justification", "evidence_ref", "reviewer_record_ref"}
    ):
        return False
    if status == "APPLICABLE":
        return all(
            _is_populated(policy[field])
            for field in EXPECTED_MINOR_REQUIRED_FIELDS
        )
    return True


def _decision_payload_is_complete(payload: dict[str, Any]) -> bool:
    optional_keys = {
        "supersedes_content_digest",
        "children_adolescents_unknown_age_and_guardian_policy",
        "retention_and_disposal_matrix",
    }
    if not all(
        _is_populated(value)
        for key, value in payload.items()
        if key not in optional_keys
    ):
        return False
    retention = payload["retention_and_disposal_matrix"]
    if not all(_is_populated(value) for value in retention.values()):
        return False
    return _minor_decision_is_complete(
        payload["children_adolescents_unknown_age_and_guardian_policy"]
    )


def _assert_eligibility_invariants(packet: dict[str, Any]) -> None:
    payload = packet["decision_payload"]
    status = packet["purpose_status"]
    consent_based = payload["consent_based_operation"]
    content_digest = packet["content_digest"]
    approvals = packet["nominal_approval_record_refs"]
    minor_status = payload[
        "children_adolescents_unknown_age_and_guardian_policy"
    ]["applicability_status"]

    if consent_based is not True:
        assert packet["writer_eligible"] is False

    if packet["controller_approved"]:
        assert status in {"CONTROLLER_APPROVED", "CATALOG_BOUND"}

    if packet["human_packet_complete"]:
        assert packet["controller_approved"] is True
        assert status in {"CONTROLLER_APPROVED", "CATALOG_BOUND"}
        assert minor_status in {"APPLICABLE", "NOT_APPLICABLE"}
        assert _decision_payload_is_complete(payload)
        assert type(content_digest) is str
        assert re.fullmatch(r"[0-9a-f]{64}", content_digest)
        assert _test_digest(payload) == content_digest
        assert all(
            _is_populated(packet[field])
            for field in {
                "facts_attested_at",
                "approved_at",
                "effective_at",
                "review_due_at",
            }
        )
        assert all(
            _approval_record_is_complete(
                approvals[role],
                content_digest=content_digest,
                role=role,
            )
            for role in EXPECTED_HUMAN_STAGE_ROLES
        )
        legal_record = approvals["legal_reviewer_when_designated"]
        if legal_record["decision"] == "NOT_DESIGNATED":
            controller_record = approvals[
                "authorized_controller_representative"
            ]
            assert legal_record["recorded_by_identity_ref"] == (
                controller_record["recorded_by_identity_ref"]
            )

    if packet["catalog_ready"]:
        assert packet["human_packet_complete"] is True
        assert status == "CATALOG_BOUND"

    if packet["writer_eligible"]:
        assert packet["catalog_ready"] is True
        assert consent_based is True
        assert status == "CATALOG_BOUND"
        assert all(
            _approval_record_is_complete(
                approvals[role],
                content_digest=content_digest,
                role=role,
            )
            for role in EXPECTED_WRITER_STAGE_ROLES
        )


def _assert_structurally_valid_template(document: dict[str, Any]) -> None:
    assert type(document) is dict
    assert set(document) == EXPECTED_TOP_LEVEL_KEYS

    metadata = document["metadata"]
    assert type(metadata) is dict
    assert set(metadata) == {
        "schema_version",
        "artifact_kind",
        "artifact_state",
        "legal_content_status",
        "template_baseline_sha",
        "materialization_cardinality",
        "purpose_packet_count",
        "runtime_authority",
        "master_draft_surface_authorized",
        "successor_gate_satisfied",
    }
    assert metadata["schema_version"] == "d2b2b2/v1"
    assert metadata["artifact_kind"] == (
        "purpose_consent_decision_packet_envelope_template"
    )
    assert metadata["artifact_state"] == "template_only"
    assert metadata["legal_content_status"] == "not_supplied"
    assert metadata["template_baseline_sha"] == (
        "74951828f48994622a112d8e59eb978e5fb4f406"
    )
    assert metadata["materialization_cardinality"] == (
        "one_envelope_per_tenant_with_four_independent_purpose_packets"
    )
    assert type(metadata["purpose_packet_count"]) is int
    assert metadata["purpose_packet_count"] == 4
    assert type(metadata["runtime_authority"]) is bool
    assert metadata["runtime_authority"] is False
    assert metadata["master_draft_surface_authorized"] is True
    assert type(metadata["successor_gate_satisfied"]) is bool
    assert metadata["successor_gate_satisfied"] is False

    delivery = document["delivery_control"]
    assert type(delivery) is dict
    assert set(delivery) == {
        "required_order",
        "allowed_now",
        "blocked_now",
        "excluded_scope",
    }
    _assert_unique_string_list(
        delivery["required_order"],
        set(EXPECTED_REQUIRED_ORDER),
        ordered=EXPECTED_REQUIRED_ORDER,
    )
    _assert_unique_string_list(delivery["allowed_now"], EXPECTED_ALLOWED_NOW)
    _assert_unique_string_list(delivery["blocked_now"], EXPECTED_BLOCKED_NOW)
    _assert_unique_string_list(
        delivery["excluded_scope"], EXPECTED_EXCLUDED_SCOPE
    )

    master_draft = document["master_draft_contract"]
    assert type(master_draft) is dict
    assert master_draft["permitted_actor"] == (
        "authenticated_platform_admin_from_server_side_allowlist"
    )
    assert master_draft["rollout_flag"] == (
        "PURPOSE_CONSENT_GOVERNANCE_DRAFTS_ENABLED"
    )
    assert master_draft["rollout_default_enabled"] is False
    assert master_draft["email_is_authority_or_versioned_configuration"] is False
    assert master_draft["purpose_status_must_remain"] == "DRAFT_NOT_APPROVED"
    assert master_draft["status_transition_authority"] is False
    assert master_draft["approval_record_authority"] is False
    assert master_draft["runtime_authority"] is False
    assert master_draft["shared_database_application_authority"] is False
    assert set(master_draft["allowed_master_fields"]) == {
        "real_processing_agents",
        "operations_and_minimum_data",
        "data_sensitivity_assessment",
        "operational_need",
        "systems_and_recipients",
        "retention_and_disposal_inventory",
        "operator_instructions",
        "open_questions",
    }
    assert master_draft["field_character_limit"] == 4000
    assert master_draft["payload_character_limit"] == 16000
    assert {
        "content_digest",
        "nominal_approval_record_refs",
        "controller_approved",
        "human_packet_complete",
        "catalog_ready",
        "writer_eligible",
    } <= set(master_draft["forbidden_master_fields"])
    digest_contract = document["digest_contract"]
    assert type(digest_contract) is dict
    assert digest_contract == {
        "algorithm": "sha256",
        "encoding": "utf-8",
        "canonicalization": "rfc8785_jcs",
        "scope": "single_purpose_packet_decision_payload_only",
        "decision_payload_schema_version": "d2b2b2/decision-payload/v1",
        "governance_envelope_is_excluded": True,
        "decision_payload_immutable_after_first_approval_record": True,
    }

    lifecycle = document["lifecycle_contract"]
    assert type(lifecycle) is dict
    assert set(lifecycle) == {
        "initial_status",
        "allowed_statuses",
        "allowed_transitions",
    }
    assert lifecycle["initial_status"] == "DRAFT_NOT_APPROVED"
    _assert_unique_string_list(
        lifecycle["allowed_statuses"],
        set(EXPECTED_LIFECYCLE_STATUSES),
        ordered=EXPECTED_LIFECYCLE_STATUSES,
    )
    assert lifecycle["allowed_transitions"] == EXPECTED_LIFECYCLE_TRANSITIONS

    approval_contract = document["approval_record_contract"]
    assert type(approval_contract) is dict
    assert set(approval_contract) == {
        "required_fields",
        "allowed_decisions",
        "human_packet_stage_roles",
        "writer_eligibility_stage_roles",
        "not_designated_allowed_only_for",
        "record_refs_are_external_sanitized_and_identity_authenticated",
        "legal_reviewer_absence_requires_controller_signed_not_designated_record",
        "all_records_must_attest_content_digest",
    }
    _assert_unique_string_list(
        approval_contract["required_fields"], APPROVAL_RECORD_FIELDS
    )
    _assert_unique_string_list(
        approval_contract["allowed_decisions"], EXPECTED_APPROVAL_DECISIONS
    )
    _assert_unique_string_list(
        approval_contract["human_packet_stage_roles"],
        set(EXPECTED_HUMAN_STAGE_ROLES),
        ordered=EXPECTED_HUMAN_STAGE_ROLES,
    )
    _assert_unique_string_list(
        approval_contract["writer_eligibility_stage_roles"],
        set(EXPECTED_WRITER_STAGE_ROLES),
        ordered=EXPECTED_WRITER_STAGE_ROLES,
    )
    _assert_unique_string_list(
        approval_contract["not_designated_allowed_only_for"],
        {"legal_reviewer_when_designated"},
    )
    for key in {
        "record_refs_are_external_sanitized_and_identity_authenticated",
        "legal_reviewer_absence_requires_controller_signed_not_designated_record",
        "all_records_must_attest_content_digest",
    }:
        assert type(approval_contract[key]) is bool
        assert approval_contract[key] is True

    minor_contract = document["minor_protection_contract"]
    assert type(minor_contract) is dict
    assert set(minor_contract) == {
        "applicability_statuses",
        "uncertain_blocks_catalog_and_writer",
        "not_applicable_requires_justification_evidence_and_reviewer",
        "when_applicable_required_fields",
    }
    _assert_unique_string_list(
        minor_contract["applicability_statuses"], EXPECTED_MINOR_STATUSES
    )
    _assert_unique_string_list(
        minor_contract["when_applicable_required_fields"],
        EXPECTED_MINOR_REQUIRED_FIELDS,
    )
    for key in {
        "uncertain_blocks_catalog_and_writer",
        "not_applicable_requires_justification_evidence_and_reviewer",
    }:
        assert type(minor_contract[key]) is bool
        assert minor_contract[key] is True

    eligibility = document["eligibility_rules"]
    assert type(eligibility) is dict
    assert set(eligibility) == {
        "human_packet_complete_requires",
        "catalog_ready_requires",
        "writer_eligible_requires",
        "non_consent_rule",
        "writer_eligible_is_derived",
    }
    _assert_unique_string_list(
        eligibility["human_packet_complete_requires"],
        EXPECTED_HUMAN_PACKET_REQUIREMENTS,
    )
    _assert_unique_string_list(
        eligibility["catalog_ready_requires"],
        EXPECTED_CATALOG_REQUIREMENTS,
    )
    _assert_unique_string_list(
        eligibility["writer_eligible_requires"],
        EXPECTED_WRITER_REQUIREMENTS,
    )
    assert eligibility["non_consent_rule"] == (
        "consent_based_operation_not_true_forces_writer_eligible_false_"
        "and_forbids_concedido"
    )
    assert type(eligibility["writer_eligible_is_derived"]) is bool
    assert eligibility["writer_eligible_is_derived"] is True

    _assert_unique_string_list(
        document["required_sections"], EXPECTED_REQUIRED_SECTIONS
    )
    _assert_unique_string_list(
        document["required_retention_surfaces"], EXPECTED_RETENTION_SURFACES
    )
    _assert_unique_string_list(
        document["required_approval_roles"], EXPECTED_APPROVAL_ROLES
    )

    purposes = document["purposes"]
    assert type(purposes) is dict
    assert set(purposes) == EXPECTED_PURPOSE_KEYS
    for purpose_name, packet in purposes.items():
        assert type(packet) is dict
        assert purpose_name in EXPECTED_PURPOSE_KEYS
        assert set(packet) == PURPOSE_ENTRY_KEYS
        assert type(packet["artifact_state"]) is str
        assert packet["artifact_state"] == "template_only"
        assert type(packet["purpose_status"]) is str
        assert packet["purpose_status"] == "DRAFT_NOT_APPROVED"

        payload = packet["decision_payload"]
        assert type(payload) is dict
        assert set(payload) == DECISION_PAYLOAD_KEYS
        assert type(payload["payload_schema_version"]) is str
        assert payload["payload_schema_version"] == (
            "d2b2b2/decision-payload/v1"
        )
        assert type(payload["purpose"]) is str
        assert payload["purpose"] == purpose_name
        assert type(payload["retention_and_disposal_matrix"]) is dict
        assert set(payload["retention_and_disposal_matrix"]) == (
            EXPECTED_RETENTION_SURFACES
        )
        assert all(
            value is None
            for value in payload["retention_and_disposal_matrix"].values()
        )
        child_policy = payload[
            "children_adolescents_unknown_age_and_guardian_policy"
        ]
        assert type(child_policy) is dict
        assert set(child_policy) == CHILD_POLICY_FIELDS
        assert all(value is None for value in child_policy.values())

        for key, value in payload.items():
            if key in {"payload_schema_version", "purpose"}:
                continue
            if key in {
                "retention_and_disposal_matrix",
                "children_adolescents_unknown_age_and_guardian_policy",
            }:
                continue
            assert value is None

        approvals = packet["nominal_approval_record_refs"]
        assert type(approvals) is dict
        assert set(packet["nominal_approval_record_refs"]) == (
            EXPECTED_APPROVAL_ROLES
        )
        for record in approvals.values():
            assert type(record) is dict
            assert set(record) == APPROVAL_RECORD_FIELDS
            assert all(value is None for value in record.values())

        for key, value in packet.items():
            if key in {
                "artifact_state",
                "purpose_status",
                "decision_payload",
                "nominal_approval_record_refs",
            }:
                continue
            if key in PURPOSE_BOOLEAN_KEYS:
                assert type(value) is bool
                assert value is False
            else:
                assert value is None
        _assert_eligibility_invariants(packet)


def test_d2b2b2_template_is_structurally_valid_and_not_approved() -> None:
    document, raw = _load_template()

    _assert_structurally_valid_template(document)
    assert "DRAFT_NOT_APPROVED" in raw
    assert re.search(r"\+55\d{10,11}", raw) is None
    assert re.search(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", raw) is None
    assert re.search(
        r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", raw
    ) is None
    assert re.search(r"(?i)(sk-|ghp_|private key|bearer\s+[a-z0-9])", raw) is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["metadata"].__setitem__("runtime_authority", True),
        lambda value: value["metadata"].__setitem__("runtime_authority", 0),
        lambda value: value["metadata"].__setitem__(
            "purpose_packet_count", True
        ),
        lambda value: value["purposes"]["comunicados"][
            "decision_payload"
        ].__setitem__(
            "legal_hypothesis_common_data", "filled"
        ),
        lambda value: value["purposes"].pop("cuidado_pastoral"),
        lambda value: value["purposes"]["atendimento_solicitado"][
            "nominal_approval_record_refs"
        ]["authorized_controller_representative"].__setitem__(
            "record_ref", "filled"
        ),
        lambda value: value["delivery_control"].__setitem__(
            "required_order", list(reversed(EXPECTED_REQUIRED_ORDER))
        ),
        lambda value: value["delivery_control"].__setitem__(
            "excluded_scope", ["universidade_da_vida"]
        ),
        lambda value: value["delivery_control"].__setitem__(
            "blocked_now", [*value["delivery_control"]["blocked_now"], "writer"]
        ),
        lambda value: value.__setitem__(
            "digest_contract",
            {
                **value["digest_contract"],
                "canonicalization": "unspecified",
            },
        ),
        lambda value: value["lifecycle_contract"]["allowed_transitions"].__setitem__(
            "CHANGES_REQUIRED", ["FACTS_ATTESTED"]
        ),
        lambda value: value["eligibility_rules"].__setitem__(
            "writer_eligible_is_derived", 1
        ),
        lambda value: value["approval_record_contract"].__setitem__(
            "human_packet_stage_roles",
            [*EXPECTED_HUMAN_STAGE_ROLES, "operation_owner"],
        ),
    ],
)
def test_d2b2b2_template_rejects_authority_or_filled_decisions(
    mutation: Any,
) -> None:
    document, _ = _load_template()
    candidate = copy.deepcopy(document)
    mutation(candidate)

    with pytest.raises(AssertionError):
        _assert_structurally_valid_template(candidate)


def test_d2b2b2_digest_scope_is_immutable_and_non_circular() -> None:
    document, _ = _load_template()
    original = copy.deepcopy(document["purposes"]["cuidado_pastoral"])
    original_digest = _test_digest(original["decision_payload"])

    governance_only = copy.deepcopy(original)
    governance_only["purpose_status"] = "CONTROLLER_APPROVED"
    governance_only["approved_at"] = "reference-only"
    governance_only["controller_approved"] = True
    governance_only["nominal_approval_record_refs"]["operation_owner"][
        "record_ref"
    ] = "governed-record-ref"
    assert _test_digest(governance_only["decision_payload"]) == original_digest

    for key in DECISION_PAYLOAD_KEYS:
        changed_decision = copy.deepcopy(original)
        changed_decision["decision_payload"][key] = {"changed": key}
        assert (
            _test_digest(changed_decision["decision_payload"])
            != original_digest
        )


def test_d2b2b2_human_gate_uses_four_digest_bound_records() -> None:
    document, _ = _load_template()
    packet = copy.deepcopy(document["purposes"]["atendimento_solicitado"])
    payload = packet["decision_payload"]

    for key, value in list(payload.items()):
        if value is None and key != "supersedes_content_digest":
            payload[key] = {"governed_record_ref": f"ref:{key}"}
    payload["consent_based_operation"] = True
    payload["children_adolescents_unknown_age_and_guardian_policy"] = {
        "applicability_status": "NOT_APPLICABLE",
        "justification": "ref:minor-justification",
        "evidence_ref": "ref:minor-evidence",
        "reviewer_record_ref": "ref:minor-review",
        "best_interest_assessment_ref": None,
        "age_or_guardian_measures": None,
        "risk_and_impact_assessment_ref": None,
    }
    payload["retention_and_disposal_matrix"] = {
        surface: {"policy_ref": f"ref:retention:{surface}"}
        for surface in EXPECTED_RETENTION_SURFACES
    }
    content_digest = _test_digest(payload)
    packet["content_digest"] = content_digest

    identity_by_role = {
        "operation_owner": "ref:identity:operation-owner",
        "privacy_or_dpo_reviewer": "ref:identity:privacy-reviewer",
        "legal_reviewer_when_designated": "ref:identity:controller",
        "authorized_controller_representative": "ref:identity:controller",
    }
    for role in EXPECTED_HUMAN_STAGE_ROLES:
        packet["nominal_approval_record_refs"][role] = {
            "record_ref": f"ref:approval:{role}",
            "recorded_by_identity_ref": identity_by_role[role],
            "attested_content_digest": content_digest,
            "decision": (
                "NOT_DESIGNATED"
                if role == "legal_reviewer_when_designated"
                else "APPROVED"
            ),
            "recorded_at": "ref:time:approved",
        }

    packet["purpose_status"] = "CONTROLLER_APPROVED"
    packet["facts_attested_at"] = "ref:time:facts"
    packet["approved_at"] = "ref:time:approved"
    packet["effective_at"] = "ref:time:effective"
    packet["review_due_at"] = "ref:time:review-due"
    packet["controller_approved"] = True
    packet["human_packet_complete"] = True

    _assert_eligibility_invariants(packet)
    assert all(
        value is None
        for role in {
            "security_or_architecture_reviewer",
            "independent_technical_verifier",
        }
        for value in packet["nominal_approval_record_refs"][role].values()
    )
    assert packet["catalog_ready"] is False
    assert packet["writer_eligible"] is False

    forged_legal_absence = copy.deepcopy(packet)
    forged_legal_absence["nominal_approval_record_refs"][
        "legal_reviewer_when_designated"
    ]["recorded_by_identity_ref"] = "ref:identity:unbound"
    with pytest.raises(AssertionError):
        _assert_eligibility_invariants(forged_legal_absence)

    arbitrary_digest = copy.deepcopy(packet)
    arbitrary_digest["content_digest"] = "0" * 64
    for role in EXPECTED_HUMAN_STAGE_ROLES:
        arbitrary_digest["nominal_approval_record_refs"][role][
            "attested_content_digest"
        ] = "0" * 64
    with pytest.raises(AssertionError):
        _assert_eligibility_invariants(arbitrary_digest)

    pending_decision = copy.deepcopy(packet)
    pending_decision["decision_payload"]["operations_and_minimum_data"] = (
        "pending"
    )
    pending_digest = _test_digest(pending_decision["decision_payload"])
    pending_decision["content_digest"] = pending_digest
    for role in EXPECTED_HUMAN_STAGE_ROLES:
        pending_decision["nominal_approval_record_refs"][role][
            "attested_content_digest"
        ] = pending_digest
    with pytest.raises(AssertionError):
        _assert_eligibility_invariants(pending_decision)

    nested_pending = copy.deepcopy(packet)
    nested_pending["decision_payload"]["operations_and_minimum_data"] = {
        "status": "unknown"
    }
    nested_digest = _test_digest(nested_pending["decision_payload"])
    nested_pending["content_digest"] = nested_digest
    for role in EXPECTED_HUMAN_STAGE_ROLES:
        nested_pending["nominal_approval_record_refs"][role][
            "attested_content_digest"
        ] = nested_digest
    with pytest.raises(AssertionError):
        _assert_eligibility_invariants(nested_pending)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda packet: packet.__setitem__("writer_eligible", True),
        lambda packet: (
            packet["decision_payload"].__setitem__(
                "consent_based_operation", False
            ),
            packet.__setitem__("writer_eligible", True),
        ),
        lambda packet: (
            packet["decision_payload"].__setitem__(
                "consent_based_operation", True
            ),
            packet.__setitem__("writer_eligible", True),
        ),
        lambda packet: packet.__setitem__("catalog_ready", True),
        lambda packet: (
            packet["decision_payload"][
                "children_adolescents_unknown_age_and_guardian_policy"
            ].__setitem__("applicability_status", "UNCERTAIN"),
            packet.__setitem__("human_packet_complete", True),
        ),
    ],
)
def test_d2b2b2_derived_eligibility_fails_closed(mutation: Any) -> None:
    document, _ = _load_template()
    packet = copy.deepcopy(document["purposes"]["comunicados"])
    mutation(packet)

    with pytest.raises(AssertionError):
        _assert_eligibility_invariants(packet)


def test_d2b2b2_template_has_no_runtime_or_migration_consumer() -> None:
    forbidden_tokens = {
        TEMPLATE_PATH.name,
        "purpose_consent_decision_packet_envelope_template",
    }
    roots = [
        REPO_ROOT / "backend" / "app",
        REPO_ROOT / "backend" / "migrations",
        REPO_ROOT / "frontend" / "src",
    ]

    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            assert not (forbidden_tokens & set(content.split()))
            for token in forbidden_tokens:
                assert token not in content, f"runtime consumer in {path}"


def test_canonical_docs_record_captured_blocked_inventories_and_one_human_gate() -> None:
    canonical_indexes = {
        REPO_ROOT / "docs" / "ai" / "AI-BOOTSTRAP.md",
        REPO_ROOT / "docs" / "ai" / "PRD-COVERAGE.md",
        REPO_ROOT / "docs" / "WIKI-IGREJA12.md",
        REPO_ROOT / "docs" / "ops" / "POST-V1-MISSION-REGISTER.md",
        REPO_ROOT / "SPEC_PROGRESS.md",
    }
    gate_contracts = canonical_indexes | {
        REPO_ROOT / "SPEC.md",
        REPO_ROOT
        / "docs"
        / "Docs20260611_163530"
        / "PRD20260611_163530.md",
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-28-d2b2b2-consent-decision-packet-contract.md",
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-28-d2b2b3-master-governance-drafts.md",
    }
    postmerge_records = gate_contracts | {
        REPO_ROOT / "backend" / "migrations" / "README.md",
        REPO_ROOT / "deploy" / "STAGING.md",
        REPO_ROOT / "docs" / "ops" / "PRODUCTION-RUNBOOK.md",
        REPO_ROOT
        / "docs"
        / "security"
        / "2026-08-20-v1-ledger-hardening-gate.md",
        RECONCILIATION_CONTRACT_PATH,
    }
    mode_provenance_records = {
        REPO_ROOT / "backend" / "migrations" / "README.md",
        REPO_ROOT / "deploy" / "STAGING.md",
        REPO_ROOT
        / "docs"
        / "Docs20260611_163530"
        / "PRD20260611_163530.md",
        REPO_ROOT / "docs" / "ops" / "POST-V1-MISSION-REGISTER.md",
        REPO_ROOT / "docs" / "ops" / "PRODUCTION-RUNBOOK.md",
        REPO_ROOT
        / "docs"
        / "security"
        / "2026-08-20-v1-ledger-hardening-gate.md",
        RECONCILIATION_CONTRACT_PATH,
    }

    for path in canonical_indexes:
        content = path.read_text(encoding="utf-8")
        normalized = _normalized_prose(content)
        assert "d2b2b2-consent-decision-packet-contract.md" in content
        assert "d2b2b3-master-governance-drafts.md" in content
        assert "jurid" in normalized
        assert "aprov" in normalized

    for path in gate_contracts:
        content = path.read_text(encoding="utf-8")
        normalized = _normalized_prose(content)
        assert "15deaf88fd4cab5b4bebdd1435a81c8b33c2b159" in content
        assert "b43ad92028374fa6763ef10f5eb7a379afd3e7a2" in content
        assert "cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7" in content
        assert "74d3f2d87a7ffad501432b2d9fc4163bd3b4ada4" in content
        assert "3a5789c784017ab15a43e28c4270d25af8618359" in content
        assert "2026-08-28T15:24:58Z" in content
        assert "6143773477" in content
        assert "2026-08-28T15:22:43Z" in content
        assert "6143819601" in content
        assert "2026-08-28T15:25:43Z" in content
        assert "#325" in content
        assert "d9595c3958fec98a875d15de2b6647d6b1de435e" in content
        assert "ab7d09f07db96d5c63a2cc32dddf3f910e23bac2" in content
        assert "2026-08-28t20:18:08z" in normalized
        assert "6147914118" in content
        assert "2026-08-28t20:16:00z" in normalized
        assert "6147952424" in content
        assert "2026-08-28t20:18:55z" in normalized
        assert "preflight prod somente leitura" in normalized
        assert "`m06_migration_database_url`" in normalized
        assert "`database_url`" in normalized
        assert "public.schema_migrations" in normalized
        assert "`bootstrap-ledger`" in normalized
        assert "`harden-ledger`" in normalized
        assert "bootstrap_ledger" in normalized
        assert "ledger vazio" in normalized
        assert "owner-only" in normalized
        assert "42/42" in normalized
        assert "87/87" in normalized
        assert "postgresql 17-alpine" in normalized
        assert "supabase pg17" in normalized
        assert "17.6.1.159" in normalized
        assert normalized.count("duas execucoes independentes") >= 2
        assert "seguranca" in normalized
        assert "`go`" in normalized
        assert "326/326" in normalized
        assert "3803 deselecionados" in normalized
        assert "2 warnings preexistentes" in normalized
        assert "162.77s" in normalized
        assert "suite offline integral" in normalized
        assert "interrompida apos 5 min sem saida ou progresso" in normalized
        assert "`inconclusivo`" in normalized
        assert "nao verde nem falha" in normalized
        assert "workflows backend tests da pr #323 e do pos-merge" in normalized
        assert "backend tests da pr permanece gate" not in normalized
        assert "integrado" in normalized
        assert "continua nao aplicado" in normalized or "mas nao aplicado" in normalized
        assert "preview automatico frontend" in normalized
        assert "production automatico frontend" in normalized
        assert "somente o frontend" in normalized
        assert "sem provar backend, banco ou runtime" in normalized
        assert "nao houve deploy manual ou do backend" in normalized
        assert "acesso aos bancos dev ou prod" in normalized
        assert "comprovado offline" in normalized
        assert "nao aplica" in normalized
        assert "registra migration" in normalized
        assert "nao" in normalized and "supabase_migrations" in normalized
        assert "2026-08-28-migration-history-reconciliation-contract.md" in content
        assert "pacote deny-state versionado" in normalized
        assert "verificador stdlib separado do runner" in normalized
        assert "integrado" in normalized
        assert "comprovado offline" in normalized
        assert "revisao independente bloqueada" in normalized
        assert "decisao owner-01 registrada" in normalized
        assert "nao aplicado" in normalized
        assert "pacote e verificador candidatos" not in normalized
        assert "nao acessa banco, rede" in normalized
        assert "variaveis de ambiente" in normalized
        assert "nao executa sql, dml ou escrita" in normalized
        assert "nao infere migration aplicada" in normalized
        assert "ledgers nativo e publico permanecem independentes" in normalized
        assert "operational_authorization=blocked" in normalized
        assert "98/98" in normalized
        assert "26/26" in normalized
        assert "42/42" in normalized
        assert "166 passed/45 skipped" in normalized
        assert "exit `8`" in normalized
        assert "656d1d9eebe90ad4b2cbb35c21939a6796c46bfe" in content
        assert "75 migrations" in normalized
        assert "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f" in content
        assert "#327" in content
        assert "c4f7a25b81a8091a0d74783c816a168bb7adf44d" in content
        assert "f9201a06495fad138e313e4149ad9275ff896900" in content
        assert "#328" in content
        assert "2cbdfaf39ae11d984f0aa27dfcf0910c25984840" in content
        assert "04e5c1720bf89313718c4159a2ac9d0eeeed3c25" in content
        assert "#329" in content
        assert "c5ae430aa865dbd6371953d43e4a4447ca8e6618" in content
        assert "341f38a7f1c6993c74d85e99748cb60046cd4501" in content
        assert "2026-08-29t00:04:50z" in normalized
        assert "6150482852" in content
        assert "2026-08-29t00:05:33z" in normalized
        assert "integrou e versionou os seis artefatos" in normalized
        assert "deployment automatico vercel frontend production" in normalized
        assert "prova somente o frontend" in normalized
        assert "sem provar deploy manual ou do backend, banco ou runtime" in normalized
        assert "inventarios dev e prod capturados" in normalized
        assert "revisao independente bloqueada" in normalized
        assert "decisao owner-01 registrada" in normalized
        assert "18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133" in content
        assert "0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240" in content
        assert "nao aplicado" in normalized
        assert "8b589e5dda722691fead34cbd63cab75a7a22f32e0cf4bdfe64d6cef603866ee" in content
        assert "em postgresql 17, dev" in normalized
        assert "33 linhas no ledger publico" in normalized
        assert "6 no nativo" in normalized
        assert "2026-08-28t22:43:11.454382z" in normalized
        assert "absent_confirmed" in normalized
        assert "0 linhas" in normalized
        assert "32 linhas no nativo" in normalized
        assert "2026-08-28t22:47:43.965243z" in normalized
        assert "native.name" in normalized
        assert "`null`" in normalized
        assert "evidence_captured_unreviewed" in normalized
        assert "exit `8`" in normalized
        assert "human_evidence_blocked" in normalized
        assert "cross_package_ok" in normalized
        assert "matriz focal offline pos-captura" in normalized
        assert "163 passed" in normalized
        assert "2 skipped" in normalized
        assert "1.40s" in normalized
        assert "nao e suite integral" in normalized
        assert "reexecucao postgresql" in normalized
        assert "somente leitura" in normalized
        assert "seis artefatos" in normalized
        assert "decisao humana" in normalized
        assert "nao prova" in normalized
        assert "prefixo reconciliado" in normalized
        assert "derivacao canonica" in normalized
        assert "reproduzida e verificada somente offline" in normalized
        assert "pr #334" in normalized
        assert "c8427b1a505c0aad2a5f675d3bf456ee33716690" in normalized
        assert "6160229001" in normalized
        assert "metadata do deployment prova somente o frontend" in normalized
        assert DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CURRENT_GATE.casefold() in normalized
        assert "manifesto estatico" in normalized
        assert "nao autoriza" in normalized and "dml" in normalized
        assert "postgresql 17 descartavel" in normalized
        assert "nao atesta dev, prod" in normalized
        assert "7f18f7e8b44cd50e6f6033867fb97bfa9eb9c9e6" in content
        assert "source_level_expectation_only" in normalized
        assert "operational_authorization=blocked" in normalized
        assert "schema_expectation_manifest_verified_source_only" in normalized
        assert "environment_attestation_complete=false" in normalized
        assert "revisao tecnica" in normalized
        assert "nao e independente" in normalized
        assert "preparar uma missao separada" not in normalized
        assert "revisar e integrar esta pr" not in normalized
        assert "inventarios dev/prod ainda nao capturados" not in normalized
        assert "concluir os testes focais" not in normalized
        assert "`status` e `apply`" in normalized
        assert "bloquead" in normalized
        assert "prefixo integro do catalogo" in normalized
        assert "no maximo uma migration pendente" in normalized
        for blocker in (
            "dml",
            "`bootstrap-ledger`",
            "`harden-ledger`",
            "`status`",
            "`apply`",
            "deploy",
            "flag",
            "runtime",
            "universidade da vida",
            "capacitacao destino",
        ):
            assert blocker in normalized

    stale_candidate_statuses = {
        "pacote e verificador candidatos",
        "pacote e o verificador candidatos",
        "pacote e o verificador de reconciliacao sao candidatos somente offline",
        "pacote e o verificador de reconciliacao estao candidatos somente offline",
    }

    for path in postmerge_records:
        content = path.read_text(encoding="utf-8")
        normalized = _normalized_prose(content)
        assert "integrado" in normalized
        assert "revisao independente bloqueada" in normalized
        assert "decisao owner-01 registrada" in normalized
        assert "nao aplicado" in normalized
        assert "98/98" in normalized
        assert "26/26" in normalized
        assert "42/42" in normalized
        assert "166 passed/45 skipped" in normalized
        assert "exit `8`" in normalized
        assert "#327" in normalized
        assert "#328" in normalized
        assert "04e5c1720bf89313718c4159a2ac9d0eeeed3c25" in normalized
        assert "#329" in normalized
        assert "c5ae430aa865dbd6371953d43e4a4447ca8e6618" in normalized
        assert "341f38a7f1c6993c74d85e99748cb60046cd4501" in normalized
        assert "2026-08-29t00:04:50z" in normalized
        assert "6150482852" in normalized
        assert "2026-08-29t00:05:33z" in normalized
        assert "integrou e versionou os seis artefatos" in normalized
        assert "prova somente o frontend" in normalized
        assert "sem provar deploy manual ou do backend, banco ou runtime" in normalized
        assert "inventarios dev e prod capturados" in normalized
        assert "revisao independente bloqueada" in normalized
        assert "decisao owner-01 registrada" in normalized
        assert "18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133" in content
        assert "0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240" in content
        assert "bloquead" in normalized
        assert "33 linhas" in normalized
        assert "6 no nativo" in normalized or "com 6 linhas" in normalized
        assert "absent_confirmed" in normalized
        assert "32 linhas" in normalized
        assert "evidence_captured_unreviewed" in normalized
        assert "human_evidence_blocked" in normalized
        assert "cross_package_ok" in normalized
        assert "163 passed" in normalized
        assert "2 skipped" in normalized
        assert "derivacao canonica" in normalized
        assert "reproduzida e verificada somente offline" in normalized
        assert "pr #334" in normalized
        assert "c8427b1a505c0aad2a5f675d3bf456ee33716690" in normalized
        assert "6160229001" in normalized
        assert "metadata do deployment prova somente o frontend" in normalized
        _assert_current_preflight_gate(path, normalized)
        assert "manifesto estatico" in normalized
        assert "nao autoriza" in normalized and "dml" in normalized
        for stale_status in stale_candidate_statuses:
            assert stale_status not in normalized
        for stale_capture_claim in (
            "em postgresql 17.6, dev registrou",
            "em postgresql 17.6, dev contem",
            "seis artefatos `0600`",
            "todos com modo `0600`",
            "foram criados com modo `0600`",
        ):
            assert stale_capture_claim not in normalized

    for path in mode_provenance_records:
        normalized = _normalized_prose(path.read_text(encoding="utf-8"))
        assert "originalmente" in normalized
        assert "`0600`" in normalized
        assert "`o_excl`" in normalized
        assert "depois do versionamento" in normalized
        assert "sanitizacao" in normalized
        assert "acl do repositorio" in normalized
        assert "nao do modo do checkout" in normalized

    for path in gate_contracts:
        normalized = _normalized_prose(path.read_text(encoding="utf-8"))
        assert normalized.count("proximo gate unico") == 1
        assert normalized.count(
            DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CURRENT_GATE.casefold()
        ) == 1
        assert "review_and_integrate_read_only_environment_attestation_pr" not in normalized
        assert "separate_read_only_environment_attestation" not in normalized
        assert _normalized_prose(ENVIRONMENT_ATTESTATION_POSTMERGE_STATE) in normalized
        assert "be958ce96e65d3d497923b7f5f912676634e9587" in normalized
        assert "1072e6a8e85d201a1c82f37a8ddeac5417300c49" in normalized
        assert "367 passed, 47 skipped" in normalized
        assert "sarah/terra" in normalized
        assert "claude opus" in normalized
        assert "execution error" in normalized
        assert "nenhum dev ou prod foi consultado" in normalized
        assert "nenhum artefato ambiental foi produzido" in normalized
        assert "envelope" in normalized
        assert "verificador python" in normalized
        assert "hmac" in normalized
        assert "correlacao" in normalized
        assert "anti-swap" in normalized
        assert "autorizacao humana" in normalized
        assert "project ref" in normalized
        assert "platform_surfaces_unattested" in normalized
        assert "operational_authorization=blocked" in normalized
        assert "environment_attestation_complete=false" in normalized
        assert "prod esta explicitamente fora" in normalized

    reconciliation_contract = RECONCILIATION_CONTRACT_PATH.read_text(
        encoding="utf-8"
    )
    reconciliation_normalized = _normalized_prose(reconciliation_contract)
    assert "cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7" in reconciliation_contract
    assert "integrado" in reconciliation_normalized
    assert "revisao independente bloqueada" in reconciliation_normalized
    assert "decisao owner-01 registrada" in reconciliation_normalized
    assert "nao aplicado" in reconciliation_normalized
    assert "pacote deny-state versionado" in reconciliation_normalized
    assert "biblioteca padrao" in reconciliation_normalized
    assert "separado de `backend/scripts/apply_migrations.py`" in reconciliation_normalized
    assert "operational_authorization=blocked" in reconciliation_normalized
    assert "166 passed/45 skipped" in reconciliation_normalized
    assert "exit `8`" in reconciliation_normalized
    assert "pacote e verificador candidatos" not in reconciliation_normalized
    assert reconciliation_normalized.count("proximo gate unico") == 1

    capture_primary_records = {
        RECONCILIATION_CONTRACT_PATH,
        REPO_ROOT / "backend" / "migrations" / "README.md",
    }
    for path in capture_primary_records:
        content = path.read_text(encoding="utf-8")
        normalized = _normalized_prose(content)
        assert "656d1d9eebe90ad4b2cbb35c21939a6796c46bfe" in content
        assert "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f" in content
        assert "8b589e5dda722691fead34cbd63cab75a7a22f32e0cf4bdfe64d6cef603866ee" in content
        assert "sql allowlisted" in normalized
        assert "canal nominal" in normalized
        assert "sanitized_capture" in normalized
        assert "descritores de arquivo independentes" in normalized
        assert "chave hmac" in normalized
        assert "target binding" in normalized
        assert "--expected-target-binding-sha256" in normalized
        assert "argumento sanitizado" in normalized
        assert "fonte permanece independente" in normalized
        assert "native.name" in normalized
        assert "`null`" in normalized
        assert "`0600`" in normalized
        assert "`o_excl`" in normalized
        assert "migration-history-reconciliation-dev-evidence-v1.json" in content
        assert "migration-history-reconciliation-prod-evidence-v1.json" in content
        assert "operational_authorization=blocked" in normalized
        assert "evidence_captured_unreviewed" in normalized
        assert "human_evidence_blocked" in normalized
        assert "todo pacote permanece bloqueado" in normalized
        assert "depois de validar a integridade" in normalized
        assert "ledger nativo `present_complete` nao vazio" in normalized
        assert "inventory_blocked" in normalized
        assert "casos anteriores podem terminar" in normalized
        assert "inventarios dev e prod capturados" in normalized
        assert "revisao independente bloqueada" in normalized
        assert "decisao owner-01 registrada" in normalized
        assert "cross_package_ok" in normalized
        assert "163 passed, 2 skipped" in normalized
        assert "nao autoriza" in normalized and "dml" in normalized
        assert "runner" in normalized and "bloquead" in normalized

        for stale_claim in (
            "produz `evidence_captured_unreviewed` e termina no verificador com",
            "ao ser apresentado ao verificador, esse pacote termina em",
        ):
            assert stale_claim not in normalized, f"stale verifier claim in {path}"

    stale_or_false_claims = {
        "inventarios dev/prod ainda nao capturados",
        "revisar e integrar esta pr",
        "preparar uma missao separada",
        "historico reconciliado",
        "reconciliacao concluida",
        "decisoes humanas concluidas",
        "runner liberado",
        "status e apply liberados",
        "artefatos ainda nao integrados",
        "artefatos ainda nao versionados",
        "revisar e integrar a pr #329",
    }
    for path in gate_contracts | capture_primary_records:
        normalized = _normalized_prose(path.read_text(encoding="utf-8"))
        for stale_claim in stale_or_false_claims:
            assert stale_claim not in normalized, f"stale or false claim in {path}"

    mission_register = (
        REPO_ROOT / "docs" / "ops" / "POST-V1-MISSION-REGISTER.md"
    ).read_text(encoding="utf-8")
    for workflow_id in (
        "33184817567",
        "33184817526",
        "33184817442",
        "33184817428",
        "33184817512",
        "33185027149",
        "33185027115",
        "33185027132",
        "33185027091",
        "33185027090",
        "33207468055",
        "33207468044",
        "33207468014",
        "33207468132",
        "33207468082",
        "33207645381",
        "33207645348",
        "33207645362",
        "33207645399",
        "33207645340",
        "33222301288",
        "33222301419",
        "33222301331",
        "33222301296",
        "33222301367",
        "33222447467",
        "33222447447",
        "33222447518",
        "33222447506",
        "33222447495",
    ):
        assert workflow_id in mission_register

    for deployment_id in ("6147914118", "6147952424", "6150482852"):
        assert deployment_id in mission_register

    reconciliation_contract = RECONCILIATION_CONTRACT_PATH.read_text(
        encoding="utf-8"
    )
    for workflow_id in (
        "33222301288",
        "33222301419",
        "33222301331",
        "33222301296",
        "33222301367",
        "33222447467",
        "33222447447",
        "33222447518",
        "33222447506",
        "33222447495",
    ):
        assert workflow_id in reconciliation_contract

    assert ADR_PATH.is_file()
    assert "TEMPLATE_ONLY / NOT_APPROVED" in ADR_PATH.read_text(
        encoding="utf-8"
    )
    assert not any(
        "approved" in path.name.lower()
        for path in TEMPLATE_PATH.parent.iterdir()
    )


def test_captured_inventory_artifacts_are_unreviewed_and_blocked() -> None:
    packets_dir = (
        REPO_ROOT / "docs" / "governance" / "migrations" / "packets"
    )
    expected = {
        "DEV": {
            "public_state": "PRESENT_COMPLETE",
            "public_rows": 33,
            "native_rows": 6,
            "captured_at": "2026-08-28T22:43:11.454382Z",
        },
        "PROD": {
            "public_state": "ABSENT_CONFIRMED",
            "public_rows": 0,
            "native_rows": 32,
            "captured_at": "2026-08-28T22:47:43.965243Z",
        },
    }
    expected_basenames = {
        f"migration-history-reconciliation-{environment.lower()}-evidence-v1{suffix}.json"
        for environment in expected
        for suffix in (
            "",
            "-public-capture-receipt-v1",
            "-native-capture-receipt-v1",
        )
    }
    actual_basenames = {
        path.name
        for path in packets_dir.glob(
            "migration-history-reconciliation-*-evidence-v1*.json"
        )
    }
    assert actual_basenames == expected_basenames

    for environment, inventory in expected.items():
        prefix = (
            f"migration-history-reconciliation-{environment.lower()}-evidence-v1"
        )
        package_path = packets_dir / f"{prefix}.json"
        package = json.loads(
            package_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
        assert package["artifact_state"] == "EVIDENCE_CAPTURED_UNREVIEWED"
        assert package["subject"]["environment"] == environment
        assert package["subject"]["repository_sha"] == (
            "656d1d9eebe90ad4b2cbb35c21939a6796c46bfe"
        )
        assert len(package["catalog"]["entries"]) == 75
        assert package["catalog"]["digest_sha256"] == (
            "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f"
        )
        public = package["inventories"]["public_ledger"]
        native = package["inventories"]["native_ledger"]
        assert public["capture_state"] == inventory["public_state"]
        assert len(public["rows"]) == inventory["public_rows"]
        assert native["capture_state"] == "PRESENT_COMPLETE"
        assert len(native["rows"]) == inventory["native_rows"]
        assert public["captured_at_utc"] == inventory["captured_at"]
        assert native["captured_at_utc"] == inventory["captured_at"]
        assert all(row["name"] is None for row in native["rows"])
        assert package["reconciliation"]["state"] == "NOT_REVIEWED"
        assert package["attestation"]["state"] == "NOT_ATTESTED"

        for source, role in (
            ("public", "PUBLIC_LEDGER_CAPTURE"),
            ("native", "NATIVE_LEDGER_CAPTURE"),
        ):
            receipt_path = packets_dir / f"{prefix}-{source}-capture-receipt-v1.json"
            receipt = json.loads(
                receipt_path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
            assert receipt["receipt_role"] == role
            assert receipt["subject"] == {
                "environment": environment,
                "target_binding_sha256": package["subject"][
                    "target_binding_sha256"
                ],
                "repository_sha": package["subject"]["repository_sha"],
            }
            assert receipt["capture_sql_sha256"] == (
                "8b589e5dda722691fead34cbd63cab75a7a22f32e0cf4bdfe64d6cef603866ee"
            )
            preimage = receipt["snapshot_record"]["preimage"]
            assert preimage["captured_at_utc"] == inventory["captured_at"]
            assert preimage["postgres_major"] == 17
            assert preimage["read_only"] is True
            assert receipt["safety_contract"]["runner_unlock"] == "BLOCKED"
            assert (
                receipt["safety_contract"]["environment_operation"]
                == "BLOCKED"
            )


def test_migration_history_human_review_guide_is_sanitized_and_fail_closed() -> None:
    guide = HUMAN_REVIEW_GUIDE_PATH.read_text(encoding="utf-8")
    normalized = _normalized_prose(guide)

    assert "owner-01" in normalized
    assert "reviewer-01" in normalized
    assert "operational_authorization=blocked" in normalized
    assert "pessoas distintas" in normalized
    assert "registro externo controlado" in normalized
    assert "nao ocupa nenhum dos dois papeis" in normalized
    assert "sem banco, rede, credencial" in normalized
    assert "blocked_ledger_divergence" in normalized
    assert "blocked_evidence_insufficient" in normalized
    assert "sem backfill ou reaplicacao automatica" in normalized
    assert "revisao independente bloqueada concluida" in normalized
    assert "decisao owner-01 registrada" in normalized
    assert "2026-08-29t02:49:00z" in normalized
    assert "raniel" not in normalized
    assert "sarah" not in normalized
    assert "@" not in guide

    expected_hashes = {
        "136b3938c62c80b0882dd084abc43bfdc58465f957a1040502b0e40aa11481fa",
        "aa79b4f52a2c152f8a1451596f37d0479f3e336bba304a8e34f579f1f39a767f",
        "c2c9c29acaf469e1e560e9fb858c260b3fa8742c0b4b5fe692c6b763755db44c",
        "34123027ab1b64108a9fb8d6c97da327306acd5ca49a11de2208eb699debc135",
        "067377258893391c10a20da1e80c5b37154b2073d4060a8bda6c9628aa753524",
        "a4ba967570985682bcff19ea5c0c9dc78f2ed96a07377cbdad3dcddf8f6dceda",
        "18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133",
        "0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240",
    }
    assert expected_hashes <= set(re.findall(r"\b[0-9a-f]{64}\b", guide))

    packets_dir = HUMAN_REVIEW_GUIDE_PATH.parent / "packets"
    dev_package = json.loads(
        (
            packets_dir / "migration-history-reconciliation-dev-evidence-v1.json"
        ).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    public_rows = dev_package["inventories"]["public_ledger"]["rows"]
    catalog_entries = dev_package["catalog"]["entries"]
    mismatches = [
        position
        for position, row in enumerate(public_rows)
        if row["name"] != catalog_entries[position]["name"]
    ]
    assert mismatches == list(range(25, 33))
    assert "oito posicoes" in normalized
    assert "posicao 25" in normalized

    contract = RECONCILIATION_CONTRACT_PATH.read_text(encoding="utf-8")
    assert "migration-history-human-review-guide-v1.md" in contract


def test_migration_operator_docs_reject_obsolete_generic_apply_contract() -> None:
    migration_readme = (
        REPO_ROOT / "backend" / "migrations" / "README.md"
    ).read_text(encoding="utf-8")
    staging_runbook = (REPO_ROOT / "deploy" / "STAGING.md").read_text(
        encoding="utf-8"
    )
    ledger_runbook = (
        REPO_ROOT
        / "docs"
        / "security"
        / "2026-08-20-v1-ledger-hardening-gate.md"
    ).read_text(encoding="utf-8")
    production_runbook = (
        REPO_ROOT / "docs" / "ops" / "PRODUCTION-RUNBOOK.md"
    ).read_text(encoding="utf-8")
    historical_m06 = (
        REPO_ROOT
        / "docs"
        / "security"
        / "2026-08-10-v1-m06-hardening.md"
    ).read_text(encoding="utf-8")

    readme_normalized = _normalized_prose(migration_readme)
    staging_normalized = _normalized_prose(staging_runbook)
    ledger_normalized = _normalized_prose(ledger_runbook)
    production_normalized = _normalized_prose(production_runbook)
    historical_normalized = _normalized_prose(historical_m06)

    for content in (migration_readme, staging_runbook):
        assert "--database-url" not in content
        assert "STAGING_DATABASE_URL" not in content

    for normalized in (readme_normalized, staging_normalized):
        assert "m06_migration_database_url" in normalized
        assert "bootstrap-ledger" in normalized
        assert "bootstrap_ledger" in normalized
        assert "ledger vazio" in normalized
        assert "status" in normalized
        assert "apply" in normalized
        assert "bloquead" in normalized
        assert "pacote deny-state versionado" in normalized
        assert "verificador stdlib separado do runner" in normalized
        assert "revisao independente bloqueada" in normalized
        assert "decisao owner-01 registrada" in normalized
        assert "dml" in normalized
        assert "nao infere migration aplicada" in normalized
        assert "operational_authorization=blocked" in normalized

    for normalized in (readme_normalized, staging_normalized, ledger_normalized):
        assert "326/326" in normalized
        assert "3803 deselecionados" in normalized
        assert "2 warnings preexistentes" in normalized
        assert "162.77s" in normalized
        assert "suite offline integral" in normalized
        assert "interrompida apos 5 min sem saida ou progresso" in normalized
        assert "`inconclusivo`" in normalized
        assert "nao verde nem falha" in normalized
        assert "workflows backend tests da pr #323 e do pos-merge" in normalized
        assert "backend tests da pr permanece gate" not in normalized

    assert "unico hardening" in ledger_normalized
    assert "integrado e comprovado somente offline" in ledger_normalized
    assert "acesso aos bancos dev ou prod" in ledger_normalized
    assert "supabase_migrations.schema_migrations" in ledger_normalized

    assert "dois historicos diferentes" in production_normalized
    assert "ledger nativo do supabase" in production_normalized
    assert "ledger de controle" in production_normalized
    assert "public.schema_migrations" in production_normalized
    assert "esta ausente" in production_normalized
    assert "integrado em `main` pela pr #323" in production_normalized

    for normalized in (
        readme_normalized,
        staging_normalized,
        ledger_normalized,
        production_normalized,
    ):
        assert "3a5789c784017ab15a43e28c4270d25af8618359" in normalized
        assert "preview e production automaticos do frontend" in normalized
        assert "nao prova" in normalized
        assert "backend" in normalized
        assert "banco" in normalized

    assert "preserva a decisao e as provas" in historical_normalized
    assert "historicas da m06" in historical_normalized
    assert "comprovad" in historical_normalized
    assert "nada nesta" in historical_normalized
    assert "nota autoriza dev, prod" in historical_normalized
    assert "delta atual tambem implementa" not in historical_normalized


def test_postmerge_ledger_docs_reject_premerge_delta_language() -> None:
    postmerge_docs = {
        REPO_ROOT / "docs" / "ai" / "PRD-COVERAGE.md",
        REPO_ROOT / "docs" / "ops" / "POST-V1-MISSION-REGISTER.md",
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-28-d2b2b2-consent-decision-packet-contract.md",
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-28-d2b2b3-master-governance-drafts.md",
        REPO_ROOT
        / "docs"
        / "security"
        / "2026-08-20-v1-ledger-hardening-gate.md",
    }

    for path in postmerge_docs:
        normalized = _normalized_prose(path.read_text(encoding="utf-8"))
        assert "este delta implementa" not in normalized
        assert "delta atual tambem contem" not in normalized
        assert "desenvolvida e comprovada offline sobre a base" in normalized
        assert "foi integrada pela pr #323" in normalized


def test_reconciliation_candidate_docs_reject_consumed_gate_and_false_authority() -> None:
    candidate_docs = {
        REPO_ROOT / "SPEC.md",
        REPO_ROOT / "SPEC_PROGRESS.md",
        REPO_ROOT
        / "docs"
        / "Docs20260611_163530"
        / "PRD20260611_163530.md",
        REPO_ROOT / "docs" / "WIKI-IGREJA12.md",
        REPO_ROOT / "docs" / "ai" / "AI-BOOTSTRAP.md",
        REPO_ROOT / "docs" / "ai" / "PRD-COVERAGE.md",
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-28-d2b2b2-consent-decision-packet-contract.md",
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-28-d2b2b3-master-governance-drafts.md",
        REPO_ROOT / "docs" / "ops" / "POST-V1-MISSION-REGISTER.md",
        REPO_ROOT / "backend" / "migrations" / "README.md",
        REPO_ROOT / "deploy" / "STAGING.md",
        REPO_ROOT
        / "docs"
        / "security"
        / "2026-08-20-v1-ledger-hardening-gate.md",
        REPO_ROOT / "docs" / "ops" / "PRODUCTION-RUNBOOK.md",
        RECONCILIATION_CONTRACT_PATH,
        CANONICAL_SCHEMA_DERIVATION_ADR_PATH,
    }
    stale_claims = {
        "implementar e testar somente offline",
        "concluir a pr offline de reconciliacao historica humana",
        "produzir a reconciliacao historica humana versionada",
        "concluir a reconciliacao historica humana offline",
        "historico reconciliado",
        "reconciliacao concluida",
        "ledgers equivalentes",
        "ledgers sincronizados",
        "status e apply liberados",
        "delta atual tambem implementa",
        "pode aprovar somente a preparacao de um manifesto estatico",
        "pode aprovar apenas a preparacao do manifesto estatico",
        "pode aprovar somente um manifesto estatico do schema",
        "desenho de uma missao posterior e separada de atestacao read-only",
    } | CONSUMED_PREMERGE_DERIVATION_GATE_CLAIMS

    for path in candidate_docs:
        normalized = _normalized_prose(path.read_text(encoding="utf-8"))
        for stale_claim in stale_claims:
            assert stale_claim not in normalized, f"stale claim in {path}"
        assert "operational_authorization=blocked" in normalized


def test_canonical_schema_derivation_docs_preserve_offline_only_limits() -> None:
    canonical_docs = {
        REPO_ROOT / "docs" / "ai" / "AI-BOOTSTRAP.md",
        REPO_ROOT / "docs" / "ai" / "PRD-COVERAGE.md",
        REPO_ROOT / "docs" / "WIKI-IGREJA12.md",
        REPO_ROOT / "docs" / "ops" / "POST-V1-MISSION-REGISTER.md",
        REPO_ROOT / "SPEC_PROGRESS.md",
        REPO_ROOT / "SPEC.md",
        REPO_ROOT / "docs" / "Docs20260611_163530" / "PRD20260611_163530.md",
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-28-d2b2b2-consent-decision-packet-contract.md",
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-28-d2b2b3-master-governance-drafts.md",
        REPO_ROOT / "backend" / "migrations" / "README.md",
        REPO_ROOT / "deploy" / "STAGING.md",
        REPO_ROOT / "docs" / "ops" / "PRODUCTION-RUNBOOK.md",
        REPO_ROOT / "docs" / "security" / "2026-08-20-v1-ledger-hardening-gate.md",
        RECONCILIATION_CONTRACT_PATH,
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-29-migration-history-divergence-remediation.md",
    }

    common_required = {
        "operational_authorization=blocked",
        "pr #337",
        "abf6f823336b81e93ec1c942dcd5a357d8ac797c",
        "278afb205a3b4735d4aeb66e2e585f71fd562ef7",
        "mergedat=2026-08-30t11:38:16z",
        "6166209567",
        "created_at=2026-08-30t11:39:02z",
        "pr #334",
        "a864730f0b678cca39cebfa6bb378243ba031cd6",
        "c8427b1a505c0aad2a5f675d3bf456ee33716690",
        "commit date=2026-08-29t21:21:15z",
        "mergedat=2026-08-29t21:21:16z",
        "6160229001",
        "os checks provam apenas o comportamento exercitado naquele sha",
        "metadata do deployment prova somente o frontend",
        "nao prova backend, banco, migration, runtime ou atestacao de ambiente",
    }
    prohibited = {
        "schema final de dev ou prod foi atestado",
        "data api atestada",
        "realtime atestado",
        "runner liberado",
        "reconciliacao de ledger aprovada",
    }

    for path in canonical_docs:
        normalized = _normalized_prose(path.read_text(encoding="utf-8"))
        assert all(item in normalized for item in common_required), (
            f"offline derivation record missing in {path}"
        )
        _assert_current_preflight_gate(path, normalized)
        for stale_claim in CONSUMED_PREMERGE_DERIVATION_GATE_CLAIMS:
            assert stale_claim not in normalized, f"stale pre-merge claim in {path}"
        for claim in prohibited:
            assert claim not in normalized, f"false authority in {path}"

    adr = _normalized_prose(CANONICAL_SCHEMA_DERIVATION_ADR_PATH.read_text(encoding="utf-8"))
    assert "derivacao canonica reproduzida e verificada somente offline em pg17 descartavel" in adr
    assert "75/75 migrations" in adr
    assert "388390 bytes identicos" in adr
    assert "21 passed, 1 skipped" in adr
    assert "286 passed, 48 skipped" in adr
    assert "github actions usa o mapeamento host:container" in adr
    assert "data api e realtime continuam nao atestados" in adr
    assert DEV_IDENTITY_PREFLIGHT_RUNNER_CURRENT_GATE.casefold() in adr
    assert "review_and_integrate_read_only_environment_attestation_pr" not in adr
    assert "pr #334" in adr
    assert "a864730f0b678cca39cebfa6bb378243ba031cd6" in adr
    assert "c8427b1a505c0aad2a5f675d3bf456ee33716690" in adr
    assert "commit date=2026-08-29t21:21:15z" in adr
    assert "mergedat=2026-08-29t21:21:16z" in adr
    for run_id in {
        "33266660793",
        "33266660831",
        "33266660798",
        "33266660804",
        "33266660852",
        "33266660794",
        "33275857135",
        "33275857158",
        "33275857195",
        "33275857144",
        "33275857174",
        "33275857154",
    }:
        assert run_id in adr
    assert "6160229001" in adr
    assert "created_at=2026-08-29t21:22:00z" in adr
    assert "superficie sanitizada da api `deployments/{deployment_id}` registrou" in adr
    assert "superficie sanitizada `deployments/{deployment_id}/statuses` registrou" in adr
    assert "state=success" in adr
    assert "created_at=2026-08-29t21:22:01z" in adr
    assert "intervalo entre esses registros nao prova duracao de build nem reuso de artefato" in adr
    assert "os checks provam apenas o comportamento exercitado naquele sha" in adr
    assert "metadata do deployment prova somente o frontend" in adr
    assert "nao prova backend, banco, migration, runtime ou atestacao de ambiente" in adr


def test_environment_attestation_tooling_docs_record_postmerge_deny_state() -> None:
    canonical_docs = {
        REPO_ROOT / "docs" / "ai" / "AI-BOOTSTRAP.md",
        REPO_ROOT / "docs" / "ai" / "PRD-COVERAGE.md",
        REPO_ROOT / "docs" / "WIKI-IGREJA12.md",
        REPO_ROOT / "docs" / "ops" / "POST-V1-MISSION-REGISTER.md",
        REPO_ROOT / "SPEC_PROGRESS.md",
        REPO_ROOT / "SPEC.md",
        REPO_ROOT / "docs" / "Docs20260611_163530" / "PRD20260611_163530.md",
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-28-d2b2b2-consent-decision-packet-contract.md",
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-28-d2b2b3-master-governance-drafts.md",
    }
    supporting_docs = {
        CANONICAL_SCHEMA_DERIVATION_ADR_PATH,
        RECONCILIATION_CONTRACT_PATH,
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-29-migration-history-divergence-remediation.md",
        REPO_ROOT / "backend" / "migrations" / "README.md",
        REPO_ROOT / "deploy" / "STAGING.md",
        REPO_ROOT / "docs" / "ops" / "PRODUCTION-RUNBOOK.md",
        REPO_ROOT
        / "docs"
        / "security"
        / "2026-08-20-v1-ledger-hardening-gate.md",
        ENVIRONMENT_ATTESTATION_ADR_PATH,
    }

    required = {
        "be958ce96e65d3d497923b7f5f912676634e9587",
        "1072e6a8e85d201a1c82f37a8ddeac5417300c49",
        "367 passed, 47 skipped",
        "sarah/terra",
        "claude opus",
        "execution error",
        "nenhum artefato ambiental foi produzido",
        "verificador python",
        "hmac",
        "correlacao",
        "anti-swap",
        "autorizacao humana",
        "project ref",
        "platform_surfaces_unattested",
        "operational_authorization=blocked",
        "environment_attestation_complete=false",
        "prod esta explicitamente fora",
        "pr #337",
        "abf6f823336b81e93ec1c942dcd5a357d8ac797c",
        "278afb205a3b4735d4aeb66e2e585f71fd562ef7",
        "mergedat=2026-08-30t11:38:16z",
        "33309430738",
        "33309430763",
        "33309430775",
        "33309430797",
        "33309430744",
        "33309430731",
        "33309430799",
        "6166209567",
        "state=success",
        "created_at=2026-08-30t11:39:02z",
        "prova somente o frontend",
        "nao prova backend, banco ou runtime",
    }
    blocked_operations = {
        "runner",
        "dml",
        "migration",
        "reconciliacao",
        "backfill",
        "deploy",
        "flag",
        "runtime",
    }

    for path in canonical_docs | supporting_docs:
        normalized = _normalized_prose(path.read_text(encoding="utf-8"))
        assert all(item in normalized for item in required), f"deny-state missing in {path}"
        _assert_current_preflight_gate(path, normalized)
        assert "separate_read_only_environment_attestation" not in normalized
        assert (
            "nenhum dev ou prod foi consultado" in normalized
            or "nenhuma consulta foi feita a dev ou prod" in normalized
        )
        assert all(item in normalized for item in blocked_operations), (
            f"blocked operation missing in {path}"
        )
        assert "schema" in normalized and "envelope" in normalized
        assert "81/81" in normalized or "81 passed" in normalized
        assert "82/82" in normalized or "82 passed" in normalized
        assert _normalized_prose(ENVIRONMENT_ATTESTATION_POSTMERGE_STATE) in normalized
        assert "review_and_integrate_read_only_environment_attestation_pr" not in normalized
        be958ce_index = normalized.index("be958ce96e65d3d497923b7f5f912676634e9587")
        be958ce_context = normalized[max(0, be958ce_index - 160) : be958ce_index + 160]
        assert "foi integrada" not in be958ce_context
        assert "foi integrado" not in be958ce_context
        assert "implementad" in be958ce_context
        assert "esse commit integra somente tooling" not in normalized

    for path in canonical_docs:
        normalized = _normalized_prose(path.read_text(encoding="utf-8"))
        assert normalized.count("proximo gate unico") == 1
        assert normalized.count(
            DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CURRENT_GATE.casefold()
        ) == 1
        assert "review_and_integrate_read_only_environment_attestation_pr" not in normalized
        assert "separate_read_only_environment_attestation" not in normalized

    adr = _normalized_prose(ENVIRONMENT_ATTESTATION_ADR_PATH.read_text(encoding="utf-8"))
    assert "json schema valida o envelope estrutural" in adr
    assert "validacao semantica completa" in adr
    assert "identidade bruta" in adr
    assert "canal transitorio privado" in adr
    assert "nao concede autorizacao humana" in adr
    assert "nao prova observacao direta do project ref" in adr
    assert _normalized_prose(ENVIRONMENT_ATTESTATION_POSTMERGE_STATE) in adr
    assert "foi implementado um capturador" in adr
    assert "integracao e ci pos-merge" in adr


def test_dev_identity_preflight_docs_record_blocked_live_diagnostics() -> None:
    canonical_docs = {
        REPO_ROOT / "SPEC.md",
        REPO_ROOT / "SPEC_PROGRESS.md",
        REPO_ROOT / "docs" / "Docs20260611_163530" / "PRD20260611_163530.md",
        REPO_ROOT / "docs" / "WIKI-IGREJA12.md",
        REPO_ROOT / "docs" / "ai" / "AI-BOOTSTRAP.md",
        REPO_ROOT / "docs" / "ai" / "PRD-COVERAGE.md",
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-28-d2b2b2-consent-decision-packet-contract.md",
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-28-d2b2b3-master-governance-drafts.md",
        REPO_ROOT / "docs" / "ops" / "POST-V1-MISSION-REGISTER.md",
    }
    supporting_docs = {
        REPO_ROOT / "backend" / "migrations" / "README.md",
        REPO_ROOT / "deploy" / "STAGING.md",
        REPO_ROOT / "docs" / "ops" / "PRODUCTION-RUNBOOK.md",
        REPO_ROOT
        / "docs"
        / "security"
        / "2026-08-20-v1-ledger-hardening-gate.md",
        RECONCILIATION_CONTRACT_PATH,
        REPO_ROOT
        / "docs"
        / "decisions"
        / "2026-08-29-migration-history-divergence-remediation.md",
        CANONICAL_SCHEMA_DERIVATION_ADR_PATH,
        ENVIRONMENT_ATTESTATION_ADR_PATH,
    }
    required = {
        _normalized_prose(DEV_IDENTITY_PREFLIGHT_RUNNER_POSTMERGE_STATE),
        "fe7dcd394bd1cfdc96204ad994bcba9f0c96adb4",
        "1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f",
        "d96fab1afe99531e3cee0f84bc285876de303ed0265fa41c51f8da9a7bcab0a0",
        "ceecfe9afa09066e4863e93be556b8f92c00a2992e0a0aef3b4253458f6fc318",
        "68f9790a734f8adf78db8a716a5c2d99adad165f00737f922db90afa614b4ed8",
        "80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf",
        "210/210",
        "verify_full_explicit_ca",
        "tls_ca_certificate_sha256",
        "digest da ca",
        "process_invocation_only",
        "nova autorizacao nominal",
        "cada invocacao",
        "hmac",
        "somente correlacao e anti-swap",
        "nao substitui autorizacao humana",
        "zero arquivo",
        "zero recibo",
        "zero captura",
        "zero materializacao",
        "buffers de chave e nonce",
        "zerados",
        "descritores sao fechados",
        "certificados tls temporarios",
        "removidos apos a prova",
        "pr #340",
        "b29d3f494eabc3a04fe7f2c434758ad274f03930",
        "82413edb884125d4d8f6e7946ffcaaf48ed8491c",
        "mergedat=2026-08-30t13:55:11z",
        "33315460948",
        "33315460933",
        "33315460941",
        "33315460942",
        "33315460949",
        "33315460934",
        "33315460939",
        "6167369343",
        "state=success",
        "2026-08-30t13:55:56z",
        "prova somente o frontend",
        "nao prova backend, banco ou runtime",
        "dev e prod nao foram consultados",
        "prod continua fora",
    }

    for path in canonical_docs | supporting_docs:
        normalized = _normalized_prose(path.read_text(encoding="utf-8"))
        assert all(item in normalized for item in required), (
            f"DEV identity preflight runner deny-state missing in {path}"
        )
        assert "sete workflows pos-merge" in normalized
        assert "captura executada" not in normalized
        assert "materializacao executada" not in normalized
        assert "preflight dev executado" not in normalized
        assert "ci ainda nao foi executado" not in normalized
        assert "ainda nao integrado" not in normalized
        assert "review_and_integrate_dev_identity_preflight_runner_pr" not in normalized

    diagnostic_required = {
        _normalized_prose(DEV_IDENTITY_PREFLIGHT_DIAGNOSTICS_STATE),
        "2026-08-30",
        "64cc157d649256a4a9819741f4276c0420590fd1",
        "duas invocacoes dev foram feitas",
        "autorizacoes humanas nominais distintas e exclusivas",
        "process_invocation_only",
        "timestamp operacional preciso nao foi preservado",
        "nenhum horario utc foi inferido",
        "exit `7`",
        "result=blocked_database_preflight_failed",
        "rollback_confirmed=false",
        "connection_closed=true",
        "operational_authorization=false",
        "next_stage_authorized=false",
        "capture_executed=false",
        "materialization_executed=false",
        "prod_accessed=false",
        "nao provam se houve conexao",
        "nao provam sucesso ou falha de autenticacao",
        "nao identificam a causa raiz",
        "2/2",
        "full-main",
        "postgresql 17 tls descartavel",
        "97/97",
        "1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f",
        "80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf",
        "ddbc092216604e65cf86070d409837c7d328da96116ae5ea8d0947195b421b9e",
        "runner permaneceu intacto",
        "workflow",
        "nao reclassifica dev",
    }

    historical_logs_gate_required = {
        DEV_IDENTITY_PREFLIGHT_RUNNER_CURRENT_GATE.casefold(),
        "nao autoriza retry",
        "nova invocacao dev",
        "autorizacao humana nova, nominal, exclusiva e separada",
        "revisao read-only e sanitizada",
        "fonte",
        "filtros",
        "janela temporal minima",
        "ainda nao foram delimitados",
        "precisam constar da nova autorizacao antes de qualquer acesso",
        "nenhum log foi acessado nesta pr",
        "consulta a prod",
        "banco ou sql",
        "exportacao ou persistencia de logs",
    }

    postmerge_required = {
        _normalized_prose(DEV_IDENTITY_PREFLIGHT_DIAGNOSTICS_POSTMERGE_STATE),
        "pr #342",
        "5076c47b19fffe503e823d68c6dadfc59b11ed5d",
        "bc202da6c0ef83e03ded4392e508441cd4d6a188",
        "mergedat=2026-08-30t15:24:45z",
        "sete workflows pos-merge",
        "33319560819",
        "33319560923",
        "33319560908",
        "33319560769",
        "33319560836",
        "33319560781",
        "33319560786",
        "6168185324",
        "17531418022",
        "state=success",
        "created_at=updated_at=2026-08-30t15:25:32z",
        "prova somente o frontend",
        "nao prova backend, banco ou runtime",
        "nao repetiu o preflight",
        "nao consultou logs",
        "nao fez novo acesso a dev ou prod",
        "nao determinou a causa do exit `7`",
        "runner e workflow permanecem intactos",
    }

    diagnostic_records = canonical_docs | supporting_docs
    for path in diagnostic_records:
        normalized = _normalized_prose(path.read_text(encoding="utf-8"))
        missing = sorted(item for item in diagnostic_required if item not in normalized)
        assert not missing, (
            f"DEV identity preflight diagnostics missing in {path}: {missing}"
        )
        postmerge_missing = sorted(
            item for item in postmerge_required if item not in normalized
        )
        assert not postmerge_missing, (
            f"DEV identity preflight postmerge evidence missing in {path}: "
            f"{postmerge_missing}"
        )
        if path in supporting_docs and path not in DEV_CONNECT_TLS_AUTH_CURRENT_DOCS:
            historical_gate_missing = sorted(
                item for item in historical_logs_gate_required if item not in normalized
            )
            assert not historical_gate_missing, (
                f"historical DEV logs gate missing in {path}: "
                f"{historical_gate_missing}"
            )
        assert "separate_nominal_dev_read_only_preflight_authorization" not in normalized
        assert "review_and_integrate_dev_identity_preflight_diagnostics_pr" not in normalized
        assert "review_and_integrate_dev_identity_preflight_diagnostics_postmerge_pr" not in normalized
        assert "nova reconciliacao documental pos-merge" not in normalized
        assert "conexao falhou" not in normalized
        assert "autenticacao falhou" not in normalized
        assert "causa raiz confirmada" not in normalized

    for path in canonical_docs | supporting_docs:
        normalized = _normalized_prose(path.read_text(encoding="utf-8"))
        assert "2026-08-30-dev-identity-preflight-diagnostics.md" in normalized

    for path in canonical_docs:
        normalized = _normalized_prose(path.read_text(encoding="utf-8"))
        assert normalized.count("proximo gate unico") == 1
        assert normalized.count(
            DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CURRENT_GATE.casefold()
        ) == 1
        assert "review_and_integrate_dev_identity_preflight_runner_pr" not in normalized
        assert "review_and_integrate_dev_identity_preflight_diagnostics_pr" not in normalized
        assert "separate_nominal_dev_read_only_preflight_authorization" not in normalized

    diagnostics_adr = _normalized_prose(
        DEV_IDENTITY_PREFLIGHT_DIAGNOSTICS_ADR_PATH.read_text(encoding="utf-8")
    )
    adr_required = {
        _normalized_prose(DEV_IDENTITY_PREFLIGHT_DIAGNOSTICS_STATE),
        "2026-08-30",
        "64cc157d649256a4a9819741f4276c0420590fd1",
        "duas invocacoes",
        "autorizacoes humanas nominais distintas e exclusivas",
        "process_invocation_only",
        "timestamp operacional preciso das duas invocacoes nao foi preservado",
        "nenhum horario utc foi inferido",
        "exit `7`",
        "result=blocked_database_preflight_failed",
        "rollback_confirmed=false",
        "connection_closed=true",
        "operational_authorization=false",
        "next_stage_authorized=false",
        "capture_executed=false",
        "materialization_executed=false",
        "prod_accessed=false",
        "nao e permitido inferir",
        "se houve ou nao conexao",
        "autenticacao teve sucesso ou falhou",
        "causa raiz",
        "2/2",
        "97/97",
        "1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f",
        "80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf",
        "ddbc092216604e65cf86070d409837c7d328da96116ae5ea8d0947195b421b9e",
        DEV_IDENTITY_PREFLIGHT_RUNNER_CURRENT_GATE.casefold(),
        "nao autoriza retry",
        _normalized_prose(DEV_IDENTITY_PREFLIGHT_DIAGNOSTICS_POSTMERGE_STATE),
        "pr #342",
        "5076c47b19fffe503e823d68c6dadfc59b11ed5d",
        "bc202da6c0ef83e03ded4392e508441cd4d6a188",
        "mergedat=2026-08-30t15:24:45z",
        "33319560819",
        "33319560923",
        "33319560908",
        "33319560769",
        "33319560836",
        "33319560781",
        "33319560786",
        "6168185324",
        "17531418022",
        "created_at=updated_at=2026-08-30t15:25:32z",
        "nenhum log foi acessado nesta pr",
        "janela temporal minima ainda nao foram delimitados",
    }
    assert all(item in diagnostics_adr for item in adr_required)
    assert diagnostics_adr.count("proximo gate unico") == 1
    assert diagnostics_adr.count(
        DEV_IDENTITY_PREFLIGHT_RUNNER_CURRENT_GATE.casefold()
    ) == 1


def test_dev_connect_tls_auth_docs_record_offline_diagnostics_plan() -> None:
    canonical_required = {
        "bab031a7e0067a257eedb4a24c786cc925801463",
        "pr #344",
        "terceira",
        "process_invocation_only",
        "exit `7`",
        "result=blocked_database_preflight_failed",
        "preflight_failure_phase=connect_tls_auth",
        "2026-08-31t11:03:30z",
        "2026-08-31t11:18:30z",
        "janela",
        "nao e o horario",
        "timestamp",
        "nao foi preservado",
        "inferido",
        "dns, tcp, tls, ca, senha, autenticacao",
        "permanecem `unknown`",
        "autorizacao foi consumida",
        "nenhum log foi consultado",
        "nao houve retry",
        "diretorio temporario de autorizacao",
        "launcher",
        "worktree operacionais temporarios",
        "checkout ficou limpo",
        "sem `__pycache__` ou `.pyc`",
        "registro git obsoleto da worktree foi removido",
        "execution_disabled=true",
        "nao foi executado",
        "2026-08-31-dev-connect-tls-auth-transport-probe.md",
        "operational_authorization=false",
        "next_stage_authorized=false",
        DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CURRENT_GATE.casefold(),
        "autorizacao humana separada que nomeie o push",
        "abertura da pr",
        "ci do mesmo sha",
        "vercel preview automatico do frontend",
        "nao autoriza merge nem integracao",
        "deploy manual ou production",
    }

    postmerge_required = {
        "pr #346",
        "0c63dc29dc903e0e7012b9fb811b7b2ddb05ab51",
        "fb776e270bf3e2ffde0cbb28e400960591b74420",
        "mergedat=2026-08-31t13:02:07z",
        "sete workflows pos-merge",
        "33394774001",
        "33394774013",
        "33394773986",
        "33394774109",
        "33394774063",
        "33394773965",
        "33394774029",
        "6181597461",
        "17569033825",
        "state=success",
        "2026-08-31t13:02:53z",
        "prova somente o frontend",
        "nao prova saude funcional, backend, banco, dev, prod, probe ou migration",
        "execution_disabled=true",
        "implementacao e capacidade de rede ausentes",
        "probe nao executado",
        "operacao bloqueada",
    }

    candidate_required = {
        "pr #347",
        "0a257e9aa1985860d5ea0a4506d4f7e84c7b2312",
        "36f8d13284a8f4964d0258a2a3b845323a80fe7e",
        "mergedat=2026-08-31t14:26:10z",
        "sete workflows pos-merge",
        "6183047421",
        "17572803614",
        "state=success",
        "2026-08-31t14:26:57z",
        "prova somente o frontend",
        "4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9",
        "b79ff9d7473fdafd0a4fcd6ceba98b2c46f5470ef517b6663898812fe8b1296e",
        "90/90",
        "loopback tls sintetico descartavel",
        "seis descritores privados",
        "hash do project-ref dev",
        "registro de autorizacao",
        "sslrequest postgresql de oito bytes",
        "exige `s`",
        "fecha antes de startupmessage",
        "nao recebe senha, usuario, banco ou dsn",
        "nao tenta autenticacao nem sql",
        "plano json permanece historico e byte-identico",
        "execution_disabled=true",
        "implementation_present=false",
        "etapa anterior ja consumida",
        "unica rede desta rodada foi o `git fetch`",
        "nenhum probe vivo, dev, prod, banco ou log foi acessado",
        "operational_authorization=false",
        "next_stage_authorized=false",
    }

    for path in DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CANONICAL_DOCS:
        normalized = _normalized_prose(path.read_text(encoding="utf-8"))
        missing = sorted(item for item in canonical_required if item not in normalized)
        assert not missing, f"CONNECT_TLS_AUTH diagnostics missing in {path}: {missing}"
        postmerge_missing = sorted(
            item for item in postmerge_required if item not in normalized
        )
        assert not postmerge_missing, (
            f"CONNECT_TLS_AUTH postmerge evidence missing in {path}: "
            f"{postmerge_missing}"
        )
        candidate_missing = sorted(
            item for item in candidate_required if item not in normalized
        )
        assert not candidate_missing, (
            f"CONNECT_TLS_AUTH candidate evidence missing in {path}: "
            f"{candidate_missing}"
        )
        assert normalized.count("proximo gate unico") == 1
        assert normalized.count(
            DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CURRENT_GATE.casefold()
        ) == 1
        for stale_claim in DEV_PREFLIGHT_PHASE_DIAGNOSTICS_STALE_CLAIMS:
            assert stale_claim not in normalized

    phase_adr = _normalized_prose(
        DEV_PREFLIGHT_PHASE_DIAGNOSTICS_ADR_PATH.read_text(encoding="utf-8")
    )
    phase_required = {
        "integrado",
        "terceira invocacao dev bloqueada em connect_tls_auth",
        "causa indeterminada",
        "probe de transporte planejado offline e desabilitado",
        "pr #344",
        "bab031a7e0067a257eedb4a24c786cc925801463",
        "exit `7`",
        "result=blocked_database_preflight_failed",
        "preflight_failure_phase=connect_tls_auth",
        "2026-08-31t11:03:30z",
        "2026-08-31t11:18:30z",
        "timestamp operacional preciso nao foi preservado",
        "dns, tcp, tls, ca, senha, autenticacao",
        "permanecem `unknown`",
        "autorizacao foi consumida",
        "nenhum log foi consultado",
        "execution_disabled=true",
        "nao foi executado",
        "2026-08-31-dev-connect-tls-auth-transport-probe.md",
        "diretorio temporario de autorizacao",
        "checkout ficou limpo",
        DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CURRENT_GATE.casefold(),
        "nao autoriza merge nem integracao",
    }
    phase_required |= postmerge_required | candidate_required
    phase_missing = sorted(item for item in phase_required if item not in phase_adr)
    assert not phase_missing, f"preflight phase ADR missing: {phase_missing}"
    assert phase_adr.count("proximo gate unico") == 1
    assert phase_adr.count(
        DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CURRENT_GATE.casefold()
    ) == 1
    for stale_claim in DEV_PREFLIGHT_PHASE_DIAGNOSTICS_STALE_CLAIMS:
        assert stale_claim not in phase_adr

    diagnostics_adr = _normalized_prose(
        DEV_CONNECT_TLS_AUTH_DIAGNOSTICS_ADR_PATH.read_text(encoding="utf-8")
    )
    diagnostics_required = {
        "plano offline integrado",
        "resultado sanitizado registrado",
        "causa indeterminada",
        "candidato de probe implementado e comprovado offline",
        "ainda nao integrado",
        "probe nao executado",
        "bab031a7e0067a257eedb4a24c786cc925801463",
        "8da631fbb602488bb8c82ce1529c9d8ba17acbae8a318ea9b0fc24cdd8f65cd2",
        "2026-08-31t11:03:30z",
        "2026-08-31t11:18:30z",
        "horario operacional preciso nao foi preservado",
        "environment=dev",
        "operational_authorization=false",
        "next_stage_authorized=false",
        "capture_executed=false",
        "materialization_executed=false",
        "prod_accessed=false",
        "single_use_scope=process_invocation_only",
        "rollback_confirmed=false",
        "connection_closed=true",
        "preflight_failure_phase=connect_tls_auth",
        "result=blocked_database_preflight_failed",
        "exit `7`",
        "dns",
        "tcp",
        "tls e ca",
        "credencial e autenticacao",
        "`unknown`",
        "autorizacao foi consumida",
        "nao existe retry implicito",
        "diretorio temporario de autorizacao",
        "checkout usado para a missao ficou limpo",
        "execution_disabled=true",
        "nao resolve dns",
        "nao abre socket",
        "startupmessage",
        "telemetria de dns e rede",
        DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CURRENT_GATE.casefold(),
        "nao autoriza merge nem integracao",
        "implementation_present=false",
        "network_capability_present=false",
        "gate consumido pela abertura, revisao, ci e integracao da pr #346",
        "evidencia historica dos bytes integrados",
        "nao e um segundo gate corrente",
    }
    diagnostics_required |= postmerge_required - {
        "implementacao e capacidade de rede ausentes",
        "probe nao executado",
    }
    diagnostics_required |= candidate_required
    diagnostics_missing = sorted(
        item for item in diagnostics_required if item not in diagnostics_adr
    )
    assert not diagnostics_missing, (
        f"CONNECT_TLS_AUTH diagnostics ADR missing: {diagnostics_missing}"
    )
    assert diagnostics_adr.count("proximo gate unico") == 1
    assert diagnostics_adr.count(
        DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CURRENT_GATE.casefold()
    ) == 1
    for stale_claim in DEV_PREFLIGHT_PHASE_DIAGNOSTICS_STALE_CLAIMS:
        if stale_claim == DEV_CONNECT_TLS_AUTH_PLAN_REVIEW_GATE.casefold():
            continue
        assert stale_claim not in diagnostics_adr
    assert diagnostics_adr.count(
        DEV_CONNECT_TLS_AUTH_PLAN_REVIEW_GATE.casefold()
    ) == 1

    plan = json.loads(DEV_CONNECT_TLS_AUTH_PROBE_PLAN_PATH.read_text(encoding="utf-8"))
    assert plan["execution_mode"] == "OFFLINE_PLAN_ONLY"
    assert plan["execution_disabled"] is True
    assert plan["operational_authorization"] is False
    assert plan["next_stage_authorized"] is False
    assert plan["next_gate"] == DEV_CONNECT_TLS_AUTH_PLAN_REVIEW_GATE
    assert plan["next_gate"] != DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CURRENT_GATE
    assert plan["historical_result"]["precise_timestamp_preserved"] is False
    assert plan["historical_result"]["exit_code"] == 7
    assert plan["historical_result"]["sanitized_output"][
        "PREFLIGHT_FAILURE_PHASE"
    ] == "CONNECT_TLS_AUTH"
    assert plan["interpretation_boundary"]["root_cause"] == "UNDETERMINED"
    assert plan["future_probe_contract"]["implementation_present"] is False
    assert plan["future_probe_contract"]["network_capability_present"] is False
    assert plan["future_probe_contract"]["execution_disabled"] is True
    assert plan["mission_evidence"] == {
        "network_accessed": False,
        "dns_queried": False,
        "tcp_attempted": False,
        "tls_attempted": False,
        "password_accessed": False,
        "sql_executed": False,
        "database_session_established": False,
        "logs_accessed": False,
        "dev_accessed": False,
        "prod_accessed": False,
        "capture_executed": False,
        "materialization_executed": False,
    }

    technical_files = {
        REPO_ROOT / "backend" / "scripts" / "probe_dev_connect_tls_auth_transport.py": (
            "4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9"
        ),
        REPO_ROOT / "backend" / "tests" / "test_dev_connect_tls_auth_transport_probe.py": (
            "b79ff9d7473fdafd0a4fcd6ceba98b2c46f5470ef517b6663898812fe8b1296e"
        ),
        REPO_ROOT / "backend" / "scripts" / "preflight_migration_history_environment_identity.py": (
            "8da631fbb602488bb8c82ce1529c9d8ba17acbae8a318ea9b0fc24cdd8f65cd2"
        ),
        REPO_ROOT / "backend" / "tests" / "test_migration_history_environment_identity_preflight.py": (
            "c55726f0ad8abf7680de868cba155388f7e56773aa8054e556be89dc87aa90a8"
        ),
        REPO_ROOT / "backend" / "tests" / "test_migration_history_environment_identity_preflight_pg17.py": (
            "d86037d759d254581d2259026585ac768e4b2d68595473371ec65daf6c6de5a9"
        ),
    }
    for path, expected_sha256 in technical_files.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256

    readme = _normalized_prose(
        (REPO_ROOT / "backend" / "migrations" / "README.md").read_text(
            encoding="utf-8"
        )
    )
    assert DEV_CONNECT_TLS_AUTH_PLAN_REVIEW_GATE.casefold() in readme
    assert "conserva como evidencia historica" in readme
    assert "consumido pela pr #346" in readme
    assert "nao e um segundo gate corrente" in readme
    assert "aceite o vercel preview automatico do frontend" in readme
    assert "deploy manual ou production" in readme
    assert DEV_PREFLIGHT_PHASE_DIAGNOSTICS_CURRENT_GATE.casefold() in readme
    assert "4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9" in readme
    assert "b79ff9d7473fdafd0a4fcd6ceba98b2c46f5470ef517b6663898812fe8b1296e" in readme
    assert "90/90" in readme
    assert readme.count(DEV_CONNECT_TLS_AUTH_PLAN_REVIEW_GATE.casefold()) == 1


def test_schema_expectation_manifest_is_source_only_and_keeps_environment_gate() -> None:
    manifest = json.loads(SCHEMA_EXPECTATION_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["artifact_state"] == (
        "SOURCE_EXPECTATION_VERIFIED_ENVIRONMENT_UNATTESTED"
    )
    assert manifest["operational_authorization"] is False
    assert manifest["source_expectation"]["manifest_scope"] == (
        "SOURCE_LEVEL_EXPECTATION_ONLY"
    )
    assert manifest["source_expectation"]["final_schema_claim"] is False
    assert manifest["review"]["review_type"] == (
        "TECHNICAL_SELF_REVIEW_NOT_INDEPENDENT"
    )
    assert manifest["review"]["independent_review_complete"] is False
    assert manifest["next_gates"][0] == (
        "INDEPENDENT_SECURITY_AND_DATABASE_ARCHITECTURE_REVIEW"
    )
    assert manifest["next_gates"][1] == (
        "SEPARATE_OFFLINE_CANONICAL_SCHEMA_DERIVATION"
    )
    assert manifest["next_gates"][2] == (
        "SEPARATE_READ_ONLY_ENVIRONMENT_ATTESTATION"
    )
    assert "STATIC_SCHEMA_EXPECTATION_MANIFEST" not in manifest["next_gates"]
