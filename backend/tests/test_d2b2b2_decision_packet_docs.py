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

EXPECTED_TOP_LEVEL_KEYS = {
    "metadata",
    "delivery_control",
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
    "materialized_packet_human_legal_approved",
    "catalog_evidence_writer",
    "d2c",
]
EXPECTED_BLOCKED_NOW = {
    "catalog",
    "evidence_store",
    "writer",
    "api",
    "panel",
    "whatsapp",
    "webhook",
    "worker",
    "langgraph",
    "tools",
    "migration",
    "supabase_dev",
    "supabase_prod",
    "memory",
    "knowledge",
    "outbox",
    "d2c",
    "deploy",
    "agent_activation",
    "canary",
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
    assert type(metadata["successor_gate_satisfied"]) is bool
    assert metadata["successor_gate_satisfied"] is False

    delivery = document["delivery_control"]
    assert type(delivery) is dict
    assert set(delivery) == {
        "required_order",
        "blocked_now",
        "excluded_scope",
    }
    _assert_unique_string_list(
        delivery["required_order"],
        set(EXPECTED_REQUIRED_ORDER),
        ordered=EXPECTED_REQUIRED_ORDER,
    )
    _assert_unique_string_list(delivery["blocked_now"], EXPECTED_BLOCKED_NOW)
    _assert_unique_string_list(
        delivery["excluded_scope"], EXPECTED_EXCLUDED_SCOPE
    )
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


def test_d2b2b2_canonical_docs_keep_one_human_gate() -> None:
    required_references = {
        REPO_ROOT / "docs" / "ai" / "AI-BOOTSTRAP.md",
        REPO_ROOT / "docs" / "ai" / "PRD-COVERAGE.md",
        REPO_ROOT / "docs" / "WIKI-IGREJA12.md",
        REPO_ROOT / "docs" / "ops" / "POST-V1-MISSION-REGISTER.md",
        REPO_ROOT / "SPEC_PROGRESS.md",
    }
    for path in required_references:
        content = path.read_text(encoding="utf-8")
        normalized = _normalized_prose(content)
        assert "74951828f48994622a112d8e59eb978e5fb4f406" in content
        assert "d2b2b2-consent-decision-packet-contract.md" in content
        assert "pacote humano e juridico" in normalized
        assert (
            "materializar uma instancia governada do template por igreja, "
            "com quatro pacotes independentes, e obter o atestado do dono "
            "factual, a revisao de privacidade ou do encarregado, a revisao "
            "juridica quando designada e a decisao final do representante "
            "autorizado do controlador, todos vinculados ao digest exato de "
            "cada pacote"
        ) in normalized
        for blocker in ("catalogo", "writer", "supabase", "d2c"):
            assert blocker in normalized

    gate_heading_paths = required_references - {
        REPO_ROOT / "docs" / "ai" / "AI-BOOTSTRAP.md"
    }
    for path in gate_heading_paths:
        normalized = _normalized_prose(path.read_text(encoding="utf-8"))
        assert normalized.count("proximo gate unico") == 1

    bootstrap = _normalized_prose(
        (REPO_ROOT / "docs" / "ai" / "AI-BOOTSTRAP.md").read_text(
            encoding="utf-8"
        )
    )
    assert bootstrap.count("o unico gate posterior") == 1

    assert ADR_PATH.is_file()
    assert "TEMPLATE_ONLY / NOT_APPROVED" in ADR_PATH.read_text(
        encoding="utf-8"
    )
    assert not any(
        "approved" in path.name.lower()
        for path in TEMPLATE_PATH.parent.iterdir()
    )
