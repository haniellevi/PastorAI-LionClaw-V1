"""Unit tests for E4a's durable identity-only domain contract."""

from __future__ import annotations

import uuid

import pytest

from app.domain.consent_ledger_receipt import (
    ConsentLedgerReceiptAction,
    ConsentLedgerReceiptIdempotencyDisposition,
    ConsentLedgerReceiptOperation,
    ConsentLedgerReceiptValidationError,
    TenantScopedConsentLedgerReceiptIdempotencyKey,
    canonical_tenant_scoped_idempotency_identity,
    compare_rehydrated_operations,
)


TENANT = uuid.UUID("10000000-0000-4000-8000-000000000001")
OTHER_TENANT = uuid.UUID("10000000-0000-4000-8000-000000000002")
OPERATION = uuid.UUID("20000000-0000-4000-8000-000000000003")
OTHER_OPERATION = uuid.UUID("20000000-0000-4000-8000-000000000004")
KEY_VALUE = "e4.consent.receipt.20260909"


def _key(
    *,
    tenant: uuid.UUID = TENANT,
    value: str = KEY_VALUE,
) -> TenantScopedConsentLedgerReceiptIdempotencyKey:
    return TenantScopedConsentLedgerReceiptIdempotencyKey.from_persisted(
        igreja_id=tenant,
        value=value,
    )


def _operation(
    *,
    operation_id: uuid.UUID = OPERATION,
    key: TenantScopedConsentLedgerReceiptIdempotencyKey | None = None,
    action: ConsentLedgerReceiptAction = ConsentLedgerReceiptAction.REFUSE_INITIAL,
) -> ConsentLedgerReceiptOperation:
    return ConsentLedgerReceiptOperation(
        operation_id=operation_id,
        idempotency_key=key or _key(),
        action=action,
    )


def test_tenant_scoped_key_rehydrates_without_process_local_proof() -> None:
    persisted = _key()
    rehydrated = TenantScopedConsentLedgerReceiptIdempotencyKey.from_persisted(
        igreja_id=TENANT,
        value=KEY_VALUE,
    )

    assert persisted == rehydrated
    assert canonical_tenant_scoped_idempotency_identity(persisted) == (
        '{"igreja_id":"10000000-0000-4000-8000-000000000001",'
        '"value":"e4.consent.receipt.20260909"}'
    )
    assert not hasattr(rehydrated, "_mint_proof")


def test_tenant_scoped_key_rejects_invalid_persisted_values() -> None:
    with pytest.raises(ConsentLedgerReceiptValidationError):
        TenantScopedConsentLedgerReceiptIdempotencyKey.from_persisted(
            igreja_id=uuid.UUID(int=0),
            value=KEY_VALUE,
        )
    with pytest.raises(ConsentLedgerReceiptValidationError):
        TenantScopedConsentLedgerReceiptIdempotencyKey.from_persisted(
            igreja_id=TENANT,
            value="not a durable key",
        )


def test_operation_is_untrusted_identity_not_authority() -> None:
    operation = _operation()
    assert not hasattr(operation, "authority")
    assert not hasattr(operation, "authorized")
    with pytest.raises(ConsentLedgerReceiptValidationError):
        ConsentLedgerReceiptOperation(
            operation_id=uuid.UUID(int=0),
            idempotency_key=_key(),
            action=ConsentLedgerReceiptAction.REFUSE_INITIAL,
        )


def test_rehydrated_same_operation_is_an_exact_retry() -> None:
    existing = _operation()
    candidate = _operation(
        key=TenantScopedConsentLedgerReceiptIdempotencyKey.from_persisted(
            igreja_id=TENANT,
            value=KEY_VALUE,
        )
    )

    assert compare_rehydrated_operations(existing, candidate) is (
        ConsentLedgerReceiptIdempotencyDisposition.EXACT_RETRY
    )


def test_same_tenant_key_with_different_operation_id_is_a_conflict() -> None:
    existing = _operation()
    candidate = _operation(operation_id=OTHER_OPERATION)

    assert compare_rehydrated_operations(existing, candidate) is (
        ConsentLedgerReceiptIdempotencyDisposition.CONFLICT
    )


def test_same_tenant_key_with_different_action_is_a_conflict() -> None:
    existing = _operation()
    candidate = _operation(action=ConsentLedgerReceiptAction.ACCEPT)

    assert compare_rehydrated_operations(existing, candidate) is (
        ConsentLedgerReceiptIdempotencyDisposition.CONFLICT
    )


def test_comparison_never_crosses_a_tenant_scoped_key_boundary() -> None:
    existing = _operation()
    candidate = _operation(key=_key(tenant=OTHER_TENANT))

    assert canonical_tenant_scoped_idempotency_identity(
        existing.idempotency_key
    ) != canonical_tenant_scoped_idempotency_identity(candidate.idempotency_key)
    with pytest.raises(ConsentLedgerReceiptValidationError):
        compare_rehydrated_operations(existing, candidate)
