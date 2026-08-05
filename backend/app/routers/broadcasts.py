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
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    Broadcast,
    BroadcastEntrega,
    BroadcastExecucao,
    Celula,
    Pessoa,
    WhatsappConnection,
)
from app.db.session import get_db
from app.deps import CurrentUser, require_screen
from app.routers._common import Page, PaginationParams
from app.services.broadcast_delivery import (
    materialize_immediate_broadcast,
    execution_result_status,
    resolve_recipient_snapshot,
    scheduled_instant,
    utc_now,
)
from app.services.broadcast_health import broadcast_worker_ready

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
    resultadoUltimaExecucao: str | None = None  # noqa: N815
    entregasAceitas: int = 0  # noqa: N815
    entregasFalhas: int = 0  # noqa: N815
    entregasDesconhecidas: int = 0  # noqa: N815
    entregasSuprimidas: int = 0  # noqa: N815
    entregasPendentes: int = 0  # noqa: N815

    @classmethod
    def from_model(
        cls, b: Broadcast, summary: dict[str, int | str] | None = None
    ) -> "BroadcastOut":
        result = summary or {}
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
            precisaRevisao=(
                b.modo == "agendado"
                and b.status == "agendado"
                and b.proxima_execucao is None
                and not result
            ),
            resultadoUltimaExecucao=(
                str(result["resultado"]) if result.get("resultado") else None
            ),
            entregasAceitas=int(result.get("aceito", 0)),
            entregasFalhas=int(result.get("falhou_permanente", 0)),
            entregasDesconhecidas=int(result.get("desconhecido", 0)),
            entregasSuprimidas=int(result.get("suprimido", 0)),
            entregasPendentes=int(result.get("pendente", 0)),
        )


def _latest_delivery_summaries(
    db: Session, broadcast_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int | str]]:
    if not broadcast_ids:
        return {}
    execution_rows = db.execute(
        select(BroadcastExecucao.broadcast_id, BroadcastExecucao.id)
        .where(BroadcastExecucao.broadcast_id.in_(broadcast_ids))
        .order_by(BroadcastExecucao.broadcast_id, BroadcastExecucao.seq.desc())
    ).all()
    latest: dict[uuid.UUID, uuid.UUID] = {}
    for broadcast_id, execution_id in execution_rows:
        latest.setdefault(broadcast_id, execution_id)
    if not latest:
        return {}

    counts_by_execution: dict[uuid.UUID, dict[str, int]] = {}
    count_rows = db.execute(
        select(
            BroadcastEntrega.execucao_id,
            BroadcastEntrega.status,
            func.count(),
        )
        .where(BroadcastEntrega.execucao_id.in_(list(latest.values())))
        .group_by(BroadcastEntrega.execucao_id, BroadcastEntrega.status)
    ).all()
    for execution_id, delivery_status, count in count_rows:
        counts_by_execution.setdefault(execution_id, {})[delivery_status] = int(count)

    summaries: dict[uuid.UUID, dict[str, int | str]] = {}
    for broadcast_id, execution_id in latest.items():
        counts = counts_by_execution.get(execution_id, {})
        pending = sum(
            counts.get(key, 0)
            for key in ("pendente", "em_envio", "falhou_retentavel")
        )
        summaries[broadcast_id] = {
            **counts,
            "pendente": pending,
            "resultado": (
                "processando" if pending else execution_result_status(counts)
            ),
        }
    return summaries


def _instance(db: Session, igreja_id: uuid.UUID) -> str | None:
    conn = db.execute(
        select(WhatsappConnection).where(WhatsappConnection.igreja_id == igreja_id)
    ).scalar_one_or_none()
    if conn is None or conn.status != "online" or not conn.instance:
        return None
    return conn.instance


def _rollout_state() -> tuple[bool, bool, bool]:
    """Return async/outbound gates plus a fresh worker heartbeat."""
    settings = get_settings()
    async_enabled = bool(getattr(settings, "broadcast_async_enabled", False))
    sends_enabled = bool(getattr(settings, "external_sends_enabled", False))
    return (
        async_enabled,
        sends_enabled,
        (
            broadcast_worker_ready(str(getattr(settings, "redis_url", "") or ""))
            if async_enabled and sends_enabled
            else False
        ),
    )


