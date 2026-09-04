#!/usr/bin/env python3
"""Replay the validated current migration-catalog head in disposable PG17.

This is a CI execution check, not a migration runner for a shared environment.
It accepts only one dedicated loopback database, loads every migration into an
immutable in-memory source set before connecting, and never creates a migration
ledger or changes either authorization gate.

The historical 75-file canonical-schema derivation remains a separate pinned
contract.  This script reuses only its compatibility scaffold; it does not
derive, replace, or reinterpret the historical schema fingerprint.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
from types import ModuleType
from typing import Any, Callable, NoReturn
from urllib.parse import urlsplit

DATABASE_URL_ENV = "MIGRATION_CATALOG_REPLAY_DATABASE_URL"
RLS_TEST_DATABASE_URL_ENV = "RLS_TEST_DATABASE_URL"
REPO_ROOT = Path(__file__).absolute().parents[2]
AUTHORING_PATH = REPO_ROOT / "backend" / "scripts" / "new_migration.py"
SNAPSHOT_API_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "validated_migration_catalog_snapshot.py"
)
AUTHORING_SHA256 = (
    "83abce96e63fe676e3088c225b1e29ae89268ce97d01727bc740fa2f50001bbe"
)
SNAPSHOT_API_SHA256 = (
    "c3b88dd7f2b520e9de9353f2c220b5a2f07aaadc42661e8f2d9bb03a955d1d3f"
)
MAX_LOCAL_MODULE_BYTES = 4_194_304
SCAFFOLD_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-canonical-schema-scaffold-v1.sql"
)
SCAFFOLD_SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-canonical-schema-derivation.schema.json"
)
SCAFFOLD_SHA256 = (
    "9dcf654790e9787d218ec93f59c04d46d1aaab214f223b8ac5f4b2dd502ef3cc"
)
SCAFFOLD_SCHEMA_SHA256 = (
    "1033463518b5655f495118b458e6ae7056d3fa92ed325df0278cf851ec89be83"
)
DISPOSABLE_DATABASE = "migration_catalog_current_head_disposable"
DECLARED_TEST_DATABASE = "postgres"
CONFIRMATION = "REPLAY_MIGRATION_CATALOG_CURRENT_HEAD_PG17_DISPOSABLE"
DECLARED_TESTS_CONFIRMATION = "RUN_DECLARED_MIGRATION_TESTS_PG17_DISPOSABLE"
SUCCESS = "RESULT=MIGRATION_CATALOG_CURRENT_HEAD_REPLAYED_PG17_DISPOSABLE"
DECLARED_TESTS_SUCCESS = "RESULT=DECLARED_MIGRATION_TESTS_EXECUTED_PG17_DISPOSABLE"
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
NEXT_STAGE_BLOCK = "NEXT_STAGE_AUTHORIZED=false"
ENVIRONMENT_BLOCK = "SHARED_ENVIRONMENT_ATTESTATION=false"
TRANSACTION_STATUS_IDLE = 0
TENANT_IDENTIFIER_PATTERN = r"(?:[a-z_][a-z0-9_]*\.)?igreja_id"
TENANT_GUC_PATTERN = (
    r"(?:pg_catalog\.)?current_setting\("
    r"'app\.tenant_igreja_id'(?:::text)?,true\)"
)
TENANT_GUC_UUID_PATTERN = (
    rf"(?:\((?:{TENANT_GUC_PATTERN}|(?:pg_catalog\.)?nullif\("
    rf"{TENANT_GUC_PATTERN},''(?:::text)?\))\)|"
    rf"(?:{TENANT_GUC_PATTERN}|(?:pg_catalog\.)?nullif\("
    rf"{TENANT_GUC_PATTERN},''(?:::text)?\)))"
    r"::(?:pg_catalog\.)?uuid"
)
TENANT_POLICY_PATTERN = re.compile(
    rf"(?:{TENANT_IDENTIFIER_PATTERN}={TENANT_GUC_UUID_PATTERN}|"
    rf"{TENANT_GUC_UUID_PATTERN}={TENANT_IDENTIFIER_PATTERN})"
)


def _read_pinned_local_module(path: Path, expected_sha256: str) -> bytes:
    """Authenticate one dependency before executing any of its bytes."""

    if (
        not path.is_absolute()
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        or any(component in {"", ".", ".."} for component in path.parts[1:])
    ):
        raise RuntimeError("replay dependency unavailable")
    required = ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required):
        raise RuntimeError("replay dependency unavailable")
    flags = os.O_RDONLY
    for name in required:
        flags |= getattr(os, name)
    try:
        descriptor = os.open(path, flags)
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError("replay dependency unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > MAX_LOCAL_MODULE_BYTES
        ):
            raise RuntimeError("replay dependency unavailable")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise RuntimeError("replay dependency unavailable")
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
            or hashlib.sha256(content).hexdigest() != expected_sha256
        ):
            raise RuntimeError("replay dependency unavailable")
        return content
    except OSError as exc:
        raise RuntimeError("replay dependency unavailable") from exc
    finally:
        os.close(descriptor)


def _load_pinned_local_module(
    *, module_name: str, path: Path, expected_sha256: str
) -> ModuleType:
    content = _read_pinned_local_module(path, expected_sha256)
    if not module_name or module_name in sys.modules:
        raise RuntimeError("replay dependency unavailable")
    try:
        code = compile(content, os.fspath(path), "exec", dont_inherit=True)
        module = ModuleType(module_name)
        module.__file__ = os.fspath(path)
        module.__package__ = ""
        module.__spec__ = None
        sys.modules[module_name] = module
        exec(code, module.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


catalog_snapshot = _load_pinned_local_module(
    module_name="_pastorai_catalog_snapshot_for_pg17_replay",
    path=SNAPSHOT_API_PATH,
    expected_sha256=SNAPSHOT_API_SHA256,
)
migration_authoring = _load_pinned_local_module(
    module_name="_pastorai_migration_authoring_for_pg17_replay",
    path=AUTHORING_PATH,
    expected_sha256=AUTHORING_SHA256,
)

# The snapshot API authenticates the historical verifier bytes before executing
# them. Never import the verifier path a second time after that proof.
catalog = catalog_snapshot.catalog


class ReplayError(RuntimeError):
    exit_code = 10
    reason = "INTERNAL_ERROR"


class CliUsageError(ReplayError):
    exit_code = 2
    reason = "USAGE"


class SourceContractError(ReplayError):
    exit_code = 4
    reason = "SOURCE_CONTRACT_INVALID"


class TargetGuardError(ReplayError):
    exit_code = 5
    reason = "DISPOSABLE_LOOPBACK_TARGET_REQUIRED"


class DatabaseContractError(ReplayError):
    exit_code = 6
    reason = "DATABASE_CONTRACT_INVALID"


class MigrationReplayError(ReplayError):
    exit_code = 7
    reason = "MIGRATION_REPLAY_BLOCKED"


class DeclaredTestsError(ReplayError):
    exit_code = 8
    reason = "DECLARED_TESTS_NOT_FULLY_EXECUTED"


class SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise CliUsageError


@dataclass(frozen=True)
class LoadedMigration:
    position: int
    name: str
    sha256: str
    sql: str
    scope: str | None = None
    affected_relations: tuple[str, ...] = ()
    pg17_test_nodeids: tuple[str, ...] = ()
    cross_tenant_test_nodeids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoadedCatalog:
    digest_sha256: str
    migrations: tuple[LoadedMigration, ...]


@dataclass(frozen=True)
class ReplayResult:
    catalog_digest_sha256: str
    migration_count: int
    postgres_version_num: int


@dataclass(frozen=True)
class DeclaredTestsResult:
    declared_nodeid_count: int
    collected_test_count: int
    passed_test_count: int


@dataclass(frozen=True)
class TenantSecurityState:
    rls_enabled: bool
    rls_forced: bool
    tenant_not_null: bool
    public_acl_present: bool
    restrictive_tenant_barrier: bool


def _load_current_catalog() -> LoadedCatalog:
    """Freeze one verified current head in memory before opening a socket."""

    try:
        before = catalog_snapshot.validated_local_catalog_snapshot()
    except catalog.VerificationError as exc:
        raise SourceContractError from exc

    if (
        before.operational_authorization is not False
        or before.next_stage_authorized is not False
        or not before.entries
    ):
        raise SourceContractError

    expected_directory = catalog.MIGRATIONS_DIR.absolute()
    directory = Path(before.catalog_directory)
    if not directory.is_absolute() or directory != expected_directory:
        raise SourceContractError

    total_bytes = 0
    loaded: list[LoadedMigration] = []
    for expected_position, entry in enumerate(before.entries):
        if entry.position != expected_position:
            raise SourceContractError
        if (
            Path(entry.name).name != entry.name
            or catalog.MIGRATION_BASENAME_RE.fullmatch(entry.name) is None
        ):
            raise SourceContractError
        try:
            record = catalog._read_stable_file(
                directory / entry.name,
                maximum_size=catalog.MAX_MIGRATION_BYTES,
                error_type=catalog.CatalogDriftError,
            )
        except catalog.VerificationError as exc:
            raise SourceContractError from exc
        raw = record.content
        total_bytes += len(raw)
        if (
            total_bytes > catalog.MAX_CATALOG_BYTES
            or len(raw) != entry.size_bytes
            or hashlib.sha256(raw).hexdigest() != entry.sha256
        ):
            raise SourceContractError
        try:
            sql = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise SourceContractError from exc
        scope: str | None = None
        affected_relations: tuple[str, ...] = ()
        pg17_test_nodeids: tuple[str, ...] = ()
        cross_tenant_test_nodeids: tuple[str, ...] = ()
        if entry.position >= catalog.HISTORICAL_COUNT:
            try:
                intent = migration_authoring._validate_candidate_intent_for_replay(
                    record,
                    basename=entry.name,
                )
            except (
                migration_authoring.AuthoringError,
                catalog.VerificationError,
            ) as exc:
                raise SourceContractError from exc
            scope_value = intent.get("scope")
            relation_values = intent.get("affected_relations")
            pg17_values = intent.get("pg17_test_nodeids")
            cross_tenant_values = intent.get("cross_tenant_test_nodeids")
            if (
                scope_value != "TENANT"
                or type(relation_values) is not list
                or not relation_values
                or type(pg17_values) is not list
                or not pg17_values
                or type(cross_tenant_values) is not list
                or not cross_tenant_values
            ):
                raise SourceContractError
            scope = scope_value
            affected_relations = tuple(relation_values)
            pg17_test_nodeids = tuple(pg17_values)
            cross_tenant_test_nodeids = tuple(cross_tenant_values)
        loaded.append(
            LoadedMigration(
                position=entry.position,
                name=entry.name,
                sha256=entry.sha256,
                sql=sql,
                scope=scope,
                affected_relations=affected_relations,
                pg17_test_nodeids=pg17_test_nodeids,
                cross_tenant_test_nodeids=cross_tenant_test_nodeids,
            )
        )

    # The SQL bytes above are now independent of later filesystem changes.
    # Revalidating the entire head here also detects catalog drift during the
    # load window, before any database connection is attempted.
    try:
        after = catalog_snapshot.validated_local_catalog_snapshot()
    except catalog.VerificationError as exc:
        raise SourceContractError from exc
    if after != before:
        raise SourceContractError

    return LoadedCatalog(
        digest_sha256=before.catalog_digest_sha256,
        migrations=tuple(loaded),
    )


def _load_historical_compatibility_scaffold() -> str:
    try:
        scaffold_record = catalog._read_stable_file(
            SCAFFOLD_PATH,
            maximum_size=262_144,
            error_type=catalog.ArtifactIoError,
        )
        schema_record = catalog._read_stable_file(
            SCAFFOLD_SCHEMA_PATH,
            maximum_size=262_144,
            error_type=catalog.ArtifactIoError,
        )
    except catalog.VerificationError as exc:
        raise SourceContractError from exc
    raw = scaffold_record.content
    schema = schema_record.content
    if (
        hashlib.sha256(raw).hexdigest() != SCAFFOLD_SHA256
        or hashlib.sha256(schema).hexdigest() != SCAFFOLD_SCHEMA_SHA256
    ):
        raise SourceContractError
    try:
        decoded = raw.decode("utf-8", errors="strict")
        json.loads(schema.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceContractError from exc
    if (
        not catalog._stable_file_unchanged(
            catalog._read_stable_file(SCAFFOLD_PATH), scaffold_record
        )
        or not catalog._stable_file_unchanged(
            catalog._read_stable_file(SCAFFOLD_SCHEMA_PATH), schema_record
        )
    ):
        raise SourceContractError
    return decoded


def _read_disposable_url() -> tuple[str, str]:
    raw = os.environ.get(DATABASE_URL_ENV)
    if (
        raw is None
        or raw == ""
        or raw != raw.strip()
        or len(raw) > 4096
        or any(ord(character) < 0x20 for character in raw)
    ):
        raise TargetGuardError
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port
    except (ValueError, UnicodeError) as exc:
        raise TargetGuardError from exc
    if parsed.scheme not in {"postgresql", "postgres"} or host is None:
        raise TargetGuardError
    try:
        target_address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise TargetGuardError from exc
    if not target_address.is_loopback:
        raise TargetGuardError
    if parsed.path != f"/{DISPOSABLE_DATABASE}":
        raise TargetGuardError
    if parsed.query or parsed.fragment:
        raise TargetGuardError
    if parsed.username != "postgres" or parsed.password in {None, ""}:
        raise TargetGuardError
    if port is None or port < 1024 or port > 65535:
        raise TargetGuardError
    return raw, DISPOSABLE_DATABASE


def _require_declared_tests_target() -> None:
    raw = os.environ.get(RLS_TEST_DATABASE_URL_ENV)
    if (
        raw is None
        or raw == ""
        or raw != raw.strip()
        or len(raw) > 4096
        or any(ord(character) < 0x20 for character in raw)
    ):
        raise TargetGuardError
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port
    except (ValueError, UnicodeError) as exc:
        raise TargetGuardError from exc
    try:
        target_address = ipaddress.ip_address(host) if host is not None else None
    except ValueError as exc:
        raise TargetGuardError from exc
    if (
        parsed.scheme != "postgresql+psycopg2"
        or target_address is None
        or not target_address.is_loopback
        or parsed.path != f"/{DECLARED_TEST_DATABASE}"
        or parsed.query
        or parsed.fragment
        or parsed.username != "postgres"
        or parsed.password in {None, ""}
        or port is None
        or port < 1024
        or port > 65535
    ):
        raise TargetGuardError


def _check_non_public_server_address(value: Any) -> None:
    if value is None:
        # PostgreSQL can report NULL for a Unix socket, but the DSN guard above
        # requires TCP.  Treat NULL as a contract failure instead of guessing.
        raise DatabaseContractError
    try:
        address = ipaddress.ip_address(str(value))
    except ValueError as exc:
        raise DatabaseContractError from exc
    # A host-loopback Docker publication terminates on a private bridge address
    # inside PostgreSQL.  The independent URL guard remains loopback-only.
    if not (address.is_loopback or address.is_private or address.is_link_local):
        raise DatabaseContractError


def _ensure_ledgers_absent(cursor: Any) -> None:
    cursor.execute(
        """
        select pg_catalog.to_regclass('public.schema_migrations') is null,
               pg_catalog.to_regnamespace('supabase_migrations') is null
        """
    )
    if cursor.fetchone() != (True, True):
        raise DatabaseContractError


def _validate_fresh_database(cursor: Any, expected_database: str) -> int:
    cursor.execute(
        """
        select current_database(), current_setting('server_version_num')::integer,
               pg_catalog.inet_server_addr(), current_user, session_user,
               current_setting('transaction_read_only')
        """
    )
    row = cursor.fetchone()
    if row is None or len(row) != 6:
        raise DatabaseContractError
    database_name, version_num, address, owner, session_owner, read_only = row
    if (
        database_name != expected_database
        or type(version_num) is not int
        or version_num // 10_000 != 17
    ):
        raise DatabaseContractError
    _check_non_public_server_address(address)
    if owner != session_owner or read_only != "off":
        raise DatabaseContractError

    cursor.execute(
        """
        select count(*)::integer
          from pg_catalog.pg_class c
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public'
           and c.relkind in ('r', 'p', 'v', 'm', 'S', 'f')
        """
    )
    if cursor.fetchone() != (0,):
        raise DatabaseContractError

    cursor.execute(
        """
        select count(*)::integer from pg_catalog.pg_roles
         where rolname in ('anon', 'authenticated', 'service_role', 'agent_runtime')
        """
    )
    if cursor.fetchone() != (0,):
        raise DatabaseContractError
    _ensure_ledgers_absent(cursor)
    return version_num


def _require_idle_transaction(connection: Any) -> None:
    try:
        status = connection.get_transaction_status()
    except Exception as exc:
        raise DatabaseContractError from exc
    if status != TRANSACTION_STATUS_IDLE:
        raise MigrationReplayError


def _validate_tenant_relations(
    cursor: Any, affected_relations: tuple[str, ...]
) -> None:
    """Prove the declared tenant postconditions from PostgreSQL catalogs."""

    if (
        type(affected_relations) is not tuple
        or not affected_relations
        or len(affected_relations) > 32
        or affected_relations != tuple(sorted(affected_relations))
        or len(affected_relations) != len(set(affected_relations))
    ):
        raise DatabaseContractError
    for relation in affected_relations:
        if (
            type(relation) is not str
            or migration_authoring.AFFECTED_RELATION_RE.fullmatch(relation) is None
        ):
            raise DatabaseContractError
        state = _tenant_relation_security_state(cursor, relation)
        if state != TenantSecurityState(True, True, True, False, True):
            raise DatabaseContractError


def _tenant_relation_security_state(
    cursor: Any, relation: str
) -> TenantSecurityState:
    schema_name, relation_name = relation.split(".", 1)
    cursor.execute(
        """
        select c.relrowsecurity,
               c.relforcerowsecurity,
               coalesce(tenant_column.attnotnull, false),
               exists (
                 select 1
                   from pg_catalog.aclexplode(
                     coalesce(
                       c.relacl,
                       pg_catalog.acldefault('r', c.relowner)
                     )
                   ) as relation_acl
                  where relation_acl.grantee = 0
                 union all
                 select 1
                   from pg_catalog.pg_attribute protected_column
                   cross join lateral pg_catalog.aclexplode(
                     protected_column.attacl
                   ) as column_acl
                  where protected_column.attrelid = c.oid
                    and protected_column.attnum > 0
                    and not protected_column.attisdropped
                    and protected_column.attacl is not null
                    and column_acl.grantee = 0
               ) as public_acl_present
          from pg_catalog.pg_class c
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
          left join pg_catalog.pg_attribute tenant_column
            on tenant_column.attrelid = c.oid
           and tenant_column.attname = 'igreja_id'
           and tenant_column.attnum > 0
           and not tenant_column.attisdropped
         where n.nspname = %s
           and c.relname = %s
           and c.relkind in ('r', 'p')
        """,
        (schema_name, relation_name),
    )
    metadata = cursor.fetchone()
    if (
        type(metadata) not in {tuple, list}
        or len(metadata) != 4
        or any(type(value) is not bool for value in metadata)
    ):
        raise DatabaseContractError

    cursor.execute(
        """
        select policy.polname,
               policy.polcmd,
               policy.polpermissive,
               policy.polroles,
               pg_catalog.pg_get_expr(policy.polqual, policy.polrelid),
               pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid)
          from pg_catalog.pg_policy policy
          join pg_catalog.pg_class c on c.oid = policy.polrelid
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
         where n.nspname = %s
           and c.relname = %s
         order by policy.polname
        """,
        (schema_name, relation_name),
    )
    policies = cursor.fetchall()
    if type(policies) is not list:
        raise DatabaseContractError
    restrictive_barrier_found = False
    for policy in policies:
        if type(policy) not in {tuple, list} or len(policy) != 6:
            raise DatabaseContractError
        (
            policy_name,
            command,
            permissive,
            roles,
            using_expression,
            check_expression,
        ) = policy
        if (
            type(policy_name) is not str
            or not policy_name
            or command not in {"*", "r", "a", "w", "d"}
            or type(permissive) is not bool
            or type(roles) not in {tuple, list}
            or not roles
            or any(type(role) is not int for role in roles)
        ):
            raise DatabaseContractError
        using_bound = _tenant_bound_policy_expression(using_expression)
        check_bound = _tenant_bound_policy_expression(check_expression)
        if (
            permissive is False
            and command == "*"
            and tuple(roles) == (0,)
            and using_bound
            and check_bound
        ):
            restrictive_barrier_found = True
    return TenantSecurityState(
        rls_enabled=metadata[0],
        rls_forced=metadata[1],
        tenant_not_null=metadata[2],
        public_acl_present=metadata[3],
        restrictive_tenant_barrier=restrictive_barrier_found,
    )


def _capture_public_tenant_security_surface(
    cursor: Any,
) -> dict[str, TenantSecurityState]:
    """Capture every public table/partition and its tenant security state."""

    cursor.execute(
        """
        select 'public.' || c.relname
          from pg_catalog.pg_class c
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public'
           and c.relkind in ('r', 'p')
         order by c.relname
        """
    )
    rows = cursor.fetchall()
    if (
        type(rows) is not list
        or not rows
        or len(rows) > 4_096
        or any(
            type(row) not in {tuple, list}
            or len(row) != 1
            or type(row[0]) is not str
            for row in rows
        )
    ):
        raise DatabaseContractError
    relations = tuple(row[0] for row in rows)
    if relations != tuple(sorted(relations)) or len(relations) != len(set(relations)):
        raise DatabaseContractError
    return {
        relation: _tenant_relation_security_state(cursor, relation)
        for relation in relations
    }


def _validate_tenant_security_delta(
    before: dict[str, TenantSecurityState],
    after: dict[str, TenantSecurityState],
    declared_relations: tuple[str, ...],
) -> None:
    """Reject removal or weakening of any pre-existing tenant boundary."""

    if (
        type(before) is not dict
        or type(after) is not dict
        or not before
        or not after
        or not set(before).issubset(after)
        or any(type(value) is not TenantSecurityState for value in before.values())
        or any(type(value) is not TenantSecurityState for value in after.values())
    ):
        raise DatabaseContractError
    declared = set(declared_relations)
    secure = TenantSecurityState(True, True, True, False, True)
    changed: set[str] = set()
    for relation, prior in before.items():
        current = after[relation]
        if prior != current:
            changed.add(relation)
        if (
            (prior.rls_enabled and not current.rls_enabled)
            or (prior.rls_forced and not current.rls_forced)
            or (prior.tenant_not_null and not current.tenant_not_null)
            or (not prior.public_acl_present and current.public_acl_present)
            or (
                prior.restrictive_tenant_barrier
                and not current.restrictive_tenant_barrier
            )
        ):
            raise DatabaseContractError
    new_relations = set(after) - set(before)
    if any(after[relation] != secure for relation in new_relations):
        raise DatabaseContractError
    if not (changed | new_relations).issubset(declared):
        raise DatabaseContractError


def _tenant_bound_policy_expression(value: object) -> bool:
    if type(value) is not str:
        return False
    normalized = _normalize_policy_expression(value)
    if normalized is None:
        return False
    while _has_one_outer_parenthesis_pair(normalized):
        normalized = normalized[1:-1]
    return TENANT_POLICY_PATTERN.fullmatch(normalized) is not None


def _normalize_policy_expression(value: str) -> str | None:
    """Fold SQL syntax whitespace without changing quoted literal bytes."""

    normalized: list[str] = []
    quoted = False
    index = 0
    while index < len(value):
        character = value[index]
        if character == "'":
            normalized.append(character)
            if quoted and index + 1 < len(value) and value[index + 1] == "'":
                normalized.append("'")
                index += 2
                continue
            quoted = not quoted
        elif quoted:
            normalized.append(character)
        elif not character.isspace():
            normalized.append(character.casefold())
        index += 1
    if quoted:
        return None
    return "".join(normalized)


def _has_one_outer_parenthesis_pair(value: str) -> bool:
    """Return true only when the first parenthesis encloses all SQL text."""

    if len(value) < 2 or value[0] != "(" or value[-1] != ")":
        return False
    depth = 0
    quoted = False
    index = 0
    while index < len(value):
        character = value[index]
        if character == "'":
            if quoted and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            quoted = not quoted
        elif not quoted:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth < 0 or (depth == 0 and index != len(value) - 1):
                    return False
        index += 1
    return not quoted and depth == 0


class _DeclaredTestsAudit:
    """Pytest plugin proving that every declared function actually ran."""

    def __init__(self, requested: tuple[str, ...]) -> None:
        self.requested = requested
        self.collected = {nodeid: 0 for nodeid in requested}
        self.passed = 0
        self.skipped = 0
        self.failed = 0
        self.xfail_or_xpass = 0
        self.invalid_collection = False

    @staticmethod
    def _repository_nodeid(value: object) -> str | None:
        if type(value) is not str:
            return None
        if value.startswith("tests/"):
            return "backend/" + value
        if value.startswith("backend/tests/"):
            return value
        return None

    def pytest_collection_modifyitems(self, items: list[Any]) -> None:
        for item in items:
            nodeid = self._repository_nodeid(getattr(item, "nodeid", None))
            matches = tuple(
                requested
                for requested in self.requested
                if nodeid == requested
                or (
                    nodeid is not None
                    and nodeid.startswith(requested + "[")
                )
            )
            if len(matches) != 1:
                self.invalid_collection = True
                continue
            self.collected[matches[0]] += 1

    def pytest_runtest_logreport(self, report: Any) -> None:
        if getattr(report, "wasxfail", None) is not None:
            self.xfail_or_xpass += 1
        if getattr(report, "skipped", False):
            self.skipped += 1
        if getattr(report, "failed", False):
            self.failed += 1
        if getattr(report, "when", None) == "call" and getattr(
            report, "passed", False
        ):
            self.passed += 1


def _declared_test_nodeids(loaded: LoadedCatalog) -> tuple[str, ...]:
    appended = tuple(
        migration
        for migration in loaded.migrations
        if migration.position >= catalog.HISTORICAL_COUNT
    )
    if not appended:
        return ()
    nodeids: set[str] = set()
    for migration in appended:
        if (
            migration.scope != "TENANT"
            or not migration.pg17_test_nodeids
            or not migration.cross_tenant_test_nodeids
            or not set(migration.cross_tenant_test_nodeids).issubset(
                set(migration.pg17_test_nodeids)
            )
        ):
            raise SourceContractError
        nodeids.update(migration.pg17_test_nodeids)
    if not nodeids:
        raise SourceContractError
    return tuple(sorted(nodeids))


def run_declared_migration_tests(
    pytest_main: Callable[..., Any] | None = None,
) -> DeclaredTestsResult:
    """Run validated nodeids through pytest's Python API, never through shell."""

    loaded = _load_current_catalog()
    nodeids = _declared_test_nodeids(loaded)
    if not nodeids:
        return DeclaredTestsResult(0, 0, 0)
    _require_declared_tests_target()
    if pytest_main is None:
        try:
            import pytest
        except ImportError as exc:
            raise DeclaredTestsError from exc
        pytest_main = pytest.main

    audit = _DeclaredTestsAudit(nodeids)
    pytest_args = [
        "--strict-markers",
        "--runxfail",
        "-o",
        "addopts=",
        "-p",
        "no:cacheprovider",
        "-q",
        "--tb=short",
        *(nodeid.removeprefix("backend/") for nodeid in nodeids),
    ]
    previous_directory = Path.cwd()
    try:
        os.chdir(REPO_ROOT / "backend")
        # Stdout is the machine-readable receipt channel of this launcher.
        # Pytest's progress, warnings and summary must never be interleaved
        # with that receipt, even when every declared test passes.  /dev/null
        # also avoids retaining attacker-controlled test output in memory.
        with open(os.devnull, "w", encoding="utf-8") as discarded_output:
            with redirect_stdout(discarded_output), redirect_stderr(
                discarded_output
            ):
                exit_code = pytest_main(pytest_args, plugins=[audit])
    except Exception as exc:
        raise DeclaredTestsError from exc
    finally:
        os.chdir(previous_directory)

    collected = sum(audit.collected.values())
    if (
        exit_code != 0
        or audit.invalid_collection
        or any(count < 1 for count in audit.collected.values())
        or collected < len(nodeids)
        or audit.skipped != 0
        or audit.failed != 0
        or audit.xfail_or_xpass != 0
        or audit.passed != collected
    ):
        raise DeclaredTestsError
    return DeclaredTestsResult(
        declared_nodeid_count=len(nodeids),
        collected_test_count=collected,
        passed_test_count=audit.passed,
    )


