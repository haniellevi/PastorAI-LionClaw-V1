"""Oráculos físicos C3 para PostgreSQL 17 local, sintético e descartável."""

from __future__ import annotations

import ast
import datetime as dt
import inspect
import os
import pathlib
import queue
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.domain.e4b_consent import (
    E4bAction,
    E4bAuthorityResolution,
    E4bConfirmedOperation,
    E4bConcessionState,
    E4bConsentIntent,
    E4bFingerprint,
    E4bIdempotencyKey,
    E4bManifestantRole,
    E4bOperatorKind,
    E4bOrigin,
    E4bRole,
)
from app.services.e4b_consent_persistence import (
    E4bConsentStageRequest,
    E4bHoldAction,
    E4bHoldAuthorityResolution,
    E4bHoldStageRequest,
    E4bPersistenceError,
    E4bPersistenceErrorCode,
    E4bStagingOutcome,
    PostgresE4bConsentStagingAdapter,
    add_24m_utc,
    e4b_advisory_lock_texts,
)
from app.services.e4b_consent_boundary import (
    E4bHistoricalOperationIdentity,
    E4bOperationSelector,
    E4bReconciliationObservation,
    E4bReconciliationOutcome,
    E4bReconciliationReadPort,
    E4bReconciliationSnapshot,
    E4bServerResolvedReadContext,
    E4bSnapshotProvenance,
    reconcile,
)
from tests.conftest_rls import assert_disposable_database


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "20260910_142830_add_e4b_consent_persistence.sql"
RELATIONS = (
    "e4b_consent_operations",
    "e4b_consent_streams",
    "e4b_consent_receipts",
    "e4b_consent_retentions",
    "e4b_consent_holds",
    "e4b_consent_hold_events",
)
POLICY_PREFIXES = (
    "operations",
    "streams",
    "receipts",
    "retentions",
    "holds",
    "hold_events",
)
NEGATIVE_ROLES = ("authenticated", "anon", "service_role", "agent_runtime")
NEGATIVE_ROLE_ATTRIBUTE_FIELDS = (
    "rolcanlogin",
    "rolinherit",
    "rolsuper",
    "rolcreatedb",
    "rolcreaterole",
    "rolreplication",
    "rolbypassrls",
    "rolconnlimit",
    "rolvaliduntil",
    "rolconfig",
)
HARNESS = "e4b_pg17_harness"
CONTROLLER = "e4b_pg17_controller"
TENANT_A = uuid.UUID("a1000000-0000-0000-0000-000000000001")
TENANT_B = uuid.UUID("b1000000-0000-0000-0000-000000000001")
PERSON_A = uuid.UUID("a1000000-0000-0000-0000-000000000002")
PERSON_B = uuid.UUID("b1000000-0000-0000-0000-000000000002")
PERSON_A_RESPONSAVEL = uuid.UUID("a1000000-0000-0000-0000-000000000004")
USER_A = uuid.UUID("a1000000-0000-0000-0000-000000000003")
USER_B = uuid.UUID("b1000000-0000-0000-0000-000000000003")
ORACLE_FUNCTIONS = (
    "test_e4b_pg17_catalog_001_matches_r4_manifest",
    "test_e4b_pg17_parent_001_requires_synthetic_parent_anchors",
    "test_e4b_pg17_rls_001_enforces_force_and_tenant_policies",
    "test_e4b_pg17_guc_001_exercises_positive_and_negative_tenant_matrix",
    "test_e4b_pg17_acl_001_verifies_revokes_and_ephemeral_memberships",
    "test_e4b_pg17_dataapi_001_denies_known_roles_without_guc",
    "test_e4b_pg17_chain_001_commits_complete_chain_and_rejects_partial",
    "test_e4b_pg17_chain_002_rejects_invalid_withdraw_origins_and_streams",
    "test_e4b_pg17_replay_001_rehydrates_exact_and_conflicts_tenant_scoped",
    "test_e4b_pg17_imm_001_rejects_immutable_updates_and_deletes",
    "test_e4b_pg17_imm_002_allows_only_stream_hold_retention_transitions",
    "test_e4b_pg17_auth_001_validates_historical_operator_role_links",
    "test_e4b_pg17_ret_001_validates_confirmed_at_and_utc_retention",
    "test_e4b_pg17_hold_001_projects_holds_and_serializes_subject",
    "test_e4b_pg17_lock_001_orders_tenant_scoped_advisory_locks",
    "test_e4b_pg17_rollback_001_removes_partial_state_and_releases_locks",
    "test_e4b_pg17_commit_001_reconciles_precommit_and_uncertain_commit",
    "test_e4b_pg17_noskip_001_collects_exact_oracle_manifest",
)
GUARD_FUNCTIONS = (
    "e4b_consent_immutable_guard_fn",
    "e4b_consent_historical_authority_guard_fn",
    "e4b_consent_stream_transition_guard_fn",
    "e4b_consent_hold_projection_guard_fn",
    "e4b_consent_chain_completeness_guard_fn",
)
ALL_TRIGGER_EVENTS = {
    "e4b_operations_immutable_guard_trg": (
        "e4b_consent_operations", False, True, True, False, True, False, False, False
    ),
    "e4b_streams_immutable_guard_trg": (
        "e4b_consent_streams", False, True, True, False, True, False, False, False
    ),
    "e4b_receipts_immutable_guard_trg": (
        "e4b_consent_receipts", False, True, True, False, True, False, False, False
    ),
    "e4b_retentions_immutable_guard_trg": (
        "e4b_consent_retentions", False, True, True, False, True, False, False, False
    ),
    "e4b_holds_immutable_guard_trg": (
        "e4b_consent_holds", False, True, True, False, True, False, False, False
    ),
    "e4b_hold_events_immutable_guard_trg": (
        "e4b_consent_hold_events", False, True, True, False, True, False, False, False
    ),
    "e4b_operations_historical_authority_guard_trg": (
        "e4b_consent_operations", True, False, False, False, True, False, False, False
    ),
    "e4b_streams_transition_guard_trg": (
        "e4b_consent_streams", True, True, False, False, True, False, False, False
    ),
    "e4b_retentions_hold_projection_guard_ctrg": (
        "e4b_consent_retentions", True, True, False, True, True, True, True, True
    ),
    "e4b_holds_hold_projection_guard_ctrg": (
        "e4b_consent_holds", True, True, False, True, True, True, True, True
    ),
    "e4b_hold_events_hold_projection_guard_ctrg": (
        "e4b_consent_hold_events", True, False, False, True, True, True, True, True
    ),
    "e4b_operations_chain_completeness_guard_ctrg": (
        "e4b_consent_operations", True, False, False, True, True, True, True, True
    ),
    "e4b_streams_chain_completeness_guard_ctrg": (
        "e4b_consent_streams", True, True, False, True, True, True, True, True
    ),
    "e4b_receipts_chain_completeness_guard_ctrg": (
        "e4b_consent_receipts", True, False, False, True, True, True, True, True
    ),
    "e4b_retentions_chain_completeness_guard_ctrg": (
        "e4b_consent_retentions", True, False, False, True, True, True, True, True
    ),
}
RECEIPT_ALLOWLIST = (
    "igreja_id",
    "receipt_id",
    "operation_id",
    "correlation_id",
    "action",
    "origin",
    "manifestant_role",
    "concession_state",
    "confirmed_at",
    "contract_version",
    "policy_version",
    "term_version",
    "content_digest",
    "fingerprint_version",
    "fingerprint",
)
CATALOG_COLUMNS = {
    "e4b_consent_operations": (
        ("igreja_id", "uuid", True, None),
        ("operation_id", "uuid", True, None),
        ("idempotency_key", "text", True, None),
        ("correlation_id", "uuid", True, None),
        ("action", "text", True, None),
        ("origin", "text", True, "'E4B'::text"),
        ("origin_accept_operation_id", "uuid", False, None),
        ("origin_action", "text", False, None),
        ("titular_pessoa_id", "uuid", True, None),
        ("manifestante_pessoa_id", "uuid", True, None),
        ("responsavel_pessoa_id", "uuid", False, None),
        ("manifestant_role", "text", True, None),
        ("manifestant_relation_valid", "boolean", True, "true"),
        ("operator_id", "uuid", True, None),
        ("operator_kind", "text", True, None),
        ("operator_role_links", "text[]", True, "ARRAY[]::text[]"),
        ("server_resolved", "boolean", True, "true"),
        ("finalidade_id", "text", True, None),
        ("contract_version", "text", True, None),
        ("policy_version", "text", True, None),
        ("term_version", "text", True, None),
        ("content_digest", "text", True, None),
        ("fingerprint_version", "text", True, "'e4b-fingerprint:v1'::text"),
        ("fingerprint", "text", True, None),
        ("concession_state", "text", True, None),
        ("operation_state", "text", True, "'CONFIRMED'::text"),
        ("confirmed_at", "timestamp with time zone", True, None),
    ),
    "e4b_consent_streams": (
        ("igreja_id", "uuid", True, None),
        ("titular_pessoa_id", "uuid", True, None),
        ("finalidade_id", "text", True, None),
        ("accept_operation_id", "uuid", True, None),
        ("accept_action", "text", True, "'ACCEPT'::text"),
        ("stream_state", "text", True, "'ACTIVE'::text"),
        ("withdraw_operation_id", "uuid", False, None),
        ("withdraw_action", "text", False, None),
        ("state_changed_at", "timestamp with time zone", True, None),
    ),
    "e4b_consent_receipts": (
        ("igreja_id", "uuid", True, None),
        ("receipt_id", "uuid", True, None),
        ("operation_id", "uuid", True, None),
        ("correlation_id", "uuid", True, None),
        ("action", "text", True, None),
        ("origin", "text", True, "'E4B'::text"),
        ("manifestant_role", "text", True, None),
        ("concession_state", "text", True, None),
        ("confirmed_at", "timestamp with time zone", True, None),
        ("contract_version", "text", True, None),
        ("policy_version", "text", True, None),
        ("term_version", "text", True, None),
        ("content_digest", "text", True, None),
        ("fingerprint_version", "text", True, None),
        ("fingerprint", "text", True, None),
    ),
    "e4b_consent_retentions": (
        ("igreja_id", "uuid", True, None),
        ("operation_id", "uuid", True, None),
        ("retention_state", "text", True, "'RETENTION_RUNNING'::text"),
        ("retention_anchor_at", "timestamp with time zone", True, None),
        ("retention_due_at", "timestamp with time zone", True, None),
        ("active_hold_count", "integer", True, "0"),
        ("suspension_started_at", "timestamp with time zone", False, None),
        ("last_hold_event_at", "timestamp with time zone", False, None),
        ("state_changed_at", "timestamp with time zone", True, None),
    ),
    "e4b_consent_holds": (
        ("igreja_id", "uuid", True, None),
        ("hold_id", "uuid", True, None),
        ("operation_id", "uuid", True, None),
        ("hold_state", "text", True, "'ACTIVE'::text"),
        ("policy_version", "text", True, None),
        ("applied_at", "timestamp with time zone", True, None),
        ("resolved_at", "timestamp with time zone", False, None),
    ),
    "e4b_consent_hold_events": (
        ("igreja_id", "uuid", True, None),
        ("hold_event_id", "uuid", True, None),
        ("hold_id", "uuid", True, None),
        ("operation_id", "uuid", True, None),
        ("event_kind", "text", True, None),
        ("event_sequence", "smallint", True, None),
        ("authority_app_user_id", "uuid", True, None),
        ("authority_resolution_version", "text", True, None),
        ("authority_resolution_sha256", "bytea", True, None),
        ("policy_version", "text", True, None),
        ("occurred_at", "timestamp with time zone", True, None),
    ),
}
EXPECTED_PRIMARY_KEYS = {
    "e4b_consent_operations_pkey": ("e4b_consent_operations", ("igreja_id", "operation_id")),
    "e4b_consent_streams_pkey": (
        "e4b_consent_streams", ("igreja_id", "titular_pessoa_id", "finalidade_id")
    ),
    "e4b_consent_receipts_pkey": ("e4b_consent_receipts", ("igreja_id", "receipt_id")),
    "e4b_consent_retentions_pkey": ("e4b_consent_retentions", ("igreja_id", "operation_id")),
    "e4b_consent_holds_pkey": ("e4b_consent_holds", ("igreja_id", "hold_id")),
    "e4b_consent_hold_events_pkey": (
        "e4b_consent_hold_events", ("igreja_id", "hold_event_id")
    ),
}
EXPECTED_UNIQUE_KEYS = {
    "e4b_consent_operations_tenant_k_key": (
        "e4b_consent_operations", ("igreja_id", "idempotency_key")
    ),
    "e4b_consent_operations_tenant_c_key": (
        "e4b_consent_operations", ("igreja_id", "correlation_id")
    ),
    "e4b_consent_operations_stream_action_key": (
        "e4b_consent_operations",
        ("igreja_id", "operation_id", "action", "titular_pessoa_id", "finalidade_id"),
    ),
    "e4b_consent_operations_confirmation_key": (
        "e4b_consent_operations", ("igreja_id", "operation_id", "confirmed_at")
    ),
    "e4b_consent_operations_receipt_projection_key": (
        "e4b_consent_operations",
        (
            "igreja_id", "operation_id", "correlation_id", "action", "origin",
            "manifestant_role", "concession_state", "confirmed_at", "contract_version",
            "policy_version", "term_version", "content_digest", "fingerprint_version",
            "fingerprint",
        ),
    ),
    "e4b_consent_receipts_tenant_operation_key": (
        "e4b_consent_receipts", ("igreja_id", "operation_id")
    ),
    "e4b_consent_holds_identity_key": (
        "e4b_consent_holds", ("igreja_id", "hold_id", "operation_id")
    ),
    "e4b_consent_hold_events_kind_key": (
        "e4b_consent_hold_events", ("igreja_id", "hold_id", "event_kind")
    ),
    "e4b_consent_hold_events_sequence_key": (
        "e4b_consent_hold_events", ("igreja_id", "hold_id", "event_sequence")
    ),
}
EXPECTED_FOREIGN_KEYS = {
    "e4b_consent_operations_igreja_fkey": (
        "e4b_consent_operations", ("igreja_id",), "igrejas", ("id",)
    ),
    "e4b_consent_operations_titular_fkey": (
        "e4b_consent_operations", ("igreja_id", "titular_pessoa_id"), "pessoas", ("igreja_id", "id")
    ),
    "e4b_consent_operations_manifestante_fkey": (
        "e4b_consent_operations", ("igreja_id", "manifestante_pessoa_id"), "pessoas", ("igreja_id", "id")
    ),
    "e4b_consent_operations_responsavel_fkey": (
        "e4b_consent_operations", ("igreja_id", "responsavel_pessoa_id"), "pessoas", ("igreja_id", "id")
    ),
    "e4b_consent_operations_origin_accept_fkey": (
        "e4b_consent_operations",
        ("igreja_id", "origin_accept_operation_id", "origin_action", "titular_pessoa_id", "finalidade_id"),
        "e4b_consent_operations",
        ("igreja_id", "operation_id", "action", "titular_pessoa_id", "finalidade_id"),
    ),
    "e4b_consent_streams_igreja_fkey": (
        "e4b_consent_streams", ("igreja_id",), "igrejas", ("id",)
    ),
    "e4b_consent_streams_titular_fkey": (
        "e4b_consent_streams", ("igreja_id", "titular_pessoa_id"), "pessoas", ("igreja_id", "id")
    ),
    "e4b_consent_streams_accept_fkey": (
        "e4b_consent_streams",
        ("igreja_id", "accept_operation_id", "accept_action", "titular_pessoa_id", "finalidade_id"),
        "e4b_consent_operations",
        ("igreja_id", "operation_id", "action", "titular_pessoa_id", "finalidade_id"),
    ),
    "e4b_consent_streams_withdraw_fkey": (
        "e4b_consent_streams",
        ("igreja_id", "withdraw_operation_id", "withdraw_action", "titular_pessoa_id", "finalidade_id"),
        "e4b_consent_operations",
        ("igreja_id", "operation_id", "action", "titular_pessoa_id", "finalidade_id"),
    ),
    "e4b_consent_receipts_igreja_fkey": (
        "e4b_consent_receipts", ("igreja_id",), "igrejas", ("id",)
    ),
    "e4b_consent_receipts_operation_fkey": (
        "e4b_consent_receipts", ("igreja_id", "operation_id"), "e4b_consent_operations", ("igreja_id", "operation_id")
    ),
    "e4b_consent_receipts_projection_fkey": (
        "e4b_consent_receipts",
        (
            "igreja_id", "operation_id", "correlation_id", "action", "origin",
            "manifestant_role", "concession_state", "confirmed_at", "contract_version",
            "policy_version", "term_version", "content_digest", "fingerprint_version",
            "fingerprint",
        ),
        "e4b_consent_operations",
        (
            "igreja_id", "operation_id", "correlation_id", "action", "origin",
            "manifestant_role", "concession_state", "confirmed_at", "contract_version",
            "policy_version", "term_version", "content_digest", "fingerprint_version",
            "fingerprint",
        ),
    ),
    "e4b_consent_retentions_igreja_fkey": (
        "e4b_consent_retentions", ("igreja_id",), "igrejas", ("id",)
    ),
    "e4b_consent_retentions_operation_fkey": (
        "e4b_consent_retentions", ("igreja_id", "operation_id"), "e4b_consent_operations", ("igreja_id", "operation_id")
    ),
    "e4b_consent_retentions_anchor_fkey": (
        "e4b_consent_retentions", ("igreja_id", "operation_id", "retention_anchor_at"),
        "e4b_consent_operations", ("igreja_id", "operation_id", "confirmed_at")
    ),
    "e4b_consent_holds_igreja_fkey": (
        "e4b_consent_holds", ("igreja_id",), "igrejas", ("id",)
    ),
    "e4b_consent_holds_operation_fkey": (
        "e4b_consent_holds", ("igreja_id", "operation_id"), "e4b_consent_retentions", ("igreja_id", "operation_id")
    ),
    "e4b_consent_hold_events_igreja_fkey": (
        "e4b_consent_hold_events", ("igreja_id",), "igrejas", ("id",)
    ),
    "e4b_consent_hold_events_hold_fkey": (
        "e4b_consent_hold_events", ("igreja_id", "hold_id", "operation_id"),
        "e4b_consent_holds", ("igreja_id", "hold_id", "operation_id")
    ),
    "e4b_consent_hold_events_authority_fkey": (
        "e4b_consent_hold_events", ("igreja_id", "authority_app_user_id"), "app_users", ("igreja_id", "id")
    ),
}
EXPECTED_CHECK_CONSTRAINTS = {
    "e4b_consent_operations_action_check": ("action", "ACCEPT", "WITHDRAW"),
    "e4b_consent_operations_origin_check": ("origin", "E4B", "origin_accept_operation_id", "ACTIVE", "WITHDRAWN"),
    "e4b_consent_operations_manifestation_check": ("manifestant_relation_valid", "server_resolved", "TITULAR", "RESPONSAVEL"),
    "e4b_consent_operations_operator_check": ("operator_kind", "HUMAN", "TECHNICAL", "operator_role_links"),
    "e4b_consent_operations_fixed_values_check": ("fingerprint_version", "operation_state", "CONFIRMED", "idempotency_key"),
    "e4b_consent_operations_digest_check": ("content_digest", "fingerprint", "[0-9a-f]"),
    "e4b_consent_streams_state_check": ("stream_state", "ACTIVE", "WITHDRAWN", "withdraw_operation_id"),
    "e4b_consent_streams_accept_check": ("accept_action", "ACCEPT", "finalidade_id"),
    "e4b_consent_receipts_fixed_values_check": ("origin", "E4B", "manifestant_role", "fingerprint_version"),
    "e4b_consent_receipts_digest_check": ("content_digest", "fingerprint", "[0-9a-f]"),
    "e4b_consent_retentions_count_check": ("active_hold_count", "0"),
    "e4b_consent_retentions_due_check": ("retention_due_at", "retention_anchor_at"),
    "e4b_consent_retentions_state_check": ("RETENTION_RUNNING", "RETENTION_HELD", "active_hold_count"),
    "e4b_consent_holds_state_check": ("hold_state", "ACTIVE", "RESOLVED", "resolved_at"),
    "e4b_consent_holds_policy_version_check": ("policy_version", "A-Za-z0-9"),
    "e4b_consent_hold_events_kind_sequence_check": ("HOLD_APPLIED", "HOLD_RESOLVED", "event_sequence"),
    "e4b_consent_hold_events_digest_check": ("authority_resolution_sha256", "octet_length", "32"),
    "e4b_consent_hold_events_versions_check": ("authority_resolution_version", "policy_version", "A-Za-z0-9"),
}
EXPECTED_INDEXES = {
    "e4b_consent_operations_pkey": ("e4b_consent_operations", True, True, ("igreja_id", "operation_id"), None),
    "e4b_consent_operations_tenant_k_key": ("e4b_consent_operations", True, False, ("igreja_id", "idempotency_key"), None),
    "e4b_consent_operations_tenant_c_key": ("e4b_consent_operations", True, False, ("igreja_id", "correlation_id"), None),
    "e4b_consent_operations_stream_action_key": ("e4b_consent_operations", True, False, ("igreja_id", "operation_id", "action", "titular_pessoa_id", "finalidade_id"), None),
    "e4b_consent_operations_confirmation_key": ("e4b_consent_operations", True, False, ("igreja_id", "operation_id", "confirmed_at"), None),
    "e4b_consent_operations_receipt_projection_key": ("e4b_consent_operations", True, False, ("igreja_id", "operation_id", "correlation_id", "fingerprint"), None),
    "e4b_consent_operations_one_accept_per_stream_key": ("e4b_consent_operations", True, False, ("igreja_id", "titular_pessoa_id", "finalidade_id"), "action = 'ACCEPT'"),
    "e4b_consent_operations_origin_lookup_idx": ("e4b_consent_operations", False, False, ("igreja_id", "origin_accept_operation_id"), None),
    "e4b_consent_operations_subject_timeline_idx": ("e4b_consent_operations", False, False, ("igreja_id", "titular_pessoa_id", "confirmed_at DESC"), None),
    "e4b_consent_operations_tenant_action_idx": ("e4b_consent_operations", False, False, ("igreja_id", "action", "confirmed_at DESC"), None),
    "e4b_consent_streams_pkey": ("e4b_consent_streams", True, True, ("igreja_id", "titular_pessoa_id", "finalidade_id"), None),
    "e4b_consent_streams_active_lookup_idx": ("e4b_consent_streams", False, False, ("igreja_id", "finalidade_id", "titular_pessoa_id"), "stream_state = 'ACTIVE'"),
    "e4b_consent_receipts_pkey": ("e4b_consent_receipts", True, True, ("igreja_id", "receipt_id"), None),
    "e4b_consent_receipts_tenant_operation_key": ("e4b_consent_receipts", True, False, ("igreja_id", "operation_id"), None),
    "e4b_consent_receipts_tenant_c_idx": ("e4b_consent_receipts", False, False, ("igreja_id", "correlation_id"), None),
    "e4b_consent_retentions_pkey": ("e4b_consent_retentions", True, True, ("igreja_id", "operation_id"), None),
    "e4b_consent_retentions_due_idx": ("e4b_consent_retentions", False, False, ("igreja_id", "retention_state", "retention_due_at"), None),
    "e4b_consent_holds_pkey": ("e4b_consent_holds", True, True, ("igreja_id", "hold_id"), None),
    "e4b_consent_holds_identity_key": ("e4b_consent_holds", True, False, ("igreja_id", "hold_id", "operation_id"), None),
    "e4b_consent_holds_active_operation_idx": ("e4b_consent_holds", False, False, ("igreja_id", "operation_id", "applied_at"), "hold_state = 'ACTIVE'"),
    "e4b_consent_hold_events_pkey": ("e4b_consent_hold_events", True, True, ("igreja_id", "hold_event_id"), None),
    "e4b_consent_hold_events_kind_key": ("e4b_consent_hold_events", True, False, ("igreja_id", "hold_id", "event_kind"), None),
    "e4b_consent_hold_events_sequence_key": ("e4b_consent_hold_events", True, False, ("igreja_id", "hold_id", "event_sequence"), None),
    "e4b_consent_hold_events_timeline_idx": ("e4b_consent_hold_events", False, False, ("igreja_id", "hold_id", "occurred_at"), None),
}


