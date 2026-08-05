"""Persistent scheduling and delivery for WhatsApp broadcasts.

The worker deliberately provides no exactly-once or at-least-once guarantee.
It retries only failures proven to happen before a send, while ambiguous
results are quarantined as ``desconhecido`` and never retried automatically.

Every cross-tenant pass is discovery-only. Mutations always happen in a fresh
tenant-scoped session, and every external HTTP call runs after the claiming
session has committed and closed.
"""

from __future__ import annotations

import calendar
import datetime as dt
import logging
import re
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    Broadcast,
    BroadcastEntrega,
    BroadcastExecucao,
    Celula,
    Pessoa,
    WhatsappConnection,
)
from app.db.tenant_session import mark_cross_tenant, mark_tenant_scoped
from app.domain.broadcast import RecipientCandidate, matches_segments, normalize_segments
from app.services.evolution import BroadcastSendResult, EvolutionClient

logger = logging.getLogger("pastorai.broadcast_delivery")

SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
UTC = dt.timezone.utc
_TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

DEFAULT_MAX_BROADCASTS_PER_CYCLE = 20
DEFAULT_MAX_DELIVERIES_PER_CYCLE = 200
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_DELIVERY_LEASE_SECONDS = 120
DEFAULT_BROADCAST_CLAIM_SECONDS = 60
DEFAULT_SEND_INTERVAL_MS = 1000
DEFAULT_RETRY_BASE_SECONDS = 30
MAX_RETRY_DELAY_SECONDS = 1800
MAX_PROVIDER_RETRY_AFTER_SECONDS = 86400

DELIVERY_STATUSES = frozenset(
    {
        "pendente",
        "em_envio",
        "aceito",
        "falhou_retentavel",
        "falhou_permanente",
        "desconhecido",
        "suprimido",
    }
)
DELIVERY_WORK_STATUSES = frozenset(
    {"pendente", "em_envio", "falhou_retentavel"}
)

SessionFactory = Callable[[], Session]


@dataclass(frozen=True)
class ResolvedRecipient:
    pessoa_id: uuid.UUID
    telefone: str


@dataclass(frozen=True)
class ResolvedAudience:
    recipients: list[ResolvedRecipient]
    ignored_optout: int

    @property
    def reach(self) -> int:
        return len(self.recipients)


@dataclass(frozen=True)
class DeliveryClaim:
    igreja_id: uuid.UUID
    entrega_id: uuid.UUID
    execucao_id: uuid.UUID
    instance: str
    telefone: str
    mensagem: str


@dataclass(frozen=True)
class ClaimDecision:
    claim: DeliveryClaim | None = None
    progressed: bool = False
    blocked_no_instance: bool = False


@dataclass(frozen=True)
class BroadcastCycleStats:
    reaped: int = 0
    materialized: int = 0
    delivery_actions: int = 0


def utc_now() -> dt.datetime:
    return dt.datetime.now(UTC)


def retry_delay_seconds(
    retry_number: int, provider_retry_after: int | None = None
) -> int:
    """Exponential retry delay, honoring a larger provider Retry-After."""
    exponent = max(0, retry_number - 1)
    local_delay = min(
        MAX_RETRY_DELAY_SECONDS,
        DEFAULT_RETRY_BASE_SECONDS * (2**exponent),
    )
    provider_delay = min(
        MAX_PROVIDER_RETRY_AFTER_SECONDS,
        max(0, int(provider_retry_after or 0)),
    )
    return max(local_delay, provider_delay)


def execution_result_status(status_counts: Mapping[str, int]) -> str:
    """Return one truthful terminal label derived from the delivery ledger."""
    accepted = int(status_counts.get("aceito", 0))
    unknown = int(status_counts.get("desconhecido", 0))
    suppressed = int(status_counts.get("suprimido", 0))
    failed = int(status_counts.get("falhou_permanente", 0))
    total = accepted + unknown + suppressed + failed
    if total == 0:
        return "concluido_sem_destinatarios"
    if accepted and (unknown or suppressed or failed):
        return "parcial"
    if accepted:
        return "enviado"
    if unknown:
        return "desconhecido"
    if failed:
        return "falhou"
    return "suprimido"


