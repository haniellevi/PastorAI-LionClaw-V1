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

install -d -m 0755 "$INSTALL_DIR"
install -d -m 0700 /var/lib/pastorai-monitor /var/backups/pastorai
install -m 0755 "$SCRIPT_DIR/production_monitor.py" "$INSTALL_DIR/production_monitor.py"
install -m 0644 "$SCRIPT_DIR/systemd/pastorai-monitor.service" /etc/systemd/system/
install -m 0644 "$SCRIPT_DIR/systemd/pastorai-monitor.timer" /etc/systemd/system/
install -m 0644 "$SCRIPT_DIR/systemd/pastorai-backup.service" /etc/systemd/system/
install -m 0644 "$SCRIPT_DIR/systemd/pastorai-backup.timer" /etc/systemd/system/

umask 077
{
  printf 'PASTORAI_ENV_FILE=%s\n' "$APP_ENV_FILE"
  printf 'MONITOR_ALERT_EMAIL=%s\n' "$ALERT_EMAIL"
  printf 'MONITOR_BACKUP_MAX_AGE_HOURS=30\n'
  printf 'MONITOR_REMINDER_HOURS=6\n'
} >"$CONFIG_FILE"
chmod 0600 "$CONFIG_FILE"

systemctl daemon-reload
systemctl enable --now pastorai-backup.timer pastorai-monitor.timer
FAILED=0
if ! systemctl start pastorai-backup.service; then
  echo "Primeiro backup falhou; consulte o journal do servico." >&2
  FAILED=1
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
