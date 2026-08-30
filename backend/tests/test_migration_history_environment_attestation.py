"""Provas offline da atestacao sanitizada de schema em DEV e PROD."""

from __future__ import annotations

import ast
from contextlib import contextmanager, ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
from typing import Any, Iterator

import pytest

from scripts import materialize_migration_history_environment_attestation as materializer
from scripts import verify_migration_history_environment_attestation as verifier


REPO_ROOT = Path(__file__).resolve().parents[2]
MATERIALIZER_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "materialize_migration_history_environment_attestation.py"
)
VERIFIER_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "verify_migration_history_environment_attestation.py"
)
PREFLIGHT_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-environment-identity-preflight-v1.sql"
)
CAPTURE_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-environment-attestation-capture-v1.sql"
)
PROFILE_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-environment-attestation-profile-v1.json"
)
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-environment-attestation.schema.json"
)
PG17_WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "environment-attestation-pg17.yml"
)
KEY = b"k" * 32
AUTHORIZATION = hashlib.sha256(b"owner authorization dev").hexdigest()
NONCE = hashlib.sha256(b"single use nonce dev").hexdigest()
SYSTEM_IDENTIFIER = "1234567890123456789"
DATABASE_NAME = "pastorai_dev_attestation"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")


def _private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


@contextmanager
def _descriptor(raw: bytes) -> Iterator[int]:
    read_descriptor, write_descriptor = os.pipe()
    try:
        os.write(write_descriptor, raw)
    finally:
        os.close(write_descriptor)
    try:
        yield read_descriptor
    finally:
        os.close(read_descriptor)


def _authorization(label: str) -> str:
    return hashlib.sha256(f"authorization:{label}".encode("ascii")).hexdigest()


def _nonce(label: str) -> str:
    return hashlib.sha256(f"nonce:{label}".encode("ascii")).hexdigest()


def _target_descriptor(
    environment: str,
    *,
    authorization: str,
    system_identifier: str,
    database_name: str,
) -> dict[str, Any]:
    return {
        "authorization_record_sha256": authorization,
        "environment": environment,
        "expected_database_name_sha256": materializer._identity_component_sha256(
            "DATABASE_NAME", database_name
        ),
        "expected_project_ref_sha256": hashlib.sha256(
            f"project-ref:{environment}".encode("ascii")
        ).hexdigest(),
        "expected_system_identifier_sha256": materializer._identity_component_sha256(
            "SYSTEM_IDENTIFIER", system_identifier
        ),
        "target_binding_contract": materializer.TARGET_BINDING_CONTRACT,
    }


def _identity(
    *, system_identifier: str = SYSTEM_IDENTIFIER, database_name: str = DATABASE_NAME
) -> dict[str, Any]:
    return {
        "identity_contract": materializer.IDENTITY_CONTRACT,
        "system_identifier": system_identifier,
        "database_name": database_name,
        "server_version_num": 170006,
        "current_user_matches_session_user": True,
        "tls": True,
        "isolation_level": "repeatable read",
        "read_only": "on",
        "full_visibility": True,
    }


def _session_proof(
    *,
    system_identifier: str = SYSTEM_IDENTIFIER,
    database_name: str = DATABASE_NAME,
    backend_pid: int = 4242,
    snapshot: str = "100:200:150,151",
) -> dict[str, Any]:
    return {
        "backend_pid": backend_pid,
        "current_user_matches_session_user": True,
        "database_name": database_name,
        "full_visibility": True,
        "isolation_level": "repeatable read",
        "read_only": "on",
        "server_version_num": 170006,
        "snapshot": snapshot,
        "system_identifier": system_identifier,
        "tls": True,
    }


