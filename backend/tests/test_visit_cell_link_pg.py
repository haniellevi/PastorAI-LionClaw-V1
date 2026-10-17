"""Synthetic real-PG visit suggestion and explicit confirmation contract."""
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.db.models import AppUser, Celula, CelulaMembro, CelulaReuniao, Pessoa, UserRole, WorkQueueItem
from tests.test_visit_events_pg import visit, prayer, msg_engine_fx, rls_database_url, register, TENANT, FOREIGN  # noqa: F401

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def candidate(visit):
    from pathlib import Path
    # Install the existing production trigger, without changing its behavior.
    trigger = (Path(__file__).parents[1] / 'migrations/0004_triggers.sql').read_text()
    trigger = trigger[trigger.index('create or replace function fn_link_cell_promote()'):trigger.index('-- trg_report_received_clears_queue')]
    with visit.engine.begin() as conn:
        conn.exec_driver_sql(trigger)
    with visit.factory.begin() as db:
        db.execute(delete(CelulaMembro).where(CelulaMembro.pessoa_id == visit.person))
        db.get(Pessoa, visit.person).celula_id = None
        db.add(WorkQueueItem(igreja_id=TENANT, pessoa_id=visit.person, tipo='conectar_celula', status='aberto', titulo='Conectar sintético'))
    register(visit)
    return visit


def read(p):
    from app.visits.cell_link import suggestion
    with p.factory() as db:
        return suggestion(db, p.actors['pastor'], p.person)


def confirm(p, evidence, role='pastor'):
    from app.visits.cell_link import confirm_link
    with p.factory.begin() as db:
        return confirm_link(db, p.actors[role], p.person, evidence)


def test_visit_person_central_confirmation_and_repetition(candidate):
    from app.visits.cell_link import suggestions
    p = candidate
    evidence = read(p)
    assert evidence['celula_id'] == str(p.cell) and evidence['blocked_reason'] is None
    with p.factory() as db:
        page = suggestions(db, p.actors['admin'], page=1, page_size=1)
        assert page['items'] == [evidence] and page['total'] == 1
        assert suggestions(db, p.actors['pastor'], page=2, page_size=1)['items'] == []
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(lambda _: confirm(p, evidence), range(2)))
    assert confirm(p, evidence)
    with p.factory() as db:
        person = db.get(Pessoa, p.person)
        assert person.celula_id == p.cell
        assert person.acompanhamento == person.subetapa == 'consolidado'
        assert db.scalar(select(func.count()).select_from(CelulaMembro).where(CelulaMembro.pessoa_id == p.person, CelulaMembro.ativo.is_(True))) == 1
        assert db.scalar(select(WorkQueueItem.status).where(WorkQueueItem.pessoa_id == p.person)) == 'resolvido'


@pytest.mark.parametrize('role', ['lider_celula', 'operador', 'membro'])
def test_forbidden_roles(candidate, role):
    from app.visits.cell_link import suggestion, suggestions
    p = candidate
    for action in [lambda db: suggestion(db, p.actors[role], p.person), lambda db: suggestions(db, p.actors[role], page=1, page_size=20), lambda db: confirm(p, read(p), role)]:
        with p.factory() as db, pytest.raises(HTTPException) as exc:
            action(db)
        assert exc.value.status_code == 403


@pytest.mark.parametrize('change', ['revoked', 'role', 'inactive', 'leader', 'meeting', 'evidence', 'other_cell', 'archived'])
def test_stale_or_unavailable_refuses_without_partial_write(candidate, change):
    from app.visits.models import VisitEvent
    p = candidate
    evidence = read(p)
    with p.factory.begin() as db:
        if change == 'revoked':
            db.get(AppUser, uuid.UUID(p.actors['pastor'].app_user_id)).status = 'inativo'
        elif change == 'role':
            db.execute(delete(UserRole).where(UserRole.user_id == uuid.UUID(p.actors['pastor'].app_user_id)))
        elif change == 'inactive':
            db.get(Celula, p.cell).ativo = False
        elif change == 'leader':
            db.get(Celula, p.cell).lider_id = None
        elif change == 'meeting':
            db.get(CelulaReuniao, p.meeting).status = 'cancelada'
        elif change == 'evidence':
            db.execute(delete(VisitEvent).where(VisitEvent.pessoa_id == p.person))
        elif change == 'archived':
            import datetime as dt
            db.get(Pessoa, p.person).arquivada_em = dt.datetime.now(dt.UTC)
        else:
            other = Celula(igreja_id=TENANT, nome='Outra sintética', ativo=True, lider_id=db.get(Celula, p.cell).lider_id, cobertura_espiritual='Teste')
            db.add(other)
            db.flush()
            db.get(Pessoa, p.person).celula_id = other.id
    with pytest.raises(HTTPException):
        confirm(p, evidence, 'admin' if change == 'other_cell' else 'pastor')
    with p.factory() as db:
        assert db.scalar(select(func.count()).select_from(CelulaMembro).where(CelulaMembro.pessoa_id == p.person)) == 0
        assert db.scalar(select(WorkQueueItem.status).where(WorkQueueItem.pessoa_id == p.person)) == 'aberto'


