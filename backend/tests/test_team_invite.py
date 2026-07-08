"""Tests for POST /team/invite — célula/liderança guards (EVT-A1 / achado C-01/C-03).

Cobre o que faltava: nenhum teste existente exercitava a persistência real do
convite (só 401/422 em test_sprint_routers_validation.py). Estes provam, offline
(sem Postgres), que:

  1. um líder de célula ATIVA nunca é aceito como convidado/membro — nem da
     própria célula nem de outra (achado C-01: o front já filtra, mas o backend
     é a fonte de verdade);
  2. célula inativa ou sem líder é rejeitada no convite, na mesma medida que já
     era em POST /contacts/{id}/cell (achado C-03: paridade de validação);
  3. o caminho feliz (pessoa elegível, célula ativa com líder) continua criando
     o app_user + role membro normalmente.

Fake session no estilo dos demais testes de team/cells (entity-routed via
``column_descriptions``, com extração genérica de predicados de igualdade —
inclusive ``func.lower(AppUser.email) == valor``, usado no dedupe de e-mail).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Celula, Pessoa
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.services.brevo import get_brevo_client
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk

_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_ADMIN_APP_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")

_TARGET_CELL = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
_LEADERLESS_CELL = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
_INACTIVE_CELL = uuid.UUID("00000000-0000-0000-0000-0000000000e3")
_LEADER_OF_TARGET = uuid.UUID("00000000-0000-0000-0000-0000000000b0")

_LIDER_PESSOA = uuid.UUID("00000000-0000-0000-0000-0000000000d1")  # lidera outra célula
_LIDER_CELL = uuid.UUID("00000000-0000-0000-0000-0000000000e4")  # célula que _LIDER_PESSOA lidera
_NORMAL_PESSOA = uuid.UUID("00000000-0000-0000-0000-0000000000d2")  # elegível

_AUTH = {"Authorization": "Bearer good"}


# ---------------------------------------------------------------------------
# Fake session — filtro genérico por predicados de igualdade (estilo
# cell_backend_fakes.CellSession), estendido para func.lower(coluna) == valor.
# ---------------------------------------------------------------------------
class _Result:
    def __init__(self, *, scalar=None, scalars_list=None) -> None:
        self._scalar = scalar
        self._scalars_list = list(scalars_list or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        items = self._scalars_list
        return SimpleNamespace(
            all=lambda: list(items),
            first=lambda: (items[0] if items else None),
        )


def _predicates(statement) -> dict[str, object]:
    preds: dict[str, object] = {}
    clause = getattr(statement, "whereclause", None)
    stack = [clause] if clause is not None else []
    while stack:
        node = stack.pop()
        left = getattr(node, "left", None)
        right = getattr(node, "right", None)
        if left is not None and right is not None:
            key = getattr(left, "key", None)
            if key is None:
                # func.lower(Column) == valor: a coluna é o 1º clause interno.
                inner_clauses = getattr(left, "clauses", None)
                if inner_clauses is not None:
                    inner = list(inner_clauses)
                    if inner:
                        key = getattr(inner[0], "key", None)
            value = getattr(right, "value", None)
            if key and value is not None:
                preds[key] = value
            continue
        child_clauses = getattr(node, "clauses", None)
        if child_clauses is not None:
            stack.extend(list(child_clauses))
    return preds


def _wants_active(statement) -> bool:
    clause = getattr(statement, "whereclause", None)
    stack = [clause] if clause is not None else []
    while stack:
        node = stack.pop()
        left = getattr(node, "left", None)
        if left is not None and getattr(left, "key", None) == "ativo":
            return True
        stack.extend(getattr(node, "clauses", []) or [])
    return False


class _InviteSession:
    def __init__(
        self,
        *,
        actor_pessoa_id: uuid.UUID | None = None,
        app_users: list = (),
        pessoas: list = (),
        cells: list = (),
    ) -> None:
        self.actor_pessoa_id = actor_pessoa_id
        self.app_users = list(app_users)
        self.pessoas = list(pessoas)
        self.cells = list(cells)
        self.added: list = []
        self.committed = False

    def execute(self, statement, params=None) -> _Result:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        name = descs[0].get("name") if descs else None

        if ent is AppUser and name == "pessoa_id":
            return _Result(scalar=self.actor_pessoa_id)
        if ent is AppUser:
            preds = _predicates(statement)
            rows = [
                u
                for u in self.app_users
                if all(str(getattr(u, k, None)) == str(v) for k, v in preds.items())
            ]
            return _Result(scalar=(rows[0] if rows else None), scalars_list=rows)
        if ent is Pessoa:
            preds = _predicates(statement)
            rows = [
                p
                for p in self.pessoas
                if all(str(getattr(p, k, None)) == str(v) for k, v in preds.items())
            ]
            return _Result(scalar=(rows[0] if rows else None), scalars_list=rows)
        if ent is Celula:
            preds = _predicates(statement)
            rows = [
                c
                for c in self.cells
                if all(str(getattr(c, k, None)) == str(v) for k, v in preds.items())
            ]
            if _wants_active(statement):
                rows = [c for c in rows if getattr(c, "ativo", True) is True]
            return _Result(scalar=(rows[0] if rows else None), scalars_list=rows)
        return _Result()  # text() do set_tenant_context (RLS GUC)

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:  # pragma: no cover
        pass

    def close(self) -> None:  # pragma: no cover
        pass


class _FakeBrevo:
    """Evita HTTP/config real do Brevo — só precisa não estourar."""

    def send_invite(self, *, to_email: str, nome: str, activation_link: str) -> str:
        return "fake-msg-id"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def _admin() -> CurrentUser:
    return CurrentUser(
        app_user_id=str(_ADMIN_APP_USER_ID),
        clerk_user_id="clerk_admin",
        igreja_id=_IGREJA_ID,
        email="admin@igrejapiloto.com.br",
        nome="Admin",
        roles=frozenset({"admin"}),
    )


def _cell(cell_id: uuid.UUID, *, lider_id: uuid.UUID | None, ativo: bool) -> SimpleNamespace:
    return SimpleNamespace(id=cell_id, igreja_id=_IGREJA_ID, lider_id=lider_id, ativo=ativo)


def _pessoa(pessoa_id: uuid.UUID, *, celula_id=None, email: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=pessoa_id,
        igreja_id=_IGREJA_ID,
        celula_id=celula_id,
        email=email,
        nome="Fulano",
    )


def _client(app, *, session, current_user) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    app.dependency_overrides[get_brevo_client] = lambda: _FakeBrevo()
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1) líder de célula ativa rejeitado como candidato (achado C-01)
# ---------------------------------------------------------------------------
def test_invite_rejects_person_who_leads_an_active_cell(app) -> None:
    target_cell = _cell(_TARGET_CELL, lider_id=_LEADER_OF_TARGET, ativo=True)
    led_cell = _cell(_LIDER_CELL, lider_id=_LIDER_PESSOA, ativo=True)
    candidato = _pessoa(_LIDER_PESSOA, celula_id=None)
    session = _InviteSession(cells=[target_cell, led_cell], pessoas=[candidato])
    client = _client(app, session=session, current_user=_admin())

    resp = client.post(
        "/team/invite",
        json={
            "pessoaId": str(_LIDER_PESSOA),
            "email": "novo@igrejapiloto.com.br",
            "celulaId": str(_TARGET_CELL),
        },
        headers=_AUTH,
    )

    assert resp.status_code == 409
    assert "lidera uma célula ativa" in resp.json()["detail"]
    assert session.added == []
    assert session.committed is False


# ---------------------------------------------------------------------------
# 2) célula inativa rejeitada (achado C-03 — paridade com link_cell)
# ---------------------------------------------------------------------------
def test_invite_rejects_inactive_cell(app) -> None:
    inactive_cell = _cell(_INACTIVE_CELL, lider_id=_LEADER_OF_TARGET, ativo=False)
    session = _InviteSession(cells=[inactive_cell])
    client = _client(app, session=session, current_user=_admin())

    resp = client.post(
        "/team/invite",
        json={
            "nome": "Novo Membro",
            "email": "novo2@igrejapiloto.com.br",
            "celulaId": str(_INACTIVE_CELL),
        },
        headers=_AUTH,
    )

    assert resp.status_code == 409
    assert "inativa" in resp.json()["detail"]
    assert session.added == []
    assert session.committed is False


# ---------------------------------------------------------------------------
# 3) célula sem líder rejeitada (achado C-03)
# ---------------------------------------------------------------------------
def test_invite_rejects_leaderless_cell(app) -> None:
    leaderless_cell = _cell(_LEADERLESS_CELL, lider_id=None, ativo=True)
    session = _InviteSession(cells=[leaderless_cell])
    client = _client(app, session=session, current_user=_admin())

    resp = client.post(
        "/team/invite",
        json={
            "nome": "Novo Membro",
            "email": "novo3@igrejapiloto.com.br",
            "celulaId": str(_LEADERLESS_CELL),
        },
        headers=_AUTH,
    )

    assert resp.status_code == 409
    assert "sem líder" in resp.json()["detail"]
    assert session.added == []
    assert session.committed is False


# ---------------------------------------------------------------------------
# 4) caso feliz continua funcionando
# ---------------------------------------------------------------------------
def test_invite_happy_path_still_works(app) -> None:
    target_cell = _cell(_TARGET_CELL, lider_id=_LEADER_OF_TARGET, ativo=True)
    candidato = _pessoa(_NORMAL_PESSOA, celula_id=None, email=None)
    session = _InviteSession(cells=[target_cell], pessoas=[candidato])
    client = _client(app, session=session, current_user=_admin())

    resp = client.post(
        "/team/invite",
        json={
            "pessoaId": str(_NORMAL_PESSOA),
            "email": "membro@igrejapiloto.com.br",
            "celulaId": str(_TARGET_CELL),
        },
        headers=_AUTH,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "convidado"
    assert session.committed is True
    # app_user + UserRole('membro') foram adicionados.
    assert len(session.added) == 2
    assert candidato.celula_id == _TARGET_CELL
