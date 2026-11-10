"""Tests for consent/opt-out rules (delta-040/US-32) and report parsing (US-24)."""

from __future__ import annotations

import pytest

from app.domain import consent
from app.domain.report import looks_like_report, parse_cell_report


# ---- consent term (delta-040) ---------------------------------------------
def test_baseline_fields_need_no_term() -> None:
    assert consent.requires_term(["nome", "telefone"]) is False
    assert consent.requires_term(["nome", "endereco"]) is True


def test_needs_reaccept_when_no_term_or_outdated() -> None:
    assert consent.needs_reaccept(None, "v1") is True
    assert consent.needs_reaccept("v1", "v1") is False
    # delta-040: bumping the version forces a re-accept.
    assert consent.needs_reaccept("v1", "v2") is True


def test_can_collect_beyond_baseline_requires_current_term() -> None:
    assert consent.can_collect_beyond_baseline(accepted_version="v1", current_version="v1")
    assert not consent.can_collect_beyond_baseline(accepted_version=None, current_version="v1")


def test_is_acceptance_detects_affirmatives() -> None:
    assert consent.is_acceptance("Aceito")
    assert consent.is_acceptance("sim, concordo")
    assert not consent.is_acceptance("não quero")
    assert not consent.is_acceptance("")


@pytest.mark.parametrize(
    "reply",
    [
        "sim, mas não quero",
        "SIM! Mas não quero aceitar.",
        "aceito, porém não agora",
        "sim, não quero receber mensagens",
        "sim, mas preciso pensar",
        "sim, quero sair da lista",
    ],
)
def test_is_acceptance_rejects_qualified_or_conflicting_replies(reply: str) -> None:
    assert not consent.is_acceptance(reply)


@pytest.mark.parametrize(
    "reply",
    ["sim", "Aceito!", "SIM, CONCORDO.", "De acordo.", "Pode sim!"],
)
def test_is_acceptance_keeps_clear_affirmatives(reply: str) -> None:
    assert consent.is_acceptance(reply)


@pytest.mark.parametrize(
    "reply",
    ["eu aceito", "sim aceito", "ok, aceito", "CLARO QUE SIM!"],
)
def test_is_acceptance_allows_short_unambiguous_replies(reply: str) -> None:
    assert consent.is_acceptance(reply)


@pytest.mark.parametrize(
    "reply",
    [
        "eu aceito, mas não agora",
        "sim aceito, porém tenho dúvidas",
        "ok, aceito, MAS não quero",
        "claro que sim, NÃO",
    ],
)
def test_is_acceptance_rejects_qualified_replies_even_with_known_phrase(reply: str) -> None:
    assert not consent.is_acceptance(reply)


# ---- opt-out (US-32 / RNF-06) ---------------------------------------------
def test_optout_request_detection() -> None:
    assert consent.is_optout_request("quero SAIR da lista")
    assert consent.is_optout_request("parar de receber mensagens")
    assert consent.is_optout_request("não quero mais receber")
    assert consent.is_optout_request("não quero receber mais mensagens")
    assert consent.is_optout_request("não desejo mais receber mensagens")
    assert consent.is_optout_request("remova meu número da lista de transmissão")
    assert consent.is_optout_request("descadastrar por favor")
    assert consent.is_optout_request("opt-out")
    assert consent.is_optout_request("não me envie mais nada")
    assert not consent.is_optout_request("quero saber mais sobre a célula")


def test_generic_verbs_without_communication_context_are_not_optout() -> None:
    assert not consent.is_optout_request("preciso cancelar a reunião")
    assert not consent.is_optout_request("pode remover esse membro?")
    assert not consent.is_optout_request("quero sair da célula")
    assert not consent.is_optout_request("vamos parar no endereço combinado")
    assert not consent.is_optout_request("não quero receber visitas")
    assert not consent.is_optout_request("não me envie o endereço")
    assert not consent.is_optout_request("não desejo receber uma ligação")


def test_terminal_sair_token_is_an_explicit_optout_without_broadening_phrases() -> None:
    assert consent.is_optout_request(" SAÍR! ")
    assert consent.is_optout_request("sair...")
    assert not consent.is_optout_request("quero sair da célula")
    assert not consent.is_optout_request("sair das mensagens")


# ---- report parsing (US-24 / delta-041) -----------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("relatório: 10 presentes, 2 visitantes", True),
        ("presentes: 0", True),
        ("presentes: 12", True),
        ("relatório: R$ 50,00", True),
        ("Lembrete do relatório de 10/11", False),
        ("Quanto foi a oferta do dia 03/11?", False),
        ("Na reunião de 20/11 teremos visitantes", False),
        ("R$ 50,00", False),
        ("bom dia, tudo bem?", False),
        (None, False),
    ],
)
def test_looks_like_report(text: str | None, expected: bool) -> None:
    assert looks_like_report(text) is expected


