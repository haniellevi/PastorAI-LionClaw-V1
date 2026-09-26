"""Explicit crisis and human handoff phrases, without provider or model calls."""

from __future__ import annotations

import pytest

from app.agent.nodes import is_handoff_request


@pytest.mark.parametrize(
    "texto",
    (
        "penso em me matar",
        "tenho pensamentos suicidas",
        "PENSANDO EM SUICÍDIO",
        "nao aguento mais viver",
        "cansei de viver",
        "queria morrer",
        "prefiro morrer",
        "quero acabar com a minha vida",
        "vou me machucar",
        "quero me cortar",
        "to pensando em me matar",
        "suicidar-me",
        "quero me automutilar",
        "penso em automutilacao",
        "vou dar um fim na minha vida",
        "não quero mais viver",
    ),
)
def test_explicit_crisis_phrases_trigger_handoff(texto: str) -> None:
    assert is_handoff_request(texto)


@pytest.mark.parametrize(
    "texto",
    (
        "suicidio",
        "pensamentos suicidas",
        "automutilacao",
        "me matar",
        "matar-me",
        "me machucar",
        "me cortar",
        "acabar com minha vida",
        "acabar com a minha vida",
        "dar um fim",
    ),
)
def test_standalone_crisis_terms_trigger_handoff(texto: str) -> None:
    assert is_handoff_request(texto)


@pytest.mark.parametrize(
    "texto",
    (
        "quero falar com alguem",
        "TEM ALGUÉM AÍ",
        "quero atendimento humano",
        "me transfere para um atendente",
        "preciso de ajuda humana",
        "quero falar com um ser humano",
        "pode me passar para o pastor",
    ),
)
def test_explicit_human_requests_trigger_handoff(texto: str) -> None:
    assert is_handoff_request(texto)


@pytest.mark.parametrize(
    "texto",
    (
        "nao quero morrer",
        "NÃO VOU MORRER",
        "nao penso em morrer",
        "nao quero me matar",
        "nao quero suicidar-me",
        "não tenho vontade de me matar",
        "não tenho vontade de suicidar-me",
        "NÃO VOU SUICIDAR-ME",
        "nao penso em suicidio",
        "nao quero automutilacao",
        "nao quero me machucar",
        "nao vou me cortar",
        "nao quero acabar com minha vida",
        "nao penso em dar um fim",
        "quero morrer de rir",
        "quero morrer de saudade",
        "quero matar a saudade",
        "ela relatou que pensa em se matar",
        "não quero falar com o pastor",
    ),
)
def test_non_intent_and_negation_do_not_trigger_handoff(texto: str) -> None:
    assert not is_handoff_request(texto)
