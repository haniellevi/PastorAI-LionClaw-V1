"""Regra de porte: planos contam membros, não todos os cadastros."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services.billing import BILLABLE_MEMBER_TYPES, current_headcount


class _CountResult:
    def scalar_one_or_none(self) -> int:
        return 17


class _CapturingSession:
    def __init__(self) -> None:
        self.statement = None

    def execute(self, statement) -> _CountResult:
        self.statement = statement
        return _CountResult()


def test_current_headcount_counts_only_active_billable_members() -> None:
    db = _CapturingSession()
    igreja_id = uuid.uuid4()

    assert current_headcount(db, SimpleNamespace(igreja_id=igreja_id)) == 17

    compiled = db.statement.compile()
    sql = " ".join(str(compiled).lower().split())
    params = compiled.params

    assert "pessoas.igreja_id =" in sql
    assert "pessoas.tipo in" in sql
    assert "pessoas.sem_interesse is false" in sql
    assert "pessoas.arquivada_em is null" in sql
    member_types = next(
        value
        for key, value in params.items()
        if key.startswith("tipo_") and isinstance(value, (list, tuple))
    )
    assert tuple(member_types) == BILLABLE_MEMBER_TYPES


def test_billable_member_types_exclude_contacts_and_visitors() -> None:
    assert set(BILLABLE_MEMBER_TYPES) == {
        "membro",
        "discipulo",
        "lider",
        "pastor",
    }
    assert "contato" not in BILLABLE_MEMBER_TYPES
    assert "visitante" not in BILLABLE_MEMBER_TYPES
