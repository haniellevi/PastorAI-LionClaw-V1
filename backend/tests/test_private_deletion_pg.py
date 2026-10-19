"""Conversation privacy deletion on the complete active migration chain (PG17)."""
import datetime as dt
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.tenant_session import mark_tenant_scoped
from app.deps import CurrentUser, get_current_user
from app.routers.conversations import router
from app.services.storage import get_storage
from tests.test_uv_turmas_pg import rls_database_url, migrated_database, database  # noqa: F401

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def private_data(database):
    with database.begin() as c:
        c.exec_driver_sql('delete from private_deletion_tasks; delete from private_deletion_event_fences; '
                         'delete from private_deletion_uploads; delete from private_deletion_sends; delete from private_deletion_receipts')
    v = {k: uuid4() for k in ('tenant', 'other', 'person', 'person2', 'person3', 'admin', 'conv', 'conv2', 'conv3', 'message', 'audio')}
    with database.begin() as c:
        for tenant in (v['tenant'], v['other']):
            c.execute(text("insert into igrejas(id,nome) values(:id,'Synthetic')"), dict(id=tenant))
        for person, tenant in ((v['person'], v['tenant']), (v['person2'], v['tenant']), (v['person3'], v['other'])):
            c.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:id,:tenant,'Synthetic',:phone)"), dict(id=person, tenant=tenant, phone=str(person.int)[-12:]))
        c.execute(text("insert into app_users(id,igreja_id,nome,email,status,clerk_user_id) values(:admin,:tenant,'Synthetic','synthetic@example.invalid','ativo','deletion-admin')"), v)
        c.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:tenant,:admin,'admin')"), v)
        for conv, person, tenant in ((v['conv'],v['person'],v['tenant']), (v['conv2'],v['person2'],v['tenant']), (v['conv3'],v['person3'],v['other'])):
            c.execute(text("insert into conversations(id,igreja_id,pessoa_id,telefone) values(:id,:tenant,:person,'000000000000')"), dict(id=conv, tenant=tenant, person=person))
            c.execute(text("insert into messages(id,igreja_id,conversation_id,direcao,autor,texto,media_path) values(:id,:tenant,:conv,'in','contato','Synthetic private text',:path)"), dict(id=v['message'] if conv == v['conv'] else uuid4(), tenant=tenant, conv=conv, path=f'{tenant}/{conv}/synthetic.png'))
        c.execute(text("""insert into cell_report_audio_inputs
            (id,igreja_id,conversation_id,pessoa_id,inbound_message_id,live_conversation_id,live_pessoa_id,live_message_id,
             provider_message_sha256,storage_path,state,transcription_attempts,purge_state,purge_attempts,
             transcript_text,transcript_sha256,content_sha256,received_at,expires_at,updated_at)
            values(:audio,:tenant,:conv,:person,:message,NULL,:person,NULL,repeat('a',64),
            :path,'processando',1,'ativa',0,'Synthetic transcript',repeat('b',64),repeat('c',64),now(),now()+interval '24 hours',now())"""), dict(v, path=f"{v['tenant']}/cell-report-audio/synthetic.ogg"))
    return v


def scoped(engine, tenant, *, admin=False):
    s = Session(engine)
    mark_tenant_scoped(s, tenant, source='private_deletion_test')
    if admin:
        s.execute(text("select set_config('request.jwt.claims', '{\"sub\":\"deletion-admin\"}', true)"))
    return s


def api(engine, v, roles=('admin',)):
    app = FastAPI(); app.include_router(router)
    def db():
        with scoped(engine, v['tenant'], admin=True) as s:
            yield s
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        app_user_id=str(v['admin']), igreja_id=str(v['tenant']), clerk_user_id='deletion-admin',
        nome='Synthetic', email='synthetic@example.invalid', roles=frozenset(roles))
    app.dependency_overrides[get_storage] = lambda: SimpleNamespace(remove=lambda paths: None)
    return TestClient(app)


