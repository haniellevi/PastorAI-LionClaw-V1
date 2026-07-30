"""POST /subscription e GET /subscription/planos usam o catálogo `planos`
(migration 0012, editado pelo master em /admin/planos) como fonte de preço e
limite — não mais os dicts hardcoded que existiam em app/domain/billing.py.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.services.asaas import CheckoutResult, get_asaas_client
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
        )


def _client(
    app,
    *,
    planos,
    asaas: _FakeAsaas | None = None,
    setup_fee_default: float = 0.0,
    setup_fee_override: float | None = None,
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
