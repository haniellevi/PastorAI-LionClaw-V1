"""Prove tenant role FK enforcement and login profile on migrated PostgreSQL."""
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.models import AppUser, Igreja, UserRole
from app.routers.auth import _login_profile
from tests.conftest_rls import rls_database_url  # noqa: F401
from tests.test_whatsapp_integrated_pg import migrated_factory  # noqa: F401

pytestmark = pytest.mark.rls_integration


def test_login_role_tenant_fk_and_legacy_profile(migrated_factory):
    own, other, user_id = uuid4(), uuid4(), uuid4()
    with migrated_factory.begin() as db:
        db.add_all([Igreja(id=own, nome='Igreja sintética A'),
                    Igreja(id=other, nome='Igreja sintética B')])
        db.flush()
        user = AppUser(id=user_id, igreja_id=own, nome='Pessoa sintética',
                       email='synthetic@example.test', status=None)
        db.add(user)
        db.flush()
        db.add(UserRole(igreja_id=own, user_id=user_id, papel='membro'))
        db.flush()
        # Raw SQL inside a savepoint proves the actual migrated constraint,
        # independent of ORM relationships; PostgreSQL cannot store this case.
        with pytest.raises(IntegrityError) as rejected:
            with db.begin_nested():
                db.execute(text('INSERT INTO user_roles (igreja_id, user_id, papel) '
                                'VALUES (:church, :user, :role)'),
                           {'church': other, 'user': user_id, 'role': 'admin'})
        assert rejected.value.orig.diag.constraint_name == 'user_roles_tenant_user_fkey'
        assert _login_profile(db, user).roles == ['membro']
