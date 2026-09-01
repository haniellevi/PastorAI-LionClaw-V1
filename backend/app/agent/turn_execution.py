"""Pure, inactive D3 contract for planning and recording turn effects.

This module has no authority and performs no I/O.  It is not imported by the
worker, runtime, graph, models, or persistence code.  It defines only immutable
values and deterministic validation needed before a future durable executor is
designed.

A complete plan is bound to one trusted :class:`AgentTurnIdentity` and to an
opaque conversation-serialization scope derived only from ``(igreja_id,
conversation_id)``.  Runtime claim or lease IDs are deliberately absent: they
must never change turn, effect, plan, receipt, scope, or compatibility identity.

The types below do not persist a plan or receipt, serialize concurrent turns,
provide FIFO execution, or create an atomic boundary between a domain commit
and an outbox update.  They also do not prove that a receipt came from a trusted
store.  A future adapter must load the expected identity and all durable
material inside the reviewed tenant transaction before calling these helpers.

``ACCEPTED`` means only that the transport/provider accepted a reply attempt.
It never means delivered or read.  ``AMBIGUOUS`` is terminal in this contract
and cannot be retried automatically.  Returning ``IN_TRANSPORT`` to ``PENDING``
requires independently proven pre-send failure; the enum value here records a
decision made by a future trusted transport adapter and is not itself proof.

Compatibility keys support an explicit ``v2``/``v1``/``v0`` lookup migration.
Only ``v2`` is derivable from this contract, using the stable ``effect_id``.
The pre-payload outbound reservation derives that same v2 key directly from
the fixed reply slot, before reply text or a plan exists.  It identifies only
that slot: it does not prove a durable row, an outbox entry, global
idempotency, provider acceptance, or a send.
The live ``v1`` formula includes the queue claim ID and the older ``v0`` form
also includes a response hash.  Both are outside stable turn identity, so this
module can only bind an exact key observed by a future trusted historical-row
adapter.  It cannot derive or authenticate that legacy evidence.  Resolution
requires exactly one structural candidate.  Message text, generated reply,
timestamps, proximity, phone number, and model output are not accepted as
matching evidence.

All hashes are deterministic opaque namespaces, not authenticators,
authorization, encryption, or tenant isolation.  ``repr=False`` reduces
accidental display only; future persistence and logs still need explicit safe
projections.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.agent.turn_identity import (
    MAX_EFFECT_INTENTS_PER_TURN,
    AgentEffectIntent,
    AgentEffectKind,
    AgentTurnContractError,
    AgentTurnIdentity,
    derive_agent_outbound_reply_effect_id,
    validate_agent_effect_intents,
)

TURN_EXECUTION_PLAN_VERSION: Final = "v1"
EFFECT_EXECUTION_ORDER_VERSION: Final = "v1"
CONVERSATION_SERIAL_SCOPE_VERSION: Final = "v1"
EFFECT_RECEIPT_VERSION: Final = "v1"
REPLY_OUTBOX_ENTRY_VERSION: Final = "v1"

MAX_EFFECT_RECEIPTS_PER_RESOLUTION: Final = 16
MAX_COMPATIBILITY_KEYS_PER_RESOLUTION: Final = 3

_PLAN_DOMAIN: Final = b"pastorai.agent.turn-execution-plan"
_SERIAL_SCOPE_DOMAIN: Final = b"pastorai.agent.conversation-serial-scope"
_RECEIPT_ID_DOMAIN: Final = b"pastorai.agent.effect-receipt-id"
_RECEIPT_DIGEST_DOMAIN: Final = b"pastorai.agent.effect-receipt-material"
_OUTBOX_ENTRY_DOMAIN: Final = b"pastorai.agent.reply-outbox-entry"
_COMPATIBILITY_KEY_DOMAIN: Final = b"pastorai.agent.effect-compatibility-key"

_PLAN_PREFIX: Final = f"agent_plan_{TURN_EXECUTION_PLAN_VERSION}_"
_SERIAL_SCOPE_PREFIX: Final = (
    f"agent_serial_scope_{CONVERSATION_SERIAL_SCOPE_VERSION}_"
)
_RECEIPT_ID_PREFIX: Final = f"agent_receipt_{EFFECT_RECEIPT_VERSION}_"
_RECEIPT_DIGEST_PREFIX: Final = (
    f"agent_receipt_material_{EFFECT_RECEIPT_VERSION}_"
)
_OUTBOX_ENTRY_PREFIX: Final = (
    f"agent_reply_outbox_{REPLY_OUTBOX_ENTRY_VERSION}_"
)
_LIVE_LEGACY_REPLY_PREFIX: Final = "agent-reply:"

_SINGLETON_EFFECT_KINDS: Final = frozenset(
    {
        AgentEffectKind.INTAKE_UPDATE,
        AgentEffectKind.APPLY_OPTOUT,
        AgentEffectKind.APPLY_CONSENT,
        AgentEffectKind.OUTBOUND_REPLY,
    }
)
_EFFECT_EXECUTION_ORDER: Final = {
    AgentEffectKind.INTAKE_UPDATE: 10,
    AgentEffectKind.APPLY_OPTOUT: 20,
    AgentEffectKind.APPLY_CONSENT: 30,
    AgentEffectKind.TOOL_CALL: 40,
    AgentEffectKind.AUDIT_EVENT: 50,
    AgentEffectKind.OUTBOUND_REPLY: 60,
}


class AgentEffectReceiptOutcome(str, Enum):
    """Closed structural outcomes for one durable effect execution."""

    COMMITTED = "committed"
    NOOP = "noop"
    REJECTED = "rejected"


class AgentReplyOutboxState(str, Enum):
    """Minimum delivery-neutral state vocabulary for a future reply outbox."""

    PENDING = "pending"
    IN_TRANSPORT = "in_transport"
    ACCEPTED = "accepted"
    AMBIGUOUS = "ambiguous"


class AgentReplyOutboxEvent(str, Enum):
    """Evidence classifications accepted by the pure transition function."""

    TRANSPORT_STARTED = "transport_started"
    TRANSPORT_ACCEPTED = "transport_accepted"
    TRANSPORT_OUTCOME_AMBIGUOUS = "transport_outcome_ambiguous"
    PRE_SEND_FAILURE_PROVEN = "pre_send_failure_proven"


class AgentCompatibilityKeyVersion(str, Enum):
    """Closed lookup order for a future idempotency-key migration."""

    V2 = "v2"
    V1 = "v1"
    V0 = "v0"


class AgentCompatibilityKeySource(str, Enum):
    """Whether a key is derivable now or exact external legacy evidence."""

    CURRENT_DERIVED = "current_derived"
    LEGACY_EXTERNAL_EVIDENCE = "legacy_external_evidence"


class AgentTurnExecutionErrorCode(str, Enum):
    """Sanitized fail-closed reasons; values never include caller material."""

    INVALID_EXPECTED_IDENTITY = "INVALID_EXPECTED_IDENTITY"
    INVALID_PLAN_COLLECTION = "INVALID_PLAN_COLLECTION"
    INVALID_EXECUTION_PLAN = "INVALID_EXECUTION_PLAN"
    EXECUTION_PLAN_CONFLICT = "EXECUTION_PLAN_CONFLICT"
    UNEXPECTED_PLAN_IDENTITY = "UNEXPECTED_PLAN_IDENTITY"
    SINGLETON_EFFECT_VIOLATION = "SINGLETON_EFFECT_VIOLATION"
    OUTBOUND_REPLY_VIOLATION = "OUTBOUND_REPLY_VIOLATION"
    INVALID_SERIAL_SCOPE = "INVALID_SERIAL_SCOPE"
    INVALID_EFFECT_INTENT = "INVALID_EFFECT_INTENT"
    EFFECT_NOT_IN_PLAN = "EFFECT_NOT_IN_PLAN"
    INVALID_RECEIPT_OUTCOME = "INVALID_RECEIPT_OUTCOME"
    INVALID_EFFECT_RECEIPT = "INVALID_EFFECT_RECEIPT"
    INVALID_RECEIPT_COLLECTION = "INVALID_RECEIPT_COLLECTION"
    RECEIPT_COLLECTION_LIMIT_EXCEEDED = (
        "RECEIPT_COLLECTION_LIMIT_EXCEEDED"
    )
    UNEXPECTED_EFFECT_RECEIPT = "UNEXPECTED_EFFECT_RECEIPT"
    EFFECT_RECEIPT_CONFLICT = "EFFECT_RECEIPT_CONFLICT"
    REPLY_EFFECT_REQUIRED = "REPLY_EFFECT_REQUIRED"
    INVALID_REPLY_OUTBOX_ENTRY = "INVALID_REPLY_OUTBOX_ENTRY"
    INVALID_REPLY_OUTBOX_STATE = "INVALID_REPLY_OUTBOX_STATE"
    INVALID_REPLY_OUTBOX_EVENT = "INVALID_REPLY_OUTBOX_EVENT"
    INVALID_REPLY_OUTBOX_TRANSITION = "INVALID_REPLY_OUTBOX_TRANSITION"
    AMBIGUOUS_REPLY_IS_TERMINAL = "AMBIGUOUS_REPLY_IS_TERMINAL"
    ACCEPTED_REPLY_IS_TERMINAL = "ACCEPTED_REPLY_IS_TERMINAL"
    INVALID_COMPATIBILITY_KEY_VERSION = (
        "INVALID_COMPATIBILITY_KEY_VERSION"
    )
    INVALID_COMPATIBILITY_KEY = "INVALID_COMPATIBILITY_KEY"
    INVALID_COMPATIBILITY_KEY_COLLECTION = (
        "INVALID_COMPATIBILITY_KEY_COLLECTION"
    )
    COMPATIBILITY_KEY_LIMIT_EXCEEDED = (
        "COMPATIBILITY_KEY_LIMIT_EXCEEDED"
    )
    COMPATIBILITY_KEY_INCONCLUSIVE = "COMPATIBILITY_KEY_INCONCLUSIVE"
    COMPATIBILITY_KEY_CONFLICT = "COMPATIBILITY_KEY_CONFLICT"


class AgentTurnExecutionError(ValueError):
    """Base error exposing only one static reason code."""

    def __init__(self, code: AgentTurnExecutionErrorCode) -> None:
        self.code = code
        super().__init__(f"agent turn execution rejected: {code.value}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


class AgentTurnExecutionPlanError(AgentTurnExecutionError):
    """The complete plan or its expected identity is invalid."""


class AgentEffectReceiptError(AgentTurnExecutionError):
    """A receipt is malformed, cross-effect, or conflicting."""


class AgentReplyOutboxError(AgentTurnExecutionError):
    """A reply outbox entry or transition fails closed."""


class AgentCompatibilityKeyError(AgentTurnExecutionError):
    """Legacy/current key evidence cannot be resolved unambiguously."""


def _binary_frame(*parts: bytes) -> bytes:
    if any(type(part) is not bytes for part in parts):
        raise TypeError("binary frame requires bytes")
    framed = bytearray(len(parts).to_bytes(4, "big"))
    for part in parts:
        framed.extend(len(part).to_bytes(4, "big"))
        framed.extend(part)
    return bytes(framed)


def _sha256_id(prefix: str, domain: bytes, version: str, *parts: bytes) -> str:
    material = _binary_frame(domain, version.encode("ascii"), *parts)
    return f"{prefix}{hashlib.sha256(material).hexdigest()}"


def _is_prefixed_sha256(value: object, prefix: str) -> bool:
    if (
        type(value) is not str
        or len(value) != len(prefix) + 64
        or not value.startswith(prefix)
    ):
        return False
    digest = value[len(prefix) :]
    return all(character in "0123456789abcdef" for character in digest)


def _safe_equal(value: object, expected: str) -> bool:
    """Bound type and work before constant-time comparison."""
    return (
        type(value) is str
        and len(value) == len(expected)
        and value.isascii()
        and hmac.compare_digest(value, expected)
    )


def _is_legacy_reply_key(
    value: object,
    version: AgentCompatibilityKeyVersion,
) -> bool:
    expected_length = len(_LIVE_LEGACY_REPLY_PREFIX) + 64
    if version is AgentCompatibilityKeyVersion.V0:
        expected_length += 65
    if (
        type(value) is not str
        or len(value) != expected_length
        or not value.startswith(_LIVE_LEGACY_REPLY_PREFIX)
    ):
        return False
    remainder = value[len(_LIVE_LEGACY_REPLY_PREFIX) :]
    parts = remainder.split(":")
    expected_parts = 1 if version is AgentCompatibilityKeyVersion.V1 else 2
    if len(parts) != expected_parts:
        return False
    return all(
        len(part) == 64
        and all(character in "0123456789abcdef" for character in part)
        for part in parts
    )


def _compatibility_key_prefix(version: AgentCompatibilityKeyVersion) -> str:
    return f"agent_effect_key_{version.value}_"


def _require_expected_identity(value: object) -> AgentTurnIdentity:
    if type(value) is not AgentTurnIdentity:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_EXPECTED_IDENTITY
        )
    try:
        validate_agent_effect_intents(value, ())
    except AgentTurnContractError:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_EXPECTED_IDENTITY
        ) from None
    return value


def _require_effect_intent_for_identity(
    identity: AgentTurnIdentity,
    value: object,
) -> AgentEffectIntent:
    try:
        validated = validate_agent_effect_intents(identity, (value,))
    except AgentTurnContractError:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_EFFECT_INTENT
        ) from None
    return validated[0]


def _derive_serial_scope_id(identity: AgentTurnIdentity) -> str:
    return _sha256_id(
        _SERIAL_SCOPE_PREFIX,
        _SERIAL_SCOPE_DOMAIN,
        CONVERSATION_SERIAL_SCOPE_VERSION,
        identity.igreja_id.bytes,
        identity.conversation_id.bytes,
    )


@dataclass(frozen=True, slots=True, repr=False, init=False)
class AgentConversationSerialScope:
    """Opaque serialization scope for exactly one tenant conversation."""

    scope_id: str

    def __repr__(self) -> str:
        return (
            "AgentConversationSerialScope("
            f"version={CONVERSATION_SERIAL_SCOPE_VERSION!r})"
        )


def _mint_serial_scope(scope_id: str) -> AgentConversationSerialScope:
    scope = object.__new__(AgentConversationSerialScope)
    object.__setattr__(scope, "scope_id", scope_id)
    return scope


def build_agent_conversation_serial_scope(
    identity: AgentTurnIdentity | object,
) -> AgentConversationSerialScope:
    """Derive scope without accepting any runtime claim or lease material."""
    expected_identity = _require_expected_identity(identity)
    return _mint_serial_scope(_derive_serial_scope_id(expected_identity))


def _require_serial_scope(
    identity: AgentTurnIdentity,
    value: object,
) -> AgentConversationSerialScope:
    if type(value) is not AgentConversationSerialScope:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_SERIAL_SCOPE
        )
    try:
        scope_id = value.scope_id
    except AttributeError:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_SERIAL_SCOPE
        ) from None
    expected = _derive_serial_scope_id(identity)
    if (
        not _is_prefixed_sha256(scope_id, _SERIAL_SCOPE_PREFIX)
        or not _safe_equal(scope_id, expected)
    ):
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_SERIAL_SCOPE
        )
    return value


def _canonical_effect_order(intent: AgentEffectIntent) -> tuple[int, int, str]:
    """Return the closed execution order; outbound reply is always last."""
    try:
        phase = _EFFECT_EXECUTION_ORDER[intent.kind]
    except KeyError:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_EFFECT_INTENT
        ) from None
    return (phase, intent.ordinal, intent.effect_id)


def _effect_plan_frame(intent: AgentEffectIntent) -> bytes:
    return _binary_frame(
        intent.turn_id.encode("ascii"),
        intent.kind.value.encode("ascii"),
        intent.semantic_slot.value.encode("ascii"),
        intent.ordinal.to_bytes(8, "big", signed=False),
        intent.effect_id.encode("ascii"),
        intent.payload_digest.encode("ascii"),
    )


def _derive_plan_digest(
    *,
    turn_id: str,
    serial_scope_id: str,
    effect_intents: tuple[AgentEffectIntent, ...],
) -> str:
    effect_frames = tuple(_effect_plan_frame(intent) for intent in effect_intents)
    return _sha256_id(
        _PLAN_PREFIX,
        _PLAN_DOMAIN,
        TURN_EXECUTION_PLAN_VERSION,
        EFFECT_EXECUTION_ORDER_VERSION.encode("ascii"),
        turn_id.encode("ascii"),
        serial_scope_id.encode("ascii"),
        len(effect_intents).to_bytes(4, "big"),
        *effect_frames,
    )


def _validate_plan_semantics(
    effect_intents: tuple[AgentEffectIntent, ...],
) -> None:
    singleton_counts = {kind: 0 for kind in _SINGLETON_EFFECT_KINDS}
    outbound_count = 0
    for intent in effect_intents:
        if intent.kind in _SINGLETON_EFFECT_KINDS:
            singleton_counts[intent.kind] += 1
            if intent.ordinal != 0 or singleton_counts[intent.kind] > 1:
                code = AgentTurnExecutionErrorCode.SINGLETON_EFFECT_VIOLATION
                if intent.kind is AgentEffectKind.OUTBOUND_REPLY:
                    code = AgentTurnExecutionErrorCode.OUTBOUND_REPLY_VIOLATION
                raise AgentTurnExecutionPlanError(code)
        if intent.kind is AgentEffectKind.OUTBOUND_REPLY:
            outbound_count += 1
    if outbound_count > 1:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.OUTBOUND_REPLY_VIOLATION
        )


@dataclass(frozen=True, slots=True, repr=False, init=False)
class AgentTurnExecutionPlan:
    """Complete immutable plan in explicit versioned execution order."""

    turn_id: str
    serial_scope: AgentConversationSerialScope
    effect_intents: tuple[AgentEffectIntent, ...]
    plan_digest: str

    def __repr__(self) -> str:
        return (
            "AgentTurnExecutionPlan("
            f"version={TURN_EXECUTION_PLAN_VERSION!r}, "
            f"effect_count={len(self.effect_intents)})"
        )


def _mint_execution_plan(
    *,
    turn_id: str,
    serial_scope: AgentConversationSerialScope,
    effect_intents: tuple[AgentEffectIntent, ...],
    plan_digest: str,
) -> AgentTurnExecutionPlan:
    plan = object.__new__(AgentTurnExecutionPlan)
    object.__setattr__(plan, "turn_id", turn_id)
    object.__setattr__(plan, "serial_scope", serial_scope)
    object.__setattr__(plan, "effect_intents", effect_intents)
    object.__setattr__(plan, "plan_digest", plan_digest)
    return plan


def build_agent_turn_execution_plan(
    identity: AgentTurnIdentity | object,
    values: list[AgentEffectIntent] | tuple[AgentEffectIntent, ...] | object,
) -> AgentTurnExecutionPlan:
    """Build a canonical plan whose digest is independent of input list order."""
    expected_identity = _require_expected_identity(identity)
    if type(values) not in {list, tuple}:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_PLAN_COLLECTION
        )
    if len(values) > MAX_EFFECT_INTENTS_PER_TURN:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_PLAN_COLLECTION
        )
    try:
        validated = validate_agent_effect_intents(expected_identity, values)
    except AgentTurnContractError:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_PLAN_COLLECTION
        ) from None
    canonical = tuple(sorted(validated, key=_canonical_effect_order))
    _validate_plan_semantics(canonical)
    serial_scope = build_agent_conversation_serial_scope(expected_identity)
    plan_digest = _derive_plan_digest(
        turn_id=expected_identity.turn_id,
        serial_scope_id=serial_scope.scope_id,
        effect_intents=canonical,
    )
    return _mint_execution_plan(
        turn_id=expected_identity.turn_id,
        serial_scope=serial_scope,
        effect_intents=canonical,
        plan_digest=plan_digest,
    )


def validate_agent_turn_execution_plan(
    identity: AgentTurnIdentity | object,
    value: object,
) -> AgentTurnExecutionPlan:
    """Rebuild and bind an untrusted structural plan to expected identity."""
    expected_identity = _require_expected_identity(identity)
    if type(value) is not AgentTurnExecutionPlan:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_EXECUTION_PLAN
        )
    try:
        turn_id = value.turn_id
        serial_scope = value.serial_scope
        effect_intents = value.effect_intents
        plan_digest = value.plan_digest
    except AttributeError:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_EXECUTION_PLAN
        ) from None
    if type(effect_intents) is not tuple:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_EXECUTION_PLAN
        )
    if not _safe_equal(turn_id, expected_identity.turn_id):
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.UNEXPECTED_PLAN_IDENTITY
        )
    _require_serial_scope(expected_identity, serial_scope)
    rebuilt = build_agent_turn_execution_plan(expected_identity, effect_intents)
    if (
        not _is_prefixed_sha256(plan_digest, _PLAN_PREFIX)
        or not _safe_equal(plan_digest, rebuilt.plan_digest)
        or rebuilt.effect_intents != effect_intents
    ):
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_EXECUTION_PLAN
        )
    return value


def resolve_agent_turn_execution_plans(
    identity: AgentTurnIdentity | object,
    values: list[AgentTurnExecutionPlan] | tuple[AgentTurnExecutionPlan, ...] | object,
) -> AgentTurnExecutionPlan | None:
    """Resolve zero or one durable plan row; duplicate rows fail closed."""
    expected_identity = _require_expected_identity(identity)
    if type(values) not in {list, tuple}:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.INVALID_PLAN_COLLECTION
        )
    if not values:
        return None
    if len(values) != 1:
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.EXECUTION_PLAN_CONFLICT
        )
    return validate_agent_turn_execution_plan(expected_identity, values[0])


def reconcile_agent_turn_execution_plan(
    identity: AgentTurnIdentity | object,
    existing: AgentTurnExecutionPlan | object,
    replay: AgentTurnExecutionPlan | object,
) -> AgentTurnExecutionPlan:
    """Accept exact plan replay or reject changed material for the turn."""
    expected_identity = _require_expected_identity(identity)
    first = validate_agent_turn_execution_plan(expected_identity, existing)
    second = validate_agent_turn_execution_plan(expected_identity, replay)
    if (
        not _safe_equal(second.turn_id, first.turn_id)
        or not _safe_equal(second.plan_digest, first.plan_digest)
        or not _safe_equal(
            second.serial_scope.scope_id,
            first.serial_scope.scope_id,
        )
        or second.effect_intents != first.effect_intents
    ):
        raise AgentTurnExecutionPlanError(
            AgentTurnExecutionErrorCode.EXECUTION_PLAN_CONFLICT
        )
    return first


def _require_plan_effect(
    identity: AgentTurnIdentity,
    plan: AgentTurnExecutionPlan,
    value: object,
) -> AgentEffectIntent:
    intent = _require_effect_intent_for_identity(identity, value)
    for planned in plan.effect_intents:
        if hmac.compare_digest(planned.effect_id, intent.effect_id):
            if planned == intent:
                return intent
            break
    raise AgentTurnExecutionPlanError(
        AgentTurnExecutionErrorCode.EFFECT_NOT_IN_PLAN
    )


def _require_receipt_outcome(value: object) -> AgentEffectReceiptOutcome:
    if type(value) is not AgentEffectReceiptOutcome:
        raise AgentEffectReceiptError(
            AgentTurnExecutionErrorCode.INVALID_RECEIPT_OUTCOME
        )
    return value


def _derive_receipt_id(effect_id: str) -> str:
    return _sha256_id(
        _RECEIPT_ID_PREFIX,
        _RECEIPT_ID_DOMAIN,
        EFFECT_RECEIPT_VERSION,
        effect_id.encode("ascii"),
    )


def _derive_receipt_digest(
    *,
    receipt_id: str,
    plan_digest: str,
    intent: AgentEffectIntent,
    outcome: AgentEffectReceiptOutcome,
) -> str:
    return _sha256_id(
        _RECEIPT_DIGEST_PREFIX,
        _RECEIPT_DIGEST_DOMAIN,
        EFFECT_RECEIPT_VERSION,
        receipt_id.encode("ascii"),
        plan_digest.encode("ascii"),
        intent.turn_id.encode("ascii"),
        intent.effect_id.encode("ascii"),
        intent.kind.value.encode("ascii"),
        intent.payload_digest.encode("ascii"),
        outcome.value.encode("ascii"),
    )


@dataclass(frozen=True, slots=True, repr=False, init=False)
class AgentEffectReceipt:
    """Structural terminal result for exactly one planned effect."""

    plan_digest: str
    turn_id: str
    effect_id: str
    kind: AgentEffectKind
    payload_digest: str
    outcome: AgentEffectReceiptOutcome
    receipt_id: str
    receipt_digest: str

    def __repr__(self) -> str:
        return (
            "AgentEffectReceipt("
            f"version={EFFECT_RECEIPT_VERSION!r}, "
            f"outcome={self.outcome.value!r})"
        )


def _mint_effect_receipt(
    *,
    plan_digest: str,
    intent: AgentEffectIntent,
    outcome: AgentEffectReceiptOutcome,
    receipt_id: str,
    receipt_digest: str,
) -> AgentEffectReceipt:
    receipt = object.__new__(AgentEffectReceipt)
    object.__setattr__(receipt, "plan_digest", plan_digest)
    object.__setattr__(receipt, "turn_id", intent.turn_id)
    object.__setattr__(receipt, "effect_id", intent.effect_id)
    object.__setattr__(receipt, "kind", intent.kind)
    object.__setattr__(receipt, "payload_digest", intent.payload_digest)
    object.__setattr__(receipt, "outcome", outcome)
    object.__setattr__(receipt, "receipt_id", receipt_id)
    object.__setattr__(receipt, "receipt_digest", receipt_digest)
    return receipt


def build_agent_effect_receipt(
    identity: AgentTurnIdentity | object,
    plan: AgentTurnExecutionPlan | object,
    intent: AgentEffectIntent | object,
    *,
    outcome: AgentEffectReceiptOutcome,
) -> AgentEffectReceipt:
    """Build one terminal receipt without writing or asserting provenance."""
    expected_identity = _require_expected_identity(identity)
    expected_plan = validate_agent_turn_execution_plan(expected_identity, plan)
    expected_intent = _require_plan_effect(
        expected_identity,
        expected_plan,
        intent,
    )
    exact_outcome = _require_receipt_outcome(outcome)
    receipt_id = _derive_receipt_id(expected_intent.effect_id)
    receipt_digest = _derive_receipt_digest(
        receipt_id=receipt_id,
        plan_digest=expected_plan.plan_digest,
        intent=expected_intent,
        outcome=exact_outcome,
    )
    return _mint_effect_receipt(
        plan_digest=expected_plan.plan_digest,
        intent=expected_intent,
        outcome=exact_outcome,
        receipt_id=receipt_id,
        receipt_digest=receipt_digest,
    )


def _validate_effect_receipt(
    identity: AgentTurnIdentity,
    plan: AgentTurnExecutionPlan,
    intent: AgentEffectIntent,
    value: object,
) -> AgentEffectReceipt:
    if type(value) is not AgentEffectReceipt:
        raise AgentEffectReceiptError(
            AgentTurnExecutionErrorCode.INVALID_EFFECT_RECEIPT
        )
    try:
        plan_digest = value.plan_digest
        turn_id = value.turn_id
        effect_id = value.effect_id
        kind = value.kind
        payload_digest = value.payload_digest
        outcome = value.outcome
        receipt_id = value.receipt_id
        receipt_digest = value.receipt_digest
    except AttributeError:
        raise AgentEffectReceiptError(
            AgentTurnExecutionErrorCode.INVALID_EFFECT_RECEIPT
        ) from None
    exact_outcome = _require_receipt_outcome(outcome)
    expected_id = _derive_receipt_id(intent.effect_id)
    if not _is_prefixed_sha256(receipt_id, _RECEIPT_ID_PREFIX):
        raise AgentEffectReceiptError(
            AgentTurnExecutionErrorCode.INVALID_EFFECT_RECEIPT
        )
    if not _safe_equal(receipt_id, expected_id):
        raise AgentEffectReceiptError(
            AgentTurnExecutionErrorCode.UNEXPECTED_EFFECT_RECEIPT
        )
    if (
        not _safe_equal(plan_digest, plan.plan_digest)
        or not _safe_equal(turn_id, identity.turn_id)
        or not _safe_equal(effect_id, intent.effect_id)
        or kind is not intent.kind
        or not _safe_equal(payload_digest, intent.payload_digest)
    ):
        raise AgentEffectReceiptError(
            AgentTurnExecutionErrorCode.EFFECT_RECEIPT_CONFLICT
        )
    expected_digest = _derive_receipt_digest(
        receipt_id=expected_id,
        plan_digest=plan.plan_digest,
        intent=intent,
        outcome=exact_outcome,
    )
    if (
        not _is_prefixed_sha256(
            receipt_digest,
            _RECEIPT_DIGEST_PREFIX,
        )
        or not _safe_equal(receipt_digest, expected_digest)
    ):
        raise AgentEffectReceiptError(
            AgentTurnExecutionErrorCode.INVALID_EFFECT_RECEIPT
        )
    return value


def resolve_agent_effect_receipts(
    identity: AgentTurnIdentity | object,
    plan: AgentTurnExecutionPlan | object,
    intent: AgentEffectIntent | object,
    values: list[AgentEffectReceipt] | tuple[AgentEffectReceipt, ...] | object,
) -> AgentEffectReceipt | None:
    """Resolve exact replay or reject conflicting durable receipt material."""
    expected_identity = _require_expected_identity(identity)
    expected_plan = validate_agent_turn_execution_plan(expected_identity, plan)
    expected_intent = _require_plan_effect(
        expected_identity,
        expected_plan,
        intent,
    )
    if type(values) not in {list, tuple}:
        raise AgentEffectReceiptError(
            AgentTurnExecutionErrorCode.INVALID_RECEIPT_COLLECTION
        )
    if len(values) > MAX_EFFECT_RECEIPTS_PER_RESOLUTION:
        raise AgentEffectReceiptError(
            AgentTurnExecutionErrorCode.RECEIPT_COLLECTION_LIMIT_EXCEEDED
        )
    if len(values) > 1:
        raise AgentEffectReceiptError(
            AgentTurnExecutionErrorCode.EFFECT_RECEIPT_CONFLICT
        )
    resolved: AgentEffectReceipt | None = None
    for value in values:
        current = _validate_effect_receipt(
            expected_identity,
            expected_plan,
            expected_intent,
            value,
        )
        resolved = current
    return resolved


def reconcile_agent_effect_receipt_replay(
    identity: AgentTurnIdentity | object,
    plan: AgentTurnExecutionPlan | object,
    intent: AgentEffectIntent | object,
    existing: AgentEffectReceipt | object,
    replay: AgentEffectReceipt | object,
) -> AgentEffectReceipt:
    """Accept exact replay material or reject every divergence."""
    expected_identity = _require_expected_identity(identity)
    expected_plan = validate_agent_turn_execution_plan(expected_identity, plan)
    expected_intent = _require_plan_effect(
        expected_identity,
        expected_plan,
        intent,
    )
    first = _validate_effect_receipt(
        expected_identity,
        expected_plan,
        expected_intent,
        existing,
    )
    second = _validate_effect_receipt(
        expected_identity,
        expected_plan,
        expected_intent,
        replay,
    )
    if (
        first.outcome is not second.outcome
        or not _safe_equal(second.receipt_id, first.receipt_id)
        or not _safe_equal(second.receipt_digest, first.receipt_digest)
    ):
        raise AgentEffectReceiptError(
            AgentTurnExecutionErrorCode.EFFECT_RECEIPT_CONFLICT
        )
    return first


def _reply_intent_from_plan(plan: AgentTurnExecutionPlan) -> AgentEffectIntent:
    replies = tuple(
        intent
        for intent in plan.effect_intents
        if intent.kind is AgentEffectKind.OUTBOUND_REPLY
    )
    if len(replies) != 1 or replies[0].ordinal != 0:
        raise AgentReplyOutboxError(
            AgentTurnExecutionErrorCode.REPLY_EFFECT_REQUIRED
        )
    return replies[0]


def _require_reply_outbox_state(value: object) -> AgentReplyOutboxState:
    if type(value) is not AgentReplyOutboxState:
        raise AgentReplyOutboxError(
            AgentTurnExecutionErrorCode.INVALID_REPLY_OUTBOX_STATE
        )
    return value


def _require_reply_outbox_event(value: object) -> AgentReplyOutboxEvent:
    if type(value) is not AgentReplyOutboxEvent:
        raise AgentReplyOutboxError(
            AgentTurnExecutionErrorCode.INVALID_REPLY_OUTBOX_EVENT
        )
    return value


def _derive_reply_outbox_entry_digest(
    *,
    plan_digest: str,
    intent: AgentEffectIntent,
    state: AgentReplyOutboxState,
) -> str:
    return _sha256_id(
        _OUTBOX_ENTRY_PREFIX,
        _OUTBOX_ENTRY_DOMAIN,
        REPLY_OUTBOX_ENTRY_VERSION,
        plan_digest.encode("ascii"),
        intent.turn_id.encode("ascii"),
        intent.effect_id.encode("ascii"),
        intent.kind.value.encode("ascii"),
        intent.payload_digest.encode("ascii"),
        state.value.encode("ascii"),
    )


@dataclass(frozen=True, slots=True, repr=False, init=False)
class AgentReplyOutboxEntry:
    """Pure structural state for the plan's sole outbound reply effect."""

    plan_digest: str
    turn_id: str
    effect_id: str
    kind: AgentEffectKind
    payload_digest: str
    state: AgentReplyOutboxState
    entry_digest: str

    def __repr__(self) -> str:
        return (
            "AgentReplyOutboxEntry("
            f"version={REPLY_OUTBOX_ENTRY_VERSION!r}, "
            f"state={self.state.value!r})"
        )


