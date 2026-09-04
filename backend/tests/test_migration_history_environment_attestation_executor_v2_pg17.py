"""Disposable PostgreSQL 17/TLS proof for the environment executor v2."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Iterator

import psycopg2
import pytest

from scripts import execute_migration_history_environment_attestation_v2 as executor
from scripts import materialize_migration_history_environment_attestation as materializer


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "execute_migration_history_environment_attestation_v2.py"
)
SOURCE_GIT_SHA_ENV = "MIGRATION_EXECUTOR_V2_TEST_SOURCE_GIT_SHA"
WRONG_HOST_PROJECT_REF = "cdefghijklmnopqrstuv"
TARGETS = {
    "DEV": {
        "database_url_env": "MIGRATION_EXECUTOR_V2_DEV_TEST_DATABASE_URL",
        "tls_ca_env": "MIGRATION_EXECUTOR_V2_DEV_TEST_TLS_CA_CERT_PATH",
        "project_ref": "abcdefghijklmnopqrst",
        "password": "postgres",
    },
    "PROD": {
        "database_url_env": "MIGRATION_EXECUTOR_V2_PROD_TEST_DATABASE_URL",
        "tls_ca_env": "MIGRATION_EXECUTOR_V2_PROD_TEST_TLS_CA_CERT_PATH",
        "project_ref": "bcdefghijklmnopqrstu",
        "password": "prod_executor_v2_test_password",
    },
}


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("ascii")


def _close_descriptor(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


@contextmanager
def _private_pipe(raw: bytes) -> Iterator[int]:
    read_descriptor, write_descriptor = os.pipe()
    try:
        os.write(write_descriptor, raw)
    finally:
        os.close(write_descriptor)
    try:
        info = os.fstat(read_descriptor)
        assert stat.S_ISFIFO(info.st_mode)
        assert stat.S_IMODE(info.st_mode) == 0o600
        assert info.st_nlink == 1
        yield read_descriptor
    finally:
        _close_descriptor(read_descriptor)


def _clean_subprocess_environment() -> dict[str, str]:
    test_names = {SOURCE_GIT_SHA_ENV}
    for target in TARGETS.values():
        test_names.add(str(target["database_url_env"]))
        test_names.add(str(target["tls_ca_env"]))
    result: dict[str, str] = {}
    for name, value in os.environ.items():
        upper = name.upper()
        if (
            name in test_names
            or upper.startswith(("PG", "SSL", "OPENSSL"))
            or "DATABASE_URL" in upper
            or upper in executor.RELEVANT_DATABASE_ENV_NAMES
        ):
            continue
        result[name] = value
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    return result


def _output_map(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition("=")
        assert separator == "="
        assert key not in result
        result[key] = value
    return result


def _snapshot_roots() -> frozenset[str]:
    return frozenset(
        entry.name
        for entry in Path("/tmp").iterdir()
        if entry.name.startswith(executor.trusted_snapshot.SNAPSHOT_PREFIX)
    )


def _successful_execution_output(environment: str, source_git_sha: str) -> str:
    return "\n".join(
        (
            f"ENVIRONMENT={environment}",
            f"SOURCE_GIT_SHA={source_git_sha}",
            "BOOTSTRAP_TRUST_REQUIREMENT="
            "EXTERNALLY_PINNED_BOOTSTRAP_AND_TRUSTED_SNAPSHOT_PRIMITIVE",
            "AUTHORIZATION_TRUST_REQUIREMENT="
            "EXTERNAL_NOMINAL_GATE_AUTHENTICATION_REQUIRED",
            "RUNTIME_TRUST_REQUIREMENT=EXTERNALLY_PINNED_RUNTIME_REQUIRED",
            "DATABASE_MUTATION_AUTHORIZED=false",
            "MIGRATION_APPLICATION_AUTHORIZED=false",
            "OPERATIONAL_AUTHORIZATION=false",
            "NEXT_STAGE_AUTHORIZED=false",
            "CAPTURE_EXECUTED=true",
            "IDENTITY_CAPTURE_SAME_CONNECTION=true",
            "MATERIALIZATION_EXECUTED=true",
            "IDENTITY_ROLLBACK_CONFIRMED=true",
            "CAPTURE_ROLLBACK_CONFIRMED=true",
            "CONNECTION_CLOSED=true",
            "ARTIFACT_PUBLISHED=true",
            "EXECUTION_PHASE=DONE_BLOCKED",
            "ENVIRONMENT_ATTESTATION_COMPLETE=false",
            "RESULT=BLOCKED_ENVIRONMENT_ATTESTATION_V1_MATERIALIZED",
            "SNAPSHOT_CLEANUP_CONFIRMED=true",
            "",
        )
    )


def _connect_tls_failure_output(environment: str, source_git_sha: str) -> str:
    return "\n".join(
        (
            f"ENVIRONMENT={environment}",
            f"SOURCE_GIT_SHA={source_git_sha}",
            "BOOTSTRAP_TRUST_REQUIREMENT="
            "EXTERNALLY_PINNED_BOOTSTRAP_AND_TRUSTED_SNAPSHOT_PRIMITIVE",
            "AUTHORIZATION_TRUST_REQUIREMENT="
            "EXTERNAL_NOMINAL_GATE_AUTHENTICATION_REQUIRED",
            "RUNTIME_TRUST_REQUIREMENT=EXTERNALLY_PINNED_RUNTIME_REQUIRED",
            "DATABASE_MUTATION_AUTHORIZED=false",
            "MIGRATION_APPLICATION_AUTHORIZED=false",
            "OPERATIONAL_AUTHORIZATION=false",
            "NEXT_STAGE_AUTHORIZED=false",
            "CAPTURE_EXECUTED=false",
            "IDENTITY_CAPTURE_SAME_CONNECTION=false",
            "MATERIALIZATION_EXECUTED=false",
            "IDENTITY_ROLLBACK_CONFIRMED=false",
            "CAPTURE_ROLLBACK_CONFIRMED=false",
            "CONNECTION_CLOSED=true",
            "ARTIFACT_PUBLISHED=false",
            "EXECUTION_PHASE=CONNECT_TLS_AUTH",
            "FAILURE_PHASE=CONNECT_TLS_AUTH",
            "ENVIRONMENT_ATTESTATION_COMPLETE=false",
            "RESULT=CONNECT_TLS_AUTH_OR_CAPTURE_FAILED",
            "SNAPSHOT_CLEANUP_CONFIRMED=true",
            "",
        )
    )


def _describe(source_git_sha: str) -> dict[str, str]:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(RUNNER_PATH),
            "describe",
            "--source-git-sha",
            source_git_sha,
        ],
        check=False,
        close_fds=True,
        capture_output=True,
        env=_clean_subprocess_environment(),
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stderr == ""
    return _output_map(completed.stdout)


def _database_observation(
    database_url: str,
    tls_ca_path: Path,
) -> tuple[str, tuple[object, ...]]:
    connection = psycopg2.connect(
        database_url,
        connect_timeout=5,
        sslmode="verify-full",
        sslrootcert=str(tls_ca_path),
    )
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select (pg_catalog.pg_control_system()).system_identifier::text"
            )
            row = cursor.fetchone()
            assert row is not None
            system_identifier = str(row[0])
            cursor.execute(
                "select "
                "(select pg_catalog.count(*) from pg_catalog.pg_namespace "
                "where nspname not like 'pg_%' "
                "and nspname <> 'information_schema'), "
                "(select pg_catalog.count(*) from pg_catalog.pg_class c "
                "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
                "where n.nspname not like 'pg_%' "
                "and n.nspname <> 'information_schema'), "
                "pg_catalog.to_regclass('public.schema_migrations') is null, "
                "pg_catalog.to_regnamespace('supabase_migrations') is null, "
                "pg_catalog.txid_current_if_assigned() is null"
            )
            catalog = cursor.fetchone()
            assert catalog is not None
        return system_identifier, tuple(catalog)
    finally:
        connection.close()


def _authorization(
    *,
    environment: str,
    source_git_sha: str,
    description: dict[str, str],
    project_ref: str,
    system_identifier: str,
    tls_ca: bytes,
    nonce: bytes,
) -> bytes:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    hashes = {
        "executor_sha256": "EXECUTOR_SHA256",
        "trusted_snapshot_script_sha256": "TRUSTED_SNAPSHOT_SCRIPT_SHA256",
        "preflight_runner_sha256": "PREFLIGHT_RUNNER_SHA256",
        "materializer_sha256": "MATERIALIZER_SHA256",
        "verifier_sha256": "VERIFIER_SHA256",
        "canonical_derivation_sha256": "CANONICAL_DERIVATION_SHA256",
        "source_manifest_verifier_sha256": "SOURCE_MANIFEST_VERIFIER_SHA256",
        "catalog_head_verifier_sha256": "CATALOG_HEAD_VERIFIER_SHA256",
        "preflight_sql_sha256": "PREFLIGHT_SQL_SHA256",
        "capture_sql_sha256": "CAPTURE_SQL_SHA256",
        "profile_sha256": "PROFILE_SHA256",
        "artifact_schema_sha256": "ARTIFACT_SCHEMA_SHA256",
        "authorization_schema_sha256": "AUTHORIZATION_SCHEMA_SHA256",
    }
    values: dict[str, object] = {
        "authorization_contract": description["AUTHORIZATION_CONTRACT"],
        "gate": executor.GATES[environment],
        "environment": environment,
        "confirmation": executor.CONFIRMATIONS[environment],
        "owner": "OWNER-01_RANIEL",
        "executor": "CI-PG17",
        "source_git_sha": source_git_sha,
        **{field: description[key] for field, key in hashes.items()},
        "tls_ca_certificate_sha256": hashlib.sha256(tls_ca).hexdigest(),
        "expected_project_ref_sha256": executor._component_sha256(
            "PROJECT_REF", project_ref
        ),
        "expected_database_name_sha256": executor._component_sha256(
            "DATABASE_NAME", "postgres"
        ),
        "expected_system_identifier_sha256": executor._component_sha256(
            "SYSTEM_IDENTIFIER", system_identifier
        ),
        "attempt_nonce_sha256": hashlib.sha256(nonce).hexdigest(),
        "valid_from_utc": (now - timedelta(minutes=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "expires_at_utc": (now + timedelta(minutes=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
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
    return _canonical_bytes(values)


def _execute(
    *,
    environment: str,
    source_git_sha: str,
    description: dict[str, str],
    database_url: str,
    tls_ca_path: Path,
    system_identifier: str,
    output_dir: Path,
    tls_ca_override_path: Path | None = None,
    project_ref_override: str | None = None,
) -> subprocess.CompletedProcess[str]:
    target = TARGETS[environment]
    project_ref = project_ref_override or str(target["project_ref"])
    nonce = (b"d" if environment == "DEV" else b"p") * 32
    key = (b"k" if environment == "DEV" else b"q") * 32
    ca_path = tls_ca_override_path or tls_ca_path
    tls_ca = ca_path.read_bytes()
    authorization = _authorization(
        environment=environment,
        source_git_sha=source_git_sha,
        description=description,
        project_ref=project_ref,
        system_identifier=system_identifier,
        tls_ca=tls_ca,
        nonce=nonce,
    )
    output_dir.mkdir(mode=0o700)
    output_dir.chmod(0o700)
    with ExitStack() as stack:
        database_url_fd = stack.enter_context(
            _private_pipe(database_url.encode("utf-8"))
        )
        authorization_fd = stack.enter_context(_private_pipe(authorization))
        hmac_key_fd = stack.enter_context(_private_pipe(key))
        nonce_fd = stack.enter_context(_private_pipe(nonce))
        ca_fd = os.open(ca_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        stack.callback(_close_descriptor, ca_fd)
        argv = [
            sys.executable,
            "-I",
            "-B",
            str(RUNNER_PATH),
            "execute",
            "--source-git-sha",
            source_git_sha,
            "--environment",
            environment,
            "--database-url-fd",
            str(database_url_fd),
            "--tls-ca-cert-fd",
            str(ca_fd),
            "--authorization-record-fd",
            str(authorization_fd),
            "--hmac-key-fd",
            str(hmac_key_fd),
            "--nonce-fd",
            str(nonce_fd),
            "--output-dir",
            str(output_dir),
            "--confirmation",
            executor.CONFIRMATIONS[environment],
        ]
        assert database_url not in argv
        assert str(target["password"]) not in argv
        return subprocess.run(
            argv,
            check=False,
            close_fds=True,
            pass_fds=(
                database_url_fd,
                ca_fd,
                authorization_fd,
                hmac_key_fd,
                nonce_fd,
            ),
            capture_output=True,
            env=_clean_subprocess_environment(),
            text=True,
            timeout=60,
        )


def test_executor_v2_dev_and_prod_are_same_session_read_only_and_separate(
    tmp_path: Path,
) -> None:
    source_git_sha = os.environ.get(SOURCE_GIT_SHA_ENV)
    configured: dict[str, tuple[str, Path]] = {}
    for environment, target in TARGETS.items():
        database_url = os.environ.get(str(target["database_url_env"]))
        tls_ca_raw = os.environ.get(str(target["tls_ca_env"]))
        if not source_git_sha or not database_url or not tls_ca_raw:
            pytest.skip("dedicated executor v2 PG17/TLS targets are not configured")
        configured[environment] = (database_url, Path(tls_ca_raw))

    initial_snapshot_roots = _snapshot_roots()
    description = _describe(source_git_sha)
    assert _snapshot_roots() == initial_snapshot_roots
    assert description["SOURCE_GIT_SHA"] == source_git_sha
    observations: dict[str, tuple[str, tuple[object, ...]]] = {}
    artifacts: dict[str, dict[str, object]] = {}
    for environment, (database_url, tls_ca_path) in configured.items():
        tls_info = tls_ca_path.lstat()
        assert stat.S_ISREG(tls_info.st_mode)
        assert stat.S_IMODE(tls_info.st_mode) == 0o600
        assert tls_info.st_nlink == 1
        assert tls_info.st_uid == os.geteuid()
        assert tls_info.st_gid == os.getegid()
        before = _database_observation(database_url, tls_ca_path)
        observations[environment] = before
        output_dir = tmp_path / environment.casefold()
        snapshot_roots_before_execution = _snapshot_roots()
        completed = _execute(
            environment=environment,
            source_git_sha=source_git_sha,
            description=description,
            database_url=database_url,
            tls_ca_path=tls_ca_path,
            system_identifier=before[0],
            output_dir=output_dir,
        )
        assert _snapshot_roots() == snapshot_roots_before_execution
        output = completed.stdout + completed.stderr
        assert completed.returncode == 8, output
        assert completed.stderr == ""
        assert completed.stdout == _successful_execution_output(
            environment, source_git_sha
        )
        for secret in (
            database_url,
            str(TARGETS[environment]["password"]),
            str(TARGETS[environment]["project_ref"]),
            before[0],
        ):
            assert secret not in output
        assert _database_observation(database_url, tls_ca_path) == before
        artifact_path = output_dir / materializer.ARTIFACT_BASENAMES[environment]
        assert artifact_path.is_file()
        assert stat.S_IMODE(artifact_path.stat().st_mode) == 0o600
        assert sorted(path.name for path in output_dir.iterdir()) == [
            materializer.ARTIFACT_BASENAMES[environment]
        ]
        artifact = json.loads(artifact_path.read_text(encoding="ascii"))
        assert artifact["artifact_state"] == "BLOCKED_DATA_INVARIANTS"
        assert artifact["environment_attestation_complete"] is False
        assert artifact["operational_authorization"] is False
        assert len(artifact["domains"]) == 14
        assert all(domain["state"] == "MATCH" for domain in artifact["domains"])
        assert artifact["unknown_owners"]["count"] == 0
        assert artifact["ledgers"] == {"native": "ABSENT", "public": "ABSENT"}
        invariant_states = {
            item["id"]: item["state"] for item in artifact["data_invariants"]
        }
        assert invariant_states == {
            "TENANT_FOREIGN_KEY_CONSISTENCY": "PASS",
            "TENANT_UNIQUENESS_GUARDS": "PASS",
            "APPEND_ONLY_AUDIT_INTEGRITY": "UNKNOWN",
            "IDEMPOTENCY_UNIQUENESS": "PASS",
            "CONSENT_LEDGER_INTEGRITY": "PASS",
            "BILLING_ISOLATION_INTEGRITY": "PASS",
            "RECOVERY_ARTIFACT_RETENTION": "UNKNOWN",
            "GOVERNANCE_DRAFT_INTEGRITY": "PASS",
        }
        assert {
            item["id"]: item["checks_executed"]
            for item in artifact["data_invariants"]
        } == {
            "TENANT_FOREIGN_KEY_CONSISTENCY": 12,
            "TENANT_UNIQUENESS_GUARDS": 14,
            "APPEND_ONLY_AUDIT_INTEGRITY": 5,
            "IDEMPOTENCY_UNIQUENESS": 24,
            "CONSENT_LEDGER_INTEGRITY": 3,
            "BILLING_ISOLATION_INTEGRITY": 19,
            "RECOVERY_ARTIFACT_RETENTION": 2,
            "GOVERNANCE_DRAFT_INTEGRITY": 2,
        }
        assert artifact["surfaces"] == {
            "data_api": "PLATFORM_SURFACES_UNATTESTED",
            "realtime": "PLATFORM_SURFACES_UNATTESTED",
        }
        serialized = _canonical_bytes(artifact).decode("ascii")
        assert database_url not in serialized
        assert before[0] not in serialized
        artifacts[environment] = artifact

    assert observations["DEV"][0] != observations["PROD"][0]
    assert (
        artifacts["DEV"]["pre_capture_binding"]["target_binding_sha256"]
        != artifacts["PROD"]["pre_capture_binding"]["target_binding_sha256"]
    )
    assert (
        artifacts["DEV"]["pre_capture_binding"]["hmac_sha256"]
        != artifacts["PROD"]["pre_capture_binding"]["hmac_sha256"]
    )
    assert _snapshot_roots() == initial_snapshot_roots


def test_executor_v2_rejects_cross_environment_ca_without_artifact(
    tmp_path: Path,
) -> None:
    source_git_sha = os.environ.get(SOURCE_GIT_SHA_ENV)
    dev_url = os.environ.get(str(TARGETS["DEV"]["database_url_env"]))
    dev_ca_raw = os.environ.get(str(TARGETS["DEV"]["tls_ca_env"]))
    prod_ca_raw = os.environ.get(str(TARGETS["PROD"]["tls_ca_env"]))
    if not source_git_sha or not dev_url or not dev_ca_raw or not prod_ca_raw:
        pytest.skip("dedicated executor v2 PG17/TLS targets are not configured")
    dev_ca = Path(dev_ca_raw)
    before = _database_observation(dev_url, dev_ca)
    output_dir = tmp_path / "wrong-ca"
    snapshot_roots_before_execution = _snapshot_roots()
    completed = _execute(
        environment="DEV",
        source_git_sha=source_git_sha,
        description=_describe(source_git_sha),
        database_url=dev_url,
        tls_ca_path=dev_ca,
        tls_ca_override_path=Path(prod_ca_raw),
        system_identifier=before[0],
        output_dir=output_dir,
    )
    assert _snapshot_roots() == snapshot_roots_before_execution
    assert completed.returncode == executor.DatabaseError.exit_code
    assert completed.stderr == ""
    assert completed.stdout == _connect_tls_failure_output("DEV", source_git_sha)
    for secret in (
        dev_url,
        str(TARGETS["DEV"]["password"]),
        str(TARGETS["DEV"]["project_ref"]),
        before[0],
    ):
        assert secret not in completed.stdout
    assert not (output_dir / materializer.ARTIFACT_BASENAMES["DEV"]).exists()
    assert _database_observation(dev_url, dev_ca) == before


def test_executor_v2_rejects_tls_hostname_mismatch_without_artifact(
    tmp_path: Path,
) -> None:
    source_git_sha = os.environ.get(SOURCE_GIT_SHA_ENV)
    dev_url = os.environ.get(str(TARGETS["DEV"]["database_url_env"]))
    dev_ca_raw = os.environ.get(str(TARGETS["DEV"]["tls_ca_env"]))
    if not source_git_sha or not dev_url or not dev_ca_raw:
        pytest.skip("dedicated executor v2 PG17/TLS DEV target is not configured")
    dev_ca = Path(dev_ca_raw)
    before = _database_observation(dev_url, dev_ca)
    wrong_hostname_url = dev_url.replace(
        str(TARGETS["DEV"]["project_ref"]), WRONG_HOST_PROJECT_REF
    )
    assert wrong_hostname_url != dev_url
    output_dir = tmp_path / "wrong-hostname"
    snapshot_roots_before_execution = _snapshot_roots()
    completed = _execute(
        environment="DEV",
        source_git_sha=source_git_sha,
        description=_describe(source_git_sha),
        database_url=wrong_hostname_url,
        tls_ca_path=dev_ca,
        system_identifier=before[0],
        output_dir=output_dir,
        project_ref_override=WRONG_HOST_PROJECT_REF,
    )
    assert _snapshot_roots() == snapshot_roots_before_execution
    assert completed.returncode == executor.DatabaseError.exit_code
    assert completed.stderr == ""
    assert completed.stdout == _connect_tls_failure_output("DEV", source_git_sha)
    for secret in (
        wrong_hostname_url,
        str(TARGETS["DEV"]["password"]),
        WRONG_HOST_PROJECT_REF,
        before[0],
    ):
        assert secret not in completed.stdout
    assert not (output_dir / materializer.ARTIFACT_BASENAMES["DEV"]).exists()
    assert _database_observation(dev_url, dev_ca) == before
