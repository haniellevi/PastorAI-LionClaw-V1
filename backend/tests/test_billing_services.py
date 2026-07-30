"""Unit tests for service-level pure helpers (Asaas + Google Calendar)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.services.asaas import AsaasClient, map_payment_status, verify_webhook_token
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


def test_subscription_payload_sets_first_due_date() -> None:
    """Asaas exige a data da primeira cobrança ao criar uma assinatura."""

    calls: list[dict] = []

    class _Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, str]:
            return {"id": "sub_test"}

    class _Client:
        def post(self, path: str, *, headers: dict, json: dict) -> _Response:
            calls.append({"path": path, "headers": headers, "json": json})
            return _Response()

    client = AsaasClient()
    result = client._create_subscription(
        _Client(),
        {"access_token": "test"},
        customer_id="cus_test",
        valor=19.9,
        ciclo="MONTHLY",
        descricao="Plano de teste",
        external_reference="sandbox-ref",
    )

    assert result == {"id": "sub_test"}
    assert calls == [
        {
            "path": "/subscriptions",
            "headers": {"access_token": "test"},
            "json": {
                "customer": "cus_test",
                "billingType": "UNDEFINED",
                "value": 19.9,
                "cycle": "MONTHLY",
                "nextDueDate": dt.date.today().isoformat(),
                "description": "Plano de teste",
                "externalReference": "sandbox-ref",
            },
        }
    ]


def test_setup_charge_payload_sets_due_date() -> None:
    """A taxa avulsa também exige a data de vencimento no Asaas."""

    calls: list[dict] = []

    class _Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, str]:
            return {"id": "pay_test"}

    class _Client:
        def post(self, path: str, *, headers: dict, json: dict) -> _Response:
            calls.append({"path": path, "headers": headers, "json": json})
            return _Response()

    result = AsaasClient()._create_setup_charge(
        _Client(), {"access_token": "test"}, customer_id="cus_test", valor=3.0
    )

    assert result == "pay_test"
    assert calls == [
        {
            "path": "/payments",
            "headers": {"access_token": "test"},
            "json": {
                "customer": "cus_test",
                "billingType": "UNDEFINED",
                "value": 3.0,
                "dueDate": dt.date.today().isoformat(),
                "description": "PastorAI — taxa de setup",
            },
        }
    ]


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