def _mint_reply_outbox_entry(
    *,
    plan_digest: str,
    intent: AgentEffectIntent,
    state: AgentReplyOutboxState,
) -> AgentReplyOutboxEntry:
    entry = object.__new__(AgentReplyOutboxEntry)
    object.__setattr__(entry, "plan_digest", plan_digest)
    object.__setattr__(entry, "turn_id", intent.turn_id)
    object.__setattr__(entry, "effect_id", intent.effect_id)
    object.__setattr__(entry, "kind", intent.kind)
    object.__setattr__(entry, "payload_digest", intent.payload_digest)
    object.__setattr__(entry, "state", state)
    object.__setattr__(
        entry,
        "entry_digest",
        _derive_reply_outbox_entry_digest(
            plan_digest=plan_digest,
            intent=intent,
            state=state,
        ),
    )
    return entry


def build_agent_reply_outbox_entry(
    identity: AgentTurnIdentity | object,
    plan: AgentTurnExecutionPlan | object,
) -> AgentReplyOutboxEntry:
    """Build the initial PENDING state without enqueueing or sending."""
    expected_identity = _require_expected_identity(identity)
    expected_plan = validate_agent_turn_execution_plan(expected_identity, plan)
    reply = _reply_intent_from_plan(expected_plan)
    return _mint_reply_outbox_entry(
        plan_digest=expected_plan.plan_digest,
        intent=reply,
        state=AgentReplyOutboxState.PENDING,
    )


