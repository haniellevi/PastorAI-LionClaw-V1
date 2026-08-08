"""Contrato estrutural da migration que muda o porte para membros ativos."""

from __future__ import annotations

from pathlib import Path

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260808_001059_billing_count_active_members.sql"
)
_LABEL_VARIANTS_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260808_014425_billing_member_plan_label_variants.sql"
)


def _sql() -> str:
    return " ".join(_MIGRATION.read_text(encoding="utf-8").lower().split())


def _label_variants_sql() -> str:
    return " ".join(
        _LABEL_VARIANTS_MIGRATION.read_text(encoding="utf-8").lower().split()
    )


def test_trigger_counts_only_active_members_and_handles_decreases() -> None:
    sql = _sql()

    assert "tipo in ('membro', 'discipulo', 'lider', 'pastor')" in sql
    assert "arquivada_em is null" in sql
    assert "coalesce(sem_interesse, false) is false" in sql
    assert "after insert or update or delete on pessoas" in sql
    assert "if tg_op = 'delete'" in sql


def test_migration_recalculates_existing_mirrors_and_keeps_durable_upgrade() -> None:
    sql = _sql()

    assert "update subscriptions s set pessoas =" in sql
    assert "insert into billing_plan_change_operations" in sql
    assert "'autoupgrade', 'prepared', 'pending'" in sql
    assert "on conflict (subscription_id)" in sql
    # O único upgrade local permanece no ramo sem assinatura Asaas.
    null_branch = sql.index("if v_sub.asaas_subscription_id is null then")
    local_update = sql.index("set plano = v_novo_plano", null_branch)
    durable_insert = sql.index("insert into billing_plan_change_operations")
    assert null_branch < local_update < durable_insert


def test_migration_preserves_legacy_columns_and_updates_default_labels() -> None:
    sql = _sql()

    assert "comment on column subscriptions.pessoas" in sql
    assert "comment on column planos.limite_pessoas" in sql
    assert "até 100 membros" in sql
    assert "101–200 membros" in sql
    assert "201+ membros" in sql
    assert "revoke all on function public.fn_subscription_autoupgrade()" in sql


def test_follow_up_migration_updates_only_known_legacy_label_variant() -> None:
    sql = _label_variants_sql()

    assert "update public.planos" in sql
    assert "codigo = '101_200'" in sql
    assert "101 a 200 pessoas" in sql
    assert "set nome = '101–200 membros'" in sql
