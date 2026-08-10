#!/usr/bin/env bash
set -euo pipefail

TEST_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
MONITOR_UNIT_SOURCE="$TEST_DIR/../systemd/pastorai-monitor.service"
BACKUP_UNIT_SOURCE="$TEST_DIR/../systemd/pastorai-backup.service"
SANDBOX=$(mktemp -d "${TMPDIR:-/var/tmp}/pastorai-systemd-sandbox.XXXXXX")
trap 'rm -rf -- "$SANDBOX"' EXIT INT TERM

UNITS_DIR="$SANDBOX/units"
BACKUP_DIR="$SANDBOX/backup"
STATE_DIR="$SANDBOX/state"
RUNTIME_DIR="$SANDBOX/runtime"
RELEASE_DIR="$SANDBOX/release"
mkdir -p "$UNITS_DIR" "$BACKUP_DIR" "$STATE_DIR" "$RUNTIME_DIR" "$RELEASE_DIR/deploy"
printf 'checksum input\n' >"$BACKUP_DIR/probe"
printf 'DATABASE_URL=not-used-by-simulation\n' >"$RELEASE_DIR/deploy/.env"
cat >"$RELEASE_DIR/deploy/simulated-backup.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cat /opt/pastorai-current/deploy/.env >/dev/null
printf 'simulated backup\n' >/root/pastorai-backups/simulated.dump
: >/run/pastorai-backup/backup.lock
EOF
chmod 0755 "$RELEASE_DIR/deploy/simulated-backup.sh"
cp "$MONITOR_UNIT_SOURCE" "$UNITS_DIR/pastorai-monitor.service"
cp "$BACKUP_UNIT_SOURCE" "$UNITS_DIR/pastorai-backup.service"
chmod 0644 "$UNITS_DIR/"*.service

systemd-analyze verify "$UNITS_DIR/pastorai-monitor.service" "$UNITS_DIR/pastorai-backup.service"
systemd-analyze security --offline=yes "$UNITS_DIR/pastorai-monitor.service" >/dev/null
systemd-analyze security --offline=yes "$UNITS_DIR/pastorai-backup.service" >/dev/null

common_properties=(
  --property=User=root
  --property=NoNewPrivileges=yes
  --property=CapabilityBoundingSet=
  --property=AmbientCapabilities=
  --property=PrivateTmp=yes
  --property=PrivateDevices=yes
  --property=PrivateMounts=yes
  --property=ProtectHome=read-only
  --property=ProtectSystem=strict
  --property=ProtectKernelTunables=yes
  --property=ProtectKernelModules=yes
  --property=ProtectKernelLogs=yes
  --property=ProtectControlGroups=yes
  --property=ProtectClock=yes
  --property=ProtectHostname=yes
  --property=ProtectProc=invisible
  --property=ProcSubset=pid
  --property='RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6'
  --property=RestrictNamespaces=yes
  --property=LockPersonality=yes
  --property=MemoryDenyWriteExecute=yes
  --property=RestrictRealtime=yes
  --property=RestrictSUIDSGID=yes
  --property=RemoveIPC=yes
  --property=KeyringMode=private
  --property=SystemCallArchitectures=native
)

deny_unrelated_writes='
  if touch /root/m08-systemd-forbidden 2>/dev/null; then exit 31; fi
  if touch /etc/m08-systemd-forbidden 2>/dev/null; then exit 32; fi
  if touch /opt/m08-systemd-forbidden 2>/dev/null; then exit 33; fi
'

monitor_unit="pastorai-m08-monitor-$RANDOM-$$"
systemd-run --wait --collect --quiet --unit="$monitor_unit" \
  "${common_properties[@]}" \
  --property=ReadOnlyPaths=/root/pastorai-backups \
  --property=ReadWritePaths=/var/lib/pastorai-monitor \
  --property=BindPaths="$BACKUP_DIR:/root/pastorai-backups" \
  --property=BindPaths="$STATE_DIR:/var/lib/pastorai-monitor" \
  --property='InaccessiblePaths=-/run/docker.sock -/var/run/docker.sock' \
  /bin/bash -c "
    cat /root/pastorai-backups/probe >/dev/null
    if touch /root/pastorai-backups/forbidden 2>/dev/null; then exit 34; fi
    touch /var/lib/pastorai-monitor/allowed
    $deny_unrelated_writes
  "
test -f "$STATE_DIR/allowed"
test ! -e "$BACKUP_DIR/forbidden"

backup_unit="pastorai-m08-backup-$RANDOM-$$"
systemd-run --wait --collect --quiet --unit="$backup_unit" \
  "${common_properties[@]}" \
  --property=ReadOnlyPaths=/opt/pastorai-current \
  --property=ReadWritePaths=/root/pastorai-backups \
  --property=BindPaths="$BACKUP_DIR:/root/pastorai-backups" \
  --property=BindPaths="$RUNTIME_DIR:/run/pastorai-backup" \
  --property=BindPaths="$RELEASE_DIR:/opt/pastorai-current" \
  /bin/bash -c "
    /bin/bash /opt/pastorai-current/deploy/simulated-backup.sh
    $deny_unrelated_writes
  "
test -f "$BACKUP_DIR/simulated.dump"
test -f "$RUNTIME_DIR/backup.lock"
test ! -e /root/m08-systemd-forbidden
test ! -e /etc/m08-systemd-forbidden
test ! -e /opt/m08-systemd-forbidden
printf 'SYSTEMD_SANDBOX_OK\n'
