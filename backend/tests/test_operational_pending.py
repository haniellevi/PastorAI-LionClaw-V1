"""Pending projection through real PG schema and tenant RLS, without payloads."""
import datetime as dt
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.test_operational_usage import db, operational_database, rls_database_url, IGREJA_A, IGREJA_B
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk

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


class SnapshotWebhookQueue:
    def __init__(
        self, items=(), *, dead_letters=(), complete=True,
        dead_letters_complete=True,
    ):
        self.items = list(items)
        self.dead_letters = list(dead_letters)
        self.complete = complete
        self.dead_letters_complete = dead_letters_complete

    def pending_metadata(self):
        return self.items, self.complete

    def dead_letter_metadata(self):
        return self.dead_letters, self.dead_letters_complete


def seed_outbox(db, now):
    db.execute(text('reset role'))
    people = {
        IGREJA_A: uuid.uuid4(),
        IGREJA_B: uuid.uuid4(),
    }
    for tenant, person_id in people.items():
        db.execute(
            text("insert into pessoas(id,igreja_id,nome,telefone) values(:id,:t,'Synthetic',:phone)"),
            dict(id=person_id, t=tenant, phone=f"+5500000000{len(tenant)}"),
        )

    def add(tenant, state, age, *, due_at=None, claimed_until=None):
        db.execute(
            text("""insert into notification_outbox
              (id,igreja_id,pessoa_id,origin_kind,origin_id,occurrence_at,
               origin_fingerprint,purpose,state,due_at,claimed_until,created_at,updated_at)
              values(:id,:tenant,:person,'event',:origin,:occurrence,:fingerprint,
                     'agenda_reminder',:state,:due,:claimed,:created,:created)"""),
            dict(
                id=uuid.uuid4(), tenant=tenant, person=people[tenant],
                origin=uuid.uuid4(), occurrence=now-dt.timedelta(seconds=age),
                fingerprint='a' * 64, state=state,
                due=due_at or now-dt.timedelta(seconds=age),
                claimed=claimed_until,
                created=now-dt.timedelta(seconds=age),
            ),
        )

    add(IGREJA_A, 'pendente', 40)
    add(IGREJA_A, 'pendente', 5000)
    add(IGREJA_A, 'pendente', 100000, due_at=now+dt.timedelta(seconds=3600))
    add(IGREJA_A, 'retry', 3600)
    add(IGREJA_A, 'em_envio', 72000, claimed_until=now-dt.timedelta(seconds=120))
    add(IGREJA_A, 'em_envio', 80000, claimed_until=now+dt.timedelta(seconds=60))
    add(IGREJA_B, 'pendente', 50000)
    db.execute(text('set local role authenticated'))
    return people


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


def test_outbox_counts_and_oldest_age_are_tenant_scoped(db):
    from app.services.operational_usage import operational_pending

    now = dt.datetime(2026, 10, 21, tzinfo=dt.UTC)
    seed_outbox(db, now)
    result = operational_pending(db, uuid.UUID(IGREJA_A), now=now)

    assert result.outbox_available is True
    assert result.notification_outbox['pending'].count == 3
    assert result.notification_outbox['pending'].oldest_age_seconds == 100000
    assert result.notification_outbox['pending'].overdue_count == 2
    assert result.notification_outbox['pending'].oldest_overdue_age_seconds == 5000
    assert result.notification_outbox['retryable'].count == 1
    assert result.notification_outbox['retryable'].oldest_age_seconds == 3600
    assert result.notification_outbox['expired_lease'].count == 1
    assert result.notification_outbox['expired_lease'].oldest_age_seconds == 72000
    assert result.notification_outbox['expired_lease'].oldest_overdue_age_seconds == 120
    assert result.webhook_dead_letters.count is None
    assert 'Synthetic' not in result.model_dump_json()

    # Explicitly asking for church B cannot cross the authenticated A context.
    other = operational_pending(db, uuid.UUID(IGREJA_B), now=now)
    assert other.outbox_available is False
    assert other.notification_outbox['pending'].count is None


