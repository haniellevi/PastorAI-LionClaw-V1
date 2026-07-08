"""Tests for app.agent.tools.vincular_celula (achado C-02, 4o ponto de escrita).

Achado pela revisão externa (Codex) do PR #134: esta tool do agente (docstring
"mirrors POST /contacts/{id}/cell", registrada em TOOL_REGISTRY e liberada em
MINISTERIAL_TOOLS — alcançável em produção via WhatsApp) só escrevia
`pessoa.celula_id`, nunca o vínculo canônico `celula_membro`. Mesmo bug do
convite/ativação/link_cell, por um 4o caminho que não estava no escopo
original do PR. Estes testes provam, offline, que agora ela também
cria/reativa `celula_membro` — espelhando exatamente o comportamento de
`contacts.py::link_cell` (transferência desativa o vínculo antigo).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import sqlalchemy as sa
import pytest
from sqlalchemy.sql import operators as sa_operators

from app.agent.tools import ToolError, vincular_celula
from app.db.models import Celula, CelulaMembro, Pessoa

_IGREJA_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_PESSOA_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
_OLD_CELL = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
_NEW_CELL = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
_LEADER = uuid.UUID("00000000-0000-0000-0000-0000000000b0")


def _right_value(right):
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


class _Result:
    def __init__(self, *, scalar=None, scalars_list=None) -> None:
        self._scalar = scalar
        self._scalars_list = list(scalars_list or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        items = self._scalars_list
        return SimpleNamespace(all=lambda: list(items), first=lambda: (items[0] if items else None))


class _ToolSession:
    def __init__(self, *, pessoas=(), cells=(), membros=()) -> None:
        self.pessoas = list(pessoas)
        self.cells = list(cells)
        self.membros = list(membros)
        self.added: list = []

    def execute(self, statement, params=None) -> _Result:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is Pessoa:
            rows = _filter(self.pessoas, statement)
            return _Result(scalar=(rows[0] if rows else None))
        if ent is Celula:
            rows = _filter(self.cells, statement)
            return _Result(scalar=(rows[0] if rows else None))
        if ent is CelulaMembro:
            rows = _filter(self.membros, statement)
            return _Result(scalar=(rows[0] if rows else None), scalars_list=rows)
        return _Result()

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        if isinstance(obj, CelulaMembro):
            self.membros.append(obj)

    def flush(self) -> None:
        pass


def _pessoa(pessoa_id: uuid.UUID, *, celula_id=None) -> SimpleNamespace:
    return SimpleNamespace(id=pessoa_id, igreja_id=_IGREJA_ID, celula_id=celula_id)


def _cell(cell_id: uuid.UUID, *, lider_id=_LEADER, ativo=True) -> SimpleNamespace:
    return SimpleNamespace(id=cell_id, igreja_id=_IGREJA_ID, lider_id=lider_id, ativo=ativo)


def _membro(*, pessoa_id, celula_id, ativo) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), igreja_id=_IGREJA_ID, pessoa_id=pessoa_id,
        celula_id=celula_id, papel="membro", ativo=ativo,
    )


def test_vincular_celula_first_link_creates_celula_membro() -> None:
    pessoa = _pessoa(_PESSOA_ID, celula_id=None)
    cell = _cell(_NEW_CELL)
    session = _ToolSession(pessoas=[pessoa], cells=[cell])

    result = vincular_celula(
        session, igreja_id=_IGREJA_ID, pessoa_id=_PESSOA_ID, celula_id=_NEW_CELL
    )

    assert result.ok is True
    assert pessoa.celula_id == cell.id
    novos = [o for o in session.added if isinstance(o, CelulaMembro)]
    assert len(novos) == 1
    assert novos[0].pessoa_id == pessoa.id
    assert novos[0].celula_id == cell.id
    assert novos[0].ativo is True


def test_vincular_celula_transfer_deactivates_old_activates_new() -> None:
    pessoa = _pessoa(_PESSOA_ID, celula_id=_OLD_CELL)
    old_cell = _cell(_OLD_CELL)
    new_cell = _cell(_NEW_CELL)
    old_membro = _membro(pessoa_id=_PESSOA_ID, celula_id=_OLD_CELL, ativo=True)
    session = _ToolSession(
        pessoas=[pessoa], cells=[old_cell, new_cell], membros=[old_membro]
    )

    vincular_celula(
        session, igreja_id=_IGREJA_ID, pessoa_id=_PESSOA_ID, celula_id=_NEW_CELL
    )

    assert pessoa.celula_id == new_cell.id
    assert old_membro.ativo is False  # nunca duas linhas ativas pra mesma pessoa
    novos = [o for o in session.added if isinstance(o, CelulaMembro)]
    assert len(novos) == 1
    assert novos[0].celula_id == new_cell.id
    assert novos[0].ativo is True


def test_vincular_celula_still_rejects_inactive_cell() -> None:
    pessoa = _pessoa(_PESSOA_ID, celula_id=None)
    cell = _cell(_NEW_CELL, ativo=False)
    session = _ToolSession(pessoas=[pessoa], cells=[cell])

    with pytest.raises(ToolError, match="inativa"):
        vincular_celula(
            session, igreja_id=_IGREJA_ID, pessoa_id=_PESSOA_ID, celula_id=_NEW_CELL
        )
    assert session.added == []


def test_vincular_celula_still_rejects_leaderless_cell() -> None:
    pessoa = _pessoa(_PESSOA_ID, celula_id=None)
    cell = _cell(_NEW_CELL, lider_id=None)
    session = _ToolSession(pessoas=[pessoa], cells=[cell])

    with pytest.raises(ToolError, match="sem líder"):
        vincular_celula(
            session, igreja_id=_IGREJA_ID, pessoa_id=_PESSOA_ID, celula_id=_NEW_CELL
        )
    assert session.added == []
