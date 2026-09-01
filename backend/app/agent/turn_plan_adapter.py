"""Pure replay-only adapter from a graph turn output to a D3 effect plan.

This module is deliberately inactive.  It performs no I/O, accepts no injected
functions,
does not read process state, and is not imported by the graph, runtime, worker,
models, or persistence code.  It can only project a versioned structural plan
and reconcile that projection with durable material supplied by a future
trusted adapter.

The only successful replay classification requires exactly one stored plan
that is structurally exact and digest-bound to the projected plan, plus exactly
one valid terminal receipt for every planned effect.  A missing plan or receipt
is classified as first execution unsupported.  No result authorizes execution,
persistence, transport, retry, or a domain mutation.

The current graph output contains an offering as a Python ``float``.  Floats
are forbidden by the canonical effect-payload contract.  This adapter accepts
a float only in the closed ``report_captured.relatorio.oferta`` field, requires
a finite non-negative amount with exact decimal-cent precision, and binds it as
an integer ``oferta_centavos``.  Every other float remains invalid.

All hashes are deterministic namespaces, not authenticators, tenant authority,
or proof of provenance.  A future caller must load the expected identity,
plans, and receipts from one reviewed tenant transaction before reconciliation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.agent.turn_execution import (
    AgentEffectReceipt,
    AgentEffectReceiptError,
    AgentTurnExecutionError,
    AgentTurnExecutionErrorCode,
    AgentTurnExecutionPlan,
    AgentTurnExecutionPlanError,
    build_agent_turn_execution_plan,
    reconcile_agent_turn_execution_plan,
    resolve_agent_effect_receipts,
    resolve_agent_turn_execution_plans,
)
from app.agent.turn_identity import (
    MAX_CANONICAL_INTEGER,
    MAX_CANONICAL_JSON_BYTES,
    MAX_EFFECT_INTENTS_PER_TURN,
    AgentEffectIntent,
    AgentEffectKind,
    AgentTurnContractError,
    AgentTurnIdentity,
    build_agent_effect_intent,
    canonical_json_bytes,
    validate_agent_effect_intents,
)
from app.domain.cell_report_limits import (
    MAX_CELL_REPORT_AGGREGATE_COUNT,
    MAX_CELL_REPORT_OFFERING_CENTS,
)

AGENT_TURN_OUTPUT_SCHEMA_VERSION: Final = "v1"
TURN_PLAN_ADAPTER_VERSION: Final = "v1"

MAX_AGENT_TURN_OUTPUT_EVENTS: Final = 7
MAX_AGENT_TURN_RESPONSE_BYTES: Final = 32_768
MAX_AGENT_TURN_FIELD_BYTES: Final = 512
MAX_AGENT_TURN_RECEIPTS: Final = MAX_EFFECT_INTENTS_PER_TURN

_OUTPUT_DIGEST_DOMAIN: Final = b"pastorai.agent.turn-output"
_OUTPUT_DIGEST_PREFIX: Final = (
    f"agent_turn_output_{AGENT_TURN_OUTPUT_SCHEMA_VERSION}_"
)

_RAW_OUTPUT_KEYS: Final = frozenset({"route", "response", "turn_effects"})
_RAW_EFFECT_KEYS: Final = frozenset(
    {
        "events",
        "tool_calls",
        "apply_optout",
        "apply_consent_version",
        "intake_update",
    }
)
_RAW_EVENT_KEYS: Final = frozenset({"evento", "payload"})
_INTAKE_UPDATE_KEYS: Final = frozenset(
    {
        "origem",
        "set_primeiro_contato",
        "sem_interesse",
        "sem_interesse_motivo",
    }
)
_INTAKE_EVENT_UPDATE_KEYS: Final = frozenset(
    {"origem", "set_primeiro_contato"}
)


class AgentTurnOutputRoute(str, Enum):
    """Closed set of terminal routes emitted by the current graph."""

    HANDOFF = "handoff"
    OPTOUT = "optout"
    CONSENT = "consent"
    REPORT_CAPTURE = "report_capture"
    ONBOARDING = "onboarding"


class AgentTurnOutputEventName(str, Enum):
    """Closed, versioned event vocabulary admitted from graph output v1."""

    INTAKE = "intake"
    CONSENT_ACCEPTED = "consent_accepted"
    CONSENT_PRESENTED = "consent_presented"
    OPTOUT = "optout"
    HANDOFF_SUSPENDED = "handoff_suspended"
    REPORT_CAPTURED = "report_captured"
    ONBOARDING = "onboarding"


_EVENT_ORDINALS: Final = {
    AgentTurnOutputEventName.INTAKE: 10,
    AgentTurnOutputEventName.CONSENT_ACCEPTED: 20,
    AgentTurnOutputEventName.CONSENT_PRESENTED: 30,
    AgentTurnOutputEventName.OPTOUT: 40,
    AgentTurnOutputEventName.HANDOFF_SUSPENDED: 50,
    AgentTurnOutputEventName.REPORT_CAPTURED: 60,
    AgentTurnOutputEventName.ONBOARDING: 70,
}
_EVENT_ORDER: Final = (
    AgentTurnOutputEventName.INTAKE,
    AgentTurnOutputEventName.CONSENT_ACCEPTED,
    AgentTurnOutputEventName.CONSENT_PRESENTED,
    AgentTurnOutputEventName.OPTOUT,
    AgentTurnOutputEventName.HANDOFF_SUSPENDED,
    AgentTurnOutputEventName.REPORT_CAPTURED,
    AgentTurnOutputEventName.ONBOARDING,
)

_ROUTE_EVENT: Final = {
    AgentTurnOutputRoute.HANDOFF: AgentTurnOutputEventName.HANDOFF_SUSPENDED,
    AgentTurnOutputRoute.OPTOUT: AgentTurnOutputEventName.OPTOUT,
    AgentTurnOutputRoute.REPORT_CAPTURE: AgentTurnOutputEventName.REPORT_CAPTURED,
    AgentTurnOutputRoute.ONBOARDING: AgentTurnOutputEventName.ONBOARDING,
}

_INTERNAL_OUTPUT_AUDIT_ORDINAL: Final = 0


class AgentTurnPlanAdapterStatus(str, Enum):
    """Replay-only conclusions, neither of which grants execution authority."""

    FIRST_EXECUTION_UNSUPPORTED = "FIRST_EXECUTION_UNSUPPORTED"
    REPLAY_TERMINAL = "REPLAY_TERMINAL"


class AgentTurnPlanAdapterErrorCode(str, Enum):
    """Sanitized fail-closed reasons; values never contain caller material."""

    INVALID_EXPECTED_IDENTITY = "INVALID_EXPECTED_IDENTITY"
    INVALID_TURN_OUTPUT = "INVALID_TURN_OUTPUT"
    TURN_OUTPUT_LIMIT_EXCEEDED = "TURN_OUTPUT_LIMIT_EXCEEDED"
    TOOL_CALLS_FORBIDDEN = "TOOL_CALLS_FORBIDDEN"
    UNKNOWN_OUTPUT_EVENT = "UNKNOWN_OUTPUT_EVENT"
    DUPLICATE_OUTPUT_EVENT = "DUPLICATE_OUTPUT_EVENT"
    OUTPUT_EVENT_MISMATCH = "OUTPUT_EVENT_MISMATCH"
    INVALID_REPORT_AMOUNT = "INVALID_REPORT_AMOUNT"
    INVALID_PROJECTED_PLAN = "INVALID_PROJECTED_PLAN"
    INVALID_PLAN_COLLECTION = "INVALID_PLAN_COLLECTION"
    PLAN_CONFLICT = "PLAN_CONFLICT"
    INVALID_RECEIPT_COLLECTION = "INVALID_RECEIPT_COLLECTION"
    RECEIPT_LIMIT_EXCEEDED = "RECEIPT_LIMIT_EXCEEDED"
    INVALID_RECEIPT = "INVALID_RECEIPT"
    UNEXPECTED_RECEIPT = "UNEXPECTED_RECEIPT"
    RECEIPT_CONFLICT = "RECEIPT_CONFLICT"


class AgentTurnPlanAdapterError(ValueError):
    """Adapter failure that exposes only one static reason code."""

    def __init__(self, code: AgentTurnPlanAdapterErrorCode) -> None:
        self.code = code
        super().__init__(f"agent turn plan adapter rejected: {code.value}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


@dataclass(frozen=True, slots=True, repr=False, init=False)
class AgentTurnOutputEventV1:
    """Detached canonical form of one admitted output event."""

    schema_version: str
    name: AgentTurnOutputEventName
    ordinal: int
    payload_json: bytes

    def __repr__(self) -> str:
        return "AgentTurnOutputEventV1(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False, init=False)
class AgentTurnOutputV1:
    """Immutable, detached, versioned graph-output snapshot."""

    schema_version: str
    route: AgentTurnOutputRoute
    response: str | None
    events: tuple[AgentTurnOutputEventV1, ...]
    apply_optout: bool
    apply_consent_version: str | None
    intake_update_json: bytes
    output_digest: str

    def __repr__(self) -> str:
        return "AgentTurnOutputV1(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False, init=False)
class AgentTurnPlanReplayResolution:
    """Sanitized replay conclusion without an execution capability."""

    status: AgentTurnPlanAdapterStatus
    output_digest: str
    plan_digest: str
    effect_count: int
    terminal_receipt_count: int

    def __repr__(self) -> str:
        return "AgentTurnPlanReplayResolution(<redacted>)"


def _binary_frame(*parts: bytes) -> bytes:
    if any(type(part) is not bytes for part in parts):
        raise TypeError("binary frame requires bytes")
    framed = bytearray(len(parts).to_bytes(4, "big"))
    for part in parts:
        framed.extend(len(part).to_bytes(4, "big"))
        framed.extend(part)
    return bytes(framed)


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
    return (
        type(value) is str
        and len(value) == len(expected)
        and value.isascii()
        and hmac.compare_digest(value, expected)
    )


def _raise(code: AgentTurnPlanAdapterErrorCode) -> None:
    raise AgentTurnPlanAdapterError(code)


def _require_exact_dict(
    value: object,
    keys: frozenset[str],
    *,
    code: AgentTurnPlanAdapterErrorCode = (
        AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT
    ),
) -> dict[str, object]:
    if type(value) is not dict or len(value) != len(keys):
        _raise(code)
    if any(type(key) is not str for key in value):
        _raise(code)
    if frozenset(value) != keys:
        _raise(code)
    return value


def _require_bounded_string(
    value: object,
    *,
    max_bytes: int = MAX_AGENT_TURN_FIELD_BYTES,
    allow_empty: bool = False,
) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    if len(value) > max_bytes:
        _raise(AgentTurnPlanAdapterErrorCode.TURN_OUTPUT_LIMIT_EXCEEDED)
    if value and (
        value[0].isspace()
        or value[-1].isspace()
        or not value.isprintable()
    ):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeEncodeError:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    if len(encoded) > max_bytes:
        _raise(AgentTurnPlanAdapterErrorCode.TURN_OUTPUT_LIMIT_EXCEEDED)
    return value


def _require_identity(value: object) -> AgentTurnIdentity:
    try:
        validate_agent_effect_intents(value, ())
    except AgentTurnContractError:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_EXPECTED_IDENTITY)
    if type(value) is not AgentTurnIdentity:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_EXPECTED_IDENTITY)
    return value


def _require_route(value: object) -> AgentTurnOutputRoute:
    if type(value) is not str or len(value) > 32:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    try:
        return AgentTurnOutputRoute(value)
    except ValueError:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)


def _require_response(
    value: object,
    route: AgentTurnOutputRoute,
) -> str | None:
    if value is None:
        if route is not AgentTurnOutputRoute.HANDOFF:
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
        return None
    if route is AgentTurnOutputRoute.HANDOFF:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    return _require_bounded_string(
        value,
        max_bytes=MAX_AGENT_TURN_RESPONSE_BYTES,
    )


def _normalize_intake_update(value: object) -> dict[str, object]:
    if type(value) is not dict or len(value) > len(_INTAKE_UPDATE_KEYS):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    if any(type(key) is not str for key in value):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    if not frozenset(value).issubset(_INTAKE_UPDATE_KEYS):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)

    normalized: dict[str, object] = {}
    if "origem" in value:
        if (
            type(value["origem"]) is not str
            or value["origem"] != "whatsapp"
        ):
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
        normalized["origem"] = "whatsapp"
    if "set_primeiro_contato" in value:
        if value["set_primeiro_contato"] is not True:
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
        normalized["set_primeiro_contato"] = True
    if "sem_interesse" in value:
        if value["sem_interesse"] is not True:
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
        normalized["sem_interesse"] = True
    if "sem_interesse_motivo" in value:
        normalized["sem_interesse_motivo"] = _require_bounded_string(
            value["sem_interesse_motivo"]
        )
    if ("sem_interesse" in normalized) != (
        "sem_interesse_motivo" in normalized
    ):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    return normalized


def _normalize_intake_event_update(value: object) -> dict[str, object]:
    normalized = _normalize_intake_update(value)
    if not frozenset(normalized).issubset(_INTAKE_EVENT_UPDATE_KEYS):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    return normalized


def _require_nonnegative_count(value: object) -> int | None:
    if value is None:
        return None
    if (
        type(value) is not int
        or value < 0
        or value > MAX_CELL_REPORT_AGGREGATE_COUNT
    ):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    return value


def _offering_cents(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is int:
        if value < 0 or value > MAX_CELL_REPORT_OFFERING_CENTS // 100:
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_REPORT_AMOUNT)
        return value * 100
    if (
        type(value) is not float
        or not math.isfinite(value)
        or math.copysign(1.0, value) < 0
    ):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_REPORT_AMOUNT)

    # Parse the built-in float's shortest decimal representation directly.
    # Decimal arithmetic is intentionally avoided: its global precision,
    # rounding, and trap configuration are mutable process state and must not
    # be able to alter a replay digest or leak an arithmetic exception.
    try:
        decimal_text = str(value).lower()
        if decimal_text.startswith(("+", "-")):
            decimal_text = decimal_text[1:]
        mantissa, exponent_separator, exponent_text = decimal_text.partition(
            "e"
        )
        exponent = int(exponent_text) if exponent_separator else 0
        whole, point, fraction = mantissa.partition(".")
        if (
            not whole.isascii()
            or not whole.isdigit()
            or (point and (not fraction.isascii() or not fraction.isdigit()))
        ):
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_REPORT_AMOUNT)
        coefficient = int(whole + fraction)
    except (OverflowError, ValueError):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_REPORT_AMOUNT)

    cents_exponent = exponent - len(fraction) + 2
    if cents_exponent >= 0:
        cents_value = coefficient * (10**cents_exponent)
    else:
        cents_value, remainder = divmod(
            coefficient,
            10 ** (-cents_exponent),
        )
        if remainder:
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_REPORT_AMOUNT)
    if cents_value < 0 or cents_value > MAX_CELL_REPORT_OFFERING_CENTS:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_REPORT_AMOUNT)
    return cents_value


def _normalize_report_payload(value: object) -> dict[str, object]:
    payload = _require_exact_dict(value, frozenset({"relatorio"}))
    report = _require_exact_dict(
        payload["relatorio"],
        frozenset({"presentes", "visitantes", "decisoes", "oferta"}),
    )
    return {
        "relatorio": {
            "presentes": _require_nonnegative_count(report["presentes"]),
            "visitantes": _require_nonnegative_count(report["visitantes"]),
            "decisoes": _require_nonnegative_count(report["decisoes"]),
            "oferta_centavos": _offering_cents(report["oferta"]),
        }
    }


def _normalize_raw_event_payload(
    name: AgentTurnOutputEventName,
    value: object,
) -> dict[str, object]:
    if name is AgentTurnOutputEventName.INTAKE:
        payload = _require_exact_dict(value, frozenset({"update"}))
        return {"update": _normalize_intake_event_update(payload["update"])}
    if name in {
        AgentTurnOutputEventName.CONSENT_ACCEPTED,
        AgentTurnOutputEventName.CONSENT_PRESENTED,
    }:
        payload = _require_exact_dict(value, frozenset({"termoVersao"}))
        return {
            "termoVersao": _require_bounded_string(payload["termoVersao"])
        }
    if name in {
        AgentTurnOutputEventName.OPTOUT,
        AgentTurnOutputEventName.HANDOFF_SUSPENDED,
    }:
        _require_exact_dict(value, frozenset())
        return {}
    if name is AgentTurnOutputEventName.REPORT_CAPTURED:
        return _normalize_report_payload(value)
    if name is AgentTurnOutputEventName.ONBOARDING:
        payload = _require_exact_dict(value, frozenset({"classificacao"}))
        return {
            "classificacao": _require_bounded_string(payload["classificacao"])
        }
    _raise(AgentTurnPlanAdapterErrorCode.UNKNOWN_OUTPUT_EVENT)


def _mint_event(
    name: AgentTurnOutputEventName,
    payload_json: bytes,
) -> AgentTurnOutputEventV1:
    value = object.__new__(AgentTurnOutputEventV1)
    object.__setattr__(value, "schema_version", AGENT_TURN_OUTPUT_SCHEMA_VERSION)
    object.__setattr__(value, "name", name)
    object.__setattr__(value, "ordinal", _EVENT_ORDINALS[name])
    object.__setattr__(value, "payload_json", payload_json)
    return value


def _canonicalize_events(
    values: list[AgentTurnOutputEventV1],
) -> tuple[AgentTurnOutputEventV1, ...]:
    by_name = {value.name: value for value in values}
    return tuple(by_name[name] for name in _EVENT_ORDER if name in by_name)


def _decode_canonical_json(value: object) -> object:
    if (
        type(value) is not bytes
        or not value
        or len(value) > MAX_CANONICAL_JSON_BYTES
    ):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    try:
        decoded = json.loads(value.decode("utf-8", "strict"))
        rebuilt = canonical_json_bytes(decoded)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
        AgentTurnContractError,
    ):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    if not hmac.compare_digest(value, rebuilt):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    return decoded


def _expected_event_names(
    route: AgentTurnOutputRoute,
    apply_consent_version: str | None,
) -> frozenset[AgentTurnOutputEventName]:
    if route is AgentTurnOutputRoute.CONSENT:
        consent_event = (
            AgentTurnOutputEventName.CONSENT_ACCEPTED
            if apply_consent_version is not None
            else AgentTurnOutputEventName.CONSENT_PRESENTED
        )
        return frozenset({AgentTurnOutputEventName.INTAKE, consent_event})
    return frozenset(
        {AgentTurnOutputEventName.INTAKE, _ROUTE_EVENT[route]}
    )


def _validate_output_semantics(
    *,
    route: AgentTurnOutputRoute,
    response: str | None,
    events: tuple[AgentTurnOutputEventV1, ...],
    apply_optout: bool,
    apply_consent_version: str | None,
    intake_update: dict[str, object],
) -> None:
    _require_response(response, route)
    if apply_optout is not (route is AgentTurnOutputRoute.OPTOUT):
        _raise(AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH)
    if route is not AgentTurnOutputRoute.CONSENT and apply_consent_version is not None:
        _raise(AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH)

    by_name = {event.name: event for event in events}
    if len(by_name) != len(events):
        _raise(AgentTurnPlanAdapterErrorCode.DUPLICATE_OUTPUT_EVENT)
    if frozenset(by_name) != _expected_event_names(
        route, apply_consent_version
    ):
        _raise(AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH)

    intake_payload = _decode_canonical_json(
        by_name[AgentTurnOutputEventName.INTAKE].payload_json
    )
    expected_intake_payload = {
        "update": {
            key: value
            for key, value in intake_update.items()
            if key in _INTAKE_EVENT_UPDATE_KEYS
        }
    }
    if canonical_json_bytes(intake_payload) != canonical_json_bytes(
        expected_intake_payload
    ):
        _raise(AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH)

    has_csim_update = "sem_interesse" in intake_update
    has_csim_classification = False
    if route is AgentTurnOutputRoute.ONBOARDING:
        onboarding_payload = _decode_canonical_json(
            by_name[AgentTurnOutputEventName.ONBOARDING].payload_json
        )
        if type(onboarding_payload) is not dict:
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
        has_csim_classification = (
            onboarding_payload.get("classificacao") == "csim"
        )
    if has_csim_update != has_csim_classification:
        _raise(AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH)

    if route is AgentTurnOutputRoute.CONSENT:
        consent_name = (
            AgentTurnOutputEventName.CONSENT_ACCEPTED
            if apply_consent_version is not None
            else AgentTurnOutputEventName.CONSENT_PRESENTED
        )
        consent_payload = _decode_canonical_json(by_name[consent_name].payload_json)
        if type(consent_payload) is not dict:
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
        event_version = consent_payload.get("termoVersao")
        if consent_name is AgentTurnOutputEventName.CONSENT_ACCEPTED:
            if event_version != apply_consent_version:
                _raise(AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH)


def _output_material(
    *,
    route: AgentTurnOutputRoute,
    response: str | None,
    events: tuple[AgentTurnOutputEventV1, ...],
    apply_optout: bool,
    apply_consent_version: str | None,
    intake_update: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": AGENT_TURN_OUTPUT_SCHEMA_VERSION,
        "route": route.value,
        "response": response,
        "turn_effects": {
            "events": [
                {
                    "evento": event.name.value,
                    "payload": _decode_canonical_json(event.payload_json),
                }
                for event in events
            ],
            "tool_calls": [],
            "apply_optout": apply_optout,
            "apply_consent_version": apply_consent_version,
            "intake_update": intake_update,
        },
    }


def _derive_output_digest(material: dict[str, object]) -> str:
    canonical = canonical_json_bytes(material)
    framed = _binary_frame(
        _OUTPUT_DIGEST_DOMAIN,
        AGENT_TURN_OUTPUT_SCHEMA_VERSION.encode("ascii"),
        canonical,
    )
    return f"{_OUTPUT_DIGEST_PREFIX}{hashlib.sha256(framed).hexdigest()}"


def _mint_output(
    *,
    route: AgentTurnOutputRoute,
    response: str | None,
    events: tuple[AgentTurnOutputEventV1, ...],
    apply_optout: bool,
    apply_consent_version: str | None,
    intake_update_json: bytes,
    output_digest: str,
) -> AgentTurnOutputV1:
    value = object.__new__(AgentTurnOutputV1)
    object.__setattr__(value, "schema_version", AGENT_TURN_OUTPUT_SCHEMA_VERSION)
    object.__setattr__(value, "route", route)
    object.__setattr__(value, "response", response)
    object.__setattr__(value, "events", events)
    object.__setattr__(value, "apply_optout", apply_optout)
    object.__setattr__(value, "apply_consent_version", apply_consent_version)
    object.__setattr__(value, "intake_update_json", intake_update_json)
    object.__setattr__(value, "output_digest", output_digest)
    return value


def build_agent_turn_output_v1(value: object) -> AgentTurnOutputV1:
    """Validate and detach one current graph output into schema v1."""
    output = _require_exact_dict(value, _RAW_OUTPUT_KEYS)
    route = _require_route(output["route"])
    response = _require_response(output["response"], route)
    effects = _require_exact_dict(output["turn_effects"], _RAW_EFFECT_KEYS)

    tool_calls = effects["tool_calls"]
    if type(tool_calls) is not list:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    if tool_calls:
        _raise(AgentTurnPlanAdapterErrorCode.TOOL_CALLS_FORBIDDEN)

    raw_events = effects["events"]
    if type(raw_events) is not list:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    if len(raw_events) > MAX_AGENT_TURN_OUTPUT_EVENTS:
        _raise(AgentTurnPlanAdapterErrorCode.TURN_OUTPUT_LIMIT_EXCEEDED)

    events: list[AgentTurnOutputEventV1] = []
    names: set[AgentTurnOutputEventName] = set()
    for raw_event in raw_events:
        event = _require_exact_dict(raw_event, _RAW_EVENT_KEYS)
        raw_name = event["evento"]
        if type(raw_name) is not str or len(raw_name) > 64:
            _raise(AgentTurnPlanAdapterErrorCode.UNKNOWN_OUTPUT_EVENT)
        try:
            name = AgentTurnOutputEventName(raw_name)
        except ValueError:
            _raise(AgentTurnPlanAdapterErrorCode.UNKNOWN_OUTPUT_EVENT)
        if name in names:
            _raise(AgentTurnPlanAdapterErrorCode.DUPLICATE_OUTPUT_EVENT)
        names.add(name)
        normalized_payload = _normalize_raw_event_payload(name, event["payload"])
        events.append(_mint_event(name, canonical_json_bytes(normalized_payload)))

    canonical_events = _canonicalize_events(events)
    apply_optout = effects["apply_optout"]
    if type(apply_optout) is not bool:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    apply_consent_version = effects["apply_consent_version"]
    if apply_consent_version is not None:
        apply_consent_version = _require_bounded_string(apply_consent_version)
    intake_update = _normalize_intake_update(effects["intake_update"])

    _validate_output_semantics(
        route=route,
        response=response,
        events=canonical_events,
        apply_optout=apply_optout,
        apply_consent_version=apply_consent_version,
        intake_update=intake_update,
    )
    material = _output_material(
        route=route,
        response=response,
        events=canonical_events,
        apply_optout=apply_optout,
        apply_consent_version=apply_consent_version,
        intake_update=intake_update,
    )
    return _mint_output(
        route=route,
        response=response,
        events=canonical_events,
        apply_optout=apply_optout,
        apply_consent_version=apply_consent_version,
        intake_update_json=canonical_json_bytes(intake_update),
        output_digest=_derive_output_digest(material),
    )


def validate_agent_turn_output_v1(value: object) -> AgentTurnOutputV1:
    """Revalidate a possibly forged output snapshot and its digest."""
    if type(value) is not AgentTurnOutputV1:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    try:
        schema_version = value.schema_version
        route = value.route
        response = value.response
        events = value.events
        apply_optout = value.apply_optout
        apply_consent_version = value.apply_consent_version
        intake_update_json = value.intake_update_json
        output_digest = value.output_digest
    except AttributeError:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)

    if (
        type(schema_version) is not str
        or schema_version != AGENT_TURN_OUTPUT_SCHEMA_VERSION
    ):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    if type(route) is not AgentTurnOutputRoute:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    response = _require_response(response, route)
    if type(events) is not tuple or len(events) > MAX_AGENT_TURN_OUTPUT_EVENTS:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    if type(apply_optout) is not bool:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    if apply_consent_version is not None:
        apply_consent_version = _require_bounded_string(apply_consent_version)

    validated_events: list[AgentTurnOutputEventV1] = []
    for event in events:
        if type(event) is not AgentTurnOutputEventV1:
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
        try:
            event_schema = event.schema_version
            name = event.name
            ordinal = event.ordinal
            payload_json = event.payload_json
        except AttributeError:
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
        if (
            type(event_schema) is not str
            or event_schema != AGENT_TURN_OUTPUT_SCHEMA_VERSION
            or type(name) is not AgentTurnOutputEventName
            or type(ordinal) is not int
            or ordinal != _EVENT_ORDINALS[name]
        ):
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
        normalized_payload = _decode_canonical_json(payload_json)
        if type(normalized_payload) is not dict:
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
        _validate_normalized_event_payload(name, normalized_payload)
        validated_events.append(event)

    canonical_events = _canonicalize_events(validated_events)
    if canonical_events != events:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    intake_update_value = _decode_canonical_json(intake_update_json)
    intake_update = _normalize_intake_update(intake_update_value)
    if canonical_json_bytes(intake_update) != intake_update_json:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)

    _validate_output_semantics(
        route=route,
        response=response,
        events=events,
        apply_optout=apply_optout,
        apply_consent_version=apply_consent_version,
        intake_update=intake_update,
    )
    material = _output_material(
        route=route,
        response=response,
        events=events,
        apply_optout=apply_optout,
        apply_consent_version=apply_consent_version,
        intake_update=intake_update,
    )
    expected_digest = _derive_output_digest(material)
    if (
        not _is_prefixed_sha256(output_digest, _OUTPUT_DIGEST_PREFIX)
        or not _safe_equal(output_digest, expected_digest)
    ):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)
    return value


def _validate_normalized_event_payload(
    name: AgentTurnOutputEventName,
    value: dict[str, object],
) -> None:
    if name is AgentTurnOutputEventName.REPORT_CAPTURED:
        payload = _require_exact_dict(value, frozenset({"relatorio"}))
        report = _require_exact_dict(
            payload["relatorio"],
            frozenset(
                {"presentes", "visitantes", "decisoes", "oferta_centavos"}
            ),
        )
        _require_nonnegative_count(report["presentes"])
        _require_nonnegative_count(report["visitantes"])
        _require_nonnegative_count(report["decisoes"])
        cents = report["oferta_centavos"]
        if cents is not None and (
            type(cents) is not int
            or cents < 0
            or cents > MAX_CELL_REPORT_OFFERING_CENTS
        ):
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_REPORT_AMOUNT)
        return
    normalized = _normalize_raw_event_payload(name, value)
    if canonical_json_bytes(normalized) != canonical_json_bytes(value):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT)


def _coerce_output(value: object) -> AgentTurnOutputV1:
    if type(value) is AgentTurnOutputV1:
        return validate_agent_turn_output_v1(value)
    return build_agent_turn_output_v1(value)


def _intent_payload_base(output: AgentTurnOutputV1) -> dict[str, object]:
    return {
        "adapter_version": TURN_PLAN_ADAPTER_VERSION,
        "output_schema_version": AGENT_TURN_OUTPUT_SCHEMA_VERSION,
        "output_digest": output.output_digest,
    }


def _project_effect_intents(
    identity: AgentTurnIdentity,
    output: AgentTurnOutputV1,
) -> tuple[AgentEffectIntent, ...]:
    base = _intent_payload_base(output)
    intents: list[AgentEffectIntent] = [
        build_agent_effect_intent(
            identity,
            kind=AgentEffectKind.AUDIT_EVENT,
            ordinal=_INTERNAL_OUTPUT_AUDIT_ORDINAL,
            payload={
                **base,
                "event": "turn_output",
                "route": output.route.value,
            },
        )
    ]

    intake_update = _decode_canonical_json(output.intake_update_json)
    if intake_update:
        intents.append(
            build_agent_effect_intent(
                identity,
                kind=AgentEffectKind.INTAKE_UPDATE,
                ordinal=0,
                payload={**base, "update": intake_update},
            )
        )
    if output.apply_optout:
        intents.append(
            build_agent_effect_intent(
                identity,
                kind=AgentEffectKind.APPLY_OPTOUT,
                ordinal=0,
                payload={**base, "apply_optout": True},
            )
        )
    if output.apply_consent_version is not None:
        intents.append(
            build_agent_effect_intent(
                identity,
                kind=AgentEffectKind.APPLY_CONSENT,
                ordinal=0,
                payload={
                    **base,
                    "term_version": output.apply_consent_version,
                },
            )
        )
    for event in output.events:
        intents.append(
            build_agent_effect_intent(
                identity,
                kind=AgentEffectKind.AUDIT_EVENT,
                ordinal=event.ordinal,
                payload={
                    **base,
                    "event": event.name.value,
                    "payload": _decode_canonical_json(event.payload_json),
                },
            )
        )
    if output.response is not None:
        intents.append(
            build_agent_effect_intent(
                identity,
                kind=AgentEffectKind.OUTBOUND_REPLY,
                ordinal=0,
                payload={**base, "response": output.response},
            )
        )
    try:
        return validate_agent_effect_intents(identity, tuple(intents))
    except AgentTurnContractError:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_PROJECTED_PLAN)


def project_agent_turn_execution_plan(
    identity: AgentTurnIdentity | object,
    output: AgentTurnOutputV1 | object,
) -> AgentTurnExecutionPlan:
    """Project a structural candidate only; it grants no first execution."""
    expected_identity = _require_identity(identity)
    expected_output = _coerce_output(output)
    try:
        intents = _project_effect_intents(expected_identity, expected_output)
        return build_agent_turn_execution_plan(expected_identity, intents)
    except (AgentTurnContractError, AgentTurnExecutionError):
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_PROJECTED_PLAN)


def _map_plan_error(error: AgentTurnExecutionError) -> None:
    if error.code is AgentTurnExecutionErrorCode.EXECUTION_PLAN_CONFLICT:
        _raise(AgentTurnPlanAdapterErrorCode.PLAN_CONFLICT)
    if error.code is AgentTurnExecutionErrorCode.INVALID_PLAN_COLLECTION:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_PLAN_COLLECTION)
    _raise(AgentTurnPlanAdapterErrorCode.PLAN_CONFLICT)


def _map_receipt_error(error: AgentTurnExecutionError) -> None:
    if error.code in {
        AgentTurnExecutionErrorCode.EFFECT_RECEIPT_CONFLICT,
        AgentTurnExecutionErrorCode.UNEXPECTED_EFFECT_RECEIPT,
    }:
        code = AgentTurnPlanAdapterErrorCode.RECEIPT_CONFLICT
        if error.code is AgentTurnExecutionErrorCode.UNEXPECTED_EFFECT_RECEIPT:
            code = AgentTurnPlanAdapterErrorCode.UNEXPECTED_RECEIPT
        _raise(code)
    _raise(AgentTurnPlanAdapterErrorCode.INVALID_RECEIPT)


def _mint_resolution(
    *,
    status: AgentTurnPlanAdapterStatus,
    output: AgentTurnOutputV1,
    plan: AgentTurnExecutionPlan,
    terminal_receipt_count: int,
) -> AgentTurnPlanReplayResolution:
    value = object.__new__(AgentTurnPlanReplayResolution)
    object.__setattr__(value, "status", status)
    object.__setattr__(value, "output_digest", output.output_digest)
    object.__setattr__(value, "plan_digest", plan.plan_digest)
    object.__setattr__(value, "effect_count", len(plan.effect_intents))
    object.__setattr__(
        value,
        "terminal_receipt_count",
        terminal_receipt_count,
    )
    return value


def _require_receipt_collection(
    value: object,
) -> list[AgentEffectReceipt] | tuple[AgentEffectReceipt, ...]:
    if type(value) not in {list, tuple}:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_RECEIPT_COLLECTION)
    if len(value) > MAX_AGENT_TURN_RECEIPTS:
        _raise(AgentTurnPlanAdapterErrorCode.RECEIPT_LIMIT_EXCEEDED)
    return value


def reconcile_agent_turn_output_replay(
    identity: AgentTurnIdentity | object,
    output: AgentTurnOutputV1 | object,
    plans: list[AgentTurnExecutionPlan] | tuple[AgentTurnExecutionPlan, ...] | object,
    receipts: list[AgentEffectReceipt] | tuple[AgentEffectReceipt, ...] | object,
) -> AgentTurnPlanReplayResolution:
    """Reconcile exact terminal replay; every incomplete state stays blocked."""
    expected_identity = _require_identity(identity)
    expected_output = _coerce_output(output)
    projected_plan = project_agent_turn_execution_plan(
        expected_identity,
        expected_output,
    )
    if type(plans) not in {list, tuple}:
        _raise(AgentTurnPlanAdapterErrorCode.INVALID_PLAN_COLLECTION)
    receipt_rows = _require_receipt_collection(receipts)

    try:
        stored_plan = resolve_agent_turn_execution_plans(
            expected_identity,
            plans,
        )
    except AgentTurnExecutionPlanError as error:
        _map_plan_error(error)

    if stored_plan is None:
        if receipt_rows:
            _raise(AgentTurnPlanAdapterErrorCode.UNEXPECTED_RECEIPT)
        return _mint_resolution(
            status=AgentTurnPlanAdapterStatus.FIRST_EXECUTION_UNSUPPORTED,
            output=expected_output,
            plan=projected_plan,
            terminal_receipt_count=0,
        )

    try:
        exact_plan = reconcile_agent_turn_execution_plan(
            expected_identity,
            stored_plan,
            projected_plan,
        )
    except AgentTurnExecutionPlanError as error:
        _map_plan_error(error)

    by_effect_id: dict[str, list[AgentEffectReceipt]] = {
        intent.effect_id: [] for intent in exact_plan.effect_intents
    }
    for receipt in receipt_rows:
        if type(receipt) is not AgentEffectReceipt:
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_RECEIPT)
        try:
            effect_id = receipt.effect_id
        except AttributeError:
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_RECEIPT)
        if type(effect_id) is not str or len(effect_id) > 128:
            _raise(AgentTurnPlanAdapterErrorCode.INVALID_RECEIPT)
        bucket = by_effect_id.get(effect_id)
        if bucket is None:
            _raise(AgentTurnPlanAdapterErrorCode.UNEXPECTED_RECEIPT)
        bucket.append(receipt)

    terminal_receipts = 0
    missing = False
    for intent in exact_plan.effect_intents:
        try:
            receipt = resolve_agent_effect_receipts(
                expected_identity,
                exact_plan,
                intent,
                by_effect_id[intent.effect_id],
            )
        except AgentEffectReceiptError as error:
            _map_receipt_error(error)
        if receipt is None:
            missing = True
        else:
            terminal_receipts += 1

    status = AgentTurnPlanAdapterStatus.REPLAY_TERMINAL
    if missing:
        status = AgentTurnPlanAdapterStatus.FIRST_EXECUTION_UNSUPPORTED
    return _mint_resolution(
        status=status,
        output=expected_output,
        plan=exact_plan,
        terminal_receipt_count=terminal_receipts,
    )


__all__ = [
    "AGENT_TURN_OUTPUT_SCHEMA_VERSION",
    "MAX_AGENT_TURN_FIELD_BYTES",
    "MAX_AGENT_TURN_OUTPUT_EVENTS",
    "MAX_AGENT_TURN_RECEIPTS",
    "MAX_AGENT_TURN_RESPONSE_BYTES",
    "TURN_PLAN_ADAPTER_VERSION",
    "AgentTurnOutputEventName",
    "AgentTurnOutputEventV1",
    "AgentTurnOutputRoute",
    "AgentTurnOutputV1",
    "AgentTurnPlanAdapterError",
    "AgentTurnPlanAdapterErrorCode",
    "AgentTurnPlanAdapterStatus",
    "AgentTurnPlanReplayResolution",
    "build_agent_turn_output_v1",
    "project_agent_turn_execution_plan",
    "reconcile_agent_turn_output_replay",
    "validate_agent_turn_output_v1",
]
