"""Hoje usa responsabilidades vigentes sem conceder autorização de domínio."""
from datetime import date
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.test_responsabilidades_pg import rls_database_url, migrated_database
from tests.test_uv_turmas_pg import database, seeded, scoped, principal
from app.db.session import get_db
from app.deps import get_current_user
from app.routers.work_queue import router

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def api(database, seeded, monkeypatch):
    monkeypatch.setattr('app.datas.hoje_da_igreja', lambda: date(2026, 10, 20))
    app = FastAPI()
    app.include_router(router)
    def db():
        with scoped(database, seeded['t']) as s:
            yield s
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: principal(seeded, 'leader')
    with TestClient(app) as client:
        yield client


def responsibility(database, v, *, setor='consolidacao', inicio='2026-10-20', fim=None, tenant=None, person=None, closed=False):
    with database.begin() as c:
        pid = person or c.scalar(text('select pessoa_id from app_users where id=:u'), dict(u=v['leader']))
        c.execute(text('''insert into responsabilidades_setor
            (igreja_id,pessoa_id,setor,inicio,fim,atribuida_por,encerrada_em,encerrada_por)
            values(:t,:p,:s,:i,:f,:u,case when :closed then now() end,case when :closed then :u end)'''),
            dict(t=tenant or v['t'],p=pid,s=setor,i=inicio,f=fim,u=v['uid'],closed=closed))


@pytest.fixture
def queue(database, seeded):
    with database.begin() as c:
        c.execute(text('delete from work_queue_items'))
        for tenant in (seeded['t'], seeded['other']):
            for tipo in ('visitante','fonovisita','conectar_celula','relatorio','atendimento'):
                c.execute(text("insert into work_queue_items(id,igreja_id,tipo,titulo,status) values(:id,:t,:tipo,'Pendência sintética','aberto')"),dict(id=uuid4(),t=tenant,tipo=tipo))


@pytest.mark.parametrize('path', ['/work-queue', '/work-queue/snapshot'])
@pytest.mark.parametrize('period,expected', [
    ({},3), ({'inicio':'2026-10-21'},0),
    ({'inicio':'2026-10-01','fim':'2026-10-20'},0),
    ({'inicio':'2026-10-01','fim':'2026-10-21'},3),
    ({'inicio':'2026-10-01','fim':'2026-10-21','closed':True},3),
    ({'inicio':'2026-10-01','fim':'2026-10-19','closed':True},0),
    ({'setor':'agenda'},0),
])
def test_live_period_and_sector(api, database, seeded, queue, path, period, expected):
    responsibility(database, seeded, **period)
    response = api.get(path, params={'hoje':True})
    assert response.status_code == 200, response.text
    assert response.json()['total'] == expected
    assert {i['tipo'] for i in response.json()['items']} <= {'visitante','fonovisita','conectar_celula'}


@pytest.mark.parametrize('path', ['/work-queue', '/work-queue/snapshot'])
@pytest.mark.parametrize('status', [None, 'ativo', 'inativo', 'suspenso', 'revogado'])
def test_live_user_status(api, database, seeded, queue, path, status):
    responsibility(database, seeded)
    # Only in this disposable PG: exercise denied states absent from today's enum.
    with database.begin() as c:
        c.execute(text("alter type app_user_status add value if not exists 'inativo'"))
        c.execute(text("alter type app_user_status add value if not exists 'suspenso'"))
    with database.begin() as c:
        c.execute(text('update app_users set status=:status where id=:u'),
                  dict(status=status, u=seeded['leader']))
    response = api.get(path, params={'hoje': True})
    assert response.status_code == (200 if status in (None, 'ativo') else 403), response.text
    if response.status_code == 200:
        assert response.json()['total'] == 3
        assert {i['tipo'] for i in response.json()['items']} == {'visitante', 'fonovisita', 'conectar_celula'}