@pytest.fixture(scope="session")
def rls_database_url() -> str:
    """Exige um alvo local descartável quando os oráculos forem executados."""

    url = os.environ.get("RLS_TEST_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "RLS_TEST_DATABASE_URL é obrigatória para os oráculos PG17 C3"
        )
    assert_disposable_database(url)
    return url


def _execute_script(engine: Engine, sql: str) -> None:
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute(sql)
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            cursor.close()
    finally:
        raw.close()


def _negative_role_attribute_vector(
    engine: Engine,
    *,
    require_all: bool,
) -> tuple[tuple[object, ...], ...]:
    """Lê os atributos públicos completos sem normalizar roles existentes."""

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "select rolname, "
                + ", ".join(NEGATIVE_ROLE_ATTRIBUTE_FIELDS)
                + " from pg_catalog.pg_roles where rolname = any(:roles) order by rolname"
            ),
            {"roles": list(NEGATIVE_ROLES)},
        ).all()
    vector = tuple(tuple(row) for row in rows)
    if require_all:
        assert [row[0] for row in vector] == sorted(NEGATIVE_ROLES)
    return vector


def _require_negative_role_preconditions(engine: Engine) -> tuple[tuple[object, ...], ...]:
    """B2: as quatro roles precisam existir antes de qualquer replay ou DDL C3."""

    vector = _negative_role_attribute_vector(engine, require_all=False)
    if [row[0] for row in vector] != sorted(NEGATIVE_ROLES):
        pytest.fail(
            "B2 requer anon, authenticated, service_role e agent_runtime preexistentes antes do replay C3"
        )
    return vector


def _bootstrap_baseline(engine: Engine) -> tuple[tuple[object, ...], ...]:
    """Cria somente pais sintéticos depois de capturar a pré-condição B2."""

    attributes_before_migration = _require_negative_role_preconditions(engine)

    _execute_script(
        engine,
        """
        create table public.igrejas (id uuid primary key, nome text not null);
        create table public.pessoas (
          id uuid primary key,
          igreja_id uuid not null references public.igrejas(id) on update restrict on delete restrict,
          nome text not null,
          constraint pessoas_igreja_id_id_key unique (igreja_id, id)
        );
        create table public.app_users (
          id uuid primary key,
          igreja_id uuid not null references public.igrejas(id) on update restrict on delete restrict,
          nome text not null,
          constraint app_users_igreja_id_id_key unique (igreja_id, id)
        );
        """,
    )
    return attributes_before_migration


def _bootstrap_harness(engine: Engine) -> None:
    """Aplica fora da migration a única ACL de teste PG17 descartável."""

    _execute_script(
        engine,
        f"""
        do $$ begin
          if pg_catalog.to_regrole('{HARNESS}') is not null
             or pg_catalog.to_regrole('{CONTROLLER}') is not null then
            raise exception using errcode = '42710', message = 'e4b ephemeral role collision';
          end if;
        end $$;
        create role {HARNESS} nologin noinherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls;
        create role {CONTROLLER} login noinherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls;
        grant {HARNESS} to {CONTROLLER} with inherit false;
        grant {HARNESS} to {CONTROLLER} with set true;
        grant {HARNESS} to {CONTROLLER} with admin false;
        grant authenticated to {CONTROLLER} with inherit false;
        grant authenticated to {CONTROLLER} with set true;
        grant authenticated to {CONTROLLER} with admin false;
        grant anon to {CONTROLLER} with inherit false;
        grant anon to {CONTROLLER} with set true;
        grant anon to {CONTROLLER} with admin false;
        grant service_role to {CONTROLLER} with inherit false;
        grant service_role to {CONTROLLER} with set true;
        grant service_role to {CONTROLLER} with admin false;
        grant agent_runtime to {CONTROLLER} with inherit false;
        grant agent_runtime to {CONTROLLER} with set true;
        grant agent_runtime to {CONTROLLER} with admin false;
        grant {CONTROLLER} to current_user with inherit false;
        grant {CONTROLLER} to current_user with set true;
        grant {CONTROLLER} to current_user with admin false;
        grant usage on schema public to {HARNESS};
        grant select, insert, update, delete on table
          public.e4b_consent_operations,
          public.e4b_consent_streams,
          public.e4b_consent_receipts,
          public.e4b_consent_retentions,
          public.e4b_consent_holds,
          public.e4b_consent_hold_events to {HARNESS};
        """,
    )


def _insert_parents(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("insert into public.igrejas (id, nome) values (:a, 'A'), (:b, 'B')"),
            {"a": TENANT_A, "b": TENANT_B},
        )
        connection.execute(
            text(
                "insert into public.pessoas (id, igreja_id, nome) values "
                "(:pa, :a, 'A'), (:pr, :a, 'Responsavel A'), (:pb, :b, 'B')"
            ),
            {
                "pa": PERSON_A,
                "pr": PERSON_A_RESPONSAVEL,
                "a": TENANT_A,
                "pb": PERSON_B,
                "b": TENANT_B,
            },
        )
        connection.execute(
            text("insert into public.app_users (id, igreja_id, nome) values (:ua, :a, 'A'), (:ub, :b, 'B')"),
            {"ua": USER_A, "a": TENANT_A, "ub": USER_B, "b": TENANT_B},
        )


def _destroy_ephemeral_harness(connection) -> None:
    """Remove e prova remoção de roles e memberships que o harness criou."""

    role_rows = connection.execute(
        text(
            "select rolname, oid from pg_catalog.pg_roles "
            "where rolname in (:harness, :controller) order by rolname"
        ),
        {"harness": HARNESS, "controller": CONTROLLER},
    ).all()
    assert [row[0] for row in role_rows] == sorted((HARNESS, CONTROLLER))
    role_oids = {str(name): int(oid) for name, oid in role_rows}
    connection.exec_driver_sql(
        f"revoke {HARNESS}, authenticated, anon, service_role, agent_runtime from {CONTROLLER}"
    )
    connection.exec_driver_sql(f"revoke {CONTROLLER} from current_user")
    connection.exec_driver_sql(f"drop role {CONTROLLER}")
    connection.exec_driver_sql(f"drop role {HARNESS}")
    assert connection.execute(
        text(
            "select count(*) from pg_catalog.pg_roles "
            "where rolname in (:harness, :controller)"
        ),
        {"harness": HARNESS, "controller": CONTROLLER},
    ).scalar_one() == 0
    assert connection.execute(
        text(
            "select count(*) from pg_catalog.pg_auth_members where "
            "roleid in (cast(:harness_oid as oid), cast(:controller_oid as oid)) "
            "or member in (cast(:harness_oid as oid), cast(:controller_oid as oid))"
        ),
        {
            "harness_oid": role_oids[HARNESS],
            "controller_oid": role_oids[CONTROLLER],
        },
    ).scalar_one() == 0


@pytest.fixture
def e4b_pg17_engine(rls_database_url: str) -> Iterator[Engine]:
    """Cria um child database PG17 por oráculo e o descarta ao terminar."""

    assert_disposable_database(rls_database_url)
    root_url = make_url(rls_database_url)
    child_name = f"e4b_c3_{uuid.uuid4().hex[:16]}"
    child_url = root_url.set(database=child_name).render_as_string(hide_password=False)
    assert_disposable_database(child_url)
    admin = create_engine(root_url, future=True, isolation_level="AUTOCOMMIT")
    quoted = admin.dialect.identifier_preparer.quote(child_name)
    child: Engine | None = None
    ephemeral_bootstrapped = False
    try:
        with admin.connect() as connection:
            assert int(connection.exec_driver_sql("show server_version_num").scalar_one()) // 10000 == 17
            connection.exec_driver_sql(f"create database {quoted} template template0")
        child = create_engine(child_url, future=True)
        negative_role_attributes_before = _bootstrap_baseline(child)
        _execute_script(child, MIGRATION.read_text(encoding="utf-8"))
        negative_role_attributes_after = _negative_role_attribute_vector(
            child,
            require_all=True,
        )
        if negative_role_attributes_after != negative_role_attributes_before:
            pytest.fail("a migration C3 alterou atributos de uma role negativa")
        _bootstrap_harness(child)
        ephemeral_bootstrapped = True
        _insert_parents(child)
        yield child
    finally:
        if child is not None:
            child.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(
                "select pg_terminate_backend(pid) from pg_stat_activity where datname=%s and pid <> pg_backend_pid()",
                (child_name,),
            )
            connection.exec_driver_sql(f"drop database if exists {quoted}")
            if ephemeral_bootstrapped:
                _destroy_ephemeral_harness(connection)
        admin.dispose()


@contextmanager
def _harness_session(engine: Engine, tenant: uuid.UUID) -> Iterator[Session]:
    with Session(engine) as session:
        with session.begin():
            session.execute(text(f"set local role {CONTROLLER}"))
            session.execute(text(f"set local role {HARNESS}"))
            session.execute(
                text("select set_config('app.tenant_igreja_id', :tenant, true)"),
                {"tenant": str(tenant)},
            )
            session.execute(text("set local lock_timeout = '5s'"))
            yield session


@contextmanager
def _oracle_session(
    engine: Engine,
    *,
    role: str = HARNESS,
    tenant: uuid.UUID | str | None = None,
    lock_timeout: str | None = None,
    read_only: bool = False,
) -> Iterator[Session]:
    """Sessão de oráculo sem fallback de owner e com role efetiva explícita."""

    with Session(engine) as session:
        with session.begin():
            if read_only:
                session.execute(text("set transaction read only"))
            session.execute(text(f"set local role {CONTROLLER}"))
            session.execute(text(f"set local role {role}"))
            if tenant is not None:
                session.execute(
                    text("select set_config('app.tenant_igreja_id', :tenant, true)"),
                    {"tenant": str(tenant)},
                )
            if lock_timeout is not None:
                session.execute(
                    text("select set_config('lock_timeout', :timeout, true)"),
                    {"timeout": lock_timeout},
                )
            yield session


