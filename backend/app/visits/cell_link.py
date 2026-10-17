"""First proven visit suggests a cell; only explicit web confirmation writes.

No commit: the HTTP adapter owns the transaction. No agent capability is added.
"""
import hashlib
import json
import uuid
from zoneinfo import ZoneInfo
import datetime as dt

from fastapi import HTTPException
from sqlalchemy import exists, func, select

from app.db.models import Celula, CelulaMembro, CelulaReuniao, CelulaVisitante, Pessoa, WhatsappConnection
from app.services.celula_membro import ensure_active_membro, assert_membro_elegivel_facts, MembroInelegivelError
from app.domain.phone import normalize_phone
from app.visits.models import VisitEvent
from app.visits.service import fresh_actor, person_for_update

ROLES = ('pastor', 'admin')


def _first(db, tenant, person_id):
    # Rank BEFORE checking availability: never silently fall back to a later visit.
    return db.scalar(select(VisitEvent).where(
        VisitEvent.igreja_id == tenant, VisitEvent.pessoa_id == person_id,
        VisitEvent.tipo == 'visita_celula',
    ).order_by(VisitEvent.data_ocorrencia, VisitEvent.data_registro, VisitEvent.id)
        .limit(1).execution_options(populate_existing=True))


def _related(db, model, tenant, ident, lock=False):
    query = select(model).where(model.igreja_id == tenant, model.id == ident)
    if lock:
        query = query.with_for_update()
    return db.scalar(query.execution_options(populate_existing=True))


def _describe(person, event, meeting, visitor, cell, timestamp, memberships,
              leads_active_cell, official_phone):
    valid = bool(meeting and visitor and cell and visitor.reuniao_id == meeting.id
                 and event.origem == 'painel_lider' and meeting.status != 'cancelada')
    if valid:
        try:
            occurrence = dt.datetime.combine(meeting.data, dt.time.fromisoformat(meeting.hora or '00:00'), ZoneInfo('America/Sao_Paulo'))
            valid = occurrence == event.data_ocorrencia and occurrence <= timestamp
        except ValueError:
            valid = False
    reason = None
    if not valid:
        reason = 'Evidência da primeira visita divergente. Revise o registro da reunião.'
    elif not cell.ativo:
        reason = 'A célula da primeira visita está inativa.'
    elif not cell.lider_id:
        reason = 'A célula da primeira visita está sem líder.'
    already_linked = False
    if cell:
        already_linked = person.celula_id == cell.id and cell.id in memberships
        if any(ident != cell.id for ident in memberships) or (person.celula_id is not None and person.celula_id != cell.id):
            reason = 'Pessoa já vinculada a outra célula. Use a transferência administrativa existente.'
        if reason is None:
            try:
                assert_membro_elegivel_facts(celula=cell, pessoa=person,
                    leads_active_cell=leads_active_cell, official_phone=official_phone)
            except MembroInelegivelError as exc:
                reason = exc.message
    # A content revision detects changes between display and confirmation,
    # including a changed meeting/visitor/leader even when still eligible.
    snapshot = [str(event.id), str(event.pessoa_id), str(event.reuniao_id),
        str(event.visitante_id), event.tipo, event.origem, str(event.registrado_por),
        event.data_ocorrencia.isoformat(), event.data_registro.isoformat(),
        [str(meeting.celula_id), str(meeting.data), meeting.hora, meeting.status] if meeting else None,
        [str(visitor.reuniao_id), str(visitor.expectativa_id), visitor.nome_visitante] if visitor else None,
        [str(cell.id), cell.nome, cell.ativo, str(cell.lider_id)] if cell else None]
    revision = hashlib.sha256(json.dumps(snapshot, ensure_ascii=True).encode()).hexdigest()
    return dict(pessoa_id=str(person.id), pessoa_nome=person.nome, evento_id=str(event.id),
        celula_id=str(cell.id) if cell else None, celula_nome=cell.nome if cell else None,
        data_ocorrencia=event.data_ocorrencia.isoformat(), revision=revision, blocked_reason=reason, already_linked=already_linked)


def _by_id(db, model, tenant, ids):
    if not ids:
        return {}
    return {row.id: row for row in db.scalars(select(model).where(
        model.igreja_id == tenant, model.id.in_(ids),
    ).execution_options(populate_existing=True))}


