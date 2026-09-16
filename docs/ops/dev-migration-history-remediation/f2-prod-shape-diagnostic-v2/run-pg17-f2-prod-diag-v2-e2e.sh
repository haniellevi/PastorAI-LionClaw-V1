#!/usr/bin/env bash
set -euo pipefail

candidate_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
sql_file="$candidate_dir/PROD-READONLY-F2-DIAG-v2.sql"
container_name="igreja12-f2-prod-diag-v2-pg17"
image_ref="postgres:17.6-trixie"
binding_primary="1111111111111111111111111111111111111111111111111111111111111111"
binding_alternate="2222222222222222222222222222222222222222222222222222222222222222"

fail() {
  printf '%s\n' "RESULT=FAIL_F2_PROD_DIAG_V2_$1"
  exit "${2:-1}"
}

cleanup() {
  docker stop "$container_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'RESULT=BLOCKED_DOCKER_UNAVAILABLE'
  exit 3
fi

if [[ ! -f "$sql_file" ]]; then
  fail SQL_FILE_MISSING 4
fi

# A inspeção é source-only. Ela não abre banco e limita as fontes físicas aos
# catálogos PostgreSQL e aos dois ledgers canônicos do diagnóstico.
if ! python3 -I -B - "$sql_file" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text(encoding='utf-8')
required = (
    "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY",
    "SET LOCAL search_path = pg_catalog",
    "SET LOCAL statement_timeout = '5000ms'",
    "SET LOCAL lock_timeout = '1000ms'",
    "SET LOCAL idle_in_transaction_session_timeout = '15000ms'",
    "SET LOCAL row_security = off",
    "pg_catalog.convert_to(",
    "pg_catalog.current_database()",
    "pg_catalog.inet_server_port()::pg_catalog.text",
    "'UNIX_SOCKET'",
    "pg_catalog.current_setting('server_version_num')",
    "\\qecho ROLLBACK_COMPLETED_F2_PROD_DIAG",
    "\\quit",
)
if any(item not in source for item in required):
    raise SystemExit(10)
if re.search(r"(?m)^\\echo(?:\s|$)", source):
    raise SystemExit(11)
if source.count("\\qecho ROLLBACK_COMPLETED_F2_PROD_DIAG") != 1:
    raise SystemExit(12)
if re.search(
    r"(?im)^\s*(?:INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|"
    r"GRANT|REVOKE|COPY|CALL|DO|EXPLAIN)\b",
    source,
):
    raise SystemExit(13)
if re.search(r"(?i)\b(?:information_schema|pg_stat_|pg_settings|pg_roles)\b", source):
    raise SystemExit(14)

without_comments = re.sub(r"(?m)^\s*--.*$", "", source)
allowed_from_join = {
    "LATERAL",
    "target_ledgers",
    "observed",
    "pg_catalog.pg_namespace",
    "pg_catalog.pg_class",
    "pg_catalog.pg_attribute",
    "pg_catalog.pg_trigger",
    "pg_catalog.pg_rewrite",
    "pg_catalog.pg_type",
    "pg_catalog.pg_attrdef",
    "public.schema_migrations",
    "supabase_migrations.schema_migrations",
}
for relation in re.findall(
    r"(?im)\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_\.]*)",
    without_comments,
):
    if relation not in allowed_from_join:
        raise SystemExit(15)
if not re.search(
    r"(?ms)ROLLBACK;\s*\\qecho ROLLBACK_COMPLETED_F2_PROD_DIAG\s*\\quit\s*$",
    without_comments,
):
    raise SystemExit(16)
PY
then
  fail STATIC_SOURCE_CONTRACT 5
fi

if docker container inspect "$container_name" >/dev/null 2>&1; then
  printf '%s\n' 'RESULT=BLOCKED_EXISTING_DISPOSABLE_CONTAINER'
  exit 6
fi
if ! docker image inspect "$image_ref" >/dev/null 2>&1; then
  printf '%s\n' 'RESULT=BLOCKED_PG17_6_IMAGE_UNAVAILABLE'
  exit 7
fi
if ! docker run --pull=never --rm --network none --name "$container_name" \
  --mount "type=bind,src=$candidate_dir,dst=/f2,readonly" \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  -d "$image_ref" >/dev/null 2>&1; then
  printf '%s\n' 'RESULT=BLOCKED_PG17_6_CONTAINER_START'
  exit 8
fi

for _attempt in $(seq 1 60); do
  if docker exec "$container_name" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container_name" pg_isready -U postgres -d postgres >/dev/null 2>&1 \
  || fail PG17_NOT_READY 9

network_mode="$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$container_name")"
port_bindings="$(docker inspect -f '{{json .HostConfig.PortBindings}}' "$container_name")"
[[ "$network_mode" == "none" ]] || fail CONTAINER_NETWORK_NOT_NONE 10
[[ "$port_bindings" == "null" || "$port_bindings" == "{}" ]] \
  || fail CONTAINER_PORT_PUBLISHED 11

