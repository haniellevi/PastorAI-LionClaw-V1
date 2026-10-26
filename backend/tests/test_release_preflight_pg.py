"""Read-only release checks against an isolated, synthetic PostgreSQL database."""

from __future__ import annotations

import io
import os
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from sqlalchemy.engine import make_url

from scripts import migrate, release_preflight
from tests.conftest_rls import assert_disposable_database

pytestmark = pytest.mark.rls_integration


@pytest.fixture(scope="module")
def rls_database_url() -> str:
    raw_url = os.environ.get("RLS_TEST_DATABASE_URL", "").strip()
    if not raw_url:
        raise RuntimeError("RLS_TEST_DATABASE_URL obrigatório para este teste PG")
    assert_disposable_database(raw_url)
    base_url = make_url(raw_url)
    if base_url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("o teste PG aceita somente PostgreSQL local sintético")

    database_name = f"release_preflight_test_{uuid4().hex}"
    admin_url = base_url.set(
        drivername="postgresql", database="postgres"
    ).render_as_string(hide_password=False)
    test_url = base_url.set(
        drivername="postgresql", database=database_name
    ).render_as_string(hide_password=False)

    admin = psycopg2.connect(admin_url)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
            )
    finally:
        admin.close()

    try:
        connection = psycopg2.connect(test_url)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "CREATE TABLE public.schema_migrations (name text PRIMARY KEY)"
                )
                cursor.execute(
                    """
                    CREATE TABLE public.celulas (
                      igreja_id uuid NOT NULL,
                      id uuid NOT NULL,
                      PRIMARY KEY (igreja_id, id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE public.celula_solicitacao (
                      id uuid PRIMARY KEY,
                      igreja_id uuid NOT NULL,
                      celula_id uuid NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE public.app_users (
                      id uuid PRIMARY KEY,
                      igreja_id uuid,
                      pessoa_id uuid
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE public.responsabilidades_setor (
                      id uuid PRIMARY KEY,
                      igreja_id uuid NOT NULL
                    )
                    """
                )
                cursor.execute("CREATE SCHEMA other")
                cursor.execute(
                    "CREATE TABLE other.responsabilidades_setor (id uuid PRIMARY KEY)"
                )
                private_tables = (
                    "private_deletion_event_fences",
                    "private_deletion_receipts",
                    "private_deletion_sends",
                    "private_deletion_tasks",
                    "private_deletion_uploads",
                )
                for table_name in private_tables:
                    cursor.execute(
                        sql.SQL("CREATE TABLE public.{} (id uuid PRIMARY KEY)").format(
                            sql.Identifier(table_name)
                        )
                    )
                cursor.execute(
                    "INSERT INTO public.schema_migrations (name) VALUES (%s), (%s), (%s)",
                    (
                        "20261018_090000_exclusao_privada.sql",
                        "20261021_100000_responsabilidades_setor.sql",
                        "unknown_synthetic_migration.sql",
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO public.celulas (igreja_id, id) VALUES
                      ('40000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-000000000001')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO public.celula_solicitacao (id, igreja_id, celula_id) VALUES
                      ('60000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-000000000001'),
                      ('60000000-0000-0000-0000-000000000002', '40000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-000000000099')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO public.app_users (id, igreja_id, pessoa_id) VALUES
                      ('70000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000001', '80000000-0000-0000-0000-000000000001'),
                      ('70000000-0000-0000-0000-000000000002', '40000000-0000-0000-0000-000000000001', '80000000-0000-0000-0000-000000000001'),
                      ('70000000-0000-0000-0000-000000000003', NULL, '80000000-0000-0000-0000-000000000002'),
                      ('70000000-0000-0000-0000-000000000004', NULL, '80000000-0000-0000-0000-000000000002')
                    """
                )
            connection.commit()
        finally:
            connection.close()
        yield test_url
    finally:
        admin = psycopg2.connect(admin_url)
        admin.autocommit = True
        try:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        finally:
            admin.close()


def test_release_preflight_reports_synthetic_findings_and_refuses_writes(
    rls_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = psycopg2.connect(rls_database_url)
    try:
        report = release_preflight.inspect_connection(connection)
        names = [row.name for row in report.migrations]
        assert names == migrate.migration_files()
        assert report.unknown_applied_count == 1
        assert report.has_findings
        assert report.expected_backup_tables == (
            "private_deletion_event_fences",
            "private_deletion_receipts",
            "private_deletion_sends",
            "private_deletion_tasks",
            "private_deletion_uploads",
            "responsabilidades_setor",
        )
        assert report.missing_backup_tables == ()
        assert len(report.fk_findings) == 1
        assert str(report.fk_findings[0].request_id) == "60000000-0000-0000-0000-000000000002"
        assert len(report.duplicate_findings) == 2
        assert report.duplicate_findings[0].rows == 2
        null_church_duplicate = next(
            finding for finding in report.duplicate_findings if finding.church_id is None
        )
        assert str(null_church_duplicate.person_id) == (
            "80000000-0000-0000-0000-000000000002"
        )
        assert null_church_duplicate.rows == 2
        # Private definer migrations are pending here: nothing is examined or
        # attested, and absence alone is not a finding.
        assert report.definer_examined == ()
        assert report.definer_unverified == tuple(
            signature for signature, _ in release_preflight.PRIVATE_DEFINER_CONTRACTS
        )
        assert report.definer_findings == ()

        output = io.StringIO()
        release_preflight.render_report(report, stream=output)
        rendered = output.getvalue()
        assert "PENDENTE 20261016_180000_prayer_requests.sql" in rendered
        assert "APLICADA 20261021_100000_responsabilidades_setor.sql" in rendered
        assert "celula_solicitacao_fk_violations=1" in rendered
        assert "app_users_duplicate_groups=2" in rendered
        assert (
            "igreja_id=NULL pessoa_id=80000000-0000-0000-0000-000000000002 linhas=2"
            in rendered
        )
        assert "backup_public_tables: esperadas=6 ausentes=0" in rendered
        assert (
            "private_definer_contracts: examinados=0 nao_verificados=5 "
            "dono_sem_bypass=0" in rendered
        )
        assert (
            "private_definer_nao_verificado=public.private_send_release(uuid,uuid)"
            in rendered
        )
        assert "responsabilidades_setor" not in report.missing_backup_tables
        assert "unknown_synthetic_migration.sql" not in rendered
        assert "synthetic-only" not in rendered

        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('transaction_read_only')")
            assert cursor.fetchone()[0] == "on"
            with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
                cursor.execute(
                    "INSERT INTO public.schema_migrations (name) VALUES ('write_attempt')"
                )
    finally:
        connection.rollback()
        connection.close()

    monkeypatch.setenv(release_preflight.DATABASE_URL_ENV, rls_database_url)
    assert release_preflight.main() == 1
    cli_output = capsys.readouterr().out
    assert "RESULTADO=ACHADOS" in cli_output
    assert "60000000-0000-0000-0000-000000000002" in cli_output
    assert (
        "igreja_id=NULL pessoa_id=80000000-0000-0000-0000-000000000002 linhas=2"
        in cli_output
    )
    assert "unknown_synthetic_migration.sql" not in cli_output

    admin = psycopg2.connect(rls_database_url)
    try:
        with admin.cursor() as cursor:
            cursor.execute("DROP TABLE public.private_deletion_receipts")
        admin.commit()
    finally:
        admin.close()

    missing_connection = psycopg2.connect(rls_database_url)
    try:
        missing_report = release_preflight.inspect_connection(missing_connection)
    finally:
        missing_connection.rollback()
        missing_connection.close()
    assert missing_report.missing_backup_tables == ("private_deletion_receipts",)
    assert missing_report.has_findings
