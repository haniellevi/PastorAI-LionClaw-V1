"""Real visit event, provenance, permissions and atomic pipeline transition."""
import datetime as dt
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func, text

from app.db.models import AppUser, Celula, CelulaReuniao, CelulaVisitante, Pessoa, Consolidacao, Decision, WorkQueueItem
from tests.test_prayer_requests_pg import (
    prayer as _prayer_fixture, msg_engine_fx as msg_engine_fx,
    rls_database_url as rls_database_url, TENANT, FOREIGN,
)

prayer = _prayer_fixture
pytestmark = pytest.mark.rls_integration
MIGRATION = Path(__file__).parents[1] / 'migrations/20261017_180000_visit_events.sql'


@pytest.fixture
def visit(prayer):
    from app.visits.models import VisitEvent
    sql = MIGRATION.read_text().replace('public.', 'msg_idemp1.')
    with prayer.engine.begin() as conn:
        # Mirror the enum used by real migrations, not only ORM Text metadata.
        conn.exec_driver_sql("create type msg_idemp1.visit_role_fixture as enum ('admin','pastor','lider_g12','lider_consol','lider_celula','lider_mult','membro','operador')")
        conn.exec_driver_sql("alter table msg_idemp1.user_roles alter column papel type msg_idemp1.visit_role_fixture using papel::text::msg_idemp1.visit_role_fixture")
        conn.exec_driver_sql(sql)
    meeting = uuid.uuid4()
    with prayer.factory.begin() as db:
        person = db.get(Pessoa, prayer.person)
        person.tipo, person.etapa, person.subetapa = 'contato', 'ganhar', 'novo_contato'
        person.origem = 'whatsapp'
        db.add(CelulaReuniao(id=meeting, igreja_id=TENANT, celula_id=prayer.cell,
            data=dt.date.today()-dt.timedelta(days=1), hora='19:30',
            status='planejada', relatorio_status='pendente'))
    prayer.meeting = meeting
    return prayer


def register(p, **kwargs):
    from app.visits.service import register_cell_visit
    db = p.factory()
    try:
        result = register_cell_visit(db, p.actors['lider_celula'],
            reuniao_id=p.meeting, pessoa_id=p.person, **kwargs)
        db.commit()
        return result.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def test_visit_promotes_atomically_preserves_origin_and_does_not_open_v3(visit):
    from app.visits.models import VisitEvent
    event_id = register(visit)
    with visit.factory() as db:
        event = db.get(VisitEvent, event_id)
        assert event.tipo == 'visita_celula'
        assert event.origem == 'painel_lider'
        assert event.registrado_por == uuid.UUID(visit.actors['lider_celula'].app_user_id)
        assert event.pessoa_id == visit.person and event.reuniao_id == visit.meeting
        assert db.get(CelulaVisitante, event.visitante_id).nome_visitante == db.get(Pessoa, visit.person).nome
        person = db.get(Pessoa, visit.person)
        assert (person.tipo, person.subetapa, person.origem) == ('visitante', 'visitante', 'whatsapp')
        for model in [Consolidacao, Decision, WorkQueueItem]:
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_outer_rollback_removes_event_visitor_and_promotion(visit):
    from app.visits.models import VisitEvent
    from app.visits.service import register_cell_visit
    with visit.factory() as db:
        register_cell_visit(db, visit.actors['lider_celula'], reuniao_id=visit.meeting, pessoa_id=visit.person)
        db.rollback()
    with visit.factory() as db:
        assert db.scalar(select(func.count()).select_from(VisitEvent)) == 0
        assert db.scalar(select(func.count()).select_from(CelulaVisitante)) == 0
        assert db.get(Pessoa, visit.person).subetapa == 'novo_contato'


def test_duplicate_and_concurrent_registration_are_one_event(visit):
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: register(visit), range(2)))
    assert ids[0] == ids[1] == register(visit)
    from app.visits.models import VisitEvent
    with visit.factory() as db:
        assert db.scalar(select(func.count()).select_from(VisitEvent)) == 1
        assert db.scalar(select(func.count()).select_from(CelulaVisitante)) == 1


