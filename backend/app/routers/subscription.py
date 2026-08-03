"""Subscription router — Asaas billing + webhook (US-36 / RF-42).

Endpoints:
  - GET  /subscription          current subscription + plan/limit/usage (admin)
  - POST /subscription          create an Asaas checkout with a setup fee (admin)
  - GET  /subscription/planos   active plan catalog + setup fee (admin)
  - POST /subscription/webhook  Asaas events -> update status (token-gated)

The autoupgrade gatilho is the DB trigger `trg_subscription_autoupgrade`: with a
tracked Asaas subscription it only records a durable operation that the
cron-worker synchronizes (see app/services/billing_worker.py — PUT in-place,
local plan only after remote confirmation, notification after commit). This
router never performs autoupgrade side effects; it keeps the subscription
status in sync from Asaas payment events. The webhook is public but gated by
the shared `asaas-access-token` header instead of Clerk auth.
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

from app.config import get_settings
from app.db.models import (
    BillingPaymentOperation,
    Igreja,
    Plano,
    Subscription,
)
from app.db.rls_observability import log_if_not_scoped
from app.db.session import get_db
from app.deps import CurrentUser, require_owner
from app.services.asaas import (
    MONTHLY_RECOVERY_DESCRIPTION,
    SETUP_CHARGE_DESCRIPTION,
    AsaasClient,
    AsaasError,
    AsaasRejectedError,
    get_asaas_client,
    map_payment_status,
    payment_invoice_url,
    payment_reversal_kind,
    subscription_description,
    verify_webhook_token,
)
from app.services.billing import (
    PlanChangeConflict,
    SubscriptionCreateConflict,
    claim_transition,
    current_headcount,
    ensure_payment_operation,
    ensure_plan_change_operation,
    find_any_open_operation,
    find_latest_reversed_setup_operation,
    find_open_operation,
    find_open_plan_change,
    find_open_subscription_operation,
    find_operation_for_payment,
    find_settled_recovery,
    find_subscription_operation_by_key,
    get_setup_fee_for_igreja,
    prepare_subscription_operation,
    reconcile_subscription_operation,
)
from app.services.billing_worker import queue_autoupgrade_if_over_limit

logger = logging.getLogger("pastorai.subscription")

router = APIRouter(prefix="/subscription", tags=["subscription"])


class SubscriptionOut(BaseModel):
    plano: str
    status: str | None = None
    pessoas: int | None = None
    limite: int | None = None
    proximaCobranca: str | None = None  # noqa: N815
    setupPago: bool  # noqa: N815
    # Valor congelado na contratação. NULL existe apenas para contratos legados;
    # a UI usa o catálogo atual somente como fallback nesses registros antigos.
    setupFeeContracted: float | None = None  # noqa: N815
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
    # Há dívida de recuperação aberta, mesmo antes de a cobrança substituta
    # ganhar URL. A UI oferece a ação explícita que a materializa/reconcilia.
    recoveryRequired: bool = False  # noqa: N815
    # Setup em aberto SEM link pagável, com assinatura já criada: a UI oferece
    # "Gerar nova taxa de setup" (operação durável — nunca outra assinatura).
    setupRecoveryRequired: bool = False  # noqa: N815
    # SINAL SEMÂNTICO EXPLÍCITO da contratação: `false` significa que existe
    # apenas o registro local placeholder (criado antes do POST no Asaas, que
    # falhou) — não há recorrência remota alguma. A UI NUNCA deve inferir
    # "assinante" da mera existência do objeto, e o id remoto não é exposto só
    # para ela adivinhar. Com `false`, a tela é a de contratação inicial:
    # CPF/CNPJ visível, sem "Plano atual", sem troca de plano, com retomada.
    hasTrackedSubscription: bool = False  # noqa: N815
    checkoutRequired: bool = False  # noqa: N815

    @classmethod
    def from_model(
        cls,
        s: Subscription,
        *,
        recovery_invoice_url: str | None = None,
        recovery_required: bool = False,
    ) -> "SubscriptionOut":
        rastreada = bool(
            s.asaas_subscription_id and s.asaas_subscription_id != "sandbox"
        )
        return cls(
            plano=s.plano,
            status=s.status,
            pessoas=s.pessoas,
            limite=s.limite,
            proximaCobranca=s.proxima_cobranca.isoformat()
            if s.proxima_cobranca
            else None,
            setupPago=s.setup_pago,
            setupFeeContracted=(
                float(getattr(s, "setup_fee_contracted", None))
                if getattr(s, "setup_fee_contracted", None) is not None
                else None
            ),
            invoiceUrl=(
                s.asaas_invoice_url
                if s.status in ("pendente", "inadimplente")
                else None
            ),
            setupInvoiceUrl=s.asaas_setup_invoice_url if not s.setup_pago else None,
            invoiceReversal=s.asaas_invoice_reversal,
            recoveryInvoiceUrl=recovery_invoice_url,
            recoveryRequired=recovery_required,
            setupRecoveryRequired=bool(
                not s.setup_pago
                and s.asaas_setup_invoice_url is None
                and s.asaas_subscription_id
            ),
            hasTrackedSubscription=rastreada,
            checkoutRequired=not rastreada,
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
    if str(getattr(legada, "asaas_setup_reversed_payment_id", "")) == payment_id:
        # A cobrança já foi adotada e depois revertida. Confirmação atrasada não
        # ressuscita obrigação morta nem remove a nova pendência de setup.
        return WebhookResponse(received=True, status=None)
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
        setup_sub.asaas_setup_reversed_payment_id = (
            str(setup_sub.asaas_setup_charge_id)
            if setup_sub.asaas_setup_charge_id
            else None
        )
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
        if new_status == "ativa" and op.status != "reversed":
            op.status = "paid"
            if not sub.setup_pago:
                sub.setup_pago = True
            if not sub.asaas_setup_charge_id and op.asaas_payment_id:
                sub.asaas_setup_charge_id = op.asaas_payment_id
        elif reversal:
            op.status = "reversed"
            op.invoice_url = None
            # AUTORIDADE: só reabre a pendência quando ESTA operação é a dona
            # do setup atualmente rastreado — um estorno atrasado/duplicado de
            # uma geração ANTIGA nunca desfaz o setup substituto já pago.
            if op.asaas_payment_id and str(sub.asaas_setup_charge_id) == str(
                op.asaas_payment_id
            ):
                sub.setup_pago = False
                sub.asaas_setup_charge_id = None
                sub.asaas_setup_invoice_url = None
        db.commit()
        return WebhookResponse(received=True, status=new_status)

    # monthly_recovery: quitação remove somente a dívida da SUA fonte. O ciclo
    # mensal pode ter avançado enquanto a recuperação estava aberta; nesse
    # caso o status atual é preservado e o gate só reabre se não restar outra
    # recuperação nem reversão e a cobrança corrente já estiver ativa.
    if new_status == "ativa" and op.status != "reversed":
        # A operação SEMPRE registra o próprio resultado histórico.
        op.status = "paid"
        # AUTORIDADE (simétrica à da reversão): só a recuperação da cobrança
        # ATUALMENTE rastreada limpa a reversão desse ciclo. Uma recovery de A
        # paga depois do avanço para B nunca altera o status/reversão de B.
        if (
            op.source_payment_id
            and str(op.source_payment_id) == str(sub.asaas_invoice_payment_id)
            and sub.asaas_invoice_reversal is not None
        ):
            sub.status = "ativa"
            sub.asaas_invoice_reversal = None  # dívida do ciclo revertido quitada

        # A própria operação já está `paid`, então deixa de aparecer na busca
        # por operações abertas (o execute faz autoflush no SQLAlchemy real).
        # Reavalia o estado CORRENTE: B ativa + nenhuma dívida restante libera;
        # B pendente/vencida/revertida continua bloqueada.
        if (
            sub.status == "ativa"
            and sub.asaas_invoice_reversal is None
            and find_any_open_operation(db, sub.id, "monthly_recovery") is None
        ):
            db.execute(
                update(Igreja)
                .where(Igreja.id == sub.igreja_id, Igreja.status == "inadimplente")
                .values(status="ativa")
            )
    elif reversal:
        # Tanto uma recovery paga depois estornada quanto uma cobrança aberta
        # depois excluída devolvem a fonte ao estado "sem pagamento possível".
        # Só a repetição de uma operação já reversed não reabre outra intenção.
        should_reopen = op.status != "reversed"
        op.status = "reversed"
        op.invoice_url = None
        # A recuperação estornada reabre a dívida da SUA fonte em operação
        # separada, mesmo se o ciclo avançou. Só o snapshot mensal corrente fica
        # sob a autoridade de `asaas_invoice_payment_id`. A linha da operação é
        # travada por find_operation_for_payment, então repetição concorrente
        # observa `reversed` e não cria outra intenção.
        if should_reopen and op.source_payment_id:
            # O dinheiro voltou, portanto a dívida da FONTE reaparece mesmo se
            # o ciclo mensal atual já avançou. Registra uma nova intenção
            # durável, ainda sem chamada externa: o dono materializa a cobrança
            # explicitamente em /recover-invoice.
            db.add(
                BillingPaymentOperation(
                    subscription_id=sub.id,
                    purpose="monthly_recovery",
                    operation_key=f"pastorai-monthly_recovery-{uuid.uuid4()}",
                    source_payment_id=str(op.source_payment_id),
                    status="prepared",
                    valor=op.valor,
                )
            )
            db.execute(
                update(Igreja)
                .where(Igreja.id == sub.igreja_id, Igreja.status == "ativa")
                .values(status="inadimplente")
            )
            if str(op.source_payment_id) == str(sub.asaas_invoice_payment_id):
                sub.status = "inadimplente"
                # Só a fonte corrente ocupa o snapshot corrente; a dívida de
                # ciclo antigo vive na operação preparada acima.
                sub.asaas_invoice_reversal = "refunded"
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
    asaas: AsaasClient = Depends(get_asaas_client),
) -> SubscriptionOut:
    """Return the tenant's subscription (read-only view).

    Nenhuma notificação nem sincronização de autoupgrade acontece aqui — isso
    é papel do cron-worker (billing_worker.run_pending_plan_changes). A única
    interação externa possível é a RECUPERAÇÃO read-only de um link de fatura
    ausente pelos ids já rastreados; com os links persistidos presentes, esta
    rota não faz nenhuma chamada externa.
    """
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

    # Cobrança avulsa de recuperação mensal emitida e em aberto: expõe o link
    # dela (a mensalidade revertida não tem link pagável próprio). Só a
    # uma recuperação aberta continua exposta mesmo se a recorrência já
    # avançou para outro ciclo: ela ainda é uma barreira financeira real.
    recovery_url: str | None = None
    recovery_op = find_any_open_operation(db, sub.id, "monthly_recovery")
    if recovery_op is not None:
        recovery_url = recovery_op.invoice_url
    return SubscriptionOut.from_model(
        sub,
        recovery_invoice_url=recovery_url,
        recovery_required=recovery_op is not None,
    )


def _ensure_setup_charge(
    db: Session, sub: Subscription, asaas: AsaasClient, setup_fee: float
) -> None:
    """Emite (ou reconcilia) a cobrança de setup como operação durável.

    Todo POST /payments de setup nasce de uma billing_payment_operation com
    operation_key exclusiva — resposta perdida é reconciliada no retry, nunca
    repetida às cegas. O espelho em sub.asaas_setup_charge_id/url mantém o
    trilho existente de webhook e recovery.
    """
    if sub.setup_pago or sub.asaas_setup_charge_id:
        return
    if setup_fee <= 0:
        # A obrigação contratada é isenta. Isto também cobre adoção/retomada
        # depois de resposta perdida: não existe cobrança a criar, mas o
        # placeholder não pode continuar parecendo devedor de setup.
        sub.setup_pago = True
        sub.asaas_setup_charge_id = None
        sub.asaas_setup_invoice_url = None
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


def _adopt_open_subscription_intent(
    db: Session,
    sub: Subscription,
    asaas: AsaasClient,
    op,
    setup_fee: float,
) -> CheckoutResponse:
    """Reconcilia e ADOTA a assinatura de uma intenção com POST ambíguo.

    Tudo vem do alvo CONGELADO na operação (plano, limite) — nunca do catálogo
    atual: entre o POST perdido e o retry o master pode ter editado o preço ou
    desativado o plano, e reinterpretar uma intenção antiga com valores novos
    reescreveria o que o assinante contratou. Nenhum POST /subscriptions
    acontece aqui: só o GET por externalReference.
    """
    try:
        remote = reconcile_subscription_operation(db, asaas, op)
    except AsaasError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível criar o checkout no Asaas",
        ) from exc
    if remote is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Contratação em reconciliação no Asaas — tente novamente",
        )
    # Assinatura ENCONTRADA e correspondente ao alvo congelado: ADOÇÃO ATÔMICA
    # — o vínculo na Subscription e o fechamento da operação vão no MESMO
    # commit. Antes dele, a operação segue aberta (encontrável): um crash aqui
    # faz o retry reconciliar e adotar de novo, nunca criar outra intenção
    # (logo nunca outro POST).
    sub.plano = op.plano
    sub.limite = op.limite
    sub.status = "pendente"
    sub.asaas_subscription_id = str(remote["id"])
    if op.customer_id:
        sub.asaas_customer_id = op.customer_id
    elif remote.get("customer"):
        sub.asaas_customer_id = str(remote["customer"])
    sub.asaas_invoice_reversal = None
    op.status = "created"
    op.asaas_subscription_id = str(remote["id"])
    db.commit()
    return _resume_tracked_checkout(db, sub, asaas, setup_fee)


@router.post("", response_model=CheckoutResponse)
def create_checkout(
    payload: CheckoutRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_owner),
    asaas: AsaasClient = Depends(get_asaas_client),
) -> CheckoutResponse:
    """Create an Asaas checkout (subscription + one-time setup fee).

    Preço e limite vêm do catálogo `planos` (fonte editada pelo master), não de
    valores fixos no código — ver _plano_ativo_or_422. A exigência de plano
    ATIVO vale apenas para uma contratação realmente nova: retomada e
    reconciliação usam o alvo CONGELADO (ver abaixo).
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
        sub = Subscription(igreja_id=igreja_uuid, plano=payload.plano)
        db.add(sub)
        # Persistida JÁ: a intenção durável de criação referencia sub.id
        # (server_default) antes de qualquer chamada externa.
        db.commit()

    contracted_setup_fee = getattr(sub, "setup_fee_contracted", None)
    if sub.setup_pago:
        setup_fee = 0.0
    elif contracted_setup_fee is not None:
        setup_fee = float(contracted_setup_fee)
    else:
        setup_fee = get_setup_fee_for_igreja(db, igreja)

    # INVARIANTE: mesmo plano + assinatura Asaas já rastreada NUNCA executa
    # outro POST /subscriptions — em qualquer status (pendente, ativa,
    # inadimplente ou revertida) o caminho é a retomada. Troca de plano
    # (plano diferente) segue o fluxo de criação — semântica de produto
    # preservada (risco da recorrência antiga reportado ao dono à parte).
    # A retomada NÃO consulta o catálogo: um plano desativado pelo master
    # depois da contratação (grandfathering) não pode travar o assinante.
    if (
        sub.asaas_subscription_id
        and sub.asaas_subscription_id != "sandbox"
        and sub.plano == payload.plano
    ):
        return _resume_tracked_checkout(db, sub, asaas, setup_fee)

    # RECONCILIAÇÃO ANTES DO CATÁLOGO: se o POST anterior pode ter criado a
    # assinatura no Asaas (`creating`/`reconciling`), o retry do MESMO plano
    # precisa poder adotá-la mesmo que o master tenha desativado o plano nesse
    # intervalo — senão a recorrência remota segue cobrando com o registro
    # local não rastreado, e não existe worker que reconcilie criações.
    aberta = find_open_subscription_operation(db, sub.id)
    if (
        aberta is not None
        and aberta.plano == payload.plano
        and aberta.status in ("creating", "reconciling")
    ):
        frozen_setup = (
            float(aberta.setup_fee)
            if aberta.setup_fee is not None
            else setup_fee
        )
        return _adopt_open_subscription_intent(
            db, sub, asaas, aberta, frozen_setup
        )

    # Contratação realmente NOVA (inclui uma intenção `prepared`, que
    # comprovadamente não postou nada e por isso não tem o que adotar): aqui
    # sim o plano precisa estar ATIVO no catálogo.
    plano_row = _plano_ativo_or_422(db, payload.plano)

    # A INTENÇÃO durável nasce (ou é adotada) ANTES do POST /subscriptions: a
    # operation_key vira a externalReference da assinatura — uma resposta
    # perdida é reconciliada por BUSCA no retry, nunca com um segundo POST (a
    # externalReference localiza, mas não é idempotência de POST no Asaas).
    descricao = subscription_description(payload.plano)
    try:
        op = prepare_subscription_operation(
            db,
            sub=sub,
            plano=payload.plano,
            valor=float(plano_row.preco_mensal),
            limite=plano_row.limite_pessoas,
            descricao=descricao,
            setup_fee=setup_fee,
        )
    except SubscriptionCreateConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    if op.status in ("creating", "reconciling"):
        # Corrida: outro request avançou a MESMA intenção enquanto líamos.
        frozen_setup = (
            float(op.setup_fee) if op.setup_fee is not None else setup_fee
        )
        return _adopt_open_subscription_intent(
            db, sub, asaas, op, frozen_setup
        )

    setup_fee = float(op.setup_fee) if op.setup_fee is not None else setup_fee

    # prepared: claim ATÔMICO da transição — dois requests que adotaram a
    # mesma intenção nunca fazem dois POSTs.
    if not claim_transition(
        db,
        op,
        "prepared",
        "creating",
        attempt_started_at=dt.datetime.now(dt.timezone.utc),
    ):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Contratação em processamento — tente novamente",
        )

    customer_persist_failed = False

    def _persist_resolved_customer(customer_id: str) -> None:
        nonlocal customer_persist_failed
        # Chamado ANTES do POST /subscriptions: com o customer persistido,
        # uma falha ambígua adiante é sabidamente do POST da assinatura (e
        # vira reconciliação — nunca um novo POST às cegas).
        previous_sub_customer = sub.asaas_customer_id
        previous_op_customer = op.customer_id
        sub.asaas_customer_id = customer_id
        op.customer_id = customer_id
        try:
            db.commit()
        except Exception as exc:
            # O POST /subscriptions ainda NÃO aconteceu. O commit falhou, então
            # esta intenção é comprovadamente reutilizável; classificá-la como
            # ambígua a prenderia em reconciling para sempre.
            customer_persist_failed = True
            db.rollback()
            sub.asaas_customer_id = previous_sub_customer
            op.customer_id = previous_op_customer
            claim_transition(
                db, op, "creating", "prepared", attempt_started_at=None
            )
            raise AsaasError("Falha ao persistir o customer resolvido") from exc

    def _track_created_subscription(customer_id: str, subscription_id: str) -> None:
        # Chamado pelo AsaasClient IMEDIATAMENTE após o POST /subscriptions:
        # persiste o vínculo antes de qualquer outra chamada remota, para uma
        # falha posterior nunca deixar assinatura viva sem rastreio — um retry
        # retomaria em vez de duplicar. ATÔMICO: Subscription e operação
        # fecham no MESMO commit (um crash antes dele deixa a operação aberta
        # e o retry reconcilia; nunca nasce uma segunda intenção).
        sub.plano = payload.plano
        sub.limite = plano_row.limite_pessoas
        sub.status = "pendente"
        sub.asaas_customer_id = customer_id
        sub.asaas_subscription_id = subscription_id
        op.status = "created"
        op.asaas_subscription_id = subscription_id
        op.attempt_started_at = None
        db.commit()

    try:
        result = asaas.create_checkout(
            nome=current_user.nome,
            email=current_user.email,
            plano=payload.plano,
            valor=float(plano_row.preco_mensal),
            cpf_cnpj=payload.cpfCnpj,
            external_reference=op.operation_key,
            on_customer_resolved=_persist_resolved_customer,
            on_subscription_created=_track_created_subscription,
        )
    except AsaasRejectedError as exc:
        # Rejeição DEFINITIVA (HTTP 4xx): o Asaas respondeu e NÃO criou nada —
        # a intenção volta a `prepared` e o usuário pode corrigir os dados
        # (CPF/CNPJ, configuração) e tentar de novo. O customer já resolvido
        # fica persistido e é reutilizado no retry.
        claim_transition(
            db, op, "creating", "prepared", attempt_started_at=None
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="O Asaas rejeitou o checkout — confira os dados e tente novamente",
        ) from exc
    except AsaasError as exc:
        if customer_persist_failed:
            # A própria callback já restaurou `prepared`; mantém a classificação
            # pré-POST mesmo se a operação carregava um customer de retry antigo.
            claim_transition(
                db, op, "creating", "prepared", attempt_started_at=None
            )
        elif op.customer_id:
            # Customer já existia quando falhou → o erro pertence ao POST da
            # assinatura (ou veio depois dele): resultado AMBÍGUO
            # (timeout/5xx), o retry deve reconciliar — nunca repetir o POST.
            claim_transition(db, op, "creating", "reconciling")
        else:
            # Falhou ainda no customer: o POST da assinatura comprovadamente
            # não aconteceu — a intenção volta a `prepared` para o retry.
            claim_transition(
                db, op, "creating", "prepared", attempt_started_at=None
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível criar o checkout no Asaas",
        ) from exc

    if result.subscription_id == "sandbox":
        # Guard de sandbox: nenhuma chamada externa aconteceu — a intenção
        # volta a `prepared` (nada a reconciliar).
        claim_transition(
            db, op, "creating", "prepared", attempt_started_at=None
        )

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


