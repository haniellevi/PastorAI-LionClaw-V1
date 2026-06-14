"""Unit tests for service-level pure helpers (Asaas + Google Calendar)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.services.asaas import map_payment_status, verify_webhook_token
from app.services.google_calendar import GoogleCalendarError, _to_rfc3339


def test_map_payment_status_known_states() -> None:
    assert map_payment_status("CONFIRMED") == "ativa"
    assert map_payment_status("RECEIVED") == "ativa"
    assert map_payment_status("PENDING") == "pendente"
    assert map_payment_status("OVERDUE") == "inadimplente"


def test_map_payment_status_unknown_and_none() -> None:
    assert map_payment_status("WHATEVER") is None
    assert map_payment_status(None) is None


def test_verify_webhook_token_constant_time() -> None:
    assert verify_webhook_token("secret", "secret") is True
    assert verify_webhook_token("secret", "wrong") is False
    assert verify_webhook_token("", "secret") is False
    assert verify_webhook_token("secret", None) is False


def test_gcal_timed_event_block() -> None:
    start, end = _to_rfc3339(dt.date(2026, 6, 13), "19:30")
    assert "dateTime" in start and "dateTime" in end
    assert start["timeZone"] == "America/Sao_Paulo"


def test_gcal_all_day_event_block() -> None:
    start, end = _to_rfc3339(dt.date(2026, 6, 13), None)
    assert start == {"date": "2026-06-13"}
    assert end == {"date": "2026-06-14"}


def test_gcal_invalid_time_raises() -> None:
    with pytest.raises(GoogleCalendarError):
        _to_rfc3339(dt.date(2026, 6, 13), "nope")
