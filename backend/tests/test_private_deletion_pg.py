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
                         'delete from private_deletion_uploads; delete from private_deletion_sends; delete from private_deletion_dependencies; delete from private_deletion_members; delete from private_deletion_receipts')
    v = {k: uuid4() for k in ('tenant', 'other', 'person', 'person2', 'person3', 'admin', 'conv', 'conv2', 'conv3', 'message', 'audio')}
    with database.begin() as c:
        c.execute(text("insert into igrejas(id,nome) values(:id,'Synthetic church A')"), dict(id=v['tenant']))
        c.execute(text("insert into igrejas(id,nome) values(:id,'Synthetic church B')"), dict(id=v['other']))
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


@pytest.fixture
def responsibilities(database, private_data):
    """Official history in both churches, alongside the private deletion graph."""
    v = private_data
    other_admin = uuid4()
    with database.begin() as c:
        c.execute(text("insert into app_users(id,igreja_id,nome,email,status) values(:u,:other,'Synthetic','other@example.invalid','ativo')"), dict(v, u=other_admin))
        for tenant, person, author in ((v['tenant'], v['person'], v['admin']),
                                       (v['other'], v['person3'], other_admin)):
            c.execute(text("insert into responsabilidades_setor(igreja_id,pessoa_id,setor,inicio,atribuida_por) values(:t,:p,'agenda','2026-10-01',:u)"), dict(t=tenant, p=person, u=author))
    return v


def test_person_cascade_after_approved_private_erasure(database, responsibilities):
    from app.services.private_deletion import event_was_deleted
    v = responsibilities
    with database.begin() as c:
        c.execute(text("update messages set provider_message_id='responsibility-erasure' where id=:message"), v)
    with api(database, v) as client:
        response = client.request('DELETE', f"/contacts/{v['person']}/private-content", json=dict(
            operation_id=str(uuid4()), confirmacao='EXCLUIR CONTEUDO PRIVADO'))
        assert response.status_code == 200, response.text
        receipt_id = response.json()['id']
    with database.begin() as c:
        # #518 erases private content, preserving official records and opt-out.
        assert c.scalar(text('select count(*) from responsabilidades_setor where igreja_id=:tenant'), v) == 1
        c.execute(text('delete from pessoas where id=:person and igreja_id=:tenant'), v)
        assert c.scalar(text('select count(*) from responsabilidades_setor where igreja_id=:tenant'), v) == 0
        assert c.scalar(text('select count(*) from responsabilidades_setor where igreja_id=:other'), v) == 1
        assert c.scalar(text('select count(*) from pessoas where id=:person3'), v) == 1
        assert c.scalar(text('select count(*) from messages where igreja_id=:other'), v) == 1
        assert c.scalar(text('select count(*) from private_deletion_receipts where id=:id'), dict(id=receipt_id)) == 1
    with scoped(database, v['tenant']) as s:
        assert event_was_deleted(s, v['tenant'], 'responsibility-erasure')


@pytest.mark.parametrize('author_column', ['atribuida_por', 'encerrada_por'])
def test_responsibility_authors_remain_protected(database, responsibilities, author_column):
    from sqlalchemy.exc import IntegrityError
    v = responsibilities
    author = uuid4()
    with database.begin() as c:
        c.execute(text("insert into app_users(id,igreja_id,nome,email,status) values(:u,:tenant,'Synthetic','history@example.invalid','ativo')"), dict(v, u=author))
        if author_column == 'atribuida_por':
            c.execute(text("insert into responsabilidades_setor(igreja_id,pessoa_id,setor,inicio,atribuida_por) values(:tenant,:person,'consolidacao','2026-10-01',:u)"), dict(v, u=author))
        else:
            c.execute(text("update responsabilidades_setor set fim='2026-10-20',encerrada_por=:u,encerrada_em=now() where igreja_id=:tenant"), dict(v, u=author))
    with database.begin() as c, pytest.raises(IntegrityError) as error:
        c.execute(text('delete from app_users where id=:u'), dict(u=author))
    assert error.value.orig.pgcode == '23503'
    assert 'responsabilidades_setor' in str(error.value.orig)


def test_reset_with_responsibilities(database, responsibilities):
    from app.db.tenant_session import mark_cross_tenant
    from app.services.tenant_deletion import reset_all_tenants, TenantDeletionActor
    with Session(database) as s:
        mark_cross_tenant(s, source='synthetic_responsibility_reset')
        result = reset_all_tenants(s, TenantDeletionActor(None, 'reset_tudo'))
        s.commit()
        assert result.igrejas_deleted == 2
    with database.connect() as c:
        for table in ('igrejas', 'pessoas', 'responsabilidades_setor'):
            assert c.scalar(text(f'select count(*) from {table}')) == 0
        assert c.scalar(text('select count(*) from private_deletion_receipts')) >= 2


