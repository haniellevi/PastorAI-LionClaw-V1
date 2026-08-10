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
from app.db.models import BillingPaymentOperation, BillingSubscriptionOperation
from app.db.session import get_db

_IGREJA_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_TOKEN = "whsec-test"
_HDR = {"asaas-access-token": _TOKEN}


def _sub(**over):
    base = dict(
        id="local-sub-1",
        igreja_id=_IGREJA_ID,
        plano="ate_100",
        status="ativa",
        setup_pago=True,
        asaas_customer_id="cus_1",
        asaas_subscription_id="sub_asaas_1",
        asaas_setup_charge_id=None,
        asaas_setup_reversed_payment_id=None,
        asaas_invoice_payment_id=None,
        asaas_invoice_url=None,
        asaas_invoice_reversal=None,
        asaas_setup_invoice_url=None,
        proxima_cobranca=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _igreja(status: str = "ativa", plano: str | None = "ate_100"):
    return SimpleNamespace(id=_IGREJA_ID, status=status, plano=plano)


def _plan(codigo: str = "ate_100"):
    return SimpleNamespace(
        codigo=codigo,
        nome=codigo,
        limite_pessoas=100,
        preco_mensal=199,
        ativo=True,
    )


class _Result:
    def __init__(self, scalar, scalars_list=None) -> None:
        self._scalar = scalar
        self._scalars_list = scalars_list or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(
            all=lambda: list(self._scalars_list),
            first=lambda: self._scalar,
        )


class _WebhookDb:
    """Fake mínimo do que o handler do webhook toca: 2 selects, get, commit.

    Roteia os selects de Subscription pelos bind params compilados
    (igreja_id / asaas_subscription_id) e compara com o sub configurado —
    o texto do SQL não serve de discriminador porque o projection lista
    `subscriptions.igreja_id` em ambas as queries.
    """

    def __init__(
        self,
        sub=None,
        igreja=None,
        legacy_candidates=None,
        operations=None,
        subscription_create_ops=None,
        plans=None,
    ) -> None:
        self.sub = sub
        self.igreja = igreja
        # Reconciliação de setup legado: assinaturas retornadas pelo select por
        # asaas_customer_id (o fake reaplica o WHERE real da query).
        self.legacy_candidates = legacy_candidates or []
        # Operações duráveis (setup / monthly_recovery) visíveis ao webhook.
        self.operations = operations or []
        # Intenções duráveis de criação de assinatura (externalReference nova).
        self.subscription_create_ops = subscription_create_ops or []
        self.plans = plans or [_plan()]
        self.commits = 0
        self.flushes = 0
        self.subscription_locks = 0
        self.lock_trace: list[str] = []
        self.before_subscription_lock = None

    def add(self, obj) -> None:
        self.operations.append(obj)

    def execute(self, statement, params=None) -> _Result:
        bound = statement.compile().params
        descriptions = getattr(statement, "column_descriptions", None)
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is BillingSubscriptionOperation:
            key = next(
                (v for k, v in bound.items() if k.startswith("operation_key")), None
            )
            match = next(
                (
                    o
                    for o in self.subscription_create_ops
                    if o.operation_key == str(key)
                ),
                None,
            )
            if (
                match is not None
                and getattr(statement, "_for_update_arg", None) is not None
            ):
                self.lock_trace.append("operation")
            return _Result(match)
        if any(key.startswith("source_payment_id") for key in bound):
            # find_settled_recovery: recovery PAGA que liquidou a fonte.
            src = next(
                value
                for key, value in bound.items()
                if key.startswith("source_payment_id")
            )
            statuses = [
                item
                for key, value in bound.items()
                if key.startswith("status") and not key.startswith("status_new")
                for item in (value if isinstance(value, (list, tuple)) else [value])
            ]
            match = next(
                (
                    o
                    for o in self.operations
                    if str(getattr(o, "source_payment_id", None)) == str(src)
                    and getattr(o, "purpose", None) == "monthly_recovery"
                    and (not statuses or o.status in statuses)
                ),
                None,
            )
            return _Result(match)
        if entity is BillingPaymentOperation and not any(
            key.startswith("asaas_payment_id") or key.startswith("operation_key")
            for key in bound
        ):
            # find_any_open_operation: pendência do propósito em qualquer
            # cobrança-fonte (usada somente como barreira financeira).
            purpose = next(
                (v for k, v in bound.items() if k.startswith("purpose")), None
            )
            statuses = [
                item
                for key, value in bound.items()
                if key.startswith("status")
                for item in (value if isinstance(value, (list, tuple)) else [value])
            ]
            match = next(
                (
                    o
                    for o in self.operations
                    if getattr(o, "purpose", None) == purpose
                    and (not statuses or o.status in statuses)
                ),
                None,
            )
            return _Result(match)
        # Operações duráveis: resolvidas por asaas_payment_id OU operation_key.
        for key, value in bound.items():
            if key.startswith("asaas_payment_id") or key.startswith("operation_key"):
                for op in self.operations:
                    if str(getattr(op, "asaas_payment_id", None)) == str(value) or str(
                        getattr(op, "operation_key", None)
                    ) == str(value):
                        if getattr(statement, "_for_update_arg", None) is not None:
                            self.lock_trace.append("operation")
                        return _Result(op)
                return _Result(None)
        # Subscription por id (dispatch do evento de operação).
        if not isinstance(statement, Update):
            sub_id = bound.get("id_1")
            candidates = [
                candidate
                for candidate in [self.sub, *self.legacy_candidates]
                if candidate is not None
            ]
            matched_sub = next(
                (
                    candidate
                    for candidate in candidates
                    if sub_id is not None
                    and str(sub_id) == str(getattr(candidate, "id", None))
                ),
                None,
            )
            if matched_sub is not None:
                if getattr(statement, "_for_update_arg", None) is not None:
                    self.subscription_locks += 1
                    self.lock_trace.append("subscription")
                    callback = self.before_subscription_lock
                    if callback is not None:
                        self.before_subscription_lock = None
                        callback(matched_sub)
                return _Result(matched_sub)
        if any(key.startswith("asaas_customer_id") for key in bound):
            if getattr(statement, "_for_update_arg", None) is not None:
                self.subscription_locks += 1
            customer = next(
                value for key, value in bound.items()
                if key.startswith("asaas_customer_id")
            )
            matches = [
                s
                for s in self.legacy_candidates
                if str(getattr(s, "asaas_customer_id", None)) == str(customer)
            ]
            return _Result(matches[0] if matches else None, scalars_list=matches)
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
                    if getattr(statement, "_for_update_arg", None) is not None:
                        self.subscription_locks += 1
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

    def flush(self) -> None:
        self.flushes += 1

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


def _client(app, db: _WebhookDb, monkeypatch) -> TestClient:
    from app.routers import subscription as subscription_router

    monkeypatch.setattr(get_settings(), "asaas_webhook_token", _TOKEN, raising=False)

    def lock_church(_session, igreja_id):
        db.lock_trace.append("church")
        if db.igreja is None or str(db.igreja.id) != str(igreja_id):
            return None
        return db.igreja

    def lock_plans(_session, *plan_codes):
        db.lock_trace.append("plans")
        requested = {str(code) for code in plan_codes if code}
        return {
            plan.codigo: plan
            for plan in db.plans
            if str(plan.codigo) in requested
        }

    monkeypatch.setattr(
        subscription_router, "lock_igreja_for_billing", lock_church
    )
    monkeypatch.setattr(
        subscription_router, "lock_plan_rows_for_billing", lock_plans
    )
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _payment(
    status: str | None = None,
    external_ref: str | None = str(_IGREJA_ID),
    subscription: str | None = "sub_asaas_1",
    payment_id: str = "pay_1",
    due_date: str | None = None,
    invoice_url: str | None = None,
    value: float | None = None,
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
    if value is not None:
        p["value"] = value
    return p


def _post(client: TestClient, event: str, payment: dict):
    return client.post(
        "/subscription/webhook",
        json={"event": event, "payment": payment},
        headers=_HDR,
    )


def test_authenticated_webhook_works_with_billing_write_gates_off(
    app, monkeypatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "allow_real_sends", False, raising=False)
    monkeypatch.setattr(settings, "asaas_billing_enabled", False, raising=False)
    db = _WebhookDb(sub=_sub(), igreja=_igreja("ativa"))
    client = _client(app, db, monkeypatch)

    resp = _post(client, "PAYMENT_CONFIRMED", _payment(status="CONFIRMED"))

    assert resp.status_code == 200
    assert resp.json() == {"received": True, "status": "ativa"}
    assert db.commits == 1


def test_monthly_webhook_locks_church_plans_then_subscription(
    app, monkeypatch
) -> None:
    db = _WebhookDb(sub=_sub(status="pendente"), igreja=_igreja("ativa"))
    client = _client(app, db, monkeypatch)

    response = _post(
        client,
        "PAYMENT_CONFIRMED",
        _payment(status="CONFIRMED", payment_id="pay_canonical"),
    )

    assert response.status_code == 200
    assert db.lock_trace[:3] == ["church", "plans", "subscription"]


def test_tracked_subscription_is_revalidated_after_canonical_locks(
    app, monkeypatch
) -> None:
    sub = _sub(status="pendente")
    db = _WebhookDb(sub=sub, igreja=_igreja("ativa"))
    db.before_subscription_lock = lambda locked: setattr(
        locked, "asaas_subscription_id", "sub_changed_while_waiting"
    )
    client = _client(app, db, monkeypatch)

    response = _post(
        client,
        "PAYMENT_CONFIRMED",
        _payment(status="CONFIRMED", payment_id="pay_revalidate"),
    )

    assert response.json() == {"received": True, "status": None}
    assert sub.status == "pendente"
    assert sub.asaas_invoice_payment_id is None
    assert db.igreja.status == "ativa"
    assert db.commits == 0
    assert db.lock_trace[:3] == ["church", "plans", "subscription"]


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
    assert db.subscription_locks == 1


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


# ---------------------------------------------------------------------------
# Veto de ciclo (P1 review 3): evento atrasado de fatura ANTIGA não muda nada —
# nem status, nem link, nem acesso da igreja, nem commit.
# ---------------------------------------------------------------------------
def test_old_overdue_after_new_cycle_confirmed_changes_nothing(app, monkeypatch) -> None:
    # Agosto (pay_m2) confirmado; OVERDUE atrasado de julho (pay_m1) chega
    # depois. Antes do fix: derrubava sub e igreja para "inadimplente".
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_url="https://asaas.test/m2",
            proxima_cobranca=dt.date(2026, 8, 1),
        ),
        igreja=_igreja("ativa"),
    )
    client = _client(app, db, monkeypatch)

    resp = _post(
        client,
        "PAYMENT_OVERDUE",
        _payment(
            status="OVERDUE",
            payment_id="pay_m1",
            due_date="2026-07-01",
            invoice_url="https://asaas.test/m1",
        ),
    )

    assert resp.json() == {"received": True, "status": None}
    assert db.sub.status == "ativa"
    assert db.igreja.status == "ativa"
    assert db.sub.asaas_invoice_payment_id == "pay_m2"
    assert db.sub.asaas_invoice_url == "https://asaas.test/m2"
    assert str(db.sub.proxima_cobranca) == "2026-08-01"
    assert db.commits == 0