def test_webhook_counts_and_age_are_resolved_by_tenant_without_payload(db):
    from app.services.operational_usage import operational_pending
    from app.workers.queue_worker import PendingWebhookMetadata

    now = dt.datetime(2026, 10, 21, tzinfo=dt.UTC)
    db.execute(text('reset role'))
    db.execute(text("""insert into whatsapp_connections
      (id,igreja_id,instance,status) values
      (:a,:tenant_a,'synthetic-instance-a','online'),
      (:b,:tenant_b,'synthetic-instance-b','online')"""),
      dict(a=uuid.uuid4(),b=uuid.uuid4(),tenant_a=IGREJA_A,tenant_b=IGREJA_B))
    db.execute(text('set local role authenticated'))
    queue = SnapshotWebhookQueue([
        PendingWebhookMetadata('claim-a-old', 'synthetic-instance-a', now.timestamp()-7200),
        PendingWebhookMetadata('claim-a-new', 'synthetic-instance-a', now.timestamp()-30),
        PendingWebhookMetadata('claim-b', 'synthetic-instance-b', now.timestamp()-90000),
    ])

    result = operational_pending(
        db, uuid.UUID(IGREJA_A), now=now, webhook_queue=queue
    )
    webhooks = result.webhooks
    assert result.webhooks_available is True
    assert webhooks.count == 2
    assert webhooks.oldest_age_seconds == 7200
    assert webhooks.age_complete is True
    assert result.webhook_dead_letters.count == 0
    assert result.webhook_dead_letters.overdue_count == 0
    assert 'claim-a-old' not in result.model_dump_json()
    assert 'synthetic-instance-a' not in result.model_dump_json()

    other = operational_pending(
        db, uuid.UUID(IGREJA_B), now=now, webhook_queue=queue
    )
    assert other.webhooks.count == 0


def test_dead_letter_webhooks_are_reported_separately_from_stuck_flow(db):
    from app.services.operational_usage import operational_pending
    from app.workers.queue_worker import PendingWebhookMetadata

    now = dt.datetime(2026, 10, 21, tzinfo=dt.UTC)
    db.execute(text('reset role'))
    db.execute(text("""insert into whatsapp_connections
      (id,igreja_id,instance,status) values
      (:a,:tenant_a,'synthetic-instance-a','online'),
      (:b,:tenant_b,'synthetic-instance-b','online')"""),
      dict(a=uuid.uuid4(),b=uuid.uuid4(),tenant_a=IGREJA_A,tenant_b=IGREJA_B))
    db.execute(text('set local role authenticated'))
    queue = SnapshotWebhookQueue(
        [PendingWebhookMetadata('claim-active', 'synthetic-instance-a', now.timestamp()-90)],
        dead_letters=[
            PendingWebhookMetadata('claim-dead-a', 'synthetic-instance-a', now.timestamp()-90000),
            PendingWebhookMetadata('claim-dead-b', 'synthetic-instance-b', now.timestamp()-180000),
        ],
    )

    result = operational_pending(
        db, uuid.UUID(IGREJA_A), now=now, webhook_queue=queue
    )

    assert result.webhooks_available is True
    assert result.webhooks.count == 1
    assert result.webhooks.oldest_age_seconds == 90
    assert result.webhooks.overdue_count == 1
    assert result.webhook_dead_letters.count == 1
    assert result.webhook_dead_letters.oldest_age_seconds == 90000
    assert result.webhook_dead_letters.overdue_count == 0
    assert result.webhook_dead_letters.oldest_overdue_age_seconds is None


def test_incomplete_dead_letter_snapshot_does_not_hide_active_webhooks(db):
    from app.services.operational_usage import operational_pending
    from app.workers.queue_worker import PendingWebhookMetadata

    now = dt.datetime(2026, 10, 21, tzinfo=dt.UTC)
    db.execute(text('reset role'))
    db.execute(text("insert into whatsapp_connections(id,igreja_id,instance,status) values(:id,:tenant,'synthetic-instance-a','online')"),
      dict(id=uuid.uuid4(),tenant=IGREJA_A))
    db.execute(text('set local role authenticated'))
    queue = SnapshotWebhookQueue(
        [PendingWebhookMetadata('claim-active', 'synthetic-instance-a', now.timestamp()-90)],
        dead_letters_complete=False,
    )

    result = operational_pending(
        db, uuid.UUID(IGREJA_A), now=now, webhook_queue=queue
    )

    assert result.webhooks_available is True
    assert result.webhooks.count == 1
    assert result.webhooks.overdue_count == 1
    assert result.webhook_dead_letters.count is None
    assert result.webhook_dead_letters.overdue_count is None


def test_legacy_webhooks_are_counted_with_unknown_age(db):
    from app.services.operational_usage import operational_pending
    from app.workers.queue_worker import PendingWebhookMetadata

    now = dt.datetime(2026, 10, 21, tzinfo=dt.UTC)
    db.execute(text('reset role'))
    db.execute(text("insert into whatsapp_connections(id,igreja_id,instance,status) values(:id,:tenant,'synthetic-legacy','online')"),
      dict(id=uuid.uuid4(),tenant=IGREJA_A))
    db.execute(text('set local role authenticated'))
    queue = SnapshotWebhookQueue([
        PendingWebhookMetadata('legacy-claim', 'synthetic-legacy', None),
    ])

    result = operational_pending(
        db, uuid.UUID(IGREJA_A), now=now, webhook_queue=queue
    )
    webhooks = result.webhooks
    assert result.webhooks_available is True
    assert webhooks.count == 1
    assert webhooks.oldest_age_seconds is None
    assert webhooks.age_complete is False
    assert webhooks.unaged_count == 1


