"""Unit tests for service-level pure helpers (Asaas + Google Calendar)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.config import Settings
from app.services.asaas import (
    AsaasClient,
    AsaasError,
    AsaasOwnershipError,
    _sao_paulo_today,
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


def test_customer_lookup_and_creation_use_reserved_external_reference() -> None:
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
            return _Response(
                {
                    "id": "cus_test",
                    "externalReference": "pastorai-customer-igreja-1",
                }
            )

    customer_id = AsaasClient(_sends_allowed_settings())._ensure_customer(
        _Client(),
        {"access_token": "test"},
        nome="Igreja Teste",
        email="financeiro@example.com",
        cpf_cnpj="24971563792",
        external_reference="pastorai-customer-igreja-1",
    )

    assert customer_id == "cus_test"
    assert calls == [
        {
            "method": "get",
            "path": "/customers",
            "headers": {"access_token": "test"},
            "params": {
                "externalReference": "pastorai-customer-igreja-1",
                "limit": 100,
                "offset": 0,
            },
        },
        {
            "method": "post",
            "path": "/customers",
            "headers": {"access_token": "test"},
            "json": {
                "name": "Igreja Teste",
                "email": "financeiro@example.com",
                "cpfCnpj": "24971563792",
                "externalReference": "pastorai-customer-igreja-1",
            },
        },
    ]


def test_one_time_charge_rejects_value_below_asaas_minimum_before_network() -> None:
    settings = Settings(
        app_env="staging",
        allow_real_sends=True,
        asaas_billing_enabled=True,
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
            expected_customer_external_reference="pastorai-customer-igreja-1",
        )


def test_billing_writes_stay_offline_without_dedicated_permission() -> None:
    """O gate dedicado bloqueia apenas mutações; leituras são independentes."""
    client = AsaasClient(
        Settings(
            app_env="staging",
            allow_real_sends=False,
            asaas_billing_enabled=False,
        )
    )

    assert (
        client.restore_payment(
            "pay_x",
            expected_subscription_id="sub_x",
            expected_customer_id="cus_x",
            expected_subscription_external_reference="pastorai-subcreate-x",
        )
        is None
    )
    assert (
        client.update_subscription(
            "sub_x",
            valor=299.0,
            descricao="PastorAI — plano x",
            expected_external_reference="pastorai-subcreate-x",
        )
        is None
    )
    assert (
        client.create_one_time_charge(
            customer_id="cus_x",
            valor=59.9,
            description="PastorAI — taxa de setup",
            external_reference="pastorai-setup-x",
            expected_customer_external_reference="pastorai-customer-igreja-1",
        )
        is None
    )


def _sends_allowed_settings() -> Settings:
    return Settings(
        app_env="staging",
        allow_real_sends=True,
        asaas_billing_enabled=True,
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

    monkeypatch.setattr(AsaasClient, "_latest_subscription_payment", _boom)

    result = client.create_checkout(
        nome="Igreja Teste",
        email="financeiro@example.com",
        plano="ate_100",
        valor=199.0,
        cpf_cnpj="24971563792",
        customer_external_reference="pastorai-customer-igreja-1",
        external_reference="pastorai-subcreate-op1",
        on_subscription_created=lambda c, s: tracked.append((c, s)),
    )

    assert tracked == [("cus_1", "sub_1")]
    assert result.subscription_id == "sub_1"
    assert result.invoice_url is None
    assert result.invoice_payment_id is None
    assert result.status == "pendente"


def test_subscription_payment_lookup_returns_newest_cycle_across_pages() -> None:
    calls: list[dict] = []
    pages = {
        0: {
            "data": [
                {"id": "pay_old", "dueDate": "2026-06-30", "status": "RECEIVED"},
                {"id": "pay_current", "dueDate": "2026-08-31", "status": "OVERDUE"},
            ],
            "hasMore": True,
        },
        2: {
            "data": [
                {"id": "pay_middle", "dueDate": "2026-07-31", "status": "RECEIVED"}
            ],
            "hasMore": False,
        },
    }

    class _Response:
        def __init__(self, body: dict) -> None:
            self._body = body

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return self._body

    class _Client:
        def get(self, path: str, *, headers: dict, params: dict) -> _Response:
            calls.append({"path": path, "headers": headers, "params": params})
            return _Response(pages[params["offset"]])

    payment = AsaasClient()._latest_subscription_payment(
        _Client(),
        {"access_token": "test"},
        subscription_id="sub_1",
    )

    assert payment == {
        "id": "pay_current",
        "dueDate": "2026-08-31",
        "status": "OVERDUE",
    }
    assert [call["params"] for call in calls] == [
        {"limit": 100, "offset": 0},
        {"limit": 100, "offset": 2},
    ]


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


def test_asaas_billing_date_uses_the_sao_paulo_calendar_day() -> None:
    # 01:30 UTC de 04/08 ainda é 22:30 de 03/08 no fuso do produto.
    instant = dt.datetime(2026, 8, 4, 1, 30, tzinfo=dt.UTC)

    assert _sao_paulo_today(instant) == dt.date(2026, 8, 3)


def test_subscription_payload_sets_first_due_date(monkeypatch) -> None:
    """Asaas exige a data da primeira cobrança ao criar uma assinatura."""

    calls: list[dict] = []
    billing_date = dt.date(2030, 1, 2)
    monkeypatch.setattr(
        "app.services.asaas._sao_paulo_today", lambda: billing_date
    )

    class _Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, str]:
            return {"id": "sub_test"}

    class _Client:
        def post(self, path: str, *, headers: dict, json: dict) -> _Response:
            calls.append({"path": path, "headers": headers, "json": json})
            return _Response()

    client = AsaasClient(_sends_allowed_settings())
    result = client._create_subscription(
        _Client(),
        {"access_token": "test"},
        customer_id="cus_test",
        valor=19.9,
        ciclo="MONTHLY",
        descricao="Plano de teste",
        external_reference="pastorai-subcreate-test",
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
                "nextDueDate": billing_date.isoformat(),
                "description": "Plano de teste",
                "externalReference": "pastorai-subcreate-test",
            },
        }
    ]


def test_setup_charge_payload_sets_due_date(monkeypatch) -> None:
    """A taxa avulsa também exige a data de vencimento no Asaas."""

    calls: list[dict] = []
    billing_date = dt.date(2030, 1, 2)
    monkeypatch.setattr(
        "app.services.asaas._sao_paulo_today", lambda: billing_date
    )

    class _Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, str]:
            return {"id": "pay_test", "invoiceUrl": "https://asaas.test/setup"}

    class _Client:
        def post(self, path: str, *, headers: dict, json: dict) -> _Response:
            calls.append({"path": path, "headers": headers, "json": json})
            return _Response()

    result = AsaasClient(_sends_allowed_settings())._create_one_time_charge(
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
                "dueDate": billing_date.isoformat(),
                "description": "PastorAI — taxa de setup",
                "externalReference": "pastorai-setup-op1",
            },
        }
    ]


def test_update_subscription_puts_in_place_and_freezes_pending_payments(
    monkeypatch,
) -> None:
    """Troca de plano = PUT na MESMA assinatura com updatePendingPayments=false
    (cobranças já emitidas intocadas; vigência no próximo ciclo)."""
    calls: list[dict] = []

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "id": "sub_1",
                "value": 299.0,
                "externalReference": "pastorai-subcreate-op1",
            }

    class _FakeHttpClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> bool:
            return False

        def get(self, path: str, *, headers: dict) -> _Resp:
            calls.append({"path": path, "method": "get"})
            return _Resp()

        def put(self, path: str, *, headers: dict, json: dict) -> _Resp:
            calls.append({"path": path, "json": json})
            return _Resp()

    import app.services.asaas as asaas_mod

    monkeypatch.setattr(asaas_mod.httpx, "Client", _FakeHttpClient)

    result = AsaasClient(_sends_allowed_settings()).update_subscription(
        "sub_1",
        valor=299.0,
        descricao="PastorAI — plano 101_200",
        expected_external_reference="pastorai-subcreate-op1",
    )

    assert result == {
        "id": "sub_1",
        "value": 299.0,
        "externalReference": "pastorai-subcreate-op1",
    }
    assert calls == [
        {
            "path": "/subscriptions/sub_1",
            "method": "get",
        },
        {
            "path": "/subscriptions/sub_1",
            "json": {
                "value": 299.0,
                "description": "PastorAI — plano 101_200",
                "updatePendingPayments": False,
            },
        }
    ]


@pytest.mark.parametrize(
    ("finder", "path"),
    [
        ("find_subscriptions_by_external_reference", "/subscriptions"),
        ("find_payments_by_external_reference", "/payments"),
    ],
)
def test_external_reference_search_reads_every_page(
    monkeypatch, finder: str, path: str
) -> None:
    offsets: list[int] = []

    class _Response:
        def __init__(self, body: dict) -> None:
            self._body = body

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return self._body

    class _Http:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> bool:
            return False

        def get(self, requested_path: str, *, headers: dict, params: dict):
            assert requested_path == path
            offsets.append(params["offset"])
            if params["offset"] == 0:
                return _Response(
                    {"data": [{"id": "first"}], "hasMore": True}
                )
            return _Response(
                {"data": [{"id": "second"}], "hasMore": False}
            )

    monkeypatch.setattr("app.services.asaas.httpx.Client", _Http)
    client = AsaasClient(_sends_allowed_settings())

    result = getattr(client, finder)("pastorai-owned-reference")

    assert result == [{"id": "first"}, {"id": "second"}]
    assert offsets == [0, 1]


def test_subscription_ownership_mismatch_blocks_put(monkeypatch) -> None:
    methods: list[str] = []

    class _Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "id": "sub_legacy",
                "externalReference": "external-legacy-resource",
            }

    class _Http:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> bool:
            return False

        def get(self, path: str, *, headers: dict):
            methods.append("GET")
            return _Response()

        def put(self, *args, **kwargs):  # pragma: no cover - defesa
            methods.append("PUT")
            raise AssertionError("recurso legado não pode ser alterado")

    monkeypatch.setattr("app.services.asaas.httpx.Client", _Http)

    with pytest.raises(AsaasOwnershipError, match="não pertence"):
        AsaasClient(_sends_allowed_settings()).update_subscription(
            "sub_legacy",
            valor=299.0,
            descricao="PastorAI — plano 101_200",
            expected_external_reference="pastorai-subcreate-owned",
        )

    assert methods == ["GET"]


def test_customer_ownership_mismatch_blocks_one_time_charge(monkeypatch) -> None:
    methods: list[str] = []

    class _Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "id": "cus_legacy",
                "externalReference": "external-legacy-resource",
            }

    class _Http:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> bool:
            return False

        def get(self, path: str, *, headers: dict):
            methods.append("GET")
            return _Response()

        def post(self, *args, **kwargs):  # pragma: no cover - defesa
            methods.append("POST")
            raise AssertionError("customer legado não pode receber cobrança")

    monkeypatch.setattr("app.services.asaas.httpx.Client", _Http)

    with pytest.raises(AsaasOwnershipError, match="não pertence"):
        AsaasClient(_sends_allowed_settings()).create_one_time_charge(
            customer_id="cus_legacy",
            valor=59.9,
            description="PastorAI — taxa de setup",
            external_reference="pastorai-setup-owned",
            expected_customer_external_reference="pastorai-customer-igreja-1",
        )

    assert methods == ["GET"]


def test_restore_ownership_mismatch_blocks_post(monkeypatch) -> None:
    methods: list[str] = []

    class _Response:
        def __init__(self, body: dict) -> None:
            self._body = body

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return self._body

    class _Http:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> bool:
            return False

        def get(self, path: str, *, headers: dict):
            methods.append("GET")
            if path.startswith("/payments/"):
                return _Response(
                    {
                        "id": "pay_legacy",
                        "subscription": "sub_legacy",
                        "customer": "cus_legacy",
                        "deleted": True,
                    }
                )
            return _Response(
                {
                    "id": "sub_legacy",
                    "externalReference": "external-legacy-resource",
                }
            )

        def post(self, *args, **kwargs):  # pragma: no cover - defesa
            methods.append("POST")
            raise AssertionError("cobrança legada não pode ser restaurada")

    monkeypatch.setattr("app.services.asaas.httpx.Client", _Http)

    with pytest.raises(AsaasOwnershipError, match="não pertence"):
        AsaasClient(_sends_allowed_settings()).restore_payment(
            "pay_legacy",
            expected_subscription_id="sub_legacy",
            expected_customer_id="cus_legacy",
            expected_subscription_external_reference="pastorai-subcreate-owned",
        )

    assert methods == ["GET", "GET"]


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