@pytest.mark.parametrize(
    ("event", "raw_status"),
    [
        ("PAYMENT_REFUNDED", "REFUNDED"),
        ("PAYMENT_DELETED", "DELETED"),
    ],
)
def test_old_cycle_reversal_stages_debt_without_replacing_current_snapshot(
    app, monkeypatch, event, raw_status
) -> None:
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            asaas_invoice_payment_id="pay_b",
            asaas_invoice_url="https://asaas.test/b",
            asaas_invoice_reversal=None,
            proxima_cobranca=dt.date(2026, 9, 1),
        ),
        igreja=_igreja("ativa"),
    )
    client = _client(app, db, monkeypatch)

    resp = _post(
        client,
        event,
        _payment(
            status=raw_status,
            payment_id="pay_a",
            due_date="2026-08-01",
            value=199.0,
        ),
    )

    assert resp.json()["status"] == "inadimplente"
    debt_a = next(
        o
        for o in db.operations
        if getattr(o, "purpose", None) == "monthly_recovery"
    )
    assert debt_a.status == "prepared"
    assert debt_a.source_payment_id == "pay_a"
    assert float(debt_a.valor) == 199.0
    # B continua sendo a fotografia mensal autoritativa.
    assert db.sub.status == "ativa"
    assert db.sub.asaas_invoice_payment_id == "pay_b"
    assert db.sub.asaas_invoice_url == "https://asaas.test/b"
    assert db.sub.asaas_invoice_reversal is None
    assert db.sub.proxima_cobranca == dt.date(2026, 9, 1)
    assert db.igreja.status == "inadimplente"
    assert db.commits == 1


def test_old_cycle_reversal_already_settled_is_ignored(app, monkeypatch) -> None:
    settled_a = _operation(status="paid", source_payment_id="pay_a")
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            asaas_invoice_payment_id="pay_b",
            asaas_invoice_url="https://asaas.test/b",
            proxima_cobranca=dt.date(2026, 9, 1),
        ),
        igreja=_igreja("ativa"),
        operations=[settled_a],
    )
    client = _client(app, db, monkeypatch)

    resp = _post(
        client,
        "PAYMENT_REFUNDED",
        _payment(
            status="REFUNDED",
            payment_id="pay_a",
            due_date="2026-08-01",
            value=199.0,
        ),
    )

    assert resp.json()["status"] is None
    assert db.operations == [settled_a]
    assert db.sub.asaas_invoice_payment_id == "pay_b"
    assert db.igreja.status == "ativa"
    assert db.commits == 0


