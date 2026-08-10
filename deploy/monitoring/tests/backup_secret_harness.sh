#!/usr/bin/env sh
set -eu

TEST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "$TEST_DIR/../.." && pwd)
BACKUP_SCRIPT="$DEPLOY_DIR/backup-production.sh"
SANDBOX=$(mktemp -d "${TMPDIR:-/tmp}/pastorai-backup-secret-test.XXXXXX")
trap 'rm -rf -- "$SANDBOX"' EXIT INT TERM

SECRET='postgresql://synthetic-user:synthetic-secret@example.invalid/database?sslmode=require'
PASSWORD='synthetic-secret'
BACKUP_ROOT="$SANDBOX/backups"
ENV_FILE="$SANDBOX/deploy.env"
COMPOSE_FILE="$SANDBOX/docker-compose.yml"
BIN_DIR="$SANDBOX/bin"
DOCKER_ARGV_LOG="$SANDBOX/docker.argv"
DOCKER_ENV_LOG="$SANDBOX/docker.env"
PGDUMP_ARGV_LOG="$SANDBOX/pg_dump.argv"
PGDUMP_ENV_LOG="$SANDBOX/pg_dump.env"
MODE_LOG="$SANDBOX/credential-modes"
mkdir -p "$BACKUP_ROOT" "$BIN_DIR"
printf 'DATABASE_URL=%s\n' "$SECRET" >"$ENV_FILE"
printf 'services: {}\n' >"$COMPOSE_FILE"
chmod 0600 "$ENV_FILE" "$COMPOSE_FILE"

cat >"$BIN_DIR/pg_dump" <<'EOF'
#!/usr/bin/env sh
set -eu
tr '\000' '\n' <"/proc/$$/cmdline" >"$FAKE_PGDUMP_ARGV_LOG"
tr '\000' '\n' <"/proc/$$/environ" >"$FAKE_PGDUMP_ENV_LOG"
[ "$PGSERVICE" = pastorai_backup ]
[ -f "$PGSERVICEFILE" ]
  grep -Fq "passfile = '/run/pastorai-backup/pgpass'" "$PGSERVICEFILE"
  printf 'fake dump\n'
  if [ "${FAKE_PGDUMP_MODE:-error}" = hold ]; then
    while :; do sleep 1; done
  fi
  exit 23
EOF
chmod 0755 "$BIN_DIR/pg_dump"

cat >"$BIN_DIR/docker" <<'EOF'
#!/usr/bin/env sh
set -eu
printf '%s\n' "$@" >"$FAKE_DOCKER_ARGV_LOG"
env >"$FAKE_DOCKER_ENV_LOG"

mount_source=
service=
service_file=
next=
command_seen=0
for argument in "$@"; do
  if [ "$next" = mount ]; then
    mount_source=$(printf '%s' "$argument" | sed -n 's/.*src=\([^,]*\).*/\1/p')
    next=
    continue
  fi
  if [ "$next" = env ]; then
    case "$argument" in
      PGSERVICE=*) service=${argument#PGSERVICE=} ;;
      PGSERVICEFILE=*) service_file=${argument#PGSERVICEFILE=} ;;
    esac
    next=
    continue
  fi
  case "$argument" in
    --mount) next=mount ;;
    --env) next=env ;;
    postgres:17-alpine) command_seen=1 ;;
    *)
      if [ "$command_seen" -eq 1 ]; then
        break
      fi
      ;;
  esac
done

[ -n "$mount_source" ]
[ "$service" = pastorai_backup ]
[ "$service_file" = /run/pastorai-backup/pg_service.conf ]
[ "$(stat -c '%a' "$mount_source/pg_service.conf")" = 600 ]
[ "$(stat -c '%a' "$mount_source/pgpass")" = 600 ]
printf '%s\n' "$(stat -c '%a' "$mount_source/pg_service.conf")" "$(stat -c '%a' "$mount_source/pgpass")" >"$FAKE_MODE_LOG"

