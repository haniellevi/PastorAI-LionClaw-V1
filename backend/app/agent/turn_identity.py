"""Pure, inactive D3 identity contract for one inbound agent turn.

This module performs no I/O and is not wired to the worker, runtime, database,
or LangGraph saver.  It gives a persisted inbound Evolution message one stable
turn identity and gives each semantic effect slot one payload-independent ID.
Payloads are represented only by a strict canonical-JSON digest.

``ordinal`` is an occurrence allocated by a future deterministic, persisted
effect plan.  It must never come from model output, list order, retry count, or
an in-memory iteration index.  Until that plan and durable receipts exist, the
current agent state remains replay-unsafe.  ``outbound_reply`` is only a future
intent kind here and does not replace or connect the worker's live reply ledger.

These opaque hashes are deterministic namespaces, not authenticators or tenant
authority.  Durable execution still requires reviewed receipts, serialization,
forced RLS, retention, deletion, and runtime wiring in later slices.
Structural validation cannot prove provenance: a future adapter must load the
expected identity and receipt from a trusted store before accepting replay.

``repr=False`` and the custom repr prevent accidental display only.  The
identity object intentionally contains raw server IDs, so it must never be
logged, passed through ``dataclasses.asdict``, or serialized as an opaque
LangGraph value.

The provider-message validator is intentionally stricter than today's live
ingress.  Future wiring must first inventory and preflight persisted Evolution
IDs, then coordinate any compatibility hardening.  It must not silently drop
or strand existing messages that are outside this inactive contract.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

TURN_ID_VERSION: Final = "v1"
EFFECT_ID_VERSION: Final = "v1"
EFFECT_PAYLOAD_SCHEMA_VERSION: Final = "v1"
EFFECT_SEMANTIC_SLOT_GRAMMAR_VERSION: Final = "v1"

MAX_PROVIDER_MESSAGE_ID_BYTES: Final = 512
MAX_EFFECT_ORDINAL: Final = (1 << 63) - 1
MAX_EFFECT_INTENTS_PER_TURN: Final = 256
MAX_CANONICAL_JSON_DEPTH: Final = 32
MAX_CANONICAL_JSON_NODES: Final = 4096
MAX_CANONICAL_JSON_BYTES: Final = 65_536
MAX_CANONICAL_STRING_BYTES: Final = 32_768
MAX_CANONICAL_INTEGER: Final = (1 << 53) - 1
MIN_CANONICAL_INTEGER: Final = -MAX_CANONICAL_INTEGER

_TURN_ID_DOMAIN: Final = b"pastorai.agent.turn-identity"
_EFFECT_ID_DOMAIN: Final = b"pastorai.agent.effect-intent"
_PAYLOAD_DIGEST_DOMAIN: Final = b"pastorai.agent.effect-payload"
_TURN_ID_PREFIX: Final = f"agent_turn_{TURN_ID_VERSION}_"
_EFFECT_ID_PREFIX: Final = f"agent_effect_{EFFECT_ID_VERSION}_"
_PAYLOAD_DIGEST_PREFIX: Final = (
    f"agent_payload_{EFFECT_PAYLOAD_SCHEMA_VERSION}_"
)


class AgentInboundProvider(str, Enum):
    """Closed provider set for this first identity contract."""

    EVOLUTION = "evolution"


class AgentEffectKind(str, Enum):
    """Minimum closed effect vocabulary required before safe replay."""

    INTAKE_UPDATE = "intake_update"
    APPLY_OPTOUT = "apply_optout"
    APPLY_CONSENT = "apply_consent"
    TOOL_CALL = "tool_call"
    AUDIT_EVENT = "audit_event"
    OUTBOUND_REPLY = "outbound_reply"


class AgentEffectSemanticSlot(str, Enum):
    """Versioned stable grammar used to allocate an effect occurrence."""

    INTAKE_UPDATE = "v1/intake_update"
    APPLY_OPTOUT = "v1/apply_optout"
    APPLY_CONSENT = "v1/apply_consent"
    TOOL_CALL = "v1/tool_call"
    AUDIT_EVENT = "v1/audit_event"
    OUTBOUND_REPLY = "v1/outbound_reply"


_SEMANTIC_SLOT_BY_KIND: Final = {
    AgentEffectKind.INTAKE_UPDATE: AgentEffectSemanticSlot.INTAKE_UPDATE,
    AgentEffectKind.APPLY_OPTOUT: AgentEffectSemanticSlot.APPLY_OPTOUT,
    AgentEffectKind.APPLY_CONSENT: AgentEffectSemanticSlot.APPLY_CONSENT,
    AgentEffectKind.TOOL_CALL: AgentEffectSemanticSlot.TOOL_CALL,
    AgentEffectKind.AUDIT_EVENT: AgentEffectSemanticSlot.AUDIT_EVENT,
    AgentEffectKind.OUTBOUND_REPLY: AgentEffectSemanticSlot.OUTBOUND_REPLY,
}


class AgentTurnContractErrorCode(str, Enum):
    """Sanitized fail-closed reasons; values never contain caller data."""

    INVALID_UUID = "INVALID_UUID"
    INVALID_PROVIDER = "INVALID_PROVIDER"
    INVALID_PROVIDER_MESSAGE_ID = "INVALID_PROVIDER_MESSAGE_ID"
    INVALID_TURN_IDENTITY = "INVALID_TURN_IDENTITY"
    INVALID_EFFECT_KIND = "INVALID_EFFECT_KIND"
    INVALID_EFFECT_ORDINAL = "INVALID_EFFECT_ORDINAL"
    INVALID_EFFECT_INTENT = "INVALID_EFFECT_INTENT"
    INVALID_EFFECT_COLLECTION = "INVALID_EFFECT_COLLECTION"
    EFFECT_COLLECTION_LIMIT_EXCEEDED = "EFFECT_COLLECTION_LIMIT_EXCEEDED"
    UNSUPPORTED_JSON_TYPE = "UNSUPPORTED_JSON_TYPE"
    JSON_INTEGER_OUT_OF_RANGE = "JSON_INTEGER_OUT_OF_RANGE"
    JSON_INVALID_UNICODE = "JSON_INVALID_UNICODE"
    JSON_DEPTH_EXCEEDED = "JSON_DEPTH_EXCEEDED"
    JSON_NODE_LIMIT_EXCEEDED = "JSON_NODE_LIMIT_EXCEEDED"
    JSON_SIZE_EXCEEDED = "JSON_SIZE_EXCEEDED"
    JSON_CYCLE_DETECTED = "JSON_CYCLE_DETECTED"
    UNEXPECTED_TURN_IDENTITY = "UNEXPECTED_TURN_IDENTITY"
    DUPLICATE_SEMANTIC_SLOT = "DUPLICATE_SEMANTIC_SLOT"
    PAYLOAD_DIGEST_CONFLICT = "PAYLOAD_DIGEST_CONFLICT"
    EFFECT_ID_COLLISION = "EFFECT_ID_COLLISION"


class AgentTurnContractError(ValueError):
    """Base error that exposes only one static reason code."""

    def __init__(self, code: AgentTurnContractErrorCode) -> None:
        self.code = code
        super().__init__(f"agent turn contract rejected: {code.value}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


class AgentTurnIdentityError(AgentTurnContractError):
    """A server-resolved inbound identity is incomplete or ambiguous."""


class CanonicalJsonError(AgentTurnContractError):
    """A payload is outside the strict canonical-JSON subset."""


class AgentEffectIntentError(AgentTurnContractError):
    """An effect occurrence is malformed, duplicated, or cross-turn."""


class AgentEffectIntentConflictError(AgentEffectIntentError):
    """The same effect identity was associated with conflicting material."""


def _binary_frame(*parts: bytes) -> bytes:
    """Frame components without delimiter or concatenation ambiguity."""
    if any(type(part) is not bytes for part in parts):
        raise TypeError("binary frame requires bytes")
    framed = bytearray(len(parts).to_bytes(4, "big"))
    for part in parts:
        framed.extend(len(part).to_bytes(4, "big"))
        framed.extend(part)
    return bytes(framed)


def _require_non_nil_uuid(value: object) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        raise AgentTurnIdentityError(AgentTurnContractErrorCode.INVALID_UUID)
    return value


def _utf8_bytes(value: str) -> bytes:
    try:
        return value.encode("utf-8", "strict")
    except UnicodeEncodeError:
        raise CanonicalJsonError(
            AgentTurnContractErrorCode.JSON_INVALID_UNICODE
        ) from None


def _require_provider_message_id(value: object) -> tuple[str, bytes]:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_PROVIDER_MESSAGE_ID_BYTES
        or value[0].isspace()
        or value[-1].isspace()
    ):
        raise AgentTurnIdentityError(
            AgentTurnContractErrorCode.INVALID_PROVIDER_MESSAGE_ID
        )
    if not value.isprintable():
        raise AgentTurnIdentityError(
            AgentTurnContractErrorCode.INVALID_PROVIDER_MESSAGE_ID
        )
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeEncodeError:
        raise AgentTurnIdentityError(
            AgentTurnContractErrorCode.INVALID_PROVIDER_MESSAGE_ID
        ) from None
    if len(encoded) > MAX_PROVIDER_MESSAGE_ID_BYTES:
        raise AgentTurnIdentityError(
            AgentTurnContractErrorCode.INVALID_PROVIDER_MESSAGE_ID
        )
    return value, encoded


def _derive_turn_id(
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    inbound_message_id: uuid.UUID,
    provider: AgentInboundProvider,
    provider_message_id_bytes: bytes,
) -> str:
    material = _binary_frame(
        _TURN_ID_DOMAIN,
        TURN_ID_VERSION.encode("ascii"),
        igreja_id.bytes,
        conversation_id.bytes,
        inbound_message_id.bytes,
        provider.value.encode("ascii"),
        provider_message_id_bytes,
    )
    return f"{_TURN_ID_PREFIX}{hashlib.sha256(material).hexdigest()}"


@dataclass(frozen=True, slots=True, repr=False)
class AgentTurnIdentity:
    """Stable binding for one already-persisted inbound Evolution message."""

    igreja_id: uuid.UUID
    conversation_id: uuid.UUID
    inbound_message_id: uuid.UUID
    provider: AgentInboundProvider
    provider_message_id: str = field(repr=False)
    turn_id: str = field(init=False)

    def __post_init__(self) -> None:
        igreja_id = _require_non_nil_uuid(self.igreja_id)
        conversation_id = _require_non_nil_uuid(self.conversation_id)
        inbound_message_id = _require_non_nil_uuid(self.inbound_message_id)
        if (
            type(self.provider) is not AgentInboundProvider
            or self.provider is not AgentInboundProvider.EVOLUTION
        ):
            raise AgentTurnIdentityError(
                AgentTurnContractErrorCode.INVALID_PROVIDER
            )
        _, provider_message_id_bytes = _require_provider_message_id(
            self.provider_message_id
        )
        object.__setattr__(
            self,
            "turn_id",
            _derive_turn_id(
                igreja_id,
                conversation_id,
                inbound_message_id,
                self.provider,
                provider_message_id_bytes,
            ),
        )

    def __repr__(self) -> str:
        return f"AgentTurnIdentity(version={TURN_ID_VERSION!r})"


def build_agent_turn_identity(
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    inbound_message_id: uuid.UUID,
    provider_message_id: str,
    provider: AgentInboundProvider = AgentInboundProvider.EVOLUTION,
) -> AgentTurnIdentity:
    """Build an identity without coercing or normalizing any component."""
    return AgentTurnIdentity(
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        inbound_message_id=inbound_message_id,
        provider=provider,
        provider_message_id=provider_message_id,
    )


def _validate_json_string(value: str) -> None:
    if len(value) > MAX_CANONICAL_STRING_BYTES:
        raise CanonicalJsonError(AgentTurnContractErrorCode.JSON_SIZE_EXCEEDED)
    encoded = _utf8_bytes(value)
    if len(encoded) > MAX_CANONICAL_STRING_BYTES:
        raise CanonicalJsonError(AgentTurnContractErrorCode.JSON_SIZE_EXCEEDED)


def _validate_canonical_json_value(
    value: object,
    *,
    depth: int,
    ancestors: set[int],
    node_count: list[int],
) -> None:
    if depth > MAX_CANONICAL_JSON_DEPTH:
        raise CanonicalJsonError(
            AgentTurnContractErrorCode.JSON_DEPTH_EXCEEDED
        )
    node_count[0] += 1
    if node_count[0] > MAX_CANONICAL_JSON_NODES:
        raise CanonicalJsonError(
            AgentTurnContractErrorCode.JSON_NODE_LIMIT_EXCEEDED
        )

    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if not MIN_CANONICAL_INTEGER <= value <= MAX_CANONICAL_INTEGER:
            raise CanonicalJsonError(
                AgentTurnContractErrorCode.JSON_INTEGER_OUT_OF_RANGE
            )
        return
    if type(value) is str:
        _validate_json_string(value)
        return

    if type(value) is list:
        container_id = id(value)
        if container_id in ancestors:
            raise CanonicalJsonError(
                AgentTurnContractErrorCode.JSON_CYCLE_DETECTED
            )
        ancestors.add(container_id)
        try:
            for item in value:
                _validate_canonical_json_value(
                    item,
                    depth=depth + 1,
                    ancestors=ancestors,
                    node_count=node_count,
                )
        finally:
            ancestors.remove(container_id)
        return

    if type(value) is dict:
        container_id = id(value)
        if container_id in ancestors:
            raise CanonicalJsonError(
                AgentTurnContractErrorCode.JSON_CYCLE_DETECTED
            )
        ancestors.add(container_id)
        try:
            for key, item in value.items():
                if type(key) is not str:
                    raise CanonicalJsonError(
                        AgentTurnContractErrorCode.UNSUPPORTED_JSON_TYPE
                    )
                _validate_json_string(key)
                _validate_canonical_json_value(
                    item,
                    depth=depth + 1,
                    ancestors=ancestors,
                    node_count=node_count,
                )
        finally:
            ancestors.remove(container_id)
        return

    raise CanonicalJsonError(AgentTurnContractErrorCode.UNSUPPORTED_JSON_TYPE)


def canonical_json_bytes(payload: object) -> bytes:
    """Return deterministic UTF-8 for the exact supported JSON subset."""
    _validate_canonical_json_value(
        payload,
        depth=0,
        ancestors=set(),
        node_count=[0],
    )
    try:
        encoder = json.JSONEncoder(
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        encoded = bytearray()
        for chunk in encoder.iterencode(payload):
            chunk_bytes = chunk.encode("utf-8", "strict")
            if len(encoded) + len(chunk_bytes) > MAX_CANONICAL_JSON_BYTES:
                raise CanonicalJsonError(
                    AgentTurnContractErrorCode.JSON_SIZE_EXCEEDED
                )
            encoded.extend(chunk_bytes)
    except CanonicalJsonError:
        raise
    except (TypeError, ValueError, UnicodeEncodeError):
        raise CanonicalJsonError(
            AgentTurnContractErrorCode.UNSUPPORTED_JSON_TYPE
        ) from None
    return bytes(encoded)


def _require_effect_kind(value: object) -> AgentEffectKind:
    if type(value) is not AgentEffectKind:
        raise AgentEffectIntentError(
            AgentTurnContractErrorCode.INVALID_EFFECT_KIND
        )
    return value


def _require_effect_ordinal(value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_EFFECT_ORDINAL:
        raise AgentEffectIntentError(
            AgentTurnContractErrorCode.INVALID_EFFECT_ORDINAL
        )
    return value


def _semantic_slot(kind: AgentEffectKind) -> AgentEffectSemanticSlot:
    try:
        return _SEMANTIC_SLOT_BY_KIND[kind]
    except KeyError:
        raise AgentEffectIntentError(
            AgentTurnContractErrorCode.INVALID_EFFECT_KIND
        ) from None


def _derive_effect_id(
    turn_id: str,
    semantic_slot: AgentEffectSemanticSlot,
    ordinal: int,
) -> str:
    material = _binary_frame(
        _EFFECT_ID_DOMAIN,
        EFFECT_ID_VERSION.encode("ascii"),
        EFFECT_SEMANTIC_SLOT_GRAMMAR_VERSION.encode("ascii"),
        turn_id.encode("ascii"),
        semantic_slot.value.encode("ascii"),
        ordinal.to_bytes(8, "big", signed=False),
    )
    return f"{_EFFECT_ID_PREFIX}{hashlib.sha256(material).hexdigest()}"


def digest_effect_payload(
    effect_id: str,
    kind: AgentEffectKind,
    payload: object,
) -> str:
    """Bind canonical payload semantics to one opaque effect occurrence."""
    if not _is_prefixed_sha256(effect_id, _EFFECT_ID_PREFIX):
        raise AgentEffectIntentError(
            AgentTurnContractErrorCode.INVALID_EFFECT_INTENT
        )
    exact_kind = _require_effect_kind(kind)
    canonical = canonical_json_bytes(payload)
    material = _binary_frame(
        _PAYLOAD_DIGEST_DOMAIN,
        EFFECT_PAYLOAD_SCHEMA_VERSION.encode("ascii"),
        effect_id.encode("ascii"),
        exact_kind.value.encode("ascii"),
        canonical,
    )
    return f"{_PAYLOAD_DIGEST_PREFIX}{hashlib.sha256(material).hexdigest()}"


@dataclass(frozen=True, slots=True, repr=False, init=False)
class AgentEffectIntent:
    """Payload-free immutable description of one semantic effect occurrence."""

    turn_id: str
    kind: AgentEffectKind
    semantic_slot: AgentEffectSemanticSlot
    ordinal: int
    effect_id: str
    payload_digest: str

    @property
    def intent_id(self) -> str:
        """Compatibility name emphasizing that the ID is only an intent."""
        return self.effect_id

    def __repr__(self) -> str:
        return (
            "AgentEffectIntent("
            f"id_version={EFFECT_ID_VERSION!r}, "
            f"payload_schema={EFFECT_PAYLOAD_SCHEMA_VERSION!r})"
        )


def _mint_effect_intent(
    *,
    turn_id: str,
    kind: AgentEffectKind,
    semantic_slot: AgentEffectSemanticSlot,
    ordinal: int,
    effect_id: str,
    payload_digest: str,
) -> AgentEffectIntent:
    intent = object.__new__(AgentEffectIntent)
    object.__setattr__(intent, "turn_id", turn_id)
    object.__setattr__(intent, "kind", kind)
    object.__setattr__(intent, "semantic_slot", semantic_slot)
    object.__setattr__(intent, "ordinal", ordinal)
    object.__setattr__(intent, "effect_id", effect_id)
    object.__setattr__(intent, "payload_digest", payload_digest)
    return intent


def _require_turn_identity(value: object) -> AgentTurnIdentity:
    if type(value) is not AgentTurnIdentity:
        raise AgentTurnIdentityError(
            AgentTurnContractErrorCode.INVALID_TURN_IDENTITY
        )
    try:
        igreja_id = value.igreja_id
        conversation_id = value.conversation_id
        inbound_message_id = value.inbound_message_id
        provider = value.provider
        provider_message_id = value.provider_message_id
        turn_id = value.turn_id
    except AttributeError:
        raise AgentTurnIdentityError(
            AgentTurnContractErrorCode.INVALID_TURN_IDENTITY
        ) from None
    if (
        type(provider) is not AgentInboundProvider
        or provider is not AgentInboundProvider.EVOLUTION
    ):
        raise AgentTurnIdentityError(
            AgentTurnContractErrorCode.INVALID_TURN_IDENTITY
        )
    _, provider_message_id_bytes = _require_provider_message_id(
        provider_message_id
    )
    expected = _derive_turn_id(
        _require_non_nil_uuid(igreja_id),
        _require_non_nil_uuid(conversation_id),
        _require_non_nil_uuid(inbound_message_id),
        provider,
        provider_message_id_bytes,
    )
    if not _is_prefixed_sha256(turn_id, _TURN_ID_PREFIX) or not hmac.compare_digest(
        expected,
        turn_id,
    ):
        raise AgentTurnIdentityError(
            AgentTurnContractErrorCode.INVALID_TURN_IDENTITY
        )
    return value


def build_agent_effect_intent(
    identity: AgentTurnIdentity | object,
    *,
    kind: AgentEffectKind,
    ordinal: int,
    payload: object,
) -> AgentEffectIntent:
    """Build from a stable planned occurrence, never transient list order."""
    trusted_identity = _require_turn_identity(identity)
    exact_kind = _require_effect_kind(kind)
    exact_ordinal = _require_effect_ordinal(ordinal)
    slot = _semantic_slot(exact_kind)
    effect_id = _derive_effect_id(
        trusted_identity.turn_id,
        slot,
        exact_ordinal,
    )
    payload_digest = digest_effect_payload(effect_id, exact_kind, payload)
    return _mint_effect_intent(
        turn_id=trusted_identity.turn_id,
        kind=exact_kind,
        semantic_slot=slot,
        ordinal=exact_ordinal,
        effect_id=effect_id,
        payload_digest=payload_digest,
    )


build_effect_intent = build_agent_effect_intent


def _is_prefixed_sha256(value: object, prefix: str) -> bool:
    if (
        type(value) is not str
        or len(value) != len(prefix) + 64
        or not value.startswith(prefix)
    ):
        return False
    digest = value[len(prefix) :]
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


def _validate_effect_intent(value: object) -> AgentEffectIntent:
    if type(value) is not AgentEffectIntent:
        raise AgentEffectIntentError(
            AgentTurnContractErrorCode.INVALID_EFFECT_INTENT
        )
    try:
        raw_kind = value.kind
        raw_ordinal = value.ordinal
        raw_slot = value.semantic_slot
        turn_id = value.turn_id
        effect_id = value.effect_id
        payload_digest = value.payload_digest
    except AttributeError:
        raise AgentEffectIntentError(
            AgentTurnContractErrorCode.INVALID_EFFECT_INTENT
        ) from None
    kind = _require_effect_kind(raw_kind)
    ordinal = _require_effect_ordinal(raw_ordinal)
    slot = _semantic_slot(kind)
    if raw_slot is not slot:
        raise AgentEffectIntentError(
            AgentTurnContractErrorCode.INVALID_EFFECT_INTENT
        )
    if not _is_prefixed_sha256(turn_id, _TURN_ID_PREFIX):
        raise AgentEffectIntentError(
            AgentTurnContractErrorCode.INVALID_EFFECT_INTENT
        )
    if not _is_prefixed_sha256(effect_id, _EFFECT_ID_PREFIX):
        raise AgentEffectIntentError(
            AgentTurnContractErrorCode.INVALID_EFFECT_INTENT
        )
    expected_effect_id = _derive_effect_id(turn_id, slot, ordinal)
    if not hmac.compare_digest(expected_effect_id, effect_id):
        raise AgentEffectIntentError(
            AgentTurnContractErrorCode.INVALID_EFFECT_INTENT
        )
    if not _is_prefixed_sha256(payload_digest, _PAYLOAD_DIGEST_PREFIX):
        raise AgentEffectIntentError(
            AgentTurnContractErrorCode.INVALID_EFFECT_INTENT
        )
    return value


def validate_agent_effect_intents(
    identity: AgentTurnIdentity | object,
    values: list[AgentEffectIntent] | tuple[AgentEffectIntent, ...] | object,
) -> tuple[AgentEffectIntent, ...]:
    """Validate structural intents against one trusted expected turn."""
    expected_identity = _require_turn_identity(identity)
    if type(values) not in {list, tuple}:
        raise AgentEffectIntentError(
            AgentTurnContractErrorCode.INVALID_EFFECT_COLLECTION
        )
    if len(values) > MAX_EFFECT_INTENTS_PER_TURN:
        raise AgentEffectIntentError(
            AgentTurnContractErrorCode.EFFECT_COLLECTION_LIMIT_EXCEEDED
        )
    validated: list[AgentEffectIntent] = []
    by_occurrence: dict[
        tuple[AgentEffectSemanticSlot, int], AgentEffectIntent
    ] = {}
    by_effect_id: dict[str, AgentEffectIntent] = {}

    for raw in values:
        current = _validate_effect_intent(raw)
        if not hmac.compare_digest(expected_identity.turn_id, current.turn_id):
            raise AgentEffectIntentError(
                AgentTurnContractErrorCode.UNEXPECTED_TURN_IDENTITY
            )

        occurrence = (current.semantic_slot, current.ordinal)
        previous_occurrence = by_occurrence.get(occurrence)
        if previous_occurrence is not None:
            if (
                hmac.compare_digest(
                    previous_occurrence.effect_id,
                    current.effect_id,
                )
                and not hmac.compare_digest(
                    previous_occurrence.payload_digest,
                    current.payload_digest,
                )
            ):
                raise AgentEffectIntentConflictError(
                    AgentTurnContractErrorCode.PAYLOAD_DIGEST_CONFLICT
                )
            raise AgentEffectIntentError(
                AgentTurnContractErrorCode.DUPLICATE_SEMANTIC_SLOT
            )

        previous_id = by_effect_id.get(current.effect_id)
        if previous_id is not None and (
            previous_id.semantic_slot is not current.semantic_slot
            or previous_id.ordinal != current.ordinal
            or not hmac.compare_digest(
                previous_id.payload_digest,
                current.payload_digest,
            )
        ):
            raise AgentEffectIntentConflictError(
                AgentTurnContractErrorCode.EFFECT_ID_COLLISION
            )

        by_occurrence[occurrence] = current
        by_effect_id[current.effect_id] = current
        validated.append(current)

    return tuple(validated)


__all__ = [
    "EFFECT_ID_VERSION",
    "EFFECT_PAYLOAD_SCHEMA_VERSION",
    "EFFECT_SEMANTIC_SLOT_GRAMMAR_VERSION",
    "MAX_CANONICAL_INTEGER",
    "MAX_CANONICAL_JSON_BYTES",
    "MAX_CANONICAL_JSON_DEPTH",
    "MAX_CANONICAL_JSON_NODES",
    "MAX_CANONICAL_STRING_BYTES",
    "MAX_EFFECT_ORDINAL",
    "MAX_EFFECT_INTENTS_PER_TURN",
    "MAX_PROVIDER_MESSAGE_ID_BYTES",
    "MIN_CANONICAL_INTEGER",
    "TURN_ID_VERSION",
    "AgentEffectIntent",
    "AgentEffectIntentConflictError",
    "AgentEffectIntentError",
    "AgentEffectKind",
    "AgentEffectSemanticSlot",
    "AgentInboundProvider",
    "AgentTurnContractError",
    "AgentTurnContractErrorCode",
    "AgentTurnIdentity",
    "AgentTurnIdentityError",
    "CanonicalJsonError",
    "build_agent_effect_intent",
    "build_agent_turn_identity",
    "build_effect_intent",
    "canonical_json_bytes",
    "digest_effect_payload",
    "validate_agent_effect_intents",
]
