"""Bounded, server-side V2a agenda projections for privileged WhatsApp turns.

Only a small institutional projection leaves this service. Event descriptions,
event messages, contacts and identifiers never enter a reply or routing prompt.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import unicodedata
import uuid
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import case, exists, false, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import AppUser, Event, Message, UserRole
from app.db.rls_observability import require_tenant_scope
from app.db.tenant_session import TenantScopeError
from app.domain.agent_authz import MINISTERIAL_ROLES
from app.services.whatsapp_privilege import privilege_enabled_from_environment

if TYPE_CHECKING:
    from app.services.whatsapp_privilege import PrivilegeContext


AGENDA_WHATSAPP_APPROVED_RELEASE_ID: str | None = None
AGENDA_TIMEZONE = ZoneInfo("America/Sao_Paulo")
AGENDA_PAGE_SIZE = 5
_MAX_DAYS = 30
_MAX_PAGE = 20
_MAX_EVENT_ROWS = 160
_SAFE_TIME = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
_PAGE = re.compile(r"\bp[aá]gina\s*(?P<page>[0-9]{1,9})\b")
_DAYS = re.compile(r"\b(?P<days>[0-9]{1,9})\s*dias?\b")
_AGENDA_REQUEST = re.compile(r"\b(?:agenda|evento(?:s)?|programa[cç][aã]o)\b")
_DRAFT_REQUEST = re.compile(r"\brascunhos?\b")
_PHONE_OR_NUMBER = re.compile(r"\d")
_UNSAFE_TITLE_MARKER = re.compile(
    r"\b(?:rua|avenida|av|travessa|estrada|rodovia|telefone|whatsapp|lider|pastor|contato|http|www)\b",
    re.IGNORECASE,
)
_INSTITUTIONAL_TITLES = MappingProxyType({
    "culto": "Culto",
    "culto de celebracao": "Culto de Celebração",
    "culto especial": "Culto Especial",
    "encontro com deus": "Encontro com Deus",
    "reuniao da igreja": "Reunião da igreja",
    "reuniao de celula": "Reunião de célula",
    "escola de discipulado": "Escola de discipulado",
    "estudo biblico": "Estudo bíblico",
    "santa ceia": "Santa Ceia",
})
_SAFE_TYPE_LABELS = MappingProxyType({
    "culto": "Culto",
    "reuniao": "Reunião da igreja",
    "celula": "Encontro de célula",
    "especial": "Evento especial da igreja",
    "conferencia": "Conferência da igreja",
})
_CONFIRMING_ROLES = frozenset({"admin", "pastor"})
_AGENDA_ROLES = frozenset({"membro", "operador", *MINISTERIAL_ROLES})
_DRAFT_ROLES = _CONFIRMING_ROLES
_ACTIVE_OFFER_STATES = frozenset({"preparada", "aceite_aguardando_ancora", "pendente"})


@dataclass(frozen=True, slots=True)
class AgendaQuery:
    days: int
    page: int
    include_drafts: bool


@dataclass(frozen=True, slots=True)
class AgendaOccurrence:
    event_id: uuid.UUID
    date: dt.date
    hour: str | None
    label: str


@dataclass(frozen=True, slots=True)
class AgendaReply:
    response: str
    query: AgendaQuery
    snapshot_sha256: str
    offers_secretary: bool


@dataclass(frozen=True, slots=True)
class _AgendaEvent:
    id: uuid.UUID
    igreja_id: uuid.UUID
    title: object
    event_type: object
    date: object
    hour: object
    recurrence: object
    weekday: object
    human_confirmed: bool
    draft: bool


def agenda_enabled_from_environment(igreja_id: object) -> bool:
    """Require the reviewed V2a release, its UUID allowlist and active S3."""

    if type(igreja_id) is not uuid.UUID or igreja_id.int == 0:
        return False
    if (
        type(AGENDA_WHATSAPP_APPROVED_RELEASE_ID) is not str
        or not AGENDA_WHATSAPP_APPROVED_RELEASE_ID.strip()
        or not privilege_enabled_from_environment(igreja_id)
    ):
        return False
    raw = os.environ.get("AGENDA_WHATSAPP_ENABLED_IGREJA_IDS", "")
    if type(raw) is not str or not raw.strip():
        return False
    pieces = raw.split(",")
    if any(not piece.strip() for piece in pieces):
        return False
    try:
        allowed = tuple(uuid.UUID(piece.strip()) for piece in pieces)
    except ValueError:
        return False
    return len(allowed) == len(set(allowed)) and igreja_id in allowed


def _plain_text(value: object) -> str | None:
    if type(value) is not str or not value or len(value) > 120:
        return None
    if any(unicodedata.category(char) == "Cc" for char in value):
        return None
    cleaned = "".join(
        " " if char in "<>[]{}()|" else char
        for char in value
        if unicodedata.category(char) != "Cf"
    )
    cleaned = " ".join(cleaned.split())
    return cleaned if cleaned and len(cleaned) <= 120 else None


def _title_key(value: str) -> str | None:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    if _PHONE_OR_NUMBER.search(normalized) or _UNSAFE_TITLE_MARKER.search(normalized):
        return None
    if not re.fullmatch(r"[a-zà-ÿ ]+", normalized):
        return None
    return " ".join(normalized.split()) or None


def project_institutional_title(value: object) -> str | None:
    """Project only a narrow institutional title grammar.

    This is not a detector for names or addresses. A title is shown only when
    every word is in the institutional grammar; uncertain legacy titles fall
    back to the event type.
    """

    cleaned = _plain_text(value)
    if cleaned is None:
        return None
    key = _title_key(cleaned)
    return _INSTITUTIONAL_TITLES.get(key) if key is not None else None


def _project_event_type(value: object) -> str:
    if type(value) is not str:
        return "Evento da igreja"
    normalized = unicodedata.normalize("NFKD", value).casefold()
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return _SAFE_TYPE_LABELS.get(normalized, "Evento da igreja")


def parse_agenda_query(value: object) -> AgendaQuery | None:
    """Parse only bounded period/page controls from an anchored agenda request."""

    if type(value) is not str or len(value) > 1200:
        return None
    normalized = unicodedata.normalize("NFKD", value).casefold()
    normalized = "".join(
        char for char in normalized
        if not unicodedata.combining(char) and unicodedata.category(char) != "Cf"
    )
    normalized = " ".join(normalized.split())
    if not normalized or _AGENDA_REQUEST.search(normalized) is None:
        return None
    days = 7
    day_match = _DAYS.search(normalized)
    if day_match is not None:
        days = int(day_match.group("days"))
        if not 1 <= days <= _MAX_DAYS:
            return None
    page = 1
    page_match = _PAGE.search(normalized)
    if page_match is not None:
        page = int(page_match.group("page"))
        if not 1 <= page <= _MAX_PAGE:
            return None
    return AgendaQuery(days=days, page=page, include_drafts=bool(_DRAFT_REQUEST.search(normalized)))


def _safe_date(value: object) -> dt.date | None:
    return value if type(value) is dt.date else None


def _safe_hour(value: object) -> str | None:
    return value if type(value) is str and _SAFE_TIME.fullmatch(value) else None


def _event_weekday(value: dt.date) -> int:
    """Event uses Sunday=0, unlike Python's Monday=0."""

    return (value.weekday() + 1) % 7