def test_parse_cell_report_extracts_counts() -> None:
    report = parse_cell_report(
        "Relatório de hoje: 12 presentes, 3 visitantes, 2 decisões, oferta R$ 50,00"
    )
    assert report.presentes == 12
    assert report.visitantes == 3
    assert report.decisoes == 2
    assert report.oferta == 50.0
    assert report.has_decisions is True


@pytest.mark.parametrize("text", [
    "Lista de presentes 10/11",
    "dia 10/11 presentes",
    "presentes: 10/11/2026",
    "visitantes = 10 / 11 / 2026",
    "2026-11-10 decisões",
    "decisões: 10-11-2026",
    "oferta: 10/11/2026",
    "oferta: 2026-11-10",
    "presentes: 10.11.2026",
    "presentes10/11",
    "10/11presentes",
    "relatório: R$ 10/11/2026",
    "presentes: 10/11 12",
    "10 10/11 presentes",
])
def test_report_dates_are_not_counts_or_offerings(text: str) -> None:
    assert parse_cell_report(text).is_empty
    assert not looks_like_report(text)


@pytest.mark.parametrize(("text", "expected"), [
    ("Relatório de 10/11: presentes: 0 visitantes: 3 decisões: 0 oferta: 12,50",
     (0, 3, 0, 12.5)),
    ("presentes 10/11; presentes: 12", (12, None, None, None)),
    ("presentes 10/11 3 visitantes", (None, 3, None, None)),
    ("oferta 10/11; oferta: R$ 1.234,56", (None, None, None, 1234.56)),
    ("Relatório de 2026-11-10: 12 presentes - 3 visitantes", (12, 3, None, None)),
    ("presentes: 12\nData: 10/11\nvisitantes: 0", (12, 0, None, None)),
    ("Relatório 10/11 - 12 presentes - 3 visitantes", (12, 3, None, None)),
    ("Dia 10/11 - 12 presentes", (12, None, None, None)),
    ("presentes: 12 - 10/11", (12, None, None, None)),
    ("oferta: R$ 50 - 10/11", (None, None, None, 50.0)),
    ("Dia 10-11 - 12 presentes", (12, None, None, None)),
    ("oferta: R$ 1.234.567,89", (None, None, None, 1234567.89)),
])
def test_report_keeps_valid_values_around_dates(text: str, expected: tuple) -> None:
    report = parse_cell_report(text)
    assert (report.presentes, report.visitantes, report.decisoes, report.oferta) == expected
    assert looks_like_report(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # B15: an explicitly labelled value belongs to its own label; a number
        # from a previous line/field must not be borrowed.
        ("presentes: 12\nvisitantes: 3\ndecisões: 1", (12, 3, 1)),
        ("presentes: 12 visitantes: 3 decisões: 1", (12, 3, 1)),
        ("Presentes = 12\r\nVisitantes = 3\r\nDecisões = 0", (12, 3, 0)),
        ("presentes:\t12\tvisitantes:\t3", (12, 3, None)),
        ("PRESENTES: 12, DECISOES: 1", (12, None, 1)),
        ("presentes - 12\nvisitantes - 3", (12, 3, None)),
        # Number-before-label stays supported, on lines or in one phrase.
        ("12 presentes\n3 visitantes\n1 decisão", (12, 3, 1)),
        ("12 presentes - 3 visitantes - 1 decisão", (12, 3, 1)),
        ("tivemos 12 presentes, 3 visitantes e nenhuma decisão", (12, 3, None)),
    ],
)
def test_parse_cell_report_binds_each_count_to_its_own_label(
    text: str, expected: tuple[int | None, int | None, int | None]
) -> None:
    report = parse_cell_report(text)
    assert (report.presentes, report.visitantes, report.decisoes) == expected


