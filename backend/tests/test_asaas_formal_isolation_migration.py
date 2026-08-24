"""Static contract for the shared-account Asaas isolation migration."""

from __future__ import annotations

import pathlib

from app.db.models import AsaasWebhookReceipt, Subscription


_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260824_180000_asaas_formal_isolation.sql"
)


def _sql() -> str:
    return " ".join(_MIGRATION.read_text(encoding="utf-8").lower().split())


def test_migration_reserves_owned_resources_and_never_adopts_legacy_rows() -> None:
    sql = _sql()

    assert "add column if not exists asaas_customer_external_reference" in sql
    assert "add column if not exists asaas_subscription_external_reference" in sql
    assert "like 'pastorai-%'" in sql
    assert "subscriptions_asaas_customer_id_uidx" in sql
    assert "subscriptions_asaas_subscription_id_uidx" in sql
    assert "subscriptions_asaas_customer_reference_uidx" in sql
    assert "subscriptions_asaas_subscription_reference_uidx" in sql
    assert "billing_payment_operations_stale_idx" in sql
    assert "billing_subscription_operations_stale_idx" in sql
    assert "where status in ('creating', 'reconciling')" in sql
    assert "raise exception 'asaas isolation preflight:" in sql
    assert "update subscriptions" not in sql


def test_webhook_receipt_is_unique_closed_and_indexed() -> None:
    sql = _sql()

    assert "create table if not exists asaas_webhook_receipts" in sql
    assert "event_id text not null unique" in sql
    assert "asaas_webhook_receipts_received_at_idx" in sql
    assert "enable row level security" in sql
    assert "service_role_bypass_only" in sql
    assert "using (false) with check (false)" in sql
    assert "revoke all privileges" in sql


def test_orm_exposes_the_same_ownership_and_receipt_fields() -> None:
    subscription_columns = set(Subscription.__table__.columns.keys())
    receipt_columns = set(AsaasWebhookReceipt.__table__.columns.keys())

    assert {
        "asaas_customer_external_reference",
        "asaas_subscription_external_reference",
    }.issubset(subscription_columns)
    assert receipt_columns == {
        "id",
        "event_id",
        "event_type",
        "resource_type",
        "resource_id",
        "received_at",
    }
