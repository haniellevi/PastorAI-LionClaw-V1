"""Draft-only governance contract for purpose-specific consent (D2B2b3A).

This module deliberately models preparation, not approval.  It accepts only
the eight operational fact fields approved for the first Console Master
slice.  Legal hypotheses, notices, minor-protection decisions, approval
records, digests, catalog state and writer state do not belong to this model.
"""

from __future__ import annotations

import datetime as dt
import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.domain.purpose_consent import (
    PURPOSE_CONSENT_PURPOSES,
    PurposeConsentPurpose,
)


class PurposeConsentGovernanceValidationError(ValueError):
    """An untrusted governance draft violates the closed contract."""


class PurposeConsentGovernanceStatus(str, Enum):
    """Only lifecycle state that D2B2b3A may represent."""

    DRAFT_NOT_APPROVED = "DRAFT_NOT_APPROVED"


PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION: Final = (
    "d2b2b3a/governance-draft/v1"
)
MAX_PURPOSE_CONSENT_GOVERNANCE_FIELD_LENGTH: Final = 4_000
MAX_PURPOSE_CONSENT_GOVERNANCE_PAYLOAD_LENGTH: Final = 16_000

# Storage uses snake_case.  The public admin API uses the paired camelCase
# names so the router does not need to duplicate or loosen this allowlist.
PURPOSE_CONSENT_GOVERNANCE_FIELD_NAMES: Final[
    tuple[tuple[str, str], ...]
] = (
    ("real_processing_agents", "realProcessingAgents"),
    ("operations_and_minimum_data", "operationsAndMinimumData"),
    ("data_sensitivity_assessment", "dataSensitivityAssessment"),
    ("operational_need", "operationalNeed"),
    ("systems_and_recipients", "systemsAndRecipients"),
    ("retention_and_disposal_inventory", "retentionAndDisposalInventory"),
    ("operator_instructions", "operatorInstructions"),
    ("open_questions", "openQuestions"),
)
PURPOSE_CONSENT_GOVERNANCE_STORAGE_FIELDS: Final = tuple(
    storage_name for storage_name, _api_name in PURPOSE_CONSENT_GOVERNANCE_FIELD_NAMES
)
PURPOSE_CONSENT_GOVERNANCE_API_FIELDS: Final = tuple(
    api_name for _storage_name, api_name in PURPOSE_CONSENT_GOVERNANCE_FIELD_NAMES
)
PURPOSE_CONSENT_GOVERNANCE_LABELS: Final = {
    PurposeConsentPurpose.ATENDIMENTO_SOLICITADO: "Atendimento solicitado",
    PurposeConsentPurpose.CUIDADO_PASTORAL: "Cuidado pastoral",
    PurposeConsentPurpose.TAREFAS_OPERACIONAIS: "Tarefas operacionais",
    PurposeConsentPurpose.COMUNICADOS: "Comunicados",
}


def _normalize_optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise PurposeConsentGovernanceValidationError(
            f"{field} deve ser texto ou nulo"
        )

    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return None
    if len(normalized) > MAX_PURPOSE_CONSENT_GOVERNANCE_FIELD_LENGTH:
        raise PurposeConsentGovernanceValidationError(
            f"{field} excede o limite de "
            f"{MAX_PURPOSE_CONSENT_GOVERNANCE_FIELD_LENGTH} caracteres"
        )
    if any(
        unicodedata.category(character) == "Cc"
        and character not in {"\n", "\t"}
        for character in normalized
    ):
        raise PurposeConsentGovernanceValidationError(
            f"{field} contém caractere de controle não permitido"
        )
    return normalized


def _require_mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PurposeConsentGovernanceValidationError(
            f"{field} deve ser um objeto"
        )
    if any(type(key) is not str for key in value):
        raise PurposeConsentGovernanceValidationError(
            f"{field} contém chave inválida"
        )
    return value