@pytest.mark.parametrize(("text", "expected"), [
    ("visitantes 3 presentes 12 decisões 1", (12, 3, 1, None)),
    ("12 presentes 3 visitantes 1 decisão", (12, 3, 1, None)),
    ("presentes12 visitantes3 decisões1", (12, 3, 1, None)),
    ("presentes120", (120, None, None, None)),
    ("presentes0 visitantes0 decisões0", (0, 0, 0, None)),
    ("12presentes 3visitantes 1decisão", (12, 3, 1, None)),
    ("presentes12-3visitantes", (12, 3, None, None)),
    ("presentes - 12 visitantes - 3", (12, 3, None, None)),
    ("12 presentes: 3 visitantes: 1", (3, 1, None, None)),
    ("12 presentes: 10/11", (None, None, None, None)),
    ("decisões 2 presentes: 10/11", (None, None, 2, None)),
    ("presentes 12 visitantes", (12, None, None, None)),
    ("visitantes: 3 presentes", (None, 3, None, None)),
    ("presentes 12 presentes: 7 visitantes3", (7, 3, None, None)),
    ("presentes: 7 presentes 12 visitantes", (7, None, None, None)),
    ("oferta 50 presentes12", (12, None, None, 50.0)),
    ("oferta50 presentes", (None, None, None, 50.0)),
    ("oferta12,50 presentes", (None, None, None, 12.5)),
    ("R$12,50 presentes3", (3, None, None, 12.5)),
    ("12 presentes R$3,50 visitantes", (12, None, None, 3.5)),
    ("R$60 oferta50 presentes12", (12, None, None, 50.0)),
    ("oferta: R$ 1.234,56 presentes: 12", (12, None, None, 1234.56)),
    ("oferta 50 oferta 70 visitantes", (None, None, None, 50.0)),
    ("oferta: 0,00 presentes0", (0, None, None, 0.0)),
    ("presentes:12,visitantes:3", (12, 3, None, None)),
    ("12 presentes,3 visitantes", (12, 3, None, None)),
    ("presentes:12.visitantes:3", (12, 3, None, None)),
    ("Presentes:\n3 visitantes", (None, 3, None, None)),
    ("Presentes:\n12\nVisitantes:\n0", (12, 0, None, None)),
    ("2 deciso\u0303es", (None, None, 2, None)),
    ("decisa\u0303o: 1", (None, None, 1, None)),
    ("12 presentes 3 visitantes sem oferta 1 decisão", (12, 3, 1, None)),
    ("nenhuma oferta 1 decisão", (None, None, 1, None)),
    ("oferta 12 presentes", (None, None, None, None)),
    ("oferta - 12 presentes", (None, None, None, None)),
    ("oferta- 12 presentes", (None, None, None, None)),
    ("oferta: 12 presentes", (None, None, None, 12.0)),
    ("oferta R$ 12 presentes", (None, None, None, 12.0)),
    ("Culto 20:00 presentes 12", (12, None, None, None)),
    ("às 19:30 presentes 12", (12, None, None, None)),
    ("oferta 12 presentes 3 visitantes 1 decisão", (None, None, None, None)),
    ("oferta 12 presentes 3 visitantes", (None, None, None, None)),
    ("oferta 50 presentes 12 visitantes 3 decisões 1", (None, None, None, None)),
    ("oferta 50 presentes 12 visitantes 3", (None, None, None, None)),
    ("oferta 50 visitantes 3 presentes 12", (None, None, None, None)),
    ("oferta 50 presentes 12", (None, None, None, None)),
    ("presentes: 12 oferta 50 visitantes 3 decisões 1", (12, None, None, None)),
    ("oferta 12 presentes 3 visitantes decisões: 1", (None, None, 1, None)),
    ("oferta 12 presentes visitantes: 3 decisões: 1", (None, 3, 1, None)),
    ("oferta 12 presentes, 3 visitantes", (None, 3, None, None)),
    ("oferta 12 presentes; visitantes 3", (None, 3, None, None)),
    ("oferta 12 presentes - 3 visitantes", (None, 3, None, None)),
    ("oferta 12 presentes 3,50 visitantes", (None, None, None, None)),
    ("oferta 12 presentes R$ 5", (None, None, None, 5.0)),
    ("oferta 50 presentes 12\nvisitantes: 3 decisões: 1", (None, 3, 1, None)),
    ("Oferta em R$\n12 presentes", (12, None, None, None)),
    ("Relatório com oferta\n12 presentes\n3 visitantes", (12, 3, None, None)),
    ("Oferta:\n50\npresentes: 12", (12, None, None, 50.0)),
    ("Oferta:\nR$ 12,50\npresentes: 0", (0, None, None, 12.5)),
])
def test_report_values_belong_to_one_field(text: str, expected: tuple) -> None:
    report = parse_cell_report(text)
    assert (report.presentes, report.visitantes, report.decisoes, report.oferta) == expected


@pytest.mark.parametrize("text", [
    "oferta12,5 presentes",
    "R$12,500 presentes",
    "oferta R$ 12:30 presentes",
    "R$12.5 presentes",
])
def test_malformed_offering_is_not_truncated_or_counted_as_attendance(text: str) -> None:
    assert parse_cell_report(text).is_empty


@pytest.mark.parametrize("text", [
    "oferta: -12 presentes",
    "R$ -12 presentes",
    "oferta: +12 presentes",
    "R$ +12 presentes",
    "presentes:12visitantes",
    "presentes: 12visitantes",
    "presentes20:00",
    "presentes: -12 visitantes",
    "decisões=+2 presentes",
    "R$ \u221212 presentes",
    "presentes: \u221212 visitantes",
    "oferta -12 presentes",
    "presentes -12",
    "-12 presentes",
    "12-3 visitantes",
])
def test_rejected_field_value_is_not_reassigned(text: str) -> None:
    assert parse_cell_report(text).is_empty
    assert not looks_like_report(text)


def test_parse_cell_report_without_decisions() -> None:
    report = parse_cell_report("tivemos 8 presentes e 1 visitante")
    assert report.presentes == 8
    assert report.visitantes == 1
    assert report.has_decisions is False
    assert report.is_empty is False
