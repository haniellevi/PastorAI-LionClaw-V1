"""Tenant and role scope for GET /descendencias."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.models import AppUser, Pessoa
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user

_AUTH = {"Authorization": "Bearer good"}
_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_OTHER_IGREJA_ID = "00000000-0000-0000-0000-000000000002"
_APP_USER_ID = "00000000-0000-0000-0000-0000000000a1"
_ACTOR_ID = "00000000-0000-0000-0000-0000000000b1"
_CHILD_ID = "00000000-0000-0000-0000-0000000000b2"
_GRANDCHILD_ID = "00000000-0000-0000-0000-0000000000b3"
_OTHER_ROOT_ID = "00000000-0000-0000-0000-0000000000b4"
_CROSS_TENANT_ID = "00000000-0000-0000-0000-0000000000c1"


class _Result:
    def __init__(self, *, scalar=None, rows=()) -> None:
        self._scalar = scalar
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._scalar

    def all(self):
        return list(self._rows)


def _where_sql(statement) -> str:
    where = getattr(statement, "whereclause", None)
    if where is None:
        return ""
    return str(where.compile(compile_kwargs={"literal_binds": True})).lower()


class TreeSession:
    def __init__(self, *, actor_pessoa_id: str | None, pessoas) -> None:
        self.actor_pessoa_id = (
            uuid.UUID(actor_pessoa_id) if actor_pessoa_id is not None else None
        )
        self.pessoas = list(pessoas)
        self.actor_lookups = 0
        self.pessoa_statements: list = []

    def execute(self, statement, params=None) -> _Result:
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entity = descriptions[0].get("entity") if descriptions else None
        name = descriptions[0].get("name") if descriptions else None

        if entity is AppUser and name == "pessoa_id":
            self.actor_lookups += 1
            return _Result(scalar=self.actor_pessoa_id)

        if entity is Pessoa:
            self.pessoa_statements.append(statement)
            pessoas = list(self.pessoas)
            if "pessoas.igreja_id" in _where_sql(statement):
                pessoas = [p for p in pessoas if str(p.igreja_id) == _IGREJA_ID]
            return _Result(
                rows=[(p.id, p.nome, p.tipo, p.lider_id) for p in pessoas]
            )

        return _Result()

    def close(self) -> None:  # pragma: no cover
        pass


def _pessoa(person_id: str, *, igreja_id=_IGREJA_ID, lider_id=None):
    return SimpleNamespace(
        id=uuid.UUID(person_id),
        igreja_id=uuid.UUID(igreja_id),
        nome=f"Pessoa {person_id[-2:]}",
        tipo="membro",
        lider_id=uuid.UUID(lider_id) if lider_id else None,
    )


def _tree_pessoas():
    return [
        _pessoa(_ACTOR_ID),
        _pessoa(_CHILD_ID, lider_id=_ACTOR_ID),
        _pessoa(_GRANDCHILD_ID, lider_id=_CHILD_ID),
        _pessoa(_OTHER_ROOT_ID),
        _pessoa(_CROSS_TENANT_ID, igreja_id=_OTHER_IGREJA_ID),
    ]


def _current_user(*roles: str) -> CurrentUser:
    return CurrentUser(
        app_user_id=_APP_USER_ID,
        clerk_user_id="clerk_tree_scope",
        igreja_id=_IGREJA_ID,
        email="tree@igrejapiloto.com.br",
        nome="Tree",
        roles=frozenset(roles),
    )


def _client(app, *, session: TreeSession, current_user: CurrentUser):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


def _assert_tenant_query(session: TreeSession) -> None:
    assert len(session.pessoa_statements) == 1
    where = _where_sql(session.pessoa_statements[0])
    assert "pessoas.igreja_id" in where, where
    assert uuid.UUID(_IGREJA_ID).hex in where, where


@pytest.mark.parametrize("wide_role", ["admin", "pastor", "lider_g12"])
def test_wide_roles_receive_tenant_forest_without_actor_lookup(app, wide_role) -> None:
    session = TreeSession(actor_pessoa_id=None, pessoas=_tree_pessoas())
    client = _client(app, session=session, current_user=_current_user(wide_role))

    response = client.get("/descendencias", headers=_AUTH)

    assert response.status_code == 200, response.text
    roots = response.json()
    assert {node["id"] for node in roots} == {_ACTOR_ID, _OTHER_ROOT_ID}
    actor = next(node for node in roots if node["id"] == _ACTOR_ID)
    assert actor["children"][0]["id"] == _CHILD_ID
    assert actor["children"][0]["children"][0]["id"] == _GRANDCHILD_ID
    assert _CROSS_TENANT_ID not in response.text
    assert session.actor_lookups == 0
    _assert_tenant_query(session)


def test_wide_accumulated_role_wins_and_may_override_root_inside_tenant(app) -> None:
    session = TreeSession(actor_pessoa_id=_ACTOR_ID, pessoas=_tree_pessoas())
    client = _client(
        app,
        session=session,
        current_user=_current_user("membro", "lider_celula", "pastor"),
    )

    response = client.get(
        f"/descendencias?rootId={_OTHER_ROOT_ID}", headers=_AUTH
    )

    assert response.status_code == 200, response.text
    assert [node["id"] for node in response.json()] == [_OTHER_ROOT_ID]
    assert session.actor_lookups == 0
    _assert_tenant_query(session)


@pytest.mark.parametrize(
    "roles", [("lider_celula",), ("membro", "lider_mult")]
)
def test_restricted_leaders_receive_descendants_from_own_root(app, roles) -> None:
    session = TreeSession(actor_pessoa_id=_ACTOR_ID, pessoas=_tree_pessoas())
    client = _client(app, session=session, current_user=_current_user(*roles))

    response = client.get("/descendencias", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert [node["id"] for node in response.json()] == [_ACTOR_ID]
    assert response.json()[0]["children"][0]["id"] == _CHILD_ID
    assert response.json()[0]["children"][0]["children"][0]["id"] == (
        _GRANDCHILD_ID
    )
    assert session.actor_lookups == 1
    _assert_tenant_query(session)


def test_restricted_leader_may_request_exactly_own_root(app) -> None:
    session = TreeSession(actor_pessoa_id=_ACTOR_ID, pessoas=_tree_pessoas())
    client = _client(
        app,
        session=session,
        current_user=_current_user("lider_celula"),
    )

    response = client.get(f"/descendencias?rootId={_ACTOR_ID}", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert response.json()[0]["id"] == _ACTOR_ID
    assert response.json()[0]["children"]


@pytest.mark.parametrize("roles", [("membro",), ("membro", "operador")])
def test_non_leader_restricted_role_receives_only_own_node(app, roles) -> None:
    session = TreeSession(actor_pessoa_id=_ACTOR_ID, pessoas=_tree_pessoas())
    client = _client(app, session=session, current_user=_current_user(*roles))

    response = client.get("/descendencias", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "id": _ACTOR_ID,
            "nome": f"Pessoa {_ACTOR_ID[-2:]}",
            "tipo": "membro",
            "children": [],
        }
    ]
    _assert_tenant_query(session)


@pytest.mark.parametrize("roles", [("lider_celula",), ("membro",)])
def test_restricted_root_override_to_other_person_is_generic_404_before_load(
    app, roles
) -> None:
    session = TreeSession(actor_pessoa_id=_ACTOR_ID, pessoas=_tree_pessoas())
    client = _client(app, session=session, current_user=_current_user(*roles))

    response = client.get(f"/descendencias?rootId={_CHILD_ID}", headers=_AUTH)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Raiz não encontrada"
    assert session.actor_lookups == 1
    assert session.pessoa_statements == []


def test_without_linked_pessoa_is_empty_or_404_without_loading_people(app) -> None:
    session = TreeSession(actor_pessoa_id=None, pessoas=_tree_pessoas())
    client = _client(
        app,
        session=session,
        current_user=_current_user("lider_celula"),
    )

    without_root = client.get("/descendencias", headers=_AUTH)
    with_root = client.get(f"/descendencias?rootId={_ACTOR_ID}", headers=_AUTH)

    assert without_root.status_code == 200, without_root.text
    assert without_root.json() == []
    assert with_root.status_code == 404, with_root.text
    assert with_root.json()["detail"] == "Raiz não encontrada"
    assert session.actor_lookups == 2
    assert session.pessoa_statements == []


def test_wide_root_from_other_tenant_is_generic_404_after_tenant_filter(app) -> None:
    session = TreeSession(actor_pessoa_id=None, pessoas=_tree_pessoas())
    client = _client(app, session=session, current_user=_current_user("pastor"))

    response = client.get(
        f"/descendencias?rootId={_CROSS_TENANT_ID}", headers=_AUTH
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Raiz não encontrada"
    assert _CROSS_TENANT_ID not in response.text
    assert session.actor_lookups == 0
    _assert_tenant_query(session)
