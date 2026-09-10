"""Checagens source-only do candidato C3, sem executar SQL ou abrir banco."""

from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "20260910_142830_add_e4b_consent_persistence.sql"
SPEC = ROOT.parent / "docs" / "superpowers" / "specs" / "2026-09-10-e4b-c3-persistence-specification.md"
PG17_TEST = ROOT / "tests" / "test_e4b_consent_persistence_pg17.py"
REPLAY = ROOT / "scripts" / "replay_migration_catalog_current_head_pg17.py"

EXPECTED_RELATIONS = [
    "public.e4b_consent_hold_events",
    "public.e4b_consent_holds",
    "public.e4b_consent_operations",
    "public.e4b_consent_receipts",
    "public.e4b_consent_retentions",
    "public.e4b_consent_streams",
]
EXPECTED_NODEIDS = [
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_catalog_001_matches_r4_manifest",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_parent_001_requires_synthetic_parent_anchors",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_rls_001_enforces_force_and_tenant_policies",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_guc_001_exercises_positive_and_negative_tenant_matrix",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_acl_001_verifies_revokes_and_ephemeral_memberships",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_dataapi_001_denies_known_roles_without_guc",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_chain_001_commits_complete_chain_and_rejects_partial",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_chain_002_rejects_invalid_withdraw_origins_and_streams",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_replay_001_rehydrates_exact_and_conflicts_tenant_scoped",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_imm_001_rejects_immutable_updates_and_deletes",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_imm_002_allows_only_stream_hold_retention_transitions",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_auth_001_validates_historical_operator_role_links",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_ret_001_validates_confirmed_at_and_utc_retention",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_hold_001_projects_holds_and_serializes_subject",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_lock_001_orders_tenant_scoped_advisory_locks",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_rollback_001_removes_partial_state_and_releases_locks",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_commit_001_reconciles_precommit_and_uncertain_commit",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_noskip_001_collects_exact_oracle_manifest",
]
EXPECTED_CROSS_TENANT_NODEIDS = [
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_rls_001_enforces_force_and_tenant_policies",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_guc_001_exercises_positive_and_negative_tenant_matrix",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_chain_002_rejects_invalid_withdraw_origins_and_streams",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_replay_001_rehydrates_exact_and_conflicts_tenant_scoped",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_lock_001_orders_tenant_scoped_advisory_locks",
    "backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_commit_001_reconciles_precommit_and_uncertain_commit",
]
EXPECTED_DECISION_REFS = [
    "docs/decisions/2026-08-28-d2b2b1-consent-security-boundary.md",
    "docs/decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md",
]


def _migration_source() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _intent() -> dict[str, object]:
    first_line = _migration_source().splitlines()[0]
    return json.loads(first_line.removeprefix("-- PASTORAI_MIGRATION_INTENT_V1="))


def test_e4b_migration_intent_is_complete_tenant_v1() -> None:
    intent = _intent()

    assert set(intent) == {
        "affected_relations",
        "artifact_id",
        "base_repository_sha",
        "cross_tenant_test_nodeids",
        "decision_refs",
        "global_justification",
        "migration_basename",
        "next_stage_authorized",
        "operational_authorization",
        "pg17_test_nodeids",
        "recovery",
        "scope",
        "tenant_controls",
    }
    assert intent["affected_relations"] == EXPECTED_RELATIONS
    assert intent["scope"] == "TENANT"
    assert intent["global_justification"] is None
    assert intent["operational_authorization"] is False
    assert intent["next_stage_authorized"] is False
    assert intent["pg17_test_nodeids"] == EXPECTED_NODEIDS
    assert intent["cross_tenant_test_nodeids"] == EXPECTED_CROSS_TENANT_NODEIDS
    assert intent["decision_refs"] == EXPECTED_DECISION_REFS
    assert intent["tenant_controls"] == {
        "acl_review": "EXPLICIT_GRANTS_AND_REVOKES",
        "enable_rls": True,
        "force_rls": True,
        "igreja_id_column": "igreja_id",
        "policy_context": "app.tenant_igreja_id",
    }
    assert intent["recovery"] == {
        "kind": "FORWARD_COMPENSATION",
        "reference": "docs/decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md",
    }


