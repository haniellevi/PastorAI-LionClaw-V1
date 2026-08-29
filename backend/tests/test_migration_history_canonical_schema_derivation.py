from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DERIVE_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "derive_migration_history_canonical_schema.py"
)
VERIFY_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "verify_migration_history_canonical_schema.py"
)
SCAFFOLD_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-canonical-schema-scaffold-v1.sql"
)
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "canonical-schema-derivation.yml"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def derive_module() -> ModuleType:
    return _load_module("canonical_schema_derivation", DERIVE_PATH)


@pytest.fixture
def verify_module() -> ModuleType:
    return _load_module("canonical_schema_verifier", VERIFY_PATH)


def _empty_artifact(module: ModuleType) -> dict[str, Any]:
    domains = []
    for name in module.REQUIRED_DOMAINS:
        entries = []
        if name == "DATA_INVARIANTS":
            entries = [
                {
                    "id": invariant,
                    "state": "DEFINED_FOR_SEPARATE_READ_ONLY_ENVIRONMENT_ATTESTATION",
                }
                for invariant in module.DATA_INVARIANTS
            ]
            entries.sort(key=module._canonical_bytes)
        domains.append(
            {
                "entry_count": len(entries),
                "entries": entries,
                "name": name,
                "sha256": module._domain_sha256(name, entries),
            }
        )
    return module._build_artifact(domains)


def _private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def test_source_catalog_is_exactly_bound_to_75_raw_files(
    derive_module: ModuleType,
) -> None:
    catalog = derive_module._load_source_catalog()

    assert len(catalog) == 75
    assert all(type(item) is bytes and item for item in catalog)
    assert derive_module.CATALOG_DIGEST_SHA256 == (
        "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f"
    )