def occurrences_for_event(
    event: object,
    *,
    start: dt.date,
    end: dt.date,
) -> tuple[AgendaOccurrence, ...]:
    """Expand one safe event without reading description or event messages."""

    if type(start) is not dt.date or type(end) is not dt.date or end < start:
        return ()
    event_id = getattr(event, "id", None)
    event_tenant = getattr(event, "igreja_id", None)
    if type(event_id) is not uuid.UUID or type(event_tenant) is not uuid.UUID:
        return ()
    label = None
    if getattr(event, "human_confirmed", False) is True:
        label = project_institutional_title(getattr(event, "title", getattr(event, "titulo", None)))
    if label is None:
        label = _project_event_type(getattr(event, "event_type", getattr(event, "tipo", None)))
    hour = _safe_hour(getattr(event, "hour", getattr(event, "hora", None)))
    recurrence = getattr(event, "recurrence", getattr(event, "recorrencia", None))
    event_date = _safe_date(getattr(event, "date", getattr(event, "data", None)))
    if recurrence == "pontual":
        if event_date is None or not start <= event_date <= end:
            return ()
        return (AgendaOccurrence(event_id, event_date, hour, label),)
    if recurrence != "semanal":
        return ()
    weekday = getattr(event, "weekday", getattr(event, "dia_semana", None))
    if type(weekday) is not int or type(weekday) is bool or not 0 <= weekday <= 6:
        return ()
    series_start = max(start, event_date) if event_date is not None else start
    first = series_start + dt.timedelta(days=(weekday - _event_weekday(series_start)) % 7)
    if first > end:
        return ()
    result: list[AgendaOccurrence] = []
    current = first
    while current <= end:
        result.append(AgendaOccurrence(event_id, current, hour, label))
        current += dt.timedelta(days=7)
    return tuple(result)


