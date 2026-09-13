from __future__ import annotations

import ast
import inspect
import json
import os
import subprocess
import sys
import uuid
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from app.agent.turn_execution import (
    MAX_COMPATIBILITY_KEYS_PER_RESOLUTION,
    MAX_EFFECT_RECEIPTS_PER_RESOLUTION,
    AgentCompatibilityKeyError,
    AgentCompatibilityKeyResolution,
    AgentCompatibilityKeySource,
    AgentCompatibilityKeyVersion,
    AgentConversationSerialScope,
    AgentEffectCompatibilityKey,
    AgentEffectReceipt,
    AgentEffectReceiptError,
    AgentEffectReceiptOutcome,
    AgentOutboundReplyReservationV2,
    AgentReplyOutboxEntry,
    AgentReplyOutboxError,
    AgentReplyOutboxEvent,
    AgentReplyOutboxState,
    AgentTurnExecutionErrorCode,
    AgentTurnExecutionPlan,
    AgentTurnExecutionPlanError,
    bind_agent_legacy_reply_key_evidence,
    build_agent_conversation_serial_scope,
    build_agent_effect_compatibility_key,
    build_agent_effect_receipt,
    build_agent_outbound_reply_reservation_v2,
    build_agent_reply_outbox_entry,
    build_agent_turn_execution_plan,
    reconcile_agent_effect_receipt_replay,
    reconcile_agent_turn_execution_plan,
    resolve_agent_effect_compatibility_keys,
    resolve_agent_effect_receipts,
    resolve_agent_turn_execution_plans,
    transition_agent_reply_outbox,
    validate_agent_turn_execution_plan,
)
from app.agent.turn_identity import (
    MAX_EFFECT_INTENTS_PER_TURN,
    AgentEffectIntent,
    AgentEffectKind,
    AgentInboundProvider,
    AgentTurnIdentity,
    build_agent_effect_intent,
    build_agent_turn_identity,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = BACKEND_ROOT / "app" / "agent" / "turn_execution.py"
TURN_PLAN_ADAPTER_PATH = (
    BACKEND_ROOT / "app" / "agent" / "turn_plan_adapter.py"
)
APP_ROOT = BACKEND_ROOT / "app"


def _identity(
    *,
    igreja: int = 1,
    conversation: int = 2,
    inbound: int = 3,
    provider_message_id: str = "evolution-message-001",
) -> AgentTurnIdentity:
    return build_agent_turn_identity(
        igreja_id=uuid.UUID(int=igreja),
        conversation_id=uuid.UUID(int=conversation),
        inbound_message_id=uuid.UUID(int=inbound),
        provider=AgentInboundProvider.EVOLUTION,
        provider_message_id=provider_message_id,
    )


def _intent(
    identity: AgentTurnIdentity,
    kind: AgentEffectKind,
    ordinal: int = 0,
    *,
    value: str = "value",
) -> AgentEffectIntent:
    return build_agent_effect_intent(
        identity,
        kind=kind,
        ordinal=ordinal,
        payload={"value": value, "enabled": True},
    )


def _plan_material(
    identity: AgentTurnIdentity,
) -> tuple[AgentTurnExecutionPlan, tuple[AgentEffectIntent, ...]]:
    intents = (
        _intent(identity, AgentEffectKind.OUTBOUND_REPLY, value="reply"),
        _intent(identity, AgentEffectKind.TOOL_CALL, 1, value="tool-1"),
        _intent(identity, AgentEffectKind.AUDIT_EVENT, 0, value="audit"),
        _intent(identity, AgentEffectKind.TOOL_CALL, 0, value="tool-0"),
        _intent(identity, AgentEffectKind.INTAKE_UPDATE, value="intake"),
    )
    return build_agent_turn_execution_plan(identity, intents), intents


def _reply_intent(plan: AgentTurnExecutionPlan) -> AgentEffectIntent:
    return next(
        intent
        for intent in plan.effect_intents
        if intent.kind is AgentEffectKind.OUTBOUND_REPLY
    )


def _compatibility_key(
    identity: AgentTurnIdentity,
    plan: AgentTurnExecutionPlan,
    intent: AgentEffectIntent,
    version: AgentCompatibilityKeyVersion,
) -> AgentEffectCompatibilityKey:
    if version is AgentCompatibilityKeyVersion.V2:
        return build_agent_effect_compatibility_key(
            identity,
            plan,
            intent,
            version=version,
        )
    suffix = "a" * 64
    if version is AgentCompatibilityKeyVersion.V0:
        suffix = f"{suffix}:{'b' * 64}"
    return bind_agent_legacy_reply_key_evidence(
        identity,
        plan,
        intent,
        version=version,
        exact_observed_key=f"agent-reply:{suffix}",
    )


def _assert_code(
    error: Exception,
    expected: AgentTurnExecutionErrorCode,
) -> None:
    assert getattr(error, "code", None) is expected


def test_plan_is_canonical_complete_and_independent_of_input_order() -> None:
    identity = _identity()
    plan, intents = _plan_material(identity)
    reverse = build_agent_turn_execution_plan(identity, list(reversed(intents)))

    assert reverse.plan_digest == plan.plan_digest
    assert reverse.effect_intents == plan.effect_intents
    assert [item.kind for item in plan.effect_intents] == [
        AgentEffectKind.INTAKE_UPDATE,
        AgentEffectKind.TOOL_CALL,
        AgentEffectKind.TOOL_CALL,
        AgentEffectKind.AUDIT_EVENT,
        AgentEffectKind.OUTBOUND_REPLY,
    ]
    assert plan.turn_id == identity.turn_id
    assert len(plan.effect_intents) == len(intents)


def test_plan_digest_changes_when_complete_effect_set_changes() -> None:
    identity = _identity()
    plan, intents = _plan_material(identity)
    additional = _intent(
        identity,
        AgentEffectKind.AUDIT_EVENT,
        1,
        value="second-audit",
    )

    changed = build_agent_turn_execution_plan(identity, (*intents, additional))

    assert changed.plan_digest != plan.plan_digest


def test_exact_plan_replay_reconciles_despite_input_order() -> None:
    identity = _identity()
    first, intents = _plan_material(identity)
    replay = build_agent_turn_execution_plan(identity, list(reversed(intents)))

    resolved = reconcile_agent_turn_execution_plan(identity, first, replay)

    assert resolved is first


def test_changed_plan_material_conflicts_for_same_turn() -> None:
    identity = _identity()
    first_reply = _intent(
        identity,
        AgentEffectKind.OUTBOUND_REPLY,
        value="first",
    )
    replay_reply = _intent(
        identity,
        AgentEffectKind.OUTBOUND_REPLY,
        value="changed",
    )
    first = build_agent_turn_execution_plan(identity, (first_reply,))
    replay = build_agent_turn_execution_plan(identity, (replay_reply,))

    with pytest.raises(AgentTurnExecutionPlanError) as exc_info:
        reconcile_agent_turn_execution_plan(identity, first, replay)

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.EXECUTION_PLAN_CONFLICT,
    )


