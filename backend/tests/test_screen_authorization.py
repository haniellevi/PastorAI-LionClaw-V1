"""Unit coverage of screen authorization using server-resolved roles."""
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.deps import CurrentUser, require_screen


def principal(role):
    return CurrentUser(
        app_user_id=str(uuid4()), clerk_user_id='synthetic',
        igreja_id=str(uuid4()), email='synthetic@example.test',
        nome='Pessoa sintética', roles=frozenset({role}),
    )


@pytest.mark.parametrize('role,allowed', [('membro', False), ('operador', True)])
def test_screen_uses_server_roles(role, allowed):
    db = Mock()
    db.execute.return_value.all.return_value = []
    user = principal(role)
    if allowed:
        assert require_screen('inbox')(db=db, current_user=user) == user
    else:
        with pytest.raises(HTTPException) as denied:
            require_screen('inbox')(db=db, current_user=user)
        assert denied.value.status_code == 403


def test_admin_keeps_implicit_access_without_matrix_read():
    db = Mock()
    user = principal('admin')
    assert require_screen('inbox')(db=db, current_user=user) == user
    db.execute.assert_not_called()
