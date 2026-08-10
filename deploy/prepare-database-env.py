#!/usr/bin/env python3
"""Write DATABASE_URL to an already-created mode-0600 Docker env file."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _database_url(env_file: Path) -> str:
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "DATABASE_URL":
            continue
        value = value.strip().strip('"').strip("'")
        if not value or "\n" in value or "\r" in value:
            raise ValueError("DATABASE_URL invalida")
        return value
    raise ValueError("DATABASE_URL ausente")


def write_database_env(env_file: Path, target: Path) -> None:
    value = _database_url(env_file)
    descriptor = os.open(target, os.O_WRONLY | os.O_TRUNC)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as output:
            output.write(f"DATABASE_URL={value}\n")
            output.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    if len(sys.argv) != 3:
        print("uso: prepare-database-env.py ENV_FILE TARGET", file=sys.stderr)
        return 2
    try:
        write_database_env(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, UnicodeError, ValueError) as exc:
        # The error class is operationally useful; paths and values stay private.
        print(f"falha ao preparar credencial do banco ({type(exc).__name__})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
