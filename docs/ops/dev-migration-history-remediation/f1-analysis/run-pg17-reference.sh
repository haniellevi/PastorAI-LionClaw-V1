#!/usr/bin/env bash
set -euo pipefail

# Reproduz apenas a referência local F1. Não abre sessão compartilhada, não
# publica porta e não preserva banco, container ou saída catalográfica bruta.

analysis_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(git -C "$analysis_dir" rev-parse --show-toplevel)"
frozen_sql="$repo_root/docs/ops/dev-migration-history-remediation/DEV-READONLY-F1.sql"
indexer="$analysis_dir/catalog-safe-index.py"
tracer="$analysis_dir/capture-reference-deltas.py"
output_dir="${1:?uso: run-pg17-reference.sh /tmp/f1-reference-XXXXXX}"
evidence_path="${2:?uso: run-pg17-reference.sh /tmp/f1-reference-XXXXXX /caminho/evidencia}"
container_name="igreja12-f1-reference-pg17"
postgres_image="postgres:17.6-trixie"
runtime_image="pastorai-agent-local-validation-v1-backend:3799272"
frozen_sql_sha256="8829decd0f0101329058ad07900ce7b7ca8b1c4fe5695f4e3cec05cff4bf288c"
evidence_sha256="b1c3e1bda63b55e7c5496d318bcf039d9a4d130de60ced535d918be233313e1b"
postgres_image_id="sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929"
local_password="f1_local_disposable_only"

fail() {
  printf '%s\n' "RESULT=FAIL_REFERENCE_${1}"
  exit "${2:-1}"
}

case "$output_dir" in
  /tmp/f1-reference-*) ;;
  *) fail OUTPUT_PATH_CONTRACT 2 ;;
esac

