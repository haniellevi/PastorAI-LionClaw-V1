#!/usr/bin/env bash
set -euo pipefail

candidate_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
container_name="igreja12-f1-pg17-e2e"
image_ref="postgres:17.6-trixie"
binding_hash="9f50e751d2f808b9a16ec9a7dc8714c3d389ff0a42c8b8e5b3396c841d5c03fa"
alternate_binding_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
clone_database="f1_digest_clone"

fail() {
  local result_code="$1"
  local exit_code="$2"
  printf '%s\n' "RESULT=FAIL_${result_code}"
  exit "$exit_code"
}

require_text() {
  local required_text="$1"
  local result_code="$2"
  local exit_code="$3"

  if [[ "$readonly_output" != *"$required_text"* ]]; then
    fail "$result_code" "$exit_code"
  fi
}

require_regex() {
  local required_pattern="$1"
  local result_code="$2"
  local exit_code="$3"

  if ! printf '%s\n' "$readonly_output" | grep -Eq "$required_pattern"; then
    fail "$result_code" "$exit_code"
  fi
}

forbid_text() {
  local prohibited_text="$1"
  local result_code="$2"
  local exit_code="$3"

  if [[ "$readonly_output" == *"$prohibited_text"* ]]; then
    fail "$result_code" "$exit_code"
  fi
}

run_readonly_sql() {
  local database_name="$1"
  local binding_value="$2"

  docker exec -i "$container_name" psql \
    -q -A -t -F '|' \
    -v ON_ERROR_STOP=1 \
    -v "f1_target_binding_sha256=$binding_value" \
    -U postgres -d "$database_name" \
    -f /f1/DEV-READONLY-F1.sql
}

extract_target_digest() {
  local candidate_output="$1"

  printf '%s\n' "$candidate_output" | awk -F'|' '
    $1 == "TARGET_DIGEST" {
      count += 1
      digest = $2
    }
    END {
      if (count == 1 && digest ~ /^[0-9a-f]{64}$/) {
        print digest
      }
    }
  '
}

if docker container inspect "$container_name" >/dev/null 2>&1; then
  printf '%s\n' "RESULT=BLOCKED_EXISTING_DISPOSABLE_CONTAINER"
  exit 3
fi

if ! docker image inspect "$image_ref" >/dev/null 2>&1; then
  printf '%s\n' "RESULT=BLOCKED_PG17_6_IMAGE_UNAVAILABLE"
  exit 4
fi

