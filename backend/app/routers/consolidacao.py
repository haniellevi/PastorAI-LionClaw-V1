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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Celula, Consolidacao, Decision, Pessoa
from app.db.session import get_db
from app.services.ministerial_actions import register_decision
from app.deps import CurrentUser, get_current_user
from app.domain.consolidation import (
    CONNECTION_DEADLINE_HOURS,
    CONSOLIDATION_ROLES,
    VALID_VINCULOS,
    VINCULO_VISITANTE,
)

logger = logging.getLogger("pastorai.consolidacao")

router = APIRouter(prefix="/consolidacao", tags=["consolidacao"])

# Postgres SQLSTATE de unique_violation. Só ele é traduzido para 409 aqui;
# outras violações de integridade sobem (500) — não são conflito de estado.
_PG_UNIQUE_VIOLATION = "23505"


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

    try:
        consolidacao = register_decision(
            db, current_user, pessoa_id=uuid.UUID(payload.pessoa),
            vinculo=payload.vinculo, origem=payload.origem,
            celula_id=uuid.UUID(payload.celulaId) if payload.celulaId else None,
        )
    except IntegrityError as exc:
        db.rollback()
        if getattr(exc.orig, "pgcode", None) == _PG_UNIQUE_VIOLATION:
            raise HTTPException(409, "Pessoa já possui uma consolidação em aberto") from exc
        raise

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
