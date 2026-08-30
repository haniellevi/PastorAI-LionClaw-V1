#!/usr/bin/env python3
"""Bind and materialize sanitized environment-schema evidence offline.

The program never opens a database, network socket, subprocess or environment
file. Raw database identity and the ephemeral HMAC key are accepted only by
already-open file descriptors and are never copied to an artifact or error.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
from typing import Any, NoReturn

try:
    from scripts import derive_migration_history_canonical_schema as canonical
except ModuleNotFoundError:
    import derive_migration_history_canonical_schema as canonical


REPO_ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_DIR = REPO_ROOT / "docs" / "governance" / "migrations"
PREFLIGHT_SQL_PATH = GOVERNANCE_DIR / "migration-history-environment-identity-preflight-v1.sql"
CAPTURE_SQL_PATH = GOVERNANCE_DIR / "migration-history-environment-attestation-capture-v1.sql"
PROFILE_PATH = GOVERNANCE_DIR / "migration-history-environment-attestation-profile-v1.json"
SCHEMA_PATH = GOVERNANCE_DIR / "migration-history-environment-attestation.schema.json"
PREFLIGHT_SQL_SHA256 = "001bfda9b4655d028abfb7d8f44ac6c4e5ab51861c9623dd54b1cdd0ab6ea336"
CAPTURE_SQL_SHA256 = "f06a8c6dd39bc137376ab5fb80699019d6d90912e0995ddda5c8253dd8e7ff24"
PROFILE_SHA256 = "0734ba9302bf9d20f0b5770745124390350d231650fdb95ef915ee1b526d5147"
SCHEMA_SHA256 = "6286f68864ff935156c4c19be74123bfdd06043d50bdfc4ad34844df321d9964"
CAPTURE_CONTRACT = "MIGRATION_HISTORY_ENVIRONMENT_ATTESTATION_CAPTURE_V1"
IDENTITY_CONTRACT = "MIGRATION_HISTORY_ENVIRONMENT_IDENTITY_PREFLIGHT_V1"
CONTRACT_VERSION = "1.0"
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
MAX_INPUT_BYTES = 16_777_216
MAX_OUTPUT_BYTES = 262_144
MAX_KEY_BYTES = 256
MAX_JSON_DEPTH = 12
MAX_JSON_NODES = 100_000
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SYSTEM_IDENTIFIER_RE = re.compile(r"^[1-9][0-9]{0,19}$")
DATABASE_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}$")
SNAPSHOT_RE = re.compile(r"^[0-9]+:[0-9]+:(?:[0-9]+(?:,[0-9]+)*)?$")
TARGET_BINDING_CONTRACT = "MIGRATION_HISTORY_EXPECTED_TARGET_BINDING_V1"
TARGET_DESCRIPTOR_KEYS = {
    "authorization_record_sha256", "environment",
    "expected_database_name_sha256", "expected_project_ref_sha256",
    "expected_system_identifier_sha256", "target_binding_contract",
}
CONFIRMATIONS = {
    "DEV": "MATERIALIZE_DEV_SCHEMA_ATTESTATION_READ_ONLY",
    "PROD": "MATERIALIZE_PROD_SCHEMA_ATTESTATION_READ_ONLY",
}
ARTIFACT_BASENAMES = {
    "DEV": "migration-history-environment-attestation-dev-v1.json",
    "PROD": "migration-history-environment-attestation-prod-v1.json",
}
BINDING_BASENAMES = {
    "DEV": "migration-history-environment-attestation-dev-pre-capture-binding-v1.json",
    "PROD": "migration-history-environment-attestation-prod-pre-capture-binding-v1.json",
}
RAW_IDENTITY_KEYS = {
    "identity_contract", "system_identifier", "database_name",
    "server_version_num", "current_user_matches_session_user", "tls",
    "isolation_level", "read_only", "full_visibility",
}
RAW_CAPTURE_KEYS = {
    "capture_contract", "system_identifier", "database_name",
    "server_version_num", "current_user_matches_session_user", "tls",
    "isolation_level", "read_only", "full_visibility", "domains", "ledgers",
    "session_proof",
}
SESSION_PROOF_KEYS = {
    "backend_pid", "current_user_matches_session_user", "database_name",
    "full_visibility", "isolation_level", "read_only", "server_version_num",
    "snapshot", "system_identifier", "tls",
}
INVARIANT_ENVELOPE_KEYS = {"query_sha256", "result", "session_proof"}
FORBIDDEN_FINAL_KEYS = {
    "database_name", "dsn", "host", "oid", "row_data", "session_user",
    "system_identifier", "timestamp", "user", "username",
}


class AttestationError(RuntimeError):
    exit_code = 10
    reason = "INTERNAL_ERROR"


class UsageError(AttestationError):
    exit_code = 2
    reason = "USAGE"


class ContractError(AttestationError):
    exit_code = 3
    reason = "CONTRACT_INVALID"


class InputError(AttestationError):
    exit_code = 4
    reason = "TRANSIENT_INPUT_INVALID"


class BindingError(AttestationError):
    exit_code = 5
    reason = "PRE_CAPTURE_BINDING_INVALID"


class CaptureError(AttestationError):
    exit_code = 6
    reason = "CAPTURE_INVALID"


class OutputError(AttestationError):
    exit_code = 7
    reason = "OUTPUT_INVALID"


class EvidenceBlocked(AttestationError):
    exit_code = 8
    reason = "ENVIRONMENT_EVIDENCE_BLOCKED"


class SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise UsageError


@dataclass(frozen=True)
class ContractBundle:
    profile: dict[str, Any]
    capture_lines: tuple[str, ...]


@dataclass(frozen=True)
class PrivateFileWitness:
    directory: Path
    basename: str
    directory_snapshot: tuple[int, ...]
    file_snapshot: tuple[int, ...]
    sha256: str


class PrivateJson(dict[str, Any]):
    def __init__(self, value: dict[str, Any], witness: PrivateFileWitness) -> None:
        super().__init__(value)
        self.witness = witness


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _frame(tag: bytes, payload: bytes) -> bytes:
    return tag + struct.pack(">Q", len(payload)) + payload


def _hmac_material(
    environment: str,
    target_binding: str,
    system_identifier: str,
    database_name: str,
    authorization_record: str,
    nonce: str,
) -> bytes:
    values = (
        environment, target_binding, system_identifier, database_name,
        CAPTURE_SQL_SHA256, authorization_record, nonce,
    )
    material = b"PASTORAI-ENVIRONMENT-ATTESTATION-BINDING\x00\x01"
    for value in values:
        material += _frame(b"V", value.encode("utf-8"))
    return material


def _json_loads(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise InputError
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=reject_duplicates,
            parse_float=lambda _value: (_ for _ in ()).throw(InputError()),
            parse_constant=lambda _value: (_ for _ in ()).throw(InputError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError from exc
    if type(value) is not dict:
        raise InputError
    nodes = 0

    def walk(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise InputError
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str or len(key) > 256:
                    raise InputError
                walk(child, depth + 1)
        elif type(item) is list:
            for child in item:
                walk(child, depth + 1)
        elif item is not None and type(item) not in {bool, int, str}:
            raise InputError

    walk(value, 0)
    return value


def _read_fd(descriptor: int, maximum: int) -> bytes:
    if descriptor < 3:
        raise InputError
    try:
        before = os.fstat(descriptor)
    except OSError as exc:
        raise InputError from exc
    is_regular = stat.S_ISREG(before.st_mode)
    is_fifo = stat.S_ISFIFO(before.st_mode)
    if not is_regular and not is_fifo:
        raise InputError
    if is_regular:
        if (
            before.st_uid != os.geteuid()
            or before.st_gid != os.getegid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > maximum
        ):
            raise InputError
        try:
            if os.lseek(descriptor, 0, os.SEEK_CUR) != 0:
                raise InputError
        except OSError as exc:
            raise InputError from exc
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            chunk = os.read(descriptor, min(65_536, maximum + 1 - total))
        except OSError as exc:
            raise InputError from exc
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum:
            raise InputError
    if total == 0:
        raise InputError
    if is_regular:
        try:
            after = os.fstat(descriptor)
        except OSError as exc:
            raise InputError from exc
        stable_fields = (
            "st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid",
            "st_size", "st_mtime_ns", "st_ctime_ns",
        )
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            raise InputError
    return b"".join(chunks)


def _read_key(descriptor: int) -> bytes:
    key = _read_fd(descriptor, MAX_KEY_BYTES)
    if len(key) < 32 or len(key) > 64:
        raise BindingError
    return key


def _open_private_dir(path: Path, allowed_existing: set[str]) -> int:
    try:
        info = path.lstat()
    except OSError as exc:
        raise OutputError from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_gid != os.getegid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise OutputError
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
            or not stat.S_ISDIR(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or opened.st_gid != os.getegid()
            or stat.S_IMODE(opened.st_mode) != 0o700
            or set(os.listdir(descriptor)) != allowed_existing
        ):
            raise OutputError
    except Exception:
        if "descriptor" in locals():
            os.close(descriptor)
        raise OutputError
    return descriptor


def _atomic_write(
    directory: Path, basename: str, value: dict[str, Any],
    *, allowed_existing: set[str],
    continuity_witness: PrivateFileWitness | None = None,
) -> Path:
    if continuity_witness is None:
        directory_descriptor = _open_private_dir(directory, allowed_existing)
    else:
        if (
            directory != continuity_witness.directory
            or allowed_existing != {continuity_witness.basename}
        ):
            raise OutputError
        directory_descriptor = _open_witness_directory(
            continuity_witness, allowed_existing, require_initial_directory=True
        )
    target = directory / basename
    temporary_name = f".{basename}.partial"
    payload = _canonical_bytes(value) + b"\n"
    if len(payload) > MAX_OUTPUT_BYTES:
        os.close(directory_descriptor)
        raise OutputError
    created_identity: tuple[int, int] | None = None
    nominal_descriptor: int | None = None

    def unlink_matching(parent_descriptor: int, name: str) -> None:
        if created_identity is None:
            return
        try:
            info = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
            if (info.st_dev, info.st_ino) == created_identity:
                os.unlink(name, dir_fd=parent_descriptor)
                os.fsync(parent_descriptor)
        except OSError:
            pass

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=directory_descriptor)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temporary = os.stat(
                temporary_name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            created_identity = (temporary.st_dev, temporary.st_ino)
            os.link(
                temporary_name, basename,
                src_dir_fd=directory_descriptor, dst_dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            linked = os.stat(basename, dir_fd=directory_descriptor, follow_symlinks=False)
            if (linked.st_dev, linked.st_ino) != created_identity:
                raise OutputError
            os.unlink(temporary_name, dir_fd=directory_descriptor)
            os.fsync(directory_descriptor)
        except Exception:
            try:
                os.unlink(temporary_name, dir_fd=directory_descriptor)
            except OSError:
                pass
            raise
        final_descriptor = os.open(basename, _file_flags(), dir_fd=directory_descriptor)
        try:
            final = os.fstat(final_descriptor)
            observed = b""
            while len(observed) <= len(payload):
                chunk = os.read(final_descriptor, min(65_536, len(payload) + 1 - len(observed)))
                if not chunk:
                    break
                observed += chunk
        finally:
            os.close(final_descriptor)
        if (
            not stat.S_ISREG(final.st_mode)
            or final.st_nlink != 1
            or final.st_uid != os.geteuid()
            or final.st_gid != os.getegid()
            or stat.S_IMODE(final.st_mode) != 0o600
            or final.st_size != len(payload)
            or not hmac.compare_digest(
                hashlib.sha256(observed).digest(), hashlib.sha256(payload).digest()
            )
        ):
            raise OutputError
        post_write_directory = os.fstat(directory_descriptor)

        nominal_descriptor = _open_private_dir(
            directory, allowed_existing | {basename}
        )
        nominal_directory = os.fstat(nominal_descriptor)
        if _stat_snapshot(nominal_directory) != _stat_snapshot(post_write_directory):
            raise OutputError
        if continuity_witness is not None:
            _validate_witness_file(continuity_witness, directory_descriptor)
            _validate_witness_file(continuity_witness, nominal_descriptor)
        nominal_file = os.open(basename, _file_flags(), dir_fd=nominal_descriptor)
        try:
            nominal_info = os.fstat(nominal_file)
            nominal_payload = b""
            while len(nominal_payload) <= len(payload):
                chunk = os.read(
                    nominal_file,
                    min(65_536, len(payload) + 1 - len(nominal_payload)),
                )
                if not chunk:
                    break
                nominal_payload += chunk
            nominal_after = os.fstat(nominal_file)
        finally:
            os.close(nominal_file)
        if (
            _stat_snapshot(nominal_info) != _stat_snapshot(final)
            or _stat_snapshot(nominal_after) != _stat_snapshot(final)
            or not hmac.compare_digest(
                hashlib.sha256(nominal_payload).digest(),
                hashlib.sha256(payload).digest(),
            )
        ):
            raise OutputError
        return target
    except AttestationError:
        unlink_matching(directory_descriptor, basename)
        if nominal_descriptor is not None:
            unlink_matching(nominal_descriptor, basename)
        raise
    except OSError as exc:
        unlink_matching(directory_descriptor, basename)
        if nominal_descriptor is not None:
            unlink_matching(nominal_descriptor, basename)
        raise OutputError from exc
    except Exception as exc:
        unlink_matching(directory_descriptor, basename)
        if nominal_descriptor is not None:
            unlink_matching(nominal_descriptor, basename)
        raise OutputError from exc
    finally:
        if nominal_descriptor is not None:
            os.close(nominal_descriptor)
        os.close(directory_descriptor)


def _validate_hash(value: Any, error: type[AttestationError] = ContractError) -> str:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        raise error
    return value


def _validate_nonce(value: str) -> str:
    return _validate_hash(value, BindingError)


def _identity_component_sha256(label: str, value: str) -> str:
    return hashlib.sha256(_frame(label.encode("ascii"), value.encode("utf-8"))).hexdigest()


def _expected_target(
    descriptor_fd: int, environment: str, authorization_record: str,
) -> tuple[dict[str, Any], str]:
    descriptor = _json_loads(_read_fd(descriptor_fd, 65_536))
    if set(descriptor) != TARGET_DESCRIPTOR_KEYS:
        raise BindingError
    if descriptor.get("target_binding_contract") != TARGET_BINDING_CONTRACT:
        raise BindingError
    if descriptor.get("environment") != environment:
        raise BindingError
    if descriptor.get("authorization_record_sha256") != authorization_record:
        raise BindingError
    for key in (
        "authorization_record_sha256", "expected_database_name_sha256",
        "expected_project_ref_sha256", "expected_system_identifier_sha256",
    ):
        _validate_hash(descriptor.get(key), BindingError)
    return descriptor, hashlib.sha256(_canonical_bytes(descriptor)).hexdigest()


def _match_expected_identity(
    descriptor: dict[str, Any], system_identifier: str, database_name: str,
) -> None:
    if not hmac.compare_digest(
        descriptor["expected_system_identifier_sha256"],
        _identity_component_sha256("SYSTEM_IDENTIFIER", system_identifier),
    ):
        raise BindingError
    if not hmac.compare_digest(
        descriptor["expected_database_name_sha256"],
        _identity_component_sha256("DATABASE_NAME", database_name),
    ):
        raise BindingError


def _validate_session_proof(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != SESSION_PROOF_KEYS:
        raise CaptureError
    server = value.get("server_version_num")
    backend_pid = value.get("backend_pid")
    snapshot = value.get("snapshot")
    if type(server) is not int or server // 10_000 != 17:
        raise CaptureError
    if type(backend_pid) is not int or backend_pid < 1:
        raise CaptureError
    if type(snapshot) is not str or SNAPSHOT_RE.fullmatch(snapshot) is None:
        raise CaptureError
    if (
        value.get("current_user_matches_session_user") is not True
        or value.get("tls") is not True
        or value.get("full_visibility") is not True
        or value.get("isolation_level") != "repeatable read"
        or value.get("read_only") != "on"
    ):
        raise CaptureError
    system_identifier = value.get("system_identifier")
    database_name = value.get("database_name")
    if type(system_identifier) is not str or SYSTEM_IDENTIFIER_RE.fullmatch(system_identifier) is None:
        raise CaptureError
    if type(database_name) is not str or DATABASE_NAME_RE.fullmatch(database_name) is None:
        raise CaptureError
    return dict(value)


def _validate_proofs(value: dict[str, Any], contract_key: str, contract_value: str) -> tuple[str, str]:
    expected = RAW_IDENTITY_KEYS if contract_key == "identity_contract" else RAW_CAPTURE_KEYS
    if set(value) != expected or value.get(contract_key) != contract_value:
        raise InputError
    server = value.get("server_version_num")
    if type(server) is not int or server // 10_000 != 17:
        raise InputError
    if (
        value.get("current_user_matches_session_user") is not True
        or value.get("tls") is not True
        or value.get("full_visibility") is not True
    ):
        raise InputError
    if value.get("isolation_level") != "repeatable read" or value.get("read_only") != "on":
        raise InputError
    system_identifier = value.get("system_identifier")
    database_name = value.get("database_name")
    if type(system_identifier) is not str or SYSTEM_IDENTIFIER_RE.fullmatch(system_identifier) is None:
        raise InputError
    if type(database_name) is not str or DATABASE_NAME_RE.fullmatch(database_name) is None:
        raise InputError
    return system_identifier, database_name


def _stat_snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
        info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
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


def _read_stable_nominal_file(
    path: Path, maximum: int, *, private: bool,
    error: type[Exception], with_witness: bool = False,
) -> bytes | tuple[bytes, PrivateFileWitness]:
    parent = path.parent
    first_dir = second_dir = first_file = second_file = None
    try:
        nominal_parent = parent.lstat()
        if (
            not stat.S_ISDIR(nominal_parent.st_mode)
            or nominal_parent.st_uid != os.geteuid()
            or nominal_parent.st_gid != os.getegid()
            or (private and stat.S_IMODE(nominal_parent.st_mode) != 0o700)
            or (not private and nominal_parent.st_mode & 0o022)
        ):
            raise error
        first_dir = os.open(parent, _directory_flags())
        opened_parent = os.fstat(first_dir)
        if _stat_snapshot(opened_parent) != _stat_snapshot(nominal_parent):
            raise error
        first_file = os.open(path.name, _file_flags(), dir_fd=first_dir)
        before = os.fstat(first_file)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or before.st_gid != os.getegid()
            or before.st_size <= 0
            or before.st_size > maximum
            or (private and stat.S_IMODE(before.st_mode) != 0o600)
            or (not private and before.st_mode & 0o022)
        ):
            raise error
        chunks: list[bytes] = []
        total = 0
        while total <= maximum:
            chunk = os.read(first_file, min(65_536, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(first_file)
        if len(raw) != before.st_size or _stat_snapshot(before) != _stat_snapshot(after):
            raise error

        second_dir = os.open(parent, _directory_flags())
        reopened_parent = os.fstat(second_dir)
        if _stat_snapshot(reopened_parent) != _stat_snapshot(opened_parent):
            raise error
        second_file = os.open(path.name, _file_flags(), dir_fd=second_dir)
        reopened_file = os.fstat(second_file)
        if _stat_snapshot(reopened_file) != _stat_snapshot(before):
            raise error
        reopened = b""
        while len(reopened) <= maximum:
            chunk = os.read(second_file, min(65_536, maximum + 1 - len(reopened)))
            if not chunk:
                break
            reopened += chunk
        final = os.fstat(second_file)
        if (
            _stat_snapshot(final) != _stat_snapshot(before)
            or len(reopened) != len(raw)
            or not hmac.compare_digest(
                hashlib.sha256(reopened).digest(), hashlib.sha256(raw).digest()
            )
        ):
            raise error
        if with_witness:
            if not private:
                raise error
            return raw, PrivateFileWitness(
                directory=parent,
                basename=path.name,
                directory_snapshot=_stat_snapshot(opened_parent),
                file_snapshot=_stat_snapshot(before),
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        return raw
    except AttestationError:
        raise
    except OSError as exc:
        raise error from exc
    finally:
        for descriptor in (second_file, first_file, second_dir, first_dir):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def _validate_witness_file(
    witness: PrivateFileWitness, directory_descriptor: int,
) -> None:
    file_descriptor = None
    try:
        file_descriptor = os.open(
            witness.basename, _file_flags(), dir_fd=directory_descriptor
        )
        before = os.fstat(file_descriptor)
        if _stat_snapshot(before) != witness.file_snapshot:
            raise OutputError
        raw = b""
        while len(raw) <= MAX_INPUT_BYTES:
            chunk = os.read(
                file_descriptor,
                min(65_536, MAX_INPUT_BYTES + 1 - len(raw)),
            )
            if not chunk:
                break
            raw += chunk
        after = os.fstat(file_descriptor)
        if (
            _stat_snapshot(after) != witness.file_snapshot
            or not hmac.compare_digest(
                hashlib.sha256(raw).hexdigest(), witness.sha256
            )
        ):
            raise OutputError
    except AttestationError:
        raise
    except OSError as exc:
        raise OutputError from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)


def _open_witness_directory(
    witness: PrivateFileWitness, allowed_existing: set[str],
    *, require_initial_directory: bool,
) -> int:
    descriptor = _open_private_dir(witness.directory, allowed_existing)
    try:
        if (
            require_initial_directory
            and _stat_snapshot(os.fstat(descriptor))
            != witness.directory_snapshot
        ):
            raise OutputError
        _validate_witness_file(witness, descriptor)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _extract_sql_block(lines: list[str], marker: str) -> str:
    if marker.startswith("invariant-data:"):
        identifier = marker.split(":", 1)[1]
        begin = f"-- invariant-data-begin:{identifier}\n"
        end = f"-- invariant-data-end:{identifier}\n"
    else:
        begin = f"-- {marker}-begin\n"
        end = f"-- {marker}-end\n"
    if lines.count(begin) != 1 or lines.count(end) != 1:
        raise ContractError
    first = lines.index(begin) + 1
    last = lines.index(end)
    if first > last:
        raise ContractError
    block = "".join(lines[first:last])
    if not block.strip():
        raise ContractError
    return block


def _load_contract_bundle() -> ContractBundle:
    paths = (
        (PREFLIGHT_SQL_PATH, PREFLIGHT_SQL_SHA256),
        (CAPTURE_SQL_PATH, CAPTURE_SQL_SHA256),
        (PROFILE_PATH, PROFILE_SHA256),
        (SCHEMA_PATH, SCHEMA_SHA256),
    )
    contents: dict[Path, bytes] = {}
    for path, expected in paths:
        content = _read_stable_nominal_file(
            path, MAX_INPUT_BYTES, private=False, error=ContractError
        )
        if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected):
            raise ContractError
        contents[path] = content
    try:
        profile = _json_loads(contents[PROFILE_PATH])
        capture_lines = contents[CAPTURE_SQL_PATH].decode("utf-8").splitlines(keepends=True)
    except (UnicodeDecodeError, InputError) as exc:
        raise ContractError from exc
    if profile.get("contract_version") != CONTRACT_VERSION:
        raise ContractError
    target_contract = profile.get("target_binding")
    if type(target_contract) is not dict or target_contract.get("contract") != TARGET_BINDING_CONTRACT:
        raise ContractError
    invariant_contracts = profile.get("data_invariants")
    if type(invariant_contracts) is not list or len(invariant_contracts) != 8:
        raise ContractError
    for invariant in invariant_contracts:
        if type(invariant) is not dict or set(invariant) != {
            "allowlisted_tables", "checks_expected", "id", "query_sha256"
        }:
            raise ContractError
        identifier = invariant["id"]
        tables = invariant["allowlisted_tables"]
        if (
            type(identifier) is not str
            or type(tables) is not list
            or tables != sorted(set(tables))
            or not all(
                type(table) is str
                and table.startswith(("pg_catalog.", "public.", "recovery."))
                for table in tables
            )
            or type(invariant["checks_expected"]) is not int
            or invariant["checks_expected"] < 1
        ):
            raise ContractError
        query = _extract_sql_block(capture_lines, f"invariant-data:{identifier}")
        query_digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(query_digest, _validate_hash(invariant["query_sha256"])):
            raise ContractError
    for marker in (
        "transaction-open", "transaction-close", "session-proof",
        "metadata-capture",
    ):
        _extract_sql_block(capture_lines, marker)
    return ContractBundle(profile=profile, capture_lines=tuple(capture_lines))


def _load_contracts() -> dict[str, Any]:
    return _load_contract_bundle().profile


def _fetch_one_json(cursor: Any) -> dict[str, Any]:
    row = cursor.fetchone()
    if type(row) not in {tuple, list} or len(row) != 1:
        raise CaptureError
    if cursor.fetchone() is not None:
        raise CaptureError
    value = row[0]
    if type(value) is str:
        value = _json_loads(value.encode("utf-8"))
    elif type(value) is dict:
        value = _json_loads(_canonical_bytes(value))
    else:
        raise CaptureError
    return value


def _recoverable_statement_error(exc: Exception, connection: Any) -> bool:
    """Classify only a live-session PostgreSQL statement failure as recoverable."""
    if getattr(connection, "closed", False) not in {False, 0, None}:
        return False
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate is None:
        sqlstate = getattr(exc, "pgcode", None)
    if type(sqlstate) is not str or re.fullmatch(r"[0-9A-Z]{5}", sqlstate) is None:
        return False
    if sqlstate == "57014":
        return True
    return sqlstate[:2] not in {"08", "25", "40", "53", "57", "58", "XX"}


def capture_one_snapshot(connection: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute the pinned capture contract on an already-authorized connection.

    The helper does not discover credentials or open a connection. Its caller
    owns the separate live-environment authorization gate and must pass an
    autocommit connection so this function can establish exactly one explicit
    repeatable-read, read-only transaction.
    """
    bundle = _load_contract_bundle()
    profile = bundle.profile
    if getattr(connection, "autocommit", None) is not True:
        raise CaptureError
    lines = list(bundle.capture_lines)
    transaction_open = _extract_sql_block(lines, "transaction-open")
    transaction_close = _extract_sql_block(lines, "transaction-close")
    proof_sql = _extract_sql_block(lines, "session-proof")
    metadata_sql = _extract_sql_block(lines, "metadata-capture")
    cursor = None
    opened = False
    primary_error: Exception | None = None
    try:
        cursor = connection.cursor()
        opened = True
        cursor.execute(transaction_open)
        cursor.execute(proof_sql)
        session_proof = _validate_session_proof(_fetch_one_json(cursor))
        cursor.execute(metadata_sql)
        metadata = _fetch_one_json(cursor)
        metadata["session_proof"] = session_proof
        system_identifier, database_name = _validate_proofs(
            metadata, "capture_contract", CAPTURE_CONTRACT
        )
        if (
            session_proof["system_identifier"] != system_identifier
            or session_proof["database_name"] != database_name
        ):
            raise CaptureError
        cursor.execute(proof_sql)
        if _validate_session_proof(_fetch_one_json(cursor)) != session_proof:
            raise CaptureError
        envelopes: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        domains, unknown = _normalize_domains(metadata, profile)
        metadata_shape_matches = (
            all(domain["state"] == "MATCH" for domain in domains)
            and unknown["count"] == 0
        )
        if not metadata_shape_matches:
            for contract in profile["data_invariants"]:
                result = {
                    "id": contract["id"],
                    "state": "UNKNOWN",
                    "checks_executed": 0,
                    "violation_count": 0,
                }
                results.append(result)
                envelopes.append({
                    "query_sha256": contract["query_sha256"],
                    "result": result,
                    "session_proof": session_proof,
                })
            _validate_invariants(results, profile)
            return metadata, envelopes
        for sequence, contract in enumerate(profile["data_invariants"], start=1):
            query = _extract_sql_block(lines, f"invariant-data:{contract['id']}")
            savepoint = f"attestation_invariant_{sequence}"
            cursor.execute(f"SAVEPOINT {savepoint}")
            try:
                cursor.execute(query)
            except Exception as exc:
                if not _recoverable_statement_error(exc, connection):
                    raise CaptureError from None
                try:
                    cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    cursor.execute(proof_sql)
                    observed_proof = _validate_session_proof(_fetch_one_json(cursor))
                    if observed_proof != session_proof:
                        raise CaptureError
                    cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
                except Exception:
                    raise CaptureError from None
                result = {
                    "id": contract["id"],
                    "state": "ERROR",
                    "checks_executed": 0,
                    "violation_count": 0,
                }
                results.append(result)
                envelopes.append({
                    "query_sha256": contract["query_sha256"],
                    "result": result,
                    "session_proof": observed_proof,
                })
                continue
            result = _fetch_one_json(cursor)
            cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
            cursor.execute(proof_sql)
            observed_proof = _validate_session_proof(_fetch_one_json(cursor))
            if observed_proof != session_proof:
                raise CaptureError
            results.append(result)
            envelopes.append({
                "query_sha256": contract["query_sha256"],
                "result": result,
                "session_proof": observed_proof,
            })
        _validate_invariants(results, profile)
        return metadata, envelopes
    except AttestationError as exc:
        primary_error = exc
        raise
    except Exception as exc:
        primary_error = exc
        raise CaptureError from None
    finally:
        close_error = False
        if cursor is not None and opened:
            try:
                cursor.execute(transaction_close)
            except Exception:
                close_error = True
                try:
                    connection.rollback()
                except Exception:
                    pass
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                close_error = True
        if close_error and primary_error is None:
            raise CaptureError