def _as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def scheduled_instant(data: dt.date, hora: str | None) -> dt.datetime:
    """Convert one nominal Sao Paulo schedule slot to an aware UTC instant."""
    normalized = (hora or "00:00").strip()
    if not _TIME_RE.fullmatch(normalized):
        raise ValueError("hora deve estar no formato HH:MM (00:00 a 23:59)")
    hours, minutes = (int(part) for part in normalized.split(":", 1))
    local = dt.datetime(
        data.year,
        data.month,
        data.day,
        hours,
        minutes,
        tzinfo=SAO_PAULO_TZ,
    )
    return local.astimezone(UTC)


def nominal_slot(instant: dt.datetime) -> tuple[dt.date, str]:
    """Return the stable local date/time represented by an execution instant."""
    local = _as_utc(instant).astimezone(SAO_PAULO_TZ)
    return local.date(), local.strftime("%H:%M")


def _add_month(
    local: dt.datetime, *, months: int = 1, anchor_day: int | None = None
) -> dt.datetime:
    month_index = local.year * 12 + (local.month - 1) + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    wanted_day = anchor_day or local.day
    day = min(wanted_day, calendar.monthrange(year, month)[1])
    return local.replace(year=year, month=month, day=day)


def next_occurrence(
    current: dt.datetime,
    repetition: str | None,
    *,
    now: dt.datetime | None = None,
    anchor_day: int | None = None,
) -> dt.datetime | None:
    """Return the next future slot using skip-forward (never catch-up).

    Monthly recurrence preserves the original day where possible: Jan 31 goes
    to Feb 28/29 and then Mar 31, using :func:`calendar.monthrange` only.
    """
    normalized = (repetition or "once").strip().lower()
    if normalized == "once":
        return None

    current_local = _as_utc(current).astimezone(SAO_PAULO_TZ)
    now_local = _as_utc(now or utc_now()).astimezone(SAO_PAULO_TZ)

    days_by_repetition = {"daily": 1, "weekly": 7, "biweekly": 14}
    if normalized in days_by_repetition:
        step_days = days_by_repetition[normalized]
        candidate = current_local + dt.timedelta(days=step_days)
        if candidate <= now_local:
            overdue_days = (now_local - candidate).days
            jumps = overdue_days // step_days + 1
            candidate += dt.timedelta(days=jumps * step_days)
        return candidate.astimezone(UTC)

    if normalized == "monthly":
        monthly_anchor = anchor_day or current_local.day
        candidate = _add_month(current_local, anchor_day=monthly_anchor)
        while candidate <= now_local:
            candidate = _add_month(candidate, anchor_day=monthly_anchor)
        return candidate.astimezone(UTC)

    raise ValueError(f"repetição inválida: {repetition}")


def normalize_delivery_phone(raw: str | None) -> str | None:
    """Return a digits-only send/dedupe key, or None when clearly invalid."""
    digits = "".join(char for char in (raw or "") if char.isdigit())
    return digits if 10 <= len(digits) <= 15 else None


def recipient_delivery_phone(person: Any | None) -> tuple[str | None, str | None]:
    """Revalidate a person immediately before an external attempt.

    Returns ``(phone, None)`` when eligible, otherwise ``(None, reason)``.
    Reasons are technical and contain no PII.
    """
    if person is None:
        return None, "pessoa_ausente"
    if getattr(person, "arquivada_em", None) is not None:
        return None, "pessoa_arquivada"
    if not bool(getattr(person, "consentimento", False)):
        return None, "sem_consentimento"
    if bool(getattr(person, "optout", False)):
        return None, "optout"
    phone = normalize_delivery_phone(getattr(person, "telefone", None))
    if phone is None:
        return None, "telefone_invalido"
    return phone, None