def test_delete_returns_durable_receipt_instead_of_losing_storage_failures(database, private_data):
    v = private_data
    with api(database, v) as client:
        response = client.delete(f"/conversations/{v['conv']}")
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt['estado'] == 'pendente'
        assert receipt['camadas']['mensagens'] == dict(encontradas=1, apagadas=1, pendentes=0, falhas=0)
        assert receipt['camadas']['midias'] == dict(encontradas=2, apagadas=0, pendentes=2, falhas=0)
        assert receipt['camadas']['transcricoes']['apagadas'] == 1
        for layer in ('resumos', 'checkpoints', 'vetores'):
            assert receipt['camadas'][layer] == dict(encontradas=0, apagadas=0, pendentes=0, falhas=0)
        assert client.delete(f"/conversations/{v['conv']}").json() == receipt
        assert client.delete(f"/conversations/{v['conv3']}").status_code == 404
    serialized = json.dumps(receipt)
    for secret in ('Synthetic', '000000', 'aaaaaa', 'bbbbbb', 'cccccc', 'storage', '.ogg', 'telefone', 'transcript'):
        assert secret not in serialized
    with database.connect() as c:
        assert c.execute(text('select count(*) from messages')).scalar_one() == 2
        assert c.execute(text('select count(*) from conversations')).scalar_one() == 2
        assert c.execute(text('select count(*) from cell_report_audio_inputs')).scalar_one() == 0


@pytest.mark.parametrize('role', ['pastor', 'operador', 'lider_celula', 'membro'])
def test_non_admin_refused(database, private_data, role):
    v = private_data
    with api(database, v, (role,)) as client:
        assert client.delete(f"/conversations/{v['conv']}").status_code == 403


def claim(v):
    from app.services.cell_report_audio_service import AudioInputClaim
    return AudioInputClaim(igreja_id=v['tenant'], input_id=v['audio'], conversation_id=v['conv'],
        pessoa_id=v['person'], inbound_message_id=v['message'], provider_message_id='synthetic',
        instance='synthetic', phone='000000000000', declared_mime='audio/ogg', provider_message_sha256='a'*64,
        lease_token=uuid4(), lease_until=dt.datetime.now(dt.UTC)+dt.timedelta(minutes=5),
        credential_provider='openai', credential_key_encrypted='synthetic', credential_model='synthetic',
        storage_path=f"{v['tenant']}/cell-report-audio/synthetic.ogg")


def test_storage_failure_retry_and_late_upload_reopen(database, private_data):
    from app.services.private_deletion import process_storage_tasks
    from app.services.cell_report_audio_service import _reopen_audio_purge_after_late_upload
    v=private_data
    with api(database,v) as client:
        initial=client.delete(f"/conversations/{v['conv']}").json()
    factory=lambda: Session(database)
    class Storage:
        failing=True
        calls=[]
        def remove_tenant_media(self, tenant, paths):
            assert tenant==v['tenant']
            self.calls.extend(paths)
            if self.failing:
                raise RuntimeError('Synthetic storage unavailable')
    storage=Storage(); now=dt.datetime.now(dt.UTC)
    assert process_storage_tasks(factory,storage=storage,now=now)==0
    with api(database,v) as client:
        failed=client.get(f"/conversations/{v['conv']}/deletion-receipt").json()
    assert failed['camadas']['midias']['pendentes']==2
    assert failed['camadas']['midias']['falhas']==2
    assert failed['estado']=='pendente'
    storage.failing=False
    assert process_storage_tasks(factory,storage=storage,now=now)==0  # backoff
    assert process_storage_tasks(factory,storage=storage,now=now+dt.timedelta(hours=1))==2
    with api(database,v) as client:
        complete=client.get(f"/conversations/{v['conv']}/deletion-receipt").json()
    assert complete['estado']=='concluido'
    assert complete['id']==initial['id']
    assert complete['camadas']['midias']==dict(encontradas=2,apagadas=2,pendentes=0,falhas=0)
    _reopen_audio_purge_after_late_upload(factory, claim(v))
    with api(database,v) as client:
        reopened=client.get(f"/conversations/{v['conv']}/deletion-receipt").json()
    assert reopened['estado']=='pendente'
    assert reopened['camadas']['midias']['pendentes']==1
    assert process_storage_tasks(factory,storage=storage,now=now+dt.timedelta(hours=2))==1
    assert process_storage_tasks(factory,storage=storage,now=now+dt.timedelta(hours=3))==0
    with database.connect() as c:
        assert c.execute(text('select count(*) from private_deletion_tasks where receipt_id=:r and storage_path is not null'),dict(r=initial['id'])).scalar_one()==0


