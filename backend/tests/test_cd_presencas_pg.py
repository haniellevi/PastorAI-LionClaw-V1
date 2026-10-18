"""CD attendance against the complete synthetic migration chain."""
from datetime import date, timedelta
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from tests.test_uv_turmas_pg import rls_database_url, migrated_database, database, seeded, scoped, principal
from tests.test_cd_turmas_pg import create, denied
from tests.test_cd_matriculas_pg import legacy, command
from app.routers.cd import CalendarioInput, ResponsaveisInput
from app.routers.uv import PresencaInput
from app.services import cd
pytestmark = pytest.mark.rls_integration


def setup(s,v):
    legacy(s,v); tid=create(s,v)
    detail=cd.get_turma(s,principal(v),tid)
    aulas=detail['modulo']['aulas']
    cd.calendar(s,principal(v),tid,CalendarioInput(aulas=[dict(aula_id=a['id'],data=date(2020,1,1)+timedelta(days=i)) for i,a in enumerate(aulas)]))
    mid=cd.enroll(s,principal(v),tid,command(v))['id']
    return tid,mid,aulas[0]['id']


def payload(**kw):
    return PresencaInput(**(dict(id=uuid4(),presente=True,modalidade='regular')|kw))


def test_history_idempotency_summary(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid,a=setup(s,v); p=payload(presente=False)
        first=cd.attendance(s,principal(v),tid,mid,a,p)
        assert cd.attendance(s,principal(v),tid,mid,a,p)==first
        denied(lambda:cd.attendance(s,principal(v),tid,mid,a,payload(id=p.id)),409)
        denied(lambda:cd.attendance(s,principal(v),tid,mid,a,payload()),409)
        cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        corrected=payload(modalidade='reposicao',anterior_id=p.id)
        cd.attendance(s,principal(v,'leader'),tid,mid,a,corrected)
        assert cd.attendance(s,principal(v),tid,mid,a,p)==first
        denied(lambda:cd.attendance(s,principal(v),tid,mid,a,payload(anterior_id=p.id)),409)
        history=cd.attendance_history(s,principal(v),tid,mid,a)
        assert [h['presente'] for h in history]==[False,True]
        assert [h['registrada_por'] for h in history]==[v['uid'],v['leader']]
        assert all(h['registrada_por_nome']=='Equipe sintética' for h in history)
        assert history[1]['registrada_em']>history[0]['registrada_em']
        assert cd.attendance_summary(s,principal(v),tid)==[dict(matricula_id=mid,aulas_cumpridas=[a])]
        s.commit()
    for sql in ['update cd_presencas_historico set presente=false','delete from cd_presencas_historico']:
        with scoped(database,v['t']) as s, pytest.raises(ProgrammingError): s.execute(text(sql))


@pytest.mark.parametrize('state',['unlinked','removed','revoked','cancelled','future','closed','other_lesson','invalid_replacement'])
def test_guards(database,seeded,state):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid,a=setup(s,v)
        if state!='unlinked': cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        if state=='removed': cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[]))
        if state=='cancelled': cd.cancel_enrollment(s,principal(v),tid,mid)
        if state=='closed': cd.close(s,principal(v),tid)
        if state=='future': s.execute(text('update cd_calendario set data=:d where turma_id=:tid'),dict(d=date(2100,1,1),tid=tid))
        if state=='other_lesson': a=uuid4()
        s.commit()
    with database.begin() as c:
        if state=='revoked': c.execute(text("update app_users set status='revogado' where id=:u"),dict(u=v['leader']))
    with scoped(database,v['t']) as s:
        u=principal(v,'leader') if state in {'unlinked','removed','revoked'} else principal(v,tenant='other') if state=='other_tenant' else principal(v)
        expected=404 if state in {'unlinked','removed','other_tenant'} else 403 if state=='revoked' else 422 if state in {'other_lesson','invalid_replacement'} else 409
        p=payload(presente=False,modalidade='reposicao') if state=='invalid_replacement' else payload()
        denied(lambda:cd.attendance(s,u,tid,mid,a,p),expected)