def scoped(engine, tenant, *, admin=False):
    s = Session(engine)
    mark_tenant_scoped(s, tenant, source='private_deletion_test')
    if admin:
        s.execute(text("select set_config('request.jwt.claims', '{\"sub\":\"deletion-admin\"}', true)"))
    return s


def api(engine, v, roles=('admin',)):
    app = FastAPI(); app.include_router(router)
    from app.routers.private_content import router as private_router
    app.include_router(private_router)
    def db():
        with scoped(engine, v['tenant'], admin=True) as s:
            yield s
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        app_user_id=str(v['admin']), igreja_id=str(v['tenant']), clerk_user_id='deletion-admin',
        nome='Synthetic', email='synthetic@example.invalid', roles=frozenset(roles))
    app.dependency_overrides[get_storage] = lambda: SimpleNamespace(remove=lambda paths: None)
    return TestClient(app)


@pytest.mark.parametrize("version", ("v1", "v2", None))
def test_delete_returns_durable_receipt_instead_of_losing_storage_failures(database, private_data, version):
    with database.begin() as c:
        c.execute(text("update cell_report_audio_inputs set consent_version=:version where id=:audio"),
                  dict(version=version, audio=private_data["audio"]))
    v = private_data
    # Retained content remains removable by the official admin path after 24h.
    with database.begin() as c:
        c.execute(text("""update cell_report_audio_inputs
            set state='transcrita', received_at=now()-interval '25 hours',
                expires_at=now()-interval '1 hour' where id=:audio"""), v)
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


@pytest.mark.parametrize('scope', ['conversa', 'pessoa', 'igreja'])
def test_real_ingestion_upload_serializes_with_deletion(database, private_data, scope):
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
            if scope=='conversa':
                return client.delete(f"/conversations/{v['conv']}")
            path=f"/contacts/{v['person']}/private-content" if scope=='pessoa' else '/igreja/private-content'
            payload=dict(operation_id=str(uuid4()),confirmacao='EXCLUIR CONTEUDO PRIVADO')
            if scope=='igreja':
                payload=dict(operation_id=payload['operation_id'],nome_igreja='Synthetic church A',
                             confirmacao='EXCLUIR CONTEUDO PRIVADO DA IGREJA')
            return client.request('DELETE',path,json=payload)
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
        assert result.json()['camadas']['mensagens']['apagadas']==(3 if scope=='igreja' else 2)
        assert result.json()['camadas']['midias']['pendentes']==(4 if scope=='igreja' else 3)
    with database.connect() as c:
        assert c.execute(text('select count(*) from messages where conversation_id=:conv'),v).scalar_one()==0


def test_receipt_tasks_survive_source_tenant_and_obey_real_rls(database, private_data):
    from sqlalchemy.exc import DBAPIError
    from app.services.private_deletion import process_storage_tasks
    v=private_data
    with api(database,v) as client:
        deleted=client.delete(f"/conversations/{v['conv']}").json()
    tables=('private_deletion_receipts','private_deletion_tasks','private_deletion_uploads','private_deletion_event_fences','private_deletion_sends','private_deletion_members','private_deletion_dependencies')
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


def test_deleted_event_caught_when_deletion_commits_before_ingestion_barrier(database, private_data, monkeypatch):
    from app.services import private_deletion as privacy
    from app.domain.conversations import ParsedMessage
    from app.domain.phone import normalize_phone
    from app.workers.queue_worker import ingest_message_event_ex, IngestionResult
    v=private_data
    with database.begin() as c:
        c.execute(text("update pessoas set telefone='550000000001' where id=:person"),v)
        c.execute(text("update cell_report_audio_inputs set provider_message_sha256=encode(digest('synthetic-racing-event','sha256'),'hex') where id=:audio"),v)
        c.execute(text("insert into whatsapp_connections(igreja_id,instance) values(:tenant,'private-race')"),v)
    original=privacy.acquire_ingestion_barrier; calls=[]
    def interleave(db, tenant, **kwargs):
        if not calls:
            calls.append(True)
            with api(database,v) as client:
                assert client.delete(f"/conversations/{v['conv']}").status_code==200
        return original(db,tenant,**kwargs)
    monkeypatch.setattr(privacy,'acquire_ingestion_barrier',interleave)
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


def test_lost_send_expiry_does_not_claim_completion_or_reopen_transport(database, private_data):
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
        assert result['estado'] == 'pendente_envio'
        assert result['camadas']['envios']['pendentes'] == 1
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


