from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
import uuid

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


def _reminder_claim() -> reminders.ReminderClaim:
    return reminders.ReminderClaim(
        igreja_id=uuid.UUID("00000000-0000-0000-0000-0000000000a1"),
        reminder_id=uuid.UUID("00000000-0000-0000-0000-0000000000b1"),
        reuniao_id=uuid.UUID("00000000-0000-0000-0000-0000000000c1"),
        leader_pessoa_id=uuid.UUID("00000000-0000-0000-0000-0000000000d1"),
        claim_token=uuid.UUID("00000000-0000-0000-0000-0000000000e1"),
        instance="synthetic-instance",
        phone="5500000000000",
        text=reminders.cell_report_reminder_text(),
    )


def test_dispatch_scans_past_a_cancelled_head_to_send_the_next_due_reminder(monkeypatch) -> None:
    claim = _reminder_claim()
    attempts = iter(
        (
            reminders._ReminderClaimAttempt(claim=None, exhausted=False),
            reminders._ReminderClaimAttempt(claim=claim, exhausted=False),
        )
    )
    scans: list[object] = []
    sends: list[tuple[str, str, str]] = []

    class _Client:
        def send_text_classificado(self, instance: str, phone: str, text: str):
            sends.append((instance, phone, text))
            return BroadcastSendResult(status="aceito")

    monkeypatch.setattr(reminders, "_discover_tenants", lambda *_args, **_kwargs: (claim.igreja_id,))

    def claim_next(*_args, **_kwargs):
        scans.append(object())
        return next(attempts)

    monkeypatch.setattr(reminders, "_claim_next_reminder", claim_next)
    monkeypatch.setattr(reminders, "_renew_reminder_transport_fence", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(reminders, "_record_reminder_result", lambda *_args, **_kwargs: True)

    dispatched = reminders.dispatch_cell_report_reminders(
        lambda: pytest.fail("o teste não abre sessão"),
        _Client(),
        worker_id="synthetic-worker",
        now=dt.datetime(2026, 9, 27, 18, tzinfo=dt.timezone.utc),
        limit=2,
    )

    assert dispatched == 1
    assert len(scans) == 2
    assert sends == [(claim.instance, claim.phone, claim.text)]


def test_dispatch_excludes_a_skipped_head_before_the_next_scan(monkeypatch) -> None:
    claim = _reminder_claim()
    skipped_id = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
    attempts = iter(
        (
            reminders._ReminderClaimAttempt(
                claim=None,
                exhausted=False,
                candidate_id=skipped_id,
            ),
            reminders._ReminderClaimAttempt(
                claim=claim,
                exhausted=False,
                candidate_id=claim.reminder_id,
            ),
        )
    )
    exclusions: list[tuple[uuid.UUID, ...]] = []
    sends: list[tuple[str, str, str]] = []

    class _Client:
        def send_text_classificado(self, instance: str, phone: str, text: str):
            sends.append((instance, phone, text))
            return BroadcastSendResult(status="aceito")

    monkeypatch.setattr(reminders, "_discover_tenants", lambda *_args, **_kwargs: (claim.igreja_id,))

    def claim_next(*_args, **kwargs):
        exclusions.append(kwargs["excluded_reminder_ids"])
        return next(attempts)

    monkeypatch.setattr(reminders, "_claim_next_reminder", claim_next)
    monkeypatch.setattr(reminders, "_renew_reminder_transport_fence", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(reminders, "_record_reminder_result", lambda *_args, **_kwargs: True)

    dispatched = reminders.dispatch_cell_report_reminders(
        lambda: pytest.fail("o teste não abre sessão"),
        _Client(),
        worker_id="synthetic-worker",
        now=dt.datetime(2026, 9, 27, 18, tzinfo=dt.timezone.utc),
        limit=2,
    )

    assert dispatched == 1
    assert exclusions == [(), (skipped_id,)]
    assert sends == [(claim.instance, claim.phone, claim.text)]


def test_dispatch_scan_limit_counts_discarded_candidates(monkeypatch) -> None:
    claim = _reminder_claim()
    attempts = iter(
        (
            reminders._ReminderClaimAttempt(claim=None, exhausted=False),
            reminders._ReminderClaimAttempt(claim=None, exhausted=False),
            reminders._ReminderClaimAttempt(claim=claim, exhausted=False),
        )
    )
    scans: list[object] = []

    monkeypatch.setattr(reminders, "_discover_tenants", lambda *_args, **_kwargs: (claim.igreja_id,))

    def claim_next(*_args, **_kwargs):
        scans.append(object())
        return next(attempts)

    monkeypatch.setattr(reminders, "_claim_next_reminder", claim_next)

    dispatched = reminders.dispatch_cell_report_reminders(
        lambda: pytest.fail("o teste não abre sessão"),
        SimpleNamespace(send_text_classificado=lambda *_args: pytest.fail("não deve enviar")),
        worker_id="synthetic-worker",
        now=dt.datetime(2026, 9, 27, 18, tzinfo=dt.timezone.utc),
        limit=2,
    )

    assert dispatched == 0
    assert len(scans) == 2