def _roles(context: object) -> frozenset[str]:
    roles = getattr(context, "roles", None)
    if type(roles) is not frozenset or any(type(role) is not str for role in roles):
        return frozenset()
    return roles


def agenda_read_allowed(context: object) -> bool:
    return bool(_roles(context) & _AGENDA_ROLES)


def agenda_draft_role_allowed(context: object) -> bool:
    """Only pastors and admins may begin the Clerk proof path for drafts."""

    return bool(_roles(context) & _DRAFT_ROLES)


def agenda_drafts_allowed(context: object) -> bool:
    return (
        agenda_draft_role_allowed(context)
        and bool(getattr(context, "sensitive", False))
        and type(getattr(context, "proof_id", None)) is uuid.UUID
    )


def _confirmed_by_human_predicate():
    active_author = exists(
        select(AppUser.id).where(
            AppUser.id == Event.confirmado_por,
            AppUser.igreja_id == Event.igreja_id,
            AppUser.status == "ativo",
            AppUser.clerk_user_id.is_not(None),
            func.length(func.btrim(AppUser.clerk_user_id)) > 0,
        )
    )
    authorized_role = exists(
        select(UserRole.id).where(
            UserRole.igreja_id == Event.igreja_id,
            UserRole.user_id == Event.confirmado_por,
            UserRole.papel.in_(tuple(sorted(_CONFIRMING_ROLES))),
        )
    )
    return (
        Event.confirmado_em.is_not(None)
        & (Event.confirmado_em <= func.clock_timestamp())
        & active_author
        & authorized_role
    )


def _query_rows(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    query: AgendaQuery,
    start: dt.date,
    end: dt.date,
) -> tuple[_AgendaEvent, ...] | None:
    status_filters: tuple[object, ...]
    if query.include_drafts:
        status_filters = (Event.status == "a_confirmar",)
        human_confirmed = false()
    else:
        status_filters = (Event.status == "confirmado",)
        human_confirmed = case((_confirmed_by_human_predicate(), True), else_=False)
    statement = (
        select(
            Event.id,
            Event.igreja_id,
            Event.titulo,
            Event.tipo,
            Event.data,
            Event.hora,
            Event.recorrencia,
            Event.dia_semana,
            human_confirmed.label("human_confirmed"),
        )
        .where(
            Event.igreja_id == igreja_id,
            *status_filters,
            or_(
                Event.recorrencia == "semanal",
                (Event.recorrencia == "pontual") & (Event.data >= start) & (Event.data <= end),
            ),
            or_(Event.data.is_(None), Event.data <= end),
        )
        .order_by(Event.data.asc().nullsfirst(), Event.id.asc())
        .limit(_MAX_EVENT_ROWS + 1)
    )
    rows = session.execute(statement).all()
    if len(rows) > _MAX_EVENT_ROWS:
        return None
    result: list[_AgendaEvent] = []
    for row in rows:
        try:
            event_id, tenant, title, event_type, date, hour, recurrence, weekday, confirmed = row
        except (TypeError, ValueError):
            continue
        if type(event_id) is not uuid.UUID or tenant != igreja_id:
            continue
        result.append(_AgendaEvent(
            event_id,
            tenant,
            title,
            event_type,
            date,
            hour,
            recurrence,
            weekday,
            confirmed is True,
            query.include_drafts,
        ))
    return tuple(result)