@pytest.mark.parametrize('scope', ['pessoa', 'igreja'])
def test_web_bulk_erasure_receipt_retry_and_two_tenants(database, private_data, scope):
    from app.services.private_deletion import process_storage_tasks, event_was_deleted
    v = private_data
    with database.begin() as c:
        c.execute(text("update pessoas set optout=true, consentimento=false where id=:person"), v)
        c.execute(text("insert into consent_records(igreja_id,pessoa_id,termo_versao,aceite_em) values(:tenant,:person,'v1',now())"), v)
        c.execute(text("insert into agent_conversation_logs(igreja_id,conversation_id,payload) values(:tenant,:conv,'{\"private\":\"synthetic\"}')"), v)
        c.execute(text("insert into agent_conversation_logs(igreja_id,evento,payload) values(:tenant,'subscription_upgrade:synthetic','{\"private\":\"synthetic\"}')"), v)
        c.execute(text("update messages set provider_message_id='bulk-synthetic' where id=:message"), v)
    operation = str(uuid4())
    payload = dict(operation_id=operation, confirmacao='EXCLUIR CONTEUDO PRIVADO')
    path = f"/contacts/{v['person']}/private-content" if scope == 'pessoa' else '/igreja/private-content'
    if scope == 'igreja':
        payload = dict(operation_id=operation, nome_igreja='Synthetic church A',
                       confirmacao='EXCLUIR CONTEUDO PRIVADO DA IGREJA')
    with api(database, v) as client:
        assert client.request('DELETE', path, json={**payload, 'confirmacao':'wrong'}).status_code == 422
        if scope == 'igreja':
            assert client.request('DELETE', path, json={**payload, 'nome_igreja':'Synthetic church B'}).status_code == 422
        result = client.request('DELETE', path, json=payload)
        assert result.status_code == 200, result.text
        initial = result.json()
        assert initial['escopo'] == scope
        assert initial['camadas']['mensagens']['apagadas'] == (1 if scope == 'pessoa' else 2)
        assert initial['camadas']['entradas_audio']['apagadas'] == 1
        assert initial['camadas']['logs_agente']['apagadas'] == 1
        assert initial['camadas']['logs_sem_ancora']['apagadas'] == 1
        assert client.request('DELETE',path,json=payload).json() == initial
        assert client.get(f"/igreja/private-deletions/{initial['id']}").json() == initial
        person_payload = dict(operation_id=operation, confirmacao='EXCLUIR CONTEUDO PRIVADO')
        assert client.request('DELETE',f"/contacts/{v['person3']}/private-content",json=person_payload).status_code == 404
    with scoped(database, v['tenant']) as s:
        assert event_was_deleted(s, v['tenant'], 'bulk-synthetic')
    calls = []
    assert process_storage_tasks(lambda: Session(database), storage=SimpleNamespace(
        remove_tenant_media=lambda t,paths: calls.append((t,paths)))) == (2 if scope == 'pessoa' else 3)
    assert all(t == v['tenant'] for t,_ in calls)
    with database.connect() as c:
        assert c.execute(text('select optout from pessoas where id=:person'),v).scalar_one()
        assert c.execute(text('select count(*) from consent_records where pessoa_id=:person'),v).scalar_one() == 1
        if scope == 'igreja':
            assert c.execute(text('select count(*) from pessoas where igreja_id=:tenant'),v).scalar_one() == 2
        assert c.execute(text('select count(*) from messages where igreja_id=:other'),v).scalar_one() == 1
        assert c.execute(text('select payload from agent_conversation_logs where conversation_id is null')).scalar_one() is None
    with api(database,v) as client:
        finished=client.get(f"/igreja/private-deletions/{initial['id']}").json()
        assert finished['estado']=='concluido'
        assert 'synthetic' not in json.dumps(finished).lower()