def test_durable_plan_resolution_allows_zero_or_one_row_only() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)

    assert resolve_agent_turn_execution_plans(identity, ()) is None
    assert resolve_agent_turn_execution_plans(identity, (plan,)) is plan
    with pytest.raises(AgentTurnExecutionPlanError) as exc_info:
        resolve_agent_turn_execution_plans(identity, (plan, plan))
    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.EXECUTION_PLAN_CONFLICT,
    )


def test_empty_complete_plan_is_supported_without_implying_execution() -> None:
    identity = _identity()

    plan = build_agent_turn_execution_plan(identity, ())

    assert plan.effect_intents == ()
    assert validate_agent_turn_execution_plan(identity, plan) is plan


@pytest.mark.parametrize(
    "kind",
    [
        AgentEffectKind.INTAKE_UPDATE,
        AgentEffectKind.APPLY_OPTOUT,
        AgentEffectKind.APPLY_CONSENT,
    ],
)
def test_singleton_effects_require_ordinal_zero(kind: AgentEffectKind) -> None:
    identity = _identity()
    singleton = _intent(identity, kind, 1)

    with pytest.raises(AgentTurnExecutionPlanError) as exc_info:
        build_agent_turn_execution_plan(identity, (singleton,))

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.SINGLETON_EFFECT_VIOLATION,
    )


def test_outbound_reply_requires_ordinal_zero() -> None:
    identity = _identity()
    reply = _intent(identity, AgentEffectKind.OUTBOUND_REPLY, 1)

    with pytest.raises(AgentTurnExecutionPlanError) as exc_info:
        build_agent_turn_execution_plan(identity, (reply,))

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.OUTBOUND_REPLY_VIOLATION,
    )


def test_outbound_reply_is_at_most_one() -> None:
    identity = _identity()
    first = _intent(identity, AgentEffectKind.OUTBOUND_REPLY, 0, value="one")
    second = _intent(identity, AgentEffectKind.OUTBOUND_REPLY, 1, value="two")

    with pytest.raises(AgentTurnExecutionPlanError) as exc_info:
        build_agent_turn_execution_plan(identity, (first, second))

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.OUTBOUND_REPLY_VIOLATION,
    )


def test_repeatable_effects_allow_stable_nonzero_ordinals() -> None:
    identity = _identity()
    values = (
        _intent(identity, AgentEffectKind.TOOL_CALL, 9, value="tool"),
        _intent(identity, AgentEffectKind.AUDIT_EVENT, 4, value="audit"),
    )

    plan = build_agent_turn_execution_plan(identity, values)

    assert {item.ordinal for item in plan.effect_intents} == {4, 9}


def test_plan_collection_limit_is_checked_before_items() -> None:
    identity = _identity()
    values = [object()] * (MAX_EFFECT_INTENTS_PER_TURN + 1)

    with pytest.raises(AgentTurnExecutionPlanError) as exc_info:
        build_agent_turn_execution_plan(identity, values)

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.INVALID_PLAN_COLLECTION,
    )


def test_plan_requires_exact_list_or_tuple() -> None:
    identity = _identity()

    with pytest.raises(AgentTurnExecutionPlanError) as exc_info:
        build_agent_turn_execution_plan(identity, iter(()))

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.INVALID_PLAN_COLLECTION,
    )


def test_plan_rejects_effect_from_another_tenant_even_if_homogeneous() -> None:
    expected = _identity(igreja=10)
    other = _identity(igreja=11)
    foreign = _intent(other, AgentEffectKind.TOOL_CALL)

    with pytest.raises(AgentTurnExecutionPlanError) as exc_info:
        build_agent_turn_execution_plan(expected, (foreign,))

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.INVALID_PLAN_COLLECTION,
    )


def test_plan_validation_rejects_wrong_expected_identity() -> None:
    identity = _identity(igreja=20)
    other = _identity(igreja=21)
    plan, _ = _plan_material(identity)

    with pytest.raises(AgentTurnExecutionPlanError) as exc_info:
        validate_agent_turn_execution_plan(other, plan)

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.UNEXPECTED_PLAN_IDENTITY,
    )


@pytest.mark.parametrize(
    ("attribute", "replacement"),
    [
        ("turn_id", "agent_turn_v1_" + "0" * 64),
        ("plan_digest", "agent_plan_v1_" + "0" * 64),
        ("effect_intents", ()),
    ],
)
def test_tampered_plan_is_rejected(
    attribute: str,
    replacement: object,
) -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    object.__setattr__(plan, attribute, replacement)

    with pytest.raises(AgentTurnExecutionPlanError):
        validate_agent_turn_execution_plan(identity, plan)


def test_serial_scope_is_conversation_tenant_bound_and_turn_stable() -> None:
    first = _identity(igreja=30, conversation=31, inbound=32)
    same_conversation = _identity(igreja=30, conversation=31, inbound=33)
    other_tenant = _identity(igreja=34, conversation=31, inbound=32)
    other_conversation = _identity(igreja=30, conversation=35, inbound=32)

    first_scope = build_agent_conversation_serial_scope(first)
    same_scope = build_agent_conversation_serial_scope(same_conversation)
    tenant_scope = build_agent_conversation_serial_scope(other_tenant)
    conversation_scope = build_agent_conversation_serial_scope(
        other_conversation
    )

    assert first_scope.scope_id == same_scope.scope_id
    assert first_scope.scope_id != tenant_scope.scope_id
    assert first_scope.scope_id != conversation_scope.scope_id
    assert first.turn_id != same_conversation.turn_id


