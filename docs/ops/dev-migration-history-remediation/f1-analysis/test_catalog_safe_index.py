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
import importlib.util


REPO_ROOT = Path(__file__).resolve().parents[4]
ANALYSIS_DIR = REPO_ROOT / "docs" / "ops" / "dev-migration-history-remediation" / "f1-analysis"
INDEXER = ANALYSIS_DIR / "catalog-safe-index.py"
COMPARATOR = ANALYSIS_DIR / "generate-reference-comparison.py"
RUNNER = ANALYSIS_DIR / "run-pg17-reference.sh"
CONTRACT = ANALYSIS_DIR / "dev_receipt_contract.py"
SEALED_F1 = "SEALED_F1"
STRICT_FUTURE = "STRICT_FUTURE"
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


def _run_index(
    source: str,
    input_path: Path,
    output_path: Path,
    dev_profile: str = STRICT_FUTURE,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-I",
        "-B",
        str(INDEXER),
        "--source",
        source,
    ]
    if source == "DEV":
        command.extend(("--dev-profile", dev_profile))
    command.extend(("--input", str(input_path), "--output", str(output_path)))
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        encoding="utf-8",
        text=True,
    )


def _dev_fixture(
    *,
    preflight_count: int = 1,
    public_state: str = "EXPECTED_33",
    native_state: str = "EXPECTED_6",
    public_entries: int = 33,
    native_entries: int = 6,
    fingerprints: int = 6,
    include_echo: bool = True,
    include_rollback: bool = True,
    rollback_count: int = 1,
    preflight_after_rollback: bool = False,
    catalog_after_terminal: bool = False,
    abort_marker: str | None = None,
    canary: str = "NO_CANARY",
) -> str:
    lines = [
        "",
        "BEGIN",
        "SET",
        "SET",
        "SET",
        "SET",
        "SET",
        "TARGET_DIGEST | " + "a" * 64,
        "F1_SESSION | 170006 | repeatable read | on | off | t | f | TARGET_BINDING_PRESENT_FORMAT_VALID_NOT_PRINTED",
    ]
    preflight = (
        "PREFLIGHT_SCOPE | F1_SCOPE_OK | NO_DOMAIN | NO_STATEMENTS | "
        "NO_UNEXPECTED_GRANTEE | TARGET_OPAQUE | ROW_SECURITY_OFF | "
        "LEDGER_COUNTS_EXPECTED | ACL_SCOPE_COMPLETE"
    )
    if not preflight_after_rollback:
        lines.extend(preflight for _ in range(preflight_count))
    lines.append("PUBLIC_LEDGER_COUNT_EXPECTATION | " + public_state)
    lines.extend(
        "PUBLIC_LEDGER_ENTRY | {position} | {digest} | f".format(
            position=position,
            digest=f"{position:032x}",
        )
        for position in range(1, public_entries + 1)
    )
    lines.append("NATIVE_LEDGER_COUNT_EXPECTATION | " + native_state)
    lines.extend(
        "NATIVE_LEDGER_ENTRY | {position} | {digest} | 1".format(
            position=position,
            digest=f"{position:032x}",
        )
        for position in range(1, native_entries + 1)
    )
    lines.extend(
        "NATIVE_LEDGER_STATEMENT_FINGERPRINT | {position} | {digest} | "
        "DDL_PATTERN".format(
            position=position,
            digest=f"{position:032x}",
        )
        for position in range(1, fingerprints + 1)
    )
    lines.extend(
        (
            "CATALOG_SCHEMA | public | " + canary,
            abort_marker or "",
        )
    )
    if include_rollback:
        lines.extend("ROLLBACK" for _ in range(rollback_count))
    if preflight_after_rollback:
        lines.extend(preflight for _ in range(preflight_count))
    if catalog_after_terminal:
        lines.append("CATALOG_SCHEMA | public | " + canary)
    if include_echo:
        lines.append("ROLLBACK_COMPLETED_F1")
    lines.append("")
    return "\n".join(lines)


def _reference_fixture() -> str:
    return "\n".join(
        (
            "REFERENCE_CATALOG_ADAPTER",
            "CATALOG_SCHEMA|public|NO_DIRECT_NSPACL",
            "REFERENCE_CATALOG_ROLLBACK_COMPLETED",
            "",
        )
    )


def _load_module(name: str, path: Path) -> object:
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("módulo indisponível")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_indexer() -> object:
    return _load_module("f1_catalog_safe_index_test", INDEXER)


def _load_comparator() -> object:
    return _load_module("f1_reference_comparator_test", COMPARATOR)


