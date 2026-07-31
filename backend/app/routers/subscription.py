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

import datetime as dt
import logging
import re
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
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
    MONTHLY_RECOVERY_DESCRIPTION,
    SETUP_CHARGE_DESCRIPTION,
    AsaasClient,
    AsaasError,
    get_asaas_client,
    map_payment_status,
    payment_invoice_url,
    payment_reversal_kind,
    verify_webhook_token,
)
from app.services.billing import (
    ensure_payment_operation,
    find_open_operation,
    find_operation_for_payment,
    get_setup_fee_for_igreja,
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
    # Links persistidos do checkout, expostos apenas enquanto a cobrança
    # correspondente ainda está em aberto — a tela reconstrói o painel de
    # pagamento após reload sem criar novas cobranças. A fatura VENCIDA
    # continua pagável: inadimplente também expõe o link (regularizar nunca
    # deve criar outra assinatura no Asaas).
    invoiceUrl: str | None = None  # noqa: N815 - mensalidade
    setupInvoiceUrl: str | None = None  # noqa: N815
    # Motivo da reversão da cobrança mensal corrente ('deleted'|'refunded') —
    # a UI decide a AÇÃO específica de recuperação por aqui, nunca pela mera
    # ausência de invoiceUrl.
    invoiceReversal: str | None = None  # noqa: N815
    # Link da cobrança avulsa de recuperação mensal, quando emitida.
    recoveryInvoiceUrl: str | None = None  # noqa: N815
    # Setup em aberto SEM link pagável, com assinatura já criada: a UI oferece
    # "Gerar nova taxa de setup" (operação durável — nunca outra assinatura).
    setupRecoveryRequired: bool = False  # noqa: N815

    @classmethod
    def from_model(
        cls, s: Subscription, *, recovery_invoice_url: str | None = None
    ) -> "SubscriptionOut":
        return cls(
            plano=s.plano,
            status=s.status,
            pessoas=s.pessoas,
            limite=s.limite,
            proximaCobranca=s.proxima_cobranca.isoformat()
            if s.proxima_cobranca
            else None,
            setupPago=s.setup_pago,
            invoiceUrl=(
                s.asaas_invoice_url
                if s.status in ("pendente", "inadimplente")
                else None
            ),
            setupInvoiceUrl=s.asaas_setup_invoice_url if not s.setup_pago else None,
            invoiceReversal=s.asaas_invoice_reversal,
            recoveryInvoiceUrl=recovery_invoice_url,
            setupRecoveryRequired=bool(
                not s.setup_pago
                and s.asaas_setup_invoice_url is None
                and s.asaas_subscription_id
            ),
        )


class CheckoutRequest(BaseModel):
    plano: str
    cpfCnpj: str = Field(max_length=20)  # noqa: N815

    @field_validator("plano")
    @classmethod
    def _plano(cls, value: str) -> str:
        # Só normaliza; a existência (e se está ativo) no catálogo `planos` é
        # checada no handler contra o banco — ver _plano_ativo_or_422.
        value = value.strip().lower()
        if not value:
            raise ValueError("plano obrigatório")
        return value

    @field_validator("cpfCnpj")
    @classmethod
    def _cpf_cnpj(cls, value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if len(digits) == 11 and _cpf_is_valid(digits):
            return digits
        if len(digits) == 14 and _cnpj_is_valid(digits):
            return digits
        raise ValueError("CPF ou CNPJ inválido")


def _cpf_is_valid(digits: str) -> bool:
    if digits == digits[0] * 11:
        return False
    first = sum(int(digit) * weight for digit, weight in zip(digits[:9], range(10, 1, -1)))
    second = sum(int(digit) * weight for digit, weight in zip(digits[:10], range(11, 1, -1)))
    return digits[9] == str(0 if first % 11 < 2 else 11 - first % 11) and digits[10] == str(
        0 if second % 11 < 2 else 11 - second % 11
    )


def _cnpj_is_valid(digits: str) -> bool:
    if digits == digits[0] * 14:
        return False
    first = sum(
        int(digit) * weight for digit, weight in zip(digits[:12], (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    )
    second = sum(
        int(digit) * weight for digit, weight in zip(digits[:13], (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    )
    return digits[12] == str(0 if first % 11 < 2 else 11 - first % 11) and digits[13] == str(
        0 if second % 11 < 2 else 11 - second % 11
    )


class CheckoutResponse(BaseModel):
    status: str
    invoiceUrl: str | None = None  # noqa: N815 - mensalidade
    setupInvoiceUrl: str | None = None  # noqa: N815
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


def _parse_iso_date(value: object) -> dt.date | None:
    """dueDate do payload Asaas (ISO yyyy-mm-dd) — None quando ausente/ilegível."""
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _is_stale_cycle_event(sub: Subscription, payment: dict) -> bool:
    """True quando o evento pertence a um ciclo ANTERIOR ao já rastreado.

    A decisão acontece ANTES de qualquer mutação no webhook: um evento vetado
    aqui não muda status, link, payment id, acesso da igreja nem comita — um
    OVERDUE atrasado de julho não pode derrubar a assinatura que agosto já
    confirmou. Mesmo payment id nunca é stale (o ciclo corrente transita de
    status normalmente). Um id DIFERENTE sem dueDate ordenável não tem como
    provar que é mais novo, então não pode regredir um ciclo já rastreado.
    """
    incoming_id = str(payment["id"]) if payment.get("id") else None
    if not incoming_id or sub.asaas_invoice_payment_id in (None, incoming_id):
        return False
    if sub.proxima_cobranca is None:
        # Rastreio sem data de referência (ex.: checkout sem 1º evento datado):
        # aceita o evento — é a primeira base de ordenação disponível.
        return False
    due = _parse_iso_date(payment.get("dueDate"))
    if due is None:
        return True  # id diferente sem data: não pode regredir o rastreado
    return due < sub.proxima_cobranca


def _apply_monthly_payment_link(
    sub: Subscription, payment: dict, *, reversal: str | None = None
) -> None:
    """Track the CURRENT monthly invoice (id + link) from a payment webhook.

    Every billing cycle emits a new payment; the stored link must follow it,
    otherwise "Pagar mensalidade" keeps opening the settled first invoice.
    Stale-cycle ordering is decided by _is_stale_cycle_event BEFORE any
    mutation — by the time this runs, the event is same-cycle (idempotent
    refresh that may only fill a missing link) or a genuinely newer cycle.
    ``reversal`` ('deleted'|'refunded') difere de OVERDUE: a fatura deixa de
    ser pagável — o MOTIVO fica persistido para a recuperação explícita
    (restore para deleted, cobrança avulsa para refunded) e um novo ciclo
    válido o limpa.
    """
    incoming_id = str(payment["id"]) if payment.get("id") else None
    if not incoming_id:
        return
    due = _parse_iso_date(payment.get("dueDate"))

    if sub.asaas_invoice_payment_id == incoming_id:
        if reversal:
            sub.asaas_invoice_url = None
            sub.asaas_invoice_reversal = reversal
        elif not sub.asaas_invoice_url and not sub.asaas_invoice_reversal:
            sub.asaas_invoice_url = payment_invoice_url(payment)
        if due is not None:
            sub.proxima_cobranca = due
        return

    sub.asaas_invoice_payment_id = incoming_id
    if reversal:
        # Ciclo novo que já chega estornado: rastreia sem expor link.
        sub.asaas_invoice_url = None
        sub.asaas_invoice_reversal = reversal
    else:
        # None quando o Asaas ainda não gerou o link — nunca manter a URL
        # quitada do ciclo anterior à mostra. Ciclo válido limpa a retenção.
        sub.asaas_invoice_url = payment_invoice_url(payment)
        sub.asaas_invoice_reversal = None
    if due is not None:
        sub.proxima_cobranca = due


def _reconcile_legacy_setup_charge(
    db: Session, payment: dict, payment_id: str | None, new_status: str | None
) -> WebhookResponse | None:
    """Setup pago por checkout ANTERIOR à migration (sem charge id rastreado).

    O cliente antigo criava a cobrança de setup sem persistir o id, então a
    confirmação chegaria aqui como "one-time payment desconhecido" e o tenant
    ficaria devendo setup para sempre. Reconciliação ESTRITA — só marca pago
    quando TODAS as condições fecham: é confirmação, a descrição é exatamente a
    da cobrança de setup, há customer no payload e existe UMA ÚNICA assinatura
    candidata (mesmo customer, setup em aberto, sem charge id rastreado).
    Qualquer ambiguidade é apenas reconhecida, sem mutação. Nunca altera
    mensalidade, status da assinatura ou acesso da igreja.
    """
    if (
        payment_id is None
        or new_status != "ativa"
        or payment.get("description") != SETUP_CHARGE_DESCRIPTION
        or not payment.get("customer")
    ):
        return None
    candidatas = db.execute(
        select(Subscription).where(
            Subscription.asaas_customer_id == str(payment["customer"]),
            Subscription.setup_pago.is_(False),
            Subscription.asaas_setup_charge_id.is_(None),
        )
    ).scalars().all()
    if len(candidatas) != 1:
        return None
    legada = candidatas[0]
    legada.asaas_setup_charge_id = payment_id
    legada.setup_pago = True
    db.commit()
    return WebhookResponse(received=True, status=new_status)


def _apply_setup_charge_event(
    db: Session, setup_sub: Subscription, new_status: str | None, reversal: str | None
) -> None:
    """Trilho da cobrança de setup rastreada. Idempotente por convergência.

    Confirmação marca apenas setup_pago; estorno/exclusão reabre a pendência e
    derruba vínculo+link da cobrança morta (a reemissão é a ação explícita
    /subscription/setup-charge). Mensalidade, status da assinatura e acesso da
    igreja ficam intocados neste trilho.
    """
    if new_status == "ativa" and not setup_sub.setup_pago:
        setup_sub.setup_pago = True
        db.commit()
    elif reversal:
        setup_sub.setup_pago = False
        setup_sub.asaas_setup_charge_id = None
        setup_sub.asaas_setup_invoice_url = None
        db.commit()


def _apply_operation_event(
    db: Session, op, payment: dict, new_status: str | None, reversal: str | None
) -> WebhookResponse:
    """Evento de cobrança avulsa nascida de OPERAÇÃO durável.

    O propósito (setup | monthly_recovery) vem da operação — nunca é inferido
    pelo shape do payload. Convergente para eventos duplicados/fora de ordem.
    """
    payment_id = str(payment["id"]) if payment.get("id") else None
    if op.asaas_payment_id is None and payment_id:
        # O webhook chegou antes da nossa reconciliação: adota o vínculo.
        op.asaas_payment_id = payment_id
    if not reversal and not op.invoice_url:
        url = payment_invoice_url(payment)
        if url:
            op.invoice_url = url

    sub = db.execute(
        select(Subscription).where(Subscription.id == op.subscription_id)
    ).scalar_one_or_none()
    if sub is None:
        db.commit()
        return WebhookResponse(received=True, status=new_status)

    if op.purpose == "setup":
        if new_status == "ativa":
            op.status = "paid"
            if not sub.setup_pago:
                sub.setup_pago = True
            if not sub.asaas_setup_charge_id and op.asaas_payment_id:
                sub.asaas_setup_charge_id = op.asaas_payment_id
        elif reversal:
            op.status = "reversed"
            op.invoice_url = None
            sub.setup_pago = False
            sub.asaas_setup_charge_id = None
            sub.asaas_setup_invoice_url = None
        db.commit()
        return WebhookResponse(received=True, status=new_status)

    # monthly_recovery: quitação regulariza assinatura e acesso (guarda
    # atômica no UPDATE condicional, como na mensalidade); nova reversão
    # mantém a dívida sem expor link inválido.
    if new_status == "ativa":
        op.status = "paid"
        sub.status = "ativa"
        sub.asaas_invoice_reversal = None  # dívida do ciclo revertido quitada
        db.execute(
            update(Igreja)
            .where(Igreja.id == sub.igreja_id, Igreja.status == "inadimplente")
            .values(status="ativa")
        )
    elif reversal:
        op.status = "reversed"
        op.invoice_url = None
    db.commit()
    return WebhookResponse(received=True, status=new_status)


def _recover_missing_invoice_urls(
    db: Session, sub: Subscription, asaas: AsaasClient
) -> None:
    """Best-effort: re-resolve payment links lost before persistence existed.

    Only READS the Asaas API by the ids already stored on the subscription —
    never creates another subscription or setup charge. When Asaas has not
    generated the link yet (or is unavailable), the subscription read keeps
    returning null links instead of failing the whole screen.
    """
    monthly_missing = (
        sub.status in ("pendente", "inadimplente")
        and sub.asaas_invoice_url is None
        # Cobrança estornada/excluída não é recuperável por aqui: reapresentar
        # o link dela não quita nada — a recuperação é a AÇÃO explícita
        # (restore/cobrança avulsa) ou o próximo ciclo válido.
        and sub.asaas_invoice_reversal is None
        and bool(sub.asaas_invoice_payment_id or sub.asaas_subscription_id)
    )
    setup_missing = (
        not sub.setup_pago
        and sub.asaas_setup_invoice_url is None
        and bool(sub.asaas_setup_charge_id)
    )
    if not monthly_missing and not setup_missing:
        return

    changed = False
    try:
        if monthly_missing:
            if sub.asaas_invoice_payment_id:
                # Cobrança mensal do ciclo corrente — consulta pelo id exato.
                url = asaas.get_payment_invoice_url(sub.asaas_invoice_payment_id)
            else:
                # Compat: registro anterior à coluna do payment id — cai na
                # primeira cobrança da assinatura.
                url = asaas.get_subscription_invoice_url(sub.asaas_subscription_id)
            if url:
                sub.asaas_invoice_url = url
                changed = True
        if setup_missing:
            url = asaas.get_payment_invoice_url(sub.asaas_setup_charge_id)
            if url:
                sub.asaas_setup_invoice_url = url
                changed = True
    except AsaasError:
        logger.warning("Asaas link recovery failed; keeping null links")
    if changed:
        db.commit()


@router.get("", response_model=SubscriptionOut)
def get_subscription(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_owner),
    evolution: EvolutionClient = Depends(get_evolution_client),
    asaas: AsaasClient = Depends(get_asaas_client),
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

    # Cobrança pendente sem link persistido (checkout antigo ou Asaas ainda
    # gerando a fatura): tenta recuperar pelos ids já armazenados, sem nunca
    # criar cobrança nova. Falha do Asaas não derruba a leitura.
    _recover_missing_invoice_urls(db, sub, asaas)

    # Surface the trigger-driven autoupgrade to the admin (idempotent).
    # notify_autoupgrade comita internamente; a re-asserção manual do contexto
    # pós-commit foi REMOVIDA (PR3-A, caso âncora): o listener after_begin (D2)
    # reabre a transação já escopada assim que db.refresh() emite o próximo BEGIN,
    # pois a sessão está marcada por get_current_user. expire_on_commit=False
    # (session.py) garante que só o refresh reabre a transação — objetos já
    # carregados não expiram no commit. A estrutura (seam) substitui a convenção.
    notify_autoupgrade(db, igreja_uuid, evolution)
    db.refresh(sub)

    # Cobrança avulsa de recuperação mensal emitida e em aberto: expõe o link
    # dela (a mensalidade revertida não tem link pagável próprio).
    recovery_url: str | None = None
    if sub.asaas_invoice_reversal:
        recovery_op = find_open_operation(db, sub.id, "monthly_recovery")
        if recovery_op is not None:
            recovery_url = recovery_op.invoice_url
    return SubscriptionOut.from_model(sub, recovery_invoice_url=recovery_url)


def _ensure_setup_charge(
    db: Session, sub: Subscription, asaas: AsaasClient, setup_fee: float
) -> None:
    """Emite (ou reconcilia) a cobrança de setup como operação durável.

    Todo POST /payments de setup nasce de uma billing_payment_operation com
    operation_key exclusiva — resposta perdida é reconciliada no retry, nunca
    repetida às cegas. O espelho em sub.asaas_setup_charge_id/url mantém o
    trilho existente de webhook e recovery.
    """
    if setup_fee <= 0 or sub.setup_pago or sub.asaas_setup_charge_id:
        return
    if not sub.asaas_customer_id:
        return  # sem customer rastreado não há como emitir a cobrança
    op = ensure_payment_operation(
        db,
        asaas,
        sub=sub,
        purpose="setup",
        valor=setup_fee,
        description=SETUP_CHARGE_DESCRIPTION,
        customer_id=sub.asaas_customer_id,
    )
    if op.asaas_payment_id:
        sub.setup_pago = False
        sub.asaas_setup_charge_id = op.asaas_payment_id
        sub.asaas_setup_invoice_url = op.invoice_url
        db.commit()


def _resume_tracked_checkout(
    db: Session,
    sub: Subscription,
    asaas: AsaasClient,
    setup_fee: float,
) -> CheckoutResponse:
    """Retry de checkout do MESMO plano com assinatura Asaas JÁ rastreada.

    Vale para QUALQUER status (pendente, ativa, inadimplente, revertida):
    nunca emite outro POST /subscriptions — recupera a fatura corrente por
    leitura (best-effort) e garante a cobrança de setup via operação durável.
    """
    try:
        payment = asaas.get_subscription_payment(sub.asaas_subscription_id)
    except AsaasError:
        payment = None  # GET /subscription recupera o link depois
    if payment and payment.get("id"):
        incoming_id = str(payment["id"])
        url = payment_invoice_url(payment)
        # Não ressuscita o link de uma cobrança revertida: só adota quando é
        # outra cobrança ou quando não há reversão pendente.
        if incoming_id != sub.asaas_invoice_payment_id or not sub.asaas_invoice_reversal:
            sub.asaas_invoice_payment_id = incoming_id
            if url:
                sub.asaas_invoice_url = url
                sub.asaas_invoice_reversal = None
            due = _parse_iso_date(payment.get("dueDate"))
            if due is not None:
                sub.proxima_cobranca = due

    try:
        _ensure_setup_charge(db, sub, asaas, setup_fee)
    except AsaasError as exc:
        db.commit()  # preserva o que a retomada já recuperou
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível criar o checkout no Asaas",
        ) from exc
    db.commit()

    return CheckoutResponse(
        status=sub.status or "pendente",
        invoiceUrl=sub.asaas_invoice_url,
        setupInvoiceUrl=sub.asaas_setup_invoice_url if not sub.setup_pago else None,
        asaasSubscriptionId=sub.asaas_subscription_id,
    )


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
    igreja = db.execute(
        select(Igreja).where(Igreja.id == igreja_uuid)
    ).scalar_one_or_none()
    if igreja is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Igreja não encontrada")

    sub = db.execute(
        select(Subscription).where(Subscription.igreja_id == igreja_uuid)
    ).scalar_one_or_none()
    if sub is None:
        sub = Subscription(igreja_id=igreja_uuid, plano=payload.plano)
        db.add(sub)

    setup_fee = 0.0 if sub.setup_pago else get_setup_fee_for_igreja(db, igreja)

    # INVARIANTE: mesmo plano + assinatura Asaas já rastreada NUNCA executa
    # outro POST /subscriptions — em qualquer status (pendente, ativa,
    # inadimplente ou revertida) o caminho é a retomada. Troca de plano
    # (plano diferente) segue o fluxo de criação — semântica de produto
    # preservada (risco da recorrência antiga reportado ao dono à parte).
    if (
        sub.asaas_subscription_id
        and sub.asaas_subscription_id != "sandbox"
        and sub.plano == payload.plano
    ):
        return _resume_tracked_checkout(db, sub, asaas, setup_fee)

    def _track_created_subscription(customer_id: str, subscription_id: str) -> None:
        # Chamado pelo AsaasClient IMEDIATAMENTE após o POST /subscriptions:
        # persiste o vínculo antes de qualquer outra chamada remota, para uma
        # falha posterior nunca deixar assinatura viva sem rastreio — um retry
        # retomaria em vez de duplicar.
        sub.plano = payload.plano
        sub.limite = plano_row.limite_pessoas
        sub.status = "pendente"
        sub.asaas_customer_id = customer_id
        sub.asaas_subscription_id = subscription_id
        db.commit()

    try:
        result = asaas.create_checkout(
            nome=current_user.nome,
            email=current_user.email,
            plano=payload.plano,
            valor=float(plano_row.preco_mensal),
            cpf_cnpj=payload.cpfCnpj,
            external_reference=str(igreja_uuid),
            on_subscription_created=_track_created_subscription,
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
    # Persist the payment links so the pending screen survives a reload —
    # they otherwise existed only in the checkout HTTP response.
    sub.asaas_invoice_url = result.invoice_url
    sub.asaas_invoice_payment_id = result.invoice_payment_id
    sub.asaas_invoice_reversal = None
    if setup_fee > 0:
        sub.setup_pago = False  # paid only once its own webhook confirms it
    else:
        sub.setup_pago = True  # no setup charge was configured for this igreja
        sub.asaas_setup_charge_id = None
        sub.asaas_setup_invoice_url = None
    db.commit()

    if setup_fee > 0:
        # A taxa de setup nasce como operação durável (retry-safe): a
        # operation_key foi persistida antes do POST — se a resposta se
        # perder, o retry reconcilia em vez de duplicar a cobrança.
        try:
            _ensure_setup_charge(db, sub, asaas, setup_fee)
        except AsaasError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Não foi possível criar o checkout no Asaas",
            ) from exc

    return CheckoutResponse(
        status=result.status,
        invoiceUrl=result.invoice_url,
        setupInvoiceUrl=sub.asaas_setup_invoice_url if not sub.setup_pago else None,
        asaasSubscriptionId=result.subscription_id,
    )


class RecoveryResponse(BaseModel):
    """Resultado das ações explícitas de recuperação de cobrança."""

    status: str
    invoiceUrl: str | None = None  # noqa: N815
    recoveryInvoiceUrl: str | None = None  # noqa: N815
    setupInvoiceUrl: str | None = None  # noqa: N815


@router.post("/recover-invoice", response_model=RecoveryResponse)
def recover_invoice(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_owner),
    asaas: AsaasClient = Depends(get_asaas_client),
) -> RecoveryResponse:
    """Ação EXPLÍCITA de recuperação da mensalidade revertida.

    'deleted': restaura a MESMA cobrança pelo endpoint oficial (consultando
    antes — restore não é tratado como idempotente). 'refunded': emite a
    cobrança avulsa de recuperação via operação durável. Nunca cria assinatura.
    """
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    sub = db.execute(
        select(Subscription).where(Subscription.igreja_id == igreja_uuid)
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assinatura não encontrada")
    if not sub.asaas_invoice_reversal:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A cobrança mensal atual não está revertida",
        )

    if sub.asaas_invoice_reversal == "deleted" and sub.asaas_invoice_payment_id:
        try:
            current = asaas.get_payment(sub.asaas_invoice_payment_id)
            if current is not None and current.get("deleted"):
                # Ainda excluída: restaura o MESMO payment id (sem nova cobrança).
                asaas.restore_payment(sub.asaas_invoice_payment_id)
                current = asaas.get_payment(sub.asaas_invoice_payment_id)
        except AsaasError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Não foi possível recuperar a cobrança no Asaas",
            ) from exc
        if current is not None and not current.get("deleted"):
            sub.asaas_invoice_url = payment_invoice_url(current)
            sub.asaas_invoice_reversal = None
            new_status = map_payment_status(current.get("status"))
            if new_status is not None:
                sub.status = new_status
            db.commit()
        return RecoveryResponse(
            status=sub.status or "pendente", invoiceUrl=sub.asaas_invoice_url
        )

    # 'refunded' (ou deleted sem payment id rastreado): cobrança estornada não
    # volta — emite a cobrança avulsa de RECUPERAÇÃO via operação durável.
    if not sub.asaas_customer_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Assinatura sem cliente Asaas rastreado",
        )
    plano_row = _plano_ativo_or_422(db, sub.plano)
    try:
        op = ensure_payment_operation(
            db,
            asaas,
            sub=sub,
            purpose="monthly_recovery",
            valor=float(plano_row.preco_mensal),
            description=MONTHLY_RECOVERY_DESCRIPTION,
            customer_id=sub.asaas_customer_id,
            source_payment_id=sub.asaas_invoice_payment_id,
        )
    except AsaasError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível recuperar a cobrança no Asaas",
        ) from exc
    return RecoveryResponse(
        status=sub.status or "inadimplente",
        recoveryInvoiceUrl=op.invoice_url,
    )


@router.post("/setup-charge", response_model=RecoveryResponse)
def create_setup_charge_action(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_owner),
    asaas: AsaasClient = Depends(get_asaas_client),
) -> RecoveryResponse:
    """Ação EXPLÍCITA de (re)emissão da taxa de setup em aberto.

    Usada quando o setup está devido mas sem link pagável (ex.: cobrança
    revertida). Cria/reconcilia SOMENTE uma operação `setup` — nunca chama
    POST /subscriptions.
    """
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    igreja = db.execute(
        select(Igreja).where(Igreja.id == igreja_uuid)
    ).scalar_one_or_none()
    if igreja is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Igreja não encontrada")
    sub = db.execute(
        select(Subscription).where(Subscription.igreja_id == igreja_uuid)
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assinatura não encontrada")
    if sub.setup_pago:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A taxa de setup já está quitada",
        )
    if sub.asaas_setup_invoice_url:
        return RecoveryResponse(
            status=sub.status or "pendente",
            setupInvoiceUrl=sub.asaas_setup_invoice_url,
        )

    setup_fee = get_setup_fee_for_igreja(db, igreja)
    if setup_fee <= 0:
        # Isenta pela configuração vigente: nada a cobrar.
        sub.setup_pago = True
        sub.asaas_setup_charge_id = None
        sub.asaas_setup_invoice_url = None
        db.commit()
        return RecoveryResponse(status=sub.status or "pendente")

    # Reemissão pós-reversão: derruba o espelho antigo para a operação criar a
    # cobrança substituta (a informação da cobrança revertida vive na operação
    # anterior e no histórico do webhook).
    sub.asaas_setup_charge_id = None
    try:
        _ensure_setup_charge(db, sub, asaas, setup_fee)
    except AsaasError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível emitir a taxa de setup no Asaas",
        ) from exc
    return RecoveryResponse(
        status=sub.status or "pendente",
        setupInvoiceUrl=sub.asaas_setup_invoice_url,
    )


