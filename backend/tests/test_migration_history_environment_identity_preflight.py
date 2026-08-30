"""Adversarial offline proofs for the nominal DEV identity preflight runner."""

from __future__ import annotations

import ast
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import re
import socket
import stat
import tempfile
from typing import Any, Iterator

import pytest
from psycopg2 import extensions

from scripts import preflight_migration_history_environment_identity as preflight


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "preflight_migration_history_environment_identity.py"
)
SQL_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-environment-identity-preflight-v1.sql"
)
PROJECT_REF = "abcdefghijklmnopqrst"
OTHER_PROJECT_REF = "bcdefghijklmnopqrstu"
DATABASE_NAME = "postgres"
SYSTEM_IDENTIFIER = "1234567890123456789"
KEY = b"k" * 32
NONCE = b"n" * 32
NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
TLS_CA_CERTIFICATE = (
    b"-----BEGIN CERTIFICATE-----\n"
    b"VEVTVF9PTkxZX1BBU1RPUkFJX0NB\n"
    b"-----END CERTIFICATE-----\n"
)
DIRECT_DSN = (
    f"postgresql://postgres:private-password@db.{PROJECT_REF}.supabase.co:5432/"
    f"{DATABASE_NAME}"
)
POOLER_DSN = (
    f"postgresql://postgres.{PROJECT_REF}:private-password@"
    f"aws-0-sa-east-1.pooler.supabase.com:6543/{DATABASE_NAME}"
)


@contextmanager
def _descriptor(raw: bytes) -> Iterator[int]:
    read_descriptor, write_descriptor = os.pipe()
    try:
        os.write(write_descriptor, raw)
    finally:
        os.close(write_descriptor)
    try:
        yield read_descriptor
    finally:
        try:
            os.close(read_descriptor)
        except OSError:
            pass


def _clean_database_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.upper().startswith("PG") or name.upper() in preflight.RELEVANT_DATABASE_ENV_NAMES:
            monkeypatch.delenv(name, raising=False)


def _project_hash(project_ref: str = PROJECT_REF) -> str:
    return preflight._component_sha256("PROJECT_REF", project_ref)


def _database_hash(database_name: str = DATABASE_NAME) -> str:
    return preflight._component_sha256("DATABASE_NAME", database_name)


def _tls_ca_hash(raw: bytes = TLS_CA_CERTIFICATE) -> str:
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def _tls_ca_descriptor(
    raw: bytes = TLS_CA_CERTIFICATE,
) -> Iterator[tuple[int, Path]]:
    with tempfile.TemporaryDirectory(prefix="pastorai-test-ca-") as directory:
        path = Path(directory) / "ca.crt"
        path.write_bytes(raw)
        path.chmod(0o600)
        descriptor = os.open(path, os.O_RDONLY)
        try:
            yield descriptor, path
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _authorization_values(
    *,
    runner_sha256: str,
    expected_project_ref_sha256: str,
    expected_database_name_sha256: str,
    nonce: bytes = NONCE,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
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
        "tls_ca_certificate_sha256": _tls_ca_hash(),
        "expected_project_ref_sha256": expected_project_ref_sha256,
        "expected_database_name_sha256": expected_database_name_sha256,
        "attempt_nonce_sha256": hashlib.sha256(nonce).hexdigest(),
        "valid_from_utc": "2026-08-30T11:59:00Z",
        "expires_at_utc": "2026-08-30T12:10:00Z",
        "single_attempt": "true",
        "single_use_scope": "PROCESS_INVOCATION_ONLY",
        "prod_authorized": "false",
        "capture_authorized": "false",
        "materialization_authorized": "false",
        "operational_authorization": "false",
        "next_stage_authorized": "false",
    }
    if overrides:
        values.update(overrides)
    return values


def _authorization_bytes(values: dict[str, str]) -> bytes:
    return (
        "".join(f"{field}={values[field]}\n" for field in preflight.AUTHORIZATION_FIELDS)
    ).encode("ascii")


def _identity(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "identity_contract": preflight.IDENTITY_CONTRACT,
        "system_identifier": SYSTEM_IDENTIFIER,
        "database_name": DATABASE_NAME,
        "server_version_num": 170_006,
        "current_user_matches_session_user": True,
        "tls": True,
        "isolation_level": "repeatable read",
        "read_only": "on",
        "full_visibility": True,
    }
    value.update(overrides)
    return value


class SecretDatabaseFailure(RuntimeError):
    pass


class _FakeCursor:
    def __init__(
        self,
        connection: "_FakeConnection",
        *,
        identity: Any,
        fail_execute_at: int | None = None,
        fail_fetch_at: int | None = None,
        transport_failure: bool = False,
        rollback_failures: int = 0,
        close_failure: bool = False,
    ) -> None:
        self.connection = connection
        self.identity = identity
        self.fail_execute_at = fail_execute_at
        self.fail_fetch_at = fail_fetch_at
        self.transport_failure = transport_failure
        self.rollback_failures = rollback_failures
        self.close_failure = close_failure
        self.executed: list[str] = []
        self.rows: list[Any] = []
        self.fetch_calls = 0
        self.rollback_execute_calls = 0
        self.close_calls = 0

    def execute(self, statement: str) -> None:
        index = len(self.executed)
        self.executed.append(statement)
        if self.fail_execute_at == index:
            if self.transport_failure:
                self.connection.closed = 1
            raise SecretDatabaseFailure(
                "SQLERRM private-password abcdefghijklmnopqrst private_database "
                "1234567890123456789"
            )
        if self.connection.closed:
            raise SecretDatabaseFailure("SQLERRM transport connection closed")
        if statement == preflight.ROLLBACK_SQL.decode("ascii"):
            self.rollback_execute_calls += 1
            if self.rollback_failures:
                self.rollback_failures -= 1
                raise SecretDatabaseFailure("SQLERRM rollback private marker")
            self.connection.transaction_status = extensions.TRANSACTION_STATUS_IDLE
            self.rows = []
        elif statement.startswith("begin transaction"):
            self.connection.transaction_status = extensions.TRANSACTION_STATUS_INTRANS
            self.rows = []
        elif "json_build_object" in statement:
            self.rows = [(self.identity,), None]
        else:
            self.rows = [("configured",), None]

    def fetchone(self) -> Any:
        self.fetch_calls += 1
        if self.fail_fetch_at == self.fetch_calls:
            raise SecretDatabaseFailure("SQLERRM fetch private marker")
        return self.rows.pop(0) if self.rows else None

    def close(self) -> None:
        self.close_calls += 1
        if self.close_failure:
            raise SecretDatabaseFailure("SQLERRM cursor close private marker")


