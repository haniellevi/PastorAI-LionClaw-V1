from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import re
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "verify_migration_history_schema_expectation_manifest.py"
)
MANIFEST_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-schema-expectation-manifest-v1.json"
)
RUNNER_PATH = REPO_ROOT / "backend" / "scripts" / "apply_migrations.py"
RECONCILIATION_VERIFIER_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "verify_migration_history_reconciliation.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_history_schema_expectation_verifier", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_source_manifest_verifies_offline_and_remains_blocked(capsys: Any) -> None:
    module = _load_module()

    assert module.main(
        ["--manifest", "migration-history-schema-expectation-manifest-v1.json"]
    ) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.splitlines() == [
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "SCHEMA_EXPECTATION_MANIFEST_VERIFIED_SOURCE_ONLY",
        "ENVIRONMENT_ATTESTATION_COMPLETE=false",
    ]


def test_manifest_is_source_only_and_not_an_environment_claim() -> None:
    manifest = _load_manifest()

    assert manifest["artifact_state"] == (
        "SOURCE_EXPECTATION_VERIFIED_ENVIRONMENT_UNATTESTED"
    )
    assert manifest["operational_authorization"] is False
    assert manifest["source_expectation"]["manifest_scope"] == (
        "SOURCE_LEVEL_EXPECTATION_ONLY"
    )
    assert manifest["source_expectation"]["final_schema_claim"] is False
    assert manifest["source_expectation"]["environment_attestation_complete"] is False
    assert manifest["repository"]["declared_base_sha_role"] == (
        "DECLARED_CONTEXT_ONLY_CATALOG_DIGEST_IS_AUTHORITATIVE_BYTE_BINDING"
    )
    assert manifest["attestation_contract"]["current_environment_version_attested"] is False
    assert manifest["attestation_contract"]["offline_derivation_target"] == {
        "postgresql_major": 17,
        "reference_path": ".github/workflows/rls-integration.yml",
        "reference_sha256": (
            "4fac0b1ed923f3dc2298b45ff63bfe57ec849654ae6ab446facbca4b6fef891b"
        ),
        "selection_basis": (
            "VERSIONED_DISPOSABLE_CI_IMAGE_NOT_ENVIRONMENT_OBSERVATION"
        ),
    }
    assert manifest["attestation_contract"]["state"] == (
        "PENDING_SEPARATE_READ_ONLY_ENVIRONMENT_ATTESTATION"
    )
    assert manifest["review"] == {
        "conclusion": "PASS_FOR_SOURCE_MANIFEST_ONLY",
        "independent_review_complete": False,
        "review_type": "TECHNICAL_SELF_REVIEW_NOT_INDEPENDENT",
        "reviewer_reference": "SYSTEM-TECHNICAL-REVIEW",
        "substantive_findings": [
            "FAIL_CLOSED_ARCHITECTURE_IS_COHERENT",
            "CONTROLLED_EPOCH_REMAINS_UNAPPROVED",
            "FINAL_SCHEMA_CANNOT_BE_PROVEN_BY_STATIC_SCAN",
            "INDEPENDENT_REVIEW_REMAINS_REQUIRED",
        ],
    }
    assert manifest["decisions"]["controlled_epoch_cutover_approved"] is False
    assert manifest["next_gates"][:3] == [
        "INDEPENDENT_SECURITY_AND_DATABASE_ARCHITECTURE_REVIEW",
        "SEPARATE_OFFLINE_CANONICAL_SCHEMA_DERIVATION",
        "SEPARATE_READ_ONLY_ENVIRONMENT_ATTESTATION",
    ]


def test_manifest_binds_the_exact_75_file_catalog_and_critical_anchors() -> None:
    module = _load_module()
    manifest = _load_manifest()
    catalog, capabilities = module._scan_catalog()

    assert len(catalog) == 75
    assert [entry["name"] for entry in catalog] == sorted(
        entry["name"] for entry in catalog
    )
    assert module._framed_sha256(
        module.CATALOG_DOMAIN,
        {"algorithm": module.CATALOG_ALGORITHM, "entries": catalog},
    ) == manifest["repository"]["catalog_digest_sha256"]
    assert capabilities == manifest["source_expectation"][
        "capability_file_counts"
    ]

    catalog_by_name = {entry["name"]: entry for entry in catalog}
    for anchor in manifest["repository"]["critical_migration_anchors"]:
        assert catalog_by_name[anchor["name"]]["sha256"] == anchor["sha256"]


