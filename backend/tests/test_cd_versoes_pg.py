"""Pastoral decision 6: explicit equivalence across curriculum versions."""
from uuid import uuid4
from types import SimpleNamespace as DTO
import pytest
from tests.test_uv_turmas_pg import rls_database_url, migrated_database, database, seeded, scoped, principal
from tests.test_cd_turmas_pg import curriculum, create, denied
from tests.test_cd_matriculas_pg import legacy, command
from tests.test_cd_conclusoes_pg import finish, second
from app.services import cd

pytestmark = pytest.mark.rls_integration


def test_previous_completion_does_not_reserve_ongoing_enrollment(database, seeded):
    v = seeded
    with scoped(database, v['t']) as s:
        legacy(s, v)
        c1 = curriculum(s, v)
        t1 = create(s, v, c1)
        mid = cd.enroll(s, principal(v), t1, command(v))['id']
        finish(s, v, t1, mid, equivalence=True)
        c2 = curriculum(s, v)
        t2 = create(s, v, c2)
        assert [p['id'] for p in cd.eligible(s, principal(v), t2)] == [v['p']]
        assert cd.enroll(s, principal(v), t2, command(v))['id']


def version_pair(s,v):
    from app.routers.cd import CalendarioInput, CurriculoInput
    from tests.test_cd_conclusoes_pg import fulfill
    from datetime import date
    legacy(s,v)
    c1=curriculum(s,v,aulas_por_modulo=[1,1])
    t1=create(s,v,c1); mid=cd.enroll(s,principal(v),t1,command(v))['id']
    cd.calendar(s,principal(v),t1,CalendarioInput(aulas=[dict(aula_id=c1['modulos'][0]['aulas'][0]['id'],data=date(2020,1,1))]))
    fulfill(s,v,t1,mid); source=finish(s,v,t1,mid)
    c2=cd.create_curriculo(s,principal(v),CurriculoInput(id=uuid4(),nome='Nova edição',versao=str(uuid4()),
        curriculo_anterior_id=c1['id'],aulas_por_modulo=[1,1]))
    return c1,c2,source


def equivalent(s,v,c,source,**kw):
    from app.routers.cd import EquivalenciaVersaoInput
    data=dict(id=uuid4(),confirmado=True,modulo_id=c['modulos'][0]['id'],conclusao_origem_id=source['id'],evidencia='Histórico institucional conferido')
    data.update(kw)
    return cd.register_version_equivalence(s,principal(v),v['p'],c['id'],EquivalenciaVersaoInput(**data))


def test_equivalence_unlocks_progression_without_destination_enrollment(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        c1,c2,source=version_pair(s,v); tid=second(s,v,c2)
        assert c1['familia_id']==c2['familia_id']
        denied(lambda:cd.enroll(s,principal(v),tid,command(v)),409)
        assert cd.eligible(s,principal(v),tid)==[]
        rid=uuid4(); receipt=equivalent(s,v,c2,source,id=rid)
        assert receipt['conclusao_origem_id']==source['id'] and receipt['registrada_por']==v['uid'] and receipt['registrada_em']
        assert equivalent(s,v,c2,source,id=rid)==receipt
        denied(lambda:equivalent(s,v,c2,source,id=rid,evidencia='Outra evidência'),409)
        assert len(cd.eligible(s,principal(v),tid))==1
        assert cd.enroll(s,principal(v),tid,command(v))['id']
        from sqlalchemy import text
        assert s.execute(text('select count(*) from cd_matriculas where modulo_id=:m'),dict(m=c2['modulos'][0]['id'])).scalar_one()==0
        assert cd.person_progress(s,principal(v),v['p'],c2['id'])['equivalencias'][0]['valida']


@pytest.mark.parametrize('invalid',['leader','family','tenant','person','module','revoked','confirmation'])
def test_equivalence_rejects_invalid_origin_or_actor(database,seeded,invalid):
    from app.routers.cd import EquivalenciaVersaoInput
    from sqlalchemy import text
    v=seeded
    with scoped(database,v['t']) as s:
        c1,c2,source=version_pair(s,v)
        target=curriculum(s,v) if invalid=='family' else c2
        data=EquivalenciaVersaoInput(id=uuid4(),confirmado=invalid!='confirmation',
            modulo_id=target['modulos'][1 if invalid=='module' else 0]['id'],conclusao_origem_id=source['id'],evidencia='Histórico conferido')
        if invalid=='person':
            pid=uuid4(); s.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'Outra pessoa sintética','550000000004')"),dict(p=pid,t=v['t']))
        else: pid=v['p']
        s.commit()
    if invalid=='revoked':
        with database.begin() as c: c.execute(text('update cd_conclusoes set revogada=true where id=:id'),dict(id=source['id']))
    with scoped(database,v['other'] if invalid=='tenant' else v['t']) as s:
        user=principal(v,'leader' if invalid=='leader' else 'uid','other' if invalid=='tenant' else 't')
        denied(lambda:cd.register_version_equivalence(s,user,pid,target['id'],data),403 if invalid in {'leader','tenant'} else 422 if invalid=='confirmation' else 409)


