"""Source-only E1–E3 guards; no database, Git history or runtime execution."""

import ast
import hashlib
import json
import re
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


def test_strategy_c_preserves_parent_acl_and_uses_only_declared_relations():
    sql = (ROOT / "backend/migrations/20260908_175522_consent_evidence_store_lab.sql").read_text()
    intent = json.loads(sql.splitlines()[0].split("=", 1)[1])
    assert intent["affected_relations"] == [
        "public.consentimento_desafio", "public.consentimento_evidencia",
        "public.consentimento_recibo",
    ]
    for statement in sql.split(";"):
        # Parent FKs and read-only catalog inspections are allowed, mutations
        # of the existing parent/ledger ACL/schema are not.
        assert not re.search(
            r"\b(?:grant|revoke|alter\s+table|create\s+policy)\b[^;]*"
            r"\bon\s+(?:table\s+)?public\.(?:pessoas|consentimento_finalidade_evento)\b",
            statement, re.IGNORECASE,
        )
        assert not re.search(
            r"\balter\s+table\s+public\.(?:pessoas|consentimento_finalidade_evento)\b",
            statement, re.IGNORECASE,
        )
    adapter = (ROOT / "backend/app/services/consent_evidence_store_postgres.py").read_text()
    assert "def lock_person(" not in adapter
    assert "from public.pessoas" not in adapter
    assert 'f"{igreja_id}:{pessoa_id}:{finalidade.value}"' in adapter


def test_rendered_candidate_binds_exact_sql_and_collected_pg17_nodeids():
    sql_path = ROOT / "backend/migrations/20260908_175522_consent_evidence_store_lab.sql"
    sql_bytes = sql_path.read_bytes()
    intent = json.loads(sql_bytes.decode().splitlines()[0].split("=", 1)[1])
    candidate = json.loads((ROOT / "docs/governance/consent/evidence-store/migration-head.candidate.json").read_text())
    terminal = candidate["append_only_batches"][-1]["entries"][-1]
    assert terminal["name"] == sql_path.name
    assert terminal["sha256"] == hashlib.sha256(sql_bytes).hexdigest()
    assert terminal["size_bytes"] == len(sql_bytes)
    declared = set(intent["pg17_test_nodeids"])
    actual = set()
    for name in ("test_consent_evidence_store_pg17.py", "test_consent_evidence_store_canonical_pg17.py"):
        relative = "backend/tests/" + name
        tree = ast.parse((ROOT / relative).read_text())
        actual.update(relative + "::" + node.name for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"))
    assert declared == actual
    assert set(intent["cross_tenant_test_nodeids"]) <= actual