def bind_target(
    *, environment: str, authorization_record: str, nonce: str,
    expected_target_fd: int, identity_fd: int, hmac_key_fd: int,
    output_dir: Path,
) -> Path:
    directory_descriptor = _open_private_dir(output_dir, set())
    os.close(directory_descriptor)
    _load_contracts()
    descriptor, target_binding = _expected_target(
        expected_target_fd, environment, authorization_record
    )
    identity = _json_loads(_read_fd(identity_fd, 65_536))
    system_identifier, database_name = _validate_proofs(
        identity, "identity_contract", IDENTITY_CONTRACT
    )
    _match_expected_identity(descriptor, system_identifier, database_name)
    key = _read_key(hmac_key_fd)
    digest = hmac.new(
        key,
        _hmac_material(
            environment, target_binding, system_identifier, database_name,
            authorization_record, nonce,
        ),
        hashlib.sha256,
    ).hexdigest()
    receipt = {
        "authorization_record_sha256": authorization_record,
        "capture_sql_sha256": CAPTURE_SQL_SHA256,
        "contract_version": CONTRACT_VERSION,
        "environment": environment,
        "hmac_sha256": digest,
        "nonce_sha256": hashlib.sha256(bytes.fromhex(nonce)).hexdigest(),
        "preflight_sql_sha256": PREFLIGHT_SQL_SHA256,
        "target_binding_sha256": target_binding,
        "target_binding_contract": TARGET_BINDING_CONTRACT,
    }
    return _atomic_write(
        output_dir, BINDING_BASENAMES[environment], receipt,
        allowed_existing=set(),
    )