def test_incomplete_webhook_snapshot_does_not_report_a_zero_count(db):
    from app.services.operational_usage import operational_pending

    now = dt.datetime(2026, 10, 21, tzinfo=dt.UTC)
    result = operational_pending(
        db,
        uuid.UUID(IGREJA_A),
        now=now,
        webhook_queue=SnapshotWebhookQueue(complete=False),
    )

    assert result.webhooks_available is False
    assert result.webhooks.count is None
    assert result.webhooks.overdue_count is None
    assert result.webhook_dead_letters.count is None


@pytest.mark.parametrize('roles,user_status,code', [
    (['admin'], None, 200), (['admin'], 'ativo', 200),
    (['admin'], 'convidado', 403), (['admin'], 'revogado', 403),
    (['pastor'], 'ativo', 403), ([], 'ativo', 403),
])
def test_pending_endpoint(app, db, roles, user_status, code):
    now = seed_tasks(db)
    seed_outbox(db, now)
    db.execute(text('reset role'))
    user_id = db.scalar(text("""update app_users set status=:status
        where clerk_user_id='synthetic' and igreja_id=:t returning id"""),
        dict(status=user_status, t=IGREJA_A))
    db.execute(text('delete from user_roles where igreja_id=:t and user_id=:id'),
               dict(t=IGREJA_A, id=user_id))
    for role in roles:
        db.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:t,:id,:role)"),
                   dict(t=IGREJA_A, id=user_id, role=role))
    db.execute(text('set local role authenticated'))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk(
        clerk_user_id='synthetic'
    )
    from app.routers.operations import get_pending_webhook_queue
    app.dependency_overrides[get_pending_webhook_queue] = lambda: SnapshotWebhookQueue()
    client = TestClient(app)
    r = client.get(
        '/operations/pending',
        params={'igreja_id':IGREJA_B,'stuck_after_seconds':1},
        headers={'Authorization': 'Bearer synthetic-session-token'},
    )
    assert r.status_code == code
    if code == 200:
        assert r.json()['sources']['tasks']['count'] == 4
        assert r.json()['outbox_available'] is True
        assert r.json()['notification_outbox']['pending']['count'] == 3
        assert r.json()['webhooks']['count'] == 0
        assert json.loads(db.scalar(
            text("select current_setting('request.jwt.claims', true)")
        )) == {'sub': 'synthetic'}
        assert r.headers['cache-control'] == 'no-store'
        assert 'PRIVATE' not in r.text
        for threshold in (0, -1, 2592001):
            assert client.get(
                '/operations/pending',
                params={'stuck_after_seconds':threshold},
                headers={'Authorization': 'Bearer synthetic-session-token'},
            ).status_code == 422


def test_pending_endpoint_reapplies_json_claim_after_intermediate_commit(app, db):
    now = seed_tasks(db)
    seed_outbox(db, now)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk(
        clerk_user_id='synthetic'
    )
    from app.routers.operations import get_pending_webhook_queue

    def commit_before_snapshot():
        db.commit()
        return SnapshotWebhookQueue()

    app.dependency_overrides[get_pending_webhook_queue] = commit_before_snapshot
    response = TestClient(app).get(
        '/operations/pending',
        headers={'Authorization': 'Bearer synthetic-session-token'},
    )

    assert response.status_code == 200, response.text
    assert response.json()['outbox_available'] is True
    assert response.json()['notification_outbox']['pending']['count'] == 3
    assert json.loads(db.scalar(
        text("select current_setting('request.jwt.claims', true)")
    )) == {'sub': 'synthetic'}


