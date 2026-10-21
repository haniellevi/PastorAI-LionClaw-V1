"""Closed typed agenda tools; no Google, notifications or editorial confirmation."""
import re
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from app.prayer.catalog import normalized
from app.routers.events import CreateEventRequest, UpdateEventRequest

HELP = ('Agenda local: AGENDA para consultar os próximos 30 dias; '
        'AGENDA criar TÍTULO; AAAA-MM-DD; HH:MM; '
        'AGENDA alterar ID; AAAA-MM-DD; HH:MM; AGENDA cancelar ID. '
        'Criar, alterar data/hora e cancelar exigem pastor/admin e SIM literal. '
        'Cancelar remove o evento local, como no painel. Google, recorrências e avisos exigem o painel.')


class EventTool(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['create', 'update', 'delete']
    event_id: UUID | None = None
    payload: CreateEventRequest | None = None
    snapshot: str | None = None


def route(text, *, pending=False):
    value = ' '.join(normalized(text).split())
    if pending:
        if text.strip().casefold() == 'sim':
            return 'confirm', None
        if value in {'nao', 'cancelar'}:
            return 'cancel', None
    if value == 'agenda':
        return 'list', None
    match = re.fullmatch(r'agenda (criar|alterar) ([^;]+);\s*([^;]+);\s*([^;]+)', value)
    if match:
        # Preserve spelling of titles, but never accept identities from a model.
        args = tuple(p.strip() for p in ' '.join(text.split()).split(' ', 2)[2].split(';'))
        return ('create' if match[1] == 'criar' else 'update'), args
    match = re.fullmatch(r'agenda cancelar ([0-9a-f-]{36})', value)
    if match:
        return 'delete', match[1]
    if re.match(r'^agenda (?:criar|alterar|cancelar|importar|confirmar|avisar)(?: |$)', value):
        return 'help', None
    return ('clarify' if pending else 'none'), None


def execute(db, user, proposal):
    from app.agenda_whatsapp.service import validate
    from app.services import event_commands
    tool = EventTool.model_validate(proposal)
    event = validate(db, user, tool)
    if tool.action == 'create':
        return event_commands.create(db, user, tool.payload)
    if tool.action == 'update':
        return event_commands.update(db, user, str(event.id), UpdateEventRequest(
            data=tool.payload.data, hora=tool.payload.hora))
    event_commands.delete(db, user, str(event.id))
    return event
