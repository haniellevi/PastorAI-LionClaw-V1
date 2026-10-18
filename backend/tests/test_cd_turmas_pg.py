"""Real migration chain + authenticated API/service, synthetic local PG only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import datetime as dt

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

# Reuse the real-chain UV fixture: same isolated DB, same migration runner.
from tests.test_uv_turmas_pg import (rls_database_url, migrated_database, database, seeded,
                                      scoped, principal)
from app.db.session import get_db
from app.deps import get_current_user
from app.routers.cd import (router, CurriculoInput, TurmaInput, NomeInput, CalendarioInput,
                            ResponsaveisInput)
from app.services import cd

pytestmark=pytest.mark.rls_integration
TABLES=['cd_curriculos','cd_niveis','cd_modulos','cd_aulas','cd_turmas','cd_calendario','cd_responsaveis']


def curriculum(s,v,**kw):
    return cd.create_curriculo(s,principal(v),CurriculoInput(id=uuid4(),nome='Formação',versao=str(uuid4()),**kw))


def create(s,v,c=None):
    c=c or curriculum(s,v)
    return cd.create_turma(s,principal(v),TurmaInput(id=uuid4(),nome='Turma',curriculo_id=c['id'],modulo_id=c['modulos'][0]['id']))['id']


def schedule(detail):
    return CalendarioInput(aulas=[dict(aula_id=a['id'],data=dt.date(2026,10,1)+dt.timedelta(days=a['numero'])) for a in detail['modulo']['aulas']])


def denied(call,code=403):
    with pytest.raises(HTTPException) as exc: call()
    assert exc.value.status_code==code


def test_authenticated_panel_api(database,seeded):
    v=seeded; app=FastAPI(); app.include_router(router)
    def db():
        with scoped(database,v['t']) as s: yield s
    app.dependency_overrides[get_db]=db
    app.dependency_overrides[get_current_user]=lambda:principal(v)
    with TestClient(app) as client:
        payload=dict(id=str(uuid4()),nome='Formação',versao='v1')
        c=client.post('/cd/curriculos',json=payload)
        assert c.status_code==200,c.text
        c=c.json(); assert len(c['modulos'])==6 and all(len(m['aulas'])==10 for m in c['modulos'])
        assert c['niveis']==[]
        assert client.post('/cd/curriculos',json=payload).json()==c
        tid=str(uuid4()); tp=dict(id=tid,nome='Turma',curriculo_id=c['id'],modulo_id=c['modulos'][0]['id'])
        for _ in range(2): assert client.post('/cd/turmas',json=tp).status_code==200
        detail=client.get('/cd/turmas/'+tid).json()
        assert 'matriculas' not in detail
        cal=schedule(detail).model_dump(mode='json')
        for _ in range(2): assert client.put(f'/cd/turmas/{tid}/calendario',json=cal).status_code==200
        assert len(client.get(f'/cd/turmas/{tid}').json()['calendario'])==10
        assert client.put(f'/cd/turmas/{tid}',json={'nome':'Nome editado'}).status_code==200
        assert client.post(f'/cd/turmas/{tid}/encerrar').status_code==200
        assert client.put(f'/cd/turmas/{tid}/calendario',json=cal).status_code==409
        assert client.post(f'/cd/turmas/{tid}/reabrir').status_code==200
        assert client.put(f'/cd/turmas/{tid}/calendario',json=cal).status_code==200
        assert len(client.get('/cd/curriculos').json())==1
        assert len(client.get('/cd/turmas').json())==1


@pytest.mark.parametrize('role',['admin','pastor'])
def test_coordination_and_levels(database,seeded,role):
    v=seeded
    with database.begin() as conn: conn.execute(text('update user_roles set papel=:r where user_id=:u'),dict(r=role,u=v['uid']))
    with scoped(database,v['t']) as s:
        c=curriculum(s,v,niveis=[dict(nome='Agrupamento definido pela equipe',modulos=[1,2,3,4,5,6])])
        assert len(c['niveis'])==1
        for kind,rid in [('curriculo',c['id']),('nivel',c['niveis'][0]['id']),('modulo',c['modulos'][0]['id']),('aula',c['modulos'][0]['aulas'][0]['id'])]:
            cd.rename_catalog(s,principal(v),c['id'],kind,rid,NomeInput(nome='Editado'))
        tid=create(s,v,c)
        cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        cd.close(s,principal(v),tid); cd.close(s,principal(v),tid,reopen=True)


@pytest.mark.parametrize('key',['leader','outsider'])
def test_no_link_or_unauthorized_role(database,seeded,key):
    v=seeded
    with scoped(database,v['t']) as s:
        tid=create(s,v); user=principal(v,key)
        if key=='leader': assert cd.list_turmas(s,user)==[]
        else: denied(lambda:cd.list_turmas(s,user))
        denied(lambda:cd.get_turma(s,user,tid))
        denied(lambda:cd.list_curriculos(s,user))
        denied(lambda:cd.options(s,user))
        denied(lambda:cd.create_curriculo(s,user,CurriculoInput(id=uuid4(),nome='X',versao='X')))


@pytest.mark.parametrize('revocation',['link','status','role','screen'])
def test_responsible_live_scope_and_readonly(database,seeded,revocation):
    v=seeded
    with scoped(database,v['t']) as s:
        tid=create(s,v); cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        user=principal(v,'leader'); d=cd.get_turma(s,user,tid)
        assert len(cd.list_turmas(s,user))==1
        denied(lambda:cd.calendar(s,user,tid,schedule(d)))
        denied(lambda:cd.rename_turma(s,user,tid,NomeInput(nome='X')))
        denied(lambda:cd.responsaveis(s,user,tid,ResponsaveisInput(usuarios=[])))
        denied(lambda:cd.close(s,user,tid))
        denied(lambda:cd.close(s,user,tid,reopen=True))
        if revocation=='link': cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[]))
        s.commit()
    with database.begin() as conn:
        if revocation=='status': conn.execute(text("update app_users set status='revogado' where id=:u"),dict(u=v['leader']))
        if revocation=='role': conn.execute(text('delete from user_roles where user_id=:u'),dict(u=v['leader']))
        if revocation=='screen': conn.execute(text("insert into role_permissions(igreja_id,papel,tela) values(:t,'lider_consol','dashboard')"),dict(t=v['t']))
    with scoped(database,v['t']) as s: denied(lambda:cd.get_turma(s,principal(v,'leader'),tid))


@pytest.mark.parametrize('key',['outsider','other'])
def test_responsible_must_be_eligible(database,seeded,key):
    v=seeded
    with scoped(database,v['t']) as s:
        tid=create(s,v)
        denied(lambda:cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v[key]])),422)


def test_versions_calendar_closure_and_conflicts(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        c=curriculum(s,v); other=curriculum(s,v); tid=create(s,v,c)
        denied(lambda:cd.create_turma(s,principal(v),TurmaInput(id=uuid4(),nome='X',curriculo_id=other['id'],modulo_id=c['modulos'][0]['id'])),409)
        denied(lambda:cd.create_curriculo(s,principal(v),CurriculoInput(id=uuid4(),nome='X',versao=c['versao'])),409)
        assert s.execute(text('select 1')).scalar()==1 # savepoint kept outer transaction usable
        d=cd.get_turma(s,principal(v),tid); cal=schedule(d)
        bad=cal.model_copy(deep=True); bad.aulas[0].aula_id=other['modulos'][0]['aulas'][0]['id']
        denied(lambda:cd.calendar(s,principal(v),tid,bad),422)
        bad=cal.model_copy(deep=True); bad.aulas[0].data=dt.date(2030,1,1)
        denied(lambda:cd.calendar(s,principal(v),tid,bad),422)
        cd.close(s,principal(v),tid)
        denied(lambda:cd.rename_turma(s,principal(v),tid,NomeInput(nome='X')),409)
        denied(lambda:cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[])),409)
        cd.close(s,principal(v),tid,reopen=True); cd.calendar(s,principal(v),tid,cal)


def test_reused_ids(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        p=CurriculoInput(id=uuid4(),nome='X',versao='1'); c=cd.create_curriculo(s,principal(v),p)
        denied(lambda:cd.create_curriculo(s,principal(v),p.model_copy(update={'nome':'Y'})),409)
        tp=TurmaInput(id=uuid4(),nome='X',curriculo_id=c['id'],modulo_id=c['modulos'][0]['id'])
        cd.create_turma(s,principal(v),tp)
        denied(lambda:cd.create_turma(s,principal(v),tp.model_copy(update={'nome':'Y'})),409)


@pytest.mark.parametrize('conflicting',[False,True])
def test_concurrent_creation(database,seeded,conflicting):
    v=seeded
    with scoped(database,v['t']) as s: c=curriculum(s,v); s.commit()
    p=TurmaInput(id=uuid4(),nome='X',curriculo_id=c['id'],modulo_id=c['modulos'][0]['id']); barrier=Barrier(2)
    def attempt(name):
        with scoped(database,v['t']) as s:
            barrier.wait(timeout=10)
            try:
                r=cd.create_turma(s,principal(v),p.model_copy(update={'nome':name})); s.commit(); return r['id']
            except HTTPException as exc: s.rollback(); return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(attempt,'X'); b=pool.submit(attempt,'Y' if conflicting else 'X'); values=[a.result(timeout=20),b.result(timeout=20)]
    assert values.count(409)==int(conflicting)
    with scoped(database,v['t']) as s: assert len(cd.list_turmas(s,principal(v)))==1


@pytest.mark.parametrize('table',TABLES)
def test_rls_and_minimal_grants(database,seeded,table):
    v=seeded
    with scoped(database,v['t']) as s:
        c=curriculum(s,v,niveis=[dict(nome='Grupo',modulos=[1,2,3,4,5,6])]); tid=create(s,v,c)
        cd.calendar(s,principal(v),tid,schedule(cd.get_turma(s,principal(v),tid)))
        cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        s.commit()
    with scoped(database,v['other']) as s:
        assert s.execute(text(f'select count(*) from {table}')).scalar()==0
        assert not s.execute(text("select has_table_privilege(current_user,:t,'DELETE')"),dict(t=table)).scalar()
        for col in ['id','igreja_id']:
            assert not s.execute(text("select has_column_privilege(current_user,:t,:c,'UPDATE')"),dict(t=table,c=col)).scalar()
        with pytest.raises(ProgrammingError):
            if table=='cd_curriculos':
                s.execute(text("insert into cd_curriculos(id,igreja_id,versao,nome,criada_por) values(:id,:t,'X','X',:u)"),dict(id=uuid4(),t=v['t'],u=v['uid']))
            else:
                # WITH CHECK evaluated on a clone with a new generated id.
                cols={'cd_niveis':'igreja_id,curriculo_id,numero,nome','cd_modulos':'igreja_id,curriculo_id,numero,nome',
                    'cd_aulas':'igreja_id,modulo_id,numero,nome','cd_turmas':'id,igreja_id,curriculo_id,modulo_id,nome,criada_por',
                    'cd_calendario':'igreja_id,turma_id,modulo_id,aula_id,data,criada_por','cd_responsaveis':'igreja_id,turma_id,usuario_id,atribuido_por'}[table]
                # Read synthetic source under provisioning, then insert in the wrong scope.
                with database.connect() as conn: source=dict(conn.execute(text(f'select {cols} from {table} limit 1')).mappings().one())
                if 'id' in source: source['id']=uuid4()
                s.execute(text(f"insert into {table}({cols}) values({','.join(':'+x for x in cols.split(','))})"),source)
    with database.connect() as conn:
        assert conn.execute(text('select relrowsecurity and relforcerowsecurity from pg_class where relname=:t'),dict(t=table)).scalar()


@pytest.mark.parametrize('edge',['nivel','modulo','aula','turma','calendario','responsavel','autor'])
def test_cross_tenant_fks(database,seeded,edge):
    v=seeded
    with scoped(database,v['t']) as s: c=curriculum(s,v); tid=create(s,v,c); s.commit()
    with database.begin() as conn:
        conn.execute(text("insert into app_users(id,igreja_id,status,nome,email) values(:u,:t,'ativo','Sintético','other@example.test')"),dict(u=v['other'],t=v['other']))
        conn.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:t,:u,'admin')"),dict(t=v['other'],u=v['other']))
    with Session(database) as s:
        foreign=cd.create_curriculo(s,principal(v,'other','other'),CurriculoInput(id=uuid4(),nome='Outro',versao='1')); s.commit()
    with scoped(database,v['t']) as s:
        params=dict(t=v['t'],c=foreign['id'],m=foreign['modulos'][0]['id'],a=foreign['modulos'][0]['aulas'][0]['id'],tid=tid,u=v['other'],id=uuid4())
        statements={
            'nivel':"insert into cd_niveis(igreja_id,curriculo_id,numero,nome) values(:t,:c,1,'X')",
            'modulo':"insert into cd_modulos(igreja_id,curriculo_id,numero,nome) values(:t,:c,1,'X')",
            'aula':"insert into cd_aulas(igreja_id,modulo_id,numero,nome) values(:t,:m,1,'X')",
            'turma':"insert into cd_turmas(id,igreja_id,curriculo_id,modulo_id,nome,criada_por) values(:id,:t,:c,:m,'X',:u)",
            'calendario':"insert into cd_calendario(igreja_id,turma_id,modulo_id,aula_id,data,criada_por) values(:t,:tid,:m,:a,current_date,:u)",
            'responsavel':"insert into cd_responsaveis(igreja_id,turma_id,usuario_id,atribuido_por) values(:t,:tid,:u,:u)",
            'autor':"insert into cd_curriculos(id,igreja_id,versao,nome,criada_por) values(:id,:t,'other','X',:u)"}
        with pytest.raises(IntegrityError) as exc: s.execute(text(statements[edge]),params)
        assert exc.value.orig.pgcode=='23503'


def test_bypassrls_service_tenant_boundary(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s: tid=create(s,v); s.commit()
    with Session(database) as s:
        denied(lambda:cd.get_turma(s,principal(v,tenant='other'),tid))


@pytest.mark.parametrize('edge',['nivel_version','turma_version','calendar_module','module_unique','lesson_unique'])
def test_same_church_structure_integrity(database,seeded,edge):
    v=seeded
    with scoped(database,v['t']) as s:
        c=curriculum(s,v,niveis=[dict(nome='Grupo',modulos=[1,2,3,4,5,6])]); other=curriculum(s,v); tid=create(s,v,c)
        m=c['modulos'][0]; other_m=c['modulos'][1]
        params=dict(t=v['t'],c=c['id'],other=other['id'],nivel=c['niveis'][0]['id'],m=m['id'],other_m=other_m['id'],a=other_m['aulas'][0]['id'],tid=tid,u=v['uid'],id=uuid4())
        queries={
            'nivel_version':"insert into cd_modulos(igreja_id,curriculo_id,nivel_id,numero,nome) values(:t,:other,:nivel,7,'X')",
            'turma_version':"insert into cd_turmas(id,igreja_id,curriculo_id,modulo_id,nome,criada_por) values(:id,:t,:other,:m,'X',:u)",
            'calendar_module':"insert into cd_calendario(igreja_id,turma_id,modulo_id,aula_id,data,criada_por) values(:t,:tid,:m,:a,current_date,:u)",
            'module_unique':"insert into cd_modulos(igreja_id,curriculo_id,numero,nome) values(:t,:c,1,'X')",
            'lesson_unique':"insert into cd_aulas(igreja_id,modulo_id,numero,nome) values(:t,:m,1,'X')"}
        with pytest.raises(IntegrityError) as exc: s.execute(text(queries[edge]),params)
        assert exc.value.orig.pgcode==('23505' if edge.endswith('unique') else '23503')


def test_concurrent_curriculum_same_key(database,seeded):
    v=seeded; payload=CurriculoInput(id=uuid4(),nome='X',versao='v1'); barrier=Barrier(2)
    def attempt():
        with scoped(database,v['t']) as s:
            barrier.wait(timeout=10); r=cd.create_curriculo(s,principal(v),payload); s.commit(); return r
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(attempt); b=pool.submit(attempt); assert a.result(timeout=20)==b.result(timeout=20)
    with scoped(database,v['t']) as s:
        assert s.execute(text('select count(*) from cd_modulos')).scalar()==6
        assert s.execute(text('select count(*) from cd_aulas')).scalar()==60


def test_concurrent_close_calendar_serialized(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid=create(s,v); cal=schedule(cd.get_turma(s,principal(v),tid)); s.commit()
    # Hold the turma lock and close; the concurrent writer must re-read closed state.
    with scoped(database,v['t']) as first:
        cd.close(first,principal(v),tid)
        def attempt():
            with scoped(database,v['t']) as second:
                try: cd.calendar(second,principal(v),tid,cal); second.commit(); return 200
                except HTTPException as exc: return exc.status_code
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(attempt); first.commit(); assert future.result(timeout=20)==409


def test_new_structure_requires_new_version(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        p=CurriculoInput(id=uuid4(),nome='Versão definida pela equipe',versao='configurada',aulas_por_modulo=[2,3],niveis=[dict(nome='Grupo definido pela equipe',modulos=[1,2])])
        c=cd.create_curriculo(s,principal(v),p)
        assert [len(m['aulas']) for m in c['modulos']]==[2,3]
        assert cd.create_curriculo(s,principal(v),p)==c
        denied(lambda:cd.create_curriculo(s,principal(v),p.model_copy(update={'aulas_por_modulo':[3,3]})),409)
        tid=create(s,v,c); d=cd.get_turma(s,principal(v),tid)
        assert len(cd.calendar(s,principal(v),tid,schedule(d))['calendario'])==2


@pytest.mark.parametrize('key',['leader','outsider'])
def test_http_refuses_scope_and_coordination_operations(database,seeded,key):
    v=seeded
    with scoped(database,v['t']) as s: c=curriculum(s,v); tid=create(s,v,c); s.commit()
    app=FastAPI(); app.include_router(router)
    def db():
        with scoped(database,v['t']) as s: yield s
    app.dependency_overrides[get_db]=db
    app.dependency_overrides[get_current_user]=lambda:principal(v,key)
    with TestClient(app) as client:
        assert client.get('/cd/curriculos').status_code==403
        assert client.get(f'/cd/turmas/{tid}').status_code==403
        assert client.post('/cd/turmas',json=dict(id=str(uuid4()),nome='X',curriculo_id=str(c['id']),modulo_id=str(c['modulos'][0]['id']))).status_code==403
        assert client.post(f'/cd/turmas/{tid}/encerrar').status_code==403


@pytest.mark.parametrize('payload',[
    {'niveis':[{'nome':'X','modulos':[1,1,2,3,4,5,6]}]},
    {'niveis':[{'nome':'X','modulos':[1]}]},
    {'niveis':[{'nome':'  ','modulos':[1,2,3,4,5,6]}]},
    {'aulas_por_modulo':[True]}, {'aulas_por_modulo':[0]}, {'versao':'  '},
])
def test_curriculum_input_rejects_invalid_structure(payload,rls_database_url):
    from pydantic import ValidationError
    data=dict(id=uuid4(),nome='X',versao='1'); data.update(payload)
    with pytest.raises(ValidationError): CurriculoInput(**data)
