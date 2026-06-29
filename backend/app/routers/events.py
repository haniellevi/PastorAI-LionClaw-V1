"""Events router — church events mirrored to Google Calendar (RF-39).

Endpoints:
  - GET  /events   paginated events (RNF-09)
  - POST /events   create an event and try to sync it to Google Calendar

On POST, sync to Google Calendar is best-effort: a sync failure does NOT fail
the request — the event is persisted with `google_event_id=null` and the
response sets `sincronizado=false` so the panel can flag it for retry.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid

from fastapi import APIRouter, Depends
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
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not _HORA_RE.match(value):
            raise ValueError("hora deve estar no formato HH:MM (24h)")
        return value


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
    current_user: CurrentUser = Depends(require_role(["pastor", "lider_g12"])),
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
