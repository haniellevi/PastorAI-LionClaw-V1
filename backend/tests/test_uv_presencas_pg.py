"""PR 3 uses PR 2's complete migration replay, never a substitute schema."""
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from tests.test_uv_turmas_pg import (rls_database_url, migrated_database, database,
    seeded, scoped, principal, create, schedule, matricula)
from app.services import uv

pytestmark = pytest.mark.rls_integration


def setup(s,v):
    tid=create(s,v)
    uv.calendar(s,principal(v),tid,schedule())
    m=matricula(v); uv.enroll(s,principal(v),tid,m)
    return tid,m.id


def payload(**changes):
    from app.routers.uv import PresencaInput
    return PresencaInput(**(dict(id=uuid4(),presente=True,modalidade='regular') | changes))


def test_correction_history_and_contract(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=setup(s,v); first=payload(presente=False)
        before=s.execute(text('select etapa,apto_proxima_cd from pessoas where id=:p'),dict(p=v['p'])).one()
        original=uv.attendance(s,principal(v),tid,mid,1,first)
        assert uv.attendance(s,principal(v),tid,mid,1,first)==original
        with pytest.raises(HTTPException) as exc: uv.attendance(s,principal(v),tid,mid,1,payload())
        assert exc.value.status_code==409
        from app.routers.uv import ResponsaveisInput
        uv.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        uv.attendance(s,principal(v,'leader'),tid,mid,1,payload(modalidade='reposicao',anterior_id=first.id))
        assert uv.attendance(s,principal(v),tid,mid,1,first)==original
        student=uv.get_turma(s,principal(v),tid)['matriculas'][0]
        assert student['aulas_cumpridas']==[1]
        assert student['aulas_pendentes']==list(range(2,9))
        assert student['presencas'][0]['modalidade']=='reposicao'
        history=uv.attendance_history(s,principal(v),tid,mid,1)
        assert [h['presente'] for h in history]==[False,True]
        assert [h['registrada_por'] for h in history]==[v['uid'],v['leader']]
        assert history[1]['registrada_em'] > history[0]['registrada_em']
        for n in range(2,9): uv.attendance(s,principal(v),tid,mid,n,payload())
        assert uv.get_turma(s,principal(v),tid)['matriculas'][0]['aulas_pendentes']==[]
        assert s.execute(text('select etapa,apto_proxima_cd from pessoas where id=:p'),dict(p=v['p'])).one()==before
        with pytest.raises(HTTPException) as exc: uv.attendance(s,principal(v),tid,mid,1,payload(anterior_id=first.id))
        assert exc.value.status_code==409


@pytest.mark.parametrize('state',['unlinked','removed','revoked','role','screen','inactive','archived','closed','outsider'])
def test_live_denials(database,seeded,state):
    from app.routers.uv import ResponsaveisInput
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=setup(s,v)
        if state not in {'unlinked','outsider'}: uv.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        if state=='removed': uv.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[]))
        if state=='inactive': s.execute(text('update uv_matriculas set ativa=false where id=:id'),dict(id=mid))
        if state=='archived': s.execute(text('update pessoas set arquivada_em=now() where id=:id'),dict(id=v['p']))
        if state=='closed': uv.close(s,principal(v),tid)
        s.commit()
    with database.begin() as c:
        if state=='revoked': c.execute(text("update app_users set status='revogado' where id=:u"),dict(u=v['leader']))
        if state=='role': c.execute(text('delete from user_roles where user_id=:u'),dict(u=v['leader']))
        if state=='screen': c.execute(text("insert into role_permissions(igreja_id,papel,tela) values(:t,'lider_consol','dashboard')"),dict(t=v['t']))
    with scoped(database,v['t']) as s:
        user=principal(v,'outsider' if state=='outsider' else 'leader')
        with pytest.raises(HTTPException) as exc: uv.attendance(s,user,tid,mid,1,payload())
        assert exc.value.status_code in {403,409}
        if state in {'unlinked','removed','revoked','role','screen','outsider'}:
            with pytest.raises(HTTPException): uv.attendance_history(s,user,tid,mid,1)


@pytest.mark.parametrize('role',['admin','pastor','lider_consol'])
def test_approved_roles(database,seeded,role):
    from app.routers.uv import ResponsaveisInput
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=setup(s,v)
        uv.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        s.commit()
    with database.begin() as c:
        c.execute(text('update user_roles set papel=:r where user_id=:u'),dict(r=role,u=v['leader']))
    with scoped(database,v['t']) as s:
        uv.attendance(s,principal(v,'leader'),tid,mid,8,payload(modalidade='reposicao'))
        assert uv.get_turma(s,principal(v,'leader'),tid)['matriculas'][0]['aulas_cumpridas']==[8]


