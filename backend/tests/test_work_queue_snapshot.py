"""Queue pagination under a real PostgreSQL snapshot and tenant role."""
from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration
TENANT = uuid.UUID(int=1)
OTHER = uuid.UUID(int=2)
ACTOR = uuid.UUID(int=3)


@pytest.fixture
def queue_db(rls_database_url):
    engine = create_engine(rls_database_url)
    schema = "perf_queue_" + uuid.uuid4().hex
    role = schema + "_reader"
    connection = engine.connect()
    transaction = connection.begin()
    connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN NOBYPASSRLS'))
    connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
    connection.execute(text("""
        CREATE TABLE work_queue_items (
          id uuid PRIMARY KEY, igreja_id uuid NOT NULL, tipo text NOT NULL,
          titulo text NOT NULL, contexto text, pessoa_id uuid, responsavel_id uuid,
          consolidacao_id uuid, status text, prazo timestamptz, prioridade integer,
          created_at timestamptz NOT NULL);
        CREATE TABLE app_users (id uuid PRIMARY KEY, igreja_id uuid, pessoa_id uuid);
        CREATE TABLE celulas (id uuid PRIMARY KEY, igreja_id uuid, lider_id uuid, ativo boolean);
        CREATE TABLE celula_membros (igreja_id uuid, celula_id uuid, pessoa_id uuid, ativo boolean);
        CREATE TABLE pessoas (id uuid PRIMARY KEY, igreja_id uuid);
    """))
    for table in ("work_queue_items", "app_users", "celulas", "celula_membros", "pessoas"):
        connection.execute(text(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY'))
        connection.execute(text(f"CREATE POLICY tenant ON {table} FOR ALL USING "
                                "(igreja_id = current_setting('app.tenant_igreja_id')::uuid) "
                                "WITH CHECK (igreja_id = current_setting('app.tenant_igreja_id')::uuid)"))
        connection.execute(text(f'GRANT SELECT ON {table} TO "{role}"'))
    connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
    for index in range(1, 7):
        connection.execute(text("""INSERT INTO work_queue_items
          (id, igreja_id, tipo, titulo, status, prioridade, created_at)
          VALUES (:id, :tenant, 'fonovisita', :title, 'aberto', 1, :created)"""),
          {"id": uuid.UUID(int=100 + index), "tenant": TENANT if index < 6 else OTHER,
           "title": f"Synthetic item {index}", "created": dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)})
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session, connection, role
    session.close()
    transaction.rollback()
    connection.close()
    engine.dispose()


def client_for(app, queue_db, roles=("admin",)):
    session, connection, role = queue_db
    connection.execute(text("SELECT set_config('app.tenant_igreja_id', :tenant, true)"), {"tenant": str(TENANT)})
    connection.execute(text(f'SET LOCAL ROLE "{role}"'))
    user = CurrentUser(app_user_id=str(ACTOR), clerk_user_id="synthetic-queue", igreja_id=str(TENANT),
                       email="synthetic@example.invalid", nome="Synthetic", roles=frozenset(roles))
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_snapshot_counts_pages_and_stable_ties(app, queue_db):
    client = client_for(app, queue_db)
    first = client.get("/work-queue/snapshot?pageSize=2")
    assert first.status_code == 200
    body = first.json()
    assert body["total"] == 5
    assert [row["id"] for row in body["items"]] == [str(uuid.UUID(int=101)), str(uuid.UUID(int=102))]
    second = client.get(f'/work-queue/snapshot?page=2&pageSize=2&revision={body["revision"]}')
    assert second.status_code == 200
    assert [row["id"] for row in second.json()["items"]] == [str(uuid.UUID(int=103)), str(uuid.UUID(int=104))]
    empty = client.get(f'/work-queue/snapshot?page=4&pageSize=2&revision={body["revision"]}')
    assert empty.json()["items"] == []
    assert empty.json()["total"] == 5
    assert empty.json()["revision"] == body["revision"]


@pytest.mark.parametrize("mutation", [
    "UPDATE work_queue_items SET titulo='Changed' WHERE id=:id",
    "UPDATE work_queue_items SET prioridade=0 WHERE id=:id",
    "UPDATE work_queue_items SET status='concluido' WHERE id=:id",
    "UPDATE work_queue_items SET responsavel_id=:actor WHERE id=:id",
    "DELETE FROM work_queue_items WHERE id=:id",
])
def test_snapshot_rejects_changes_between_pages(app, queue_db, mutation):
    client = client_for(app, queue_db)
    first = client.get("/work-queue/snapshot?pageSize=2")
    assert first.status_code == 200
    _, connection, role = queue_db
    connection.execute(text("RESET ROLE"))
    connection.execute(text(mutation), {"id": uuid.UUID(int=105), "actor": ACTOR})
    connection.execute(text(f'SET LOCAL ROLE "{role}"'))
    response = client.get(f'/work-queue/snapshot?page=2&pageSize=2&revision={first.json()["revision"]}')
    assert response.status_code == 409


def test_other_tenant_change_does_not_change_revision(app, queue_db):
    client = client_for(app, queue_db)
    first = client.get("/work-queue/snapshot")
    assert first.status_code == 200
    _, connection, role = queue_db
    connection.execute(text("RESET ROLE"))
    connection.execute(text("UPDATE work_queue_items SET titulo='Other change' WHERE igreja_id=:tenant"), {"tenant": OTHER})
    connection.execute(text(f'SET LOCAL ROLE "{role}"'))
    refreshed = client.get("/work-queue/snapshot")
    assert refreshed.json()["revision"] == first.json()["revision"]
    assert refreshed.json()["total"] == 5


def test_restricted_actor_only_sees_assigned_without_linked_person(app, queue_db):
    _, connection, _ = queue_db
    connection.execute(text("UPDATE work_queue_items SET responsavel_id=:actor WHERE id=:id"),
                       {"actor": ACTOR, "id": uuid.UUID(int=103)})
    client = client_for(app, queue_db, roles=("lider_celula",))
    response = client.get("/work-queue/snapshot")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["items"]] == [str(uuid.UUID(int=103))]