def test_scaffold_has_only_required_roles_and_no_platform_or_ledger(
    derive_module: ModuleType,
) -> None:
    content = derive_module._load_scaffold().decode("utf-8").casefold()

    assert "create role anon" in content
    assert "create role authenticated" in content
    assert "create role service_role" in content
    assert "bypassrls" in content
    assert "create role agent_runtime" not in content
    assert "realtime" in content  # only the explicit absence comment
    assert "create schema realtime" not in content
    assert "create table" not in content
    assert "schema_migrations" not in content
    assert "supabase_migrations" not in content


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        " postgresql://postgres:postgres@127.0.0.1:55432/canonical_schema_disposable_a",
        "postgresql://postgres:postgres@example.com:55432/canonical_schema_disposable_a",
        "postgresql://postgres:postgres@127.0.0.1:55432/postgres",
        "postgresql://postgres:postgres@127.0.0.1:55432/canonical_schema_disposable_a?sslmode=disable",
        "postgresql://postgres@127.0.0.1:55432/canonical_schema_disposable_a",
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:55432/canonical_schema_disposable_a",
    ],
)
def test_target_guard_rejects_any_non_exact_disposable_dsn(
    derive_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv(derive_module.DATABASE_URL_ENV, raising=False)
    else:
        monkeypatch.setenv(derive_module.DATABASE_URL_ENV, value)

    with pytest.raises(derive_module.TargetGuardError):
        derive_module._read_disposable_url()


def test_target_guard_accepts_only_dedicated_env_and_loopback(
    derive_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = (
        "postgresql://postgres:postgres@127.0.0.1:55432/"
        "canonical_schema_disposable_a"
    )
    monkeypatch.setenv(derive_module.DATABASE_URL_ENV, value)

    assert derive_module._read_disposable_url() == (
        value,
        "canonical_schema_disposable_a",
    )


def test_output_requires_private_directory_and_is_atomic(
    derive_module: ModuleType,
    tmp_path: Path,
) -> None:
    artifact = _empty_artifact(derive_module)
    public_dir = tmp_path / "public"
    public_dir.mkdir(mode=0o755)
    public_dir.chmod(0o755)
    with pytest.raises(derive_module.OutputError):
        derive_module._write_atomic(public_dir, artifact)

    private_dir = _private_dir(tmp_path / "private")
    target = derive_module._write_atomic(private_dir, artifact)

    assert target.name == derive_module.OUTPUT_BASENAME
    assert target.stat().st_mode & 0o777 == 0o600
    assert not any(path.name.endswith(".partial") for path in private_dir.iterdir())
    assert json.loads(target.read_text(encoding="utf-8")) == artifact
    with pytest.raises(derive_module.OutputError):
        derive_module._write_atomic(private_dir, artifact)


def test_output_is_prevalidated_before_reading_dsn_or_connecting(
    derive_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    public_dir = tmp_path / "public"
    public_dir.mkdir(mode=0o755)
    public_dir.chmod(0o755)
    dsn_read = False

    def unexpected_dsn_read() -> tuple[str, str]:
        nonlocal dsn_read
        dsn_read = True
        raise AssertionError("DSN must not be read for an invalid output layout")

    monkeypatch.setattr(derive_module, "_read_disposable_url", unexpected_dsn_read)

    with pytest.raises(derive_module.OutputError):
        derive_module.derive(public_dir)

    assert dsn_read is False


def test_sequence_acl_uses_postgresql_sequence_defaults() -> None:
    source = DERIVE_PATH.read_text(encoding="utf-8")

    assert "case when c.relkind = 'S' then 's'::\"char\"" in source
    assert "c.relkind in ('r', 'p', 'v', 'm', 'S', 'f')" in source


def test_two_equal_artifacts_verify_without_environment_claim(
    derive_module: ModuleType,
    verify_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = _empty_artifact(derive_module)
    first = derive_module._write_atomic(_private_dir(tmp_path / "a"), artifact)
    second = derive_module._write_atomic(_private_dir(tmp_path / "b"), artifact)
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            verify_module._expected_summary(artifact, first.read_bytes()),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(verify_module, "FINGERPRINT_SUMMARY_PATH", summary_path)

    verified = verify_module.verify(first, second)

    assert verified["operational_authorization"] is False
    assert verified["environment_attestation_complete"] is False
    assert verified["data_api"]["exposure_inferred"] is False
    assert verified["derivation_target"]["realtime_scaffolded"] is False
    assert len(verified["domains"]) == 15


def test_replay_mismatch_fails_closed(
    derive_module: ModuleType,
    verify_module: ModuleType,
    tmp_path: Path,
) -> None:
    first_artifact = _empty_artifact(derive_module)
    second_artifact = copy.deepcopy(first_artifact)
    second_artifact["domains"][0]["entries"] = [
        {"name": "pgcrypto", "observed_version": "different", "schema": "public"}
    ]
    second_artifact["domains"][0]["entry_count"] = 1
    second_artifact["domains"][0]["sha256"] = derive_module._domain_sha256(
        "EXTENSIONS", second_artifact["domains"][0]["entries"]
    )
    second_artifact["canonical_schema_fingerprint_sha256"] = (
        derive_module._artifact_sha256(second_artifact["domains"])
    )
    first = derive_module._write_atomic(
        _private_dir(tmp_path / "a"), first_artifact
    )
    second = derive_module._write_atomic(
        _private_dir(tmp_path / "b"), second_artifact
    )

    with pytest.raises(verify_module.ReplayMismatchError):
        verify_module.verify(first, second)


def test_artifact_rejects_operational_or_environment_claims(
    derive_module: ModuleType,
    verify_module: ModuleType,
) -> None:
    for key in ("operational_authorization", "environment_attestation_complete"):
        artifact = _empty_artifact(derive_module)
        artifact[key] = True
        with pytest.raises(verify_module.ArtifactContractError):
            verify_module._validate_artifact(artifact)


def test_cli_failure_is_static_sanitized_and_writes_nothing(
    derive_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(derive_module.DATABASE_URL_ENV, raising=False)
    output = _private_dir(tmp_path / "output")

    assert derive_module.main(
        [
            "--confirmation",
            derive_module.CONFIRMATION,
            "--output-dir",
            str(output),
        ]
    ) == 5
    captured = capsys.readouterr()
    assert captured.out == "OPERATIONAL_AUTHORIZATION=BLOCKED\n"
    assert captured.err == (
        "CANONICAL_SCHEMA_DERIVATION_BLOCKED:DISPOSABLE_TARGET_REQUIRED\n"
    )
    assert list(output.iterdir()) == []


def test_tool_is_separate_from_runner_and_has_no_container_pull_path() -> None:
    source = DERIVE_PATH.read_text(encoding="utf-8")
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

    assert "subprocess" not in imports
    assert not ({"system", "popen", "run", "check_call", "check_output"} & calls)
    assert "docker pull" not in source.casefold()
    assert "apply_migrations" in source  # only the explicit separation contract
    assert "from scripts import apply_migrations" not in source
    assert "public.schema_migrations" in source  # absence guard only
    assert "create table public.schema_migrations" not in source.casefold()
    assert "create schema supabase_migrations" not in source.casefold()
    assert "os.environ.get(DATABASE_URL_ENV)" in source
    assert "os.environ.get(\"DATABASE_URL\")" not in source
    assert "os.environ[\"DATABASE_URL\"]" not in source


def test_public_sources_do_not_embed_connection_material() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (DERIVE_PATH, SCAFFOLD_PATH)
    ).casefold()

    assert "supabase.co" not in text
    assert "postgresql://" not in text
    assert "postgres://" not in text
    assert "service_role_key" not in text
    assert "eyj" not in text


def test_dedicated_workflow_pins_two_fresh_pg17_replays() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    image = (
        "postgres:17.6-trixie@"
        "sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929"
    )

    assert workflow.count(image) == 2
    assert "canonical_schema_disposable_a" in workflow
    assert "canonical_schema_disposable_b" in workflow
    assert "127.0.0.1:5432" in workflow
    assert "127.0.0.1:5433" in workflow
    assert workflow.count("test_migration_history_canonical_schema_pg17.py") == 2
    assert "verify_migration_history_canonical_schema.py" in workflow
    assert "migration-history-canonical-schema-fingerprint-v1.json" not in workflow
    assert "apply_migrations.py" not in workflow
    assert "supabase" not in workflow.casefold()
