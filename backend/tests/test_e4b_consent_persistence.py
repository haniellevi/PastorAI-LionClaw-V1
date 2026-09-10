"""Testes puros da porta C3, sem conexão, role ou banco PostgreSQL."""

from __future__ import annotations

import datetime as dt
import inspect
import uuid
from dataclasses import replace

import pytest

from app.domain.e4b_consent import (
    E4bAction,
    E4bAuthorityResolution,
    E4bConsentIntent,
    E4bFingerprint,
    E4bIdempotencyKey,
    E4bManifestantRole,
    E4bOperatorKind,
    E4bOrigin,
    E4bRole,
)
from app.db.models import (
    E4bConsentHold,
    E4bConsentHoldEvent,
    E4bConsentOperation,
    E4bConsentReceipt,
    E4bConsentRetention,
    E4bConsentStream,
)
from app.services.e4b_consent_persistence import (
    E4bConsentStageRequest,
    E4bHoldAction,
    E4bHoldAuthorityResolution,
    E4bHoldStageRequest,
    E4bPersistenceError,
    E4bPersistenceErrorCode,
    PostgresE4bConsentStagingAdapter,
    add_24m_utc,
    e4b_advisory_lock_texts,
)


TENANT = uuid.UUID("a1000000-0000-0000-0000-000000000001")
SUBJECT = uuid.UUID("a1000000-0000-0000-0000-000000000002")
CORRELATION = uuid.UUID("a1000000-0000-0000-0000-000000000003")
OPERATION = uuid.UUID("a1000000-0000-0000-0000-000000000004")
RECEIPT = uuid.UUID("a1000000-0000-0000-0000-000000000005")


def _authority() -> E4bAuthorityResolution:
    return E4bAuthorityResolution(
        igreja_id=TENANT,
        titular_pessoa_id=SUBJECT,
        manifestante_pessoa_id=SUBJECT,
        manifestant_role=E4bManifestantRole.TITULAR,
        responsavel_pessoa_id=None,
        operador_id=SUBJECT,
        operator_kind=E4bOperatorKind.HUMAN,
        finalidade_id="cuidado_pastoral",
        origin=E4bOrigin.E4B,
        correlation_id=CORRELATION,
        contract_version="contract/v1",
        policy_version="policy/v1",
        term_version="term/v1",
        content_digest="a" * 64,
        operator_role_links=frozenset({E4bRole.TITULAR, E4bRole.MANIFESTANTE}),
    )


def _accept_request() -> E4bConsentStageRequest:
    intent = E4bConsentIntent.create(
        action=E4bAction.ACCEPT,
        idempotency_key=E4bIdempotencyKey(
            igreja_id=TENANT,
            value="e4b:consent-operation:v1:unit-test",
        ),
        authority=_authority(),
    )
    return E4bConsentStageRequest(
        operation_id=OPERATION,
        receipt_id=RECEIPT,
        intent=intent,
    )


def test_e4b_advisory_lock_texts_are_exact_v1_sequence() -> None:
    locks = e4b_advisory_lock_texts(
        igreja_id=TENANT,
        idempotency_key="e4b:consent-operation:v1:unit-test",
        titular_pessoa_id=SUBJECT,
        correlation_id=CORRELATION,
        finalidade_id="cuidado_pastoral",
    )

    assert [seed for _, seed in locks] == [2026091001, 2026091002, 2026091003, 2026091004]
    assert locks[0][0].startswith(f"e4b:consent-operation:v1:{TENANT}:")
    assert locks[1][0] == f"purpose-consent-person-v1:{TENANT}:{SUBJECT}"
    assert locks[2][0] == f"e4b:consent-correlation:v1:{TENANT}:{CORRELATION}"
    assert locks[3][0] == f"e4b:consent-stream:v1:{TENANT}:{SUBJECT}:cuidado_pastoral"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            dt.datetime(2024, 2, 29, 23, 59, 59, 123456, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 2, 28, 23, 59, 59, 123456, tzinfo=dt.timezone.utc),
        ),
        (
            dt.datetime(2025, 1, 31, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=-3))),
            dt.datetime(2027, 1, 31, 15, 0, tzinfo=dt.timezone.utc),
        ),
    ],
)
def test_e4b_add_24m_utc_is_calendar_based_and_timezone_independent(
    value: dt.datetime, expected: dt.datetime
) -> None:
    assert add_24m_utc(value) == expected


def test_e4b_stage_request_requires_closed_accept_origin_shape() -> None:
    request = _accept_request()

    assert request.intent.action is E4bAction.ACCEPT
    assert request.intent.origin_accept_operation_id is None


def test_e4b_stage_request_rejects_forged_fingerprint_and_legacy_artifact() -> None:
    request = _accept_request()
    forged = replace(request.intent, fingerprint=E4bFingerprint("b" * 64))
    legacy = replace(request.intent, legacy_artifact=object())

    for intent in (forged, legacy):
        with pytest.raises(E4bPersistenceError) as raised:
            E4bConsentStageRequest(
                operation_id=OPERATION,
                receipt_id=RECEIPT,
                intent=intent,
            )
        assert raised.value.code is E4bPersistenceErrorCode.INVALID_INPUT


