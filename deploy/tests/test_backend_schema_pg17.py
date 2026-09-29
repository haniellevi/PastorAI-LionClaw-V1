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
MIGRATIONS = runpy.run_path(
    str(CHECKER.parent.parent / "backend/scripts/migrate.py")
)["migration_files"](CHECKER.parent.parent / "backend/migrations")
TENANT_PREDICATE = """
igreja_id = public.current_igreja_id()
and nullif(coalesce(
  nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
  pg_catalog.current_setting('request.jwt.claim.sub', true)
), '') is null
"""


def test_missing_v2b_and_v3_columns_abort_before_deploy() -> None:
    # Independent sentinels catch a removed REQUIRED_COLUMNS entry.
    assert ("igrejas", "notification_outbox_cutover_at") in REQUIRED_COLUMNS
    assert ("consolidacoes", "assignment_revision") in REQUIRED_COLUMNS
    assert ("notification_outbox", "claim_token") in REQUIRED_COLUMNS
    assert "20260927_120000_church_cell_public_data.sql" in MIGRATIONS
    assert "20260927_170000_whatsapp_privilege_actions.sql" in MIGRATIONS
    assert len(MIGRATIONS) == 81
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
                connection.execute(
                    text("CREATE TABLE public.schema_migrations (name text PRIMARY KEY)")
                )
                connection.execute(
                    text("INSERT INTO public.schema_migrations (name) VALUES (:name)"),
                    [{"name": name} for name in MIGRATIONS],
                )
                for table_name, columns in columns_by_table.items():
                    definitions = ", ".join(
                        f'"{column}" '
                        + (
                            "uuid"
                            if table_name == "consolidation_whatsapp_activation"
                            and column == "igreja_id"
                            else "text"
                        )
                        for column in columns
                    )
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
                connection.execute(
                    text(
                        "CREATE FUNCTION public.current_igreja_id() RETURNS uuid "
                        "LANGUAGE sql STABLE AS $$ SELECT null::uuid $$"
                    )
                )
                for name, command in (
                    ("select", "SELECT"),
                    ("insert", "INSERT"),
                    ("update", "UPDATE"),
                ):
                    predicate = (
                        f"WITH CHECK ({TENANT_PREDICATE})"
                        if name == "insert"
                        else f"USING ({TENANT_PREDICATE})"
                    )
                    if name == "update":
                        predicate += f" WITH CHECK ({TENANT_PREDICATE})"
                    connection.execute(
                        text(
                            "CREATE POLICY consolidation_whatsapp_activation_worker_"
                            f"{name} ON public.consolidation_whatsapp_activation "
                            f"FOR {command} TO authenticated {predicate}"
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
            assert "database identity:" in complete.stdout
            assert database_name in complete.stdout
            assert "127.0.0.1" in complete.stdout

            with target.begin() as connection:
                connection.execute(
                    text("DELETE FROM public.schema_migrations WHERE name = :name"),
                    {"name": "20260927_120000_church_cell_public_data.sql"},
                )
            missing_migration = dry_run()
            assert missing_migration.returncode != 0
            assert (
                "migration not applied: 20260927_120000_church_cell_public_data.sql"
                in missing_migration.stderr
            )
            with target.begin() as connection:
                connection.execute(
                    text("INSERT INTO public.schema_migrations (name) VALUES (:name)"),
                    {"name": "20260927_120000_church_cell_public_data.sql"},
                )

            with target.begin() as connection:
                connection.execute(
                    text("INSERT INTO public.schema_migrations (name) VALUES (:name)"),
                    {"name": "20990101_000000_future_schema.sql"},
                )
            future_schema = dry_run()
            assert future_schema.returncode != 0
            assert (
                "database migration absent from candidate: "
                "20990101_000000_future_schema.sql"
            ) in future_schema.stderr
            with target.begin() as connection:
                connection.execute(
                    text("DELETE FROM public.schema_migrations WHERE name = :name"),
                    {"name": "20990101_000000_future_schema.sql"},
                )

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
            with target.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE public.consolidation_whatsapp_activation "
                        "FORCE ROW LEVEL SECURITY"
                    )
                )
                connection.execute(
                    text(
                        "DROP POLICY consolidation_whatsapp_activation_worker_select "
                        "ON public.consolidation_whatsapp_activation"
                    )
                )
                connection.execute(
                    text(
                        "CREATE POLICY consolidation_whatsapp_activation_worker_select "
                        "ON public.consolidation_whatsapp_activation "
                        "FOR SELECT TO authenticated USING (true)"
                    )
                )
            unsafe_policy = dry_run()
            assert unsafe_policy.returncode != 0
            assert "V3 activation policy contract" in unsafe_policy.stderr

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
