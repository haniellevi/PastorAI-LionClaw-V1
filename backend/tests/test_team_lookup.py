"""Focused contract and query-scope tests for GET /team/lookup."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.domain.work_queue import resolvable_tipos
from app.routers._common import PaginationParams
from app.routers.team import TeamLookupOut, TeamMemberOut, list_members_lookup


_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_OTHER_IGREJA_ID = "00000000-0000-0000-0000-000000000002"


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


def _compiled(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True})).lower()


def _where_sql(statement) -> str:
    where = getattr(statement, "whereclause", None)
    if where is None:
        return ""
    return str(where.compile(compile_kwargs={"literal_binds": True})).lower()


class _LookupSession:
    """Model tenant/revocation predicates and record the lookup hot path."""

    def __init__(self, users: list[SimpleNamespace]) -> None:
        self.statements = []
        self.users = users
        self.users_result: _UsersResult | None = None

    def _visible(self, statement) -> list[SimpleNamespace]:
        where = _where_sql(statement)
        rows = list(self.users)
        if "app_users.igreja_id" in where:
            rows = [user for user in rows if str(user.igreja_id) == _IGREJA_ID]
        if "app_users.status is null" in where:
            rows = [user for user in rows if user.status in {None, "ativo"}]
        if "user_roles.papel in" in where:
            rows = [
                user
                for user in rows
                if resolvable_tipos(role.papel for role in user.roles)
            ]
        return rows

    def execute(self, statement):
        self.statements.append(statement)
        rows = self._visible(statement)
        if "count(" in _compiled(statement):
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
    linked: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID(int=index),
        igreja_id=uuid.UUID(igreja_id),
        nome=nome,
        email=f"{nome.lower()}@segredo.com.br",
        status=status,
        pessoa_id=uuid.UUID(int=100 + index) if linked else None,
        roles=[SimpleNamespace(papel=role) for role in roles],
    )


def _current_user(*roles: str) -> CurrentUser:
    return CurrentUser(
        app_user_id="00000000-0000-0000-0000-0000000000a1",
        clerk_user_id="clerk_admin",
        igreja_id=_IGREJA_ID,
        email="admin@igreja.com.br",
        nome="Admin",
        roles=frozenset(roles or ("admin",)),
    )


def _lookup(session: _LookupSession, *, page=1, page_size=20):
    return list_members_lookup(
        pagination=PaginationParams(page=page, page_size=page_size),
        db=session,  # type: ignore[arg-type]
        current_user=_current_user(),
    )


def _assert_lookup_filter(statement) -> None:
    where = _where_sql(statement)
    assert "app_users.igreja_id" in where, where
    assert uuid.UUID(_IGREJA_ID).hex in where, where
    assert "app_users.status is null" in where, where
    assert "app_users.status = 'ativo'" in where, where
    assert "user_roles.igreja_id" in where, where
    assert "user_roles.papel in" in where, where


def test_lookup_count_and_rows_share_tenant_and_revocation_filter() -> None:
    session = _LookupSession(
        [
            _user(1, "Ana", "pastor"),
            _user(2, "Bruno", "pastor", status="revogado"),
            _user(3, "Carla", "admin", igreja_id=_OTHER_IGREJA_ID),
            _user(4, "Davi", "lider_celula", status="convidado"),
        ]
    )

    page = _lookup(session)

    assert page.total == 1
    assert [item.nome for item in page.items] == ["Ana"]
    assert page.items[0].email == ""
    assert len(session.statements) == 2
    count_where = _where_sql(session.statements[0])
    rows_where = _where_sql(session.statements[1])
    assert count_where == rows_where
    for statement in session.statements:
        _assert_lookup_filter(statement)
    assert session.users_result is not None
    assert session.users_result.unique_calls == 1


def test_lookup_derives_queue_types_from_accumulated_roles() -> None:
    session = _LookupSession(
        [
            _user(1, "Admin", "membro", "admin"),
            _user(2, "Lider", "membro", "lider_celula", "lider_consol"),
            _user(3, "Membro", "membro", linked=False),
        ]
    )

    page = _lookup(session)
    by_name = {item.nome: item for item in page.items}

    assert by_name["Admin"].tiposFila == [
        "atendimento",
        "conectar_celula",
        "fonovisita",
        "relatorio",
        "visitante",
    ]
    assert by_name["Lider"].papeis == ["lider_celula", "lider_consol", "membro"]
    assert by_name["Lider"].tiposFila == [
        "conectar_celula",
        "fonovisita",
        "relatorio",
        "visitante",
    ]
    assert "Membro" not in by_name
    assert all(item.email == "" for item in page.items)


def test_lookup_paginates_after_excluding_revoked_and_cross_tenant_users() -> None:
    session = _LookupSession(
        [
            _user(1, "Ana", "lider_celula"),
            _user(2, "Beto", "lider_celula"),
            _user(3, "Caio", "lider_celula"),
            _user(4, "Dora", "lider_celula"),
            _user(5, "Eva", "lider_celula"),
            _user(6, "Aarao", "admin", status="revogado"),
            _user(7, "Abel", "admin", igreja_id=_OTHER_IGREJA_ID),
        ]
    )

    page = _lookup(session, page=2, page_size=2)

    assert page.total == 5
    assert [item.nome for item in page.items] == ["Caio", "Dora"]
    assert page.page == 2
    assert page.pageSize == 2
    rows_statement = session.statements[1]
    assert rows_statement._limit_clause.value == 2
    assert rows_statement._offset_clause.value == 2
    assert "order by app_users.nome asc" in _compiled(rows_statement)


def test_lookup_excludes_more_than_one_page_of_ineligible_users_before_paging() -> None:
    users = [
        _user(index, f"Membro {index:03d}", "membro")
        for index in range(1, 202)
    ]
    users.append(_user(500, "Zacarias", "lider_celula"))
    session = _LookupSession(users)

    page = _lookup(session, page=1, page_size=200)

    assert page.total == 1
    assert [item.nome for item in page.items] == ["Zacarias"]
    assert all(
        "user_roles.papel in" in _where_sql(statement)
        for statement in session.statements
    )


def test_lookup_capability_field_does_not_change_full_team_projection() -> None:
    assert "tiposFila" in TeamLookupOut.model_fields
    assert "tiposFila" not in TeamMemberOut.model_fields


@pytest.mark.parametrize(
    "roles",
    [
        ("membro",),
        ("operador",),
        ("lider_celula",),
        ("lider_mult",),
    ],
)
def test_lookup_rejects_roles_without_queue_assign_capability(app, roles) -> None:
    session = _LookupSession([_user(1, "Ana", "pastor")])
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: _current_user(*roles)

    response = TestClient(app).get("/team/lookup")

    assert response.status_code == 403, response.text
    assert session.statements == []


@pytest.mark.parametrize(
    "roles",
    [
        ("admin",),
        ("pastor",),
        ("lider_g12",),
        ("lider_consol",),
        ("lider_celula", "lider_g12"),
    ],
)
def test_lookup_accepts_accumulated_queue_assign_capability(app, roles) -> None:
    session = _LookupSession([_user(1, "Ana", "lider_celula")])
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: _current_user(*roles)

    response = TestClient(app).get("/team/lookup")

    assert response.status_code == 200, response.text
    assert [item["nome"] for item in response.json()["items"]] == ["Ana"]
