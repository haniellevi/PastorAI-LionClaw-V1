#!/usr/bin/env python3
"""Valida as capturas F2 seladas sem reemitir conteúdo observado.

O programa só aceita os dois contratos pinados desta missão. O caminho da
captura é uma entrada local efêmera: não é registrado, impresso ou usado para
derivar artefato. A saída contém somente resultado e contagens sanitizadas.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import stat
import sys
from typing import Iterable


DEV_CAPTURE_SHA256 = "18d2e78ffc16d26f20f1e58459969c9c3bcc5cf58896c33c6225daedd01f6cb9"
DEV_CAPTURE_SIZE_BYTES = 405_404
DEV_SUPERSEDED_SHA256_PREFIX = "5fbd1c8f"
PROD_CAPTURE_SHA256 = "8a8601efc9e6bbc7d8772570a2d78535073c13e999753bf12ea92bdcf6868bd3"
PROD_CAPTURE_SIZE_BYTES = 2_182
PROD_HALF_SHA256 = "d9f8deff50021757469a6dd0b1ec0ad9858bdd8602b40d1a74514dd24287624d"
REQUIRED_MODE = 0o600

HEX_32 = re.compile(r"^[0-9a-f]{32}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
ROW_FOOTER = re.compile(r"^\((?:0|[1-9][0-9]*) rows?\)$")
TABLE_SEPARATOR = re.compile(r"^-+(?:\+-+)*$")


class ContractFailure(Exception):
    """Erro deliberadamente sem detalhe para preservar a captura."""


@dataclass(frozen=True)
class CaptureContract:
    environment: str
    expected_sha256: str
    expected_size_bytes: int
    duplicate_identical_halves: bool
    expected_half_sha256: str | None = None
    required_mode: int = REQUIRED_MODE


@dataclass(frozen=True)
class CaptureSummary:
    environment: str
    physical_capture_copies: int
    logical_capture_copies: int
    target_digest_count: int
    public_ledger_entry_count: int
    native_ledger_entry_count: int
    native_ledger_cardinality: int


OFFICIAL_CONTRACTS = {
    "DEV": CaptureContract(
        environment="DEV",
        expected_sha256=DEV_CAPTURE_SHA256,
        expected_size_bytes=DEV_CAPTURE_SIZE_BYTES,
        duplicate_identical_halves=False,
    ),
    "PROD": CaptureContract(
        environment="PROD",
        expected_sha256=PROD_CAPTURE_SHA256,
        expected_size_bytes=PROD_CAPTURE_SIZE_BYTES,
        duplicate_identical_halves=True,
        expected_half_sha256=PROD_HALF_SHA256,
    ),
}

DEV_RECORD_SHAPES = {
    "TARGET_DIGEST": 2,
    "F2_SESSION": 12,
    "LEDGER_RELATION": 9,
    "LEDGER_COLUMN": 7,
    "PUBLIC_LEDGER_COUNT_EXPECTATION": 2,
    "PUBLIC_LEDGER_ENTRY": 4,
    "NATIVE_LEDGER_COUNT_EXPECTATION": 2,
    "NATIVE_LEDGER_ENTRY": 4,
    "NATIVE_LEDGER_STATEMENT_FINGERPRINT": 4,
    "CATALOG_SCHEMA": 5,
    "CATALOG_RELATION": 10,
    "CATALOG_COLUMN": 10,
    "CATALOG_CONSTRAINT": 9,
    "CATALOG_INDEX": 11,
    "CATALOG_RLS_POLICY": 8,
    "CATALOG_TRIGGER": 6,
    "CATALOG_FUNCTION": 11,
    "SCHEMA_ACL_DIRECT_GRANTEE": 6,
    "RELACL_DIRECT_GRANTEE": 8,
    "PROACL_DIRECT_GRANTEE": 7,
    "DEFAULT_ACL_DIRECT_GRANTEE": 7,
    "PREFLIGHT_SCOPE": 9,
}

PROD_RECORD_SHAPES = {
    "TARGET_DIGEST": 2,
    "F2_SESSION": 11,
    "PREFLIGHT_SCOPE": 6,
    "LEDGER_RELATION": 9,
    "LEDGER_CARDINALITY": 4,
    "LEDGER_COLUMN": 7,
    "LEDGER_TRIGGER": 5,
    "LEDGER_RULE": 4,
}

COMMON_COMMAND_MARKERS = frozenset({"BEGIN", "SET", "ROLLBACK"})
DEV_RECEIPT = "F2_DEV_FINAL_RECEIPT=ROLLBACK_COMPLETED_F2_DEV"
PROD_RECEIPT = "ROLLBACK_COMPLETED_F2_PROD_DIAG"


def _fail() -> None:
    raise ContractFailure


def _is_hex_32(value: str) -> bool:
    return HEX_32.fullmatch(value) is not None


def _is_hex_64(value: str) -> bool:
    return HEX_64.fullmatch(value) is not None


def _is_boolean(value: str) -> bool:
    return value in {"t", "f", "true", "false"}


def _is_nonnegative_integer(value: str) -> bool:
    return value.isdecimal()


def _is_safe_opaque(value: str, prefix: str) -> bool:
    return value.startswith(prefix) and _is_hex_32(value[len(prefix) :])


def _parse_rows(
    payload: bytes,
    environment: str,
) -> tuple[list[tuple[str, ...]], Counter[str], Counter[str]]:
    try:
        text = payload.decode("utf-8", "strict")
    except UnicodeError:
        _fail()
    if "F2_ABORT" in text or "\x00" in text:
        _fail()

    shapes = DEV_RECORD_SHAPES if environment == "DEV" else PROD_RECORD_SHAPES
    receipt = DEV_RECEIPT if environment == "DEV" else PROD_RECEIPT
    allowed_markers = COMMON_COMMAND_MARKERS | {receipt}
    rows: list[tuple[str, ...]] = []
    record_counts: Counter[str] = Counter()
    marker_counts: Counter[str] = Counter()
    final_nonempty = ""

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped:
            final_nonempty = stripped
        if not stripped or ROW_FOOTER.fullmatch(stripped) or TABLE_SEPARATOR.fullmatch(stripped):
            continue
        if "|" not in raw_line:
            if stripped not in allowed_markers:
                _fail()
            marker_counts[stripped] += 1
            continue

        fields = tuple(part.strip() for part in raw_line.split("|"))
        record_type = fields[0]
        if record_type not in shapes or len(fields) != shapes[record_type]:
            _fail()
        rows.append(fields)
        record_counts[record_type] += 1

    if final_nonempty != receipt or marker_counts[receipt] != 1:
        _fail()
    if any(marker_counts[marker] > 1 for marker in COMMON_COMMAND_MARKERS):
        _fail()
    return rows, record_counts, marker_counts


def _require_exact_count(counts: Counter[str], name: str, expected: int) -> None:
    if counts[name] != expected:
        _fail()


def _rows_of(rows: Iterable[tuple[str, ...]], record_type: str) -> list[tuple[str, ...]]:
    return [row for row in rows if row[0] == record_type]


def _positions_are_exact(rows: Iterable[tuple[str, ...]], expected_count: int) -> bool:
    positions: list[int] = []
    for row in rows:
        if not _is_nonnegative_integer(row[1]):
            return False
        positions.append(int(row[1]))
    return sorted(positions) == list(range(expected_count))


def _validate_target_and_terminal_order(
    rows: list[tuple[str, ...]],
    record_counts: Counter[str],
    expected_preflight_position: int | None,
) -> None:
    _require_exact_count(record_counts, "TARGET_DIGEST", 1)
    _require_exact_count(record_counts, "F2_SESSION", 1)
    _require_exact_count(record_counts, "PREFLIGHT_SCOPE", 1)
    if not rows or rows[0][0] != "TARGET_DIGEST" or not _is_hex_64(rows[0][1]):
        _fail()
    if len(rows) < 2 or rows[1][0] != "F2_SESSION":
        _fail()
    preflight_index = next(
        index for index, row in enumerate(rows) if row[0] == "PREFLIGHT_SCOPE"
    )
    if expected_preflight_position is not None and preflight_index != expected_preflight_position:
        _fail()
    if expected_preflight_position is None and preflight_index != len(rows) - 1:
        _fail()


def _validate_dev_session(row: tuple[str, ...]) -> None:
    if row[0:9] != (
        "F2_SESSION",
        "DEV",
        "170006",
        "repeatable read",
        "on",
        "5s",
        "1s",
        "15s",
        "off",
    ):
        _fail()
    if not _is_boolean(row[9]) or not _is_boolean(row[10]):
        _fail()
    if row[11] != "TARGET_BINDING_PRESENT_FORMAT_VALID_NOT_PRINTED":
        _fail()


def _validate_dev_ledger_relations(rows: list[tuple[str, ...]]) -> None:
    relation_rows = _rows_of(rows, "LEDGER_RELATION")
    if len(relation_rows) != 2:
        _fail()
    by_ref = {row[1]: row for row in relation_rows}
    if set(by_ref) != {"PUBLIC_LEDGER", "NATIVE_LEDGER"}:
        _fail()
    public = by_ref["PUBLIC_LEDGER"]
    native = by_ref["NATIVE_LEDGER"]
    if public[2:7] != ("PRESENT", "r", "p", "t", "f"):
        _fail()
    if native[2:7] != ("PRESENT", "r", "p", "f", "f"):
        _fail()
    if public[7:] != ("0", "0") or native[7:] != ("0", "0"):
        _fail()


def _validate_dev_columns(rows: list[tuple[str, ...]]) -> None:
    column_rows = _rows_of(rows, "LEDGER_COLUMN")
    if len(column_rows) != 8:
        _fail()
    grouped: dict[str, list[tuple[str, ...]]] = {"PUBLIC_LEDGER": [], "NATIVE_LEDGER": []}
    for row in column_rows:
        if row[1] not in grouped or not _is_nonnegative_integer(row[2]) or not _is_boolean(row[5]):
            _fail()
        if row[6] != "NO_DEFAULT" and not _is_hex_32(row[6]):
            _fail()
        grouped[row[1]].append(row)
    public_names = {row[3] for row in grouped["PUBLIC_LEDGER"]}
    native_names = {row[3] for row in grouped["NATIVE_LEDGER"]}
    if public_names != {"name", "applied_at"} or native_names != {
        "version",
        "statements",
        "name",
        "created_by",
        "idempotency_key",
        "rollback",
    }:
        _fail()
    if sorted(int(row[2]) for row in grouped["PUBLIC_LEDGER"]) != [1, 2]:
        _fail()
    if sorted(int(row[2]) for row in grouped["NATIVE_LEDGER"]) != [1, 2, 3, 4, 5, 6]:
        _fail()


def _validate_dev_catalog_row(row: tuple[str, ...]) -> None:
    record_type = row[0]
    scopes = {"PUBLIC_SCHEMA", "AGENT_PRIVATE_SCHEMA", "RECOVERY_SCHEMA", "GLOBAL_NAMESPACE"}
    allowed_roles = {
        "postgres",
        "anon",
        "authenticated",
        "service_role",
        "agent_runtime",
        "authenticator",
        "supabase_storage_admin",
        "pgbouncer",
        "supabase_realtime_admin",
        "supabase_replication_admin",
        "PUBLIC",
        "PREDEFINED_ROLE",
        "UNEXPECTED_CUSTOM_GRANTEE",
    }
    if record_type == "CATALOG_SCHEMA":
        if row[1] not in scopes - {"GLOBAL_NAMESPACE"} or row[2] not in {"PRESENT", "ABSENT"}:
            _fail()
        if row[3] not in {"ALLOWLIST_ROLE", "PREDEFINED_ROLE", "UNEXPECTED_CUSTOM_OWNER"}:
            _fail()
        if row[4] not in {"NO_DIRECT_NSPACL", "DIRECT_NSPACL_PRESENT"}:
            _fail()
        return
    if record_type == "CATALOG_RELATION":
        if row[1] not in scopes - {"GLOBAL_NAMESPACE"}:
            _fail()
        if row[2] != "schema_migrations" and not _is_safe_opaque(row[2], "OPAQUE_RELATION_"):
            _fail()
        if row[8] not in {"ALLOWLIST_ROLE", "PREDEFINED_ROLE", "UNEXPECTED_CUSTOM_OWNER"}:
            _fail()
        if row[9] not in {"NO_DIRECT_RELACL", "DIRECT_RELACL_PRESENT"}:
            _fail()
        return
    if record_type == "CATALOG_COLUMN":
        if row[1] not in scopes - {"GLOBAL_NAMESPACE"} or not _is_nonnegative_integer(row[3]):
            _fail()
        if row[2] != "schema_migrations" and not _is_safe_opaque(row[2], "OPAQUE_RELATION_"):
            _fail()
        if row[4] not in {"name", "applied_at"} and not _is_safe_opaque(row[4], "OPAQUE_COLUMN_"):
            _fail()
        if not _is_boolean(row[6]) or (row[9] != "NO_DEFAULT" and not _is_hex_32(row[9])):
            _fail()
        return
    if record_type == "CATALOG_CONSTRAINT":
        if row[1] not in scopes - {"GLOBAL_NAMESPACE"}:
            _fail()
        if not _is_safe_opaque(row[2], "OPAQUE_RELATION_") or not _is_safe_opaque(row[3], "OPAQUE_CONSTRAINT_"):
            _fail()
        if not _is_boolean(row[5]) or not _is_boolean(row[6]) or not _is_boolean(row[7]) or not _is_hex_32(row[8]):
            _fail()
        return
    if record_type == "CATALOG_INDEX":
        if row[1] not in scopes - {"GLOBAL_NAMESPACE"}:
            _fail()
        if not _is_safe_opaque(row[2], "OPAQUE_RELATION_") or not _is_safe_opaque(row[3], "OPAQUE_INDEX_"):
            _fail()
        if any(not _is_boolean(value) for value in row[4:9]) or not _is_hex_32(row[9]):
            _fail()
        if row[10] != "NO_PREDICATE" and not _is_hex_32(row[10]):
            _fail()
        return
    if record_type == "CATALOG_RLS_POLICY":
        if row[1] not in scopes - {"GLOBAL_NAMESPACE"}:
            _fail()
        if not _is_safe_opaque(row[2], "OPAQUE_RELATION_") or not _is_safe_opaque(row[3], "OPAQUE_POLICY_"):
            _fail()
        if row[4] not in {"r", "a", "w", "d", "*"} or not _is_boolean(row[5]):
            _fail()
        if not _is_hex_32(row[6]) or not _is_hex_32(row[7]):
            _fail()
        return
    if record_type == "CATALOG_TRIGGER":
        if row[1] not in scopes - {"GLOBAL_NAMESPACE"}:
            _fail()
        if not _is_safe_opaque(row[2], "OPAQUE_RELATION_") or not _is_safe_opaque(row[3], "OPAQUE_TRIGGER_"):
            _fail()
        if len(row[4]) != 1 or not _is_hex_32(row[5]):
            _fail()
        return
    if record_type == "CATALOG_FUNCTION":
        if row[1] not in scopes - {"GLOBAL_NAMESPACE"} or not _is_safe_opaque(row[2], "OPAQUE_FUNCTION_"):
            _fail()
        if not _is_boolean(row[4]) or not _is_hex_32(row[7]):
            _fail()
        if row[8] != "AGGREGATE_DEFINITION_NOT_EXTRACTED" and not _is_hex_32(row[8]):
            _fail()
        if row[9] not in {"ALLOWLIST_ROLE", "PREDEFINED_ROLE", "UNEXPECTED_CUSTOM_OWNER"}:
            _fail()
        if row[10] not in {"NO_DIRECT_PROACL", "DIRECT_PROACL_PRESENT"}:
            _fail()
        return
    if record_type == "SCHEMA_ACL_DIRECT_GRANTEE":
        if row[1] not in scopes - {"GLOBAL_NAMESPACE"} or row[3] not in allowed_roles:
            _fail()
        if row[2] not in {"PUBLIC", "ALLOWLIST_ROLE", "PREDEFINED_ROLE", "UNEXPECTED_CUSTOM_GRANTEE"}:
            _fail()
        if not _is_boolean(row[5]):
            _fail()
        return
    if record_type == "RELACL_DIRECT_GRANTEE":
        if row[1] not in scopes - {"GLOBAL_NAMESPACE"}:
            _fail()
        if row[2] != "schema_migrations" and not _is_safe_opaque(row[2], "OPAQUE_RELATION_"):
            _fail()
        if row[5] not in allowed_roles or row[4] not in {"PUBLIC", "ALLOWLIST_ROLE", "PREDEFINED_ROLE", "UNEXPECTED_CUSTOM_GRANTEE"}:
            _fail()
        if not _is_boolean(row[7]):
            _fail()
        return
    if record_type == "PROACL_DIRECT_GRANTEE":
        if row[1] not in scopes - {"GLOBAL_NAMESPACE"} or not _is_safe_opaque(row[2], "OPAQUE_FUNCTION_"):
            _fail()
        if row[4] not in allowed_roles or row[3] not in {"PUBLIC", "ALLOWLIST_ROLE", "PREDEFINED_ROLE", "UNEXPECTED_CUSTOM_GRANTEE"}:
            _fail()
        if not _is_boolean(row[6]):
            _fail()
        return
    if record_type == "DEFAULT_ACL_DIRECT_GRANTEE":
        if row[1] not in scopes or row[4] not in allowed_roles:
            _fail()
        if row[3] not in {"PUBLIC", "ALLOWLIST_ROLE", "PREDEFINED_ROLE", "UNEXPECTED_CUSTOM_GRANTEE"}:
            _fail()
        if not _is_boolean(row[6]):
            _fail()
        return
    _fail()


def _validate_dev(payload: bytes) -> CaptureSummary:
    rows, counts, _markers = _parse_rows(payload, "DEV")
    _validate_target_and_terminal_order(rows, counts, expected_preflight_position=None)
    _validate_dev_session(rows[1])
    preflight = _rows_of(rows, "PREFLIGHT_SCOPE")[0]
    if preflight != (
        "PREFLIGHT_SCOPE",
        "PG_CATALOG_INFORMATION_SCHEMA_AND_TWO_LEDGERS_ONLY",
        "ZERO_DOMAIN_ROWS",
        "ZERO_LEDGER_STATEMENT_TEXT",
        "OPAQUE_DOMAIN_OBJECT_NAMES",
        "OPAQUE_UNEXPECTED_AND_PREDEFINED_ROLE_NAMES",
        "TARGET_DIGEST_UTF8_HEX",
        "ROW_SECURITY_OFF_FAIL_CLOSED",
        "PUBLIC_33_AND_NATIVE_6_OR_ABORT",
    ):
        _fail()
    _validate_dev_ledger_relations(rows)
    _validate_dev_columns(rows)
    _require_exact_count(counts, "PUBLIC_LEDGER_COUNT_EXPECTATION", 1)
    _require_exact_count(counts, "NATIVE_LEDGER_COUNT_EXPECTATION", 1)
    if _rows_of(rows, "PUBLIC_LEDGER_COUNT_EXPECTATION")[0] != (
        "PUBLIC_LEDGER_COUNT_EXPECTATION",
        "EXPECTED_33",
    ):
        _fail()
    if _rows_of(rows, "NATIVE_LEDGER_COUNT_EXPECTATION")[0] != (
        "NATIVE_LEDGER_COUNT_EXPECTATION",
        "EXPECTED_6",
    ):
        _fail()
    public_entries = _rows_of(rows, "PUBLIC_LEDGER_ENTRY")
    native_entries = _rows_of(rows, "NATIVE_LEDGER_ENTRY")
    fingerprints = _rows_of(rows, "NATIVE_LEDGER_STATEMENT_FINGERPRINT")
    if len(public_entries) != 33 or not _positions_are_exact(public_entries, 33):
        _fail()
    if len(native_entries) != 6 or not _positions_are_exact(native_entries, 6):
        _fail()
    if len(fingerprints) != 6 or not _positions_are_exact(fingerprints, 6):
        _fail()
    if any(not _is_hex_32(row[2]) or not _is_boolean(row[3]) for row in public_entries):
        _fail()
    for row in native_entries:
        if not _is_hex_32(row[2]) or (not _is_nonnegative_integer(row[3]) and row[3] not in {"[null]", ""}):
            _fail()
    for row in fingerprints:
        if row[2] != "STATEMENTS_NULL" and not _is_hex_32(row[2]):
            _fail()
        if row[3] not in {
            "STATEMENTS_NULL",
            "NON_SENSITIVE_DDL_PATTERN_PRESENT",
            "NO_NON_SENSITIVE_DDL_PATTERN",
        }:
            _fail()
    _require_exact_count(counts, "CATALOG_SCHEMA", 3)
    for row in rows:
        if row[0].startswith("CATALOG_") or row[0].endswith("DIRECT_GRANTEE"):
            _validate_dev_catalog_row(row)
    return CaptureSummary(
        environment="DEV",
        physical_capture_copies=1,
        logical_capture_copies=1,
        target_digest_count=1,
        public_ledger_entry_count=33,
        native_ledger_entry_count=6,
        native_ledger_cardinality=6,
    )


def _validate_prod_session(row: tuple[str, ...]) -> None:
    if row != (
        "F2_SESSION",
        "PROD_DIAG",
        "170006",
        "REPEATABLE_READ",
        "READ_ONLY_ON",
        "SEARCH_PATH_PG_CATALOG",
        "STATEMENT_TIMEOUT_5000MS",
        "LOCK_TIMEOUT_1000MS",
        "IDLE_TIMEOUT_15000MS",
        "ROW_SECURITY_OFF",
        "BINDING_64HEX_ACCEPTED_NOT_PRINTED",
    ):
        _fail()


def _validate_prod(payload: bytes) -> CaptureSummary:
    rows, counts, _markers = _parse_rows(payload, "PROD")
    _validate_target_and_terminal_order(rows, counts, expected_preflight_position=2)
    _validate_prod_session(rows[1])
    if rows[2] != (
        "PREFLIGHT_SCOPE",
        "PG_CATALOG_AND_TWO_CANONICAL_LEDGERS_ONLY",
        "NO_DOMAIN_ROWS_OR_LEDGER_STATEMENT_TEXT",
        "COLUMN_CEILING_16",
        "TRIGGER_CEILING_8",
        "RULE_CEILING_8",
    ):
        _fail()
    relation_rows = _rows_of(rows, "LEDGER_RELATION")
    if len(relation_rows) != 2:
        _fail()
    by_ref = {row[1]: row for row in relation_rows}
    if set(by_ref) != {"PUBLIC_LEDGER", "NATIVE_LEDGER"}:
        _fail()
    if by_ref["PUBLIC_LEDGER"] != (
        "LEDGER_RELATION",
        "PUBLIC_LEDGER",
        "ABSENT",
        "ABSENT",
        "ABSENT",
        "NOT_APPLICABLE",
        "NOT_APPLICABLE",
        "0",
        "0",
    ):
        _fail()
    native_relation = by_ref["NATIVE_LEDGER"]
    if native_relation[2:5] != ("PRESENT", "r", "p"):
        _fail()
    if native_relation[5] not in {"RLS_ENABLED", "RLS_DISABLED"}:
        _fail()
    if native_relation[6] not in {"RLS_FORCED", "RLS_NOT_FORCED"}:
        _fail()
    if not _is_nonnegative_integer(native_relation[7]) or not _is_nonnegative_integer(native_relation[8]):
        _fail()
    cardinality_rows = _rows_of(rows, "LEDGER_CARDINALITY")
    if len(cardinality_rows) != 2:
        _fail()
    cardinality = {row[1]: row for row in cardinality_rows}
    if set(cardinality) != {"PUBLIC_LEDGER", "NATIVE_LEDGER"}:
        _fail()
    if cardinality["PUBLIC_LEDGER"][2] != "NOT_TABLE_OR_PARTITIONED":
        _fail()
    if cardinality["PUBLIC_LEDGER"][3] not in {"", "[null]", "NULL"}:
        _fail()
    if cardinality["NATIVE_LEDGER"] != (
        "LEDGER_CARDINALITY",
        "NATIVE_LEDGER",
        "TABLE_OR_PARTITIONED",
        "32",
    ):
        _fail()
    column_rows = _rows_of(rows, "LEDGER_COLUMN")
    if len(column_rows) != 6:
        _fail()
    expected_names = {"version", "statements", "name", "created_by", "idempotency_key", "rollback"}
    if {row[1] for row in column_rows} != {"NATIVE_LEDGER"}:
        _fail()
    if {row[3] for row in column_rows} != expected_names:
        _fail()
    if not all(_is_nonnegative_integer(row[2]) for row in column_rows):
        _fail()
    if sorted(int(row[2]) for row in column_rows) != [1, 2, 3, 4, 5, 6]:
        _fail()
    for row in column_rows:
        if not _is_boolean(row[5]) or (row[6] != "NO_DEFAULT" and not _is_hex_32(row[6])):
            _fail()
    for row in _rows_of(rows, "LEDGER_TRIGGER"):
        if row[1] not in {"PUBLIC_LEDGER", "NATIVE_LEDGER"} or not _is_safe_opaque(row[2], "OPAQUE_TRIGGER_"):
            _fail()
        if len(row[3]) != 1 or not _is_hex_32(row[4]):
            _fail()
    for row in _rows_of(rows, "LEDGER_RULE"):
        if row[1] not in {"PUBLIC_LEDGER", "NATIVE_LEDGER"} or not _is_safe_opaque(row[2], "OPAQUE_RULE_") or not _is_hex_32(row[3]):
            _fail()
    if counts["LEDGER_TRIGGER"] > 8 or counts["LEDGER_RULE"] > 8:
        _fail()
    return CaptureSummary(
        environment="PROD",
        physical_capture_copies=2,
        logical_capture_copies=1,
        target_digest_count=1,
        public_ledger_entry_count=0,
        native_ledger_entry_count=0,
        native_ledger_cardinality=32,
    )


def validate_payload(payload: bytes, contract: CaptureContract) -> CaptureSummary:
    """Valida bytes já autenticados; função pública usada somente nos testes locais."""
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if contract.environment == "DEV" and actual_sha256.startswith(DEV_SUPERSEDED_SHA256_PREFIX):
        _fail()
    if actual_sha256 != contract.expected_sha256:
        _fail()
    if len(payload) != contract.expected_size_bytes:
        _fail()
    if contract.environment == "DEV":
        if contract.duplicate_identical_halves:
            _fail()
        return _validate_dev(payload)
    if contract.environment == "PROD":
        if not contract.duplicate_identical_halves or contract.expected_half_sha256 is None:
            _fail()
        if len(payload) % 2:
            _fail()
        half_size = len(payload) // 2
        first_half = payload[:half_size]
        second_half = payload[half_size:]
        if first_half != second_half:
            _fail()
        if hashlib.sha256(first_half).hexdigest() != contract.expected_half_sha256:
            _fail()
        return _validate_prod(first_half)
    _fail()


def validate_file(path: Path, contract: CaptureContract) -> CaptureSummary:
    """Verifica arquivo regular, modo e bytes sem divulgar a entrada local."""
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            _fail()
        if stat.S_IMODE(metadata.st_mode) != contract.required_mode:
            _fail()
        if metadata.st_size != contract.expected_size_bytes:
            _fail()
        with path.open("rb") as handle:
            payload = handle.read()
    except (OSError, ValueError):
        _fail()
    return validate_payload(payload, contract)


def _parse_cli(argv: list[str]) -> tuple[str, Path] | None:
    if len(argv) != 5:
        return None
    if argv[1] != "--environment" or argv[3] != "--input":
        return None
    environment = argv[2]
    if environment not in OFFICIAL_CONTRACTS:
        return None
    return environment, Path(argv[4])


def _emit_pass(summary: CaptureSummary) -> None:
    print("RESULT=PASS_F2_CAPTURE_CONTRACT")
    print("PHYSICAL_CAPTURE_COPIES=" + str(summary.physical_capture_copies))
    print("LOGICAL_CAPTURE_COPIES=" + str(summary.logical_capture_copies))
    print("TARGET_DIGEST_COUNT=" + str(summary.target_digest_count))
    print("PUBLIC_LEDGER_ENTRY_COUNT=" + str(summary.public_ledger_entry_count))
    print("NATIVE_LEDGER_ENTRY_COUNT=" + str(summary.native_ledger_entry_count))
    print("NATIVE_LEDGER_CARDINALITY=" + str(summary.native_ledger_cardinality))


def _emit_fail() -> None:
    print("RESULT=FAIL_F2_CAPTURE_CONTRACT")


def main(argv: list[str] | None = None) -> int:
    parsed = _parse_cli(sys.argv if argv is None else argv)
    if parsed is None:
        _emit_fail()
        return 1
    environment, path = parsed
    try:
        summary = validate_file(path, OFFICIAL_CONTRACTS[environment])
    except (ContractFailure, OSError, UnicodeError, ValueError):
        _emit_fail()
        return 1
    _emit_pass(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
