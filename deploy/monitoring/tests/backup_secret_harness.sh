#!/usr/bin/env sh
set -eu

TEST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "$TEST_DIR/../.." && pwd)
INSTALL_SCRIPT="$DEPLOY_DIR/install-legacy-backup.sh"
SANDBOX=$(mktemp -d "${TMPDIR:-/tmp}/pastorai-backup-secret-test.XXXXXX")
SIGNAL_PGID=""
cleanup_sandbox() {
  if [ -n "$SIGNAL_PGID" ]; then
    /bin/kill -TERM -- "-$SIGNAL_PGID" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$SANDBOX"
}
trap cleanup_sandbox EXIT INT TERM

SECRET='postgresql://synthetic-user:synthetic-secret@example.invalid/database?sslmode=require'
PASSWORD='synthetic-secret'
BACKUP_ROOT="$SANDBOX/backups"
ENV_FILE="$SANDBOX/deploy.env"
COMPOSE_FILE="$SANDBOX/docker-compose.yml"
BIN_DIR="$SANDBOX/bin"
LEGACY_ROOT="$SANDBOX/legacy"
BACKUP_SCRIPT="$LEGACY_ROOT/usr/local/sbin/pastorai-backup.sh"
HELPER_DIR="$LEGACY_ROOT/usr/local/libexec/pastorai-backup"
HELPER="$HELPER_DIR/prepare-database-service.py"
HELPER_SHA256="$HELPER.sha256"
REAL_PYTHON=$(command -v python3)
mkdir -p "$BACKUP_ROOT" "$BIN_DIR"
printf 'DATABASE_URL=%s\nSUPABASE_URL=https://unused.invalid\nSUPABASE_SERVICE_ROLE_KEY=unused\n' "$SECRET" >"$ENV_FILE"
printf 'services: {}\n' >"$COMPOSE_FILE"
chmod 0600 "$ENV_FILE" "$COMPOSE_FILE"
PASTORAI_LEGACY_BACKUP_INSTALL_TEST_MODE=1 \
PASTORAI_LEGACY_BACKUP_TARGET="$BACKUP_SCRIPT" \
PASTORAI_LEGACY_BACKUP_HELPER_DIR="$HELPER_DIR" \
bash "$INSTALL_SCRIPT" >/dev/null

cat >"$BIN_DIR/python3" <<'EOF'
#!/usr/bin/env sh
set -eu

phase=
case "${1##*/}" in
  prepare-database-service.py) phase=prepare ;;
  -) phase=storage ;;
  *) exec "$REAL_PYTHON" "$@" ;;
esac

printf '%s\n' "$$" >"$FAKE_INSPECT_DIR/$phase.pid"
: >"$FAKE_INSPECT_DIR/$phase.ready"
if [ "${FAKE_AUTO_RELEASE:-0}" != 1 ]; then
  while [ ! -f "$FAKE_INSPECT_DIR/$phase.release" ]; do sleep 0.01; done
fi

if [ "$phase" = storage ]; then
  exit 24
fi
exec "$REAL_PYTHON" "$@"
EOF
chmod 0755 "$BIN_DIR/python3"

cat >"$BIN_DIR/pg_dump" <<'EOF'
#!/usr/bin/env sh
set -eu

printf '%s\n' "$$" >"$FAKE_INSPECT_DIR/pgdump.pid"
: >"$FAKE_INSPECT_DIR/pgdump.ready"
if [ "${FAKE_AUTO_RELEASE:-0}" != 1 ]; then
  while [ ! -f "$FAKE_INSPECT_DIR/pgdump.release" ]; do sleep 0.01; done
fi
if [ "${FAKE_PGDUMP_HOLD:-0}" = 1 ]; then
  while :; do sleep 1; done
fi
printf 'fake dump\n'
exit 23
EOF
chmod 0755 "$BIN_DIR/pg_dump"

cat >"$BIN_DIR/docker" <<'EOF'
#!/usr/bin/env sh
set -eu

if [ "${FAKE_DOCKER_MODE:-hold}" != signal ] \
  && [ ! -f "$FAKE_INSPECT_DIR/docker.seen" ]; then
  : >"$FAKE_INSPECT_DIR/docker.seen"
  printf '%s\n' "$$" >"$FAKE_INSPECT_DIR/docker.pid"
  : >"$FAKE_INSPECT_DIR/docker.ready"
  while [ ! -f "$FAKE_INSPECT_DIR/docker.release" ]; do sleep 0.01; done
