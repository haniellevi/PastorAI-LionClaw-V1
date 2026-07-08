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
            setup_charge_id=None,
            invoice_url="https://asaas.test/invoice",
            status="pendente",
        )


def _client(app, *, planos, asaas: _FakeAsaas | None = None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: FakeSession(
        app_user=make_app_user(), roles=["admin"], planos=planos
    )
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    app.dependency_overrides[get_asaas_client] = lambda: asaas or _FakeAsaas()
    return TestClient(app)


def test_checkout_charges_price_from_planos_table(app) -> None:
    # Master editou o preço pra 249 (era 199 hardcoded em domain/billing.py) —
    # o checkout tem que cobrar o valor do catálogo, não um valor fixo.
    asaas = _FakeAsaas()
    client = _client(
        app, planos=[_plano(preco_mensal=249, limite_pessoas=150)], asaas=asaas
    )
    resp = client.post("/subscription", json={"plano": "ate_100"}, headers=_AUTH)
    assert resp.status_code == 200
    assert asaas.calls[0]["valor"] == 249.0


def test_checkout_rejects_plano_desconhecido(app) -> None:
    client = _client(app, planos=[])
    resp = client.post("/subscription", json={"plano": "nao_existe"}, headers=_AUTH)
    assert resp.status_code == 422


def test_checkout_rejects_plano_inativo(app) -> None:
    # Master desativou o plano — tenant não consegue mais contratá-lo do zero
    # (grandfathering só protege quem já está nele).
    client = _client(app, planos=[_plano(ativo=False)])
    resp = client.post("/subscription", json={"plano": "ate_100"}, headers=_AUTH)
    assert resp.status_code == 422


def test_list_planos_returns_active_catalog_and_setup_fee(app) -> None:
    client = _client(app, planos=[_plano(preco_mensal=249, limite_pessoas=150)])
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
    assert "setupFee" in body


def test_list_planos_omits_inactive(app) -> None:
    client = _client(app, planos=[_plano(ativo=False)])
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
