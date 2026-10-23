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


def test_admin_request_list_reports_age_and_overdue_without_content(database, enabled):
    from app.services.private_erasure_requests import PRIVATE_ERASURE_SLA_DAYS_V1
    v = enabled
    prepare_request(database, v)
    row = request(database, v)
    with database.begin() as c:
        c.execute(text("update private_erasure_requests set created_at=now()-interval '16 days' where id=:id"),
                  dict(id=row['id']))
    with api(database, v) as client:
        response = client.get(f"/contacts/{v['person']}/private-erasure-requests")
        assert response.status_code == 200, response.text
        item = response.json()['items'][0]
        assert item['id'] == str(row['id'])
        assert item['idade_segundos'] >= 16 * 86400
        assert item['prazo_dias'] == PRIVATE_ERASURE_SLA_DAYS_V1 == 15
        assert item['prazo_versao'] == 'v1'
        assert item['vencido'] is True
        assert 'QUERO SOLICITAR' not in response.text
        assert 'telefone' not in response.text


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


@pytest.mark.parametrize('body', [
    '  quero solicitar exclusao do meu conteudo privado  ',
    'Quero   Solicitar\tExclusao do Meu Conteudo Privado',
])
def test_normalized_command_full_turn(database, channel, body):
    from app.workers.queue_worker import run_agent_for_message
    from tests.test_messages_inbound_idempotency import _ClassifiedEvolution
    with database.begin() as c:
        c.execute(text('update messages set texto=:body where id=:message'), dict(channel, body=body))
    transport = _ClassifiedEvolution()
    run_agent_for_message(lambda: Session(database), outcome(channel), evolution_client=transport)
    assert len(transport.calls) == 1
    assert 'pendente' in transport.calls[0][2]


def test_approved_inbound_replay_survives_deleted_identity(database, enabled):
    v = enabled
    prepare_request(database, v)
    row = request(database, v)
    with api(database, v) as client:
        result = client.post(f"/private-erasure-requests/{row['id']}/decision", json={
            'decision': 'aprovado', 'confirmacao': 'DECIDIR PEDIDO DE EXCLUSAO'})
        assert result.status_code == 200, result.text
    replay = request(database, v)
    assert replay['id'] == row['id']
    assert replay['state'] == 'aprovado'


def test_registration_denial_closes_reserved_reply(database, channel, monkeypatch):
    from app.workers.queue_worker import run_agent_for_message
    from tests.test_messages_inbound_idempotency import _ClassifiedEvolution
    from app.services import private_erasure_requests as service
    original = service.register

    def denied(db, **kwargs):
        # Exercise an actual SQL 42501 after contact validation/reservation.
        return original(db, **dict(kwargs, person=channel['person2']))

    monkeypatch.setattr(service, 'register', denied)
    transport = _ClassifiedEvolution()
    run_agent_for_message(lambda: Session(database), outcome(channel), evolution_client=transport)
    assert transport.calls == []
    with database.connect() as c:
        assert c.execute(text("select agent_reply_state,texto from messages where igreja_id=:tenant and direcao='out'"), channel).one() == ('ia_sem_resposta', None)
        assert c.scalar(text('select count(*) from private_erasure_requests where igreja_id=:tenant'), channel) == 0


@pytest.mark.parametrize('decisions', [('aprovado', 'aprovado'), ('aprovado', 'recusado')])
def test_two_admins_decide_concurrently(database, enabled, decisions):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    from app.services.private_erasure_requests import decide
    v = enabled
    prepare_request(database, v)
    row = request(database, v)
    second = uuid4()
    with database.begin() as c:
        c.execute(text("insert into app_users(id,igreja_id,nome,email,status,clerk_user_id) values(:u,:tenant,'Synthetic','admin2@example.test','ativo','erasure-admin2')"), dict(v,u=second))
        c.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:tenant,:u,'admin')"), dict(v,u=second))
    barrier = Barrier(2)

    def run(args):
        sub, decision = args
        with scoped(database, v['tenant']) as db:
            db.execute(text("select set_config('request.jwt.claims',:claims,true)"), dict(claims='{"sub":"'+sub+'"}'))
            barrier.wait(timeout=10)
            try:
                return decide(db, v['tenant'], row['id'], decision)['state']
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, zip(('deletion-admin', 'erasure-admin2'), decisions)))
    if decisions[0] == decisions[1]:
        assert results == ['aprovado', 'aprovado']
    else:
        assert results in (['aprovado', 409], [409, 'recusado'])
    with database.connect() as c:
        final = c.execute(text('select state,decided_by,receipt_id from private_erasure_requests where id=:id'), row).one()
        assert final.decided_by in (v['admin'], second)
        assert (final.receipt_id is not None) is (final.state == 'aprovado')
        assert c.scalar(text("select count(*) from private_deletion_receipts where igreja_id=:tenant and scope='pessoa'"),v) == int(final.state == 'aprovado')