class _FakeConnection:
    def __init__(
        self,
        *,
        identity: Any | None = None,
        server_version: int = 170_006,
        fail_execute_at: int | None = None,
        fail_fetch_at: int | None = None,
        transport_failure: bool = False,
        rollback_failures: int = 0,
        connection_rollback_failure: bool = False,
        cursor_close_failure: bool = False,
        connection_close_failure: bool = False,
        idle_after_rollback: bool = True,
    ) -> None:
        self.server_version = server_version
        self.autocommit = False
        self.closed = 0
        self.close_calls = 0
        self.cursor_calls = 0
        self.rollback_calls = 0
        self.connection_rollback_failure = connection_rollback_failure
        self.connection_close_failure = connection_close_failure
        self.idle_after_rollback = idle_after_rollback
        self.transaction_status = extensions.TRANSACTION_STATUS_IDLE
        self.fake_cursor = _FakeCursor(
            self,
            identity=_identity() if identity is None else identity,
            fail_execute_at=fail_execute_at,
            fail_fetch_at=fail_fetch_at,
            transport_failure=transport_failure,
            rollback_failures=rollback_failures,
            close_failure=cursor_close_failure,
        )

    def cursor(self) -> _FakeCursor:
        self.cursor_calls += 1
        return self.fake_cursor

    def get_transaction_status(self) -> int:
        if (
            not self.idle_after_rollback
            and self.fake_cursor.rollback_execute_calls
        ):
            return extensions.TRANSACTION_STATUS_INTRANS
        return self.transaction_status

    def rollback(self) -> None:
        self.rollback_calls += 1
        if self.connection_rollback_failure or self.closed:
            raise SecretDatabaseFailure("SQLERRM connection rollback private marker")
        self.transaction_status = extensions.TRANSACTION_STATUS_IDLE

    def close(self) -> None:
        self.close_calls += 1
        if self.connection_close_failure:
            raise SecretDatabaseFailure("SQLERRM close private marker")
        self.closed = 1


class _FakeConnect:
    def __init__(
        self,
        connection: _FakeConnection | None = None,
        *,
        failure: Exception | None = None,
        mutate_tls_ca_on_connect: bytes | None = None,
    ) -> None:
        self.connection = connection or _FakeConnection()
        self.failure = failure
        self.mutate_tls_ca_on_connect = mutate_tls_ca_on_connect
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.tls_ca_bytes: bytes | None = None
        self.tls_ca_fd_was_open = False

    def __call__(self, *args: Any, **kwargs: Any) -> _FakeConnection:
        self.calls.append((args, kwargs))
        sslrootcert = kwargs.get("sslrootcert")
        if isinstance(sslrootcert, str) and sslrootcert.startswith("/proc/self/fd/"):
            descriptor = int(sslrootcert.rsplit("/", 1)[1])
            os.fstat(descriptor)
            self.tls_ca_fd_was_open = True
            with open(sslrootcert, "rb") as handle:
                self.tls_ca_bytes = handle.read()
            if self.mutate_tls_ca_on_connect is not None:
                Path(sslrootcert).write_bytes(self.mutate_tls_ca_on_connect)
        if self.failure is not None:
            raise self.failure
        return self.connection


def _invoke_main(
    monkeypatch: pytest.MonkeyPatch,
    *,
    connect: _FakeConnect | None = None,
    libpq_version: int = 170_000,
    runtime_libpq_version: int = 170_000,
    dsn: str = DIRECT_DSN,
    expected_project_ref: str = PROJECT_REF,
    expected_database_name: str = DATABASE_NAME,
    authorization_overrides: dict[str, str] | None = None,
    authorization_raw: bytes | None = None,
    key: bytes = KEY,
    nonce: bytes = NONCE,
    tls_ca_certificate: bytes = TLS_CA_CERTIFICATE,
    tls_ca_action: str | None = None,
    confirmation: str = preflight.CONFIRMATION,
    reset_attempt: bool = True,
    environment: dict[str, str] | None = None,
) -> tuple[int, _FakeConnect, bytes]:
    _clean_database_environment(monkeypatch)
    if environment:
        for name, value in environment.items():
            monkeypatch.setenv(name, value)
    if reset_attempt:
        monkeypatch.setattr(preflight, "_ATTEMPT_STATE", preflight.AttemptState())
    monkeypatch.setattr(preflight, "_utc_now", lambda: NOW)
    monkeypatch.setattr(preflight.psycopg2, "__libpq_version__", libpq_version)
    monkeypatch.setattr(
        preflight.extensions,
        "libpq_version",
        lambda: runtime_libpq_version,
    )
    fake_connect = connect or _FakeConnect()
    monkeypatch.setattr(preflight.psycopg2, "connect", fake_connect)
    expected_project_ref_sha256 = _project_hash(expected_project_ref)
    expected_database_name_sha256 = _database_hash(expected_database_name)
    if authorization_raw is None:
        authorization_raw = _authorization_bytes(
            _authorization_values(
                runner_sha256=preflight._runner_sha256(),
                expected_project_ref_sha256=expected_project_ref_sha256,
                expected_database_name_sha256=expected_database_name_sha256,
                nonce=nonce,
                overrides={
                    "tls_ca_certificate_sha256": _tls_ca_hash(
                        tls_ca_certificate
                    ),
                    **(authorization_overrides or {}),
                },
            )
        )
    values = (
        dsn.encode("utf-8"),
        authorization_raw,
        expected_project_ref_sha256.encode("ascii"),
        expected_database_name_sha256.encode("ascii"),
        key,
        nonce,
    )
    with ExitStack() as stack:
        descriptors = [stack.enter_context(_descriptor(value)) for value in values]
        tls_ca_descriptor, tls_ca_path = stack.enter_context(
            _tls_ca_descriptor(tls_ca_certificate)
        )
        descriptors.append(tls_ca_descriptor)
        if tls_ca_action in {"drift_before_connect", "close_before_connect"}:
            real_validate_dsn = preflight._validate_dsn

            def validate_then_change_ca(*args: Any, **kwargs: Any) -> preflight.Target:
                target = real_validate_dsn(*args, **kwargs)
                if tls_ca_action == "drift_before_connect":
                    tls_ca_path.write_bytes(tls_ca_certificate + b"drift")
                else:
                    os.close(tls_ca_descriptor)
                return target

            monkeypatch.setattr(preflight, "_validate_dsn", validate_then_change_ca)
        cli_descriptors = list(descriptors)
        if tls_ca_action == "duplicate_nonce_descriptor":
            cli_descriptors[-1] = cli_descriptors[-2]
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
            cli_descriptors,
            strict=True,
        ):
            argv.extend((flag, str(descriptor)))
        argv.extend(("--confirmation", confirmation))
        result = preflight.main(argv)
    return result, fake_connect, authorization_raw


