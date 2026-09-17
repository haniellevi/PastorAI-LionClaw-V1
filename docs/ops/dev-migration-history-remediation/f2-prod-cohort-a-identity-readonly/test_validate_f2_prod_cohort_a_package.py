#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = Path(__file__).resolve().parent
MISSION = ROOT / "docs/missions/M-2026-09-17-f2-prod-cohort-a-identity-readonly.md"
SQL = PACKAGE / "PROD-READONLY-F2-COHORT-A.sql"
RUNBOOK = PACKAGE / "RANIEL-PROD-COHORT-A-RUNBOOK.md"
RUNNER = PACKAGE / "run-pg17-f2-prod-cohort-a-e2e.sh"

EXPECTED_FILES = {
    "BRIEFING.md",
    "CANDIDATE-MANIFEST.md",
    "EVIDENCE-CONTRACT.md",
    "PROD-READONLY-F2-COHORT-A.sql",
    "RANIEL-PROD-COHORT-A-RUNBOOK.md",
    "SOURCE-PINS.md",
    "run-pg17-f2-prod-cohort-a-e2e.sh",
    "test_validate_f2_prod_cohort_a_package.py",
}
EXPECTED_POSITIONS = "1,2,3,4,5,6,7,8,9,10,11,12,13,14,22,23,24,25,26,29,31,32"
EXPECTED_SQL_SHA256 = "84898a80b53c41e3dbaf6b68bea2911a99116ccbf48e6f4f05eed6562c9ba7e7"
PINS = {
    "c7831ca5d17b8c250e2cd7a6bc1a5f65c66ddcd874ddbca214c16f4d067b8830",
    "d3f0e9610ace59d704bb5e77dc49e52f6f115cdf2b7847a8bd7e0b5bcc3c85e8",
    "5399bb7db895be26c7fb0dcaf67375d0aa7a78c58c03de80b50ed27a9fd2944d",
}
GATE = "OWNER_AUTHORIZE_PROD_UNMATCHED_IDENTITY_EVIDENCE_READ_ONLY"

def require(condition: bool, code: str) -> None:
    if not condition:
        raise SystemExit(f"RESULT=FAIL_F2_PROD_COHORT_A_PACKAGE_{code}")

require(MISSION.is_file(), "MISSION_MISSING")
require(SQL.is_file() and not SQL.is_symlink(), "SQL_SOURCE")
require(hashlib.sha256(SQL.read_bytes()).hexdigest() == EXPECTED_SQL_SHA256, "SQL_SHA256")
require({p.name for p in PACKAGE.iterdir() if p.is_file()} == EXPECTED_FILES, "FILE_SET")

texts = {
    path: path.read_text(encoding="utf-8")
    for path in [MISSION, *sorted(PACKAGE.iterdir())]
    if path.is_file()
}
joined = "\n".join(texts.values())
require(PINS <= set(re.findall(r"\b[0-9a-f]{64}\b", joined)), "SOURCE_PINS")
require(
    set(re.findall(r"OWNER_AUTHORIZE_[A-Z0-9_]+", joined)) == {GATE},
    "GATE_SET",
)
require("execution_authorized: false" in texts[MISSION], "EXECUTION_FLAG")
require(EXPECTED_POSITIONS in texts[SQL], "POSITIONS")
future_label = "coorte " + chr(66)
future_symbol = "COORTE_" + chr(66)
require(future_label not in joined and future_symbol not in joined, "FUTURE_COHORT_DRAFT")
home_prefix = "/" + "home/"
require(home_prefix not in joined, "PERSONAL_PATH")

source = texts[SQL]
for item in (
    "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY",
    "SET LOCAL statement_timeout = '5000ms'",
    "SET LOCAL lock_timeout = '1000ms'",
    "SET LOCAL idle_in_transaction_session_timeout = '15000ms'",
    "SET LOCAL row_security = off",
    "pg_catalog.count(DISTINCT forward_identity_ref) = 22",
    "\\qecho ROLLBACK_COMPLETED_F2_PROD_COHORT_A_IDENTITY",
):
    require(item in source, "SQL_CONTRACT")
require(not re.search(r"(?m)^\\echo(?:\s|$)", source), "ECHO_FORBIDDEN")
require(
    not re.search(
        r"(?im)^\s*(?:INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|"
        r"GRANT|REVOKE|COPY|CALL|DO|EXPLAIN)\b",
        source,
    ),
    "SQL_WRITE_TOKEN",
)
without_comments = re.sub(r"(?m)^\s*--.*$", "", source)
allowed_relations = {
    "relation_shape", "columns_ok", "ordered", "cohort", "commitments",
    "pg_catalog.pg_namespace", "pg_catalog.pg_class",
    "pg_catalog.pg_attribute", "pg_catalog.pg_trigger",
    "pg_catalog.pg_rewrite", "supabase_migrations.schema_migrations",
}
relations = set(
    re.findall(r"(?im)\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_\.]*)", without_comments)
)
require(relations <= allowed_relations, "SQL_SOURCE_SCOPE")

forward_blocks = re.findall(
    r"'F2-PROD-COHORT-A-FORWARD-v1'.+?AS forward_identity_ref",
    source,
    flags=re.S,
)
require(len(forward_blocks) == 2, "FORWARD_FORMULA_COUNT")
for block in forward_blocks:
    require("statements" in block, "FORWARD_STATEMENTS")
    require(not re.search(r"\b(?:version|name|scope_ordinal)\b", block), "FORWARD_METADATA")

runner = texts[RUNNER]
require(EXPECTED_SQL_SHA256 in runner, "RUNNER_SQL_PIN")
for item in (
    "--network none",
    "--pull=never",
    "container_owned=true",
    "RESULT=BLOCKED_EXISTING_DISPOSABLE_CONTAINER",
    "chmod 700",
    "install -m 600",
    "RAW_VALUE_LEAK",
    "COLLISION_NOT_BLOCKED",
    "CARDINALITY_NOT_BLOCKED",
    "MATERIAL_NOT_BLOCKED",
):
    require(item in runner, "RUNNER_CONTRACT")
require("docker run" in runner and "-p " not in runner and "--publish" not in runner, "RUNNER_NETWORK")

runbook = texts[RUNBOOK]
require("arquivo novo" in runbook and "0600" in runbook, "RUNBOOK_OUTPUT_MODE")
require("não pode ser executado" in runbook, "RUNBOOK_GATE_CLOSED")
require("Não repita" in runbook, "RUNBOOK_NO_RETRY")

print("RESULT=PASS_F2_PROD_COHORT_A_PACKAGE_STATIC")