def _synthetic_profile(
    *, unknown_owner: bool = False,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    profile = json.loads(PROFILE_PATH.read_text(encoding="ascii"))
    entries_by_domain: dict[str, list[dict[str, Any]]] = {}
    domains: list[dict[str, Any]] = []
    for index, original in enumerate(profile["domains"]):
        entry: dict[str, Any] = {
            "domain": original["name"],
            "synthetic_ordinal": index,
        }
        if unknown_owner and index == 0:
            entry["owner_class"] = "UNKNOWN_OWNER"
        entries = [entry]
        entries_by_domain[original["name"]] = entries
        domains.append(
            {
                "comparison": original["comparison"],
                "entry_count": len(entries),
                "name": original["name"],
                "sha256": materializer.canonical._domain_sha256(
                    original["name"], entries
                ),
            }
        )
    profile["domains"] = domains
    return profile, entries_by_domain


def _invariants(
    profile: dict[str, Any],
    *,
    override_index: int | None = None,
    state: str = "PASS",
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for index, contract in enumerate(profile["data_invariants"]):
        current_state = "UNKNOWN" if index == 2 else "PASS"
        if index == override_index:
            current_state = state
        values.append(
            {
                "id": contract["id"],
                "state": current_state,
                "checks_executed": (
                    0 if current_state == "ERROR" else contract["checks_expected"]
                ),
                "violation_count": 1 if current_state == "FAIL" else 0,
            }
        )
    return values


def _structural_drift_invariants(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": contract["id"],
            "state": "UNKNOWN",
            "checks_executed": 0,
            "violation_count": 0,
        }
        for contract in profile["data_invariants"]
    ]


def _capture(
    profile: dict[str, Any],
    entries_by_domain: dict[str, list[dict[str, Any]]],
    *,
    system_identifier: str = SYSTEM_IDENTIFIER,
    database_name: str = DATABASE_NAME,
    session_proof: dict[str, Any] | None = None,
    ledgers: dict[str, str] | None = None,
    invariants: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "capture_contract": materializer.CAPTURE_CONTRACT,
        "system_identifier": system_identifier,
        "database_name": database_name,
        "server_version_num": 170006,
        "current_user_matches_session_user": True,
        "tls": True,
        "isolation_level": "repeatable read",
        "read_only": "on",
        "full_visibility": True,
        "session_proof": session_proof
        or _session_proof(
            system_identifier=system_identifier, database_name=database_name
        ),
        "domains": [
            {"name": item["name"], "entries": entries_by_domain[item["name"]]}
            for item in profile["domains"]
        ],
        "ledgers": ledgers or {"public": "ABSENT", "native": "PRESENT"},
    }


def _invariant_envelopes(
    profile: dict[str, Any],
    session_proof: dict[str, Any],
    invariants: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    values = invariants or _invariants(profile)
    return {
        contract["id"]: {
            "query_sha256": contract["query_sha256"],
            "result": value,
            "session_proof": copy.deepcopy(session_proof),
        }
        for contract, value in zip(profile["data_invariants"], values, strict=True)
    }


def _bind(
    output_dir: Path,
    *,
    environment: str,
    authorization: str,
    nonce: str,
    key: bytes,
    target: dict[str, Any],
    identity: dict[str, Any],
) -> Path:
    with (
        _descriptor(_canonical(target)) as target_fd,
        _descriptor(_canonical(identity)) as identity_fd,
        _descriptor(key) as key_fd,
    ):
        return materializer.bind_target(
            environment=environment,
            authorization_record=authorization,
            nonce=nonce,
            expected_target_fd=target_fd,
            identity_fd=identity_fd,
            hmac_key_fd=key_fd,
            output_dir=output_dir,
        )


def _materialize(
    output_dir: Path,
    *,
    environment: str,
    authorization: str,
    nonce: str,
    key: bytes,
    target: dict[str, Any],
    capture: dict[str, Any],
    invariant_envelopes: dict[str, dict[str, Any]] | None = None,
) -> tuple[Path, bool]:
    envelopes = (
        invariant_envelopes
        if invariant_envelopes is not None
        else _invariant_envelopes(
            json.loads(PROFILE_PATH.read_text(encoding="ascii")),
            capture["session_proof"],
        )
    )
    with ExitStack() as stack:
        target_fd = stack.enter_context(_descriptor(_canonical(target)))
        capture_fd = stack.enter_context(_descriptor(_canonical(capture)))
        key_fd = stack.enter_context(_descriptor(key))
        invariant_fds = {
            identifier: stack.enter_context(_descriptor(_canonical(envelope)))
            for identifier, envelope in envelopes.items()
        }
        return materializer.materialize(
            environment=environment,
            authorization_record=authorization,
            nonce=nonce,
            expected_target_fd=target_fd,
            metadata_capture_fd=capture_fd,
            hmac_key_fd=key_fd,
            invariant_result_fds=invariant_fds,
            output_dir=output_dir,
        )


def _make_artifact(
    output_dir: Path,
    profile: dict[str, Any],
    entries_by_domain: dict[str, list[dict[str, Any]]],
    *,
    environment: str,
    label: str,
) -> Path:
    authorization = _authorization(label)
    nonce = _nonce(label)
    key = hashlib.sha256(f"key:{label}".encode("ascii")).digest()
    system_identifier = str(1234567890123456700 + (1 if environment == "DEV" else 2))
    database_name = f"pastorai_{environment.casefold()}_attestation"
    target = _target_descriptor(
        environment,
        authorization=authorization,
        system_identifier=system_identifier,
        database_name=database_name,
    )
    _bind(
        output_dir,
        environment=environment,
        authorization=authorization,
        nonce=nonce,
        key=key,
        target=target,
        identity=_identity(
            system_identifier=system_identifier, database_name=database_name
        ),
    )
    capture = _capture(
        profile,
        entries_by_domain,
        system_identifier=system_identifier,
        database_name=database_name,
    )
    path, blocked = _materialize(
        output_dir,
        environment=environment,
        authorization=authorization,
        nonce=nonce,
        key=key,
        target=target,
        capture=capture,
        invariant_envelopes=_invariant_envelopes(
            profile, capture["session_proof"]
        ),
    )
    assert blocked is True
    return path


def _bind_default_dev(output_dir: Path) -> dict[str, Any]:
    target = _target_descriptor(
        "DEV",
        authorization=AUTHORIZATION,
        system_identifier=SYSTEM_IDENTIFIER,
        database_name=DATABASE_NAME,
    )
    _bind(
        output_dir,
        environment="DEV",
        authorization=AUTHORIZATION,
        nonce=NONCE,
        key=KEY,
        target=target,
        identity=_identity(),
    )
    return target


class _FakeCursor:
    def __init__(
        self,
        *,
        profile: dict[str, Any],
        proof: dict[str, Any],
        metadata: dict[str, Any],
        results: list[dict[str, Any]],
        fail_identifier: str | None = None,
        fail_mode: str = "recoverable",
        session_change_after_proofs: int | None = None,
    ) -> None:
        lines = CAPTURE_PATH.read_text(encoding="ascii").splitlines(keepends=True)
        self.transaction_open = materializer._extract_sql_block(
            lines, "transaction-open"
        )
        self.transaction_close = materializer._extract_sql_block(
            lines, "transaction-close"
        )
        self.proof_sql = materializer._extract_sql_block(lines, "session-proof")
        self.metadata_sql = materializer._extract_sql_block(
            lines, "metadata-capture"
        )
        self.invariant_sql = {
            contract["id"]: materializer._extract_sql_block(
                lines, f"invariant-data:{contract['id']}"
            )
            for contract in profile["data_invariants"]
        }
        self.results = {
            value["id"]: copy.deepcopy(value) for value in results
        }
        self.proof = copy.deepcopy(proof)
        self.metadata = copy.deepcopy(metadata)
        self.fail_identifier = fail_identifier
        self.fail_mode = fail_mode
        self.failed_once = False
        self.connection: _FakeConnection | None = None
        self.session_change_after_proofs = session_change_after_proofs
        self.proof_count = 0
        self.executed: list[str] = []
        self.closed = False
        self._pending: dict[str, Any] | None = None
        self._row_served = False

    def execute(self, sql: str) -> None:
        self.executed.append(sql)
        self._pending = None
        self._row_served = False
        if re.fullmatch(
            r"(?:SAVEPOINT|RELEASE SAVEPOINT) attestation_invariant_[1-8]", sql
        ):
            return
        if re.fullmatch(
            r"ROLLBACK TO SAVEPOINT attestation_invariant_[1-8]", sql
        ):
            if self.fail_mode == "rollback_failure":
                raise RuntimeError("private rollback failure detail")
            return
        if sql in {self.transaction_open, self.transaction_close}:
            if sql == self.transaction_close and self.fail_mode == "final_rollback_failure":
                raise RuntimeError("private final rollback failure detail")
            return
        if sql == self.proof_sql:
            self.proof_count += 1
            self._pending = copy.deepcopy(self.proof)
            if (
                self.session_change_after_proofs is not None
                and self.proof_count >= self.session_change_after_proofs
            ):
                self._pending["snapshot"] = "100:201:150,151"
            return
        if sql == self.metadata_sql:
            self._pending = copy.deepcopy(self.metadata)
            return
        for identifier, query in self.invariant_sql.items():
            if sql == query:
                if identifier == self.fail_identifier and not self.failed_once:
                    self.failed_once = True
                    sqlstate = {
                        "recoverable": "42703",
                        "timeout": "57014",
                        "transport": "08006",
                        "connection_closed": "42703",
                        "rollback_failure": "42703",
                        "final_rollback_failure": "42703",
                    }.get(self.fail_mode)
                    if self.fail_mode == "connection_closed" and self.connection:
                        self.connection.closed = True
                    raise _FakeDatabaseError(
                        "private database failure detail", sqlstate=sqlstate
                    )
                self._pending = copy.deepcopy(self.results[identifier])
                return
        raise AssertionError("unexpected SQL fragment")

    def fetchone(self) -> tuple[dict[str, Any]] | None:
        if self._pending is None or self._row_served:
            self._pending = None
            return None
        self._row_served = True
        return (copy.deepcopy(self._pending),)

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    autocommit = True

    def __init__(self, cursor: _FakeCursor) -> None:
        self.fake_cursor = cursor
        self.rollback_called = False
        self.closed = False
        cursor.connection = self

    def cursor(self) -> _FakeCursor:
        return self.fake_cursor

    def rollback(self) -> None:
        self.rollback_called = True


class _FakeDatabaseError(RuntimeError):
    def __init__(self, message: str, *, sqlstate: str | None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate
        self.pgcode = sqlstate


def _fake_capture_connection(
    profile: dict[str, Any],
    entries: dict[str, list[dict[str, Any]]],
    *,
    metadata_mismatch: bool = False,
    fail_identifier: str | None = None,
    fail_mode: str = "recoverable",
    session_change_after_proofs: int | None = None,
) -> _FakeConnection:
    observed_entries = copy.deepcopy(entries)
    if metadata_mismatch:
        first = profile["domains"][0]["name"]
        observed_entries[first][0]["synthetic_ordinal"] = 999
    metadata = _capture(profile, observed_entries)
    proof = metadata.pop("session_proof")
    cursor = _FakeCursor(
        profile=profile,
        proof=proof,
        metadata=metadata,
        results=_invariants(profile),
        fail_identifier=fail_identifier,
        fail_mode=fail_mode,
        session_change_after_proofs=session_change_after_proofs,
    )
    return _FakeConnection(cursor)


def _patch_capture_bundle(
    monkeypatch: pytest.MonkeyPatch, profile: dict[str, Any]
) -> None:
    lines = tuple(
        CAPTURE_PATH.read_text(encoding="ascii").splitlines(keepends=True)
    )
    monkeypatch.setattr(
        materializer,
        "_load_contract_bundle",
        lambda: materializer.ContractBundle(
            profile=copy.deepcopy(profile), capture_lines=lines
        ),
    )


def test_contract_files_are_byte_pinned_and_schema_matches_verifier() -> None:
    assert hashlib.sha256(PREFLIGHT_PATH.read_bytes()).hexdigest() == (
        materializer.PREFLIGHT_SQL_SHA256
    )
    assert hashlib.sha256(CAPTURE_PATH.read_bytes()).hexdigest() == (
        materializer.CAPTURE_SQL_SHA256
    )
    assert hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest() == (
        materializer.PROFILE_SHA256
    )
    assert hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest() == (
        materializer.SCHEMA_SHA256
    )
    profile = materializer._load_contracts()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="ascii"))
    assert profile["contract_version"] == materializer.CONTRACT_VERSION
    assert profile["target_binding"]["contract"] == (
        materializer.TARGET_BINDING_CONTRACT
    )
    assert set(schema["required"]) == verifier.TOP_LEVEL_KEYS
    assert set(schema["properties"]) == verifier.TOP_LEVEL_KEYS
    assert schema["additionalProperties"] is False


def test_json_schema_exactly_pins_runtime_domain_and_invariant_contracts() -> None:
    profile = json.loads(PROFILE_PATH.read_text(encoding="ascii"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="ascii"))
    properties = schema["properties"]

    invariants = properties["data_invariants"]
    assert invariants["items"] is False
    assert invariants["minItems"] == invariants["maxItems"] == 8
    assert len(invariants["prefixItems"]) == len(profile["data_invariants"]) == 8
    for item, contract in zip(
        invariants["prefixItems"], profile["data_invariants"], strict=True
    ):
        fixed = next(
            part["properties"]
            for part in item["allOf"]
            if "properties" in part and "id" in part["properties"]
        )
        assert fixed["id"] == {"const": contract["id"]}
        assert fixed["checks_executed"] == {
            "enum": [0, contract["checks_expected"]]
        }
        if contract["id"] == "APPEND_ONLY_AUDIT_INTEGRITY":
            assert fixed["state"] == {"const": "UNKNOWN"}
        else:
            pass_fail_guard = next(
                part
                for part in item["allOf"]
                if "if" in part and "then" in part
            )
            assert pass_fail_guard["if"]["properties"]["state"] == {
                "enum": ["PASS", "FAIL"]
            }
            assert pass_fail_guard["then"]["properties"]["checks_executed"] == {
                "const": contract["checks_expected"]
            }

    domains = properties["domains"]
    assert domains["items"] is False
    assert domains["minItems"] == domains["maxItems"] == 14
    assert len(domains["prefixItems"]) == len(profile["domains"]) == 14
    for item, contract in zip(
        domains["prefixItems"], profile["domains"], strict=True
    ):
        fixed = next(
            part["properties"]
            for part in item["allOf"]
            if "properties" in part and "name" in part["properties"]
        )
        assert fixed == {
            "comparison": {"const": contract["comparison"]},
            "expected_entry_count": {"const": contract["entry_count"]},
            "expected_sha256": {"const": contract["sha256"]},
            "name": {"const": contract["name"]},
        }

    assert set(schema["$defs"]["invariant"]["properties"]["state"]["enum"]) == {
        "PASS", "FAIL", "UNKNOWN", "ERROR"
    }
    assert set(properties["artifact_state"]["enum"]) == {
        "BLOCKED_DATA_INVARIANTS",
        "BLOCKED_PLATFORM_SURFACES_UNATTESTED",
        "BLOCKED_SCHEMA_METADATA_DIVERGENCE",
    }
    assert set(properties["ledgers"]["properties"]["public"]["enum"]) == {
        "ABSENT", "PRESENT", "INVALID", "UNKNOWN"
    }


def test_contract_drift_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    drifted = tmp_path / "profile.json"
    drifted.write_bytes(PROFILE_PATH.read_bytes() + b"\n")
    monkeypatch.setattr(materializer, "PROFILE_PATH", drifted)
    with pytest.raises(materializer.ContractError):
        materializer._load_contracts()


@pytest.mark.parametrize(
    "target_attribute",
    ["CAPTURE_SQL_PATH", "PROFILE_PATH", "SCHEMA_PATH", "PREFLIGHT_SQL_PATH"],
)
def test_contract_bundle_uses_validated_bytes_after_nominal_rename(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target_attribute: str
) -> None:
    contract_dir = _private_dir(tmp_path / "contracts")
    originals = {
        "CAPTURE_SQL_PATH": CAPTURE_PATH,
        "PROFILE_PATH": PROFILE_PATH,
        "SCHEMA_PATH": SCHEMA_PATH,
        "PREFLIGHT_SQL_PATH": PREFLIGHT_PATH,
    }
    isolated: dict[str, Path] = {}
    for attribute, source in originals.items():
        destination = contract_dir / source.name
        destination.write_bytes(source.read_bytes())
        destination.chmod(0o644)
        isolated[attribute] = destination
        monkeypatch.setattr(materializer, attribute, destination)

    attacked = isolated[target_attribute]
    original_bytes = attacked.read_bytes()
    real_reader = materializer._read_stable_nominal_file
    replaced = False

    def rename_after_validation(
        path: Path,
        maximum: int,
        *,
        private: bool,
        error: type[materializer.AttestationError],
    ) -> bytes:
        nonlocal replaced
        value = real_reader(path, maximum, private=private, error=error)
        if path == attacked and not replaced:
            replaced = True
            path.rename(path.with_name(f"{path.name}.validated"))
            path.write_bytes(b"X" + original_bytes[1:])
            path.chmod(0o644)
        return value

    monkeypatch.setattr(
        materializer, "_read_stable_nominal_file", rename_after_validation
    )
    bundle = materializer._load_contract_bundle()
    assert replaced is True
    assert bundle.profile["contract_version"] == materializer.CONTRACT_VERSION
    assert hashlib.sha256("".join(bundle.capture_lines).encode("utf-8")).hexdigest() == (
        materializer.CAPTURE_SQL_SHA256
    )
    assert attacked.read_bytes() != original_bytes


@pytest.mark.parametrize("script_path", [MATERIALIZER_PATH, VERIFIER_PATH])
def test_python_ast_has_no_database_network_environment_or_subprocess_access(
    script_path: Path,
) -> None:
    source = script_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    attributes: set[str] = set()
    called_names: set[str] = set()
    string_literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Attribute):
            attributes.add(node.attr)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_names.add(node.func.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            string_literals.append(node.value)
    assert not imported.intersection(
        {
            "asyncio",
            "http",
            "psycopg",
            "psycopg2",
            "requests",
            "socket",
            "sqlalchemy",
            "subprocess",
            "urllib",
        }
    )
    assert not attributes.intersection(
        {
            "connect",
            "environ",
            "getenv",
            "popen",
            "putenv",
            "spawnl",
            "spawnle",
            "spawnlp",
            "spawnlpe",
            "spawnv",
            "spawnve",
            "spawnvp",
            "spawnvpe",
            "system",
            "unsetenv",
            "urlopen",
        }
    )
    assert not called_names.intersection({"eval", "exec", "compile", "__import__"})
    assert not any(
        value == ".env" or value.startswith((".env.", ".env/"))
        for value in string_literals
    )
    assert "/proc" not in source


def _sql_without_comments_or_literals(sql: str) -> str:
    without_comments = re.sub(r"--[^\n]*", "", sql)
    return re.sub(r"'(?:''|[^'])*'", "''", without_comments)


@pytest.mark.parametrize(
    ("path", "expected_transactions"),
    [(PREFLIGHT_PATH, 1), (CAPTURE_PATH, 1)],
)
def test_sql_is_static_repeatable_read_read_only_and_has_no_mutating_statement(
    path: Path, expected_transactions: int
) -> None:
    sql = path.read_text(encoding="ascii")
    normalized = _sql_without_comments_or_literals(sql).casefold()
    assert "begin transaction isolation level repeatable read read only;" in sql
    assert re.search(r"(?m)^\s*rollback\s*;", sql)
    assert normalized.count(
        "begin transaction isolation level repeatable read read only;"
    ) == expected_transactions
    assert len(re.findall(r"(?m)^\s*rollback\s*;", normalized)) == expected_transactions
    assert "pg_catalog.set_config(''" in normalized
    assert not re.search(
        r"(?im)^\s*(insert|update|delete|merge|copy|call|do|create|alter|drop|"
        r"truncate|grant|revoke|vacuum|analyze|refresh|cluster|reindex)\b",
        normalized,
    )


def test_search_path_is_explicit_and_scoped_per_sql_contract() -> None:
    capture_sql = CAPTURE_PATH.read_text(encoding="ascii")
    preflight_sql = PREFLIGHT_PATH.read_text(encoding="ascii")
    capture_statement = (
        "select pg_catalog.set_config('search_path', "
        "'pg_catalog, public, agent_private', true);"
    )
    preflight_statement = (
        "select pg_catalog.set_config('search_path', 'pg_catalog', true);"
    )
    search_path_statement = re.compile(
        r"(?m)^select pg_catalog\.set_config\('search_path', [^\n;]+;\s*$"
    )
    assert search_path_statement.findall(capture_sql) == [capture_statement]
    assert search_path_statement.findall(preflight_sql) == [preflight_statement]
    assert capture_sql.count(capture_statement) == 1
    assert preflight_sql.count(preflight_statement) == 1
    profile = json.loads(PROFILE_PATH.read_text(encoding="ascii"))
    assert profile["invariant_execution"]["required_session"] == (
        "SAME_CONNECTION_REPEATABLE_READ_READ_ONLY_"
        "SEARCH_PATH_PG_CATALOG_PUBLIC_AGENT_PRIVATE"
    )


def test_pg17_workflow_is_digest_pinned_loopback_tls_and_dedicated() -> None:
    workflow = PG17_WORKFLOW_PATH.read_text(encoding="utf-8")
    image = (
        "postgres:17.6-trixie@sha256:"
        "00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929"
    )
    assert workflow.count(image) == 1
    assert workflow.count("--publish 127.0.0.1:55434:5432") == 1
    assert workflow.count(
        "postgresql://postgres:postgres@127.0.0.1:55434/"
        "canonical_schema_disposable_test"
    ) == 1
    assert workflow.count("POSTGRES_DB=canonical_schema_disposable_test") == 1
    assert workflow.count("PGSSLMODE: require") == 1
    assert "?sslmode=" not in workflow
    assert (
        'sudo chown 999:999 \\\n'
        '            "$RUNNER_TEMP/environment-attestation-tls" \\\n'
    ) in workflow
    assert re.findall(r"tests/test_[A-Za-z0-9_]+\.py", workflow) == [
        "tests/test_migration_history_environment_attestation.py",
        "tests/test_migration_history_environment_attestation_pg17.py",
    ]
    assert workflow.count("-m pytest") == 2
    assert "if: always()" in workflow
    assert "docker rm --force pastorai-environment-attestation-pg17" in workflow
    assert re.search(r"\b(?:DEV|PROD)\b", workflow) is None
    assert "54322" not in workflow


def test_capture_bundle_requires_exact_single_invariant_selection() -> None:
    profile = json.loads(PROFILE_PATH.read_text(encoding="ascii"))
    sql = CAPTURE_PATH.read_text(encoding="ascii").splitlines(keepends=True)
    assert profile["invariant_execution"]["bundle_execution"] == "FORBIDDEN"
    for invariant in profile["data_invariants"]:
        begin = f"-- invariant-data-begin:{invariant['id']}\n"
        end = f"-- invariant-data-end:{invariant['id']}\n"
        assert sql.count(begin) == 1
        assert sql.count(end) == 1
        first = sql.index(begin) + 1
        last = sql.index(end)
        assert hashlib.sha256("".join(sql[first:last]).encode("ascii")).hexdigest() == (
            invariant["query_sha256"]
        )


def test_capture_one_snapshot_executes_complete_contract_on_fake_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, entries = _synthetic_profile()
    _patch_capture_bundle(monkeypatch, profile)
    connection = _fake_capture_connection(profile, entries)
    metadata, envelopes = materializer.capture_one_snapshot(connection)
    cursor = connection.fake_cursor
    assert metadata["session_proof"] == _session_proof()
    assert len(envelopes) == 8
    assert [item["result"]["id"] for item in envelopes] == [
        item["id"] for item in profile["data_invariants"]
    ]
    assert all(
        item["session_proof"] == metadata["session_proof"] for item in envelopes
    )
    executed = "\n".join(cursor.executed).casefold()
    assert executed.count(
        "begin transaction isolation level repeatable read read only;"
    ) == 1
    assert len(re.findall(r"(?m)^\s*rollback\s*;", executed)) == 1
    assert all(query in cursor.executed for query in cursor.invariant_sql.values())
    assert cursor.closed is True
    assert connection.rollback_called is False


def test_capture_one_snapshot_metadata_mismatch_never_prepares_data_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, entries = _synthetic_profile()
    _patch_capture_bundle(monkeypatch, profile)
    connection = _fake_capture_connection(profile, entries, metadata_mismatch=True)
    _metadata, envelopes = materializer.capture_one_snapshot(connection)
    cursor = connection.fake_cursor
    assert all(item["result"]["state"] == "UNKNOWN" for item in envelopes)
    assert all(
        item["result"]["checks_executed"] == 0
        and item["result"]["violation_count"] == 0
        for item in envelopes
    )
    assert all(query not in cursor.executed for query in cursor.invariant_sql.values())
    assert cursor.executed.count(cursor.transaction_open) == 1
    assert cursor.executed.count(cursor.transaction_close) == 1
    assert cursor.closed is True


@pytest.mark.parametrize("fail_mode", ["recoverable", "timeout"])
def test_capture_one_snapshot_recoverable_sql_error_yields_error_and_continues(
    monkeypatch: pytest.MonkeyPatch, fail_mode: str
) -> None:
    profile, entries = _synthetic_profile()
    _patch_capture_bundle(monkeypatch, profile)
    failed = profile["data_invariants"][3]["id"]
    connection = _fake_capture_connection(
        profile, entries, fail_identifier=failed, fail_mode=fail_mode
    )
    _metadata, envelopes = materializer.capture_one_snapshot(connection)
    cursor = connection.fake_cursor
    failed_index = 3
    assert envelopes[failed_index]["result"] == {
        "id": failed,
        "state": "ERROR",
        "checks_executed": 0,
        "violation_count": 0,
    }
    assert cursor.invariant_sql[profile["data_invariants"][4]["id"]] in cursor.executed
    assert cursor.executed.count("ROLLBACK TO SAVEPOINT attestation_invariant_4") == 1
    assert cursor.executed.count("RELEASE SAVEPOINT attestation_invariant_4") == 1
    assert sum(item.startswith("SAVEPOINT attestation_invariant_") for item in cursor.executed) == 8
    assert "private database failure detail" not in json.dumps(envelopes)
    assert cursor.executed.count(cursor.transaction_open) == 1
    assert cursor.executed.count(cursor.transaction_close) == 1
    assert cursor.closed is True


@pytest.mark.parametrize(
    "fail_mode", ["transport", "connection_closed", "rollback_failure", "no_sqlstate"]
)
def test_capture_one_snapshot_connection_or_recovery_failure_aborts_without_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fail_mode: str
) -> None:
    profile, entries = _synthetic_profile()
    _patch_capture_bundle(monkeypatch, profile)
    failed = profile["data_invariants"][2]["id"]
    connection = _fake_capture_connection(
        profile, entries, fail_identifier=failed, fail_mode=fail_mode
    )
    output_dir = _private_dir(tmp_path / "no-artifact")
    with pytest.raises(materializer.CaptureError) as captured:
        materializer.capture_one_snapshot(connection)
    cursor = connection.fake_cursor
    assert cursor.executed.count(cursor.transaction_open) == 1
    assert cursor.executed.count(cursor.transaction_close) == 1
    assert cursor.closed is True
    assert str(captured.value) == ""
    assert list(output_dir.iterdir()) == []


