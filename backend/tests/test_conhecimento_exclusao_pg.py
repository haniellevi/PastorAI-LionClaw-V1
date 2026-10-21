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
        assert c.post('/conhecimento/documentos',json=first).status_code==410
        old_edit=dict(operacao_id=p['operacao_id'],versao_id=p['versao_id'],anterior_id=first['versao_id'],conteudo=p['conteudo'],origem=p['origem'],publicos=p['publicos'])
        assert c.post(f"/conhecimento/documentos/{p['id']}/rascunhos",json=old_edit).status_code==410
        resurrect=dict(first,operacao_id=str(uuid4()),versao_id=str(uuid4()))
        assert c.post('/conhecimento/documentos',json=resurrect).status_code==409
        assert c.post(path,json=payload).json()==r.json()
        assert c.get('/conhecimento/busca?q=orientacao').json()==[]
        assert c.get('/conhecimento/versoes/'+p['versao_id']).status_code==404
        with database.connect() as s:
            for table in ('conhecimento_documentos','conhecimento_versoes','conhecimento_trechos'):
                assert s.execute(text(f'select count(*) from {table}')).scalar()==0
            after=s.execute(text('select * from conhecimento_operacoes order by id')).all()
            assert len(after)==len(before)
            assert [{k:v for k,v in a._mapping.items() if k!='fingerprint'} for a in after] == [{k:v for k,v in b._mapping.items() if k!='fingerprint'} for b in before]
            assert all(a.fingerprint != b.fingerprint for a,b in zip(after,before))
            assert len({a.fingerprint for a in after})==1
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


def test_pastor_cannot_erase(database,seeded):
    v=seeded; subject(database,v)
    with client(database,v) as c: p=create(c,v)
    with database.begin() as s:
        s.execute(text("update user_roles set papel='pastor' where user_id=:u"),dict(u=v['leader']))
    with client(database,v,'leader') as c: assert erase(c,p).status_code==403


def test_atomic_rollback_and_church_cascade(database,seeded):
    from app.services.conhecimento_editorial import excluir
    v=seeded; subject(database,v)
    with client(database,v) as c:
        p=create(c,v,publicos=['institucional_publico']); publish(c,p)
    with scoped(database,v['t']) as s:
        s.execute(text("select set_config('request.jwt.claim.sub','synthetic',true)"))
        excluir(s,principal(v),p['id'],uuid4())
        s.rollback()
    with client(database,v) as c:
        assert c.get('/conhecimento/busca?q=orientacao').json()
    with database.connect() as s:
        assert s.execute(text('select count(*) from conhecimento_exclusoes')).scalar()==0
    with client(database,v) as c: assert erase(c,p).status_code==200
    with database.begin() as s:
        s.execute(text('delete from igrejas where id=:t'),dict(t=v['t']))
        for table in ('conhecimento_exclusoes','conhecimento_operacoes','conhecimento_trechos','conhecimento_versoes','conhecimento_documentos'):
            assert s.execute(text(f'select count(*) from {table}')).scalar()==0


def test_two_real_tenants_and_no_residual_search(database,seeded):
    v=seeded; subject(database,v); other=dict(v,t=v['other'],uid=uuid4())
    with database.begin() as s:
        s.execute(text("insert into app_users(id,igreja_id,status,nome,email) values(:u,:t,'ativo','Outro','other@example.test')"),dict(u=other['uid'],t=other['t']))
        s.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:t,:u,'admin')"),dict(u=other['uid'],t=other['t']))
    with client(database,other) as c:
        q=create(c,other,publicos=['institucional_publico']); publish(c,q)
    with client(database,v) as c:
        p=create(c,v,publicos=['institucional_publico'])
        p=edit(c,p,conteudo='Apagavelunico orientação sintética.'); publish(c,p)
        assert c.get('/conhecimento/busca?q=apagavelunico').json()
        assert erase(c,q).status_code==404
        assert erase(c,p).status_code==200
    with client(database,other) as c:
        assert c.get('/conhecimento/busca?q=orientacao').json()
    with database.begin() as s:
        s.execute(text('set local enable_seqscan=off'))
        query="select texto from conhecimento_trechos where busca @@ plainto_tsquery('public.conhecimento_portuguese','apagavelunico')"
        plan=s.execute(text('explain (costs off) '+query)).all()
        assert 'conhecimento_trechos_lexical' in str(plan)
        assert s.execute(text(query)).all()==[]
        assert s.execute(text('select count(*) from conhecimento_trechos where igreja_id=:t'),dict(t=v['t'])).scalar()==0
        # Exercise church cascade with a live official document as well.
        s.execute(text('delete from igrejas where id=:t'),dict(t=other['t']))


