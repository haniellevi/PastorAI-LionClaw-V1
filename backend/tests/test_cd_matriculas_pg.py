"""CD enrollment: synthetic real-chain PostgreSQL, live scope and authenticated API."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import monotonic, sleep
from uuid import uuid4
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session
from tests.test_uv_turmas_pg import rls_database_url, migrated_database, database, seeded, scoped, principal
from tests.test_cd_turmas_pg import curriculum, create, denied
from tests.test_uv_conclusao_pg import complete
from app.db.session import get_db
from app.deps import get_current_user
from app.routers.cd import router, TurmaInput, ResponsaveisInput, MatriculaInput
from app.routers.uv import ConclusaoInput
from app.services import cd, uv
pytestmark = pytest.mark.rls_integration


def command(v, **kw):
    return MatriculaInput(**(dict(id=uuid4(),pessoa_id=v['p']) | kw))


def legacy(s,v):
    s.execute(text('update pessoas set apto_proxima_cd=true where igreja_id=:t and id=:p'),dict(t=v['t'],p=v['p']))


@pytest.mark.parametrize('origin',['legado','conclusao_uv'])
def test_http_lifecycle_and_provenance(database,seeded,origin):
    v=seeded
    with scoped(database,v['t']) as s:
        if origin=='legado': legacy(s,v)
        else:
            ut,um=complete(s,v)
            uv.finish(s,principal(v),ut,um,ConclusaoInput(id=uuid4(),confirmado=True))
        tid=create(s,v); cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        assert cd.list_enrollments(s,principal(v),tid)==[]
        s.commit()
    app=FastAPI(); app.include_router(router)
    def db():
        with scoped(database,v['t']) as s: yield s
    app.dependency_overrides[get_db]=db
    app.dependency_overrides[get_current_user]=lambda:principal(v,'leader')
    with TestClient(app) as client:
        base=f'/cd/turmas/{tid}'; payload=command(v).model_dump(mode='json')
        assert client.get(base+'/elegiveis').json()==[dict(id=str(v['p']),nome='Aluno sintético')]
        for _ in range(2):
            response=client.post(base+'/matriculas',json=payload)
            assert response.status_code==200,response.text
        assert client.get(base+'/elegiveis').json()==[]
        receipt=client.get(base+'/matriculas').json()[0]
        assert receipt['origem_aptidao']==origin and receipt['criada_por']==str(v['leader'])
        assert set(receipt)=={'id','pessoa_id','nome','ativa','origem_aptidao','criada_por','criada_em','cancelada_por','cancelada_em'}
        for _ in range(2): assert client.post(base+f"/matriculas/{receipt['id']}/cancelar").status_code==200
        cancelled=client.get(base+'/matriculas').json()[0]
        assert not cancelled['ativa'] and cancelled['cancelada_por']==str(v['leader']) and cancelled['cancelada_em']
        for _ in range(2): assert client.post(base+'/matriculas',json=payload).json()['id']==receipt['id']
        active=client.get(base+'/matriculas').json()[0]
        assert active['ativa'] and active['cancelada_por'] is None and active['cancelada_em'] is None


@pytest.mark.parametrize('state',['inapto','origem_ausente','arquivada','modulo2','encerrada'])
def test_guards(database,seeded,state):
    v=seeded
    with scoped(database,v['t']) as s:
        c=curriculum(s,v); tid=create(s,v,c)
        if state!='inapto': legacy(s,v)
        if state=='modulo2': tid=cd.create_turma(s,principal(v),TurmaInput(id=uuid4(),nome='Segundo',curriculo_id=c['id'],modulo_id=c['modulos'][1]['id']))['id']
        if state=='encerrada': cd.close(s,principal(v),tid)
        if state=='arquivada': s.execute(text('update pessoas set arquivada_em=now() where id=:p'),dict(p=v['p']))
        s.commit()
    if state=='origem_ausente':
        # Deliberately corrupt synthetic history: normal writes enforce origin.
        with database.begin() as conn:
            conn.exec_driver_sql('alter table pessoas disable trigger uv_origem_aptidao')
            conn.exec_driver_sql('alter table pessoas drop constraint uv_aptidao_origem_coerente')
            conn.execute(text('update pessoas set origem_aptidao_cd=null where id=:p'),dict(p=v['p']))
    try:
        with scoped(database,v['t']) as s:
            with pytest.raises(HTTPException) as exc: cd.enroll(s,principal(v),tid,command(v))
            assert exc.value.status_code==(404 if state=='arquivada' else 409 if state in {'modulo2','encerrada'} else 422)
            if state=='modulo2': assert 'pré-requisito' in exc.value.detail
            else: assert cd.eligible(s,principal(v),tid)==[]
            assert cd.list_enrollments(s,principal(v),tid)==[]
    finally:
        if state=='origem_ausente':
            with database.begin() as conn:
                conn.execute(text("update pessoas set origem_aptidao_cd='legado' where id=:p"),dict(p=v['p']))
                conn.exec_driver_sql('alter table pessoas enable trigger uv_origem_aptidao')
                conn.exec_driver_sql('alter table pessoas add constraint uv_aptidao_origem_coerente check(apto_proxima_cd=(origem_aptidao_cd is not null))')


@pytest.mark.parametrize('state',['unlinked','removed','status','role','screen','allowed','pastor'])
def test_live_authorization(database,seeded,state):
    v=seeded
    with scoped(database,v['t']) as s:
        legacy(s,v); tid=create(s,v); mid=cd.enroll(s,principal(v),tid,command(v))['id']
        if state!='unlinked': cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        if state=='removed': cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[]))
        s.commit()
    with database.begin() as conn:
        if state=='status': conn.execute(text("update app_users set status='revogado' where id=:u"),dict(u=v['leader']))
        if state=='role': conn.execute(text('delete from user_roles where user_id=:u'),dict(u=v['leader']))
        if state=='screen': conn.execute(text("insert into role_permissions(igreja_id,papel,tela) values(:t,'lider_consol','dashboard')"),dict(t=v['t']))
        if state=='pastor': conn.execute(text("update user_roles set papel='pastor' where user_id=:u"),dict(u=v['leader']))
    with scoped(database,v['t']) as s:
        u=principal(v,'leader')
        actions=[lambda:cd.eligible(s,u,tid),lambda:cd.list_enrollments(s,u,tid),lambda:cd.enroll(s,u,tid,command(v)),lambda:cd.cancel_enrollment(s,u,tid,mid)]
        if state in {'allowed','pastor'}:
            actions[0](); actions[1](); actions[3](); cd.enroll(s,u,tid,command(v,id=mid))
        else:
            for action in actions: denied(action,404 if state in {'unlinked','removed'} else 403)


def test_idor_even_bypassrls(database,seeded):
    v=seeded; foreign=uuid4()
    with database.begin() as conn:
        conn.execute(text("insert into pessoas(id,igreja_id,nome,telefone,apto_proxima_cd) values(:p,:t,'Outra','550000000002',true)"),dict(p=foreign,t=v['other']))
        conn.execute(text("insert into app_users(id,igreja_id,status,nome,email) values(:u,:t,'ativo','Outro','other@example.test')"),dict(u=v['other'],t=v['other']))
        conn.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:t,:u,'admin')"),dict(t=v['other'],u=v['other']))
    with scoped(database,v['t']) as s: legacy(s,v); tid=create(s,v); mid=cd.enroll(s,principal(v),tid,command(v))['id']; s.commit()
    with Session(database) as s:
        denied(lambda:cd.enroll(s,principal(v),tid,command(v,pessoa_id=foreign)),404)
        for action in [lambda:cd.enroll(s,principal(v,'other','other'),tid,command(v)),lambda:cd.eligible(s,principal(v,'other','other'),tid),lambda:cd.list_enrollments(s,principal(v,'other','other'),tid),lambda:cd.cancel_enrollment(s,principal(v,'other','other'),tid,mid)]: denied(action,404)


def test_duplicate_versions_and_reactivation_guards(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        legacy(s,v); tid=create(s,v); other=create(s,v); p=command(v)
        mid=cd.enroll(s,principal(v),tid,p)['id']
        for target,payload in [(other,command(v)),(tid,command(v)),(other,p)]: denied(lambda:cd.enroll(s,principal(v),target,payload),409)
        cd.cancel_enrollment(s,principal(v),tid,mid)
        s.execute(text('update pessoas set apto_proxima_cd=false where id=:p'),dict(p=v['p']))
        denied(lambda:cd.enroll(s,principal(v),tid,command(v)),422)
        legacy(s,v); cd.enroll(s,principal(v),other,command(v))
        denied(lambda:cd.enroll(s,principal(v),tid,command(v)),409)


@pytest.mark.parametrize('same_turma',[False,True])
def test_concurrent_enrollment(database,seeded,same_turma):
    v=seeded
    with scoped(database,v['t']) as s:
        legacy(s,v); tid=create(s,v); tids=[tid,tid if same_turma else create(s,v)]; s.commit()
    barrier=Barrier(2)
    def attempt(tid):
        with scoped(database,v['t']) as s:
            barrier.wait(timeout=10)
            try: cd.enroll(s,principal(v),tid,command(v)); s.commit(); return 200
            except HTTPException as exc: s.rollback(); return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(attempt,tids))
    assert sorted(results)==[200,409]
    with scoped(database,v['t']) as s: assert s.execute(text('select count(*) from cd_matriculas where ativa')).scalar()==1


@pytest.mark.parametrize('mode',['closure','revocation','aptitude'])
def test_waiting_writer_revalidates(database,seeded,mode):
    v=seeded
    with scoped(database,v['t']) as s:
        legacy(s,v); tid=create(s,v); cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']])); s.commit()
    started=Event(); waiting_pid=[]
    with scoped(database,v['t']) as first:
        if mode=='closure': cd.close(first,principal(v),tid)
        elif mode=='revocation': cd.responsaveis(first,principal(v),tid,ResponsaveisInput(usuarios=[]))
        else: first.execute(text('update pessoas set apto_proxima_cd=false where id=:p'),dict(p=v['p']))
        def attempt():
            with scoped(database,v['t']) as second:
                waiting_pid.append(second.execute(text('select pg_backend_pid()')).scalar())
                started.set()
                try: cd.enroll(second,principal(v,'leader'),tid,command(v)); second.commit(); return 200
                except HTTPException as exc: return exc.status_code
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(attempt)
            try:
                assert started.wait(timeout=5)
                deadline=monotonic()+5
                while monotonic()<deadline:
                    with database.connect() as observer:
                        blocked=observer.execute(text("select wait_event_type='Lock' from pg_stat_activity where pid=:p"),dict(p=waiting_pid[0])).scalar()
                    if blocked: break
                    sleep(0.01)
                assert blocked, 'writer must actually wait for the held lock'
            finally:
                first.commit()
            assert future.result(timeout=20)==dict(closure=409,revocation=404,aptitude=422)[mode]


def test_rls_grants_and_composite_fks(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        legacy(s,v); tid=create(s,v); cd.enroll(s,principal(v),tid,command(v)); s.commit()
    with database.begin() as conn:
        conn.exec_driver_sql("do $$ begin if not exists(select 1 from pg_roles where rolname='authenticator') then create role authenticator nologin; end if; end $$")
        conn.exec_driver_sql('grant authenticated to authenticator')
        assert conn.execute(text("select relrowsecurity and relforcerowsecurity from pg_class where relname='cd_matriculas'")).scalar()
        for role in ['anon','service_role']:
            assert not conn.execute(text("select has_any_column_privilege(:r,'cd_matriculas','INSERT')"),dict(r=role)).scalar()
        source=dict(conn.execute(text('select id,igreja_id,turma_id,modulo_id,modulo_numero,pessoa_id,origem_aptidao,criada_por from cd_matriculas')).mappings().one())
    sql=text('insert into cd_matriculas('+','.join(source)+') values('+','.join(':'+k for k in source)+')')
    with scoped(database,v['other']) as s:
        assert s.execute(text('select count(*) from cd_matriculas')).scalar()==0
        assert s.execute(text('update cd_matriculas set ativa=ativa')).rowcount==0
        with pytest.raises(ProgrammingError): s.execute(sql,source | {'id':uuid4()})
    with scoped(database,v['t']) as s:
        assert not s.execute(text("select has_table_privilege(current_user,'cd_matriculas','DELETE')")).scalar()
        for col in ['id','igreja_id','turma_id','pessoa_id','modulo_id','modulo_numero']:
            assert not s.execute(text("select has_column_privilege(current_user,'cd_matriculas',:c,'UPDATE')"),dict(c=col)).scalar()
        s.execute(text('set local session authorization authenticator')); s.execute(text('set local role authenticated'))
        assert s.execute(text('select count(*) from cd_matriculas')).scalar()==0
        with pytest.raises(ProgrammingError): s.execute(sql,source | {'id':uuid4()})
    for field in ['pessoa_id','turma_id']:
        with database.begin() as conn:
            with pytest.raises(IntegrityError): conn.execute(sql,source | {'id':uuid4(),field:uuid4()})


def test_immutable_transition_history(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        legacy(s,v); tid=create(s,v); p=command(v)
        cd.enroll(s,principal(v),tid,p); cd.cancel_enrollment(s,principal(v),tid,p.id)
        cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        s.commit()
    with scoped(database,v['t']) as s:
        cd.enroll(s,principal(v,'leader'),tid,p); s.commit()
    with scoped(database,v['t']) as s:
        assert cd.enroll(s,principal(v,'leader'),tid,p)=={'id':p.id}
        events=s.execute(text('select tipo,autor_id,origem_aptidao,registrada_em from cd_matricula_eventos order by registrada_em')).all()
        assert [(e.tipo,e.autor_id,e.origem_aptidao) for e in events]==[('matricula',v['uid'],'legado'),('cancelamento',v['uid'],'legado'),('reativacao',v['leader'],'legado')]
        for privilege in ['UPDATE','INSERT','DELETE']:
            query="select has_table_privilege(current_user,'cd_matricula_eventos',:p)" if privilege=='DELETE' else "select has_any_column_privilege(current_user,'cd_matricula_eventos',:p)"
            assert not s.execute(text(query),dict(p=privilege)).scalar()
    with scoped(database,v['other']) as s: assert s.execute(text('select count(*) from cd_matricula_eventos')).scalar()==0


def test_foreign_person_and_turma_composite_fks(database,seeded):
    from app.routers.cd import CurriculoInput
    v=seeded; foreign_person=uuid4()
    with database.begin() as conn:
        conn.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'Outra pessoa','550000000002')"),dict(p=foreign_person,t=v['other']))
        conn.execute(text("insert into app_users(id,igreja_id,status,nome,email) values(:u,:t,'ativo','Outro','other@example.test')"),dict(u=v['other'],t=v['other']))
        conn.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:t,:u,'admin')"),dict(t=v['other'],u=v['other']))
    with scoped(database,v['t']) as s:
        c=curriculum(s,v); tid=create(s,v,c); s.commit()
    with scoped(database,v['other']) as s:
        user=principal(v,'other','other')
        fc=cd.create_curriculo(s,user,CurriculoInput(id=uuid4(),nome='Outro',versao='1'))
        foreign_turma=cd.create_turma(s,user,TurmaInput(id=uuid4(),nome='Outra',curriculo_id=fc['id'],modulo_id=fc['modulos'][0]['id']))['id']; s.commit()
    for person,target in [(foreign_person,tid),(v['p'],foreign_turma)]:
        with scoped(database,v['t']) as s:
            with pytest.raises(IntegrityError) as exc:
                s.execute(text("insert into cd_matriculas(id,igreja_id,turma_id,modulo_id,modulo_numero,pessoa_id,origem_aptidao,criada_por) values(:id,:t,:tid,:m,1,:p,'legado',:u)"),dict(id=uuid4(),t=v['t'],tid=target,m=c['modulos'][0]['id'],p=person,u=v['uid']))
            assert exc.value.orig.pgcode=='23503'
