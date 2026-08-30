"""Disposable PostgreSQL 17 TLS proof for the DEV-only identity preflight."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import stat
from typing import Iterator

import psycopg2
from psycopg2 import extensions
import pytest

from scripts import preflight_migration_history_environment_identity as preflight


DATABASE_URL_ENV = "DEV_IDENTITY_PREFLIGHT_TEST_DATABASE_URL"
TLS_CA_CERT_PATH_ENV = "DEV_IDENTITY_PREFLIGHT_TEST_TLS_CA_CERT_PATH"
PROJECT_REF = "abcdefghijklmnopqrst"
HMAC_KEY = b"k" * 32
NONCE = b"n" * 32


def _close_descriptor(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


@contextmanager
def _private_pipe(raw: bytes) -> Iterator[int]:
    read_descriptor, write_descriptor = os.pipe()
    try:
        os.write(write_descriptor, raw)
    finally:
        os.close(write_descriptor)
    try:
        yield read_descriptor
    finally:
        _close_descriptor(read_descriptor)


def _authorization_record(
    *,
    runner_sha256: str,
    expected_project_ref_sha256: str,
    expected_database_name_sha256: str,
    tls_ca_certificate_sha256: str,
) -> bytes:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    values = {
        "authorization_contract": preflight.AUTHORIZATION_CONTRACT,
        "gate": preflight.GATE,
        "environment": preflight.ENVIRONMENT,
        "confirmation": preflight.CONFIRMATION,
        "executor": "OWNER-01_RANIEL",
        "reviewer": preflight.REVIEWER,
        "base_git_sha": preflight.SOURCE_BASE_GIT_SHA,
        "runner_sha256": runner_sha256,
        "preflight_sql_sha256": preflight.PREFLIGHT_SQL_SHA256,
        "tls_ca_certificate_sha256": tls_ca_certificate_sha256,
        "expected_project_ref_sha256": expected_project_ref_sha256,
        "expected_database_name_sha256": expected_database_name_sha256,
        "attempt_nonce_sha256": hashlib.sha256(NONCE).hexdigest(),
        "valid_from_utc": (now - timedelta(minutes=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "expires_at_utc": (now + timedelta(minutes=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "single_attempt": "true",
        "single_use_scope": "PROCESS_INVOCATION_ONLY",
        "prod_authorized": "false",
        "capture_authorized": "false",
        "materialization_authorized": "false",
        "operational_authorization": "false",
        "next_stage_authorized": "false",
    }
    return "".join(
        f"{field}={values[field]}\n" for field in preflight.AUTHORIZATION_FIELDS
    ).encode("ascii")


def _output_map(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        key, value = line.split("=", 1)
        assert key not in result
        result[key] = value
    return result


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


def test_dev_identity_preflight_full_main_uses_seven_fds_and_zero_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url = os.environ.get(DATABASE_URL_ENV)
    tls_ca_certificate_path_raw = os.environ.get(TLS_CA_CERT_PATH_ENV)
    if not database_url or not tls_ca_certificate_path_raw:
        pytest.skip(
            "dedicated disposable PostgreSQL 17 TLS URL and CA path are not configured"
        )
    tls_ca_certificate_path = Path(tls_ca_certificate_path_raw)
    tls_ca_certificate = tls_ca_certificate_path.read_bytes()
    tls_ca_info = tls_ca_certificate_path.lstat()
    assert stat.S_ISREG(tls_ca_info.st_mode)
    assert stat.S_IMODE(tls_ca_info.st_mode) == 0o600
    assert tls_ca_info.st_nlink == 1
    assert tls_ca_info.st_uid == os.geteuid()
    assert tls_ca_info.st_gid == os.getegid()

    for name in list(os.environ):
        upper = name.upper()
        if (
            upper.startswith(("PG", "SSL", "OPENSSL"))
            or upper in preflight.RELEVANT_DATABASE_ENV_NAMES
        ):
            monkeypatch.delenv(name, raising=False)

    expected_project_ref_sha256 = preflight._component_sha256(
        "PROJECT_REF", PROJECT_REF
    )
    expected_database_name_sha256 = preflight._component_sha256(
        "DATABASE_NAME", "postgres"
    )
    authorization_record = _authorization_record(
        runner_sha256=preflight._runner_sha256(),
        expected_project_ref_sha256=expected_project_ref_sha256,
        expected_database_name_sha256=expected_database_name_sha256,
        tls_ca_certificate_sha256=hashlib.sha256(tls_ca_certificate).hexdigest(),
    )
    private_inputs = (
        database_url.encode("utf-8"),
        authorization_record,
        expected_project_ref_sha256.encode("ascii"),
        expected_database_name_sha256.encode("ascii"),
        HMAC_KEY,
        NONCE,
    )
    descriptor_flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        descriptor_flags |= os.O_NOFOLLOW

    original_validate_dsn = preflight._validate_dsn

    def validate_loopback_target(
        dsn: str,
        **kwargs: object,
    ) -> preflight.Target:
        return original_validate_dsn(
            dsn,
            test_only_allow_loopback=preflight._TEST_ONLY_LOOPBACK_SENTINEL,
            **kwargs,
        )

    monkeypatch.setattr(preflight, "_validate_dsn", validate_loopback_target)
    monkeypatch.setattr(preflight, "_ATTEMPT_STATE", preflight.AttemptState())

    before = _catalog_snapshot(database_url, tls_ca_certificate_path)
    with ExitStack() as stack:
        descriptors = [
            stack.enter_context(_private_pipe(raw)) for raw in private_inputs
        ]
        tls_ca_certificate_fd = os.open(
            tls_ca_certificate_path,
            descriptor_flags,
        )
        stack.callback(_close_descriptor, tls_ca_certificate_fd)
        descriptors.append(tls_ca_certificate_fd)
        assert len(descriptors) == 7
        assert len(set(descriptors)) == 7
        assert all(
            stat.S_ISFIFO(os.fstat(descriptor).st_mode)
            and stat.S_IMODE(os.fstat(descriptor).st_mode) == 0o600
            and os.fstat(descriptor).st_nlink == 1
            for descriptor in descriptors[:-1]
        )
        tls_ca_fd_info = os.fstat(tls_ca_certificate_fd)
        assert stat.S_ISREG(tls_ca_fd_info.st_mode)
        assert stat.S_IMODE(tls_ca_fd_info.st_mode) == 0o600
        assert tls_ca_fd_info.st_nlink == 1
        assert (
            fcntl.fcntl(tls_ca_certificate_fd, fcntl.F_GETFL) & os.O_ACCMODE
        ) == os.O_RDONLY

        argv: list[str] = []
        for flag, descriptor in zip(
            (
                "--database-url-fd",
                "--authorization-record-fd",
                "--expected-project-ref-sha256-fd",
                "--expected-database-name-sha256-fd",
                "--hmac-key-fd",
                "--nonce-fd",
                "--tls-ca-cert-fd",
            ),
            descriptors,
            strict=True,
        ):
            argv.extend((flag, str(descriptor)))
        argv.extend(("--confirmation", preflight.CONFIRMATION))
        result = preflight.main(argv)
        for descriptor in descriptors:
            with pytest.raises(OSError):
                os.fstat(descriptor)

    after = _catalog_snapshot(database_url, tls_ca_certificate_path)
    output = _output_map(capsys.readouterr().out)
    assert result == 0
    assert before == after
    assert "PREFLIGHT_FAILURE_PHASE" not in output
    assert output["RESULT"] == "PREFLIGHT_IDENTITY_OBSERVED_NOT_ATTESTED"
    assert output["TLS_MODE"] == "VERIFY_FULL_EXPLICIT_CA"
    assert output["POSTGRES_MAJOR_17"] == "true"
    assert output["CURRENT_USER_MATCHES_SESSION_USER"] == "true"
    assert output["FULL_VISIBILITY"] == "true"
    assert output["ISOLATION_LEVEL"] == "REPEATABLE_READ"
    assert output["READ_ONLY"] == "true"
    assert output["ROLLBACK_CONFIRMED"] == "true"
    assert output["CONNECTION_CLOSED"] == "true"
    assert output["OPERATIONAL_AUTHORIZATION"] == "false"
    assert output["NEXT_STAGE_AUTHORIZED"] == "false"
    assert output["CAPTURE_EXECUTED"] == "false"
    assert output["MATERIALIZATION_EXECUTED"] == "false"
    assert output["PROD_ACCESSED"] == "false"
