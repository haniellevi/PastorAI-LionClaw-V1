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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import BillingPaymentOperation, BillingSettings, Igreja, Subscription
from app.services.asaas import AsaasClient, AsaasError, payment_invoice_url

logger = logging.getLogger("pastorai.billing")

# Estados em que a operação ainda "ocupa" o slot (claim) da assinatura+propósito.
OPEN_OPERATION_STATUSES = ("prepared", "creating", "reconciling", "created")


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
        # Resultado do POST anterior é DESCONHECIDO: reconcilia pela
        # operation_key. Nunca repete o POST às cegas.
        matches = [
            p
            for p in asaas.find_payments_by_external_reference(op.operation_key)
            if _matches_operation(op, p, description=description)
            and (not p.get("customer") or str(p.get("customer")) == str(customer_id))
        ]
        if len(matches) == 1:
            op.asaas_payment_id = str(matches[0]["id"])
            op.invoice_url = payment_invoice_url(matches[0])
            op.status = "created"
            db.commit()
            return op
        if len(matches) > 1:
            op.status = "failed"
            db.commit()
            logger.warning("Billing operation ambiguous on reconcile; marked failed")
            raise AsaasError("Reconciliação ambígua da cobrança — intervenção manual")
        # 0 correspondências: mantém reconciling e falha com segurança — o
        # próximo retry reconcilia de novo (sem POST automático).
        op.status = "reconciling"
        db.commit()
        raise AsaasError("Cobrança em reconciliação no Asaas — tente novamente")

    # prepared: ainda não houve POST. Marca a intenção e chama exatamente uma vez.
    op.status = "creating"
    db.commit()
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
        op.status = "reconciling"
        db.commit()
        raise
    if charge is None:
        # Sandbox (sends bloqueados): nada foi criado — a operação volta a
        # `prepared` e pode tentar de novo quando os envios forem permitidos.
        op.status = "prepared"
        db.commit()
        return op
    op.asaas_payment_id = str(charge["id"])
    op.invoice_url = payment_invoice_url(charge)
    op.status = "created"
    db.commit()
    return op
