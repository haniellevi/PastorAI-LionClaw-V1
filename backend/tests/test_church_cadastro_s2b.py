"""S2b church-cadastro endpoints use the authenticated tenant only."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Igreja
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user


_AUTH = {"Authorization": "Bearer good"}
_TENANT_A = uuid.UUID(make_app_user().igreja_id)


class _Result:
    def __init__(self, *, scalar=None, scalars=()) -> None:
        self._scalar = scalar
        self._scalars = list(scalars)

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class CadastroSession:
    def __init__(self, *, igreja, roles) -> None:
        self.igreja = igreja
        self.roles = roles
        self.commits = 0
        self.igreja_queries: list[str] = []

    def execute(self, statement, params=None):
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is AppUser:
            return _Result(scalar=make_app_user())
        if entity is Igreja:
            sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
            self.igreja_queries.append(sql)
            return _Result(scalar=self.igreja)
        return _Result(scalars=self.roles)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:  # pragma: no cover
        pass


def _church(*, address=None, hours=None):
    return SimpleNamespace(
        id=_TENANT_A,
        nome="Igreja Sintética",
        logo_path=None,
        endereco_institucional=address,
        horarios_culto=hours,
    )


def _client(app, session: CadastroSession) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def test_capability_is_authenticated_but_does_not_read_church_data(app) -> None:
    session = CadastroSession(igreja=_church(), roles=["lider_celula"])

    response = _client(app, session).get(
        "/igreja/cadastro/capabilities", headers=_AUTH
    )

    assert response.status_code == 200
    assert response.json() == {"version": 1}
    assert session.igreja_queries == []


def test_leader_can_read_capability_but_cannot_read_or_write_cadastro(app) -> None:
    session = CadastroSession(igreja=_church(), roles=["lider_celula"])
    client = _client(app, session)

    assert client.get("/igreja/cadastro/capabilities", headers=_AUTH).status_code == 200
    assert client.get("/igreja/cadastro", headers=_AUTH).status_code == 403
    assert (
        client.put(
            "/igreja/cadastro",
            headers=_AUTH,
            json={"enderecoInstitucional": None, "horariosCulto": None},
        ).status_code
        == 403
    )
    assert session.igreja_queries == []
    assert session.commits == 0


def test_admin_reads_and_replaces_only_own_canonical_church_fields(app) -> None:
    igreja = _church(address="Endereço anterior", hours="Sábado, 18:00")
    session = CadastroSession(igreja=igreja, roles=["admin"])
    client = _client(app, session)

    get_response = client.get("/igreja/cadastro", headers=_AUTH)
    put_response = client.put(
        "/igreja/cadastro",
        headers=_AUTH,
        json={
            "enderecoInstitucional": "Avenida Institucional, 10",
            "horariosCulto": "Domingo, 19:00",
        },
    )

    assert get_response.status_code == 200
    assert get_response.json() == {
        "enderecoInstitucional": "Endereço anterior",
        "horariosCulto": "Sábado, 18:00",
    }
    assert put_response.status_code == 200
    assert put_response.json() == {
        "enderecoInstitucional": "Avenida Institucional, 10",
        "horariosCulto": "Domingo, 19:00",
    }
    assert igreja.endereco_institucional == "Avenida Institucional, 10"
    assert igreja.horarios_culto == "Domingo, 19:00"
    assert session.commits == 1
    assert all(str(_TENANT_A).replace("-", "") in sql for sql in session.igreja_queries)


def test_cadastro_rejects_extra_or_oversized_payload_without_writing(app) -> None:
    igreja = _church()
    session = CadastroSession(igreja=igreja, roles=["admin"])
    client = _client(app, session)

    response = client.put(
        "/igreja/cadastro",
        headers=_AUTH,
        json={"enderecoInstitucional": "x" * 401, "tenant": "forjado"},
    )

    assert response.status_code == 422
    assert igreja.endereco_institucional is None
    assert igreja.horarios_culto is None
    assert session.commits == 0


def test_cadastro_requires_admin(app) -> None:
    session = CadastroSession(igreja=_church(), roles=["pastor"])

    response = _client(app, session).put(
        "/igreja/cadastro",
        headers=_AUTH,
        json={"enderecoInstitucional": None, "horariosCulto": None},
    )

    assert response.status_code == 403
