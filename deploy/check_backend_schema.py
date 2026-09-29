"""Fail closed before starting a backend that requires V2b/V3 schema."""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine


REQUIRED_COLUMNS = (
    ("agenda_alert_recipients", "pessoa_id"),
    ("events", "notification_outbox_fenced_at"),
    ("events", "notification_outbox_fence_reason"),
    ("igrejas", "notification_outbox_cutover_at"),
    ("whatsapp_reminder_preferences", "id"),
    ("whatsapp_reminder_preferences", "igreja_id"),
    ("whatsapp_reminder_preferences", "pessoa_id"),
    ("whatsapp_reminder_preferences", "reminder_kind"),
    ("whatsapp_reminder_preferences", "state"),
    ("whatsapp_reminder_preferences", "term_version"),
    ("whatsapp_reminder_preferences", "accepted_at"),
    ("whatsapp_reminder_preferences", "changed_at"),
    ("agenda_reminder_subscriptions", "id"),
    ("agenda_reminder_subscriptions", "igreja_id"),
    ("agenda_reminder_subscriptions", "pessoa_id"),
    ("agenda_reminder_subscriptions", "event_id"),
    ("agenda_reminder_subscriptions", "occurrence_at"),
    ("agenda_reminder_subscriptions", "proposal_id"),
    ("agenda_reminder_subscriptions", "state"),
    ("agenda_reminder_subscriptions", "term_version"),
    ("agenda_reminder_subscriptions", "confirmed_at"),
    ("agenda_reminder_subscriptions", "updated_at"),
    ("notification_outbox", "id"),
    ("notification_outbox", "igreja_id"),
    ("notification_outbox", "pessoa_id"),
    ("notification_outbox", "agenda_alert_recipient_id"),
    ("notification_outbox", "event_id"),
    ("notification_outbox", "reuniao_id"),
    ("notification_outbox", "agenda_subscription_id"),
    ("notification_outbox", "origin_kind"),
    ("notification_outbox", "origin_id"),
    ("notification_outbox", "occurrence_at"),
    ("notification_outbox", "origin_fingerprint"),
    ("notification_outbox", "purpose"),
    ("notification_outbox", "state"),
    ("notification_outbox", "due_at"),
    ("notification_outbox", "delivery_reservation_day"),
    ("notification_outbox", "claim_token"),
    ("notification_outbox", "claimed_until"),
    ("notification_outbox", "claimed_by"),
    ("notification_outbox", "attempts"),
    ("notification_outbox", "transport_started_at"),
    ("notification_outbox", "sent_at"),
    ("notification_outbox", "terminal_reason"),
    ("notification_outbox", "created_at"),
    ("notification_outbox", "updated_at"),
    ("consolidacoes", "origin_decision_id"),
    ("consolidacoes", "assignment_revision"),
    ("work_queue_items", "consolidacao_id"),
    ("notification_outbox", "consolidacao_id"),
    ("notification_outbox", "work_queue_item_id"),
    ("consolidation_whatsapp_activation", "igreja_id"),
    ("consolidation_whatsapp_activation", "activated_at"),
    ("consolidation_whatsapp_activation", "gate_open"),
)


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("schema preflight failed: DATABASE_URL unavailable", file=sys.stderr)
        return 1

    engine = None
    try:
        engine = create_engine(
            database_url, connect_args={"connect_timeout": 5}, future=True
        )
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '5s'")
            missing = connection.exec_driver_sql(
                """
                WITH required(table_name, column_name) AS (
                  VALUES """
                + ", ".join("(%s, %s)" for _ in REQUIRED_COLUMNS)
                + """
                )
                SELECT required.table_name, required.column_name
                FROM required
                WHERE NOT EXISTS (
                  SELECT 1 FROM pg_catalog.pg_attribute attribute
                  WHERE attribute.attrelid = to_regclass('public.' || required.table_name)
                    AND attribute.attname = required.column_name
                    AND attribute.attnum > 0
                    AND NOT attribute.attisdropped
                )
                ORDER BY required.table_name, required.column_name
                """,
                tuple(part for pair in REQUIRED_COLUMNS for part in pair),
            ).all()
            activation_safe = connection.exec_driver_sql(
                """
                SELECT relrowsecurity AND relforcerowsecurity
                   AND has_table_privilege('authenticated', oid, 'SELECT')
                   AND has_table_privilege('authenticated', oid, 'INSERT')
                   AND has_table_privilege('authenticated', oid, 'UPDATE')
                   AND NOT has_table_privilege('authenticated', oid, 'DELETE')
                FROM pg_catalog.pg_class
                WHERE oid = to_regclass('public.consolidation_whatsapp_activation')
                """
            ).scalar_one_or_none()
            connection.rollback()
    except Exception as exc:
        print(
            f"schema preflight failed: database check error ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()

    if missing:
        for table_name, column_name in missing:
            print(
                f"schema preflight failed: missing public.{table_name}.{column_name}",
                file=sys.stderr,
            )
        return 1
    if activation_safe is not True:
        print("schema preflight failed: V3 activation RLS/ACL contract", file=sys.stderr)
        return 1
    print("schema preflight OK: V2b/V3 columns and V3 activation RLS/ACL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
