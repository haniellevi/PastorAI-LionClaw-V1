"""Isolated, source-only tests for the negative E4b projection precheck."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import stat
from dataclasses import replace
from contextlib import ExitStack, contextmanager
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import urllib.request
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


class ForbiddenEffectProbe:
    def __init__(self) -> None:
        self.calls = 0

    def reject(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("forbidden external effect")


@contextmanager
def import_effect_guard():
    probe = ForbiddenEffectProbe()
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
            "urllib.request.urlopen",
            "pathlib.Path.open",
            "pathlib.Path.read_bytes",
            "pathlib.Path.read_text",
        ):
            stack.enter_context(patch(target, probe.reject))
        yield probe


@contextmanager
def network_and_subprocess_guard():
    probe = ForbiddenEffectProbe()
    with ExitStack() as stack:
        for target in (
            "os.system",
            "os.popen",
            "subprocess.run",
            "subprocess.Popen",
            "subprocess.call",
            "socket.socket",
            "socket.create_connection",
            "urllib.request.urlopen",
        ):
            stack.enter_context(patch(target, probe.reject))
        yield probe


class FakeGitReader:
    def __init__(self, facts, tree_entries, blobs, *, later_facts=None, later_tree=None):
        self.facts = facts
        self.tree_entries = tuple(tree_entries)
        self.blobs = dict(blobs)
        self.later_facts = facts if later_facts is None else later_facts
        self.later_tree = self.tree_entries if later_tree is None else tuple(later_tree)
        self.fact_calls = 0
        self.tree_calls = 0
        self.blob_calls: list[str] = []
        self.environments = []

    def _check_environment(self, environment) -> None:
        self.environments.append(dict(environment))
        if dict(environment) != {
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": "/nonexistent",
            "LANG": "C",
            "LC_ALL": "C",
            "TZ": "UTC",
        }:
            raise AssertionError("adapter received a non-fixed environment")

    def inspect_commit(self, commit_sha: str, environment):
        self._check_environment(environment)
        self.fact_calls += 1
        if commit_sha != self.facts.commit_sha:
            raise AssertionError("unexpected commit request")
        return self.facts if self.fact_calls == 1 else self.later_facts

    def list_tree(self, tree_sha: str, environment):
        self._check_environment(environment)
        self.tree_calls += 1
        if tree_sha != self.facts.tree_sha:
            raise AssertionError("unexpected tree request")
        return self.tree_entries if self.tree_calls == 1 else self.later_tree

    def read_blob(self, object_id: str, environment):
        self._check_environment(environment)
        self.blob_calls.append(object_id)
        return self.blobs[object_id]


class AuthenticatedProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.projection = load_projection_module()

    def _inputs(
        self, *, tree_entries=None, files=None, omitted=None, blobs=None, later_tree=None
    ):
        facts = self.projection.RepositoryFacts(
            commit_sha="a" * 40,
            tree_sha="b" * 40,
            parent_sha="c" * 40,
            base_sha="d" * 40,
            ancestry_digest_sha256="e" * 64,
        )
        default_files = [
            ("backend/scripts/example.py", "1" * 40, "100644", b"alpha\n"),
            ("backend/scripts/run.py", "2" * 40, "100755", b"beta\n"),
        ]
        chosen_files = default_files if files is None else files
        chosen_omitted = [] if omitted is None else omitted
        chosen_blobs = (
            {object_id: content for _path, object_id, _mode, content in chosen_files}
            if blobs is None
            else blobs
        )
        chosen_tree = (
            tuple(
                self.projection.TreeEntry(
                    path=path.encode("ascii"),
                    object_id=object_id,
                    kind="blob",
                    mode=mode,
                    size=len(content),
                )
                for path, object_id, mode, content in chosen_files
            )
            if tree_entries is None
            else tuple(tree_entries)
        )
        manifest = {
            "schema": "e4b-operational-dependency-manifest-v1",
            "candidate": {
                "commit_sha": facts.commit_sha,
                "tree_sha": facts.tree_sha,
                "parent_sha": facts.parent_sha,
                "base_sha": facts.base_sha,
                "ancestry_digest_sha256": facts.ancestry_digest_sha256,
            },
            "omitted": [
                {
                    "path": path,
                    "object_id": object_id,
                    "mode": mode,
                    "size": size,
                }
                for path, object_id, mode, size in chosen_omitted
            ],
            "files": [
                {
                    "path": path,
                    "object_id": object_id,
                    "mode": mode,
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
                for path, object_id, mode, content in chosen_files
            ],
        }
        manifest_bytes = json.dumps(
            manifest, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        patch_receipt = {
            "schema": "e4b-patch-receipt-v1",
            "candidate": manifest["candidate"],
            "patch": {
                "algorithm": "sha256",
                "digest_sha256": "f" * 64,
                "recipe_id": "e4b-patch-replay",
                "recipe_version": 1,
            },
        }
        patch_bytes = json.dumps(
            patch_receipt, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        anchors = self.projection.SourceTrustAnchors(
            expected_commit_sha=facts.commit_sha,
            expected_tree_sha=facts.tree_sha,
            expected_parent_sha=facts.parent_sha,
            expected_base_sha=facts.base_sha,
            expected_ancestry_digest_sha256=facts.ancestry_digest_sha256,
            expected_patch_receipt_sha256=hashlib.sha256(patch_bytes).hexdigest(),
            expected_patch_digest_sha256="f" * 64,
            expected_patch_recipe_id="e4b-patch-replay",
            expected_patch_recipe_version=1,
            expected_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        )
        reader = FakeGitReader(
            facts,
            chosen_tree,
            chosen_blobs,
            later_tree=chosen_tree if later_tree is None else later_tree,
        )
        return anchors, manifest_bytes, patch_bytes, reader, facts

    def _materialize(self, anchors, manifest_bytes, patch_bytes, reader, parent, name="run"):
        return self.projection.materialize_authenticated_projection(
            anchors=anchors,
            manifest_bytes=manifest_bytes,
            patch_receipt_bytes=patch_bytes,
            reader=reader,
            destination_parent=str(parent),
            publication_name=name,
        )

    def _assert_error(self, code: str, callable_):
        with self.assertRaises(self.projection.ProjectionSourceError) as raised:
            callable_()
        self.assertEqual(raised.exception.code, code)

    def test_module_import_is_inert_before_any_adapter_or_filesystem_use(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        code = compile(source, str(MODULE_PATH), "exec")
        module = types.ModuleType("e4b_projection_inert_import")
        module.__file__ = str(MODULE_PATH)
        sys.modules[module.__name__] = module
        try:
            with import_effect_guard() as probe:
                exec(code, module.__dict__)
        finally:
            sys.modules.pop(module.__name__, None)
        self.assertEqual(probe.calls, 0)

    def test_casefolded_protected_categories_reject_before_blob(self) -> None:
        protected_variants = {
            b"backend/app/.ENV",
            b"SECRETS/token.txt",
            b"backend/ID_RSA_BACKUP",
            b"backend/KEY.PEM",
            b"BACKUPS/archive.BAK",
            b"MEDIA/recording.MP3",
            b"backend/scripts/CLERK_rotate.py",
            b"backend/scripts/TARGET_USERS_private.JSON",
            b"backend/scripts/MIGRATE_CLERK_PRODUCTION.PY",
        }
        for path in protected_variants:
            with self.subTest(path=path):
                self.assertEqual(self.projection.classify_path(path), "PROTECTED")

        files = [("backend/app/.ENV", "1" * 40, "100644", b"case\n")]
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs(files=files)
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            self._assert_error(
                "MANIFEST_INVALID",
                lambda: self._materialize(
                    anchors, manifest_bytes, patch_bytes, reader, temporary
                ),
            )
            self.assertEqual(reader.fact_calls, 0)
            self.assertEqual(reader.blob_calls, [])
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_sensitive_data_artifact_names_reject_before_blob(self) -> None:
        protected_paths = (
            "backend/scripts/prod_dump.sql",
            "backend/tests/customer_export.csv",
            "backend/app/private_media.flac",
        )
        for index, path in enumerate(protected_paths, start=1):
            with self.subTest(path=path):
                self.assertEqual(
                    self.projection.classify_path(path.encode("ascii")), "PROTECTED"
                )
                files = [(path, str(index) * 40, "100644", b"synthetic\n")]
                anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs(
                    files=files
                )
                with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
                    os.chmod(temporary, 0o700)
                    self._assert_error(
                        "MANIFEST_INVALID",
                        lambda: self._materialize(
                            anchors, manifest_bytes, patch_bytes, reader, temporary
                        ),
                    )
                    self.assertEqual(reader.fact_calls, 0)
                    self.assertEqual(reader.blob_calls, [])

    def test_complete_tree_allows_manifested_ordinary_omissions(self) -> None:
        ordinary = (
            (".github/workflows/backend-tests.yml", "3" * 40, "100644", 0),
            ("AGENTS.md", "4" * 40, "100644", 0),
            ("frontend/src/app/ativar/[token]/route.ts", "5" * 40, "100644", 0),
        )
        entries = [
            self.projection.TreeEntry(
                path=path.encode("ascii"),
                object_id=object_id,
                kind="blob",
                mode=mode,
                size=size,
            )
            for path, object_id, mode, size in ordinary
        ]
        entries.extend(
            (
                self.projection.TreeEntry(
                    path=b"backend/scripts/example.py",
                    object_id="1" * 40,
                    kind="blob",
                    mode="100644",
                    size=6,
                ),
                self.projection.TreeEntry(
                    path=b"backend/scripts/run.py",
                    object_id="2" * 40,
                    kind="blob",
                    mode="100755",
                    size=5,
                ),
            )
        )
        entries.sort(key=lambda entry: entry.path)
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs(
            tree_entries=entries,
            omitted=ordinary,
        )
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            published = self._materialize(
                anchors, manifest_bytes, patch_bytes, reader, temporary
            )
            try:
                self.assertEqual(reader.blob_calls, ["1" * 40, "2" * 40])
            finally:
                published.close()

    def test_descriptor_traversal_prevents_ancestor_symlink_escape(self) -> None:
        files = [("backend/scripts/unit.py", "1" * 40, "100644", b"alpha\n")]
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs(files=files)
        original_open = self.projection.os.open
        swapped = False

        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            escaped = Path(temporary) / "outside"
            escaped.mkdir(mode=0o700)

            def swap_ancestor(path, flags, *args, **kwargs):
                nonlocal swapped
                target = os.fspath(path)
                if not swapped and flags & os.O_CREAT:
                    if target == "unit.py" and "dir_fd" in kwargs:
                        ancestor = os.readlink(f"/proc/self/fd/{kwargs['dir_fd']}")
                    elif target.endswith("/backend/scripts/unit.py"):
                        ancestor = os.path.dirname(target)
                    else:
                        return original_open(path, flags, *args, **kwargs)
                    os.rmdir(ancestor)
                    os.symlink(escaped, ancestor)
                    swapped = True
                return original_open(path, flags, *args, **kwargs)

            with patch.object(self.projection.os, "open", swap_ancestor):
                self._assert_error(
                    "MATERIALIZATION_LINK_INVALID",
                    lambda: self._materialize(
                        anchors, manifest_bytes, patch_bytes, reader, temporary
                    ),
                )
            self.assertTrue(swapped)
            self.assertFalse((escaped / "unit.py").exists())
            remaining = list(Path(temporary).iterdir())
            self.assertIn(escaped, remaining)
            attempt_shells = [path for path in remaining if path != escaped]
            self.assertEqual(len(attempt_shells), 2)
            self.assertTrue(
                all(path.is_dir() and not list(path.iterdir()) for path in attempt_shells)
            )

    def test_parent_descriptor_blocks_swap_before_staging_creation(self) -> None:
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs()
        original_reserve = self.projection._reserve_publication
        state = {"swapped": False}

        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            outer = Path(temporary)
            parent = outer / "parent"
            moved = outer / "moved-parent"
            outside = outer / "outside"
            parent.mkdir(mode=0o700)
            outside.mkdir(mode=0o700)
            os.chmod(parent, 0o700)
            os.chmod(outside, 0o700)

            def reserve_then_swap(parent_descriptor, publication_name):
                reservation = original_reserve(parent_descriptor, publication_name)
                os.rename(parent, moved)
                os.symlink(outside, parent)
                os.mkdir(outside / publication_name, 0o700)
                state["swapped"] = True
                return reservation

            with patch.object(self.projection, "_reserve_publication", reserve_then_swap):
                self._assert_error(
                    "DESTINATION_CHANGED",
                    lambda: self._materialize(
                        anchors, manifest_bytes, patch_bytes, reader, parent, "parent-swap"
                    ),
                )
            self.assertTrue(state["swapped"])
            self.assertFalse((outside / "parent-swap" / "root").exists())
            self.assertFalse((outside / "parent-swap" / "backend/scripts/example.py").exists())
            self.assertTrue((outside / "parent-swap").is_dir())
            self.assertEqual(list((outside / "parent-swap").iterdir()), [])
            self.assertTrue((moved / "parent-swap").is_dir())
            self.assertEqual(list((moved / "parent-swap").iterdir()), [])

    def test_root_handle_stays_bound_after_final_check_and_closes(self) -> None:
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs()
        original_create = self.projection._create_projection_root_handle

        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            outer = Path(temporary)
            parent = outer / "parent"
            moved = outer / "moved-parent"
            outside = outer / "outside"
            parent.mkdir(mode=0o700)
            outside.mkdir(mode=0o700)
            os.chmod(parent, 0o700)
            os.chmod(outside, 0o700)
            state = {"swapped": False}

            def create_then_swap(root_descriptor, files):
                os.rename(parent, moved)
                os.symlink(outside, parent)
                forged_root = outside / "return-handle" / "root"
                forged_root.mkdir(parents=True, mode=0o700)
                (forged_root / "backend").mkdir(mode=0o700)
                (forged_root / "backend" / "scripts").mkdir(mode=0o700)
                (forged_root / "backend" / "scripts" / "example.py").write_bytes(b"forged")
                state["swapped"] = True
                return original_create(root_descriptor, files)

            with patch.object(
                self.projection, "_create_projection_root_handle", create_then_swap
            ):
                published = self._materialize(
                    anchors, manifest_bytes, patch_bytes, reader, parent, "return-handle"
                )
            self.assertTrue(state["swapped"])
            self.assertFalse(hasattr(published, "root_path"))
            self.assertFalse(hasattr(published, "read_file"))
            self.assertEqual(
                published.root_handle.read_file("backend/scripts/example.py"), b"alpha\n"
            )
            self._assert_error(
                "PROJECTION_HANDLE_PATH_INVALID",
                lambda: published.root_handle.read_file("backend/scripts/not-selected.py"),
            )
            self._assert_error(
                "PROJECTION_HANDLE_PATH_INVALID",
                lambda: published.root_handle.read_file("../outside"),
            )
            self.assertEqual(
                (outside / "return-handle" / "root" / "backend/scripts/example.py").read_bytes(),
                b"forged",
            )
            descriptor = published.root_handle._descriptor
            self.assertIs(type(descriptor), int)
            published.close()
            published.close()
            self._assert_error(
                "PROJECTION_HANDLE_CLOSED",
                lambda: published.root_handle.read_file("backend/scripts/example.py"),
            )
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_unexpected_empty_directory_is_rejected_before_publication(self) -> None:
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs()
        original_write = self.projection._write_staged_file
        added = False

        def write_then_add_empty(root, item, blob):
            nonlocal added
            original_write(root, item, blob)
            if not added:
                os.mkdir("unexpected-empty", 0o700, dir_fd=root)
                added = True

        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            with patch.object(self.projection, "_write_staged_file", write_then_add_empty):
                self._assert_error(
                    "MATERIALIZATION_EXTRA_DIRECTORY",
                    lambda: self._materialize(
                        anchors, manifest_bytes, patch_bytes, reader, temporary
                    ),
                )
            attempt_shells = list(Path(temporary).iterdir())
            self.assertEqual(len(attempt_shells), 2)
            self.assertTrue(
                all(path.is_dir() and not list(path.iterdir()) for path in attempt_shells)
            )

    def test_adapter_exceptions_are_sanitized_and_internal_errors_preserved(self) -> None:
        for method_name in ("inspect_commit", "list_tree", "read_blob"):
            with self.subTest(method_name=method_name):
                anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs()

                def raise_external(*_args, **_kwargs):
                    raise RuntimeError("synthetic-reader-detail-must-not-leak")

                setattr(reader, method_name, raise_external)
                with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
                    os.chmod(temporary, 0o700)
                    with self.assertRaises(self.projection.ProjectionSourceError) as raised:
                        self._materialize(
                            anchors, manifest_bytes, patch_bytes, reader, temporary
                        )
                self.assertEqual(raised.exception.code, "READER_ADAPTER_FAILURE")
                self.assertNotIn("synthetic-reader-detail-must-not-leak", str(raised.exception))

        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs()

        def raise_internal(*_args, **_kwargs):
            raise self.projection.ProjectionSourceError("ADAPTER_INTERNAL")

        reader.inspect_commit = raise_internal
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            self._assert_error(
                "ADAPTER_INTERNAL",
                lambda: self._materialize(
                    anchors, manifest_bytes, patch_bytes, reader, temporary
                ),
            )

    def test_finalizes_exact_private_root_from_individual_fake_blobs(self) -> None:
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs()
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            with network_and_subprocess_guard() as probe:
                published = self._materialize(
                    anchors, manifest_bytes, patch_bytes, reader, temporary
                )
            try:
                root = Path(temporary) / "run" / "root"
                self.assertEqual(
                    published.root_handle.read_file("backend/scripts/example.py"), b"alpha\n"
                )
                self.assertEqual(
                    published.root_handle.read_file("backend/scripts/run.py"), b"beta\n"
                )
                self.assertEqual(
                    stat.S_IMODE(os.lstat(root / "backend/scripts/example.py").st_mode), 0o600
                )
                self.assertEqual(
                    stat.S_IMODE(os.lstat(root / "backend/scripts/run.py").st_mode), 0o700
                )
                self.assertTrue(stat.S_ISREG(os.lstat(root / "backend/scripts/example.py").st_mode))
                self.assertEqual(os.lstat(root / "backend/scripts/example.py").st_nlink, 1)
                self.assertEqual(reader.blob_calls, ["1" * 40, "2" * 40])
                self.assertEqual(reader.tree_calls, 2)
                self.assertEqual(reader.fact_calls, 2)
                self.assertGreaterEqual(len(reader.environments), 6)
                self.assertEqual(probe.calls, 0)
                self.assertIs(type(published.receipt), self.projection.FinalProjectionReceipt)
                sanitized = published.receipt.to_sanitized_dict()
                self.assertFalse(sanitized["operational_authorization"])
                self.assertNotIn("root_path", sanitized)
                self.assertNotIn("selected_paths", sanitized)
                self.assertNotIn("object_ids", sanitized)
            finally:
                published.close()

    def test_anchor_mismatch_blocks_before_blob_or_root(self) -> None:
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs()
        reader.facts = self.projection.RepositoryFacts(
            commit_sha="a" * 40,
            tree_sha="9" * 40,
            parent_sha="c" * 40,
            base_sha="d" * 40,
            ancestry_digest_sha256="e" * 64,
        )
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            self._assert_error(
                "REPOSITORY_ANCHOR_MISMATCH",
                lambda: self._materialize(anchors, manifest_bytes, patch_bytes, reader, temporary),
            )
            self.assertEqual(reader.blob_calls, [])
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_protected_alias_unmanifested_path_mode_and_link_block_before_blob(self) -> None:
        cases = []
        protected = self.projection.TreeEntry(
            path=b".env.synthetic.example",
            object_id="1" * 40,
            kind="blob",
            mode="100644",
            size=6,
        )
        selected = self.projection.TreeEntry(
            path=b"backend/scripts/example.py",
            object_id="1" * 40,
            kind="blob",
            mode="100644",
            size=6,
        )
        cases.append(("PROTECTED_OBJECT_ALIAS", (protected, selected)))
        cases.append(
            (
                "MANIFEST_TREE_DRIFT",
                (
                    self.projection.TreeEntry(
                        path=b"misc/unknown.txt",
                        object_id="1" * 40,
                        kind="blob",
                        mode="100644",
                        size=6,
                    ),
                ),
            )
        )
        cases.append(
            (
                "TREE_METADATA_INVALID",
                (
                    self.projection.TreeEntry(
                        path=b"backend/scripts/example.py",
                        object_id="1" * 40,
                        kind="blob",
                        mode="120000",
                        size=6,
                    ),
                ),
            )
        )
        cases.append(
            (
                "TREE_METADATA_INVALID",
                (
                    self.projection.TreeEntry(
                        path=b"backend/scripts/example.py",
                        object_id="1" * 40,
                        kind="symlink",
                        mode="120000",
                        size=6,
                    ),
                ),
            )
        )
        files = [("backend/scripts/example.py", "1" * 40, "100644", b"alpha\n")]
        for expected, tree_entries in cases:
            with self.subTest(expected=expected):
                anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs(
                    tree_entries=tree_entries, files=files
                )
                with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
                    os.chmod(temporary, 0o700)
                    self._assert_error(
                        expected,
                        lambda: self._materialize(
                            anchors, manifest_bytes, patch_bytes, reader, temporary
                        ),
                    )
                    self.assertEqual(reader.blob_calls, [])
                    self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_protected_omission_is_covered_without_a_blob_request(self) -> None:
        protected = self.projection.TreeEntry(
            path=b".env.synthetic.example",
            object_id="3" * 40,
            kind="blob",
            mode="100644",
            size=0,
        )
        selected_one = self.projection.TreeEntry(
            path=b"backend/scripts/example.py",
            object_id="1" * 40,
            kind="blob",
            mode="100644",
            size=6,
        )
        selected_two = self.projection.TreeEntry(
            path=b"backend/scripts/run.py",
            object_id="2" * 40,
            kind="blob",
            mode="100755",
            size=5,
        )
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs(
            tree_entries=(protected, selected_one, selected_two),
            omitted=[(".env.synthetic.example", "3" * 40, "100644", 0)],
        )
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            published = self._materialize(
                anchors, manifest_bytes, patch_bytes, reader, temporary
            )
            try:
                self.assertEqual(
                    published.root_handle.read_file("backend/scripts/example.py"), b"alpha\n"
                )
                self.assertEqual(reader.blob_calls, ["1" * 40, "2" * 40])
            finally:
                published.close()

    def test_manifest_drift_and_patch_repinning_fail_closed(self) -> None:
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs()
        decoded_manifest = json.loads(manifest_bytes)
        decoded_manifest["files"][0]["object_id"] = "3" * 40
        drifted_manifest = json.dumps(
            decoded_manifest, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        drifted_anchors = self.projection.SourceTrustAnchors(
            **{
                **anchors.__dict__,
                "expected_manifest_sha256": hashlib.sha256(drifted_manifest).hexdigest(),
            }
        )
        decoded_patch = json.loads(patch_bytes)
        decoded_patch["patch"]["digest_sha256"] = "0" * 64
        repinned_patch = json.dumps(
            decoded_patch, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        repinned_anchors = self.projection.SourceTrustAnchors(
            **{
                **anchors.__dict__,
                "expected_patch_receipt_sha256": hashlib.sha256(repinned_patch).hexdigest(),
            }
        )
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            self._assert_error(
                "MANIFEST_TREE_DRIFT",
                lambda: self._materialize(
                    drifted_anchors, drifted_manifest, patch_bytes, reader, temporary
                ),
            )
            self.assertEqual(reader.blob_calls, [])
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs()
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            self._assert_error(
                "PATCH_RECEIPT_INVALID",
                lambda: self._materialize(
                    repinned_anchors, manifest_bytes, repinned_patch, reader, temporary
                ),
            )
            self.assertEqual(reader.blob_calls, [])

    def test_manifest_coverage_rejects_duplicate_absent_and_extra_tree_metadata(self) -> None:
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs()
        duplicate = json.loads(manifest_bytes)
        duplicate["files"].append(dict(duplicate["files"][0]))
        duplicate_bytes = json.dumps(
            duplicate, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        duplicate_anchors = self.projection.SourceTrustAnchors(
            **{
                **anchors.__dict__,
                "expected_manifest_sha256": hashlib.sha256(duplicate_bytes).hexdigest(),
            }
        )
        absent = json.loads(manifest_bytes)
        absent["omitted"].append(
            {
                "path": "backend/scripts/absent.py",
                "object_id": "3" * 40,
                "mode": "100644",
                "size": 0,
            }
        )
        absent_bytes = json.dumps(
            absent, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        absent_anchors = self.projection.SourceTrustAnchors(
            **{
                **anchors.__dict__,
                "expected_manifest_sha256": hashlib.sha256(absent_bytes).hexdigest(),
            }
        )
        extra_tree = (
            self.projection.TreeEntry(
                path=b"backend/scripts/example.py",
                object_id="1" * 40,
                kind="blob",
                mode="100644",
                size=6,
            ),
            self.projection.TreeEntry(
                path=b"backend/scripts/extra.py",
                object_id="3" * 40,
                kind="blob",
                mode="100644",
                size=0,
            ),
            self.projection.TreeEntry(
                path=b"backend/scripts/run.py",
                object_id="2" * 40,
                kind="blob",
                mode="100755",
                size=5,
            ),
        )
        extra_reader = self._inputs(tree_entries=extra_tree)[3]
        cases = (
            ("MANIFEST_INVALID", duplicate_anchors, duplicate_bytes, reader),
            ("MANIFEST_TREE_DRIFT", absent_anchors, absent_bytes, reader),
            ("MANIFEST_TREE_DRIFT", anchors, manifest_bytes, extra_reader),
        )
        for expected, case_anchors, case_manifest, case_reader in cases:
            with self.subTest(expected=expected):
                with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
                    os.chmod(temporary, 0o700)
                    self._assert_error(
                        expected,
                        lambda: self._materialize(
                            case_anchors,
                            case_manifest,
                            patch_bytes,
                            case_reader,
                            temporary,
                        ),
                    )
                    self.assertEqual(case_reader.blob_calls, [])

    def test_blob_or_tree_toctou_fails_before_publication(self) -> None:
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs(
            blobs={"1" * 40: b"change", "2" * 40: b"beta\n"}
        )
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            self._assert_error(
                "BLOB_HASH_MISMATCH",
                lambda: self._materialize(
                    anchors, manifest_bytes, patch_bytes, reader, temporary
                ),
            )
            self.assertEqual(list(Path(temporary).iterdir()), [])
        anchors, manifest_bytes, patch_bytes, reader, facts = self._inputs()
        changed_tree = (
            self.projection.TreeEntry(
                path=b"backend/scripts/example.py",
                object_id="3" * 40,
                kind="blob",
                mode="100644",
                size=6,
            ),
            self.projection.TreeEntry(
                path=b"backend/scripts/run.py",
                object_id="2" * 40,
                kind="blob",
                mode="100755",
                size=5,
            ),
        )
        reader.later_tree = changed_tree
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            self._assert_error(
                "TREE_TOCTOU",
                lambda: self._materialize(
                    anchors, manifest_bytes, patch_bytes, reader, temporary
                ),
            )
            self.assertEqual(reader.blob_calls, ["1" * 40, "2" * 40])
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_partial_write_failure_cleans_only_attempt_root(self) -> None:
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs()
        original_write = self.projection._write_staged_file
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic write failure")
            return original_write(*args, **kwargs)

        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            sentinel = Path(temporary) / "sentinel"
            sentinel.write_text("keep", encoding="ascii")
            with patch.object(self.projection, "_write_staged_file", fail_second):
                self._assert_error(
                    "MATERIALIZATION_FAILED",
                    lambda: self._materialize(
                        anchors, manifest_bytes, patch_bytes, reader, temporary
                    ),
                )
            self.assertEqual(sentinel.read_text(encoding="ascii"), "keep")
            attempt_shells = [item for item in Path(temporary).iterdir() if item != sentinel]
            self.assertEqual(len(attempt_shells), 2)
            self.assertIn("run", {item.name for item in attempt_shells})
            self.assertTrue(
                any(item.name.startswith(".e4b-stage-") for item in attempt_shells)
            )
            self.assertTrue(
                all(item.is_dir() and not list(item.iterdir()) for item in attempt_shells)
            )

    def test_cleanup_preserves_replacement_of_reserved_publication(self) -> None:
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs()

        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            parent = Path(temporary)

            def replace_reservation_then_fail(*_args, **_kwargs):
                (parent / "run").rename(parent / "original-run")
                replacement = parent / "run"
                replacement.mkdir(mode=0o700)
                raise OSError("synthetic write failure")

            with patch.object(
                self.projection,
                "_write_staged_file",
                replace_reservation_then_fail,
            ):
                self._assert_error(
                    "MATERIALIZATION_FAILED",
                    lambda: self._materialize(
                        anchors, manifest_bytes, patch_bytes, reader, temporary
                    ),
                )
            self.assertTrue((parent / "run").is_dir())
            self.assertEqual(list((parent / "run").iterdir()), [])
            self.assertTrue((parent / "original-run").is_dir())

    def test_owned_cleanup_never_rmdirs_authenticated_name(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            parent = Path(temporary)
            owned = parent / "owned"
            owned.mkdir(mode=0o700)
            parent_descriptor = os.open(temporary, self.projection._directory_open_flags())
            owned_descriptor = os.open(
                "owned",
                self.projection._directory_open_flags(),
                dir_fd=parent_descriptor,
            )
            try:
                identity = self.projection._directory_identity(owned_descriptor)
            finally:
                os.close(owned_descriptor)

            original_rmdir = self.projection.os.rmdir
            rmdir_calls = 0

            def swap_empty_replacement_then_rmdir(name, *args, **kwargs):
                nonlocal rmdir_calls
                rmdir_calls += 1
                owned.rename(parent / "owned-original")
                owned.mkdir(mode=0o700)
                return original_rmdir(name, *args, **kwargs)

            try:
                with patch.object(
                    self.projection.os,
                    "rmdir",
                    swap_empty_replacement_then_rmdir,
                ):
                    self.projection._remove_owned_tree_at(
                        parent_descriptor,
                        "owned",
                        identity,
                    )
            finally:
                os.close(parent_descriptor)
            self.assertEqual(rmdir_calls, 0)
            self.assertTrue(owned.is_dir())

    def test_failed_publication_open_retains_empty_replacement(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            parent = Path(temporary)
            parent_descriptor = os.open(temporary, self.projection._directory_open_flags())

            def replace_then_fail(parent_fd, name):
                os.rename(name, f"{name}-original", src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                os.mkdir(name, 0o700, dir_fd=parent_fd)
                raise OSError("synthetic open failure")

            try:
                with patch.object(
                    self.projection,
                    "_open_private_child_directory",
                    replace_then_fail,
                ):
                    with self.assertRaises(OSError):
                        self.projection._reserve_publication(parent_descriptor, "run")
            finally:
                os.close(parent_descriptor)
            self.assertTrue((parent / "run").is_dir())
            self.assertTrue((parent / "run-original").is_dir())

    def test_failed_staging_open_retains_empty_replacement(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            parent = Path(temporary)
            parent_descriptor = os.open(temporary, self.projection._directory_open_flags())
            original_name = None

            def replace_then_fail(parent_fd, name):
                nonlocal original_name
                original_name = f"{name}-original"
                os.rename(name, original_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                os.mkdir(name, 0o700, dir_fd=parent_fd)
                raise OSError("synthetic open failure")

            try:
                with patch.object(
                    self.projection,
                    "_open_private_child_directory",
                    replace_then_fail,
                ):
                    with self.assertRaises(OSError):
                        self.projection._reserve_staging(parent_descriptor)
            finally:
                os.close(parent_descriptor)
            if original_name is None:
                raise AssertionError("staging name was not captured")
            replacement_name = original_name.removesuffix("-original")
            self.assertTrue((parent / replacement_name).is_dir())
            self.assertTrue((parent / original_name).is_dir())

    def test_publication_name_is_single_writer_safe(self) -> None:
        anchors, manifest_bytes, patch_bytes, reader, _facts = self._inputs()
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            first = self._materialize(
                anchors, manifest_bytes, patch_bytes, reader, temporary, name="same"
            )
            second_reader = self._inputs()[3]
            self._assert_error(
                "PUBLICATION_CONFLICT",
                lambda: self._materialize(
                    anchors,
                    manifest_bytes,
                    patch_bytes,
                    second_reader,
                    temporary,
                    name="same",
                ),
            )
            try:
                self.assertEqual(
                    first.root_handle.read_file("backend/scripts/example.py"), b"alpha\n"
                )
            finally:
                first.close()

    def test_concurrent_reservation_has_one_winner(self) -> None:
        anchors, manifest_bytes, patch_bytes, reader_one, _facts = self._inputs()
        reader_two = self._inputs()[3]
        barrier = threading.Barrier(2)
        original_reserve = None
        outcomes = []

        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            os.chmod(temporary, 0o700)
            original_reserve = self.projection._reserve_publication

            def synchronized_reserve(*args, **kwargs):
                barrier.wait(timeout=5)
                return original_reserve(*args, **kwargs)

            def run(reader):
                try:
                    outcomes.append(
                        self._materialize(
                            anchors,
                            manifest_bytes,
                            patch_bytes,
                            reader,
                            temporary,
                            name="parallel",
                        )
                    )
                except self.projection.ProjectionSourceError as error:
                    outcomes.append(error.code)

            with patch.object(self.projection, "_reserve_publication", synchronized_reserve):
                threads = [threading.Thread(target=run, args=(reader,)) for reader in (reader_one, reader_two)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=10)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(len(outcomes), 2)
            self.assertEqual(sum(type(item) is self.projection.PublishedProjection for item in outcomes), 1)
            self.assertEqual(outcomes.count("PUBLICATION_CONFLICT"), 1)
            for outcome in outcomes:
                if type(outcome) is self.projection.PublishedProjection:
                    outcome.close()

    def test_negative_precheck_remains_inert(self) -> None:
        receipt = json.dumps(
            {
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
                    "digest_sha256": "f" * 64,
                    "recipe_id": "e4b-patch-replay",
                    "recipe_version": 1,
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        policy = self.projection.TrustPolicy(
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
        with import_effect_guard() as probe:
            result = self.projection.preflight_blocked(
                policy,
                (
                    self.projection.TreeEntry(
                        path=b"backend/scripts/example.py",
                        object_id="1" * 40,
                        kind="blob",
                        mode="100644",
                        size=1,
                    ),
                ),
                ("backend/scripts/example.py",),
                self.projection.DependencyResolution(
                    status="BLOCKED", required_paths=(), reason="UNPROVEN"
                ),
                receipt,
            )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "DEPENDENCY_CLOSURE_NOT_PROVEN")
        self.assertEqual(probe.calls, 0)


if __name__ == "__main__":
    unittest.main()