def test_no_evidence_or_foreign_person(visit):
    from app.visits.cell_link import suggestion
    with visit.factory() as db:
        assert suggestion(db, visit.actors['pastor'], visit.person) is None
        with pytest.raises(HTTPException) as exc:
            suggestion(db, visit.actors['pastor'], uuid.uuid4())
        assert exc.value.status_code == 404


@pytest.mark.parametrize('kind', ['expectation', 'manual', 'name_only', 'selection'])
def test_unproven_inputs_never_suggest(visit, kind):
    from app.db.models import CelulaExpectativaVisitante, CelulaVisitante
    from app.visits.service import record_manual_transition
    from app.visits.cell_link import suggestion, suggestions
    with visit.factory.begin() as db:
        if kind == 'expectation':
            db.add(CelulaExpectativaVisitante(igreja_id=TENANT, reuniao_id=visit.meeting, pessoa_id=visit.person, nome_visitante='Sintética'))
        elif kind == 'manual':
            record_manual_transition(db, visit.actors['pastor'], pessoa_id=visit.person, etapa='ganhar')
        elif kind == 'name_only':
            db.add(CelulaVisitante(igreja_id=TENANT, reuniao_id=visit.meeting, nome_visitante=db.get(Pessoa, visit.person).nome))
        # Selection deliberately performs no domain write.
    with visit.factory() as db:
        assert suggestion(db, visit.actors['pastor'], visit.person) is None
        assert suggestions(db, visit.actors['pastor'], page=1, page_size=20)['total'] == 0


@pytest.mark.parametrize('change', ['inactive', 'no_leader', 'date', 'visitor', 'leader_changed', 'forged'])
def test_first_chronological_visit_blocks_without_falling_back(candidate, change):
    import datetime as dt
    from app.visits.service import register_cell_visit
    p = candidate
    evidence = read(p)
    meeting_id = uuid.uuid4()
    with p.factory.begin() as db:
        other = Celula(igreja_id=TENANT, nome='Segunda célula sintética', ativo=True, lider_id=db.get(Celula, p.cell).lider_id, cobertura_espiritual='Teste')
        db.add(other)
        db.flush()
        db.add(CelulaReuniao(id=meeting_id, igreja_id=TENANT, celula_id=other.id, data=dt.date.today(), hora='00:00', status='planejada', relatorio_status='pendente'))
    with p.factory.begin() as db:
        register_cell_visit(db, p.actors['lider_celula'], reuniao_id=meeting_id, pessoa_id=p.person)
    with p.factory.begin() as db:
        if change == 'inactive':
            db.get(Celula, p.cell).ativo = False
        elif change == 'no_leader':
            db.get(Celula, p.cell).lider_id = None
        elif change == 'date':
            db.get(CelulaReuniao, p.meeting).data -= dt.timedelta(days=1)
        elif change == 'visitor':
            from app.db.models import CelulaVisitante
            from app.visits.models import VisitEvent
            event = db.get(VisitEvent, uuid.UUID(evidence['evento_id']))
            db.get(CelulaVisitante, event.visitante_id).nome_visitante = 'Identificação corrigida sintética'
        elif change == 'leader_changed':
            db.get(Celula, p.cell).lider_id = db.get(AppUser, uuid.UUID(p.actors['membro'].app_user_id)).pessoa_id
        else:
            evidence['celula_id'] = str(other.id)
    current = read(p)
    assert current['celula_id'] == str(p.cell)
    if change in ('inactive', 'no_leader', 'date'):
        assert current['blocked_reason']
    with pytest.raises(HTTPException) as exc:
        confirm(p, evidence)
    assert exc.value.status_code == 409
    with p.factory() as db:
        assert db.get(Pessoa, p.person).celula_id is None
        assert db.scalar(select(WorkQueueItem.status).where(WorkQueueItem.pessoa_id == p.person)) == 'aberto'