def test_pending_metrics_acl_and_admin_scope(db):
    function = (
        'public.operations_notification_outbox_pending_metrics(uuid,timestamptz)'
    )
    db.execute(text('reset role'))
    assert not db.scalar(
        text("select has_function_privilege('anon', :fn, 'EXECUTE')"),
        {'fn': function},
    )
    assert db.scalar(
        text("select has_function_privilege('authenticated', :fn, 'EXECUTE')"),
        {'fn': function},
    )
    assert not db.scalar(
        text("select has_function_privilege('service_role', :fn, 'EXECUTE')"),
        {'fn': function},
    )

    with pytest.raises(DBAPIError, match='permission denied for function') as denied:
        with db.begin_nested():
            db.execute(text('set local role anon'))
            db.execute(text("""select * from public.
              operations_notification_outbox_pending_metrics(:tenant, now())"""),
              {'tenant': IGREJA_A})
    denied_sqlstate = (
        getattr(denied.value.orig, 'sqlstate', None)
        or getattr(denied.value.orig, 'pgcode', None)
    )
    assert denied_sqlstate == '42501'

    db.execute(text("""insert into app_users
      (igreja_id,clerk_user_id,nome,email,status)
      values(:tenant,'synthetic-admin-b','Synthetic Admin B',
             'synthetic-admin-b@example.invalid','ativo')"""),
      {'tenant': IGREJA_B})
    db.execute(text("""insert into user_roles(igreja_id,user_id,papel)
      select igreja_id,id,'admin' from app_users
      where clerk_user_id='synthetic-admin-b' and igreja_id=:tenant"""),
      {'tenant': IGREJA_B})
    db.execute(text("""update app_users set status='revogado'
      where clerk_user_id='synthetic' and igreja_id=:tenant"""),
      {'tenant': IGREJA_A})

    def assert_not_authorized(clerk_sub, current_tenant):
        db.execute(text("select set_config('request.jwt.claims', :claims, true)"),
                   {'claims': json.dumps({'sub': clerk_sub})})
        db.execute(text("select set_config('app.tenant_igreja_id', :tenant, true)"),
                   {'tenant': current_tenant})
        db.execute(text('set local role authenticated'))
        with pytest.raises(DBAPIError, match='not authorized') as rejected:
            with db.begin_nested():
                db.execute(text("""select * from public.
                  operations_notification_outbox_pending_metrics(:tenant, now())"""),
                  {'tenant': IGREJA_A})
        rejected_sqlstate = (
            getattr(rejected.value.orig, 'sqlstate', None)
            or getattr(rejected.value.orig, 'pgcode', None)
        )
        assert rejected_sqlstate == '42501'
        db.execute(text('reset role'))

    assert_not_authorized('synthetic', IGREJA_A)
    assert_not_authorized('synthetic-admin-b', IGREJA_B)


def test_index_and_rls(db):
    assert db.scalar(text("select not rolbypassrls and not rolsuper from pg_roles where rolname=current_user"))
    assert db.scalar(text("select count(*) from pg_indexes where tablename='ai_usage_logs' and indexdef like '%(igreja_id, created_at)%'")) == 1
    assert db.scalar(text("select indisvalid from pg_index where indexrelid='ai_usage_logs_igreja_created_at_idx'::regclass"))
    assert db.scalar(text("select relrowsecurity and relforcerowsecurity from pg_class where oid='ai_usage_logs'::regclass"))


def test_partial_pending_indexes_are_valid_and_used_by_explain(db):
    indexes = {
        'notification_outbox_pending_igreja_created_idx': """select count(*), max(created_at)
          from public.notification_outbox
          where igreja_id='0a0a0a0a-0000-0000-0000-00000000000a'::uuid
            and state='pendente'""",
        'notification_outbox_retry_igreja_created_idx': """select count(*), max(created_at)
          from public.notification_outbox
          where igreja_id='0a0a0a0a-0000-0000-0000-00000000000a'::uuid
            and state='retry'""",
        'notification_outbox_lease_igreja_claimed_idx': """select count(*), max(created_at)
          from public.notification_outbox
          where igreja_id='0a0a0a0a-0000-0000-0000-00000000000a'::uuid
            and state='em_envio' and claimed_until is not null
            and claimed_until <= timestamptz '2026-10-21 00:00:00+00'""",
        'messages_pending_agent_igreja_created_idx': """select count(*), max(criado_em)
          from public.messages
          where igreja_id='0a0a0a0a-0000-0000-0000-00000000000a'::uuid
            and direcao='out' and autor='ia'
            and agent_reply_state in ('ia_reservada', 'ia_executando',
                                      'ia_pendente', 'ia_em_transporte')""",
        'work_queue_pending_igreja_created_idx': """select count(*), max(created_at)
          from public.work_queue_items
          where igreja_id='0a0a0a0a-0000-0000-0000-00000000000a'::uuid
            and (status is null or status in ('aberto', 'assumido'))""",
    }
    db.execute(text('reset role'))
    db.execute(text('set local enable_seqscan = off'))
    for index_name, query in indexes.items():
        assert db.scalar(text(
            "select indisvalid from pg_index where indexrelid=to_regclass(:name)"
        ), {'name': f'public.{index_name}'}) is True
        plan = db.execute(text(f'EXPLAIN (FORMAT JSON) {query}')).scalar_one()
        if isinstance(plan, str):
            plan = json.loads(plan)

        def find_index_names(node):
            if isinstance(node, dict):
                if 'Index Name' in node:
                    yield node['Index Name']
                for value in node.values():
                    yield from find_index_names(value)
            elif isinstance(node, list):
                for value in node:
                    yield from find_index_names(value)

        assert index_name in set(find_index_names(plan)), index_name


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
