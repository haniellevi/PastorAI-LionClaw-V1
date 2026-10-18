"""Real PG proof: the runner, tenant RLS, domain service and authenticated API."""
import datetime as dt
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.tenant_session import mark_tenant_scoped
from app.deps import CurrentUser, get_current_user
from app.routers.uv import router, TurmaInput, CalendarioInput, ResponsaveisInput, MatriculaInput
from app.services import uv
from tests.conftest_rls import assert_disposable_database

pytestmark = pytest.mark.rls_integration
ROOT = Path(__file__).resolve().parents[1]
MIGRATION = '20261017_210500_uv_turmas.sql'


@pytest.fixture
def rls_database_url():
    url = os.environ.get('UV_TURMAS_DATABASE_URL', '').strip()
    if not url:
        pytest.skip('UV_TURMAS_DATABASE_URL não definida para PostgreSQL descartável')
    assert_disposable_database(url)
    parsed = urlsplit(url)
    if parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.path != '/uv_turmas_test':
        raise RuntimeError('UV exige banco local descartável exclusivo uv_turmas_test')
    return url


@pytest.fixture
def database(rls_database_url):
    assert_disposable_database(rls_database_url)
    engine = create_engine(rls_database_url)
    with engine.begin() as c:
        c.exec_driver_sql('''drop schema public cascade; create schema public;
        do $$ begin
          if not exists(select 1 from pg_roles where rolname='authenticated') then
            create role authenticated nologin nobypassrls; end if;
          if not exists(select 1 from pg_roles where rolname='anon') then
            create role anon nologin nobypassrls; end if;
        end $$;
        create table schema_migrations(name text primary key);
        grant usage on schema public to authenticated;
        create function current_igreja_id() returns uuid language sql stable as
          $$ select nullif(current_setting('app.tenant_igreja_id',true),'')::uuid $$;
        create table igrejas(id uuid primary key);
        create table pessoas(id uuid primary key, igreja_id uuid not null references igrejas,
          nome text not null, celula_id uuid, arquivada_em timestamptz, unique(igreja_id,id));
        create table app_users(id uuid primary key, igreja_id uuid not null references igrejas,
          pessoa_id uuid, status text not null, unique(igreja_id,id));
        create table user_roles(id uuid primary key default gen_random_uuid(), igreja_id uuid not null,
          user_id uuid not null, papel text not null);
        create table decisions(id uuid primary key default gen_random_uuid(), igreja_id uuid not null,
          pessoa_id uuid not null);
        create table consolidacoes(id uuid primary key default gen_random_uuid(), igreja_id uuid not null,
          pessoa_id uuid not null, responsavel_id uuid, tipo text default 'individual',
          abandonada_em timestamptz, created_at timestamptz default now());
        grant select,insert,update on pessoas,app_users,user_roles,decisions,consolidacoes to authenticated;
        ''')
    # Use the same official runner authorized for deployments; no raw apply.
    env = dict(os.environ, MIGRATION_DATABASE_URL=rls_database_url.replace('postgresql+psycopg2:', 'postgresql:'))
    subprocess.run([sys.executable, str(ROOT/'scripts/migrate.py'), 'apply', MIGRATION, '--yes'],
                   env=env, check=True, capture_output=True)
    yield engine
    engine.dispose()


@pytest.fixture
def seeded(database):
    t, other, uid, leader, outsider, p = [uuid4() for _ in range(6)]
    with database.begin() as c:
        for tenant in (t, other):
            c.execute(text('insert into igrejas values(:t)'), dict(t=tenant))
        for u, role in ((uid,'admin'), (leader,'lider_consol'), (outsider,'operador')):
            c.execute(text("insert into app_users(id,igreja_id,status) values(:u,:t,'ativo')"), dict(u=u,t=t))
            c.execute(text('insert into user_roles(igreja_id,user_id,papel) values(:t,:u,:r)'), dict(t=t,u=u,r=role))
        c.execute(text("insert into pessoas(id,igreja_id,nome) values(:p,:t,'Aluno sintético')"), dict(p=p,t=t))
        c.execute(text('insert into decisions(igreja_id,pessoa_id) values(:t,:p)'), dict(p=p,t=t))
        c.execute(text('insert into consolidacoes(igreja_id,pessoa_id,responsavel_id) values(:t,:p,:u)'), dict(p=p,t=t,u=uid))
    return dict(t=t, other=other, uid=uid, leader=leader, outsider=outsider, p=p)


