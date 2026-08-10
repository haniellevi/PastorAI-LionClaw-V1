"""Structural guard for the per-tenant LLM model migration."""

from __future__ import annotations

from pathlib import Path

from app.db.models import LlmCredential


_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260808_135841_llm_model_selection_per_tenant.sql"
)


def test_llm_credential_model_is_required_in_orm() -> None:
    column = LlmCredential.__table__.c.modelo
    assert column.nullable is False
    assert "gpt-5.6-luna" in str(column.server_default.arg)


def test_migration_backfills_default_and_database_allowlist() -> None:
    sql = _MIGRATION.read_text(encoding="utf-8").lower()

    assert "add column if not exists modelo text" in sql
    assert "set modelo = 'gpt-5.6-luna'" in sql
    assert "alter column modelo set not null" in sql
    assert "llm_credentials_modelo_check" in sql
    for model in ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"):
        assert model in sql
    assert sql.strip().startswith("--")
    assert "begin;" in sql and sql.rstrip().endswith("commit;")