@router.get("/planos", response_model=PlanCatalogOut)
def list_planos_disponiveis(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_owner),
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
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    igreja = db.execute(
        select(Igreja).where(Igreja.id == igreja_uuid)
    ).scalar_one_or_none()
    if igreja is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Igreja não encontrada")
    return PlanCatalogOut(planos=planos, setupFee=get_setup_fee_for_igreja(db, igreja))


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

    payment = payload.payment or {}
    subscription = payload.subscription or {}
    obj = payment or subscription
    raw_status = obj.get("status") or payload.event
    new_status = map_payment_status(raw_status)

    payment_id = str(payment["id"]) if payment.get("id") else None
    reversal = payment_reversal_kind(raw_status)

    # PROPÓSITO EXPLÍCITO primeiro: cobranças avulsas nascidas de operações
    # duráveis são resolvidas pela operação (asaas_payment_id ou operation_key
    # na externalReference) — nunca inferidas pela ausência de
    # payment.subscription no payload.
    if payment:
        op = find_operation_for_payment(
            db,
            payment_id=payment_id,
            external_reference=payment.get("externalReference"),
        )
        if op is not None:
            return _apply_operation_event(db, op, payment, new_status, reversal)

    if payment_id:
        setup_sub = db.execute(
            select(Subscription).where(Subscription.asaas_setup_charge_id == payment_id)
        ).scalar_one_or_none()
        if setup_sub is not None:
            _apply_setup_charge_event(db, setup_sub, new_status, reversal)
            return WebhookResponse(received=True, status=new_status)

    # A payment without an Asaas subscription can only be a setup charge.
    # Never use its externalReference as authority for a monthly status
    # transition; that would let another one-time charge alter access.
    if payment and not payment.get("subscription"):
        legacy = _reconcile_legacy_setup_charge(db, payment, payment_id, new_status)
        if legacy is not None:
            return legacy
        logger.info("Asaas webhook for unknown one-time payment; acknowledged")
        return WebhookResponse(received=True, status=None)

    asaas_sub_id = payment.get("subscription") or subscription.get("id")
    sub: Subscription | None = None
    if asaas_sub_id:
        sub = db.execute(
            select(Subscription).where(Subscription.asaas_subscription_id == str(asaas_sub_id))
        ).scalar_one_or_none()
    if sub is None and not payment:
        external_ref = subscription.get("externalReference")
        if external_ref:
            try:
                igreja_uuid = uuid.UUID(str(external_ref))
                sub = db.execute(
                    select(Subscription).where(Subscription.igreja_id == igreja_uuid)
                ).scalar_one_or_none()
            except ValueError:
                sub = None
    if sub is None:
        logger.info("Asaas webhook for unknown subscription; acknowledged")
        return WebhookResponse(received=True, status=None)

    # Veto de ciclo ANTES de qualquer mutação: um evento atrasado/duplicado de
    # fatura de ciclo anterior é reconhecido e ignorado por inteiro — nem
    # status, nem link/payment id, nem acesso da igreja, nem commit.
    if payment and _is_stale_cycle_event(sub, payment):
        logger.info("Asaas webhook for a previous billing cycle; acknowledged")
        return WebhookResponse(received=True, status=None)

    if new_status is not None:
        sub.status = new_status
        # Cada ciclo mensal emite uma cobrança nova: acompanha id + link da
        # fatura corrente, senão "Pagar mensalidade" abriria a primeira
        # fatura já quitada. Estorno/exclusão retém o link (inutilizável).
        if payment:
            _apply_monthly_payment_link(sub, payment, reversal=reversal)
        # Reflect subscription billing only onto the igreja access gate. Setup
        # payment events return above and never change this status.
        if new_status in ("ativa", "inadimplente"):
            expected = "inadimplente" if new_status == "ativa" else "ativa"
            db.execute(
                update(Igreja)
                .where(Igreja.id == sub.igreja_id, Igreja.status == expected)
                .values(status=new_status)
            )
        db.commit()

    return WebhookResponse(received=True, status=new_status)