# Todas as escritas a seguir são fixtures sintéticas dentro do PostgreSQL 17
# descartável. O arquivo SQL em avaliação permanece somente leitura.
docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 -U postgres -d postgres <<'SQL'
CREATE DATABASE f2_diag_base;
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d f2_diag_base <<'SQL'
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
  ARRAY['f2_secret_statement_canary_' || i::text],
  'f2_secret_name_canary_' || i::text,
  NULL,
  NULL,
  NULL
FROM pg_catalog.generate_series(1, 6) AS i;
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d postgres <<'SQL'
CREATE DATABASE f2_diag_public_present TEMPLATE f2_diag_base;
CREATE DATABASE f2_diag_cardinality_drift TEMPLATE f2_diag_base;
CREATE DATABASE f2_diag_column_extra TEMPLATE f2_diag_base;
CREATE DATABASE f2_diag_type_changed TEMPLATE f2_diag_base;
CREATE DATABASE f2_diag_notnull_changed TEMPLATE f2_diag_base;
CREATE DATABASE f2_diag_trigger_rule TEMPLATE f2_diag_base;
CREATE DATABASE f2_diag_ceiling TEMPLATE f2_diag_base;
CREATE DATABASE f2_diag_digest_clone TEMPLATE f2_diag_base;
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d f2_diag_public_present <<'SQL'
CREATE TABLE public.schema_migrations (
  name text NOT NULL,
  applied_at timestamp with time zone NOT NULL DEFAULT pg_catalog.now()
);
INSERT INTO public.schema_migrations (name)
VALUES ('f2_secret_public_row_canary');
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d f2_diag_cardinality_drift <<'SQL'
DELETE FROM supabase_migrations.schema_migrations
WHERE version IN ('00000000000005', '00000000000006');
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d f2_diag_column_extra <<'SQL'
ALTER TABLE supabase_migrations.schema_migrations
  ADD COLUMN f2_secret_extra_column_canary text;
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d f2_diag_type_changed <<'SQL'
ALTER TABLE supabase_migrations.schema_migrations
  ALTER COLUMN version TYPE bigint USING version::bigint;
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d f2_diag_notnull_changed <<'SQL'
ALTER TABLE supabase_migrations.schema_migrations
  ALTER COLUMN name SET NOT NULL;
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d f2_diag_trigger_rule <<'SQL'
CREATE FUNCTION public.f2_secret_trigger_function_canary()
RETURNS trigger
LANGUAGE plpgsql
AS $$ BEGIN RETURN NEW; END $$;
CREATE TRIGGER f2_secret_trigger_canary
BEFORE INSERT ON supabase_migrations.schema_migrations
FOR EACH ROW EXECUTE FUNCTION public.f2_secret_trigger_function_canary();
CREATE RULE f2_secret_rule_canary AS
  ON UPDATE TO supabase_migrations.schema_migrations
  DO INSTEAD NOTHING;
SQL

docker exec -i "$container_name" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d f2_diag_ceiling <<'SQL'
ALTER TABLE supabase_migrations.schema_migrations
  ADD COLUMN f2_ceiling_01 text,
  ADD COLUMN f2_ceiling_02 text,
  ADD COLUMN f2_ceiling_03 text,
  ADD COLUMN f2_ceiling_04 text,
  ADD COLUMN f2_ceiling_05 text,
  ADD COLUMN f2_ceiling_06 text,
  ADD COLUMN f2_ceiling_07 text,
  ADD COLUMN f2_ceiling_08 text,
  ADD COLUMN f2_ceiling_09 text,
  ADD COLUMN f2_ceiling_10 text,
  ADD COLUMN f2_ceiling_11 text;
SQL

