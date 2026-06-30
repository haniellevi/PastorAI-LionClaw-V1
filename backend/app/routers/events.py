"""Events router — church events mirrored to Google Calendar (RF-39).

Endpoints:
  - GET    /events              paginated events (RNF-09)
  - POST   /events              create an event and try to sync it to Google
  - GET    /events/{id}         single tenant event or 404 (EVT-2)
  - PUT    /events/{id}         edit a manual tenant event (EVT-2)
  - DELETE /events/{id}         remove a tenant event (EVT-2)
  - POST   /events/{id}/confirm manual confirmation of an 'a_confirmar' event

On POST, sync to Google Calendar is best-effort: a sync failure does NOT fail
the request — the event is persisted with `google_event_id=null` and the
response sets `sincronizado=false` so the panel can flag it for retry.

EVT-2 (CRUD + manual confirmation) is tenant-scoped: every by-id lookup filters
by `igreja_id` on top of RLS, so an event from another tenant is never reachable.
Edit/delete do NOT touch Google Calendar (out of scope, EVT-6+).
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

from app.db.models import Event
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user, require_role
from app.routers._common import Page, PaginationParams, ensure_tenant_context
from app.services.google_calendar import (
    GoogleCalendarClient,
    GoogleCalendarError,
    get_google_calendar_client,
)

logger = logging.getLogger("pastorai.events")

# EVT-1: `hora` é texto livre na coluna; aqui validamos HH:MM (24h) no payload
# para não persistir lixo (espelha a CHECK constraint events_hora_formato_chk).
_HORA_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

# EVT-2 — valores do enum event_status usados na confirmação manual.
STATUS_CONFIRMADO = "confirmado"
STATUS_A_CONFIRMAR = "a_confirmar"


def _normalize_hora(value: str | None) -> str | None:
    """Normaliza/valida `hora` HH:MM (24h); vazio vira None. Reusado nos schemas."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not _HORA_RE.match(value):
        raise ValueError("hora deve estar no formato HH:MM (24h)")
    return value


router = APIRouter(prefix="/events", tags=["events"])


class EventOut(BaseModel):
    id: str
    titulo: str
    # EVT-1: nullable porque eventos semanais (recorrencia='semanal') não têm
    # data específica — espelha events.data, que deixou de ser NOT NULL.
    data: dt.date | None = None
    hora: str | None = None
    descricao: str | None = None
    googleEventId: str | None = None  # noqa: N815
    sincronizado: bool
    # EVT-2: expõe estado da Agenda (aditivo). Optional porque instâncias
    # transientes (server_default só vale no DB) podem ter status=None até o flush.
    status: str | None = None
    origem: str | None = None
    recorrencia: str | None = None
    confirmadoEm: dt.datetime | None = None  # noqa: N815
    confirmadoPor: str | None = None  # noqa: N815

    @classmethod
    def from_model(cls, e: Event) -> "EventOut":
        return cls(
            id=str(e.id),
            titulo=e.titulo,
            data=e.data,
            hora=e.hora,
            descricao=e.descricao,
            googleEventId=e.google_event_id,
            sincronizado=e.google_event_id is not None,
            status=e.status,
            origem=e.origem,
            recorrencia=e.recorrencia,
            confirmadoEm=e.confirmado_em,
            confirmadoPor=str(e.confirmado_por) if e.confirmado_por else None,
        )