def test_claim_material_is_absent_from_every_identity_boundary() -> None:
    dataclass_types = (
        AgentConversationSerialScope,
        AgentTurnExecutionPlan,
        AgentEffectReceipt,
        AgentOutboundReplyReservationV2,
        AgentReplyOutboxEntry,
        AgentEffectCompatibilityKey,
        AgentCompatibilityKeyResolution,
    )
    functions = (
        build_agent_conversation_serial_scope,
        build_agent_turn_execution_plan,
        build_agent_effect_receipt,
        build_agent_outbound_reply_reservation_v2,
        build_agent_reply_outbox_entry,
        transition_agent_reply_outbox,
        build_agent_effect_compatibility_key,
        resolve_agent_effect_compatibility_keys,
    )

    for value_type in dataclass_types:
        names = {item.name for item in fields(value_type)}
        assert not any("claim" in name or "lease" in name for name in names)
    for function in functions:
        names = set(inspect.signature(function).parameters)
        assert not any("claim" in name or "lease" in name for name in names)


def test_execution_values_are_frozen_slotted_and_sanitized() -> None:
    identity = _identity(provider_message_id="private-provider-id")
    plan, _ = _plan_material(identity)
    scope = plan.serial_scope
    reply = _reply_intent(plan)
    receipt = build_agent_effect_receipt(
        identity,
        plan,
        reply,
        outcome=AgentEffectReceiptOutcome.COMMITTED,
    )
    entry = build_agent_reply_outbox_entry(identity, plan)
    key = build_agent_effect_compatibility_key(
        identity,
        plan,
        reply,
        version=AgentCompatibilityKeyVersion.V2,
    )
    reservation = build_agent_outbound_reply_reservation_v2(identity)
    values = (scope, plan, receipt, entry, key, reservation)

    for value in values:
        assert "__dict__" not in dir(value)
        first_field = fields(type(value))[0].name
        with pytest.raises(FrozenInstanceError):
            setattr(value, first_field, getattr(value, first_field))
        rendered = repr(value)
        assert "private-provider-id" not in rendered
        assert str(identity.igreja_id) not in rendered
        assert identity.turn_id not in rendered
        if type(value) is AgentOutboundReplyReservationV2:
            assert value.effect_id not in rendered
            assert value.key not in rendered


@pytest.mark.parametrize("outcome", list(AgentEffectReceiptOutcome))
def test_receipt_binds_required_effect_material(
    outcome: AgentEffectReceiptOutcome,
) -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = plan.effect_intents[0]

    receipt = build_agent_effect_receipt(
        identity,
        plan,
        intent,
        outcome=outcome,
    )

    assert receipt.plan_digest == plan.plan_digest
    assert receipt.turn_id == identity.turn_id
    assert receipt.effect_id == intent.effect_id
    assert receipt.kind is intent.kind
    assert receipt.payload_digest == intent.payload_digest
    assert receipt.outcome is outcome


def test_receipt_same_material_replay_resolves_idempotently() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = plan.effect_intents[0]
    first = build_agent_effect_receipt(
        identity,
        plan,
        intent,
        outcome=AgentEffectReceiptOutcome.NOOP,
    )
    replay = build_agent_effect_receipt(
        identity,
        plan,
        intent,
        outcome=AgentEffectReceiptOutcome.NOOP,
    )

    resolved = reconcile_agent_effect_receipt_replay(
        identity,
        plan,
        intent,
        first,
        replay,
    )

    assert resolved is first
    assert replay == first


def test_duplicate_durable_receipt_rows_fail_closed_even_if_identical() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = plan.effect_intents[0]
    receipt = build_agent_effect_receipt(
        identity,
        plan,
        intent,
        outcome=AgentEffectReceiptOutcome.NOOP,
    )

    with pytest.raises(AgentEffectReceiptError) as exc_info:
        resolve_agent_effect_receipts(
            identity,
            plan,
            intent,
            (receipt, receipt),
        )

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.EFFECT_RECEIPT_CONFLICT,
    )


def test_receipt_and_v2_lookup_ids_stay_stable_across_material_conflict() -> None:
    identity = _identity()
    first_reply = _intent(
        identity,
        AgentEffectKind.OUTBOUND_REPLY,
        value="first-payload",
    )
    second_reply = _intent(
        identity,
        AgentEffectKind.OUTBOUND_REPLY,
        value="second-payload",
    )
    audit = _intent(identity, AgentEffectKind.AUDIT_EVENT, value="new-effect")
    first_plan = build_agent_turn_execution_plan(identity, (first_reply,))
    second_plan = build_agent_turn_execution_plan(
        identity,
        (second_reply, audit),
    )
    first_receipt = build_agent_effect_receipt(
        identity,
        first_plan,
        first_reply,
        outcome=AgentEffectReceiptOutcome.COMMITTED,
    )
    second_receipt = build_agent_effect_receipt(
        identity,
        second_plan,
        second_reply,
        outcome=AgentEffectReceiptOutcome.COMMITTED,
    )
    first_key = build_agent_effect_compatibility_key(
        identity,
        first_plan,
        first_reply,
        version=AgentCompatibilityKeyVersion.V2,
    )
    second_key = build_agent_effect_compatibility_key(
        identity,
        second_plan,
        second_reply,
        version=AgentCompatibilityKeyVersion.V2,
    )

    assert first_reply.effect_id == second_reply.effect_id
    assert first_reply.payload_digest != second_reply.payload_digest
    assert first_plan.plan_digest != second_plan.plan_digest
    assert first_receipt.receipt_id == second_receipt.receipt_id
    assert first_receipt.receipt_digest != second_receipt.receipt_digest
    assert first_key.key == second_key.key
    with pytest.raises(AgentEffectReceiptError) as exc_info:
        resolve_agent_effect_receipts(
            identity,
            second_plan,
            second_reply,
            (first_receipt,),
        )
    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.EFFECT_RECEIPT_CONFLICT,
    )


def test_absent_receipt_is_explicitly_unresolved() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = plan.effect_intents[0]

    assert resolve_agent_effect_receipts(identity, plan, intent, ()) is None


def test_conflicting_receipt_outcomes_fail_closed() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = plan.effect_intents[0]
    committed = build_agent_effect_receipt(
        identity,
        plan,
        intent,
        outcome=AgentEffectReceiptOutcome.COMMITTED,
    )
    rejected = build_agent_effect_receipt(
        identity,
        plan,
        intent,
        outcome=AgentEffectReceiptOutcome.REJECTED,
    )

    with pytest.raises(AgentEffectReceiptError) as exc_info:
        reconcile_agent_effect_receipt_replay(
            identity,
            plan,
            intent,
            committed,
            rejected,
        )

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.EFFECT_RECEIPT_CONFLICT,
    )


