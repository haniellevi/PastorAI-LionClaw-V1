"""Minimal tenant-admin operational projection, without conversation data."""
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import CurrentUser, require_role
from app.services.operational_usage import OperationalUsage, operational_usage

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/ai-usage", response_model=OperationalUsage)
def ai_usage(
    response: Response,
    user: CurrentUser = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
) -> OperationalUsage:
    """Seven rolling days for the authenticated admin's church only."""
    response.headers["Cache-Control"] = "no-store"
    return operational_usage(db, UUID(user.igreja_id))
