"""Heuristic CSIM detection for a WhatsApp contact (#1).

Pure, deterministic and I/O-free — same style as ``domain.consent`` and
``domain.report``. Flags a contact with **no ministerial link** (a company,
sales/marketing, someone from another city) as **CSIM** so the pastoral funnel
skips them.

The ``contato → visitante`` transition is **not** decided here. A contact only
becomes a *visitante* through a real event — a leader registering the person,
the consolidation team handing them to a leader, or a church **check-in** — not
from a self-declared "I went to church" in chat. So this module only answers
"is this contact outside the ministry's interest?".

This is a v1 heuristic (keywords). An LLM refinement can be layered on later
without changing the call sites. ``sem_interesse=None`` means "no signal — leave
the person as-is", so a neutral message never clears a previously set CSIM flag.
"""

from __future__ import annotations

from dataclasses import dataclass

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

    sem_interesse: bool | None = None
    motivo: str | None = None


def _norm(texto: str | None) -> str:
    return (texto or "").strip().lower()


def classify_contact(texto: str | None) -> Classification:
    """Flag CSIM from the latest message, or return an empty Classification."""
    t = _norm(texto)
    for keywords, motivo in CSIM_RULES:
        if any(k in t for k in keywords):
            return Classification(sem_interesse=True, motivo=motivo)
    return Classification()