def _authority(tenant: uuid.UUID, person: uuid.UUID, correlation: uuid.UUID, purpose: str) -> E4bAuthorityResolution:
    return E4bAuthorityResolution(
        igreja_id=tenant,
        titular_pessoa_id=person,
        manifestante_pessoa_id=person,
        manifestant_role=E4bManifestantRole.TITULAR,
        responsavel_pessoa_id=None,
        operador_id=person,
        operator_kind=E4bOperatorKind.HUMAN,
        finalidade_id=purpose,
        origin=E4bOrigin.E4B,
        correlation_id=correlation,
        contract_version="contract/v1",
        policy_version="policy/v1",
        term_version="term/v1",
        content_digest="a" * 64,
        operator_role_links=frozenset({E4bRole.TITULAR, E4bRole.MANIFESTANTE}),
    )


def _accept_request(
    tenant: uuid.UUID = TENANT_A,
    person: uuid.UUID = PERSON_A,
    *,
    key: str | None = None,
    correlation: uuid.UUID | None = None,
    purpose: str = "cuidado_pastoral",
) -> E4bConsentStageRequest:
    correlation = correlation or uuid.uuid4()
    intent = E4bConsentIntent.create(
        action=E4bAction.ACCEPT,
        idempotency_key=E4bIdempotencyKey(
            igreja_id=tenant,
            value=key or f"e4b:consent-operation:v1:{uuid.uuid4().hex}",
        ),
        authority=_authority(tenant, person, correlation, purpose),
    )
    return E4bConsentStageRequest(uuid.uuid4(), uuid.uuid4(), intent)


def _withdraw_request(accept: E4bConsentStageRequest) -> E4bConsentStageRequest:
    authority = accept.intent.authority
    intent = E4bConsentIntent.create(
        action=E4bAction.WITHDRAW,
        idempotency_key=E4bIdempotencyKey(
            igreja_id=authority.igreja_id,
            value=f"e4b:consent-operation:v1:{uuid.uuid4().hex}",
        ),
        authority=_authority(
            authority.igreja_id,
            authority.titular_pessoa_id,
            uuid.uuid4(),
            authority.finalidade_id,
        ),
        origin_accept_operation_id=accept.operation_id,
    )
    return E4bConsentStageRequest(uuid.uuid4(), uuid.uuid4(), intent)


def _hold_request(
    action: E4bHoldAction,
    *,
    tenant: uuid.UUID,
    operation_id: uuid.UUID,
    hold_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    authority_tenant: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    authority_version: str = "authority/v1",
    policy_version: str = "policy/v1",
) -> E4bHoldStageRequest:
    return E4bHoldStageRequest(
        action,
        tenant,
        operation_id,
        hold_id or uuid.uuid4(),
        event_id or uuid.uuid4(),
        E4bHoldAuthorityResolution(
            igreja_id=authority_tenant or tenant,
            authority_app_user_id=user_id or (USER_A if tenant == TENANT_A else USER_B),
            authority_resolution_version=authority_version,
            authority_resolution_sha256=(b"a" if action is E4bHoldAction.APPLY else b"b") * 32,
        ),
        policy_version,
    )


def _stage_accept(engine: Engine, request: E4bConsentStageRequest | None = None) -> E4bConsentStageRequest:
    request = request or _accept_request()
    with _harness_session(engine, request.intent.authority.igreja_id) as session:
        result = PostgresE4bConsentStagingAdapter(session).stage_consent(request)
        assert result.outcome is E4bStagingOutcome.STAGED
    return request


def _count(engine: Engine, relation: str, tenant: uuid.UUID) -> int:
    with _harness_session(engine, tenant) as session:
        return int(session.execute(text(f"select count(*) from public.{relation}")).scalar_one())


def _relation_counts(engine: Engine, tenant: uuid.UUID) -> dict[str, int]:
    return {relation: _count(engine, relation, tenant) for relation in RELATIONS}


def _normalise_catalog_sql(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.replace("::text", "").split())


def _assert_missing_root_key_blocks_before_e4b_ddl(engine: Engine) -> None:
    """Exerce a variação negativa em outra base descartável, antes de qualquer DDL E4b."""

    source_url = make_url(engine.url.render_as_string(hide_password=False))
    child_name = f"e4b_c3_parent_{uuid.uuid4().hex[:12]}"
    child_url = source_url.set(database=child_name).render_as_string(hide_password=False)
    assert_disposable_database(child_url)
    admin = create_engine(source_url, future=True, isolation_level="AUTOCOMMIT")
    quoted = admin.dialect.identifier_preparer.quote(child_name)
    broken: Engine | None = None
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f"create database {quoted} template template0")
        broken = create_engine(child_url, future=True)
        _execute_script(
            broken,
            """
            create table public.igrejas (id uuid not null, nome text not null);
            create table public.pessoas (
              id uuid primary key,
              igreja_id uuid not null,
              nome text not null,
              constraint pessoas_igreja_id_id_key unique (igreja_id, id)
            );
            create table public.app_users (
              id uuid primary key,
              igreja_id uuid not null,
              nome text not null,
              constraint app_users_igreja_id_id_key unique (igreja_id, id)
            );
            """,
        )
        with pytest.raises(Exception) as raised:
            _execute_script(broken, MIGRATION.read_text(encoding="utf-8"))
        assert getattr(raised.value, "pgcode", None) == "P0001"
        assert "required root parent key is absent" in str(raised.value)
        with broken.connect() as connection:
            assert connection.execute(
                text("select to_regclass('public.e4b_consent_operations')")
            ).scalar_one() is None
    finally:
        if broken is not None:
            broken.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(
                "select pg_terminate_backend(pid) from pg_stat_activity "
                "where datname=%s and pid <> pg_backend_pid()",
                (child_name,),
            )
            connection.exec_driver_sql(f"drop database if exists {quoted}")
        admin.dispose()


def _assert_sqlstate(
    session: Session,
    statement: str,
    parameters: dict[str, object] | None,
    expected_sqlstate: str,
) -> None:
    """Executa uma tentativa isolada para não confundir falhas subsequentes."""

    try:
        with session.begin_nested():
            session.execute(text(statement), parameters or {})
    except DBAPIError as raised:
        assert getattr(raised.orig, "pgcode", None) == expected_sqlstate
    else:
        pytest.fail(f"a tentativa deveria falhar com SQLSTATE {expected_sqlstate}")


def _guc_source_payload(session: Session, tenant: uuid.UUID) -> dict[str, object]:
    """Lê uma cadeia ACCEPT/HOLD já válida para clonar INSERTs completos."""

    row = session.execute(
        text(
            "select operation.action, operation.origin, operation.origin_accept_operation_id, "
            "operation.origin_action, operation.titular_pessoa_id, "
            "operation.manifestante_pessoa_id, operation.responsavel_pessoa_id, "
            "operation.manifestant_role, operation.manifestant_relation_valid, "
            "operation.operator_id, operation.operator_kind, operation.operator_role_links, "
            "operation.server_resolved, operation.contract_version, operation.policy_version, "
            "operation.term_version, operation.content_digest, operation.fingerprint_version, "
            "operation.fingerprint, operation.concession_state, operation.operation_state, "
            "operation.confirmed_at, retention.retention_due_at, hold.hold_state, "
            "hold.policy_version as hold_policy_version, hold.applied_at, hold.resolved_at, "
            "event.event_kind, event.event_sequence, event.authority_app_user_id, "
            "event.authority_resolution_version, event.authority_resolution_sha256, "
            "event.policy_version as event_policy_version, event.occurred_at "
            "from public.e4b_consent_operations operation "
            "join public.e4b_consent_streams stream "
            "on stream.igreja_id=operation.igreja_id "
            "and stream.accept_operation_id=operation.operation_id "
            "join public.e4b_consent_receipts receipt "
            "on receipt.igreja_id=operation.igreja_id "
            "and receipt.operation_id=operation.operation_id "
            "join public.e4b_consent_retentions retention "
            "on retention.igreja_id=operation.igreja_id "
            "and retention.operation_id=operation.operation_id "
            "join public.e4b_consent_holds hold "
            "on hold.igreja_id=operation.igreja_id "
            "and hold.operation_id=operation.operation_id "
            "join public.e4b_consent_hold_events event "
            "on event.igreja_id=hold.igreja_id and event.hold_id=hold.hold_id "
            "and event.operation_id=hold.operation_id "
            "where operation.igreja_id=:tenant and operation.action='ACCEPT' "
            "and operation.operation_state='CONFIRMED' and stream.stream_state='ACTIVE' "
            "and hold.hold_state='ACTIVE' and event.event_kind='HOLD_APPLIED' "
            "and event.event_sequence=1 "
            "order by operation.confirmed_at, operation.operation_id limit 1"
        ),
        {"tenant": tenant},
    ).mappings().one()
    return dict(row)


def _guc_clone_payload(source: dict[str, object], tenant: uuid.UUID) -> dict[str, object]:
    """Gera identidades inéditas, mantendo os valores válidos da cadeia fonte."""

    suffix = uuid.uuid4().hex
    return {
        "igreja_id": tenant,
        "operation_id": uuid.uuid4(),
        "receipt_id": uuid.uuid4(),
        "hold_id": uuid.uuid4(),
        "hold_event_id": uuid.uuid4(),
        "idempotency_key": f"e4b:consent-operation:v1:guc-{suffix}",
        "correlation_id": uuid.uuid4(),
        # A finalidade é parte da unicidade do stream. Ela precisa ser nova
        # para que o INSERT próprio teste RLS, não uma colisão de índice.
        "finalidade_id": f"guc_{suffix}",
        "action": source["action"],
        "origin": source["origin"],
        "origin_accept_operation_id": source["origin_accept_operation_id"],
        "origin_action": source["origin_action"],
        "titular_pessoa_id": source["titular_pessoa_id"],
        "manifestante_pessoa_id": source["manifestante_pessoa_id"],
        "responsavel_pessoa_id": source["responsavel_pessoa_id"],
        "manifestant_role": source["manifestant_role"],
        "manifestant_relation_valid": source["manifestant_relation_valid"],
        "operator_id": source["operator_id"],
        "operator_kind": source["operator_kind"],
        "operator_role_links": source["operator_role_links"],
        "server_resolved": source["server_resolved"],
        "contract_version": source["contract_version"],
        "policy_version": source["policy_version"],
        "term_version": source["term_version"],
        "content_digest": source["content_digest"],
        "fingerprint_version": source["fingerprint_version"],
        "fingerprint": source["fingerprint"],
        "concession_state": source["concession_state"],
        "operation_state": source["operation_state"],
        "confirmed_at": source["confirmed_at"],
        "accept_action": "ACCEPT",
        "stream_state": "ACTIVE",
        "withdraw_operation_id": None,
        "withdraw_action": None,
        "receipt_origin": source["origin"],
        "retention_state": "RETENTION_RUNNING",
        "retention_anchor_at": source["confirmed_at"],
        "retention_due_at": source["retention_due_at"],
        "active_hold_count": 0,
        "suspension_started_at": None,
        "last_hold_event_at": None,
        "state_changed_at": source["confirmed_at"],
        "hold_state": source["hold_state"],
        "hold_policy_version": source["hold_policy_version"],
        "applied_at": source["applied_at"],
        "resolved_at": source["resolved_at"],
        "event_kind": source["event_kind"],
        "event_sequence": source["event_sequence"],
        "authority_app_user_id": source["authority_app_user_id"],
        "authority_resolution_version": source["authority_resolution_version"],
        "authority_resolution_sha256": bytes(source["authority_resolution_sha256"]),
        "event_policy_version": source["event_policy_version"],
        "occurred_at": source["occurred_at"],
    }


def _guc_insert_relation(session: Session, relation: str, payload: dict[str, object]) -> None:
    """Insere uma linha integral da relação indicada, sem SELECT vazio ou invisível."""

    statements = {
        "e4b_consent_operations": (
            "insert into public.e4b_consent_operations "
            "(igreja_id, operation_id, idempotency_key, correlation_id, action, origin, "
            "origin_accept_operation_id, origin_action, titular_pessoa_id, "
            "manifestante_pessoa_id, responsavel_pessoa_id, manifestant_role, "
            "manifestant_relation_valid, operator_id, operator_kind, operator_role_links, "
            "server_resolved, finalidade_id, contract_version, policy_version, term_version, "
            "content_digest, fingerprint_version, fingerprint, concession_state, "
            "operation_state, confirmed_at) values "
            "(:igreja_id, :operation_id, :idempotency_key, :correlation_id, :action, :origin, "
            ":origin_accept_operation_id, :origin_action, :titular_pessoa_id, "
            ":manifestante_pessoa_id, :responsavel_pessoa_id, :manifestant_role, "
            ":manifestant_relation_valid, :operator_id, :operator_kind, :operator_role_links, "
            ":server_resolved, :finalidade_id, :contract_version, :policy_version, :term_version, "
            ":content_digest, :fingerprint_version, :fingerprint, :concession_state, "
            ":operation_state, :confirmed_at)"
        ),
        "e4b_consent_streams": (
            "insert into public.e4b_consent_streams "
            "(igreja_id, titular_pessoa_id, finalidade_id, accept_operation_id, accept_action, "
            "stream_state, withdraw_operation_id, withdraw_action, state_changed_at) values "
            "(:igreja_id, :titular_pessoa_id, :finalidade_id, :operation_id, :accept_action, "
            ":stream_state, :withdraw_operation_id, :withdraw_action, :confirmed_at)"
        ),
        "e4b_consent_receipts": (
            "insert into public.e4b_consent_receipts "
            "(igreja_id, receipt_id, operation_id, correlation_id, action, origin, "
            "manifestant_role, concession_state, confirmed_at, contract_version, policy_version, "
            "term_version, content_digest, fingerprint_version, fingerprint) values "
            "(:igreja_id, :receipt_id, :operation_id, :correlation_id, :action, :receipt_origin, "
            ":manifestant_role, :concession_state, :confirmed_at, :contract_version, :policy_version, "
            ":term_version, :content_digest, :fingerprint_version, :fingerprint)"
        ),
        "e4b_consent_retentions": (
            "insert into public.e4b_consent_retentions "
            "(igreja_id, operation_id, retention_state, retention_anchor_at, retention_due_at, "
            "active_hold_count, suspension_started_at, last_hold_event_at, state_changed_at) values "
            "(:igreja_id, :operation_id, :retention_state, :retention_anchor_at, :retention_due_at, "
            ":active_hold_count, :suspension_started_at, :last_hold_event_at, :state_changed_at)"
        ),
        "e4b_consent_holds": (
            "insert into public.e4b_consent_holds "
            "(igreja_id, hold_id, operation_id, hold_state, policy_version, applied_at, resolved_at) "
            "values (:igreja_id, :hold_id, :operation_id, :hold_state, :hold_policy_version, "
            ":applied_at, :resolved_at)"
        ),
        "e4b_consent_hold_events": (
            "insert into public.e4b_consent_hold_events "
            "(igreja_id, hold_event_id, hold_id, operation_id, event_kind, event_sequence, "
            "authority_app_user_id, authority_resolution_version, authority_resolution_sha256, "
            "policy_version, occurred_at) values "
            "(:igreja_id, :hold_event_id, :hold_id, :operation_id, :event_kind, :event_sequence, "
            ":authority_app_user_id, :authority_resolution_version, :authority_resolution_sha256, "
            ":event_policy_version, :occurred_at)"
        ),
    }
    try:
        statement = statements[relation]
    except KeyError as error:
        raise AssertionError(f"relação GUC desconhecida: {relation}") from error
    result = session.execute(text(statement), payload)
    assert result.rowcount == 1


def _guc_stage_prefix(session: Session, relation: str, payload: dict[str, object]) -> None:
    """Materializa dependências válidas antes de uma tentativa negativa isolada."""

    try:
        target_index = RELATIONS.index(relation)
    except ValueError as error:
        raise AssertionError(f"relação GUC desconhecida: {relation}") from error
    for predecessor in RELATIONS[:target_index]:
        _guc_insert_relation(session, predecessor, payload)


def _guc_complete_chain(session: Session, payload: dict[str, object]) -> None:
    """Cria a cadeia completa e materializa a projeção antes dos triggers diferidos."""

    for relation in RELATIONS:
        _guc_insert_relation(session, relation, payload)
    session.execute(
        text(
            "update public.e4b_consent_retentions set retention_state='RETENTION_HELD', "
            "active_hold_count=1, suspension_started_at=:applied_at, "
            "last_hold_event_at=:occurred_at, state_changed_at=:occurred_at "
            "where igreja_id=:igreja_id and operation_id=:operation_id"
        ),
        payload,
    )
    session.execute(text("set constraints all immediate"))


def _guc_assert_insert_sqlstate(
    session: Session,
    relation: str,
    payload: dict[str, object],
    *,
    guc: str | None,
    expected_sqlstate: str,
) -> None:
    """Executa um INSERT real em savepoint e exige o erro de RLS esperado."""

    try:
        with session.begin_nested():
            # O owner descartável suspende somente os triggers do alvo dentro
            # do savepoint. Assim, a tentativa negativa prova o SQLSTATE da
            # WITH CHECK de RLS antes de uma guarda diferida consultar o
            # prefixo que ficou invisível sob a GUC adversarial.
            session.execute(text("reset role"))
            session.execute(
                text(f"alter table public.{relation} disable trigger user")
            )
            session.execute(text(f"set local role {CONTROLLER}"))
            session.execute(text(f"set local role {HARNESS}"))
            if guc is None:
                session.execute(text("reset app.tenant_igreja_id"))
            else:
                session.execute(
                    text("select set_config('app.tenant_igreja_id', :tenant, true)"),
                    {"tenant": guc},
                )
            _guc_insert_relation(session, relation, payload)
    except DBAPIError as raised:
        assert getattr(raised.orig, "pgcode", None) == expected_sqlstate
        assert session.execute(text("select current_user")).scalar_one() == HARNESS
        assert session.execute(
            text("select current_setting('app.tenant_igreja_id', true)")
        ).scalar_one() == str(payload["igreja_id"])
        assert session.execute(
            text(
                "select bool_and(trigger_row.tgenabled='O') "
                "from pg_catalog.pg_trigger trigger_row "
                "where trigger_row.tgrelid=cast(:relation as regclass) "
                "and not trigger_row.tgisinternal"
            ),
            {"relation": f"public.{relation}"},
        ).scalar_one() is True
    else:
        pytest.fail(f"o INSERT de {relation} deveria falhar com SQLSTATE {expected_sqlstate}")


