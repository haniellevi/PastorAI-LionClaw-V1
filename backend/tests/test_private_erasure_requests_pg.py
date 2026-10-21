"""Requests use synthetic PG, real worker/catalog/router and authenticated API."""
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from tests.test_private_summaries_pg import ready, generate, get_summary  # noqa: F401
from tests.test_private_deletion_pg import private_data, scoped, api  # noqa: F401
from tests.test_uv_turmas_pg import migrated_database, database  # noqa: F401

pytestmark = pytest.mark.rls_integration


@pytest.fixture(scope='module')
def rls_database_url():
    import os
    from urllib.parse import urlsplit
    from tests.conftest_rls import assert_disposable_database
    url = os.environ.get('UV_TURMAS_DATABASE_URL', '').strip()
    if not url:
        pytest.fail('Pedido de exclusão exige PostgreSQL local sintético; nenhum skip permitido')
    assert_disposable_database(url)
    parsed = urlsplit(url)
    if parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.path != '/uv_turmas_test':
        pytest.fail('Use somente o banco local descartável uv_turmas_test')
    return url


@pytest.fixture
def enabled(database, ready, monkeypatch):
    from app.services import private_erasure_requests as service
    monkeypatch.setattr(service, 'APPROVED_RELEASE_ID', 'synthetic-only')
    monkeypatch.setattr(service, 'APPROVED_IGREJA_IDS', frozenset({str(ready['tenant'])}))
    with database.begin() as c:
        c.execute(text("update conversations set estado='ia' where igreja_id=:tenant"), ready)
        c.execute(text('insert into private_erasure_request_settings(igreja_id,enabled) values(:tenant,true)'), ready)
    return ready


def request(database, v):
    from app.services.private_erasure_requests import register
    with scoped(database, v['tenant']) as db:
        result = register(db, tenant=v['tenant'], person=v['person'], conversation=v['conv'], inbound=v['message'])
        db.commit()
        return result


def prepare_request(database, v):
    from app.services.private_erasure_requests import COMMAND
    with database.begin() as c:
        c.execute(text('update messages set texto=:body where id=:message'), dict(v, body=COMMAND))


def test_pending_refusal_restores_memory_and_approval_erases(database, enabled):
    v = enabled
    generate(database, v)
    original = get_summary(database, v)['summary']
    # Separate request conversation: the summary source remains operational.
    with database.begin() as c:
        request_conv, inbound = uuid4(), uuid4()
        c.execute(text("insert into conversations(id,igreja_id,pessoa_id,telefone,estado) values(:c,:tenant,:person,'550000000001','ia')"), dict(v,c=request_conv))
        c.execute(text("insert into messages(id,igreja_id,conversation_id,direcao,autor,texto) values(:m,:tenant,:c,'in','contato','QUERO SOLICITAR EXCLUSAO DO MEU CONTEUDO PRIVADO')"),dict(v,c=request_conv,m=inbound))
    req_v = dict(v, conv=request_conv, message=inbound)
    first = request(database, req_v)
    assert first == request(database, req_v)
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        get_summary(database, v)
    for admin in (True,False):
        with scoped(database,v['tenant'],admin=admin) as db:
            assert db.scalar(text('select count(*) from private_conversation_summaries'))==0
            assert db.scalar(text('select count(*) from private_summary_sources'))==0
    from app.services.private_summaries import enqueue
    with scoped(database,v['tenant']) as db:
        assert enqueue(db,v['tenant'],v['conv']) is None
    with api(database,v) as client:
        path = f"/private-erasure-requests/{first['id']}/decision"
        r = client.post(path,json={'decision':'recusado','confirmacao':'DECIDIR PEDIDO DE EXCLUSAO'})
        assert r.status_code == 200,r.text
        assert r.json()['state'] == 'recusado'
        assert client.post(path,json={'decision':'aprovado','confirmacao':'DECIDIR PEDIDO DE EXCLUSAO'}).status_code == 409
    assert get_summary(database,v)['summary'] == original
    # Replay cannot reopen a refused request. New inbound can.
    assert request(database,req_v)['state'] == 'recusado'
    with database.begin() as c:
        new_inbound=uuid4()
        c.execute(text("insert into messages(id,igreja_id,conversation_id,direcao,autor,texto) values(:m,:tenant,:c,'in','contato','QUERO SOLICITAR EXCLUSAO DO MEU CONTEUDO PRIVADO')"),dict(v,c=request_conv,m=new_inbound))
    second=request(database,dict(req_v,message=new_inbound))
    with api(database,v) as client:
        path=f"/private-erasure-requests/{second['id']}/decision"
        payload={'decision':'aprovado','confirmacao':'DECIDIR PEDIDO DE EXCLUSAO'}
        r=client.post(path,json=payload)
        assert r.status_code==200,r.text
        assert r.json()['receipt']['camadas']['resumos']['apagadas']==1
        assert r.json()==client.post(path,json=payload).json()
    with database.connect() as c:
        assert c.scalar(text('select count(*) from conversations where igreja_id=:tenant and pessoa_id=:person'),v)==0
        assert c.scalar(text('select count(*) from pessoas where id=:person'),v)==1
        assert c.scalar(text('select count(*) from conversations where igreja_id=:other'),v)==1