def test_receipt_from_other_effect_fails_closed() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    first, second = plan.effect_intents[:2]
    receipt = build_agent_effect_receipt(
        identity,
        plan,
        first,
        outcome=AgentEffectReceiptOutcome.NOOP,
    )

    with pytest.raises(AgentEffectReceiptError) as exc_info:
        resolve_agent_effect_receipts(identity, plan, second, (receipt,))

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.UNEXPECTED_EFFECT_RECEIPT,
    )


def test_receipt_from_other_tenant_plan_fails_closed() -> None:
    first_identity = _identity(igreja=40)
    second_identity = _identity(igreja=41)
    first_plan, _ = _plan_material(first_identity)
    second_plan, _ = _plan_material(second_identity)
    first_intent = first_plan.effect_intents[0]
    second_intent = second_plan.effect_intents[0]
    receipt = build_agent_effect_receipt(
        first_identity,
        first_plan,
        first_intent,
        outcome=AgentEffectReceiptOutcome.COMMITTED,
    )

    with pytest.raises(AgentEffectReceiptError):
        resolve_agent_effect_receipts(
            second_identity,
            second_plan,
            second_intent,
            (receipt,),
        )


def test_tampered_receipt_digest_is_rejected() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = plan.effect_intents[0]
    receipt = build_agent_effect_receipt(
        identity,
        plan,
        intent,
        outcome=AgentEffectReceiptOutcome.COMMITTED,
    )
    object.__setattr__(
        receipt,
        "receipt_digest",
        "agent_receipt_material_v1_" + "0" * 64,
    )

    with pytest.raises(AgentEffectReceiptError) as exc_info:
        resolve_agent_effect_receipts(identity, plan, intent, (receipt,))

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.INVALID_EFFECT_RECEIPT,
    )


def test_receipt_collection_limit_precedes_item_validation() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = plan.effect_intents[0]
    values = [object()] * (MAX_EFFECT_RECEIPTS_PER_RESOLUTION + 1)

    with pytest.raises(AgentEffectReceiptError) as exc_info:
        resolve_agent_effect_receipts(identity, plan, intent, values)

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.RECEIPT_COLLECTION_LIMIT_EXCEEDED,
    )


def test_reply_outbox_happy_path_ends_at_transport_accepted() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    pending = build_agent_reply_outbox_entry(identity, plan)

    in_transport = transition_agent_reply_outbox(
        identity,
        plan,
        pending,
        event=AgentReplyOutboxEvent.TRANSPORT_STARTED,
    )
    accepted = transition_agent_reply_outbox(
        identity,
        plan,
        in_transport,
        event=AgentReplyOutboxEvent.TRANSPORT_ACCEPTED,
    )

    assert pending.state is AgentReplyOutboxState.PENDING
    assert in_transport.state is AgentReplyOutboxState.IN_TRANSPORT
    assert accepted.state is AgentReplyOutboxState.ACCEPTED
    assert "DELIVERED" not in AgentReplyOutboxState.__members__
    assert "READ" not in AgentReplyOutboxState.__members__


def test_ambiguous_reply_is_terminal_without_automatic_retry() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    pending = build_agent_reply_outbox_entry(identity, plan)
    in_transport = transition_agent_reply_outbox(
        identity,
        plan,
        pending,
        event=AgentReplyOutboxEvent.TRANSPORT_STARTED,
    )
    ambiguous = transition_agent_reply_outbox(
        identity,
        plan,
        in_transport,
        event=AgentReplyOutboxEvent.TRANSPORT_OUTCOME_AMBIGUOUS,
    )

    for event in AgentReplyOutboxEvent:
        with pytest.raises(AgentReplyOutboxError) as exc_info:
            transition_agent_reply_outbox(
                identity,
                plan,
                ambiguous,
                event=event,
            )
        _assert_code(
            exc_info.value,
            AgentTurnExecutionErrorCode.AMBIGUOUS_REPLY_IS_TERMINAL,
        )


def test_proven_pre_send_failure_is_only_return_path_to_pending() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    pending = build_agent_reply_outbox_entry(identity, plan)
    in_transport = transition_agent_reply_outbox(
        identity,
        plan,
        pending,
        event=AgentReplyOutboxEvent.TRANSPORT_STARTED,
    )

    retryable = transition_agent_reply_outbox(
        identity,
        plan,
        in_transport,
        event=AgentReplyOutboxEvent.PRE_SEND_FAILURE_PROVEN,
    )

    assert retryable.state is AgentReplyOutboxState.PENDING


@pytest.mark.parametrize(
    "event",
    [
        AgentReplyOutboxEvent.TRANSPORT_ACCEPTED,
        AgentReplyOutboxEvent.TRANSPORT_OUTCOME_AMBIGUOUS,
        AgentReplyOutboxEvent.PRE_SEND_FAILURE_PROVEN,
    ],
)
def test_pending_rejects_every_event_except_transport_start(
    event: AgentReplyOutboxEvent,
) -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    pending = build_agent_reply_outbox_entry(identity, plan)

    with pytest.raises(AgentReplyOutboxError) as exc_info:
        transition_agent_reply_outbox(
            identity,
            plan,
            pending,
            event=event,
        )

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.INVALID_REPLY_OUTBOX_TRANSITION,
    )


def test_accepted_reply_is_terminal() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    entry = build_agent_reply_outbox_entry(identity, plan)
    entry = transition_agent_reply_outbox(
        identity,
        plan,
        entry,
        event=AgentReplyOutboxEvent.TRANSPORT_STARTED,
    )
    entry = transition_agent_reply_outbox(
        identity,
        plan,
        entry,
        event=AgentReplyOutboxEvent.TRANSPORT_ACCEPTED,
    )

    with pytest.raises(AgentReplyOutboxError) as exc_info:
        transition_agent_reply_outbox(
            identity,
            plan,
            entry,
            event=AgentReplyOutboxEvent.TRANSPORT_STARTED,
        )

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.ACCEPTED_REPLY_IS_TERMINAL,
    )


def _outbox_entry_at_state(
    identity: AgentTurnIdentity,
    plan: AgentTurnExecutionPlan,
    state: AgentReplyOutboxState,
) -> AgentReplyOutboxEntry:
    entry = build_agent_reply_outbox_entry(identity, plan)
    if state is AgentReplyOutboxState.PENDING:
        return entry
    entry = transition_agent_reply_outbox(
        identity,
        plan,
        entry,
        event=AgentReplyOutboxEvent.TRANSPORT_STARTED,
    )
    if state is AgentReplyOutboxState.IN_TRANSPORT:
        return entry
    event = AgentReplyOutboxEvent.TRANSPORT_ACCEPTED
    if state is AgentReplyOutboxState.AMBIGUOUS:
        event = AgentReplyOutboxEvent.TRANSPORT_OUTCOME_AMBIGUOUS
    return transition_agent_reply_outbox(
        identity,
        plan,
        entry,
        event=event,
    )


