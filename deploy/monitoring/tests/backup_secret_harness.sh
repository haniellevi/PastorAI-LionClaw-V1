#!/usr/bin/env sh
set -eu

TEST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "$TEST_DIR/../.." && pwd)
BACKUP_SCRIPT="$DEPLOY_DIR/backup-production.sh"
SANDBOX=$(mktemp -d "${TMPDIR:-/tmp}/pastorai-backup-secret-test.XXXXXX")
trap 'rm -rf -- "$SANDBOX"' EXIT INT TERM

SECRET='postgresql://synthetic-user:synthetic-secret@example.invalid/database'
BACKUP_ROOT="$SANDBOX/backups"
ENV_FILE="$SANDBOX/deploy.env"
COMPOSE_FILE="$SANDBOX/docker-compose.yml"
BIN_DIR="$SANDBOX/bin"
ARGV_LOG="$SANDBOX/docker.argv"
ENV_LOG="$SANDBOX/docker.env"
MODE_LOG="$SANDBOX/env-file.mode"
mkdir -p "$BACKUP_ROOT" "$BIN_DIR"
printf 'DATABASE_URL=%s\n' "$SECRET" >"$ENV_FILE"
printf 'services: {}\n' >"$COMPOSE_FILE"
chmod 0600 "$ENV_FILE" "$COMPOSE_FILE"

cat >"$BIN_DIR/docker" <<'EOF'
#!/usr/bin/env sh
set -eu
printf '%s\n' "$@" >"$FAKE_DOCKER_ARGV_LOG"
env >"$FAKE_DOCKER_ENV_LOG"
previous=
for argument in "$@"; do
  if [ "$previous" = --env-file ]; then
    stat -c '%a' "$argument" >"$FAKE_DOCKER_MODE_LOG"
  fi
  previous=$argument
done
exit 23
EOF
chmod 0755 "$BIN_DIR/docker"

export PATH="$BIN_DIR:$PATH"
export FAKE_DOCKER_ARGV_LOG="$ARGV_LOG"
export FAKE_DOCKER_ENV_LOG="$ENV_LOG"
export FAKE_DOCKER_MODE_LOG="$MODE_LOG"
set +e
output=$(
  PASTORAI_BACKUP_ROOT="$BACKUP_ROOT" \
  PASTORAI_ENV_FILE="$ENV_FILE" \
  PASTORAI_COMPOSE_FILE="$COMPOSE_FILE" \
  PASTORAI_BACKUP_LOCK_FILE="$SANDBOX/backup.lock" \
  bash "$BACKUP_SCRIPT" 2>&1
)
status=$?
set -e

[ "$status" -eq 23 ]
[ "$(cat "$MODE_LOG")" = 600 ]
if printf '%s\n' "$output" | grep -Fq "$SECRET"; then
  echo "secret leaked to output" >&2
  exit 1
fi
if grep -Fq "$SECRET" "$ARGV_LOG"; then
  echo "secret leaked to argv" >&2
  exit 1
fi
if grep -Fq "$SECRET" "$ENV_LOG"; then
  echo "secret leaked to process environment" >&2
  exit 1
fi
if find "$BACKUP_ROOT" -maxdepth 1 -name '.database-url.*' -print -quit \
  | grep -q .; then
  echo "temporary database env leaked" >&2
  exit 1
fi
printf 'BACKUP_SECRET_OK\n'