def test_capture_one_snapshot_session_change_aborts_without_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile, entries = _synthetic_profile()
    _patch_capture_bundle(monkeypatch, profile)
    connection = _fake_capture_connection(
        profile, entries, session_change_after_proofs=3
    )
    output_dir = _private_dir(tmp_path / "no-session-artifact")
    with pytest.raises(materializer.CaptureError) as captured:
        materializer.capture_one_snapshot(connection)
    assert connection.fake_cursor.executed.count(
        connection.fake_cursor.transaction_close
    ) == 1
    assert str(captured.value) == ""
    assert list(output_dir.iterdir()) == []


def test_capture_one_snapshot_final_rollback_failure_aborts_without_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile, entries = _synthetic_profile()
    _patch_capture_bundle(monkeypatch, profile)
    connection = _fake_capture_connection(
        profile, entries, fail_mode="final_rollback_failure"
    )
    output_dir = _private_dir(tmp_path / "no-rollback-artifact")
    with pytest.raises(materializer.CaptureError) as captured:
        materializer.capture_one_snapshot(connection)
    assert connection.rollback_called is True
    assert connection.fake_cursor.closed is True
    assert str(captured.value) == ""
    assert list(output_dir.iterdir()) == []


def test_hmac_bind_and_materialize_produce_only_blocked_sanitized_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile, entries = _synthetic_profile()
    monkeypatch.setattr(materializer, "_load_contracts", lambda: copy.deepcopy(profile))
    output_dir = _private_dir(tmp_path / "evidence")
    target = _target_descriptor(
        "DEV",
        authorization=AUTHORIZATION,
        system_identifier=SYSTEM_IDENTIFIER,
        database_name=DATABASE_NAME,
    )
    receipt_path = _bind(
        output_dir,
        environment="DEV",
        authorization=AUTHORIZATION,
        nonce=NONCE,
        key=KEY,
        target=target,
        identity=_identity(),
    )
    assert receipt_path.name == materializer.BINDING_BASENAMES["DEV"]
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    capture = _capture(profile, entries)
    artifact_path, blocked = _materialize(
        output_dir,
        environment="DEV",
        authorization=AUTHORIZATION,
        nonce=NONCE,
        key=KEY,
        target=target,
        capture=capture,
        invariant_envelopes=_invariant_envelopes(
            profile, capture["session_proof"]
        ),
    )
    assert blocked is True
    assert stat.S_IMODE(artifact_path.stat().st_mode) == 0o600
    artifact = json.loads(artifact_path.read_text(encoding="ascii"))
    assert artifact["artifact_state"] == "BLOCKED_DATA_INVARIANTS"
    assert artifact["operational_authorization"] is False
    assert artifact["environment_attestation_complete"] is False
    assert artifact["surfaces"] == {
        "data_api": "PLATFORM_SURFACES_UNATTESTED",
        "realtime": "PLATFORM_SURFACES_UNATTESTED",
    }
    serialized = receipt_path.read_text(encoding="ascii") + artifact_path.read_text(
        encoding="ascii"
    )
    assert SYSTEM_IDENTIFIER not in serialized
    assert DATABASE_NAME not in serialized
    assert "database_name" not in serialized
    assert "system_identifier" not in serialized
    assert "postgresql://" not in serialized.casefold()