def _scheduled_for(agendamento: ScheduleIn | None) -> str | None:
    if agendamento is None:
        return None
    if agendamento.hora:
        return f"{agendamento.data.isoformat()}T{agendamento.hora}"
    return agendamento.data.isoformat()


def _stored_schedule(broadcast: Broadcast) -> str | None:
    if broadcast.modo != "agendado" or broadcast.data is None:
        return None
    if broadcast.hora:
        return f"{broadcast.data.isoformat()}T{broadcast.hora}"
    return broadcast.data.isoformat()


def _idempotent_response(db: Session, broadcast: Broadcast) -> BroadcastResponse:
    execution_id = db.execute(
        select(BroadcastExecucao.id)
        .where(BroadcastExecucao.broadcast_id == broadcast.id)
        .order_by(BroadcastExecucao.seq.desc())
        .limit(1)
    ).scalar_one_or_none()
    counts: dict[str, int] = {}
    if execution_id is not None:
        counts = {
            delivery_status: int(count)
            for delivery_status, count in db.execute(
                select(BroadcastEntrega.status, func.count())
                .where(BroadcastEntrega.execucao_id == execution_id)
                .group_by(BroadcastEntrega.status)
            ).all()
        }
    pending = sum(
        counts.get(key, 0)
        for key in ("pendente", "em_envio", "falhou_retentavel")
    )
    if broadcast.status == "rascunho":
        api_status = "bloqueado"
    elif broadcast.modo == "agendado" and broadcast.status == "agendado":
        api_status = "agendado"
    elif pending:
        api_status = "enfileirado"
    elif execution_id is not None:
        api_status = execution_result_status(counts)
    else:
        api_status = broadcast.status or "enfileirado"
    return BroadcastResponse(
        id=str(broadcast.id),
        status=api_status,
        enviados=counts.get("aceito", 0),
        ignoradosOptout=broadcast.ignorados_optout or 0,
        agendadoPara=_stored_schedule(broadcast),
        execucaoId=str(execution_id) if execution_id else None,
        alcancePrevisto=broadcast.alcance,
    )


def _same_idempotent_request(
    existing: Broadcast, payload: CreateBroadcastRequest
) -> bool:
    schedule = payload.agendamento
    return (
        existing.titulo == payload.titulo
        and existing.mensagem == payload.mensagem
        and list(existing.segmentos or []) == payload.segmentos
        and existing.modo == payload.modo
        and existing.data == (schedule.data if schedule else None)
        and existing.hora == (schedule.hora if schedule else None)
        and (existing.repeticao or "once")
        == ((schedule.repeticao or "once") if schedule else "once")
    )


def _reject_idempotency_conflict(
    existing: Broadcast, payload: CreateBroadcastRequest
) -> None:
    if not _same_idempotent_request(existing, payload):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key já foi usada por outro comunicado.",
        )


