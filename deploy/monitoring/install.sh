#!/usr/bin/env sh
set -eu

if [ "${PASTORAI_INSTALL_TEST_MODE:-0}" != 1 ] && [ "$(id -u)" -ne 0 ]; then
  echo "Execute como root no Web Terminal da VPS." >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR=${PASTORAI_MONITOR_INSTALL_DIR:-/opt/pastorai-monitor}
CONFIG_FILE=${PASTORAI_MONITOR_CONFIG_FILE:-/etc/pastorai-monitor.env}
APP_ENV_FILE=${PASTORAI_ENV_FILE:-/opt/pastorai-current/deploy/.env}
BACKUP_ROOT=${PASTORAI_BACKUP_ROOT:-/root/pastorai-backups}
BACKUP_MANIFEST=${PASTORAI_BACKUP_MONITOR_MANIFEST:-/var/lib/pastorai-backup/backup-status.json}
STATE_DIR=${PASTORAI_MONITOR_STATE_DIR:-/var/lib/pastorai-monitor}
SYSTEMD_DIR=${PASTORAI_SYSTEMD_DIR:-/etc/systemd/system}
CONFIG_DIR=$(dirname -- "$CONFIG_FILE")
MANIFEST_DIR=$(dirname -- "$BACKUP_MANIFEST")
SYSTEMCTL=${PASTORAI_SYSTEMCTL_BIN:-systemctl}
SYSTEMD_ANALYZE=${PASTORAI_SYSTEMD_ANALYZE_BIN:-systemd-analyze}
INSTALL_BIN=${PASTORAI_INSTALL_BIN:-install}
CRONTAB_BIN=${PASTORAI_CRONTAB_BIN:-crontab}
CRON_PATHS=${PASTORAI_CRON_PATHS:-'/etc/crontab /etc/cron.d/*'}
BACKUP_TIMER_MODE=${PASTORAI_BACKUP_TIMER_MODE:-preserve}
BACKUP_COMMAND_PATTERN='(/usr/local/sbin/pastorai-backup\.sh|/opt/pastorai-current/deploy/backup-production\.sh)'

run_systemctl() {
  "$SYSTEMCTL" "$@"
}

legacy_backup_schedule_present() {
  # Intentional word splitting expands the configured system cron globs.
  # shellcheck disable=SC2086
  for candidate in $CRON_PATHS; do
    [ -f "$candidate" ] || continue
    if grep -Ev '^[[:space:]]*(#|$)' "$candidate" \
      | grep -Eq "$BACKUP_COMMAND_PATTERN"; then
      return 0
    fi
  done
  if command -v "$CRONTAB_BIN" >/dev/null 2>&1 \
    && "$CRONTAB_BIN" -l 2>/dev/null \
      | grep -Ev '^[[:space:]]*(#|$)' \
      | grep -Eq "$BACKUP_COMMAND_PATTERN"; then
    return 0
  fi
  return 1
}

unit_enabled() {
  run_systemctl is-enabled --quiet "$1" 2>/dev/null
}

unit_active() {
  run_systemctl is-active --quiet "$1" 2>/dev/null
}

unit_loaded() {
  [ "$(run_systemctl show --property=LoadState --value "$1" 2>/dev/null || true)" = loaded ]
}

fail_if_requested() {
  if [ "${PASTORAI_INSTALL_FAIL_STEP:-}" = "$1" ]; then
    echo "Falha de teste injetada em $1." >&2
    return 1
  fi
}

if [ ! -f "$APP_ENV_FILE" ]; then
  echo "Release ativo nao encontrado em /opt/pastorai-current." >&2
  exit 1
fi

for source_file in \
  "$SCRIPT_DIR/production_monitor.py" \
  "$SCRIPT_DIR/prepare_monitor_config.py" \
  "$SCRIPT_DIR/systemd/pastorai-monitor.service" \
  "$SCRIPT_DIR/systemd/pastorai-monitor.timer" \
  "$SCRIPT_DIR/systemd/pastorai-backup.service" \
  "$SCRIPT_DIR/systemd/pastorai-backup.timer"; do
  if [ ! -f "$source_file" ]; then
    echo "Artefato de monitoramento ausente." >&2
    exit 1
  fi
done