def test_dev_prod_pair_validates_blocked_and_rejects_swap_or_reuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile, entries = _synthetic_profile()
    monkeypatch.setattr(materializer, "_load_contracts", lambda: copy.deepcopy(profile))
    dev_path = _make_artifact(
        _private_dir(tmp_path / "dev"),
        profile,
        entries,
        environment="DEV",
        label="dev",
    )
    prod_path = _make_artifact(
        _private_dir(tmp_path / "prod"),
        profile,
        entries,
        environment="PROD",
        label="prod",
    )
    dev, prod = verifier.verify(dev_path, prod_path)
    assert dev["pre_capture_binding"]["environment"] == "DEV"
    assert prod["pre_capture_binding"]["environment"] == "PROD"
    with pytest.raises(verifier.ArtifactError):
        verifier.verify(prod_path, dev_path)

    prod_artifact = json.loads(prod_path.read_text(encoding="ascii"))
    prod_artifact["pre_capture_binding"]["target_binding_sha256"] = dev[
        "pre_capture_binding"
    ]["target_binding_sha256"]
    prod_path.write_bytes(_canonical(prod_artifact) + b"\n")
    prod_path.chmod(0o600)
    with pytest.raises(verifier.PairReuseError):
        verifier.verify(dev_path, prod_path)