@pytest.mark.parametrize("state", list(AgentReplyOutboxState))
@pytest.mark.parametrize("event", list(AgentReplyOutboxEvent))
def test_reply_outbox_complete_state_event_matrix(
    state: AgentReplyOutboxState,
    event: AgentReplyOutboxEvent,
) -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    entry = _outbox_entry_at_state(identity, plan, state)
    expected = {
        (
            AgentReplyOutboxState.PENDING,
            AgentReplyOutboxEvent.TRANSPORT_STARTED,
        ): AgentReplyOutboxState.IN_TRANSPORT,
        (
            AgentReplyOutboxState.IN_TRANSPORT,
            AgentReplyOutboxEvent.TRANSPORT_ACCEPTED,
        ): AgentReplyOutboxState.ACCEPTED,
        (
            AgentReplyOutboxState.IN_TRANSPORT,
            AgentReplyOutboxEvent.TRANSPORT_OUTCOME_AMBIGUOUS,
        ): AgentReplyOutboxState.AMBIGUOUS,
        (
            AgentReplyOutboxState.IN_TRANSPORT,
            AgentReplyOutboxEvent.PRE_SEND_FAILURE_PROVEN,
        ): AgentReplyOutboxState.PENDING,
    }.get((state, event))

    if expected is not None:
        changed = transition_agent_reply_outbox(
            identity,
            plan,
            entry,
            event=event,
        )
        assert changed.state is expected
        return

    with pytest.raises(AgentReplyOutboxError) as exc_info:
        transition_agent_reply_outbox(
            identity,
            plan,
            entry,
            event=event,
        )
    if state is AgentReplyOutboxState.AMBIGUOUS:
        expected_code = AgentTurnExecutionErrorCode.AMBIGUOUS_REPLY_IS_TERMINAL
    elif state is AgentReplyOutboxState.ACCEPTED:
        expected_code = AgentTurnExecutionErrorCode.ACCEPTED_REPLY_IS_TERMINAL
    else:
        expected_code = AgentTurnExecutionErrorCode.INVALID_REPLY_OUTBOX_TRANSITION
    _assert_code(exc_info.value, expected_code)


def test_reply_outbox_requires_exactly_one_planned_reply() -> None:
    identity = _identity()
    no_reply = build_agent_turn_execution_plan(
        identity,
        (_intent(identity, AgentEffectKind.AUDIT_EVENT),),
    )

    with pytest.raises(AgentReplyOutboxError) as exc_info:
        build_agent_reply_outbox_entry(identity, no_reply)

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.REPLY_EFFECT_REQUIRED,
    )


def test_tampered_reply_outbox_entry_is_rejected() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    entry = build_agent_reply_outbox_entry(identity, plan)
    object.__setattr__(entry, "payload_digest", "agent_payload_v1_" + "0" * 64)

    with pytest.raises(AgentReplyOutboxError) as exc_info:
        transition_agent_reply_outbox(
            identity,
            plan,
            entry,
            event=AgentReplyOutboxEvent.TRANSPORT_STARTED,
        )

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.INVALID_REPLY_OUTBOX_ENTRY,
    )


def test_current_v2_compatibility_key_resolves_exactly() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = _reply_intent(plan)
    key = _compatibility_key(
        identity,
        plan,
        intent,
        AgentCompatibilityKeyVersion.V2,
    )

    resolution = resolve_agent_effect_compatibility_keys(
        identity,
        plan,
        intent,
        (key,),
    )

    assert resolution.selected_version is AgentCompatibilityKeyVersion.V2
    assert resolution.source is AgentCompatibilityKeySource.CURRENT_DERIVED
    assert resolution.selected_key == key.key


def test_pre_payload_reply_reservation_has_fixed_minimal_vector() -> None:
    identity = _identity()
    reservation = build_agent_outbound_reply_reservation_v2(identity)

    assert reservation.version is AgentCompatibilityKeyVersion.V2
    assert reservation.source is AgentCompatibilityKeySource.CURRENT_DERIVED
    assert reservation.kind is AgentEffectKind.OUTBOUND_REPLY
    assert reservation.turn_id == identity.turn_id
    assert reservation.effect_id == (
        "agent_effect_v1_"
        "0ceb8d4004baa60e1e66be2489e9224b39a61918c8228a10c1a0d06f18f6b190"
    )
    assert reservation.key == (
        "agent_effect_key_v2_"
        "75946f43b2aa862cd0cd0d5b5d9779736d5418a6e2dbcea3315c0d8b54b26ab9"
    )
    assert {item.name for item in fields(type(reservation))} == {
        "version",
        "source",
        "key",
        "turn_id",
        "effect_id",
        "kind",
    }
    assert not hasattr(reservation, "payload_digest")
    assert not hasattr(reservation, "plan_digest")


def test_pre_payload_reply_reservation_rejects_future_material() -> None:
    parameters = inspect.signature(
        build_agent_outbound_reply_reservation_v2
    ).parameters
    assert tuple(parameters) == ("identity",)

    with pytest.raises(TypeError):
        build_agent_outbound_reply_reservation_v2(  # type: ignore[call-arg]
            _identity(),
            claim_id="transient-claim",
        )


def test_pre_payload_key_equals_post_plan_v2_key_for_valid_plan_variants() -> None:
    identity = _identity()
    reservation = build_agent_outbound_reply_reservation_v2(identity)
    variants = (
        (
            _intent(
                identity,
                AgentEffectKind.OUTBOUND_REPLY,
                value="first-payload",
            ),
            (),
        ),
        (
            _intent(
                identity,
                AgentEffectKind.OUTBOUND_REPLY,
                value="changed-payload",
            ),
            (
                _intent(
                    identity,
                    AgentEffectKind.INTAKE_UPDATE,
                    value="intake",
                ),
                _intent(
                    identity,
                    AgentEffectKind.AUDIT_EVENT,
                    value="audit",
                ),
                _intent(
                    identity,
                    AgentEffectKind.TOOL_CALL,
                    value="tool",
                ),
            ),
        ),
    )

    for reply, other_intents in variants:
        plan = build_agent_turn_execution_plan(
            identity,
            (reply, *other_intents),
        )
        post_plan = build_agent_effect_compatibility_key(
            identity,
            plan,
            reply,
            version=AgentCompatibilityKeyVersion.V2,
        )

        assert reservation.effect_id == reply.effect_id
        assert reservation.key == post_plan.key