def test_different_payment_without_duedate_cannot_regress_tracked_cycle(
    app, monkeypatch
) -> None:
    # Sem dueDate não há como provar que o evento é mais novo — id diferente
    # do rastreado é ignorado por inteiro.
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
        "PAYMENT_OVERDUE",
        _payment(status="OVERDUE", payment_id="pay_mx"),
    )

    assert resp.json() == {"received": True, "status": None}
    assert db.sub.status == "pendente"
    assert db.igreja.status == "ativa"
    assert db.sub.asaas_invoice_payment_id == "pay_m2"
    assert db.commits == 0


def test_same_payment_id_still_transitions_status(app, monkeypatch) -> None:
    # O ciclo CORRENTE transita normalmente: confirmação do payment rastreado
    # ativa a assinatura e reativa a igreja inadimplente.
    db = _WebhookDb(
        sub=_sub(
            status="pendente",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_url="https://asaas.test/m2",
            proxima_cobranca=dt.date(2026, 8, 1),
        ),
        igreja=_igreja("inadimplente"),
    )
    client = _client(app, db, monkeypatch)

    resp = _post(
        client,
        "PAYMENT_CONFIRMED",
        _payment(status="CONFIRMED", payment_id="pay_m2", due_date="2026-08-01"),
    )

    assert resp.json() == {"received": True, "status": "ativa"}
    assert db.sub.status == "ativa"
    assert db.igreja.status == "ativa"
    assert db.commits == 1


# ---------------------------------------------------------------------------
# Setup legado (P2 review 3): checkout anterior à migration não tem charge id
# rastreado — a confirmação reconcilia por customer + descrição exata, e SÓ
# quando existe uma única candidata.
# ---------------------------------------------------------------------------
def _legacy_payment(**over) -> dict:
    p = {
        "id": "pay_leg_1",
        "status": "CONFIRMED",
        "customer": "cus_leg_1",
        "description": "PastorAI — taxa de setup",
    }
    p.update(over)
    return p


def _legacy_sub(**over):
    values = dict(
        status="pendente",
        setup_pago=False,
        asaas_setup_charge_id=None,
        asaas_customer_id="cus_leg_1",
    )
    values.update(over)
    return _sub(**values)


def test_legacy_setup_confirmation_marks_paid(app, monkeypatch) -> None:
    legada = _legacy_sub()
    db = _WebhookDb(sub=None, igreja=_igreja("ativa"), legacy_candidates=[legada])
    client = _client(app, db, monkeypatch)

    resp = _post(client, "PAYMENT_CONFIRMED", _legacy_payment())

    assert resp.json() == {"received": True, "status": "ativa"}
    assert legada.setup_pago is True
    assert legada.asaas_setup_charge_id == "pay_leg_1"  # persiste o id
    assert legada.status == "pendente"  # mensalidade intocada
    assert db.igreja.status == "ativa"  # acesso intocado
    assert db.commits == 1
    assert db.subscription_locks == 1


def test_legacy_setup_pending_event_does_not_mark_paid(app, monkeypatch) -> None:
    # Só CONFIRMAÇÃO reconcilia — fatura de setup recém-criada não.
    legada = _legacy_sub()
    db = _WebhookDb(sub=None, igreja=_igreja("ativa"), legacy_candidates=[legada])
    client = _client(app, db, monkeypatch)

    resp = _post(client, "PAYMENT_CREATED", _legacy_payment(status="PENDING"))

    assert resp.json() == {"received": True, "status": None}
    assert legada.setup_pago is False
    assert legada.asaas_setup_charge_id is None
    assert db.commits == 0


def test_delayed_legacy_confirmation_cannot_readopt_reversed_setup(
    app, monkeypatch
) -> None:
    legada = _legacy_sub(asaas_setup_reversed_payment_id="pay_leg_1")
    db = _WebhookDb(sub=None, igreja=_igreja("ativa"), legacy_candidates=[legada])
    client = _client(app, db, monkeypatch)

    resp = _post(client, "PAYMENT_CONFIRMED", _legacy_payment())

    assert resp.json() == {"received": True, "status": None}
    assert legada.setup_pago is False
    assert legada.asaas_setup_charge_id is None
    assert legada.asaas_setup_reversed_payment_id == "pay_leg_1"
    assert db.commits == 0


def test_legacy_reversal_before_confirmation_persists_tombstone(
    app, monkeypatch
) -> None:
    legada = _legacy_sub()
    db = _WebhookDb(sub=None, igreja=_igreja("ativa"), legacy_candidates=[legada])
    client = _client(app, db, monkeypatch)
    deleted = _legacy_payment(status="PENDING")
    deleted["deleted"] = True

    reversed_resp = _post(client, "PAYMENT_DELETED", deleted)

    assert reversed_resp.json()["status"] == "inadimplente"
    assert legada.setup_pago is False
    assert legada.asaas_setup_charge_id is None
    assert legada.asaas_setup_reversed_payment_id == "pay_leg_1"
    assert db.commits == 1
    assert db.subscription_locks == 1

    confirmed_resp = _post(client, "PAYMENT_CONFIRMED", _legacy_payment())
    assert confirmed_resp.json() == {"received": True, "status": None}
    assert legada.setup_pago is False
    assert legada.asaas_setup_charge_id is None
    assert db.commits == 1


def test_legacy_setup_rejects_wrong_description_missing_customer_or_ambiguity(
    app, monkeypatch
) -> None:
    for payload, candidatas in [
        # Descrição diferente da cobrança de setup oficial.
        (_legacy_payment(description="Outra cobrança"), [_legacy_sub()]),
        # Payload sem customer.
        ({k: v for k, v in _legacy_payment().items() if k != "customer"}, [_legacy_sub()]),
        # Payment novo tem externalReference; se a operação não casar, nunca
        # pode cair no fallback histórico sem identidade por igreja.
        (
            _legacy_payment(externalReference="pastorai-setup-outra-operacao"),
            [_legacy_sub()],
        ),
        # Duas candidatas com o mesmo customer: ambíguo, nada muda.
        (_legacy_payment(), [_legacy_sub(), _legacy_sub()]),
    ]:
        db = _WebhookDb(sub=None, igreja=_igreja("ativa"), legacy_candidates=candidatas)
        client = _client(app, db, monkeypatch)

        resp = _post(client, "PAYMENT_CONFIRMED", payload)

        assert resp.json() == {"received": True, "status": None}
        assert all(c.setup_pago is False for c in candidatas)
        assert all(c.asaas_setup_charge_id is None for c in candidatas)
        assert db.commits == 0


def test_legacy_setup_declines_customer_shared_by_multiple_churches(
    app, monkeypatch
) -> None:
    # O Asaas reutiliza customer por CPF/CNPJ. Mesmo que só B esteja com setup
    # aberto, o payment legado sem externalReference pode pertencer a A; o
    # customer compartilhado não autoriza mutar nenhuma das duas igrejas.
    igreja_a = _legacy_sub(
        id="sub-a",
        setup_pago=True,
        asaas_setup_charge_id="pay_setup_a_current",
    )
    igreja_b = _legacy_sub(id="sub-b")
    db = _WebhookDb(
        sub=None,
        igreja=_igreja("ativa"),
        legacy_candidates=[igreja_a, igreja_b],
    )
    client = _client(app, db, monkeypatch)

    resp = _post(
        client,
        "PAYMENT_CONFIRMED",
        _legacy_payment(id="pay_setup_a_legacy"),
    )

    assert resp.json() == {"received": True, "status": None}
    assert igreja_a.setup_pago is True
    assert igreja_a.asaas_setup_charge_id == "pay_setup_a_current"
    assert igreja_b.setup_pago is False
    assert igreja_b.asaas_setup_charge_id is None
    assert db.commits == 0


