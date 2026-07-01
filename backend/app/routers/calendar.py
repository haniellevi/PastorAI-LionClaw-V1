"""Calendar router — connect a church's existing Google Calendar (events F1).

OAuth web flow (offline → refresh_token). The connect/status/list/select/
disconnect endpoints are admin-only and tenant-scoped; the callback is PUBLIC
(a redirect from Google) and attributes the consent via a signed ``state`` —
so it writes scoped strictly by the igreja_id carried in that state.

Tokens are stored encrypted at rest (reusing the BYO-credential crypto). The
key never leaves the server; status/list never echo it.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import CalendarSync, Event
from app.db.session import get_db
from app.deps import CurrentUser, require_role
from app.routers._common import ensure_tenant_context
from app.services.crypto import SecretDecryptionError, decrypt_secret, encrypt_secret
from app.services.google_oauth import (
    GoogleOAuthClient,
    GoogleOAuthError,
    get_google_oauth_client,
)

logger = logging.getLogger("pastorai.calendar")

router = APIRouter(prefix="/calendar", tags=["calendar"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ConnectUrlOut(BaseModel):
    authUrl: str  # noqa: N815 - external contract camelCase


class StatusOut(BaseModel):
    connected: bool
    calendarId: str | None = None  # noqa: N815


class CalendarItem(BaseModel):
    id: str
    summary: str | None = None
    primary: bool = False


class CalendarListOut(BaseModel):
    calendars: list[CalendarItem]


class SelectCalendarRequest(BaseModel):
    calendarId: str = Field(min_length=1, max_length=300)  # noqa: N815


class PreviewEventItem(BaseModel):
    googleEventId: str  # noqa: N815
    titulo: str | None = None
    descricao: str | None = None
    data: str | None = None  # YYYY-MM-DD
    hora: str | None = None  # HH:MM (None for all-day)
    fim: str | None = None  # HH:MM end (None for all-day / unset)
    recorrente: bool = False


class ImportPreviewOut(BaseModel):
    calendarId: str  # noqa: N815
    events: list[PreviewEventItem]


# EVT-6 PR6.2 — eventos importados do Google nascem pendentes de confirmação,
# marcados como origem Google e tratados como pontuais (têm data específica).
_IMPORT_STATUS = "a_confirmar"
_IMPORT_ORIGEM = "google"
_IMPORT_RECORRENCIA = "pontual"


class ImportResultItem(BaseModel):
    id: str
    googleEventId: str  # noqa: N815
    titulo: str


class ImportResultOut(BaseModel):
    created: int
    skipped: int
    events: list[ImportResultItem]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sync_for(db: Session, igreja_id: uuid.UUID) -> CalendarSync | None:
    return db.execute(
        select(CalendarSync).where(CalendarSync.igreja_id == igreja_id)
    ).scalar_one_or_none()


def _connected(sync: CalendarSync | None) -> bool:
    return sync is not None and bool(sync.refresh_token_encrypted)


def _parse_date(value: str | None) -> dt.date | None:
    """Parse a preview ``'YYYY-MM-DD'`` into a date, or None when absent/invalid."""
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _valid_access_token(
    db: Session, sync: CalendarSync, oauth: GoogleOAuthClient
) -> str:
    """Return a usable access token, refreshing it when missing/expired."""
    now = dt.datetime.now(dt.timezone.utc)
    if (
        sync.access_token_encrypted
        and sync.access_token_expira_em
        and sync.access_token_expira_em > now + dt.timedelta(seconds=60)
    ):
        try:
            return decrypt_secret(sync.access_token_encrypted)
        except SecretDecryptionError:
            pass  # fall through to a refresh
    if not sync.refresh_token_encrypted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Agenda não conectada"
        )
    try:
        refresh = decrypt_secret(sync.refresh_token_encrypted)
    except SecretDecryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reconecte a agenda do Google",
        ) from exc
    try:
        tokens = oauth.refresh_access_token(refresh)
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    sync.access_token_encrypted = encrypt_secret(tokens.access_token)
    sync.access_token_expira_em = now + dt.timedelta(seconds=tokens.expires_in)
    sync.atualizado_em = now
    db.commit()
    return tokens.access_token


# ---------------------------------------------------------------------------
# Endpoints (admin only, tenant-scoped) — except the public callback
# ---------------------------------------------------------------------------
@router.get("/connect", response_model=ConnectUrlOut)
def connect(
    current_user: CurrentUser = Depends(require_role(["admin"])),
    oauth: GoogleOAuthClient = Depends(get_google_oauth_client),
) -> ConnectUrlOut:
    """Return the Google consent URL to connect the igreja's calendar."""
    try:
        url = oauth.build_consent_url(current_user.igreja_id)
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return ConnectUrlOut(authUrl=url)


