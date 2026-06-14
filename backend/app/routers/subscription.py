"""Subscription router — Asaas billing + webhook (US-36 / RF-42).

Endpoints:
  - GET  /subscription          current subscription + plan/limit/usage (admin)
  - POST /subscription          create an Asaas checkout with a setup fee (admin)
  - POST /subscription/webhook  Asaas events -> update status (token-gated)

The autoupgrade itself is performed by the DB trigger `trg_subscription_autoupgrade`
when the people count crosses the plan limit; this router detects the resulting
plan change and notifies the admin once (idempotent), and keeps the subscription
status in sync from Asaas payment events. The webhook is public but gated by the
shared `asaas-access-token` header instead of Clerk auth.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.masking import log_agent_event
from app.config import get_settings
from app.db.models import (
    AgentConversationLog,
    AppUser,
    Igreja,
    Subscription,
    UserRole,
    WhatsappConnection,
)
from app.db.session import get_db
from app.deps import ADMIN_ROLE, CurrentUser, require_role
from app.domain.billing import plan_limit, plan_price
from app.routers._common import ensure_tenant_context
from app.services.asaas import (
    AsaasClient,
    AsaasError,
    get_asaas_client,
    map_payment_status,
    verify_webhook_token,
)
from app.services.evolution import EvolutionClient, EvolutionError, get_evolution_client

logger = logging.getLogger("pastorai.subscription")

router = APIRouter(prefix="/subscription", tags=["subscription"])

VALID_PLANOS = {"ate_100", "101_200", "acima_201"}


class SubscriptionOut(BaseModel):
    plano: str
    status: str | None = None
    pessoas: int | None = None
    limite: int | None = None
    proximaCobranca: str | None = None  # noqa: N815
    setupPago: bool  # noqa: N815

    @classmethod
    def from_model(cls, s: Subscription) -> "SubscriptionOut":
        return cls(
            plano=s.plano,
            status=s.status,
            pessoas=s.pessoas,
            limite=s.limite,
            proximaCobranca=s.proxima_cobranca.isoformat()
            if s.proxima_cobranca
            else None,
            setupPago=s.setup_pago,
        )


class CheckoutRequest(BaseModel):
    plano: str
    cpfCnpj: str | None = Field(default=None, max_length=20)  # noqa: N815

    @field_validator("plano")
    @classmethod
    def _plano(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in VALID_PLANOS:
            raise ValueError(f"plano inválido: {value}")
        return value


class CheckoutResponse(BaseModel):
    status: str
    invoiceUrl: str | None = None  # noqa: N815
    asaasSubscriptionId: str | None = None  # noqa: N815


class WebhookResponse(BaseModel):
    received: bool
    status: str | None = None


def _admin_phones(db: Session, igreja_id: uuid.UUID) -> list[str]:
    """Phones of admins (via their linked pessoa) for upgrade notifications."""
    admin_ids = db.execute(
        select(UserRole.user_id).where(
            UserRole.igreja_id == igreja_id, UserRole.papel == ADMIN_ROLE
        )
    ).scalars().all()
    phones: list[str] = []
    for uid in set(admin_ids):
        app_user = db.get(AppUser, uid)
        if app_user and app_user.pessoa_id:
            from app.db.models import Pessoa  # noqa: PLC0415

            pessoa = db.get(Pessoa, app_user.pessoa_id)
            if pessoa and pessoa.telefone:
                phones.append(pessoa.telefone)
    return phones


def notify_autoupgrade(
    db: Session, igreja_id: uuid.UUID, evolution: EvolutionClient
) -> bool:
    """Notify the admin once when the plan was promoted by the autoupgrade trigger.

    Idempotent: a `subscription_upgrade:<plano>` event in agent_conversation_logs
    marks a plan as already announced, so repeated calls do not re-notify.
    Returns True when a new notification was emitted.
    """
    sub = db.execute(
        select(Subscription).where(Subscription.igreja_id == igreja_id)
    ).scalar_one_or_none()
    if sub is None:
        return False

    evento = f"subscription_upgrade:{sub.plano}"
    already = db.execute(
        select(AgentConversationLog.id).where(
            AgentConversationLog.igreja_id == igreja_id,
            AgentConversationLog.evento == evento,
        )
    ).first()
    if already is not None:
        return False

    # Only notify when there is an upgrade marker to record beyond the base tier.
    if sub.plano == "ate_100":
        return False

    conn = db.execute(
        select(WhatsappConnection).where(WhatsappConnection.igreja_id == igreja_id)
    ).scalar_one_or_none()
    instance = conn.instance if conn else None

    texto = (
        "Aviso de assinatura: seu plano foi atualizado automaticamente para "
        f"'{sub.plano}' por aumento do número de pessoas. 🙏"
    )
    if instance:
        for phone in _admin_phones(db, igreja_id):
            try:
                evolution.send_text(instance, phone, texto)
            except EvolutionError:
                logger.warning("Autoupgrade notification failed to an admin")

    log_agent_event(
        db, igreja_id=igreja_id, evento=evento, payload={"plano": sub.plano}
    )
    db.commit()
    return True


@router.get("", response_model=SubscriptionOut)
def get_subscription(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
    evolution: EvolutionClient = Depends(get_evolution_client),
) -> SubscriptionOut:
    """Return the tenant's subscription, notifying any pending autoupgrade."""
    ensure_tenant_context(db, current_user)
    igreja_uuid = uuid.UUID(current_user.igreja_id)

    sub = db.execute(
        select(Subscription).where(Subscription.igreja_id == igreja_uuid)
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assinatura não encontrada",
        )

    # Surface the trigger-driven autoupgrade to the admin (idempotent).
    notify_autoupgrade(db, igreja_uuid, evolution)
    ensure_tenant_context(db, current_user)
    db.refresh(sub)
    return SubscriptionOut.from_model(sub)