def test_e4b_migration_owns_exactly_six_relations_and_five_internal_functions() -> None:
    source = _migration_source()

    assert re.findall(r"^create table public\.(e4b_consent_[a-z_]+) \(", source, re.M) == [
        "e4b_consent_operations",
        "e4b_consent_streams",
        "e4b_consent_receipts",
        "e4b_consent_retentions",
        "e4b_consent_holds",
        "e4b_consent_hold_events",
    ]
    assert source.count("create function public.e4b_consent_") == 5
    assert "security definer" not in source.lower()
    assert "bypassrls" not in source.lower()
    assert "migration_draft_incomplete" not in source.lower()


def test_e4b_migration_has_exact_trigger_families_and_no_unlisted_constraint_delete() -> None:
    source = _migration_source().lower()

    for trigger in (
        "e4b_operations_immutable_guard_trg",
        "e4b_streams_immutable_guard_trg",
        "e4b_receipts_immutable_guard_trg",
        "e4b_retentions_immutable_guard_trg",
        "e4b_holds_immutable_guard_trg",
        "e4b_hold_events_immutable_guard_trg",
        "e4b_operations_historical_authority_guard_trg",
        "e4b_streams_transition_guard_trg",
        "e4b_retentions_hold_projection_guard_ctrg",
        "e4b_holds_hold_projection_guard_ctrg",
        "e4b_hold_events_hold_projection_guard_ctrg",
        "e4b_operations_chain_completeness_guard_ctrg",
        "e4b_streams_chain_completeness_guard_ctrg",
        "e4b_receipts_chain_completeness_guard_ctrg",
        "e4b_retentions_chain_completeness_guard_ctrg",
    ):
        assert f"create {'constraint ' if trigger.endswith('_ctrg') else ''}trigger {trigger}" in source
    assert "after delete on public.e4b_consent" not in source
    assert source.count("deferrable initially deferred") == 7
    assert source.count("for each row execute function public.e4b_consent_hold_projection_guard_fn()") == 3
    assert source.count("for each row execute function public.e4b_consent_chain_completeness_guard_fn()") == 4


def test_e4b_migration_fails_preflight_before_c3_ddl_and_keeps_eligible_future_only() -> None:
    source = _migration_source()
    preflight_end = source.index("create table public.e4b_consent_operations")
    preflight = source[:preflight_end]
    retention_state_check = source[source.index("constraint e4b_consent_retentions_state_check"):]

    assert "public.igrejas'::pg_catalog.regclass" in preflight
    assert "required root parent key is absent" in preflight
    assert "required tenant parent key is absent" in preflight
    assert "root_key.contype in ('p', 'u')" in preflight
    assert "root_key.conkey = array[" in preflight
    assert "root_attribute.atttypid = 'uuid'::pg_catalog.regtype" in preflight
    assert "e4b immutable guard rejected retention eligibility in C3" in source
    assert "expected_state := case when active_count > 0 then 'RETENTION_HELD'" in source
    assert "else 'RETENTION_RUNNING'" in source
    assert "RETENTION_ELIGIBLE" not in retention_state_check.split(
        "create table public.e4b_consent_holds", 1
    )[0]


def test_e4b_migration_enforces_rls_and_zero_operational_grant() -> None:
    source = _migration_source().lower()

    for relation in EXPECTED_RELATIONS:
        table = relation.removeprefix("public.")
        assert f"alter table public.{table} enable row level security;" in source
        assert f"alter table public.{table} force row level security;" in source
    assert source.count(" as permissive for all to public") == 6
    assert source.count(" as restrictive for all to public") == 6
    assert source.count("with check (") == 12
    assert "grant " not in source


