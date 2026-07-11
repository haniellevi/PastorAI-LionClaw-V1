"""M7B-W1 — prova, contra Postgres real, que a migration de backfill
`20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql`:

  * promove tipo NULL/'contato'/'visitante' com vínculo ATIVO para 'membro';
  * PRESERVA 'membro'/'discipulo'/'lider'/'pastor' (nunca rebaixa);
  * ignora vínculos INATIVOS;
  * é tenant-safe (não promove por causa de vínculo de OUTRA igreja);
  * é idempotente (reexecutar não muda nada).

Não dá pra provar UPDATE de banco com FakeSession (SQL nunca roda de verdade) —
por isso é integração pura contra Postgres descartável, mesmo padrão de
`test_agent_event_idempotency_index.py`: sem `RLS_TEST_DATABASE_URL`, skip
limpo; com a env var, roda de verdade. Aplica o ARQUIVO real da migration (não
uma cópia), provando o artefato que de fato vai pro Supabase.
"""

from __future__ import annotations

import pathlib

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.conftest_rls import IGREJA_A, IGREJA_B, rls_database_url, rls_engine, rls_seeded  # noqa: F401

pytestmark = pytest.mark.rls_integration

_MIGRATION_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "migrations"
    / "20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql"
)

# Schema mínimo exercitado pela migration: pessoas.tipo (enum real), celulas e
# celula_membro. conftest_rls já cria/semeia igrejas + pessoas(id, igreja_id,
# nome). Idempotente (if not exists / add column if not exists).
_SETUP_SQL = """
do $$ begin
  if not exists (select 1 from pg_type where typname = 'pessoa_tipo') then
    create type pessoa_tipo as enum
      ('visitante', 'membro', 'lider', 'pastor', 'discipulo', 'contato');
  end if;
end $$;

alter table pessoas add column if not exists tipo pessoa_tipo;

create table if not exists celulas (
  id        uuid primary key default gen_random_uuid(),
  igreja_id uuid not null references igrejas(id) on delete cascade
);

create table if not exists celula_membro (
  id         uuid primary key default gen_random_uuid(),
  igreja_id  uuid not null references igrejas(id) on delete cascade,
  celula_id  uuid not null references celulas(id) on delete cascade,
  pessoa_id  uuid not null references pessoas(id) on delete cascade,
  papel      text not null default 'membro',
  ativo      boolean not null default true
);
"""

# UUIDs fixos do cenário (prefixo estável, fáceis de deletar entre reexecuções).
_CELULA_A = "0c0c0c0c-0000-0000-0000-0000000000a1"
_CELULA_B = "0c0c0c0c-0000-0000-0000-0000000000b1"
# (uuid, tipo_inicial, tipo_esperado_apos_backfill)
_ATIVOS_A: tuple[tuple[str, str | None, str], ...] = (
    ("d0000000-0000-0000-0000-000000000001", None, "membro"),
    ("d0000000-0000-0000-0000-000000000002", "contato", "membro"),
    ("d0000000-0000-0000-0000-000000000003", "visitante", "membro"),
    ("d0000000-0000-0000-0000-000000000004", "membro", "membro"),
    ("d0000000-0000-0000-0000-000000000005", "discipulo", "discipulo"),
    ("d0000000-0000-0000-0000-000000000006", "lider", "lider"),
    ("d0000000-0000-0000-0000-000000000007", "pastor", "pastor"),
)
# contato com vínculo INATIVO em A — NÃO promove.
_INATIVO_A = "d0000000-0000-0000-0000-0000000000f1"
# contato de A cujo ÚNICO vínculo ativo está marcado como igreja B
# (cm.igreja_id != p.igreja_id) — NÃO promove (tenant-safe).
_CROSS = "d0000000-0000-0000-0000-0000000000f2"


def _uuid_list(*ids: str) -> str:
    return ", ".join(f"'{i}'::uuid" for i in ids)


def _cleanup(conn, all_pessoas: list[str]) -> None:
    conn.execute(
        text(f"delete from celula_membro where pessoa_id in ({_uuid_list(*all_pessoas)})")
    )
    conn.execute(text(f"delete from pessoas where id in ({_uuid_list(*all_pessoas)})"))
    conn.execute(
        text(f"delete from celulas where id in ({_uuid_list(_CELULA_A, _CELULA_B)})")
    )