def test_late_transcript_and_message_cannot_repopulate(database, private_data, monkeypatch):
    from app.services.cell_report_audio_service import _stage_audio_transcript
    from app.services import cell_report_audio_service as audio
    from app.services.private_deletion import lock_generation
    from app.workers.queue_worker import _prepare_agent_reply_intent, IngestionOutcome, IngestionResult
    v=private_data
    with api(database,v) as client:
        assert client.delete(f"/conversations/{v['conv']}").status_code==200
    # The fake provider can return, but real DB ownership and generation must deny persistence.
    monkeypatch.setattr(audio,'cell_report_audio_enabled_from_environment',lambda tenant: True)
    factory=lambda: Session(database)
    assert _stage_audio_transcript(factory,claim(v),transcript='Late synthetic',measured_mime='audio/ogg',
        byte_size=20,duration_seconds=1,content_sha256='d'*64) is None
    with scoped(database,v['tenant']) as s:
        assert not lock_generation(s,v['tenant'],v['conv'],0)
    outcome=IngestionOutcome(result=IngestionResult.REGISTERED,conversation_id=v['conv'],
        instance='synthetic',telefone='000000000000',texto='synthetic',inbound=True,
        igreja_id=v['tenant'],inbound_message_id=v['message'],provider_message_id='synthetic')
    assert _prepare_agent_reply_intent(factory,outcome,'Late synthetic',public_info_reply=False) is None
    with database.connect() as c:
        assert c.execute(text('select count(*) from messages where conversation_id=:id'),dict(id=v['conv'])).scalar_one()==0
        assert c.execute(text('select count(*) from cell_report_audio_inputs')).scalar_one()==0


def test_replay_of_deleted_provider_event_does_not_create_new_conversation(database, private_data):
    from app.domain.conversations import ParsedMessage
    from app.domain.phone import normalize_phone
    from app.workers.queue_worker import ingest_message_event_ex, IngestionResult
    v=private_data
    with database.begin() as c:
        c.execute(text("update pessoas set telefone='550000000001' where id=:person"),v)
        c.execute(text("update messages set provider_message_id='synthetic-deleted-event' where id=:message"),v)
        c.execute(text("insert into whatsapp_connections(igreja_id,instance) values(:tenant,'private-replay')"),v)
    with api(database,v) as client:
        assert client.delete(f"/conversations/{v['conv']}").status_code==200
    parsed=ParsedMessage(instance='private-replay', provider_message_id='synthetic-deleted-event',
        telefone=normalize_phone('550000000001'),telefone_raw='550000000001',texto='Old synthetic',push_name=None,from_me=False)
    with Session(database) as s:
        outcome=ingest_message_event_ex(s,parsed)
        assert outcome.result==IngestionResult.IGNORED
    with database.connect() as c:
        assert c.execute(text('select count(*) from conversations where pessoa_id=:person'),v).scalar_one()==0


def test_inflight_upload_prevents_false_completion_even_when_finalize_database_fails(database, private_data):
    from app.services.private_deletion import begin_audio_upload, finish_audio_upload, process_storage_tasks
    v=private_data; factory=lambda: Session(database)
    assert begin_audio_upload(factory,claim(v))
    with api(database,v) as client:
        assert client.delete(f"/conversations/{v['conv']}").status_code==200
    def unavailable():
        raise RuntimeError('Synthetic DB unavailable')
    with pytest.raises(RuntimeError):
        finish_audio_upload(unavailable,claim(v))
    storage=SimpleNamespace(remove_tenant_media=lambda tenant,paths: None)
    assert process_storage_tasks(factory,storage=storage,now=dt.datetime.now(dt.UTC)+dt.timedelta(days=2))==1
    with api(database,v) as client:
        assert client.get(f"/conversations/{v['conv']}/deletion-receipt").json()['estado']=='pendente'
    finish_audio_upload(factory,claim(v))
    assert process_storage_tasks(factory,storage=storage,now=dt.datetime.now(dt.UTC)+dt.timedelta(days=3))==1


def test_generation_change_rejects_live_audio_claim(database, private_data, monkeypatch):
    from app.services import cell_report_audio_service as audio
    from app.services.private_deletion import lock_generation
    v=private_data
    with database.begin() as c:
        c.execute(text('update conversations set deletion_generation=1 where id=:conv'),v)
        c.execute(text('update cell_report_audio_inputs set live_conversation_id=:conv,live_message_id=:message where id=:audio'),v)
    monkeypatch.setattr(audio,'cell_report_audio_enabled_from_environment',lambda tenant: True)
    with scoped(database,v['tenant']) as s:
        assert audio._lock_audio_claim_context(s,claim(v),now=dt.datetime.now(dt.UTC)) is None
        assert not lock_generation(s,v['tenant'],v['conv'],0)
        assert lock_generation(s,v['tenant'],v['conv'],1)


