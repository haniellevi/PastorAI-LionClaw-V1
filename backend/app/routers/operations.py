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
from app.services.private_memory_overview import PrivateMemoryOverview, memory_overview

router = APIRouter(prefix="/operations", tags=["operations"])


def _require_admin_status(
    user: CurrentUser,
    db: Session,
    *,
    require_explicit_active_status: bool,
) -> CurrentUser:
    status_predicate = (
        AppUser.status == "ativo"
        if require_explicit_active_status
        else or_(AppUser.status.is_(None), AppUser.status == "ativo")
    )
    active = db.scalar(select(AppUser.id).where(
        AppUser.id == UUID(user.app_user_id),
        AppUser.igreja_id == UUID(user.igreja_id),
        AppUser.clerk_user_id == user.clerk_user_id,
        status_predicate,
    ))
    if active is None:
        detail = (
            "Acesso restrito a administrador ativo"
            if require_explicit_active_status
            else "Acesso restrito a administrador"
        )
        raise HTTPException(403, detail)
    return user


def require_operational_admin(
    user: CurrentUser = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Preserve the project's NULL-or-active status convention for operations."""
    return _require_admin_status(user, db, require_explicit_active_status=False)


def require_active_admin(
    user: CurrentUser = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Require an explicit active status for private-memory access."""
    return _require_admin_status(user, db, require_explicit_active_status=True)


@router.get("/ai-usage", response_model=OperationalUsage)
def ai_usage(
    response: Response,
    user: CurrentUser = Depends(require_operational_admin),
    db: Session = Depends(get_db),
) -> OperationalUsage:
    """Seven rolling days for the authenticated admin's church only."""
    response.headers["Cache-Control"] = "no-store"
    return operational_usage(db, UUID(user.igreja_id))


@router.get("/pending", response_model=OperationalPending)
def pending(
    response: Response,
    stuck_after_seconds: int = Query(default=3600, ge=1, le=2592000),
    user: CurrentUser = Depends(require_operational_admin),
    db: Session = Depends(get_db),
) -> OperationalPending:
    """Aggregate age only; the authenticated church supplies the tenant."""
    response.headers["Cache-Control"] = "no-store"
    return operational_pending(db, UUID(user.igreja_id), stuck_after_seconds=stuck_after_seconds)


@router.get("/private-memory", response_model=PrivateMemoryOverview)
def private_memory(
    response: Response,
    user: CurrentUser = Depends(require_active_admin),
    db: Session = Depends(get_db),
) -> PrivateMemoryOverview:
    """Admin inventory; tenant comes exclusively from the server identity."""
    response.headers["Cache-Control"] = "private, no-store"
    return memory_overview(db, UUID(user.igreja_id))
