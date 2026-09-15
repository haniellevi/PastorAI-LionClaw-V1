#!/usr/bin/env python3
"""Testes sintéticos offline do parser opaco F1."""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[4]
ANALYSIS_DIR = REPO_ROOT / "docs" / "ops" / "dev-migration-history-remediation" / "f1-analysis"
INDEXER = ANALYSIS_DIR / "catalog-safe-index.py"
RUNNER = ANALYSIS_DIR / "run-pg17-reference.sh"
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


def _run_index(source: str, input_path: Path, output_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(INDEXER),
            "--source",
            source,
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        encoding="utf-8",
        text=True,
    )


def _dev_fixture() -> str:
    return "\n".join(
        (
            "",
            "BEGIN",
            "SET",
            "record_type | TARGET_DIGEST",
            "------------+----------------------------------------------------------------",
            "TARGET_DIGEST | " + "a" * 64,
            "(1 row)",
            "record_type | server_version_num | transaction_isolation | transaction_read_only | row_security_setting | current_user_matches_session_user | current_role_superuser_or_bypassrls | target_binding_state",
            "------------+--------------------+-----------------------+------------------------+----------------------+----------------------------------+--------------------------------------+----------------------------------",
            "F1_SESSION | 170006 | repeatable read | on | off | t | f | TARGET_BINDING_PRESENT_FORMAT_VALID_NOT_PRINTED",
            "(1 row)",
            "record_type | state",
            "------------+------------",
            "PUBLIC_LEDGER_COUNT_EXPECTATION | EXPECTED_33",
            "(1 row)",
            "record_type | state",
            "------------+------------",
            "NATIVE_LEDGER_COUNT_EXPECTATION | EXPECTED_6",
            "(1 row)",
            "record_type | schema_ref | acl_state",
            "------------+------------+-------------------",
            "CATALOG_SCHEMA | public | NO_DIRECT_NSPACL",
            "(1 row)",
            "ROLLBACK",
            "",
        )
    )


def _reference_fixture() -> str:
    return "\n".join(
        (
            "REFERENCE_CATALOG_ADAPTER",
            "CATALOG_SCHEMA|public|NO_DIRECT_NSPACL",
            "REFERENCE_CATALOG_ROLLBACK_COMPLETED",
            "",
        )
    )


class CatalogSafeIndexSyntheticTest(unittest.TestCase):
    def test_valid_dev_and_reference_inputs_have_closed_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="f1-indexer-valid-") as directory:
            root = Path(directory)
            dev_input = root / "dev.txt"
            reference_input = root / "reference.txt"
            dev_output = root / "dev.json"
            reference_output = root / "reference.json"
            dev_input.write_text(_dev_fixture(), encoding="utf-8")
            reference_input.write_text(_reference_fixture(), encoding="utf-8")
            for source, input_path, output_path in (
                ("DEV", dev_input, dev_output),
                ("REFERENCE", reference_input, reference_output),
            ):
                result = _run_index(source, input_path, output_path)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "")
                document = json.loads(output_path.read_text(encoding="ascii"))
                self.assertEqual(set(document), INDEX_FIELDS)
                self.assertEqual(document["format"], "F1_CATALOG_SAFE_INDEX_V3")
                self.assertEqual(document["source"], source)
                self.assertEqual(document["record_count"], 1)
                self.assertEqual(document["record_type_counts"], {"CATALOG_SCHEMA": 1})
                self.assertNotIn("record_type", document["source_observed_record_type_counts"])

    def test_unknown_pipe_record_is_rejected_without_canary_emission(self) -> None:
        self._assert_rejected_without_canary("UNKNOWN_RECORD_TYPE|{canary}\n")

    def test_unknown_nonpipe_marker_is_rejected_without_canary_emission(self) -> None:
        self._assert_rejected_without_canary("{canary}\n")

    def test_runner_rejects_mode_644_before_docker_or_parser(self) -> None:
        self._assert_runner_preflight_failure(0o644, "EVIDENCE_MODE")

    def test_runner_rejects_wrong_sha_before_docker_or_parser(self) -> None:
        self._assert_runner_preflight_failure(0o600, "EVIDENCE_SHA256")

    def _assert_rejected_without_canary(self, template: str) -> None:
        canary = "SYNTHETIC_CANARY_" + secrets.token_hex(24)
        with tempfile.TemporaryDirectory(prefix="f1-indexer-reject-") as directory:
            root = Path(directory)
            valid_input = root / "valid.txt"
            invalid_input = root / "invalid.txt"
            output = root / "index.json"
            valid_input.write_text(_reference_fixture(), encoding="utf-8")
            baseline = _run_index("REFERENCE", valid_input, output)
            self.assertEqual(baseline.returncode, 0)
            baseline_json = output.read_bytes()
            invalid_input.write_text(template.format(canary=canary), encoding="utf-8")
            result = _run_index("REFERENCE", invalid_input, output)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(canary, result.stdout)
            self.assertNotIn(canary, result.stderr)
            self.assertEqual(output.read_bytes(), baseline_json)
            self.assertNotIn(canary, output.read_text(encoding="ascii"))

    def _assert_runner_preflight_failure(self, mode: int, failure: str) -> None:
        canary = "SYNTHETIC_CANARY_" + secrets.token_hex(24)
        with (
            tempfile.TemporaryDirectory(prefix="f1-reference-indexer-", dir="/tmp") as output_directory,
            tempfile.TemporaryDirectory(prefix="f1-evidence-indexer-") as evidence_directory,
        ):
            output = Path(output_directory)
            evidence = Path(evidence_directory) / "evidence.txt"
            evidence.write_text(canary + "\n", encoding="utf-8")
            os.chmod(evidence, mode)
            result = subprocess.run(
                ["bash", str(RUNNER), str(output), str(evidence)],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                encoding="utf-8",
                text=True,
            )
            self.assertEqual(result.returncode, 4)
            self.assertEqual(result.stdout, f"RESULT=FAIL_REFERENCE_{failure}\n")
            self.assertEqual(result.stderr, "")
            self.assertNotIn(canary, result.stdout)
            self.assertNotIn(canary, result.stderr)
            self.assertEqual(list(output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
