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
from app.services.asaas import AsaasError, MONTHLY_RECOVERY_DESCRIPTION
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
        tracked: dict | None = None,
    ) -> None:
        self.posts = 0
        self.finds = 0
        self.gets = 0
        self._charge = charge
        self._post_error = post_error
        self._found = found or []
        self._tracked = tracked

    def create_one_time_charge(self, **kwargs):
        self.posts += 1
        if self._post_error:
            raise AsaasError("timeout ambíguo depois do POST")
        return self._charge

    def find_payments_by_external_reference(self, external_reference: str):
        self.finds += 1
        return [dict(p) for p in self._found]

    def get_payment(self, payment_id: str):
        self.gets += 1
        return dict(self._tracked) if self._tracked is not None else None


_DESC = "PastorAI — taxa de setup"


def _ensure(db, asaas, *, valor: float = 59.9, sub=None):
    return ensure_payment_operation(
        db,
        asaas,
        sub=sub or _sub(),
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


def test_reconcile_confirmed_setup_applies_paid_state_without_webhook() -> None:
    sub = SimpleNamespace(
        id="local-sub-1",
        igreja_id="igreja-1",
        setup_pago=False,
        asaas_setup_charge_id=None,
        asaas_setup_reversed_payment_id=None,
        asaas_setup_invoice_url=None,
    )
    op = BillingPaymentOperation(
        subscription_id=sub.id,
        purpose="setup",
        operation_key="pastorai-setup-confirmed",
        status="reconciling",
        valor=59.9,
    )
    db = FakeSession(
        subscription=sub,
        igreja=SimpleNamespace(id="igreja-1", status="ativa"),
        operations=[op],
    )
    asaas = _OpsAsaas(
        found=[
            {
                "id": "pay_setup_confirmed",
                "value": 59.9,
                "description": _DESC,
                "customer": "cus_1",
                "status": "CONFIRMED",
            }
        ]
    )

    resolved = _ensure(db, asaas, sub=sub)

    assert resolved is op
    assert op.status == "paid"
    assert op.asaas_payment_id == "pay_setup_confirmed"
    assert sub.setup_pago is True
    assert sub.asaas_setup_charge_id == "pay_setup_confirmed"
    assert db.flushes == 1


def test_reconcile_deleted_flag_takes_precedence_over_pending_status() -> None:
    sub = SimpleNamespace(
        id="local-sub-1",
        igreja_id="igreja-1",
        setup_pago=False,
        asaas_setup_charge_id=None,
        asaas_setup_reversed_payment_id=None,
        asaas_setup_invoice_url=None,
    )
    op = BillingPaymentOperation(
        subscription_id=sub.id,
        purpose="setup",
        operation_key="pastorai-setup-deleted",
        status="reconciling",
        valor=59.9,
    )
    db = FakeSession(
        subscription=sub,
        igreja=SimpleNamespace(id="igreja-1", status="ativa"),
        operations=[op],
    )
    asaas = _OpsAsaas(
        found=[{
            "id": "pay_setup_deleted",
            "value": 59.9,
            "description": _DESC,
            "customer": "cus_1",
            "status": "PENDING",
            "deleted": True,
            "invoiceUrl": "https://asaas.test/dead",
        }]
    )

    resolved = _ensure(db, asaas, sub=sub)

    assert resolved.status == "reversed"
    assert resolved.invoice_url is None
    assert sub.setup_pago is False
    assert sub.asaas_setup_reversed_payment_id == "pay_setup_deleted"
    assert sub.asaas_setup_invoice_url is None
    assert asaas.posts == 0


def test_reconcile_confirmed_recovery_settles_debt_without_webhook() -> None:
    sub = SimpleNamespace(
        id="local-sub-1",
        igreja_id="igreja-1",
        status="inadimplente",
        asaas_invoice_payment_id="pay_source",
        asaas_invoice_reversal="refunded",
    )
    op = BillingPaymentOperation(
        subscription_id=sub.id,
        purpose="monthly_recovery",
        operation_key="pastorai-monthly-recovery-confirmed",
        source_payment_id="pay_source",
        status="reconciling",
        valor=199.0,
    )
    igreja = SimpleNamespace(id="igreja-1", status="inadimplente")
    db = FakeSession(subscription=sub, igreja=igreja, operations=[op])
    asaas = _OpsAsaas(
        found=[
            {
                "id": "pay_recovery_confirmed",
                "value": 199.0,
                "description": MONTHLY_RECOVERY_DESCRIPTION,
                "customer": "cus_1",
                "status": "RECEIVED",
            }
        ]
    )

    resolved = ensure_payment_operation(
        db,
        asaas,
        sub=sub,
        purpose="monthly_recovery",
        valor=199.0,
        description=MONTHLY_RECOVERY_DESCRIPTION,
        customer_id="cus_1",
        source_payment_id="pay_source",
    )

    assert resolved is op
    assert op.status == "paid"
    assert sub.status == "ativa"
    assert sub.asaas_invoice_reversal is None
    assert igreja.status == "ativa"
    assert db.flushes == 1
    assert asaas.posts == 0


def test_created_setup_retry_repairs_a_missed_confirmation_webhook() -> None:
    sub = SimpleNamespace(
        id="local-sub-1",
        igreja_id="igreja-1",
        setup_pago=False,
        asaas_setup_charge_id="pay_setup_created",
        asaas_setup_reversed_payment_id=None,
        asaas_setup_invoice_url="https://asaas.test/setup",
    )
    op = BillingPaymentOperation(
        subscription_id=sub.id,
        purpose="setup",
        operation_key="pastorai-setup-created",
        status="created",
        valor=59.9,
        asaas_payment_id="pay_setup_created",
        invoice_url="https://asaas.test/setup",
    )
    db = FakeSession(
        subscription=sub,
        igreja=SimpleNamespace(id="igreja-1", status="ativa"),
        operations=[op],
    )
    asaas = _OpsAsaas(
        tracked={
            "id": "pay_setup_created",
            "status": "CONFIRMED",
            "value": 59.9,
        }
    )

    resolved = _ensure(db, asaas, sub=sub)

    assert resolved.status == "paid"
    assert sub.setup_pago is True
    assert sub.asaas_setup_invoice_url is None
    assert asaas.gets == 1
    assert asaas.posts == 0


def test_created_recovery_retry_reopens_gate_after_missed_webhook() -> None:
    sub = SimpleNamespace(
        id="local-sub-1",
        igreja_id="igreja-1",
        status="inadimplente",
        asaas_invoice_payment_id="pay_source",
        asaas_invoice_reversal="refunded",
    )
    op = BillingPaymentOperation(
        subscription_id=sub.id,
        purpose="monthly_recovery",
        operation_key="pastorai-monthly-recovery-created",
        source_payment_id="pay_source",
        status="created",
        valor=199.0,
        asaas_payment_id="pay_recovery_created",
        invoice_url="https://asaas.test/recovery",
    )
    igreja = SimpleNamespace(id="igreja-1", status="inadimplente")
    db = FakeSession(subscription=sub, igreja=igreja, operations=[op])
    asaas = _OpsAsaas(
        tracked={
            "id": "pay_recovery_created",
            "status": "RECEIVED",
            "value": 199.0,
        }
    )

    resolved = ensure_payment_operation(
        db,
        asaas,
        sub=sub,
        purpose="monthly_recovery",
        valor=199.0,
        description=MONTHLY_RECOVERY_DESCRIPTION,
        customer_id="cus_1",
        source_payment_id="pay_source",
    )

    assert resolved.status == "paid"
    assert sub.status == "ativa"
    assert sub.asaas_invoice_reversal is None
    assert igreja.status == "ativa"
    assert asaas.gets == 1
    assert asaas.posts == 0


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


def test_abandoned_payment_claim_stays_reconciling_without_second_post() -> None:
    import datetime as dt

    abandoned = BillingPaymentOperation(
        subscription_id="local-sub-1",
        purpose="setup",
        operation_key="pastorai-setup-abandoned",
        status="creating",
        valor=59.9,
        attempt_started_at=(
            dt.datetime.now(dt.timezone.utc)
            - dt.timedelta(minutes=10)
            - dt.timedelta(seconds=1)
        ),
    )
    db = FakeSession(operations=[abandoned])
    asaas = _OpsAsaas(
        found=[],
        charge={
            "id": "pay_reclaimed",
            "invoiceUrl": "https://asaas.test/reclaimed",
        },
    )

    with pytest.raises(AsaasError):
        _ensure(db, asaas)
    with pytest.raises(AsaasError):
        _ensure(db, asaas)

    assert asaas.finds == 2
    assert asaas.posts == 0
    assert abandoned.status == "reconciling"
    assert abandoned.asaas_payment_id is None


def test_reconcile_multiple_matches_stays_blocking_without_new_post() -> None:
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
    with pytest.raises(AsaasError):
        _ensure(db, asaas)

    assert op.status == "reconciling"
    assert "revisão manual" in (op.error or "")
    assert asaas.finds == 2
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


# ---------------------------------------------------------------------------
# Troca de plano durável (PLAN-CHANGE-SAFETY-1): PUT na assinatura EXISTENTE,
# vigência no próximo ciclo, retry por reconciliação — nunca 2ª recorrência.
# ---------------------------------------------------------------------------
import datetime as dt  # noqa: E402

from app.db.models import BillingPlanChangeOperation, Subscription  # noqa: E402
from app.services.asaas import AsaasRejectedError  # noqa: E402
from app.services.billing import (  # noqa: E402
    PLAN_CHANGE_ATTEMPT_LEASE,
    PlanChangeConflict,
    ensure_plan_change_operation,
)


def _plan_sub():
    return SimpleNamespace(
        id="local-sub-1",
        igreja_id="igreja-1",
        plano="ate_100",
        limite=100,
        proxima_cobranca="2026-08-01",
        asaas_subscription_id="sub_asaas_1",
    )


class _PlanAsaas:
    def __init__(
        self,
        *,
        remote: dict | None = None,
        put_error: bool = False,
        put_rejected: bool = False,
    ) -> None:
        self.puts = 0
        self.gets = 0
        self._remote = remote
        self._put_error = put_error
        self._put_rejected = put_rejected

    def update_subscription(self, subscription_id: str, *, valor: float, descricao: str):
        self.puts += 1
        if self._put_rejected:
            raise AsaasRejectedError("O Asaas rejeitou a atualização da assinatura")
        if self._put_error:
            raise AsaasError("timeout ambíguo depois do PUT")
        return {"id": subscription_id, "value": valor, "description": descricao}

    def get_subscription(self, subscription_id: str):
        self.gets += 1
        return self._remote

    def create_checkout(self, **kwargs):  # pragma: no cover - defesa
        raise AssertionError("troca de plano nunca cria assinatura")


def _change(db, asaas, sub, *, to_plano: str = "101_200"):
    return ensure_plan_change_operation(
        db,
        asaas,
        sub=sub,
        to_plano=to_plano,
        to_preco=299.0,
        to_limite=200,
    )


def test_plan_change_updates_same_subscription_in_place() -> None:
    sub = _plan_sub()
    igreja = SimpleNamespace(id="igreja-1", plano="ate_100")
    db = FakeSession(igreja=igreja)
    asaas = _PlanAsaas()

    op = _change(db, asaas, sub)

    assert op.status == "completed"
    assert asaas.puts == 1
    assert sub.plano == "101_200"
    assert sub.limite == 200
    assert igreja.plano == "101_200"
    assert sub.proxima_cobranca == "2026-08-01"  # ciclo preservado
    assert sub.asaas_subscription_id == "sub_asaas_1"  # MESMO id remoto


def test_plan_change_put_timeout_keeps_local_plan_and_reconciles_later() -> None:
    sub = _plan_sub()
    db = FakeSession(igreja=SimpleNamespace(id="igreja-1", plano="ate_100"))
    flaky = _PlanAsaas(put_error=True)

    with pytest.raises(AsaasError):
        _change(db, flaky, sub)

    op = next(o for o in db.added if isinstance(o, BillingPlanChangeOperation))
    assert op.status == "reconciling"
    assert sub.plano == "ate_100"  # plano local INTACTO até confirmação
    assert flaky.puts == 1

    # Retry: GET confirma que o PUT anterior chegou (valor remoto == alvo) —
    # conclui SEM repetir o PUT.
    confirming = _PlanAsaas(
        remote={
            "id": "sub_asaas_1",
            "value": 299.0,
            "description": "PastorAI — plano 101_200",
        }
    )
    done = _change(db, confirming, sub)

    assert done is op
    assert done.status == "completed"
    assert sub.plano == "101_200"
    assert confirming.puts == 0
    assert confirming.gets == 1


def test_plan_change_reconciling_retries_the_same_put_and_completes() -> None:
    # SELF-AUDIT-10 P1: `reconciling` com remoto DIVERGENTE tinha o GET como
    # única saída — e o GET nunca mudaria sozinho. A operação (e o slot único
    # da assinatura) ficavam presos para sempre. O PUT é idempotente por
    # construção, então o retry controlado o repete com os alvos congelados.
    sub = _plan_sub()
    igreja = SimpleNamespace(id="igreja-1", plano="ate_100")
    op = BillingPlanChangeOperation(
        subscription_id="local-sub-1",
        asaas_subscription_id="sub_asaas_1",
        from_plano="ate_100",
        to_plano="101_200",
        to_preco=299.0,
        to_limite=200,
        to_descricao="PastorAI — plano 101_200",
        status="reconciling",
    )
    db = FakeSession(plan_changes=[op], igreja=igreja)
    # Remoto ainda mostra o valor antigo: o GET não conclui nada.
    asaas = _PlanAsaas(remote={"id": "sub_asaas_1", "value": 199.0})

    done = _change(db, asaas, sub)

    assert done is op
    assert asaas.gets == 1  # reconciliação SEMPRE antes de escrever
    assert asaas.puts == 1  # exatamente um PUT no retry
    assert op.status == "completed"
    assert sub.plano == "101_200"
    assert sub.limite == 200
    assert igreja.plano == "101_200"
    assert sub.asaas_subscription_id == "sub_asaas_1"  # nunca outra recorrência


def test_plan_change_in_flight_attempt_never_gets_a_second_put() -> None:
    # Duas tentativas concorrentes: a operação está em `processing` com o lease
    # VIVO (outro processo dentro do PUT). O retry só reconcilia por GET —
    # jamais dispara um segundo PUT em paralelo.
    sub = _plan_sub()
    op = BillingPlanChangeOperation(
        subscription_id="local-sub-1",
        asaas_subscription_id="sub_asaas_1",
        from_plano="ate_100",
        to_plano="101_200",
        to_preco=299.0,
        to_limite=200,
        to_descricao="PastorAI — plano 101_200",
        status="processing",
        attempt_started_at=dt.datetime.now(dt.timezone.utc),
    )
    db = FakeSession(plan_changes=[op])
    asaas = _PlanAsaas(remote={"id": "sub_asaas_1", "value": 199.0})

    with pytest.raises(AsaasError):
        _change(db, asaas, sub)

    assert asaas.puts == 0
    assert op.status == "processing"  # o dono do claim segue com a posse
    assert sub.plano == "ate_100"


def test_plan_change_abandoned_attempt_is_reclaimed_after_the_lease() -> None:
    # O processo dono morreu entre o claim e o PUT: `processing` com lease
    # VENCIDO é tentativa abandonada e volta a ser executável.
    sub = _plan_sub()
    igreja = SimpleNamespace(id="igreja-1", plano="ate_100")
    op = BillingPlanChangeOperation(
        subscription_id="local-sub-1",
        asaas_subscription_id="sub_asaas_1",
        from_plano="ate_100",
        to_plano="101_200",
        to_preco=299.0,
        to_limite=200,
        to_descricao="PastorAI — plano 101_200",
        status="processing",
        attempt_started_at=dt.datetime.now(dt.timezone.utc)
        - PLAN_CHANGE_ATTEMPT_LEASE
        - dt.timedelta(seconds=1),
    )
    db = FakeSession(plan_changes=[op], igreja=igreja)
    asaas = _PlanAsaas(remote={"id": "sub_asaas_1", "value": 199.0})

    done = _change(db, asaas, sub)

    assert done.status == "completed"
    assert asaas.puts == 1
    assert sub.plano == "101_200"


def test_plan_change_retry_definitive_rejection_fails_and_frees_the_slot() -> None:
    # 4xx no PUT do RETRY é definitivo (o remoto ficou como estava): fecha
    # `failed`, plano local intacto e o claim único liberado.
    sub = _plan_sub()
    igreja = SimpleNamespace(id="igreja-1", plano="ate_100")
    op = BillingPlanChangeOperation(
        subscription_id="local-sub-1",
        asaas_subscription_id="sub_asaas_1",
        from_plano="ate_100",
        to_plano="101_200",
        to_preco=299.0,
        to_limite=200,
        to_descricao="PastorAI — plano 101_200",
        status="reconciling",
    )
    db = FakeSession(plan_changes=[op], igreja=igreja)
    asaas = _PlanAsaas(
        remote={"id": "sub_asaas_1", "value": 199.0}, put_rejected=True
    )

    with pytest.raises(AsaasRejectedError):
        _change(db, asaas, sub)

    assert op.status == "failed"
    assert op.error
    assert sub.plano == "ate_100"
    assert igreja.plano == "ate_100"


def test_plan_change_retry_ambiguous_failure_stays_recoverable() -> None:
    # Timeout/5xx no PUT do RETRY continua AMBÍGUO: volta a `reconciling`
    # (plano local intacto) e o próximo retry reconcilia de novo — nunca
    # termina em estado sem saída.
    sub = _plan_sub()
    op = BillingPlanChangeOperation(
        subscription_id="local-sub-1",
        asaas_subscription_id="sub_asaas_1",
        from_plano="ate_100",
        to_plano="101_200",
        to_preco=299.0,
        to_limite=200,
        to_descricao="PastorAI — plano 101_200",
        status="reconciling",
    )
    db = FakeSession(plan_changes=[op])
    flaky = _PlanAsaas(remote={"id": "sub_asaas_1", "value": 199.0}, put_error=True)

    with pytest.raises(AsaasError):
        _change(db, flaky, sub)

    assert op.status == "reconciling"
    assert flaky.puts == 1
    assert sub.plano == "ate_100"

    # E o retry seguinte conclui pelo GET, agora que o remoto reflete o alvo.
    applied = _PlanAsaas(
        remote={
            "id": "sub_asaas_1",
            "value": 299.0,
            "description": "PastorAI — plano 101_200",
        }
    )
    done = _change(db, applied, sub)
    assert done.status == "completed"
    assert applied.puts == 0
    assert sub.plano == "101_200"


def test_concurrent_plan_change_to_other_plan_conflicts() -> None:
    sub = _plan_sub()
    open_op = BillingPlanChangeOperation(
        subscription_id="local-sub-1",
        asaas_subscription_id="sub_asaas_1",
        from_plano="ate_100",
        to_plano="acima_201",
        to_preco=499.0,
        to_limite=None,
        status="processing",
    )
    db = FakeSession(plan_changes=[open_op])
    asaas = _PlanAsaas()

    with pytest.raises(PlanChangeConflict):
        _change(db, asaas, sub, to_plano="101_200")

    assert asaas.puts == 0


def test_concurrent_claim_adopts_winner_for_same_plan() -> None:
    winner = BillingPlanChangeOperation(
        subscription_id="local-sub-1",
        asaas_subscription_id="sub_asaas_1",
        from_plano="ate_100",
        to_plano="101_200",
        to_preco=299.0,
        to_limite=200,
        status="processing",
    )

    class _RacyPlanSession(FakeSession):
        def __init__(self) -> None:
            super().__init__(igreja=SimpleNamespace(id="igreja-1", plano="ate_100"))
            self._raced = False

        def commit(self) -> None:
            pending = [
                o for o in self.added if isinstance(o, BillingPlanChangeOperation)
            ]
            if not self._raced and pending:
                self._raced = True
                self.added = [
                    o
                    for o in self.added
                    if not isinstance(o, BillingPlanChangeOperation)
                ]
                self.plan_changes.append(winner)
                raise IntegrityError("insert", {}, Exception("unique violation"))
            super().commit()

    sub = _plan_sub()
    db = _RacyPlanSession()
    # A operação do vencedor está `processing`: o perdedor reconcilia por GET.
    asaas = _PlanAsaas(
        remote={
            "id": "sub_asaas_1",
            "value": 299.0,
            "description": "PastorAI — plano 101_200",
        }
    )

    op = _change(db, asaas, sub)

    assert op is winner
    assert op.status == "completed"
    assert asaas.puts == 0  # nenhum PUT duplicado


# ---------------------------------------------------------------------------
# CORRECTIVE-6 P1: claim ATÔMICO prepared -> creating — dois requests que
# adotaram a MESMA operação nunca fazem dois POST /payments.
# ---------------------------------------------------------------------------
import uuid  # noqa: E402

from app.services.billing import (  # noqa: E402
    SubscriptionCreateConflict,
    claim_transition,
    find_subscription_operation_by_key,
    finish_operation,
    prepare_subscription_operation,
    subscription_matches_operation,
)
from app.db.models import BillingSubscriptionOperation  # noqa: E402
from tests.conftest import FakeSession as _ConfFakeSession  # noqa: E402


class _RaceOnClaimSession(FakeSession):
    """No PRIMEIRO UPDATE condicional, o rival roda ANTES — reproduz
    deterministicamente os dois requests que leram `prepared` juntos."""

    def __init__(self, rival, **kw) -> None:
        super().__init__(**kw)
        self._rival = rival
        self._raced = False

    def _apply_conditional_update(self, statement):
        if not self._raced:
            self._raced = True
            self._rival()
        return super()._apply_conditional_update(statement)


def test_payment_claim_race_makes_at_most_one_post() -> None:
    shared = BillingPaymentOperation(
        id=uuid.uuid4(),
        subscription_id="local-sub-1",
        purpose="setup",
        operation_key="pastorai-setup-race",
        status="prepared",
        valor=59.9,
    )
    asaas_winner = _OpsAsaas(charge={"id": "pay_winner", "invoiceUrl": "u"})
    db_winner = FakeSession(operations=[shared])

    def rival() -> None:
        # O rival A completa o fluxo INTEIRO entre o find do B e o claim do B.
        result = _ensure(db_winner, asaas_winner)
        assert result.status == "created"

    asaas_loser = _OpsAsaas(charge={"id": "pay_loser", "invoiceUrl": "u2"})
    db_loser = _RaceOnClaimSession(rival, operations=[shared])

    result = _ensure(db_loser, asaas_loser)

    # Exatamente UM POST no total; o perdedor ADOTA a cobrança do vencedor.
    assert asaas_winner.posts == 1
    assert asaas_loser.posts == 0
    assert result is shared
    assert shared.status == "created"
    assert shared.asaas_payment_id == "pay_winner"


def test_zero_match_reconcile_never_regresses_created_by_owner() -> None:
    # O dono do POST grava `created` ENQUANTO um retry reconciliava com zero
    # correspondências: a escrita condicional do retry não pode regredir.
    op = BillingPaymentOperation(
        id=uuid.uuid4(),
        subscription_id="local-sub-1",
        purpose="setup",
        operation_key="pastorai-setup-owner",
        status="creating",
        valor=59.9,
    )
    db = FakeSession(operations=[op])

    class _OwnerFinishesDuringReconcile:
        def find_payments_by_external_reference(self, key: str) -> list[dict]:
            finish_operation(
                db,
                op,
                ("creating", "reconciling"),
                status="created",
                asaas_payment_id="pay_owner",
                invoice_url="https://asaas.test/owner",
            )
            return []

        def create_one_time_charge(self, **kwargs):  # pragma: no cover
            raise AssertionError("retry em reconciliação nunca POSTa")

    with pytest.raises(AsaasError):
        _ensure(db, _OwnerFinishesDuringReconcile())

    assert op.status == "created"  # resultado do dono PRESERVADO
    assert op.asaas_payment_id == "pay_owner"


# ---------------------------------------------------------------------------
# CORRECTIVE-6 P1: helpers da intenção durável de criação de assinatura
# ---------------------------------------------------------------------------
def _sub_op(**over) -> BillingSubscriptionOperation:
    fields = dict(
        id=uuid.uuid4(),
        subscription_id="local-sub-1",
        operation_key="pastorai-subcreate-k1",
        customer_id="cus_1",
        plano="ate_100",
        valor=199.0,
        ciclo="MONTHLY",
        descricao="PastorAI — plano ate_100",
        status="reconciling",
    )
    fields.update(over)
    return BillingSubscriptionOperation(**fields)


def test_find_subscription_operation_by_key_matches_exact_key() -> None:
    op = _sub_op()
    db = _ConfFakeSession(subscription_ops=[op])
    assert find_subscription_operation_by_key(db, "pastorai-subcreate-k1") is op
    assert find_subscription_operation_by_key(db, "outra-chave") is None


def test_subscription_matches_operation_requires_frozen_target() -> None:
    op = _sub_op()
    good = {
        "id": "sub_9",
        "customer": "cus_1",
        "value": 199.0,
        "cycle": "MONTHLY",
        "description": "PastorAI — plano ate_100",
    }
    assert subscription_matches_operation(op, good) is True
    assert subscription_matches_operation(op, {**good, "value": 149.0}) is False
    assert subscription_matches_operation(op, {**good, "customer": "cus_2"}) is False
    assert subscription_matches_operation(op, {**good, "cycle": "YEARLY"}) is False
    assert subscription_matches_operation(
        op, {**good, "description": "outra"}
    ) is False
    assert subscription_matches_operation(op, {}) is False


def test_reconcile_leaves_operation_open_until_adoption() -> None:
    """CORRECTIVE-7: localizar a assinatura remota NÃO fecha a operação.

    A adoção (vínculo local + created) é do chamador, num commit único; um
    crash entre localizar e adotar deixa a operação aberta e o retry
    reconcilia de novo — nunca nasce segunda intenção/POST.
    """
    from app.services.billing import reconcile_subscription_operation

    op = _sub_op(status="reconciling")
    db = _ConfFakeSession(subscription_ops=[op])
    remote = {
        "id": "sub_9",
        "customer": "cus_1",
        "value": 199.0,
        "cycle": "MONTHLY",
        "description": "PastorAI — plano ate_100",
    }

    class _FinderAsaas:
        def __init__(self) -> None:
            self.finds = 0

        def find_subscriptions_by_external_reference(self, ref: str):
            self.finds += 1
            return [remote]

    asaas = _FinderAsaas()
    found = reconcile_subscription_operation(db, asaas, op)

    assert found is remote
    # Operação segue ABERTA e encontrável — nada de created/asaas id aqui.
    assert op.status == "reconciling"
    assert op.asaas_subscription_id is None

    # "Crash" antes da adoção: a repetição localiza de novo, idempotente.
    found2 = reconcile_subscription_operation(db, asaas, op)
    assert found2 is remote
    assert asaas.finds == 2
    assert op.status == "reconciling"


# ---------------------------------------------------------------------------
# CORRECTIVE-8 P1: rejeição DEFINITIVA fecha a operação como failed e LIBERA
# o slot — nunca fica presa em reconciling.
# ---------------------------------------------------------------------------
def test_one_time_charge_definitive_rejection_fails_and_frees_slot() -> None:
    class _RejectingAsaas:
        def create_one_time_charge(self, **kwargs):
            raise AsaasRejectedError("A cobrança precisa ser de pelo menos R$ 5,00")

        def find_payments_by_external_reference(self, key):  # pragma: no cover
            raise AssertionError("rejeição definitiva nunca reconcilia")

    db = FakeSession()
    with pytest.raises(AsaasRejectedError):
        _ensure(db, _RejectingAsaas())

    failed = next(
        o for o in db.added if isinstance(o, BillingPaymentOperation)
    )
    assert failed.status == "failed"
    assert failed.error  # motivo registrado

    # O slot foi LIBERADO: uma nova operação corrigida nasce e completa.
    ok = _OpsAsaas(charge={"id": "pay_fixed", "invoiceUrl": "u"})
    op2 = _ensure(db, ok)
    assert op2 is not failed
    assert op2.status == "created"
    assert ok.posts == 1


def test_plan_change_definitive_put_rejection_fails_and_frees_claim() -> None:
    sub = _plan_sub()
    igreja = SimpleNamespace(id="igreja-1", plano="ate_100")
    db = FakeSession(igreja=igreja)

    class _RejectingPlanAsaas:
        def update_subscription(self, subscription_id, *, valor, descricao):
            raise AsaasRejectedError("O Asaas rejeitou a atualização da assinatura")

        def get_subscription(self, subscription_id):  # pragma: no cover
            raise AssertionError("rejeição definitiva nunca reconcilia")

    with pytest.raises(AsaasRejectedError):
        _change(db, _RejectingPlanAsaas(), sub)

    failed = next(
        o for o in db.added if isinstance(o, BillingPlanChangeOperation)
    )
    assert failed.status == "failed"
    assert failed.error
    # Plano local INTACTO.
    assert sub.plano == "ate_100"
    assert igreja.plano == "ate_100"

    # Claim liberado: a solicitação corrigida completa normalmente.
    ok = _PlanAsaas()
    done = _change(db, ok, sub)
    assert done is not failed
    assert done.status == "completed"
    assert sub.plano == "101_200"
    assert ok.puts == 1


# ---------------------------------------------------------------------------
# CORRECTIVE-9 P1: reconciliação pela IDENTIDADE (preço + descrição). Dois
# planos podem custar o mesmo — só o valor não distingue PUT aplicado de PUT
# perdido.
# ---------------------------------------------------------------------------
def test_same_price_with_old_description_never_completes_reconcile() -> None:
    sub = _plan_sub()
    igreja = SimpleNamespace(id="igreja-1", plano="ate_100")
    db = FakeSession(igreja=igreja)

    # PUT perdido por timeout: a operação fica reconciling com o alvo congelado.
    with pytest.raises(AsaasError):
        _change(db, _PlanAsaas(put_error=True), sub)
    op = next(o for o in db.added if isinstance(o, BillingPlanChangeOperation))
    assert op.status == "reconciling"
    assert op.to_descricao == "PastorAI — plano 101_200"

    # Remoto ANTIGO com o MESMO preço do alvo (planos de preço igual) e a
    # descrição do plano anterior: a RECONCILIAÇÃO não conclui nada. Com o PUT
    # do retry falhando (ambíguo), fica provado que nem o GET nem qualquer
    # outro caminho aplicou o plano local só porque o preço batia.
    stale = _PlanAsaas(
        remote={
            "id": "sub_asaas_1",
            "value": 299.0,
            "description": "PastorAI — plano ate_100",
        },
        put_error=True,
    )
    with pytest.raises(AsaasError):
        _change(db, stale, sub)

    assert op.status == "reconciling"
    assert sub.plano == "ate_100"
    assert sub.limite == 100
    assert igreja.plano == "ate_100"
    assert stale.gets == 1

    # Com a DESCRIÇÃO-alvo, o mesmo preço conclui — o PUT chegou de fato.
    applied = _PlanAsaas(
        remote={
            "id": "sub_asaas_1",
            "value": 299.0,
            "description": "PastorAI — plano 101_200",
        }
    )
    done = _change(db, applied, sub)
    assert done is op
    assert done.status == "completed"
    assert sub.plano == "101_200"
    assert applied.puts == 0  # concluiu por reconciliação, sem novo PUT


def test_put_sends_the_frozen_target_description() -> None:
    sub = _plan_sub()
    db = FakeSession(igreja=SimpleNamespace(id="igreja-1", plano="ate_100"))

    class _CapturingAsaas(_PlanAsaas):
        def __init__(self) -> None:
            super().__init__()
            self.descricoes: list[str] = []

        def update_subscription(self, subscription_id, *, valor, descricao):
            self.descricoes.append(descricao)
            return super().update_subscription(
                subscription_id, valor=valor, descricao=descricao
            )

    asaas = _CapturingAsaas()
    op = _change(db, asaas, sub)

    # A descrição enviada no PUT é EXATAMENTE a congelada na operação — a
    # mesma que a reconciliação confere depois.
    assert asaas.descricoes == ["PastorAI — plano 101_200"]
    assert op.to_descricao == "PastorAI — plano 101_200"


# ---------------------------------------------------------------------------
# REVIEW-10 P2: substituição de intenção `prepared` — atômica e sem retarget
# silencioso da mesma linha.
# ---------------------------------------------------------------------------
def _intent_sub():
    return SimpleNamespace(id="local-sub-1", asaas_customer_id="cus_1")


def _prepared_intent(plano="ate_100", **over):
    fields = dict(
        id=uuid.uuid4(),
        subscription_id="local-sub-1",
        operation_key=f"pastorai-subcreate-{plano}",
        plano=plano,
        valor=199.0,
        limite=100,
        descricao=f"PastorAI - plano {plano}",
        status="prepared",
    )
    fields.update(over)
    return BillingSubscriptionOperation(**fields)


def _prepare(db, sub, plano, valor, limite):
    return prepare_subscription_operation(
        db,
        sub=sub,
        plano=plano,
        valor=valor,
        limite=limite,
        descricao=f"PastorAI - plano {plano}",
    )


def test_prepared_intent_of_another_plan_is_closed_with_a_reason() -> None:
    antiga = _prepared_intent()
    db = _ConfFakeSession(subscription_ops=[antiga])

    nova = _prepare(db, _intent_sub(), "101_200", 299.0, 200)

    assert antiga.status == "superseded"  # terminal, não retargetada
    assert antiga.plano == "ate_100"  # a linha antiga guarda o alvo original
    assert "101_200" in (antiga.error or "")
    assert nova is not antiga
    assert nova.plano == "101_200"
    assert nova.limite == 200
    assert nova.status == "prepared"


def test_supersede_race_keeps_a_single_open_intent() -> None:
    # Duas solicitações concorrentes para o MESMO novo plano: o claim atômico
    # (rowcount) elege um vencedor; o perdedor adota a intenção dele em vez de
    # abrir uma segunda.
    antiga = _prepared_intent()
    db = _ConfFakeSession(subscription_ops=[antiga])

    primeira = _prepare(db, _intent_sub(), "101_200", 299.0, 200)
    segunda = _prepare(db, _intent_sub(), "101_200", 299.0, 200)

    assert primeira is segunda  # uma só intenção sobrevive
    abertas = [
        o
        for o in [antiga, *db.added]
        if isinstance(o, BillingSubscriptionOperation)
        and o.status in ("prepared", "creating", "reconciling")
    ]
    assert len(abertas) == 1


def test_supersede_claim_is_atomic_only_one_winner() -> None:
    # Prova direta do gargalo: dois processos que leram a MESMA linha
    # `prepared` — só um consegue fechá-la.
    antiga = _prepared_intent()
    db = _ConfFakeSession(subscription_ops=[antiga])

    primeiro = claim_transition(db, antiga, "prepared", "superseded", error="a")
    segundo = claim_transition(db, antiga, "prepared", "superseded", error="b")

    assert primeiro is True
    assert segundo is False  # perdeu o rowcount
    assert antiga.error == "a"  # o motivo do vencedor permanece


def test_ambiguous_intent_of_another_plan_raises_conflict() -> None:
    for estado in ("creating", "reconciling"):
        ambigua = _prepared_intent(status=estado)
        db = _ConfFakeSession(subscription_ops=[ambigua])
        with pytest.raises(SubscriptionCreateConflict):
            _prepare(db, _intent_sub(), "101_200", 299.0, 200)
        assert ambigua.status == estado  # intocada


def test_prepared_intent_with_tracked_remote_is_never_superseded() -> None:
    # Defesa extra: `prepared` com assinatura remota rastreada (estado que só
    # existiria por reconciliação parcial) nunca é substituída.
    rastreada = _prepared_intent(asaas_subscription_id="sub_asaas_1")
    db = _ConfFakeSession(subscription_ops=[rastreada])

    with pytest.raises(SubscriptionCreateConflict):
        _prepare(db, _intent_sub(), "101_200", 299.0, 200)

    assert rastreada.status == "prepared"


def test_same_plan_prepared_intent_is_reused() -> None:
    antiga = _prepared_intent()
    db = _ConfFakeSession(subscription_ops=[antiga])

    mesma = _prepare(db, _intent_sub(), "ate_100", 199.0, 100)

    assert mesma is antiga
    assert antiga.status == "prepared"
    assert not [
        o for o in db.added if isinstance(o, BillingSubscriptionOperation)
    ]
