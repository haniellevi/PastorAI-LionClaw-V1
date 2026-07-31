"""Sincronização assíncrona do auto-upgrade de plano (cron-worker).

O trigger `fn_subscription_autoupgrade` (redefinido na migration
BILLING-SANDBOX-1) NÃO promove mais o plano local quando existe assinatura
Asaas rastreada: ele registra UMA operação durável em
`billing_plan_change_operations` (origin='autoupgrade', alvo congelado) e
nada mais. Este módulo é quem sincroniza, a cada tick do cron-worker:

  1. DESCOBERTA cross-tenant na sessão compartilhada (papel de conexão,
     BYPASSRLS — só leitura), coletando as operações autoupgrade abertas com a
     igreja dona (mesmo desenho do sweep de SLA, D3).
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
    Subscription,
    UserRole,
    WhatsappConnection,
)
from app.db.session import get_session_factory
from app.db.tenant_session import mark_tenant_scoped
from app.deps import ADMIN_ROLE
from app.services.asaas import AsaasClient, AsaasError
from app.services.billing import (
    OPEN_PLAN_CHANGE_STATUSES,
    ensure_plan_change_operation,
)
from app.services.evolution import EvolutionClient, EvolutionError

logger = logging.getLogger("pastorai.billing_worker")


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
) -> str:
    """Notify the admin once when the plan was promoted by the autoupgrade flow.

    Idempotent: a `subscription_upgrade:<plano>` event in agent_conversation_logs
    marks a plan as already announced, so repeated calls do not re-notify.
    Returns the delivery outcome:

      - ``"sent"``    — mensagem emitida agora (ou nada a emitir: sem conexão
        WhatsApp/telefones, o marcador fica reservado e não há retry a fazer);
      - ``"already"`` — marcador já existia/perdeu a corrida (outro processo é
        o dono do anúncio);
      - ``"skipped"`` — nada a anunciar (sem assinatura ou tier base);
      - ``"retry"``   — TODOS os envios falharam: a reserva foi liberada e o
        chamador deve manter a entrega descobrível para uma nova tentativa.

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

    evento = _autoupgrade_event_name(sub.plano)
    already = db.execute(
        select(AgentConversationLog.id).where(
            AgentConversationLog.igreja_id == igreja_id,
            AgentConversationLog.evento == evento,
        )
    ).first()
    if already is not None:
        return "already"  # saída antecipada barata

    # Only notify when there is an upgrade marker to record beyond the base tier.
    if sub.plano == "ate_100":
        return "skipped"

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
        return "already"

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
        return "retry"

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
        outcome = notify_autoupgrade(db, igreja_id, evolution)
    except Exception:  # noqa: BLE001 - notificação nunca reverte billing
        logger.exception("Autoupgrade notification failed for igreja %s", igreja_id)
        return False  # segue 'pending': redescoberta no próximo tick
    if outcome == "retry":
        return False  # reserva liberada; segue 'pending' para o próximo tick
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
    """Processa UMA operação de autoupgrade na sessão tenant-scoped.

    Recarrega a operação dentro do tenant (ela pode ter sido concluída por uma
    troca manual entre a descoberta e o claim) e delega o PUT/reconciliação a
    `ensure_plan_change_operation` com o ALVO CONGELADO da própria operação —
    nunca recalculado aqui. Retorna True quando a troca foi concluída.
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
        origin="autoupgrade",
    )
    if result.status != "completed":
        return False

    # Notificação SÓ depois do commit da conclusão (feito por
    # _complete_plan_change) — e com entrega DURÁVEL: se falhar agora, a
    # operação completed permanece com notify_status='pending' e o próximo
    # tick a redescobre. Nunca desfaz a troca já confirmada.
    _deliver_upgrade_notification(db, op, igreja_id, evolution)
    return True


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
    """Processa as operações de autoupgrade abertas em todos os tenants.

    Retorna o número de trocas CONCLUÍDAS neste tick. Segue o desenho D3 do
    sweep de SLA: a `session` compartilhada (BYPASSRLS) faz só a DESCOBERTA
    read-only; cada operação roda numa NOVA sessão `mark_tenant_scoped`,
    fechada ao fim (o role/GUC nunca volta ao pool). Operações `manual` são
    ignoradas — pertencem ao request do assinante, nunca ao worker.
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
        .where(
            BillingPlanChangeOperation.origin == "autoupgrade",
            BillingPlanChangeOperation.status.in_(OPEN_PLAN_CHANGE_STATUSES),
        )
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
