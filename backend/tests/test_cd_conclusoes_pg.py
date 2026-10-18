"""CD PR 5: real migration chain, tenant roles, transaction races and HTTP."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session
from tests.test_uv_turmas_pg import rls_database_url, migrated_database, database, seeded, scoped, principal
from tests.test_cd_turmas_pg import denied
from tests.test_cd_presencas_pg import setup, payload
from tests.test_cd_matriculas_pg import command
from app.services import cd
from app.routers.cd import TurmaInput, ResponsaveisInput, CurriculoInput
from types import SimpleNamespace as DTO
pytestmark = pytest.mark.rls_integration


def finish(s,v,tid,mid,*,equivalence=False,id=None,key='uid'):
    return cd.finish(s,principal(v,key),tid,mid,DTO(id=id or uuid4(),confirmado=True,
        evidencia='Documento institucional conferido' if equivalence else None),equivalence=equivalence)


def fulfill(s,v,tid,mid):
    for a in cd.get_turma(s,principal(v),tid)['modulo']['aulas']:
        cd.attendance(s,principal(v),tid,mid,a['id'],payload(modalidade='reposicao'))


def issue(s,v,cid,*,id=None,key='uid'):
    return cd.issue_certificate(s,principal(v,key),v['p'],cid,DTO(id=id or uuid4(),confirmado=True))


def short_course(s,v):
    c=cd.create_curriculo(s,principal(v),CurriculoInput(id=uuid4(),nome='Currículo sintético',versao='curto',
        aulas_por_modulo=[1,1],niveis=[dict(nome='Nível sintético',modulos=[1,2])]))
    return c


def second(s,v,c):
    return cd.create_turma(s,principal(v),TurmaInput(id=uuid4(),nome='Módulo seguinte',curriculo_id=c['id'],modulo_id=c['modulos'][1]['id']))['id']


def test_completion_requires_all_lessons_and_explicit_confirmation(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid,a=setup(s,v)
        denied(lambda:finish(s,v,tid,mid),422)
        fulfill(s,v,tid,mid)
        denied(lambda:cd.finish(s,principal(v),tid,mid,DTO(id=uuid4(),confirmado=False,evidencia=None)),422)
        before=s.execute(text('select apto_lider,etapa,subetapa from pessoas where id=:p'),dict(p=v['p'])).one()
        cid=cd.get_turma(s,principal(v),tid)['curriculo_id']
        cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        rid=uuid4(); r=finish(s,v,tid,mid,id=rid,key='leader')
        assert r['origem']=='frequencia' and r['confirmada_por']==v['leader'] and r['confirmada_em']
        assert finish(s,v,tid,mid,id=rid,key='leader')==r
        denied(lambda:finish(s,v,tid,mid),409)
        denied(lambda:cd.cancel_enrollment(s,principal(v),tid,mid),409)
        denied(lambda:cd.attendance(s,principal(v),tid,mid,a,payload()),409)
        assert cd.list_enrollments(s,principal(v),tid)[0]['conclusao']['id']==rid
        assert cd.person_progress(s,principal(v),v['p'],cid)['conclusoes'][0]['id']==rid
        assert s.execute(text('select apto_lider,etapa,subetapa from pessoas where id=:p'),dict(p=v['p'])).one()==before


@pytest.mark.parametrize('state',['unlinked','removed','revoked','cancelled','archived','closed','equivalence_leader','empty_evidence'])
def test_live_guards(database,seeded,state):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid,a=setup(s,v); fulfill(s,v,tid,mid)
        if state!='unlinked': cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        if state=='removed': cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[]))
        if state=='cancelled': cd.cancel_enrollment(s,principal(v),tid,mid)
        if state=='closed': cd.close(s,principal(v),tid)
        if state=='archived': s.execute(text('update pessoas set arquivada_em=now() where id=:p'),dict(p=v['p']))
        s.commit()
    if state=='revoked':
        with database.begin() as c: c.execute(text("update app_users set status='revogado' where id=:u"),dict(u=v['leader']))
    with scoped(database,v['t']) as s:
        key='leader' if state in {'unlinked','removed','revoked','equivalence_leader'} else 'uid'
        action=(lambda:cd.finish(s,principal(v),tid,mid,DTO(id=uuid4(),confirmado=True,evidencia='  '),equivalence=True)) if state=='empty_evidence' else lambda:finish(s,v,tid,mid,key=key,equivalence=state=='equivalence_leader')
        denied(action,404 if state in {'unlinked','removed','archived'} else 403 if state in {'revoked','equivalence_leader'} else 422 if state=='empty_evidence' else 409)


def test_progression_levels_certification_snapshots_reissue_and_no_promotion(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        from tests.test_cd_matriculas_pg import legacy
        from tests.test_cd_turmas_pg import create
        legacy(s,v); c=short_course(s,v); t1=create(s,v,c); t2=second(s,v,c)
        assert cd.eligible(s,principal(v),t2)==[]
        denied(lambda:cd.enroll(s,principal(v),t2,command(v)),409)
        m1=cd.enroll(s,principal(v),t1,command(v))['id']
        before=s.execute(text('select apto_lider,etapa,subetapa from pessoas where id=:p'),dict(p=v['p'])).one()
        r1=finish(s,v,t1,m1,equivalence=True)
        assert r1['origem']=='equivalencia' and r1['evidencia']
        assert cd.eligible(s,principal(v),t1)==[]
        assert len(cd.eligible(s,principal(v),t2))==1
        denied(lambda:issue(s,v,c['id']),422)
        denied(lambda:issue(s,v,c['id'],key='leader'),403)
        m2=cd.enroll(s,principal(v),t2,command(v))['id']
        r2=finish(s,v,t2,m2,equivalence=True)
        progress=cd.person_progress(s,principal(v),v['p'],c['id'])
        assert progress['niveis_concluidos']==[c['niveis'][0]['id']]
        cert_id=uuid4(); cert=issue(s,v,c['id'],id=cert_id)
        assert set(cert['conclusoes_ids'])=={r1['id'],r2['id']}
        assert cert['nome_pessoa']=='Aluno sintético' and cert['nome_curriculo']==c['nome']
        assert cert['versao_curriculo']=='curto' and cert['codigo'] and cert['emitida_por']==v['uid']
        assert issue(s,v,c['id'],id=cert_id)==cert
        denied(lambda:issue(s,v,c['id']),409)
        s.execute(text("update pessoas set nome='Nome novo' where id=:p"),dict(p=v['p']))
        cd.rename_catalog(s,principal(v),c['id'],'curriculo',c['id'],DTO(nome='Título novo'))
        assert cd.person_progress(s,principal(v),v['p'],c['id'])['certificados'][0]==cert
        reason=DTO(motivo='Correção administrativa')
        denied(lambda:cd.revoke_certificate(s,principal(v,'leader'),cert_id,reason),403)
        revoked=cd.revoke_certificate(s,principal(v),cert_id,reason)
        assert revoked['revogada_por']==v['uid'] and revoked['revogada_em'] and revoked['motivo_revogacao']==reason.motivo
        assert cd.revoke_certificate(s,principal(v),cert_id,reason)==revoked
        denied(lambda:issue(s,v,c['id'],id=cert_id),409)
        new=issue(s,v,c['id'])
        assert new['id']!=cert_id and new['codigo']!=cert['codigo']
        assert new['nome_pessoa']=='Nome novo' and new['nome_curriculo']=='Título novo'
        assert s.execute(text('select apto_lider,etapa,subetapa from pessoas where id=:p'),dict(p=v['p'])).one()==before
        assert len(cd.person_progress(s,principal(v),v['p'],c['id'])['certificados'])==2


@pytest.mark.parametrize('operation',['completion','certificate'])
@pytest.mark.parametrize('same_key',[True,False])
def test_concurrent_commands(database,seeded,operation,same_key):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid,a=setup(s,v); fulfill(s,v,tid,mid)
        cid=cd.get_turma(s,principal(v),tid)['curriculo_id']
        if operation=='certificate':
            finish(s,v,tid,mid)
            c=cd.catalog(s,v['t'],cid)
            for m in c['modulos'][1:]:
                nt=cd.create_turma(s,principal(v),TurmaInput(id=uuid4(),nome='Seguinte',curriculo_id=cid,modulo_id=m['id']))['id']
                nm=cd.enroll(s,principal(v),nt,command(v))['id']; finish(s,v,nt,nm,equivalence=True)
        s.commit()
    one=uuid4(); ids=[one,one if same_key else uuid4()]; barrier=Barrier(2)
    def attempt(rid):
        with scoped(database,v['t']) as s:
            barrier.wait(timeout=10)
            try:
                if operation=='completion': finish(s,v,tid,mid,id=rid)
                else: issue(s,v,cid,id=rid)
                s.commit(); return 200
            except HTTPException as exc: s.rollback(); return exc.status_code
    with ThreadPoolExecutor(2) as pool: result=list(pool.map(attempt,ids))
    assert sorted(result)==([200,200] if same_key else [200,409])


def test_tenants_idor_rls_and_constraints(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid,a=setup(s,v); finish(s,v,tid,mid,equivalence=True)
        cid=cd.get_turma(s,principal(v),tid)['curriculo_id']
        for module in cd.catalog(s,v['t'],cid)['modulos'][1:]:
            nt=cd.create_turma(s,principal(v),TurmaInput(id=uuid4(),nome='Seguinte',curriculo_id=cid,modulo_id=module['id']))['id']
            nm=cd.enroll(s,principal(v),nt,command(v))['id']; finish(s,v,nt,nm,equivalence=True)
        cert=issue(s,v,cid); s.commit()
    with database.begin() as c:
        c.execute(text("insert into app_users(id,igreja_id,status,nome,email) values(:u,:u,'ativo','Outro','other@example.test')"),dict(u=v['other']))
        c.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:u,:u,'admin')"),dict(u=v['other']))
    with Session(database) as s:
        u=principal(v,'other','other')
        denied(lambda:cd.person_progress(s,u,v['p'],cid),404)
        denied(lambda:cd.finish(s,u,tid,mid,DTO(id=uuid4(),confirmado=True,evidencia='Documento'),equivalence=True),404)
        denied(lambda:cd.issue_certificate(s,u,v['p'],cid,DTO(id=uuid4(),confirmado=True)),404)
        denied(lambda:cd.revoke_certificate(s,u,cert['id'],DTO(motivo='Motivo')),404)
    for table in ('cd_conclusoes','cd_certificados','cd_certificado_conclusoes'):
        with scoped(database,v['other']) as s:
            assert s.execute(text(f'select count(*) from {table}')).scalar_one()==0
            with pytest.raises(ProgrammingError),s.begin_nested(): s.execute(text(f'delete from {table}'))
        with database.connect() as c:
            assert c.execute(text('select relrowsecurity,relforcerowsecurity from pg_class where oid=cast(:t as regclass)'),dict(t=table)).one()==(True,True)
            for role in ('anon','service_role'):
                for privilege in ('SELECT','INSERT','UPDATE','DELETE'):
                    assert not c.execute(text('select has_table_privilege(:r,:t,:p)'),dict(r=role,t=table,p=privilege)).scalar_one()


def test_http_completion_and_equivalence(database,seeded):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.deps import get_current_user
    from app.db.session import get_db
    from app.routers.cd import router
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid,a=setup(s,v); fulfill(s,v,tid,mid); s.commit()
    app=FastAPI(); app.include_router(router)
    def db():
        with scoped(database,v['t']) as s: yield s
    app.dependency_overrides[get_db]=db; app.dependency_overrides[get_current_user]=lambda:principal(v)
    with TestClient(app) as client:
        path=f'/cd/turmas/{tid}/matriculas/{mid}'
        assert client.post(path+'/conclusao',json=dict(id=str(uuid4()),confirmado=False)).status_code==422
        assert client.post(path+'/equivalencia',json=dict(id=str(uuid4()),confirmado=True,evidencia='  ')).status_code==422
        r=client.post(path+'/conclusao',json=dict(id=str(uuid4()),confirmado=True))
        assert r.status_code==200,r.text
        cid=client.get(f'/cd/turmas/{tid}').json()['curriculo_id']
        assert len(client.get(f'/cd/pessoas/{v["p"]}/curriculos/{cid}').json()['conclusoes'])==1


def test_prerequisites_are_specific_to_curriculum_version(database,seeded):
    from tests.test_cd_turmas_pg import create, curriculum
    from tests.test_cd_matriculas_pg import legacy
    v=seeded
    with scoped(database,v['t']) as s:
        legacy(s,v); c1=curriculum(s,v); t1=create(s,v,c1)
        m1=cd.enroll(s,principal(v),t1,command(v))['id']; finish(s,v,t1,m1,equivalence=True)
        c2=curriculum(s,v); t2=second(s,v,c2)
        assert cd.eligible(s,principal(v),t2)==[]
        denied(lambda:cd.enroll(s,principal(v),t2,command(v)),409)


def test_equivalence_evidence_bounds_and_identity_conflicts(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid,a=setup(s,v)
        for evidence in (None,'\t\n','x'*301):
            denied(lambda:cd.finish(s,principal(v),tid,mid,DTO(id=uuid4(),confirmado=True,evidencia=evidence),equivalence=True),422)
        rid=uuid4(); finish(s,v,tid,mid,equivalence=True,id=rid)
        denied(lambda:cd.finish(s,principal(v),tid,mid,DTO(id=rid,confirmado=True,evidencia='Outra evidência'),equivalence=True),409)
        denied(lambda:finish(s,v,tid,mid,id=rid),409)


def test_certificate_database_constraints_and_postgrest_guards(database,seeded):
    from tests.test_cd_turmas_pg import create
    from tests.test_cd_matriculas_pg import legacy
    v=seeded
    with scoped(database,v['t']) as s:
        legacy(s,v); c=short_course(s,v)
        for module in c['modulos']:
            tid=cd.create_turma(s,principal(v),TurmaInput(id=uuid4(),nome='Turma',curriculo_id=c['id'],modulo_id=module['id']))['id']
            mid=cd.enroll(s,principal(v),tid,command(v))['id']; finish(s,v,tid,mid,equivalence=True)
        cert=issue(s,v,c['id']); s.commit()
    with scoped(database,v['t']) as s:
        for field in ('nome_pessoa','nome_curriculo','versao_curriculo','emitida_em','emitida_por','codigo','revogada_em'):
            assert not s.execute(text("select has_column_privilege(current_user,'cd_certificados',:f,'UPDATE')"),dict(f=field)).scalar_one()
        with pytest.raises(IntegrityError),s.begin_nested():
            s.execute(text('update cd_certificados set revogada=true where id=:id'),dict(id=cert['id']))
        with pytest.raises(IntegrityError),s.begin_nested():
            s.execute(text('update cd_matriculas set ativa=false,cancelada_por=:u,cancelada_em=now() where id=:id'),dict(id=mid,u=v['uid']))
        for table in ('cd_conclusoes','cd_certificado_conclusoes'):
            assert not s.execute(text('select has_table_privilege(current_user,:t,\'UPDATE\')'),dict(t=table)).scalar_one()
        cd.revoke_certificate(s,principal(v),cert['id'],DTO(motivo='Motivo'))
        with pytest.raises(IntegrityError),s.begin_nested():
            s.execute(text("update cd_certificados set revogada=true,motivo_revogacao='Outro' where id=:id"),dict(id=cert['id']))
        s.commit()
    # Even a bypass connection cannot link someone else's or another version's completion.
    with database.begin() as conn:
        person=uuid4()
        conn.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'Outra','550000000003')"),dict(p=person,t=v['t']))
        with pytest.raises(IntegrityError),conn.begin_nested():
            conn.execute(text('''insert into cd_certificado_conclusoes(igreja_id,certificado_id,conclusao_id,pessoa_id,curriculo_id)
                values(:t,:id,:conclusao,:p,:c)'''),dict(t=v['t'],id=cert['id'],conclusao=cert['conclusoes_ids'][0],p=person,c=c['id']))
        conn.exec_driver_sql("do $$ begin if not exists(select 1 from pg_roles where rolname='authenticator') then create role authenticator nologin; end if; end $$")
        conn.exec_driver_sql('grant authenticated to authenticator')
        conn.execute(text("update app_users set clerk_user_id='synthetic-clerk' where id=:u"),dict(u=v['uid']))
    for table in ('cd_conclusoes','cd_certificados','cd_certificado_conclusoes'):
        with scoped(database,v['t']) as s:
            s.execute(text('set local session authorization authenticator')); s.execute(text('set local role authenticated'))
            assert s.execute(text(f'select count(*) from {table}')).scalar_one()==0
        with Session(database) as s:
            s.execute(text('set local role authenticated'))
            s.execute(text("select set_config('request.jwt.claims',:c,true)"),dict(c='{"sub":"synthetic-clerk"}'))
            assert s.execute(text(f'select count(*) from {table}')).scalar_one()==0


def test_http_certificate_revoke_reissue_and_no_enviar_side_effect(database,seeded):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.deps import get_current_user
    from app.db.session import get_db
    from app.routers.cd import router
    from tests.test_cd_matriculas_pg import legacy
    v=seeded
    with scoped(database,v['t']) as s:
        legacy(s,v); c=short_course(s,v)
        for module in c['modulos']:
            tid=cd.create_turma(s,principal(v),TurmaInput(id=uuid4(),nome='Turma',curriculo_id=c['id'],modulo_id=module['id']))['id']
            mid=cd.enroll(s,principal(v),tid,command(v))['id']; finish(s,v,tid,mid,equivalence=True)
        # CD cannot create a nomination, multiplication or transition to Enviar.
        before={table:s.execute(text(f'select count(*) from {table} where igreja_id=:t'),dict(t=v['t'])).scalar_one() for table in ('celula_solicitacao','multiplicacoes')}
        person_before=s.execute(text('select apto_lider,etapa,subetapa from pessoas where id=:p'),dict(p=v['p'])).one()
        s.commit()
    app=FastAPI(); app.include_router(router)
    def db():
        with scoped(database,v['t']) as s: yield s
    app.dependency_overrides[get_db]=db; app.dependency_overrides[get_current_user]=lambda:principal(v)
    with TestClient(app) as client:
        path=f'/cd/pessoas/{v["p"]}/curriculos/{c["id"]}'
        assert client.post(path+'/certificados',json=dict(id=str(uuid4()),confirmado=False)).status_code==422
        r=client.post(path+'/certificados',json=dict(id=str(uuid4()),confirmado=True)); assert r.status_code==200,r.text
        cert=r.json(); revoke=f'/cd/certificados/{cert["id"]}/revogar'
        assert client.post(revoke,json=dict(motivo=' ')).status_code==422
        assert client.post(revoke,json=dict(motivo='Correção')).status_code==200
        assert client.post(path+'/certificados',json=dict(id=str(uuid4()),confirmado=True)).status_code==200
        assert len(client.get(path).json()['certificados'])==2
    with scoped(database,v['t']) as s:
        assert {table:s.execute(text(f'select count(*) from {table} where igreja_id=:t'),dict(t=v['t'])).scalar_one() for table in before}==before
        assert s.execute(text('select apto_lider,etapa,subetapa from pessoas where id=:p'),dict(p=v['p'])).one()==person_before