@pytest.mark.parametrize(
    "mutation,expected_error",
    [
        (
            lambda manifest: manifest["safety_contract"].__setitem__(
                "database_access_allowed", True
            ),
            "ManifestError",
        ),
        (
            lambda manifest: manifest["source_expectation"].__setitem__(
                "final_schema_claim", True
            ),
            "ManifestError",
        ),
        (
            lambda manifest: manifest["review"].__setitem__(
                "independent_review_complete", True
            ),
            "ManifestError",
        ),
        (
            lambda manifest: manifest["decisions"].__setitem__(
                "controlled_epoch_cutover_approved", True
            ),
            "ManifestError",
        ),
        (
            lambda manifest: manifest["repository"].__setitem__(
                "catalog_digest_sha256", "0" * 64
            ),
            "CatalogDriftError",
        ),
        (
            lambda manifest: manifest["attestation_contract"][
                "required_domains"
            ].pop(),
            "ManifestError",
        ),
        (
            lambda manifest: manifest["next_gates"].remove(
                "INDEPENDENT_SECURITY_AND_DATABASE_ARCHITECTURE_REVIEW"
            ),
            "ManifestError",
        ),
    ],
)
def test_manifest_mutations_fail_closed(mutation: Any, expected_error: str) -> None:
    module = _load_module()
    manifest = copy.deepcopy(_load_manifest())
    catalog, capabilities = module._scan_catalog()
    mutation(manifest)

    error_type = getattr(module, expected_error)
    with pytest.raises(error_type):
        module._validate_manifest(manifest, catalog, capabilities)


def test_manifest_requires_full_schema_security_and_data_domains() -> None:
    manifest = _load_manifest()
    domains = manifest["attestation_contract"]["required_domains"]
    invariants = {
        item["id"]: item["state"]
        for item in manifest["attestation_contract"]["data_invariants"]
    }

    assert domains == [
        "EXTENSIONS",
        "ENUM_TYPES_AND_VALUES",
        "ROLES_AND_MEMBERSHIPS",
        "SCHEMAS_AND_OWNERS",
        "RELATIONS_AND_PERSISTENCE",
        "COLUMNS_TYPES_DEFAULTS_IDENTITY_GENERATED",
        "CONSTRAINTS_AND_VALIDATION_STATE",
        "INDEXES_DEFINITIONS_AND_VALIDITY",
        "FUNCTIONS_SIGNATURE_LANGUAGE_VOLATILITY_SECURITY_SEARCH_PATH",
        "TRIGGERS_AND_REWRITE_RULES",
        "RLS_ENABLE_FORCE_FLAGS",
        "POLICIES_COMMAND_ROLES_USING_WITH_CHECK",
        "TABLE_COLUMN_FUNCTION_SCHEMA_PRIVILEGES",
        "DEFAULT_PRIVILEGES",
        "DATA_INVARIANTS",
    ]
    assert set(invariants) == {
        "TENANT_FOREIGN_KEY_CONSISTENCY",
        "TENANT_UNIQUENESS_GUARDS",
        "APPEND_ONLY_AUDIT_INTEGRITY",
        "IDEMPOTENCY_UNIQUENESS",
        "CONSENT_LEDGER_INTEGRITY",
        "BILLING_ISOLATION_INTEGRITY",
        "RECOVERY_ARTIFACT_RETENTION",
        "GOVERNANCE_DRAFT_INTEGRITY",
    }
    assert set(invariants.values()) == {
        "PENDING_SEPARATE_READ_ONLY_ATTESTATION"
    }


def test_verifier_has_no_database_network_runner_or_environment_path() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)

    assert not ({"psycopg", "psycopg2", "sqlalchemy", "socket", "subprocess"} & imports)
    assert not ({"connect", "execute", "executemany", "system", "popen"} & calls)
    assert "os.environ" not in source
    assert "DATABASE_URL" not in source
    assert "apply_migrations" not in source
    assert "supabase_migrations" not in source


def test_manifest_cannot_change_or_unlock_existing_tooling() -> None:
    runner = RUNNER_PATH.read_text(encoding="utf-8")
    reconciliation_verifier = RECONCILIATION_VERIFIER_PATH.read_text(
        encoding="utf-8"
    )

    assert _sha256(RUNNER_PATH) == (
        "36e63cde6751cd0cb33e1511091068b0b04f10029ace06703eead82e0e836c65"
    )
    assert _sha256(RECONCILIATION_VERIFIER_PATH) == (
        "9451cbe5054d8c0d7e2754d09dea7f3a9761e8585269ca783eea943dd785dfae"
    )
    assert "schema-expectation-manifest" not in runner
    assert "schema-expectation-manifest" not in reconciliation_verifier
    assert not any(
        "schema_expectation" in path.name
        for path in (REPO_ROOT / "backend" / "migrations").glob("*.sql")
    )


