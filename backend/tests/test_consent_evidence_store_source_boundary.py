"""Source-only E1–E3 guards; no database, Git history or runtime execution."""

import ast
import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        (
            "backend/app/services/purpose_consent.py",
            "65a859c5db03916791b07e1a68245ccc0b953a765fd63fa59d89616b73d9ef28",
        ),
        (
            "backend/scripts/verify_migration_catalog_head.py",
            "2fe1a93bf9c9116426683e7fd86c4f7b7c20753f7ce11a8282d9ca06087ac30d",
        ),
        (
            "backend/scripts/apply_migrations.py",
            "36e63cde6751cd0cb33e1511091068b0b04f10029ace06703eead82e0e836c65",
        ),
        (
            "docs/governance/migrations/migration-catalog-head-v1.json",
            "a591923ce771349d286cdc424d599c593e070ecea0271f3909c64719258658b4",
        ),
    ],
)
def test_e1_e3_preserves_protected_source_bytes(relative, expected):
    # The legacy migration script is hashed, never imported or invoked.
    assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_evidence_store_has_no_application_callers():
    allowed = {
        "domain/consent_evidence_store.py",
        "services/consent_evidence_store.py",
        "services/consent_evidence_store_postgres.py",
    }
    application = ROOT / "backend/app"
    for path in application.rglob("*.py"):
        if path.relative_to(application).as_posix() in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [entry.name for entry in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [entry.name for entry in node.names]
            else:
                continue
            assert not any("consent_evidence_store" in name for name in names), (
                "new evidence-store caller outside the authorized laboratory"
            )


def test_strategy_c_adapter_uses_stream_without_explicit_person_lock():
    # Migration ACL/intent proofs belong to the deferred database delivery,
    # preserved in c48a62f. This guard must work in a clean source-only checkout.
    adapter = (ROOT / "backend/app/services/consent_evidence_store_postgres.py").read_text()
    assert "def lock_person(" not in adapter
    assert "from public.pessoas" not in adapter
    assert 'f"{igreja_id}:{pessoa_id}:{finalidade.value}"' in adapter


def test_source_only_delivery_keeps_approved_75_head_and_closed_gates():
    head = json.loads((ROOT / "docs/governance/migrations/migration-catalog-head-v1.json").read_text())
    assert head["current_head"]["migration_count"] == 75
    assert len(head["historical_prefix"]["entries"]) == 75
    assert head["append_only_batches"] == []
    assert head["operational_authorization"] is False
    assert head["next_stage_authorized"] is False