def _flush_or_find_existing(db: Session, broadcast: Broadcast) -> Broadcast | None:
    db.add(broadcast)
    try:
        db.flush()
        return None
    except IntegrityError:
        db.rollback()
        if not broadcast.idempotency_key:
            raise
        existing = db.execute(
            select(Broadcast).where(
                Broadcast.igreja_id == broadcast.igreja_id,
                Broadcast.idempotency_key == broadcast.idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is None:
            raise
        return existing


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
    summaries = _latest_delivery_summaries(db, [row.id for row in rows])
    return Page[BroadcastOut](
        items=[BroadcastOut.from_model(b, summaries.get(b.id)) for b in rows],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=total,
    )


@router.get("/capabilities", response_model=BroadcastCapabilities)
def broadcast_capabilities(
    current_user: CurrentUser = Depends(require_screen("comunicados")),
) -> BroadcastCapabilities:
    """Expose the backend rollout gate as the single UI source of truth."""
    async_enabled, sends_enabled, worker_ready = _rollout_state()
    enabled = async_enabled and sends_enabled and worker_ready
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
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_screen("comunicados")),
) -> BroadcastResponse:
    """Resolve the audience (honoring opt-out) and send or schedule it.

    - Opt-out / no-consent people are excluded and counted (RF-38).
    - Archived people are excluded and NOT counted as opt-out (W3).
    - Zero cleared reach blocks the send (recorded as rascunho, enviados=0).
    - modo=agora sends now; modo=agendado stores the schedule (agendadoPara).
    """
    async_enabled, sends_enabled, worker_ready = _rollout_state()
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    normalized_idempotency_key: str | None = None
    if async_enabled:
        normalized_idempotency_key = (idempotency_key or "").strip()
        if not normalized_idempotency_key or len(normalized_idempotency_key) > 128:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency-Key é obrigatório e deve ter até 128 caracteres.",
            )
        existing = db.execute(
            select(Broadcast).where(
                Broadcast.igreja_id == igreja_uuid,
                Broadcast.idempotency_key == normalized_idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            _reject_idempotency_conflict(existing, payload)
            response.status_code = (
                status.HTTP_202_ACCEPTED
                if existing.status == "agendado"
                else status.HTTP_200_OK
            )
            return _idempotent_response(db, existing)
    if not sends_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Envios externos ainda não habilitados.",
        )
    if not async_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Despacho seguro de comunicados ainda não habilitado.",
        )
    if async_enabled and not worker_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker de comunicados indisponível.",
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

    # Pessoa arquivada (W3) está FORA da audiência: não recebe e não conta como
    # opt-out — ela nem chega a ser candidata. `arquivada_em IS NULL` = ativa
    # (ver models.Pessoa). O escopo por tenant continua vindo da RLS.
    people = db.execute(
        select(Pessoa).where(Pessoa.arquivada_em.is_(None))
    ).scalars().all()
    # Segmento "lider" é derivado: quem lidera célula ATIVA (celulas.lider_id),
    # não o tipo manual (regra 2026-07-06).
    leader_ids = {
        r
        for r in db.execute(
            select(Celula.lider_id).where(
                Celula.ativo.is_(True), Celula.lider_id.is_not(None)
            )
        ).scalars().all()
    }
    audience = resolve_recipient_snapshot(people, leader_ids, payload.segmentos)

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
        idempotency_key=normalized_idempotency_key,
        proxima_execucao=next_execution,
    )

    # Zero cleared reach -> blocked (e.g. everyone opted out). RF-38.
    if audience.reach == 0:
        broadcast.alcance = 0
        broadcast.status = "rascunho"
        broadcast.proxima_execucao = None
        existing = _flush_or_find_existing(db, broadcast)
        if existing is not None:
            _reject_idempotency_conflict(existing, payload)
            response.status_code = status.HTTP_200_OK
            return _idempotent_response(db, existing)
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

    broadcast.alcance = audience.reach
    broadcast.status = "agendado"
    existing = _flush_or_find_existing(db, broadcast)
    if existing is not None:
        _reject_idempotency_conflict(existing, payload)
        response.status_code = (
            status.HTTP_202_ACCEPTED
            if existing.status == "agendado"
            else status.HTTP_200_OK
        )
        return _idempotent_response(db, existing)
    execution_id: uuid.UUID | None = None
    if payload.modo == "agora":
        execution_id = materialize_immediate_broadcast(
            db,
            broadcast,
            audience.recipients,
            now=now,
        )
    db.refresh(broadcast)
    db.commit()
    response.status_code = status.HTTP_202_ACCEPTED
    return BroadcastResponse(
        id=str(broadcast.id),
        status="agendado" if payload.modo == "agendado" else "enfileirado",
        enviados=0,
        ignoradosOptout=audience.ignored_optout,
        agendadoPara=(scheduled_for if payload.modo == "agendado" else None),
        execucaoId=str(execution_id) if execution_id else None,
        alcancePrevisto=audience.reach,
    )
