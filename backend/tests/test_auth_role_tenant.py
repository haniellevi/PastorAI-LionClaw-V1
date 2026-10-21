"""Execute role queries against synthetic rows, including corrupt legacy data.

The composite FK user_roles_tenant_user_fkey prevents the foreign-tenant row
in migrated PostgreSQL. This isolated SQLite table deliberately omits FKs to
prove the query's defense in depth even in the presence of such a row.
"""
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import UserRole
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user


@pytest.mark.parametrize('endpoint', ['/auth/login', '/auth/me'])
@pytest.mark.parametrize('status', ['ativo', None])
def test_auth_excludes_foreign_church_role(app, endpoint, status):
    user = make_app_user(status=status)
    user.id = UUID(user.id)
    user.igreja_id = UUID(user.igreja_id)
    user.igreja.dono_id = user.id
    engine = create_engine('sqlite://', poolclass=StaticPool,
                           connect_args={'check_same_thread': False})
    try:
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE user_roles (user_id CHAR(32), igreja_id CHAR(32), papel TEXT)'))
            conn.execute(text('INSERT INTO user_roles VALUES (:user, :church, :role)'), [
                {'user': user.id.hex, 'church': user.igreja_id.hex, 'role': 'membro'},
                {'user': user.id.hex, 'church': uuid4().hex, 'role': 'admin'},
            ])
        with Session(engine) as role_db:
            class RoleSession(FakeSession):
                def execute(self, statement, *args, **kwargs):
                    if any(d.get('entity') is UserRole for d in getattr(statement, 'column_descriptions', [])):
                        return role_db.execute(statement, *args, **kwargs)
                    return super().execute(statement, *args, **kwargs)

            session = RoleSession(app_user=user)
            # Exercise the legacy fallback rather than the joinedload collection.
            del user.roles
            app.dependency_overrides[get_db] = lambda: session
            app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
            with TestClient(app) as client:
                if endpoint == '/auth/login':
                    response = client.post(endpoint, json={'email': user.email, 'password': 'synthetic'})
                else:
                    response = client.get(endpoint, headers={'Authorization': 'Bearer good'})
            assert response.status_code == 200, response.text
            assert response.json()['roles'] == ['membro']
    finally:
        engine.dispose()
