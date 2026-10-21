"""Read-only, seven-day AI ledger totals. No payloads or free-text labels."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AiUsageLog


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
