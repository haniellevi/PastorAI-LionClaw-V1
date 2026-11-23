"""Read-only platform allowlist check for tenant-plane routes.

``platform_admins`` is closed to ``anon``/``authenticated`` (migration 0010),
so a tenant-scoped request session cannot see it.  Tenant routes that must not
act on a platform operator (P1.1: ``DELETE /team/{id}``) ask this narrow,
separate BYPASSRLS session a single yes/no question.  The tenant session keeps
its scope; this one only reads and is always rolled back.  The session opens
lazily, so requests refused before the check never touch the database.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PlatformAdmin
from app.db.session import get_session_factory
from app.db.tenant_session import mark_cross_tenant

PlatformAdminChecker = Callable[[uuid.UUID], bool]


def platform_admin_exists_with_backend_role(
    app_user_id: uuid.UUID,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> bool:
    """Return whether ``app_user_id`` is on the platform allowlist."""

    db = (session_factory or get_session_factory())()
    try:
        mark_cross_tenant(db, source="tenant-platform-membership-check")
        found = db.execute(
            select(PlatformAdmin.id).where(PlatformAdmin.app_user_id == app_user_id)
        ).scalar_one_or_none()
        return found is not None
    finally:
        try:
            db.rollback()
        finally:
            db.close()


def get_platform_admin_checker() -> PlatformAdminChecker:
    """FastAPI dependency resolving the lazy allowlist reader."""

    return platform_admin_exists_with_backend_role