def _output(capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def _output_map(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        key, value = line.split("=", 1)
        assert key not in result
        result[key] = value
    return result


def test_runner_and_sql_contracts_are_byte_pinned_and_exact() -> None:
    assert hashlib.sha256(RUNNER_PATH.read_bytes()).hexdigest() == preflight._runner_sha256()
    assert preflight.PREFLIGHT_SQL_SHA256 == (
        "001bfda9b4655d028abfb7d8f44ac6c4e5ab51861c9623dd54b1cdd0ab6ea336"
    )
    assert hashlib.sha256(SQL_PATH.read_bytes()).hexdigest() == (
        preflight.PREFLIGHT_SQL_SHA256
    )
    contract = preflight._load_sql_contract()
    executed_bytes = b"".join(item.encode("ascii") for item in contract.statements)
    executed_bytes += contract.rollback.encode("ascii")
    assert (
        executed_bytes[: -len(preflight.ROLLBACK_SQL)]
        + b"\n"
        + preflight.ROLLBACK_SQL
        == SQL_PATH.read_bytes()
    )
    assert len(contract.statements) == 7
    assert contract.statements[0] == (
        "begin transaction isolation level repeatable read read only;\n"
    )
    assert contract.rollback == "rollback;\n"
    assert sum("set_config('search_path', 'pg_catalog', true)" in item for item in contract.statements) == 1
    normalized = re.sub(r"--[^\n]*", "", executed_bytes.decode("ascii")).casefold()
    assert not re.search(
        r"(?im)^\s*(insert|update|delete|merge|copy|call|do|create|alter|drop|"
        r"truncate|grant|revoke|vacuum|analyze|refresh|cluster|reindex)\b",
        normalized,
    )


def test_sql_pin_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        preflight,
        "_read_stable_public_file",
        lambda _path, _maximum: SQL_PATH.read_bytes() + b"\n",
    )
    with pytest.raises(preflight.ContractError):
        preflight._load_sql_contract()


def test_cli_is_dev_only_fd_only_and_has_no_output_or_environment_switch() -> None:
    parser = preflight._build_parser()
    options = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert options == {
        "--database-url-fd",
        "--authorization-record-fd",
        "--expected-project-ref-sha256-fd",
        "--expected-database-name-sha256-fd",
        "--hmac-key-fd",
        "--nonce-fd",
        "--tls-ca-cert-fd",
        "--confirmation",
    }
    assert "--environment" not in options
    assert "--output-dir" not in options
    assert "--database-url" not in options
    assert len([option for option in options if option.endswith("-fd")]) == 7


def test_ast_has_no_subprocess_socket_requests_or_file_output_primitives() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Attribute):
            attributes.add(node.attr)
    assert not imported.intersection(
        {"asyncio", "http", "requests", "socket", "subprocess", "urllib"}
    )
    assert not attributes.intersection(
        {
            "mkdir",
            "popen",
            "remove",
            "rename",
            "rmdir",
            "symlink",
            "system",
            "unlink",
            "write_bytes",
            "write_text",
        }
    )
    assert "materialize_migration_history" not in source
    assert "capture_one_snapshot" not in source
    assert "O_CREAT" not in source and "O_WRONLY" not in source and "O_RDWR" not in source
    assert 'sslrootcert="system"' not in source
    assert "SSL_CERT_FILE" in preflight.RELEVANT_DATABASE_ENV_NAMES


def test_private_fd_accepts_fifo_and_exact_0600_stable_regular(tmp_path: Path) -> None:
    with _descriptor(b"fifo-private") as descriptor:
        assert preflight._read_private_fd(descriptor, 64) == b"fifo-private"
    path = tmp_path / "private-input"
    path.write_bytes(b"regular-private")
    path.chmod(0o600)
    descriptor = os.open(path, os.O_RDONLY)
    try:
        assert preflight._read_private_fd(descriptor, 64) == b"regular-private"
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("mode", [0o000, 0o400, 0o640, 0o700])
def test_private_regular_fd_rejects_every_mode_except_0600(
    tmp_path: Path, mode: int
) -> None:
    path = tmp_path / f"mode-{mode:o}"
    path.write_bytes(b"private")
    descriptor = os.open(path, os.O_RDONLY)
    path.chmod(mode)
    try:
        with pytest.raises(preflight.InputError):
            preflight._read_private_fd(descriptor, 64)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("kind", ["socket", "device", "directory", "hardlink"])
def test_private_fd_rejects_type_or_link_violations(tmp_path: Path, kind: str) -> None:
    peer: socket.socket | None = None
    if kind == "socket":
        source, peer = socket.socketpair()
        descriptor = source.detach()
    elif kind == "device":
        descriptor = os.open("/dev/null", os.O_RDONLY)
    elif kind == "directory":
        descriptor = os.open(tmp_path, os.O_RDONLY)
    else:
        path = tmp_path / "hardlinked"
        path.write_bytes(b"private")
        path.chmod(0o600)
        os.link(path, tmp_path / "hardlinked-second-name")
        descriptor = os.open(path, os.O_RDONLY)
    try:
        with pytest.raises(preflight.InputError):
            preflight._read_private_fd(descriptor, 64)
    finally:
        os.close(descriptor)
        if peer is not None:
            peer.close()


