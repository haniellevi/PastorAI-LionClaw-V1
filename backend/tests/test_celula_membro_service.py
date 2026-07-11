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

from app.db.models import Celula, CelulaMembro, Pessoa
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


class _Rev:
    """Inverte a comparação — usado pra simular DESC num sort ascendente."""

    __slots__ = ("value",)

    def __init__(self, value) -> None:
        self.value = value

    def __lt__(self, other: "_Rev") -> bool:
        return other.value < self.value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Rev) and self.value == other.value


def _order_by_specs(statement) -> list[tuple[str, bool, bool]]:
    """Extrai (coluna, desc, nulls_last) de cada clause do ORDER BY real —
    não hardcoda a ordem esperada, lê a query de verdade (senão o teste só
    provaria que o fake devolve o que foi semeado, não que o código ordena
    certo)."""
    specs = []
    for clause in getattr(statement, "_order_by_clauses", ()):
        node = clause
        desc = False
        nulls_last = False
        key = None
        for _ in range(6):
            mod_name = getattr(getattr(node, "modifier", None), "__name__", "")
            if mod_name == "desc_op":
                desc = True
            elif mod_name == "asc_op":
                desc = False
            elif mod_name == "nulls_last_op":
                nulls_last = True
            elif mod_name == "nulls_first_op":
                nulls_last = False
            element = getattr(node, "element", None)
            candidate_key = getattr(node, "key", None) or getattr(element, "key", None)
            if candidate_key:
                key = candidate_key
                break
            if element is None:
                break
            node = element
        if key is not None:
            specs.append((key, desc, nulls_last))
    return specs


def _sort_by_real_order_by(rows, statement):
    specs = _order_by_specs(statement)
    if not specs:
        return list(rows)

    def sort_key(row):
        parts = []
        for attr, desc, nulls_last in specs:
            value = getattr(row, attr, None)
            if value is None:
                parts.append((1 if nulls_last else 0, 0))
            else:
                parts.append((0 if nulls_last else 1, _Rev(value) if desc else value))
        return tuple(parts)

    return sorted(rows, key=sort_key)


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
    def __init__(self, *, cells=(), membros=(), pessoas=()) -> None:
        self.cells = list(cells)
        self.membros = list(membros)
        self.pessoas = list(pessoas)
        self.added: list = []

    def execute(self, statement, params=None) -> _Result:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is Celula:
            rows = _filter(self.cells, statement)
            return _Result(scalar=(rows[0] if rows else None))
        if ent is CelulaMembro:
            rows = _sort_by_real_order_by(_filter(self.membros, statement), statement)
            return _Result(scalar=(rows[0] if rows else None), scalars_list=rows)
        if ent is Pessoa:
            rows = _filter(self.pessoas, statement)
            return _Result(scalar=(rows[0] if rows else None))
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
    # Ordem de seed embaralhada de propósito — o fake aplica o ORDER BY real
    # da query (ver _sort_by_real_order_by), não confia na ordem de inserção.
    session = _Session(cells=[cell], membros=[antiga, recente])

    ensure_active_membro(
        session, igreja_id=_IGREJA_A, celula_id=_CELULA_ID, pessoa_id=_PESSOA_ID
    )

    assert recente.ativo is True
    assert antiga.ativo is False  # a duplicata mais antiga fica intocada
    assert session.added == []  # não criou linha nova


