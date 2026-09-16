#!/usr/bin/env bash
set -euo pipefail

candidate_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
container_name="igreja12-f2-readonly-pg17-e2e"
image_ref="postgres:17.6-trixie"
runner_path="$candidate_dir/run-pg17-f2-e2e.sh"
existing_container_rc=3
container_owned=false
owned_container_id=""
ownership_fixture_child="${F2_READONLY_OWNERSHIP_FIXTURE_CHILD:-0}"
prod_binding="1111111111111111111111111111111111111111111111111111111111111111"
dev_binding="2222222222222222222222222222222222222222222222222222222222222222"
alternate_binding="3333333333333333333333333333333333333333333333333333333333333333"

fail() {
  printf '%s\n' "RESULT=FAIL_$1"
  exit "${2:-1}"
}

cleanup() {
  local current_container_id
  [[ "$container_owned" == true ]] || return 0
  current_container_id="$(docker container inspect -f '{{.Id}}' "$container_name" 2>/dev/null || true)"
  if [[ -n "$owned_container_id" && "$current_container_id" == "$owned_container_id" ]]; then
    docker stop "$owned_container_id" >/dev/null 2>&1 || true
  fi
  container_owned=false
  owned_container_id=""
}

block_existing_container() {
  printf '%s\n' "RESULT=BLOCKED_EXISTING_DISPOSABLE_CONTAINER"
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
    printf '%s\n' "RESULT=BLOCKED_PG17_6_CONTAINER_START"
    exit 5
  fi
  [[ "$owned_container_id" =~ ^[0-9a-f]{64}$ ]] || fail "CONTAINER_OWNERSHIP_ID_INVALID" 13
  container_owned=true
  trap cleanup EXIT
}

wait_for_owned_container_running() {
  local container_state
  for _attempt in $(seq 1 20); do
    container_state="$(docker inspect -f '{{.State.Status}}' "$container_name" 2>/dev/null || true)"
    [[ "$container_state" == "running" ]] && return 0
    sleep 1
  done
  return 1
}

run_ownership_fixture() {
  local fixture_child_output fixture_child_rc
  run_owned_container
  set +e
  fixture_child_output="$(F2_READONLY_OWNERSHIP_FIXTURE_CHILD=1 bash "$runner_path" 2>&1)"
  fixture_child_rc=$?
  set -e
  [[ "$fixture_child_rc" -eq "$existing_container_rc" && \
    "$fixture_child_output" == "RESULT=BLOCKED_EXISTING_DISPOSABLE_CONTAINER" ]] \
    || fail "OWNERSHIP_FIXTURE_CHILD_CONTRACT" 14
  wait_for_owned_container_running || fail "OWNERSHIP_FIXTURE_CONTAINER_NOT_RUNNING" 15
  cleanup
}

for sql_file in PROD-READONLY-F2.sql DEV-READONLY-F2.sql; do
  if grep -Eq '^\\echo([[:space:]]|$)' "$candidate_dir/$sql_file"; then
    fail "ECHO_FORBIDDEN_IN_${sql_file}" 10
  fi
  if grep -Eiq '^[[:space:]]*(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|COPY|CALL|DO|EXPLAIN)[[:space:]]' "$candidate_dir/$sql_file"; then
    fail "WRITE_OR_ANALYZE_STATEMENT_IN_${sql_file}" 11
  fi
  for required in \
    "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY" \
    "SET LOCAL statement_timeout = '5000ms'" \
    "SET LOCAL lock_timeout = '1000ms'" \
    "SET LOCAL idle_in_transaction_session_timeout = '15000ms'" \
    "SET LOCAL row_security = off" \
    "pg_catalog.convert_to" \
    "'UTF8'" \
    "pg_catalog.encode" \
    "'hex'" \
    "ROLLBACK;" \
    "\\qecho"; do
    grep -Fq -- "$required" "$candidate_dir/$sql_file" \
      || fail "REQUIRED_CONTRACT_MISSING_IN_${sql_file}" 12
  done
done