def test_default_closed_and_wrong_person(database, private_data):
    from fastapi import HTTPException
    from app.services.private_erasure_requests import register
    v=private_data
    with scoped(database,v['tenant']) as db,pytest.raises(HTTPException):
        register(db,tenant=v['tenant'],person=v['person'],conversation=v['conv'],inbound=v['message'])


def test_other_person_tenant_and_web_roles_denied(database, enabled):
    from fastapi import HTTPException
    from app.services.private_erasure_requests import register
    v=enabled
    prepare_request(database,v)
    for person in (v['person2'],v['person3']):
        with scoped(database,v['tenant']) as db,pytest.raises(HTTPException):
            register(db,tenant=v['tenant'],person=person,conversation=v['conv'],inbound=v['message'])
    row=request(database,v)
    for role in ('pastor','membro','operador'):
        with api(database,v,roles=(role,)) as client:
            r=client.post(f"/private-erasure-requests/{row['id']}/decision",json={'decision':'aprovado','confirmacao':'DECIDIR PEDIDO DE EXCLUSAO'})
            assert r.status_code==403
    with scoped(database,v['other']) as db:
        assert db.execute(text('select * from private_erasure_requests')).all()==[]
    from sqlalchemy.exc import DBAPIError
    with scoped(database,v['tenant']) as db,pytest.raises(DBAPIError):
        db.execute(text("update private_erasure_requests set state='aprovado'"))


@pytest.fixture
def channel(database, enabled, monkeypatch):
    from app.config import get_settings
    from app.db.models import AgentConfig, ConsentRecord, WhatsappConnection
    from app.services.llm import LLMClient
    import datetime as dt
    v=enabled
    monkeypatch.setenv('APP_ENV','test')
    monkeypatch.setenv('AGENT_TERM_VERSION','erasure-synthetic-v1')
    monkeypatch.setenv('WHATSAPP_PILOTO_IGREJA_IDS',str(v['tenant']))
    # Only fake transport is supplied. No real provider can be reached.
    monkeypatch.setenv('ALLOW_REAL_SENDS','true')
    get_settings.cache_clear()
    def forbidden(*a,**kw):
        raise AssertionError('unexpected external LLM')
    monkeypatch.setattr(LLMClient,'complete',forbidden)
    with Session(database) as db:
        db.add(AgentConfig(igreja_id=v['tenant'],comportamento='Synthetic',ativo=True))
        db.add(ConsentRecord(igreja_id=v['tenant'],pessoa_id=v['person'],termo_versao='erasure-synthetic-v1',aceite_em=dt.datetime.now(dt.UTC)))
        db.add(WhatsappConnection(igreja_id=v['tenant'],instance='erasure-synthetic'))
        db.commit()
    prepare_request(database,v)
    with database.begin() as c:
        c.execute(text("update messages set media_path=null,provider_message_id='erasure-inbound' where id=:message"),v)
    yield v
    get_settings.cache_clear()


def outcome(v):
    from tests.test_messages_inbound_idempotency import _agent_outcome
    return _agent_outcome(v['conv'],igreja_id=v['tenant'],inbound_message_id=v['message'],provider_message_id='erasure-inbound',instance='erasure-synthetic',telefone='550000000001')


