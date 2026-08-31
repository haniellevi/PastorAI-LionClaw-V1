"""Offline contract tests for the fail-closed D3 checkpoint boundary."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.agent.context import (
    LegacyTermContext,
    TrustedAgentContext,
    TrustedContextError,
    validate_agent_input_state,
)
from app.agent.graph import get_compiled_graph
from app.agent.nodes import AgentState, AgentTurnEffects
from app.agent.private_checkpoint import (
    CHECKPOINT_NAMESPACE,
    CURRENT_EPHEMERAL_AGENT_STATE_KEYS,
    CURRENT_PRIVATE_CHECKPOINT_BLOCKERS,
    CURRENT_REPLAY_SENSITIVE_AGENT_STATE_KEYS,
    CURRENT_TURN_EFFECT_KEYS,
    PrivateCheckpointActivationBlocker,
    PrivateCheckpointActivationError,
    build_private_checkpoint_binding,
    build_private_checkpointer,
    reject_current_agent_state_rehydration,
)
from app.domain.agent_authz import PrivilegeContext

TENANT_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
CONVERSATION_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CONVERSATION_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
PESSOA_A = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _context(
    *,
    igreja_id: uuid.UUID = TENANT_A,
    conversation_id: uuid.UUID = CONVERSATION_A,
    pessoa_id: uuid.UUID = PESSOA_A,
) -> TrustedAgentContext:
    return TrustedAgentContext(
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        pessoa_id=pessoa_id,
        conversation_state="ia",
        igreja_nome="Igreja Privada",
        privilege=PrivilegeContext(pessoa_id=str(pessoa_id), tipo="visitante"),
        legacy_term=LegacyTermContext("v1", "v1"),
    )


def test_binding_is_derived_only_from_exact_trusted_context() -> None:
    binding = build_private_checkpoint_binding(_context())

    assert binding.igreja_id == TENANT_A
    assert binding.conversation_id == CONVERSATION_A
    assert binding.pessoa_id == PESSOA_A

    with pytest.raises(TrustedContextError, match="trusted agent context"):
        build_private_checkpoint_binding(
            {
                "igreja_id": TENANT_A,
                "conversation_id": CONVERSATION_A,
                "pessoa_id": PESSOA_A,
            }
        )


def test_thread_id_has_a_fixed_cross_process_vector_and_never_uses_hash() -> None:
    binding = build_private_checkpoint_binding(_context())

    assert binding.thread_id == (
        "d3v1_"
        "3486b9ec11a1e14659aba6ee6ff132a4deae36c880a3e599e3e07eb51ea96100"
    )


def test_scope_is_stable_and_changes_across_tenant_or_conversation() -> None:
    first = build_private_checkpoint_binding(_context())
    same = build_private_checkpoint_binding(_context())
    other_tenant = build_private_checkpoint_binding(_context(igreja_id=TENANT_B))
    other_conversation = build_private_checkpoint_binding(
        _context(conversation_id=CONVERSATION_B)
    )

    assert first.thread_id == same.thread_id
    assert first.thread_id != other_tenant.thread_id
    assert first.thread_id != other_conversation.thread_id


def test_person_binding_changes_without_changing_conversation_thread() -> None:
    other_person_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
    original = build_private_checkpoint_binding(_context())
    rebound = build_private_checkpoint_binding(_context(pessoa_id=other_person_id))

    assert rebound.pessoa_id == other_person_id
    assert rebound.thread_id == original.thread_id


def test_langgraph_config_is_non_authoritative_opaque_and_fresh() -> None:
    binding = build_private_checkpoint_binding(_context())
    first = binding.as_langgraph_config()
    second = binding.as_langgraph_config()

    assert first == {
        "configurable": {
            "thread_id": binding.thread_id,
            "checkpoint_ns": CHECKPOINT_NAMESPACE,
        }
    }
    assert first is not second
    assert first["configurable"] is not second["configurable"]

    rendered = repr(binding) + repr(first)
    for private_value in (
        str(TENANT_A),
        str(CONVERSATION_A),
        str(PESSOA_A),
        "Igreja Privada",
    ):
        assert private_value not in rendered


@pytest.mark.parametrize(
    "reserved_key",
    [
        "thread_id",
        "checkpoint_id",
        "checkpoint_ns",
        "checkpoint_map",
        "checkpoint",
        "memory",
        "messages",
        "conversation_summary",
        "recent_context",
    ],
)
def test_untrusted_state_cannot_inject_memory_or_checkpoint_configuration(
    reserved_key: str,
) -> None:
    state = {
        "texto": "oi",
        "pessoa": {},
        reserved_key: "caller-controlled",
    }

    with pytest.raises(TrustedContextError, match="reserved agent state key"):
        validate_agent_input_state(state)


def test_current_agent_state_is_explicitly_ephemeral_and_replay_sensitive() -> None:
    assert CURRENT_EPHEMERAL_AGENT_STATE_KEYS == set(AgentState.__annotations__)
    assert CURRENT_EPHEMERAL_AGENT_STATE_KEYS == {
        "texto",
        "pessoa",
        "route",
        "response",
        "turn_effects",
    }
    assert CURRENT_REPLAY_SENSITIVE_AGENT_STATE_KEYS == {"turn_effects"}
    assert CURRENT_TURN_EFFECT_KEYS == set(AgentTurnEffects.__annotations__)
    assert CURRENT_TURN_EFFECT_KEYS == {
        "events",
        "tool_calls",
        "apply_optout",
        "apply_consent_version",
        "intake_update",
    }

    with pytest.raises(PrivateCheckpointActivationError) as raised:
        reject_current_agent_state_rehydration(
            {
                "turn_effects": {
                    "events": [{"evento": "example"}],
                    "apply_optout": True,
                },
            }
        )

    assert raised.value.blockers == (
        PrivateCheckpointActivationBlocker.CURRENT_AGENT_STATE_REPLAY_UNSAFE,
        PrivateCheckpointActivationBlocker.STATELESS_FALLBACK_REPLAY_UNSAFE,
    )
    assert "example" not in str(raised.value)


def test_activation_errors_never_echo_state_context_or_factory_values() -> None:
    private_state_value = "private-state-value"
    private_context_value = "private-context-value"
    private_factory_value = "private-factory-value"

    with pytest.raises(PrivateCheckpointActivationError) as state_error:
        reject_current_agent_state_rehydration(
            {"turn_effects": {"events": [{"payload": private_state_value}]}}
        )
    with pytest.raises(TrustedContextError) as context_error:
        build_private_checkpoint_binding(
            {"igreja_id": private_context_value}
        )

    class ForbiddenFactory:
        def __repr__(self) -> str:
            return private_factory_value

        def create(self, *, binding: object) -> object:
            raise AssertionError("checkpoint factory must not be called")

    with pytest.raises(PrivateCheckpointActivationError) as factory_error:
        build_private_checkpointer(ForbiddenFactory(), context=_context())

    rendered = " ".join(
        (str(state_error.value), str(context_error.value), str(factory_error.value))
    )
    assert private_state_value not in rendered
    assert private_context_value not in rendered
    assert private_factory_value not in rendered


def test_factory_is_never_called_while_activation_is_blocked() -> None:
    class ForbiddenFactory:
        def create(self, *, binding: object) -> object:
            raise AssertionError("checkpoint factory must not be called")

    with pytest.raises(PrivateCheckpointActivationError) as raised:
        build_private_checkpointer(ForbiddenFactory(), context=_context())

    assert raised.value.blockers == CURRENT_PRIVATE_CHECKPOINT_BLOCKERS
    assert set(raised.value.blockers) == set(PrivateCheckpointActivationBlocker)


def test_false_context_is_rejected_before_factory_or_activation() -> None:
    calls = 0
    private_context_value = "private-false-context"

    class CountingFactory:
        def create(self, *, binding: object) -> object:
            nonlocal calls
            calls += 1
            return object()

    with pytest.raises(TrustedContextError, match="trusted agent context") as raised:
        build_private_checkpointer(
            CountingFactory(),
            context={"igreja_id": private_context_value},
        )

    assert calls == 0
    assert private_context_value not in str(raised.value)


def test_contract_has_no_memory_saver_or_postgres_saver_fallback() -> None:
    source = (
        Path(__file__)
        .parents[1]
        .joinpath("app/agent/private_checkpoint.py")
        .read_text(encoding="utf-8")
    )

    assert "MemorySaver" not in source
    assert "PostgresSaver" not in source
    assert "langgraph.checkpoint.memory" not in source


def test_current_compiled_graph_remains_stateless() -> None:
    get_compiled_graph.cache_clear()
    try:
        assert get_compiled_graph().checkpointer is None
    finally:
        get_compiled_graph.cache_clear()
