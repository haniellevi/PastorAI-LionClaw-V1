"""Synthetic tests for the inert E4b external-trust-anchor boundary."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import unittest
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ANCHORS_PATH = BACKEND_ROOT / "scripts" / "e4b_external_trust_anchors.py"
CORE_PATH = BACKEND_ROOT / "scripts" / "e4b_authenticated_operational_projection.py"
ANCHORS_MODULE_NAME = "e4b_external_trust_anchors"


def load_module(name: str, path: Path):
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("candidate module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CallProbe:
    def __init__(self) -> None:
        self.calls = 0

    def reject(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("blocked anchors must not reach I/O or parsing")


class ExternalTrustAnchorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.anchors = load_module(ANCHORS_MODULE_NAME, ANCHORS_PATH)
        cls.core = load_module("e4b_projection_external_anchor_core", CORE_PATH)

    def _values(self) -> dict[str, object]:
        return {
            "expected_commit_sha": "a" * 40,
            "expected_tree_sha": "b" * 40,
            "expected_parent_sha": "c" * 40,
            "expected_base_sha": "d" * 40,
            "expected_ancestry_digest_sha256": "e" * 64,
            "expected_patch_receipt_sha256": "f" * 64,
            "expected_patch_digest_sha256": "0" * 64,
            "expected_patch_recipe_id": "e4b-patch-replay",
            "expected_patch_recipe_version": 1,
            "expected_manifest_sha256": "1" * 64,
        }

    def _parsed(self, **overrides):
        values = self._values()
        values.update(overrides)
        return self.anchors.ParsedSourceTrustAnchors(**values)

    def _canonical_bytes(self) -> bytes:
        return self.anchors.serialize_source_trust_anchor_bundle(self._parsed())

    def _payload(self) -> dict[str, object]:
        return json.loads(self._canonical_bytes())

    def _encoded(self, payload: dict[str, object]) -> bytes:
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8") + b"\n"

    def _assert_error(self, code: str, callback) -> None:
        with self.assertRaises(self.anchors.ExternalTrustAnchorError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def _verified_white_box(self, **overrides):
        """Test-only arbitrary in-process capability forging, outside threat model."""

        values = self._values()
        values.update(overrides)
        verified = object.__new__(self.anchors.VerifiedSourceTrustAnchors)
        for name, value in values.items():
            setattr(verified, name, value)
        return verified

    def test_canonical_round_trip_is_byte_identity_and_has_no_self_digest(self) -> None:
        raw = self._canonical_bytes()
        parsed = self.anchors.parse_source_trust_anchor_bundle(raw)
        self.assertIs(type(parsed), self.anchors.ParsedSourceTrustAnchors)
        self.assertEqual(parsed, self._parsed())
        self.assertEqual(self.anchors.serialize_source_trust_anchor_bundle(parsed), raw)
        payload = self._payload()
        self.assertEqual(
            tuple(payload),
            ("schema", "version", "algorithm", *self._values()),
        )
        self.assertNotIn("bundle_digest_sha256", payload)
        self.assertNotIn("self_digest", payload)
        self.assertEqual(payload["expected_manifest_sha256"], "1" * 64)

    def test_absent_empty_truncated_and_invalid_utf8_are_sanitized(self) -> None:
        cases = (
            (None, "ANCHOR_ABSENT"),
            (b"", "ANCHOR_MALFORMED"),
            (b"{", "ANCHOR_MALFORMED"),
            (b"\xff", "ANCHOR_MALFORMED"),
            ("/not-a-path-input", "ANCHOR_MALFORMED"),
            (7, "ANCHOR_MALFORMED"),
        )
        for raw, code in cases:
            with self.subTest(code=code):
                self._assert_error(code, lambda raw=raw: self.anchors.parse_source_trust_anchor_bundle(raw))

    def test_noncanonical_order_whitespace_newline_and_mutated_bytes_reject(self) -> None:
        raw = self._canonical_bytes()
        payload = self._payload()
        reordered = dict(reversed(tuple(payload.items())))
        cases = (
            raw[:-1],
            raw.replace(b":", b": ", 1),
            self._encoded(reordered),
            raw[:-1] + b" ",
        )
        for mutated in cases:
            with self.subTest(mutated=mutated[-16:]):
                self._assert_error(
                    "ANCHOR_NON_CANONICAL",
                    lambda mutated=mutated: self.anchors.parse_source_trust_anchor_bundle(mutated),
                )

    def test_duplicate_unknown_and_missing_fields_reject(self) -> None:
        duplicate = (
            b'{"schema":"e4b-external-trust-anchors-v1",'
            b'"schema":"e4b-external-trust-anchors-v1"}\n'
        )
        extra = self._payload()
        extra["unexpected"] = "x"
        missing = self._payload()
        del missing["expected_manifest_sha256"]
        cases = (
            (duplicate, "ANCHOR_FIELD_DUPLICATE"),
            (self._encoded(extra), "ANCHOR_FIELD_UNKNOWN"),
            (self._encoded(missing), "ANCHOR_FIELD_MISSING"),
        )
        for raw, code in cases:
            with self.subTest(code=code):
                self._assert_error(code, lambda raw=raw: self.anchors.parse_source_trust_anchor_bundle(raw))

    def test_exact_types_digests_and_supported_values_reject_closed(self) -> None:
        cases: list[tuple[dict[str, object], str]] = []
        bool_bundle_version = self._payload()
        bool_bundle_version["version"] = True
        cases.append((bool_bundle_version, "ANCHOR_MALFORMED"))
        bool_recipe_version = self._payload()
        bool_recipe_version["expected_patch_recipe_version"] = True
        cases.append((bool_recipe_version, "ANCHOR_MALFORMED"))
        uppercase_digest = self._payload()
        uppercase_digest["expected_manifest_sha256"] = "A" * 64
        cases.append((uppercase_digest, "ANCHOR_DIGEST_MALFORMED"))
        short_digest = self._payload()
        short_digest["expected_manifest_sha256"] = "1" * 63
        cases.append((short_digest, "ANCHOR_DIGEST_MALFORMED"))
        unsupported_algorithm = self._payload()
        unsupported_algorithm["algorithm"] = "sha512"
        cases.append((unsupported_algorithm, "ANCHOR_ALGORITHM_UNSUPPORTED"))
        unsupported_schema = self._payload()
        unsupported_schema["schema"] = "other"
        cases.append((unsupported_schema, "ANCHOR_SCHEMA_UNSUPPORTED"))
        unsupported_version = self._payload()
        unsupported_version["version"] = 2
        cases.append((unsupported_version, "ANCHOR_VERSION_UNSUPPORTED"))
        unsupported_recipe = self._payload()
        unsupported_recipe["expected_patch_recipe_id"] = "other"
        cases.append((unsupported_recipe, "ANCHOR_RECIPE_UNSUPPORTED"))
        unsupported_recipe_version = self._payload()
        unsupported_recipe_version["expected_patch_recipe_version"] = 2
        cases.append((unsupported_recipe_version, "ANCHOR_RECIPE_VERSION_UNSUPPORTED"))
        for payload, code in cases:
            with self.subTest(code=code):
                self._assert_error(
                    code,
                    lambda payload=payload: self.anchors.parse_source_trust_anchor_bundle(
                        self._encoded(payload)
                    ),
                )

    def test_limit_exact_and_plus_one_are_classified_before_decode(self) -> None:
        exact = b" " * self.anchors.MAX_ANCHOR_BUNDLE_BYTES
        self._assert_error(
            "ANCHOR_MALFORMED",
            lambda: self.anchors.parse_source_trust_anchor_bundle(exact),
        )
        with patch.object(self.anchors.json, "loads") as loads:
            self._assert_error(
                "ANCHOR_LIMIT_EXCEEDED",
                lambda: self.anchors.parse_source_trust_anchor_bundle(exact + b" "),
            )
        loads.assert_not_called()

    def test_verified_has_no_normal_constructor_or_copy_serialization_route(self) -> None:
        self._assert_error(
            "VERIFIED_ANCHORS_UNAVAILABLE",
            self.anchors.VerifiedSourceTrustAnchors,
        )
        verified = self._verified_white_box()
        self.assertTrue(self.anchors.is_valid_verified_source_trust_anchors(verified))
        for callback in (
            lambda: copy.copy(verified),
            lambda: copy.deepcopy(verified),
            lambda: pickle.dumps(verified),
        ):
            self._assert_error("VERIFIED_ANCHORS_UNAVAILABLE", callback)

    def test_parsed_absent_mutated_parsed_and_subclass_block_core_before_any_spy(self) -> None:
        parsed = self.anchors.parse_source_trust_anchor_bundle(self._canonical_bytes())
        mutated_payload = self._payload()
        mutated_payload["expected_commit_sha"] = "0" * 40
        mutated_parsed = self.anchors.parse_source_trust_anchor_bundle(
            self._encoded(mutated_payload)
        )

        class VerifiedSubclass(self.anchors.VerifiedSourceTrustAnchors):
            pass

        subclass = object.__new__(VerifiedSubclass)
        for candidate in (None, parsed, mutated_parsed, subclass):
            with self.subTest(candidate_type=type(candidate).__name__):
                reader_probe = CallProbe()
                manifest_probe = CallProbe()
                filesystem_probe = CallProbe()
                with (
                    patch.object(self.core, "_call_reader", reader_probe.reject),
                    patch.object(self.core, "_parse_dependency_manifest", manifest_probe.reject),
                    patch.object(self.core, "_valid_external_patch_receipt", manifest_probe.reject),
                    patch.object(self.core.os, "open", filesystem_probe.reject),
                    patch.object(self.core.os, "mkdir", filesystem_probe.reject),
                ):
                    with self.assertRaises(self.core.ProjectionSourceError) as raised:
                        self.core.materialize_authenticated_projection(
                            anchors=candidate,
                            manifest_bytes=b"not-read",
                            patch_receipt_bytes=b"not-read",
                            reader=reader_probe,
                            destination_parent="/not-read",
                            publication_name="not-read",
                        )
                self.assertEqual(raised.exception.code, "TRUST_ANCHORS_UNVERIFIED")
                self.assertEqual(reader_probe.calls, 0)
                self.assertEqual(manifest_probe.calls, 0)
                self.assertEqual(filesystem_probe.calls, 0)

    def test_ast_proves_no_runtime_verified_constructor_or_io_import(self) -> None:
        source = ANCHORS_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        forbidden_imports = {
            "asyncio",
            "ctypes",
            "ftplib",
            "http",
            "multiprocessing",
            "os",
            "pathlib",
            "shutil",
            "socket",
            "ssl",
            "subprocess",
            "tempfile",
            "urllib",
        }
        self.assertTrue(forbidden_imports.isdisjoint(imported_roots))
        public_functions = {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
        }
        self.assertEqual(
            public_functions,
            {
                "is_valid_verified_source_trust_anchors",
                "parse_source_trust_anchor_bundle",
                "serialize_source_trust_anchor_bundle",
            },
        )
        constructor_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "VerifiedSourceTrustAnchors"
        ]
        self.assertEqual(constructor_calls, [])
        self.assertNotIn("object.__new__", source)
        self.assertNotIn("from_path", source)
        self.assertNotIn("from_fd", source)


if __name__ == "__main__":
    unittest.main()