@router.get("/callback")
def callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    db: Session = Depends(get_db),
    oauth: GoogleOAuthClient = Depends(get_google_oauth_client),
) -> RedirectResponse:
    """Public OAuth callback. Stores tokens for the igreja named in `state`.

    No session here (Google redirects the browser), so the tenant is taken from
    the signed `state` and the write is scoped strictly to that igreja_id.
    """
    frontend = get_settings().frontend_url.rstrip("/")
    try:
        igreja_id = uuid.UUID(oauth.verify_state(state))
        tokens = oauth.exchange_code(code)
    except (GoogleOAuthError, ValueError):
        logger.warning("Google OAuth callback rejected (state/code)")
        return RedirectResponse(url=f"{frontend}/#calendario")

    now = dt.datetime.now(dt.timezone.utc)
    sync = _sync_for(db, igreja_id)
    if sync is None:
        sync = CalendarSync(igreja_id=igreja_id)
        db.add(sync)
    if tokens.refresh_token:
        sync.refresh_token_encrypted = encrypt_secret(tokens.refresh_token)
    sync.access_token_encrypted = encrypt_secret(tokens.access_token)
    sync.access_token_expira_em = now + dt.timedelta(seconds=tokens.expires_in)
    sync.atualizado_em = now
    db.commit()
    logger.info("Google Calendar connected for an igreja")
    return RedirectResponse(url=f"{frontend}/#calendario")


@router.get("/status", response_model=StatusOut)
def get_status(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> StatusOut:
    """Whether the igreja has a connected calendar (no secret echoed)."""
    ensure_tenant_context(db, current_user)
    sync = _sync_for(db, uuid.UUID(current_user.igreja_id))
    if not _connected(sync):
        return StatusOut(connected=False)
    return StatusOut(connected=True, calendarId=sync.google_calendar_id)


@router.get("/list", response_model=CalendarListOut)
def list_calendars(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
    oauth: GoogleOAuthClient = Depends(get_google_oauth_client),
) -> CalendarListOut:
    """List the connected account's calendars so the admin can pick one."""
    ensure_tenant_context(db, current_user)
    sync = _sync_for(db, uuid.UUID(current_user.igreja_id))
    if not _connected(sync):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Agenda não conectada"
        )
    token = _valid_access_token(db, sync, oauth)
    try:
        cals = oauth.list_calendars(token)
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return CalendarListOut(calendars=[CalendarItem(**c) for c in cals])


@router.get("/import/preview", response_model=ImportPreviewOut)
def import_preview(
    timeMin: str | None = Query(default=None),  # noqa: N803 - external camelCase
    timeMax: str | None = Query(default=None),  # noqa: N803
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["pastor"])),
    oauth: GoogleOAuthClient = Depends(get_google_oauth_client),
) -> ImportPreviewOut:
    """Read-only preview of the igreja's Google Calendar events (EVT-6 PR6.1).

    Lists events using the per-igreja OAuth token (``calendar_sync``); nothing is
    written to ``events``. Defaults to a safe forward window (now → +90d) when
    the range is omitted. 409 when the igreja has no calendar connected.
    """
    ensure_tenant_context(db, current_user)
    sync = _sync_for(db, uuid.UUID(current_user.igreja_id))
    if not _connected(sync):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Agenda não conectada"
        )
    now = dt.datetime.now(dt.timezone.utc)
    time_min = timeMin or now.isoformat()
    time_max = timeMax or (now + dt.timedelta(days=90)).isoformat()
    token = _valid_access_token(db, sync, oauth)
    # ponytail: default to "primary" when no calendar selected yet — same
    # convention as the legacy client and Google's own default.
    calendar_id = sync.google_calendar_id or "primary"
    try:
        events = oauth.list_events(token, calendar_id, time_min, time_max)
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return ImportPreviewOut(
        calendarId=calendar_id,
        events=[PreviewEventItem(**e) for e in events],
    )