def test_pair_cli_is_always_blocked_even_for_a_valid_pair(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile, entries = _synthetic_profile()
    monkeypatch.setattr(materializer, "_load_contracts", lambda: copy.deepcopy(profile))
    dev_path = _make_artifact(
        _private_dir(tmp_path / "dev"), profile, entries, environment="DEV", label="d"
    )
    prod_path = _make_artifact(
        _private_dir(tmp_path / "prod"), profile, entries, environment="PROD", label="p"
    )
    result = verifier.main(
        ["--dev-artifact", str(dev_path), "--prod-artifact", str(prod_path)]
    )
    output = capsys.readouterr()
    assert result == verifier.EnvironmentEvidenceBlocked.exit_code
    assert output.err == ""
    assert output.out == (
        f"{verifier.OPERATIONAL_BLOCK}\n"
        "ENVIRONMENT_ATTESTATION_COMPLETE=false\n"
        f"{verifier.SUCCESS}\n"
    )


def test_nested_duplicate_json_is_rejected_by_both_parsers() -> None:
    raw = b'{"outer":{"duplicate":1,"duplicate":2}}'
    with pytest.raises(materializer.InputError):
        materializer._json_loads(raw)
    with pytest.raises(verifier.ArtifactError):
        verifier._json_loads(raw)


def test_target_environment_and_authorization_mismatch_block_before_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile, _entries = _synthetic_profile()
    monkeypatch.setattr(materializer, "_load_contracts", lambda: copy.deepcopy(profile))
    target = _target_descriptor(
        "DEV",
        authorization=AUTHORIZATION,
        system_identifier=SYSTEM_IDENTIFIER,
        database_name=DATABASE_NAME,
    )
    cases = [
        ("PROD", AUTHORIZATION, _identity()),
        ("DEV", _authorization("wrong"), _identity()),
        (
            "DEV",
            AUTHORIZATION,
            _identity(system_identifier="9876543210987654321"),
        ),
    ]
    for index, (environment, authorization, identity) in enumerate(cases):
        output_dir = _private_dir(tmp_path / f"case-{index}")
        with pytest.raises(materializer.BindingError):
            _bind(
                output_dir,
                environment=environment,
                authorization=authorization,
                nonce=NONCE,
                key=KEY,
                target=target,
                identity=identity,
            )
        assert list(output_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("changed_nonce", "changed_key"),
    [(True, False), (False, True)],
)
def test_wrong_nonce_or_hmac_key_blocks_materialization_without_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    changed_nonce: bool,
    changed_key: bool,
) -> None:
    profile, entries = _synthetic_profile()
    monkeypatch.setattr(materializer, "_load_contracts", lambda: copy.deepcopy(profile))
    output_dir = _private_dir(tmp_path / "evidence")
    target = _target_descriptor(
        "DEV",
        authorization=AUTHORIZATION,
        system_identifier=SYSTEM_IDENTIFIER,
        database_name=DATABASE_NAME,
    )
    _bind(
        output_dir,
        environment="DEV",
        authorization=AUTHORIZATION,
        nonce=NONCE,
        key=KEY,
        target=target,
        identity=_identity(),
    )
    with pytest.raises(materializer.BindingError):
        capture = _capture(profile, entries)
        _materialize(
            output_dir,
            environment="DEV",
            authorization=AUTHORIZATION,
            nonce=_nonce("wrong") if changed_nonce else NONCE,
            key=(b"x" * 32) if changed_key else KEY,
            target=target,
            capture=capture,
            invariant_envelopes=_invariant_envelopes(
                profile, capture["session_proof"]
            ),
        )
    assert {path.name for path in output_dir.iterdir()} == {
        materializer.BINDING_BASENAMES["DEV"]
    }


