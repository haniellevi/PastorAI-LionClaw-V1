from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
HARNESS = ROOT / "deploy/monitoring/tests/install_harness.sh"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _run_harness(*arguments: str) -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        wsl = shutil.which("wsl.exe") or shutil.which("wsl")
        if wsl is None:
            pytest.skip("WSL is required for the controlled installer harness")
        converted = subprocess.run(
            [wsl, "-e", "wslpath", "-a", str(HARNESS)],
            check=True,
            capture_output=True,
            text=True,
            # WSL can cold-start while controlled Docker/Systemd checks run.
            # Keep the conversion bounded without making the test timing-flaky.
            timeout=30,
        ).stdout.strip()
        command = [wsl, "-e", "sh", converted, *arguments]
    else:
        shell = shutil.which("sh")
        if shell is None:
            pytest.skip("POSIX sh is required for the installer harness")
        command = [shell, str(HARNESS), *arguments]
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_root_backup_is_kept_privileged_and_monitor_uses_sanitized_manifest() -> None:
    expected = "/root/pastorai-backups"
    privileged_files = (
        "deploy/backup-production.sh",
        "deploy/monitoring/install.sh",
        "deploy/monitoring/systemd/pastorai-backup.service",
    )

    for relative in privileged_files:
        assert expected in _read(relative), relative
        assert "/var/backups/pastorai" not in _read(relative), relative
    monitor = _read("deploy/monitoring/production_monitor.py")
    monitor_unit = _read("deploy/monitoring/systemd/pastorai-monitor.service")
    assert expected not in monitor
    assert expected not in monitor_unit
    assert "/var/lib/pastorai-backup/backup-status.json" in monitor
    assert "/var/lib/pastorai-backup/backup-status.json" in monitor_unit


def test_units_use_strict_filesystem_sandbox_and_explicit_privilege_boundaries() -> None:
    backup_unit = _read("deploy/monitoring/systemd/pastorai-backup.service")
    monitor_unit = _read("deploy/monitoring/systemd/pastorai-monitor.service")

    assert "ProtectHome=read-only" in backup_unit
    assert "ProtectSystem=strict" in backup_unit
    assert "ReadWritePaths=/root/pastorai-backups" in backup_unit
    assert "RuntimeDirectory=pastorai-backup" in backup_unit
    assert "Environment=PASTORAI_BACKUP_LOCK_FILE=/run/pastorai-backup/backup.lock" in backup_unit
    assert "CapabilityBoundingSet=" in backup_unit
    assert "PrivateDevices=true" in backup_unit
    assert "RestrictNamespaces=true" in backup_unit
    assert "ReadOnlyPaths=/opt/pastorai-current" in backup_unit

    assert "DynamicUser=yes" in monitor_unit
    assert "User=root" not in monitor_unit
    assert "Group=root" not in monitor_unit
    assert "ProtectHome=true" in monitor_unit
    assert "ProtectSystem=strict" in monitor_unit
    assert "ReadOnlyPaths=-/var/lib/pastorai-backup/backup-status.json" in monitor_unit
    assert "ReadWritePaths=/var/lib/pastorai-monitor" in monitor_unit
    assert "StateDirectory=pastorai-monitor" in monitor_unit
    assert (
        "InaccessiblePaths=/root /home -/run/docker.sock -/var/run/docker.sock "
        "-/opt/pastorai-current/deploy/.env /etc/shadow"
    ) in monitor_unit
    assert "/opt/pastorai-current/deploy/.env" in monitor_unit
    assert "CapabilityBoundingSet=" in monitor_unit
    assert "PrivateDevices=true" in monitor_unit
    assert "RestrictNamespaces=true" in monitor_unit


def test_installer_preserves_legacy_cron_and_requires_explicit_timer_opt_in() -> None:
    install = _read("deploy/monitoring/install.sh")

    assert "PASTORAI_BACKUP_TIMER_MODE:-preserve" in install
    assert "legacy_backup_schedule_present" in install
    assert 'if [ "$BACKUP_TIMER_MODE" = enable ]' in install
    assert "systemctl enable --now pastorai-monitor.timer" in install
    assert (
        "systemctl enable --now pastorai-backup.timer pastorai-monitor.timer"
        not in install
    )
    assert "Cron legado detectado" in install
    assert '"$INSTALL_BIN" -d -m 0700 "$STATE_DIR" "$BACKUP_ROOT"' in install
    assert '"$INSTALL_BIN" -d -m 0755 "$MANIFEST_DIR"' in install
    assert "prepare_monitor_config.py" in install


def test_duplicate_scheduler_preflight_runs_before_install_writes() -> None:
    install = _read("deploy/monitoring/install.sh")

    duplicate_guard = install.index('if [ "$LEGACY_BACKUP_SCHEDULE" -eq 1 ]')
    guard_end = install.index("fi", duplicate_guard)
    duplicate_guard_text = install[duplicate_guard:guard_end]
    assert '"$BACKUP_TIMER_ENABLED" -eq 1' in duplicate_guard_text
    assert '"$BACKUP_TIMER_ACTIVE" -eq 1' in duplicate_guard_text
    first_install_write = install.index(
        '"$INSTALL_BIN" -d -m 0755 "$INSTALL_DIR"'
    )

    assert duplicate_guard < first_install_write


@pytest.mark.parametrize("cron", [0, 1])
@pytest.mark.parametrize("enabled", [0, 1])
@pytest.mark.parametrize("active", [0, 1])
def test_scheduler_matrix_aborts_every_cron_timer_duplicate(
    cron: int,
    enabled: int,
    active: int,
) -> None:
    expected = "fail" if cron and (enabled or active) else "pass"
    result = _run_harness(
        "matrix",
        str(cron),
        str(enabled),
        str(active),
        "preserve",
        expected,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "MATRIX_OK" in result.stdout


def test_explicit_timer_enable_refuses_legacy_cron_before_writes() -> None:
    result = _run_harness("matrix", "1", "0", "0", "enable", "fail")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "MATRIX_OK" in result.stdout


@pytest.mark.parametrize(
    ("failure_step", "mode"),
    [
        ("copy", "preserve"),
        ("daemon-reload", "preserve"),
        ("unit-load", "preserve"),
        ("enable-monitor", "preserve"),
        ("enable-backup", "enable"),
    ],
)
def test_installer_rolls_back_files_modes_and_timer_state(
    failure_step: str,
    mode: str,
) -> None:
    result = _run_harness("rollback", failure_step, mode)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"ROLLBACK_OK step={failure_step}" in result.stdout


def test_installer_is_idempotent_without_legacy_cron() -> None:
    result = _run_harness("idempotent")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "IDEMPOTENT_OK" in result.stdout


def test_operational_degradation_does_not_roll_back_a_valid_timer_install() -> None:
    result = _run_harness("operational")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OPERATIONAL_DEGRADATION_INSTALL_OK" in result.stdout
