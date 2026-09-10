"""Oráculos C2 para o boundary E4b, usando somente dados sintéticos em memória."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from dataclasses import replace

import pytest

from app.domain.e4b_consent import (
    E4B_IDEMPOTENCY_KEY_PREFIX,
    E4B_RECEIPT_ALLOWLIST,
    E4bAction,
    E4bAuthorityResolution,
    E4bClassification,
    E4bConcession,
    E4bConcessionState,
    E4bConsentIntent,
    E4bDenialReason,
    E4bFingerprint,
    E4bIdempotencyKey,
    E4bManifestantRole,
    E4bOperatorKind,
    E4bOrigin,
    E4bRole,
    build_confirmed_operation,
    classify_e4b_intent,
)
from app.services.e4b_consent_boundary import (
    E4B_FUTURE_LOGICAL_ORDER,
    E4bBoundaryFailure,
    E4bBoundaryFailureCode,
    E4bBoundaryOperation,
    E4bBoundaryValidationError,
    E4bCorrelationSelector,
    E4bHistoricalOperationIdentity,
    E4bOperationSelector,
    E4bReconciliationDecision,
    E4bReconciliationObservation,
    E4bReconciliationOutcome,
    E4bReconciliationReadPort,
    E4bReconciliationSnapshot,
    E4bReplayDecision,
    E4bReplayObservation,
    E4bReplayOutcome,
    E4bReplayReadPort,
    E4bReplaySnapshot,
    E4bServerResolvedReadContext,
    E4bServerResolvedReplayContext,
    E4bSnapshotPresence,
    E4bSnapshotProvenance,
    reconcile,
    replay_intent,
)


UTC = dt.timezone.utc
TENANT_A = uuid.UUID("10000000-0000-4000-8000-000000000001")
TENANT_B = uuid.UUID("10000000-0000-4000-8000-000000000002")
SUBJECT_A = uuid.UUID("20000000-0000-4000-8000-000000000001")
SUBJECT_B = uuid.UUID("20000000-0000-4000-8000-000000000002")
OPERATOR_A = uuid.UUID("30000000-0000-4000-8000-000000000001")
CORRELATION_A = uuid.UUID("40000000-0000-4000-8000-000000000001")
CORRELATION_B = uuid.UUID("40000000-0000-4000-8000-000000000002")
OPERATION_A = uuid.UUID("50000000-0000-4000-8000-000000000001")
RECEIPT_A = uuid.UUID("60000000-0000-4000-8000-000000000001")
OPERATION_WITHDRAW = uuid.UUID("50000000-0000-4000-8000-000000000002")
RECEIPT_WITHDRAW = uuid.UUID("60000000-0000-4000-8000-000000000002")
CONFIRMED_AT = dt.datetime(2026, 1, 31, 12, 0, tzinfo=UTC)
CONTENT_DIGEST = hashlib.sha256(b"e4b-c2-synthetic-content").hexdigest()


def _key(number: int = 1, *, tenant: uuid.UUID = TENANT_A) -> E4bIdempotencyKey:
    return E4bIdempotencyKey(
        igreja_id=tenant,
        value=f"{E4B_IDEMPOTENCY_KEY_PREFIX}boundary-{number}",
    )


def _authority(
    *,
    tenant: uuid.UUID = TENANT_A,
    subject: uuid.UUID = SUBJECT_A,
    correlation: uuid.UUID = CORRELATION_A,
    term: str = "term-v1",
    server_resolved: bool = True,
) -> E4bAuthorityResolution:
    return E4bAuthorityResolution(
        igreja_id=tenant,
        titular_pessoa_id=subject,
        manifestante_pessoa_id=subject,
        manifestant_role=E4bManifestantRole.TITULAR,
        responsavel_pessoa_id=None,
        operador_id=OPERATOR_A,
        operator_kind=E4bOperatorKind.HUMAN,
        finalidade_id="tarefas_operacionais",
        origin=E4bOrigin.E4B,
        correlation_id=correlation,
        contract_version="contract-v1",
        policy_version="policy-v1",
        term_version=term,
        content_digest=CONTENT_DIGEST,
        server_resolved=server_resolved,
        operator_role_links=frozenset(),
    )


def _intent(
    *,
    action: E4bAction = E4bAction.ACCEPT,
    key: E4bIdempotencyKey | None = None,
    authority: E4bAuthorityResolution | None = None,
    origin_accept_operation_id: uuid.UUID | None = None,
    legacy_artifact: object | None = None,
) -> E4bConsentIntent:
    return E4bConsentIntent.create(
        action=action,
        idempotency_key=key or _key(),
        authority=authority or _authority(),
        origin_accept_operation_id=origin_accept_operation_id,
        legacy_artifact=legacy_artifact,
    )


def _active_concession(
    *,
    tenant: uuid.UUID = TENANT_A,
    subject: uuid.UUID = SUBJECT_A,
    purpose: str = "tarefas_operacionais",
    accept_operation_id: uuid.UUID = OPERATION_A,
) -> E4bConcession:
    return E4bConcession(
        igreja_id=tenant,
        titular_pessoa_id=subject,
        finalidade_id=purpose,
        state=E4bConcessionState.ACTIVE,
        accept_operation_id=accept_operation_id,
    )


def _confirmed_accept(
    *,
    intent: E4bConsentIntent | None = None,
    operation_id: uuid.UUID = OPERATION_A,
    receipt_id: uuid.UUID = RECEIPT_A,
):
    candidate = intent or _intent()
    classification = classify_e4b_intent(candidate)
    assert classification.classification is E4bClassification.ELIGIBLE
    return build_confirmed_operation(
        candidate,
        classification=classification,
        operation_id=operation_id,
        receipt_id=receipt_id,
        confirmed_at=CONFIRMED_AT,
    )


def _replay_context(intent: E4bConsentIntent) -> E4bServerResolvedReplayContext:
    return E4bServerResolvedReplayContext(
        igreja_id=intent.authority.igreja_id,
        authority=intent.authority,
    )


def _read_context(
    *, authority: E4bAuthorityResolution | None = None
) -> E4bServerResolvedReadContext:
    resolved = authority or _authority()
    return E4bServerResolvedReadContext(
        igreja_id=resolved.igreja_id,
        authority=resolved,
    )


def _provenance(*, tenant: uuid.UUID = TENANT_A) -> E4bSnapshotProvenance:
    return E4bSnapshotProvenance(igreja_id=tenant, origin=E4bOrigin.E4B)


def _historical_identity(
    intent: E4bConsentIntent,
    operation,
    *,
    authority: E4bAuthorityResolution | None = None,
) -> E4bHistoricalOperationIdentity:
    return E4bHistoricalOperationIdentity(
        igreja_id=operation.igreja_id,
        operation_id=operation.operation_id,
        receipt_id=operation.receipt_id,
        idempotency_key=operation.idempotency_key,
        fingerprint=operation.fingerprint,
        authority=authority or intent.authority,
        action=operation.action,
        origin_accept_operation_id=operation.origin_accept_operation_id,
    )


def _replay_snapshot(
    intent: E4bConsentIntent,
    *,
    existing_operation=None,
    existing_operation_identity: E4bHistoricalOperationIdentity | None = None,
    concession: E4bConcession | None = None,
    origin_accept_operation=None,
    origin_accept_operation_identity: E4bHistoricalOperationIdentity | None = None,
    observation: E4bReplayObservation = E4bReplayObservation.COMPLETE,
) -> E4bReplaySnapshot:
    if observation is E4bReplayObservation.INCOMPLETE_OR_INCONSISTENT:
        operation_presence = E4bSnapshotPresence.NOT_APPLICABLE
        concession_presence = E4bSnapshotPresence.NOT_APPLICABLE
        origin_presence = E4bSnapshotPresence.NOT_APPLICABLE
        existing_operation = None
        concession = None
        origin_accept_operation = None
    else:
        operation_presence = (
            E4bSnapshotPresence.PRESENT
            if existing_operation is not None
            else E4bSnapshotPresence.ABSENT
        )
        if existing_operation is not None:
            if existing_operation_identity is None:
                existing_operation_identity = _historical_identity(
                    intent, existing_operation
                )
            concession_presence = E4bSnapshotPresence.NOT_APPLICABLE
            origin_presence = E4bSnapshotPresence.NOT_APPLICABLE
            concession = None
            origin_accept_operation = None
        else:
            concession_presence = (
                E4bSnapshotPresence.PRESENT
                if concession is not None
                else E4bSnapshotPresence.ABSENT
            )
            if intent.action is E4bAction.ACCEPT:
                origin_presence = E4bSnapshotPresence.NOT_APPLICABLE
                origin_accept_operation = None
            else:
                origin_presence = (
                    E4bSnapshotPresence.PRESENT
                    if origin_accept_operation is not None
                    else E4bSnapshotPresence.ABSENT
                )
                if (
                    origin_accept_operation is not None
                    and origin_accept_operation_identity is None
                ):
                    origin_accept_operation_identity = _historical_identity(
                        intent, origin_accept_operation
                    )
    return E4bReplaySnapshot(
        igreja_id=intent.authority.igreja_id,
        idempotency_key=intent.idempotency_key,
        fingerprint=intent.fingerprint,
        correlation_id=intent.authority.correlation_id,
        action=intent.action,
        origin=intent.authority.origin,
        origin_accept_operation_id=intent.origin_accept_operation_id,
        provenance=_provenance(tenant=intent.authority.igreja_id),
        observation=observation,
        operation_presence=operation_presence,
        existing_operation=existing_operation,
        concession_presence=concession_presence,
        concession=concession,
        origin_presence=origin_presence,
        origin_accept_operation=origin_accept_operation,
        existing_operation_identity=existing_operation_identity,
        origin_accept_operation_identity=origin_accept_operation_identity,
    )


def _reconciliation_snapshot(
    selector: E4bOperationSelector | E4bCorrelationSelector,
    *,
    observation: E4bReconciliationObservation,
    operation=None,
    historical_identity: E4bHistoricalOperationIdentity | None = None,
) -> E4bReconciliationSnapshot:
    return E4bReconciliationSnapshot(
        igreja_id=selector.igreja_id,
        selector=selector,
        provenance=_provenance(tenant=selector.igreja_id),
        observation=observation,
        operation=operation,
        historical_identity=historical_identity,
    )


def _corrupt_snapshot(snapshot, **updates):
    """Simula uma porta que viola o contrato depois da construção tipada."""

    for field_name, value in updates.items():
        object.__setattr__(snapshot, field_name, value)
    return snapshot


def _withdrawal_inputs():
    accept_intent = _intent()
    accept_operation = _confirmed_accept(intent=accept_intent)
    withdrawal_intent = _intent(
        action=E4bAction.WITHDRAW,
        key=_key(2),
        origin_accept_operation_id=accept_operation.operation_id,
    )
    active_concession = _active_concession(
        accept_operation_id=accept_operation.operation_id,
    )
    origin_identity = _historical_identity(accept_intent, accept_operation)
    return (
        accept_intent,
        accept_operation,
        withdrawal_intent,
        active_concession,
        origin_identity,
    )


class _ReplayPort(E4bReplayReadPort):
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0
        self.requests = []

    def read_replay_snapshot(self, request):
        self.calls += 1
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _ReconciliationPort(E4bReconciliationReadPort):
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0
        self.requests = []

    def read_reconciliation_snapshot(self, request):
        self.calls += 1
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _assert_failure(
    result: object,
    *,
    operation: E4bBoundaryOperation,
    code: E4bBoundaryFailureCode,
) -> None:
    assert type(result) is E4bBoundaryFailure
    assert result.operation is operation
    assert result.code is code
    assert not hasattr(result, "outcome")
    assert not hasattr(result, "receipt")


def test_c2_q04_proven_absent_k_maps_eligible_to_new_with_one_observation() -> None:
    intent = _intent()
    port = _ReplayPort(_replay_snapshot(intent))

    result = replay_intent(intent=intent, context=_replay_context(intent), port=port)

    assert type(result) is E4bReplayDecision
    assert result.outcome is E4bReplayOutcome.NEW
    assert result.receipt is None
    assert result.denial_reason is None
    assert port.calls == 1
    request = port.requests[0]
    assert request.igreja_id == TENANT_A
    assert request.idempotency_key == intent.idempotency_key
    assert request.fingerprint == intent.fingerprint
    assert request.correlation_id == CORRELATION_A


def test_c2_q05_exact_replay_exposes_only_allowlisted_receipt() -> None:
    intent = _intent()
    operation = _confirmed_accept(intent=intent)
    port = _ReplayPort(_replay_snapshot(intent, existing_operation=operation))

    result = replay_intent(intent=intent, context=_replay_context(intent), port=port)

    assert type(result) is E4bReplayDecision
    assert result.outcome is E4bReplayOutcome.EXACT_REPLAY
    assert result.denial_reason is None
    assert result.receipt is not None
    assert set(result.receipt.to_mapping()) == E4B_RECEIPT_ALLOWLIST
    assert not hasattr(result, "existing_operation")
    assert not hasattr(result.receipt, "titular_pessoa_id")
    assert str(SUBJECT_A) not in result.receipt.to_mapping().values()
    assert str(OPERATOR_A) not in result.receipt.to_mapping().values()
    assert port.calls == 1


def test_c2_regression_copied_fingerprint_cannot_hide_changed_closed_correlation() -> None:
    intent = _intent()
    operation = _confirmed_accept(intent=intent)
    changed_operation = replace(operation, correlation_id=CORRELATION_B)
    port = _ReplayPort(
        _replay_snapshot(intent, existing_operation=changed_operation)
    )

    result = replay_intent(intent=intent, context=_replay_context(intent), port=port)

    _assert_failure(
        result,
        operation=E4bBoundaryOperation.REPLAY,
        code=E4bBoundaryFailureCode.CHAIN_INCOMPLETE,
    )
    assert port.calls == 1


def test_c2_regression_historical_proof_requires_operator_kind_and_role_links() -> None:
    intent = _intent()
    operation = _confirmed_accept(intent=intent)
    altered_authorities = (
        replace(intent.authority, operator_kind=E4bOperatorKind.TECHNICAL),
        replace(
            intent.authority,
            operator_role_links=frozenset({E4bRole.TITULAR}),
        ),
    )

    for altered_authority in altered_authorities:
        port = _ReplayPort(
            _replay_snapshot(
                intent,
                existing_operation=operation,
                existing_operation_identity=_historical_identity(
                    intent,
                    operation,
                    authority=altered_authority,
                ),
            )
        )
        result = replay_intent(
            intent=intent,
            context=_replay_context(intent),
            port=port,
        )

        _assert_failure(
            result,
            operation=E4bBoundaryOperation.REPLAY,
            code=E4bBoundaryFailureCode.CHAIN_INCOMPLETE,
        )
        assert port.calls == 1


def test_c2_regression_missing_or_mismatched_receipt_proof_fails_closed() -> None:
    intent = _intent()
    operation = _confirmed_accept(intent=intent)
    missing_proof = _corrupt_snapshot(
        _replay_snapshot(intent, existing_operation=operation),
        existing_operation_identity=None,
    )
    changed_receipt = replace(
        operation,
        receipt_id=uuid.UUID("60000000-0000-4000-8000-000000000002"),
    )
    receipt_mismatch = _replay_snapshot(
        intent,
        existing_operation=changed_receipt,
        existing_operation_identity=_historical_identity(intent, operation),
    )

    for snapshot, expected_code in (
        (missing_proof, E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED),
        (receipt_mismatch, E4bBoundaryFailureCode.CHAIN_INCOMPLETE),
    ):
        port = _ReplayPort(snapshot)
        result = replay_intent(
            intent=intent,
            context=_replay_context(intent),
            port=port,
        )

        _assert_failure(
            result,
            operation=E4bBoundaryOperation.REPLAY,
            code=expected_code,
        )
        assert port.calls == 1


def test_c2_regression_replay_rejects_identity_without_its_payload() -> None:
    intent = _intent()
    operation = _confirmed_accept(intent=intent)
    proof = _historical_identity(intent, operation)
    (
        _,
        _,
        withdrawal_intent,
        active_concession,
        origin_proof,
    ) = _withdrawal_inputs()
    absent_operation = _corrupt_snapshot(
        _replay_snapshot(intent),
        existing_operation_identity=proof,
    )
    incomplete_chain = _corrupt_snapshot(
        _replay_snapshot(
            intent,
            observation=E4bReplayObservation.INCOMPLETE_OR_INCONSISTENT,
        ),
        existing_operation_identity=proof,
        origin_accept_operation_identity=proof,
    )
    inapplicable_origin = _corrupt_snapshot(
        _replay_snapshot(intent),
        origin_accept_operation_identity=proof,
    )
    absent_origin = _corrupt_snapshot(
        _replay_snapshot(
            withdrawal_intent,
            concession=active_concession,
        ),
        origin_accept_operation_identity=origin_proof,
    )

    for replay_intent_input, snapshot in (
        (intent, absent_operation),
        (intent, incomplete_chain),
        (intent, inapplicable_origin),
        (withdrawal_intent, absent_origin),
    ):
        port = _ReplayPort(snapshot)
        result = replay_intent(
            intent=replay_intent_input,
            context=_replay_context(replay_intent_input),
            port=port,
        )

        _assert_failure(
            result,
            operation=E4bBoundaryOperation.REPLAY,
            code=E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
        )
        assert port.calls == 1


def test_c2_closed_snapshots_reject_identity_without_corresponding_payload() -> None:
    intent = _intent()
    operation = _confirmed_accept(intent=intent)
    proof = _historical_identity(intent, operation)
    (
        _,
        _,
        withdrawal_intent,
        active_concession,
        origin_proof,
    ) = _withdrawal_inputs()
    selector = E4bOperationSelector(
        igreja_id=TENANT_A,
        operation_id=operation.operation_id,
    )
    replay_cases = (
        (_replay_snapshot(intent), {"existing_operation_identity": proof}),
        (
            _replay_snapshot(
                intent,
                observation=E4bReplayObservation.INCOMPLETE_OR_INCONSISTENT,
            ),
            {"existing_operation_identity": proof},
        ),
        (_replay_snapshot(intent), {"origin_accept_operation_identity": proof}),
        (
            _replay_snapshot(withdrawal_intent, concession=active_concession),
            {"origin_accept_operation_identity": origin_proof},
        ),
    )

    for snapshot, updates in replay_cases:
        with pytest.raises(E4bBoundaryValidationError):
            replace(snapshot, **updates)

    for observation in (
        E4bReconciliationObservation.NOT_FOUND,
        E4bReconciliationObservation.UNKNOWN,
        E4bReconciliationObservation.INCOMPLETE_OR_INCONSISTENT,
    ):
        with pytest.raises(E4bBoundaryValidationError):
            replace(
                _reconciliation_snapshot(selector, observation=observation),
                historical_identity=proof,
            )


def test_c2_withdraw_active_accept_and_closed_origin_proof_maps_to_new() -> None:
    (
        _,
        accept_operation,
        withdrawal_intent,
        active_concession,
        origin_proof,
    ) = _withdrawal_inputs()
    port = _ReplayPort(
        _replay_snapshot(
            withdrawal_intent,
            concession=active_concession,
            origin_accept_operation=accept_operation,
            origin_accept_operation_identity=origin_proof,
        )
    )

    result = replay_intent(
        intent=withdrawal_intent,
        context=_replay_context(withdrawal_intent),
        port=port,
    )

    assert type(result) is E4bReplayDecision
    assert result.outcome is E4bReplayOutcome.NEW
    assert result.receipt is None
    assert result.denial_reason is None
    assert port.calls == 1


def test_c2_withdraw_missing_origin_proof_fails_internal() -> None:
    (
        _,
        accept_operation,
        withdrawal_intent,
        active_concession,
        origin_proof,
    ) = _withdrawal_inputs()
    snapshot = _corrupt_snapshot(
        _replay_snapshot(
            withdrawal_intent,
            concession=active_concession,
            origin_accept_operation=accept_operation,
            origin_accept_operation_identity=origin_proof,
        ),
        origin_accept_operation_identity=None,
    )
    port = _ReplayPort(snapshot)

    result = replay_intent(
        intent=withdrawal_intent,
        context=_replay_context(withdrawal_intent),
        port=port,
    )

    _assert_failure(
        result,
        operation=E4bBoundaryOperation.REPLAY,
        code=E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
    )
    assert port.calls == 1


def test_c2_withdraw_exact_replay_preserves_only_historical_receipt() -> None:
    (
        _,
        accept_operation,
        withdrawal_intent,
        active_concession,
        _,
    ) = _withdrawal_inputs()
    classification = classify_e4b_intent(
        withdrawal_intent,
        concession=active_concession,
        origin_accept_operation=accept_operation,
    )
    assert classification.classification is E4bClassification.ELIGIBLE
    withdrawal_operation = build_confirmed_operation(
        withdrawal_intent,
        classification=classification,
        operation_id=OPERATION_WITHDRAW,
        receipt_id=RECEIPT_WITHDRAW,
        confirmed_at=CONFIRMED_AT + dt.timedelta(minutes=1),
    )
    port = _ReplayPort(
        _replay_snapshot(
            withdrawal_intent,
            existing_operation=withdrawal_operation,
        )
    )

    result = replay_intent(
        intent=withdrawal_intent,
        context=_replay_context(withdrawal_intent),
        port=port,
    )

    assert type(result) is E4bReplayDecision
    assert result.outcome is E4bReplayOutcome.EXACT_REPLAY
    assert result.receipt is not None
    assert result.receipt.to_mapping()["action"] == E4bAction.WITHDRAW.value
    assert result.receipt.to_mapping()["concession_state"] == "WITHDRAWN"
    assert not hasattr(result, "existing_operation")
    assert port.calls == 1


def test_c2_post_observation_denials_preserve_sanitized_reason() -> None:
    (
        accept_intent,
        _,
        withdrawal_intent,
        active_concession,
        _,
    ) = _withdrawal_inputs()
    other_purpose_intent = _intent(
        authority=replace(
            accept_intent.authority,
            finalidade_id="cuidado_pastoral",
        )
    )
    other_purpose_origin = _confirmed_accept(intent=other_purpose_intent)
    withdraw_with_other_purpose_origin = _replay_snapshot(
        withdrawal_intent,
        concession=active_concession,
        origin_accept_operation=other_purpose_origin,
        origin_accept_operation_identity=_historical_identity(
            other_purpose_intent,
            other_purpose_origin,
        ),
    )
    accept_with_active_concession = _intent(key=_key(3))
    active_accept_snapshot = _replay_snapshot(
        accept_with_active_concession,
        concession=_active_concession(),
    )

    for intent, snapshot, expected_reason in (
        (
            withdrawal_intent,
            withdraw_with_other_purpose_origin,
            E4bDenialReason.ORIGIN_PURPOSE_MISMATCH,
        ),
        (
            accept_with_active_concession,
            active_accept_snapshot,
            E4bDenialReason.ACTIVE_CONCESSION,
        ),
    ):
        port = _ReplayPort(snapshot)
        result = replay_intent(
            intent=intent,
            context=_replay_context(intent),
            port=port,
        )

        assert type(result) is E4bReplayDecision
        assert result.outcome is E4bReplayOutcome.DENIED
        assert result.denial_reason is expected_reason
        assert result.receipt is None
        assert port.calls == 1


def test_c2_withdraw_foreign_origin_is_rejected_by_snapshot_constructor() -> None:
    (
        _,
        _,
        withdrawal_intent,
        active_concession,
        _,
    ) = _withdrawal_inputs()
    foreign_accept_intent = _intent(
        key=_key(3, tenant=TENANT_B),
        authority=_authority(
            tenant=TENANT_B,
            subject=SUBJECT_B,
            correlation=CORRELATION_B,
        ),
    )
    foreign_accept_operation = _confirmed_accept(intent=foreign_accept_intent)

    with pytest.raises(E4bBoundaryValidationError):
        _replay_snapshot(
            withdrawal_intent,
            concession=active_concession,
            origin_accept_operation=foreign_accept_operation,
            origin_accept_operation_identity=_historical_identity(
                foreign_accept_intent,
                foreign_accept_operation,
            ),
        )


def test_c2_q06_same_k_with_different_fingerprint_maps_to_conflict() -> None:
    original_intent = _intent()
    operation = _confirmed_accept(intent=original_intent)
    changed_intent = _intent(
        key=original_intent.idempotency_key,
        authority=_authority(term="term-v2"),
    )
    port = _ReplayPort(
        _replay_snapshot(
            changed_intent,
            existing_operation=operation,
            existing_operation_identity=_historical_identity(original_intent, operation),
        )
    )

    result = replay_intent(
        intent=changed_intent,
        context=_replay_context(changed_intent),
        port=port,
    )

    assert type(result) is E4bReplayDecision
    assert result.outcome is E4bReplayOutcome.CONFLICT
    assert result.receipt is None
    assert result.denial_reason is None
    assert port.calls == 1


def test_c2_r4_postconstruction_replay_revalidates_k_and_tenant_scope() -> None:
    intent = _intent()
    operation = _confirmed_accept(intent=intent)
    identity = _historical_identity(intent, operation)
    other_key_intent = _intent(
        key=_key(2),
        authority=_authority(term="term-v2"),
    )
    other_key_operation = _confirmed_accept(intent=other_key_intent)
    other_key_identity = _historical_identity(
        other_key_intent,
        other_key_operation,
    )
    foreign_intent = _intent(
        key=_key(3, tenant=TENANT_B),
        authority=_authority(
            tenant=TENANT_B,
            subject=SUBJECT_B,
            correlation=CORRELATION_A,
        ),
    )
    foreign_operation = _confirmed_accept(intent=foreign_intent)
    foreign_identity = _historical_identity(foreign_intent, foreign_operation)

    with pytest.raises(E4bBoundaryValidationError):
        _replay_snapshot(
            intent,
            existing_operation=other_key_operation,
            existing_operation_identity=other_key_identity,
        )

    cases = (
        (other_key_operation, other_key_identity),
        (other_key_operation, identity),
        (operation, other_key_identity),
        (foreign_operation, foreign_identity),
    )
    for corrupted_operation, corrupted_identity in cases:
        snapshot = _corrupt_snapshot(
            _replay_snapshot(intent, existing_operation=operation),
            existing_operation=corrupted_operation,
            existing_operation_identity=corrupted_identity,
        )
        port = _ReplayPort(snapshot)

        result = replay_intent(
            intent=intent,
            context=_replay_context(intent),
            port=port,
        )

        _assert_failure(
            result,
            operation=E4bBoundaryOperation.REPLAY,
            code=E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
        )
        assert port.calls == 1


def test_c2_r4_postconstruction_concession_and_origin_keep_tenant_scope() -> None:
    accept_intent = _intent(key=_key(4))
    foreign_concession_snapshot = _corrupt_snapshot(
        _replay_snapshot(accept_intent, concession=_active_concession()),
        concession=_active_concession(tenant=TENANT_B, subject=SUBJECT_B),
    )
    (
        _,
        accept_operation,
        withdrawal_intent,
        active_concession,
        origin_identity,
    ) = _withdrawal_inputs()
    foreign_origin_intent = _intent(
        key=_key(5, tenant=TENANT_B),
        authority=_authority(
            tenant=TENANT_B,
            subject=SUBJECT_B,
            correlation=CORRELATION_B,
        ),
    )
    foreign_origin = _confirmed_accept(
        intent=foreign_origin_intent,
        operation_id=accept_operation.operation_id,
    )
    foreign_origin_snapshot = _corrupt_snapshot(
        _replay_snapshot(
            withdrawal_intent,
            concession=active_concession,
            origin_accept_operation=accept_operation,
            origin_accept_operation_identity=origin_identity,
        ),
        origin_accept_operation=foreign_origin,
        origin_accept_operation_identity=_historical_identity(
            foreign_origin_intent,
            foreign_origin,
        ),
    )

    for replay_input, snapshot in (
        (accept_intent, foreign_concession_snapshot),
        (withdrawal_intent, foreign_origin_snapshot),
    ):
        port = _ReplayPort(snapshot)
        result = replay_intent(
            intent=replay_input,
            context=_replay_context(replay_input),
            port=port,
        )

        _assert_failure(
            result,
            operation=E4bBoundaryOperation.REPLAY,
            code=E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
        )
        assert port.calls == 1


def test_c2_r4_postconstruction_operation_semantics_fail_before_replay_receipt() -> None:
    for field_name, corrupted_value in (
        ("action", E4bAction.WITHDRAW),
        ("concession_state", E4bConcessionState.WITHDRAWN),
    ):
        intent = _intent()
        operation = _confirmed_accept(intent=intent)
        snapshot = _replay_snapshot(intent, existing_operation=operation)
        object.__setattr__(operation, field_name, corrupted_value)
        port = _ReplayPort(snapshot)

        result = replay_intent(
            intent=intent,
            context=_replay_context(intent),
            port=port,
        )

        _assert_failure(
            result,
            operation=E4bBoundaryOperation.REPLAY,
            code=E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
        )
        assert port.calls == 1


def test_c2_r4_postconstruction_concession_state_shape_fails_before_new() -> None:
    (
        _,
        accept_operation,
        withdrawal_intent,
        active_concession,
        origin_identity,
    ) = _withdrawal_inputs()
    withdrawn_concession = replace(
        active_concession,
        state=E4bConcessionState.WITHDRAWN,
        withdraw_operation_id=OPERATION_WITHDRAW,
    )
    snapshot = _replay_snapshot(
        withdrawal_intent,
        concession=withdrawn_concession,
        origin_accept_operation=accept_operation,
        origin_accept_operation_identity=origin_identity,
    )
    object.__setattr__(withdrawn_concession, "state", E4bConcessionState.ACTIVE)
    port = _ReplayPort(snapshot)

    result = replay_intent(
        intent=withdrawal_intent,
        context=_replay_context(withdrawal_intent),
        port=port,
    )

    _assert_failure(
        result,
        operation=E4bBoundaryOperation.REPLAY,
        code=E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
    )
    assert port.calls == 1


def test_c2_r5_nested_historical_authority_tenant_fails_before_replay_or_receipt() -> None:
    local_intent = _intent()
    operation = _confirmed_accept(intent=local_intent)
    identity = _historical_identity(local_intent, operation)
    foreign_authority = _authority(tenant=TENANT_B)
    foreign_authority_intent = _intent(authority=foreign_authority)

    with pytest.raises(E4bBoundaryValidationError):
        replace(identity, authority=foreign_authority)

    object.__setattr__(operation, "fingerprint", foreign_authority_intent.fingerprint)
    object.__setattr__(identity, "authority", foreign_authority)
    object.__setattr__(identity, "fingerprint", foreign_authority_intent.fingerprint)
    replay_snapshot = _corrupt_snapshot(
        _replay_snapshot(
            local_intent,
            existing_operation=_confirmed_accept(intent=local_intent),
        ),
        existing_operation=operation,
        existing_operation_identity=identity,
    )
    replay_port = _ReplayPort(replay_snapshot)

    replay_result = replay_intent(
        intent=local_intent,
        context=_replay_context(local_intent),
        port=replay_port,
    )

    _assert_failure(
        replay_result,
        operation=E4bBoundaryOperation.REPLAY,
        code=E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
    )
    assert replay_port.calls == 1

    selectors = (
        E4bOperationSelector(
            igreja_id=TENANT_A,
            operation_id=operation.operation_id,
        ),
        E4bCorrelationSelector(
            igreja_id=TENANT_A,
            correlation_id=operation.correlation_id,
        ),
    )
    for selector in selectors:
        reconciliation_snapshot = _corrupt_snapshot(
            _reconciliation_snapshot(
                selector,
                observation=E4bReconciliationObservation.CONFIRMED,
                operation=_confirmed_accept(intent=local_intent),
                historical_identity=_historical_identity(
                    local_intent,
                    _confirmed_accept(intent=local_intent),
                ),
            ),
            operation=operation,
            historical_identity=identity,
        )
        reconciliation_port = _ReconciliationPort(reconciliation_snapshot)

        reconciliation_result = reconcile(
            context=_read_context(),
            selector=selector,
            port=reconciliation_port,
        )

        _assert_failure(
            reconciliation_result,
            operation=E4bBoundaryOperation.RECONCILE,
            code=E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
        )
        assert reconciliation_port.calls == 1


def test_c2_q07_c0_semantic_denials_happen_before_observation() -> None:
    unresolved = _intent(authority=_authority(server_resolved=False))
    tenant_mismatch = _intent(key=_key(2, tenant=TENANT_B))
    forged_fingerprint = replace(_intent(), fingerprint=E4bFingerprint("f" * 64))
    incompatible_origin = _intent(origin_accept_operation_id=OPERATION_A)
    legacy = _intent(legacy_artifact=object())
    cases = (
        (unresolved, E4bDenialReason.AUTHORITY_UNRESOLVED),
        (tenant_mismatch, E4bDenialReason.TENANT_MISMATCH),
        (forged_fingerprint, E4bDenialReason.FINGERPRINT_INVALID),
        (incompatible_origin, E4bDenialReason.ACTION_ORIGIN_INVALID),
        (legacy, E4bDenialReason.LEGACY_ARTIFACT),
    )

    for intent, expected_reason in cases:
        port = _ReplayPort(None)
        result = replay_intent(intent=intent, context=_replay_context(intent), port=port)

        assert type(result) is E4bReplayDecision
        assert result.outcome is E4bReplayOutcome.DENIED
        assert result.denial_reason is expected_reason
        assert result.receipt is None
        assert port.calls == 0


def test_c2_q02_q08_invalid_replay_envelope_or_context_fails_before_observation() -> None:
    intent = _intent()
    port = _ReplayPort(_replay_snapshot(intent))
    mismatched_context = E4bServerResolvedReplayContext(
        igreja_id=TENANT_B,
        authority=intent.authority,
    )

    for invalid_intent, invalid_context in (
        ({"intent": "free"}, _replay_context(intent)),
        (intent, {"context": "free"}),
        (intent, mismatched_context),
    ):
        result = replay_intent(
            intent=invalid_intent,
            context=invalid_context,
            port=port,
        )
        _assert_failure(
            result,
            operation=E4bBoundaryOperation.REPLAY,
            code=E4bBoundaryFailureCode.INVALID_CONTEXT,
        )

    assert port.calls == 0


def test_c2_q13_context_artifact_or_credential_is_not_authority() -> None:
    intent = _intent()
    port = _ReplayPort(_replay_snapshot(intent))
    credential_context = replace(_replay_context(intent), presented_credential=object())
    artifact_context = replace(_replay_context(intent), legacy_artifact=object())

    for context in (credential_context, artifact_context):
        result = replay_intent(intent=intent, context=context, port=port)
        _assert_failure(
            result,
            operation=E4bBoundaryOperation.REPLAY,
            code=E4bBoundaryFailureCode.INVALID_CONTEXT,
        )

    assert port.calls == 0


def test_c2_r5_invalid_nested_authority_shape_is_invalid_context_before_read() -> None:
    replay_input = _intent()
    replay_context = _replay_context(replay_input)
    replay_port = _ReplayPort(_replay_snapshot(replay_input))
    object.__setattr__(replay_context.authority, "operator_role_links", set())

    replay_result = replay_intent(
        intent=replay_input,
        context=replay_context,
        port=replay_port,
    )

    _assert_failure(
        replay_result,
        operation=E4bBoundaryOperation.REPLAY,
        code=E4bBoundaryFailureCode.INVALID_CONTEXT,
    )
    assert replay_port.calls == 0

    read_authority = _authority()
    read_context = _read_context(authority=read_authority)
    selector = E4bOperationSelector(igreja_id=TENANT_A, operation_id=OPERATION_A)
    read_port = _ReconciliationPort(
        _reconciliation_snapshot(
            selector,
            observation=E4bReconciliationObservation.NOT_FOUND,
        )
    )
    object.__setattr__(read_authority, "operator_role_links", set())

    read_result = reconcile(
        context=read_context,
        selector=selector,
        port=read_port,
    )

    _assert_failure(
        read_result,
        operation=E4bBoundaryOperation.RECONCILE,
        code=E4bBoundaryFailureCode.INVALID_CONTEXT,
    )
    assert read_port.calls == 0


def test_c2_q03_wrong_tenant_snapshot_is_rejected_after_one_observation() -> None:
    intent = _intent()
    foreign_intent = _intent(
        key=_key(1, tenant=TENANT_B),
        authority=_authority(tenant=TENANT_B, subject=SUBJECT_B, correlation=CORRELATION_B),
    )
    port = _ReplayPort(_replay_snapshot(foreign_intent))

    result = replay_intent(intent=intent, context=_replay_context(intent), port=port)

    _assert_failure(
        result,
        operation=E4bBoundaryOperation.REPLAY,
        code=E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
    )
    assert port.calls == 1


def test_c2_q10_q16_raw_or_incomplete_replay_observation_never_becomes_business_result() -> None:
    intent = _intent()
    raw_port = _ReplayPort(None)
    incomplete_port = _ReplayPort(
        _replay_snapshot(
            intent,
            observation=E4bReplayObservation.INCOMPLETE_OR_INCONSISTENT,
        )
    )

    for port in (raw_port, incomplete_port):
        result = replay_intent(intent=intent, context=_replay_context(intent), port=port)
        _assert_failure(
            result,
            operation=E4bBoundaryOperation.REPLAY,
            code=(
                E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED
                if port is raw_port
                else E4bBoundaryFailureCode.CHAIN_INCOMPLETE
            ),
        )
        assert port.calls == 1


def test_c2_q15_replay_port_absent_or_unavailable_never_infers_new() -> None:
    intent = _intent()
    absent = replay_intent(intent=intent, context=_replay_context(intent), port=None)
    unavailable_port = _ReplayPort(RuntimeError("synthetic unavailable"))
    unavailable = replay_intent(
        intent=intent,
        context=_replay_context(intent),
        port=unavailable_port,
    )

    _assert_failure(
        absent,
        operation=E4bBoundaryOperation.REPLAY,
        code=E4bBoundaryFailureCode.SOURCE_UNAVAILABLE,
    )
    _assert_failure(
        unavailable,
        operation=E4bBoundaryOperation.REPLAY,
        code=E4bBoundaryFailureCode.SOURCE_UNAVAILABLE,
    )
    assert unavailable_port.calls == 1


def test_c2_q12_order_is_documentary_and_ports_remain_abstract() -> None:
    assert E4B_FUTURE_LOGICAL_ORDER == (
        "autoridade e tenant",
        "K",
        "L",
        "C",
        "stream",
        "revalidação",
        "staging",
        "owner externo",
    )
    assert E4bReplayReadPort.__abstractmethods__ == frozenset({"read_replay_snapshot"})
    assert E4bReconciliationReadPort.__abstractmethods__ == frozenset(
        {"read_reconciliation_snapshot"}
    )


def test_c2_q18_reconcile_confirmed_by_i_exposes_minimized_receipt_once() -> None:
    historical_intent = _intent()
    operation = _confirmed_accept(intent=historical_intent)
    selector = E4bOperationSelector(igreja_id=TENANT_A, operation_id=operation.operation_id)
    port = _ReconciliationPort(
        _reconciliation_snapshot(
            selector,
            observation=E4bReconciliationObservation.CONFIRMED,
            operation=operation,
            historical_identity=_historical_identity(historical_intent, operation),
        )
    )

    result = reconcile(context=_read_context(), selector=selector, port=port)

    assert type(result) is E4bReconciliationDecision
    assert result.outcome is E4bReconciliationOutcome.CONFIRMED
    assert result.receipt is not None
    assert set(result.receipt.to_mapping()) == E4B_RECEIPT_ALLOWLIST
    assert not hasattr(result, "operation")
    assert not hasattr(result.receipt, "operador_id")
    assert port.calls == 1


def test_c2_q18_reconcile_confirmed_by_c_requires_matching_correlation() -> None:
    historical_intent = _intent()
    operation = _confirmed_accept(intent=historical_intent)
    selector = E4bCorrelationSelector(
        igreja_id=TENANT_A,
        correlation_id=operation.correlation_id,
    )
    port = _ReconciliationPort(
        _reconciliation_snapshot(
            selector,
            observation=E4bReconciliationObservation.CONFIRMED,
            operation=operation,
            historical_identity=_historical_identity(historical_intent, operation),
        )
    )

    result = reconcile(context=_read_context(), selector=selector, port=port)

    assert type(result) is E4bReconciliationDecision
    assert result.outcome is E4bReconciliationOutcome.CONFIRMED
    assert result.receipt is not None
    assert port.calls == 1


def test_c2_regression_reconcile_by_i_or_c_rejects_contradictory_history() -> None:
    historical_intent = _intent()
    operation = _confirmed_accept(intent=historical_intent)
    changed_operation = replace(operation, finalidade_id="cuidado_pastoral")
    original_proof = _historical_identity(historical_intent, operation)
    altered_authority = replace(
        historical_intent.authority,
        finalidade_id="cuidado_pastoral",
    )
    copied_fingerprint_proof = _historical_identity(
        historical_intent,
        changed_operation,
        authority=altered_authority,
    )
    selectors_and_proofs = (
        (
            E4bOperationSelector(
                igreja_id=TENANT_A,
                operation_id=operation.operation_id,
            ),
            original_proof,
        ),
        (
            E4bCorrelationSelector(
                igreja_id=TENANT_A,
                correlation_id=operation.correlation_id,
            ),
            copied_fingerprint_proof,
        ),
    )

    for selector, proof in selectors_and_proofs:
        port = _ReconciliationPort(
            _reconciliation_snapshot(
                selector,
                observation=E4bReconciliationObservation.CONFIRMED,
                operation=changed_operation,
                historical_identity=proof,
            )
        )
        result = reconcile(context=_read_context(), selector=selector, port=port)

        assert type(result) is E4bReconciliationDecision
        assert result.outcome is E4bReconciliationOutcome.UNKNOWN
        assert result.receipt is None
        assert port.calls == 1


def test_c2_r4_reconciliation_revalidates_tenant_for_i_and_c_before_receipt() -> None:
    local_intent = _intent()
    local_operation = _confirmed_accept(intent=local_intent)
    foreign_intent = _intent(
        key=_key(7, tenant=TENANT_B),
        authority=_authority(
            tenant=TENANT_B,
            subject=SUBJECT_B,
            correlation=CORRELATION_A,
        ),
    )
    foreign_operation = _confirmed_accept(intent=foreign_intent)
    foreign_identity = _historical_identity(foreign_intent, foreign_operation)
    selectors = (
        E4bOperationSelector(
            igreja_id=TENANT_A,
            operation_id=local_operation.operation_id,
        ),
        E4bCorrelationSelector(
            igreja_id=TENANT_A,
            correlation_id=local_operation.correlation_id,
        ),
    )

    for selector in selectors:
        snapshot = _corrupt_snapshot(
            _reconciliation_snapshot(
                selector,
                observation=E4bReconciliationObservation.CONFIRMED,
                operation=local_operation,
                historical_identity=_historical_identity(
                    local_intent,
                    local_operation,
                ),
            ),
            operation=foreign_operation,
            historical_identity=foreign_identity,
        )
        port = _ReconciliationPort(snapshot)

        result = reconcile(
            context=_read_context(),
            selector=selector,
            port=port,
        )

        _assert_failure(
            result,
            operation=E4bBoundaryOperation.RECONCILE,
            code=E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
        )
        assert port.calls == 1


def test_c2_r4_reconciliation_operation_semantics_fail_before_receipt() -> None:
    for field_name, corrupted_value in (
        ("action", E4bAction.WITHDRAW),
        ("concession_state", E4bConcessionState.WITHDRAWN),
    ):
        historical_intent = _intent()
        operation = _confirmed_accept(intent=historical_intent)
        selector = E4bOperationSelector(
            igreja_id=TENANT_A,
            operation_id=operation.operation_id,
        )
        snapshot = _reconciliation_snapshot(
            selector,
            observation=E4bReconciliationObservation.CONFIRMED,
            operation=operation,
            historical_identity=_historical_identity(historical_intent, operation),
        )
        object.__setattr__(operation, field_name, corrupted_value)
        port = _ReconciliationPort(snapshot)

        result = reconcile(context=_read_context(), selector=selector, port=port)

        _assert_failure(
            result,
            operation=E4bBoundaryOperation.RECONCILE,
            code=E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
        )
        assert port.calls == 1


def test_c2_regression_reconcile_confirmed_without_historical_proof_fails_internal() -> None:
    historical_intent = _intent()
    operation = _confirmed_accept(intent=historical_intent)
    selector = E4bOperationSelector(
        igreja_id=TENANT_A,
        operation_id=operation.operation_id,
    )
    snapshot = _corrupt_snapshot(
        _reconciliation_snapshot(
            selector,
            observation=E4bReconciliationObservation.CONFIRMED,
            operation=operation,
            historical_identity=_historical_identity(historical_intent, operation),
        ),
        historical_identity=None,
    )
    port = _ReconciliationPort(
        snapshot
    )

    result = reconcile(context=_read_context(), selector=selector, port=port)

    _assert_failure(
        result,
        operation=E4bBoundaryOperation.RECONCILE,
        code=E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
    )
    assert port.calls == 1


def test_c2_q18_not_found_requires_proven_absence() -> None:
    selector = E4bOperationSelector(igreja_id=TENANT_A, operation_id=OPERATION_A)
    port = _ReconciliationPort(
        _reconciliation_snapshot(
            selector,
            observation=E4bReconciliationObservation.NOT_FOUND,
        )
    )

    result = reconcile(context=_read_context(), selector=selector, port=port)

    assert type(result) is E4bReconciliationDecision
    assert result.outcome is E4bReconciliationOutcome.NOT_FOUND
    assert result.receipt is None
    assert port.calls == 1


def test_c2_q18_authorized_unknown_and_incomplete_chain_map_only_to_unknown() -> None:
    selector = E4bOperationSelector(igreja_id=TENANT_A, operation_id=OPERATION_A)

    for observation in (
        E4bReconciliationObservation.UNKNOWN,
        E4bReconciliationObservation.INCOMPLETE_OR_INCONSISTENT,
    ):
        port = _ReconciliationPort(
            _reconciliation_snapshot(selector, observation=observation)
        )
        result = reconcile(context=_read_context(), selector=selector, port=port)

        assert type(result) is E4bReconciliationDecision
        assert result.outcome is E4bReconciliationOutcome.UNKNOWN
        assert result.receipt is None
        assert port.calls == 1


def test_c2_regression_nonconfirmed_reconciliation_cannot_carry_identity() -> None:
    historical_intent = _intent()
    operation = _confirmed_accept(intent=historical_intent)
    proof = _historical_identity(historical_intent, operation)
    selector = E4bOperationSelector(
        igreja_id=TENANT_A,
        operation_id=operation.operation_id,
    )

    for observation in (
        E4bReconciliationObservation.NOT_FOUND,
        E4bReconciliationObservation.UNKNOWN,
        E4bReconciliationObservation.INCOMPLETE_OR_INCONSISTENT,
    ):
        snapshot = _corrupt_snapshot(
            _reconciliation_snapshot(selector, observation=observation),
            historical_identity=proof,
        )
        port = _ReconciliationPort(snapshot)
        result = reconcile(context=_read_context(), selector=selector, port=port)

        _assert_failure(
            result,
            operation=E4bBoundaryOperation.RECONCILE,
            code=E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
        )
        assert port.calls == 1


def test_c2_q09_invalid_reconcile_context_or_selector_fails_before_read() -> None:
    selector_i = E4bOperationSelector(igreja_id=TENANT_A, operation_id=OPERATION_A)
    selector_c = E4bCorrelationSelector(igreja_id=TENANT_A, correlation_id=CORRELATION_A)
    port = _ReconciliationPort(
        _reconciliation_snapshot(
            selector_i,
            observation=E4bReconciliationObservation.NOT_FOUND,
        )
    )
    credential_context = replace(_read_context(), presented_credential=object())
    other_tenant_selector = E4bOperationSelector(
        igreja_id=TENANT_B,
        operation_id=OPERATION_A,
    )

    cases = (
        (_read_context(), None, E4bBoundaryFailureCode.INVALID_SELECTOR),
        (_read_context(), (selector_i, selector_c), E4bBoundaryFailureCode.INVALID_SELECTOR),
        (_read_context(), {"I": OPERATION_A}, E4bBoundaryFailureCode.INVALID_SELECTOR),
        (credential_context, selector_i, E4bBoundaryFailureCode.INVALID_CONTEXT),
        (_read_context(), other_tenant_selector, E4bBoundaryFailureCode.INVALID_SELECTOR),
    )
    for context, selector, expected_code in cases:
        result = reconcile(context=context, selector=selector, port=port)
        _assert_failure(
            result,
            operation=E4bBoundaryOperation.RECONCILE,
            code=expected_code,
        )

    assert port.calls == 0


def test_c2_r5_postconstruction_i_and_c_shapes_fail_before_read() -> None:
    selector_cases = (
        (
            E4bOperationSelector(igreja_id=TENANT_A, operation_id=OPERATION_A),
            "operation_id",
            uuid.UUID(int=0),
        ),
        (
            E4bOperationSelector(igreja_id=TENANT_A, operation_id=OPERATION_A),
            "operation_id",
            "invalid",
        ),
        (
            E4bCorrelationSelector(
                igreja_id=TENANT_A,
                correlation_id=CORRELATION_A,
            ),
            "correlation_id",
            uuid.UUID(int=0),
        ),
        (
            E4bCorrelationSelector(
                igreja_id=TENANT_A,
                correlation_id=CORRELATION_A,
            ),
            "correlation_id",
            "invalid",
        ),
    )

    for selector, field_name, corrupted_value in selector_cases:
        object.__setattr__(selector, field_name, corrupted_value)
        port = _ReconciliationPort(None)

        result = reconcile(
            context=_read_context(),
            selector=selector,
            port=port,
        )

        _assert_failure(
            result,
            operation=E4bBoundaryOperation.RECONCILE,
            code=E4bBoundaryFailureCode.INVALID_SELECTOR,
        )
        assert port.calls == 0


def test_c2_q17_reconcile_port_absent_or_unavailable_never_becomes_not_found() -> None:
    selector = E4bOperationSelector(igreja_id=TENANT_A, operation_id=OPERATION_A)
    absent = reconcile(context=_read_context(), selector=selector, port=None)
    unavailable_port = _ReconciliationPort(RuntimeError("synthetic unavailable"))
    unavailable = reconcile(
        context=_read_context(),
        selector=selector,
        port=unavailable_port,
    )

    _assert_failure(
        absent,
        operation=E4bBoundaryOperation.RECONCILE,
        code=E4bBoundaryFailureCode.SOURCE_UNAVAILABLE,
    )
    _assert_failure(
        unavailable,
        operation=E4bBoundaryOperation.RECONCILE,
        code=E4bBoundaryFailureCode.SOURCE_UNAVAILABLE,
    )
    assert unavailable_port.calls == 1


def test_c2_q10_raw_or_wrong_tenant_reconciliation_observation_is_not_not_found() -> None:
    selector = E4bOperationSelector(igreja_id=TENANT_A, operation_id=OPERATION_A)
    raw_port = _ReconciliationPort(None)
    foreign_selector = E4bOperationSelector(igreja_id=TENANT_B, operation_id=OPERATION_A)
    foreign_port = _ReconciliationPort(
        _reconciliation_snapshot(
            foreign_selector,
            observation=E4bReconciliationObservation.NOT_FOUND,
        )
    )

    for port in (raw_port, foreign_port):
        result = reconcile(context=_read_context(), selector=selector, port=port)
        _assert_failure(
            result,
            operation=E4bBoundaryOperation.RECONCILE,
            code=E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
        )
        assert port.calls == 1


def test_c2_q19_q20_outputs_are_disjoint_and_cannot_be_used_as_selectors() -> None:
    intent = _intent()
    replay_port = _ReplayPort(_replay_snapshot(intent))
    replay_result = replay_intent(
        intent=intent,
        context=_replay_context(intent),
        port=replay_port,
    )
    selector = E4bOperationSelector(igreja_id=TENANT_A, operation_id=OPERATION_A)
    reconcile_port = _ReconciliationPort(
        _reconciliation_snapshot(
            selector,
            observation=E4bReconciliationObservation.NOT_FOUND,
        )
    )
    reconciliation_result = reconcile(
        context=_read_context(),
        selector=selector,
        port=reconcile_port,
    )
    mixed_port = _ReconciliationPort(
        _reconciliation_snapshot(
            selector,
            observation=E4bReconciliationObservation.NOT_FOUND,
        )
    )
    mixed = reconcile(
        context=_read_context(),
        selector=replay_result,
        port=mixed_port,
    )

    assert type(replay_result) is E4bReplayDecision
    assert replay_result.outcome in {
        E4bReplayOutcome.NEW,
        E4bReplayOutcome.EXACT_REPLAY,
        E4bReplayOutcome.CONFLICT,
        E4bReplayOutcome.DENIED,
    }
    assert type(reconciliation_result) is E4bReconciliationDecision
    assert reconciliation_result.outcome in {
        E4bReconciliationOutcome.CONFIRMED,
        E4bReconciliationOutcome.NOT_FOUND,
        E4bReconciliationOutcome.UNKNOWN,
    }
    _assert_failure(
        mixed,
        operation=E4bBoundaryOperation.RECONCILE,
        code=E4bBoundaryFailureCode.INVALID_SELECTOR,
    )
    assert replay_port.calls == 1
    assert reconcile_port.calls == 1
    assert mixed_port.calls == 0


def test_c2_q21_inputs_remain_immutable_and_ports_have_no_write_contract() -> None:
    intent = _intent()
    context = _replay_context(intent)
    snapshot = _replay_snapshot(intent)
    port = _ReplayPort(snapshot)

    result = replay_intent(intent=intent, context=context, port=port)

    assert type(result) is E4bReplayDecision
    assert result.outcome is E4bReplayOutcome.NEW
    assert snapshot == _replay_snapshot(intent)
    assert context == _replay_context(intent)
    assert not any(
        name in E4bReplayReadPort.__dict__
        for name in ("write", "stage", "flush", "commit", "rollback")
    )
    assert not any(
        name in E4bReconciliationReadPort.__dict__
        for name in ("write", "stage", "flush", "commit", "rollback")
    )
