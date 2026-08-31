"""Adversarial offline tests for stable D3 turn and effect identity."""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import app.agent.turn_identity as turn_identity_module
from app.agent.private_checkpoint import (
    CURRENT_PRIVATE_CHECKPOINT_BLOCKERS,
    PrivateCheckpointActivationBlocker,
)
from app.agent.turn_identity import (
    MAX_CANONICAL_INTEGER,
    MAX_CANONICAL_JSON_DEPTH,
    MAX_CANONICAL_JSON_NODES,
    MAX_CANONICAL_STRING_BYTES,
    MAX_EFFECT_INTENTS_PER_TURN,
    MAX_EFFECT_ORDINAL,
    MAX_PROVIDER_MESSAGE_ID_BYTES,
    AgentEffectIntent,
    AgentEffectIntentConflictError,
    AgentEffectIntentError,
    AgentEffectKind,
    AgentEffectSemanticSlot,
    AgentInboundProvider,
    AgentTurnContractErrorCode,
    AgentTurnIdentity,
    AgentTurnIdentityError,
    CanonicalJsonError,
    _binary_frame,
    build_agent_effect_intent,
    build_agent_turn_identity,
    canonical_json_bytes,
    digest_effect_payload,
    validate_agent_effect_intents,
)

TENANT_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
CONVERSATION_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CONVERSATION_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
INBOUND_A = uuid.UUID("33333333-3333-3333-3333-333333333333")
INBOUND_B = uuid.UUID("44444444-4444-4444-4444-444444444444")
PROVIDER_MESSAGE_A = "3EB0123456789ABCDEF"


def _identity(
    *,
    igreja_id: uuid.UUID = TENANT_A,
    conversation_id: uuid.UUID = CONVERSATION_A,
    inbound_message_id: uuid.UUID = INBOUND_A,
    provider_message_id: str = PROVIDER_MESSAGE_A,
) -> AgentTurnIdentity:
    return build_agent_turn_identity(
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        inbound_message_id=inbound_message_id,
        provider_message_id=provider_message_id,
    )


def _effect(
    *,
    identity: AgentTurnIdentity | None = None,
    kind: AgentEffectKind = AgentEffectKind.TOOL_CALL,
    ordinal: int = 0,
    payload: object = None,
) -> AgentEffectIntent:
    return build_agent_effect_intent(
        identity or _identity(),
        kind=kind,
        ordinal=ordinal,
        payload=payload,
    )


def test_turn_identity_has_fixed_binary_framed_vector() -> None:
    identity = _identity()

    assert identity.turn_id == (
        "agent_turn_v1_"
        "b978939e8c9d545cd412dad1a9bde9b42bccfa362e452b3cc9d1429c641a2f53"
    )


def test_effect_and_payload_have_fixed_independent_vectors() -> None:
    effect = _effect(
        kind=AgentEffectKind.TOOL_CALL,
        ordinal=7,
        payload={"args": {"celula_id": "synthetic"}, "tool": "consultar"},
    )

    assert effect.semantic_slot is AgentEffectSemanticSlot.TOOL_CALL
    assert effect.effect_id == (
        "agent_effect_v1_"
        "626f2a4e23d5cbda66f211ccab36f6c5a2142d6dd17a902a1500d102dc10c9bd"
    )
    assert effect.intent_id == effect.effect_id
    assert effect.payload_digest == (
        "agent_payload_v1_"
        "40af053474a7af2a1bf8c4363e4785ec258802aff964624335857fe392264ddf"
    )


