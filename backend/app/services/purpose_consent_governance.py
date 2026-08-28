"""Platform-only draft persistence for purpose-consent governance (D2B2b3A).

The service is intentionally inactive outside a future Console Master router.
It has no tenant runtime, agent, worker, WhatsApp, catalog or consent-ledger
caller.  Every query filters the explicit church.  Mutations lock the church
root before the single envelope row and use a per-purpose optimistic revision.
Transaction ownership stays with the caller; this module never commits or
rolls back.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Igreja,
    PlatformAdmin,
    PurposeConsentGovernanceEnvelope,
)
from app.domain.purpose_consent import (
    PURPOSE_CONSENT_PURPOSES,
    PurposeConsentPurpose,
)
from app.domain.purpose_consent_governance import (
    PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION,
    PurposeConsentGovernanceDraftContent,
    PurposeConsentGovernancePurposeSnapshot,
    PurposeConsentGovernanceSnapshot,
    PurposeConsentGovernanceStatus,
    PurposeConsentGovernanceValidationError,
    empty_purpose_consent_governance_content,
    purpose_consent_governance_content_from_storage,
)


class PurposeConsentGovernanceServiceError(RuntimeError):
    """Base error for persisted governance state."""


class PurposeConsentGovernanceChurchNotFoundError(
    PurposeConsentGovernanceServiceError
):
    """The explicitly named church does not exist."""


class PurposeConsentGovernanceActorNotAuthorizedError(
    PurposeConsentGovernanceServiceError
):
    """The server-derived app_user is not in the platform allowlist."""


class PurposeConsentGovernanceNotInitializedError(
    PurposeConsentGovernanceServiceError
):
    """An update was requested before the envelope was initialized."""


class PurposeConsentGovernanceRevisionConflictError(
    PurposeConsentGovernanceServiceError
):
    """The purpose draft changed after the caller loaded it."""


class PurposeConsentGovernanceDataIntegrityError(
    PurposeConsentGovernanceServiceError
):
    """Persisted state cannot be represented by the closed domain model."""


_MAX_SAFE_REVISION = 999_999_999_999_999_999


def _require_uuid(value: object, *, field: str) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        raise PurposeConsentGovernanceValidationError(
            f"{field} deve ser UUID não nulo"
        )
    return value


def _require_purpose(value: object) -> PurposeConsentPurpose:
    if type(value) is not PurposeConsentPurpose:
        raise PurposeConsentGovernanceValidationError("finalidade inválida")
    return value


def _require_expected_revision(value: object) -> int:
    if type(value) is not int or value < 1 or value > _MAX_SAFE_REVISION:
        raise PurposeConsentGovernanceValidationError(
            "expected_revision deve ser inteiro positivo válido"
        )
    return value


def _require_decision_payload(
    value: object,
) -> PurposeConsentGovernanceDraftContent:
    if type(value) is not PurposeConsentGovernanceDraftContent:
        raise PurposeConsentGovernanceValidationError(
            "decision_payload deve ser validado pelo contrato de governança"
        )
    return value


def _require_church_and_platform_actor(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    actor_app_user_id: uuid.UUID,
    lock_church: bool,
) -> None:
    church_statement = select(Igreja.id).where(Igreja.id == igreja_id)
    if lock_church:
        church_statement = church_statement.with_for_update()
    church_id = db.execute(church_statement).scalar_one_or_none()
    if church_id is None:
        raise PurposeConsentGovernanceChurchNotFoundError(
            "igreja não encontrada no plano de plataforma"
        )

    platform_admin_id = db.execute(
        select(PlatformAdmin.id).where(
            PlatformAdmin.app_user_id == actor_app_user_id
        )
    ).scalar_one_or_none()
    if platform_admin_id is None:
        raise PurposeConsentGovernanceActorNotAuthorizedError(
            "app_user autenticado não pertence à allowlist do Console Master"
        )


def _snapshot_from_envelope(
    envelope: PurposeConsentGovernanceEnvelope,
) -> PurposeConsentGovernanceSnapshot:
    try:
        if type(envelope.igreja_id) is not uuid.UUID:
            raise PurposeConsentGovernanceValidationError(
                "igreja_id persistida é inválida"
            )
        if envelope.status != PurposeConsentGovernanceStatus.DRAFT_NOT_APPROVED.value:
            raise PurposeConsentGovernanceValidationError(
                "status persistido excede a fatia draft-only"
            )
        if not isinstance(envelope.drafts, Mapping):
            raise PurposeConsentGovernanceValidationError(
                "drafts persistidos devem ser objeto"
            )
        if not isinstance(envelope.draft_revisions, Mapping):
            raise PurposeConsentGovernanceValidationError(
                "revisões persistidas devem ser objeto"
            )
        expected_purpose_keys = {purpose.value for purpose in PURPOSE_CONSENT_PURPOSES}
        if set(envelope.drafts) != expected_purpose_keys:
            raise PurposeConsentGovernanceValidationError(
                "drafts persistidos não contêm exatamente quatro finalidades"
            )
        if set(envelope.draft_revisions) != expected_purpose_keys:
            raise PurposeConsentGovernanceValidationError(
                "revisões persistidas não contêm exatamente quatro finalidades"
            )

        purpose_snapshots: list[PurposeConsentGovernancePurposeSnapshot] = []
        for purpose in PURPOSE_CONSENT_PURPOSES:
            draft_revision = envelope.draft_revisions[purpose.value]
            if (
                type(draft_revision) is not int
                or draft_revision < 1
                or draft_revision > _MAX_SAFE_REVISION
            ):
                raise PurposeConsentGovernanceValidationError(
                    "revision persistida da finalidade é inválida"
                )
            purpose_snapshots.append(
                PurposeConsentGovernancePurposeSnapshot(
                    purpose=purpose,
                    revision=draft_revision,
                    status=PurposeConsentGovernanceStatus.DRAFT_NOT_APPROVED,
                    decision_payload=purpose_consent_governance_content_from_storage(
                        envelope.drafts[purpose.value]
                    ),
                )
            )

        return PurposeConsentGovernanceSnapshot(
            igreja_id=envelope.igreja_id,
            schema_version=envelope.schema_version,
            revision=envelope.revision,
            purposes=tuple(purpose_snapshots),
            created_at=envelope.created_at,
            updated_at=envelope.updated_at,
        )
    except (PurposeConsentGovernanceValidationError, KeyError, TypeError) as exc:
        raise PurposeConsentGovernanceDataIntegrityError(
            "envelope de governança persistido viola o contrato draft-only"
        ) from exc


def _empty_drafts() -> dict[str, dict[str, str | None]]:
    return {
        purpose.value: empty_purpose_consent_governance_content().to_storage_mapping()
        for purpose in PURPOSE_CONSENT_PURPOSES
    }


def _initial_draft_revisions() -> dict[str, int]:
    return {purpose.value: 1 for purpose in PURPOSE_CONSENT_PURPOSES}


def load_purpose_consent_governance(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    actor_app_user_id: uuid.UUID,
) -> PurposeConsentGovernanceSnapshot | None:
    """Load a full envelope through the platform plane without mutating it."""

    tenant_id = _require_uuid(igreja_id, field="igreja_id")
    actor_id = _require_uuid(actor_app_user_id, field="actor_app_user_id")
    _require_church_and_platform_actor(
        db,
        igreja_id=tenant_id,
        actor_app_user_id=actor_id,
        lock_church=False,
    )
    envelope = db.execute(
        select(PurposeConsentGovernanceEnvelope).where(
            PurposeConsentGovernanceEnvelope.igreja_id == tenant_id
        )
    ).scalar_one_or_none()
    if envelope is None:
        return None
    return _snapshot_from_envelope(envelope)


def initialize_purpose_consent_governance(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    actor_app_user_id: uuid.UUID,
) -> PurposeConsentGovernanceSnapshot:
    """Atomically create or return one four-purpose envelope for a church."""

    tenant_id = _require_uuid(igreja_id, field="igreja_id")
    actor_id = _require_uuid(actor_app_user_id, field="actor_app_user_id")
    _require_church_and_platform_actor(
        db,
        igreja_id=tenant_id,
        actor_app_user_id=actor_id,
        lock_church=True,
    )
    envelope = db.execute(
        select(PurposeConsentGovernanceEnvelope)
        .where(PurposeConsentGovernanceEnvelope.igreja_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if envelope is None:
        now = dt.datetime.now(dt.timezone.utc)
        envelope = PurposeConsentGovernanceEnvelope(
            igreja_id=tenant_id,
            schema_version=PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION,
            status=PurposeConsentGovernanceStatus.DRAFT_NOT_APPROVED.value,
            drafts=_empty_drafts(),
            draft_revisions=_initial_draft_revisions(),
            revision=1,
            created_by_app_user_id=actor_id,
            updated_by_app_user_id=actor_id,
            created_at=now,
            updated_at=now,
        )
        db.add(envelope)
        db.flush()
    return _snapshot_from_envelope(envelope)


def update_purpose_consent_governance_draft(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    actor_app_user_id: uuid.UUID,
    purpose: PurposeConsentPurpose,
    expected_revision: int,
    decision_payload: PurposeConsentGovernanceDraftContent,
) -> PurposeConsentGovernanceSnapshot:
    """Replace one purpose draft under lock and optimistic revision control."""

    tenant_id = _require_uuid(igreja_id, field="igreja_id")
    actor_id = _require_uuid(actor_app_user_id, field="actor_app_user_id")
    trusted_purpose = _require_purpose(purpose)
    trusted_revision = _require_expected_revision(expected_revision)
    trusted_payload = _require_decision_payload(decision_payload)

    _require_church_and_platform_actor(
        db,
        igreja_id=tenant_id,
        actor_app_user_id=actor_id,
        lock_church=True,
    )
    envelope = db.execute(
        select(PurposeConsentGovernanceEnvelope)
        .where(PurposeConsentGovernanceEnvelope.igreja_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if envelope is None:
        raise PurposeConsentGovernanceNotInitializedError(
            "governança da igreja ainda não foi inicializada"
        )

    # Rehydrate first so corrupt JSON never gets overwritten or normalized
    # silently by a later edit.
    _snapshot_from_envelope(envelope)
    persisted_revision = envelope.draft_revisions[trusted_purpose.value]
    if persisted_revision != trusted_revision:
        raise PurposeConsentGovernanceRevisionConflictError(
            "rascunho foi alterado; recarregue antes de salvar novamente"
        )
    if (
        persisted_revision >= _MAX_SAFE_REVISION
        or envelope.revision >= _MAX_SAFE_REVISION
    ):
        raise PurposeConsentGovernanceDataIntegrityError(
            "contador de revisão atingiu o limite operacional"
        )

    drafts = dict(envelope.drafts)
    drafts[trusted_purpose.value] = trusted_payload.to_storage_mapping()
    draft_revisions = dict(envelope.draft_revisions)
    draft_revisions[trusted_purpose.value] = persisted_revision + 1

    envelope.drafts = drafts
    envelope.draft_revisions = draft_revisions
    envelope.revision += 1
    envelope.updated_by_app_user_id = actor_id
    envelope.updated_at = dt.datetime.now(dt.timezone.utc)
    db.flush()
    return _snapshot_from_envelope(envelope)


__all__ = [
    "PurposeConsentGovernanceActorNotAuthorizedError",
    "PurposeConsentGovernanceChurchNotFoundError",
    "PurposeConsentGovernanceDataIntegrityError",
    "PurposeConsentGovernanceNotInitializedError",
    "PurposeConsentGovernanceRevisionConflictError",
    "PurposeConsentGovernanceServiceError",
    "initialize_purpose_consent_governance",
    "load_purpose_consent_governance",
    "update_purpose_consent_governance_draft",
]
