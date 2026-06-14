"""System managers router — operational operators (papel_operacional).

Endpoints:
  - GET    /system-managers          list operators
  - POST   /system-managers          add an operator
  - DELETE /system-managers/{id}     remove an operator

These are operational system roles (admin_sistema / operador), distinct from the
pastoral user_roles. Config screens are admin-only (delta-005).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SystemManager
from app.db.session import get_db
from app.deps import CurrentUser, require_role
from app.routers._common import ensure_tenant_context

logger = logging.getLogger("pastorai.system_managers")

router = APIRouter(prefix="/system-managers", tags=["system-managers"])

VALID_PAPEIS = {"admin_sistema", "operador"}


class SystemManagerOut(BaseModel):
    id: str
    nome: str
    email: str
    papelOperacional: str | None = None  # noqa: N815

    @classmethod
    def from_model(cls, m: SystemManager) -> "SystemManagerOut":
        return cls(
            id=str(m.id),
            nome=m.nome,
            email=m.email,
            papelOperacional=m.papel_operacional,
        )


class CreateSystemManagerRequest(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    papelOperacional: str = Field(default="operador")  # noqa: N815

    @field_validator("nome")
    @classmethod
    def _nome(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("nome obrigatório")
        return value

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.split("@")[-1]:
            raise ValueError("e-mail inválido")
        return value

    @field_validator("papelOperacional")
    @classmethod
    def _papel(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in VALID_PAPEIS:
            raise ValueError(f"papel_operacional inválido: {value}")
        return value


@router.get("", response_model=list[SystemManagerOut])
def list_managers(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> list[SystemManagerOut]:
    """List the tenant's system managers/operators."""
    ensure_tenant_context(db, current_user)
    rows = db.execute(select(SystemManager)).scalars().all()
    return [SystemManagerOut.from_model(m) for m in rows]


@router.post("", response_model=SystemManagerOut, status_code=status.HTTP_201_CREATED)
def create_manager(
    payload: CreateSystemManagerRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> SystemManagerOut:
    """Add an operator, rejecting a duplicate email within the tenant (409)."""
    ensure_tenant_context(db, current_user)
    igreja_uuid = uuid.UUID(current_user.igreja_id)

    existing = db.execute(
        select(SystemManager).where(SystemManager.email == payload.email)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um gerente com este e-mail",
        )

    manager = SystemManager(
        igreja_id=igreja_uuid,
        nome=payload.nome,
        email=payload.email,
        papel_operacional=payload.papelOperacional,
    )
    db.add(manager)
    db.flush()
    db.refresh(manager)
    db.commit()
    return SystemManagerOut.from_model(manager)


@router.delete("/{manager_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_manager(
    manager_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> None:
    """Remove an operator by id (tenant-scoped)."""
    ensure_tenant_context(db, current_user)

    try:
        manager_uuid = uuid.UUID(manager_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Gerente não encontrado"
        ) from exc

    manager = db.execute(
        select(SystemManager).where(SystemManager.id == manager_uuid)
    ).scalar_one_or_none()
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Gerente não encontrado"
        )

    db.delete(manager)
    db.commit()