ALERT_EMAIL=${MONITOR_ALERT_EMAIL:-}
case "$ALERT_EMAIL" in
  *@*.*) ;;
  *)
    echo "Informe MONITOR_ALERT_EMAIL. Nenhuma conta nova sera criada." >&2
    exit 1
    ;;
esac

case "$BACKUP_TIMER_MODE" in
  preserve|enable) ;;
  *)
    echo "PASTORAI_BACKUP_TIMER_MODE deve ser preserve ou enable." >&2
    exit 1
    ;;
esac

LEGACY_BACKUP_SCHEDULE=0
BACKUP_TIMER_ENABLED=0
BACKUP_TIMER_ACTIVE=0
if legacy_backup_schedule_present; then
  LEGACY_BACKUP_SCHEDULE=1
fi
if unit_enabled pastorai-backup.timer; then
  BACKUP_TIMER_ENABLED=1
fi
if unit_active pastorai-backup.timer; then
  BACKUP_TIMER_ACTIVE=1
fi
if [ "$LEGACY_BACKUP_SCHEDULE" -eq 1 ] \
  && { [ "$BACKUP_TIMER_ENABLED" -eq 1 ] || [ "$BACKUP_TIMER_ACTIVE" -eq 1 ]; }; then
  echo "Cron legado e pastorai-backup.timer coexistem; resolva a duplicidade antes de instalar." >&2
  exit 1
fi
if [ "$BACKUP_TIMER_MODE" = enable ] && [ "$LEGACY_BACKUP_SCHEDULE" -eq 1 ]; then
  echo "Cron legado detectado; preserve-o ou migre-o explicitamente antes de habilitar o timer." >&2
  exit 1
fi
if unit_active pastorai-backup.service || unit_active pastorai-monitor.service; then
  echo "Servico de backup/monitor em execucao; tente novamente apos ele terminar." >&2
  exit 1
fi

umask 077
TRANSACTION_DIR=$(mktemp -d "${TMPDIR:-/tmp}/pastorai-monitor-install.XXXXXX")
STAGE_DIR="$TRANSACTION_DIR/stage"
ROLLBACK_DIR="$TRANSACTION_DIR/rollback"
mkdir -p "$STAGE_DIR/systemd" "$ROLLBACK_DIR"
ROLLBACK_READY=0
COMMITTED=0

finish_transaction() {
  status=$?
  trap - EXIT INT TERM
  if [ "$status" -ne 0 ] && [ "$ROLLBACK_READY" -eq 1 ] && [ "$COMMITTED" -eq 0 ]; then
    echo "Instalacao falhou; restaurando estado anterior." >&2
    rollback_install
  fi
  rm -rf -- "$TRANSACTION_DIR"
  exit "$status"
}
trap finish_transaction EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Stage and validate every artifact before touching live paths.
"$INSTALL_BIN" -m 0755 "$SCRIPT_DIR/production_monitor.py" "$STAGE_DIR/production_monitor.py"
for unit in pastorai-monitor.service pastorai-monitor.timer pastorai-backup.service pastorai-backup.timer; do
  "$INSTALL_BIN" -m 0644 "$SCRIPT_DIR/systemd/$unit" "$STAGE_DIR/systemd/$unit"
done
# The staged EnvironmentFile is an explicit Brevo/monitor allowlist.  Do not
# pass the deployment .env path or its inherited credentials to the monitor.
env -i PATH="$PATH" python3 "$SCRIPT_DIR/prepare_monitor_config.py" \
  "$APP_ENV_FILE" "$ALERT_EMAIL" "$BACKUP_MANIFEST" \
  "$STAGE_DIR/pastorai-monitor.env"
if command -v "$SYSTEMD_ANALYZE" >/dev/null 2>&1; then
  "$SYSTEMD_ANALYZE" verify "$STAGE_DIR/systemd/"*.service "$STAGE_DIR/systemd/"*.timer
fi

snapshot_file() {
  target=$1
  name=$2
  if [ -e "$target" ]; then
    cp -p "$target" "$ROLLBACK_DIR/$name"
    : >"$ROLLBACK_DIR/$name.present"
  fi
}