@pytest.fixture
def seeded_engine(rls_engine: Engine, rls_seeded: dict[str, str]):
    all_pessoas = [u for (u, _, _) in _ATIVOS_A] + [_INATIVO_A, _CROSS]
    with rls_engine.begin() as conn:
        conn.execute(text(_SETUP_SQL))
        # Limpa qualquer resíduo de execução anterior (mesmo Postgres descartável).
        _cleanup(conn, all_pessoas)
        conn.execute(
            text(
                "insert into celulas (id, igreja_id) values "
                "(:ca, :ia), (:cb, :ib)"
            ),
            {"ca": _CELULA_A, "ia": IGREJA_A, "cb": _CELULA_B, "ib": IGREJA_B},
        )
        # Pessoas + vínculo ATIVO em A pra cada tipo do cenário.
        for pid, tipo, _ in _ATIVOS_A:
            conn.execute(
                text(
                    "insert into pessoas (id, igreja_id, nome, tipo) "
                    "values (:id, :ig, 'X', :tipo)"
                ),
                {"id": pid, "ig": IGREJA_A, "tipo": tipo},
            )
            conn.execute(
                text(
                    "insert into celula_membro (igreja_id, celula_id, pessoa_id, ativo) "
                    "values (:ig, :cel, :pid, true)"
                ),
                {"ig": IGREJA_A, "cel": _CELULA_A, "pid": pid},
            )
        # contato com vínculo INATIVO.
        conn.execute(
            text(
                "insert into pessoas (id, igreja_id, nome, tipo) "
                "values (:id, :ig, 'X', 'contato')"
            ),
            {"id": _INATIVO_A, "ig": IGREJA_A},
        )
        conn.execute(
            text(
                "insert into celula_membro (igreja_id, celula_id, pessoa_id, ativo) "
                "values (:ig, :cel, :pid, false)"
            ),
            {"ig": IGREJA_A, "cel": _CELULA_A, "pid": _INATIVO_A},
        )
        # contato de A com vínculo ativo marcado como igreja B (cross-tenant).
        conn.execute(
            text(
                "insert into pessoas (id, igreja_id, nome, tipo) "
                "values (:id, :ig, 'X', 'contato')"
            ),
            {"id": _CROSS, "ig": IGREJA_A},
        )
        conn.execute(
            text(
                "insert into celula_membro (igreja_id, celula_id, pessoa_id, ativo) "
                "values (:ig, :cel, :pid, true)"
            ),
            {"ig": IGREJA_B, "cel": _CELULA_B, "pid": _CROSS},
        )
    yield rls_engine
    # Teardown: remove as linhas semeadas pra não poluir a tabela `pessoas`
    # compartilhada do Postgres descartável (outros testes RLS assumem só as
    # pessoas do seed do conftest_rls).
    with rls_engine.begin() as conn:
        _cleanup(conn, all_pessoas)


def _tipo(engine: Engine, pessoa_id: str) -> str | None:
    with engine.begin() as conn:
        return conn.execute(
            text("select tipo from pessoas where id = :id"), {"id": pessoa_id}
        ).scalar_one()


def _apply_migration(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(_MIGRATION_PATH.read_text(encoding="utf-8")))


def test_backfill_promotes_and_preserves(seeded_engine: Engine) -> None:
    _apply_migration(seeded_engine)

    for pid, _, esperado in _ATIVOS_A:
        assert _tipo(seeded_engine, pid) == esperado, pid
    # Vínculo inativo → não promove.
    assert _tipo(seeded_engine, _INATIVO_A) == "contato"
    # Vínculo de outra igreja → não promove (tenant-safe).
    assert _tipo(seeded_engine, _CROSS) == "contato"


def test_backfill_is_idempotent(seeded_engine: Engine) -> None:
    _apply_migration(seeded_engine)
    snapshot = {pid: _tipo(seeded_engine, pid) for pid, _, _ in _ATIVOS_A}

    _apply_migration(seeded_engine)  # 2ª aplicação não pode mudar nada

    for pid, _, _ in _ATIVOS_A:
        assert _tipo(seeded_engine, pid) == snapshot[pid], pid
    assert _tipo(seeded_engine, _INATIVO_A) == "contato"
    assert _tipo(seeded_engine, _CROSS) == "contato"


def test_backfill_leaves_no_divergences(seeded_engine: Engine) -> None:
    _apply_migration(seeded_engine)
    with seeded_engine.begin() as conn:
        restantes = conn.execute(
            text(
                "select count(*) from pessoas p "
                "where (p.tipo is null or p.tipo in ('contato', 'visitante')) "
                "and exists (select 1 from celula_membro cm "
                "  where cm.pessoa_id = p.id and cm.igreja_id = p.igreja_id "
                "  and cm.ativo = true)"
            )
        ).scalar_one()
    assert restantes == 0


# Query 2 da migration (contagem por tipo), COM `p.tipo::text` — sem o cast, o
# coalesce(enum, '(null)') falha no Postgres ('(null)' não é label do enum
# pessoa_tipo). Este teste executa a query documentada de verdade, provando que
# ela roda e que o backfill deixou a distribuição correta.
_COUNT_BY_TIPO_SQL = (
    "select coalesce(p.tipo::text, '(null)') as tipo, count(*) as qtd "
    "from pessoas p "
    "where exists (select 1 from celula_membro cm "
    "  where cm.pessoa_id = p.id and cm.igreja_id = p.igreja_id "
    "  and cm.ativo = true) "
    "group by p.tipo order by 1"
)


def test_backfill_count_by_tipo_query_runs_and_is_consistent(seeded_engine: Engine) -> None:
    _apply_migration(seeded_engine)
    with seeded_engine.begin() as conn:
        # (1) executa sem erro no Postgres real.
        counts = {row[0]: row[1] for row in conn.execute(text(_COUNT_BY_TIPO_SQL))}
    # (2) nenhum null/contato/visitante com vínculo ativo após o backfill.
    assert "(null)" not in counts
    assert "contato" not in counts
    assert "visitante" not in counts
    # (3) tipos superiores aparecem corretamente na contagem.
    #     membro = null + contato + visitante (promovidos) + membro (preservado).
    assert counts["membro"] == 4
    assert counts["discipulo"] == 1
    assert counts["lider"] == 1
    assert counts["pastor"] == 1
