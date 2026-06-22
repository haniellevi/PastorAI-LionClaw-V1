"""Shared test fixtures and lightweight fakes.

The Backend Core sprint is validated without a live database or Clerk tenant:
we override the DB session and Clerk client dependencies with in-memory fakes.
This keeps the auth/RBAC logic under test deterministic and offline.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db.models import AppUser
from app.services.clerk import ClerkAuthError, ClerkIdentity


# ---------------------------------------------------------------------------
# Fake SQLAlchemy session
# ---------------------------------------------------------------------------
class _FakeScalars:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return list(self._items)


class _FakeResult:
    def __init__(self, scalar=None, scalars_list=None) -> None:
        self._scalar = scalar
        self._scalars_list = scalars_list or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._scalars_list)


class FakeSession:
    """Minimal session: routes selects by entity, ignores set_config text."""

    def __init__(self, app_user=None, roles: list[str] | None = None) -> None:
        self.app_user = app_user
        self.roles = roles or []

    def execute(self, statement, params=None) -> _FakeResult:
        descriptions = getattr(statement, "column_descriptions", None)
        if not descriptions:
            # e.g. select set_config(...) text clause for RLS context.
            return _FakeResult()
        entity = descriptions[0].get("entity")
        if entity is AppUser:
            return _FakeResult(scalar=self.app_user)
        # Anything else here is the UserRole.papel projection.
        return _FakeResult(scalars_list=self.roles)

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


# ---------------------------------------------------------------------------
# Fake Clerk client
# ---------------------------------------------------------------------------
class FakeClerk:
    def __init__(
        self,
        *,
        clerk_user_id: str = "clerk_user_1",
        login_result: tuple[str, str] | None = None,
        raise_verify: bool = False,
        raise_login: bool = False,
    ) -> None:
        self._clerk_user_id = clerk_user_id
        self._login_result = login_result
        self._raise_verify = raise_verify
        self._raise_login = raise_login

    def verify_session_token(self, token: str) -> ClerkIdentity:
        if self._raise_verify:
            raise ClerkAuthError("invalid")
        return ClerkIdentity(
            clerk_user_id=self._clerk_user_id, claims={"sub": self._clerk_user_id}
        )

    def authenticate_password(self, email: str, password: str) -> tuple[str, str]:
        if self._raise_login:
            raise ClerkAuthError("invalid")
        return self._login_result or ("session_token_abc", self._clerk_user_id)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def make_app_user(
    *,
    clerk_user_id: str = "clerk_user_1",
    igreja_status: str = "ativa",
    email: str = "pastor@igrejapiloto.com",
    nome: str = "Pastor Piloto",
    status: str = "ativo",
):
    """Build an app_user stand-in compatible with the deps/router access."""
    igreja = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001", status=igreja_status
    )
    return SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000a1",
        igreja_id="00000000-0000-0000-0000-000000000001",
        clerk_user_id=clerk_user_id,
        email=email,
        nome=nome,
        status=status,
        igreja=igreja,
    )


@pytest.fixture
def app():
    from app.main import create_app

    return create_app()
