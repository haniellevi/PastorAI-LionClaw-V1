from __future__ import annotations

import ast
import copy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "verify_migration_history_divergence_remediation_proposal_v4.py"
)
PROPOSAL_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-divergence-remediation-proposal-v4.json"
)
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-divergence-remediation-proposal-v4.schema.json"
)
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "migration-divergence-v4.yml"
)


def _load_verifier() -> Any:
    spec = importlib.util.spec_from_file_location(
        "migration_divergence_v4_verifier_tests", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verifier = _load_verifier()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _set_path(value: dict[str, Any], path: tuple[str, ...], replacement: Any) -> None:
    target = value
    for key in path[:-1]:
        child = target[key]
        assert type(child) is dict
        target = child
    target[path[-1]] = replacement


def _fake_snapshot(
    *,
    names: tuple[str, ...] = ("0001_first.sql", "0002_second.sql"),
    catalog_digest: str = "c" * 64,
    operational_authorization: bool = False,
    next_stage_authorized: bool = False,
    position_offset: int = 0,
) -> SimpleNamespace:
    entries = tuple(
        SimpleNamespace(
            position=index + position_offset,
            name=name,
            sha256=f"{index + 1:064x}",
            size_bytes=index + 10,
        )
        for index, name in enumerate(names)
    )
    return SimpleNamespace(
        head_content_sha256="a" * 64,
        schema_content_sha256="b" * 64,
        catalog_digest_sha256=catalog_digest,
        catalog_directory=str(verifier.MIGRATIONS_DIR.absolute()),
        entries=entries,
        operational_authorization=operational_authorization,
        next_stage_authorized=next_stage_authorized,
    )


def test_versioned_package_verifies_but_remains_blocked(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH)])

    assert verifier.main() == verifier.BLOCKED_EXIT == 8
    assert capsys.readouterr().out.splitlines() == [
        "RESULT=BLOCKED_MIGRATION_DIVERGENCE_V4:SOURCE_EXTENSION_VERIFIED",
        "PROPOSAL_STRUCTURE=VERIFIED_SOURCE_ONLY",
        "CATALOG_SNAPSHOTS=2_STABLE_EQUAL",
        "V3_ENVIRONMENT_AND_CUTOVER_STATE=PRESERVED_UNCHANGED",
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "NEXT_STAGE_AUTHORIZED=false",
    ]


def test_cli_rejects_all_arguments_before_reading_artifacts(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    def forbidden_load() -> Any:
        raise AssertionError("arguments must be rejected before artifact loading")

    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH), "/tmp/untrusted.json"])
    monkeypatch.setattr(verifier, "SNAPSHOT_API", None)
    monkeypatch.setattr(verifier, "_load_snapshot_api", forbidden_load)

    assert verifier.main() == 2
    assert capsys.readouterr().out.splitlines() == [
        "RESULT=BLOCKED_MIGRATION_DIVERGENCE_V4:USAGE",
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "NEXT_STAGE_AUTHORIZED=false",
    ]


def test_proposal_is_exact_closed_and_all_permissions_are_false() -> None:
    proposal = _load_json(PROPOSAL_PATH)

    verifier.validate_proposal(proposal)
    assert set(proposal) == verifier.EXPECTED_TOP_LEVEL_KEYS
    assert proposal == verifier.EXPECTED_PROPOSAL
    assert proposal["current_permissions"] == {
        name: False for name in verifier.EXPECTED_PERMISSIONS
    }
    assert proposal["operational_authorization"] is False
    assert proposal["next_stage_authorized"] is False
    assert proposal["next_gate"]["authorized"] is False
    assert proposal["verification_result"]["valid_exit_code"] == 8


def test_v4_extends_v3_without_superseding_or_reinterpreting_state() -> None:
    proposal = _load_json(PROPOSAL_PATH)
    extension = proposal["extension_contract"]
    preserved = proposal["preserved_v3_state"]
    v3 = _load_json(
        REPO_ROOT
        / verifier.EXPECTED_HISTORICAL_CONTRACTS["v3_proposal"]["path"]
    )

    assert extension["extends_proposal_id"] == v3["proposal_id"]
    assert extension["extends_sha256"] == _sha256(
        REPO_ROOT
        / verifier.EXPECTED_HISTORICAL_CONTRACTS["v3_proposal"]["path"]
    )
    assert extension["supersedes_prior_proposals"] is False
    assert extension["reinterprets_environment_or_cutover_state"] is False
    assert extension[
        "prior_environment_and_cutover_records_remain_governed_by_v1_v2_v3"
    ] is True
    assert preserved["environment_tracks"] == v3["environment_tracks"]
    assert preserved["review"] == v3["review"]
    assert preserved["v4_environment_evidence_added"] is False
    assert preserved["v4_cutover_decision_made"] is False