restore_file() {
  target=$1
  name=$2
  if [ -f "$ROLLBACK_DIR/$name.present" ]; then
    mkdir -p "$(dirname -- "$target")"
    cp -p "$ROLLBACK_DIR/$name" "$target"
  else
    rm -f -- "$target"
  fi
}

snapshot_state() {
  unit=$1
  prefix=$2
  if unit_enabled "$unit"; then : >"$ROLLBACK_DIR/$prefix.enabled"; fi
  if unit_active "$unit"; then : >"$ROLLBACK_DIR/$prefix.active"; fi
}

restore_state() {
  unit=$1
  prefix=$2
  if [ -f "$ROLLBACK_DIR/$prefix.enabled" ]; then
    run_systemctl enable "$unit" >/dev/null 2>&1 || true
  else
    run_systemctl disable "$unit" >/dev/null 2>&1 || true
  fi
  if [ -f "$ROLLBACK_DIR/$prefix.active" ]; then
    run_systemctl start "$unit" >/dev/null 2>&1 || true
  else
    run_systemctl stop "$unit" >/dev/null 2>&1 || true
  fi
}

INSTALL_DIR_EXISTED=0
STATE_DIR_EXISTED=0
BACKUP_ROOT_EXISTED=0
MANIFEST_DIR_EXISTED=0
SYSTEMD_DIR_EXISTED=0
CONFIG_DIR_EXISTED=0
INSTALL_DIR_MODE=
STATE_DIR_MODE=
BACKUP_ROOT_MODE=
MANIFEST_DIR_MODE=
SYSTEMD_DIR_MODE=
CONFIG_DIR_MODE=
if [ -d "$INSTALL_DIR" ]; then
  INSTALL_DIR_EXISTED=1
  INSTALL_DIR_MODE=$(stat -c '%a' "$INSTALL_DIR")
fi
if [ -d "$STATE_DIR" ]; then
  STATE_DIR_EXISTED=1
  STATE_DIR_MODE=$(stat -c '%a' "$STATE_DIR")
fi
if [ -d "$BACKUP_ROOT" ]; then
  BACKUP_ROOT_EXISTED=1
  BACKUP_ROOT_MODE=$(stat -c '%a' "$BACKUP_ROOT")
fi
if [ -d "$MANIFEST_DIR" ]; then
  MANIFEST_DIR_EXISTED=1
  MANIFEST_DIR_MODE=$(stat -c '%a' "$MANIFEST_DIR")
fi
if [ -d "$SYSTEMD_DIR" ]; then
  SYSTEMD_DIR_EXISTED=1
  SYSTEMD_DIR_MODE=$(stat -c '%a' "$SYSTEMD_DIR")
fi
if [ -d "$CONFIG_DIR" ]; then
  CONFIG_DIR_EXISTED=1
  CONFIG_DIR_MODE=$(stat -c '%a' "$CONFIG_DIR")
fi

snapshot_file "$INSTALL_DIR/production_monitor.py" production_monitor.py
snapshot_file "$CONFIG_FILE" pastorai-monitor.env
for unit in pastorai-monitor.service pastorai-monitor.timer pastorai-backup.service pastorai-backup.timer; do
  snapshot_file "$SYSTEMD_DIR/$unit" "$unit"
done
snapshot_state pastorai-monitor.timer monitor-timer
snapshot_state pastorai-backup.timer backup-timer

