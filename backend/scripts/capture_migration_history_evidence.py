#!/usr/bin/env python3
"""Materializa, offline, uma captura sanitizada dos ledgers de migrations.

O SQL allowlisted e versionado e executado por um canal nominal separado. Este
programa nao conecta a banco ou rede: recebe apenas o JSON sanitizado por um
descritor, valida contrato, alvo e proveniencia e cria um pacote bloqueado e
dois recibos externos com exclusividade no filesystem local.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import hmac
import json
import os
import pathlib
import re
import stat
import struct
import sys
from dataclasses import dataclass
from typing import Any, NoReturn


SCRIPT_PATH = pathlib.Path(__file__).absolute()
REPO_ROOT = SCRIPT_PATH.parents[2]
MIGRATIONS_DIR = REPO_ROOT / "backend" / "migrations"
PACKETS_DIR = REPO_ROOT / "docs" / "governance" / "migrations" / "packets"
CAPTURE_SQL_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-inventory-capture-v1.sql"
)

CAPTURE_SQL_SHA256 = "8b589e5dda722691fead34cbd63cab75a7a22f32e0cf4bdfe64d6cef603866ee"
EXPECTED_REPOSITORY_SHA = "656d1d9eebe90ad4b2cbb35c21939a6796c46bfe"
EXPECTED_CATALOG_DIGEST_SHA256 = (
    "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f"
)
CANONICAL_OUTPUT_BASENAMES = {
    "DEV": "migration-history-reconciliation-dev-evidence-v1.json",
    "PROD": "migration-history-reconciliation-prod-evidence-v1.json",
}
CONFIRMATION = "MATERIALIZE_MIGRATION_HISTORY_EVIDENCE"
CAPTURE_CONTRACT = "MIGRATION_HISTORY_INVENTORY_CAPTURE_V1"
CONTRACT_VERSION = "1.0"
CATALOG_PATH = "backend/migrations"
CATALOG_ALGORITHM = "basename-ascii-ascending+sha256-raw-bytes-v1"
PUBLIC_SOURCE = "public.schema_migrations"
NATIVE_SOURCE = "supabase_migrations.schema_migrations"
PUBLIC_QUERY_CONTRACT = (
    "PUBLIC_LEDGER_V1|ISOLATION=REPEATABLE_READ_READ_ONLY|"
    "ORDER=applied_at_ASC,name_ASC|PROJECTION=position,name"
)
NATIVE_QUERY_CONTRACT = (
    "NATIVE_LEDGER_V1|ISOLATION=REPEATABLE_READ_READ_ONLY|"
    "ORDER=version_ASC|PROJECTION=position,version,name_NULL_REDACTED"
)

MAX_INPUT_BYTES = 1_048_576
MAX_PACKET_BYTES = 524_288
MAX_RECEIPT_BYTES = 65_536
MAX_MIGRATION_BYTES = 4_194_304
MAX_CATALOG_BYTES = 67_108_864
MAX_CATALOG_FILES = 2_048
MAX_CAPTURE_ROWS = 2_048
MAX_JSON_DEPTH = 6
MAX_JSON_NODES = 20_000
MAX_JSON_STRING = 65_536

MIGRATION_BASENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.sql$")
NATIVE_VERSION_RE = re.compile(r"^[0-9]{14}$")
NATIVE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,126}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SYSTEM_IDENTIFIER_RE = re.compile(r"^[1-9][0-9]{0,19}$")
SNAPSHOT_RE = re.compile(r"^[0-9]+:[0-9]+:(?:[0-9]+(?:,[0-9]+)*)?$")
UTC_TIMESTAMP_RE = re.compile(
    r"^(?:[0-9]{4})-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
    r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,6})?Z$"
)

SAFETY_CONTRACT = {
    "offline_only": True,
    "database_connection": "BLOCKED",
    "database_mutation": "BLOCKED",
    "migration_application": "BLOCKED",
    "ledger_write": "BLOCKED",
    "runner_unlock": "BLOCKED",
    "environment_operation": "BLOCKED",
    "applied_history_inference": "BLOCKED",
}

CAPTURE_KEYS = {
    "capture_contract",
    "server_version_num",
    "current_user_matches_session_user",
    "system_identifier",
    "database_name",
    "captured_at_utc",
    "snapshot_token",
    "isolation_level",
    "read_only",
    "public_relation_count",
    "public_relkind",
    "public_columns_ok",
    "public_row_security_active",
    "public_rule_count",
    "public_trigger_count",
    "public_rows",
    "native_relation_count",
    "native_relkind",
    "native_has_version",
    "native_has_name",
    "native_name_column_present",
    "native_row_security_active",
    "native_rule_count",
    "native_trigger_count",
    "native_rows",
}

OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
USAGE_ERROR = "MIGRATION_HISTORY_CAPTURE_BLOCKED:USAGE"
HELP_TEXT = (
    "usage: capture_migration_history_evidence.py --environment DEV|PROD "
    "--expected-target-binding-sha256 <64hex> "
    "--authorization-record-sha256 <64hex> "
    f"--confirm {CONFIRMATION} --target-key-fd <fd> [--input-fd <fd>]\n"
    "Offline materializer; it never connects to a database or network."
)


class CaptureError(RuntimeError):
    exit_code = 10
    reason = "INTERNAL_ERROR"


class LayoutError(CaptureError):
    exit_code = 3
    reason = "LOCAL_LAYOUT_INVALID"


class InputError(CaptureError):
    exit_code = 4
    reason = "SANITIZED_INPUT_INVALID"


class SqlContractError(CaptureError):
    exit_code = 5
    reason = "CAPTURE_SQL_INVALID"


class TargetBindingError(CaptureError):
    exit_code = 6
    reason = "TARGET_BINDING_INVALID"


class InventoryError(CaptureError):
    exit_code = 7
    reason = "INVENTORY_CAPTURE_INVALID"


class OutputError(CaptureError):
    exit_code = 8
    reason = "OUTPUT_INVALID"


class CatalogError(CaptureError):
    exit_code = 9
    reason = "CATALOG_DRIFT"


class CliUsageError(RuntimeError):
    """Parser error whose text is never returned to the operator."""


class SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise CliUsageError


@dataclass(frozen=True)
class FileSnapshot:
    device: int
    inode: int
    mode: int
    links: int
    uid: int
    gid: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> "FileSnapshot":
        return cls(
            device=int(value.st_dev),
            inode=int(value.st_ino),
            mode=int(value.st_mode),
            links=int(value.st_nlink),
            uid=int(value.st_uid),
            gid=int(value.st_gid),
            size=int(value.st_size),
            mtime_ns=int(value.st_mtime_ns),
            ctime_ns=int(value.st_ctime_ns),
        )


def _blocked(error: CaptureError) -> int:
    print(OPERATIONAL_BLOCK, file=sys.stderr)
    print(f"MIGRATION_HISTORY_CAPTURE_BLOCKED:{error.reason}", file=sys.stderr)
    return error.exit_code


def _frame(tag: bytes, payload: bytes) -> bytes:
    if len(tag) != 1:
        raise ValueError("invalid internal frame tag")
    return tag + struct.pack(">Q", len(payload)) + payload


def _encode_framed(value: Any) -> bytes:
    if value is None:
        return _frame(b"N", b"")
    if type(value) is bool:
        return _frame(b"B", b"\x01" if value else b"\x00")
    if type(value) is int:
        return _frame(b"I", str(value).encode("ascii"))
    if type(value) is str:
        return _frame(b"S", value.encode("utf-8"))
    if type(value) is list:
        payload = struct.pack(">Q", len(value))
        payload += b"".join(_encode_framed(item) for item in value)
        return _frame(b"L", payload)
    if type(value) is dict:
        items: list[tuple[bytes, bytes]] = []
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("invalid internal mapping key")
            items.append((key.encode("utf-8"), _encode_framed(item)))
        items.sort(key=lambda pair: pair[0])
        payload = struct.pack(">Q", len(items))
        for key, encoded in items:
            payload += _frame(b"K", key) + encoded
        return _frame(b"O", payload)
    raise ValueError("unsupported internal framing type")


def _framed_material(domain: str, value: Any) -> bytes:
    material = b"PASTORAI-MIGRATION-HISTORY\x00\x01"
    material += _frame(b"D", domain.encode("ascii"))
    material += _encode_framed(value)
    return material


def _framed_sha256(domain: str, value: Any) -> str:
    return hashlib.sha256(_framed_material(domain, value)).hexdigest()


def _directory_flags() -> int:
    required = ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
    if any(not hasattr(os, name) for name in required):
        raise LayoutError
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _read_file_flags() -> int:
    required = ("O_NOFOLLOW", "O_CLOEXEC", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required):
        raise LayoutError
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def _write_file_flags() -> int:
    required = ("O_NOFOLLOW", "O_CLOEXEC", "O_EXCL")
    if any(not hasattr(os, name) for name in required):
        raise OutputError
    return os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


def _validate_directory(
    snapshot: FileSnapshot,
    error_type: type[CaptureError],
    *,
    allow_system_sticky: bool = False,
    allow_filesystem_root: bool = False,
) -> None:
    if not stat.S_ISDIR(snapshot.mode) or snapshot.links < 2:
        raise error_type
    if allow_system_sticky and snapshot.mode & stat.S_ISVTX:
        return
    if allow_filesystem_root:
        if snapshot.mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise error_type
        return
    own = snapshot.uid == os.geteuid() and snapshot.gid == os.getegid()
    root = snapshot.uid == 0 and snapshot.gid == 0
    if not own and not root:
        raise error_type
    if snapshot.mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise error_type


def _open_directory(
    path: pathlib.Path, error_type: type[CaptureError]
) -> tuple[int, FileSnapshot]:
    if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts[1:]):
        raise error_type
    try:
        descriptor = os.open(os.sep, _directory_flags())
    except (OSError, ValueError) as exc:
        raise error_type from exc
    try:
        snapshot = FileSnapshot.from_stat(os.fstat(descriptor))
        _validate_directory(snapshot, error_type, allow_filesystem_root=True)
        for index, component in enumerate(path.parts[1:]):
            child = os.open(component, _directory_flags(), dir_fd=descriptor)
            try:
                snapshot = FileSnapshot.from_stat(os.fstat(child))
                named = FileSnapshot.from_stat(
                    os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                )
                if snapshot != named:
                    raise error_type
                _validate_directory(
                    snapshot,
                    error_type,
                    allow_system_sticky=index == 0 and component == "tmp",
                )
            except Exception:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        return descriptor, snapshot
    except Exception as exc:
        os.close(descriptor)
        if isinstance(exc, CaptureError):
            raise
        raise error_type from exc


def _read_fd_bytes(descriptor: int, maximum_size: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            chunk = os.read(descriptor, min(65_536, maximum_size + 1 - total))
        except OSError as exc:
            raise InputError from exc
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum_size:
            raise InputError
    return b"".join(chunks)


def _read_regular_at(
    directory_fd: int,
    basename: str,
    *,
    maximum_size: int,
    error_type: type[CaptureError],
) -> tuple[bytes, FileSnapshot]:
    try:
        descriptor = os.open(basename, _read_file_flags(), dir_fd=directory_fd)
    except (OSError, ValueError) as exc:
        raise error_type from exc
    try:
        before = FileSnapshot.from_stat(os.fstat(descriptor))
        if (
            not stat.S_ISREG(before.mode)
            or before.links != 1
            or before.uid != os.geteuid()
            or before.gid != os.getegid()
            or before.mode & (stat.S_IWGRP | stat.S_IWOTH)
            or before.size < 0
            or before.size > maximum_size
        ):
            raise error_type
        content = _read_fd_bytes_for_file(descriptor, before.size, maximum_size, error_type)
        after = FileSnapshot.from_stat(os.fstat(descriptor))
        named = FileSnapshot.from_stat(
            os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
        )
        if before != after or before != named:
            raise error_type
        return content, before
    except OSError as exc:
        raise error_type from exc
    finally:
        os.close(descriptor)


def _read_fd_bytes_for_file(
    descriptor: int,
    expected_size: int,
    maximum_size: int,
    error_type: type[CaptureError],
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            chunk = os.read(descriptor, min(65_536, maximum_size + 1 - total))
        except OSError as exc:
            raise error_type from exc
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum_size:
            raise error_type
    if total != expected_size:
        raise error_type
    return b"".join(chunks)


def _validate_runtime_and_sql() -> bytes:
    for path, maximum, error_type in (
        (SCRIPT_PATH, MAX_PACKET_BYTES, LayoutError),
        (CAPTURE_SQL_PATH, MAX_PACKET_BYTES, SqlContractError),
    ):
        directory_fd, before = _open_directory(path.parent, error_type)
        try:
            content, _snapshot = _read_regular_at(
                directory_fd,
                path.name,
                maximum_size=maximum,
                error_type=error_type,
            )
            if FileSnapshot.from_stat(os.fstat(directory_fd)) != before:
                raise error_type
        finally:
            os.close(directory_fd)
        if path == CAPTURE_SQL_PATH:
            sql_bytes = content
    if not hmac.compare_digest(hashlib.sha256(sql_bytes).hexdigest(), CAPTURE_SQL_SHA256):
        raise SqlContractError
    if not sql_bytes.endswith(b"\nrollback;\n"):
        raise SqlContractError
    return sql_bytes


def _scan_catalog() -> list[dict[str, Any]]:
    directory_fd, before = _open_directory(MIGRATIONS_DIR, CatalogError)
    try:
        first = sorted(os.listdir(directory_fd))
        names = sorted(name for name in first if name.endswith(".sql"))
        if not names or len(names) > MAX_CATALOG_FILES:
            raise CatalogError
        if any(not MIGRATION_BASENAME_RE.fullmatch(name) for name in names):
            raise CatalogError
        if len(names) != len(set(names)) or len(names) != len({n.casefold() for n in names}):
            raise CatalogError
        entries: list[dict[str, Any]] = []
        snapshots: dict[str, FileSnapshot] = {}
        total = 0
        for position, name in enumerate(names):
            content, snapshot = _read_regular_at(
                directory_fd,
                name,
                maximum_size=MAX_MIGRATION_BYTES,
                error_type=CatalogError,
            )
            total += snapshot.size
            if total > MAX_CATALOG_BYTES:
                raise CatalogError
            snapshots[name] = snapshot
            entries.append(
                {
                    "position": position,
                    "name": name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": snapshot.size,
                }
            )
        if sorted(os.listdir(directory_fd)) != first:
            raise CatalogError
        for name, expected in snapshots.items():
            actual = FileSnapshot.from_stat(
                os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            )
            if actual != expected:
                raise CatalogError
        if FileSnapshot.from_stat(os.fstat(directory_fd)) != before:
            raise CatalogError
        return entries
    except OSError as exc:
        raise CatalogError from exc
    finally:
        os.close(directory_fd)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError
        result[key] = value
    return result


def _reject_number(_value: str) -> NoReturn:
    raise InputError


def _parse_input(content: bytes) -> dict[str, Any]:
    if not content or content.startswith(b"\xef\xbb\xbf"):
        raise InputError
    try:
        value = json.loads(
            content.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_number,
            parse_float=_reject_number,
        )
    except CaptureError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise InputError from exc
    stack: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise InputError
        if type(item) is str:
            if len(item) > MAX_JSON_STRING or not item.isascii():
                raise InputError
        elif type(item) is list:
            stack.extend((nested, depth + 1) for nested in item)
        elif type(item) is dict:
            stack.extend((nested, depth + 1) for nested in item.values())
        elif item is not None and type(item) not in (bool, int):
            raise InputError
    if type(value) is not dict or set(value) != CAPTURE_KEYS:
        raise InputError
    return value


def _read_sanitized_input(input_fd: int) -> bytes:
    try:
        snapshot = FileSnapshot.from_stat(os.fstat(input_fd))
    except OSError as exc:
        raise InputError from exc
    if stat.S_ISREG(snapshot.mode):
        if (
            snapshot.links != 1
            or snapshot.uid != os.geteuid()
            or snapshot.gid != os.getegid()
            or stat.S_IMODE(snapshot.mode) != 0o600
            or snapshot.size < 1
            or snapshot.size > MAX_INPUT_BYTES
        ):
            raise InputError
        try:
            if os.lseek(input_fd, 0, os.SEEK_CUR) != 0:
                raise InputError
        except OSError as exc:
            raise InputError from exc
    elif not stat.S_ISFIFO(snapshot.mode):
        raise InputError
    content = _read_fd_bytes(input_fd, MAX_INPUT_BYTES)
    if stat.S_ISREG(snapshot.mode):
        try:
            after = FileSnapshot.from_stat(os.fstat(input_fd))
        except OSError as exc:
            raise InputError from exc
        if after != snapshot:
            raise InputError
    return content


def _read_target_key(target_key_fd: int) -> bytearray:
    try:
        snapshot = FileSnapshot.from_stat(os.fstat(target_key_fd))
    except OSError as exc:
        raise TargetBindingError from exc
    if stat.S_ISREG(snapshot.mode):
        if (
            snapshot.links != 1
            or snapshot.uid != os.geteuid()
            or snapshot.gid != os.getegid()
            or stat.S_IMODE(snapshot.mode) != 0o600
            or snapshot.size not in {32, 64}
        ):
            raise TargetBindingError
        try:
            if os.lseek(target_key_fd, 0, os.SEEK_CUR) != 0:
                raise TargetBindingError
        except OSError as exc:
            raise TargetBindingError from exc
    elif not stat.S_ISFIFO(snapshot.mode):
        raise TargetBindingError
    try:
        raw = _read_fd_bytes(target_key_fd, 64)
    except InputError as exc:
        raise TargetBindingError from exc
    if stat.S_ISREG(snapshot.mode):
        try:
            after = FileSnapshot.from_stat(os.fstat(target_key_fd))
        except OSError as exc:
            raise TargetBindingError from exc
        if after != snapshot:
            raise TargetBindingError
    if len(raw) == 32:
        result = bytearray(raw)
        if not any(result):
            raise TargetBindingError
        return result
    if len(raw) == 64:
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise TargetBindingError from exc
        if not SHA256_RE.fullmatch(text):
            raise TargetBindingError
        result = bytearray.fromhex(text)
        if not any(result):
            raise TargetBindingError
        return result
    raise TargetBindingError


def _string(value: Any, pattern: re.Pattern[str] | None = None) -> str:
    if type(value) is not str or not value or len(value) > MAX_JSON_STRING:
        raise InventoryError
    if pattern is not None and not pattern.fullmatch(value):
        raise InventoryError
    return value


def _integer(value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise InventoryError
    return value


def _timestamp(value: Any) -> str:
    result = _string(value, UTC_TIMESTAMP_RE)
    try:
        datetime.fromisoformat(result.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise InventoryError from exc
    return result


def _public_rows(value: Any) -> list[dict[str, Any]]:
    if type(value) is not list or len(value) > MAX_CAPTURE_ROWS + 1:
        raise InventoryError
    if len(value) > MAX_CAPTURE_ROWS:
        raise InventoryError
    rows: list[dict[str, Any]] = []
    names: list[str] = []
    for position, raw in enumerate(value):
        if type(raw) is not dict or set(raw) != {"position", "name"}:
            raise InventoryError
        if _integer(raw["position"], 0, MAX_CAPTURE_ROWS) != position:
            raise InventoryError
        name = _string(raw["name"], MIGRATION_BASENAME_RE)
        names.append(name)
        rows.append({"position": position, "name": name})
    if len(names) != len(set(names)):
        raise InventoryError
    return rows


def _native_rows(value: Any) -> list[dict[str, Any]]:
    if type(value) is not list or len(value) > MAX_CAPTURE_ROWS + 1:
        raise InventoryError
    if len(value) > MAX_CAPTURE_ROWS:
        raise InventoryError
    rows: list[dict[str, Any]] = []
    versions: list[str] = []
    for position, raw in enumerate(value):
        if type(raw) is not dict or set(raw) != {"position", "version", "name"}:
            raise InventoryError
        if _integer(raw["position"], 0, MAX_CAPTURE_ROWS) != position:
            raise InventoryError
        version = _string(raw["version"], NATIVE_VERSION_RE)
        try:
            datetime.strptime(version, "%Y%m%d%H%M%S")
        except ValueError as exc:
            raise InventoryError from exc
        raw_name = raw["name"]
        name = None if raw_name is None else _string(raw_name, NATIVE_NAME_RE)
        versions.append(version)
        rows.append({"position": position, "version": version, "name": name})
    if versions != sorted(set(versions)):
        raise InventoryError
    return rows


def _relation_state(
    capture: dict[str, Any], prefix: str, rows: list[dict[str, Any]]
) -> str:
    count = _integer(capture[f"{prefix}_relation_count"], 0, 1)
    relkind = capture[f"{prefix}_relkind"]
    row_security = capture[f"{prefix}_row_security_active"]
    rule_count = _integer(capture[f"{prefix}_rule_count"], 0, 2_147_483_647)
    trigger_count = _integer(capture[f"{prefix}_trigger_count"], 0, 2_147_483_647)
    if count == 0:
        if relkind is not None or row_security is not None or rule_count or trigger_count or rows:
            raise InventoryError
        if prefix == "public" and capture["public_columns_ok"] is not False:
            raise InventoryError
        if prefix == "native" and any(
            capture[key] is not False
            for key in (
                "native_has_version",
                "native_has_name",
                "native_name_column_present",
            )
        ):
            raise InventoryError
        return "ABSENT_CONFIRMED"
    if relkind != "r" or row_security is not False or rule_count or trigger_count:
        raise InventoryError
    if prefix == "public":
        if capture["public_columns_ok"] is not True:
            raise InventoryError
    else:
        if capture["native_has_version"] is not True:
            raise InventoryError
        name_present = capture["native_name_column_present"]
        has_name = capture["native_has_name"]
        if type(name_present) is not bool or type(has_name) is not bool:
            raise InventoryError
        if name_present != has_name:
            raise InventoryError
    return "PRESENT_COMPLETE"


def _validate_capture(raw: dict[str, Any]) -> dict[str, Any]:
    if raw["capture_contract"] != CAPTURE_CONTRACT:
        raise InventoryError
    version = _integer(raw["server_version_num"], 170000, 179999)
    if raw["current_user_matches_session_user"] is not True:
        raise InventoryError
    system_identifier = _string(raw["system_identifier"], SYSTEM_IDENTIFIER_RE)
    database_name = _string(raw["database_name"])
    if len(database_name.encode("ascii")) > 63 or any(
        ord(character) < 0x20 or ord(character) > 0x7E for character in database_name
    ):
        raise InventoryError
    captured_at = _timestamp(raw["captured_at_utc"])
    snapshot_token = _string(raw["snapshot_token"], SNAPSHOT_RE)
    if raw["isolation_level"] != "repeatable read" or raw["read_only"] != "on":
        raise InventoryError
    public_rows = _public_rows(raw["public_rows"])
    native_rows = _native_rows(raw["native_rows"])
    public_state = _relation_state(raw, "public", public_rows)
    native_state = _relation_state(raw, "native", native_rows)
    return {
        "server_version_num": version,
        "system_identifier": system_identifier,
        "database_name": database_name,
        "captured_at_utc": captured_at,
        "snapshot_token": snapshot_token,
        "public_state": public_state,
        "public_rows": public_rows,
        "native_state": native_state,
        "native_rows": native_rows,
    }


def _target_binding(
    key: bytearray, environment: str, capture: dict[str, Any]
) -> str:
    material = _framed_material(
        "pastorai/migration-history/target-binding/v1",
        {
            "environment": environment,
            "system_identifier": capture["system_identifier"],
            "database_name": capture["database_name"],
        },
    )
    return hmac.new(bytes(key), material, hashlib.sha256).hexdigest()


def _inventory(
    *,
    source: str,
    state: str,
    target_binding: str,
    captured_at: str,
    authorization_record: str,
    capture_record: str,
    snapshot_record: str,
    query_contract: str,
    rows: list[dict[str, Any]],
    rows_digest: str,
) -> dict[str, Any]:
    return {
        "source": source,
        "capture_state": state,
        "target_binding_sha256": target_binding,
        "captured_at_utc": captured_at,
        "authorization_record_sha256": authorization_record,
        "capture_record_sha256": capture_record,
        "snapshot_record_sha256": snapshot_record,
        "completeness_attested": True,
        "query_contract": query_contract,
        "rows": rows,
        "rows_digest_sha256": rows_digest,
    }


def _sanitize_native_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "position": row["position"],
            "version": row["version"],
            "name": None,
        }
        for row in rows
    ]


def _catalog_digest(catalog_entries: list[dict[str, Any]]) -> str:
    return _framed_sha256(
        "pastorai/migration-history/catalog/v1",
        {"algorithm": CATALOG_ALGORITHM, "entries": catalog_entries},
    )


def _require_public_catalog_prefix(
    public_rows: list[dict[str, Any]], catalog_entries: list[dict[str, Any]]
) -> None:
    public_names = [row["name"] for row in public_rows]
    catalog_names = [entry["name"] for entry in catalog_entries]
    if public_names != catalog_names[: len(public_names)]:
        raise InventoryError


def _build_artifacts(
    *,
    environment: str,
    authorization_record: str,
    target_binding: str,
    catalog_entries: list[dict[str, Any]],
    capture: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    package_id = CANONICAL_OUTPUT_BASENAMES[environment][:-5]
    native_rows = _sanitize_native_rows(capture["native_rows"])
    public_rows_digest = _framed_sha256(
        "pastorai/migration-history/public-ledger/v1",
        {
            "source": PUBLIC_SOURCE,
            "query_contract": PUBLIC_QUERY_CONTRACT,
            "rows": capture["public_rows"],
        },
    )
    native_rows_digest = _framed_sha256(
        "pastorai/migration-history/native-ledger/v1",
        {
            "source": NATIVE_SOURCE,
            "query_contract": NATIVE_QUERY_CONTRACT,
            "rows": native_rows,
        },
    )
    snapshot_token_digest = _framed_sha256(
        "pastorai/migration-history/postgres-snapshot-token/v1",
        {"snapshot_token": capture["snapshot_token"]},
    )
    snapshot_preimage = {
        "capture_sql_sha256": CAPTURE_SQL_SHA256,
        "package_id": package_id,
        "repository_sha": EXPECTED_REPOSITORY_SHA,
        "environment": environment,
        "target_binding_sha256": target_binding,
        "captured_at_utc": capture["captured_at_utc"],
        "postgres_major": 17,
        "isolation_level": "repeatable read",
        "read_only": True,
        "snapshot_token_sha256": snapshot_token_digest,
        "public_rows_digest_sha256": public_rows_digest,
        "native_rows_digest_sha256": native_rows_digest,
    }
    snapshot_record = _framed_sha256(
        "pastorai/migration-history/snapshot-record/v1", snapshot_preimage
    )

    def capture_record(
        source: str, state: str, query_contract: str, rows_digest: str
    ) -> tuple[str, dict[str, Any]]:
        preimage = {
            "capture_sql_sha256": CAPTURE_SQL_SHA256,
            "package_id": package_id,
            "repository_sha": EXPECTED_REPOSITORY_SHA,
            "authorization_record_sha256": authorization_record,
            "environment": environment,
            "target_binding_sha256": target_binding,
            "captured_at_utc": capture["captured_at_utc"],
            "snapshot_record_sha256": snapshot_record,
            "source": source,
            "capture_state": state,
            "completeness_attested": True,
            "query_contract": query_contract,
            "rows_digest_sha256": rows_digest,
        }
        domain = (
            "pastorai/migration-history/capture-record/public/v1"
            if source == PUBLIC_SOURCE
            else "pastorai/migration-history/capture-record/native/v1"
        )
        return _framed_sha256(domain, preimage), preimage

    public_record, public_preimage = capture_record(
        PUBLIC_SOURCE,
        capture["public_state"],
        PUBLIC_QUERY_CONTRACT,
        public_rows_digest,
    )
    native_record, native_preimage = capture_record(
        NATIVE_SOURCE,
        capture["native_state"],
        NATIVE_QUERY_CONTRACT,
        native_rows_digest,
    )
    if (
        public_record == native_record
        or snapshot_record in {authorization_record, public_record, native_record}
        or authorization_record in {public_record, native_record}
    ):
        raise InventoryError
    catalog = {
        "algorithm": CATALOG_ALGORITHM,
        "entries": catalog_entries,
        "digest_sha256": _catalog_digest(catalog_entries),
    }
    package = {
        "contract_version": CONTRACT_VERSION,
        "package_id": package_id,
        "artifact_state": "EVIDENCE_CAPTURED_UNREVIEWED",
        "safety_contract": dict(SAFETY_CONTRACT),
        "subject": {
            "environment": environment,
            "target_binding_sha256": target_binding,
            "repository_sha": EXPECTED_REPOSITORY_SHA,
            "catalog_path": CATALOG_PATH,
        },
        "catalog": catalog,
        "inventories": {
            "public_ledger": _inventory(
                source=PUBLIC_SOURCE,
                state=capture["public_state"],
                target_binding=target_binding,
                captured_at=capture["captured_at_utc"],
                authorization_record=authorization_record,
                capture_record=public_record,
                snapshot_record=snapshot_record,
                query_contract=PUBLIC_QUERY_CONTRACT,
                rows=capture["public_rows"],
                rows_digest=public_rows_digest,
            ),
            "native_ledger": _inventory(
                source=NATIVE_SOURCE,
                state=capture["native_state"],
                target_binding=target_binding,
                captured_at=capture["captured_at_utc"],
                authorization_record=authorization_record,
                capture_record=native_record,
                snapshot_record=snapshot_record,
                query_contract=NATIVE_QUERY_CONTRACT,
                rows=native_rows,
                rows_digest=native_rows_digest,
            ),
        },
        "reconciliation": {
            "state": "NOT_REVIEWED",
            "catalog_entries": [],
            "native_rows": [],
        },
        "attestation": {
            "state": "NOT_ATTESTED",
            "inventory_attestation_record_sha256": None,
            "migration_owner_decision_record_sha256": None,
            "independent_review_record_sha256": None,
            "attested_at_utc": None,
            "payload_sha256": None,
        },
    }

    def receipt(role: str, capture_sha: str, preimage: dict[str, Any]) -> dict[str, Any]:
        return {
            "receipt_version": CONTRACT_VERSION,
            "receipt_role": role,
            "safety_contract": dict(SAFETY_CONTRACT),
            "subject": {
                "environment": environment,
                "target_binding_sha256": target_binding,
                "repository_sha": EXPECTED_REPOSITORY_SHA,
            },
            "capture_sql_sha256": CAPTURE_SQL_SHA256,
            "authorization_record_sha256": authorization_record,
            "snapshot_record": {
                "snapshot_record_sha256": snapshot_record,
                "preimage": snapshot_preimage,
            },
            "capture_record": {
                "capture_record_sha256": capture_sha,
                "preimage": preimage,
            },
        }

    return (
        package,
        receipt("PUBLIC_LEDGER_CAPTURE", public_record, public_preimage),
        receipt("NATIVE_LEDGER_CAPTURE", native_record, native_preimage),
    )


def _json_bytes(value: dict[str, Any], maximum: int) -> bytes:
    encoded = (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("ascii")
    if len(encoded) > maximum:
        raise OutputError
    return encoded


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OutputError
        offset += written


def _materialize(outputs: dict[str, bytes]) -> None:
    directory_fd, before = _open_directory(PACKETS_DIR, OutputError)
    descriptors: dict[str, int] = {}
    created: dict[str, FileSnapshot] = {}
    final_files: dict[str, FileSnapshot] = {}
    descriptor_digests: dict[str, str] = {}
    try:
        for name in outputs:
            try:
                os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise OutputError
        for name in outputs:
            descriptor = os.open(name, _write_file_flags(), 0o600, dir_fd=directory_fd)
            descriptors[name] = descriptor
            snapshot = FileSnapshot.from_stat(os.fstat(descriptor))
            if (
                not stat.S_ISREG(snapshot.mode)
                or snapshot.links != 1
                or snapshot.uid != os.geteuid()
                or snapshot.gid != os.getegid()
                or stat.S_IMODE(snapshot.mode) != 0o600
                or snapshot.size != 0
            ):
                raise OutputError
            created[name] = snapshot
        secured_directory = FileSnapshot.from_stat(os.fstat(directory_fd))
        _validate_directory(secured_directory, OutputError)
        for name, content in outputs.items():
            descriptor = descriptors[name]
            _write_all(descriptor, content)
            os.fsync(descriptor)
            after = FileSnapshot.from_stat(os.fstat(descriptor))
            named = FileSnapshot.from_stat(
                os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            )
            if (
                after.device != created[name].device
                or after.inode != created[name].inode
                or not stat.S_ISREG(after.mode)
                or after.links != 1
                or after.uid != os.geteuid()
                or after.gid != os.getegid()
                or after.size != len(content)
                or stat.S_IMODE(after.mode) != 0o600
                or after != named
            ):
                raise OutputError
        os.fsync(directory_fd)
        for name, descriptor in descriptors.items():
            final_fd = FileSnapshot.from_stat(os.fstat(descriptor))
            final_named = FileSnapshot.from_stat(
                os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            )
            if (
                final_fd != final_named
                or not stat.S_ISREG(final_fd.mode)
                or final_fd.links != 1
                or final_fd.uid != os.geteuid()
                or final_fd.gid != os.getegid()
                or stat.S_IMODE(final_fd.mode) != 0o600
                or final_fd.size != len(outputs[name])
            ):
                raise OutputError
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
            except OSError as exc:
                raise OutputError from exc
            descriptor_content = _read_fd_bytes_for_file(
                descriptor, final_fd.size, MAX_PACKET_BYTES, OutputError
            )
            if FileSnapshot.from_stat(os.fstat(descriptor)) != final_fd:
                raise OutputError
            descriptor_digest = hashlib.sha256(descriptor_content).hexdigest()
            if not hmac.compare_digest(
                descriptor_digest, hashlib.sha256(outputs[name]).hexdigest()
            ):
                raise OutputError
            final_files[name] = final_fd
            descriptor_digests[name] = descriptor_digest
        final_directory = FileSnapshot.from_stat(os.fstat(directory_fd))
        if final_directory != secured_directory or final_directory == before:
            raise OutputError
        _validate_directory(final_directory, OutputError)
        reopened_fd, reopened_directory = _open_directory(PACKETS_DIR, OutputError)
        try:
            if (
                reopened_directory != final_directory
                or reopened_directory.device != final_directory.device
                or reopened_directory.inode != final_directory.inode
            ):
                raise OutputError
            _validate_directory(reopened_directory, OutputError)
            for name, expected in final_files.items():
                path_content, path_snapshot = _read_regular_at(
                    reopened_fd,
                    name,
                    maximum_size=MAX_PACKET_BYTES,
                    error_type=OutputError,
                )
                if (
                    path_snapshot != expected
                    or not stat.S_ISREG(path_snapshot.mode)
                    or path_snapshot.links != 1
                    or path_snapshot.uid != os.geteuid()
                    or path_snapshot.gid != os.getegid()
                    or stat.S_IMODE(path_snapshot.mode) != 0o600
                    or path_snapshot.size != len(outputs[name])
                    or FileSnapshot.from_stat(os.fstat(descriptors[name]))
                    != expected
                    or not hmac.compare_digest(
                        hashlib.sha256(path_content).hexdigest(),
                        descriptor_digests[name],
                    )
                ):
                    raise OutputError
            if (
                FileSnapshot.from_stat(os.fstat(directory_fd)) != final_directory
                or FileSnapshot.from_stat(os.fstat(reopened_fd)) != final_directory
            ):
                raise OutputError
        finally:
            os.close(reopened_fd)
    except Exception as exc:
        for descriptor in descriptors.values():
            try:
                os.close(descriptor)
            except OSError:
                pass
        descriptors.clear()
        for name, expected in created.items():
            try:
                actual = FileSnapshot.from_stat(
                    os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                )
                if actual.device == expected.device and actual.inode == expected.inode:
                    os.unlink(name, dir_fd=directory_fd)
            except OSError:
                pass
        if isinstance(exc, CaptureError):
            raise
        raise OutputError from exc
    finally:
        for descriptor in descriptors.values():
            os.close(descriptor)
        os.close(directory_fd)


def build_parser() -> argparse.ArgumentParser:
    parser = SanitizedArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("--environment")
    parser.add_argument("--expected-target-binding-sha256")
    parser.add_argument("--authorization-record-sha256")
    parser.add_argument("--confirm")
    parser.add_argument("--input-fd", type=int, default=0)
    parser.add_argument("--target-key-fd", type=int)
    return parser


def _validated_args(
    args: argparse.Namespace,
) -> tuple[str, str, str, int, int]:
    if (
        args.environment not in {"DEV", "PROD"}
        or type(args.expected_target_binding_sha256) is not str
        or not SHA256_RE.fullmatch(args.expected_target_binding_sha256)
        or type(args.authorization_record_sha256) is not str
        or not SHA256_RE.fullmatch(args.authorization_record_sha256)
        or args.confirm != CONFIRMATION
        or type(args.input_fd) is not int
        or args.input_fd < 0
        or args.input_fd > 1_048_576
        or type(args.target_key_fd) is not int
        or args.target_key_fd < 0
        or args.target_key_fd > 1_048_576
        or args.target_key_fd == args.input_fd
    ):
        raise CliUsageError
    return (
        args.environment,
        args.expected_target_binding_sha256,
        args.authorization_record_sha256,
        args.input_fd,
        args.target_key_fd,
    )


def main(argv: list[str]) -> int:
    try:
        args = build_parser().parse_args(argv[1:])
        if args.help:
            print(OPERATIONAL_BLOCK)
            print(HELP_TEXT)
            return 0
        (
            environment,
            expected_target,
            authorization_record,
            input_fd,
            target_key_fd,
        ) = _validated_args(args)
    except CliUsageError:
        print(OPERATIONAL_BLOCK, file=sys.stderr)
        print(USAGE_ERROR, file=sys.stderr)
        return 2
    try:
        _validate_runtime_and_sql()
        catalog_before = _scan_catalog()
        if not hmac.compare_digest(
            _catalog_digest(catalog_before), EXPECTED_CATALOG_DIGEST_SHA256
        ):
            raise CatalogError
        capture = _validate_capture(_parse_input(_read_sanitized_input(input_fd)))
        _require_public_catalog_prefix(capture["public_rows"], catalog_before)
        key = _read_target_key(target_key_fd)
        try:
            target_binding = _target_binding(key, environment, capture)
        finally:
            key[:] = b"\x00" * len(key)
        if not hmac.compare_digest(target_binding, expected_target):
            raise TargetBindingError
        output_basename = CANONICAL_OUTPUT_BASENAMES[environment]
        package_id = output_basename[:-5]
        package, public_receipt, native_receipt = _build_artifacts(
            environment=environment,
            authorization_record=authorization_record,
            target_binding=target_binding,
            catalog_entries=catalog_before,
            capture=capture,
        )
        if _scan_catalog() != catalog_before:
            raise CatalogError
        outputs = {
            output_basename: _json_bytes(package, MAX_PACKET_BYTES),
            f"{package_id}-public-capture-receipt-v1.json": _json_bytes(
                public_receipt, MAX_RECEIPT_BYTES
            ),
            f"{package_id}-native-capture-receipt-v1.json": _json_bytes(
                native_receipt, MAX_RECEIPT_BYTES
            ),
        }
        _materialize(outputs)
    except CaptureError as error:
        return _blocked(error)
    except Exception:  # noqa: BLE001 - deliberately static, sanitized output
        return _blocked(CaptureError())
    print(OPERATIONAL_BLOCK)
    print("EVIDENCE_CAPTURED_UNREVIEWED")
    print("FILES_MATERIALIZED=3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
