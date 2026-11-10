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
import unicodedata
from dataclasses import dataclass

# Keywords that flag a message as a cell report alongside an extractable
# value, e.g. "tivemos 12 presentes".
REPORT_KEYWORDS: tuple[str, ...] = (
    "presente",
    "presentes",
    "visitante",
    "visitantes",
    "decis",  # decisão / decisões / decisoes
    "oferta",
    "relat",  # relatório / relatorio
)

# Spaced hyphens separate report fields; dates must keep one separator.
_NUMERIC_DATE = re.compile(
    r"(?<!\d)(?:"
    r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}-\d{1,2}-\d{2,4}"
    r"|\d{4}[ \t]*([./])[ \t]*\d{1,2}[ \t]*\1[ \t]*\d{1,2}"
    r"|\d{1,2}[ \t]*([./])[ \t]*\d{1,2}[ \t]*\2[ \t]*\d{2,4}"
    r"|\d{1,2}[ \t]*/[ \t]*\d{1,2}"
    r")(?!\d)"
)
_COUNT_LABEL = r"(?:presentes?|visitantes?|decis(?:ão|ões|ao|oes))"
# A spaced dash can separate a label and its value. An attached sign belongs
# to the value and must not turn a rejected count or amount into a positive one.
_LOOSE_SEPARATOR = r"(?:[ \t]+-[ \t]+|[ \t]*)"
_COUNT_PAIR = re.compile(
    rf"(?<!\w)(?:"
    rf"(?P<after_label>{_COUNT_LABEL})(?![^\W\d_])"
    r"(?:[ \t]*(?P<explicit>[:=])"
    rf"(?:[ \t]*|\s*[\r\n][ \t]*(?=\d+[ \t]*(?:[\r\n]|$)))|{_LOOSE_SEPARATOR})"
    r"(?P<after_value>[+\-\u2212]?(?=\d)\w+)(?!\w|[.,:]\d)"
    rf"|(?:(?P<compact_dash>(?<=\d-))|(?<![\w+\-\u2212]))(?<!\d[.,:])"
    rf"(?P<before_value>\d+)(?!\d|[.,:]\d)[ \t]*(?P<before_label>{_COUNT_LABEL})"
    r"(?![^\W\d_]|[ \t]*[:=]))",
    re.IGNORECASE,
)
_MONEY_VALUE = r"(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{2})?(?!\w|[.,:]\d)"
_OFFERING_PREFIX = (
    r"(?<!\w)ofertas?(?![^\W\d_])"
    r"(?:[ \t]*[:=](?:[ \t]*|\s*[\r\n][ \t]*"
    rf"(?=(?:r\$[ \t]*)?{_MONEY_VALUE}[ \t]*(?:[\r\n]|$)))|{_LOOSE_SEPARATOR})"
    r"(?:r\$[ \t]*)?"
)
_OFFERING_AMOUNT = re.compile(_OFFERING_PREFIX + rf"({_MONEY_VALUE})", re.IGNORECASE)
_CURRENCY_AMOUNT = re.compile(r"r\$[ \t]*" + rf"({_MONEY_VALUE})", re.IGNORECASE)
_MONEY_SPAN = re.compile(rf"(?:{_OFFERING_PREFIX}|r\$[ \t]*)[+\-\u2212]?[ \t]*[\d.,:]+", re.IGNORECASE)
_NO_OFFERING = re.compile(r"(?<!\w)(?:sem|nenhuma)[ \t]+ofertas?(?![^\W\d_])", re.IGNORECASE)
# Do not infer values inside a run of loose pairs that starts with an ambiguous
# offering. Resume at a labeled value or separator, excluding decimal marks.
_FIELD_BOUNDARY = (
    rf"(?<!\w)(?:(?:{_COUNT_LABEL}|ofertas?)[ \t]*[:=]|r\$)"
    r"|[;|]|(?<!\d)[,.]|[,.](?!\d)|[ \t]+-[ \t]+"
)
_AMBIGUOUS_OFFERING = re.compile(
    r"(?<!\w)ofertas?(?:[ \t]+-?[ \t]*|-[ \t]*)\d+(?![\d.,:])"
    rf"[ \t]+{_COUNT_LABEL}(?![^\W\d_])"
    r"(?!\d|[ \t]*[:=])"
    rf"(?:(?!{_FIELD_BOUNDARY})[^\r\n])*",
    re.IGNORECASE,
)


def _find_count(text: str, *keywords: str) -> int | None:
    """Select a field from non-overlapping pairs consumed in message order.

    Every field scans the same pairs, so a number belongs to only one label.
    The first explicit ``label: n`` / ``label = n`` wins over loose pairs.
    A value after a line break must stand alone on that line.
    """
    fallback = None
    previous_count_end = -1
    for match in _COUNT_PAIR.finditer(text):
        # An attached dash separates fields only after a recognized count.
        if match.group("compact_dash") is not None and match.start() != previous_count_end + 1:
            continue
        raw = match.group("after_value") or match.group("before_value")
        if not raw.isdecimal():
            continue
        previous_count_end = match.end()
        label = (match.group("after_label") or match.group("before_label")).lower()
        if not any(label.startswith(kw) for kw in keywords):
            continue
        value = int(raw)
        if match.group("explicit"):
            return value
        if fallback is None:
            fallback = value
    return fallback


def _find_oferta(text: str) -> float | None:
    """Find a monetary offering amount (R$ 50, oferta 50,00, etc.)."""
    m = _OFFERING_AMOUNT.search(text) or _CURRENCY_AMOUNT.search(text)
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
    """Require a report keyword and a value the report parser can extract."""
    if not text:
        return False
    lowered = text.lower()
    has_kw = any(kw in lowered for kw in REPORT_KEYWORDS)
    return has_kw and not parse_cell_report(text).is_empty


def parse_cell_report(text: str | None) -> CellReport:
    """Extract a structured report from free text (best-effort)."""
    if not text:
        return CellReport(None, None, None, None)
    text = unicodedata.normalize("NFC", text)
    # Block numeric dates without joining neighbouring labels and values.
    text = _NUMERIC_DATE.sub("|", text)
    text = _AMBIGUOUS_OFFERING.sub("|", _NO_OFFERING.sub("|", text))
    oferta = _find_oferta(text)
    # Reserve every monetary span, including amounts not selected as oferta.
    text = _MONEY_SPAN.sub("|", text)
    return CellReport(
        presentes=_find_count(text, "presente"),
        visitantes=_find_count(text, "visitante"),
        decisoes=_find_count(text, "decis"),
        oferta=oferta,
    )
