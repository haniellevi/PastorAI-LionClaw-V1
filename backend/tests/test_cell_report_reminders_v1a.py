from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from app.services import cell_report_reminders as reminders
from app.services.evolution import BroadcastSendResult


def test_reminder_due_time_uses_sao_paulo_two_hours_after_meeting() -> None:
    due = reminders.cell_report_reminder_due_at(dt.date(2026, 9, 27), "19:00")

    assert due == dt.datetime(2026, 9, 28, 0, tzinfo=dt.timezone.utc)


def test_reminder_after_window_moves_to_next_local_morning_without_anticipating() -> None:
    due = reminders.cell_report_reminder_due_at(dt.date(2026, 9, 27), "20:00")

    assert due == dt.datetime(2026, 9, 28, 11, tzinfo=dt.timezone.utc)


@pytest.mark.parametrize("hora", [None, "", "25:00", "19:7", 19])
def test_reminder_is_not_created_without_a_valid_local_meeting_time(hora: object) -> None:
    assert reminders.cell_report_reminder_due_at(dt.date(2026, 9, 27), hora) is None


def test_reminder_is_obsolete_only_after_twenty_four_hours_from_meeting_start() -> None:
    meeting_date = dt.date(2026, 9, 27)

    assert not reminders.cell_report_reminder_is_obsolete(
        meeting_date,
        "19:00",
        dt.datetime(2026, 9, 28, 22, tzinfo=dt.timezone.utc),
    )
    assert reminders.cell_report_reminder_is_obsolete(
        meeting_date,
        "19:00",
        dt.datetime(2026, 9, 28, 22, 0, 1, tzinfo=dt.timezone.utc),
    )


def test_pre_send_retry_has_only_two_retry_indices_and_then_cancels() -> None:
    now = dt.datetime(2026, 9, 27, 18, tzinfo=dt.timezone.utc)
    first = reminders.reminder_result_transition(
        BroadcastSendResult(status="falhou_retentavel"), attempts=0, now=now
    )
    second = reminders.reminder_result_transition(
        BroadcastSendResult(status="falhou_retentavel"), attempts=1, now=first.due_at
    )
    exhausted = reminders.reminder_result_transition(
        BroadcastSendResult(status="falhou_retentavel"), attempts=2, now=second.due_at
    )

    assert (first.state, first.attempts, first.due_at) == (
        "retry",
        1,
        now + dt.timedelta(minutes=1),
    )
    assert (second.state, second.attempts, second.due_at) == (
        "retry",
        2,
        now + dt.timedelta(minutes=6),
    )
    assert (exhausted.state, exhausted.attempts, exhausted.terminal_reason) == (
        "cancelado",
        2,
        "retries_esgotados",
    )


@pytest.mark.parametrize(
    "result",
    [
        BroadcastSendResult(status="desconhecido"),
        BroadcastSendResult(status="resultado_invalido"),
        object(),
    ],
)
def test_unknown_or_invalid_result_is_terminal_ambiguity(result: object) -> None:
    transition = reminders.reminder_result_transition(
        result,
        attempts=0,
        now=dt.datetime(2026, 9, 27, 18, tzinfo=dt.timezone.utc),
    )

    assert transition.state == "ambiguo"
    assert transition.attempts == 0
    assert transition.due_at is None


def test_pre_send_configuration_wait_still_consumes_the_bounded_retry_budget() -> None:
    now = dt.datetime(2026, 9, 27, 18, tzinfo=dt.timezone.utc)
    transition = reminders.reminder_result_transition(
        BroadcastSendResult(
            status="falhou_retentavel",
            retry_after_seconds=180,
            consume_retry_budget=False,
        ),
        attempts=1,
        now=now,
    )

    assert (transition.state, transition.attempts, transition.due_at) == (
        "retry",
        2,
        now + dt.timedelta(minutes=3),
    )
    exhausted = reminders.reminder_result_transition(
        BroadcastSendResult(
            status="falhou_retentavel",
            retry_after_seconds=180,
            consume_retry_budget=False,
        ),
        attempts=transition.attempts,
        now=transition.due_at,
    )
    assert (exhausted.state, exhausted.attempts, exhausted.terminal_reason) == (
        "cancelado",
        2,
        "retries_esgotados",
    )


@pytest.mark.parametrize(
    ("current", "allowed"),
    [
        (dt.datetime(2026, 9, 27, 11, tzinfo=dt.timezone.utc), True),  # 08:00 São Paulo
        (dt.datetime(2026, 9, 28, 0, tzinfo=dt.timezone.utc), True),  # 21:00 São Paulo
        (dt.datetime(2026, 9, 27, 10, 59, tzinfo=dt.timezone.utc), False),  # 07:59
        (dt.datetime(2026, 9, 28, 1, tzinfo=dt.timezone.utc), False),  # 22:00
    ],
)
def test_reminder_transport_window_is_strictly_sao_paulo_business_hours(
    current: dt.datetime,
    allowed: bool,
) -> None:
    assert reminders.cell_report_reminder_transport_window_open(current) is allowed


def test_transport_adapter_shape_is_accepted_without_expanding_unknown_fields() -> None:
    transition = reminders.reminder_result_transition(
        SimpleNamespace(status="aceito"),
        attempts=0,
        now=dt.datetime(2026, 9, 27, 18, tzinfo=dt.timezone.utc),
    )

    assert transition.state == "enviado"


def test_reminder_message_is_fixed_and_only_its_digest_is_persistable() -> None:
    text = reminders.cell_report_reminder_text()

    assert "PARAR LEMBRETES" in text
    assert len(reminders.cell_report_reminder_text_sha256()) == 64
