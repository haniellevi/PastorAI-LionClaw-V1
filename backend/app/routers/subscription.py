"""Subscription router — Asaas billing + webhook (US-36 / RF-42).

Endpoints:
  - GET  /subscription          current subscription + plan/limit/usage (admin)
  - POST /subscription          create an Asaas checkout with a setup fee (admin)
  - GET  /subscription/planos   active plan catalog + setup fee (admin)
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

from app.agent.masking import release_agent_event, reserve_agent_event
from app.config import get_settings
from app.db.models import (
    AgentConversationLog,
    AppUser,
    Igreja,
    Plano,
    Subscription,
    UserRole,
    WhatsappConnection,
)
from app.db.rls_observability import log_if_not_scoped
from app.db.session import get_db
from app.deps import ADMIN_ROLE, CurrentUser, require_owner
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
        # Só normaliza; a existência (e se está ativo) no catálogo `planos` é
        # checada no handler contra o banco — ver _plano_ativo_or_422.
        value = value.strip().lower()
        if not value:
            raise ValueError("plano obrigatório")
        return value


class CheckoutResponse(BaseModel):
    status: str
    invoiceUrl: str | None = None  # noqa: N815
    asaasSubscriptionId: str | None = None  # noqa: N815


class WebhookResponse(BaseModel):
    received: bool
    status: str | None = None


class PlanoPublicOut(BaseModel):
    """Um plano do catálogo `planos`, como visto pela igreja (só planos ativos)."""

    codigo: str
    nome: str
    limitePessoas: int | None = None  # noqa: N815 - None = ilimitado
    precoMensal: float  # noqa: N815


class PlanCatalogOut(BaseModel):
    planos: list[PlanoPublicOut]
    setupFee: float  # noqa: N815


def _plano_ativo_or_422(db: Session, codigo: str) -> Plano:
    """Busca o plano ATIVO no catálogo `planos` (senão 422).

    Fonte única de preço/limite do checkout (migration 0012) — edição do master
    em /admin/planos vale na próxima contratação sem mudança de código.
    """
    plano = db.execute(
        select(Plano).where(Plano.codigo == codigo, Plano.ativo.is_(True))
    ).scalar_one_or_none()
    if plano is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"plano inválido: {codigo}",
        )
    return plano


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


def _autoupgrade_event_name(plano: str) -> str:
    """Stable dedupe key for one autoupgrade notification (SEC-4).

    Must match the `subscription\\_upgrade:%` predicate of the partial unique
    index `agent_conversation_logs_idem_marker_uidx`.
    """
    return f"subscription_upgrade:{plano}"


def notify_autoupgrade(
    db: Session, igreja_id: uuid.UUID, evolution: EvolutionClient
) -> bool:
    """Notify the admin once when the plan was promoted by the autoupgrade trigger.

    Idempotent: a `subscription_upgrade:<plano>` event in agent_conversation_logs
    marks a plan as already announced, so repeated calls do not re-notify.
    Returns True when a new notification was emitted.

    SEC-4: a reserva do marcador (`reserve_agent_event`, INSERT + commit
    imediato) acontece ANTES do `send_text` — nunca depois. Se a reserva
    perder a corrida (outro processo já reservou o MESMO marcador), retorna
    sem enviar; nenhuma transação fica aberta durante a chamada externa. Se o
    envio falhar pra todo destinatário tentado, a reserva é liberada
    (`release_agent_event`) pra próxima chamada tentar de novo
    (at-least-once — ver decisão no PR).

    Gap-2 (revisão SEC-4): TODAS as leituras (conexão WhatsApp, telefones de
    admin) acontecem ANTES da reserva — não depois. `db.execute`/`db.get`
    após um `commit()` reabre implicitamente uma transação (autobegin do
    SQLAlchemy); fazer essas leituras depois da reserva deixaria essa
    transação aberta durante o `send_text` (chamada externa). Lendo antes e
    guardando só valores simples (str), nenhuma query roda entre a reserva e
    o envio.
    """
    sub = db.execute(
        select(Subscription).where(Subscription.igreja_id == igreja_id)
    ).scalar_one_or_none()
    if sub is None:
        return False

    evento = _autoupgrade_event_name(sub.plano)
    already = db.execute(
        select(AgentConversationLog.id).where(
            AgentConversationLog.igreja_id == igreja_id,
            AgentConversationLog.evento == evento,
        )
    ).first()
    if already is not None:
        return False  # saída antecipada barata

    # Only notify when there is an upgrade marker to record beyond the base tier.
    if sub.plano == "ate_100":
        return False

    # Lidas ANTES da reserva (gap-2): só valores simples sobrevivem até o
    # send, nenhuma query fica pendurada numa transação aberta pelo envio.
    conn = db.execute(
        select(WhatsappConnection).where(WhatsappConnection.igreja_id == igreja_id)
    ).scalar_one_or_none()
    instance = conn.instance if conn else None
    phones = _admin_phones(db, igreja_id)

    marker = reserve_agent_event(
        db, igreja_id=igreja_id, evento=evento, payload={"plano": sub.plano}
    )
    if marker is None:
        # Perdeu a corrida: outro processo já reserva este marcador.
        return False

    texto = (
        "Aviso de assinatura: seu plano foi atualizado automaticamente para "
        f"'{sub.plano}' por aumento do número de pessoas. 🙏"
    )
    attempted = False
    sent_any = False
    if instance:
        for phone in phones:
            attempted = True
            try:
                evolution.send_text(instance, phone, texto)
                sent_any = True
            except EvolutionError:
                logger.warning("Autoupgrade notification failed to an admin")

    if attempted and not sent_any:
        # Falha total do envio: libera a reserva pra próxima chamada tentar.
        release_agent_event(db, marker)
        return False

    return True


@router.get("", response_model=SubscriptionOut)
def get_subscription(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_owner),
    evolution: EvolutionClient = Depends(get_evolution_client),
) -> SubscriptionOut:
    """Return the tenant's subscription, notifying any pending autoupgrade."""
    # Sinal de observabilidade (PR1 / feat-004) ligado a este caminho HTTP de
    # amostra do seam: se a sessão marcada por get_current_user NÃO estiver
    # tenant-scoped (perda de contexto / BYPASSRLS inesperado / fallback), emite
    # log estruturado sem PII (só source/role/igreja_id). É a fonte do gatilho de
    # rollback da SPEC §9/10 (evidência de leitura cross-tenant nos logs).
    log_if_not_scoped(db, source="http")
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
    # notify_autoupgrade comita internamente; a re-asserção manual do contexto
    # pós-commit foi REMOVIDA (PR3-A, caso âncora): o listener after_begin (D2)
    # reabre a transação já escopada assim que db.refresh() emite o próximo BEGIN,
    # pois a sessão está marcada por get_current_user. expire_on_commit=False
    # (session.py) garante que só o refresh reabre a transação — objetos já
    # carregados não expiram no commit. A estrutura (seam) substitui a convenção.
    notify_autoupgrade(db, igreja_uuid, evolution)
    db.refresh(sub)
    return SubscriptionOut.from_model(sub)