@pytest.mark.parametrize("mode", ["metadata_only", "one_missing"])
def test_missing_invariant_result_blocks_without_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    profile, entries = _synthetic_profile()
    monkeypatch.setattr(materializer, "_load_contracts", lambda: copy.deepcopy(profile))
    output_dir = _private_dir(tmp_path / mode)
    target = _bind_default_dev(output_dir)
    capture = _capture(profile, entries)
    envelopes = _invariant_envelopes(profile, capture["session_proof"])
    if mode == "metadata_only":
        envelopes.clear()
    else:
        envelopes.pop(profile["data_invariants"][-1]["id"])
    with pytest.raises(materializer.UsageError):
        _materialize(
            output_dir,
            environment="DEV",
            authorization=AUTHORIZATION,
            nonce=NONCE,
            key=KEY,
            target=target,
            capture=capture,
            invariant_envelopes=envelopes,
        )
    assert {path.name for path in output_dir.iterdir()} == {
        materializer.BINDING_BASENAMES["DEV"]
    }


def test_duplicate_invariant_descriptor_is_rejected_before_read() -> None:
    identifier = "TENANT_FOREIGN_KEY_CONSISTENCY"
    with pytest.raises(materializer.UsageError):
        materializer._parse_invariant_descriptors(
            [f"{identifier}=30", f"{identifier}=31"]
        )


@pytest.mark.parametrize(
    "mutation", ["wrong_query_hash", "mixed_connection", "mixed_snapshot"]
)
def test_invariant_envelope_cannot_mix_query_connection_or_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    profile, entries = _synthetic_profile()
    monkeypatch.setattr(materializer, "_load_contracts", lambda: copy.deepcopy(profile))
    output_dir = _private_dir(tmp_path / mutation)
    target = _bind_default_dev(output_dir)
    capture = _capture(profile, entries)
    envelopes = _invariant_envelopes(profile, capture["session_proof"])
    identifier = profile["data_invariants"][0]["id"]
    if mutation == "wrong_query_hash":
        envelopes[identifier]["query_sha256"] = "f" * 64
    elif mutation == "mixed_connection":
        envelopes[identifier]["session_proof"]["backend_pid"] += 1
    else:
        envelopes[identifier]["session_proof"]["snapshot"] = "100:201:150,151"
    with pytest.raises(materializer.CaptureError):
        _materialize(
            output_dir,
            environment="DEV",
            authorization=AUTHORIZATION,
            nonce=NONCE,
            key=KEY,
            target=target,
            capture=capture,
            invariant_envelopes=envelopes,
        )
    assert not (output_dir / materializer.ARTIFACT_BASENAMES["DEV"]).exists()


def test_intermediate_invariant_error_is_materialized_as_blocked_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile, entries = _synthetic_profile()
    monkeypatch.setattr(materializer, "_load_contracts", lambda: copy.deepcopy(profile))
    output_dir = _private_dir(tmp_path / "intermediate-error")
    target = _bind_default_dev(output_dir)
    capture = _capture(profile, entries)
    values = _invariants(profile, override_index=0, state="ERROR")
    path, blocked = _materialize(
        output_dir,
        environment="DEV",
        authorization=AUTHORIZATION,
        nonce=NONCE,
        key=KEY,
        target=target,
        capture=capture,
        invariant_envelopes=_invariant_envelopes(
            profile, capture["session_proof"], values
        ),
    )
    artifact = json.loads(path.read_text(encoding="ascii"))
    assert blocked is True
    assert artifact["data_invariants"][0]["state"] == "ERROR"
    assert artifact["artifact_state"] == "BLOCKED_DATA_INVARIANTS"
    assert artifact["operational_authorization"] is False


@pytest.mark.parametrize("value", ["short", "g" * 64, "0" * 63])
def test_invalid_nonce_shape_is_rejected(value: str) -> None:
    with pytest.raises(materializer.BindingError):
        materializer._validate_nonce(value)


@pytest.mark.parametrize("key", [b"short", b"x" * 65])
def test_invalid_hmac_key_length_is_rejected(key: bytes) -> None:
    with _descriptor(key) as descriptor:
        with pytest.raises(materializer.BindingError):
            materializer._read_key(descriptor)


def test_read_fd_accepts_closed_pipe_and_private_stable_regular_file(
    tmp_path: Path,
) -> None:
    with _descriptor(b"pipe-payload") as descriptor:
        assert materializer._read_fd(descriptor, 64) == b"pipe-payload"

    path = tmp_path / "private-input"
    path.write_bytes(b"regular-payload")
    path.chmod(0o600)
    descriptor = os.open(path, os.O_RDONLY)
    try:
        assert materializer._read_fd(descriptor, 64) == b"regular-payload"
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("kind", ["socket", "device", "directory"])
def test_read_fd_rejects_non_allowlisted_descriptor_types(
    tmp_path: Path, kind: str
) -> None:
    peer: socket.socket | None = None
    if kind == "socket":
        source, peer = socket.socketpair()
        descriptor = source.detach()
    elif kind == "device":
        descriptor = os.open("/dev/null", os.O_RDONLY)
    else:
        descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        with pytest.raises(materializer.InputError):
            materializer._read_fd(descriptor, 64)
    finally:
        os.close(descriptor)
        if peer is not None:
            peer.close()


def test_read_fd_rejects_regular_file_mutated_during_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "mutable-input"
    path.write_bytes(b"stable-size-payload")
    path.chmod(0o600)
    descriptor = os.open(path, os.O_RDONLY)
    real_read = os.read
    mutated = False

    def mutate_after_first_read(fd: int, maximum: int) -> bytes:
        nonlocal mutated
        value = real_read(fd, maximum)
        if fd == descriptor and value and not mutated:
            mutated = True
            path.chmod(0o400)
        return value

    monkeypatch.setattr(materializer.os, "read", mutate_after_first_read)
    try:
        with pytest.raises(materializer.InputError):
            materializer._read_fd(descriptor, 64)
    finally:
        os.close(descriptor)


def test_unknown_owner_blocks_even_when_the_domain_digest_matches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile, entries = _synthetic_profile(unknown_owner=True)
    monkeypatch.setattr(materializer, "_load_contracts", lambda: copy.deepcopy(profile))
    output_dir = _private_dir(tmp_path / "unknown-owner")
    target = _target_descriptor(
        "DEV",
        authorization=AUTHORIZATION,
        system_identifier=SYSTEM_IDENTIFIER,
        database_name=DATABASE_NAME,
    )
    _bind(
        output_dir,
        environment="DEV",
        authorization=AUTHORIZATION,
        nonce=NONCE,
        key=KEY,
        target=target,
        identity=_identity(),
    )
    capture = _capture(profile, entries)
    invariants = _structural_drift_invariants(profile)
    path, _blocked = _materialize(
        output_dir,
        environment="DEV",
        authorization=AUTHORIZATION,
        nonce=NONCE,
        key=KEY,
        target=target,
        capture=capture,
        invariant_envelopes=_invariant_envelopes(
            profile, capture["session_proof"], invariants
        ),
    )
    artifact = json.loads(path.read_text(encoding="ascii"))
    assert artifact["unknown_owners"]["count"] == 1
    assert artifact["artifact_state"] == "BLOCKED_SCHEMA_METADATA_DIVERGENCE"
    assert all(domain["state"] == "MATCH" for domain in artifact["domains"])
    assert artifact["data_invariants"] == invariants
    assert "UNKNOWN_OWNER" not in path.read_text(encoding="ascii")


def test_domain_digest_mismatch_is_preserved_as_blocked_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile, entries = _synthetic_profile()
    monkeypatch.setattr(materializer, "_load_contracts", lambda: copy.deepcopy(profile))
    changed_entries = copy.deepcopy(entries)
    changed_entries[profile["domains"][0]["name"]][0]["synthetic_ordinal"] = 999
    output_dir = _private_dir(tmp_path / "domain-mismatch")
    target = _target_descriptor(
        "DEV",
        authorization=AUTHORIZATION,
        system_identifier=SYSTEM_IDENTIFIER,
        database_name=DATABASE_NAME,
    )
    _bind(
        output_dir,
        environment="DEV",
        authorization=AUTHORIZATION,
        nonce=NONCE,
        key=KEY,
        target=target,
        identity=_identity(),
    )
    capture = _capture(profile, changed_entries)
    invariants = _structural_drift_invariants(profile)
    path, _blocked = _materialize(
        output_dir,
        environment="DEV",
        authorization=AUTHORIZATION,
        nonce=NONCE,
        key=KEY,
        target=target,
        capture=capture,
        invariant_envelopes=_invariant_envelopes(
            profile, capture["session_proof"], invariants
        ),
    )
    artifact = json.loads(path.read_text(encoding="ascii"))
    assert artifact["domains"][0]["state"] == "MISMATCH"
    assert artifact["artifact_state"] == "BLOCKED_SCHEMA_METADATA_DIVERGENCE"
    assert artifact["data_invariants"] == invariants