@pytest.mark.parametrize(
    "changed",
    [
        {"igreja": 2},
        {"conversation": 3},
        {"inbound": 4},
        {"provider_message_id": "evolution-message-002"},
    ],
)
def test_pre_payload_reply_reservation_separates_authoritative_turn_material(
    changed: dict[str, object],
) -> None:
    expected = build_agent_outbound_reply_reservation_v2(_identity())
    separated = build_agent_outbound_reply_reservation_v2(
        _identity(**changed)  # type: ignore[arg-type]
    )

    assert separated.turn_id != expected.turn_id
    assert separated.effect_id != expected.effect_id
    assert separated.key != expected.key


@pytest.mark.parametrize(
    ("attribute", "forged"),
    [
        ("turn_id", "agent_turn_v1_" + "0" * 64),
        ("provider", "other-provider"),
        ("provider_message_id", "x" * 513),
    ],
)
def test_pre_payload_reply_reservation_revalidates_full_identity(
    attribute: str,
    forged: object,
) -> None:
    identity = _identity()
    object.__setattr__(identity, attribute, forged)

    with pytest.raises(AgentTurnExecutionPlanError) as exc_info:
        build_agent_outbound_reply_reservation_v2(identity)

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.INVALID_EXPECTED_IDENTITY,
    )


@pytest.mark.parametrize(
    "version",
    [AgentCompatibilityKeyVersion.V1, AgentCompatibilityKeyVersion.V0],
)
def test_legacy_key_format_alone_remains_inconclusive(
    version: AgentCompatibilityKeyVersion,
) -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = _reply_intent(plan)
    key = _compatibility_key(identity, plan, intent, version)

    with pytest.raises(AgentCompatibilityKeyError) as exc_info:
        resolve_agent_effect_compatibility_keys(
            identity,
            plan,
            intent,
            (key,),
        )

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.COMPATIBILITY_KEY_INCONCLUSIVE,
    )


@pytest.mark.parametrize(
    "version",
    [AgentCompatibilityKeyVersion.V1, AgentCompatibilityKeyVersion.V0],
)
def test_legacy_key_evidence_is_reply_only(
    version: AgentCompatibilityKeyVersion,
) -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    tool = next(
        intent
        for intent in plan.effect_intents
        if intent.kind is AgentEffectKind.TOOL_CALL
    )

    with pytest.raises(AgentCompatibilityKeyError):
        _compatibility_key(identity, plan, tool, version)


@pytest.mark.parametrize(
    ("version", "observed"),
    [
        (AgentCompatibilityKeyVersion.V1, "agent-reply:" + "a" * 63),
        (AgentCompatibilityKeyVersion.V1, "agent-reply:" + "é" * 64),
        (AgentCompatibilityKeyVersion.V0, "agent-reply:" + "a" * 64),
        (
            AgentCompatibilityKeyVersion.V0,
            "agent-reply:" + "a" * 64 + ":" + "g" * 64,
        ),
        (AgentCompatibilityKeyVersion.V0, "agent-reply:" + "a" * 10_000_000),
    ],
)
def test_malformed_legacy_key_evidence_is_rejected_with_static_error(
    version: AgentCompatibilityKeyVersion,
    observed: str,
) -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = _reply_intent(plan)

    with pytest.raises(AgentCompatibilityKeyError) as exc_info:
        bind_agent_legacy_reply_key_evidence(
            identity,
            plan,
            intent,
            version=version,
            exact_observed_key=observed,
        )

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.INVALID_COMPATIBILITY_KEY,
    )


def test_multiple_compatibility_versions_are_inconclusive_without_preference() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = _reply_intent(plan)
    keys = tuple(
        _compatibility_key(identity, plan, intent, version)
        for version in AgentCompatibilityKeyVersion
    )

    with pytest.raises(AgentCompatibilityKeyError) as exc_info:
        resolve_agent_effect_compatibility_keys(
            identity,
            plan,
            intent,
            keys,
        )

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.COMPATIBILITY_KEY_INCONCLUSIVE,
    )


def test_compatibility_resolution_without_structural_key_is_inconclusive() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = _reply_intent(plan)

    with pytest.raises(AgentCompatibilityKeyError) as exc_info:
        resolve_agent_effect_compatibility_keys(identity, plan, intent, ())

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.COMPATIBILITY_KEY_INCONCLUSIVE,
    )


def test_duplicate_compatibility_version_is_inconclusive() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = _reply_intent(plan)
    key = _compatibility_key(
        identity,
        plan,
        intent,
        AgentCompatibilityKeyVersion.V2,
    )

    with pytest.raises(AgentCompatibilityKeyError) as exc_info:
        resolve_agent_effect_compatibility_keys(
            identity,
            plan,
            intent,
            (key, key),
        )

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.COMPATIBILITY_KEY_INCONCLUSIVE,
    )


def test_compatibility_key_for_other_effect_is_conflict() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    expected = _reply_intent(plan)
    non_reply = next(
        item
        for item in plan.effect_intents
        if item.kind is AgentEffectKind.TOOL_CALL
    )

    with pytest.raises(AgentCompatibilityKeyError):
        build_agent_effect_compatibility_key(
            identity,
            plan,
            non_reply,
            version=AgentCompatibilityKeyVersion.V2,
        )

    other_identity = _identity(inbound=99)
    other_reply = _intent(other_identity, AgentEffectKind.OUTBOUND_REPLY)
    other_plan = build_agent_turn_execution_plan(other_identity, (other_reply,))
    foreign = build_agent_effect_compatibility_key(
        other_identity,
        other_plan,
        other_reply,
        version=AgentCompatibilityKeyVersion.V2,
    )

    with pytest.raises(AgentCompatibilityKeyError) as exc_info:
        resolve_agent_effect_compatibility_keys(
            identity,
            plan,
            expected,
            (foreign,),
        )

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.COMPATIBILITY_KEY_CONFLICT,
    )


def test_compatibility_key_tampering_is_rejected() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = _reply_intent(plan)
    key = build_agent_effect_compatibility_key(
        identity,
        plan,
        intent,
        version=AgentCompatibilityKeyVersion.V2,
    )
    object.__setattr__(key, "key", "agent_effect_key_v2_" + "0" * 64)

    with pytest.raises(AgentCompatibilityKeyError) as exc_info:
        resolve_agent_effect_compatibility_keys(
            identity,
            plan,
            intent,
            (key,),
        )

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.INVALID_COMPATIBILITY_KEY,
    )


