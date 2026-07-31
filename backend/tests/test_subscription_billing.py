"""POST /subscription e GET /subscription/planos usam o catálogo `planos`
(migration 0012, editado pelo master em /admin/planos) como fonte de preço e
limite — não mais os dicts hardcoded que existiam em app/domain/billing.py.
"""

from __future__ import annotations

from types import SimpleNamespace

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

    def create_checkout(self, **kwargs):
        self.calls.append(kwargs)
        return CheckoutResult(
            customer_id="cus_1",
            subscription_id="sub_1",
            setup_charge_id="pay_setup_1" if kwargs["setup_fee"] > 0 else None,
            invoice_url="https://asaas.test/monthly",
            setup_invoice_url=(
                "https://asaas.test/setup" if kwargs["setup_fee"] > 0 else None
            ),
            status="pendente",
            invoice_payment_id="pay_m1",
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
    assert asaas.calls[0]["setup_fee"] == 59.9
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
    assert asaas.calls[0]["setup_fee"] == 19.9


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
    assert asaas.calls[0]["setup_fee"] == 0.0
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