@pytest.mark.parametrize("state", ["PASS", "FAIL", "UNKNOWN", "ERROR"])
def test_invariant_states_are_validated_and_preserved(state: str) -> None:
    profile, _entries = _synthetic_profile()
    values = _invariants(profile, override_index=0, state=state)
    result = materializer._validate_invariants(values, profile)
    assert result[0]["state"] == state
    assert result[0]["violation_count"] == (1 if state == "FAIL" else 0)


@pytest.mark.parametrize(
    ("state", "checks", "violations"),
    [
        ("PASS", 12, 1),
        ("FAIL", 12, 0),
        ("UNKNOWN", 12, 1),
        ("ERROR", 12, 1),
        ("PASS", 11, 0),
        ("FAIL", 11, 1),
    ],
)
def test_invariant_state_contradictions_fail_closed(
    state: str, checks: int, violations: int
) -> None:
    profile, _entries = _synthetic_profile()
    values = _invariants(profile)
    values[0] = {
        "id": profile["data_invariants"][0]["id"],
        "state": state,
        "checks_executed": checks,
        "violation_count": violations,
    }
    with pytest.raises(materializer.CaptureError):
        materializer._validate_invariants(values, profile)


@pytest.mark.parametrize("public", ["PRESENT", "INVALID", "UNKNOWN"])
def test_non_absent_public_ledger_blocks_schema_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, public: str
) -> None:
    profile, entries = _synthetic_profile()
    monkeypatch.setattr(materializer, "_load_contracts", lambda: copy.deepcopy(profile))
    output_dir = _private_dir(tmp_path / public.casefold())
    target = _target_descriptor(
        "DEV",
        authorization=AUTHORIZATION,
        system_identifier=SYSTEM_IDENTIFIER,
        database_name=DATABASE_NAME,
    )
    _bind(
        output_dir,
        environment="DEV",
        authorization=AUTHORIZATION,
        nonce=NONCE,
        key=KEY,
        target=target,
        identity=_identity(),
    )
    capture = _capture(
        profile, entries, ledgers={"public": public, "native": "PRESENT"}
    )
    path, _blocked = _materialize(
        output_dir,
        environment="DEV",
        authorization=AUTHORIZATION,
        nonce=NONCE,
        key=KEY,
        target=target,
        capture=capture,
        invariant_envelopes=_invariant_envelopes(
            profile, capture["session_proof"]
        ),
    )
    artifact = json.loads(path.read_text(encoding="ascii"))
    assert artifact["ledgers"]["public"] == public
    assert artifact["artifact_state"] == "BLOCKED_SCHEMA_METADATA_DIVERGENCE"


def test_invalid_ledger_value_blocks_before_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile, entries = _synthetic_profile()
    monkeypatch.setattr(materializer, "_load_contracts", lambda: copy.deepcopy(profile))
    output_dir = _private_dir(tmp_path / "bad-ledger")
    target = _target_descriptor(
        "DEV",
        authorization=AUTHORIZATION,
        system_identifier=SYSTEM_IDENTIFIER,
        database_name=DATABASE_NAME,
    )
    _bind(
        output_dir,
        environment="DEV",
        authorization=AUTHORIZATION,
        nonce=NONCE,
        key=KEY,
        target=target,
        identity=_identity(),
    )
    with pytest.raises(materializer.CaptureError):
        capture = _capture(
            profile,
            entries,
            ledgers={"public": "APPLIED", "native": "PRESENT"},
        )
        _materialize(
            output_dir,
            environment="DEV",
            authorization=AUTHORIZATION,
            nonce=NONCE,
            key=KEY,
            target=target,
            capture=capture,
            invariant_envelopes=_invariant_envelopes(
                profile, capture["session_proof"]
            ),
        )
    assert not (output_dir / materializer.ARTIFACT_BASENAMES["DEV"]).exists()


def test_output_directory_permissions_and_symlink_are_rejected(tmp_path: Path) -> None:
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o755)
    unsafe.chmod(0o755)
    with pytest.raises(materializer.OutputError):
        materializer._atomic_write(
            unsafe, "evidence.json", {"blocked": True}, allowed_existing=set()
        )

    private = _private_dir(tmp_path / "private")
    symlink = tmp_path / "private-link"
    symlink.symlink_to(private, target_is_directory=True)
    with pytest.raises(materializer.OutputError):
        materializer._atomic_write(
            symlink, "evidence.json", {"blocked": True}, allowed_existing=set()
        )


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    output_dir = _private_dir(tmp_path / "output")
    target = output_dir / "evidence.json"
    target.write_bytes(b"sentinel")
    target.chmod(0o600)
    with pytest.raises(materializer.OutputError):
        materializer._atomic_write(
            output_dir,
            target.name,
            {"blocked": True},
            allowed_existing={target.name},
        )
    assert target.read_bytes() == b"sentinel"
    assert sorted(path.name for path in output_dir.iterdir()) == [target.name]


@pytest.mark.parametrize(
    "attack", ["directory_replace", "directory_chmod", "target_tamper", "target_hardlink"]
)
def test_atomic_write_rejects_post_write_directory_and_target_attacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, attack: str
) -> None:
    output_dir = _private_dir(tmp_path / "atomic-output")
    target = output_dir / "evidence.json"
    displaced = tmp_path / "atomic-output-validated"
    attacker_link = output_dir / "attacker-hardlink"
    real_open_private_dir = materializer._open_private_dir
    calls = 0

    def attack_before_nominal_reopen(
        path: Path, allowed_existing: set[str]
    ) -> int:
        nonlocal calls
        calls += 1
        if path == output_dir and calls == 2:
            if attack == "directory_replace":
                output_dir.rename(displaced)
                output_dir.mkdir(mode=0o700)
                output_dir.chmod(0o700)
                target.write_bytes(b"attacker-sentinel")
                target.chmod(0o600)
            elif attack == "directory_chmod":
                output_dir.chmod(0o755)
            elif attack == "target_tamper":
                content = target.read_bytes()
                target.write_bytes(b"X" + content[1:])
                target.chmod(0o600)
            else:
                os.link(target, attacker_link)
        return real_open_private_dir(path, allowed_existing)

    monkeypatch.setattr(
        materializer, "_open_private_dir", attack_before_nominal_reopen
    )
    with pytest.raises(materializer.OutputError):
        materializer._atomic_write(
            output_dir,
            target.name,
            {"blocked": True},
            allowed_existing=set(),
        )
    assert calls == 2
    if attack == "directory_replace":
        assert target.read_bytes() == b"attacker-sentinel"
        assert not (displaced / target.name).exists()
    elif attack == "target_hardlink":
        assert not target.exists()
        assert attacker_link.is_file()
        assert attacker_link.stat().st_nlink == 1
    else:
        if output_dir.exists():
            output_dir.chmod(0o700)
        assert not target.exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_verifier_rejects_symlink_and_hardlinked_artifact(
    tmp_path: Path, kind: str
) -> None:
    real = tmp_path / "real.json"
    real.write_bytes(b"{}\n")
    real.chmod(0o600)
    candidate = tmp_path / materializer.ARTIFACT_BASENAMES["DEV"]
    if kind == "symlink":
        candidate.symlink_to(real)
    else:
        os.link(real, candidate)
    with pytest.raises(verifier.ArtifactError):
        verifier._read_artifact(candidate, candidate.name)