class _C3ReadOnlyReconciliationPort(E4bReconciliationReadPort):
    """Porta de teste que reidrata uma cadeia confirmada em sessão nova."""

    def __init__(
        self,
        engine: Engine,
        *,
        force_unknown: bool = False,
    ) -> None:
        self._engine = engine
        self._force_unknown = force_unknown
        self.calls = 0
        self.effective_roles: list[str] = []
        self.transaction_read_only: list[str] = []

    def read_reconciliation_snapshot(self, request) -> E4bReconciliationSnapshot:
        self.calls += 1
        with _oracle_session(
            self._engine,
            tenant=request.igreja_id,
            read_only=True,
        ) as session:
            self.effective_roles.append(
                str(session.execute(text("select current_user")).scalar_one())
            )
            self.transaction_read_only.append(
                str(session.execute(text("show transaction_read_only")).scalar_one())
            )
            row = session.execute(
                text(
                    "select operation.igreja_id as operation_igreja_id, "
                    "operation.operation_id as operation_id, "
                    "operation.idempotency_key as operation_idempotency_key, "
                    "operation.origin_accept_operation_id as operation_origin_accept_operation_id, "
                    "operation.titular_pessoa_id as operation_titular_pessoa_id, "
                    "operation.manifestante_pessoa_id as operation_manifestante_pessoa_id, "
                    "operation.responsavel_pessoa_id as operation_responsavel_pessoa_id, "
                    "operation.operator_id as operation_operator_id, "
                    "operation.operator_kind as operation_operator_kind, "
                    "operation.operator_role_links as operation_operator_role_links, "
                    "operation.finalidade_id as operation_finalidade_id, "
                    "receipt.receipt_id as receipt_id, "
                    "receipt.igreja_id as receipt_igreja_id, "
                    "receipt.operation_id as receipt_operation_id, "
                    "receipt.correlation_id as receipt_correlation_id, "
                    "receipt.action as receipt_action, receipt.origin as receipt_origin, "
                    "receipt.manifestant_role as receipt_manifestant_role, "
                    "receipt.concession_state as receipt_concession_state, "
                    "receipt.confirmed_at as receipt_confirmed_at, "
                    "receipt.contract_version as receipt_contract_version, "
                    "receipt.policy_version as receipt_policy_version, "
                    "receipt.term_version as receipt_term_version, "
                    "receipt.content_digest as receipt_content_digest, "
                    "receipt.fingerprint_version as receipt_fingerprint_version, "
                    "receipt.fingerprint as receipt_fingerprint, "
                    "operation.correlation_id as operation_correlation_id, "
                    "operation.action as operation_action, operation.origin as operation_origin, "
                    "operation.manifestant_role as operation_manifestant_role, "
                    "operation.concession_state as operation_concession_state, "
                    "operation.confirmed_at as operation_confirmed_at, "
                    "operation.contract_version as operation_contract_version, "
                    "operation.policy_version as operation_policy_version, "
                    "operation.term_version as operation_term_version, "
                    "operation.content_digest as operation_content_digest, "
                    "operation.fingerprint_version as operation_fingerprint_version, "
                    "operation.fingerprint as operation_fingerprint "
                    "from public.e4b_consent_operations operation "
                    "join public.e4b_consent_receipts receipt "
                    "on receipt.igreja_id=operation.igreja_id "
                    "and receipt.operation_id=operation.operation_id "
                    "where operation.igreja_id=:igreja_id "
                    "and operation.operation_id=:operation_id "
                    "and operation.operation_state='CONFIRMED'"
                ),
                {
                    "igreja_id": request.igreja_id,
                    "operation_id": request.selector.operation_id,
                },
            ).mappings().one_or_none()
        provenance = E4bSnapshotProvenance(
            igreja_id=request.igreja_id,
            origin=E4bOrigin.E4B,
        )

        def unknown_snapshot() -> E4bReconciliationSnapshot:
            return E4bReconciliationSnapshot(
                igreja_id=request.igreja_id,
                selector=request.selector,
                provenance=provenance,
                observation=E4bReconciliationObservation.UNKNOWN,
                operation=None,
            )

        if self._force_unknown:
            return unknown_snapshot()
        if row is None:
            return E4bReconciliationSnapshot(
                igreja_id=request.igreja_id,
                selector=request.selector,
                provenance=provenance,
                observation=E4bReconciliationObservation.NOT_FOUND,
                operation=None,
            )
        projection_pairs = (
            ("operation_igreja_id", "receipt_igreja_id"),
            ("operation_id", "receipt_operation_id"),
            ("operation_correlation_id", "receipt_correlation_id"),
            ("operation_action", "receipt_action"),
            ("operation_origin", "receipt_origin"),
            ("operation_manifestant_role", "receipt_manifestant_role"),
            ("operation_concession_state", "receipt_concession_state"),
            ("operation_confirmed_at", "receipt_confirmed_at"),
            ("operation_contract_version", "receipt_contract_version"),
            ("operation_policy_version", "receipt_policy_version"),
            ("operation_term_version", "receipt_term_version"),
            ("operation_content_digest", "receipt_content_digest"),
            ("operation_fingerprint_version", "receipt_fingerprint_version"),
            ("operation_fingerprint", "receipt_fingerprint"),
        )
        if any(row[operation_field] != row[receipt_field] for operation_field, receipt_field in projection_pairs):
            return unknown_snapshot()
        try:
            origin = E4bOrigin(row["receipt_origin"])
            action = E4bAction(row["receipt_action"])
            authority = E4bAuthorityResolution(
                igreja_id=row["operation_igreja_id"],
                titular_pessoa_id=row["operation_titular_pessoa_id"],
                manifestante_pessoa_id=row["operation_manifestante_pessoa_id"],
                manifestant_role=E4bManifestantRole(row["receipt_manifestant_role"]),
                responsavel_pessoa_id=row["operation_responsavel_pessoa_id"],
                operador_id=row["operation_operator_id"],
                operator_kind=E4bOperatorKind(row["operation_operator_kind"]),
                finalidade_id=row["operation_finalidade_id"],
                origin=origin,
                correlation_id=row["receipt_correlation_id"],
                contract_version=row["receipt_contract_version"],
                policy_version=row["receipt_policy_version"],
                term_version=row["receipt_term_version"],
                content_digest=row["receipt_content_digest"],
                operator_role_links=frozenset(
                    E4bRole(role) for role in row["operation_operator_role_links"]
                ),
            )
            idempotency_key = E4bIdempotencyKey(
                igreja_id=row["operation_igreja_id"],
                value=row["operation_idempotency_key"],
            )
            fingerprint = E4bFingerprint(row["receipt_fingerprint"])
            operation = E4bConfirmedOperation(
                operation_id=row["operation_id"],
                igreja_id=row["operation_igreja_id"],
                idempotency_key=idempotency_key,
                correlation_id=row["receipt_correlation_id"],
                fingerprint=fingerprint,
                action=action,
                origin=origin,
                titular_pessoa_id=row["operation_titular_pessoa_id"],
                manifestante_pessoa_id=row["operation_manifestante_pessoa_id"],
                manifestant_role=E4bManifestantRole(row["receipt_manifestant_role"]),
                responsavel_pessoa_id=row["operation_responsavel_pessoa_id"],
                operador_id=row["operation_operator_id"],
                finalidade_id=row["operation_finalidade_id"],
                origin_accept_operation_id=row["operation_origin_accept_operation_id"],
                concession_state=E4bConcessionState(row["receipt_concession_state"]),
                receipt_id=row["receipt_id"],
                confirmed_at=row["receipt_confirmed_at"],
                contract_version=row["receipt_contract_version"],
                policy_version=row["receipt_policy_version"],
                term_version=row["receipt_term_version"],
                content_digest=row["receipt_content_digest"],
            )
            historical_identity = E4bHistoricalOperationIdentity(
                igreja_id=row["operation_igreja_id"],
                operation_id=row["operation_id"],
                receipt_id=row["receipt_id"],
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
                authority=authority,
                action=action,
                origin_accept_operation_id=row["operation_origin_accept_operation_id"],
            )
        except (TypeError, ValueError):
            return unknown_snapshot()
        return E4bReconciliationSnapshot(
            igreja_id=request.igreja_id,
            selector=request.selector,
            provenance=provenance,
            observation=E4bReconciliationObservation.CONFIRMED,
            operation=operation,
            historical_identity=historical_identity,
        )


@pytest.mark.rls_integration
def test_e4b_pg17_catalog_001_matches_r4_manifest(e4b_pg17_engine: Engine) -> None:
    with e4b_pg17_engine.connect() as connection:
        relations = connection.execute(
            text(
                "select relname from pg_catalog.pg_class c join pg_catalog.pg_namespace n "
                "on n.oid=c.relnamespace where n.nspname='public' and c.relkind='r' "
                "and c.relname like 'e4b_consent_%' order by relname"
            )
        ).scalars().all()
        assert relations == sorted(RELATIONS)
        non_table_e4b_objects = connection.execute(
            text(
                "select relname from pg_catalog.pg_class relation "
                "join pg_catalog.pg_namespace namespace on namespace.oid=relation.relnamespace "
                "where namespace.nspname='public' and relname like 'e4b_consent_%' "
                "and relkind in ('S', 'v', 'm') order by relname"
            )
        ).scalars().all()
        assert non_table_e4b_objects == []
        assert connection.execute(
            text(
                "select typname from pg_catalog.pg_type type_row "
                "join pg_catalog.pg_namespace namespace on namespace.oid=type_row.typnamespace "
                "where namespace.nspname='public' and typtype='e' and typname like 'e4b_consent_%'"
            )
        ).scalars().all() == []
        column_rows = connection.execute(
            text(
                "select relation_row.relname, attribute_row.attname, "
                "pg_catalog.format_type(attribute_row.atttypid, attribute_row.atttypmod), "
                "attribute_row.attnotnull, "
                "pg_catalog.pg_get_expr(default_row.adbin, default_row.adrelid) "
                "from pg_catalog.pg_class relation_row "
                "join pg_catalog.pg_namespace namespace on namespace.oid=relation_row.relnamespace "
                "join pg_catalog.pg_attribute attribute_row on attribute_row.attrelid=relation_row.oid "
                "left join pg_catalog.pg_attrdef default_row on default_row.adrelid=relation_row.oid "
                "and default_row.adnum=attribute_row.attnum "
                "where namespace.nspname='public' and relation_row.relname = any(:relations) "
                "and attribute_row.attnum > 0 and not attribute_row.attisdropped "
                "order by relation_row.relname, attribute_row.attnum"
            ),
            {"relations": list(RELATIONS)},
        ).all()
        actual_columns: dict[str, list[tuple[object, ...]]] = {relation: [] for relation in RELATIONS}
        for relation, name, type_name, not_null, default in column_rows:
            actual_columns[str(relation)].append(
                (str(name), str(type_name), bool(not_null), _normalise_catalog_sql(default))
            )
        assert actual_columns == {
            relation: [
                (name, type_name, not_null, _normalise_catalog_sql(default))
                for name, type_name, not_null, default in expected
            ]
            for relation, expected in CATALOG_COLUMNS.items()
        }
        key_rows = connection.execute(
            text(
                "select constraint_row.conname, constraint_row.contype, relation_row.relname, "
                "array_agg(attribute_row.attname order by mapping.ordinality) "
                "from pg_catalog.pg_constraint constraint_row "
                "join pg_catalog.pg_class relation_row on relation_row.oid=constraint_row.conrelid "
                "join pg_catalog.pg_namespace namespace on namespace.oid=relation_row.relnamespace "
                "join lateral pg_catalog.unnest(constraint_row.conkey) with ordinality "
                "as mapping(attnum, ordinality) on true "
                "join pg_catalog.pg_attribute attribute_row on attribute_row.attrelid=relation_row.oid "
                "and attribute_row.attnum=mapping.attnum "
                "where namespace.nspname='public' and relation_row.relname = any(:relations) "
                "and constraint_row.contype in ('p', 'u') "
                "group by constraint_row.conname, constraint_row.contype, relation_row.relname "
                "order by constraint_row.conname"
            ),
            {"relations": list(RELATIONS)},
        ).all()
        actual_primary = {
            str(name): (str(relation), tuple(columns))
            for name, kind, relation, columns in key_rows
            if kind == "p"
        }
        actual_unique = {
            str(name): (str(relation), tuple(columns))
            for name, kind, relation, columns in key_rows
            if kind == "u"
        }
        assert actual_primary == EXPECTED_PRIMARY_KEYS
        assert actual_unique == EXPECTED_UNIQUE_KEYS
        foreign_key_rows = connection.execute(
            text(
                "select constraint_row.conname, local_relation.relname, foreign_relation.relname, "
                "array_agg(local_attribute.attname order by mapping.ordinality), "
                "array_agg(foreign_attribute.attname order by mapping.ordinality), "
                "constraint_row.confupdtype, constraint_row.confdeltype "
                "from pg_catalog.pg_constraint constraint_row "
                "join pg_catalog.pg_class local_relation on local_relation.oid=constraint_row.conrelid "
                "join pg_catalog.pg_namespace local_namespace on local_namespace.oid=local_relation.relnamespace "
                "join pg_catalog.pg_class foreign_relation on foreign_relation.oid=constraint_row.confrelid "
                "join lateral pg_catalog.unnest(constraint_row.conkey) with ordinality "
                "as mapping(local_attnum, ordinality) on true "
                "join pg_catalog.pg_attribute local_attribute on local_attribute.attrelid=local_relation.oid "
                "and local_attribute.attnum=mapping.local_attnum "
                "join pg_catalog.pg_attribute foreign_attribute on foreign_attribute.attrelid=foreign_relation.oid "
                "and foreign_attribute.attnum=constraint_row.confkey[mapping.ordinality::integer] "
                "where local_namespace.nspname='public' and local_relation.relname = any(:relations) "
                "and constraint_row.contype='f' "
                "and pg_catalog.array_length(constraint_row.conkey, 1) "
                "= pg_catalog.array_length(constraint_row.confkey, 1) "
                "group by constraint_row.conname, local_relation.relname, foreign_relation.relname, "
                "constraint_row.confupdtype, constraint_row.confdeltype "
                "order by constraint_row.conname"
            ),
            {"relations": list(RELATIONS)},
        ).all()
        actual_foreign_keys = {
            str(name): (str(local), tuple(local_columns), str(foreign), tuple(foreign_columns))
            for name, local, foreign, local_columns, foreign_columns, update_action, delete_action in foreign_key_rows
            if update_action == "r" and delete_action == "r"
        }
        assert len(foreign_key_rows) == len(EXPECTED_FOREIGN_KEYS)
        assert actual_foreign_keys == EXPECTED_FOREIGN_KEYS
        assert all(row[-2:] == ("r", "r") for row in foreign_key_rows)
        check_rows = connection.execute(
            text(
                "select constraint_row.conname, pg_catalog.pg_get_constraintdef(constraint_row.oid, true) "
                "from pg_catalog.pg_constraint constraint_row "
                "join pg_catalog.pg_class relation_row on relation_row.oid=constraint_row.conrelid "
                "join pg_catalog.pg_namespace namespace on namespace.oid=relation_row.relnamespace "
                "where namespace.nspname='public' and relation_row.relname = any(:relations) "
                "and constraint_row.contype='c' order by constraint_row.conname"
            ),
            {"relations": list(RELATIONS)},
        ).all()
        actual_checks = {str(name): _normalise_catalog_sql(definition) or "" for name, definition in check_rows}
        assert set(actual_checks) == set(EXPECTED_CHECK_CONSTRAINTS)
        for name, fragments in EXPECTED_CHECK_CONSTRAINTS.items():
            definition = actual_checks[name]
            assert all(fragment.lower() in definition.lower() for fragment in fragments)
        assert "RETENTION_ELIGIBLE" not in actual_checks["e4b_consent_retentions_state_check"]
        index_rows = connection.execute(
            text(
                "select index_relation.relname, relation_row.relname, index_row.indisunique, "
                "index_row.indisprimary, pg_catalog.pg_get_indexdef(index_row.indexrelid), "
                "pg_catalog.pg_get_expr(index_row.indpred, index_row.indrelid) "
                "from pg_catalog.pg_index index_row "
                "join pg_catalog.pg_class index_relation on index_relation.oid=index_row.indexrelid "
                "join pg_catalog.pg_class relation_row on relation_row.oid=index_row.indrelid "
                "join pg_catalog.pg_namespace namespace on namespace.oid=relation_row.relnamespace "
                "where namespace.nspname='public' and relation_row.relname = any(:relations) "
                "order by index_relation.relname"
            ),
            {"relations": list(RELATIONS)},
        ).all()
        assert {str(row[0]) for row in index_rows} == set(EXPECTED_INDEXES)
        for name, relation, unique, primary, definition, predicate in index_rows:
            expected_relation, expected_unique, expected_primary, fragments, expected_predicate = EXPECTED_INDEXES[str(name)]
            assert (str(relation), bool(unique), bool(primary)) == (
                expected_relation,
                expected_unique,
                expected_primary,
            )
            normalised_definition = _normalise_catalog_sql(definition) or ""
            assert all(fragment in normalised_definition for fragment in fragments)
            normalised_predicate = _normalise_catalog_sql(predicate)
            if expected_predicate is None:
                assert normalised_predicate is None
            else:
                assert _normalise_catalog_sql(expected_predicate) in (normalised_predicate or "")
        guard_rows = connection.execute(
            text(
                "select proname, prosecdef, prokind, pronargs from pg_catalog.pg_proc procedure_row "
                "join pg_catalog.pg_namespace namespace on namespace.oid=procedure_row.pronamespace "
                "where namespace.nspname='public' and proname = any(:names) order by proname"
            ),
            {"names": list(GUARD_FUNCTIONS)},
        ).all()
        assert [row[0] for row in guard_rows] == sorted(GUARD_FUNCTIONS)
        assert all(row[1:] == (False, "f", 0) for row in guard_rows)
        e4b_functions = connection.execute(
            text(
                "select proname from pg_catalog.pg_proc procedure_row "
                "join pg_catalog.pg_namespace namespace on namespace.oid=procedure_row.pronamespace "
                "where namespace.nspname='public' and proname like 'e4b_consent_%' order by proname"
            )
        ).scalars().all()
        assert e4b_functions == sorted(GUARD_FUNCTIONS)
        trigger_rows = connection.execute(
            text(
                "select trigger_row.tgname, relation_row.relname, "
                "(trigger_row.tgtype::integer & 4) <> 0 as on_insert, "
                "(trigger_row.tgtype::integer & 16) <> 0 as on_update, "
                "(trigger_row.tgtype::integer & 8) <> 0 as on_delete, "
                "(trigger_row.tgtype::integer & 2) = 0 as after_timing, "
                "(trigger_row.tgtype::integer & 1) <> 0 as row_level, "
                "trigger_row.tgdeferrable, trigger_row.tginitdeferred, trigger_row.tgconstraint <> 0 "
                "from pg_catalog.pg_trigger trigger_row "
                "join pg_catalog.pg_class relation_row on relation_row.oid=trigger_row.tgrelid "
                "where trigger_row.tgname = any(:names) and not trigger_row.tgisinternal "
                "order by trigger_row.tgname"
            ),
            {"names": list(ALL_TRIGGER_EVENTS)},
        ).all()
        assert len(trigger_rows) == len(ALL_TRIGGER_EVENTS)
        for row in trigger_rows:
            assert row[1:] == ALL_TRIGGER_EVENTS[str(row[0])]
        receipt_columns = connection.execute(
            text(
                "select attname from pg_catalog.pg_attribute "
                "where attrelid='public.e4b_consent_receipts'::regclass "
                "and attnum > 0 and not attisdropped order by attnum"
            )
        ).scalars().all()
        assert tuple(receipt_columns) == RECEIPT_ALLOWLIST
        receipt_nullability = connection.execute(
            text(
                "select bool_and(attnotnull) from pg_catalog.pg_attribute "
                "where attrelid='public.e4b_consent_receipts'::regclass "
                "and attnum > 0 and not attisdropped"
            )
        ).scalar_one()
        assert receipt_nullability is True
        assert {
            "titular_pessoa_id",
            "manifestante_pessoa_id",
            "responsavel_pessoa_id",
            "operator_id",
            "operator_role_links",
            "finalidade_id",
            "idempotency_key",
            "receipt_state",
        }.isdisjoint(receipt_columns)


