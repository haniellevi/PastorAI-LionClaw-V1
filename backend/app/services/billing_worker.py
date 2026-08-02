"""Sincronização assíncrona do auto-upgrade de plano (cron-worker).

O trigger `fn_subscription_autoupgrade` (redefinido na migration
BILLING-SANDBOX-1) NÃO promove mais o plano local quando existe assinatura
Asaas rastreada: ele registra UMA operação durável em
`billing_plan_change_operations` (origin='autoupgrade', alvo congelado) e
nada mais. Este módulo é quem sincroniza, a cada tick do cron-worker:

  1. DESCOBERTA cross-tenant na sessão compartilhada (papel de conexão,
     BYPASSRLS — só leitura), coletando as trocas de plano abertas com a
     igreja dona (mesmo desenho do sweep de SLA, D3). Trocas `manual` entram
     junto: sem isso, uma operação cujo request morreu no PUT dependeria de o
     assinante repetir a solicitação para sair de `reconciling`.
  2. CADA operação é processada numa NOVA sessão tenant-scoped
     (`mark_tenant_scoped`), reutilizando `ensure_plan_change_operation` — o
     MESMO mecanismo durável da troca manual: claim atômico, exatamente um
     PUT /subscriptions/{id} com updatePendingPayments=false, timeout →
     `reconciling` e retry por GET (nunca outro PUT às cegas). Plano/limite
     locais e o rótulo da igreja só mudam após confirmação remota. NUNCA há
     POST /subscriptions nem cobrança de setup neste caminho.
  3. A notificação de upgrade (WhatsApp, idempotente pelo marcador
     `subscription_upgrade:<plano>`) dispara SOMENTE após a conclusão/commit —
     nunca mais como efeito colateral de GET /subscription.

Falha remota preserva o plano local anterior e deixa a operação recuperável
(`reconciling`/`prepared`) para o próximo tick; a falha de um tenant não
interrompe os demais.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.masking import release_agent_event, reserve_agent_event
from app.db.models import (
    AgentConversationLog,
    AppUser,
    BillingPlanChangeOperation,
    Plano,
    Subscription,
    UserRole,
    WhatsappConnection,
)
from app.db.session import get_session_factory
from app.db.tenant_session import mark_tenant_scoped
from app.deps import ADMIN_ROLE
from app.domain.billing import PLAN_ORDER, plan_rank
from app.services.asaas import AsaasClient, AsaasError, subscription_description
from app.services.billing import (
    OPEN_PLAN_CHANGE_STATUSES,
    PlanChangeConflict,
    current_headcount,
    ensure_plan_change_operation,
    find_open_plan_change,
)
from app.services.evolution import EvolutionClient, EvolutionError

logger = logging.getLogger("pastorai.billing_worker")

# Lease da RESERVA de notificação: uma reserva sem marcador de entrega mais
# velha que isto é considerada abandonada (crash entre reservar e enviar) e
# pode ser reivindicada por outro tick.
NOTIFY_RESERVATION_LEASE = dt.timedelta(minutes=15)


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


def _autoupgrade_sent_event_name(plano: str) -> str:
    """Marcador de ENTREGA comprovada — separado da reserva (CORRECTIVE-8).

    A reserva (`subscription_upgrade:<plano>`) só prova a INTENÇÃO de enviar;
    este marcador é gravado somente APÓS um `send_text` bem-sucedido. Ambos
    casam o predicado `subscription\\_upgrade:%` do índice único parcial.
    """
    return f"subscription_upgrade:{plano}:sent"


def notify_autoupgrade(
    db: Session,
    igreja_id: uuid.UUID,
    evolution: EvolutionClient,
    *,
    plano: str | None = None,
) -> str:
    """Notify the admin once when the plan was promoted by the autoupgrade flow.

    RESERVA ≠ ENTREGA (CORRECTIVE-8): a reserva
    (`subscription_upgrade:<plano>`) só prova a intenção; a entrega comprovada
    grava um segundo marcador (`...:sent`) DEPOIS do `send_text`. Uma reserva
    sem marcador de entrega e mais velha que ``NOTIFY_RESERVATION_LEASE`` é
    abandonada (crash entre reservar e enviar) e é reivindicada aqui — a
    janela de crash nunca finge entrega. Returns the delivery outcome:

      - ``"sent"``     — mensagem emitida AGORA (marcador de entrega gravado);
      - ``"already"``  — entrega COMPROVADA anteriormente (marcador ``:sent``);
      - ``"inflight"`` — reserva recente de outro processo: não envia nem
        conclui; o chamador mantém a entrega pendente/descobrível;
      - ``"skipped"``  — nada a anunciar/entregar (sem assinatura, tier base,
        ou sem conexão WhatsApp/telefones — reserva liberada);
      - ``"retry"``    — TODOS os envios falharam: reserva liberada e o
        chamador deve manter a entrega descobrível para nova tentativa.

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
        return "skipped"

    # O worker passa o alvo congelado da operação. O fallback mantém a chamada
    # direta legada, mas retry de uma operação nunca deriva do plano corrente:
    # ele pode já ter avançado para outro degrau no mesmo tick.
    target_plano = plano or sub.plano

    # Only notify when there is an upgrade marker to record beyond the base tier.
    if target_plano == "ate_100":
        return "skipped"

    evento = _autoupgrade_event_name(target_plano)
    evento_sent = _autoupgrade_sent_event_name(target_plano)

    # ENTREGA já comprovada? (marcador :sent) — nunca reenvia.
    delivered = db.execute(
        select(AgentConversationLog.id).where(
            AgentConversationLog.igreja_id == igreja_id,
            AgentConversationLog.evento == evento_sent,
        )
    ).first()
    if delivered is not None:
        return "already"

    # Reserva existente SEM entrega: recente = outro processo pode estar
    # enviando agora (inflight); mais velha que o lease = abandonada por um
    # crash entre reservar e enviar — reivindica e tenta entregar.
    reservation = db.execute(
        select(AgentConversationLog).where(
            AgentConversationLog.igreja_id == igreja_id,
            AgentConversationLog.evento == evento,
        )
    ).scalar_one_or_none()
    if reservation is not None:
        created = getattr(reservation, "created_at", None)
        now = dt.datetime.now(dt.timezone.utc)
        if created is None or (now - created) < NOTIFY_RESERVATION_LEASE:
            return "inflight"
        release_agent_event(db, reservation)
        logger.info("Reclaimed an abandoned autoupgrade notification reservation")

    # Lidas ANTES da reserva (gap-2): só valores simples sobrevivem até o
    # send, nenhuma query fica pendurada numa transação aberta pelo envio.
    conn = db.execute(
        select(WhatsappConnection).where(WhatsappConnection.igreja_id == igreja_id)
    ).scalar_one_or_none()
    instance = conn.instance if conn else None
    phones = _admin_phones(db, igreja_id)

    marker = reserve_agent_event(
        db, igreja_id=igreja_id, evento=evento, payload={"plano": target_plano}
    )
    if marker is None:
        # Perdeu a corrida AGORA: outro processo acabou de reservar.
        return "inflight"

    texto = (
        "Aviso de assinatura: seu plano foi atualizado automaticamente para "
        f"'{target_plano}' por aumento do número de pessoas. 🙏"
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
        return "retry"

    if not attempted:
        # Sem conexão WhatsApp/telefones: NADA a entregar — a reserva é
        # liberada e nenhum marcador de entrega é gravado (não finge envio).
        release_agent_event(db, marker)
        return "skipped"

    # ENTREGA comprovada: o marcador :sent é a prova durável (idempotente
    # pelo índice único — um segundo processo não o duplica).
    reserve_agent_event(
        db,
        igreja_id=igreja_id,
        evento=evento_sent,
        payload={"plano": target_plano},
    )
    return "sent"


def _deliver_upgrade_notification(
    db: Session,
    op: BillingPlanChangeOperation,
    igreja_id: uuid.UUID,
    evolution: EvolutionClient,
) -> bool:
    """Entrega DURÁVEL da notificação de upgrade — separada do financeiro.

    `notify_status='pending'` é o estado descobrível: só vira 'sent' quando o
    desfecho não pede retry. Falha do Evolution (ou crash) mantém 'pending' e
    o próximo tick reencontra a operação COMPLETED pendente de aviso; o
    marcador idempotente em agent_conversation_logs impede duplicar a mensagem
    após sucesso. Nunca reverte nem bloqueia o billing.
    """
    if op.notify_status != "pending":
        return False
    try:
        outcome = notify_autoupgrade(
            db, igreja_id, evolution, plano=op.to_plano
        )
    except Exception:  # noqa: BLE001 - notificação nunca reverte billing
        logger.exception("Autoupgrade notification failed for igreja %s", igreja_id)
        return False  # segue 'pending': redescoberta no próximo tick
    if outcome in ("retry", "inflight"):
        # retry: envio falhou (reserva liberada). inflight: reserva de outro
        # processo sem entrega comprovada — NUNCA vira 'sent' por presunção;
        # o lease reivindica reservas abandonadas no tick seguinte.
        return False
    op.notify_status = "sent"
    db.commit()
    return outcome == "sent"


def _process_operation(
    db: Session,
    asaas: AsaasClient,
    evolution: EvolutionClient,
    op_id: uuid.UUID,
    igreja_id: uuid.UUID,
) -> bool:
    """Processa UMA troca de plano aberta na sessão tenant-scoped.

    Recarrega a operação dentro do tenant (ela pode ter sido concluída pelo
    request do assinante entre a descoberta e o claim) e delega o
    PUT/reconciliação a `ensure_plan_change_operation` com o ALVO CONGELADO da
    própria operação — nunca recalculado aqui, e a origem é preservada.
    Retorna True quando a troca foi concluída.
    """
    op = db.get(BillingPlanChangeOperation, op_id)
    if op is None or op.status not in OPEN_PLAN_CHANGE_STATUSES:
        return False
    sub = db.get(Subscription, op.subscription_id)
    if sub is None:
        return False

    result = ensure_plan_change_operation(
        db,
        asaas,
        sub=sub,
        to_plano=op.to_plano,
        to_preco=float(op.to_preco),
        to_limite=op.to_limite,
        origin=op.origin,
    )
    if result.status != "completed":
        return False

    # Notificação SÓ depois do commit da conclusão (feito por
    # _complete_plan_change) — e com entrega DURÁVEL: se falhar agora, a
    # operação completed permanece com notify_status='pending' e o próximo
    # tick a redescobre. Nunca desfaz a troca já confirmada.
    _deliver_upgrade_notification(db, op, igreja_id, evolution)

    # Multi-tier (CORRECTIVE-8): o porte pode ter cruzado MAIS de um degrau
    # antes deste upgrade concluir — os triggers repetidos coalesceram na
    # operação recém-completada, e o UPDATE do plano não dispara o trigger de
    # pessoas. Reavalia AGORA e persegue os degraus restantes, sem depender
    # de uma futura mutação de pessoas.
    _chase_remaining_tiers(db, asaas, evolution, sub, igreja_id)
    return True


def _next_ladder_target(db: Session, sub: Subscription) -> Plano | None:
    """Próximo degrau elegível da escada canônica, com alvo do CATÁLOGO.

    Elegível quando o porte CORRENTE excede o limite vigente. A contagem é
    relida da tabela `pessoas` (`current_headcount`) e não do espelho
    ``sub.pessoas`` do objeto em memória: a sessão não expira no commit
    (``expire_on_commit=False``), então depois de uma troca de plano o espelho
    ainda carrega o valor lido ANTES da chamada externa — e é exatamente a
    corrida "o porte subiu durante o PUT" que esta função precisa enxergar. O
    preço/limite congelam do catálogo `planos` do master; plano fora do
    catálogo não gera operação (nunca inventar preço remoto — mesma regra do
    trigger).
    """
    try:
        limite = int(sub.limite) if sub.limite is not None else None
    except (TypeError, ValueError):
        return None
    if limite is None:
        return None  # plano ilimitado: não há degrau acima
    pessoas = current_headcount(db, sub)
    if pessoas <= limite:
        return None
    idx = plan_rank(sub.plano)
    if idx < 0 or idx + 1 >= len(PLAN_ORDER):
        return None
    for proximo in PLAN_ORDER[idx + 1 :]:
        plano_row = db.execute(
            select(Plano).where(Plano.codigo == proximo, Plano.ativo.is_(True))
        ).scalar_one_or_none()
        if plano_row is None or plano_row.preco_mensal is None:
            continue
        alvo_limite = plano_row.limite_pessoas
        if alvo_limite is None or pessoas <= int(alvo_limite):
            return plano_row
    return None


def queue_autoupgrade_if_over_limit(db: Session, sub: Subscription) -> bool:
    """Registra a operação de auto-upgrade quando o porte já passou do limite.

    Usado depois de uma troca MANUAL concluída: aplicar o novo plano não
    dispara o trigger de pessoas, então uma igreja cujo porte subiu durante o
    processamento (ou que trocou para um plano no limite) ficaria abaixo do
    porte até a próxima mutação de pessoa. O porte vem da releitura canônica
    feita por `_next_ladder_target` — o espelho em memória é sempre anterior à
    chamada externa e nunca enxergaria essa corrida. Aqui só a INTENÇÃO é
    registrada — quem executa o PUT é o cron-worker, pelo trilho durável.
    Nenhuma chamada externa acontece nesta função. Retorna True quando
    enfileirou.
    """
    if not sub.asaas_subscription_id or sub.asaas_subscription_id == "sandbox":
        return False
    alvo = _next_ladder_target(db, sub)
    if alvo is None:
        return False
    if find_open_plan_change(db, sub.id) is not None:
        return False  # já há uma operação aberta (manual ou de porte)
    op = BillingPlanChangeOperation(
        subscription_id=sub.id,
        asaas_subscription_id=str(sub.asaas_subscription_id),
        from_plano=sub.plano,
        to_plano=alvo.codigo,
        to_preco=float(alvo.preco_mensal),
        to_limite=alvo.limite_pessoas,
        to_descricao=subscription_description(alvo.codigo),
        origin="autoupgrade",
        status="prepared",
        notify_status="pending",
    )
    db.add(op)
    try:
        db.commit()
    except Exception:  # noqa: BLE001 - claim perdido = já existe uma aberta
        db.rollback()
        return False
    return True


def _chase_remaining_tiers(
    db: Session,
    asaas: AsaasClient,
    evolution: EvolutionClient,
    sub: Subscription,
    igreja_id: uuid.UUID,
) -> None:
    """Cria e processa os degraus RESTANTES após um upgrade concluído.

    Cada follow-up nasce como operação `prepared` própria (claim pelo índice
    único parcial) e passa pelo MESMO mecanismo durável — PUT na assinatura
    existente, reconciliação em retry, local só após confirmação. Uma troca
    manual aberta tem precedência (conflito encerra a perseguição). Loop
    limitado pela altura da escada.
    """
    if not sub.asaas_subscription_id:
        return  # sem recorrência remota o trigger local já resolve sozinho
    for _ in range(len(PLAN_ORDER)):
        alvo = _next_ladder_target(db, sub)
        if alvo is None:
            return
        try:
            followup = ensure_plan_change_operation(
                db,
                asaas,
                sub=sub,
                to_plano=alvo.codigo,
                to_preco=float(alvo.preco_mensal),
                to_limite=alvo.limite_pessoas,
                origin="autoupgrade",
            )
        except PlanChangeConflict:
            return  # operação manual aberta é do assinante — nunca atropela
        if followup.status != "completed":
            return  # ficou aberta (reconciling): o próximo tick continua
        _deliver_upgrade_notification(db, followup, igreja_id, evolution)


def _retry_pending_notification(
    db: Session,
    evolution: EvolutionClient,
    op_id: uuid.UUID,
    igreja_id: uuid.UUID,
) -> bool:
    """Reentrega o aviso de uma operação já COMPLETED (descoberta dedicada)."""
    op = db.get(BillingPlanChangeOperation, op_id)
    if op is None or op.status != "completed":
        return False
    return _deliver_upgrade_notification(db, op, igreja_id, evolution)


def run_pending_plan_changes(
    session: Session,
    *,
    session_factory: Callable[[], Session] | None = None,
    asaas: AsaasClient | None = None,
    evolution: EvolutionClient | None = None,
) -> int:
    """Processa as trocas de plano abertas em todos os tenants.

    Retorna o número de trocas CONCLUÍDAS neste tick. Segue o desenho D3 do
    sweep de SLA: a `session` compartilhada (BYPASSRLS) faz só a DESCOBERTA
    read-only; cada operação roda numa NOVA sessão `mark_tenant_scoped`,
    fechada ao fim (o role/GUC nunca volta ao pool).

    Operações `manual` TAMBÉM são processadas: o request do assinante pode ter
    morrido no meio (timeout do PUT) e, sem o worker, a operação dependeria de
    ele repetir a solicitação — que as guardas do endpoint podem recusar
    (porte, inadimplência), prendendo a operação e o slot único da assinatura
    para sempre. O que continua exclusivo do autoupgrade é a NOTIFICAÇÃO: a
    troca manual nasce com `notify_status='skipped'`.
    """
    if session_factory is None:
        session_factory = get_session_factory()
    asaas = asaas or AsaasClient()
    evolution = evolution or EvolutionClient()

    open_rows = session.execute(
        select(BillingPlanChangeOperation.id, Subscription.igreja_id)
        .join(
            Subscription,
            Subscription.id == BillingPlanChangeOperation.subscription_id,
        )
        .where(BillingPlanChangeOperation.status.in_(OPEN_PLAN_CHANGE_STATUSES))
    ).all()
    # Entrega durável: operações já COMPLETED cuja notificação ainda não saiu
    # (falha do Evolution ou crash pós-conclusão) são redescobertas aqui.
    notify_rows = session.execute(
        select(BillingPlanChangeOperation.id, Subscription.igreja_id)
        .join(
            Subscription,
            Subscription.id == BillingPlanChangeOperation.subscription_id,
        )
        .where(
            BillingPlanChangeOperation.origin == "autoupgrade",
            BillingPlanChangeOperation.status == "completed",
            BillingPlanChangeOperation.notify_status == "pending",
        )
    ).all()

    work: list[tuple[str, uuid.UUID, uuid.UUID]] = [
        ("process", op_id, igreja_id) for op_id, igreja_id in open_rows
    ] + [("notify", op_id, igreja_id) for op_id, igreja_id in notify_rows]

    completed = 0
    for kind, op_id, igreja_id in work:
        tenant_session = session_factory()
        try:
            mark_tenant_scoped(tenant_session, igreja_id, source="cron_billing")
            if kind == "process":
                if _process_operation(
                    tenant_session, asaas, evolution, op_id, igreja_id
                ):
                    completed += 1
            else:
                _retry_pending_notification(
                    tenant_session, evolution, op_id, igreja_id
                )
        except AsaasError:
            # Falha/timeout remoto: a operação ficou `reconciling` (plano
            # local intacto) e o próximo tick reconcilia — sem PUT repetido.
            logger.warning(
                "Autoupgrade plan change pending reconciliation (igreja %s)",
                igreja_id,
            )
        except Exception:  # noqa: BLE001 - um tenant não derruba os demais
            logger.exception("Autoupgrade plan change failed (igreja %s)", igreja_id)
            tenant_session.rollback()
        finally:
            tenant_session.close()
    return completed
