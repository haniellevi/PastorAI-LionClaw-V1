#!/usr/bin/env python3
"""Converte uma coleta F1 de catálogo em índice opaco, sem reemitir valores.

O programa aceita o formato alinhado produzido pelo psql humano e o formato
sem alinhamento usado pela referência local. Somente hashes de chave e payload
chegam ao arquivo de saída. Nenhuma definição, nome de papel inesperado,
binding, linha de domínio ou dado da transcrição é gravado.

A versão V3 acrescenta um segundo hash opaco para isolar exclusivamente
``acl_state`` de ``CATALOG_SCHEMA`` e ``CATALOG_RELATION``. Ele não expõe o
estado, nomes, OIDs ou ACLs; apenas permite que o comparador diferencie uma
variação exclusiva desse campo de outra variação de definição.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Iterable


def _load_dev_receipt_contract() -> object:
    module_name = "f1_dev_receipt_contract"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    source = Path(__file__).with_name("dev_receipt_contract.py")
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise RuntimeError("DEV receipt contract unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_dev_contract = _load_dev_receipt_contract()
DEV_RECEIPT_CONTRACT = _dev_contract.DEV_RECEIPT_CONTRACT
DEV_RECEIPT_CONTRACT_SHA256 = _dev_contract.DEV_RECEIPT_CONTRACT_SHA256
DEV_RECEIPT_PROFILES = _dev_contract.DEV_RECEIPT_PROFILES
SEALED_F1 = _dev_contract.SEALED_F1
STRICT_FUTURE = _dev_contract.STRICT_FUTURE
validate_dev_raw_receipt = _dev_contract.validate_dev_raw_receipt
validate_dev_safe_index = _dev_contract.validate_dev_safe_index
validate_sealed_f1_evidence = _dev_contract.validate_sealed_f1_evidence


CATALOG_SHAPES = {
    "CATALOG_SCHEMA": {3},
    "CATALOG_RELATION": {9},
    "CATALOG_COLUMN": {10},
    "CATALOG_CONSTRAINT": {9},
    "CATALOG_INDEX": {11},
    "CATALOG_RLS_POLICY": {12},
    "CATALOG_FUNCTION": {10},
    "CATALOG_TRIGGER": {7},
    "CATALOG_TYPE": {6},
    "CATALOG_ROLE_AGENT_RUNTIME": {11},
    "CATALOG_ROLE_AGENT_RUNTIME_MEMBERSHIP": {2},
    "SCHEMA_ACL_DIRECT_GRANTEE": {6},
    "RELACL_DIRECT_GRANTEE": {8},
    "PROACL_DIRECT_GRANTEE": {8},
    "DEFAULT_ACL_SCOPE": {3},
    "DEFAULT_ACL_DIRECT_GRANTEE": {7},
    "UNEXPECTED_CUSTOM_GRANTEE_SUMMARY": {4},
    "PREFLIGHT_SCOPE": {9},
}

CONTROL_SHAPES = {
    "TARGET_DIGEST": {2},
    "F1_SESSION": {8},
    "LEDGER_RELATION": {9},
    "LEDGER_COLUMN": {7},
    "PUBLIC_LEDGER_COUNT_EXPECTATION": {2},
    "PUBLIC_LEDGER_ENTRY": {4},
    "NATIVE_LEDGER_COUNT_EXPECTATION": {2},
    "NATIVE_LEDGER_ENTRY": {4},
    "NATIVE_LEDGER_STATEMENT_FINGERPRINT": {4},
}

KNOWN_RECORD_SHAPES = {**CONTROL_SHAPES, **CATALOG_SHAPES}
INDEX_FORMAT = "F1_CATALOG_SAFE_INDEX_V3"
INDEX_FIELDS = {
    "format",
    "receipt_marker_counts",
    "record_count",
    "record_type_counts",
    "records",
    "rollback_receipt_state",
    "source",
    "source_observed_record_type_counts",
}

RECORD_HEADERS = {
    "TARGET_DIGEST": ("TARGET_DIGEST",),
    "F1_SESSION": (
        "server_version_num",
        "transaction_isolation",
        "transaction_read_only",
        "row_security_setting",
        "current_user_matches_session_user",
        "current_role_superuser_or_bypassrls",
        "target_binding_state",
    ),
    "LEDGER_RELATION": (
        "ledger_ref",
        "state",
        "relation_kind",
        "persistence",
        "rls_enabled",
        "rls_forced",
        "user_trigger_count",
        "user_rule_count",
    ),
    "LEDGER_COLUMN": (
        "ledger_ref",
        "ordinal_position",
        "column_name",
        "column_type",
        "not_null",
        "default_definition_md5",
    ),
    "PUBLIC_LEDGER_COUNT_EXPECTATION": ("state",),
    "PUBLIC_LEDGER_ENTRY": ("position", "migration_name_md5", "applied_at_null"),
    "NATIVE_LEDGER_COUNT_EXPECTATION": ("state",),
    "NATIVE_LEDGER_ENTRY": ("position", "version_md5", "statement_count"),
    "NATIVE_LEDGER_STATEMENT_FINGERPRINT": (
        "position",
        "statements_md5_or_state",
        "statement_pattern",
    ),
    "CATALOG_SCHEMA": ("schema_ref", "acl_state"),
    "CATALOG_RELATION": (
        "schema_ref",
        "relation_ref",
        "relation_kind",
        "persistence",
        "rls_enabled",
        "rls_forced",
        "replica_identity",
        "acl_state",
    ),
    "CATALOG_COLUMN": (
        "schema_ref",
        "relation_ref",
        "ordinal_position",
        "column_ref",
        "column_type",
        "not_null",
        "identity_kind",
        "generated_kind",
        "default_definition_md5",
    ),
    "CATALOG_CONSTRAINT": (
        "schema_ref",
        "relation_ref",
        "constraint_ref",
        "constraint_type",
        "validated",
        "deferrable",
        "initially_deferred",
        "definition_md5",
    ),
    "CATALOG_INDEX": (
        "schema_ref",
        "relation_ref",
        "index_ref",
        "is_unique",
        "is_primary",
        "is_valid",
        "is_ready",
        "is_live",
        "definition_md5",
        "predicate_md5",
    ),
    "CATALOG_RLS_POLICY": (
        "schema_ref",
        "relation_ref",
        "rls_enabled",
        "rls_forced",
        "policy_ref",
        "is_permissive",
        "command_code",
        "role_scope",
        "using_expression_md5",
        "check_expression_md5",
        "mentions_tenant_guc",
    ),
    "CATALOG_FUNCTION": (
        "schema_ref",
        "function_ref",
        "function_kind",
        "language_name",
        "volatility",
        "security_definer",
        "leakproof",
        "config_md5",
        "definition_md5",
    ),
    "CATALOG_TRIGGER": (
        "schema_ref",
        "relation_ref",
        "trigger_ref",
        "enabled_code",
        "function_ref",
        "definition_md5",
    ),
    "CATALOG_TYPE": (
        "schema_ref",
        "type_name",
        "type_kind",
        "enum_label_count",
        "enum_labels_md5",
    ),
    "CATALOG_ROLE_AGENT_RUNTIME": (
        "state",
        "can_login",
        "inherit",
        "superuser",
        "bypass_rls",
        "create_db",
        "create_role",
        "replication",
        "connection_limit",
        "config_md5",
    ),
    "CATALOG_ROLE_AGENT_RUNTIME_MEMBERSHIP": ("membership_edge_count",),
    "SCHEMA_ACL_DIRECT_GRANTEE": (
        "scope_ref",
        "grantee_class",
        "grantee_ref",
        "privilege_type",
        "is_grantable",
    ),
    "RELACL_DIRECT_GRANTEE": (
        "scope_ref",
        "relation_ref",
        "relation_kind",
        "grantee_class",
        "grantee_ref",
        "privilege_type",
        "is_grantable",
    ),
    "PROACL_DIRECT_GRANTEE": (
        "scope_ref",
        "function_ref",
        "function_kind",
        "grantee_class",
        "grantee_ref",
        "privilege_type",
        "is_grantable",
    ),
    "DEFAULT_ACL_SCOPE": ("scope_ref", "default_acl_row_count"),
    "DEFAULT_ACL_DIRECT_GRANTEE": (
        "scope_ref",
        "object_kind",
        "grantee_class",
        "grantee_ref",
        "privilege_type",
        "is_grantable",
    ),
    "UNEXPECTED_CUSTOM_GRANTEE_SUMMARY": (
        "scope_ref",
        "unexpected_direct_grant_count",
        "state",
    ),
    "PREFLIGHT_SCOPE": (
        "assertion",
        "domain_data_assertion",
        "statement_assertion",
        "grantee_assertion",
        "target_assertion",
        "row_security_assertion",
        "ledger_count_assertion",
        "acl_scope_assertion",
    ),
}
PSQL_HEADERS = frozenset(("record_type",) + header for header in RECORD_HEADERS.values())
PSQL_ROW_FOOTER = re.compile(r"^\((?:0|[1-9][0-9]*) rows?\)$")
PSQL_TABLE_SEPARATOR = re.compile(r"^-+(?:\+-+)*$")
PSQL_COMMAND_MARKERS = frozenset({"BEGIN", "SET", "ROLLBACK"})
SUCCESS_MARKERS_BY_SOURCE = {
    "DEV": frozenset({"ROLLBACK_COMPLETED_F1"}),
    "REFERENCE": frozenset({"REFERENCE_CATALOG_ADAPTER", "REFERENCE_CATALOG_ROLLBACK_COMPLETED"}),
}
ABORT_MARKERS_BY_SOURCE = {
    "DEV": frozenset({
        "F1_ABORT_MISSING_TARGET_BINDING",
        "F1_ABORT_INVALID_TARGET_BINDING_FORMAT",
        "F1_ABORT_UNEXPECTED_PUBLIC_LEDGER_COUNT",
        "F1_ABORT_PUBLIC_LEDGER_INVALID_SHAPE",
        "F1_ABORT_UNEXPECTED_NATIVE_LEDGER_COUNT",
        "F1_ABORT_NATIVE_LEDGER_INVALID_SHAPE",
    }),
    "REFERENCE": frozenset({"REFERENCE_ABORT_LEDGER_CONTRACT"}),
}
ALLOWED_MARKERS_BY_SOURCE = {
    source: PSQL_COMMAND_MARKERS | SUCCESS_MARKERS_BY_SOURCE[source] | ABORT_MARKERS_BY_SOURCE[source]
    for source in SUCCESS_MARKERS_BY_SOURCE
}
ALLOWED_PIPE_RECORD_TYPES_BY_SOURCE = {
    "DEV": frozenset(KNOWN_RECORD_SHAPES),
    "REFERENCE": frozenset(CATALOG_SHAPES),
}

ACL_STATE_RECORD_TYPES = {"CATALOG_SCHEMA", "CATALOG_RELATION"}


def _digest(label: bytes, values: Iterable[str]) -> str:
    hasher = hashlib.sha256()
    hasher.update(label)
    for value in values:
        encoded = value.encode("utf-8", "strict")
        hasher.update(encoded)
        hasher.update(b"\x1f")
    return hasher.hexdigest()


def _key_components(fields: tuple[str, ...]) -> tuple[str, str, str, str]:
    record_type = fields[0]
    if record_type == "CATALOG_SCHEMA":
        return record_type, fields[1], "-", "SCHEMA"
    if record_type == "CATALOG_RELATION":
        return record_type, fields[1], fields[2], "RELATION"
    if record_type in {
        "CATALOG_COLUMN",
        "CATALOG_CONSTRAINT",
        "CATALOG_INDEX",
        "CATALOG_TRIGGER",
    }:
        return record_type, fields[1], fields[2], fields[3]
    if record_type == "CATALOG_RLS_POLICY":
        return record_type, fields[1], fields[2], fields[5]
    if record_type in {"CATALOG_FUNCTION", "CATALOG_TYPE"}:
        return record_type, fields[1], "-", fields[2]
    if record_type == "CATALOG_ROLE_AGENT_RUNTIME":
        return record_type, "ROLE_SCOPE", "-", "agent_runtime"
    if record_type == "CATALOG_ROLE_AGENT_RUNTIME_MEMBERSHIP":
        return record_type, "ROLE_SCOPE", "-", "agent_runtime_membership"
    if record_type == "SCHEMA_ACL_DIRECT_GRANTEE":
        return record_type, fields[1], "-", "/".join(fields[2:5])
    if record_type == "RELACL_DIRECT_GRANTEE":
        return record_type, fields[1], fields[2], "/".join(fields[4:7])
    if record_type == "PROACL_DIRECT_GRANTEE":
        return record_type, fields[1], "-", "/".join(fields[2:7])
    if record_type == "DEFAULT_ACL_SCOPE":
        return record_type, fields[1], "-", "DEFAULT_ACL_SCOPE"
    if record_type == "DEFAULT_ACL_DIRECT_GRANTEE":
        return record_type, fields[1], "-", "/".join(fields[2:6])
    if record_type == "UNEXPECTED_CUSTOM_GRANTEE_SUMMARY":
        return record_type, fields[1], "-", "SUMMARY"
    if record_type == "PREFLIGHT_SCOPE":
        return record_type, "PREFLIGHT_SCOPE", "-", "F1_SCOPE"
    raise ValueError("record type outside catalog schema")


def _definition_fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    """Normaliza somente o campo ``acl_state`` dos dois registros aplicáveis."""
    if fields[0] in ACL_STATE_RECORD_TYPES:
        return fields[:-1] + ("ACL_STATE_NORMALIZED",)
    return fields


def _accept_nonpipe_line(
    raw_line: str,
    source: str,
    markers: Counter[str],
) -> tuple[str, str] | None:
    marker = raw_line.strip()
    if not marker or PSQL_ROW_FOOTER.fullmatch(marker) or PSQL_TABLE_SEPARATOR.fullmatch(marker):
        return None
    if marker not in ALLOWED_MARKERS_BY_SOURCE[source]:
        raise ValueError("unrecognized psql marker")
    markers[marker] += 1
    if marker in ABORT_MARKERS_BY_SOURCE[source]:
        raise ValueError("abort marker observed")
    return "marker", marker


def _accept_pipe_line(
    raw_line: str,
    source: str,
    observed_records: Counter[str],
    observed_rows: dict[str, list[tuple[str, ...]]],
    events: list[tuple[str, str]],
) -> tuple[tuple[str, str, str, str], tuple[str, ...]] | None:
    fields = tuple(part.strip() for part in raw_line.split("|"))
    if fields in PSQL_HEADERS:
        if source != "DEV":
            raise ValueError("unexpected reference psql header")
        return None
    record_type = fields[0]
    allowed_shapes = KNOWN_RECORD_SHAPES.get(record_type)
    if allowed_shapes is None or record_type not in ALLOWED_PIPE_RECORD_TYPES_BY_SOURCE[source]:
        raise ValueError("unrecognized pipe record")
    if len(fields) not in allowed_shapes:
        raise ValueError("recognized record shape invalid")
    observed_records[record_type] += 1
    observed_rows[record_type].append(fields)
    events.append(("record", record_type))
    if record_type not in CATALOG_SHAPES:
        return None
    return _key_components(fields), fields


def _valid_count_map(value: object, allowed_names: set[str] | frozenset[str]) -> bool:
    return (
        isinstance(value, dict)
        and all(
            isinstance(name, str)
            and name in allowed_names
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count > 0
            for name, count in value.items()
        )
    )


def _valid_dev_raw_receipt(
    observed_records: Counter[str],
    observed_rows: dict[str, list[tuple[str, ...]]],
    observed_markers: Counter[str],
    events: list[tuple[str, str]],
    profile: str,
) -> str:
    """Exige o contrato terminal completo antes de criar qualquer índice.

    As linhas são usadas somente nesta validação de processo. Elas nunca entram
    no JSON, que conserva apenas hashes de registros catalográficos conhecidos.
    """
    return validate_dev_raw_receipt(
        observed_records,
        observed_rows,
        observed_markers,
        events,
        profile,
    )


def _serialized_document(document: object) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _validate_document(
    document: object,
    source: str,
    dev_profile: str,
    serialized_sha256: str | None,
) -> bool:
    if not isinstance(document, dict) or set(document) != INDEX_FIELDS:
        return False
    if document.get("format") != INDEX_FORMAT or document.get("source") != source:
        return False
    records = document.get("records")
    record_count = document.get("record_count")
    if (
        not isinstance(records, list)
        or not records
        or not isinstance(record_count, int)
        or isinstance(record_count, bool)
        or record_count != len(records)
    ):
        return False
    record_counts = Counter()
    for record in records:
        if (
            not isinstance(record, dict)
            or set(record) != {
                "definition_sha256",
                "key_sha256",
                "payload_sha256",
                "record_type",
            }
            or not isinstance(record["record_type"], str)
            or record["record_type"] not in CATALOG_SHAPES
            or any(
                not isinstance(record[field], str)
                or re.fullmatch(r"[0-9a-f]{64}", record[field]) is None
                for field in ("definition_sha256", "key_sha256", "payload_sha256")
            )
        ):
            return False
        record_counts[record["record_type"]] += 1
    if len({record["key_sha256"] for record in records}) != len(records):
        return False
    if not _valid_count_map(document.get("record_type_counts"), set(CATALOG_SHAPES)):
        return False
    if document.get("record_type_counts") != dict(sorted(record_counts.items())):
        return False
    observed = document.get("source_observed_record_type_counts")
    if not _valid_count_map(observed, set(ALLOWED_PIPE_RECORD_TYPES_BY_SOURCE[source])):
        return False
    if any(observed.get(name) != count for name, count in record_counts.items()):
        return False
    allowed_markers = PSQL_COMMAND_MARKERS | SUCCESS_MARKERS_BY_SOURCE[source]
    markers = document.get("receipt_marker_counts")
    if not _valid_count_map(markers, allowed_markers):
        return False
    receipt_state = document.get("rollback_receipt_state")
    if source == "DEV":
        try:
            validate_dev_safe_index(document, dev_profile, serialized_sha256)
        except ValueError:
            return False
        return True
    if (
        markers.get("REFERENCE_CATALOG_ADAPTER") != 1
        or markers.get("REFERENCE_CATALOG_ROLLBACK_COMPLETED") != 1
    ):
        return False
    return receipt_state == "REFERENCE_ECHO_OBSERVED"


def _parse(
    raw: str,
    source: str,
    dev_profile: str = STRICT_FUTURE,
) -> tuple[dict[str, object], Counter[str]]:
    if source not in ALLOWED_MARKERS_BY_SOURCE:
        raise ValueError("source invalid")
    if source == "DEV" and dev_profile not in DEV_RECEIPT_PROFILES:
        raise ValueError("DEV receipt profile invalid")
    records: list[tuple[tuple[str, str, str, str], tuple[str, ...]]] = []
    observed_records: Counter[str] = Counter()
    observed_rows: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    observed_markers: Counter[str] = Counter()
    events: list[tuple[str, str]] = []
    for raw_line in raw.splitlines():
        if "|" not in raw_line:
            event = _accept_nonpipe_line(raw_line, source, observed_markers)
            if event is not None:
                events.append(event)
            continue
        accepted = _accept_pipe_line(
            raw_line,
            source,
            observed_records,
            observed_rows,
            events,
        )
        if accepted is not None:
            records.append(accepted)

    dev_receipt_state = None
    if source == "DEV":
        dev_receipt_state = _valid_dev_raw_receipt(
            observed_records,
            observed_rows,
            observed_markers,
            events,
            dev_profile,
        )

    grouped: dict[tuple[str, str, str, str], list[tuple[str, ...]]] = defaultdict(list)
    for key, fields in records:
        grouped[key].append(fields)

    opaque_records: list[dict[str, str]] = []
    record_type_counts = Counter()
    for key, grouped_fields in grouped.items():
        ordered = sorted(grouped_fields)
        for occurrence, fields in enumerate(ordered, start=1):
            record_type, schema_ref, relation_ref, object_ref = key
            key_values = (record_type, schema_ref, relation_ref, object_ref, str(occurrence))
            opaque_records.append(
                {
                    "key_sha256": _digest(b"F1-SAFE-KEY-v1\0", key_values),
                    "record_type": record_type,
                    "payload_sha256": _digest(b"F1-SAFE-PAYLOAD-v1\0", fields),
                    "definition_sha256": _digest(
                        b"F1-SAFE-DEFINITION-v1\0", _definition_fields(fields)
                    ),
                }
            )
            record_type_counts[record_type] += 1

    opaque_records.sort(key=lambda item: (item["record_type"], item["key_sha256"]))
    if not opaque_records or len({item["key_sha256"] for item in opaque_records}) != len(opaque_records):
        raise ValueError("safe key collision")
    document = {
        "format": INDEX_FORMAT,
        "source": source,
        "record_count": len(opaque_records),
        "record_type_counts": dict(sorted(record_type_counts.items())),
        "records": opaque_records,
        "source_observed_record_type_counts": dict(sorted(observed_records.items())),
        "receipt_marker_counts": dict(sorted(observed_markers.items())),
        "rollback_receipt_state": (
            dev_receipt_state if source == "DEV" else "REFERENCE_ECHO_OBSERVED"
        ),
    }
    if not _validate_document(document, source, dev_profile, None):
        raise ValueError("safe index document contract invalid")
    return document, observed_records


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--source", choices=("DEV", "REFERENCE"), required=True)
    parser.add_argument(
        "--dev-profile",
        choices=tuple(sorted(DEV_RECEIPT_PROFILES)),
        default=STRICT_FUTURE,
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output_path = Path(args.output)
    if output_path.parent != output_path.parent.resolve():
        raise SystemExit("FAIL=PATH_CONTRACT")
    try:
        input_path: Path | None = None
        if args.input == "-":
            if args.source == "DEV" and args.dev_profile == SEALED_F1:
                raise ValueError("sealed evidence stdin invalid")
            raw = sys.stdin.read()
        else:
            input_path = Path(args.input)
            if not input_path.is_file():
                raise ValueError("input path invalid")
            if args.source == "DEV" and args.dev_profile == SEALED_F1:
                validate_sealed_f1_evidence(input_path)
            raw = input_path.read_text(encoding="utf-8")
        document, _observed = _parse(raw, args.source, args.dev_profile)
        serialized = _serialized_document(document)
        if not _validate_document(
            document,
            args.source,
            args.dev_profile,
            hashlib.sha256(serialized).hexdigest(),
        ):
            raise ValueError("safe index document contract invalid")
        output_path.write_bytes(serialized)
    except (OSError, UnicodeError, ValueError) as exc:
        raise SystemExit("FAIL=CATALOG_SAFE_INDEX") from exc
    print("RESULT=PASS_F1_CATALOG_SAFE_INDEX")
    print(f"SOURCE={args.source}")
    print(f"RECORD_COUNT={document['record_count']}")
    print("INDEX_SHA256=" + hashlib.sha256(output_path.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