@pytest.mark.parametrize('same_key',[True,False])
@pytest.mark.parametrize('correction',[True,False])
def test_concurrency(database,seeded,same_key,correction):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid,a=setup(s,v); previous=payload(presente=False)
        if correction: cd.attendance(s,principal(v),tid,mid,a,previous)
        s.commit()
    one=payload(anterior_id=previous.id if correction else None)
    commands=[one,one if same_key else payload(anterior_id=one.anterior_id)]
    barrier=Barrier(2)
    def attempt(p):
        with scoped(database,v['t']) as s:
            barrier.wait(timeout=10)
            try: cd.attendance(s,principal(v),tid,mid,a,p); s.commit(); return 200
            except HTTPException as exc: s.rollback(); return exc.status_code
    with ThreadPoolExecutor(2) as pool: results=list(pool.map(attempt,commands))
    assert sorted(results)==([200,200] if same_key else [200,409])
    with scoped(database,v['t']) as s:
        assert len(cd.attendance_history(s,principal(v),tid,mid,a))==(2 if correction else 1)


def test_http_and_tenant_rls(database,seeded):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.deps import get_current_user
    from app.db.session import get_db
    from app.routers.cd import router
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid,a=setup(s,v); s.commit()
    app=FastAPI(); app.include_router(router)
    def db():
        with scoped(database,v['t']) as s: yield s
    app.dependency_overrides[get_db]=db
    app.dependency_overrides[get_current_user]=lambda:principal(v)
    path=f'/cd/turmas/{tid}/matriculas/{mid}/presencas/{a}'
    with TestClient(app) as client:
        p=payload(); first=client.post(path,json=p.model_dump(mode='json'))
        assert first.status_code==200,first.text
        assert client.post(path,json=p.model_dump(mode='json')).json()==first.json()
        assert client.post(path,json=payload(modalidade='reposicao',presente=False).model_dump(mode='json')).status_code==422
        assert client.post(path,json=payload().model_dump(mode='json')).status_code==409
        history=client.get(path+'/historico').json()
        assert history[0]['registrada_por_nome']=='Equipe sintética'
        assert client.get(f'/cd/turmas/{tid}/frequencia').json()==[dict(matricula_id=str(mid),aulas_cumpridas=[str(a)])]
    with scoped(database,v['other']) as s:
        for table in ('cd_presencas','cd_presencas_historico'):
            assert s.execute(text(f'select count(*) from {table}')).scalar_one()==0
            with pytest.raises(ProgrammingError),s.begin_nested(): s.execute(text(f'delete from {table}'))
    with database.connect() as c:
        for table in ('cd_presencas','cd_presencas_historico'):
            assert c.execute(text('select relrowsecurity,relforcerowsecurity from pg_class where oid=cast(:t as regclass)'),dict(t=table)).one()==(True,True)
            for role in ('anon','service_role'):
                for privilege in ('SELECT','INSERT','UPDATE','DELETE'):
                    assert not c.execute(text('select has_table_privilege(:r,:t,:p)'),dict(r=role,t=table,p=privilege)).scalar_one()


def test_foreign_turma_and_idor_even_bypass(database,seeded):
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import IntegrityError
    v=seeded
    with database.begin() as c:
        c.execute(text("insert into app_users(id,igreja_id,status,nome,email) values(:u,:u,'ativo','Outro sintético','other@example.test')"),dict(u=v['other']))
        c.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:u,:u,'admin')"),dict(u=v['other']))
    with scoped(database,v['t']) as s:
        tid,mid,a=setup(s,v); other=create(s,v)
        denied(lambda:cd.attendance(s,principal(v),other,mid,a,payload()),409)
        with pytest.raises(IntegrityError),s.begin_nested():
            s.execute(text('''insert into cd_presencas(igreja_id,turma_id,matricula_id,aula_id,presente,modalidade,registro_id,registrada_por)
                values(:t,:tid,:mid,:a,true,'regular',:id,:u)'''),dict(t=v['t'],tid=other,mid=mid,a=a,id=uuid4(),u=v['uid']))
        s.commit()
    with Session(database) as s:
        u=principal(v,'other','other')
        denied(lambda:cd.attendance(s,u,tid,mid,a,payload()),404)
        denied(lambda:cd.attendance_history(s,u,tid,mid,a),404)
        denied(lambda:cd.attendance_summary(s,u,tid),404)


