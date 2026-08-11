"""Safe assignment rules for POST /work-queue/{id}/action."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.models import AppUser, UserRole, WorkQueueItem
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user

_AUTH = {"Authorization": "Bearer good"}
_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_OTHER_IGREJA_ID = "00000000-0000-0000-0000-000000000002"
_ACTOR_ID = "00000000-0000-0000-0000-0000000000a1"
_ACTOR_PESSOA_ID = "00000000-0000-0000-0000-0000000000b1"
_TARGET_ID = "00000000-0000-0000-0000-0000000000c1"
_OLD_HOLDER_ID = "00000000-0000-0000-0000-0000000000c2"
_ITEM_ID = "00000000-0000-0000-0000-0000000000d1"


class _Result:
    def __init__(self, *, scalar=None, scalars=()) -> None:
        self._scalar = scalar
        self._scalars = list(scalars)

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


def _compiled(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True})).lower()


def _where_sql(statement) -> str:
    where = getattr(statement, "whereclause", None)
    if where is None:
        return ""
    return str(where.compile(compile_kwargs={"literal_binds": True})).lower()


class AssignSession:
    def __init__(
        self,
        *,
        item,
        actor_pessoa_id: str | None = _ACTOR_PESSOA_ID,
        target=None,
        target_roles=(),
        current_holder=None,
        current_holder_roles=(),
    ) -> None:
        self.item = item
        self.actor_pessoa_id = (
            uuid.UUID(actor_pessoa_id) if actor_pessoa_id is not None else None
        )
        self.target = target
        self.target_roles = list(target_roles)
        self.current_holder = current_holder
        self.current_holder_roles = list(current_holder_roles)
        self.execute_count = 0
        self.item_statements: list = []
        self.target_statements: list = []
        self.role_statements: list = []
        self.holder_statements: list = []
        self.flushes = 0
        self.commits = 0

    def execute(self, statement, params=None) -> _Result:
        self.execute_count += 1
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entity = descriptions[0].get("entity") if descriptions else None
        name = descriptions[0].get("name") if descriptions else None

        if entity is AppUser and name == "pessoa_id":
            return _Result(scalar=self.actor_pessoa_id)

        if entity is WorkQueueItem:
            self.item_statements.append(statement)
            return _Result(scalar=self.item)

        if entity is AppUser and name == "id":
            self.target_statements.append(statement)
            if self.target is None:
                return _Result()

            where = _where_sql(statement)
            if (
                str(self.target.igreja_id) != _IGREJA_ID
                and "app_users.igreja_id" in where
            ):
                return _Result()
            if (
                self.target.status not in {None, "ativo"}
                and "app_users.status" in where
            ):
                return _Result()
            return _Result(scalar=self.target.id)

        if entity is AppUser:
            self.holder_statements.append(statement)
            if self.current_holder is None:
                return _Result()
            where = _where_sql(statement)
            if (
                str(self.current_holder.igreja_id) != _IGREJA_ID
                and "app_users.igreja_id" in where
            ):
                return _Result()
            return _Result(scalar=self.current_holder)

        if entity is UserRole and name == "papel":
            self.role_statements.append(statement)
            where = _where_sql(statement)
            if uuid.UUID(_OLD_HOLDER_ID).hex in where:
                return _Result(scalars=self.current_holder_roles)
            return _Result(scalars=self.target_roles)

        return _Result()

    def flush(self) -> None:
        self.flushes += 1

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:  # pragma: no cover
        pass

    def close(self) -> None:  # pragma: no cover
        pass


def _item(
    *,
    tipo="visitante",
    pessoa_id=_ACTOR_PESSOA_ID,
    item_status="aberto",
    responsavel_id: str | None = None,
):
    return SimpleNamespace(
        id=uuid.UUID(_ITEM_ID),
        igreja_id=uuid.UUID(_IGREJA_ID),
        tipo=tipo,
        pessoa_id=uuid.UUID(pessoa_id),
        status=item_status,
        responsavel_id=(
            uuid.UUID(responsavel_id) if responsavel_id is not None else None
        ),
    )


def _target(*, igreja_id=_IGREJA_ID, status="ativo"):
    return SimpleNamespace(
        id=uuid.UUID(_TARGET_ID),
        igreja_id=uuid.UUID(igreja_id),
        status=status,
    )


def _holder(*, igreja_id=_IGREJA_ID, status="ativo"):
    return SimpleNamespace(
        id=uuid.UUID(_OLD_HOLDER_ID),
        igreja_id=uuid.UUID(igreja_id),
        status=status,
    )


def _current_user(*roles: str) -> CurrentUser:
    return CurrentUser(
        app_user_id=_ACTOR_ID,
        clerk_user_id="clerk_queue_assign",
        igreja_id=_IGREJA_ID,
        email="assign@igrejapiloto.com.br",
        nome="Assign",
        roles=frozenset(roles),
    )


def _client(app, *, session: AssignSession, current_user: CurrentUser):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


def _assign(client: TestClient):
    return client.post(
        f"/work-queue/{_ITEM_ID}/action",
        headers=_AUTH,
        json={"action": "assign", "responsavelId": _TARGET_ID},
    )


def _assert_no_write(session: AssignSession, item) -> None:
    assert item.status == "aberto"
    assert item.responsavel_id is None
    assert session.flushes == 0
    assert session.commits == 0


@pytest.mark.parametrize("roles", [("lider_celula",), ("membro",)])
def test_restricted_roles_cannot_assign_before_any_read_or_write(app, roles) -> None:
    item = _item()
    session = AssignSession(
        item=item,
        target=_target(),
        target_roles=["lider_celula"],
    )
    client = _client(app, session=session, current_user=_current_user(*roles))

    response = _assign(client)

    assert response.status_code == 403, response.text
    assert session.execute_count == 0
    _assert_no_write(session, item)


def test_cell_leader_can_still_assume_item_in_own_scope(app) -> None:
    item = _item()
    session = AssignSession(item=item)
    client = _client(
        app,
        session=session,
        current_user=_current_user("lider_celula"),
    )

    response = client.post(
        f"/work-queue/{_ITEM_ID}/action",
        headers=_AUTH,
        json={"action": "assume"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["responsavelId"] == _ACTOR_ID
    assert len(session.item_statements) == 1
    assert session.target_statements == []
    assert session.role_statements == []
    assert item.responsavel_id == uuid.UUID(_ACTOR_ID)
    assert session.flushes == 1
    assert session.commits == 1


def test_accumulated_broad_actor_assigns_capable_same_tenant_target(app) -> None:
    item = _item()
    session = AssignSession(
        item=item,
        target=_target(),
        target_roles=["membro", "lider_celula"],
    )
    client = _client(
        app,
        session=session,
        current_user=_current_user("lider_celula", "lider_g12"),
    )

    response = _assign(client)

    assert response.status_code == 200, response.text
    assert response.json()["responsavelId"] == _TARGET_ID
    assert len(session.target_statements) == 1
    target_where = _where_sql(session.target_statements[0])
    assert "app_users.igreja_id" in target_where, target_where
    assert "app_users.status" in target_where, target_where
    assert "app_users.status is null" in target_where, target_where
    assert "app_users.status = 'ativo'" in target_where, target_where
    assert len(session.role_statements) == 1
    role_where = _where_sql(session.role_statements[0])
    assert "user_roles.user_id" in role_where, role_where
    assert "user_roles.igreja_id" in role_where, role_where
    assert item.responsavel_id == uuid.UUID(_TARGET_ID)
    assert session.flushes == 1
    assert session.commits == 1


@pytest.mark.parametrize(
    ("holder", "holder_roles"),
    [
        (_holder(status="revogado"), ["lider_celula"]),
        (_holder(status="convidado"), ["lider_celula"]),
        (_holder(), ["membro"]),
        (None, []),
    ],
    ids=["revoked", "invited", "demoted", "missing"],
)
def test_broad_actor_transfers_assumed_item_from_orphaned_holder(
    app, holder, holder_roles
) -> None:
    """Revocation/demotion of the old holder must not strand queue work."""

    item = _item(
        item_status="assumido",
        responsavel_id=_OLD_HOLDER_ID,
    )
    session = AssignSession(
        item=item,
        target=_target(),
        target_roles=["lider_celula"],
        current_holder=holder,
        current_holder_roles=holder_roles,
    )
    client = _client(app, session=session, current_user=_current_user("pastor"))

    response = _assign(client)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "assumido",
        "itemId": _ITEM_ID,
        "responsavelId": _TARGET_ID,
    }
    assert item.responsavel_id == uuid.UUID(_TARGET_ID)
    assert session.flushes == 1
    assert session.commits == 1


def test_broad_actor_cannot_silently_overwrite_live_capable_holder(app) -> None:
    item = _item(
        item_status="assumido",
        responsavel_id=_OLD_HOLDER_ID,
    )
    session = AssignSession(
        item=item,
        target=_target(),
        target_roles=["lider_celula"],
        current_holder=_holder(),
        current_holder_roles=["lider_celula"],
    )
    client = _client(app, session=session, current_user=_current_user("pastor"))

    response = _assign(client)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["responsavelId"] == _OLD_HOLDER_ID
    assert item.responsavel_id == uuid.UUID(_OLD_HOLDER_ID)
    assert session.flushes == 0
    assert session.commits == 0


def test_restricted_assume_cannot_steal_an_assumed_item(app) -> None:
    item = _item(
        item_status="assumido",
        responsavel_id=_OLD_HOLDER_ID,
    )
    session = AssignSession(item=item)
    client = _client(
        app,
        session=session,
        current_user=_current_user("lider_celula"),
    )

    response = client.post(
        f"/work-queue/{_ITEM_ID}/action",
        headers=_AUTH,
        json={"action": "assume"},
    )

    assert response.status_code == 409, response.text
    assert item.responsavel_id == uuid.UUID(_OLD_HOLDER_ID)
    assert session.flushes == 0
    assert session.commits == 0


@pytest.mark.parametrize("item_status", ["resolvido", "cancelado"])
def test_non_operational_status_cannot_be_reopened_by_uuid(
    app, item_status
) -> None:
    item = _item(item_status=item_status)
    session = AssignSession(item=item)
    client = _client(app, session=session, current_user=_current_user("pastor"))

    response = client.post(
        f"/work-queue/{_ITEM_ID}/action",
        headers=_AUTH,
        json={"action": "assume"},
    )

    assert response.status_code == 409, response.text
    assert item.status == item_status
    assert item.responsavel_id is None
    assert session.flushes == 0
    assert session.commits == 0


def test_legacy_null_status_can_be_assumed_and_normalized(app) -> None:
    item = _item(item_status=None)
    session = AssignSession(item=item)
    client = _client(app, session=session, current_user=_current_user("pastor"))

    response = client.post(
        f"/work-queue/{_ITEM_ID}/action",
        headers=_AUTH,
        json={"action": "assume"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "assumido"
    assert response.json()["responsavelId"] == _ACTOR_ID
    assert item.status == "assumido"
    assert item.responsavel_id == uuid.UUID(_ACTOR_ID)
    assert session.flushes == 1
    assert session.commits == 1


@pytest.mark.parametrize(
    "target",
    [
        None,
        _target(igreja_id=_OTHER_IGREJA_ID),
        _target(status="revogado"),
        _target(status="convidado"),
    ],
    ids=["missing", "cross-tenant", "revoked", "invited"],
)
def test_missing_cross_tenant_or_revoked_target_is_generic_404_without_write(
    app, target
) -> None:
    item = _item()
    session = AssignSession(
        item=item,
        target=target,
        target_roles=["admin"],
    )
    client = _client(app, session=session, current_user=_current_user("pastor"))

    response = _assign(client)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Responsável não encontrado"
    assert len(session.target_statements) == 1
    assert session.role_statements == []
    _assert_no_write(session, item)


@pytest.mark.parametrize(
    "target",
    [
        _target(igreja_id=_OTHER_IGREJA_ID),
        _target(status="revogado"),
        _target(status="convidado"),
    ],
    ids=["cross-tenant", "revoked", "invited"],
)
def test_transfer_keeps_old_holder_when_new_target_is_ineligible(app, target) -> None:
    item = _item(
        item_status="assumido",
        responsavel_id=_OLD_HOLDER_ID,
    )
    session = AssignSession(
        item=item,
        target=target,
        target_roles=["admin"],
    )
    client = _client(app, session=session, current_user=_current_user("pastor"))

    response = _assign(client)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Responsável não encontrado"
    assert item.status == "assumido"
    assert item.responsavel_id == uuid.UUID(_OLD_HOLDER_ID)
    assert session.flushes == 0
    assert session.commits == 0


def test_target_without_capable_accumulated_role_is_422_without_write(app) -> None:
    item = _item()
    session = AssignSession(
        item=item,
        target=_target(),
        target_roles=["membro", "lider_mult"],
    )
    client = _client(app, session=session, current_user=_current_user("pastor"))

    response = _assign(client)

    assert response.status_code == 422, response.text
    assert len(session.role_statements) == 1
    _assert_no_write(session, item)


def test_accumulated_admin_target_can_resolve_unknown_item_type(app) -> None:
    item = _item(tipo="novo_tipo")
    session = AssignSession(
        item=item,
        target=_target(),
        target_roles=["membro", "admin"],
    )
    client = _client(app, session=session, current_user=_current_user("admin"))

    response = _assign(client)

    assert response.status_code == 200, response.text
    assert item.responsavel_id == uuid.UUID(_TARGET_ID)
    assert session.flushes == 1
    assert session.commits == 1
