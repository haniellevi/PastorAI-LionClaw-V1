"""Tests for app.services.celula_membro (achado da 2a revisão externa do PR #134).

A 1a revisão achou 2 problemas reais que a cobertura indireta (via router/tool)
não pegava porque só exercitava o caso de 0 ou 1 linha histórica:

1. ``ensure_active_membro`` usava ``scalar_one_or_none()`` — a migration de
   backfill pode legitimamente preservar mais de uma linha INATIVA histórica
   pra (pessoa, célula) (duplicatas de ``add_cell_member``, anterior a este
   PR); uma nova chamada pro mesmo par estourava ``MultipleResultsFound`` em
   vez de reativar deterministicamente a mais recente.
2. o service inseria/reativava confiando cegamente que ``celula_id`` pertence
   a ``igreja_id`` — sem uma `Celula` real de outro tenant no teste, nada
   pegava isso. Agora recusa (``ValueError``) célula fora do escopo da igreja.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import sqlalchemy as sa
import pytest
from sqlalchemy.sql import operators as sa_operators

from app.db.models import Celula, CelulaMembro
from app.services.celula_membro import deactivate_other_active_membro, ensure_active_membro

_IGREJA_A = uuid.UUID("00000000-0000-0000-0000-00000000a001")
_IGREJA_B = uuid.UUID("00000000-0000-0000-0000-00000000a002")  # outro tenant
_PESSOA_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
_CELULA_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
_OTHER_CELULA_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e2")


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


class _Session:
    def __init__(self, *, cells=(), membros=()) -> None:
        self.cells = list(cells)
        self.membros = list(membros)
        self.added: list = []

    def execute(self, statement, params=None) -> _Result:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
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


def _cell(cell_id: uuid.UUID, *, igreja_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=cell_id, igreja_id=igreja_id)


def _membro(*, pessoa_id, celula_id, igreja_id, ativo, updated_at=None, created_at=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), igreja_id=igreja_id, pessoa_id=pessoa_id, celula_id=celula_id,
        papel="membro", ativo=ativo, updated_at=updated_at, created_at=created_at,
    )


def test_ensure_active_membro_reativa_linha_mais_recente_entre_duplicatas() -> None:
    # 2 linhas INATIVAS históricas pro MESMO par (pessoa, célula) — cenário que
    # a migration de backfill preserva (não deduplica, só reativa 1).
    # scalar_one_or_none() estouraria MultipleResultsFound aqui.
    antiga = _membro(
        pessoa_id=_PESSOA_ID, celula_id=_CELULA_ID, igreja_id=_IGREJA_A, ativo=False,
        updated_at="2026-06-01", created_at="2026-06-01",
    )
    recente = _membro(
        pessoa_id=_PESSOA_ID, celula_id=_CELULA_ID, igreja_id=_IGREJA_A, ativo=False,
        updated_at="2026-07-01", created_at="2026-07-01",
    )
    cell = _cell(_CELULA_ID, igreja_id=_IGREJA_A)
    # Fake não simula ORDER BY do SQL real — semeia já na ordem que o
    # `ORDER BY updated_at DESC` produziria (mais recente primeiro); a ordem
    # real do banco é coberta pela prova via Postgres real da migration
    # (mesmo critério de desempate, mesmo ORDER BY).
    session = _Session(cells=[cell], membros=[recente, antiga])

    ensure_active_membro(
        session, igreja_id=_IGREJA_A, celula_id=_CELULA_ID, pessoa_id=_PESSOA_ID
    )

    assert recente.ativo is True
    assert antiga.ativo is False  # a duplicata mais antiga fica intocada
    assert session.added == []  # não criou linha nova


def test_ensure_active_membro_recusa_celula_de_outro_tenant() -> None:
    # Célula existe, mas pertence a OUTRA igreja — vínculo cross-tenant recusado.
    cell_outro_tenant = _cell(_CELULA_ID, igreja_id=_IGREJA_B)
    session = _Session(cells=[cell_outro_tenant])

    with pytest.raises(ValueError, match="fora do escopo"):
        ensure_active_membro(
            session, igreja_id=_IGREJA_A, celula_id=_CELULA_ID, pessoa_id=_PESSOA_ID
        )
    assert session.added == []


def test_ensure_active_membro_recusa_celula_inexistente() -> None:
    session = _Session(cells=[])

    with pytest.raises(ValueError, match="fora do escopo"):
        ensure_active_membro(
            session, igreja_id=_IGREJA_A, celula_id=_CELULA_ID, pessoa_id=_PESSOA_ID
        )


def test_ensure_active_membro_cria_quando_nao_existe_nenhuma_linha() -> None:
    cell = _cell(_CELULA_ID, igreja_id=_IGREJA_A)
    session = _Session(cells=[cell], membros=[])

    ensure_active_membro(
        session, igreja_id=_IGREJA_A, celula_id=_CELULA_ID, pessoa_id=_PESSOA_ID
    )

    novos = [o for o in session.added if isinstance(o, CelulaMembro)]
    assert len(novos) == 1
    assert novos[0].ativo is True
    assert novos[0].celula_id == _CELULA_ID
    assert novos[0].pessoa_id == _PESSOA_ID


def test_deactivate_other_active_membro_desativa_so_a_outra_celula() -> None:
    ativo_em_outra = _membro(
        pessoa_id=_PESSOA_ID, celula_id=_OTHER_CELULA_ID, igreja_id=_IGREJA_A, ativo=True,
    )
    session = _Session(membros=[ativo_em_outra])

    deactivate_other_active_membro(
        session, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_ID, keep_celula_id=_CELULA_ID
    )

    assert ativo_em_outra.ativo is False