rollback_install() {
  set +e
  run_systemctl stop pastorai-monitor.service pastorai-backup.service >/dev/null 2>&1
  restore_file "$INSTALL_DIR/production_monitor.py" production_monitor.py
  restore_file "$CONFIG_FILE" pastorai-monitor.env
  for unit in pastorai-monitor.service pastorai-monitor.timer pastorai-backup.service pastorai-backup.timer; do
    restore_file "$SYSTEMD_DIR/$unit" "$unit"
  done
  run_systemctl daemon-reload >/dev/null 2>&1
  restore_state pastorai-monitor.timer monitor-timer
  restore_state pastorai-backup.timer backup-timer
  [ "$INSTALL_DIR_EXISTED" -eq 0 ] || chmod "$INSTALL_DIR_MODE" "$INSTALL_DIR"
  [ "$STATE_DIR_EXISTED" -eq 0 ] || chmod "$STATE_DIR_MODE" "$STATE_DIR"
  [ "$BACKUP_ROOT_EXISTED" -eq 0 ] || chmod "$BACKUP_ROOT_MODE" "$BACKUP_ROOT"
  [ "$MANIFEST_DIR_EXISTED" -eq 0 ] || chmod "$MANIFEST_DIR_MODE" "$MANIFEST_DIR"
  [ "$SYSTEMD_DIR_EXISTED" -eq 0 ] || chmod "$SYSTEMD_DIR_MODE" "$SYSTEMD_DIR"
  [ "$CONFIG_DIR_EXISTED" -eq 0 ] || chmod "$CONFIG_DIR_MODE" "$CONFIG_DIR"
  [ "$INSTALL_DIR_EXISTED" -eq 1 ] || rmdir "$INSTALL_DIR" >/dev/null 2>&1
  [ "$STATE_DIR_EXISTED" -eq 1 ] || rmdir "$STATE_DIR" >/dev/null 2>&1
  [ "$BACKUP_ROOT_EXISTED" -eq 1 ] || rmdir "$BACKUP_ROOT" >/dev/null 2>&1
  [ "$MANIFEST_DIR_EXISTED" -eq 1 ] || rmdir "$MANIFEST_DIR" >/dev/null 2>&1
  [ "$CONFIG_DIR_EXISTED" -eq 1 ] || rmdir "$CONFIG_DIR" >/dev/null 2>&1
  [ "$SYSTEMD_DIR_EXISTED" -eq 1 ] || rmdir "$SYSTEMD_DIR" >/dev/null 2>&1
  set -e
}
ROLLBACK_READY=1

apply_install() {
  "$INSTALL_BIN" -d -m 0755 "$INSTALL_DIR" || return 1
  "$INSTALL_BIN" -d -m 0700 "$STATE_DIR" "$BACKUP_ROOT" || return 1
  "$INSTALL_BIN" -d -m 0755 "$MANIFEST_DIR" || return 1
  "$INSTALL_BIN" -d -m 0755 "$SYSTEMD_DIR" || return 1
  "$INSTALL_BIN" -d -m 0755 "$CONFIG_DIR" || return 1
  "$INSTALL_BIN" -m 0755 "$STAGE_DIR/production_monitor.py" "$INSTALL_DIR/production_monitor.py" || return 1
  for unit in pastorai-monitor.service pastorai-monitor.timer pastorai-backup.service pastorai-backup.timer; do
    "$INSTALL_BIN" -m 0644 "$STAGE_DIR/systemd/$unit" "$SYSTEMD_DIR/$unit" || return 1
  done
  "$INSTALL_BIN" -m 0600 "$STAGE_DIR/pastorai-monitor.env" "$CONFIG_FILE" || return 1
  fail_if_requested copy || return 1
  run_systemctl daemon-reload || return 1
  fail_if_requested daemon-reload || return 1
  # `production_monitor.py` returns zero for operational degradation so the
  # timer can keep observing and alerting.  This check is structural only: an
  # unloaded unit can never become healthy on a later timer tick.
  unit_loaded pastorai-monitor.service || return 1
  fail_if_requested unit-load || return 1
  run_systemctl enable --now pastorai-monitor.timer || return 1
  fail_if_requested enable-monitor || return 1
  if [ "$BACKUP_TIMER_MODE" = enable ]; then
    run_systemctl enable --now pastorai-backup.timer || return 1
    fail_if_requested enable-backup || return 1
  fi
}

if ! apply_install; then
  exit 1
fi
COMMITTED=1

if [ "$BACKUP_TIMER_MODE" = enable ]; then
  echo "Timer de backup habilitado explicitamente; nenhum backup foi executado pelo instalador."
elif [ "$LEGACY_BACKUP_SCHEDULE" -eq 1 ]; then
  echo "Cron legado de backup preservado; pastorai-backup.timer nao foi habilitado."
else
  echo "Nenhum agendador de backup alterado; use PASTORAI_BACKUP_TIMER_MODE=enable somente apos preflight."
fi
run_systemctl list-timers pastorai-backup.timer pastorai-monitor.timer --all --no-pager || true
echo "Monitor instalado. O primeiro tick reportara estado operacional degradado sem desfazer a instalacao."
echo "Revise: journalctl -u pastorai-monitor.service -n 50 --no-pager"
