#!/usr/bin/env bash
# Run on the VPS only after a separately authorized database release.
set -Eeuo pipefail
BACKEND_RELEASE_SAFETY_VERSION=2

configuration=.env
if [[ "${BACKEND_RELEASE_TEST_MODE:-}" == 1 ]]; then
  configuration=${BACKEND_RELEASE_TEST_CONFIG:?}
  [[ "$configuration" == *.fixture && "$configuration" != */* ]] || exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Use the candidate's own migration selection rule. A missing ledger entry
# blocks the release even when /health and /ready would still answer 200.
migration_manifest() {
  python3 - "$1" <<'MANIFEST'
import json
from pathlib import Path
import runpy
import sys
backend = Path(sys.argv[1]).resolve()
files = runpy.run_path(str(backend / "scripts/migrate.py"))["migration_files"](backend / "migrations")
if not files:
    raise SystemExit("release has no active migration files")
print(json.dumps(files, separators=(",", ":")))
MANIFEST
}
expected_migrations=$(migration_manifest "$script_dir/../backend")
if [[ "${1:-}" == "--dry-run" ]]; then
  EXPECTED_MIGRATIONS="$expected_migrations" \
    "${BACKEND_RELEASE_PYTHON:-python3}" "$script_dir/check_backend_schema.py"
  echo "dry-run OK: schema ready; build and restart were not run"
  exit 0
fi

release_sha=${1:-}
if [[ ! "$release_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "expected an exact 40-character release SHA" >&2
  exit 2
fi

if [[ "${BACKEND_RELEASE_TEST_MODE:-}" == 1 ]]; then
  release_root="${BACKEND_RELEASE_TEST_ROOT:?}/releases"
  active_link="$BACKEND_RELEASE_TEST_ROOT/current"
else
  release_root=/opt/pastorai-releases
  active_link=/opt/pastorai-current
fi
candidate="$release_root/$release_sha"
active=$(readlink -f -- "$active_link")
if [[ "$(readlink -f -- "$candidate")" != "$candidate" || -L "$candidate/deploy" ||
      -e "$candidate/deploy/$configuration" || -L "$candidate/deploy/$configuration" ]]; then
  echo "candidate path is aliased or contains an existing private configuration" >&2
  exit 1
fi
if [[ "$active" != "$release_root/"* || ! -d "$active/deploy" || ! -d "$candidate/deploy" || "$active" == "$candidate" ]]; then
  echo "release paths are missing, outside the release root, or already active" >&2
  exit 1
fi
if [[ ! -f "$active/deploy/$configuration" || ! -f "$candidate/deploy/check_backend_schema.py" ]]; then
  echo "active configuration or candidate schema check is missing" >&2
  exit 1
fi

export PASTORAI_ENV_FILE="$configuration"
services=(backend queue-worker cron-worker broadcast-worker)
restart_started=0

check_compose_gates() {
  docker compose config --format json | python3 -c '
import json
import sys

try:
    services = json.load(sys.stdin)["services"]
except (KeyError, TypeError, ValueError):
    print("effective Compose gates unverifiable", file=sys.stderr)
    sys.exit(1)

expected = {
    "ALLOW_REAL_SENDS": "false",
    "ASAAS_BILLING_ENABLED": "false",
    "BREVO_SEND_MODE": "off",
    "BROADCAST_ASYNC_ENABLED": "false",
}
for name in ("backend", "queue-worker", "cron-worker", "broadcast-worker"):
    environment = services.get(name, {}).get("environment")
    if not isinstance(environment, dict) or any(
        environment.get(key) != value for key, value in expected.items()
    ):
        print(f"effective Compose gates open or unverifiable: {name}", file=sys.stderr)
        sys.exit(1)
'
}

check_external_gates() {
  local service
  for service in "${services[@]}"; do
    if ! docker compose exec -T "$service" sh -c '
      [ "${ALLOW_REAL_SENDS+x}" = x ] && [ "$ALLOW_REAL_SENDS" = false ] &&
      [ "${ASAAS_BILLING_ENABLED+x}" = x ] && [ "$ASAAS_BILLING_ENABLED" = false ] &&
      [ "${BREVO_SEND_MODE+x}" = x ] && [ "$BREVO_SEND_MODE" = off ] &&
      [ "${BROADCAST_ASYNC_ENABLED+x}" = x ] && [ "$BROADCAST_ASYNC_ENABLED" = false ]
    ' >/dev/null; then
      echo "external-effect gates open or unverifiable: $service" >&2
      return 1
    fi
  done
}

# Containers are inspected while stopped, before any application entrypoint.
create_and_start() {
  local service container
  docker compose up --no-start --no-build --no-deps --pull never --force-recreate "${services[@]}" || return 1
  for service in "${services[@]}"; do
    container=$(docker compose ps -aq "$service")
    [[ -n "$container" && "$container" != *$'\n'* ]] || return 1
    docker inspect --format '{{json .Config.Env}}' "$container" | python3 -c '
import json, sys
try:
    entries = json.load(sys.stdin)
    env = dict(item.split("=", 1) for item in entries)
    expected = {"ALLOW_REAL_SENDS": "false", "ASAAS_BILLING_ENABLED": "false",
                "BREVO_SEND_MODE": "off", "BROADCAST_ASYNC_ENABLED": "false"}
    if len(env) != len(entries) or not all(env.get(k) == v for k, v in expected.items()):
        raise ValueError("invalid gates")
except Exception:
    sys.exit("stopped container gates open or unverifiable")
' || return 1
  done
  docker compose start --wait --wait-timeout 180 "${services[@]}"
}

cleanup() {
  local status=$?
  if [[ "$(readlink -f -- "$active_link")" != "$candidate" ]]; then
    rm -f -- "$candidate/deploy/$configuration"
  fi
  rm -f -- "$active_link.next.$$"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

rollback() {
  local original_status=$? previous_migrations
  trap - ERR
  if (( restart_started )); then
    # Stop first: a rejected rollback must never leave candidate workers running.
    docker compose stop "${services[@]}" || { echo "containment failed; human intervention required" >&2; exit "$original_status"; }
    cd -- "$active/deploy"
    if [[ ! -f check_backend_schema.py ]] ||
       ! previous_migrations=$(migration_manifest "$active/backend"); then
      echo "rollback schema compatibility unverifiable; keep gates closed and use a reviewed forward fix" >&2
      exit "$original_status"
    fi
    if ! check_compose_gates ||
       ! docker compose build backend ||
       ! docker compose run --rm --no-deps -T -e "EXPECTED_MIGRATIONS=$previous_migrations" --entrypoint python backend - < check_backend_schema.py ||
       ! create_and_start ||
       ! check_external_gates ||
       ! curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null ||
       ! curl -fsS --max-time 5 http://127.0.0.1:8000/ready >/dev/null; then
      docker compose stop "${services[@]}" || true
      echo "rollback of code is unhealthy or schema incompatible; keep gates closed and use a reviewed forward fix" >&2
    fi
  else
    echo "deploy stopped before restart; previous containers remain active" >&2
  fi
  exit "$original_status"
}
trap rollback ERR

# Keep secrets on the VPS; never include them in the Git archive or logs.
cp -p -- "$active/deploy/$configuration" "$candidate/deploy/$configuration"
chmod 600 "$candidate/deploy/$configuration"
cd -- "$candidate/deploy"
docker compose config --quiet
check_compose_gates

# The current backend container has the database driver and live DATABASE_URL.
# The candidate checker is piped in; it queries only catalog metadata and the
# migration ledger inside a read-only transaction. A failure exits before build.
cd -- "$active/deploy"
check_compose_gates
check_external_gates
docker compose exec -T -e "EXPECTED_MIGRATIONS=$expected_migrations" backend python - \
  < "$candidate/deploy/check_backend_schema.py"

cd -- "$candidate/deploy"
docker compose build backend
restart_started=1
create_and_start
check_external_gates
curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null
curl -fsS --max-time 5 http://127.0.0.1:8000/ready >/dev/null

# Only a healthy candidate becomes the stable release. The old tree remains
# available for code rollback; its database schema is never rolled back here.
ln -s -- "$candidate" "$active_link.next.$$"
mv -Tf -- "$active_link.next.$$" "$active_link"
trap - ERR
echo "backend release healthy: $release_sha"
