"""W3: schema de arquivamento de Pessoa (arquivada_em/por/motivo).

Duas camadas:

  - testes sempre-on (sem Postgres real): paridade ORM <-> SQL da migration,
    nullability, tipo, e o FK ON DELETE SET NULL declarados no arquivo;
  - `test_migration_postgres_real` (opt-in, `RLS_TEST_DATABASE_URL`): aplica a
    migration de verdade num Postgres descartavel (schema minimo de
    `conftest_rls`), prova que uma pessoa existente permanece ativa
    (arquivada_em IS NULL) e que o FK realmente faz SET NULL quando o
    app_user referenciado e removido.
"""

from __future__ import annotations

import pathlib
import uuid

import pytest
from sqlalchemy import text

from app.db.models import Pessoa
from tests.conftest_rls import rls_database_url  # noqa: F401
from tests.conftest_rls import rls_engine  # noqa: F401
from tests.conftest_rls import rls_seeded  # noqa: F401

_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260713_013054_pessoa_arquivamento_schema.sql"
)


def _sql() -> str:
    return _MIGRATION.read_text(encoding="utf-8").lower()


# ---- ORM: colunas / nullability / FK ---------------------------------------
def test_orm_columns_present_and_nullable() -> None:
    cols = Pessoa.__table__.columns
    for name in ("arquivada_em", "arquivada_por", "arquivada_motivo"):
        assert name in cols, f"coluna {name} faltando no modelo Pessoa"
        assert cols[name].nullable, f"{name} deve ser nullable (NULL = ativa)"

    # nenhum boolean `ativo` novo, nem alteracao de pessoa_tipo (contrato W3).
    assert "ativo" not in cols


def test_orm_fk_arquivada_por_set_null() -> None:
    fks = {fk.column.table.name: fk for fk in Pessoa.__table__.columns["arquivada_por"].foreign_keys}
    assert "app_users" in fks
    assert fks["app_users"].ondelete == "SET NULL"


# ---- migration SQL: paridade com o ORM -------------------------------------
def test_migration_adds_expected_columns() -> None:
    sql = _sql()
    assert "add column if not exists arquivada_em timestamptz" in sql
    assert (
        "add column if not exists arquivada_por uuid references app_users(id) "
        "on delete set null" in sql
    )
    assert "add column if not exists arquivada_motivo text" in sql

    # nao declara NOT NULL em nenhuma das 3 (todas opcionais).
    for col in ("arquivada_em", "arquivada_por", "arquivada_motivo"):
        assert f"{col} timestamptz not null" not in sql
        assert f"{col} uuid not null" not in sql
        assert f"{col} text not null" not in sql


def test_migration_is_additive_only() -> None:
    sql = _sql()
    assert "drop " not in sql
    assert "alter column" not in sql
    assert "not null" not in sql or "add column" in sql  # sem NOT NULL fora de add column


# ---- Postgres real (opt-in) -------------------------------------------------
pytestmark_pg = pytest.mark.rls_integration


@pytest.mark.rls_integration
def test_migration_postgres_real(rls_engine, rls_seeded: dict[str, str]) -> None:  # noqa: F811
    igreja_a = rls_seeded["A"]

    # IDs podem nunca ser atribuidos (falha antes do insert correspondente) —
    # o finally so tenta apagar o que de fato foi criado.
    pessoa_id: uuid.UUID | None = None
    app_user_id: uuid.UUID | None = None

    try:
        with rls_engine.begin() as conn:
            # pessoa propria do teste (isolada da seedada pela fixture de
            # sessao, que persiste no container entre execucoes) —
            # representa um registro "existente" ANTES da
            # migration/arquivamento rodarem. Removida no finally: o
            # schema/seed de conftest_rls e compartilhado com outros testes
            # rls_integration na mesma sessao/container.
            pessoa_id = conn.execute(
                text(
                    "insert into pessoas (igreja_id, nome) values (:ig, :nome) "
                    "returning id"
                ),
                {"ig": igreja_a, "nome": f"Pessoa arquivamento {uuid.uuid4()}"},
            ).scalar_one()

            # app_user descartavel, referenciado pelo arquivamento.
            app_user_id = conn.execute(
                text(
                    "insert into app_users (igreja_id, clerk_user_id) "
                    "values (:ig, :sub) returning id"
                ),
                {"ig": igreja_a, "sub": f"clerk-arquivista-{uuid.uuid4()}"},
            ).scalar_one()

        # aplica a migration de verdade (idempotente).
        with rls_engine.begin() as conn:
            conn.exec_driver_sql(_MIGRATION.read_text(encoding="utf-8"))

        with rls_engine.begin() as conn:
            # colunas existem, tipos e nullability corretos.
            rows = conn.execute(
                text(
                    "select column_name, data_type, is_nullable "
                    "from information_schema.columns "
                    "where table_name = 'pessoas' "
                    "and column_name in ('arquivada_em', 'arquivada_por', 'arquivada_motivo')"
                )
            ).mappings().all()
            by_name = {r["column_name"]: r for r in rows}
            assert by_name["arquivada_em"]["data_type"] == "timestamp with time zone"
            assert by_name["arquivada_em"]["is_nullable"] == "YES"
            assert by_name["arquivada_por"]["data_type"] == "uuid"
            assert by_name["arquivada_por"]["is_nullable"] == "YES"
            assert by_name["arquivada_motivo"]["data_type"] == "text"
            assert by_name["arquivada_motivo"]["is_nullable"] == "YES"

            # pessoa que ja existia continua ativa (nao arquivada pela migration).
            arquivada_em = conn.execute(
                text("select arquivada_em from pessoas where id = :id"),
                {"id": pessoa_id},
            ).scalar_one()
            assert arquivada_em is None

            # marca a pessoa como arquivada pelo app_user descartavel.
            conn.execute(
                text(
                    "update pessoas set arquivada_em = now(), arquivada_por = :au, "
                    "arquivada_motivo = 'teste' where id = :id"
                ),
                {"au": app_user_id, "id": pessoa_id},
            )

        with rls_engine.begin() as conn:
            # remove o app_user: FK deve fazer SET NULL, NAO bloquear nem apagar a pessoa.
            conn.execute(text("delete from app_users where id = :id"), {"id": app_user_id})

        with rls_engine.begin() as conn:
            row = conn.execute(
                text(
                    "select arquivada_em, arquivada_por from pessoas where id = :id"
                ),
                {"id": pessoa_id},
            ).mappings().one()
            assert row["arquivada_em"] is not None  # trilha de auditoria preservada
            assert row["arquivada_por"] is None  # SET NULL, pessoa nao foi apagada
    finally:
        # Limpeza best-effort: tolera IDs nao criados (falha antes do insert)
        # e nao mascara a excecao original do teste — cada delete roda no seu
        # proprio try/except, entao uma falha de limpeza nunca sobrescreve o
        # erro real do teste (nem impede a tentativa do segundo delete).
        # Ordem de FK: Pessoa antes de AppUser (arquivada_por -> app_users).
        if pessoa_id is not None:
            try:
                with rls_engine.begin() as conn:
                    conn.execute(
                        text("delete from pessoas where id = :id"), {"id": pessoa_id}
                    )
            except Exception:
                pass

        if app_user_id is not None:
            try:
                with rls_engine.begin() as conn:
                    conn.execute(
                        text("delete from app_users where id = :id"),
                        {"id": app_user_id},
                    )
            except Exception:
                pass