@router.post("", response_model=CheckoutResponse)
def create_checkout(
    payload: CheckoutRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
    asaas: AsaasClient = Depends(get_asaas_client),
) -> CheckoutResponse:
    """Create an Asaas checkout (subscription + one-time setup fee)."""
    ensure_tenant_context(db, current_user)
    igreja_uuid = uuid.UUID(current_user.igreja_id)

    sub = db.execute(
        select(Subscription).where(Subscription.igreja_id == igreja_uuid)
    ).scalar_one_or_none()
    if sub is None:
        sub = Subscription(igreja_id=igreja_uuid, plano=payload.plano)
        db.add(sub)

    setup_fee = 0.0 if sub.setup_pago else get_settings().asaas_setup_fee

    try:
        result = asaas.create_checkout(
            nome=current_user.nome,
            email=current_user.email,
            plano=payload.plano,
            valor=plan_price(payload.plano),
            setup_fee=setup_fee,
            cpf_cnpj=payload.cpfCnpj,
            external_reference=str(igreja_uuid),
        )
    except AsaasError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível criar o checkout no Asaas",
        ) from exc

    sub.plano = payload.plano
    sub.limite = plan_limit(payload.plano)
    sub.status = result.status
    sub.asaas_customer_id = result.customer_id
    sub.asaas_subscription_id = result.subscription_id
    if result.setup_charge_id:
        sub.setup_pago = False  # paid only once Asaas confirms via webhook
    db.commit()

    return CheckoutResponse(
        status=result.status,
        invoiceUrl=result.invoice_url,
        asaasSubscriptionId=result.subscription_id,
    )


class AsaasWebhookEvent(BaseModel):
    """Subset of the Asaas webhook payload we consume."""

    event: str | None = None
    payment: dict | None = None
    subscription: dict | None = None


@router.post("/webhook", response_model=WebhookResponse)
def asaas_webhook(
    payload: AsaasWebhookEvent,
    db: Session = Depends(get_db),
    asaas_access_token: str | None = Header(default=None),
) -> WebhookResponse:
    """Apply an Asaas payment/subscription event to the subscription status.

    The webhook is gated by the shared `asaas-access-token` header (constant-time
    comparison). The igreja is resolved from the payment/subscription
    externalReference (set to the igreja id at checkout). Unknown statuses are
    acknowledged without changing state.
    """
    settings = get_settings()
    if not verify_webhook_token(settings.asaas_webhook_token, asaas_access_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Assinatura de webhook inválida",
        )

    obj = payload.payment or payload.subscription or {}
    external_ref = obj.get("externalReference")
    asaas_sub_id = obj.get("subscription") or obj.get("id")
    raw_status = obj.get("status") or payload.event
    new_status = map_payment_status(raw_status)

    sub: Subscription | None = None
    if external_ref:
        try:
            igreja_uuid = uuid.UUID(str(external_ref))
            sub = db.execute(
                select(Subscription).where(Subscription.igreja_id == igreja_uuid)
            ).scalar_one_or_none()
        except ValueError:
            sub = None
    if sub is None and asaas_sub_id:
        sub = db.execute(
            select(Subscription).where(
                Subscription.asaas_subscription_id == str(asaas_sub_id)
            )
        ).scalar_one_or_none()

    if sub is None:
        logger.info("Asaas webhook for unknown subscription; acknowledged")
        return WebhookResponse(received=True, status=None)

    if new_status is not None:
        sub.status = new_status
        # First confirmed payment settles the setup fee.
        if new_status == "ativa":
            sub.setup_pago = True
        # Reflect billing status onto the igreja access gate (US-35).
        igreja = db.get(Igreja, sub.igreja_id)
        if igreja is not None:
            igreja.status = "ativa" if new_status == "ativa" else "inadimplente"
        db.commit()

    return WebhookResponse(received=True, status=new_status)