@pytest.mark.parametrize('same_key',[True,False])
@pytest.mark.parametrize('correction',[True,False])
def test_concurrent_attendance(database,seeded,same_key,correction):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=setup(s,v)
        first=payload()
        if correction: uv.attendance(s,principal(v),tid,mid,1,first)
        s.commit()
    next_payload=payload(anterior_id=first.id if correction else None)
    barrier=Barrier(2)
    def attempt(p):
        with scoped(database,v['t']) as s:
            barrier.wait(timeout=10)
            try:
                uv.attendance(s,principal(v),tid,mid,1,p); s.commit(); return 200
            except HTTPException as exc: return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(attempt,next_payload)
        b=pool.submit(attempt,next_payload if same_key else payload(anterior_id=first.id if correction else None))
        assert sorted([a.result(timeout=15),b.result(timeout=15)])==([200,200] if same_key else [200,409])
    with scoped(database,v['t']) as s:
        assert s.execute(text('select count(*) from uv_presencas')).scalar_one()==1
        assert s.execute(text('select count(*) from uv_presencas_historico')).scalar_one()==(2 if correction else 1)


def test_http_validation_and_audit(database,seeded):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.uv import router
    from app.db.session import get_db
    from app.deps import get_current_user
    v=seeded
    with scoped(database,v['t']) as s: tid,mid=setup(s,v); s.commit()
    app=FastAPI(); app.include_router(router)
    def db():
        with scoped(database,v['t']) as s: yield s
    app.dependency_overrides[get_db]=db
    app.dependency_overrides[get_current_user]=lambda:principal(v)
    path=f'/uv/turmas/{tid}/matriculas/{mid}/presencas'
    with TestClient(app) as client:
        p=payload().model_dump(mode='json')
        assert client.post(path+'/1',json=p).status_code==200
        assert len(client.get(path+'/1/historico').json())==1
        for invalid in ['0','9','encontro']:
            assert client.post(path+'/'+invalid,json=p).status_code==422
        assert client.post(path+'/2',json=p | dict(registrada_por=str(v['leader']))).status_code==422
        assert client.post(path+'/2',json=p | dict(modalidade='outra')).status_code==422
        assert client.post(path+'/2',json=p | dict(presente='true')).status_code==422
        app.dependency_overrides[get_current_user]=lambda:principal(v,'outsider')
        assert client.post(path+'/2',json=p).status_code==403
        assert client.get(path+'/1/historico').status_code==403


@pytest.mark.parametrize('edge',['tenant','matricula','atividade','autor','encontro'])
def test_composite_fks(database,seeded,edge):
    from sqlalchemy.exc import IntegrityError,ProgrammingError
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=setup(s,v); second,second_mid=setup(s,v)
        activity=s.execute(text('select id from uv_atividades where turma_id=:t and ordem=:ordem'),dict(t=second if edge=='atividade' else tid,ordem=5 if edge=='encontro' else 1)).scalar_one()
        s.commit()
    with database.begin() as c:
        foreign=uuid4()
        c.execute(text("insert into app_users(id,igreja_id,status,nome,email) values(:u,:t,'ativo','Equipe','synthetic@example.test')"),dict(u=foreign,t=v['other']))
    with scoped(database,v['t']) as s:
        with pytest.raises((IntegrityError,ProgrammingError)) as exc:
            s.execute(text('''insert into uv_presencas(igreja_id,turma_id,matricula_id,atividade_id,aula,presente,modalidade,registro_id,registrada_por)
                values(:t,:tid,:mid,:activity,1,true,'regular',:id,:u)'''),dict(t=v['other'] if edge=='tenant' else v['t'],tid=tid,
                    mid=second_mid if edge=='matricula' else mid,activity=activity,id=uuid4(),u=foreign if edge=='autor' else v['uid']))
        assert exc.value.orig.pgcode==('42501' if edge=='tenant' else '23503')


@pytest.mark.parametrize('table,column',[('uv_presencas','igreja_id'),('uv_presencas','matricula_id'),('uv_presencas','atividade_id'),('uv_presencas_historico','presente')])
def test_rls_and_immutable_history(database,seeded,table,column):
    from sqlalchemy.exc import ProgrammingError
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=setup(s,v); uv.attendance(s,principal(v),tid,mid,1,payload()); s.commit()
    with scoped(database,v['other']) as s:
        for name in ('uv_presencas','uv_presencas_historico'):
            assert s.execute(text(f'select count(*) from {name}')).scalar_one()==0
            assert not s.execute(text("select has_table_privilege(current_user,:t,'DELETE')"),dict(t=name)).scalar_one()
    with scoped(database,v['t']) as s:
        with pytest.raises(ProgrammingError) as exc: s.execute(text(f'update {table} set {column}={column}'))
        assert exc.value.orig.pgcode=='42501'