cleanup() {
  docker stop "$container_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! docker run --pull=never --rm --network none --name "$container_name" \
  --mount "type=bind,src=$candidate_dir,dst=/f1,readonly" \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  -d "$image_ref" >/dev/null 2>&1; then
  printf '%s\n' "RESULT=BLOCKED_PG17_6_CONTAINER_START"
  exit 5
fi

for _attempt in $(seq 1 60); do
  if docker exec "$container_name" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! docker exec "$container_name" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
  printf '%s\n' "RESULT=BLOCKED_PG17_NOT_READY"
  exit 6
fi

if ! readonly_output="$(docker exec -i "$container_name" psql \
  -q -A -t -F '|' \
  -v ON_ERROR_STOP=1 \
  -v "f1_target_binding_sha256=$binding_hash" \
  -U postgres -d postgres \
  -f /f1/PG17-E2E.sql 2>&1)"; then
  if [[ "$readonly_output" == *"syntax error"* ]]; then
    printf '%s\n' "RESULT=FAIL_PG17_EXECUTION_SYNTAX"
  elif [[ "$readonly_output" == *"invalid escape"* ]]; then
    printf '%s\n' "RESULT=FAIL_PG17_EXECUTION_ESCAPE"
  elif [[ "$readonly_output" == *"does not exist"* ]]; then
    printf '%s\n' "RESULT=FAIL_PG17_EXECUTION_UNDEFINED_CATALOG_OBJECT"
  elif [[ "$readonly_output" == *"operator does not exist"* ]] \
    || [[ "$readonly_output" == *"cannot be matched"* ]]; then
    printf '%s\n' "RESULT=FAIL_PG17_EXECUTION_TYPE"
  else
    printf '%s\n' "RESULT=FAIL_PG17_EXECUTION_OTHER"
  fi
  exit 7
fi

if ! socket_transport_state="$(docker exec -i "$container_name" psql \
  -q -A -t \
  -v ON_ERROR_STOP=1 \
  -U postgres -d postgres \
  -c "SELECT CASE WHEN pg_catalog.inet_server_port() IS NULL THEN 'UNIX_SOCKET' ELSE 'NETWORK_TRANSPORT' END;" 2>&1)"; then
  printf '%s\n' "RESULT=FAIL_PG17_SOCKET_TRANSPORT_CHECK"
  exit 8
fi
if [[ "$socket_transport_state" != "UNIX_SOCKET" ]]; then
  fail "UNIX_SOCKET_NOT_VERIFIED" 9
fi

if ! custom_grantee_oid="$(docker exec -i "$container_name" psql \
  -q -A -t \
  -v ON_ERROR_STOP=1 \
  -U postgres -d postgres \
  -c "SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'f1_e2e_custom_grantee';" 2>&1)"; then
  printf '%s\n' "RESULT=FAIL_PG17_CUSTOM_GRANTEE_OID_LOOKUP"
  exit 10
fi
if [[ ! "$custom_grantee_oid" =~ ^[0-9]+$ ]]; then
  fail "CUSTOM_GRANTEE_OID_INVALID" 11
fi
if ! printf '%s\n' "$readonly_output" | awk -F'|' -v forbidden="$custom_grantee_oid" '
  {
    for (field = 1; field <= NF; field += 1) {
      if ($field == forbidden) {
        found = 1
      }
    }
  }
  END { exit(found ? 1 : 0) }
'; then
  fail "CUSTOM_GRANTEE_OID_LEAKED" 12
fi

if ! repeated_same_output="$(run_readonly_sql postgres "$binding_hash" 2>&1)"; then
  printf '%s\n' "RESULT=FAIL_PG17_REPEAT_SAME_TARGET_DIGEST"
  exit 13
fi

if ! alternate_binding_output="$(run_readonly_sql postgres "$alternate_binding_hash" 2>&1)"; then
  printf '%s\n' "RESULT=FAIL_PG17_ALTERNATE_BINDING_TARGET_DIGEST"
  exit 14
fi

if ! docker exec -i "$container_name" psql \
  -q -A -t \
  -v ON_ERROR_STOP=1 \
  -U postgres -d template1 \
  -c "CREATE DATABASE $clone_database TEMPLATE postgres;" >/dev/null 2>&1; then
  printf '%s\n' "RESULT=FAIL_PG17_DIGEST_CLONE_CREATE"
  exit 15
fi

if ! clone_database_output="$(run_readonly_sql "$clone_database" "$binding_hash" 2>&1)"; then
  printf '%s\n' "RESULT=FAIL_PG17_CLONED_DATABASE_TARGET_DIGEST"
  exit 16
fi

primary_target_digest="$(extract_target_digest "$readonly_output")"
repeated_target_digest="$(extract_target_digest "$repeated_same_output")"
alternate_target_digest="$(extract_target_digest "$alternate_binding_output")"
clone_target_digest="$(extract_target_digest "$clone_database_output")"
for target_digest in \
  "$primary_target_digest" \
  "$repeated_target_digest" \
  "$alternate_target_digest" \
  "$clone_target_digest"; do
  if [[ ! "$target_digest" =~ ^[0-9a-f]{64}$ ]]; then
    fail "TARGET_DIGEST_MISSING_OR_INVALID" 14
  fi
done

for candidate_output in \
  "$repeated_same_output" \
  "$alternate_binding_output" \
  "$clone_database_output"; do
  if [[ "$candidate_output" != *"ROLLBACK_COMPLETED_F1"* ]] \
    || [[ "$candidate_output" == *"F1_ABORT_"* ]]; then
    fail "TARGET_DIGEST_READONLY_ROLLBACK_REGRESSION" 15
  fi
done

if [[ "$primary_target_digest" != "$repeated_target_digest" ]]; then
  fail "TARGET_DIGEST_NOT_STABLE_SAME_BINDING_AND_DATABASE" 16
fi
if [[ "$primary_target_digest" == "$alternate_target_digest" ]]; then
  fail "TARGET_DIGEST_NOT_BINDING_SENSITIVE" 17
fi
if [[ "$primary_target_digest" == "$clone_target_digest" ]]; then
  fail "TARGET_DIGEST_NOT_DATABASE_SENSITIVE" 18
fi

all_target_output="$readonly_output"$'\n'"$repeated_same_output"$'\n'"$alternate_binding_output"$'\n'"$clone_database_output"
if [[ "$all_target_output" == *"$binding_hash"* ]] \
  || [[ "$all_target_output" == *"$alternate_binding_hash"* ]] \
  || [[ "$clone_database_output" == *"$clone_database"* ]]; then
  fail "TARGET_DIGEST_INPUT_LEAKED" 19
fi

require_regex '^F1_SESSION\|[^|]*\|[^|]*\|on\|off\|' \
  "ROW_SECURITY_OFF_NOT_VERIFIED" 20
require_text "PUBLIC_LEDGER_COUNT_EXPECTATION|EXPECTED_33" \
  "PUBLIC_LEDGER_33_NOT_VERIFIED" 9
require_text "NATIVE_LEDGER_COUNT_EXPECTATION|EXPECTED_6" \
  "NATIVE_LEDGER_6_NOT_VERIFIED" 10
require_regex '^NATIVE_LEDGER_STATEMENT_FINGERPRINT\|0\|[0-9a-f]{32}\|NON_SENSITIVE_DDL_PATTERN_PRESENT$' \
  "LEADING_COMMENT_DDL_PATTERN_NOT_VERIFIED" 11
require_text "ROLLBACK_COMPLETED_F1" "ROLLBACK_RECEIPT_MISSING" 12
forbid_text "F1_ABORT_" "UNEXPECTED_LEDGER_ABORT" 13

require_text \
  "SCHEMA_ACL_DIRECT_GRANTEE|PUBLIC_SCHEMA|UNEXPECTED_CUSTOM_GRANTEE|UNEXPECTED_CUSTOM_GRANTEE|USAGE|" \
  "PUBLIC_SCHEMA_ACL_CUSTOM_GRANTEE_NOT_DETECTED" 14
require_text \
  "SCHEMA_ACL_DIRECT_GRANTEE|AGENT_PRIVATE_SCHEMA|UNEXPECTED_CUSTOM_GRANTEE|UNEXPECTED_CUSTOM_GRANTEE|USAGE|" \
  "AGENT_PRIVATE_SCHEMA_ACL_CUSTOM_GRANTEE_NOT_DETECTED" 15
require_text \
  "SCHEMA_ACL_DIRECT_GRANTEE|RECOVERY_SCHEMA_OPAQUE|UNEXPECTED_CUSTOM_GRANTEE|UNEXPECTED_CUSTOM_GRANTEE|USAGE|" \
  "RECOVERY_SCHEMA_ACL_CUSTOM_GRANTEE_NOT_DETECTED" 16
require_text \
  "SCHEMA_ACL_DIRECT_GRANTEE|AGENT_PRIVATE_SCHEMA|ALLOWLIST_ROLE|anon|USAGE|" \
  "AGENT_PRIVATE_ANON_GRANTEE_REF_NOT_EMITTED" 20
require_text \
  "SCHEMA_ACL_DIRECT_GRANTEE|RECOVERY_SCHEMA_OPAQUE|PUBLIC|PUBLIC|USAGE|" \
  "PUBLIC_GRANTEE_REF_NOT_EMITTED" 21
require_text \
  "SCHEMA_ACL_DIRECT_GRANTEE|PUBLIC_SCHEMA|PLATFORM_ROLE|authenticator|USAGE|" \
  "PLATFORM_GRANTEE_REF_NOT_EMITTED" 22

require_text \
  "RELACL_DIRECT_GRANTEE|PUBLIC_SCHEMA|f1_public_acl_fixture|r|UNEXPECTED_CUSTOM_GRANTEE|UNEXPECTED_CUSTOM_GRANTEE|SELECT|" \
  "PUBLIC_RELACL_CUSTOM_GRANTEE_NOT_DETECTED" 17
require_text \
  "RELACL_DIRECT_GRANTEE|AGENT_PRIVATE_SCHEMA|f1_agent_private_acl_fixture|r|UNEXPECTED_CUSTOM_GRANTEE|UNEXPECTED_CUSTOM_GRANTEE|SELECT|" \
  "AGENT_PRIVATE_RELACL_CUSTOM_GRANTEE_NOT_DETECTED" 18
require_regex \
  '^RELACL_DIRECT_GRANTEE\|RECOVERY_SCHEMA_OPAQUE\|OPAQUE_RELATION_[0-9a-f]{32}\|r\|UNEXPECTED_CUSTOM_GRANTEE\|UNEXPECTED_CUSTOM_GRANTEE\|SELECT\|' \
  "RECOVERY_RELACL_CUSTOM_GRANTEE_NOT_DETECTED" 19

require_text \
  "PROACL_DIRECT_GRANTEE|PUBLIC_SCHEMA|f1_public_acl_function|f|UNEXPECTED_CUSTOM_GRANTEE|UNEXPECTED_CUSTOM_GRANTEE|EXECUTE|" \
  "PUBLIC_PROACL_CUSTOM_GRANTEE_NOT_DETECTED" 20
require_text \
  "PROACL_DIRECT_GRANTEE|AGENT_PRIVATE_SCHEMA|f1_agent_private_acl_function|f|UNEXPECTED_CUSTOM_GRANTEE|UNEXPECTED_CUSTOM_GRANTEE|EXECUTE|" \
  "AGENT_PRIVATE_PROACL_CUSTOM_GRANTEE_NOT_DETECTED" 21
require_regex \
  '^PROACL_DIRECT_GRANTEE\|RECOVERY_SCHEMA_OPAQUE\|OPAQUE_FUNCTION_[0-9a-f]{32}\|f\|UNEXPECTED_CUSTOM_GRANTEE\|UNEXPECTED_CUSTOM_GRANTEE\|EXECUTE\|' \
  "RECOVERY_PROACL_CUSTOM_GRANTEE_NOT_DETECTED" 22

require_text \
  "DEFAULT_ACL_DIRECT_GRANTEE|PUBLIC_SCHEMA|r|UNEXPECTED_CUSTOM_GRANTEE|UNEXPECTED_CUSTOM_GRANTEE|SELECT|" \
  "PUBLIC_DEFAULT_ACL_CUSTOM_GRANTEE_NOT_DETECTED" 23
require_text \
  "DEFAULT_ACL_DIRECT_GRANTEE|AGENT_PRIVATE_SCHEMA|r|UNEXPECTED_CUSTOM_GRANTEE|UNEXPECTED_CUSTOM_GRANTEE|SELECT|" \
  "AGENT_PRIVATE_DEFAULT_ACL_CUSTOM_GRANTEE_NOT_DETECTED" 24
require_text \
  "DEFAULT_ACL_DIRECT_GRANTEE|RECOVERY_SCHEMA_OPAQUE|r|UNEXPECTED_CUSTOM_GRANTEE|UNEXPECTED_CUSTOM_GRANTEE|SELECT|" \
  "RECOVERY_DEFAULT_ACL_CUSTOM_GRANTEE_NOT_DETECTED" 25
require_text \
  "DEFAULT_ACL_DIRECT_GRANTEE|GLOBAL_NAMESPACE|r|UNEXPECTED_CUSTOM_GRANTEE|UNEXPECTED_CUSTOM_GRANTEE|SELECT|" \
  "GLOBAL_DEFAULT_ACL_CUSTOM_GRANTEE_NOT_DETECTED" 26

require_regex \
  '^UNEXPECTED_CUSTOM_GRANTEE_SUMMARY\|PUBLIC_SCHEMA\|[1-9][0-9]*\|UNEXPECTED_CUSTOM_GRANTEE$' \
  "PUBLIC_SUMMARY_CUSTOM_GRANTEE_NOT_DETECTED" 27
require_regex \
  '^UNEXPECTED_CUSTOM_GRANTEE_SUMMARY\|AGENT_PRIVATE_SCHEMA\|[1-9][0-9]*\|UNEXPECTED_CUSTOM_GRANTEE$' \
  "AGENT_PRIVATE_SUMMARY_CUSTOM_GRANTEE_NOT_DETECTED" 28
require_regex \
  '^UNEXPECTED_CUSTOM_GRANTEE_SUMMARY\|RECOVERY_SCHEMA_OPAQUE\|[1-9][0-9]*\|UNEXPECTED_CUSTOM_GRANTEE$' \
  "RECOVERY_SUMMARY_CUSTOM_GRANTEE_NOT_DETECTED" 29
require_regex \
  '^UNEXPECTED_CUSTOM_GRANTEE_SUMMARY\|GLOBAL_NAMESPACE\|[1-9][0-9]*\|UNEXPECTED_CUSTOM_GRANTEE$' \
  "GLOBAL_SUMMARY_CUSTOM_GRANTEE_NOT_DETECTED" 30

platform_role_count="$(
  (printf '%s\n' "$readonly_output" | grep -o 'PLATFORM_ROLE' | wc -l | tr -d '[:space:]') || true
)"
if [[ ! "$platform_role_count" =~ ^[0-9]+$ ]] || (( platform_role_count < 5 )); then
  fail "PLATFORM_ROLE_ALLOWLIST_NOT_VERIFIED" 31