def test_full_turn_commits_before_fake_delivery_and_replay(database, channel):
    from app.workers.queue_worker import run_agent_for_message
    from tests.test_messages_inbound_idempotency import _ClassifiedEvolution
    v=channel
    class Transport(_ClassifiedEvolution):
        def send_text_classificado(self,*args):
            with database.connect() as c:
                assert c.scalar(text("select count(*) from private_erasure_requests where igreja_id=:tenant and state='pendente'"),v)==1
                assert c.scalar(text("select count(*) from messages where igreja_id=:tenant and direcao='out' and agent_reply_state='ia_em_transporte'"),v)==1
            return super().send_text_classificado(*args)
    transport=Transport()
    run_agent_for_message(lambda:Session(database),outcome(v),evolution_client=transport)
    assert len(transport.calls)==1
    assert 'pendente' in transport.calls[0][2]
    run_agent_for_message(lambda:Session(database),outcome(v),evolution_client=transport)
    assert len(transport.calls)==1
    with database.connect() as c:
        row=c.execute(text("select agent_reply_state,agent_privilege_context from messages where igreja_id=:tenant and direcao='out'"),v).one()
        assert row[0]=='ia' and row[1]['kind']=='private_erasure'
        assert c.scalar(text('select count(*) from conversations where id=:conv'),v)==1


@pytest.mark.parametrize('denial',['flag','identity','optout'])
def test_full_turn_refuses_request_without_capability(database,channel,denial,monkeypatch):
    from app.workers.queue_worker import run_agent_for_message
    from tests.test_messages_inbound_idempotency import _ClassifiedEvolution
    v=channel
    with database.begin() as c:
        if denial=='flag':
            c.execute(text('update private_erasure_request_settings set enabled=false where igreja_id=:tenant'),v)
        elif denial=='identity':
            c.execute(text('update conversations set pessoa_id=:person2 where id=:conv'),v)
        elif denial=='optout':
            c.execute(text('update pessoas set optout=true where id=:person'),v)
    transport=_ClassifiedEvolution()
    run_agent_for_message(lambda:Session(database),outcome(v),evolution_client=transport)
    with database.connect() as c:
        assert c.scalar(text('select count(*) from private_erasure_requests where igreja_id=:tenant'),v)==0
        assert c.scalar(text("select count(*) from messages where igreja_id=:tenant and agent_privilege_context->>'kind'='private_erasure'"),v)==0


def test_request_during_provider_call_prevents_publication(database, enabled):
    from app.services.private_erasure_requests import COMMAND
    v=enabled
    # Request from another conversation while provider has no open transaction.
    def provider(**kw):
        c_id,m_id=uuid4(),uuid4()
        with database.begin() as c:
            c.execute(text("insert into conversations(id,igreja_id,pessoa_id,telefone,estado) values(:c,:tenant,:person,'550000000001','ia')"),dict(v,c=c_id))
            c.execute(text("insert into messages(id,igreja_id,conversation_id,direcao,autor,texto) values(:m,:tenant,:c,'in','contato',:body)"),dict(v,c=c_id,m=m_id,body=COMMAND))
        request(database,dict(v,conv=c_id,message=m_id))
        return {'topic':'uv'}
    generate(database,v,provider)
    with database.connect() as c:
        assert c.scalar(text('select count(*) from private_conversation_summaries where igreja_id=:tenant'),v)==0


def test_unreleased_channel_has_no_dependencies(rls_database_url):
    from app.private_erasure.turn import run_private_erasure_turn
    def forbidden(*a,**kw):
        raise AssertionError('unreleased request touched a dependency')
    assert run_private_erasure_turn(forbidden,forbidden,object(),igreja_id=uuid4(),
        uses_dedicated_agent_session=False,ownership_guard=forbidden,evolution_client=forbidden) is None


def test_concurrent_requests_coalesce_and_worker_cannot_decide(database, enabled):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.exc import DBAPIError
    v=enabled
    prepare_request(database,v)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows=list(pool.map(lambda _:request(database,v),range(2)))
    assert rows[0]['id']==rows[1]['id']
    with scoped(database,v['tenant']) as db,pytest.raises(DBAPIError):
        db.execute(text("select private_erasure_decide(:r,'aprovado')"),dict(r=rows[0]['id']))


