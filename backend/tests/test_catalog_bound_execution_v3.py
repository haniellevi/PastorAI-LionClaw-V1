from __future__ import annotations

import ast
import dataclasses
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "backend" / "scripts"
MODULE_PATH = SCRIPTS_DIR / "catalog_bound_execution_v3.py"
WRAPPER_PATH = SCRIPTS_DIR / "execute_catalog_bound_migration_v3.py"


def _load_module(path: Path, name: str) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


execution = _load_module(MODULE_PATH, "catalog_bound_execution_v3")
wrapper = _load_module(WRAPPER_PATH, "execute_catalog_bound_migration_v3")


def _payload(kind: str) -> dict[str, object]:
    return {"type": kind, "binding": execution.c3_binding_payload()}


def _mutate(value: str) -> str:
    replacement = "0" if value[-1] != "0" else "1"
    return value[:-1] + replacement


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    return roots


def test_c3_binding_is_literal_complete_and_immutable() -> None:
    assert execution.C3_BINDING.repository_sha1 == "02a4f1aecfcf0433455e1b5c93a96b10e2358a55"
    assert execution.C3_BINDING.sql_sha256 == (
        "6952a2aaca04d6765a0bc77f831b2507e9cf5fd77d80f76e43b0816b06806e6b"
    )
    assert execution.C3_BINDING.head_sha256 == (
        "9b756191d6a3e89fca61b3c88015b1f76423692e09b12270239389bef63dd1f5"
    )
    assert execution.C3_BINDING.catalog_digest_sha256 == (
        "ed6398ff6cfc15981208631075b724fb128991682e6c7e607acf72fb913a6ac2"
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        execution.C3_BINDING.repository_sha1 = "0" * 40
    with pytest.raises((AttributeError, TypeError)):
        setattr(execution.C3_BINDING, "unexpected", "value")


@pytest.mark.parametrize(
    ("kind", "expected_type", "expected_status"),
    (
        (
            "envelope",
            execution.ExternalAuthorizationEnvelope,
            execution.VerificationStatus.EXTERNAL_AUTHORIZATION_UNVERIFIED,
        ),
        (
            "replay",
            execution.DurableReplayReceipt,
            execution.VerificationStatus.DURABLE_REPLAY_UNVERIFIED,
        ),
        (
            "cutover",
            execution.EpochCutoverDecision,
            execution.VerificationStatus.CUTOVER_UNVERIFIED,
        ),
    ),
)
def test_verification_shapes_remain_distinct_and_unverified(
    kind: str, expected_type: type[object], expected_status: object
) -> None:
    value = execution.parse_verification_envelope(_payload(kind))
    assert type(value) is expected_type
    assert value.binding is execution.C3_BINDING
    assert value.status is expected_status


def test_superseded_public_types_and_execution_intent_are_absent() -> None:
    assert not hasattr(execution, "DurableReplay")
    assert not hasattr(execution, "Cutover")
    assert not hasattr(execution, "ExecutionIntent")


def test_valid_json_validation_reports_structure_not_authorization(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = execution.main(
        [
            "catalog_bound_execution_v3.py",
            "validate",
            "--envelope",
            json.dumps(_payload("envelope")),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert captured.err == ""
    assert payload["result"] == "EXTERNAL_AUTHORIZATION_UNVERIFIED"
    assert payload["operational_authorization"] == "BLOCKED"
    assert payload["next_stage_authorized"] is False


@pytest.mark.parametrize("where", ("root", "binding"))
def test_extra_fields_are_rejected(where: str) -> None:
    payload = _payload("envelope")
    if where == "root":
        payload["unexpected"] = "extra"
    else:
        binding = payload["binding"]
        assert type(binding) is dict
        binding["unexpected"] = "extra"
    with pytest.raises(execution.InputRejected):
        execution.parse_verification_envelope(payload)


def _assert_unrecognized_envelope_proof_is_rejected(field: str) -> None:
    payload = _payload("envelope")
    payload[field] = "untrusted-claim"
    with pytest.raises(execution.InputRejected):
        execution.parse_verification_envelope(payload)


def test_envelope_owner_field_is_not_recognized_as_proof() -> None:
    _assert_unrecognized_envelope_proof_is_rejected("owner")


def test_envelope_executor_field_is_not_recognized_as_proof() -> None:
    _assert_unrecognized_envelope_proof_is_rejected("executor")


def test_envelope_hmac_field_is_not_recognized_as_proof() -> None:
    _assert_unrecognized_envelope_proof_is_rejected("hmac")


def test_envelope_nonce_field_is_not_recognized_as_proof() -> None:
    _assert_unrecognized_envelope_proof_is_rejected("nonce")


def test_envelope_receipt_field_is_not_recognized_as_proof() -> None:
    _assert_unrecognized_envelope_proof_is_rejected("receipt")


@pytest.mark.parametrize(
    "field",
    ("repository_sha1", "sql_sha256", "head_sha256", "catalog_digest_sha256"),
)
def test_mutated_complete_hashes_are_rejected(field: str) -> None:
    payload = _payload("replay")
    binding = payload["binding"]
    assert type(binding) is dict
    original = binding[field]
    assert type(original) is str
    binding[field] = _mutate(original)
    with pytest.raises(execution.InputRejected):
        execution.parse_verification_envelope(payload)


@pytest.mark.parametrize(
    "field",
    ("repository_sha1", "sql_sha256", "head_sha256", "catalog_digest_sha256"),
)
def test_hash_prefixes_are_rejected(field: str) -> None:
    payload = _payload("cutover")
    binding = payload["binding"]
    assert type(binding) is dict
    original = binding[field]
    assert type(original) is str
    binding[field] = original[:-1]
    with pytest.raises(execution.InputRejected):
        execution.parse_verification_envelope(payload)


@pytest.mark.parametrize(
    ("command", "expected_result"),
    (
        ("apply", "EXTERNAL_AUTHORIZATION_UNVERIFIED"),
        ("bootstrap", "EXTERNAL_AUTHORIZATION_UNVERIFIED"),
        ("bootstrap-ledger", "EXTERNAL_AUTHORIZATION_UNVERIFIED"),
        ("harden", "EXTERNAL_AUTHORIZATION_UNVERIFIED"),
        ("harden-ledger", "EXTERNAL_AUTHORIZATION_UNVERIFIED"),
        ("reconcile", "DURABLE_REPLAY_UNVERIFIED"),
        ("reconciliation", "DURABLE_REPLAY_UNVERIFIED"),
        ("cutover", "CUTOVER_UNVERIFIED"),
        ("legacy-ledger", "EXTERNAL_AUTHORIZATION_UNVERIFIED"),
    ),
)
def test_operational_commands_block_before_any_operational_path(
    command: str, expected_result: str, capsys: pytest.CaptureFixture[str]
) -> None:
    result = execution.main(["catalog_bound_execution_v3.py", command])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == execution.BLOCKED_EXIT
    assert captured.err == ""
    assert payload["command"] == command
    assert payload["result"] == expected_result
    assert payload["operational_authorization"] == "BLOCKED"
    assert payload["next_stage_authorized"] is False


def test_invalid_cli_is_sanitized_without_reflecting_the_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_like_value = "never-echo-this-value"
    result = execution.main(
        [
            "catalog_bound_execution_v3.py",
            "validate",
            "--envelope",
            json.dumps({"type": "envelope", "binding": execution.c3_binding_payload(), "x": secret_like_value}),
        ]
    )
    captured = capsys.readouterr()
    assert result == execution.USAGE_EXIT
    assert captured.err == ""
    assert secret_like_value not in captured.out
    assert json.loads(captured.out)["result"] == "INPUT_REJECTED"


def test_describe_is_the_only_non_validation_readout() -> None:
    payload = execution.describe_payload()
    assert payload["catalog_bound_execution"] == "V3_SOURCE_ONLY"
    assert payload["verification_types"] == {
        "envelope": "EXTERNAL_AUTHORIZATION_UNVERIFIED",
        "replay": "DURABLE_REPLAY_UNVERIFIED",
        "cutover": "CUTOVER_UNVERIFIED",
    }
    assert payload["binding"] == execution.c3_binding_payload()


def test_wrapper_delegates_only_to_v3_main() -> None:
    assert wrapper.main is execution.main


def test_v3_source_ast_rejects_historical_and_operational_dependencies() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MODULE_PATH))
    assert _import_roots(tree) == {
        "__future__",
        "argparse",
        "dataclasses",
        "enum",
        "json",
        "sys",
        "typing",
    }

    forbidden_import_roots = {
        "os",
        "subprocess",
        "socket",
        "pathlib",
        "psycopg",
        "psycopg2",
        "sqlalchemy",
        "driver",
        "apply_migrations",
        "apply_migrations_catalog_bound_v2",
        "validated_migration_catalog_snapshot",
    }
    assert not (_import_roots(tree) & forbidden_import_roots)

    forbidden_names = {
        "open",
        "exec",
        "eval",
        "compile",
        "__import__",
        "environ",
        "getenv",
        "descriptor",
        "pass_fds",
    }
    forbidden_attributes = {
        "environ",
        "getenv",
        "open",
        "read",
        "read_bytes",
        "read_text",
        "write",
        "write_text",
        "connect",
        "cursor",
        "execute",
        "fileno",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in forbidden_names
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_attributes

    constants = [
        value.value.lower()
        for value in ast.walk(tree)
        if isinstance(value, ast.Constant) and type(value.value) is str
    ]
    forbidden_fragments = (
        "pass_fds",
        "/proc/self/fd",
        "descriptor",
        "dsn",
        "driver",
        "apply_migrations_catalog_bound_v2",
        "validated_migration_catalog_snapshot",
    )
    executable_sql_fragments = (
        "select ",
        "insert ",
        "update ",
        "delete ",
        "create ",
        "alter ",
        "drop ",
        "grant ",
        "revoke ",
    )
    for fragment in forbidden_fragments + executable_sql_fragments:
        assert all(fragment not in value for value in constants)


def test_wrapper_ast_has_only_the_v3_local_import() -> None:
    tree = ast.parse(WRAPPER_PATH.read_text(encoding="utf-8"), filename=str(WRAPPER_PATH))
    assert _import_roots(tree) == {"__future__", "catalog_bound_execution_v3"}