@pytest.mark.parametrize('table',['cd_presencas','cd_presencas_historico'])
def test_postgrest_and_unpinned_jwt_denied(database,seeded,table):
    from sqlalchemy.orm import Session
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid,a=setup(s,v); cd.attendance(s,principal(v),tid,mid,a,payload()); s.commit()
    with database.begin() as c:
        c.exec_driver_sql("do $$ begin if not exists(select 1 from pg_roles where rolname='authenticator') then create role authenticator nologin; end if; end $$")
        c.exec_driver_sql('grant authenticated to authenticator')
        c.execute(text("update app_users set clerk_user_id='synthetic-clerk' where id=:u"),dict(u=v['uid']))
    with scoped(database,v['t']) as s:
        s.execute(text('set local session authorization authenticator'))
        s.execute(text('set local role authenticated'))
        assert s.execute(text(f'select count(*) from {table}')).scalar_one()==0
        for privilege in ('INSERT','UPDATE'):
            assert not s.execute(text('select has_any_column_privilege(\'service_role\',:t,:p)'),dict(t=table,p=privilege)).scalar_one()
    with Session(database) as s:
        s.execute(text('set local role authenticated'))
        s.execute(text("select set_config('request.jwt.claims',:c,true)"),dict(c='{"sub":"synthetic-clerk"}'))
        assert s.execute(text('select current_igreja_id()')).scalar_one()==v['t']
        assert s.execute(text(f'select count(*) from {table}')).scalar_one()==0


def test_clock_and_direct_revision_guards(database,seeded,monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from tests.test_cd_turmas_pg import curriculum
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid,a=setup(s,v)
        monkeypatch.setattr(cd,'today_sao_paulo',lambda:date(2019,12,31))
        denied(lambda:cd.attendance(s,principal(v),tid,mid,a,payload()),409)
        monkeypatch.setattr(cd,'today_sao_paulo',lambda:date(2020,1,1))
        first=payload(); cd.attendance(s,principal(v),tid,mid,a,first)
        with pytest.raises(IntegrityError),s.begin_nested():
            s.execute(text('update cd_presencas set registro_id=:id where matricula_id=:m'),dict(id=uuid4(),m=mid))
        for field in ('registrada_em','igreja_id','turma_id','aula_id','matricula_id'):
            assert not s.execute(text("select has_column_privilege(current_user,'cd_presencas',:f,'UPDATE')"),dict(f=field)).scalar_one()
        c=curriculum(s,v)
        foreign_aula=c['modulos'][1]['aulas'][0]['id']
        denied(lambda:cd.attendance(s,principal(v),tid,mid,foreign_aula,payload()),422)
        assert cd.attendance_summary(s,principal(v),tid)[0]['aulas_cumpridas']==[a]
        for lesson in cd.get_turma(s,principal(v),tid)['modulo']['aulas'][1:]:
            monkeypatch.setattr(cd,'today_sao_paulo',lambda:date(2021,1,1))
            cd.attendance(s,principal(v),tid,mid,lesson['id'],payload(modalidade='reposicao'))
        assert len(cd.attendance_summary(s,principal(v),tid)[0]['aulas_cumpridas'])==10


@pytest.mark.parametrize('presente',[True,False])
def test_calendar_cannot_move_recorded_lesson_to_future(database,seeded,presente):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid,a=setup(s,v); first=payload(presente=presente)
        cd.attendance(s,principal(v),tid,mid,a,first)
        detail=cd.get_turma(s,principal(v),tid)
        future=CalendarioInput(aulas=[dict(aula_id=lesson['id'],data=date(2100,1,1)+timedelta(days=i)) for i,lesson in enumerate(detail['modulo']['aulas'])])
        denied(lambda:cd.calendar(s,principal(v),tid,future),409)
        assert cd.get_turma(s,principal(v),tid)['calendario']==detail['calendario']
        corrected=cd.attendance(s,principal(v),tid,mid,a,payload(anterior_id=first.id,presente=not presente))
        assert corrected['presente']==(not presente)
