"""Row-level Pessoas scope for GET/POST /contacts.

The offline router suite does not execute SQL predicates. These tests therefore
combine HTTP behaviour with inspection of the real SQLAlchemy statements built
for count, rows and detail, including the canonical cell-membership and assigned
conversation exceptions.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.db.models import AppUser, Celula, Pessoa
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user


_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
_APP_USER = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_ACTOR = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
_TARGET = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
_OTHER_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000002")


class _Result:
    def __init__(self, *, scalar=None, rows=()) -> None:
        self._scalar = scalar
        self._rows = list(rows)

    def scalar_one(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))


class _ScopeSession:
    """Capture statements while returning deterministic endpoint fixtures."""

    def __init__(
        self,
        *,
        actor_pessoa_id: uuid.UUID | None = _ACTOR,
        people=(),
        detail_person=None,
        total: int | None = None,
        detail: bool = False,
    ) -> None:
        self.actor_pessoa_id = actor_pessoa_id
        self.people = list(people)
        self.detail_person = detail_person
        self.total = len(self.people) if total is None else total
        self.detail = detail
        self.statements: list = []
        self.added: list = []
        self.commits = 0
        self.flushes = 0

    def execute(self, statement, params=None) -> _Result:
        self.statements.append(statement)
        sql = str(statement).lower()
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        first = descriptions[0] if descriptions else {}
        entity = first.get("entity")

        if entity is AppUser and first.get("name") == "pessoa_id":
            return _Result(scalar=self.actor_pessoa_id)
        if "count(" in sql and "pessoas" in sql:
            return _Result(scalar=self.total)
        if entity is Pessoa:
            if self.detail:
                return _Result(scalar=self.detail_person)
            return _Result(rows=self.people)
        if entity is Celula:
            return _Result(scalar=None, rows=())
        return _Result()

    def add(self, value) -> None:
        self.added.append(value)

    def flush(self) -> None:
        self.flushes += 1

    def refresh(self, value) -> None:  # pragma: no cover - denied/dedupe paths
        pass

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:  # pragma: no cover
        pass

    def close(self) -> None:  # pragma: no cover
        pass


def _user(*roles: str) -> CurrentUser:
    return CurrentUser(
        app_user_id=str(_APP_USER),
        clerk_user_id="clerk-scope",
        igreja_id=str(_TENANT),
        email="scope@example.com",
        nome="Scope",
        roles=frozenset(roles),
    )


def _person(pessoa_id: uuid.UUID, *, telefone: str = "11999990000") -> Pessoa:
    return Pessoa(
        id=pessoa_id,
        igreja_id=_TENANT,
        nome="Pessoa visível",
        telefone=telefone,
        email=None,
        genero=None,
        faixa_etaria=None,
        endereco=None,
        tipo="contato",
        etapa=None,
        subetapa=None,
        presencas_celula=0,
        aceitou_jesus=False,
        acompanhamento=None,
        origem=None,
        primeiro_contato=None,
        celula_id=None,
        lider_id=None,
        consentimento=False,
        optout=False,
        apto_lider=False,
        sem_interesse=False,
        sem_interesse_motivo=None,
        arquivada_em=None,
        created_at=dt.datetime(2026, 8, 10, tzinfo=dt.UTC),
    )


def _client(app, *, session: _ScopeSession, user: CurrentUser) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).replace("\n", " ")


def _people_statements(session: _ScopeSession) -> list:
    return [
        statement
        for statement in session.statements
        if "pessoas" in str(statement).lower()
        and "app_users" not in str(statement).lower()
    ]


@pytest.mark.parametrize(
    "roles",
    [
        ("admin",),
        ("pastor",),
        ("lider_g12",),
        ("lider_consol",),
        ("lider_celula", "operador", "lider_consol"),
    ],
)
def test_list_tenant_wide_roles_keep_full_tenant_scope(app, roles) -> None:
    session = _ScopeSession(actor_pessoa_id=None, total=0)
    response = _client(app, session=session, user=_user(*roles)).get("/contacts")

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    # Wide access wins before resolving app_user.pessoa_id, including when
    # accumulated with lider_celula.
    assert not any("app_users.pessoa_id" in str(s) for s in session.statements)
    statements = _people_statements(session)
    assert len(statements) == 2  # count + paginated rows
    for statement in statements:
        sql = _sql(statement)
        assert "pessoas.igreja_id" in sql
        assert str(_TENANT) in sql
        assert "celula_membro" not in sql
        assert "conversations" not in sql


def test_list_cell_leader_unions_own_active_cell_and_assigned_conversation(
    app,
) -> None:
    session = _ScopeSession(total=0)
    response = _client(
        app, session=session, user=_user("membro", "lider_celula")
    ).get("/contacts?page=2&pageSize=25")

    assert response.status_code == 200, response.text
    statements = _people_statements(session)
    assert len(statements) == 2
    for statement in statements:
        sql = _sql(statement)
        for fragment in (
            "pessoas.igreja_id",
            "pessoas.id",
            "EXISTS",
            "celula_membro",
            "JOIN celulas",
            "celula_membro.igreja_id",
            "celula_membro.pessoa_id = pessoas.id",
            "celula_membro.ativo IS true",
            "celulas.igreja_id",
            "celulas.lider_id",
            "celulas.ativo IS true",
            "EXISTS (SELECT conversations.id",
            "conversations.igreja_id",
            "conversations.pessoa_id = pessoas.id",
            "conversations.assumido_por",
        ):
            assert fragment in sql, sql
        assert str(_TENANT) in sql
        assert str(_ACTOR) in sql
        assert str(_APP_USER) in sql
    assert "LIMIT 25 OFFSET 25" in _sql(statements[1])


def test_list_operator_sees_assigned_conversation_without_linked_pessoa(app) -> None:
    assigned = _person(_TARGET)
    session = _ScopeSession(
        actor_pessoa_id=None, people=[assigned], total=1
    )
    response = _client(app, session=session, user=_user("operador")).get(
        "/contacts"
    )

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [str(_TARGET)]
    assert len(_people_statements(session)) == 2
    for statement in _people_statements(session):
        sql = _sql(statement)
        assert "pessoas.igreja_id" in sql
        assert "conversations.igreja_id" in sql
        assert "conversations.pessoa_id = pessoas.id" in sql
        assert "conversations.assumido_por" in sql
        assert str(_TENANT) in sql
        assert str(_APP_USER) in sql
        assert "false" not in sql.lower()


def test_list_operator_after_assignment_revoked_or_transferred_is_empty(app) -> None:
    session = _ScopeSession(actor_pessoa_id=None, people=[], total=0)
    response = _client(app, session=session, user=_user("operador")).get(
        "/contacts"
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "page": 1, "pageSize": 20, "total": 0}
    # The live assignee is part of both count and row predicates; once
    # assumido_por changes, the previous operador no longer matches either.
    for statement in _people_statements(session):
        sql = _sql(statement)
        assert "conversations.assumido_por" in sql
        assert str(_APP_USER) in sql


@pytest.mark.parametrize("role", ["membro", "lider_mult"])
def test_list_non_inbox_restricted_role_sees_only_own_pessoa(app, role) -> None:
    own = _person(_ACTOR)
    session = _ScopeSession(people=[own], total=1)
    response = _client(app, session=session, user=_user(role)).get("/contacts")

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [str(_ACTOR)]
    for statement in _people_statements(session)[:2]:
        sql = _sql(statement)
        assert "pessoas.igreja_id" in sql
        assert "pessoas.id" in sql
        assert str(_ACTOR) in sql
        assert "celula_membro" not in sql
        assert "conversations" not in sql


def test_list_restricted_user_without_pessoa_is_empty_fail_closed(app) -> None:
    session = _ScopeSession(actor_pessoa_id=None, total=0)
    response = _client(app, session=session, user=_user("membro")).get("/contacts")

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "page": 1, "pageSize": 20, "total": 0}
    statements = _people_statements(session)
    assert len(statements) == 2
    assert all("false" in _sql(statement).lower() for statement in statements)


@pytest.mark.parametrize("role", ["lider_celula", "operador"])
def test_detail_restricted_inbox_scope_includes_assigned_tenant_conversation(
    app, role
) -> None:
    target = _person(_TARGET)
    session = _ScopeSession(detail=True, detail_person=target)
    response = _client(app, session=session, user=_user("membro", role)).get(
        f"/contacts/{_TARGET}"
    )

    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(_TARGET)
    pessoa_statement = _people_statements(session)[0]
    sql = _sql(pessoa_statement)
    for fragment in (
        "pessoas.igreja_id",
        "EXISTS (SELECT conversations.id",
        "conversations.igreja_id",
        "conversations.pessoa_id = pessoas.id",
        "conversations.assumido_por",
    ):
        assert fragment in sql, sql
    if role == "lider_celula":
        assert "celula_membro.ativo IS true" in sql
        assert "celulas.ativo IS true" in sql
    else:
        assert "celula_membro" not in sql
    assert str(_TENANT) in sql
    assert str(_APP_USER) in sql


def test_detail_restricted_user_can_read_own_pessoa(app) -> None:
    own = _person(_ACTOR)
    session = _ScopeSession(detail=True, detail_person=own)
    response = _client(app, session=session, user=_user("membro")).get(
        f"/contacts/{_ACTOR}"
    )

    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(_ACTOR)
    sql = _sql(_people_statements(session)[0])
    assert "pessoas.id" in sql
    assert str(_ACTOR) in sql
    assert "pessoas.igreja_id" in sql


def test_detail_out_of_scope_is_404_before_label_queries(app) -> None:
    session = _ScopeSession(detail=True, detail_person=None)
    response = _client(app, session=session, user=_user("operador")).get(
        f"/contacts/{_TARGET}"
    )

    assert response.status_code == 404
    pessoa_statements = _people_statements(session)
    assert len(pessoa_statements) == 1
    sql = _sql(pessoa_statements[0])
    assert "conversations.assumido_por" in sql
    assert str(_APP_USER) in sql
    # Actor lookup + scoped Pessoa lookup only: no cell/leader label or
    # liderDeCelula lookup may run after the scoped query misses.
    assert len(session.statements) == 2


@pytest.mark.parametrize("role", ["membro", "lider_mult"])
def test_detail_non_inbox_role_gets_no_artificial_conversation_exception(
    app, role
) -> None:
    session = _ScopeSession(detail=True, detail_person=None)
    response = _client(app, session=session, user=_user(role)).get(
        f"/contacts/{_TARGET}"
    )

    assert response.status_code == 404
    sql = _sql(_people_statements(session)[0])
    assert "pessoas.igreja_id" in sql
    assert "conversations" not in sql
    assert str(_ACTOR) in sql


def test_detail_operator_cross_tenant_id_is_404_with_explicit_tenant_filters(
    app,
) -> None:
    session = _ScopeSession(actor_pessoa_id=None, detail=True, detail_person=None)
    response = _client(app, session=session, user=_user("operador")).get(
        f"/contacts/{_TARGET}"
    )

    assert response.status_code == 404
    sql = _sql(_people_statements(session)[0])
    assert "pessoas.igreja_id" in sql
    assert "conversations.igreja_id" in sql
    assert sql.count(str(_TENANT)) >= 2
    assert str(_OTHER_TENANT) not in sql


@pytest.mark.parametrize(
    "roles",
    [
        ("membro",),
        ("lider_celula",),
        ("operador",),
        ("lider_mult",),
    ],
)
def test_create_restricted_roles_are_denied_before_any_db_work(app, roles) -> None:
    session = _ScopeSession()
    response = _client(app, session=session, user=_user(*roles)).post(
        "/contacts",
        json={"nome": "Nova", "telefone": "11999990000"},
    )

    assert response.status_code == 403
    assert session.statements == []
    assert session.added == []
    assert session.flushes == 0
    assert session.commits == 0


def test_create_accumulated_wide_role_wins_over_cell_leader(app) -> None:
    existing = _person(_TARGET)
    session = _ScopeSession(people=[existing])
    response = _client(
        app,
        session=session,
        user=_user("lider_celula", "operador", "lider_consol"),
    ).post(
        "/contacts",
        json={"nome": "Nova", "telefone": existing.telefone},
    )

    assert response.status_code == 200, response.text
    assert response.json()["deduped"] is True
    assert response.json()["contact"]["id"] == str(_TARGET)
    assert session.added == []
    assert session.commits == 0
