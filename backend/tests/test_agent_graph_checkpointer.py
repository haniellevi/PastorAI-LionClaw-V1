"""Regression tests for the LangGraph process-memory boundary."""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace

import pytest

from app.agent.context import LegacyTermContext, TrustedAgentContext
from app.agent.graph import get_compiled_graph
from app.agent.nodes import AgentState, ROUTE_ONBOARDING, ROUTE_OPTOUT
from app.domain.agent_authz import PrivilegeContext


@pytest.fixture(autouse=True)
def _clear_compiled_graph_cache() -> None:
    get_compiled_graph.cache_clear()
    yield
    get_compiled_graph.cache_clear()


def _state(texto: str) -> AgentState:
    return {
        "texto": texto,
        "pessoa": {"has_endereco": False},
    }


def _context(conversation_id: uuid.UUID) -> TrustedAgentContext:
    pessoa_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
    return TrustedAgentContext(
        igreja_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        conversation_id=conversation_id,
        pessoa_id=pessoa_id,
        conversation_state="ia",
        igreja_nome="Igreja Piloto",
        privilege=PrivilegeContext(pessoa_id=str(pessoa_id), tipo="visitante"),
        legacy_term=LegacyTermContext("v1", "v1"),
    )


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

    context_a = _context(uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))
    context_b = _context(uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"))
    first = graph.invoke(
        _state("quero sair da lista"),
        context=context_a,
    )
    second = graph.invoke(_state("oi"), context=context_b)

    assert first["route"] == ROUTE_OPTOUT
    assert second["route"] == ROUTE_ONBOARDING
    forbidden = {"conversation_id", "pessoa_id", "igreja_id", "privilege"}
    assert forbidden.isdisjoint(first)
    assert forbidden.isdisjoint(second)


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
