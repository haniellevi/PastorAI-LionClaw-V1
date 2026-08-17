from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
HARNESS = ROOT / "deploy/monitoring/tests/systemd_sandbox_harness.sh"


def _wsl_path(path: Path) -> str:
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if wsl is None:
        pytest.skip("WSL with systemd is required for the controlled sandbox harness")
    return subprocess.run(
        [wsl, "-e", "wslpath", "-a", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


def test_systemd_units_have_a_controlled_writable_surface() -> None:
    if os.name == "nt":
        wsl = shutil.which("wsl.exe") or shutil.which("wsl")
        if wsl is None:
            pytest.skip("WSL with systemd is required for the controlled sandbox harness")
        deploy = _wsl_path(ROOT / "deploy")
        relative = HARNESS.relative_to(ROOT / "deploy").as_posix()
        script = f"""
            set -eu
            sandbox=$(mktemp -d)
            trap 'rm -rf -- "$sandbox"' EXIT
            mkdir -p "$sandbox/deploy"
            cp -a {shlex.quote(deploy)}/. "$sandbox/deploy/"
            find "$sandbox/deploy" -type f -name '*.sh' -exec sed -i 's/\\r$//' {{}} +
            exec bash "$sandbox/deploy/{relative}"
        """
        command = [wsl, "-u", "root", "-e", "sh", "-lc", script]
    else:
        if os.geteuid() != 0:
            pytest.skip("root with a running systemd manager is required")
        command = ["bash", str(HARNESS)]

    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "SYSTEMD_SANDBOX_OK" in result.stdout
