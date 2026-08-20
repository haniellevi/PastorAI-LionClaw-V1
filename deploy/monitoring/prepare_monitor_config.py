#!/usr/bin/env python3
"""Derive the monitor's small systemd environment from the deployment file.

This program runs only during the privileged installer transaction.  The
result intentionally excludes the application's database, JWT and provider
credentials other than the Brevo values required for alerts.  The monitor
process itself receives this allowlist from systemd and never opens ``.env``.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


_BREVO_KEYS = (
    "BREVO_API_KEY",
    "BREVO_API_URL",
    "BREVO_FROM_EMAIL",
    "BREVO_FROM_NAME",
)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _systemd_value(value: str) -> str:
    if any(character in value for character in "\r\n\x00"):
        raise ValueError("valor de monitor invalido")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_config(
    application_values: dict[str, str], *, alert_email: str, manifest_path: str
) -> dict[str, str]:
    """Build the exact non-secret monitor environment, never copying ``.env``."""
    values = {
        "MONITOR_ALERT_EMAIL": alert_email,
        "MONITOR_BACKUP_MANIFEST": manifest_path,
        "MONITOR_BACKUP_MAX_AGE_HOURS": "30",
        "MONITOR_REMINDER_HOURS": "6",
        "MONITOR_RETRY_HOURS": "1",
        "MONITOR_AMBIGUOUS_RETRY_HOURS": "6",
        "MONITOR_LOCAL_API_BASE": "http://127.0.0.1:8000",
        "BREVO_API_URL": "https://api.brevo.com/v3",
        "BREVO_FROM_NAME": "Igreja 12",
    }
    for key in _BREVO_KEYS:
        configured = application_values.get(key)
        if configured:
            values[key] = configured
    return values


def write_config(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", text=True
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for key in sorted(values):
                handle.write(f"{key}={_systemd_value(values[key])}\n")
        temporary.replace(path)
        os.chmod(path, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main(arguments: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if arguments is None else arguments)
    if len(args) != 4:
        print(
            "uso: prepare_monitor_config.py APP_ENV ALERT_EMAIL MANIFEST DESTINO",
            file=sys.stderr,
        )
        return 2
    env_file, alert_email, manifest_path, destination = (Path(args[0]), args[1], args[2], Path(args[3]))
    try:
        values = build_config(
            parse_env_file(env_file),
            alert_email=alert_email,
            manifest_path=manifest_path,
        )
        write_config(destination, values)
    except (OSError, UnicodeError, ValueError):
        print("nao foi possivel preparar a configuracao do monitor", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - command entry point
    raise SystemExit(main())
