"""Shared billing configuration resolution.

The master owns the default setup fee. A church may carry one explicit override;
tenant checkout requests never provide either value.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import BillingSettings, Igreja


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