run_capture() {
  local database_name="$1"
  local binding_value="$2"
  local transport="${3:-socket}"
  local capture_file="/tmp/f2-prod-diag-$RANDOM-$RANDOM.txt"
  local -a host_args=()
  local rc
  if [[ "$transport" == "tcp" ]]; then
    host_args=(-h 127.0.0.1)
  fi
  if printf '\\o %s\n\\i /f2/PROD-READONLY-F2-DIAG-v2.sql\n' "$capture_file" \
    | docker exec -i "$container_name" psql -X -q -A -t -F '|' \
        -v ON_ERROR_STOP=1 \
        -v "f2_prod_diag_binding=$binding_value" \
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
  [[ "$(printf '%s\n' "$output" | grep -Fxc 'ROLLBACK_COMPLETED_F2_PROD_DIAG')" == "1" ]] \
    || fail RECEIPT_COUNT 30
  [[ "$(printf '%s\n' "$output" | tail -n 1)" == 'ROLLBACK_COMPLETED_F2_PROD_DIAG' ]] \
    || fail RECEIPT_NOT_TERMINAL 31
  [[ "$output" != *'F2_ABORT_'* ]] || fail UNEXPECTED_ABORT 32
  printf '%s\n' "$output" | grep -Eq \
    '^F2_SESSION\|PROD_DIAG\|170006\|REPEATABLE_READ\|READ_ONLY_ON\|SEARCH_PATH_PG_CATALOG\|STATEMENT_TIMEOUT_5000MS\|LOCK_TIMEOUT_1000MS\|IDLE_TIMEOUT_15000MS\|ROW_SECURITY_OFF\|BINDING_64HEX_ACCEPTED_NOT_PRINTED$' \
    || fail SESSION_CONTRACT 33
  printf '%s\n' "$output" | grep -Eq '^TARGET_DIGEST\|[0-9a-f]{64}$' \
    || fail TARGET_DIGEST_MISSING 34
}

assert_only_abort() {
  local output="$1"
  local abort_code="$2"
  [[ "$output" == "$abort_code" ]] || fail ABORT_OUTPUT_CONTRACT 35
  [[ "$output" != *'ROLLBACK_COMPLETED_F2_PROD_DIAG'* ]] \
    || fail ABORT_RECEIPT_FORBIDDEN 36
}

base_output="$(run_capture f2_diag_base "$binding_primary")" \
  || fail BASE_EXECUTION 40
public_present_output="$(run_capture f2_diag_public_present "$binding_primary")" \
  || fail PUBLIC_PRESENT_EXECUTION 41
cardinality_output="$(run_capture f2_diag_cardinality_drift "$binding_primary")" \
  || fail CARDINALITY_EXECUTION 42
column_extra_output="$(run_capture f2_diag_column_extra "$binding_primary")" \
  || fail COLUMN_EXTRA_EXECUTION 43
type_changed_output="$(run_capture f2_diag_type_changed "$binding_primary")" \
  || fail TYPE_CHANGED_EXECUTION 44
notnull_changed_output="$(run_capture f2_diag_notnull_changed "$binding_primary")" \
  || fail NOTNULL_CHANGED_EXECUTION 45
trigger_rule_output="$(run_capture f2_diag_trigger_rule "$binding_primary")" \
  || fail TRIGGER_RULE_EXECUTION 46

for output in \
  "$base_output" \
  "$public_present_output" \
  "$cardinality_output" \
  "$column_extra_output" \
  "$type_changed_output" \
  "$notnull_changed_output" \
  "$trigger_rule_output"; do
  assert_success "$output"
done

printf '%s\n' "$base_output" | grep -Eq \
  '^LEDGER_RELATION\|PUBLIC_LEDGER\|ABSENT\|ABSENT\|ABSENT\|NOT_APPLICABLE\|NOT_APPLICABLE\|0\|0$' \
  || fail PUBLIC_ABSENT_NOT_REPORTED 50
printf '%s\n' "$public_present_output" | grep -Eq \
  '^LEDGER_RELATION\|PUBLIC_LEDGER\|PRESENT\|r\|p\|' \
  || fail PUBLIC_PRESENT_NOT_REPORTED 51
printf '%s\n' "$base_output" | grep -Fqx \
  'LEDGER_CARDINALITY|NATIVE_LEDGER|TABLE_OR_PARTITIONED|6' \
  || fail BASE_CARDINALITY_NOT_REPORTED 52
printf '%s\n' "$cardinality_output" | grep -Fqx \
  'LEDGER_CARDINALITY|NATIVE_LEDGER|TABLE_OR_PARTITIONED|4' \
  || fail CARDINALITY_DRIFT_NOT_REPORTED 53
printf '%s\n' "$column_extra_output" | grep -Eq \
  '^LEDGER_COLUMN\|NATIVE_LEDGER\|7\|OPAQUE_COLUMN_[0-9a-f]{32}\|text\|' \
  || fail EXTRA_COLUMN_NOT_OPAQUE 54
printf '%s\n' "$type_changed_output" | grep -Fq \
  'LEDGER_COLUMN|NATIVE_LEDGER|1|version|bigint|t|' \
  || fail TYPE_DRIFT_NOT_REPORTED 55
printf '%s\n' "$notnull_changed_output" | grep -Fq \
  'LEDGER_COLUMN|NATIVE_LEDGER|3|name|text|t|' \
  || fail NOTNULL_DRIFT_NOT_REPORTED 56