def _validate_reply_outbox_entry(
    identity: AgentTurnIdentity,
    plan: AgentTurnExecutionPlan,
    value: object,
) -> AgentReplyOutboxEntry:
    if type(value) is not AgentReplyOutboxEntry:
        raise AgentReplyOutboxError(
            AgentTurnExecutionErrorCode.INVALID_REPLY_OUTBOX_ENTRY
        )
    reply = _reply_intent_from_plan(plan)
    try:
        plan_digest = value.plan_digest
        turn_id = value.turn_id
        effect_id = value.effect_id
        kind = value.kind
        payload_digest = value.payload_digest
        state = value.state
        entry_digest = value.entry_digest
    except AttributeError:
        raise AgentReplyOutboxError(
            AgentTurnExecutionErrorCode.INVALID_REPLY_OUTBOX_ENTRY
        ) from None
    exact_state = _require_reply_outbox_state(state)
    expected_digest = _derive_reply_outbox_entry_digest(
        plan_digest=plan.plan_digest,
        intent=reply,
        state=exact_state,
    )
    if (
        not _safe_equal(plan_digest, plan.plan_digest)
        or not _safe_equal(turn_id, identity.turn_id)
        or not _safe_equal(effect_id, reply.effect_id)
        or kind is not AgentEffectKind.OUTBOUND_REPLY
        or not _safe_equal(payload_digest, reply.payload_digest)
        or not _is_prefixed_sha256(entry_digest, _OUTBOX_ENTRY_PREFIX)
        or not _safe_equal(entry_digest, expected_digest)
    ):
        raise AgentReplyOutboxError(
            AgentTurnExecutionErrorCode.INVALID_REPLY_OUTBOX_ENTRY
        )
    return value


