#!/usr/bin/env bash
set -euo pipefail

candidate_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
sql_file="$candidate_dir/PROD-READONLY-F2-COHORT-A.sql"
expected_sql_sha256="84898a80b53c41e3dbaf6b68bea2911a99116ccbf48e6f4f05eed6562c9ba7e7"
container_name="igreja12-f2-prod-cohort-a-pg17"
image_ref="postgres:17.6-trixie"
runner_path="$candidate_dir/run-pg17-f2-prod-cohort-a-e2e.sh"
existing_container_rc=6
container_owned=false
owned_container_id=""
ownership_fixture_child="${F2_COHORT_A_OWNERSHIP_FIXTURE_CHILD:-0}"
binding_primary="1111111111111111111111111111111111111111111111111111111111111111"
binding_alternate="2222222222222222222222222222222222222222222222222222222222222222"
tmp_dir=""

fail() {
  printf '%s\n' "RESULT=FAIL_F2_PROD_COHORT_A_$1"
  exit "${2:-1}"
}

cleanup() {
  local current_container_id
  if [[ -n "$tmp_dir" && -d "$tmp_dir" ]]; then
    rm -rf -- "$tmp_dir"
  fi
  tmp_dir=""
  [[ "$container_owned" == true ]] || return 0
  current_container_id="$(docker container inspect -f '{{.Id}}' "$container_name" 2>/dev/null || true)"
  if [[ -n "$owned_container_id" && "$current_container_id" == "$owned_container_id" ]]; then
    docker stop "$owned_container_id" >/dev/null 2>&1 || true
  fi
  container_owned=false
  owned_container_id=""
}

block_existing_container() {
  printf '%s\n' 'RESULT=BLOCKED_EXISTING_DISPOSABLE_CONTAINER'
  exit "$existing_container_rc"
}

run_owned_container() {
  if ! owned_container_id="$(docker run --pull=never --rm --network none --name "$container_name" \
    --mount "type=bind,src=$candidate_dir,dst=/f2,readonly" \
    -e POSTGRES_HOST_AUTH_METHOD=trust \
    -d "$image_ref" 2>/dev/null)"; then
    if docker container inspect "$container_name" >/dev/null 2>&1; then
      block_existing_container
    fi
    printf '%s\n' 'RESULT=BLOCKED_PG17_6_CONTAINER_START'
    exit 8
  fi
  [[ "$owned_container_id" =~ ^[0-9a-f]{64}$ ]] || fail CONTAINER_OWNERSHIP_ID_INVALID 12
  container_owned=true
  trap cleanup EXIT
}

run_ownership_fixture() {
  local child_output child_rc
  run_owned_container
  set +e
  child_output="$(F2_COHORT_A_OWNERSHIP_FIXTURE_CHILD=1 bash "$runner_path" 2>&1)"
  child_rc=$?
  set -e
  [[ "$child_rc" -eq "$existing_container_rc" ]] || fail OWNERSHIP_FIXTURE_RC 13
  [[ "$child_output" == 'RESULT=BLOCKED_EXISTING_DISPOSABLE_CONTAINER' ]] ||
    fail OWNERSHIP_FIXTURE_OUTPUT 14
  [[ "$(docker inspect -f '{{.State.Status}}' "$container_name")" == 'running' ]] ||
    fail OWNERSHIP_FIXTURE_CONTAINER_REMOVED 15
  cleanup
}

run_sql() {
  local database="$1"
  local binding="$2"
  local output="$3"
  install -m 600 /dev/null "$output"
  docker exec -i "$container_name" psql -X -q -A -t -F '|' -P pager=off \
    -v ON_ERROR_STOP=1 -v "f2_cohort_a_binding=$binding" \
    -U postgres -d "$database" -f /f2/PROD-READONLY-F2-COHORT-A.sql >"$output"
  [[ "$(stat -c '%a' "$output")" == 600 ]] || fail OUTPUT_MODE
}

target_digest() {
  awk -F'|' '$1 == "TARGET_DIGEST" {count += 1; value = $2}
    END {if (count == 1 && value ~ /^[0-9a-f]{64}$/) print value}' "$1"
}

if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'RESULT=BLOCKED_DOCKER_UNAVAILABLE'
  exit 3
