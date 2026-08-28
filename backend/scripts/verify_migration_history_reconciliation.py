#!/usr/bin/env python3
"""Verifica, sem efeitos externos, um pacote humano de histórico de migrations.

O verificador lê somente um pacote JSON versionado e os bytes do catálogo local.
Ele não conecta a banco, não consulta ambiente, não executa subprocessos, não
altera arquivos e não chama o runner de migrations. Um resultado válido serve
exclusivamente para revisão humana e nunca libera operação em ambiente.
"""

from __future__ import annotations

import argparse
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
    "ORDER=version_ASC|PROJECTION=position,version,name"
)

MAX_PACKET_BYTES = 524_288
MAX_MIGRATION_BYTES = 4_194_304
MAX_CATALOG_BYTES = 67_108_864
MAX_CATALOG_FILES = 2_048
MAX_JSON_DEPTH = 8
MAX_JSON_NODES = 100_000
MAX_JSON_STRING = 4_096

PACKAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,126}$")
PACKET_BASENAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,126}\.json$")
MIGRATION_BASENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.sql$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
UTC_TIMESTAMP_RE = re.compile(
    r"^(?:[0-9]{4})-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
    r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,6})?Z$"
)
NATIVE_VERSION_RE = re.compile(r"^[0-9]{14}$")
NATIVE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,126}$")

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

TOP_LEVEL_KEYS = {
    "contract_version",
    "package_id",
    "artifact_state",
    "safety_contract",
    "subject",
    "catalog",
    "inventories",
    "reconciliation",
    "attestation",
}
SAFETY_KEYS = set(SAFETY_CONTRACT)
SUBJECT_KEYS = {
    "environment",
    "target_binding_sha256",
    "repository_sha",
    "catalog_path",
}
CATALOG_KEYS = {"algorithm", "entries", "digest_sha256"}
CATALOG_ENTRY_KEYS = {"position", "name", "sha256", "size_bytes"}
INVENTORIES_KEYS = {"public_ledger", "native_ledger"}
INVENTORY_KEYS = {
    "source",
    "capture_state",
    "target_binding_sha256",
    "captured_at_utc",
    "authorization_record_sha256",
    "capture_record_sha256",
    "snapshot_record_sha256",
    "completeness_attested",
    "query_contract",
    "rows",
    "rows_digest_sha256",
}
PUBLIC_ROW_KEYS = {"position", "name"}
NATIVE_ROW_KEYS = {"position", "version", "name"}
RECONCILIATION_KEYS = {"state", "catalog_entries", "native_rows"}
CATALOG_DECISION_KEYS = {
    "position",
    "catalog_name",
    "human_determination",
    "public_row_position",
    "native_row_positions",
    "basis_record_sha256",
    "evidence_record_sha256",
    "decision_record_sha256",
}
NATIVE_DECISION_KEYS = {
    "native_row_position",
    "disposition",
    "catalog_names",
    "basis_record_sha256",
    "evidence_record_sha256",
    "decision_record_sha256",
}
ATTESTATION_KEYS = {
    "state",
    "inventory_attestation_record_sha256",
    "migration_owner_decision_record_sha256",
    "independent_review_record_sha256",
    "attested_at_utc",
    "payload_sha256",
}

ARTIFACT_STATES = {
    "TEMPLATE_NOT_EVIDENCE",
    "EVIDENCE_CAPTURED_UNREVIEWED",
    "HUMAN_REVIEW_COMPLETE",
}
CAPTURE_STATES = {"NOT_CAPTURED", "ABSENT_CONFIRMED", "PRESENT_COMPLETE"}
RECONCILIATION_STATES = {
    "NOT_REVIEWED",
    "HUMAN_REVIEW_INCOMPLETE",
    "HUMAN_REVIEW_COMPLETE",
}
HUMAN_DETERMINATIONS = {
    "APPLIED_CONFIRMED",
    "NOT_APPLIED_CONFIRMED",
    "UNRESOLVED",
}
NATIVE_DISPOSITIONS = {
    "MAPS_TO_CATALOG",
    "NON_CATALOG_HISTORY_CONFIRMED",
    "UNRESOLVED",
}

USAGE_ERROR = "RECONCILIATION_CONTRACT_BLOCKED:USAGE"
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
HELP_TEXT = (
    "usage: verify_migration_history_reconciliation.py "
    "--packet <basename.json>\n"
    "Offline read-only verifier for a versioned human-review packet."
)


class VerificationError(RuntimeError):
    """Falha conhecida com saída estática e sanitizada."""

    exit_code = 10
    reason = "INTERNAL_ERROR"


class PacketIoError(VerificationError):
    exit_code = 3
    reason = "PACKET_IO_INVALID"


class SchemaError(VerificationError):
    exit_code = 4
    reason = "SCHEMA_INVALID"


class CatalogDriftError(VerificationError):
    exit_code = 5
    reason = "CATALOG_DRIFT"


class InventoryBlockedError(VerificationError):
    exit_code = 6
    reason = "INVENTORY_BLOCKED"