def test_receipt_actor_requires_same_tenant_fk(database,seeded):
    v=seeded
    with database.begin() as s:
        # Disable only the authenticated erasure trigger to isolate FK enforcement.
        s.execute(text('alter table conhecimento_exclusoes disable trigger conhecimento_recibo_apagar'))
        s.execute(text('set constraints conhecimento_exclusoes_ator_fk immediate'))
        with pytest.raises(DBAPIError) as exc:
            s.execute(text('insert into conhecimento_exclusoes(igreja_id,operacao_id,documento_id,ator_id,versoes,trechos) values(:t,:o,:d,:u,0,0)'),dict(t=v['other'],o=uuid4(),d=uuid4(),u=v['uid']))
        assert getattr(exc.value.orig,'pgcode',None)=='23503'
        s.rollback()


def quoted_message(database,v,p,preview='quoted'):
    import json
    c,m=uuid4(),uuid4()
    with database.begin() as s:
        s.execute(text("insert into conversations(id,igreja_id,pessoa_id,telefone,ultima_mensagem) values(:c,:t,:p,'550000000001',:preview)"),dict(v,c=c,preview=preview))
        s.execute(text("insert into messages(id,igreja_id,conversation_id,direcao,autor,tipo,texto,agent_privilege_context) values(:m,:t,:c,'out','ia','texto','quoted',cast(:metadata as jsonb))"),dict(v,c=c,m=m,metadata=json.dumps(dict(kind='conhecimento',fontes=[dict(versao_id=p['versao_id'])]))))
    return c,m

@pytest.mark.parametrize('preview,latest', [('quoted',False),('stale preview',True),('unrelated',False)])
def test_erasure_cleans_preview_and_summary_inside_definer(database,seeded,preview,latest):
    v=seeded; subject(database,v)
    with client(database,v) as c: p=create(c,v)
    conv,mid=quoted_message(database,v,p,preview)
    with database.begin() as s:
        if not latest:
            s.execute(text("insert into messages(igreja_id,conversation_id,direcao,autor,tipo,texto,criado_em) values(:t,:c,'in','contato','texto','unrelated',now()+interval '1 minute')"),dict(v,c=conv))
        revision=s.scalar(text('select private_summary_revision from conversations where id=:c'),dict(c=conv))
        s.execute(text("insert into private_conversation_summaries(igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation,state,summary,human_correction) values(:t,:c,:p,:r,0,'corrected','quoted','quoted')"),dict(v,c=conv,r=revision))
        s.execute(text('insert into private_summary_sources(igreja_id,conversation_id,message_id) values(:t,:c,:m)'),dict(v,c=conv,m=mid))
        s.execute(text('insert into private_summary_tasks(igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation) values(:t,:c,:p,:r,0)'),dict(v,c=conv,r=revision))
    with client(database,v) as c: assert erase(c,p).status_code==200
    with database.connect() as s:
        row=s.execute(text('select ultima_mensagem,private_summary_revision from conversations where id=:c'),dict(c=conv)).one()
        assert row.ultima_mensagem == ('unrelated' if preview=='unrelated' else '[Conhecimento oficial excluído]')
        assert row.private_summary_revision==revision+1
        assert s.scalar(text('select texto from messages where id=:m'),dict(m=mid))=='[Conhecimento oficial excluído]'
        for table in ('private_conversation_summaries','private_summary_sources','private_summary_tasks'):
            assert s.scalar(text(f'select count(*) from {table} where conversation_id=:c'),dict(c=conv))==0