@router.post("/import", response_model=ImportResultOut)
def import_events(
    timeMin: str | None = Query(default=None),  # noqa: N803 - external camelCase
    timeMax: str | None = Query(default=None),  # noqa: N803
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["pastor"])),
    oauth: GoogleOAuthClient = Depends(get_google_oauth_client),
) -> ImportResultOut:
    """Importa eventos do Google como ``a_confirmar`` / ``origem='google'`` (PR6.2).

    Lê o Google **por igreja** (read-only, mesma janela do preview) e **persiste**
    localmente, tenant-scoped, **sem confirmar** e **sem enviar** nada (WhatsApp/
    e-mail só no fluxo de confirmação/worker, não aqui). Dedup **simples em código**
    por ``(igreja_id, google_event_id)`` — o índice único parcial vem no PR6.3.
    Não escreve no Google (só ``events.list``). 409 quando a igreja não está
    conectada; 502 em falha do Google.
    """
    ensure_tenant_context(db, current_user)
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    sync = _sync_for(db, igreja_uuid)
    if not _connected(sync):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Agenda não conectada"
        )
    now = dt.datetime.now(dt.timezone.utc)
    time_min = timeMin or now.isoformat()
    time_max = timeMax or (now + dt.timedelta(days=90)).isoformat()
    token = _valid_access_token(db, sync, oauth)
    calendar_id = sync.google_calendar_id or "primary"
    try:
        previews = oauth.list_events(token, calendar_id, time_min, time_max)
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    # Dedup tenant-scoped: ids já importados NESTA igreja (RLS + filtro igreja_id,
    # defesa em profundidade). Eventos de outro tenant com o mesmo google_event_id
    # não aparecem aqui, então não bloqueiam este tenant.
    candidate_ids = [p["googleEventId"] for p in previews if p.get("googleEventId")]
    seen: set[str] = set()
    if candidate_ids:
        rows = db.execute(
            select(Event.google_event_id).where(
                Event.igreja_id == igreja_uuid,
                Event.google_event_id.in_(candidate_ids),
            )
        ).scalars().all()
        seen.update(r for r in rows if r)

    created: list[Event] = []
    skipped = 0
    for p in previews:
        gid = p.get("googleEventId")
        data = _parse_date(p.get("data"))
        # Pula: sem id Google, já importado (dedup), ou sem data — 'pontual' exige
        # data NOT NULL pela CHECK events_recorrencia_chk (recorrente fica p/ depois).
        if not gid or gid in seen or data is None:
            skipped += 1
            continue
        seen.add(gid)
        event = Event(
            igreja_id=igreja_uuid,
            # ponytail: placeholder se o Google não expõe summary — evita violar
            # events.titulo NOT NULL; o usuário ajusta o título ao confirmar.
            titulo=p.get("titulo") or "(sem título)",
            descricao=p.get("descricao"),
            data=data,
            hora=p.get("hora"),
            google_event_id=gid,
            status=_IMPORT_STATUS,
            origem=_IMPORT_ORIGEM,
            recorrencia=_IMPORT_RECORRENCIA,
        )
        db.add(event)
        created.append(event)

    if created:
        db.flush()
        for event in created:
            db.refresh(event)
    db.commit()

    return ImportResultOut(
        created=len(created),
        skipped=skipped,
        events=[
            ImportResultItem(
                id=str(e.id),
                googleEventId=e.google_event_id or "",
                titulo=e.titulo,
            )
            for e in created
        ],
    )


@router.put("", response_model=StatusOut)
def select_calendar(
    payload: SelectCalendarRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> StatusOut:
    """Set which calendar (id) this igreja syncs with."""
    ensure_tenant_context(db, current_user)
    sync = _sync_for(db, uuid.UUID(current_user.igreja_id))
    if not _connected(sync):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Agenda não conectada"
        )
    sync.google_calendar_id = payload.calendarId
    sync.atualizado_em = dt.datetime.now(dt.timezone.utc)
    db.commit()
    return StatusOut(connected=True, calendarId=sync.google_calendar_id)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> None:
    """Disconnect the igreja's Google Calendar (drops stored tokens)."""
    ensure_tenant_context(db, current_user)
    sync = _sync_for(db, uuid.UUID(current_user.igreja_id))
    if sync is not None:
        db.delete(sync)
        db.commit()
    return None