@pytest.mark.parametrize('scope', ['pessoa', 'igreja'])
def test_bulk_web_and_sql_deny_nonadmin_and_cross_tenant(database,private_data,scope):
    from sqlalchemy.exc import DBAPIError
    v=private_data
    payload=dict(operation_id=str(uuid4()),confirmacao='EXCLUIR CONTEUDO PRIVADO')
    path=f"/contacts/{v['person']}/private-content" if scope=='pessoa' else '/igreja/private-content'
    if scope == 'igreja':
        payload = dict(operation_id=payload['operation_id'], nome_igreja='Synthetic church A',
                       confirmacao='EXCLUIR CONTEUDO PRIVADO DA IGREJA')
    with api(database,v,('pastor',)) as client:
        assert client.request('DELETE',path,json=payload).status_code==403
    for tenant,sub in ((v['tenant'],'unknown'),(v['other'],'deletion-admin')):
        with scoped(database,tenant) as s:
            s.execute(text("select set_config('request.jwt.claims',:claims,true)"),dict(claims=json.dumps(dict(sub=sub))))
            with pytest.raises(DBAPIError):
                s.execute(text('select private_delete_scope(:t,:scope,:target,:operation)'),
                    dict(t=v['tenant'],scope=scope,target=v['person'] if scope=='pessoa' else v['tenant'],operation=uuid4()))
            s.rollback()
    with database.begin() as c:
        c.execute(text("update app_users set status='revogado' where id=:admin"),v)
    if scope == 'igreja':
        with api(database, v) as client:
            assert client.request('DELETE', path, json=payload).status_code == 403
    with scoped(database,v['tenant'],admin=True) as s:
        with pytest.raises(DBAPIError):
            s.execute(text('select private_delete_scope(:t,:scope,:target,:operation)'),
                dict(t=v['tenant'],scope=scope,target=v['person'] if scope=='pessoa' else v['tenant'],operation=uuid4()))


def test_church_reset_receipt_accumulates_prior_private_deletions(database, private_data):
    v = private_data
    payload = dict(operation_id=str(uuid4()), nome_igreja='Synthetic church A',
                   confirmacao='EXCLUIR CONTEUDO PRIVADO DA IGREJA')
    with api(database, v) as client:
        prior = client.delete(f"/conversations/{v['conv']}")
        assert prior.status_code == 200, prior.text
        response = client.request('DELETE', '/igreja/private-content', json=payload)
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt['escopo'] == 'igreja'
        assert receipt['camadas']['mensagens']['encontradas'] == 2
        assert receipt['camadas']['mensagens']['apagadas'] == 2
        assert receipt['camadas']['midias']['pendentes'] == 3
        assert client.request('DELETE', '/igreja/private-content', json=payload).json() == receipt
        assert client.get(f"/igreja/private-deletions/{receipt['id']}").json() == receipt
    with database.connect() as c:
        assert c.execute(text('select count(*) from messages where igreja_id=:tenant'), v).scalar_one() == 0
        assert c.execute(text('select count(*) from messages where igreja_id=:other'), v).scalar_one() == 1


def test_bulk_new_operation_erases_new_content_but_retry_is_snapshot(database,private_data):
    v=private_data; op=uuid4()
    from app.services.private_deletion import delete_private
    with scoped(database,v['tenant'],admin=True) as s:
        first=delete_private(s,scope='pessoa',igreja_id=v['tenant'],target_id=v['person'],operation_id=op)
    new_conv=uuid4()
    with database.begin() as c:
        c.execute(text("insert into conversations(id,igreja_id,pessoa_id,telefone) values(:c,:tenant,:person,'000000000000')"),dict(v,c=new_conv))
    with scoped(database,v['tenant'],admin=True) as s:
        assert delete_private(s,scope='pessoa',igreja_id=v['tenant'],target_id=v['person'],operation_id=op)==first
    with database.connect() as c:
        assert c.execute(text('select count(*) from conversations where id=:c'),dict(c=new_conv)).scalar_one()==1
    with scoped(database,v['tenant'],admin=True) as s:
        second=delete_private(s,scope='pessoa',igreja_id=v['tenant'],target_id=v['person'],operation_id=uuid4())
        assert second['id']!=first['id']
    with database.connect() as c:
        assert c.execute(text('select count(*) from conversations where id=:c'),dict(c=new_conv)).scalar_one()==0


def test_bulk_late_upload_survives_source_and_tenant_loss(database,private_data):
    from app.services.private_deletion import begin_audio_upload,finish_audio_upload,delete_private,process_storage_tasks
    v=private_data; factory=lambda:Session(database)
    assert begin_audio_upload(factory,claim(v))
    with scoped(database,v['tenant'],admin=True) as s:
        result=delete_private(s,scope='igreja',igreja_id=v['tenant'],target_id=v['tenant'],operation_id=uuid4())
    calls=[]; storage=SimpleNamespace(remove_tenant_media=lambda t,paths:calls.append(paths))
    assert process_storage_tasks(factory,storage=storage)==2  # image paths only; audio still owned
    with database.begin() as c:
        c.execute(text('delete from igrejas where id=:tenant'),v)
    finish_audio_upload(factory,claim(v))
    assert process_storage_tasks(factory,storage=storage)==1
    with database.connect() as c:
        assert c.execute(text("select count(*) from private_deletion_tasks where receipt_id=:r and state='pendente'"),dict(r=result['id'])).scalar_one()==0


