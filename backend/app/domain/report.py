"""Cell-report extraction from free text (US-24 / delta-041).

Pure helpers that turn a leader's WhatsApp message into a structured report:
presentes, visitantes, decisões (por Jesus) and oferta. Audio is transcribed
upstream (the agent passes the transcript here as text), so this module only
parses text and stays fully unit-testable.

A decisão por Jesus (decisoes >= 1) is what later opens a consolidation, so the
parser exposes that explicitly via `has_decisions`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Keywords that flag a message as a cell report (any one is enough alongside a
# number, e.g. "tivemos 12 presentes").
REPORT_KEYWORDS: tuple[str, ...] = (
    "presente",
    "presentes",
    "visitante",
    "visitantes",
    "decis",  # decisão / decisões / decisoes
    "oferta",
    "relat",  # relatório / relatorio
)

_INT_AFTER = r"(\d+)"


def _find_count(text: str, *keywords: str) -> int | None:
    """Find an integer near any keyword (either order, same line/phrase)."""
    for kw in keywords:
        # "<n> presentes" / "presentes: <n>" / "presentes <n>"
        patterns = (
            rf"{_INT_AFTER}\s*{kw}\w*",
            rf"{kw}\w*\s*[:=-]?\s*{_INT_AFTER}",
        )
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return int(m.group(1))
    return None


def _find_oferta(text: str) -> float | None:
    """Find a monetary offering amount (R$ 50, oferta 50,00, etc.)."""
    m = re.search(
        r"oferta\w*\s*[:=-]?\s*(?:r\$\s*)?([\d.]+(?:,\d{2})?)",
        text,
        re.IGNORECASE,
    )
    if not m:
        m = re.search(r"r\$\s*([\d.]+(?:,\d{2})?)", text, re.IGNORECASE)
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class CellReport:
    """Structured cell report extracted from text."""

    presentes: int | None
    visitantes: int | None
    decisoes: int | None
    oferta: float | None

    @property
    def has_decisions(self) -> bool:
        """True when at least one decision for Jesus was reported (delta-041)."""
        return bool(self.decisoes and self.decisoes > 0)

    @property
    def is_empty(self) -> bool:
        return (
            self.presentes is None
            and self.visitantes is None
            and self.decisoes is None
            and self.oferta is None
        )


def looks_like_report(text: str | None) -> bool:
    """Heuristic: the message mentions a report keyword and at least one number."""
    if not text:
        return False
    lowered = text.lower()
    has_kw = any(kw in lowered for kw in REPORT_KEYWORDS)
    has_num = bool(re.search(r"\d", lowered))
    return has_kw and has_num


def parse_cell_report(text: str | None) -> CellReport:
    """Extract a structured report from free text (best-effort)."""
    if not text:
        return CellReport(None, None, None, None)
    return CellReport(
        presentes=_find_count(text, "presente"),
        visitantes=_find_count(text, "visitante"),
        decisoes=_find_count(text, "decis"),
        oferta=_find_oferta(text),
    )