class CreateEventRequest(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    data: dt.date
    hora: str | None = Field(default=None, max_length=10)
    descricao: str | None = Field(default=None, max_length=2000)

    @field_validator("titulo")
    @classmethod
    def _titulo(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("titulo obrigatório")
        return value

    @field_validator("hora")
    @classmethod
    def _hora(cls, value: str | None) -> str | None:
        return _normalize_hora(value)


class UpdateEventRequest(BaseModel):
    """Edição parcial de um evento manual (EVT-2). Campos None = inalterados."""

    titulo: str | None = Field(default=None, max_length=200)
    data: dt.date | None = None
    hora: str | None = Field(default=None, max_length=10)
    descricao: str | None = Field(default=None, max_length=2000)

    @field_validator("titulo")
    @classmethod
    def _titulo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("titulo não pode ser vazio")
        return value

    @field_validator("hora")
    @classmethod
    def _hora(cls, value: str | None) -> str | None:
        return _normalize_hora(value)


def _get_event(db: Session, current_user: CurrentUser, event_id: str) -> Event:
    """Busca um evento do tenant por id ou levanta 404.

    Escopo de tenant em dois cintos: a RLS já filtra por igreja_id, e ainda
    adicionamos o predicado explícito `igreja_id` — um evento de outro tenant
    nunca é alcançável, mesmo que o GUC da RLS não estivesse em vigor. Id
    malformado também vira 404 (não vaza diferença entre inválido e inexistente).
    """
    try:
        event_uuid = uuid.UUID(event_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evento não encontrado"
        ) from exc

    event = db.execute(
        select(Event).where(
            Event.id == event_uuid,
            Event.igreja_id == uuid.UUID(current_user.igreja_id),
        )
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evento não encontrado"
        )
    return event


@router.get("", response_model=Page[EventOut])
def list_events(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Page[EventOut]:
    """Return the tenant's events, soonest first (RNF-09)."""
    ensure_tenant_context(db, current_user)
    rows = db.execute(
        select(Event)
        .order_by(Event.data.asc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()
    total = len(db.execute(select(Event.id)).scalars().all())
    return Page[EventOut](
        items=[EventOut.from_model(e) for e in rows],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=total,
    )


@router.post("", response_model=EventOut)
def create_event(
    payload: CreateEventRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["pastor"])),
    gcal: GoogleCalendarClient = Depends(get_google_calendar_client),
) -> EventOut:
    """Create an event and attempt to mirror it to Google Calendar.

    The event is always persisted. If the Google Calendar sync fails (or is not
    configured), the event is saved unsynced and the response reflects that
    instead of erroring.
    """
    ensure_tenant_context(db, current_user)

    google_event_id: str | None = None
    try:
        google_event_id = gcal.create_event(
            titulo=payload.titulo,
            data=payload.data,
            hora=payload.hora,
            descricao=payload.descricao,
        )
    except GoogleCalendarError:
        logger.warning("Event created but Google Calendar sync failed")

    event = Event(
        igreja_id=uuid.UUID(current_user.igreja_id),
        titulo=payload.titulo,
        data=payload.data,
        hora=payload.hora,
        descricao=payload.descricao,
        google_event_id=google_event_id,
    )
    db.add(event)
    db.flush()
    db.refresh(event)
    db.commit()

    return EventOut.from_model(event)


@router.get("/{event_id}", response_model=EventOut)
def get_event(
    event_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> EventOut:
    """Retorna um único evento do tenant ou 404 (RLS + igreja_id).

    Leitura aberta a qualquer usuário autenticado do tenant (como GET /events).
    """
    ensure_tenant_context(db, current_user)
    return EventOut.from_model(_get_event(db, current_user, event_id))


@router.put("/{event_id}", response_model=EventOut)
def update_event(
    event_id: str,
    payload: UpdateEventRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["pastor"])),
) -> EventOut:
    """Edita um evento manual do tenant (pastor/admin).

    Atualização parcial: campos omitidos/None ficam inalterados (espelha
    PATCH /contacts). NÃO re-sincroniza com o Google Calendar — sync na edição é
    escopo de fase posterior (EVT-6+).
    """
    ensure_tenant_context(db, current_user)
    event = _get_event(db, current_user, event_id)

    if payload.titulo is not None:
        event.titulo = payload.titulo
    if payload.data is not None:
        event.data = payload.data
    if payload.hora is not None:
        event.hora = payload.hora
    if payload.descricao is not None:
        event.descricao = payload.descricao

    db.flush()
    db.refresh(event)
    db.commit()
    return EventOut.from_model(event)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["pastor"])),
) -> Response:
    """Remove um evento do tenant (pastor/admin). Tenant-scoped (RLS + igreja_id).

    NÃO remove o evento espelhado no Google Calendar — fora do escopo (EVT-6+).
    """
    ensure_tenant_context(db, current_user)
    event = _get_event(db, current_user, event_id)
    db.delete(event)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{event_id}/confirm", response_model=EventOut)
def confirm_event(
    event_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["pastor"])),
) -> EventOut:
    """Confirmação manual de um evento 'a_confirmar' (pastor/admin).

    Só transita a partir de 'a_confirmar' (estado dos eventos importados do
    Google, EVT-6). Confirmar um evento que não está 'a_confirmar' (já confirmado,
    etc.) retorna 409 — regra explícita e consistente com o uso de 409 para
    conflito de estado no projeto. Em sucesso: status='confirmado', grava
    confirmado_em (UTC) e confirmado_por (app_user atual). Tenant-scoped.
    """
    ensure_tenant_context(db, current_user)
    event = _get_event(db, current_user, event_id)

    if event.status != STATUS_A_CONFIRMAR:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evento não está aguardando confirmação",
        )

    event.status = STATUS_CONFIRMADO
    event.confirmado_em = dt.datetime.now(dt.timezone.utc)
    event.confirmado_por = uuid.UUID(current_user.app_user_id)

    db.flush()
    db.refresh(event)
    db.commit()
    return EventOut.from_model(event)