# ---------------------------------------------------------------------------
# Cobranças de OPERAÇÃO durável (setup / monthly_recovery): o propósito vem da
# operação — nunca do shape do payload.
# ---------------------------------------------------------------------------
def _operation(**over):
    base = dict(
        subscription_id="local-sub-1",
        purpose="monthly_recovery",
        operation_key="pastorai-monthly_recovery-op1",
        source_payment_id="pay_m2",
        asaas_payment_id="pay_rec_1",
        status="created",
        valor=199.0,
        invoice_url="https://asaas.test/recovery",
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_recovery_charge_confirmation_regularizes_access_not_setup(
    app, monkeypatch
) -> None:
    op = _operation()
    db = _WebhookDb(
        sub=_sub(
            status="inadimplente",
            setup_pago=False,  # setup segue devido — recovery NÃO o quita
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_url=None,
            asaas_invoice_reversal="refunded",
        ),
        igreja=_igreja("inadimplente"),
        operations=[op],
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="CONFIRMED", subscription=None, payment_id="pay_rec_1")
    payment["externalReference"] = op.operation_key

    for _ in range(2):  # evento repetido permanece idempotente
        resp = _post(client, "PAYMENT_CONFIRMED", payment)
        assert resp.json() == {"received": True, "status": "ativa"}
        assert op.status == "paid"
        assert db.sub.status == "ativa"
        assert db.sub.asaas_invoice_reversal is None  # dívida quitada
        assert db.igreja.status == "ativa"  # guarda atômica reativa a igreja
        assert db.sub.setup_pago is False  # recovery NUNCA é confundida com setup

    assert db.lock_trace[:4] == [
        "church",
        "plans",
        "operation",
        "subscription",
    ]


@pytest.mark.parametrize("conflicting_id", ["pay_duplicate", None])
def test_operation_key_cannot_rebind_a_different_payment(
    app, monkeypatch, conflicting_id
) -> None:
    op = _operation(
        asaas_payment_id="pay_rec_1",
        operation_key="pastorai-monthly_recovery-op1",
    )
    db = _WebhookDb(
        sub=_sub(
            status="inadimplente",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_reversal="refunded",
        ),
        igreja=_igreja("inadimplente"),
        operations=[op],
    )
    client = _client(app, db, monkeypatch)
    duplicate = _payment(
        status="CONFIRMED",
        subscription=None,
        payment_id=conflicting_id,
    )
    duplicate["externalReference"] = op.operation_key

    resp = _post(client, "PAYMENT_CONFIRMED", duplicate)

    assert resp.json() == {"received": True, "status": None}
    assert op.asaas_payment_id == "pay_rec_1"
    assert op.status == "created"
    assert db.sub.status == "inadimplente"
    assert db.sub.asaas_invoice_reversal == "refunded"
    assert db.igreja.status == "inadimplente"
    assert db.commits == 0


def test_recovery_charge_reversal_keeps_debt_without_link(app, monkeypatch) -> None:
    op = _operation()
    db = _WebhookDb(
        sub=_sub(
            status="inadimplente",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_url=None,
            asaas_invoice_reversal="refunded",
        ),
        igreja=_igreja("inadimplente"),
        operations=[op],
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="REFUNDED", subscription=None, payment_id="pay_rec_1")

    resp = _post(client, "PAYMENT_REFUNDED", payment)

    assert resp.status_code == 200
    assert op.status == "reversed"
    assert op.invoice_url is None  # link inválido não volta para a tela
    assert db.sub.status == "inadimplente"  # dívida permanece
    assert db.sub.asaas_invoice_reversal == "refunded"
    assert db.igreja.status == "inadimplente"


# ---------------------------------------------------------------------------
# REVIEW-10 P1: a recuperação só tem autoridade sobre a SUA cobrança-fonte.
# ---------------------------------------------------------------------------
def test_late_payment_of_an_older_recovery_never_settles_the_current_debt(
    app, monkeypatch
) -> None:
    # A recovery do ciclo A ficou em aberto; a assinatura avançou para a
    # cobrança B, que foi revertida. Pagar A tarde registra o resultado dela e
    # NADA MAIS: a dívida de B continua, a assinatura segue inadimplente e a
    # igreja não é reativada.
    op_a = _operation(
        operation_key="pastorai-monthly_recovery-a",
        source_payment_id="pay_m1",  # ciclo ANTIGO
        asaas_payment_id="pay_rec_a",
    )
    db = _WebhookDb(
        sub=_sub(
            status="inadimplente",
            asaas_invoice_payment_id="pay_m2",  # ciclo CORRENTE
            asaas_invoice_url=None,
            asaas_invoice_reversal="refunded",
        ),
        igreja=_igreja("inadimplente"),
        operations=[op_a],
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="CONFIRMED", subscription=None, payment_id="pay_rec_a")

    for _ in range(2):  # repetição permanece idempotente
        resp = _post(client, "PAYMENT_CONFIRMED", payment)
        assert resp.status_code == 200
        assert op_a.status == "paid"  # resultado histórico da própria operação
        assert db.sub.asaas_invoice_reversal == "refunded"  # dívida de B intacta
        assert db.sub.status == "inadimplente"
        assert db.igreja.status == "inadimplente"


def test_payment_of_the_current_source_recovery_settles_and_reactivates(
    app, monkeypatch
) -> None:
    # Contraprova do teste acima: a recovery da fonte CORRENTE quita a dívida,
    # reativa a assinatura e o gate da igreja.
    op_b = _operation(
        operation_key="pastorai-monthly_recovery-b",
        source_payment_id="pay_m2",
        asaas_payment_id="pay_rec_b",
    )
    db = _WebhookDb(
        sub=_sub(
            status="inadimplente",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_url=None,
            asaas_invoice_reversal="refunded",
        ),
        igreja=_igreja("inadimplente"),
        operations=[op_b],
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="CONFIRMED", subscription=None, payment_id="pay_rec_b")

    resp = _post(client, "PAYMENT_CONFIRMED", payment)

    assert resp.status_code == 200
    assert op_b.status == "paid"
    assert db.sub.asaas_invoice_reversal is None
    assert db.sub.status == "ativa"
    assert db.igreja.status == "ativa"
    assert db.flushes == 1  # autoflush=False: quitação foi ao DB antes do probe
    assert db.subscription_locks == 1


def test_reversal_of_an_older_recovery_reopens_its_debt_without_rewriting_current_cycle(
    app, monkeypatch
) -> None:
    # Simetria: o estorno de uma recovery paga de ciclo antigo reabre só a
    # cobrança-fonte dela — nunca derruba um ciclo corrente já regularizado.
    op_a = _operation(
        operation_key="pastorai-monthly_recovery-a",
        source_payment_id="pay_m1",
        asaas_payment_id="pay_rec_a",
        status="paid",
    )
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            asaas_invoice_payment_id="pay_m2",  # ciclo corrente, regular
            asaas_invoice_reversal=None,
        ),
        igreja=_igreja("ativa"),
        operations=[op_a],
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="REFUNDED", subscription=None, payment_id="pay_rec_a")

    resp = _post(client, "PAYMENT_REFUNDED", payment)

    assert resp.status_code == 200
    assert op_a.status == "reversed"
    assert db.sub.status == "ativa"
    assert db.sub.asaas_invoice_reversal is None
    assert db.igreja.status == "inadimplente"
    replacement = [o for o in db.operations if o is not op_a]
    assert len(replacement) == 1
    assert replacement[0].status == "prepared"
    assert replacement[0].source_payment_id == "pay_m1"
    assert replacement[0].valor == op_a.valor