def test_hash_vectors_are_stable_in_a_fresh_process() -> None:
    backend = Path(__file__).parents[1]
    script = """
import json
import uuid
from app.agent.turn_identity import (
    AgentEffectKind,
    build_agent_effect_intent,
    build_agent_turn_identity,
)

identity = build_agent_turn_identity(
    igreja_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    conversation_id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    inbound_message_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
    provider_message_id="3EB0123456789ABCDEF",
)
effect = build_agent_effect_intent(
    identity,
    kind=AgentEffectKind.TOOL_CALL,
    ordinal=7,
    payload={"tool": "consultar", "args": {"celula_id": "synthetic"}},
)
print(json.dumps([identity.turn_id, effect.effect_id, effect.payload_digest]))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(backend)
    env["PYTHONHASHSEED"] = "random"

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    identity = _identity()
    effect = _effect(
        kind=AgentEffectKind.TOOL_CALL,
        ordinal=7,
        payload={"args": {"celula_id": "synthetic"}, "tool": "consultar"},
    )
    assert json.loads(completed.stdout) == [
        identity.turn_id,
        effect.effect_id,
        effect.payload_digest,
    ]


@pytest.mark.parametrize(
    "changed",
    [
        {"igreja_id": TENANT_B},
        {"conversation_id": CONVERSATION_B},
        {"inbound_message_id": INBOUND_B},
        {"provider_message_id": "3EB0123456789ABCDE0"},
    ],
)
def test_each_authoritative_component_isolates_turn_identity(
    changed: dict[str, object],
) -> None:
    assert _identity(**changed).turn_id != _identity().turn_id  # type: ignore[arg-type]


def test_provider_message_id_is_opaque_and_never_normalized() -> None:
    composed = _identity(provider_message_id="Evolution-é")
    decomposed = _identity(provider_message_id="Evolution-e\u0301")
    with_colon_a = _identity(provider_message_id="a:bc")
    with_colon_b = _identity(provider_message_id="ab:c")

    assert composed.provider_message_id == "Evolution-é"
    assert decomposed.provider_message_id == "Evolution-e\u0301"
    assert composed.turn_id != decomposed.turn_id
    assert with_colon_a.turn_id != with_colon_b.turn_id
    assert _binary_frame(b"a", b"bc") != _binary_frame(b"ab", b"c")


def test_provider_message_id_accepts_exact_byte_limit() -> None:
    provider_message_id = "x" * MAX_PROVIDER_MESSAGE_ID_BYTES

    assert _identity(
        provider_message_id=provider_message_id
    ).provider_message_id == provider_message_id

    multibyte_at_limit = "é" * (MAX_PROVIDER_MESSAGE_ID_BYTES // 2)
    assert len(multibyte_at_limit.encode("utf-8")) == MAX_PROVIDER_MESSAGE_ID_BYTES
    assert _identity(
        provider_message_id=multibyte_at_limit
    ).provider_message_id == multibyte_at_limit

    with pytest.raises(AgentTurnIdentityError):
        _identity(provider_message_id=multibyte_at_limit + "é")


@pytest.mark.parametrize(
    "field",
    ["igreja_id", "conversation_id", "inbound_message_id"],
)
def test_nil_or_non_uuid_identity_components_fail_closed(field: str) -> None:
    values = {
        "igreja_id": TENANT_A,
        "conversation_id": CONVERSATION_A,
        "inbound_message_id": INBOUND_A,
        "provider_message_id": PROVIDER_MESSAGE_A,
    }
    for invalid in (uuid.UUID(int=0), str(values[field]), None, True):
        values[field] = invalid
        with pytest.raises(AgentTurnIdentityError) as raised:
            build_agent_turn_identity(**values)  # type: ignore[arg-type]
        assert raised.value.code is AgentTurnContractErrorCode.INVALID_UUID


@pytest.mark.parametrize(
    "provider_message_id",
    [
        "",
        " leading",
        "trailing ",
        "line\nbreak",
        "null\x00byte",
        "zero\u200dwidth",
        "x" * (MAX_PROVIDER_MESSAGE_ID_BYTES + 1),
        "\ud800",
    ],
)
def test_provider_message_id_rejects_ambiguity_and_excess(
    provider_message_id: str,
) -> None:
    with pytest.raises(AgentTurnIdentityError) as raised:
        _identity(provider_message_id=provider_message_id)
    assert (
        raised.value.code
        is AgentTurnContractErrorCode.INVALID_PROVIDER_MESSAGE_ID
    )


def test_provider_requires_the_exact_closed_enum() -> None:
    with pytest.raises(AgentTurnIdentityError) as raised:
        AgentTurnIdentity(
            igreja_id=TENANT_A,
            conversation_id=CONVERSATION_A,
            inbound_message_id=INBOUND_A,
            provider="evolution",  # type: ignore[arg-type]
            provider_message_id=PROVIDER_MESSAGE_A,
        )
    assert raised.value.code is AgentTurnContractErrorCode.INVALID_PROVIDER


def test_effect_id_excludes_payload_while_digest_binds_payload_and_kind() -> None:
    first = _effect(payload={"tool": "one"})
    changed_payload = _effect(payload={"tool": "two"})
    changed_kind = _effect(kind=AgentEffectKind.AUDIT_EVENT, payload={"tool": "one"})
    changed_ordinal = _effect(ordinal=1, payload={"tool": "one"})

    assert first.effect_id == changed_payload.effect_id
    assert first.payload_digest != changed_payload.payload_digest
    assert first.effect_id != changed_kind.effect_id
    assert first.payload_digest != changed_kind.payload_digest
    assert first.effect_id != changed_ordinal.effect_id
    assert first.payload_digest != changed_ordinal.payload_digest


def test_payload_digest_is_stable_per_effect_and_isolated_across_turns() -> None:
    payload = {"status": "synthetic"}
    first = _effect(payload=payload)
    replay = _effect(payload={"status": "synthetic"})
    other_tenant = _effect(identity=_identity(igreja_id=TENANT_B), payload=payload)
    other_turn = _effect(
        identity=_identity(inbound_message_id=INBOUND_B),
        payload=payload,
    )

    assert first.effect_id == replay.effect_id
    assert first.payload_digest == replay.payload_digest
    assert first.effect_id != other_tenant.effect_id
    assert first.payload_digest != other_tenant.payload_digest
    assert first.effect_id != other_turn.effect_id
    assert first.payload_digest != other_turn.payload_digest


@pytest.mark.parametrize("kind", list(AgentEffectKind))
def test_every_minimum_effect_kind_has_a_versioned_semantic_slot(
    kind: AgentEffectKind,
) -> None:
    effect = _effect(kind=kind, payload={})

    assert effect.semantic_slot.value == f"v1/{kind.value}"


def test_ordinal_is_stable_plan_occurrence_not_construction_order() -> None:
    first_order = [
        _effect(kind=AgentEffectKind.TOOL_CALL, ordinal=4, payload={"n": 4}),
        _effect(kind=AgentEffectKind.AUDIT_EVENT, ordinal=2, payload={"n": 2}),
    ]
    reverse_order = [
        _effect(kind=AgentEffectKind.AUDIT_EVENT, ordinal=2, payload={"n": 2}),
        _effect(kind=AgentEffectKind.TOOL_CALL, ordinal=4, payload={"n": 4}),
    ]

    first_ids = {(item.kind, item.ordinal): item.effect_id for item in first_order}
    reverse_ids = {
        (item.kind, item.ordinal): item.effect_id for item in reverse_order
    }
    assert first_ids == reverse_ids


@pytest.mark.parametrize("ordinal", [-1, True, False, 1.0, "0", MAX_EFFECT_ORDINAL + 1])
def test_effect_ordinal_is_an_exact_bounded_nonnegative_int(
    ordinal: object,
) -> None:
    with pytest.raises(AgentEffectIntentError) as raised:
        _effect(ordinal=ordinal)  # type: ignore[arg-type]
    assert raised.value.code is AgentTurnContractErrorCode.INVALID_EFFECT_ORDINAL


def test_effect_kind_requires_exact_enum() -> None:
    with pytest.raises(AgentEffectIntentError) as raised:
        _effect(kind="tool_call")  # type: ignore[arg-type]
    assert raised.value.code is AgentTurnContractErrorCode.INVALID_EFFECT_KIND


def test_canonical_json_has_fixed_order_encoding_and_scalar_semantics() -> None:
    payload = {
        "z": {"b": 2},
        "a": [None, True, False, 0, -1, "á"],
    }

    assert canonical_json_bytes(payload) == (
        b'{"a":[null,true,false,0,-1,"\xc3\xa1"],"z":{"b":2}}'
    )
    effect_id = _effect(kind=AgentEffectKind.AUDIT_EVENT).effect_id
    assert digest_effect_payload(effect_id, AgentEffectKind.AUDIT_EVENT, True) != (
        digest_effect_payload(effect_id, AgentEffectKind.AUDIT_EVENT, 1)
    )


def test_payload_digest_requires_a_valid_effect_identity() -> None:
    with pytest.raises(AgentEffectIntentError) as raised:
        digest_effect_payload(
            "caller-controlled",
            AgentEffectKind.AUDIT_EVENT,
            {},
        )
    assert raised.value.code is AgentTurnContractErrorCode.INVALID_EFFECT_INTENT


@pytest.mark.parametrize(
    "unsupported",
    [
        1.0,
        float("nan"),
        b"bytes",
        ("tuple",),
        {"set"},
        uuid.UUID("55555555-5555-5555-5555-555555555555"),
        dt.datetime(2026, 8, 31, tzinfo=dt.UTC),
        object(),
    ],
)
def test_canonical_json_rejects_non_exact_json_types(unsupported: object) -> None:
    with pytest.raises(CanonicalJsonError) as raised:
        canonical_json_bytes(unsupported)
    assert raised.value.code is AgentTurnContractErrorCode.UNSUPPORTED_JSON_TYPE


def test_canonical_json_rejects_container_subclasses_and_non_string_keys() -> None:
    class ListSubclass(list[object]):
        pass

    class DictSubclass(dict[str, object]):
        pass

    for payload in (ListSubclass(), DictSubclass(), {1: "value"}):
        with pytest.raises(CanonicalJsonError) as raised:
            canonical_json_bytes(payload)
        assert raised.value.code is AgentTurnContractErrorCode.UNSUPPORTED_JSON_TYPE


@pytest.mark.parametrize(
    "integer",
    [MAX_CANONICAL_INTEGER + 1, -MAX_CANONICAL_INTEGER - 1],
)
def test_canonical_json_rejects_integers_outside_portable_range(
    integer: int,
) -> None:
    with pytest.raises(CanonicalJsonError) as raised:
        canonical_json_bytes(integer)
    assert raised.value.code is AgentTurnContractErrorCode.JSON_INTEGER_OUT_OF_RANGE


def test_canonical_json_rejects_cycles_depth_node_and_size_exhaustion() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)
    too_deep: object = None
    for _ in range(MAX_CANONICAL_JSON_DEPTH + 1):
        too_deep = [too_deep]

    cases = (
        (cyclic, AgentTurnContractErrorCode.JSON_CYCLE_DETECTED),
        (too_deep, AgentTurnContractErrorCode.JSON_DEPTH_EXCEEDED),
        (
            [None] * MAX_CANONICAL_JSON_NODES,
            AgentTurnContractErrorCode.JSON_NODE_LIMIT_EXCEEDED,
        ),
        ("x" * 32_769, AgentTurnContractErrorCode.JSON_SIZE_EXCEEDED),
        ("\ud800", AgentTurnContractErrorCode.JSON_INVALID_UNICODE),
    )
    for payload, expected_code in cases:
        with pytest.raises(CanonicalJsonError) as raised:
            canonical_json_bytes(payload)
        assert raised.value.code is expected_code


def test_canonical_json_aborts_streaming_before_repeated_escaped_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_encoder = turn_identity_module.json.JSONEncoder
    yielded_chunks = 0

    class CountingEncoder(real_encoder):
        def iterencode(
            self,
            value: object,
            _one_shot: bool = False,
        ) -> object:
            nonlocal yielded_chunks
            for chunk in super().iterencode(value, _one_shot=_one_shot):
                yielded_chunks += 1
                if yielded_chunks > 3:
                    raise AssertionError("canonical encoder did not abort early")
                yield chunk

    monkeypatch.setattr(
        turn_identity_module.json,
        "JSONEncoder",
        CountingEncoder,
    )
    escaped_expansion = "\x00" * MAX_CANONICAL_STRING_BYTES
    payload = [escaped_expansion] * 100

    with pytest.raises(CanonicalJsonError) as raised:
        canonical_json_bytes(payload)

    assert raised.value.code is AgentTurnContractErrorCode.JSON_SIZE_EXCEEDED
    assert yielded_chunks <= 3


def test_duplicate_occurrence_and_payload_conflict_are_distinct() -> None:
    original = _effect(payload={"value": "same"})
    duplicate = _effect(payload={"value": "same"})
    conflict = _effect(payload={"value": "different"})

    with pytest.raises(AgentEffectIntentError) as duplicate_error:
        validate_agent_effect_intents(_identity(), [original, duplicate])
    assert (
        duplicate_error.value.code
        is AgentTurnContractErrorCode.DUPLICATE_SEMANTIC_SLOT
    )

    with pytest.raises(AgentEffectIntentConflictError) as conflict_error:
        validate_agent_effect_intents(_identity(), [original, conflict])
    assert (
        conflict_error.value.code
        is AgentTurnContractErrorCode.PAYLOAD_DIGEST_CONFLICT
    )


def test_effect_collection_accepts_distinct_slots_and_ordinals_in_one_turn() -> None:
    effects = [
        _effect(kind=AgentEffectKind.TOOL_CALL, ordinal=0, payload={"n": 0}),
        _effect(kind=AgentEffectKind.TOOL_CALL, ordinal=1, payload={"n": 1}),
        _effect(kind=AgentEffectKind.AUDIT_EVENT, ordinal=0, payload={"n": 0}),
    ]

    assert validate_agent_effect_intents(_identity(), effects) == tuple(effects)


def test_effect_collection_has_a_small_explicit_pre_iteration_cap() -> None:
    effects = [
        _effect(ordinal=ordinal, payload={"n": ordinal})
        for ordinal in range(MAX_EFFECT_INTENTS_PER_TURN + 1)
    ]

    with pytest.raises(AgentEffectIntentError) as raised:
        validate_agent_effect_intents(_identity(), effects)
    assert (
        raised.value.code
        is AgentTurnContractErrorCode.EFFECT_COLLECTION_LIMIT_EXCEEDED
    )


def test_effect_collection_rejects_mixed_turns_and_non_plain_sequences() -> None:
    first = _effect(identity=_identity())
    second = _effect(identity=_identity(inbound_message_id=INBOUND_B))

    with pytest.raises(AgentEffectIntentError) as mixed:
        validate_agent_effect_intents(_identity(), [first, second])
    assert (
        mixed.value.code
        is AgentTurnContractErrorCode.UNEXPECTED_TURN_IDENTITY
    )

    for invalid in ({}, iter([first]), {first}):
        with pytest.raises(AgentEffectIntentError) as invalid_error:
            validate_agent_effect_intents(_identity(), invalid)
        assert (
            invalid_error.value.code
            is AgentTurnContractErrorCode.INVALID_EFFECT_COLLECTION
        )


@pytest.mark.parametrize(
    "wrong_identity",
    [
        _identity(igreja_id=TENANT_B),
        _identity(inbound_message_id=INBOUND_B),
    ],
)
def test_homogeneous_wrong_turn_collection_is_rejected_against_expected_identity(
    wrong_identity: AgentTurnIdentity,
) -> None:
    wrong_effects = [
        _effect(identity=wrong_identity, ordinal=0, payload={"n": 0}),
        _effect(identity=wrong_identity, ordinal=1, payload={"n": 1}),
    ]

    with pytest.raises(AgentEffectIntentError) as raised:
        validate_agent_effect_intents(_identity(), wrong_effects)
    assert (
        raised.value.code
        is AgentTurnContractErrorCode.UNEXPECTED_TURN_IDENTITY
    )


def test_structurally_adulterated_identity_or_effect_is_rejected() -> None:
    identity = _identity()
    object.__setattr__(identity, "turn_id", "agent_turn_v1_" + "0" * 64)
    with pytest.raises(AgentTurnIdentityError) as identity_error:
        build_agent_effect_intent(
            identity,
            kind=AgentEffectKind.AUDIT_EVENT,
            ordinal=0,
            payload={},
        )
    assert (
        identity_error.value.code
        is AgentTurnContractErrorCode.INVALID_TURN_IDENTITY
    )

    effect = _effect()
    object.__setattr__(effect, "effect_id", "agent_effect_v1_" + "0" * 64)
    with pytest.raises(AgentEffectIntentError) as effect_error:
        validate_agent_effect_intents(_identity(), [effect])
    assert (
        effect_error.value.code
        is AgentTurnContractErrorCode.INVALID_EFFECT_INTENT
    )


@pytest.mark.parametrize(
    "invalid_turn_id",
    [
        "é",
        "agent_turn_v1_short",
        "agent_turn_v1_" + "A" * 64,
    ],
)
def test_noncanonical_turn_ids_fail_with_sanitized_identity_error(
    invalid_turn_id: str,
) -> None:
    identity = _identity()
    object.__setattr__(identity, "turn_id", invalid_turn_id)

    with pytest.raises(AgentTurnIdentityError) as raised:
        build_agent_effect_intent(
            identity,
            kind=AgentEffectKind.AUDIT_EVENT,
            ordinal=0,
            payload={},
        )

    assert (
        raised.value.code
        is AgentTurnContractErrorCode.INVALID_TURN_IDENTITY
    )

    malformed_effect = _effect()
    object.__setattr__(malformed_effect, "payload_digest", object())
    with pytest.raises(AgentEffectIntentError) as malformed_error:
        validate_agent_effect_intents(_identity(), [malformed_effect])
    assert (
        malformed_error.value.code
        is AgentTurnContractErrorCode.INVALID_EFFECT_INTENT
    )


def test_repr_and_errors_never_echo_identity_or_payload_data() -> None:
    private_provider_id = "PRIVATE-PROVIDER-MESSAGE-ID"
    private_payload = "PRIVATE-PAYLOAD-CONTENT"
    identity = _identity(provider_message_id=private_provider_id)
    effect = _effect(identity=identity, payload={"private": private_payload})

    with pytest.raises(CanonicalJsonError) as payload_error:
        canonical_json_bytes({"private": object()})
    with pytest.raises(AgentTurnIdentityError) as identity_error:
        _identity(provider_message_id=f" {private_provider_id}")

    rendered = " ".join(
        (
            repr(identity),
            repr(effect),
            repr(payload_error.value),
            str(payload_error.value),
            repr(identity_error.value),
            str(identity_error.value),
        )
    )
    for private_value in (
        private_provider_id,
        private_payload,
        str(TENANT_A),
        str(CONVERSATION_A),
        str(INBOUND_A),
        identity.turn_id,
        effect.effect_id,
        effect.payload_digest,
    ):
        assert private_value not in rendered


def test_repr_safety_is_not_a_serialization_or_logging_boundary() -> None:
    identity = _identity()

    raw_mapping = dataclasses.asdict(identity)
    assert raw_mapping["igreja_id"] == TENANT_A
    assert raw_mapping["conversation_id"] == CONVERSATION_A
    assert raw_mapping["inbound_message_id"] == INBOUND_A
    assert raw_mapping["provider_message_id"] == PROVIDER_MESSAGE_A
    assert str(TENANT_A) not in repr(identity)


def test_claim_id_is_absent_from_identity_fields_and_hash_contract() -> None:
    source_path = Path(__file__).parents[1] / "app/agent/turn_identity.py"
    source = source_path.read_text(encoding="utf-8")

    assert "claim_id" not in AgentTurnIdentity.__annotations__
    assert "claim_id" not in AgentEffectIntent.__annotations__
    assert "claim_id" not in source


def test_contract_is_stdlib_only_and_has_no_runtime_wiring() -> None:
    source_path = Path(__file__).parents[1] / "app/agent/turn_identity.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        (node.module or "").split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )

    assert imported_roots <= {
        "__future__",
        "dataclasses",
        "enum",
        "hashlib",
        "hmac",
        "json",
        "typing",
        "uuid",
    }
    assert imported_roots.isdisjoint(
        {
            "app",
            "httpx",
            "langgraph",
            "psycopg",
            "requests",
            "sqlalchemy",
        }
    )


def test_current_agent_state_remains_explicitly_replay_unsafe() -> None:
    assert (
        PrivateCheckpointActivationBlocker.CURRENT_AGENT_STATE_REPLAY_UNSAFE
        in CURRENT_PRIVATE_CHECKPOINT_BLOCKERS
    )
