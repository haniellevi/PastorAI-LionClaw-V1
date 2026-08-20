"""POST /subscription e GET /subscription/planos usam o catálogo `planos`
(migration 0012, editado pelo master em /admin/planos) como fonte de preço e
limite — não mais os dicts hardcoded que existiam em app/domain/billing.py.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.models import (
    BillingPaymentOperation,
    BillingPlanChangeOperation,
    BillingSubscriptionOperation,
    Subscription,
)
from app.db.session import get_db
from app.services.asaas import (
    AsaasError,
    AsaasRejectedError,
    CheckoutResult,
    get_asaas_client,
)
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_CPF = "249.715.637-92"


def _plano(**over):
    base = dict(
        codigo="ate_100",
        nome="Até 100 pessoas",
        limite_pessoas=100,
        preco_mensal=199,
        ativo=True,
    )
    base.update(over)
    return SimpleNamespace(**base)


class _FakeAsaas:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.charge_calls: list[dict] = []

    def create_checkout(self, **kwargs):
        self.calls.append(kwargs)
        # Espelha o cliente real: o callback rastreia a assinatura ANTES de o
        # resultado voltar ao router.
        callback = kwargs.get("on_subscription_created")
        if callback is not None:
            callback("cus_1", "sub_1")
        return CheckoutResult(
            customer_id="cus_1",
            subscription_id="sub_1",
            invoice_url="https://asaas.test/monthly",
            status="pendente",
            invoice_payment_id="pay_m1",
        )

    def create_one_time_charge(self, **kwargs):
        # Cobrança avulsa emitida pela OPERAÇÃO durável (setup/recovery).
        self.charge_calls.append(kwargs)
        return {"id": "pay_setup_1", "invoiceUrl": "https://asaas.test/setup"}


class _SandboxCheckoutAsaas:
    def __init__(self) -> None:
        self.create_calls = 0

    def create_checkout(self, **kwargs):
        self.create_calls += 1
        return CheckoutResult(
            customer_id="sandbox",
            subscription_id="sandbox",
            invoice_url=None,
            status="pendente",
            invoice_payment_id=None,
        )


class _RecoveryAsaas:
    """Fake do caminho de RECUPERAÇÃO de links (GET /subscription).

    Só sabe consultar por id; qualquer tentativa de criar cobrança durante a
    recuperação explode o teste — recovery é estritamente read-only.
    """

    def __init__(
        self,
        *,
        monthly_url: str | None = None,
        setup_url: str | None = None,
        payment_urls: dict[str, str] | None = None,
        monthly_payment: dict | None = None,
        setup_payment: dict | None = None,
        payment_payloads: dict[str, dict] | None = None,
        unavailable: bool = False,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self._monthly_url = monthly_url
        self._setup_url = setup_url
        self._payment_urls = payment_urls or {}
        self._monthly_payment = monthly_payment
        self._setup_payment = setup_payment
        self._payment_payloads = payment_payloads or {}
        self._unavailable = unavailable

    def get_subscription_payment(self, subscription_id: str):
        self.calls.append(("get_subscription_payment", subscription_id))
        if self._unavailable:
            raise AsaasError("Asaas indisponível")
        if self._monthly_payment is not None:
            return self._monthly_payment
        if self._monthly_url is None:
            return None
        return {
            "id": "pay_m1",
            "status": "PENDING",
            "invoiceUrl": self._monthly_url,
        }

    def get_payment(self, payment_id: str):
        self.calls.append(("get_payment", payment_id))
        if self._unavailable:
            raise AsaasError("Asaas indisponível")
        if payment_id in self._payment_payloads:
            return self._payment_payloads[payment_id]
        if self._setup_payment is not None and str(
            self._setup_payment.get("id")
        ) == str(payment_id):
            return self._setup_payment
        if payment_id in self._payment_urls:
            return {
                "id": payment_id,
                "status": "PENDING",
                "invoiceUrl": self._payment_urls[payment_id],
            }
        if self._setup_url is None:
            return None
        return {
            "id": payment_id,
            "status": "PENDING",
            "invoiceUrl": self._setup_url,
        }

    def get_subscription_invoice_url(self, subscription_id: str) -> str | None:
        self.calls.append(("get_subscription_invoice_url", subscription_id))
        if self._unavailable:
            raise AsaasError("Asaas indisponível")
        return self._monthly_url

    def get_payment_invoice_url(self, payment_id: str) -> str | None:
        self.calls.append(("get_payment_invoice_url", payment_id))
        if self._unavailable:
            raise AsaasError("Asaas indisponível")
        if payment_id in self._payment_urls:
            return self._payment_urls[payment_id]
        return self._setup_url

    def create_checkout(self, **kwargs):  # pragma: no cover - defesa do teste
        raise AssertionError("recovery de links nunca pode criar cobrança")


def _subscription(**over):
    base = dict(
        id="00000000-0000-0000-0000-00000000su01",
        igreja_id=make_app_user().igreja_id,
        plano="ate_100",
        status="pendente",
        pessoas=10,
        limite=100,
        proxima_cobranca=None,
        asaas_customer_id="cus_1",
        asaas_subscription_id="sub_asaas_1",
        asaas_setup_charge_id="pay_setup_1",
        asaas_invoice_payment_id=None,
        asaas_invoice_url=None,
        asaas_invoice_reversal=None,
        asaas_setup_invoice_url=None,
        setup_pago=False,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _client(
    app,
    *,
    planos,
    asaas=None,
    setup_fee_default: float = 0.0,
    setup_fee_override: float | None = None,
    subscription=None,
    operations=None,
    plan_changes=None,
    subscription_ops=None,
    igreja_status: str = "ativa",
    igreja_plano: str | None = None,
) -> tuple[TestClient, FakeSession]:
    app_user = make_app_user(igreja_status=igreja_status)
    igreja = SimpleNamespace(
        id=app_user.igreja_id,
        setup_fee_override=setup_fee_override,
        status=igreja_status,
        plano=igreja_plano,
    )
    db = FakeSession(
        app_user=app_user,
        roles=["admin"],
        planos=planos,
        igreja=igreja,
        billing_settings=SimpleNamespace(id=1, setup_fee_default=setup_fee_default),
        subscription=subscription,
        operations=operations,
        plan_changes=plan_changes,
        subscription_ops=subscription_ops,
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    app.dependency_overrides[get_asaas_client] = lambda: asaas or _FakeAsaas()
    return TestClient(app), db


def test_checkout_charges_price_and_saves_limit_from_planos_table(app) -> None:
    # Master editou preço pra 249 e limite pra 150 (eram 199/100 hardcoded em
    # domain/billing.py) — o checkout tem que cobrar E gravar os valores do
    # catálogo, não valores fixos.
    asaas = _FakeAsaas()
    client, db = _client(
        app, planos=[_plano(preco_mensal=249, limite_pessoas=150)], asaas=asaas
    )
    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert resp.status_code == 200
    assert asaas.calls[0]["valor"] == 249.0
    assert asaas.calls[0]["cpf_cnpj"] == "24971563792"
    # A Subscription nova é passada a db.add() dentro do handler — inspeciona
    # o objeto de verdade em vez de confiar só no preço cobrado no Asaas.
    added_subs = [o for o in db.added if isinstance(o, Subscription)]
    assert len(added_subs) == 1  # a intenção durável também entra em db.added
    assert added_subs[0].limite == 150


def test_new_checkout_keeps_church_and_plan_locked_until_intent_commit(
    app, monkeypatch
) -> None:
    """Placeholder e intenção nascem no mesmo commit sob a ordem canônica."""
    from app.routers import subscription as subscription_router

    events: list[str] = []
    original_lock_church = subscription_router.lock_igreja_for_billing
    original_lock_plans = subscription_router.lock_plan_rows_for_billing
    original_prepare = subscription_router.prepare_subscription_operation

    def lock_church(*args, **kwargs):
        events.append("lock_church")
        return original_lock_church(*args, **kwargs)

    def lock_plans(*args, **kwargs):
        events.append("lock_plans")
        return original_lock_plans(*args, **kwargs)

    def prepare(*args, **kwargs):
        events.append("prepare_intent")
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(subscription_router, "lock_igreja_for_billing", lock_church)
    monkeypatch.setattr(subscription_router, "lock_plan_rows_for_billing", lock_plans)
    monkeypatch.setattr(subscription_router, "prepare_subscription_operation", prepare)

    client, db = _client(app, planos=[_plano()], asaas=_FakeAsaas())
    original_add = db.add
    original_flush = db.flush
    original_commit = db.commit

    def add(obj) -> None:
        if isinstance(obj, Subscription):
            events.append("add_placeholder")
        original_add(obj)

    def flush() -> None:
        events.append("flush_placeholder")
        original_flush()

    def commit() -> None:
        events.append("commit")
        original_commit()

    db.add = add
    db.flush = flush
    db.commit = commit

    response = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert response.status_code == 200
    canonical_prefix = [
        events.index("lock_church"),
        events.index("lock_plans"),
        events.index("add_placeholder"),
        events.index("flush_placeholder"),
        events.index("prepare_intent"),
    ]
    assert canonical_prefix == sorted(canonical_prefix)
    assert "commit" not in events[: events.index("prepare_intent")]
    assert events.index("commit") > events.index("prepare_intent")


def test_sandbox_checkout_keeps_one_retryable_prepared_intent(app) -> None:
    asaas = _SandboxCheckoutAsaas()
    sub = _subscription(
        status=None,
        asaas_customer_id=None,
        asaas_subscription_id=None,
        asaas_setup_charge_id=None,
        setup_fee_contracted=0.0,
        setup_pago=False,
    )
    client, db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        subscription=sub,
        setup_fee_default=0.0,
    )

    first = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    second = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["asaasSubscriptionId"] is None
    assert second.json()["asaasSubscriptionId"] is None
    operations = [
        op for op in db.added if isinstance(op, BillingSubscriptionOperation)
    ]
    assert len(operations) == 1
    assert operations[0].status == "prepared"
    assert operations[0].asaas_subscription_id is None
    assert sub.asaas_subscription_id is None
    assert asaas.create_calls == 2


def test_checkout_uses_price_of_requested_plano_not_another_active_one(app) -> None:
    # Duas ativas no catálogo, códigos diferentes — prova que o handler filtra
    # por CÓDIGO, não só por "algum plano ativo existe". Com o fake antigo
    # (que ignorava o WHERE de codigo) este teste teria cobrado o preço do
    # primeiro plano da lista sem acusar nada.
    asaas = _FakeAsaas()
    client, db = _client(
        app,
        planos=[
            _plano(codigo="ate_100", preco_mensal=199, limite_pessoas=100),
            _plano(codigo="101_200", preco_mensal=299, limite_pessoas=200),
        ],
        asaas=asaas,
    )
    resp = client.post(
        "/subscription", json={"plano": "101_200", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert resp.status_code == 200
    assert asaas.calls[0]["valor"] == 299.0
    assert db.added[0].limite == 200


def test_checkout_uses_master_setup_default_and_returns_two_payment_links(app) -> None:
    asaas = _FakeAsaas()
    client, db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        setup_fee_default=59.9,
    )

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert asaas.calls[0]["valor"] == 199.0
    # A taxa de setup nasce como OPERAÇÃO durável (cobrança avulsa própria).
    assert asaas.charge_calls[0]["valor"] == 59.9
    assert asaas.charge_calls[0]["external_reference"].startswith("pastorai-setup-")
    assert resp.json() == {
        "status": "pendente",
        "invoiceUrl": "https://asaas.test/monthly",
        "setupInvoiceUrl": "https://asaas.test/setup",
        "asaasSubscriptionId": "sub_1",
    }
    assert db.added[0].asaas_setup_charge_id == "pay_setup_1"
    assert db.added[0].setup_pago is False
    # Os links são PERSISTIDOS na assinatura — a tela pendente sobrevive a
    # reload lendo GET /subscription, sem depender do estado do checkout.
    assert db.added[0].asaas_invoice_url == "https://asaas.test/monthly"
    assert db.added[0].asaas_setup_invoice_url == "https://asaas.test/setup"
    # O id da 1ª cobrança mensal também é persistido: os ciclos seguintes (e o
    # recovery) passam a mirar a cobrança exata, nunca "a primeira da assinatura".
    assert db.added[0].asaas_invoice_payment_id == "pay_m1"


def test_checkout_uses_church_setup_override_before_master_default(app) -> None:
    asaas = _FakeAsaas()
    client, _db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        setup_fee_default=59.9,
        setup_fee_override=19.9,
    )

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert asaas.charge_calls[0]["valor"] == 19.9


def test_zero_church_setup_override_skips_the_setup_charge(app) -> None:
    asaas = _FakeAsaas()
    client, db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        setup_fee_default=59.9,
        setup_fee_override=0.0,
    )

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert asaas.charge_calls == []  # isenta: nenhuma cobrança de setup emitida
    assert resp.json()["setupInvoiceUrl"] is None
    assert db.added[0].setup_pago is True
    assert db.added[0].asaas_setup_charge_id is None
    assert db.added[0].asaas_setup_invoice_url is None
    assert db.added[0].asaas_invoice_url == "https://asaas.test/monthly"


def test_new_contract_does_not_recharge_setup_already_paid(app) -> None:
    asaas = _FakeAsaas()
    sub = _subscription(
        asaas_subscription_id=None,
        asaas_setup_charge_id=None,
        setup_pago=True,
    )
    client, db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        setup_fee_default=59.9,
        subscription=sub,
    )

    response = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert response.status_code == 200
    assert asaas.charge_calls == []
    op = next(o for o in db.added if isinstance(o, BillingSubscriptionOperation))
    assert float(op.setup_fee) == 0.0
    assert float(sub.setup_fee_contracted) == 0.0
    assert sub.setup_pago is True


# ---------------------------------------------------------------------------
# GET /subscription — links persistidos e recuperação read-only (PR#219 P2):
# a tela pendente reconstrói o painel de pagamento após reload; se um link se
# perdeu, o backend o recupera pelos ids Asaas já armazenados, sem NUNCA criar
# outra assinatura ou taxa de setup.
# ---------------------------------------------------------------------------
def test_get_subscription_keeps_persisted_links_and_polls_tracked_setup(app) -> None:
    asaas = _RecoveryAsaas()
    sub = _subscription(
        pessoas=999,  # espelho legado propositalmente defasado
        asaas_invoice_url="https://asaas.test/monthly",
        asaas_setup_invoice_url="https://asaas.test/setup",
    )
    client, db = _client(app, planos=[], asaas=asaas, subscription=sub)
    db.pessoas_count = 12

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["pessoas"] == 12  # contrato legado, valor canônico de membros
    assert sub.pessoas == 999  # a leitura não precisa regravar o espelho
    assert body["invoiceUrl"] == "https://asaas.test/monthly"
    assert body["setupInvoiceUrl"] == "https://asaas.test/setup"
    # Mensalidade com link não é consultada. Setup ainda não pago é consultado
    # pelo id mesmo com link, para convergir confirmação/reversão sem webhook.
    assert asaas.calls == [("get_payment", "pay_setup_1")]


def test_get_subscription_exposes_the_setup_fee_frozen_at_checkout(app) -> None:
    asaas = _RecoveryAsaas()
    sub = _subscription(
        setup_pago=False,
        setup_fee_contracted=59.9,
        asaas_invoice_url="https://asaas.test/monthly",
        asaas_setup_invoice_url="https://asaas.test/setup",
    )
    client, _db = _client(app, planos=[], asaas=asaas, subscription=sub)

    response = client.get("/subscription", headers=_AUTH)

    assert response.status_code == 200
    assert response.json()["setupFeeContracted"] == 59.9


def test_get_subscription_recovers_monthly_link_by_subscription_id(app) -> None:
    asaas = _RecoveryAsaas(monthly_url="https://asaas.test/recovered-monthly")
    sub = _subscription(
        asaas_invoice_url=None,
        asaas_setup_charge_id=None,
        asaas_setup_invoice_url=None,
        setup_pago=True,
    )
    client, db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["invoiceUrl"] == "https://asaas.test/recovered-monthly"
    assert sub.asaas_invoice_url == "https://asaas.test/recovered-monthly"
    assert asaas.calls == [("get_subscription_payment", "sub_asaas_1")]
    assert db.commits == 1  # link recuperado é persistido


def test_get_subscription_recovers_by_exact_monthly_payment_id(app) -> None:
    # Ciclo 2+: o webhook rastreou o payment id da fatura corrente mas o link
    # ainda faltava (payload sem invoiceUrl). O GET consulta a cobrança EXATA
    # — nunca a "primeira da assinatura", que já está quitada.
    asaas = _RecoveryAsaas(payment_urls={"pay_m2": "https://asaas.test/m2"})
    sub = _subscription(
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
        asaas_setup_charge_id=None,
        asaas_setup_invoice_url=None,
        setup_pago=True,
    )
    client, db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["invoiceUrl"] == "https://asaas.test/m2"
    assert sub.asaas_invoice_url == "https://asaas.test/m2"
    # Somente a consulta pelo id exato — a busca pela primeira cobrança da
    # assinatura fica restrita a registros legados sem payment id.
    assert asaas.calls == [("get_payment", "pay_m2")]
    assert db.commits == 1


def test_get_subscription_recovers_setup_link_by_charge_id(app) -> None:
    asaas = _RecoveryAsaas(setup_url="https://asaas.test/recovered-setup")
    sub = _subscription(
        asaas_invoice_url="https://asaas.test/monthly",
        asaas_setup_invoice_url=None,
        setup_pago=False,
    )
    client, db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["setupInvoiceUrl"] == "https://asaas.test/recovered-setup"
    assert sub.asaas_setup_invoice_url == "https://asaas.test/recovered-setup"
    assert asaas.calls == [("get_payment", "pay_setup_1")]
    assert db.commits == 1


def test_get_subscription_survives_asaas_outage_with_null_links(app) -> None:
    asaas = _RecoveryAsaas(unavailable=True)
    sub = _subscription()  # pendente, ambos os links ausentes
    client, db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    # A leitura da assinatura continua 200 com links nulos — a tela inteira
    # não vira 502 por indisponibilidade temporária do provedor.
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pendente"
    assert body["invoiceUrl"] is None
    assert body["setupInvoiceUrl"] is None
    assert db.commits == 0  # nada recuperado, nada persistido


def test_link_recovery_never_creates_new_charges(app) -> None:
    asaas = _RecoveryAsaas(
        monthly_url="https://asaas.test/recovered-monthly",
        setup_url="https://asaas.test/recovered-setup",
    )
    sub = _subscription()  # ambos ausentes => recupera os dois
    client, _db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    # Somente consultas por id — _RecoveryAsaas.create_checkout levantaria
    # AssertionError se o recovery tentasse criar qualquer cobrança.
    assert asaas.calls == [
        ("get_subscription_payment", "sub_asaas_1"),
        ("get_payment", "pay_setup_1"),
    ]


def test_get_subscription_returns_invoice_url_when_overdue(app) -> None:
    # Fatura VENCIDA continua pagável: o link persistido é exatamente o caminho
    # de regularização — some só quando a assinatura está ativa/quitada.
    asaas = _RecoveryAsaas()
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url="https://asaas.test/m2-overdue",
    )
    client, _db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["invoiceUrl"] == "https://asaas.test/m2-overdue"
    assert asaas.calls == [("get_payment", "pay_m2")]


def test_get_subscription_recovers_overdue_url_by_current_payment_id(app) -> None:
    asaas = _RecoveryAsaas(
        payment_payloads={
            "pay_m2": {
                "id": "pay_m2",
                "status": "OVERDUE",
                "invoiceUrl": "https://asaas.test/m2-overdue",
            }
        }
    )
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_setup_invoice_url=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
    )
    client, db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["invoiceUrl"] == "https://asaas.test/m2-overdue"
    assert sub.asaas_invoice_url == "https://asaas.test/m2-overdue"
    assert asaas.calls == [("get_payment", "pay_m2")]
    assert db.commits == 1


def test_get_subscription_applies_monthly_confirmation_while_recovering_link(
    app,
) -> None:
    asaas = _RecoveryAsaas(
        payment_payloads={
            "pay_m2": {
                "id": "pay_m2",
                "status": "CONFIRMED",
                "invoiceUrl": "https://asaas.test/m2-paid",
                "value": 199,
            }
        }
    )
    sub = _subscription(
        status="pendente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
    )
    client, db = _client(app, planos=[], asaas=asaas, subscription=sub)
    db.igreja.status = "inadimplente"

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["status"] == "ativa"
    assert resp.json()["invoiceUrl"] is None  # cobrança já quitada
    assert sub.status == "ativa"
    assert db.igreja.status == "ativa"


def test_get_subscription_applies_monthly_refund_while_recovering_link(
    app,
) -> None:
    asaas = _RecoveryAsaas(
        payment_payloads={
            "pay_m2": {
                "id": "pay_m2",
                "status": "REFUNDED",
                "invoiceUrl": "https://asaas.test/m2-dead",
                "value": 199,
            }
        }
    )
    sub = _subscription(
        status="pendente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
    )
    client, db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "inadimplente"
    assert body["invoiceUrl"] is None
    assert body["invoiceReversal"] == "refunded"
    assert body["recoveryRequired"] is True
    assert sub.status == "inadimplente"
    assert db.igreja.status == "inadimplente"


def test_get_subscription_polls_confirmation_even_with_monthly_url(app) -> None:
    asaas = _RecoveryAsaas(
        payment_payloads={
            "pay_m2": {
                "id": "pay_m2",
                "status": "CONFIRMED",
                "invoiceUrl": "https://asaas.test/m2-paid",
                "value": 199.0,
            }
        }
    )
    sub = _subscription(
        status="pendente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url="https://asaas.test/m2",
    )
    client, _db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["status"] == "ativa"
    assert resp.json()["invoiceUrl"] is None
    assert sub.status == "ativa"
    assert asaas.calls == [("get_payment", "pay_m2")]


def test_get_subscription_polls_refund_after_monthly_was_locally_active(
    app,
) -> None:
    asaas = _RecoveryAsaas(
        payment_payloads={
            "pay_m2": {
                "id": "pay_m2",
                "status": "REFUNDED",
                "invoiceUrl": "https://asaas.test/m2-dead",
                "value": 199.0,
            }
        }
    )
    sub = _subscription(
        status="ativa",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
    )
    client, db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["status"] == "inadimplente"
    assert resp.json()["invoiceReversal"] == "refunded"
    assert resp.json()["recoveryRequired"] is True
    assert sub.status == "inadimplente"
    assert sub.asaas_invoice_url is None
    assert db.igreja.status == "inadimplente"
    assert asaas.calls == [("get_payment", "pay_m2")]


def test_get_subscription_applies_setup_confirmation_while_recovering_link(
    app,
) -> None:
    asaas = _RecoveryAsaas(
        setup_payment={
            "id": "pay_setup_1",
            "status": "CONFIRMED",
            "invoiceUrl": "https://asaas.test/setup-paid",
        }
    )
    sub = _subscription(
        asaas_invoice_url="https://asaas.test/monthly",
        setup_pago=False,
        asaas_setup_charge_id="pay_setup_1",
        asaas_setup_invoice_url=None,
    )
    client, _db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["setupPago"] is True
    assert resp.json()["setupInvoiceUrl"] is None
    assert sub.setup_pago is True


def test_get_subscription_applies_setup_refund_while_recovering_link(app) -> None:
    asaas = _RecoveryAsaas(
        setup_payment={
            "id": "pay_setup_1",
            "status": "REFUNDED",
            "invoiceUrl": "https://asaas.test/setup-dead",
        }
    )
    sub = _subscription(
        asaas_invoice_url="https://asaas.test/monthly",
        setup_pago=False,
        asaas_setup_charge_id="pay_setup_1",
        asaas_setup_invoice_url=None,
    )
    client, _db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["setupPago"] is False
    assert resp.json()["setupInvoiceUrl"] is None
    assert sub.asaas_setup_charge_id is None
    assert sub.asaas_setup_reversed_payment_id == "pay_setup_1"


def test_get_subscription_polls_setup_confirmation_even_with_persisted_url(
    app,
) -> None:
    asaas = _RecoveryAsaas(
        setup_payment={
            "id": "pay_setup_1",
            "status": "CONFIRMED",
            "invoiceUrl": "https://asaas.test/setup-paid",
        }
    )
    sub = _subscription(
        asaas_invoice_url="https://asaas.test/monthly",
        setup_pago=False,
        asaas_setup_charge_id="pay_setup_1",
        asaas_setup_invoice_url="https://asaas.test/setup-stale",
    )
    client, _db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["setupPago"] is True
    assert resp.json()["setupInvoiceUrl"] is None
    assert sub.setup_pago is True
    assert asaas.calls == [("get_payment", "pay_setup_1")]


def test_get_subscription_polls_setup_refund_even_with_persisted_url(app) -> None:
    asaas = _RecoveryAsaas(
        setup_payment={
            "id": "pay_setup_1",
            "status": "REFUNDED",
            "invoiceUrl": "https://asaas.test/setup-dead",
        }
    )
    sub = _subscription(
        asaas_invoice_url="https://asaas.test/monthly",
        setup_pago=False,
        asaas_setup_charge_id="pay_setup_1",
        asaas_setup_invoice_url="https://asaas.test/setup-stale",
    )
    client, _db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["setupPago"] is False
    assert resp.json()["setupInvoiceUrl"] is None
    assert sub.asaas_setup_charge_id is None
    assert sub.asaas_setup_reversed_payment_id == "pay_setup_1"
    assert asaas.calls == [("get_payment", "pay_setup_1")]


def test_get_subscription_reconciles_refund_after_setup_was_locally_paid(
    app,
) -> None:
    operation = BillingPaymentOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        purpose="setup",
        operation_key="pastorai-setup-paid-then-refunded",
        status="paid",
        valor=59.9,
        asaas_payment_id="pay_setup_1",
        invoice_url=None,
    )
    asaas = _RecoveryAsaas(
        setup_payment={
            "id": "pay_setup_1",
            "status": "REFUNDED",
            "value": 59.9,
        }
    )
    sub = _subscription(
        status="ativa",
        setup_pago=True,
        setup_fee_contracted=59.9,
        asaas_setup_charge_id="pay_setup_1",
        asaas_setup_invoice_url=None,
    )
    client, _db = _client(
        app,
        planos=[],
        asaas=asaas,
        subscription=sub,
        operations=[operation],
    )

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["setupPago"] is False
    assert resp.json()["setupRecoveryRequired"] is True
    assert operation.status == "reversed"
    assert sub.asaas_setup_charge_id is None
    assert sub.asaas_setup_invoice_url is None
    assert asaas.calls == [("get_payment", "pay_setup_1")]


class _TrackingFailAsaas:
    """create_checkout que rastreia a assinatura via callback e ENTÃO falha —
    simula lookup/setup quebrando depois do POST /subscriptions real."""

    def create_checkout(self, **kwargs):
        kwargs["on_subscription_created"]("cus_1", "sub_1")
        raise AsaasError("falha transitória depois da criação")


class _ResumeAsaas:
    """Fake do caminho de RETOMADA: proíbe recriar a assinatura."""

    def __init__(self, *, payment=None, exact_payment=None, charge=None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._payment = payment
        self._exact_payment = exact_payment
        self._charge = charge

    def create_checkout(self, **kwargs):  # pragma: no cover - defesa do teste
        raise AssertionError("retomada nunca emite outro POST /subscriptions")

    def get_subscription_payment(self, subscription_id: str):
        self.calls.append(("get_subscription_payment", subscription_id))
        return self._payment

    def get_payment(self, payment_id: str):
        self.calls.append(("get_payment", payment_id))
        return self._exact_payment

    def create_one_time_charge(self, **kwargs):
        self.calls.append(("create_one_time_charge", kwargs["customer_id"]))
        return self._charge


def test_checkout_persists_tracking_even_when_client_fails_after_creation(app) -> None:
    # POST /subscriptions remoto ok + falha posterior => 502, mas a assinatura
    # criada NÃO fica órfã: o callback persistiu o vínculo antes da falha.
    client, db = _client(app, planos=[_plano()], asaas=_TrackingFailAsaas())

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 502
    added_subs = [o for o in db.added if isinstance(o, Subscription)]
    assert len(added_subs) == 1
    tracked = added_subs[0]
    assert tracked.asaas_customer_id == "cus_1"
    assert tracked.asaas_subscription_id == "sub_1"
    assert tracked.status == "pendente"
    assert tracked.plano == "ate_100"
    assert db.commits >= 1  # rastreio comitado apesar do 502


def test_creation_callback_preserves_confirmation_that_arrived_first(app) -> None:
    # O webhook confirma a cobrança entre o POST remoto e a callback local.
    # A callback relê sob lock e não pode rebaixar o estado autoritativo.
    client, db = _client(app, planos=[_plano()], asaas=_TrackingFailAsaas())

    def webhook_won(obj, with_for_update) -> None:
        if isinstance(obj, Subscription):
            obj.asaas_subscription_id = "sub_1"
            obj.status = "ativa"

    db.refresh_callback = webhook_won
    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 502  # processo parou depois da callback
    tracked = next(o for o in db.added if isinstance(o, Subscription))
    assert tracked.status == "ativa"
    assert tracked.asaas_subscription_id == "sub_1"
    assert any(obj is tracked and lock is True for obj, lock in db.refresh_calls)


class _WebhookAfterCallbackAsaas:
    """Simula confirmação entre a callback de rastreio e o retorno final."""

    def __init__(self) -> None:
        self.db = None

    def create_checkout(self, **kwargs):
        kwargs["on_subscription_created"]("cus_1", "sub_1")
        tracked = next(o for o in self.db.added if isinstance(o, Subscription))
        tracked.status = "ativa"
        return CheckoutResult(
            customer_id="cus_1",
            subscription_id="sub_1",
            invoice_url="https://asaas.test/m1",
            status="pendente",
            invoice_payment_id="pay_m1",
        )


def test_checkout_result_preserves_confirmation_after_creation_callback(app) -> None:
    asaas = _WebhookAfterCallbackAsaas()
    client, db = _client(app, planos=[_plano()], asaas=asaas)
    asaas.db = db

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    tracked = next(o for o in db.added if isinstance(o, Subscription))
    assert tracked.status == "ativa"
    assert resp.json()["status"] == "ativa"


class _SetupConfirmedAfterCallbackAsaas:
    """Simula confirmação do setup por retry concorrente antes do retorno."""

    def __init__(self) -> None:
        self.db = None

    def create_checkout(self, **kwargs):
        kwargs["on_subscription_created"]("cus_1", "sub_1")
        tracked = next(o for o in self.db.added if isinstance(o, Subscription))
        tracked.setup_pago = True
        tracked.asaas_setup_charge_id = "pay_setup_concurrent"
        tracked.asaas_setup_invoice_url = None
        return CheckoutResult(
            customer_id="cus_1",
            subscription_id="sub_1",
            invoice_url="https://asaas.test/m1",
            status="pendente",
            invoice_payment_id="pay_m1",
        )

    def create_one_time_charge(self, **kwargs):  # pragma: no cover - defesa
        raise AssertionError("setup já confirmado não pode emitir outra cobrança")


def test_checkout_finalization_preserves_concurrent_setup_confirmation(app) -> None:
    asaas = _SetupConfirmedAfterCallbackAsaas()
    client, db = _client(
        app, planos=[_plano()], asaas=asaas, setup_fee_default=59.9
    )
    asaas.db = db

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    tracked = next(o for o in db.added if isinstance(o, Subscription))
    assert tracked.setup_pago is True
    assert tracked.asaas_setup_charge_id == "pay_setup_concurrent"
    assert resp.json()["setupInvoiceUrl"] is None


class _ReversalAfterCallbackAsaas:
    """Simula delete/refund entre a callback e a persistência final."""

    def __init__(self) -> None:
        self.db = None

    def create_checkout(self, **kwargs):
        kwargs["on_subscription_created"]("cus_1", "sub_1")
        tracked = next(o for o in self.db.added if isinstance(o, Subscription))
        tracked.status = "inadimplente"
        tracked.asaas_invoice_payment_id = "pay_m1"
        tracked.asaas_invoice_url = "https://asaas.test/m1-deleted"
        tracked.asaas_invoice_reversal = "deleted"
        return CheckoutResult(
            customer_id="cus_1",
            subscription_id="sub_1",
            invoice_url="https://asaas.test/m1-stale",
            status="pendente",
            invoice_payment_id="pay_m1",
        )


def test_checkout_result_preserves_reversal_after_creation_callback(app) -> None:
    asaas = _ReversalAfterCallbackAsaas()
    client, db = _client(app, planos=[_plano()], asaas=asaas)
    asaas.db = db

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    tracked = next(o for o in db.added if isinstance(o, Subscription))
    assert tracked.status == "inadimplente"
    assert tracked.asaas_invoice_payment_id == "pay_m1"
    assert tracked.asaas_invoice_url == "https://asaas.test/m1-deleted"
    assert tracked.asaas_invoice_reversal == "deleted"
    assert resp.json()["invoiceUrl"] is None


def test_retry_resumes_pending_checkout_without_new_subscription(app) -> None:
    # Retry do MESMO plano com assinatura já vinculada: recupera fatura e cria
    # só a cobrança de setup que faltava — nenhum novo POST /subscriptions.
    asaas = _ResumeAsaas(
        payment={
            "id": "pay_m1",
            "invoiceUrl": "https://asaas.test/m1",
            "dueDate": "2026-07-31",
        },
        charge={"id": "pay_setup_9", "invoiceUrl": "https://asaas.test/setup9"},
    )
    sub = _subscription(
        status="pendente",
        setup_pago=False,
        asaas_setup_charge_id=None,
        asaas_setup_invoice_url=None,
        asaas_invoice_payment_id=None,
        asaas_invoice_url=None,
    )
    client, db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        setup_fee_default=59.9,
        subscription=sub,
    )

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "status": "pendente",
        "invoiceUrl": "https://asaas.test/m1",
        "setupInvoiceUrl": "https://asaas.test/setup9",
        "asaasSubscriptionId": "sub_asaas_1",
    }
    assert asaas.calls == [
        ("get_subscription_payment", "sub_asaas_1"),
        ("create_one_time_charge", "cus_1"),
    ]
    assert sub.asaas_invoice_payment_id == "pay_m1"
    assert sub.asaas_setup_charge_id == "pay_setup_9"
    assert db.commits >= 1


def test_retry_does_not_duplicate_existing_setup_charge(app) -> None:
    asaas = _ResumeAsaas(
        payment={"id": "pay_m1", "invoiceUrl": "https://asaas.test/m1"}
    )
    sub = _subscription(
        status="pendente",
        setup_pago=False,
        asaas_setup_charge_id="pay_setup_1",  # já rastreada
        asaas_setup_invoice_url="https://asaas.test/setup",
    )
    client, _db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        setup_fee_default=59.9,
        subscription=sub,
    )

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    # Só a leitura da fatura — nenhuma segunda cobrança de setup.
    assert asaas.calls == [("get_subscription_payment", "sub_asaas_1")]
    assert sub.asaas_setup_charge_id == "pay_setup_1"


def test_retry_reconciles_a_tracked_setup_paid_without_webhook(app) -> None:
    op = BillingPaymentOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        purpose="setup",
        operation_key="pastorai-setup-tracked-paid",
        status="created",
        valor=59.9,
        asaas_payment_id="pay_setup_1",
        invoice_url="https://asaas.test/setup",
    )
    asaas = _ResumeAsaas(
        payment={"id": "pay_m1", "invoiceUrl": "https://asaas.test/m1"},
        exact_payment={
            "id": "pay_setup_1",
            "status": "CONFIRMED",
            "value": 59.9,
        },
    )
    sub = _subscription(
        setup_pago=False,
        asaas_setup_charge_id="pay_setup_1",
        asaas_setup_invoice_url="https://asaas.test/setup",
    )
    client, _db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        setup_fee_default=59.9,
        subscription=sub,
        operations=[op],
    )

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert op.status == "paid"
    assert sub.setup_pago is True
    assert sub.asaas_setup_invoice_url is None
    assert asaas.calls == [
        ("get_subscription_payment", "sub_asaas_1"),
        ("get_payment", "pay_setup_1"),
    ]


def test_retry_reconciles_a_tracked_setup_reversed_without_webhook(app) -> None:
    op = BillingPaymentOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        purpose="setup",
        operation_key="pastorai-setup-tracked-reversed",
        status="created",
        valor=59.9,
        asaas_payment_id="pay_setup_1",
        invoice_url="https://asaas.test/setup",
    )
    asaas = _ResumeAsaas(
        payment={"id": "pay_m1", "invoiceUrl": "https://asaas.test/m1"},
        exact_payment={
            "id": "pay_setup_1",
            "status": "REFUNDED",
            "value": 59.9,
        },
    )
    sub = _subscription(
        setup_pago=True,
        asaas_setup_charge_id="pay_setup_1",
        asaas_setup_invoice_url="https://asaas.test/setup",
    )
    client, _db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        setup_fee_default=59.9,
        subscription=sub,
        operations=[op],
    )

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert op.status == "reversed"
    assert sub.setup_pago is False
    assert sub.asaas_setup_charge_id is None
    assert sub.asaas_setup_invoice_url is None
    assert asaas.calls == [
        ("get_subscription_payment", "sub_asaas_1"),
        ("get_payment", "pay_setup_1"),
    ]


def test_paid_setup_retry_preserves_fee_if_refund_wins_during_monthly_lookup(
    app,
) -> None:
    old_setup = BillingPaymentOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        purpose="setup",
        operation_key="pastorai-setup-paid-before-race",
        status="paid",
        valor=59.9,
        asaas_payment_id="pay_setup_old",
        invoice_url=None,
    )
    asaas = _ResumeAsaas(
        payment={
            "id": "pay_m1",
            "status": "PENDING",
            "invoiceUrl": "https://asaas.test/m1",
        },
        charge={
            "id": "pay_setup_new",
            "invoiceUrl": "https://asaas.test/setup-new",
        },
    )
    sub = _subscription(
        status="pendente",
        setup_pago=True,
        setup_fee_contracted=59.9,
        asaas_setup_charge_id="pay_setup_old",
        asaas_setup_invoice_url=None,
        asaas_invoice_payment_id="pay_m1",
        asaas_invoice_url="https://asaas.test/m1",
    )
    client, db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        setup_fee_default=0.0,
        subscription=sub,
        operations=[old_setup],
    )

    def refund_won(obj, with_for_update) -> None:
        if obj is sub:
            old_setup.status = "reversed"
            sub.setup_pago = False
            sub.asaas_setup_charge_id = None
            sub.asaas_setup_invoice_url = None

    db.refresh_callback = refund_won
    resp = client.post(
        "/subscription", json={"plano": "ate_100"}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert ("create_one_time_charge", "cus_1") in asaas.calls
    replacement = next(
        op
        for op in db.added
        if isinstance(op, BillingPaymentOperation) and op is not old_setup
    )
    assert float(replacement.valor) == 59.9
    assert replacement.status == "created"
    assert replacement.asaas_payment_id == "pay_setup_new"
    assert sub.setup_pago is False
    assert sub.asaas_setup_charge_id == "pay_setup_new"
    assert sub.asaas_setup_invoice_url == "https://asaas.test/setup-new"


def test_retry_selects_current_payment_and_applies_confirmation(app) -> None:
    asaas = _ResumeAsaas(
        payment={
            "id": "pay_current",
            "invoiceUrl": "https://asaas.test/current",
            "dueDate": "2026-08-31",
            "status": "CONFIRMED",
        },
    )
    sub = _subscription(
        status="pendente",
        setup_pago=True,
        asaas_invoice_payment_id="pay_current",
        asaas_invoice_url=None,
    )
    client, db = _client(app, planos=[_plano()], asaas=asaas, subscription=sub)
    db.igreja.status = "inadimplente"

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "ativa"
    assert resp.json()["invoiceUrl"] == "https://asaas.test/current"
    assert asaas.calls == [("get_subscription_payment", "sub_asaas_1")]
    assert sub.status == "ativa"
    assert sub.proxima_cobranca == dt.date(2026, 8, 31)
    assert db.igreja.status == "ativa"


def test_retry_applies_current_overdue_status_and_closes_gate(app) -> None:
    asaas = _ResumeAsaas(
        payment={
            "id": "pay_current",
            "invoiceUrl": "https://asaas.test/current",
            "dueDate": "2026-08-31",
            "status": "OVERDUE",
        }
    )
    sub = _subscription(
        status="pendente",
        setup_pago=True,
        asaas_invoice_payment_id="pay_current",
    )
    client, db = _client(app, planos=[_plano()], asaas=asaas, subscription=sub)

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "inadimplente"
    assert sub.status == "inadimplente"
    assert db.igreja.status == "inadimplente"


def test_retry_never_regresses_a_concurrent_confirmation_to_pending(app) -> None:
    asaas = _ResumeAsaas(
        payment={
            "id": "pay_current",
            "invoiceUrl": "https://asaas.test/current",
            "dueDate": "2026-08-31",
            "status": "PENDING",
        }
    )
    sub = _subscription(
        status="pendente",
        setup_pago=True,
        asaas_invoice_payment_id="pay_current",
    )
    client, db = _client(app, planos=[_plano()], asaas=asaas, subscription=sub)

    def _concurrent_webhook_snapshot(obj, with_for_update) -> None:
        assert with_for_update is True
        obj.status = "ativa"
        obj.asaas_invoice_payment_id = "pay_current"
        db.igreja.status = "ativa"

    db.refresh_callback = _concurrent_webhook_snapshot

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "ativa"
    assert sub.status == "ativa"
    assert db.igreja.status == "ativa"
    assert db.refresh_calls == [(sub, True)]


def test_retry_still_adopts_pending_snapshot_from_a_new_billing_cycle(app) -> None:
    asaas = _ResumeAsaas(
        payment={
            "id": "pay_august",
            "invoiceUrl": "https://asaas.test/august",
            "dueDate": "2026-08-31",
            "status": "PENDING",
        }
    )
    sub = _subscription(
        status="ativa",
        setup_pago=True,
        asaas_invoice_payment_id="pay_july",
        asaas_invoice_url="https://asaas.test/july",
        proxima_cobranca=dt.date(2026, 7, 31),
    )
    client, db = _client(app, planos=[_plano()], asaas=asaas, subscription=sub)

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "pendente"
    assert sub.status == "pendente"
    assert sub.asaas_invoice_payment_id == "pay_august"
    assert sub.asaas_invoice_url == "https://asaas.test/august"
    assert db.igreja.status == "ativa"  # PENDING não é inadimplência


def test_tracked_subscription_requires_change_plan_instead_of_second_checkout(
    app,
) -> None:
    # Uma recorrência rastreada nunca pode gerar outro POST. Plano diferente
    # deve seguir a troca in-place da assinatura existente.
    asaas = _FakeAsaas()
    sub = _subscription(status="pendente", plano="ate_100")
    client, db = _client(
        app,
        planos=[_plano(codigo="101_200", preco_mensal=299, limite_pessoas=200)],
        asaas=asaas,
        subscription=sub,
    )

    resp = client.post(
        "/subscription", json={"plano": "101_200", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 409
    assert "troca de plano" in resp.json()["detail"]
    assert asaas.calls == []
    assert not [
        op for op in db.added if isinstance(op, BillingSubscriptionOperation)
    ]
    assert sub.plano == "ate_100"


def test_get_subscription_withholds_reversed_invoice_link(app) -> None:
    # Cobrança mensal estornada/excluída: o GET não expõe o link dela,
    # mas ainda consulta o payment autoritativo para detectar uma mudança real.
    asaas = _RecoveryAsaas(payment_urls={"pay_m2": "https://asaas.test/m2"})
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
        asaas_invoice_reversal="refunded",
    )
    client, db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["invoiceUrl"] is None
    assert body["invoiceReversal"] == "refunded"  # a UI decide a ação por aqui
    assert asaas.calls == [("get_payment", "pay_m2")]
    assert db.commits == 0


class _RestoreAsaas:
    """Fake do fluxo deleted→restore: consulta, restaura, consulta de novo.

    Criar assinatura ou cobrança aqui explode o teste — a recuperação de uma
    cobrança EXCLUÍDA restaura o MESMO payment id, nada além disso.
    """

    def __init__(self, states: list[dict | None]) -> None:
        self.calls: list[tuple[str, str]] = []
        self._states = list(states)

    def get_payment(self, payment_id: str):
        self.calls.append(("get_payment", payment_id))
        return self._states.pop(0) if self._states else None

    def restore_payment(self, payment_id: str):
        self.calls.append(("restore_payment", payment_id))
        return {"id": payment_id}

    def create_checkout(self, **kwargs):  # pragma: no cover - defesa
        raise AssertionError("recuperação nunca cria assinatura")

    def create_one_time_charge(self, **kwargs):  # pragma: no cover - defesa
        raise AssertionError("deleted restaura o mesmo payment, não cria cobrança")


class _RecoveryChargeAsaas:
    """Fake do fluxo refunded→cobrança avulsa de recuperação (via operação).

    O VALOR da recuperação vem da cobrança rastreada (ou da assinatura) — o
    catálogo do master não participa, então um plano desativado/reprecificado
    nunca muda o que o assinante grandfathered paga.
    """

    def __init__(self, *, payment_value: float | None = 199.0,
                 subscription_value: float | None = None) -> None:
        self.posts = 0
        self.charged_values: list[float] = []
        self._payment_value = payment_value
        self._subscription_value = subscription_value

    def get_payment(self, payment_id: str):
        if payment_id == "pay_rec_1":
            return {
                "id": payment_id,
                "value": self._payment_value,
                "status": "PENDING",
                "invoiceUrl": "https://asaas.test/recovery",
            }
        if self._payment_value is None:
            return None
        return {"id": payment_id, "value": self._payment_value, "status": "REFUNDED"}

    def get_subscription(self, subscription_id: str):
        if self._subscription_value is None:
            return None
        return {"id": subscription_id, "value": self._subscription_value}

    def create_checkout(self, **kwargs):  # pragma: no cover - defesa
        raise AssertionError("recuperação nunca cria assinatura")

    def create_one_time_charge(self, **kwargs):
        self.posts += 1
        self.charged_values.append(kwargs["valor"])
        assert kwargs["external_reference"].startswith("pastorai-monthly_recovery-")
        return {"id": "pay_rec_1", "invoiceUrl": "https://asaas.test/recovery"}


def test_recover_invoice_deleted_restores_same_payment(app) -> None:
    asaas = _RestoreAsaas(
        states=[
            {"id": "pay_m2", "deleted": True},
            {
                "id": "pay_m2",
                "deleted": False,
                "status": "PENDING",
                "invoiceUrl": "https://asaas.test/m2-restored",
            },
        ]
    )
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
        asaas_invoice_reversal="deleted",
    )
    staged = BillingPaymentOperation(
        subscription_id=sub.id,
        purpose="monthly_recovery",
        operation_key="pastorai-monthly_recovery-deleted-m2",
        source_payment_id="pay_m2",
        status="prepared",
        valor=199.0,
    )
    client, _db = _client(
        app,
        planos=[],
        asaas=asaas,
        subscription=sub,
        operations=[staged],
    )

    resp = client.post("/subscription/recover-invoice", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["invoiceUrl"] == "https://asaas.test/m2-restored"
    # Consulta ANTES de restaurar (restore não é tratado como idempotente) e
    # consulta de novo depois; restaura o MESMO payment id.
    assert asaas.calls == [
        ("get_payment", "pay_m2"),
        ("restore_payment", "pay_m2"),
        ("get_payment", "pay_m2"),
    ]
    assert sub.asaas_invoice_url == "https://asaas.test/m2-restored"
    assert sub.asaas_invoice_reversal is None
    assert sub.status == "pendente"
    assert staged.status == "created"
    assert staged.asaas_payment_id == "pay_m2"
    assert staged.invoice_url == "https://asaas.test/m2-restored"
    assert staged.error is None


def test_recover_invoice_deleted_already_restored_skips_restore(app) -> None:
    # O Asaas já mostra a cobrança viva (ex.: restaurada por retry anterior):
    # nenhum restore repetido.
    asaas = _RestoreAsaas(
        states=[
            {
                "id": "pay_m2",
                "deleted": False,
                "status": "PENDING",
                "invoiceUrl": "https://asaas.test/m2-alive",
            }
        ]
    )
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
        asaas_invoice_reversal="deleted",
    )
    client, _db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.post("/subscription/recover-invoice", headers=_AUTH)

    assert resp.status_code == 200
    assert asaas.calls == [("get_payment", "pay_m2")]  # zero restore repetido
    assert sub.asaas_invoice_url == "https://asaas.test/m2-alive"


def test_recover_deleted_preserves_refund_seen_after_restore(app) -> None:
    asaas = _RestoreAsaas(
        states=[
            {"id": "pay_m2", "deleted": True},
            {
                "id": "pay_m2",
                "deleted": False,
                "status": "REFUNDED",
                "invoiceUrl": "https://asaas.test/m2-dead",
                "value": 199.0,
            },
        ]
    )
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
        asaas_invoice_reversal="deleted",
    )
    staged = BillingPaymentOperation(
        subscription_id=sub.id,
        purpose="monthly_recovery",
        operation_key="pastorai-monthly-recovery-refund-after-restore",
        source_payment_id="pay_m2",
        status="prepared",
        valor=199.0,
    )
    client, db = _client(
        app,
        planos=[],
        asaas=asaas,
        subscription=sub,
        operations=[staged],
        igreja_status="inadimplente",
    )

    resp = client.post("/subscription/recover-invoice", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["status"] == "inadimplente"
    assert resp.json()["invoiceUrl"] is None
    assert sub.asaas_invoice_reversal == "refunded"
    assert sub.asaas_invoice_url is None
    assert staged.status == "prepared"
    assert staged.error is None
    assert db.igreja.status == "inadimplente"
    assert asaas.calls == [
        ("get_payment", "pay_m2"),
        ("restore_payment", "pay_m2"),
        ("get_payment", "pay_m2"),
    ]


def test_recover_deleted_does_not_overwrite_a_newer_billing_cycle(app) -> None:
    asaas = _RestoreAsaas(
        states=[
            {"id": "pay_a", "deleted": True},
            {
                "id": "pay_a",
                "deleted": False,
                "status": "PENDING",
                "invoiceUrl": "https://asaas.test/a-restored",
            },
        ]
    )
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_invoice_payment_id="pay_a",
        asaas_invoice_url=None,
        asaas_invoice_reversal="deleted",
    )
    staged = BillingPaymentOperation(
        subscription_id=sub.id,
        purpose="monthly_recovery",
        operation_key="pastorai-monthly_recovery-a-race",
        source_payment_id="pay_a",
        status="prepared",
        valor=199.0,
    )
    client, db = _client(
        app,
        planos=[],
        asaas=asaas,
        subscription=sub,
        operations=[staged],
        igreja_status="inadimplente",
    )

    def cycle_b_won(obj, with_for_update) -> None:
        if obj is sub:
            sub.status = "ativa"
            sub.asaas_invoice_payment_id = "pay_b"
            sub.asaas_invoice_url = "https://asaas.test/b"
            sub.asaas_invoice_reversal = None

    db.refresh_callback = cycle_b_won
    resp = client.post("/subscription/recover-invoice", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["invoiceUrl"] == "https://asaas.test/b"
    assert sub.status == "ativa"
    assert sub.asaas_invoice_payment_id == "pay_b"
    assert sub.asaas_invoice_url == "https://asaas.test/b"
    assert sub.asaas_invoice_reversal is None
    # A restauração de A é real mesmo após o avanço para B, mas PENDING ainda
    # é dívida: a operação fica aberta e seu link continua visível sem tocar B.
    assert staged.status == "created"
    assert staged.asaas_payment_id == "pay_a"
    assert staged.error is None
    assert staged.invoice_url == "https://asaas.test/a-restored"
    view = client.get("/subscription", headers=_AUTH)
    assert view.status_code == 200
    # B já está ativa; a visão pública não oferece novamente sua fatura paga.
    assert view.json()["invoiceUrl"] is None
    assert view.json()["recoveryInvoiceUrl"] == "https://asaas.test/a-restored"
    assert view.json()["recoveryRequired"] is True
    assert db.igreja.status == "inadimplente"
    assert db.refresh_calls[:2] == [(staged, True), (sub, True)]
    assert db.commits == 1


def test_recover_deleted_confirmed_reopens_the_church_gate(app) -> None:
    asaas = _RestoreAsaas(
        states=[
            {"id": "pay_m2", "deleted": True},
            {
                "id": "pay_m2",
                "deleted": False,
                "status": "CONFIRMED",
                "invoiceUrl": "https://asaas.test/m2-paid",
            },
        ]
    )
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
        asaas_invoice_reversal="deleted",
    )
    staged = BillingPaymentOperation(
        subscription_id=sub.id,
        purpose="monthly_recovery",
        operation_key="pastorai-monthly-recovery-confirmed-restore",
        source_payment_id="pay_m2",
        status="prepared",
        valor=199.0,
    )
    client, db = _client(
        app, planos=[], asaas=asaas, subscription=sub, operations=[staged]
    )
    db.igreja.status = "inadimplente"

    resp = client.post("/subscription/recover-invoice", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["status"] == "ativa"
    assert sub.status == "ativa"
    assert sub.asaas_invoice_reversal is None
    assert staged.status == "paid"
    assert staged.asaas_payment_id == "pay_m2"
    assert db.flushes == 1
    assert db.igreja.status == "ativa"


def test_recover_deleted_confirmed_old_cycle_reopens_gate_without_overwriting_b(
    app,
) -> None:
    asaas = _RestoreAsaas(
        states=[
            {"id": "pay_a", "deleted": True},
            {
                "id": "pay_a",
                "deleted": False,
                "status": "CONFIRMED",
                "invoiceUrl": "https://asaas.test/a-paid",
            },
        ]
    )
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_invoice_payment_id="pay_a",
        asaas_invoice_url=None,
        asaas_invoice_reversal="deleted",
    )
    staged = BillingPaymentOperation(
        subscription_id=sub.id,
        purpose="monthly_recovery",
        operation_key="pastorai-monthly-recovery-a-confirmed-race",
        source_payment_id="pay_a",
        status="prepared",
        valor=199.0,
    )
    client, db = _client(
        app,
        planos=[],
        asaas=asaas,
        subscription=sub,
        operations=[staged],
        igreja_status="inadimplente",
    )

    def cycle_b_won(obj, with_for_update) -> None:
        if obj is sub:
            sub.status = "pendente"
            sub.asaas_invoice_payment_id = "pay_b"
            sub.asaas_invoice_url = "https://asaas.test/b"
            sub.asaas_invoice_reversal = None

    db.refresh_callback = cycle_b_won
    resp = client.post("/subscription/recover-invoice", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["status"] == "pendente"
    assert resp.json()["invoiceUrl"] == "https://asaas.test/b"
    assert resp.json()["recoveryInvoiceUrl"] is None
    assert sub.status == "pendente"
    assert sub.asaas_invoice_payment_id == "pay_b"
    assert sub.asaas_invoice_url == "https://asaas.test/b"
    assert staged.status == "paid"
    assert staged.asaas_payment_id == "pay_a"
    assert staged.invoice_url == "https://asaas.test/a-paid"
    assert db.igreja.status == "ativa"


def test_recover_invoice_refunded_emits_recovery_charge_once(app) -> None:
    asaas = _RecoveryChargeAsaas()
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
        asaas_invoice_reversal="refunded",
    )
    client, db = _client(app, planos=[_plano()], asaas=asaas, subscription=sub)

    first = client.post("/subscription/recover-invoice", headers=_AUTH)
    retry = client.post("/subscription/recover-invoice", headers=_AUTH)

    assert first.status_code == 200
    assert first.json()["recoveryInvoiceUrl"] == "https://asaas.test/recovery"
    assert retry.status_code == 200
    assert retry.json()["recoveryInvoiceUrl"] == "https://asaas.test/recovery"
    # Retry reusa a operação criada — exatamente UMA cobrança de recuperação,
    # e nenhuma assinatura nova (o fake explode se create_checkout rodar).
    assert asaas.posts == 1
    ops = [o for o in db.added if getattr(o, "purpose", None) == "monthly_recovery"]
    assert len(ops) == 1
    assert ops[0].valor == 199.0  # preço do plano atual do catálogo


def test_recover_invoice_rechecks_a_concurrent_settlement_before_post(app) -> None:
    asaas = _RecoveryChargeAsaas()
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_reversal="refunded",
    )
    open_recovery = BillingPaymentOperation(
        subscription_id=sub.id,
        purpose="monthly_recovery",
        operation_key="pastorai-monthly_recovery-race-paid",
        source_payment_id="pay_m2",
        status="prepared",
        valor=199.0,
    )
    client, db = _client(
        app,
        planos=[],
        asaas=asaas,
        subscription=sub,
        operations=[open_recovery],
        igreja_status="inadimplente",
    )

    def webhook_won(obj, with_for_update) -> None:
        if obj is open_recovery:
            open_recovery.status = "paid"
            sub.status = "ativa"
            sub.asaas_invoice_reversal = None

    db.refresh_callback = webhook_won
    resp = client.post("/subscription/recover-invoice", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["status"] == "ativa"
    assert asaas.posts == 0
    assert db.refresh_calls[:2] == [(open_recovery, True), (sub, True)]
    assert not [
        obj
        for obj in db.added
        if getattr(obj, "purpose", None) == "monthly_recovery"
    ]


def test_delinquent_owner_can_load_billing_screen_for_recovery(app) -> None:
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id=None,
        asaas_invoice_url="https://asaas.test/m2",
        asaas_invoice_reversal=None,
    )
    client, _db = _client(
        app,
        planos=[_plano()],
        subscription=sub,
        igreja_status="inadimplente",
    )

    subscription = client.get("/subscription", headers=_AUTH)
    catalog = client.get("/subscription/planos", headers=_AUTH)

    assert subscription.status_code == 200
    assert subscription.json()["invoiceUrl"] == "https://asaas.test/m2"
    assert catalog.status_code == 200
    assert catalog.json()["planos"][0]["codigo"] == "ate_100"


def test_delinquent_owner_can_resume_only_the_tracked_subscription(app) -> None:
    asaas = _ResumeAsaas(
        payment={
            "id": "pay_m2",
            "status": "PENDING",
            "invoiceUrl": "https://asaas.test/m2-recovered",
        }
    )
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
        asaas_invoice_reversal=None,
    )
    client, _db = _client(
        app,
        planos=[],
        asaas=asaas,
        subscription=sub,
        igreja_status="inadimplente",
    )

    resp = client.post("/subscription/resume", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["invoiceUrl"] == "https://asaas.test/m2-recovered"
    assert asaas.calls == [
        ("get_subscription_payment", "sub_asaas_1"),
    ]


def test_delinquent_resume_never_creates_an_untracked_subscription(app) -> None:
    asaas = _ResumeAsaas()
    sub = _subscription(
        status="inadimplente",
        asaas_subscription_id=None,
        asaas_invoice_payment_id=None,
    )
    client, _db = _client(
        app,
        planos=[],
        asaas=asaas,
        subscription=sub,
        igreja_status="inadimplente",
    )

    resp = client.post("/subscription/resume", headers=_AUTH)

    assert resp.status_code == 409
    assert asaas.calls == []


def test_recover_invoice_of_new_cycle_is_not_blocked_by_an_older_recovery(
    app,
) -> None:
    # REVIEW-10 P1: a recovery órfã do ciclo A não pode ocupar o slot e impedir
    # a recuperação do ciclo B — a cobrança-fonte faz parte da identidade do
    # claim, então B nasce como operação própria.
    from app.db.models import BillingPaymentOperation

    recovery_a = BillingPaymentOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        purpose="monthly_recovery",
        operation_key="pastorai-monthly_recovery-a",
        status="created",
        valor=199.0,
        source_payment_id="pay_m1",  # ciclo ANTIGO, ainda aberto
        asaas_payment_id="pay_rec_a",
        invoice_url="https://asaas.test/recovery-a",
    )
    asaas = _RecoveryChargeAsaas()
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m2",  # ciclo CORRENTE
        asaas_invoice_url=None,
        asaas_invoice_reversal="refunded",
    )
    client, db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        subscription=sub,
        operations=[recovery_a],
    )

    resp = client.post("/subscription/recover-invoice", headers=_AUTH)

    assert resp.status_code == 200
    assert asaas.posts == 1  # a recuperação de B foi emitida
    criadas = [
        o for o in db.added if getattr(o, "purpose", None) == "monthly_recovery"
    ]
    assert len(criadas) == 1
    assert criadas[0].source_payment_id == "pay_m2"  # amarrada à fonte corrente
    assert recovery_a.status == "created"  # a operação antiga fica intacta


def test_recover_invoice_rejects_when_not_reversed(app) -> None:
    sub = _subscription(status="pendente", asaas_invoice_reversal=None)
    client, _db = _client(app, planos=[], asaas=_RecoveryChargeAsaas(), subscription=sub)

    resp = client.post("/subscription/recover-invoice", headers=_AUTH)

    assert resp.status_code == 422


def test_recover_invoice_materializes_reopened_debt_from_an_older_cycle(app) -> None:
    from app.db.models import BillingPaymentOperation

    reopened = BillingPaymentOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        purpose="monthly_recovery",
        operation_key="pastorai-monthly_recovery-reopened-a",
        status="prepared",
        valor=149.0,
        source_payment_id="pay_m1",
    )
    sub = _subscription(
        status="ativa",
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_reversal=None,
    )
    asaas = _RecoveryChargeAsaas()
    client, _db = _client(
        app,
        planos=[],
        asaas=asaas,
        subscription=sub,
        operations=[reopened],
    )

    resp = client.post("/subscription/recover-invoice", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["recoveryInvoiceUrl"] == "https://asaas.test/recovery"
    assert asaas.posts == 1
    assert reopened.source_payment_id == "pay_m1"
    assert float(reopened.valor) == 149.0


def test_setup_charge_action_emits_via_operation_once(app) -> None:
    # Setup revertido de assinante ativo: a ação explícita reemite a taxa como
    # cobrança avulsa — nunca passa pelo checkout nem cria assinatura.
    asaas = _FakeAsaas()
    sub = _subscription(
        status="ativa",
        setup_pago=False,
        asaas_setup_charge_id=None,
        asaas_setup_invoice_url=None,
    )
    client, db = _client(
        app,
        planos=[],
        asaas=asaas,
        setup_fee_default=59.9,
        subscription=sub,
    )

    first = client.post("/subscription/setup-charge", headers=_AUTH)
    retry = client.post("/subscription/setup-charge", headers=_AUTH)

    assert first.status_code == 200
    assert first.json()["setupInvoiceUrl"] == "https://asaas.test/setup"
    assert retry.status_code == 200
    assert asaas.calls == []  # jamais create_checkout
    assert len(asaas.charge_calls) == 1  # uma única cobrança emitida
    assert sub.asaas_setup_charge_id == "pay_setup_1"
    assert sub.setup_pago is False
    ops = [o for o in db.added if getattr(o, "purpose", None) == "setup"]
    assert len(ops) == 1


def test_setup_charge_rechecks_concurrent_confirmation_before_reissue(app) -> None:
    asaas = _FakeAsaas()
    sub = _subscription(
        status="ativa",
        setup_pago=False,
        asaas_setup_charge_id="pay_setup_race",
        asaas_setup_invoice_url=None,
    )
    operation = BillingPaymentOperation(
        subscription_id=sub.id,
        purpose="setup",
        operation_key="pastorai-setup-race-confirmed",
        source_payment_id=None,
        asaas_payment_id="pay_setup_race",
        status="created",
        valor=59.9,
    )
    client, db = _client(
        app,
        planos=[],
        asaas=asaas,
        setup_fee_default=59.9,
        subscription=sub,
        operations=[operation],
    )

    def webhook_won(obj, with_for_update) -> None:
        if obj is sub:
            operation.status = "paid"
            sub.setup_pago = True

    db.refresh_callback = webhook_won
    resp = client.post("/subscription/setup-charge", headers=_AUTH)

    assert resp.status_code == 422
    assert "quitada" in resp.json()["detail"]
    assert asaas.charge_calls == []
    assert sub.asaas_setup_charge_id == "pay_setup_race"
    assert db.refresh_calls == [(sub, True)]


def test_setup_reissue_uses_reversed_operation_amount_not_current_fee(app) -> None:
    # Contrato nasceu em 59,90; depois o master isentou novas contratações.
    # Reemitir a cobrança revertida não pode perdoar nem reprecificar a dívida.
    reversed_setup = BillingPaymentOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        purpose="setup",
        operation_key="pastorai-setup-original",
        status="reversed",
        valor=59.9,
        asaas_payment_id="pay_setup_old",
    )
    asaas = _FakeAsaas()
    sub = _subscription(
        status="ativa",
        setup_pago=False,
        asaas_setup_charge_id=None,
        asaas_setup_invoice_url=None,
    )
    client, _db = _client(
        app,
        planos=[],
        asaas=asaas,
        setup_fee_default=0.0,
        subscription=sub,
        operations=[reversed_setup],
    )

    resp = client.post("/subscription/setup-charge", headers=_AUTH)

    assert resp.status_code == 200
    assert len(asaas.charge_calls) == 1
    assert asaas.charge_calls[0]["valor"] == 59.9
    assert sub.setup_pago is False


def test_setup_reissue_without_operation_uses_contracted_fee_not_current_fee(app) -> None:
    # Crash/rejeição depois de congelar o contrato, antes de criar a operação:
    # a configuração de novas vendas mudou, mas esta obrigação continua 59,90.
    asaas = _FakeAsaas()
    sub = _subscription(
        status="ativa",
        setup_pago=False,
        setup_fee_contracted=59.9,
        asaas_setup_charge_id=None,
        asaas_setup_invoice_url=None,
    )
    client, _db = _client(
        app,
        planos=[],
        asaas=asaas,
        setup_fee_default=0.0,
        subscription=sub,
        operations=[],
    )

    resp = client.post("/subscription/setup-charge", headers=_AUTH)

    assert resp.status_code == 200
    assert len(asaas.charge_calls) == 1
    assert asaas.charge_calls[0]["valor"] == 59.9
    assert sub.setup_pago is False


def test_setup_charge_action_rejects_when_already_paid(app) -> None:
    sub = _subscription(status="ativa", setup_pago=True)
    client, _db = _client(app, planos=[], asaas=_FakeAsaas(), subscription=sub)

    resp = client.post("/subscription/setup-charge", headers=_AUTH)

    assert resp.status_code == 422


def test_get_subscription_exposes_recovery_url_and_setup_flag(app) -> None:
    from app.db.models import BillingPaymentOperation

    recovery_op = BillingPaymentOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        purpose="monthly_recovery",
        operation_key="pastorai-monthly_recovery-x",
        status="created",
        valor=199.0,
        # A recuperação existe para quitar UMA mensalidade: a fonte é parte da
        # identidade dela, e só a fonte CORRENTE pode ser exposta.
        source_payment_id="pay_m2",
        asaas_payment_id="pay_rec_1",
        invoice_url="https://asaas.test/recovery",
    )
    sub = _subscription(
        status="inadimplente",
        setup_pago=False,
        asaas_setup_charge_id=None,
        asaas_setup_invoice_url=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
        asaas_invoice_reversal="refunded",
    )
    client, _db = _client(
        app,
        planos=[],
        asaas=_RecoveryAsaas(),
        subscription=sub,
        operations=[recovery_op],
    )

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["recoveryInvoiceUrl"] == "https://asaas.test/recovery"
    assert body["recoveryRequired"] is True
    assert body["invoiceReversal"] == "refunded"
    # Setup devido, sem link pagável e com assinatura criada => a UI oferece
    # "Gerar nova taxa de setup".
    assert body["setupRecoveryRequired"] is True


def test_get_subscription_reconciles_confirmed_open_recovery(app) -> None:
    recovery_op = BillingPaymentOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        purpose="monthly_recovery",
        operation_key="pastorai-monthly_recovery-confirmed",
        status="created",
        valor=199.0,
        source_payment_id="pay_m2",
        asaas_payment_id="pay_rec_1",
        invoice_url="https://asaas.test/recovery",
    )
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
        asaas_invoice_reversal="refunded",
    )
    asaas = _RecoveryAsaas(
        payment_payloads={
            "pay_rec_1": {
                "id": "pay_rec_1",
                "status": "CONFIRMED",
                "invoiceUrl": "https://asaas.test/recovery",
            }
        }
    )
    client, db = _client(
        app,
        planos=[],
        asaas=asaas,
        subscription=sub,
        operations=[recovery_op],
        igreja_status="inadimplente",
    )

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ativa"
    assert body["invoiceReversal"] is None
    assert body["recoveryRequired"] is False
    assert body["recoveryInvoiceUrl"] is None
    assert recovery_op.status == "paid"
    assert db.igreja.status == "ativa"
    assert asaas.calls == [
        ("get_payment", "pay_m2"),
        ("get_payment", "pay_rec_1"),
    ]


@pytest.mark.parametrize(
    "remote_payload",
    [
        {"id": "pay_rec_1", "status": "REFUNDED"},
        {"id": "pay_rec_1", "status": "PENDING", "deleted": True},
    ],
)
def test_get_subscription_reconciles_reversed_open_recovery(
    app, remote_payload
) -> None:
    recovery_op = BillingPaymentOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        purpose="monthly_recovery",
        operation_key="pastorai-monthly_recovery-reversed",
        status="created",
        valor=199.0,
        source_payment_id="pay_m2",
        asaas_payment_id="pay_rec_1",
        invoice_url="https://asaas.test/recovery-dead",
    )
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url=None,
        asaas_invoice_reversal="refunded",
    )
    asaas = _RecoveryAsaas(
        payment_payloads={"pay_rec_1": remote_payload}
    )
    client, db = _client(
        app,
        planos=[],
        asaas=asaas,
        subscription=sub,
        operations=[recovery_op],
        igreja_status="inadimplente",
    )

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["recoveryRequired"] is True
    assert resp.json()["recoveryInvoiceUrl"] is None
    assert recovery_op.status == "reversed"
    reopened = [
        op
        for op in db.added
        if isinstance(op, BillingPaymentOperation)
        and op.purpose == "monthly_recovery"
    ]
    assert len(reopened) == 1
    assert reopened[0].status == "prepared"
    assert reopened[0].source_payment_id == "pay_m2"
    assert asaas.calls == [
        ("get_payment", "pay_m2"),
        ("get_payment", "pay_rec_1"),
    ]


def test_get_subscription_keeps_older_recovery_visible_as_a_real_debt(app) -> None:
    # A recuperação do ciclo A ficou aberta enquanto a assinatura avançou para
    # B. Ela não quita B, mas continua sendo uma dívida real e uma barreira de
    # acesso; escondê-la tornaria impossível regularizar A. Depois de A paga, a
    # UI passa à pendência corrente de B.
    from app.db.models import BillingPaymentOperation

    recovery_a = BillingPaymentOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        purpose="monthly_recovery",
        operation_key="pastorai-monthly_recovery-a",
        status="created",
        valor=199.0,
        source_payment_id="pay_m1",  # ciclo ANTIGO
        asaas_payment_id="pay_rec_a",
        invoice_url="https://asaas.test/recovery-a",
    )
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_setup_invoice_url=None,
        asaas_invoice_payment_id="pay_m2",  # ciclo CORRENTE, revertido
        asaas_invoice_url=None,
        asaas_invoice_reversal="refunded",
    )
    client, _db = _client(
        app,
        planos=[],
        asaas=_RecoveryAsaas(),
        subscription=sub,
        operations=[recovery_a],
    )

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["recoveryInvoiceUrl"] == "https://asaas.test/recovery-a"
    assert resp.json()["invoiceReversal"] == "refunded"


def test_get_subscription_exposes_reopened_debt_before_it_has_a_link(app) -> None:
    from app.db.models import BillingPaymentOperation

    reopened = BillingPaymentOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        purpose="monthly_recovery",
        operation_key="pastorai-monthly_recovery-reopened-a",
        status="prepared",
        valor=199.0,
        source_payment_id="pay_m1",
        invoice_url=None,
    )
    sub = _subscription(
        status="ativa",
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_reversal=None,
    )
    client, _db = _client(
        app,
        planos=[],
        asaas=_RecoveryAsaas(),
        subscription=sub,
        operations=[reopened],
    )

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["recoveryRequired"] is True
    assert resp.json()["recoveryInvoiceUrl"] is None


@pytest.mark.parametrize("sub_status", [None, "pendente", "ativa", "inadimplente"])
def test_same_plan_any_status_never_posts_subscription(app, sub_status) -> None:
    # INVARIANTE 1: mesmo plano + assinatura Asaas rastreada nunca executa
    # outro POST /subscriptions — _ResumeAsaas explode se create_checkout rodar.
    asaas = _ResumeAsaas(payment={"id": "pay_m1", "invoiceUrl": "https://asaas.test/m1"})
    sub = _subscription(
        status=sub_status,
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_setup_invoice_url=None,
    )
    client, _db = _client(app, planos=[_plano()], asaas=asaas, subscription=sub)

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert asaas.calls[0] == ("get_subscription_payment", "sub_asaas_1")


def test_same_tracked_plan_resumes_without_billing_document(app) -> None:
    asaas = _ResumeAsaas(
        payment={"id": "pay_m2", "invoiceUrl": "https://asaas.test/m2"}
    )
    sub = _subscription(status="inadimplente", setup_pago=True)
    client, _db = _client(app, planos=[_plano()], asaas=asaas, subscription=sub)

    resp = client.post(
        "/subscription", json={"plano": "ate_100"}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert resp.json()["invoiceUrl"] == "https://asaas.test/m2"
    assert asaas.calls[0] == ("get_subscription_payment", "sub_asaas_1")


def test_resume_treats_deleted_flag_as_reversal_even_with_pending_status(app) -> None:
    asaas = _ResumeAsaas(
        payment={
            "id": "pay_m2",
            "status": "PENDING",
            "deleted": True,
            "invoiceUrl": "https://asaas.test/dead",
            "dueDate": "2026-08-10",
            "value": 199.0,
        }
    )
    sub = _subscription(
        status="ativa",
        setup_pago=True,
        asaas_invoice_payment_id="pay_m2",
        asaas_invoice_url="https://asaas.test/dead",
        asaas_invoice_reversal=None,
    )
    client, db = _client(app, planos=[_plano()], asaas=asaas, subscription=sub)

    resp = client.post(
        "/subscription", json={"plano": "ate_100"}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "inadimplente"
    assert resp.json()["invoiceUrl"] is None
    assert sub.status == "inadimplente"
    assert sub.asaas_invoice_reversal == "deleted"
    assert db.igreja.status == "inadimplente"
    recovery = next(
        op for op in db.added if getattr(op, "purpose", None) == "monthly_recovery"
    )
    assert recovery.source_payment_id == "pay_m2"


def test_new_checkout_without_billing_document_is_rejected_before_mutation(app) -> None:
    client, db = _client(app, planos=[_plano()], asaas=_NoCallAsaas())

    resp = client.post(
        "/subscription", json={"plano": "ate_100"}, headers=_AUTH
    )

    assert resp.status_code == 422
    assert "CPF ou CNPJ" in resp.json()["detail"]
    assert not [o for o in db.added if isinstance(o, Subscription)]


class _ChangePlanAsaas:
    """Fake da troca de plano: PUT in-place; criar assinatura explode."""

    def __init__(self, *, error: bool = False) -> None:
        self.puts: list[tuple[str, float, str]] = []
        self._error = error

    def update_subscription(self, subscription_id: str, *, valor: float, descricao: str):
        self.puts.append((subscription_id, valor, descricao))
        if self._error:
            raise AsaasError("Asaas indisponível")
        return {"id": subscription_id, "value": valor}

    def get_subscription(self, subscription_id: str):
        return None

    def create_checkout(self, **kwargs):  # pragma: no cover - defesa
        raise AssertionError("troca de plano nunca cria assinatura")


class _RejectedChangePlanAsaas(_ChangePlanAsaas):
    """Rejeição definitiva depois de o porte crescer durante o PUT."""

    def __init__(self) -> None:
        super().__init__()
        self.db = None

    def update_subscription(self, subscription_id: str, *, valor: float, descricao: str):
        self.puts.append((subscription_id, valor, descricao))
        assert self.db is not None
        self.db.pessoas_count = 250
        raise AsaasRejectedError("Plano rejeitado definitivamente pelo Asaas")


class _SupersededChangePlanAsaas(_ChangePlanAsaas):
    """A resposta do PUT antigo volta após uma troca mais nova concluir."""

    def __init__(self) -> None:
        super().__init__()
        self.db = None
        self.sub = None

    def update_subscription(self, subscription_id: str, *, valor: float, descricao: str):
        self.puts.append((subscription_id, valor, descricao))
        assert self.db is not None and self.sub is not None
        old = next(
            o
            for o in self.db.added
            if isinstance(o, BillingPlanChangeOperation)
        )
        old.status = "completed"  # o worker já fechou o claim antigo
        self.sub.plano = "acima_201"
        self.sub.limite = None
        self.db.igreja.plano = "acima_201"
        return {"id": subscription_id, "value": valor, "description": descricao}


def _active_sub(**over):
    base = dict(
        status="ativa",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_setup_invoice_url=None,
    )
    base.update(over)
    return _subscription(**base)


def test_change_plan_updates_existing_subscription_in_place(app) -> None:
    asaas = _ChangePlanAsaas()
    sub = _active_sub(proxima_cobranca=None)
    client, db = _client(
        app,
        planos=[_plano(codigo="101_200", preco_mensal=299, limite_pessoas=200)],
        asaas=asaas,
        subscription=sub,
    )

    resp = client.post(
        "/subscription/change-plan", json={"plano": "101_200"}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ativa",
        "plano": "101_200",
        "precoMensal": 299.0,
        "vigencia": "proximo_ciclo",
    }
    # PUT no MESMO id remoto; zero POST /subscriptions (o fake explodiria).
    assert asaas.puts == [("sub_asaas_1", 299.0, "PastorAI — plano 101_200")]
    assert sub.plano == "101_200"
    assert sub.limite == 200
    assert sub.asaas_subscription_id == "sub_asaas_1"
    assert db.igreja.plano == "101_200"  # reflexo no cadastro da igreja


def test_late_plan_change_completion_cannot_overwrite_a_newer_plan() -> None:
    from app.services.billing import _complete_plan_change

    op_id = uuid.UUID("00000000-0000-0000-0000-00000000c901")
    stale = BillingPlanChangeOperation(
        id=op_id,
        subscription_id="00000000-0000-0000-0000-00000000su01",
        asaas_subscription_id="sub_asaas_1",
        from_plano="ate_100",
        to_plano="101_200",
        to_preco=299.0,
        to_limite=200,
        status="processing",
    )
    # O worker já concluiu a operação antiga e uma segunda troca já gravou o
    # plano mais novo enquanto a resposta do primeiro PUT estava em voo.
    current = BillingPlanChangeOperation(
        id=op_id,
        subscription_id=stale.subscription_id,
        asaas_subscription_id="sub_asaas_1",
        from_plano="ate_100",
        to_plano="101_200",
        to_preco=299.0,
        to_limite=200,
        status="completed",
    )
    sub = _subscription(plano="acima_201", limite=500)
    igreja = SimpleNamespace(id=sub.igreja_id, plano="acima_201")
    db = FakeSession(
        igreja=igreja,
        subscription=sub,
        plan_changes=[current],
    )

    applied = _complete_plan_change(db, stale, sub)

    assert applied is False
    assert sub.plano == "acima_201"
    assert sub.limite == 500
    assert igreja.plano == "acima_201"
    assert current.status == "completed"


def test_change_plan_rejects_same_plan_as_noop(app) -> None:
    client, _db = _client(
        app,
        planos=[_plano()],
        asaas=_ChangePlanAsaas(),
        subscription=_active_sub(),
    )

    resp = client.post(
        "/subscription/change-plan", json={"plano": "ate_100"}, headers=_AUTH
    )

    assert resp.status_code == 422


@pytest.mark.parametrize(
    "dirty",
    [
        {"status": "pendente"},
        {"status": "inadimplente"},
        {"asaas_invoice_reversal": "refunded"},
        {"setup_pago": False},
    ],
)
def test_change_plan_blocks_dirty_states(app, dirty) -> None:
    asaas = _ChangePlanAsaas()
    sub = _active_sub(**dirty)
    client, _db = _client(
        app,
        planos=[_plano(codigo="101_200", preco_mensal=299, limite_pessoas=200)],
        asaas=asaas,
        subscription=sub,
    )

    resp = client.post(
        "/subscription/change-plan", json={"plano": "101_200"}, headers=_AUTH
    )

    assert resp.status_code == 409
    assert asaas.puts == []
    assert sub.plano == "ate_100"


def test_change_plan_blocks_while_recovery_charge_is_open(app) -> None:
    from app.db.models import BillingPaymentOperation

    open_recovery = BillingPaymentOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        purpose="monthly_recovery",
        operation_key="pastorai-monthly_recovery-x",
        status="created",
        valor=199.0,
    )
    client, _db = _client(
        app,
        planos=[_plano(codigo="101_200", preco_mensal=299, limite_pessoas=200)],
        asaas=_ChangePlanAsaas(),
        subscription=_active_sub(),
        operations=[open_recovery],
    )

    resp = client.post(
        "/subscription/change-plan", json={"plano": "101_200"}, headers=_AUTH
    )

    assert resp.status_code == 409


def test_change_plan_remote_failure_keeps_local_plan(app) -> None:
    from app.db.models import BillingPlanChangeOperation

    asaas = _ChangePlanAsaas(error=True)
    sub = _active_sub()
    client, db = _client(
        app,
        planos=[_plano(codigo="101_200", preco_mensal=299, limite_pessoas=200)],
        asaas=asaas,
        subscription=sub,
    )

    resp = client.post(
        "/subscription/change-plan", json={"plano": "101_200"}, headers=_AUTH
    )

    assert resp.status_code == 502
    assert sub.plano == "ate_100"  # plano local intacto
    op = next(o for o in db.added if isinstance(o, BillingPlanChangeOperation))
    assert op.status == "reconciling"  # retry reconciliará por GET


def test_rejected_manual_change_requeues_growth_autoupgrade(app) -> None:
    asaas = _RejectedChangePlanAsaas()
    sub = _active_sub(pessoas=50, limite=100)
    planos = [
        _plano(codigo="ate_100", preco_mensal=199, limite_pessoas=100),
        _plano(codigo="101_200", preco_mensal=299, limite_pessoas=200),
        _plano(codigo="acima_201", preco_mensal=499, limite_pessoas=None),
    ]
    client, db = _client(
        app, planos=planos, asaas=asaas, subscription=sub
    )
    db.pessoas_count = 50
    asaas.db = db

    resp = client.post(
        "/subscription/change-plan", json={"plano": "101_200"}, headers=_AUTH
    )

    assert resp.status_code == 502
    assert sub.plano == "ate_100"
    changes = [
        o for o in db.added if isinstance(o, BillingPlanChangeOperation)
    ]
    assert len(changes) == 2
    manual, automatic = changes
    assert manual.status == "failed"
    assert manual.origin == "manual"
    assert automatic.status == "prepared"
    assert automatic.origin == "autoupgrade"
    assert automatic.to_plano == "acima_201"


def test_superseded_delayed_plan_change_returns_conflict_not_false_success(app) -> None:
    asaas = _SupersededChangePlanAsaas()
    sub = _active_sub(pessoas=50, limite=100)
    client, db = _client(
        app,
        planos=[_plano(codigo="101_200", preco_mensal=299, limite_pessoas=200)],
        asaas=asaas,
        subscription=sub,
    )
    db.pessoas_count = 50
    asaas.db = db
    asaas.sub = sub

    resp = client.post(
        "/subscription/change-plan", json={"plano": "101_200"}, headers=_AUTH
    )

    assert resp.status_code == 409
    assert "superada" in resp.json()["detail"]
    assert sub.plano == "acima_201"
    assert sub.limite is None
    assert db.igreja.plano == "acima_201"


def test_change_plan_conflicts_with_open_change_to_other_plan(app) -> None:
    from app.db.models import BillingPlanChangeOperation

    open_change = BillingPlanChangeOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        asaas_subscription_id="sub_asaas_1",
        from_plano="ate_100",
        to_plano="acima_201",
        to_preco=499.0,
        to_limite=None,
        status="processing",
    )
    client, _db = _client(
        app,
        planos=[_plano(codigo="101_200", preco_mensal=299, limite_pessoas=200)],
        asaas=_ChangePlanAsaas(),
        subscription=_active_sub(),
        plan_changes=[open_change],
    )

    resp = client.post(
        "/subscription/change-plan", json={"plano": "101_200"}, headers=_AUTH
    )

    assert resp.status_code == 409


def test_change_plan_retry_returns_the_frozen_operation_price(app) -> None:
    open_change = BillingPlanChangeOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        asaas_subscription_id="sub_asaas_1",
        from_plano="ate_100",
        to_plano="101_200",
        to_preco=299.0,
        to_limite=200,
        to_descricao="PastorAI — plano 101_200",
        status="reconciling",
    )
    asaas = _ChangePlanAsaas()
    client, _db = _client(
        app,
        # O catálogo foi editado depois de a operação congelar seu alvo.
        planos=[_plano(codigo="101_200", preco_mensal=399, limite_pessoas=200)],
        asaas=asaas,
        subscription=_active_sub(),
        plan_changes=[open_change],
    )

    resp = client.post(
        "/subscription/change-plan", json={"plano": "101_200"}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert resp.json()["precoMensal"] == 299.0
    assert asaas.puts == [
        ("sub_asaas_1", 299.0, "PastorAI — plano 101_200")
    ]


def test_get_subscription_hides_links_already_settled(app) -> None:
    # Assinatura ativa com setup pago: links persistidos não voltam na leitura
    # (nada em aberto para pagar).
    asaas = _RecoveryAsaas()
    sub = _subscription(
        status="ativa",
        setup_pago=True,
        asaas_invoice_url="https://asaas.test/monthly",
        asaas_setup_invoice_url="https://asaas.test/setup",
    )
    client, _db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["invoiceUrl"] is None
    assert body["setupInvoiceUrl"] is None
    assert asaas.calls == [("get_payment", "pay_setup_1")]


def test_checkout_rejects_plano_desconhecido(app) -> None:
    client, _db = _client(app, planos=[])
    resp = client.post(
        "/subscription", json={"plano": "nao_existe", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert resp.status_code == 422


def test_checkout_rejects_plano_inativo(app) -> None:
    # Master desativou o plano — tenant não consegue mais contratá-lo do zero
    # (grandfathering só protege quem já está nele).
    client, _db = _client(app, planos=[_plano(ativo=False)])
    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert resp.status_code == 422


def test_checkout_rejects_complimentary_plan_without_mutation_or_asaas(app) -> None:
    asaas = _FakeAsaas()
    client, db = _client(
        app,
        planos=[_plano(codigo="teste_free", preco_mensal=0)],
        asaas=asaas,
    )

    resp = client.post(
        "/subscription",
        json={"plano": "teste_free", "cpfCnpj": _CPF},
        headers=_AUTH,
    )

    assert resp.status_code == 422
    assert "administrador da plataforma" in resp.json()["detail"]
    assert asaas.calls == []
    assert not any(isinstance(obj, Subscription) for obj in db.added)


def test_complimentary_church_cannot_contract_paid_plan_or_create_placeholder(
    app,
) -> None:
    asaas = _FakeAsaas()
    client, db = _client(
        app,
        planos=[
            _plano(codigo="teste_free", preco_mensal=0),
            _plano(codigo="ate_100", preco_mensal=199),
        ],
        asaas=asaas,
        igreja_plano="teste_free",
    )

    resp = client.post(
        "/subscription",
        json={"plano": "ate_100", "cpfCnpj": _CPF},
        headers=_AUTH,
    )

    assert resp.status_code == 409
    assert "administrador da plataforma" in resp.json()["detail"]
    assert asaas.calls == []
    assert asaas.charge_calls == []
    assert not any(isinstance(obj, Subscription) for obj in db.added)
    assert db.commits == 0


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/subscription/resume", None),
        ("/subscription/recover-invoice", None),
        ("/subscription/setup-charge", None),
        ("/subscription/change-plan", {"plano": "ate_100"}),
    ],
    ids=["resume", "recovery", "setup", "plan-change"],
)
def test_complimentary_church_blocks_all_financial_self_service_before_mutation(
    app, path, payload
) -> None:
    class _NoAsaasCalls:
        def __getattr__(self, name):  # pragma: no cover - defesa do teste
            raise AssertionError(f"cortesia não pode tocar o Asaas ({name})")

    sub = _subscription(
        asaas_subscription_id="sub_should_not_be_touched",
        asaas_invoice_reversal="refunded",
        setup_pago=False,
    )
    client, db = _client(
        app,
        planos=[
            _plano(codigo="teste_free", preco_mensal=0),
            _plano(codigo="ate_100", preco_mensal=199),
        ],
        asaas=_NoAsaasCalls(),
        subscription=sub,
        igreja_plano="teste_free",
    )

    resp = client.post(path, json=payload, headers=_AUTH)

    assert resp.status_code == 409
    assert "administrador da plataforma" in resp.json()["detail"]
    assert db.added == []
    assert db.commits == 0


def test_checkout_rejects_unmatched_codigo_when_other_planos_active(app) -> None:
    # Dois planos ATIVOS no catálogo, nenhum com o código pedido — se o
    # filtro de código fosse ignorado (como no fake antigo), isso devolveria
    # 200 cobrando o preço de um plano que a igreja nem pediu.
    client, _db = _client(
        app,
        planos=[
            _plano(codigo="ate_100", ativo=True),
            _plano(codigo="101_200", ativo=True),
        ],
    )
    resp = client.post(
        "/subscription", json={"plano": "acima_201", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert resp.status_code == 422


def test_checkout_rejects_missing_or_invalid_cpf_cnpj(app) -> None:
    client, _db = _client(app, planos=[_plano()])

    missing = client.post("/subscription", json={"plano": "ate_100"}, headers=_AUTH)
    invalid = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": "111.111.111-11"}, headers=_AUTH
    )

    assert missing.status_code == 422
    assert invalid.status_code == 422


def test_list_planos_returns_active_catalog_and_setup_fee(app) -> None:
    client, _db = _client(
        app,
        planos=[_plano(preco_mensal=249, limite_pessoas=150)],
        setup_fee_default=59.9,
    )
    resp = client.get("/subscription/planos", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["planos"] == [
        {
            "codigo": "ate_100",
            "nome": "Até 100 pessoas",
            "limitePessoas": 150,
            "precoMensal": 249.0,
        }
    ]
    assert body["setupFee"] == 59.9


def test_list_planos_omits_inactive(app) -> None:
    client, _db = _client(app, planos=[_plano(ativo=False)])
    resp = client.get("/subscription/planos", headers=_AUTH)
    assert resp.status_code == 200
    assert resp.json()["planos"] == []


def test_list_planos_hides_complimentary_from_other_churches(app) -> None:
    client, _db = _client(
        app,
        planos=[
            _plano(codigo="teste_free", nome="Cortesia", preco_mensal=0),
            _plano(codigo="ate_100", preco_mensal=199),
        ],
    )

    resp = client.get("/subscription/planos", headers=_AUTH)

    assert resp.status_code == 200
    assert [p["codigo"] for p in resp.json()["planos"]] == ["ate_100"]


def test_get_subscription_exposes_master_assigned_complimentary_plan(app) -> None:
    asaas = _RecoveryAsaas()
    client, db = _client(
        app,
        planos=[
            _plano(
                codigo="teste_free",
                nome="Cortesia de testes",
                preco_mensal=0,
                limite_pessoas=50,
            )
        ],
        asaas=asaas,
        setup_fee_default=59.9,
        setup_fee_override=99.0,
        subscription=_subscription(
            status=None,
            asaas_customer_id=None,
            asaas_subscription_id=None,
            asaas_setup_charge_id=None,
        ),
        igreja_plano="teste_free",
    )
    db.pessoas_count = 7

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json() == {
        "plano": "teste_free",
        "status": "ativa",
        "pessoas": 7,
        "limite": 50,
        "proximaCobranca": None,
        "setupPago": True,
        "setupFeeContracted": 0.0,
        "invoiceUrl": None,
        "setupInvoiceUrl": None,
        "invoiceReversal": None,
        "recoveryInvoiceUrl": None,
        "recoveryRequired": False,
        "setupRecoveryRequired": False,
        "hasTrackedSubscription": False,
        "checkoutRequired": False,
        "isComplimentary": True,
    }
    assert asaas.calls == []

    catalog = client.get("/subscription/planos", headers=_AUTH)
    assert [p["codigo"] for p in catalog.json()["planos"]] == ["teste_free"]
    assert catalog.json()["setupFee"] == 0.0


def test_list_planos_forbidden_for_non_owner_admin(app) -> None:
    app.dependency_overrides[get_db] = lambda: FakeSession(
        app_user=make_app_user(dono_id="00000000-0000-0000-0000-0000000000c9"),
        roles=["admin"],
        planos=[_plano()],
    )
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    client = TestClient(app)
    resp = client.get("/subscription/planos", headers=_AUTH)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# AUTOUPGRADE-BILLING-WORKER-1: sem payment pendente de reconciliação, o GET é
# leitura pura e nunca notifica. Setup com ID rastreado é a exceção deliberada:
# uma leitura autoritativa detecta reversão cujo webhook se perdeu.
# ---------------------------------------------------------------------------
def test_get_subscription_makes_no_external_call_nor_notification(app) -> None:
    class _BoomAsaas:
        """Explode em QUALQUER acesso: prova que o GET não toca o Asaas."""

        def __getattr__(self, name):  # pragma: no cover - defesa do teste
            raise AssertionError(f"GET /subscription não pode chamar Asaas ({name})")

    sub = _subscription(
        status="pendente",
        asaas_invoice_url="https://asaas.test/i/abc",
        setup_pago=True,
        asaas_setup_charge_id=None,
    )
    client, db = _client(app, planos=[_plano()], asaas=_BoomAsaas(), subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["invoiceUrl"] == "https://asaas.test/i/abc"
    assert db.commits == 0  # leitura pura: nada persistido

    # O caminho de notificação saiu do router por inteiro: notify_autoupgrade
    # vive em app/services/billing_worker.py e o GET não depende mais do
    # EvolutionClient.
    from app.routers import subscription as subscription_module

    assert not hasattr(subscription_module, "notify_autoupgrade")
    assert not hasattr(subscription_module, "get_evolution_client")


# ---------------------------------------------------------------------------
# CORRECTIVE-6 P1: criação INICIAL de assinatura retry-safe — intenção durável
# antes do POST; resposta perdida reconcilia por externalReference (que
# localiza, mas NÃO é idempotência de POST); nunca um segundo POST às cegas.
# ---------------------------------------------------------------------------
class _LostResponseAsaas:
    """POST /subscriptions ACEITO no Asaas, resposta perdida (timeout).

    O customer resolve (callback roda) e a exceção estoura DEPOIS — como um
    `raise_for_status` de timeout. `found` é o que o retry enxerga no
    GET /subscriptions?externalReference=.
    """

    def __init__(self) -> None:
        self.create_calls = 0
        self.find_calls = 0
        self.charge_calls: list[dict] = []
        self.found: list[dict] = []

    def create_checkout(self, **kwargs):
        self.create_calls += 1
        kwargs["on_customer_resolved"]("cus_1")
        raise AsaasError("timeout depois do POST /subscriptions")

    def find_subscriptions_by_external_reference(self, ref: str) -> list[dict]:
        self.find_calls += 1
        assert ref.startswith("pastorai-subcreate-")
        return list(self.found)

    def find_payments_by_external_reference(self, ref: str) -> list[dict]:
        return []

    def create_one_time_charge(self, **kwargs):
        self.charge_calls.append(dict(kwargs))
        return {
            "id": "pay_setup_frozen",
            "invoiceUrl": "https://asaas.test/setup-frozen",
        }

    def get_subscription_payment(self, subscription_id: str):
        return {
            "id": "pay_m1",
            "status": "PENDING",
            "invoiceUrl": "https://asaas.test/m1",
            "dueDate": "2026-08-01",
        }

    def get_payment(self, payment_id: str):
        assert payment_id == "pay_m1"
        return {
            "id": payment_id,
            "status": "PENDING",
            "invoiceUrl": "https://asaas.test/m1",
            "dueDate": "2026-08-01",
        }


def _adopt_created_sub(db) -> None:
    """Entre requests do mesmo tenant: o dispatch de Subscription do fake lê
    self.subscription — aponta para a Subscription criada no 1º request."""
    created = next(o for o in db.added if isinstance(o, Subscription))
    db.subscription = created


def _ambiguous_subscription_intent(**over) -> BillingSubscriptionOperation:
    base = dict(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        operation_key="pastorai-subcreate-local-validation",
        customer_id="cus_1",
        plano="ate_100",
        valor=199.0,
        limite=100,
        setup_fee=0.0,
        ciclo="MONTHLY",
        descricao="PastorAI — plano ate_100",
        status="reconciling",
        attempt_started_at=dt.datetime.now(dt.timezone.utc),
    )
    base.update(over)
    return BillingSubscriptionOperation(**base)


class _NoAsaasCalls:
    """Qualquer método acessado prova que a validação local chegou tarde."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name):
        def forbidden(*_args, **_kwargs):
            self.calls.append(name)
            raise AssertionError(f"alvo local inválido não pode chamar Asaas ({name})")

        return forbidden