printf '%s\n' "$trigger_rule_output" | grep -Eq \
  '^LEDGER_TRIGGER\|NATIVE_LEDGER\|OPAQUE_TRIGGER_[0-9a-f]{32}\|O\|[0-9a-f]{32}$' \
  || fail TRIGGER_NOT_OPAQUE 57
printf '%s\n' "$trigger_rule_output" | grep -Eq \
  '^LEDGER_RULE\|NATIVE_LEDGER\|OPAQUE_RULE_[0-9a-f]{32}\|[0-9a-f]{32}$' \
  || fail RULE_NOT_OPAQUE 58

combined_output="$(printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n' \
  "$base_output" \
  "$public_present_output" \
  "$cardinality_output" \
  "$column_extra_output" \
  "$type_changed_output" \
  "$notnull_changed_output" \
  "$trigger_rule_output")"
for forbidden in \
  f2_secret_statement_canary \
  f2_secret_name_canary \
  f2_secret_public_row_canary \
  f2_secret_extra_column_canary \
  f2_secret_trigger_canary \
  f2_secret_rule_canary \
  f2_secret_trigger_function_canary \
  "$binding_primary" \
  f2_diag_base \
  f2_diag_public_present; do
  [[ "$combined_output" != *"$forbidden"* ]] || fail PRIVACY_LEAK 59
done

repeat_output="$(run_capture f2_diag_base "$binding_primary")" \
  || fail DIGEST_REPEAT_EXECUTION 60
alternate_binding_output="$(run_capture f2_diag_base "$binding_alternate")" \
  || fail DIGEST_BINDING_EXECUTION 61
clone_output="$(run_capture f2_diag_digest_clone "$binding_primary")" \
  || fail DIGEST_DATABASE_EXECUTION 62
tcp_output="$(run_capture f2_diag_base "$binding_primary" tcp)" \
  || fail DIGEST_TCP_EXECUTION 63
for output in "$repeat_output" "$alternate_binding_output" "$clone_output" "$tcp_output"; do
  assert_success "$output"
done

base_digest="$(printf '%s\n' "$base_output" | extract_digest)"
repeat_digest="$(printf '%s\n' "$repeat_output" | extract_digest)"
alternate_binding_digest="$(printf '%s\n' "$alternate_binding_output" | extract_digest)"
clone_digest="$(printf '%s\n' "$clone_output" | extract_digest)"
tcp_digest="$(printf '%s\n' "$tcp_output" | extract_digest)"
[[ -n "$base_digest" && "$base_digest" == "$repeat_digest" ]] \
  || fail DIGEST_NOT_STABLE 64
[[ "$base_digest" != "$alternate_binding_digest" ]] \
  || fail DIGEST_NOT_BINDING_SENSITIVE 65
[[ "$base_digest" != "$clone_digest" ]] \
  || fail DIGEST_NOT_DATABASE_SENSITIVE 66
[[ "$base_digest" != "$tcp_digest" ]] \
  || fail DIGEST_NOT_SOCKET_TCP_SENSITIVE 67

server_version_num="$(docker exec "$container_name" psql -X -q -A -t \
  -U postgres -d f2_diag_base -c "SELECT pg_catalog.current_setting('server_version_num');")"
expected_socket_digest="$(printf '%s\x1f%s\x1f%s\x1f%s' \
  "$binding_primary" f2_diag_base UNIX_SOCKET "$server_version_num" \
  | sha256sum | awk '{print $1}')"
[[ "$base_digest" == "$expected_socket_digest" ]] || fail DIGEST_FORMULA_MISMATCH 68
changed_version_digest="$(printf '%s\x1f%s\x1f%s\x1f%s' \
  "$binding_primary" f2_diag_base UNIX_SOCKET 170007 \
  | sha256sum | awk '{print $1}')"
[[ "$base_digest" != "$changed_version_digest" ]] || fail DIGEST_NOT_VERSION_SENSITIVE 69

set +e
invalid_binding_output="$(run_capture f2_diag_base invalid)"
invalid_binding_rc=$?
ceiling_output="$(run_capture f2_diag_ceiling "$binding_primary")"
ceiling_rc=$?
set -e
[[ "$invalid_binding_rc" -eq 0 ]] || fail INVALID_BINDING_EXECUTION 70
[[ "$ceiling_rc" -eq 0 ]] || fail CEILING_EXECUTION 71
assert_only_abort "$invalid_binding_output" F2_ABORT_BINDING_INVALID
assert_only_abort "$ceiling_output" F2_ABORT_OBSERVATION_CEILING

printf '%s\n' 'RESULT=PASS_PG17_F2_PROD_DIAG_V2'
