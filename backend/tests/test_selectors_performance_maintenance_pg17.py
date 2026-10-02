"""Maintenance lookups against only the old columns, under real tenant RLS."""
from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.routers import cells, contacts
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration
TENANT = uuid.UUID(int=1)
OTHER = uuid.UUID(int=2)
ACTOR = uuid.UUID(int=10000)
USER = uuid.UUID(int=1100)


@pytest.fixture(scope="module")
def selector_engine(rls_database_url):
    engine = create_engine(rls_database_url)
    suffix = uuid.uuid4().hex[:12]
    schema, role = f"selector_{suffix}", f"selector_reader_{suffix}"
    with engine.begin() as connection:
        connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
        connection.exec_driver_sql(f"CREATE ROLE {role} NOLOGIN NOBYPASSRLS")
        connection.exec_driver_sql(f"SET LOCAL search_path TO {schema}")
        connection.exec_driver_sql("""CREATE TABLE celulas (
            id uuid PRIMARY KEY, igreja_id uuid NOT NULL, nome text NOT NULL,
            lider_id uuid, dia_reuniao text, cobertura_espiritual text NOT NULL,
            anfitriao_id uuid, auxiliar_id uuid, endereco text, horario text,
            link_grupo text, link_localizacao text, mensagem_convite text,
            ativo boolean NOT NULL, created_at timestamptz DEFAULT now()
        )""")
        connection.exec_driver_sql("""CREATE TABLE pessoas (
            id uuid PRIMARY KEY, igreja_id uuid NOT NULL, nome text NOT NULL,
            telefone text NOT NULL, email text, tipo text, celula_id uuid,
            apto_lider boolean NOT NULL, sem_interesse boolean NOT NULL,
            arquivada_em timestamptz, acompanhamento text, subetapa text
        )""")
        connection.exec_driver_sql("CREATE TABLE app_users (id uuid PRIMARY KEY, igreja_id uuid NOT NULL, pessoa_id uuid)")
        connection.exec_driver_sql("CREATE TABLE celula_membro (id uuid PRIMARY KEY, igreja_id uuid NOT NULL, pessoa_id uuid, celula_id uuid, ativo boolean)")
        connection.exec_driver_sql("CREATE TABLE conversations (id uuid PRIMARY KEY, igreja_id uuid NOT NULL, pessoa_id uuid, assumido_por uuid)")
        for table in ("celulas", "pessoas", "app_users", "celula_membro", "conversations"):
            connection.exec_driver_sql(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            connection.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            connection.exec_driver_sql(f"CREATE POLICY tenant_only ON {table} USING (igreja_id::text = current_setting('app.tenant_igreja_id', true))")
        connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA {schema} TO {role}")
        connection.exec_driver_sql(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {role}")
        connection.execute(text("INSERT INTO app_users VALUES (:id,:tenant,:person)"), {"id": USER, "tenant": TENANT, "person": ACTOR})
        cell_rows = [{"id": uuid.UUID(int=100 + index), "tenant": TENANT, "nome": f"Célula {index:03d}",
            "leader": None if index == 199 else uuid.UUID(int=20000) if index == 200 else ACTOR,
            "active": index != 200} for index in range(201)]
        # An invalid historical cross-tenant reference must not label a tenant-A person as a leader.
        cell_rows.append({"id": uuid.UUID(int=991), "tenant": OTHER, "nome": "Célula secreta", "leader": uuid.UUID(int=10200), "active": True})
        connection.execute(text("INSERT INTO celulas (id,igreja_id,nome,lider_id,cobertura_espiritual,ativo) VALUES (:id,:tenant,:nome,:leader,'Cobertura',:active)"), cell_rows)
        people = [{"id": uuid.UUID(int=10000 + index), "tenant": TENANT,
            "nome": "Alpha leader" if index == 0 else f"Pessoa {index:03d}",
            "tipo": "visitante" if index == 200 else "membro", "cell": uuid.UUID(int=100)} for index in range(201)]
        people.append({"id": uuid.UUID(int=20000), "tenant": OTHER, "nome": "Hidden leader", "tipo": "membro", "cell": uuid.UUID(int=991)})
        connection.execute(text("INSERT INTO pessoas (id,igreja_id,nome,telefone,email,tipo,celula_id,apto_lider,sem_interesse) VALUES (:id,:tenant,:nome,'11999990000','lookup@example.test',:tipo,:cell,true,false)"), people)
        connection.execute(text("INSERT INTO pessoas (id,igreja_id,nome,telefone,tipo,celula_id,apto_lider,sem_interesse,arquivada_em) VALUES (:id,:tenant,'Arquivada','1100000000','membro',:cell,true,false,now())"), {"id": uuid.UUID(int=10999), "tenant": TENANT, "cell": uuid.UUID(int=100)})
        connection.execute(text("INSERT INTO celula_membro VALUES (:id,:tenant,:person,:cell,true)"), [
            {"id": uuid.UUID(int=30000 + index), "tenant": TENANT, "person": uuid.UUID(int=10000 + index), "cell": uuid.UUID(int=100)} for index in (0, 1, 2)])
        connection.execute(text("INSERT INTO conversations VALUES (:id,:tenant,:person,:actor)"), {"id": uuid.UUID(int=40000), "tenant": TENANT, "person": uuid.UUID(int=10003), "actor": USER})
    try:
        yield engine, schema, role
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP SCHEMA {schema} CASCADE")
            connection.exec_driver_sql(f"DROP ROLE {role}")
        engine.dispose()


@pytest.fixture
def selector_client(selector_engine) -> Iterator[tuple[TestClient, list[str], dict]]:
    engine, schema, role = selector_engine
    statements: list[str] = []
    principal = {"roles": frozenset({"admin"})}
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        connection.exec_driver_sql(f"SET LOCAL search_path TO {schema}")
        connection.execute(text("SELECT set_config('app.tenant_igreja_id',:tenant,true)"), {"tenant": str(TENANT)})
        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
        event.listen(connection, "before_cursor_execute", capture)
        with Session(bind=connection) as session:
            application = FastAPI()
            application.include_router(cells.router)
            application.include_router(contacts.router)
            application.dependency_overrides[get_db] = lambda: session
            application.dependency_overrides[get_current_user] = lambda: CurrentUser(
                app_user_id=str(USER), clerk_user_id="synthetic-selector", igreja_id=str(TENANT),
                email="selector@example.test", nome="Selector", roles=principal["roles"],
            )
            with TestClient(application) as client:
                yield client, statements, principal
        event.remove(connection, "before_cursor_execute", capture)
        transaction.rollback()


def test_contact_lookup_beyond200_is_bounded_and_does_not_expose_foreign_leadership(selector_client):
    client, statements, _ = selector_client
    response = client.get("/contacts/lookup?page=9&pageSize=25")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 201
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == str(uuid.UUID(int=10200))
    assert data["items"][0]["liderDeCelula"] is False
    assert len(statements) == 3
    assert "LIMIT" in statements[1] and "OFFSET" in statements[1]
    assert "pessoas.presencas_celula" not in statements[1]
    assert "pessoas.endereco" not in statements[1]


def test_cell_lookup_and_summary_use_old_schema_and_exact_totals(selector_client):
    client, statements, _ = selector_client
    response = client.get("/cells/lookup?page=9&pageSize=25")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 201
    assert len(response.json()["items"]) == 1
    assert len(statements) == 2
    assert "celulas.bairro" not in statements[1]
    statements.clear()
    response = client.get("/cells/summary")
    assert response.status_code == 200, response.text
    assert response.json() == {"total": 201, "ativas": 200, "semLider": 1, "pessoasEmCelulas": 201}
    assert len(statements) == 1


def test_cell_page_metadata_is_bounded_and_preserves_original_counts(selector_client):
    client, statements, _ = selector_client
    response = client.get("/cells?page=9&pageSize=25")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 201
    assert data["items"][0]["id"] == str(uuid.UUID(int=100))
    assert data["items"][0]["liderNome"] == "Alpha leader"
    assert data["items"][0]["membros"] == 200
    assert data["items"][0]["visitantes"] == 1
    assert len(statements) == 4
    assert "pessoas.celula_id IN" in statements[2]
    assert "pessoas.id IN" in statements[3]


def test_search_respects_tenant_and_literal_wildcards(selector_client):
    client, _, _ = selector_client
    assert client.get("/cells/lookup?q=Alpha").json()["total"] == 199
    assert client.get("/cells/lookup?q=Hidden").json()["total"] == 0
    assert client.get("/contacts/lookup?q=Hidden").json()["total"] == 0
    assert client.get("/contacts/lookup?q=%25").json()["total"] == 0
    assert client.get("/cells/lookup?q=_").json()["total"] == 0
    assert client.get(f"/contacts/lookup?celulaId={uuid.UUID(int=991)}").json()["total"] == 0


@pytest.mark.parametrize(("roles", "people", "cell_count"), [
    ({"membro"}, 1, 1), ({"lider_celula"}, 4, 199), ({"operador"}, 2, 1),
    ({"membro", "lider_consol"}, 201, 1), ({"lider_celula", "admin"}, 201, 201),
])
def test_lookup_permissions_preserve_role_union_and_canonical_membership(selector_client, roles, people, cell_count):
    client, _, principal = selector_client
    principal["roles"] = frozenset(roles)
    assert client.get("/contacts/lookup").json()["total"] == people
    assert client.get("/cells/lookup").json()["total"] == cell_count


@pytest.mark.parametrize("path", ["/contacts/lookup?pageSize=201", "/contacts/lookup?celulaId=invalid", "/contacts/lookup?q=" + "x" * 121, "/cells/lookup?page=0"])
def test_invalid_lookup_input_is_rejected_before_domain_queries(selector_client, path):
    client, statements, _ = selector_client
    response = client.get(path)
    assert response.status_code == 422
    assert statements == []
