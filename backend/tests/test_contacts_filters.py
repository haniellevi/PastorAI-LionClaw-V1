"""Server-side contact views are applied before count and pagination."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.db.models import Pessoa
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.routers.contacts import ContactView, _contact_view_conditions


def _predicate_sql(view: ContactView) -> str:
    statement = select(Pessoa.id).where(*_contact_view_conditions(view))
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).replace("\n", " ")


@pytest.mark.parametrize(
    ("view", "required"),
    [
        ("all", ("pessoas.arquivada_em IS NULL",)),
        ("arquivadas", ("pessoas.arquivada_em IS NOT NULL",)),
        ("contato", ("pessoas.arquivada_em IS NULL", "pessoas.tipo = 'contato'")),
        ("visitante", ("pessoas.tipo = 'visitante'",)),
        ("discipulo", ("pessoas.tipo = 'discipulo'",)),
        ("pastor", ("pessoas.tipo = 'pastor'",)),
        ("csim", ("pessoas.sem_interesse IS true",)),
        (
            "lideres_celula",
            (
                "pessoas.sem_interesse IS false",
                "EXISTS",
                "celulas.lider_id = pessoas.id",
                "celulas.ativo IS true",
            ),
        ),
        (
            "aptos",
            (
                "pessoas.apto_lider IS true",
                "pessoas.sem_interesse IS false",
                "NOT (EXISTS",
            ),
        ),
        (
            "pending",
            (
                "lower(coalesce(pessoas.acompanhamento, '')) NOT IN",
                "pessoas.subetapa != 'consolidado'",
                "pessoas.celula_id IS NULL",
                "pessoas.tipo != 'pastor'",
                "NOT (EXISTS",
            ),
        ),
    ],
)
def test_contact_view_predicates_match_tab_semantics(
    view: ContactView, required: tuple[str, ...]
) -> None:
    sql = _predicate_sql(view)
    for fragment in required:
        assert fragment in sql


class _Result:
    def __init__(self, *, scalar: int = 0, rows: list | None = None) -> None:
        self.scalar = scalar
        self.rows = rows or []

    def scalar_one(self) -> int:
        return self.scalar

    def scalars(self) -> _Result:
        return self

    def all(self) -> list:
        return self.rows


class _CaptureSession:
    def __init__(self) -> None:
        self.statements: list = []

    def execute(self, statement, params=None) -> _Result:
        self.statements.append(statement)
        return _Result(scalar=73 if len(self.statements) == 1 else 0)


def _current_user() -> CurrentUser:
    return CurrentUser(
        app_user_id="00000000-0000-0000-0000-0000000000a1",
        clerk_user_id="clerk-test",
        igreja_id="00000000-0000-0000-0000-000000000001",
        email="admin@example.com",
        nome="Admin",
        roles=frozenset({"admin"}),
    )


def test_endpoint_filters_count_and_rows_before_offset(app) -> None:
    session = _CaptureSession()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = _current_user

    response = TestClient(app).get(
        "/contacts?view=aptos&page=2&pageSize=50",
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 2, "pageSize": 50, "total": 73}
    # An empty page needs only count + rows; the bounded leader query is skipped.
    assert len(session.statements) == 2
    count_sql = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    rows_sql = str(
        session.statements[1].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    for sql in (count_sql, rows_sql):
        assert "pessoas.arquivada_em IS NULL" in sql
        assert "pessoas.apto_lider IS true" in sql
        assert "NOT (EXISTS" in sql
    assert "LIMIT 50 OFFSET 50" in rows_sql.replace("\n", " ")
    assert "ORDER BY pessoas.created_at DESC, pessoas.id DESC" in rows_sql.replace(
        "\n", " "
    )


class _PagedContactSession:
    def __init__(self, contacts: list[Pessoa], leader_ids: list[uuid.UUID]) -> None:
        self.contacts = contacts
        self.leader_ids = leader_ids
        self.statements: list = []

    def execute(self, statement, params=None) -> _Result:
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _Result(scalar=len(self.contacts))
        if len(self.statements) == 2:
            return _Result(rows=self.contacts)
        return _Result(rows=self.leader_ids)


def _contact(pessoa_id: uuid.UUID, nome: str) -> Pessoa:
    return Pessoa(
        id=pessoa_id,
        igreja_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        nome=nome,
        telefone="5511999999999",
        email=None,
        genero=None,
        tipo="contato",
        etapa=None,
        subetapa=None,
        acompanhamento=None,
        sem_interesse=False,
        sem_interesse_motivo=None,
        presencas_celula=0,
        aceitou_jesus=False,
        celula_id=None,
        lider_id=None,
        apto_lider=False,
        arquivada_em=None,
        created_at=dt.datetime(2026, 8, 8, tzinfo=dt.UTC),
    )


def test_endpoint_limits_leader_projection_to_returned_page_ids(app) -> None:
    first_id = uuid.UUID("00000000-0000-0000-0000-000000000101")
    second_id = uuid.UUID("00000000-0000-0000-0000-000000000102")
    outside_page_id = uuid.UUID("00000000-0000-0000-0000-000000000999")
    session = _PagedContactSession(
        [_contact(first_id, "Primeiro"), _contact(second_id, "Segundo")],
        [second_id],
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = _current_user

    response = TestClient(app).get("/contacts?page=1&pageSize=2")

    assert response.status_code == 200
    assert [item["liderDeCelula"] for item in response.json()["items"]] == [
        False,
        True,
    ]
    assert len(session.statements) == 3
    leader_sql = str(
        session.statements[2].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).replace("\n", " ")
    assert "SELECT DISTINCT celulas.lider_id" in leader_sql
    assert "celulas.ativo IS true" in leader_sql
    assert "celulas.lider_id IN" in leader_sql
    assert str(first_id) in leader_sql
    assert str(second_id) in leader_sql
    assert str(outside_page_id) not in leader_sql


def test_endpoint_rejects_unknown_view(app) -> None:
    app.dependency_overrides[get_db] = lambda: _CaptureSession()
    app.dependency_overrides[get_current_user] = _current_user
    response = TestClient(app).get("/contacts?view=qualquer")
    assert response.status_code == 422
