"""Tests for POST /contacts/{id}/cell (link_cell) — vínculo canônico (achado C-02).

Nenhum teste dedicado existia para este endpoint (só citado em comentário de
outro arquivo). Estes provam, offline (sem Postgres), que `link_cell` passa a
criar/ativar `celula_membro` — não só o espelho legado `pessoas.celula_id`:

  1. primeira vinculação por pastor/admin cria a linha canônica ativa, enquanto
     líder de célula é barrado antes de leituras ou escrita de domínio;
  2. transferência (admin move pessoa de uma célula pra outra) desativa o
     vínculo canônico ANTIGO antes de ativar o novo — o índice único parcial
     (igreja_id, pessoa_id) WHERE ativo só permite 1 vínculo ativo por pessoa;
  3. se já existir uma linha INATIVA pra (pessoa, célula destino) — ex.: um
     retorno a uma célula anterior — reativa em vez de duplicar.

Fake session no estilo dos demais testes (entity-routed via
``column_descriptions``), mas avalia cada predicado do WHERE contra o operador
real (eq/ne/is_) em vez de um dict achatado — a detecção de transferência em
`ensure_active_membro` usa `celula_id != <célula alvo>`, que um dict
key->value confundiria com `==`.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.sql import operators as sa_operators

from app.db.models import AppUser, Celula, CelulaMembro, Pessoa
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user

_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_ADMIN_APP_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")

_PESSOA_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
_OLD_CELL = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
_NEW_CELL = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
_LEADER = uuid.UUID("00000000-0000-0000-0000-0000000000b0")

_AUTH = {"Authorization": "Bearer good"}


# ---------------------------------------------------------------------------
# Fake session — avalia cada nó do WHERE contra o operador real (eq/ne/is_),
# não um dict achatado (que perderia a diferença entre == e !=).
# ---------------------------------------------------------------------------
class _Result:
    def __init__(self, *, scalar=None, scalars_list=None) -> None:
        self._scalar = scalar
        self._scalars_list = list(scalars_list or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        items = self._scalars_list
        return SimpleNamespace(all=lambda: list(items), first=lambda: (items[0] if items else None))


def _right_value(right):
    """Extrai o valor comparado — BindParameter tem `.value`, mas `.is_(True)`/
    `.is_(False)` viram o singleton True_/False_ (sem `.value`)."""
    if right is sa.true():
        return True
    if right is sa.false():
        return False
    return getattr(right, "value", None)


def _row_matches(row, node) -> bool:
    left = getattr(node, "left", None)
    right = getattr(node, "right", None)
    if left is not None and right is not None:
        key = getattr(left, "key", None)
        if key is None:
            return True
        actual = getattr(row, key, None)
        value = _right_value(right)
        op = getattr(node, "operator", None)
        if op is sa_operators.ne:
            return str(actual) != str(value)
        return str(actual) == str(value)
    children = getattr(node, "clauses", None)
    if children is not None:
        return all(_row_matches(row, c) for c in children)
    return True


def _filter(rows, statement):
    clause = getattr(statement, "whereclause", None)
    if clause is None:
        return list(rows)
    return [r for r in rows if _row_matches(r, clause)]


class _LinkCellSession:
    def __init__(self, *, pessoas=(), cells=(), membros=()) -> None:
        self.pessoas = list(pessoas)
        self.cells = list(cells)
        self.membros = list(membros)
        self.added: list = []
        self.committed = False
        self.execute_count = 0

    def execute(self, statement, params=None) -> _Result:
        self.execute_count += 1
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None

        if ent is Pessoa:
            rows = _filter(self.pessoas, statement)
            return _Result(scalar=(rows[0] if rows else None), scalars_list=rows)
        if ent is Celula:
            rows = _filter(self.cells, statement)
            return _Result(scalar=(rows[0] if rows else None), scalars_list=rows)
        if ent is CelulaMembro:
            rows = _filter(self.membros, statement)
            return _Result(scalar=(rows[0] if rows else None), scalars_list=rows)
        return _Result()  # text() do set_tenant_context (RLS GUC)

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        if isinstance(obj, CelulaMembro):
            self.membros.append(obj)

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


def _cell_leader() -> CurrentUser:
    return CurrentUser(
        app_user_id=str(uuid.uuid4()),
        clerk_user_id="clerk_lider",
        igreja_id=_IGREJA_ID,
        email="lider@igrejapiloto.com.br",
        nome="Líder",
        roles=frozenset({"lider_celula"}),
    )


def _pastor() -> CurrentUser:
    return CurrentUser(
        app_user_id=str(uuid.uuid4()),
        clerk_user_id="clerk_pastor",
        igreja_id=_IGREJA_ID,
        email="pastor@igrejapiloto.com.br",
        nome="Pastor",
        roles=frozenset({"pastor"}),
    )


def _pessoa(pessoa_id: uuid.UUID, *, celula_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=pessoa_id,
        igreja_id=_IGREJA_ID,
        celula_id=celula_id,
        nome="Fulano",
        tipo="membro",
        genero=None,
        etapa=None,
        subetapa=None,
        acompanhamento=None,
        sem_interesse=False,
        sem_interesse_motivo=None,
        faixa_etaria=None,
        endereco=None,
        presencas_celula=0,
        aceitou_jesus=False,
        lider_id=None,
        apto_lider=False,
        telefone="11988887777",
        email=None,
        arquivada_em=None,
    )


def _cell(cell_id: uuid.UUID, *, lider_id=_LEADER, ativo=True) -> SimpleNamespace:
    return SimpleNamespace(id=cell_id, igreja_id=_IGREJA_ID, lider_id=lider_id, ativo=ativo)


def _membro(*, pessoa_id, celula_id, ativo) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        igreja_id=_IGREJA_ID,
        pessoa_id=pessoa_id,
        celula_id=celula_id,
        papel="membro",
        ativo=ativo,
    )


def _client(app, *, session, current_user) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1) primeira vinculação — cria celula_membro ativo
# ---------------------------------------------------------------------------
def test_link_cell_first_link_creates_celula_membro(app) -> None:
    pessoa = _pessoa(_PESSOA_ID, celula_id=None)
    cell = _cell(_NEW_CELL)
    session = _LinkCellSession(pessoas=[pessoa], cells=[cell])
    client = _client(app, session=session, current_user=_admin())

    resp = client.post(
        f"/contacts/{_PESSOA_ID}/cell", headers=_AUTH, json={"celulaId": str(_NEW_CELL)}
    )

    assert resp.status_code == 200, resp.text
    assert pessoa.celula_id == cell.id
    novos_membros = [o for o in session.added if isinstance(o, CelulaMembro)]
    assert len(novos_membros) == 1
    membro = novos_membros[0]
    assert membro.pessoa_id == pessoa.id
    assert membro.celula_id == cell.id
    assert membro.ativo is True
    assert session.committed is True


# ---------------------------------------------------------------------------
# 2) transferência — desativa o vínculo antigo, ativa o novo
# ---------------------------------------------------------------------------
def test_link_cell_transfer_deactivates_old_activates_new(app) -> None:
    pessoa = _pessoa(_PESSOA_ID, celula_id=_OLD_CELL)
    old_cell = _cell(_OLD_CELL)
    new_cell = _cell(_NEW_CELL)
    old_membro = _membro(pessoa_id=_PESSOA_ID, celula_id=_OLD_CELL, ativo=True)
    session = _LinkCellSession(
        pessoas=[pessoa], cells=[old_cell, new_cell], membros=[old_membro]
    )
    client = _client(app, session=session, current_user=_admin())

    resp = client.post(
        f"/contacts/{_PESSOA_ID}/cell", headers=_AUTH, json={"celulaId": str(_NEW_CELL)}
    )

    assert resp.status_code == 200, resp.text
    assert pessoa.celula_id == new_cell.id
    # Vínculo antigo desativado — nunca duas linhas ativas pra mesma pessoa.
    assert old_membro.ativo is False
    novos_membros = [o for o in session.added if isinstance(o, CelulaMembro)]
    assert len(novos_membros) == 1
    novo = novos_membros[0]
    assert novo.celula_id == new_cell.id
    assert novo.ativo is True


# ---------------------------------------------------------------------------
# 3) retorno a célula com vínculo INATIVO existente — reativa, não duplica
# ---------------------------------------------------------------------------
def test_link_cell_reactivates_existing_inactive_membro(app) -> None:
    pessoa = _pessoa(_PESSOA_ID, celula_id=_OLD_CELL)
    old_cell = _cell(_OLD_CELL)
    new_cell = _cell(_NEW_CELL)
    old_membro = _membro(pessoa_id=_PESSOA_ID, celula_id=_OLD_CELL, ativo=True)
    # Vínculo antigo (inativo) com a célula de DESTINO — retorno.
    stale_membro = _membro(pessoa_id=_PESSOA_ID, celula_id=_NEW_CELL, ativo=False)
    session = _LinkCellSession(
        pessoas=[pessoa], cells=[old_cell, new_cell], membros=[old_membro, stale_membro]
    )
    client = _client(app, session=session, current_user=_admin())

    resp = client.post(
        f"/contacts/{_PESSOA_ID}/cell", headers=_AUTH, json={"celulaId": str(_NEW_CELL)}
    )

    assert resp.status_code == 200, resp.text
    assert old_membro.ativo is False
    assert stale_membro.ativo is True  # reativado, não duplicado
    novos_membros = [o for o in session.added if isinstance(o, CelulaMembro)]
    assert novos_membros == []  # nada novo criado


# ---------------------------------------------------------------------------
# 4) célula inativa/sem líder continuam rejeitadas (regressão C-03, sem tocar
#    celula_membro nenhum)
# ---------------------------------------------------------------------------
def test_link_cell_still_rejects_inactive_cell(app) -> None:
    pessoa = _pessoa(_PESSOA_ID, celula_id=None)
    cell = _cell(_NEW_CELL, ativo=False)
    session = _LinkCellSession(pessoas=[pessoa], cells=[cell])
    client = _client(app, session=session, current_user=_admin())

    resp = client.post(
        f"/contacts/{_PESSOA_ID}/cell", headers=_AUTH, json={"celulaId": str(_NEW_CELL)}
    )

    assert resp.status_code == 409
    assert session.added == []


# ---------------------------------------------------------------------------
# 5) D2 — transferência é capacidade derivada do papel admin PELO ADAPTER; o
#    domínio (ensure_active_membro) recusa antes de qualquer mutação.
# ---------------------------------------------------------------------------
def test_link_cell_pastor_cannot_transfer(app) -> None:
    pessoa = _pessoa(_PESSOA_ID, celula_id=_OLD_CELL)
    old_cell = _cell(_OLD_CELL)
    new_cell = _cell(_NEW_CELL)
    old_membro = _membro(pessoa_id=_PESSOA_ID, celula_id=_OLD_CELL, ativo=True)
    session = _LinkCellSession(
        pessoas=[pessoa], cells=[old_cell, new_cell], membros=[old_membro]
    )
    client = _client(app, session=session, current_user=_pastor())

    resp = client.post(
        f"/contacts/{_PESSOA_ID}/cell", headers=_AUTH, json={"celulaId": str(_NEW_CELL)}
    )

    assert resp.status_code == 403, resp.text
    assert "administrador" in resp.json()["detail"]
    assert old_membro.ativo is True  # vínculo antigo intacto
    assert pessoa.celula_id == _OLD_CELL  # espelho inalterado
    assert session.added == []  # nenhuma linha criada
    assert session.committed is False


def test_link_cell_cell_leader_cannot_create_first_link(app) -> None:
    pessoa = _pessoa(_PESSOA_ID, celula_id=None)
    cell = _cell(_NEW_CELL)
    session = _LinkCellSession(pessoas=[pessoa], cells=[cell])
    client = _client(app, session=session, current_user=_cell_leader())

    resp = client.post(
        f"/contacts/{_PESSOA_ID}/cell", headers=_AUTH, json={"celulaId": str(_NEW_CELL)}
    )

    assert resp.status_code == 403, resp.text
    assert pessoa.celula_id is None
    assert session.execute_count == 0  # dependency gate runs before domain reads
    assert session.added == []
    assert session.committed is False


def test_link_cell_pastor_can_create_first_link(app) -> None:
    pessoa = _pessoa(_PESSOA_ID, celula_id=None)
    cell = _cell(_NEW_CELL)
    session = _LinkCellSession(pessoas=[pessoa], cells=[cell])
    client = _client(app, session=session, current_user=_pastor())

    resp = client.post(
        f"/contacts/{_PESSOA_ID}/cell", headers=_AUTH, json={"celulaId": str(_NEW_CELL)}
    )

    assert resp.status_code == 200, resp.text
    assert pessoa.celula_id == cell.id
    novos = [o for o in session.added if isinstance(o, CelulaMembro)]
    assert len(novos) == 1
    assert novos[0].ativo is True
    assert session.committed is True
