"""Authenticated editorial lifecycle over real PG, no remote providers."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from app.db.session import get_db
from app.deps import get_current_user
from app.routers.conhecimento import router
from app.services.conhecimento import Visitante, pode_ler
from tests.test_uv_turmas_pg import (rls_database_url, migrated_database, database,
                                      seeded, scoped, principal)

pytestmark=pytest.mark.rls_integration


def client(database,v,key='uid',tenant='t',authenticated=True):
    app=FastAPI(); app.include_router(router)
    app.state.clerk_client=object()
    def db():
        with scoped(database,v[tenant]) as s: yield s
    app.dependency_overrides[get_db]=db
    if authenticated:
        app.dependency_overrides[get_current_user]=lambda:principal(v,key,tenant)
    return TestClient(app)


def draft(v, **kw):
    return dict(operacao_id=str(uuid4()),id=str(uuid4()),versao_id=str(uuid4()),
                titulo='FAQ sintética',assunto='institucional',responsavel_id=str(v['uid']),
                conteudo='Orientação oficial sintética',origem='redacao_manual',**kw)


def create(c,v,**kw):
    p=draft(v,**kw); r=c.post('/conhecimento/documentos',json=p)
    assert r.status_code==200,r.text
    return p


def action(c,p,kind,**kw):
    return c.post(f"/conhecimento/documentos/{p['id']}/{kind}",json=dict(
        operacao_id=str(uuid4()),versao_id=p['versao_id'],**kw))


def edit(c,p,**kw):
    data=dict(operacao_id=str(uuid4()),versao_id=str(uuid4()),anterior_id=p['versao_id'],
        conteudo=p['conteudo'],origem=p['origem'],publicos=['institucional_publico'])
    data.update(kw)
    r=c.post(f"/conhecimento/documentos/{p['id']}/rascunhos",json=data)
    assert r.status_code==200,r.text
    return dict(p,**{k:v for k,v in data.items() if k!='anterior_id'})


def publish(c,p,expected=None):
    r=action(c,p,'enviar-revisao'); assert r.status_code==200,r.text
    r=action(c,p,'publicar',publicos=p.get('publicos',[]),vigente_esperada_id=expected)
    assert r.status_code==200,r.text
    return r


def test_complete_flow_immutable_edit_publication_revocation(database,seeded):
    v=seeded
    with client(database,v) as c:
        first=create(c,v)
        assert c.get('/conhecimento/versoes/'+first['versao_id']).status_code==200
        p=edit(c,first)
        with scoped(database,v['t']) as s:
            assert not pode_ler(s,Visitante(v['t']),p['versao_id'])
            original=s.execute(text('select conteudo,estado from conhecimento_versoes where id=:id'),dict(id=first['versao_id'])).one()
            assert original==(first['conteudo'],'substituida')
        publish(c,p)
        with scoped(database,v['t']) as s:
            assert pode_ler(s,Visitante(v['t']),p['versao_id'])
        replacement=edit(c,p,conteudo='Nova orientação')
        # Existing approved version stays current during replacement review.
        with scoped(database,v['t']) as s: assert pode_ler(s,Visitante(v['t']),p['versao_id'])
        assert action(c,replacement,'publicar',publicos=['institucional_publico'],vigente_esperada_id=p['versao_id']).status_code==409
        publish(c,replacement,p['versao_id'])
        with scoped(database,v['t']) as s:
            assert not pode_ler(s,Visitante(v['t']),p['versao_id'])
            assert pode_ler(s,Visitante(v['t']),replacement['versao_id'])
        assert action(c,replacement,'revogar').status_code==200
        with scoped(database,v['t']) as s:
            assert not pode_ler(s,Visitante(v['t']),replacement['versao_id'])
            assert s.execute(text('select vigente_id from conhecimento_documentos where id=:d'),dict(d=p['id'])).scalar() is None
        assert c.get('/conhecimento/versoes/'+replacement['versao_id']).status_code==404


@pytest.mark.parametrize('kind',['enviar-revisao','revisar','publicar','revogar','rascunhos'])
def test_roles_are_live_not_claims(database,seeded,kind):
    v=seeded
    with client(database,v) as c: p=create(c,v)
    with client(database,v,'leader') as c:
        if kind=='rascunhos':
            r=c.post(f"/conhecimento/documentos/{p['id']}/rascunhos",json=dict(operacao_id=str(uuid4()),versao_id=str(uuid4()),anterior_id=p['versao_id'],conteudo='X',origem='manual',publicos=[]))
        else:
            r=action(c,p,kind,**(dict(publicos=['institucional_publico'],vigente_esperada_id=None) if kind=='publicar' else {}))
        assert r.status_code==403,r.text
        assert c.post('/conhecimento/documentos',json=draft(v)).status_code==403


def test_pastor_only_reviews_assigned_area(database,seeded):
    v=seeded
    with database.begin() as s:
        s.execute(text("update user_roles set papel='pastor' where user_id=:u"),dict(u=v['leader']))
    with client(database,v) as c:
        p=create(c,v); p=edit(c,p); assert action(c,p,'enviar-revisao').status_code==200
        other=create(c,v); other=edit(c,other)
        assert action(c,other,'enviar-revisao').status_code==200
    with client(database,v,'leader') as c:
        assert action(c,p,'revisar').status_code==403
    with client(database,v) as c:
        data=draft(v); data['responsavel_id']=str(v['leader'])
        assert c.post('/conhecimento/documentos',json=data).status_code==200
        p=edit(c,data); assert action(c,p,'enviar-revisao').status_code==200
    with client(database,v,'leader') as c:
        assert action(c,p,'revisar').status_code==200
        assert action(c,p,'publicar',publicos=p['publicos'],vigente_esperada_id=None).status_code==403


def test_idempotency_replay_and_payload_conflicts(database,seeded):
    v=seeded
    with client(database,v) as c:
        p=create(c,v); path='/conhecimento/documentos'
        first=c.post(path,json=p)
        assert first.status_code==200
        assert c.post(path,json=dict(p,conteudo='Mudança')).status_code==409
        p=edit(c,p)
        q=dict(operacao_id=str(uuid4()),versao_id=p['versao_id'])
        path=f"/conhecimento/documentos/{p['id']}/enviar-revisao"
        r=c.post(path,json=q); assert r.status_code==200
        assert c.post(path,json=q).json()==r.json()
        pub=dict(operacao_id=str(uuid4()),versao_id=p['versao_id'],publicos=p['publicos'],vigente_esperada_id=None)
        path=f"/conhecimento/documentos/{p['id']}/publicar"
        published=c.post(path,json=pub); assert published.status_code==200
        assert action(c,p,'revogar').status_code==200
        assert c.post(path,json=pub).json()==published.json()
        with scoped(database,v['t']) as s: assert not pode_ler(s,Visitante(v['t']),p['versao_id'])
        assert c.post(path,json=dict(pub,publicos=['membros'])).status_code==409


def test_content_or_audience_changes_require_new_approval(database,seeded):
    v=seeded
    with client(database,v) as c:
        p=create(c,v); p=edit(c,p,publicos=['papel:admin']); publish(c,p)
        assert action(c,p,'publicar',publicos=['institucional_publico'],vigente_esperada_id=p['versao_id']).status_code==409
        new=edit(c,p,publicos=['institucional_publico'])
        assert action(c,new,'publicar',publicos=new['publicos'],vigente_esperada_id=p['versao_id']).status_code==409
        publish(c,new,p['versao_id'])


def test_idor_even_with_bypassrls_and_revoked_actor(database,seeded):
    v=seeded
    with client(database,v) as c: p=create(c,v)
    # Valid admin of B, not simply an invalid user/tenant pair.
    with database.begin() as s:
        s.execute(text("""insert into app_users(id,igreja_id,nome,email,status)
          values(:u,:t,'Outro','outro@example.test','ativo')"""),dict(u=v['other'],t=v['other']))
        s.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:t,:u,'admin')"),dict(u=v['other'],t=v['other']))
    with client(database,v,'other','other') as c:
        assert c.get('/conhecimento/versoes/'+p['versao_id']).status_code==404
        assert action(c,p,'revogar').status_code==404
        bad=draft(v); bad['responsavel_id']=str(v['uid'])
        assert c.post('/conhecimento/documentos',json=bad).status_code==422
    from sqlalchemy.orm import Session
    from app.services.conhecimento_editorial import executar
    from app.routers.conhecimento import AcaoInput
    from fastapi import HTTPException
    with Session(database) as s:
        with pytest.raises(HTTPException) as e:
            executar(s,principal(v,'other','other'),'revogar',p['id'],AcaoInput(operacao_id=uuid4(),versao_id=p['versao_id']))
        assert e.value.status_code==404
    with database.begin() as s:
        s.execute(text("update app_users set status='revogado' where id=:u"),dict(u=v['uid']))
    with client(database,v) as c:
        assert c.post('/conhecimento/documentos',json=draft(v)).status_code==403
        assert c.get('/conhecimento/versoes/'+p['versao_id']).status_code==404


def test_requires_web_authentication(database,seeded):
    with client(database,seeded,authenticated=False) as c:
        assert c.post('/conhecimento/documentos',json=draft(seeded)).status_code==401


def test_concurrent_same_operation_creates_one_snapshot(database,seeded):
    v=seeded; p=draft(v); barrier=Barrier(2)
    def attempt():
        with client(database,v) as c:
            barrier.wait(timeout=10)
            r=c.post('/conhecimento/documentos',json=p)
            return r.status_code,r.json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(attempt); b=pool.submit(attempt)
        assert a.result(timeout=20)==b.result(timeout=20)
        assert a.result()[0]==200
    with scoped(database,v['t']) as s:
        assert s.execute(text('select count(*) from conhecimento_versoes')).scalar()==1


def test_concurrent_stale_publication_and_edit_are_serialized(database,seeded):
    v=seeded
    with client(database,v) as c:
        p=create(c,v); p=edit(c,p); publish(c,p)
        new=edit(c,p); assert action(c,new,'enviar-revisao').status_code==200
    barrier=Barrier(2)
    def attempt(kind):
        with client(database,v) as c:
            barrier.wait(timeout=10)
            if kind=='publish': return action(c,new,'publicar',publicos=new['publicos'],vigente_esperada_id=None).status_code
            data=dict(operacao_id=str(uuid4()),versao_id=str(uuid4()),anterior_id=new['versao_id'],conteudo='Edição concorrente',origem='manual',publicos=['membros'])
            return c.post(f"/conhecimento/documentos/{p['id']}/rascunhos",json=data).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(attempt,'publish'); b=pool.submit(attempt,'edit')
        assert a.result(timeout=20)==409
        assert b.result(timeout=20)==200
    with scoped(database,v['t']) as s:
        assert s.execute(text("select count(*) from conhecimento_versoes where estado='publicada'")).scalar()==1
        assert pode_ler(s,Visitante(v['t']),p['versao_id'])


def test_revoked_document_can_receive_fresh_unapproved_replacement(database,seeded):
    v=seeded
    with client(database,v) as c:
        p=create(c,v); p=edit(c,p); publish(c,p)
        assert action(c,p,'revogar').status_code==200
        fresh=edit(c,p,conteudo='Correção após revogação')
        with scoped(database,v['t']) as s:
            assert not pode_ler(s,Visitante(v['t']),fresh['versao_id'])
        publish(c,fresh)


def test_two_distinct_publishers_cannot_both_win(database,seeded):
    v=seeded
    with client(database,v) as c:
        p=create(c,v); p=edit(c,p)
        assert action(c,p,'enviar-revisao').status_code==200
    barrier=Barrier(2)
    def attempt():
        with client(database,v) as c:
            barrier.wait(timeout=10)
            return action(c,p,'publicar',publicos=p['publicos'],vigente_esperada_id=None).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(attempt); b=pool.submit(attempt)
        assert sorted([a.result(timeout=20),b.result(timeout=20)])==[200,409]
    with scoped(database,v['t']) as s:
        assert s.execute(text("select count(*) from conhecimento_versoes where estado='publicada'")).scalar()==1


def test_legacy_responsible_and_strict_web_payload(database,seeded):
    v=seeded
    with database.begin() as s:
        s.execute(text('update app_users set status=null where id=:u'),dict(u=v['uid']))
    with client(database,v) as c:
        p=create(c,v)
        assert c.post('/conhecimento/documentos',json=dict(draft(v),igreja_id=str(v['other']))).status_code==422
        assert action(c,p,'publicar',publicos=['institucional_publico'],vigente_esperada_id=None).status_code==409
        assert action(c,p,'publicar',publicos=[],vigente_esperada_id=None).status_code==422


def test_pastor_can_propose_for_own_area_without_publishing(database,seeded):
    v=seeded
    with database.begin() as s:
        s.execute(text("update user_roles set papel='pastor' where user_id=:u"),dict(u=v['leader']))
    with client(database,v) as c:
        other=create(c,v)
    with client(database,v,'leader') as c:
        p=draft(v); p['responsavel_id']=str(v['leader'])
        response=c.post('/conhecimento/documentos',json=p)
        assert response.status_code==200,response.text
        p=edit(c,p)
        assert action(c,p,'enviar-revisao').status_code==200
        assert action(c,p,'revisar').status_code==200
        assert action(c,p,'publicar',publicos=p['publicos'],vigente_esperada_id=None).status_code==403
        assert action(c,p,'revogar').status_code==403
        assert action(c,other,'enviar-revisao').status_code==403
        assert c.post('/conhecimento/documentos',json=draft(v)).status_code==403
