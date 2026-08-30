#!/usr/bin/env python3
"""Run the nominal DEV database identity preflight without materializing evidence.

The command is deliberately DEV-only.  It accepts private inputs exclusively
through already-open file descriptors, opens one PostgreSQL connection, runs
the byte-pinned identity SQL in one explicit read-only transaction, rolls it
back and emits only sanitized hashes, booleans and fixed enums.

It never reads an environment file, writes a file, invokes a subprocess,
captures schema metadata or authorizes a later stage.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
from typing import Any, Mapping, NoReturn

import psycopg2
from psycopg2 import extensions


REPO_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT_SQL_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-environment-identity-preflight-v1.sql"
)
PREFLIGHT_SQL_SHA256 = (
    "001bfda9b4655d028abfb7d8f44ac6c4e5ab51861c9623dd54b1cdd0ab6ea336"
)
CAPTURE_SQL_SHA256 = (
    "f06a8c6dd39bc137376ab5fb80699019d6d90912e0995ddda5c8253dd8e7ff24"
)
SOURCE_BASE_GIT_SHA = "fe7dcd394bd1cfdc96204ad994bcba9f0c96adb4"
CONFIRMATION = "PREFLIGHT_DEV_IDENTITY_READ_ONLY"
AUTHORIZATION_CONTRACT = "PASTORAI_DEV_IDENTITY_PREFLIGHT_AUTHORIZATION_V1"
IDENTITY_CONTRACT = "MIGRATION_HISTORY_ENVIRONMENT_IDENTITY_PREFLIGHT_V1"
TARGET_BINDING_CONTRACT = "MIGRATION_HISTORY_EXPECTED_TARGET_BINDING_V1"
GATE = "SEPARATE_NOMINAL_DEV_READ_ONLY_PREFLIGHT_AUTHORIZATION"
ENVIRONMENT = "DEV"
REVIEWER = "REVIEWER-01_SARAH"
APPLICATION_NAME = "pastorai_dev_identity_preflight_v1"
CONNECT_TIMEOUT_SECONDS = 5
MAX_AUTHORIZATION_WINDOW = timedelta(minutes=15)
MAX_DSN_BYTES = 8_192
MAX_AUTHORIZATION_BYTES = 16_384
MAX_SQL_BYTES = 65_536
MAX_KEY_BYTES = 64
MAX_TLS_CA_CERTIFICATE_BYTES = 1_048_576
ROLLBACK_SQL = b"rollback;\n"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PROJECT_REF_RE = re.compile(r"^[a-z0-9]{20}$")
DIRECT_HOST_RE = re.compile(r"^db\.([a-z0-9]{20})\.supabase\.co$")
POOLER_HOST_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+pooler\.supabase\.com$"
)
POOLER_USER_RE = re.compile(r"^postgres\.([a-z0-9]{20})$")
DATABASE_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}$")
SYSTEM_IDENTIFIER_RE = re.compile(r"^[1-9][0-9]{0,19}$")
EXECUTOR_RE = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,63}$")
ISO_UTC_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
RAW_REF_IN_ARG_RE = re.compile(r"(?<![a-z0-9])[a-z0-9]{20}(?![a-z0-9])")
RAW_SYSTEM_IDENTIFIER_IN_ARG_RE = re.compile(r"(?<![0-9])[1-9][0-9]{15,19}(?![0-9])")

ALLOWED_DSN_KEYS = {"dbname", "host", "password", "port", "user"}
RELEVANT_DATABASE_ENV_NAMES = {
    "DATABASE_URL",
    "DATABASE_URI",
    "DB_URL",
    "DEV_IDENTITY_PREFLIGHT_TEST_DATABASE_URL",
    "DIRECT_URL",
    "ENVIRONMENT_ATTESTATION_TEST_DATABASE_URL",
    "M06_MIGRATION_DATABASE_URL",
    "OPENSSL_CONF",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "SQLALCHEMY_DATABASE_URI",
    "SUPABASE_DATABASE_URL",
    "SUPABASE_DB_URL",
}
RAW_IDENTITY_KEYS = {
    "identity_contract",
    "system_identifier",
    "database_name",
    "server_version_num",
    "current_user_matches_session_user",
    "tls",
    "isolation_level",
    "read_only",
    "full_visibility",
}
AUTHORIZATION_FIELDS = (
    "authorization_contract",
    "gate",
    "environment",
    "confirmation",
    "executor",
    "reviewer",
    "base_git_sha",
    "runner_sha256",
    "preflight_sql_sha256",
    "tls_ca_certificate_sha256",
    "expected_project_ref_sha256",
    "expected_database_name_sha256",
    "attempt_nonce_sha256",
    "valid_from_utc",
    "expires_at_utc",
    "single_attempt",
    "single_use_scope",
    "prod_authorized",
    "capture_authorized",
    "materialization_authorized",
    "operational_authorization",
    "next_stage_authorized",
)
FORBIDDEN_ARG_FRAGMENTS = (
    "://",
    ".supabase.co",
    "pooler.supabase.com",
    "password=",
    "host=",
    "system_identifier",
    "database_name",
)


class PreflightError(RuntimeError):
    exit_code = 10
    reason = "INTERNAL_ERROR"


class UsageError(PreflightError):
    exit_code = 2
    reason = "USAGE"


class ContractError(PreflightError):
    exit_code = 3
    reason = "CONTRACT_INVALID"


class InputError(PreflightError):
    exit_code = 4
    reason = "TRANSIENT_INPUT_INVALID"


class AuthorizationError(PreflightError):
    exit_code = 5
    reason = "AUTHORIZATION_INVALID"


class TargetError(PreflightError):
    exit_code = 6
    reason = "DEV_TARGET_INVALID"


class DatabaseError(PreflightError):
    exit_code = 7
    reason = "DATABASE_PREFLIGHT_FAILED"


class RollbackError(PreflightError):
    exit_code = 8
    reason = "ROLLBACK_FAILED"


class ConnectionCloseError(PreflightError):
    exit_code = 8
    reason = "CONNECTION_CLOSE_FAILED"


class AttemptConsumedError(PreflightError):
    exit_code = 9
    reason = "ATTEMPT_ALREADY_CONSUMED_IN_PROCESS"


class SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise UsageError


@dataclass(frozen=True)
class SqlContract:
    statements: tuple[str, ...]
    rollback: str


@dataclass(frozen=True)
class Target:
    database_name: str
    project_ref: str


@dataclass(frozen=True)
class Authorization:
    record_sha256: str
    values: Mapping[str, str]


@dataclass(frozen=True)
class TlsCaCertificateWitness:
    descriptor: int
    stat_snapshot: tuple[int, ...]
    size: int
    offset: int
    sha256: str


@dataclass
class AttemptState:
    consumed: bool = False


@dataclass
class CleanupState:
    connection_opened: bool = False
    connection_closed: bool = True
    rollback_attempted: bool = False
    rollback_confirmed: bool = False


_ATTEMPT_STATE = AttemptState()
_TEST_ONLY_LOOPBACK_SENTINEL = object()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _frame(label: str, raw: str) -> bytes:
    label_bytes = label.encode("ascii")
    raw_bytes = raw.encode("utf-8")
    return label_bytes + struct.pack(">Q", len(raw_bytes)) + raw_bytes


def _component_sha256(label: str, raw: str) -> str:
    return hashlib.sha256(_frame(label, raw)).hexdigest()


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")


def _stat_snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _directory_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _file_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _read_stable_public_file(path: Path, maximum: int) -> bytes:
    """Read one repository file once and reject nominal-path replacement."""
    parent = path.parent
    basename = path.name
    first_parent_fd: int | None = None
    file_fd: int | None = None
    second_parent_fd: int | None = None
    second_file_fd: int | None = None
    try:
        parent_info = parent.lstat()
        if not stat.S_ISDIR(parent_info.st_mode):
            raise ContractError
        first_parent_fd = os.open(parent, _directory_flags())
        opened_parent = os.fstat(first_parent_fd)
        if _stat_snapshot(opened_parent) != _stat_snapshot(parent_info):
            raise ContractError
        nominal_info = os.stat(basename, dir_fd=first_parent_fd, follow_symlinks=False)
        file_fd = os.open(basename, _file_flags(), dir_fd=first_parent_fd)
        before = os.fstat(file_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or before.st_gid != os.getegid()
            or _stat_snapshot(before) != _stat_snapshot(nominal_info)
            or before.st_size <= 0
            or before.st_size > maximum
        ):
            raise ContractError
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if not raw or len(raw) > maximum or _stat_snapshot(os.fstat(file_fd)) != _stat_snapshot(before):
            raise ContractError

        second_parent_info = parent.lstat()
        second_parent_fd = os.open(parent, _directory_flags())
        if (
            _stat_snapshot(second_parent_info) != _stat_snapshot(parent_info)
            or _stat_snapshot(os.fstat(second_parent_fd)) != _stat_snapshot(opened_parent)
        ):
            raise ContractError
        second_file_fd = os.open(basename, _file_flags(), dir_fd=second_parent_fd)
        reopened = os.fstat(second_file_fd)
        if _stat_snapshot(reopened) != _stat_snapshot(before):
            raise ContractError
        return raw
    except (OSError, ContractError):
        raise ContractError from None
    finally:
        for descriptor in (second_file_fd, second_parent_fd, file_fd, first_parent_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def _read_private_fd(descriptor: int, maximum: int) -> bytes:
    if descriptor < 3:
        raise InputError
    try:
        before = os.fstat(descriptor)
    except OSError:
        raise InputError from None
    regular = stat.S_ISREG(before.st_mode)
    fifo = stat.S_ISFIFO(before.st_mode)
    if not regular and not fifo:
        raise InputError
    if (
        before.st_uid != os.geteuid()
        or before.st_gid != os.getegid()
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink != 1
    ):
        raise InputError
    if regular:
        if before.st_size <= 0 or before.st_size > maximum:
            raise InputError
        try:
            if os.lseek(descriptor, 0, os.SEEK_CUR) != 0:
                raise InputError
        except OSError:
            raise InputError from None
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            chunk = os.read(descriptor, min(65_536, maximum + 1 - total))
        except OSError:
            raise InputError from None
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum:
            raise InputError
    if total == 0:
        raise InputError
    try:
        after = os.fstat(descriptor)
    except OSError:
        raise InputError from None
    if _stat_snapshot(after) != _stat_snapshot(before):
        raise InputError
    return b"".join(chunks)


def _pread_sha256(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    position = 0
    while position < size:
        try:
            chunk = os.pread(descriptor, min(65_536, size - position), position)
        except OSError:
            raise InputError from None
        if not chunk:
            raise InputError
        digest.update(chunk)
        position += len(chunk)
    try:
        if os.pread(descriptor, 1, size):
            raise InputError
    except OSError:
        raise InputError from None
    return digest.hexdigest()


def _witness_tls_ca_certificate_fd(descriptor: int) -> TlsCaCertificateWitness:
    if descriptor < 3:
        raise InputError
    try:
        before = os.fstat(descriptor)
        offset = os.lseek(descriptor, 0, os.SEEK_CUR)
        access_mode = fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE
    except OSError:
        raise InputError from None
    if (
        not stat.S_ISREG(before.st_mode)
        or access_mode != os.O_RDONLY
        or before.st_uid != os.geteuid()
        or before.st_gid != os.getegid()
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink != 1
        or before.st_size <= 0
        or before.st_size > MAX_TLS_CA_CERTIFICATE_BYTES
    ):
        raise InputError
    digest = _pread_sha256(descriptor, before.st_size)
    try:
        after = os.fstat(descriptor)
        after_offset = os.lseek(descriptor, 0, os.SEEK_CUR)
    except OSError:
        raise InputError from None
    snapshot = _stat_snapshot(before)
    if _stat_snapshot(after) != snapshot or after_offset != offset:
        raise InputError
    return TlsCaCertificateWitness(
        descriptor=descriptor,
        stat_snapshot=snapshot,
        size=before.st_size,
        offset=offset,
        sha256=digest,
    )


def _revalidate_tls_ca_certificate_fd(
    witness: TlsCaCertificateWitness,
) -> None:
    try:
        before = os.fstat(witness.descriptor)
        offset = os.lseek(witness.descriptor, 0, os.SEEK_CUR)
    except OSError:
        raise InputError from None
    if (
        _stat_snapshot(before) != witness.stat_snapshot
        or before.st_size != witness.size
        or offset != witness.offset
    ):
        raise InputError
    digest = _pread_sha256(witness.descriptor, witness.size)
    try:
        after = os.fstat(witness.descriptor)
        after_offset = os.lseek(witness.descriptor, 0, os.SEEK_CUR)
    except OSError:
        raise InputError from None
    if (
        _stat_snapshot(after) != witness.stat_snapshot
        or after_offset != witness.offset
        or not hmac.compare_digest(digest, witness.sha256)
    ):
        raise InputError


def _close_descriptors(descriptors: tuple[int, ...]) -> None:
    for descriptor in descriptors:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _validate_hash_bytes(raw: bytes, error: type[PreflightError] = InputError) -> str:
    try:
        value = raw.decode("ascii")
    except UnicodeDecodeError:
        raise error from None
    if SHA256_RE.fullmatch(value) is None:
        raise error
    return value


def _load_sql_contract() -> SqlContract:
    raw = _read_stable_public_file(PREFLIGHT_SQL_PATH, MAX_SQL_BYTES)
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), PREFLIGHT_SQL_SHA256):
        raise ContractError
    if not raw.endswith(ROLLBACK_SQL):
        raise ContractError
    prefix = raw[: -len(ROLLBACK_SQL)]
    pieces = prefix.split(b";\n")
    if len(pieces) != 8 or pieces[-1].strip():
        raise ContractError
    statement_bytes = tuple(piece + b";\n" for piece in pieces[:-1])
    if (
        len(statement_bytes) != 7
        or not statement_bytes[0].startswith(b"begin transaction isolation level repeatable read read only")
        or not statement_bytes[-1].lstrip().startswith(b"select pg_catalog.json_build_object(")
    ):
        raise ContractError
    try:
        statements = tuple(item.decode("ascii") for item in statement_bytes)
        rollback = ROLLBACK_SQL.decode("ascii")
    except UnicodeDecodeError:
        raise ContractError from None
    return SqlContract(statements=statements, rollback=rollback)


def _runner_sha256() -> str:
    return hashlib.sha256(
        _read_stable_public_file(Path(__file__).resolve(), 262_144)
    ).hexdigest()


def _assert_sanitized_argv(argv: list[str]) -> None:
    for item in argv:
        lowered = item.casefold()
        if (
            any(fragment in lowered for fragment in FORBIDDEN_ARG_FRAGMENTS)
            or RAW_REF_IN_ARG_RE.search(lowered) is not None
            or RAW_SYSTEM_IDENTIFIER_IN_ARG_RE.search(lowered) is not None
        ):
            raise UsageError


def _assert_clean_database_environment(environ: Mapping[str, str]) -> None:
    for name in environ:
        upper = name.upper()
        if (
            upper.startswith("PG")
            or upper.startswith("SSL")
            or upper.startswith("OPENSSL")
            or upper in RELEVANT_DATABASE_ENV_NAMES
        ):
            raise InputError


def _parse_timestamp(value: str) -> datetime:
    if ISO_UTC_RE.fullmatch(value) is None:
        raise AuthorizationError
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        raise AuthorizationError from None


def _parse_authorization(
    raw: bytes,
    *,
    runner_sha256: str,
    expected_project_ref_sha256: str,
    expected_database_name_sha256: str,
    tls_ca_certificate_sha256: str,
    nonce_sha256: str,
    now: datetime,
) -> Authorization:
    if b"\r" in raw or not raw.endswith(b"\n") or raw.startswith(b"\n"):
        raise AuthorizationError
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise AuthorizationError from None
    lines = text[:-1].split("\n")
    if len(lines) != len(AUTHORIZATION_FIELDS):
        raise AuthorizationError
    values: dict[str, str] = {}
    for expected_key, line in zip(AUTHORIZATION_FIELDS, lines, strict=True):
        if line.count("=") != 1:
            raise AuthorizationError
        key, value = line.split("=", 1)
        if key != expected_key or not value or key in values:
            raise AuthorizationError
        values[key] = value
    expected = {
        "authorization_contract": AUTHORIZATION_CONTRACT,
        "gate": GATE,
        "environment": ENVIRONMENT,
        "confirmation": CONFIRMATION,
        "reviewer": REVIEWER,
        "base_git_sha": SOURCE_BASE_GIT_SHA,
        "runner_sha256": runner_sha256,
        "preflight_sql_sha256": PREFLIGHT_SQL_SHA256,
        "tls_ca_certificate_sha256": tls_ca_certificate_sha256,
        "expected_project_ref_sha256": expected_project_ref_sha256,
        "expected_database_name_sha256": expected_database_name_sha256,
        "attempt_nonce_sha256": nonce_sha256,
        "single_attempt": "true",
        "single_use_scope": "PROCESS_INVOCATION_ONLY",
        "prod_authorized": "false",
        "capture_authorized": "false",
        "materialization_authorized": "false",
        "operational_authorization": "false",
        "next_stage_authorized": "false",
    }
    if any(values.get(key) != value for key, value in expected.items()):
        raise AuthorizationError
    if EXECUTOR_RE.fullmatch(values["executor"]) is None:
        raise AuthorizationError
    valid_from = _parse_timestamp(values["valid_from_utc"])
    expires_at = _parse_timestamp(values["expires_at_utc"])
    if (
        expires_at <= valid_from
        or expires_at - valid_from > MAX_AUTHORIZATION_WINDOW
        or now < valid_from
        or now > expires_at
    ):
        raise AuthorizationError
    return Authorization(
        record_sha256=hashlib.sha256(raw).hexdigest(), values=values
    )


def _decode_dsn(raw: bytes) -> str:
    if len(raw) > MAX_DSN_BYTES or b"\x00" in raw or b"\r" in raw or b"\n" in raw:
        raise InputError
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise InputError from None
    if not value or "?" in value or "#" in value:
        raise TargetError
    return value


def _validate_dsn(
    dsn: str,
    *,
    expected_project_ref_sha256: str,
    expected_database_name_sha256: str,
    test_only_allow_loopback: object | None = None,
) -> Target:
    try:
        parsed = extensions.parse_dsn(dsn)
    except Exception:
        raise TargetError from None
    if set(parsed) - ALLOWED_DSN_KEYS:
        raise TargetError
    if any(type(parsed.get(key)) is not str or not parsed.get(key) for key in ALLOWED_DSN_KEYS):
        raise TargetError
    host = parsed["host"].casefold()
    user = parsed["user"]
    database_name = parsed["dbname"]
    port = parsed["port"]
    if (
        "," in host
        or "," in port
        or port not in {"5432", "6543"}
        or database_name != "postgres"
        or DATABASE_NAME_RE.fullmatch(database_name) is None
    ):
        raise TargetError

    direct_match = DIRECT_HOST_RE.fullmatch(host)
    pooler_user_match = POOLER_USER_RE.fullmatch(user)
    if direct_match is not None:
        if user != "postgres" or port != "5432":
            raise TargetError
        project_ref = direct_match.group(1)
    elif POOLER_HOST_RE.fullmatch(host) is not None:
        if pooler_user_match is None:
            raise TargetError
        project_ref = pooler_user_match.group(1)
    elif (
        test_only_allow_loopback is _TEST_ONLY_LOOPBACK_SENTINEL
        and host in {"127.0.0.1", "::1"}
        and pooler_user_match is not None
    ):
        project_ref = pooler_user_match.group(1)
    else:
        raise TargetError
    if PROJECT_REF_RE.fullmatch(project_ref) is None:
        raise TargetError
    if not hmac.compare_digest(
        _component_sha256("PROJECT_REF", project_ref),
        expected_project_ref_sha256,
    ):
        raise TargetError
    if not hmac.compare_digest(
        _component_sha256("DATABASE_NAME", database_name),
        expected_database_name_sha256,
    ):
        raise TargetError
    return Target(database_name=database_name, project_ref=project_ref)


def _strict_json_object(value: Any) -> dict[str, Any]:
    if type(value) is dict:
        raw = _canonical_json_bytes(value)
    elif type(value) is str:
        raw = value.encode("utf-8")
    else:
        raise DatabaseError

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise DatabaseError
            result[key] = item
        return result

    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_float=lambda _value: (_ for _ in ()).throw(DatabaseError()),
            parse_constant=lambda _value: (_ for _ in ()).throw(DatabaseError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DatabaseError from None
    if type(parsed) is not dict:
        raise DatabaseError
    return parsed


def _fetch_single_value(cursor: Any) -> Any:
    try:
        row = cursor.fetchone()
        extra = cursor.fetchone()
    except Exception:
        raise DatabaseError from None
    if type(row) not in {tuple, list} or len(row) != 1 or extra is not None:
        raise DatabaseError
    return row[0]


def _validate_identity(value: Any, target: Target) -> tuple[str, str]:
    identity = _strict_json_object(value)
    if set(identity) != RAW_IDENTITY_KEYS or identity.get("identity_contract") != IDENTITY_CONTRACT:
        raise DatabaseError
    server_version = identity.get("server_version_num")
    system_identifier = identity.get("system_identifier")
    database_name = identity.get("database_name")
    if (
        type(server_version) is not int
        or server_version // 10_000 != 17
        or type(system_identifier) is not str
        or SYSTEM_IDENTIFIER_RE.fullmatch(system_identifier) is None
        or type(database_name) is not str
        or database_name != target.database_name
        or identity.get("current_user_matches_session_user") is not True
        or identity.get("tls") is not True
        or identity.get("isolation_level") != "repeatable read"
        or identity.get("read_only") != "on"
        or identity.get("full_visibility") is not True
    ):
        raise DatabaseError
    return system_identifier, database_name


def _target_binding_sha256(
    *,
    authorization_record_sha256: str,
    expected_project_ref_sha256: str,
    expected_database_name_sha256: str,
    observed_system_identifier_sha256: str,
) -> str:
    descriptor = {
        "authorization_record_sha256": authorization_record_sha256,
        "environment": ENVIRONMENT,
        "expected_database_name_sha256": expected_database_name_sha256,
        "expected_project_ref_sha256": expected_project_ref_sha256,
        "expected_system_identifier_sha256": observed_system_identifier_sha256,
        "target_binding_contract": TARGET_BINDING_CONTRACT,
    }
    return hashlib.sha256(_canonical_json_bytes(descriptor)).hexdigest()


def _binding_hmac(
    *,
    key: bytes,
    target_binding_sha256: str,
    system_identifier: str,
    database_name: str,
    authorization_record_sha256: str,
    nonce: bytes,
) -> str:
    values = (
        ENVIRONMENT,
        target_binding_sha256,
        system_identifier,
        database_name,
        CAPTURE_SQL_SHA256,
        authorization_record_sha256,
        nonce.hex(),
    )
    material = b"PASTORAI-ENVIRONMENT-ATTESTATION-BINDING\x00\x01"
    for value in values:
        payload = value.encode("utf-8")
        material += b"V" + struct.pack(">Q", len(payload)) + payload
    return hmac.new(key, material, hashlib.sha256).hexdigest()


def _run_database_preflight(
    *,
    dsn: str,
    target: Target,
    sql_contract: SqlContract,
    tls_ca_certificate_fd: int,
    cleanup: CleanupState,
) -> tuple[str, str]:
    connection: Any | None = None
    cursor: Any | None = None
    begin_attempted = False
    transaction_open = False
    rollback_confirmed = False
    pending: PreflightError | None = None
    identity: tuple[str, str] | None = None
    try:
        if (
            getattr(psycopg2, "__libpq_version__", 0) < 170_000
            or extensions.libpq_version() < 170_000
        ):
            raise ContractError
        connection = psycopg2.connect(
            dsn,
            application_name=APPLICATION_NAME,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            sslmode="verify-full",
            sslrootcert=f"/proc/self/fd/{tls_ca_certificate_fd}",
        )
        cleanup.connection_opened = True
        cleanup.connection_closed = False
        if type(connection.server_version) is not int or connection.server_version // 10_000 != 17:
            raise DatabaseError
        connection.autocommit = True
        cursor = connection.cursor()
        begin_attempted = True
        cursor.execute(sql_contract.statements[0])
        transaction_open = True
        for statement in sql_contract.statements[1:-1]:
            cursor.execute(statement)
            _fetch_single_value(cursor)
        cursor.execute(sql_contract.statements[-1])
        identity = _validate_identity(_fetch_single_value(cursor), target)
        cursor.execute(sql_contract.rollback)
        transaction_open = False
        cleanup.rollback_attempted = True
        rollback_confirmed = (
            connection.get_transaction_status() == extensions.TRANSACTION_STATUS_IDLE
        )
        cleanup.rollback_confirmed = rollback_confirmed
        if not rollback_confirmed:
            raise RollbackError
    except PreflightError as exc:
        pending = exc
    except Exception:
        pending = DatabaseError()
    finally:
        if connection is not None and cursor is not None and begin_attempted and not rollback_confirmed:
            cleanup.rollback_attempted = True
            try:
                cursor.execute(sql_contract.rollback)
                transaction_open = False
                rollback_confirmed = (
                    connection.get_transaction_status()
                    == extensions.TRANSACTION_STATUS_IDLE
                )
                if not rollback_confirmed:
                    connection.rollback()
                    rollback_confirmed = (
                        connection.get_transaction_status()
                        == extensions.TRANSACTION_STATUS_IDLE
                    )
            except Exception:
                try:
                    connection.rollback()
                    transaction_open = False
                    rollback_confirmed = (
                        connection.get_transaction_status()
                        == extensions.TRANSACTION_STATUS_IDLE
                    )
                except Exception:
                    rollback_confirmed = False
            cleanup.rollback_confirmed = rollback_confirmed
        cursor_close_failed = False
        connection_close_failed = False
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                cursor_close_failed = True
        if connection is not None:
            try:
                connection.close()
                if getattr(connection, "closed", 0) in {0, False, None}:
                    connection_close_failed = True
                else:
                    cleanup.connection_closed = True
            except Exception:
                connection_close_failed = True
        if (transaction_open or (begin_attempted and not rollback_confirmed)) and pending is None:
            pending = RollbackError()
        if cursor_close_failed and pending is None:
            pending = DatabaseError()
        if connection_close_failed and pending is None:
            pending = ConnectionCloseError()
    if pending is not None:
        raise pending
    if not rollback_confirmed or identity is None:
        raise RollbackError
    return identity


def _build_parser() -> argparse.ArgumentParser:
    parser = SanitizedArgumentParser(add_help=False)
    parser.add_argument("--database-url-fd", required=True, type=int)
    parser.add_argument("--authorization-record-fd", required=True, type=int)
    parser.add_argument("--expected-project-ref-sha256-fd", required=True, type=int)
    parser.add_argument("--expected-database-name-sha256-fd", required=True, type=int)
    parser.add_argument("--hmac-key-fd", required=True, type=int)
    parser.add_argument("--nonce-fd", required=True, type=int)
    parser.add_argument("--tls-ca-cert-fd", required=True, type=int)
    parser.add_argument("--confirmation", required=True)
    return parser


def _deny_lines() -> tuple[str, ...]:
    return (
        "ENVIRONMENT=DEV",
        "OPERATIONAL_AUTHORIZATION=false",
        "NEXT_STAGE_AUTHORIZED=false",
        "CAPTURE_EXECUTED=false",
        "MATERIALIZATION_EXECUTED=false",
        "PROD_ACCESSED=false",
        "SINGLE_USE_SCOPE=PROCESS_INVOCATION_ONLY",
    )


def _print_blocked(reason: str, cleanup: CleanupState) -> None:
    for line in _deny_lines():
        print(line)
    print(f"ROLLBACK_CONFIRMED={str(cleanup.rollback_confirmed).lower()}")
    print(f"CONNECTION_CLOSED={str(cleanup.connection_closed).lower()}")
    print(f"RESULT=BLOCKED_{reason}")


def _consume_attempt() -> None:
    if _ATTEMPT_STATE.consumed:
        raise AttemptConsumedError
    _ATTEMPT_STATE.consumed = True


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    descriptors: tuple[int, ...] = ()
    key_buffer: bytearray | None = None
    nonce_buffer: bytearray | None = None
    tls_ca_witness: TlsCaCertificateWitness | None = None
    tls_ca_revalidated = False
    cleanup = CleanupState()
    try:
        _assert_sanitized_argv(arguments)
        args = _build_parser().parse_args(arguments)
        if args.confirmation != CONFIRMATION:
            raise UsageError
        descriptors = (
            args.database_url_fd,
            args.authorization_record_fd,
            args.expected_project_ref_sha256_fd,
            args.expected_database_name_sha256_fd,
            args.hmac_key_fd,
            args.nonce_fd,
            args.tls_ca_cert_fd,
        )
        if len(set(descriptors)) != len(descriptors) or any(item < 3 for item in descriptors):
            raise UsageError
        _consume_attempt()
        _assert_clean_database_environment(os.environ)
        sql_contract = _load_sql_contract()
        runner_sha256 = _runner_sha256()
        read_once_descriptors = descriptors[:-1]
        try:
            dsn_raw = _read_private_fd(args.database_url_fd, MAX_DSN_BYTES)
            authorization_raw = _read_private_fd(
                args.authorization_record_fd, MAX_AUTHORIZATION_BYTES
            )
            expected_project_ref_sha256 = _validate_hash_bytes(
                _read_private_fd(args.expected_project_ref_sha256_fd, 64)
            )
            expected_database_name_sha256 = _validate_hash_bytes(
                _read_private_fd(args.expected_database_name_sha256_fd, 64)
            )
            key_buffer = bytearray(
                _read_private_fd(args.hmac_key_fd, MAX_KEY_BYTES)
            )
            nonce_buffer = bytearray(_read_private_fd(args.nonce_fd, 32))
            tls_ca_witness = _witness_tls_ca_certificate_fd(
                args.tls_ca_cert_fd
            )
        finally:
            _close_descriptors(read_once_descriptors)
            descriptors = (args.tls_ca_cert_fd,)
        if tls_ca_witness is None:
            raise InputError
        if (
            key_buffer is None
            or nonce_buffer is None
            or not 32 <= len(key_buffer) <= MAX_KEY_BYTES
            or len(nonce_buffer) != 32
        ):
            raise InputError
        nonce_sha256 = hashlib.sha256(nonce_buffer).hexdigest()
        authorization = _parse_authorization(
            authorization_raw,
            runner_sha256=runner_sha256,
            expected_project_ref_sha256=expected_project_ref_sha256,
            expected_database_name_sha256=expected_database_name_sha256,
            tls_ca_certificate_sha256=tls_ca_witness.sha256,
            nonce_sha256=nonce_sha256,
            now=_utc_now(),
        )
        dsn = _decode_dsn(dsn_raw)
        target = _validate_dsn(
            dsn,
            expected_project_ref_sha256=expected_project_ref_sha256,
            expected_database_name_sha256=expected_database_name_sha256,
        )
        _revalidate_tls_ca_certificate_fd(tls_ca_witness)
        try:
            system_identifier, database_name = _run_database_preflight(
                dsn=dsn,
                target=target,
                sql_contract=sql_contract,
                tls_ca_certificate_fd=tls_ca_witness.descriptor,
                cleanup=cleanup,
            )
        finally:
            _revalidate_tls_ca_certificate_fd(tls_ca_witness)
            tls_ca_revalidated = True
        observed_system_identifier_sha256 = _component_sha256(
            "SYSTEM_IDENTIFIER", system_identifier
        )
        observed_database_name_sha256 = _component_sha256(
            "DATABASE_NAME", database_name
        )
        target_binding_sha256 = _target_binding_sha256(
            authorization_record_sha256=authorization.record_sha256,
            expected_project_ref_sha256=expected_project_ref_sha256,
            expected_database_name_sha256=expected_database_name_sha256,
            observed_system_identifier_sha256=observed_system_identifier_sha256,
        )
        hmac_sha256 = _binding_hmac(
            key=bytes(key_buffer),
            target_binding_sha256=target_binding_sha256,
            system_identifier=system_identifier,
            database_name=database_name,
            authorization_record_sha256=authorization.record_sha256,
            nonce=bytes(nonce_buffer),
        )
        for line in _deny_lines():
            print(line)
        print(f"RUNNER_SHA256={runner_sha256}")
        print(f"PREFLIGHT_SQL_SHA256={PREFLIGHT_SQL_SHA256}")
        print(f"TLS_CA_CERTIFICATE_SHA256={tls_ca_witness.sha256}")
        print(f"AUTHORIZATION_RECORD_SHA256={authorization.record_sha256}")
        print(f"EXPECTED_PROJECT_REF_SHA256={expected_project_ref_sha256}")
        print(f"OBSERVED_DATABASE_NAME_SHA256={observed_database_name_sha256}")
        print(
            "OBSERVED_SYSTEM_IDENTIFIER_SHA256="
            f"{observed_system_identifier_sha256}"
        )
        print(f"TARGET_BINDING_SHA256={target_binding_sha256}")
        print(f"ATTEMPT_NONCE_SHA256={nonce_sha256}")
        print(f"HMAC_SHA256={hmac_sha256}")
        print("POSTGRES_MAJOR_17=true")
        print("TLS_MODE=VERIFY_FULL_EXPLICIT_CA")
        print("CURRENT_USER_MATCHES_SESSION_USER=true")
        print("FULL_VISIBILITY=true")
        print("ISOLATION_LEVEL=REPEATABLE_READ")
        print("READ_ONLY=true")
        print("ROLLBACK_CONFIRMED=true")
        print("CONNECTION_CLOSED=true")
        print("RESULT=PREFLIGHT_IDENTITY_OBSERVED_NOT_ATTESTED")
        return 0
    except PreflightError as exc:
        _print_blocked(exc.reason, cleanup)
        return exc.exit_code
    except Exception:
        _print_blocked("INTERNAL_ERROR", cleanup)
        return 10
    finally:
        if tls_ca_witness is not None and not tls_ca_revalidated:
            try:
                _revalidate_tls_ca_certificate_fd(tls_ca_witness)
            except PreflightError:
                pass
        if descriptors:
            _close_descriptors(descriptors)
        if key_buffer is not None:
            key_buffer[:] = b"\x00" * len(key_buffer)
        if nonce_buffer is not None:
            nonce_buffer[:] = b"\x00" * len(nonce_buffer)


if __name__ == "__main__":
    raise SystemExit(main())
