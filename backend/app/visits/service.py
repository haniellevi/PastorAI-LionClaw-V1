"""One application service for real cell visits and audited manual classification.

No commit here: callers own the transaction including evidence and promotion.
"""
import dataclasses
import datetime as dt
import uuid
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import delete, func, select, or_
from app.db.models import AppUser, CelulaExpectativaVisitante, CelulaVisitante, Pessoa, UserRole
from app.domain.pipeline import PIPELINE_PROMOTE_ROLES, validate_transition
from app.visits.models import VisitEvent

LEADER_ROLES = ('lider_celula', 'pastor', 'admin')


def now(db):
    return db.scalar(select(func.clock_timestamp()))


def fresh_actor(db, actor, allowed_roles):
    user = db.execute(select(AppUser).where(
        AppUser.id == uuid.UUID(actor.app_user_id), AppUser.igreja_id == uuid.UUID(actor.igreja_id),
    ).with_for_update(of=AppUser).execution_options(populate_existing=True)).scalar_one_or_none()
    if user is None or user.clerk_user_id != actor.clerk_user_id or user.status not in (None, 'ativo'):
        raise HTTPException(403, 'Acesso do responsável revogado')
    roles = db.execute(select(UserRole.papel).where(
        UserRole.igreja_id == user.igreja_id, UserRole.user_id == user.id,
    ).with_for_update()).scalars().all()
    if not set(roles).intersection(allowed_roles):
        raise HTTPException(403, 'Papel não autorizado para este registro')
    return dataclasses.replace(actor, roles=frozenset(roles))