class LedgerDivergenceError(VerificationError):
    exit_code = 7
    reason = "LEDGER_DIVERGENCE"


class HumanEvidenceBlockedError(VerificationError):
    exit_code = 8
    reason = "HUMAN_EVIDENCE_BLOCKED"


class AttestationBlockedError(VerificationError):
    exit_code = 9
    reason = "ATTESTATION_BLOCKED"


class CliUsageError(RuntimeError):
    """Erro do parser que nunca contém valores fornecidos pelo operador."""


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


def _blocked(error: VerificationError) -> int:
    print(OPERATIONAL_BLOCK, file=sys.stderr)
    print(f"RECONCILIATION_CONTRACT_BLOCKED:{error.reason}", file=sys.stderr)
    return error.exit_code


def _frame(tag: bytes, payload: bytes) -> bytes:
    if len(tag) != 1:
        raise ValueError("invalid internal frame tag")
    return tag + struct.pack(">Q", len(payload)) + payload


def _encode_framed(value: Any) -> bytes:
    """Codifica tipos JSON em TLV inequívoco, sem depender de JSON canônico."""
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
        encoded_items: list[tuple[bytes, bytes]] = []
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("invalid internal mapping key")
            key_bytes = key.encode("utf-8")
            encoded_items.append((key_bytes, _encode_framed(item)))
        encoded_items.sort(key=lambda pair: pair[0])
        payload = struct.pack(">Q", len(encoded_items))
        for key_bytes, encoded_value in encoded_items:
            payload += _frame(b"K", key_bytes) + encoded_value
        return _frame(b"O", payload)
    raise ValueError("unsupported internal framing type")


def _framed_sha256(domain: str, value: Any) -> str:
    material = b"PASTORAI-MIGRATION-HISTORY\x00\x01"
    material += _frame(b"D", domain.encode("ascii"))
    material += _encode_framed(value)
    return hashlib.sha256(material).hexdigest()


def _directory_flags() -> int:
    required = ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
    if any(not hasattr(os, name) for name in required):
        raise PacketIoError
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _file_flags() -> int:
    required = ("O_NOFOLLOW", "O_CLOEXEC", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required):
        raise PacketIoError
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def _validate_directory(snapshot: FileSnapshot, error_type: type[VerificationError]) -> None:
    if not stat.S_ISDIR(snapshot.mode):
        raise error_type
    if snapshot.links < 2:
        raise error_type
    if snapshot.uid != os.geteuid() or snapshot.gid != os.getegid():
        raise error_type
    if snapshot.mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise error_type


def _validate_ancestor_directory(
    snapshot: FileSnapshot,
    error_type: type[VerificationError],
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
    current_identity = snapshot.uid == os.geteuid() and snapshot.gid == os.getegid()
    root_identity = snapshot.uid == 0 and snapshot.gid == 0
    if not current_identity and not root_identity:
        raise error_type
    if snapshot.mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise error_type


def _validate_regular_file(
    snapshot: FileSnapshot,
    *,
    maximum_size: int,
    error_type: type[VerificationError],
) -> None:
    if not stat.S_ISREG(snapshot.mode):
        raise error_type
    if snapshot.links != 1:
        raise error_type
    if snapshot.uid != os.geteuid() or snapshot.gid != os.getegid():
        raise error_type
    if snapshot.mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise error_type
    if snapshot.mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
        raise error_type
    if snapshot.size < 0 or snapshot.size > maximum_size:
        raise error_type


def _open_directory(path: pathlib.Path, error_type: type[VerificationError]) -> tuple[int, FileSnapshot]:
    if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts[1:]):
        raise error_type
    try:
        descriptor = os.open(os.sep, _directory_flags())
    except (OSError, ValueError) as exc:
        raise error_type from exc
    try:
        root_snapshot = FileSnapshot.from_stat(os.fstat(descriptor))
        _validate_ancestor_directory(
            root_snapshot, error_type, allow_filesystem_root=True
        )
        snapshot = root_snapshot
        components = path.parts[1:]
        for index, component in enumerate(components):
            try:
                child_descriptor = os.open(
                    component, _directory_flags(), dir_fd=descriptor
                )
            except (OSError, ValueError) as exc:
                raise error_type from exc
            try:
                snapshot = FileSnapshot.from_stat(os.fstat(child_descriptor))
                named = FileSnapshot.from_stat(
                    os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                )
                if named != snapshot:
                    raise error_type
                if index == len(components) - 1:
                    _validate_directory(snapshot, error_type)
                else:
                    _validate_ancestor_directory(
                        snapshot,
                        error_type,
                        allow_system_sticky=index == 0 and component == "tmp",
                    )
            except Exception:
                os.close(child_descriptor)
                raise
            os.close(descriptor)
            descriptor = child_descriptor
        if not components:
            _validate_directory(snapshot, error_type)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor, snapshot


