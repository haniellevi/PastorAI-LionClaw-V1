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


# ---------------------------------------------------------------------------
# Troca de plano durável (PLAN-CHANGE-SAFETY-1): PUT na assinatura EXISTENTE,
# vigência no próximo ciclo, retry por reconciliação — nunca 2ª recorrência.
# ---------------------------------------------------------------------------
from app.db.models import BillingPlanChangeOperation, Subscription  # noqa: E402
from app.services.billing import (  # noqa: E402
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
    def __init__(self, *, remote: dict | None = None, put_error: bool = False) -> None:
        self.puts = 0
        self.gets = 0
        self._remote = remote
        self._put_error = put_error

    def update_subscription(self, subscription_id: str, *, valor: float, descricao: str):
        self.puts += 1
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
    confirming = _PlanAsaas(remote={"id": "sub_asaas_1", "value": 299.0})
    done = _change(db, confirming, sub)

    assert done is op
    assert done.status == "completed"
    assert sub.plano == "101_200"
    assert confirming.puts == 0
    assert confirming.gets == 1


def test_plan_change_divergent_remote_stays_reconciling() -> None:
    sub = _plan_sub()
    op = BillingPlanChangeOperation(
        subscription_id="local-sub-1",
        asaas_subscription_id="sub_asaas_1",
        from_plano="ate_100",
        to_plano="101_200",
        to_preco=299.0,
        to_limite=200,
        status="reconciling",
    )
    db = FakeSession(plan_changes=[op])
    # Remoto ainda mostra o valor antigo: não conclui, não aplica local.
    asaas = _PlanAsaas(remote={"id": "sub_asaas_1", "value": 199.0})

    with pytest.raises(AsaasError):
        _change(db, asaas, sub)

    assert op.status == "reconciling"
    assert sub.plano == "ate_100"
    assert asaas.puts == 0


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
    asaas = _PlanAsaas(remote={"id": "sub_asaas_1", "value": 299.0})

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
    claim_transition,
    find_subscription_operation_by_key,
    finish_operation,
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
from app.services.asaas import AsaasRejectedError  # noqa: E402


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