def test_dev_and_prod_blockers_are_preserved_exactly() -> None:
    tracks = _load_json(PROPOSAL_PATH)["preserved_v3_state"][
        "environment_tracks"
    ]

    assert tracks["DEV"]["legacy_evidence_classification"] == (
        "BLOCKED_LEDGER_DIVERGENCE"
    )
    assert tracks["PROD"]["legacy_evidence_classification"] == (
        "BLOCKED_EVIDENCE_INSUFFICIENT"
    )
    assert tracks["DEV"]["cutover_decision"] == "BLOCKED"
    assert tracks["PROD"]["cutover_decision"] == "BLOCKED"
    assert tracks["DEV"]["environment_attestation"] == "NOT_COMPLETE_FOR_V3"
    assert tracks["PROD"]["environment_attestation"] == "NOT_COMPLETE_FOR_V3"


def test_historical_v1_v2_v3_and_source_anchor_bytes_match_exact_pins() -> None:
    proposal = _load_json(PROPOSAL_PATH)

    for contract in proposal["historical_contracts"].values():
        assert _sha256(REPO_ROOT / contract["path"]) == contract["sha256"]
    for contract in proposal["repository_anchor"]["source_artifacts"].values():
        assert _sha256(REPO_ROOT / contract["path"]) == contract["sha256"]

    assert proposal["repository_anchor"]["repository_commit_sha"] == (
        "9b9395e29cc821d6808738a30a6afe367d4ffbea"
    )
    verifier._validate_historical_contracts()
    verifier._validate_source_artifacts()


def test_v4_package_and_schema_bytes_are_self_pinned_by_verifier() -> None:
    assert _sha256(PROPOSAL_PATH) == verifier.EXPECTED_PROPOSAL_SHA256
    assert _sha256(SCHEMA_PATH) == verifier.EXPECTED_SCHEMA_SHA256


def test_schema_is_closed_and_in_exact_semantic_parity() -> None:
    proposal = _load_json(PROPOSAL_PATH)
    schema = _load_json(SCHEMA_PATH)

    verifier._validate_schema_document(schema)
    verifier._validate_schema_instance(proposal, schema)
    assert schema["additionalProperties"] is False
    assert schema["required"] == sorted(verifier.EXPECTED_TOP_LEVEL_KEYS)
    assert set(schema["properties"]) == verifier.EXPECTED_TOP_LEVEL_KEYS
    assert all(
        node == {"const": proposal[key]}
        for key, node in schema["properties"].items()
    )


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("artifact_state",), "READY"),
        (("contract_version",), "4.1"),
        (("operational_authorization",), True),
        (("next_stage_authorized",), True),
        (("extension_contract", "supersedes_prior_proposals"), True),
        (
            ("extension_contract", "reinterprets_environment_or_cutover_state"),
            True,
        ),
        (
            ("dynamic_catalog_validation", "catalog_count_or_digest_embedded"),
            True,
        ),
        (("preserved_v3_state", "v4_environment_evidence_added"), True),
        (("preserved_v3_state", "v4_cutover_decision_made"), True),
        (
            (
                "preserved_v3_state",
                "environment_tracks",
                "DEV",
                "cutover_decision",
            ),
            "APPROVED",
        ),
        (
            (
                "preserved_v3_state",
                "environment_tracks",
                "PROD",
                "legacy_evidence_classification",
            ),
            "READY",
        ),
        (("preserved_v3_state", "review", "human_cutover_decision"), "APPROVED"),
        (("next_gate", "authorized"), True),
        (("repository_anchor", "repository_commit_sha"), "0" * 40),
        (
            (
                "repository_anchor",
                "source_artifacts",
                "migration_authoring",
                "sha256",
            ),
            "0" * 64,
        ),
    ],
)
def test_critical_mutations_fail_closed(
    path: tuple[str, ...], replacement: Any
) -> None:
    proposal = copy.deepcopy(_load_json(PROPOSAL_PATH))
    _set_path(proposal, path, replacement)

    with pytest.raises(verifier.VerificationError):
        verifier.validate_proposal(proposal)
    with pytest.raises(verifier.VerificationError):
        verifier._validate_schema_instance(proposal, _load_json(SCHEMA_PATH))