def test_compatibility_key_limit_precedes_item_validation() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = _reply_intent(plan)
    values = [object()] * (MAX_COMPATIBILITY_KEYS_PER_RESOLUTION + 1)

    with pytest.raises(AgentCompatibilityKeyError) as exc_info:
        resolve_agent_effect_compatibility_keys(
            identity,
            plan,
            intent,
            values,
        )

    _assert_code(
        exc_info.value,
        AgentTurnExecutionErrorCode.COMPATIBILITY_KEY_LIMIT_EXCEEDED,
    )


def test_compatibility_api_cannot_infer_from_text_or_time() -> None:
    functions = (
        bind_agent_legacy_reply_key_evidence,
        build_agent_effect_compatibility_key,
        build_agent_outbound_reply_reservation_v2,
        resolve_agent_effect_compatibility_keys,
    )
    forbidden = {
        "text",
        "message",
        "reply",
        "timestamp",
        "time",
        "phone",
        "content",
    }

    for function in functions:
        names = set(inspect.signature(function).parameters)
        assert names.isdisjoint(forbidden)


def test_cross_tenant_material_never_correlates() -> None:
    first_identity = _identity(igreja=50, conversation=51, inbound=52)
    second_identity = _identity(igreja=53, conversation=51, inbound=52)
    first_reply = _intent(
        first_identity,
        AgentEffectKind.OUTBOUND_REPLY,
        value="identical-low-entropy",
    )
    second_reply = _intent(
        second_identity,
        AgentEffectKind.OUTBOUND_REPLY,
        value="identical-low-entropy",
    )
    first_plan = build_agent_turn_execution_plan(first_identity, (first_reply,))
    second_plan = build_agent_turn_execution_plan(
        second_identity,
        (second_reply,),
    )
    first_receipt = build_agent_effect_receipt(
        first_identity,
        first_plan,
        first_reply,
        outcome=AgentEffectReceiptOutcome.COMMITTED,
    )
    second_receipt = build_agent_effect_receipt(
        second_identity,
        second_plan,
        second_reply,
        outcome=AgentEffectReceiptOutcome.COMMITTED,
    )
    first_key = build_agent_effect_compatibility_key(
        first_identity,
        first_plan,
        first_reply,
        version=AgentCompatibilityKeyVersion.V2,
    )
    second_key = build_agent_effect_compatibility_key(
        second_identity,
        second_plan,
        second_reply,
        version=AgentCompatibilityKeyVersion.V2,
    )

    assert first_plan.serial_scope.scope_id != second_plan.serial_scope.scope_id
    assert first_plan.plan_digest != second_plan.plan_digest
    assert first_receipt.receipt_id != second_receipt.receipt_id
    assert first_receipt.receipt_digest != second_receipt.receipt_digest
    assert first_key.key != second_key.key


def test_cross_process_vectors_are_deterministic() -> None:
    script = """
import json
import uuid
from app.agent.turn_execution import (
    AgentCompatibilityKeyVersion,
    AgentEffectReceiptOutcome,
    build_agent_effect_compatibility_key,
    build_agent_effect_receipt,
    build_agent_outbound_reply_reservation_v2,
    build_agent_reply_outbox_entry,
    build_agent_turn_execution_plan,
)
from app.agent.turn_identity import (
    AgentEffectKind,
    build_agent_effect_intent,
    build_agent_turn_identity,
)
identity = build_agent_turn_identity(
    igreja_id=uuid.UUID(int=101),
    conversation_id=uuid.UUID(int=102),
    inbound_message_id=uuid.UUID(int=103),
    provider_message_id="cross-process-evolution-id",
)
reservation = build_agent_outbound_reply_reservation_v2(identity)
reply = build_agent_effect_intent(
    identity,
    kind=AgentEffectKind.OUTBOUND_REPLY,
    ordinal=0,
    payload={"answer": "ok"},
)
audit = build_agent_effect_intent(
    identity,
    kind=AgentEffectKind.AUDIT_EVENT,
    ordinal=0,
    payload={"event": "planned"},
)
plan = build_agent_turn_execution_plan(identity, (reply, audit))
receipt = build_agent_effect_receipt(
    identity,
    plan,
    reply,
    outcome=AgentEffectReceiptOutcome.COMMITTED,
)
entry = build_agent_reply_outbox_entry(identity, plan)
key = build_agent_effect_compatibility_key(
    identity,
    plan,
    reply,
    version=AgentCompatibilityKeyVersion.V2,
)
print(json.dumps({
    "scope": plan.serial_scope.scope_id,
    "plan": plan.plan_digest,
    "receipt_id": receipt.receipt_id,
    "receipt_digest": receipt.receipt_digest,
    "entry": entry.entry_digest,
    "key": key.key,
    "reservation_effect": reservation.effect_id,
    "reservation_key": reservation.key,
}, sort_keys=True))
"""
    first_env = dict(os.environ)
    first_env["PYTHONHASHSEED"] = "1"
    first = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=first_env,
    ).stdout.strip()
    second_env = dict(os.environ)
    second_env["PYTHONHASHSEED"] = "987654321"
    second = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=second_env,
    ).stdout.strip()

    assert first == second
    assert json.loads(first) == {
        "entry": (
            "agent_reply_outbox_v1_"
            "282891532f94b946e1b86a081e9669178c3392e2a82f241fe9f794362511dd20"
        ),
        "key": (
            "agent_effect_key_v2_"
            "333b8ec19b83d04119f4d020578d96bcbbddd4e14a267fd56ae412600132a8ed"
        ),
        "plan": (
            "agent_plan_v1_"
            "174bb14f8b613555163b54640121ba4c978ff8ad0928551feba6fbcd1bfa48eb"
        ),
        "receipt_digest": (
            "agent_receipt_material_v1_"
            "0f3eb0db1461d5142d34e301ab0682061168e15da07930da6e7bc045fd4276f3"
        ),
        "receipt_id": (
            "agent_receipt_v1_"
            "8c34c47019ea0e8099fc9327dbd00b211ba571f316f8dd9bc931e9dc300b53c0"
        ),
        "reservation_effect": (
            "agent_effect_v1_"
            "98f15d6ffd45b8a850730934ab58ab36e4416fb89126f1177ade4fd9a6ca03ca"
        ),
        "reservation_key": (
            "agent_effect_key_v2_"
            "333b8ec19b83d04119f4d020578d96bcbbddd4e14a267fd56ae412600132a8ed"
        ),
        "scope": (
            "agent_serial_scope_v1_"
            "8899f1dbdd0b76c6e0d2ca3901dedf4676d7b251da6d5db1f0e4c0eb4a64d24b"
        ),
    }