@pytest.mark.parametrize('mixed',[False,True])
def test_certificate_snapshots_equivalences_and_revoked_source_blocks_new_use(database,seeded,mixed):
    from sqlalchemy import text
    from tests.test_cd_conclusoes_pg import issue
    v=seeded
    with scoped(database,v['t']) as s:
        c1,c2,source=version_pair(s,v); e1=equivalent(s,v,c2,source)
        t2=second(s,v,c1); m2=cd.enroll(s,principal(v),t2,command(v))['id']
        r2=finish(s,v,t2,m2,equivalence=True)
        if mixed:
            target=second(s,v,c2); mid=cd.enroll(s,principal(v),target,command(v))['id']
            e2=finish(s,v,target,mid,equivalence=True)
        else:
            e2=equivalent(s,v,c2,r2,modulo_id=c2['modulos'][1]['id'])
        cert=issue(s,v,c2['id'])
        assert cert['conclusoes_ids']==([e2['id']] if mixed else [])
        assert set(cert['equivalencias_ids'])==({e1['id']} if mixed else {e1['id'],e2['id']})
        cd.revoke_certificate(s,principal(v),cert['id'],DTO(motivo='Correção'))
        s.commit()
    with database.begin() as c: c.execute(text('update cd_conclusoes set revogada=true where id=:id'),dict(id=source['id']))
    with scoped(database,v['t']) as s:
        denied(lambda:issue(s,v,c2['id']),422)
        tid=second(s,v,c2); denied(lambda:cd.enroll(s,principal(v),tid,command(v)),409)
        assert not next(e for e in cd.person_progress(s,principal(v),v['p'],c2['id'])['equivalencias'] if e['id']==e1['id'])['valida']


@pytest.mark.parametrize('same_key',[True,False])
def test_concurrent_equivalences(database,seeded,same_key):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    v=seeded
    with scoped(database,v['t']) as s:
        _,c2,source=version_pair(s,v); s.commit()
    rid=uuid4(); ids=[rid,rid if same_key else uuid4()]; barrier=Barrier(2)
    def attempt(key):
        with scoped(database,v['t']) as s:
            barrier.wait(timeout=10)
            try: equivalent(s,v,c2,source,id=key); s.commit(); return 200
            except HTTPException as exc: s.rollback(); return exc.status_code
    with ThreadPoolExecutor(2) as pool: results=list(pool.map(attempt,ids))
    assert sorted(results)==([200,200] if same_key else [200,409])


def test_equivalence_rls_grants_and_database_guard(database,seeded):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError, ProgrammingError
    v=seeded
    with scoped(database,v['t']) as s:
        _,c2,source=version_pair(s,v); receipt=equivalent(s,v,c2,source); other=curriculum(s,v)
        for privilege in ('USAGE','SELECT','UPDATE'):
            assert not s.execute(text("select has_sequence_privilege(current_user,'cd_curriculos_ordem_versao_seq',:p)"),dict(p=privilege)).scalar_one()
        with pytest.raises(IntegrityError),s.begin_nested():
            s.execute(text('''insert into cd_equivalencias_versoes(id,igreja_id,pessoa_id,curriculo_id,modulo_id,conclusao_origem_id,evidencia,registrada_por)
                values(:id,:t,:p,:c,:m,:source,'Prova',:u)'''),dict(id=uuid4(),t=v['t'],p=v['p'],c=other['id'],m=other['modulos'][0]['id'],source=source['id'],u=v['uid']))
        s.commit()
    for table in ('cd_equivalencias_versoes','cd_certificado_equivalencias'):
        with scoped(database,v['other']) as s:
            assert s.execute(text(f'select count(*) from {table}')).scalar_one()==0
            for action in ('DELETE','UPDATE'):
                assert not s.execute(text('select has_table_privilege(current_user,:t,:p)'),dict(t=table,p=action)).scalar_one()
            with pytest.raises(ProgrammingError),s.begin_nested(): s.execute(text(f'delete from {table}'))
        with database.connect() as c:
            assert c.execute(text('select relrowsecurity,relforcerowsecurity from pg_class where oid=cast(:t as regclass)'),dict(t=table)).one()==(True,True)
            for role in ('anon','service_role'):
                for privilege in ('SELECT','INSERT','UPDATE','DELETE'):
                    assert not c.execute(text('select has_table_privilege(:r,:t,:p)'),dict(r=role,t=table,p=privilege)).scalar_one()