@pytest.mark.parametrize("permission", sorted(verifier.EXPECTED_PERMISSIONS))
def test_every_permission_is_independently_fail_closed(permission: str) -> None:
    proposal = copy.deepcopy(_load_json(PROPOSAL_PATH))
    proposal["current_permissions"][permission] = True

    with pytest.raises(verifier.VerificationError):
        verifier.validate_proposal(proposal)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"a":1,"a":2}',
        b'{"a":1.0}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b"\xef\xbb\xbf{}",
        b"[]",
    ],
)
def test_duplicate_float_nonfinite_bom_or_non_object_json_is_rejected(
    payload: bytes,
) -> None:
    with pytest.raises(verifier.VerificationError):
        verifier._decode_json(payload)


def test_integer_boolean_type_confusion_is_rejected() -> None:
    proposal = copy.deepcopy(_load_json(PROPOSAL_PATH))
    proposal["operational_authorization"] = 0

    with pytest.raises(verifier.VerificationError):
        verifier.validate_proposal(proposal)


def test_stable_reader_rejects_wrong_hash_symlink_hardlink_fifo_and_directory(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.json"
    content = b"{}\n"
    target.write_bytes(content)
    digest = sha256(content).hexdigest()

    with pytest.raises(verifier.ArtifactIoError):
        verifier._read_stable_bytes(
            target,
            expected_sha256="0" * 64,
            max_bytes=1024,
        )

    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(target)
    with pytest.raises(verifier.ArtifactIoError):
        verifier._read_stable_bytes(
            symlink, expected_sha256=digest, max_bytes=1024
        )

    hardlink = tmp_path / "hardlink.json"
    os.link(target, hardlink)
    with pytest.raises(verifier.ArtifactIoError):
        verifier._read_stable_bytes(
            hardlink, expected_sha256=digest, max_bytes=1024
        )

    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(verifier.ArtifactIoError):
        verifier._read_stable_bytes(
            fifo, expected_sha256=digest, max_bytes=1024
        )

    with pytest.raises(verifier.ArtifactIoError):
        verifier._read_stable_bytes(
            tmp_path, expected_sha256=digest, max_bytes=1024
        )


def test_stable_reader_uses_authenticated_descriptor_not_path_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "artifact.json"
    content = b'{"blocked":true}\n'
    target.write_bytes(content)

    def forbidden_path_read(_path: Path) -> bytes:
        raise AssertionError("authenticated reader must not reopen the path")

    monkeypatch.setattr(Path, "read_bytes", forbidden_path_read)

    assert verifier._read_stable_bytes(
        target,
        expected_sha256=sha256(content).hexdigest(),
        max_bytes=1024,
    ) == content


def test_catalog_validation_is_dynamic_and_reads_exactly_two_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dynamic = _fake_snapshot(
        names=("a.sql", "b.sql", "c.sql", "d.sql"),
        catalog_digest="d" * 64,
    )
    calls: list[int] = []

    def snapshot() -> SimpleNamespace:
        calls.append(1)
        return dynamic

    monkeypatch.setattr(
        verifier,
        "SNAPSHOT_API",
        SimpleNamespace(validated_local_catalog_snapshot=snapshot),
    )

    signature = verifier._validate_dynamic_catalog()
    assert len(calls) == 2
    assert len(signature[4]) == 4
    assert signature[2] == "d" * 64


def test_full_verification_accepts_a_well_formed_unpinned_catalog_size_and_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dynamic = _fake_snapshot(
        names=("only-current-entry.sql",),
        catalog_digest="e" * 64,
    )
    calls: list[int] = []

    def snapshot() -> SimpleNamespace:
        calls.append(1)
        return dynamic

    monkeypatch.setattr(
        verifier,
        "SNAPSHOT_API",
        SimpleNamespace(validated_local_catalog_snapshot=snapshot),
    )

    verifier.verify_versioned_package()
    assert len(calls) == 2


def test_catalog_change_between_snapshots_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = iter(
        [
            _fake_snapshot(catalog_digest="1" * 64),
            _fake_snapshot(catalog_digest="2" * 64),
        ]
    )
    monkeypatch.setattr(
        verifier,
        "SNAPSHOT_API",
        SimpleNamespace(validated_local_catalog_snapshot=lambda: next(snapshots)),
    )

    with pytest.raises(verifier.CatalogDriftError):
        verifier.verify_versioned_package()


@pytest.mark.parametrize(
    "snapshot",
    [
        _fake_snapshot(names=()),
        _fake_snapshot(operational_authorization=True),
        _fake_snapshot(next_stage_authorized=True),
        _fake_snapshot(position_offset=1),
    ],
)
def test_malformed_or_authorizing_dynamic_snapshot_fails_closed(
    monkeypatch: pytest.MonkeyPatch, snapshot: SimpleNamespace
) -> None:
    monkeypatch.setattr(
        verifier,
        "SNAPSHOT_API",
        SimpleNamespace(validated_local_catalog_snapshot=lambda: snapshot),
    )

    with pytest.raises(verifier.CatalogDriftError):
        verifier._catalog_snapshot_signature()


def test_catalog_count_and_digest_are_not_embedded_as_v4_evidence() -> None:
    proposal_text = PROPOSAL_PATH.read_text(encoding="utf-8")
    schema_text = SCHEMA_PATH.read_text(encoding="utf-8")
    verifier_text = SCRIPT_PATH.read_text(encoding="utf-8")
    current_catalog_digest = (
        "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f"
    )

    assert current_catalog_digest not in proposal_text
    assert current_catalog_digest not in schema_text
    assert current_catalog_digest not in verifier_text
    assert "migration_count" not in proposal_text
    assert _load_json(PROPOSAL_PATH)["dynamic_catalog_validation"][
        "catalog_count_or_digest_embedded"
    ] is False


def test_schema_mutation_or_extra_property_is_rejected() -> None:
    proposal = _load_json(PROPOSAL_PATH)
    schema = copy.deepcopy(_load_json(SCHEMA_PATH))
    schema["properties"]["operational_authorization"] = {"const": True}

    with pytest.raises(verifier.VerificationError):
        verifier._validate_schema_document(schema)

    extra = copy.deepcopy(proposal)
    extra["unexpected"] = False
    with pytest.raises(verifier.VerificationError):
        verifier.validate_proposal(extra)


def test_verifier_source_has_no_environment_network_database_or_subprocess_api() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    attributes: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Attribute):
            attributes.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)

    assert imported_roots.isdisjoint(
        {
            "asyncpg",
            "httpx",
            "psycopg",
            "psycopg2",
            "requests",
            "socket",
            "sqlalchemy",
            "subprocess",
            "urllib",
        }
    )
    assert {"environ", "getenv", "putenv", "socket", "connect"}.isdisjoint(
        attributes
    )
    assert {"open", "urlopen"}.isdisjoint(names)
    assert {
        "chmod",
        "mkdir",
        "rename",
        "replace",
        "rmdir",
        "touch",
        "unlink",
        "write_bytes",
        "write_text",
    }.isdisjoint(attributes)


