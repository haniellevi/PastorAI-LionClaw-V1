"""Adversarial offline proofs for the migration environment executor v2."""

from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from scripts import execute_migration_history_environment_attestation_v2 as executor
from scripts import preflight_migration_history_environment_identity as preflight_v1


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "execute_migration_history_environment_attestation_v2.py"
)
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-environment-attestation-executor-authorization-v2.schema.json"
)
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "environment-attestation-pg17.yml"
REQUIREMENTS_LOCK_PATH = REPO_ROOT / "backend" / "requirements.lock"
SOURCE_GIT_SHA = "a" * 40
PROJECT_REF = "abcdefghijklmnopqrst"
DATABASE_NAME = "postgres"
SYSTEM_IDENTIFIER = "1234567890123456789"
TLS_CA = b"test-only-ca-certificate"
KEY = b"k" * 32
NONCE = b"n" * 32
NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)


def _canonical_bytes(value: object) -> bytes:
    return executor._canonical_json_bytes(value) + b"\n"


def _authorization_values(
    *,
    environment: str = "DEV",
    executor_sha256: str | None = None,
    tls_ca: bytes = TLS_CA,
    nonce: bytes = NONCE,
    overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    values: dict[str, object] = {
        "authorization_contract": executor.AUTHORIZATION_CONTRACT,
        "gate": executor.GATES[environment],
        "environment": environment,
        "confirmation": executor.CONFIRMATIONS[environment],
        "owner": "OWNER-01_RANIEL",
        "executor": "CI-OFFLINE",
        "source_git_sha": SOURCE_GIT_SHA,
        "executor_sha256": executor_sha256 or "e" * 64,
        "trusted_snapshot_script_sha256": executor.EXPECTED_FILE_SHA256[
            str(executor.TRUSTED_SNAPSHOT_RELATIVE_PATH)
        ],
        "preflight_runner_sha256": executor.EXPECTED_FILE_SHA256[
            str(executor.PREFLIGHT_RUNNER_RELATIVE_PATH)
        ],
        "materializer_sha256": executor.EXPECTED_FILE_SHA256[
            str(executor.MATERIALIZER_RELATIVE_PATH)
        ],
        "verifier_sha256": executor.EXPECTED_FILE_SHA256[
            str(executor.VERIFIER_RELATIVE_PATH)
        ],
        "canonical_derivation_sha256": executor.EXPECTED_FILE_SHA256[
            str(executor.CANONICAL_DERIVATION_RELATIVE_PATH)
        ],
        "source_manifest_verifier_sha256": executor.EXPECTED_FILE_SHA256[
            str(executor.SOURCE_MANIFEST_VERIFIER_RELATIVE_PATH)
        ],
        "catalog_head_verifier_sha256": executor.EXPECTED_FILE_SHA256[
            str(executor.CATALOG_HEAD_VERIFIER_RELATIVE_PATH)
        ],
        "preflight_sql_sha256": executor.EXPECTED_FILE_SHA256[
            str(executor.PREFLIGHT_SQL_RELATIVE_PATH)
        ],
        "capture_sql_sha256": executor.EXPECTED_FILE_SHA256[
            str(executor.CAPTURE_SQL_RELATIVE_PATH)
        ],
        "profile_sha256": executor.EXPECTED_FILE_SHA256[
            str(executor.PROFILE_RELATIVE_PATH)
        ],
        "artifact_schema_sha256": executor.EXPECTED_FILE_SHA256[
            str(executor.ARTIFACT_SCHEMA_RELATIVE_PATH)
        ],
        "authorization_schema_sha256": executor.EXPECTED_FILE_SHA256[
            str(executor.AUTHORIZATION_SCHEMA_RELATIVE_PATH)
        ],
        "tls_ca_certificate_sha256": hashlib.sha256(tls_ca).hexdigest(),
        "expected_project_ref_sha256": executor._component_sha256(
            "PROJECT_REF", PROJECT_REF
        ),
        "expected_database_name_sha256": executor._component_sha256(
            "DATABASE_NAME", DATABASE_NAME
        ),
        "expected_system_identifier_sha256": executor._component_sha256(
            "SYSTEM_IDENTIFIER", SYSTEM_IDENTIFIER
        ),
        "attempt_nonce_sha256": hashlib.sha256(nonce).hexdigest(),
        "valid_from_utc": "2026-09-03T11:59:00Z",
        "expires_at_utc": "2026-09-03T12:10:00Z",
        "single_attempt": True,
        "single_use_scope": "PROCESS_INVOCATION_ONLY",
        "database_session_authorized": True,
        "identity_capture_authorized": True,
        "schema_capture_authorized": True,
        "materialization_authorized": True,
        "prod_authorized": environment == "PROD",
        "database_mutation_authorized": False,
        "migration_application_authorized": False,
        "operational_authorization": False,
        "next_stage_authorized": False,
    }
    if overrides:
        values.update(overrides)
    return values


def _authorization_bytes(**kwargs: Any) -> bytes:
    return _canonical_bytes(_authorization_values(**kwargs))


def _close_descriptor(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


@contextmanager
def _pipe(raw: bytes) -> Iterator[int]:
    read_descriptor, write_descriptor = os.pipe()
    try:
        os.write(write_descriptor, raw)
    finally:
        os.close(write_descriptor)
    try:
        yield read_descriptor
    finally:
        _close_descriptor(read_descriptor)


def _open_pipe(raw: bytes) -> int:
    read_descriptor, write_descriptor = os.pipe()
    try:
        os.write(write_descriptor, raw)
    finally:
        os.close(write_descriptor)
    return read_descriptor


def _private_file(path: Path, raw: bytes) -> int:
    path.write_bytes(raw)
    path.chmod(0o600)
    return os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))


def _clean_database_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        upper = name.upper()
        if (
            upper.startswith(("PG", "SSL", "OPENSSL"))
            or upper in executor.RELEVANT_DATABASE_ENV_NAMES
        ):
            monkeypatch.delenv(name, raising=False)


def test_contract_files_are_byte_pinned_without_changing_v1() -> None:
    assert {
        str(executor.CANONICAL_DERIVATION_RELATIVE_PATH),
        str(executor.SOURCE_MANIFEST_VERIFIER_RELATIVE_PATH),
        str(executor.CATALOG_HEAD_VERIFIER_RELATIVE_PATH),
    }.issubset(executor.EXPECTED_FILE_SHA256)
    digests = executor._validate_contract_files(REPO_ROOT)
    assert digests[executor.SCRIPT_BASENAME] == hashlib.sha256(
        RUNNER_PATH.read_bytes()
    ).hexdigest()
    for relative, expected in executor.EXPECTED_FILE_SHA256.items():
        assert hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest() == expected
        assert digests[relative] == expected


