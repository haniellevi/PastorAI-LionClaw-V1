#!/usr/bin/env python3
"""Create temporary libpq credentials without exposing ``DATABASE_URL``.

The backup process receives only a libpq service name and a bind-mounted,
mode-0600 credentials directory.  The password lives in a ``.pgpass``-format
file; neither the full URL nor the password becomes an argument or environment
variable of ``pg_dump``.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit


_SERVICE_NAME = "pastorai_backup"
_CONTAINER_PASSFILE = "/run/pastorai-backup/pgpass"
_ALLOWED_QUERY_OPTIONS = frozenset(
    {
        "application_name",
        "channel_binding",
        "connect_timeout",
        "gssencmode",
        "keepalives",
        "keepalives_count",
        "keepalives_idle",
        "keepalives_interval",
        "options",
        "require_auth",
        "sslcert",
        "sslcrl",
        "sslcrldir",
        "sslkey",
        "sslmode",
        "sslrootcert",
        "sslsni",
        "target_session_attrs",
    }
)


def _database_url(env_file: Path) -> str:
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "DATABASE_URL":
            continue
        value = value.strip().strip('"').strip("'")
        if not value or any(character in value for character in "\r\n\x00"):
            raise ValueError("DATABASE_URL invalida")
        return value
    raise ValueError("DATABASE_URL ausente")


def _safe_value(value: str) -> str:
    if not value or any(character in value for character in "\r\n\x00"):
        raise ValueError("componente de conexao invalido")
    return value


def _service_value(value: str) -> str:
    """Quote a libpq service-file value without allowing line injection."""
    return "'" + _safe_value(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _pgpass_value(value: str) -> str:
    """Escape the two separators defined by the libpq ``.pgpass`` format."""
    return _safe_value(value).replace("\\", "\\\\").replace(":", "\\:")


def _connection_parts(url: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL invalida")
    if parsed.hostname is None or parsed.username is None or parsed.password is None:
        raise ValueError("DATABASE_URL incompleta")
    try:
        port = str(parsed.port or 5432)
    except ValueError as exc:
        raise ValueError("DATABASE_URL invalida") from exc

    raw_database = parsed.path.removeprefix("/")
    if not raw_database or "/" in raw_database:
        raise ValueError("DATABASE_URL invalida")
    connection = {
        "host": _safe_value(unquote(parsed.hostname)),
        "port": _safe_value(port),
        "dbname": _safe_value(unquote(raw_database)),
        "user": _safe_value(unquote(parsed.username)),
        "password": _safe_value(unquote(parsed.password)),
    }
    options: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key in {"password", "passfile", "service", "servicefile"}:
            # Credentials always stay in the generated .pgpass file; allowing
            # an arbitrary passfile/service would bypass that boundary.
            continue
        if key not in _ALLOWED_QUERY_OPTIONS:
            continue
        options.append((key, _safe_value(value)))
    return connection, options


def _write_restricted(path: Path, content: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as output:
            output.write(content)
            output.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_database_service(env_file: Path, target_dir: Path) -> None:
    """Write libpq ``pg_service.conf`` and ``pgpass`` files to ``target_dir``."""
    # ``stat`` follows a symlink, which would let an attacker redirect the
    # credentials outside the directory created by the backup trap.  Reject the
    # link itself before opening either mode-0600 file.
    directory_stat = target_dir.lstat()
    if not stat.S_ISDIR(directory_stat.st_mode) or stat.S_ISLNK(directory_stat.st_mode):
        raise ValueError("diretorio de credenciais invalido")
    os.chmod(target_dir, 0o700)

    connection, options = _connection_parts(_database_url(env_file))
    service = target_dir / "pg_service.conf"
    passfile = target_dir / "pgpass"
    service_lines = [f"[{_SERVICE_NAME}]"]
    for key in ("host", "port", "dbname", "user"):
        service_lines.append(f"{key} = {_service_value(connection[key])}")
    service_lines.append(f"passfile = {_service_value(_CONTAINER_PASSFILE)}")
    for key, value in options:
        service_lines.append(f"{key} = {_service_value(value)}")
    pgpass_line = ":".join(
        _pgpass_value(connection[key])
        for key in ("host", "port", "dbname", "user", "password")
    )

    try:
        _write_restricted(service, "\n".join(service_lines) + "\n")
        _write_restricted(passfile, pgpass_line + "\n")
    except Exception:
        service.unlink(missing_ok=True)
        passfile.unlink(missing_ok=True)
        raise


def main() -> int:
    if len(sys.argv) != 3:
        print("uso: prepare-database-service.py ENV_FILE TARGET_DIR", file=sys.stderr)
        return 2
    try:
        write_database_service(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, UnicodeError, ValueError) as exc:
        # Error classes help operations while values, paths and credentials stay private.
        print(
            f"falha ao preparar credencial do banco ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