def test_runtime_verification_cannot_write_open_network_or_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("forbidden side effect")

    for method in (
        "chmod",
        "mkdir",
        "rename",
        "replace",
        "rmdir",
        "touch",
        "unlink",
        "write_bytes",
        "write_text",
    ):
        monkeypatch.setattr(Path, method, forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "check_call", forbidden)
    monkeypatch.setattr(subprocess, "check_output", forbidden)

    verifier.verify_versioned_package()


def test_dedicated_workflow_requires_the_exact_blocked_v4_receipt() -> None:
    workflow = yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    assert set(workflow) == {
        "concurrency",
        "jobs",
        "name",
        "on",
        "permissions",
    }
    assert workflow["on"] == {
        "pull_request": "",
        "push": {"branches": ["main"]},
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"migration-divergence-v4"}
    job = workflow["jobs"]["migration-divergence-v4"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == "5"
    checkout, setup, verification = job["steps"]
    assert checkout == {
        "uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        "with": {"persist-credentials": "false"},
    }
    assert setup == {
        "uses": "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
        "with": {"python-version": "3.13.14"},
    }
    command = verification["run"]
    assert verification["working-directory"] == "backend"
    assert "python -I -S -P -B" in command
    assert "python -I -S -" in command
    assert "test \"$result\" -eq 8" in command
    assert "SOURCE_EXTENSION_VERIFIED" in command
    assert "V3_ENVIRONMENT_AND_CUTOVER_STATE=PRESERVED_UNCHANGED" in command
    assert "OPERATIONAL_AUTHORIZATION=BLOCKED" in command
    assert "NEXT_STAGE_AUTHORIZED=false" in command
    normalized = WORKFLOW_PATH.read_text(encoding="utf-8").casefold()
    for forbidden in (
        "pull_request_target",
        "secrets.",
        "database_url",
        "apply_migrations.py",
        "git push",
        "curl ",
        "wget ",
    ):
        assert forbidden not in normalized
