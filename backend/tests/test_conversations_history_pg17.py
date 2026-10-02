"""Cursor boundaries, private media and revocation with real PostgreSQL RLS."""
from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, text

from app.db.models import Conversation, Message, RolePermission
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.domain.agent_reply import AGENT_REPLY_PENDING
from app.services.storage import get_storage
from tests.test_work_queue_snapshot import queue_db, TENANT, OTHER, ACTOR  # noqa: F401
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration
CONV = uuid.UUID(int=20)
OTHER_CONV = uuid.UUID(int=21)


@pytest.fixture
def history_db(queue_db):
    session, connection, role = queue_db
    metadata = MetaData()
    tables = {}
    for model in (Conversation, Message, RolePermission):
        table = Table(model.__tablename__, metadata, *(Column(
            c.name, c.type, primary_key=c.primary_key, nullable=c.nullable,
            server_default=c.server_default,
        ) for c in model.__table__.columns))
        table.create(connection)
        connection.execute(text(f'ALTER TABLE {table.name} ENABLE ROW LEVEL SECURITY'))
        connection.execute(text(f"CREATE POLICY tenant ON {table.name} FOR ALL USING "
            "(igreja_id = current_setting('app.tenant_igreja_id')::uuid) "
            "WITH CHECK (igreja_id = current_setting('app.tenant_igreja_id')::uuid)"))
        connection.execute(text(f'GRANT SELECT ON {table.name} TO "{role}"'))
        tables[model.__tablename__] = table
    connection.execute(tables["role_permissions"].insert(), {
        "igreja_id": TENANT, "papel": "secretaria", "tela": "inbox",
    })
    connection.execute(tables["conversations"].insert(), [
        {"id": CONV, "igreja_id": TENANT, "telefone": "00000000000", "assumido_por": ACTOR},
        {"id": OTHER_CONV, "igreja_id": OTHER, "telefone": "00000000001", "assumido_por": ACTOR},
    ])
    for index in range(1, 9):
        connection.execute(tables["messages"].insert(), {
            "id": uuid.UUID(int=100 + index), "igreja_id": TENANT if index < 8 else OTHER,
            "conversation_id": CONV if index < 8 else OTHER_CONV,
            "direcao": "out" if index == 7 else "in", "autor": "ia" if index == 7 else "contato",
            "agent_reply_state": AGENT_REPLY_PENDING if index == 7 else None,
            "texto": f"Synthetic {index}", "media_path": f"{TENANT}/{CONV}/{index}.png",
            "criado_em": dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        })
    yield queue_db


def client_for(app, history_db, roles=("admin",)):
    session, connection, role = history_db
    connection.execute(text("SELECT set_config('app.tenant_igreja_id', :tenant, true)"), {"tenant": str(TENANT)})
    connection.execute(text(f'SET LOCAL ROLE "{role}"'))
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        app_user_id=str(ACTOR), clerk_user_id="synthetic-history", igreja_id=str(TENANT),
        email="synthetic@example.invalid", nome="Synthetic", roles=frozenset(roles))
    calls = []
    class Storage:
        def sign(self, paths):
            assert not session.in_transaction()
            calls.append(list(paths))
            return {path: "https://synthetic.example.invalid/signed" for path in paths}
    app.dependency_overrides[get_storage] = lambda: Storage()
    return TestClient(app), calls


def test_cursor_history_has_no_gaps_or_duplicates_at_equal_timestamps(app, history_db):
    client, calls = client_for(app, history_db)
    path = f"/conversations/{CONV}/messages"
    newest = client.get(path + "?latest=true&includeMedia=false&pageSize=2")
    assert newest.status_code == 200
    body = newest.json()
    assert body["total"] == 6
    collected = body["items"]
    cursor = body["nextBefore"]
    while cursor:
        response = client.get(path, params={"before": cursor, "includeMedia": "false", "pageSize": 2})
        assert response.status_code == 200
        collected = response.json()["items"] + collected
        cursor = response.json()["nextBefore"]
    assert [item["id"] for item in collected] == [str(uuid.UUID(int=100 + index)) for index in range(1, 7)]
    assert calls == []
    after = client.get(path, params={"after": body["nextAfter"], "includeMedia": "false"})
    assert after.json()["items"] == []


def test_delta_is_bounded_and_media_signs_only_authorized_ids(app, history_db):
    client, calls = client_for(app, history_db)
    path = f"/conversations/{CONV}/messages"
    first = client.get(path + "?includeMedia=false&pageSize=2").json()
    delta = client.get(path, params={"after": first["nextAfter"], "includeMedia": "false", "pageSize": 2})
    assert [item["id"] for item in delta.json()["items"]] == [str(uuid.UUID(int=103)), str(uuid.UUID(int=104))]
    assert delta.json()["hasMoreAfter"] is True
    signed = client.get(path + "/media-urls", params={"ids": str(uuid.UUID(int=103))})
    assert signed.status_code == 200
    assert list(signed.json()["urls"]) == [str(uuid.UUID(int=103))]
    assert len(calls) == 1
    for invalid_id in (107, 108):
        response = client.get(path + "/media-urls", params={"ids": str(uuid.UUID(int=invalid_id))})
        assert response.status_code == 404
    assert len(calls) == 1
    assert client.get(f"/conversations/{OTHER_CONV}/messages?latest=true").status_code == 404


def test_handoff_revokes_media_read_before_storage_call(app, history_db):
    session, connection, _ = history_db
    connection.execute(text("UPDATE conversations SET assumido_por=:actor WHERE id=:id"),
                       {"actor": uuid.UUID(int=99), "id": CONV})
    client, calls = client_for(app, history_db, roles=("secretaria",))
    response = client.get(f"/conversations/{CONV}/messages/media-urls", params={"ids": str(uuid.UUID(int=101))})
    assert response.status_code == 404
    assert calls == []
