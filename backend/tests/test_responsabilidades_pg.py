"""Vigência por setor: API real e RLS em PostgreSQL sintético obrigatório."""
import os
from datetime import date
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.test_uv_turmas_pg import database, seeded, scoped, principal
from tests.conftest_rls import assert_disposable_database
from app.db.session import get_db
from app.deps import get_current_user

pytestmark = pytest.mark.rls_integration


@pytest.fixture(autouse=True)
def church_today(monkeypatch):
    monkeypatch.setattr('app.services.responsabilidades.hoje_da_igreja', lambda: date(2026, 10, 9))


@pytest.fixture(scope='module')
def rls_database_url():
    url = os.environ.get('RESPONSABILIDADES_TEST_DATABASE_URL') or os.environ['UV_TURMAS_DATABASE_URL']
    assert_disposable_database(url)
    from sqlalchemy.engine import make_url
    parsed = make_url(url)
    assert parsed.host == '127.0.0.1' and parsed.database == 'uv_turmas_test'
    return url


@pytest.fixture(scope='module', params=['fresh', 'upgrade'])
def migrated_database(rls_database_url, request):
    """Cadeia ativa completa via runner; upgrade conserva cadastro prévio."""
    import subprocess
    import sys
    from pathlib import Path
    from sqlalchemy import create_engine
    from scripts import migrate
    engine = create_engine(rls_database_url)
    with engine.begin() as c:
        c.exec_driver_sql('drop schema public cascade; create schema public')
        for role, bypass in (('anon',False),('authenticated',False),('service_role',True)):
            c.exec_driver_sql(f"do $$ begin if not exists(select 1 from pg_roles where rolname='{role}') then create role {role}; end if; end $$")
            c.exec_driver_sql(f"alter role {role} nologin {'bypassrls' if bypass else 'nobypassrls'}")
        c.exec_driver_sql('grant usage on schema public to anon, authenticated, service_role')
        for obj in ('tables','sequences','functions'):
            c.exec_driver_sql(f'alter default privileges in schema public grant all on {obj} to anon,authenticated,service_role')
        c.exec_driver_sql('create table schema_migrations(name text primary key)')
    legacy_tenant, legacy_person = uuid4(), uuid4()
    for name in migrate.migration_files():
        if name == '20261021_100000_responsabilidades_setor.sql' and request.param == 'upgrade':
            with engine.begin() as c:
                c.execute(text("insert into igrejas(id,nome) values(:t,'Legado sintético')"),dict(t=legacy_tenant))
                c.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'Pessoa sintética','550000000099')"),dict(t=legacy_tenant,p=legacy_person))
        body = (migrate.MIGRATIONS_DIR/name).read_text()
        command = [sys.executable,str(Path(migrate.__file__)),'apply',name,'--yes']
        if any('index concurrently' in line.lower() for line in body.splitlines() if not line.lstrip().startswith('--')):
            command.append('--no-transaction')
        result = subprocess.run(command,env=dict(os.environ,MIGRATION_DATABASE_URL=rls_database_url.replace('postgresql+psycopg2:', 'postgresql:')),capture_output=True,text=True)
        assert result.returncode == 0, f'{name}: {result.stderr}'
    if request.param == 'upgrade':
        with engine.connect() as c:
            assert c.scalar(text('select id from pessoas where id=:p'),dict(p=legacy_person)) == legacy_person
            assert c.scalar(text('select count(*) from responsabilidades_setor')) == 0
    yield engine
    engine.dispose()


@pytest.fixture
def api(database, seeded):
    from app.routers.responsabilidades import router
    app = FastAPI()
    app.include_router(router)
    def db():
        with scoped(database, seeded['t']) as s:
            yield s
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: principal(seeded)
    with TestClient(app) as client:
        yield client


def assign(api, v, **kw):
    data = dict(pessoa_id=str(v['p']), setor='consolidacao', inicio='2026-10-01', fim=None)
    data.update(kw)
    return api.post('/responsabilidades', json=data)


def test_interval_history_and_query(api, seeded, database):
    v = seeded
    response = assign(api, v)
    assert response.status_code == 201, response.text
    rid = response.json()['id']
    assert api.get('/responsabilidades', params={'em':'2026-09-30'}).json() == []
    assert len(api.get('/responsabilidades', params={'em':'2026-10-01'}).json()) == 1
    assert assign(api, v).status_code == 409
    assert api.post(f'/responsabilidades/{rid}/encerrar', json={'fim':'2026-10-15'}).status_code == 200
    assert assign(api, v, inicio='2026-10-15').status_code == 201
    assert len(api.get('/responsabilidades').json()) == 2
    assert len(api.get('/responsabilidades', params={'em':'2026-10-14'}).json()) == 1
    from app.services.responsabilidades import vigentes_em
    with scoped(database, v['t']) as s:
        assert vigentes_em(s, igreja_id=v['t'], em=date(2026,10,15))[0]['inicio'] == date(2026,10,15)
    assert api.post(f'/responsabilidades/{rid}/encerrar', json={'fim':'2026-10-16'}).status_code == 409


