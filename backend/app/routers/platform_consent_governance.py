"""Console Master workspace for purpose-consent governance drafts (D2B2b3A).

This control-plane router prepares tenant-bound operational drafts only.  It
cannot attest facts, approve legal content, bind a catalog, write consent or
authorize any agent/runtime behavior.  The entire surface is rollout-gated and
defaults to disabled in every environment.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import PlatformAuditLog
from app.db.session import get_db
from app.deps import PlatformAdminUser, get_platform_admin
from app.domain.purpose_consent import PurposeConsentPurpose
from app.domain.purpose_consent_governance import (
    PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION,
    PurposeConsentGovernanceValidationError,
    empty_purpose_consent_governance_content,
    normalize_purpose_consent_governance_api_payload,
    serialize_purpose_consent_governance_snapshot,
)
from app.services.purpose_consent_governance import (
    PurposeConsentGovernanceActorNotAuthorizedError,
    PurposeConsentGovernanceChurchNotFoundError,
    PurposeConsentGovernanceDataIntegrityError,
    PurposeConsentGovernanceNotInitializedError,
    PurposeConsentGovernanceRevisionConflictError,
    initialize_purpose_consent_governance,
    load_purpose_consent_governance,
    update_purpose_consent_governance_draft,
)

router = APIRouter(prefix="/admin", tags=["platform-admin-consent-governance"])

_SCHEMA_VERSION = PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION
_PURPOSE_LABELS: dict[PurposeConsentPurpose, str] = {
    PurposeConsentPurpose.ATENDIMENTO_SOLICITADO: "Atendimento solicitado",
    PurposeConsentPurpose.CUIDADO_PASTORAL: "Cuidado pastoral",
    PurposeConsentPurpose.TAREFAS_OPERACIONAIS: "Tarefas operacionais",
    PurposeConsentPurpose.COMUNICADOS: "Comunicados",
}


class AdminConsentGovernanceDecisionPayload(BaseModel):
    """Strict operational facts the Master may prepare, never legal approval."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    real_processing_agents: str | None = Field(
        default=None, alias="realProcessingAgents", max_length=4000
    )
    operations_and_minimum_data: str | None = Field(
        default=None, alias="operationsAndMinimumData", max_length=4000
    )
    data_sensitivity_assessment: str | None = Field(
        default=None, alias="dataSensitivityAssessment", max_length=4000
    )
    operational_need: str | None = Field(
        default=None, alias="operationalNeed", max_length=4000
    )
    systems_and_recipients: str | None = Field(
        default=None, alias="systemsAndRecipients", max_length=4000
    )
    retention_and_disposal_inventory: str | None = Field(
        default=None, alias="retentionAndDisposalInventory", max_length=4000
    )
    operator_instructions: str | None = Field(
        default=None, alias="operatorInstructions", max_length=4000
    )
    open_questions: str | None = Field(
        default=None, alias="openQuestions", max_length=4000
    )


class AdminConsentGovernanceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    expected_revision: int = Field(alias="expectedRevision", ge=1, strict=True)
    decision_payload: AdminConsentGovernanceDecisionPayload = Field(
        alias="decisionPayload"
    )


class AdminConsentGovernancePurposeOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    purpose: PurposeConsentPurpose
    purpose_label: str = Field(alias="purposeLabel")
    revision: int = Field(ge=1)
    purpose_status: Literal["DRAFT_NOT_APPROVED"] = Field(alias="purposeStatus")
    decision_payload: dict[str, str | None] = Field(alias="decisionPayload")
    controller_approved: Literal[False] = Field(alias="controllerApproved")
    human_packet_complete: Literal[False] = Field(alias="humanPacketComplete")
    catalog_ready: Literal[False] = Field(alias="catalogReady")
    writer_eligible: Literal[False] = Field(alias="writerEligible")


class AdminConsentGovernanceStateOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool
    initialized: bool
    schema_version: str = Field(alias="schemaVersion")
    revision: int = Field(ge=0)
    purposes: list[AdminConsentGovernancePurposeOut]


def _disabled_state() -> dict[str, object]:
    return {
        "enabled": False,
        "initialized": False,
        "schemaVersion": _SCHEMA_VERSION,
        "revision": 0,
        "purposes": [],
    }


def _uninitialized_state() -> dict[str, object]:
    empty_payload = empty_purpose_consent_governance_content().to_api_mapping()
    purposes = [
        {
            "purpose": purpose.value,
            "purposeLabel": _PURPOSE_LABELS[purpose],
            "revision": 1,
            "purposeStatus": "DRAFT_NOT_APPROVED",
            "decisionPayload": dict(empty_payload),
            "controllerApproved": False,
            "humanPacketComplete": False,
            "catalogReady": False,
            "writerEligible": False,
        }
        for purpose in PurposeConsentPurpose
    ]
    return {
        "enabled": True,
        "initialized": False,
        "schemaVersion": _SCHEMA_VERSION,
        "revision": 0,
        "purposes": purposes,
    }


def _enabled_state(snapshot: object) -> dict[str, object]:
    serialized = serialize_purpose_consent_governance_snapshot(snapshot)
    return {"enabled": True, **serialized}


def _require_drafts_enabled() -> None:
    if not get_settings().purpose_consent_governance_drafts_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rascunhos de governança ainda não habilitados",
        )


def _uuid_or_404(raw: str) -> uuid.UUID:
    try:
        value = uuid.UUID(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Igreja não encontrada",
        ) from exc
    if value.int == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Igreja não encontrada",
        )
    return value


