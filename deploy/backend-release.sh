#!/usr/bin/env bash
# Run on the VPS only after a separately authorized database release.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ "${1:-}" == "--dry-run" ]]; then
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
if [[ "$active" != "$release_root/"* || ! -d "$active/deploy" || ! -d "$candidate/deploy" || "$active" == "$candidate" ]]; then
  echo "release paths are missing, outside the release root, or already active" >&2
  exit 1
fi
if [[ ! -f "$active/deploy/.env" || ! -f "$candidate/deploy/check_backend_schema.py" ]]; then
  echo "active configuration or candidate schema check is missing" >&2
  exit 1
fi

export PASTORAI_ENV_FILE=.env
services=(backend queue-worker cron-worker broadcast-worker)
restart_started=0

rollback() {
  local original_status=$?
  trap - ERR
  if (( restart_started )); then
    echo "candidate unhealthy; restoring previous backend code" >&2
    cd -- "$active/deploy"
    if ! docker compose build backend ||
       ! docker compose up -d --no-build --no-deps --force-recreate --wait --wait-timeout 180 "${services[@]}" ||
       ! curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null ||
       ! curl -fsS --max-time 5 http://127.0.0.1:8000/ready >/dev/null; then
      echo "rollback of code is unhealthy; keep gates closed and use a reviewed forward fix" >&2
    fi
  else
    echo "deploy stopped before restart; previous containers remain active" >&2
  fi
  exit "$original_status"
}
trap rollback ERR

# Keep secrets on the VPS; never include them in the Git archive or logs.
cp -p -- "$active/deploy/.env" "$candidate/deploy/.env"
chmod 600 "$candidate/deploy/.env"
cd -- "$candidate/deploy"
docker compose config --quiet

# The current backend container has the database driver and live DATABASE_URL.
# The candidate checker is piped in; it only queries catalog metadata inside a
# read-only transaction. A failure exits before build or restart.
cd -- "$active/deploy"
docker compose exec -T backend python - < "$candidate/deploy/check_backend_schema.py"

cd -- "$candidate/deploy"
docker compose build backend
restart_started=1
docker compose up -d --no-build --no-deps --force-recreate --wait --wait-timeout 180 "${services[@]}"
curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null
curl -fsS --max-time 5 http://127.0.0.1:8000/ready >/dev/null

# Only a healthy candidate becomes the stable release. The old tree remains
# available for code rollback; its database schema is never rolled back here.
ln -s -- "$candidate" "$active_link.next.$$"
mv -Tf -- "$active_link.next.$$" "$active_link"
trap - ERR
echo "backend release healthy: $release_sha"
