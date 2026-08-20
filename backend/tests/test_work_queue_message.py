"""POST /work-queue/{id}/message — a nota interna respeita a visão restrita (#5).

O responsável (visão restrita) só anota em conversa atribuída a ele; admin/pastor
(visão completa) anotam em qualquer conversa do tenant.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import (
    AppUser,
    Conversation,
    Message,
    Pessoa,
    UserRole,
    WorkQueueItem,
)
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_ITEM = "00000000-0000-0000-0000-0000000000d1"
_MSG = f"/work-queue/{_ITEM}/message"
_SELF_ID = "00000000-0000-0000-0000-0000000000a1"  # = make_app_user().id
_OTHER_ID = "00000000-0000-0000-0000-0000000000c9"
_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_OTHER_IGREJA_ID = "00000000-0000-0000-0000-000000000002"
_PESSOA_ID = "00000000-0000-0000-0000-0000000000b1"


class _R:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class WQSession:
    """Routes auth (AppUser/UserRole) + item/pessoa/conversation lookups."""

    def __init__(
        self,
        *,
        app_user,
        roles,
        item,
        pessoa,
        conversation=None,
        conversations=None,
    ) -> None:
        self.app_user = app_user
        self.roles = roles
        self.item = item
        self.pessoa = pessoa
        self.conversations = list(
            conversations
            if conversations is not None
            else ([conversation] if conversation is not None else [])
        )
        self.added: list = []
        self.committed = False
        self.conversation_sql: list[str] = []
        self.conversation_where: list[str] = []
        self.work_item_sql: list[str] = []

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        name = descs[0].get("name") if descs else None
        if ent is AppUser and name == "pessoa_id":
            return _R(scalar=None)
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is WorkQueueItem:
            sql = str(
                statement.compile(compile_kwargs={"literal_binds": True})
            ).lower()
            self.work_item_sql.append(sql)
            if (
                self.item is not None
                and self.item.status not in {None, "aberto", "assumido"}
                and "work_queue_items.status in" in sql
            ):
                return _R()
            return _R(scalar=self.item)
        if ent is Pessoa:
            return _R(scalar=self.pessoa)
        if ent is Conversation:
            sql = str(
                statement.compile(compile_kwargs={"literal_binds": True})
            ).lower()
            self.conversation_sql.append(sql)
            where_clause = getattr(statement, "whereclause", None)
            where = (
                str(
                    where_clause.compile(
                        compile_kwargs={"literal_binds": True}
                    )
                ).lower()
                if where_clause is not None
                else ""
            )
            self.conversation_where.append(where)
            rows = list(self.conversations)
            if "conversations.igreja_id" in where:
                rows = [
                    row for row in rows if str(row.igreja_id) == _IGREJA_ID
                ]
            if "conversations.assumido_por" in where:
                rows = [
                    row for row in rows if str(row.assumido_por) == _SELF_ID
                ]
            rows.sort(
                key=lambda row: (
                    not row.numero_oficial,
                    -row.updated_at.timestamp(),
                    str(row.id),
                )
            )
            return _R(scalar=rows[0] if rows else None, scalars=rows)
        return _R(scalars=self.roles)

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        for index, obj in enumerate(self.added, start=1):
            if getattr(obj, "id", None) is None:
                obj.id = uuid.UUID(int=900 + index)

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


def _item():
    return SimpleNamespace(
        id=uuid.UUID(_ITEM),
        igreja_id=uuid.UUID(_IGREJA_ID),
        tipo="visitante",
        pessoa_id=uuid.UUID(_PESSOA_ID),
        responsavel_id=uuid.UUID(_SELF_ID),
        status="aberto",
    )


def _pessoa():
    return SimpleNamespace(
        id=uuid.UUID(_PESSOA_ID), telefone="+5511999990000"
    )


def _conv(
    assumido_por,
    *,
    index=1,
    igreja_id=_IGREJA_ID,
    numero_oficial=True,
    updated_at=None,
):
    return SimpleNamespace(
        id=uuid.UUID(int=700 + index),
        igreja_id=uuid.UUID(igreja_id),
        pessoa_id=uuid.UUID(_PESSOA_ID),
        assumido_por=(uuid.UUID(assumido_por) if assumido_por else None),
        numero_oficial=numero_oficial,
        updated_at=updated_at or dt.datetime(2026, 8, index, tzinfo=dt.timezone.utc),
        ultima_mensagem=None,
    )


def _wire(app, session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


_NOTE = {"mensagem": "Liguei, sem resposta."}


def test_responsavel_cannot_note_unassigned_conversation(app) -> None:
    # lider_celula resolve "visitante", mas a conversa não está atribuída a ele.
    session = WQSession(
        app_user=make_app_user(),
        roles=["lider_celula"],
        item=_item(),
        pessoa=_pessoa(),
        conversation=_conv(assumido_por=None),
    )
    client = _wire(app, session=session)
    resp = client.post(_MSG, headers=_AUTH, json=_NOTE)
    assert resp.status_code == 404
    assert session.committed is False


def test_responsavel_cannot_note_others_conversation(app) -> None:
    session = WQSession(
        app_user=make_app_user(),
        roles=["lider_celula"],
        item=_item(),
        pessoa=_pessoa(),
        conversation=_conv(assumido_por=_OTHER_ID),
    )
    client = _wire(app, session=session)
    resp = client.post(_MSG, headers=_AUTH, json=_NOTE)
    assert resp.status_code == 404
    assert session.committed is False


def test_responsavel_can_note_own_conversation(app) -> None:
    session = WQSession(
        app_user=make_app_user(),
        roles=["lider_celula"],
        item=_item(),
        pessoa=_pessoa(),
        conversation=_conv(assumido_por=_SELF_ID),
    )
    client = _wire(app, session=session)
    resp = client.post(_MSG, headers=_AUTH, json=_NOTE)
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"
    assert session.committed is True


def test_restricted_message_selects_the_same_assigned_conversation_as_capability(
    app,
) -> None:
    assigned = _conv(_SELF_ID, index=1, numero_oficial=False)
    newer_unassigned = _conv(_OTHER_ID, index=2, numero_oficial=True)
    session = WQSession(
        app_user=make_app_user(),
        roles=["lider_celula"],
        item=_item(),
        pessoa=_pessoa(),
        conversations=[newer_unassigned, assigned],
    )

    resp = _wire(app, session=session).post(_MSG, headers=_AUTH, json=_NOTE)

    assert resp.status_code == 200, resp.text
    message = next(obj for obj in session.added if isinstance(obj, Message))
    assert message.conversation_id == assigned.id
    sql = session.conversation_sql[0]
    assert "conversations.igreja_id" in sql
    assert "conversations.assumido_por" in sql
    assert "order by conversations.numero_oficial desc" in sql
    assert "conversations.updated_at desc" in sql
    assert "conversations.id asc" in sql


def test_pastor_notes_any_conversation(app) -> None:
    # Visão completa: pastor anota mesmo em conversa de outra pessoa.
    session = WQSession(
        app_user=make_app_user(),
        roles=["pastor"],
        item=_item(),
        pessoa=_pessoa(),
        conversation=_conv(assumido_por=_OTHER_ID),
    )
    client = _wire(app, session=session)
    resp = client.post(_MSG, headers=_AUTH, json=_NOTE)
    assert resp.status_code == 200
    assert session.committed is True


def test_pastor_uses_deterministic_official_recent_conversation(app) -> None:
    official_old = _conv(_OTHER_ID, index=1, numero_oficial=True)
    unofficial_new = _conv(_OTHER_ID, index=3, numero_oficial=False)
    official_new = _conv(_OTHER_ID, index=2, numero_oficial=True)
    session = WQSession(
        app_user=make_app_user(),
        roles=["pastor"],
        item=_item(),
        pessoa=_pessoa(),
        conversations=[unofficial_new, official_old, official_new],
    )

    resp = _wire(app, session=session).post(_MSG, headers=_AUTH, json=_NOTE)

    assert resp.status_code == 200, resp.text
    message = next(obj for obj in session.added if isinstance(obj, Message))
    assert message.conversation_id == official_new.id
    assert "conversations.assumido_por" not in session.conversation_where[0]


def test_restricted_message_does_not_cross_tenant_or_create_conversation(app) -> None:
    session = WQSession(
        app_user=make_app_user(),
        roles=["lider_celula"],
        item=_item(),
        pessoa=_pessoa(),
        conversations=[
            _conv(_SELF_ID, igreja_id=_OTHER_IGREJA_ID),
            _conv(_OTHER_ID, index=2),
        ],
    )

    resp = _wire(app, session=session).post(_MSG, headers=_AUTH, json=_NOTE)

    assert resp.status_code == 404, resp.text
    assert session.added == []
    assert session.committed is False


def test_pastor_creates_tenant_conversation_only_when_none_exists(app) -> None:
    session = WQSession(
        app_user=make_app_user(),
        roles=["pastor"],
        item=_item(),
        pessoa=_pessoa(),
        conversations=[_conv(_OTHER_ID, igreja_id=_OTHER_IGREJA_ID)],
    )

    resp = _wire(app, session=session).post(_MSG, headers=_AUTH, json=_NOTE)

    assert resp.status_code == 200, resp.text
    created = next(obj for obj in session.added if isinstance(obj, Conversation))
    message = next(obj for obj in session.added if isinstance(obj, Message))
    assert created.igreja_id == uuid.UUID(_IGREJA_ID)
    assert created.pessoa_id == uuid.UUID(_PESSOA_ID)
    assert message.conversation_id == created.id


def test_resolved_item_cannot_be_messaged_by_uuid(app) -> None:
    item = _item()
    item.status = "resolvido"
    session = WQSession(
        app_user=make_app_user(),
        roles=["pastor"],
        item=item,
        pessoa=_pessoa(),
        conversation=_conv(_OTHER_ID),
    )

    resp = _wire(app, session=session).post(_MSG, headers=_AUTH, json=_NOTE)

    assert resp.status_code == 404, resp.text
    assert session.added == []
    assert session.committed is False
    assert "work_queue_items.status is null" in session.work_item_sql[0]
    assert "work_queue_items.status in ('aberto', 'assumido')" in (
        session.work_item_sql[0]
    )


def test_legacy_null_status_item_can_still_be_messaged(app) -> None:
    item = _item()
    item.status = None
    session = WQSession(
        app_user=make_app_user(),
        roles=["pastor"],
        item=item,
        pessoa=_pessoa(),
        conversation=_conv(_OTHER_ID),
    )

    resp = _wire(app, session=session).post(_MSG, headers=_AUTH, json=_NOTE)

    assert resp.status_code == 200, resp.text
    assert session.committed is True
    assert "work_queue_items.status is null" in session.work_item_sql[0]
    assert "work_queue_items.status in ('aberto', 'assumido')" in (
        session.work_item_sql[0]
    )