def test_setup_operation_resolved_by_operation_key_marks_paid(app, monkeypatch) -> None:
    # Webhook chega ANTES da nossa reconciliação (op ainda sem payment id):
    # a operação é resolvida pela operation_key na externalReference.
    op = _operation(
        purpose="setup",
        operation_key="pastorai-setup-op9",
        asaas_payment_id=None,
        status="creating",
        valor=59.9,
        invoice_url=None,
        source_payment_id=None,
    )
    db = _WebhookDb(
        sub=_sub(
            status="pendente",
            setup_pago=False,
            asaas_customer_id="cus_1",
        ),
        igreja=_igreja("aguardando_aprovacao"),
        operations=[op],
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="CONFIRMED", subscription=None, payment_id="pay_setup_9")
    payment["externalReference"] = "pastorai-setup-op9"
    payment["value"] = 59.9
    payment["description"] = "PastorAI — taxa de setup"
    payment["customer"] = "cus_1"

    resp = _post(client, "PAYMENT_CONFIRMED", payment)

    assert resp.json() == {"received": True, "status": "ativa"}
    assert op.asaas_payment_id == "pay_setup_9"  # vínculo adotado do webhook
    assert op.status == "paid"
    assert db.sub.setup_pago is True
    assert db.sub.status == "pendente"  # mensalidade intocada
    assert db.igreja.status == "aguardando_aprovacao"  # acesso intocado


@pytest.mark.parametrize(
    ("field", "conflicting"),
    [
        ("value", 10.0),
        ("description", "Outra cobrança"),
        ("customer", "cus_2"),
        ("customer", None),
    ],
)
def test_unbound_payment_operation_rejects_conflicting_snapshot(
    app, monkeypatch, field, conflicting
) -> None:
    op = _operation(
        purpose="setup",
        operation_key="pastorai-setup-unbound",
        asaas_payment_id=None,
        status="creating",
        valor=59.9,
        invoice_url=None,
        source_payment_id=None,
    )
    db = _WebhookDb(
        sub=_sub(
            status="pendente",
            setup_pago=False,
            asaas_customer_id="cus_1",
        ),
        igreja=_igreja("aguardando_aprovacao"),
        operations=[op],
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(
        status="CONFIRMED",
        subscription=None,
        payment_id="pay_conflicting",
        value=59.9,
    )
    payment.update(
        {
            "externalReference": op.operation_key,
            "description": "PastorAI — taxa de setup",
            "customer": "cus_1",
            field: conflicting,
        }
    )

    resp = _post(client, "PAYMENT_CONFIRMED", payment)

    assert resp.json() == {"received": True, "status": None}
    assert op.asaas_payment_id is None
    assert op.status == "creating"
    assert db.sub.setup_pago is False
    assert db.sub.status == "pendente"
    assert db.igreja.status == "aguardando_aprovacao"
    assert db.commits == 0


# ---------------------------------------------------------------------------
# Reversões (review 4): estorno/exclusão difere de atraso — a cobrança deixa
# de existir para pagamento.
# ---------------------------------------------------------------------------
def test_setup_refund_reopens_the_pending_setup(app, monkeypatch) -> None:
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            setup_pago=True,
            asaas_setup_charge_id="pay_setup_1",
            asaas_setup_invoice_url="https://asaas.test/setup",
        ),
        igreja=_igreja("ativa"),
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="REFUNDED", subscription=None, payment_id="pay_setup_1")

    resp = _post(client, "PAYMENT_REFUNDED", payment)

    assert resp.status_code == 200
    assert db.sub.setup_pago is False  # pendência reaberta
    assert db.sub.asaas_setup_charge_id is None  # cobrança revertida morre
    assert db.sub.asaas_setup_invoice_url is None  # link inutilizável some
    assert db.sub.status == "ativa"  # mensalidade intocada
    assert db.igreja.status == "ativa"  # acesso intocado
    assert db.commits == 1
    assert db.subscription_locks == 1


def test_setup_delete_clears_the_dead_charge_even_if_unpaid(app, monkeypatch) -> None:
    db = _WebhookDb(
        sub=_sub(
            status="pendente",
            setup_pago=False,
            asaas_setup_charge_id="pay_setup_1",
            asaas_setup_invoice_url="https://asaas.test/setup",
        ),
        igreja=_igreja("ativa"),
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="PENDING", subscription=None, payment_id="pay_setup_1")
    payment["deleted"] = True

    resp = _post(client, "PAYMENT_DELETED", payment)

    assert resp.status_code == 200
    assert db.sub.setup_pago is False
    assert db.sub.asaas_setup_charge_id is None
    assert db.sub.asaas_setup_invoice_url is None
    # Próximo checkout volta a criar (e cobrar) a taxa: nada ficou "pago".


def test_monthly_delete_event_overrides_pending_payment_status(app, monkeypatch) -> None:
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_url="https://asaas.test/m2",
        ),
        igreja=_igreja("ativa"),
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(
        status="PENDING",
        payment_id="pay_m2",
        invoice_url="https://asaas.test/m2",
        value=199.0,
    )
    payment["deleted"] = True

    resp = _post(client, "PAYMENT_DELETED", payment)

    assert resp.json()["status"] == "inadimplente"
    assert db.sub.status == "inadimplente"
    assert db.sub.asaas_invoice_reversal == "deleted"
    assert db.igreja.status == "inadimplente"
    recovery = next(
        op for op in db.operations if op.purpose == "monthly_recovery"
    )
    assert recovery.source_payment_id == "pay_m2"
    assert recovery.status == "prepared"