def recipient_phone_for_delivery(
    person: Any | None, *, snapshot_phone: str
) -> tuple[str | None, str | None]:
    """Revalidate eligibility without silently changing the dedupe target.

    A phone changed after materialization could collide with another delivery
    in the same occurrence and cause a duplicate send. Suppress this occurrence
    instead; a future occurrence will materialize the current audience afresh.
    """
    phone, reason = recipient_delivery_phone(person)
    if phone is None:
        return None, reason
    if phone != snapshot_phone:
        return None, "telefone_alterado"
    return phone, None


def resolve_recipient_snapshot(
    people: list[Any], leader_ids: set[uuid.UUID], segmentos: list[str]
) -> ResolvedAudience:
    """Resolve one immutable recipient snapshot from already-read people."""
    normalized_segments = normalize_segments(segmentos)
    recipients: list[ResolvedRecipient] = []
    seen_phones: set[str] = set()
    ignored_optout = 0
    for person in people:
        candidate = RecipientCandidate(
            telefone=person.telefone,
            tipo=person.tipo,
            optout=person.optout,
            consentimento=person.consentimento,
            lidera_celula=person.id in leader_ids,
        )
        if not matches_segments(candidate, normalized_segments):
            continue
        phone, reason = recipient_delivery_phone(person)
        if reason in {"optout", "sem_consentimento"}:
            ignored_optout += 1
        if phone is None or phone in seen_phones:
            continue
        seen_phones.add(phone)
        recipients.append(ResolvedRecipient(person.id, phone))
    return ResolvedAudience(recipients, ignored_optout)


def _resolve_recipients(
    session: Session, igreja_id: uuid.UUID, segmentos: list[str]
) -> list[ResolvedRecipient]:
    """Resolve the live audience while a scheduled occurrence is materialized."""
    people = session.execute(
        select(Pessoa).where(
            Pessoa.igreja_id == igreja_id,
            Pessoa.arquivada_em.is_(None),
        )
    ).scalars().all()
    leader_ids = {
        row
        for row in session.execute(
            select(Celula.lider_id).where(
                Celula.igreja_id == igreja_id,
                Celula.ativo.is_(True),
                Celula.lider_id.is_not(None),
            )
        ).scalars().all()
    }
    return resolve_recipient_snapshot(people, leader_ids, segmentos).recipients


def materialize_immediate_broadcast(
    session: Session,
    broadcast: Broadcast,
    recipients: list[ResolvedRecipient],
    *,
    now: dt.datetime,
) -> uuid.UUID:
    """Persist the reviewed send-now audience before returning to the caller.

    Scheduled occurrences intentionally resolve their audience when due. A
    send-now request is different: recipients must be exactly those reviewed
    in the request, so the worker only dispatches this durable snapshot.
    """
    if broadcast.id is None:
        raise ValueError("broadcast must be flushed before materialization")

    slot_date, slot_time = nominal_slot(now)
    execution = BroadcastExecucao(
        igreja_id=broadcast.igreja_id,
        broadcast_id=broadcast.id,
        seq=1,
        data_nominal=slot_date,
        hora_nominal=slot_time,
    )
    session.add(execution)
    session.flush()
    session.add_all(
        [
            BroadcastEntrega(
                igreja_id=broadcast.igreja_id,
                execucao_id=execution.id,
                pessoa_id=recipient.pessoa_id,
                telefone=recipient.telefone,
                status="pendente",
            )
            for recipient in recipients
        ]
    )
    # Prevent the due-broadcast sweep from resolving this audience again.
    broadcast.proxima_execucao = None
    broadcast.claim_ate = None
    broadcast.claim_por = None
    # The router refreshes ``broadcast`` before committing. Persist the reset
    # first so refresh cannot restore the original due slot from the database.
    session.flush()
    return execution.id


