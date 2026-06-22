"""Broadcasts router — segmented communications honoring opt-out (RF-38).

Endpoints:
  - GET  /broadcasts   paginated broadcast history (RNF-09)
  - POST /broadcasts   create/send a segmented broadcast

POST contract:
  {titulo, mensagem, segmentos, modo, agendamento?}
    -> {status, enviados, ignoradosOptout, agendadoPara}

Opt-out / no-consent people are always excluded (RF-38) and counted in
`ignoradosOptout`. When the cleared reach is zero (e.g. everyone opted out), the
send is blocked: the broadcast is recorded as `rascunho` and `enviados=0`. Sends
go out through the official WhatsApp number (Evolution).
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Broadcast, Pessoa, WhatsappConnection
from app.db.session import get_db
from app.deps import CurrentUser, require_screen
from app.domain.broadcast import RecipientCandidate, resolve_audience
from app.routers._common import Page, PaginationParams, ensure_tenant_context
from app.services.evolution import EvolutionClient, EvolutionError, get_evolution_client

logger = logging.getLogger("pastorai.broadcasts")

router = APIRouter(prefix="/broadcasts", tags=["broadcasts"])

VALID_MODOS = {"agora", "agendado"}
VALID_REPETICOES = {"once", "daily", "weekly", "biweekly", "monthly"}


class ScheduleIn(BaseModel):
    data: dt.date
    hora: str | None = Field(default=None, max_length=10)
    repeticao: str | None = Field(default=None)

    @field_validator("repeticao")
    @classmethod
    def _repeticao(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if value not in VALID_REPETICOES:
            raise ValueError(f"repeticao inválida: {value}")
        return value


class CreateBroadcastRequest(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    mensagem: str = Field(min_length=1, max_length=4000)
    segmentos: list[str] = Field(min_length=1)
    modo: str
    agendamento: ScheduleIn | None = None

    @field_validator("modo")
    @classmethod
    def _modo(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in VALID_MODOS:
            raise ValueError(f"modo inválido: {value}")
        return value


class BroadcastResponse(BaseModel):
    """Result of creating a broadcast."""

    id: str
    status: str  # enviado | agendado | rascunho
    enviados: int
    ignoradosOptout: int  # noqa: N815
    agendadoPara: str | None = None  # noqa: N815


class BroadcastOut(BaseModel):
    id: str
    titulo: str
    mensagem: str
    segmentos: list[str]
    modo: str
    status: str | None = None
    alcance: int | None = None
    ignoradosOptout: int | None = None  # noqa: N815
    data: dt.date | None = None
    hora: str | None = None
    repeticao: str | None = None

    @classmethod
    def from_model(cls, b: Broadcast) -> "BroadcastOut":
        return cls(
            id=str(b.id),
            titulo=b.titulo,
            mensagem=b.mensagem,
            segmentos=list(b.segmentos or []),
            modo=b.modo,
            status=b.status,
            alcance=b.alcance,
            ignoradosOptout=b.ignorados_optout,
            data=b.data,
            hora=b.hora,
            repeticao=b.repeticao,
        )


def _instance(db: Session, igreja_id: uuid.UUID) -> str | None:
    conn = db.execute(
        select(WhatsappConnection).where(WhatsappConnection.igreja_id == igreja_id)
    ).scalar_one_or_none()
    return conn.instance if conn else None


def _scheduled_for(agendamento: ScheduleIn | None) -> str | None:
    if agendamento is None:
        return None
    if agendamento.hora:
        return f"{agendamento.data.isoformat()}T{agendamento.hora}"
    return agendamento.data.isoformat()


@router.get("", response_model=Page[BroadcastOut])
def list_broadcasts(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_screen("comunicados")),
) -> Page[BroadcastOut]:
    """Return the tenant's broadcasts, newest first (RNF-09)."""
    ensure_tenant_context(db, current_user)
    rows = db.execute(
        select(Broadcast)
        .order_by(Broadcast.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()
    total = len(
        db.execute(select(Broadcast.id)).scalars().all()
    )
    return Page[BroadcastOut](
        items=[BroadcastOut.from_model(b) for b in rows],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=total,
    )


@router.post("", response_model=BroadcastResponse)
def create_broadcast(
    payload: CreateBroadcastRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_screen("comunicados")),
    evolution: EvolutionClient = Depends(get_evolution_client),
) -> BroadcastResponse:
    """Resolve the audience (honoring opt-out) and send or schedule it.

    - Opt-out / no-consent people are excluded and counted (RF-38).
    - Zero cleared reach blocks the send (recorded as rascunho, enviados=0).
    - modo=agora sends now; modo=agendado stores the schedule (agendadoPara).
    """
    ensure_tenant_context(db, current_user)
    igreja_uuid = uuid.UUID(current_user.igreja_id)

    people = db.execute(select(Pessoa)).scalars().all()
    candidates = [
        RecipientCandidate(
            telefone=p.telefone,
            tipo=p.tipo,
            optout=p.optout,
            consentimento=p.consentimento,
        )
        for p in people
    ]
    audience = resolve_audience(candidates, payload.segmentos)

    scheduled_for = _scheduled_for(payload.agendamento)
    broadcast = Broadcast(
        igreja_id=igreja_uuid,
        titulo=payload.titulo,
        mensagem=payload.mensagem,
        segmentos=payload.segmentos,
        modo=payload.modo,
        data=payload.agendamento.data if payload.agendamento else None,
        hora=payload.agendamento.hora if payload.agendamento else None,
        repeticao=payload.agendamento.repeticao if payload.agendamento else None,
        ignorados_optout=audience.ignored_optout,
    )

    # Zero cleared reach -> blocked (e.g. everyone opted out). RF-38.
    if audience.reach == 0:
        broadcast.alcance = 0
        broadcast.status = "rascunho"
        db.add(broadcast)
        db.flush()
        db.refresh(broadcast)
        db.commit()
        logger.info(
            "Broadcast blocked (reach=0, ignorados=%s)", audience.ignored_optout
        )
        return BroadcastResponse(
            id=str(broadcast.id),
            status="bloqueado",
            enviados=0,
            ignoradosOptout=audience.ignored_optout,
            agendadoPara=scheduled_for,
        )

    if payload.modo == "agendado":
        broadcast.alcance = audience.reach
        broadcast.status = "agendado"
        db.add(broadcast)
        db.flush()
        db.refresh(broadcast)
        db.commit()
        return BroadcastResponse(
            id=str(broadcast.id),
            status="agendado",
            enviados=0,
            ignoradosOptout=audience.ignored_optout,
            agendadoPara=scheduled_for,
        )

    # modo=agora -> dispatch through the official number.
    instance = _instance(db, igreja_uuid)
    sent = 0
    if instance:
        for phone in audience.recipients:
            try:
                evolution.send_text(instance, phone, payload.mensagem)
                sent += 1
            except EvolutionError:
                logger.warning("Broadcast send failed to a recipient")
    else:
        logger.info("No official WhatsApp instance; broadcast recorded only")

    broadcast.alcance = audience.reach
    broadcast.status = "enviado"
    db.add(broadcast)
    db.flush()
    db.refresh(broadcast)
    db.commit()

    return BroadcastResponse(
        id=str(broadcast.id),
        status="enviado",
        enviados=sent,
        ignoradosOptout=audience.ignored_optout,
        agendadoPara=None,
    )
