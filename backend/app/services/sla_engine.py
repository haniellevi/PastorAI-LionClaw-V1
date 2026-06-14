"""SLA engine: detect blown deadlines and charge/escalate by WhatsApp (O5).

Responsibilities:

1. Scan the tenant's timed items for SLA breaches:
   - work_queue_items of a timed tipo (relatorio 2h, conectar_celula 12h,
     fonovisita 24h) that are still open.
   - consolidacoes with an open 24h connection deadline (prazo_conexao).
2. For a blown deadline, charge the responsible leader by WhatsApp (Evolution).
3. For an unanswered charge past the escalation grace, escalate to coordination
   (pastor / lider_g12) and open a coordination work item.

Dispatch is idempotent: each (item, stage) emits exactly one charge/escalation,
deduped via an `agent_conversation_logs` event whose name embeds the item id (so
the dedupe key is never altered by payload masking).

The engine reads prazos written by the routers/triggers (sprint-004/005) and
sends through the official number (sprint-006); the deadline math lives in
`app.domain.sla`. It is a separate channel from the panel assistant and the
WhatsApp orchestrator.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AgentConversationLog,
    AppUser,
    Consolidacao,
    Pessoa,
    UserRole,
    WhatsappConnection,
    WorkQueueItem,
)
from app.domain.sla import (
    SLA_CONNECTION,
    SLA_POLICIES,
    WORK_QUEUE_TIPO_TO_SLA,
    SlaStatus,
    classify,
    resolve_deadline,
)
from app.services.evolution import EvolutionClient, EvolutionError

logger = logging.getLogger("pastorai.sla_engine")

# work_queue_status values that still need attention (not resolved).
OPEN_WORK_QUEUE_STATUSES: frozenset[str] = frozenset({"aberto", "assumido"})

# Roles that receive escalations (coordination). admin is operational, not a
# pastoral coordination contact, so it is not targeted here.
COORDINATION_ROLES: frozenset[str] = frozenset({"pastor", "lider_g12"})


@dataclass(frozen=True)
class SlaBreach:
    """A tracked item whose SLA deadline (or escalation grace) has elapsed."""

    igreja_id: uuid.UUID
    source: str  # "work_queue" | "consolidacao"
    item_id: uuid.UUID
    kind: str
    status: SlaStatus
    titulo: str
    pessoa_id: uuid.UUID | None = None
    responsavel_user_id: uuid.UUID | None = None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def scan_breaches(
    session: Session, igreja_id: uuid.UUID, now: dt.datetime | None = None
) -> list[SlaBreach]:
    """Return the COBRANCA/ESCALONAMENTO breaches for one igreja (no dispatch)."""
    now = now or _now()
    breaches: list[SlaBreach] = []

    # --- work_queue items of a timed tipo, still open ------------------------
    items = session.execute(
        select(WorkQueueItem).where(WorkQueueItem.igreja_id == igreja_id)
    ).scalars().all()
    for item in items:
        kind = WORK_QUEUE_TIPO_TO_SLA.get(item.tipo or "")
        if kind is None:
            continue
        if (item.status or "aberto") not in OPEN_WORK_QUEUE_STATUSES:
            continue
        policy = SLA_POLICIES[kind]
        deadline = resolve_deadline(
            policy=policy, prazo=item.prazo, created_at=item.created_at, now=now
        )
        status = classify(policy=policy, deadline=deadline, now=now)
        if status is SlaStatus.OK:
            continue
        breaches.append(
            SlaBreach(
                igreja_id=igreja_id,
                source="work_queue",
                item_id=item.id,
                kind=kind,
                status=status,
                titulo=item.titulo,
                pessoa_id=item.pessoa_id,
                responsavel_user_id=item.responsavel_id,
            )
        )

    # --- consolidacoes with an open 24h connection deadline -----------------
    consolidacoes = session.execute(
        select(Consolidacao).where(
            Consolidacao.igreja_id == igreja_id,
            Consolidacao.concluida.is_(False),
            Consolidacao.prazo_conexao.is_not(None),
        )
    ).scalars().all()
    policy_conn = SLA_POLICIES[SLA_CONNECTION]
    for cons in consolidacoes:
        deadline = resolve_deadline(
            policy=policy_conn,
            prazo=cons.prazo_conexao,
            created_at=cons.created_at,
            now=now,
        )
        status = classify(policy=policy_conn, deadline=deadline, now=now)
        if status is SlaStatus.OK:
            continue
        breaches.append(
            SlaBreach(
                igreja_id=igreja_id,
                source="consolidacao",
                item_id=cons.id,
                kind=SLA_CONNECTION,
                status=status,
                titulo="Consolidação aguardando conexão",
                pessoa_id=cons.pessoa_id,
                responsavel_user_id=cons.responsavel_id,
            )
        )

    return breaches


def _dispatch_event_name(breach: SlaBreach) -> str:
    """Stable, non-masked dedupe key for one (item, stage) dispatch."""
    return f"sla_{breach.status.value}:{breach.source}:{breach.item_id}"


def _already_dispatched(session: Session, igreja_id: uuid.UUID, evento: str) -> bool:
    existing = session.execute(
        select(AgentConversationLog.id).where(
            AgentConversationLog.igreja_id == igreja_id,
            AgentConversationLog.evento == evento,
        )
    ).first()
    return existing is not None


def _user_phone(session: Session, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    app_user = session.get(AppUser, user_id)
    if app_user is None or app_user.pessoa_id is None:
        return None
    pessoa = session.get(Pessoa, app_user.pessoa_id)
    return pessoa.telefone if pessoa else None


def _pessoa_phone(session: Session, pessoa_id: uuid.UUID | None) -> str | None:
    if pessoa_id is None:
        return None
    pessoa = session.get(Pessoa, pessoa_id)
    return pessoa.telefone if pessoa else None


def _coordination_phones(session: Session, igreja_id: uuid.UUID) -> list[str]:
    """Phones of coordination contacts (pastor / lider_g12) in the igreja."""
    user_ids = session.execute(
        select(UserRole.user_id).where(
            UserRole.igreja_id == igreja_id,
            UserRole.papel.in_(COORDINATION_ROLES),
        )
    ).scalars().all()
    phones: list[str] = []
    for uid in set(user_ids):
        phone = _user_phone(session, uid)
        if phone:
            phones.append(phone)
    return phones


_CHARGE_TEMPLATES: dict[str, str] = {
    "relatorio": (
        "Olá! O relatório da célula está pendente além do prazo. "
        "Pode enviar agora? 🙏"
    ),
    SLA_CONNECTION: (
        "Olá! Há uma conexão de consolidação aguardando além do prazo. "
        "Pode dar continuidade? 🙏"
    ),
    "fonovisita": (
        "Olá! A fonovisita está pendente além do prazo. "
        "Pode realizar o contato? 🙏"
    ),
}


def _charge_text(breach: SlaBreach) -> str:
    return _CHARGE_TEMPLATES.get(
        breach.kind, "Olá! Há uma pendência além do prazo. Pode verificar? 🙏"
    )


def _escalation_text(breach: SlaBreach) -> str:
    return (
        "Atenção (coordenação): a pendência "
        f"'{breach.titulo}' segue sem resposta do líder além do prazo. "
        "Favor acompanhar."
    )


def _instance(session: Session, igreja_id: uuid.UUID) -> str | None:
    conn = session.execute(
        select(WhatsappConnection).where(WhatsappConnection.igreja_id == igreja_id)
    ).scalar_one_or_none()
    return conn.instance if conn else None


class SlaEngine:
    """Detect SLA breaches and dispatch charges/escalations via WhatsApp."""

    def __init__(self, evolution: EvolutionClient | None = None) -> None:
        self._evolution = evolution or EvolutionClient()

    def run_for_igreja(
        self, session: Session, igreja_id: uuid.UUID, now: dt.datetime | None = None
    ) -> list[SlaBreach]:
        """Scan + dispatch for one igreja, returning the breaches handled."""
        now = now or _now()
        instance = _instance(session, igreja_id)
        breaches = scan_breaches(session, igreja_id, now)
        handled: list[SlaBreach] = []
        for breach in breaches:
            if self._dispatch(session, breach, instance):
                handled.append(breach)
        session.commit()
        return handled

    def _dispatch(
        self, session: Session, breach: SlaBreach, instance: str | None
    ) -> bool:
        """Charge or escalate one breach exactly once (idempotent)."""
        evento = _dispatch_event_name(breach)
        if _already_dispatched(session, breach.igreja_id, evento):
            return False

        if breach.status is SlaStatus.ESCALONAMENTO:
            recipients = _coordination_phones(session, breach.igreja_id)
            texto = _escalation_text(breach)
            self._open_coordination_item(session, breach)
        else:
            phone = _user_phone(session, breach.responsavel_user_id) or _pessoa_phone(
                session, breach.pessoa_id
            )
            recipients = [phone] if phone else []
            texto = _charge_text(breach)

        sent_to: list[str] = []
        if instance:
            for phone in recipients:
                try:
                    self._evolution.send_text(instance, phone, texto)
                    sent_to.append(phone)
                except EvolutionError:
                    logger.warning(
                        "SLA dispatch failed to send (%s) for %s",
                        breach.status.value,
                        breach.item_id,
                    )
        else:
            logger.info(
                "No official WhatsApp instance for igreja %s; SLA logged only",
                breach.igreja_id,
            )

        # Record the dispatch so it is not repeated on the next tick. Logged even
        # when no recipient/instance was available, to avoid tight re-detection
        # loops; the payload keeps an audit of what happened.
        self._log_dispatch(session, breach, evento, recipients_count=len(sent_to))
        return True

    def _open_coordination_item(self, session: Session, breach: SlaBreach) -> None:
        """Create a coordination work item so escalation is actionable in-panel."""
        session.add(
            WorkQueueItem(
                igreja_id=breach.igreja_id,
                tipo="atendimento",
                titulo=f"Escalonamento SLA: {breach.titulo}",
                contexto=(
                    f"SLA {breach.kind} sem resposta do líder "
                    f"({breach.source}:{breach.item_id})"
                ),
                pessoa_id=breach.pessoa_id,
                status="aberto",
                prioridade=1,
            )
        )

    def _log_dispatch(
        self,
        session: Session,
        breach: SlaBreach,
        evento: str,
        *,
        recipients_count: int,
    ) -> None:
        # Imported here to avoid a hard dependency for callers that only scan.
        from app.agent.masking import log_agent_event  # noqa: PLC0415

        log_agent_event(
            session,
            igreja_id=breach.igreja_id,
            evento=evento,
            payload={
                "kind": breach.kind,
                "source": breach.source,
                "itemId": str(breach.item_id),
                "status": breach.status.value,
                "recipients": recipients_count,
            },
        )


def run_all_igrejas(
    session: Session, engine: SlaEngine | None = None, now: dt.datetime | None = None
) -> int:
    """Run the SLA engine for every igreja with an SLA-relevant open item.

    Returns the number of breaches handled across all tenants. Tenant set is
    derived from open work_queue items and open consolidacoes so we do not scan
    igrejas with nothing pending.
    """
    engine = engine or SlaEngine()
    now = now or _now()

    igreja_ids: set[uuid.UUID] = set()
    igreja_ids.update(
        session.execute(select(WorkQueueItem.igreja_id).distinct()).scalars().all()
    )
    igreja_ids.update(
        session.execute(
            select(Consolidacao.igreja_id)
            .where(Consolidacao.concluida.is_(False))
            .distinct()
        ).scalars().all()
    )

    total = 0
    for igreja_id in igreja_ids:
        try:
            total += len(engine.run_for_igreja(session, igreja_id, now))
        except Exception:  # noqa: BLE001 - one tenant must not break the others
            logger.exception("SLA engine failed for igreja %s", igreja_id)
            session.rollback()
    return total
