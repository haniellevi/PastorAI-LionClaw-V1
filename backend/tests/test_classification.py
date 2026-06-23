"""Tests for the contact classification heuristic (#1 / US-10).

Pure domain function — no DB, no LLM. Covers contato→visitante promotion,
CSIM detection (with motivo) and the "no signal → no change" contract.
"""

from __future__ import annotations

from app.domain.classification import Classification, classify_contact


def _contato(**over: object) -> dict:
    base = {
        "subetapa": "novo_contato",
        "tem_celula": False,
        "presencas_celula": 0,
        "aceitou_jesus": False,
    }
    base.update(over)
    return base


# ---- CSIM (sem interesse ministerial) -------------------------------------
def test_csim_commercial_message() -> None:
    c = classify_contact(_contato(), "Olá, sou de uma empresa e quero vender um serviço")
    assert c.sem_interesse is True
    assert c.motivo == "comercial/empresa"
    assert c.subetapa is None  # CSIM não promove


def test_csim_billing_keyword() -> None:
    c = classify_contact(_contato(), "Preciso enviar um boleto de cobrança")
    assert c.sem_interesse is True
    assert c.motivo == "comercial/empresa"


def test_csim_outra_cidade() -> None:
    c = classify_contact(_contato(), "Não sou daqui, moro em outra cidade")
    assert c.sem_interesse is True
    assert c.motivo == "fora da cidade"


def test_csim_has_priority_over_attendance() -> None:
    # Mesmo citando que já foi ao culto, sinal comercial manda → CSIM.
    c = classify_contact(_contato(), "Já fui ao culto, mas represento uma empresa de marketing")
    assert c.sem_interesse is True


# ---- promoção contato -> visitante ----------------------------------------
def test_attendance_text_promotes_to_visitante() -> None:
    c = classify_contact(_contato(), "Oi! Eu já frequento a célula de vocês")
    assert c.subetapa == "visitante"
    assert c.sem_interesse is None


def test_stored_cell_link_promotes_to_visitante() -> None:
    c = classify_contact(_contato(tem_celula=True), "boa noite")
    assert c.subetapa == "visitante"


def test_decision_signal_promotes_to_visitante() -> None:
    c = classify_contact(_contato(aceitou_jesus=True), "amém")
    assert c.subetapa == "visitante"


def test_already_visitante_is_not_repromoted() -> None:
    # Quem já não está em novo_contato não é re-promovido (evita escrita à toa).
    c = classify_contact(_contato(subetapa="visitante"), "já fui no culto")
    assert c == Classification()


def test_neutral_message_is_no_op() -> None:
    c = classify_contact(_contato(), "oi, tudo bem?")
    assert c == Classification()
    assert c.subetapa is None and c.sem_interesse is None