def test_e4b_conditional_revokes_preserve_role_free_general_replay() -> None:
    source = _migration_source().lower()
    replay_source = REPLAY.read_text(encoding="utf-8")
    pg17_source = PG17_TEST.read_text(encoding="utf-8").lower()

    # The catalog replay intentionally starts with none of the named roles.
    # Named revokes therefore have to remain inside the conditional dynamic
    # block. PUBLIC is always addressable and is the sole direct grantee.
    assert "if pg_catalog.to_regrole(target_role) is not null then" in source
    assert "create role" not in source
    assert "revoke all privileges on table" in source
    assert "revoke select, insert, update, delete, truncate, references, trigger" in source
    assert "from %i" in source
    for role in ("anon", "authenticated", "service_role", "agent_runtime"):
        assert f"'{role}'" in source
        assert f"'{role}'" in replay_source
        assert re.search(rf"\\bfrom\\s+{role}\\b", source) is None
        assert re.search(rf"\\bto\\s+{role}\\b", source) is None

    role_free_guard = replay_source.index(
        "where rolname in ('anon', 'authenticated', 'service_role', 'agent_runtime')"
    )
    migration_execution = replay_source.index("cursor.execute(migration.sql)")
    assert role_free_guard < migration_execution
    assert "if cursor.fetchone() != (0,):" in replay_source

    # B2 is a prerequisite, not a repair path: these four live role names must
    # already exist before the migration is replayed and cannot be normalized.
    assert "def _bootstrap_baseline" in pg17_source
    assert "def _require_negative_role_preconditions" in pg17_source
    assert "b2 requer anon, authenticated, service_role e agent_runtime preexistentes" in pg17_source
    assert "_require_negative_role_preconditions(engine)" in pg17_source
    bootstrap_start = pg17_source.index("def _bootstrap_baseline")
    bootstrap_end = pg17_source.index("def _bootstrap_harness")
    bootstrap_source = pg17_source[bootstrap_start:bootstrap_end]
    assert bootstrap_source.index("_require_negative_role_preconditions(engine)") < bootstrap_source.index(
        "_execute_script("
    )
    assert "if pg_catalog.to_regrole(role_name) is null then" not in pg17_source
    assert "create role %i nologin noinherit nosuperuser" not in pg17_source
    assert "negative_role_attribute_fields" in pg17_source
    assert '"rolbypassrls",' in pg17_source
    assert '"rolconfig",' in pg17_source
    assert '", ".join(negative_role_attribute_fields)' in pg17_source
    assert "negative_role_attributes_before = _bootstrap_baseline(child)" in pg17_source
    assert "negative_role_attributes_after = _negative_role_attribute_vector(" in pg17_source
    assert "negative_role_attributes_after != negative_role_attributes_before" in pg17_source
    assert "a migration c3 alterou atributos de uma role negativa" in pg17_source
    assert "alter role" not in pg17_source
    assert "negative_role_safe_flags" not in pg17_source
    assert "def _destroy_ephemeral_harness" in pg17_source
    assert "drop role {controller}" in pg17_source
    assert "drop role {harness}" in pg17_source
    assert "pg_catalog.pg_auth_members" in pg17_source


def test_e4b_pg17_intent_nodeids_map_to_marked_real_functions() -> None:
    tree = ast.parse(PG17_TEST.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_e4b_pg17_")
    }

    assert list(functions) == [nodeid.split("::", 1)[1] for nodeid in EXPECTED_NODEIDS]
    for function in functions.values():
        decorator_text = "\n".join(ast.unparse(item) for item in function.decorator_list)
        assert "pytest.mark.rls_integration" in decorator_text
        assert not any(token in decorator_text for token in ("skip", "xfail"))


def test_e4b_frozen_spec_hash_is_unchanged() -> None:
    assert hashlib.sha256(SPEC.read_bytes()).hexdigest() == (
        "4da3aec66152aca4aa6513de47daa3740ac2f145332af7ec859ae0e350d228a2"
    )