def _actor_uuid(admin: PlatformAdminUser) -> uuid.UUID:
    try:
        actor_id = uuid.UUID(admin.app_user_id)
    except (TypeError, ValueError) as exc:  # authenticated DB identity is corrupt
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito à administração da plataforma",
        ) from exc
    if actor_id.int == 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito à administração da plataforma",
        )
    return actor_id


def _audit_metadata_only(
    db: Session,
    *,
    admin: PlatformAdminUser,
    action: str,
    igreja_id: uuid.UUID,
    detail: dict[str, object],
) -> None:
    """Audit coordination metadata without draft text, signature or contact."""

    db.add(
        PlatformAuditLog(
            actor_id=_actor_uuid(admin),
            # O UUID autenticado identifica o operador sem copiar contato
            # pessoal para este log de coordenação draft-only.
            actor_email=None,
            acao=action,
            alvo_tipo="igreja_consent_governance",
            alvo_id=igreja_id,
            alvo_nome=None,
            detalhe=detail,
        )
    )


def _translate_service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PurposeConsentGovernanceChurchNotFoundError):
        return HTTPException(status_code=404, detail="Igreja não encontrada")
    if isinstance(exc, PurposeConsentGovernanceActorNotAuthorizedError):
        return HTTPException(
            status_code=403,
            detail="Acesso restrito à administração da plataforma",
        )
    if isinstance(exc, PurposeConsentGovernanceNotInitializedError):
        return HTTPException(
            status_code=409,
            detail="Inicialize os quatro rascunhos antes de editar",
        )
    if isinstance(exc, PurposeConsentGovernanceRevisionConflictError):
        return HTTPException(
            status_code=409,
            detail="O rascunho foi alterado em outra sessão. Recarregue e tente novamente.",
        )
    if isinstance(exc, PurposeConsentGovernanceValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, PurposeConsentGovernanceDataIntegrityError):
        return HTTPException(
            status_code=500,
            detail="Estado de governança inconsistente",
        )
    return HTTPException(status_code=500, detail="Falha ao processar a governança")


@router.get(
    "/igrejas/{igreja_id}/consent-governance",
    response_model=AdminConsentGovernanceStateOut,
)
def get_consent_governance(
    igreja_id: str,
    db: Session = Depends(get_db),
    admin: PlatformAdminUser = Depends(get_platform_admin),
) -> dict[str, object]:
    """Read the Master draft workspace without opening any legal/runtime gate."""

    if not get_settings().purpose_consent_governance_drafts_enabled:
        return _disabled_state()
    tenant_id = _uuid_or_404(igreja_id)
    try:
        snapshot = load_purpose_consent_governance(
            db,
            igreja_id=tenant_id,
            actor_app_user_id=_actor_uuid(admin),
        )
    except Exception as exc:
        raise _translate_service_error(exc) from exc
    if snapshot is None:
        return _uninitialized_state()
    return _enabled_state(snapshot)


@router.post(
    "/igrejas/{igreja_id}/consent-governance/initialize",
    response_model=AdminConsentGovernanceStateOut,
    status_code=status.HTTP_201_CREATED,
)
def initialize_consent_governance(
    igreja_id: str,
    db: Session = Depends(get_db),
    admin: PlatformAdminUser = Depends(get_platform_admin),
) -> dict[str, object]:
    """Create exactly four empty drafts; no legal content or approval is added."""

    _require_drafts_enabled()
    tenant_id = _uuid_or_404(igreja_id)
    try:
        snapshot = initialize_purpose_consent_governance(
            db,
            igreja_id=tenant_id,
            actor_app_user_id=_actor_uuid(admin),
        )
        _audit_metadata_only(
            db,
            admin=admin,
            action="consent_governance_drafts_initialize",
            igreja_id=tenant_id,
            detail={"revision": snapshot.revision, "purposeCount": 4},
        )
        db.commit()
    except Exception as exc:
        raise _translate_service_error(exc) from exc
    return _enabled_state(snapshot)


@router.put(
    "/igrejas/{igreja_id}/consent-governance/purposes/{purpose}",
    response_model=AdminConsentGovernanceStateOut,
)
def update_consent_governance_purpose(
    igreja_id: str,
    purpose: PurposeConsentPurpose,
    payload: AdminConsentGovernanceUpdateRequest,
    db: Session = Depends(get_db),
    admin: PlatformAdminUser = Depends(get_platform_admin),
) -> dict[str, object]:
    """Replace one operational draft under optimistic concurrency control."""

    _require_drafts_enabled()
    tenant_id = _uuid_or_404(igreja_id)
    raw_payload = payload.decision_payload.model_dump(by_alias=True)
    changed_sections = sorted(
        type(payload.decision_payload).model_fields[field].alias or field
        for field in payload.decision_payload.model_fields_set
    )
    try:
        content = normalize_purpose_consent_governance_api_payload(raw_payload)
        snapshot = update_purpose_consent_governance_draft(
            db,
            igreja_id=tenant_id,
            actor_app_user_id=_actor_uuid(admin),
            purpose=purpose,
            expected_revision=payload.expected_revision,
            decision_payload=content,
        )
        updated = next(item for item in snapshot.purposes if item.purpose is purpose)
        _audit_metadata_only(
            db,
            admin=admin,
            action="consent_governance_draft_update",
            igreja_id=tenant_id,
            detail={
                "purpose": purpose.value,
                "revision": updated.revision,
                "changedSections": changed_sections,
            },
        )
        db.commit()
    except Exception as exc:
        raise _translate_service_error(exc) from exc
    return _enabled_state(snapshot)
