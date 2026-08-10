from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "deploy/prepare-database-service.py"
BACKUP_SCRIPT = ROOT / "deploy/backup-production.sh"
HARNESS = ROOT / "deploy/monitoring/tests/backup_secret_harness.sh"
SYNTHETIC_URL = (
    "postgresql://synthetic-user:synthetic-secret@example.invalid/database?sslmode=require"
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


def test_database_service_helper_writes_restricted_libpq_files_without_output(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "deploy.env"
    target = tmp_path / ".pg-credentials"
    env_file.write_text(f"DATABASE_URL='{SYNTHETIC_URL}'\n", encoding="utf-8")
    target.mkdir(mode=0o700)

    result = subprocess.run(
        [sys.executable, str(HELPER), str(env_file), str(target)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    service = target / "pg_service.conf"
    passfile = target / "pgpass"
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert SYNTHETIC_URL not in result.stderr
    assert "synthetic-secret" not in service.read_text(encoding="utf-8")
    assert service.read_text(encoding="utf-8") == (
        "[pastorai_backup]\n"
        "host = 'example.invalid'\n"
        "port = '5432'\n"
        "dbname = 'database'\n"
        "user = 'synthetic-user'\n"
        "passfile = '/run/pastorai-backup/pgpass'\n"
        "sslmode = 'require'\n"
    )
    assert passfile.read_text(encoding="utf-8") == (
        "example.invalid:5432:database:synthetic-user:synthetic-secret\n"
    )
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o700
        assert stat.S_IMODE(service.stat().st_mode) == 0o600
        assert stat.S_IMODE(passfile.stat().st_mode) == 0o600


def test_database_service_escapes_special_values_for_libpq(tmp_path: Path) -> None:
    env_file = tmp_path / "deploy.env"
    target = tmp_path / ".pg-credentials"
    env_file.write_text(
        "DATABASE_URL=postgresql://user%3Aname:pass%3Aword%5Cvalue@db.example:6543/db%3Aname?sslmode=require\n",
        encoding="utf-8",
    )
    target.mkdir(mode=0o700)

    result = subprocess.run(
        [sys.executable, str(HELPER), str(env_file), str(target)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert (target / "pgpass").read_text(encoding="utf-8") == (
        "db.example:6543:db\\:name:user\\:name:pass\\:word\\\\value\n"
    )


def test_database_service_rejects_a_symlinked_credentials_directory(tmp_path: Path) -> None:
    if os.name == "nt":
        wsl = shutil.which("wsl.exe") or shutil.which("wsl")
        if wsl is None:
            pytest.skip("WSL is required to create a POSIX symlink safely")
        helper = _wsl_path(HELPER)
        script = f"""
            set -eu
            sandbox=$(mktemp -d)
            trap 'rm -rf -- "$sandbox"' EXIT
            env_file="$sandbox/deploy.env"
            target="$sandbox/safe-target"
            link="$sandbox/.pg-credentials"
            printf '%s\\n' {shlex.quote(f'DATABASE_URL={SYNTHETIC_URL}')} >"$env_file"
            mkdir -m 700 "$target"
            ln -s "$target" "$link"
            if python3 {shlex.quote(helper)} "$env_file" "$link" >/dev/null 2>"$sandbox/error"; then
              exit 61
            fi
            if grep -Fq {shlex.quote(SYNTHETIC_URL)} "$sandbox/error"; then
              exit 62
            fi
            test ! -e "$target/pg_service.conf"
            test ! -e "$target/pgpass"
            printf 'SYMLINK_REJECTED\\n'
        """
        result = subprocess.run(
            [wsl, "-u", "root", "-e", "sh", "-lc", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "SYMLINK_REJECTED" in result.stdout
        return

    env_file = tmp_path / "deploy.env"
    safe_target = tmp_path / "safe-target"
    unsafe_link = tmp_path / ".pg-credentials"
    env_file.write_text(f"DATABASE_URL='{SYNTHETIC_URL}'\n", encoding="utf-8")
    safe_target.mkdir(mode=0o700)
    try:
        unsafe_link.symlink_to(safe_target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable in this local test environment")

    result = subprocess.run(
        [sys.executable, str(HELPER), str(env_file), str(unsafe_link)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 1
    assert SYNTHETIC_URL not in result.stderr
    assert not (safe_target / "pg_service.conf").exists()
    assert not (safe_target / "pgpass").exists()


def test_backup_uses_libpq_files_and_always_traps_temporary_secret() -> None:
    source = BACKUP_SCRIPT.read_text(encoding="utf-8")

    assert "--env-file" not in source
    assert "--dbname=\"$DATABASE_URL\"" not in source
    assert "--mount \"type=bind,src=${DATABASE_CREDENTIALS_DIR}" in source
    assert "--env PGSERVICE=pastorai_backup" in source
    assert "--env PGSERVICEFILE=/run/pastorai-backup/pg_service.conf" in source
    assert "unset DATABASE_URL PGPASSWORD" in source
    assert 'rm -rf -- "${DATABASE_CREDENTIALS_DIR}"' in source
    assert "trap cleanup EXIT" in source
    assert "prepare-database-service.py" in source


def test_backup_secret_never_reaches_pgdump_proc_argv_environment_logs_or_residual_file() -> None:
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


def test_actual_pgdump_has_no_database_url_or_password_in_proc(tmp_path: Path) -> None:
    """Inspect the real pinned-image pg_dump process through container /proc."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker is required for the actual pg_dump process harness")
    available = subprocess.run(
        [docker, "info"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )
    if available.returncode != 0:
        pytest.skip("Docker daemon is unavailable for the actual pg_dump process harness")

    actual_url = (
        "postgresql://synthetic-user:synthetic-secret@127.0.0.1:6543/database?connect_timeout=10"
    )
    env_file = tmp_path / "deploy.env"
    credentials_dir = tmp_path / ".pg-credentials"
    env_file.write_text(f"DATABASE_URL={actual_url}\n", encoding="utf-8")
    credentials_dir.mkdir(mode=0o700)
    prepared = subprocess.run(
        [sys.executable, str(HELPER), str(env_file), str(credentials_dir)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert prepared.returncode == 0, prepared.stderr

    inspection_script = r'''
        busybox nc -l -p 6543 >/dev/null 2>&1 &
        listener=$!
        cleanup() {
          kill "$pg_dump_pid" "$listener" >/dev/null 2>&1 || true
          wait "$pg_dump_pid" >/dev/null 2>&1 || true
          wait "$listener" >/dev/null 2>&1 || true
        }
        trap cleanup EXIT INT TERM
        pg_dump --format=custom --compress=9 --no-owner --no-acl --schema=public \
          >/dev/null 2>/tmp/pg_dump.err &
        pg_dump_pid=$!
        for _ in $(seq 1 50); do
          if [ -r "/proc/$pg_dump_pid/cmdline" ]; then
            break
          fi
          sleep 0.05
        done
        test -r "/proc/$pg_dump_pid/cmdline"
        printf '%s\n' '---ARGV---'
        tr '\000' '\n' <"/proc/$pg_dump_pid/cmdline"
        printf '%s\n' '---ENV---'
        tr '\000' '\n' <"/proc/$pg_dump_pid/environ"
    '''
    result = subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "--mount",
            f"type=bind,src={credentials_dir.resolve()},dst=/run/pastorai-backup,readonly",
            "--env",
            "PGSERVICE=pastorai_backup",
            "--env",
            "PGSERVICEFILE=/run/pastorai-backup/pg_service.conf",
            "postgres:17-alpine",
            "/bin/sh",
            "-ec",
            inspection_script,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "pg_dump" in result.stdout
    assert "PGSERVICE=pastorai_backup" in result.stdout
    assert "PGSERVICEFILE=/run/pastorai-backup/pg_service.conf" in result.stdout
    assert actual_url not in result.stdout
    assert "synthetic-secret" not in result.stdout
    assert actual_url not in result.stderr
    assert "synthetic-secret" not in result.stderr
