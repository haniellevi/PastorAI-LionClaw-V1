"""Synthetic PG proof for the bounded AI ledger projection (no new storage)."""
import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import CurrentUser, get_current_user
from app.db.session import get_db
from tests.conftest_rls import IGREJA_A, IGREJA_B

from tests.operational_pg import operational_database, rls_database_url

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def db(operational_database):
    engine = operational_database
    with engine.begin() as conn:
        conn.exec_driver_sql("delete from igrejas")
        conn.execute(text("insert into igrejas(id,nome) values(:a,'Synthetic A'),(:b,'Synthetic B')"), dict(a=IGREJA_A,b=IGREJA_B))
        conn.execute(text("insert into app_users(igreja_id,clerk_user_id,nome,email,status) values(:t,'synthetic','Synthetic','synthetic@example.invalid','ativo')"), dict(t=IGREJA_A))
        # Match FakeClerk's fixed JTI so authenticated endpoint tests exercise
        # their role checks with a valid synthetic server-side session.
        conn.execute(text("""insert into auth_sessions
          (jti,igreja_id,app_user_id,issued_at,expires_at)
          select 'synthetic-session-jti', igreja_id, id, now(), now()+interval '1 hour'
          from app_users where clerk_user_id='synthetic' and igreja_id=:t"""), dict(t=IGREJA_A))
        conn.execute(text("insert into user_roles(igreja_id,user_id,papel) select igreja_id,id,'admin' from app_users where clerk_user_id='synthetic'"))
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
        session.execute(text("select set_config('request.jwt.claim.sub', 'synthetic', true)"))
        yield session



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


@pytest.mark.parametrize('roles,user_status,expected', [
    (['admin'], None, 200), (['admin'], 'ativo', 200),
    (['admin'], 'convidado', 403), (['admin'], 'revogado', 403),
    (['pastor'], 'ativo', 403), ([], 'ativo', 403),
])
def test_admin_endpoint(app, db, roles, user_status, expected):
    db.execute(text('reset role'))
    user_id = db.scalar(text("""update app_users set status=:status
        where clerk_user_id='synthetic' and igreja_id=:t returning id"""),
        dict(status=user_status, t=IGREJA_A))
    db.execute(text('set local role authenticated'))
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        app_user_id=str(user_id), clerk_user_id='synthetic', igreja_id=IGREJA_A,
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