def test_private_receipt_hardlink_is_rejected(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(b"{}\n")
    receipt.chmod(0o600)
    os.link(receipt, tmp_path / "receipt-copy.json")
    with pytest.raises(materializer.InputError):
        materializer._read_private_json(receipt, 65_536)


@pytest.mark.parametrize(
    "attack", ["replacement_receipt", "same_size_rewrite", "parent_swap"]
)
def test_materialize_rejects_receipt_changed_after_private_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, attack: str
) -> None:
    profile, entries = _synthetic_profile()
    monkeypatch.setattr(materializer, "_load_contracts", lambda: copy.deepcopy(profile))
    output_dir = _private_dir(tmp_path / "receipt-race")
    displaced = tmp_path / "receipt-race-validated"
    target = _target_descriptor(
        "DEV",
        authorization=AUTHORIZATION,
        system_identifier=SYSTEM_IDENTIFIER,
        database_name=DATABASE_NAME,
    )
    _bind(
        output_dir,
        environment="DEV",
        authorization=AUTHORIZATION,
        nonce=NONCE,
        key=KEY,
        target=target,
        identity=_identity(),
    )
    receipt_path = output_dir / materializer.BINDING_BASENAMES["DEV"]
    original_bytes = receipt_path.read_bytes()
    replacement = json.loads(original_bytes)
    replacement["hmac_sha256"] = "f" * 64
    replacement_bytes = _canonical(replacement) + b"\n"
    assert len(replacement_bytes) == len(original_bytes)
    attacker_bytes = original_bytes if attack == "parent_swap" else replacement_bytes
    real_reader = materializer._read_private_json
    attacked = False

    def attack_after_private_read(path: Path, maximum: int) -> Any:
        nonlocal attacked
        value = real_reader(path, maximum)
        if path == receipt_path and not attacked:
            attacked = True
            if attack == "replacement_receipt":
                path.rename(output_dir / "receipt.validated.json")
            elif attack == "parent_swap":
                output_dir.rename(displaced)
                output_dir.mkdir(mode=0o700)
                output_dir.chmod(0o700)
            path.write_bytes(attacker_bytes)
            path.chmod(0o600)
        return value

    monkeypatch.setattr(materializer, "_read_private_json", attack_after_private_read)
    capture = _capture(profile, entries)
    with pytest.raises(materializer.AttestationError) as captured:
        _materialize(
            output_dir,
            environment="DEV",
            authorization=AUTHORIZATION,
            nonce=NONCE,
            key=KEY,
            target=target,
            capture=capture,
            invariant_envelopes=_invariant_envelopes(
                profile, capture["session_proof"]
            ),
        )
    assert attacked is True
    assert str(captured.value) == ""
    assert "f" * 64 not in str(captured.value)
    assert receipt_path.read_bytes() == attacker_bytes
    artifact_name = materializer.ARTIFACT_BASENAMES["DEV"]
    partial_name = f".{artifact_name}.partial"
    for directory in (output_dir, displaced):
        if directory.exists():
            assert not (directory / artifact_name).exists()
            assert not (directory / partial_name).exists()


@pytest.mark.parametrize("attack", ["receipt_rename", "parent_swap"])
def test_private_receipt_nominal_rename_or_parent_swap_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, attack: str
) -> None:
    parent = _private_dir(tmp_path / "receipts")
    receipt = parent / "receipt.json"
    original = b'{"value":1}\n'
    replacement = b'{"value":2}\n'
    assert len(original) == len(replacement)
    receipt.write_bytes(original)
    receipt.chmod(0o600)
    original_inode = receipt.stat().st_ino
    real_read = os.read
    attacked = False

    def swap_after_first_read(descriptor: int, maximum: int) -> bytes:
        nonlocal attacked
        value = real_read(descriptor, maximum)
        if (
            value
            and not attacked
            and os.fstat(descriptor).st_ino == original_inode
        ):
            attacked = True
            if attack == "receipt_rename":
                receipt.rename(parent / "receipt.validated.json")
            else:
                displaced = parent.with_name("receipts-validated")
                parent.rename(displaced)
                parent.mkdir(mode=0o700)
                parent.chmod(0o700)
            receipt.write_bytes(replacement)
            receipt.chmod(0o600)
        return value

    monkeypatch.setattr(materializer.os, "read", swap_after_first_read)
    with pytest.raises(materializer.InputError):
        materializer._read_private_json(receipt, 65_536)
    assert attacked is True


def test_verifier_rejects_same_size_artifact_rename_during_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parent = _private_dir(tmp_path / "artifacts")
    artifact = parent / materializer.ARTIFACT_BASENAMES["DEV"]
    original = b'{"value":1}\n'
    replacement = b'{"value":2}\n'
    assert len(original) == len(replacement)
    artifact.write_bytes(original)
    artifact.chmod(0o600)
    original_inode = artifact.stat().st_ino
    real_read = os.read
    attacked = False

    def rename_after_first_read(descriptor: int, maximum: int) -> bytes:
        nonlocal attacked
        value = real_read(descriptor, maximum)
        if (
            value
            and not attacked
            and os.fstat(descriptor).st_ino == original_inode
        ):
            attacked = True
            artifact.rename(parent / "artifact.validated.json")
            artifact.write_bytes(replacement)
            artifact.chmod(0o600)
        return value

    monkeypatch.setattr(materializer.os, "read", rename_after_first_read)
    with pytest.raises(verifier.ArtifactError):
        verifier._read_artifact(artifact, artifact.name)
    assert attacked is True


def test_verifier_detects_same_size_toctou_rewrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parent = _private_dir(tmp_path / "rewrite")
    artifact = parent / materializer.ARTIFACT_BASENAMES["DEV"]
    artifact.write_bytes(b'{"value":1}\n')
    artifact.chmod(0o600)
    original_inode = artifact.stat().st_ino
    real_read = os.read
    changed = False

    def rewrite_after_read(descriptor: int, maximum: int) -> bytes:
        nonlocal changed
        raw = real_read(descriptor, maximum)
        if (
            raw
            and not changed
            and os.fstat(descriptor).st_ino == original_inode
        ):
            changed = True
            before = artifact.stat().st_mtime_ns
            artifact.write_bytes(b'{"value":2}\n')
            os.utime(artifact, ns=(before + 1, before + 1))
        return raw

    monkeypatch.setattr(materializer.os, "read", rewrite_after_read)
    with pytest.raises(verifier.ArtifactError):
        verifier._read_artifact(artifact, artifact.name)
    assert changed is True


def test_error_messages_never_echo_cli_or_raw_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "postgresql://private-user:private-password@private-host/db"
    assert materializer.main(["bind-target", "--unknown", secret]) == (
        materializer.UsageError.exit_code
    )
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert secret not in output

    profile, _entries = _synthetic_profile()
    monkeypatch.setattr(materializer, "_load_contracts", lambda: copy.deepcopy(profile))
    output_dir = _private_dir(tmp_path / "sanitized")
    target = _target_descriptor(
        "DEV",
        authorization=AUTHORIZATION,
        system_identifier="9876543210987654321",
        database_name="private_database_marker",
    )
    with (
        _descriptor(_canonical(target)) as target_fd,
        _descriptor(_canonical(_identity())) as identity_fd,
        _descriptor(KEY) as key_fd,
    ):
        result = materializer.main(
            [
                "bind-target",
                "--environment",
                "DEV",
                "--expected-target-fd",
                str(target_fd),
                "--identity-fd",
                str(identity_fd),
                "--authorization-record-sha256",
                AUTHORIZATION,
                "--nonce",
                NONCE,
                "--hmac-key-fd",
                str(key_fd),
                "--output-dir",
                str(output_dir),
                "--confirmation",
                materializer.CONFIRMATIONS["DEV"],
            ]
        )
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert result == materializer.BindingError.exit_code
    assert SYSTEM_IDENTIFIER not in text
    assert DATABASE_NAME not in text
    assert "9876543210987654321" not in text
    assert "private_database_marker" not in text
    assert list(output_dir.iterdir()) == []
