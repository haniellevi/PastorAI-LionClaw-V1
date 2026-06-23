"""POST /work-queue/{id}/message — a nota interna respeita a visão restrita (#5).

O responsável (visão restrita) só anota em conversa atribuída a ele; admin/pastor
(visão completa) anotam em qualquer conversa do tenant.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Conversation, Pessoa, UserRole, WorkQueueItem
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_ITEM = "00000000-0000-0000-0000-0000000000d1"
_MSG = f"/work-queue/{_ITEM}/message"
_SELF_ID = "00000000-0000-0000-0000-0000000000a1"  # = make_app_user().id
_OTHER_ID = "00000000-0000-0000-0000-0000000000c9"


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

    def __init__(self, *, app_user, roles, item, pessoa, conversation) -> None:
        self.app_user = app_user
        self.roles = roles
        self.item = item
        self.pessoa = pessoa
        self.conversation = conversation
        self.added: list = []
        self.committed = False

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is WorkQueueItem:
            return _R(scalar=self.item)
        if ent is Pessoa:
            return _R(scalar=self.pessoa)
        if ent is Conversation:
            return _R(scalar=self.conversation)
        return _R(scalars=self.roles)

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


def _item():
    return SimpleNamespace(id=_ITEM, tipo="visitante", pessoa_id="p1")


def _pessoa():
    return SimpleNamespace(id="p1", telefone="+5511999990000")


def _conv(assumido_por):
    return SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000aa",
        pessoa_id="p1",
        assumido_por=assumido_por,
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
