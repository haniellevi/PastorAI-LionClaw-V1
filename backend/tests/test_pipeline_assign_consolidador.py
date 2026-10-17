"""HTTP boundary checks; real assignment/tenant behavior is exercised in PG tests."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.deps import CurrentUser, get_current_user


class NoDatabase:
    def __getattr__(self, name):
        raise AssertionError(f'Autorização/validação deve recusar antes do banco: {name}')


@pytest.mark.parametrize('roles', [frozenset({'membro'}), frozenset({'lider_celula'}), frozenset({'operador'})])
def test_assign_rejects_non_coordinator_before_domain_access(app, roles):
    user = CurrentUser(app_user_id=str(uuid.uuid4()), igreja_id=str(uuid.uuid4()),
                       clerk_user_id='synthetic', email='synthetic@example.test',
                       nome='Sintético', roles=roles)
    app.dependency_overrides[get_db] = lambda: NoDatabase()
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        response = client.post('/pipeline/assign-consolidador', json={
            'consolidacaoId': str(uuid.uuid4()), 'responsavelId': str(uuid.uuid4()),
        })
    assert response.status_code == 403


def test_assignment_ids_are_validated_before_domain_access(app):
    user = CurrentUser(app_user_id=str(uuid.uuid4()), igreja_id=str(uuid.uuid4()),
                       clerk_user_id='synthetic', email='synthetic@example.test',
                       nome='Sintético', roles=frozenset({'pastor'}))
    app.dependency_overrides[get_db] = lambda: NoDatabase()
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        response = client.post('/pipeline/assign-consolidador', json={
            'consolidacaoId': 'inválido', 'responsavelId': str(uuid.uuid4()),
        })
    assert response.status_code == 422