def test_monthly_refund_blocks_delayed_confirmation_of_same_payment(
    app, monkeypatch
) -> None:
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_url="https://asaas.test/m2",
            proxima_cobranca=dt.date(2026, 8, 1),
        ),
        igreja=_igreja("ativa"),
    )
    client = _client(app, db, monkeypatch)

    refund = _post(
        client,
        "PAYMENT_REFUNDED",
        _payment(
            status="REFUNDED",
            payment_id="pay_m2",
            due_date="2026-08-01",
            invoice_url="https://asaas.test/m2",
        ),
    )

    assert refund.json()["status"] == "inadimplente"
    assert db.sub.asaas_invoice_url is None  # link estornado retido
    assert db.sub.asaas_invoice_reversal == "refunded"  # MOTIVO persistido
    assert db.sub.asaas_invoice_payment_id == "pay_m2"

    commits_after_refund = db.commits
    delayed = _post(
        client,
        "PAYMENT_CONFIRMED",
        _payment(
            status="CONFIRMED",
            payment_id="pay_m2",
            due_date="2026-08-01",
            invoice_url="https://asaas.test/m2",
        ),
    )

    assert delayed.json()["status"] is None
    assert db.sub.status == "inadimplente"
    assert db.sub.asaas_invoice_payment_id == "pay_m2"
    assert db.sub.asaas_invoice_url is None
    assert db.sub.asaas_invoice_reversal == "refunded"
    assert db.igreja.status == "inadimplente"
    assert db.commits == commits_after_refund


def test_new_cycle_tracks_its_state_without_settling_prior_recovery_debt(
    app, monkeypatch
) -> None:
    recovery_a = _operation(
        operation_key="pastorai-monthly_recovery-a-open",
        source_payment_id="pay_m2",
        asaas_payment_id="pay_rec_a_open",
        status="created",
    )
    db = _WebhookDb(
        sub=_sub(
            status="inadimplente",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_url=None,
            asaas_invoice_reversal="refunded",
            proxima_cobranca=dt.date(2026, 8, 1),
        ),
        igreja=_igreja("inadimplente"),
        operations=[recovery_a],
    )
    client = _client(app, db, monkeypatch)

    for event, raw_status in (
        ("PAYMENT_CREATED", "PENDING"),
        ("PAYMENT_CONFIRMED", "CONFIRMED"),
    ):
        resp = _post(
            client,
            event,
            _payment(
                status=raw_status,
                payment_id="pay_m3",
                due_date="2026-09-01",
                invoice_url="https://asaas.test/m3",
            ),
        )
        assert resp.json()["status"] in ("pendente", "ativa")

    assert recovery_a.status == "created"
    assert db.sub.status == "ativa"  # snapshot correto do ciclo B
    assert db.sub.asaas_invoice_payment_id == "pay_m3"
    assert db.sub.asaas_invoice_reversal is None
    assert db.igreja.status == "inadimplente"
    assert db.commits == 2

    # A recuperação de A agora pode reavaliar B: como B está ativa e não há
    # outra dívida, só neste momento o gate é liberado.
    recovery_payment = _payment(
        status="CONFIRMED", subscription=None, payment_id="pay_rec_a_open"
    )
    recovery_payment["externalReference"] = recovery_a.operation_key
    settled = _post(client, "PAYMENT_CONFIRMED", recovery_payment)

    assert settled.json()["status"] == "ativa"
    assert recovery_a.status == "paid"
    assert db.sub.status == "ativa"
    assert db.igreja.status == "ativa"


def test_refund_stages_debt_before_new_overdue_cycle_and_recovery_cannot_unlock(
    app, monkeypatch
) -> None:
    db = _WebhookDb(
        sub=_sub(
            status="inadimplente",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_reversal="refunded",
            proxima_cobranca=dt.date(2026, 8, 1),
        ),
        igreja=_igreja("inadimplente"),
    )
    client = _client(app, db, monkeypatch)

    refund = _post(
        client,
        "PAYMENT_REFUNDED",
        _payment(
            status="REFUNDED",
            payment_id="pay_m2",
            due_date="2026-08-01",
            value=199.0,
        ),
    )

    assert refund.json()["status"] == "inadimplente"
    recovery_a = next(
        o
        for o in db.operations
        if getattr(o, "purpose", None) == "monthly_recovery"
    )
    assert recovery_a.status == "prepared"
    assert recovery_a.source_payment_id == "pay_m2"
    assert float(recovery_a.valor) == 199.0

    overdue_b = _post(
        client,
        "PAYMENT_OVERDUE",
        _payment(
            status="OVERDUE",
            payment_id="pay_m3",
            due_date="2026-09-01",
            invoice_url="https://asaas.test/m3",
        ),
    )

    assert overdue_b.json()["status"] == "inadimplente"
    assert db.sub.status == "inadimplente"
    assert db.sub.asaas_invoice_payment_id == "pay_m3"
    assert db.sub.asaas_invoice_reversal is None
    assert db.igreja.status == "inadimplente"

    # Mesmo após a cobrança de recuperação de A ser paga, B continua vencida:
    # a confirmação tardia não pode reativar o tenant.
    recovery_a.status = "created"
    recovery_a.asaas_payment_id = "pay_rec_a"
    paid_a = _payment(
        status="CONFIRMED", subscription=None, payment_id="pay_rec_a"
    )
    paid_a["externalReference"] = recovery_a.operation_key
    settled = _post(client, "PAYMENT_CONFIRMED", paid_a)

    assert settled.json()["status"] == "ativa"
    assert recovery_a.status == "paid"
    assert db.sub.status == "inadimplente"
    assert db.sub.asaas_invoice_payment_id == "pay_m3"
    assert db.igreja.status == "inadimplente"


def test_new_cycle_overdue_remains_blocked_after_prior_recovery_is_paid(
    app, monkeypatch
) -> None:
    recovery_a = _operation(
        operation_key="pastorai-monthly_recovery-a-overdue",
        source_payment_id="pay_m2",
        asaas_payment_id="pay_rec_a_overdue",
        status="created",
    )
    db = _WebhookDb(
        sub=_sub(
            status="inadimplente",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_reversal="refunded",
            proxima_cobranca=dt.date(2026, 8, 1),
        ),
        igreja=_igreja("inadimplente"),
        operations=[recovery_a],
    )
    client = _client(app, db, monkeypatch)

    overdue = _post(
        client,
        "PAYMENT_OVERDUE",
        _payment(
            status="OVERDUE",
            payment_id="pay_m3",
            due_date="2026-09-01",
            invoice_url="https://asaas.test/m3",
        ),
    )

    assert overdue.json()["status"] == "inadimplente"
    assert db.sub.asaas_invoice_payment_id == "pay_m3"
    assert db.sub.asaas_invoice_url == "https://asaas.test/m3"
    assert db.sub.status == "inadimplente"

    recovery_payment = _payment(
        status="CONFIRMED", subscription=None, payment_id="pay_rec_a_overdue"
    )
    recovery_payment["externalReference"] = recovery_a.operation_key
    settled = _post(client, "PAYMENT_CONFIRMED", recovery_payment)

    assert settled.json()["status"] == "ativa"
    assert recovery_a.status == "paid"
    assert db.sub.status == "inadimplente"  # B continua vencida
    assert db.sub.asaas_invoice_payment_id == "pay_m3"
    assert db.igreja.status == "inadimplente"


