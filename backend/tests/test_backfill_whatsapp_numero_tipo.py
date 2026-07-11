"""M7B-W1.2 — prova, contra Postgres real, que a migration
`20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql`:

  * reclassifica de 'membro' para 'contato' SOMENTE a pessoa cujo telefone é o
    número conectado ao WhatsApp da igreja E que NÃO tem vínculo ativo de célula;
  * PRESERVA um membro real (mesmo número, mas COM vínculo ativo) — nunca rebaixa;
  * PRESERVA um membro comum cujo número NÃO é o do WhatsApp;
  * é tenant-safe (conexão de OUTRA igreja não reclassifica);
  * é idempotente (reexecutar não muda nada).

Integração pura contra Postgres descartável (mesmo padrão de
`test_backfill_pessoa_tipo_membro.py`): sem `RLS_TEST_DATABASE_URL`, skip limpo;
com a env var, roda de verdade aplicando o ARQUIVO real da migration.
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
    / "20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql"
)

# Schema mínimo: pessoas.tipo (enum real) + pessoas.telefone, celulas,
# celula_membro e whatsapp_connections. conftest_rls já cria/semeia igrejas +
# pessoas(id, igreja_id, nome). Idempotente (if not exists / add column if not exists).
_SETUP_SQL = """
do $$ begin
  if not exists (select 1 from pg_type where typname = 'pessoa_tipo') then
    create type pessoa_tipo as enum
      ('visitante', 'membro', 'lider', 'pastor', 'discipulo', 'contato');
  end if;
end $$;

alter table pessoas add column if not exists tipo pessoa_tipo;
alter table pessoas add column if not exists telefone text;

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

