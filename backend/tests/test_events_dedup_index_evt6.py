"""EVT-6 PR6.3 — índice único parcial de dedup do import Google.

O harness de testes é in-memory (FakeSession não persiste), então não dá pra
exercitar a migration contra o Postgres real aqui (como já observa
`test_events_schema_evt1.py`). Mas a *semântica* do índice único parcial é
padrão-SQL e o SQLite (stdlib) também suporta índice parcial com `WHERE`, com as
mesmas regras de NULL. Então este teste **lê o statement do próprio arquivo de
migration** e o executa num SQLite in-memory, provando exatamente o contrato da
missão:

  - mesmo ``google_event_id`` em igrejas DIFERENTES => permitido (multi-tenant);
  - mesmo ``google_event_id`` na MESMA igreja => bloqueado pelo índice;
  - ``google_event_id`` NULL (evento manual) repetido => permitido (índice
    parcial não indexa NULL).

Ler do arquivo (em vez de copiar o SQL) faz o teste falhar se o índice mudar de
colunas ou de predicado — pega drift real, não uma cópia estática.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
_MIGRATION_GLOB = "*_evt6_google_event_dedup_index.sql"


def _index_statement() -> str:
    """Extrai o `create unique index ... ;` do arquivo de migration do PR6.3."""
    matches = list(_MIGRATIONS_DIR.glob(_MIGRATION_GLOB))
    assert len(matches) == 1, f"esperava 1 migration do dedup, achei {matches}"
    raw = matches[0].read_text(encoding="utf-8")
    # Tira comentários de linha (`-- ...`) — o header menciona "create unique
    # index" em prosa e casaria antes do statement real.
    sql = "\n".join(re.sub(r"--.*$", "", line) for line in raw.splitlines())
    m = re.search(r"create\s+unique\s+index.*?;", sql, re.IGNORECASE | re.DOTALL)
    assert m, "statement `create unique index` não encontrado na migration"
    stmt = m.group(0)
    # Sanidade: é o índice parcial esperado, nas colunas certas.
    assert "igreja_id" in stmt and "google_event_id" in stmt
    assert re.search(r"where\s+google_event_id\s+is\s+not\s+null", stmt, re.IGNORECASE)
    return stmt


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute(
        "create table events ("
        " id integer primary key,"
        " igreja_id text not null,"
        " google_event_id text)"
    )
    con.execute(_index_statement())  # o SQL REAL da migration
    return con


_IGREJA_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_IGREJA_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _insert(con: sqlite3.Connection, igreja: str, gid: str | None) -> None:
    con.execute(
        "insert into events (igreja_id, google_event_id) values (?, ?)", (igreja, gid)
    )


def test_same_gid_different_igreja_is_allowed() -> None:
    con = _db()
    _insert(con, _IGREJA_A, "g1")
    _insert(con, _IGREJA_B, "g1")  # outra igreja, mesmo gid — permitido
    assert con.execute("select count(*) from events").fetchone()[0] == 2


def test_same_gid_same_igreja_is_blocked() -> None:
    con = _db()
    _insert(con, _IGREJA_A, "g1")
    with pytest.raises(sqlite3.IntegrityError):
        _insert(con, _IGREJA_A, "g1")  # duplicata no mesmo tenant — bloqueada


def test_null_gid_manual_events_do_not_collide() -> None:
    con = _db()
    _insert(con, _IGREJA_A, None)
    _insert(con, _IGREJA_A, None)  # eventos manuais (gid NULL) não colidem
    assert con.execute("select count(*) from events").fetchone()[0] == 2
