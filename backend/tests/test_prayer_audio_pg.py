"""Synthetic audio through ingestion, real prayer router, domain and inbox RLS."""
import dataclasses
import uuid
import pytest
from sqlalchemy import select, text
from app.db.models import Message
from app.prayer.models import PrayerProposal, PrayerRequest
from app.workers.queue_worker import ingest_message_event_ex, run_agent_for_message
from tests.test_messages_inbound_idempotency import _parsed, _ClassifiedEvolution
from tests.test_prayer_privacy_pg import (  # noqa: F401
    private_prayer, prayer, msg_engine_fx, rls_database_url, TENANT,
    send, client_for, Storage, MARKER,
)

pytestmark = pytest.mark.rls_integration


def audio(p):
    from types import SimpleNamespace
    parsed = dataclasses.replace(
        _parsed(provider_message_id='prayer-audio-' + uuid.uuid4().hex,
                instance='prayer-test', telefone='5500000000000'),
        texto=None, media_kind='audio', media_mime='audio/ogg', media_nome='pedido.ogg',
    )
    path = f'{TENANT}/synthetic/prayer.ogg'
    with p.factory() as db:
        outcome = ingest_message_event_ex(
            db, parsed, media_resolver=lambda *args: SimpleNamespace(
                path=path, mime='audio/ogg', nome='pedido.ogg', tamanho=12),
        )
    return dataclasses.replace(outcome, claim_id='prayer-audio-claim'), path


def test_audio_collection_full_turn_retention_and_deletion(private_prayer):
    p = private_prayer
    send(p, 'Quero iniciar pedido de oração')
    outcome, path = audio(p)
    mid = outcome.inbound_message_id
    # Privacy is already effective before the first audio worker executes.
    with client_for(p, 'admin') as client:
        rows = client.get(f'/conversations/{p.conv}/messages').json()['items']
        assert next(m for m in rows if m['id'] == str(mid))['texto'] == MARKER
    transport = _ClassifiedEvolution()
    run_agent_for_message(p.factory, outcome, evolution_client=transport)
    assert transport.calls
    with p.factory() as db:
        assert db.scalar(select(PrayerProposal.summary)) == 'Pedido de oração em áudio.'
        assert db.get(Message, mid).media_path == path
        assert db.scalar(text('select count(*) from cell_report_audio_inputs')) == 0
    send(p, 'Só pastores')
    send(p, 'SIM')
    with p.factory() as db:
        assert db.scalar(select(PrayerRequest.audience)) == 'pastoral'
    for role in ('admin', 'operador', 'lider_celula', 'pastor'):
        with client_for(p, role) as client:
            urls = client.get(f'/conversations/{p.conv}/messages/media-urls', params={'ids': str(mid)}).json()['urls']
            assert (str(mid) in urls) == (role == 'pastor')
    with client_for(p, 'admin') as client:
        result = client.delete(f'/conversations/{p.conv}')
        assert result.status_code == 200, result.text
        assert result.json()['camadas']['midias']['pendentes'] == 1
    from app.services.private_deletion import process_storage_tasks
    removed = []
    class Cleanup:
        def remove_tenant_media(self, tenant, paths):
            assert tenant == TENANT
            removed.extend(paths)
    assert process_storage_tasks(p.factory, storage=Cleanup()) == 1
    assert removed == [path]


def test_audio_cannot_be_shared_with_leader(private_prayer):
    p = private_prayer
    send(p, 'Quero iniciar pedido de oração')
    outcome, _ = audio(p)
    run_agent_for_message(p.factory, outcome, evolution_client=_ClassifiedEvolution())
    send(p, 'Pastores e meu líder')
    send(p, 'SIM')
    with p.factory() as db:
        assert db.scalar(select(PrayerRequest)) is None


