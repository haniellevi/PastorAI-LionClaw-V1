import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from artifact_identity_receipt import compare_evidence, write_receipt


def evidence(component="backend", **changes):
    return {
        "component": component,
        "revision": "a" * 40,
        "digest": "sha256:" + "b" * 64,
        "evidence_id": "00000000-0000-4000-8000-000000000001",
        "evidence_at": "2026-01-01T12:00:00Z",
    } | changes


class ArtifactIdentityReceiptTest(unittest.TestCase):
    def test_corresponding_is_comparison_of_both_valid_identities(self):
        for component in ("backend", "frontend"):
            expected = evidence(component)
            observed = evidence(component, evidence_at="2026-01-02T12:00:00Z")
            result = compare_evidence({"component": component, "expected": expected, "observed": observed})
            self.assertEqual(result, {
                "schema_version": 1,
                "component": component,
                "expected": expected,
                "observed": observed,
                "status": "correspondente",
            })

    def test_either_revision_or_digest_difference_is_divergent(self):
        for changes in ({"revision": "c" * 40}, {"digest": "sha256:" + "d" * 64}):
            with self.subTest(changes=changes):
                result = compare_evidence({
                    "component": "backend", "expected": evidence(), "observed": evidence(**changes)
                })
                self.assertEqual(result["status"], "divergente")

    def test_missing_or_invalid_evidence_is_unknown_and_not_retained(self):
        for candidate in (
            None,
            {},
            evidence(revision="a" * 7),
            evidence(revision="z" * 40),
            evidence(digest="sha256:" + "b" * 63),
            evidence(digest="sha256:" + "z" * 64),
            evidence(evidence_at="2026-02-30T12:00:00Z"),
            evidence(evidence_id="unknown"),
            evidence("frontend"),
        ):
            for field in ("expected", "observed"):
                with self.subTest(candidate=candidate, field=field):
                    data = {"component": "backend", "expected": evidence(), "observed": evidence()}
                    data[field] = candidate
                    result = compare_evidence(data)
                    self.assertEqual(result["status"], "desconhecido")
                    self.assertIsNone(result[field])
        self.assertEqual(compare_evidence({"component": "backend"})["status"], "desconhecido")

    def test_invalid_component_is_rejected(self):
        with self.assertRaises(ValueError):
            compare_evidence({"component": "other"})

    def test_persistence_is_private_versioned_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            payload = {"component": "backend", "expected": evidence(), "observed": evidence()}
            identifier = UUID("00000000-0000-4000-8000-000000000002")
            with patch("artifact_identity_receipt.uuid4", return_value=identifier):
                first = write_receipt(payload, folder)
                before = first.read_bytes()
                with self.assertRaises(FileExistsError):
                    write_receipt({"component": "frontend"}, folder)
            self.assertEqual(first.read_bytes(), before)
            self.assertEqual(list(folder.iterdir()), [first])
            self.assertEqual(first.stat().st_mode & 0o777, 0o600)
            contents = json.loads(before)
            self.assertEqual(contents["receipt_id"], str(identifier))
            self.assertRegex(contents["recorded_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertEqual(contents["status"], "correspondente")
            self.assertEqual(contents["schema_version"], 1)

    def test_an_unknown_receipt_is_persisted_by_cli_without_data_on_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("artifact_identity_receipt.py")), directory],
                input=json.dumps({"component": "frontend"}), text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")
            files = list(Path(directory).iterdir())
            self.assertEqual(len(files), 1)
            self.assertEqual(json.loads(files[0].read_text())["status"], "desconhecido")

    def test_directory_must_be_private(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            os.chmod(folder, 0o755)
            with self.assertRaises(ValueError):
                write_receipt({"component": "backend"}, folder)
            self.assertEqual(list(folder.iterdir()), [])

    def test_private_directory_in_source_tree_is_not_a_receipt_location(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            folder = Path(directory)
            with self.assertRaises(ValueError):
                write_receipt({"component": "backend"}, folder)
            self.assertEqual(list(folder.iterdir()), [])

    def test_ambiguous_json_is_rejected_without_echoing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = {"component": "backend", "expected": evidence(), "observed": evidence()}
            ambiguous = json.dumps(payload).replace('"component": "backend"', '"component": "frontend", "component": "backend"', 1)
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("artifact_identity_receipt.py")), directory],
                input=ambiguous, text=True, capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "Não foi possível registrar o recibo privado.\n")
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
