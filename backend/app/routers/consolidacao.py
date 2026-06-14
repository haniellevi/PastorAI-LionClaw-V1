"""Consolidation router — launch a decision and open consolidation (US-37/40).

Endpoint:
  - POST /consolidacao/decisao   register a decision and open its consolidation

Inserting a row in `decisions` fires the database trigger
`trg_decision_opens_consolidation`, which creates the consolidation (initial
stage `aceitou_jesus`) and, for the visitante flow, a `conectar_celula`
work-queue item due in 24h. We therefore write the decision and then read back
the consolidation the trigger created, rather than re-implementing the side
effects in the app.

Access is restricted to lider_consol/pastor (admin passes implicitly).
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Celula, Consolidacao, Decision, Pessoa
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.domain.consolidation import (
    CONNECTION_DEADLINE_HOURS,
    CONSOLIDATION_ROLES,
    VALID_VINCULOS,
    VINCULO_VISITANTE,
)
from app.routers._common import ensure_tenant_context

logger = logging.getLogger("pastorai.consolidacao")

router = APIRouter(prefix="/consolidacao", tags=["consolidacao"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class LaunchDecisionRequest(BaseModel):
    """Payload for launching a decision (data-decision)."""

    pessoa: str = Field(min_length=1, description="pessoa_id (uuid)")
    origem: str | None = Field(default=None, max_length=120)
    vinculo: str
    celulaId: str | None = None  # noqa: N815

    @field_validator("pessoa")
    @classmethod
    def _pessoa_uuid(cls, value: str) -> str:
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("pessoa inválida") from exc
        return value

    @field_validator("vinculo")
    @classmethod
    def _vinculo(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in VALID_VINCULOS:
            raise ValueError(f"vinculo inválido: {value}")
        return value

    @field_validator("celulaId")
    @classmethod
    def _celula_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("celulaId inválido") from exc
        return value


class LaunchDecisionResponse(BaseModel):
    status: str
    consolidacaoId: str  # noqa: N815
    etapa: str
    prazoConexao: dt.datetime | None = None  # noqa: N815
    responsavel: str | None = None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@router.post("/decisao", response_model=LaunchDecisionResponse)
def launch_decision(
    payload: LaunchDecisionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> LaunchDecisionResponse:
    """Register a decision and open its consolidation (US-37/40).

    - visitante flow (fluxo B): sets a 24h connection deadline; the trigger
      enqueues a `conectar_celula` item due in 24h.
    - celula flow (fluxo A): links the cell, no 24h deadline.
    """
    ensure_tenant_context(db, current_user)

    if not current_user.has_any_role(CONSOLIDATION_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para lançar decisões",
        )

    pessoa = db.execute(
        select(Pessoa).where(Pessoa.id == uuid.UUID(payload.pessoa))
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada"
        )

    celula_uuid: uuid.UUID | None = None
    if payload.celulaId is not None:
        celula_uuid = uuid.UUID(payload.celulaId)
        celula = db.execute(
            select(Celula).where(Celula.id == celula_uuid)
        ).scalar_one_or_none()
        if celula is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
            )

    # fluxo B (visitante): 24h connection deadline; fluxo A (celula): none.
    prazo_conexao: dt.datetime | None = None
    if payload.vinculo == VINCULO_VISITANTE:
        prazo_conexao = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
            hours=CONNECTION_DEADLINE_HOURS
        )

    decision = Decision(
        igreja_id=uuid.UUID(current_user.igreja_id),
        pessoa_id=pessoa.id,
        origem=payload.origem,
        vinculo=payload.vinculo,
        celula_id=celula_uuid,
        prazo_conexao=prazo_conexao,
    )
    db.add(decision)
    # A decision implies the person accepted Jesus (feeds F2 promotion).
    pessoa.aceitou_jesus = True
    # Flush so trg_decision_opens_consolidation creates the consolidation.
    db.flush()

    consolidacao = db.execute(
        select(Consolidacao)
        .where(Consolidacao.pessoa_id == pessoa.id)
        .order_by(Consolidacao.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if consolidacao is None:
        # The trigger should always create one; fail loudly if it did not.
        logger.error(
            "consolidation not created by trigger for decision pessoa=%s",
            pessoa.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Falha ao abrir consolidação",
        )

    db.commit()

    return LaunchDecisionResponse(
        status="created",
        consolidacaoId=str(consolidacao.id),
        etapa="inicial",
        prazoConexao=consolidacao.prazo_conexao,
        responsavel=str(consolidacao.responsavel_id)
        if consolidacao.responsavel_id
        else None,
    )
