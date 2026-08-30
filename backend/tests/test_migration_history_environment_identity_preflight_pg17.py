"""Disposable PostgreSQL 17 TLS proof for the DEV-only identity preflight."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import stat

import psycopg2
from psycopg2 import extensions
import pytest

from scripts import preflight_migration_history_environment_identity as preflight


DATABASE_URL_ENV = "DEV_IDENTITY_PREFLIGHT_TEST_DATABASE_URL"
TLS_CA_CERT_PATH_ENV = "DEV_IDENTITY_PREFLIGHT_TEST_TLS_CA_CERT_PATH"
PROJECT_REF = "abcdefghijklmnopqrst"


def _catalog_snapshot(
    database_url: str,
    tls_ca_certificate_path: Path,
) -> tuple[object, ...]:
    connection = psycopg2.connect(
        database_url,
        connect_timeout=5,
        sslmode="verify-full",
        sslrootcert=str(tls_ca_certificate_path),
    )
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select "
                "(select pg_catalog.count(*) from pg_catalog.pg_namespace "
                "where nspname not like 'pg_%' and nspname <> 'information_schema'), "
                "(select pg_catalog.count(*) from pg_catalog.pg_class c "
                "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
                "where n.nspname not like 'pg_%' "
                "and n.nspname <> 'information_schema'), "
                "pg_catalog.to_regclass('public.schema_migrations') is null, "
                "pg_catalog.to_regnamespace('supabase_migrations') is null"
            )
            row = cursor.fetchone()
        assert row is not None
        return tuple(row)
    finally:
        connection.close()


def test_dev_identity_preflight_is_pg17_tls_read_only_and_zero_write() -> None:
    database_url = os.environ.get(DATABASE_URL_ENV)
    tls_ca_certificate_path_raw = os.environ.get(TLS_CA_CERT_PATH_ENV)
    if not database_url or not tls_ca_certificate_path_raw:
        pytest.skip(
            "dedicated disposable PostgreSQL 17 TLS URL and CA path are not configured"
        )
    tls_ca_certificate_path = Path(tls_ca_certificate_path_raw)
    info = tls_ca_certificate_path.lstat()
    assert stat.S_ISREG(info.st_mode)
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert info.st_nlink == 1
    assert info.st_uid == os.geteuid()
    assert info.st_gid == os.getegid()
    assert 0 < info.st_size <= preflight.MAX_TLS_CA_CERTIFICATE_BYTES
    assert getattr(psycopg2, "__libpq_version__", 0) >= 170_000
    assert extensions.libpq_version() >= 170_000
    expected_project_ref_sha256 = preflight._component_sha256(
        "PROJECT_REF", PROJECT_REF
    )
    expected_database_name_sha256 = preflight._component_sha256(
        "DATABASE_NAME", "postgres"
    )
    target = preflight._validate_dsn(
        database_url,
        expected_project_ref_sha256=expected_project_ref_sha256,
        expected_database_name_sha256=expected_database_name_sha256,
        test_only_allow_loopback=preflight._TEST_ONLY_LOOPBACK_SENTINEL,
    )
    descriptor_flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        descriptor_flags |= os.O_NOFOLLOW
    tls_ca_certificate_fd = os.open(
        tls_ca_certificate_path,
        descriptor_flags,
    )
    try:
        access_mode = (
            fcntl.fcntl(tls_ca_certificate_fd, fcntl.F_GETFL) & os.O_ACCMODE
        )
        assert access_mode == os.O_RDONLY
        witness = preflight._witness_tls_ca_certificate_fd(
            tls_ca_certificate_fd
        )
        before = _catalog_snapshot(database_url, tls_ca_certificate_path)
        cleanup = preflight.CleanupState()
        system_identifier, database_name = preflight._run_database_preflight(
            dsn=database_url,
            target=target,
            sql_contract=preflight._load_sql_contract(),
            tls_ca_certificate_fd=tls_ca_certificate_fd,
            cleanup=cleanup,
        )
        preflight._revalidate_tls_ca_certificate_fd(witness)
        after = _catalog_snapshot(database_url, tls_ca_certificate_path)
    finally:
        os.close(tls_ca_certificate_fd)
    assert before == after
    assert database_name == "postgres"
    assert system_identifier.isdecimal()
    assert cleanup.connection_opened is True
    assert cleanup.rollback_attempted is True
    assert cleanup.rollback_confirmed is True
    assert cleanup.connection_closed is True

    connection = psycopg2.connect(
        database_url,
        connect_timeout=5,
        sslmode="verify-full",
        sslrootcert=str(tls_ca_certificate_path),
    )
    connection.autocommit = True
    try:
        assert connection.server_version // 10_000 == 17
        assert connection.get_transaction_status() == extensions.TRANSACTION_STATUS_IDLE
        with connection.cursor() as cursor:
            cursor.execute("show ssl")
            assert cursor.fetchone() == ("on",)
            cursor.execute("select pg_catalog.txid_current_if_assigned() is null")
            assert cursor.fetchone() == (True,)
    finally:
        connection.close()