def _read_private_json(path: Path, maximum: int) -> PrivateJson:
    try:
        captured = _read_stable_nominal_file(
            path, maximum, private=True, error=InputError, with_witness=True
        )
    except AttestationError:
        raise
    if type(captured) is not tuple or len(captured) != 2:
        raise InputError
    raw, witness = captured
    if type(raw) is not bytes or type(witness) is not PrivateFileWitness:
        raise InputError
    return PrivateJson(_json_loads(raw), witness)


def _normalize_domains(capture: dict[str, Any], profile: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_domains = capture.get("domains")
    expected_domains = profile.get("domains")
    if type(raw_domains) is not list or type(expected_domains) is not list or len(raw_domains) != 14:
        raise CaptureError
    by_name: dict[str, list[dict[str, Any]]] = {}
    for domain in raw_domains:
        if type(domain) is not dict or set(domain) != {"name", "entries"}:
            raise CaptureError
        name, entries = domain["name"], domain["entries"]
        if type(name) is not str or type(entries) is not list or name in by_name:
            raise CaptureError
        if not all(type(entry) is dict for entry in entries):
            raise CaptureError
        normalized = sorted(entries, key=_canonical_bytes)
        if len({_canonical_bytes(entry) for entry in normalized}) != len(normalized):
            raise CaptureError
        by_name[name] = normalized
    if set(by_name) != {item["name"] for item in expected_domains}:
        raise CaptureError

    unknown_tokens: list[dict[str, str]] = []

    def contains_unknown(value: Any) -> bool:
        if type(value) is dict:
            return "UNKNOWN_OWNER" in value.values() or any(
                contains_unknown(child) for child in value.values()
            )
        if type(value) is list:
            return any(contains_unknown(child) for child in value)
        return False

    results: list[dict[str, Any]] = []
    for expected in expected_domains:
        name = expected["name"]
        entries = by_name[name]
        for entry in entries:
            if contains_unknown(entry):
                unknown_tokens.append({
                    "domain": name,
                    "entry_sha256": hashlib.sha256(_canonical_bytes(entry)).hexdigest(),
                })
        digest = canonical._domain_sha256(name, entries)
        state = "MATCH" if (
            len(entries) == expected["entry_count"] and
            hmac.compare_digest(digest, expected["sha256"])
        ) else "MISMATCH"
        results.append({
            "comparison": expected["comparison"],
            "expected_entry_count": expected["entry_count"],
            "expected_sha256": expected["sha256"],
            "name": name,
            "observed_entry_count": len(entries),
            "observed_sha256": digest,
            "state": state,
        })
    unknown_tokens.sort(key=_canonical_bytes)
    unknown = {
        "count": len(unknown_tokens),
        "fingerprint_sha256": hashlib.sha256(_canonical_bytes(unknown_tokens)).hexdigest(),
    }
    return results, unknown


def _validate_invariants(values: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
    expected = profile.get("data_invariants")
    if type(values) is not list or type(expected) is not list or len(values) != 8:
        raise CaptureError
    results: list[dict[str, Any]] = []
    for value, contract in zip(values, expected, strict=True):
        if type(value) is not dict or set(value) != {
            "id", "state", "checks_executed", "violation_count"
        }:
            raise CaptureError
        if value["id"] != contract["id"] or value["state"] not in {"PASS", "FAIL", "UNKNOWN", "ERROR"}:
            raise CaptureError
        if type(value["checks_executed"]) is not int or value["checks_executed"] < 0:
            raise CaptureError
        if type(value["violation_count"]) is not int or value["violation_count"] < 0:
            raise CaptureError
        if value["state"] == "PASS" and value["violation_count"] != 0:
            raise CaptureError
        expected_checks = contract.get("checks_expected")
        if type(expected_checks) is not int or expected_checks < 1:
            raise ContractError
        if value["checks_executed"] not in {0, expected_checks}:
            raise CaptureError
        if value["state"] in {"PASS", "FAIL"} and value["checks_executed"] != expected_checks:
            raise CaptureError
        if value["state"] == "FAIL" and value["violation_count"] < 1:
            raise CaptureError
        if value["state"] in {"UNKNOWN", "ERROR"} and value["violation_count"] != 0:
            raise CaptureError
        if value["state"] == "ERROR" and value["checks_executed"] != 0:
            raise CaptureError
        if value["id"] == "APPEND_ONLY_AUDIT_INTEGRITY":
            if (
                value["state"] != "UNKNOWN"
                or value["checks_executed"] not in {0, expected_checks}
                or value["violation_count"] != 0
            ):
                raise CaptureError
        results.append(dict(value))
    return results


def _read_invariant_results(
    descriptors: dict[str, int], profile: dict[str, Any], reserved_fds: set[int],
    expected_session_proof: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[bytes]]:
    expected = profile.get("data_invariants")
    identifiers = [item["id"] for item in expected]
    if set(descriptors) != set(identifiers):
        raise UsageError
    values: list[dict[str, Any]] = []
    raw_results: list[bytes] = []
    observed_fds = list(descriptors.values())
    if (
        any(type(value) is not int or value < 3 for value in observed_fds)
        or len(set(observed_fds)) != len(observed_fds)
        or set(observed_fds) & reserved_fds
    ):
        raise UsageError
    contracts = {item["id"]: item for item in expected}
    for identifier in identifiers:
        raw = _read_fd(descriptors[identifier], 65_536)
        envelope = _json_loads(raw)
        if type(envelope) is not dict or set(envelope) != INVARIANT_ENVELOPE_KEYS:
            raise CaptureError
        if not hmac.compare_digest(
            _validate_hash(envelope.get("query_sha256"), CaptureError),
            contracts[identifier]["query_sha256"],
        ):
            raise CaptureError
        proof = _validate_session_proof(envelope.get("session_proof"))
        if proof != expected_session_proof:
            raise CaptureError
        value = envelope.get("result")
        if type(value) is not dict or value.get("id") != identifier:
            raise CaptureError
        values.append(value)
        raw_results.append(raw)
    return _validate_invariants(values, profile), raw_results


def materialize(
    *, environment: str, authorization_record: str, nonce: str,
    expected_target_fd: int, metadata_capture_fd: int, hmac_key_fd: int,
    invariant_result_fds: dict[str, int], output_dir: Path,
) -> tuple[Path, bool]:
    binding_basename = BINDING_BASENAMES[environment]
    directory_descriptor = _open_private_dir(output_dir, {binding_basename})
    os.close(directory_descriptor)
    profile = _load_contracts()
    descriptor, target_binding = _expected_target(
        expected_target_fd, environment, authorization_record
    )
    receipt_path = output_dir / binding_basename
    receipt = _read_private_json(receipt_path, 65_536)
    receipt_witness = receipt.witness
    expected_receipt_keys = {
        "authorization_record_sha256", "capture_sql_sha256", "contract_version",
        "environment", "hmac_sha256", "nonce_sha256", "preflight_sql_sha256",
        "target_binding_contract", "target_binding_sha256",
    }
    if set(receipt) != expected_receipt_keys:
        raise BindingError
    if receipt != {
        **receipt,
        "authorization_record_sha256": authorization_record,
        "capture_sql_sha256": CAPTURE_SQL_SHA256,
        "contract_version": CONTRACT_VERSION,
        "environment": environment,
        "nonce_sha256": hashlib.sha256(bytes.fromhex(nonce)).hexdigest(),
        "preflight_sql_sha256": PREFLIGHT_SQL_SHA256,
        "target_binding_sha256": target_binding,
        "target_binding_contract": TARGET_BINDING_CONTRACT,
    }:
        raise BindingError
    _validate_hash(receipt.get("hmac_sha256"), BindingError)
    capture_raw = _read_fd(metadata_capture_fd, MAX_INPUT_BYTES)
    capture = _json_loads(capture_raw)
    system_identifier, database_name = _validate_proofs(
        capture, "capture_contract", CAPTURE_CONTRACT
    )
    session_proof = _validate_session_proof(capture.get("session_proof"))
    if (
        session_proof["system_identifier"] != system_identifier
        or session_proof["database_name"] != database_name
    ):
        raise CaptureError
    _match_expected_identity(descriptor, system_identifier, database_name)
    key = _read_key(hmac_key_fd)
    expected_hmac = hmac.new(
        key,
        _hmac_material(
            environment, target_binding, system_identifier, database_name,
            authorization_record, nonce,
        ),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(receipt["hmac_sha256"], expected_hmac):
        raise BindingError

    domains, unknown = _normalize_domains(capture, profile)
    invariants, invariant_raws = _read_invariant_results(
        invariant_result_fds, profile,
        {expected_target_fd, metadata_capture_fd, hmac_key_fd},
        session_proof,
    )
    ledgers = capture.get("ledgers")
    if type(ledgers) is not dict or set(ledgers) != {"public", "native"}:
        raise CaptureError
    if any(value not in {"ABSENT", "PRESENT", "INVALID", "UNKNOWN"} for value in ledgers.values()):
        raise CaptureError
    metadata_blocked = (
        any(domain["state"] != "MATCH" for domain in domains)
        or unknown["count"] != 0
        or ledgers["public"] != "ABSENT"
    )
    structural_metadata_blocked = (
        any(domain["state"] != "MATCH" for domain in domains)
        or unknown["count"] != 0
    )
    if structural_metadata_blocked:
        if any(
            item["state"] != "UNKNOWN"
            or item["checks_executed"] != 0
            or item["violation_count"] != 0
            for item in invariants
        ):
            raise CaptureError
    elif invariants[2] != {
        "id": "APPEND_ONLY_AUDIT_INTEGRITY",
        "state": "UNKNOWN",
        "checks_executed": profile["data_invariants"][2]["checks_expected"],
        "violation_count": 0,
    }:
        raise CaptureError
    data_blocked = any(item["state"] != "PASS" for item in invariants)
    state = (
        "BLOCKED_SCHEMA_METADATA_DIVERGENCE"
        if metadata_blocked
        else "BLOCKED_DATA_INVARIANTS" if data_blocked
        else "BLOCKED_PLATFORM_SURFACES_UNATTESTED"
    )
    artifact = {
        "artifact_id": f"migration-history-environment-attestation-{environment.casefold()}-v1",
        "artifact_state": state,
        "capture_record_sha256": hashlib.sha256(
            _frame(b"E", environment.encode("ascii"))
            + _frame(b"B", target_binding.encode("ascii"))
            + _frame(b"C", capture_raw)
            + b"".join(_frame(b"I", raw) for raw in invariant_raws)
        ).hexdigest(),
        "contract_version": CONTRACT_VERSION,
        "data_invariants": invariants,
        "domains": domains,
        "environment_attestation_complete": False,
        "ledgers": dict(ledgers),
        "operational_authorization": False,
        "pre_capture_binding": {
            "authorization_record_sha256": authorization_record,
            "environment": environment,
            "hmac_sha256": receipt["hmac_sha256"],
            "nonce_sha256": receipt["nonce_sha256"],
            "target_binding_sha256": target_binding,
            "target_binding_contract": TARGET_BINDING_CONTRACT,
        },
        "profile_sha256": PROFILE_SHA256,
        "source": {
            "canonical_schema_fingerprint_sha256": profile["canonical_schema_fingerprint_sha256"],
            "capture_sql_sha256": CAPTURE_SQL_SHA256,
            "source_catalog_digest_sha256": profile["source_catalog_digest_sha256"],
        },
        "surfaces": {
            "data_api": "PLATFORM_SURFACES_UNATTESTED",
            "realtime": "PLATFORM_SURFACES_UNATTESTED",
        },
        "unknown_owners": unknown,
    }
    serialized = _canonical_bytes(artifact).decode("ascii").casefold()
    if any(key in serialized for key in ("postgresql://", "postgres://")):
        raise CaptureError
    path = _atomic_write(
        output_dir, ARTIFACT_BASENAMES[environment], artifact,
        allowed_existing={binding_basename},
        continuity_witness=receipt_witness,
    )
    return path, True


def _parse_invariant_descriptors(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        if type(value) is not str or value.count("=") != 1:
            raise UsageError
        identifier, raw_descriptor = value.split("=", 1)
        if identifier in result or not raw_descriptor.isascii() or not raw_descriptor.isdecimal():
            raise UsageError
        descriptor = int(raw_descriptor)
        if descriptor < 3:
            raise UsageError
        result[identifier] = descriptor
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = SanitizedArgumentParser(add_help=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("bind-target", "materialize"):
        child = subparsers.add_parser(command, add_help=False)
        child.add_argument("--environment", required=True, choices=sorted(CONFIRMATIONS))
        child.add_argument("--expected-target-fd", required=True, type=int)
        child.add_argument("--authorization-record-sha256", required=True)
        child.add_argument("--nonce", required=True)
        child.add_argument("--hmac-key-fd", required=True, type=int)
        child.add_argument("--output-dir", required=True, type=Path)
        child.add_argument("--confirmation", required=True)
        if command == "bind-target":
            child.add_argument("--identity-fd", required=True, type=int)
        else:
            child.add_argument("--metadata-capture-fd", required=True, type=int)
            child.add_argument(
                "--invariant-result-fd", required=True, action="append"
            )
    return parser


def main(argv: list[str] | None = None) -> int:
    print(OPERATIONAL_BLOCK)
    try:
        args = build_parser().parse_args(argv)
        if args.confirmation != CONFIRMATIONS[args.environment]:
            raise UsageError
        authorization = _validate_hash(args.authorization_record_sha256)
        nonce = _validate_nonce(args.nonce)
        if args.command == "bind-target":
            bind_target(
                environment=args.environment, authorization_record=authorization,
                nonce=nonce, expected_target_fd=args.expected_target_fd,
                identity_fd=args.identity_fd, hmac_key_fd=args.hmac_key_fd,
                output_dir=args.output_dir,
            )
            print("PRE_CAPTURE_TARGET_BINDING_CREATED_OFFLINE_ONLY")
            return 0
        _path, blocked = materialize(
            environment=args.environment, authorization_record=authorization,
            nonce=nonce, expected_target_fd=args.expected_target_fd,
            metadata_capture_fd=args.metadata_capture_fd,
            hmac_key_fd=args.hmac_key_fd,
            invariant_result_fds=_parse_invariant_descriptors(
                args.invariant_result_fd
            ),
            output_dir=args.output_dir,
        )
        print("ENVIRONMENT_ATTESTATION_COMPLETE=false")
        if blocked:
            print("ENVIRONMENT_SCHEMA_EVIDENCE_MATERIALIZED_BLOCKED")
            return EvidenceBlocked.exit_code
        print("ENVIRONMENT_SCHEMA_METADATA_MATCH_PLATFORM_SURFACES_UNATTESTED")
        return 0
    except AttestationError as exc:
        print(f"ENVIRONMENT_ATTESTATION_BLOCKED:{exc.reason}", file=sys.stderr)
        return exc.exit_code
    except Exception:
        print("ENVIRONMENT_ATTESTATION_BLOCKED:INTERNAL_ERROR", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
