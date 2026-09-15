#!/usr/bin/env python3
"""Contrato fechado do recibo DEV F1, compartilhado por parser e comparador.

O índice selado F1 mantém o formato V3 já pinado. O contrato não grava a
transcrição, binding, nomes de roles inesperadas ou valores de domínio: ele
valida somente contagens, estados de controle e ordem de marcadores.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import stat
from typing import Any


SEALED_F1 = "SEALED_F1"
STRICT_FUTURE = "STRICT_FUTURE"
DEV_RECEIPT_PROFILES = frozenset({SEALED_F1, STRICT_FUTURE})
SEALED_F1_EVIDENCE_SHA256 = "b1c3e1bda63b55e7c5496d318bcf039d9a4d130de60ced535d918be233313e1b"
SEALED_F1_INDEX_SHA256 = "a783fa04da2df40981c24e464b8fc4cb997be5b8d535e9dc7d307498636ebf25"

# Esta é a única tabela normativa do recibo DEV. As duas ferramentas a leem
# diretamente, e o teste sintético compara o mesmo fingerprint nas duas.
DEV_RECEIPT_CONTRACT: dict[str, object] = {
    "records": (
        ("TARGET_DIGEST", 1, None),
        ("F1_SESSION", 1, None),
        ("PREFLIGHT_SCOPE", 1, None),
        ("PUBLIC_LEDGER_COUNT_EXPECTATION", 1, "EXPECTED_33"),
        ("PUBLIC_LEDGER_ENTRY", 33, None),
        ("NATIVE_LEDGER_COUNT_EXPECTATION", 1, "EXPECTED_6"),
        ("NATIVE_LEDGER_ENTRY", 6, None),
        ("NATIVE_LEDGER_STATEMENT_FINGERPRINT", 6, None),
    ),
    "markers": (
        ("BEGIN", 1),
        ("SET", 5),
        ("ROLLBACK", 1),
    ),
    "terminal": {
        "preflight_before_rollback": True,
        "no_record_after_rollback": True,
    },
    "profiles": {
        SEALED_F1: {
            "rollback_completed_f1_min": 0,
            "rollback_completed_f1_max": 1,
            "requires_pinned_evidence": True,
            "requires_pinned_index": True,
        },
        STRICT_FUTURE: {
            "rollback_completed_f1_min": 1,
            "rollback_completed_f1_max": 1,
            "requires_pinned_evidence": False,
            "requires_pinned_index": False,
        },
    },
}
DEV_RECEIPT_CONTRACT_SHA256 = hashlib.sha256(
    json.dumps(
        DEV_RECEIPT_CONTRACT,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
).hexdigest()
DEV_REQUIRED_RECORD_COUNTS = {
    record_type: count
    for record_type, count, _expected_state in DEV_RECEIPT_CONTRACT["records"]
}
DEV_EXPECTED_CONTROL_ROWS = {
    record_type: (record_type, expected_state)
    for record_type, _count, expected_state in DEV_RECEIPT_CONTRACT["records"]
    if expected_state is not None
}
DEV_REQUIRED_MARKER_COUNTS = dict(DEV_RECEIPT_CONTRACT["markers"])
DEV_ALLOWED_MARKERS = frozenset({
    "BEGIN",
    "SET",
    "ROLLBACK",
    "ROLLBACK_COMPLETED_F1",
})


def _profile_rules(profile: str) -> Mapping[str, object]:
    profiles = DEV_RECEIPT_CONTRACT["profiles"]
    if not isinstance(profiles, dict) or profile not in profiles:
        raise ValueError("DEV receipt profile invalid")
    rules = profiles[profile]
    if not isinstance(rules, dict):
        raise ValueError("DEV receipt profile invalid")
    return rules


def _as_nonnegative_counts(value: object) -> Mapping[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError("DEV receipt contract invalid")
    if any(
        not isinstance(name, str)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
        for name, count in value.items()
    ):
        raise ValueError("DEV receipt contract invalid")
    return value


def _validate_counts_and_markers(
    observed_records: object,
    observed_markers: object,
    profile: str,
) -> str:
    records = _as_nonnegative_counts(observed_records)
    markers = _as_nonnegative_counts(observed_markers)
    if any(
        records.get(record_type) != expected_count
        for record_type, expected_count in DEV_REQUIRED_RECORD_COUNTS.items()
    ):
        raise ValueError("DEV receipt contract invalid")
    if any(
        markers.get(marker) != expected_count
        for marker, expected_count in DEV_REQUIRED_MARKER_COUNTS.items()
    ):
        raise ValueError("DEV receipt contract invalid")
    if any(
        marker not in DEV_ALLOWED_MARKERS or marker.startswith("F1_ABORT")
        for marker in markers
    ):
        raise ValueError("DEV receipt contract invalid")
    rules = _profile_rules(profile)
    rollback_echo = markers.get("ROLLBACK_COMPLETED_F1", 0)
    minimum = rules["rollback_completed_f1_min"]
    maximum = rules["rollback_completed_f1_max"]
    if (
        not isinstance(minimum, int)
        or not isinstance(maximum, int)
        or not minimum <= rollback_echo <= maximum
    ):
        raise ValueError("DEV receipt contract invalid")
    return "F1_ECHO_OBSERVED" if rollback_echo else "PSQL_ROLLBACK_COMMAND_OBSERVED"


def validate_dev_raw_receipt(
    observed_records: object,
    observed_rows: Mapping[str, Sequence[tuple[str, ...]]],
    observed_markers: object,
    events: Sequence[tuple[str, str]],
    profile: str,
) -> str:
    """Valida a captura antes da serialização e devolve somente o estado opaco."""
    receipt_state = _validate_counts_and_markers(
        observed_records,
        observed_markers,
        profile,
    )
    if any(
        observed_rows.get(record_type) != [expected_row]
        for record_type, expected_row in DEV_EXPECTED_CONTROL_ROWS.items()
    ):
        raise ValueError("DEV receipt contract invalid")
    rollback_positions = [
        index
        for index, event in enumerate(events)
        if event == ("marker", "ROLLBACK")
    ]
    preflight_positions = [
        index
        for index, event in enumerate(events)
        if event == ("record", "PREFLIGHT_SCOPE")
    ]
    if len(rollback_positions) != 1 or len(preflight_positions) != 1:
        raise ValueError("DEV receipt contract invalid")
    rollback_position = rollback_positions[0]
    if preflight_positions[0] >= rollback_position:
        raise ValueError("DEV receipt contract invalid")
    terminal_events = list(events[rollback_position + 1 :])
    if any(kind == "record" for kind, _name in terminal_events):
        raise ValueError("DEV receipt contract invalid")
    if receipt_state == "F1_ECHO_OBSERVED":
        if terminal_events != [("marker", "ROLLBACK_COMPLETED_F1")]:
            raise ValueError("DEV receipt contract invalid")
    elif terminal_events:
        raise ValueError("DEV receipt contract invalid")
    return receipt_state


def validate_dev_safe_index(
    document: Mapping[str, Any],
    profile: str,
    serialized_sha256: str | None,
) -> None:
    """Revalida o recibo resumido antes de o comparador aceitar o índice."""
    receipt_state = _validate_counts_and_markers(
        document.get("source_observed_record_type_counts"),
        document.get("receipt_marker_counts"),
        profile,
    )
    if document.get("rollback_receipt_state") != receipt_state:
        raise ValueError("DEV receipt contract invalid")
    rules = _profile_rules(profile)
    if (
        rules["requires_pinned_index"]
        and serialized_sha256 is not None
        and serialized_sha256 != SEALED_F1_INDEX_SHA256
    ):
        raise ValueError("DEV sealed index digest invalid")


def _validate_pinned_evidence(
    path: Path,
    expected_sha256: str,
) -> str:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError("sealed evidence unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError("sealed evidence mode invalid")
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError("sealed evidence unavailable") from exc
    if digest != expected_sha256:
        raise ValueError("sealed evidence digest invalid")
    return digest


def validate_sealed_f1_evidence(path: Path) -> str:
    """Valida a evidência F1 fornecida pelo runner, sem registrar seu caminho."""
    return _validate_pinned_evidence(
        path,
        SEALED_F1_EVIDENCE_SHA256,
    )