@pytest.mark.parametrize(
    ("case", "operation_status"),
    [
        ("removed", "creating"),
        ("removed", "reconciling"),
        ("complimentary", "reconciling"),
        ("invalid_catalog_price", "reconciling"),
        ("changed_catalog_price", "reconciling"),
        ("changed_catalog_limit", "reconciling"),
        ("changed_catalog_price", "prepared"),
        ("changed_catalog_limit", "prepared"),
        ("zero_frozen_price", "reconciling"),
        ("changed_setup_contract", "reconciling"),
        ("changed_customer", "reconciling"),
        ("missing_operation_key", "reconciling"),
        ("incompatible_placeholder", "reconciling"),
        ("invalid_cycle", "reconciling"),
        ("invalid_description", "reconciling"),
    ],
)
def test_ambiguous_checkout_validates_local_target_before_any_asaas_call(
    app,
    case: str,
    operation_status: str,
) -> None:
    """Catálogo/intenção divergente falha sem GET, tentativa ou mutação."""
    plan = _plano()
    plans = [plan]
    sub = _subscription(
        status=None,
        asaas_subscription_id=None,
        asaas_setup_charge_id=None,
        setup_fee_contracted=0.0,
        setup_pago=False,
    )
    op_overrides: dict[str, object] = {"status": operation_status}

    if case == "removed":
        plans = []
    elif case == "complimentary":
        plan.preco_mensal = 0
    elif case == "invalid_catalog_price":
        plan.preco_mensal = -1
    elif case == "changed_catalog_price":
        plan.preco_mensal = 249
    elif case == "changed_catalog_limit":
        plan.limite_pessoas = 150
    elif case == "zero_frozen_price":
        op_overrides["valor"] = 0
    elif case == "changed_setup_contract":
        sub.setup_fee_contracted = 59.9
    elif case == "changed_customer":
        sub.asaas_customer_id = "cus_changed"
    elif case == "missing_operation_key":
        op_overrides["operation_key"] = ""
    elif case == "incompatible_placeholder":
        sub.plano = "101_200"
    elif case == "invalid_cycle":
        op_overrides["ciclo"] = "YEARLY"
    elif case == "invalid_description":
        op_overrides["descricao"] = "alvo local incompatível"

    op = _ambiguous_subscription_intent(**op_overrides)
    asaas = _NoAsaasCalls()
    client, db = _client(
        app,
        planos=plans,
        asaas=asaas,
        subscription=sub,
        subscription_ops=[op],
    )
    op_before = (
        op.status,
        op.attempt_started_at,
        op.asaas_subscription_id,
        op.customer_id,
        op.error,
    )
    sub_before = (
        sub.plano,
        sub.status,
        sub.asaas_subscription_id,
        sub.asaas_customer_id,
        sub.setup_fee_contracted,
        sub.setup_pago,
    )
    igreja_before = (db.igreja.plano, db.igreja.status)

    response = client.post(
        "/subscription",
        json={"plano": "ate_100", "cpfCnpj": _CPF},
        headers=_AUTH,
    )

    assert response.status_code in (409, 422)
    assert asaas.calls == []
    assert (
        op.status,
        op.attempt_started_at,
        op.asaas_subscription_id,
        op.customer_id,
        op.error,
    ) == op_before
    assert (
        sub.plano,
        sub.status,
        sub.asaas_subscription_id,
        sub.asaas_customer_id,
        sub.setup_fee_contracted,
        sub.setup_pago,
    ) == sub_before
    assert (db.igreja.plano, db.igreja.status) == igreja_before
    assert db.commits == 0
    assert db.refresh_calls == []
    assert not any(isinstance(obj, Subscription) for obj in db.added)
    assert not any(isinstance(obj, BillingSubscriptionOperation) for obj in db.added)