def _discover_due_broadcasts(
    session_factory: SessionFactory,
    *,
    now: dt.datetime,
    limit: int,
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    discovery = session_factory()
    try:
        mark_cross_tenant(discovery, source="broadcast_due_discovery")
        return list(
            discovery.execute(
                select(Broadcast.igreja_id, Broadcast.id)
                .where(
                    Broadcast.status == "agendado",
                    Broadcast.proxima_execucao.is_not(None),
                    Broadcast.proxima_execucao <= now,
                )
                .order_by(Broadcast.proxima_execucao, Broadcast.id)
                .limit(limit)
            ).all()
        )
    finally:
        discovery.close()


def _materialize_one(
    session: Session,
    igreja_id: uuid.UUID,
    broadcast_id: uuid.UUID,
    *,
    now: dt.datetime,
    worker_id: str,
    claim_seconds: int,
) -> uuid.UUID | None:
    claim_until = now + dt.timedelta(seconds=claim_seconds)
    claimed = session.execute(
        update(Broadcast)
        .where(
            Broadcast.id == broadcast_id,
            Broadcast.igreja_id == igreja_id,
            Broadcast.status == "agendado",
            Broadcast.proxima_execucao.is_not(None),
            Broadcast.proxima_execucao <= now,
            or_(Broadcast.claim_ate.is_(None), Broadcast.claim_ate < now),
        )
        .values(claim_ate=claim_until, claim_por=worker_id)
    )
    if claimed.rowcount != 1:
        session.rollback()
        return None

    broadcast = session.execute(
        select(Broadcast).where(
            Broadcast.id == broadcast_id,
            Broadcast.igreja_id == igreja_id,
        )
    ).scalar_one()
    due_at = broadcast.proxima_execucao
    if due_at is None:  # defensive: the conditional claim already excludes it
        session.rollback()
        return None

    next_seq = session.execute(
        select(func.coalesce(func.max(BroadcastExecucao.seq), 0) + 1).where(
            BroadcastExecucao.broadcast_id == broadcast_id
        )
    ).scalar_one()
    slot_date, slot_time = nominal_slot(due_at)
    execution = BroadcastExecucao(
        igreja_id=igreja_id,
        broadcast_id=broadcast_id,
        seq=next_seq,
        data_nominal=slot_date,
        hora_nominal=slot_time,
    )
    session.add(execution)
    session.flush()

    recipients = _resolve_recipients(session, igreja_id, list(broadcast.segmentos or []))
    session.add_all(
        [
            BroadcastEntrega(
                igreja_id=igreja_id,
                execucao_id=execution.id,
                pessoa_id=recipient.pessoa_id,
                telefone=recipient.telefone,
                status="pendente",
            )
            for recipient in recipients
        ]
    )

    following = next_occurrence(
        due_at,
        broadcast.repeticao,
        now=now,
        anchor_day=broadcast.data.day if broadcast.data else slot_date.day,
    )
    broadcast.proxima_execucao = following
    broadcast.claim_ate = None
    broadcast.claim_por = None
    # Empty occurrences are first-class history rows and complete immediately.
    if not recipients:
        execution.iniciada_em = now
        execution.finalizada_em = now
        if following is None:
            # ``broadcast_status`` describes lifecycle only. The truthful
            # delivery result is derived from this execution's ledger.
            broadcast.status = "enviado"

    execution_id = execution.id
    session.commit()
    return execution_id


def materialize_due_broadcasts(
    session_factory: SessionFactory,
    *,
    now: dt.datetime | None = None,
    worker_id: str,
    limit: int = DEFAULT_MAX_BROADCASTS_PER_CYCLE,
    claim_seconds: int = DEFAULT_BROADCAST_CLAIM_SECONDS,
) -> int:
    """Materialize due occurrences, using a fresh scoped session per tenant."""
    current = _as_utc(now or utc_now())
    due = _discover_due_broadcasts(
        session_factory, now=current, limit=max(1, limit)
    )
    grouped: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for igreja_id, broadcast_id in due:
        grouped[igreja_id].append(broadcast_id)

    materialized = 0
    for igreja_id, broadcast_ids in grouped.items():
        tenant_session = session_factory()
        try:
            mark_tenant_scoped(
                tenant_session, igreja_id, source="broadcast_materialize"
            )
            for broadcast_id in broadcast_ids:
                if _materialize_one(
                    tenant_session,
                    igreja_id,
                    broadcast_id,
                    now=current,
                    worker_id=worker_id,
                    claim_seconds=claim_seconds,
                ):
                    materialized += 1
        except Exception:  # noqa: BLE001 - one tenant must not stop the sweep
            logger.exception("Broadcast materialization failed igreja_id=%s", igreja_id)
            tenant_session.rollback()
        finally:
            tenant_session.close()
    return materialized


def _finalize_execution_if_done(
    session: Session, execucao_id: uuid.UUID, *, now: dt.datetime
) -> bool:
    remaining = session.execute(
        select(func.count())
        .select_from(BroadcastEntrega)
        .where(
            BroadcastEntrega.execucao_id == execucao_id,
            BroadcastEntrega.status.in_(DELIVERY_WORK_STATUSES),
        )
    ).scalar_one()
    if remaining:
        return False
    broadcast_id = session.execute(
        select(BroadcastExecucao.broadcast_id).where(
            BroadcastExecucao.id == execucao_id
        )
    ).scalar_one()
    session.execute(
        update(BroadcastExecucao)
        .where(
            BroadcastExecucao.id == execucao_id,
            BroadcastExecucao.finalizada_em.is_(None),
        )
        .values(
            finalizada_em=now,
            lease_ate=None,
            claim_por=None,
        )
    )
    # A ocorrência única só vira "enviado" depois de todas as entregas saírem
    # dos estados de trabalho. Recorrências mantêm proxima_execucao preenchida
    # e continuam "agendado" para o próximo slot.
    session.execute(
        update(Broadcast)
        .where(
            Broadcast.id == broadcast_id,
            Broadcast.status == "agendado",
            Broadcast.proxima_execucao.is_(None),
        )
        # Keep the enum as a lifecycle state. API/UI derive the truthful
        # terminal outcome from ``broadcast_entregas``.
        .values(status="enviado")
    )
    return True


def _finalize_ready_executions(
    session: Session, igreja_id: uuid.UUID, *, now: dt.datetime
) -> None:
    execution_ids = session.execute(
        select(BroadcastExecucao.id).where(
            BroadcastExecucao.igreja_id == igreja_id,
            BroadcastExecucao.finalizada_em.is_(None),
        )
    ).scalars().all()
    for execution_id in execution_ids:
        _finalize_execution_if_done(session, execution_id, now=now)


def _expire_retry_budget(
    session: Session,
    igreja_id: uuid.UUID,
    *,
    now: dt.datetime,
    max_attempts: int,
) -> None:
    session.execute(
        update(BroadcastEntrega)
        .where(
            BroadcastEntrega.igreja_id == igreja_id,
            BroadcastEntrega.status == "falhou_retentavel",
            BroadcastEntrega.retry_budget_used >= max_attempts,
        )
        .values(
            status="falhou_permanente",
            lease_ate=None,
            next_attempt_at=None,
            claim_por=None,
            atualizado_em=now,
        )
    )


def _discover_orphan_tenants(
    session_factory: SessionFactory, *, now: dt.datetime
) -> list[uuid.UUID]:
    """Discover expired in-flight rows independently of due broadcasts."""
    discovery = session_factory()
    try:
        mark_cross_tenant(discovery, source="broadcast_reaper_discovery")
        return list(
            discovery.execute(
                select(BroadcastEntrega.igreja_id)
                .where(
                    BroadcastEntrega.status == "em_envio",
                    BroadcastEntrega.lease_ate.is_not(None),
                    BroadcastEntrega.lease_ate < now,
                )
                .distinct()
            ).scalars().all()
        )
    finally:
        discovery.close()


def _reap_tenant_deliveries(
    session: Session,
    igreja_id: uuid.UUID,
    *,
    now: dt.datetime,
    max_attempts: int,
) -> int:
    execution_ids = session.execute(
        select(BroadcastEntrega.execucao_id)
        .where(
            BroadcastEntrega.igreja_id == igreja_id,
            BroadcastEntrega.status == "em_envio",
            BroadcastEntrega.lease_ate.is_not(None),
            BroadcastEntrega.lease_ate < now,
        )
        .distinct()
    ).scalars().all()
    result = session.execute(
        update(BroadcastEntrega)
        .where(
            BroadcastEntrega.igreja_id == igreja_id,
            BroadcastEntrega.status == "em_envio",
            BroadcastEntrega.lease_ate.is_not(None),
            BroadcastEntrega.lease_ate < now,
        )
        .values(
            status="desconhecido",
            ultimo_erro_classe="lease_expirado",
            lease_ate=None,
            next_attempt_at=None,
            claim_por=None,
            atualizado_em=now,
        )
    )
    _expire_retry_budget(
        session, igreja_id, now=now, max_attempts=max_attempts
    )
    for execution_id in execution_ids:
        _finalize_execution_if_done(session, execution_id, now=now)
    session.commit()
    return int(result.rowcount or 0)


def reap_orphaned_deliveries(
    session_factory: SessionFactory,
    *,
    now: dt.datetime | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> int:
    """Quarantine expired ``em_envio`` rows without ever resending them."""
    current = _as_utc(now or utc_now())
    church_ids = _discover_orphan_tenants(session_factory, now=current)
    reaped = 0
    for igreja_id in church_ids:
        tenant_session = session_factory()
        try:
            mark_tenant_scoped(tenant_session, igreja_id, source="broadcast_reaper")
            reaped += _reap_tenant_deliveries(
                tenant_session,
                igreja_id,
                now=current,
                max_attempts=max_attempts,
            )
        except Exception:  # noqa: BLE001 - one tenant must not stop the reaper
            logger.exception("Broadcast reaper failed igreja_id=%s", igreja_id)
            tenant_session.rollback()
        finally:
            tenant_session.close()
    return reaped


def _discover_delivery_tenants(session_factory: SessionFactory) -> list[uuid.UUID]:
    discovery = session_factory()
    try:
        mark_cross_tenant(discovery, source="broadcast_delivery_discovery")
        return list(
            discovery.execute(
                select(BroadcastEntrega.igreja_id)
                .join(
                    BroadcastExecucao,
                    BroadcastExecucao.id == BroadcastEntrega.execucao_id,
                )
                .where(
                    BroadcastExecucao.finalizada_em.is_(None),
                    BroadcastEntrega.status.in_(
                        {"pendente", "falhou_retentavel"}
                    ),
                )
                .distinct()
            ).scalars().all()
        )
    finally:
        discovery.close()


def _claim_next_delivery(
    session_factory: SessionFactory,
    igreja_id: uuid.UUID,
    *,
    now: dt.datetime,
    worker_id: str,
    lease_seconds: int,
    max_attempts: int,
) -> ClaimDecision:
    """Claim one revalidated target and close the DB session before returning."""
    session = session_factory()
    try:
        mark_tenant_scoped(session, igreja_id, source="broadcast_delivery_claim")
        _expire_retry_budget(
            session, igreja_id, now=now, max_attempts=max_attempts
        )

        row = session.execute(
            select(BroadcastEntrega, BroadcastExecucao, Broadcast)
            .join(
                BroadcastExecucao,
                BroadcastExecucao.id == BroadcastEntrega.execucao_id,
            )
            .join(Broadcast, Broadcast.id == BroadcastExecucao.broadcast_id)
            .where(
                BroadcastEntrega.igreja_id == igreja_id,
                BroadcastExecucao.igreja_id == igreja_id,
                BroadcastExecucao.finalizada_em.is_(None),
                or_(
                    BroadcastEntrega.status == "pendente",
                    and_(
                        BroadcastEntrega.status == "falhou_retentavel",
                        BroadcastEntrega.retry_budget_used < max_attempts,
                        or_(
                            BroadcastEntrega.next_attempt_at.is_(None),
                            BroadcastEntrega.next_attempt_at <= now,
                        ),
                    ),
                ),
            )
            .order_by(BroadcastEntrega.criado_em, BroadcastEntrega.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if row is None:
            _finalize_ready_executions(session, igreja_id, now=now)
            session.commit()
            return ClaimDecision()

        delivery: BroadcastEntrega = row[0]
        execution: BroadcastExecucao = row[1]
        broadcast: Broadcast = row[2]

        person = None
        if delivery.pessoa_id is not None:
            person = session.execute(
                select(Pessoa).where(
                    Pessoa.id == delivery.pessoa_id,
                    Pessoa.igreja_id == igreja_id,
                )
            ).scalar_one_or_none()
        phone, suppression_reason = recipient_phone_for_delivery(
            person, snapshot_phone=delivery.telefone
        )
        if phone is None:
            delivery.status = "suprimido"
            delivery.ultimo_erro_classe = suppression_reason
            delivery.lease_ate = None
            delivery.next_attempt_at = None
            delivery.claim_por = None
            delivery.atualizado_em = now
            session.flush()
            _finalize_execution_if_done(session, execution.id, now=now)
            session.commit()
            return ClaimDecision(progressed=True)

        connection = session.execute(
            select(WhatsappConnection).where(
                WhatsappConnection.igreja_id == igreja_id,
                WhatsappConnection.instance.is_not(None),
                WhatsappConnection.status == "online",
            )
        ).scalar_one_or_none()
        if connection is None or not connection.instance:
            # A missing/offline official instance is safely before send. Keep
            # the delivery pending so a later tick can retry after reconnection.
            session.commit()
            return ClaimDecision(blocked_no_instance=True)

        lease_until = now + dt.timedelta(seconds=lease_seconds)
        delivery.status = "em_envio"
        delivery.tentativas += 1
        delivery.lease_ate = lease_until
        delivery.next_attempt_at = None
        delivery.claim_por = worker_id
        delivery.ultimo_erro_classe = None
        delivery.atualizado_em = now
        execution.iniciada_em = execution.iniciada_em or now
        execution.lease_ate = lease_until
        execution.claim_por = worker_id

        claim = DeliveryClaim(
            igreja_id=igreja_id,
            entrega_id=delivery.id,
            execucao_id=execution.id,
            instance=connection.instance,
            telefone=phone,
            mensagem=broadcast.mensagem,
        )
        session.commit()
        return ClaimDecision(claim=claim, progressed=True)
    finally:
        # The caller performs HTTP only after this close. No pool connection or
        # transaction can be retained across the network boundary.
        session.close()


def _record_delivery_result(
    session_factory: SessionFactory,
    claim: DeliveryClaim,
    result: BroadcastSendResult,
    *,
    now: dt.datetime,
    worker_id: str,
    max_attempts: int,
) -> bool:
    session = session_factory()
    try:
        mark_tenant_scoped(
            session, claim.igreja_id, source="broadcast_delivery_result"
        )
        delivery = session.execute(
            select(BroadcastEntrega)
            .where(
                BroadcastEntrega.id == claim.entrega_id,
                BroadcastEntrega.igreja_id == claim.igreja_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if (
            delivery is None
            or delivery.status != "em_envio"
            or delivery.claim_por != worker_id
        ):
            # The reaper may already have quarantined an expired claim. Never
            # overwrite ``desconhecido`` with a late HTTP result.
            session.rollback()
            return False

        final_status = (
            result.status if result.status in DELIVERY_STATUSES else "desconhecido"
        )
        error_class = result.error_class
        if result.status not in DELIVERY_STATUSES:
            error_class = "resultado_invalido"
        next_attempt_at: dt.datetime | None = None
        if final_status == "falhou_retentavel":
            if result.consume_retry_budget:
                delivery.retry_budget_used += 1
            if delivery.retry_budget_used >= max_attempts:
                final_status = "falhou_permanente"
            else:
                delay = retry_delay_seconds(
                    delivery.tentativas,
                    result.retry_after_seconds,
                )
                next_attempt_at = now + dt.timedelta(seconds=delay)

        delivery.status = final_status
        delivery.ultimo_erro_classe = error_class
        delivery.lease_ate = None
        delivery.next_attempt_at = next_attempt_at
        delivery.claim_por = None
        delivery.atualizado_em = now
        execution_id = delivery.execucao_id
        session.flush()
        _finalize_execution_if_done(session, execution_id, now=now)
        session.commit()
        return True
    finally:
        session.close()


def dispatch_pending_deliveries(
    session_factory: SessionFactory,
    evolution: EvolutionClient,
    *,
    now: dt.datetime | None = None,
    worker_id: str,
    limit: int = DEFAULT_MAX_DELIVERIES_PER_CYCLE,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    lease_seconds: int = DEFAULT_DELIVERY_LEASE_SECONDS,
    send_interval_ms: int = DEFAULT_SEND_INTERVAL_MS,
    should_continue: Callable[[], bool] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    """Dispatch a bounded, round-robin batch across discovered tenants."""
    fixed_now = _as_utc(now) if now is not None else None
    can_continue = should_continue or (lambda: True)
    church_ids = _discover_delivery_tenants(session_factory)
    blocked: set[uuid.UUID] = set()
    actions = 0

    while actions < max(1, limit) and can_continue():
        progressed_this_round = False
        for igreja_id in church_ids:
            if igreja_id in blocked or actions >= limit or not can_continue():
                continue
            try:
                attempt_now = fixed_now or utc_now()
                decision = _claim_next_delivery(
                    session_factory,
                    igreja_id,
                    now=attempt_now,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                    max_attempts=max_attempts,
                )
            except Exception:  # noqa: BLE001 - isolate one tenant
                logger.exception("Broadcast delivery claim failed igreja_id=%s", igreja_id)
                blocked.add(igreja_id)
                continue

            if decision.blocked_no_instance:
                blocked.add(igreja_id)
                continue
            if not decision.progressed:
                blocked.add(igreja_id)
                continue

            progressed_this_round = True
            actions += 1
            if decision.claim is None:
                continue  # a recipient was suppressed during revalidation

            claim = decision.claim
            try:
                outcome = evolution.send_text_classificado(
                    claim.instance, claim.telefone, claim.mensagem
                )
            except Exception:  # noqa: BLE001 - unknown means no automatic retry
                logger.exception(
                    "Unexpected broadcast transport failure execucao_id=%s",
                    claim.execucao_id,
                )
                outcome = BroadcastSendResult(
                    status="desconhecido", error_class="erro_nao_classificado"
                )

            _record_delivery_result(
                session_factory,
                claim,
                outcome,
                now=fixed_now or utc_now(),
                worker_id=worker_id,
                max_attempts=max_attempts,
            )
            if send_interval_ms > 0:
                remaining_seconds = send_interval_ms / 1000
                while remaining_seconds > 0 and can_continue():
                    step_seconds = min(1.0, remaining_seconds)
                    sleeper(step_seconds)
                    remaining_seconds -= step_seconds

        if not progressed_this_round:
            break
    return actions


def run_delivery_cycle(
    session_factory: SessionFactory,
    evolution: EvolutionClient,
    *,
    worker_id: str,
    now: dt.datetime | None = None,
    max_broadcasts: int = DEFAULT_MAX_BROADCASTS_PER_CYCLE,
    max_deliveries: int = DEFAULT_MAX_DELIVERIES_PER_CYCLE,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    claim_seconds: int = DEFAULT_BROADCAST_CLAIM_SECONDS,
    lease_seconds: int = DEFAULT_DELIVERY_LEASE_SECONDS,
    send_interval_ms: int = DEFAULT_SEND_INTERVAL_MS,
    should_continue: Callable[[], bool] | None = None,
) -> BroadcastCycleStats:
    """Run reaper, materialization, and bounded delivery in that order."""
    current = _as_utc(now or utc_now())
    reaped = reap_orphaned_deliveries(
        session_factory, now=current, max_attempts=max_attempts
    )
    materialized = materialize_due_broadcasts(
        session_factory,
        now=current,
        worker_id=worker_id,
        limit=max_broadcasts,
        claim_seconds=claim_seconds,
    )
    delivery_actions = dispatch_pending_deliveries(
        session_factory,
        evolution,
        now=now,
        worker_id=worker_id,
        limit=max_deliveries,
        max_attempts=max_attempts,
        lease_seconds=lease_seconds,
        send_interval_ms=send_interval_ms,
        should_continue=should_continue,
    )
    return BroadcastCycleStats(
        reaped=reaped,
        materialized=materialized,
        delivery_actions=delivery_actions,
    )
