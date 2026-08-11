"""Row-level read scope for GET /cells and GET /cells/{id}."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.models import AppUser, Celula, CellAlert
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user

_AUTH = {"Authorization": "Bearer good"}
_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_OTHER_IGREJA_ID = "00000000-0000-0000-0000-000000000002"
_APP_USER_ID = "00000000-0000-0000-0000-0000000000a1"
_ACTOR_PESSOA_ID = "00000000-0000-0000-0000-0000000000b1"
_OTHER_PESSOA_ID = "00000000-0000-0000-0000-0000000000b2"
_CELL_ID = "00000000-0000-0000-0000-0000000000e1"
_INACTIVE_CELL_ID = "00000000-0000-0000-0000-0000000000e2"


class _Result:
    def __init__(self, *, scalar=None, scalars=()) -> None:
        self._scalar = scalar
        self._scalars = list(scalars)

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
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


class CellScopeSession:
    def __init__(
        self,
        *,
        actor_pessoa_id: str | None,
        cells=(),
        alerts=(),
        deny_scope_marker: str | None = None,
    ) -> None:
        self.actor_pessoa_id = actor_pessoa_id
        self.cells = list(cells)
        self.alerts = list(alerts)
        self.deny_scope_marker = deny_scope_marker
        self.actor_lookups = 0
        self.cell_statements: list = []
        self.alert_statements: list = []

    def _visible_cells(self, statement):
        where = _where_sql(statement)
        if "false" in where:
            return []
        if self.deny_scope_marker and self.deny_scope_marker in where:
            return []

        rows = list(self.cells)
        if "celulas.igreja_id" in where:
            rows = [cell for cell in rows if str(cell.igreja_id) == _IGREJA_ID]
        if "celulas.ativo is true" in where:
            rows = [cell for cell in rows if cell.ativo]
        return rows

    def execute(self, statement, params=None) -> _Result:
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entity = descriptions[0].get("entity") if descriptions else None
        name = descriptions[0].get("name") if descriptions else None
        sql = _compiled(statement)

        if entity is AppUser and name == "pessoa_id":
            self.actor_lookups += 1
            return _Result(scalar=self.actor_pessoa_id)

        if "count(" in sql and "celulas" in sql:
            self.cell_statements.append(statement)
            return _Result(scalar=len(self._visible_cells(statement)))

        if entity is Celula:
            self.cell_statements.append(statement)
            rows = self._visible_cells(statement)
            return _Result(
                scalar=(rows[0] if rows else None),
                scalars=rows,
            )

        if entity is CellAlert:
            self.alert_statements.append(statement)
            return _Result(scalars=self.alerts)

        return _Result()

    def close(self) -> None:  # pragma: no cover
        pass


def _cell(
    *,
    cell_id=_CELL_ID,
    igreja_id=_IGREJA_ID,
    lider_id=_ACTOR_PESSOA_ID,
    ativo=True,
):
    return SimpleNamespace(
        id=uuid.UUID(cell_id),
        igreja_id=uuid.UUID(igreja_id),
        nome="Célula Escopada",
        lider_id=uuid.UUID(lider_id) if lider_id else None,
        dia_reuniao="terça",
        cobertura_espiritual="Rede Azul",
        anfitriao_id=None,
        auxiliar_id=None,
        endereco=None,
        horario="20:00",
        link_grupo=None,
        link_localizacao=None,
        mensagem_convite=None,
        ativo=ativo,
        created_at=None,
    )


def _alert():
    return SimpleNamespace(
        id=uuid.UUID("00000000-0000-0000-0000-0000000000f1"),
        pessoa_id=uuid.UUID("00000000-0000-0000-0000-0000000000d1"),
        gatilho="ausencia",
        acao_esperada="contato",
        tratado=False,
        created_at=None,
    )


def _current_user(*roles: str) -> CurrentUser:
    return CurrentUser(
        app_user_id=_APP_USER_ID,
        clerk_user_id="clerk_cells_scope",
        igreja_id=_IGREJA_ID,
        email="scope@igrejapiloto.com.br",
        nome="Scope",
        roles=frozenset(roles),
    )


def _client(app, *, session: CellScopeSession, current_user: CurrentUser):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


def _assert_leader_scope(statement) -> None:
    where = _where_sql(statement)
    assert "celulas.igreja_id" in where, where
    assert "celulas.lider_id" in where, where
    assert uuid.UUID(_IGREJA_ID).hex in where, where
    assert uuid.UUID(_ACTOR_PESSOA_ID).hex in where, where
    assert "celula_membro" not in where, where
    assert "celulas.ativo" not in where, where


def _assert_member_scope(statement) -> None:
    where = _where_sql(statement)
    assert "celulas.igreja_id" in where, where
    assert "celulas.ativo is true" in where, where
    assert "celula_membro" in where, where
    assert "celula_membro.igreja_id" in where, where
    assert "celula_membro.pessoa_id" in where, where
    assert "celula_membro.ativo is true" in where, where
    assert uuid.UUID(_IGREJA_ID).hex in where, where
    assert uuid.UUID(_ACTOR_PESSOA_ID).hex in where, where


def _assert_wide_detail_scope(statement) -> None:
    where = _where_sql(statement)
    assert "celulas.id" in where, where
    assert "celulas.igreja_id" not in where, where
    assert "celulas.lider_id" not in where, where
    assert "celulas.ativo" not in where, where
    assert "celula_membro" not in where, where


def test_cell_leader_scope_reaches_count_and_rows_and_keeps_inactive_cells(app) -> None:
    cells = [_cell(), _cell(cell_id=_INACTIVE_CELL_ID, ativo=False)]
    session = CellScopeSession(actor_pessoa_id=_ACTOR_PESSOA_ID, cells=cells)
    client = _client(
        app,
        session=session,
        current_user=_current_user("membro", "lider_celula"),
    )

    response = client.get("/cells", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2
    assert {item["id"] for item in response.json()["items"]} == {
        _CELL_ID,
        _INACTIVE_CELL_ID,
    }
    assert session.actor_lookups == 1
    assert len(session.cell_statements) == 2
    for statement in session.cell_statements:
        _assert_leader_scope(statement)


def test_member_scope_reaches_count_and_rows_with_canonical_active_link(app) -> None:
    session = CellScopeSession(actor_pessoa_id=_ACTOR_PESSOA_ID, cells=[_cell()])
    client = _client(app, session=session, current_user=_current_user("membro"))

    response = client.get("/cells", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert session.actor_lookups == 1
    assert len(session.cell_statements) == 2
    for statement in session.cell_statements:
        _assert_member_scope(statement)


@pytest.mark.parametrize(
    "wide_role", ["admin", "pastor", "lider_g12", "lider_mult", "operador"]
)
def test_accumulated_wide_role_wins_over_cell_leader_scope(app, wide_role) -> None:
    session = CellScopeSession(actor_pessoa_id=None, cells=[_cell()])
    client = _client(
        app,
        session=session,
        current_user=_current_user("lider_celula", wide_role),
    )

    response = client.get("/cells", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert session.actor_lookups == 0
    assert len(session.cell_statements) == 2
    for statement in session.cell_statements:
        assert _where_sql(statement) == ""


def test_effective_cell_leader_detail_loads_full_alerts(app) -> None:
    session = CellScopeSession(
        actor_pessoa_id=_ACTOR_PESSOA_ID,
        cells=[_cell()],
        alerts=[_alert()],
    )
    client = _client(
        app,
        session=session,
        current_user=_current_user("membro", "lider_celula"),
    )

    response = client.get(f"/cells/{_CELL_ID}", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert len(response.json()["alerts"]) == 1
    assert session.actor_lookups == 2
    assert len(session.cell_statements) == 1
    _assert_leader_scope(session.cell_statements[0])
    assert len(session.alert_statements) == 1


def test_member_detail_omits_alerts_without_querying_them(app) -> None:
    session = CellScopeSession(
        actor_pessoa_id=_ACTOR_PESSOA_ID,
        cells=[_cell(lider_id=_OTHER_PESSOA_ID)],
        alerts=[_alert()],
    )
    client = _client(app, session=session, current_user=_current_user("membro"))

    response = client.get(f"/cells/{_CELL_ID}", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert response.json()["alerts"] == []
    assert session.actor_lookups == 2
    assert len(session.cell_statements) == 1
    _assert_member_scope(session.cell_statements[0])
    assert len(session.alert_statements) == 0


@pytest.mark.parametrize("role", ["admin", "pastor"])
def test_pastoral_roles_receive_full_alerts_without_actor_lookup(app, role) -> None:
    session = CellScopeSession(
        actor_pessoa_id=None,
        cells=[_cell(lider_id=_OTHER_PESSOA_ID)],
        alerts=[_alert()],
    )
    client = _client(app, session=session, current_user=_current_user(role))

    response = client.get(f"/cells/{_CELL_ID}", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert len(response.json()["alerts"]) == 1
    assert session.actor_lookups == 0
    assert len(session.cell_statements) == 1
    _assert_wide_detail_scope(session.cell_statements[0])
    assert len(session.alert_statements) == 1


@pytest.mark.parametrize("role", ["lider_g12", "lider_mult", "operador"])
def test_nonpastoral_wide_role_omits_other_peoples_alerts(app, role) -> None:
    session = CellScopeSession(
        actor_pessoa_id=_ACTOR_PESSOA_ID,
        cells=[_cell(lider_id=_OTHER_PESSOA_ID)],
        alerts=[_alert()],
    )
    client = _client(app, session=session, current_user=_current_user(role))

    response = client.get(f"/cells/{_CELL_ID}", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert response.json()["alerts"] == []
    assert session.actor_lookups == 1
    assert len(session.cell_statements) == 1
    _assert_wide_detail_scope(session.cell_statements[0])
    assert len(session.alert_statements) == 0


def test_accumulated_pastor_role_wins_and_receives_full_alerts(app) -> None:
    session = CellScopeSession(
        actor_pessoa_id=None,
        cells=[_cell(lider_id=_OTHER_PESSOA_ID)],
        alerts=[_alert()],
    )
    client = _client(
        app,
        session=session,
        current_user=_current_user("membro", "operador", "pastor"),
    )

    response = client.get(f"/cells/{_CELL_ID}", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert len(response.json()["alerts"]) == 1
    assert session.actor_lookups == 0
    _assert_wide_detail_scope(session.cell_statements[0])
    assert len(session.alert_statements) == 1


def test_accumulated_wide_role_can_receive_alerts_as_effective_leader(app) -> None:
    session = CellScopeSession(
        actor_pessoa_id=_ACTOR_PESSOA_ID,
        cells=[_cell()],
        alerts=[_alert()],
    )
    client = _client(
        app,
        session=session,
        current_user=_current_user("membro", "lider_celula", "lider_g12"),
    )

    response = client.get(f"/cells/{_CELL_ID}", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert len(response.json()["alerts"]) == 1
    assert session.actor_lookups == 1
    _assert_wide_detail_scope(session.cell_statements[0])
    assert len(session.alert_statements) == 1


def test_member_cannot_list_or_open_inactive_linked_cell(app) -> None:
    session = CellScopeSession(
        actor_pessoa_id=_ACTOR_PESSOA_ID,
        cells=[_cell(ativo=False, lider_id=_OTHER_PESSOA_ID)],
        alerts=[_alert()],
    )
    client = _client(app, session=session, current_user=_current_user("membro"))

    list_response = client.get("/cells", headers=_AUTH)
    detail_response = client.get(f"/cells/{_CELL_ID}", headers=_AUTH)

    assert list_response.status_code == 200, list_response.text
    assert list_response.json()["total"] == 0
    assert list_response.json()["items"] == []
    assert detail_response.status_code == 404, detail_response.text
    assert session.actor_lookups == 2
    assert len(session.cell_statements) == 3
    for statement in session.cell_statements:
        _assert_member_scope(statement)
    assert len(session.alert_statements) == 0


def test_effective_leader_can_open_inactive_cell_and_receive_alerts(app) -> None:
    session = CellScopeSession(
        actor_pessoa_id=_ACTOR_PESSOA_ID,
        cells=[_cell(ativo=False)],
        alerts=[_alert()],
    )
    client = _client(
        app,
        session=session,
        current_user=_current_user("lider_celula"),
    )

    response = client.get(f"/cells/{_CELL_ID}", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert response.json()["ativo"] is False
    assert len(response.json()["alerts"]) == 1
    assert session.actor_lookups == 2
    _assert_leader_scope(session.cell_statements[0])
    assert len(session.alert_statements) == 1


def test_member_scope_rejects_cross_tenant_cell_before_alerts(app) -> None:
    session = CellScopeSession(
        actor_pessoa_id=_ACTOR_PESSOA_ID,
        cells=[
            _cell(
                igreja_id=_OTHER_IGREJA_ID,
                lider_id=_OTHER_PESSOA_ID,
            )
        ],
        alerts=[_alert()],
    )
    client = _client(app, session=session, current_user=_current_user("membro"))

    list_response = client.get("/cells", headers=_AUTH)
    detail_response = client.get(f"/cells/{_CELL_ID}", headers=_AUTH)

    assert list_response.status_code == 200, list_response.text
    assert list_response.json()["total"] == 0
    assert list_response.json()["items"] == []
    assert detail_response.status_code == 404, detail_response.text
    assert len(session.cell_statements) == 3
    for statement in session.cell_statements:
        _assert_member_scope(statement)
    assert len(session.alert_statements) == 0


@pytest.mark.parametrize(
    ("role", "scope_marker"),
    [("lider_celula", "celulas.lider_id"), ("membro", "celula_membro")],
)
def test_direct_cell_access_outside_scope_is_404_before_alerts(
    app, role, scope_marker
) -> None:
    session = CellScopeSession(
        actor_pessoa_id=_ACTOR_PESSOA_ID,
        cells=[_cell()],
        alerts=[_alert()],
        deny_scope_marker=scope_marker,
    )
    client = _client(app, session=session, current_user=_current_user(role))

    response = client.get(f"/cells/{_CELL_ID}", headers=_AUTH)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Célula não encontrada"
    assert len(session.cell_statements) == 1
    assert len(session.alert_statements) == 0


def test_user_without_linked_pessoa_gets_empty_list_and_detail_404(app) -> None:
    session = CellScopeSession(actor_pessoa_id=None, cells=[_cell()], alerts=[_alert()])
    client = _client(app, session=session, current_user=_current_user("membro"))

    list_response = client.get("/cells", headers=_AUTH)
    detail_response = client.get(f"/cells/{_CELL_ID}", headers=_AUTH)

    assert list_response.status_code == 200, list_response.text
    assert list_response.json() == {
        "items": [],
        "page": 1,
        "pageSize": 20,
        "total": 0,
    }
    assert detail_response.status_code == 404, detail_response.text
    assert session.actor_lookups == 2
    assert len(session.cell_statements) == 3
    for statement in session.cell_statements:
        assert "false" in _where_sql(statement)
    assert len(session.alert_statements) == 0