# Docker forwards only values passed with --env.  Recreate that boundary so the
# fake pg_dump is inspected through /proc with no inherited URL/password.
exec env -i \
  PATH="$PATH" \
  PGSERVICE="$service" \
  PGSERVICEFILE="$mount_source/pg_service.conf" \
  FAKE_PGDUMP_MODE="${FAKE_PGDUMP_MODE:-error}" \
  FAKE_PGDUMP_ARGV_LOG="$FAKE_PGDUMP_ARGV_LOG" \
  FAKE_PGDUMP_ENV_LOG="$FAKE_PGDUMP_ENV_LOG" \
  "$FAKE_PGDUMP" pg_dump --format=custom --compress=9 --no-owner --no-acl --schema=public
EOF
chmod 0755 "$BIN_DIR/docker"

export PATH="$BIN_DIR:$PATH"
export FAKE_DOCKER_ARGV_LOG="$DOCKER_ARGV_LOG"
export FAKE_DOCKER_ENV_LOG="$DOCKER_ENV_LOG"
export FAKE_PGDUMP_ARGV_LOG="$PGDUMP_ARGV_LOG"
export FAKE_PGDUMP_ENV_LOG="$PGDUMP_ENV_LOG"
export FAKE_MODE_LOG="$MODE_LOG"
export FAKE_PGDUMP="$BIN_DIR/pg_dump"
set +e
output=$(
  DATABASE_URL="$SECRET" \
  PGPASSWORD="$PASSWORD" \
  PASTORAI_BACKUP_ROOT="$BACKUP_ROOT" \
  PASTORAI_ENV_FILE="$ENV_FILE" \
  PASTORAI_COMPOSE_FILE="$COMPOSE_FILE" \
  PASTORAI_BACKUP_LOCK_FILE="$SANDBOX/backup.lock" \
  bash "$BACKUP_SCRIPT" 2>&1
)
status=$?
set -e

[ "$status" -eq 23 ]
[ "$(cat "$MODE_LOG")" = "600
600" ]
for log in "$DOCKER_ARGV_LOG" "$DOCKER_ENV_LOG" "$PGDUMP_ARGV_LOG" "$PGDUMP_ENV_LOG"; do
  if grep -Fq "$SECRET" "$log" || grep -Fq "$PASSWORD" "$log"; then
    echo "secret leaked to process inspection" >&2
    exit 1
  fi
done
if printf '%s\n' "$output" | grep -Fq "$SECRET" || printf '%s\n' "$output" | grep -Fq "$PASSWORD"; then
  echo "secret leaked to output" >&2
  exit 1
fi
if find "$BACKUP_ROOT" -maxdepth 1 -name '.pg-credentials.*' -print -quit | grep -q .; then
  echo "temporary libpq credentials leaked" >&2
  exit 1
fi

# Exercise the signal trap independently from the ordinary pg_dump error path.
# timeout uses an isolated process group, so the simulated pg_dump is also
# interrupted and cannot keep the shell waiting after TERM.
set +e
FAKE_PGDUMP_MODE=hold \
DATABASE_URL="$SECRET" \
PGPASSWORD="$PASSWORD" \
PASTORAI_BACKUP_ROOT="$BACKUP_ROOT" \
PASTORAI_ENV_FILE="$ENV_FILE" \
PASTORAI_COMPOSE_FILE="$COMPOSE_FILE" \
PASTORAI_BACKUP_LOCK_FILE="$SANDBOX/backup-signal.lock" \
timeout -k 3s -s TERM 2s bash "$BACKUP_SCRIPT" \
  >"$SANDBOX/signal-output" 2>&1 &
signal_runner=$!
set -e
for _ in $(seq 1 40); do
  if find "$BACKUP_ROOT" -maxdepth 1 -name '.pg-credentials.*' -print -quit | grep -q .; then
    break
  fi
  sleep 0.05
done
if ! find "$BACKUP_ROOT" -maxdepth 1 -name '.pg-credentials.*' -print -quit | grep -q .; then
  echo "signal test did not create temporary credentials" >&2
  exit 1
fi
set +e
wait "$signal_runner"
signal_status=$?
set -e
case "$signal_status" in
  124|137|143) ;;
  *)
    echo "unexpected signal test status: $signal_status" >&2
    exit 1
    ;;
esac
if find "$BACKUP_ROOT" -maxdepth 1 -name '.pg-credentials.*' -print -quit | grep -q .; then
  echo "temporary libpq credentials survived termination" >&2
  exit 1
fi
printf 'BACKUP_SECRET_OK\n'