def _normalize_fields(
    value: object,
    *,
    source_names: tuple[str, ...],
    require_all: bool,
) -> dict[str, str | None]:
    payload = _require_mapping(value, field="decisionPayload")
    supplied = set(payload)
    allowed = set(source_names)
    extras = supplied - allowed
    if extras:
        raise PurposeConsentGovernanceValidationError(
            "decisionPayload contém campos não permitidos: "
            + ", ".join(sorted(extras))
        )
    if require_all and supplied != allowed:
        missing = allowed - supplied
        raise PurposeConsentGovernanceValidationError(
            "decisionPayload persistido está incompleto: "
            + ", ".join(sorted(missing))
        )

    normalized = {
        name: _normalize_optional_text(payload.get(name), field=name)
        for name in source_names
    }
    total = sum(len(item) for item in normalized.values() if item is not None)
    if total > MAX_PURPOSE_CONSENT_GOVERNANCE_PAYLOAD_LENGTH:
        raise PurposeConsentGovernanceValidationError(
            "decisionPayload excede o limite total de "
            f"{MAX_PURPOSE_CONSENT_GOVERNANCE_PAYLOAD_LENGTH} caracteres"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class PurposeConsentGovernanceDraftContent:
    """Normalized closed payload for one purpose draft."""

    real_processing_agents: str | None = None
    operations_and_minimum_data: str | None = None
    data_sensitivity_assessment: str | None = None
    operational_need: str | None = None
    systems_and_recipients: str | None = None
    retention_and_disposal_inventory: str | None = None
    operator_instructions: str | None = None
    open_questions: str | None = None

    def __post_init__(self) -> None:
        normalized = _normalize_fields(
            self.to_storage_mapping(),
            source_names=PURPOSE_CONSENT_GOVERNANCE_STORAGE_FIELDS,
            require_all=True,
        )
        for field, value in normalized.items():
            object.__setattr__(self, field, value)

    def to_storage_mapping(self) -> dict[str, str | None]:
        """Return the exact JSONB shape persisted by the service."""

        return {
            name: getattr(self, name)
            for name in PURPOSE_CONSENT_GOVERNANCE_STORAGE_FIELDS
        }

    def to_api_mapping(self) -> dict[str, str | None]:
        """Return the exact camelCase decisionPayload exposed by the API."""

        return {
            api_name: getattr(self, storage_name)
            for storage_name, api_name in PURPOSE_CONSENT_GOVERNANCE_FIELD_NAMES
        }


def normalize_purpose_consent_governance_api_payload(
    value: object,
) -> PurposeConsentGovernanceDraftContent:
    """Validate an API payload with optional camelCase keys and no extras."""

    normalized = _normalize_fields(
        value,
        source_names=PURPOSE_CONSENT_GOVERNANCE_API_FIELDS,
        require_all=False,
    )
    by_storage = {
        storage_name: normalized[api_name]
        for storage_name, api_name in PURPOSE_CONSENT_GOVERNANCE_FIELD_NAMES
    }
    return PurposeConsentGovernanceDraftContent(**by_storage)


def purpose_consent_governance_content_from_storage(
    value: object,
) -> PurposeConsentGovernanceDraftContent:
    """Rehydrate only an exact normalized storage object, failing closed."""

    payload = _require_mapping(value, field="decisionPayload persistido")
    normalized = _normalize_fields(
        payload,
        source_names=PURPOSE_CONSENT_GOVERNANCE_STORAGE_FIELDS,
        require_all=True,
    )
    changed_fields = [
        field
        for field in PURPOSE_CONSENT_GOVERNANCE_STORAGE_FIELDS
        if payload[field] != normalized[field]
    ]
    if changed_fields:
        raise PurposeConsentGovernanceValidationError(
            "decisionPayload persistido não está em forma canônica: "
            + ", ".join(changed_fields)
        )
    return PurposeConsentGovernanceDraftContent(**normalized)


def empty_purpose_consent_governance_content() -> PurposeConsentGovernanceDraftContent:
    """Create the canonical empty, non-authoritative draft payload."""

    return PurposeConsentGovernanceDraftContent()


@dataclass(frozen=True, slots=True)
class PurposeConsentGovernancePurposeSnapshot:
    """One purpose draft in the immutable service snapshot."""

    purpose: PurposeConsentPurpose
    revision: int
    status: PurposeConsentGovernanceStatus
    decision_payload: PurposeConsentGovernanceDraftContent

    def __post_init__(self) -> None:
        if type(self.purpose) is not PurposeConsentPurpose:
            raise PurposeConsentGovernanceValidationError("finalidade inválida")
        if type(self.revision) is not int or self.revision < 1:
            raise PurposeConsentGovernanceValidationError(
                "revision da finalidade inválida"
            )
        if self.status is not PurposeConsentGovernanceStatus.DRAFT_NOT_APPROVED:
            raise PurposeConsentGovernanceValidationError(
                "D2B2b3A aceita apenas DRAFT_NOT_APPROVED"
            )
        if type(self.decision_payload) is not PurposeConsentGovernanceDraftContent:
            raise PurposeConsentGovernanceValidationError(
                "decisionPayload normalizado é obrigatório"
            )


@dataclass(frozen=True, slots=True)
class PurposeConsentGovernanceSnapshot:
    """Complete tenant envelope returned by initialize and update."""

    igreja_id: uuid.UUID
    schema_version: str
    revision: int
    purposes: tuple[PurposeConsentGovernancePurposeSnapshot, ...]
    created_at: dt.datetime
    updated_at: dt.datetime

    def __post_init__(self) -> None:
        if type(self.igreja_id) is not uuid.UUID or self.igreja_id.int == 0:
            raise PurposeConsentGovernanceValidationError("igreja_id inválido")
        if self.schema_version != PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION:
            raise PurposeConsentGovernanceValidationError(
                "schema_version persistida é incompatível"
            )
        if type(self.revision) is not int or self.revision < 1:
            raise PurposeConsentGovernanceValidationError("revision inválida")
        if not isinstance(self.purposes, tuple):
            raise PurposeConsentGovernanceValidationError(
                "finalidades devem ser imutáveis"
            )
        if tuple(item.purpose for item in self.purposes) != tuple(
            PURPOSE_CONSENT_PURPOSES
        ):
            raise PurposeConsentGovernanceValidationError(
                "envelope deve conter exatamente as quatro finalidades canônicas"
            )
        for timestamp, field in (
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
        ):
            if (
                not isinstance(timestamp, dt.datetime)
                or timestamp.tzinfo is None
                or timestamp.utcoffset() is None
            ):
                raise PurposeConsentGovernanceValidationError(
                    f"{field} deve conter fuso horário"
                )

    @property
    def initialized(self) -> bool:
        return True


def serialize_purpose_consent_governance_snapshot(
    snapshot: PurposeConsentGovernanceSnapshot,
) -> dict[str, object]:
    """Serialize the stable admin API response without actor identity."""

    if type(snapshot) is not PurposeConsentGovernanceSnapshot:
        raise PurposeConsentGovernanceValidationError("snapshot inválido")
    return {
        "initialized": snapshot.initialized,
        "schemaVersion": snapshot.schema_version,
        "revision": snapshot.revision,
        "purposes": [
            {
                "purpose": item.purpose.value,
                "purposeLabel": PURPOSE_CONSENT_GOVERNANCE_LABELS[item.purpose],
                "revision": item.revision,
                "purposeStatus": item.status.value,
                "decisionPayload": item.decision_payload.to_api_mapping(),
                "controllerApproved": False,
                "humanPacketComplete": False,
                "catalogReady": False,
                "writerEligible": False,
            }
            for item in snapshot.purposes
        ],
        "updatedAt": snapshot.updated_at.isoformat(),
    }


__all__ = [
    "MAX_PURPOSE_CONSENT_GOVERNANCE_FIELD_LENGTH",
    "MAX_PURPOSE_CONSENT_GOVERNANCE_PAYLOAD_LENGTH",
    "PURPOSE_CONSENT_GOVERNANCE_API_FIELDS",
    "PURPOSE_CONSENT_GOVERNANCE_FIELD_NAMES",
    "PURPOSE_CONSENT_GOVERNANCE_LABELS",
    "PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION",
    "PURPOSE_CONSENT_GOVERNANCE_STORAGE_FIELDS",
    "PurposeConsentGovernanceDraftContent",
    "PurposeConsentGovernancePurposeSnapshot",
    "PurposeConsentGovernanceSnapshot",
    "PurposeConsentGovernanceStatus",
    "PurposeConsentGovernanceValidationError",
    "empty_purpose_consent_governance_content",
    "normalize_purpose_consent_governance_api_payload",
    "purpose_consent_governance_content_from_storage",
    "serialize_purpose_consent_governance_snapshot",
]
