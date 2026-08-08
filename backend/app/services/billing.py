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

import datetime as dt
import logging
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    BillingPaymentOperation,
    BillingPlanChangeOperation,
    BillingSettings,
    BillingSubscriptionOperation,
    Igreja,
    Pessoa,
    Plano,
    Subscription,
)
from app.services.asaas import (
    AsaasClient,
    AsaasError,
    AsaasRejectedError,
    map_payment_status,
    payment_invoice_url,
    payment_reversal_kind,
    subscription_description,
)

logger = logging.getLogger("pastorai.billing")

# Categorias que representam membros para fins de porte/cobrança. ``lider``
# permanece por compatibilidade com dados legados; novas lideranças são
# derivadas das células e a pessoa continua classificada, no mínimo, como
# ``membro``. Contato e visitante nunca entram nesta contagem.
BILLABLE_MEMBER_TYPES = ("membro", "discipulo", "lider", "pastor")

# Estados em que a operação ainda "ocupa" o slot (claim) da assinatura+propósito.
OPEN_OPERATION_STATUSES = ("prepared", "creating", "reconciling", "created")
# Estados abertos da troca de plano (claim único por assinatura).
OPEN_PLAN_CHANGE_STATUSES = ("prepared", "processing", "reconciling")
# Estados abertos da CRIAÇÃO de assinatura (claim único por Subscription).
OPEN_SUBSCRIPTION_OP_STATUSES = ("prepared", "creating", "reconciling")
# Lease da TENTATIVA de PUT: um `processing` mais velho que isto é uma tentativa
# abandonada (crash entre o claim e o PUT, ou processo morto no meio) e pode ser
# retomada. Folgado sobre o timeout de 20s do cliente HTTP.
PLAN_CHANGE_ATTEMPT_LEASE = dt.timedelta(minutes=5)


class PlanChangeConflict(Exception):
    """Já existe uma troca de plano EM ANDAMENTO para outro plano."""


