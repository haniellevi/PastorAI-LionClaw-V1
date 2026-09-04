#!/usr/bin/env python3
"""Execute one fail-closed migration environment attestation from a Git snapshot.

The public process is only a bootstrapper.  It authenticates and materializes an
exact local Git commit with ``trusted_repository_snapshot.py`` and starts this
same program from that private snapshot.  The child accepts all sensitive
inputs through inherited private file descriptors, opens exactly one TLS
``verify-full`` PostgreSQL connection, runs identity and capture in separate
``REPEATABLE READ READ ONLY`` transactions on that same connection, closes the
connection, and only then publishes one sanitized v1 artifact.

The artifact is intentionally blocked.  This executor never applies a
migration, writes a ledger, authorizes an operational stage, or claims that the
v1 platform-surface and append-only gaps have been attested.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading
import types
from typing import Any, Callable, Iterator, Mapping, NoReturn


SCRIPT_BASENAME = "execute_migration_history_environment_attestation_v2.py"
SCRIPT_PATH = Path(__file__).absolute()
REPO_ROOT = SCRIPT_PATH.parents[2]


def _load_trusted_snapshot_primitive() -> Any:
    module_path = SCRIPT_PATH.with_name("trusted_repository_snapshot.py")
    module_name = "_pastorai_trusted_repository_snapshot_v1"
    try:
        specification = importlib.util.spec_from_file_location(module_name, module_path)
        if specification is None or specification.loader is None:
            raise ImportError
        module = importlib.util.module_from_spec(specification)
        sys.modules[module_name] = module
        specification.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(module_name, None)
        raise


trusted_snapshot = _load_trusted_snapshot_primitive()


AUTHORIZATION_SCHEMA_RELATIVE_PATH = Path(
    "docs/governance/migrations/"
    "migration-history-environment-attestation-executor-authorization-v2.schema.json"
)
PREFLIGHT_RUNNER_RELATIVE_PATH = Path(
    "backend/scripts/preflight_migration_history_environment_identity.py"
)
MATERIALIZER_RELATIVE_PATH = Path(
    "backend/scripts/materialize_migration_history_environment_attestation.py"
)
VERIFIER_RELATIVE_PATH = Path(
    "backend/scripts/verify_migration_history_environment_attestation.py"
)
CANONICAL_DERIVATION_RELATIVE_PATH = Path(
    "backend/scripts/derive_migration_history_canonical_schema.py"
)
SOURCE_MANIFEST_VERIFIER_RELATIVE_PATH = Path(
    "backend/scripts/verify_migration_history_schema_expectation_manifest.py"
)
CATALOG_HEAD_VERIFIER_RELATIVE_PATH = Path(
    "backend/scripts/verify_migration_catalog_head.py"
)
PREFLIGHT_SQL_RELATIVE_PATH = Path(
    "docs/governance/migrations/"
    "migration-history-environment-identity-preflight-v1.sql"
)
CAPTURE_SQL_RELATIVE_PATH = Path(
    "docs/governance/migrations/"
    "migration-history-environment-attestation-capture-v1.sql"
)
PROFILE_RELATIVE_PATH = Path(
    "docs/governance/migrations/"
    "migration-history-environment-attestation-profile-v1.json"
)
ARTIFACT_SCHEMA_RELATIVE_PATH = Path(
    "docs/governance/migrations/"
    "migration-history-environment-attestation.schema.json"
)
TRUSTED_SNAPSHOT_RELATIVE_PATH = Path(
    "backend/scripts/trusted_repository_snapshot.py"
)

AUTHORIZATION_CONTRACT = (
    "PASTORAI_MIGRATION_ENVIRONMENT_ATTESTATION_EXECUTION_AUTHORIZATION_V2"
)
TARGET_BINDING_CONTRACT = "MIGRATION_HISTORY_EXPECTED_TARGET_BINDING_V1"
GATES = {
    "DEV": "OWNER_AUTHORIZE_CAPTURE_MIGRATION_ENVIRONMENT_DEV_READ_ONLY_V2",
    "PROD": "OWNER_AUTHORIZE_CAPTURE_MIGRATION_ENVIRONMENT_PROD_READ_ONLY_V2",
}
CONFIRMATIONS = {
    "DEV": "EXECUTE_DEV_MIGRATION_ENVIRONMENT_ATTESTATION_READ_ONLY_V2",
    "PROD": "EXECUTE_PROD_MIGRATION_ENVIRONMENT_ATTESTATION_READ_ONLY_V2",
}

# These are historical v1 inputs.  The v2 executor consumes them but must not
# silently evolve them.  A deliberate v1 change therefore requires a new v2
# review and an explicit constant update here.
EXPECTED_FILE_SHA256 = {
    str(PREFLIGHT_RUNNER_RELATIVE_PATH): (
        "8da631fbb602488bb8c82ce1529c9d8ba17acbae8a318ea9b0fc24cdd8f65cd2"
    ),
    str(MATERIALIZER_RELATIVE_PATH): (
        "7a44699dafef512fee552e3dc3b03103ed8429bcf8fbc658016d92be7d55f616"
    ),
    str(VERIFIER_RELATIVE_PATH): (
        "da891dad279008f8e454b0d0e17c2e984216a7bf1904d77426f3a6332a9809f6"
    ),
    str(CANONICAL_DERIVATION_RELATIVE_PATH): (
        "a7f826ce4b57e5dbb1fc178826b0f0c27dc385b3307962f83b330359a36d8f3e"
    ),
    str(SOURCE_MANIFEST_VERIFIER_RELATIVE_PATH): (
        "7e6eef829d95905dd9aab16a0620a35b1da50ea4fc08baca7f1687a398870456"
    ),
    str(CATALOG_HEAD_VERIFIER_RELATIVE_PATH): (
        "2fe1a93bf9c9116426683e7fd86c4f7b7c20753f7ce11a8282d9ca06087ac30d"
    ),
    str(PREFLIGHT_SQL_RELATIVE_PATH): (
        "001bfda9b4655d028abfb7d8f44ac6c4e5ab51861c9623dd54b1cdd0ab6ea336"
    ),
    str(CAPTURE_SQL_RELATIVE_PATH): (
        "f06a8c6dd39bc137376ab5fb80699019d6d90912e0995ddda5c8253dd8e7ff24"
    ),
    str(PROFILE_RELATIVE_PATH): (
        "0734ba9302bf9d20f0b5770745124390350d231650fdb95ef915ee1b526d5147"
    ),
    str(ARTIFACT_SCHEMA_RELATIVE_PATH): (
        "6286f68864ff935156c4c19be74123bfdd06043d50bdfc4ad34844df321d9964"
    ),
    str(AUTHORIZATION_SCHEMA_RELATIVE_PATH): (
        "059db5f990c4f38672465f78428014acd34a35089317d0ae7d4d3948ad5a61f8"
    ),
    str(TRUSTED_SNAPSHOT_RELATIVE_PATH): (
        "43dd9161cda2fc3cb7e1800a1b756f5595facbcc5c15274f282f6e763252d392"
    ),
}

AUTHORIZATION_KEYS = {
    "authorization_contract",
    "gate",
    "environment",
    "confirmation",
    "owner",
    "executor",
    "source_git_sha",
    "executor_sha256",
    "trusted_snapshot_script_sha256",
    "preflight_runner_sha256",
    "materializer_sha256",
    "verifier_sha256",
    "canonical_derivation_sha256",
    "source_manifest_verifier_sha256",
    "catalog_head_verifier_sha256",
    "preflight_sql_sha256",
    "capture_sql_sha256",
    "profile_sha256",
    "artifact_schema_sha256",
    "authorization_schema_sha256",
    "tls_ca_certificate_sha256",
    "expected_project_ref_sha256",
    "expected_database_name_sha256",
    "expected_system_identifier_sha256",
    "attempt_nonce_sha256",
    "valid_from_utc",
    "expires_at_utc",
    "single_attempt",
    "single_use_scope",
    "database_session_authorized",
    "identity_capture_authorized",
    "schema_capture_authorized",
    "materialization_authorized",
    "prod_authorized",
    "database_mutation_authorized",
    "migration_application_authorized",
    "operational_authorization",
    "next_stage_authorized",
}

AUTHORIZATION_BOOLEAN_FIELDS = {
    "single_attempt",
    "database_session_authorized",
    "identity_capture_authorized",
    "schema_capture_authorized",
    "materialization_authorized",
    "prod_authorized",
    "database_mutation_authorized",
    "migration_application_authorized",
    "operational_authorization",
    "next_stage_authorized",
}

MAX_AUTHORIZATION_WINDOW = timedelta(minutes=15)
MAX_AUTHORIZATION_BYTES = 65_536
MAX_DSN_BYTES = 8_192
MAX_KEY_BYTES = 64
MAX_NONCE_BYTES = 32
MAX_CONTEXT_BYTES = 16_384
MAX_CHILD_OUTPUT_BYTES = 32_768
CHILD_TIMEOUT_SECONDS = 360
CONNECT_TIMEOUT_SECONDS = 5
EXPECTED_PSYCOPG2_VERSION = "2.9.12"
EXPECTED_PYTHON_VERSION = (3, 13, 14)
STAGING_BASENAME = ".migration-environment-attestation-v2-runtime"
INTERNAL_CHILD_COMMAND = "__trusted-snapshot-child"
_TEST_ONLY_LOOPBACK_SENTINEL = object()

BOOTSTRAP_TRUST_REQUIREMENT = (
    "EXTERNALLY_PINNED_BOOTSTRAP_AND_TRUSTED_SNAPSHOT_PRIMITIVE"
)
AUTHORIZATION_TRUST_REQUIREMENT = (
    "EXTERNAL_NOMINAL_GATE_AUTHENTICATION_REQUIRED"
)
RUNTIME_TRUST_REQUIREMENT = "EXTERNALLY_PINNED_RUNTIME_REQUIRED"

GIT_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PRINCIPAL_RE = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,63}$")
UTC_SECOND_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
SAFE_OUTPUT_LINE_RE = re.compile(r"^[A-Z0-9_./:-]+=[A-Za-z0-9_./:-]+$")
FORBIDDEN_ARG_FRAGMENTS = (
    "://",
    ".supabase.co",
    "pooler.supabase.com",
    "password=",
    "system_identifier",
    "database_name",
)
RAW_REF_IN_ARG_RE = re.compile(r"(?<![a-z0-9])[a-z0-9]{20}(?![a-z0-9])")
RAW_SYSTEM_IDENTIFIER_IN_ARG_RE = re.compile(
    r"(?<![0-9])[1-9][0-9]{15,19}(?![0-9])"
)

AUTHORIZATION_HASH_FIELDS = {
    "executor_sha256": None,
    "trusted_snapshot_script_sha256": str(TRUSTED_SNAPSHOT_RELATIVE_PATH),
    "preflight_runner_sha256": str(PREFLIGHT_RUNNER_RELATIVE_PATH),
    "materializer_sha256": str(MATERIALIZER_RELATIVE_PATH),
    "verifier_sha256": str(VERIFIER_RELATIVE_PATH),
    "canonical_derivation_sha256": str(CANONICAL_DERIVATION_RELATIVE_PATH),
    "source_manifest_verifier_sha256": str(
        SOURCE_MANIFEST_VERIFIER_RELATIVE_PATH
    ),
    "catalog_head_verifier_sha256": str(CATALOG_HEAD_VERIFIER_RELATIVE_PATH),
    "preflight_sql_sha256": str(PREFLIGHT_SQL_RELATIVE_PATH),
    "capture_sql_sha256": str(CAPTURE_SQL_RELATIVE_PATH),
    "profile_sha256": str(PROFILE_RELATIVE_PATH),
    "artifact_schema_sha256": str(ARTIFACT_SCHEMA_RELATIVE_PATH),
    "authorization_schema_sha256": str(AUTHORIZATION_SCHEMA_RELATIVE_PATH),
}

RELEVANT_DATABASE_ENV_NAMES = {
    "DATABASE_URL",
    "DATABASE_URI",
    "DB_URL",
    "DIRECT_URL",
    "M06_MIGRATION_DATABASE_URL",
    "SQLALCHEMY_DATABASE_URI",
    "SUPABASE_DATABASE_URL",
    "SUPABASE_DB_URL",
}


class ExecutorError(RuntimeError):
    exit_code = 10
    reason = "INTERNAL_ERROR"

    def __init__(self, *, phase: str = "INTERNAL") -> None:
        super().__init__()
        self.phase = phase


class UsageError(ExecutorError):
    exit_code = 2
    reason = "USAGE"


class ContractError(ExecutorError):
    exit_code = 3
    reason = "TRUSTED_SNAPSHOT_OR_CONTRACT_INVALID"


class PrivateInputError(ExecutorError):
    exit_code = 4
    reason = "PRIVATE_INPUT_INVALID"


class AuthorizationError(ExecutorError):
    exit_code = 5
    reason = "AUTHORIZATION_INVALID"


class TargetError(ExecutorError):
    exit_code = 6
    reason = "TARGET_OR_IDENTITY_MISMATCH"


class DatabaseError(ExecutorError):
    exit_code = 7
    reason = "CONNECT_TLS_AUTH_OR_CAPTURE_FAILED"


class EvidenceMaterializedBlocked(ExecutorError):
    exit_code = 8
    reason = "BLOCKED_ENVIRONMENT_ATTESTATION_V1_MATERIALIZED"


class CleanupError(ExecutorError):
    exit_code = 9
    reason = "ROLLBACK_CLOSE_OR_CLEANUP_FAILED"


CHILD_RESULT_BY_EXIT_CODE = {
    UsageError.exit_code: UsageError.reason,
    ContractError.exit_code: ContractError.reason,
    PrivateInputError.exit_code: PrivateInputError.reason,
    AuthorizationError.exit_code: AuthorizationError.reason,
    TargetError.exit_code: TargetError.reason,
    DatabaseError.exit_code: DatabaseError.reason,
    EvidenceMaterializedBlocked.exit_code: EvidenceMaterializedBlocked.reason,
    CleanupError.exit_code: CleanupError.reason,
    ExecutorError.exit_code: ExecutorError.reason,
}


class SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise UsageError(phase="ARGUMENTS")


@dataclass(frozen=True, slots=True)
class Authorization:
    record_sha256: str
    values: Mapping[str, Any]
    valid_from: datetime
    expires_at: datetime


@dataclass(slots=True)
class ExecutionState:
    environment: str
    source_git_sha: str
    phase: str = "PRE_SNAPSHOT"
    connection_opened: bool = False
    connection_closed: bool = True
    identity_rollback_confirmed: bool = False
    capture_rollback_confirmed: bool = False
    capture_executed: bool = False
    identity_capture_same_connection: bool = False
    materialization_executed: bool = False
    artifact_published: bool = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _strict_json(
    raw: bytes, *, error: type[ExecutorError], phase: str
) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise error(phase=phase)
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=reject_duplicates,
            parse_float=lambda _value: (_ for _ in ()).throw(
                error(phase=phase)
            ),
            parse_constant=lambda _value: (_ for _ in ()).throw(
                error(phase=phase)
            ),
        )
    except ExecutorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise error(phase=phase) from None
    if type(value) is not dict:
        raise error(phase=phase)
    return value


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_nlink),
        int(value.st_uid),
        int(value.st_gid),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _read_private_fd(descriptor: int, maximum: int) -> bytes:
    if type(descriptor) is not int or descriptor < 3:
        raise PrivateInputError(phase="PRIVATE_INPUTS")
    try:
        before = os.fstat(descriptor)
    except OSError:
        raise PrivateInputError(phase="PRIVATE_INPUTS") from None
    regular = stat.S_ISREG(before.st_mode)
    fifo = stat.S_ISFIFO(before.st_mode)
    if (
        not (regular or fifo)
        or before.st_uid != os.geteuid()
        or before.st_gid != os.getegid()
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink != 1
    ):
        raise PrivateInputError(phase="PRIVATE_INPUTS")
    if regular:
        try:
            position = os.lseek(descriptor, 0, os.SEEK_CUR)
        except OSError:
            raise PrivateInputError(phase="PRIVATE_INPUTS") from None
        if position != 0 or before.st_size <= 0 or before.st_size > maximum:
            raise PrivateInputError(phase="PRIVATE_INPUTS")
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            chunk = os.read(descriptor, min(65_536, maximum + 1 - total))
        except OSError:
            raise PrivateInputError(phase="PRIVATE_INPUTS") from None
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum:
            raise PrivateInputError(phase="PRIVATE_INPUTS")
    if total == 0:
        raise PrivateInputError(phase="PRIVATE_INPUTS")
    try:
        after = os.fstat(descriptor)
    except OSError:
        raise PrivateInputError(phase="PRIVATE_INPUTS") from None
    if _stat_identity(after) != _stat_identity(before):
        raise PrivateInputError(phase="PRIVATE_INPUTS")
    return b"".join(chunks)


def _close_fds(descriptors: Iterator[int] | tuple[int, ...] | list[int]) -> None:
    for descriptor in descriptors:
        try:
            os.close(descriptor)
        except OSError:
            pass


@contextmanager
def _pipe_payload(raw: bytes) -> Iterator[int]:
    read_descriptor, write_descriptor = os.pipe()
    writer_error: list[BaseException] = []

    def write_payload() -> None:
        try:
            position = 0
            while position < len(raw):
                written = os.write(write_descriptor, raw[position:])
                if written <= 0:
                    raise OSError("short anonymous-pipe write")
                position += written
        except BaseException as exc:
            writer_error.append(exc)
        finally:
            try:
                os.close(write_descriptor)
            except OSError:
                pass

    writer = threading.Thread(target=write_payload, daemon=True)
    writer.start()
    body_failed = False
    try:
        yield read_descriptor
    except BaseException:
        body_failed = True
        raise
    finally:
        try:
            os.close(read_descriptor)
        except OSError:
            pass
        writer.join(timeout=5)
        if not body_failed and (writer.is_alive() or writer_error):
            raise PrivateInputError(phase="PRIVATE_INPUTS")


def _read_stable_file(path: Path, maximum: int = 32 * 1_048_576) -> bytes:
    try:
        parent_before = path.parent.lstat()
        before = path.lstat()
        if (
            not stat.S_ISDIR(parent_before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_gid != os.getegid()
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > maximum
        ):
            raise ContractError(phase="CONTRACTS")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if _stat_identity(opened) != _stat_identity(before):
                raise ContractError(phase="CONTRACTS")
            chunks: list[bytes] = []
            remaining = maximum + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if (
                not raw
                or len(raw) > maximum
                or _stat_identity(os.fstat(descriptor)) != _stat_identity(before)
                or _stat_identity(path.parent.lstat())
                != _stat_identity(parent_before)
            ):
                raise ContractError(phase="CONTRACTS")
            return raw
        finally:
            os.close(descriptor)
    except ExecutorError:
        raise
    except OSError:
        raise ContractError(phase="CONTRACTS") from None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(_read_stable_file(path)).hexdigest()


def _component_sha256(label: str, raw: str) -> str:
    label_bytes = label.encode("ascii")
    raw_bytes = raw.encode("utf-8")
    framed = label_bytes + len(raw_bytes).to_bytes(8, "big") + raw_bytes
    return hashlib.sha256(framed).hexdigest()


def _authorization_record_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _assert_sanitized_argv(arguments: list[str]) -> None:
    for argument in arguments:
        lowered = argument.casefold()
        public_identifier = (
            GIT_SHA_RE.fullmatch(lowered) is not None
            or SHA256_RE.fullmatch(lowered) is not None
            or lowered.isdecimal()
        )
        if (
            any(fragment in lowered for fragment in FORBIDDEN_ARG_FRAGMENTS)
            or (
                not public_identifier
                and RAW_REF_IN_ARG_RE.search(lowered) is not None
            )
            or (
                not public_identifier
                and RAW_SYSTEM_IDENTIFIER_IN_ARG_RE.search(lowered) is not None
            )
            or "\x00" in argument
            or "\n" in argument
            or "\r" in argument
        ):
            raise UsageError(phase="ARGUMENTS")


def _parse_utc_second(value: Any) -> datetime:
    if type(value) is not str or UTC_SECOND_RE.fullmatch(value) is None:
        raise AuthorizationError(phase="AUTHORIZATION")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        raise AuthorizationError(phase="AUTHORIZATION") from None


def _ensure_authorization_window(
    authorization: Authorization, now: datetime | None = None
) -> None:
    observed = _utc_now() if now is None else now
    if observed < authorization.valid_from or observed >= authorization.expires_at:
        raise AuthorizationError(phase="AUTHORIZATION_WINDOW")


def _validate_authorization(
    raw: bytes,
    *,
    environment: str,
    confirmation: str,
    source_git_sha: str,
    executor_sha256: str,
    tls_ca_certificate_sha256: str,
    nonce_sha256: str,
    now: datetime | None = None,
) -> Authorization:
    if (
        not raw.endswith(b"\n")
        or raw.startswith(b"\n")
        or b"\r" in raw
        or len(raw) > MAX_AUTHORIZATION_BYTES
    ):
        raise AuthorizationError(phase="AUTHORIZATION")
    values = _strict_json(
        raw[:-1], error=AuthorizationError, phase="AUTHORIZATION"
    )
    if set(values) != AUTHORIZATION_KEYS:
        raise AuthorizationError(phase="AUTHORIZATION")
    if not hmac.compare_digest(_canonical_json_bytes(values) + b"\n", raw):
        raise AuthorizationError(phase="AUTHORIZATION")
    if any(type(values.get(key)) is not bool for key in AUTHORIZATION_BOOLEAN_FIELDS):
        raise AuthorizationError(phase="AUTHORIZATION")
    for key in (
        "executor_sha256",
        "trusted_snapshot_script_sha256",
        "preflight_runner_sha256",
        "materializer_sha256",
        "verifier_sha256",
        "preflight_sql_sha256",
        "capture_sql_sha256",
        "profile_sha256",
        "artifact_schema_sha256",
        "authorization_schema_sha256",
        "tls_ca_certificate_sha256",
        "expected_project_ref_sha256",
        "expected_database_name_sha256",
        "expected_system_identifier_sha256",
        "attempt_nonce_sha256",
    ):
        if type(values.get(key)) is not str or SHA256_RE.fullmatch(values[key]) is None:
            raise AuthorizationError(phase="AUTHORIZATION")
    if any(
        values[key] == "0" * 64
        for key in (
            "expected_project_ref_sha256",
            "expected_database_name_sha256",
            "expected_system_identifier_sha256",
            "attempt_nonce_sha256",
        )
    ):
        raise AuthorizationError(phase="AUTHORIZATION")
    if (
        type(values.get("source_git_sha")) is not str
        or GIT_SHA_RE.fullmatch(values["source_git_sha"]) is None
        or type(values.get("owner")) is not str
        or PRINCIPAL_RE.fullmatch(values["owner"]) is None
        or type(values.get("executor")) is not str
        or PRINCIPAL_RE.fullmatch(values["executor"]) is None
    ):
        raise AuthorizationError(phase="AUTHORIZATION")
    expected_scalars: dict[str, Any] = {
        "authorization_contract": AUTHORIZATION_CONTRACT,
        "gate": GATES[environment],
        "environment": environment,
        "confirmation": confirmation,
        "source_git_sha": source_git_sha,
        "executor_sha256": executor_sha256,
        "trusted_snapshot_script_sha256": EXPECTED_FILE_SHA256[
            str(TRUSTED_SNAPSHOT_RELATIVE_PATH)
        ],
        "preflight_runner_sha256": EXPECTED_FILE_SHA256[
            str(PREFLIGHT_RUNNER_RELATIVE_PATH)
        ],
        "materializer_sha256": EXPECTED_FILE_SHA256[
            str(MATERIALIZER_RELATIVE_PATH)
        ],
        "verifier_sha256": EXPECTED_FILE_SHA256[str(VERIFIER_RELATIVE_PATH)],
        "canonical_derivation_sha256": EXPECTED_FILE_SHA256[
            str(CANONICAL_DERIVATION_RELATIVE_PATH)
        ],
        "source_manifest_verifier_sha256": EXPECTED_FILE_SHA256[
            str(SOURCE_MANIFEST_VERIFIER_RELATIVE_PATH)
        ],
        "catalog_head_verifier_sha256": EXPECTED_FILE_SHA256[
            str(CATALOG_HEAD_VERIFIER_RELATIVE_PATH)
        ],
        "preflight_sql_sha256": EXPECTED_FILE_SHA256[
            str(PREFLIGHT_SQL_RELATIVE_PATH)
        ],
        "capture_sql_sha256": EXPECTED_FILE_SHA256[
            str(CAPTURE_SQL_RELATIVE_PATH)
        ],
        "profile_sha256": EXPECTED_FILE_SHA256[str(PROFILE_RELATIVE_PATH)],
        "artifact_schema_sha256": EXPECTED_FILE_SHA256[
            str(ARTIFACT_SCHEMA_RELATIVE_PATH)
        ],
        "authorization_schema_sha256": EXPECTED_FILE_SHA256[
            str(AUTHORIZATION_SCHEMA_RELATIVE_PATH)
        ],
        "tls_ca_certificate_sha256": tls_ca_certificate_sha256,
        "attempt_nonce_sha256": nonce_sha256,
        "single_attempt": True,
        "single_use_scope": "PROCESS_INVOCATION_ONLY",
        "database_session_authorized": True,
        "identity_capture_authorized": True,
        "schema_capture_authorized": True,
        "materialization_authorized": True,
        "prod_authorized": environment == "PROD",
        "database_mutation_authorized": False,
        "migration_application_authorized": False,
        "operational_authorization": False,
        "next_stage_authorized": False,
    }
    if any(values.get(key) != value for key, value in expected_scalars.items()):
        raise AuthorizationError(phase="AUTHORIZATION")
    valid_from = _parse_utc_second(values["valid_from_utc"])
    expires_at = _parse_utc_second(values["expires_at_utc"])
    if (
        expires_at <= valid_from
        or expires_at - valid_from > MAX_AUTHORIZATION_WINDOW
    ):
        raise AuthorizationError(phase="AUTHORIZATION")
    authorization = Authorization(
        record_sha256=_authorization_record_sha256(raw),
        values=values,
        valid_from=valid_from,
        expires_at=expires_at,
    )
    _ensure_authorization_window(authorization, now)
    return authorization


def _validate_contract_files(repository: Path) -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative, expected in EXPECTED_FILE_SHA256.items():
        digest = _sha256_file(repository / relative)
        if not hmac.compare_digest(digest, expected):
            raise ContractError(phase="CONTRACTS")
        observed[relative] = digest
    executor_digest = _sha256_file(
        repository / "backend" / "scripts" / SCRIPT_BASENAME
    )
    observed[SCRIPT_BASENAME] = executor_digest
    return observed


def _validate_bootstrap_primitive() -> None:
    """Detect drift; an external caller must still pin this bootstrap."""

    expected_path = REPO_ROOT / TRUSTED_SNAPSHOT_RELATIVE_PATH
    module_path = getattr(trusted_snapshot, "__file__", None)
    if (
        type(module_path) is not str
        or Path(module_path).resolve(strict=True) != expected_path.resolve(strict=True)
        or not hmac.compare_digest(
            _sha256_file(expected_path),
            EXPECTED_FILE_SHA256[str(TRUSTED_SNAPSHOT_RELATIVE_PATH)],
        )
    ):
        raise ContractError(phase="BOOTSTRAP_TRUST")


def _validate_python_runtime() -> None:
    """Enforce local runtime invariants; external pinning remains mandatory."""

    try:
        executable = Path(sys.executable)
        resolved = executable.resolve(strict=True)
        info = resolved.stat()
    except (OSError, RuntimeError):
        raise ContractError(phase="RUNTIME_TRUST") from None
    if (
        sys.flags.isolated != 1
        or not sys.flags.safe_path
        or sys.flags.no_user_site != 1
        or not sys.dont_write_bytecode
        or tuple(sys.version_info[:3]) != EXPECTED_PYTHON_VERSION
        or not executable.is_absolute()
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid not in {0, os.geteuid()}
        or info.st_mode & 0o022
    ):
        raise ContractError(phase="RUNTIME_TRUST")


def _snapshot_context_payload(
    *,
    snapshot: trusted_snapshot.RepositorySnapshot,
    staging_dir: Path,
    token: bytes,
) -> bytes:
    root_info = snapshot.root.lstat()
    repository_info = snapshot.repository.lstat()
    context: dict[str, Any] = {
        "contract": "PASTORAI_TRUSTED_REPOSITORY_EXECUTION_CONTEXT_V1",
        "source_git_sha": snapshot.git_sha,
        "snapshot_root": str(snapshot.root),
        "snapshot_repository": str(snapshot.repository),
        "staging_directory": str(staging_dir),
        "root_identity": list(_stat_identity(root_info)),
        "repository_identity": list(_stat_identity(repository_info)),
    }
    context_hmac = hmac.new(
        token, _canonical_json_bytes(context), hashlib.sha256
    ).hexdigest()
    context["context_hmac_sha256"] = context_hmac
    return _canonical_json_bytes(context) + b"\n"


def _validate_snapshot_context(
    context_raw: bytes,
    token: bytes,
    *,
    source_git_sha: str,
    staging_dir: Path,
) -> Path:
    if len(token) != 32 or not context_raw.endswith(b"\n"):
        raise ContractError(phase="SNAPSHOT_CONTEXT")
    context = _strict_json(
        context_raw[:-1], error=ContractError, phase="SNAPSHOT_CONTEXT"
    )
    expected_keys = {
        "contract",
        "source_git_sha",
        "snapshot_root",
        "snapshot_repository",
        "staging_directory",
        "root_identity",
        "repository_identity",
        "context_hmac_sha256",
    }
    if set(context) != expected_keys:
        raise ContractError(phase="SNAPSHOT_CONTEXT")
    received_hmac = context.pop("context_hmac_sha256")
    if (
        type(received_hmac) is not str
        or SHA256_RE.fullmatch(received_hmac) is None
        or not hmac.compare_digest(
            received_hmac,
            hmac.new(token, _canonical_json_bytes(context), hashlib.sha256).hexdigest(),
        )
    ):
        raise ContractError(phase="SNAPSHOT_CONTEXT")
    if (
        context.get("contract")
        != "PASTORAI_TRUSTED_REPOSITORY_EXECUTION_CONTEXT_V1"
        or context.get("source_git_sha") != source_git_sha
        or context.get("staging_directory") != str(staging_dir)
    ):
        raise ContractError(phase="SNAPSHOT_CONTEXT")
    try:
        root = Path(context["snapshot_root"])
        repository = Path(context["snapshot_repository"])
        root_info = root.lstat()
        repository_info = repository.lstat()
        script_info = SCRIPT_PATH.lstat()
        expected_script = repository / "backend" / "scripts" / SCRIPT_BASENAME
        if (
            root.parent != Path("/tmp")
            or repository.parent != root
            or repository.name != trusted_snapshot.SNAPSHOT_REPOSITORY_BASENAME
            or SCRIPT_PATH != expected_script
            or SCRIPT_PATH.resolve(strict=True) != expected_script.resolve(strict=True)
            or context.get("root_identity") != list(_stat_identity(root_info))
            or context.get("repository_identity")
            != list(_stat_identity(repository_info))
            or not stat.S_ISDIR(root_info.st_mode)
            or not stat.S_ISDIR(repository_info.st_mode)
            or stat.S_IMODE(root_info.st_mode) != 0o700
            or stat.S_IMODE(repository_info.st_mode) != 0o700
            or root_info.st_uid != os.geteuid()
            or root_info.st_gid != os.getegid()
            or repository_info.st_uid != os.geteuid()
            or repository_info.st_gid != os.getegid()
            or not stat.S_ISREG(script_info.st_mode)
            or stat.S_IMODE(script_info.st_mode) != 0o600
            or script_info.st_uid != os.geteuid()
            or script_info.st_gid != os.getegid()
            or script_info.st_nlink != 1
            or (repository / ".git").exists()
        ):
            raise ContractError(phase="SNAPSHOT_CONTEXT")
        staging_info = staging_dir.lstat()
        if (
            staging_dir.parent != root
            or staging_dir.name != STAGING_BASENAME
            or not stat.S_ISDIR(staging_info.st_mode)
            or stat.S_IMODE(staging_info.st_mode) != 0o700
            or staging_info.st_uid != os.geteuid()
            or staging_info.st_gid != os.getegid()
            or any(staging_dir.iterdir())
        ):
            raise ContractError(phase="SNAPSHOT_CONTEXT")
    except ExecutorError:
        raise
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        raise ContractError(phase="SNAPSHOT_CONTEXT") from None
    return repository


def _minimal_child_environment() -> dict[str, str]:
    return {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.defpath,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def _assert_clean_database_environment(environ: Mapping[str, str]) -> None:
    for name in environ:
        upper = name.upper()
        if (
            upper.startswith(("PG", "SSL", "OPENSSL"))
            or upper in RELEVANT_DATABASE_ENV_NAMES
        ):
            raise PrivateInputError(phase="PRIVATE_INPUTS")


def _witness_output_directory(path: Path) -> tuple[int, ...]:
    try:
        info = path.lstat()
        if (
            not path.is_absolute()
            or not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o700
            or info.st_uid != os.geteuid()
            or info.st_gid != os.getegid()
            or any(path.iterdir())
        ):
            raise PrivateInputError(phase="OUTPUT_DIRECTORY")
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if _stat_identity(opened) != _stat_identity(info):
                raise PrivateInputError(phase="OUTPUT_DIRECTORY")
        finally:
            os.close(descriptor)
        return _stat_identity(info)
    except ExecutorError:
        raise
    except OSError:
        raise PrivateInputError(phase="OUTPUT_DIRECTORY") from None


def _revalidate_output_directory(path: Path, witness: tuple[int, ...]) -> None:
    if _stat_identity(path.lstat()) != witness or any(path.iterdir()):
        raise CleanupError(phase="OUTPUT_PUBLICATION")


def _validate_operational_dsn(
    raw: bytes,
    *,
    expected_project_ref_sha256: str,
    expected_database_name_sha256: str,
    preflight: Any,
    test_only_allow_loopback: object | None = None,
) -> tuple[str, Any]:
    dsn = preflight._decode_dsn(raw)
    try:
        parsed = preflight.extensions.parse_dsn(dsn)
    except Exception:
        raise TargetError(phase="TARGET") from None
    loopback_test = (
        test_only_allow_loopback is _TEST_ONLY_LOOPBACK_SENTINEL
        and parsed.get("host") in {"127.0.0.1", "::1"}
    )
    if parsed.get("port") != "5432" and not loopback_test:
        # Transaction-pooler port 6543 cannot prove one stable session across
        # the identity and capture transactions.
        raise TargetError(phase="TARGET")
    try:
        target = preflight._validate_dsn(
            dsn,
            expected_project_ref_sha256=expected_project_ref_sha256,
            expected_database_name_sha256=expected_database_name_sha256,
            test_only_allow_loopback=(
                preflight._TEST_ONLY_LOOPBACK_SENTINEL
                if loopback_test
                else None
            ),
        )
    except Exception:
        raise TargetError(phase="TARGET") from None
    return dsn, target


def _run_identity_transaction(
    connection: Any,
    *,
    target: Any,
    sql_contract: Any,
    preflight: Any,
) -> dict[str, Any]:
    cursor: Any | None = None
    transaction_open = False
    identity: dict[str, Any] | None = None
    primary: BaseException | None = None
    try:
        if connection.autocommit is not True:
            raise DatabaseError(phase="IDENTITY_TRANSACTION")
        cursor = connection.cursor()
        cursor.execute(sql_contract.statements[0])
        transaction_open = True
        for statement in sql_contract.statements[1:-1]:
            cursor.execute(statement)
            preflight._fetch_single_value(cursor)
        cursor.execute(sql_contract.statements[-1])
        raw_identity = preflight._fetch_single_value(cursor)
        identity = preflight._strict_json_object(raw_identity)
        preflight._validate_identity(identity, target)
        cursor.execute(sql_contract.rollback)
        transaction_open = False
        if (
            connection.get_transaction_status()
            != preflight.extensions.TRANSACTION_STATUS_IDLE
        ):
            raise CleanupError(phase="IDENTITY_ROLLBACK")
    except ExecutorError as exc:
        primary = exc
        raise
    except Exception as exc:
        primary = exc
        raise DatabaseError(phase="IDENTITY_TRANSACTION") from None
    finally:
        cleanup_failed = False
        if cursor is not None and transaction_open:
            try:
                cursor.execute(sql_contract.rollback)
                transaction_open = False
            except Exception:
                try:
                    connection.rollback()
                    transaction_open = False
                except Exception:
                    cleanup_failed = True
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                cleanup_failed = True
        try:
            if (
                connection.get_transaction_status()
                != preflight.extensions.TRANSACTION_STATUS_IDLE
            ):
                cleanup_failed = True
        except Exception:
            cleanup_failed = True
        if cleanup_failed:
            raise CleanupError(phase="IDENTITY_ROLLBACK") from primary
    if identity is None:
        raise DatabaseError(phase="IDENTITY_TRANSACTION")
    return identity


def _target_descriptor(
    authorization: Authorization, *, environment: str
) -> dict[str, Any]:
    return {
        "authorization_record_sha256": authorization.record_sha256,
        "environment": environment,
        "expected_database_name_sha256": authorization.values[
            "expected_database_name_sha256"
        ],
        "expected_project_ref_sha256": authorization.values[
            "expected_project_ref_sha256"
        ],
        "expected_system_identifier_sha256": authorization.values[
            "expected_system_identifier_sha256"
        ],
        "target_binding_contract": TARGET_BINDING_CONTRACT,
    }


def _connection_backend_pid(connection: Any) -> int:
    try:
        value = connection.get_backend_pid()
    except Exception:
        raise DatabaseError(phase="SESSION_CONTINUITY") from None
    if type(value) is not int or value < 1:
        raise DatabaseError(phase="SESSION_CONTINUITY")
    return value


def _safe_unlink_artifact(
    output_dir: Path,
    basename: str,
    *,
    expected_identity: tuple[int, ...],
) -> bool:
    try:
        info = output_dir.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o700
            or info.st_uid != os.geteuid()
            or info.st_gid != os.getegid()
        ):
            return False
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        directory_fd = os.open(output_dir, flags)
        try:
            target = os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(target.st_mode)
                or target.st_uid != os.geteuid()
                or target.st_gid != os.getegid()
                or target.st_nlink != 1
                or _stat_identity(target) != expected_identity
            ):
                return False
            os.unlink(basename, dir_fd=directory_fd)
            os.fsync(directory_fd)
            return True
        finally:
            os.close(directory_fd)
    except OSError:
        return False


def _publish_artifact(
    *,
    environment: str,
    staging_dir: Path,
    output_dir: Path,
    output_witness: tuple[int, ...],
    state: ExecutionState,
    materializer: Any,
    verifier: Any,
) -> tuple[Path, tuple[int, ...]]:
    basename = materializer.ARTIFACT_BASENAMES[environment]
    staged_path = staging_dir / basename
    published_identity: tuple[int, ...] | None = None
    try:
        artifact = materializer._read_private_json(
            staged_path, materializer.MAX_OUTPUT_BYTES
        )
        profile = materializer._load_contracts()
        verifier._validate_artifact(dict(artifact), environment, profile)
        _revalidate_output_directory(output_dir, output_witness)
        published = materializer._atomic_write(
            output_dir,
            basename,
            dict(artifact),
            allowed_existing=set(),
        )
        published_info = published.lstat()
        published_identity = _stat_identity(published_info)
        state.artifact_published = True
        reread = materializer._read_private_json(
            published, materializer.MAX_OUTPUT_BYTES
        )
        verifier._validate_artifact(dict(reread), environment, profile)
        if dict(reread) != dict(artifact):
            raise CleanupError(phase="OUTPUT_PUBLICATION")
        return published, published_identity
    except ExecutorError:
        if published_identity is not None:
            if _safe_unlink_artifact(
                output_dir,
                basename,
                expected_identity=published_identity,
            ):
                state.artifact_published = False
        raise
    except Exception:
        if published_identity is not None:
            if _safe_unlink_artifact(
                output_dir,
                basename,
                expected_identity=published_identity,
            ):
                state.artifact_published = False
        raise CleanupError(phase="OUTPUT_PUBLICATION") from None


def _load_child_modules(repository: Path) -> tuple[Any, Any, Any, Any]:
    scripts_directory = repository / "backend" / "scripts"
    short_module_names = (
        "preflight_migration_history_environment_identity",
        "materialize_migration_history_environment_attestation",
        "verify_migration_history_environment_attestation",
        "derive_migration_history_canonical_schema",
        "verify_migration_history_schema_expectation_manifest",
        "verify_migration_catalog_head",
    )
    qualified_module_names = tuple(
        f"scripts.{name}" for name in short_module_names
    )
    controlled_module_names = ("scripts", *qualified_module_names)
    try:
        if (
            sys.flags.isolated != 1
            or not sys.flags.safe_path
            or any(name in sys.modules for name in short_module_names)
            or any(
                name == "scripts" or name.startswith("scripts.")
                for name in sys.modules
            )
            or any(
                name == "psycopg2" or name.startswith("psycopg2.")
                for name in sys.modules
            )
        ):
            raise ImportError
        import psycopg2
        from psycopg2 import _psycopg, extensions

        package = types.ModuleType("scripts")
        package.__package__ = "scripts"
        package.__path__ = [str(scripts_directory)]
        sys.modules["scripts"] = package

        loaded: dict[str, Any] = {}
        for short_name in (
            "verify_migration_catalog_head",
            "verify_migration_history_schema_expectation_manifest",
            "derive_migration_history_canonical_schema",
            "materialize_migration_history_environment_attestation",
            "verify_migration_history_environment_attestation",
            "preflight_migration_history_environment_identity",
        ):
            qualified_name = f"scripts.{short_name}"
            module_path = scripts_directory / f"{short_name}.py"
            specification = importlib.util.spec_from_file_location(
                qualified_name, module_path
            )
            if specification is None or specification.loader is None:
                raise ImportError
            module = importlib.util.module_from_spec(specification)
            sys.modules[qualified_name] = module
            setattr(package, short_name, module)
            specification.loader.exec_module(module)
            loaded[short_name] = module

        preflight = loaded["preflight_migration_history_environment_identity"]
        materializer = loaded[
            "materialize_migration_history_environment_attestation"
        ]
        verifier = loaded["verify_migration_history_environment_attestation"]
        canonical = loaded["derive_migration_history_canonical_schema"]
        source_manifest = loaded[
            "verify_migration_history_schema_expectation_manifest"
        ]
        catalog_head = loaded["verify_migration_catalog_head"]
    except Exception:
        for name in controlled_module_names:
            sys.modules.pop(name, None)
        raise ContractError(phase="RUNTIME_IMPORTS") from None
    try:
        distribution_version = importlib.metadata.version("psycopg2-binary")
        runtime_root = Path(sys.prefix).resolve(strict=True)
    except (importlib.metadata.PackageNotFoundError, OSError, RuntimeError):
        raise ContractError(phase="RUNTIME_IMPORTS") from None
    if (
        getattr(psycopg2, "__version__", "").split()[0]
        != EXPECTED_PSYCOPG2_VERSION
        or distribution_version != EXPECTED_PSYCOPG2_VERSION
        or getattr(psycopg2, "__libpq_version__", 0) // 10_000 != 17
        or extensions.libpq_version() // 10_000 != 17
    ):
        raise ContractError(phase="RUNTIME_IMPORTS")
    for module in (psycopg2, _psycopg):
        module_path = getattr(module, "__file__", None)
        if type(module_path) is not str:
            raise ContractError(phase="RUNTIME_IMPORTS")
        try:
            resolved = Path(module_path).resolve(strict=True)
            info = resolved.stat()
            if (
                not resolved.is_relative_to(runtime_root)
                or not stat.S_ISREG(info.st_mode)
                or info.st_uid not in {0, os.geteuid()}
                or info.st_mode & 0o022
            ):
                raise ContractError(phase="RUNTIME_IMPORTS")
        except (OSError, RuntimeError):
            raise ContractError(phase="RUNTIME_IMPORTS") from None
    expected_modules = {
        preflight: repository / PREFLIGHT_RUNNER_RELATIVE_PATH,
        materializer: repository / MATERIALIZER_RELATIVE_PATH,
        verifier: repository / VERIFIER_RELATIVE_PATH,
        canonical: repository / CANONICAL_DERIVATION_RELATIVE_PATH,
        source_manifest: repository / SOURCE_MANIFEST_VERIFIER_RELATIVE_PATH,
        catalog_head: repository / CATALOG_HEAD_VERIFIER_RELATIVE_PATH,
        trusted_snapshot: repository / TRUSTED_SNAPSHOT_RELATIVE_PATH,
    }
    for module, expected_path in expected_modules.items():
        module_path = getattr(module, "__file__", None)
        if (
            type(module_path) is not str
            or Path(module_path).resolve(strict=True)
            != expected_path.resolve(strict=True)
        ):
            raise ContractError(phase="RUNTIME_IMPORTS")
    if (
        preflight.psycopg2 is not psycopg2
        or preflight.extensions is not extensions
        or materializer.canonical is not canonical
        or verifier.materializer is not materializer
        or canonical.source_manifest is not source_manifest
        or source_manifest.catalog_head is not catalog_head
    ):
        raise ContractError(phase="RUNTIME_IMPORTS")
    return psycopg2, preflight, materializer, verifier


def _execute_child(
    args: argparse.Namespace,
    *,
    state: ExecutionState | None = None,
    connect: Callable[..., Any] | None = None,
    now: datetime | None = None,
    test_only_allow_loopback: object | None = None,
) -> tuple[int, ExecutionState]:
    state = state or ExecutionState(args.environment, args.source_git_sha)
    state.phase = "SNAPSHOT_CONTEXT"
    context_raw = _read_private_fd(args.snapshot_context_fd, MAX_CONTEXT_BYTES)
    token_buffer = bytearray(_read_private_fd(args.launch_token_fd, 32))
    _close_fds((args.snapshot_context_fd, args.launch_token_fd))
    try:
        repository = _validate_snapshot_context(
            context_raw,
            bytes(token_buffer),
            source_git_sha=args.source_git_sha,
            staging_dir=args.staging_dir,
        )
    finally:
        token_buffer[:] = b"\x00" * len(token_buffer)
    state.phase = "CONTRACTS"
    digests = _validate_contract_files(repository)
    psycopg2, preflight, materializer, verifier = _load_child_modules(repository)
    connector = psycopg2.connect if connect is None else connect
    _assert_clean_database_environment(os.environ)
    output_witness = _witness_output_directory(args.output_dir)

    descriptors = (
        args.database_url_fd,
        args.tls_ca_cert_fd,
        args.authorization_record_fd,
        args.hmac_key_fd,
        args.nonce_fd,
    )
    if len(set(descriptors)) != len(descriptors) or any(item < 3 for item in descriptors):
        raise UsageError(phase="ARGUMENTS")

    state.phase = "PRIVATE_INPUTS"
    dsn_raw = b""
    authorization_raw = bytearray()
    key_buffer = bytearray()
    nonce_buffer = bytearray()
    try:
        ca_witness = preflight._witness_tls_ca_certificate_fd(
            args.tls_ca_cert_fd
        )
        try:
            dsn_raw = _read_private_fd(args.database_url_fd, MAX_DSN_BYTES)
            authorization_raw = bytearray(
                _read_private_fd(
                    args.authorization_record_fd, MAX_AUTHORIZATION_BYTES
                )
            )
            key_buffer = bytearray(
                _read_private_fd(args.hmac_key_fd, MAX_KEY_BYTES)
            )
            nonce_buffer = bytearray(
                _read_private_fd(args.nonce_fd, MAX_NONCE_BYTES)
            )
        finally:
            _close_fds(
                (
                    args.database_url_fd,
                    args.authorization_record_fd,
                    args.hmac_key_fd,
                    args.nonce_fd,
                )
            )
        if not 32 <= len(key_buffer) <= 64 or len(nonce_buffer) != 32:
            raise PrivateInputError(phase="PRIVATE_INPUTS")
    except BaseException:
        authorization_raw[:] = b"\x00" * len(authorization_raw)
        key_buffer[:] = b"\x00" * len(key_buffer)
        nonce_buffer[:] = b"\x00" * len(nonce_buffer)
        dsn_raw = b""
        _close_fds(descriptors)
        raise

    connection: Any | None = None
    artifact_path: Path | None = None
    artifact_identity: tuple[int, ...] | None = None
    primary_error: BaseException | None = None
    try:
        state.phase = "AUTHORIZATION"
        authorization = _validate_authorization(
            bytes(authorization_raw),
            environment=args.environment,
            confirmation=args.confirmation,
            source_git_sha=args.source_git_sha,
            executor_sha256=digests[SCRIPT_BASENAME],
            tls_ca_certificate_sha256=ca_witness.sha256,
            nonce_sha256=hashlib.sha256(nonce_buffer).hexdigest(),
            now=now,
        )
        state.phase = "TARGET"
        dsn, target = _validate_operational_dsn(
            dsn_raw,
            expected_project_ref_sha256=authorization.values[
                "expected_project_ref_sha256"
            ],
            expected_database_name_sha256=authorization.values[
                "expected_database_name_sha256"
            ],
            preflight=preflight,
            test_only_allow_loopback=test_only_allow_loopback,
        )
        if not hmac.compare_digest(
            authorization.values["expected_database_name_sha256"],
            _component_sha256("DATABASE_NAME", "postgres"),
        ):
            raise TargetError(phase="TARGET")
        _ensure_authorization_window(authorization, now)
        preflight._revalidate_tls_ca_certificate_fd(ca_witness)

        state.phase = "CONNECT_TLS_AUTH"
        try:
            connection = connector(
                dsn,
                application_name=(
                    "pastorai_migration_environment_attestation_v2_"
                    f"{args.environment.casefold()}"
                ),
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                sslmode="verify-full",
                sslrootcert=f"/proc/self/fd/{args.tls_ca_cert_fd}",
            )
        except Exception:
            raise DatabaseError(phase="CONNECT_TLS_AUTH") from None
        state.connection_opened = True
        state.connection_closed = False
        if (
            type(connection.server_version) is not int
            or connection.server_version // 10_000 != 17
        ):
            raise DatabaseError(phase="SERVER_VERSION")
        connection.autocommit = True
        backend_pid = _connection_backend_pid(connection)

        state.phase = "IDENTITY_TRANSACTION"
        identity = _run_identity_transaction(
            connection,
            target=target,
            sql_contract=preflight._load_sql_contract(),
            preflight=preflight,
        )
        state.identity_rollback_confirmed = True
        if _connection_backend_pid(connection) != backend_pid:
            raise DatabaseError(phase="SESSION_CONTINUITY")
        observed_system_identifier = identity["system_identifier"]
        if not hmac.compare_digest(
            authorization.values["expected_system_identifier_sha256"],
            _component_sha256("SYSTEM_IDENTIFIER", observed_system_identifier),
        ):
            raise TargetError(phase="IDENTITY_TRANSACTION")
        preflight._revalidate_tls_ca_certificate_fd(ca_witness)
        _ensure_authorization_window(authorization, now)

        state.phase = "PRE_CAPTURE_BINDING"
        target_descriptor = _target_descriptor(
            authorization, environment=args.environment
        )
        with ExitStack() as stack:
            expected_target_fd = stack.enter_context(
                _pipe_payload(_canonical_json_bytes(target_descriptor))
            )
            identity_fd = stack.enter_context(
                _pipe_payload(_canonical_json_bytes(identity))
            )
            key_fd = stack.enter_context(_pipe_payload(bytes(key_buffer)))
            materializer.bind_target(
                environment=args.environment,
                authorization_record=authorization.record_sha256,
                nonce=bytes(nonce_buffer).hex(),
                expected_target_fd=expected_target_fd,
                identity_fd=identity_fd,
                hmac_key_fd=key_fd,
                output_dir=args.staging_dir,
            )

        state.phase = "CAPTURE_TRANSACTION"
        try:
            metadata, invariant_envelopes = materializer.capture_one_snapshot(
                connection
            )
        except Exception:
            raise DatabaseError(phase="CAPTURE_TRANSACTION") from None
        state.capture_executed = True
        if (
            connection.get_transaction_status()
            != preflight.extensions.TRANSACTION_STATUS_IDLE
        ):
            raise CleanupError(phase="CAPTURE_ROLLBACK")
        state.capture_rollback_confirmed = True
        session_proof = metadata.get("session_proof")
        if (
            type(session_proof) is not dict
            or session_proof.get("backend_pid") != backend_pid
            or metadata.get("system_identifier") != identity["system_identifier"]
            or metadata.get("database_name") != identity["database_name"]
            or _connection_backend_pid(connection) != backend_pid
        ):
            raise DatabaseError(phase="SESSION_CONTINUITY")
        state.identity_capture_same_connection = True
        preflight._revalidate_tls_ca_certificate_fd(ca_witness)
        _ensure_authorization_window(authorization, now)

        state.phase = "CONNECTION_CLOSE"
        try:
            connection.close()
        except Exception:
            raise CleanupError(phase="CONNECTION_CLOSE") from None
        if getattr(connection, "closed", 0) in {0, False, None}:
            raise CleanupError(phase="CONNECTION_CLOSE")
        state.connection_closed = True
        connection = None
        preflight._revalidate_tls_ca_certificate_fd(ca_witness)

        state.phase = "MATERIALIZATION"
        with ExitStack() as stack:
            expected_target_fd = stack.enter_context(
                _pipe_payload(_canonical_json_bytes(target_descriptor))
            )
            metadata_fd = stack.enter_context(
                _pipe_payload(_canonical_json_bytes(metadata))
            )
            key_fd = stack.enter_context(_pipe_payload(bytes(key_buffer)))
            invariant_fds: dict[str, int] = {}
            for envelope in invariant_envelopes:
                identifier = envelope.get("result", {}).get("id")
                if type(identifier) is not str or identifier in invariant_fds:
                    raise DatabaseError(phase="MATERIALIZATION")
                invariant_fds[identifier] = stack.enter_context(
                    _pipe_payload(_canonical_json_bytes(envelope))
                )
            _staged_path, blocked = materializer.materialize(
                environment=args.environment,
                authorization_record=authorization.record_sha256,
                nonce=bytes(nonce_buffer).hex(),
                expected_target_fd=expected_target_fd,
                metadata_capture_fd=metadata_fd,
                hmac_key_fd=key_fd,
                invariant_result_fds=invariant_fds,
                output_dir=args.staging_dir,
            )
        if blocked is not True:
            raise ContractError(phase="MATERIALIZATION")
        state.materialization_executed = True
        _ensure_authorization_window(authorization, now)

        state.phase = "OUTPUT_PUBLICATION"
        artifact_path, artifact_identity = _publish_artifact(
            environment=args.environment,
            staging_dir=args.staging_dir,
            output_dir=args.output_dir,
            output_witness=output_witness,
            state=state,
            materializer=materializer,
            verifier=verifier,
        )
        state.artifact_published = True
        state.phase = "DONE_BLOCKED"
        return EvidenceMaterializedBlocked.exit_code, state
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        authorization_raw[:] = b"\x00" * len(authorization_raw)
        key_buffer[:] = b"\x00" * len(key_buffer)
        nonce_buffer[:] = b"\x00" * len(nonce_buffer)
        dsn_raw = b""
        cleanup_failed = False
        if connection is not None:
            try:
                if (
                    connection.get_transaction_status()
                    != preflight.extensions.TRANSACTION_STATUS_IDLE
                ):
                    connection.rollback()
            except Exception:
                cleanup_failed = True
            try:
                connection.close()
            except Exception:
                cleanup_failed = True
            if getattr(connection, "closed", 0) in {0, False, None}:
                cleanup_failed = True
            else:
                state.connection_closed = True
        try:
            preflight._revalidate_tls_ca_certificate_fd(ca_witness)
        except Exception:
            cleanup_failed = True
        _close_fds((args.tls_ca_cert_fd,))
        if cleanup_failed:
            if artifact_path is not None and artifact_identity is not None:
                removed = _safe_unlink_artifact(
                    args.output_dir,
                    artifact_path.name,
                    expected_identity=artifact_identity,
                )
                if removed:
                    state.artifact_published = False
            raise CleanupError(phase="CONNECTION_CLOSE") from primary_error


def _deny_lines(state: ExecutionState) -> tuple[str, ...]:
    return (
        f"ENVIRONMENT={state.environment}",
        f"SOURCE_GIT_SHA={state.source_git_sha}",
        f"BOOTSTRAP_TRUST_REQUIREMENT={BOOTSTRAP_TRUST_REQUIREMENT}",
        f"AUTHORIZATION_TRUST_REQUIREMENT={AUTHORIZATION_TRUST_REQUIREMENT}",
        f"RUNTIME_TRUST_REQUIREMENT={RUNTIME_TRUST_REQUIREMENT}",
        "DATABASE_MUTATION_AUTHORIZED=false",
        "MIGRATION_APPLICATION_AUTHORIZED=false",
        "OPERATIONAL_AUTHORIZATION=false",
        "NEXT_STAGE_AUTHORIZED=false",
        f"CAPTURE_EXECUTED={str(state.capture_executed).lower()}",
        "IDENTITY_CAPTURE_SAME_CONNECTION="
        f"{str(state.identity_capture_same_connection).lower()}",
        f"MATERIALIZATION_EXECUTED={str(state.materialization_executed).lower()}",
        f"IDENTITY_ROLLBACK_CONFIRMED={str(state.identity_rollback_confirmed).lower()}",
        f"CAPTURE_ROLLBACK_CONFIRMED={str(state.capture_rollback_confirmed).lower()}",
        f"CONNECTION_CLOSED={str(state.connection_closed).lower()}",
        f"ARTIFACT_PUBLISHED={str(state.artifact_published).lower()}",
    )


def _emit_result(state: ExecutionState, result: str) -> None:
    for line in _deny_lines(state):
        print(line)
    print(f"EXECUTION_PHASE={state.phase}")
    if result != EvidenceMaterializedBlocked.reason:
        print(f"FAILURE_PHASE={state.phase}")
    print("ENVIRONMENT_ATTESTATION_COMPLETE=false")
    print(f"RESULT={result}")


def _validate_child_output(
    raw: bytes,
    *,
    expected_environment: str,
    expected_source_git_sha: str,
    exit_code: int,
) -> tuple[str, dict[str, str]]:
    if not raw or len(raw) > MAX_CHILD_OUTPUT_BYTES:
        raise CleanupError(phase="CHILD_OUTPUT")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise CleanupError(phase="CHILD_OUTPUT") from None
    if not text.endswith("\n"):
        raise CleanupError(phase="CHILD_OUTPUT")
    lines = text.splitlines()
    if not lines or any(SAFE_OUTPUT_LINE_RE.fullmatch(line) is None for line in lines):
        raise CleanupError(phase="CHILD_OUTPUT")
    lowered = text.casefold()
    if any(fragment in lowered for fragment in ("password", "postgresql://", "postgres://")):
        raise CleanupError(phase="CHILD_OUTPUT")
    if exit_code not in CHILD_RESULT_BY_EXIT_CODE:
        raise CleanupError(phase="CHILD_OUTPUT")
    values: dict[str, str] = {}
    for line in lines:
        key, value = line.split("=", 1)
        if key in values:
            raise CleanupError(phase="CHILD_OUTPUT")
        values[key] = value
    expected_keys = {
        "ENVIRONMENT",
        "SOURCE_GIT_SHA",
        "BOOTSTRAP_TRUST_REQUIREMENT",
        "AUTHORIZATION_TRUST_REQUIREMENT",
        "RUNTIME_TRUST_REQUIREMENT",
        "DATABASE_MUTATION_AUTHORIZED",
        "MIGRATION_APPLICATION_AUTHORIZED",
        "OPERATIONAL_AUTHORIZATION",
        "NEXT_STAGE_AUTHORIZED",
        "CAPTURE_EXECUTED",
        "IDENTITY_CAPTURE_SAME_CONNECTION",
        "MATERIALIZATION_EXECUTED",
        "IDENTITY_ROLLBACK_CONFIRMED",
        "CAPTURE_ROLLBACK_CONFIRMED",
        "CONNECTION_CLOSED",
        "ARTIFACT_PUBLISHED",
        "EXECUTION_PHASE",
        "ENVIRONMENT_ATTESTATION_COMPLETE",
        "RESULT",
    }
    if exit_code != EvidenceMaterializedBlocked.exit_code:
        expected_keys.add("FAILURE_PHASE")
    if set(values) != expected_keys:
        raise CleanupError(phase="CHILD_OUTPUT")
    fixed = {
        "ENVIRONMENT": expected_environment,
        "SOURCE_GIT_SHA": expected_source_git_sha,
        "BOOTSTRAP_TRUST_REQUIREMENT": BOOTSTRAP_TRUST_REQUIREMENT,
        "AUTHORIZATION_TRUST_REQUIREMENT": AUTHORIZATION_TRUST_REQUIREMENT,
        "RUNTIME_TRUST_REQUIREMENT": RUNTIME_TRUST_REQUIREMENT,
        "DATABASE_MUTATION_AUTHORIZED": "false",
        "MIGRATION_APPLICATION_AUTHORIZED": "false",
        "OPERATIONAL_AUTHORIZATION": "false",
        "NEXT_STAGE_AUTHORIZED": "false",
        "ENVIRONMENT_ATTESTATION_COMPLETE": "false",
        "RESULT": CHILD_RESULT_BY_EXIT_CODE[exit_code],
    }
    if any(values.get(key) != value for key, value in fixed.items()):
        raise CleanupError(phase="CHILD_OUTPUT")
    boolean_keys = {
        "CAPTURE_EXECUTED",
        "IDENTITY_CAPTURE_SAME_CONNECTION",
        "MATERIALIZATION_EXECUTED",
        "IDENTITY_ROLLBACK_CONFIRMED",
        "CAPTURE_ROLLBACK_CONFIRMED",
        "CONNECTION_CLOSED",
        "ARTIFACT_PUBLISHED",
    }
    if any(values[key] not in {"true", "false"} for key in boolean_keys):
        raise CleanupError(phase="CHILD_OUTPUT")
    if exit_code == EvidenceMaterializedBlocked.exit_code:
        success = {
            "CAPTURE_EXECUTED": "true",
            "IDENTITY_CAPTURE_SAME_CONNECTION": "true",
            "MATERIALIZATION_EXECUTED": "true",
            "IDENTITY_ROLLBACK_CONFIRMED": "true",
            "CAPTURE_ROLLBACK_CONFIRMED": "true",
            "CONNECTION_CLOSED": "true",
            "ARTIFACT_PUBLISHED": "true",
            "EXECUTION_PHASE": "DONE_BLOCKED",
        }
        if any(values.get(key) != value for key, value in success.items()):
            raise CleanupError(phase="CHILD_OUTPUT")
    else:
        if (
            values.get("FAILURE_PHASE") != values.get("EXECUTION_PHASE")
            or values.get("EXECUTION_PHASE") == "DONE_BLOCKED"
            or (
                exit_code != CleanupError.exit_code
                and values.get("ARTIFACT_PUBLISHED") != "false"
            )
        ):
            raise CleanupError(phase="CHILD_OUTPUT")
    return text, values


def _apply_child_report(state: ExecutionState, values: Mapping[str, str]) -> None:
    state.capture_executed = values["CAPTURE_EXECUTED"] == "true"
    state.identity_capture_same_connection = (
        values["IDENTITY_CAPTURE_SAME_CONNECTION"] == "true"
    )
    state.materialization_executed = values["MATERIALIZATION_EXECUTED"] == "true"
    state.identity_rollback_confirmed = (
        values["IDENTITY_ROLLBACK_CONFIRMED"] == "true"
    )
    state.capture_rollback_confirmed = (
        values["CAPTURE_ROLLBACK_CONFIRMED"] == "true"
    )
    state.connection_closed = values["CONNECTION_CLOSED"] == "true"
    state.artifact_published = values["ARTIFACT_PUBLISHED"] == "true"


def _create_staging_directory(snapshot: trusted_snapshot.RepositorySnapshot) -> Path:
    staging = snapshot.root / STAGING_BASENAME
    try:
        os.mkdir(staging, 0o700)
        staging.chmod(0o700)
    except OSError:
        raise ContractError(phase="SNAPSHOT") from None
    return staging


def _public_execute(args: argparse.Namespace) -> int:
    state = ExecutionState(args.environment, args.source_git_sha)
    snapshot: trusted_snapshot.RepositorySnapshot | None = None
    output_witness: tuple[int, ...] | None = None
    input_fds = (
        args.database_url_fd,
        args.tls_ca_cert_fd,
        args.authorization_record_fd,
        args.hmac_key_fd,
        args.nonce_fd,
    )

    def release_snapshot() -> bool:
        nonlocal snapshot
        if snapshot is None:
            return True
        current = snapshot
        snapshot = None
        try:
            current.cleanup()
        except Exception:
            return False
        return True

    def emit_failure(error: ExecutorError, *, cleanup_failed: bool = False) -> int:
        if output_witness is not None:
            try:
                current = _stat_identity(args.output_dir.lstat())
                if current != output_witness or any(args.output_dir.iterdir()):
                    state.artifact_published = True
            except OSError:
                state.artifact_published = True
        state.phase = error.phase
        if cleanup_failed:
            print("SNAPSHOT_CLEANUP_CONFIRMED=false")
        _emit_result(state, error.reason)
        return error.exit_code

    try:
        _validate_bootstrap_primitive()
        if len(set(input_fds)) != len(input_fds) or any(item < 3 for item in input_fds):
            raise UsageError(phase="ARGUMENTS")
        output_witness = _witness_output_directory(args.output_dir)
        state.phase = "SNAPSHOT"
        snapshot = trusted_snapshot.create_trusted_repository_snapshot(
            repository_root=REPO_ROOT,
            git_sha=args.source_git_sha,
        )
        staging = _create_staging_directory(snapshot)
        token = bytearray(os.urandom(32))
        with ExitStack() as stack:
            context_fd = stack.enter_context(
                _pipe_payload(
                    _snapshot_context_payload(
                        snapshot=snapshot,
                        staging_dir=staging,
                        token=bytes(token),
                    )
                )
            )
            token_fd = stack.enter_context(_pipe_payload(bytes(token)))
            child_script = (
                snapshot.repository / "backend" / "scripts" / SCRIPT_BASENAME
            )
            child_args = [
                sys.executable,
                "-I",
                "-B",
                str(child_script),
                INTERNAL_CHILD_COMMAND,
                "--source-git-sha",
                args.source_git_sha,
                "--environment",
                args.environment,
                "--database-url-fd",
                str(args.database_url_fd),
                "--tls-ca-cert-fd",
                str(args.tls_ca_cert_fd),
                "--authorization-record-fd",
                str(args.authorization_record_fd),
                "--hmac-key-fd",
                str(args.hmac_key_fd),
                "--nonce-fd",
                str(args.nonce_fd),
                "--output-dir",
                str(args.output_dir),
                "--confirmation",
                args.confirmation,
                "--snapshot-context-fd",
                str(context_fd),
                "--launch-token-fd",
                str(token_fd),
                "--staging-dir",
                str(staging),
            ]
            pass_fds = tuple(sorted(set(input_fds + (context_fd, token_fd))))
            try:
                completed = subprocess.run(
                    child_args,
                    cwd=snapshot.repository,
                    env=_minimal_child_environment(),
                    pass_fds=pass_fds,
                    close_fds=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=CHILD_TIMEOUT_SECONDS,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                raise CleanupError(phase="CHILD_EXECUTION") from None
            finally:
                token[:] = b"\x00" * len(token)
        if completed.stderr:
            raise CleanupError(phase="CHILD_OUTPUT")
        child_code = completed.returncode
        child_output, child_report = _validate_child_output(
            completed.stdout,
            expected_environment=args.environment,
            expected_source_git_sha=args.source_git_sha,
            exit_code=child_code,
        )
        _apply_child_report(state, child_report)
        state.phase = "SNAPSHOT_CLEANUP"
        if not release_snapshot():
            return emit_failure(
                CleanupError(phase="SNAPSHOT_CLEANUP"), cleanup_failed=True
            )
        print(child_output, end="")
        print("SNAPSHOT_CLEANUP_CONFIRMED=true")
        return child_code
    except trusted_snapshot.CleanupError:
        snapshot = None
        return emit_failure(
            CleanupError(phase="SNAPSHOT_CLEANUP"), cleanup_failed=True
        )
    except trusted_snapshot.SnapshotError:
        if not release_snapshot():
            return emit_failure(
                CleanupError(phase="SNAPSHOT_CLEANUP"), cleanup_failed=True
            )
        return emit_failure(ContractError(phase="SNAPSHOT"))
    except ExecutorError as exc:
        if not release_snapshot():
            return emit_failure(
                CleanupError(phase="SNAPSHOT_CLEANUP"), cleanup_failed=True
            )
        return emit_failure(exc)
    except Exception:
        if not release_snapshot():
            return emit_failure(
                CleanupError(phase="SNAPSHOT_CLEANUP"), cleanup_failed=True
            )
        return emit_failure(ExecutorError(phase="INTERNAL"))
    finally:
        _close_fds(input_fds)


def _describe(source_git_sha: str) -> int:
    snapshot: trusted_snapshot.RepositorySnapshot | None = None

    def release_snapshot() -> bool:
        nonlocal snapshot
        if snapshot is None:
            return True
        current = snapshot
        snapshot = None
        try:
            current.cleanup()
        except Exception:
            return False
        return True

    try:
        _validate_bootstrap_primitive()
        snapshot = trusted_snapshot.create_trusted_repository_snapshot(
            repository_root=REPO_ROOT,
            git_sha=source_git_sha,
        )
        digests = _validate_contract_files(snapshot.repository)
        lines = (
            f"AUTHORIZATION_CONTRACT={AUTHORIZATION_CONTRACT}",
            f"SOURCE_GIT_SHA={source_git_sha}",
            f"EXECUTOR_SHA256={digests[SCRIPT_BASENAME]}",
            "TRUSTED_SNAPSHOT_SCRIPT_SHA256="
            f"{digests[str(TRUSTED_SNAPSHOT_RELATIVE_PATH)]}",
            f"BOOTSTRAP_TRUST_REQUIREMENT={BOOTSTRAP_TRUST_REQUIREMENT}",
            f"AUTHORIZATION_TRUST_REQUIREMENT={AUTHORIZATION_TRUST_REQUIREMENT}",
            f"RUNTIME_TRUST_REQUIREMENT={RUNTIME_TRUST_REQUIREMENT}",
            "EXPECTED_PYTHON_VERSION="
            f"{'.'.join(str(item) for item in EXPECTED_PYTHON_VERSION)}",
            f"EXPECTED_PSYCOPG2_VERSION={EXPECTED_PSYCOPG2_VERSION}",
            "PREFLIGHT_RUNNER_SHA256="
            f"{digests[str(PREFLIGHT_RUNNER_RELATIVE_PATH)]}",
            f"MATERIALIZER_SHA256={digests[str(MATERIALIZER_RELATIVE_PATH)]}",
            f"VERIFIER_SHA256={digests[str(VERIFIER_RELATIVE_PATH)]}",
            "CANONICAL_DERIVATION_SHA256="
            f"{digests[str(CANONICAL_DERIVATION_RELATIVE_PATH)]}",
            "SOURCE_MANIFEST_VERIFIER_SHA256="
            f"{digests[str(SOURCE_MANIFEST_VERIFIER_RELATIVE_PATH)]}",
            "CATALOG_HEAD_VERIFIER_SHA256="
            f"{digests[str(CATALOG_HEAD_VERIFIER_RELATIVE_PATH)]}",
            f"PREFLIGHT_SQL_SHA256={digests[str(PREFLIGHT_SQL_RELATIVE_PATH)]}",
            f"CAPTURE_SQL_SHA256={digests[str(CAPTURE_SQL_RELATIVE_PATH)]}",
            f"PROFILE_SHA256={digests[str(PROFILE_RELATIVE_PATH)]}",
            "ARTIFACT_SCHEMA_SHA256="
            f"{digests[str(ARTIFACT_SCHEMA_RELATIVE_PATH)]}",
            "AUTHORIZATION_SCHEMA_SHA256="
            f"{digests[str(AUTHORIZATION_SCHEMA_RELATIVE_PATH)]}",
            f"DEV_GATE={GATES['DEV']}",
            f"PROD_GATE={GATES['PROD']}",
            f"DEV_CONFIRMATION={CONFIRMATIONS['DEV']}",
            f"PROD_CONFIRMATION={CONFIRMATIONS['PROD']}",
            "MAX_AUTHORIZATION_WINDOW_SECONDS="
            f"{int(MAX_AUTHORIZATION_WINDOW.total_seconds())}",
            "EXPECTED_DATABASE_NAME_SHA256="
            f"{_component_sha256('DATABASE_NAME', 'postgres')}",
            "EXPECTED_SYSTEM_IDENTIFIER_SOURCE="
            "INDEPENDENT_TARGET_REGISTRY_REQUIRED",
            "DATABASE_MUTATION_AUTHORIZED=false",
            "MIGRATION_APPLICATION_AUTHORIZED=false",
            "OPERATIONAL_AUTHORIZATION=false",
            "NEXT_STAGE_AUTHORIZED=false",
            "RESULT=MIGRATION_ENVIRONMENT_ATTESTATION_EXECUTOR_V2_DESCRIBED_OFFLINE",
        )
        if not release_snapshot():
            raise CleanupError(phase="SNAPSHOT_CLEANUP")
        print("\n".join(lines))
        return 0
    except trusted_snapshot.CleanupError:
        snapshot = None
        print("SNAPSHOT_CLEANUP_CONFIRMED=false")
        print("OPERATIONAL_AUTHORIZATION=false")
        print("NEXT_STAGE_AUTHORIZED=false")
        print(f"RESULT={CleanupError.reason}")
        return CleanupError.exit_code
    except CleanupError:
        print("SNAPSHOT_CLEANUP_CONFIRMED=false")
        print("OPERATIONAL_AUTHORIZATION=false")
        print("NEXT_STAGE_AUTHORIZED=false")
        print(f"RESULT={CleanupError.reason}")
        return CleanupError.exit_code
    except (trusted_snapshot.SnapshotError, ExecutorError):
        cleanup_ok = release_snapshot()
        if not cleanup_ok:
            print("SNAPSHOT_CLEANUP_CONFIRMED=false")
            print("OPERATIONAL_AUTHORIZATION=false")
            print("NEXT_STAGE_AUTHORIZED=false")
            print(f"RESULT={CleanupError.reason}")
            return CleanupError.exit_code
        print("OPERATIONAL_AUTHORIZATION=false")
        print("NEXT_STAGE_AUTHORIZED=false")
        print("RESULT=BLOCKED_TRUSTED_SNAPSHOT_OR_CONTRACT_INVALID")
        return ContractError.exit_code
    except Exception:
        if not release_snapshot():
            print("SNAPSHOT_CLEANUP_CONFIRMED=false")
            print("OPERATIONAL_AUTHORIZATION=false")
            print("NEXT_STAGE_AUTHORIZED=false")
            print(f"RESULT={CleanupError.reason}")
            return CleanupError.exit_code
        print("OPERATIONAL_AUTHORIZATION=false")
        print("NEXT_STAGE_AUTHORIZED=false")
        print("RESULT=BLOCKED_INTERNAL_ERROR")
        return ExecutorError.exit_code


def build_parser(*, internal: bool = False) -> argparse.ArgumentParser:
    parser = SanitizedArgumentParser(add_help=False, allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    describe = subparsers.add_parser("describe", add_help=False, allow_abbrev=False)
    describe.add_argument("--source-git-sha", required=True)
    execute = subparsers.add_parser("execute", add_help=False, allow_abbrev=False)
    execute.add_argument("--source-git-sha", required=True)
    execute.add_argument("--environment", required=True, choices=sorted(GATES))
    execute.add_argument("--database-url-fd", required=True, type=int)
    execute.add_argument("--tls-ca-cert-fd", required=True, type=int)
    execute.add_argument("--authorization-record-fd", required=True, type=int)
    execute.add_argument("--hmac-key-fd", required=True, type=int)
    execute.add_argument("--nonce-fd", required=True, type=int)
    execute.add_argument("--output-dir", required=True, type=Path)
    execute.add_argument("--confirmation", required=True)
    if internal:
        child = subparsers.add_parser(
            INTERNAL_CHILD_COMMAND, add_help=False, allow_abbrev=False
        )
        child.add_argument("--source-git-sha", required=True)
        child.add_argument("--environment", required=True, choices=sorted(GATES))
        child.add_argument("--database-url-fd", required=True, type=int)
        child.add_argument("--tls-ca-cert-fd", required=True, type=int)
        child.add_argument("--authorization-record-fd", required=True, type=int)
        child.add_argument("--hmac-key-fd", required=True, type=int)
        child.add_argument("--nonce-fd", required=True, type=int)
        child.add_argument("--output-dir", required=True, type=Path)
        child.add_argument("--confirmation", required=True)
        child.add_argument("--snapshot-context-fd", required=True, type=int)
        child.add_argument("--launch-token-fd", required=True, type=int)
        child.add_argument("--staging-dir", required=True, type=Path)
    return parser


def _validate_common_args(args: argparse.Namespace) -> None:
    if (
        type(args.source_git_sha) is not str
        or GIT_SHA_RE.fullmatch(args.source_git_sha) is None
    ):
        raise UsageError(phase="ARGUMENTS")
    if args.command in {"execute", INTERNAL_CHILD_COMMAND}:
        if args.confirmation != CONFIRMATIONS[args.environment]:
            raise UsageError(phase="ARGUMENTS")


def _child_main(args: argparse.Namespace) -> int:
    state = ExecutionState(args.environment, args.source_git_sha)
    try:
        code, state = _execute_child(args, state=state)
        _emit_result(state, EvidenceMaterializedBlocked.reason)
        return code
    except ExecutorError as exc:
        state.phase = exc.phase
        _emit_result(state, exc.reason)
        return exc.exit_code
    except Exception:
        state.phase = "INTERNAL"
        _emit_result(state, ExecutorError.reason)
        return ExecutorError.exit_code


def main(argv: list[str] | None = None) -> int:
    try:
        _validate_python_runtime()
    except ContractError:
        state = ExecutionState("UNKNOWN", "UNKNOWN")
        state.phase = "RUNTIME_TRUST"
        _emit_result(state, ContractError.reason)
        return ContractError.exit_code
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        _assert_sanitized_argv(arguments)
        internal = bool(arguments and arguments[0] == INTERNAL_CHILD_COMMAND)
        args = build_parser(internal=internal).parse_args(arguments)
        _validate_common_args(args)
    except ExecutorError as exc:
        state = ExecutionState("UNKNOWN", "UNKNOWN")
        state.phase = exc.phase
        _emit_result(state, exc.reason)
        return exc.exit_code
    except Exception:
        state = ExecutionState("UNKNOWN", "UNKNOWN")
        state.phase = "ARGUMENTS"
        _emit_result(state, UsageError.reason)
        return UsageError.exit_code
    if args.command == "describe":
        return _describe(args.source_git_sha)
    if args.command == INTERNAL_CHILD_COMMAND:
        return _child_main(args)
    return _public_execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
