#!/usr/bin/env python3
"""Expose immutable source evidence for catalog-bound local consumers.

This module is deliberately additive.  The historical catalog verifier is a
byte-pinned dependency of the environment-attestation executor and therefore
must not be modified merely to expose a new consumer API.  The snapshot below
reuses that verifier's strict schema, catalog, and stable-file checks without
turning source evidence into a live-database trust anchor.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import sys
from types import ModuleType


VERIFIER_PATH = Path(__file__).absolute().with_name(
    "verify_migration_catalog_head.py"
)
CATALOG_VERIFIER_SHA256 = (
    "2fe1a93bf9c9116426683e7fd86c4f7b7c20753f7ce11a8282d9ca06087ac30d"
)
MAX_VERIFIER_BYTES = 4_194_304
_CATALOG_MODULE_NAME = (
    "_pastorai_validated_migration_catalog_head_verifier_"
    + hashlib.sha256(__name__.encode("utf-8")).hexdigest()[:16]
)
_STABLE_STAT_FIELDS = (
    "st_dev",
    "st_ino",
    "st_mode",
    "st_nlink",
    "st_uid",
    "st_gid",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
)


def _verifier_unavailable() -> RuntimeError:
    return RuntimeError("catalog verifier unavailable")


def _read_authenticated_verifier_source(path: Path) -> bytes:
    """Read one regular, single-link verifier and authenticate its exact bytes."""

    if not path.is_absolute() or any(
        component in {"", ".", ".."} for component in path.parts[1:]
    ):
        raise _verifier_unavailable()
    required_flags = ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required_flags):
        raise _verifier_unavailable()
    flags = os.O_RDONLY
    for name in required_flags:
        flags |= getattr(os, name)
    try:
        descriptor = os.open(path, flags)
    except (OSError, TypeError, ValueError) as exc:
        raise _verifier_unavailable() from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > MAX_VERIFIER_BYTES
        ):
            raise _verifier_unavailable()

        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise _verifier_unavailable()
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            any(
                getattr(before, field) != getattr(after, field)
                for field in _STABLE_STAT_FIELDS
            )
            or hashlib.sha256(content).hexdigest() != CATALOG_VERIFIER_SHA256
        ):
            raise _verifier_unavailable()
        return content
    except OSError as exc:
        raise _verifier_unavailable() from exc
    finally:
        os.close(descriptor)


def _load_catalog_verifier(
    path: Path = VERIFIER_PATH,
    *,
    module_name: str = _CATALOG_MODULE_NAME,
) -> ModuleType:
    """Compile and execute only verifier bytes authenticated above."""

    content = _read_authenticated_verifier_source(path)
    if not module_name or module_name in sys.modules:
        raise _verifier_unavailable()
    try:
        code = compile(content, os.fspath(path), "exec", dont_inherit=True)
        module = ModuleType(module_name)
        module.__file__ = os.fspath(path)
        module.__package__ = ""
        module.__spec__ = None
        sys.modules[module_name] = module
        exec(code, module.__dict__)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise _verifier_unavailable() from exc
    return module


catalog = _load_catalog_verifier()


@dataclass(frozen=True)
class ValidatedCatalogEntry:
    """One immutable source entry proven by the versioned catalog head."""

    position: int
    name: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ValidatedCatalogSnapshot:
    """One stable source-only view of the current catalog."""

    head_content_sha256: str
    schema_content_sha256: str
    catalog_digest_sha256: str
    catalog_directory: str
    entries: tuple[ValidatedCatalogEntry, ...]
    operational_authorization: bool
    next_stage_authorized: bool


def validated_local_catalog_snapshot() -> ValidatedCatalogSnapshot:
    """Return immutable source evidence without authorizing database access.

    Longitudinal approval of a newly appended batch remains the CI verifier's
    responsibility.  A live operation additionally requires an independently
    pinned launcher and nominal authorization; consumers must not reinterpret
    this value as either.
    """

    head_record = catalog._read_stable_file(catalog.HEAD_PATH)
    schema_record = catalog._read_stable_file(catalog.SCHEMA_PATH)
    head = catalog._decode_json(head_record.content)
    schema = catalog._decode_json(schema_record.content)
    catalog._require_exact(schema, catalog._expected_schema())
    scanned = catalog._scan_catalog()
    reconstructed = catalog.validate_head(
        head,
        scanned_catalog=scanned,
        _approved_snapshot=True,
    )
    if not catalog._stable_file_unchanged(
        catalog._read_stable_file(catalog.HEAD_PATH), head_record
    ):
        raise catalog.ArtifactIoError
    if not catalog._stable_file_unchanged(
        catalog._read_stable_file(catalog.SCHEMA_PATH), schema_record
    ):
        raise catalog.ArtifactIoError

    return ValidatedCatalogSnapshot(
        head_content_sha256=hashlib.sha256(head_record.content).hexdigest(),
        schema_content_sha256=hashlib.sha256(schema_record.content).hexdigest(),
        catalog_digest_sha256=head["current_head"]["digest_sha256"],
        catalog_directory=os.fspath(catalog.MIGRATIONS_DIR.absolute()),
        entries=tuple(
            ValidatedCatalogEntry(
                position=entry["position"],
                name=entry["name"],
                sha256=entry["sha256"],
                size_bytes=entry["size_bytes"],
            )
            for entry in reconstructed
        ),
        operational_authorization=head["operational_authorization"],
        next_stage_authorized=head["next_stage_authorized"],
    )


__all__ = (
    "ValidatedCatalogEntry",
    "ValidatedCatalogSnapshot",
    "validated_local_catalog_snapshot",
)
