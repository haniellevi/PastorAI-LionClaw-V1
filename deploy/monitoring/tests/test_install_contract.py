from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_backup_root_is_canonical_across_script_monitor_and_units() -> None:
    expected = "/root/pastorai-backups"
    files = (
        "deploy/backup-production.sh",
        "deploy/monitoring/production_monitor.py",
        "deploy/monitoring/install.sh",
        "deploy/monitoring/systemd/pastorai-backup.service",
        "deploy/monitoring/systemd/pastorai-monitor.service",
    )

    for relative in files:
        assert expected in _read(relative), relative
        assert "/var/backups/pastorai" not in _read(relative), relative


def test_units_keep_home_sandbox_and_open_only_canonical_backup_path() -> None:
    backup_unit = _read("deploy/monitoring/systemd/pastorai-backup.service")
    monitor_unit = _read("deploy/monitoring/systemd/pastorai-monitor.service")

    assert "ProtectHome=read-only" in backup_unit
    assert "ReadWritePaths=/root/pastorai-backups" in backup_unit
    assert "ProtectHome=read-only" in monitor_unit
    assert "ReadOnlyPaths=/root/pastorai-backups" in monitor_unit
    assert "ReadWritePaths=/var/lib/pastorai-monitor" in monitor_unit


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
    assert 'install -d -m 0700 /var/lib/pastorai-monitor "$BACKUP_ROOT"' in install


def test_duplicate_scheduler_preflight_runs_before_install_writes() -> None:
    install = _read("deploy/monitoring/install.sh")

    duplicate_guard = install.index(
        'if [ "$LEGACY_BACKUP_SCHEDULE" -eq 1 ] '
        '&& [ "$BACKUP_TIMER_ENABLED" -eq 1 ]'
    )
    first_install_write = install.index('install -d -m 0755 "$INSTALL_DIR"')

    assert duplicate_guard < first_install_write