def replay_current_head_pg17(
    connect: Callable[..., Any] | None = None,
) -> ReplayResult:
    """Replay the current verified source in one fresh disposable database."""

    # Validate and freeze all non-secret inputs before reading the DSN.
    loaded = _load_current_catalog()
    scaffold = _load_historical_compatibility_scaffold()
    database_url, database_name = _read_disposable_url()

    if connect is None:
        try:
            import psycopg2
        except ImportError as exc:
            raise DatabaseContractError from exc
        connect = psycopg2.connect

    connection = None
    try:
        connection = connect(
            database_url,
            connect_timeout=5,
            application_name="pastorai-current-head-pg17-replay",
        )
        connection.autocommit = True
        with connection.cursor() as cursor:
            version_num = _validate_fresh_database(cursor, database_name)
            cursor.execute("set statement_timeout = '120s'")
            cursor.execute("set lock_timeout = '10s'")
            cursor.execute("set idle_in_transaction_session_timeout = '30s'")
            _require_idle_transaction(connection)

            try:
                cursor.execute(scaffold)
            except Exception as exc:
                raise MigrationReplayError from exc
            _require_idle_transaction(connection)
            _ensure_ledgers_absent(cursor)

            for migration in loaded.migrations:
                tenant_before = None
                if migration.position >= catalog.HISTORICAL_COUNT:
                    if migration.scope != "TENANT":
                        raise SourceContractError
                    tenant_before = _capture_public_tenant_security_surface(cursor)
                try:
                    cursor.execute(migration.sql)
                except Exception as exc:
                    raise MigrationReplayError from exc
                _require_idle_transaction(connection)
                _ensure_ledgers_absent(cursor)
                if migration.position >= catalog.HISTORICAL_COUNT:
                    if tenant_before is None:
                        raise SourceContractError
                    tenant_after = _capture_public_tenant_security_surface(cursor)
                    _validate_tenant_security_delta(
                        tenant_before,
                        tenant_after,
                        migration.affected_relations,
                    )
                    _validate_tenant_relations(
                        cursor,
                        migration.affected_relations,
                    )
                elif migration.scope is not None:
                    raise SourceContractError
    except ReplayError:
        raise
    except Exception as exc:
        raise DatabaseContractError from exc
    finally:
        if connection is not None:
            connection.close()

    return ReplayResult(
        catalog_digest_sha256=loaded.digest_sha256,
        migration_count=len(loaded.migrations),
        postgres_version_num=version_num,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = SanitizedArgumentParser(add_help=False)
    parser.add_argument(
        "--confirmation",
        required=True,
        choices=[CONFIRMATION, DECLARED_TESTS_CONFIRMATION],
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    print(OPERATIONAL_BLOCK)
    print(NEXT_STAGE_BLOCK)
    print(ENVIRONMENT_BLOCK)
    try:
        args = build_parser().parse_args(argv)
        if args.confirmation == DECLARED_TESTS_CONFIRMATION:
            declared = run_declared_migration_tests()
        else:
            result = replay_current_head_pg17()
    except ReplayError as exc:
        print(f"MIGRATION_CATALOG_CURRENT_HEAD_REPLAY_BLOCKED:{exc.reason}", file=sys.stderr)
        return exc.exit_code
    except Exception:
        print("MIGRATION_CATALOG_CURRENT_HEAD_REPLAY_BLOCKED:INTERNAL_ERROR", file=sys.stderr)
        return 10
    if args.confirmation == DECLARED_TESTS_CONFIRMATION:
        print(DECLARED_TESTS_SUCCESS)
        print(f"DECLARED_NODEID_COUNT={declared.declared_nodeid_count}")
        print(f"COLLECTED_TEST_COUNT={declared.collected_test_count}")
        print(f"PASSED_TEST_COUNT={declared.passed_test_count}")
    else:
        print(SUCCESS)
        print(f"CATALOG_MIGRATION_COUNT={result.migration_count}")
        print(f"CATALOG_DIGEST_SHA256={result.catalog_digest_sha256}")
        print(f"POSTGRESQL_MAJOR={result.postgres_version_num // 10_000}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
