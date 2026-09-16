#!/usr/bin/env python3
"""Testes sintéticos do validador F2, sem evidência externa ou banco."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

_SCRIPT_PATH = Path(__file__).with_name("validate_f2_capture_contract.py")
_SPEC = importlib.util.spec_from_file_location("f2_capture_contract_subject", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("validator source unavailable")
subject = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = subject
_SPEC.loader.exec_module(subject)


def _md5(seed: int) -> str:
    return f"{seed:032x}"[-32:]


def _contract(environment: str, payload: bytes, *, duplicated: bool = False, half: bytes | None = None) -> subject.CaptureContract:
    return subject.CaptureContract(
        environment=environment,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        expected_size_bytes=len(payload),
        duplicate_identical_halves=duplicated,
        expected_half_sha256=(hashlib.sha256(half).hexdigest() if half is not None else None),
    )


def _dev_payload(public_entries: int = 33) -> bytes:
    lines = [
        "TARGET_DIGEST|" + "a" * 64,
        "F2_SESSION|DEV|170006|repeatable read|on|5s|1s|15s|off|t|t|TARGET_BINDING_PRESENT_FORMAT_VALID_NOT_PRINTED",
        "LEDGER_RELATION|PUBLIC_LEDGER|PRESENT|r|p|t|f|0|0",
        "LEDGER_RELATION|NATIVE_LEDGER|PRESENT|r|p|f|f|0|0",
        "LEDGER_COLUMN|PUBLIC_LEDGER|1|name|text|t|NO_DEFAULT",
        "LEDGER_COLUMN|PUBLIC_LEDGER|2|applied_at|timestamp with time zone|t|" + _md5(1),
        "LEDGER_COLUMN|NATIVE_LEDGER|1|version|text|t|NO_DEFAULT",
        "LEDGER_COLUMN|NATIVE_LEDGER|2|statements|text[]|f|NO_DEFAULT",
        "LEDGER_COLUMN|NATIVE_LEDGER|3|name|text|f|NO_DEFAULT",
        "LEDGER_COLUMN|NATIVE_LEDGER|4|created_by|text|f|NO_DEFAULT",
        "LEDGER_COLUMN|NATIVE_LEDGER|5|idempotency_key|text|f|NO_DEFAULT",
        "LEDGER_COLUMN|NATIVE_LEDGER|6|rollback|text[]|f|NO_DEFAULT",
        "PUBLIC_LEDGER_COUNT_EXPECTATION|EXPECTED_33",
    ]
    for position in range(public_entries):
        lines.append(f"PUBLIC_LEDGER_ENTRY|{position}|{_md5(position + 10)}|f")
    lines.append("NATIVE_LEDGER_COUNT_EXPECTATION|EXPECTED_6")
    for position in range(6):
        lines.append(f"NATIVE_LEDGER_ENTRY|{position}|{_md5(position + 100)}|1")
    for position in range(6):
        lines.append(
            f"NATIVE_LEDGER_STATEMENT_FINGERPRINT|{position}|{_md5(position + 200)}|NO_NON_SENSITIVE_DDL_PATTERN"
        )
    lines.extend(
        [
            "CATALOG_SCHEMA|PUBLIC_SCHEMA|PRESENT|ALLOWLIST_ROLE|NO_DIRECT_NSPACL",
            "CATALOG_SCHEMA|AGENT_PRIVATE_SCHEMA|ABSENT|ALLOWLIST_ROLE|NO_DIRECT_NSPACL",
            "CATALOG_SCHEMA|RECOVERY_SCHEMA|ABSENT|ALLOWLIST_ROLE|NO_DIRECT_NSPACL",
            "CATALOG_RELATION|PUBLIC_SCHEMA|schema_migrations|r|p|t|f|d|ALLOWLIST_ROLE|NO_DIRECT_RELACL",
            "PREFLIGHT_SCOPE|PG_CATALOG_INFORMATION_SCHEMA_AND_TWO_LEDGERS_ONLY|ZERO_DOMAIN_ROWS|ZERO_LEDGER_STATEMENT_TEXT|OPAQUE_DOMAIN_OBJECT_NAMES|OPAQUE_UNEXPECTED_AND_PREDEFINED_ROLE_NAMES|TARGET_DIGEST_UTF8_HEX|ROW_SECURITY_OFF_FAIL_CLOSED|PUBLIC_33_AND_NATIVE_6_OR_ABORT",
            "F2_DEV_FINAL_RECEIPT=ROLLBACK_COMPLETED_F2_DEV",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _prod_half(
    *,
    native_cardinality: int = 32,
    receipt: str = "ROLLBACK_COMPLETED_F2_PROD_DIAG",
    terminal_extra: str = "",
) -> bytes:
    lines = [
        "TARGET_DIGEST|" + "b" * 64,
        "F2_SESSION|PROD_DIAG|170006|REPEATABLE_READ|READ_ONLY_ON|SEARCH_PATH_PG_CATALOG|STATEMENT_TIMEOUT_5000MS|LOCK_TIMEOUT_1000MS|IDLE_TIMEOUT_15000MS|ROW_SECURITY_OFF|BINDING_64HEX_ACCEPTED_NOT_PRINTED",
        "PREFLIGHT_SCOPE|PG_CATALOG_AND_TWO_CANONICAL_LEDGERS_ONLY|NO_DOMAIN_ROWS_OR_LEDGER_STATEMENT_TEXT|COLUMN_CEILING_16|TRIGGER_CEILING_8|RULE_CEILING_8",
        "LEDGER_RELATION|PUBLIC_LEDGER|ABSENT|ABSENT|ABSENT|NOT_APPLICABLE|NOT_APPLICABLE|0|0",
        "LEDGER_RELATION|NATIVE_LEDGER|PRESENT|r|p|RLS_DISABLED|RLS_NOT_FORCED|0|0",
        "LEDGER_CARDINALITY|PUBLIC_LEDGER|NOT_TABLE_OR_PARTITIONED|[null]",
        f"LEDGER_CARDINALITY|NATIVE_LEDGER|TABLE_OR_PARTITIONED|{native_cardinality}",
        "LEDGER_COLUMN|NATIVE_LEDGER|1|version|text|t|NO_DEFAULT",
        "LEDGER_COLUMN|NATIVE_LEDGER|2|statements|text[]|f|NO_DEFAULT",
        "LEDGER_COLUMN|NATIVE_LEDGER|3|name|text|f|NO_DEFAULT",
        "LEDGER_COLUMN|NATIVE_LEDGER|4|created_by|text|f|NO_DEFAULT",
        "LEDGER_COLUMN|NATIVE_LEDGER|5|idempotency_key|text|f|NO_DEFAULT",
        "LEDGER_COLUMN|NATIVE_LEDGER|6|rollback|text[]|f|NO_DEFAULT",
        receipt,
    ]
    if terminal_extra:
        lines.append(terminal_extra)
    return ("\n".join(lines) + "\n").encode("utf-8")


class CaptureContractTests(unittest.TestCase):
    def assert_contract_rejected(self, payload: bytes, contract: subject.CaptureContract) -> None:
        with self.assertRaises(subject.ContractFailure):
            subject.validate_payload(payload, contract)

    def test_valid_dev_capture_passes(self) -> None:
        payload = _dev_payload()
        summary = subject.validate_payload(payload, _contract("DEV", payload))
        self.assertEqual((summary.public_ledger_entry_count, summary.native_ledger_entry_count), (33, 6))

    def test_dev_wrong_public_cardinality_is_rejected(self) -> None:
        payload = _dev_payload(public_entries=32)
        self.assert_contract_rejected(payload, _contract("DEV", payload))

    def test_unknown_pipe_record_is_rejected_without_echoing_canary(self) -> None:
        payload = _dev_payload().replace(
            b"PREFLIGHT_SCOPE|",
            b"CANARY_SECRET_UNEXPECTED|",
            1,
        )
        self.assert_contract_rejected(payload, _contract("DEV", payload))

    def test_valid_prod_double_capture_is_deduplicated(self) -> None:
        half = _prod_half()
        payload = half + half
        summary = subject.validate_payload(payload, _contract("PROD", payload, duplicated=True, half=half))
        self.assertEqual((summary.physical_capture_copies, summary.logical_capture_copies), (2, 1))
        self.assertEqual(summary.native_ledger_cardinality, 32)

    def test_prod_single_capture_is_rejected(self) -> None:
        half = _prod_half()
        self.assert_contract_rejected(half, _contract("PROD", half, duplicated=True, half=half))

    def test_prod_three_captures_are_rejected(self) -> None:
        half = _prod_half()
        payload = half + half + half
        self.assert_contract_rejected(payload, _contract("PROD", payload, duplicated=True, half=half))

    def test_prod_different_halves_are_rejected(self) -> None:
        half = _prod_half()
        different_half = half.replace(b"b" * 64, b"c" * 64, 1)
        payload = half + different_half
        self.assert_contract_rejected(payload, _contract("PROD", payload, duplicated=True, half=half))

    def test_prod_missing_receipt_is_rejected(self) -> None:
        half = _prod_half(receipt="ROLLBACK")
        payload = half + half
        self.assert_contract_rejected(payload, _contract("PROD", payload, duplicated=True, half=half))

    def test_prod_nonterminal_receipt_is_rejected(self) -> None:
        half = _prod_half(terminal_extra="BEGIN")
        payload = half + half
        self.assert_contract_rejected(payload, _contract("PROD", payload, duplicated=True, half=half))

    def test_prod_native_cardinality_different_is_rejected(self) -> None:
        half = _prod_half(native_cardinality=31)
        payload = half + half
        self.assert_contract_rejected(payload, _contract("PROD", payload, duplicated=True, half=half))

    def test_mode_644_is_rejected(self) -> None:
        payload = _dev_payload()
        contract = _contract("DEV", payload)
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "capture.txt"
            path.write_bytes(payload)
            path.chmod(0o644)
            with self.assertRaises(subject.ContractFailure):
                subject.validate_file(path, contract)

    def test_cli_never_echoes_canary_or_input(self) -> None:
        payload = b"CANARY_SECRET_VALUE|unexpected\n"
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "capture.txt"
            path.write_bytes(payload)
            path.chmod(0o600)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(subject.__file__).resolve()),
                    "--environment",
                    "DEV",
                    "--input",
                    str(path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("RESULT=FAIL_F2_CAPTURE_CONTRACT", completed.stdout)
        self.assertNotIn("CANARY_SECRET_VALUE", completed.stdout)
        self.assertNotIn("CANARY_SECRET_VALUE", completed.stderr)
        self.assertNotIn(str(path), completed.stdout)
        self.assertNotIn(str(path), completed.stderr)


if __name__ == "__main__":
    unittest.main()
