"""Real worker, PostgreSQL privacy policies and authenticated inbox API."""
import json
import uuid
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text, delete
from app.db.models import Conversation, Message, RolePermission, UserRole
from app.db.session import get_db
from app.deps import get_current_user
from app.prayer.models import PrayerProposal
from app.routers.conversations import router
from app.services.storage import get_storage
from tests.test_prayer_requests_pg import (  # noqa: F401
    prayer, msg_engine_fx, rls_database_url, TENANT, FOREIGN, _SCHEMA,
    send, inbound, create_request,
)
pytestmark = pytest.mark.rls_integration
MARKER = 'Mensagem pastoral protegida'
MIGRATION = Path(__file__).parents[1] / 'migrations/20261018_090000_prayer_message_privacy.sql'

@pytest.fixture
def private_prayer(prayer):
    return install_privacy(prayer)


def install_privacy(prayer):
    if MIGRATION.exists():
        sql = MIGRATION.read_text().replace('public.', _SCHEMA + '.').replace('pg_catalog, public', 'pg_catalog, ' + _SCHEMA).replace('pg_catalog,public', 'pg_catalog,' + _SCHEMA)
        with prayer.engine.begin() as conn:
            conn.exec_driver_sql("do $$ begin if not exists(select 1 from pg_roles where rolname='anon') then create role anon; end if; if not exists(select 1 from pg_roles where rolname='service_role') then create role service_role; end if; end $$")
            # The base fixture uses create_all (no production tenant policies).
            conn.exec_driver_sql(f"create policy tenant_fixture on {_SCHEMA}.messages using(igreja_id={_SCHEMA}.current_igreja_id()) with check(igreja_id={_SCHEMA}.current_igreja_id())")
            conn.exec_driver_sql(sql)
    return prayer

def install_inbox_schema(engine):
    """Real parent + privacy migration for legacy tests which now use the inbox.

    Their ORM baseline predates the mandatory projection. No authorization,
    projection or privacy policy is mocked to keep those regressions running.
    """
    from types import SimpleNamespace
    parent = MIGRATION.with_name('20261016_180000_prayer_requests.sql')
    sql = parent.read_text().replace('public.', _SCHEMA + '.').replace(
        'pg_catalog, public', 'pg_catalog, ' + _SCHEMA
    ).replace('pg_catalog,public', 'pg_catalog,' + _SCHEMA)
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)
    install_privacy(SimpleNamespace(engine=engine))


def scope(db, p, role):
    db.execute(text("select set_config('app.tenant_igreja_id',:t,true), set_config('request.jwt.claims',:claims,true), set_config('role','authenticated',true)"), {'t': str(TENANT), 'claims': json.dumps({'sub': p.actors[role].clerk_user_id})})

class Storage:
    def __init__(self):
        self.paths = []
    def sign(self, paths):
        self.paths.extend(paths)
        return {p: 'https://synthetic.invalid/' + p for p in paths}
    def remove(self, paths):
        self.paths.extend(paths)

def client_for(p, role, storage=None):
    user = p.actors[role]
    with p.factory.begin() as db:
        db.get(Conversation, p.conv).assumido_por = uuid.UUID(user.app_user_id)
        if not db.scalar(select(RolePermission).where(RolePermission.papel == role, RolePermission.tela == 'inbox')):
            db.add(RolePermission(igreja_id=TENANT, papel=role, tela='inbox'))
    def dependency():
        with p.factory() as db:
            scope(db, p, role)
            yield db
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = dependency
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_storage] = lambda: storage or Storage()
    return TestClient(app)

def test_raw_message_id_is_denied_to_admin(private_prayer):
    p = private_prayer
    row = create_request(p)
    with p.factory() as db:
        mid = db.get(PrayerProposal, row.proposal_id).source_message_id
    with p.factory() as db:
        scope(db, p, 'admin')
        assert db.scalar(select(Message).where(Message.id == mid)) is None

def test_inbound_is_protected_before_worker_and_after_cancel(private_prayer):
    p = private_prayer
    send(p, 'Quero iniciar pedido de oração')
    incoming = inbound(p, 'conteúdo pastoral sintético privado')
    with p.factory() as db:
        scope(db, p, 'admin')
        assert db.scalar(select(Message).where(Message.id == incoming.inbound_message_id)) is None
    send(p, 'NÃO')
    with client_for(p, 'admin') as client:
        result = client.get(f'/conversations/{p.conv}/messages').json()
        assert 'conteúdo pastoral' not in json.dumps(result)
        assert any(m['texto'] == MARKER for m in result['items'])