fi

require_regex \
  '^CATALOG_CONSTRAINT\|RECOVERY_SCHEMA_OPAQUE\|OPAQUE_RELATION_[0-9a-f]{32}\|OPAQUE_CONSTRAINT_[0-9a-f]{32}\|' \
  "MASKED_CONSTRAINT_NOT_VERIFIED" 32
require_regex \
  '^CATALOG_INDEX\|RECOVERY_SCHEMA_OPAQUE\|OPAQUE_RELATION_[0-9a-f]{32}\|OPAQUE_INDEX_[0-9a-f]{32}\|' \
  "MASKED_INDEX_NOT_VERIFIED" 33
require_regex \
  '^CATALOG_RLS_POLICY\|RECOVERY_SCHEMA_OPAQUE\|OPAQUE_RELATION_[0-9a-f]{32}\|t\|f\|OPAQUE_POLICY_[0-9a-f]{32}\|' \
  "MASKED_POLICY_NOT_VERIFIED" 34
require_regex \
  '^CATALOG_TRIGGER\|RECOVERY_SCHEMA_OPAQUE\|OPAQUE_RELATION_[0-9a-f]{32}\|OPAQUE_TRIGGER_[0-9a-f]{32}\|' \
  "MASKED_TRIGGER_NOT_VERIFIED" 35

for prohibited_text in \
  "f1_e2e_custom_grantee" \
  "f1_e2e_default_owner" \
  "f1_statement_comment_not_output" \
  "f1_initial_comment" \
  "f1_masked_recovery_relation" \
  "f1_masked_recovery_constraint" \
  "f1_masked_recovery_index" \
  "f1_masked_recovery_policy" \
  "f1_masked_recovery_trigger" \
  "f1_masked_recovery_trigger_function"; do
  forbid_text "$prohibited_text" "SANITIZATION_REGRESSION" 36
done

printf '%s\n' "RESULT=PASS_PG17_E2E_F1_B1_B2_AND_REGRESSION"
