from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.domain.purpose_consent import (
    PURPOSE_CONSENT_PURPOSES,
    PurposeConsentPurpose,
)
from app.domain.purpose_consent_governance import (
    PURPOSE_CONSENT_GOVERNANCE_API_FIELDS,
    PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION,
    PURPOSE_CONSENT_GOVERNANCE_STORAGE_FIELDS,
    PurposeConsentGovernancePurposeSnapshot,
    PurposeConsentGovernanceSnapshot,
    PurposeConsentGovernanceStatus,
    PurposeConsentGovernanceValidationError,
    empty_purpose_consent_governance_content,
    normalize_purpose_consent_governance_api_payload,
    purpose_consent_governance_content_from_storage,
    serialize_purpose_consent_governance_snapshot,
)


TENANT_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
NOW = dt.datetime(2026, 8, 28, 9, 30, tzinfo=dt.timezone.utc)


def test_api_payload_is_closed_normalized_and_stored_with_exact_keys() -> None:
    payload = normalize_purpose_consent_governance_api_payload(
        {
            "realProcessingAgents": "  Igreja controladora\r\nOperador SaaS  ",
            "operationalNeed": "   ",
        }
    )

    assert payload.real_processing_agents == "Igreja controladora\nOperador SaaS"
    assert payload.operational_need is None
    assert tuple(payload.to_storage_mapping()) == (
        PURPOSE_CONSENT_GOVERNANCE_STORAGE_FIELDS
    )
    assert tuple(payload.to_api_mapping()) == PURPOSE_CONSENT_GOVERNANCE_API_FIELDS
    assert payload.to_api_mapping()["operationsAndMinimumData"] is None


@pytest.mark.parametrize(
    "payload",
    (
        {"legalHypothesis": "não pertence ao draft operacional"},
        {"controllerApproved": False},
        {"operationalNeed": 42},
        {"operationalNeed": True},
        {"operationalNeed": "ok\u0000não"},
        [],
    ),
)
def test_api_payload_rejects_extras_wrong_types_and_controls(payload: object) -> None:
    with pytest.raises(PurposeConsentGovernanceValidationError):
        normalize_purpose_consent_governance_api_payload(payload)


def test_field_and_total_limits_are_enforced_after_trim() -> None:
    with pytest.raises(PurposeConsentGovernanceValidationError, match="4000"):
        normalize_purpose_consent_governance_api_payload(
            {"operationalNeed": "x" * 4001}
        )

    with pytest.raises(PurposeConsentGovernanceValidationError, match="16000"):
        normalize_purpose_consent_governance_api_payload(
            {
                "realProcessingAgents": "a" * 4000,
                "operationsAndMinimumData": "b" * 4000,
                "dataSensitivityAssessment": "c" * 4000,
                "operationalNeed": "d" * 4000,
                "systemsAndRecipients": "e",
            }
        )


def test_storage_rehydration_requires_all_and_only_canonical_fields() -> None:
    canonical = empty_purpose_consent_governance_content().to_storage_mapping()
    assert purpose_consent_governance_content_from_storage(canonical) == (
        empty_purpose_consent_governance_content()
    )

    missing = dict(canonical)
    missing.pop("open_questions")
    with pytest.raises(PurposeConsentGovernanceValidationError, match="incompleto"):
        purpose_consent_governance_content_from_storage(missing)

    extra = dict(canonical, content_digest=None)
    with pytest.raises(
        PurposeConsentGovernanceValidationError,
        match="não permitidos",
    ):
        purpose_consent_governance_content_from_storage(extra)


@pytest.mark.parametrize(
    "persisted_value",
    (
        "",
        "   ",
        " conteúdo",
        "conteúdo ",
        "linha 1\r\nlinha 2",
        "linha 1\rlinha 2",
    ),
)
def test_storage_rehydration_never_normalizes_persisted_text_silently(
    persisted_value: str,
) -> None:
    persisted = empty_purpose_consent_governance_content().to_storage_mapping()
    persisted["operational_need"] = persisted_value

    with pytest.raises(PurposeConsentGovernanceValidationError):
        purpose_consent_governance_content_from_storage(persisted)


def test_storage_rehydration_accepts_canonical_lf_and_tab_inside_text() -> None:
    persisted = empty_purpose_consent_governance_content().to_storage_mapping()
    persisted["operational_need"] = "linha 1\n\tdetalhe"

    content = purpose_consent_governance_content_from_storage(persisted)

    assert content.operational_need == "linha 1\n\tdetalhe"


def test_snapshot_serializer_exposes_four_drafts_and_only_false_derivations() -> None:
    empty = empty_purpose_consent_governance_content()
    snapshot = PurposeConsentGovernanceSnapshot(
        igreja_id=TENANT_ID,
        schema_version=PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION,
        revision=7,
        purposes=tuple(
            PurposeConsentGovernancePurposeSnapshot(
                purpose=purpose,
                revision=index,
                status=PurposeConsentGovernanceStatus.DRAFT_NOT_APPROVED,
                decision_payload=empty,
            )
            for index, purpose in enumerate(PURPOSE_CONSENT_PURPOSES, start=2)
        ),
        created_at=NOW,
        updated_at=NOW,
    )

    serialized = serialize_purpose_consent_governance_snapshot(snapshot)

    assert serialized["initialized"] is True
    assert serialized["schemaVersion"] == PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION
    assert serialized["revision"] == 7
    assert "enabled" not in serialized
    assert [item["purpose"] for item in serialized["purposes"]] == [
        purpose.value for purpose in PURPOSE_CONSENT_PURPOSES
    ]
    assert [item["revision"] for item in serialized["purposes"]] == [2, 3, 4, 5]
    assert [item["purposeLabel"] for item in serialized["purposes"]] == [
        "Atendimento solicitado",
        "Cuidado pastoral",
        "Tarefas operacionais",
        "Comunicados",
    ]
    for item in serialized["purposes"]:
        assert item["purposeStatus"] == "DRAFT_NOT_APPROVED"
        assert item["controllerApproved"] is False
        assert item["humanPacketComplete"] is False
        assert item["catalogReady"] is False
        assert item["writerEligible"] is False
        assert tuple(item["decisionPayload"]) == PURPOSE_CONSENT_GOVERNANCE_API_FIELDS
        assert all(value is None for value in item["decisionPayload"].values())


def test_snapshot_rejects_missing_reordered_or_non_draft_purpose() -> None:
    empty = empty_purpose_consent_governance_content()
    incomplete = tuple(
        PurposeConsentGovernancePurposeSnapshot(
            purpose=purpose,
            revision=1,
            status=PurposeConsentGovernanceStatus.DRAFT_NOT_APPROVED,
            decision_payload=empty,
        )
        for purpose in PURPOSE_CONSENT_PURPOSES[:-1]
    )
    with pytest.raises(PurposeConsentGovernanceValidationError, match="quatro"):
        PurposeConsentGovernanceSnapshot(
            igreja_id=TENANT_ID,
            schema_version=PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION,
            revision=1,
            purposes=incomplete,
            created_at=NOW,
            updated_at=NOW,
        )

    with pytest.raises(PurposeConsentGovernanceValidationError):
        PurposeConsentGovernancePurposeSnapshot(
            purpose=PurposeConsentPurpose.COMUNICADOS,
            revision=0,
            status=PurposeConsentGovernanceStatus.DRAFT_NOT_APPROVED,
            decision_payload=empty,
        )
