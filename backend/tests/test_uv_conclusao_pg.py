"""PR4: real migration chain, live capabilities and atomic person history."""
from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from tests.test_uv_turmas_pg import (rls_database_url, migrated_database, database,
    seeded, scoped, principal)
from tests.test_uv_presencas_pg import setup, payload as attendance_payload
from app.services import uv
from app.routers.uv import MarcoInput, ConclusaoInput, ResponsaveisInput

pytestmark = pytest.mark.rls_integration


def marco(**changes):
    return MarcoInput(**(dict(id=uuid4(),data=date(2020,1,1),anterior_turma=True,confirmado=True) | changes))


def complete(s,v,missing=None):
    tid,mid=setup(s,v)
    for n in range(1,9):
        if missing != n: uv.attendance(s,principal(v),tid,mid,n,attendance_payload(modalidade='reposicao'))
    for kind in ('encontro','batismo'):
        if missing != kind: uv.milestone(s,principal(v),tid,mid,kind,marco())
    return tid,mid


@pytest.mark.parametrize('missing',list(range(1,9))+['encontro','batismo','confirmacao'])
def test_each_requirement(database,seeded,missing):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=complete(s,v,missing)
        with pytest.raises(HTTPException) as exc:
            uv.finish(s,principal(v),tid,mid,ConclusaoInput(id=uuid4(),confirmado=missing!='confirmacao'))
        assert exc.value.status_code==422
        assert s.execute(text('select count(*) from uv_conclusoes')).scalar_one()==0
        assert not s.execute(text('select apto_proxima_cd from pessoas where id=:p'),dict(p=v['p'])).scalar_one()


@pytest.mark.parametrize('legacy,ahead',[(False,False),(True,False),(False,True)])
def test_completion_history_legacy_and_no_cd(database,seeded,legacy,ahead):
    v=seeded
    with scoped(database,v['t']) as s:
        s.execute(text('update pessoas set apto_proxima_cd=:legacy,etapa=:etapa where id=:p'),dict(legacy=legacy,etapa='enviar' if ahead else 'consolidar',p=v['p']))
        tid,mid=complete(s,v)
        # No automatic retroactive completion, even with existing eligibility.
        assert s.execute(text('select count(*) from uv_conclusoes')).scalar_one()==0
        command=ConclusaoInput(id=uuid4(),confirmado=True)
        result=uv.finish(s,principal(v),tid,mid,command)
        assert uv.finish(s,principal(v),tid,mid,command)==result
        person=s.execute(text('select etapa,apto_proxima_cd,origem_aptidao_cd from pessoas where id=:p'),dict(p=v['p'])).one()
        assert tuple(person)==('enviar' if ahead else 'discipular',True,'legado' if legacy else 'conclusao_uv')
        history=s.execute(text('select pessoa_id,confirmada_por,etapa_anterior,etapa_resultante from uv_conclusoes')).one()
        assert tuple(history)==(v['p'],v['uid'],'enviar' if ahead else 'consolidar',person.etapa)
        detail=uv.get_turma(s,principal(v),tid)['matriculas'][0]
        assert detail['conclusao']['id']==command.id
        assert len(detail['marcos'])==2
        assert all(m['anterior_turma'] and m['validada_por']==v['uid'] for m in detail['marcos'])
        with pytest.raises(HTTPException) as exc: uv.finish(s,principal(v),tid,mid,ConclusaoInput(id=uuid4(),confirmado=True))
        assert exc.value.status_code==409
        assert s.execute(text("select count(*) from consolidacoes where tipo::text <> 'individual'")).scalar_one()==0


