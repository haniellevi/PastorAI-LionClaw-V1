"""Roles router — role x screen permission matrix (delta-010).

Endpoints:
  - GET /roles/permissions   read the matrix (papel -> [telas])
  - PUT /roles/permissions   replace the matrix

role_permissions is the source of truth for the sidebar menu. `dashboard` is
liberated to every role and cannot be removed (delta-010). `admin` has implicit
access to everything and is therefore not stored in the matrix. Config screens
are admin-only (delta-005).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RolePermission
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user, require_role
from app.domain.permissions import DEFAULT_PERMISSIONS

logger = logging.getLogger("pastorai.roles")

router = APIRouter(prefix="/roles", tags=["roles"])

# Screen that is always available and may never be removed (delta-010).
MANDATORY_SCREEN = "dashboard"

# Roles that participate in the matrix (admin has implicit access, excluded).
MATRIX_ROLES = {
    "operador",
    "pastor",
    "lider_g12",
    "lider_consol",
    "lider_celula",
    "lider_mult",
    "membro",
}


class PermissionsMatrix(BaseModel):
    """Matrix mapping each role to the list of screens it can access."""

    matriz: dict[str, list[str]]

    @field_validator("matriz")
    @classmethod
    def _matriz(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        normalized: dict[str, list[str]] = {}
        for papel, telas in value.items():
            role = (papel or "").strip().lower()
            if role not in MATRIX_ROLES:
                raise ValueError(f"papel inválido: {papel}")
            seen: list[str] = []
            for tela in telas:
                screen = (tela or "").strip().lower()
                if screen and screen not in seen:
                    seen.append(screen)
            normalized[role] = seen
        return normalized


@router.get("/permissions", response_model=PermissionsMatrix)
def get_permissions(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> PermissionsMatrix:
    """Return the authenticated user's tenant role x screen matrix.

    Reading the matrix is required by every authenticated shell so its menu and
    preloads match the same server-side authorization source. Tenant isolation
    remains enforced by ``get_current_user`` + the scoped database session;
    replacing the matrix stays admin-only on PUT.
    """
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    rows = db.execute(
        select(RolePermission).where(RolePermission.igreja_id == igreja_uuid)
    ).scalars().all()
    stored: dict[str, list[str]] = {}
    for row in rows:
        stored.setdefault(row.papel, [])
        if row.tela not in stored[row.papel]:
            stored[row.papel].append(row.tela)

    # Espelha screens_for_role: papel sem linha persistida ainda usa o default;
    # papel customizado recebe exatamente suas linhas, sempre com dashboard.
    # Assim shell e backend compartilham a mesma matriz EFETIVA inclusive para
    # tenants antigos/ parcialmente semeados.
    matriz: dict[str, list[str]] = {}
    for role in MATRIX_ROLES:
        telas = list(stored.get(role, sorted(DEFAULT_PERMISSIONS.get(role, ()))))
        if MANDATORY_SCREEN not in telas:
            telas.insert(0, MANDATORY_SCREEN)
        matriz[role] = telas
    return PermissionsMatrix(matriz=matriz)


@router.put("/permissions", response_model=PermissionsMatrix)
def update_permissions(
    payload: PermissionsMatrix,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> PermissionsMatrix:
    """Replace the matrix, guaranteeing dashboard stays for every role.

    `dashboard` is force-included for each matrix role even if the client omits
    it (delta-010), so the menu always has a landing screen.
    """
    igreja_uuid = uuid.UUID(current_user.igreja_id)

    # Force dashboard for every role in the matrix.
    final: dict[str, list[str]] = {}
    for role in MATRIX_ROLES:
        telas = list(payload.matriz.get(role, []))
        if MANDATORY_SCREEN not in telas:
            telas.insert(0, MANDATORY_SCREEN)
        final[role] = telas

    # Replace existing rows for this tenant.
    existing = db.execute(
        select(RolePermission).where(RolePermission.igreja_id == igreja_uuid)
    ).scalars().all()
    for row in existing:
        db.delete(row)
    db.flush()

    for role, telas in final.items():
        for tela in telas:
            db.add(
                RolePermission(igreja_id=igreja_uuid, papel=role, tela=tela)
            )
    db.commit()

    return PermissionsMatrix(matriz=final)
