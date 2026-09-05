from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
INTENT_PATH = REPO_ROOT / "backend" / "scripts" / "private_runtime_intent_v2.py"
AUTHOR_PATH = REPO_ROOT / "backend" / "scripts" / "new_private_runtime_migration.py"
REPLAY_PATH = REPO_ROOT / "backend" / "scripts" / "replay_private_runtime_migration_pg17.py"
VERIFY_PATH = REPO_ROOT / "backend" / "scripts" / "verify_migration_history_divergence_remediation_proposal_v5.py"
sys.path.insert(0, str(INTENT_PATH.parent))


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


intent = _load(INTENT_PATH, "private_runtime_intent_v2_test")
author = _load(AUTHOR_PATH, "new_private_runtime_migration_test")
replay = _load(REPLAY_PATH, "replay_private_runtime_migration_test")
verifier = _load(VERIFY_PATH, "verify_migration_history_divergence_remediation_proposal_test")


def _complete_intent() -> dict[str, object]:
    value = intent.default_intent(
        basename="20260904_120000_private_runtime.policy.json",
        base_repository_sha="a" * 40,
    )
    value["decision_refs"] = [
        "docs/decisions/2026-09-04-private-runtime-migration-policy-v2.md"
    ]
    value["recovery"] = {
        "kind": "FORWARD_COMPENSATION",
        "reference": "docs/decisions/2026-09-04-private-runtime-migration-policy-v2.md",
    }
    # These are references required by the authoring contract only. They are
    # not presented as executed PG17 or cross-tenant evidence.
    value["pg17_test_nodeids"] = [
        "backend/tests/test_private_runtime_migration_policy.py::test_replay_api_is_fail_closed"
    ]
    value["cross_tenant_test_nodeids"] = list(value["pg17_test_nodeids"])
    return value


def test_v2_intent_is_closed_and_gates_are_false() -> None:
    value = _complete_intent()
    parsed = intent.validate_intent(value)
    assert parsed["scope"] == "PRIVATE_RUNTIME"
    assert parsed["artifact_id"] == "migration-authoring-intent-v2"
    assert parsed["operational_authorization"] is False
    assert parsed["next_stage_authorized"] is False
    with pytest.raises(intent.PrivateRuntimeIntentError):
        intent.validate_intent({**value, "unexpected": True})


def test_v2_rejects_nonclosed_direct_acl_entry() -> None:
    value = _complete_intent()
    value["private_runtime_controls"]["acl"]["direct_runtime_grants"] = [
        {"object": "agent_private", "grantee": "agent_runtime"}
    ]
    with pytest.raises(intent.PrivateRuntimeIntentError):
        intent.validate_intent(value)


def test_v2_rejects_gate_tampering_and_duplicate_grants() -> None:
    value = _complete_intent()
    with pytest.raises(intent.PrivateRuntimeIntentError):
        intent.validate_intent({**value, "operational_authorization": True})
    controls = value["private_runtime_controls"]
    grant = controls["acl"]["direct_runtime_grants"][0]
    controls["acl"]["direct_runtime_grants"] = [grant, dict(grant)]
    with pytest.raises(intent.PrivateRuntimeIntentError):
        intent.validate_intent(value)


def test_v2_render_is_not_a_catalog_migration() -> None:
    content = intent.render_draft(
        basename="20260904_120000_private_runtime.policy.json",
        base_repository_sha="a" * 40,
    )
    assert content.startswith(intent.INTENT_PREFIX.encode("ascii"))
    assert b"PASTORAI_MIGRATION_INTENT_V1" not in content
    assert b"MIGRATION_POLICY_DRAFT_INCOMPLETE" in content
    assert b"OPERATIONAL_AUTHORIZATION=BLOCKED" in content


def test_helper_and_projection_have_separate_security_contracts() -> None:
    controls = intent.default_private_runtime_controls()
    helper = controls["functions"][0]
    projection = controls["projection_function"]
    assert helper["identity"] == "agent_private.current_tenant_id()"
    assert helper["security_definer"] is False
    assert helper["search_path"] == ["pg_catalog"]
    assert helper["lifecycle"] == "EXISTING_HELPER"
    assert projection["identity"] == "agent_private.load_turn_context(uuid)"
    assert projection["security_definer"] is True
    assert projection["search_path"] == ["pg_catalog", "agent_private"]
    assert projection["lifecycle"] == "FUTURE_PROJECTION_CONTRACT"


