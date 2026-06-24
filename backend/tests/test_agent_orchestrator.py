"""Tests for the Orchestrator routing/graph invariants and log masking.

Covers delta-034 (one entry, one exit, one reply), delta-040 (consent gate) and
the sensitive-data masking applied before persisting agent payloads (F8/RNF-24).
These exercise the pure node/graph functions, so no DB or LLM is required.
"""

from __future__ import annotations

from app.agent.graph import run_turn_direct
from app.agent.masking import mask_payload, mask_text
from app.agent.nodes import (
    ROUTE_CONSENT,
    ROUTE_HANDOFF,
    ROUTE_ONBOARDING,
    ROUTE_OPTOUT,
    ROUTE_REPORT,
    AgentState,
    route_intent,
)


def _state(**overrides: object) -> AgentState:
    base: AgentState = {
        "igreja_id": "11111111-1111-1111-1111-111111111111",
        "igreja_nome": "Igreja Piloto",
        "conversation_id": "22222222-2222-2222-2222-222222222222",
        "pessoa_id": "33333333-3333-3333-3333-333333333333",
        "texto": "",
        "estado": "ia",
        "pessoa": {"tipo": "visitante", "has_endereco": False},
        "term_accepted_version": "v1",
        "term_current_version": "v1",
        "events": [],
        "tool_calls": [],
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


# ---- routing priority (route_intent) --------------------------------------
def test_handoff_has_highest_priority() -> None:
    # Even an opt-out phrase is ignored while a human owns the conversation.
    state = _state(estado="humano", texto="quero sair da lista")
    assert route_intent(state) == ROUTE_HANDOFF


def test_optout_routes_before_report_and_onboarding() -> None:
    state = _state(texto="parar de receber mensagens")
    assert route_intent(state) == ROUTE_OPTOUT


def test_acceptance_when_term_pending_routes_to_consent() -> None:
    state = _state(term_accepted_version=None, texto="Aceito")
    assert route_intent(state) == ROUTE_CONSENT


def test_report_routes_to_report_capture() -> None:
    # Relatório é ação ministerial (#10b Fase 2): só roteia p/ report se líder.
    state = _state(texto="Relatório: 10 presentes, 2 decisões", is_ministerial=True)
    assert route_intent(state) == ROUTE_REPORT


def test_report_from_non_ministerial_routes_to_onboarding() -> None:
    # Um contato comum mandando algo que "parece relatório" cai em onboarding —
    # sem confirmação falsa, sem decisão auto-registrada (anti-escalonamento).
    state = _state(texto="Relatório: 10 presentes, 2 decisões")  # is_ministerial ausente
    assert route_intent(state) == ROUTE_ONBOARDING


def test_missing_term_blocks_onboarding_with_consent_gate() -> None:
    # delta-040: collecting beyond name+telefone requires the current term.
    state = _state(term_accepted_version=None, texto="meu endereço é rua X")
    assert route_intent(state) == ROUTE_CONSENT


def test_default_route_is_onboarding_with_term_accepted() -> None:
    state = _state(texto="oi, tudo bem?")
    assert route_intent(state) == ROUTE_ONBOARDING


# ---- single-reply invariant via the graph (one entry, one exit) -----------
def test_run_turn_emits_single_reply_for_onboarding() -> None:
    final = run_turn_direct(_state(texto="oi"))
    assert final["route"] == ROUTE_ONBOARDING
    assert isinstance(final["response"], str) and final["response"]


def test_handoff_suppresses_automatic_reply() -> None:
    final = run_turn_direct(_state(estado="humano", texto="oi"))
    assert final["route"] == ROUTE_HANDOFF
    assert final["response"] is None


def test_optout_turn_flags_persistence_and_replies_once() -> None:
    final = run_turn_direct(_state(texto="quero cancelar"))
    assert final["route"] == ROUTE_OPTOUT
    assert final["apply_optout"] is True
    assert isinstance(final["response"], str)


def test_consent_acceptance_flags_version_to_persist() -> None:
    final = run_turn_direct(
        _state(term_accepted_version=None, term_current_version="v2", texto="Aceito")
    )
    assert final["route"] == ROUTE_CONSENT
    assert final["apply_consent_version"] == "v2"


def test_report_decision_emits_tool_call() -> None:
    final = run_turn_direct(
        _state(texto="Relatório: 5 presentes, 1 decisão", is_ministerial=True)
    )
    assert final["route"] == ROUTE_REPORT
    names = [c["ferramenta"] for c in final.get("tool_calls", [])]
    assert "registrar_decisao" in names


def test_report_decision_from_non_ministerial_emits_no_tool() -> None:
    # #10b Fase 2: contato comum não vira report nem emite registrar_decisao.
    final = run_turn_direct(_state(texto="Relatório: 5 presentes, 1 decisão"))
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
    final = run_turn_direct(
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
    final = run_turn_direct(
        _state(
            texto="já fui no culto de vocês",
            pessoa={"subetapa": "novo_contato", "has_endereco": False},
        )
    )
    assert final["route"] == ROUTE_ONBOARDING
    assert "subetapa" not in final["intake_update"]
    assert "sem_interesse" not in final["intake_update"]


def test_onboarding_preserves_intake_basics_when_flagging_csim() -> None:
    # O intake_node produz origem/primeiro_contato; o onboarding mescla o CSIM
    # SEM perder esses campos.
    final = run_turn_direct(
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