@pytest.mark.parametrize('role', ['lider_consol', 'operador', 'revogado', 'inativo'])
def test_live_permission_denial(api, seeded, database, role):
    with database.begin() as c:
        c.execute(text('delete from user_roles where user_id=:u'), {'u':seeded['uid']})
        if role != 'revogado':
            c.execute(text('insert into user_roles(igreja_id,user_id,papel) values(:t,:u,:r)'),dict(t=seeded['t'],u=seeded['uid'],r='admin' if role=='inativo' else role))
        if role == 'inativo':
            c.execute(text("update app_users set status='revogado' where id=:u"),dict(u=seeded['uid']))
    assert assign(api, seeded).status_code == 403
    assert api.get('/responsabilidades').status_code == 403


@pytest.mark.parametrize('kind', ['tenant','archived','invalid_dates','unknown_sector'])
def test_invalid_assignment(api, seeded, database, kind):
    v = seeded
    if kind in {'tenant','archived'}:
        with database.begin() as c:
            c.execute(text('update pessoas set igreja_id=:t where id=:p') if kind=='tenant' else text('update pessoas set arquivada_em=now() where id=:p'), dict(t=v['other'],p=v['p']))
    overrides = {'fim':'2026-10-01'} if kind=='invalid_dates' else {'setor':'qualquer'} if kind=='unknown_sector' else {}
    assert assign(api,v,**overrides).status_code == (404 if kind in {'tenant','archived'} else 422)


def test_rls_and_history_guards(api, seeded, database):
    v=seeded
    rid=assign(api,v).json()['id']
    with scoped(database,v['other']) as s:
        assert s.execute(text('select * from responsabilidades_setor')).all() == []
        assert s.execute(text('update responsabilidades_setor set fim=\'2026-10-02\' where id=:id'),dict(id=rid)).rowcount == 0
        with pytest.raises(DBAPIError):
            s.execute(text("insert into responsabilidades_setor(igreja_id,pessoa_id,setor,inicio,atribuida_por) values(:t,:p,'agenda','2026-10-01',:u)"),dict(t=v['t'],p=v['p'],u=v['uid']))
    for sql in ('delete from responsabilidades_setor', "update responsabilidades_setor set fim='2026-10-05'", "update responsabilidades_setor set inicio='2026-09-01'", "insert into responsabilidades_setor(igreja_id,pessoa_id,setor,inicio,atribuida_por) values(:t,:p,'consolidacao','2026-10-10',:u)"):
        with scoped(database,v['t']) as s, pytest.raises(DBAPIError):
            s.execute(text(sql),dict(t=v['t'],p=v['p'],u=v['uid']))
    with database.connect() as c:
        assert c.execute(text("select relrowsecurity,relforcerowsecurity from pg_class where oid='responsabilidades_setor'::regclass")).one() == (True,True)


def test_finite_intervals_boundaries_and_close_validation(api, seeded):
    row = assign(api,seeded,fim='2026-10-10').json()
    assert assign(api,seeded,inicio='2026-09-01',fim='2026-10-02').status_code==409
    assert assign(api,seeded,inicio='2026-10-09',fim='2026-10-12').status_code==409
    assert assign(api,seeded,inicio='2026-10-10',fim='2026-10-20').status_code==201
    assert api.post(f"/responsabilidades/{row['id']}/encerrar",json={'fim':'2026-10-11'}).status_code==422
    assert api.post(f"/responsabilidades/{row['id']}/encerrar",json={'fim':'2026-10-01'}).status_code==422
    url=f"/responsabilidades/{row['id']}/encerrar"
    first=api.post(url,json={'fim':'2026-10-09'})
    assert first.status_code==200
    assert api.post(url,json={'fim':'2026-10-09'}).json()==first.json()
    assert api.get('/responsabilidades',params={'em':'2026-10-09'}).json()==[]
    assert len(api.get('/responsabilidades',params={'limit':1}).json())==1
    assert assign(api,seeded,setor='agenda').status_code==201


def test_two_tenants_and_composite_fk(api, seeded, database):
    from app.services.responsabilidades import vigentes_em, encerrar
    from fastapi import HTTPException
    v=seeded
    row=assign(api,v).json()
    with scoped(database,v['other']) as s:
        assert vigentes_em(s,igreja_id=v['t'],em=date(2026,10,1))==[]
        with pytest.raises(HTTPException) as error:
            encerrar(s,principal(v,tenant='other'),row['id'],date(2026,10,2))
        assert error.value.status_code==403
    other_person, other_user = uuid4(), uuid4()
    with database.begin() as c:
        c.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'Outro tenant sintético','550000000077')"),dict(p=other_person,t=v['other']))
        c.execute(text("insert into app_users(id,igreja_id,status,nome,email) values(:u,:t,'ativo','Outro admin sintético','other@example.test')"),dict(u=other_user,t=v['other']))
        c.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:t,:u,'admin')"),dict(t=v['other'],u=other_user))
    from app.services.responsabilidades import atribuir
    from app.routers.responsabilidades import AtribuicaoInput
    from dataclasses import replace
    with scoped(database,v['other']) as s:
        user=replace(principal(v),igreja_id=str(v['other']),app_user_id=str(other_user))
        other_row=atribuir(s,user,AtribuicaoInput(pessoa_id=other_person,setor='consolidacao',inicio=date(2026,10,1)))
        assert other_row['igreja_id']==v['other']
        assert len(vigentes_em(s,igreja_id=v['other'],em=date(2026,10,1)))==1
        with pytest.raises(HTTPException) as error:
            encerrar(s,user,row['id'],date(2026,10,2))
        assert error.value.status_code==404
        s.commit()
    with scoped(database,v['t']) as s, pytest.raises(DBAPIError):
        s.execute(text("insert into responsabilidades_setor(igreja_id,pessoa_id,setor,inicio,atribuida_por) values(:t,:p,'agenda','2026-10-01',:u)"),dict(t=v['t'],p=other_person,u=v['uid']))


