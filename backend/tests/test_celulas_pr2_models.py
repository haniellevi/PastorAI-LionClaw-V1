"""Células PR2 — schema/model de reunião / presença / expectativa de visitante.

O harness de testes é in-memory (não há Postgres real), então UNIQUE, CHECK e
RLS não são exercitados aqui em runtime. Estes testes cobrem o que é verificável
em Python puro + inspeção do SQL da migration:

  - os 3 modelos (`CelulaReuniao`, `CelulaPresenca`, `CelulaExpectativaVisitante`)
    têm as colunas do PR2 com nullability/defaults corretos;
  - as FKs novas (igreja/celula/reuniao/pessoa) apontam pros alvos certos e são
    ON DELETE CASCADE (DB-DEC-04);
  - a migration declara os UNIQUE de celula_reuniao e celula_presenca e NÃO
    declara UNIQUE em celula_expectativa_visitante;
  - a migration declara os CHECK de status (celula_reuniao) e estado
    (celula_presenca) com os valores permitidos, o CHECK de hora HH:MM NOT VALID,
    os indexes esperados, e o padrão de RLS (enable + tenant_isolation) das 3
    tabelas — idêntico ao PR1;
  - a migration é 100% aditiva: não contém ALTER/DROP em celulas/pessoas/
    celula_membro/multiplicacoes.

A validação de que a migration realmente aplica (constraints/RLS efetivas) é
manual no Supabase DEV — ver docs/design/CELULAS-DECISOES-FINAIS.md.
"""

from __future__ import annotations

import pathlib

from app.db.models import (
    CelulaExpectativaVisitante,
    CelulaPresenca,
    CelulaReuniao,
)

_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260704_100000_celula_pr2_reuniao_presenca_expectativa.sql"
)


def _sql() -> str:
    return _MIGRATION.read_text(encoding="utf-8").lower()


# ---- modelo: colunas / nullability / defaults ------------------------------
def test_celula_reuniao_columns() -> None:
    cols = CelulaReuniao.__table__.columns
    for name in (
        "id",
        "igreja_id",
        "celula_id",
        "data",
        "hora",
        "tema",
        "status",
        "created_at",
        "updated_at",
    ):
        assert name in cols, f"coluna {name} faltando em celula_reuniao"
    # NOT NULL
    assert cols["igreja_id"].nullable is False
    assert cols["celula_id"].nullable is False
    assert cols["data"].nullable is False
    assert cols["status"].nullable is False
    assert cols["created_at"].nullable is False
    # nullable
    assert cols["hora"].nullable is True
    assert cols["tema"].nullable is True
    assert cols["updated_at"].nullable is True
    # defaults
    assert "planejada" in str(cols["status"].server_default.arg)
    assert cols["created_at"].server_default is not None
    # updated_at gerenciado pela aplicação (sem server_default)
    assert cols["updated_at"].server_default is None


def test_celula_presenca_columns() -> None:
    cols = CelulaPresenca.__table__.columns
    for name in (
        "id",
        "igreja_id",
        "reuniao_id",
        "pessoa_id",
        "estado",
        "origem",
        "created_at",
        "updated_at",
    ):
        assert name in cols, f"coluna {name} faltando em celula_presenca"
    assert cols["igreja_id"].nullable is False
    assert cols["reuniao_id"].nullable is False
    assert cols["pessoa_id"].nullable is False
    assert cols["estado"].nullable is False
    assert cols["created_at"].nullable is False
    assert cols["origem"].nullable is True
    assert cols["updated_at"].nullable is True
    assert cols["updated_at"].server_default is None


def test_celula_expectativa_columns() -> None:
    cols = CelulaExpectativaVisitante.__table__.columns
    for name in (
        "id",
        "igreja_id",
        "reuniao_id",
        "pessoa_id",
        "nome_visitante",
        "observacao_oracao",
        "created_at",
        "updated_at",
    ):
        assert name in cols, f"coluna {name} faltando em celula_expectativa_visitante"
    assert cols["igreja_id"].nullable is False
    assert cols["reuniao_id"].nullable is False
    assert cols["pessoa_id"].nullable is False
    assert cols["nome_visitante"].nullable is False
    assert cols["created_at"].nullable is False
    assert cols["observacao_oracao"].nullable is True
    assert cols["updated_at"].nullable is True
    assert cols["updated_at"].server_default is None


# ---- modelo: FKs ON DELETE CASCADE (DB-DEC-04) -----------------------------
def _fk_target(model, col: str) -> str:
    fks = list(model.__table__.c[col].foreign_keys)
    assert len(fks) == 1, f"{col} deveria ter exatamente 1 FK"
    return fks[0].column.table.name


def _fk_ondelete(model, col: str) -> str:
    fks = list(model.__table__.c[col].foreign_keys)
    return (fks[0].ondelete or "").upper()


def test_celula_reuniao_fks_cascade() -> None:
    assert _fk_target(CelulaReuniao, "igreja_id") == "igrejas"
    assert _fk_target(CelulaReuniao, "celula_id") == "celulas"
    assert _fk_ondelete(CelulaReuniao, "igreja_id") == "CASCADE"
    assert _fk_ondelete(CelulaReuniao, "celula_id") == "CASCADE"


