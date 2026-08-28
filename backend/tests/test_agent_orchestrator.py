"""Tests for the Orchestrator routing/graph invariants and log masking.

Covers delta-034 (one entry, one exit, one reply), delta-040 (consent gate) and
the sensitive-data masking applied before persisting agent payloads (F8/RNF-24).
These exercise the pure node/graph functions, so no DB or LLM is required.
"""

from __future__ import annotations

import uuid

from langgraph.runtime import Runtime

from app.agent.context import LegacyTermContext, TrustedAgentContext
from app.agent.graph import run_turn_direct
from app.agent.masking import mask_payload, mask_text
from app.agent.nodes import (
    ROUTE_CONSENT,
    ROUTE_HANDOFF,
    ROUTE_ONBOARDING,
    ROUTE_OPTOUT,
    ROUTE_REPORT,
    AgentState,
    first_name_for_greeting,
    route_intent,
)
from app.domain.agent_authz import PrivilegeContext


_IGREJA_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_CONVERSATION_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
_PESSOA_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _state(**overrides: object) -> AgentState:
    base: AgentState = {
        "texto": "",
        "pessoa": {"has_endereco": False},
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


def _context(
    *,
    conversation_state: str = "ia",
    accepted_version: str | None = "v1",
    current_version: str = "v1",
    roles: frozenset[str] = frozenset(),
) -> TrustedAgentContext:
    privilege = PrivilegeContext(
        pessoa_id=str(_PESSOA_ID),
        tipo="visitante",
        roles=roles,
    )
    return TrustedAgentContext(
        igreja_id=_IGREJA_ID,
        conversation_id=_CONVERSATION_ID,
        pessoa_id=_PESSOA_ID,
        conversation_state=conversation_state,
        igreja_nome="Igreja Piloto",
        privilege=privilege,
        legacy_term=LegacyTermContext(accepted_version, current_version),
    )


def _route(state: AgentState, context: TrustedAgentContext | None = None) -> str:
    return route_intent(state, Runtime(context=context or _context()))


def _turn(
    state: AgentState, context: TrustedAgentContext | None = None
) -> AgentState:
    return run_turn_direct(state, context=context or _context())


# ---- routing priority (route_intent) --------------------------------------
def test_handoff_has_highest_priority() -> None:
    # Even an opt-out phrase is ignored while a human owns the conversation.
    state = _state(texto="quero sair da lista")
    assert _route(state, _context(conversation_state="humano")) == ROUTE_HANDOFF


def test_optout_routes_before_report_and_onboarding() -> None:
    state = _state(texto="parar de receber mensagens")
    assert _route(state) == ROUTE_OPTOUT


def test_acceptance_when_term_pending_routes_to_consent() -> None:
    state = _state(texto="Aceito")
    assert _route(state, _context(accepted_version=None)) == ROUTE_CONSENT


def test_report_routes_to_report_capture() -> None:
    # Relatório é ação ministerial (#10b Fase 2): só roteia p/ report se líder.
    state = _state(texto="Relatório: 10 presentes, 2 decisões")
    assert _route(state, _context(roles=frozenset({"pastor"}))) == ROUTE_REPORT


def test_report_from_non_ministerial_routes_to_onboarding() -> None:
    # Um contato comum mandando algo que "parece relatório" cai em onboarding —
    # sem confirmação falsa, sem decisão auto-registrada (anti-escalonamento).
    state = _state(texto="Relatório: 10 presentes, 2 decisões")  # is_ministerial ausente
    assert _route(state) == ROUTE_ONBOARDING


def test_missing_term_blocks_onboarding_with_consent_gate() -> None:
    # delta-040: collecting beyond name+telefone requires the current term.
    state = _state(texto="meu endereço é rua X")
    assert _route(state, _context(accepted_version=None)) == ROUTE_CONSENT


def test_default_route_is_onboarding_with_term_accepted() -> None:
    state = _state(texto="oi, tudo bem?")
    assert _route(state) == ROUTE_ONBOARDING


# ---- single-reply invariant via the graph (one entry, one exit) -----------
def test_run_turn_emits_single_reply_for_onboarding() -> None:
    final = _turn(_state(texto="oi"))
    assert final["route"] == ROUTE_ONBOARDING
    assert isinstance(final["response"], str) and final["response"]


def test_handoff_suppresses_automatic_reply() -> None:
    final = _turn(_state(texto="oi"), _context(conversation_state="humano"))
    assert final["route"] == ROUTE_HANDOFF
    assert final["response"] is None


def test_optout_turn_flags_persistence_and_replies_once() -> None:
    final = _turn(_state(texto="quero sair da lista"))
    assert final["route"] == ROUTE_OPTOUT
    assert final["apply_optout"] is True
    assert isinstance(final["response"], str)


def test_consent_acceptance_flags_version_to_persist() -> None:
    final = _turn(
        _state(texto="Aceito"),
        _context(accepted_version=None, current_version="v2"),
    )
    assert final["route"] == ROUTE_CONSENT
    assert final["apply_consent_version"] == "v2"


def test_aggregate_report_decision_emits_no_individual_tool_call() -> None:
    final = _turn(
        _state(texto="Relatório: 5 presentes, 1 decisão"),
        _context(roles=frozenset({"pastor"})),
    )
    assert final["route"] == ROUTE_REPORT
    names = [c["ferramenta"] for c in final.get("tool_calls", [])]
    assert "registrar_decisao" not in names
    assert "Relatório recebido" in final["response"]
    assert "confirmação humana" in final["response"]
    assert "Registrei" not in final["response"]


def test_report_decision_from_non_ministerial_emits_no_tool() -> None:
    # #10b Fase 2: contato comum não vira report nem emite registrar_decisao.
    final = _turn(_state(texto="Relatório: 5 presentes, 1 decisão"))
    assert final["route"] == ROUTE_ONBOARDING
    names = [c["ferramenta"] for c in final.get("tool_calls", [])]
    assert "registrar_decisao" not in names


# ---- masking (F8 / RNF-24 / delta-040) ------------------------------------
def test_mask_text_redacts_cpf_email_and_long_digits() -> None:
    masked = mask_text("CPF 123.456.789-00 email joao@ex.com fone 5511987654321")
    assert "123.456.789-00" not in masked
    assert "joao@ex.com" not in masked
    assert "5511987654321" not in masked


def test_mask_payload_is_recursive() -> None:
    payload = {
        "pessoa": {"email": "ana@ex.com", "telefone": "5511912345678"},
        "itens": ["cpf 111.222.333-44"],
        "ok": True,
    }
    masked = mask_payload(payload)
    assert "ana@ex.com" not in str(masked)
    assert "5511912345678" not in str(masked)
    assert "111.222.333-44" not in str(masked)
    # Non-sensitive scalars are preserved untouched.
    assert masked["ok"] is True


# ---- CSIM no onboarding (#1) ----------------------------------------------
def test_onboarding_flags_csim_and_closes_politely() -> None:
    final = _turn(
        _state(
            texto="sou de uma empresa e quero vender um serviço",
            pessoa={"subetapa": "novo_contato", "has_endereco": False},
        )
    )
    assert final["route"] == ROUTE_ONBOARDING
    assert final["intake_update"]["sem_interesse"] is True
    assert final["intake_update"]["sem_interesse_motivo"] == "comercial/empresa"
    ev = [e for e in final["events"] if e["evento"] == "onboarding"]
    assert ev and ev[0]["payload"]["classificacao"] == "csim"


def test_onboarding_does_not_promote_on_attendance_claim() -> None:
    # Dizer que foi à igreja NÃO promove a visitante (transição é por evento
    # real: cadastro do líder / consolidação / check-in).
    final = _turn(
        _state(
            texto="já fui no culto de vocês",
            pessoa={"subetapa": "novo_contato", "has_endereco": False},
        )
    )
    assert final["route"] == ROUTE_ONBOARDING
    assert "subetapa" not in final["intake_update"]
    assert "sem_interesse" not in final["intake_update"]


# ---- Saudação nominal no onboarding (M7B-W1) ------------------------------
def test_onboarding_greets_recognized_person_by_first_name() -> None:
    final = _turn(
        _state(
            texto="oi",
            pessoa={
                "nome": "Raniel Levi",
                "has_endereco": False,
            },
        )
    )
    assert final["route"] == ROUTE_ONBOARDING
    assert final["response"].startswith("Olá, Raniel! ")
    assert "Que bom falar com você!" in final["response"]


def test_onboarding_generic_when_name_is_the_phone_number() -> None:
    # Contato sem push_name nasce com nome = telefone_raw; não se saúda por ele.
    final = _turn(
        _state(
            texto="oi",
            pessoa={
                "nome": "5511999998888",
                "has_endereco": False,
            },
        )
    )
    assert not final["response"].startswith("Olá")
    assert final["response"] == "Que bom falar com você! Como posso te ajudar?"


def test_onboarding_generic_when_no_name() -> None:
    final = _turn(_state(texto="oi", pessoa={"has_endereco": False}))
    assert final["response"] == "Que bom falar com você! Como posso te ajudar?"


def test_first_name_for_greeting_edge_cases() -> None:
    assert first_name_for_greeting("Raniel Levi") == "Raniel"
    assert first_name_for_greeting("  Maria  ") == "Maria"
    assert first_name_for_greeting(None) is None
    assert first_name_for_greeting("") is None
    assert first_name_for_greeting("   ") is None
    assert first_name_for_greeting("5511999998888") is None
    assert first_name_for_greeting("+55 11 99999-8888") is None


def test_onboarding_preserves_intake_basics_when_flagging_csim() -> None:
    # O intake_node produz origem/primeiro_contato; o onboarding mescla o CSIM
    # SEM perder esses campos.
    final = _turn(
        _state(
            texto="represento uma empresa de marketing",
            pessoa={
                "subetapa": "novo_contato",
                "has_endereco": False,
                "origem": "",
                "primeiro_contato_set": False,
            },
        )
    )
    upd = final["intake_update"]
    assert upd["origem"] == "whatsapp"
    assert upd["set_primeiro_contato"] is True
    assert upd["sem_interesse"] is True


# ---- persistência do CSIM (_apply_intake) ---------------------------------
def test_apply_intake_flags_csim() -> None:
    from types import SimpleNamespace

    from app.agent.runtime import _apply_intake

    p = SimpleNamespace(
        origem="whatsapp",
        primeiro_contato="x",
        sem_interesse=False,
        sem_interesse_motivo=None,
    )
    _apply_intake(
        p, {"sem_interesse": True, "sem_interesse_motivo": "comercial/empresa"}
    )
    assert p.sem_interesse is True
    assert p.sem_interesse_motivo == "comercial/empresa"


def test_apply_intake_neutral_turn_keeps_csim() -> None:
    # Sem sinal de CSIM no update, um flag já setado não é limpo.
    from types import SimpleNamespace

    from app.agent.runtime import _apply_intake

    p = SimpleNamespace(
        origem="whatsapp",
        primeiro_contato="x",
        sem_interesse=True,
        sem_interesse_motivo="comercial/empresa",
    )
    _apply_intake(p, {"origem": "whatsapp"})
    assert p.sem_interesse is True