@pytest.mark.parametrize('change', ['unlinked','archived','revoked','no_role','other_person','no_responsibility'])
def test_revalidation_each_use(api, database, seeded, queue, change):
    if change != 'no_responsibility':
        responsibility(database, seeded)
        assert api.get('/work-queue?hoje=true').json()['total'] == 3
    with database.begin() as c:
        if change == 'unlinked':
            c.execute(text('update app_users set pessoa_id=null where id=:u'),dict(u=seeded['leader']))
        elif change == 'archived':
            c.execute(text('update pessoas set arquivada_em=now() where id=(select pessoa_id from app_users where id=:u)'),dict(u=seeded['leader']))
        elif change == 'revoked':
            c.execute(text("update app_users set status='revogado' where id=:u"),dict(u=seeded['leader']))
        elif change == 'no_role':
            c.execute(text('delete from user_roles where user_id=:u'),dict(u=seeded['leader']))
        elif change == 'other_person':
            c.execute(text('update app_users set pessoa_id=:p where id=:u'),dict(u=seeded['leader'],p=seeded['p']))
    response = api.get('/work-queue?hoje=true')
    assert response.status_code == (403 if change == 'revoked' else 200)
    if response.status_code == 200:
        assert response.json()['total'] == 0


@pytest.mark.parametrize('role', ['admin','pastor'])
def test_pastor_admin_keep_current_scope(api, database, seeded, queue, role):
    with database.begin() as c:
        c.execute(text('update user_roles set papel=:r where user_id=:u'),dict(r=role,u=seeded['leader']))
    assert api.get('/work-queue?hoje=true').json()['total'] == 5


def test_responsibility_never_grants_permission(api, database, seeded, queue):
    responsibility(database, seeded, setor='atendimento')
    # Principal deliberately claims admin; actual role is lider_consol.
    assert api.get('/work-queue?hoje=true').json()['total'] == 0


def test_central_rechecks_live_roles_without_granting_access(api, database, seeded, queue):
    from app.routers.cell_central import router as central
    api.app.include_router(central)
    responsibility(database, seeded, setor='central_celulas')
    assert api.get('/cell-central/dashboard?hoje=true').status_code == 403
    with database.begin() as c:
        c.execute(text("update user_roles set papel='pastor' where user_id=:u"),dict(u=seeded['leader']))
    response = api.get('/cell-central/dashboard?hoje=true')
    assert response.status_code == 200, response.text


def test_other_church_and_person_cannot_supply_scope(api, database, seeded, queue):
    other_person, other_user = uuid4(), uuid4()
    with database.begin() as c:
        c.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'Pessoa sintética','550000000078')"),dict(p=other_person,t=seeded['other']))
        c.execute(text("insert into app_users(id,igreja_id,status,nome,email) values(:u,:t,'ativo','Equipe sintética','other@example.test')"),dict(u=other_user,t=seeded['other']))
        c.execute(text("insert into responsabilidades_setor(igreja_id,pessoa_id,setor,inicio,atribuida_por) values(:t,:p,'consolidacao','2026-10-01',:u)"),dict(t=seeded['other'],p=other_person,u=other_user))
    assert api.get('/work-queue?hoje=true').json()['total'] == 0
    responsibility(database, seeded, person=seeded['p'])
    assert api.get('/work-queue?hoje=true').json()['total'] == 0
    from app.services.hoje import escopo_vigente
    with scoped(database, seeded['other']) as s:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as error:
            escopo_vigente(s, principal(seeded, 'leader'))
        assert error.value.status_code == 403


def test_pagination_revalidates_at_end_of_period(api, database, seeded, queue, monkeypatch):
    responsibility(database, seeded, fim='2026-10-21')
    first = api.get('/work-queue/snapshot?hoje=true&pageSize=1').json()
    assert first['total'] == 3
    second = api.get('/work-queue/snapshot', params=dict(hoje=True,page=2,pageSize=1,revision=first['revision']))
    assert second.status_code == 200
    assert len(second.json()['items']) == 1
    monkeypatch.setattr('app.datas.hoje_da_igreja', lambda: date(2026, 10, 21))
    assert api.get('/work-queue/snapshot', params=dict(hoje=True,page=3,pageSize=1,revision=first['revision'])).status_code == 409
    assert api.get('/work-queue/snapshot?hoje=true').json()['total'] == 0