def principal(v, key='uid', tenant='t'):
    # Deliberately claim admin even for the outsider; service must revalidate.
    return CurrentUser(app_user_id=str(v[key]), igreja_id=str(v[tenant]),
                       clerk_user_id='synthetic', email='synthetic@example.test', nome='Sintético', roles=frozenset({'admin'}))


def scoped(engine, tenant):
    s = Session(engine)
    mark_tenant_scoped(s, tenant, source='uv_pg_test')
    assert s.execute(text('select current_user')).scalar_one() == 'authenticated'
    assert s.execute(text('select rolbypassrls from pg_roles where rolname=current_user')).scalar_one() is False
    return s


def create(s, v, key='uid'):
    return uv.create_turma(s, principal(v,key), TurmaInput(id=uuid4(), nome='Turma sintética'))['id']


def matricula(v):
    return MatriculaInput(id=uuid4(), pessoa_id=v['p'])


def schedule():
    curriculum = [('aula', n) for n in range(1,5)] + [('encontro',None)] + [('aula', n) for n in range(5,9)]
    return CalendarioInput(atividades=[dict(ordem=i,tipo=tipo,aula=aula,data=dt.date(2026,10,1)+dt.timedelta(weeks=i))
        for i,(tipo,aula) in enumerate(curriculum,1)])


def test_complete_panel_api_and_idempotent_calendar(database, seeded):
    v=seeded
    app=FastAPI(); app.include_router(router)
    def db():
        with scoped(database,v['t']) as s:
            yield s
    app.dependency_overrides[get_db]=db
    app.dependency_overrides[get_current_user]=lambda: principal(v)
    with TestClient(app) as client:
        tid=str(uuid4()); payload=dict(id=tid,nome='Turma teste')
        assert client.post('/uv/turmas',json=payload).status_code==200
        assert client.post('/uv/turmas',json=payload).status_code==200
        cal=schedule().model_dump(mode='json')
        for _ in range(2):
            response=client.put(f'/uv/turmas/{tid}/calendario',json=cal)
            assert response.status_code==200, response.text
            assert len(response.json()['atividades'])==9
        enrollment=matricula(v).model_dump(mode='json')
        for _ in range(2):
            assert client.post(f'/uv/turmas/{tid}/matriculas',json=enrollment).status_code==200
        detail=client.get(f'/uv/turmas/{tid}').json()
        assert len(detail['matriculas'])==1
        assert detail['matriculas'][0]['conexao_celula_pendente'] is True
        assert set(detail['matriculas'][0])=={'id','pessoa_id','nome','conexao_celula_pendente'}
        assert len(client.get('/uv/turmas').json())==1
        assert client.post(f'/uv/turmas/{tid}/encerrar').status_code==200
        assert client.post(f'/uv/turmas/{tid}/matriculas',json=matricula(v).model_dump(mode='json')).status_code==409


@pytest.mark.parametrize('missing', ['decision','responsible','person'])
def test_entry_requirements(database, seeded, missing):
    v=seeded
    with database.begin() as c:
        if missing=='decision': c.execute(text('delete from decisions'))
        if missing=='responsible': c.execute(text('update consolidacoes set responsavel_id=null'))
        if missing=='person': c.execute(text('update pessoas set arquivada_em=now()'))
    with scoped(database,v['t']) as s:
        tid=create(s,v)
        with pytest.raises(HTTPException) as exc: uv.enroll(s,principal(v),tid,matricula(v))
        assert exc.value.status_code==(404 if missing=='person' else 422)