def test_web_claim_is_not_authority_and_closed_admission_allows_decision(database, enabled):
    v=enabled
    prepare_request(database,v)
    row=request(database,v)
    with database.begin() as c:
        c.execute(text('update private_erasure_request_settings set enabled=false where igreja_id=:tenant'),v)
        c.execute(text('delete from user_roles where igreja_id=:tenant and user_id=:admin'),v)
    with api(database,v) as client:
        assert client.post(f"/private-erasure-requests/{row['id']}/decision",json={'decision':'aprovado','confirmacao':'DECIDIR PEDIDO DE EXCLUSAO'}).status_code==403
    with database.begin() as c:
        c.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:tenant,:admin,'admin')"),v)
    with api(database,v) as client:
        response=client.post(f"/private-erasure-requests/{row['id']}/decision",json={'decision':'recusado','confirmacao':'DECIDIR PEDIDO DE EXCLUSAO'})
        assert response.status_code==200,response.text


def test_coalesced_inbound_cannot_reopen_after_refusal(database, enabled):
    v=enabled
    prepare_request(database,v)
    first=request(database,v)
    mid=uuid4()
    with database.begin() as c:
        c.execute(text("insert into messages(id,igreja_id,conversation_id,direcao,autor,texto) select :m,igreja_id,conversation_id,direcao,autor,texto from messages where id=:message"),dict(v,m=mid))
    second_v=dict(v,message=mid)
    assert request(database,second_v)['id']==first['id']
    with api(database,v) as client:
        assert client.post(f"/private-erasure-requests/{first['id']}/decision",json={'decision':'recusado','confirmacao':'DECIDIR PEDIDO DE EXCLUSAO'}).status_code==200
    assert request(database,second_v)['state']=='recusado'


def test_approval_enqueues_retained_audio_and_preserves_consent(database, private_data, monkeypatch):
    from app.services import private_erasure_requests as service
    from app.db.models import ConsentRecord
    import datetime as dt
    v=private_data
    monkeypatch.setattr(service,'APPROVED_RELEASE_ID','synthetic-only')
    monkeypatch.setattr(service,'APPROVED_IGREJA_IDS',frozenset({str(v['tenant'])}))
    mid=uuid4()
    with database.begin() as c:
        c.execute(text('insert into private_erasure_request_settings(igreja_id,enabled) values(:tenant,true)'),v)
        c.execute(text("update pessoas set telefone='550000000001' where id=:person"),v)
        c.execute(text("update conversations set telefone='550000000001',estado='ia' where id=:conv"),v)
        c.execute(text("insert into messages(id,igreja_id,conversation_id,direcao,autor,texto) values(:m,:tenant,:conv,'in','contato',:body)"),dict(v,m=mid,body=service.COMMAND))
    with Session(database) as db:
        db.add(ConsentRecord(igreja_id=v['tenant'],pessoa_id=v['person'],termo_versao='synthetic-consent',aceite_em=dt.datetime.now(dt.UTC)))
        db.commit()
    row=request(database,dict(v,message=mid))
    with api(database,v) as client:
        listed=client.get(f"/contacts/{v['person']}/private-erasure-requests")
        assert listed.status_code==200
        assert listed.headers['cache-control']=='private, no-store'
        assert listed.json()['items'][0]['id']==str(row['id'])
        result=client.post(f"/private-erasure-requests/{row['id']}/decision",json={'decision':'aprovado','confirmacao':'DECIDIR PEDIDO DE EXCLUSAO'})
        assert result.status_code==200,result.text
        receipt=result.json()['receipt']
        assert receipt['estado']=='pendente'
        assert receipt['camadas']['transcricoes']['apagadas']==1
        assert receipt['camadas']['midias']['pendentes']==2
    from sqlalchemy import select,func
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(ConsentRecord).where(ConsentRecord.igreja_id==v['tenant'],ConsentRecord.pessoa_id==v['person']))==1
        assert db.scalar(text('select count(*) from cell_report_audio_inputs where igreja_id=:tenant'),v)==0