def test_inactive_paid_plan_can_resume_its_matching_ambiguous_intent(app) -> None:
    """Grandfathering pago inativo mantém um único GET e zero novo POST."""
    plan = _plano(ativo=False)
    sub = _subscription(
        status=None,
        asaas_subscription_id=None,
        asaas_setup_charge_id=None,
        setup_fee_contracted=0.0,
        setup_pago=True,
    )
    op = _ambiguous_subscription_intent(status="reconciling")
    asaas = _LostResponseAsaas()
    asaas.found = [
        {
            "id": "sub_asaas_inactive_paid",
            "customer": "cus_1",
            "value": 199.0,
            "cycle": "MONTHLY",
            "description": "PastorAI — plano ate_100",
        }
    ]
    client, _db = _client(
        app,
        planos=[plan],
        asaas=asaas,
        subscription=sub,
        subscription_ops=[op],
    )

    response = client.post(
        "/subscription",
        json={"plano": "ate_100", "cpfCnpj": _CPF},
        headers=_AUTH,
    )

    assert response.status_code == 200
    assert plan.ativo is False
    assert asaas.find_calls == 1
    assert asaas.create_calls == 0
    assert op.status == "created"
    assert sub.asaas_subscription_id == "sub_asaas_inactive_paid"


def test_checkout_lost_response_reconciles_without_second_post(app) -> None:
    asaas = _LostResponseAsaas()
    client, db = _client(app, planos=[_plano()], asaas=asaas)

    # 1º request: POST aceito, resposta perdida → 502; NADA de retry cego.
    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert resp.status_code == 502
    assert asaas.create_calls == 1

    op = next(o for o in db.added if isinstance(o, BillingSubscriptionOperation))
    assert op.status == "reconciling"  # resultado desconhecido → só reconciliação
    # Customer persistido ANTES do POST da assinatura (nos dois lugares).
    assert op.customer_id == "cus_1"
    created_sub = next(o for o in db.added if isinstance(o, Subscription))
    assert created_sub.asaas_customer_id == "cus_1"

    # Retry: a assinatura EXISTE no Asaas com a externalReference da intenção.
    _adopt_created_sub(db)
    asaas.found = [{
        "id": "sub_asaas_9",
        "customer": "cus_1",
        "value": 199.0,
        "cycle": "MONTHLY",
        "description": "PastorAI — plano ate_100",
    }]
    resp2 = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert resp2.status_code == 200
    # ADOTADA por reconciliação: zero POST novo, mesmo id remoto rastreado.
    assert asaas.create_calls == 1
    assert created_sub.asaas_subscription_id == "sub_asaas_9"
    assert op.status == "created"
    assert op.asaas_subscription_id == "sub_asaas_9"
    assert resp2.json()["invoiceUrl"] == "https://asaas.test/m1"