create table if not exists whatsapp_connections (
  id        uuid primary key default gen_random_uuid(),
  igreja_id uuid not null unique references igrejas(id) on delete cascade,
  numero    text
);
"""

_CELULA_A = "0c0c0c0c-0000-0000-0000-0000000000a1"

# Número conectado ao WhatsApp da igreja A (forma WhatsApp: 55 + DDD + 8 dígitos).
_NUMERO_WA = "558994315927"
# Mesma linha, cadastrada com máscara / 9º dígito na pessoa (casa por sufixo).
_TEL_WA_MASK = "+55 (89) 99431-5927"
_TEL_OUTRO = "11988887777"
# DISCRIMINANTE: MESMOS 8 dígitos finais (94315927) do número WhatsApp, mas DDD
# DIFERENTE (11 vs 89). Sob o bug antigo (right(...,8)) casaria e reclassificaria
# indevidamente; sob a chave canônica completa (11994315927 vs 89994315927) NÃO
# casa. Este é o caso que trava a correção F4/F5 contra regressão.
_TEL_COLIDE = "+55 (11) 99431-5927"

_P_NUMERO = "e0000000-0000-0000-0000-000000000001"     # A: o número, membro sem vínculo → contato
_P_MEMBRO_REAL = "e0000000-0000-0000-0000-000000000002"  # A: mesmo número, COM vínculo → preserva
_P_OUTRO = "e0000000-0000-0000-0000-000000000003"       # A: membro de outra linha → preserva
_P_COLIDE = "e0000000-0000-0000-0000-000000000005"      # A: sufixo 8 díg. igual, DDD ≠ → preserva
# B: telefone == número do WhatsApp de A, mas a conexão só existe em A. Tenant-safe:
# o EXISTS casa wc.igreja_id = p.igreja_id, então a conexão de A NÃO alcança esta
# pessoa de B → preserva 'membro'. (Sem conexão em B.)
_P_CROSS = "e0000000-0000-0000-0000-000000000004"


def _uuid_list(*ids: str) -> str:
    return ", ".join(f"'{i}'::uuid" for i in ids)


def _cleanup(conn) -> None:
    todos = [_P_NUMERO, _P_MEMBRO_REAL, _P_OUTRO, _P_CROSS, _P_COLIDE]
    conn.execute(text(f"delete from celula_membro where pessoa_id in ({_uuid_list(*todos)})"))
    conn.execute(text(f"delete from pessoas where id in ({_uuid_list(*todos)})"))
    conn.execute(text(f"delete from celulas where id = '{_CELULA_A}'::uuid"))
    conn.execute(
        text("delete from whatsapp_connections where igreja_id in (:a, :b)"),
        {"a": IGREJA_A, "b": IGREJA_B},
    )


@pytest.fixture
def seeded_engine(rls_engine: Engine, rls_seeded: dict[str, str]):
    with rls_engine.begin() as conn:
        conn.execute(text(_SETUP_SQL))
        _cleanup(conn)
        conn.execute(
            text("insert into celulas (id, igreja_id) values (:c, :i)"),
            {"c": _CELULA_A, "i": IGREJA_A},
        )
        # Conexão WhatsApp só na igreja A.
        conn.execute(
            text("insert into whatsapp_connections (igreja_id, numero) values (:i, :n)"),
            {"i": IGREJA_A, "n": _NUMERO_WA},
        )
        for pid, igreja, tipo, tel in (
            (_P_NUMERO, IGREJA_A, "membro", _TEL_WA_MASK),
            (_P_MEMBRO_REAL, IGREJA_A, "membro", _TEL_WA_MASK),
            (_P_OUTRO, IGREJA_A, "membro", _TEL_OUTRO),
            (_P_CROSS, IGREJA_B, "membro", _TEL_WA_MASK),  # outra igreja, sem conexão
            (_P_COLIDE, IGREJA_A, "membro", _TEL_COLIDE),  # sufixo 8 díg. igual, DDD ≠
        ):
            conn.execute(
                text(
                    "insert into pessoas (id, igreja_id, nome, tipo, telefone) "
                    "values (:id, :ig, 'X', :tipo, :tel)"
                ),
                {"id": pid, "ig": igreja, "tipo": tipo, "tel": tel},
            )
        # Só _P_MEMBRO_REAL tem vínculo ATIVO (membro legítimo → intocado).
        conn.execute(
            text(
                "insert into celula_membro (igreja_id, celula_id, pessoa_id, ativo) "
                "values (:ig, :cel, :pid, true)"
            ),
            {"ig": IGREJA_A, "cel": _CELULA_A, "pid": _P_MEMBRO_REAL},
        )
    yield rls_engine
    with rls_engine.begin() as conn:
        _cleanup(conn)


def _tipo(engine: Engine, pessoa_id: str) -> str | None:
    with engine.begin() as conn:
        return conn.execute(
            text("select tipo from pessoas where id = :id"), {"id": pessoa_id}
        ).scalar_one()


def _apply_migration(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(_MIGRATION_PATH.read_text(encoding="utf-8")))


def test_reclassifica_so_o_numero_sem_vinculo(seeded_engine: Engine) -> None:
    _apply_migration(seeded_engine)
    assert _tipo(seeded_engine, _P_NUMERO) == "contato"       # o número → contato
    assert _tipo(seeded_engine, _P_MEMBRO_REAL) == "membro"   # membro real preservado
    assert _tipo(seeded_engine, _P_OUTRO) == "membro"         # outra linha preservada
    assert _tipo(seeded_engine, _P_CROSS) == "membro"         # tenant-safe (pessoa em B, conexão só em A)
    assert _tipo(seeded_engine, _P_COLIDE) == "membro"        # sufixo 8 díg. igual, DDD ≠ → NÃO reclassifica


def test_migration_is_idempotent(seeded_engine: Engine) -> None:
    _apply_migration(seeded_engine)
    snapshot = {
        pid: _tipo(seeded_engine, pid)
        for pid in (_P_NUMERO, _P_MEMBRO_REAL, _P_OUTRO, _P_CROSS)
    }
    _apply_migration(seeded_engine)  # 2ª aplicação não muda nada
    for pid, esperado in snapshot.items():
        assert _tipo(seeded_engine, pid) == esperado, pid