@pytest.mark.parametrize(
    "relative",
    [
        executor.CANONICAL_DERIVATION_RELATIVE_PATH,
        executor.SOURCE_MANIFEST_VERIFIER_RELATIVE_PATH,
        executor.CATALOG_HEAD_VERIFIER_RELATIVE_PATH,
    ],
)
def test_contract_validation_rejects_transitive_module_drift(
    relative: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = executor._sha256_file

    def drifted(path: Path) -> str:
        if path == REPO_ROOT / relative:
            return "0" * 64
        return original(path)

    monkeypatch.setattr(executor, "_sha256_file", drifted)
    with pytest.raises(executor.ContractError):
        executor._validate_contract_files(REPO_ROOT)


def test_authorization_schema_is_closed_and_keeps_every_effect_blocked() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="ascii"))
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == executor.AUTHORIZATION_KEYS
    properties = schema["properties"]
    for field in (
        "database_mutation_authorized",
        "migration_application_authorized",
        "operational_authorization",
        "next_stage_authorized",
    ):
        assert properties[field] == {"const": False}
    assert properties["environment"] == {"enum": ["DEV", "PROD"]}
    assert set(properties["gate"]["enum"]) == set(executor.GATES.values())
    assert set(properties["confirmation"]["enum"]) == set(
        executor.CONFIRMATIONS.values()
    )


def test_runtime_contract_matches_the_pinned_ci_and_dependency_lock() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    lockfile = REQUIREMENTS_LOCK_PATH.read_text(encoding="utf-8")
    assert executor.EXPECTED_PYTHON_VERSION == (3, 13, 14)
    assert workflow.count('python-version: "3.13.14"') == 1
    assert executor.EXPECTED_PSYCOPG2_VERSION == "2.9.12"
    assert "\npsycopg2-binary==2.9.12 \\" in lockfile
    assert executor.AUTHORIZATION_TRUST_REQUIREMENT.endswith("_REQUIRED")
    assert executor.RUNTIME_TRUST_REQUIREMENT.endswith("_REQUIRED")


def test_public_cli_is_fd_only_and_internal_child_is_not_public() -> None:
    parser = executor.build_parser()
    commands = parser._subparsers._group_actions[0].choices
    assert set(commands) == {"describe", "execute"}
    execute = commands["execute"]
    options = {
        option
        for action in execute._actions
        for option in action.option_strings
    }
    assert options == {
        "--source-git-sha",
        "--environment",
        "--database-url-fd",
        "--tls-ca-cert-fd",
        "--authorization-record-fd",
        "--hmac-key-fd",
        "--nonce-fd",
        "--output-dir",
        "--confirmation",
    }
    assert "--database-url" not in options
    assert "--password" not in options
    assert executor.INTERNAL_CHILD_COMMAND not in commands
    assert executor.INTERNAL_CHILD_COMMAND in (
        executor.build_parser(internal=True)._subparsers._group_actions[0].choices
    )


def test_cli_refuses_a_nonisolated_python_runtime() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            os.fspath(RUNNER_PATH),
            "describe",
            "--source-git-sha",
            SOURCE_GIT_SHA,
        ],
        check=False,
        close_fds=True,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == executor.ContractError.exit_code
    assert completed.stderr == ""
    assert "EXECUTION_PHASE=RUNTIME_TRUST" in completed.stdout
    assert f"RESULT={executor.ContractError.reason}" in completed.stdout


