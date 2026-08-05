"""Broadcasts router — segmented communications honoring opt-out (RF-38).

Endpoints:
  - GET  /broadcasts   paginated broadcast history (RNF-09)
  - POST /broadcasts   create/send a segmented broadcast

POST contract:
  {titulo, mensagem, segmentos, modo, agendamento?}
    -> {status, enviados, ignoradosOptout, agendadoPara}

Opt-out / no-consent people are always excluded (RF-38) and counted in
`ignoradosOptout`. Archived people (W3) are excluded too, but are NOT counted as
opt-out — they simply are not part of the church's audience anymore. When the
cleared reach is zero (e.g. everyone opted out), the send is blocked: the
broadcast is recorded as `rascunho` and `enviados=0`. Sends go out through the
official WhatsApp number (Evolution).
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Broadcast, Celula, Pessoa, WhatsappConnection
from app.db.session import get_db
from app.deps import CurrentUser, require_screen
from app.domain.broadcast import RecipientCandidate, resolve_audience
from app.routers._common import Page, PaginationParams
from app.services.broadcast_delivery import scheduled_instant, utc_now
from app.services.evolution import EvolutionClient, EvolutionError, get_evolution_client

logger = logging.getLogger("pastorai.broadcasts")

router = APIRouter(prefix="/broadcasts", tags=["broadcasts"])

VALID_MODOS = {"agora", "agendado"}
VALID_REPETICOES = {"once", "daily", "weekly", "biweekly", "monthly"}
_TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


class ScheduleIn(BaseModel):
    data: dt.date
    hora: str | None = Field(default=None, max_length=10)
    repeticao: str | None = Field(default=None)

    @field_validator("hora")
    @classmethod
    def _hora(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not _TIME_RE.fullmatch(value):
            raise ValueError("hora deve estar no formato HH:MM (00:00 a 23:59)")
        return value

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
    execucaoId: str | None = None  # noqa: N815
    alcancePrevisto: int | None = None  # noqa: N815


class BroadcastCapabilities(BaseModel):
    agendamentoDisponivel: bool  # noqa: N815
    motivo: str | None = None


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
    proximaExecucao: dt.datetime | None = None  # noqa: N815
    precisaRevisao: bool = False  # noqa: N815

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
            proximaExecucao=b.proxima_execucao,
            precisaRevisao=(b.status == "agendado" and b.proxima_execucao is None),
        )


def _instance(db: Session, igreja_id: uuid.UUID) -> str | None:
    conn = db.execute(
        select(WhatsappConnection).where(WhatsappConnection.igreja_id == igreja_id)
    ).scalar_one_or_none()
    if conn is None or conn.status != "online" or not conn.instance:
        return None
    return conn.instance


def _rollout_state() -> tuple[bool, bool]:
    """Return the boot-time async and outbound gates."""
    settings = get_settings()
    return (
        bool(getattr(settings, "broadcast_async_enabled", False)),
        bool(getattr(settings, "external_sends_enabled", False)),
    )


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


@router.get("/capabilities", response_model=BroadcastCapabilities)
def broadcast_capabilities(
    current_user: CurrentUser = Depends(require_screen("comunicados")),
) -> BroadcastCapabilities:
    """Expose the backend rollout gate as the single UI source of truth."""
    async_enabled, sends_enabled = _rollout_state()
    enabled = async_enabled and sends_enabled
    return BroadcastCapabilities(
        agendamentoDisponivel=enabled,
        motivo=(
            None
            if enabled
            else (
                "envios_externos_desabilitados"
                if not sends_enabled
                else "despacho_indisponivel"
            )
        ),
    )


@router.post("", response_model=BroadcastResponse)
def create_broadcast(
    payload: CreateBroadcastRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_screen("comunicados")),
    evolution: EvolutionClient = Depends(get_evolution_client),
) -> BroadcastResponse:
    """Resolve the audience (honoring opt-out) and send or schedule it.

    - Opt-out / no-consent people are excluded and counted (RF-38).
    - Archived people are excluded and NOT counted as opt-out (W3).
    - Zero cleared reach blocks the send (recorded as rascunho, enviados=0).
    - modo=agora sends now; modo=agendado stores the schedule (agendadoPara).
    """
    async_enabled, sends_enabled = _rollout_state()
    if not sends_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Envios externos ainda não habilitados.",
        )
    if payload.modo == "agendado" and not async_enabled:
        # Must happen before any broadcast write: accepting an agenda without a
        # live dispatcher would be a silent promise the system cannot keep.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agendamento de comunicados ainda não habilitado.",
        )

    now = utc_now()
    next_execution: dt.datetime | None = None
    if payload.modo == "agendado":
        if payload.agendamento is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Data do agendamento é obrigatória.",
            )
        try:
            next_execution = scheduled_instant(
                payload.agendamento.data, payload.agendamento.hora
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        if next_execution <= now:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Data e hora do agendamento já passaram.",
            )
    elif async_enabled:
        next_execution = now

    igreja_uuid = uuid.UUID(current_user.igreja_id)

    # Pessoa arquivada (W3) está FORA da audiência: não recebe e não conta como
    # opt-out — ela nem chega a ser candidata. `arquivada_em IS NULL` = ativa
    # (ver models.Pessoa). O escopo por tenant continua vindo da RLS.
    people = db.execute(
        select(Pessoa).where(Pessoa.arquivada_em.is_(None))
    ).scalars().all()
    # Segmento "lider" é derivado: quem lidera célula ATIVA (celulas.lider_id),
    # não o tipo manual (regra 2026-07-06).
    leader_ids = {
        str(r)
        for r in db.execute(
            select(Celula.lider_id).where(
                Celula.ativo.is_(True), Celula.lider_id.is_not(None)
            )
        ).scalars().all()
    }
    candidates = [
        RecipientCandidate(
            telefone=p.telefone,
            tipo=p.tipo,
            optout=p.optout,
            consentimento=p.consentimento,
            lidera_celula=str(p.id) in leader_ids,
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
        repeticao=(
            (payload.agendamento.repeticao or "once")
            if payload.agendamento
            else "once"
        ),
        ignorados_optout=audience.ignored_optout,
        proxima_execucao=next_execution,
    )

    # Zero cleared reach -> blocked (e.g. everyone opted out). RF-38.
    if audience.reach == 0:
        broadcast.alcance = 0
        broadcast.status = "rascunho"
        broadcast.proxima_execucao = None
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
            alcancePrevisto=0,
        )

    # Immediate sends require a currently online official instance in both
    # rollout modes. Scheduled sends may wait for a later reconnection.
    instance: str | None = None
    if payload.modo == "agora":
        instance = _instance(db, igreja_uuid)
        if instance is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Nenhum número oficial conectado. Reconecte o WhatsApp.",
            )

    if async_enabled:
        broadcast.alcance = audience.reach
        broadcast.status = "agendado"
        db.add(broadcast)
        db.flush()
        db.refresh(broadcast)
        db.commit()
        response.status_code = status.HTTP_202_ACCEPTED
        return BroadcastResponse(
            id=str(broadcast.id),
            status="agendado" if payload.modo == "agendado" else "enfileirado",
            enviados=0,
            ignoradosOptout=audience.ignored_optout,
            agendadoPara=(scheduled_for if payload.modo == "agendado" else None),
            execucaoId=None,
            alcancePrevisto=audience.reach,
        )

    # ponytail: fallback de rollout — remover em BROADCAST-FLAG-CLEANUP-1.
    # With the async flag off, modo=agora preserves the existing synchronous
    # response contract until the dedicated worker is activated.
    sent = 0
    for phone in audience.recipients:
        try:
            evolution.send_text(instance, phone, payload.mensagem)
            sent += 1
        except EvolutionError:
            logger.warning("Broadcast send failed to a recipient")

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
        alcancePrevisto=audience.reach,
    )
