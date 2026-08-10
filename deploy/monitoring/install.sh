#!/usr/bin/env sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Execute como root no Web Terminal da VPS." >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR=/opt/pastorai-monitor
CONFIG_FILE=/etc/pastorai-monitor.env
APP_ENV_FILE=/opt/pastorai-current/deploy/.env
BACKUP_ROOT=/root/pastorai-backups
BACKUP_TIMER_MODE=${PASTORAI_BACKUP_TIMER_MODE:-preserve}
BACKUP_COMMAND_PATTERN='(/usr/local/sbin/pastorai-backup\.sh|/opt/pastorai-current/deploy/backup-production\.sh)'

legacy_backup_schedule_present() {
  for candidate in /etc/crontab /etc/cron.d/*; do
    [ -f "$candidate" ] || continue
    if grep -Ev '^[[:space:]]*(#|$)' "$candidate" \
      | grep -Eq "$BACKUP_COMMAND_PATTERN"; then
      return 0
    fi
  done
  if command -v crontab >/dev/null 2>&1 \
    && crontab -l 2>/dev/null \
      | grep -Ev '^[[:space:]]*(#|$)' \
      | grep -Eq "$BACKUP_COMMAND_PATTERN"; then
    return 0
  fi
  return 1
}

if [ ! -f "$APP_ENV_FILE" ]; then
  echo "Release ativo nao encontrado em /opt/pastorai-current." >&2
  exit 1
fi

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
if legacy_backup_schedule_present; then
  LEGACY_BACKUP_SCHEDULE=1
fi
if systemctl is-enabled --quiet pastorai-backup.timer 2>/dev/null; then
  BACKUP_TIMER_ENABLED=1
fi
if [ "$LEGACY_BACKUP_SCHEDULE" -eq 1 ] && [ "$BACKUP_TIMER_ENABLED" -eq 1 ]; then
  echo "Cron legado e pastorai-backup.timer estao ativos; resolva a duplicidade antes de instalar." >&2
  exit 1
fi
if [ "$BACKUP_TIMER_MODE" = enable ] && [ "$LEGACY_BACKUP_SCHEDULE" -eq 1 ]; then
  echo "Cron legado detectado; preserve-o ou migre-o explicitamente antes de habilitar o timer." >&2
  exit 1
fi

install -d -m 0755 "$INSTALL_DIR"
install -d -m 0700 /var/lib/pastorai-monitor "$BACKUP_ROOT"
install -m 0755 "$SCRIPT_DIR/production_monitor.py" "$INSTALL_DIR/production_monitor.py"
install -m 0644 "$SCRIPT_DIR/systemd/pastorai-monitor.service" /etc/systemd/system/
install -m 0644 "$SCRIPT_DIR/systemd/pastorai-monitor.timer" /etc/systemd/system/
install -m 0644 "$SCRIPT_DIR/systemd/pastorai-backup.service" /etc/systemd/system/
install -m 0644 "$SCRIPT_DIR/systemd/pastorai-backup.timer" /etc/systemd/system/

umask 077
{
  printf 'PASTORAI_ENV_FILE=%s\n' "$APP_ENV_FILE"
  printf 'MONITOR_ALERT_EMAIL=%s\n' "$ALERT_EMAIL"
  printf 'MONITOR_BACKUP_ROOT=%s\n' "$BACKUP_ROOT"
  printf 'MONITOR_BACKUP_MAX_AGE_HOURS=30\n'
  printf 'MONITOR_REMINDER_HOURS=6\n'
  printf 'MONITOR_RETRY_HOURS=1\n'
  printf 'MONITOR_AMBIGUOUS_RETRY_HOURS=6\n'
} >"$CONFIG_FILE"
chmod 0600 "$CONFIG_FILE"

systemctl daemon-reload
systemctl enable --now pastorai-monitor.timer
FAILED=0
if [ "$BACKUP_TIMER_MODE" = enable ]; then
  systemctl enable --now pastorai-backup.timer
  if ! systemctl start pastorai-backup.service; then
    echo "Primeiro backup falhou; consulte o journal do servico." >&2
    FAILED=1
  fi
elif [ "$LEGACY_BACKUP_SCHEDULE" -eq 1 ]; then
  echo "Cron legado de backup preservado; pastorai-backup.timer nao foi habilitado."
else
  echo "Nenhum agendador de backup alterado; use PASTORAI_BACKUP_TIMER_MODE=enable somente apos preflight."
fi
if ! systemctl start pastorai-monitor.service; then
  echo "Monitor detectou falha; consulte o journal do servico." >&2
  FAILED=1
fi
systemctl list-timers pastorai-backup.timer pastorai-monitor.timer --all --no-pager
if [ "$FAILED" -ne 0 ]; then
  exit 1
fi
echo "Monitor instalado. Revise: journalctl -u pastorai-monitor.service -n 50 --no-pager"