def test_e4b_stage_request_rejects_cross_tenant_key_and_inexact_role_links() -> None:
    key_from_other_tenant = E4bIdempotencyKey(
        igreja_id=uuid.UUID("b1000000-0000-0000-0000-000000000001"),
        value="e4b:consent-operation:v1:other-tenant",
    )
    cross_tenant = E4bConsentIntent.create(
        action=E4bAction.ACCEPT,
        idempotency_key=key_from_other_tenant,
        authority=_authority(),
    )
    inexact_roles = E4bConsentIntent.create(
        action=E4bAction.ACCEPT,
        idempotency_key=E4bIdempotencyKey(
            igreja_id=TENANT,
            value="e4b:consent-operation:v1:inexact-roles",
        ),
        authority=replace(
            _authority(), operator_role_links=frozenset({E4bRole.TITULAR})
        ),
    )

    for intent in (cross_tenant, inexact_roles):
        with pytest.raises(E4bPersistenceError) as raised:
            E4bConsentStageRequest(OPERATION, RECEIPT, intent)
        assert raised.value.code is E4bPersistenceErrorCode.INVALID_INPUT


def test_e4b_hold_request_requires_32_byte_authority_digest() -> None:
    with pytest.raises(E4bPersistenceError) as raised:
        E4bHoldAuthorityResolution(
            igreja_id=TENANT,
            authority_app_user_id=uuid.uuid4(),
            authority_resolution_version="authority/v1",
            authority_resolution_sha256=b"short",
        )

    assert raised.value.code is E4bPersistenceErrorCode.INVALID_INPUT


def test_e4b_hold_request_requires_server_resolved_authority_for_same_tenant() -> None:
    authority = E4bHoldAuthorityResolution(
        igreja_id=TENANT,
        authority_app_user_id=uuid.uuid4(),
        authority_resolution_version="authority/v1",
        authority_resolution_sha256=b"a" * 32,
    )
    request = E4bHoldStageRequest(
        E4bHoldAction.APPLY,
        TENANT,
        OPERATION,
        uuid.uuid4(),
        uuid.uuid4(),
        authority,
        "policy/v1",
    )

    assert request.authority is authority
    with pytest.raises(E4bPersistenceError) as raised:
        E4bHoldStageRequest(
            E4bHoldAction.APPLY,
            TENANT,
            OPERATION,
            uuid.uuid4(),
            uuid.uuid4(),
            replace(authority, igreja_id=uuid.uuid4()),
            "policy/v1",
        )
    assert raised.value.code is E4bPersistenceErrorCode.INVALID_INPUT


def test_e4b_hold_projection_never_derives_eligible_without_a_future_protocol() -> None:
    source = inspect.getsource(PostgresE4bConsentStagingAdapter._reproject_retention)

    assert 'state = "RETENTION_HELD" if active_count else "RETENTION_RUNNING"' in source
    assert "RETENTION_ELIGIBLE" not in source


def test_e4b_retention_model_allows_only_running_or_held_projection_states() -> None:
    constraint = next(
        item
        for item in E4bConsentRetention.__table__.constraints
        if item.name == "e4b_consent_retentions_state_check"
    )
    sql = str(constraint.sqltext)

    assert "RETENTION_RUNNING" in sql
    assert "RETENTION_HELD" in sql
    assert "RETENTION_ELIGIBLE" not in sql


def test_e4b_hold_staging_has_a_closed_action_branch() -> None:
    source = inspect.getsource(PostgresE4bConsentStagingAdapter.stage_hold)

    assert "elif request.action is E4bHoldAction.RESOLVE:" in source
    assert "else:\n                _reject(E4bPersistenceErrorCode.INVALID_INPUT)" in source


def test_e4b_adapter_requires_external_transaction_without_opening_one() -> None:
    class InactiveSession:
        def in_transaction(self) -> bool:
            return False

        def get_transaction(self):
            return None

    with pytest.raises(E4bPersistenceError) as raised:
        PostgresE4bConsentStagingAdapter(InactiveSession()).stage_consent(_accept_request())

    assert raised.value.code is E4bPersistenceErrorCode.TRANSACTION_REQUIRED


def test_e4b_adapter_source_has_no_transaction_owner_methods() -> None:
    source = inspect.getsource(PostgresE4bConsentStagingAdapter)

    assert ".commit(" not in source
    assert ".rollback(" not in source
    assert ".begin(" not in source
    assert ".close(" not in source
    assert "create_engine(" not in source


def test_e4b_models_keep_the_six_relation_boundary_and_receipt_allowlist() -> None:
    tables = (
        E4bConsentOperation.__table__,
        E4bConsentStream.__table__,
        E4bConsentReceipt.__table__,
        E4bConsentRetention.__table__,
        E4bConsentHold.__table__,
        E4bConsentHoldEvent.__table__,
    )

    assert [table.name for table in tables] == [
        "e4b_consent_operations",
        "e4b_consent_streams",
        "e4b_consent_receipts",
        "e4b_consent_retentions",
        "e4b_consent_holds",
        "e4b_consent_hold_events",
    ]
    assert [column.name for column in E4bConsentReceipt.__table__.columns] == [
        "igreja_id",
        "receipt_id",
        "operation_id",
        "correlation_id",
        "action",
        "origin",
        "manifestant_role",
        "concession_state",
        "confirmed_at",
        "contract_version",
        "policy_version",
        "term_version",
        "content_digest",
        "fingerprint_version",
        "fingerprint",
    ]
    for table in tables:
        assert table.c.igreja_id.nullable is False
        assert all(
            foreign_key.onupdate == "RESTRICT" and foreign_key.ondelete == "RESTRICT"
            for constraint in table.foreign_key_constraints
            for foreign_key in constraint.elements
        )