if [[ ! -d "$output_dir" ]] || [[ -n "$(find "$output_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  fail OUTPUT_DIRECTORY_CONTRACT 3
fi
if [[ ! -f "$evidence_path" ]]; then
  fail EVIDENCE_PATH_CONTRACT 4
fi
if ! evidence_mode="$(stat -c '%a' -- "$evidence_path" 2>/dev/null)" || [[ "$evidence_mode" != 600 ]]; then
  fail EVIDENCE_MODE 4
fi
if [[ "$(sha256sum -- "$evidence_path" | awk '{print $1}')" != "$evidence_sha256" ]]; then
  fail EVIDENCE_SHA256 4
fi
if [[ ! -f "$frozen_sql" ]] || [[ ! -f "$indexer" ]] || [[ ! -f "$tracer" ]]; then
  fail INPUT_CONTRACT 4
fi
if [[ "$(sha256sum "$frozen_sql" | awk '{print $1}')" != "$frozen_sql_sha256" ]]; then
  fail FROZEN_SQL_SHA256 5
fi
if docker container inspect "$container_name" >/dev/null 2>&1; then
  fail EXISTING_DISPOSABLE_CONTAINER 6
fi
if [[ "$(docker image inspect --format '{{.Id}}' "$postgres_image" 2>/dev/null)" != "$postgres_image_id" ]]; then
  fail PG17_6_IMAGE_CONTRACT 7
fi
if ! docker image inspect "$runtime_image" >/dev/null 2>&1; then
  fail LOCAL_RUNTIME_IMAGE_UNAVAILABLE 8
fi

cleanup() {
  docker stop "$container_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

start_disposable() {
  if docker container inspect "$container_name" >/dev/null 2>&1; then
    fail DISPOSABLE_RESTART_CONTRACT 9
  fi
  if ! docker run --pull=never --rm --network none --name "$container_name" \
    --mount "type=bind,src=$repo_root,dst=/repo,readonly" \
    -e POSTGRES_HOST_AUTH_METHOD=trust \
    -e POSTGRES_DB=migration_catalog_current_head_disposable \
    -d "$postgres_image" >/dev/null 2>&1; then
    fail PG17_CONTAINER_START 9
  fi
  local ready=false
  for _attempt in $(seq 1 60); do
    if docker exec "$container_name" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
      ready=true
      break
    fi
    sleep 1
  done
  [[ "$ready" == true ]] || fail PG17_NOT_READY 10
}

# O traço roda primeiro em cluster sem roles persistentes. O harness oficial
# roda depois em novo cluster, porque papéis PostgreSQL são globais ao cluster.
start_disposable

if ! trace_output="$(docker run --pull=never --rm --network "container:$container_name" \
  --mount "type=bind,src=$repo_root,dst=/repo,readonly" \
  --mount "type=bind,src=$output_dir,dst=/out" \
  --user "$(id -u):$(id -g)" \
  --workdir /repo \
  --entrypoint python3 \
  "$runtime_image" \
  -I -P docs/ops/dev-migration-history-remediation/f1-analysis/capture-reference-deltas.py \
  --output /out/reference-trace.json 2>&1)"; then
  if [[ "$trace_output" == *'FAIL=TRACE_INCOMPLETE'* ]]; then
    fail TRACE_INCOMPLETE 13
  elif [[ "$trace_output" == *'FAIL=CATALOG_COUNT_NOT_77'* ]]; then
    fail TRACE_CATALOG_COUNT 13
  elif [[ "$trace_output" == *'FAIL=DUPLICATE_MIGRATION_SQL'* ]]; then
    fail TRACE_SOURCE_DUPLICATE 13
  elif [[ "$trace_output" =~ FAIL=TRACE_INTERNAL_([A-Z_]+) ]]; then
    fail "TRACE_INTERNAL_${BASH_REMATCH[1]}" 13
  elif [[ "$trace_output" == *'Traceback'* ]]; then
    fail TRACE_INTERNAL_SANITIZED 13
  else
    fail TRACE_REPLAY_SANITIZED 13
  fi
fi
for required in \
  'RESULT=PASS_F1_REFERENCE_STRUCTURAL_TRACE' \
  'CATALOG_MIGRATION_COUNT=77' \
  'POSTGRESQL_MAJOR=17'; do
  [[ "$trace_output" == *"$required"* ]] || fail TRACE_RECEIPT 14
done

python3 -I -B "$indexer" \
  --source DEV \
  --input "$evidence_path" \
  --output "$output_dir/dev-catalog-safe-index.json" >/dev/null

{
  cat <<'PSQL'
\set ON_ERROR_STOP on
\pset pager off
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '15000ms';
SET LOCAL lock_timeout = '2000ms';
SET LOCAL idle_in_transaction_session_timeout = '30000ms';
SET LOCAL row_security = off;
SELECT CASE
  WHEN pg_catalog.to_regclass('public.schema_migrations') IS NULL
   AND pg_catalog.to_regnamespace('supabase_migrations') IS NULL
  THEN true
  ELSE false
END AS f1_reference_ledgers_absent
\gset
\if :f1_reference_ledgers_absent
\echo REFERENCE_CATALOG_ADAPTER
\else
\echo REFERENCE_ABORT_LEDGER_CONTRACT
ROLLBACK;
\quit 4
\endif
PSQL
  sed -n '306,988p' "$frozen_sql"
  cat <<'PSQL'
ROLLBACK;
\echo REFERENCE_CATALOG_ROLLBACK_COMPLETED
PSQL
} | docker exec -i "$container_name" psql \
  -q -A -t -F '|' -v ON_ERROR_STOP=1 -U postgres -d migration_catalog_current_head_disposable \
  | python3 -I -B "$indexer" \
    --source REFERENCE \
    --input - \
    --output "$output_dir/reference-catalog-safe-index.json" >/dev/null

if [[ ! -s "$output_dir/dev-catalog-safe-index.json" ]] \
  || [[ ! -s "$output_dir/reference-catalog-safe-index.json" ]] \
  || [[ ! -s "$output_dir/reference-trace.json" ]]; then
  fail SAFE_ARTIFACT_CONTRACT 15
fi

# Isola o replay oficial do cluster que recebeu o traço. Isto evita que roles
# globais criadas por migrations alterem o contrato fresh do segundo replay.
docker stop "$container_name" >/dev/null 2>&1 || fail TRACE_CONTAINER_STOP 16
for _attempt in $(seq 1 30); do
  if ! docker container inspect "$container_name" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if docker container inspect "$container_name" >/dev/null 2>&1; then
  fail TRACE_CONTAINER_REMOVAL 17
fi
start_disposable

if ! harness_output="$(docker run --pull=never --rm --network "container:$container_name" \
  --mount "type=bind,src=$repo_root,dst=/repo,readonly" \
  --workdir /repo/backend \
  -e "MIGRATION_CATALOG_REPLAY_DATABASE_URL=postgresql://postgres:${local_password}@127.0.0.1:5432/migration_catalog_current_head_disposable" \
  --entrypoint python3 \
  "$runtime_image" \
  -I -P scripts/replay_migration_catalog_current_head_pg17.py \
  --confirmation REPLAY_MIGRATION_CATALOG_CURRENT_HEAD_PG17_DISPOSABLE 2>&1)"; then
  if [[ "$harness_output" == *'MIGRATION_CATALOG_CURRENT_HEAD_REPLAY_BLOCKED:SOURCE_CONTRACT'* ]]; then
    fail HARNESS_SOURCE_CONTRACT 18
  elif [[ "$harness_output" == *'MIGRATION_CATALOG_CURRENT_HEAD_REPLAY_BLOCKED:TARGET_GUARD'* ]]; then
    fail HARNESS_TARGET_GUARD 18
  elif [[ "$harness_output" == *'MIGRATION_CATALOG_CURRENT_HEAD_REPLAY_BLOCKED:MIGRATION_REPLAY'* ]]; then
    fail HARNESS_MIGRATION_REPLAY 18
  elif [[ "$harness_output" == *'MIGRATION_CATALOG_CURRENT_HEAD_REPLAY_BLOCKED:DATABASE_CONTRACT'* ]]; then
    fail HARNESS_DATABASE_CONTRACT 18
  else
    fail HARNESS_REPLAY_SANITIZED 18
  fi
fi
for required in \
  'OPERATIONAL_AUTHORIZATION=BLOCKED' \
  'NEXT_STAGE_AUTHORIZED=false' \
  'SHARED_ENVIRONMENT_ATTESTATION=false' \
  'RESULT=MIGRATION_CATALOG_CURRENT_HEAD_REPLAYED_PG17_DISPOSABLE' \
  'CATALOG_MIGRATION_COUNT=77' \
  'POSTGRESQL_MAJOR=17'; do
  [[ "$harness_output" == *"$required"* ]] || fail HARNESS_RECEIPT 19
done

printf '%s\n' 'RESULT=PASS_F1_REFERENCE_REPLAY_AND_SAFE_COLLECTION'
printf '%s\n' 'CATALOG_MIGRATION_COUNT=77'
printf '%s\n' 'POSTGRESQL_MAJOR=17'
printf '%s\n' 'TRACE_DATABASE_RECREATED_VIA_POSTGRES=true'
printf '%s\n' 'TRACE_FRESH_CONTRACT=PASS'
printf '%s\n' 'OFFICIAL_HARNESS_REPLAY=PASS'
printf '%s\n' "FROZEN_SQL_SHA256=$frozen_sql_sha256"
printf '%s\n' "DEV_INDEX_SHA256=$(sha256sum "$output_dir/dev-catalog-safe-index.json" | awk '{print $1}')"
printf '%s\n' "REFERENCE_INDEX_SHA256=$(sha256sum "$output_dir/reference-catalog-safe-index.json" | awk '{print $1}')"
printf '%s\n' "TRACE_SHA256=$(sha256sum "$output_dir/reference-trace.json" | awk '{print $1}')"
printf '%s\n' 'NETWORK=NONE_WITH_SHARED_LOOPBACK_NAMESPACE'
printf '%s\n' 'PUBLISHED_PORTS=NONE'