def person_for_update(db, tenant, pessoa_id):
    person = db.execute(select(Pessoa).where(
        Pessoa.id == pessoa_id, Pessoa.igreja_id == tenant,
        Pessoa.arquivada_em.is_(None), Pessoa.sem_interesse.is_(False),
    ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if person is None:
        raise HTTPException(404, 'Pessoa não encontrada ou fora do acompanhamento')
    return person


def _promote_entry(person):
    if person.tipo in (None, 'contato', 'visitante') and person.etapa in (None, 'ganhar') and person.subetapa in (None, 'novo_contato', 'visitante'):
        person.tipo, person.etapa, person.subetapa = 'visitante', 'ganhar', 'visitante'


def register_cell_visit(db, actor, *, reuniao_id, pessoa_id, expectativa_id=None, observacao=None):
    from app.routers.cell_meetings import (
        _locked_leader_meeting_or_404, _assert_report_open,
        _invalidate_pending_agent_report_for_human_takeover,
    )
    meeting = _locked_leader_meeting_or_404(db, actor, str(reuniao_id))
    actor = fresh_actor(db, actor, LEADER_ROLES)
    _assert_report_open(meeting)
    if meeting.status == "cancelada":
        raise HTTPException(409, "Reunião cancelada não comprova visita")
    if pessoa_id is None:
        raise HTTPException(422, 'Selecione a Pessoa por identificação; nome não comprova identidade')
    timestamp = now(db)
    try:
        occurrence = dt.datetime.combine(meeting.data, dt.time.fromisoformat(meeting.hora or '00:00'), ZoneInfo('America/Sao_Paulo'))
    except ValueError:
        raise HTTPException(409, 'Horário da reunião inválido') from None
    if occurrence > timestamp:
        raise HTTPException(409, 'Reunião futura não comprova visita')
    person = person_for_update(db, meeting.igreja_id, pessoa_id)
    existing = db.execute(select(VisitEvent).where(
        VisitEvent.igreja_id == meeting.igreja_id, VisitEvent.reuniao_id == meeting.id,
        VisitEvent.pessoa_id == person.id,
    )).scalar_one_or_none()
    if expectativa_id is not None:
        expected = db.execute(select(CelulaExpectativaVisitante.id).where(
            CelulaExpectativaVisitante.id == expectativa_id,
            CelulaExpectativaVisitante.igreja_id == meeting.igreja_id,
            CelulaExpectativaVisitante.reuniao_id == meeting.id,
        )).scalar_one_or_none()
        if expected is None:
            raise HTTPException(422, 'Expectativa de outra reunião ou igreja')
    if existing is not None:
        if expectativa_id is not None:
            visitor = db.get(CelulaVisitante, existing.visitante_id)
            if visitor.expectativa_id not in (None, expectativa_id):
                raise HTTPException(409, 'Presença já vinculada a outra expectativa')
            if visitor.expectativa_id is None:
                _invalidate_pending_agent_report_for_human_takeover(meeting)
                visitor.expectativa_id = expectativa_id
                db.flush()
        return existing
    _invalidate_pending_agent_report_for_human_takeover(meeting)
    visitor = CelulaVisitante(igreja_id=meeting.igreja_id, reuniao_id=meeting.id,
        expectativa_id=expectativa_id, nome_visitante=person.nome, observacao=observacao)
    db.add(visitor)
    db.flush()
    db.refresh(visitor)
    event = VisitEvent(igreja_id=meeting.igreja_id, pessoa_id=person.id,
        reuniao_id=meeting.id, visitante_id=visitor.id,
        registrado_por=uuid.UUID(actor.app_user_id), tipo='visita_celula', origem='painel_lider',
        data_ocorrencia=occurrence, data_registro=timestamp)
    db.add(event)
    _promote_entry(person)
    db.flush()
    return event


def record_manual_transition(db, actor, *, pessoa_id, etapa):
    actor = fresh_actor(db, actor, (*PIPELINE_PROMOTE_ROLES, 'admin'))
    person = person_for_update(db, uuid.UUID(actor.igreja_id), pessoa_id)
    result = validate_transition(current_tipo=person.tipo, current_etapa=person.etapa,
        target_etapa=etapa, target_subetapa='visitante', presencas_celula=person.presencas_celula,
        aceitou_jesus=person.aceitou_jesus)
    if not result.allowed:
        raise HTTPException(409, result.reason)
    timestamp = now(db)
    db.add(VisitEvent(igreja_id=person.igreja_id, pessoa_id=person.id,
        registrado_por=uuid.UUID(actor.app_user_id), tipo='manual_painel', origem='painel_pipeline',
        data_ocorrencia=timestamp, data_registro=timestamp))
    # Audit the team's action, without downgrading members or advanced stages.
    if person.tipo in (None, 'contato', 'visitante') and person.etapa in (None, 'ganhar'):
        person.etapa, person.subetapa = etapa, 'visitante'
        if etapa == 'ganhar':
            person.tipo = 'visitante'
    db.flush()
    return person


def has_real_event(db, *, igreja_id, pessoa_id):
    return db.scalar(select(VisitEvent.id).where(VisitEvent.igreja_id == igreja_id,
        VisitEvent.pessoa_id == pessoa_id, VisitEvent.tipo == 'visita_celula',
        VisitEvent.data_ocorrencia <= func.now()).limit(1)) is not None


def delete_for_person(db, *, igreja_id, pessoa_id):
    db.execute(delete(VisitEvent).where(VisitEvent.igreja_id == igreja_id, VisitEvent.pessoa_id == pessoa_id))


def lookup_people(db, actor, *, reuniao_id, q, page, page_size):
    from app.routers.cell_meetings import _locked_leader_meeting_or_404
    meeting = _locked_leader_meeting_or_404(db, actor, reuniao_id)
    fresh_actor(db, actor, LEADER_ROLES)
    if len(q.strip()) < 3:
        return dict(items=[], page=page, pageSize=page_size, total=0)
    term = q.strip()
    pattern = '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    digits = ''.join(c for c in term if c.isdigit())
    phone = func.regexp_replace(Pessoa.telefone, '[^0-9]', '', 'g')
    name_or_phone = [Pessoa.nome.ilike(pattern, escape='\\')]
    if len(digits) >= 3:
        name_or_phone.append(phone.contains(digits))
    filters = [Pessoa.igreja_id == meeting.igreja_id, Pessoa.arquivada_em.is_(None),
        Pessoa.sem_interesse.is_(False), or_(*name_or_phone)]
    total = db.scalar(select(func.count()).select_from(Pessoa).where(*filters))
    rows = db.execute(select(Pessoa.id, Pessoa.nome, Pessoa.telefone).where(*filters)
        .order_by(Pessoa.nome, Pessoa.id).offset((page-1)*page_size).limit(page_size)).all()
    return dict(items=[dict(id=str(row.id), nome=row.nome,
        telefone='•••• '+''.join(c for c in row.telefone if c.isdigit())[-4:]) for row in rows],
        page=page, pageSize=page_size, total=total)
