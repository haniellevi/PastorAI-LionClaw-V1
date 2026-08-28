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
)
from app.agent.nodes import (
    ROUTE_HANDOFF,
    ROUTE_ONBOARDING,
    ROUTE_OPTOUT,
    ROUTE_REPORT,
    SUBAGENTS,
    AgentState,
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


def _snapshot_agent_input(state: AgentState) -> AgentState:
    """Return a detached, canonical copy of the only accepted input fields."""
    validated = validate_agent_input_state(state)
    return {
        "texto": validated["texto"],
        "pessoa": dict(validated["pessoa"]),
    }


def _merge_state(base: AgentState, updates: dict[str, Any]) -> AgentState:
    """Merge a node's partial update, accumulating list fields (events/tools)."""
    merged: AgentState = dict(base)  # type: ignore[assignment]
    for key, value in updates.items():
        if key in ("events", "tool_calls") and isinstance(value, list):
            existing = list(merged.get(key, []) or [])
            merged[key] = existing + value  # type: ignore[literal-required]
        else:
            merged[key] = value  # type: ignore[literal-required]
    return merged


def _run_turn_direct_validated(
    state: AgentState, context: TrustedAgentContext
) -> AgentState:
    """Run direct nodes after the untrusted input boundary was validated."""
    runtime = Runtime(context=context)
    working: AgentState = {
        **_snapshot_agent_input(state),
        "events": [],
        "tool_calls": [],
    }
    orchestrator_updates = orchestrator_node(working, runtime)
    after_orchestrator = _merge_state(working, orchestrator_updates)
    route = after_orchestrator.get("route") or ROUTE_ONBOARDING
    subagent = SUBAGENTS.get(route, onboarding_node)
    updates = subagent(after_orchestrator, runtime)
    final = _merge_state(after_orchestrator, updates)
    validate_agent_node_state(final)
    return final


def run_turn_direct(
    state: AgentState, *, context: TrustedAgentContext
) -> AgentState:
    """Execute one turn directly after validating context and input once."""
    trusted = require_trusted_context(context)
    pristine = _snapshot_agent_input(state)
    return _run_turn_direct_validated(pristine, trusted)


class _TrustedCompiledGraph:
    """Narrow adapter that validates raw inputs before LangGraph reducers."""

    def __init__(self, compiled: Any) -> None:
        self._compiled = compiled

    @property
    def checkpointer(self) -> Any:
        return self._compiled.checkpointer

    def invoke(
        self,
        state: AgentState,
        *,
        context: TrustedAgentContext | None = None,
        **kwargs: Any,
    ) -> AgentState:
        detached = _snapshot_agent_input(state)
        trusted = require_trusted_context(context)
        result = self._compiled.invoke(detached, context=trusted, **kwargs)
        validate_agent_node_state(result)
        return result  # type: ignore[no-any-return]


@lru_cache
def get_compiled_graph() -> Any:
    """Build and compile the stateless LangGraph (cached per process)."""
    from langgraph.graph import END, START, StateGraph  # noqa: PLC0415

    builder = StateGraph(AgentState, context_schema=TrustedAgentContext)
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
) -> AgentState:
    """Run a single orchestrator turn, returning the merged final state.

    Backend execution failures fall back to the direct path. Trust-boundary
    failures always propagate and never enter the fallback.
    """
    trusted = require_trusted_context(context)
    pristine = _snapshot_agent_input(state)

    if use_graph:
        try:
            graph = get_compiled_graph()
            result = graph.invoke(_snapshot_agent_input(pristine), context=trusted)
            validate_agent_node_state(result)
            return result  # type: ignore[return-value]
        except TrustedContextError:
            raise
        except Exception:  # noqa: BLE001 - resilience: never drop a turn
            logger.exception("LangGraph turn failed; using direct fallback")
    return _run_turn_direct_validated(pristine, trusted)


# Re-export for callers that route by intent without running the graph.
__all__ = ["run_turn", "run_turn_direct", "get_compiled_graph", "route_intent"]