def test_public_manifest_and_verifier_are_sanitized() -> None:
    public_text = MANIFEST_PATH.read_text(encoding="utf-8") + SCRIPT_PATH.read_text(
        encoding="utf-8"
    )
    lowered = public_text.casefold()

    assert "@" not in public_text
    assert "postgresql://" not in lowered
    assert "database_url" not in lowered
    assert "service_role" not in lowered
    assert not re.search(r"\beyj[a-z0-9_-]{10,}\b", lowered)
    assert "operational_authorization=blocked" in lowered


def test_cli_errors_stay_sanitized_and_blocked(capsys: Any) -> None:
    module = _load_module()

    assert module.main(["--manifest", "unexpected-private-name.json"]) == 2
    output = capsys.readouterr()
    assert output.out == "OPERATIONAL_AUTHORIZATION=BLOCKED\n"
    assert output.err == "SCHEMA_EXPECTATION_MANIFEST_BLOCKED:USAGE\n"
    assert "unexpected-private-name" not in output.err


@pytest.mark.parametrize(
    ("content", "expected_exit", "expected_reason"),
    [
        (b"\xef\xbb\xbf{}", 3, "MANIFEST_IO_INVALID"),
        (
            b'{"contract_version":"1.0","contract_version":"1.0"}',
            4,
            "MANIFEST_INVALID",
        ),
        (b'{"contract_version":1.5}', 4, "MANIFEST_INVALID"),
    ],
)
def test_invalid_manifest_bytes_fail_closed_without_echo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    content: bytes,
    expected_exit: int,
    expected_reason: str,
) -> None:
    module = _load_module()
    target = tmp_path / module.MANIFEST_BASENAME
    target.write_bytes(content)
    monkeypatch.setattr(module, "MANIFEST_DIR", tmp_path)

    assert module.main(["--manifest", module.MANIFEST_BASENAME]) == expected_exit
    output = capsys.readouterr()
    assert output.out == "OPERATIONAL_AUTHORIZATION=BLOCKED\n"
    assert output.err == f"SCHEMA_EXPECTATION_MANIFEST_BLOCKED:{expected_reason}\n"
    assert "contract_version" not in output.err


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_manifest_link_aliases_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    link_kind: str,
) -> None:
    module = _load_module()
    source = tmp_path / "source.json"
    source.write_bytes(MANIFEST_PATH.read_bytes())
    target = tmp_path / module.MANIFEST_BASENAME
    if link_kind == "symlink":
        target.symlink_to(source)
    else:
        target.hardlink_to(source)
    monkeypatch.setattr(module, "MANIFEST_DIR", tmp_path)

    assert module.main(["--manifest", module.MANIFEST_BASENAME]) == 3
    output = capsys.readouterr()
    assert output.out == "OPERATIONAL_AUTHORIZATION=BLOCKED\n"
    assert output.err == (
        "SCHEMA_EXPECTATION_MANIFEST_BLOCKED:MANIFEST_IO_INVALID\n"
    )


def test_catalog_byte_drift_blocks_before_source_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    module = _load_module()
    catalog_copy = tmp_path / "migrations"
    shutil.copytree(REPO_ROOT / "backend" / "migrations", catalog_copy)
    target = sorted(catalog_copy.glob("*.sql"))[0]
    target.write_bytes(target.read_bytes() + b"\n")
    monkeypatch.setattr(module, "MIGRATIONS_DIR", catalog_copy)

    assert module.main(["--manifest", module.MANIFEST_BASENAME]) == 5
    output = capsys.readouterr()
    assert output.out == "OPERATIONAL_AUTHORIZATION=BLOCKED\n"
    assert output.err == "SCHEMA_EXPECTATION_MANIFEST_BLOCKED:CATALOG_DRIFT\n"


@pytest.mark.parametrize("suffix", [".SQL", ".Sql", ".sQl"])
def test_noncanonical_sql_suffix_fails_closed_before_source_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    suffix: str,
) -> None:
    module = _load_module()
    catalog_copy = tmp_path / "migrations"
    shutil.copytree(REPO_ROOT / "backend" / "migrations", catalog_copy)
    (catalog_copy / f"20990101_000000_private{suffix}").write_text(
        "select 1;\n", encoding="utf-8"
    )
    monkeypatch.setattr(module, "MIGRATIONS_DIR", catalog_copy)

    assert module.main(["--manifest", module.MANIFEST_BASENAME]) == 5
    output = capsys.readouterr()
    assert output.out == "OPERATIONAL_AUTHORIZATION=BLOCKED\n"
    assert output.err == "SCHEMA_EXPECTATION_MANIFEST_BLOCKED:CATALOG_DRIFT\n"
    assert "private" not in output.err