@pytest.mark.parametrize("kind", ["regular", "fifo"])
def test_private_fd_rejects_metadata_toctou(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    if kind == "regular":
        path = tmp_path / "mutable"
        path.write_bytes(b"stable-size")
        path.chmod(0o600)
        descriptor = os.open(path, os.O_RDONLY)
    else:
        path = None
        read_descriptor, write_descriptor = os.pipe()
        os.write(write_descriptor, b"fifo-payload")
        os.close(write_descriptor)
        descriptor = read_descriptor
    real_read = os.read
    changed = False

    def mutate_after_read(fd: int, maximum: int) -> bytes:
        nonlocal changed
        value = real_read(fd, maximum)
        if fd == descriptor and value and not changed:
            changed = True
            os.fchmod(descriptor, 0o400)
        return value

    monkeypatch.setattr(preflight.os, "read", mutate_after_read)
    try:
        with pytest.raises(preflight.InputError):
            preflight._read_private_fd(descriptor, 64)
    finally:
        os.close(descriptor)
    assert changed is True


def test_tls_ca_witness_requires_stable_private_read_only_regular_file() -> None:
    with _tls_ca_descriptor() as (descriptor, _path):
        info = os.fstat(descriptor)
        access_mode = fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE
        offset_before = os.lseek(descriptor, 0, os.SEEK_CUR)
        witness = preflight._witness_tls_ca_certificate_fd(descriptor)
        assert stat.S_ISREG(info.st_mode)
        assert access_mode == os.O_RDONLY
        assert stat.S_IMODE(info.st_mode) == 0o600
        assert info.st_nlink == 1
        assert info.st_uid == os.geteuid()
        assert info.st_gid == os.getegid()
        assert info.st_size == len(TLS_CA_CERTIFICATE)
        assert witness.descriptor == descriptor
        assert witness.size == len(TLS_CA_CERTIFICATE)
        assert witness.sha256 == _tls_ca_hash()
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == offset_before
        preflight._revalidate_tls_ca_certificate_fd(witness)


@pytest.mark.parametrize(
    "violation",
    ["writable", "mode", "hardlink", "empty", "oversized"],
)
def test_tls_ca_witness_rejects_access_metadata_and_size_violations(
    tmp_path: Path,
    violation: str,
) -> None:
    path = tmp_path / "ca.crt"
    raw = TLS_CA_CERTIFICATE
    if violation == "empty":
        raw = b""
    elif violation == "oversized":
        raw = b"x" * (preflight.MAX_TLS_CA_CERTIFICATE_BYTES + 1)
    path.write_bytes(raw)
    path.chmod(0o600)
    if violation == "mode":
        path.chmod(0o640)
    elif violation == "hardlink":
        os.link(path, tmp_path / "ca-second-name.crt")
    flags = os.O_RDWR if violation == "writable" else os.O_RDONLY
    descriptor = os.open(path, flags)
    try:
        with pytest.raises(preflight.InputError):
            preflight._witness_tls_ca_certificate_fd(descriptor)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("stat_index", [4, 5], ids=["uid", "gid"])
def test_tls_ca_witness_rejects_owner_or_group_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    stat_index: int,
) -> None:
    with _tls_ca_descriptor() as (descriptor, _path):
        real_fstat = preflight.os.fstat

        def fstat_with_mismatched_identity(fd: int) -> os.stat_result:
            info = real_fstat(fd)
            if fd != descriptor:
                return info
            values = list(info)
            values[stat_index] = int(values[stat_index]) + 1
            return os.stat_result(values)

        monkeypatch.setattr(preflight.os, "fstat", fstat_with_mismatched_identity)
        with pytest.raises(preflight.InputError):
            preflight._witness_tls_ca_certificate_fd(descriptor)


@pytest.mark.parametrize("action", ["drift", "close"])
def test_tls_ca_revalidation_rejects_content_drift_or_closed_fd(action: str) -> None:
    with _tls_ca_descriptor() as (descriptor, path):
        witness = preflight._witness_tls_ca_certificate_fd(descriptor)
        if action == "drift":
            path.write_bytes(TLS_CA_CERTIFICATE + b"drift")
        else:
            os.close(descriptor)
        with pytest.raises(preflight.InputError):
            preflight._revalidate_tls_ca_certificate_fd(witness)


def test_authorization_record_is_canonical_bounded_and_distinguishes_source_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight, "_utc_now", lambda: NOW)
    runner_sha256 = preflight._runner_sha256()
    values = _authorization_values(
        runner_sha256=runner_sha256,
        expected_project_ref_sha256=_project_hash(),
        expected_database_name_sha256=_database_hash(),
    )
    parsed = preflight._parse_authorization(
        _authorization_bytes(values),
        runner_sha256=runner_sha256,
        expected_project_ref_sha256=_project_hash(),
        expected_database_name_sha256=_database_hash(),
        tls_ca_certificate_sha256=_tls_ca_hash(),
        nonce_sha256=hashlib.sha256(NONCE).hexdigest(),
        now=NOW,
    )
    assert parsed.values["base_git_sha"] == preflight.SOURCE_BASE_GIT_SHA
    assert parsed.values["runner_sha256"] == runner_sha256
    assert parsed.values["base_git_sha"] != parsed.values["runner_sha256"]
    assert parsed.values["single_use_scope"] == "PROCESS_INVOCATION_ONLY"
    assert parsed.values["single_attempt"] == "true"
    assert parsed.values["tls_ca_certificate_sha256"] == _tls_ca_hash()
    assert TLS_CA_CERTIFICATE not in _authorization_bytes(values)


