from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import ssl
from types import ModuleType
from typing import Any, Callable

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "verify_dev_connect_tls_auth_transport_probe_plan.py"
)
PLAN_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "dev-connect-tls-auth-transport-probe-plan-v1.json"
)
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "dev-connect-tls-auth-transport-probe-plan.schema.json"
)
SCHEMA_SHA256 = "431b413ff8c14ea331269116b13e7ebf1f1f9cdb80ddf7b23c8182c2437648bb"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "dev_connect_tls_auth_transport_probe_plan_verifier", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_plan() -> dict[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def _write_artifacts(
    tmp_path: Path,
    plan: dict[str, Any],
    *,
    schema_raw: bytes | None = None,
) -> tuple[Path, Path]:
    root = tmp_path / "artifacts"
    root.mkdir(mode=0o755)
    plan_path = root / PLAN_PATH.name
    schema_path = root / SCHEMA_PATH.name
    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    schema_path.write_bytes(SCHEMA_PATH.read_bytes() if schema_raw is None else schema_raw)
    plan_path.chmod(0o644)
    schema_path.chmod(0o644)
    return plan_path, schema_path


def test_plan_verifies_offline_and_remains_disabled(capsys: Any) -> None:
    module = _load_module()

    assert module.main([]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.splitlines() == [
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "EXECUTION_DISABLED=true",
        "ROOT_CAUSE=UNDETERMINED",
        "NEXT_STAGE_AUTHORIZED=false",
        "DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_PLAN_VERIFIED_OFFLINE",
    ]


def test_verification_cannot_open_dns_tcp_tls_or_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("external capability invoked")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(ssl, "SSLContext", forbidden)

    assert module.main([]) == 0


def test_verifier_import_and_call_graph_has_no_external_capability() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    imports: set[str] = set()
    calls: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)

    assert imports <= {
        "__future__",
        "argparse",
        "hashlib",
        "json",
        "pathlib",
        "re",
        "stat",
        "sys",
    }
    assert imports.isdisjoint(
        {
            "asyncio",
            "http",
            "httpx",
            "os",
            "psycopg",
            "psycopg2",
            "requests",
            "socket",
            "ssl",
            "subprocess",
            "urllib",
        }
    )
    assert calls.isdisjoint(
        {
            "connect",
            "create_connection",
            "getaddrinfo",
            "gethostbyname",
            "Popen",
            "run",
            "socket",
            "urlopen",
            "wrap_socket",
        }
    )


def test_historical_result_preserves_only_sanitized_frontier() -> None:
    plan = _load_plan()

    assert plan["historical_result"] == {
        "environment": "DEV",
        "repository_main_sha": "bab031a7e0067a257eedb4a24c786cc925801463",
        "runner_sha256": (
            "8da631fbb602488bb8c82ce1529c9d8ba17acbae8a318ea9b0fc24cdd8f65cd2"
        ),
        "sql_sha256": (
            "001bfda9b4655d028abfb7d8f44ac6c4e5ab51861c9623dd54b1cdd0ab6ea336"
        ),
        "precise_timestamp_preserved": False,
        "exit_code": 7,
        "sanitized_output": {
            "ENVIRONMENT": "DEV",
            "OPERATIONAL_AUTHORIZATION": False,
            "NEXT_STAGE_AUTHORIZED": False,
            "CAPTURE_EXECUTED": False,
            "MATERIALIZATION_EXECUTED": False,
            "PROD_ACCESSED": False,
            "SINGLE_USE_SCOPE": "PROCESS_INVOCATION_ONLY",
            "ROLLBACK_CONFIRMED": False,
            "CONNECTION_CLOSED": True,
            "PREFLIGHT_FAILURE_PHASE": "CONNECT_TLS_AUTH",
            "RESULT": "BLOCKED_DATABASE_PREFLIGHT_FAILED",
        },
    }
    assert plan["interpretation_boundary"]["root_cause"] == "UNDETERMINED"
    assert len(plan["interpretation_boundary"]["establishes_only"]) == 1
    assert set(plan["interpretation_boundary"]["does_not_establish"]) == {
        "DNS_SUCCESS_OR_FAILURE",
        "TCP_SUCCESS_OR_FAILURE",
        "TLS_SUCCESS_OR_FAILURE",
        "CA_VALIDITY_OR_INVALIDITY",
        "ENDPOINT_AVAILABILITY",
        "CONNECTION_ESTABLISHED",
        "CREDENTIAL_VALIDITY_OR_INVALIDITY",
        "AUTHENTICATION_ATTEMPTED",
        "DATABASE_SESSION_ESTABLISHED",
        "TRANSACTION_STARTED",
        "PROJECT_IDENTITY",
    }


def test_future_probe_is_a_non_executable_transport_contract() -> None:
    plan = _load_plan()
    contract = plan["future_probe_contract"]

    assert plan["execution_mode"] == "OFFLINE_PLAN_ONLY"
    assert plan["execution_disabled"] is True
    assert plan["operational_authorization"] is False
    assert plan["next_stage_authorized"] is False
    assert contract["implementation_present"] is False
    assert contract["network_capability_present"] is False
    assert contract["execution_disabled"] is True
    assert contract["wire_contract"] == {
        "postgres_sslrequest_hex": "0000000804d2162f",
        "required_server_response": "S",
        "startup_message_allowed": False,
        "authentication_allowed": False,
        "database_session_allowed": False,
        "sql_allowed": False,
    }
    assert contract["dns_and_address_policy"]["resolve_count_max"] == 1
    assert contract["dns_and_address_policy"]["retry_allowed"] is False
    assert contract["dns_and_address_policy"]["fallback_allowed"] is False
    assert contract["tls_policy"]["mode"] == "VERIFY_FULL_EXPLICIT_CA"
    assert contract["input_policy"]["private_descriptor_only"] is True
    assert contract["input_policy"]["password_allowed"] is False
    assert contract["output_policy"]["logs_accessed"] is False
    assert contract["output_policy"]["local_persistence_allowed"] is False
    assert all(value is False for value in plan["mission_evidence"].values())
    assert plan["next_gate"] == (
        "REVIEW_AND_CI_DEV_CONNECT_TLS_AUTH_OFFLINE_DIAGNOSTICS_PR"
    )


def _set_nested(*keys: str, value: object) -> Callable[[dict[str, Any]], None]:
    def mutate(plan: dict[str, Any]) -> None:
        target = plan
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value

    return mutate


@pytest.mark.parametrize(
    "mutation",
    [
        _set_nested("execution_disabled", value=False),
        _set_nested("operational_authorization", value=True),
        _set_nested("interpretation_boundary", "root_cause", value="PASSWORD"),
        _set_nested(
            "historical_result",
            "sanitized_output",
            "PREFLIGHT_FAILURE_PHASE",
            value="DNS_RESOLUTION",
        ),
        _set_nested(
            "future_probe_contract",
            "network_capability_present",
            value=True,
        ),
        _set_nested(
            "future_probe_contract",
            "wire_contract",
            "authentication_allowed",
            value=True,
        ),
        _set_nested(
            "future_probe_contract",
            "dns_and_address_policy",
            "retry_allowed",
            value=True,
        ),
        _set_nested(
            "future_probe_contract",
            "tls_policy",
            "system_ca_fallback_allowed",
            value=True,
        ),
        _set_nested(
            "future_probe_contract",
            "input_policy",
            "password_allowed",
            value=True,
        ),
        _set_nested(
            "future_probe_contract",
            "output_policy",
            "raw_hostname_allowed",
            value=True,
        ),
        _set_nested("mission_evidence", "network_accessed", value=True),
        _set_nested("next_stage_authorized", value=True),
    ],
)
def test_security_critical_mutations_fail_closed(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    capsys: Any,
) -> None:
    module = _load_module()
    plan = copy.deepcopy(_load_plan())
    mutation(plan)
    plan_path, schema_path = _write_artifacts(tmp_path, plan)

    assert module.main(["--plan", str(plan_path), "--schema", str(schema_path)]) == 5
    output = capsys.readouterr()
    assert "PLAN_CONTRACT_INVALID" in output.err
    assert "PASSWORD" not in output.err
    assert str(tmp_path) not in output.err


def test_additional_raw_target_identifier_fails_closed(
    tmp_path: Path, capsys: Any
) -> None:
    module = _load_module()
    plan = _load_plan()
    plan["future_probe_contract"]["target_contract"]["raw_hostname"] = (
        "forbidden.example"
    )
    plan_path, schema_path = _write_artifacts(tmp_path, plan)

    assert module.main(["--plan", str(plan_path), "--schema", str(schema_path)]) == 5
    output = capsys.readouterr()
    assert output.err.strip() == (
        "OFFLINE_PROBE_PLAN_VERIFICATION_BLOCKED:PLAN_CONTRACT_INVALID"
    )
    assert "forbidden.example" not in output.err


def test_schema_is_closed_and_digest_bound() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    plan = _load_plan()

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest() == SCHEMA_SHA256
    assert plan["schema_binding"] == {
        "algorithm": "SHA-256",
        "sha256": SCHEMA_SHA256,
    }


def test_schema_drift_is_rejected(tmp_path: Path, capsys: Any) -> None:
    module = _load_module()
    schema_raw = SCHEMA_PATH.read_bytes().replace(
        b"offline transport probe plan", b"altered transport probe plan", 1
    )
    plan_path, schema_path = _write_artifacts(
        tmp_path, _load_plan(), schema_raw=schema_raw
    )

    assert module.main(["--plan", str(plan_path), "--schema", str(schema_path)]) == 4
    output = capsys.readouterr()
    assert output.err.strip() == "OFFLINE_PROBE_PLAN_VERIFICATION_BLOCKED:SCHEMA_DRIFT"


def test_duplicate_json_key_is_rejected(tmp_path: Path, capsys: Any) -> None:
    module = _load_module()
    plan_path, schema_path = _write_artifacts(tmp_path, _load_plan())
    raw = plan_path.read_text(encoding="utf-8").replace(
        '  "execution_disabled": true,',
        '  "execution_disabled": true,\n  "execution_disabled": true,',
        1,
    )
    plan_path.write_text(raw, encoding="utf-8")
    plan_path.chmod(0o644)

    assert module.main(["--plan", str(plan_path), "--schema", str(schema_path)]) == 3
    output = capsys.readouterr()
    assert output.err.strip() == (
        "OFFLINE_PROBE_PLAN_VERIFICATION_BLOCKED:ARTIFACT_INVALID"
    )


def test_symlink_plan_is_rejected(tmp_path: Path, capsys: Any) -> None:
    module = _load_module()
    plan_path, schema_path = _write_artifacts(tmp_path, _load_plan())
    real_path = plan_path.with_name("real-plan.json")
    plan_path.rename(real_path)
    plan_path.symlink_to(real_path.name)

    assert module.main(["--plan", str(plan_path), "--schema", str(schema_path)]) == 3
    output = capsys.readouterr()
    assert output.err.strip() == (
        "OFFLINE_PROBE_PLAN_VERIFICATION_BLOCKED:ARTIFACT_INVALID"
    )