def test_duplicates_and_reused_keys(database, seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid=create(s,v); p=matricula(v)
        uv.enroll(s,principal(v),tid,p)
        assert uv.enroll(s,principal(v),tid,p)['id']==p.id
        with pytest.raises(HTTPException) as exc: uv.enroll(s,principal(v),tid,matricula(v))
        assert exc.value.status_code==409
        other=create(s,v)
        with pytest.raises(HTTPException) as exc: uv.enroll(s,principal(v),other,p)
        assert exc.value.status_code==409
        with pytest.raises(HTTPException) as exc: uv.create_turma(s,principal(v),TurmaInput(id=tid,nome='Outro nome'))
        assert exc.value.status_code==409


@pytest.mark.parametrize('operation', ['list','create','detail','calendar','enroll','responsible','close'])
def test_outsider_denied_despite_stale_claims(database,seeded,operation):
    v=seeded
    with scoped(database,v['t']) as s:
        tid=create(s,v); u=principal(v,'outsider')
        calls=dict(list=lambda:uv.list_turmas(s,u), create=lambda:create(s,v,'outsider'),
            detail=lambda:uv.get_turma(s,u,tid), calendar=lambda:uv.calendar(s,u,tid,schedule()),
            enroll=lambda:uv.enroll(s,u,tid,matricula(v)),
            responsible=lambda:uv.responsaveis(s,u,tid,ResponsaveisInput(usuarios=[])), close=lambda:uv.close(s,u,tid))
        with pytest.raises(HTTPException) as exc: calls[operation]()
        assert exc.value.status_code==403


def test_responsible_scope_removal_and_revocation(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid=create(s,v); own=create(s,v,'leader')
        assert [r['id'] for r in uv.list_turmas(s,principal(v,'leader'))]==[own]
        with pytest.raises(HTTPException): uv.get_turma(s,principal(v,'leader'),tid)
        uv.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        assert uv.get_turma(s,principal(v,'leader'),tid)['id']==tid
        uv.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[]))
        with pytest.raises(HTTPException): uv.get_turma(s,principal(v,'leader'),tid)
        s.execute(text("update app_users set status='revogado' where id=:u"), dict(u=v['leader']))
        with pytest.raises(HTTPException) as exc: uv.get_turma(s,principal(v,'leader'),own)
        assert exc.value.status_code==403
        with pytest.raises(HTTPException) as exc: uv.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        assert exc.value.status_code==422


