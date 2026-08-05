"""Structural guards for SECURITY DEFINER execute hardening."""

from __future__ import annotations

from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260805_153000_security_definer_execute_hardening.sql"
)


def _sql() -> str:
    return " ".join(MIGRATION.read_text(encoding="utf-8").lower().split())


def test_anon_cannot_execute_any_security_definer_helper() -> None:
    sql = _sql()
    assert (
        "revoke execute on function public.current_igreja_id() "
        "from public, anon"
    ) in sql
    for function in ("fn_subscription_autoupgrade", "rls_auto_enable"):
        assert (
            f"revoke execute on function public.{function}() "
            "from public, anon, authenticated"
        ) in sql


def test_authenticated_keeps_only_the_rls_tenant_helper() -> None:
    sql = _sql()
    assert (
        "grant execute on function public.current_igreja_id() "
        "to authenticated, service_role"
    ) in sql
    assert "current_igreja_id() from public, anon, authenticated" not in sql


def test_trigger_helpers_remain_available_only_for_maintenance_role() -> None:
    sql = _sql()
    for function in ("fn_subscription_autoupgrade", "rls_auto_enable"):
        assert (
            f"grant execute on function public.{function}() to service_role"
        ) in sql