def test_retry_conflicts_scope_and_missing_calendar(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=setup(s,v); first=payload()
        uv.attendance(s,principal(v),tid,mid,1,first)
        for n,p in [(2,first),(1,first.model_copy(update={'presente':False}))]:
            with pytest.raises(HTTPException) as exc: uv.attendance(s,principal(v),tid,mid,n,p)
            assert exc.value.status_code==409
        second=create(s,v); m=matricula(v); uv.enroll(s,principal(v),second,m)
        with pytest.raises(HTTPException) as exc: uv.attendance(s,principal(v),second,m.id,1,payload())
        assert exc.value.status_code==422
        with pytest.raises(HTTPException) as exc: uv.attendance(s,principal(v),second,mid,1,payload())
        assert exc.value.status_code==409
        uv.close(s,principal(v),tid)
        assert uv.attendance(s,principal(v),tid,mid,1,first)['registro_id']==first.id
        with pytest.raises(HTTPException) as exc: uv.attendance(s,principal(v),tid,mid,1,payload(anterior_id=first.id))
        assert exc.value.status_code==409


@pytest.mark.parametrize('edge',['matricula','atividade'])
def test_cross_church_fk_even_without_rls(database,seeded,edge):
    from sqlalchemy.exc import IntegrityError
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=setup(s,v)
        activity=s.execute(text('select id from uv_atividades where turma_id=:t and aula=1'),dict(t=tid)).scalar_one()
        s.commit()
    with database.begin() as c:
        foreign_turma,foreign_mid,foreign_activity,foreign_person=[uuid4() for _ in range(4)]
        c.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'Aluno sintético','550000000003')"),dict(p=foreign_person,t=v['other']))
        c.execute(text("insert into uv_turmas(id,igreja_id,nome) values(:id,:t,'Outra turma')"),dict(id=foreign_turma,t=v['other']))
        c.execute(text('insert into uv_matriculas(id,igreja_id,turma_id,pessoa_id) values(:id,:t,:tid,:p)'),dict(id=foreign_mid,t=v['other'],tid=foreign_turma,p=foreign_person))
        c.execute(text("insert into uv_atividades(id,igreja_id,turma_id,tipo,aula,ordem,data) values(:id,:t,:tid,'aula',1,1,current_date)"),dict(id=foreign_activity,t=v['other'],tid=foreign_turma))
    with database.connect() as c:
        with pytest.raises(IntegrityError) as exc:
            c.execute(text('''insert into uv_presencas(igreja_id,turma_id,matricula_id,atividade_id,aula,presente,modalidade,registro_id,registrada_por)
                values(:t,:tid,:mid,:a,1,true,'regular',:id,:u)'''),dict(t=v['t'],tid=tid,
                    mid=foreign_mid if edge=='matricula' else mid,a=foreign_activity if edge=='atividade' else activity,id=uuid4(),u=v['uid']))
        assert exc.value.orig.pgcode=='23503'


def test_correction_to_absent_and_transaction_rollback(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=setup(s,v); first=payload()
        uv.attendance(s,principal(v),tid,mid,1,first); s.commit()
    with scoped(database,v['t']) as s:
        uv.attendance(s,principal(v),tid,mid,1,payload(presente=False,anterior_id=first.id))
        assert uv.get_turma(s,principal(v),tid)['matriculas'][0]['aulas_cumpridas']==[]
        s.rollback()
    with scoped(database,v['t']) as s:
        assert uv.get_turma(s,principal(v),tid)['matriculas'][0]['aulas_cumpridas']==[1]
        assert len(uv.attendance_history(s,principal(v),tid,mid,1))==1


@pytest.mark.parametrize('target',['pessoas','igrejas'])
def test_approved_deletion_includes_revisions(database,seeded,target):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=setup(s,v); first=payload()
        uv.attendance(s,principal(v),tid,mid,1,first)
        uv.attendance(s,principal(v),tid,mid,1,payload(presente=False,anterior_id=first.id)); s.commit()
    with database.begin() as c:
        c.execute(text(f'delete from {target} where id=:id'),dict(id=v['p'] if target=='pessoas' else v['t']))
        for table in ['uv_presencas','uv_presencas_historico']:
            assert c.execute(text(f'select count(*) from {table}')).scalar_one()==0
