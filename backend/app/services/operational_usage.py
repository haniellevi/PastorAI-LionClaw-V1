"""Read-only tenant operational aggregates. No payloads or free-text labels."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import AiUsageLog, Message, WorkQueueItem
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


class OperationalPending(BaseModel):
    measured_at: datetime
    stuck_after_seconds: int
    webhooks_available: bool = False
    outbox_available: bool = False
    sources: dict[str, PendingAge]


def operational_pending(
    db: Session, igreja_id: UUID, *, stuck_after_seconds: int = 3600,
    now: datetime | None = None,
) -> OperationalPending:
    """Age of active durable work, not proof of failure or transport backlog.

    Read only tenant-visible SQL metadata. Redis webhooks and worker-private
    outbox are deliberately unavailable, rather than reported as zero.
    """
    if not 1 <= stuck_after_seconds <= 2592000:
        raise ValueError('stuck_after_seconds must be between 1 and 2592000')
    end = now or datetime.now(UTC)
    sources = {}
    for name, model, timestamp, pending in (
        ('messages', Message, Message.criado_em,
         (Message.direcao == 'out') & (Message.autor == 'ia') &
         Message.agent_reply_state.in_((AGENT_REPLY_RESERVED, AGENT_REPLY_EXECUTING,
                                       AGENT_REPLY_PENDING, AGENT_REPLY_IN_FLIGHT))),
        ('tasks', WorkQueueItem, WorkQueueItem.created_at,
         or_(WorkQueueItem.status.is_(None), WorkQueueItem.status.in_(('aberto', 'assumido')))),
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
    return OperationalPending(measured_at=end, stuck_after_seconds=stuck_after_seconds, sources=sources)
