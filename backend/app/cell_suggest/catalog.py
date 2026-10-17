"""Closed, deterministic catalog; no model-supplied identity or location."""

import re
from app.agent.read_only_info import (
    canonical_public_bairro_key,
    canonical_public_info_request,
)

ASK = "Qual é o bairro onde você procura uma célula? Informe somente o bairro, sem endereço de casa. Não calculo distância."
AMBIGUOUS = "Informe somente o bairro completo para a equipe conferir. Não consigo distinguir esses bairros com os dados públicos cadastrados."
MISSING = "Não encontrei célula pública para esse bairro. Vou encaminhar à equipe da igreja para ajudar."


def route(text, *, pending=False):
    key = canonical_public_bairro_key(text)
    # Confirmation words always belong to existing protocols, even while live.
    if key.strip(" .!?") in {"sim", "nao", "ok", "cancelar"} or not key:
        return "none", None
    # Reuse the real S3 catalog's intent markers rather than a second grammar.
    from app.services.agent_privilege_catalog import (
        _ASSIGNMENT_REQUEST,
        _CONSOLIDATION_QUERY_REQUEST,
        _FONOVISITA_REQUEST,
        _REMINDER_REQUEST,
    )

    if any(
        pattern.search(key)
        for pattern in (
            _ASSIGNMENT_REQUEST,
            _CONSOLIDATION_QUERY_REQUEST,
            _FONOVISITA_REQUEST,
            _REMINDER_REQUEST,
        )
    ):
        return "none", None
    request = canonical_public_info_request(text)
    if request and request[0] != "celula":
        return "none", None
    if request and request[0] == "celula":
        return "lookup" if request[1] else "ask", request[1]
    if "celula" in key and re.search(
        r"\b(quero|procuro|encontrar|indique|indica|perto|proxima)\b", key
    ):
        return "ask", None
    # Only a short neighborhood answer while our own delivered prompt is live.
    # Commands for prayer/S3/report and numeric answers are never neighborhoods.
    if (
        pending
        and len(key) <= 120
        and not re.search(
            r"\d|[/:?]|\b(oracao|pastor(?:es)?|relatorio|registre|registrar|decisao|agenda|presenca|visitante|reuniao|celula)\b",
            key,
        )
    ):
        return "lookup", re.sub(
            r"^(?:moro |estou )?(?:no |na |em )?(?:bairro )?", "", key
        )
    return "none", None