def test_monthly_overdue_keeps_the_payable_link(app, monkeypatch) -> None:
    # Atraso NÃO é reversão: a mesma fatura continua sendo o caminho de
    # regularização.
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
        "PAYMENT_OVERDUE",
        _payment(status="OVERDUE", payment_id="pay_m2", due_date="2026-08-01"),
    )

    assert resp.json()["status"] == "inadimplente"
    assert db.sub.asaas_invoice_url == "https://asaas.test/m2"
    assert db.sub.asaas_invoice_reversal is None  # OVERDUE não é reversão


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


# ---------------------------------------------------------------------------
# CORRECTIVE-6: a externalReference NOVA (operation_key da intenção durável)
# resolve a Subscription pela operação; o formato legado (igreja_id) segue no
# fallback (coberto pelos testes de external_ref acima).
# ---------------------------------------------------------------------------
def test_subscription_event_resolves_new_external_reference_via_operation(
    app, monkeypatch
) -> None:
    sub = _sub(status="pendente", setup_pago=True)
    create_op = SimpleNamespace(
        operation_key="pastorai-subcreate-k1",
        subscription_id=sub.id,
        plano="ate_100",
        limite=100,
        customer_id="cus_1",
        valor=199.0,
        ciclo="MONTHLY",
        descricao="PastorAI — plano ate_100",
        setup_fee=0.0,
        asaas_subscription_id=None,
        status="reconciling",
        attempt_started_at=None,
    )
    db = _WebhookDb(
        sub=sub, igreja=_igreja("ativa"), subscription_create_ops=[create_op]
    )
    client = _client(app, db, monkeypatch)

    resp = client.post(
        "/subscription/webhook",
        json={
            "event": "SUBSCRIPTION_UPDATED",
            "subscription": {
                # id remoto DIFERENTE do rastreado: só a externalReference nova
                # (via operação durável) pode resolver o tenant.
                "id": "sub_asaas_9",
                "status": "ACTIVE",
                "externalReference": "pastorai-subcreate-k1",
                "customer": "cus_1",
                "value": 199.0,
                "cycle": "MONTHLY",
                "description": "PastorAI — plano ate_100",
            },
        },
        headers=_HDR,
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "ativa"
    assert db.sub.status == "ativa"
    assert db.lock_trace[:4] == [
        "church",
        "plans",
        "operation",
        "subscription",
    ]


def test_subscription_event_rejects_contract_that_differs_from_frozen_intent(
    app, monkeypatch
) -> None:
    sub = _sub(
        status="pendente",
        setup_pago=False,
        asaas_subscription_id=None,
    )
    create_op = SimpleNamespace(
        operation_key="pastorai-subcreate-mismatch",
        subscription_id=sub.id,
        plano="ate_100",
        limite=100,
        customer_id="cus_1",
        valor=199.0,
        ciclo="MONTHLY",
        descricao="PastorAI — plano ate_100",
        setup_fee=59.9,
        asaas_subscription_id=None,
        status="reconciling",
        attempt_started_at=None,
    )
    db = _WebhookDb(
        sub=sub,
        igreja=_igreja("aguardando_aprovacao"),
        subscription_create_ops=[create_op],
    )
    client = _client(app, db, monkeypatch)

    resp = client.post(
        "/subscription/webhook",
        json={
            "event": "SUBSCRIPTION_UPDATED",
            "subscription": {
                "id": "sub_conflicting",
                "status": "ACTIVE",
                "externalReference": create_op.operation_key,
                "customer": "cus_1",
                "value": 999.0,
                "cycle": "MONTHLY",
                "description": "PastorAI — plano ate_100",
            },
        },
        headers=_HDR,
    )

    assert resp.json() == {"received": True, "status": None}
    assert sub.asaas_subscription_id is None
    assert sub.status == "pendente"
    assert sub.setup_pago is False
    assert create_op.asaas_subscription_id is None
    assert create_op.status == "reconciling"
    assert db.igreja.status == "aguardando_aprovacao"
    assert db.commits == 0


def test_early_payment_cannot_close_an_unbound_creation_intent(
    app, monkeypatch
) -> None:
    sub = _sub(
        status="pendente",
        setup_pago=False,
        asaas_subscription_id=None,
        asaas_invoice_payment_id=None,
    )
    create_op = SimpleNamespace(
        operation_key="pastorai-subcreate-early-payment",
        subscription_id=sub.id,
        plano="ate_100",
        limite=100,
        customer_id="cus_early",
        valor=199.0,
        ciclo="MONTHLY",
        descricao="PastorAI — plano ate_100",
        setup_fee=0.0,
        asaas_subscription_id=None,
        status="creating",
        attempt_started_at=dt.datetime.now(dt.timezone.utc),
    )
    db = _WebhookDb(
        sub=sub,
        igreja=_igreja("inadimplente"),
        subscription_create_ops=[create_op],
    )
    client = _client(app, db, monkeypatch)

    payment = _payment(
        status="CONFIRMED",
        external_ref=create_op.operation_key,
        subscription="sub_asaas_early",
        payment_id="pay_early",
        due_date="2026-08-01",
        invoice_url="https://asaas.test/pay-early",
    )
    payment["customer"] = "cus_early"
    payment["value"] = 199.0
    payment["description"] = "PastorAI — plano ate_100"
    resp = _post(client, "PAYMENT_CONFIRMED", payment)

    assert resp.json() == {"received": True, "status": None}
    assert sub.status == "pendente"
    assert sub.asaas_subscription_id is None
    assert sub.asaas_invoice_payment_id is None
    assert sub.setup_pago is False
    assert create_op.status == "creating"
    assert create_op.asaas_subscription_id is None
    assert db.igreja.status == "inadimplente"
    assert db.commits == 0


# ---------------------------------------------------------------------------
# CORRECTIVE-7 P1: estorno de recuperação mensal PAGA devolve a dívida — com
# AUTORIDADE (source_payment_id == mensalidade corrente) contra atrasados.
# ---------------------------------------------------------------------------
def test_recovery_reversal_after_paid_drops_access_and_reexposes_debt(
    app, monkeypatch
) -> None:
    op = _operation(status="paid", source_payment_id="pay_m2")
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_reversal=None,  # quitada pela recovery
        ),
        igreja=_igreja("ativa"),
        operations=[op],
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="REFUNDED", subscription=None, payment_id="pay_rec_1")

    resp = _post(client, "PAYMENT_REFUNDED", payment)

    assert resp.status_code == 200
    assert op.status == "reversed"
    assert op.invoice_url is None
    # O dinheiro da recuperação voltou: dívida e bloqueio reaparecem.
    assert db.sub.status == "inadimplente"
    assert db.sub.asaas_invoice_reversal == "refunded"  # ação de recovery volta
    assert db.igreja.status == "inadimplente"

    # Repetição do estorno: operação já reversed — nada re-derruba nem muda.
    db.igreja.status = "ativa"  # sentinela: um segundo drop seria visível
    resp2 = _post(client, "PAYMENT_REFUNDED", payment)
    assert resp2.status_code == 200
    assert db.igreja.status == "ativa"  # intocada na repetição


