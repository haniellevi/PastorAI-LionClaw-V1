"""POST /subscription e GET /subscription/planos usam o catálogo `planos`
(migration 0012, editado pelo master em /admin/planos) como fonte de preço e
limite — não mais os dicts hardcoded que existiam em app/domain/billing.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.services.asaas import AsaasError, CheckoutResult, get_asaas_client
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
        unavailable: bool = False,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self._monthly_url = monthly_url
        self._setup_url = setup_url
        self._payment_urls = payment_urls or {}
        self._unavailable = unavailable

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
) -> tuple[TestClient, FakeSession]:
    igreja = SimpleNamespace(
        id=make_app_user().igreja_id,
        setup_fee_override=setup_fee_override,
    )
    db = FakeSession(
        app_user=make_app_user(),
        roles=["admin"],
        planos=planos,
        igreja=igreja,
        billing_settings=SimpleNamespace(id=1, setup_fee_default=setup_fee_default),
        subscription=subscription,
        operations=operations,
        plan_changes=plan_changes,
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
    assert len(db.added) == 1
    assert db.added[0].limite == 150


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


# ---------------------------------------------------------------------------
# GET /subscription — links persistidos e recuperação read-only (PR#219 P2):
# a tela pendente reconstrói o painel de pagamento após reload; se um link se
# perdeu, o backend o recupera pelos ids Asaas já armazenados, sem NUNCA criar
# outra assinatura ou taxa de setup.
# ---------------------------------------------------------------------------
def test_get_subscription_returns_persisted_payment_links(app) -> None:
    asaas = _RecoveryAsaas()
    sub = _subscription(
        asaas_invoice_url="https://asaas.test/monthly",
        asaas_setup_invoice_url="https://asaas.test/setup",
    )
    client, db = _client(app, planos=[], asaas=asaas, subscription=sub)

    resp = client.get("/subscription", headers=_AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["invoiceUrl"] == "https://asaas.test/monthly"
    assert body["setupInvoiceUrl"] == "https://asaas.test/setup"
    assert asaas.calls == []  # nada a recuperar => nenhuma chamada externa


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
    assert asaas.calls == [("get_subscription_invoice_url", "sub_asaas_1")]
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
    assert asaas.calls == [("get_payment_invoice_url", "pay_m2")]
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
    assert asaas.calls == [("get_payment_invoice_url", "pay_setup_1")]
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
        ("get_subscription_invoice_url", "sub_asaas_1"),
        ("get_payment_invoice_url", "pay_setup_1"),
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
    assert asaas.calls == []


def test_get_subscription_recovers_overdue_url_by_current_payment_id(app) -> None:
    asaas = _RecoveryAsaas(payment_urls={"pay_m2": "https://asaas.test/m2-overdue"})
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
    assert asaas.calls == [("get_payment_invoice_url", "pay_m2")]
    assert db.commits == 1


class _TrackingFailAsaas:
    """create_checkout que rastreia a assinatura via callback e ENTÃO falha —
    simula lookup/setup quebrando depois do POST /subscriptions real."""

    def create_checkout(self, **kwargs):
        kwargs["on_subscription_created"]("cus_1", "sub_1")
        raise AsaasError("falha transitória depois da criação")


class _ResumeAsaas:
    """Fake do caminho de RETOMADA: proíbe recriar a assinatura."""

    def __init__(self, *, payment=None, charge=None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._payment = payment
        self._charge = charge

    def create_checkout(self, **kwargs):  # pragma: no cover - defesa do teste
        raise AssertionError("retomada nunca emite outro POST /subscriptions")

    def get_subscription_payment(self, subscription_id: str):
        self.calls.append(("get_subscription_payment", subscription_id))
        return self._payment

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
    assert len(db.added) == 1
    tracked = db.added[0]
    assert tracked.asaas_customer_id == "cus_1"
    assert tracked.asaas_subscription_id == "sub_1"
    assert tracked.status == "pendente"
    assert tracked.plano == "ate_100"
    assert db.commits >= 1  # rastreio comitado apesar do 502


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


def test_plan_change_still_creates_new_subscription(app) -> None:
    # Troca de plano (plano DIFERENTE do vinculado) segue o fluxo normal de
    # criação — a retomada vale só para retry do mesmo plano pendente.
    asaas = _FakeAsaas()
    sub = _subscription(status="pendente", plano="ate_100")
    client, _db = _client(
        app,
        planos=[_plano(codigo="101_200", preco_mensal=299, limite_pessoas=200)],
        asaas=asaas,
        subscription=sub,
    )

    resp = client.post(
        "/subscription", json={"plano": "101_200", "cpfCnpj": _CPF}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert len(asaas.calls) == 1  # create_checkout chamado (fluxo legítimo)
    assert asaas.calls[0]["plano"] == "101_200"


def test_get_subscription_withholds_reversed_invoice_link(app) -> None:
    # Cobrança mensal estornada/excluída: o GET não expõe nem tenta recuperar
    # o link dela — espera o próximo ciclo válido.
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
    assert asaas.calls == []  # recovery retido pelo motivo de reversão
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
    """Fake do fluxo refunded→cobrança avulsa de recuperação (via operação)."""

    def __init__(self) -> None:
        self.posts = 0

    def create_checkout(self, **kwargs):  # pragma: no cover - defesa
        raise AssertionError("recuperação nunca cria assinatura")

    def create_one_time_charge(self, **kwargs):
        self.posts += 1
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
    client, _db = _client(app, planos=[], asaas=asaas, subscription=sub)

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


def test_recover_invoice_rejects_when_not_reversed(app) -> None:
    sub = _subscription(status="pendente", asaas_invoice_reversal=None)
    client, _db = _client(app, planos=[], asaas=_RecoveryChargeAsaas(), subscription=sub)

    resp = client.post("/subscription/recover-invoice", headers=_AUTH)

    assert resp.status_code == 422


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
    assert body["invoiceReversal"] == "refunded"
    # Setup devido, sem link pagável e com assinatura criada => a UI oferece
    # "Gerar nova taxa de setup".
    assert body["setupRecoveryRequired"] is True


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
    assert asaas.calls == []


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
# AUTOUPGRADE-BILLING-WORKER-1: GET /subscription é leitura pura — nenhuma
# chamada externa nem notificação como efeito colateral. A sincronização do
# auto-upgrade (e sua notificação) pertence ao cron-worker.
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