def test_legacy_shared_collection_audio_is_pastor_only(private_prayer):
    from tests.test_prayer_requests_pg import create_request
    from tests.test_prayer_privacy_pg import scope
    p = private_prayer
    row = create_request(p, 'Pastores e meu líder')
    with p.factory.begin() as db:
        mid = db.get(PrayerProposal, row.proposal_id).source_message_id
        db.get(Message, mid).tipo = 'audio'
        db.get(Message, mid).media_path = f'{TENANT}/synthetic/legacy.ogg'
    for role in ('lider_celula', 'admin', 'pastor'):
        with p.factory() as db:
            scope(db, p, role)
            assert (db.get(Message, mid) is not None) == (role == 'pastor')
        with client_for(p, role) as client:
            rows = client.get(f'/conversations/{p.conv}/messages').json()['items']
            message = next(m for m in rows if m['id'] == str(mid))
            assert (message['texto'] == MARKER) == (role != 'pastor')


def test_prayer_audio_never_enters_report_capture(private_prayer):
    from app.services.cell_report_audio_service import audio_capture_scope_allows
    p = private_prayer
    send(p, 'Quero iniciar pedido de oração')
    outcome, _ = audio(p)
    with p.factory() as db:
        assert not audio_capture_scope_allows(
            db, igreja_id=TENANT, conversation_id=p.conv,
            inbound_message_id=outcome.inbound_message_id,
        )


def test_unavailable_audio_does_not_confirm_invented_request(private_prayer):
    p = private_prayer
    send(p, 'Quero iniciar pedido de oração')
    outcome, _ = audio(p)
    with p.factory.begin() as db:
        db.get(Message, outcome.inbound_message_id).media_path = None
    transport = _ClassifiedEvolution()
    run_agent_for_message(p.factory, outcome, evolution_client=transport)
    assert transport.calls
    with p.factory() as db:
        assert db.scalar(select(PrayerProposal.summary)) == ''
        reply = db.scalars(select(Message).where(Message.direcao == 'out').order_by(Message.criado_em.desc())).first()
        assert 'indisponível' in reply.texto
        assert db.scalar(select(PrayerRequest)) is None


def test_delayed_audio_cannot_move_to_restarted_collection(private_prayer):
    p = private_prayer
    send(p, 'Quero iniciar pedido de oração')
    outcome, _ = audio(p)
    with p.factory() as db:
        original = db.scalar(select(PrayerProposal.id))
    send(p, 'CANCELAR')
    send(p, 'Quero iniciar pedido de oração')
    run_agent_for_message(p.factory, outcome, evolution_client=_ClassifiedEvolution())
    with p.factory() as db:
        current = db.scalar(select(PrayerProposal).where(PrayerProposal.state == 'collecting'))
        assert current.id != original
        assert current.summary == ''
    send(p, 'Pastores e meu líder')
    send(p, 'SIM')
    with p.factory() as db:
        assert db.scalar(select(PrayerRequest)) is None


@pytest.fixture
def report_audio_prayer(private_prayer, monkeypatch):
    import datetime as dt
    from app.config import get_settings
    from app.db.models import AppUser, Celula, CelulaReuniao, UserRole
    from app.services import cell_report_audio as v1b, cell_report_audio_service, cell_report_whatsapp, whatsapp_privilege
    p = private_prayer
    monkeypatch.setattr(v1b, 'CELL_REPORT_AUDIO_APPROVED_RELEASE_ID', 'synthetic-only')
    monkeypatch.setattr(whatsapp_privilege, 'PRIVILEGE_APPROVED_RELEASE_ID', 'synthetic-only')
    monkeypatch.setattr(cell_report_whatsapp, 'CELL_REPORT_APPROVED_RELEASE_ID', 'synthetic-only')
    monkeypatch.setenv('CELL_REPORT_ENABLED_IGREJA_IDS', str(TENANT))
    monkeypatch.setenv('CELL_REPORT_AUDIO_ENABLED_IGREJA_IDS', str(TENANT))
    monkeypatch.setenv('AGENT_PRIVILEGE_ENABLED_IGREJA_IDS', str(TENANT))
    # ORM fixture lives in an isolated schema; only discovery is adapted.
    monkeypatch.setattr(cell_report_audio_service, 'audio_schema_available', lambda db:
        db.scalar(text("select to_regclass('msg_idemp1.cell_report_audio_inputs') is not null")))
    get_settings.cache_clear()
    with p.factory.begin() as db:
        user = AppUser(igreja_id=TENANT, pessoa_id=p.person, nome='Relator sintético',
                       email='relator@example.test', clerk_user_id='synthetic-reporter', status='ativo')
        db.add(user)
        db.flush()
        db.add(UserRole(igreja_id=TENANT, user_id=user.id, papel='lider_celula'))
        db.get(Celula, p.cell).lider_id = p.person
        db.add(CelulaReuniao(igreja_id=TENANT, celula_id=p.cell,
                            data=dt.date.today()-dt.timedelta(days=1), hora='19:00'))
    # Real notice delivery and explicit consent through the existing worker.
    first, _ = audio(p)
    run_agent_for_message(p.factory, first, evolution_client=_ClassifiedEvolution())
    send(p, 'ACEITO AUDIO')
    from app.db.models import CellReportAudioConsentEvent
    with p.factory() as db:
        assert db.scalar(select(CellReportAudioConsentEvent.command)) == 'aceito'
    return p