@pytest.mark.parametrize('change', ['future', 'other_church', 'old_leader', 'no_role', 'expectation'])
def test_invalid_visit_cannot_promote(visit, change):
    from app.db.models import UserRole, CelulaExpectativaVisitante
    from app.visits.models import VisitEvent
    with visit.factory.begin() as db:
        if change == 'future':
            db.get(CelulaReuniao, visit.meeting).data = dt.date.today()+dt.timedelta(days=1)
        elif change == 'other_church':
            foreign = Pessoa(id=uuid.uuid4(), igreja_id=FOREIGN, nome='Pessoa estrangeira sintética', telefone='5500000000066')
            db.add(foreign)
            db.flush()
            visit.person = foreign.id
        elif change == 'old_leader':
            db.get(Celula, visit.cell).lider_id = db.get(AppUser, uuid.UUID(visit.actors['membro'].app_user_id)).pessoa_id
        elif change == 'no_role':
            db.query(UserRole).filter_by(user_id=uuid.UUID(visit.actors['lider_celula'].app_user_id)).delete()
        else:
            db.add(CelulaExpectativaVisitante(igreja_id=TENANT, reuniao_id=visit.meeting,
                pessoa_id=visit.person, nome_visitante='Homônimo sintético'))
    if change == 'expectation':
        with visit.factory() as db:
            assert db.get(Pessoa, visit.person).subetapa == 'novo_contato'
            assert db.scalar(select(func.count()).select_from(VisitEvent)) == 0
    else:
        with pytest.raises(HTTPException):
            register(visit)
        with visit.factory() as db:
            assert db.scalar(select(func.count()).select_from(VisitEvent)) == 0


def test_homonyms_are_selected_by_id_and_members_are_not_downgraded(visit):
    other = uuid.uuid4()
    with visit.factory.begin() as db:
        person = db.get(Pessoa, visit.person)
        db.add(Pessoa(id=other, igreja_id=TENANT, nome=person.nome, telefone='5500000000077',
                      tipo='contato', subetapa='novo_contato'))
        person.tipo, person.subetapa, person.etapa = 'membro', 'consolidado', 'discipular'
    register(visit)
    with visit.factory() as db:
        assert db.get(Pessoa, other).subetapa == 'novo_contato'
        person = db.get(Pessoa, visit.person)
        assert (person.tipo, person.subetapa, person.etapa) == ('membro', 'consolidado', 'discipular')


def test_agent_tool_refuses_without_real_event_and_manual_panel_is_audited(visit):
    from app.agent.tools import avancar_trilha, ToolError
    from app.routers.pipeline import update_pipeline, PipelineUpdateRequest
    from app.visits.models import VisitEvent
    with visit.factory() as db:
        with pytest.raises(ToolError, match='evento'):
            avancar_trilha(db, igreja_id=TENANT, pessoa_id=visit.person, etapa='ganhar', subetapa='visitante')
        update_pipeline(PipelineUpdateRequest(pessoaId=str(visit.person), etapa='ganhar', subetapa='visitante'), db, visit.actors['pastor'])
    with visit.factory() as db:
        event = db.scalars(select(VisitEvent)).one()
        assert event.tipo == 'manual_painel' and event.reuniao_id is None
        assert event.registrado_por == uuid.UUID(visit.actors['pastor'].app_user_id)
        assert db.get(Pessoa, visit.person).subetapa == 'visitante'
        # A manual classification does not fabricate evidence of attendance.
        with pytest.raises(ToolError, match='evento'):
            avancar_trilha(db, igreja_id=TENANT, pessoa_id=visit.person, etapa='ganhar', subetapa='visitante')


def test_event_rls_and_cross_tenant_fk(visit):
    from app.visits.models import VisitEvent
    register(visit)
    with visit.engine.begin() as conn:
        flags = conn.execute(text("select relrowsecurity, relforcerowsecurity from pg_class where oid='msg_idemp1.evento_visita'::regclass")).one()
        assert flags == (True, True)
        conn.execute(text("set local role authenticated"))
        conn.execute(text("select set_config('app.tenant_igreja_id', :tenant, true)"), {'tenant': str(FOREIGN)})
        assert conn.scalar(select(func.count()).select_from(VisitEvent)) == 0
        conn.execute(text("select set_config('app.tenant_igreja_id', :tenant, true)"), {'tenant': str(TENANT)})
        assert conn.scalar(select(func.count()).select_from(VisitEvent)) == 1


def test_approved_offboarding_deletes_new_events(visit):
    from sqlalchemy import delete
    from app.db.models import CelulaMembro
    from app.services.pessoa_offboarding_service import archive_pessoa
    from app.visits.models import VisitEvent
    register(visit)
    with visit.factory.begin() as db:
        db.execute(delete(CelulaMembro).where(CelulaMembro.pessoa_id == visit.person))
    with visit.factory() as db:
        db.execute(text("select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claims','{\"sub\":\"prayer-admin\"}',true),set_config('role','authenticated',true)"), {'t':str(TENANT)})
        archive_pessoa(db, pessoa=db.get(Pessoa,visit.person),
            actor_app_user_id=uuid.UUID(visit.actors['admin'].app_user_id), motivo='Exclusão sintética aprovada')
    with visit.factory() as db:
        assert db.scalar(select(func.count()).select_from(VisitEvent)) == 0
        assert db.get(Pessoa,visit.person).arquivada_em is not None


