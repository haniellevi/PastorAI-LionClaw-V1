"""Agenda projections and proposals over the panel's tenant-scoped commands."""
import datetime as dt
import hashlib
import json
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select
from app.db.models import AppUser, UserRole, EventNotifyTarget
from app.db.rls_observability import require_tenant_scope
from app.deps import CurrentUser
from app.routers.events import CreateEventRequest
from app.routers._common import PaginationParams
from app.services import event_commands
from app.services.whatsapp_agenda import AGENDA_TIMEZONE, project_institutional_title


def actor(db, contact):
    require_tenant_scope(db, expected_igreja_id=contact.igreja_id, source='agenda_whatsapp')
    users = db.scalars(select(AppUser).where(AppUser.igreja_id == contact.igreja_id,
        AppUser.pessoa_id == contact.pessoa_id, AppUser.status == 'ativo').with_for_update(read=True, of=AppUser)).all()
    if len(users) != 1:
        raise HTTPException(403, 'Remetente sem usuário ativo único')
    roles = db.scalars(select(UserRole.papel).where(UserRole.igreja_id == contact.igreja_id,
        UserRole.user_id == users[0].id).with_for_update(read=True)).all()
    return CurrentUser(app_user_id=str(users[0].id), igreja_id=str(contact.igreja_id),
        clerk_user_id='', email='', nome='', roles=frozenset(roles))


def _snapshot(event):
    # Digest includes notification/confirmation state without copying its private text.
    payload = {col.key: str(getattr(event, col.key)) for col in event.__table__.columns}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate(db, user, tool):
    event_commands._write_allowed(user)
    if tool.action == 'create':
        if tool.event_id or tool.snapshot or tool.payload is None:
            raise ValueError('invalid create')
        if (not project_institutional_title(tool.payload.titulo)
            or tool.payload.descricao is not None or tool.payload.tipo is not None
            or tool.payload.hora is None):
            raise HTTPException(422, 'Use um título institucional da agenda e horário HH:MM; outros detalhes exigem o painel.')
        return None
    if tool.event_id is None or not tool.snapshot:
        raise ValueError('missing target')
    event = event_commands._get_event(db, user, str(tool.event_id), for_update=True)
    if (event.origem != 'manual' or event.google_event_id is not None
        or event.recorrencia != 'pontual' or event.status != 'confirmado'
        or any(getattr(event, f) is not None for f in (
            'publico_alvo', 'antecedencia_horas', 'mensagem_confirmacao', 'notificar_em',
            'notificacao_enviada_em', 'canal', 'notificado_em', 'notification_outbox_fenced_at'))
        or db.scalar(select(EventNotifyTarget.id).where(EventNotifyTarget.igreja_id == UUID(user.igreja_id),
            EventNotifyTarget.event_id == event.id).limit(1)) is not None):
        raise HTTPException(422, 'Evento com integração, recorrência ou avisos: use o painel autenticado.')
    if _snapshot(event) != tool.snapshot:
        raise HTTPException(409, 'O evento mudou. Consulte a agenda e faça uma nova proposta.')
    if tool.action == 'update' and (tool.payload is None or tool.payload.hora is None):
        raise ValueError('missing schedule')
    if tool.action == 'delete' and tool.payload is not None:
        raise ValueError('invalid delete')
    return event


def propose(db, user, command, args):
    from app.agenda_whatsapp.catalog import EventTool
    event_commands._write_allowed(user)
    if command == 'create':
        title, day, hour = args
        tool = EventTool(action='create', payload=CreateEventRequest(titulo=title, data=day, hora=hour))
        description = f'Criar {tool.payload.titulo} em {tool.payload.data:%d/%m/%Y} às {tool.payload.hora}.'
    else:
        eid = UUID(args[0] if command == 'update' else args)
        event = event_commands._get_event(db, user, str(eid), for_update=True)
        payload = CreateEventRequest(titulo='Evento', data=args[1], hora=args[2]) if command == 'update' else None
        tool = EventTool(action=command, event_id=eid, payload=payload, snapshot=_snapshot(event))
        validate(db, user, tool)
        title = project_institutional_title(event.titulo) or 'Evento da igreja'
        description = f'{title} ({eid}), em {event.data.strftime('%d/%m/%Y') if event.data else 'data não cadastrada'} às {event.hora or "horário não cadastrado"}. '
        description += (f'Alterar para {payload.data:%d/%m/%Y} às {payload.hora}.' if payload
            else 'Cancelar por remoção do evento local, como no painel.')
    validate(db, user, tool)  # Read-only preview: never execute/rollback a domain writer.
    return (description + ' Sem Google ou envio de avisos. Confirma? Responda somente SIM ou NÃO em até 10 minutos.',
        tool.model_dump(mode='json'))


def read(db, user):
    start = dt.datetime.now(AGENDA_TIMEZONE).date()
    rows, total = event_commands.list_page(db, user, pagination=PaginationParams(page=1, page_size=25),
        from_date=start, to_date=start+dt.timedelta(days=29), confirmed_only=True)
    lines = ['Agenda local: próximos 30 dias (até 25 eventos).']
    for event in rows:
        title = project_institutional_title(event.titulo) or 'Evento da igreja'
        identity = f' ({event.id})' if user.has_any_role(['pastor']) else ''
        lines.append(f'{title}{identity}: {event.data.strftime('%d/%m/%Y') if event.data else 'data não cadastrada'} às {event.hora or "horário não cadastrado"}.')
    if not rows:
        lines.append('Nenhum evento cadastrado no período.')
    if total > 25:
        lines.append('Há mais resultados; consulte o painel.')
    return '\n'.join(lines)
