from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import sys
import time
import uuid
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
        # WSL may cold-start while Docker/Systemd tests are active; conversion
        # is still bounded but should not turn that host startup into a flake.
        timeout=30,
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
        "host=example.invalid\n"
        "port=5432\n"
        "dbname=database\n"
        "user=synthetic-user\n"
        "passfile=/run/pastorai-backup/pgpass\n"
        "sslmode=require\n"
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


def test_database_service_rejects_an_unrepresentable_service_value(tmp_path: Path) -> None:
    env_file = tmp_path / "deploy.env"
    target = tmp_path / ".pg-credentials"
    env_file.write_text(
        "DATABASE_URL=postgresql://user:password@db.example/database?application_name=%23comment\n",
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

    assert result.returncode == 1
    assert "#comment" not in result.stderr
    assert not (target / "pg_service.conf").exists()
    assert not (target / "pgpass").exists()


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
    assert source.index("unset DATABASE_URL") < source.index("SCRIPT_DIR=")
    assert 'rm -rf -- "${DATABASE_CREDENTIALS_DIR}"' in source
    assert "trap cleanup EXIT" in source
    assert "prepare-database-service.py" in source
    assert "PASTORAI_BACKUP_MONITOR_MANIFEST" in source


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
    """Inspect real pg_dump while a disposable PostgreSQL table lock holds it."""
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

    token = uuid.uuid4().hex[:12]
    network_name = f"pastorai-m08-pgdump-net-{token}"
    server_name = f"pastorai-m08-pgdump-db-{token}"
    client_name = f"pastorai-m08-pgdump-client-{token}"
    actual_url = "postgresql://synthetic-user:synthetic-secret@pg-server:5432/database?sslmode=disable"
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
        install -d -m 700 /run/pastorai-backup
        install -m 600 /input/pg_service.conf /run/pastorai-backup/pg_service.conf
        install -m 600 /input/pgpass /run/pastorai-backup/pgpass
        unset DATABASE_URL PGPASSWORD PGHOST PGPORT PGDATABASE PGUSER PGSERVICE PGSERVICEFILE PGPASSFILE
        export PGSERVICE=pastorai_backup
        export PGSERVICEFILE=/run/pastorai-backup/pg_service.conf
        pg_dump --format=custom --compress=9 --no-owner --no-acl --schema=public \
          >/dev/null 2>/tmp/pg_dump.err &
        pg_dump_pid=$!
        printf '%s\n' "$pg_dump_pid" >/tmp/pastorai-pgdump.pid
        while [ ! -f /tmp/pastorai-release ]; do
          if ! kill -0 "$pg_dump_pid" >/dev/null 2>&1; then
            wait "$pg_dump_pid" || status=$?
            printf '%s\n' "${status:-0}" >/tmp/pastorai-pgdump.status
            break
          fi
          sleep 0.05
        done
        if [ -f /tmp/pastorai-release ]; then
          kill "$pg_dump_pid" >/dev/null 2>&1 || true
          wait "$pg_dump_pid" >/dev/null 2>&1 || true
        fi
    '''
    client: subprocess.Popen[str] | None = None
    locker: subprocess.Popen[str] | None = None
    try:
        created = subprocess.run(
            [docker, "network", "create", network_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert created.returncode == 0, created.stderr
        started = subprocess.run(
            [
                docker,
                "run",
                "-d",
                "--rm",
                "--name",
                server_name,
                "--network",
                network_name,
                "--network-alias",
                "pg-server",
                "--label",
                "pastorai.m08.test=pgdump-proc",
                "--env",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                "--env",
                "POSTGRES_DB=database",
                "--env",
                "POSTGRES_USER=synthetic-user",
                "postgres:17-alpine",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert started.returncode == 0, started.stderr

        for _ in range(100):
            ready = subprocess.run(
                [docker, "exec", server_name, "pg_isready", "-U", "synthetic-user", "-d", "database"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.1)
        else:
            pytest.fail("disposable PostgreSQL did not become ready")

        initialized: subprocess.CompletedProcess[str] | None = None
        for _ in range(100):
            initialized = subprocess.run(
                [
                    docker,
                    "exec",
                    server_name,
                    "psql",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-U",
                    "synthetic-user",
                    "-d",
                    "database",
                    "-c",
                    "CREATE TABLE IF NOT EXISTS lock_target(id integer PRIMARY KEY); "
                    "INSERT INTO lock_target VALUES (1) ON CONFLICT DO NOTHING;",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if initialized.returncode == 0:
                break
            time.sleep(0.1)
        else:
            assert initialized is not None
            pytest.fail("disposable PostgreSQL did not accept initialization")
        locker = subprocess.Popen(
            [
                docker,
                "exec",
                "--env",
                "PGAPPNAME=m08-locker",
                server_name,
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "synthetic-user",
                "-d",
                "database",
                "-c",
                "BEGIN; LOCK TABLE lock_target IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(60);",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(100):
            held = subprocess.run(
                [
                    docker,
                    "exec",
                    server_name,
                    "psql",
                    "-tA",
                    "-U",
                    "synthetic-user",
                    "-d",
                    "database",
                    "-c",
                    "SELECT count(*) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
                    "WHERE c.relname = 'lock_target' AND l.mode = 'AccessExclusiveLock' AND l.granted;",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if held.returncode == 0 and held.stdout.strip() == "1":
                break
            time.sleep(0.1)
        else:
            pytest.fail("disposable PostgreSQL table lock was not acquired")

        client = subprocess.Popen(
            [
                docker,
                "run",
                "--rm",
                "--name",
                client_name,
                "--network",
                network_name,
                "--label",
                "pastorai.m08.test=pgdump-proc",
                "--mount",
                f"type=bind,src={credentials_dir.resolve()},dst=/input,readonly",
                "postgres:17-alpine",
                "/bin/sh",
                "-ec",
                inspection_script,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(100):
            waiting = subprocess.run(
                [
                    docker,
                    "exec",
                    server_name,
                    "psql",
                    "-tA",
                    "-U",
                    "synthetic-user",
                    "-d",
                    "database",
                    "-c",
                    "SELECT count(*) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
                    "WHERE c.relname = 'lock_target' AND l.mode = 'AccessShareLock' AND NOT l.granted;",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if waiting.returncode == 0 and int(waiting.stdout.strip() or "0") >= 1:
                break
            completed = subprocess.run(
                [
                    docker,
                    "exec",
                    client_name,
                    "/bin/sh",
                    "-c",
                    "test -f /tmp/pastorai-pgdump.status",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            if completed.returncode == 0:
                pytest.fail("pg_dump exited before reaching the deterministic table lock")
            if client.poll() is not None:
                pytest.fail("pg_dump exited before reaching the deterministic table lock")
            time.sleep(0.1)
        else:
            pytest.fail("pg_dump did not reach the deterministic table lock")

        result = subprocess.run(
            [
                docker,
                "exec",
                client_name,
                "/bin/sh",
                "-ec",
                r'''
                    test -r /tmp/pastorai-pgdump.pid
                    pid=$(cat /tmp/pastorai-pgdump.pid)
                    test -r "/proc/$pid/cmdline"
                    test -r "/proc/$pid/environ"
                    for proc in /proc/[0-9]*; do
                      [ -r "$proc/cmdline" ] || continue
                      printf '%s\n' "---PID:${proc##*/}:ARGV---"
                      tr '\000' '\n' <"$proc/cmdline"
                      printf '%s\n' "---PID:${proc##*/}:ENV---"
                      tr '\000' '\n' <"$proc/environ"
                    done
                ''',
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "pg_dump" in result.stdout
        assert "PGSERVICE=pastorai_backup" in result.stdout
        assert "PGSERVICEFILE=/run/pastorai-backup/pg_service.conf" in result.stdout
        assert actual_url not in result.stdout
        assert "synthetic-secret" not in result.stdout
        assert actual_url not in result.stderr
        assert "synthetic-secret" not in result.stderr
    finally:
        subprocess.run(
            [docker, "exec", client_name, "/bin/sh", "-c", "touch /tmp/pastorai-release"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        subprocess.run(
            [
                docker,
                "exec",
                server_name,
                "psql",
                "-tA",
                "-U",
                "synthetic-user",
                "-d",
                "database",
                "-c",
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = 'm08-locker';",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        for process in (client, locker):
            if process is None:
                continue
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=10)
        for container in (client_name, server_name):
            subprocess.run(
                [docker, "rm", "-f", container],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        subprocess.run(
            [docker, "network", "rm", network_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
