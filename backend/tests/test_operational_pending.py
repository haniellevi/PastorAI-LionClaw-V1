"""Pending projection through real PG schema and tenant RLS, without payloads."""
import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.test_operational_usage import db, operational_database, rls_database_url, IGREJA_A, IGREJA_B
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user

pytestmark = pytest.mark.rls_integration


def seed_tasks(db):
    now = dt.datetime(2026, 10, 21, tzinfo=dt.UTC)
    db.execute(text('reset role'))
    for tenant, seconds, status in [(IGREJA_A, 0, None), (IGREJA_A, 300, 'aberto'),
            (IGREJA_A, 3600, 'assumido'), (IGREJA_A, 86400, 'aberto'),
            (IGREJA_A, 999999, 'resolvido'), (IGREJA_B, 999999, 'aberto')]:
        db.execute(text('insert into work_queue_items(id,igreja_id,tipo,titulo,contexto,status,created_at) values(:id,:t,\'atendimento\',\'PRIVATE\',\'PRIVATE\',:s,:at)'),
            dict(id=uuid.uuid4(),t=tenant,s=status,at=now-dt.timedelta(seconds=seconds)))
    db.execute(text('set local role authenticated'))
    return now


def test_ages_boundaries_and_rls(db):
    from app.services.operational_usage import operational_pending
    now = seed_tasks(db)
    result = operational_pending(db, uuid.UUID(IGREJA_A), stuck_after_seconds=3600, now=now)
    tasks = result.sources['tasks']
    assert tasks.count == 4
    assert tasks.oldest_age_seconds == 86400
    assert tasks.age_buckets == {'under_5m': 1, '5m_to_1h': 1, '1h_to_24h': 1, '24h_plus': 1}
    assert tasks.stuck_count == 1  # strictly above the threshold
    assert tasks.stuck_oldest_age_seconds == 86400
    assert 'PRIVATE' not in result.model_dump_json()
    assert operational_pending(db, uuid.UUID(IGREJA_B), now=now).sources['tasks'].count == 0
    db.execute(text("select set_config('app.tenant_igreja_id', :id, true)"), {'id': IGREJA_B})
    assert operational_pending(db, uuid.UUID(IGREJA_B), now=now).sources['tasks'].count == 1
    assert result.webhooks_available is False


@pytest.mark.parametrize('roles,user_status,code', [
    (['admin'], None, 403), (['admin'], 'ativo', 200),
    (['admin'], 'convidado', 403), (['admin'], 'revogado', 403),
    (['pastor'], 'ativo', 403), ([], 'ativo', 403),
])
def test_pending_endpoint(app, db, roles, user_status, code):
    seed_tasks(db)
    db.execute(text('reset role'))
    user_id = db.scalar(text("""update app_users set status=:status
        where clerk_user_id='synthetic' and igreja_id=:t returning id"""),
        dict(status=user_status, t=IGREJA_A))
    db.execute(text('set local role authenticated'))
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        app_user_id=str(user_id),clerk_user_id='synthetic',igreja_id=IGREJA_A,
        email='synthetic@example.invalid',nome='Synthetic',roles=frozenset(roles))
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    r = client.get('/operations/pending', params={'igreja_id':IGREJA_B,'stuck_after_seconds':1})
    assert r.status_code == code
    if code == 200:
        assert r.json()['sources']['tasks']['count'] == 4
        assert r.headers['cache-control'] == 'no-store'
        assert 'PRIVATE' not in r.text
        for threshold in (0, -1, 2592001):
            assert client.get('/operations/pending',params={'stuck_after_seconds':threshold}).status_code == 422


def test_index_and_rls(db):
    assert db.scalar(text("select not rolbypassrls and not rolsuper from pg_roles where rolname=current_user"))
    assert db.scalar(text("select count(*) from pg_indexes where tablename='ai_usage_logs' and indexdef like '%(igreja_id, created_at)%'")) == 1
    assert db.scalar(text("select indisvalid from pg_index where indexrelid='ai_usage_logs_igreja_created_at_idx'::regclass"))
    assert db.scalar(text("select relrowsecurity and relforcerowsecurity from pg_class where oid='ai_usage_logs'::regclass"))


def test_message_states_empty_and_future(db):
    from app.services.operational_usage import operational_pending
    now = seed_tasks(db)
    db.execute(text('reset role'))
    for tenant in (IGREJA_A, IGREJA_B):
        conversation = uuid.uuid4()
        db.execute(text("insert into conversations(id,igreja_id,telefone) values(:id,:t,'550000000000')"),dict(id=conversation,t=tenant))
        for state, age in [('ia_reservada',1),('ia_executando',400),('ia_pendente',4000),
                           ('ia_em_transporte',90000),('ia',999999),('ia_ambigua',999999),
                           ('ia_falhou',999999),('ia_suprimida',999999),('ia_pendente',-1)]:
            db.execute(text("insert into messages(igreja_id,conversation_id,direcao,autor,texto,agent_reply_state,criado_em) values(:t,:c,'out','ia','PRIVATE',:s,:at)"),dict(t=tenant,c=conversation,s=state,at=now-dt.timedelta(seconds=age)))
    db.execute(text('set local role authenticated'))
    result = operational_pending(db,uuid.UUID(IGREJA_A),now=now)
    msgs = result.sources['messages']
    assert msgs.count == 5
    assert msgs.age_buckets == {'under_5m':2,'5m_to_1h':1,'1h_to_24h':1,'24h_plus':1}
    assert msgs.stuck_count == 2
    assert msgs.oldest_age_seconds == 90000
    assert 'PRIVATE' not in result.model_dump_json()
    assert operational_pending(db, uuid.UUID(IGREJA_B),now=now).sources['messages'].count == 0
    empty = operational_pending(db, uuid.uuid4(),now=now)
    for source in empty.sources.values():
        assert source.count == source.stuck_count == 0
        assert source.oldest_age_seconds is source.stuck_oldest_age_seconds is None
        assert sum(source.age_buckets.values()) == 0


def test_pending_requires_authentication(app, db):
    from app.services.clerk import get_clerk_client
    from tests.conftest import FakeClerk
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    assert TestClient(app).get('/operations/pending').status_code == 401


def test_projection_needs_no_content_column_privileges(db):
    """The aggregate still works when tenant SELECT on payloads is revoked."""
    from app.services.operational_usage import operational_pending
    now = seed_tasks(db)
    db.execute(text('reset role'))
    db.execute(text('revoke select on messages, work_queue_items from authenticated'))
    db.execute(text('grant select(igreja_id, criado_em, direcao, autor, agent_reply_state, id) on messages to authenticated'))
    db.execute(text('grant select(igreja_id, created_at, status) on work_queue_items to authenticated'))
    db.execute(text('set local role authenticated'))
    result = operational_pending(db,uuid.UUID(IGREJA_A),now=now)
    assert result.sources['tasks'].count == 4
    assert not db.scalar(text("select has_column_privilege(current_user, 'messages', 'texto', 'SELECT')"))
    assert not db.scalar(text("select has_column_privilege(current_user, 'work_queue_items', 'contexto', 'SELECT')"))
