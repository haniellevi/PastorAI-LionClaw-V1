"""Structural guards for the additive Calendar FK index migration."""

from __future__ import annotations

import re
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260805_120000_calendar_fk_indexes.sql"
)


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_calendar_fk_indexes_are_additive_and_idempotent() -> None:
    sql = _sql()
    for index in (
        "idx_calendar_oauth_flows_igreja",
        "idx_calendar_oauth_flows_app_user",
        "idx_calendar_sync_connected_by_app_user",
    ):
        assert f"create index if not exists {index}" in sql

    assert re.search(r"(?m)^\s*(update|delete|alter\s+table|drop)\b", sql) is None


def test_nullable_set_null_fk_uses_a_partial_index() -> None:
    sql = _sql()
    assert "on calendar_sync (connected_by_app_user_id)" in sql
    assert "where connected_by_app_user_id is not null" in sql
