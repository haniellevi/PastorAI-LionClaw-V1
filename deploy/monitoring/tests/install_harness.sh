#!/usr/bin/env sh
set -eu

TEST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_SCRIPT=$(CDPATH= cd -- "$TEST_DIR/.." && pwd)/install.sh
SCENARIO=${1:?scenario required}
SANDBOX=$(mktemp -d "${TMPDIR:-/tmp}/pastorai-install-test.XXXXXX")
trap 'rm -rf -- "$SANDBOX"' EXIT INT TERM

BIN_DIR="$SANDBOX/bin"
SYSTEMCTL_STATE="$SANDBOX/systemctl-state"
INSTALL_DIR="$SANDBOX/opt/pastorai-monitor"
STATE_DIR="$SANDBOX/var/lib/pastorai-monitor"
BACKUP_ROOT="$SANDBOX/root/pastorai-backups"
BACKUP_MANIFEST="$SANDBOX/var/lib/pastorai-backup/backup-status.json"
SYSTEMD_DIR="$SANDBOX/etc/systemd/system"
CONFIG_DIR="$SANDBOX/etc/config"
CONFIG_FILE="$CONFIG_DIR/pastorai-monitor.env"
APP_ENV_FILE="$SANDBOX/opt/pastorai-current/deploy/.env"
CRON_FILE="$SANDBOX/etc/crontab"
TRANSACTION_TMP="$SANDBOX/tmp"
mkdir -p "$BIN_DIR" "$SYSTEMCTL_STATE" "$(dirname -- "$APP_ENV_FILE")" \
  "$(dirname -- "$CRON_FILE")" "$TRANSACTION_TMP"
: >"$APP_ENV_FILE"
: >"$CRON_FILE"

cat >"$BIN_DIR/systemctl" <<'EOF'
#!/usr/bin/env sh
set -eu
state=${FAKE_SYSTEMCTL_STATE:?}
command=$1
shift
case "$command" in
  is-enabled|is-active)
    [ "${1:-}" != --quiet ] || shift
    unit=$1
    suffix=active
    [ "$command" != is-enabled ] || suffix=enabled
    [ -f "$state/$unit.$suffix" ]
    ;;
  enable)
    start_now=0
    if [ "${1:-}" = --now ]; then
      start_now=1
      shift
    fi
    for unit in "$@"; do
      : >"$state/$unit.enabled"
      [ "$start_now" -eq 0 ] || : >"$state/$unit.active"
    done
    ;;
  disable)
    for unit in "$@"; do rm -f -- "$state/$unit.enabled"; done
    ;;
  start)
    for unit in "$@"; do
      case "$unit" in *.timer) : >"$state/$unit.active" ;; esac
    done
    ;;
  stop)
    for unit in "$@"; do rm -f -- "$state/$unit.active"; done
    ;;
  show)
    if [ "${FAKE_SYSTEMCTL_LOAD_FAIL:-0}" = 1 ]; then
      printf '%s\n' not-found
      exit 1
    fi
    printf '%s\n' loaded
    ;;
  daemon-reload|list-timers) ;;
  *) echo "unexpected fake systemctl command: $command" >&2; exit 64 ;;
esac
EOF
cat >"$BIN_DIR/systemd-analyze" <<'EOF'
#!/usr/bin/env sh
exit 0
EOF
cat >"$BIN_DIR/crontab" <<'EOF'
#!/usr/bin/env sh
exit 1
EOF
chmod 0755 "$BIN_DIR/systemctl" "$BIN_DIR/systemd-analyze" "$BIN_DIR/crontab"

export PASTORAI_INSTALL_TEST_MODE=1
export PASTORAI_MONITOR_INSTALL_DIR="$INSTALL_DIR"
export PASTORAI_MONITOR_CONFIG_FILE="$CONFIG_FILE"
export PASTORAI_ENV_FILE="$APP_ENV_FILE"
export PASTORAI_BACKUP_ROOT="$BACKUP_ROOT"
export PASTORAI_BACKUP_MONITOR_MANIFEST="$BACKUP_MANIFEST"
export PASTORAI_MONITOR_STATE_DIR="$STATE_DIR"
export PASTORAI_SYSTEMD_DIR="$SYSTEMD_DIR"
export PASTORAI_SYSTEMCTL_BIN="$BIN_DIR/systemctl"
export PASTORAI_SYSTEMD_ANALYZE_BIN="$BIN_DIR/systemd-analyze"
export PASTORAI_CRONTAB_BIN="$BIN_DIR/crontab"
export PASTORAI_CRON_PATHS="$CRON_FILE"
export FAKE_SYSTEMCTL_STATE="$SYSTEMCTL_STATE"
export MONITOR_ALERT_EMAIL="alerts@example.invalid"
export TMPDIR="$TRANSACTION_TMP"

run_installer() {
  sh "$INSTALL_SCRIPT"
}

assert_no_live_writes() {
  [ ! -e "$INSTALL_DIR/production_monitor.py" ]
  [ ! -e "$CONFIG_FILE" ]
  [ ! -e "$SYSTEMD_DIR/pastorai-monitor.service" ]
  [ ! -e "$SYSTEMD_DIR/pastorai-backup.timer" ]
}