fi

mount_source=
service=
service_file=
next=
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
  esac
done

case " $* " in
  *' pg_dump '*)
    [ -n "$mount_source" ]
    [ "$service" = pastorai_backup ]
    [ "$service_file" = /run/pastorai-backup/pg_service.conf ]
    [ "$(stat -c '%a' "$mount_source/pg_service.conf")" = 600 ]
    [ "$(stat -c '%a' "$mount_source/pgpass")" = 600 ]
    if [ "${FAKE_DOCKER_MODE:-hold}" = continue ]; then
      printf 'fake dump\n'
      exit 0
    fi
    exec env -i \
      PATH="$PATH" \
      FAKE_INSPECT_DIR="$FAKE_INSPECT_DIR" \
      FAKE_AUTO_RELEASE="${FAKE_AUTO_RELEASE:-0}" \
      FAKE_PGDUMP_HOLD="${FAKE_PGDUMP_HOLD:-0}" \
      "$FAKE_PGDUMP" pg_dump --format=custom --compress=9 --no-owner --no-acl --schema=public
    ;;
  *' pg_restore '*)
    printf 'fake list\n'
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
EOF
chmod 0755 "$BIN_DIR/docker"

wait_file() {
  file=$1
  for _ in $(seq 1 200); do
    [ -f "$file" ] && return 0
    sleep 0.01
  done
  echo "timed out waiting for $file" >&2
  return 1
}

inspect_process() {
  phase=$1
  inspect_dir=$2
  pid=$(cat "$inspect_dir/$phase.pid")
  test -n "$pid"
  test -r "/proc/$pid/cmdline"
  test -r "/proc/$pid/environ"
  tr '\000' '\n' <"/proc/$pid/cmdline" >"$inspect_dir/$phase.argv"
  tr '\000' '\n' <"/proc/$pid/environ" >"$inspect_dir/$phase.env"
}