def test_duplicate_old_recovery_reversal_does_not_duplicate_reopened_debt(
    app, monkeypatch
) -> None:
    # Recovery ANTIGA estornada: a dívida reabre uma vez, sem reescrever o
    # snapshot corrente e sem duplicar a intenção no webhook repetido.
    op = _operation(status="paid", source_payment_id="pay_m1")
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            asaas_invoice_payment_id="pay_m9",
            asaas_invoice_reversal=None,
        ),
        igreja=_igreja("ativa"),
        operations=[op],
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="REFUNDED", subscription=None, payment_id="pay_rec_1")

    resp = _post(client, "PAYMENT_REFUNDED", payment)
    resp2 = _post(client, "PAYMENT_REFUNDED", payment)

    assert resp.status_code == 200
    assert resp2.status_code == 200
    assert op.status == "reversed"  # a operação antiga é sempre marcada
    assert db.sub.status == "ativa"  # ciclo novo intocado
    assert db.sub.asaas_invoice_reversal is None
    assert db.igreja.status == "inadimplente"
    replacements = [o for o in db.operations if o is not op]
    assert len(replacements) == 1


def test_deleted_unpaid_old_recovery_reopens_a_payable_intent(app, monkeypatch) -> None:
    op = _operation(
        status="created",
        source_payment_id="pay_m1",
        asaas_payment_id="pay_rec_unpaid",
        invoice_url="https://asaas.test/recovery-unpaid",
    )
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            asaas_invoice_payment_id="pay_m9",
            asaas_invoice_reversal=None,
        ),
        igreja=_igreja("inadimplente"),
        operations=[op],
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(
        status="DELETED", subscription=None, payment_id="pay_rec_unpaid"
    )

    resp = _post(client, "PAYMENT_DELETED", payment)

    assert resp.status_code == 200
    assert op.status == "reversed"
    replacement = [candidate for candidate in db.operations if candidate is not op]
    assert len(replacement) == 1
    assert replacement[0].status == "prepared"
    assert replacement[0].source_payment_id == "pay_m1"
    assert replacement[0].valor == op.valor
    assert db.sub.status == "ativa"
    assert db.sub.asaas_invoice_reversal is None
    assert db.igreja.status == "inadimplente"


def test_late_confirmation_never_resurrects_reversed_recovery(
    app, monkeypatch
) -> None:
    op = _operation(status="reversed", invoice_url=None, source_payment_id="pay_m2")
    db = _WebhookDb(
        sub=_sub(
            status="inadimplente",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_reversal="refunded",
        ),
        igreja=_igreja("inadimplente"),
        operations=[op],
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="CONFIRMED", subscription=None, payment_id="pay_rec_1")

    resp = _post(client, "PAYMENT_CONFIRMED", payment)

    assert resp.status_code == 200
    # Confirmação ATRASADA de uma cobrança já estornada não reativa nada.
    assert op.status == "reversed"
    assert db.sub.status == "inadimplente"
    assert db.igreja.status == "inadimplente"


# ---------------------------------------------------------------------------
# CORRECTIVE-7 P2: estorno tardio de setup ANTIGO nunca desfaz o substituto.
# ---------------------------------------------------------------------------
def test_stale_setup_reversal_keeps_replacement_paid(app, monkeypatch) -> None:
    old_setup = _operation(
        purpose="setup",
        operation_key="pastorai-setup-opA",
        asaas_payment_id="pay_sA",
        status="paid",
        valor=59.9,
        source_payment_id=None,
    )
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            setup_pago=True,
            asaas_setup_charge_id="pay_sB",  # substituto B é o rastreado
            asaas_setup_invoice_url="https://asaas.test/setup-b",
        ),
        igreja=_igreja("ativa"),
        operations=[old_setup],
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="REFUNDED", subscription=None, payment_id="pay_sA")

    for _ in range(2):  # inclusive repetido
        resp = _post(client, "PAYMENT_REFUNDED", payment)
        assert resp.status_code == 200
        assert old_setup.status == "reversed"  # a geração antiga é marcada
        # O substituto pago permanece intocado.
        assert db.sub.setup_pago is True
        assert db.sub.asaas_setup_charge_id == "pay_sB"
        assert db.sub.asaas_setup_invoice_url == "https://asaas.test/setup-b"


def test_setup_reversal_of_current_charge_still_reopens(app, monkeypatch) -> None:
    current = _operation(
        purpose="setup",
        operation_key="pastorai-setup-opC",
        asaas_payment_id="pay_sC",
        status="paid",
        valor=59.9,
        source_payment_id=None,
    )
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            setup_pago=True,
            asaas_setup_charge_id="pay_sC",  # a operação É a dona atual
            asaas_setup_invoice_url="https://asaas.test/setup-c",
        ),
        igreja=_igreja("ativa"),
        operations=[current],
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="REFUNDED", subscription=None, payment_id="pay_sC")

    resp = _post(client, "PAYMENT_REFUNDED", payment)

    assert resp.status_code == 200
    assert current.status == "reversed"
    assert db.sub.setup_pago is False  # dona atual: pendência reabre
    assert db.sub.asaas_setup_charge_id is None
    assert db.sub.asaas_setup_invoice_url is None


# ---------------------------------------------------------------------------
# CORRECTIVE-8 P1: fonte já LIQUIDADA por recovery paga — estorno duplicado
# da cobrança-fonte é ignorado; só a reversão da PRÓPRIA recovery reabre.
# ---------------------------------------------------------------------------
def test_duplicate_source_refund_after_paid_recovery_is_ignored(
    app, monkeypatch
) -> None:
    settled = _operation(status="paid", source_payment_id="pay_m2")
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_reversal=None,  # dívida quitada pela recovery
        ),
        igreja=_igreja("ativa"),
        operations=[settled],
    )
    client = _client(app, db, monkeypatch)
    # Estorno DUPLICADO/atrasado da cobrança-fonte (não da recovery).
    payment = _payment(status="REFUNDED", payment_id="pay_m2")

    resp = _post(client, "PAYMENT_REFUNDED", payment)

    assert resp.status_code == 200
    assert resp.json() == {"received": True, "status": None}
    # NADA muda: sem dívida nova, sem gate, sem segunda recovery possível.
    assert db.sub.status == "ativa"
    assert db.sub.asaas_invoice_reversal is None
    assert db.igreja.status == "ativa"
    assert db.commits == 0


def test_source_refund_counts_again_after_recovery_itself_reversed(
    app, monkeypatch
) -> None:
    # A recovery que liquidava a fonte foi revertida: a guarda deixa de casar
    # e o estorno da fonte volta a valer (dívida real).
    dead_recovery = _operation(status="reversed", source_payment_id="pay_m2")
    db = _WebhookDb(
        sub=_sub(
            status="ativa",
            asaas_invoice_payment_id="pay_m2",
            asaas_invoice_reversal=None,
        ),
        igreja=_igreja("ativa"),
        operations=[dead_recovery],
    )
    client = _client(app, db, monkeypatch)
    payment = _payment(status="REFUNDED", payment_id="pay_m2")

    resp = _post(client, "PAYMENT_REFUNDED", payment)

    assert resp.status_code == 200
    assert db.sub.status == "inadimplente"
    assert db.igreja.status == "inadimplente"
