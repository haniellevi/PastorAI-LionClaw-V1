"""Isolated, source-only tests for the negative E4b projection precheck."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
from dataclasses import replace
from contextlib import ExitStack, contextmanager
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = BACKEND_ROOT / "scripts" / "e4b_authenticated_operational_projection.py"


def load_projection_module():
    spec = importlib.util.spec_from_file_location("e4b_projection_under_test", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("projection module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ExternalIoProbe:
    def __init__(self) -> None:
        self.calls = 0

    def reject(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("external I/O is forbidden in this test")


@contextmanager
def external_io_guard():
    probe = ExternalIoProbe()
    with ExitStack() as stack:
        for target in (
            "builtins.open",
            "os.open",
            "os.system",
            "os.popen",
            "subprocess.run",
            "subprocess.Popen",
            "subprocess.call",
            "socket.socket",
            "socket.create_connection",
            "pathlib.Path.open",
            "pathlib.Path.read_bytes",
            "pathlib.Path.read_text",
        ):
            stack.enter_context(patch(target, probe.reject))
        yield probe


class ProjectionPrecheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.projection = load_projection_module()

    def patch_receipt_bytes(
        self, *, patch_digest: str = "f" * 64, recipe_version: object = 1
    ) -> bytes:
        receipt = {
            "schema": "e4b-patch-receipt-v1",
            "candidate": {
                "commit_sha": "a" * 40,
                "tree_sha": "b" * 40,
                "parent_sha": "c" * 40,
                "base_sha": "d" * 40,
                "ancestry_digest_sha256": "e" * 64,
            },
            "patch": {
                "algorithm": "sha256",
                "digest_sha256": patch_digest,
                "recipe_id": "e4b-patch-replay",
                "recipe_version": recipe_version,
            },
        }
        return json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()

    def policy(self, receipt: bytes):
        return self.projection.TrustPolicy(
            expected_commit_sha="a" * 40,
            expected_tree_sha="b" * 40,
            expected_parent_sha="c" * 40,
            expected_base_sha="d" * 40,
            expected_ancestry_digest_sha256="e" * 64,
            expected_patch_receipt_sha256=hashlib.sha256(receipt).hexdigest(),
            expected_patch_digest_sha256="f" * 64,
            expected_patch_recipe_id="e4b-patch-replay",
            expected_patch_recipe_version=1,
        )

    def entry(self, path: bytes, object_id: str = "1" * 40):
        return self.projection.TreeEntry(
            path=path,
            object_id=object_id,
            kind="blob",
            mode="100644",
            size=17,
        )

    def test_fc09_incomplete_profile_blocks_without_any_io_or_consumer(self) -> None:
        receipt = self.patch_receipt_bytes()
        result = self.projection.preflight_blocked(
            self.policy(receipt),
            (self.entry(b"backend/scripts/example.py"),),
            ("backend/scripts/example.py",),
            self.projection.DependencyResolution(
                status="BLOCKED",
                required_paths=(),
                reason="UNPROVEN_TRANSITIVE_CLOSURE",
            ),
            receipt,
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "DEPENDENCY_CLOSURE_NOT_PROVEN")
        self.assertEqual(result["closure_status"], "NOT_PROVEN")
        self.assertEqual(result["runtime_status"], "NOT_EVALUATED")
        self.assertNotIn("projection_root", result)
        self.assertNotIn("root_digest_sha256", result)
        signature = inspect.signature(self.projection.preflight_blocked)
        self.assertNotIn("read_blob", signature.parameters)
        self.assertNotIn("consumer", signature.parameters)
        with external_io_guard() as probe:
            guarded = self.projection.preflight_blocked(
                self.policy(receipt),
                (self.entry(b"backend/scripts/example.py"),),
                ("backend/scripts/example.py",),
                self.projection.DependencyResolution(
                    status="BLOCKED",
                    required_paths=(),
                    reason="UNPROVEN_TRANSITIVE_CLOSURE",
                ),
                receipt,
            )
        self.assertEqual(guarded["reason"], "DEPENDENCY_CLOSURE_NOT_PROVEN")
        self.assertEqual(probe.calls, 0)

    def test_forged_complete_profile_is_still_source_only_blocked(self) -> None:
        receipt = self.patch_receipt_bytes()
        with external_io_guard() as probe:
            result = self.projection.preflight_blocked(
                self.policy(receipt),
                (self.entry(b"backend/scripts/example.py"),),
                ("backend/scripts/example.py",),
                self.projection.DependencyResolution(
                    status="RESOLVED",
                    required_paths=("backend/scripts/example.py",),
                    reason="COMPLETE_FOR_TEST",
                ),
                receipt,
            )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "SOURCE_ONLY_EXECUTION_DISABLED")
        self.assertEqual(probe.calls, 0)

    def test_protected_alias_blocks_before_patch_or_blob(self) -> None:
        receipt = self.patch_receipt_bytes()
        protected = self.entry(b".env.production.example", object_id="2" * 40)
        selected = self.entry(b"backend/scripts/example.py", object_id="2" * 40)
        with external_io_guard() as probe:
            result = self.projection.preflight_blocked(
                self.policy(receipt),
                (protected, selected),
                ("backend/scripts/example.py",),
                self.projection.DependencyResolution(
                    status="BLOCKED",
                    required_paths=(),
                    reason="UNPROVEN_TRANSITIVE_CLOSURE",
                ),
                receipt,
            )
        self.assertEqual(result["reason"], "PROTECTED_OBJECT_ALIAS")
        self.assertEqual(result["patch_receipt_status"], "NOT_READ")
        self.assertEqual(probe.calls, 0)

    def test_invalid_external_anchor_and_duplicate_json_block_before_blob(self) -> None:
        receipt = self.patch_receipt_bytes()
        policy = self.policy(receipt)
        bad_anchor = self.projection.TrustPolicy(
            **{
                **policy.__dict__,
                "expected_patch_digest_sha256": "0" * 64,
            }
        )
        duplicate = (
            b'{"schema":"e4b-patch-receipt-v1",'
            b'"schema":"e4b-patch-receipt-v1"}'
        )
        for candidate_policy, candidate_receipt in (
            (bad_anchor, receipt),
            (policy, duplicate),
        ):
            with self.subTest(candidate_receipt=candidate_receipt), external_io_guard() as probe:
                result = self.projection.preflight_blocked(
                    candidate_policy,
                    (self.entry(b"backend/scripts/example.py"),),
                    ("backend/scripts/example.py",),
                    self.projection.DependencyResolution(
                        status="BLOCKED",
                        required_paths=(),
                        reason="UNPROVEN_TRANSITIVE_CLOSURE",
                    ),
                    candidate_receipt,
                )
            self.assertEqual(result["reason"], "PATCH_RECEIPT_INVALID")
            self.assertEqual(probe.calls, 0)

    def test_repinned_receipt_cannot_replace_expected_patch_digest(self) -> None:
        altered = self.patch_receipt_bytes(patch_digest="0" * 64)
        with external_io_guard() as probe:
            result = self.projection.preflight_blocked(
                self.policy(altered),
                (self.entry(b"backend/scripts/example.py"),),
                ("backend/scripts/example.py",),
                self.projection.DependencyResolution(
                    status="BLOCKED",
                    required_paths=(),
                    reason="UNPROVEN_TRANSITIVE_CLOSURE",
                ),
                altered,
            )
        self.assertEqual(result["reason"], "PATCH_RECEIPT_INVALID")
        self.assertEqual(probe.calls, 0)

    def test_invalid_selected_types_block_instead_of_raising(self) -> None:
        receipt = self.patch_receipt_bytes()
        result = self.projection.preflight_blocked(
            self.policy(receipt),
            (self.entry(b"backend/scripts/example.py"),),
            ({}, 1),
            self.projection.DependencyResolution(
                status="BLOCKED",
                required_paths=(),
                reason="UNPROVEN_TRANSITIVE_CLOSURE",
            ),
            receipt,
        )
        self.assertEqual(result["reason"], "SELECTION_INVALID")

    def test_boolean_recipe_version_is_not_an_integer_version(self) -> None:
        receipt = self.patch_receipt_bytes(recipe_version=True)
        result = self.projection.preflight_blocked(
            self.policy(receipt),
            (self.entry(b"backend/scripts/example.py"),),
            ("backend/scripts/example.py",),
            self.projection.DependencyResolution(
                status="BLOCKED",
                required_paths=(),
                reason="UNPROVEN_TRANSITIVE_CLOSURE",
            ),
            receipt,
        )
        self.assertEqual(result["reason"], "PATCH_RECEIPT_INVALID")

    def test_mutated_tree_entry_type_boundaries_block_without_type_error(self) -> None:
        receipt = self.patch_receipt_bytes()
        entry = self.entry(b"backend/scripts/example.py")
        for mutated in (
            replace(entry, mode=[]),
            replace(entry, kind={}),
            replace(entry, size=True),
        ):
            with self.subTest(mutated=mutated), external_io_guard() as probe:
                result = self.projection.preflight_blocked(
                    self.policy(receipt),
                    (mutated,),
                    ("backend/scripts/example.py",),
                    self.projection.DependencyResolution(
                        status="BLOCKED",
                        required_paths=(),
                        reason="UNPROVEN_TRANSITIVE_CLOSURE",
                    ),
                    receipt,
                )
            self.assertEqual(result["reason"], "TREE_METADATA_INVALID")
            self.assertEqual(probe.calls, 0)

    def test_mutated_resolution_and_selection_type_boundaries_block(self) -> None:
        receipt = self.patch_receipt_bytes()
        valid_resolution = self.projection.DependencyResolution(
            status="BLOCKED",
            required_paths=(),
            reason="UNPROVEN_TRANSITIVE_CLOSURE",
        )
        with external_io_guard() as probe:
            resolution_result = self.projection.preflight_blocked(
                self.policy(receipt),
                (self.entry(b"backend/scripts/example.py"),),
                ("backend/scripts/example.py",),
                replace(valid_resolution, status=[]),
                receipt,
            )
            selection_result = self.projection.preflight_blocked(
                self.policy(receipt),
                (self.entry(b"backend/scripts/example.py"),),
                (True, {}),
                valid_resolution,
                receipt,
            )
        self.assertEqual(resolution_result["reason"], "DEPENDENCY_RESOLUTION_INVALID")
        self.assertEqual(selection_result["reason"], "SELECTION_INVALID")
        self.assertEqual(probe.calls, 0)

    def test_policy_boolean_and_deeply_nested_repinned_json_block(self) -> None:
        receipt = self.patch_receipt_bytes()
        bad_policy = replace(self.policy(receipt), expected_patch_digest_sha256=True)
        deeply_nested = b"[" * 20_000 + b"0" + b"]" * 20_000
        with external_io_guard() as probe:
            policy_result = self.projection.preflight_blocked(
                bad_policy,
                (self.entry(b"backend/scripts/example.py"),),
                ("backend/scripts/example.py",),
                self.projection.DependencyResolution(
                    status="BLOCKED",
                    required_paths=(),
                    reason="UNPROVEN_TRANSITIVE_CLOSURE",
                ),
                receipt,
            )
            nested_result = self.projection.preflight_blocked(
                self.policy(deeply_nested),
                (self.entry(b"backend/scripts/example.py"),),
                ("backend/scripts/example.py",),
                self.projection.DependencyResolution(
                    status="BLOCKED",
                    required_paths=(),
                    reason="UNPROVEN_TRANSITIVE_CLOSURE",
                ),
                deeply_nested,
            )
        self.assertEqual(policy_result["reason"], "TRUST_POLICY_INVALID")
        self.assertEqual(nested_result["reason"], "PATCH_RECEIPT_INVALID")
        self.assertNotIn("[" * 128, repr(nested_result))
        self.assertEqual(probe.calls, 0)

    def test_dataclass_subclasses_block_before_field_access(self) -> None:
        receipt = self.patch_receipt_bytes()
        exact_policy = self.policy(receipt)
        exact_entry = self.entry(b"backend/scripts/example.py")
        exact_resolution = self.projection.DependencyResolution(
            status="BLOCKED",
            required_paths=(),
            reason="UNPROVEN_TRANSITIVE_CLOSURE",
        )

        class ProbePolicy(self.projection.TrustPolicy):
            accesses = 0

            def __getattribute__(self, name: str):
                if name.startswith("expected_"):
                    type(self).accesses += 1
                    raise RuntimeError("policy field must not be accessed")
                return super().__getattribute__(name)

        class ProbeEntry(self.projection.TreeEntry):
            accesses = 0

            def __getattribute__(self, name: str):
                if name in {"path", "object_id", "kind", "mode", "size"}:
                    type(self).accesses += 1
                    raise RuntimeError("tree field must not be accessed")
                return super().__getattribute__(name)

        class ProbeResolution(self.projection.DependencyResolution):
            accesses = 0

            def __getattribute__(self, name: str):
                if name in {"status", "required_paths", "reason"}:
                    type(self).accesses += 1
                    raise RuntimeError("resolution field must not be accessed")
                return super().__getattribute__(name)

        policy_result = self.projection.preflight_blocked(
            ProbePolicy(**exact_policy.__dict__), (), (), exact_resolution, receipt
        )
        entry_result = self.projection.preflight_blocked(
            exact_policy,
            (ProbeEntry(**exact_entry.__dict__),),
            ("backend/scripts/example.py",),
            exact_resolution,
            receipt,
        )
        resolution_result = self.projection.preflight_blocked(
            exact_policy,
            (exact_entry,),
            ("backend/scripts/example.py",),
            ProbeResolution(**exact_resolution.__dict__),
            receipt,
        )

        self.assertEqual(policy_result["reason"], "TRUST_POLICY_INVALID")
        self.assertEqual(entry_result["reason"], "TREE_METADATA_INVALID")
        self.assertEqual(resolution_result["reason"], "DEPENDENCY_RESOLUTION_INVALID")
        self.assertEqual(ProbePolicy.accesses, 0)
        self.assertEqual(ProbeEntry.accesses, 0)
        self.assertEqual(ProbeResolution.accesses, 0)

    def test_unknown_path_and_incomplete_resolved_selection_fail_closed(self) -> None:
        receipt = self.patch_receipt_bytes()
        unknown = self.projection.preflight_blocked(
            self.policy(receipt),
            (self.entry(b"misc/unclassified.txt"),),
            (),
            self.projection.DependencyResolution(
                status="BLOCKED",
                required_paths=(),
                reason="UNPROVEN_TRANSITIVE_CLOSURE",
            ),
            receipt,
        )
        incomplete = self.projection.preflight_blocked(
            self.policy(receipt),
            (self.entry(b"backend/scripts/example.py"),),
            ("backend/scripts/example.py",),
            self.projection.DependencyResolution(
                status="RESOLVED",
                required_paths=("backend/scripts/missing.py",),
                reason="COMPLETE_FOR_TEST",
            ),
            receipt,
        )
        self.assertEqual(unknown["reason"], "UNKNOWN_PATH_CLASS")
        self.assertEqual(incomplete["reason"], "DEPENDENCY_SELECTION_INCOMPLETE")

    def test_protected_categories_are_finite_and_explicit(self) -> None:
        expected = {
            b".env",
            b".env.local.example",
            b"secrets/token.txt",
            b"backend/key.pem",
            b"backend/id_rsa_backup",
            b"backend/scripts/clerk_rotate.py",
            b"backend/scripts/target_users_private.json",
            b"backend/scripts/migrate_clerk_production.py",
            b"exports/people.json",
            b"backup/archive.bak",
            b"media/audio.mp3",
        }
        for path in expected:
            with self.subTest(path=path):
                self.assertEqual(self.projection.classify_path(path), "PROTECTED")


if __name__ == "__main__":
    unittest.main()