def transition_agent_reply_outbox(
    identity: AgentTurnIdentity | object,
    plan: AgentTurnExecutionPlan | object,
    entry: AgentReplyOutboxEntry | object,
    *,
    event: AgentReplyOutboxEvent,
) -> AgentReplyOutboxEntry:
    """Apply one allowed state transition; no retry is scheduled here."""
    expected_identity = _require_expected_identity(identity)
    expected_plan = validate_agent_turn_execution_plan(expected_identity, plan)
    current = _validate_reply_outbox_entry(
        expected_identity,
        expected_plan,
        entry,
    )
    exact_event = _require_reply_outbox_event(event)
    if current.state is AgentReplyOutboxState.AMBIGUOUS:
        raise AgentReplyOutboxError(
            AgentTurnExecutionErrorCode.AMBIGUOUS_REPLY_IS_TERMINAL
        )
    if current.state is AgentReplyOutboxState.ACCEPTED:
        raise AgentReplyOutboxError(
            AgentTurnExecutionErrorCode.ACCEPTED_REPLY_IS_TERMINAL
        )
    transitions = {
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
    }
    next_state = transitions.get((current.state, exact_event))
    if next_state is None:
        raise AgentReplyOutboxError(
            AgentTurnExecutionErrorCode.INVALID_REPLY_OUTBOX_TRANSITION
        )
    return _mint_reply_outbox_entry(
        plan_digest=expected_plan.plan_digest,
        intent=_reply_intent_from_plan(expected_plan),
        state=next_state,
    )


