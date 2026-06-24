"""Fila de requisição admin → master (#10b Fase 1) — lado do tenant (admin).

O admin não edita o comportamento do agente (PUT /agent/config = 403); abre uma
requisição por mensagem livre (POST /agent/config/requests) e acompanha o
histórico (GET). Cobre o caminho de escrita com um fake que suporta add/flush.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AgentConfigRequest, AppUser
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}


class _Scalars:
    def __init__(self, items) -> None:
        self._items = items

    def all(self) -> list:
        return list(self._items)


class _Result:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self) -> _Scalars:
        return _Scalars(self._scalars)


class _AgentReqDB:
    """Fake com gate (AppUser/roles) + roteamento de AgentConfigRequest + add/flush."""

    def __init__(self, app_user, roles, requests=None) -> None:
        self.app_user = app_user
        self.roles = roles
        self.requests = requests or []
        self.added: list = []
        self.committed = False

    def execute(self, statement, params=None) -> _Result:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        if not descs:  # set_config(...) text clause (RLS context)
            return _Result()
        ent = descs[0].get("entity")
        if ent is AppUser:
            return _Result(scalar=self.app_user)
        if ent is AgentConfigRequest:
            return _Result(scalars=self.requests)
        return _Result(scalars=self.roles)  # UserRole.papel projection

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


def _wire(app, db) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def test_admin_creates_config_request(app) -> None:
    db = _AgentReqDB(make_app_user(), ["admin"])
    client = _wire(app, db)
    resp = client.post(
        "/agent/config/requests",
        headers=_AUTH,
        json={"mensagem": "Pode deixar o agente mais formal?"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["mensagem"] == "Pode deixar o agente mais formal?"
    assert body["status"] == "pendente"
    assert db.committed is True
    # Escopado: igreja + solicitante vêm do current_user.
    created = next(o for o in db.added if isinstance(o, AgentConfigRequest))
    assert str(created.igreja_id) == "00000000-0000-0000-0000-000000000001"
    assert str(created.solicitante_user_id) == "00000000-0000-0000-0000-0000000000a1"


def test_admin_lists_own_config_requests(app) -> None:
    req = SimpleNamespace(
        id=uuid.uuid4(),
        mensagem="Mudar saudação",
        status="atendida",
        resposta="Feito",
        criado_em=None,
        resolvido_em=None,
    )
    db = _AgentReqDB(make_app_user(), ["admin"], requests=[req])
    client = _wire(app, db)
    resp = client.get("/agent/config/requests", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["mensagem"] == "Mudar saudação"
    assert body[0]["resposta"] == "Feito"


def test_config_request_requires_auth(app) -> None:
    db = _AgentReqDB(make_app_user(), ["admin"])
    client = _wire(app, db)
    resp = client.post("/agent/config/requests", json={"mensagem": "oi"})
    assert resp.status_code == 401


def test_config_request_rejects_empty_mensagem(app) -> None:
    db = _AgentReqDB(make_app_user(), ["admin"])
    client = _wire(app, db)
    resp = client.post(
        "/agent/config/requests", headers=_AUTH, json={"mensagem": "   "}
    )
    assert resp.status_code == 422


def test_config_request_blocks_non_admin(app) -> None:
    db = _AgentReqDB(make_app_user(), ["lider_celula"])
    client = _wire(app, db)
    resp = client.post(
        "/agent/config/requests", headers=_AUTH, json={"mensagem": "oi"}
    )
    assert resp.status_code == 403
