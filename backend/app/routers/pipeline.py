"""Pipeline router — person state machine (F2) and fonovisita action.

Endpoints:
  - GET  /pipeline             paginated people with their stage (feeds the
                               ganhar/consolidar screens)
  - PUT  /pipeline             move a person's etapa/subetapa respecting F2
  - POST /pipeline/fonovisita  queue a fonovisita work item for a person

The promotion criteria are enforced *before* writing (a visitante cannot be
promoted past "ganhar" without 3+ attendances or a decision). The database
trigger `trg_promote_pipeline` may still auto-advance on write; we refresh and
return the resulting state.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    Consolidacao,
    ConsolidacaoEtapa,
    Pessoa,
    WorkQueueItem,
)
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.domain.consolidation import (
    CONSOLIDATION_ROLES,
    can_conclude,
    compute_progresso,
    is_valid_etapa,
    pending_mandatory,
)
from app.domain.pipeline import VALID_ETAPAS, validate_transition
from app.routers._common import Page, PaginationParams, ensure_tenant_context
from app.routers.contacts import ContactOut

logger = logging.getLogger("pastorai.pipeline")

router = APIRouter(tags=["pipeline"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class PipelineUpdateRequest(BaseModel):
    pessoaId: str = Field(min_length=1)  # noqa: N815
    etapa: str
    subetapa: str | None = None

    @field_validator("pessoaId")
    @classmethod
    def _uuid(cls, value: str) -> str:
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("pessoaId inválido") from exc
        return value

    @field_validator("etapa")
    @classmethod
    def _etapa(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in VALID_ETAPAS:
            raise ValueError(f"etapa inválida: {value}")
        return value


class PipelineUpdateResponse(BaseModel):
    status: str
    pessoaId: str  # noqa: N815
    etapa: str | None = None
    subetapa: str | None = None
    tipo: str | None = None


class FonovisitaRequest(BaseModel):
    pessoaId: str = Field(min_length=1)  # noqa: N815
    contexto: str | None = Field(default=None, max_length=400)

    @field_validator("pessoaId")
    @classmethod
    def _uuid(cls, value: str) -> str:
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("pessoaId inválido") from exc
        return value


class FonovisitaResponse(BaseModel):
    status: str
    itemId: str  # noqa: N815


class AssignConsolidadorRequest(BaseModel):
    consolidacaoId: str = Field(min_length=1)  # noqa: N815
    responsavelId: str = Field(min_length=1)  # noqa: N815

    @field_validator("consolidacaoId", "responsavelId")
    @classmethod
    def _uuid(cls, value: str) -> str:
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("identificador inválido") from exc
        return value


class AssignConsolidadorResponse(BaseModel):
    status: str
    consolidacaoId: str  # noqa: N815
    responsavelId: str  # noqa: N815


class AdvanceStageRequest(BaseModel):
    consolidacaoId: str = Field(min_length=1)  # noqa: N815
    etapa: str | None = None
    concluir: bool = False

    @field_validator("consolidacaoId")
    @classmethod
    def _uuid(cls, value: str) -> str:
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("consolidacaoId inválido") from exc
        return value

    @field_validator("etapa")
    @classmethod
    def _etapa(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if not is_valid_etapa(value):
            raise ValueError(f"etapa inválida: {value}")
        return value


class AdvanceStageResponse(BaseModel):
    status: str
    consolidacaoId: str  # noqa: N815
    progresso: int
    concluida: bool
    etapasPendentes: list[str]  # noqa: N815


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/pipeline", response_model=Page[ContactOut])
def list_pipeline(
    pagination: PaginationParams = Depends(),
    etapa: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Page[ContactOut]:
    """Return people with their stage, optionally filtered by etapa."""
    ensure_tenant_context(db, current_user)

    filters = []
    if etapa is not None:
        normalized = etapa.strip().lower()
        if normalized not in VALID_ETAPAS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"etapa inválida: {etapa}",
            )
        filters.append(Pessoa.etapa == normalized)

    total = db.execute(
        select(func.count()).select_from(Pessoa).where(*filters)
    ).scalar_one()
    rows = db.execute(
        select(Pessoa)
        .where(*filters)
        .order_by(Pessoa.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()

    return Page[ContactOut](
        items=[ContactOut.from_model(p) for p in rows],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


@router.put("/pipeline", response_model=PipelineUpdateResponse)
def update_pipeline(
    payload: PipelineUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> PipelineUpdateResponse:
    """Move a person along the pipeline, enforcing F2 promotion rules."""
    ensure_tenant_context(db, current_user)

    pessoa = db.execute(
        select(Pessoa).where(Pessoa.id == uuid.UUID(payload.pessoaId))
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada"
        )

    result = validate_transition(
        current_tipo=pessoa.tipo,
        current_etapa=pessoa.etapa,
        target_etapa=payload.etapa,
        target_subetapa=payload.subetapa,
        presencas_celula=pessoa.presencas_celula,
        aceitou_jesus=pessoa.aceitou_jesus,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=result.reason
        )

    pessoa.etapa = payload.etapa
    if payload.subetapa is not None:
        pessoa.subetapa = payload.subetapa
    db.flush()  # fires trg_promote_pipeline; may auto-advance further
    db.refresh(pessoa)
    db.commit()

    return PipelineUpdateResponse(
        status="updated",
        pessoaId=str(pessoa.id),
        etapa=pessoa.etapa,
        subetapa=pessoa.subetapa,
        tipo=pessoa.tipo,
    )


@router.post("/pipeline/fonovisita", response_model=FonovisitaResponse)
def queue_fonovisita(
    payload: FonovisitaRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> FonovisitaResponse:
    """Create (or refresh) an open 'fonovisita' work item for a person.

    Idempotent per person: an already-open fonovisita item is reused and its
    context updated instead of creating a duplicate.
    """
    ensure_tenant_context(db, current_user)

    pessoa = db.execute(
        select(Pessoa).where(Pessoa.id == uuid.UUID(payload.pessoaId))
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada"
        )

    contexto = payload.contexto or f"Fonovisita para {pessoa.nome}"

    existing = db.execute(
        select(WorkQueueItem).where(
            WorkQueueItem.pessoa_id == pessoa.id,
            WorkQueueItem.tipo == "fonovisita",
            WorkQueueItem.status.in_(["aberto", "assumido"]),
        )
        .limit(1)
    ).scalar_one_or_none()

    if existing is not None:
        existing.contexto = contexto
        db.flush()
        db.refresh(existing)
        db.commit()
        return FonovisitaResponse(status="updated", itemId=str(existing.id))

    item = WorkQueueItem(
        igreja_id=uuid.UUID(current_user.igreja_id),
        tipo="fonovisita",
        titulo=f"Fonovisita: {pessoa.nome}",
        contexto=contexto,
        pessoa_id=pessoa.id,
        status="aberto",
        prioridade=2,
    )
    db.add(item)
    db.flush()
    db.refresh(item)
    db.commit()
    return FonovisitaResponse(status="created", itemId=str(item.id))


@router.post("/pipeline/assign-consolidador", response_model=AssignConsolidadorResponse)
def assign_consolidador(
    payload: AssignConsolidadorRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> AssignConsolidadorResponse:
    """Assign the responsible consolidador to a consolidation (delta-018).

    Setting `responsavel_id` is what later enables that user (and only that
    user) to confirm stages via /pipeline/advance-stage.
    """
    ensure_tenant_context(db, current_user)

    if not current_user.has_any_role(CONSOLIDATION_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para atribuir consolidador",
        )

    consolidacao = db.execute(
        select(Consolidacao).where(
            Consolidacao.id == uuid.UUID(payload.consolidacaoId)
        )
    ).scalar_one_or_none()
    if consolidacao is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consolidação não encontrada",
        )

    responsavel = db.execute(
        select(AppUser).where(AppUser.id == uuid.UUID(payload.responsavelId))
    ).scalar_one_or_none()
    if responsavel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Responsável não encontrado",
        )

    consolidacao.responsavel_id = responsavel.id
    db.flush()
    db.refresh(consolidacao)
    db.commit()

    return AssignConsolidadorResponse(
        status="assigned",
        consolidacaoId=str(consolidacao.id),
        responsavelId=str(consolidacao.responsavel_id),
    )


@router.post("/pipeline/advance-stage", response_model=AdvanceStageResponse)
def advance_stage(
    payload: AdvanceStageRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> AdvanceStageResponse:
    """Confirm an individual-track stage or conclude the consolidation.

    Identity gate (delta-018): only the consolidation's responsavel_id may
    confirm a stage or conclude — everyone else gets 403. Concluding is blocked
    (409) while any mandatory stage is still pending. Progress reflects the
    confirmed mandatory stages.
    """
    ensure_tenant_context(db, current_user)

    if payload.etapa is None and not payload.concluir:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe etapa para confirmar ou concluir=true",
        )

    consolidacao = db.execute(
        select(Consolidacao)
        .where(Consolidacao.id == uuid.UUID(payload.consolidacaoId))
        .with_for_update()
    ).scalar_one_or_none()
    if consolidacao is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consolidação não encontrada",
        )

    # Identity gate: only the assigned consolidador may act (delta-018).
    if (
        consolidacao.responsavel_id is None
        or str(consolidacao.responsavel_id) != current_user.app_user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o consolidador responsável pode confirmar etapas",
        )

    if consolidacao.concluida:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Consolidação já concluída",
        )

    # Confirm the requested stage (idempotent per stage name).
    if payload.etapa is not None:
        etapa_row = db.execute(
            select(ConsolidacaoEtapa).where(
                ConsolidacaoEtapa.consolidacao_id == consolidacao.id,
                ConsolidacaoEtapa.etapa == payload.etapa,
            )
        ).scalar_one_or_none()
        if etapa_row is None:
            etapa_row = ConsolidacaoEtapa(
                igreja_id=uuid.UUID(current_user.igreja_id),
                consolidacao_id=consolidacao.id,
                etapa=payload.etapa,
            )
            db.add(etapa_row)
        etapa_row.concluida = True
        etapa_row.confirmada_por = uuid.UUID(current_user.app_user_id)
        etapa_row.confirmada_em = dt.datetime.now(dt.timezone.utc)
        db.flush()

    confirmed = db.execute(
        select(ConsolidacaoEtapa.etapa).where(
            ConsolidacaoEtapa.consolidacao_id == consolidacao.id,
            ConsolidacaoEtapa.concluida.is_(True),
        )
    ).scalars().all()
    confirmed_set = {e for e in confirmed if e}

    consolidacao.progresso = compute_progresso(confirmed_set)

    if payload.concluir:
        if not can_conclude(confirmed_set):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "pending_stages",
                    "message": "Há etapas obrigatórias pendentes",
                    "etapasPendentes": sorted(pending_mandatory(confirmed_set)),
                },
            )
        consolidacao.concluida = True
        consolidacao.progresso = 100

    db.flush()
    db.refresh(consolidacao)
    db.commit()

    return AdvanceStageResponse(
        status="concluded" if consolidacao.concluida else "advanced",
        consolidacaoId=str(consolidacao.id),
        progresso=consolidacao.progresso,
        concluida=consolidacao.concluida,
        etapasPendentes=sorted(pending_mandatory(confirmed_set)),
    )
