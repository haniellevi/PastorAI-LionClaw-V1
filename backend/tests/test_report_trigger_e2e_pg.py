"""B15: gatilho do relatório no turno completo (pergunta não vira relatório).

Mesmo molde de ``test_report_capture_counts_e2e_pg``: inbound persistido,
worker, contexto confiável, privilégio lido do PostgreSQL e LangGraph reais.
Só o provedor e o LLM são falsos. Dados fictícios.
"""
from __future__ import annotations

import pytest

from app.db.models import AgentActionProposal, CelulaReuniao, Decision
from tests.test_report_capture_counts_e2e_pg import (  # noqa: F401 - fixtures
    _CONTACT_PHONE, _LEADER_PHONE, _count, _outbound, _report_events, _run, b15_turn,
    msg_engine_fx, rls_database_url,
)

pytestmark = pytest.mark.rls_integration

_QUESTIONS = (
    "Vamos ter 2 decisões de batismo no domingo? Preciso confirmar os nomes",
    "Quantos presentes 20 pessoas cabem no salão?",
    "Será que teremos 30 visitantes no sábado?",
    "Quanto foi a oferta de R$ 1.234,50?",
)


@pytest.mark.parametrize("texto", _QUESTIONS)
def test_leader_question_with_keyword_and_digit_is_not_captured_as_report(b15_turn, texto):
    evolution = _run(b15_turn, b15_turn.leader_conversation, _LEADER_PHONE, "B15-Q-LEADER", texto)

    assert _report_events(b15_turn, b15_turn.leader_conversation) == []
    assert len(evolution.calls) == 1
    assert "confirmação humana" not in evolution.calls[0][2]
    assert "Esta mensagem não finaliza o relatório" not in evolution.calls[0][2]
    assert _outbound(b15_turn, b15_turn.leader_conversation) == [evolution.calls[0][2]]
    assert _count(b15_turn, Decision) == 0
    assert _count(b15_turn, AgentActionProposal) == 0
    assert _count(b15_turn, CelulaReuniao) == 0


@pytest.mark.parametrize(("texto", "expected"), [
    ("12 presentes, 3 visitantes, 1 decisão. Tudo certo?", (12, 3, 1)),
    ("Tivemos 12 presentes. Serão 30 visitantes?", (12, None, None)),
])
def test_leader_report_with_separate_question_is_still_captured(b15_turn, texto, expected):
    evolution = _run(
        b15_turn, b15_turn.leader_conversation, _LEADER_PHONE, "B15-Q-REPORT",
        texto,
    )

    events = _report_events(b15_turn, b15_turn.leader_conversation)
    assert len(events) == 1
    resumo = events[0]["relatorio"]
    assert (resumo["presentes"], resumo["visitantes"], resumo["decisoes"]) == expected
    assert len(evolution.calls) == 1
    assert "confirmação humana" in evolution.calls[0][2]
    assert _outbound(b15_turn, b15_turn.leader_conversation) == [evolution.calls[0][2]]
    assert b15_turn.llm_calls == []
    assert _count(b15_turn, Decision) == 0
    assert _count(b15_turn, AgentActionProposal) == 0


def test_non_ministerial_contact_report_is_refused_and_question_is_ignored(b15_turn):
    for provider_id, texto in (
        ("B15-Q-CONTACT-REPORT", "12 presentes, 3 visitantes, 1 decisão. Tudo certo?"),
        ("B15-Q-CONTACT-QUESTION", _QUESTIONS[0]),
    ):
        evolution = _run(b15_turn, b15_turn.contact_conversation, _CONTACT_PHONE,
                         provider_id, texto)
        assert len(evolution.calls) == 1
        assert "Relatório recebido" not in evolution.calls[0][2]
        assert "confirmação humana" not in evolution.calls[0][2]

    assert _report_events(b15_turn, b15_turn.contact_conversation) == []
    assert _count(b15_turn, Decision) == 0
    assert _count(b15_turn, AgentActionProposal) == 0