def _require_compatibility_key_version(
    value: object,
) -> AgentCompatibilityKeyVersion:
    if type(value) is not AgentCompatibilityKeyVersion:
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.INVALID_COMPATIBILITY_KEY_VERSION
        )
    return value


def _derive_v2_compatibility_key_from_effect_id(effect_id: str) -> str:
    return _sha256_id(
        _compatibility_key_prefix(AgentCompatibilityKeyVersion.V2),
        _COMPATIBILITY_KEY_DOMAIN,
        AgentCompatibilityKeyVersion.V2.value,
        effect_id.encode("ascii"),
    )


def _derive_v2_compatibility_key(intent: AgentEffectIntent) -> str:
    return _derive_v2_compatibility_key_from_effect_id(intent.effect_id)


@dataclass(frozen=True, slots=True, repr=False, init=False)
class AgentOutboundReplyReservationV2:
    """Pre-payload identity for the sole outbound-reply reservation slot.

    The value intentionally has no payload or plan digest.  It identifies the
    compatibility namespace that a future trusted adapter may use while
    reserving durable state, but it does not prove that any row or outbox entry
    exists, provide global idempotency, authorize transport, or prove a send.
    """

    version: AgentCompatibilityKeyVersion
    source: AgentCompatibilityKeySource
    key: str
    turn_id: str
    effect_id: str
    kind: AgentEffectKind

    def __repr__(self) -> str:
        return (
            "AgentOutboundReplyReservationV2("
            f"version={self.version.value!r}, source={self.source.value!r})"
        )