@pytest.mark.rls_integration
def test_e4b_pg17_parent_001_requires_synthetic_parent_anchors(
    e4b_pg17_engine: Engine,
) -> None:
    with e4b_pg17_engine.connect() as connection:
        root_key = connection.execute(
            text(
                "select constraint_row.contype, array_agg(attribute_row.attname order by mapping.ordinality) "
                "from pg_catalog.pg_constraint constraint_row "
                "join lateral pg_catalog.unnest(constraint_row.conkey) with ordinality "
                "as mapping(attnum, ordinality) on true "
                "join pg_catalog.pg_attribute attribute_row "
                "on attribute_row.attrelid=constraint_row.conrelid "
                "and attribute_row.attnum=mapping.attnum "
                "where constraint_row.conrelid='public.igrejas'::regclass "
                "and constraint_row.contype in ('p', 'u') "
                "group by constraint_row.contype"
            )
        ).all()
        assert ("p", ["id"]) in root_key
        parent_keys = connection.execute(
            text(
                "select conname from pg_catalog.pg_constraint "
                "where conname in ('pessoas_igreja_id_id_key', 'app_users_igreja_id_id_key') "
                "order by conname"
            )
        ).scalars().all()
        assert parent_keys == ["app_users_igreja_id_id_key", "pessoas_igreja_id_id_key"]
        source = MIGRATION.read_text(encoding="utf-8")
        assert "required root parent key is absent" in source
        assert source.index("required root parent key is absent") < source.index(
            "create table public.e4b_consent_operations"
        )
    _assert_missing_root_key_blocks_before_e4b_ddl(e4b_pg17_engine)


@pytest.mark.rls_integration
def test_e4b_pg17_rls_001_enforces_force_and_tenant_policies(
    e4b_pg17_engine: Engine,
) -> None:
    with e4b_pg17_engine.connect() as connection:
        for relation in RELATIONS:
            assert connection.execute(
                text(
                    "select relrowsecurity, relforcerowsecurity from pg_catalog.pg_class "
                    "where oid=to_regclass(:relation)"
                ),
                {"relation": f"public.{relation}"},
            ).one() == (True, True)
        policies = connection.execute(
            text(
                "select policy_row.polname, relation_row.relname, policy_row.polpermissive, "
                "policy_row.polcmd::text, policy_row.polroles, "
                "pg_catalog.pg_get_expr(policy_row.polqual, policy_row.polrelid), "
                "pg_catalog.pg_get_expr(policy_row.polwithcheck, policy_row.polrelid) "
                "from pg_catalog.pg_policy policy_row "
                "join pg_catalog.pg_class relation_row on relation_row.oid=policy_row.polrelid "
                "join pg_catalog.pg_namespace namespace on namespace.oid=relation_row.relnamespace "
                "where namespace.nspname='public' and relation_row.relname = any(:relations) "
                "order by policy_row.polname"
            ),
            {"relations": list(RELATIONS)},
        ).all()
        expected_names = {
            f"e4b_{prefix}_tenant_{mode}"
            for prefix in POLICY_PREFIXES
            for mode in ("permissive", "restrictive")
        }
        assert {row[0] for row in policies} == expected_names
        assert len(policies) == 12
        for name, relation, permissive, command, roles, using, with_check in policies:
            assert relation in RELATIONS
            assert command == "*"
            assert roles == [0]
            assert permissive is name.endswith("_permissive")
            assert using is not None and with_check is not None
            for expression in (using, with_check):
                assert "current_setting" in expression
                assert "app.tenant_igreja_id" in expression
                assert "nullif" in expression.lower()
                assert "::uuid" in expression


@pytest.mark.rls_integration
def test_e4b_pg17_guc_001_exercises_positive_and_negative_tenant_matrix(
    e4b_pg17_engine: Engine,
) -> None:
    accepts = (
        (_stage_accept(e4b_pg17_engine, _accept_request(TENANT_A, PERSON_A)), USER_A),
        (_stage_accept(e4b_pg17_engine, _accept_request(TENANT_B, PERSON_B)), USER_B),
    )
    for accept, user_id in accepts:
        tenant = accept.intent.authority.igreja_id
        with _harness_session(e4b_pg17_engine, tenant) as session:
            result = PostgresE4bConsentStagingAdapter(session).stage_hold(
                _hold_request(
                    E4bHoldAction.APPLY,
                    tenant=tenant,
                    operation_id=accept.operation_id,
                    user_id=user_id,
                )
            )
            assert result.outcome is E4bStagingOutcome.STAGED
    matrix_log: list[tuple[str, str, str, str, str, int | str]] = []
    source_payloads: dict[uuid.UUID, dict[str, object]] = {}

    # Cada INSERT positivo percorre as seis relações com valores completos de
    # uma cadeia já válida. O savepoint deixa a base exatamente como a recebeu.
    for tenant in (TENANT_A, TENANT_B):
        with _oracle_session(e4b_pg17_engine, tenant=tenant) as session:
            assert session.execute(text("select current_user")).scalar_one() == HARNESS
            source = _guc_source_payload(session, tenant)
            source_payloads[tenant] = source
            before = {
                relation: int(
                    session.execute(text(f"select count(*) from public.{relation}")).scalar_one()
                )
                for relation in RELATIONS
            }
            with session.begin_nested() as savepoint:
                _guc_complete_chain(session, _guc_clone_payload(source, tenant))
                for relation in RELATIONS:
                    assert int(
                        session.execute(text(f"select count(*) from public.{relation}")).scalar_one()
                    ) == before[relation] + 1
                    matrix_log.append(
                        (relation, "INSERT", str(tenant), "valid", HARNESS, 1)
                    )
                savepoint.rollback()
            assert {
                relation: int(
                    session.execute(text(f"select count(*) from public.{relation}")).scalar_one()
                )
                for relation in RELATIONS
            } == before
    for tenant, other in ((TENANT_A, TENANT_B), (TENANT_B, TENANT_A)):
        with _oracle_session(e4b_pg17_engine, tenant=tenant) as session:
            assert session.execute(text("select current_user")).scalar_one() == HARNESS
            for relation in RELATIONS:
                assert _count(e4b_pg17_engine, relation, tenant) >= 1
                own_count = int(
                    session.execute(
                        text(f"select count(*) from public.{relation} where igreja_id=:tenant"),
                        {"tenant": tenant},
                    ).scalar_one()
                )
                assert own_count >= 1
                matrix_log.append((relation, "SELECT", str(tenant), "valid", HARNESS, own_count))
                assert session.execute(
                    text(f"select count(*) from public.{relation} where igreja_id=:other"),
                    {"other": other},
                ).scalar_one() == 0
                assert session.execute(
                    text(
                        f"update public.{relation} set igreja_id=igreja_id "
                        "where igreja_id=:other"
                    ),
                    {"other": other},
                ).rowcount == 0
                matrix_log.append((relation, "UPDATE", str(other), "divergent", HARNESS, 0))
                assert session.execute(
                    text(f"delete from public.{relation} where igreja_id=:other"),
                    {"other": other},
                ).rowcount == 0
                matrix_log.append((relation, "DELETE", str(other), "divergent", HARNESS, 0))

    # A tentativa divergente tem dependências materializadas para que o 42501
    # só possa representar a WITH CHECK de RLS, não FK, CHECK ou trigger.
    for tenant, other in ((TENANT_A, TENANT_B), (TENANT_B, TENANT_A)):
        with _oracle_session(e4b_pg17_engine, tenant=other) as session:
            source = _guc_source_payload(session, other)
            before = {
                relation: int(
                    session.execute(text(f"select count(*) from public.{relation}")).scalar_one()
                )
                for relation in RELATIONS
            }
            for relation in RELATIONS:
                with session.begin_nested() as savepoint:
                    payload = _guc_clone_payload(source, other)
                    _guc_stage_prefix(session, relation, payload)
                    _guc_assert_insert_sqlstate(
                        session,
                        relation,
                        payload,
                        guc=str(tenant),
                        expected_sqlstate="42501",
                    )
                    savepoint.rollback()
                assert {
                    current_relation: int(
                        session.execute(
                            text(f"select count(*) from public.{current_relation}")
                        ).scalar_one()
                    )
                    for current_relation in RELATIONS
                } == before
                matrix_log.append((relation, "INSERT", str(other), "divergent", HARNESS, "42501"))
    for mode, guc in (("missing", None), ("empty", "")):
        with _oracle_session(e4b_pg17_engine, tenant=guc) as session:
            assert session.execute(text("select current_user")).scalar_one() == HARNESS
            for relation in RELATIONS:
                assert session.execute(text(f"select count(*) from public.{relation}")).scalar_one() == 0
                assert session.execute(
                    text(f"update public.{relation} set igreja_id=igreja_id where igreja_id=:tenant"),
                    {"tenant": TENANT_A},
                ).rowcount == 0
                assert session.execute(
                    text(f"delete from public.{relation} where igreja_id=:tenant"),
                    {"tenant": TENANT_A},
                ).rowcount == 0
                matrix_log.extend(
                    (relation, operation, str(TENANT_A), mode, HARNESS, 0)
                    for operation in ("SELECT", "UPDATE", "DELETE")
                )

        # O prefixo nasce sob o tenant correto e só a GUC da tentativa muda.
        # RESET e string vazia cobrem separadamente os dois estados sem tenant.
        with _oracle_session(e4b_pg17_engine, tenant=TENANT_A) as session:
            source = source_payloads[TENANT_A]
            before = {
                relation: int(
                    session.execute(text(f"select count(*) from public.{relation}")).scalar_one()
                )
                for relation in RELATIONS
            }
            for relation in RELATIONS:
                with session.begin_nested() as savepoint:
                    payload = _guc_clone_payload(source, TENANT_A)
                    _guc_stage_prefix(session, relation, payload)
                    _guc_assert_insert_sqlstate(
                        session,
                        relation,
                        payload,
                        guc=guc,
                        expected_sqlstate="42501",
                    )
                    savepoint.rollback()
                assert {
                    current_relation: int(
                        session.execute(
                            text(f"select count(*) from public.{current_relation}")
                        ).scalar_one()
                    )
                    for current_relation in RELATIONS
                } == before
                matrix_log.append((relation, "INSERT", str(TENANT_A), mode, HARNESS, "42501"))
    with _oracle_session(e4b_pg17_engine, tenant="not-a-uuid") as session:
        assert session.execute(text("select current_user")).scalar_one() == HARNESS
        for relation in RELATIONS:
            for operation, statement in (
                ("SELECT", f"select count(*) from public.{relation}"),
                ("UPDATE", f"update public.{relation} set igreja_id=igreja_id"),
                ("DELETE", f"delete from public.{relation}"),
            ):
                _assert_sqlstate(session, statement, None, "22P02")
                matrix_log.append((relation, operation, "invalid", "malformed", HARNESS, "22P02"))

    with _oracle_session(e4b_pg17_engine, tenant=TENANT_A) as session:
        source = source_payloads[TENANT_A]
        before = {
            relation: int(
                session.execute(text(f"select count(*) from public.{relation}")).scalar_one()
            )
            for relation in RELATIONS
        }
        for relation in RELATIONS:
            with session.begin_nested() as savepoint:
                payload = _guc_clone_payload(source, TENANT_A)
                _guc_stage_prefix(session, relation, payload)
                _guc_assert_insert_sqlstate(
                    session,
                    relation,
                    payload,
                    guc="not-a-uuid",
                    expected_sqlstate="22P02",
                )
                savepoint.rollback()
            assert {
                current_relation: int(
                    session.execute(
                        text(f"select count(*) from public.{current_relation}")
                    ).scalar_one()
                )
                for current_relation in RELATIONS
            } == before
            matrix_log.append((relation, "INSERT", "invalid", "malformed", HARNESS, "22P02"))

    assert len(matrix_log) == len(RELATIONS) * (10 + 8 + 4)