def test_ensure_active_membro_prioriza_linha_ja_ativa_sobre_duplicata_inativa_mais_recente() -> None:
    # Achado da 3a revisão externa: uma linha ATIVA nunca tem `updated_at`
    # tocado (fica NULL pra sempre), enquanto toda linha DESATIVADA sempre
    # ganha `updated_at = now()` no momento da transferência
    # (cell_requests_service.py/cell_multiplication_service.py). Se o ORDER
    # BY só olhasse updated_at, uma chamada idempotente pra um par JÁ ativo
    # escolheria por engano a duplicata inativa (updated_at populado) em vez
    # da linha ativa (updated_at NULL) — e tentaria reativá-la também,
    # violando o índice único parcial. `ativo DESC` tem que vir primeiro.
    ja_ativa = _membro(
        pessoa_id=_PESSOA_ID, celula_id=_CELULA_ID, igreja_id=_IGREJA_A, ativo=True,
        updated_at=None, created_at="2026-01-01",  # nunca tocada desde a criação
    )
    duplicata_inativa_mais_recente = _membro(
        pessoa_id=_PESSOA_ID, celula_id=_CELULA_ID, igreja_id=_IGREJA_A, ativo=False,
        updated_at="2026-07-08", created_at="2026-01-01",  # desativada recentemente
    )
    cell = _cell(_CELULA_ID, igreja_id=_IGREJA_A)
    session = _Session(cells=[cell], membros=[duplicata_inativa_mais_recente, ja_ativa])

    ensure_active_membro(
        session, igreja_id=_IGREJA_A, celula_id=_CELULA_ID, pessoa_id=_PESSOA_ID
    )

    assert ja_ativa.ativo is True  # continua a única ativa (idempotente, no-op)
    assert duplicata_inativa_mais_recente.ativo is False  # NUNCA reativada por engano
    assert session.added == []


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


# ---------------------------------------------------------------------------
# Missão M7B-W1 — promoção de tipo ao ganhar vínculo canônico ativo
# ---------------------------------------------------------------------------
def _pessoa(*, pessoa_id=_PESSOA_ID, igreja_id=_IGREJA_A, tipo=None) -> SimpleNamespace:
    return SimpleNamespace(id=pessoa_id, igreja_id=igreja_id, tipo=tipo)


@pytest.mark.parametrize("tipo_inicial", [None, "contato", "visitante"])
def test_ensure_active_membro_promove_tipo_de_entrada_para_membro(tipo_inicial) -> None:
    pessoa = _pessoa(tipo=tipo_inicial)
    session = _Session(
        cells=[_cell(_CELULA_ID, igreja_id=_IGREJA_A)], pessoas=[pessoa]
    )

    ensure_active_membro(
        session, igreja_id=_IGREJA_A, celula_id=_CELULA_ID, pessoa_id=_PESSOA_ID
    )

    assert pessoa.tipo == "membro"


@pytest.mark.parametrize("tipo_superior", ["membro", "discipulo", "lider", "pastor"])
def test_ensure_active_membro_nao_rebaixa_tipo_superior(tipo_superior) -> None:
    pessoa = _pessoa(tipo=tipo_superior)
    session = _Session(
        cells=[_cell(_CELULA_ID, igreja_id=_IGREJA_A)], pessoas=[pessoa]
    )

    ensure_active_membro(
        session, igreja_id=_IGREJA_A, celula_id=_CELULA_ID, pessoa_id=_PESSOA_ID
    )

    assert pessoa.tipo == tipo_superior  # preservado, nunca rebaixado


def test_ensure_active_membro_promocao_e_idempotente() -> None:
    pessoa = _pessoa(tipo="contato")
    session = _Session(
        cells=[_cell(_CELULA_ID, igreja_id=_IGREJA_A)], pessoas=[pessoa]
    )

    ensure_active_membro(
        session, igreja_id=_IGREJA_A, celula_id=_CELULA_ID, pessoa_id=_PESSOA_ID
    )
    ensure_active_membro(
        session, igreja_id=_IGREJA_A, celula_id=_CELULA_ID, pessoa_id=_PESSOA_ID
    )

    assert pessoa.tipo == "membro"
    # 2ª chamada reativa a MESMA linha — nunca duplica o vínculo.
    novos = [o for o in session.added if isinstance(o, CelulaMembro)]
    assert len(novos) == 1


def test_ensure_active_membro_nao_promove_pessoa_de_outro_tenant() -> None:
    # A pessoa alvo pertence à igreja B; o vínculo é criado no escopo da igreja A.
    # A promoção é tenant-scoped (filtra por igreja_id) — não pode tocar a
    # pessoa da igreja B.
    pessoa_outro_tenant = _pessoa(igreja_id=_IGREJA_B, tipo="contato")
    session = _Session(
        cells=[_cell(_CELULA_ID, igreja_id=_IGREJA_A)], pessoas=[pessoa_outro_tenant]
    )

    ensure_active_membro(
        session, igreja_id=_IGREJA_A, celula_id=_CELULA_ID, pessoa_id=_PESSOA_ID
    )

    assert pessoa_outro_tenant.tipo == "contato"  # intocada
