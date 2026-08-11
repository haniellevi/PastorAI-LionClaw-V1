"""Escopo de linha da fila pastoral, inclusive acessos diretos por UUID."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AppUser, Conversation, Pessoa, WorkQueueItem
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.domain.work_queue import has_tenant_queue_scope
from app.routers.work_queue import _messageable_person_ids, _work_item_scope_condition

_IGREJA = "00000000-0000-0000-0000-000000000001"
_USER = "00000000-0000-0000-0000-0000000000a1"
_PESSOA = "00000000-0000-0000-0000-0000000000b1"
_ITEM = "00000000-0000-0000-0000-0000000000d1"


class _Result:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class ScopeSession:
    def __init__(
        self,
        actor_pessoa_id: str | None,
        *,
        assigned_conversation_person_ids: list[str] | None = None,
        work_items: list[object] | None = None,
        valid_person_ids: list[str] | None = None,
    ) -> None:
        self.actor_pessoa_id = (
            uuid.UUID(actor_pessoa_id) if actor_pessoa_id is not None else None
        )
        self.work_item_sql: list[str] = []
        self.conversation_sql: list[str] = []
        self.assigned_conversation_person_ids = [
            uuid.UUID(value) for value in (assigned_conversation_person_ids or [])
        ]
        self.assigned_conversations = [
            SimpleNamespace(
                id=uuid.UUID(int=500 + index),
                pessoa_id=pessoa_id,
                igreja_id=uuid.UUID(_IGREJA),
                assumido_por=uuid.UUID(_USER),
                numero_oficial=True,
                updated_at=None,
            )
            for index, pessoa_id in enumerate(
                self.assigned_conversation_person_ids, start=1
            )
        ]
        self.work_items = work_items or []
        self.valid_person_ids = [
            uuid.UUID(value)
            for value in (
                valid_person_ids
                if valid_person_ids is not None
                else [
                    str(item.pessoa_id)
                    for item in self.work_items
                    if getattr(item, "pessoa_id", None) is not None
                ]
            )
        ]
        self.added: list[object] = []
        self.committed = False
        self.pessoa_sql: list[str] = []

    def execute(self, statement, params=None):
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entity = descriptions[0].get("entity") if descriptions else None
        name = descriptions[0].get("name") if descriptions else None
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))

        if entity is AppUser and name == "pessoa_id":
            return _Result(scalar=self.actor_pessoa_id)
        if entity is Conversation:
            self.conversation_sql.append(sql)
            return _Result(scalars=self.assigned_conversations)
        if entity is Pessoa and name == "id":
            self.pessoa_sql.append(sql)
            return _Result(scalars=self.valid_person_ids)
        if entity is WorkQueueItem or "work_queue_items" in sql:
            self.work_item_sql.append(sql)
            visible_items = [
                item
                for item in self.work_items
                if getattr(item, "status", None) in {None, "aberto", "assumido"}
            ]
            visible_items.sort(
                key=lambda item: (
                    getattr(item, "prioridade", None) is None,
                    getattr(item, "prioridade", 0) or 0,
                )
            )
            if "count(" in sql.lower():
                return _Result(scalar=len(visible_items))
            offset_clause = getattr(statement, "_offset_clause", None)
            limit_clause = getattr(statement, "_limit_clause", None)
            offset = offset_clause.value if offset_clause is not None else 0
            limit = (
                limit_clause.value
                if limit_clause is not None
                else len(visible_items)
            )
            return _Result(
                scalar=None,
                scalars=visible_items[offset : offset + limit],
            )
        return _Result()

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        pass


def _user(*roles: str) -> CurrentUser:
    return CurrentUser(
        app_user_id=_USER,
        clerk_user_id="clerk_scope",
        igreja_id=_IGREJA,
        email="lider@example.com",
        nome="Líder",
        roles=frozenset(roles),
    )


def _compiled_scope(session: ScopeSession, user: CurrentUser) -> str:
    condition = _work_item_scope_condition(session, user)
    return str(
        select(WorkQueueItem)
        .where(condition)
        .compile(compile_kwargs={"literal_binds": True})
    )


def _where(sql: str) -> str:
    return sql.split("WHERE", 1)[1]


def _client(app, session: ScopeSession, user: CurrentUser) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_tenant_scope_role_is_additive() -> None:
    assert has_tenant_queue_scope(["lider_celula"]) is False
    assert has_tenant_queue_scope(["lider_celula", "membro"]) is False
    assert has_tenant_queue_scope(["lider_celula", "lider_g12"]) is True
    assert has_tenant_queue_scope(["lider_celula", "lider_consol"]) is True
    assert has_tenant_queue_scope(["admin", "lider_celula"]) is True


def test_cell_leader_scope_uses_assignment_self_and_canonical_membership() -> None:
    session = ScopeSession(_PESSOA)
    sql = _compiled_scope(session, _user("lider_celula"))

    assert "work_queue_items.igreja_id" in sql
    assert "work_queue_items.responsavel_id" in sql
    assert "work_queue_items.pessoa_id" in sql
    assert "celula_membro" in sql
    assert "JOIN celulas" in sql
    assert "celula_membro.ativo IS true" in sql
    assert "celulas.ativo IS true" in sql
    assert "celulas.lider_id" in sql
    assert sql.count(_IGREJA.replace("-", "")) >= 3


def test_restricted_user_without_pessoa_keeps_only_explicit_assignment() -> None:
    session = ScopeSession(None)
    sql = _compiled_scope(session, _user("lider_celula"))
    where = _where(sql)

    assert "work_queue_items.igreja_id" in where
    assert "work_queue_items.responsavel_id" in where
    assert "work_queue_items.pessoa_id" not in where
    assert "celula_membro" not in where


def test_accumulated_broad_role_wins_without_cell_subquery() -> None:
    session = ScopeSession(_PESSOA)
    sql = _compiled_scope(session, _user("lider_celula", "lider_g12"))
    where = _where(sql)

    assert "work_queue_items.igreja_id" in where
    assert "celula_membro" not in where
    assert "work_queue_items.responsavel_id" not in where


def test_list_applies_same_scope_to_count_and_rows(app) -> None:
    session = ScopeSession(_PESSOA)
    response = _client(app, session, _user("lider_celula")).get("/work-queue")

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0
    assert len(session.work_item_sql) == 2
    for sql in session.work_item_sql:
        assert "work_queue_items.igreja_id" in sql
        assert "work_queue_items.responsavel_id" in sql
        assert "celula_membro" in sql
        assert "work_queue_items.status IS NULL" in sql
        assert "work_queue_items.status IN ('aberto', 'assumido')" in sql


def test_message_capability_for_restricted_role_uses_assigned_conversation() -> None:
    session = ScopeSession(
        _PESSOA,
        assigned_conversation_person_ids=[_PESSOA],
        valid_person_ids=[_PESSOA],
    )
    rows = [SimpleNamespace(pessoa_id=uuid.UUID(_PESSOA))]

    visible = _messageable_person_ids(session, _user("lider_celula"), rows)

    assert visible == {uuid.UUID(_PESSOA)}
    assert len(session.pessoa_sql) == 1
    assert "pessoas.igreja_id" in session.pessoa_sql[0]
    assert len(session.conversation_sql) == 1
    sql = session.conversation_sql[0]
    assert "conversations.igreja_id" in sql
    assert "conversations.assumido_por" in sql
    assert "ORDER BY conversations.pessoa_id ASC" in sql
    assert "conversations.numero_oficial DESC" in sql
    assert "conversations.updated_at DESC" in sql
    assert "conversations.id ASC" in sql
    assert _IGREJA.replace("-", "") in sql
    assert _USER.replace("-", "") in sql


def test_message_capability_for_pastor_validates_person_without_conversation_lookup() -> None:
    session = ScopeSession(_PESSOA, valid_person_ids=[_PESSOA])
    rows = [SimpleNamespace(pessoa_id=uuid.UUID(_PESSOA))]

    visible = _messageable_person_ids(session, _user("pastor"), rows)

    assert visible == {uuid.UUID(_PESSOA)}
    assert len(session.pessoa_sql) == 1
    assert "pessoas.igreja_id" in session.pessoa_sql[0]
    assert session.conversation_sql == []


def test_message_capability_fails_closed_for_person_outside_tenant() -> None:
    session = ScopeSession(_PESSOA, valid_person_ids=[])
    rows = [SimpleNamespace(pessoa_id=uuid.UUID(_PESSOA))]

    visible = _messageable_person_ids(session, _user("pastor"), rows)

    assert visible == set()
    assert len(session.pessoa_sql) == 1
    assert "pessoas.igreja_id" in session.pessoa_sql[0]
    assert session.conversation_sql == []


def test_list_projects_server_resolved_message_capability(app) -> None:
    item = SimpleNamespace(
        id=uuid.UUID(_ITEM),
        tipo="visitante",
        titulo="Acompanhar visitante",
        contexto=None,
        status="aberto",
        pessoa_id=uuid.UUID(_PESSOA),
        responsavel_id=None,
        prioridade=1,
        prazo=None,
    )
    session = ScopeSession(
        _PESSOA,
        assigned_conversation_person_ids=[_PESSOA],
        work_items=[item],
    )

    response = _client(app, session, _user("lider_celula")).get("/work-queue")

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["canMessage"] is True


def test_list_includes_legacy_null_and_excludes_resolved_before_pagination(app) -> None:
    def item(index: int, item_status: str | None):
        return SimpleNamespace(
            id=uuid.UUID(int=800 + index),
            tipo="visitante",
            titulo=f"Item {index}",
            contexto=None,
            status=item_status,
            pessoa_id=uuid.UUID(_PESSOA),
            responsavel_id=None,
            prioridade=index,
            prazo=None,
        )

    session = ScopeSession(
        _PESSOA,
        work_items=[
            item(1, "resolvido"),
            item(2, None),
            item(3, "aberto"),
        ],
    )

    response = _client(app, session, _user("lider_celula")).get(
        "/work-queue?page=1&pageSize=1"
    )

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2
    assert [row["titulo"] for row in response.json()["items"]] == ["Item 2"]
    assert len(session.work_item_sql) == 2
    for sql in session.work_item_sql:
        assert "work_queue_items.status IS NULL" in sql
        assert "work_queue_items.status IN ('aberto', 'assumido')" in sql


def test_action_outside_scope_is_404_without_write(app) -> None:
    session = ScopeSession(_PESSOA)
    response = _client(app, session, _user("lider_celula")).post(
        f"/work-queue/{_ITEM}/action", json={"action": "assume"}
    )

    assert response.status_code == 404
    assert session.added == []
    assert session.committed is False
    assert len(session.work_item_sql) == 1
    assert "celula_membro" in session.work_item_sql[0]


def test_message_outside_scope_is_404_without_write(app) -> None:
    session = ScopeSession(_PESSOA)
    response = _client(app, session, _user("lider_celula")).post(
        f"/work-queue/{_ITEM}/message", json={"mensagem": "Tentei contato."}
    )

    assert response.status_code == 404
    assert session.added == []
    assert session.committed is False
    assert len(session.work_item_sql) == 1
    assert "celula_membro" in session.work_item_sql[0]