def test_transcriptions_count_text_not_untranscribed_inputs(database,private_data):
    v=private_data
    with database.begin() as c:
        c.execute(text('update cell_report_audio_inputs set transcript_text=null where id=:audio'),v)
    with api(database,v) as client:
        r=client.delete(f"/conversations/{v['conv']}").json()
        assert r['camadas']['transcricoes']['apagadas']==0
        assert r['camadas']['entradas_audio']['apagadas']==1


def test_platform_erasure_uses_private_queue_and_preserves_other_tenant(database,private_data):
    from app.services.tenant_deletion import delete_tenant_locally,TenantDeletionActor
    from app.services.private_deletion import process_storage_tasks
    v=private_data
    with Session(database) as s:
        result=delete_tenant_locally(s,v['tenant'],TenantDeletionActor(None,None))
        assert result.deleted_now
        s.commit()
    with database.connect() as c:
        assert c.execute(text('select count(*) from igrejas where id=:tenant'),v).scalar_one()==0
        assert c.execute(text('select count(*) from messages where igreja_id=:other'),v).scalar_one()==1
        assert c.execute(text("select count(*) from private_deletion_receipts where igreja_id=:tenant and scope='igreja'"),v).scalar_one()==1
        assert c.execute(text("select count(*) from private_deletion_tasks where igreja_id=:tenant and state='pendente'"),v).scalar_one()==3
        assert c.execute(text('select count(*) from cell_report_audio_inputs where igreja_id=:tenant'),v).scalar_one()==0
    calls=[]
    assert process_storage_tasks(lambda:Session(database),storage=SimpleNamespace(remove_tenant_media=lambda t,paths:calls.append(t)))==3
    assert calls==[v['tenant']]*3


def test_private_deletion_receipt_requires_active_admin(database, private_data):
    v = private_data
    with api(database, v) as client:
        erased = client.request('DELETE', f"/contacts/{v['person']}/private-content", json={
            'operation_id': str(uuid4()), 'confirmacao': 'EXCLUIR CONTEUDO PRIVADO',
        })
        assert erased.status_code == 200, erased.text
        receipt_id = erased.json()['id']
    with database.begin() as c:
        c.execute(text("update app_users set status='revogado' where id=:admin"), v)
    with api(database, v) as client:
        response = client.get(f"/igreja/private-deletions/{receipt_id}")
        assert response.status_code == 403


def test_church_receipt_includes_older_conversation_cleanup(database,private_data):
    v=private_data
    with api(database,v) as client:
        earlier=client.delete(f"/conversations/{v['conv']}").json()
        bulk=client.request('DELETE','/igreja/private-content',json=dict(
            operation_id=str(uuid4()),nome_igreja='Synthetic church A',
            confirmacao='EXCLUIR CONTEUDO PRIVADO DA IGREJA')).json()
        assert earlier['camadas']['midias']['pendentes']==2
        assert bulk['camadas']['midias']['pendentes']==3
        assert bulk['camadas']['mensagens']['apagadas']==2
        assert bulk['estado']=='pendente'


def test_person_erases_orphan_audio_and_reopens_its_late_upload(database,private_data):
    from app.services.private_deletion import begin_audio_upload,finish_audio_upload,process_storage_tasks
    v=private_data; factory=lambda:Session(database)
    assert begin_audio_upload(factory,claim(v))
    with database.begin() as c:
        c.execute(text('update cell_report_audio_inputs set conversation_id=:old,inbound_message_id=:msg,live_conversation_id=null,live_message_id=null where id=:audio'),dict(v,old=uuid4(),msg=uuid4()))
    with api(database,v) as client:
        r=client.request('DELETE',f"/contacts/{v['person']}/private-content",json=dict(
            operation_id=str(uuid4()),confirmacao='EXCLUIR CONTEUDO PRIVADO'))
        assert r.status_code==200,r.text
        assert r.json()['camadas']['entradas_audio']['apagadas']==1
    storage=SimpleNamespace(remove_tenant_media=lambda *args:None)
    assert process_storage_tasks(factory,storage=storage)==1
    finish_audio_upload(factory,claim(v))
    assert process_storage_tasks(factory,storage=storage)==1


def test_person_receipt_includes_prior_church_cleanup(database,private_data):
    v=private_data
    with api(database,v) as client:
        church=client.request('DELETE','/igreja/private-content',json=dict(
            operation_id=str(uuid4()),nome_igreja='Synthetic church A',
            confirmacao='EXCLUIR CONTEUDO PRIVADO DA IGREJA')).json()
        person=client.request('DELETE',f"/contacts/{v['person']}/private-content",json=dict(
            operation_id=str(uuid4()),confirmacao='EXCLUIR CONTEUDO PRIVADO')).json()
        assert person['camadas']['midias']['pendentes']==church['camadas']['midias']['pendentes']==3
        assert person['estado']=='pendente'


