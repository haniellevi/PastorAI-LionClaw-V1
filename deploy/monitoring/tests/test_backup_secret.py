from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "deploy/prepare-database-env.py"
BACKUP_SCRIPT = ROOT / "deploy/backup-production.sh"
HARNESS = ROOT / "deploy/monitoring/tests/backup_secret_harness.sh"
SYNTHETIC_URL = (
    "postgresql://synthetic-user:synthetic-secret@example.invalid/database"
)


def _wsl_path(path: Path) -> str:
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if wsl is None:
        pytest.skip("WSL is required for the controlled backup harness")
    return subprocess.run(
        [wsl, "-e", "wslpath", "-a", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


def test_database_env_helper_writes_restricted_file_without_output(tmp_path) -> None:
    env_file = tmp_path / "deploy.env"
    target = tmp_path / ".database-url.test"
    env_file.write_text(f"DATABASE_URL='{SYNTHETIC_URL}'\n", encoding="utf-8")
    target.touch(mode=0o600)

    result = subprocess.run(
        [sys.executable, str(HELPER), str(env_file), str(target)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert SYNTHETIC_URL not in result.stderr
    assert target.read_text(encoding="utf-8") == f"DATABASE_URL={SYNTHETIC_URL}\n"
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_backup_uses_env_file_and_always_traps_temporary_secret() -> None:
    source = BACKUP_SCRIPT.read_text(encoding="utf-8")

    assert '--env-file "${DATABASE_ENV_FILE}"' in source
    assert '-e DATABASE_URL=' not in source
    assert 'DATABASE_URL="$' not in source
    assert 'rm -f -- "${DATABASE_ENV_FILE}"' in source
    assert "trap cleanup EXIT" in source
    assert "prepare-database-env.py" in source


def test_backup_secret_never_reaches_argv_logs_or_residual_file() -> None:
    if os.name == "nt":
        wsl = shutil.which("wsl.exe") or shutil.which("wsl")
        if wsl is None:
            pytest.skip("WSL is required for the controlled backup harness")
        command = [wsl, "-u", "root", "-e", "sh", _wsl_path(HARNESS)]
    else:
        if os.geteuid() != 0:
            pytest.skip("root is required to exercise the backup root guard")
        command = ["sh", str(HARNESS)]

    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "BACKUP_SECRET_OK" in result.stdout
    assert SYNTHETIC_URL not in result.stdout
    assert SYNTHETIC_URL not in result.stderr
