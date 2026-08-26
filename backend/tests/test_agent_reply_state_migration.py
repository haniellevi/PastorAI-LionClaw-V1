"""Schema contract for the durable agent-reply state machine.

The always-on checks keep the ORM, migration and three-value authorship enum
aligned. The opt-in test applies the real migration twice to an isolated schema
in disposable PostgreSQL and exercises its database constraint.
"""

from __future__ import annotations

import pathlib

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.db.models import Message
from app.domain.agent_reply import AGENT_REPLY_STATES
from tests.conftest_rls import rls_database_url, rls_engine  # noqa: F401

_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260826_030508_separar_estado_resposta_agente_de_autor_mensagem.sql"
)
_BASE_ENUMS = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "0001_extensions_and_enums.sql"
)
_SCHEMA = "agent_reply_state_migration"
_CONSTRAINT = "messages_agent_reply_state_check"


def _sql() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def _schema_sql() -> str:
    return _sql().replace("public.", f"{_SCHEMA}.")


def _apply_real_migration(engine: Engine) -> None:
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute(_schema_sql())
            raw.commit()
        finally:
            cursor.close()
    finally:
        raw.close()


def test_message_author_enum_remains_the_three_value_public_contract() -> None:
    base_sql = " ".join(_BASE_ENUMS.read_text(encoding="utf-8").lower().split())
    migration_sql = " ".join(_sql().lower().split())

    assert "message_autor as enum ('contato', 'ia', 'humano')" in base_sql
    assert "alter type" not in migration_sql
    assert "create type" not in migration_sql


def test_migration_and_orm_share_the_dedicated_state_constraint() -> None:
    column = Message.__table__.columns["agent_reply_state"]
    constraint = next(
        item
        for item in Message.__table__.constraints
        if item.name == _CONSTRAINT
    )
    migration_sql = _sql().lower()
    orm_sql = str(constraint.sqltext).lower()

    assert column.nullable is True
    assert "add column if not exists agent_reply_state text" in migration_sql
    assert "not valid" in migration_sql
    assert f"validate constraint {_CONSTRAINT}" in migration_sql
    for state in AGENT_REPLY_STATES:
        assert f"'{state}'" in migration_sql
        assert f"'{state}'" in orm_sql
    assert "autor = 'ia'" in migration_sql
    assert "direcao = 'out'" in migration_sql


@pytest.mark.rls_integration
def test_real_migration_preserves_enum_and_enforces_internal_state(
    rls_engine: Engine,
) -> None:
    with rls_engine.begin() as conn:
        conn.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade")
        conn.exec_driver_sql(f"create schema {_SCHEMA}")
        conn.exec_driver_sql(
            f"create type {_SCHEMA}.message_direcao as enum ('in', 'out')"
        )
        conn.exec_driver_sql(
            f"create type {_SCHEMA}.message_autor "
            "as enum ('contato', 'ia', 'humano')"
        )
        conn.exec_driver_sql(
            f"create table {_SCHEMA}.messages ("
            "id bigint generated always as identity primary key, "
            f"direcao {_SCHEMA}.message_direcao not null, "
            f"autor {_SCHEMA}.message_autor not null, "
            "texto text)"
        )
        conn.exec_driver_sql(
            f"insert into {_SCHEMA}.messages (direcao, autor, texto) values "
            "('in', 'contato', 'entrada'), "
            "('out', 'ia', 'legado confirmado'), "
            "('out', 'humano', 'resposta humana')"
        )

    try:
        _apply_real_migration(rls_engine)
        _apply_real_migration(rls_engine)

        with rls_engine.begin() as conn:
            enum_labels = conn.exec_driver_sql(
                "select e.enumlabel from pg_enum e "
                "join pg_type t on t.oid = e.enumtypid "
                "join pg_namespace n on n.oid = t.typnamespace "
                "where n.nspname = %s and t.typname = 'message_autor' "
                "order by e.enumsortorder",
                (_SCHEMA,),
            ).scalars().all()
            column = conn.exec_driver_sql(
                "select data_type, is_nullable from information_schema.columns "
                "where table_schema = %s and table_name = 'messages' "
                "and column_name = 'agent_reply_state'",
                (_SCHEMA,),
            ).one()
            constraint_validated = conn.exec_driver_sql(
                "select convalidated from pg_constraint "
                "where conname = %s "
                "and conrelid = %s::regclass",
                (_CONSTRAINT, f"{_SCHEMA}.messages"),
            ).scalar_one()
            legacy_rows = conn.exec_driver_sql(
                f"select autor::text, agent_reply_state from {_SCHEMA}.messages "
                "order by id"
            ).all()

            assert enum_labels == ["contato", "ia", "humano"]
            assert column == ("text", "YES")
            assert constraint_validated is True
            assert legacy_rows == [
                ("contato", None),
                ("ia", None),
                ("humano", None),
            ]

            for state in AGENT_REPLY_STATES:
                conn.exec_driver_sql(
                    f"insert into {_SCHEMA}.messages "
                    "(direcao, autor, agent_reply_state) values ('out', 'ia', %s)",
                    (state,),
                )

        with pytest.raises(IntegrityError):
            with rls_engine.begin() as conn:
                conn.exec_driver_sql(
                    f"insert into {_SCHEMA}.messages "
                    "(direcao, autor, agent_reply_state) "
                    "values ('out', 'humano', 'ia_pendente')"
                )

        with pytest.raises(IntegrityError):
            with rls_engine.begin() as conn:
                conn.exec_driver_sql(
                    f"insert into {_SCHEMA}.messages "
                    "(direcao, autor, agent_reply_state) "
                    "values ('out', 'ia', 'estado_desconhecido')"
                )
    finally:
        with rls_engine.begin() as conn:
            conn.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade")