def test_source_base_git_sha_is_literal_40hex_and_shallow_checkout_safe() -> None:
    expected = "fe7dcd394bd1cfdc96204ad994bcba9f0c96adb4"
    # CI intentionally uses a shallow checkout, so history-object availability
    # is not part of this source-binding contract.
    assert re.fullmatch(r"[0-9a-f]{40}", preflight.SOURCE_BASE_GIT_SHA)
    assert preflight.SOURCE_BASE_GIT_SHA == expected


@pytest.mark.parametrize(
    "mutation",
    ["duplicate", "extra", "reordered", "crlf", "missing_lf", "wrong_base"],
)
def test_authorization_record_rejects_noncanonical_or_wrong_source_binding(
    mutation: str,
) -> None:
    runner_sha256 = preflight._runner_sha256()
    values = _authorization_values(
        runner_sha256=runner_sha256,
        expected_project_ref_sha256=_project_hash(),
        expected_database_name_sha256=_database_hash(),
    )
    raw = _authorization_bytes(values)
    if mutation == "duplicate":
        lines = raw.splitlines(keepends=True)
        lines[1] = lines[0]
        raw = b"".join(lines)
    elif mutation == "extra":
        raw += b"unexpected=false\n"
    elif mutation == "reordered":
        lines = raw.splitlines(keepends=True)
        lines[0], lines[1] = lines[1], lines[0]
        raw = b"".join(lines)
    elif mutation == "crlf":
        raw = raw.replace(b"\n", b"\r\n")
    elif mutation == "missing_lf":
        raw = raw.rstrip(b"\n")
    else:
        raw = raw.replace(
            preflight.SOURCE_BASE_GIT_SHA.encode("ascii"), b"f" * 40
        )
    with pytest.raises(preflight.AuthorizationError):
        preflight._parse_authorization(
            raw,
            runner_sha256=runner_sha256,
            expected_project_ref_sha256=_project_hash(),
            expected_database_name_sha256=_database_hash(),
            tls_ca_certificate_sha256=_tls_ca_hash(),
            nonce_sha256=hashlib.sha256(NONCE).hexdigest(),
            now=NOW,
        )


@pytest.mark.parametrize(
    ("field", "sensitive_value"),
    [
        ("database_url", DIRECT_DSN),
        ("host", f"db.{PROJECT_REF}.supabase.co"),
        ("password", "private-password"),
        ("project_ref", PROJECT_REF),
        ("database_name", DATABASE_NAME),
        ("system_identifier", SYSTEM_IDENTIFIER),
        ("hmac_key", KEY.decode("ascii")),
        ("nonce", NONCE.decode("ascii")),
    ],
)
def test_authorization_record_rejects_raw_sensitive_fields_before_connect(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    field: str,
    sensitive_value: str,
) -> None:
    values = _authorization_values(
        runner_sha256=preflight._runner_sha256(),
        expected_project_ref_sha256=_project_hash(),
        expected_database_name_sha256=_database_hash(),
    )
    raw = _authorization_bytes(values) + f"{field}={sensitive_value}\n".encode(
        "ascii"
    )
    connect = _FakeConnect()
    result, _, _ = _invoke_main(
        monkeypatch,
        connect=connect,
        authorization_raw=raw,
    )
    text = _output(capsys)
    assert field not in preflight.AUTHORIZATION_FIELDS
    assert result == preflight.AuthorizationError.exit_code
    assert connect.calls == []
    assert sensitive_value not in text
    assert "RESULT=BLOCKED_AUTHORIZATION_INVALID" in text
    assert "TLS_MODE=" not in text


@pytest.mark.parametrize(
    ("valid_from", "expires"),
    [
        ("2026-08-30T12:01:00Z", "2026-08-30T12:10:00Z"),
        ("2026-08-30T11:00:00Z", "2026-08-30T11:10:00Z"),
        ("2026-08-30T11:59:00Z", "2026-08-30T12:16:00Z"),
        ("2026-08-30T12:00:00Z", "2026-08-30T12:00:00Z"),
    ],
)
def test_authorization_window_is_current_positive_and_at_most_fifteen_minutes(
    valid_from: str, expires: str
) -> None:
    runner_sha256 = preflight._runner_sha256()
    values = _authorization_values(
        runner_sha256=runner_sha256,
        expected_project_ref_sha256=_project_hash(),
        expected_database_name_sha256=_database_hash(),
        overrides={"valid_from_utc": valid_from, "expires_at_utc": expires},
    )
    with pytest.raises(preflight.AuthorizationError):
        preflight._parse_authorization(
            _authorization_bytes(values),
            runner_sha256=runner_sha256,
            expected_project_ref_sha256=_project_hash(),
            expected_database_name_sha256=_database_hash(),
            tls_ca_certificate_sha256=_tls_ca_hash(),
            nonce_sha256=hashlib.sha256(NONCE).hexdigest(),
            now=NOW,
        )


def test_direct_and_pooler_dsn_extract_the_same_expected_ref() -> None:
    for dsn in (DIRECT_DSN, POOLER_DSN):
        target = preflight._validate_dsn(
            dsn,
            expected_project_ref_sha256=_project_hash(),
            expected_database_name_sha256=_database_hash(),
        )
        assert target.project_ref == PROJECT_REF
        assert target.database_name == DATABASE_NAME


@pytest.mark.parametrize(
    "dsn",
    [
        f"postgresql://postgres:pw@db.{OTHER_PROJECT_REF}.supabase.co:5432/postgres",
        f"postgresql://postgres.{OTHER_PROJECT_REF}:pw@aws-0.pooler.supabase.com:6543/postgres",
        f"postgresql://postgres:pw@db.{PROJECT_REF}.supabase.co:5432/postgres?sslmode=disable",
        f"dbname=postgres host=db.{PROJECT_REF}.supabase.co hostaddr=127.0.0.1 port=5432 user=postgres password=pw",
        f"dbname=postgres host=db.{PROJECT_REF}.supabase.co,evil.invalid port=5432 user=postgres password=pw",
        f"dbname=postgres host=db.{PROJECT_REF}.supabase.co port=5432,6543 user=postgres password=pw",
        f"dbname=postgres host=db.{PROJECT_REF}.supabase.co port=5432 user=postgres password=pw sslrootcert=/tmp/evil",
        f"dbname=postgres host=db.{PROJECT_REF}.supabase.co port=5432 user=postgres password=pw options=-csearch_path=public",
        f"postgresql://postgres:pw@db.{PROJECT_REF}.supabase.co:6543/postgres",
        f"postgresql://postgres.{PROJECT_REF}:pw@evil.pooler.invalid:6543/postgres",
    ],
)
def test_dsn_override_multihost_and_ref_swap_are_rejected(dsn: str) -> None:
    if "?" in dsn or "#" in dsn:
        with pytest.raises(preflight.TargetError):
            preflight._decode_dsn(dsn.encode("utf-8"))
        return
    with pytest.raises(preflight.TargetError):
        preflight._validate_dsn(
            dsn,
            expected_project_ref_sha256=_project_hash(),
            expected_database_name_sha256=_database_hash(),
        )


