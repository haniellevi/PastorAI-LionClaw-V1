from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
HARNESS = ROOT / "deploy/monitoring/tests/legacy_backup_harness.sh"
INSTALLER = ROOT / "deploy/install-legacy-backup.sh"
BACKUP = ROOT / "deploy/backup-production.sh"


def _wsl_path(path: Path) -> str:
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if wsl is None:
        pytest.skip("WSL is required for the controlled legacy backup harness")
    return subprocess.run(
        [wsl, "-e", "wslpath", "-a", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def test_legacy_backup_package_is_self_contained_and_fails_closed() -> None:
    """Exercise a complete legacy install in a disposable empty target tree."""

    if os.name == "nt":
        wsl = shutil.which("wsl.exe") or shutil.which("wsl")
        if wsl is None:
            pytest.skip("WSL is required for the controlled legacy backup harness")
        command = [wsl, "-u", "root", "-e", "bash", _wsl_path(HARNESS)]
    else:
        if os.geteuid() != 0:
            pytest.skip("root is required for the controlled legacy backup harness")
        command = ["bash", str(HARNESS)]

    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "LEGACY_BACKUP_OK" in result.stdout


def test_legacy_installer_and_runtime_use_fixed_verified_helper_contract() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    backup = BACKUP.read_text(encoding="utf-8")

    assert "prepare-database-service.py" in installer
    assert "prepare-database-service.py.sha256" in installer
    assert "PASTORAI_LEGACY_BACKUP_HELPER_DIR" in installer
    assert "rollback_install" in installer
    assert "DATABASE_SERVICE_HELPER" in backup
    assert "DATABASE_SERVICE_HELPER_SHA256" in backup
    assert "validate_database_service_helper" in backup
    assert "SCRIPT_DIR=" not in backup
