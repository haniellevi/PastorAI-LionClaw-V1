"""Erasure through authenticated web over synthetic PostgreSQL."""
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.test_uv_turmas_pg import rls_database_url, migrated_database, database, seeded, scoped
from tests.test_conhecimento_api_pg import create, edit, publish
from tests.test_uv_turmas_pg import principal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db.session import get_db
from app.deps import get_current_user
from app.routers.conhecimento import router
pytestmark=pytest.mark.rls_integration

def client(database,v,key='uid',authenticated=True):
    app=FastAPI(); app.include_router(router); app.state.clerk_client=object()
    def db():
        with scoped(database,v['t']) as s:
            s.execute(text("select set_config('request.jwt.claim.sub','synthetic',true)"))
            yield s
    app.dependency_overrides[get_db]=db
    if authenticated: app.dependency_overrides[get_current_user]=lambda:principal(v,key)
    return TestClient(app)

def subject(database,v):
    with database.begin() as s:
        s.execute(text("update app_users set clerk_user_id='synthetic' where id=:u"),dict(u=v['uid']))

def erase(c,p):
    return c.post(f"/conhecimento/documentos/{p['id']}/excluir",json=dict(operacao_id=str(uuid4()),confirmacao='EXCLUIR DOCUMENTO'))

def test_erases_all_versions_chunks_search_preserves_audit_and_replays(database,seeded):
    v=seeded; subject(database,v)
    with client(database,v) as c:
        first=create(c,v); p=edit(c,first); publish(c,p)
        assert c.get('/conhecimento/busca?q=orientacao').json()
        with database.connect() as s: before=s.execute(text('select * from conhecimento_operacoes order by id')).all()
        payload=dict(operacao_id=str(uuid4()),confirmacao='EXCLUIR DOCUMENTO')
        path=f"/conhecimento/documentos/{p['id']}/excluir"
        r=c.post(path,json=payload); assert r.status_code==200,r.text
        assert r.json()['estado']=='concluido' and r.json()['versoes']==2 and r.json()['trechos']>0
        assert c.post(path,json=payload).json()==r.json()
        resurrect=dict(first,operacao_id=str(uuid4()),versao_id=str(uuid4()))
        assert c.post('/conhecimento/documentos',json=resurrect).status_code==409
        assert c.post(path,json=payload).json()==r.json()
        assert c.get('/conhecimento/busca?q=orientacao').json()==[]
        assert c.get('/conhecimento/versoes/'+p['versao_id']).status_code==404
        with database.connect() as s:
            for table in ('conhecimento_documentos','conhecimento_versoes','conhecimento_trechos'):
                assert s.execute(text(f'select count(*) from {table}')).scalar()==0
            assert s.execute(text('select * from conhecimento_operacoes order by id')).all()==before
        assert c.get('/conhecimento/documentos').json()['documentos']==[]

@pytest.mark.parametrize('key',['leader','outsider'])
def test_denies_live_non_admin_even_with_claim(database,seeded,key):
    subject(database,seeded)
    with client(database,seeded) as c: p=create(c,seeded)
    with client(database,seeded,key) as c: assert erase(c,p).status_code==403

def test_confirmation_auth_scope_subject_required(database,seeded):
    v=seeded
    with client(database,v) as c:
        p=create(c,v); assert erase(c,p).status_code==403
        assert c.post(f"/conhecimento/documentos/{p['id']}/excluir",json=dict(operacao_id=str(uuid4()),confirmacao='sim')).status_code==422
    with client(database,v,authenticated=False) as c: assert erase(c,p).status_code==401
    subject(database,v)
    with client(database,v) as c: assert erase(c,dict(p,id=str(uuid4()))).status_code==404
    with scoped(database,v['other']) as s:
        with pytest.raises(DBAPIError): s.execute(text('select conhecimento_excluir_documento(:t,:d,:o,:u)'),dict(t=v['t'],d=p['id'],o=uuid4(),u=v['uid']))

def test_direct_delete_and_snapshot_changes_forbidden(database,seeded):
    v=seeded
    with client(database,v) as c: create(c,v)
    for sql in ('delete from conhecimento_versoes',"update conhecimento_versoes set conteudo='alterado'",'delete from conhecimento_documentos'):
        with database.connect() as s:
            with pytest.raises(DBAPIError): s.execute(text(sql))
    with scoped(database,v['t']) as s:
        with pytest.raises(DBAPIError): s.execute(text('delete from conhecimento_versoes'))


def test_owner_cannot_forge_receipt_and_marker_to_bypass_function(database,seeded):
    v=seeded; subject(database,v)
    with client(database,v) as c: p=create(c,v)
    with database.begin() as s:
        op=uuid4()
        with pytest.raises(DBAPIError):
            s.execute(text("insert into conhecimento_exclusoes(igreja_id,operacao_id,documento_id,ator_id,versoes,trechos) values(:t,:o,:d,:u,1,0)"),dict(t=v['t'],o=op,d=p['id'],u=v['uid']))
        s.rollback()


def test_concurrent_same_operation_recovers_one_receipt(database,seeded):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    v=seeded; subject(database,v)
    with client(database,v) as c: p=create(c,v)
    payload=dict(operacao_id=str(uuid4()),confirmacao='EXCLUIR DOCUMENTO'); barrier=Barrier(2)
    def attempt():
        with client(database,v) as c:
            barrier.wait(timeout=10)
            r=c.post(f"/conhecimento/documentos/{p['id']}/excluir",json=payload)
            return r.status_code,r.json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(attempt); b=pool.submit(attempt)
        assert a.result(timeout=20)==b.result(timeout=20)
        assert a.result()[0]==200


def test_owner_with_web_context_cannot_delete_directly(database,seeded):
    v=seeded; subject(database,v)
    with client(database,v) as c: create(c,v)
    with database.begin() as s:
        s.execute(text("select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claim.sub','synthetic',true),set_config('app.conhecimento_exclusao',:o,true)"),dict(t=str(v['t']),o=str(uuid4())))
        with pytest.raises(DBAPIError): s.execute(text('delete from conhecimento_versoes'))
        s.rollback()


def test_recreate_waiting_on_uncommitted_erasure_cannot_resurrect(database,seeded):
    from concurrent.futures import ThreadPoolExecutor
    import time
    from app.services.conhecimento_editorial import excluir
    v=seeded; subject(database,v)
    with client(database,v) as c: p=create(c,v)
    payload=dict(p,operacao_id=str(uuid4()),versao_id=str(uuid4()))
    with scoped(database,v['t']) as s:
        s.execute(text("select set_config('request.jwt.claim.sub','synthetic',true)"))
        excluir(s,principal(v),p['id'],uuid4())
        def recreate():
            with client(database,v) as c: return c.post('/conhecimento/documentos',json=payload).status_code
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(recreate)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                with database.connect() as observer:
                    waiting=observer.execute(text("select count(*) from pg_locks where locktype='advisory' and not granted")).scalar()
                if waiting: break
                time.sleep(.01)
            assert waiting, 'Recreation must wait on the document barrier'
            s.commit()
            assert pending.result(timeout=15)==409
    with database.connect() as s:
        assert s.execute(text('select count(*) from conhecimento_documentos')).scalar()==0