@pytest.mark.parametrize('collecting', [True, False])
def test_v1b_enabled_consent_routes_prayer_and_regular_audio(report_audio_prayer, collecting):
    import datetime as dt
    from app.db.models import CellReportAudioInput
    from app.services.cell_report_audio_service import purge_cell_report_audio_inputs
    p = report_audio_prayer
    if collecting:
        send(p, 'Quero iniciar pedido de oração')
    outcome, path = audio(p)
    with p.factory() as db:
        job = db.scalar(select(CellReportAudioInput).where(
            CellReportAudioInput.inbound_message_id == outcome.inbound_message_id))
        assert (job is None) == collecting
        assert db.get(Message, outcome.inbound_message_id).media_path == (path if collecting else None)
        if job:
            assert job.consent_version == 'v2'
    transport = _ClassifiedEvolution()
    run_agent_for_message(p.factory, outcome, evolution_client=transport)
    if collecting:
        assert transport.calls
    else:
        with p.factory() as db:
            job = db.scalar(select(CellReportAudioInput).where(
                CellReportAudioInput.inbound_message_id == outcome.inbound_message_id))
            assert job.state == 'pendente'
    # Replay must not create another reply, proposal or report capture.
    with p.factory() as db:
        before = tuple(db.scalar(text(f'select count(*) from {table}')) for table in
                       ('messages', 'pedido_oracao_proposta', 'cell_report_audio_inputs'))
    run_agent_for_message(p.factory, outcome, evolution_client=transport)
    with p.factory() as db:
        assert tuple(db.scalar(text(f'select count(*) from {table}')) for table in
                     ('messages', 'pedido_oracao_proposta', 'cell_report_audio_inputs')) == before
    removed = []
    class Cleanup:
        def remove_tenant_media(self, tenant, paths):
            removed.extend(paths)
    # A real pre-consent V1b row expires; this is not an empty purge proof.
    with p.factory.begin() as db:
        assert db.scalar(text('select count(*) from cell_report_audio_inputs')) >= 1
        if collecting:
            db.scalar(select(PrayerProposal)).expires_at = dt.datetime.now(dt.UTC)-dt.timedelta(hours=1)
    purge_cell_report_audio_inputs(p.factory, storage=Cleanup(),
        now=dt.datetime.now(dt.UTC)+dt.timedelta(hours=25))
    with p.factory() as db:
        assert db.scalar(text("select count(*) from cell_report_audio_inputs where content_purged_at is not null")) >= 1
        if collecting:
            assert db.get(Message, outcome.inbound_message_id).media_path == path
            assert db.scalar(select(PrayerProposal.summary)) == 'Pedido de oração em áudio.'
            assert path not in removed
        else:
            assert db.scalar(select(PrayerProposal)) is None


