"""Unit tests for service-level pure helpers (Asaas + Google Calendar)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.config import Settings
from app.services.asaas import (
    AsaasClient,
    AsaasError,
    map_payment_status,
    payment_invoice_url,
    verify_webhook_token,
)
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


def test_asaas_headers_identify_the_client() -> None:
    headers = AsaasClient()._headers("test")

    assert headers == {
        "access_token": "test",
        "Content-Type": "application/json",
        "User-Agent": "PastorAI/1.0 (Python; billing)",
    }


def test_customer_lookup_and_creation_require_the_document() -> None:
    calls: list[dict] = []

    class _Response:
        def __init__(self, body: dict) -> None:
            self._body = body

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return self._body

    class _Client:
        def get(self, path: str, *, headers: dict, params: dict) -> _Response:
            calls.append({"method": "get", "path": path, "headers": headers, "params": params})
            return _Response({"data": []})

        def post(self, path: str, *, headers: dict, json: dict) -> _Response:
            calls.append({"method": "post", "path": path, "headers": headers, "json": json})
            return _Response({"id": "cus_test"})

    customer_id = AsaasClient()._ensure_customer(
        _Client(),
        {"access_token": "test"},
        nome="Igreja Teste",
        email="financeiro@example.com",
        cpf_cnpj="24971563792",
    )

    assert customer_id == "cus_test"
    assert calls == [
        {
            "method": "get",
            "path": "/customers",
            "headers": {"access_token": "test"},
            "params": {"cpfCnpj": "24971563792"},
        },
        {
            "method": "post",
            "path": "/customers",
            "headers": {"access_token": "test"},
            "json": {
                "name": "Igreja Teste",
                "email": "financeiro@example.com",
                "cpfCnpj": "24971563792",
            },
        },
    ]


def test_one_time_charge_rejects_value_below_asaas_minimum_before_network() -> None:
    settings = Settings(
        app_env="staging",
        allow_real_sends=True,
        asaas_api_url="https://api-sandbox.asaas.com/v3",
        asaas_api_key="sandbox-key",
        asaas_setup_fee=3.0,
    )

    with pytest.raises(AsaasError, match=r"pelo menos R\$ 5,00"):
        AsaasClient(settings).create_one_time_charge(
            customer_id="cus_test",
            valor=3.0,
            description="PastorAI — taxa de setup",
            external_reference="pastorai-setup-x",
        )


def test_invoice_link_lookups_stay_offline_without_send_permission() -> None:
    """Recovery/operações respeitam o outbound guard: fora de produção (sem
    ALLOW_REAL_SENDS) devolvem vazio sem tocar a rede."""
    client = AsaasClient()

    assert client.get_subscription_invoice_url("sub_x") is None
    assert client.get_payment_invoice_url("pay_x") is None
    assert client.get_subscription_payment("sub_x") is None
    assert client.get_payment("pay_x") is None
    assert client.restore_payment("pay_x") is None
    assert client.find_payments_by_external_reference("pastorai-setup-x") == []
    assert (
        client.create_one_time_charge(
            customer_id="cus_x",
            valor=59.9,
            description="PastorAI — taxa de setup",
            external_reference="pastorai-setup-x",
        )
        is None
    )


def _sends_allowed_settings() -> Settings:
    return Settings(
        app_env="staging",
        allow_real_sends=True,
        asaas_api_url="https://api-sandbox.asaas.com/v3",
        asaas_api_key="sandbox-key",
        asaas_setup_fee=0.0,
    )


def test_checkout_survives_invoice_lookup_failure_after_subscription_created(
    monkeypatch,
) -> None:
    """Falha TRANSITÓRIA no lookup da 1ª fatura não pode abortar um checkout
    cuja assinatura já existe no Asaas — o resultado volta sem link e o
    callback de rastreio já foi disparado (retry não duplica)."""
    import httpx

    client = AsaasClient(_sends_allowed_settings())
    tracked: list[tuple[str, str]] = []

    monkeypatch.setattr(
        AsaasClient, "_ensure_customer", lambda self, *a, **k: "cus_1"
    )
    monkeypatch.setattr(
        AsaasClient, "_create_subscription", lambda self, *a, **k: {"id": "sub_1"}
    )

    def _boom(self, *a, **k):
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(AsaasClient, "_first_subscription_payment", _boom)

    result = client.create_checkout(
        nome="Igreja Teste",
        email="financeiro@example.com",
        plano="ate_100",
        valor=199.0,
        cpf_cnpj="24971563792",
        on_subscription_created=lambda c, s: tracked.append((c, s)),
    )

    assert tracked == [("cus_1", "sub_1")]
    assert result.subscription_id == "sub_1"
    assert result.invoice_url is None
    assert result.invoice_payment_id is None
    assert result.status == "pendente"


def test_payment_invoice_url_extraction() -> None:
    """Página pública do pagamento: invoiceUrl primeiro, bankSlipUrl como
    fallback; payload vazio/ausente vira None (nunca uma URL herdada)."""
    assert (
        payment_invoice_url({"invoiceUrl": "https://a/i", "bankSlipUrl": "https://a/b"})
        == "https://a/i"
    )
    assert payment_invoice_url({"bankSlipUrl": "https://a/b"}) == "https://a/b"
    assert payment_invoice_url({}) is None
    assert payment_invoice_url(None) is None


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
            return {"id": "pay_test", "invoiceUrl": "https://asaas.test/setup"}

    class _Client:
        def post(self, path: str, *, headers: dict, json: dict) -> _Response:
            calls.append({"path": path, "headers": headers, "json": json})
            return _Response()

    result = AsaasClient()._create_one_time_charge(
        _Client(),
        {"access_token": "test"},
        customer_id="cus_test",
        valor=3.0,
        description="PastorAI — taxa de setup",
        external_reference="pastorai-setup-op1",
    )

    assert result == {"id": "pay_test", "invoiceUrl": "https://asaas.test/setup"}
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
                "externalReference": "pastorai-setup-op1",
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