def test_reconciled_adoption_discards_lookup_when_webhook_wins_during_get(app) -> None:
    asaas = _LostResponseAsaas()
    client, db = _client(app, planos=[_plano()], asaas=asaas)

    assert client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    ).status_code == 502
    _adopt_created_sub(db)
    sub = db.subscription
    op = next(o for o in db.added if isinstance(o, BillingSubscriptionOperation))
    remote = {
        "id": "sub_asaas_9",
        "customer": "cus_1",
        "value": 199.0,
        "cycle": "MONTHLY",
        "description": "PastorAI — plano ate_100",
    }

    def lookup_after_webhook(ref: str):
        # Enquanto o retry esperava o GET, o webhook resolveu a intenção e
        # confirmou a primeira cobrança no banco.
        asaas.find_calls += 1
        op.status = "created"
        op.asaas_subscription_id = "sub_asaas_9"
        sub.asaas_subscription_id = "sub_asaas_9"
        sub.asaas_invoice_payment_id = "pay_m1"
        sub.asaas_invoice_url = "https://asaas.test/m1-confirmed"
        sub.status = "ativa"
        sub.asaas_invoice_reversal = None
        return [remote]

    asaas.find_subscriptions_by_external_reference = lookup_after_webhook
    commits_before = db.commits
    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 409
    assert asaas.find_calls == 1
    assert sub.status == "ativa"
    assert sub.asaas_invoice_payment_id == "pay_m1"
    assert sub.asaas_invoice_url == "https://asaas.test/m1-confirmed"
    assert op.status == "created"
    assert op.asaas_subscription_id == "sub_asaas_9"
    assert db.commits == commits_before