@pytest.mark.parametrize('role', ['admin', 'secretaria', 'operador', 'lider_consol', 'lider_celula'])
def test_inbox_masks_history_preview_and_media(private_prayer, role):
    p = private_prayer
    if role in {'lider_consol', 'secretaria'}:
        import dataclasses
        base = p.actors['operador']
        p.actors[role] = dataclasses.replace(base, roles=frozenset({role}))
        with p.factory.begin() as db:
            db.add(UserRole(igreja_id=TENANT, user_id=uuid.UUID(base.app_user_id), papel=role))
    row = create_request(p)
    with p.factory.begin() as db:
        mid = db.get(PrayerProposal, row.proposal_id).source_message_id
        msg = db.get(Message, mid)
        msg.tipo = 'arquivo'
        msg.media_path = 'synthetic/private-path'
        msg.media_nome = 'pastoral-private.txt'
        msg.media_mime = 'text/plain'
    storage = Storage()
    with client_for(p, role, storage) as client:
        history = client.get(f'/conversations/{p.conv}/messages')
        assert history.status_code == 200, history.text
        masked = next(m for m in history.json()['items'] if m['id'] == str(mid))
        assert masked['texto'] == MARKER
        assert masked['tipo'] == 'texto'
        assert all(masked[k] is None for k in ('mediaUrl','mediaMime','mediaNome'))
        assert storage.paths == []
        result = client.get('/conversations').json()
        assert result['items'][0]['ultimaMensagem'] == MARKER
        assert 'preciso' not in json.dumps(result).lower()
        response = client.get(f'/conversations/{p.conv}/messages/media-urls', params={'ids': str(mid)})
        assert response.status_code == 200
        assert response.json() == {'urls': {}}
        assert storage.paths == []

def test_pastor_and_only_confirmed_nominal_leader_can_read(private_prayer):
    p = private_prayer
    row = create_request(p, 'Pastores e meu líder')
    with p.factory() as db:
        mid = db.get(PrayerProposal, row.proposal_id).source_message_id
    for role in ['pastor', 'lider_celula']:
        with client_for(p, role) as client:
            msgs = client.get(f'/conversations/{p.conv}/messages').json()['items']
            assert next(m for m in msgs if m['id'] == str(mid))['texto'] != MARKER
    with p.factory.begin() as db:
        from app.db.models import CelulaMembro
        db.execute(delete(CelulaMembro).where(CelulaMembro.pessoa_id == p.person))
    with client_for(p, 'lider_celula') as client:
        msgs = client.get(f'/conversations/{p.conv}/messages').json()['items']
        assert next(m for m in msgs if m['id'] == str(mid))['texto'] == MARKER

def test_conversation_delete_cascades_private_association(private_prayer):
    p = private_prayer
    create_request(p)
    with p.factory.begin() as db:
        db.execute(text('alter table messages drop constraint if exists messages_conversation_id_fkey'))
    with client_for(p, 'admin') as client:
        assert client.delete(f'/conversations/{p.conv}').status_code == 204
    with p.factory() as db:
        assert db.scalar(text('select count(*) from pedido_oracao_mensagem')) == 0


def test_approved_person_erasure_does_not_reopen_history(private_prayer):
    p = private_prayer
    row = create_request(p)
    with p.factory() as db:
        mid = db.get(PrayerProposal, row.proposal_id).source_message_id
    with p.factory.begin() as db:
        scope(db, p, 'admin')
        db.execute(text('select delete_prayer_requests_for_person(:t,:p)'), {'t': str(TENANT), 'p': str(p.person)})
    with p.factory() as db:
        scope(db, p, 'admin')
        msg = db.scalar(select(Message).where(Message.id == mid))
        assert msg is None or msg.texto == MARKER


def test_admin_delete_cleans_protected_media_without_reading(private_prayer):
    p = private_prayer
    row = create_request(p)
    with p.factory.begin() as db:
        mid = db.get(PrayerProposal, row.proposal_id).source_message_id
        db.get(Message, mid).media_path = 'synthetic/to-delete'
    with p.factory.begin() as db:
        db.execute(text('alter table messages drop constraint if exists messages_conversation_id_fkey'))
    storage = Storage()
    with client_for(p, 'admin', storage) as client:
        assert client.delete(f'/conversations/{p.conv}').status_code == 204
    assert storage.paths == ['synthetic/to-delete']


