"""Closed text-only projection for the V1a WhatsApp cell report.

The existing cell-report workflow remains the parser and revision primitive.
This module narrows its input to the four aggregate values approved for V1a;
free observations and raw inbound text never cross this boundary.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata

from app.domain.cell_report_workflow import (
    CellReportCandidate,
    CellReportWorkflowError,
    merge_cell_report_candidates,
    parse_cell_report_candidate,
)


MAX_V1A_REPORT_TEXT_CHARS = 4_000
_STOP_REMINDERS = re.compile(r"\s*parar\s+lembretes\s*[.!?]*\s*\Z")
_V1A_AGGREGATE_LINE_BREAK = re.compile(
    r"[ \t]*(?:\r\n|\n)[ \t]*(?="
    r"(?:presentes?|visitantes?|decis(?:ão|ões|ao|oes)|ofertas?)\b"
    r"|[0-9]+\s+(?:presentes?|visitantes?|decis(?:ão|ões|ao|oes))\b"
    r"|r\$\s*[0-9]"
    r")",
    re.IGNORECASE,
)


class CellReportV1aError(ValueError):
    """Static, non-disclosing rejection for the narrowed V1a contract."""


def _reject() -> None:
    raise CellReportV1aError("relatório de célula inválido")


def parse_v1a_cell_report_text(text: object) -> CellReportCandidate:
    """Parse only four aggregate fields from one bounded text inbound.

    ``CellReportCandidate`` is reused because it already has closed count and
    money validation.  V1a deliberately rejects observations rather than
    retaining a private-text side channel for a later prompt or summary.
    """

    if type(text) is not str or len(text) > MAX_V1A_REPORT_TEXT_CHARS:
        _reject()
    normalized_text = unicodedata.normalize("NFC", text)
    try:
        candidate = parse_cell_report_candidate(
            _V1A_AGGREGATE_LINE_BREAK.sub("; ", normalized_text)
        )
    except CellReportWorkflowError as exc:
        raise CellReportV1aError("relatório de célula inválido") from exc
    if candidate.observacoes is not None:
        _reject()
    return candidate


def merge_v1a_cell_report_text(
    current: CellReportCandidate,
    patch_text: object,
) -> CellReportCandidate:
    """Revise only explicitly supplied aggregate fields without free text."""

    patch = parse_v1a_cell_report_text(patch_text)
    try:
        merged = merge_cell_report_candidates(current, patch)
    except CellReportWorkflowError as exc:
        raise CellReportV1aError("relatório de célula inválido") from exc
    if merged.observacoes is not None:
        _reject()
    return merged


def render_v1a_cell_report_summary(
    candidate: object,
    *,
    cell_name: object,
    meeting_date: object,
) -> str:
    """Render the fixed confirmation summary from server-owned aggregate facts."""

    if type(candidate) is not CellReportCandidate or not candidate.is_complete:
        _reject()
    if type(meeting_date) is not dt.date or type(meeting_date) is dt.datetime:
        _reject()
    if candidate.observacoes is not None:
        _reject()
    if (
        type(cell_name) is not str
        or not cell_name.strip()
        or cell_name != cell_name.strip()
        or "\n" in cell_name
        or "\r" in cell_name
        or len(cell_name.encode("utf-8", "strict")) > 120
    ):
        _reject()
    try:
        oferta = candidate.oferta
        if type(oferta) is not str:
            _reject()
        reais, centavos = oferta.split(".", 1)
        if not reais.isascii() or not reais.isdigit() or len(centavos) != 2:
            _reject()
        assert candidate.presentes is not None
        assert candidate.visitantes is not None
        assert candidate.decisoes is not None
    except (AssertionError, ValueError):
        _reject()
    decision_label = "decisão" if candidate.decisoes == 1 else "decisões"
    return (
        f"Resumo do relatório da célula {cell_name}, reunião de "
        f"{meeting_date:%d/%m/%Y}: "
        f"{candidate.presentes} presentes, {candidate.visitantes} visitantes, "
        f"{candidate.decisoes} {decision_label} e oferta total de R$ "
        f"{reais},{centavos}. Responda SIM para confirmar ou envie a correção."
    )


def is_stop_cell_report_reminders_request(text: object) -> bool:
    """Recognize the explicit, scoped reminder refusal without global opt-out."""

    if type(text) is not str:
        return False
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )
    return _STOP_REMINDERS.fullmatch(normalized) is not None


__all__ = [
    "CellReportV1aError",
    "MAX_V1A_REPORT_TEXT_CHARS",
    "is_stop_cell_report_reminders_request",
    "merge_v1a_cell_report_text",
    "parse_v1a_cell_report_text",
    "render_v1a_cell_report_summary",
]