@pytest.mark.parametrize(
    "changed_field",
    [
        "church_status",
        "plan_code",
        "plan_price",
        "plan_limit",
        "setup",
        "cycle",
        "description",
        "operation_status",
        "operation_attempt",
        "subscription_status",
        "subscription_customer",
    ],
)
def test_reconciliation_revalidates_every_local_snapshot_after_remote_get(
    app, changed_field: str
) -> None:
    """Um GET iniciado nunca autoriza adoção com estado local já obsoleto."""
    plan = _plano()
    sub = _subscription(
        status="pendente",
        asaas_subscription_id=None,
        asaas_setup_charge_id=None,
        setup_fee_contracted=0.0,
        setup_pago=True,
    )
    op = _ambiguous_subscription_intent(status="reconciling")
    asaas = _LostResponseAsaas()
    asaas.found = [{
        "id": "sub_remote_frozen",
        "customer": "cus_1",
        "value": 199.0,
        "cycle": "MONTHLY",
        "description": "PastorAI — plano ate_100",
    }]
    client, db = _client(
        app,
        planos=[plan],
        asaas=asaas,
        subscription=sub,
        subscription_ops=[op],
    )

    def mutate_while_get_is_in_flight(_ref: str) -> list[dict]:
        asaas.find_calls += 1
        if changed_field == "church_status":
            db.igreja.status = "suspensa"
        elif changed_field == "plan_code":
            plan.codigo = "catalogo_movido"
        elif changed_field == "plan_price":
            plan.preco_mensal = 249
        elif changed_field == "plan_limit":
            plan.limite_pessoas = 150
        elif changed_field == "setup":
            op.setup_fee = 59.9
        elif changed_field == "cycle":
            op.ciclo = "YEARLY"
        elif changed_field == "description":
            op.descricao = "Contrato alterado durante o GET"
        elif changed_field == "operation_status":
            op.status = "creating"
        elif changed_field == "operation_attempt":
            op.attempt_started_at = dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc)
        elif changed_field == "subscription_status":
            sub.status = "inadimplente"
        elif changed_field == "subscription_customer":
            sub.asaas_customer_id = "cus_changed_during_get"
        return list(asaas.found)

    asaas.find_subscriptions_by_external_reference = mutate_while_get_is_in_flight
    commits_before = db.commits
    response = client.post(
        "/subscription",
        json={"plano": "ate_100", "cpfCnpj": _CPF},
        headers=_AUTH,
    )

    assert response.status_code == 409
    assert asaas.find_calls == 1
    assert asaas.create_calls == 0
    assert op.asaas_subscription_id is None
    assert sub.asaas_subscription_id is None
    assert db.commits == commits_before
    # A própria mutação concorrente pode ter mudado o status, mas a operação
    # continua aberta/recuperável e jamais foi adotada por este request.
    assert op.status in ("creating", "reconciling")