def test_ingestion_opens_privacy_before_any_worker(private_prayer):
    import dataclasses
    from tests.test_messages_inbound_idempotency import _parsed
    from app.workers.queue_worker import ingest_message_event_ex
    p = private_prayer
    def ingest(body):
        parsed = dataclasses.replace(_parsed(provider_message_id='privacy-' + uuid.uuid4().hex, instance='prayer-test', telefone='5500000000000'), texto=body)
        with p.factory() as db:
            return dataclasses.replace(ingest_message_event_ex(db, parsed), claim_id="privacy-test-claim")
    first = ingest('Quero iniciar pedido de oração')
    second = ingest('conteúdo sigiloso sintético rápido')
    with p.factory() as db:
        scope(db, p, 'admin')
        assert db.scalar(select(Message).where(Message.id == second.inbound_message_id)) is None
    from app.workers.queue_worker import run_agent_for_message
    from tests.test_messages_inbound_idempotency import _ClassifiedEvolution
    run_agent_for_message(p.factory, first, evolution_client=_ClassifiedEvolution())
    run_agent_for_message(p.factory, second, evolution_client=_ClassifiedEvolution())
    with p.factory() as db:
        scope(db, p, 'admin')
        assert db.scalar(select(Message).where(Message.id == second.inbound_message_id)) is None


def test_expiry_and_closed_release_do_not_remove_privacy(private_prayer, monkeypatch):
    from app.prayer import policy, service
    import datetime as dt
    p = private_prayer
    send(p, 'Peço oração por mim: sigilo sintético mesmo expirado.')
    with p.factory.begin() as db:
        proposal = db.scalar(select(PrayerProposal))
        mid = proposal.source_message_id
        proposal.expires_at = service.now(db) - dt.timedelta(seconds=1)
    send(p, 'SIM')
    monkeypatch.setattr(policy, 'PRAYER_REQUEST_APPROVED_RELEASE_ID', None)
    for role, expected in [('admin', MARKER), ('pastor', 'Peço oração por mim: sigilo sintético mesmo expirado.')]:
        with client_for(p, role) as client:
            response = client.get(f'/conversations/{p.conv}/messages')
            assert response.headers['cache-control'] == 'private, no-store'
            assert next(m for m in response.json()['items'] if m['id'] == str(mid))['texto'] == expected


def test_leader_must_confirm_each_share_and_cannot_read_other_requests(private_prayer):
    p = private_prayer
    first = create_request(p)
    with p.factory() as db:
        first_mid = db.get(PrayerProposal, first.proposal_id).source_message_id
    send(p, 'Peço oração por mim: segundo pedido privado sintético.')
    send(p, 'Pastores e meu líder')
    with client_for(p, 'lider_celula') as client:
        result = client.get(f'/conversations/{p.conv}/messages').json()['items']
        assert all(m['texto'] == MARKER for m in result if m['id'] == str(first_mid) or 'segundo' in (m['texto'] or ''))
    send(p, 'SIM')
    with client_for(p, 'lider_celula') as client:
        result = client.get(f'/conversations/{p.conv}/messages').json()['items']
        assert next(m for m in result if m['id'] == str(first_mid))['texto'] == MARKER
        assert any('segundo pedido' in (m['texto'] or '') for m in result)


def test_revoke_active_pastor_role_hides_text_and_media(private_prayer):
    p = private_prayer
    row = create_request(p)
    with p.factory.begin() as db:
        mid = db.get(PrayerProposal, row.proposal_id).source_message_id
        db.get(Message, mid).media_path = 'synthetic/revoked-pastor'
        db.execute(delete(UserRole).where(UserRole.user_id == uuid.UUID(p.actors['pastor'].app_user_id)))
    storage = Storage()
    with client_for(p, 'pastor', storage) as client:
        result = client.get(f'/conversations/{p.conv}/messages').json()['items']
        assert next(m for m in result if m['id'] == str(mid))['texto'] == MARKER
        assert client.get(f'/conversations/{p.conv}/messages/media-urls', params={'ids': str(mid)}).json() == {'urls': {}}
        assert storage.paths == []


