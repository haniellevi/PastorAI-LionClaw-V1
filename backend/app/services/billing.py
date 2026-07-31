"""Shared billing configuration resolution and durable payment operations.

The master owns the default setup fee. A church may carry one explicit override;
tenant checkout requests never provide either value.

As operações duráveis (``billing_payment_operations``) garantem que todo
POST /payments tenha uma intenção persistida ANTES da chamada externa: a
``operation_key`` vira a externalReference exclusiva da cobrança, e um retry
RECONCILIA pela chave em vez de repetir o POST às cegas — resposta perdida
nunca vira cobrança duplicada.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    BillingPaymentOperation,
    BillingPlanChangeOperation,
    BillingSettings,
    BillingSubscriptionOperation,
    Igreja,
    Subscription,
)
from app.services.asaas import AsaasClient, AsaasError, payment_invoice_url

logger = logging.getLogger("pastorai.billing")

# Estados em que a operação ainda "ocupa" o slot (claim) da assinatura+propósito.
OPEN_OPERATION_STATUSES = ("prepared", "creating", "reconciling", "created")
# Estados abertos da troca de plano (claim único por assinatura).
OPEN_PLAN_CHANGE_STATUSES = ("prepared", "processing", "reconciling")
# Estados abertos da CRIAÇÃO de assinatura (claim único por Subscription).
OPEN_SUBSCRIPTION_OP_STATUSES = ("prepared", "creating", "reconciling")


class PlanChangeConflict(Exception):
    """Já existe uma troca de plano EM ANDAMENTO para outro plano."""


class SubscriptionCreateConflict(Exception):
    """Já existe uma criação de assinatura EM ANDAMENTO para outro plano."""


def claim_transition(db: Session, op, from_status: str, to_status: str) -> bool:
    """Transição de estado ATÔMICA de uma operação durável (UPDATE condicional).

    O índice único parcial garante uma única LINHA aberta, mas não serializa a
    transição de estado: dois requests que leram a mesma operação `prepared`
    fariam ambos o POST. Aqui só o rowcount==1 ganha a posse do passo — quem
    perde deve recarregar e RECONCILIAR, nunca chamar a API externa. Também
    protege o resultado do dono: um retry não regride `created` para
    `reconciling` (o WHERE exige o estado de origem).
    """
    result = db.execute(
        update(type(op))
        .where(type(op).id == op.id, type(op).status == from_status)
        .values(status=to_status)
    )
    db.commit()
    claimed = getattr(result, "rowcount", 0) == 1
    if claimed:
        op.status = to_status
    return claimed


def finish_operation(db: Session, op, from_statuses: tuple[str, ...], **values) -> bool:
    """Grava o RESULTADO de uma chamada externa já feita (UPDATE condicional).

    Aceita mais de um estado de origem porque o dono pode ter sido rebaixado a
    `reconciling` por um retry concorrente enquanto a chamada externa ainda
    corria — o resultado real nunca pode ser perdido nesse caso.
    """
    result = db.execute(
        update(type(op))
        .where(type(op).id == op.id, type(op).status.in_(from_statuses))
        .values(**values)
    )
    db.commit()
    done = getattr(result, "rowcount", 0) == 1
    if done:
        for key, value in values.items():
            setattr(op, key, value)
    return done


def get_setup_fee_default(db: Session) -> float:
    """Read the master default, with a temporary legacy environment fallback."""
    settings_row = db.execute(
        select(BillingSettings).where(BillingSettings.id == 1)
    ).scalar_one_or_none()
    if settings_row is not None and settings_row.setup_fee_default is not None:
        return float(settings_row.setup_fee_default)
    return get_settings().asaas_setup_fee


def get_setup_fee_for_igreja(db: Session, igreja: Igreja) -> float:
    """Resolve the church exception before the global master default."""
    if igreja.setup_fee_override is not None:
        return float(igreja.setup_fee_override)
    return get_setup_fee_default(db)


def find_open_operation(
    db: Session, subscription_id, purpose: str
) -> BillingPaymentOperation | None:
    """A operação em andamento (claim) desta assinatura+propósito, se houver."""
    return db.execute(
        select(BillingPaymentOperation).where(
            BillingPaymentOperation.subscription_id == subscription_id,
            BillingPaymentOperation.purpose == purpose,
            BillingPaymentOperation.status.in_(OPEN_OPERATION_STATUSES),
        )
    ).scalar_one_or_none()


def find_operation_for_payment(
    db: Session, *, payment_id: str | None, external_reference: str | None
) -> BillingPaymentOperation | None:
    """Resolve a operação dona de um payment do webhook (id ou operation_key).

    O PROPÓSITO da cobrança vem daqui — nunca é inferido pela ausência de
    ``payment.subscription`` no payload.
    """
    if payment_id:
        op = db.execute(
            select(BillingPaymentOperation).where(
                BillingPaymentOperation.asaas_payment_id == payment_id
            )
        ).scalar_one_or_none()
        if op is not None:
            return op
    if external_reference:
        return db.execute(
            select(BillingPaymentOperation).where(
                BillingPaymentOperation.operation_key == str(external_reference)
            )
        ).scalar_one_or_none()
    return None


def _matches_operation(op: BillingPaymentOperation, payment: dict, *, description: str) -> bool:
    """Uma cobrança encontrada na reconciliação só é adotada se os dados batem."""
    try:
        value_ok = float(payment.get("value")) == float(op.valor)
    except (TypeError, ValueError):
        value_ok = False
    return bool(
        payment.get("id")
        and value_ok
        and payment.get("description") == description
    )


def ensure_payment_operation(
    db: Session,
    asaas: AsaasClient,
    *,
    sub: Subscription,
    purpose: str,
    valor: float,
    description: str,
    customer_id: str,
    source_payment_id: str | None = None,
) -> BillingPaymentOperation:
    """Garante UMA cobrança avulsa para (assinatura, propósito), retry-safe.

    Fluxo: claim da operação aberta (ou criação de uma nova, persistida antes
    de qualquer chamada externa) → reconciliação por operation_key quando o
    resultado do POST anterior é desconhecido → POST /payments apenas quando a
    operação está comprovadamente sem cobrança. Timeout/5xx ambíguo após o
    POST marca `reconciling`: retries seguintes só reconciliam — nunca um novo
    POST automático.
    """
    op = find_open_operation(db, sub.id, purpose)

    if op is None:
        op = BillingPaymentOperation(
            subscription_id=sub.id,
            purpose=purpose,
            operation_key=f"pastorai-{purpose}-{uuid.uuid4()}",
            source_payment_id=source_payment_id,
            status="prepared",
            valor=valor,
        )
        db.add(op)
        try:
            # O índice único parcial (subscription_id, purpose | status aberto)
            # faz o claim atômico: a corrida perde aqui e adota a operação do
            # vencedor em vez de criar uma segunda cobrança.
            db.commit()
        except Exception:
            db.rollback()
            op = find_open_operation(db, sub.id, purpose)
            if op is None:
                raise

    if op.status == "created" and op.asaas_payment_id:
        return op  # cobrança já existe e está rastreada

    if op.status in ("creating", "reconciling"):
        return _reconcile_payment_operation(
            db, asaas, op, description=description, customer_id=customer_id
        )

    # prepared: ainda não houve POST. O claim da transição é ATÔMICO — dois
    # requests que adotaram a MESMA operação `prepared` não podem ambos
    # postar; quem perde o rowcount reconcilia em vez de chamar a API.
    if not claim_transition(db, op, "prepared", "creating"):
        db.rollback()
        current = find_open_operation(db, sub.id, purpose)
        if current is None:
            raise AsaasError("Cobrança em processamento — tente novamente")
        if current.status in ("creating", "reconciling"):
            # O dono pode estar com o POST em voo NESTE instante: não toca o
            # estado nem reconcilia por cima — o retry seguinte resolve.
            raise AsaasError("Cobrança em processamento — tente novamente")
        return current  # created por outro request
    try:
        charge = asaas.create_one_time_charge(
            customer_id=customer_id,
            valor=valor,
            description=description,
            external_reference=op.operation_key,
        )
    except AsaasError:
        # Resultado ambíguo (o POST pode ter chegado): daqui em diante só
        # reconciliação — nunca outro POST automático.
        claim_transition(db, op, "creating", "reconciling")
        raise
    if charge is None:
        # Sandbox (sends bloqueados): nada foi criado — a operação volta a
        # `prepared` e pode tentar de novo quando os envios forem permitidos.
        claim_transition(db, op, "creating", "prepared")
        return op
    # Resultado REAL do POST: gravado mesmo se um retry concorrente rebaixou o
    # estado para `reconciling` enquanto a chamada corria.
    finish_operation(
        db,
        op,
        ("creating", "reconciling"),
        status="created",
        asaas_payment_id=str(charge["id"]),
        invoice_url=payment_invoice_url(charge),
    )
    return op


def _reconcile_payment_operation(
    db: Session,
    asaas: AsaasClient,
    op: BillingPaymentOperation,
    *,
    description: str,
    customer_id: str,
) -> BillingPaymentOperation:
    """Resolve uma operação cujo POST anterior tem resultado DESCONHECIDO.

    Procura pela operation_key e adota apenas a cobrança que bate com o alvo
    congelado. Nunca repete o POST às cegas; toda escrita de estado é
    condicional para nunca sobrescrever o resultado gravado pelo dono do POST.
    """
    matches = [
        p
        for p in asaas.find_payments_by_external_reference(op.operation_key)
        if _matches_operation(op, p, description=description)
        and (not p.get("customer") or str(p.get("customer")) == str(customer_id))
    ]
    if len(matches) == 1:
        finish_operation(
            db,
            op,
            ("creating", "reconciling"),
            status="created",
            asaas_payment_id=str(matches[0]["id"]),
            invoice_url=payment_invoice_url(matches[0]),
        )
        return op
    if len(matches) > 1:
        finish_operation(db, op, ("creating", "reconciling"), status="failed")
        logger.warning("Billing operation ambiguous on reconcile; marked failed")
        raise AsaasError("Reconciliação ambígua da cobrança — intervenção manual")
    # 0 correspondências: mantém reconciling e falha com segurança — o próximo
    # retry reconcilia de novo (sem POST automático). Condicional: nunca
    # regride um `created` gravado pelo dono do POST em paralelo.
    claim_transition(db, op, "creating", "reconciling")
    raise AsaasError("Cobrança em reconciliação no Asaas — tente novamente")


def find_open_plan_change(
    db: Session, subscription_id
) -> BillingPlanChangeOperation | None:
    """A troca de plano em andamento desta assinatura, se houver."""
    return db.execute(
        select(BillingPlanChangeOperation).where(
            BillingPlanChangeOperation.subscription_id == subscription_id,
            BillingPlanChangeOperation.status.in_(OPEN_PLAN_CHANGE_STATUSES),
        )
    ).scalar_one_or_none()


def _plan_change_matches_remote(
    op: BillingPlanChangeOperation, remote: dict | None
) -> bool:
    """O estado remoto já reflete o alvo congelado da operação?"""
    if not isinstance(remote, dict):
        return False
    try:
        return float(remote.get("value")) == float(op.to_preco)
    except (TypeError, ValueError):
        return False


def _complete_plan_change(
    db: Session, op: BillingPlanChangeOperation, sub: Subscription
) -> None:
    """Aplica o plano local SOMENTE após confirmação/reconciliação remota."""
    sub.plano = op.to_plano
    sub.limite = op.to_limite
    igreja = db.execute(
        select(Igreja).where(Igreja.id == sub.igreja_id)
    ).scalar_one_or_none()
    if igreja is not None:
        igreja.plano = op.to_plano
    op.status = "completed"
    db.commit()


def ensure_plan_change_operation(
    db: Session,
    asaas: AsaasClient,
    *,
    sub: Subscription,
    to_plano: str,
    to_preco: float,
    to_limite: int | None,
    origin: str = "manual",
) -> BillingPlanChangeOperation:
    """Troca de plano durável: PUT na assinatura Asaas EXISTENTE, retry-safe.

    O alvo (plano/preço/limite) é congelado e persistido ANTES do PUT; um
    retry com a operação em `processing`/`reconciling` RECONCILIA pelo GET da
    assinatura (valor remoto == alvo) em vez de repetir o PUT às cegas. O
    plano/limite locais só mudam após confirmação ou reconciliação. Falha
    remota preserva o plano atual. Nunca cria outra recorrência.
    """
    op = find_open_plan_change(db, sub.id)

    if op is not None and op.to_plano != to_plano:
        # Duas solicitações concorrentes para planos DIFERENTES nunca se
        # atropelam silenciosamente: a segunda é rejeitada com conflito.
        raise PlanChangeConflict(
            f"Já existe uma troca em andamento para o plano {op.to_plano}"
        )

    if op is None:
        op = BillingPlanChangeOperation(
            subscription_id=sub.id,
            asaas_subscription_id=str(sub.asaas_subscription_id),
            from_plano=sub.plano,
            to_plano=to_plano,
            to_preco=to_preco,
            to_limite=to_limite,
            origin=origin,
            status="prepared",
            # A notificação do auto-upgrade tem entrega DURÁVEL própria; a
            # troca manual não notifica.
            notify_status="pending" if origin == "autoupgrade" else "skipped",
        )
        db.add(op)
        try:
            # Índice único parcial (subscription_id | status aberto) = claim
            # atômico: a corrida perde aqui e adota a operação do vencedor.
            db.commit()
        except Exception:
            db.rollback()
            op = find_open_plan_change(db, sub.id)
            if op is None:
                raise
            if op.to_plano != to_plano:
                raise PlanChangeConflict(
                    f"Já existe uma troca em andamento para o plano {op.to_plano}"
                ) from None

    if op.status in ("processing", "reconciling"):
        # Resultado do PUT anterior é DESCONHECIDO: reconcilia pelo GET antes
        # de qualquer nova escrita remota.
        remote = asaas.get_subscription(op.asaas_subscription_id)
        if _plan_change_matches_remote(op, remote):
            _complete_plan_change(db, op, sub)
            return op
        op.status = "reconciling"
        db.commit()
        raise AsaasError(
            "Troca de plano em reconciliação no Asaas — tente novamente"
        )

    # prepared: marca a intenção e faz exatamente UM PUT. Claim ATÔMICO — o
    # worker e um request manual que leram a mesma operação `prepared` nunca
    # fazem dois PUTs: quem perde o rowcount reconcilia no retry.
    if not claim_transition(db, op, "prepared", "processing"):
        db.rollback()
        raise AsaasError("Troca de plano em processamento — tente novamente")
    try:
        remote = asaas.update_subscription(
            op.asaas_subscription_id,
            valor=float(op.to_preco),
            descricao=f"PastorAI — plano {op.to_plano}",
        )
    except AsaasError:
        # Ambíguo (o PUT pode ter chegado): plano local fica INTACTO e o
        # retry reconcilia — nunca outro PUT automático imediato.
        claim_transition(db, op, "processing", "reconciling")
        raise
    if remote is None:
        # Sandbox (sends bloqueados): não há remoto a confirmar — completa
        # localmente para o fluxo de desenvolvimento seguir utilizável.
        _complete_plan_change(db, op, sub)
        return op
    _complete_plan_change(db, op, sub)
    return op


def find_open_subscription_operation(
    db: Session, subscription_id
) -> BillingSubscriptionOperation | None:
    """A criação de assinatura em andamento desta Subscription, se houver."""
    return db.execute(
        select(BillingSubscriptionOperation).where(
            BillingSubscriptionOperation.subscription_id == subscription_id,
            BillingSubscriptionOperation.status.in_(OPEN_SUBSCRIPTION_OP_STATUSES),
        )
    ).scalar_one_or_none()


def find_subscription_operation_by_key(
    db: Session, operation_key: str
) -> BillingSubscriptionOperation | None:
    """Resolve a intenção de criação pela operation_key (webhook novo formato).

    A externalReference das assinaturas criadas após CORRECTIVE-6 é a
    operation_key da intenção durável — o webhook a resolve por aqui; o
    formato legado (igreja_id) continua no fallback do próprio webhook.
    """
    return db.execute(
        select(BillingSubscriptionOperation).where(
            BillingSubscriptionOperation.operation_key == str(operation_key)
        )
    ).scalar_one_or_none()


def subscription_matches_operation(
    op: BillingSubscriptionOperation, remote: dict
) -> bool:
    """A assinatura achada na reconciliação bate com o alvo CONGELADO?

    Adota somente quando customer, valor, ciclo e descrição correspondem — a
    externalReference localiza candidatas, mas não é prova de posse.
    """
    if not isinstance(remote, dict) or not remote.get("id"):
        return False
    try:
        value_ok = float(remote.get("value")) == float(op.valor)
    except (TypeError, ValueError):
        value_ok = False
    customer_ok = (
        not op.customer_id
        or not remote.get("customer")
        or str(remote.get("customer")) == str(op.customer_id)
    )
    cycle_ok = str(remote.get("cycle") or "").upper() == str(op.ciclo).upper()
    return bool(
        value_ok
        and customer_ok
        and cycle_ok
        and remote.get("description") == op.descricao
    )


def prepare_subscription_operation(
    db: Session,
    *,
    sub: Subscription,
    plano: str,
    valor: float,
    descricao: str,
    ciclo: str = "MONTHLY",
) -> BillingSubscriptionOperation:
    """Garante UMA intenção durável de criação para esta Subscription.

    Persistida ANTES de qualquer chamada externa; o claim é o índice único
    parcial (subscription_id | status aberto). Uma intenção aberta para OUTRO
    plano nunca é sobrescrita silenciosamente — conflito explícito.
    """
    op = find_open_subscription_operation(db, sub.id)
    if op is not None and op.plano != plano:
        raise SubscriptionCreateConflict(
            f"Já existe uma contratação em andamento para o plano {op.plano}"
        )
    if op is not None:
        return op
    op = BillingSubscriptionOperation(
        subscription_id=sub.id,
        operation_key=f"pastorai-subcreate-{uuid.uuid4()}",
        customer_id=sub.asaas_customer_id,
        plano=plano,
        valor=valor,
        ciclo=ciclo,
        descricao=descricao,
        status="prepared",
    )
    db.add(op)
    try:
        db.commit()
    except Exception:
        db.rollback()
        op = find_open_subscription_operation(db, sub.id)
        if op is None:
            raise
        if op.plano != plano:
            raise SubscriptionCreateConflict(
                f"Já existe uma contratação em andamento para o plano {op.plano}"
            ) from None
    return op


def reconcile_subscription_operation(
    db: Session, asaas: AsaasClient, op: BillingSubscriptionOperation
) -> dict | None:
    """Localiza a assinatura de uma criação cujo POST tem resultado DESCONHECIDO.

    Busca GET /subscriptions?externalReference=operation_key e devolve somente
    a assinatura que corresponda ao alvo congelado — SEM fechar a operação:
    ela permanece aberta (encontrável) até o chamador COMMITAR a adoção
    (vínculo na Subscription local + operação `created`) numa transação única.
    Um crash entre localizar e adotar deixa a operação aberta e o retry
    reconcilia de novo — nunca nasce uma segunda intenção (e portanto nunca um
    segundo POST). 0 correspondências mantém `reconciling` e NUNCA repete o
    POST automaticamente; mais de uma é ambiguidade real → `failed`.
    """
    matches = [
        s
        for s in asaas.find_subscriptions_by_external_reference(op.operation_key)
        if subscription_matches_operation(op, s)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        finish_operation(db, op, ("creating", "reconciling"), status="failed")
        logger.warning("Subscription create ambiguous on reconcile; marked failed")
        raise AsaasError(
            "Reconciliação ambígua da assinatura — intervenção manual"
        )
    claim_transition(db, op, "creating", "reconciling")
    return None
