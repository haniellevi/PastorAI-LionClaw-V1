"""Structural guards for the unapplied BROADCAST-DELIVERY-1 migration."""

from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _migration() -> tuple[Path, str]:
    matches = sorted(MIGRATIONS.glob("20260805_*_broadcast_delivery.sql"))
    assert len(matches) == 1
    path = matches[0]
    return path, path.read_text(encoding="utf-8").lower()


def test_migration_keeps_existing_broadcast_status_enum_and_no_backfill() -> None:
    path, sql = _migration()
    assert path.name.startswith("20260805_")
    assert "alter type broadcast_status" not in sql
    assert "add column if not exists proxima_execucao" in sql
    assert re.search(r"(?m)^\s*update\s+broadcasts\b", sql) is None


def test_migration_creates_occurrence_and_delivery_ledger_states() -> None:
    _path, sql = _migration()
    assert "create table if not exists broadcast_execucoes" in sql
    assert "create table if not exists broadcast_entregas" in sql
    for state in (
        "pendente",
        "em_envio",
        "aceito",
        "falhou_retentavel",
        "falhou_permanente",
        "desconhecido",
        "suprimido",
    ):
        assert f"'{state}'" in sql


def test_migration_has_durable_dedupe_claim_and_reaper_indexes() -> None:
    _path, sql = _migration()
    assert "broadcast_execucoes_seq_uq" in sql
    assert "broadcast_execucoes_slot_uq" in sql
    assert "broadcast_entregas_execucao_telefone_uq" in sql
    assert "broadcast_entregas_execucao_pessoa_uq" in sql
    assert "idx_broadcast_entregas_pessoa" in sql
    assert "idx_broadcast_entregas_trabalho" in sql
    assert "idx_broadcast_entregas_lease" in sql
    assert "broadcasts_igreja_idempotency_uq" in sql
    assert "idx_broadcast_entregas_retry_due" in sql
    assert "next_attempt_at" in sql
    assert "retry_budget_used" in sql
    assert "where status = 'em_envio'" in sql


def test_migration_applies_tenant_isolation_to_both_new_tables() -> None:
    _path, sql = _migration()
    for table in ("broadcast_execucoes", "broadcast_entregas"):
        assert f"alter table {table} enable row level security" in sql
        assert f"drop policy if exists tenant_isolation on {table}" in sql
        assert f"create policy tenant_isolation on {table}" in sql
    assert sql.count("using (igreja_id = current_igreja_id())") == 2
    assert sql.count("with check (igreja_id = current_igreja_id())") == 2


def test_migration_does_not_expose_delivery_ledger_to_anon() -> None:
    _path, sql = _migration()
    for table in ("broadcast_execucoes", "broadcast_entregas"):
        assert f"revoke all privileges on table {table} from public" in sql
        assert f"revoke all privileges on table {table} from anon" in sql
        assert f"revoke all privileges on table {table} from authenticated" in sql
        assert (
            f"grant select, insert, update, delete on table {table} "
            "to authenticated"
        ) in sql


def test_hour_constraint_accepts_2359_but_not_2400_without_breaking_legacy() -> None:
    _path, sql = _migration()
    assert "^([01][0-9]|2[0-3]):[0-5][0-9]$" in sql
    assert "constraint broadcasts_hora_chk" in sql
    assert "not valid" in sql