def test_two_churches_and_forged_composite_association(private_prayer):
    from app.db.models import AppUser
    from app.deps import CurrentUser
    from sqlalchemy.exc import DBAPIError
    p = private_prayer
    row = create_request(p)
    foreign_uid, foreign_conv = uuid.uuid4(), uuid.uuid4()
    with p.factory.begin() as db:
        db.add(AppUser(id=foreign_uid, igreja_id=FOREIGN, nome='Pastor B sintético', email='b@example.test', clerk_user_id='privacy-b', status='ativo'))
        db.add(Conversation(id=foreign_conv, igreja_id=FOREIGN, telefone='00000002'))
        db.flush()
        db.add(UserRole(igreja_id=FOREIGN, user_id=foreign_uid, papel='pastor'))
        mid = db.get(PrayerProposal, row.proposal_id).source_message_id
    with p.factory() as db:
        db.execute(text("select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claims','{\"sub\":\"privacy-b\"}',true),set_config('role','authenticated',true)"), {'t': str(FOREIGN)})
        assert db.scalar(select(Message).where(Message.id == mid)) is None
        assert db.execute(text('select * from prayer_inbox_messages(:c)'), {'c': str(p.conv)}).all() == []
    with pytest.raises(DBAPIError):
        with p.factory.begin() as db:
            db.execute(text('insert into pedido_oracao_mensagem values(:t,:c,:p,:m)'), {'t': str(FOREIGN),'c': str(foreign_conv), 'p': str(row.proposal_id), 'm': str(mid)})
    with p.factory() as db:
        scope(db, p, 'admin')
        assert db.scalar(text('select count(*) from pedido_oracao_mensagem')) == 0
    with pytest.raises(DBAPIError):
        with p.factory.begin() as db:
            scope(db, p, 'pastor')
            db.execute(text('delete from pedido_oracao_mensagem'))


def test_every_collected_correction_summary_and_authorization_is_bound(private_prayer):
    p = private_prayer
    send(p, 'Quero iniciar pedido de oração')
    send(p, 'Peço oração por mim: primeiro texto sintético.')
    send(p, 'Peço oração por mim: correção sintética.')
    send(p, 'Só pastores')
    send(p, 'SIM')
    with p.factory() as db:
        messages = db.scalars(select(Message).where(Message.conversation_id == p.conv, Message.provider_message_id != 'PRAYER-SEED')).all()
        bound = set(db.scalars(text('select message_id from pedido_oracao_mensagem')))
        assert messages
        assert all(m.id in bound for m in messages)


def test_authorized_pastor_media_and_cursor_pagination(private_prayer):
    p = private_prayer
    row = create_request(p)
    with p.factory.begin() as db:
        mid = db.get(PrayerProposal, row.proposal_id).source_message_id
        db.get(Message, mid).media_path = 'synthetic/pastor-media'
    storage = Storage()
    with client_for(p, 'pastor', storage) as client:
        assert str(mid) in client.get(f'/conversations/{p.conv}/messages/media-urls', params={'ids': str(mid)}).json()['urls']
    assert storage.paths == ['synthetic/pastor-media']
    with client_for(p, 'admin') as client:
        path = f'/conversations/{p.conv}/messages'
        result = client.get(path, params={'latest': True, 'pageSize': 2}).json()
        rows = result['items']
        cursor = result['nextBefore']
        while cursor:
            result = client.get(path, params={'before': cursor, 'pageSize': 2}).json()
            rows = result['items'] + rows
            cursor = result['nextBefore']
        assert len({m['id'] for m in rows}) == len(rows) == result['total']
        assert all(m['texto'] == MARKER for m in rows if m['id'] == str(mid))


def test_backfill_does_not_share_later_unrelated_history_with_leader(prayer):
    p = prayer
    create_request(p, 'Pastores e meu líder')
    later = inbound(p, 'assunto posterior sintético fora da oração')
    install_privacy(p)
    with client_for(p, 'lider_celula') as client:
        result = client.get(f'/conversations/{p.conv}/messages').json()['items']
        assert next(m for m in result if m['id'] == str(later.inbound_message_id))['texto'] == MARKER
        assert any('preciso de força' in (m['texto'] or '') for m in result)


