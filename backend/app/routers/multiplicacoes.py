"""Multiplications router — schedule and approve cell multiplications (enviar).

Endpoints:
  - GET  /multiplicacoes              list multiplications, optionally by status
  - POST /multiplicacoes              schedule a multiplication
  - POST /multiplicacoes/{id}/aprovar approve (gated by supervisao_ok)

delta-027: approval is disabled while supervision has not signed off
(`supervisao_ok=false`); approving records the approver (`aprovada_por`).
Access is restricted to lider_g12/pastor (admin passes implicitly).
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Celula, Multiplicacao, Pessoa
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.domain.multiplication import (
    MULTIPLICATION_ROLES,
    STATUS_APROVADA,
    VALID_STATUS,
    can_approve,
    schedule_status,
)
from app.routers._common import Page, PaginationParams, ensure_tenant_context

logger = logging.getLogger("pastorai.multiplicacoes")

router = APIRouter(prefix="/multiplicacoes", tags=["multiplicacoes"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class MultiplicacaoOut(BaseModel):
    id: str
    celulaId: str  # noqa: N815
    status: str | None = None
    dataPrevista: dt.date | None = None  # noqa: N815
    descendencia: str | None = None
    novoLiderId: str | None = None  # noqa: N815
    supervisaoOk: bool  # noqa: N815
    aprovadaPor: str | None = None  # noqa: N815

    @classmethod
    def from_model(cls, m: Multiplicacao) -> "MultiplicacaoOut":
        return cls(
            id=str(m.id),
            celulaId=str(m.celula_id),
            status=m.status,
            dataPrevista=m.data_prevista,
            descendencia=m.descendencia,
            novoLiderId=str(m.novo_lider_id) if m.novo_lider_id else None,
            supervisaoOk=m.supervisao_ok,
            aprovadaPor=str(m.aprovada_por) if m.aprovada_por else None,
        )


class CreateMultiplicacaoRequest(BaseModel):
    celulaId: str = Field(min_length=1)  # noqa: N815
    dataPrevista: dt.date | None = None  # noqa: N815
    novoLiderId: str | None = None  # noqa: N815
    descendencia: str | None = Field(default=None, max_length=400)

    @field_validator("celulaId")
    @classmethod
    def _celula_uuid(cls, value: str) -> str:
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("celulaId inválido") from exc
        return value

    @field_validator("novoLiderId")
    @classmethod
    def _lider_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("novoLiderId inválido") from exc
        return value


class ApproveResponse(BaseModel):
    status: str
    multiplicacaoId: str  # noqa: N815
    aprovadaPor: str  # noqa: N815


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("", response_model=Page[MultiplicacaoOut])
def list_multiplicacoes(
    pagination: PaginationParams = Depends(),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Page[MultiplicacaoOut]:
    """List multiplications, optionally filtered by status."""
    ensure_tenant_context(db, current_user)

    filters = []
    if status_filter is not None:
        normalized = status_filter.strip().lower()
        if normalized not in VALID_STATUS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"status inválido: {status_filter}",
            )
        filters.append(Multiplicacao.status == normalized)

    total = db.execute(
        select(func.count()).select_from(Multiplicacao).where(*filters)
    ).scalar_one()
    rows = db.execute(
        select(Multiplicacao)
        .where(*filters)
        .order_by(Multiplicacao.data_prevista.asc().nulls_last())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()

    return Page[MultiplicacaoOut](
        items=[MultiplicacaoOut.from_model(m) for m in rows],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


@router.post("", response_model=MultiplicacaoOut, status_code=status.HTTP_201_CREATED)
def schedule_multiplicacao(
    payload: CreateMultiplicacaoRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> MultiplicacaoOut:
    """Schedule a multiplication (agendada with a date, else sem_agendamento)."""
    ensure_tenant_context(db, current_user)

    if not current_user.has_any_role(MULTIPLICATION_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para agendar multiplicações",
        )

    celula = db.execute(
        select(Celula).where(Celula.id == uuid.UUID(payload.celulaId))
    ).scalar_one_or_none()
    if celula is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
        )

    novo_lider_uuid: uuid.UUID | None = None
    if payload.novoLiderId is not None:
        novo_lider_uuid = uuid.UUID(payload.novoLiderId)
        novo_lider = db.execute(
            select(Pessoa).where(Pessoa.id == novo_lider_uuid)
        ).scalar_one_or_none()
        if novo_lider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Novo líder não encontrado",
            )

    multiplicacao = Multiplicacao(
        igreja_id=uuid.UUID(current_user.igreja_id),
        celula_id=celula.id,
        status=schedule_status(payload.dataPrevista is not None),
        data_prevista=payload.dataPrevista,
        descendencia=payload.descendencia,
        novo_lider_id=novo_lider_uuid,
    )
    db.add(multiplicacao)
    db.flush()
    db.refresh(multiplicacao)
    db.commit()

    return MultiplicacaoOut.from_model(multiplicacao)


@router.post("/{multiplicacao_id}/aprovar", response_model=ApproveResponse)
def approve_multiplicacao(
    multiplicacao_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApproveResponse:
    """Approve a multiplication; blocked while supervisao_ok=false (delta-027)."""
    ensure_tenant_context(db, current_user)

    if not current_user.has_any_role(MULTIPLICATION_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para aprovar multiplicações",
        )

    multiplicacao = db.execute(
        select(Multiplicacao)
        .where(Multiplicacao.id == _parse_uuid(multiplicacao_id))
        .with_for_update()
    ).scalar_one_or_none()
    if multiplicacao is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Multiplicação não encontrada",
        )

    if not can_approve(multiplicacao.supervisao_ok):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "supervision_pending",
                "message": "Aprovação bloqueada: supervisão pendente",
            },
        )

    multiplicacao.status = STATUS_APROVADA
    multiplicacao.aprovada_por = uuid.UUID(current_user.app_user_id)
    db.flush()
    db.refresh(multiplicacao)
    db.commit()

    return ApproveResponse(
        status=STATUS_APROVADA,
        multiplicacaoId=str(multiplicacao.id),
        aprovadaPor=str(multiplicacao.aprovada_por),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Multiplicação não encontrada",
        ) from exc
