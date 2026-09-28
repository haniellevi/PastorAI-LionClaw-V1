"""The legacy public-profile route reads canonical church facts only."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.models import AgentConfig, Celula, Igreja
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_TENANT_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
_TENANT_B = uuid.UUID("00000000-0000-0000-0000-000000000002")


class _Result:
    def __init__(self, *, one=None, rows=()) -> None:
        self._one = one
        self._rows = rows

    def one_or_none(self):
        return self._one

    def all(self):
        return list(self._rows)


class PublicProfileSession(FakeSession):
    """Apply tenant and publication predicates from the real SELECTs."""

    def __init__(self, *, churches=None, cells=(), roles=None) -> None:
        super().__init__(app_user=make_app_user(), roles=roles or ["admin"])
        self.churches = churches or {}
        self.cells = cells
        self.public_queries = []

    @staticmethod
    def _predicates(statement: object) -> dict[str, str]:
        predicates: dict[str, str] = {}
        clause = getattr(statement, "whereclause", None)
        stack = [clause] if clause is not None else []
        while stack:
            node = stack.pop()
            left = getattr(node, "left", None)
            right = getattr(node, "right", None)
            if left is not None and right is not None:
                key = getattr(left, "key", None)
                value = getattr(right, "value", None)
                if key is not None and value is not None:
                    predicates[key] = str(value)
                continue
            stack.extend(getattr(node, "clauses", []) or [])
        return predicates

    def execute(self, statement, params=None):
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entities = {item.get("entity") for item in descriptions}
        names = [item.get("name") for item in descriptions]
        if AgentConfig in entities:
            raise AssertionError("legacy AgentConfig JSON must not be queried")
        if entities == {Igreja} and names == ["endereco_institucional", "horarios_culto"]:
            self.public_queries.append(statement)
            tenant_id = self._predicates(statement).get("id")
            assert tenant_id is not None
            return _Result(one=self.churches.get(tenant_id))
        if entities == {Celula}:
            assert names == ["bairro", "nome", "dia_reuniao", "horario"]
            sql = str(statement)
            assert "celulas.ativo IS true" in sql
            assert "celulas.divulgar_whatsapp IS true" in sql
            assert "celulas.bairro IS NOT NULL" in sql
            assert statement._limit_clause.value == 5
            self.public_queries.append(statement)
            tenant_id = self._predicates(statement).get("igreja_id")
            assert tenant_id is not None
            rows = [
                (cell.bairro, cell.nome, cell.dia_reuniao, cell.horario)
                for cell in self.cells
                if str(cell.igreja_id) == tenant_id
                and cell.ativo and cell.divulgar_whatsapp and cell.bairro is not None
            ]
            return _Result(rows=rows[:5])
        return super().execute(statement, params)


def _cell(tenant_id: uuid.UUID, **overrides):
    values = {
        "igreja_id": tenant_id,
        "bairro": "Centro",
        "nome": "Esperança",
        "dia_reuniao": "Terça-feira",
        "horario": "19:00",
        "ativo": True,
        "divulgar_whatsapp": True,
        "endereco": "RUA-RESIDENCIAL-PRIVADA",
        "link_grupo": "LINK-PRIVADO",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _client(app, session: PublicProfileSession) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def test_get_public_profile_returns_empty_shape_without_canonical_church(app) -> None:
    session = PublicProfileSession(churches={str(_TENANT_B): ("Rua B", "Sábado")})
    response = _client(app, session).get("/agent/public-profile", headers=_AUTH)

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "informacoesPublicas": {
            "enderecoIgreja": None,
            "horariosCulto": None,
            "celulas": [],
        },
    }
    assert len(session.public_queries) == 1


def test_get_public_profile_uses_only_tenant_canonical_published_facts(app) -> None:
    session = PublicProfileSession(
        churches={
            str(_TENANT_A): ("Rua Institucional A, 100", "Domingo, 19:00"),
            str(_TENANT_B): ("Rua Institucional B, 200", "Sábado, 18:00"),
        },
        cells=[
            _cell(_TENANT_A),
            _cell(_TENANT_A, bairro="Oculto", divulgar_whatsapp=False),
            _cell(_TENANT_A, bairro="Inativo", ativo=False),
            _cell(_TENANT_A, bairro=None),
            _cell(_TENANT_B, nome="Célula B"),
        ],
    )
    response = _client(app, session).get("/agent/public-profile", headers=_AUTH)

    assert response.status_code == 200
    assert response.json() == {
        "configured": True,
        "informacoesPublicas": {
            "enderecoIgreja": "Rua Institucional A, 100",
            "horariosCulto": "Domingo, 19:00",
            "celulas": [
                {"bairro": "Centro", "nome": "Esperança", "encontro": "Terça-feira, 19:00"}
            ],
        },
    }
    assert "Rua Institucional B" not in response.text
    assert "RUA-RESIDENCIAL-PRIVADA" not in response.text
    assert "LINK-PRIVADO" not in response.text
    assert len(session.public_queries) == 2


def test_get_public_profile_never_falls_back_to_agent_config_json(app) -> None:
    session = PublicProfileSession(churches={str(_TENANT_A): (None, None)})
    response = _client(app, session).get("/agent/public-profile", headers=_AUTH)

    assert response.status_code == 200
    assert response.json()["informacoesPublicas"] == {
        "enderecoIgreja": None,
        "horariosCulto": None,
        "celulas": [],
    }
    assert session.commits == 0


@pytest.mark.parametrize(
    "payload",
    (
        {"enderecoIgreja": "Rua A, 100"},
        {"igrejaId": str(_TENANT_B), "segredo": "NOME-SINTETICO-90000-0000"},
        {},
    ),
)
def test_put_public_profile_is_read_only_without_echo_or_write(app, payload) -> None:
    session = PublicProfileSession(churches={str(_TENANT_A): ("Rua A", "Domingo")})
    response = _client(app, session).put(
        "/agent/public-profile", headers=_AUTH, json=payload
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "public_profile_read_only"
    assert "NOME-SINTETICO-90000-0000" not in response.text
    assert session.public_queries == []
    assert session.added == []
    assert session.commits == 0


@pytest.mark.parametrize("method", ["get", "put"])
def test_public_profile_remains_admin_only(app, method: str) -> None:
    client = _client(app, PublicProfileSession(roles=["lider_celula"]))
    response = getattr(client, method)("/agent/public-profile", headers=_AUTH)
    assert response.status_code == 403
