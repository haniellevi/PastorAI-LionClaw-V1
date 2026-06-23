"""Heuristic classification of a WhatsApp contact (#1 / US-10).

Pure, deterministic and I/O-free — same style as ``domain.consent`` and
``domain.report``. Given a person snapshot + the inbound text, it decides:

- **subetapa**: promote ``novo_contato`` ("contato") → ``visitante`` when there
  are signals the person has already been to the church or a cell (a stored
  signal — cell link / attendance / decision — or a phrase in the message).
- **sem_interesse (CSIM)**: flag a contact with no ministerial link (a company,
  someone from another city, sales/marketing) so the pastoral funnel skips
  them. CSIM never enters consolidation.

This is a v1 heuristic (keyword + state signals). An LLM refinement can be
layered on later without changing the call sites: the orchestrator only needs a
``Classification`` back. Fields left as ``None`` mean "no signal — leave the
person as-is" (so a neutral message never clears a previously set CSIM flag).
"""

from __future__ import annotations

from dataclasses import dataclass

# Phrases that indicate the person has already attended the church or a cell,
# so a "contato" (novo_contato) can be promoted to "visitante".
ATTENDANCE_SIGNALS: tuple[str, ...] = (
    "ja fui",
    "já fui",
    "fui na igreja",
    "fui ao culto",
    "fui no culto",
    "fui na celula",
    "fui na célula",
    "fui no evento",
    "frequento",
    "ja visitei",
    "já visitei",
    "ja estive",
    "já estive",
    "congrego",
    "sou da igreja",
    "sou membro",
    "participei do culto",
    "estive ai",
    "estive aí",
)

# CSIM rules: ordered (keywords, motivo). First match wins. Kept tight to avoid
# false positives — only clear "no ministerial link" signals.
CSIM_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        (
            "empresa",
            "fornecedor",
            "representante comercial",
            "orcamento",
            "orçamento",
            "proposta comercial",
            "parceria comercial",
            "vender",
            "venda de",
            "marketing",
            "propaganda",
            "anuncio",
            "anúncio",
            "publicidade",
            "boleto",
            "cobranca",
            "cobrança",
        ),
        "comercial/empresa",
    ),
    (
        (
            "outra cidade",
            "outro estado",
            "nao sou daqui",
            "não sou daqui",
            "nao sou dessa cidade",
            "não sou dessa cidade",
            "moro longe",
        ),
        "fora da cidade",
    ),
)


@dataclass(frozen=True)
class Classification:
    """Outcome of classifying one inbound turn. ``None`` = no change."""

    subetapa: str | None = None
    sem_interesse: bool | None = None
    motivo: str | None = None


def _norm(texto: str | None) -> str:
    return (texto or "").strip().lower()


def classify_contact(pessoa: dict, texto: str | None) -> Classification:
    """Classify a contact from its snapshot + the latest message.

    Priority: CSIM first (a contact with no ministerial link leaves the funnel),
    then the contato→visitante promotion. Returns an empty ``Classification``
    when there is no signal.
    """
    t = _norm(texto)

    # CSIM tem prioridade: sem vínculo ministerial sai do funil pastoral.
    for keywords, motivo in CSIM_RULES:
        if any(k in t for k in keywords):
            return Classification(sem_interesse=True, motivo=motivo)

    # Promoção contato → visitante: já teve contato presencial com a igreja.
    stored_signal = (
        bool(pessoa.get("tem_celula"))
        or (pessoa.get("presencas_celula") or 0) >= 1
        or bool(pessoa.get("aceitou_jesus"))
    )
    text_signal = any(k in t for k in ATTENDANCE_SIGNALS)
    subetapa_atual = pessoa.get("subetapa")
    if (stored_signal or text_signal) and subetapa_atual in (None, "novo_contato"):
        return Classification(subetapa="visitante")

    return Classification()