def test_unauthorized_decision_does_not_wait_for_tenant_lock(database, enabled):
    from sqlalchemy.exc import DBAPIError
    v = enabled
    prepare_request(database, v)
    row = request(database, v)
    with database.begin() as holder:
        holder.execute(text("select pg_advisory_xact_lock(hashtextextended('private-content:'||cast(:t as text),0))"), dict(t=v['tenant']))
        with scoped(database, v['tenant']) as db:
            db.execute(text("set local lock_timeout='100ms'"))
            with pytest.raises(DBAPIError) as exc:
                db.execute(text("select private_erasure_decide(:r,'aprovado')"), dict(r=row['id']))
            assert exc.value.orig.pgcode == '42501'


def test_full_turn_leader_cannot_request_for_another_person(database, channel):
    from app.workers.queue_worker import run_agent_for_message
    from tests.test_messages_inbound_idempotency import _ClassifiedEvolution
    v = channel
    with database.begin() as c:
        c.execute(text('update app_users set pessoa_id=:person where id=:admin'), v)
        c.execute(text("update user_roles set papel='lider_celula' where user_id=:admin"), v)
        # Persisted conversation targets another person; leader role grants no override.
        c.execute(text('update conversations set pessoa_id=:person2 where id=:conv'), v)
    transport = _ClassifiedEvolution()
    run_agent_for_message(lambda: Session(database), outcome(v), evolution_client=transport)
    assert transport.calls == []
    with database.connect() as c:
        assert c.scalar(text('select count(*) from private_erasure_requests where igreja_id=:tenant'),v) == 0


@pytest.mark.parametrize('body', [
    'QUERO SOLICITAR EXCLUSAO DO CONTEUDO PRIVADO DE MARIA',
    'QUERO SOLICITAR EXCLUSAO DO MEU CONTEUDO PRIVADO E DO DISCIPULO',
    'EXCLUA MEU CONTEUDO PRIVADO', '', None,
])
def test_catalog_does_not_expand_the_target(rls_database_url, body):
    from app.private_erasure.catalog import route
    assert route(body) is False


@pytest.mark.parametrize('decision, status', [('aprovado', 200), ('recusado', 409)])
def test_manual_reset_settles_pending_request(database, enabled, decision, status):
    v = enabled
    generate(database, v)
    prepare_request(database, v)
    pending = request(database, v)
    with api(database, v) as client:
        reset = client.request('DELETE', f"/contacts/{v['person']}/private-content", json={
            'operation_id': str(uuid4()), 'confirmacao': 'EXCLUIR CONTEUDO PRIVADO'})
        assert reset.status_code == 200, reset.text
        assert reset.json()['camadas']['resumos']['apagadas'] == 1
        response = client.post(f"/private-erasure-requests/{pending['id']}/decision", json={
            'decision': decision, 'confirmacao': 'DECIDIR PEDIDO DE EXCLUSAO'})
        assert response.status_code == status, response.text
        if status == 200:
            assert response.json()['receipt'] == reset.json()
    with database.connect() as c:
        row = c.execute(text('select * from private_erasure_requests where id=:id'),
                        {'id': pending['id']}).mappings().one()
        assert row['state'] == 'aprovado'
        assert str(row['receipt_id']) == reset.json()['id']
        assert row['decided_by'] == v['admin']
        assert row['decided_at'] is not None
        assert c.scalar(text('select count(*) from private_deletion_receipts where igreja_id=:tenant'), v) == 1
        assert c.scalar(text('select count(*) from private_conversation_summaries where igreja_id=:tenant'), v) == 0


def test_old_manual_reset_replay_does_not_settle_new_request(database, enabled):
    v = enabled
    payload = {'operation_id': str(uuid4()), 'confirmacao': 'EXCLUIR CONTEUDO PRIVADO'}
    with api(database, v) as client:
        path = f"/contacts/{v['person']}/private-content"
        first = client.request('DELETE', path, json=payload)
        assert first.status_code == 200, first.text
        conv, inbound = uuid4(), uuid4()
        with database.begin() as c:
            c.execute(text("insert into conversations(id,igreja_id,pessoa_id,telefone,estado) values(:c,:tenant,:person,'550000000001','ia')"), dict(v, c=conv))
            c.execute(text("insert into messages(id,igreja_id,conversation_id,direcao,autor,texto) values(:m,:tenant,:c,'in','contato','QUERO SOLICITAR EXCLUSAO DO MEU CONTEUDO PRIVADO')"), dict(v, c=conv, m=inbound))
        pending = request(database, dict(v, conv=conv, message=inbound))
        replay = client.request('DELETE', path, json=payload)
        assert replay.status_code == 200, replay.text
        assert replay.json() == first.json()
        from app.services.private_erasure_requests import detail
        with scoped(database, v['tenant'], admin=True) as db:
            assert detail(db, v['tenant'], pending['id'])['state'] == 'pendente'
        with database.connect() as c:
            assert c.scalar(text('select count(*) from messages where id=:m'), {'m': inbound}) == 1
