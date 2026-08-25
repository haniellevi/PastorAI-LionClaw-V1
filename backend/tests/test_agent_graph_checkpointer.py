"""Regression tests for the LangGraph process-memory boundary."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.agent.graph import get_compiled_graph
from app.agent.nodes import AgentState, ROUTE_ONBOARDING, ROUTE_OPTOUT


@pytest.fixture(autouse=True)
def _clear_compiled_graph_cache() -> None:
    get_compiled_graph.cache_clear()
    yield
    get_compiled_graph.cache_clear()


def _state(conversation_id: str, texto: str) -> AgentState:
    return {
        "igreja_id": "11111111-1111-1111-1111-111111111111",
        "igreja_nome": "Igreja Piloto",
        "conversation_id": conversation_id,
        "pessoa_id": "33333333-3333-3333-3333-333333333333",
        "texto": texto,
        "estado": "ia",
        "pessoa": {"tipo": "visitante", "has_endereco": False},
        "term_accepted_version": "v1",
        "term_current_version": "v1",
        "events": [],
        "tool_calls": [],
    }


def test_compiled_graph_does_not_instantiate_or_retain_memory_saver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import langgraph.checkpoint.memory as checkpoint_memory

    class ForbiddenMemorySaver:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("MemorySaver must not be instantiated")

    monkeypatch.setattr(checkpoint_memory, "MemorySaver", ForbiddenMemorySaver)

    graph = get_compiled_graph()

    assert graph.checkpointer is None


def test_stateless_graph_executes_independent_conversations_without_thread_config() -> None:
    graph = get_compiled_graph()

    first = graph.invoke(_state("conversation-a", "quero sair da lista"))
    second = graph.invoke(_state("conversation-b", "oi"))

    assert first["conversation_id"] == "conversation-a"
    assert first["route"] == ROUTE_OPTOUT
    assert second["conversation_id"] == "conversation-b"
    assert second["route"] == ROUTE_ONBOARDING


def test_configured_checkpoint_url_warns_instead_of_claiming_durability(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(agent_graph_checkpoint_url="postgresql://configured"),
    )
    caplog.set_level(logging.WARNING, logger="pastorai.agent.graph")

    graph = get_compiled_graph()

    assert graph.checkpointer is None
    assert "running without checkpoint persistence" in caplog.text
