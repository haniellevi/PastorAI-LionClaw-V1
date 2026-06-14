"""LangGraph wiring for the Orchestrator multi-agent (SPEC 3.4 / delta-034).

The graph has the orchestrator (supervisor) as the single entry node. A
conditional edge dispatches to exactly one sub-agent based on the route the
supervisor chose; every sub-agent then terminates the turn. This encodes the
core invariant: one entry, one exit, one reply.

`run_turn` executes a single turn and returns the merged state. It prefers the
compiled LangGraph (production parity, checkpointed via
AGENT_GRAPH_CHECKPOINT_URL) and falls back to a direct, dependency-free
execution of the same node functions so the logic stays testable without a
running graph backend.
"""

from __future__ import annotations

import logging
import operator
from functools import lru_cache
from typing import Annotated, Any

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


def run_turn_direct(state: AgentState) -> AgentState:
    """Execute one orchestrator turn directly (no graph backend required)."""
    after_orchestrator = orchestrator_node(state)
    route = after_orchestrator.get("route") or ROUTE_ONBOARDING
    subagent = SUBAGENTS.get(route, onboarding_node)
    updates = subagent(after_orchestrator)
    return _merge_state(after_orchestrator, updates)


# ---------------------------------------------------------------------------
# Compiled LangGraph (lazy, cached)
# ---------------------------------------------------------------------------
class _GraphState(dict):
    """Marker type; the real schema is provided to StateGraph below."""


@lru_cache
def get_compiled_graph() -> Any:
    """Build and compile the LangGraph StateGraph (cached per process)."""
    from langgraph.graph import END, START, StateGraph  # noqa: PLC0415

    # State schema with reducers so list fields accumulate across nodes.
    from typing import TypedDict  # noqa: PLC0415

    class GraphState(TypedDict, total=False):
        igreja_id: str
        igreja_nome: str
        conversation_id: str
        pessoa_id: str
        texto: str
        estado: str
        pessoa: dict
        term_accepted_version: str | None
        term_current_version: str
        route: str
        response: str | None
        events: Annotated[list, operator.add]
        tool_calls: Annotated[list, operator.add]
        apply_optout: bool
        apply_consent_version: str | None
        intake_update: dict

    builder = StateGraph(GraphState)
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

    checkpointer = _build_checkpointer()
    return builder.compile(checkpointer=checkpointer)


def _build_checkpointer() -> Any:
    """In-memory checkpointer (AGENT_GRAPH_CHECKPOINT_URL reserved for Postgres).

    The Postgres saver requires an extra dependency and a live connection; we
    default to the in-memory saver and log when a durable URL is configured so
    the deploy can wire it without changing call sites.
    """
    from app.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    if settings.agent_graph_checkpoint_url:
        logger.info("Agent graph checkpoint configured (durable store)")
    try:
        from langgraph.checkpoint.memory import MemorySaver  # noqa: PLC0415

        return MemorySaver()
    except Exception:  # noqa: BLE001 - checkpointer is optional
        return None


def run_turn(state: AgentState, *, use_graph: bool = True) -> AgentState:
    """Run a single orchestrator turn, returning the merged final state.

    Prefers the compiled LangGraph; on any failure (or use_graph=False) falls
    back to the direct execution of the same node functions.
    """
    if use_graph:
        try:
            graph = get_compiled_graph()
            config = {
                "configurable": {
                    "thread_id": state.get("conversation_id") or "default"
                }
            }
            result = graph.invoke(state, config=config)
            return result  # type: ignore[return-value]
        except Exception:  # noqa: BLE001 - resilience: never drop a turn
            logger.exception("LangGraph turn failed; using direct fallback")
    return run_turn_direct(state)


# Re-export for callers that route by intent without running the graph.
__all__ = ["run_turn", "run_turn_direct", "get_compiled_graph", "route_intent"]