@pytest.mark.parametrize('scope',['conversa','pessoa','igreja'])
@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_admin_bulk_erases_protected_messages_without_read_permission(database,private_data,scope,version):
    from app.services.private_deletion import process_storage_tasks
    v=private_data
    with database.begin() as c:
        c.execute(text("""update cell_report_audio_inputs set consent_version=:version,
            state='transcrita', received_at=now()-interval '25 hours',
            expires_at=now()-interval '1 hour' where id=:audio"""),dict(v,version=version))
    with database.begin() as c:
        c.execute(text('insert into pedido_oracao_mensagem(igreja_id,conversation_id,message_id) values(:tenant,:conv,:message)'),v)
    with scoped(database,v['tenant'],admin=True) as s:
        assert s.execute(text('select count(*) from messages where id=:message'),v).scalar_one()==0
    with api(database,v) as client:
        if scope=='conversa':
            response=client.delete(f"/conversations/{v['conv']}")
        else:
            path=f"/contacts/{v['person']}/private-content" if scope=='pessoa' else '/igreja/private-content'
            payload=dict(operation_id=str(uuid4()),confirmacao='EXCLUIR CONTEUDO PRIVADO')
            if scope=='igreja':
                payload=dict(operation_id=payload['operation_id'],nome_igreja='Synthetic church A',
                             confirmacao='EXCLUIR CONTEUDO PRIVADO DA IGREJA')
            response=client.request('DELETE',path,json=payload)
        assert response.status_code==200,response.text
        result=response.json()
        assert result['camadas']['pedido_oracao_mensagem']['apagadas']==1
        assert result['camadas']['midias']['pendentes']==(3 if scope=='igreja' else 2)
        assert 'synthetic' not in json.dumps(result).lower()
    with database.connect() as c:
        assert c.execute(text('select count(*) from pedido_oracao_mensagem')).scalar_one()==0
        assert c.execute(text('select count(*) from messages where igreja_id=:other'),v).scalar_one()==1


    calls = []
    assert process_storage_tasks(lambda: Session(database), storage=SimpleNamespace(
        remove_tenant_media=lambda tenant, paths: calls.extend((tenant, path) for path in paths)),
        now=dt.datetime.now(dt.UTC)+dt.timedelta(days=1)) == (3 if scope=='igreja' else 2)
    assert (v['tenant'], f"{v['tenant']}/cell-report-audio/synthetic.ogg") in calls
    assert all(tenant == v['tenant'] for tenant, _ in calls)
    with database.connect() as c:
        assert c.execute(text('select count(*) from cell_report_audio_inputs where id=:audio'), v).scalar_one() == 0
    with api(database, v) as client:
        final = client.get(f"/igreja/private-deletions/{result['id']}").json()
        assert final['estado'] == 'concluido'
        assert final['camadas']['midias']['pendentes'] == 0


def test_person_erases_unlinked_conversation_identified_by_private_source(database,private_data):
    v=private_data
    with database.begin() as c:
        c.execute(text('update conversations set pessoa_id=null where id=:conv'),v)
    with api(database,v) as client:
        response=client.request('DELETE',f"/contacts/{v['person']}/private-content",json=dict(
            operation_id=str(uuid4()),confirmacao='EXCLUIR CONTEUDO PRIVADO'))
        assert response.status_code==200,response.text
        assert response.json()['camadas']['mensagens']['apagadas']==1
        assert response.json()['camadas']['entradas_audio']['apagadas']==1
    with database.connect() as c:
        assert c.execute(text('select count(*) from messages where conversation_id=:conv'),v).scalar_one()==0


def test_private_scope_owner_helper_and_dependency_rls(database,private_data):
    from sqlalchemy.exc import DBAPIError
    v=private_data
    with api(database,v) as client:
        client.delete(f"/conversations/{v['conv']}")
        result=client.request('DELETE','/igreja/private-content',json=dict(
            operation_id=str(uuid4()),nome_igreja='Synthetic church A',
            confirmacao='EXCLUIR CONTEUDO PRIVADO DA IGREJA')).json()
    with scoped(database,v['other']) as s:
        assert s.execute(text('select count(*) from private_deletion_dependencies')).scalar_one()==0
        assert s.execute(text('select count(*) from private_deletion_members')).scalar_one()==0
    with scoped(database,v['tenant'],admin=True) as s:
        assert s.execute(text('select count(*) from private_deletion_dependencies where receipt_id=:r'),dict(r=result['id'])).scalar_one()==1
        with pytest.raises(DBAPIError):
            s.execute(text("select private_delete_content(:tenant,'igreja',:tenant,:op)"),dict(v,op=uuid4()))
        s.rollback()
    with database.connect() as c:
        for role in ('anon','authenticated','service_role'):
            assert not c.execute(text("select has_function_privilege(:r,'private_delete_content(uuid,text,uuid,uuid)','EXECUTE')"),dict(r=role)).scalar_one()


