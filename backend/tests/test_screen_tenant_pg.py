"""Tenant permission grants must never authorize another church's role."""
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.db.models import Igreja, RolePermission
from app.deps import CurrentUser, require_screen
from tests.conftest_rls import rls_database_url  # noqa: F401
from tests.test_whatsapp_integrated_pg import migrated_factory  # noqa: F401

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def grants(migrated_factory):
    own, other = uuid4(), uuid4()
    with migrated_factory.begin() as db:
        db.add_all([Igreja(id=own, nome='Igreja sintética A'),
                    Igreja(id=other, nome='Igreja sintética B')])
        db.flush()
        db.add_all([
            RolePermission(igreja_id=own, papel='membro', tela='dashboard'),
            RolePermission(igreja_id=other, papel='membro', tela='inbox'),
        ])
    user = CurrentUser(app_user_id=str(uuid4()), clerk_user_id='synthetic',
                       igreja_id=str(own), email='member@example.test',
                       nome='Pessoa sintética', roles=frozenset({'membro'}))
    return user, other


@pytest.mark.parametrize('scoped', [False, True])
def test_foreign_grant_does_not_authorize_and_own_grant_does(
    migrated_factory, grants, scoped,
):
    user, other = grants
    with migrated_factory() as db:
        if scoped:
            db.execute(text('SET LOCAL ROLE authenticated'))
            db.execute(text("SELECT set_config('app.tenant_igreja_id', :tenant, true)"),
                       {'tenant': user.igreja_id})
        with pytest.raises(HTTPException) as denied:
            require_screen('inbox')(db=db, current_user=user)
        assert denied.value.status_code == 403
        assert require_screen('dashboard')(db=db, current_user=user) == user
    other_user = replace(user, igreja_id=str(other))
    with migrated_factory() as db:
        if scoped:
            db.execute(text('SET LOCAL ROLE authenticated'))
            db.execute(text("SELECT set_config('app.tenant_igreja_id', :tenant, true)"),
                       {'tenant': str(other)})
        assert require_screen('inbox')(db=db, current_user=other_user) == other_user
