"""Casos C0-U01..C0-U13 do domínio E4b, somente com dados sintéticos."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from dataclasses import replace

import pytest

from app.domain.e4b_consent import (
    E4B_IDEMPOTENCY_KEY_PREFIX,
    E4B_RECEIPT_ALLOWLIST,
    E4bAccessDecision,
    E4bAction,
    E4bAdminReadRequest,
    E4bAdminScope,
    E4bAuthorityResolution,
    E4bClassification,
    E4bConcession,
    E4bConcessionState,
    E4bConsentIntent,
    E4bDeleteDecision,
    E4bDenialReason,
    E4bFingerprint,
    E4bHoldEvent,
    E4bHoldEventType,
    E4bIdempotencyKey,
    E4bManifestantRole,
    E4bOperatorKind,
    E4bOrigin,
    E4bRetentionState,
    E4bRole,
    E4bValidationError,
    apply_hold,
    build_confirmed_operation,
    calculate_retention_due_at,
    classify_admin_read,
    classify_e4b_intent,
    classify_person_delete,
    compute_e4b_fingerprint,
    project_receipt,
    resolve_hold,
    retention_state_at,
    start_retention,
)


UTC = dt.timezone.utc
TENANT_A = uuid.UUID("10000000-0000-4000-8000-000000000001")
TENANT_B = uuid.UUID("10000000-0000-4000-8000-000000000002")
SUBJECT_A = uuid.UUID("20000000-0000-4000-8000-000000000001")
SUBJECT_B = uuid.UUID("20000000-0000-4000-8000-000000000002")
RESPONSIBLE_A = uuid.UUID("30000000-0000-4000-8000-000000000001")
OPERATOR_A = uuid.UUID("40000000-0000-4000-8000-000000000001")
OPERATOR_B = uuid.UUID("40000000-0000-4000-8000-000000000002")
CORRELATION_A = uuid.UUID("50000000-0000-4000-8000-000000000001")
CORRELATION_B = uuid.UUID("50000000-0000-4000-8000-000000000002")
OPERATION_A = uuid.UUID("60000000-0000-4000-8000-000000000001")
OPERATION_WITHDRAW = uuid.UUID("60000000-0000-4000-8000-000000000002")
RECEIPT_A = uuid.UUID("70000000-0000-4000-8000-000000000001")
RECEIPT_WITHDRAW = uuid.UUID("70000000-0000-4000-8000-000000000002")
HOLD_1 = uuid.UUID("80000000-0000-4000-8000-000000000001")
HOLD_2 = uuid.UUID("80000000-0000-4000-8000-000000000002")
ADMIN_A = uuid.UUID("90000000-0000-4000-8000-000000000001")
ADMIN_B = uuid.UUID("90000000-0000-4000-8000-000000000002")
CONFIRMED_AT = dt.datetime(2026, 1, 31, 12, 0, tzinfo=UTC)
CONTENT_DIGEST = hashlib.sha256(b"approved synthetic content").hexdigest()


def _key(number: int = 1, *, tenant: uuid.UUID = TENANT_A) -> E4bIdempotencyKey:
    return E4bIdempotencyKey(
        igreja_id=tenant,
        value=f"{E4B_IDEMPOTENCY_KEY_PREFIX}synthetic-{number}",
    )


def _authority(
    *,
    tenant: uuid.UUID = TENANT_A,
    subject: uuid.UUID = SUBJECT_A,
    manifestant: uuid.UUID | None = None,
    role: E4bManifestantRole = E4bManifestantRole.TITULAR,
    responsible: uuid.UUID | None = None,
    operator: uuid.UUID = OPERATOR_A,
    correlation: uuid.UUID = CORRELATION_A,
    purpose: str = "tarefas_operacionais",
    term: str = "termo-v1",
    operator_links: frozenset[E4bRole] = frozenset(),
    legacy_artifact: object | None = None,
    server_resolved: bool = True,
    relation_valid: bool = True,
) -> E4bAuthorityResolution:
    if manifestant is None:
        manifestant = subject if role is E4bManifestantRole.TITULAR else RESPONSIBLE_A
    if role is E4bManifestantRole.RESPONSAVEL and responsible is None:
        responsible = manifestant
    return E4bAuthorityResolution(
        igreja_id=tenant,
        titular_pessoa_id=subject,
        manifestante_pessoa_id=manifestant,
        manifestant_role=role,
        responsavel_pessoa_id=responsible,
        operador_id=operator,
        operator_kind=E4bOperatorKind.HUMAN,
        finalidade_id=purpose,
        origin=E4bOrigin.E4B,
        correlation_id=correlation,
        contract_version="contract-v1",
        policy_version="policy-v1",
        term_version=term,
        content_digest=CONTENT_DIGEST,
        server_resolved=server_resolved,
        manifestant_relation_valid=relation_valid,
        operator_role_links=operator_links,
        legacy_artifact=legacy_artifact,
    )


def _intent(
    *,
    action: E4bAction = E4bAction.ACCEPT,
    key: E4bIdempotencyKey | None = None,
    authority: E4bAuthorityResolution | None = None,
    origin_id: uuid.UUID | None = None,
    legacy_artifact: object | None = None,
) -> E4bConsentIntent:
    return E4bConsentIntent.create(
        action=action,
        idempotency_key=key or _key(),
        authority=authority or _authority(),
        origin_accept_operation_id=origin_id,
        legacy_artifact=legacy_artifact,
    )


def _confirmed_accept(
    *,
    intent: E4bConsentIntent | None = None,
    operation_id: uuid.UUID = OPERATION_A,
    receipt_id: uuid.UUID = RECEIPT_A,
):
    candidate = intent or _intent()
    decision = classify_e4b_intent(candidate)
    assert decision.classification is E4bClassification.ELIGIBLE
    return build_confirmed_operation(
        candidate,
        classification=decision,
        operation_id=operation_id,
        receipt_id=receipt_id,
        confirmed_at=CONFIRMED_AT,
    )


def _active_concession(
    *,
    tenant: uuid.UUID = TENANT_A,
    subject: uuid.UUID = SUBJECT_A,
    purpose: str = "tarefas_operacionais",
    accept_id: uuid.UUID = OPERATION_A,
) -> E4bConcession:
    return E4bConcession(
        igreja_id=tenant,
        titular_pessoa_id=subject,
        finalidade_id=purpose,
        state=E4bConcessionState.ACTIVE,
        accept_operation_id=accept_id,
    )


def _withdrawn_concession() -> E4bConcession:
    return replace(
        _active_concession(),
        state=E4bConcessionState.WITHDRAWN,
        withdraw_operation_id=OPERATION_WITHDRAW,
    )


def _hold(
    *,
    hold_id: uuid.UUID,
    event_type: E4bHoldEventType,
    at: dt.datetime,
    tenant: uuid.UUID = TENANT_A,
    operation_id: uuid.UUID = OPERATION_A,
    authority_id: uuid.UUID = ADMIN_A,
) -> E4bHoldEvent:
    return E4bHoldEvent(
        hold_id=hold_id,
        igreja_id=tenant,
        operation_id=operation_id,
        authority_id=authority_id,
        event_type=event_type,
        occurred_at=at,
        policy_version="policy-v1",
    )


def test_c0_u01_own_accept_is_only_eligible_for_staging() -> None:
    result = classify_e4b_intent(_intent())

    assert result.classification is E4bClassification.ELIGIBLE
    assert result.eligible_for_staging is True
    assert result.requires_confirmation is True
    assert result.existing_operation is None
    assert result.receipt is None


def test_c0_u02_operator_overlap_without_server_owned_link_is_denied() -> None:
    authority = _authority(operator=SUBJECT_A)

    result = classify_e4b_intent(_intent(authority=authority))

    assert result.classification is E4bClassification.DENIED
    assert result.reason is E4bDenialReason.OPERATOR_ROLE_UNRESOLVED


def test_c0_u03_withdraw_requires_same_active_e4b_accept() -> None:
    accept = _confirmed_accept()
    withdrawal = _intent(
        action=E4bAction.WITHDRAW,
        key=_key(2),
        origin_id=accept.operation_id,
    )

    result = classify_e4b_intent(
        withdrawal,
        concession=_active_concession(),
        origin_accept_operation=accept,
    )

    assert result.classification is E4bClassification.ELIGIBLE
    assert result.origin_accept_operation_id == accept.operation_id
    assert result.receipt is None


@pytest.mark.parametrize("variant", ("missing", "withdrawn", "tenant", "subject", "purpose", "legacy"))
def test_c0_u04_invalid_withdraw_origin_is_denied(variant: str) -> None:
    accept = _confirmed_accept()
    withdrawal = _intent(
        action=E4bAction.WITHDRAW,
        key=_key(2),
        origin_id=accept.operation_id,
    )
    if variant == "missing":
        result = classify_e4b_intent(withdrawal, concession=None, origin_accept_operation=None)
    elif variant == "withdrawn":
        result = classify_e4b_intent(
            withdrawal,
            concession=_withdrawn_concession(),
            origin_accept_operation=accept,
        )
    elif variant == "tenant":
        other_accept = _confirmed_accept(
            intent=_intent(key=_key(1, tenant=TENANT_B), authority=_authority(tenant=TENANT_B)),
            operation_id=uuid.UUID("60000000-0000-4000-8000-000000000003"),
            receipt_id=uuid.UUID("70000000-0000-4000-8000-000000000003"),
        )
        result = classify_e4b_intent(
            withdrawal,
            concession=_active_concession(),
            origin_accept_operation=other_accept,
        )
    elif variant == "subject":
        other_accept = replace(
            accept,
            titular_pessoa_id=SUBJECT_B,
            manifestante_pessoa_id=SUBJECT_B,
        )
        result = classify_e4b_intent(
            withdrawal,
            concession=_active_concession(),
            origin_accept_operation=other_accept,
        )
    elif variant == "purpose":
        other_accept = replace(accept, finalidade_id="cuidado_pastoral")
        result = classify_e4b_intent(
            withdrawal,
            concession=_active_concession(),
            origin_accept_operation=other_accept,
        )
    else:
        legacy = _intent(action=E4bAction.WITHDRAW, key=_key(2), origin_id=accept.operation_id, legacy_artifact=object())
        result = classify_e4b_intent(
            legacy,
            concession=_active_concession(),
            origin_accept_operation=accept,
        )

    assert result.classification is E4bClassification.DENIED
    assert result.receipt is None


def test_c0_u05_overlapping_roles_need_explicit_server_owned_links() -> None:
    explicit_titular_overlap = _authority(
        operator=SUBJECT_A,
        operator_links=frozenset({E4bRole.TITULAR, E4bRole.MANIFESTANTE}),
    )
    explicit_responsible_overlap = _authority(
        role=E4bManifestantRole.RESPONSAVEL,
        manifestant=RESPONSIBLE_A,
        responsible=RESPONSIBLE_A,
        operator=RESPONSIBLE_A,
        operator_links=frozenset({E4bRole.MANIFESTANTE, E4bRole.RESPONSAVEL}),
    )

    assert classify_e4b_intent(_intent(authority=explicit_titular_overlap)).eligible_for_staging
    assert classify_e4b_intent(
        _intent(authority=explicit_responsible_overlap)
    ).eligible_for_staging


def test_c0_u06_same_key_replays_exact_fingerprint_and_conflicts_on_difference() -> None:
    original_intent = _intent()
    original = _confirmed_accept(intent=original_intent)

    replay = classify_e4b_intent(original_intent, existing_operation=original)
    changed_intent = _intent(
        key=original_intent.idempotency_key,
        authority=_authority(term="termo-v2"),
    )
    conflict = classify_e4b_intent(changed_intent, existing_operation=original)

    assert replay.classification is E4bClassification.REPLAY
    assert replay.receipt is not None
    assert replay.receipt.receipt_id == original.receipt_id
    assert conflict.classification is E4bClassification.CONFLICT
    assert conflict.receipt is None


def test_p1_01_accept_against_active_concession_is_denied() -> None:
    result = classify_e4b_intent(
        _intent(),
        concession=_active_concession(),
    )

    assert result.classification is E4bClassification.DENIED
    assert result.reason is E4bDenialReason.ACTIVE_CONCESSION
    assert result.receipt is None


def test_withdraw_replay_and_fingerprint_conflict_preserve_the_historical_receipt() -> None:
    accept = _confirmed_accept()
    withdrawal_intent = _intent(
        action=E4bAction.WITHDRAW,
        key=_key(2),
        origin_id=accept.operation_id,
    )
    withdrawal_decision = classify_e4b_intent(
        withdrawal_intent,
        concession=_active_concession(),
        origin_accept_operation=accept,
    )
    withdrawal = build_confirmed_operation(
        withdrawal_intent,
        classification=withdrawal_decision,
        operation_id=OPERATION_WITHDRAW,
        receipt_id=RECEIPT_WITHDRAW,
        confirmed_at=CONFIRMED_AT + dt.timedelta(minutes=1),
    )
    withdrawn_concession = replace(
        _active_concession(),
        state=E4bConcessionState.WITHDRAWN,
        withdraw_operation_id=withdrawal.operation_id,
    )
    replay = classify_e4b_intent(
        withdrawal_intent,
        existing_operation=withdrawal,
        concession=withdrawn_concession,
    )
    changed = _intent(
        action=E4bAction.WITHDRAW,
        key=withdrawal_intent.idempotency_key,
        origin_id=accept.operation_id,
        authority=_authority(term="termo-v2"),
    )
    conflict = classify_e4b_intent(
        changed,
        existing_operation=withdrawal,
        concession=withdrawn_concession,
        origin_accept_operation=accept,
    )

    assert replay.classification is E4bClassification.REPLAY
    assert replay.receipt is not None
    assert replay.receipt.receipt_id == withdrawal.receipt_id
    assert conflict.classification is E4bClassification.CONFLICT
    assert conflict.receipt is None


def test_retention_from_february_29_uses_last_valid_day_after_24_months() -> None:
    confirmed = dt.datetime(2024, 2, 29, 8, 15, tzinfo=UTC)
    due = calculate_retention_due_at(confirmed)
    retention = start_retention(
        igreja_id=TENANT_A,
        operation_id=OPERATION_A,
        confirmed_at=confirmed,
    )

    assert due == dt.datetime(2026, 2, 28, 8, 15, tzinfo=UTC)
    assert retention.retention_due_at == due
    assert retention_state_at(retention, due) is E4bRetentionState.RETENTION_ELIGIBLE


def test_hold_rejects_tenant_operation_mismatch_and_invalid_resolution() -> None:
    retention = start_retention(
        igreja_id=TENANT_A,
        operation_id=OPERATION_A,
        confirmed_at=CONFIRMED_AT,
    )
    wrong_tenant = _hold(
        hold_id=HOLD_1,
        event_type=E4bHoldEventType.HOLD_APPLIED,
        at=CONFIRMED_AT + dt.timedelta(hours=1),
        tenant=TENANT_B,
    )
    wrong_operation = _hold(
        hold_id=HOLD_1,
        event_type=E4bHoldEventType.HOLD_APPLIED,
        at=CONFIRMED_AT + dt.timedelta(hours=1),
        operation_id=uuid.UUID("60000000-0000-4000-8000-000000000003"),
    )
    invalid_resolution = _hold(
        hold_id=HOLD_1,
        event_type=E4bHoldEventType.HOLD_RESOLVED,
        at=CONFIRMED_AT + dt.timedelta(hours=1),
    )

    with pytest.raises(E4bValidationError):
        apply_hold(retention, wrong_tenant)
    with pytest.raises(E4bValidationError):
        apply_hold(retention, wrong_operation)
    with pytest.raises(E4bValidationError):
        resolve_hold(retention, invalid_resolution)


def test_withdraw_receipt_keeps_allowlist_and_excludes_direct_person_ids() -> None:
    accept = _confirmed_accept()
    withdrawal_intent = _intent(
        action=E4bAction.WITHDRAW,
        key=_key(2),
        origin_id=accept.operation_id,
    )
    decision = classify_e4b_intent(
        withdrawal_intent,
        concession=_active_concession(),
        origin_accept_operation=accept,
    )
    withdrawal = build_confirmed_operation(
        withdrawal_intent,
        classification=decision,
        operation_id=OPERATION_WITHDRAW,
        receipt_id=RECEIPT_WITHDRAW,
        confirmed_at=CONFIRMED_AT + dt.timedelta(minutes=1),
    )
    mapping = project_receipt(withdrawal).to_mapping()

    assert set(mapping) == E4B_RECEIPT_ALLOWLIST
    assert mapping["action"] == E4bAction.WITHDRAW.value
    assert mapping["concession_state"] == E4bConcessionState.WITHDRAWN.value
    assert all(
        str(person_id) not in mapping.values()
        for person_id in (SUBJECT_A, RESPONSIBLE_A, OPERATOR_A)
    )
    assert "motivo_hold" not in mapping


def test_same_tenant_admin_read_scope_is_allowed() -> None:
    request = E4bAdminReadRequest(
        actor_id=ADMIN_A,
        requester_igreja_id=TENANT_A,
        record_igreja_id=TENANT_A,
        resolved_admin_igreja_id=TENANT_A,
        resolved_admin_actor_id=ADMIN_A,
        scope=E4bAdminScope.READ,
    )

    assert classify_admin_read(request) is E4bAccessDecision.ALLOWED


def test_fingerprint_with_valid_shape_but_wrong_canonical_value_is_denied_first() -> None:
    original_intent = _intent()
    original = _confirmed_accept(intent=original_intent)
    forged = replace(
        original_intent,
        fingerprint=E4bFingerprint("f" * 64),
    )

    result = classify_e4b_intent(
        forged,
        existing_operation=original,
        concession=_active_concession(),
        origin_accept_operation=original,
    )

    assert result.classification is E4bClassification.DENIED
    assert result.reason is E4bDenialReason.FINGERPRINT_INVALID
    assert result.receipt is None


def test_c0_u07_only_same_tenant_server_owned_admin_can_read() -> None:
    same_tenant = E4bAdminReadRequest(
        actor_id=ADMIN_A,
        requester_igreja_id=TENANT_A,
        record_igreja_id=TENANT_A,
        resolved_admin_igreja_id=TENANT_A,
        scope=E4bAdminScope.REIDENTIFY,
        resolved_admin_actor_id=ADMIN_A,
    )
    other_admin = replace(
        same_tenant,
        actor_id=ADMIN_B,
        resolved_admin_igreja_id=TENANT_B,
        resolved_admin_actor_id=ADMIN_B,
    )
    non_admin = replace(same_tenant, resolved_admin_igreja_id=None)
    operator = replace(same_tenant, actor_id=OPERATOR_A, resolved_admin_igreja_id=None)

    assert classify_admin_read(same_tenant) is E4bAccessDecision.ALLOWED
    assert classify_admin_read(other_admin) is E4bAccessDecision.DENIED
    assert classify_admin_read(non_admin) is E4bAccessDecision.DENIED
    assert classify_admin_read(operator) is E4bAccessDecision.DENIED


def test_c0_u08_retention_uses_calendar_24_months_and_never_discards() -> None:
    retention = start_retention(
        igreja_id=TENANT_A,
        operation_id=OPERATION_A,
        confirmed_at=CONFIRMED_AT,
    )
    due = calculate_retention_due_at(CONFIRMED_AT)

    assert due == dt.datetime(2028, 1, 31, 12, 0, tzinfo=UTC)
    assert retention_state_at(retention, due - dt.timedelta(microseconds=1)) is E4bRetentionState.RETENTION_RUNNING
    assert retention_state_at(retention, due) is E4bRetentionState.RETENTION_ELIGIBLE
    assert retention_state_at(retention, due + dt.timedelta(days=1)) is E4bRetentionState.RETENTION_ELIGIBLE
    assert retention.operation_id == OPERATION_A


def test_c0_u09_overlapping_holds_pause_once_until_last_resolution() -> None:
    retention = start_retention(
        igreja_id=TENANT_A,
        operation_id=OPERATION_A,
        confirmed_at=CONFIRMED_AT,
    )
    first_applied = _hold(
        hold_id=HOLD_1,
        event_type=E4bHoldEventType.HOLD_APPLIED,
        at=dt.datetime(2027, 1, 31, 12, 0, tzinfo=UTC),
    )
    second_applied = _hold(
        hold_id=HOLD_2,
        event_type=E4bHoldEventType.HOLD_APPLIED,
        at=dt.datetime(2027, 2, 15, 12, 0, tzinfo=UTC),
    )
    first_resolved = _hold(
        hold_id=HOLD_1,
        event_type=E4bHoldEventType.HOLD_RESOLVED,
        at=dt.datetime(2027, 3, 1, 12, 0, tzinfo=UTC),
    )
    last_resolved = _hold(
        hold_id=HOLD_2,
        event_type=E4bHoldEventType.HOLD_RESOLVED,
        at=dt.datetime(2027, 3, 15, 12, 0, tzinfo=UTC),
    )

    held_once = apply_hold(retention, first_applied)
    held_twice = apply_hold(held_once, second_applied)
    still_held = resolve_hold(held_twice, first_resolved)
    resumed = resolve_hold(still_held, last_resolved)

    assert held_once.suspension_started_at == first_applied.occurred_at
    assert held_twice.suspension_started_at == first_applied.occurred_at
    assert still_held.active_hold_ids == (HOLD_2,)
    assert still_held.retention_due_at == retention.retention_due_at
    assert resumed.active_hold_ids == ()
    assert resumed.suspension_started_at is None
    assert resumed.retention_due_at == retention.retention_due_at + dt.timedelta(days=43)
    assert resumed.state is E4bRetentionState.RETENTION_RUNNING


def test_c0_u10_person_delete_is_denied_during_retention_or_hold_and_deferred_after() -> None:
    retention = start_retention(
        igreja_id=TENANT_A,
        operation_id=OPERATION_A,
        confirmed_at=CONFIRMED_AT,
    )
    held = apply_hold(
        retention,
        _hold(
            hold_id=HOLD_1,
            event_type=E4bHoldEventType.HOLD_APPLIED,
            at=dt.datetime(2026, 2, 1, tzinfo=UTC),
        ),
    )
    assert classify_person_delete(retention, at=CONFIRMED_AT) is E4bDeleteDecision.DENIED
    assert classify_person_delete(held, at=retention.retention_due_at) is E4bDeleteDecision.DENIED
    assert classify_person_delete(retention, at=retention.retention_due_at) is E4bDeleteDecision.DEFERRED


def test_c0_u11_receipt_is_an_explicit_allowlist_without_direct_person_ids() -> None:
    operation = _confirmed_accept(
        intent=_intent(
            authority=_authority(
                role=E4bManifestantRole.RESPONSAVEL,
                manifestant=RESPONSIBLE_A,
                responsible=RESPONSIBLE_A,
                operator=OPERATOR_B,
            )
        )
    )
    receipt = project_receipt(operation)
    mapping = receipt.to_mapping()

    assert receipt.allowlisted_keys == E4B_RECEIPT_ALLOWLIST
    assert set(mapping) == E4B_RECEIPT_ALLOWLIST
    assert "titular_pessoa_id" not in mapping
    assert "manifestante_pessoa_id" not in mapping
    assert "responsavel_pessoa_id" not in mapping
    assert "operador_id" not in mapping
    assert all(str(person_id) not in mapping.values() for person_id in (SUBJECT_A, RESPONSIBLE_A, OPERATOR_B))
    with pytest.raises(AttributeError):
        receipt.titular_pessoa_id  # type: ignore[attr-defined]


def test_c0_u12_legacy_artifact_is_denied_before_replay_or_origin() -> None:
    original = _confirmed_accept()
    legacy = _intent(key=original.idempotency_key, legacy_artifact=object())

    result = classify_e4b_intent(
        legacy,
        existing_operation=original,
        concession=_active_concession(),
        origin_accept_operation=original,
    )

    assert result.classification is E4bClassification.DENIED
    assert result.reason is E4bDenialReason.LEGACY_ARTIFACT
    assert result.receipt is None


def test_c0_u13_withdraw_then_new_accept_denies_but_old_accept_replays_without_reactivation() -> None:
    accept_intent = _intent(key=_key(1))
    accept = _confirmed_accept(intent=accept_intent)
    active = _active_concession()
    withdraw_intent = _intent(
        action=E4bAction.WITHDRAW,
        key=_key(2),
        origin_id=accept.operation_id,
    )
    withdrawal_decision = classify_e4b_intent(
        withdraw_intent,
        concession=active,
        origin_accept_operation=accept,
    )
    withdrawal = build_confirmed_operation(
        withdraw_intent,
        classification=withdrawal_decision,
        operation_id=OPERATION_WITHDRAW,
        receipt_id=RECEIPT_WITHDRAW,
        confirmed_at=CONFIRMED_AT + dt.timedelta(minutes=1),
    )
    withdrawn = replace(
        active,
        state=E4bConcessionState.WITHDRAWN,
        withdraw_operation_id=withdrawal.operation_id,
    )

    new_accept = classify_e4b_intent(
        _intent(key=_key(3)),
        concession=withdrawn,
    )
    historical_replay = classify_e4b_intent(
        accept_intent,
        existing_operation=accept,
        concession=withdrawn,
    )

    assert new_accept.classification is E4bClassification.DENIED
    assert new_accept.reason is E4bDenialReason.WITHDRAWN_CONCESSION
    assert historical_replay.classification is E4bClassification.REPLAY
    assert historical_replay.receipt is not None
    assert historical_replay.receipt.receipt_id == accept.receipt_id
    assert withdrawn.state is E4bConcessionState.WITHDRAWN
    assert historical_replay.existing_operation is accept


def test_fingerprint_is_canonical_and_changes_when_closed_authority_changes() -> None:
    first = _intent()
    second = _intent(authority=_authority(correlation=CORRELATION_B))

    assert compute_e4b_fingerprint(first) == first.fingerprint
    assert compute_e4b_fingerprint(second) == second.fingerprint
    assert first.fingerprint != second.fingerprint