def test_foreign_church_conclusion_is_rejected_by_service_and_composite_fk(database,seeded):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    v=seeded
    with scoped(database,v['t']) as s:
        _,c2,_=version_pair(s,v); s.commit()
    # Independent synthetic church and real completion, using its own actor.
    other=dict(v,t=v['other'],uid=uuid4(),p=uuid4())
    with database.begin() as c:
        c.execute(text("insert into app_users(id,igreja_id,status,nome,email) values(:u,:t,'ativo','Coordenação sintética','other@example.test')"),dict(u=other['uid'],t=other['t']))
        c.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:t,:u,'admin')"),dict(u=other['uid'],t=other['t']))
        c.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'Aluno sintético B','550000000005')"),dict(p=other['p'],t=other['t']))
    with scoped(database,other['t']) as s:
        _,_,foreign=version_pair(s,other); s.commit()
    with scoped(database,v['t']) as s:
        denied(lambda:equivalent(s,v,c2,foreign),409)
        with pytest.raises(IntegrityError),s.begin_nested():
            s.execute(text('''insert into cd_equivalencias_versoes(id,igreja_id,pessoa_id,curriculo_id,modulo_id,conclusao_origem_id,evidencia,registrada_por)
                values(:id,:t,:p,:c,:m,:source,'Prova',:u)'''),dict(id=uuid4(),t=v['t'],p=v['p'],c=c2['id'],m=c2['modulos'][0]['id'],source=foreign['id'],u=v['uid']))


def test_ongoing_enrollment_still_unique_across_versions(database,seeded):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    v=seeded
    with scoped(database,v['t']) as s:
        c1,c2,_=version_pair(s,v)
        c3=curriculum(s,v); t2=create(s,v,c2); t3=create(s,v,c3); s.commit()
    barrier=Barrier(2)
    def attempt(tid):
        with scoped(database,v['t']) as s:
            barrier.wait(timeout=10)
            try: cd.enroll(s,principal(v),tid,command(v)); s.commit(); return 200
            except HTTPException as exc: s.rollback(); return exc.status_code
    with ThreadPoolExecutor(2) as pool: assert sorted(pool.map(attempt,[t2,t3]))==[200,409]
    with scoped(database,v['t']) as s:
        # A direct writer cannot forge completion to free the ongoing slot.
        s.execute(text('update cd_matriculas set concluida=true where not concluida'))
        assert s.execute(text('select count(*) from cd_matriculas where ativa and not concluida')).scalar_one()==1
        with pytest.raises(IntegrityError),s.begin_nested():
            s.execute(text('update cd_conclusoes set id=:id'),dict(id=uuid4()))


def test_http_equivalence_without_destination_turma_and_live_coordination(database,seeded):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.db.session import get_db
    from app.deps import get_current_user
    from app.routers.cd import router
    v=seeded
    with scoped(database,v['t']) as s:
        _,c2,source=version_pair(s,v); s.commit()
    app=FastAPI(); app.include_router(router)
    def db():
        with scoped(database,v['t']) as s: yield s
    app.dependency_overrides[get_db]=db
    app.dependency_overrides[get_current_user]=lambda:principal(v)
    path=f'/cd/pessoas/{v["p"]}/curriculos/{c2["id"]}'
    data=dict(id=str(uuid4()),confirmado=True,modulo_id=str(c2['modulos'][0]['id']),conclusao_origem_id=str(source['id']),evidencia='Histórico institucional conferido')
    with TestClient(app) as client:
        assert client.get(f'/cd/curriculos/{c2["id"]}/pessoas-equivalencia?q=Aluno').json()==[dict(id=str(v['p']),nome='Aluno sintético')]
        assert len(client.get(path+'/origens-equivalencia').json())==1
        for _ in range(2):
            response=client.post(path+'/equivalencias',json=data); assert response.status_code==200,response.text
        assert client.get(path).json()['equivalencias'][0]['valida']
        app.dependency_overrides[get_current_user]=lambda:principal(v,'leader')
        assert client.post(path+'/equivalencias',json=data).status_code==403
        assert client.get(path+'/origens-equivalencia').status_code==403


def test_equivalence_cannot_flow_from_newer_to_older_version(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        c1,c2,_=version_pair(s,v)
        tid=create(s,v,c2); mid=cd.enroll(s,principal(v),tid,command(v))['id']
        newer=finish(s,v,tid,mid,equivalence=True)
        denied(lambda:equivalent(s,v,c1,newer),409)