if docker container inspect "$container_name" >/dev/null 2>&1; then
  block_existing_container
fi
if [[ "$ownership_fixture_child" == "1" ]]; then
  fail "OWNERSHIP_FIXTURE_CHILD_WITHOUT_PREEXISTING_CONTAINER" 16
fi
if ! docker image inspect "$image_ref" >/dev/null 2>&1; then
  printf '%s\n' "RESULT=BLOCKED_PG17_6_IMAGE_UNAVAILABLE"
  exit 4
fi

run_ownership_fixture
run_owned_container

for _attempt in $(seq 1 60); do
  docker exec "$container_name" pg_isready -U postgres -d postgres >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$container_name" pg_isready -U postgres -d postgres >/dev/null 2>&1 \
  || fail "PG17_NOT_READY" 6

network_mode="$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$container_name")"
port_bindings="$(docker inspect -f '{{json .HostConfig.PortBindings}}' "$container_name")"
[[ "$network_mode" == "none" ]] || fail "CONTAINER_NETWORK_NOT_NONE" 7
[[ "$port_bindings" == "null" || "$port_bindings" == "{}" ]] \
  || fail "CONTAINER_PORT_PUBLISHED" 8

# All writes below are fixtures inside the disposable local PG17 container.
docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 -U postgres -d postgres <<'SQL'
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
CREATE ROLE service_role NOLOGIN;
CREATE ROLE agent_runtime NOLOGIN;
CREATE ROLE authenticator NOLOGIN;
CREATE ROLE supabase_storage_admin NOLOGIN;
CREATE ROLE pgbouncer NOLOGIN;
CREATE ROLE supabase_realtime_admin NOLOGIN;
CREATE ROLE supabase_replication_admin NOLOGIN;
CREATE ROLE f2_private_fixture_role NOLOGIN;
CREATE ROLE f2_private_default_owner NOLOGIN;
CREATE DATABASE f2_prod;
CREATE DATABASE f2_dev;
SQL

setup_common() {
  local database_name="$1"
  docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
    -U postgres -d "$database_name" <<'SQL'
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
  ARRAY['/* f2_private_statement_marker */ CREATE TABLE hidden_' || i::text || ' (id int)'],
  NULL, NULL, NULL, NULL
FROM pg_catalog.generate_series(1, 6) AS i;
CREATE SCHEMA agent_private;
CREATE SCHEMA recovery;
CREATE TABLE public.f2_private_relation_fixture (
  id bigint PRIMARY KEY,
  private_value text NOT NULL DEFAULT 'f2_private_default_marker'
);
CREATE INDEX f2_private_index_fixture
  ON public.f2_private_relation_fixture (private_value);
ALTER TABLE public.f2_private_relation_fixture ENABLE ROW LEVEL SECURITY;
CREATE POLICY f2_private_policy_fixture
  ON public.f2_private_relation_fixture USING (true);
CREATE FUNCTION public.f2_private_trigger_function_fixture()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;
CREATE TRIGGER f2_private_trigger_fixture
BEFORE INSERT ON public.f2_private_relation_fixture
FOR EACH ROW EXECUTE FUNCTION public.f2_private_trigger_function_fixture();
CREATE TABLE agent_private.f2_agent_private_relation_fixture (id bigint);
CREATE FUNCTION agent_private.f2_agent_private_function_fixture()
RETURNS bigint LANGUAGE sql AS $$ SELECT 1::bigint $$;
CREATE TABLE recovery.f2_recovery_relation_fixture (id bigint);
GRANT USAGE ON SCHEMA public, agent_private, recovery TO f2_private_fixture_role;
GRANT SELECT ON public.f2_private_relation_fixture TO f2_private_fixture_role;
GRANT EXECUTE ON FUNCTION agent_private.f2_agent_private_function_fixture()
  TO f2_private_fixture_role;
SET ROLE f2_private_default_owner;
ALTER DEFAULT PRIVILEGES IN SCHEMA agent_private
  GRANT SELECT ON TABLES TO f2_private_fixture_role;
RESET ROLE;
SQL
}