def test_http_flow_and_isolation_with_authenticated_pg_role(candidate):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import contacts, cell_central
    from app.db.session import get_db
    from app.deps import get_current_user
    from sqlalchemy import text
    from app.visits.cell_link import suggestion
    p = candidate
    foreign_id = uuid.uuid4()
    with p.factory.begin() as db:
        db.add(Pessoa(id=foreign_id, igreja_id=FOREIGN, nome='Outra igreja sintética', telefone='5500000000900'))
    def db_session():
        with p.factory() as db:
            db.execute(text("set local role authenticated"))
            db.execute(text("select set_config('app.tenant_igreja_id', :t, true), set_config('request.jwt.claim.sub', 'prayer-pastor', true)"), {'t': str(TENANT)})
            yield db
    app = FastAPI()
    app.include_router(contacts.router)
    app.include_router(cell_central.router)
    app.dependency_overrides[get_db] = db_session
    app.dependency_overrides[get_current_user] = lambda: p.actors['pastor']
    with TestClient(app) as client:
        url = f'/contacts/{p.person}/visit-cell-suggestion'
        response = client.get(url)
        assert response.status_code == 200, response.text
        evidence = response.json()
        page = client.get('/cell-central/visit-cell-suggestions?page=1&page_size=1')
        assert page.status_code == 200 and page.json()['items'] == [evidence]
        for path in [f'/contacts/{foreign_id}/visit-cell-suggestion', f'/contacts/{uuid.uuid4()}/visit-cell-suggestion']:
            assert client.get(path).status_code == 404
            assert client.post(path + '/confirm', json=evidence).status_code == 404
        result = client.post(url + '/confirm', json=evidence)
        assert result.status_code == 200, result.text
        assert client.post(url + '/confirm', json=evidence).status_code == 200
    with p.factory() as db:
        assert db.get(Pessoa, p.person).acompanhamento == 'consolidado'
        assert db.scalar(select(WorkQueueItem.status).where(WorkQueueItem.pessoa_id == p.person)) == 'resolvido'


def test_chronological_order_stable_tie_and_new_earlier_evidence(candidate):
    import datetime as dt
    from app.visits.models import VisitEvent
    from app.visits.service import register_cell_visit
    p = candidate
    initial = read(p)
    with p.factory.begin() as db:
        original = db.get(VisitEvent, uuid.UUID(initial['evento_id']))
        first_meeting = db.get(CelulaReuniao, p.meeting)
        other = Celula(igreja_id=TENANT, nome='Outra cronológica sintética', ativo=True, lider_id=db.get(Celula, p.cell).lider_id, cobertura_espiritual='Teste')
        db.add(other); db.flush()
        tied = CelulaReuniao(igreja_id=TENANT, celula_id=other.id, data=first_meeting.data, hora=first_meeting.hora, status='planejada', relatorio_status='pendente')
        db.add(tied); db.flush()
        event = register_cell_visit(db, p.actors['lider_celula'], reuniao_id=tied.id, pessoa_id=p.person)
        # Privileged synthetic fixture sets an exact tie; runtime evidence is immutable.
        event.data_registro = original.data_registro
        event.id = uuid.UUID(int=1)
        db.flush()
    tied_evidence = read(p)
    assert tied_evidence['evento_id'] == str(uuid.UUID(int=1))
    assert read(p) == tied_evidence
    with pytest.raises(HTTPException) as exc:
        confirm(p, initial)
    assert exc.value.status_code == 409
    with p.factory.begin() as db:
        earlier = CelulaReuniao(igreja_id=TENANT, celula_id=p.cell, data=dt.date.today()-dt.timedelta(days=3), hora='19:30', status='planejada', relatorio_status='pendente')
        db.add(earlier); db.flush()
        earliest = register_cell_visit(db, p.actors['lider_celula'], reuniao_id=earlier.id, pessoa_id=p.person)
        earliest_id = earliest.id
    assert read(p)['evento_id'] == str(earliest_id)
    with pytest.raises(HTTPException):
        confirm(p, tied_evidence)


def test_concurrent_cell_deactivation_prevents_partial_link(candidate):
    p = candidate
    evidence = read(p)
    with p.factory() as writer, ThreadPoolExecutor(max_workers=1) as pool:
        cell = writer.scalar(select(Celula).where(Celula.id == p.cell).with_for_update())
        cell.ativo = False
        future = pool.submit(confirm, p, evidence)
        writer.commit()
        with pytest.raises(HTTPException) as exc:
            future.result(timeout=10)
        assert exc.value.status_code == 409
    with p.factory() as db:
        assert db.get(Pessoa, p.person).celula_id is None
        assert db.scalar(select(func.count()).select_from(CelulaMembro).where(CelulaMembro.pessoa_id == p.person)) == 0