def test_failure_after_redaction_rolls_back_every_layer(database,seeded):
    v=seeded; subject(database,v)
    with client(database,v) as c:
        p=create(c,v,publicos=['institucional_publico']); publish(c,p)
    conv,mid=quoted_message(database,v,p)
    with database.begin() as s:
        s.execute(text("insert into private_conversation_summaries(igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation,state,summary,human_correction) values(:t,:c,:p,1,0,'corrected','quoted','quoted')"),dict(v,c=conv))
        s.execute(text('insert into private_summary_sources(igreja_id,conversation_id,message_id) values(:t,:c,:m)'),dict(v,c=conv,m=mid))
        s.execute(text('insert into private_summary_tasks(igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation) values(:t,:c,:p,1,0)'),dict(v,c=conv))
        before=s.execute(text('select * from conhecimento_operacoes order by id')).all()
        s.execute(text("""create function conhecimento_test_fail() returns trigger language plpgsql as $$
            begin raise exception 'synthetic rollback'; end $$"""))
        s.execute(text('create trigger conhecimento_test_fail before delete on conhecimento_trechos for each row execute function conhecimento_test_fail()'))
    try:
        from app.services.conhecimento_editorial import excluir
        with scoped(database,v['t']) as s:
            s.execute(text("select set_config('request.jwt.claim.sub','synthetic',true)"))
            with pytest.raises(RuntimeError): excluir(s,principal(v),p['id'],uuid4())
            s.commit()
        with database.connect() as s:
            assert s.scalar(text('select ultima_mensagem from conversations where id=:c'),dict(c=conv))=='quoted'
            assert s.scalar(text('select texto from messages where id=:m'),dict(m=mid))=='quoted'
            assert s.execute(text('select summary,human_correction from private_conversation_summaries where conversation_id=:c'),dict(c=conv)).one()==('quoted','quoted')
            assert s.scalar(text('select private_summary_revision from conversations where id=:c'),dict(c=conv))==1
            for table in ('private_summary_sources','private_summary_tasks'):
                assert s.scalar(text(f'select count(*) from {table} where conversation_id=:c'),dict(c=conv))==1
            assert s.execute(text('select * from conhecimento_operacoes order by id')).all()==before
            assert s.execute(text('select count(*) from conhecimento_exclusoes')).scalar()==0
            assert s.execute(text('select count(*) from conhecimento_versoes')).scalar()==1
        with client(database,v) as c:
            assert c.get('/conhecimento/busca?q=orientacao').json()
    finally:
        with database.begin() as s:
            s.execute(text('drop trigger conhecimento_test_fail on conhecimento_trechos'))
            s.execute(text('drop function conhecimento_test_fail()'))


def test_deleted_document_actor_cannot_be_hard_deleted(database,seeded):
    v=seeded; subject(database,v)
    with client(database,v) as c: p=create(c,v)
    # A different admin erases, isolating the receipt FK from editorial actors.
    with database.begin() as s:
        s.execute(text("update app_users set clerk_user_id=null where id=:u"),dict(u=v['uid']))
        s.execute(text("update app_users set clerk_user_id='synthetic' where id=:u"),dict(u=v['leader']))
        s.execute(text("update user_roles set papel='admin' where user_id=:u"),dict(u=v['leader']))
    with client(database,v,'leader') as c: assert erase(c,p).status_code==200
    with pytest.raises(DBAPIError) as exc:
        with database.begin() as s:
            s.execute(text('delete from user_roles where user_id=:u'),dict(u=v['leader']))
            s.execute(text('delete from app_users where id=:u'),dict(u=v['leader']))
    assert exc.value.orig.pgcode=='23503'
    assert exc.value.orig.diag.constraint_name=='conhecimento_exclusoes_ator_fk'


@pytest.mark.parametrize('status,role,allowed', [
    (None, 'admin', True), ('ativo', 'admin', True),
    ('inativo', 'admin', False), ('suspenso', 'admin', False),
    (None, 'pastor', False), ('ativo', 'pastor', False),
])
def test_live_status_authorization_in_web_and_sql(database, seeded, status, role, allowed):
    v=seeded; subject(database,v)
    with client(database,v) as c: p=create(c,v)
    # Extend only the disposable enum to exercise these otherwise absent labels.
    with database.connect().execution_options(isolation_level='AUTOCOMMIT') as s:
        s.execute(text("alter type app_user_status add value if not exists 'inativo'"))
        s.execute(text("alter type app_user_status add value if not exists 'suspenso'"))
    with database.begin() as s:
        s.execute(text('update app_users set status=:status where id=:u'), dict(status=status,u=v['uid']))
        s.execute(text('update user_roles set papel=:role where user_id=:u'), dict(role=role,u=v['uid']))
    # Exercise SQL independently so a service refusal cannot mask a SQL bypass.
    with scoped(database,v['t']) as s:
        s.execute(text("select set_config('request.jwt.claim.sub','synthetic',true)"))
        params=dict(t=v['t'],d=p['id'],o=uuid4(),u=v['uid'])
        if allowed:
            assert s.execute(text('select conhecimento_excluir_documento(:t,:d,:o,:u)'),params).scalar()['estado']=='concluido'
            assert s.execute(text('select count(*) from conhecimento_exclusoes')).scalar()==1
        else:
            with pytest.raises(DBAPIError) as exc:
                s.execute(text('select conhecimento_excluir_documento(:t,:d,:o,:u)'),params)
            assert exc.value.orig.pgcode=='42501'
        s.rollback()
    with client(database,v) as c:
        response=erase(c,p)
        assert response.status_code==(200 if allowed else 403),response.text
    with database.connect() as s:
        assert s.execute(text('select count(*) from conhecimento_documentos')).scalar()==(0 if allowed else 1)
