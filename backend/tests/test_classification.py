"""Tests for the CSIM detection heuristic (#1).

Pure domain function — no DB, no LLM. The contato→visitante transition is NOT
handled here (it is event-driven: leader cadastro / consolidation / check-in),
so this only covers CSIM detection and the "no signal → no change" contract.
"""

from __future__ import annotations

from app.domain.classification import Classification, classify_contact


# ---- CSIM (sem interesse ministerial) -------------------------------------
def test_csim_commercial_message() -> None:
    c = classify_contact("Olá, sou de uma empresa e quero vender um serviço")
    assert c.sem_interesse is True
    assert c.motivo == "comercial/empresa"


def test_csim_billing_keyword() -> None:
    c = classify_contact("Preciso enviar um boleto de cobrança")
    assert c.sem_interesse is True
    assert c.motivo == "comercial/empresa"


def test_csim_outra_cidade() -> None:
    c = classify_contact("Não sou daqui, moro em outra cidade")
    assert c.sem_interesse is True
    assert c.motivo == "fora da cidade"


# ---- sem sinal -> não muda nada -------------------------------------------
def test_neutral_message_is_no_op() -> None:
    c = classify_contact("oi, tudo bem?")
    assert c == Classification()
    assert c.sem_interesse is None


def test_attendance_claim_does_not_flag_or_promote() -> None:
    # Dizer que foi à igreja NÃO classifica nada (transição é por evento real).
    c = classify_contact("já fui no culto de vocês")
    assert c == Classification()