case "$SCENARIO" in
  matrix)
    cron=$2
    enabled=$3
    active=$4
    mode=$5
    expected=$6
    if [ "$cron" -eq 1 ]; then
      printf '10 3 * * * root /opt/pastorai-current/deploy/backup-production.sh\n' \
        >"$CRON_FILE"
    fi
    [ "$enabled" -eq 0 ] || : >"$SYSTEMCTL_STATE/pastorai-backup.timer.enabled"
    [ "$active" -eq 0 ] || : >"$SYSTEMCTL_STATE/pastorai-backup.timer.active"
    export PASTORAI_BACKUP_TIMER_MODE="$mode"
    set +e
    output=$(run_installer 2>&1)
    status=$?
    set -e
    if [ "$expected" = fail ]; then
      [ "$status" -ne 0 ]
      assert_no_live_writes
    else
      [ "$status" -eq 0 ] || { printf '%s\n' "$output" >&2; exit 1; }
      [ -f "$INSTALL_DIR/production_monitor.py" ]
      [ -f "$SYSTEMD_DIR/pastorai-monitor.service" ]
    fi
    printf 'MATRIX_OK cron=%s enabled=%s active=%s mode=%s expected=%s\n' \
      "$cron" "$enabled" "$active" "$mode" "$expected"
    ;;
  rollback)
    fail_step=$2
    mode=$3
    mkdir -p "$INSTALL_DIR" "$STATE_DIR" "$BACKUP_ROOT" "$SYSTEMD_DIR" "$CONFIG_DIR"
    chmod 0711 "$INSTALL_DIR"
    chmod 0750 "$STATE_DIR" "$BACKUP_ROOT"
    chmod 0710 "$SYSTEMD_DIR" "$CONFIG_DIR"
    printf 'old-monitor\n' >"$INSTALL_DIR/production_monitor.py"
    printf 'old-config\n' >"$CONFIG_FILE"
    for unit in pastorai-monitor.service pastorai-monitor.timer \
      pastorai-backup.service pastorai-backup.timer; do
      printf 'old-%s\n' "$unit" >"$SYSTEMD_DIR/$unit"
    done
    : >"$SYSTEMCTL_STATE/pastorai-monitor.timer.enabled"
    : >"$SYSTEMCTL_STATE/pastorai-monitor.timer.active"
    export PASTORAI_BACKUP_TIMER_MODE="$mode"
    export PASTORAI_INSTALL_FAIL_STEP="$fail_step"
    set +e
    output=$(run_installer 2>&1)
    status=$?
    set -e
    [ "$status" -ne 0 ]
    [ "$(cat "$INSTALL_DIR/production_monitor.py")" = old-monitor ]
    [ "$(cat "$CONFIG_FILE")" = old-config ]
    for unit in pastorai-monitor.service pastorai-monitor.timer \
      pastorai-backup.service pastorai-backup.timer; do
      [ "$(cat "$SYSTEMD_DIR/$unit")" = "old-$unit" ]
    done
    [ "$(stat -c '%a' "$INSTALL_DIR")" = 711 ]
    [ "$(stat -c '%a' "$STATE_DIR")" = 750 ]
    [ "$(stat -c '%a' "$BACKUP_ROOT")" = 750 ]
    [ "$(stat -c '%a' "$SYSTEMD_DIR")" = 710 ]
    [ "$(stat -c '%a' "$CONFIG_DIR")" = 710 ]
    [ -f "$SYSTEMCTL_STATE/pastorai-monitor.timer.enabled" ]
    [ -f "$SYSTEMCTL_STATE/pastorai-monitor.timer.active" ]
    [ ! -f "$SYSTEMCTL_STATE/pastorai-backup.timer.enabled" ]
    [ ! -f "$SYSTEMCTL_STATE/pastorai-backup.timer.active" ]
    if find "$TRANSACTION_TMP" -mindepth 1 -print -quit | grep -q .; then
      echo "transaction directory leaked" >&2
      exit 1
    fi
    printf 'ROLLBACK_OK step=%s mode=%s\n' "$fail_step" "$mode"
    ;;
  operational)
    # No manifest or live API is required to install the timer.  The monitor
    # reports those conditions on its own tick after the transaction commits.
    export PASTORAI_BACKUP_TIMER_MODE=preserve
    run_installer >/dev/null
    [ -f "$INSTALL_DIR/production_monitor.py" ]
    [ -f "$SYSTEMCTL_STATE/pastorai-monitor.timer.enabled" ]
    [ -f "$SYSTEMCTL_STATE/pastorai-monitor.timer.active" ]
    printf 'OPERATIONAL_DEGRADATION_INSTALL_OK\n'
    ;;
  idempotent)
    export PASTORAI_BACKUP_TIMER_MODE=preserve
    run_installer >/dev/null
    first=$(sha256sum "$INSTALL_DIR/production_monitor.py" "$CONFIG_FILE" \
      "$SYSTEMD_DIR"/pastorai-*.service "$SYSTEMD_DIR"/pastorai-*.timer)
    run_installer >/dev/null
    second=$(sha256sum "$INSTALL_DIR/production_monitor.py" "$CONFIG_FILE" \
      "$SYSTEMD_DIR"/pastorai-*.service "$SYSTEMD_DIR"/pastorai-*.timer)
    [ "$first" = "$second" ]
    [ -f "$SYSTEMCTL_STATE/pastorai-monitor.timer.enabled" ]
    [ -f "$SYSTEMCTL_STATE/pastorai-monitor.timer.active" ]
    [ ! -f "$SYSTEMCTL_STATE/pastorai-backup.timer.enabled" ]
    printf 'IDEMPOTENT_OK\n'
    ;;
  *) echo "unknown scenario: $SCENARIO" >&2; exit 64 ;;
esac