@pytest.mark.parametrize(
    "case",
    [
        "authorization",
        "nonce",
        "tls_ca_digest",
        "project_ref",
        "database_name",
        "key",
        "dsn_query",
    ],
)
def test_every_input_mismatch_blocks_before_psycopg_connect(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    connect = _FakeConnect()
    kwargs: dict[str, Any] = {"connect": connect}
    if case == "authorization":
        kwargs["authorization_overrides"] = {"environment": "PROD"}
    elif case == "nonce":
        kwargs["authorization_overrides"] = {"attempt_nonce_sha256": "f" * 64}
    elif case == "tls_ca_digest":
        kwargs["authorization_overrides"] = {
            "tls_ca_certificate_sha256": "f" * 64
        }
    elif case == "project_ref":
        kwargs["expected_project_ref"] = OTHER_PROJECT_REF
    elif case == "database_name":
        kwargs["expected_database_name"] = "different_database"
    elif case == "key":
        kwargs["key"] = b"short"
    else:
        kwargs["dsn"] = DIRECT_DSN + "?hostaddr=127.0.0.1"
    result, _, _ = _invoke_main(monkeypatch, **kwargs)
    text = _output(capsys)
    assert result != 0
    assert connect.calls == []
    assert "CONNECTION_CLOSED=true" in text
    assert "ROLLBACK_CONFIRMED=false" in text
    assert "TLS_MODE=" not in text


@pytest.mark.parametrize(
    "name",
    [
        "PGHOST",
        "PGSERVICEFILE",
        "DATABASE_URL",
        "DEV_IDENTITY_PREFLIGHT_TEST_DATABASE_URL",
        "M06_MIGRATION_DATABASE_URL",
        "SSL_CERT_FILE",
    ],
)
def test_inherited_database_environment_blocks_before_connect(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    name: str,
) -> None:
    connect = _FakeConnect()
    result, _, _ = _invoke_main(
        monkeypatch,
        connect=connect,
        environment={name: "private-environment-value"},
    )
    text = _output(capsys)
    assert result == preflight.InputError.exit_code
    assert connect.calls == []
    assert "private-environment-value" not in text
    assert "RESULT=BLOCKED_TRANSIENT_INPUT_INVALID" in text


def test_confirmation_and_dev_only_cli_reject_without_connect_or_secret_echo(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connect = _FakeConnect()
    result, _, _ = _invoke_main(
        monkeypatch, connect=connect, confirmation="PREFLIGHT_PROD_IDENTITY"
    )
    assert result == preflight.UsageError.exit_code
    assert connect.calls == []
    first = _output(capsys)
    assert "TLS_MODE=" not in first

    monkeypatch.setattr(preflight, "_ATTEMPT_STATE", preflight.AttemptState())
    secret = "postgresql://private:private@private.invalid/private"
    result = preflight.main(["--environment", "PROD", secret])
    text = _output(capsys)
    assert result == preflight.UsageError.exit_code
    assert secret not in text
    assert "PROD_ACCESSED=false" in text


def test_psycopg_build_libpq_before_17_blocks_before_connect_without_tls_or_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connect = _FakeConnect()
    result, _, _ = _invoke_main(
        monkeypatch,
        connect=connect,
        libpq_version=169_999,
    )
    text = _output(capsys)
    assert result == preflight.ContractError.exit_code
    assert connect.calls == []
    assert "ROLLBACK_CONFIRMED=false" in text
    assert "CONNECTION_CLOSED=true" in text
    assert "RESULT=BLOCKED_CONTRACT_INVALID" in text
    assert "TLS_MODE=" not in text
    assert "PREFLIGHT_IDENTITY_OBSERVED_NOT_ATTESTED" not in text


def test_runtime_libpq_before_17_blocks_before_connect_without_tls_or_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connect = _FakeConnect()
    result, _, _ = _invoke_main(
        monkeypatch,
        connect=connect,
        runtime_libpq_version=169_999,
    )
    text = _output(capsys)
    assert result == preflight.ContractError.exit_code
    assert connect.calls == []
    assert "ROLLBACK_CONFIRMED=false" in text
    assert "CONNECTION_CLOSED=true" in text
    assert "RESULT=BLOCKED_CONTRACT_INVALID" in text
    assert "TLS_MODE=" not in text
    assert "PREFLIGHT_IDENTITY_OBSERVED_NOT_ATTESTED" not in text


def test_success_uses_one_session_verify_full_explicit_ca_and_emits_correlation_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    connection = _FakeConnection()
    connect = _FakeConnect(connection)
    result, _, authorization_raw = _invoke_main(monkeypatch, connect=connect)
    text = _output(capsys)
    output = _output_map(text)
    assert result == 0
    assert len(connect.calls) == 1
    args, kwargs = connect.calls[0]
    assert args == (DIRECT_DSN,)
    sslrootcert = kwargs.pop("sslrootcert")
    assert re.fullmatch(r"/proc/self/fd/[0-9]+", sslrootcert)
    tls_ca_descriptor = int(sslrootcert.rsplit("/", 1)[1])
    assert tls_ca_descriptor >= 3
    with pytest.raises(OSError):
        os.fstat(tls_ca_descriptor)
    assert kwargs == {
        "application_name": preflight.APPLICATION_NAME,
        "connect_timeout": 5,
        "sslmode": "verify-full",
    }
    assert sslrootcert != "system"
    assert connect.tls_ca_fd_was_open is True
    assert connect.tls_ca_bytes == TLS_CA_CERTIFICATE
    contract = preflight._load_sql_contract()
    assert connection.cursor_calls == 1
    assert connection.fake_cursor.executed == [*contract.statements, contract.rollback]
    assert connection.autocommit is True
    assert connection.fake_cursor.executed.count(
        preflight.ROLLBACK_SQL.decode("ascii")
    ) == 1
    assert connection.fake_cursor.close_calls == 1
    assert connection.close_calls == 1 and connection.closed == 1
    assert output["TLS_MODE"] == "VERIFY_FULL_EXPLICIT_CA"
    assert output["TLS_CA_CERTIFICATE_SHA256"] == _tls_ca_hash()
    assert output["POSTGRES_MAJOR_17"] == "true"
    assert output["ROLLBACK_CONFIRMED"] == "true"
    assert output["CONNECTION_CLOSED"] == "true"
    assert output["RESULT"] == "PREFLIGHT_IDENTITY_OBSERVED_NOT_ATTESTED"
    assert output["OPERATIONAL_AUTHORIZATION"] == "false"
    assert output["NEXT_STAGE_AUTHORIZED"] == "false"
    assert output["CAPTURE_EXECUTED"] == "false"
    assert output["MATERIALIZATION_EXECUTED"] == "false"
    assert output["SINGLE_USE_SCOPE"] == "PROCESS_INVOCATION_ONLY"
    expected_hmac = preflight._binding_hmac(
        key=KEY,
        target_binding_sha256=output["TARGET_BINDING_SHA256"],
        system_identifier=SYSTEM_IDENTIFIER,
        database_name=DATABASE_NAME,
        authorization_record_sha256=hashlib.sha256(authorization_raw).hexdigest(),
        nonce=NONCE,
    )
    assert output["HMAC_SHA256"] == expected_hmac
    assert list(tmp_path.iterdir()) == []
    for raw_secret in (
        DIRECT_DSN,
        TLS_CA_CERTIFICATE.decode("ascii"),
        PROJECT_REF,
        DATABASE_NAME,
        SYSTEM_IDENTIFIER,
        "private-password",
        "SQLERRM",
    ):
        assert raw_secret not in text


@pytest.mark.parametrize(
    "tls_ca_action",
    ["drift_before_connect", "close_before_connect"],
)
def test_tls_ca_drift_or_close_before_connect_blocks_without_connect(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tls_ca_action: str,
) -> None:
    connect = _FakeConnect()
    result, _, _ = _invoke_main(
        monkeypatch,
        connect=connect,
        tls_ca_action=tls_ca_action,
    )
    text = _output(capsys)
    assert result == preflight.InputError.exit_code
    assert connect.calls == []
    assert "ROLLBACK_CONFIRMED=false" in text
    assert "CONNECTION_CLOSED=true" in text
    assert "RESULT=BLOCKED_TRANSIENT_INPUT_INVALID" in text
    assert "TLS_MODE=" not in text
    assert "PREFLIGHT_IDENTITY_OBSERVED_NOT_ATTESTED" not in text


def test_tls_ca_drift_after_connect_blocks_without_success_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _FakeConnection()
    connect = _FakeConnect(
        connection,
        mutate_tls_ca_on_connect=TLS_CA_CERTIFICATE + b"post-connect-drift",
    )
    result, _, _ = _invoke_main(monkeypatch, connect=connect)
    text = _output(capsys)
    assert result == preflight.InputError.exit_code
    assert len(connect.calls) == 1
    assert connect.tls_ca_fd_was_open is True
    assert connect.tls_ca_bytes == TLS_CA_CERTIFICATE
    assert connection.fake_cursor.rollback_execute_calls == 1
    assert connection.close_calls == 1 and connection.closed == 1
    assert "ROLLBACK_CONFIRMED=true" in text
    assert "CONNECTION_CLOSED=true" in text
    assert "RESULT=BLOCKED_TRANSIENT_INPUT_INVALID" in text
    assert "TLS_MODE=" not in text
    assert "PREFLIGHT_IDENTITY_OBSERVED_NOT_ATTESTED" not in text


def test_duplicate_tls_ca_descriptor_blocks_before_read_or_connect(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connect = _FakeConnect()
    result, _, _ = _invoke_main(
        monkeypatch,
        connect=connect,
        tls_ca_action="duplicate_nonce_descriptor",
    )
    text = _output(capsys)
    assert result == preflight.UsageError.exit_code
    assert connect.calls == []
    assert "ROLLBACK_CONFIRMED=false" in text
    assert "CONNECTION_CLOSED=true" in text
    assert "RESULT=BLOCKED_USAGE" in text
    assert "TLS_MODE=" not in text


def test_single_attempt_is_process_scoped_and_consumes_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connect = _FakeConnect()
    first, _, _ = _invoke_main(
        monkeypatch,
        connect=connect,
        expected_project_ref=OTHER_PROJECT_REF,
    )
    assert first == preflight.TargetError.exit_code
    _output(capsys)
    second, _, _ = _invoke_main(
        monkeypatch,
        connect=connect,
        reset_attempt=False,
    )
    text = _output(capsys)
    assert second == preflight.AttemptConsumedError.exit_code
    assert connect.calls == []
    assert "RESULT=BLOCKED_ATTEMPT_ALREADY_CONSUMED_IN_PROCESS" in text
    assert "SINGLE_USE_SCOPE=PROCESS_INVOCATION_ONLY" in text
    assert "GLOBAL" not in text


@pytest.mark.parametrize(
    "overrides",
    [
        {"current_user_matches_session_user": False},
        {"tls": False},
        {"isolation_level": "read committed"},
        {"read_only": "off"},
        {"full_visibility": False},
        {"server_version_num": 160_010},
        {"database_name": "private_database"},
        {"system_identifier": "invalid"},
        {"identity_contract": "WRONG"},
    ],
)
def test_identity_session_or_pg17_mismatch_is_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(preflight.DatabaseError):
        preflight._validate_identity(
            _identity(**overrides),
            preflight.Target(database_name=DATABASE_NAME, project_ref=PROJECT_REF),
        )


def test_identity_duplicate_json_key_is_rejected() -> None:
    value = (
        '{"identity_contract":"MIGRATION_HISTORY_ENVIRONMENT_IDENTITY_PREFLIGHT_V1",'
        '"identity_contract":"MIGRATION_HISTORY_ENVIRONMENT_IDENTITY_PREFLIGHT_V1"}'
    )
    with pytest.raises(preflight.DatabaseError):
        preflight._strict_json_object(value)


@pytest.mark.parametrize("fail_execute_at", [0, 1, 6])
def test_sql_failure_at_any_phase_rolls_back_and_closes_same_connection(
    monkeypatch: pytest.MonkeyPatch, fail_execute_at: int
) -> None:
    monkeypatch.setattr(preflight.psycopg2, "__libpq_version__", 170_000)
    monkeypatch.setattr(preflight.extensions, "libpq_version", lambda: 170_000)
    connection = _FakeConnection(fail_execute_at=fail_execute_at)
    connect = _FakeConnect(connection)
    monkeypatch.setattr(preflight.psycopg2, "connect", connect)
    cleanup = preflight.CleanupState()
    with _tls_ca_descriptor() as (tls_ca_descriptor, _path):
        with pytest.raises(preflight.DatabaseError):
            preflight._run_database_preflight(
                dsn=DIRECT_DSN,
                target=preflight.Target(DATABASE_NAME, PROJECT_REF),
                sql_contract=preflight._load_sql_contract(),
                tls_ca_certificate_fd=tls_ca_descriptor,
                cleanup=cleanup,
            )
    assert len(connect.calls) == 1
    assert connect.tls_ca_fd_was_open is True
    assert connect.tls_ca_bytes == TLS_CA_CERTIFICATE
    assert connection.cursor_calls == 1
    assert connection.fake_cursor.rollback_execute_calls == 1
    assert connection.close_calls == 1 and connection.closed == 1
    assert cleanup.rollback_confirmed is True
    assert cleanup.connection_closed is True


def test_prior_sql_error_survives_rollback_and_close_failures_without_false_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _FakeConnection(
        fail_execute_at=1,
        rollback_failures=2,
        connection_rollback_failure=True,
        connection_close_failure=True,
    )
    result, _, _ = _invoke_main(
        monkeypatch, connect=_FakeConnect(connection)
    )
    text = _output(capsys)
    assert result == preflight.DatabaseError.exit_code
    assert connection.fake_cursor.rollback_execute_calls == 1
    assert connection.rollback_calls >= 1
    assert connection.close_calls == 1 and connection.closed == 0
    assert "ROLLBACK_CONFIRMED=false" in text
    assert "CONNECTION_CLOSED=false" in text
    assert "RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED" in text
    assert "TLS_MODE=" not in text
    assert "SQLERRM" not in text


@pytest.mark.parametrize(
    ("connection_kwargs", "expected_result", "connection_closed"),
    [
        (
            {"cursor_close_failure": True},
            "BLOCKED_DATABASE_PREFLIGHT_FAILED",
            True,
        ),
        (
            {"connection_close_failure": True},
            "BLOCKED_CONNECTION_CLOSE_FAILED",
            False,
        ),
    ],
)
def test_isolated_close_failure_never_emits_tls_or_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    connection_kwargs: dict[str, bool],
    expected_result: str,
    connection_closed: bool,
) -> None:
    connection = _FakeConnection(**connection_kwargs)
    result, _, _ = _invoke_main(
        monkeypatch,
        connect=_FakeConnect(connection),
    )
    text = _output(capsys)
    assert result != 0
    assert connection.fake_cursor.rollback_execute_calls == 1
    assert connection.close_calls == 1
    assert connection.closed == int(connection_closed)
    assert "ROLLBACK_CONFIRMED=true" in text
    assert f"CONNECTION_CLOSED={str(connection_closed).lower()}" in text
    assert f"RESULT={expected_result}" in text
    assert "TLS_MODE=" not in text
    assert "PREFLIGHT_IDENTITY_OBSERVED_NOT_ATTESTED" not in text


def test_connect_transport_failure_never_claims_rollback_or_tls(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failure = SecretDatabaseFailure(
        "SQLERRM private-password abcdefghijklmnopqrst private_database 1234567890123456789"
    )
    connect = _FakeConnect(failure=failure)
    result, _, _ = _invoke_main(monkeypatch, connect=connect)
    text = _output(capsys)
    assert result == preflight.DatabaseError.exit_code
    assert len(connect.calls) == 1
    assert "ROLLBACK_CONFIRMED=false" in text
    assert "CONNECTION_CLOSED=true" in text
    assert "TLS_MODE=" not in text
    for secret in ("SQLERRM", "private-password", PROJECT_REF, "private_database", SYSTEM_IDENTIFIER):
        assert secret not in text


def test_opened_transport_failure_attempts_rollback_and_closes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _FakeConnection(fail_execute_at=2, transport_failure=True)
    result, _, _ = _invoke_main(
        monkeypatch, connect=_FakeConnect(connection)
    )
    text = _output(capsys)
    assert result == preflight.DatabaseError.exit_code
    assert connection.fake_cursor.executed.count(
        preflight.ROLLBACK_SQL.decode("ascii")
    ) == 1
    assert connection.rollback_calls == 1
    assert connection.close_calls == 1
    assert "ROLLBACK_CONFIRMED=false" in text
    assert "CONNECTION_CLOSED=true" in text
    assert "TLS_MODE=" not in text


def test_wrong_connection_server_version_closes_without_starting_sql(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _FakeConnection(server_version=160_010)
    result, _, _ = _invoke_main(
        monkeypatch, connect=_FakeConnect(connection)
    )
    text = _output(capsys)
    assert result == preflight.DatabaseError.exit_code
    assert connection.cursor_calls == 0
    assert connection.close_calls == 1 and connection.closed == 1
    assert "ROLLBACK_CONFIRMED=false" in text
    assert "CONNECTION_CLOSED=true" in text
    assert "TLS_MODE=" not in text