def test_reconciliation_releases_transaction_before_get_then_relocks_canonically(
    app, monkeypatch
) -> None:
    from app.routers import subscription as subscription_router

    plan = _plano()
    sub = _prepared_placeholder(status="pendente", setup_pago=True)
    op = _ambiguous_subscription_intent(status="reconciling")
    asaas = _LostResponseAsaas()
    asaas.found = [{
        "id": "sub_remote_ordered",
        "customer": "cus_1",
        "value": 199.0,
        "cycle": "MONTHLY",
        "description": "PastorAI — plano ate_100",
    }]
    client, db = _client(
        app,
        planos=[plan],
        asaas=asaas,
        subscription=sub,
        subscription_ops=[op],
    )
    events: list[str] = []
    original_rollback = db.rollback
    original_lock_church = subscription_router.lock_igreja_for_billing
    original_lock_plans = subscription_router.lock_plan_rows_for_billing
    original_find_op = subscription_router.find_subscription_operation_by_key
    original_find_sub = subscription_router._subscription_by_id

    def rollback() -> None:
        events.append("rollback_before_get")
        original_rollback()

    def lookup(ref: str) -> list[dict]:
        asaas.find_calls += 1
        assert events == [
            "church",
            "plans",
            "subscription",
            "rollback_before_get",
        ]
        events.append("remote_get")
        return list(asaas.found)

    def lock_church(*args, **kwargs):
        events.append("church")
        return original_lock_church(*args, **kwargs)

    def lock_plans(*args, **kwargs):
        events.append("plans")
        return original_lock_plans(*args, **kwargs)

    def find_op(*args, **kwargs):
        if kwargs.get("for_update"):
            events.append("operation")
        return original_find_op(*args, **kwargs)

    def find_sub(*args, **kwargs):
        if kwargs.get("for_update"):
            events.append("subscription")
        return original_find_sub(*args, **kwargs)

    db.rollback = rollback
    asaas.find_subscriptions_by_external_reference = lookup
    monkeypatch.setattr(subscription_router, "lock_igreja_for_billing", lock_church)
    monkeypatch.setattr(subscription_router, "lock_plan_rows_for_billing", lock_plans)
    monkeypatch.setattr(
        subscription_router, "find_subscription_operation_by_key", find_op
    )
    monkeypatch.setattr(subscription_router, "_subscription_by_id", find_sub)

    response = client.post(
        "/subscription",
        json={"plano": "ate_100", "cpfCnpj": _CPF},
        headers=_AUTH,
    )

    assert response.status_code == 200
    assert events[:9] == [
        "church",
        "plans",
        "subscription",
        "rollback_before_get",
        "remote_get",
        "church",
        "plans",
        "operation",
        "subscription",
    ]


class _PreparedNoNetwork:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name):
        def forbidden(*_args, **_kwargs):
            self.calls.append(name)
            raise AssertionError(f"placeholder conflitante tocou Asaas ({name})")

        return forbidden


def _prepared_placeholder(**over) -> SimpleNamespace:
    base = dict(
        status="pendente",
        asaas_customer_id="cus_1",
        asaas_subscription_id=None,
        asaas_setup_charge_id=None,
        asaas_setup_reversed_payment_id=None,
        asaas_invoice_payment_id=None,
        asaas_invoice_url=None,
        asaas_setup_invoice_url=None,
        asaas_invoice_reversal=None,
        proxima_cobranca=None,
        setup_fee_contracted=0.0,
        setup_pago=False,
        limite=100,
    )
    base.update(over)
    return _subscription(**base)


@pytest.mark.parametrize(
    "conflict",
    [
        "plan",
        "customer",
        "cycle",
        "church",
        "status",
        "external_id",
        "operation_external_id",
        "setup",
    ],
)
def test_prepared_placeholder_conflict_fails_before_commit_claim_or_network(
    app, conflict: str
) -> None:
    sub = _prepared_placeholder()
    op = _ambiguous_subscription_intent(status="prepared", attempt_started_at=None)
    if conflict == "plan":
        sub.plano = "101_200"
    elif conflict == "customer":
        sub.asaas_customer_id = "cus_other"
    elif conflict == "cycle":
        sub.ciclo = "YEARLY"
    elif conflict == "church":
        sub.igreja_id = "00000000-0000-0000-0000-00000000ffff"
    elif conflict == "status":
        sub.status = "ativa"
    elif conflict == "external_id":
        sub.asaas_subscription_id = "sub_other"
    elif conflict == "operation_external_id":
        op.asaas_subscription_id = "sub_other"
    elif conflict == "setup":
        sub.setup_fee_contracted = 59.9

    asaas = _PreparedNoNetwork()
    client, db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        subscription=sub,
        subscription_ops=[op],
    )
    op_before = (
        op.status,
        op.attempt_started_at,
        op.asaas_subscription_id,
        op.error,
    )
    sub_before = vars(sub).copy()
    response = client.post(
        "/subscription",
        json={"plano": "ate_100", "cpfCnpj": _CPF},
        headers=_AUTH,
    )

    assert response.status_code == 409
    assert asaas.calls == []
    assert db.commits == 0
    assert (
        op.status,
        op.attempt_started_at,
        op.asaas_subscription_id,
        op.error,
    ) == op_before
    assert vars(sub) == sub_before
    assert db.added == []


def test_subscription_asaas_field_inventory_is_explicit() -> None:
    asaas_fields = {
        column.name
        for column in Subscription.__table__.columns
        if column.name.startswith("asaas_")
    }

    assert asaas_fields == {
        "asaas_customer_id",
        "asaas_subscription_id",
        "asaas_setup_charge_id",
        "asaas_setup_reversed_payment_id",
        "asaas_invoice_url",
        "asaas_setup_invoice_url",
        "asaas_invoice_payment_id",
        "asaas_invoice_reversal",
    }


def test_all_financial_operation_fields_are_inventoried_explicitly() -> None:
    from app.routers import subscription as subscription_router

    assert set(subscription_router._PAYMENT_OPERATION_INVENTORY_FIELDS) == {
        column.name
        for column in BillingPaymentOperation.__table__.columns
        if column.name not in {"created_at", "updated_at"}
    }
    assert set(subscription_router._PLAN_CHANGE_OPERATION_INVENTORY_FIELDS) == {
        column.name
        for column in BillingPlanChangeOperation.__table__.columns
        if column.name not in {"created_at", "updated_at"}
    }
    assert set(subscription_router._SUBSCRIPTION_OPERATION_INVENTORY_FIELDS) == {
        column.name
        for column in BillingSubscriptionOperation.__table__.columns
        if column.name not in {"created_at", "updated_at"}
    }


def _payment_history(**over) -> BillingPaymentOperation:
    base = dict(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        purpose="setup",
        operation_key="pastorai-setup-history-review8",
        source_payment_id=None,
        asaas_payment_id=None,
        status="failed",
        valor=50.0,
        invoice_url=None,
        error="rejeição definitiva",
        attempt_started_at=None,
    )
    base.update(over)
    return BillingPaymentOperation(**base)


def _plan_change_history(**over) -> BillingPlanChangeOperation:
    base = dict(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        asaas_subscription_id="sub_remote_history",
        from_plano="ate_100",
        to_plano="101_200",
        to_preco=299.0,
        to_limite=200,
        to_descricao="PastorAI — plano 101_200",
        origin="manual",
        status="completed",
        notify_status="skipped",
        attempt_started_at=None,
    )
    base.update(over)
    return BillingPlanChangeOperation(**base)


def _assert_new_subscription_history_conflict(
    app,
    *,
    operations: list[BillingPaymentOperation] | None = None,
    plan_changes: list[BillingPlanChangeOperation] | None = None,
    extra_subscription_ops: list[BillingSubscriptionOperation] | None = None,
) -> None:
    sub = _prepared_placeholder()
    current = _ambiguous_subscription_intent(
        status="prepared", attempt_started_at=None
    )
    histories: list[object] = [
        *(operations or []),
        *(plan_changes or []),
        *(extra_subscription_ops or []),
    ]
    histories_before = [vars(item).copy() for item in histories]
    current_before = vars(current).copy()
    sub_before = vars(sub).copy()
    asaas = _PreparedNoNetwork()
    client, db = _client(
        app,
        planos=[
            _plano(),
            _plano(
                codigo="101_200",
                nome="101–200 pessoas",
                limite_pessoas=200,
                preco_mensal=299,
            ),
        ],
        asaas=asaas,
        subscription=sub,
        operations=operations,
        plan_changes=plan_changes,
        subscription_ops=[current, *(extra_subscription_ops or [])],
    )
    church_before = vars(db.igreja).copy()

    response = client.post(
        "/subscription",
        json={"plano": "ate_100", "cpfCnpj": _CPF},
        headers=_AUTH,
    )

    assert response.status_code == 409
    assert asaas.calls == []
    assert db.commits == 0
    assert db.added == []
    assert vars(current) == current_before
    assert vars(sub) == sub_before
    assert vars(db.igreja) == church_before
    assert [vars(item) for item in histories] == histories_before


@pytest.mark.parametrize(
    ("operation_status", "overrides"),
    [
        ("prepared", {}),
        ("creating", {"attempt_started_at": dt.datetime.now(dt.timezone.utc)}),
        ("reconciling", {}),
        ("created", {"asaas_payment_id": "pay_setup_created"}),
        ("paid", {"asaas_payment_id": "pay_setup_paid"}),
        ("reversed", {"asaas_payment_id": "pay_setup_reversed"}),
        ("failed", {"asaas_payment_id": "pay_setup_failed_but_remote"}),
        ("future_unknown", {}),
    ],
)
def test_payment_history_blocks_new_subscription_before_claim_or_network(
    app, operation_status: str, overrides: dict
) -> None:
    _assert_new_subscription_history_conflict(
        app,
        operations=[_payment_history(status=operation_status, **overrides)],
    )


def test_reversed_setup_history_missing_from_subscription_blocks_new_post(app) -> None:
    _assert_new_subscription_history_conflict(
        app,
        operations=[
            _payment_history(
                status="reversed",
                asaas_payment_id="pay_reversed_only_in_operation",
                invoice_url="https://asaas.test/reversed-history",
            )
        ],
    )


@pytest.mark.parametrize(
    "operation_status",
    ["prepared", "processing", "reconciling", "completed", "failed", "future_unknown"],
)
def test_plan_change_remote_history_blocks_second_subscription_post(
    app, operation_status: str
) -> None:
    _assert_new_subscription_history_conflict(
        app,
        plan_changes=[_plan_change_history(status=operation_status)],
    )


def test_historical_subscription_remote_id_blocks_new_post(app) -> None:
    historical = _ambiguous_subscription_intent(
        operation_key="pastorai-subcreate-historical-created",
        status="created",
        asaas_subscription_id="sub_only_in_history",
        attempt_started_at=None,
    )
    _assert_new_subscription_history_conflict(
        app, extra_subscription_ops=[historical]
    )