def test_late_initial_worker_does_not_recreate_expired_source(private_prayer):
    import dataclasses
    import datetime as dt
    from tests.test_messages_inbound_idempotency import _parsed, _ClassifiedEvolution
    from app.workers.queue_worker import ingest_message_event_ex, run_agent_for_message
    from app.prayer import service
    p = private_prayer
    parsed = dataclasses.replace(_parsed(provider_message_id='privacy-delayed', instance='prayer-test', telefone='5500000000000'), texto='Quero iniciar pedido de oração')
    with p.factory() as db:
        outcome = dataclasses.replace(ingest_message_event_ex(db, parsed), claim_id='privacy-delayed-claim')
    with p.factory.begin() as db:
        proposal = db.scalar(select(PrayerProposal))
        proposal.expires_at = service.now(db) - dt.timedelta(seconds=1)
    run_agent_for_message(p.factory, outcome, evolution_client=_ClassifiedEvolution())
    with p.factory() as db:
        proposals = db.scalars(select(PrayerProposal)).all()
        assert len(proposals) == 1
        assert proposals[0].state == 'expired'


def test_private_table_and_helpers_have_minimal_privileges(private_prayer):
    p = private_prayer
    with p.factory() as db:
        flags = db.execute(text("select relrowsecurity,relforcerowsecurity from pg_class where oid='pedido_oracao_mensagem'::regclass")).one()
        assert flags == (True, True)
        for role in ('anon', 'service_role'):
            assert not db.scalar(text("select has_table_privilege(:role,'pedido_oracao_mensagem','SELECT')"), {'role': role})
            assert not db.scalar(text("select has_function_privilege(:role,'prayer_inbox_messages(uuid)','EXECUTE')"), {'role': role})
    with p.factory.begin() as db:
        scope(db, p, 'pastor')
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError):
            with db.begin_nested():
                db.execute(text('select delete_prayer_inbox_conversation(:t,:c)'), {'t': str(TENANT), 'c': str(p.conv)})


def test_media_after_expiry_is_not_added_to_the_old_collection(private_prayer, monkeypatch):
    import datetime as dt
    from app.prayer import policy, service
    p = private_prayer
    send(p, 'Peço oração por mim: coleta sintética com prazo.')
    with p.factory.begin() as db:
        proposal = db.scalar(select(PrayerProposal))
        protected_mid = proposal.source_message_id
        proposal.expires_at = service.now(db) - dt.timedelta(seconds=1)
    monkeypatch.setattr(policy, 'PRAYER_REQUEST_APPROVED_RELEASE_ID', None)
    after = inbound(p, 'mídia sintética fora do prazo')
    with p.factory.begin() as db:
        msg = db.get(Message, after.inbound_message_id)
        msg.tipo = 'audio'
        msg.media_path = 'synthetic/after-expiry'
    with client_for(p, 'admin') as client:
        rows = client.get(f'/conversations/{p.conv}/messages').json()['items']
        assert next(m for m in rows if m['id'] == str(protected_mid))['texto'] == MARKER
        assert next(m for m in rows if m['id'] == str(after.inbound_message_id))['texto'] == 'mídia sintética fora do prazo'


def test_reply_metadata_update_does_not_invert_handoff_locks(private_prayer):
    import threading
    from app.domain.agent_reply import AGENT_REPLY_PENDING
    from app.services.conversation_handoff import mark_conversation_for_handoff_locked
    p = private_prayer
    create_request(p)
    with p.factory.begin() as db:
        reply = db.scalars(select(Message).where(Message.conversation_id == p.conv, Message.direcao == 'out').order_by(Message.criado_em.desc())).first()
        mid = reply.id
        reply.agent_reply_state = AGENT_REPLY_PENDING
    conversation_locked = threading.Event()
    errors = []
    def handoff():
        try:
            with p.factory.begin() as db:
                db.execute(text("set local lock_timeout='3s'"))
                conv = db.scalar(select(Conversation).where(Conversation.id == p.conv).with_for_update())
                conversation_locked.set()
                mark_conversation_for_handoff_locked(db, conversation=conv)
        except Exception as exc:
            errors.append(type(exc).__name__)
    with p.factory.begin() as db:
        db.execute(text("set local lock_timeout='500ms'"))
        db.scalar(select(Message).where(Message.id == mid).with_for_update())
        thread = threading.Thread(target=handoff)
        thread.start()
        assert conversation_locked.wait(2)
        try:
            db.execute(text('update messages set agent_privilege_context=agent_privilege_context where id=:id'), {'id': str(mid)})
        except Exception as exc:
            errors.append(type(exc).__name__)
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert errors == []
