"""Operações duráveis de cobrança (billing_payment_operations).

Invariantes sob teste: intenção persistida ANTES do POST /payments; retry
reconcilia pela operation_key (externalReference exclusiva) em vez de repetir
o POST; claim atômico impede requests concorrentes de criarem duas cobranças;
reconciliação ambígua/divergente falha com segurança, sem criar nada.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import BillingPaymentOperation
from app.services.asaas import AsaasError
from app.services.billing import ensure_payment_operation
from tests.conftest import FakeSession


def _sub():
    return SimpleNamespace(id="local-sub-1")


class _OpsAsaas:
    """Fake do provedor para o ciclo da operação durável."""

    def __init__(
        self,
        *,
        charge: dict | None = None,
        post_error: bool = False,
        found: list[dict] | None = None,
    ) -> None:
        self.posts = 0
        self.finds = 0
        self._charge = charge
        self._post_error = post_error
        self._found = found or []

    def create_one_time_charge(self, **kwargs):
        self.posts += 1
        if self._post_error:
            raise AsaasError("timeout ambíguo depois do POST")
        return self._charge

    def find_payments_by_external_reference(self, external_reference: str):
        self.finds += 1
        return [dict(p) for p in self._found]


_DESC = "PastorAI — taxa de setup"


def _ensure(db, asaas, *, valor: float = 59.9):
    return ensure_payment_operation(
        db,
        asaas,
        sub=_sub(),
        purpose="setup",
        valor=valor,
        description=_DESC,
        customer_id="cus_1",
    )


def test_lost_response_reconciles_same_charge_without_second_post() -> None:
    db = FakeSession()
    flaky = _OpsAsaas(post_error=True)

    # 1º request: POST ambíguo (timeout) => operação fica `reconciling`.
    with pytest.raises(AsaasError):
        _ensure(db, flaky)
    op = next(o for o in db.added if isinstance(o, BillingPaymentOperation))
    assert op.status == "reconciling"
    assert flaky.posts == 1

    # Retry: a MESMA operação é reconciliada pela operation_key — a cobrança
    # existia no Asaas e é adotada. Total de POSTs continua 1.
    reconciler = _OpsAsaas(
        found=[
            {
                "id": "pay_setup_9",
                "value": 59.9,
                "description": _DESC,
                "customer": "cus_1",
                "invoiceUrl": "https://asaas.test/setup9",
            }
        ]
    )
    resolved = _ensure(db, reconciler)

    assert resolved is op
    assert resolved.status == "created"
    assert resolved.asaas_payment_id == "pay_setup_9"
    assert resolved.invoice_url == "https://asaas.test/setup9"
    assert reconciler.posts == 0  # zero segundo POST
    assert reconciler.finds == 1


def test_concurrent_claim_adopts_winner_without_second_charge() -> None:
    winner = BillingPaymentOperation(
        subscription_id="local-sub-1",
        purpose="setup",
        operation_key="pastorai-setup-winner",
        status="created",
        valor=59.9,
        asaas_payment_id="pay_setup_1",
        invoice_url="https://asaas.test/setup",
    )

    class _RacySession(FakeSession):
        """Simula a corrida: o INSERT da operação perde para o vencedor
        (índice único parcial) — exatamente como no banco real."""

        def __init__(self) -> None:
            super().__init__()
            self._raced = False

        def commit(self) -> None:
            pending = [
                o for o in self.added if isinstance(o, BillingPaymentOperation)
            ]
            if not self._raced and pending:
                self._raced = True
                self.added = [
                    o for o in self.added
                    if not isinstance(o, BillingPaymentOperation)
                ]
                self.operations.append(winner)
                raise IntegrityError("insert", {}, Exception("unique violation"))
            super().commit()

    db = _RacySession()
    asaas = _OpsAsaas(charge={"id": "pay_dup", "invoiceUrl": "x"})

    op = _ensure(db, asaas)

    assert op is winner  # adota a operação do vencedor
    assert asaas.posts == 0  # e NÃO cria uma segunda cobrança


def test_reconcile_zero_matches_stays_reconciling_without_post() -> None:
    stuck = BillingPaymentOperation(
        subscription_id="local-sub-1",
        purpose="setup",
        operation_key="pastorai-setup-stuck",
        status="reconciling",
        valor=59.9,
    )
    db = FakeSession(operations=[stuck])
    asaas = _OpsAsaas(found=[])

    with pytest.raises(AsaasError):
        _ensure(db, asaas)

    assert stuck.status == "reconciling"  # falha segura, sem POST automático
    assert asaas.posts == 0


def test_reconcile_multiple_matches_fails_safe() -> None:
    match = {
        "id": "pay_a",
        "value": 59.9,
        "description": _DESC,
        "customer": "cus_1",
    }
    op = BillingPaymentOperation(
        subscription_id="local-sub-1",
        purpose="setup",
        operation_key="pastorai-setup-dup",
        status="reconciling",
        valor=59.9,
    )
    db = FakeSession(operations=[op])
    asaas = _OpsAsaas(found=[match, {**match, "id": "pay_b"}])

    with pytest.raises(AsaasError):
        _ensure(db, asaas)

    assert op.status == "failed"  # registrado; nada criado
    assert asaas.posts == 0


def test_reconcile_rejects_mismatched_charge_data() -> None:
    op = BillingPaymentOperation(
        subscription_id="local-sub-1",
        purpose="setup",
        operation_key="pastorai-setup-mism",
        status="reconciling",
        valor=59.9,
    )
    db = FakeSession(operations=[op])
    # Valor e descrição divergentes: correspondência REJEITADA.
    asaas = _OpsAsaas(
        found=[
            {"id": "pay_x", "value": 10.0, "description": _DESC, "customer": "cus_1"},
            {"id": "pay_y", "value": 59.9, "description": "Outra", "customer": "cus_1"},
        ]
    )

    with pytest.raises(AsaasError):
        _ensure(db, asaas)

    assert op.status == "reconciling"
    assert op.asaas_payment_id is None
    assert asaas.posts == 0


def test_created_operation_is_reused_without_any_remote_call() -> None:
    done = BillingPaymentOperation(
        subscription_id="local-sub-1",
        purpose="setup",
        operation_key="pastorai-setup-done",
        status="created",
        valor=59.9,
        asaas_payment_id="pay_setup_1",
        invoice_url="https://asaas.test/setup",
    )
    db = FakeSession(operations=[done])
    asaas = _OpsAsaas(charge={"id": "pay_new"})

    op = _ensure(db, asaas)

    assert op is done
    assert asaas.posts == 0
    assert asaas.finds == 0
