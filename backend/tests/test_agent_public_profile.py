"""HTTP contract for the per-tenant structured public agent profile."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.models import AgentConfig
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_TENANT_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
_TENANT_B = uuid.UUID("00000000-0000-0000-0000-000000000002")


class _Result:
    def __init__(self, scalar: object | None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> object | None:
        return self._scalar


class PublicProfileSession(FakeSession):
    """Fake that applies the router's actual AgentConfig tenant predicate."""

    def __init__(self, *, store: list[object] | None = None, roles=None) -> None:
        super().__init__(app_user=make_app_user(), roles=roles or ["admin"])
        self.store = store or []
        self.agent_config_queries: list[object] = []

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
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is AgentConfig:
            self.agent_config_queries.append(statement)
            predicates = self._predicates(statement)
            row = next(
                (
                    config
                    for config in self.store
                    if all(str(getattr(config, key, None)) == value for key, value in predicates.items())
                ),
                None,
            )
            return _Result(row)
        return super().execute(statement, params)


def _config(
    tenant_id: uuid.UUID = _TENANT_A,
    *,
    ativo: bool = False,
    public_info: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        igreja_id=tenant_id,
        nome="Agente sintético",
        tom="acolhedor",
        comportamento="Tom externo que não pode ser alterado.",
        ativo=ativo,
        informacoes_publicas={} if public_info is None else public_info,
    )


def _client(app, session: PublicProfileSession) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "enderecoIgreja": "Rua da Igreja, 100",
        "horariosCulto": "Domingo, 19:00",
        "celulas": [
            {"bairro": "Centro", "nome": "Esperança", "encontro": "terça, 19h"}
        ],
    }
    payload.update(overrides)
    return payload


def test_get_public_profile_returns_empty_shape_when_config_is_absent(app) -> None:
    response = _client(app, PublicProfileSession()).get(
        "/agent/public-profile", headers=_AUTH
    )

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "informacoesPublicas": {
            "enderecoIgreja": None,
            "horariosCulto": None,
            "celulas": [],
        },
    }


def test_put_public_profile_requires_existing_config_without_creating_one(app) -> None:
    session = PublicProfileSession()

    response = _client(app, session).put(
        "/agent/public-profile", headers=_AUTH, json=_payload()
    )

    assert response.status_code == 409
    assert session.added == []
    assert session.commits == 0


def test_admin_replaces_own_public_profile_in_canonical_snake_case(app) -> None:
    config = _config(ativo=False)
    session = PublicProfileSession(store=[_config(_TENANT_B), config])

    response = _client(app, session).put(
        "/agent/public-profile", headers=_AUTH, json=_payload()
    )

    assert response.status_code == 200
    assert response.json() == {
        "configured": True,
        "informacoesPublicas": {
            "enderecoIgreja": "Rua da Igreja, 100",
            "horariosCulto": "Domingo, 19:00",
            "celulas": [
                {"bairro": "Centro", "nome": "Esperança", "encontro": "terça, 19h"}
            ],
        },
    }
    assert config.informacoes_publicas == {
        "endereco_igreja": "Rua da Igreja, 100",
        "horarios_culto": "Domingo, 19:00",
        "celulas": [
            {"bairro": "Centro", "nome": "Esperança", "encontro": "terça, 19h"}
        ],
    }
    assert config.ativo is False
    assert config.comportamento == "Tom externo que não pode ser alterado."
    assert session.commits == 1
    assert all(
        "agent_configs.igreja_id" in str(query)
        for query in session.agent_config_queries
    )


def test_put_public_profile_replaces_omitted_fields_with_empty_values(app) -> None:
    config = _config(
        public_info={
            "endereco_igreja": "Rua anterior, 10",
            "horarios_culto": "Sábado, 18:00",
            "celulas": [{"bairro": "Centro", "nome": "Anterior", "encontro": None}],
        }
    )
    session = PublicProfileSession(store=[config])

    response = _client(app, session).put(
        "/agent/public-profile",
        headers=_AUTH,
        json={"enderecoIgreja": "Rua atual, 20"},
    )

    assert response.status_code == 200
    assert config.informacoes_publicas == {
        "endereco_igreja": "Rua atual, 20",
        "horarios_culto": None,
        "celulas": [],
    }


@pytest.mark.parametrize(
    "payload",
    (
        _payload(enderecoIgreja="NOME-SINTETICO-90000-0000"),
        _payload(ativo=True),
        {"endereco_igreja": "Rua sintética, 100", "celulas": []},
    ),
)
def test_public_profile_rejects_extra_or_private_input_without_echoing_it(
    app,
    payload: dict[str, object],
) -> None:
    config = _config()
    session = PublicProfileSession(store=[config])
    secret = "NOME-SINTETICO-90000-0000"

    response = _client(app, session).put(
        "/agent/public-profile",
        headers=_AUTH,
        json=payload,
    )

    assert response.status_code == 422
    assert secret not in response.text
    assert config.informacoes_publicas == {}
    assert session.commits == 0


def test_public_profile_is_admin_only(app) -> None:
    response = _client(
        app, PublicProfileSession(store=[_config()], roles=["lider_celula"])
    ).get("/agent/public-profile", headers=_AUTH)

    assert response.status_code == 403