def test_milestone_idempotency_and_baptism_never_repeated(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=setup(s,v); p=marco()
        first=uv.milestone(s,principal(v),tid,mid,'batismo',p)
        assert uv.milestone(s,principal(v),tid,mid,'batismo',p)==first
        for other in (marco(),p.model_copy(update={'data':date(2019,1,1)})):
            with pytest.raises(HTTPException) as exc: uv.milestone(s,principal(v),tid,mid,'batismo',other)
            assert exc.value.status_code==409
        with pytest.raises(HTTPException): uv.milestone(s,principal(v),tid,mid,'encontro',marco(confirmado=False))


@pytest.mark.parametrize('operation',['milestone','finish'])
@pytest.mark.parametrize('state',['unlinked','removed','revoked','allowed','pastor'])
def test_capability_revalidated(database,seeded,operation,state):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=complete(s,v,'batismo' if operation=='milestone' else None)
        if state!='unlinked': uv.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        if state=='removed': uv.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[]))
        s.commit()
    with database.begin() as c:
        if state=='revoked': c.execute(text("update app_users set status='revogado' where id=:u"),dict(u=v['leader']))
        if state=='pastor':
            c.execute(text("update user_roles set papel='pastor' where user_id=:u"),dict(u=v['leader']))
            c.execute(text('update uv_responsaveis set ativo=false where usuario_id=:u'),dict(u=v['leader']))
    with scoped(database,v['t']) as s:
        def act():
            if operation=='finish': return uv.finish(s,principal(v,'leader'),tid,mid,ConclusaoInput(id=uuid4(),confirmado=True))
            # Existing milestone still requires current authorization.
            return uv.milestone(s,principal(v,'leader'),tid,mid,'batismo',marco())
        if state in {'allowed','pastor'}:
            if operation=='finish': assert act()['confirmada_por']==v['leader']
            else: assert act()['validada_por']==v['leader']
        else:
            with pytest.raises(HTTPException) as exc: act()
            assert exc.value.status_code==403


def test_reactivate_responsible_clears_removal(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=setup(s,v)
        for users in ([v['leader']],[],[v['leader']]): uv.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=users))
        r=s.execute(text('select ativo,removido_por,removida_em from uv_responsaveis where usuario_id=:u'),dict(u=v['leader'])).one()
        assert tuple(r)==(True,None,None)