@pytest.mark.parametrize('deletion_scope', ['pessoa', 'igreja'])
def test_audio_deleted_by_person_and_church(private_prayer, deletion_scope):
    from app.services.private_deletion import delete_private, process_storage_tasks
    from tests.test_prayer_privacy_pg import scope
    p = private_prayer
    send(p, 'Quero iniciar pedido de oração')
    outcome, path = audio(p)
    run_agent_for_message(p.factory, outcome, evolution_client=_ClassifiedEvolution())
    with p.factory() as db:
        scope(db, p, 'admin')
        receipt = delete_private(db, scope=deletion_scope, igreja_id=TENANT,
            target_id=p.person if deletion_scope == 'pessoa' else TENANT, operation_id=uuid.uuid4())
        assert receipt['camadas']['midias']['pendentes'] == 1
    removed = []
    class Cleanup:
        def remove_tenant_media(self, tenant, paths):
            assert tenant == TENANT
            removed.extend(paths)
    assert process_storage_tasks(p.factory, storage=Cleanup()) == 1
    assert removed == [path]
    with p.factory() as db:
        assert db.get(Message, outcome.inbound_message_id) is None
        assert db.scalar(text('select count(*) from pedido_oracao_mensagem')) == 0


@pytest.mark.parametrize('function_name', ['prayer_message_readable', 'prayer_proposal_has_audio'])
def test_audio_reader_tenant_boundary_and_function_privileges(private_prayer, function_name):
    import json
    from app.db.models import AppUser, UserRole
    from tests.test_prayer_privacy_pg import scope
    from tests.test_prayer_requests_pg import FOREIGN, _SCHEMA
    p = private_prayer
    send(p, 'Quero iniciar pedido de oração')
    outcome, _ = audio(p)
    with p.factory.begin() as db:
        foreign_pastor = AppUser(igreja_id=FOREIGN, nome='Pastor sintético externo',
            email='foreign@example.test', clerk_user_id='foreign-pastor', status='ativo')
        db.add(foreign_pastor)
        db.flush()
        db.add(UserRole(igreja_id=FOREIGN, user_id=foreign_pastor.id, papel='pastor'))
    with p.factory() as db:
        fn = function_name + '(uuid,uuid)'
        flags = db.execute(text('select prosecdef,proconfig from pg_proc where oid=to_regprocedure(:fn)'), {'fn': fn}).one()
        assert flags.prosecdef
        assert flags.proconfig == [f'search_path=pg_catalog, {_SCHEMA}']
        for role in ('anon', 'service_role'):
            assert not db.scalar(text('select has_function_privilege(:role,:fn,\'EXECUTE\')'), {'role': role, 'fn': fn})
        assert db.scalar(text("select has_function_privilege('authenticated',:fn,'EXECUTE')"), {'fn': fn})
        assert not db.scalar(text("select exists(select 1 from pg_proc p, lateral aclexplode(p.proacl) a where p.oid=to_regprocedure(:fn) and a.grantee=0 and a.privilege_type='EXECUTE')"), {'fn': fn})
    with p.factory() as db:
        scope(db, p, 'pastor')
        assert db.scalar(text('select prayer_message_readable(:tenant,:mid)'), {'tenant': TENANT, 'mid': outcome.inbound_message_id})
        # A real active pastor of the other tenant cannot read this audio.
        db.execute(text("select set_config('app.tenant_igreja_id',:t,true), set_config('request.jwt.claims',:claims,true)"),
                   {'t': str(FOREIGN), 'claims': json.dumps({'sub': 'foreign-pastor'})})
        assert not db.scalar(text('select prayer_message_readable(:tenant,:mid)'), {'tenant': TENANT, 'mid': outcome.inbound_message_id})
        assert db.get(Message, outcome.inbound_message_id) is None