class SubscriptionCreateConflict(Exception):
    """Já existe uma criação de assinatura EM ANDAMENTO para outro plano."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _attempt_lease_alive(op: BillingPlanChangeOperation) -> bool:
    """Há uma tentativa de PUT EM VOO nesta operação?

    Sem marca de tentativa (linha criada antes desta coluna existir) o lease é
    tratado como vencido: um `processing` órfão precisa poder ser retomado.
    """
    started = op.attempt_started_at
    if started is None:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=dt.timezone.utc)
    return _utcnow() - started < PLAN_CHANGE_ATTEMPT_LEASE


def claim_transition(
    db: Session, op, from_status: str, to_status: str, **values
) -> bool:
    """Transição de estado ATÔMICA de uma operação durável (UPDATE condicional).

    O índice único parcial garante uma única LINHA aberta, mas não serializa a
    transição de estado: dois requests que leram a mesma operação `prepared`
    fariam ambos o POST. Aqui só o rowcount==1 ganha a posse do passo — quem
    perde deve recarregar e RECONCILIAR, nunca chamar a API externa. Também
    protege o resultado do dono: um retry não regride `created` para
    `reconciling` (o WHERE exige o estado de origem). ``values`` extras são
    gravados no MESMO UPDATE (ex.: o lease da tentativa).
    """
    result = db.execute(
        update(type(op))
        .where(type(op).id == op.id, type(op).status == from_status)
        .values(status=to_status, **values)
    )
    db.commit()
    claimed = getattr(result, "rowcount", 0) == 1
    if claimed:
        op.status = to_status
        for key, value in values.items():
            setattr(op, key, value)
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


def is_complimentary_plan(plano: Plano | None) -> bool:
    """A zero-priced plan is a master-granted entitlement, never a checkout.

    ``preco_mensal`` is constrained to non-negative values by the admin API.
    Keeping the rule on the catalog avoids a second per-tenant exemption flag
    and makes MRR naturally remain zero for test churches.
    """
    if plano is None or plano.preco_mensal is None:
        return False
    try:
        return float(plano.preco_mensal) == 0.0
    except (TypeError, ValueError):
        return False


def assigned_complimentary_plan(
    db: Session, igreja: Igreja | None
) -> Plano | None:
    """Return the complimentary plan assigned by the platform master, if any.

    Inactive plans remain valid for already-assigned churches (grandfathering),
    matching the existing paid-plan semantics.  Inactive only prevents new
    assignments in the UI; it must not silently revoke an existing grant.
    """
    plan_code = getattr(igreja, "plano", None) if igreja is not None else None
    if not plan_code:
        return None
    plano = db.execute(
        select(Plano).where(Plano.codigo == plan_code)
    ).scalar_one_or_none()
    return plano if is_complimentary_plan(plano) else None


def find_open_operation(
    db: Session, subscription_id, purpose: str, source_payment_id: str | None = None
) -> BillingPaymentOperation | None:
    """A operação em andamento desta assinatura+propósito+COBRANÇA-FONTE.

    A cobrança-fonte faz parte da identidade do claim, não é metadado: uma
    recuperação nasce para quitar UMA mensalidade específica. Selecionar só por
    (assinatura, propósito) faria a recovery do ciclo B adotar a operação órfã
    do ciclo A — e uma quitação tardia de A regularizaria a dívida de B. O
    setup não tem fonte (``source_payment_id IS NULL``) e a comparação com
    ``None`` já o isola.
    """
    return db.execute(
        select(BillingPaymentOperation).where(
            BillingPaymentOperation.subscription_id == subscription_id,
            BillingPaymentOperation.purpose == purpose,
            BillingPaymentOperation.source_payment_id.is_(None)
            if source_payment_id is None
            else BillingPaymentOperation.source_payment_id == str(source_payment_id),
            BillingPaymentOperation.status.in_(OPEN_OPERATION_STATUSES),
        )
    ).scalar_one_or_none()


def find_any_open_operation(
    db: Session, subscription_id, purpose: str
) -> BillingPaymentOperation | None:
    """Qualquer operação aberta do propósito, de QUALQUER cobrança-fonte.

    Só para guardas que perguntam "há pendência financeira deste tipo?" — a
    troca de plano exige estado limpo. Nunca use para decidir quitação ou
    reutilização de cobrança: isso é papel de `find_open_operation`, que
    respeita a autoridade da fonte.
    """
    return db.execute(
        select(BillingPaymentOperation)
        .where(
            BillingPaymentOperation.subscription_id == subscription_id,
            BillingPaymentOperation.purpose == purpose,
            BillingPaymentOperation.status.in_(OPEN_OPERATION_STATUSES),
        )
        .limit(1)
    ).scalars().first()


def find_latest_reversed_setup_operation(
    db: Session, subscription_id
) -> BillingPaymentOperation | None:
    """Última cobrança de setup revertida, fonte do valor contratado.

    O master pode alterar ou isentar a taxa depois da contratação. Uma
    reemissão substitui a cobrança revertida e, portanto, herda o ``valor``
    congelado nela — nunca reprecifica um contrato existente.
    """
    return db.execute(
        select(BillingPaymentOperation)
        .where(
            BillingPaymentOperation.subscription_id == subscription_id,
            BillingPaymentOperation.purpose == "setup",
            BillingPaymentOperation.status == "reversed",
        )
        .order_by(BillingPaymentOperation.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def find_settled_recovery(
    db: Session, subscription_id, source_payment_id: str
) -> BillingPaymentOperation | None:
    """A recuperação PAGA (não revertida) que liquidou esta cobrança-fonte.

    Relação durável source→recovery: quando existe, um estorno
    duplicado/atrasado da cobrança-fonte já foi compensado — o webhook deve
    ignorá-lo (a dívida só volta se a PRÓPRIA recovery for revertida, o que
    move a operação para `reversed` e desfaz esta consulta).
    """
    if not source_payment_id:
        return None
    return db.execute(
        select(BillingPaymentOperation).where(
            BillingPaymentOperation.subscription_id == subscription_id,
            BillingPaymentOperation.purpose == "monthly_recovery",
            BillingPaymentOperation.source_payment_id == str(source_payment_id),
            BillingPaymentOperation.status == "paid",
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
            ).with_for_update()
        ).scalar_one_or_none()
        if op is not None:
            return op
    if external_reference:
        op = db.execute(
            select(BillingPaymentOperation)
            .where(
                BillingPaymentOperation.operation_key == str(external_reference)
            )
            .with_for_update()
        ).scalar_one_or_none()
        # A operation_key localiza uma intenção, não autoriza rebind. Se ela
        # já pertence a outro payment, este webhook é um duplicado remoto
        # conflitante e não pode alterar a operação original.
        if (
            op is not None
            and op.asaas_payment_id
            and (
                payment_id is None
                or str(op.asaas_payment_id) != str(payment_id)
            )
        ):
            return None
        return op
    return None


def payment_matches_operation(
    op: BillingPaymentOperation,
    payment: dict,
    *,
    description: str,
    customer_id: str | None,
) -> bool:
    """A cobrança bate integralmente com o alvo congelado da operação?"""
    try:
        value_ok = float(payment.get("value")) == float(op.valor)
    except (TypeError, ValueError):
        value_ok = False
    customer_ok = bool(
        customer_id
        and payment.get("customer")
        and str(payment.get("customer")) == str(customer_id)
    )
    return bool(
        payment.get("id")
        and value_ok
        and customer_ok
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
    op = find_open_operation(db, sub.id, purpose, source_payment_id)

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
            # O índice único parcial (subscription_id, purpose, fonte | status
            # aberto) faz o claim atômico: a corrida perde aqui e adota a
            # operação do vencedor em vez de criar uma segunda cobrança. A
            # fonte entra na chave para que uma recovery órfã de ciclo antigo
            # não bloqueie a recuperação do ciclo corrente.
            db.commit()
        except Exception:
            db.rollback()
            op = find_open_operation(db, sub.id, purpose, source_payment_id)
            if op is None:
                raise

    if op.status == "created" and op.asaas_payment_id:
        # Webhook pode ter sido perdido depois de a cobrança rastreada ser
        # paga/revertida. O retry é também o caminho explícito de reparo:
        # relê o payment exato e converge o produto sem emitir novo POST.
        payment = asaas.get_payment(str(op.asaas_payment_id))
        if payment is None:
            return op
        operation_status, _reversal = _payment_operation_status(payment)
        if operation_status != "created":
            return _apply_payment_operation_snapshot(
                db,
                op,
                sub=sub,
                payment=payment,
                expected_statuses=("created",),
            )
        return op

    if op.status in ("creating", "reconciling"):
        op = _reconcile_payment_operation(
            db,
            asaas,
            op,
            sub=sub,
            description=description,
            customer_id=customer_id,
        )
        if op.status != "prepared":
            return op

    # prepared: ainda não houve POST. O claim da transição é ATÔMICO — dois
    # requests que adotaram a MESMA operação `prepared` não podem ambos
    # postar; quem perde o rowcount reconcilia em vez de chamar a API.
    if not claim_transition(
        db, op, "prepared", "creating", attempt_started_at=_utcnow()
    ):
        db.rollback()
        current = find_open_operation(db, sub.id, purpose, source_payment_id)
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
    except AsaasRejectedError as exc:
        # Rejeição DEFINITIVA (mínimo local / HTTP 4xx): nada foi criado — a
        # operação fecha como `failed` (erro registrado) e LIBERA o índice
        # parcial para uma nova operação corrigida. Nunca fica em reconciling.
        finish_operation(
            db,
            op,
            ("creating",),
            status="failed",
            error=str(exc),
            attempt_started_at=None,
        )
        raise
    except AsaasError:
        # Resultado ambíguo (o POST pode ter chegado): daqui em diante só
        # reconciliação — nunca outro POST automático.
        claim_transition(db, op, "creating", "reconciling")
        raise
    if charge is None:
        # Sandbox (sends bloqueados): nada foi criado — a operação volta a
        # `prepared` e pode tentar de novo quando os envios forem permitidos.
        claim_transition(
            db, op, "creating", "prepared", attempt_started_at=None
        )
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
        attempt_started_at=None,
    )
    return op


def _payment_operation_status(payment: dict) -> tuple[str, str | None]:
    reversal = (
        "deleted"
        if payment.get("deleted")
        else payment_reversal_kind(payment.get("status"))
    )
    mapped_status = (
        "inadimplente"
        if reversal
        else map_payment_status(payment.get("status"))
    )
    operation_status = (
        "reversed"
        if reversal
        else "paid"
        if mapped_status == "ativa"
        else "created"
    )
    return operation_status, reversal


def _apply_payment_operation_snapshot(
    db: Session,
    op: BillingPaymentOperation,
    *,
    sub: Subscription,
    payment: dict,
    expected_statuses: tuple[str, ...],
) -> BillingPaymentOperation:
    operation_status, reversal = _payment_operation_status(payment)
    # Mesma ordem do webhook: operação -> assinatura. Se o webhook ou outro
    # retry venceu a leitura externa, o status recarregado impede regressão.
    db.refresh(op, with_for_update=True)
    if op.status not in expected_statuses:
        return op
    db.refresh(sub, with_for_update=True)
    op.status = operation_status
    op.asaas_payment_id = str(payment["id"])
    op.invoice_url = None if reversal else payment_invoice_url(payment)
    op.attempt_started_at = None
    if operation_status in ("paid", "reversed"):
        # autoflush=False: o probe de operações abertas precisa enxergar o
        # novo estado desta própria linha dentro da transação atômica.
        db.flush()
        _apply_reconciled_payment_state(
            db,
            sub=sub,
            op=op,
            payment=payment,
            operation_status=operation_status,
        )
    db.commit()
    return op


def _reconcile_payment_operation(
    db: Session,
    asaas: AsaasClient,
    op: BillingPaymentOperation,
    *,
    sub: Subscription,
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
        if payment_matches_operation(
            op,
            p,
            description=description,
            customer_id=customer_id,
        )
    ]
    if len(matches) == 1:
        payment = matches[0]
        return _apply_payment_operation_snapshot(
            db,
            op,
            sub=sub,
            payment=payment,
            expected_statuses=("creating", "reconciling"),
        )
    if len(matches) > 1:
        finish_operation(
            db,
            op,
            ("creating", "reconciling"),
            status="reconciling",
            error="Múltiplas cobranças encontradas; revisão manual obrigatória",
            attempt_started_at=None,
        )
        logger.warning("Billing operation ambiguous on reconcile; kept blocking")
        raise AsaasError("Reconciliação ambígua da cobrança — intervenção manual")
    # 0 correspondências: mantém reconciling e falha com segurança — o próximo
    # retry reconcilia de novo (sem POST automático). Condicional: nunca
    # regride um `created` gravado pelo dono do POST em paralelo.
    # Lease vencido só prova que o processo local terminou; não prova que o
    # POST /payments foi rejeitado. Busca vazia pode ser atraso de consistência,
    # então a intenção ambígua permanece reconciling e nunca repete o POST.
    claim_transition(db, op, "creating", "reconciling")
    raise AsaasError("Cobrança em reconciliação no Asaas — tente novamente")


def _apply_reconciled_payment_state(
    db: Session,
    *,
    sub: Subscription,
    op: BillingPaymentOperation,
    payment: dict,
    operation_status: str,
) -> None:
    """Aplica ao produto o status autoritativo lido na reconciliação.

    O chamador já travou operação e assinatura na mesma ordem usada pelo
    webhook. Esta função só deriva as mutações; a adoção e todos os efeitos
    são comitados atomicamente pelo chamador.
    """
    payment_id = str(payment["id"])

    if op.purpose == "setup":
        if operation_status == "paid":
            sub.setup_pago = True
            sub.asaas_setup_charge_id = payment_id
            sub.asaas_setup_invoice_url = None
        else:
            sub.setup_pago = False
            sub.asaas_setup_reversed_payment_id = payment_id
            if str(sub.asaas_setup_charge_id) == payment_id:
                sub.asaas_setup_charge_id = None
            sub.asaas_setup_invoice_url = None
        return

    if operation_status == "paid":
        if (
            op.source_payment_id
            and str(op.source_payment_id) == str(sub.asaas_invoice_payment_id)
            and sub.asaas_invoice_reversal is not None
        ):
            sub.status = "ativa"
            sub.asaas_invoice_reversal = None
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
    else:
        if op.source_payment_id:
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
                sub.asaas_invoice_reversal = "refunded"


def current_headcount_for_igreja(db: Session, igreja_id) -> int:
    """Porte faturável da igreja — membros ativos, não todos os cadastros.

    A coluna legada ``subscriptions.pessoas`` espelha esta contagem, mas pode
    estar desatualizada entre eventos — e o objeto ORM carregado antes de uma
    chamada externa fica STALE por definição (a sessão não expira no commit).
    Toda decisão de porte (bloquear downgrade, enfileirar auto-upgrade) relê a
    fonte canônica e inclui somente membro/discípulo/líder legado/pastor que não
    esteja arquivado nem marcado como fora da igreja (CSIM).
    """
    total = db.execute(
        select(func.count())
        .select_from(Pessoa)
        .where(
            Pessoa.igreja_id == igreja_id,
            Pessoa.tipo.in_(BILLABLE_MEMBER_TYPES),
            Pessoa.sem_interesse.is_(False),
            Pessoa.arquivada_em.is_(None),
        )
    ).scalar_one_or_none()
    try:
        contagem = int(total) if total is not None else 0
    except (TypeError, ValueError):
        contagem = 0
    return contagem


def current_headcount(db: Session, sub: Subscription) -> int:
    """Compatibility wrapper for billing paths that already hold a subscription."""
    return current_headcount_for_igreja(db, sub.igreja_id)


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
    """O estado remoto já reflete o alvo congelado da operação?

    Compara valor E DESCRIÇÃO: dois planos podem ter o mesmo preço mensal (o
    console master permite), então um PUT perdido por timeout seria
    indistinguível de um aplicado se só o valor fosse conferido — o remoto
    antigo já traria o preço-alvo. Com a descrição congelada, preço igual +
    descrição do plano anterior mantém a operação em `reconciling` e o plano
    local intacto.
    """
    if not isinstance(remote, dict):
        return False
    try:
        value_ok = float(remote.get("value")) == float(op.to_preco)
    except (TypeError, ValueError):
        return False
    if not value_ok:
        return False
    alvo = op.to_descricao or subscription_description(op.to_plano)
    return remote.get("description") == alvo


def _complete_plan_change(
    db: Session, op: BillingPlanChangeOperation, sub: Subscription
) -> bool:
    """Aplica o alvo somente se ``op`` ainda for a troca autoritativa.

    A chamada externa pode ficar em voo enquanto o worker reconcilia a mesma
    operação, libera o slot e uma troca mais nova conclui. O UPDATE condicional
    fecha a operação velha e reserva a aplicação local na MESMA transação; se
    ela já fechou, a resposta atrasada não escreve plano nem entitlement.
    """
    claimed = db.execute(
        update(BillingPlanChangeOperation)
        .where(
            BillingPlanChangeOperation.id == op.id,
            BillingPlanChangeOperation.status.in_(("processing", "reconciling")),
        )
        .values(status="completed", attempt_started_at=None)
    )
    if getattr(claimed, "rowcount", 0) != 1:
        db.rollback()
        return False

    sub.plano = op.to_plano
    sub.limite = op.to_limite
    igreja = db.execute(
        select(Igreja).where(Igreja.id == sub.igreja_id)
    ).scalar_one_or_none()
    if igreja is not None:
        igreja.plano = op.to_plano
    op.status = "completed"
    op.attempt_started_at = None
    db.commit()
    return True


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

    O alvo (plano/preço/limite/descrição) é congelado e persistido ANTES do
    PUT. Um retry com a operação em `processing`/`reconciling` RECONCILIA
    primeiro pelo GET da assinatura (valor E descrição remotos == alvo); só se
    o remoto ainda NÃO refletir o alvo é que o PUT se repete — ele é
    idempotente por construção (mesma assinatura, alvos congelados,
    ``updatePendingPayments=false``), e o claim atômico por lease garante um
    PUT por vez. O plano/limite locais só mudam após confirmação ou
    reconciliação. Rejeição 4xx fecha como `failed` e libera o slot; falha
    ambígua preserva o plano atual e mantém a operação recuperável. Nunca cria
    outra recorrência.
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
            # Identidade completa do alvo (com o preço) para a reconciliação.
            to_descricao=subscription_description(to_plano),
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
            if not _complete_plan_change(db, op, sub):
                raise PlanChangeConflict(
                    "A troca foi superada por uma alteração mais recente — recarregue"
                )
            return op
        if op.status == "processing" and _attempt_lease_alive(op):
            # Outro processo está DENTRO do PUT agora: não há o que reconciliar
            # nem o que repetir — só esperar o desfecho dele.
            raise AsaasError("Troca de plano em processamento — tente novamente")
        if op.status == "processing":
            # Lease vencido = tentativa abandonada (crash entre o claim e o
            # PUT). Devolve ao pool CONDICIONALMENTE: se o dono concluiu nesse
            # meio-tempo, o rowcount é 0 e o resultado dele fica preservado.
            claim_transition(db, op, "processing", "reconciling")
        # `reconciling` sem match remoto: REPETE o PUT. Ele é idempotente por
        # construção — mesma assinatura, preço e descrição congelados na
        # operação e `updatePendingPayments=false` —, então repetir é seguro e
        # é a ÚNICA saída deste estado: sem isso a operação (e o slot único da
        # assinatura) ficariam presos para sempre, com toda troca futura em 409.
        if not claim_transition(
            db, op, "reconciling", "processing", attempt_started_at=_utcnow()
        ):
            db.rollback()
            raise AsaasError(
                "Troca de plano em reconciliação no Asaas — tente novamente"
            )
    # prepared: marca a intenção e faz exatamente UM PUT. Claim ATÔMICO — o
    # worker e um request manual que leram a mesma operação `prepared` nunca
    # fazem dois PUTs: quem perde o rowcount reconcilia no retry.
    elif not claim_transition(
        db, op, "prepared", "processing", attempt_started_at=_utcnow()
    ):
        db.rollback()
        raise AsaasError("Troca de plano em processamento — tente novamente")
    try:
        remote = asaas.update_subscription(
            op.asaas_subscription_id,
            valor=float(op.to_preco),
            # MESMA descrição que a reconciliação confere depois.
            descricao=op.to_descricao or subscription_description(op.to_plano),
        )
    except AsaasRejectedError as exc:
        # Rejeição DEFINITIVA do PUT (4xx): o remoto ficou como estava — a
        # operação fecha como `failed` (plano local INTACTO) e o claim único
        # é liberado para uma solicitação corrigida. O worker não redescobre
        # operações failed, então não há loop automático.
        finish_operation(
            db, op, ("processing",), status="failed", error=str(exc)
        )
        raise
    except AsaasError:
        # Ambíguo (o PUT pode ter chegado): plano local fica INTACTO e o
        # retry reconcilia — nunca outro PUT automático imediato.
        claim_transition(db, op, "processing", "reconciling")
        raise
    if remote is None:
        # Sandbox (sends bloqueados): não há remoto a confirmar — completa
        # localmente para o fluxo de desenvolvimento seguir utilizável.
        if not _complete_plan_change(db, op, sub):
            raise PlanChangeConflict(
                "A troca foi superada por uma alteração mais recente — recarregue"
            )
        return op
    if not _complete_plan_change(db, op, sub):
        raise PlanChangeConflict(
            "A troca foi superada por uma alteração mais recente — recarregue"
        )
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
        ).with_for_update()
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
    customer_ok = bool(
        op.customer_id
        and remote.get("customer")
        and str(remote.get("customer")) == str(op.customer_id)
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
    limite: int | None = None,
    setup_fee: float | None = None,
    ciclo: str = "MONTHLY",
) -> BillingSubscriptionOperation:
    """Garante UMA intenção durável de criação para esta Subscription.

    Persistida ANTES de qualquer chamada externa; o claim é o índice único
    parcial (subscription_id | status aberto). Uma intenção aberta para outro
    plano só é substituída quando está comprovado que NENHUM POST remoto
    aconteceu (`prepared`, sem assinatura rastreada) — nesse caso a antiga vira
    `superseded` por transição ATÔMICA e só o vencedor cria a substituta.
    `creating`/`reconciling` são ambíguos: o POST pode ter chegado ao Asaas, e
    trocar de alvo poderia abandonar uma recorrência viva — conflito explícito.
    """
    op = find_open_subscription_operation(db, sub.id)
    if op is not None and op.plano != plano:
        if op.status != "prepared" or op.asaas_subscription_id:
            raise SubscriptionCreateConflict(
                f"Já existe uma contratação em andamento para o plano {op.plano}"
            )
        # Substituição SEGURA: a linha antiga não é retargetada silenciosamente
        # — ela fecha em estado terminal com o motivo, e só quem vencer o
        # rowcount segue para criar a nova intenção.
        if claim_transition(
            db,
            op,
            "prepared",
            "superseded",
            error=f"Substituída pela contratação do plano {plano}",
        ):
            op = None
        else:
            op = find_open_subscription_operation(db, sub.id)
            if op is not None and op.plano != plano:
                raise SubscriptionCreateConflict(
                    f"Já existe uma contratação em andamento para o plano {op.plano}"
                )
    if op is not None:
        frozen_setup = op.setup_fee if op.setup_fee is not None else setup_fee
        if op.setup_fee is None:
            op.setup_fee = frozen_setup
        sub.setup_fee_contracted = frozen_setup
        db.commit()
        return op
    op = BillingSubscriptionOperation(
        subscription_id=sub.id,
        operation_key=f"pastorai-subcreate-{uuid.uuid4()}",
        customer_id=sub.asaas_customer_id,
        plano=plano,
        valor=valor,
        limite=limite,
        setup_fee=setup_fee,
        ciclo=ciclo,
        descricao=descricao,
        status="prepared",
    )
    sub.setup_fee_contracted = setup_fee
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
        finish_operation(
            db,
            op,
            ("creating", "reconciling"),
            status="reconciling",
            error="Múltiplas assinaturas encontradas; revisão manual obrigatória",
            attempt_started_at=None,
        )
        logger.warning("Subscription create ambiguous on reconcile; kept blocking")
        raise AsaasError(
            "Reconciliação ambígua da assinatura — intervenção manual"
        )
    # Ausência temporária na busca NÃO prova que o POST remoto falhou. A
    # externalReference localiza, mas não torna POST /subscriptions idempotente;
    # portanto uma criação ambígua jamais volta automaticamente a `prepared`.
    # Mantê-la em reconciling exige intervenção/reconciliação posterior e evita
    # uma segunda assinatura recorrente viva.
    claim_transition(db, op, "creating", "reconciling")
    return None