assert_no_secret() {
  inspect_dir=$1
  for log in "$inspect_dir"/*.argv "$inspect_dir"/*.env "$inspect_dir"/output; do
    [ -e "$log" ] || continue
    if grep -Fq "$SECRET" "$log" || grep -Fq "$PASSWORD" "$log"; then
      echo "secret leaked to process inspection" >&2
      exit 1
    fi
  done
}

start_backup() {
  inspect_dir=$1
  mode=$2
  mkdir -p "$inspect_dir"
  (
    export PATH="$BIN_DIR:$PATH"
    export REAL_PYTHON FAKE_PGDUMP="$BIN_DIR/pg_dump" FAKE_INSPECT_DIR="$inspect_dir"
    export FAKE_DOCKER_MODE="$mode"
    DATABASE_URL="$SECRET" \
    PGPASSWORD="$PASSWORD" \
    PASTORAI_BACKUP_ROOT="$BACKUP_ROOT" \
    PASTORAI_ENV_FILE="$ENV_FILE" \
    PASTORAI_COMPOSE_FILE="$COMPOSE_FILE" \
    PASTORAI_BACKUP_LOCK_FILE="$SANDBOX/backup.lock" \
    PASTORAI_BACKUP_MONITOR_MANIFEST="$SANDBOX/backup-status.json" \
    PASTORAI_BACKUP_HELPER="$HELPER" \
    PASTORAI_BACKUP_HELPER_SHA256="$HELPER_SHA256" \
    bash "$BACKUP_SCRIPT" >"$inspect_dir/output" 2>&1
  ) &
  BACKUP_PID=$!
}

# First path: inspect the prepare helper, Docker client and pg_dump descendants
# while each is stopped by a deterministic release file.
FIRST="$SANDBOX/inspect-first"
start_backup "$FIRST" hold
wait_file "$FIRST/prepare.ready"
inspect_process prepare "$FIRST"
: >"$FIRST/prepare.release"
wait_file "$FIRST/docker.ready"
inspect_process docker "$FIRST"
: >"$FIRST/docker.release"
wait_file "$FIRST/pgdump.ready"
inspect_process pgdump "$FIRST"
: >"$FIRST/pgdump.release"
set +e
wait "$BACKUP_PID"
status=$?
set -e
[ "$status" -eq 23 ]
assert_no_secret "$FIRST"

# Second path reaches the inline storage Python helper.  The fake pg_dump and
# pg_restore succeed, then that Python process is held until /proc inspection.
SECOND="$SANDBOX/inspect-second"
start_backup "$SECOND" continue
wait_file "$SECOND/prepare.ready"
inspect_process prepare "$SECOND"
: >"$SECOND/prepare.release"
wait_file "$SECOND/docker.ready"
inspect_process docker "$SECOND"
: >"$SECOND/docker.release"
wait_file "$SECOND/storage.ready"
inspect_process storage "$SECOND"
: >"$SECOND/storage.release"
set +e
wait "$BACKUP_PID"
status=$?
set -e
[ "$status" -eq 24 ]
assert_no_secret "$SECOND"

if find "$BACKUP_ROOT" -maxdepth 1 -name '.pg-credentials.*' -print -quit | grep -q .; then
  echo "temporary libpq credentials leaked after error" >&2
  exit 1
fi

# Signal cleanup uses an isolated process group so a blocked descendant cannot
# outlive the script.  The script's EXIT trap must still remove its credentials.
SIGNAL="$SANDBOX/inspect-signal"
mkdir -p "$SIGNAL"
set +e
# --fork --wait keeps a new session alive while providing a parent that the
# harness can wait for.  The group actually holding pg_dump is resolved from
# /proc below; $! alone is not reliable because setsid may fork.
setsid --fork --wait env \
  PATH="$BIN_DIR:$PATH" \
  REAL_PYTHON="$REAL_PYTHON" \
  FAKE_PGDUMP="$BIN_DIR/pg_dump" \
  FAKE_INSPECT_DIR="$SIGNAL" \
  FAKE_DOCKER_MODE=signal \
  FAKE_AUTO_RELEASE=1 \
  FAKE_PGDUMP_HOLD=1 \
  DATABASE_URL="$SECRET" \
  PGPASSWORD="$PASSWORD" \
  PASTORAI_BACKUP_ROOT="$BACKUP_ROOT" \
  PASTORAI_ENV_FILE="$ENV_FILE" \
  PASTORAI_COMPOSE_FILE="$COMPOSE_FILE" \
  PASTORAI_BACKUP_LOCK_FILE="$SANDBOX/backup-signal.lock" \
  PASTORAI_BACKUP_MONITOR_MANIFEST="$SANDBOX/backup-status.json" \
  PASTORAI_BACKUP_HELPER="$HELPER" \
  PASTORAI_BACKUP_HELPER_SHA256="$HELPER_SHA256" \
  bash "$BACKUP_SCRIPT" >"$SIGNAL/output" 2>&1 &
signal_runner=$!
set -e
for _ in $(seq 1 200); do
  if find "$BACKUP_ROOT" -maxdepth 1 -name '.pg-credentials.*' -print -quit | grep -q .; then
    break
  fi
  sleep 0.01
done
if ! find "$BACKUP_ROOT" -maxdepth 1 -name '.pg-credentials.*' -print -quit | grep -q .; then
  echo "signal test did not create temporary credentials" >&2
  exit 1
fi
wait_file "$SIGNAL/pgdump.ready"
inspect_process pgdump "$SIGNAL"
assert_no_secret "$SIGNAL"
SIGNAL_PGID=$(ps -o pgid= -p "$(cat "$SIGNAL/pgdump.pid")" | tr -d ' ')
HARNESS_PGID=$(ps -o pgid= -p "$$" | tr -d ' ')
if [ -z "$SIGNAL_PGID" ] || [ "$SIGNAL_PGID" = "$HARNESS_PGID" ]; then
  echo "signal test did not isolate the backup process group" >&2
  exit 1
fi
/bin/kill -TERM -- "-$SIGNAL_PGID" >/dev/null 2>&1 || true
set +e
wait "$signal_runner"
signal_status=$?
set -e
case "$signal_status" in
  130|143) ;;
  *)
    echo "unexpected signal test status: $signal_status" >&2
    exit 1
    ;;
esac
SIGNAL_PGID=""
if find "$BACKUP_ROOT" -maxdepth 1 -name '.pg-credentials.*' -print -quit | grep -q .; then
  echo "temporary libpq credentials survived termination" >&2
  exit 1
fi
assert_no_secret "$SIGNAL"
printf 'BACKUP_SECRET_OK\n'