@pytest.mark.parametrize(
    ("preloaded_name", "expected"),
    [
        ("", None),
        ("scripts", "BLOCKED:RUNTIME_IMPORTS\n"),
        ("scripts.attacker_controlled", "BLOCKED:RUNTIME_IMPORTS\n"),
        ("psycopg2", "BLOCKED:RUNTIME_IMPORTS\n"),
    ],
)
def test_isolated_child_loader_owns_or_rejects_the_scripts_namespace(
    preloaded_name: str,
    expected: str | None,
) -> None:
    probe = """
import importlib.util
from pathlib import Path
import sys
import types

runner = Path(sys.argv[1])
repository = Path(sys.argv[2])
preloaded_name = sys.argv[3]
module_name = "_pastorai_executor_v2_import_probe"
specification = importlib.util.spec_from_file_location(module_name, runner)
if specification is None or specification.loader is None:
    raise SystemExit(91)
module = importlib.util.module_from_spec(specification)
sys.modules[module_name] = module
specification.loader.exec_module(module)
if preloaded_name:
    sys.modules[preloaded_name] = types.ModuleType(preloaded_name)
try:
    module._load_child_modules(repository)
except module.ContractError as exc:
    print(f"BLOCKED:{exc.phase}")
else:
    print("LOADED_PINNED_MODULE_GRAPH")
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            probe,
            os.fspath(RUNNER_PATH),
            os.fspath(REPO_ROOT),
            preloaded_name,
        ],
        check=False,
        close_fds=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stderr == ""
    if expected is None:
        import psycopg2
        from psycopg2 import _psycopg

        runtime_root = Path(sys.prefix).resolve(strict=True)
        runtime_files = (
            Path(psycopg2.__file__).resolve(strict=True),
            Path(_psycopg.__file__).resolve(strict=True),
        )
        runtime_is_locally_trusted = all(
            path.is_relative_to(runtime_root)
            and not path.stat().st_mode & 0o022
            for path in runtime_files
        )
        expected = (
            "LOADED_PINNED_MODULE_GRAPH\n"
            if runtime_is_locally_trusted
            else "BLOCKED:RUNTIME_IMPORTS\n"
        )
    assert completed.stdout == expected


def test_runner_has_no_migration_application_or_protected_file_access() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert not any("capture_migration_history_evidence" in item for item in imported)
    assert "apply_migration" not in source.casefold()
    assert "migrate_clerk_production" not in source
    assert "target_users" not in source
    string_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert ".env" not in string_literals
    assert "sslmode=\"verify-full\"" in source
    assert "trusted_repository_snapshot" in source
    assert "close_fds=True" in source


def test_public_argv_rejects_identifiers_embedded_in_absolute_paths() -> None:
    executor._assert_sanitized_argv(
        ["execute", "--output-dir", "/tmp/pastorai-safe-output"]
    )
    for unsafe in (
        f"/tmp/{PROJECT_REF}",
        f"/tmp/{SYSTEM_IDENTIFIER}",
    ):
        with pytest.raises(executor.UsageError):
            executor._assert_sanitized_argv(
                ["execute", "--output-dir", unsafe]
            )


@pytest.mark.parametrize("cleanup_succeeds", [True, False])
def test_postpublication_failure_reports_whether_the_artifact_remains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_succeeds: bool,
) -> None:
    staging_dir = tmp_path / "staging"
    output_dir = tmp_path / "output"
    for directory in (staging_dir, output_dir):
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)
    basename = "blocked-attestation.json"
    (staging_dir / basename).write_text("{}\n", encoding="ascii")

    def read_private_json(path: Path, _maximum: int) -> dict[str, object]:
        if path.parent == staging_dir:
            return {"artifact": "blocked"}
        raise RuntimeError("synthetic post-publication validation failure")

    def atomic_write(
        directory: Path,
        name: str,
        _artifact: dict[str, object],
        *,
        allowed_existing: set[str],
    ) -> Path:
        assert allowed_existing == set()
        path = directory / name
        path.write_text("{}\n", encoding="ascii")
        path.chmod(0o600)
        return path

    def unlink(
        directory: Path,
        name: str,
        *,
        expected_identity: tuple[int, ...],
    ) -> bool:
        assert expected_identity
        path = directory / name
        if cleanup_succeeds:
            path.unlink()
            return True
        return False

    monkeypatch.setattr(executor, "_safe_unlink_artifact", unlink)
    materializer = SimpleNamespace(
        ARTIFACT_BASENAMES={"DEV": basename},
        MAX_OUTPUT_BYTES=1024,
        _read_private_json=read_private_json,
        _load_contracts=lambda: {},
        _atomic_write=atomic_write,
    )
    verifier = SimpleNamespace(_validate_artifact=lambda *_args: None)
    state = executor.ExecutionState("DEV", SOURCE_GIT_SHA)
    witness = executor._witness_output_directory(output_dir)

    with pytest.raises(executor.CleanupError):
        executor._publish_artifact(
            environment="DEV",
            staging_dir=staging_dir,
            output_dir=output_dir,
            output_witness=witness,
            state=state,
            materializer=materializer,
            verifier=verifier,
        )

    assert state.artifact_published is (not cleanup_succeeds)
    assert (output_dir / basename).exists() is (not cleanup_succeeds)


@pytest.mark.parametrize("environment", ["DEV", "PROD"])
def test_authorization_accepts_exact_separate_environment_contract(
    environment: str,
) -> None:
    raw = _authorization_bytes(environment=environment)
    authorization = executor._validate_authorization(
        raw,
        environment=environment,
        confirmation=executor.CONFIRMATIONS[environment],
        source_git_sha=SOURCE_GIT_SHA,
        executor_sha256="e" * 64,
        tls_ca_certificate_sha256=hashlib.sha256(TLS_CA).hexdigest(),
        nonce_sha256=hashlib.sha256(NONCE).hexdigest(),
        now=NOW,
    )
    assert authorization.record_sha256 == hashlib.sha256(raw).hexdigest()
    assert authorization.values["prod_authorized"] is (environment == "PROD")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_mutation_authorized", True),
        ("migration_application_authorized", True),
        ("operational_authorization", True),
        ("next_stage_authorized", True),
        ("single_attempt", False),
        ("materialization_authorized", False),
        ("single_attempt", 1),
        ("database_session_authorized", 1),
        ("database_mutation_authorized", 0),
        ("prod_authorized", 0),
        ("source_git_sha", "b" * 40),
        ("attempt_nonce_sha256", "f" * 64),
    ],
)
def test_authorization_rejects_privilege_or_binding_drift(
    field: str,
    value: object,
) -> None:
    raw = _authorization_bytes(overrides={field: value})
    with pytest.raises(executor.AuthorizationError):
        executor._validate_authorization(
            raw,
            environment="DEV",
            confirmation=executor.CONFIRMATIONS["DEV"],
            source_git_sha=SOURCE_GIT_SHA,
            executor_sha256="e" * 64,
            tls_ca_certificate_sha256=hashlib.sha256(TLS_CA).hexdigest(),
            nonce_sha256=hashlib.sha256(NONCE).hexdigest(),
            now=NOW,
        )


def test_authorization_rejects_cross_environment_reuse_and_noncanonical_json() -> None:
    dev = _authorization_bytes(environment="DEV")
    with pytest.raises(executor.AuthorizationError):
        executor._validate_authorization(
            dev,
            environment="PROD",
            confirmation=executor.CONFIRMATIONS["PROD"],
            source_git_sha=SOURCE_GIT_SHA,
            executor_sha256="e" * 64,
            tls_ca_certificate_sha256=hashlib.sha256(TLS_CA).hexdigest(),
            nonce_sha256=hashlib.sha256(NONCE).hexdigest(),
            now=NOW,
        )
    parsed = json.loads(dev)
    noncanonical = (json.dumps(parsed, indent=2) + "\n").encode("ascii")
    with pytest.raises(executor.AuthorizationError):
        executor._validate_authorization(
            noncanonical,
            environment="DEV",
            confirmation=executor.CONFIRMATIONS["DEV"],
            source_git_sha=SOURCE_GIT_SHA,
            executor_sha256="e" * 64,
            tls_ca_certificate_sha256=hashlib.sha256(TLS_CA).hexdigest(),
            nonce_sha256=hashlib.sha256(NONCE).hexdigest(),
            now=NOW,
        )


def test_authorization_rejects_expired_or_oversized_window() -> None:
    for overrides, now in (
        (
            {
                "valid_from_utc": "2026-09-03T10:00:00Z",
                "expires_at_utc": "2026-09-03T10:10:00Z",
            },
            NOW,
        ),
        (
            {
                "valid_from_utc": "2026-09-03T11:50:00Z",
                "expires_at_utc": "2026-09-03T12:10:01Z",
            },
            NOW,
        ),
    ):
        with pytest.raises(executor.AuthorizationError):
            executor._validate_authorization(
                _authorization_bytes(overrides=overrides),
                environment="DEV",
                confirmation=executor.CONFIRMATIONS["DEV"],
                source_git_sha=SOURCE_GIT_SHA,
                executor_sha256="e" * 64,
                tls_ca_certificate_sha256=hashlib.sha256(TLS_CA).hexdigest(),
                nonce_sha256=hashlib.sha256(NONCE).hexdigest(),
                now=now,
            )


def test_authorization_window_is_inclusive_at_start_and_exclusive_at_expiry() -> None:
    raw = _authorization_bytes()
    start = datetime(2026, 9, 3, 11, 59, 0, tzinfo=timezone.utc)
    expiry = datetime(2026, 9, 3, 12, 10, 0, tzinfo=timezone.utc)
    executor._validate_authorization(
        raw,
        environment="DEV",
        confirmation=executor.CONFIRMATIONS["DEV"],
        source_git_sha=SOURCE_GIT_SHA,
        executor_sha256="e" * 64,
        tls_ca_certificate_sha256=hashlib.sha256(TLS_CA).hexdigest(),
        nonce_sha256=hashlib.sha256(NONCE).hexdigest(),
        now=start,
    )
    for observed in (start - timedelta(microseconds=1), expiry):
        with pytest.raises(executor.AuthorizationError):
            executor._validate_authorization(
                raw,
                environment="DEV",
                confirmation=executor.CONFIRMATIONS["DEV"],
                source_git_sha=SOURCE_GIT_SHA,
                executor_sha256="e" * 64,
                tls_ca_certificate_sha256=hashlib.sha256(TLS_CA).hexdigest(),
                nonce_sha256=hashlib.sha256(NONCE).hexdigest(),
                now=observed,
            )


def test_operational_dsn_accepts_only_stable_direct_or_session_postgres_5432() -> None:
    project_hash = executor._component_sha256("PROJECT_REF", PROJECT_REF)
    database_hash = executor._component_sha256("DATABASE_NAME", DATABASE_NAME)
    direct = (
        f"postgresql://postgres:private@db.{PROJECT_REF}.supabase.co:5432/"
        f"{DATABASE_NAME}"
    )
    observed, target = executor._validate_operational_dsn(
        direct.encode("utf-8"),
        expected_project_ref_sha256=project_hash,
        expected_database_name_sha256=database_hash,
        preflight=preflight_v1,
    )
    assert observed == direct
    assert target.project_ref == PROJECT_REF
    assert target.database_name == DATABASE_NAME

    session_pooler = (
        f"postgresql://postgres.{PROJECT_REF}:private@"
        "aws-0-us-east-1.pooler.supabase.com:5432/postgres"
    )
    observed, target = executor._validate_operational_dsn(
        session_pooler.encode("utf-8"),
        expected_project_ref_sha256=project_hash,
        expected_database_name_sha256=database_hash,
        preflight=preflight_v1,
    )
    assert observed == session_pooler
    assert target.project_ref == PROJECT_REF
    assert target.database_name == DATABASE_NAME

    rejected = (
        direct.replace(":5432/", ":6543/"),
        session_pooler.replace(":5432/", ":6543/"),
        direct + "?sslmode=require",
        direct.replace("db.", "db.bad,"),
        direct.replace("/postgres", "/other"),
        direct.replace(PROJECT_REF, "bcdefghijklmnopqrstu"),
    )
    for dsn in rejected:
        with pytest.raises((executor.TargetError, preflight_v1.PreflightError)):
            executor._validate_operational_dsn(
                dsn.encode("utf-8"),
                expected_project_ref_sha256=project_hash,
                expected_database_name_sha256=database_hash,
                preflight=preflight_v1,
            )


def test_private_fd_accepts_fifo_and_stable_0600_file(tmp_path: Path) -> None:
    with _pipe(b"fifo-secret") as descriptor:
        assert executor._read_private_fd(descriptor, 64) == b"fifo-secret"
    descriptor = _private_file(tmp_path / "secret", b"file-secret")
    try:
        assert executor._read_private_fd(descriptor, 64) == b"file-secret"
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("mode", [0o000, 0o400, 0o640, 0o700])
def test_private_regular_fd_rejects_every_mode_except_0600(
    tmp_path: Path,
    mode: int,
) -> None:
    path = tmp_path / f"secret-{mode:o}"
    path.write_bytes(b"secret")
    descriptor = os.open(path, os.O_RDONLY)
    path.chmod(mode)
    try:
        with pytest.raises(executor.PrivateInputError):
            executor._read_private_fd(descriptor, 64)
    finally:
        os.close(descriptor)


def test_private_fd_rejects_hardlink_socket_and_nonzero_position(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original"
    original.write_bytes(b"secret")
    original.chmod(0o600)
    linked = tmp_path / "linked"
    os.link(original, linked)
    descriptor = os.open(original, os.O_RDONLY)
    try:
        with pytest.raises(executor.PrivateInputError):
            executor._read_private_fd(descriptor, 64)
    finally:
        os.close(descriptor)

    first, second = socket.socketpair()
    try:
        with pytest.raises(executor.PrivateInputError):
            executor._read_private_fd(first.fileno(), 64)
    finally:
        first.close()
        second.close()

    positioned = tmp_path / "positioned"
    positioned.write_bytes(b"secret")
    positioned.chmod(0o600)
    descriptor = os.open(positioned, os.O_RDONLY)
    try:
        os.read(descriptor, 1)
        with pytest.raises(executor.PrivateInputError):
            executor._read_private_fd(descriptor, 64)
    finally:
        os.close(descriptor)


def test_child_environment_is_minimal_and_database_environment_is_rejected() -> None:
    environment = executor._minimal_child_environment()
    assert environment == {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.defpath,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    for name in (
        "DATABASE_URL",
        "PGPASSWORD",
        "SSL_CERT_FILE",
        "OPENSSL_CONF",
    ):
        with pytest.raises(executor.PrivateInputError):
            executor._assert_clean_database_environment({name: "secret"})


class _FakeSnapshot:
    def __init__(
        self,
        root: Path,
        repository: Path,
        git_sha: str,
        *,
        cleanup_fails: bool = False,
    ) -> None:
        self.root = root
        self.repository = repository
        self.git_sha = git_sha
        self.cleanup_calls = 0
        self.cleanup_fails = cleanup_fails

    def cleanup(self) -> None:
        self.cleanup_calls += 1
        if self.cleanup_fails:
            raise executor.trusted_snapshot.CleanupError


def test_public_bootstrap_executes_exact_snapshot_child_without_secret_argv_or_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mutable_repository = tmp_path / "mutable-checkout"
    mutable_repository.mkdir(mode=0o700)
    mutable_script = mutable_repository / "backend" / "scripts" / executor.SCRIPT_BASENAME
    mutable_script.parent.mkdir(parents=True)
    mutable_script.write_text("MUTABLE_CHECKOUT_SECRET\n", encoding="ascii")

    snapshot_root = tmp_path / "private-snapshot"
    snapshot_root.mkdir(mode=0o700)
    snapshot_repository = snapshot_root / "repository"
    snapshot_repository.mkdir(mode=0o700)
    snapshot_script = (
        snapshot_repository / "backend" / "scripts" / executor.SCRIPT_BASENAME
    )
    snapshot_script.parent.mkdir(parents=True)
    snapshot_script.write_text("TRUSTED_SNAPSHOT_COPY\n", encoding="ascii")
    snapshot = _FakeSnapshot(snapshot_root, snapshot_repository, SOURCE_GIT_SHA)
    creation_calls: list[dict[str, object]] = []

    def create_snapshot(**kwargs: object) -> _FakeSnapshot:
        creation_calls.append(kwargs)
        return snapshot

    observed: dict[str, object] = {}

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed["args"] = list(args)
        observed.update(kwargs)
        state = executor.ExecutionState("DEV", SOURCE_GIT_SHA)
        state.phase = "DONE_BLOCKED"
        state.capture_executed = True
        state.identity_capture_same_connection = True
        state.materialization_executed = True
        state.identity_rollback_confirmed = True
        state.capture_rollback_confirmed = True
        state.connection_closed = True
        state.artifact_published = True
        output = (
            "\n".join(
                (
                    *executor._deny_lines(state),
                    "EXECUTION_PHASE=DONE_BLOCKED",
                    "ENVIRONMENT_ATTESTATION_COMPLETE=false",
                    f"RESULT={executor.EvidenceMaterializedBlocked.reason}",
                )
            )
            + "\n"
        ).encode("ascii")
        return subprocess.CompletedProcess(args, 8, stdout=output, stderr=b"")

    monkeypatch.setattr(executor, "REPO_ROOT", mutable_repository)
    monkeypatch.setattr(executor, "_validate_bootstrap_primitive", lambda: None)
    monkeypatch.setattr(
        executor.trusted_snapshot,
        "create_trusted_repository_snapshot",
        create_snapshot,
    )
    monkeypatch.setattr(executor.subprocess, "run", run)
    output_dir = tmp_path / "output"
    output_dir.mkdir(mode=0o700)
    secret_dsn = (
        f"postgresql://postgres:private-password@db.{PROJECT_REF}.supabase.co:"
        "5432/postgres"
    )
    input_payloads = (
        secret_dsn.encode("utf-8"),
        TLS_CA,
        _authorization_bytes(),
        KEY,
        NONCE,
    )
    descriptors = tuple(_open_pipe(raw) for raw in input_payloads)
    args = argparse.Namespace(
        source_git_sha=SOURCE_GIT_SHA,
        environment="DEV",
        database_url_fd=descriptors[0],
        tls_ca_cert_fd=descriptors[1],
        authorization_record_fd=descriptors[2],
        hmac_key_fd=descriptors[3],
        nonce_fd=descriptors[4],
        output_dir=output_dir,
        confirmation=executor.CONFIRMATIONS["DEV"],
    )
    assert executor._public_execute(args) == 8
    assert creation_calls == [
        {"repository_root": mutable_repository, "git_sha": SOURCE_GIT_SHA}
    ]
    child_args = observed["args"]
    assert isinstance(child_args, list)
    assert child_args[1:3] == ["-I", "-B"]
    assert str(snapshot_script) in child_args
    assert str(mutable_script) not in child_args
    joined = " ".join(child_args)
    assert secret_dsn not in joined
    assert "private-password" not in joined
    assert PROJECT_REF not in joined
    assert observed["cwd"] == snapshot_repository
    assert observed["env"] == executor._minimal_child_environment()
    assert observed["close_fds"] is True
    assert observed["stdin"] is subprocess.DEVNULL
    assert len(observed["pass_fds"]) == 7
    assert snapshot.cleanup_calls == 1
    assert "SNAPSHOT_CLEANUP_CONFIRMED=true" in capsys.readouterr().out
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_abnormal_child_exit_conservatively_reports_a_remaining_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir(mode=0o700)
    snapshot_root = tmp_path / "snapshot"
    snapshot_root.mkdir(mode=0o700)
    snapshot = _FakeSnapshot(snapshot_root, repository, SOURCE_GIT_SHA)
    output_dir = tmp_path / "output"
    output_dir.mkdir(mode=0o700)
    basename = "migration-history-environment-attestation-dev-v1.json"

    def run(
        args: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        artifact = output_dir / basename
        artifact.write_bytes(b"blocked-artifact\n")
        artifact.chmod(0o600)
        return subprocess.CompletedProcess(
            args,
            executor.DatabaseError.exit_code,
            stdout=b"INVALID CHILD PROTOCOL\n",
            stderr=b"",
        )

    monkeypatch.setattr(executor, "_validate_bootstrap_primitive", lambda: None)
    monkeypatch.setattr(
        executor.trusted_snapshot,
        "create_trusted_repository_snapshot",
        lambda **_kwargs: snapshot,
    )
    monkeypatch.setattr(executor.subprocess, "run", run)
    descriptors = tuple(_open_pipe(b"x") for _ in range(5))
    args = argparse.Namespace(
        source_git_sha=SOURCE_GIT_SHA,
        environment="DEV",
        database_url_fd=descriptors[0],
        tls_ca_cert_fd=descriptors[1],
        authorization_record_fd=descriptors[2],
        hmac_key_fd=descriptors[3],
        nonce_fd=descriptors[4],
        output_dir=output_dir,
        confirmation=executor.CONFIRMATIONS["DEV"],
    )

    assert executor._public_execute(args) == executor.CleanupError.exit_code
    output = capsys.readouterr().out
    assert "ARTIFACT_PUBLISHED=true" in output
    assert "EXECUTION_PHASE=CHILD_OUTPUT" in output
    assert (output_dir / basename).is_file()
    assert snapshot.cleanup_calls == 1
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_public_rejection_never_deletes_a_preexisting_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(executor, "_validate_bootstrap_primitive", lambda: None)
    monkeypatch.setattr(
        executor.trusted_snapshot,
        "create_trusted_repository_snapshot",
        lambda **_kwargs: pytest.fail("snapshot creation must not start"),
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir(mode=0o700)
    artifact = output_dir / "migration-history-environment-attestation-dev-v1.json"
    artifact.write_bytes(b"preexisting-owner-evidence\n")
    artifact.chmod(0o600)
    before = artifact.stat()
    descriptors = tuple(_open_pipe(b"x") for _ in range(5))
    args = argparse.Namespace(
        source_git_sha=SOURCE_GIT_SHA,
        environment="DEV",
        database_url_fd=descriptors[0],
        tls_ca_cert_fd=descriptors[1],
        authorization_record_fd=descriptors[2],
        hmac_key_fd=descriptors[3],
        nonce_fd=descriptors[4],
        output_dir=output_dir,
        confirmation=executor.CONFIRMATIONS["DEV"],
    )
    assert executor._public_execute(args) == executor.PrivateInputError.exit_code
    after = artifact.stat()
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert artifact.read_bytes() == b"preexisting-owner-evidence\n"
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_cleanup_unlinks_only_the_exact_artifact_inode(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir(mode=0o700)
    basename = "migration-history-environment-attestation-dev-v1.json"
    artifact = output_dir / basename
    artifact.write_bytes(b"first\n")
    artifact.chmod(0o600)
    first = artifact.stat()
    artifact.unlink()
    artifact.write_bytes(b"replacement\n")
    artifact.chmod(0o600)
    replacement = artifact.stat()
    assert executor._safe_unlink_artifact(
        output_dir,
        basename,
        expected_identity=executor._stat_identity(first),
    ) is False
    assert artifact.read_bytes() == b"replacement\n"
    assert executor._safe_unlink_artifact(
        output_dir,
        basename,
        expected_identity=executor._stat_identity(replacement),
    ) is True
    assert not artifact.exists()


class _IdentityCursor:
    def __init__(self, connection: "_IdentityConnection", identity: dict[str, Any]) -> None:
        self.connection = connection
        self.identity = identity
        self.executed: list[str] = []
        self.rows: list[Any] = []
        self.close_calls = 0
        self.fail_identity = False
        self.fail_close = False

    def execute(self, statement: str) -> None:
        self.executed.append(statement)
        if statement == "begin\n":
            self.connection.status = 2
            self.rows = []
        elif statement == "guard\n":
            self.rows = [("ok",), None]
        elif statement == "identity\n":
            if self.fail_identity:
                raise RuntimeError("private-password SQLERRM")
            self.rows = [(self.identity,), None]
        elif statement == "rollback\n":
            self.connection.status = 0
            self.rows = []

    def fetchone(self) -> Any:
        return self.rows.pop(0) if self.rows else None

    def close(self) -> None:
        self.close_calls += 1
        if self.fail_close:
            raise RuntimeError("private-password close")


class _IdentityConnection:
    def __init__(self, identity: dict[str, Any]) -> None:
        self.autocommit = True
        self.status = 0
        self.rollback_calls = 0
        self.cursor_instance = _IdentityCursor(self, identity)

    def cursor(self) -> _IdentityCursor:
        return self.cursor_instance

    def get_transaction_status(self) -> int:
        return self.status

    def rollback(self) -> None:
        self.rollback_calls += 1
        self.status = 0


class _IdentityPreflight:
    extensions = SimpleNamespace(TRANSACTION_STATUS_IDLE=0)

    @staticmethod
    def _fetch_single_value(cursor: _IdentityCursor) -> Any:
        row = cursor.fetchone()
        extra = cursor.fetchone()
        if not isinstance(row, tuple) or len(row) != 1 or extra is not None:
            raise RuntimeError
        return row[0]

    @staticmethod
    def _strict_json_object(value: Any) -> dict[str, Any]:
        assert isinstance(value, dict)
        return value

    @staticmethod
    def _validate_identity(value: dict[str, Any], _target: object) -> tuple[str, str]:
        return value["system_identifier"], value["database_name"]


def _identity() -> dict[str, Any]:
    return {
        "system_identifier": SYSTEM_IDENTIFIER,
        "database_name": DATABASE_NAME,
    }


def test_identity_transaction_rolls_back_and_leaves_connection_idle() -> None:
    connection = _IdentityConnection(_identity())
    contract = SimpleNamespace(
        statements=("begin\n", "guard\n", "identity\n"),
        rollback="rollback\n",
    )
    assert executor._run_identity_transaction(
        connection,
        target=object(),
        sql_contract=contract,
        preflight=_IdentityPreflight,
    ) == _identity()
    assert connection.cursor_instance.executed == [
        "begin\n",
        "guard\n",
        "identity\n",
        "rollback\n",
    ]
    assert connection.status == 0
    assert connection.cursor_instance.close_calls == 1


def test_identity_failure_still_rolls_back_and_sanitizes_exception() -> None:
    connection = _IdentityConnection(_identity())
    connection.cursor_instance.fail_identity = True
    contract = SimpleNamespace(
        statements=("begin\n", "guard\n", "identity\n"),
        rollback="rollback\n",
    )
    with pytest.raises(executor.DatabaseError) as captured:
        executor._run_identity_transaction(
            connection,
            target=object(),
            sql_contract=contract,
            preflight=_IdentityPreflight,
        )
    assert str(captured.value) == ""
    assert connection.cursor_instance.executed[-1] == "rollback\n"
    assert connection.status == 0


def test_isolated_cursor_close_failure_becomes_cleanup_error() -> None:
    connection = _IdentityConnection(_identity())
    connection.cursor_instance.fail_close = True
    contract = SimpleNamespace(
        statements=("begin\n", "guard\n", "identity\n"),
        rollback="rollback\n",
    )
    with pytest.raises(executor.CleanupError) as captured:
        executor._run_identity_transaction(
            connection,
            target=object(),
            sql_contract=contract,
            preflight=_IdentityPreflight,
        )
    assert captured.value.phase == "IDENTITY_ROLLBACK"


class _ChildConnection:
    def __init__(self, backend_pids: list[int] | None = None) -> None:
        self.server_version = 170_006
        self.autocommit = False
        self.closed = 0
        self.close_calls = 0
        self.rollback_calls = 0
        self.backend_pids = list(backend_pids or [4321, 4321, 4321, 4321])

    def get_backend_pid(self) -> int:
        if len(self.backend_pids) > 1:
            return self.backend_pids.pop(0)
        return self.backend_pids[0]

    def get_transaction_status(self) -> int:
        return 0

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.close_calls += 1
        self.closed = 1


class _ChildPreflight:
    extensions = SimpleNamespace(TRANSACTION_STATUS_IDLE=0)

    @staticmethod
    def _witness_tls_ca_certificate_fd(_descriptor: int) -> SimpleNamespace:
        return SimpleNamespace(sha256=hashlib.sha256(TLS_CA).hexdigest())

    @staticmethod
    def _revalidate_tls_ca_certificate_fd(_witness: object) -> None:
        return None

    @staticmethod
    def _load_sql_contract() -> object:
        return object()


class _ChildMaterializer:
    def __init__(self, connection: _ChildConnection) -> None:
        self.connection = connection
        self.bind_connections_closed: list[int] = []
        self.capture_connections: list[object] = []
        self.materialize_connections_closed: list[int] = []

    def bind_target(self, **_kwargs: object) -> Path:
        self.bind_connections_closed.append(self.connection.closed)
        return Path("binding")

    def capture_one_snapshot(self, connection: object) -> tuple[dict[str, Any], list[Any]]:
        self.capture_connections.append(connection)
        return (
            {
                "session_proof": {"backend_pid": 4321},
                "system_identifier": SYSTEM_IDENTIFIER,
                "database_name": DATABASE_NAME,
            },
            [],
        )

    def materialize(self, **_kwargs: object) -> tuple[Path, bool]:
        self.materialize_connections_closed.append(self.connection.closed)
        return Path("artifact"), True


def _child_args_and_fds(
    tmp_path: Path,
    *,
    executor_sha256: str,
) -> tuple[argparse.Namespace, tuple[int, ...]]:
    output_dir = tmp_path / "output"
    output_dir.mkdir(mode=0o700)
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir(mode=0o700)
    context_fd = _open_pipe(b"context")
    token_fd = _open_pipe(b"t" * 32)
    database_url_fd = _open_pipe(
        (
            f"postgresql://postgres:private-password@db.{PROJECT_REF}."
            "supabase.co:5432/postgres"
        ).encode("utf-8")
    )
    authorization_fd = _open_pipe(
        _authorization_bytes(executor_sha256=executor_sha256)
    )
    hmac_key_fd = _open_pipe(KEY)
    nonce_fd = _open_pipe(NONCE)
    ca_path = tmp_path / "ca.crt"
    tls_ca_fd = _private_file(ca_path, TLS_CA)
    args = argparse.Namespace(
        environment="DEV",
        source_git_sha=SOURCE_GIT_SHA,
        snapshot_context_fd=context_fd,
        launch_token_fd=token_fd,
        database_url_fd=database_url_fd,
        tls_ca_cert_fd=tls_ca_fd,
        authorization_record_fd=authorization_fd,
        hmac_key_fd=hmac_key_fd,
        nonce_fd=nonce_fd,
        output_dir=output_dir,
        staging_dir=staging_dir,
        confirmation=executor.CONFIRMATIONS["DEV"],
    )
    return args, (
        context_fd,
        token_fd,
        database_url_fd,
        tls_ca_fd,
        authorization_fd,
        hmac_key_fd,
        nonce_fd,
    )


def test_child_connects_once_keeps_same_session_and_closes_before_materializing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clean_database_environment(monkeypatch)
    executor_sha256 = "e" * 64
    args, descriptors = _child_args_and_fds(
        tmp_path,
        executor_sha256=executor_sha256,
    )
    connection = _ChildConnection()
    materializer = _ChildMaterializer(connection)
    connect_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def connect(*positional: Any, **keywords: Any) -> _ChildConnection:
        connect_calls.append((positional, keywords))
        return connection

    identity_connections: list[object] = []

    def run_identity(connection_arg: object, **_kwargs: object) -> dict[str, Any]:
        identity_connections.append(connection_arg)
        return _identity()

    monkeypatch.setattr(executor, "_validate_snapshot_context", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(
        executor,
        "_validate_contract_files",
        lambda _repository: {executor.SCRIPT_BASENAME: executor_sha256},
    )
    monkeypatch.setattr(
        executor,
        "_load_child_modules",
        lambda _repository: (
            SimpleNamespace(),
            _ChildPreflight,
            materializer,
            object(),
        ),
    )
    monkeypatch.setattr(
        executor,
        "_validate_operational_dsn",
        lambda *_a, **_k: ("private-dsn", object()),
    )
    monkeypatch.setattr(executor, "_run_identity_transaction", run_identity)

    def publish(**kwargs: object) -> tuple[Path, tuple[int, ...]]:
        assert connection.closed == 1
        path = Path(kwargs["output_dir"]) / "artifact.json"
        path.write_text("{}\n", encoding="ascii")
        path.chmod(0o600)
        info = path.stat()
        return path, executor._stat_identity(info)

    monkeypatch.setattr(executor, "_publish_artifact", publish)
    code, state = executor._execute_child(args, connect=connect, now=NOW)
    assert code == 8
    assert len(connect_calls) == 1
    assert connect_calls[0][0] == ("private-dsn",)
    assert connect_calls[0][1] == {
        "application_name": "pastorai_migration_environment_attestation_v2_dev",
        "connect_timeout": 5,
        "sslmode": "verify-full",
        "sslrootcert": f"/proc/self/fd/{descriptors[3]}",
    }
    assert identity_connections == [connection]
    assert materializer.capture_connections == [connection]
    assert materializer.bind_connections_closed == [0]
    assert materializer.materialize_connections_closed == [1]
    assert connection.close_calls == 1
    assert state.identity_rollback_confirmed is True
    assert state.capture_rollback_confirmed is True
    assert state.connection_closed is True
    assert state.artifact_published is True
    assert state.phase == "DONE_BLOCKED"
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_session_pid_change_blocks_before_capture_and_closes_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clean_database_environment(monkeypatch)
    executor_sha256 = "e" * 64
    args, descriptors = _child_args_and_fds(
        tmp_path,
        executor_sha256=executor_sha256,
    )
    connection = _ChildConnection([4321, 9999])
    materializer = _ChildMaterializer(connection)
    monkeypatch.setattr(executor, "_validate_snapshot_context", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(
        executor,
        "_validate_contract_files",
        lambda _repository: {executor.SCRIPT_BASENAME: executor_sha256},
    )
    monkeypatch.setattr(
        executor,
        "_load_child_modules",
        lambda _repository: (
            SimpleNamespace(),
            _ChildPreflight,
            materializer,
            object(),
        ),
    )
    monkeypatch.setattr(
        executor,
        "_validate_operational_dsn",
        lambda *_a, **_k: ("private-dsn", object()),
    )
    monkeypatch.setattr(executor, "_run_identity_transaction", lambda *_a, **_k: _identity())
    with pytest.raises(executor.DatabaseError) as captured:
        executor._execute_child(args, connect=lambda *_a, **_k: connection, now=NOW)
    assert captured.value.phase == "SESSION_CONTINUITY"
    assert materializer.capture_connections == []
    assert connection.close_calls == 1
    assert connection.closed == 1
    assert not any(args.output_dir.iterdir())
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_child_failure_report_uses_the_mutated_execution_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = argparse.Namespace(environment="DEV", source_git_sha=SOURCE_GIT_SHA)

    def fail(
        _args: argparse.Namespace,
        *,
        state: executor.ExecutionState | None = None,
        **_kwargs: object,
    ) -> tuple[int, executor.ExecutionState]:
        assert state is not None
        state.connection_opened = True
        state.connection_closed = False
        state.identity_rollback_confirmed = True
        raise executor.CleanupError(phase="CONNECTION_CLOSE")

    monkeypatch.setattr(executor, "_execute_child", fail)
    assert executor._child_main(args) == executor.CleanupError.exit_code
    output = capsys.readouterr().out
    assert "CONNECTION_CLOSED=false" in output
    assert "IDENTITY_ROLLBACK_CONFIRMED=true" in output
    assert "FAILURE_PHASE=CONNECTION_CLOSE" in output


def _successful_child_output() -> bytes:
    state = executor.ExecutionState("DEV", SOURCE_GIT_SHA)
    state.phase = "DONE_BLOCKED"
    state.capture_executed = True
    state.identity_capture_same_connection = True
    state.materialization_executed = True
    state.identity_rollback_confirmed = True
    state.capture_rollback_confirmed = True
    state.connection_closed = True
    state.artifact_published = True
    return (
        "\n".join(
            (
                *executor._deny_lines(state),
                "EXECUTION_PHASE=DONE_BLOCKED",
                "ENVIRONMENT_ATTESTATION_COMPLETE=false",
                f"RESULT={executor.EvidenceMaterializedBlocked.reason}",
            )
        )
        + "\n"
    ).encode("ascii")


def test_describe_reports_snapshot_cleanup_failure_without_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "snapshot"
    repository = root / "repository"
    repository.mkdir(parents=True, mode=0o700)
    snapshot = _FakeSnapshot(
        root,
        repository,
        SOURCE_GIT_SHA,
        cleanup_fails=True,
    )
    digests = dict(executor.EXPECTED_FILE_SHA256)
    digests[executor.SCRIPT_BASENAME] = "e" * 64
    monkeypatch.setattr(executor, "_validate_bootstrap_primitive", lambda: None)
    monkeypatch.setattr(
        executor.trusted_snapshot,
        "create_trusted_repository_snapshot",
        lambda **_kwargs: snapshot,
    )
    monkeypatch.setattr(executor, "_validate_contract_files", lambda _path: digests)
    assert executor._describe(SOURCE_GIT_SHA) == executor.CleanupError.exit_code
    output = capsys.readouterr().out
    assert output.count("SNAPSHOT_CLEANUP_CONFIRMED=false") == 1
    assert f"RESULT={executor.CleanupError.reason}" in output
    assert "DESCRIBED_OFFLINE" not in output
    assert snapshot.cleanup_calls == 1


def test_public_cleanup_failure_preserves_published_artifact_and_reports_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "snapshot"
    repository = root / "repository"
    repository.mkdir(parents=True, mode=0o700)
    snapshot = _FakeSnapshot(
        root,
        repository,
        SOURCE_GIT_SHA,
        cleanup_fails=True,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir(mode=0o700)
    artifact = output_dir / "migration-history-environment-attestation-dev-v1.json"

    def run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        artifact.write_bytes(b"valid-blocked-artifact\n")
        artifact.chmod(0o600)
        return subprocess.CompletedProcess(
            args,
            executor.EvidenceMaterializedBlocked.exit_code,
            stdout=_successful_child_output(),
            stderr=b"",
        )

    monkeypatch.setattr(executor, "_validate_bootstrap_primitive", lambda: None)
    monkeypatch.setattr(
        executor.trusted_snapshot,
        "create_trusted_repository_snapshot",
        lambda **_kwargs: snapshot,
    )
    monkeypatch.setattr(executor.subprocess, "run", run)
    descriptors = tuple(_open_pipe(b"x") for _ in range(5))
    args = argparse.Namespace(
        source_git_sha=SOURCE_GIT_SHA,
        environment="DEV",
        database_url_fd=descriptors[0],
        tls_ca_cert_fd=descriptors[1],
        authorization_record_fd=descriptors[2],
        hmac_key_fd=descriptors[3],
        nonce_fd=descriptors[4],
        output_dir=output_dir,
        confirmation=executor.CONFIRMATIONS["DEV"],
    )
    assert executor._public_execute(args) == executor.CleanupError.exit_code
    output = capsys.readouterr().out
    assert output.count("SNAPSHOT_CLEANUP_CONFIRMED=false") == 1
    assert "ARTIFACT_PUBLISHED=true" in output
    assert f"RESULT={executor.CleanupError.reason}" in output
    assert artifact.read_bytes() == b"valid-blocked-artifact\n"
    assert snapshot.cleanup_calls == 1


def test_child_output_protocol_is_exact_and_bound_to_invocation() -> None:
    raw = _successful_child_output()
    text, values = executor._validate_child_output(
        raw,
        expected_environment="DEV",
        expected_source_git_sha=SOURCE_GIT_SHA,
        exit_code=8,
    )
    assert text.encode("ascii") == raw
    assert values["RESULT"] == executor.EvidenceMaterializedBlocked.reason
    rejected = (
        raw.replace(b"ENVIRONMENT=DEV\n", b"ENVIRONMENT=PROD\n", 1),
        raw.replace(SOURCE_GIT_SHA.encode("ascii"), b"b" * 40, 1),
        raw.replace(
            executor.EvidenceMaterializedBlocked.reason.encode("ascii"),
            executor.DatabaseError.reason.encode("ascii"),
            1,
        ),
        raw + b"ENVIRONMENT=DEV\n",
        raw + b"SNAPSHOT_CLEANUP_CONFIRMED=true\n",
        raw.replace(b"CAPTURE_EXECUTED=true\n", b"", 1),
    )
    for candidate in rejected:
        with pytest.raises(executor.CleanupError):
            executor._validate_child_output(
                candidate,
                expected_environment="DEV",
                expected_source_git_sha=SOURCE_GIT_SHA,
                exit_code=8,
            )
    with pytest.raises(executor.CleanupError):
        executor._validate_child_output(
            raw,
            expected_environment="DEV",
            expected_source_git_sha=SOURCE_GIT_SHA,
            exit_code=7,
        )


@pytest.mark.parametrize(
    "raw",
    [
        b"RESULT=OK\npassword=secret\n",
        b"RESULT=OK\nDATABASE_URL=postgresql://private\n",
        b"RESULT=OK\nnot terminated",
        b"RESULT=OK\nPRIVATE VALUE\n",
    ],
)
def test_child_output_rejects_secrets_or_noncanonical_lines(raw: bytes) -> None:
    with pytest.raises(executor.CleanupError):
        executor._validate_child_output(
            raw,
            expected_environment="DEV",
            expected_source_git_sha=SOURCE_GIT_SHA,
            exit_code=8,
        )
