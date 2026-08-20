#!/usr/bin/env bash
set -euo pipefail

TEST_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
MONITOR_UNIT_SOURCE="$TEST_DIR/../systemd/pastorai-monitor.service"
BACKUP_UNIT_SOURCE="$TEST_DIR/../systemd/pastorai-backup.service"
SANDBOX=$(mktemp -d "${TMPDIR:-/var/tmp}/pastorai-systemd-sandbox.XXXXXX")
cleanup() {
  for path in "${STATE_PATH:-}" "${MANIFEST_DIR:-}" "${BACKUP_DIR:-}" "${RUNTIME_DIR:-}" "$SANDBOX"; do
    [ -n "$path" ] || continue
    case "$path" in
      /var/lib/pastorai-m08-*|/root/pastorai-m08-*|/run/pastorai-m08-*|"$SANDBOX")
        rm -rf -- "$path"
        ;;
      *)
        echo "refusing to remove unexpected test path" >&2
        ;;
    esac
  done
}
trap cleanup EXIT INT TERM

UNITS_DIR="$SANDBOX/units"
MANIFEST_DIR="/var/lib/pastorai-m08-manifest-$RANDOM-$$"
BACKUP_DIR="/root/pastorai-m08-backup-$RANDOM-$$"
RUNTIME_DIR="/run/pastorai-m08-backup-$RANDOM-$$"
RELEASE_DIR="$SANDBOX/release"
STATE_NAME="pastorai-m08-monitor-$RANDOM-$$"
STATE_PATH="/var/lib/$STATE_NAME"
mkdir -p "$UNITS_DIR" "$MANIFEST_DIR" "$BACKUP_DIR" "$RUNTIME_DIR" "$RELEASE_DIR/deploy"
printf '%s\n' '{"version":1,"status":"verified","archive":"pastorai-backup-20260810T120000Z.tar.gz","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","bytes":1,"completed_at":"2026-08-10T12:00:00Z"}' >"$MANIFEST_DIR/backup-status.json"
chmod 0755 "$MANIFEST_DIR"
chmod 0644 "$MANIFEST_DIR/backup-status.json"
cat >"$RELEASE_DIR/deploy/simulated-backup.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'simulated backup\n' >"$M08_BACKUP_DIR/simulated.dump"
printf '%s\n' '{"version":1,"status":"verified"}' >"$M08_MANIFEST_DIR/backup-status.json"
: >"$M08_RUNTIME_DIR/backup.lock"
EOF
chmod 0755 "$RELEASE_DIR/deploy/simulated-backup.sh"
cp "$MONITOR_UNIT_SOURCE" "$UNITS_DIR/pastorai-monitor.service"
cp "$BACKUP_UNIT_SOURCE" "$UNITS_DIR/pastorai-backup.service"
chmod 0644 "$UNITS_DIR/"*.service

systemd-analyze verify "$UNITS_DIR/pastorai-monitor.service" "$UNITS_DIR/pastorai-backup.service"
systemd-analyze security --offline=yes "$UNITS_DIR/pastorai-monitor.service" >/dev/null
systemd-analyze security --offline=yes "$UNITS_DIR/pastorai-backup.service" >/dev/null

common_properties=(
  --property=NoNewPrivileges=yes
  --property=CapabilityBoundingSet=
  --property=AmbientCapabilities=
  --property=PrivateTmp=yes
  --property=PrivateDevices=yes
  --property=PrivateMounts=yes
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
systemd-run --wait --collect --unit="$monitor_unit" \
  "${common_properties[@]}" \
  --property=DynamicUser=yes \
  --property=ProtectHome=yes \
  --property="StateDirectory=$STATE_NAME" \
  --property="ReadOnlyPaths=$MANIFEST_DIR/backup-status.json" \
  --property="ReadWritePaths=$STATE_PATH" \
  --property='InaccessiblePaths=/root /home -/run/docker.sock -/var/run/docker.sock -/opt/pastorai-current/deploy/.env /etc/shadow' \
  /bin/bash -c "
    test \"\$(id -u)\" -ne 0
    test ! -r /root
    test ! -r /root/.ssh
    test ! -r /etc/shadow
    test ! -r /opt/pastorai-current/deploy/.env
    test ! -e /run/docker.sock
    test ! -e /var/run/docker.sock
    grep -Fq '\"status\":\"verified\"' $MANIFEST_DIR/backup-status.json
    if touch $MANIFEST_DIR/forbidden 2>/dev/null; then exit 34; fi
    touch $STATE_PATH/allowed
    $deny_unrelated_writes
  "
backup_unit="pastorai-m08-backup-$RANDOM-$$"
systemd-run --wait --collect --unit="$backup_unit" \
  "${common_properties[@]}" \
  --property=User=root \
  --property=ProtectHome=read-only \
  --property="ReadWritePaths=$BACKUP_DIR $MANIFEST_DIR $RUNTIME_DIR" \
  --setenv="M08_BACKUP_DIR=$BACKUP_DIR" \
  --setenv="M08_MANIFEST_DIR=$MANIFEST_DIR" \
  --setenv="M08_RUNTIME_DIR=$RUNTIME_DIR" \
  /bin/bash -c "
    /bin/bash $RELEASE_DIR/deploy/simulated-backup.sh
    test -f $BACKUP_DIR/simulated.dump
    test -f $MANIFEST_DIR/backup-status.json
    test -f $RUNTIME_DIR/backup.lock
    $deny_unrelated_writes
  "
test ! -e /root/m08-systemd-forbidden
test ! -e /etc/m08-systemd-forbidden
test ! -e /opt/m08-systemd-forbidden
printf 'SYSTEMD_SANDBOX_OK\n'
