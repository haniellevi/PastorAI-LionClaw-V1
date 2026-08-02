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
    Subscription,
)
from app.services.asaas import (
    AsaasClient,
    AsaasError,
    AsaasRejectedError,
    payment_invoice_url,
    subscription_description,
)

logger = logging.getLogger("pastorai.billing")

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
# POSTs de criação também são ambíguos, mas um processo morto não pode ocupar
# o slot para sempre. Após este lease, uma reconciliação com zero matches pode
# devolver o claim a prepared e permitir uma nova tentativa controlada.
CREATE_ATTEMPT_LEASE = dt.timedelta(minutes=5)


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


def _create_attempt_lease_alive(op) -> bool:
    """Ainda pode existir um POST de criação em voo para esta operação?"""
    started = getattr(op, "attempt_started_at", None)
    if started is None:
        # Legado sem relógio é AMBÍGUO, não comprovadamente abandonado. Falhar
        # fechado evita repetir um POST que pode ter criado recurso remoto.
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=dt.timezone.utc)
    return _utcnow() - started < CREATE_ATTEMPT_LEASE


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
        return op  # cobrança já existe e está rastreada

    if op.status in ("creating", "reconciling"):
        op = _reconcile_payment_operation(
            db, asaas, op, description=description, customer_id=customer_id
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
            attempt_started_at=None,
        )
        return op
    if len(matches) > 1:
        finish_operation(
            db,
            op,
            ("creating", "reconciling"),
            status="failed",
            attempt_started_at=None,
        )
        logger.warning("Billing operation ambiguous on reconcile; marked failed")
        raise AsaasError("Reconciliação ambígua da cobrança — intervenção manual")
    # 0 correspondências: mantém reconciling e falha com segurança — o próximo
    # retry reconcilia de novo (sem POST automático). Condicional: nunca
    # regride um `created` gravado pelo dono do POST em paralelo.
    if not _create_attempt_lease_alive(op):
        current_status = op.status
        if claim_transition(
            db,
            op,
            current_status,
            "prepared",
            attempt_started_at=None,
        ):
            return op
    claim_transition(db, op, "creating", "reconciling")
    raise AsaasError("Cobrança em reconciliação no Asaas — tente novamente")


def current_headcount(db: Session, sub: Subscription) -> int:
    """Porte atual da igreja — contagem canônica, não o espelho defasado.

    `subscriptions.pessoas` é mantido pelo trigger a cada mutação, mas pode
    estar desatualizado entre eventos — e o objeto ORM carregado antes de uma
    chamada externa fica STALE por definição (a sessão não expira no commit).
    Toda decisão de porte (bloquear downgrade, enfileirar auto-upgrade) lê a
    tabela `pessoas` diretamente e usa o espelho apenas como piso (nunca aceita
    um valor MENOR do que o já registrado).
    """
    total = db.execute(
        select(func.count()).select_from(Pessoa).where(Pessoa.igreja_id == sub.igreja_id)
    ).scalar_one_or_none()
    try:
        contagem = int(total) if total is not None else 0
    except (TypeError, ValueError):
        contagem = 0
    try:
        espelho = int(sub.pessoas) if sub.pessoas is not None else 0
    except (TypeError, ValueError):
        espelho = 0
    return max(contagem, espelho)


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
            _complete_plan_change(db, op, sub)
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
            status="failed",
            attempt_started_at=None,
        )
        logger.warning("Subscription create ambiguous on reconcile; marked failed")
        raise AsaasError(
            "Reconciliação ambígua da assinatura — intervenção manual"
        )
    if not _create_attempt_lease_alive(op):
        current_status = op.status
        claim_transition(
            db,
            op,
            current_status,
            "prepared",
            attempt_started_at=None,
        )
        return None
    claim_transition(db, op, "creating", "reconciling")
    return None