def test_concurrent_different_people_cannot_own_same_sector(api, seeded, database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.routers.responsabilidades import AtribuicaoInput
    from app.services.responsabilidades import atribuir
    from fastapi import HTTPException
    v=seeded
    second=uuid4()
    with database.begin() as c:
        c.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'Pessoa sintética 2','550000000088')"),dict(p=second,t=v['t']))
    barrier=Barrier(2)
    def attempt(pid):
        with scoped(database,v['t']) as s:
            barrier.wait(timeout=10)
            try:
                atribuir(s,principal(v),AtribuicaoInput(pessoa_id=pid,setor='agenda',inicio=date(2026,10,1)))
                s.commit()
                return 201
            except HTTPException as exc:
                s.rollback()
                return exc.status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(attempt,[v['p'],second]))==[201,409]


@pytest.mark.parametrize('role', ['admin', 'pastor'])
def test_today_boundary_and_real_role(api, seeded, database, role):
    from dataclasses import replace
    with database.begin() as c:
        c.execute(text('update user_roles set papel=:r where user_id=:u'), dict(r=role,u=seeded['uid']))
    api.app.dependency_overrides[get_current_user] = lambda: replace(principal(seeded), roles=frozenset({role}))
    row = assign(api, seeded)
    assert row.status_code == 201, row.text
    assert row.json()['atribuida_por'] == str(seeded['uid'])
    url = f"/responsabilidades/{row.json()['id']}/encerrar"
    rejected = api.post(url, json={'fim':'2026-10-08'})
    assert rejected.status_code == 422
    assert 'retroativo' in rejected.json()['detail']
    assert api.get('/responsabilidades').json()[0]['encerrada_em'] is None
    closed = api.post(url, json={'fim':'2026-10-09'})
    assert closed.status_code == 200, closed.text
    assert closed.json()['encerrada_por'] == str(seeded['uid'])


def test_concurrent_close_different_ends(api, seeded, database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.services.responsabilidades import encerrar
    from fastapi import HTTPException
    row = assign(api, seeded).json()
    barrier = Barrier(2)
    def attempt(end):
        with scoped(database, seeded['t']) as s:
            barrier.wait(timeout=10)
            try:
                result = encerrar(s, principal(seeded), row['id'], end)
                s.commit()
                return 200, result['fim']
            except HTTPException as exc:
                s.rollback()
                return exc.status_code, end
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, [date(2026,10,9), date(2026,10,10)]))
    assert sorted(status for status, _ in results) == [200, 409]
    winner = next(end for status, end in results if status == 200)
    assert api.get('/responsabilidades').json()[0]['fim'] == winner.isoformat()


def test_cross_tenant_authors_and_closed_extension_fail_sql(api, seeded, database):
    other_user = uuid4()
    with database.begin() as c:
        c.execute(text("insert into app_users(id,igreja_id,status,nome,email) values(:u,:t,'ativo','Autor sintético','author@example.test')"), dict(u=other_user,t=seeded['other']))
    row = assign(api, seeded).json()
    with scoped(database, seeded['t']) as s, pytest.raises(DBAPIError) as error:
        s.execute(text("insert into responsabilidades_setor(igreja_id,pessoa_id,setor,inicio,atribuida_por) values(:t,:p,'agenda','2026-10-01',:u)"), dict(t=seeded['t'],p=seeded['p'],u=other_user))
    assert error.value.orig.pgcode == '23503'
    with scoped(database, seeded['t']) as s, pytest.raises(DBAPIError) as error:
        s.execute(text("update responsabilidades_setor set fim='2026-10-09',encerrada_por=:u,encerrada_em=clock_timestamp() where id=:id"), dict(u=other_user,id=row['id']))
    assert error.value.orig.pgcode == '23503'
    assert api.post(f"/responsabilidades/{row['id']}/encerrar", json={'fim':'2026-10-09'}).status_code == 200
    with scoped(database, seeded['t']) as s, pytest.raises(DBAPIError) as error:
        s.execute(text("update responsabilidades_setor set fim='2026-10-10' where id=:id"), dict(id=row['id']))
    assert error.value.orig.pgcode == '23514'
    with database.connect() as c:
        for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
            assert not c.scalar(text("select has_table_privilege('service_role','responsabilidades_setor',:p)"), dict(p=privilege))
