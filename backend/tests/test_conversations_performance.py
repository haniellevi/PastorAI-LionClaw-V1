"""Synthetic inbox tests: bounded recent history and connection-free media I/O."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.models import Conversation, Message
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.services.storage import get_storage

TENANT = uuid.UUID(int=1)
ACTOR = uuid.UUID(int=2)
CONV = uuid.UUID(int=3)


def message(index: int, *, media: bool = False) -> Message:
    return Message(
        id=uuid.UUID(int=100 + index), igreja_id=TENANT, conversation_id=CONV,
        direcao="in", autor="contato", tipo="imagem" if media else "texto",
        texto=f"Synthetic message {index}",
        criado_em=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(minutes=index),
        media_path=f"{TENANT}/{CONV}/{index}.png" if media else None,
    )


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: self.value)


class HistorySession:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False
        self.conv = Conversation(id=CONV, igreja_id=TENANT, telefone="00000000000")

    def execute(self, statement, params=None):
        sql = str(statement)
        if "count(" in sql.lower():
            return Result(len(self.rows))
        if "FROM conversations" in sql:
            return Result(self.conv)
        rows = sorted(self.rows, key=lambda row: (row.criado_em, row.id),
                      reverse="DESC" in str(statement._order_by_clause))
        offset = statement._offset_clause.value if statement._offset_clause is not None else 0
        limit = statement._limit_clause.value if statement._limit_clause is not None else len(rows)
        return Result(rows[offset:offset + limit])

    def close(self):
        self.closed = True


class MediaStorage:
    def __init__(self, db):
        self.db = db
        self.calls = 0

    def sign(self, paths):
        self.calls += 1
        assert self.db.closed, "Storage I/O retained the database connection"
        return {path: "https://storage.example.test/signed" for path in paths}


def client_for(app, rows):
    db = HistorySession(rows)
    storage = MediaStorage(db)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        app_user_id=str(ACTOR), clerk_user_id="synthetic", igreja_id=str(TENANT),
        email="synthetic@example.test", nome="Synthetic", roles=frozenset({"admin"}),
    )
    app.dependency_overrides[get_storage] = lambda: storage
    return TestClient(app), db, storage


def test_recent_history_returns_latest_page_in_chronological_order(app):
    client, _, _ = client_for(app, [message(index) for index in range(1, 6)])
    response = client.get(f"/conversations/{CONV}/messages?latest=true&pageSize=2")
    assert response.status_code == 200
    assert [item["texto"] for item in response.json()["items"]] == [
        "Synthetic message 4", "Synthetic message 5",
    ]
    assert response.json()["total"] == 5
    assert response.json()["nextBefore"]


def test_media_signing_releases_database_before_external_io(app):
    client, db, storage = client_for(app, [message(1, media=True)])
    response = client.get(f"/conversations/{CONV}/messages")
    assert response.status_code == 200
    assert db.closed and storage.calls == 1
    assert response.json()["items"][0]["mediaUrl"]


def test_text_history_does_not_wait_for_media_signing(app):
    client, _, storage = client_for(app, [message(1, media=True)])
    response = client.get(f"/conversations/{CONV}/messages?includeMedia=false")
    assert response.status_code == 200
    assert storage.calls == 0
    assert response.json()["items"][0]["mediaUrl"] is None


@pytest.mark.parametrize("cursor", ["bad", "a" * 300])
def test_malformed_history_cursor_is_rejected(app, cursor):
    client, _, _ = client_for(app, [message(1)])
    response = client.get(f"/conversations/{CONV}/messages?before={cursor}")
    assert response.status_code == 422


@pytest.mark.parametrize("query", ["before=", "after=", "latest=true&page=2", "before=bad&after=bad"])
def test_ambiguous_or_empty_history_navigation_is_rejected(app, query):
    client, _, storage = client_for(app, [message(1)])
    response = client.get(f"/conversations/{CONV}/messages?{query}")
    assert response.status_code == 422
    assert storage.calls == 0