def _monthly_recovery_amount(sub: Subscription, asaas: AsaasClient) -> float:
    """Valor da cobrança de recuperação mensal — o CONTRATADO, não o catálogo.

    Fontes, na ordem: o payment mensal rastreado (o próprio valor estornado) e
    a assinatura Asaas existente. O catálogo `planos` NÃO entra: um plano
    desativado com assinantes (grandfathered) continua recuperável e um preço
    editado depois nunca reajusta a recuperação. Sem fonte confiável → erro
    controlado, sem criar cobrança.
    """
    try:
        if sub.asaas_invoice_payment_id:
            payment = asaas.get_payment(sub.asaas_invoice_payment_id)
            if payment is not None and payment.get("value") is not None:
                return float(payment["value"])
        if sub.asaas_subscription_id and sub.asaas_subscription_id != "sandbox":
            remote = asaas.get_subscription(sub.asaas_subscription_id)
            if remote is not None and remote.get("value") is not None:
                return float(remote["value"])
    except (AsaasError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível recuperar a cobrança no Asaas",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "Sem fonte confiável para o valor da recuperação — "
            "nenhuma cobrança foi criada"
        ),
    )


def _stage_monthly_recovery_from_webhook(
    db: Session, sub: Subscription, payment: dict, payment_id: str
) -> BillingPaymentOperation | None:
    """Persiste a dívida da fatura revertida sem chamar o Asaas.

    O payment do webhook é a fonte contratual mais precisa para o valor da
    própria fatura. A intenção nasce na MESMA transação que fecha o acesso e
    ocupa o claim por cobrança-fonte; a ação explícita do owner apenas
    materializa essa intenção depois. Assim um ciclo novo pode atualizar seu
    snapshot sem apagar nem perder a dívida anterior.
    """
    existing = find_open_operation(
        db, sub.id, "monthly_recovery", payment_id
    )
    if existing is not None:
        return existing
    try:
        valor = float(payment["value"])
        if valor <= 0:
            raise ValueError("non-positive payment value")
    except (KeyError, TypeError, ValueError):
        # O payload oficial de payment contém `value`. Falhar fechado sem
        # inventar preço: a reversão continua bloqueando o acesso e não será
        # superada por um ciclo novo enquanto a dívida não for representável.
        logger.error(
            "Asaas monthly reversal without a valid payment value; recovery "
            "intent was not staged"
        )
        return None
    op = BillingPaymentOperation(
        subscription_id=sub.id,
        purpose="monthly_recovery",
        operation_key=f"pastorai-monthly_recovery-{uuid.uuid4()}",
        source_payment_id=payment_id,
        status="prepared",
        valor=valor,
    )
    db.add(op)
    return op


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
    # Se o ciclo CORRENTE está revertido, sua fonte tem precedência absoluta:
    # uma dívida antiga aberta não pode capturar a ação destinada ao ciclo novo.
    # Sem reversão corrente, a ação materializa a dívida antiga reaberta.
    open_recovery = (
        find_open_operation(
            db,
            sub.id,
            "monthly_recovery",
            sub.asaas_invoice_payment_id,
        )
        if sub.asaas_invoice_reversal
        else find_any_open_operation(db, sub.id, "monthly_recovery")
    )
    if not sub.asaas_invoice_reversal and open_recovery is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A cobrança mensal atual não está revertida",
        )

    if (
        sub.asaas_invoice_reversal == "deleted"
        and sub.asaas_invoice_payment_id
    ):
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
            # A intenção criada pelo webhook serviu como barreira durável; a
            # restauração da cobrança-fonte a encerra sem marcá-la como paga
            # (uma reversão futura do mesmo payment precisa poder reabrir).
            if open_recovery is not None:
                open_recovery.status = "failed"
                open_recovery.error = "source payment restored"
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
    # Valor da recuperação = o CONTRATADO desta assinatura, nunca o preço
    # atual do catálogo: um plano desativado pelo master (grandfathering) não
    # pode bloquear a recuperação (422) nem reajustar o assinante por fora.
    valor = (
        float(open_recovery.valor)
        if open_recovery is not None
        else _monthly_recovery_amount(sub, asaas)
    )
    source_payment_id = (
        open_recovery.source_payment_id
        if open_recovery is not None
        else sub.asaas_invoice_payment_id
    )
    try:
        op = ensure_payment_operation(
            db,
            asaas,
            sub=sub,
            purpose="monthly_recovery",
            valor=valor,
            description=MONTHLY_RECOVERY_DESCRIPTION,
            customer_id=sub.asaas_customer_id,
            source_payment_id=source_payment_id,
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

    reversed_setup = find_latest_reversed_setup_operation(db, sub.id)
    contracted_setup = getattr(sub, "setup_fee_contracted", None)
    setup_fee = (
        float(reversed_setup.valor)
        if reversed_setup is not None
        else (
            float(contracted_setup)
            if contracted_setup is not None
            else get_setup_fee_for_igreja(db, igreja)
        )
    )
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


class ChangePlanRequest(BaseModel):
    plano: str

    @field_validator("plano")
    @classmethod
    def _plano(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("plano obrigatório")
        return value


class ChangePlanResponse(BaseModel):
    status: str
    plano: str
    precoMensal: float  # noqa: N815
    # A mudança vale a partir do próximo ciclo: cobranças já emitidas não são
    # alteradas (updatePendingPayments=false, decisão do dono).
    vigencia: str = "proximo_ciclo"


@router.post("/change-plan", response_model=ChangePlanResponse)
def change_plan(
    payload: ChangePlanRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_owner),
    asaas: AsaasClient = Depends(get_asaas_client),
) -> ChangePlanResponse:
    """Troca de plano de assinante: atualiza a assinatura Asaas EXISTENTE.

    Decisão de produto (PLAN-CHANGE-SAFETY-1): PUT in-place com
    ``updatePendingPayments=false`` (vigência no próximo ciclo; cobranças
    emitidas intocadas); NUNCA cria segunda recorrência; exige estado limpo —
    assinatura ativa, setup quitado, sem reversão nem recuperação pendente.
    Não solicita CPF/CNPJ (o cliente Asaas já existe).
    """
    plano_row = _plano_ativo_or_422(db, payload.plano)
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    sub = db.execute(
        select(Subscription).where(Subscription.igreja_id == igreja_uuid)
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Assinatura não encontrada"
        )
    if payload.plano == sub.plano:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Este já é o plano atual",
        )
    if not sub.asaas_subscription_id or sub.asaas_subscription_id == "sandbox":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Não há assinatura Asaas rastreada — contrate um plano primeiro",
        )
    # Estado precisa estar LIMPO antes de trocar: pendências financeiras são
    # regularizadas primeiro (pendente/inadimplente/reversão/recovery/setup).
    if sub.status != "ativa":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Regularize a assinatura antes de mudar de plano",
        )
    if sub.asaas_invoice_reversal:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Há uma cobrança revertida pendente de recuperação",
        )
    if not sub.setup_pago:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Quite a taxa de setup antes de mudar de plano",
        )
    if find_any_open_operation(db, sub.id, "monthly_recovery") is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Há uma cobrança de recuperação em aberto",
        )

    # A guarda de porte vale para uma troca NOVA. Com uma operação JÁ ABERTA
    # quem decide é `ensure_plan_change_operation`: mesmo alvo precisa
    # RECONCILIAR (o PUT pode ter sido aplicado remotamente antes do timeout, e
    # o crescimento posterior da igreja não pode impedir a leitura desse
    # resultado — bloquear aqui prenderia a operação e o slot único para
    # sempre); alvo diferente continua sendo conflito 409.
    if find_open_plan_change(db, sub.id) is None:
        # DOWNGRADE abaixo do porte é rejeitado ANTES de criar operação ou
        # tocar o Asaas: o trigger de auto-upgrade só dispara em mutação de
        # `pessoas` — concluir a troca não o invoca —, então uma igreja de 201
        # ficaria no preço de 100 até um cadastro qualquer acontecer. Contagem
        # canônica lida da tabela (a mesma fonte que o trigger espelha em
        # subscriptions.pessoas).
        pessoas_atual = current_headcount(db, sub)
        limite_alvo = plano_row.limite_pessoas  # None = ilimitado (sempre ok)
        if limite_alvo is not None and pessoas_atual > int(limite_alvo):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"O plano escolhido atende até {limite_alvo} pessoas e a "
                    f"igreja tem {pessoas_atual}"
                ),
            )

    try:
        ensure_plan_change_operation(
            db,
            asaas,
            sub=sub,
            to_plano=plano_row.codigo,
            to_preco=float(plano_row.preco_mensal),
            to_limite=plano_row.limite_pessoas,
        )
    except PlanChangeConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except AsaasError as exc:
        # Plano local permanece INTACTO. Uma rejeição 4xx fecha a operação
        # manual como failed; nesse caso o crescimento ocorrido enquanto ela
        # ocupava o claim precisa ser reavaliado agora, pois o trigger da
        # pessoa foi suprimido por ON CONFLICT e não voltará sozinho.
        if find_open_plan_change(db, sub.id) is None:
            try:
                queue_autoupgrade_if_over_limit(db, sub)
            except Exception:  # noqa: BLE001 - não mascara o erro original
                logger.exception(
                    "Failed to queue autoupgrade after rejected manual plan change"
                )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível atualizar a assinatura no Asaas — tente novamente",
        ) from exc

    # Corrida: o porte pode ter subido ENQUANTO a troca era processada (e
    # concluir a troca não dispara o trigger de pessoas). Se o plano recém
    # aplicado já não cobre a igreja, registra a operação de auto-upgrade
    # AGORA — o cron-worker a processa pelo trilho durável (PUT in-place,
    # nunca POST de assinatura). Falha aqui não invalida a troca concluída.
    try:
        queue_autoupgrade_if_over_limit(db, sub)
    except Exception:  # noqa: BLE001 - enfileiramento nunca derruba a resposta
        logger.exception("Failed to queue autoupgrade after a manual plan change")

    return ChangePlanResponse(
        status=sub.status or "ativa",
        plano=sub.plano,
        precoMensal=float(plano_row.preco_mensal),
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
            select(Subscription)
            .where(Subscription.asaas_subscription_id == str(asaas_sub_id))
            .with_for_update()
        ).scalar_one_or_none()
    if sub is None:
        # O webhook pode vencer a callback do POST /subscriptions: nesse
        # intervalo o id remoto ainda não está na Subscription local, mas a
        # operation_key já foi persistida e é a externalReference do recurso.
        # Isso vale tanto para eventos da assinatura quanto para payments
        # recorrentes dela; cobranças avulsas já retornaram acima.
        external_ref = (
            payment.get("externalReference")
            if payment
            else subscription.get("externalReference")
        )
        if external_ref:
            # Formato novo (CORRECTIVE-6): a externalReference é a
            # operation_key da intenção durável de criação.
            create_op = find_subscription_operation_by_key(db, str(external_ref))
            if create_op is not None:
                candidate = db.execute(
                    select(Subscription).where(
                        Subscription.id == create_op.subscription_id
                    ).with_for_update()
                ).scalar_one_or_none()
                tracked_remote = getattr(create_op, "asaas_subscription_id", None)
                remote_matches = bool(
                    candidate is not None
                    and asaas_sub_id
                    and (not tracked_remote or str(tracked_remote) == str(asaas_sub_id))
                )
                if remote_matches:
                    sub = candidate
                    sub.plano = create_op.plano
                    sub.limite = create_op.limite
                    sub.asaas_subscription_id = str(asaas_sub_id)
                    if getattr(create_op, "customer_id", None):
                        sub.asaas_customer_id = create_op.customer_id
                    frozen_setup = getattr(create_op, "setup_fee", None)
                    if frozen_setup is not None:
                        sub.setup_fee_contracted = frozen_setup
                        if float(frozen_setup) == 0:
                            sub.setup_pago = True
                    create_op.asaas_subscription_id = str(asaas_sub_id)
                    create_op.status = "created"
                    create_op.attempt_started_at = None
                elif candidate is not None:
                    logger.warning(
                        "Asaas webhook creation intent does not match remote "
                        "subscription id; acknowledged"
                    )
            elif not payment:
                # Compat: assinaturas antigas carregam o igreja_id.
                try:
                    igreja_uuid = uuid.UUID(str(external_ref))
                    sub = db.execute(
                        select(Subscription).where(
                            Subscription.igreja_id == igreja_uuid
                        )
                    ).scalar_one_or_none()
                except ValueError:
                    sub = None
    if sub is None:
        logger.info("Asaas webhook for unknown subscription; acknowledged")
        return WebhookResponse(received=True, status=None)

    # Recuperação aberta é uma barreira separada do snapshot do ciclo mensal.
    # Assim B pode avançar e preservar seu próprio status/link, enquanto a
    # dívida de A continua bloqueando acesso até a quitação explícita.
    open_recovery = find_any_open_operation(db, sub.id, "monthly_recovery")

    # DÍVIDA REVERTIDA da cobrança corrente não aceita uma confirmação
    # atrasada da MESMA cobrança. Já um payment id realmente mais novo precisa
    # ser rastreado (inclusive OVERDUE/REFUNDED), sem superar `open_recovery`.
    if sub.asaas_invoice_reversal:
        current_payment_id = sub.asaas_invoice_payment_id
        blocked_payment = bool(
            payment
            and (
                # Confirmação atrasada da própria fatura revertida.
                (payment_id == current_payment_id and reversal is None)
                # Payload legado/malformado sem valor não permitiu criar a
                # intenção durável: nesse caso ainda falhamos fechado.
                or (payment_id != current_payment_id and open_recovery is None)
            )
        )
        blocked_subscription_confirmation = not payment and new_status == "ativa"
        if blocked_payment or blocked_subscription_confirmation:
            logger.info(
                "Asaas billing event cannot supersede an unresolved reversal; "
                "acknowledged"
            )
            return WebhookResponse(received=True, status=None)

    # Veto de ciclo ANTES de qualquer mutação do SNAPSHOT atual. Uma reversão
    # tardia do ciclo A, porém, é dívida nova: persiste recovery por fonte e
    # fecha o gate sem substituir status/id/link/data do ciclo B.
    if payment and _is_stale_cycle_event(sub, payment):
        if reversal and payment_id:
            settled = find_settled_recovery(db, sub.id, payment_id)
            if settled is not None:
                logger.info(
                    "Asaas stale reversal for a source already settled by a "
                    "paid recovery; acknowledged"
                )
                return WebhookResponse(received=True, status=None)
            staged = _stage_monthly_recovery_from_webhook(
                db, sub, payment, payment_id
            )
            if staged is not None:
                db.execute(
                    update(Igreja)
                    .where(Igreja.id == sub.igreja_id, Igreja.status == "ativa")
                    .values(status="inadimplente")
                )
                db.commit()
                return WebhookResponse(received=True, status=new_status)
        logger.info("Asaas webhook for a previous billing cycle; acknowledged")
        return WebhookResponse(received=True, status=None)

    # Fonte JÁ LIQUIDADA: se uma recuperação PAGA (não revertida) cobre esta
    # cobrança-fonte, um estorno duplicado/atrasado dela não reabre a dívida —
    # nem status, nem gate, nem nova recovery. A dívida só volta quando a
    # PRÓPRIA recuperação é revertida (aí a operação sai de `paid` e esta
    # guarda deixa de casar).
    if payment and reversal and payment_id:
        settled = find_settled_recovery(db, sub.id, payment_id)
        if settled is not None:
            logger.info(
                "Asaas reversal for a source already settled by a paid "
                "recovery; acknowledged"
            )
            return WebhookResponse(received=True, status=None)

    if new_status is not None:
        sub.status = new_status
        # Cada ciclo mensal emite uma cobrança nova: acompanha id + link da
        # fatura corrente, senão "Pagar mensalidade" abriria a primeira
        # fatura já quitada. Estorno/exclusão retém o link (inutilizável).
        if payment:
            _apply_monthly_payment_link(sub, payment, reversal=reversal)
            if reversal and payment_id:
                staged = _stage_monthly_recovery_from_webhook(
                    db, sub, payment, payment_id
                )
                if staged is not None:
                    open_recovery = staged
        # Reflect subscription billing only onto the igreja access gate. Setup
        # payment events return above and never change this status.
        if new_status == "ativa":
            # Pagamento do ciclo novo não quita uma recovery anterior. O
            # snapshot fica ativo, mas o gate só abre sem nenhuma dívida.
            if sub.asaas_invoice_reversal is None and open_recovery is None:
                db.execute(
                    update(Igreja)
                    .where(
                        Igreja.id == sub.igreja_id,
                        Igreja.status == "inadimplente",
                    )
                    .values(status="ativa")
                )
        elif new_status == "inadimplente":
            db.execute(
                update(Igreja)
                .where(Igreja.id == sub.igreja_id, Igreja.status == "ativa")
                .values(status="inadimplente")
            )
        db.commit()

    return WebhookResponse(received=True, status=new_status)
