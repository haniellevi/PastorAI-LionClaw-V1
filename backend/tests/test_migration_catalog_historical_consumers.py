from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import derive_migration_history_canonical_schema as derivation
from scripts import verify_migration_catalog_head as catalog_head
from scripts import (
    verify_migration_history_divergence_remediation_proposal_v3 as epoch_v3,
)
from scripts import (
    verify_migration_history_schema_expectation_manifest as source_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONED_HEAD_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-catalog-head-v1.json"
)
VERSIONED_HEAD_SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-catalog-head-v1.schema.json"
)


def _serialized(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode(
        "ascii"
    )


def _future_catalog(
    tmp_path: Path,
) -> tuple[Path, Path, Path, bytes, dict[str, Any]]:
    prior_content = VERSIONED_HEAD_PATH.read_bytes()
    head = catalog_head._decode_json(prior_content)
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    historical_entries = head["historical_prefix"]["entries"]
    for entry in historical_entries:
        source = catalog_head.MIGRATIONS_DIR / entry["name"]
        (migrations / entry["name"]).write_bytes(source.read_bytes())

    new_name = "20260902_120000_catalog_consumer_example.sql"
    new_content = b"select 1;\n"
    (migrations / new_name).write_bytes(new_content)
    addition = {
        "position": len(historical_entries),
        "name": new_name,
        "sha256": hashlib.sha256(new_content).hexdigest(),
        "size_bytes": len(new_content),
    }
    current_entries = copy.deepcopy(historical_entries) + [addition]
    resulting_digest = catalog_head._catalog_digest(current_entries)
    head["append_only_batches"] = [
        {
            "batch_id": "migration-catalog-append-0001",
            "entries": [addition],
            "previous_catalog_digest_sha256": (
                catalog_head.HISTORICAL_DIGEST_SHA256
            ),
            "resulting_catalog_digest_sha256": resulting_digest,
            "sequence": 1,
        }
    ]
    head["current_head"] = {
        "digest_sha256": resulting_digest,
        "last_basename": new_name,
        "migration_count": 76,
    }
    head["previous_approved_head_sha256"] = hashlib.sha256(
        prior_content
    ).hexdigest()
    head_path = tmp_path / "head.json"
    schema_path = tmp_path / "head.schema.json"
    head_path.write_bytes(_serialized(head))
    schema_path.write_bytes(VERSIONED_HEAD_SCHEMA_PATH.read_bytes())
    return migrations, head_path, schema_path, prior_content, head


def _point_catalog_head_at(
    monkeypatch: pytest.MonkeyPatch,
    *,
    migrations: Path,
    head_path: Path,
    schema_path: Path,
) -> None:
    monkeypatch.setattr(catalog_head, "MIGRATIONS_DIR", migrations)
    monkeypatch.setattr(catalog_head, "HEAD_PATH", head_path)
    monkeypatch.setattr(catalog_head, "SCHEMA_PATH", schema_path)
    monkeypatch.setattr(source_manifest, "MIGRATIONS_DIR", migrations)


def test_future_head_keeps_historical_consumers_on_exact_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrations, head_path, schema_path, prior_content, expected_head = (
        _future_catalog(tmp_path)
    )
    _point_catalog_head_at(
        monkeypatch,
        migrations=migrations,
        head_path=head_path,
        schema_path=schema_path,
    )

    with pytest.raises(catalog_head.VerificationError):
        catalog_head.verify_versioned_head()

    prior = catalog_head.ApprovedPriorHead(
        content_sha256=hashlib.sha256(prior_content).hexdigest(),
        head=catalog_head._decode_json(prior_content),
    )
    assert catalog_head.verify_versioned_head(approved_prior=prior)[
        "current_head"
    ]["migration_count"] == 76

    snapshot, current_entries = (
        catalog_head._validated_snapshot_for_historical_consumers()
    )
    assert snapshot == expected_head
    assert snapshot["operational_authorization"] is False
    assert snapshot["next_stage_authorized"] is False
    assert len(current_entries) == 76

    historical_entries, capabilities = source_manifest._scan_catalog()
    assert historical_entries == expected_head["historical_prefix"]["entries"]
    assert len(historical_entries) == 75
    assert capabilities == source_manifest.EXPECTED_CAPABILITY_FILE_COUNTS
    source_manifest.verify_manifest(
        source_manifest.MANIFEST_DIR / source_manifest.MANIFEST_BASENAME
    )

    raw_historical = derivation._load_source_catalog()
    assert len(raw_historical) == 75
    assert hashlib.sha256(raw_historical[-1]).hexdigest() == (
        historical_entries[-1]["sha256"]
    )
    epoch_v3.verify_versioned_package()


def test_unrepresented_tail_is_rejected_by_every_adapted_consumer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrations, head_path, schema_path, _prior_content, _head = (
        _future_catalog(tmp_path)
    )
    head = catalog_head._decode_json(head_path.read_bytes())
    head["append_only_batches"] = []
    head["current_head"] = copy.deepcopy(head["historical_prefix"])
    head["current_head"].pop("entries")
    head["previous_approved_head_sha256"] = None
    head_path.write_bytes(_serialized(head))
    _point_catalog_head_at(
        monkeypatch,
        migrations=migrations,
        head_path=head_path,
        schema_path=schema_path,
    )

    with pytest.raises(catalog_head.CatalogDriftError):
        catalog_head._validated_snapshot_for_historical_consumers()
    with pytest.raises(source_manifest.CatalogDriftError):
        source_manifest._scan_catalog()
    with pytest.raises(epoch_v3.HistoricalDriftError):
        epoch_v3._validate_catalog_unchanged()
