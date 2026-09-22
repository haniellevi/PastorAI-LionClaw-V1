"""Synthetic, source-only tests for the E4b closed-manifest builder."""

from __future__ import annotations

import ast
from dataclasses import fields, replace
import importlib.util
import json
from pathlib import Path
import sys
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BUILDER_PATH = REPOSITORY_ROOT / "backend" / "scripts" / "e4b_dependency_manifest_builder.py"
CORE_PATH = REPOSITORY_ROOT / "backend" / "scripts" / "e4b_authenticated_operational_projection.py"
MODULE_NAME = "e4b_dependency_manifest_builder_r2"
POLICY_TABLES = (
    "_ELIGIBLE_PREFIXES",
    "_ELIGIBLE_EXACT",
    "_PROTECTED_DIRECTORIES",
    "_PROTECTED_SUFFIXES",
)


def load_builder():
    spec = importlib.util.spec_from_file_location(MODULE_NAME, BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("builder specification unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(MODULE_NAME, None)
        raise
    return module


def literal_tables(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in POLICY_TABLES:
                values[target.id] = ast.literal_eval(node.value)
    if set(values) != set(POLICY_TABLES):
        raise AssertionError("classification tables unavailable")
    return values


class ClosedManifestBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(BUILDER_PATH.is_file(), "builder must be added before this suite can pass")
        self.builder = load_builder()

    def tearDown(self) -> None:
        if sys.modules.get(MODULE_NAME) is self.builder:
            sys.modules.pop(MODULE_NAME, None)

    def candidate(self, **overrides):
        values = {
            "commit_sha": "a" * 40,
            "tree_sha": "b" * 40,
            "parent_sha": "c" * 40,
            "base_sha": "d" * 40,
            "ancestry_digest_sha256": "e" * 64,
        }
        values.update(overrides)
        return self.builder.CandidateIdentity(**values)

    def metadata(self, path: str, object_id: str, **overrides):
        values = {
            "path": path,
            "object_id": object_id,
            "mode": "100644",
            "size": 7,
        }
        values.update(overrides)
        return self.builder.InventoryMetadata(**values)

    def selection(self, path: str, digest: str):
        return self.builder.ResolvedSelection(path=path, sha256=digest)

    def inventory(self, *entries):
        return self.builder.DependencyInventory(entries=tuple(entries))

    def resolution(self, *selections, status: str = "RESOLVED"):
        return self.builder.ManifestResolution(status=status, selected=tuple(selections))

    def assert_code(self, code: str, callback) -> None:
        with self.assertRaises(self.builder.ClosedManifestError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def normal_inputs(self):
        first = self.metadata("backend/scripts/alpha.py", "1" * 40)
        second = self.metadata("docs/missions/beta.md", "2" * 40)
        candidate = self.candidate()
        inventory = self.inventory(first, second)
        resolution = self.resolution(self.selection(first.path, "a" * 64))
        return candidate, inventory, resolution, first, second

    def test_privacy_ast_and_policy_tables_match_core(self) -> None:
        source = BUILDER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(BUILDER_PATH))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        call_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        privacy_checks = {
            "os": "os" not in imported,
            "pathlib": "pathlib" not in imported,
            "tempfile": "tempfile" not in imported,
            "shutil": "shutil" not in imported,
            "subprocess": "subprocess" not in imported,
            "socket": "socket" not in imported,
            "web": not ({"urllib", "http", "ssl"} & imported),
            "database": "sqlite3" not in imported,
            "clock": "time" not in imported,
            "randomness": "random" not in imported,
            "secrets": "secrets" not in imported,
            "open": "open" not in call_names,
            "runtime_core": "e4b_authenticated_operational_projection" not in source,
        }
        self.assertEqual(len(privacy_checks), 13)
        self.assertTrue(all(privacy_checks.values()), privacy_checks)
        self.assertEqual(imported, {"__future__", "dataclasses", "json", "re"})
        self.assertEqual(literal_tables(BUILDER_PATH), literal_tables(CORE_PATH))
        self.assertNotIn("COVERAGE_INVALID", self.builder._ERROR_CODES)
        contract = (
            REPOSITORY_ROOT
            / "docs"
            / "ops"
            / "e4b-filadelfia-catalog-materialization"
            / "E4B-OPERATIONAL-PROJECTION-CONTRACT-v1.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(self.builder._MAX_FILE_SIZE, (1 << 63) - 1)
        self.assertIn(
            "The builder accepts an exact built-in integer `size` in `0..2^63-1` "
            "before any decimal conversion.",
            contract,
        )
        self.assertIn("This is a conservative restriction specific to the builder.", contract)
        self.assertIn("Every manifest emitted by the builder remains accepted by the parser.", contract)
        self.assertIn("This does not claim bidirectional equivalence.", contract)

    def test_absence_empty_unknown_and_dynamic_are_terminal(self) -> None:
        candidate = self.candidate()
        empty_resolution = self.resolution()
        self.assert_code(
            "INVENTORY_ABSENT",
            lambda: self.builder.build_closed_manifest(candidate, None, empty_resolution),
        )
        empty = self.builder.build_closed_manifest(candidate, self.inventory(), empty_resolution)
        self.assertIs(type(empty), self.builder.EmptyManifestResult)
        self.assert_code("MANIFEST_EMPTY", lambda: self.builder.serialize_closed_manifest(empty))
        unknown = self.metadata("misc/unclassified.txt", "3" * 40)
        self.assert_code(
            "UNKNOWN",
            lambda: self.builder.build_closed_manifest(
                candidate,
                self.inventory(unknown),
                self.resolution(self.selection(unknown.path, "c" * 64)),
            ),
        )
        known = self.metadata("backend/scripts/alpha.py", "4" * 40)
        for status, code in (("UNKNOWN", "UNKNOWN"), ("DYNAMIC", "DYNAMIC")):
            with self.subTest(status=status):
                self.assert_code(
                    code,
                    lambda status=status: self.builder.build_closed_manifest(
                        candidate,
                        self.inventory(known),
                        self.resolution(status=status),
                    ),
                )

    def test_duplicate_metadata_conflict_and_inventory_casefold_fail_closed(self) -> None:
        candidate, _inventory, resolution, first, _second = self.normal_inputs()
        self.assert_code(
            "DUPLICATE_IDENTITY",
            lambda: self.builder.build_closed_manifest(
                candidate, self.inventory(first, first), resolution
            ),
        )
        conflicting = self.metadata(first.path, first.object_id, size=first.size + 1)
        self.assert_code(
            "CONFLICTING_IDENTITY",
            lambda: self.builder.build_closed_manifest(
                candidate, self.inventory(first, conflicting), resolution
            ),
        )
        upper = self.metadata("backend/scripts/Alpha.py", "5" * 40)
        lower = self.metadata("backend/scripts/alpha.py", "6" * 40)
        self.assert_code(
            "CONFLICTING_IDENTITY",
            lambda: self.builder.build_closed_manifest(
                candidate,
                self.inventory(upper, lower),
                self.resolution(self.selection(upper.path, "f" * 64)),
            ),
        )
        non_string_path = self.builder.InventoryMetadata(
            path=[], object_id="7" * 40, mode="100644", size=1
        )
        self.assert_code(
            "INVENTORY_INVALID",
            lambda: self.builder.build_closed_manifest(
                candidate, self.inventory(non_string_path), self.resolution()
            ),
        )

        class HostilePath(str):
            def __hash__(self):
                raise AssertionError("path subtype reached a hash operation")

            def casefold(self):
                raise AssertionError("path subtype reached classification")

        hostile_path = self.builder.InventoryMetadata(
            path=HostilePath("backend/scripts/hostile.py"),
            object_id="8" * 40,
            mode="100644",
            size=1,
        )
        self.assert_code(
            "INVENTORY_INVALID",
            lambda: self.builder.build_closed_manifest(
                candidate, self.inventory(hostile_path), self.resolution()
            ),
        )
        enormous_size = self.metadata(
            "backend/scripts/size.py", "9" * 40, size=10**5000
        )
        self.assert_code(
            "INVENTORY_INVALID",
            lambda: self.builder.build_closed_manifest(
                candidate,
                self.inventory(enormous_size),
                self.resolution(self.selection(enormous_size.path, "a" * 64)),
            ),
        )

    def test_selection_duplicate_digest_conflict_and_alias_fail_closed(self) -> None:
        candidate, inventory, resolution, first, _second = self.normal_inputs()
        same = self.selection(first.path, "a" * 64)
        self.assert_code(
            "SELECTION_DUPLICATE",
            lambda: self.builder.build_closed_manifest(
                candidate, inventory, self.resolution(same, same)
            ),
        )
        self.assert_code(
            "DIGEST_CONFLICT",
            lambda: self.builder.build_closed_manifest(
                candidate,
                inventory,
                self.resolution(same, self.selection(first.path, "b" * 64)),
            ),
        )

        too_many = tuple(
            self.selection(first.path, "a" * 64)
            for _ in range(self.builder.MAX_INVENTORY_ENTRIES + 1)
        )
        original_validate = self.builder._validate_selection
        validations = []

        def unexpected_validation(_selection):
            validations.append(True)
            raise AssertionError("selection validation ran before cardinality rejection")

        self.builder._validate_selection = unexpected_validation
        try:
            self.assert_code(
                "SELECTION_INVALID",
                lambda: self.builder.build_closed_manifest(
                    candidate,
                    self.inventory(first),
                    self.builder.ManifestResolution(status="RESOLVED", selected=too_many),
                ),
            )
        finally:
            self.builder._validate_selection = original_validate
        self.assertEqual(validations, [])
        protected = self.metadata("backend/media/unit.bin", first.object_id)
        self.assert_code(
            "SELECTION_INVALID",
            lambda: self.builder.build_closed_manifest(
                candidate,
                self.inventory(protected),
                self.resolution(self.selection(protected.path, "c" * 64)),
            ),
        )
        self.assert_code(
            "PROTECTED_OBJECT_ALIAS",
            lambda: self.builder.build_closed_manifest(
                candidate,
                self.inventory(first, protected),
                resolution,
            ),
        )

    def test_build_partitions_declared_inventory_without_omitted_digests(self) -> None:
        candidate, inventory, resolution, first, second = self.normal_inputs()
        result = self.builder.build_closed_manifest(candidate, inventory, resolution)
        self.assertIs(type(result), self.builder.ResolvedManifestResult)
        self.assertEqual(
            tuple(field.name for field in fields(self.builder.InventoryMetadata)),
            ("path", "object_id", "mode", "size"),
        )
        self.assertEqual(
            tuple(field.name for field in fields(self.builder.ResolvedSelection)),
            ("path", "sha256"),
        )
        raw = self.builder.serialize_closed_manifest(result)
        payload = json.loads(raw)
        self.assertEqual(payload["files"][0]["path"], first.path)
        self.assertEqual(payload["omitted"][0], {
            "path": second.path,
            "object_id": second.object_id,
            "mode": second.mode,
            "size": second.size,
        })
        self.assertNotIn("sha256", payload["omitted"][0])
        self.builder.verify_closed_manifest(result, candidate, inventory, resolution)

    def test_serializer_rejects_cross_partition_casefold_before_bytes(self) -> None:
        candidate = self.candidate()
        upper = self.metadata("backend/scripts/Alpha.py", "7" * 40)
        lower = self.metadata("backend/scripts/alpha.py", "8" * 40)
        forged = self.builder.ResolvedManifestResult(
            candidate=candidate,
            inventory=(upper, lower),
            selected=(self.selection(upper.path, "a" * 64),),
        )
        self.assert_code("CONFLICTING_IDENTITY", lambda: self.builder.serialize_closed_manifest(forged))

    def test_verifier_rejects_coverage_order_provenance_and_drift(self) -> None:
        candidate, inventory, resolution, first, second = self.normal_inputs()
        result = self.builder.build_closed_manifest(candidate, inventory, resolution)
        self.assert_code(
            "COVERAGE_MISSING",
            lambda: self.builder.verify_closed_manifest(
                replace(result, inventory=(first,)), candidate, inventory, resolution
            ),
        )
        extra = self.metadata("backend/scripts/zeta.py", "9" * 40)
        self.assert_code(
            "COVERAGE_EXTRA",
            lambda: self.builder.verify_closed_manifest(
                replace(result, inventory=(first, extra, second)), candidate, inventory, resolution
            ),
        )
        self.assert_code(
            "ORDER_INVALID",
            lambda: self.builder.verify_closed_manifest(
                replace(result, inventory=tuple(reversed(result.inventory))),
                candidate,
                inventory,
                resolution,
            ),
        )
        self.assert_code(
            "PROVENANCE_DRIFT",
            lambda: self.builder.verify_closed_manifest(
                replace(result, candidate=self.candidate(commit_sha="f" * 40)),
                candidate,
                inventory,
                resolution,
            ),
        )
        self.assert_code(
            "MANIFEST_DRIFT",
            lambda: self.builder.verify_closed_manifest(
                replace(result, selected=(self.selection(first.path, "0" * 64),)),
                candidate,
                inventory,
                resolution,
            ),
        )

    def test_count_and_serialization_budgets_fail_closed_before_excess_work(self) -> None:
        class Trap:
            def __getattribute__(self, _name: str):
                raise AssertionError("entry access after count quota")

        self.assert_code(
            "INVENTORY_LIMIT",
            lambda: self.builder.build_closed_manifest(
                self.candidate(),
                self.inventory(*(Trap() for _ in range(self.builder.MAX_INVENTORY_ENTRIES + 1))),
                self.resolution(),
            ),
        )
        prefix = "backend/scripts/"
        suffix = ".py"

        def result_for(path: str):
            metadata = self.metadata(path, "a" * 40)
            return self.builder.build_closed_manifest(
                self.candidate(),
                self.inventory(metadata),
                self.resolution(self.selection(path, "b" * 64)),
            )

        baseline = self.builder.serialize_closed_manifest(result_for(prefix + suffix))
        padding = self.builder.MAX_MANIFEST_BYTES - len(baseline)
        exact_path = prefix + ("a" * padding) + suffix
        exact = self.builder.serialize_closed_manifest(result_for(exact_path))
        self.assertEqual(len(exact), self.builder.MAX_MANIFEST_BYTES)
        self.assert_code(
            "SERIALIZATION_LIMIT",
            lambda: self.builder.serialize_closed_manifest(result_for(exact_path + "a")),
        )
        huge_path = prefix + ("a" * self.builder.MAX_MANIFEST_BYTES) + suffix
        original_dumps = self.builder.json.dumps

        def unexpected_dumps(*_args, **_kwargs):
            raise AssertionError("json.dumps ran before the serialized-byte budget")

        self.builder.json.dumps = unexpected_dumps
        try:
            self.assert_code(
                "SERIALIZATION_LIMIT",
                lambda: self.builder.serialize_closed_manifest(result_for(huge_path)),
            )
        finally:
            self.builder.json.dumps = original_dumps

    def test_serialization_is_canonical_and_final_lf_terminated(self) -> None:
        candidate, inventory, resolution, _first, _second = self.normal_inputs()
        raw = self.builder.serialize_closed_manifest(
            self.builder.build_closed_manifest(candidate, inventory, resolution)
        )
        payload = json.loads(raw)
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii") + b"\n"
        self.assertEqual(raw, canonical)
        self.assertTrue(raw.endswith(b"\n"))
        self.assertFalse(raw.endswith(b"\n\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
