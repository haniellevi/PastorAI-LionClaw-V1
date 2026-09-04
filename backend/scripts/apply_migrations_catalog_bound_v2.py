#!/usr/bin/env python3
"""Catalog-bound launcher candidate for the immutable legacy migration runner.

This module adds a source-integrity boundary around ``apply_migrations.py``.
It authenticates the exact legacy runner bytes, consumes the strict local
catalog snapshot, and binds every discovered SQL file to the snapshot's name,
position, size, and SHA-256.

The snapshot is source evidence only.  No independently pinned trust anchor or
authorization context for a database operation exists in this version, so
``status``, ``harden-ledger``, ``bootstrap-ledger``, and ``apply`` always fail
closed before a connection.  ``list`` is the only successful command and is
explicitly source-only.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import types
from typing import Any, Iterator

LEGACY_RUNNER_PATH = Path(__file__).absolute().with_name("apply_migrations.py")
SNAPSHOT_API_PATH = Path(__file__).absolute().with_name(
    "validated_migration_catalog_snapshot.py"
)
LEGACY_RUNNER_SHA256 = (
    "36e63cde6751cd0cb33e1511091068b0b04f10029ace06703eead82e0e836c65"
)
SNAPSHOT_API_SHA256 = (
    "c3b88dd7f2b520e9de9353f2c220b5a2f07aaadc42661e8f2d9bb03a955d1d3f"
)
MAX_LEGACY_RUNNER_BYTES = 4_194_304
MAX_SNAPSHOT_API_BYTES = 4_194_304
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

USAGE_EXIT = 2
CATALOG_EXIT = 4
AUTHORIZATION_EXIT = 8
INTEGRITY_EXIT = 9
INTERNAL_EXIT = 10


class CatalogBoundV2Error(RuntimeError):
    """Base class whose public representation is a fixed, non-secret token."""

    exit_code = INTERNAL_EXIT
    reason = "INTERNAL_FAIL_CLOSED"


class LegacyIntegrityError(CatalogBoundV2Error):
    exit_code = INTEGRITY_EXIT
    reason = "LEGACY_RUNNER_INTEGRITY"


class CatalogBindingError(CatalogBoundV2Error):
    exit_code = CATALOG_EXIT
    reason = "CATALOG_BINDING"


class RequestRejectedError(CatalogBoundV2Error):
    exit_code = CATALOG_EXIT
    reason = "REQUEST_REJECTED"


class OperatorHashMismatchError(RequestRejectedError):
    reason = "OPERATOR_HASH_NOT_CATALOG_HEAD"


class AuthorizationUnavailableError(CatalogBoundV2Error):
    exit_code = AUTHORIZATION_EXIT
    reason = "TRUST_ANCHOR_AND_AUTHORIZATION_CONTEXT_UNAVAILABLE"


def _read_pinned_snapshot_api() -> bytes:
    """Read and authenticate the snapshot API before executing any bytes."""

    required = ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required):
        raise CatalogBindingError
    flags = os.O_RDONLY
    for name in required:
        flags |= getattr(os, name)
    try:
        descriptor = os.open(SNAPSHOT_API_PATH, flags)
    except (OSError, TypeError, ValueError) as exc:
        raise CatalogBindingError from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > MAX_SNAPSHOT_API_BYTES
        ):
            raise CatalogBindingError
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise CatalogBindingError
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        stable_fields = (
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
        if (
            any(
                getattr(before, field) != getattr(after, field)
                for field in stable_fields
            )
            or hashlib.sha256(content).hexdigest() != SNAPSHOT_API_SHA256
        ):
            raise CatalogBindingError
        return content
    except OSError as exc:
        raise CatalogBindingError from exc
    finally:
        os.close(descriptor)


def _load_pinned_snapshot_api() -> types.ModuleType:
    content = _read_pinned_snapshot_api()
    module_name = "_pastorai_catalog_snapshot_for_catalog_bound_v2"
    if module_name in sys.modules:
        raise CatalogBindingError
    module = types.ModuleType(module_name)
    module.__file__ = os.fspath(SNAPSHOT_API_PATH)
    module.__package__ = ""
    module.__spec__ = None
    sys.modules[module_name] = module
    try:
        code = compile(
            content,
            os.fspath(SNAPSHOT_API_PATH),
            "exec",
            dont_inherit=True,
        )
        exec(code, module.__dict__)
    except BaseException as exc:
        sys.modules.pop(module_name, None)
        raise CatalogBindingError from exc
    return module


try:
    migration_catalog: types.ModuleType | None = _load_pinned_snapshot_api()
except BaseException:
    # Keep CLI failures sanitized and fail-closed inside ``main``.
    migration_catalog = None


@dataclass(frozen=True)
class CatalogBinding:
    snapshot: Any
    migrations: tuple[Any, ...]
    entries: tuple[Any, ...]


def _stable_regular_file_bytes(path: Path, *, maximum: int) -> bytes:
    """Read through the catalog verifier's dir-fd-bound hardened primitive.

    That reader opens every ancestor without following symlinks, opens the
    final file with ``O_NOFOLLOW|O_NONBLOCK``, rejects non-regular and
    multiply-linked files, and revalidates the full directory chain.  Reusing
    it keeps the legacy loader from having a weaker pathname/TOCTOU boundary
    than the catalog it is supposed to consume.
    """

    catalog_module = getattr(migration_catalog, "catalog", None)
    reader = getattr(catalog_module, "_read_stable_file", None)
    if not callable(reader):
        raise LegacyIntegrityError
    try:
        record = reader(
            path,
            maximum_size=maximum,
            error_type=LegacyIntegrityError,
        )
    except LegacyIntegrityError:
        raise
    except BaseException as exc:
        raise LegacyIntegrityError from exc
    content = getattr(record, "content", None)
    if type(content) is not bytes:
        raise LegacyIntegrityError
    return content


def _verified_legacy_bytes(path: Path = LEGACY_RUNNER_PATH) -> bytes:
    content = _stable_regular_file_bytes(path, maximum=MAX_LEGACY_RUNNER_BYTES)
    if hashlib.sha256(content).hexdigest() != LEGACY_RUNNER_SHA256:
        raise LegacyIntegrityError
    return content


def _load_legacy_runner(path: Path = LEGACY_RUNNER_PATH) -> types.ModuleType:
    """Execute only bytes authenticated against the pinned legacy SHA-256."""

    content = _verified_legacy_bytes(path)
    module_name = "_catalog_bound_v2_verified_legacy_runner"
    module = types.ModuleType(module_name)
    module.__file__ = os.fspath(path)
    module.__package__ = ""
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        code = compile(content, os.fspath(path), "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        raise LegacyIntegrityError from exc
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous

    # The path is reauthenticated after execution.  Execution used the already
    # verified immutable bytes above; this second read detects replacement of
    # the versioned runner during loading before the module is exposed.
    if _verified_legacy_bytes(path) != content:
        raise LegacyIntegrityError
    required_callables = (
        "build_parser",
        "discover_migrations",
        "resolve_selected_migration",
        "_read_verified_migration",
        "prepare_transactional_sql",
        "_connect",
        "cmd_list",
    )
    if any(not callable(getattr(module, name, None)) for name in required_callables):
        raise LegacyIntegrityError
    if getattr(module, "DATABASE_URL_ENV", None) != "M06_MIGRATION_DATABASE_URL":
        raise LegacyIntegrityError
    return module


def _normalized_absolute_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise CatalogBindingError
    path = Path(value)
    if not path.is_absolute():
        raise CatalogBindingError
    return os.path.normcase(os.path.normpath(os.fspath(path)))


def _validate_snapshot(snapshot: Any, legacy: types.ModuleType) -> Any:
    snapshot_type = getattr(migration_catalog, "ValidatedCatalogSnapshot", None)
    entry_type = getattr(migration_catalog, "ValidatedCatalogEntry", None)
    if snapshot_type is None or entry_type is None or type(snapshot) is not snapshot_type:
        raise CatalogBindingError
    if snapshot.operational_authorization is not False:
        raise CatalogBindingError
    if snapshot.next_stage_authorized is not False:
        raise CatalogBindingError
    for digest in (
        snapshot.head_content_sha256,
        snapshot.schema_content_sha256,
        snapshot.catalog_digest_sha256,
    ):
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise CatalogBindingError

    try:
        root = legacy._migration_root()
    except BaseException as exc:
        raise CatalogBindingError from exc
    if _normalized_absolute_path(snapshot.catalog_directory) != os.path.normcase(
        os.path.normpath(os.fspath(root))
    ):
        raise CatalogBindingError

    entries = snapshot.entries
    if type(entries) is not tuple or not entries:
        raise CatalogBindingError
    names: list[str] = []
    folded_names: set[str] = set()
    basename_re = getattr(legacy, "MIGRATION_BASENAME_RE", None)
    if not hasattr(basename_re, "fullmatch"):
        raise CatalogBindingError
    for expected_position, entry in enumerate(entries):
        if type(entry) is not entry_type:
            raise CatalogBindingError
        if type(entry.position) is not int or entry.position != expected_position:
            raise CatalogBindingError
        if (
            not isinstance(entry.name, str)
            or entry.name != Path(entry.name).name
            or not basename_re.fullmatch(entry.name)
        ):
            raise CatalogBindingError
        if entry.name.casefold() in folded_names:
            raise CatalogBindingError
        folded_names.add(entry.name.casefold())
        names.append(entry.name)
        if not isinstance(entry.sha256, str) or not SHA256_RE.fullmatch(entry.sha256):
            raise CatalogBindingError
        if type(entry.size_bytes) is not int or entry.size_bytes < 1:
            raise CatalogBindingError
    if names != sorted(names) or len(names) != len(set(names)):
        raise CatalogBindingError
    return snapshot


def _read_catalog_snapshot(legacy: types.ModuleType) -> Any:
    helper = getattr(migration_catalog, "validated_local_catalog_snapshot", None)
    if not callable(helper):
        raise CatalogBindingError
    try:
        snapshot = helper()
        return _validate_snapshot(snapshot, legacy)
    except CatalogBoundV2Error:
        raise
    except BaseException as exc:
        raise CatalogBindingError from exc


def _require_snapshot_unchanged(expected: Any, legacy: types.ModuleType) -> None:
    if _read_catalog_snapshot(legacy) != expected:
        raise CatalogBindingError


def _build_catalog_binding(legacy: types.ModuleType) -> CatalogBinding:
    snapshot = _read_catalog_snapshot(legacy)
    try:
        migrations = legacy.discover_migrations()
    except BaseException as exc:
        raise CatalogBindingError from exc
    if type(migrations) is not list or len(migrations) != len(snapshot.entries):
        raise CatalogBindingError

    migration_type = getattr(legacy, "MigrationFile", None)
    if migration_type is None:
        raise CatalogBindingError
    names = tuple(candidate.name for candidate in migrations)
    expected_names = tuple(entry.name for entry in snapshot.entries)
    if names != expected_names:
        raise CatalogBindingError

    for candidate, entry in zip(migrations, snapshot.entries, strict=True):
        if type(candidate) is not migration_type:
            raise CatalogBindingError
        if candidate.name != entry.name:
            raise CatalogBindingError
        if candidate.path.name != candidate.name or candidate.path.parent != candidate.root:
            raise CatalogBindingError
        if _normalized_absolute_path(os.fspath(candidate.root)) != _normalized_absolute_path(
            snapshot.catalog_directory
        ):
            raise CatalogBindingError
        if type(candidate.identity.size) is not int or candidate.identity.size != entry.size_bytes:
            raise CatalogBindingError
        try:
            legacy._read_verified_migration(candidate, entry.sha256)
        except BaseException as exc:
            raise CatalogBindingError from exc

    _require_snapshot_unchanged(snapshot, legacy)
    return CatalogBinding(
        snapshot=snapshot,
        migrations=tuple(migrations),
        entries=tuple(snapshot.entries),
    )


def _entry_for_candidate(binding: CatalogBinding, candidate: Any) -> Any:
    for bound_candidate, entry in zip(
        binding.migrations, binding.entries, strict=True
    ):
        if candidate is bound_candidate:
            return entry
    raise CatalogBindingError


@contextmanager
def _catalog_bound_hooks(
    legacy: types.ModuleType, binding: CatalogBinding
) -> Iterator[None]:
    """Install temporary catalog/connection guards and restore them exactly."""

    original_discover = legacy.discover_migrations
    original_read = legacy._read_verified_migration
    original_connect = legacy._connect

    def bound_discover() -> list[Any]:
        _require_snapshot_unchanged(binding.snapshot, legacy)
        return list(binding.migrations)

    def bound_read(candidate: Any, expected_hash: str | None) -> str:
        _require_snapshot_unchanged(binding.snapshot, legacy)
        entry = _entry_for_candidate(binding, candidate)
        if expected_hash != entry.sha256:
            raise OperatorHashMismatchError
        try:
            return original_read(candidate, entry.sha256)
        except BaseException as exc:
            raise CatalogBindingError from exc

    def blocked_connect(_url: str) -> Any:
        _require_snapshot_unchanged(binding.snapshot, legacy)
        raise AuthorizationUnavailableError

    legacy.discover_migrations = bound_discover
    legacy._read_verified_migration = bound_read
    legacy._connect = blocked_connect
    try:
        yield
    finally:
        legacy.discover_migrations = original_discover
        legacy._read_verified_migration = original_read
        legacy._connect = original_connect


def _validate_database_request(
    legacy: types.ModuleType, binding: CatalogBinding, args: Any
) -> None:
    command = getattr(args, "command", None)
    if command == "apply":
        if not all(
            isinstance(getattr(args, field, None), str)
            and bool(getattr(args, field, None))
            for field in ("migration", "sha256", "confirm")
        ):
            raise RequestRejectedError
        try:
            migrations = legacy.discover_migrations()
            selected = legacy.resolve_selected_migration(args.migration, migrations)
        except CatalogBoundV2Error:
            raise
        except BaseException as exc:
            raise RequestRejectedError from exc
        entry = _entry_for_candidate(binding, selected)
        if args.sha256 != entry.sha256:
            raise OperatorHashMismatchError
        try:
            sql = legacy._read_verified_migration(selected, args.sha256)
            legacy.prepare_transactional_sql(sql)
        except CatalogBoundV2Error:
            raise
        except BaseException as exc:
            raise RequestRejectedError from exc
        return
    if command == "harden-ledger":
        if getattr(args, "confirm", None) != legacy.LEDGER_HARDEN_CONFIRMATION:
            raise RequestRejectedError
        return
    if command == "bootstrap-ledger":
        if getattr(args, "confirm", None) != legacy.LEDGER_BOOTSTRAP_CONFIRMATION:
            raise RequestRejectedError
        return
    if command != "status":
        raise RequestRejectedError


def _print_gates() -> None:
    print("OPERATIONAL_AUTHORIZATION=BLOCKED")
    print("NEXT_STAGE_AUTHORIZED=false")


def _abort(error: CatalogBoundV2Error) -> int:
    print(f"CATALOG_BOUND_V2_BLOCKED:{error.reason}", file=sys.stderr)
    _print_gates()
    return error.exit_code


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv if argv is None else argv
    try:
        legacy = _load_legacy_runner()
    except CatalogBoundV2Error as error:
        return _abort(error)
    except BaseException:
        return _abort(LegacyIntegrityError())

    try:
        args = legacy.build_parser().parse_args(arguments[1:])
    except legacy.CliUsageError:
        print("CATALOG_BOUND_V2_BLOCKED:USAGE", file=sys.stderr)
        _print_gates()
        return USAGE_EXIT
    except SystemExit:
        # Even argparse's nominally successful --help path must remain
        # fail-closed.  ``list`` is the only command allowed to return zero.
        return _abort(RequestRejectedError())
    except BaseException:
        return _abort(RequestRejectedError())

    try:
        binding = _build_catalog_binding(legacy)
        with _catalog_bound_hooks(legacy, binding):
            if args.command == "list":
                result = legacy.cmd_list(args)
                if result != 0:
                    raise CatalogBindingError
                _require_snapshot_unchanged(binding.snapshot, legacy)
                print("CATALOG_BOUND_V2=VERIFIED_SOURCE_ONLY")
                print(f"CATALOG_ENTRY_COUNT={len(binding.entries)}")
                print(
                    "CATALOG_DIGEST_SHA256="
                    f"{binding.snapshot.catalog_digest_sha256}"
                )
                _print_gates()
                return 0

            _validate_database_request(legacy, binding, args)
            # This is the final check immediately before the absent operational
            # boundary.  No DSN is read and the original _connect is unreachable.
            _require_snapshot_unchanged(binding.snapshot, legacy)
            raise AuthorizationUnavailableError
    except CatalogBoundV2Error as error:
        return _abort(error)
    except BaseException:
        return _abort(CatalogBoundV2Error())


if __name__ == "__main__":
    raise SystemExit(main())
