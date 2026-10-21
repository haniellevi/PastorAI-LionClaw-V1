"""Reenvio: isolamento explícito e RLS com e-mail/Clerk simulados."""
import os
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.routers.team import router
from app.services.brevo import get_brevo_client
from app.services.clerk import get_clerk_client
from tests.test_uv_turmas_pg import migrated_database, database, seeded, scoped, principal
from tests.conftest_rls import assert_disposable_database

pytestmark = pytest.mark.rls_integration


@pytest.fixture(scope='module')
def rls_database_url():
    url = os.environ['TEAM_RESEND_TEST_DATABASE_URL']
    assert_disposable_database(url)
    from sqlalchemy.engine import make_url
    parsed = make_url(url)
    assert parsed.host == '127.0.0.1' and parsed.database == 'uv_turmas_test'
    return url


@pytest.mark.parametrize('bypass_rls', [False, True])
@pytest.mark.parametrize('target_kind', ['same', 'other', 'active', 'revoked'])
def test_resend_isolation_and_state(database, seeded, bypass_rls, target_kind):
    v = seeded
    target = uuid4()
    tenant = v['other'] if target_kind == 'other' else v['t']
    state = {'active': 'ativo', 'revoked': 'revogado'}.get(target_kind, 'convidado')
    with database.begin() as c:
        c.execute(text("insert into app_users(id,igreja_id,nome,email,status) values(:u,:t,'Convite sintético','invite@example.test',:s)"), dict(u=target,t=tenant,s=state))
        c.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:t,:u,'membro')"), dict(t=tenant,u=target))
    sent, minted = [], []
    class Mailer:
        def send_invite(self, **kwargs):
            sent.append(kwargs)
    class Clerk:
        def mint_invite_token(self, subject):
            minted.append(subject)
            return 'synthetic-token'
    app = FastAPI()
    app.include_router(router)
    def db():
        with (Session(database) if bypass_rls else scoped(database, v['t'])) as s:
            yield s
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: principal(v)
    app.dependency_overrides[get_brevo_client] = Mailer
    app.dependency_overrides[get_clerk_client] = Clerk
    with TestClient(app) as client:
        response = client.post(f'/team/{target}/resend')
    expected = 200 if target_kind == 'same' else 404 if target_kind == 'other' else 409
    assert response.status_code == expected, response.text
    assert len(sent) == len(minted) == (1 if expected == 200 else 0)
    if expected == 200:
        assert minted == [str(target)]
        assert response.json()['usuarioId'] == str(target)
    with database.connect() as c:
        assert c.scalar(text('select status from app_users where id=:u'), dict(u=target)) == state
        assert c.scalar(text('select count(*) from app_users where id=:u'), dict(u=target)) == 1
        assert c.execute(text('select papel from user_roles where user_id=:u'), dict(u=target)).scalars().all() == ['membro']
