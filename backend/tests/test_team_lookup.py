"""Focused contract and query-count tests for GET /team/lookup."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.deps import CurrentUser
from app.routers._common import PaginationParams
from app.routers.team import list_members_lookup


class _CountResult:
    def __init__(self, total: int) -> None:
        self._total = total

    def scalar_one(self) -> int:
        return self._total


class _UsersResult:
    def __init__(self, users: list[SimpleNamespace]) -> None:
        self._users = users
        self.unique_calls = 0

    def unique(self) -> "_UsersResult":
        self.unique_calls += 1
        return self

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._users))


class _LookupSession:
    """Serve count + paginated users and record the complete hot-path SQL."""

    def __init__(self, users: list[SimpleNamespace], total: int) -> None:
        self.statements = []
        self.users_result = _UsersResult(users)
        self._total = total

    def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _CountResult(self._total)
        if len(self.statements) == 2:
            return self.users_result
        raise AssertionError("team lookup executou consulta adicional inesperada")


def _current_user() -> CurrentUser:
    return CurrentUser(
        app_user_id="00000000-0000-0000-0000-0000000000a1",
        clerk_user_id="clerk_admin",
        igreja_id="00000000-0000-0000-0000-000000000001",
        email="admin@igreja.com.br",
        nome="Admin",
        roles=frozenset({"admin"}),
    )


def test_lookup_preserves_payload_and_loads_roles_in_two_queries() -> None:
    pessoa_id = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
    users = [
        SimpleNamespace(
            id=uuid.UUID("00000000-0000-0000-0000-0000000000a1"),
            nome="Ana",
            email="ana@igreja.com.br",
            status="ativo",
            pessoa_id=pessoa_id,
            roles=[SimpleNamespace(papel="pastor"), SimpleNamespace(papel="admin")],
        ),
        SimpleNamespace(
            id=uuid.UUID("00000000-0000-0000-0000-0000000000a2"),
            nome="Bruno",
            email="bruno@igreja.com.br",
            status="revogado",
            pessoa_id=None,
            roles=[],
        ),
    ]
    session = _LookupSession(users, total=7)

    page = list_members_lookup(
        pagination=PaginationParams(page=2, page_size=2),
        db=session,  # type: ignore[arg-type]
        current_user=_current_user(),
    )

    assert page.model_dump() == {
        "items": [
            {
                "usuarioId": "00000000-0000-0000-0000-0000000000a1",
                "nome": "Ana",
                "email": "",
                "status": None,
                "papeis": ["admin", "pastor"],
                "pessoaId": str(pessoa_id),
            },
            {
                "usuarioId": "00000000-0000-0000-0000-0000000000a2",
                "nome": "Bruno",
                "email": "",
                "status": None,
                "papeis": [],
                "pessoaId": None,
            },
        ],
        "page": 2,
        "pageSize": 2,
        "total": 7,
    }

    assert len(session.statements) == 2
    users_statement = session.statements[1]
    users_sql = str(users_statement).lower()
    assert "left outer join user_roles" in users_sql
    assert "order by app_users.nome asc" in users_sql
    assert users_statement._limit_clause.value == 2
    assert users_statement._offset_clause.value == 2
    assert session.users_result.unique_calls == 1
