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
    ("whatsapp_reminder_preferences", "state"),
    ("agenda_reminder_subscriptions", "id"),
    ("notification_outbox", "id"),
    ("consolidacoes", "origin_decision_id"),
    ("consolidacoes", "assignment_revision"),
    ("work_queue_items", "consolidacao_id"),
    ("notification_outbox", "consolidacao_id"),
    ("notification_outbox", "work_queue_item_id"),
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
