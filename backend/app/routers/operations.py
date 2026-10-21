"""Minimal tenant-admin operational projection, without conversation data."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import AppUser
from app.db.session import get_db
from app.deps import CurrentUser, require_role
from app.services.operational_usage import (
    OperationalPending, OperationalUsage, operational_pending, operational_usage,
)

router = APIRouter(prefix="/operations", tags=["operations"])


def require_active_admin(
    user: CurrentUser = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
) -> CurrentUser:
    active = db.scalar(select(AppUser.id).where(
        AppUser.id == UUID(user.app_user_id),
        AppUser.igreja_id == UUID(user.igreja_id),
        AppUser.clerk_user_id == user.clerk_user_id,
        or_(AppUser.status.is_(None), AppUser.status == "ativo"),
    ))
    if active is None:
        raise HTTPException(403, "Acesso restrito a administrador ativo")
    return user


@router.get("/ai-usage", response_model=OperationalUsage)
def ai_usage(
    response: Response,
    user: CurrentUser = Depends(require_active_admin),
    db: Session = Depends(get_db),
) -> OperationalUsage:
    """Seven rolling days for the authenticated admin's church only."""
    response.headers["Cache-Control"] = "no-store"
    return operational_usage(db, UUID(user.igreja_id))


@router.get("/pending", response_model=OperationalPending)
def pending(
    response: Response,
    stuck_after_seconds: int = Query(default=3600, ge=1, le=2592000),
    user: CurrentUser = Depends(require_active_admin),
    db: Session = Depends(get_db),
) -> OperationalPending:
    """Aggregate age only; the authenticated church supplies the tenant."""
    response.headers["Cache-Control"] = "no-store"
    return operational_pending(db, UUID(user.igreja_id), stuck_after_seconds=stuck_after_seconds)
