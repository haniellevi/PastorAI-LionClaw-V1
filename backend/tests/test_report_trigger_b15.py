"""B15: o gatilho do relatório não dispara em pergunta com palavra + número.

Frases fictícias. O critério vem do corpus ``jev_corpus_v1.jsonl`` (rel-neg-008)
e do teste já existente de ``looks_like_report`` ("Quanto foi a oferta do dia
03/11?"): uma pergunta não é relatório.
"""
from __future__ import annotations

import pytest

from app.agent.nodes import message_is_cell_report


@pytest.mark.parametrize("texto", [
    "Vamos ter 2 decisões de batismo no domingo? Preciso confirmar os nomes",
    "Quantos presentes 20 pessoas cabem no salão?",
    "Será que teremos 30 visitantes no sábado?",
    "o relatório tem que ter 12 presentes?",
    "Posso contar 3 visitantes no relatório?",
    "Quanto foi a oferta de R$ 1.234,50?",
    "O salão comporta 20 visitantes, p.ex.?",
    "O salão comporta 20 visitantes, p. ex.?",
    "Serão 20 visitantes! ?",
])
def test_question_with_keyword_and_digit_is_not_a_report(texto):
    assert not message_is_cell_report(texto)


@pytest.mark.parametrize("texto", [
    "Relatório da célula de hoje: 12 presentes, 3 visitantes, 1 decisão, oferta de 85 reais",
    "presentes: 12\nvisitantes: 3\ndecisões: 1",
    "celula hoje 7 presentes 1 visitante oferta 30",
    "Tivemos 12 presentes e 3 visitantes. Tudo certo?",
    "Tudo bem? Hoje foram 12 presentes e 3 visitantes",
    "12 presentes.Tudo certo?",
    "Relatório 10/11 - 12 presentes - 3 visitantes - 1 decisão",
])
def test_report_still_triggers_even_with_a_separate_question(texto):
    assert message_is_cell_report(texto)


@pytest.mark.parametrize("texto", [None, "", "bom dia?", "Lembrete do relatório de 10/11"])
def test_non_report_inputs(texto):
    assert not message_is_cell_report(texto)