def test_real_ingestion_upload_serializes_with_deletion(database, private_data):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.domain.conversations import ParsedMessage
    from app.domain.phone import normalize_phone
    from app.workers.queue_worker import ingest_message_event_ex, IngestionResult
    v=private_data
    with database.begin() as c:
        c.execute(text("update pessoas set telefone='550000000001' where id=:person"),v)
        c.execute(text("insert into whatsapp_connections(igreja_id,instance) values(:tenant,'private-upload')"),v)
    entered=Event(); release=Event(); deleting=Event()
    path=f"{v['tenant']}/{v['conv']}/late.png"
    def resolver(*args):
        entered.set()
        assert release.wait(10)
        return SimpleNamespace(path=path,mime='image/png',nome='synthetic.png',tamanho=4)
    parsed=ParsedMessage(instance='private-upload',provider_message_id='synthetic-upload',
        telefone=normalize_phone('550000000001'),telefone_raw='550000000001',texto=None,
        push_name=None,from_me=False,media_kind='imagem',media_mime='image/png')
    def ingest():
        with Session(database) as s:
            return ingest_message_event_ex(s,parsed,media_resolver=resolver)
    def delete():
        deleting.set()
        with api(database,v) as client:
            return client.delete(f"/conversations/{v['conv']}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        uploaded=pool.submit(ingest)
        assert entered.wait(10)
        deleted=pool.submit(delete)
        assert deleting.wait(5)
        try:
            # Deletion must wait for the existing locked writer to commit.
            assert not deleted.done()
        finally:
            release.set()
        assert uploaded.result(timeout=10).result==IngestionResult.REGISTERED
        result=deleted.result(timeout=10)
        assert result.status_code==200, result.text
        assert result.json()['camadas']['mensagens']['apagadas']==2
        assert result.json()['camadas']['midias']['pendentes']==3
    with database.connect() as c:
        assert c.execute(text('select count(*) from messages where conversation_id=:conv'),v).scalar_one()==0


def test_receipt_tasks_survive_source_tenant_and_obey_real_rls(database, private_data):
    from sqlalchemy.exc import DBAPIError
    from app.services.private_deletion import process_storage_tasks
    v=private_data
    with api(database,v) as client:
        deleted=client.delete(f"/conversations/{v['conv']}").json()
    tables=('private_deletion_receipts','private_deletion_tasks','private_deletion_uploads','private_deletion_event_fences','private_deletion_sends')
    with database.connect() as c:
        for table in tables:
            assert c.execute(text("select relrowsecurity and relforcerowsecurity from pg_class where oid=cast(:t as regclass)"),dict(t=table)).scalar_one()
            for role in ('anon','service_role'):
                assert not c.execute(text("select has_table_privilege(:r,:t,'SELECT')"),dict(r=role,t=table)).scalar_one()
    with scoped(database,v['other']) as s:
        for table in tables:
            assert s.execute(text(f'select count(*) from {table}')).scalar_one()==0
        assert s.execute(text('select private_deletion_task_path(:id)'),dict(id=uuid4())).scalar_one() is None
        with pytest.raises(DBAPIError):
            s.execute(text('select private_delete_conversation(:t,:c)'),dict(t=v['tenant'],c=v['conv2']))
        s.rollback()
    with scoped(database,v['tenant'],admin=True) as s:
        with pytest.raises(DBAPIError):
            s.execute(text('select private_deletion_task_path(:id)'),dict(id=uuid4()))
        s.rollback()
    with database.begin() as c:
        c.execute(text('delete from igrejas where id=:tenant'),v)
    assert process_storage_tasks(lambda: Session(database),storage=SimpleNamespace(remove_tenant_media=lambda tenant,paths: None))==2
    with database.connect() as c:
        assert c.execute(text('select count(*) from private_deletion_receipts where id=:id'),dict(id=deleted['id'])).scalar_one()==1


def test_deleted_event_caught_when_deletion_commits_between_fence_and_conversation_lookup(database, private_data, monkeypatch):
    from app.services import private_deletion as privacy
    from app.domain.conversations import ParsedMessage
    from app.domain.phone import normalize_phone
    from app.workers.queue_worker import ingest_message_event_ex, IngestionResult
    v=private_data
    with database.begin() as c:
        c.execute(text("update pessoas set telefone='550000000001' where id=:person"),v)
        c.execute(text("update cell_report_audio_inputs set provider_message_sha256=encode(digest('synthetic-racing-event','sha256'),'hex') where id=:audio"),v)
        c.execute(text("insert into whatsapp_connections(igreja_id,instance) values(:tenant,'private-race')"),v)
    original=privacy.event_was_deleted; calls=[]
    def interleave(db, tenant, event):
        result=original(db,tenant,event)
        if not calls:
            calls.append(True)
            with api(database,v) as client:
                assert client.delete(f"/conversations/{v['conv']}").status_code==200
        return result
    monkeypatch.setattr(privacy,'event_was_deleted',interleave)
    parsed=ParsedMessage(instance='private-race',provider_message_id='synthetic-racing-event',
        telefone=normalize_phone('550000000001'),telefone_raw='550000000001',texto='synthetic',push_name=None,from_me=False)
    with Session(database) as s:
        assert ingest_message_event_ex(s,parsed).result==IngestionResult.IGNORED


def test_lost_upload_cannot_starve_later_cleanup(database, private_data):
    from app.services.private_deletion import begin_audio_upload, process_storage_tasks
    v=private_data; factory=lambda: Session(database)
    assert begin_audio_upload(factory,claim(v))
    with api(database,v) as client:
        assert client.delete(f"/conversations/{v['conv']}").status_code==200
    with database.begin() as c:
        c.execute(text("update private_deletion_tasks set next_attempt_at=now()-interval '2 days' where source_id=:audio"),v)
    assert process_storage_tasks(factory,storage=SimpleNamespace(remove_tenant_media=lambda tenant,paths: None),limit=1)==1


def test_audio_derivatives_of_other_people_and_church_are_untouched(database, private_data):
    v=private_data
    others=[]
    with database.begin() as c:
        for conv,person,tenant,digest in ((v['conv2'],v['person2'],v['tenant'],'d'),
                                          (v['conv3'],v['person3'],v['other'],'e')):
            audio_id=uuid4(); others.append(audio_id)
            c.execute(text("""insert into cell_report_audio_inputs
                (id,igreja_id,conversation_id,pessoa_id,inbound_message_id,provider_message_sha256,storage_path,
                 state,transcription_attempts,purge_state,purge_attempts,transcript_text,transcript_sha256,
                 content_sha256,received_at,expires_at,updated_at)
                select :id,:tenant,:conv,:person,m.id,repeat(:digest,64),:path,'transcrita',1,'ativa',0,
                 'Synthetic unrelated',repeat(:digest,64),repeat(:digest,64),now(),now()+interval '24 hours',now()
                from messages m where m.igreja_id=:tenant and m.conversation_id=:conv limit 1"""),
                dict(id=audio_id,tenant=tenant,conv=conv,person=person,digest=digest,
                     path=f'{tenant}/cell-report-audio/unrelated.ogg'))
        before=c.execute(text('select id,transcript_text,transcript_sha256,content_sha256,storage_path from cell_report_audio_inputs where id in (:a,:b) order by id'),dict(a=others[0],b=others[1])).all()
    with api(database,v) as client:
        assert client.delete(f"/conversations/{v['conv']}").status_code==200
    with database.connect() as c:
        after=c.execute(text('select id,transcript_text,transcript_sha256,content_sha256,storage_path from cell_report_audio_inputs where id in (:a,:b) order by id'),dict(a=others[0],b=others[1])).all()
    assert after==before


def test_delete_erases_linked_audit_payload_and_preserves_unrelated_logs(database, private_data):
    v = private_data
    with database.begin() as c:
        for conv, tenant in ((v['conv'], v['tenant']), (v['conv2'], v['tenant']), (v['conv3'], v['other'])):
            c.execute(text("""insert into agent_conversation_logs(igreja_id,conversation_id,evento,payload)
                values(:t,:c,'synthetic',:payload)"""),
                dict(t=tenant, c=conv, payload=json.dumps({'pessoaId': str(v['person']), 'report': 'Synthetic private'})))
    with api(database, v) as client:
        result = client.delete(f"/conversations/{v['conv']}").json()
    assert result['camadas']['logs_agente'] == dict(encontradas=1, apagadas=1, pendentes=0, falhas=0)
    with database.connect() as c:
        assert c.execute(text('select count(*) from agent_conversation_logs')).scalar_one() == 2
        assert c.execute(text('select count(*) from agent_conversation_logs where conversation_id is null')).scalar_one() == 0


@pytest.mark.parametrize('status', ['aceito', 'falhou_retentavel', 'desconhecido'])
def test_deletion_during_agent_transport_waits_for_boundary_without_resend(database, private_data, status):
    from app.workers.queue_worker import (
        _prepare_agent_reply_intent, _deliver_agent_reply_intent, IngestionOutcome, IngestionResult,
    )
    from app.services.private_deletion import process_storage_tasks
    v = private_data
    factory = lambda: Session(database)
    outcome = IngestionOutcome(result=IngestionResult.REGISTERED, conversation_id=v['conv'],
        instance='synthetic', telefone='000000000000', texto='synthetic', inbound=True,
        igreja_id=v['tenant'], inbound_message_id=v['message'], provider_message_id='synthetic-send', claim_id='synthetic-claim')
    intent = _prepare_agent_reply_intent(factory, outcome, 'Synthetic reply', public_info_reply=False)
    assert intent is not None
    calls = []; observed = []
    class Transport:
        def send_text_classificado(self, *args):
            calls.append(True)
            with api(database, v) as client:
                deleted = client.delete(f"/conversations/{v['conv']}").json()
                observed.append(deleted)
            process_storage_tasks(factory, storage=SimpleNamespace(remove_tenant_media=lambda *args: None))
            with api(database, v) as client:
                observed.append(client.get(f"/conversations/{v['conv']}/deletion-receipt").json())
            return SimpleNamespace(status=status)
    _deliver_agent_reply_intent(factory, outcome, intent, None, evolution_client=Transport())
    _deliver_agent_reply_intent(factory, outcome, intent, None, evolution_client=Transport())
    assert len(calls) == 1
    assert [r['estado'] for r in observed] == ['pendente_envio', 'pendente_envio']
    assert all(r['camadas']['envios']['pendentes'] == 1 for r in observed)
    with api(database, v) as client:
        result = client.get(f"/conversations/{v['conv']}/deletion-receipt").json()
        assert result['estado'] == 'concluido'
        assert result['camadas']['envios']['pendentes'] == 0
    with database.connect() as c:
        assert c.execute(text('select count(*) from messages where conversation_id=:conv'), v).scalar_one() == 0
        assert c.execute(text('select count(*) from agent_conversation_logs where conversation_id=:conv'), v).scalar_one() == 0


def test_deletion_after_final_probe_before_http_is_still_pending(database, private_data, monkeypatch):
    from app.workers import queue_worker as worker
    v = private_data; factory = lambda: Session(database)
    outcome = worker.IngestionOutcome(result=worker.IngestionResult.REGISTERED, conversation_id=v['conv'],
        instance='synthetic', telefone='000000000000', texto='synthetic', inbound=True,
        igreja_id=v['tenant'], inbound_message_id=v['message'], provider_message_id='synthetic-gap', claim_id='synthetic-gap')
    intent = worker._prepare_agent_reply_intent(factory, outcome, 'Synthetic reply', public_info_reply=False)
    observed = []; calls = []
    def interleave(client, instance, phone, response, *, ownership_guard, before_transport):
        assert before_transport()
        with api(database, v) as client_api:
            observed.append(client_api.delete(f"/conversations/{v['conv']}").json())
        # Exact old gap: deletion commits after the final short lock, before HTTP.
        calls.append(True)
        return 'aceito'
    monkeypatch.setattr(worker, '_send_agent_reply', interleave)
    worker._deliver_agent_reply_intent(factory, outcome, intent, None, evolution_client=object())
    assert calls == [True]
    assert observed[0]['estado'] == 'pendente_envio'
    with api(database, v) as client:
        assert client.get(f"/conversations/{v['conv']}/deletion-receipt").json()['estado'] == 'pendente'
    with database.connect() as c:
        assert c.execute(text('select count(*) from messages where conversation_id=:conv'), v).scalar_one() == 0


def test_send_generation_change_prevents_transport_and_post_send_writes(database, private_data, monkeypatch):
    from app.workers import queue_worker as worker
    v = private_data; factory = lambda: Session(database)
    outcome = worker.IngestionOutcome(result=worker.IngestionResult.REGISTERED, conversation_id=v['conv'],
        instance='synthetic', telefone='000000000000', texto='synthetic', inbound=True,
        igreja_id=v['tenant'], inbound_message_id=v['message'], provider_message_id='synthetic-generation', claim_id='synthetic-generation')
    intent = worker._prepare_agent_reply_intent(factory, outcome, 'Synthetic reply', public_info_reply=False)
    observed = []
    class Transport:
        def send_agent_text(self, *args, before_send):
            with database.begin() as c:
                c.execute(text('update conversations set deletion_generation=deletion_generation+1 where id=:conv'), v)
            # The real final generation check must suppress this call.
            before_send()
            observed.append(True)
            return SimpleNamespace(status='aceito')
    worker._deliver_agent_reply_intent(factory, outcome, intent, None, evolution_client=Transport())
    assert observed == []
    with database.connect() as c:
        assert c.execute(text('select agent_reply_state from messages where id=:id'), dict(id=intent.id)).scalar_one() == 'ia_em_transporte'
        assert c.execute(text('select ultima_mensagem from conversations where id=:conv'), v).scalar_one() is None


def test_send_marker_admin_read_only_and_worker_tenant_isolation(database, private_data):
    from sqlalchemy.exc import DBAPIError
    v = private_data
    with scoped(database, v['tenant']) as s:
        s.execute(text('insert into private_deletion_sends(igreja_id,source_id,conversation_id,generation) values(:tenant,:message,:conv,0)'), v)
        s.commit()
    with scoped(database, v['other']) as s:
        assert s.execute(text('select count(*) from private_deletion_sends')).scalar_one() == 0
        with pytest.raises(DBAPIError):
            s.execute(text('insert into private_deletion_sends(igreja_id,source_id,conversation_id,generation) values(:tenant,:audio,:conv,0)'), v)
        s.rollback()
    with scoped(database, v['tenant'], admin=True) as s:
        assert s.execute(text('select count(*) from private_deletion_sends')).scalar_one() == 1
        assert s.execute(text('delete from private_deletion_sends')).rowcount == 0
        with pytest.raises(DBAPIError):
            s.execute(text('insert into private_deletion_sends(igreja_id,source_id,conversation_id,generation) values(:tenant,:audio,:conv,0)'), v)
        s.rollback()


def test_lost_send_expires_without_reopening_transport(database, private_data):
    from app.workers import queue_worker as worker
    v = private_data; factory = lambda: Session(database)
    outcome = worker.IngestionOutcome(result=worker.IngestionResult.REGISTERED, conversation_id=v['conv'],
        instance='synthetic', telefone='000000000000', texto='synthetic', inbound=True,
        igreja_id=v['tenant'], inbound_message_id=v['message'], provider_message_id='synthetic-lost', claim_id='synthetic-lost')
    intent = worker._prepare_agent_reply_intent(factory, outcome, 'Synthetic reply', public_info_reply=False)
    assert worker._transition_agent_reply_intent(factory, outcome, intent, expected='ia_pendente', target='ia_em_transporte')
    with api(database, v) as client:
        assert client.delete(f"/conversations/{v['conv']}").json()['estado'] == 'pendente_envio'
    with database.begin() as c:
        c.execute(text("update private_deletion_sends set expires_at=clock_timestamp()-interval '1 second' where igreja_id=:tenant"), v)
        c.execute(text("update private_deletion_tasks set state='concluida',storage_path=null where igreja_id=:tenant"), v)
    with api(database, v) as client:
        result = client.get(f"/conversations/{v['conv']}/deletion-receipt").json()
        assert result['estado'] == 'concluido'
        assert result['camadas']['envios']['pendentes'] == 0
    calls = []
    worker._deliver_agent_reply_intent(factory, outcome, intent, None,
        evolution_client=SimpleNamespace(send_text=lambda *args: calls.append(True)))
    assert calls == []


def test_generation_changed_during_http_does_not_confirm_or_refresh_snapshot(database, private_data):
    from app.workers import queue_worker as worker
    v = private_data; factory = lambda: Session(database)
    outcome = worker.IngestionOutcome(result=worker.IngestionResult.REGISTERED, conversation_id=v['conv'],
        instance='synthetic', telefone='000000000000', texto='synthetic', inbound=True,
        igreja_id=v['tenant'], inbound_message_id=v['message'], provider_message_id='synthetic-late-generation', claim_id='synthetic-late-generation')
    intent = worker._prepare_agent_reply_intent(factory, outcome, 'Synthetic reply', public_info_reply=False)
    calls = []
    class Transport:
        def send_text(self, *args):
            calls.append(True)
            with database.begin() as c:
                c.execute(text('update conversations set deletion_generation=deletion_generation+1 where id=:conv'), v)
            return True
    worker._deliver_agent_reply_intent(factory, outcome, intent, None, evolution_client=Transport())
    worker._deliver_agent_reply_intent(factory, outcome, intent, None, evolution_client=Transport())
    assert calls == [True]
    with database.connect() as c:
        assert c.execute(text('select agent_reply_state from messages where id=:id'), dict(id=intent.id)).scalar_one() == 'ia_em_transporte'
        assert c.execute(text('select ultima_mensagem from conversations where id=:conv'), v).scalar_one() is None


def test_preflight_renews_full_window_and_rejects_expired_owner(database, private_data):
    from app.services.private_deletion import renew_agent_send, lock_generation
    v = private_data
    with database.begin() as c:
        c.execute(text("""insert into private_deletion_sends(igreja_id,source_id,conversation_id,generation,expires_at)
            values(:tenant,:message,:conv,0,clock_timestamp()+interval '1 second')"""), v)
    with scoped(database, v['tenant']) as s:
        assert lock_generation(s, v['tenant'], v['conv'], 0)
        assert renew_agent_send(s, v['tenant'], v['conv'], v['message'], 0)
        remaining = s.execute(text('select extract(epoch from expires_at-clock_timestamp()) from private_deletion_sends')).scalar_one()
        assert 55 < remaining <= 60
        s.commit()
    with database.begin() as c:
        c.execute(text("update private_deletion_sends set expires_at=clock_timestamp()-interval '1 second'"))
    with scoped(database, v['tenant']) as s:
        assert lock_generation(s, v['tenant'], v['conv'], 0)
        assert not renew_agent_send(s, v['tenant'], v['conv'], v['message'], 0)


def test_prayer_collection_media_erased_without_admin_read(database, private_data):
    from app.services.private_deletion import process_storage_tasks
    v = private_data
    with database.begin() as c:
        # A content-free orphan fence is also the state left by person offboarding.
        c.execute(text("insert into pedido_oracao_mensagem(igreja_id,conversation_id,message_id) values(:tenant,:conv,:message)"), v)
        # The composite FK may remain NO ACTION even without the legacy cascade.
        c.exec_driver_sql('alter table messages drop constraint if exists messages_conversation_id_fkey')
    with scoped(database, v['tenant'], admin=True) as s:
        assert s.execute(text('select id from messages where id=:message'), v).first() is None
    with api(database, v) as client:
        response = client.delete(f"/conversations/{v['conv']}")
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['camadas']['mensagens']['apagadas'] == 1
        assert result['camadas']['midias']['pendentes'] == 2
        assert client.get(f"/conversations/{v['conv']}/deletion-receipt").json() == result
        assert 'synthetic.png' not in response.text and 'Synthetic private text' not in response.text
    with database.connect() as c:
        assert c.execute(text('select count(*) from messages where conversation_id=:conv'), v).scalar_one() == 0
        assert c.execute(text('select count(*) from pedido_oracao_mensagem where conversation_id=:conv'), v).scalar_one() == 0
        assert c.execute(text('select count(*) from messages where igreja_id=:other'), v).scalar_one() == 1
    calls = []
    class Storage:
        def remove_tenant_media(self, tenant, paths):
            assert tenant == v['tenant']
            calls.extend(paths)
    assert process_storage_tasks(lambda: Session(database), storage=Storage(), now=dt.datetime.now(dt.UTC)+dt.timedelta(days=1)) == 2
    assert f"{v['tenant']}/{v['conv']}/synthetic.png" in calls
    with database.connect() as c:
        assert c.execute(text("select count(*) from private_deletion_tasks where igreja_id=:tenant and (state!='concluida' or storage_path is not null)"), v).scalar_one() == 0


def test_privileged_church_erasure_keeps_protected_media_in_manifest(database, private_data):
    from app.db.tenant_session import mark_cross_tenant
    from app.services.tenant_deletion import delete_tenant_locally, TenantDeletionActor
    v = private_data
    with database.begin() as c:
        c.execute(text('insert into pedido_oracao_mensagem(igreja_id,conversation_id,message_id) values(:tenant,:conv,:message)'), v)
    with Session(database) as s:
        mark_cross_tenant(s, source='synthetic_church_erasure_test')
        result = delete_tenant_locally(s, v['tenant'], TenantDeletionActor(v['admin'], 'synthetic@example.invalid'))
        s.commit()
        assert result.deleted_now
    with database.connect() as c:
        assert c.execute(text('select count(*) from pedido_oracao_mensagem where igreja_id=:tenant'), v).scalar_one() == 0
        assert c.execute(text('select count(*) from messages where igreja_id=:tenant'), v).scalar_one() == 0
        assert c.execute(text('select count(*) from messages where igreja_id=:other'), v).scalar_one() == 1
        manifest = c.execute(text('select detalhe from platform_audit_log where alvo_id=:tenant'), v).scalars().all()
        assert f"{v['tenant']}/{v['conv']}/synthetic.png" in json.dumps(manifest)