def test_authenticated_leader_writes_and_role_revocation_closes_rls(visit):
    from app.visits.service import register_cell_visit
    from app.visits.models import VisitEvent
    from app.db.models import UserRole
    with visit.factory() as db:
        db.execute(text("select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claims','{\"sub\":\"prayer-lider_celula\"}',true),set_config('role','authenticated',true)"), {'t':str(TENANT)})
        register_cell_visit(db,visit.actors['lider_celula'],reuniao_id=visit.meeting,pessoa_id=visit.person)
        db.commit()
    for subject, expected in [('prayer-membro',0),('prayer-lider_celula',1),('prayer-pastor',1)]:
        import json
        with visit.engine.begin() as conn:
            conn.execute(text("select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claims',:jwt,true),set_config('role','authenticated',true)"), {'t':str(TENANT),'jwt':json.dumps({'sub':subject})})
            assert conn.scalar(select(func.count()).select_from(VisitEvent)) == expected
    with visit.factory.begin() as db:
        db.query(UserRole).filter_by(user_id=uuid.UUID(visit.actors['lider_celula'].app_user_id)).delete()
    with visit.engine.begin() as conn:
        conn.execute(text("select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claims','{\"sub\":\"prayer-lider_celula\"}',true),set_config('role','authenticated',true)"), {'t':str(TENANT)})
        assert conn.scalar(select(func.count()).select_from(VisitEvent)) == 0


@pytest.mark.parametrize('forgery',['foreign_person','wrong_source_meeting','foreign_actor','invalid_type'])
def test_composite_fks_and_type_reject_forgery(visit,forgery):
    from app.visits.models import VisitEvent
    from sqlalchemy.exc import DBAPIError
    register(visit)
    foreign_person, foreign_actor, other_person, other_meeting = [uuid.uuid4() for _ in range(4)]
    with visit.factory.begin() as db:
        db.add(Pessoa(id=foreign_person,igreja_id=FOREIGN,nome='Pessoa B sintética',telefone='5500000000044'))
        db.add(Pessoa(id=other_person,igreja_id=TENANT,nome='Pessoa C sintética',telefone='5500000000055'))
        db.add(AppUser(id=foreign_actor,igreja_id=FOREIGN,nome='Responsável B',email='other@example.test',clerk_user_id='foreign-actor'))
        db.add(CelulaReuniao(id=other_meeting,igreja_id=TENANT,celula_id=visit.cell,data=dt.date.today()-dt.timedelta(days=2)))
    with pytest.raises(DBAPIError):
        with visit.factory.begin() as db:
            event = db.scalars(select(VisitEvent)).one()
            db.add(VisitEvent(id=uuid.uuid4(),igreja_id=TENANT,
                pessoa_id=foreign_person if forgery=='foreign_person' else other_person,
                reuniao_id=other_meeting if forgery=='wrong_source_meeting' else visit.meeting,
                visitante_id=event.visitante_id,
                registrado_por=foreign_actor if forgery=='foreign_actor' else event.registrado_por,
                tipo='fake' if forgery=='invalid_type' else 'visita_celula',origem='painel_lider',
                data_ocorrencia=event.data_ocorrencia,data_registro=event.data_registro))


def test_lookup_is_scoped_to_current_leader_masks_phone_and_avoids_browsing(visit):
    from app.visits.service import lookup_people
    with visit.factory() as db:
        assert lookup_people(db,visit.actors['lider_celula'],reuniao_id=str(visit.meeting),q='',page=1,page_size=20)['items'] == []
        found = lookup_people(db,visit.actors['lider_celula'],reuniao_id=str(visit.meeting),q='Contato',page=1,page_size=20)
        assert found['items'][0]['id'] == str(visit.person)
        assert found['items'][0]['telefone'].startswith('•••• ')
        with pytest.raises(HTTPException):
            lookup_people(db,visit.actors['membro'],reuniao_id=str(visit.meeting),q='Contato',page=1,page_size=20)


def test_manual_member_classification_does_not_downgrade_and_revoked_role_is_denied(visit):
    from app.visits.service import record_manual_transition
    from app.db.models import UserRole
    with visit.factory.begin() as db:
        person=db.get(Pessoa,visit.person)
        person.tipo,person.etapa,person.subetapa='membro','discipular','consolidado'
        record_manual_transition(db,visit.actors['pastor'],pessoa_id=visit.person,etapa='ganhar')
        assert (person.tipo,person.etapa,person.subetapa)==('membro','discipular','consolidado')
        db.query(UserRole).filter_by(user_id=uuid.UUID(visit.actors['pastor'].app_user_id)).delete()
    with visit.factory() as db:
        with pytest.raises(HTTPException):
            record_manual_transition(db,visit.actors['pastor'],pessoa_id=visit.person,etapa='ganhar')


