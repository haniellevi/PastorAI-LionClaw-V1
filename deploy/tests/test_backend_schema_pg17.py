"""Exercise the release gate against an isolated PostgreSQL 17 database."""

from __future__ import annotations

import os
from pathlib import Path
import runpy
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

CHECKER = Path(__file__).resolve().parents[1] / "backend-release.sh"
REQUIRED_COLUMNS = runpy.run_path(
    str(CHECKER.parent / "check_backend_schema.py")
)["REQUIRED_COLUMNS"]


def test_missing_v2b_and_v3_columns_abort_before_deploy() -> None:
    source = make_url(os.environ["BACKEND_RELEASE_TEST_DATABASE_URL"])
    if source.host not in ("127.0.0.1", "localhost") or source.database != "rls_disposable":
        raise AssertionError("PG17 release test requires the disposable CI database")

    database_name = f"backend_release_{uuid.uuid4().hex[:12]}"
    admin = create_engine(source, isolation_level="AUTOCOMMIT")
    target_url = source.set(database=database_name)
    try:
        with admin.connect() as connection:
            connection.execute(
                text(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
                    "'authenticated') THEN CREATE ROLE authenticated; END IF; END $$"
                )
            )
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        target = create_engine(target_url)
        try:
            columns_by_table: dict[str, list[str]] = {}
            for table_name, column_name in REQUIRED_COLUMNS:
                columns_by_table.setdefault(table_name, []).append(column_name)
            with target.begin() as connection:
                for table_name, columns in columns_by_table.items():
                    definitions = ", ".join(f'"{column}" text' for column in columns)
                    connection.execute(text(f'CREATE TABLE public."{table_name}" ({definitions})'))
                connection.execute(
                    text(
                        "ALTER TABLE public.consolidation_whatsapp_activation "
                        "ENABLE ROW LEVEL SECURITY"
                    )
                )
                connection.execute(
                    text(
                        "ALTER TABLE public.consolidation_whatsapp_activation "
                        "FORCE ROW LEVEL SECURITY"
                    )
                )
                connection.execute(
                    text(
                        "GRANT SELECT, INSERT, UPDATE ON "
                        "public.consolidation_whatsapp_activation TO authenticated"
                    )
                )

            def dry_run() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["bash", str(CHECKER), "--dry-run"],
                    env={
                        **os.environ,
                        "DATABASE_URL": target_url.render_as_string(hide_password=False),
                        "BACKEND_RELEASE_PYTHON": sys.executable,
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )

            complete = dry_run()
            assert complete.returncode == 0, complete.stderr
            assert "dry-run OK" in complete.stdout

            for table_name, column_name in (
                ("igrejas", "notification_outbox_cutover_at"),
                ("consolidacoes", "assignment_revision"),
            ):
                with target.begin() as connection:
                    connection.execute(
                        text(f'ALTER TABLE public."{table_name}" DROP COLUMN "{column_name}"')
                    )
                missing = dry_run()
                assert missing.returncode != 0
                assert f"missing public.{table_name}.{column_name}" in missing.stderr
                assert "dry-run OK" not in missing.stdout
                with target.begin() as connection:
                    connection.execute(
                        text(f'ALTER TABLE public."{table_name}" ADD COLUMN "{column_name}" text')
                    )

            with target.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE public.consolidation_whatsapp_activation "
                        "NO FORCE ROW LEVEL SECURITY"
                    )
                )
            unsafe_rls = dry_run()
            assert unsafe_rls.returncode != 0
            assert "V3 activation RLS/ACL contract" in unsafe_rls.stderr

            bad_connection = subprocess.run(
                ["bash", str(CHECKER), "--dry-run"],
                env={
                    **os.environ,
                    "DATABASE_URL": target_url.set(port=1).render_as_string(
                        hide_password=False
                    ),
                    "BACKEND_RELEASE_PYTHON": sys.executable,
                },
                capture_output=True,
                text=True,
                check=False,
            )
            assert bad_connection.returncode != 0
            assert "database check error" in bad_connection.stderr
        finally:
            target.dispose()
    finally:
        with admin.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin.dispose()
