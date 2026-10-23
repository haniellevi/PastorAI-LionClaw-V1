"""Read-only tenant operational aggregates. No payloads or free-text labels."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, literal_column, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import AiUsageLog, Message, WhatsappConnection, WorkQueueItem
from app.domain.agent_reply import (
    AGENT_REPLY_EXECUTING, AGENT_REPLY_IN_FLIGHT,
    AGENT_REPLY_PENDING, AGENT_REPLY_RESERVED,
)


class OperationalUsage(BaseModel):
    window_start: datetime
    window_end: datetime
    calls: int
    tokens_in: int
    tokens_out: int
    cost: Decimal


def operational_usage(db: Session, igreja_id: UUID) -> OperationalUsage:
    """Filter explicitly by tenant as well as the caller's existing RLS context.

    Counts ledger records, not user turns or successful provider calls. Null
    legacy token/cost values contribute zero. No new telemetry is persisted.
    """
    end = datetime.now(UTC)
    start = end - timedelta(days=7)
    row = db.execute(
        select(
            func.count(AiUsageLog.id),
            func.coalesce(func.sum(AiUsageLog.tokens_in), 0),
            func.coalesce(func.sum(AiUsageLog.tokens_out), 0),
            func.coalesce(func.sum(AiUsageLog.custo), 0),
        ).where(
            AiUsageLog.igreja_id == igreja_id,
            AiUsageLog.created_at >= start,
            AiUsageLog.created_at < end,
        )
    ).one()
    return OperationalUsage(
        window_start=start, window_end=end, calls=row[0],
        tokens_in=row[1], tokens_out=row[2], cost=row[3],
    )


class PendingAge(BaseModel):
    count: int
    oldest_age_seconds: float | None
    age_buckets: dict[str, int]
    stuck_count: int
    stuck_oldest_age_seconds: float | None


class QueueAge(BaseModel):
    count: int | None
    oldest_age_seconds: float | None
    age_complete: bool = True
    unaged_count: int | None = 0
    overdue_count: int | None = 0
    oldest_overdue_age_seconds: float | None = None


class OperationalPending(BaseModel):
    measured_at: datetime
    stuck_after_seconds: int
    webhooks_available: bool = False
    outbox_available: bool = False
    notification_outbox: dict[str, QueueAge]
    webhooks: QueueAge
    webhook_dead_letters: QueueAge
    sources: dict[str, PendingAge]


def _empty_queue_age(*, complete: bool = False) -> QueueAge:
    return QueueAge(
        count=None,
        oldest_age_seconds=None,
        age_complete=complete,
        unaged_count=None,
        overdue_count=None,
    )


def _outbox_pending_ages(
    db: Session, igreja_id: UUID, measured_at: datetime
) -> tuple[dict[str, QueueAge], bool]:
    names = {
        "pending": "pending",
        "retryable": "retryable",
        "expired_lease": "expired_lease",
    }
    sources = {name: _empty_queue_age() for name in names.values()}
    try:
        with db.begin_nested():
            rows = db.execute(
                text(
                    "SELECT queue_state, item_count, oldest_age_seconds, "
                    "overdue_count, oldest_overdue_age_seconds "
                    "FROM public.operations_notification_outbox_pending_metrics "
                    "(:igreja_id, :measured_at)"
                ),
                {"igreja_id": igreja_id, "measured_at": measured_at},
            ).all()
    except SQLAlchemyError:
        return sources, False

    metrics = {str(row[0]): row[1:] for row in rows}
    if set(metrics) != set(names):
        return sources, False
    for state, source in names.items():
        count, oldest, overdue_count, overdue_oldest = metrics[state]
        count = int(count)
        overdue_count = int(overdue_count)
        if (
            count < 0
            or overdue_count < 0
            or overdue_count > count
            or (count > 0 and oldest is None)
            or (overdue_count > 0 and overdue_oldest is None)
        ):
            return sources, False
        sources[source] = QueueAge(
            count=count,
            oldest_age_seconds=float(oldest) if oldest is not None else None,
            overdue_count=overdue_count,
            oldest_overdue_age_seconds=(
                float(overdue_oldest) if overdue_oldest is not None else None
            ),
        )
    return sources, True


def _webhook_pending_age(
    db: Session,
    igreja_id: UUID,
    measured_at: datetime,
    queue: object | None,
) -> tuple[QueueAge, QueueAge, bool]:
    if queue is None:
        return _empty_queue_age(), _empty_queue_age(), False

    items: list[Any] = []
    snapshot_complete = False
    registered: set[str] = set()
    try:
        with db.begin_nested():
            items, snapshot_complete = queue.pending_metadata()  # type: ignore[attr-defined]
            if snapshot_complete:
                instances = {
                    item.instance
                    for item in items
                    if isinstance(item.instance, str) and item.instance
                }
                if instances:
                    registered = set(
                        db.execute(
                            select(WhatsappConnection.instance).where(
                                WhatsappConnection.igreja_id == igreja_id,
                                WhatsappConnection.instance.in_(instances),
                                WhatsappConnection.instance.is_not(None),
                            )
                        ).scalars()
                    )
    except Exception:
        items = []
        snapshot_complete = False
        registered = set()
    if not snapshot_complete:
        return _empty_queue_age(), _empty_queue_age(), False

    dead_letters: list[Any] = []
    dead_letters_complete = False
    registered_dead_letters: set[str] = set()
    try:
        with db.begin_nested():
            dead_letters, dead_letters_complete = queue.dead_letter_metadata()  # type: ignore[attr-defined]
            if dead_letters_complete:
                instances = {
                    item.instance
                    for item in dead_letters
                    if isinstance(item.instance, str) and item.instance
                }
                if instances:
                    registered_dead_letters = set(
                        db.execute(
                            select(WhatsappConnection.instance).where(
                                WhatsappConnection.igreja_id == igreja_id,
                                WhatsappConnection.instance.in_(instances),
                                WhatsappConnection.instance.is_not(None),
                            )
                        ).scalars()
                    )
    except Exception:
        dead_letters = []
        dead_letters_complete = False
        registered_dead_letters = set()

    def queue_age(
        queue_items: list[Any], *, overdue: bool, complete: bool
    ) -> QueueAge:
        if not complete:
            return _empty_queue_age()
        unaged_count = sum(item.received_at is None for item in queue_items)
        ages = [
            max(0.0, measured_at.timestamp() - float(item.received_at))
            for item in queue_items
            if item.received_at is not None
        ]
        age_complete = unaged_count == 0
        return QueueAge(
            count=len(queue_items),
            oldest_age_seconds=max(ages) if ages and age_complete else None,
            age_complete=age_complete,
            unaged_count=unaged_count,
            overdue_count=len(queue_items) if overdue else 0,
            oldest_overdue_age_seconds=(
                max(ages) if overdue and ages and age_complete else None
            ),
        )

    tenant_items = [item for item in items if item.instance in registered]
    tenant_dead_letters = [
        item for item in dead_letters if item.instance in registered_dead_letters
    ]
    return (
        queue_age(tenant_items, overdue=True, complete=snapshot_complete),
        queue_age(
            tenant_dead_letters,
            overdue=False,
            complete=dead_letters_complete,
        ),
        bool(snapshot_complete),
    )


def operational_pending(
    db: Session, igreja_id: UUID, *, stuck_after_seconds: int = 3600,
    now: datetime | None = None, webhook_queue: object | None = None,
) -> OperationalPending:
    """Age of active durable work, not proof of failure or transport backlog.

    Read only tenant-scoped aggregates. Webhook payloads never leave Redis;
    only the registered instance mapping and receipt timestamp are inspected.
    """
    if not 1 <= stuck_after_seconds <= 2592000:
        raise ValueError('stuck_after_seconds must be between 1 and 2592000')
    end = now or datetime.now(UTC)
    sources = {}
    for name, model, timestamp, pending in (
        ('messages', Message, Message.criado_em,
         (Message.direcao == literal_column("'out'")) &
         (Message.autor == literal_column("'ia'")) &
         Message.agent_reply_state.in_(tuple(literal_column(f"'{state}'") for state in (
             AGENT_REPLY_RESERVED, AGENT_REPLY_EXECUTING,
             AGENT_REPLY_PENDING, AGENT_REPLY_IN_FLIGHT,
         )))),
        ('tasks', WorkQueueItem, WorkQueueItem.created_at,
         or_(WorkQueueItem.status.is_(None), WorkQueueItem.status.in_(
             (literal_column("'aberto'"), literal_column("'assumido'"))
         ))),
    ):
        age = func.greatest(0, func.extract('epoch', end - timestamp))
        stuck = age > stuck_after_seconds
        row = db.execute(select(
            func.count(), func.max(age),
            func.count().filter(age < 300),
            func.count().filter((age >= 300) & (age < 3600)),
            func.count().filter((age >= 3600) & (age < 86400)),
            func.count().filter(age >= 86400),
            func.count().filter(stuck), func.max(age).filter(stuck),
        ).select_from(model).where(model.igreja_id == igreja_id, pending)).one()
        sources[name] = PendingAge(
            count=row[0], oldest_age_seconds=row[1],
            age_buckets=dict(zip(('under_5m', '5m_to_1h', '1h_to_24h', '24h_plus'), row[2:6], strict=True)),
            stuck_count=row[6], stuck_oldest_age_seconds=row[7],
        )
    outbox_sources, outbox_available = _outbox_pending_ages(db, igreja_id, end)
    webhooks, webhook_dead_letters, webhooks_available = _webhook_pending_age(
        db, igreja_id, end, webhook_queue
    )
    return OperationalPending(
        measured_at=end,
        stuck_after_seconds=stuck_after_seconds,
        outbox_available=outbox_available,
        webhooks_available=webhooks_available,
        notification_outbox=outbox_sources,
        webhooks=webhooks,
        webhook_dead_letters=webhook_dead_letters,
        sources=sources,
    )