fi
[[ -f "$sql_file" && ! -L "$sql_file" ]] || fail SQL_SOURCE
sql_mode="$(stat -c '%a' "$sql_file")"
(( (8#$sql_mode & 8#022) == 0 )) || fail SQL_MODE
actual_sql_sha256="$(sha256sum "$sql_file" | awk '{print $1}')"
[[ "$actual_sql_sha256" == "$expected_sql_sha256" ]] || fail SQL_SHA256
unset actual_sql_sha256 sql_mode

if ! python3 -I -B - "$sql_file" <<'PY'
from __future__ import annotations
import re
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text(encoding="utf-8")
required = (
    "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY",
    "SET LOCAL search_path = pg_catalog",
    "SET LOCAL statement_timeout = '5000ms'",
    "SET LOCAL lock_timeout = '1000ms'",
    "SET LOCAL idle_in_transaction_session_timeout = '15000ms'",
    "SET LOCAL row_security = off",
    "ARRAY[1,2,3,4,5,6,7,8,9,10,11,12,13,14,22,23,24,25,26,29,31,32]",
    "F2_ABORT_COHORT_A_IDENTITY_COLLISION",
    "\\qecho ROLLBACK_COMPLETED_F2_PROD_COHORT_A_IDENTITY",
)
if any(item not in source for item in required):
    raise SystemExit(20)
if re.search(r"(?m)^\\echo(?:\s|$)", source):
    raise SystemExit(21)
if re.search(
    r"(?im)^\s*(?:INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|"
    r"GRANT|REVOKE|COPY|CALL|DO|EXPLAIN)\b",
    source,
):
    raise SystemExit(22)
without_comments = re.sub(r"(?m)^\s*--.*$", "", source)
allowed = {
    "relation_shape", "columns_ok", "ordered", "cohort", "commitments",
    "pg_catalog.pg_namespace", "pg_catalog.pg_class",
    "pg_catalog.pg_attribute", "pg_catalog.pg_trigger",
    "pg_catalog.pg_rewrite", "supabase_migrations.schema_migrations",
}
for relation in re.findall(
    r"(?im)\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_\.]*)",
    without_comments,
):
    if relation not in allowed:
        raise SystemExit(23)
if not re.search(
    r"(?ms)ROLLBACK;\s*\\qecho ROLLBACK_COMPLETED_F2_PROD_COHORT_A_IDENTITY"
    r"\s*\\quit\s*$",
    without_comments,
):
    raise SystemExit(24)
PY
then
  fail STATIC_SOURCE_CONTRACT 5
fi

if docker container inspect "$container_name" >/dev/null 2>&1; then
  block_existing_container
fi
if [[ "$ownership_fixture_child" == 1 ]]; then
  fail OWNERSHIP_FIXTURE_CHILD_WITHOUT_CONTAINER 16
fi
if ! docker image inspect "$image_ref" >/dev/null 2>&1; then
  printf '%s\n' 'RESULT=BLOCKED_PG17_6_IMAGE_UNAVAILABLE'
  exit 7
fi

run_ownership_fixture
run_owned_container

for _attempt in $(seq 1 60); do
  docker exec "$container_name" pg_isready -U postgres -d postgres >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$container_name" pg_isready -U postgres -d postgres >/dev/null 2>&1 ||
  fail PG17_NOT_READY 9
[[ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$container_name")" == none ]] ||
  fail CONTAINER_NETWORK
port_bindings="$(docker inspect -f '{{json .HostConfig.PortBindings}}' "$container_name")"
[[ "$port_bindings" == null || "$port_bindings" == "{}" ]] || fail CONTAINER_PORT

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 -U postgres -d postgres <<'SQL'
CREATE DATABASE cohort_a_ok;
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 -U postgres -d cohort_a_ok <<'SQL'
CREATE SCHEMA supabase_migrations;
CREATE TABLE supabase_migrations.schema_migrations (
  version text NOT NULL,
  statements text[],
  name text,
  created_by text,
  idempotency_key text,
  rollback text[]
);
INSERT INTO supabase_migrations.schema_migrations
  (version, statements, name, created_by, idempotency_key, rollback)
SELECT
  pg_catalog.lpad(i::text, 14, '0'),
  ARRAY['private_statement_sentinel_' || i::text],
  'private_name_sentinel_' || i::text,
  'private_creator_sentinel',
  CASE WHEN i % 2 = 0 THEN 'private_idempotency_sentinel_' || i::text ELSE NULL END,
  CASE WHEN i % 3 = 0 THEN ARRAY['private_rollback_sentinel_' || i::text] ELSE NULL END
FROM pg_catalog.generate_series(1, 32) AS i;
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 -U postgres -d postgres <<'SQL'
CREATE DATABASE cohort_a_collision TEMPLATE cohort_a_ok;
CREATE DATABASE cohort_a_cardinality TEMPLATE cohort_a_ok;
CREATE DATABASE cohort_a_material TEMPLATE cohort_a_ok;
CREATE DATABASE cohort_a_other TEMPLATE cohort_a_ok;
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 -U postgres -d cohort_a_collision <<'SQL'
UPDATE supabase_migrations.schema_migrations AS target
SET statements = source.statements
FROM supabase_migrations.schema_migrations AS source
WHERE target.version = '00000000000002'
  AND source.version = '00000000000001';
SQL
docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 -U postgres -d cohort_a_cardinality <<'SQL'
DELETE FROM supabase_migrations.schema_migrations WHERE version = '00000000000032';
SQL
docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 -U postgres -d cohort_a_material <<'SQL'
UPDATE supabase_migrations.schema_migrations SET statements = NULL
WHERE version = '00000000000001';
SQL

tmp_dir="$(mktemp -d)"
chmod 700 "$tmp_dir"
run_sql cohort_a_ok "$binding_primary" "$tmp_dir/ok-1.txt"
run_sql cohort_a_ok "$binding_primary" "$tmp_dir/ok-2.txt"
run_sql cohort_a_ok "$binding_alternate" "$tmp_dir/alternate.txt"
run_sql cohort_a_other "$binding_primary" "$tmp_dir/other-db.txt"
run_sql cohort_a_collision "$binding_primary" "$tmp_dir/collision.txt"
run_sql cohort_a_cardinality "$binding_primary" "$tmp_dir/cardinality.txt"
run_sql cohort_a_material "$binding_primary" "$tmp_dir/material.txt"

cmp -s "$tmp_dir/ok-1.txt" "$tmp_dir/ok-2.txt" || fail NONDETERMINISTIC_OUTPUT
[[ "$(tail -n 1 "$tmp_dir/ok-1.txt")" == ROLLBACK_COMPLETED_F2_PROD_COHORT_A_IDENTITY ]] ||
  fail FINAL_RECEIPT
[[ "$(grep -c '^COHORT_A_ENTRY|' "$tmp_dir/ok-1.txt")" -eq 22 ]] ||
  fail ENTRY_COUNT
expected_positions="1 2 3 4 5 6 7 8 9 10 11 12 13 14 22 23 24 25 26 29 31 32"
actual_positions="$(awk -F'|' '$1 == "COHORT_A_ENTRY" {print $2}' "$tmp_dir/ok-1.txt" | paste -sd' ' -)"
[[ "$actual_positions" == "$expected_positions" ]] || fail ENTRY_POSITIONS
[[ "$(awk -F'|' '$1 == "COHORT_A_ENTRY" {print $8}' "$tmp_dir/ok-1.txt" | sort -u | wc -l)" -eq 22 ]] ||
  fail IDENTITY_UNIQUENESS
if grep -Eq 'private_(statement|name|creator|idempotency|rollback)_sentinel' "$tmp_dir/ok-1.txt"; then
  fail RAW_VALUE_LEAK
fi
[[ "$(target_digest "$tmp_dir/ok-1.txt")" == "$(target_digest "$tmp_dir/ok-2.txt")" ]] ||
  fail DIGEST_NOT_STABLE
[[ "$(target_digest "$tmp_dir/ok-1.txt")" != "$(target_digest "$tmp_dir/alternate.txt")" ]] ||
  fail DIGEST_BINDING_NOT_DISTINCT
[[ "$(target_digest "$tmp_dir/ok-1.txt")" != "$(target_digest "$tmp_dir/other-db.txt")" ]] ||
  fail DIGEST_DATABASE_NOT_DISTINCT
grep -qx 'F2_ABORT_COHORT_A_IDENTITY_COLLISION' "$tmp_dir/collision.txt" ||
  fail COLLISION_NOT_BLOCKED
grep -qx 'F2_ABORT_COHORT_A_LEDGER_CARDINALITY' "$tmp_dir/cardinality.txt" ||
  fail CARDINALITY_NOT_BLOCKED
grep -qx 'F2_ABORT_COHORT_A_IDENTITY_MATERIAL' "$tmp_dir/material.txt" ||
  fail MATERIAL_NOT_BLOCKED

printf '%s\n' 'RESULT=PASS_PG17_F2_PROD_COHORT_A_IDENTITY'
