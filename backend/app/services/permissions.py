"""Effective tenant menu, shared by session bootstrap and permission reads."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RolePermission
from app.domain.permissions import screens_for_role

MANDATORY_SCREEN = "dashboard"
MATRIX_ROLES = {
    "operador", "pastor", "lider_g12", "lider_consol",
    "lider_celula", "lider_mult", "membro",
}


def effective_permissions(db: Session, igreja_id: str) -> dict[str, list[str]]:
    rows = db.execute(
        select(RolePermission).where(RolePermission.igreja_id == uuid.UUID(igreja_id))
    ).scalars().all()
    stored: dict[str, set[str]] = {}
    for row in rows:
        stored.setdefault(row.papel, set()).add(row.tela)
    result: dict[str, list[str]] = {}
    for role in sorted(MATRIX_ROLES):
        effective = screens_for_role(role, stored)
        result[role] = [MANDATORY_SCREEN, *sorted(effective - {MANDATORY_SCREEN})]
    return result