setup_common f2_prod
setup_common f2_dev

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d f2_dev <<'SQL'
CREATE TABLE public.schema_migrations (
  name text NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY;
INSERT INTO public.schema_migrations (name, applied_at)
SELECT 'f2_public_migration_' || pg_catalog.lpad(i::text, 2, '0') || '.sql',
       '2026-01-01 00:00:00+00'::timestamptz + (i || ' seconds')::interval
FROM pg_catalog.generate_series(1, 33) AS i;
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d postgres <<'SQL'
CREATE DATABASE f2_prod_clone TEMPLATE f2_prod;
CREATE DATABASE f2_prod_public_drift TEMPLATE f2_prod;
CREATE DATABASE f2_prod_native_drift TEMPLATE f2_prod;
CREATE DATABASE f2_dev_count_drift TEMPLATE f2_dev;
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d f2_prod_public_drift <<'SQL'
CREATE TABLE public.schema_migrations (
  name text NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now()
);
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d f2_prod_native_drift \
  -c "DELETE FROM supabase_migrations.schema_migrations WHERE version = '00000000000006';"
docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d f2_dev_count_drift \
  -c "DELETE FROM public.schema_migrations WHERE name = 'f2_public_migration_33.sql';"

run_capture() {
  local database_name="$1"
  local binding_value="$2"
  local sql_file="$3"
  local transport="${4:-socket}"
  local capture_file="/tmp/f2-$RANDOM-$RANDOM.txt"
  local -a host_args=()
  local rc
  if [[ "$transport" == "tcp" ]]; then
    host_args=(-h 127.0.0.1)
  fi
  if printf '\\o %s\n\\i /f2/%s\n\\o\n' "$capture_file" "$sql_file" \
    | docker exec -i "$container_name" psql -X -q -A -t -F '|' \
        -v ON_ERROR_STOP=1 -v "f2_target_binding_sha256=$binding_value" \
        "${host_args[@]}" -U postgres -d "$database_name" >/dev/null 2>&1; then
    rc=0
  else
    rc=$?
  fi
  docker exec "$container_name" cat "$capture_file" 2>/dev/null || true
  docker exec "$container_name" rm -f "$capture_file" >/dev/null 2>&1 || true
  return "$rc"
}

extract_digest() {
  awk -F'|' '$1 == "TARGET_DIGEST" { count += 1; value = $2 }
    END { if (count == 1 && value ~ /^[0-9a-f]{64}$/) print value }'
}

assert_success() {
  local output="$1"
  local environment="$2"
  local receipt="F2_${environment}_FINAL_RECEIPT=ROLLBACK_COMPLETED_F2_${environment}"
  [[ "$(printf '%s\n' "$output" | grep -Fxc "$receipt")" == "1" ]] \
    || fail "${environment}_RECEIPT_COUNT" 20
  [[ "$(printf '%s\n' "$output" | tail -n 1)" == "$receipt" ]] \
    || fail "${environment}_RECEIPT_NOT_TERMINAL" 21
  [[ "$output" != *"F2_ABORT_"* ]] || fail "${environment}_UNEXPECTED_ABORT" 22
  printf '%s\n' "$output" | grep -Eq \
    "^F2_SESSION\\|${environment}\\|170006\\|repeatable read\\|on\\|5s\\|1s\\|15s\\|off\\|" \
    || fail "${environment}_SESSION_CONTRACT" 23
  printf '%s\n' "$output" | grep -Eq '^TARGET_DIGEST\|[0-9a-f]{64}$' \
    || fail "${environment}_TARGET_DIGEST" 24
}

prod_output="$(run_capture f2_prod "$prod_binding" PROD-READONLY-F2.sql)" \
  || fail "PROD_SUCCESS_EXECUTION" 30
dev_output="$(run_capture f2_dev "$dev_binding" DEV-READONLY-F2.sql)" \
  || fail "DEV_SUCCESS_EXECUTION" 31
assert_success "$prod_output" PROD
assert_success "$dev_output" DEV

[[ "$prod_output" == *"PUBLIC_LEDGER_FORM|ABSENT_ACCEPTED"* ]] \
  || fail "PROD_PUBLIC_ABSENT_NOT_CONFIRMED" 32
[[ "$prod_output" == *"NATIVE_LEDGER_COUNT_EXPECTATION|EXPECTED_6"* ]] \
  || fail "PROD_NATIVE_6_NOT_CONFIRMED" 33
[[ "$prod_output" != *"PUBLIC_LEDGER_COUNT_EXPECTATION|EXPECTED_33"* ]] \
  || fail "PROD_REUSED_DEV_EXPECTATION" 34
[[ "$dev_output" == *"PUBLIC_LEDGER_COUNT_EXPECTATION|EXPECTED_33"* ]] \
  || fail "DEV_PUBLIC_33_NOT_CONFIRMED" 35
[[ "$dev_output" == *"NATIVE_LEDGER_COUNT_EXPECTATION|EXPECTED_6"* ]] \
  || fail "DEV_NATIVE_6_NOT_CONFIRMED" 36

combined_output="$prod_output"$'\n'"$dev_output"
for forbidden in \
  f2_private_fixture_role \
  f2_private_default_owner \
  f2_private_relation_fixture \
  f2_private_index_fixture \
  f2_private_policy_fixture \
  f2_private_trigger_fixture \
  f2_private_trigger_function_fixture \
  f2_agent_private_relation_fixture \
  f2_agent_private_function_fixture \
  f2_recovery_relation_fixture \
  f2_private_statement_marker \
  f2_private_default_marker \
  "$prod_binding" "$dev_binding" \
  f2_prod f2_dev; do
  [[ "$combined_output" != *"$forbidden"* ]] \
    || fail "SANITIZATION_LEAK" 40
done
for required_pattern in \
  '^CATALOG_RELATION\\|PUBLIC_SCHEMA\\|OPAQUE_RELATION_[0-9a-f]{32}\\|' \
  '^CATALOG_FUNCTION\\|AGENT_PRIVATE_SCHEMA\\|OPAQUE_FUNCTION_[0-9a-f]{32}\\|' \
  '^CATALOG_CONSTRAINT\\|PUBLIC_SCHEMA\\|OPAQUE_RELATION_[0-9a-f]{32}\\|OPAQUE_CONSTRAINT_[0-9a-f]{32}\\|' \
  '^CATALOG_INDEX\\|PUBLIC_SCHEMA\\|OPAQUE_RELATION_[0-9a-f]{32}\\|OPAQUE_INDEX_[0-9a-f]{32}\\|' \
  '^CATALOG_RLS_POLICY\\|PUBLIC_SCHEMA\\|OPAQUE_RELATION_[0-9a-f]{32}\\|OPAQUE_POLICY_[0-9a-f]{32}\\|' \
  '^CATALOG_TRIGGER\\|PUBLIC_SCHEMA\\|OPAQUE_RELATION_[0-9a-f]{32}\\|OPAQUE_TRIGGER_[0-9a-f]{32}\\|' \
  '^SCHEMA_ACL_DIRECT_GRANTEE\\|PUBLIC_SCHEMA\\|UNEXPECTED_CUSTOM_GRANTEE\\|UNEXPECTED_CUSTOM_GRANTEE\\|USAGE\\|' \
  '^DEFAULT_ACL_DIRECT_GRANTEE\\|AGENT_PRIVATE_SCHEMA\\|r\\|UNEXPECTED_CUSTOM_GRANTEE\\|UNEXPECTED_CUSTOM_GRANTEE\\|SELECT\\|'; do
  printf '%s\n' "$combined_output" | grep -Eq "$required_pattern" \
    || fail "OPAQUE_OR_ACL_FIXTURE_NOT_PROVEN" 41
done

prod_repeat="$(run_capture f2_prod "$prod_binding" PROD-READONLY-F2.sql)" \
  || fail "PROD_REPEAT_EXECUTION" 50
prod_alt="$(run_capture f2_prod "$alternate_binding" PROD-READONLY-F2.sql)" \
  || fail "PROD_ALTERNATE_BINDING_EXECUTION" 51
prod_clone="$(run_capture f2_prod_clone "$prod_binding" PROD-READONLY-F2.sql)" \
  || fail "PROD_CLONE_DATABASE_EXECUTION" 52
prod_tcp="$(run_capture f2_prod "$prod_binding" PROD-READONLY-F2.sql tcp)" \
  || fail "PROD_TCP_EXECUTION" 53
for output in "$prod_repeat" "$prod_alt" "$prod_clone" "$prod_tcp"; do
  assert_success "$output" PROD
done

prod_digest="$(printf '%s\n' "$prod_output" | extract_digest)"
repeat_digest="$(printf '%s\n' "$prod_repeat" | extract_digest)"
alt_digest="$(printf '%s\n' "$prod_alt" | extract_digest)"
clone_digest="$(printf '%s\n' "$prod_clone" | extract_digest)"
tcp_digest="$(printf '%s\n' "$prod_tcp" | extract_digest)"
[[ -n "$prod_digest" && "$prod_digest" == "$repeat_digest" ]] \
  || fail "DIGEST_NOT_STABLE" 54
[[ "$prod_digest" != "$alt_digest" ]] || fail "DIGEST_NOT_BINDING_SENSITIVE" 55
[[ "$prod_digest" != "$clone_digest" ]] || fail "DIGEST_NOT_DATABASE_SENSITIVE" 56
[[ "$prod_digest" != "$tcp_digest" ]] || fail "DIGEST_NOT_PORT_SOCKET_SENSITIVE" 57

server_version_num="$(docker exec "$container_name" psql -X -q -A -t \
  -U postgres -d f2_prod -c "SELECT current_setting('server_version_num');")"
expected_socket_digest="$(printf '%s\x1f%s\x1f%s\x1f%s' \
  "$prod_binding" f2_prod UNIX_SOCKET "$server_version_num" | sha256sum | awk '{print $1}')"
[[ "$prod_digest" == "$expected_socket_digest" ]] || fail "DIGEST_FORMULA_MISMATCH" 58
changed_version_digest="$(printf '%s\x1f%s\x1f%s\x1f%s' \
  "$prod_binding" f2_prod UNIX_SOCKET 170007 | sha256sum | awk '{print $1}')"
[[ "$prod_digest" != "$changed_version_digest" ]] || fail "DIGEST_NOT_VERSION_SENSITIVE" 59

set +e
prod_public_drift="$(run_capture f2_prod_public_drift "$prod_binding" PROD-READONLY-F2.sql)"
prod_public_rc=$?
prod_native_drift="$(run_capture f2_prod_native_drift "$prod_binding" PROD-READONLY-F2.sql)"
prod_native_rc=$?
dev_count_drift="$(run_capture f2_dev_count_drift "$dev_binding" DEV-READONLY-F2.sql)"
dev_count_rc=$?
set -e
[[ "$prod_public_rc" -eq 0 && "$prod_public_drift" == "F2_ABORT_PROD_LEDGER_SHAPE_DRIFT" ]] \
  || fail "PROD_PUBLIC_DRIFT_NOT_FAIL_CLOSED" 60
[[ "$prod_native_rc" -eq 0 && "$prod_native_drift" == "F2_ABORT_PROD_LEDGER_SHAPE_DRIFT" ]] \
  || fail "PROD_NATIVE_DRIFT_NOT_FAIL_CLOSED" 61
[[ "$dev_count_rc" -eq 0 && "$dev_count_drift" == "F2_ABORT_DEV_LEDGER_SHAPE_DRIFT" ]] \
  || fail "DEV_COUNT_DRIFT_NOT_FAIL_CLOSED" 62

printf '%s\n' "RESULT=PASS_PG17_E2E_F2_PROD_DEV_STRICT_FUTURE"
