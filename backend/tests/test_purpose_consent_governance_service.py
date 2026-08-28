from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable
from typing import Any

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql

from app.db.models import PurposeConsentGovernanceEnvelope
from app.domain.purpose_consent import PURPOSE_CONSENT_PURPOSES, PurposeConsentPurpose
from app.domain.purpose_consent_governance import (
    PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION,
    PurposeConsentGovernanceStatus,
    PurposeConsentGovernanceValidationError,
    empty_purpose_consent_governance_content,
    normalize_purpose_consent_governance_api_payload,
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


TENANT_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = uuid.UUID("20000000-0000-0000-0000-000000000002")
ACTOR_ID = uuid.UUID("30000000-0000-0000-0000-000000000003")
PLATFORM_ADMIN_ID = uuid.UUID("40000000-0000-0000-0000-000000000004")
NOW = dt.datetime(2026, 8, 28, 9, 40, tzinfo=dt.timezone.utc)


class _Result:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object | None:
        return self.value


class _FakeSession:
    def __init__(self, results: Iterable[object]) -> None:
        self._results = list(results)
        self.statements: list[Any] = []
        self.added: list[object] = []
        self.flush_calls = 0

    def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        if not self._results:
            raise AssertionError("query inesperada")
        return _Result(self._results.pop(0))

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        self.flush_calls += 1

    def commit(self) -> None:
        raise AssertionError("service não pode fazer commit")

    def rollback(self) -> None:
        raise AssertionError("service não pode fazer rollback")


def _empty_drafts() -> dict[str, dict[str, str | None]]:
    return {
        purpose.value: empty_purpose_consent_governance_content().to_storage_mapping()
        for purpose in PURPOSE_CONSENT_PURPOSES
    }


def _envelope(
    *,
    tenant_id: uuid.UUID = TENANT_ID,
    revision: int = 1,
) -> PurposeConsentGovernanceEnvelope:
    return PurposeConsentGovernanceEnvelope(
        id=uuid.uuid4(),
        igreja_id=tenant_id,
        schema_version=PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION,
        status=PurposeConsentGovernanceStatus.DRAFT_NOT_APPROVED.value,
        drafts=_empty_drafts(),
        draft_revisions={purpose.value: 1 for purpose in PURPOSE_CONSENT_PURPOSES},
        revision=revision,
        created_by_app_user_id=ACTOR_ID,
        updated_by_app_user_id=ACTOR_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _compiled(statement: Any) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_orm_models_one_envelope_four_closed_drafts_and_complete_fks() -> None:
    table = PurposeConsentGovernanceEnvelope.__table__
    assert tuple(column.name for column in table.columns) == (
        "id",
        "igreja_id",
        "schema_version",
        "status",
        "drafts",
        "draft_revisions",
        "revision",
        "created_by_app_user_id",
        "updated_by_app_user_id",
        "created_at",
        "updated_at",
    )

    uniques = {
        (constraint.name, tuple(column.name for column in constraint.columns))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert (
        "purpose_consent_governance_envelope_igreja_key",
        ("igreja_id",),
    ) in uniques

    foreign_keys = {
        constraint.name: (
            tuple(column.name for column in constraint.columns),
            constraint.ondelete,
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert foreign_keys == {
        "purpose_consent_governance_envelope_igreja_fkey": (
            ("igreja_id",),
            "CASCADE",
        ),
        "purpose_consent_governance_envelope_created_by_fkey": (
            ("created_by_app_user_id",),
            "SET NULL",
        ),
        "purpose_consent_governance_envelope_updated_by_fkey": (
            ("updated_by_app_user_id",),
            "SET NULL",
        ),
    }
    assert {index.name for index in table.indexes} == {
        "purpose_consent_governance_envelope_created_by_idx",
        "purpose_consent_governance_envelope_updated_by_idx",
    }
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert set(checks) == {
        "purpose_consent_governance_envelope_schema_version_check",
        "purpose_consent_governance_envelope_status_check",
        "purpose_consent_governance_envelope_revision_check",
        "purpose_consent_governance_envelope_drafts_check",
        "purpose_consent_governance_envelope_draft_revisions_check",
    }
    assert "DRAFT_NOT_APPROVED" in checks[
        "purpose_consent_governance_envelope_status_check"
    ]
    assert "controller_approved" not in " ".join(checks.values())
    for purpose in PURPOSE_CONSENT_PURPOSES:
        assert purpose.value in checks[
            "purpose_consent_governance_envelope_drafts_check"
        ]


def test_initialize_locks_church_then_envelope_and_builds_exact_four() -> None:
    db = _FakeSession([TENANT_ID, PLATFORM_ADMIN_ID, None])

    snapshot = initialize_purpose_consent_governance(
        db,  # type: ignore[arg-type]
        igreja_id=TENANT_ID,
        actor_app_user_id=ACTOR_ID,
    )

    assert snapshot.revision == 1
    assert [item.purpose for item in snapshot.purposes] == list(
        PURPOSE_CONSENT_PURPOSES
    )
    assert all(item.revision == 1 for item in snapshot.purposes)
    assert len(db.added) == 1
    created = db.added[0]
    assert isinstance(created, PurposeConsentGovernanceEnvelope)
    assert set(created.drafts) == {
        purpose.value for purpose in PURPOSE_CONSENT_PURPOSES
    }
    assert created.draft_revisions == {
        purpose.value: 1 for purpose in PURPOSE_CONSENT_PURPOSES
    }
    assert created.created_by_app_user_id == ACTOR_ID
    assert db.flush_calls == 1
    assert getattr(db.statements[0], "_for_update_arg", None) is not None
    assert getattr(db.statements[2], "_for_update_arg", None) is not None
    assert "platform_admins.app_user_id" in _compiled(db.statements[1])
    assert "purpose_consent_governance_envelope.igreja_id" in _compiled(
        db.statements[2]
    )


def test_initialize_is_idempotent_for_existing_envelope() -> None:
    existing = _envelope(revision=9)
    db = _FakeSession([TENANT_ID, PLATFORM_ADMIN_ID, existing])

    snapshot = initialize_purpose_consent_governance(
        db,  # type: ignore[arg-type]
        igreja_id=TENANT_ID,
        actor_app_user_id=ACTOR_ID,
    )

    assert snapshot.revision == 9
    assert db.added == []
    assert db.flush_calls == 0


def test_load_is_read_only_and_explicitly_tenant_filtered() -> None:
    existing = _envelope()
    db = _FakeSession([TENANT_ID, PLATFORM_ADMIN_ID, existing])

    snapshot = load_purpose_consent_governance(
        db,  # type: ignore[arg-type]
        igreja_id=TENANT_ID,
        actor_app_user_id=ACTOR_ID,
    )

    assert snapshot is not None
    assert db.added == []
    assert db.flush_calls == 0
    assert getattr(db.statements[0], "_for_update_arg", None) is None
    assert "purpose_consent_governance_envelope.igreja_id" in _compiled(
        db.statements[2]
    )


def test_update_uses_purpose_revision_and_increments_both_counters() -> None:
    existing = _envelope(revision=12)
    existing.draft_revisions[PurposeConsentPurpose.CUIDADO_PASTORAL.value] = 4
    db = _FakeSession([TENANT_ID, PLATFORM_ADMIN_ID, existing])
    payload = normalize_purpose_consent_governance_api_payload(
        {
            "operationalNeed": "Registrar fatos da operação",
            "openQuestions": "Quem é o responsável factual?",
        }
    )

    snapshot = update_purpose_consent_governance_draft(
        db,  # type: ignore[arg-type]
        igreja_id=TENANT_ID,
        actor_app_user_id=ACTOR_ID,
        purpose=PurposeConsentPurpose.CUIDADO_PASTORAL,
        expected_revision=4,
        decision_payload=payload,
    )

    assert snapshot.revision == 13
    by_purpose = {item.purpose: item for item in snapshot.purposes}
    assert by_purpose[PurposeConsentPurpose.CUIDADO_PASTORAL].revision == 5
    assert by_purpose[
        PurposeConsentPurpose.CUIDADO_PASTORAL
    ].decision_payload.operational_need == "Registrar fatos da operação"
    assert by_purpose[PurposeConsentPurpose.COMUNICADOS].revision == 1
    assert existing.updated_by_app_user_id == ACTOR_ID
    assert db.flush_calls == 1
    assert getattr(db.statements[0], "_for_update_arg", None) is not None
    assert getattr(db.statements[2], "_for_update_arg", None) is not None


def test_update_rejects_stale_purpose_revision_without_write() -> None:
    existing = _envelope(revision=3)
    existing.draft_revisions[PurposeConsentPurpose.COMUNICADOS.value] = 2
    db = _FakeSession([TENANT_ID, PLATFORM_ADMIN_ID, existing])

    with pytest.raises(PurposeConsentGovernanceRevisionConflictError):
        update_purpose_consent_governance_draft(
            db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            actor_app_user_id=ACTOR_ID,
            purpose=PurposeConsentPurpose.COMUNICADOS,
            expected_revision=1,
            decision_payload=empty_purpose_consent_governance_content(),
        )

    assert existing.revision == 3
    assert db.flush_calls == 0


def test_update_requires_initialized_envelope() -> None:
    db = _FakeSession([TENANT_ID, PLATFORM_ADMIN_ID, None])
    with pytest.raises(PurposeConsentGovernanceNotInitializedError):
        update_purpose_consent_governance_draft(
            db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            actor_app_user_id=ACTOR_ID,
            purpose=PurposeConsentPurpose.COMUNICADOS,
            expected_revision=1,
            decision_payload=empty_purpose_consent_governance_content(),
        )
    assert db.flush_calls == 0


def test_church_and_actor_are_required_by_server_identity() -> None:
    missing_church = _FakeSession([None])
    with pytest.raises(PurposeConsentGovernanceChurchNotFoundError):
        initialize_purpose_consent_governance(
            missing_church,  # type: ignore[arg-type]
            igreja_id=OTHER_TENANT_ID,
            actor_app_user_id=ACTOR_ID,
        )

    unauthorized = _FakeSession([TENANT_ID, None])
    with pytest.raises(PurposeConsentGovernanceActorNotAuthorizedError):
        initialize_purpose_consent_governance(
            unauthorized,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            actor_app_user_id=ACTOR_ID,
        )
    assert all(
        "email" not in _compiled(item).lower()
        for item in unauthorized.statements
    )


def test_untrusted_update_input_fails_before_database_io() -> None:
    db = _FakeSession([])
    with pytest.raises(PurposeConsentGovernanceValidationError):
        update_purpose_consent_governance_draft(
            db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            actor_app_user_id=ACTOR_ID,
            purpose="comunicados",  # type: ignore[arg-type]
            expected_revision=1,
            decision_payload=empty_purpose_consent_governance_content(),
        )
    assert db.statements == []


def test_corrupt_persisted_shape_fails_closed_instead_of_being_overwritten() -> None:
    existing = _envelope()
    existing.drafts[PurposeConsentPurpose.COMUNICADOS.value] = {
        "content_digest": "forbidden"
    }
    db = _FakeSession([TENANT_ID, PLATFORM_ADMIN_ID, existing])

    with pytest.raises(PurposeConsentGovernanceDataIntegrityError):
        update_purpose_consent_governance_draft(
            db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            actor_app_user_id=ACTOR_ID,
            purpose=PurposeConsentPurpose.COMUNICADOS,
            expected_revision=1,
            decision_payload=empty_purpose_consent_governance_content(),
        )

    assert db.flush_calls == 0