@router.post("", response_model=CheckoutResponse)
def create_checkout(
    payload: CheckoutRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_owner),
    asaas: AsaasClient = Depends(get_asaas_client),
) -> CheckoutResponse:
    """Create an Asaas checkout (subscription + one-time setup fee).

    Preço e limite vêm do catálogo `planos` (fonte editada pelo master), não de
    valores fixos no código — ver _plano_ativo_or_422.
    """
    plano_row = _plano_ativo_or_422(db, payload.plano)
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
            valor=float(plano_row.preco_mensal),
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
    sub.limite = plano_row.limite_pessoas
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


@router.get("/planos", response_model=PlanCatalogOut)
def list_planos_disponiveis(
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_owner),
) -> PlanCatalogOut:
    """Catálogo de planos ATIVOS (tabela `planos`, editada pelo master) + taxa de
    setup vigente — a tela de Assinatura da igreja usa isto em vez de um
    catálogo fixo no frontend (antes espelhava `PLAN_PRICE`/`PLAN_CATALOG`
    hardcoded, que desalinhava do preço editado no console master).
    """
    rows = db.execute(
        select(Plano).where(Plano.ativo.is_(True)).order_by(Plano.ordem, Plano.codigo)
    ).scalars().all()
    planos = [
        PlanoPublicOut(
            codigo=p.codigo,
            nome=p.nome,
            limitePessoas=p.limite_pessoas,
            precoMensal=float(p.preco_mensal),
        )
        for p in rows
    ]
    return PlanCatalogOut(planos=planos, setupFee=get_settings().asaas_setup_fee)


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
        # Reflect billing status onto the igreja access gate (US-35) — só as
        # transições FINANCEIRAS: pagamento confirmado tira a igreja de
        # "inadimplente" e vencimento explícito tira de "ativa". Estados
        # administrativos do console master ("suspensa", "aguardando_aprovacao"
        # — a aprovação também semeia permissões/AgentConfig) nunca são
        # sobrescritos por webhook, e "pendente" (fatura recém-emitida)
        # preserva qualquer igreja.status.
        if new_status in ("ativa", "inadimplente"):
            igreja = db.get(Igreja, sub.igreja_id)
            expected = "inadimplente" if new_status == "ativa" else "ativa"
            if igreja is not None and igreja.status == expected:
                igreja.status = new_status
        db.commit()

    return WebhookResponse(received=True, status=new_status)
