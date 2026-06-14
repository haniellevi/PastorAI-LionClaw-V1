"""Tests for consent/opt-out rules (delta-040/US-32) and report parsing (US-24)."""

from __future__ import annotations

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


# ---- opt-out (US-32 / RNF-06) ---------------------------------------------
def test_optout_request_detection() -> None:
    assert consent.is_optout_request("quero SAIR da lista")
    assert consent.is_optout_request("parar de receber mensagens")
    assert consent.is_optout_request("não quero mais receber")
    assert consent.is_optout_request("descadastrar por favor")
    assert not consent.is_optout_request("quero saber mais sobre a célula")


# ---- report parsing (US-24 / delta-041) -----------------------------------
def test_looks_like_report() -> None:
    assert looks_like_report("relatório: 10 presentes, 2 visitantes")
    assert not looks_like_report("bom dia, tudo bem?")
    assert not looks_like_report(None)


def test_parse_cell_report_extracts_counts() -> None:
    report = parse_cell_report(
        "Relatório de hoje: 12 presentes, 3 visitantes, 2 decisões, oferta R$ 50,00"
    )
    assert report.presentes == 12
    assert report.visitantes == 3
    assert report.decisoes == 2
    assert report.oferta == 50.0
    assert report.has_decisions is True


def test_parse_cell_report_without_decisions() -> None:
    report = parse_cell_report("tivemos 8 presentes e 1 visitante")
    assert report.presentes == 8
    assert report.visitantes == 1
    assert report.has_decisions is False
    assert report.is_empty is False
