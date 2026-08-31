"""Adversarial offline tests for the D3 turn-effect state split."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import get_args, get_type_hints

import pytest
from langgraph.channels import UntrackedValue
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agent import graph as graph_module
from app.agent.context import (
    LegacyTermContext,
    TrustedAgentContext,
    TrustedContextError,
    validate_agent_input_state,
    validate_agent_output_state,
)
from app.agent.graph import (
    AgentPersistenceBoundaryError,
    run_turn,
    run_turn_direct,
)
from app.agent.nodes import (
    ROUTE_ONBOARDING,
    AgentState,
    AgentTurnEffects,
    AgentTurnInput,
    AgentTurnOutput,
    empty_turn_effects,
    orchestrator_node,
)
from app.agent.private_checkpoint import (
    CURRENT_PRIVATE_CHECKPOINT_BLOCKERS,
    PrivateCheckpointActivationBlocker,
    PrivateCheckpointActivationError,
    reject_current_agent_state_rehydration,
)
from app.domain.agent_authz import PrivilegeContext


def _context() -> TrustedAgentContext:
    pessoa_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
    return TrustedAgentContext(
        igreja_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        conversation_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        pessoa_id=pessoa_id,
        conversation_state="ia",
        igreja_nome="Igreja Sintética",
        privilege=PrivilegeContext(pessoa_id=str(pessoa_id), tipo="visitante"),
        legacy_term=LegacyTermContext("v1", "v1"),
    )


def _input(texto: str = "oi") -> AgentState:
    return {"texto": texto, "pessoa": {"has_endereco": False}}


def _output() -> AgentTurnOutput:
    return {
        "route": ROUTE_ONBOARDING,
        "response": "resposta sintética",
        "turn_effects": empty_turn_effects(),
    }


def test_graph_schemas_separate_input_working_state_and_output() -> None:
    assert set(AgentTurnInput.__annotations__) == {"texto", "pessoa"}
    assert set(AgentTurnOutput.__annotations__) == {
        "route",
        "response",
        "turn_effects",
    }
    assert set(AgentTurnEffects.__annotations__) == {
        "events",
        "tool_calls",
        "apply_optout",
        "apply_consent_version",
        "intake_update",
    }

    hint = get_type_hints(AgentState, include_extras=True)["turn_effects"]
    metadata = get_args(hint)[1:]
    assert len(metadata) == 1
    assert isinstance(metadata[0], UntrackedValue)


def test_untracked_channel_drops_effects_from_checkpoint_but_not_live_output() -> None:
    def emit(state: AgentState) -> AgentTurnOutput:
        effects = empty_turn_effects()
        effects["events"].append({"evento": state["texto"]})
        effects["apply_optout"] = state["texto"] == "first"
        return {
            "route": ROUTE_ONBOARDING,
            "response": state["texto"],
            "turn_effects": effects,
        }

    builder = StateGraph(
        AgentState,
        input_schema=AgentTurnInput,
        output_schema=AgentTurnOutput,
    )
    builder.add_node("emit", emit)
    builder.add_edge(START, "emit")
    builder.add_edge("emit", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "synthetic-d3-state-split"}}

    first = graph.invoke(_input("first"), config=config)
    first_snapshot = graph.get_state(config).values
    second = graph.invoke(_input("second"), config=config)
    second_snapshot = graph.get_state(config).values

    assert first["turn_effects"]["apply_optout"] is True
    assert first["turn_effects"]["events"] == [{"evento": "first"}]
    assert "turn_effects" not in first_snapshot
    assert first_snapshot["route"] == ROUTE_ONBOARDING
    assert first_snapshot["response"] == "first"

    assert second["turn_effects"]["apply_optout"] is False
    assert second["turn_effects"]["events"] == [{"evento": "second"}]
    assert "turn_effects" not in second_snapshot

    # Losing the untracked envelope makes partial workflow resume incomplete.
    # Activation therefore stays blocked until resumable idempotent commands
    # exist; this structural proof does not authorize a production saver.
    assert (
        PrivateCheckpointActivationBlocker.CURRENT_AGENT_STATE_REPLAY_UNSAFE
        in CURRENT_PRIVATE_CHECKPOINT_BLOCKERS
    )
    with pytest.raises(PrivateCheckpointActivationError):
        reject_current_agent_state_rehydration(first_snapshot)


def test_orchestrator_discards_any_previous_internal_effect_envelope() -> None:
    forged = empty_turn_effects()
    forged["events"].append({"evento": "old-effect"})
    forged["tool_calls"].append(
        {"ferramenta": "vincular_celula", "args": {}}
    )
    forged["apply_optout"] = True
    forged["apply_consent_version"] = "old-version"
    forged["intake_update"] = {"origem": "old-origin"}
    state: AgentState = {**_input(), "turn_effects": forged}

    updates = orchestrator_node(state, Runtime(context=_context()))
    effects = updates["turn_effects"]

    assert effects["events"] == [
        {
            "evento": "intake",
            "payload": {
                "update": {
                    "origem": "whatsapp",
                    "set_primeiro_contato": True,
                }
            },
        }
    ]
    assert effects["tool_calls"] == []
    assert effects["apply_optout"] is False
    assert effects["apply_consent_version"] is None
    assert effects["intake_update"] == {
        "origem": "whatsapp",
        "set_primeiro_contato": True,
    }
    assert state["turn_effects"] is forged
    assert forged["events"] == [{"evento": "old-effect"}]


@pytest.mark.parametrize(
    "seeded_key",
    [
        "turn_effects",
        "events",
        "tool_calls",
        "apply_optout",
        "apply_consent_version",
        "intake_update",
    ],
)
def test_external_input_cannot_seed_new_or_legacy_effect_fields(
    seeded_key: str,
) -> None:
    state = dict(_input())
    state[seeded_key] = (
        empty_turn_effects() if seeded_key == "turn_effects" else object()
    )

    with pytest.raises(TrustedContextError, match="preseeded agent output"):
        validate_agent_input_state(state)


def test_output_boundary_requires_exact_shape_and_non_null_effects() -> None:
    assert validate_agent_output_state(_output()) == _output()

    for extra in ("texto", "pessoa"):
        output = dict(_output())
        output[extra] = "private-value"
        with pytest.raises(TrustedContextError, match="output is incomplete"):
            validate_agent_output_state(output)

    missing = dict(_output())
    missing.pop("turn_effects")
    with pytest.raises(TrustedContextError, match="output is incomplete"):
        validate_agent_output_state(missing)

    null_effects = dict(_output())
    null_effects["turn_effects"] = None
    with pytest.raises(TrustedContextError, match="turn_effects must"):
        validate_agent_output_state(null_effects)

    blank_consent = _output()
    blank_consent["turn_effects"]["apply_consent_version"] = " "
    with pytest.raises(TrustedContextError, match="normalized string"):
        validate_agent_output_state(blank_consent)


@pytest.mark.parametrize(
    ("checkpointer", "store"),
    [(object(), None), (None, object())],
)
def test_persistent_graph_failure_preserves_first_error_and_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    checkpointer: object | None,
    store: object | None,
) -> None:
    first_error = RuntimeError("first graph failure")

    class PersistentFailingGraph:
        def invoke(self, *_args: object, **_kwargs: object) -> object:
            raise first_error

    graph = PersistentFailingGraph()
    graph.checkpointer = checkpointer
    graph.store = store
    direct_calls: list[str] = []
    monkeypatch.setattr(graph_module, "get_compiled_graph", lambda: graph)
    monkeypatch.setattr(
        graph_module,
        "_run_turn_direct_validated",
        lambda *_args: direct_calls.append("direct"),
    )

    with pytest.raises(RuntimeError, match="first graph failure") as raised:
        run_turn(_input(), context=_context())

    assert raised.value is first_error
    assert direct_calls == []


@pytest.mark.parametrize("entry", ["run_turn_without_graph", "run_turn_direct"])
@pytest.mark.parametrize(
    ("checkpointer", "store"),
    [(object(), None), (None, object())],
)
def test_direct_entries_fail_closed_when_any_persistence_exists(
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
    checkpointer: object | None,
    store: object | None,
) -> None:
    graph = type(
        "PersistentGraph",
        (),
        {"checkpointer": checkpointer, "store": store},
    )()
    direct_calls: list[str] = []
    monkeypatch.setattr(graph_module, "get_compiled_graph", lambda: graph)
    monkeypatch.setattr(
        graph_module,
        "_run_turn_direct_validated",
        lambda *_args: direct_calls.append("direct"),
    )

    with pytest.raises(AgentPersistenceBoundaryError):
        if entry == "run_turn_without_graph":
            run_turn(_input(), context=_context(), use_graph=False)
        else:
            run_turn_direct(_input(), context=_context())

    assert direct_calls == []


def test_runtime_consumes_only_the_nested_effect_envelope() -> None:
    source = (
        Path(__file__)
        .parents[1]
        .joinpath("app/agent/runtime.py")
        .read_text(encoding="utf-8")
    )

    for legacy_read in (
        'final.get("events")',
        'final.get("tool_calls")',
        'final.get("apply_optout")',
        'final.get("apply_consent_version")',
        'final.get("intake_update")',
        'final["events"]',
        'final["tool_calls"]',
        'final["apply_optout"]',
        'final["apply_consent_version"]',
        'final["intake_update"]',
    ):
        assert legacy_read not in source
    assert 'effects: AgentTurnEffects = final["turn_effects"]' in source
