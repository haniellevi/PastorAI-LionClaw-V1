"""LangGraph wiring for the Orchestrator multi-agent (SPEC 3.4 / delta-034).

The graph has the orchestrator (supervisor) as the single entry node. A
conditional edge dispatches to exactly one sub-agent based on the route the
supervisor chose; every sub-agent then terminates the turn. This encodes the
core invariant: one entry, one exit, one reply.

`run_turn` executes a single turn and returns the merged state. It prefers the
compiled, stateless LangGraph and falls back to direct execution of the same
node functions so the logic stays testable without a running graph backend.
Durable checkpointing is intentionally disabled until
a supported external saver is installed; process memory must not grow with the
number of conversations.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langgraph.runtime import Runtime

from app.agent.context import (
    TrustedAgentContext,
    TrustedContextError,
    require_trusted_context,
    validate_agent_input_state,
    validate_agent_node_state,
    validate_agent_output_state,
)
from app.agent.nodes import (
    ROUTE_HANDOFF,
    ROUTE_ONBOARDING,
    ROUTE_OPTOUT,
    ROUTE_REPORT,
    SUBAGENTS,
    AgentState,
    AgentTurnInput,
    AgentTurnOutput,
    empty_turn_effects,
    handoff_node,
    onboarding_node,
    optout_node,
    orchestrator_node,
    report_capture_node,
    route_intent,
)
from app.agent.nodes import (
    ROUTE_CONSENT,
    consent_node,
)

logger = logging.getLogger("pastorai.agent.graph")


class AgentPersistenceBoundaryError(RuntimeError):
    """Direct execution is unsafe while graph persistence may be present."""


def _snapshot_agent_input(state: AgentState) -> AgentState:
    """Return a detached, canonical copy of the only accepted input fields."""
    validated = validate_agent_input_state(state)
    return {
        "texto": validated["texto"],
        "pessoa": dict(validated["pessoa"]),
    }


def _merge_state(base: AgentState, updates: dict[str, Any]) -> AgentState:
    """Merge a node update with replacement semantics for every channel."""
    merged: AgentState = dict(base)  # type: ignore[assignment]
    merged.update(updates)  # type: ignore[typeddict-item]
    return merged


def _project_agent_output(state: AgentState | object) -> AgentTurnOutput:
    """Validate and detach the only values the effect runtime may consume."""
    working = validate_agent_node_state(state)
    required = {"route", "response", "turn_effects"}
    if not required.issubset(working):
        raise TrustedContextError("agent turn output is incomplete")
    effects = working["turn_effects"]
    projected: AgentTurnOutput = {
        "route": working["route"],
        "response": working["response"],
        "turn_effects": {
            "events": list(effects["events"]),
            "tool_calls": list(effects["tool_calls"]),
            "apply_optout": effects["apply_optout"],
            "apply_consent_version": effects["apply_consent_version"],
            "intake_update": dict(effects["intake_update"]),
        },
    }
    validate_agent_output_state(projected)
    return projected


def _run_turn_direct_validated(
    state: AgentState, context: TrustedAgentContext
) -> AgentTurnOutput:
    """Run direct nodes after the untrusted input boundary was validated."""
    runtime = Runtime(context=context)
    working: AgentState = {
        **_snapshot_agent_input(state),
        "turn_effects": empty_turn_effects(),
    }
    orchestrator_updates = orchestrator_node(working, runtime)
    after_orchestrator = _merge_state(working, orchestrator_updates)
    route = after_orchestrator.get("route") or ROUTE_ONBOARDING
    subagent = SUBAGENTS.get(route, onboarding_node)
    updates = subagent(after_orchestrator, runtime)
    final = _merge_state(after_orchestrator, updates)
    validate_agent_node_state(final)
    return _project_agent_output(final)


def run_turn_direct(
    state: AgentState, *, context: TrustedAgentContext
) -> AgentTurnOutput:
    """Execute one turn directly after validating context and input once."""
    trusted = require_trusted_context(context)
    pristine = _snapshot_agent_input(state)
    _require_persistence_absent_for_direct_execution()
    return _run_turn_direct_validated(pristine, trusted)


class _TrustedCompiledGraph:
    """Narrow adapter that validates raw inputs before LangGraph reducers."""

    def __init__(self, compiled: Any) -> None:
        self._compiled = compiled

    @property
    def checkpointer(self) -> Any:
        return self._compiled.checkpointer

    @property
    def store(self) -> Any:
        return self._compiled.store

    def invoke(
        self,
        state: AgentState,
        *,
        context: TrustedAgentContext | None = None,
        **kwargs: Any,
    ) -> AgentTurnOutput:
        detached = _snapshot_agent_input(state)
        trusted = require_trusted_context(context)
        # This value is server-created after the external input validation.
        # The entry node resets it again, so compiled and direct paths both
        # start from an explicit, complete, unexecuted effect envelope.
        internal_input: AgentState = {
            **detached,
            "turn_effects": empty_turn_effects(),
        }
        result = self._compiled.invoke(
            internal_input,
            context=trusted,
            **kwargs,
        )
        return _project_agent_output(result)


@lru_cache
def get_compiled_graph() -> Any:
    """Build and compile the stateless LangGraph (cached per process)."""
    from langgraph.graph import END, START, StateGraph  # noqa: PLC0415

    builder = StateGraph(
        AgentState,
        context_schema=TrustedAgentContext,
        input_schema=AgentTurnInput,
        output_schema=AgentTurnOutput,
    )
    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node(ROUTE_HANDOFF, handoff_node)
    builder.add_node(ROUTE_OPTOUT, optout_node)
    builder.add_node(ROUTE_CONSENT, consent_node)
    builder.add_node(ROUTE_REPORT, report_capture_node)
    builder.add_node(ROUTE_ONBOARDING, onboarding_node)

    builder.add_edge(START, "orchestrator")
    builder.add_conditional_edges(
        "orchestrator",
        lambda s: s.get("route") or ROUTE_ONBOARDING,
        {
            ROUTE_HANDOFF: ROUTE_HANDOFF,
            ROUTE_OPTOUT: ROUTE_OPTOUT,
            ROUTE_CONSENT: ROUTE_CONSENT,
            ROUTE_REPORT: ROUTE_REPORT,
            ROUTE_ONBOARDING: ROUTE_ONBOARDING,
        },
    )
    for route in (
        ROUTE_HANDOFF,
        ROUTE_OPTOUT,
        ROUTE_CONSENT,
        ROUTE_REPORT,
        ROUTE_ONBOARDING,
    ):
        builder.add_edge(route, END)

    _warn_if_checkpoint_url_is_configured()
    return _TrustedCompiledGraph(builder.compile())


def _warn_if_checkpoint_url_is_configured() -> None:
    """Make an unimplemented durable checkpoint configuration visible.

    Falling back to ``MemorySaver`` would retain every conversation in the
    process for the lifetime of this cached graph. Until the external saver is
    installed, the safe behaviour is a stateless graph and an explicit warning
    rather than pretending that a configured URL is durable.
    """
    from app.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    if settings.agent_graph_checkpoint_url:
        logger.warning(
            "AGENT_GRAPH_CHECKPOINT_URL is configured, but no durable "
            "LangGraph checkpointer is installed; running without checkpoint "
            "persistence"
        )


def run_turn(
    state: AgentState,
    *,
    context: TrustedAgentContext,
    use_graph: bool = True,
) -> AgentTurnOutput:
    """Run a single orchestrator turn, returning the merged final state.

    Backend execution failures fall back only while checkpointer and store are
    proven absent. Trust-boundary failures and any persistent or indeterminate
    graph boundary propagate without direct execution.
    """
    trusted = require_trusted_context(context)
    pristine = _snapshot_agent_input(state)

    if use_graph:
        graph: Any | None = None
        try:
            graph = get_compiled_graph()
            result = graph.invoke(_snapshot_agent_input(pristine), context=trusted)
            return _project_agent_output(result)
        except TrustedContextError:
            raise
        except Exception:  # noqa: BLE001 - resilience: never drop a turn
            if graph is None or not _persistence_is_proven_absent(graph):
                logger.exception(
                    "LangGraph turn failed with a persistence boundary; "
                    "direct fallback blocked"
                )
                raise
            logger.exception("LangGraph turn failed; using direct fallback")
            return _run_turn_direct_validated(pristine, trusted)
    _require_persistence_absent_for_direct_execution()
    return _run_turn_direct_validated(pristine, trusted)


def _persistence_is_proven_absent(graph: object) -> bool:
    """Allow direct fallback only for a graph with no saver and no store."""
    try:
        return graph.checkpointer is None and graph.store is None  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - absence cannot be inferred on failure
        return False


def _require_persistence_absent_for_direct_execution() -> None:
    """Fail closed unless the active compiled graph proves it is stateless."""
    graph = get_compiled_graph()
    if not _persistence_is_proven_absent(graph):
        raise AgentPersistenceBoundaryError(
            "direct agent execution requires checkpointer and store to be absent"
        )


# Re-export for callers that route by intent without running the graph.
__all__ = [
    "AgentPersistenceBoundaryError",
    "run_turn",
    "run_turn_direct",
    "get_compiled_graph",
    "route_intent",
]