@pytest.mark.parametrize('person_phone,conversation_phone',[
    ('00900000001','+55 (00) 90000-0001'),
    ('+55 (00) 90000-0001','0000000001'),
    ('00900000001','550000000001'),
])
def test_person_erasure_matches_canonical_phone_of_unlinked_conversation(database,private_data,person_phone,conversation_phone):
    v=private_data
    with database.begin() as c:
        c.execute(text('delete from cell_report_audio_inputs where igreja_id=:tenant'),v)
        c.execute(text('update pessoas set telefone=:phone where id=:person'),dict(v,phone=person_phone))
        c.execute(text('update conversations set pessoa_id=null,telefone=:phone where id=:conv'),dict(v,phone=conversation_phone))
        c.execute(text("update conversations set pessoa_id=null,telefone='01900000001' where id=:conv2"),v)
    with api(database,v) as client:
        response=client.request('DELETE',f"/contacts/{v['person']}/private-content",json=dict(
            operation_id=str(uuid4()),confirmacao='EXCLUIR CONTEUDO PRIVADO'))
        assert response.status_code==200,response.text
        assert response.json()['camadas']['mensagens']['apagadas']==1
        assert response.json()['camadas']['midias']['pendentes']==1
    with database.connect() as c:
        assert c.execute(text('select count(*) from messages where conversation_id=:conv'),v).scalar_one()==0
        assert c.execute(text('select count(*) from messages where conversation_id=:conv2'),v).scalar_one()==1
        assert c.execute(text('select count(*) from messages where igreja_id=:other'),v).scalar_one()==1


def test_expired_send_stays_pending_until_known_transport_return(database,private_data):
    from app.workers import queue_worker as worker
    from app.services.private_deletion import process_storage_tasks
    v=private_data; factory=lambda:Session(database)
    outcome=worker.IngestionOutcome(result=worker.IngestionResult.REGISTERED,conversation_id=v['conv'],
        instance='synthetic',telefone='000000000000',texto='synthetic',inbound=True,
        igreja_id=v['tenant'],inbound_message_id=v['message'],provider_message_id='synthetic-expired-http',claim_id='synthetic-expired-http')
    intent=worker._prepare_agent_reply_intent(factory,outcome,'Synthetic reply',public_info_reply=False)
    observed=[]
    class Transport:
        def send_text(self,*args):
            with database.begin() as c:
                c.execute(text("update private_deletion_sends set expires_at=clock_timestamp()-interval '1 second' where igreja_id=:tenant"),v)
            with api(database,v) as client:
                observed.append(client.delete(f"/conversations/{v['conv']}").json())
            process_storage_tasks(factory,storage=SimpleNamespace(remove_tenant_media=lambda *args:None))
            with api(database,v) as client:
                observed.append(client.get(f"/conversations/{v['conv']}/deletion-receipt").json())
            return SimpleNamespace(status='aceito')
    worker._deliver_agent_reply_intent(factory,outcome,intent,None,evolution_client=Transport())
    assert [r['estado'] for r in observed]==['pendente_envio','pendente_envio']
    assert all(r['camadas']['envios']['pendentes']==1 for r in observed)
    with api(database,v) as client:
        assert client.get(f"/conversations/{v['conv']}/deletion-receipt").json()['estado']=='concluido'


@pytest.mark.parametrize('phone',[None,'','invalid','00900000001','0000000001','+55 (00) 90000-0001',
    '550000000001','5500900000001','01900000001','+54 00 90000-0001','12345678','550000000001'])
def test_deletion_phone_key_matches_domain_canonical_rules(database,phone):
    from app.domain.phone import normalize_phone
    with database.connect() as c:
        actual=c.execute(text('select private_deletion_phone_key(:phone)'),dict(phone=phone)).scalar_one()
    assert actual==normalize_phone(phone)


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