def test_unknown_historical_subscription_state_fails_closed(app) -> None:
    historical = _ambiguous_subscription_intent(
        operation_key="pastorai-subcreate-historical-unknown",
        status="future_unknown",
        customer_id=None,
        attempt_started_at=None,
    )
    _assert_new_subscription_history_conflict(
        app, extra_subscription_ops=[historical]
    )


def test_failed_payment_without_remote_markers_remains_safe_history(app) -> None:
    sub = _prepared_placeholder()
    current = _ambiguous_subscription_intent(
        status="prepared", attempt_started_at=None
    )
    failed = _payment_history()
    asaas = _FakeAsaas()
    client, _db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        subscription=sub,
        operations=[failed],
        subscription_ops=[current],
    )

    response = client.post(
        "/subscription",
        json={"plano": "ate_100", "cpfCnpj": _CPF},
        headers=_AUTH,
    )

    assert response.status_code == 200
    assert len(asaas.calls) == 1
    assert current.status == "created"


def test_history_materialized_after_claim_is_revalidated_before_asaas(app) -> None:
    sub = _prepared_placeholder()
    current = _ambiguous_subscription_intent(
        status="prepared", attempt_started_at=None
    )
    history = _payment_history(
        status="reversed",
        asaas_payment_id="pay_race_after_claim",
    )
    asaas = _PreparedNoNetwork()
    client, db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        subscription=sub,
        subscription_ops=[current],
    )
    original_commit = db.commit
    history_before = vars(history).copy()

    def commit_and_materialize_history() -> None:
        original_commit()
        if db.commits == 1:
            # Simula outra transação que venceu logo após o commit do claim.
            # A nova leitura canônica precisa barrar a chamada externa.
            db.operations.append(history)

    db.commit = commit_and_materialize_history

    response = client.post(
        "/subscription",
        json={"plano": "ate_100", "cpfCnpj": _CPF},
        headers=_AUTH,
    )

    assert response.status_code == 409
    assert "reconciliação manual" in response.json()["detail"]
    assert asaas.calls == []
    assert db.commits == 1
    assert db.added == []
    assert vars(history) == history_before


class _TrackedSubscriptionNoCreate:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_subscription_payment(self, subscription_id: str):
        self.calls.append(("GET subscription payment", subscription_id))
        return None

    def create_checkout(self, **_kwargs):  # pragma: no cover - defesa do teste
        self.calls.append(("POST subscription", "unexpected"))
        raise AssertionError("assinatura rastreada nunca cria nova recorrência")


def test_reconciled_plan_change_history_does_not_false_block_tracked_subscription(
    app,
) -> None:
    sub = _subscription(
        plano="101_200",
        asaas_subscription_id="sub_remote_history",
        asaas_setup_charge_id=None,
        setup_fee_contracted=0.0,
        setup_pago=True,
    )
    history = _plan_change_history()
    asaas = _TrackedSubscriptionNoCreate()
    client, _db = _client(
        app,
        planos=[
            _plano(),
            _plano(
                codigo="101_200",
                nome="101–200 pessoas",
                limite_pessoas=200,
                preco_mensal=299,
            ),
        ],
        asaas=asaas,
        subscription=sub,
        plan_changes=[history],
    )

    response = client.post(
        "/subscription",
        json={"plano": "101_200"},
        headers=_AUTH,
    )

    assert response.status_code == 200
    assert asaas.calls == [("GET subscription payment", "sub_remote_history")]


def test_divergent_plan_change_id_blocks_tracked_subscription_before_network(
    app,
) -> None:
    sub = _subscription(
        plano="101_200",
        asaas_subscription_id="sub_current",
        asaas_setup_charge_id=None,
        setup_fee_contracted=0.0,
        setup_pago=True,
    )
    history = _plan_change_history(asaas_subscription_id="sub_other")
    asaas = _PreparedNoNetwork()
    client, db = _client(
        app,
        planos=[
            _plano(),
            _plano(
                codigo="101_200",
                nome="101–200 pessoas",
                limite_pessoas=200,
                preco_mensal=299,
            ),
        ],
        asaas=asaas,
        subscription=sub,
        plan_changes=[history],
    )
    history_before = vars(history).copy()
    sub_before = vars(sub).copy()

    response = client.post(
        "/subscription",
        json={"plano": "101_200"},
        headers=_AUTH,
    )

    assert response.status_code == 409
    assert asaas.calls == []
    assert db.commits == 0
    assert vars(history) == history_before
    assert vars(sub) == sub_before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("asaas_subscription_id", "sub_materialized"),
        ("asaas_setup_charge_id", "pay_setup_materialized"),
        ("asaas_setup_reversed_payment_id", "pay_setup_reversed"),
        ("asaas_invoice_payment_id", "pay_monthly_materialized"),
        ("asaas_invoice_url", "https://asaas.test/monthly-materialized"),
        ("asaas_setup_invoice_url", "https://asaas.test/setup-materialized"),
        ("asaas_invoice_reversal", "refunded"),
        ("proxima_cobranca", "2026-09-01"),
    ],
)
def test_prepared_placeholder_financial_marker_fails_without_side_effects(
    app, field: str, value: object
) -> None:
    sub = _prepared_placeholder(**{field: value})
    op = _ambiguous_subscription_intent(status="prepared", attempt_started_at=None)
    asaas = _PreparedNoNetwork()
    client, db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        subscription=sub,
        subscription_ops=[op],
    )
    op_before = vars(op).copy()
    sub_before = vars(sub).copy()

    response = client.post(
        "/subscription",
        json={"plano": "ate_100", "cpfCnpj": _CPF},
        headers=_AUTH,
    )

    assert response.status_code == 409
    assert asaas.calls == []
    assert db.commits == 0
    assert vars(op) == op_before
    assert vars(sub) == sub_before
    assert getattr(sub, field) == value
    assert db.added == []


def test_prepared_placeholder_reversal_history_combination_is_preserved(
    app,
) -> None:
    sub = _prepared_placeholder(
        asaas_setup_reversed_payment_id="pay_setup_reversed",
        asaas_invoice_reversal="deleted",
    )
    op = _ambiguous_subscription_intent(status="prepared", attempt_started_at=None)
    asaas = _PreparedNoNetwork()
    client, db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        subscription=sub,
        subscription_ops=[op],
    )
    op_before = vars(op).copy()
    sub_before = vars(sub).copy()

    response = client.post(
        "/subscription",
        json={"plano": "ate_100", "cpfCnpj": _CPF},
        headers=_AUTH,
    )

    assert response.status_code == 409
    assert asaas.calls == []
    assert db.commits == 0
    assert vars(op) == op_before
    assert vars(sub) == sub_before
    assert sub.asaas_setup_reversed_payment_id == "pay_setup_reversed"
    assert sub.asaas_invoice_reversal == "deleted"
    assert db.added == []


@pytest.mark.parametrize("placeholder_shape", ["absent_fields", "matching"])
def test_prepared_placeholder_absent_or_matching_identity_can_proceed(
    app, placeholder_shape: str
) -> None:
    if placeholder_shape == "absent_fields":
        sub = _prepared_placeholder(
            plano="",
            status=None,
            limite=None,
            asaas_customer_id=None,
            setup_fee_contracted=None,
        )
        op = _ambiguous_subscription_intent(
            status="prepared", customer_id=None, attempt_started_at=None
        )
    else:
        sub = _prepared_placeholder()
        op = _ambiguous_subscription_intent(
            status="prepared", attempt_started_at=None
        )
    asaas = _FakeAsaas()
    client, _db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        subscription=sub,
        subscription_ops=[op],
    )

    response = client.post(
        "/subscription",
        json={"plano": "ate_100", "cpfCnpj": _CPF},
        headers=_AUTH,
    )

    assert response.status_code == 200
    assert len(asaas.calls) == 1
    assert op.status == "created"
    assert sub.plano == "ate_100"


def test_prepared_placeholder_empty_financial_markers_can_proceed(app) -> None:
    sub = _prepared_placeholder(
        asaas_subscription_id="",
        asaas_setup_charge_id=" ",
        asaas_setup_reversed_payment_id="",
        asaas_invoice_payment_id=" ",
        asaas_invoice_url="",
        asaas_setup_invoice_url=" ",
        asaas_invoice_reversal="",
        proxima_cobranca=None,
        setup_pago=False,
    )
    op = _ambiguous_subscription_intent(
        status="prepared", attempt_started_at=None
    )
    asaas = _FakeAsaas()
    client, _db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        subscription=sub,
        subscription_ops=[op],
    )

    response = client.post(
        "/subscription",
        json={"plano": "ate_100", "cpfCnpj": _CPF},
        headers=_AUTH,
    )

    assert response.status_code == 200
    assert len(asaas.calls) == 1
    assert op.status == "created"


def test_checkout_reconcile_zero_matches_stays_reconciling_without_post(app) -> None:
    asaas = _LostResponseAsaas()
    client, db = _client(app, planos=[_plano()], asaas=asaas)

    assert client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    ).status_code == 502
    _adopt_created_sub(db)

    # Retry com ZERO correspondências: permanece reconciling — nunca outro POST.
    resp2 = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert resp2.status_code == 502
    assert asaas.create_calls == 1
    assert asaas.find_calls == 1
    op = next(o for o in db.added if isinstance(o, BillingSubscriptionOperation))
    assert op.status == "reconciling"
    created_sub = next(o for o in db.added if isinstance(o, Subscription))
    assert created_sub.asaas_subscription_id is None


def test_checkout_reconcile_multiple_matches_stays_blocking(app) -> None:
    asaas = _LostResponseAsaas()
    client, db = _client(app, planos=[_plano()], asaas=asaas)

    assert client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    ).status_code == 502
    _adopt_created_sub(db)
    match = {
        "id": "sub_asaas_a",
        "customer": "cus_1",
        "value": 199.0,
        "cycle": "MONTHLY",
        "description": "PastorAI — plano ate_100",
    }
    asaas.found = [match, {**match, "id": "sub_asaas_b"}]

    for _ in range(2):
        assert client.post(
            "/subscription",
            json={"plano": "ate_100", "cpfCnpj": _CPF},
            headers=_AUTH,
        ).status_code == 502

    op = next(o for o in db.added if isinstance(o, BillingSubscriptionOperation))
    assert op.status == "reconciling"
    assert "revisão manual" in (op.error or "")
    assert asaas.find_calls == 2
    assert asaas.create_calls == 1


def test_adoption_uses_the_setup_fee_frozen_before_the_lost_response(app) -> None:
    asaas = _LostResponseAsaas()
    client, db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        setup_fee_default=59.9,
    )

    assert client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    ).status_code == 502
    op = next(o for o in db.added if isinstance(o, BillingSubscriptionOperation))
    created_sub = next(o for o in db.added if isinstance(o, Subscription))
    assert float(op.setup_fee) == 59.9
    assert float(created_sub.setup_fee_contracted) == 59.9

    _adopt_created_sub(db)
    db.billing_settings.setup_fee_default = 0.0
    asaas.found = [{
        "id": "sub_asaas_frozen",
        "customer": "cus_1",
        "value": 199.0,
        "cycle": "MONTHLY",
        "description": "PastorAI — plano ate_100",
    }]

    response = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert response.status_code == 200
    assert asaas.create_calls == 1
    assert len(asaas.charge_calls) == 1
    assert asaas.charge_calls[0]["valor"] == 59.9
    assert created_sub.setup_fee_contracted == 59.9


def test_adoption_of_zero_fee_checkout_marks_setup_as_paid(app) -> None:
    asaas = _LostResponseAsaas()
    client, db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        setup_fee_default=0.0,
    )

    assert client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    ).status_code == 502
    created_sub = next(o for o in db.added if isinstance(o, Subscription))
    assert not created_sub.setup_pago
    assert float(created_sub.setup_fee_contracted) == 0.0

    _adopt_created_sub(db)
    asaas.found = [{
        "id": "sub_asaas_zero_setup",
        "customer": "cus_1",
        "value": 199.0,
        "cycle": "MONTHLY",
        "description": "PastorAI — plano ate_100",
    }]

    response = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert response.status_code == 200
    assert created_sub.setup_pago is True
    assert asaas.charge_calls == []
    assert client.get("/subscription", headers=_AUTH).json()[
        "setupRecoveryRequired"
    ] is False


def test_abandoned_subscription_claim_stays_reconciling_without_second_post(app) -> None:
    op = BillingSubscriptionOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        operation_key="pastorai-subcreate-abandoned",
        customer_id="cus_1",
        plano="ate_100",
        valor=199.0,
        limite=100,
        setup_fee=0.0,
        ciclo="MONTHLY",
        descricao="PastorAI — plano ate_100",
        status="creating",
        attempt_started_at=(
            dt.datetime.now(dt.timezone.utc)
            - dt.timedelta(minutes=10)
            - dt.timedelta(seconds=1)
        ),
    )

    class _ReclaimingAsaas:
        def __init__(self) -> None:
            self.find_calls = 0
            self.create_calls = 0

        def find_subscriptions_by_external_reference(self, ref: str):
            self.find_calls += 1
            return []

        def create_checkout(self, **kwargs):
            self.create_calls += 1
            kwargs["on_customer_resolved"]("cus_1")
            kwargs["on_subscription_created"]("cus_1", "sub_reclaimed")
            return CheckoutResult(
                status="pendente",
                customer_id="cus_1",
                subscription_id="sub_reclaimed",
                invoice_url="https://asaas.test/reclaimed",
                invoice_payment_id="pay_reclaimed",
            )

    asaas = _ReclaimingAsaas()
    sub = _subscription(
        asaas_subscription_id=None,
        asaas_setup_charge_id=None,
        setup_fee_contracted=0.0,
        setup_pago=False,
    )
    client, db = _client(
        app,
        planos=[_plano()],
        asaas=asaas,
        subscription=sub,
        subscription_ops=[op],
    )

    first = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert first.status_code == 502
    assert op.status == "reconciling"
    assert asaas.find_calls == 1
    assert asaas.create_calls == 0

    second = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert second.status_code == 502
    assert asaas.find_calls == 2
    assert asaas.create_calls == 0
    assert op.status == "reconciling"
    assert sub.asaas_subscription_id is None


class _CustomerFailAsaas:
    """Falha ANTES do customer existir: o POST comprovadamente não aconteceu."""

    def __init__(self) -> None:
        self.create_calls = 0

    def create_checkout(self, **kwargs):
        self.create_calls += 1
        if self.create_calls == 1:
            raise AsaasError("falha ao resolver o customer")
        kwargs["on_customer_resolved"]("cus_1")
        kwargs["on_subscription_created"]("cus_1", "sub_asaas_1")
        return CheckoutResult(
            customer_id="cus_1",
            subscription_id="sub_asaas_1",
            invoice_url="https://asaas.test/m1",
            status="pendente",
            invoice_payment_id="pay_m1",
        )


def test_checkout_customer_failure_returns_to_prepared_and_allows_retry_post(
    app,
) -> None:
    asaas = _CustomerFailAsaas()
    client, db = _client(app, planos=[_plano()], asaas=asaas)

    assert client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    ).status_code == 502
    op = next(o for o in db.added if isinstance(o, BillingSubscriptionOperation))
    # Sem customer resolvido, o POST nunca rodou: a intenção volta a prepared.
    assert op.status == "prepared"
    assert op.customer_id is None

    _adopt_created_sub(db)
    resp2 = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    # Retry LEGÍTIMO (nada existia no Asaas): um novo POST é permitido.
    assert resp2.status_code == 200
    assert asaas.create_calls == 2
    assert op.status == "created"
    assert op.asaas_subscription_id == "sub_asaas_1"


class _CustomerPersistRetryAsaas:
    """Customer existe, mas o primeiro commit local falha antes da assinatura."""

    def __init__(self) -> None:
        self.create_calls = 0

    def create_checkout(self, **kwargs):
        self.create_calls += 1
        kwargs["on_customer_resolved"]("cus_1")
        kwargs["on_subscription_created"]("cus_1", "sub_asaas_1")
        return CheckoutResult(
            customer_id="cus_1",
            subscription_id="sub_asaas_1",
            invoice_url="https://asaas.test/m1",
            status="pendente",
            invoice_payment_id="pay_m1",
        )


def test_customer_persistence_failure_returns_intent_to_prepared(app) -> None:
    asaas = _CustomerPersistRetryAsaas()
    client, db = _client(app, planos=[_plano()], asaas=asaas)
    original_commit = db.commit

    def fail_customer_commit_once() -> None:
        # Placeholder + intenção agora nascem no mesmo commit; depois, o claim
        # faz o segundo. O terceiro é a callback que persiste o customer antes
        # do POST /subscriptions.
        if db.commits == 2:
            db.commits += 1
            raise RuntimeError("falha transitória no commit do customer")
        original_commit()

    db.commit = fail_customer_commit_once  # type: ignore[method-assign]

    first = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert first.status_code == 502
    op = next(o for o in db.added if isinstance(o, BillingSubscriptionOperation))
    assert op.status == "prepared"
    assert op.customer_id is None
    created_sub = next(o for o in db.added if isinstance(o, Subscription))
    assert created_sub.asaas_subscription_id is None

    _adopt_created_sub(db)
    second = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert second.status_code == 200
    assert asaas.create_calls == 2
    assert op.status == "created"
    assert created_sub.asaas_subscription_id == "sub_asaas_1"


# ---------------------------------------------------------------------------
# CORRECTIVE-6 P1: recuperação com plano grandfathered (desativado no catálogo)
# ---------------------------------------------------------------------------
def test_recover_refunded_works_with_inactive_plan_using_original_amount(
    app,
) -> None:
    # Plano DESATIVADO pelo master, assinante existente, fatura estornada: a
    # recuperação sai pelo VALOR ORIGINAL da cobrança rastreada — não pelo
    # catálogo (que nem pode reajustar o grandfathered).
    asaas = _RecoveryChargeAsaas(payment_value=149.0)
    plano_inativo = _plano(ativo=False, preco_mensal=999.0)
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m3",
        asaas_invoice_reversal="refunded",
    )
    client, db = _client(app, planos=[plano_inativo], asaas=asaas, subscription=sub)

    resp = client.post("/subscription/recover-invoice", headers=_AUTH)

    assert resp.status_code == 200
    assert asaas.posts == 1
    assert asaas.charged_values == [149.0]  # nunca os 999 do catálogo atual
    assert resp.json()["recoveryInvoiceUrl"] == "https://asaas.test/recovery"
    assert plano_inativo.ativo is False  # plano segue desativado


def test_recover_refunded_without_value_source_fails_without_charge(app) -> None:
    asaas = _RecoveryChargeAsaas(payment_value=None, subscription_value=None)
    sub = _subscription(
        status="inadimplente",
        setup_pago=True,
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id="pay_m3",
        asaas_invoice_reversal="refunded",
    )
    client, _db = _client(app, planos=[_plano()], asaas=asaas, subscription=sub)

    resp = client.post("/subscription/recover-invoice", headers=_AUTH)

    # Sem fonte confiável de valor: erro CONTROLADO e nenhuma cobrança criada.
    assert resp.status_code == 409
    assert asaas.posts == 0


# ---------------------------------------------------------------------------
# CORRECTIVE-7 P1: 4xx definitivo volta a `prepared`; adoção reconciliada é
# atômica (a operação fica ABERTA até o commit conjunto com a Subscription).
# ---------------------------------------------------------------------------
class _RejectedThenOkAsaas:
    """1ª chamada: rejeição DEFINITIVA (4xx) após customer resolvido."""

    def __init__(self) -> None:
        self.create_calls = 0

    def create_checkout(self, **kwargs):
        self.create_calls += 1
        kwargs["on_customer_resolved"]("cus_1")
        if self.create_calls == 1:
            raise AsaasRejectedError("O Asaas rejeitou os dados do checkout")
        kwargs["on_subscription_created"]("cus_1", "sub_asaas_1")
        return CheckoutResult(
            customer_id="cus_1",
            subscription_id="sub_asaas_1",
            invoice_url="https://asaas.test/m1",
            status="pendente",
            invoice_payment_id="pay_m1",
        )