def test_atomic_failure(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s: tid,mid=complete(s,v); s.commit()
    # Real SQL failure after the person update, during conclusion insertion.
    with database.begin() as c:
        c.exec_driver_sql("create function uv_test_fail() returns trigger language plpgsql as $$ begin raise exception 'synthetic failure'; end $$")
        c.exec_driver_sql('create trigger uv_test_fail before insert on uv_conclusoes for each row execute function uv_test_fail()')
    try:
        with scoped(database,v['t']) as s:
            with pytest.raises(Exception,match='synthetic failure'):
                uv.finish(s,principal(v),tid,mid,ConclusaoInput(id=uuid4(),confirmado=True)); s.commit()
            s.rollback()
        with scoped(database,v['t']) as s:
            assert s.execute(text('select count(*) from uv_conclusoes')).scalar_one()==0
            assert not s.execute(text('select apto_proxima_cd from pessoas where id=:p'),dict(p=v['p'])).scalar_one()
            assert s.execute(text('select origem_aptidao_cd from pessoas where id=:p'),dict(p=v['p'])).scalar_one() is None
    finally:
        with database.begin() as c:
            c.exec_driver_sql('drop trigger uv_test_fail on uv_conclusoes; drop function uv_test_fail()')


@pytest.mark.parametrize('same_key',[True,False])
def test_concurrent_completion(database,seeded,same_key):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    v=seeded
    with scoped(database,v['t']) as s: tid,mid=complete(s,v); s.commit()
    command=ConclusaoInput(id=uuid4(),confirmado=True); barrier=Barrier(2)
    def attempt(p):
        with scoped(database,v['t']) as s:
            barrier.wait(timeout=10)
            try: uv.finish(s,principal(v),tid,mid,p); s.commit(); return 200
            except HTTPException as exc: return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(attempt,command); b=pool.submit(attempt,command if same_key else ConclusaoInput(id=uuid4(),confirmado=True))
        assert sorted([a.result(timeout=15),b.result(timeout=15)])==([200,200] if same_key else [200,409])
    with scoped(database,v['t']) as s: assert s.execute(text('select count(*) from uv_conclusoes')).scalar_one()==1


@pytest.mark.parametrize('table',['uv_marcos','uv_conclusoes'])
def test_tenant_rls_and_immutable_records(database,seeded,table):
    from sqlalchemy.exc import ProgrammingError
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=complete(s,v); uv.finish(s,principal(v),tid,mid,ConclusaoInput(id=uuid4(),confirmado=True)); s.commit()
    with scoped(database,v['other']) as s:
        assert s.execute(text(f'select count(*) from {table}')).scalar_one()==0
        with pytest.raises(HTTPException): uv.finish(s,principal(v,tenant='other'),tid,mid,ConclusaoInput(id=uuid4(),confirmado=True))
    for verb in ('update','delete'):
        with scoped(database,v['t']) as s:
            with pytest.raises(ProgrammingError) as exc: s.execute(text(f'update {table} set pessoa_id=pessoa_id' if verb=='update' else f'delete from {table}'))
            assert exc.value.orig.pgcode=='42501'


@pytest.mark.parametrize('operation',['finish','milestone'])
def test_cross_turma_concurrency(database,seeded,operation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    v=seeded
    with scoped(database,v['t']) as s:
        a=complete(s,v,'batismo' if operation=='milestone' else None)
        b=setup(s,v)
        if operation=='finish':
            for n in range(1,9): uv.attendance(s,principal(v),*b,n,attendance_payload())
        s.commit()
    barrier=Barrier(2)
    def attempt(pair):
        with scoped(database,v['t']) as s:
            barrier.wait(timeout=10)
            try:
                if operation=='finish': uv.finish(s,principal(v),*pair,ConclusaoInput(id=uuid4(),confirmado=True))
                else: uv.milestone(s,principal(v),*pair,'batismo',marco())
                s.commit(); return 200
            except HTTPException as exc: return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        x=pool.submit(attempt,a); y=pool.submit(attempt,b)
        assert sorted([x.result(timeout=15),y.result(timeout=15)])==[200,409]


@pytest.mark.parametrize('table',['uv_marcos','uv_conclusoes'])
@pytest.mark.parametrize('edge',['tenant','person','enrollment','author'])
def test_composite_integrity(database,seeded,table,edge):
    from sqlalchemy.exc import IntegrityError,ProgrammingError
    v=seeded
    with scoped(database,v['t']) as s: tid,mid=setup(s,v); s.commit()
    foreign=uuid4()
    with database.begin() as c:
        c.execute(text("insert into app_users(id,igreja_id,status,nome,email) values(:u,:t,'ativo','Equipe','synthetic@example.test')"),dict(u=foreign,t=v['other']))
    with scoped(database,v['t']) as s:
        params=dict(id=uuid4(),t=v['other'] if edge=='tenant' else v['t'],p=uuid4() if edge=='person' else v['p'],
                    tid=tid,mid=uuid4() if edge=='enrollment' else mid,u=foreign if edge=='author' else v['uid'])
        with pytest.raises((IntegrityError,ProgrammingError)) as exc:
            if table=='uv_marcos':
                s.execute(text("insert into uv_marcos(id,igreja_id,pessoa_id,turma_id,matricula_id,tipo,data,anterior_turma,validada_por) values(:id,:t,:p,:tid,:mid,'batismo','2020-01-01',true,:u)"),params)
            else:
                s.execute(text("insert into uv_conclusoes(id,igreja_id,pessoa_id,turma_id,matricula_id,confirmada_por,etapa_resultante,origem_aptidao) values(:id,:t,:p,:tid,:mid,:u,'discipular','conclusao_uv')"),params)
        assert exc.value.orig.pgcode==('42501' if edge=='tenant' else '23503')


def test_http_full_flow_and_input_authority(database,seeded):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.uv import router
    from app.db.session import get_db
    from app.deps import get_current_user
    v=seeded
    with scoped(database,v['t']) as s: tid,mid=complete(s,v,'batismo'); s.commit()
    app=FastAPI(); app.include_router(router)
    def db():
        with scoped(database,v['t']) as s: yield s
    app.dependency_overrides[get_db]=db
    app.dependency_overrides[get_current_user]=lambda:principal(v)
    path=f'/uv/turmas/{tid}/matriculas/{mid}'
    with TestClient(app) as client:
        p=marco().model_dump(mode='json')
        assert client.post(path+'/marcos/batismo',json=p | {'validada_por':str(v['leader'])}).status_code==422
        assert client.post(path+'/marcos/batismo',json=p | {'confirmado':'true'}).status_code==422
        assert client.post(path+'/marcos/batismo',json=p | {'data':'2099-01-01'}).status_code==422
        assert client.post(path+'/marcos/batismo',json=p).status_code==200
        confirmation=ConclusaoInput(id=uuid4(),confirmado=True).model_dump(mode='json')
        assert client.post(path+'/concluir',json=confirmation).status_code==200
        assert client.post(path+'/concluir',json=confirmation).status_code==200
        detail=client.get(f'/uv/turmas/{tid}').json()['matriculas'][0]
        assert detail['conclusao']['id']==confirmation['id']
        assert detail['conexao_celula_pendente'] is True
        app.dependency_overrides[get_current_user]=lambda:principal(v,'leader')
        assert client.post(path+'/concluir',json=confirmation).status_code==403


def test_pipeline_validation_is_not_bypassed(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=complete(s,v)
        s.execute(text("update pessoas set tipo='visitante',aceitou_jesus=false,presencas_celula=0,etapa='ganhar' where id=:p"),dict(p=v['p']))
        with pytest.raises(HTTPException) as exc: uv.finish(s,principal(v),tid,mid,ConclusaoInput(id=uuid4(),confirmado=True))
        assert exc.value.status_code==409
        assert s.execute(text('select count(*) from uv_conclusoes')).scalar_one()==0


@pytest.mark.parametrize('state',['inactive','archived','closed'])
@pytest.mark.parametrize('operation',['milestone','finish'])
def test_formation_lifecycle_denials(database,seeded,state,operation):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=complete(s,v,'batismo' if operation=='milestone' else None)
        if state=='inactive': s.execute(text('update uv_matriculas set ativa=false where id=:id'),dict(id=mid))
        if state=='archived': s.execute(text('update pessoas set arquivada_em=now() where id=:p'),dict(p=v['p']))
        if state=='closed': uv.close(s,principal(v),tid)
        with pytest.raises(HTTPException) as exc:
            if operation=='finish': uv.finish(s,principal(v),tid,mid,ConclusaoInput(id=uuid4(),confirmado=True))
            else: uv.milestone(s,principal(v),tid,mid,'batismo',marco())
        assert exc.value.status_code==409


def test_completion_freezes_attendance_but_preserves_receipt_replay(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=complete(s,v)
        first=uv.get_turma(s,principal(v),tid)['matriculas'][0]['presencas'][0]
        uv.finish(s,principal(v),tid,mid,ConclusaoInput(id=uuid4(),confirmado=True))
        with pytest.raises(HTTPException) as exc:
            uv.attendance(s,principal(v),tid,mid,1,attendance_payload(presente=False,anterior_id=first['registro_id']))
        assert exc.value.status_code==409
        receipt=uv.attendance(s,principal(v),tid,mid,1,attendance_payload(id=first['registro_id'],modalidade='reposicao'))
        assert receipt['presente'] is True
        student=uv.get_turma(s,principal(v),tid)['matriculas'][0]
        assert student['aulas_pendentes']==[] and student['conclusao']
        assert s.execute(text('select count(*) from uv_presencas_historico')).scalar_one()==8


def test_reused_milestone_exposes_origin_turma(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=setup(s,v)
        uv.milestone(s,principal(v),tid,mid,'batismo',marco(anterior_turma=False))
        other,other_mid=setup(s,v)
        result=uv.get_turma(s,principal(v),other)['matriculas'][0]['marcos'][0]
        assert result['turma_id']==tid and result['turma_id']!=other
        assert result['turma_nome']=='Turma sintética'
        assert result['anterior_turma'] is False  # Relative to origin, never the displayed turma.
