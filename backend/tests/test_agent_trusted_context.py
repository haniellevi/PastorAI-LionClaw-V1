"""Security boundary tests for D2B1 trusted agent context."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import FrozenInstanceError
from types import MappingProxyType, SimpleNamespace

import pytest
from langgraph.runtime import Runtime

from app.agent import graph as graph_module
from app.agent.context import (
    LegacyTermContext,
    TrustedAgentContext,
    TrustedContextError,
    require_trusted_context,
    validate_agent_input_state,
)
from app.agent.graph import get_compiled_graph, run_turn, run_turn_direct
from app.agent.nodes import (
    ROUTE_HANDOFF,
    ROUTE_ONBOARDING,
    AgentState,
    consent_node,
    empty_turn_effects,
    handoff_node,
    intake_node,
    onboarding_node,
    optout_node,
    orchestrator_node,
    report_capture_node,
    route_intent,
)
from app.agent.runtime import _build_trusted_context
from app.domain.agent_authz import PrivilegeContext


_IGREJA_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_CONVERSATION_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
_PESSOA_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


@pytest.fixture(autouse=True)
def _clear_graph_cache() -> None:
    get_compiled_graph.cache_clear()
    yield
    get_compiled_graph.cache_clear()


def _context(
    *,
    igreja_id: uuid.UUID = _IGREJA_ID,
    conversation_id: uuid.UUID = _CONVERSATION_ID,
    pessoa_id: uuid.UUID = _PESSOA_ID,
    conversation_state: str = "ia",
    igreja_nome: str | None = "Igreja Piloto",
    accepted_version: str | None = "v1",
    current_version: str = "v1",
    privilege: PrivilegeContext | None = None,
) -> TrustedAgentContext:
    resolved = privilege or PrivilegeContext(
        pessoa_id=str(pessoa_id), tipo="visitante"
    )
    return TrustedAgentContext(
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        pessoa_id=pessoa_id,
        conversation_state=conversation_state,
        igreja_nome=igreja_nome,
        privilege=resolved,
        legacy_term=LegacyTermContext(accepted_version, current_version),
    )


def _state(texto: str = "oi") -> AgentState:
    return {
        "texto": texto,
        "pessoa": {
            "nome": "Pessoa Sintética",
            "subetapa": "novo_contato",
            "origem": "whatsapp",
            "has_endereco": False,
            "primeiro_contato_set": True,
        },
    }


def test_context_and_legacy_term_are_frozen_slotted_values() -> None:
    context = _context()

    assert not hasattr(context, "__dict__")
    assert not hasattr(context.legacy_term, "__dict__")
    with pytest.raises(FrozenInstanceError):
        context.channel = "web"  # type: ignore[misc]


def test_context_keeps_exact_privilege_instance() -> None:
    privilege = PrivilegeContext(
        pessoa_id=str(_PESSOA_ID),
        tipo="membro",
        roles=frozenset({"pastor"}),
    )

    context = _context(privilege=privilege)

    assert context.privilege is privilege


class _StatefulString(str):
    """String-shaped object whose equality changes between validations."""

    def __new__(cls, value: str):
        instance = super().__new__(cls, value)
        instance.comparisons = 0
        return instance

    def __eq__(self, other: object) -> bool:
        self.comparisons += 1
        return self.comparisons < 3 and str.__eq__(self, other)

    __hash__ = str.__hash__


@pytest.mark.parametrize(
    "conversation_state",
    ["", "robot", None, [], {}, _StatefulString("humano")],
)
def test_context_rejects_invalid_conversation_state(
    conversation_state: object,
) -> None:
    with pytest.raises(TrustedContextError, match="conversation_state"):
        _context(conversation_state=conversation_state)  # type: ignore[arg-type]


def test_context_rejects_string_subclass_channel() -> None:
    with pytest.raises(TrustedContextError, match="channel"):
        TrustedAgentContext(
            igreja_id=_IGREJA_ID,
            conversation_id=_CONVERSATION_ID,
            pessoa_id=_PESSOA_ID,
            conversation_state="ia",
            igreja_nome="Igreja Piloto",
            privilege=PrivilegeContext(
                pessoa_id=str(_PESSOA_ID), tipo="visitante"
            ),
            legacy_term=LegacyTermContext("v1", "v1"),
            channel=_StatefulString("whatsapp"),  # type: ignore[arg-type]
        )


def test_context_accepts_missing_church_name_without_synthesizing_one() -> None:
    context = _context(igreja_nome=None)

    assert context.igreja_nome is None


def test_context_rejects_privilege_for_another_person_without_echoing_ids() -> None:
    other_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
    privilege = PrivilegeContext(pessoa_id=str(other_id), tipo="membro")

    with pytest.raises(TrustedContextError) as raised:
        _context(privilege=privilege)

    message = str(raised.value)
    assert str(_PESSOA_ID) not in message
    assert str(other_id) not in message


def test_context_rejects_string_subclass_privilege_person_id() -> None:
    privilege = PrivilegeContext(
        pessoa_id=_StatefulString(str(_PESSOA_ID)),  # type: ignore[arg-type]
        tipo="membro",
    )

    with pytest.raises(TrustedContextError, match="privilege.pessoa_id"):
        _context(privilege=privilege)


def test_repeated_validation_detects_tampered_frozen_context() -> None:
    context = _context()
    object.__setattr__(context, "conversation_state", "forged")

    with pytest.raises(TrustedContextError, match="conversation_state"):
        require_trusted_context(context)


@pytest.mark.parametrize(
    "reserved",
    [
        "tenant_id",
        "church_id",
        "actor_id",
        "actor_roles",
        "capabilities",
        "permissions",
        "is_admin",
        "is_pastor",
        "igreja_id",
        "conversation_id",
        "pessoa_id",
        "privilege",
        "term_current_version",
    ],
)
def test_input_rejects_authority_aliases(reserved: str) -> None:
    state = dict(_state())
    state[reserved] = "forged"

    with pytest.raises(TrustedContextError, match="reserved agent state key"):
        validate_agent_input_state(state)


@pytest.mark.parametrize(
    "output",
    [
        "tool_calls",
        "apply_optout",
        "apply_consent_version",
        "intake_update",
        "events",
        "route",
        "response",
    ],
)
def test_run_entry_rejects_preseeded_outputs_even_when_empty(output: str) -> None:
    values = {
        "tool_calls": [],
        "apply_optout": False,
        "apply_consent_version": None,
        "intake_update": {},
        "events": [],
        "route": "",
        "response": None,
    }
    state = dict(_state())
    state[output] = values[output]

    with pytest.raises(TrustedContextError, match="preseeded agent output key"):
        run_turn(state, context=_context())  # type: ignore[arg-type]


def test_compiled_graph_adapter_rejects_preseeded_outputs_before_reducers() -> None:
    state = dict(_state())
    state["events"] = []

    with pytest.raises(TrustedContextError, match="preseeded agent output key"):
        get_compiled_graph().invoke(state, context=_context())


def test_input_boundary_rejects_generic_mappings() -> None:
    with pytest.raises(TrustedContextError, match="plain dict"):
        validate_agent_input_state(MappingProxyType(dict(_state())))

    state = dict(_state())
    state["pessoa"] = MappingProxyType(dict(state["pessoa"]))
    with pytest.raises(TrustedContextError, match="plain dict"):
        validate_agent_input_state(state)


def test_input_errors_do_not_echo_unknown_keys_or_values() -> None:
    marker = "44444444-4444-4444-4444-444444444444"
    state = dict(_state())
    state[marker] = {"roles": ["forged"]}

    with pytest.raises(TrustedContextError) as raised:
        validate_agent_input_state(state)

    assert marker not in str(raised.value)
    assert "forged" not in str(raised.value)


@pytest.mark.parametrize("state", [{"texto": "oi"}, {"pessoa": {}}])
def test_input_requires_message_and_person_snapshot(state: dict) -> None:
    with pytest.raises(TrustedContextError, match="required agent inputs"):
        validate_agent_input_state(state)


@pytest.mark.parametrize(
    "field",
    ["id", "telefone", "tipo", "etapa", "sem_interesse", "unknown"],
)
def test_person_snapshot_allowlist_is_recursive(field: str) -> None:
    state = dict(_state())
    state["pessoa"] = {"nome": "Pessoa Sintética", field: "forged"}

    with pytest.raises(TrustedContextError, match="pessoa snapshot key"):
        validate_agent_input_state(state)


@pytest.mark.parametrize(
    "node",
    [
        route_intent,
        orchestrator_node,
        intake_node,
        consent_node,
        optout_node,
        handoff_node,
        report_capture_node,
        onboarding_node,
    ],
)
def test_every_route_and_node_rejects_missing_context(node) -> None:
    with pytest.raises(TrustedContextError):
        node(_state(), Runtime(context=None))


def test_compiled_graph_rejects_missing_or_wrong_context() -> None:
    graph = get_compiled_graph()

    with pytest.raises(TrustedContextError):
        graph.invoke(_state())
    with pytest.raises(TrustedContextError):
        graph.invoke(_state(), context={"igreja_id": str(_IGREJA_ID)})


@pytest.mark.parametrize(
    "invalid_context",
    [None, object(), {}, MappingProxyType({})],
)
@pytest.mark.parametrize("runner", [run_turn, run_turn_direct])
def test_all_turn_entries_reject_non_context_objects(
    runner,
    invalid_context: object,
) -> None:
    with pytest.raises(TrustedContextError):
        runner(_state(), context=invalid_context)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "invalid_context",
    [None, object(), {}, MappingProxyType({})],
)
def test_direct_node_rejects_non_context_objects(
    invalid_context: object,
) -> None:
    with pytest.raises(TrustedContextError):
        route_intent(_state(), Runtime(context=invalid_context))


def test_run_turn_validates_before_graph_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        graph_module,
        "get_compiled_graph",
        lambda: calls.append("graph") or None,
    )
    state = dict(_state())
    state["tool_calls"] = []

    with pytest.raises(TrustedContextError):
        run_turn(state, context=_context())  # type: ignore[arg-type]

    assert calls == []


def test_trusted_context_error_from_graph_never_uses_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingGraph:
        checkpointer = None
        store = None

        def invoke(self, *_args, **_kwargs):
            raise TrustedContextError("context rejected")

    calls: list[str] = []
    monkeypatch.setattr(graph_module, "get_compiled_graph", lambda: _FailingGraph())
    monkeypatch.setattr(
        graph_module,
        "_run_turn_direct_validated",
        lambda *_args: calls.append("fallback"),
    )

    with pytest.raises(TrustedContextError, match="context rejected"):
        run_turn(_state(), context=_context())

    assert calls == []


def test_general_graph_failure_reuses_one_runtime_and_context_in_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingGraph:
        checkpointer = None
        store = None

        def invoke(self, *_args, **_kwargs):
            raise RuntimeError("synthetic graph failure")

    runtimes: list[Runtime[TrustedAgentContext]] = []

    def fake_orchestrator(state, runtime):
        runtimes.append(runtime)
        return {"route": ROUTE_ONBOARDING}

    def fake_onboarding(state, runtime):
        runtimes.append(runtime)
        return {"route": ROUTE_ONBOARDING, "response": "ok"}

    monkeypatch.setattr(graph_module, "get_compiled_graph", lambda: _FailingGraph())
    monkeypatch.setattr(graph_module, "orchestrator_node", fake_orchestrator)
    monkeypatch.setitem(graph_module.SUBAGENTS, ROUTE_ONBOARDING, fake_onboarding)
    context = _context()

    final = run_turn(_state(), context=context)

    assert final["response"] == "ok"
    assert len(runtimes) == 2
    assert runtimes[0] is runtimes[1]
    assert runtimes[0].context is context


def test_graph_mutation_cannot_contaminate_fallback_or_caller_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MutatingFailingGraph:
        checkpointer = None
        store = None

        def invoke(self, state, *_args, **_kwargs):
            state["turn_effects"] = {
                "events": [{"evento": "forged"}],
                "tool_calls": [
                    {"ferramenta": "vincular_celula", "args": {}}
                ],
                "apply_optout": True,
                "apply_consent_version": "forged",
                "intake_update": {"origem": "forged"},
            }
            state["route"] = "report_capture"
            state["pessoa"]["nome"] = "Contexto contaminado"
            raise RuntimeError("synthetic graph failure after mutation")

    monkeypatch.setattr(
        graph_module,
        "get_compiled_graph",
        lambda: _MutatingFailingGraph(),
    )
    context = _context()
    caller_input = _state()
    caller_before = deepcopy(caller_input)
    expected = run_turn_direct(deepcopy(caller_input), context=context)

    final = run_turn(caller_input, context=context)

    assert final == expected
    assert caller_input == caller_before
    assert final["turn_effects"]["apply_consent_version"] is None
    assert final["turn_effects"]["apply_optout"] is False
    assert final["turn_effects"]["tool_calls"] == []
    assert set(final) == {"route", "response", "turn_effects"}


def test_compiled_graph_preserves_context_and_privilege_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts: list[TrustedAgentContext] = []

    def fake_orchestrator(state, runtime):
        contexts.append(runtime.context)
        return {
            "route": ROUTE_ONBOARDING,
            "turn_effects": empty_turn_effects(),
        }

    def fake_onboarding(state, runtime):
        contexts.append(runtime.context)
        return {"route": ROUTE_ONBOARDING, "response": "ok"}

    monkeypatch.setattr(graph_module, "orchestrator_node", fake_orchestrator)
    monkeypatch.setattr(graph_module, "onboarding_node", fake_onboarding)
    context = _context()

    final = run_turn(_state(), context=context)

    assert final["response"] == "ok"
    assert contexts == [context, context]
    assert all(item is context for item in contexts)
    assert all(item.privilege is context.privilege for item in contexts)


def test_cached_graph_does_not_retain_previous_tenant_context() -> None:
    graph = get_compiled_graph()
    tenant_b = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    conversation_b = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    pessoa_b = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    context_a = _context(
        conversation_state="humano",
        igreja_nome="Igreja A",
    )
    context_b = _context(
        igreja_id=tenant_b,
        conversation_id=conversation_b,
        pessoa_id=pessoa_b,
        conversation_state="ia",
        igreja_nome="Igreja B",
    )
    same_input = _state("oi")

    first = graph.invoke(deepcopy(same_input), context=context_a)
    second = graph.invoke(deepcopy(same_input), context=context_b)

    assert first["route"] == ROUTE_HANDOFF
    assert second["route"] == ROUTE_ONBOARDING
    serialized_second = repr(second)
    assert str(_IGREJA_ID) not in serialized_second
    assert str(_CONVERSATION_ID) not in serialized_second
    assert str(_PESSOA_ID) not in serialized_second
    assert "Igreja A" not in serialized_second


@pytest.mark.parametrize(
    ("state", "context"),
    [
        (_state("oi"), _context()),
        (_state("quero sair da lista"), _context()),
        (_state("Aceito"), _context(accepted_version=None, current_version="v2")),
        (_state("oi"), _context(conversation_state="humano")),
        (
            _state("Relatório: 8 presentes, 1 decisão"),
            _context(
                privilege=PrivilegeContext(
                    pessoa_id=str(_PESSOA_ID),
                    tipo="membro",
                    roles=frozenset({"pastor"}),
                )
            ),
        ),
    ],
)
def test_compiled_and_direct_paths_have_parity_without_duplicate_events(
    state: AgentState, context: TrustedAgentContext
) -> None:
    compiled = run_turn(dict(state), context=context)  # type: ignore[arg-type]
    direct = run_turn_direct(dict(state), context=context)  # type: ignore[arg-type]

    assert compiled == direct
    effects = compiled["turn_effects"]
    event_names = [event["evento"] for event in effects["events"]]
    assert event_names.count("intake") == 1
    assert len(event_names) == 2
    assert all(
        "pessoaId" not in event.get("payload", {})
        and "conversationId" not in event.get("payload", {})
        for event in effects["events"]
    )
    forbidden = {
        "igreja_id",
        "igreja_nome",
        "conversation_id",
        "pessoa_id",
        "privilege",
        "legacy_term",
    }
    assert forbidden.isdisjoint(compiled)
    assert set(compiled) == {"route", "response", "turn_effects"}


def _walk_result(value: object):
    yield value
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk_result(key)
            yield from _walk_result(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _walk_result(item)


def test_result_recursively_excludes_authority_objects_and_context_ids() -> None:
    context = _context(
        privilege=PrivilegeContext(
            pessoa_id=str(_PESSOA_ID),
            tipo="membro",
            roles=frozenset({"pastor"}),
        )
    )

    final = run_turn(
        _state("Relatório: 8 presentes, 1 decisão"),
        context=context,
    )

    values = list(_walk_result(final))
    assert not any(
        isinstance(value, (TrustedAgentContext, PrivilegeContext, uuid.UUID))
        for value in values
    )
    strings = {value for value in values if type(value) is str}
    assert str(context.igreja_id) not in strings
    assert str(context.conversation_id) not in strings
    assert str(context.pessoa_id) not in strings
    assert context.privilege.roles.isdisjoint(strings)


def test_runtime_context_factory_preserves_resolved_privilege_instance() -> None:
    privilege = PrivilegeContext(
        pessoa_id=str(_PESSOA_ID),
        tipo="membro",
        roles=frozenset({"pastor"}),
    )
    igreja = SimpleNamespace(id=_IGREJA_ID, nome="Igreja Piloto")
    conversation = SimpleNamespace(
        id=_CONVERSATION_ID,
        estado="ia",
    )
    pessoa = SimpleNamespace(id=_PESSOA_ID)

    context = _build_trusted_context(
        igreja_id=_IGREJA_ID,
        igreja=igreja,
        conversation=conversation,
        pessoa=pessoa,
        privilege=privilege,
        accepted_version="v1",
        current_version="v1",
    )

    assert context.privilege is privilege


def test_tool_boundary_receives_exact_context_privilege_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent import runtime as runtime_module

    captured: list[tuple[uuid.UUID, PrivilegeContext]] = []

    def fake_execute(_session, igreja_id, privilege, tool_calls):
        captured.append((igreja_id, privilege))
        assert tool_calls == []
        return [], []

    monkeypatch.setattr(runtime_module, "_execute_tools", fake_execute)
    context = _context()

    runtime_module._execute_tools_for_context(object(), context, [])

    assert captured == [(_IGREJA_ID, context.privilege)]
    assert captured[0][1] is context.privilege


def test_runtime_context_factory_does_not_default_missing_conversation_state() -> None:
    privilege = PrivilegeContext(pessoa_id=str(_PESSOA_ID), tipo="visitante")

    with pytest.raises(TrustedContextError, match="conversation_state"):
        _build_trusted_context(
            igreja_id=_IGREJA_ID,
            igreja=SimpleNamespace(id=_IGREJA_ID, nome="Igreja Piloto"),
            conversation=SimpleNamespace(id=_CONVERSATION_ID, estado=None),
            pessoa=SimpleNamespace(id=_PESSOA_ID),
            privilege=privilege,
            accepted_version="v1",
            current_version="v1",
        )