def test_privileged_church_erasure_keeps_protected_media_in_manifest(database, private_data, responsibilities):
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
        assert c.scalar(text('select count(*) from responsabilidades_setor where igreja_id=:tenant'), v) == 0
        assert c.scalar(text('select count(*) from responsabilidades_setor where igreja_id=:other'), v) == 1
        assert c.scalar(text('select count(*) from pessoas where id=:person3'), v) == 1
        manifest = c.execute(text('select detalhe from platform_audit_log where alvo_id=:tenant'), v).scalars().all()
        assert f"{v['tenant']}/{v['conv']}/synthetic.png" in json.dumps(manifest)
        assert c.execute(text('select count(*) from private_deletion_tasks where igreja_id=:tenant and storage_path=:path'), dict(v,path=f"{v['tenant']}/{v['conv']}/synthetic.png")).scalar_one()==1


@pytest.mark.parametrize('scope', ['conversa', 'pessoa', 'igreja'])
@pytest.mark.parametrize('state', ['consumida', 'pendente'])
@pytest.mark.parametrize('legacy_fallback', [True, False])
def test_secretaria_offer_erasure_clears_anchors_before_messages(database, private_data, scope, state, legacy_fallback):
    v = private_data
    with database.begin() as c:
        for conv in (v['conv'], v['conv3']):
            row = c.execute(text('select id from messages where conversation_id=:conv'), dict(conv=conv)).scalar_one()
            c.execute(text('''update conversations set secretaria_oferta_estado=:state,
                secretaria_oferta_message_id=:message,
                secretaria_oferta_resposta_message_id=case when :state='consumida' then :message else null end,
                secretaria_oferta_expira_em=case when :state='pendente' then now()+interval '1 hour' else null end
                where id=:conv'''), dict(conv=conv, message=row, state=state))
        # Explicit ordering must also work without the legacy fallback trigger,
        # as in the tenant reset, which already clears these anchors itself.
        if not legacy_fallback:
            c.exec_driver_sql('alter table messages disable trigger clear_secretaria_offer_before_message_delete')
    try:
        with api(database, v) as client:
            if scope == 'conversa':
                response = client.delete(f"/conversations/{v['conv']}")
            else:
                path = f"/contacts/{v['person']}/private-content" if scope == 'pessoa' else '/igreja/private-content'
                payload=dict(operation_id=str(uuid4()),confirmacao='EXCLUIR CONTEUDO PRIVADO')
                if scope=='igreja':
                    payload=dict(operation_id=payload['operation_id'],nome_igreja='Synthetic church A',
                                 confirmacao='EXCLUIR CONTEUDO PRIVADO DA IGREJA')
                response = client.request('DELETE', path, json=payload)
            assert response.status_code == 200, response.text
            receipt = response.json()
            assert receipt['camadas']['mensagens']['apagadas'] == (2 if scope == 'igreja' else 1)
            assert receipt['camadas']['midias']['pendentes'] == (3 if scope == 'igreja' else 2)
        with database.connect() as c:
            assert c.execute(text('select count(*) from conversations where id=:conv'), v).scalar_one() == 0
            assert c.execute(text('select secretaria_oferta_estado from conversations where id=:conv3'), v).scalar_one() == state
            assert c.execute(text('select count(*) from messages where igreja_id=:other'), v).scalar_one() == 1
    finally:
        with database.begin() as c:
            c.exec_driver_sql('alter table messages enable trigger clear_secretaria_offer_before_message_delete')


@pytest.mark.parametrize('role', ['operador', 'lider_celula', 'membro'])
def test_person_reset_denies_non_admin(database, private_data, role):
    v = private_data
    with api(database, v, roles=(role,)) as client:
        result = client.request('DELETE', f"/contacts/{v['person']}/private-content", json={
            'operation_id': str(uuid4()), 'confirmacao': 'EXCLUIR CONTEUDO PRIVADO'})
        assert result.status_code == 403
    with database.connect() as c:
        assert c.scalar(text('select count(*) from conversations where id=:conv'), v) == 1


def test_person_reset_http_replay_preserves_new_content(database, private_data):
    v = private_data
    payload = {'operation_id': str(uuid4()), 'confirmacao': 'EXCLUIR CONTEUDO PRIVADO'}
    with api(database, v) as client:
        first = client.request('DELETE', f"/contacts/{v['person']}/private-content", json=payload)
        assert first.status_code == 200, first.text
        with database.begin() as c:
            c.execute(text("insert into conversations(id,igreja_id,pessoa_id,telefone) values(:id,:tenant,:person,'000000000000')"), dict(v, id=uuid4()))
        replay = client.request('DELETE', f"/contacts/{v['person']}/private-content", json=payload)
        assert replay.status_code == 200, replay.text
        assert replay.json() == first.json()
    with database.connect() as c:
        assert c.scalar(text('select count(*) from conversations where igreja_id=:tenant and pessoa_id=:person'), v) == 1
        assert c.scalar(text('select count(*) from private_deletion_receipts where igreja_id=:tenant'), v) == 1