def test_celula_presenca_fks_cascade() -> None:
    assert _fk_target(CelulaPresenca, "igreja_id") == "igrejas"
    assert _fk_target(CelulaPresenca, "reuniao_id") == "celula_reuniao"
    assert _fk_target(CelulaPresenca, "pessoa_id") == "pessoas"
    for col in ("igreja_id", "reuniao_id", "pessoa_id"):
        assert _fk_ondelete(CelulaPresenca, col) == "CASCADE"


def test_celula_expectativa_fks_cascade() -> None:
    assert _fk_target(CelulaExpectativaVisitante, "igreja_id") == "igrejas"
    assert _fk_target(CelulaExpectativaVisitante, "reuniao_id") == "celula_reuniao"
    assert _fk_target(CelulaExpectativaVisitante, "pessoa_id") == "pessoas"
    for col in ("igreja_id", "reuniao_id", "pessoa_id"):
        assert _fk_ondelete(CelulaExpectativaVisitante, col) == "CASCADE"


# ---- migration: cria as 3 tabelas ------------------------------------------
def test_migration_creates_three_tables() -> None:
    sql = _sql()
    assert "create table if not exists celula_reuniao" in sql
    assert "create table if not exists celula_presenca" in sql
    assert "create table if not exists celula_expectativa_visitante" in sql
    # todas as FKs novas apontam p/ igrejas com CASCADE.
    assert "references igrejas(id) on delete cascade" in sql
    assert "references celulas(id) on delete cascade" in sql
    assert "references celula_reuniao(id) on delete cascade" in sql
    assert "references pessoas(id) on delete cascade" in sql


# ---- migration: UNIQUE (presença sim, expectativa não) ---------------------
def test_migration_unique_constraints() -> None:
    sql = _sql()
    # celula_reuniao: UNIQUE por slot com coalesce(hora,'') p/ tratar hora NULL.
    assert "celula_reuniao_slot_uq" in sql
    assert "coalesce(hora, '')" in sql
    # celula_presenca: UNIQUE por (igreja, reunião, pessoa).
    assert "celula_presenca_pessoa_uq" in sql


def test_expectativa_has_no_unique() -> None:
    sql = _sql()
    # A tabela de expectativa NÃO deve declarar nenhum unique index.
    assert "celula_expectativa" in sql  # sanidade: bloco existe
    # nenhum "unique index" referenciando a tabela de expectativa.
    for line in sql.splitlines():
        if "unique index" in line and "celula_expectativa" in line:
            raise AssertionError("celula_expectativa_visitante não deve ter UNIQUE")


# ---- migration: CHECKs (status / estado / hora) ----------------------------
def test_migration_status_check_values() -> None:
    sql = _sql()
    assert "celula_reuniao_status_chk" in sql
    for value in ("'planejada'", "'confirmada'", "'realizada'", "'cancelada'"):
        assert value in sql, f"status permitido {value} faltando no CHECK"


def test_migration_estado_check_values() -> None:
    sql = _sql()
    assert "celula_presenca_estado_chk" in sql
    for value in ("'confirmada'", "'compareceu'", "'ausente'"):
        assert value in sql, f"estado permitido {value} faltando no CHECK"


def test_migration_hora_check_not_valid() -> None:
    sql = _sql()
    assert "celula_reuniao_hora_chk" in sql
    # HH:MM, no mesmo padrão NOT VALID de celulas_horario_chk (PR1).
    assert "not valid" in sql


# ---- migration: indexes esperados ------------------------------------------
def test_migration_indexes() -> None:
    sql = _sql()
    for idx in (
        "celula_reuniao_igreja_idx",
        "celula_reuniao_igreja_celula_idx",
        "celula_reuniao_igreja_celula_data_idx",
        "celula_presenca_igreja_idx",
        "celula_presenca_igreja_reuniao_idx",
        "celula_expectativa_igreja_idx",
        "celula_expectativa_igreja_reuniao_idx",
        "celula_expectativa_igreja_pessoa_idx",
    ):
        assert idx in sql, f"index {idx} faltando na migration"


# ---- migration: RLS padrão PR1 nas 3 tabelas -------------------------------
def test_migration_rls_pattern() -> None:
    sql = _sql()
    for tbl in ("celula_reuniao", "celula_presenca", "celula_expectativa_visitante"):
        assert f"alter table {tbl} enable row level security" in sql
    # policy tenant_isolation cobrindo ALL (for all) com USING/WITH CHECK.
    assert sql.count("create policy tenant_isolation") == 3
    assert "using (igreja_id = current_igreja_id())" in sql
    assert "with check (igreja_id = current_igreja_id())" in sql


# ---- migration: 100% aditiva (não toca no PR1) -----------------------------
def test_migration_is_purely_additive() -> None:
    sql = _sql()
    # Não deve conter ALTER/DROP sobre as tabelas do PR1.
    for tbl in ("celulas", "pessoas", "celula_membro", "multiplicacoes"):
        assert f"alter table {tbl} " not in sql, f"migration não deve alterar {tbl}"
        assert f"drop table {tbl}" not in sql, f"migration não deve dropar {tbl}"
    assert "drop table" not in sql