def _read_fd_bytes(descriptor: int, expected_size: int, maximum_size: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, min(65_536, maximum_size + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum_size:
            raise ValueError("read limit exceeded")
    if total != expected_size:
        raise ValueError("file changed during read")
    return b"".join(chunks)


def _read_regular_at(
    directory_fd: int,
    basename: str,
    *,
    maximum_size: int,
    error_type: type[VerificationError],
) -> tuple[bytes, FileSnapshot]:
    try:
        descriptor = os.open(basename, _file_flags(), dir_fd=directory_fd)
    except (OSError, ValueError) as exc:
        raise error_type from exc
    try:
        before = FileSnapshot.from_stat(os.fstat(descriptor))
        _validate_regular_file(before, maximum_size=maximum_size, error_type=error_type)
        try:
            content = _read_fd_bytes(descriptor, before.size, maximum_size)
        except (OSError, ValueError) as exc:
            raise error_type from exc
        after = FileSnapshot.from_stat(os.fstat(descriptor))
        if after != before:
            raise error_type
        try:
            named = FileSnapshot.from_stat(
                os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
            )
        except OSError as exc:
            raise error_type from exc
        if named != before:
            raise error_type
        return content, before
    finally:
        os.close(descriptor)


def _validate_regular_path(
    path: pathlib.Path, error_type: type[VerificationError]
) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise error_type
    directory_fd, directory_before = _open_directory(path.parent, error_type)
    try:
        _content, _snapshot = _read_regular_at(
            directory_fd,
            path.name,
            maximum_size=MAX_PACKET_BYTES,
            error_type=error_type,
        )
        if FileSnapshot.from_stat(os.fstat(directory_fd)) != directory_before:
            raise error_type
    finally:
        os.close(directory_fd)


def _validate_runtime_layout() -> None:
    _validate_regular_path(SCRIPT_PATH, PacketIoError)


def _load_packet_bytes(packet_basename: str) -> bytes:
    directory_fd, directory_before = _open_directory(PACKETS_DIR, PacketIoError)
    try:
        content, _snapshot = _read_regular_at(
            directory_fd,
            packet_basename,
            maximum_size=MAX_PACKET_BYTES,
            error_type=PacketIoError,
        )
        directory_after = FileSnapshot.from_stat(os.fstat(directory_fd))
        if directory_after != directory_before:
            raise PacketIoError
        return content
    finally:
        os.close(directory_fd)


def _scan_catalog() -> list[dict[str, Any]]:
    directory_fd, directory_before = _open_directory(MIGRATIONS_DIR, CatalogDriftError)
    try:
        try:
            first_listing = sorted(os.listdir(directory_fd))
        except OSError as exc:
            raise CatalogDriftError from exc
        names = sorted(name for name in first_listing if name.endswith(".sql"))
        if not names or len(names) > MAX_CATALOG_FILES:
            raise CatalogDriftError
        if any(not MIGRATION_BASENAME_RE.fullmatch(name) for name in names):
            raise CatalogDriftError
        folded = [name.casefold() for name in names]
        if len(set(names)) != len(names) or len(set(folded)) != len(names):
            raise CatalogDriftError

        entries: list[dict[str, Any]] = []
        file_snapshots: dict[str, FileSnapshot] = {}
        total_size = 0
        for position, name in enumerate(names):
            content, snapshot = _read_regular_at(
                directory_fd,
                name,
                maximum_size=MAX_MIGRATION_BYTES,
                error_type=CatalogDriftError,
            )
            file_snapshots[name] = snapshot
            total_size += snapshot.size
            if total_size > MAX_CATALOG_BYTES:
                raise CatalogDriftError
            entries.append(
                {
                    "position": position,
                    "name": name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": snapshot.size,
                }
            )

        try:
            second_listing = sorted(os.listdir(directory_fd))
        except OSError as exc:
            raise CatalogDriftError from exc
        if first_listing != second_listing:
            raise CatalogDriftError
        try:
            for name, expected_snapshot in file_snapshots.items():
                current_snapshot = FileSnapshot.from_stat(
                    os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                )
                if current_snapshot != expected_snapshot:
                    raise CatalogDriftError
        except OSError as exc:
            raise CatalogDriftError from exc
        directory_after = FileSnapshot.from_stat(os.fstat(directory_fd))
        if directory_after != directory_before:
            raise CatalogDriftError
        return entries
    finally:
        os.close(directory_fd)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SchemaError
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> NoReturn:
    raise SchemaError


def _reject_float(_value: str) -> NoReturn:
    raise SchemaError


def _is_safe_ascii(value: str, maximum_length: int) -> bool:
    return (
        len(value) <= maximum_length
        and value.isascii()
        and all(0x20 <= ord(character) <= 0x7E for character in value)
    )


def _validate_json_limits(root: Any) -> None:
    stack: list[tuple[Any, int]] = [(root, 1)]
    nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise SchemaError
        if type(value) is str:
            if not _is_safe_ascii(value, MAX_JSON_STRING):
                raise SchemaError
        elif type(value) is list:
            if len(value) > MAX_JSON_NODES:
                raise SchemaError
            stack.extend((item, depth + 1) for item in value)
        elif type(value) is dict:
            if len(value) > MAX_JSON_NODES:
                raise SchemaError
            for key, item in value.items():
                if type(key) is not str or not _is_safe_ascii(key, 128):
                    raise SchemaError
                stack.append((item, depth + 1))
        elif value is not None and type(value) not in (bool, int):
            raise SchemaError


def _parse_packet(content: bytes) -> dict[str, Any]:
    if content.startswith(b"\xef\xbb\xbf"):
        raise SchemaError
    try:
        text = content.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
            parse_float=_reject_float,
        )
    except VerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise SchemaError from exc
    _validate_json_limits(value)
    if type(value) is not dict:
        raise SchemaError
    return value


def _object(value: Any, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise SchemaError
    return value


def _list(value: Any, maximum: int = MAX_JSON_NODES) -> list[Any]:
    if type(value) is not list or len(value) > maximum:
        raise SchemaError
    return value


def _string(value: Any, *, pattern: re.Pattern[str] | None = None) -> str:
    if type(value) is not str or not value or len(value) > MAX_JSON_STRING:
        raise SchemaError
    if pattern is not None and not pattern.fullmatch(value):
        raise SchemaError
    return value


def _nullable_sha256(value: Any) -> str | None:
    if value is None:
        return None
    return _string(value, pattern=SHA256_RE)


def _sha256(value: Any) -> str:
    return _string(value, pattern=SHA256_RE)


def _integer(value: Any, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise SchemaError
    return value


def _boolean(value: Any) -> bool:
    if type(value) is not bool:
        raise SchemaError
    return value


def _timestamp(value: Any) -> str:
    result = _string(value, pattern=UTC_TIMESTAMP_RE)
    try:
        from datetime import datetime

        datetime.fromisoformat(result.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise SchemaError from exc
    return result


def _timestamp_value(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _nullable_timestamp(value: Any) -> str | None:
    return None if value is None else _timestamp(value)


def _sha256_list(value: Any) -> list[str]:
    values = _list(value, MAX_CATALOG_FILES)
    result = [_sha256(item) for item in values]
    if result != sorted(set(result)):
        raise SchemaError
    return result


def _validate_catalog(catalog: Any) -> list[dict[str, Any]]:
    value = _object(catalog, CATALOG_KEYS)
    if value["algorithm"] != CATALOG_ALGORITHM:
        raise SchemaError
    entries = _list(value["entries"], MAX_CATALOG_FILES)
    if not entries:
        raise SchemaError
    names: list[str] = []
    validated: list[dict[str, Any]] = []
    for expected_position, raw_entry in enumerate(entries):
        entry = _object(raw_entry, CATALOG_ENTRY_KEYS)
        position = _integer(
            entry["position"], minimum=0, maximum=MAX_CATALOG_FILES - 1
        )
        if position != expected_position:
            raise SchemaError
        name = _string(entry["name"], pattern=MIGRATION_BASENAME_RE)
        digest = _sha256(entry["sha256"])
        size_bytes = _integer(
            entry["size_bytes"], minimum=0, maximum=MAX_MIGRATION_BYTES
        )
        names.append(name)
        validated.append(
            {
                "position": position,
                "name": name,
                "sha256": digest,
                "size_bytes": size_bytes,
            }
        )
    if names != sorted(names):
        raise SchemaError
    if len(set(names)) != len(names) or len({name.casefold() for name in names}) != len(
        names
    ):
        raise SchemaError
    expected_digest = _framed_sha256(
        "pastorai/migration-history/catalog/v1",
        {"algorithm": CATALOG_ALGORITHM, "entries": validated},
    )
    if not hmac.compare_digest(_sha256(value["digest_sha256"]), expected_digest):
        raise SchemaError
    return validated


def _validate_public_rows(rows: Any) -> list[dict[str, Any]]:
    values = _list(rows, MAX_CATALOG_FILES)
    result: list[dict[str, Any]] = []
    names: list[str] = []
    for expected_position, raw_row in enumerate(values):
        row = _object(raw_row, PUBLIC_ROW_KEYS)
        if _integer(row["position"], minimum=0, maximum=MAX_CATALOG_FILES - 1) != expected_position:
            raise SchemaError
        name = _string(row["name"], pattern=MIGRATION_BASENAME_RE)
        names.append(name)
        result.append(
            {
                "position": expected_position,
                "name": name,
            }
        )
    if len(set(names)) != len(names):
        raise SchemaError
    return result


def _validate_native_rows(rows: Any) -> list[dict[str, Any]]:
    from datetime import datetime

    values = _list(rows, MAX_CATALOG_FILES)
    result: list[dict[str, Any]] = []
    versions: list[str] = []
    for expected_position, raw_row in enumerate(values):
        row = _object(raw_row, NATIVE_ROW_KEYS)
        if _integer(row["position"], minimum=0, maximum=MAX_CATALOG_FILES - 1) != expected_position:
            raise SchemaError
        version = _string(row["version"], pattern=NATIVE_VERSION_RE)
        try:
            datetime.strptime(version, "%Y%m%d%H%M%S")
        except ValueError as exc:
            raise SchemaError from exc
        name_value = row["name"]
        name = None if name_value is None else _string(name_value, pattern=NATIVE_NAME_RE)
        versions.append(version)
        result.append({"position": expected_position, "version": version, "name": name})
    if len(set(versions)) != len(versions):
        raise SchemaError
    if versions != sorted(versions):
        raise SchemaError
    return result


def _validate_inventory(
    raw_inventory: Any,
    *,
    source: str,
    query_contract: str,
    target_binding: str | None,
) -> dict[str, Any]:
    inventory = _object(raw_inventory, INVENTORY_KEYS)
    if inventory["source"] != source or inventory["query_contract"] != query_contract:
        raise SchemaError
    capture_state = _string(inventory["capture_state"])
    if capture_state not in CAPTURE_STATES:
        raise SchemaError
    inventory_target = _nullable_sha256(inventory["target_binding_sha256"])
    captured_at = _nullable_timestamp(inventory["captured_at_utc"])
    authorization_ref = _nullable_sha256(inventory["authorization_record_sha256"])
    capture_ref = _nullable_sha256(inventory["capture_record_sha256"])
    snapshot_ref = _nullable_sha256(inventory["snapshot_record_sha256"])
    completeness = _boolean(inventory["completeness_attested"])
    rows = (
        _validate_public_rows(inventory["rows"])
        if source == PUBLIC_SOURCE
        else _validate_native_rows(inventory["rows"])
    )
    rows_digest = _nullable_sha256(inventory["rows_digest_sha256"])

    if capture_state == "NOT_CAPTURED":
        if any(
            item is not None
            for item in (
                inventory_target,
                captured_at,
                authorization_ref,
                capture_ref,
                snapshot_ref,
                rows_digest,
            )
        ) or completeness or rows:
            raise SchemaError
    else:
        if (
            target_binding is None
            or inventory_target != target_binding
            or captured_at is None
            or authorization_ref is None
            or capture_ref is None
            or snapshot_ref is None
            or not completeness
        ):
            raise SchemaError
        if capture_state == "ABSENT_CONFIRMED" and rows:
            raise SchemaError
        expected_rows_digest = _framed_sha256(
            (
                "pastorai/migration-history/public-ledger/v1"
                if source == PUBLIC_SOURCE
                else "pastorai/migration-history/native-ledger/v1"
            ),
            {"source": source, "query_contract": query_contract, "rows": rows},
        )
        if rows_digest is None or not hmac.compare_digest(
            rows_digest, expected_rows_digest
        ):
            raise SchemaError
    return {
        "source": source,
        "capture_state": capture_state,
        "target_binding_sha256": inventory_target,
        "captured_at_utc": captured_at,
        "authorization_record_sha256": authorization_ref,
        "capture_record_sha256": capture_ref,
        "snapshot_record_sha256": snapshot_ref,
        "completeness_attested": completeness,
        "query_contract": query_contract,
        "rows": rows,
        "rows_digest_sha256": rows_digest,
    }


def _validate_catalog_decisions(raw_entries: Any) -> list[dict[str, Any]]:
    entries = _list(raw_entries, MAX_CATALOG_FILES)
    result: list[dict[str, Any]] = []
    for expected_position, raw_entry in enumerate(entries):
        entry = _object(raw_entry, CATALOG_DECISION_KEYS)
        position = _integer(entry["position"], minimum=0, maximum=MAX_CATALOG_FILES - 1)
        if position != expected_position:
            raise SchemaError
        determination = _string(entry["human_determination"])
        if determination not in HUMAN_DETERMINATIONS:
            raise SchemaError
        public_position = entry["public_row_position"]
        if public_position is not None:
            public_position = _integer(
                public_position, minimum=0, maximum=MAX_CATALOG_FILES - 1
            )
        native_positions = [
            _integer(item, minimum=0, maximum=MAX_CATALOG_FILES - 1)
            for item in _list(entry["native_row_positions"], MAX_CATALOG_FILES)
        ]
        if native_positions != sorted(set(native_positions)):
            raise SchemaError
        basis = _sha256_list(entry["basis_record_sha256"])
        evidence = _nullable_sha256(entry["evidence_record_sha256"])
        decision = _nullable_sha256(entry["decision_record_sha256"])
        if determination == "UNRESOLVED":
            if basis or evidence is not None or decision is not None:
                raise SchemaError
        elif evidence is None or decision is None:
            raise SchemaError
        result.append(
            {
                "position": position,
                "catalog_name": _string(
                    entry["catalog_name"], pattern=MIGRATION_BASENAME_RE
                ),
                "human_determination": determination,
                "public_row_position": public_position,
                "native_row_positions": native_positions,
                "basis_record_sha256": basis,
                "evidence_record_sha256": evidence,
                "decision_record_sha256": decision,
            }
        )
    return result


def _validate_native_decisions(raw_entries: Any) -> list[dict[str, Any]]:
    entries = _list(raw_entries, MAX_CATALOG_FILES)
    result: list[dict[str, Any]] = []
    for expected_position, raw_entry in enumerate(entries):
        entry = _object(raw_entry, NATIVE_DECISION_KEYS)
        position = _integer(
            entry["native_row_position"], minimum=0, maximum=MAX_CATALOG_FILES - 1
        )
        if position != expected_position:
            raise SchemaError
        disposition = _string(entry["disposition"])
        if disposition not in NATIVE_DISPOSITIONS:
            raise SchemaError
        names = [
            _string(item, pattern=MIGRATION_BASENAME_RE)
            for item in _list(entry["catalog_names"], MAX_CATALOG_FILES)
        ]
        if names != sorted(set(names)):
            raise SchemaError
        basis = _sha256_list(entry["basis_record_sha256"])
        evidence = _nullable_sha256(entry["evidence_record_sha256"])
        decision = _nullable_sha256(entry["decision_record_sha256"])
        if disposition == "UNRESOLVED":
            if basis or evidence is not None or decision is not None:
                raise SchemaError
        elif evidence is None or decision is None:
            raise SchemaError
        result.append(
            {
                "native_row_position": position,
                "disposition": disposition,
                "catalog_names": names,
                "basis_record_sha256": basis,
                "evidence_record_sha256": evidence,
                "decision_record_sha256": decision,
            }
        )
    return result


def _validate_reconciliation(raw_reconciliation: Any) -> dict[str, Any]:
    reconciliation = _object(raw_reconciliation, RECONCILIATION_KEYS)
    state = _string(reconciliation["state"])
    if state not in RECONCILIATION_STATES:
        raise SchemaError
    catalog_entries = _validate_catalog_decisions(reconciliation["catalog_entries"])
    native_rows = _validate_native_decisions(reconciliation["native_rows"])
    if state == "NOT_REVIEWED" and (catalog_entries or native_rows):
        raise SchemaError
    return {"state": state, "catalog_entries": catalog_entries, "native_rows": native_rows}


def _validate_attestation(raw_attestation: Any) -> dict[str, Any]:
    attestation = _object(raw_attestation, ATTESTATION_KEYS)
    state = _string(attestation["state"])
    if state not in {"NOT_ATTESTED", "ATTESTED_REVIEW_ONLY"}:
        raise SchemaError
    inventory_ref = _nullable_sha256(
        attestation["inventory_attestation_record_sha256"]
    )
    owner_ref = _nullable_sha256(
        attestation["migration_owner_decision_record_sha256"]
    )
    independent_ref = _nullable_sha256(
        attestation["independent_review_record_sha256"]
    )
    attested_at = _nullable_timestamp(attestation["attested_at_utc"])
    payload_digest = _nullable_sha256(attestation["payload_sha256"])
    if state == "NOT_ATTESTED":
        if any(
            item is not None
            for item in (
                inventory_ref,
                owner_ref,
                independent_ref,
                attested_at,
                payload_digest,
            )
        ):
            raise SchemaError
    else:
        if any(
            item is None
            for item in (
                inventory_ref,
                owner_ref,
                independent_ref,
                attested_at,
                payload_digest,
            )
        ):
            raise SchemaError
        if len({inventory_ref, owner_ref, independent_ref}) != 3:
            raise SchemaError
    return {
        "state": state,
        "inventory_attestation_record_sha256": inventory_ref,
        "migration_owner_decision_record_sha256": owner_ref,
        "independent_review_record_sha256": independent_ref,
        "attested_at_utc": attested_at,
        "payload_sha256": payload_digest,
    }


def _validate_packet_schema(packet: dict[str, Any]) -> dict[str, Any]:
    value = _object(packet, TOP_LEVEL_KEYS)
    if value["contract_version"] != CONTRACT_VERSION:
        raise SchemaError
    package_id = _string(value["package_id"], pattern=PACKAGE_ID_RE)
    artifact_state = _string(value["artifact_state"])
    if artifact_state not in ARTIFACT_STATES:
        raise SchemaError
    safety = _object(value["safety_contract"], SAFETY_KEYS)
    if safety != SAFETY_CONTRACT:
        raise SchemaError
    subject = _object(value["subject"], SUBJECT_KEYS)
    environment = _string(subject["environment"])
    if environment not in {"UNBOUND", "DEV", "PROD"}:
        raise SchemaError
    target_binding = _nullable_sha256(subject["target_binding_sha256"])
    repository_sha = _string(subject["repository_sha"], pattern=GIT_SHA_RE)
    if subject["catalog_path"] != CATALOG_PATH:
        raise SchemaError
    if artifact_state == "TEMPLATE_NOT_EVIDENCE":
        if environment != "UNBOUND" or target_binding is not None:
            raise SchemaError
    elif environment not in {"DEV", "PROD"} or target_binding is None:
        raise SchemaError

    catalog = _object(value["catalog"], CATALOG_KEYS)
    validated_catalog_entries = _validate_catalog(catalog)
    validated_catalog = {
        "algorithm": CATALOG_ALGORITHM,
        "entries": validated_catalog_entries,
        "digest_sha256": catalog["digest_sha256"],
    }
    inventories = _object(value["inventories"], INVENTORIES_KEYS)
    public_inventory = _validate_inventory(
        inventories["public_ledger"],
        source=PUBLIC_SOURCE,
        query_contract=PUBLIC_QUERY_CONTRACT,
        target_binding=target_binding,
    )
    native_inventory = _validate_inventory(
        inventories["native_ledger"],
        source=NATIVE_SOURCE,
        query_contract=NATIVE_QUERY_CONTRACT,
        target_binding=target_binding,
    )
    reconciliation = _validate_reconciliation(value["reconciliation"])
    attestation = _validate_attestation(value["attestation"])
    return {
        "contract_version": CONTRACT_VERSION,
        "package_id": package_id,
        "artifact_state": artifact_state,
        "safety_contract": dict(SAFETY_CONTRACT),
        "subject": {
            "environment": environment,
            "target_binding_sha256": target_binding,
            "repository_sha": repository_sha,
            "catalog_path": CATALOG_PATH,
        },
        "catalog": validated_catalog,
        "inventories": {
            "public_ledger": public_inventory,
            "native_ledger": native_inventory,
        },
        "reconciliation": reconciliation,
        "attestation": attestation,
    }


def _require_human_evidence(
    entry: dict[str, Any],
    capture_records: tuple[str, str],
    forbidden_global_records: set[str],
) -> None:
    basis = entry["basis_record_sha256"]
    evidence = entry["evidence_record_sha256"]
    decision = entry["decision_record_sha256"]
    expected_basis = (
        [] if evidence is None else sorted({*capture_records, evidence})
    )
    if (
        evidence is None
        or evidence in forbidden_global_records
        or basis != expected_basis
        or decision is None
        or decision in forbidden_global_records
        or decision == evidence
        or decision in basis
    ):
        raise HumanEvidenceBlockedError


def _verify_semantics(packet: dict[str, Any]) -> None:
    if packet["artifact_state"] == "TEMPLATE_NOT_EVIDENCE":
        raise HumanEvidenceBlockedError
    public = packet["inventories"]["public_ledger"]
    native = packet["inventories"]["native_ledger"]
    if public["capture_state"] == "NOT_CAPTURED" or native["capture_state"] == "NOT_CAPTURED":
        raise InventoryBlockedError
    if native["capture_state"] != "PRESENT_COMPLETE" or not native["rows"]:
        raise InventoryBlockedError
    if public["captured_at_utc"] != native["captured_at_utc"]:
        raise InventoryBlockedError
    authorization_records = {
        public["authorization_record_sha256"],
        native["authorization_record_sha256"],
    }
    capture_records = (public["capture_record_sha256"], native["capture_record_sha256"])
    capture_record_set = set(capture_records)
    if (
        len(capture_record_set) != 2
        or capture_record_set.intersection(authorization_records)
    ):
        raise InventoryBlockedError
    snapshot_record = public["snapshot_record_sha256"]
    if (
        snapshot_record != native["snapshot_record_sha256"]
        or snapshot_record in capture_record_set
        or snapshot_record in authorization_records
    ):
        raise InventoryBlockedError
    attestation = packet["attestation"]
    if attestation["state"] != "ATTESTED_REVIEW_ONLY":
        raise AttestationBlockedError
    attestation_records = {
        attestation["inventory_attestation_record_sha256"],
        attestation["migration_owner_decision_record_sha256"],
        attestation["independent_review_record_sha256"],
    }
    inventory_provenance_records = {
        *authorization_records,
        *capture_record_set,
        snapshot_record,
    }
    if attestation_records.intersection(inventory_provenance_records):
        raise AttestationBlockedError
    forbidden_global_records = inventory_provenance_records | attestation_records
    reconciliation = packet["reconciliation"]
    if (
        packet["artifact_state"] != "HUMAN_REVIEW_COMPLETE"
        or reconciliation["state"] != "HUMAN_REVIEW_COMPLETE"
    ):
        raise HumanEvidenceBlockedError

    catalog_entries = packet["catalog"]["entries"]
    decisions = reconciliation["catalog_entries"]
    native_decisions = reconciliation["native_rows"]
    if len(decisions) != len(catalog_entries) or len(native_decisions) != len(native["rows"]):
        raise HumanEvidenceBlockedError

    catalog_names = [entry["name"] for entry in catalog_entries]
    decision_names = [entry["catalog_name"] for entry in decisions]
    if decision_names != catalog_names:
        raise HumanEvidenceBlockedError

    determinations = [entry["human_determination"] for entry in decisions]
    if "UNRESOLVED" in determinations:
        raise HumanEvidenceBlockedError
    pending_positions = [
        index
        for index, determination in enumerate(determinations)
        if determination == "NOT_APPLIED_CONFIRMED"
    ]
    if len(pending_positions) > 1:
        raise LedgerDivergenceError
    if pending_positions and pending_positions[0] != len(determinations) - 1:
        raise LedgerDivergenceError

    public_rows = public["rows"]
    applied_names = [
        entry["catalog_name"]
        for entry in decisions
        if entry["human_determination"] == "APPLIED_CONFIRMED"
    ]
    public_names = [row["name"] for row in public_rows]
    if public_names != applied_names[: len(public_names)]:
        raise LedgerDivergenceError

    public_references: list[int] = []
    native_edges_from_catalog: set[tuple[int, str]] = set()
    evidence_records: list[str] = []
    decision_records: list[str] = []
    for entry in decisions:
        _require_human_evidence(entry, capture_records, forbidden_global_records)
        evidence_records.append(entry["evidence_record_sha256"])
        decision_records.append(entry["decision_record_sha256"])
        public_position = entry["public_row_position"]
        if entry["position"] < len(public_rows):
            if (
                entry["human_determination"] != "APPLIED_CONFIRMED"
                or public_position != entry["position"]
                or public_rows[public_position]["name"] != entry["catalog_name"]
            ):
                raise LedgerDivergenceError
            public_references.append(public_position)
        elif public_position is not None:
            raise LedgerDivergenceError
        for native_position in entry["native_row_positions"]:
            if native_position >= len(native["rows"]):
                raise LedgerDivergenceError
            native_edges_from_catalog.add((native_position, entry["catalog_name"]))
    if public_references != list(range(len(public_rows))):
        raise LedgerDivergenceError

    catalog_name_set = set(catalog_names)
    native_edges_from_rows: set[tuple[int, str]] = set()
    for expected_position, entry in enumerate(native_decisions):
        if entry["native_row_position"] != expected_position:
            raise HumanEvidenceBlockedError
        disposition = entry["disposition"]
        if disposition == "UNRESOLVED":
            raise HumanEvidenceBlockedError
        _require_human_evidence(entry, capture_records, forbidden_global_records)
        evidence_records.append(entry["evidence_record_sha256"])
        decision_records.append(entry["decision_record_sha256"])
        names = entry["catalog_names"]
        if disposition == "MAPS_TO_CATALOG":
            if len(names) != 1 or names[0] not in catalog_name_set:
                raise LedgerDivergenceError
            native_edges_from_rows.update((expected_position, name) for name in names)
        elif names:
            raise LedgerDivergenceError
    if native_edges_from_catalog != native_edges_from_rows:
        raise LedgerDivergenceError
    evidence_record_set = set(evidence_records)
    decision_record_set = set(decision_records)
    if (
        len(evidence_record_set) != len(evidence_records)
        or len(decision_record_set) != len(decision_records)
        or evidence_record_set.intersection(decision_record_set)
    ):
        raise HumanEvidenceBlockedError

    if _timestamp_value(attestation["attested_at_utc"]) < _timestamp_value(
        public["captured_at_utc"]
    ):
        raise AttestationBlockedError
    attested_payload = {
        key: packet[key]
        for key in (
            "contract_version",
            "package_id",
            "artifact_state",
            "safety_contract",
            "subject",
            "catalog",
            "inventories",
            "reconciliation",
        )
    }
    expected_digest = _framed_sha256(
        "pastorai/migration-history/attestation/v1", attested_payload
    )
    if not hmac.compare_digest(attestation["payload_sha256"], expected_digest):
        raise AttestationBlockedError


def verify_packet(packet_basename: str) -> None:
    if not PACKET_BASENAME_RE.fullmatch(packet_basename):
        raise PacketIoError
    _validate_runtime_layout()
    packet = _validate_packet_schema(_parse_packet(_load_packet_bytes(packet_basename)))
    if packet_basename != f"{packet['package_id']}.json":
        raise SchemaError
    actual_catalog = _scan_catalog()
    if packet["catalog"]["entries"] != actual_catalog:
        raise CatalogDriftError
    actual_digest = _framed_sha256(
        "pastorai/migration-history/catalog/v1",
        {"algorithm": CATALOG_ALGORITHM, "entries": actual_catalog},
    )
    if not hmac.compare_digest(packet["catalog"]["digest_sha256"], actual_digest):
        raise CatalogDriftError
    _verify_semantics(packet)


def build_parser() -> argparse.ArgumentParser:
    parser = SanitizedArgumentParser(
        prog="verify_migration_history_reconciliation.py",
        add_help=False,
        allow_abbrev=False,
        description="Verificador offline e somente leitura de pacote humano sanitizado.",
    )
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument(
        "--packet",
        type=str,
    )
    return parser


def main(argv: list[str]) -> int:
    try:
        args = build_parser().parse_args(argv[1:])
    except CliUsageError:
        print(OPERATIONAL_BLOCK, file=sys.stderr)
        print(USAGE_ERROR, file=sys.stderr)
        return 2
    if args.help:
        print(OPERATIONAL_BLOCK)
        print(HELP_TEXT)
        return 0
    if args.packet is None:
        print(OPERATIONAL_BLOCK, file=sys.stderr)
        print(USAGE_ERROR, file=sys.stderr)
        return 2
    try:
        verify_packet(args.packet)
    except VerificationError as error:
        return _blocked(error)
    except Exception:  # noqa: BLE001 - saída deliberadamente estática e sanitizada
        return _blocked(VerificationError())
    print(OPERATIONAL_BLOCK)
    print("VALID_FOR_HUMAN_REVIEW_ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
