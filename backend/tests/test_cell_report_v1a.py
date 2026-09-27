from __future__ import annotations

import datetime as dt

import pytest

from app.domain.cell_report_v1a import (
    CellReportV1aError,
    is_stop_cell_report_reminders_request,
    merge_v1a_cell_report_text,
    parse_v1a_cell_report_text,
    render_v1a_cell_report_summary,
)


def test_v1a_text_parser_keeps_only_the_four_aggregate_fields() -> None:
    candidate = parse_v1a_cell_report_text(
        "Presentes: 8; visitantes: 2; decisões: 1; oferta: R$ 42,50"
    )

    assert (candidate.presentes, candidate.visitantes, candidate.decisoes) == (8, 2, 1)
    assert candidate.oferta == "42.50"
    assert candidate.observacoes is None


def test_v1a_text_parser_rejects_private_observations_and_overlong_text() -> None:
    with pytest.raises(CellReportV1aError):
        parse_v1a_cell_report_text(
            "presentes: 8; visitantes: 2; decisões: 1; oferta: 42,50; "
            "obs: dado privado"
        )
    with pytest.raises(CellReportV1aError):
        parse_v1a_cell_report_text("x" * 4001)


def test_v1a_revision_replaces_only_explicit_aggregate_values() -> None:
    initial = parse_v1a_cell_report_text(
        "presentes: 8; visitantes: 2; decisões: 1; oferta: 42,50"
    )

    revised = merge_v1a_cell_report_text(initial, "oferta: R$ 50,00")

    assert (revised.presentes, revised.visitantes, revised.decisoes) == (8, 2, 1)
    assert revised.oferta == "50.00"


def test_v1a_summary_is_deterministic_and_never_echoes_private_text() -> None:
    candidate = parse_v1a_cell_report_text(
        "presentes: 8; visitantes: 2; decisões: 1; oferta: 42,50"
    )

    summary = render_v1a_cell_report_summary(
        candidate,
        cell_name="Esperança",
        meeting_date=dt.date(2026, 9, 27),
    )

    assert summary == (
        "Resumo do relatório da célula Esperança, reunião de 27/09/2026: 8 presentes, "
        "2 visitantes, 1 decisão e oferta total de R$ 42,50. "
        "Responda SIM para confirmar ou envie a correção."
    )
    assert "obs" not in summary.casefold()


@pytest.mark.parametrize("text", ["PARAR LEMBRETES", " parar lembretes! "])
def test_stop_reminders_is_an_explicit_scoped_command(text: str) -> None:
    assert is_stop_cell_report_reminders_request(text) is True


@pytest.mark.parametrize("text", ["pare os lembretes amanhã", "parar lembretes da célula"])
def test_stop_reminders_does_not_capture_other_messages(text: str) -> None:
    assert is_stop_cell_report_reminders_request(text) is False