def test_error_messages_and_reprs_do_not_echo_private_material() -> None:
    private = "private-evolution-id-person@example.test"
    identity = _identity(provider_message_id=private)
    plan, _ = _plan_material(identity)
    intent = plan.effect_intents[0]
    receipt = build_agent_effect_receipt(
        identity,
        plan,
        intent,
        outcome=AgentEffectReceiptOutcome.REJECTED,
    )
    object.__setattr__(receipt, "turn_id", "agent_turn_v1_" + "0" * 64)

    with pytest.raises(AgentEffectReceiptError) as exc_info:
        resolve_agent_effect_receipts(identity, plan, intent, (receipt,))

    rendered = f"{exc_info.value!s} {exc_info.value!r}"
    assert private not in rendered
    assert str(identity.igreja_id) not in rendered
    assert identity.turn_id not in rendered
    assert intent.effect_id not in rendered
    assert intent.payload_digest not in rendered


def _forged_string_values(expected: str) -> tuple[object, ...]:
    return (
        None,
        b"not-a-string",
        "é" * len(expected),
        "x" * 10_000_000,
    )


def test_forged_plan_fields_always_fail_with_static_contract_error() -> None:
    for attribute in ("turn_id", "plan_digest"):
        identity = _identity()
        clean, _ = _plan_material(identity)
        expected = getattr(clean, attribute)
        for forged in _forged_string_values(expected):
            plan, _ = _plan_material(identity)
            object.__setattr__(plan, attribute, forged)
            with pytest.raises(AgentTurnExecutionPlanError):
                validate_agent_turn_execution_plan(identity, plan)

    identity = _identity()
    clean, _ = _plan_material(identity)
    expected_scope = clean.serial_scope.scope_id
    for forged in _forged_string_values(expected_scope):
        plan, _ = _plan_material(identity)
        object.__setattr__(plan.serial_scope, "scope_id", forged)
        with pytest.raises(AgentTurnExecutionPlanError):
            validate_agent_turn_execution_plan(identity, plan)


def test_forged_receipt_fields_always_fail_with_static_contract_error() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = plan.effect_intents[0]
    clean = build_agent_effect_receipt(
        identity,
        plan,
        intent,
        outcome=AgentEffectReceiptOutcome.COMMITTED,
    )
    attributes = (
        "plan_digest",
        "turn_id",
        "effect_id",
        "payload_digest",
        "receipt_id",
        "receipt_digest",
    )
    for attribute in attributes:
        expected = getattr(clean, attribute)
        for forged in _forged_string_values(expected):
            receipt = build_agent_effect_receipt(
                identity,
                plan,
                intent,
                outcome=AgentEffectReceiptOutcome.COMMITTED,
            )
            object.__setattr__(receipt, attribute, forged)
            with pytest.raises(AgentEffectReceiptError):
                resolve_agent_effect_receipts(
                    identity,
                    plan,
                    intent,
                    (receipt,),
                )


def test_forged_outbox_fields_always_fail_with_static_contract_error() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    clean = build_agent_reply_outbox_entry(identity, plan)
    attributes = (
        "plan_digest",
        "turn_id",
        "effect_id",
        "payload_digest",
        "entry_digest",
    )
    for attribute in attributes:
        expected = getattr(clean, attribute)
        for forged in _forged_string_values(expected):
            entry = build_agent_reply_outbox_entry(identity, plan)
            object.__setattr__(entry, attribute, forged)
            with pytest.raises(AgentReplyOutboxError):
                transition_agent_reply_outbox(
                    identity,
                    plan,
                    entry,
                    event=AgentReplyOutboxEvent.TRANSPORT_STARTED,
                )


def test_forged_compatibility_fields_fail_with_static_contract_error() -> None:
    identity = _identity()
    plan, _ = _plan_material(identity)
    intent = _reply_intent(plan)
    clean = build_agent_effect_compatibility_key(
        identity,
        plan,
        intent,
        version=AgentCompatibilityKeyVersion.V2,
    )
    attributes = (
        "key",
        "plan_digest",
        "turn_id",
        "effect_id",
        "payload_digest",
    )
    for attribute in attributes:
        expected = getattr(clean, attribute)
        for forged in _forged_string_values(expected):
            key = build_agent_effect_compatibility_key(
                identity,
                plan,
                intent,
                version=AgentCompatibilityKeyVersion.V2,
            )
            object.__setattr__(key, attribute, forged)
            with pytest.raises(AgentCompatibilityKeyError):
                resolve_agent_effect_compatibility_keys(
                    identity,
                    plan,
                    intent,
                    (key,),
                )


def test_module_uses_only_stdlib_and_the_frozen_identity_contract() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
            imported_modules.add(node.module)

    assert imported_roots <= {
        "__future__",
        "dataclasses",
        "enum",
        "hashlib",
        "hmac",
        "typing",
        "app",
    }
    assert {
        module
        for module in imported_modules
        if module.startswith("app.")
    } == {"app.agent.turn_identity"}


def test_module_has_no_production_wiring() -> None:
    execution_consumers: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        if path == MODULE_PATH:
            continue
        source = path.read_text(encoding="utf-8")
        if "turn_execution" in source:
            execution_consumers.append(str(path.relative_to(BACKEND_ROOT)))

    assert sorted(execution_consumers) == [
        "app/agent/turn_plan_adapter.py",
        "app/services/cell_report_turn_uow.py",
        "app/services/cell_report_whatsapp_coordinator.py",
    ]

    adapter_consumers: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        if path == TURN_PLAN_ADAPTER_PATH:
            continue
        source = path.read_text(encoding="utf-8")
        if "turn_plan_adapter" in source:
            adapter_consumers.append(str(path.relative_to(BACKEND_ROOT)))

    assert adapter_consumers == ["app/services/cell_report_turn_uow.py"]


def test_module_documents_every_deferred_durable_boundary() -> None:
    source = " ".join(
        MODULE_PATH.read_text(encoding="utf-8").lower().split()
    )

    for marker in (
        "persist a plan",
        "trusted store",
        "serialize concurrent turns",
        "fifo",
        "atomic boundary",
        "no i/o",
        "not imported by the worker",
        "ambiguous",
        "transport/provider accepted",
    ):
        assert marker in source