def _snapshot(query: AgendaQuery, occurrences: Iterable[AgendaOccurrence]) -> str:
    payload = {
        "days": query.days,
        "page": query.page,
        "include_drafts": query.include_drafts,
        "occurrences": [
            {
                "event_id": str(item.event_id),
                "date": item.date.isoformat(),
                "hour": item.hour,
                "label": item.label,
            }
            for item in occurrences
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _response(query: AgendaQuery, occurrences: tuple[AgendaOccurrence, ...], *, start: dt.date, end: dt.date) -> str:
    period = f"Período: {start:%d/%m/%Y} a {end:%d/%m/%Y}, página {query.page}."
    if not occurrences:
        return f"{period} Não tenho essa informação cadastrada. Quer falar com a secretaria da igreja?"
    lines = []
    for occurrence in occurrences:
        when = (
            f"{occurrence.date:%d/%m/%Y} às {occurrence.hour}"
            if occurrence.hour is not None
            else f"{occurrence.date:%d/%m/%Y}, horário não cadastrado"
        )
        lines.append(f"{occurrence.label} — {when}.")
    return f"{period} Agenda: " + " ".join(lines)


def resolve_agenda_reply(
    session: Session,
    *,
    context: object,
    text: object,
    now: dt.datetime | None = None,
) -> AgendaReply | None:
    """Resolve a selected agenda query from a bounded server-side projection."""

    from app.services.whatsapp_privilege import PrivilegeContext

    query = parse_agenda_query(text)
    igreja_id = getattr(context, "igreja_id", None)
    if (
        query is None
        or type(context) is not PrivilegeContext
        or type(igreja_id) is not uuid.UUID
        or not agenda_enabled_from_environment(igreja_id)
        or not agenda_read_allowed(context)
    ):
        return None
    try:
        require_tenant_scope(
            session,
            expected_igreja_id=igreja_id,
            source="whatsapp_agenda",
        )
    except (TenantScopeError, ValueError):
        return None
    if query.include_drafts and not agenda_drafts_allowed(context):
        return None
    observed = now or dt.datetime.now(AGENDA_TIMEZONE)
    if type(observed) is not dt.datetime or observed.tzinfo is None:
        return None
    start = observed.astimezone(AGENDA_TIMEZONE).date()
    end = start + dt.timedelta(days=query.days - 1)
    rows = _query_rows(session, igreja_id=igreja_id, query=query, start=start, end=end)
    if rows is None:
        return None
    occurrences: list[AgendaOccurrence] = []
    for event in rows:
        occurrences.extend(occurrences_for_event(event, start=start, end=end))
    local_now = observed.astimezone(AGENDA_TIMEZONE)
    now_minutes = local_now.hour * 60 + local_now.minute
    occurrences = [
        item
        for item in occurrences
        if (
            item.date != start
            or item.hour is None
            or int(item.hour[:2]) * 60 + int(item.hour[3:]) > now_minutes
        )
    ]
    occurrences.sort(key=lambda item: (item.date, item.hour or "", item.label, item.event_id.hex))
    first = (query.page - 1) * AGENDA_PAGE_SIZE
    page = tuple(occurrences[first:first + AGENDA_PAGE_SIZE])
    if query.include_drafts:
        page = tuple(
            AgendaOccurrence(item.event_id, item.date, item.hour, f"Rascunho: {item.label}")
            for item in page
        )
    return AgendaReply(
        response=_response(query, page, start=start, end=end),
        query=query,
        snapshot_sha256=_snapshot(query, page),
        offers_secretary=not bool(page),
    )


def agenda_reply_metadata(reply: AgendaReply) -> dict[str, object]:
    return {
        "days": reply.query.days,
        "page": reply.query.page,
        "include_drafts": reply.query.include_drafts,
        "snapshot_sha256": reply.snapshot_sha256,
    }


def valid_agenda_reply_metadata(raw: object) -> bool:
    if type(raw) is not dict or set(raw) != {"agenda"} or type(raw["agenda"]) is not dict:
        return False
    agenda = raw["agenda"]
    if set(agenda) != {"days", "page", "include_drafts", "snapshot_sha256"}:
        return False
    return (
        type(agenda["days"]) is int
        and 1 <= agenda["days"] <= _MAX_DAYS
        and type(agenda["page"]) is int
        and 1 <= agenda["page"] <= _MAX_PAGE
        and type(agenda["include_drafts"]) is bool
        and type(agenda["snapshot_sha256"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", agenda["snapshot_sha256"]) is not None
    )


def agenda_reply_still_authorized(
    session: Session,
    *,
    message: Message,
    conversation: object,
    context: object,
) -> bool:
    """Re-query the exact anchored request and compare its safe snapshot."""

    raw = getattr(message, "agent_privilege_context", None)
    if type(raw) is not dict:
        return False
    metadata = {"agenda": raw.get("agenda")}
    if not valid_agenda_reply_metadata(metadata):
        return False
    try:
        inbound_id = uuid.UUID(raw["inbound_message_id"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    if (
        getattr(context, "igreja_id", None) != message.igreja_id
        or getattr(context, "conversation_id", None) != message.conversation_id
        or getattr(context, "inbound_message_id", None) != inbound_id
    ):
        return False
    source = session.execute(
        select(Message.texto).where(
            Message.id == inbound_id,
            Message.igreja_id == message.igreja_id,
            Message.conversation_id == message.conversation_id,
            Message.direcao == "in",
        )
    ).scalar_one_or_none()
    reply = resolve_agenda_reply(session, context=context, text=source)
    agenda = metadata["agenda"]
    if reply is None or agenda_reply_metadata(reply) != agenda or message.texto != reply.response:
        return False
    if reply.offers_secretary:
        return (
            getattr(conversation, "secretaria_oferta_message_id", None) == message.id
            and getattr(conversation, "secretaria_oferta_estado", None) in _ACTIVE_OFFER_STATES
        )
    return True