def test_panel_http_explicit_identity_provenance_and_snapshot(visit):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.db.session import get_db
    from app.deps import get_current_user
    from app.routers.cell_meetings import router
    actor = visit.actors['lider_celula']

    def session():
        with visit.factory() as db:
            yield db

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: actor
    url = f'/cell-meetings/{visit.meeting}'
    with TestClient(app) as client:
        missing = client.post(url+'/visitors', json={'nome_visitante':'Nome não é identidade'})
        assert missing.status_code == 422
        response = client.post(url+'/visitors', json={
            'nome_visitante':'Nome enviado não é autoridade', 'pessoa_id':str(visit.person),
        })
        assert response.status_code == 201, response.text
        row = response.json()
        assert row['pessoa_id'] == str(visit.person) and row['origem'] == 'painel_lider'
        assert row['registrado_por'] == actor.app_user_id
        assert row['nome_visitante'] == 'Contato sintético'
        live = client.get(url+'/report')
        assert live.status_code == 200, live.text
        assert live.json()['visitantes'][0]['pessoa_id'] == str(visit.person)
        sent = client.post(url+'/report/submit')
        assert sent.status_code == 200, sent.text
        frozen = client.get(url+'/report')
        assert frozen.status_code == 200, frozen.text
        assert frozen.json()['visitantes'][0]['pessoa_id'] == str(visit.person)
    with visit.factory() as db:
        snapshot = db.get(CelulaReuniao, visit.meeting).relatorio_snapshot
        assert 'pessoa_id' not in snapshot['visitantes'][0]
        assert 'registrado_por' not in snapshot['visitantes'][0]


@pytest.mark.parametrize('invalid', ['cancelled', 'future_today', 'submitted'])
def test_rls_rejects_direct_evidence_for_ineligible_meeting(visit, invalid):
    from app.visits.models import VisitEvent
    from sqlalchemy.exc import DBAPIError
    visitor = uuid.uuid4()
    with visit.factory.begin() as db:
        meeting = db.get(CelulaReuniao, visit.meeting)
        occurrence = dt.datetime.combine(meeting.data, dt.time(19,30), dt.timezone(dt.timedelta(hours=-3)))
        if invalid == 'cancelled':
            meeting.status = 'cancelada'
        elif invalid == 'submitted':
            meeting.relatorio_status = 'enviado'
        else:
            meeting.data = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).date()
            meeting.hora = '23:59'
            occurrence = dt.datetime.combine(meeting.data, dt.time(0), dt.timezone(dt.timedelta(hours=-3)))
        db.add(CelulaVisitante(id=visitor, igreja_id=TENANT, reuniao_id=visit.meeting, nome_visitante='Nome não é prova'))
    with pytest.raises(DBAPIError):
        with visit.factory.begin() as db:
            db.execute(text("select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claims','{\"sub\":\"prayer-lider_celula\"}',true),set_config('role','authenticated',true)"), {'t':str(TENANT)})
            db.add(VisitEvent(igreja_id=TENANT,pessoa_id=visit.person,reuniao_id=visit.meeting,
                visitante_id=visitor,registrado_por=uuid.UUID(visit.actors['lider_celula'].app_user_id),
                tipo='visita_celula',origem='painel_lider',data_ocorrencia=occurrence))


def test_rls_only_admin_may_delete_evidence(visit):
    from app.visits.models import VisitEvent
    from sqlalchemy import delete
    register(visit)
    for subject in ['prayer-pastor','prayer-lider_celula']:
        import json
        with visit.engine.begin() as conn:
            conn.execute(text("select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claims',:jwt,true),set_config('role','authenticated',true)"), {'t':str(TENANT),'jwt':json.dumps({'sub':subject})})
            assert conn.execute(delete(VisitEvent)).rowcount == 0
    with visit.factory() as db:
        assert db.scalar(select(func.count()).select_from(VisitEvent)) == 1


def test_duplicate_after_leader_change_preserves_original_responsible(visit):
    from app.db.models import UserRole
    from app.routers.cell_meetings import register_visitor, RegisterVisitorRequest
    import dataclasses
    register(visit)
    replacement = dataclasses.replace(visit.actors['membro'],roles=frozenset({'lider_celula'}))
    with visit.factory.begin() as db:
        user=db.get(AppUser,uuid.UUID(replacement.app_user_id))
        db.get(Celula,visit.cell).lider_id=user.pessoa_id
        db.add(UserRole(igreja_id=TENANT,user_id=user.id,papel='lider_celula'))
    with visit.factory() as db:
        result=register_visitor(str(visit.meeting),RegisterVisitorRequest(
            pessoa_id=str(visit.person),nome_visitante='Ignorado'),db,replacement)
        assert result.registrado_por == visit.actors['lider_celula'].app_user_id
        assert result.responsavel_nome == 'lider_celula'
