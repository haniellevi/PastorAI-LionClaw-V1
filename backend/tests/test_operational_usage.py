"""Synthetic PG proof for the bounded AI ledger projection (no new storage)."""
import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.deps import CurrentUser, get_current_user
from app.db.session import get_db
from tests.conftest_rls import rls_database_url, _provision_schema, IGREJA_A, IGREJA_B

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def db(rls_database_url):
    engine = create_engine(rls_database_url)
    _provision_schema(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql('''
        create table if not exists ai_usage_logs (
          id uuid primary key, igreja_id uuid not null, modelo text,
          tokens_in integer, tokens_out integer, custo numeric, ferramenta text,
          created_at timestamptz not null);
        alter table ai_usage_logs enable row level security;
        alter table ai_usage_logs force row level security;
        drop policy if exists tenant_isolation on ai_usage_logs;
        create policy tenant_isolation on ai_usage_logs for all
          using (igreja_id = current_igreja_id())
          with check (igreja_id = current_igreja_id());
        grant select on ai_usage_logs to authenticated;
        delete from ai_usage_logs;
        ''')
        now = dt.datetime.now(dt.UTC)
        for tenant, tokens, age in [(IGREJA_A, 10, 1), (IGREJA_B, 999, 1),
                                    (IGREJA_A, 777, 9), (IGREJA_A, 888, -1)]:
            conn.execute(text('''insert into ai_usage_logs values
              (:id, :tenant, 'SYNTHETIC_PRIVATE_MODEL', :tokens, null, null,
               'SYNTHETIC_PRIVATE_CONTENT', :created)'''),
              dict(id=uuid.uuid4(), tenant=tenant, tokens=tokens,
                   created=now - dt.timedelta(days=age)))
    with Session(engine) as session:
        session.execute(text('set local role authenticated'))
        session.execute(text("select set_config('app.tenant_igreja_id', :id, true)"), {'id': IGREJA_A})
        yield session
    engine.dispose()


def test_bounded_usage_isolates_and_omits_content(db):
    from app.services.operational_usage import operational_usage
    result = operational_usage(db, uuid.UUID(IGREJA_A))
    assert result.calls == 1
    assert result.tokens_in == 10
    assert result.tokens_out == 0
    assert result.cost == 0
    assert 'PRIVATE' not in result.model_dump_json()
    assert set(result.model_dump()) == {
        'window_start', 'window_end', 'calls', 'tokens_in', 'tokens_out', 'cost'}
    # Even an explicit B filter cannot bypass A's database context.
    assert operational_usage(db, uuid.UUID(IGREJA_B)).calls == 0


@pytest.mark.parametrize('roles,expected', [(['admin'], 200), (['pastor'], 403), ([], 403)])
def test_admin_endpoint(app, db, roles, expected):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        app_user_id=str(uuid.uuid4()), clerk_user_id='synthetic', igreja_id=IGREJA_A,
        email='synthetic@example.invalid', nome='Synthetic', roles=frozenset(roles))
    app.dependency_overrides[get_db] = lambda: db
    response = TestClient(app).get('/operations/ai-usage?igreja_id=' + IGREJA_B)
    assert response.status_code == expected
    if expected == 200:
        assert response.json()['calls'] == 1
        assert response.headers['cache-control'] == 'no-store'
        assert 'PRIVATE' not in response.text


def test_endpoint_requires_authentication(app, db):
    app.dependency_overrides[get_db] = lambda: db
    from app.services.clerk import get_clerk_client
    from tests.conftest import FakeClerk
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    assert TestClient(app).get('/operations/ai-usage').status_code == 401


def test_empty_window(db):
    from app.services.operational_usage import operational_usage
    result = operational_usage(db, uuid.uuid4())
    assert (result.calls, result.tokens_in, result.tokens_out, result.cost) == (0, 0, 0, 0)


def test_sums_and_half_open_window(db):
    from app.services.operational_usage import operational_usage
    # Fixture owner inserts synthetic ledger data before returning to tenant role.
    db.execute(text('reset role'))
    db.execute(text("""insert into ai_usage_logs values
      (:id, :tenant, null, 5, 7, 0.125, null, now() - interval '2 days')"""),
      dict(id=uuid.uuid4(), tenant=IGREJA_A))
    db.execute(text('set local role authenticated'))
    result = operational_usage(db, uuid.UUID(IGREJA_A))
    assert result.calls == 2
    assert result.tokens_in == 15
    assert result.tokens_out == 7
    assert str(result.cost) == '0.125'
    assert result.window_end - result.window_start == dt.timedelta(days=7)


def test_church_b_only_sees_its_own_ledger(db):
    from app.services.operational_usage import operational_usage
    db.execute(text("select set_config('app.tenant_igreja_id', :id, true)"), {'id': IGREJA_B})
    result = operational_usage(db, uuid.UUID(IGREJA_B))
    assert result.calls == 1
    assert result.tokens_in == 999
    assert operational_usage(db, uuid.UUID(IGREJA_A)).calls == 0