def _descriptions(db, tenant, people):
    """Constant round trips per page, including canonical eligibility facts."""
    if not people:
        return []
    ids = [person.id for person in people]
    events = db.scalars(select(VisitEvent).where(
        VisitEvent.igreja_id == tenant, VisitEvent.pessoa_id.in_(ids),
        VisitEvent.tipo == 'visita_celula',
    ).distinct(VisitEvent.pessoa_id).order_by(VisitEvent.pessoa_id,
        VisitEvent.data_ocorrencia, VisitEvent.data_registro, VisitEvent.id)
        .execution_options(populate_existing=True)).all()
    meetings = _by_id(db, CelulaReuniao, tenant, {e.reuniao_id for e in events})
    visitors = _by_id(db, CelulaVisitante, tenant, {e.visitante_id for e in events})
    cells = _by_id(db, Celula, tenant, {m.celula_id for m in meetings.values()})
    memberships = {}
    for person_id, cell_id in db.execute(select(CelulaMembro.pessoa_id, CelulaMembro.celula_id).where(
        CelulaMembro.igreja_id == tenant, CelulaMembro.pessoa_id.in_(ids), CelulaMembro.ativo.is_(True),
    )):
        memberships.setdefault(person_id, []).append(cell_id)
    leaders = set(db.scalars(select(Celula.lider_id).where(
        Celula.igreja_id == tenant, Celula.lider_id.in_(ids), Celula.ativo.is_(True),
    )))
    official = normalize_phone(db.scalar(select(WhatsappConnection.numero).where(
        WhatsappConnection.igreja_id == tenant,
    )) or '')
    timestamp = db.scalar(select(func.now()))
    events_by_person = {event.pessoa_id: event for event in events}
    result = []
    for person in people:
        event = events_by_person.get(person.id)
        # Offboarding may remove evidence between the page and batch reads.
        if event is None:
            continue
        meeting = meetings.get(event.reuniao_id)
        result.append(_describe(person, event, meeting, visitors.get(event.visitante_id),
            cells.get(meeting.celula_id) if meeting else None, timestamp,
            memberships.get(person.id, []), person.id in leaders,
            bool(official and normalize_phone(person.telefone or '') == official)))
    return result


def suggestion(db, actor, pessoa_id):
    actor = fresh_actor(db, actor, ROLES)
    tenant = uuid.UUID(actor.igreja_id)
    person = _related(db, Pessoa, tenant, pessoa_id)
    if person is None:
        raise HTTPException(404, 'Pessoa não encontrada')
    if person.arquivada_em or person.sem_interesse:
        return None
    items = _descriptions(db, tenant, [person])
    return items[0] if items else None


def suggestions(db, actor, *, page, page_size):
    actor = fresh_actor(db, actor, ROLES)
    tenant = uuid.UUID(actor.igreja_id)
    filters = [Pessoa.igreja_id == tenant, Pessoa.arquivada_em.is_(None), Pessoa.sem_interesse.is_(False),
        Pessoa.celula_id.is_(None),
        ~exists(select(CelulaMembro.id).where(CelulaMembro.igreja_id == tenant,
            CelulaMembro.pessoa_id == Pessoa.id, CelulaMembro.ativo.is_(True))),
        exists(select(VisitEvent.id).where(VisitEvent.igreja_id == tenant,
            VisitEvent.pessoa_id == Pessoa.id, VisitEvent.tipo == 'visita_celula'))]
    total = db.scalar(select(func.count()).select_from(Pessoa).where(*filters))
    people = db.scalars(select(Pessoa).where(*filters).order_by(Pessoa.nome, Pessoa.id)
        .offset((page-1)*page_size).limit(page_size)).all()
    return dict(items=_descriptions(db, tenant, people),
        page=page, page_size=page_size, total=total)


def confirm_link(db, actor, pessoa_id, evidence):
    actor = fresh_actor(db, actor, ROLES)
    tenant = uuid.UUID(actor.igreja_id)
    # After authorization, lock domain rows in order: meeting, cell, person.
    event = _first(db, tenant, pessoa_id)
    if event is None:
        if _related(db, Pessoa, tenant, pessoa_id) is None:
            raise HTTPException(404, 'Pessoa não encontrada')
        raise HTTPException(409, 'Primeira visita não comprovada. Atualize a sugestão.')
    meeting = _related(db, CelulaReuniao, tenant, event.reuniao_id, True)
    cell = _related(db, Celula, tenant, meeting.celula_id, True) if meeting else None
    person = person_for_update(db, tenant, pessoa_id)
    first = _first(db, tenant, pessoa_id)
    if first is None or first.id != event.id:
        raise HTTPException(409, 'Primeira visita alterada. Atualize a sugestão.')
    # Evidence is immutable (no UPDATE grant); approved offboarding deletes
    # it under the same Person lock. FOR UPDATE would require a forbidden
    # UPDATE privilege on evento_visita for the authenticated database role.
    locked_event = _related(db, VisitEvent, tenant, first.id)
    if (locked_event is None or meeting is None or cell is None
            or locked_event.reuniao_id != meeting.id
            or meeting.celula_id != cell.id):
        raise HTTPException(409, 'Evidência alterada. Atualize a sugestão.')
    _related(db, CelulaVisitante, tenant, first.visitante_id, True)
    descriptions = _descriptions(db, tenant, [person])
    if not descriptions:
        raise HTTPException(409, 'Primeira visita alterada. Atualize a sugestão.')
    current = descriptions[0]
    if current['blocked_reason']:
        raise HTTPException(409, current['blocked_reason'])
    if any(current[key] != evidence.get(key) for key in ('evento_id', 'celula_id', 'revision')):
        raise HTTPException(409, 'Evidência alterada. Atualize a sugestão antes de confirmar.')
    ensure_active_membro(db, igreja_id=tenant, celula_id=cell.id, pessoa_id=person.id, pode_transferir=False)
    db.flush()  # preserve trg_link_cell_promote
    from app.routers.contacts import _resolve_cell_connection_queue_items
    _resolve_cell_connection_queue_items(db, igreja_id=tenant, pessoa_id=person.id)
    db.flush()
    return dict(pessoa_id=str(person.id), celula_id=str(cell.id), confirmed=True)
