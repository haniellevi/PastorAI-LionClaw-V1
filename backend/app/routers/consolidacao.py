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


class InvitationResponse(BaseModel):
    id: str
    consolidacaoId: str
    responsavelId: str
    status: str
    prazoAceite: dt.datetime
    autoatribuicao: bool


def _invitation_response(row) -> InvitationResponse:
    return InvitationResponse(
        id=str(row.id), consolidacaoId=str(row.consolidacao_id),
        responsavelId=str(row.responsavel_id), status=row.status,
        prazoAceite=row.prazo_aceite, autoatribuicao=row.autoatribuicao,
    )


class InvitationAnswer(BaseModel):
    aceitar: bool = Field(strict=True)


@router.post('/{consolidacao_id}/atribuicoes/{atribuicao_id}/resposta', response_model=InvitationResponse)
def answer_invitation(
    consolidacao_id: uuid.UUID, atribuicao_id: uuid.UUID, payload: InvitationAnswer,
    db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user),
) -> InvitationResponse:
    from app.services.consolidation_workflow import respond_consolidacao_invitation
    row = respond_consolidacao_invitation(
        db, current_user, consolidacao_id=consolidacao_id,
        atribuicao_id=atribuicao_id, aceitar=payload.aceitar,
    )
    result = _invitation_response(row)
    db.commit()  # also persists expiry; an expired invitation never promotes the candidate
    return result


class AssignmentTrack(BaseModel):
    id: str
    pessoaId: str
    pessoaNome: str
    responsavelId: str | None
    convite: InvitationResponse | None
    etapasConfirmadas: list[str]
    prazoConexao: dt.datetime | None


@router.get('/atribuicoes', response_model=list[AssignmentTrack])
def list_assignments(
    offset: int = 0,
    db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user),
) -> list[AssignmentTrack]:
    """Live panel read. Expiration is lazy, serialized with answers and replacement."""
    from app.db.models import AppUser, UserRole, ConsolidacaoAtribuicao, ConsolidacaoEtapa
    from app.services.consolidation_workflow import (
        _lock_consolidacao, _lock_invitations, _expire_invitations,
    )
    from app.domain.work_queue import can_resolve
    if offset < 0:
        raise HTTPException(422, 'Página inválida')
    tenant = uuid.UUID(current_user.igreja_id)
    actor = uuid.UUID(current_user.app_user_id)
    # Read authorization takes no account lock before track locks (stable lock order).
    active = db.execute(select(AppUser.id).join(Pessoa, (Pessoa.id == AppUser.pessoa_id) &
        (Pessoa.igreja_id == AppUser.igreja_id)).where(
        AppUser.igreja_id == tenant, AppUser.id == actor, AppUser.status == 'ativo',
        Pessoa.arquivada_em.is_(None),
    )).scalar_one_or_none()
    roles = list(db.execute(select(UserRole.papel).where(
        UserRole.igreja_id == tenant, UserRole.user_id == actor,
    )).scalars())
    if active is None or not can_resolve(roles, 'fonovisita'):
        raise HTTPException(403, 'Conta sem vínculo ou capacidade para fonovisita')
    coordinator = bool(set(roles) & {'admin', 'pastor', 'lider_consol'})
    query = select(Consolidacao.id).where(
        Consolidacao.igreja_id == tenant, Consolidacao.concluida.is_(False),
        Consolidacao.abandonada_em.is_(None),
    )
    if not coordinator:
        query = query.where((Consolidacao.responsavel_id == actor) | select(
            ConsolidacaoAtribuicao.id
        ).where(
            ConsolidacaoAtribuicao.igreja_id == tenant,
            ConsolidacaoAtribuicao.consolidacao_id == Consolidacao.id,
            ConsolidacaoAtribuicao.responsavel_id == actor,
            ConsolidacaoAtribuicao.status == "atribuida",
        ).exists())
    ids = list(db.execute(query.order_by(Consolidacao.id).offset(offset).limit(50)).scalars())
    result = []
    for track_id in ids:
        track = _lock_consolidacao(db, tenant, track_id)
        if track.concluida or track.abandonada_em is not None:
            continue
        rows = _lock_invitations(db, tenant, track.id)
        _expire_invitations(db, rows)
        person = db.execute(select(Pessoa).where(
            Pessoa.igreja_id == tenant, Pessoa.id == track.pessoa_id,
        )).scalar_one()
        latest = rows[-1] if rows else None
        result.append(AssignmentTrack(
            id=str(track.id), pessoaId=str(person.id), pessoaNome=person.nome,
            responsavelId=str(track.responsavel_id) if track.responsavel_id else None,
            convite=_invitation_response(latest) if latest else None,
            prazoConexao=track.prazo_conexao,
            etapasConfirmadas=list(db.execute(select(ConsolidacaoEtapa.etapa).where(
                ConsolidacaoEtapa.igreja_id == tenant,
                ConsolidacaoEtapa.consolidacao_id == track.id,
                ConsolidacaoEtapa.concluida.is_(True),
            ).order_by(ConsolidacaoEtapa.etapa)).scalars()),
        ))
    db.commit()
    return result
