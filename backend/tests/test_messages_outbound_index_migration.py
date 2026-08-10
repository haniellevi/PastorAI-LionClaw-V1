"""Contrato estrutural da migration de idempotência outbound."""

from pathlib import Path

from app.db.models import Message


_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260808_011500_messages_outbound_provider_id_uidx.sql"
)
_INDEX_NAME = "messages_outbound_provider_id_uidx"


def _executable_sql() -> str:
    lines = []
    for line in _MIGRATION.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            lines.append(stripped)
    return " ".join(lines).lower()


def test_outbound_provider_index_migration_is_concurrent_and_standalone() -> None:
    sql = _executable_sql()

    assert sql.count(";") == 1
    assert f"create unique index concurrently {_INDEX_NAME}" in sql
    assert "on messages (igreja_id, provider_message_id)" in sql
    assert "where direcao = 'out' and provider_message_id is not null" in sql
    assert "if not exists" not in sql
    assert "begin;" not in sql
    assert "commit;" not in sql


def test_outbound_provider_index_migration_matches_the_orm_model() -> None:
    index = next(index for index in Message.__table__.indexes if index.name == _INDEX_NAME)

    assert index.unique is True
    assert [column.name for column in index.columns] == [
        "igreja_id",
        "provider_message_id",
    ]
    predicate = str(index.dialect_options["postgresql"]["where"]).lower()
    assert predicate == "direcao = 'out' and provider_message_id is not null"