def _mint_outbound_reply_reservation_v2(
    *,
    turn_id: str,
    effect_id: str,
    key: str,
) -> AgentOutboundReplyReservationV2:
    value = object.__new__(AgentOutboundReplyReservationV2)
    object.__setattr__(
        value,
        "version",
        AgentCompatibilityKeyVersion.V2,
    )
    object.__setattr__(
        value,
        "source",
        AgentCompatibilityKeySource.CURRENT_DERIVED,
    )
    object.__setattr__(value, "key", key)
    object.__setattr__(value, "turn_id", turn_id)
    object.__setattr__(value, "effect_id", effect_id)
    object.__setattr__(value, "kind", AgentEffectKind.OUTBOUND_REPLY)
    return value


def build_agent_outbound_reply_reservation_v2(
    identity: AgentTurnIdentity | object,
) -> AgentOutboundReplyReservationV2:
    """Derive the claim-independent provider key before payload or plan.

    The builder accepts only the trusted turn identity.  The returned key is
    byte-for-byte identical to the current v2 compatibility key for every
    valid later plan containing that turn's outbound-reply ordinal-zero intent.
    """
    expected_identity = _require_expected_identity(identity)
    effect_id = derive_agent_outbound_reply_effect_id(expected_identity)
    return _mint_outbound_reply_reservation_v2(
        turn_id=expected_identity.turn_id,
        effect_id=effect_id,
        key=_derive_v2_compatibility_key_from_effect_id(effect_id),
    )