def test_role_revocation_revalidated(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid=create(s,v,'leader')
        # Update role under provisioning connection, then start a fresh request.
        s.commit()
    with database.begin() as c: c.execute(text("delete from user_roles where user_id=:u"), dict(u=v['leader']))
    with scoped(database,v['t']) as s:
        with pytest.raises(HTTPException) as exc: uv.get_turma(s,principal(v,'leader'),tid)
        assert exc.value.status_code==403


@pytest.mark.parametrize('table', ['uv_turmas','uv_atividades','uv_responsaveis','uv_matriculas'])
def test_rls_isolation_using_and_with_check(database,seeded,table):
    v=seeded
    with scoped(database,v['t']) as s:
        tid=create(s,v); uv.calendar(s,principal(v),tid,schedule()); uv.enroll(s,principal(v),tid,matricula(v)); s.commit()
    with scoped(database,v['other']) as s:
        assert s.execute(text(f'select count(*) from {table}')).scalar_one()==0
        assert s.execute(text(f'update {table} set igreja_id=:t'),dict(t=v['other'])).rowcount==0
        with pytest.raises(ProgrammingError):
            if table=='uv_turmas':
                s.execute(text("insert into uv_turmas(id,igreja_id,nome) values(:id,:t,'X')"), dict(id=uuid4(),t=v['t']))
            elif table=='uv_atividades':
                s.execute(text("insert into uv_atividades(igreja_id,turma_id,ordem,tipo,aula,data) values(:t,:id,1,'aula',1,current_date)"),dict(t=v['t'],id=tid))
            elif table=='uv_responsaveis':
                s.execute(text('insert into uv_responsaveis(igreja_id,turma_id,usuario_id) values(:t,:id,:u)'),dict(t=v['t'],id=tid,u=v['leader']))
            else:
                s.execute(text('insert into uv_matriculas(id,igreja_id,turma_id,pessoa_id) values(:m,:t,:id,:p)'),dict(m=uuid4(),t=v['t'],id=tid,p=v['p']))


@pytest.mark.parametrize('edge',['activity_turma','responsible_turma','responsible_user','enrollment_turma','enrollment_person'])
def test_composite_foreign_keys(database,seeded,edge):
    v=seeded
    with scoped(database,v['t']) as s: tid=create(s,v); s.commit()
    with database.begin() as c:
        ot=uuid4(); ou=uuid4(); op=uuid4()
        c.execute(text("insert into uv_turmas(id,igreja_id,nome) values(:id,:t,'Outra')"),dict(id=ot,t=v['other']))
        c.execute(text("insert into app_users(id,igreja_id,status) values(:id,:t,'ativo')"),dict(id=ou,t=v['other']))
        c.execute(text("insert into pessoas(id,igreja_id,nome) values(:id,:t,'Outra')"),dict(id=op,t=v['other']))
    with scoped(database,v['t']) as s:
        with pytest.raises(IntegrityError) as exc:
            if edge=='activity_turma':
                s.execute(text("insert into uv_atividades(igreja_id,turma_id,ordem,tipo,aula,data) values(:t,:id,1,'aula',1,current_date)"),dict(t=v['t'],id=ot))
            elif edge.startswith('responsible'):
                s.execute(text('insert into uv_responsaveis(igreja_id,turma_id,usuario_id) values(:t,:id,:u)'),dict(t=v['t'],id=ot if edge.endswith('turma') else tid,u=ou if edge.endswith('user') else v['uid']))
            else:
                s.execute(text('insert into uv_matriculas(id,igreja_id,turma_id,pessoa_id) values(:m,:t,:id,:p)'),dict(m=uuid4(),t=v['t'],id=ot if edge.endswith('turma') else tid,p=op if edge.endswith('person') else v['p']))
        assert exc.value.orig.pgcode=='23503'


def test_service_cross_tenant_and_grants(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s: tid=create(s,v); s.commit()
    with scoped(database,v['other']) as s:
        with pytest.raises(HTTPException): uv.get_turma(s,principal(v,tenant='other'),tid)
        for table in ('uv_turmas','uv_atividades','uv_responsaveis','uv_matriculas'):
            assert not s.execute(text("select has_table_privilege(current_user,:t,'DELETE')"),dict(t=table)).scalar_one()
    with database.connect() as c:
        flags=c.execute(text("select relrowsecurity,relforcerowsecurity from pg_class where relname like 'uv_%' and relkind='r'")).all()
        assert len(flags)==4 and all(a and b for a,b in flags)


@pytest.mark.parametrize('role', ['admin','pastor','lider_consol'])
def test_all_approved_writer_roles(database,seeded,role):
    v=seeded
    with database.begin() as c:
        c.execute(text('update user_roles set papel=:r where user_id=:u'),dict(r=role,u=v['uid']))
    with scoped(database,v['t']) as s:
        tid=create(s,v)
        uv.calendar(s,principal(v),tid,schedule())
        assert uv.enroll(s,principal(v),tid,matricula(v))['id']


def test_retry_creation_does_not_restore_removed_responsibility(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid=create(s,v,'leader')
        uv.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[]))
        with pytest.raises(HTTPException) as exc:
            uv.create_turma(s,principal(v,'leader'),TurmaInput(id=tid,nome='Turma sintética'))
        assert exc.value.status_code==403
        assert uv.list_turmas(s,principal(v,'leader'))==[]


def test_service_isolates_even_with_bypassrls_connection(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s: tid=create(s,v); s.commit()
    with database.begin() as c:
        c.execute(text("insert into app_users(id,igreja_id,status) values(:u,:t,'ativo')"),dict(u=v['other'],t=v['other']))
        c.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:t,:u,'admin')"),dict(u=v['other'],t=v['other']))
    with Session(database) as s:
        other_user=principal(v,key='other',tenant='other')
        assert uv.list_turmas(s,other_user)==[]
        with pytest.raises(HTTPException) as exc: uv.get_turma(s,other_user,tid)
        assert exc.value.status_code==404
        with pytest.raises(HTTPException) as exc: uv.enroll(s,other_user,tid,matricula(v))
        assert exc.value.status_code==404


def test_picker_is_minimal_and_enrollment_not_automatic(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid=create(s,v)
        options=uv.options(s,principal(v),'sintétic')
        assert options['pessoas']==[dict(id=v['p'],nome='Aluno sintético')]
        assert all(set(u)=={'id','nome'} for u in options['usuarios'])
        assert uv.get_turma(s,principal(v),tid)['matriculas']==[]
        assert uv.options(s,principal(v),'%')['pessoas']==[]


def test_same_person_allowed_in_different_turmas(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        for _ in range(2): uv.enroll(s,principal(v),create(s,v),matricula(v))
        assert s.execute(text('select count(*) from uv_matriculas')).scalar_one()==2


def test_calendar_rejects_invalid_or_reversed_schedule(database,seeded):
    from pydantic import ValidationError
    data=schedule().model_dump()
    data['atividades'][0]['aula']=8
    with pytest.raises(ValidationError): CalendarioInput(**data)
    data=schedule().model_dump(); data['atividades'][0]['data']=dt.date(2030,1,1)
    with pytest.raises(ValidationError): CalendarioInput(**data)


def test_replay_committed_enrollment_after_closure(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid=create(s,v); payload=matricula(v)
        uv.enroll(s,principal(v),tid,payload); uv.close(s,principal(v),tid)
        assert uv.enroll(s,principal(v),tid,payload)=={'id':payload.id}
        with pytest.raises(HTTPException) as exc: uv.enroll(s,principal(v),tid,matricula(v))
        assert exc.value.status_code==409


def test_http_denies_unauthorized_user(database,seeded):
    v=seeded
    app=FastAPI(); app.include_router(router)
    def db():
        with scoped(database,v['t']) as s: yield s
    app.dependency_overrides[get_db]=db
    app.dependency_overrides[get_current_user]=lambda:principal(v,'outsider')
    with TestClient(app) as client:
        assert client.get('/uv/turmas').status_code==403
        assert client.get('/uv/turmas/opcoes').status_code==403
        assert client.post('/uv/turmas',json=dict(id=str(uuid4()),nome='Negada')).status_code==403


def test_concurrent_enrollment_same_key_commits_once(database,seeded):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    v=seeded
    with scoped(database,v['t']) as s: tid=create(s,v); s.commit()
    payload=matricula(v); barrier=Barrier(2)
    def attempt():
        with scoped(database,v['t']) as s:
            barrier.wait(timeout=10)
            result=uv.enroll(s,principal(v),tid,payload)
            s.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(attempt); b=pool.submit(attempt)
        assert a.result(timeout=15)==b.result(timeout=15)=={'id':payload.id}
    with scoped(database,v['t']) as s:
        assert s.execute(text('select count(*) from uv_matriculas')).scalar_one()==1


@pytest.mark.parametrize('table', ['uv_turmas','uv_atividades','uv_responsaveis','uv_matriculas'])
def test_rls_rejects_moving_visible_record_to_other_tenant(database,seeded,table):
    v=seeded
    with scoped(database,v['t']) as s:
        tid=create(s,v); uv.calendar(s,principal(v),tid,schedule()); uv.enroll(s,principal(v),tid,matricula(v)); s.commit()
    with scoped(database,v['t']) as s:
        with pytest.raises(ProgrammingError) as exc:
            s.execute(text(f'update {table} set igreja_id=:t'),dict(t=v['other']))
        assert exc.value.orig.pgcode=='42501'


def test_legacy_cross_tenant_person_responsible_cannot_authorize_enrollment(database,seeded):
    v=seeded
    with database.begin() as c:
        c.execute(text("insert into app_users(id,igreja_id,status) values(:u,:t,'ativo')"),dict(u=v['other'],t=v['other']))
        c.execute(text('update consolidacoes set responsavel_id=:u'),dict(u=v['other']))
    with scoped(database,v['t']) as s:
        tid=create(s,v)
        assert uv.options(s,principal(v),'')['pessoas']==[]
        with pytest.raises(HTTPException) as exc: uv.enroll(s,principal(v),tid,matricula(v))
        assert exc.value.status_code==422
