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
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.db.tenant_session import mark_tenant_scoped

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
    # W3.2A: uma consolidação ABANDONADA (Pessoa arquivada) não é mais "aberta"
    # — não pode ser cobrada/escalonada por WhatsApp (revisão externa PR#163).
    consolidacoes = session.execute(
        select(Consolidacao).where(
            Consolidacao.igreja_id == igreja_id,
            Consolidacao.concluida.is_(False),
            Consolidacao.abandonada_em.is_(None),
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


def _coordination_item_event_name(breach: SlaBreach) -> str:
    """Chave de dedupe PERMANENTE (nunca liberada) do WorkQueueItem de
    coordenação de uma escalação — SEC-4 gap-2.

    Separada de `_dispatch_event_name` de propósito: aquele marcador É
    liberado em falha total de envio (at-least-once, permite retry do
    WhatsApp); este NUNCA é liberado, porque criar o item de coordenação é
    uma ação "no máximo uma vez pra sempre" — diferente de "reenviar até dar
    certo". Cobre o mesmo predicado `sla\\_%` do índice único parcial
    `agent_conversation_logs_idem_marker_uidx`, sem precisar de migration
    nova.
    """
    return f"sla_coordenacao_item:{breach.source}:{breach.item_id}"


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
        """Charge or escalate one breach exactly once (idempotent, SEC-4).

        Ordem (evita o duplo-envio sob corrida — achado da revisão do índice
        `agent_conversation_logs_idem_marker_uidx`): RESERVA o marcador
        (INSERT + commit imediato, via `reserve_agent_event`) ANTES de
        qualquer `send_text`. Se a reserva perder a corrida (outro processo
        já reservou o MESMO marcador), retorna sem enviar — nenhum envio
        duplicado é possível, porque nenhum envio acontece sem reserva
        vencida antes. Nenhuma transação fica aberta durante a chamada
        externa: a reserva já commitou antes do primeiro `send_text`.

        At-least-once: se o envio falhar pra TODOS os destinatários
        tentados, a reserva é liberada (`release_agent_event`) e a próxima
        varredura tenta de novo — perder uma cobrança/aviso é pior, neste
        domínio, do que ocasionalmente duplicar um WhatsApp (ver decisão no
        PR). "Sem destinatário/instância" continua só logado (comportamento
        preexistente — evita loop de reprocessamento apertado pra item sem
        contato resolvível).

        Gap-2 (revisão SEC-4): o `WorkQueueItem` de coordenação de uma
        escalação é gate-ado por um marcador PERMANENTE separado
        (`_coordination_item_event_name`, nunca liberado) — resolve o
        cenário em que a reserva de ENVIO é liberada (falha total) e a
        varredura seguinte reprocessa a mesma breach: sem o gate, isso
        recriava o item de coordenação a cada retry.
        """
        evento = _dispatch_event_name(breach)
        if _already_dispatched(session, breach.igreja_id, evento):
            return False  # saída antecipada barata, antes de montar destinatários/texto

        from app.agent.masking import (  # noqa: PLC0415
            release_agent_event,
            reserve_agent_event,
        )

        if breach.status is SlaStatus.ESCALONAMENTO:
            recipients = _coordination_phones(session, breach.igreja_id)
            texto = _escalation_text(breach)
            # session.add() pendente — commita JUNTO com a reserva do
            # marcador PERMANENTE abaixo (mesma transação): se essa reserva
            # perder a corrida (sequencial, num retry, ou concorrente, numa
            # segunda varredura), o rollback do reserve_agent_event desfaz
            # o item pendente também — no máximo 1 WorkQueueItem por breach.
            self._open_coordination_item(session, breach)
            # Resultado não importa aqui: o destino do WorkQueueItem pendente
            # já foi decidido pelo commit/rollback desta chamada.
            reserve_agent_event(
                session,
                igreja_id=breach.igreja_id,
                evento=_coordination_item_event_name(breach),
            )
        else:
            phone = _user_phone(session, breach.responsavel_user_id) or _pessoa_phone(
                session, breach.pessoa_id
            )
            recipients = [phone] if phone else []
            texto = _charge_text(breach)

        marker = reserve_agent_event(
            session,
            igreja_id=breach.igreja_id,
            evento=evento,
            payload={
                "kind": breach.kind,
                "source": breach.source,
                "itemId": str(breach.item_id),
                "status": breach.status.value,
            },
        )
        if marker is None:
            # Perdeu a corrida: outro processo já reserva este marcador —
            # nunca envia aqui também (SEC-4).
            return False

        sent_to: list[str] = []
        attempted = False
        if instance:
            for phone in recipients:
                attempted = True
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

        if attempted and not sent_to:
            # Falha total do envio (todo destinatário tentado falhou):
            # libera a reserva pra próxima varredura tentar de novo.
            release_agent_event(session, marker)
            return False

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

def run_all_igrejas(
    session: Session,
    engine: SlaEngine | None = None,
    now: dt.datetime | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> int:
    """Run the SLA engine for every igreja with an SLA-relevant open item.

    Returns the number of breaches handled across all tenants. Tenant set is
    derived from open work_queue items and open consolidacoes so we do not scan
    igrejas with nothing pending.

    Pinning (D3): uma sessão tenant-scoped NÃO pode ser re-fixada em outra
    igreja. Por isso o sweep NÃO reutiliza uma única sessão iterando tenants
    (estratégia (a) do SPEC): a DESCOBERTA do conjunto de igrejas roda na
    `session` compartilhada (papel de conexão / BYPASSRLS — deliberadamente
    cross-tenant), mas CADA igreja é processada numa NOVA sessão
    `mark_tenant_scoped`, fechada ao fim da iteração. Assim nenhuma sessão é
    remarcada (sem TenantPinConflictError) e o role/GUC nunca vaza ao pool.
    """
    engine = engine or SlaEngine()
    now = now or _now()
    if session_factory is None:
        session_factory = get_session_factory()

    # Descoberta cross-tenant: a `session` compartilhada roda no papel de conexão
    # (BYPASSRLS), então enxerga todas as igrejas com pendências. Nenhuma escrita
    # acontece aqui — só a coleta do conjunto de tenants a varrer.
    igreja_ids: set[uuid.UUID] = set()
    igreja_ids.update(
        session.execute(select(WorkQueueItem.igreja_id).distinct()).scalars().all()
    )
    igreja_ids.update(
        session.execute(
            select(Consolidacao.igreja_id)
            .where(
                Consolidacao.concluida.is_(False),
                Consolidacao.abandonada_em.is_(None),
            )
            .distinct()
        ).scalars().all()
    )

    total = 0
    for igreja_id in igreja_ids:
        # Uma NOVA sessão tenant-scoped por igreja (D3). Fresh a cada iteração:
        # mark_tenant_scoped a pina no tenant sem risco de re-fixação.
        tenant_session = session_factory()
        try:
            mark_tenant_scoped(tenant_session, igreja_id, source="cron_sla")
            total += len(engine.run_for_igreja(tenant_session, igreja_id, now))
        except Exception:  # noqa: BLE001 - one tenant must not break the others
            logger.exception("SLA engine failed for igreja %s", igreja_id)
            tenant_session.rollback()
        finally:
            # Fecha SEMPRE (inclusive na exceção): sem isso a conexão voltaria ao
            # pool no papel `authenticated` com o GUC do tenant (§5.7).
            tenant_session.close()
    return total
