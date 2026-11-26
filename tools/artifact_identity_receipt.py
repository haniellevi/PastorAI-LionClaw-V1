"""Compare supplied artifact identities offline; never observe or authenticate an installation."""

import json
import os
import re
import stat
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

_EVIDENCE_FIELDS = {"component", "revision", "digest", "evidence_id", "evidence_at"}
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _utc_timestamp(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo == UTC and value == parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def _evidence_id(value):
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _valid_evidence(value, component):
    if not isinstance(value, dict) or set(value) != _EVIDENCE_FIELDS:
        return None
    if (
        value["component"] != component
        or not isinstance(value["revision"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", value["revision"])
        or not isinstance(value["digest"], str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", value["digest"])
        or not _evidence_id(value["evidence_id"])
        or not _utc_timestamp(value["evidence_at"])
    ):
        return None
    return dict(value)


def compare_evidence(payload):
    """Return only validated fields; correspondence is equality of supplied data."""
    if not isinstance(payload, dict) or set(payload) - {"component", "expected", "observed"}:
        raise ValueError("invalid receipt input")
    component = payload.get("component")
    if component not in ("backend", "frontend"):
        raise ValueError("invalid component")
    expected = _valid_evidence(payload.get("expected"), component)
    observed = _valid_evidence(payload.get("observed"), component)
    status = "desconhecido"
    if expected is not None and observed is not None:
        status = (
            "correspondente"
            if (expected["revision"], expected["digest"]) == (observed["revision"], observed["digest"])
            else "divergente"
        )
    return {
        "schema_version": 1,
        "component": component,
        "expected": expected,
        "observed": observed,
        "status": status,
    }


def write_receipt(payload, directory):
    """Persist an exclusive, private JSON receipt in an existing private directory."""
    receipt = compare_evidence(payload)
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("expected an absolute private directory")
    directory = directory.resolve(strict=True)
    metadata = directory.stat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or directory.is_relative_to(_PROJECT_ROOT)
    ):
        raise ValueError("expected an owned private directory outside the project")

    receipt_id = str(uuid4())
    receipt["receipt_id"] = receipt_id
    receipt["recorded_at"] = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    path = directory / f"{receipt_id}.json"
    # Publish the complete file atomically. A duplicate ID fails without replacing the prior receipt.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory) as pending:
        os.fchmod(pending.fileno(), 0o600)
        json.dump(receipt, pending, indent=2)
        pending.write("\n")
        pending.flush()
        os.fsync(pending.fileno())
        os.link(pending.name, path)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def _unique_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("ambiguous JSON fields")
    return result


def main():
    try:
        if len(sys.argv) != 2:
            raise ValueError("expected a private directory")
        write_receipt(json.load(sys.stdin, object_pairs_hook=_unique_fields), sys.argv[1])
    except (OSError, ValueError):
        print("Não foi possível registrar o recibo privado.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
