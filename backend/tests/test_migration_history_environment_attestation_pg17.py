from __future__ import annotations

import os
from pathlib import Path

import psycopg2
from psycopg2 import extensions
import pytest

from scripts import derive_migration_history_canonical_schema as derivation
from scripts import materialize_migration_history_environment_attestation as attestation


DATABASE_URL_ENV = "ENVIRONMENT_ATTESTATION_TEST_DATABASE_URL"


def test_capture_contract_runs_in_one_read_only_snapshot_on_postgresql17(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.environ.get(DATABASE_URL_ENV)
    if not database_url:
        pytest.skip("dedicated disposable PostgreSQL 17 URL is not configured")

    output_dir = tmp_path / "canonical-schema"
    output_dir.mkdir(mode=0o700)
    output_dir.chmod(0o700)
    monkeypatch.setenv(derivation.DATABASE_URL_ENV, database_url)

    assert derivation.derive(output_dir).is_file()

    connection = psycopg2.connect(database_url, connect_timeout=5)
    connection.autocommit = True
    try:
        preflight_sql = attestation.PREFLIGHT_SQL_PATH.read_text(encoding="ascii")
        rollback_sql = "rollback;\n"
        assert preflight_sql.endswith(rollback_sql)
        with connection.cursor() as cursor:
            cursor.execute(preflight_sql[: -len(rollback_sql)])
            identity = cursor.fetchone()[0]
            cursor.execute(rollback_sql)
        assert identity["server_version_num"] // 10_000 == 17
        assert identity["current_user_matches_session_user"] is True
        assert identity["tls"] is True
        assert identity["isolation_level"] == "repeatable read"
        assert identity["read_only"] == "on"
        assert identity["full_visibility"] is True
        assert connection.get_transaction_status() == extensions.TRANSACTION_STATUS_IDLE

        metadata, envelopes = attestation.capture_one_snapshot(connection)

        assert metadata["server_version_num"] // 10_000 == 17
        assert metadata["current_user_matches_session_user"] is True
        assert metadata["tls"] is True
        assert metadata["isolation_level"] == "repeatable read"
        assert metadata["read_only"] == "on"
        assert metadata["full_visibility"] is True
        assert metadata["ledgers"] == {"public": "ABSENT", "native": "ABSENT"}
        assert len(metadata["domains"]) == 14

        profile = attestation._load_contracts()
        assert [item["result"]["id"] for item in envelopes] == [
            item["id"] for item in profile["data_invariants"]
        ]
        states = {item["result"]["id"]: item["result"]["state"] for item in envelopes}
        assert states == {
            "TENANT_FOREIGN_KEY_CONSISTENCY": "PASS",
            "TENANT_UNIQUENESS_GUARDS": "PASS",
            "APPEND_ONLY_AUDIT_INTEGRITY": "UNKNOWN",
            "IDEMPOTENCY_UNIQUENESS": "PASS",
            "CONSENT_LEDGER_INTEGRITY": "PASS",
            "BILLING_ISOLATION_INTEGRITY": "PASS",
            "RECOVERY_ARTIFACT_RETENTION": "UNKNOWN",
            "GOVERNANCE_DRAFT_INTEGRITY": "PASS",
        }
        proofs = [item["session_proof"] for item in envelopes]
        assert proofs and all(proof == metadata["session_proof"] for proof in proofs)
        assert connection.get_transaction_status() == extensions.TRANSACTION_STATUS_IDLE

        with connection.cursor() as cursor:
            cursor.execute(
                "select pg_catalog.to_regclass('public.schema_migrations') is null, "
                "pg_catalog.to_regnamespace('supabase_migrations') is null"
            )
            assert cursor.fetchone() == (True, True)
    finally:
        connection.close()
