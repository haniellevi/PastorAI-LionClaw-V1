"""Tests for the CSIM detection heuristic (#1).

Pure domain function — no DB, no LLM. The contato→visitante transition is NOT
handled here (it is event-driven: leader cadastro / consolidation / check-in),
so this only covers CSIM detection and the "no signal → no change" contract.
"""

from __future__ import annotations

import pytest

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


# ---- B5: comercial exige oferta explícita, não assunto --------------------
@pytest.mark.parametrize(
    "texto",
    [
        "trabalho numa empresa e quero conhecer a célula",
        "minha empresa fechou, preciso de oração",
        "paguei o boleto do curso?",
        "sou representante comercial",
        "não quero vender nada, só conhecer a célula",
        "nunca quis vender produtos, quero servir",
        'meu chefe disse "quero vender um serviço" e fiquei triste',
        "trabalho com marketing e queria saber o horário do culto",
        "quero oferecer meu serviço como voluntário",
        "fui demitido da empresa, preciso de ajuda",
        "o orçamento lá de casa apertou, orem por mim",
        "a cobrança no trabalho está pesada",
        "quero vender",
        "venderia minha alma por um café, kkk",
        # Terceira pessoa / pergunta genérica: não é oferta DO contato.
        "meu filho quer vender produtos, preciso de oração por ele",
        "como vender produtos para ajudar a igreja?",
        "os vizinhos querem oferecer publicidade, peço oração",
        "meu filho gostaria de vender produtos",
        # Citação aberta sem fecho vale até o fim da mensagem.
        "meu chefe falou “quero vender serviços",
        'meu chefe falou "quero vender serviços',
    ],
)
def test_commercial_subject_without_offer_is_no_signal(texto: str) -> None:
    # Ambíguo -> None (não False): não limpa um CSIM já existente.
    assert classify_contact(texto) == Classification()


@pytest.mark.parametrize(
    "texto",
    [
        "quero oferecer publicidade",
        "quero apresentar uma proposta comercial",
        "Gostaria de oferecer nossos serviços de marketing para a igreja",
        "QUERO VENDER UM PRODUTO PARA VOCÊS",
        "Vendemos produtos de limpeza, posso apresentar uma parceria comercial?",
        "vou mandar a cobrança amanhã",
        "eu gostaria de oferecer publicidade",
        "preciso de oração, quero vender produtos",
    ],
)
def test_explicit_commercial_offer_flags_csim(texto: str) -> None:
    c = classify_contact(texto)
    assert c.sem_interesse is True
    assert c.motivo == "comercial/empresa"


def test_commercial_word_must_be_whole_word() -> None:
    # "vendedor"/"publicidades" de forma isolada não são o verbo/objeto da oferta,
    # e "cobrancas" dentro de outra palavra não conta.
    assert classify_contact("o vendedor da loja é da minha célula") == Classification()
    assert classify_contact("quero oferecer superpublicidade") == Classification()


def test_long_input_is_scanned_whole_without_truncation() -> None:
    # Entrada longa sem pontuação: a varredura é linear e não corta o texto,
    # então uma oferta no fim de uma mensagem enorme ainda conta. Aberturas “
    # sem fecho apagam o resto (citação até o fim), sem reescanear cada uma.
    filler = "quero vender " * 20_000
    assert classify_contact("nao " + filler + "produtos") == Classification()
    assert classify_contact(filler + "produtos").sem_interesse is True
    assert classify_contact("“" * 20_000 + "quero vender produtos") == Classification()


def test_outra_cidade_rule_unchanged() -> None:
    assert classify_contact("moro longe") == Classification(True, "fora da cidade")
    assert classify_contact("sou de outro estado") == Classification(
        True, "fora da cidade"
    )