@pytest.mark.rls_integration
def test_e4b_pg17_acl_001_verifies_revokes_and_ephemeral_memberships(
    e4b_pg17_engine: Engine,
) -> None:
    with e4b_pg17_engine.connect() as connection:
        grants = connection.execute(
            text(
                "select count(*) from information_schema.role_table_grants "
                "where table_schema='public' and table_name like 'e4b_consent_%' "
                "and grantee in ('PUBLIC', 'anon', 'authenticated', 'service_role', 'agent_runtime')"
            )
        ).scalar_one()
        assert grants == 0
        harness_grants = connection.execute(
            text(
                "select table_name, privilege_type from information_schema.role_table_grants "
                "where table_schema='public' and table_name = any(:relations) "
                "and grantee=:harness order by privilege_type"
            ),
            {"harness": HARNESS, "relations": list(RELATIONS)},
        ).all()
        assert {(row[0], row[1]) for row in harness_grants} == {
            (relation, privilege)
            for relation in RELATIONS
            for privilege in ("DELETE", "INSERT", "SELECT", "UPDATE")
        }
        schema_acl = connection.execute(
            text(
                "select has_schema_privilege(:role, 'public', 'USAGE'), "
                "has_schema_privilege(:role, 'public', 'CREATE')"
            ),
            {"role": HARNESS},
        ).one()
        assert schema_acl == (True, False)
        parent_acl = connection.execute(
            text(
                "select has_table_privilege(:role, 'public.pessoas', 'SELECT'), "
                "has_table_privilege(:role, 'public.app_users', 'SELECT')"
            ),
            {"role": HARNESS},
        ).one()
        assert parent_acl == (False, False)
        for role in NEGATIVE_ROLES:
            for relation in RELATIONS:
                privileges = connection.execute(
                    text(
                        "select has_table_privilege(:role, :relation, 'SELECT'), "
                        "has_table_privilege(:role, :relation, 'INSERT'), "
                        "has_table_privilege(:role, :relation, 'UPDATE'), "
                        "has_table_privilege(:role, :relation, 'DELETE'), "
                        "has_table_privilege(:role, :relation, 'TRUNCATE'), "
                        "has_table_privilege(:role, :relation, 'REFERENCES'), "
                        "has_table_privilege(:role, :relation, 'TRIGGER')"
                    ),
                    {"role": role, "relation": f"public.{relation}"},
                ).one()
                assert privileges == (False, False, False, False, False, False, False)
        for role in (HARNESS,) + NEGATIVE_ROLES:
            function_acl = connection.execute(
                text(
                    "select bool_and(not has_function_privilege(:role, procedure_row.oid, 'EXECUTE')) "
                    "from pg_catalog.pg_proc procedure_row "
                    "join pg_catalog.pg_namespace namespace on namespace.oid=procedure_row.pronamespace "
                    "where namespace.nspname='public' and procedure_row.proname = any(:functions)"
                ),
                {"role": role, "functions": list(GUARD_FUNCTIONS)},
            ).scalar_one()
            assert function_acl is True
        harness_flags = connection.execute(
            text(
                "select rolcanlogin, rolinherit, rolsuper, rolcreatedb, rolcreaterole, "
                "rolreplication, rolbypassrls from pg_catalog.pg_roles where rolname=:role"
            ),
            {"role": HARNESS},
        ).one()
        assert harness_flags == (False, False, False, False, False, False, False)
        controller_flags = connection.execute(
            text(
                "select rolcanlogin, rolinherit, rolsuper, rolcreatedb, rolcreaterole, "
                "rolreplication, rolbypassrls from pg_catalog.pg_roles where rolname=:role"
            ),
            {"role": CONTROLLER},
        ).one()
        assert controller_flags == (True, False, False, False, False, False, False)
        assert connection.execute(
            text(
                "select count(*) from pg_catalog.pg_auth_members membership "
                "join pg_catalog.pg_roles member on member.oid=membership.member "
                "where member.rolname=:harness"
            ),
            {"harness": HARNESS},
        ).scalar_one() == 0
        memberships = connection.execute(
            text(
                "select parent.rolname, m.admin_option, m.inherit_option, m.set_option "
                "from pg_catalog.pg_auth_members m join pg_catalog.pg_roles member on member.oid=m.member "
                "join pg_catalog.pg_roles parent on parent.oid=m.roleid "
                "where member.rolname=:controller order by parent.rolname"
            ),
            {"controller": CONTROLLER},
        ).all()
        assert [row[0] for row in memberships] == sorted((HARNESS,) + NEGATIVE_ROLES)
        assert all(row[1:] == (False, False, True) for row in memberships)
        controller_grants = connection.execute(
            text(
                "select count(*) from information_schema.role_table_grants "
                "where table_schema='public' and table_name = any(:relations) and grantee=:controller"
            ),
            {"relations": list(RELATIONS), "controller": CONTROLLER},
        ).scalar_one()
        assert controller_grants == 0
    for role in (HARNESS,) + NEGATIVE_ROLES:
        with _oracle_session(
            e4b_pg17_engine,
            role=role,
            tenant=TENANT_A if role == HARNESS else None,
        ) as session:
            assert session.execute(text("select current_user")).scalar_one() == role


@pytest.mark.rls_integration
def test_e4b_pg17_dataapi_001_denies_known_roles_without_guc(
    e4b_pg17_engine: Engine,
) -> None:
    for role in NEGATIVE_ROLES:
        with Session(e4b_pg17_engine) as session, session.begin():
            session.execute(text(f"set local role {CONTROLLER}"))
            session.execute(text(f"set local role {role}"))
            assert session.execute(text("select current_user")).scalar_one() == role
            for relation in RELATIONS:
                _assert_sqlstate(
                    session,
                    f"select * from public.{relation}",
                    None,
                    "42501",
                )
                _assert_sqlstate(
                    session,
                    f"insert into public.{relation} default values",
                    None,
                    "42501",
                )
                _assert_sqlstate(
                    session,
                    f"update public.{relation} set igreja_id=igreja_id",
                    None,
                    "42501",
                )
                _assert_sqlstate(
                    session,
                    f"delete from public.{relation}",
                    None,
                    "42501",
                )


@pytest.mark.rls_integration
def test_e4b_pg17_chain_001_commits_complete_chain_and_rejects_partial(
    e4b_pg17_engine: Engine,
) -> None:
    request = _stage_accept(e4b_pg17_engine)
    for relation in RELATIONS[:4]:
        assert _count(e4b_pg17_engine, relation, TENANT_A) == 1
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        row = session.execute(
            text(
                "select operation.confirmed_at, receipt.confirmed_at, stream.state_changed_at, "
                "retention.retention_anchor_at, retention.state_changed_at "
                "from public.e4b_consent_operations operation "
                "join public.e4b_consent_receipts receipt using (igreja_id, operation_id) "
                "join public.e4b_consent_streams stream on stream.igreja_id=operation.igreja_id "
                "and stream.accept_operation_id=operation.operation_id "
                "join public.e4b_consent_retentions retention on retention.igreja_id=operation.igreja_id "
                "and retention.operation_id=operation.operation_id "
                "where operation.operation_id=:operation_id"
            ),
            {"operation_id": request.operation_id},
        ).one()
        assert len(set(row)) == 1
    withdraw = _withdraw_request(request)
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        result = PostgresE4bConsentStagingAdapter(session).stage_consent(withdraw)
        assert result.outcome is E4bStagingOutcome.STAGED
    assert _count(e4b_pg17_engine, "e4b_consent_operations", TENANT_A) == 2
    assert _count(e4b_pg17_engine, "e4b_consent_streams", TENANT_A) == 1
    assert _count(e4b_pg17_engine, "e4b_consent_receipts", TENANT_A) == 2
    assert _count(e4b_pg17_engine, "e4b_consent_retentions", TENANT_A) == 2
    partial_operation = uuid.uuid4()
    with pytest.raises(DBAPIError):
        with _harness_session(e4b_pg17_engine, TENANT_A) as session:
            session.execute(
                text(
                    "insert into public.e4b_consent_operations "
                    "(igreja_id, operation_id, idempotency_key, correlation_id, action, "
                    "titular_pessoa_id, manifestante_pessoa_id, manifestant_role, operator_id, "
                    "operator_kind, operator_role_links, finalidade_id, contract_version, "
                    "policy_version, term_version, content_digest, fingerprint, concession_state, confirmed_at) "
                    "values (:tenant, :operation, :key, :correlation, 'ACCEPT', :person, :person, "
                    "'TITULAR', :person, 'HUMAN', ARRAY['TITULAR', 'MANIFESTANTE']::text[], "
                    "'partial_chain', 'contract/v1', 'policy/v1', 'term/v1', :digest, :digest, "
                    "'ACTIVE', pg_catalog.clock_timestamp())"
                ),
                {
                    "tenant": TENANT_A,
                    "operation": partial_operation,
                    "key": f"e4b:consent-operation:v1:{uuid.uuid4().hex}",
                    "correlation": uuid.uuid4(),
                    "person": PERSON_A,
                    "digest": "a" * 64,
                },
            )
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        assert session.execute(
            text(
                "select count(*) from public.e4b_consent_operations "
                "where operation_id=:operation"
            ),
            {"operation": partial_operation},
        ).scalar_one() == 0

    def reject_incomplete_chain(link: str) -> None:
        operation_id = uuid.uuid4()
        confirmed_at: dt.datetime | None = None
        with pytest.raises(DBAPIError):
            with _harness_session(e4b_pg17_engine, TENANT_A) as session:
                session.execute(
                    text(
                        "insert into public.e4b_consent_operations "
                        "(igreja_id, operation_id, idempotency_key, correlation_id, action, "
                        "titular_pessoa_id, manifestante_pessoa_id, manifestant_role, operator_id, "
                        "operator_kind, operator_role_links, finalidade_id, contract_version, "
                        "policy_version, term_version, content_digest, fingerprint, concession_state, confirmed_at) "
                        "values (:tenant, :operation, :key, :correlation, 'ACCEPT', :person, :person, "
                        "'TITULAR', :person, 'HUMAN', ARRAY['TITULAR', 'MANIFESTANTE']::text[], "
                        ":purpose, 'contract/v1', 'policy/v1', 'term/v1', :digest, :digest, "
                        "'ACTIVE', pg_catalog.clock_timestamp())"
                    ),
                    {
                        "tenant": TENANT_A,
                        "operation": operation_id,
                        "key": f"e4b:consent-operation:v1:{uuid.uuid4().hex}",
                        "correlation": uuid.uuid4(),
                        "person": PERSON_A,
                        "purpose": f"partial_{link}",
                        "digest": "a" * 64,
                    },
                )
                confirmed_at = session.execute(
                    text(
                        "select confirmed_at from public.e4b_consent_operations "
                        "where operation_id=:operation"
                    ),
                    {"operation": operation_id},
                ).scalar_one()
                if link == "stream":
                    session.execute(
                        text(
                            "insert into public.e4b_consent_streams "
                            "(igreja_id, titular_pessoa_id, finalidade_id, accept_operation_id, "
                            "accept_action, stream_state, state_changed_at) "
                            "values (:tenant, :person, :purpose, :operation, 'ACCEPT', 'ACTIVE', :confirmed_at)"
                        ),
                        {
                            "tenant": TENANT_A,
                            "person": PERSON_A,
                            "purpose": f"partial_{link}",
                            "operation": operation_id,
                            "confirmed_at": confirmed_at,
                        },
                    )
                elif link == "receipt":
                    session.execute(
                        text(
                            "insert into public.e4b_consent_receipts "
                            "(igreja_id, receipt_id, operation_id, correlation_id, action, origin, "
                            "manifestant_role, concession_state, confirmed_at, contract_version, "
                            "policy_version, term_version, content_digest, fingerprint_version, fingerprint) "
                            "select igreja_id, :receipt, operation_id, correlation_id, action, origin, "
                            "manifestant_role, concession_state, confirmed_at, contract_version, "
                            "policy_version, term_version, content_digest, fingerprint_version, fingerprint "
                            "from public.e4b_consent_operations where operation_id=:operation"
                        ),
                        {"receipt": uuid.uuid4(), "operation": operation_id},
                    )
                elif link == "retention":
                    assert confirmed_at is not None
                    session.execute(
                        text(
                            "insert into public.e4b_consent_retentions "
                            "(igreja_id, operation_id, retention_state, retention_anchor_at, "
                            "retention_due_at, active_hold_count, state_changed_at) "
                            "values (:tenant, :operation, 'RETENTION_RUNNING', :confirmed_at, "
                            ":due_at, 0, :confirmed_at)"
                        ),
                        {
                            "tenant": TENANT_A,
                            "operation": operation_id,
                            "confirmed_at": confirmed_at,
                            "due_at": add_24m_utc(confirmed_at),
                        },
                    )
                else:
                    raise AssertionError(f"elo parcial desconhecido: {link}")
                # Força os quatro constraint triggers de cadeia no mesmo ponto
                # em que o commit normal os executaria.
                session.execute(text("set constraints all immediate"))
        assert _count(e4b_pg17_engine, "e4b_consent_operations", TENANT_A) == 2

    for incomplete_link in ("stream", "receipt", "retention"):
        reject_incomplete_chain(incomplete_link)


@pytest.mark.rls_integration
def test_e4b_pg17_chain_002_rejects_invalid_withdraw_origins_and_streams(
    e4b_pg17_engine: Engine,
) -> None:
    accept = _stage_accept(e4b_pg17_engine)
    withdraw = _withdraw_request(accept)
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        result = PostgresE4bConsentStagingAdapter(session).stage_consent(withdraw)
        assert result.outcome is E4bStagingOutcome.STAGED
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        assert session.execute(
            text("select stream_state from public.e4b_consent_streams")
        ).scalar_one() == "WITHDRAWN"
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        assert PostgresE4bConsentStagingAdapter(session).stage_consent(
            _withdraw_request(accept)
        ).outcome is E4bStagingOutcome.DENIED
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        assert PostgresE4bConsentStagingAdapter(session).stage_consent(
            _accept_request(TENANT_A, PERSON_A)
        ).outcome is E4bStagingOutcome.DENIED
    cross_tenant = E4bConsentIntent.create(
        action=E4bAction.WITHDRAW,
        idempotency_key=E4bIdempotencyKey(
            igreja_id=TENANT_B,
            value=f"e4b:consent-operation:v1:{uuid.uuid4().hex}",
        ),
        authority=_authority(TENANT_B, PERSON_B, uuid.uuid4(), "cuidado_pastoral"),
        origin_accept_operation_id=accept.operation_id,
    )
    with _harness_session(e4b_pg17_engine, TENANT_B) as session:
        denied = PostgresE4bConsentStagingAdapter(session).stage_consent(
            E4bConsentStageRequest(uuid.uuid4(), uuid.uuid4(), cross_tenant)
        )
        assert denied.outcome is E4bStagingOutcome.DENIED
    assert _count(e4b_pg17_engine, "e4b_consent_operations", TENANT_B) == 0
    with pytest.raises(E4bPersistenceError):
        E4bConsentStageRequest(
            uuid.uuid4(),
            uuid.uuid4(),
            E4bConsentIntent.create(
                action=E4bAction.WITHDRAW,
                idempotency_key=E4bIdempotencyKey(
                    igreja_id=TENANT_A,
                    value=f"e4b:consent-operation:v1:{uuid.uuid4().hex}",
                ),
                authority=_authority(TENANT_A, PERSON_A, uuid.uuid4(), "cuidado_pastoral"),
            ),
        )


@pytest.mark.rls_integration
def test_e4b_pg17_replay_001_rehydrates_exact_and_conflicts_tenant_scoped(
    e4b_pg17_engine: Engine,
) -> None:
    request = _accept_request()
    _stage_accept(e4b_pg17_engine, request)
    baseline_a = _relation_counts(e4b_pg17_engine, TENANT_A)
    assert baseline_a == {
        "e4b_consent_operations": 1,
        "e4b_consent_streams": 1,
        "e4b_consent_receipts": 1,
        "e4b_consent_retentions": 1,
        "e4b_consent_holds": 0,
        "e4b_consent_hold_events": 0,
    }
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        replay = PostgresE4bConsentStagingAdapter(session).stage_consent(request)
        assert replay.outcome is E4bStagingOutcome.EXACT_REPLAY
    assert _relation_counts(e4b_pg17_engine, TENANT_A) == baseline_a
    conflicting_key = _accept_request(
        TENANT_A,
        PERSON_A,
        key=request.intent.idempotency_key.value,
    )
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        assert PostgresE4bConsentStagingAdapter(session).stage_consent(
            conflicting_key
        ).outcome is E4bStagingOutcome.CONFLICT
    assert _relation_counts(e4b_pg17_engine, TENANT_A) == baseline_a
    conflicting_correlation = _accept_request(
        TENANT_A,
        PERSON_A,
        correlation=request.intent.authority.correlation_id,
    )
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        assert PostgresE4bConsentStagingAdapter(session).stage_consent(
            conflicting_correlation
        ).outcome is E4bStagingOutcome.CONFLICT
    assert _relation_counts(e4b_pg17_engine, TENANT_A) == baseline_a
    tenant_b_same_key = _accept_request(
        TENANT_B,
        PERSON_B,
        key=request.intent.idempotency_key.value,
    )
    _stage_accept(e4b_pg17_engine, tenant_b_same_key)
    assert _relation_counts(e4b_pg17_engine, TENANT_A) == baseline_a
    assert _relation_counts(e4b_pg17_engine, TENANT_B) == {
        "e4b_consent_operations": 1,
        "e4b_consent_streams": 1,
        "e4b_consent_receipts": 1,
        "e4b_consent_retentions": 1,
        "e4b_consent_holds": 0,
        "e4b_consent_hold_events": 0,
    }


@pytest.mark.rls_integration
def test_e4b_pg17_imm_001_rejects_immutable_updates_and_deletes(
    e4b_pg17_engine: Engine,
) -> None:
    request = _stage_accept(e4b_pg17_engine)
    hold_id = uuid.uuid4()
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        assert PostgresE4bConsentStagingAdapter(session).stage_hold(
            _hold_request(
                E4bHoldAction.APPLY,
                tenant=TENANT_A,
                operation_id=request.operation_id,
                hold_id=hold_id,
            )
        ).outcome is E4bStagingOutcome.STAGED
    attempts = (
        (
            "update public.e4b_consent_operations set fingerprint=fingerprint where operation_id=:id",
            {"id": request.operation_id},
        ),
        (
            "delete from public.e4b_consent_operations where operation_id=:id",
            {"id": request.operation_id},
        ),
        (
            "update public.e4b_consent_receipts set fingerprint=fingerprint where operation_id=:id",
            {"id": request.operation_id},
        ),
        (
            "delete from public.e4b_consent_receipts where operation_id=:id",
            {"id": request.operation_id},
        ),
        (
            "update public.e4b_consent_hold_events set policy_version=policy_version where hold_id=:hold_id",
            {"hold_id": hold_id},
        ),
        (
            "delete from public.e4b_consent_hold_events where hold_id=:hold_id",
            {"hold_id": hold_id},
        ),
    )
    for statement, parameters in attempts:
        with _harness_session(e4b_pg17_engine, TENANT_A) as session:
            _assert_sqlstate(session, statement, parameters, "P0001")