@dataclass(frozen=True, slots=True, repr=False, init=False)
class AgentEffectCompatibilityKey:
    """One exact structural lookup key for a planned effect."""

    version: AgentCompatibilityKeyVersion
    source: AgentCompatibilityKeySource
    key: str
    plan_digest: str
    turn_id: str
    effect_id: str
    kind: AgentEffectKind
    payload_digest: str

    def __repr__(self) -> str:
        return (
            "AgentEffectCompatibilityKey("
            f"version={self.version.value!r}, source={self.source.value!r})"
        )


def _mint_compatibility_key(
    *,
    version: AgentCompatibilityKeyVersion,
    source: AgentCompatibilityKeySource,
    key: str,
    plan: AgentTurnExecutionPlan,
    intent: AgentEffectIntent,
) -> AgentEffectCompatibilityKey:
    value = object.__new__(AgentEffectCompatibilityKey)
    object.__setattr__(value, "version", version)
    object.__setattr__(value, "source", source)
    object.__setattr__(value, "key", key)
    object.__setattr__(value, "plan_digest", plan.plan_digest)
    object.__setattr__(value, "turn_id", intent.turn_id)
    object.__setattr__(value, "effect_id", intent.effect_id)
    object.__setattr__(value, "kind", intent.kind)
    object.__setattr__(value, "payload_digest", intent.payload_digest)
    return value


def build_agent_effect_compatibility_key(
    identity: AgentTurnIdentity | object,
    plan: AgentTurnExecutionPlan | object,
    intent: AgentEffectIntent | object,
    *,
    version: AgentCompatibilityKeyVersion,
) -> AgentEffectCompatibilityKey:
    """Build the current v2 key, stable only on the planned effect ID."""
    expected_identity = _require_expected_identity(identity)
    expected_plan = validate_agent_turn_execution_plan(expected_identity, plan)
    expected_intent = _require_plan_effect(
        expected_identity,
        expected_plan,
        intent,
    )
    if expected_intent.kind is not AgentEffectKind.OUTBOUND_REPLY:
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.INVALID_COMPATIBILITY_KEY
        )
    exact_version = _require_compatibility_key_version(version)
    if exact_version is not AgentCompatibilityKeyVersion.V2:
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.INVALID_COMPATIBILITY_KEY_VERSION
        )
    key = _derive_v2_compatibility_key(expected_intent)
    return _mint_compatibility_key(
        version=exact_version,
        source=AgentCompatibilityKeySource.CURRENT_DERIVED,
        key=key,
        plan=expected_plan,
        intent=expected_intent,
    )


def bind_agent_legacy_reply_key_evidence(
    identity: AgentTurnIdentity | object,
    plan: AgentTurnExecutionPlan | object,
    intent: AgentEffectIntent | object,
    *,
    version: AgentCompatibilityKeyVersion,
    exact_observed_key: str,
) -> AgentEffectCompatibilityKey:
    """Bind, but never derive or authenticate, one exact live legacy key.

    A future trusted adapter must obtain the key from the exact durable row.
    Calling this function is not proof that the row belongs to the effect.
    """
    expected_identity = _require_expected_identity(identity)
    expected_plan = validate_agent_turn_execution_plan(expected_identity, plan)
    expected_intent = _require_plan_effect(
        expected_identity,
        expected_plan,
        intent,
    )
    if expected_intent.kind is not AgentEffectKind.OUTBOUND_REPLY:
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.INVALID_COMPATIBILITY_KEY
        )
    exact_version = _require_compatibility_key_version(version)
    if exact_version not in {
        AgentCompatibilityKeyVersion.V1,
        AgentCompatibilityKeyVersion.V0,
    }:
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.INVALID_COMPATIBILITY_KEY_VERSION
        )
    if not _is_legacy_reply_key(exact_observed_key, exact_version):
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.INVALID_COMPATIBILITY_KEY
        )
    return _mint_compatibility_key(
        version=exact_version,
        source=AgentCompatibilityKeySource.LEGACY_EXTERNAL_EVIDENCE,
        key=exact_observed_key,
        plan=expected_plan,
        intent=expected_intent,
    )