def test_replay_api_is_fail_closed() -> None:
    before = replay.PrivateRuntimeSurface(None, None, (), (), (), (), ())
    with pytest.raises(replay.ReplayNotImplementedError):
        replay.validate_private_runtime_delta(before, before, _complete_intent())


def test_fake_cursor_is_never_touched_or_accepted() -> None:
    class FakeCursor:
        touched = False

        def execute(self, _sql: str) -> None:
            self.touched = True
            raise AssertionError("source-only policy touched a cursor")

    cursor = FakeCursor()
    with pytest.raises(replay.ReplayNotImplementedError):
        replay.capture_private_runtime_surface(cursor)
    with pytest.raises(replay.ReplayNotImplementedError):
        replay.validate_fresh_private_runtime_database(cursor)
    assert cursor.touched is False


def test_fake_snapshot_with_projection_or_acl_extra_is_not_evidence() -> None:
    fake = replay.PrivateRuntimeSurface(
        schema={"name": "agent_private"},
        runtime_role={"name": "agent_runtime"},
        memberships=(("agent_runtime", "other_role"),),
        functions=({"identity": "agent_private.load_turn_context(uuid)"},),
        relations=(),
        grants=({"object": "agent_private", "grantee": "PUBLIC", "privilege": "USAGE"},),
        config=(("agent_runtime", "search_path=public"),),
    )
    with pytest.raises(replay.ReplayNotImplementedError):
        replay.validate_private_runtime_delta(fake, fake, _complete_intent())


def test_dispatcher_keeps_v1_on_legacy_path_and_rejects_incomplete_v2() -> None:
    v1 = replay.dispatch_intent(b"-- PASTORAI_MIGRATION_INTENT_V1={}\n", basename="legacy.sql")
    assert v1.version == "V1" and v1.scope == "TENANT"
    content = intent.render_draft(
        basename="20260904_120000_private_runtime.policy.json",
        base_repository_sha="a" * 40,
    )
    with pytest.raises(replay.SourceContractError):
        replay.dispatch_intent(content, basename="20260904_120000_private_runtime.policy.json")


def test_disposable_url_validation_does_not_connect_or_accept_shared_hosts(monkeypatch) -> None:
    monkeypatch.setenv(
        replay.DATABASE_URL_ENV,
        "postgresql://postgres:secret@127.0.0.1:55432/migration_private_runtime_disposable",
    )
    assert replay._read_disposable_url().startswith("postgresql://")
    monkeypatch.setenv(
        replay.DATABASE_URL_ENV,
        "postgresql://postgres:secret@db.example/migration_private_runtime_disposable",
    )
    with pytest.raises(replay.TargetGuardError):
        replay._read_disposable_url()


def test_isolated_cli_entrypoints_load_sibling_modules_without_pythonpath() -> None:
    replay_run = subprocess.run(
        [sys.executable, "-I", "-P", str(REPLAY_PATH), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert replay_run.returncode == 2
    assert "ModuleNotFoundError" not in replay_run.stderr
    assert "--policy POLICY" in replay_run.stderr

    author_run = subprocess.run(
        [sys.executable, "-I", "-P", str(AUTHOR_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert author_run.returncode == 2
    assert "ModuleNotFoundError" not in author_run.stdout + author_run.stderr
    assert "OPERATIONAL_AUTHORIZATION=BLOCKED" in author_run.stdout


def test_v5_verifier_accepts_only_the_pinned_source_package() -> None:
    package = verifier.verify()
    assert package["status"] == "POLICY_ONLY_NOT_APPROVED"
    assert package["anchors"]["v4_proposal_sha256"] == verifier.V4_ANCHORS["v4_proposal_sha256"]


def test_v5_schema_shape_rejects_top_level_and_nested_extras() -> None:
    schema = verifier._load(verifier.SCHEMA_PATH)
    schema["properties"]["unexpected"] = {"const": True}
    with pytest.raises(RuntimeError):
        verifier._validate_schema_shape(schema)
    schema = verifier._load(verifier.SCHEMA_PATH)
    schema["properties"]["anchors"]["properties"]["unexpected"] = {"type": "string"}
    with pytest.raises(RuntimeError):
        verifier._validate_schema_shape(schema)
