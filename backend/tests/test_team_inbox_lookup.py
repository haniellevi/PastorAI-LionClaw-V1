"""Contract, authorization and scope for GET /team/inbox-lookup."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.domain.conversations import can_access_inbox
from app.routers._common import PaginationParams
from app.routers.team import InboxLookupOut, list_inbox_transfer_targets

_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_OTHER_IGREJA_ID = "00000000-0000-0000-0000-000000000002"


class _CountResult:
    def __init__(self, total: int) -> None:
        self.total = total

    def scalar_one(self) -> int:
        return self.total


class _UsersResult:
    def __init__(self, users: list[SimpleNamespace]) -> None:
        self.users = users
        self.unique_calls = 0

    def unique(self) -> "_UsersResult":
        self.unique_calls += 1
        return self

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self.users))


class InboxLookupSession:
    def __init__(self, users: list[SimpleNamespace]) -> None:
        self.users = users
        self.statements: list = []
        self.users_result: _UsersResult | None = None

    def _eligible(self) -> list[SimpleNamespace]:
        return [
            user
            for user in self.users
            if str(user.igreja_id) == _IGREJA_ID
            and user.status in {None, "ativo"}
            and can_access_inbox(role.papel for role in user.roles)
        ]

    def execute(self, statement):
        self.statements.append(statement)
        rows = self._eligible()
        compiled = str(
            statement.compile(compile_kwargs={"literal_binds": True})
        ).lower()
        if "count(" in compiled:
            return _CountResult(len(rows))

        rows.sort(key=lambda user: user.nome)
        offset_clause = getattr(statement, "_offset_clause", None)
        limit_clause = getattr(statement, "_limit_clause", None)
        offset = offset_clause.value if offset_clause is not None else 0
        limit = limit_clause.value if limit_clause is not None else len(rows)
        self.users_result = _UsersResult(rows[offset : offset + limit])
        return self.users_result


def _user(
    index: int,
    nome: str,
    *roles: str,
    igreja_id: str = _IGREJA_ID,
    status: str | None = "ativo",
    chat_nome: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID(int=index),
        igreja_id=uuid.UUID(igreja_id),
        nome=nome,
        chat_nome=chat_nome,
        status=status,
        roles=[SimpleNamespace(papel=role) for role in roles],
    )


def _current_user(*roles: str) -> CurrentUser:
    return CurrentUser(
        app_user_id="00000000-0000-0000-0000-0000000000a1",
        clerk_user_id="clerk_inbox_lookup",
        igreja_id=_IGREJA_ID,
        email="inbox@igreja.com.br",
        nome="Inbox",
        roles=frozenset(roles),
    )


def _list(session: InboxLookupSession, *, page=1, page_size=20):
    return list_inbox_transfer_targets(
        pagination=PaginationParams(page=page, page_size=page_size),
        db=session,  # type: ignore[arg-type]
        current_user=_current_user("lider_celula"),
    )


def _where(statement) -> str:
    clause = getattr(statement, "whereclause", None)
    assert clause is not None
    return str(
        clause.compile(compile_kwargs={"literal_binds": True})
    ).lower()


def test_inbox_lookup_returns_only_active_eligible_same_tenant_users() -> None:
    session = InboxLookupSession(
        [
            _user(1, "Ana", "lider_celula", chat_nome="Pra. Ana"),
            _user(2, "Beto", "membro", "operador", status=None),
            _user(3, "Caio", "pastor", status="revogado"),
            _user(4, "Dora", "admin", status="convidado"),
            _user(5, "Eva", "admin", igreja_id=_OTHER_IGREJA_ID),
            _user(6, "Fábio", "membro"),
        ]
    )

    page = _list(session)

    assert page.total == 2
    assert [item.model_dump() for item in page.items] == [
        {
            "usuarioId": str(uuid.UUID(int=1)),
            "nome": "Pra. Ana",
            "papeis": ["lider_celula"],
        },
        {
            "usuarioId": str(uuid.UUID(int=2)),
            "nome": "Beto",
            "papeis": ["membro", "operador"],
        },
    ]
    assert set(InboxLookupOut.model_fields) == {"usuarioId", "nome", "papeis"}
    assert len(session.statements) == 2
    assert session.users_result is not None
    assert session.users_result.unique_calls == 1


def test_inbox_lookup_count_and_rows_share_tenant_status_and_role_scope() -> None:
    session = InboxLookupSession([_user(1, "Ana", "pastor")])

    _list(session)

    count_where = _where(session.statements[0])
    rows_where = _where(session.statements[1])
    assert count_where == rows_where
    for where in (count_where, rows_where):
        assert "app_users.igreja_id" in where
        assert uuid.UUID(_IGREJA_ID).hex in where
        assert "app_users.status is null" in where
        assert "app_users.status = 'ativo'" in where
        assert "user_roles.igreja_id" in where
        assert "user_roles.papel in" in where
        for role in (
            "admin",
            "pastor",
            "lider_g12",
            "lider_consol",
            "lider_celula",
            "operador",
        ):
            assert role in where


def test_inbox_lookup_paginates_after_eligibility_filter() -> None:
    session = InboxLookupSession(
        [
            _user(1, "Ana", "pastor"),
            _user(2, "Beto", "membro"),
            _user(3, "Caio", "operador"),
            _user(4, "Dora", "lider_g12"),
        ]
    )

    page = _list(session, page=2, page_size=1)

    assert page.total == 3
    assert [item.nome for item in page.items] == ["Caio"]
    rows_statement = session.statements[1]
    assert rows_statement._offset_clause.value == 1
    assert rows_statement._limit_clause.value == 1


@pytest.mark.parametrize(
    "roles",
    [
        ("admin",),
        ("pastor",),
        ("lider_g12",),
        ("lider_consol",),
        ("lider_celula",),
        ("operador",),
        ("membro", "operador"),
    ],
)
def test_inbox_lookup_accepts_canonical_inbox_roles(app, roles) -> None:
    session = InboxLookupSession([_user(1, "Ana", "pastor")])
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: _current_user(*roles)

    response = TestClient(app).get("/team/inbox-lookup")

    assert response.status_code == 200, response.text


@pytest.mark.parametrize("roles", [("membro",), ("lider_mult",), ()])
def test_inbox_lookup_rejects_non_inbox_roles_without_query(app, roles) -> None:
    session = InboxLookupSession([_user(1, "Ana", "pastor")])
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: _current_user(*roles)

    response = TestClient(app).get("/team/inbox-lookup")

    assert response.status_code == 403, response.text
    assert session.statements == []