def _validate_compatibility_key(
    plan: AgentTurnExecutionPlan,
    intent: AgentEffectIntent,
    value: object,
) -> AgentEffectCompatibilityKey:
    if type(value) is not AgentEffectCompatibilityKey:
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.INVALID_COMPATIBILITY_KEY
        )
    try:
        version = value.version
        source = value.source
        key = value.key
        plan_digest = value.plan_digest
        turn_id = value.turn_id
        effect_id = value.effect_id
        kind = value.kind
        payload_digest = value.payload_digest
    except AttributeError:
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.INVALID_COMPATIBILITY_KEY
        ) from None
    exact_version = _require_compatibility_key_version(version)
    if (
        intent.kind is not AgentEffectKind.OUTBOUND_REPLY
        or not _safe_equal(plan_digest, plan.plan_digest)
        or not _safe_equal(turn_id, intent.turn_id)
        or not _safe_equal(effect_id, intent.effect_id)
        or kind is not intent.kind
        or not _safe_equal(payload_digest, intent.payload_digest)
    ):
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.COMPATIBILITY_KEY_CONFLICT
        )
    if exact_version is AgentCompatibilityKeyVersion.V2:
        if source is not AgentCompatibilityKeySource.CURRENT_DERIVED:
            raise AgentCompatibilityKeyError(
                AgentTurnExecutionErrorCode.INVALID_COMPATIBILITY_KEY
            )
        expected_key = _derive_v2_compatibility_key(intent)
        if (
            not _is_prefixed_sha256(
                key,
                _compatibility_key_prefix(exact_version),
            )
            or not _safe_equal(key, expected_key)
        ):
            raise AgentCompatibilityKeyError(
                AgentTurnExecutionErrorCode.INVALID_COMPATIBILITY_KEY
            )
        return value
    if (
        source is not AgentCompatibilityKeySource.LEGACY_EXTERNAL_EVIDENCE
        or not _is_legacy_reply_key(key, exact_version)
    ):
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.INVALID_COMPATIBILITY_KEY
        )
    return value


@dataclass(frozen=True, slots=True, repr=False, init=False)
class AgentCompatibilityKeyResolution:
    """The sole exact candidate; multiple candidates remain inconclusive."""

    selected_version: AgentCompatibilityKeyVersion
    selected_key: str
    source: AgentCompatibilityKeySource

    def __repr__(self) -> str:
        return (
            "AgentCompatibilityKeyResolution("
            f"selected_version={self.selected_version.value!r}, "
            f"source={self.source.value!r})"
        )


def _mint_compatibility_resolution(
    *,
    selected: AgentEffectCompatibilityKey,
) -> AgentCompatibilityKeyResolution:
    resolution = object.__new__(AgentCompatibilityKeyResolution)
    object.__setattr__(resolution, "selected_version", selected.version)
    object.__setattr__(resolution, "selected_key", selected.key)
    object.__setattr__(resolution, "source", selected.source)
    return resolution


def resolve_agent_effect_compatibility_keys(
    identity: AgentTurnIdentity | object,
    plan: AgentTurnExecutionPlan | object,
    intent: AgentEffectIntent | object,
    values: (
        list[AgentEffectCompatibilityKey]
        | tuple[AgentEffectCompatibilityKey, ...]
        | object
    ),
) -> AgentCompatibilityKeyResolution:
    """Resolve one exact v2/v1/v0 key; zero or multiple stay inconclusive."""
    expected_identity = _require_expected_identity(identity)
    expected_plan = validate_agent_turn_execution_plan(expected_identity, plan)
    expected_intent = _require_plan_effect(
        expected_identity,
        expected_plan,
        intent,
    )
    if type(values) not in {list, tuple}:
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.INVALID_COMPATIBILITY_KEY_COLLECTION
        )
    if len(values) > MAX_COMPATIBILITY_KEYS_PER_RESOLUTION:
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.COMPATIBILITY_KEY_LIMIT_EXCEEDED
        )
    if not values:
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.COMPATIBILITY_KEY_INCONCLUSIVE
        )
    if len(values) != 1:
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.COMPATIBILITY_KEY_INCONCLUSIVE
        )
    selected = _validate_compatibility_key(
        expected_plan,
        expected_intent,
        values[0],
    )
    if selected.version is not AgentCompatibilityKeyVersion.V2:
        raise AgentCompatibilityKeyError(
            AgentTurnExecutionErrorCode.COMPATIBILITY_KEY_INCONCLUSIVE
        )
    return _mint_compatibility_resolution(selected=selected)


__all__ = [
    "CONVERSATION_SERIAL_SCOPE_VERSION",
    "EFFECT_RECEIPT_VERSION",
    "EFFECT_EXECUTION_ORDER_VERSION",
    "MAX_COMPATIBILITY_KEYS_PER_RESOLUTION",
    "MAX_EFFECT_RECEIPTS_PER_RESOLUTION",
    "REPLY_OUTBOX_ENTRY_VERSION",
    "TURN_EXECUTION_PLAN_VERSION",
    "AgentCompatibilityKeyError",
    "AgentCompatibilityKeyResolution",
    "AgentCompatibilityKeySource",
    "AgentCompatibilityKeyVersion",
    "AgentConversationSerialScope",
    "AgentEffectCompatibilityKey",
    "AgentEffectReceipt",
    "AgentEffectReceiptError",
    "AgentEffectReceiptOutcome",
    "AgentOutboundReplyReservationV2",
    "AgentReplyOutboxEntry",
    "AgentReplyOutboxError",
    "AgentReplyOutboxEvent",
    "AgentReplyOutboxState",
    "AgentTurnExecutionError",
    "AgentTurnExecutionErrorCode",
    "AgentTurnExecutionPlan",
    "AgentTurnExecutionPlanError",
    "bind_agent_legacy_reply_key_evidence",
    "build_agent_conversation_serial_scope",
    "build_agent_effect_compatibility_key",
    "build_agent_effect_receipt",
    "build_agent_outbound_reply_reservation_v2",
    "build_agent_reply_outbox_entry",
    "build_agent_turn_execution_plan",
    "resolve_agent_effect_compatibility_keys",
    "resolve_agent_effect_receipts",
    "resolve_agent_turn_execution_plans",
    "reconcile_agent_effect_receipt_replay",
    "reconcile_agent_turn_execution_plan",
    "transition_agent_reply_outbox",
    "validate_agent_turn_execution_plan",
]