@pytest.mark.parametrize('has_audio', ['source', 'associated', None])
def test_legacy_request_visibility_sql_backend_and_api(private_prayer, has_audio):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from app.db.session import get_db
    from app.deps import get_current_user
    from app.prayer import service
    from app.prayer.router import router
    from tests.test_prayer_requests_pg import create_request, FOREIGN
    from tests.test_prayer_privacy_pg import scope
    p = private_prayer
    row = create_request(p, 'Pastores e meu líder')
    if has_audio:
        with p.factory.begin() as db:
            mid = (db.get(PrayerProposal, row.proposal_id).source_message_id
                   if has_audio == 'source' else row.confirmation_message_id)
            db.get(Message, mid).tipo = 'audio'
    for role in ('lider_celula', 'pastor', 'admin', 'operador'):
        allowed = role == 'pastor' or (role == 'lider_celula' and not has_audio)
        # No JWT: bypass the SQL reader policy to independently prove backend filtering.
        with p.factory() as db:
            db.execute(text("select set_config('app.tenant_igreja_id',:t,true)"), {'t': str(TENANT)})
            assert bool(service.list_requests(db, p.actors[role])) == allowed
            if allowed:
                assert service.get_request(db, p.actors[role], row.id).id == row.id
            else:
                with pytest.raises(HTTPException) as exc:
                    service.get_request(db, p.actors[role], row.id)
                assert exc.value.status_code == 404
        with p.factory() as db:
            scope(db, p, role)
            assert db.scalar(text('select count(*) from pedido_oracao where id=:id'), {'id': row.id}) == int(allowed)
        def dependency():
            with p.factory() as db:
                scope(db, p, role)
                yield db
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = dependency
        app.dependency_overrides[get_current_user] = lambda: p.actors[role]
        with TestClient(app) as client:
            result = client.get('/prayer-requests')
            assert result.status_code == 200
            assert bool(result.json()) == allowed
            assert client.get(f'/prayer-requests/{row.id}').status_code == (200 if allowed else 404)
            assert client.get('/prayer-requests/access').json()['allowed'] == allowed
    with p.factory() as db:
        scope(db, p, 'pastor')
        db.execute(text("select set_config('app.tenant_igreja_id',:t,true)"), {'t': str(FOREIGN)})
        assert db.scalar(text('select count(*) from pedido_oracao')) == 0


def test_foreign_pastor_cannot_read_legacy_audio_request(private_prayer, monkeypatch):
    import dataclasses
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.db.models import AppUser, UserRole
    from app.db.session import get_db
    from app.deps import get_current_user
    from app.prayer.router import router
    from tests.test_prayer_requests_pg import create_request, FOREIGN
    from tests.test_prayer_privacy_pg import scope
    p = private_prayer
    row = create_request(p, 'Pastores e meu líder')
    with p.factory.begin() as db:
        mid = db.get(PrayerProposal, row.proposal_id).source_message_id
        db.get(Message, mid).tipo = 'audio'
        actor = AppUser(igreja_id=FOREIGN, nome='Pastor externo sintético',
                       email='externo@example.test', clerk_user_id='foreign-request-pastor', status='ativo')
        db.add(actor)
        db.flush()
        db.add(UserRole(igreja_id=FOREIGN, user_id=actor.id, papel='pastor'))
        user = dataclasses.replace(p.actors['pastor'], app_user_id=str(actor.id),
                                   igreja_id=str(FOREIGN), clerk_user_id=actor.clerk_user_id)
    def dependency():
        import json
        with p.factory() as db:
            scope(db, p, 'pastor')
            db.execute(text("select set_config('app.tenant_igreja_id',:t,true), set_config('request.jwt.claims',:claims,true)"),
                       {'t': str(FOREIGN), 'claims': json.dumps({'sub': user.clerk_user_id})})
            yield db
    from contextlib import contextmanager
    with contextmanager(dependency)() as db:
        assert db.scalar(text('select count(*) from pedido_oracao where id=:id'), {'id': row.id}) == 0
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = dependency
    app.dependency_overrides[get_current_user] = lambda: user
    # Enable only the synthetic feature fence; tenant authorization stays real.
    monkeypatch.setenv('PRAYER_REQUEST_ENABLED_IGREJA_IDS', str(TENANT) + ',' + str(FOREIGN))
    with TestClient(app) as client:
        assert client.get('/prayer-requests').json() == []
        assert client.get(f'/prayer-requests/{row.id}').status_code == 404