class _RejectedThenCustomerFailAsaas:
    """4xx definitivo, depois falha pré-POST com customer antigo persistido."""

    def __init__(self) -> None:
        self.create_calls = 0

    def create_checkout(self, **kwargs):
        self.create_calls += 1
        if self.create_calls == 1:
            kwargs["on_customer_resolved"]("cus_1")
            raise AsaasRejectedError("O Asaas rejeitou os dados do checkout")
        if self.create_calls == 2:
            raise AsaasError("timeout ao procurar customer")
        kwargs["on_customer_resolved"]("cus_1")
        kwargs["on_subscription_created"]("cus_1", "sub_asaas_1")
        return CheckoutResult(
            customer_id="cus_1",
            subscription_id="sub_asaas_1",
            invoice_url="https://asaas.test/m1",
            status="pendente",
            invoice_payment_id="pay_m1",
        )


def test_checkout_definitive_rejection_returns_to_prepared_and_allows_retry(
    app,
) -> None:
    asaas = _RejectedThenOkAsaas()
    client, db = _client(app, planos=[_plano()], asaas=asaas)

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert resp.status_code == 502
    assert "rejeitou" in resp.json()["detail"]
    op = next(o for o in db.added if isinstance(o, BillingSubscriptionOperation))
    # 4xx é DEFINITIVO (nada criado): a intenção volta a prepared — sem ficar
    # presa em reconciling — e o customer resolvido fica preservado.
    assert op.status == "prepared"
    assert op.customer_id == "cus_1"

    _adopt_created_sub(db)
    resp2 = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert resp2.status_code == 200
    assert asaas.create_calls == 2  # retry legítimo após correção dos dados
    assert op.status == "created"
    created_sub = next(o for o in db.added if isinstance(o, Subscription))
    assert created_sub.asaas_subscription_id == "sub_asaas_1"  # UMA recorrência


def test_pre_post_retry_failure_ignores_customer_from_a_previous_attempt(
    app,
) -> None:
    asaas = _RejectedThenCustomerFailAsaas()
    client, db = _client(app, planos=[_plano()], asaas=asaas)

    first = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert first.status_code == 502
    op = next(o for o in db.added if isinstance(o, BillingSubscriptionOperation))
    assert op.status == "prepared"
    assert op.customer_id == "cus_1"

    _adopt_created_sub(db)
    second = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert second.status_code == 502
    # A callback não rodou nesta tentativa: nenhum POST de assinatura ocorreu.
    assert op.status == "prepared"
    assert op.customer_id == "cus_1"

    third = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert third.status_code == 200
    assert op.status == "created"
    assert asaas.create_calls == 3


# ---------------------------------------------------------------------------
# CORRECTIVE-9 P1: downgrade abaixo dos membros atuais é rejeitado ANTES de criar
# operação ou tocar o Asaas (o trigger só corrigiria numa mudança de membro).
# ---------------------------------------------------------------------------
class _NoCallAsaas:
    """Qualquer chamada aqui é falha do teste: o bloqueio vem antes."""

    def __getattr__(self, name):  # pragma: no cover - defesa
        raise AssertionError(f"downgrade bloqueado não pode chamar Asaas ({name})")


def _downgrade_client(app, *, pessoas: int, limite_alvo, preco=99.0):
    plano_atual = _plano(codigo="acima_201", preco_mensal=499.0, limite_pessoas=None)
    plano_alvo = _plano(
        codigo="ate_100", preco_mensal=preco, limite_pessoas=limite_alvo
    )
    sub = _active_sub(plano="acima_201", limite=None, pessoas=pessoas)
    client, db = _client(
        app,
        planos=[plano_atual, plano_alvo],
        asaas=_NoCallAsaas(),
        subscription=sub,
    )
    db.pessoas_count = pessoas
    return client, db, sub


def test_change_plan_rejects_downgrade_below_current_headcount(app) -> None:
    client, db, sub = _downgrade_client(app, pessoas=201, limite_alvo=100)

    resp = client.post(
        "/subscription/change-plan", json={"plano": "ate_100"}, headers=_AUTH
    )

    assert resp.status_code == 422
    assert "201" in resp.json()["detail"]
    assert "membros" in resp.json()["detail"]
    # Zero PUT (fake explode), zero operação criada, plano local intacto.
    assert not [
        o for o in db.added if isinstance(o, BillingPlanChangeOperation)
    ]
    assert sub.plano == "acima_201"


def test_change_plan_allows_downgrade_exactly_at_the_limit(app) -> None:
    client, db, sub = _downgrade_client(app, pessoas=100, limite_alvo=100)
    # Aqui o fluxo segue: troca o fake por um que aceita o PUT.
    app.dependency_overrides[get_asaas_client] = lambda: _ChangePlanAsaas()

    resp = client.post(
        "/subscription/change-plan", json={"plano": "ate_100"}, headers=_AUTH
    )

    assert resp.status_code == 200  # igualdade é permitida
    assert sub.plano == "ate_100"


def test_change_plan_allows_unlimited_target(app) -> None:
    plano_atual = _plano(codigo="ate_100", preco_mensal=99.0, limite_pessoas=100)
    ilimitado = _plano(codigo="acima_201", preco_mensal=499.0, limite_pessoas=None)
    sub = _active_sub(plano="ate_100", limite=100, pessoas=5000)
    client, db = _client(
        app,
        planos=[plano_atual, ilimitado],
        asaas=_ChangePlanAsaas(),
        subscription=sub,
    )
    db.pessoas_count = 5000

    resp = client.post(
        "/subscription/change-plan", json={"plano": "acima_201"}, headers=_AUTH
    )

    assert resp.status_code == 200  # plano ilimitado nunca é bloqueado
    assert sub.plano == "acima_201"


# ---------------------------------------------------------------------------
# SELF-AUDIT-10: a corrida "o porte subiu DURANTE a troca" precisa ser
# exercitada de verdade — o teste anterior morria num 422 de mesmo-plano antes
# de alcançar o enfileiramento, e a função lia o espelho `sub.pessoas` do
# objeto em memória (anterior à chamada externa), o que a tornava inerte.
# ---------------------------------------------------------------------------
class _FlakyChangePlanAsaas:
    """PUT falha (ambíguo) na 1ª vez e conclui na 2ª. Criar assinatura EXPLODE."""

    def __init__(self) -> None:
        self.puts: list[tuple[str, float, str]] = []
        self.gets = 0

    def update_subscription(self, subscription_id: str, *, valor: float, descricao: str):
        self.puts.append((subscription_id, valor, descricao))
        if len(self.puts) == 1:
            raise AsaasError("timeout ambíguo depois do PUT")
        return {"id": subscription_id, "value": valor, "description": descricao}

    def get_subscription(self, subscription_id: str):
        self.gets += 1
        return None  # remoto ainda não reflete o alvo

    def create_checkout(self, **kwargs):  # pragma: no cover - defesa
        raise AssertionError("troca de plano nunca cria assinatura")

    def create_one_time_charge(self, **kwargs):  # pragma: no cover - defesa
        raise AssertionError("troca de plano nunca emite cobrança")


def _race_client(app):
    planos = [
        _plano(codigo="ate_100", preco_mensal=99.0, limite_pessoas=100),
        _plano(codigo="101_200", preco_mensal=299.0, limite_pessoas=200),
        _plano(codigo="acima_201", preco_mensal=499.0, limite_pessoas=None),
    ]
    sub = _active_sub(plano="ate_100", limite=100, pessoas=50)
    asaas = _FlakyChangePlanAsaas()
    client, db = _client(app, planos=planos, asaas=asaas, subscription=sub)
    db.pessoas_count = 50
    return client, db, sub, asaas


def test_change_plan_retry_reconciles_even_after_headcount_passed_the_limit(
    app,
) -> None:
    # Item 4: o retry do MESMO alvo não pode ser barrado pela guarda de porte —
    # o PUT pode já ter sido aplicado remotamente antes do timeout, e barrar
    # aqui prenderia a operação (e o slot único) para sempre.
    client, db, sub, asaas = _race_client(app)

    primeira = client.post(
        "/subscription/change-plan", json={"plano": "101_200"}, headers=_AUTH
    )
    assert primeira.status_code == 502  # ambíguo: plano local intacto
    assert sub.plano == "ate_100"
    op = next(o for o in db.added if isinstance(o, BillingPlanChangeOperation))
    assert op.status == "reconciling"

    # A igreja cresce ALÉM do limite do plano-alvo enquanto a operação está
    # presa. O retry do mesmo alvo segue reconciliando.
    db.pessoas_count = 250

    segunda = client.post(
        "/subscription/change-plan", json={"plano": "101_200"}, headers=_AUTH
    )

    assert segunda.status_code == 200  # nada de 422 na reconciliação
    assert asaas.gets == 1  # reconcilia ANTES de reescrever
    assert len(asaas.puts) == 2  # exatamente um PUT por tentativa
    assert op.status == "completed"
    assert sub.plano == "101_200"
    assert sub.limite == 200


def test_change_plan_queues_autoupgrade_when_headcount_grew_during_change(
    app,
) -> None:
    # Item 6 (a corrida COMPLETA): porte compatível no início, PUT ambíguo,
    # porte alterado no banco, retry reconcilia o mesmo alvo, releitura
    # canônica detecta o excesso e o auto-upgrade é ENFILEIRADO — sem nenhum
    # POST (o fake explode) e sem depender de uma futura mutação de pessoas.
    client, db, sub, asaas = _race_client(app)

    assert (
        client.post(
            "/subscription/change-plan", json={"plano": "101_200"}, headers=_AUTH
        ).status_code
        == 502
    )
    db.pessoas_count = 250  # cresceu durante o PUT; o espelho segue em 50
    assert sub.pessoas == 50

    resp = client.post(
        "/subscription/change-plan", json={"plano": "101_200"}, headers=_AUTH
    )
    assert resp.status_code == 200
    assert sub.plano == "101_200"
    assert sub.limite == 200

    # O caminho de enfileiramento FOI alcançado: nova operação durável para o
    # próximo degrau, aberta, do trilho de auto-upgrade.
    operacoes = [o for o in db.added if isinstance(o, BillingPlanChangeOperation)]
    assert len(operacoes) == 2
    enfileirada = operacoes[-1]
    assert enfileirada.to_plano == "acima_201"
    assert enfileirada.origin == "autoupgrade"
    assert enfileirada.status == "prepared"
    assert enfileirada.notify_status == "pending"
    assert float(enfileirada.to_preco) == 499.0
    # Nada além dos dois PUTs da própria troca aconteceu no Asaas.
    assert len(asaas.puts) == 2


# ---------------------------------------------------------------------------
# REVIEW-10 P1: a intenção de criação com POST AMBÍGUO precisa ser reconciliada
# ANTES de exigir plano ativo — senão o master desativar o plano no intervalo
# deixa a assinatura remota cobrando com o registro local não rastreado (e não
# existe worker que reconcilie criações).
# ---------------------------------------------------------------------------
def test_reconciles_open_intent_even_after_the_master_deactivates_the_plan(
    app,
) -> None:
    plano = _plano()
    asaas = _LostResponseAsaas()
    client, db = _client(app, planos=[plano], asaas=asaas)

    # 1) POST aceito remotamente, resposta perdida => operação em reconciling.
    assert client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    ).status_code == 502
    op = next(o for o in db.added if isinstance(o, BillingSubscriptionOperation))
    assert op.status == "reconciling"
    assert op.limite == 100  # limite CONGELADO junto do preço

    # 2) O master desativa o plano ANTES do retry do tenant.
    plano.ativo = False

    # 3) Retry do mesmo plano: localiza pelo externalReference, valida o alvo
    #    congelado e adota a MESMA assinatura — zero segundo POST, zero 422.
    _adopt_created_sub(db)
    asaas.found = [{
        "id": "sub_asaas_9",
        "customer": "cus_1",
        "value": 199.0,
        "cycle": "MONTHLY",
        "description": "PastorAI — plano ate_100",
    }]
    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert asaas.create_calls == 1  # nenhum POST /subscriptions novo
    assert op.status == "created"
    created_sub = next(o for o in db.added if isinstance(o, Subscription))
    assert created_sub.asaas_subscription_id == "sub_asaas_9"
    assert created_sub.plano == "ate_100"
    assert created_sub.limite == 100


def test_deactivated_plan_without_open_intent_still_returns_422(app) -> None:
    # Contraprova: sem nada a reconciliar, uma contratação NOVA continua
    # exigindo plano ativo — e não toca o Asaas.
    class _NoCallAsaasCheckout:
        def __getattr__(self, name):  # pragma: no cover - defesa
            raise AssertionError(f"plano inativo nao pode chamar o Asaas ({name})")

    client, db = _client(
        app,
        planos=[_plano(ativo=False)],
        asaas=_NoCallAsaasCheckout(),
    )

    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 422
    assert not [o for o in db.added if isinstance(o, BillingSubscriptionOperation)]


def test_adoption_rejects_catalog_changed_after_the_frozen_intent(app) -> None:
    # O master editou preço e limite DEPOIS da intenção: a adoção automática
    # falha localmente. O remoto pode existir com o contrato antigo, mas essa
    # divergência exige reconciliação manual e nenhum GET é autorizado.
    plano = _plano()
    asaas = _LostResponseAsaas()
    client, db = _client(app, planos=[plano], asaas=asaas)

    assert client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    ).status_code == 502
    op = next(o for o in db.added if isinstance(o, BillingSubscriptionOperation))
    assert float(op.valor) == 199.0
    assert op.limite == 100

    plano.preco_mensal = 999
    plano.limite_pessoas = 5

    _adopt_created_sub(db)
    created_sub = next(o for o in db.added if isinstance(o, Subscription))
    op_before = (op.status, op.asaas_subscription_id, op.attempt_started_at)
    sub_before = (
        created_sub.plano,
        created_sub.limite,
        created_sub.status,
        created_sub.asaas_subscription_id,
        created_sub.asaas_customer_id,
    )
    commits_before = db.commits
    asaas.found = [{
        "id": "sub_asaas_9",
        "customer": "cus_1",
        "value": 199.0,  # o remoto reflete o valor CONGELADO
        "cycle": "MONTHLY",
        "description": "PastorAI — plano ate_100",
    }]
    resp = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 409
    assert asaas.find_calls == 0
    assert asaas.create_calls == 1  # só o POST inicial, nunca um segundo
    assert (op.status, op.asaas_subscription_id, op.attempt_started_at) == op_before
    assert (
        created_sub.plano,
        created_sub.limite,
        created_sub.status,
        created_sub.asaas_subscription_id,
        created_sub.asaas_customer_id,
    ) == sub_before
    assert db.commits == commits_before


# ---------------------------------------------------------------------------
# REVIEW-10 P2: intenção `prepared` (comprovadamente sem POST) não pode prender
# o assinante em 409 quando ele escolhe outro plano.
# ---------------------------------------------------------------------------
class _RejectingThenTrackingAsaas:
    """1o checkout rejeitado (4xx definitivo); o seguinte cria de verdade."""

    def __init__(self) -> None:
        self.create_calls: list[str] = []
        self.values: list[float] = []

    def create_checkout(self, **kwargs):
        self.create_calls.append(kwargs["plano"])
        self.values.append(kwargs["valor"])
        kwargs["on_customer_resolved"]("cus_1")
        if len(self.create_calls) == 1:
            raise AsaasRejectedError("O Asaas rejeitou os dados do checkout")
        kwargs["on_subscription_created"]("cus_1", "sub_asaas_2")
        return CheckoutResult(
            customer_id="cus_1",
            subscription_id="sub_asaas_2",
            invoice_url="https://asaas.test/m1",
            status="pendente",
            invoice_payment_id="pay_m1",
        )


def test_prepared_intent_is_superseded_when_the_user_picks_another_plan(
    app,
) -> None:
    asaas = _RejectingThenTrackingAsaas()
    planos = [
        _plano(),
        _plano(codigo="101_200", preco_mensal=299, limite_pessoas=200),
    ]
    client, db = _client(app, planos=planos, asaas=asaas)

    # 1) Rejeição definitiva: a intenção volta a `prepared` (nada foi criado).
    assert client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    ).status_code == 502
    antiga = next(o for o in db.added if isinstance(o, BillingSubscriptionOperation))
    assert antiga.status == "prepared"

    # 2) O assinante escolhe OUTRO plano: a antiga fecha como terminal com o
    #    motivo e uma intenção nova nasce para o novo alvo.
    _adopt_created_sub(db)
    resp = client.post(
        "/subscription", json={"plano": "101_200", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert antiga.status == "superseded"
    assert "101_200" in (antiga.error or "")
    intencoes = [
        o for o in db.added if isinstance(o, BillingSubscriptionOperation)
    ]
    assert len(intencoes) == 2
    nova = intencoes[-1]
    assert nova.plano == "101_200"
    assert nova.status == "created"
    assert nova.limite == 200
    # Somente UM POST por alvo (o primeiro foi rejeitado sem criar nada).
    assert asaas.create_calls == ["ate_100", "101_200"]


def test_prepared_retry_rejects_catalog_edit_before_any_new_post(
    app,
) -> None:
    asaas = _RejectingThenTrackingAsaas()
    plano = _plano(preco_mensal=199, limite_pessoas=100)
    client, db = _client(app, planos=[plano], asaas=asaas)

    first = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )
    assert first.status_code == 502
    op = next(o for o in db.added if isinstance(o, BillingSubscriptionOperation))
    assert op.status == "prepared"
    assert op.limite == 100
    _adopt_created_sub(db)
    sub = db.subscription
    op_before = (
        op.status,
        op.valor,
        op.limite,
        op.attempt_started_at,
        op.error,
    )
    sub_before = (
        sub.plano,
        sub.status,
        sub.asaas_customer_id,
        sub.asaas_subscription_id,
    )
    commits_before = db.commits

    plano.preco_mensal = 999
    plano.limite_pessoas = 5
    second = client.post(
        "/subscription", json={"plano": "ate_100", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert second.status_code == 409
    assert asaas.values == [199.0]
    assert (
        op.status,
        op.valor,
        op.limite,
        op.attempt_started_at,
        op.error,
    ) == op_before
    assert (
        sub.plano,
        sub.status,
        sub.asaas_customer_id,
        sub.asaas_subscription_id,
    ) == sub_before
    assert db.commits == commits_before


def test_ambiguous_intent_for_another_plan_still_conflicts(app) -> None:
    # `creating`/`reconciling` podem ter criado a assinatura remotamente: trocar
    # de alvo abandonaria uma recorrência viva — segue 409, sem POST.
    class _NoCheckoutAsaas:
        def create_checkout(self, **kwargs):  # pragma: no cover - defesa
            raise AssertionError("conflito nunca posta assinatura")

        def find_subscriptions_by_external_reference(self, ref):  # pragma: no cover
            raise AssertionError("conflito nunca reconcilia outro alvo")

    ambigua = BillingSubscriptionOperation(
        subscription_id="00000000-0000-0000-0000-00000000su01",
        operation_key="pastorai-subcreate-amb",
        plano="ate_100",
        valor=199.0,
        limite=100,
        descricao="PastorAI - plano ate_100",
        status="reconciling",
    )
    sub = _subscription(status=None, asaas_subscription_id=None, setup_pago=False)
    client, _db = _client(
        app,
        planos=[
            _plano(),
            _plano(codigo="101_200", preco_mensal=299, limite_pessoas=200),
        ],
        asaas=_NoCheckoutAsaas(),
        subscription=sub,
        subscription_ops=[ambigua],
    )

    resp = client.post(
        "/subscription", json={"plano": "101_200", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 409
    assert "ate_100" in resp.json()["detail"]
    assert ambigua.status == "reconciling"  # intocada