@pytest.mark.rls_integration
def test_e4b_pg17_imm_002_allows_only_stream_hold_retention_transitions(
    e4b_pg17_engine: Engine,
) -> None:
    accept = _stage_accept(e4b_pg17_engine)
    withdraw = _withdraw_request(accept)
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        assert PostgresE4bConsentStagingAdapter(session).stage_consent(
            withdraw
        ).outcome is E4bStagingOutcome.STAGED
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        _assert_sqlstate(
            session,
            "update public.e4b_consent_streams set stream_state='ACTIVE', "
            "withdraw_operation_id=null, withdraw_action=null where accept_operation_id=:operation",
            {"operation": accept.operation_id},
            "P0001",
        )
        for statement, parameters in (
            (
                "update public.e4b_consent_streams set titular_pessoa_id=:person "
                "where accept_operation_id=:operation",
                {"person": PERSON_A_RESPONSAVEL, "operation": accept.operation_id},
            ),
            (
                "update public.e4b_consent_streams set finalidade_id='other_purpose' "
                "where accept_operation_id=:operation",
                {"operation": accept.operation_id},
            ),
            (
                "update public.e4b_consent_streams set accept_operation_id=:replacement "
                "where accept_operation_id=:operation",
                {"replacement": uuid.uuid4(), "operation": accept.operation_id},
            ),
            (
                "update public.e4b_consent_streams "
                "set state_changed_at=state_changed_at + interval '1 second' "
                "where accept_operation_id=:operation",
                {"operation": accept.operation_id},
            ),
        ):
            _assert_sqlstate(session, statement, parameters, "P0001")
    hold_id = uuid.uuid4()
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        adapter = PostgresE4bConsentStagingAdapter(session)
        applied = _hold_request(
            E4bHoldAction.APPLY,
            tenant=TENANT_A,
            operation_id=accept.operation_id,
            hold_id=hold_id,
        )
        assert adapter.stage_hold(applied).outcome is E4bStagingOutcome.STAGED
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        _assert_sqlstate(
            session,
            "update public.e4b_consent_holds set hold_state='ACTIVE' where hold_id=:hold_id",
            {"hold_id": hold_id},
            "P0001",
        )
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        resolved = _hold_request(
            E4bHoldAction.RESOLVE,
            tenant=TENANT_A,
            operation_id=accept.operation_id,
            hold_id=hold_id,
            authority_version="authority/v2",
            policy_version="policy/v2",
        )
        assert PostgresE4bConsentStagingAdapter(session).stage_hold(
            resolved
        ).outcome is E4bStagingOutcome.STAGED
        retention = session.execute(
            text(
                "select retention_state, active_hold_count, suspension_started_at "
                "from public.e4b_consent_retentions where operation_id=:operation"
            ),
            {"operation": accept.operation_id},
        ).one()
        assert retention == ("RETENTION_RUNNING", 0, None)
        _assert_sqlstate(
            session,
            "update public.e4b_consent_retentions set retention_state='RETENTION_ELIGIBLE' "
            "where operation_id=:operation",
            {"operation": accept.operation_id},
            "P0001",
        )
        _assert_sqlstate(
            session,
            "update public.e4b_consent_retentions "
            "set retention_anchor_at=retention_anchor_at + interval '1 second' "
            "where operation_id=:operation",
            {"operation": accept.operation_id},
            "P0001",
        )
        _assert_sqlstate(
            session,
            "update public.e4b_consent_holds set hold_state='ACTIVE', resolved_at=null "
            "where hold_id=:hold_id",
            {"hold_id": hold_id},
            "P0001",
        )


@pytest.mark.rls_integration
def test_e4b_pg17_auth_001_validates_historical_operator_role_links(
    e4b_pg17_engine: Engine,
) -> None:
    statement_template = (
        "insert into public.e4b_consent_operations "
        "(igreja_id, operation_id, idempotency_key, correlation_id, action, "
        "titular_pessoa_id, manifestante_pessoa_id, responsavel_pessoa_id, manifestant_role, operator_id, "
        "operator_kind, operator_role_links, finalidade_id, contract_version, "
        "policy_version, term_version, content_digest, fingerprint, concession_state, confirmed_at) "
        "values (:tenant, :operation, :key, :correlation, 'ACCEPT', :titular, :manifestante, "
        ":responsavel, :manifestant_role, :operator, 'HUMAN', {role_links}, 'authority_roles', "
        "'contract/v1', 'policy/v1', 'term/v1', :digest, :digest, 'ACTIVE', "
        "pg_catalog.clock_timestamp())"
    )
    valid_cases = (
        (
            PERSON_A,
            PERSON_A,
            None,
            "TITULAR",
            PERSON_A,
            "ARRAY['TITULAR', 'MANIFESTANTE']::text[]",
        ),
        (
            PERSON_A,
            PERSON_A_RESPONSAVEL,
            PERSON_A_RESPONSAVEL,
            "RESPONSAVEL",
            PERSON_A_RESPONSAVEL,
            "ARRAY['MANIFESTANTE', 'RESPONSAVEL']::text[]",
        ),
        (
            PERSON_A,
            PERSON_A_RESPONSAVEL,
            PERSON_A_RESPONSAVEL,
            "RESPONSAVEL",
            PERSON_A,
            "ARRAY['TITULAR']::text[]",
        ),
        (
            PERSON_A,
            PERSON_A,
            None,
            "TITULAR",
            uuid.uuid4(),
            "ARRAY[]::text[]",
        ),
    )
    for titular, manifestante, responsavel, manifestant_role, operator, role_links in valid_cases:
        with Session(e4b_pg17_engine) as session:
            session.begin()
            session.execute(text(f"set local role {CONTROLLER}"))
            session.execute(text(f"set local role {HARNESS}"))
            session.execute(
                text("select set_config('app.tenant_igreja_id', :tenant, true)"),
                {"tenant": str(TENANT_A)},
            )
            session.execute(text("set local lock_timeout = '5s'"))
            assert session.execute(
                text(statement_template.format(role_links=role_links)),
                {
                    "tenant": TENANT_A,
                    "operation": uuid.uuid4(),
                    "key": f"e4b:consent-operation:v1:{uuid.uuid4().hex}",
                    "correlation": uuid.uuid4(),
                    "titular": titular,
                    "manifestante": manifestante,
                    "responsavel": responsavel,
                    "manifestant_role": manifestant_role,
                    "operator": operator,
                    "digest": "a" * 64,
                },
            ).rowcount == 1
            # A cadeia propositalmente parcial não pode ser confirmada; esta
            # rodada observa apenas a guarda BEFORE de autoridade histórica.
            session.rollback()
    cases = (
        (
            PERSON_A,
            PERSON_A,
            None,
            "TITULAR",
            PERSON_A,
            (
                "ARRAY[]::text[]",
                "ARRAY['TITULAR']::text[]",
                "ARRAY['MANIFESTANTE', 'TITULAR']::text[]",
                "ARRAY['TITULAR', 'MANIFESTANTE', 'RESPONSAVEL']::text[]",
                "ARRAY['TITULAR', 'TITULAR']::text[]",
            ),
        ),
        (
            PERSON_A,
            PERSON_A_RESPONSAVEL,
            PERSON_A_RESPONSAVEL,
            "RESPONSAVEL",
            PERSON_A_RESPONSAVEL,
            (
                "ARRAY[]::text[]",
                "ARRAY['MANIFESTANTE']::text[]",
                "ARRAY['RESPONSAVEL']::text[]",
                "ARRAY['RESPONSAVEL', 'MANIFESTANTE']::text[]",
                "ARRAY['TITULAR', 'MANIFESTANTE', 'RESPONSAVEL']::text[]",
            ),
        ),
        (
            PERSON_A,
            PERSON_A,
            None,
            "TITULAR",
            uuid.uuid4(),
            (
                "ARRAY['TITULAR']::text[]",
                "ARRAY['MANIFESTANTE']::text[]",
                "ARRAY['TITULAR', 'MANIFESTANTE']::text[]",
            ),
        ),
    )
    for titular, manifestante, responsavel, manifestant_role, operator, invalid_links in cases:
        for role_links in invalid_links:
            with _harness_session(e4b_pg17_engine, TENANT_A) as session:
                _assert_sqlstate(
                    session,
                    statement_template.format(role_links=role_links),
                    {
                        "tenant": TENANT_A,
                        "operation": uuid.uuid4(),
                        "key": f"e4b:consent-operation:v1:{uuid.uuid4().hex}",
                        "correlation": uuid.uuid4(),
                        "titular": titular,
                        "manifestante": manifestante,
                        "responsavel": responsavel,
                        "manifestant_role": manifestant_role,
                        "operator": operator,
                        "digest": "a" * 64,
                    },
                    "P0001",
                )


@pytest.mark.rls_integration
def test_e4b_pg17_ret_001_validates_confirmed_at_and_utc_retention(
    e4b_pg17_engine: Engine,
) -> None:
    calendar_cases = (
        (
            dt.datetime(2024, 2, 29, 23, 59, 59, 123456, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 2, 28, 23, 59, 59, 123456, tzinfo=dt.timezone.utc),
        ),
        (
            dt.datetime(2023, 1, 31, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2025, 1, 31, 0, 0, tzinfo=dt.timezone.utc),
        ),
        (
            dt.datetime(2023, 3, 31, 12, 30, 1, tzinfo=dt.timezone.utc),
            dt.datetime(2025, 3, 31, 12, 30, 1, tzinfo=dt.timezone.utc),
        ),
        (
            dt.datetime(2023, 4, 30, 12, 30, 1, tzinfo=dt.timezone.utc),
            dt.datetime(2025, 4, 30, 12, 30, 1, tzinfo=dt.timezone.utc),
        ),
        (
            dt.datetime(2024, 8, 31, 23, 59, tzinfo=dt.timezone(dt.timedelta(hours=-3))),
            dt.datetime(2026, 9, 1, 2, 59, tzinfo=dt.timezone.utc),
        ),
    )
    for instant, expected in calendar_cases:
        assert add_24m_utc(instant) == expected
    request = _accept_request()
    with Session(e4b_pg17_engine) as staging_session:
        staging_session.begin()
        staging_session.execute(text(f"set local role {CONTROLLER}"))
        staging_session.execute(text(f"set local role {HARNESS}"))
        staging_session.execute(
            text("select set_config('app.tenant_igreja_id', :tenant, true)"),
            {"tenant": str(TENANT_A)},
        )
        staging_session.execute(text("set local lock_timeout = '5s'"))
        assert PostgresE4bConsentStagingAdapter(staging_session).stage_consent(
            request
        ).outcome is E4bStagingOutcome.STAGED
        assert staging_session.execute(
            text(
                "select count(*) from pg_catalog.pg_locks "
                "where locktype='advisory' and granted and pid=pg_catalog.pg_backend_pid()"
            )
        ).scalar_one() == 4
        confirmed_rows = staging_session.execute(
            text(
                "select operation.confirmed_at, receipt.confirmed_at, stream.state_changed_at, "
                "retention.retention_anchor_at, retention.state_changed_at "
                "from public.e4b_consent_operations operation "
                "join public.e4b_consent_receipts receipt "
                "on receipt.igreja_id=operation.igreja_id and receipt.operation_id=operation.operation_id "
                "join public.e4b_consent_streams stream "
                "on stream.igreja_id=operation.igreja_id and stream.accept_operation_id=operation.operation_id "
                "join public.e4b_consent_retentions retention "
                "on retention.igreja_id=operation.igreja_id and retention.operation_id=operation.operation_id "
                "where operation.operation_id=:operation"
            ),
            {"operation": request.operation_id},
        ).one()
        assert len(set(confirmed_rows)) == 1
        with _harness_session(e4b_pg17_engine, TENANT_A) as observer:
            assert observer.execute(
                text(
                    "select count(*) from public.e4b_consent_operations "
                    "where operation_id=:operation"
                ),
                {"operation": request.operation_id},
            ).scalar_one() == 0
        staging_session.commit()
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        session.execute(text("set local timezone = 'America/Sao_Paulo'"))
        anchor, due, state = session.execute(
            text(
                "select retention_anchor_at, retention_due_at, retention_state "
                "from public.e4b_consent_retentions where operation_id=:operation"
            ),
            {"operation": request.operation_id},
        ).one()
        assert due == add_24m_utc(anchor)
        assert state == "RETENTION_RUNNING"
        assert session.execute(
            text(
                "select count(*) from public.e4b_consent_retentions "
                "where retention_state='RETENTION_ELIGIBLE'"
            )
        ).scalar_one() == 0
        _assert_sqlstate(
            session,
            "update public.e4b_consent_retentions set retention_state='RETENTION_ELIGIBLE' "
            "where operation_id=:operation",
            {"operation": request.operation_id},
            "P0001",
        )


@pytest.mark.rls_integration
def test_e4b_pg17_hold_001_projects_holds_and_serializes_subject(
    e4b_pg17_engine: Engine,
) -> None:
    accept = _stage_accept(e4b_pg17_engine)
    before_bad_authority = _relation_counts(e4b_pg17_engine, TENANT_A)
    with Session(e4b_pg17_engine) as session:
        session.begin()
        session.execute(text(f"set local role {CONTROLLER}"))
        session.execute(text(f"set local role {HARNESS}"))
        session.execute(
            text("select set_config('app.tenant_igreja_id', :tenant, true)"),
            {"tenant": str(TENANT_A)},
        )
        session.execute(text("set local lock_timeout = '5s'"))
        with pytest.raises(E4bPersistenceError) as raised:
            PostgresE4bConsentStagingAdapter(session).stage_hold(
                _hold_request(
                    E4bHoldAction.APPLY,
                    tenant=TENANT_A,
                    operation_id=accept.operation_id,
                    user_id=USER_B,
                )
            )
        assert raised.value.code is E4bPersistenceErrorCode.DATA_INTEGRITY
        session.rollback()
    assert _relation_counts(e4b_pg17_engine, TENANT_A) == before_bad_authority
    first_hold = uuid.uuid4()
    second_hold = uuid.uuid4()
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        adapter = PostgresE4bConsentStagingAdapter(session)
        applied = _hold_request(
            E4bHoldAction.APPLY,
            tenant=TENANT_A,
            operation_id=accept.operation_id,
            hold_id=first_hold,
        )
        assert adapter.stage_hold(applied).outcome is E4bStagingOutcome.STAGED
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        applied = _hold_request(
            E4bHoldAction.APPLY,
            tenant=TENANT_A,
            operation_id=accept.operation_id,
            hold_id=second_hold,
        )
        assert PostgresE4bConsentStagingAdapter(session).stage_hold(
            applied
        ).outcome is E4bStagingOutcome.STAGED
        state = session.execute(
            text(
                "select retention_state, active_hold_count, suspension_started_at "
                "from public.e4b_consent_retentions where operation_id=:operation"
            ),
            {"operation": accept.operation_id},
        ).one()
        assert state[0:2] == ("RETENTION_HELD", 2)
        assert state[2] is not None
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        resolved = _hold_request(
            E4bHoldAction.RESOLVE,
            tenant=TENANT_A,
            operation_id=accept.operation_id,
            hold_id=first_hold,
            authority_version="authority/v2",
            policy_version="policy/v2",
        )
        assert PostgresE4bConsentStagingAdapter(session).stage_hold(
            resolved
        ).outcome is E4bStagingOutcome.STAGED
        assert session.execute(
            text("select active_hold_count from public.e4b_consent_retentions")
        ).scalar_one() == 1
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        resolved = _hold_request(
            E4bHoldAction.RESOLVE,
            tenant=TENANT_A,
            operation_id=accept.operation_id,
            hold_id=second_hold,
            authority_version="authority/v2",
            policy_version="policy/v2",
        )
        assert PostgresE4bConsentStagingAdapter(session).stage_hold(
            resolved
        ).outcome is E4bStagingOutcome.STAGED
        retention = session.execute(
            text(
                "select retention_state, active_hold_count, suspension_started_at, "
                "retention_anchor_at, retention_due_at, last_hold_event_at "
                "from public.e4b_consent_retentions where operation_id=:operation"
            ),
            {"operation": accept.operation_id},
        ).one()
        assert retention[0:3] == ("RETENTION_RUNNING", 0, None)
        first_applied, last_resolved = session.execute(
            text(
                "select min(applied_at), max(resolved_at) from public.e4b_consent_holds "
                "where operation_id=:operation"
            ),
            {"operation": accept.operation_id},
        ).one()
        assert retention[4] == add_24m_utc(retention[3]) + (last_resolved - first_applied)
        event_shapes = session.execute(
            text(
                "select hold_id, event_kind, event_sequence from public.e4b_consent_hold_events "
                "where operation_id=:operation order by hold_id, event_sequence"
            ),
            {"operation": accept.operation_id},
        ).all()
        assert {(row[1], row[2]) for row in event_shapes} == {
            ("HOLD_APPLIED", 1),
            ("HOLD_RESOLVED", 2),
        }


