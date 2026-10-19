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
                         'delete from private_deletion_uploads; delete from private_deletion_receipts')
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
    tables=('private_deletion_receipts','private_deletion_tasks','private_deletion_uploads','private_deletion_event_fences')
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