def test_snapshot_requires_revision_after_first_page(app, queue_db):
    client = client_for(app, queue_db)
    assert client.get("/work-queue/snapshot?page=2").status_code == 422
    assert client.get("/work-queue/snapshot?revision=invalid").status_code == 422


def test_snapshot_materializes_one_page_beyond_200_with_one_queue_statement(app, queue_db):
    _, connection, _ = queue_db
    connection.execute(text("""INSERT INTO work_queue_items
      (id, igreja_id, tipo, titulo, status, prioridade, created_at)
      SELECT md5('synthetic-' || n)::uuid, :tenant, 'fonovisita', 'Synthetic bulk ' || n,
             'aberto', 2, '2026-01-01T00:00:00Z'::timestamptz
      FROM generate_series(1, 1000) AS n"""), {"tenant": TENANT})
    queries = []
    def capture(conn, cursor, statement, params, context, many):
        if "visible_queue AS" in statement:
            queries.append(statement)
    event.listen(connection, "before_cursor_execute", capture)
    client = client_for(app, queue_db)
    first = client.get("/work-queue/snapshot?pageSize=20")
    assert first.status_code == 200
    assert first.json()["total"] == 1005
    assert len(first.json()["items"]) == 20
    assert len(queries) == 1
    later = client.get("/work-queue/snapshot", params={"page": 16, "pageSize": 20,
                                                     "revision": first.json()["revision"]})
    assert later.status_code == 200
    assert len(later.json()["items"]) == 20
    assert not ({item["id"] for item in later.json()["items"]} & {item["id"] for item in first.json()["items"]})
    assert len(queries) == 2


def test_snapshot_empty_role_is_complete_and_old_revision_conflicts(app, queue_db):
    client = client_for(app, queue_db, roles=("membro",))
    response = client.get("/work-queue/snapshot")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0
    assert client.get("/work-queue/snapshot?revision=" + "0" * 32).status_code == 409
