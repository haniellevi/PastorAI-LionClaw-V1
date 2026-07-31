"""Corpo real do webhook Asaas (BILLING-GATE-1): transições de status.

Bug corrigido: todo status não-"ativa" — inclusive a fatura mensal recém
criada (PAYMENT_CREATED / payment.status=PENDING) — derrubava igreja.status
para "inadimplente", bloqueando o acesso (deps.BLOCKING_IGREJA_STATUSES) de
igreja adimplente a cada ciclo de cobrança. Agora igreja.status só faz as
transições FINANCEIRAS: pagamento confirmado tira de "inadimplente" e
vencimento explícito (mapeado em _STATUS_MAP) tira de "ativa". "pendente" e
os estados administrativos do console master ("suspensa",
"aguardando_aprovacao") preservam igreja.status sempre.

Nenhum teste toca rede ou Asaas real: o handler do webhook só usa o DB
(fake abaixo) e o token compartilhado via settings (monkeypatch).
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Update

from app.config import get_settings
from app.db.session import get_db

_IGREJA_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_TOKEN = "whsec-test"
_HDR = {"asaas-access-token": _TOKEN}


def _sub(**over):
    base = dict(
        igreja_id=_IGREJA_ID,
        plano="ate_100",
        status="ativa",
        setup_pago=True,
        asaas_subscription_id="sub_asaas_1",
        asaas_setup_charge_id=None,
        asaas_invoice_payment_id=None,
        asaas_invoice_url=None,
        asaas_setup_invoice_url=None,
        proxima_cobranca=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _igreja(status: str = "ativa"):
    return SimpleNamespace(id=_IGREJA_ID, status=status)


class _Result:
    def __init__(self, scalar) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _WebhookDb:
    """Fake mínimo do que o handler do webhook toca: 2 selects, get, commit.

    Roteia os selects de Subscription pelos bind params compilados
    (igreja_id / asaas_subscription_id) e compara com o sub configurado —
    o texto do SQL não serve de discriminador porque o projection lista
    `subscriptions.igreja_id` em ambas as queries.
    """

    def __init__(self, sub=None, igreja=None) -> None:
        self.sub = sub
        self.igreja = igreja
        self.commits = 0

    def execute(self, statement, params=None) -> _Result:
        bound = statement.compile().params
        if isinstance(statement, Update):
            # UPDATE condicional da igreja (P1 Codex): como no banco real, o
            # WHERE (id + status esperado) é avaliado contra o estado ATUAL do
            # registro no momento do UPDATE — casa, aplica; não casa, 0 linhas.
            if (
                self.igreja is not None
                and str(bound.get("id_1")) == str(self.igreja.id)
                and bound.get("status_1") == self.igreja.status
            ):
                self.igreja.status = bound["status"]
            return _Result(None)
        sub = self.sub
        if sub is not None:
            for key, value in bound.items():
                if key.startswith("asaas_setup_charge_id") and str(value) == str(
                    sub.asaas_setup_charge_id
                ):
                    return _Result(sub)
                if key.startswith("asaas_subscription_id") and str(value) == str(
                    sub.asaas_subscription_id
                ):
                    return _Result(sub)
                if key.startswith("igreja_id") and str(value) == str(sub.igreja_id):
                    return _Result(sub)
        return _Result(None)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


def _client(app, db: _WebhookDb, monkeypatch) -> TestClient:
    monkeypatch.setattr(get_settings(), "asaas_webhook_token", _TOKEN, raising=False)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _payment(
    status: str | None = None,
    external_ref: str | None = str(_IGREJA_ID),
    subscription: str | None = "sub_asaas_1",
    payment_id: str = "pay_1",
    due_date: str | None = None,
    invoice_url: str | None = None,
) -> dict:
    p: dict = {"id": payment_id}
    if status is not None:
        p["status"] = status
    if external_ref is not None:
        p["externalReference"] = external_ref
    if subscription is not None:
        p["subscription"] = subscription
    if due_date is not None:
        p["dueDate"] = due_date
    if invoice_url is not None:
        p["invoiceUrl"] = invoice_url
    return p


def _post(client: TestClient, event: str, payment: dict):
    return client.post(
        "/subscription/webhook",
        json={"event": event, "payment": payment},
        headers=_HDR,
    )


def test_payment_created_pending_preserva_igreja_ativa(app, monkeypatch) -> None:
    # Fatura mensal recém-criada NÃO pode derrubar igreja adimplente.
    db = _WebhookDb(sub=_sub(), igreja=_igreja("ativa"))
    client = _client(app, db, monkeypatch)
    resp = _post(client, "PAYMENT_CREATED", _payment(status="PENDING"))
    assert resp.status_code == 200
    assert resp.json() == {"received": True, "status": "pendente"}
    assert db.sub.status == "pendente"
    assert db.igreja.status == "ativa"  # antes do fix: "inadimplente"
    assert db.commits == 1


def test_pendente_nao_reativa_igreja_inadimplente(app, monkeypatch) -> None:
    # Preservar vale nos dois sentidos: cobrança pendente também não REativa.
    db = _WebhookDb(
        sub=_sub(status="inadimplente"), igreja=_igreja("inadimplente")
    )
    client = _client(app, db, monkeypatch)
    resp = _post(client, "PAYMENT_CREATED", _payment(status="PENDING"))
    assert resp.json()["status"] == "pendente"
    assert db.igreja.status == "inadimplente"


def test_payment_confirmed_ativa_igreja_sem_marcar_setup(app, monkeypatch) -> None:
    db = _WebhookDb(
        sub=_sub(status="pendente", setup_pago=False),
        igreja=_igreja("inadimplente"),
    )
    client = _client(app, db, monkeypatch)
    resp = _post(client, "PAYMENT_CONFIRMED", _payment(status="CONFIRMED"))
    assert resp.json() == {"received": True, "status": "ativa"}
    assert db.sub.status == "ativa"
    assert db.sub.setup_pago is False
    assert db.igreja.status == "ativa"
    assert db.commits == 1


def test_payment_received_ativa(app, monkeypatch) -> None:
    db = _WebhookDb(
        sub=_sub(status="pendente", setup_pago=False), igreja=_igreja("ativa")
    )
    client = _client(app, db, monkeypatch)
    resp = _post(client, "PAYMENT_RECEIVED", _payment(status="RECEIVED"))
    assert resp.json()["status"] == "ativa"
    assert db.sub.status == "ativa"
    assert db.sub.setup_pago is False
    assert db.igreja.status == "ativa"


def test_payment_overdue_torna_inadimplente(app, monkeypatch) -> None:
    db = _WebhookDb(sub=_sub(), igreja=_igreja("ativa"))
    client = _client(app, db, monkeypatch)
    resp = _post(client, "PAYMENT_OVERDUE", _payment(status="OVERDUE"))
    assert resp.json()["status"] == "inadimplente"
    assert db.sub.status == "inadimplente"
    assert db.igreja.status == "inadimplente"


def test_evento_desconhecido_ack_sem_mutacao(app, monkeypatch) -> None:
    db = _WebhookDb(sub=_sub(), igreja=_igreja("ativa"))
    client = _client(app, db, monkeypatch)
    resp = _post(
        client,
        "PAYMENT_CHARGEBACK_REQUESTED",
        _payment(status="CHARGEBACK_REQUESTED"),
    )
    assert resp.status_code == 200
    assert resp.json() == {"received": True, "status": None}
    assert db.sub.status == "ativa"
    assert db.igreja.status == "ativa"
    assert db.commits == 0


def test_external_ref_invalida_cai_no_fallback_por_subscription_id(
    app, monkeypatch
) -> None:
    db = _WebhookDb(
        sub=_sub(status="pendente", setup_pago=False), igreja=_igreja("ativa")
    )
    client = _client(app, db, monkeypatch)
    resp = _post(
        client,
        "PAYMENT_CONFIRMED",
        _payment(status="CONFIRMED", external_ref="nao-e-uuid"),
    )
    assert resp.json()["status"] == "ativa"
    assert db.sub.status == "ativa"


def test_external_ref_invalida_sem_fallback_nao_muta(app, monkeypatch) -> None:
    db = _WebhookDb(sub=_sub(), igreja=_igreja("ativa"))
    client = _client(app, db, monkeypatch)
    resp = _post(
        client,
        "PAYMENT_CONFIRMED",
        _payment(
            status="CONFIRMED", external_ref="nao-e-uuid", subscription="sub_outra"
        ),
    )
    assert resp.json() == {"received": True, "status": None}
    assert db.sub.status == "ativa"
    assert db.igreja.status == "ativa"
    assert db.commits == 0


def test_assinatura_desconhecida_ack_sem_mutacao(app, monkeypatch) -> None:
    db = _WebhookDb(sub=None, igreja=_igreja("ativa"))
    client = _client(app, db, monkeypatch)
    resp = _post(client, "PAYMENT_CONFIRMED", _payment(status="CONFIRMED"))
    assert resp.status_code == 200
    assert resp.json() == {"received": True, "status": None}
    assert db.igreja.status == "ativa"
    assert db.commits == 0


def test_repeticao_do_evento_e_idempotente(app, monkeypatch) -> None:
    db = _WebhookDb(
        sub=_sub(status="pendente", setup_pago=False), igreja=_igreja("ativa")
    )
    client = _client(app, db, monkeypatch)
    for _ in range(2):
        resp = _post(client, "PAYMENT_CONFIRMED", _payment(status="CONFIRMED"))
        assert resp.json()["status"] == "ativa"
    assert db.sub.status == "ativa"
    assert db.sub.setup_pago is False
    assert db.igreja.status == "ativa"
    assert db.commits == 2


def test_setup_confirmed_only_marks_the_tracked_setup_charge_paid(app, monkeypatch) -> None:
    db = _WebhookDb(
        sub=_sub(
            status="pendente",
            setup_pago=False,
            asaas_setup_charge_id="pay_setup_1",
        ),
        igreja=_igreja("aguardando_aprovacao"),
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="CONFIRMED", subscription=None)
    payment["id"] = "pay_setup_1"

    resp = _post(client, "PAYMENT_CONFIRMED", payment)

    assert resp.json() == {"received": True, "status": "ativa"}
    assert db.sub.setup_pago is True
    assert db.sub.status == "pendente"
    assert db.igreja.status == "aguardando_aprovacao"
    assert db.commits == 1


def test_pending_setup_payment_does_not_unlock_the_setup(app, monkeypatch) -> None:
    db = _WebhookDb(
        sub=_sub(setup_pago=False, asaas_setup_charge_id="pay_setup_1"),
        igreja=_igreja("ativa"),
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="PENDING", subscription=None)
    payment["id"] = "pay_setup_1"

    resp = _post(client, "PAYMENT_CREATED", payment)

    assert resp.json() == {"received": True, "status": "pendente"}
    assert db.sub.setup_pago is False
    assert db.sub.status == "ativa"
    assert db.igreja.status == "ativa"
    assert db.commits == 0


def test_untracked_one_time_payment_cannot_change_access(app, monkeypatch) -> None:
    db = _WebhookDb(
        sub=_sub(setup_pago=False, asaas_setup_charge_id="pay_setup_1"),
        igreja=_igreja("ativa"),
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="CONFIRMED", subscription=None)
    payment["id"] = "pay_untracked"

    resp = _post(client, "PAYMENT_CONFIRMED", payment)

    assert resp.json() == {"received": True, "status": None}
    assert db.sub.setup_pago is False
    assert db.sub.status == "ativa"
    assert db.igreja.status == "ativa"
    assert db.commits == 0


# ---------------------------------------------------------------------------
# Ciclo mensal (P1 Codex, PR#219 corretivo 2): cada fatura nova substitui id +
# link da anterior; evento atrasado de ciclo antigo nunca regride o corrente.
# ---------------------------------------------------------------------------
def test_second_monthly_invoice_replaces_url_and_payment_id(app, monkeypatch) -> None:
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            asaas_invoice_payment_id="pay_m1",
            asaas_invoice_url="https://asaas.test/m1",
            proxima_cobranca=dt.date(2026, 7, 1),
        ),
        igreja=_igreja("ativa"),
    )
    client = _client(app, db, monkeypatch)

    resp = _post(
        client,
        "PAYMENT_CREATED",
        _payment(
            status="PENDING",
            payment_id="pay_m2",
            due_date="2026-08-01",
            invoice_url="https://asaas.test/m2",
        ),
    )

    assert resp.json() == {"received": True, "status": "pendente"}
    assert db.sub.asaas_invoice_payment_id == "pay_m2"
    assert db.sub.asaas_invoice_url == "https://asaas.test/m2"
    assert str(db.sub.proxima_cobranca) == "2026-08-01"
    assert db.commits == 1


def test_monthly_payload_without_url_clears_the_stale_link(app, monkeypatch) -> None:
    # Asaas ainda não gerou o link da fatura nova: melhor link NENHUM do que o
    # link quitado do ciclo anterior (o GET recupera depois pelo payment id).
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            asaas_invoice_payment_id="pay_m1",
            asaas_invoice_url="https://asaas.test/m1",
            proxima_cobranca=dt.date(2026, 7, 1),
        ),
        igreja=_igreja("ativa"),
    )
    client = _client(app, db, monkeypatch)

    resp = _post(
        client,
        "PAYMENT_CREATED",
        _payment(status="PENDING", payment_id="pay_m2", due_date="2026-08-01"),
    )

    assert resp.json()["status"] == "pendente"
    assert db.sub.asaas_invoice_payment_id == "pay_m2"
    assert db.sub.asaas_invoice_url is None
    assert str(db.sub.proxima_cobranca) == "2026-08-01"


def test_late_event_from_previous_cycle_does_not_regress_the_newer_one(
    app, monkeypatch
) -> None:
    # Retry atrasado do PAYMENT_CREATED do ciclo 1 chega DEPOIS do ciclo 2:
    # dueDate menor que o rastreado => id/URL/data do ciclo 2 ficam intactos.
    db = _WebhookDb(
        sub=_sub(
            status="pendente",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_url="https://asaas.test/m2",
            proxima_cobranca=dt.date(2026, 8, 1),
        ),
        igreja=_igreja("ativa"),
    )
    client = _client(app, db, monkeypatch)

    resp = _post(
        client,
        "PAYMENT_CREATED",
        _payment(
            status="PENDING",
            payment_id="pay_m1",
            due_date="2026-07-01",
            invoice_url="https://asaas.test/m1",
        ),
    )

    assert resp.status_code == 200
    assert db.sub.asaas_invoice_payment_id == "pay_m2"
    assert db.sub.asaas_invoice_url == "https://asaas.test/m2"
    assert str(db.sub.proxima_cobranca) == "2026-08-01"


def test_repeated_payment_created_is_idempotent_and_fills_missing_url(
    app, monkeypatch
) -> None:
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            asaas_invoice_payment_id=None,
            asaas_invoice_url=None,
        ),
        igreja=_igreja("ativa"),
    )
    client = _client(app, db, monkeypatch)
    evento = _payment(
        status="PENDING",
        payment_id="pay_m2",
        due_date="2026-08-01",
        invoice_url="https://asaas.test/m2",
    )

    for _ in range(2):
        resp = _post(client, "PAYMENT_CREATED", evento)
        assert resp.json()["status"] == "pendente"
        assert db.sub.asaas_invoice_payment_id == "pay_m2"
        assert db.sub.asaas_invoice_url == "https://asaas.test/m2"
        assert str(db.sub.proxima_cobranca) == "2026-08-01"

    # Variante: retry do MESMO payment preenche a URL que faltava, sem trocar id.
    db.sub.asaas_invoice_url = None
    resp = _post(client, "PAYMENT_CREATED", evento)
    assert db.sub.asaas_invoice_payment_id == "pay_m2"
    assert db.sub.asaas_invoice_url == "https://asaas.test/m2"


def test_setup_charge_event_does_not_touch_monthly_link(app, monkeypatch) -> None:
    # A cobrança de setup segue um trilho separado: seu webhook nunca mexe no
    # id/link da mensalidade nem no status mensal.
    db = _WebhookDb(
        sub=_sub(
            status="pendente",
            setup_pago=False,
            asaas_setup_charge_id="pay_setup_1",
            asaas_invoice_payment_id="pay_m1",
            asaas_invoice_url="https://asaas.test/m1",
        ),
        igreja=_igreja("ativa"),
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="CONFIRMED", subscription=None, payment_id="pay_setup_1")

    resp = _post(client, "PAYMENT_CONFIRMED", payment)

    assert resp.json() == {"received": True, "status": "ativa"}
    assert db.sub.setup_pago is True
    assert db.sub.status == "pendente"  # mensal intocado
    assert db.sub.asaas_invoice_payment_id == "pay_m1"
    assert db.sub.asaas_invoice_url == "https://asaas.test/m1"


def test_pendente_apos_ativa_nao_derruba_igreja(app, monkeypatch) -> None:
    # Ciclo real: paga (ativa) → mês seguinte o Asaas emite a nova fatura.
    db = _WebhookDb(
        sub=_sub(status="pendente", setup_pago=False), igreja=_igreja("ativa")
    )
    client = _client(app, db, monkeypatch)
    _post(client, "PAYMENT_CONFIRMED", _payment(status="CONFIRMED"))
    _post(client, "PAYMENT_CREATED", _payment(status="PENDING"))
    assert db.sub.status == "pendente"
    assert db.igreja.status == "ativa"


@pytest.mark.parametrize("estado_admin", ["suspensa", "aguardando_aprovacao"])
@pytest.mark.parametrize(
    ("event", "payment_status", "esperado_sub"),
    [
        ("PAYMENT_CONFIRMED", "CONFIRMED", "ativa"),
        ("PAYMENT_OVERDUE", "OVERDUE", "inadimplente"),
        ("PAYMENT_CREATED", "PENDING", "pendente"),
    ],
)
def test_estados_administrativos_sao_preservados(
    app, monkeypatch, estado_admin, event, payment_status, esperado_sub
) -> None:
    # "suspensa"/"aguardando_aprovacao" pertencem ao console master (a
    # aprovação também semeia permissões/AgentConfig) — o webhook financeiro
    # atualiza a assinatura, mas NUNCA sobrescreve esses estados da igreja.
    db = _WebhookDb(
        sub=_sub(status="pendente", setup_pago=False), igreja=_igreja(estado_admin)
    )
    client = _client(app, db, monkeypatch)
    resp = _post(client, event, _payment(status=payment_status))
    assert resp.status_code == 200
    assert resp.json()["status"] == esperado_sub
    assert db.sub.status == esperado_sub
    assert db.igreja.status == estado_admin


class _RacingDb(_WebhookDb):
    """Simula o console master comitando um estado administrativo DURANTE o
    request do webhook — depois da resolução da assinatura (primeiro select),
    antes do UPDATE da igreja. É a corrida do P1 do Codex: com read-check-write
    o webhook sobrescreveria; com UPDATE condicional o WHERE vê o estado novo
    e afeta zero linhas.
    """

    def __init__(self, sub, igreja, admin_status: str) -> None:
        super().__init__(sub=sub, igreja=igreja)
        self._admin_status: str | None = admin_status

    def execute(self, statement, params=None) -> _Result:
        result = super().execute(statement, params)
        if self._admin_status is not None and not isinstance(statement, Update):
            # "admin comitou" logo após o webhook resolver a assinatura.
            self.igreja.status = self._admin_status
            self._admin_status = None
        return result


@pytest.mark.parametrize("estado_admin", ["suspensa", "aguardando_aprovacao"])
@pytest.mark.parametrize(
    ("event", "payment_status", "estado_inicial", "esperado_sub"),
    [
        ("PAYMENT_CONFIRMED", "CONFIRMED", "inadimplente", "ativa"),
        ("PAYMENT_OVERDUE", "OVERDUE", "ativa", "inadimplente"),
    ],
)
def test_corrida_com_admin_durante_request_preserva_estado(
    app, monkeypatch, estado_admin, event, payment_status, estado_inicial, esperado_sub
) -> None:
    # A igreja começa num estado ELEGÍVEL para a transição (sem a corrida o
    # UPDATE aplicaria); o admin comita suspensa/aguardando_aprovacao no meio
    # do request e o UPDATE condicional precisa afetar zero linhas.
    db = _RacingDb(
        sub=_sub(status="pendente", setup_pago=False),
        igreja=_igreja(estado_inicial),
        admin_status=estado_admin,
    )
    client = _client(app, db, monkeypatch)
    resp = _post(client, event, _payment(status=payment_status))
    assert resp.status_code == 200
    assert db.igreja.status == estado_admin  # estado administrativo venceu
    assert db.sub.status == esperado_sub  # assinatura segue o financeiro
    assert db.commits == 1


def test_token_incorreto_rejeitado(app, monkeypatch) -> None:
    db = _WebhookDb(sub=_sub(), igreja=_igreja("ativa"))
    client = _client(app, db, monkeypatch)
    resp = client.post(
        "/subscription/webhook",
        json={"event": "PAYMENT_CONFIRMED", "payment": _payment(status="CONFIRMED")},
        headers={"asaas-access-token": "errado"},
    )
    assert resp.status_code == 401
    assert db.sub.status == "ativa"
    assert db.commits == 0


def test_token_ausente_rejeitado(app, monkeypatch) -> None:
    db = _WebhookDb(sub=_sub(), igreja=_igreja("ativa"))
    client = _client(app, db, monkeypatch)
    resp = client.post(
        "/subscription/webhook",
        json={"event": "PAYMENT_CONFIRMED", "payment": _payment(status="CONFIRMED")},
    )
    assert resp.status_code == 401
    assert db.commits == 0