def _load_contract() -> object:
    return _load_module("f1_dev_receipt_contract", CONTRACT)


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
                expected_count = 2 if source == "DEV" else 1
                expected_types = (
                    {"CATALOG_SCHEMA": 1, "PREFLIGHT_SCOPE": 1}
                    if source == "DEV"
                    else {"CATALOG_SCHEMA": 1}
                )
                self.assertEqual(document["record_count"], expected_count)
                self.assertEqual(document["record_type_counts"], expected_types)
                self.assertNotIn("record_type", document["source_observed_record_type_counts"])
                if source == "DEV":
                    self.assertEqual(document["source_observed_record_type_counts"]["PUBLIC_LEDGER_ENTRY"], 33)
                    self.assertEqual(document["source_observed_record_type_counts"]["NATIVE_LEDGER_ENTRY"], 6)
                    self.assertEqual(
                        document["source_observed_record_type_counts"]["NATIVE_LEDGER_STATEMENT_FINGERPRINT"],
                        6,
                    )
                    self.assertEqual(document["receipt_marker_counts"]["ROLLBACK_COMPLETED_F1"], 1)
                    self.assertEqual(document["rollback_receipt_state"], "F1_ECHO_OBSERVED")

    def test_parser_and_comparator_share_one_dev_contract(self) -> None:
        indexer = _load_indexer()
        comparator = _load_comparator()
        contract = _load_contract()
        self.assertEqual(indexer.DEV_RECEIPT_CONTRACT, comparator.DEV_RECEIPT_CONTRACT)
        self.assertEqual(indexer.DEV_RECEIPT_CONTRACT, contract.DEV_RECEIPT_CONTRACT)
        self.assertEqual(
            indexer.DEV_RECEIPT_CONTRACT_SHA256,
            comparator.DEV_RECEIPT_CONTRACT_SHA256,
        )
        self.assertEqual(
            indexer.DEV_RECEIPT_CONTRACT_SHA256,
            contract.DEV_RECEIPT_CONTRACT_SHA256,
        )

    def test_strict_future_accepts_capture_with_internal_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="f1-strict-future-") as directory:
            root = Path(directory)
            input_path = root / "strict-dev.txt"
            output_path = root / "strict-dev.json"
            input_path.write_text(_dev_fixture(), encoding="utf-8")
            result = _run_index("DEV", input_path, output_path, STRICT_FUTURE)
            self.assertEqual(result.returncode, 0)
            document = json.loads(output_path.read_text(encoding="ascii"))
            self.assertEqual(document["rollback_receipt_state"], "F1_ECHO_OBSERVED")

    def test_sealed_f1_accepts_capture_style_without_echo_before_serialization(self) -> None:
        indexer = _load_indexer()
        document, _observed = indexer._parse(
            _dev_fixture(include_echo=False),
            "DEV",
            SEALED_F1,
        )
        self.assertEqual(document["rollback_receipt_state"], "PSQL_ROLLBACK_COMMAND_OBSERVED")
        self.assertNotIn("ROLLBACK_COMPLETED_F1", document["receipt_marker_counts"])

    def test_unknown_pipe_record_is_rejected_without_canary_emission(self) -> None:
        self._assert_rejected_without_canary("UNKNOWN_RECORD_TYPE|{canary}\n")

    def test_unknown_nonpipe_marker_is_rejected_without_canary_emission(self) -> None:
        self._assert_rejected_without_canary("{canary}\n")

    def test_runner_rejects_mode_644_before_docker_or_parser(self) -> None:
        self._assert_runner_preflight_failure(0o644, "EVIDENCE_MODE")

    def test_runner_rejects_wrong_sha_before_docker_or_parser(self) -> None:
        self._assert_runner_preflight_failure(0o600, "EVIDENCE_SHA256")

    def test_sealed_profile_rejects_mode_644_without_canary_emission(self) -> None:
        self._assert_sealed_profile_evidence_rejected(0o644)

    def test_sealed_profile_rejects_wrong_sha_without_canary_emission(self) -> None:
        self._assert_sealed_profile_evidence_rejected(0o600)

    def test_dev_rejects_missing_preflight_scope_without_canary_emission(self) -> None:
        self._assert_dev_rejected_without_canary(preflight_count=0)

    def test_dev_rejects_duplicate_preflight_scope_without_canary_emission(self) -> None:
        self._assert_dev_rejected_without_canary(preflight_count=2)

    def test_dev_rejects_wrong_expectation_states_without_canary_emission(self) -> None:
        self._assert_dev_rejected_without_canary(
            public_state="UNEXPECTED_33",
            native_state="UNEXPECTED_6",
        )

    def test_dev_rejects_32_public_entries_without_canary_emission(self) -> None:
        self._assert_dev_rejected_without_canary(public_entries=32)

    def test_dev_rejects_5_native_entries_without_canary_emission(self) -> None:
        self._assert_dev_rejected_without_canary(native_entries=5)

    def test_dev_rejects_5_native_fingerprints_without_canary_emission(self) -> None:
        self._assert_dev_rejected_without_canary(fingerprints=5)

    def test_dev_rejects_preflight_after_rollback_without_canary_emission(self) -> None:
        self._assert_dev_rejected_without_canary(preflight_after_rollback=True)

    def test_dev_rejects_catalog_after_terminal_without_canary_emission(self) -> None:
        self._assert_dev_rejected_without_canary(catalog_after_terminal=True)

    def test_dev_rejects_missing_rollback_without_canary_emission(self) -> None:
        self._assert_dev_rejected_without_canary(
            include_rollback=False,
            include_echo=False,
        )

    def test_dev_rejects_duplicate_rollback_without_canary_emission(self) -> None:
        self._assert_dev_rejected_without_canary(rollback_count=2)

    def test_strict_future_rejects_rollback_without_echo_without_canary_emission(self) -> None:
        self._assert_dev_rejected_without_canary(include_echo=False)

    def test_dev_rejects_abort_marker_without_canary_emission(self) -> None:
        self._assert_dev_rejected_without_canary(
            abort_marker="F1_ABORT_UNEXPECTED_PUBLIC_LEDGER_COUNT"
        )

    def test_comparator_rejects_nonpinned_index_in_sealed_profile(self) -> None:
        canary = "SYNTHETIC_CANARY_" + secrets.token_hex(24)
        with tempfile.TemporaryDirectory(prefix="f1-index-digest-") as directory:
            root = Path(directory)
            input_path = root / "strict-dev.txt"
            output_path = root / "strict-dev.json"
            input_path.write_text(_dev_fixture(canary=canary), encoding="utf-8")
            result = _run_index("DEV", input_path, output_path)
            self.assertEqual(result.returncode, 0)
            self.assertNotIn(canary, output_path.read_text(encoding="ascii"))
            comparator = _load_comparator()
            accepted = comparator._read_index(output_path, "DEV", STRICT_FUTURE)
            self.assertEqual(accepted["rollback_receipt_state"], "F1_ECHO_OBSERVED")
            with self.assertRaises(ValueError) as rejected:
                comparator._read_index(output_path, "DEV", SEALED_F1)
            self.assertNotIn(canary, str(rejected.exception))

    def test_comparator_rejects_incoherent_rollback_receipt_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="f1-index-state-") as directory:
            root = Path(directory)
            input_path = root / "strict-dev.txt"
            output_path = root / "strict-dev.json"
            input_path.write_text(_dev_fixture(), encoding="utf-8")
            self.assertEqual(_run_index("DEV", input_path, output_path).returncode, 0)
            document = json.loads(output_path.read_text(encoding="ascii"))
            document["rollback_receipt_state"] = "PSQL_ROLLBACK_COMMAND_OBSERVED"
            output_path.write_text(
                json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="ascii",
            )
            with self.assertRaises(ValueError):
                _load_comparator()._read_index(output_path, "DEV", STRICT_FUTURE)

    def test_analysis_files_contain_no_personal_path_literal(self) -> None:
        forbidden = "/" + "home/"
        files = [
            path
            for path in ANALYSIS_DIR.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ]
        self.assertTrue(files)
        for path in files:
            self.assertNotIn(forbidden, path.read_text(encoding="utf-8"))

    def test_terminal_retirement_absent_in_dev_is_equal(self) -> None:
        comparator = _load_comparator()
        transient = "1" * 64
        replacement = "2" * 64
        trace = {
            0: {
                "safe_key_sha256": [transient],
                "retired_safe_key_sha256": [],
                "introduced_safe_key_sha256": [transient],
                "modified_safe_key_sha256": [],
                "transition_record_types": {transient: "CATALOG_RLS_POLICY"},
            },
            1: {
                "safe_key_sha256": sorted([transient, replacement]),
                "retired_safe_key_sha256": [transient],
                "introduced_safe_key_sha256": [replacement],
                "modified_safe_key_sha256": [],
                "transition_record_types": {
                    transient: "CATALOG_RLS_POLICY",
                    replacement: "CATALOG_RLS_POLICY",
                },
            },
        }
        final_keys, terminal_absence, unresolved = comparator._terminal_retirement_plan(
            trace[0],
            0,
            trace,
            {replacement: "3" * 64},
        )
        self.assertEqual(final_keys, [])
        self.assertEqual(terminal_absence, [transient])
        self.assertEqual(unresolved, [])
        equality = comparator._equality_for_plan(
            final_keys,
            terminal_absence,
            unresolved,
            {replacement: "3" * 64},
            {},
        )
        self.assertEqual(equality, "EQUAL")
        self.assertEqual(
            comparator._classify(18, equality, 0, unresolved),
            "PHYSICAL_EFFECTS_PRESENT",
        )

    def test_terminal_retirement_still_present_in_dev_is_different(self) -> None:
        comparator = _load_comparator()
        transient = "4" * 64
        replacement = "5" * 64
        trace = {
            0: {
                "safe_key_sha256": [transient],
                "retired_safe_key_sha256": [],
                "introduced_safe_key_sha256": [transient],
                "modified_safe_key_sha256": [],
                "transition_record_types": {transient: "CATALOG_RLS_POLICY"},
            },
            1: {
                "safe_key_sha256": sorted([transient, replacement]),
                "retired_safe_key_sha256": [transient],
                "introduced_safe_key_sha256": [replacement],
                "modified_safe_key_sha256": [],
                "transition_record_types": {
                    transient: "CATALOG_RLS_POLICY",
                    replacement: "CATALOG_RLS_POLICY",
                },
            },
        }
        final_keys, terminal_absence, unresolved = comparator._terminal_retirement_plan(
            trace[0],
            0,
            trace,
            {replacement: "6" * 64},
        )
        equality = comparator._equality_for_plan(
            final_keys,
            terminal_absence,
            unresolved,
            {replacement: "6" * 64},
            {transient: "7" * 64},
        )
        self.assertEqual(equality, "DIFFERENT_OR_PARTIAL")
        self.assertEqual(
            comparator._classify(18, equality, 1, unresolved),
            "PARTIAL_OR_CONFLICTING",
        )

    def test_missing_final_key_without_directional_retirement_is_different(self) -> None:
        comparator = _load_comparator()
        transient = "8" * 64
        trace = {
            0: {
                "safe_key_sha256": [transient],
                "retired_safe_key_sha256": [],
                "introduced_safe_key_sha256": [transient],
                "modified_safe_key_sha256": [],
                "transition_record_types": {transient: "CATALOG_RLS_POLICY"},
            },
        }
        final_keys, terminal_absence, unresolved = comparator._terminal_retirement_plan(
            trace[0],
            0,
            trace,
            {},
        )
        self.assertEqual(final_keys, [])
        self.assertEqual(terminal_absence, [])
        self.assertEqual(unresolved, [transient])
        self.assertEqual(
            comparator._equality_for_plan(
                final_keys,
                terminal_absence,
                unresolved,
                {},
                {},
            ),
            "DIFFERENT_OR_PARTIAL",
        )

    def test_unresolved_reference_gap_cannot_be_present_or_absent(self) -> None:
        comparator = _load_comparator()
        unresolved = ["9" * 64]
        self.assertEqual(
            comparator._classify(1, "DIFFERENT_OR_PARTIAL", 0, unresolved),
            "PARTIAL_OR_CONFLICTING",
        )
        self.assertEqual(
            comparator._classify(40, "DIFFERENT_OR_PARTIAL", 0, unresolved),
            "PARTIAL_OR_CONFLICTING",
        )
        self.assertEqual(
            comparator._classify(13, "EQUAL", 1, unresolved),
            "NOT_SCHEMA_DECIDABLE",
        )

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

    def _assert_dev_rejected_without_canary(self, **fixture_kwargs: object) -> None:
        canary = "SYNTHETIC_CANARY_" + secrets.token_hex(24)
        with tempfile.TemporaryDirectory(prefix="f1-dev-indexer-reject-") as directory:
            root = Path(directory)
            valid_input = root / "valid-dev.txt"
            invalid_input = root / "invalid-dev.txt"
            output = root / "dev-index.json"
            valid_input.write_text(_dev_fixture(), encoding="utf-8")
            baseline = _run_index("DEV", valid_input, output)
            self.assertEqual(baseline.returncode, 0)
            baseline_json = output.read_bytes()
            invalid_input.write_text(
                _dev_fixture(canary=canary, **fixture_kwargs),
                encoding="utf-8",
            )
            result = _run_index("DEV", invalid_input, output)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(canary, result.stdout)
            self.assertNotIn(canary, result.stderr)
            self.assertEqual(output.read_bytes(), baseline_json)
            self.assertNotIn(canary, output.read_text(encoding="ascii"))

    def _assert_sealed_profile_evidence_rejected(self, mode: int) -> None:
        canary = "SYNTHETIC_CANARY_" + secrets.token_hex(24)
        with tempfile.TemporaryDirectory(prefix="f1-sealed-profile-") as directory:
            root = Path(directory)
            evidence = root / "evidence.txt"
            output = root / "sealed-index.json"
            evidence.write_text(_dev_fixture(canary=canary), encoding="utf-8")
            os.chmod(evidence, mode)
            result = _run_index("DEV", evidence, output, SEALED_F1)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(canary, result.stdout)
            self.assertNotIn(canary, result.stderr)
            self.assertFalse(output.exists())

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
