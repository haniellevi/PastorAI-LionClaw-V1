"""Legacy DB doubles still exercise the real authentication dependency."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.db.models import AppUser
from app.deps import get_current_user
from tests.conftest import FakeClerk, FakeSession, make_app_user


class _LegacySession(FakeSession):
    def execute(self, statement, params=None):
        descriptions = getattr(statement, "column_descriptions", ())
        if descriptions and descriptions[0].get("entity") is AppUser:
            return SimpleNamespace(scalar_one_or_none=lambda: self.app_user)
        return super().execute(statement, params)


class _ProjectionSession(_LegacySession):
    def execute(self, statement, params=None):
        if len(getattr(statement, "column_descriptions", ())) > 1:
            return SimpleNamespace(scalar_one_or_none=lambda: None)
        return super().execute(statement, params)


def _authenticate(session, *, clerk=None):
    return get_current_user(
        authorization="Bearer synthetic",
        db=session,
        clerk=clerk or FakeClerk(),
    )


@pytest.mark.parametrize("session_type", [_LegacySession, _ProjectionSession])
def test_legacy_double_resolves_user_and_roles_then_rejects_revocation(session_type):
    session = session_type(app_user=make_app_user(), roles=["pastor"])
    del session.auth_session

    principal = _authenticate(session)

    assert principal.app_user_id == session.app_user.id
    assert principal.igreja_id == session.app_user.igreja_id
    assert principal.roles == frozenset({"pastor"})
    session.auth_session.revoked_at = datetime.now(timezone.utc)
    with pytest.raises(HTTPException) as error:
        _authenticate(session)
    assert error.value.status_code == 401


@pytest.mark.parametrize("field,value", [
    ("jti", "another-session"),
    ("app_user_id", "another-user"),
    ("igreja_id", "another-tenant"),
    ("revoked_at", datetime(2026, 1, 1, tzinfo=timezone.utc)),
])
def test_legacy_double_rejects_session_outside_active_join(field, value):
    session = _LegacySession(app_user=make_app_user(), roles=["admin"])
    setattr(session.auth_session, field, value)

    with pytest.raises(HTTPException) as error:
        _authenticate(session)

    assert error.value.status_code == 401


def test_legacy_double_rejects_unregistered_session():
    session = _LegacySession(app_user=make_app_user())
    session.auth_session = None

    with pytest.raises(HTTPException) as error:
        _authenticate(session)

    assert error.value.status_code == 401


def test_legacy_double_rejects_token_with_another_jti():
    session = _LegacySession(app_user=make_app_user())

    with pytest.raises(HTTPException) as error:
        _authenticate(session, clerk=FakeClerk(session_jti="unregistered-jti"))

    assert error.value.status_code == 401


def test_legacy_double_preserves_unlinked_user_refusal():
    session = _LegacySession()

    with pytest.raises(HTTPException) as error:
        _authenticate(session)

    assert error.value.status_code == 403