@pytest.mark.rls_integration
def test_e4b_pg17_lock_001_orders_tenant_scoped_advisory_locks(
    e4b_pg17_engine: Engine,
) -> None:
    request = _accept_request()
    authority = request.intent.authority
    locks_a = e4b_advisory_lock_texts(
        igreja_id=TENANT_A,
        idempotency_key=request.intent.idempotency_key.value,
        titular_pessoa_id=PERSON_A,
        correlation_id=authority.correlation_id,
        finalidade_id=authority.finalidade_id,
    )
    locks_b = e4b_advisory_lock_texts(
        igreja_id=TENANT_B,
        idempotency_key=request.intent.idempotency_key.value,
        titular_pessoa_id=PERSON_B,
        correlation_id=authority.correlation_id,
        finalidade_id=authority.finalidade_id,
    )
    assert [seed for _, seed in locks_a] == [2026091001, 2026091002, 2026091003, 2026091004]
    assert [value for value, _ in locks_a] != [value for value, _ in locks_b]
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        signed_hashes = [
            session.execute(
                text(
                    "select pg_catalog.pg_typeof("
                    "pg_catalog.hashtextextended(:lock_text, :seed))::text, "
                    "pg_catalog.hashtextextended(:lock_text, :seed)"
                ),
                {"lock_text": lock_text, "seed": seed},
            ).one()
            for lock_text, seed in locks_a
        ]
        assert all(type_name == "bigint" for type_name, _ in signed_hashes)
        assert all(-(2**63) <= value < 2**63 for _, value in signed_hashes)
        assert session.execute(text("show lock_timeout")).scalar_one() == "5s"
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        adapter = PostgresE4bConsentStagingAdapter(session)
        assert adapter.stage_consent(request).outcome is E4bStagingOutcome.STAGED
        assert session.execute(
            text(
                "select count(*) from pg_catalog.pg_locks "
                "where locktype='advisory' and granted and pid=pg_catalog.pg_backend_pid()"
            )
        ).scalar_one() == 4
    with _harness_session(e4b_pg17_engine, TENANT_A) as session:
        assert PostgresE4bConsentStagingAdapter(session).stage_hold(
            _hold_request(
                E4bHoldAction.APPLY,
                tenant=TENANT_A,
                operation_id=request.operation_id,
            )
        ).outcome is E4bStagingOutcome.STAGED
        assert session.execute(
            text(
                "select count(*) from pg_catalog.pg_locks "
                "where locktype='advisory' and granted and pid=pg_catalog.pg_backend_pid()"
            )
        ).scalar_one() == 1

    # Duas sessões do controlador usam uma barreira para provar contenção de L.
    # Não inferimos ausência de colisão fora desse escopo sintético observado.
    lock_text, seed = locks_a[1]
    barrier = threading.Barrier(2, timeout=5)
    release_holder = threading.Event()
    thread_failures: queue.Queue[BaseException] = queue.Queue()
    contender_sqlstates: list[str | None] = []
    elapsed: list[float] = []

    def hold_l_lock() -> None:
        try:
            with _oracle_session(
                e4b_pg17_engine,
                tenant=TENANT_A,
                lock_timeout="5s",
            ) as session:
                session.execute(
                    text(
                        "select pg_catalog.pg_advisory_xact_lock("
                        "pg_catalog.hashtextextended(:lock_text, :seed))"
                    ),
                    {"lock_text": lock_text, "seed": seed},
                )
                barrier.wait()
                if not release_holder.wait(timeout=5):
                    raise RuntimeError("a barreira de lock C3 não liberou o holder")
        except BaseException as raised:
            thread_failures.put(raised)

    def contend_for_l_lock() -> None:
        try:
            with _oracle_session(
                e4b_pg17_engine,
                tenant=TENANT_A,
                lock_timeout="125ms",
            ) as session:
                barrier.wait()
                started = time.monotonic()
                try:
                    session.execute(
                        text(
                            "select pg_catalog.pg_advisory_xact_lock("
                            "pg_catalog.hashtextextended(:lock_text, :seed))"
                        ),
                        {"lock_text": lock_text, "seed": seed},
                    )
                except DBAPIError as raised:
                    elapsed.append(time.monotonic() - started)
                    contender_sqlstates.append(getattr(raised.orig, "pgcode", None))
                else:
                    contender_sqlstates.append("ACQUIRED")
        except BaseException as raised:
            thread_failures.put(raised)

    holder = threading.Thread(target=hold_l_lock, name="e4b-c3-lock-holder")
    contender = threading.Thread(target=contend_for_l_lock, name="e4b-c3-lock-contender")
    holder.start()
    contender.start()
    try:
        contender.join(timeout=5)
        assert not contender.is_alive()
        assert contender_sqlstates == ["55P03"]
        assert elapsed and elapsed[0] >= 0.05
    finally:
        release_holder.set()
        holder.join(timeout=5)
        contender.join(timeout=5)
    assert not holder.is_alive()
    assert thread_failures.empty()
    adapter_source = inspect.getsource(PostgresE4bConsentStagingAdapter).lower()
    assert "for update pessoa" not in adapter_source
    assert "lock_timeout" in adapter_source


@pytest.mark.rls_integration
def test_e4b_pg17_rollback_001_removes_partial_state_and_releases_locks(
    e4b_pg17_engine: Engine,
) -> None:
    def configure(session: Session) -> None:
        session.begin()
        session.execute(text(f"set local role {CONTROLLER}"))
        session.execute(text(f"set local role {HARNESS}"))
        session.execute(
            text("select set_config('app.tenant_igreja_id', :tenant, true)"),
            {"tenant": str(TENANT_A)},
        )
        session.execute(text("set local lock_timeout = '5s'"))

    def assert_no_advisory_locks() -> None:
        with e4b_pg17_engine.connect() as connection:
            assert connection.execute(
                text(
                    "select count(*) from pg_catalog.pg_locks "
                    "where locktype='advisory' and granted and database=("
                    "select oid from pg_catalog.pg_database where datname=current_database())"
                )
            ).scalar_one() == 0

    def fail_after(original):
        def injected(*args, **kwargs):
            original(*args, **kwargs)
            raise E4bPersistenceError(E4bPersistenceErrorCode.DATA_INTEGRITY)

        return injected

    def fail_after_deferred(original, session: Session):
        def injected(*args, **kwargs):
            original(*args, **kwargs)
            session.execute(text("set constraints all immediate"))
            raise E4bPersistenceError(E4bPersistenceErrorCode.DATA_INTEGRITY)

        return injected

    # Cada elo da cadeia ACCEPT é inserido antes da falha injetada; rollback
    # precisa restaurar integralmente as seis relações e os locks da transação.
    for point in (
        "_insert_operation",
        "_insert_active_stream",
        "_insert_receipt",
        "_insert_retention",
        "_flush",
    ):
        baseline = _relation_counts(e4b_pg17_engine, TENANT_A)
        with Session(e4b_pg17_engine) as session:
            configure(session)
            adapter = PostgresE4bConsentStagingAdapter(session)
            original = getattr(adapter, point)
            if point == "_flush":
                setattr(adapter, point, fail_after_deferred(original, session))
            else:
                setattr(adapter, point, fail_after(original))
            with pytest.raises(E4bPersistenceError) as raised:
                adapter.stage_consent(
                    _accept_request(purpose=f"rollback_consent_{point}")
                )
            assert raised.value.code is E4bPersistenceErrorCode.DATA_INTEGRITY
            session.rollback()
        assert _relation_counts(e4b_pg17_engine, TENANT_A) == baseline
        assert_no_advisory_locks()

    # Hold e evento percorrem os três triggers de projeção antes do rollback.
    for point in (
        "_insert_hold_applied",
        "_insert_hold_event",
        "_reproject_retention",
        "_flush",
    ):
        committed = _stage_accept(
            e4b_pg17_engine,
            _accept_request(purpose=f"rollback_hold_{point}"),
        )
        baseline = _relation_counts(e4b_pg17_engine, TENANT_A)
        with Session(e4b_pg17_engine) as session:
            configure(session)
            adapter = PostgresE4bConsentStagingAdapter(session)
            original = getattr(adapter, point)
            if point == "_flush":
                setattr(adapter, point, fail_after_deferred(original, session))
            else:
                setattr(adapter, point, fail_after(original))
            with pytest.raises(E4bPersistenceError) as raised:
                adapter.stage_hold(
                    _hold_request(
                        E4bHoldAction.APPLY,
                        tenant=TENANT_A,
                        operation_id=committed.operation_id,
                    )
                )
            assert raised.value.code is E4bPersistenceErrorCode.DATA_INTEGRITY
            session.rollback()
        assert _relation_counts(e4b_pg17_engine, TENANT_A) == baseline
        assert_no_advisory_locks()


@pytest.mark.rls_integration
def test_e4b_pg17_commit_001_reconciles_precommit_and_uncertain_commit(
    e4b_pg17_engine: Engine,
) -> None:
    precommit = _accept_request()
    with Session(e4b_pg17_engine) as session:
        session.begin()
        session.execute(text(f"set local role {CONTROLLER}"))
        session.execute(text(f"set local role {HARNESS}"))
        session.execute(
            text("select set_config('app.tenant_igreja_id', :tenant, true)"),
            {"tenant": str(TENANT_A)},
        )
        session.execute(text("set local lock_timeout = '5s'"))
        assert PostgresE4bConsentStagingAdapter(session).stage_consent(
            precommit
        ).outcome is E4bStagingOutcome.STAGED
        session.rollback()
    assert _count(e4b_pg17_engine, "e4b_consent_operations", TENANT_A) == 0

    # O primeiro resultado fechado da porta C2 representa a falha pré-commit.
    precommit_port = _C3ReadOnlyReconciliationPort(e4b_pg17_engine)
    precommit_decision = reconcile(
        context=E4bServerResolvedReadContext(
            igreja_id=TENANT_A,
            authority=precommit.intent.authority,
        ),
        selector=E4bOperationSelector(TENANT_A, precommit.operation_id),
        port=precommit_port,
    )
    assert precommit_decision.outcome is E4bReconciliationOutcome.NOT_FOUND

    # O owner confirma a transação, mas o acknowledgement é descartado antes
    # de ser consumido. A reconciliação em uma sessão nova decide o resultado.
    request = _accept_request()
    with Session(e4b_pg17_engine) as session:
        session.begin()
        session.execute(text(f"set local role {CONTROLLER}"))
        session.execute(text(f"set local role {HARNESS}"))
        session.execute(
            text("select set_config('app.tenant_igreja_id', :tenant, true)"),
            {"tenant": str(TENANT_A)},
        )
        session.execute(text("set local lock_timeout = '5s'"))
        acknowledgement_lost = PostgresE4bConsentStagingAdapter(session).stage_consent(
            request
        )
        assert acknowledgement_lost.outcome is E4bStagingOutcome.STAGED
        session.commit()

    confirmed_port = _C3ReadOnlyReconciliationPort(e4b_pg17_engine)
    confirmed_decision = reconcile(
        context=E4bServerResolvedReadContext(
            igreja_id=TENANT_A,
            authority=request.intent.authority,
        ),
        selector=E4bOperationSelector(TENANT_A, request.operation_id),
        port=confirmed_port,
    )
    assert confirmed_decision.outcome is E4bReconciliationOutcome.CONFIRMED
    assert confirmed_decision.receipt == acknowledgement_lost.receipt
    assert confirmed_port.calls == 1
    assert confirmed_port.effective_roles == [HARNESS]
    assert confirmed_port.transaction_read_only == ["on"]

    # A divergência é persistida somente no banco filho. O owner a cria com
    # triggers desligados, a porta lê como HARNESS/read-only e o finally restaura
    # tanto o recibo como os triggers antes de deixar COMMIT-001.
    original_digest: str | None = None
    try:
        with Session(e4b_pg17_engine) as owner:
            with owner.begin():
                assert owner.execute(text("select current_user")).scalar_one() == "postgres"
                assert owner.execute(
                    text(
                        "select bool_and(trigger_row.tgenabled='O') "
                        "from pg_catalog.pg_trigger trigger_row "
                        "where trigger_row.tgrelid='public.e4b_consent_receipts'::regclass"
                    )
                ).scalar_one() is True
                original_digest = str(
                    owner.execute(
                        text(
                            "select content_digest from public.e4b_consent_receipts "
                            "where igreja_id=:igreja_id and operation_id=:operation_id"
                        ),
                        {"igreja_id": TENANT_A, "operation_id": request.operation_id},
                    ).scalar_one()
                )
                divergent_digest = "b" * 64 if original_digest != "b" * 64 else "c" * 64
                owner.execute(
                    text("alter table public.e4b_consent_receipts disable trigger all")
                )
                assert owner.execute(
                    text(
                        "update public.e4b_consent_receipts set content_digest=:content_digest "
                        "where igreja_id=:igreja_id and operation_id=:operation_id"
                    ),
                    {
                        "content_digest": divergent_digest,
                        "igreja_id": TENANT_A,
                        "operation_id": request.operation_id,
                    },
                ).rowcount == 1

        divergent_port = _C3ReadOnlyReconciliationPort(e4b_pg17_engine)
        divergent_decision = reconcile(
            context=E4bServerResolvedReadContext(
                igreja_id=TENANT_A,
                authority=request.intent.authority,
            ),
            selector=E4bOperationSelector(TENANT_A, request.operation_id),
            port=divergent_port,
        )
        assert divergent_decision.outcome is E4bReconciliationOutcome.UNKNOWN
        assert divergent_port.effective_roles == [HARNESS]
        assert divergent_port.transaction_read_only == ["on"]
    finally:
        if original_digest is not None:
            with Session(e4b_pg17_engine) as owner:
                with owner.begin():
                    assert owner.execute(text("select current_user")).scalar_one() == "postgres"
                    owner.execute(
                        text("alter table public.e4b_consent_receipts disable trigger all")
                    )
                    assert owner.execute(
                        text(
                            "update public.e4b_consent_receipts set content_digest=:content_digest "
                            "where igreja_id=:igreja_id and operation_id=:operation_id"
                        ),
                        {
                            "content_digest": original_digest,
                            "igreja_id": TENANT_A,
                            "operation_id": request.operation_id,
                        },
                    ).rowcount == 1
                    owner.execute(
                        text("alter table public.e4b_consent_receipts enable trigger all")
                    )
            with Session(e4b_pg17_engine) as owner:
                with owner.begin():
                    assert owner.execute(
                        text(
                            "select content_digest from public.e4b_consent_receipts "
                            "where igreja_id=:igreja_id and operation_id=:operation_id"
                        ),
                        {"igreja_id": TENANT_A, "operation_id": request.operation_id},
                    ).scalar_one() == original_digest
                    assert owner.execute(
                        text(
                            "select bool_and(trigger_row.tgenabled='O') "
                            "from pg_catalog.pg_trigger trigger_row "
                            "where trigger_row.tgrelid='public.e4b_consent_receipts'::regclass"
                        )
                    ).scalar_one() is True

    unknown_port = _C3ReadOnlyReconciliationPort(
        e4b_pg17_engine,
        force_unknown=True,
    )
    unknown_decision = reconcile(
        context=E4bServerResolvedReadContext(
            igreja_id=TENANT_A,
            authority=request.intent.authority,
        ),
        selector=E4bOperationSelector(TENANT_A, request.operation_id),
        port=unknown_port,
    )
    assert unknown_decision.outcome is E4bReconciliationOutcome.UNKNOWN
    assert unknown_port.effective_roles == [HARNESS]
    assert unknown_port.transaction_read_only == ["on"]

    cross_tenant_port = _C3ReadOnlyReconciliationPort(e4b_pg17_engine)
    cross_tenant_decision = reconcile(
        context=E4bServerResolvedReadContext(
            igreja_id=TENANT_B,
            authority=_authority(TENANT_B, PERSON_B, uuid.uuid4(), "cuidado_pastoral"),
        ),
        selector=E4bOperationSelector(TENANT_B, request.operation_id),
        port=cross_tenant_port,
    )
    assert cross_tenant_decision.outcome is E4bReconciliationOutcome.NOT_FOUND
    assert cross_tenant_port.effective_roles == [HARNESS]
    assert cross_tenant_port.transaction_read_only == ["on"]

    with _oracle_session(
        e4b_pg17_engine,
        tenant=TENANT_A,
        read_only=True,
    ) as session:
        _assert_sqlstate(
            session,
            "insert into public.e4b_consent_operations default values",
            None,
            "25006",
        )


@pytest.mark.rls_integration
def test_e4b_pg17_noskip_001_collects_exact_oracle_manifest(
    e4b_pg17_engine: Engine,
) -> None:
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_e4b_pg17_")
    ]
    assert [function.name for function in functions] == list(ORACLE_FUNCTIONS)
    for function in functions:
        decorators = "\n".join(ast.unparse(item) for item in function.decorator_list)
        assert "rls_integration" in decorators
        assert all(
            word not in decorators
            for word in ("s" + "kip", "x" + "fail")
        )
    assert all(
        forbidden not in source
        for forbidden in (
            "pytest." + "s" + "kip",
            "pytest.mark." + "s" + "kipif",
            "pytest." + "x" + "fail",
            "pytest.mark.x" + "fail",
            "pytest.importor" + "s" + "kip",
        )
    )
    assert e4b_pg17_engine.dialect.name == "postgresql"
