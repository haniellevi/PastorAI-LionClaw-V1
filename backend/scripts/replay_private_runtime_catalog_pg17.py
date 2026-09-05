#!/usr/bin/env python3
"""Replay the composed public-75 + private-runtime catalog on disposable PG17.

The public V1 catalog is loaded through its existing byte-pinned replay
scaffold.  The private stream is loaded separately through its closed V2 head
and stable no-follow reader, then applied to the same fresh database.  This is
an execution proof only: it never talks to a shared environment, creates a
migration ledger, or opens either operational gate.

The lexical adapter is not used as security evidence.  After every private
append this runner compares a catalog surface before/after, checks the exact
owner/function/RLS/ACL contract, and exercises tenant A/B reads plus denied
direct SELECT/DML as the runtime role.  The receipt is emitted only after all
of those checks pass.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import stat
import sys
from types import ModuleType
from typing import Any, Callable, Mapping, NoReturn
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).absolute().parents[2]
PUBLIC_REPLAY_PATH = (
    REPO_ROOT / "backend" / "scripts" / "replay_migration_catalog_current_head_pg17.py"
)
PRIVATE_CATALOG_PATH = (
    REPO_ROOT / "backend" / "scripts" / "private_runtime_catalog_v1.py"
)
PRIVATE_ADAPTER_PATH = (
    REPO_ROOT / "backend" / "scripts" / "private_runtime_catalog_adapter_v1.py"
)
PRIVATE_INTENT_PATH = (
    REPO_ROOT / "backend" / "scripts" / "private_runtime_intent_runtime_v1.py"
)

PUBLIC_REPLAY_SHA256 = (
    "753abf57747de9a28f6192617dfd7ea348cb7adf302d7acbd57f280de3d8ce3f"
)
PRIVATE_CATALOG_SHA256 = (
    "e957748a6e195466e132c9d5623daab2926a5d1fd2852476d74721fe1f5061c4"
)
PRIVATE_ADAPTER_SHA256 = (
    "80c95ef0d83a6a5a83d07ca39003e3c90a7fc3dd8ce85793ee37c0ee7dc5cde8"
)
PRIVATE_INTENT_SHA256 = (
    "946c1a3f62105291e192ae7e8ed1e4f184f6c4fc200c25e62ecbb8393811b01c"
)

DATABASE_URL_ENV = "MIGRATION_PRIVATE_RUNTIME_REPLAY_DATABASE_URL"
DISPOSABLE_DATABASE = "migration_catalog_current_head_disposable"
CONFIRMATION = "REPLAY_PRIVATE_RUNTIME_CATALOG_PG17_DISPOSABLE"
SUCCESS = "RESULT=PRIVATE_RUNTIME_PROJECTION_REPLAYED_PG17_DISPOSABLE"
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
NEXT_STAGE_BLOCK = "NEXT_STAGE_AUTHORIZED=false"
ENVIRONMENT_BLOCK = "SHARED_ENVIRONMENT_ATTESTATION=false"
TRANSACTION_STATUS_IDLE = 0
HISTORICAL_COUNT = 75
HISTORICAL_DIGEST_SHA256 = (
    "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f"
)
HISTORICAL_LAST_BASENAME = (
    "20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql"
)
MAX_LOCAL_MODULE_BYTES = 4_194_304
MAX_RECEIPT_BYTES = 16_384
PRIVATE_RUNTIME_ROLE = "agent_runtime"
PRIVATE_OWNER_ROLE = "agent_projection_owner"
PRIVATE_SCHEMA = "agent_private"
PRIVATE_RELATIONS = frozenset({"public.pessoas", "public.conversations"})
PRIVATE_FUNCTIONS = frozenset(
    {
        "agent_private.current_tenant_id()",
        "agent_private.load_turn_context(uuid)",
        "public.current_igreja_id()",
    }
)
PRIVATE_POLICIES = frozenset(
    {
        "public.pessoas.agent_projection_owner_select_pessoas",
        "public.pessoas.agent_projection_owner_tenant_barrier_pessoas",
        "public.conversations.agent_projection_owner_select_conversations",
        "public.conversations.agent_projection_owner_tenant_barrier_conversations",
    }
)
PRIVATE_COLUMNS = frozenset(
    {
        "public.pessoas.igreja_id",
        "public.pessoas.id",
        "public.pessoas.optout",
        "public.pessoas.sem_interesse",
        "public.conversations.igreja_id",
        "public.conversations.id",
        "public.conversations.pessoa_id",
        "public.conversations.estado",
    }
)
PRIVATE_ROLE_CONFIG = ("row_security=on", "search_path=pg_catalog, agent_private")
PRIVATE_FUNCTION_CONFIG = frozenset(
    {"search_path=pg_catalog, agent_private", "row_security=on"}
)
TENANT_GUC = "app.tenant_igreja_id"
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)


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


class SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise CliUsageError


@dataclass(frozen=True)
class LoadedPrivateMigration:
    position: int
    name: str
    sha256: str
    sql: str
    intent: Mapping[str, object]


@dataclass(frozen=True)
class LoadedPrivateCatalog:
    digest_sha256: str
    migrations: tuple[LoadedPrivateMigration, ...]


@dataclass(frozen=True)
class CatalogSurface:
    current_role: str
    roles: dict[str, tuple[object, ...]]
    memberships: dict[str, tuple[object, ...]]
    schemas: dict[str, tuple[object, ...]]
    relations: dict[str, tuple[object, ...]]
    columns: dict[str, tuple[object, ...]]
    functions: dict[str, tuple[object, ...]]
    policies: dict[str, tuple[object, ...]]
    defaults: dict[str, tuple[object, ...]]
    types: dict[str, tuple[object, ...]]
    constraints: dict[str, tuple[object, ...]]
    triggers: dict[str, tuple[object, ...]]


@dataclass(frozen=True)
class ReplayResult:
    public_migration_count: int
    public_digest_sha256: str
    private_migration_count: int
    private_digest_sha256: str
    private_last_basename: str
    private_last_sha256: str
    combined_migration_count: int
    postgres_version_num: int
    cross_tenant_evidence: bool
    direct_select_denied: bool
    dml_denied: bool
    catalog_delta_verified: bool


def _stable_stat(value: os.stat_result) -> tuple[int, ...]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_nlink),
        int(value.st_uid),
        int(value.st_gid),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _read_pinned_source(path: Path, expected_sha256: str) -> bytes:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        or any(part in {"", ".", ".."} for part in path.parts[1:])
    ):
        raise SourceContractError
    required = ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required):
        raise SourceContractError
    flags = os.O_RDONLY
    for name in required:
        flags |= getattr(os, name)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > MAX_LOCAL_MODULE_BYTES
        ):
            raise SourceContractError
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise SourceContractError
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            _stable_stat(before) != _stable_stat(after)
            or hashlib.sha256(content).hexdigest() != expected_sha256
        ):
            raise SourceContractError
        return content
    except (OSError, ValueError) as exc:
        raise SourceContractError from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _load_pinned_module(
    *, name: str, path: Path, expected_sha256: str
) -> ModuleType:
    if name in sys.modules:
        raise SourceContractError
    content = _read_pinned_source(path, expected_sha256)
    try:
        code = compile(content, os.fspath(path), "exec", dont_inherit=True)
        module = ModuleType(name)
        module.__file__ = os.fspath(path)
        module.__package__ = ""
        module.__spec__ = None
        sys.modules[name] = module
        exec(code, module.__dict__)
    except Exception as exc:
        sys.modules.pop(name, None)
        raise SourceContractError from exc
    return module


def _load_isolated_public_replay() -> ModuleType:
    """Load the V1 replay without clobbering another in-process V1 proof."""

    names = (
        "_pastorai_public_replay_for_private_runtime_pg17",
        "_pastorai_catalog_snapshot_for_pg17_replay",
        "_pastorai_migration_authoring_for_pg17_replay",
        "_pastorai_validated_migration_catalog_head_verifier_1ced5a715987ce9d",
    )
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    try:
        return _load_pinned_module(
            name="_pastorai_public_replay_for_private_runtime_pg17",
            path=PUBLIC_REPLAY_PATH,
            expected_sha256=PUBLIC_REPLAY_SHA256,
        )
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


public_replay = _load_isolated_public_replay()
private_catalog = _load_pinned_module(
    name="_pastorai_private_catalog_for_private_runtime_pg17",
    path=PRIVATE_CATALOG_PATH,
    expected_sha256=PRIVATE_CATALOG_SHA256,
)
private_intent = _load_pinned_module(
    name="_pastorai_private_intent_for_private_runtime_pg17",
    path=PRIVATE_INTENT_PATH,
    expected_sha256=PRIVATE_INTENT_SHA256,
)
# The adapter imports the V2 intent by this conventional module name when it
# is available.  Install the already-authenticated module under that name
# rather than allowing a second path import, then restore any caller module.
_previous_intent_module = sys.modules.get("private_runtime_intent_runtime_v1")
sys.modules["private_runtime_intent_runtime_v1"] = private_intent
try:
    private_adapter = _load_pinned_module(
        name="_pastorai_private_adapter_for_private_runtime_pg17",
        path=PRIVATE_ADAPTER_PATH,
        expected_sha256=PRIVATE_ADAPTER_SHA256,
    )
finally:
    if _previous_intent_module is None:
        sys.modules.pop("private_runtime_intent_runtime_v1", None)
    else:
        sys.modules["private_runtime_intent_runtime_v1"] = _previous_intent_module


def _validate_private_schema(schema: object) -> None:
    """Require the head schema's nested objects to be closed before replay."""

    if type(schema) is not dict or schema.get("type") != "object":
        raise SourceContractError
    if schema.get("additionalProperties") is not False:
        raise SourceContractError
    definitions = schema.get("$defs")
    if type(definitions) is not dict or set(definitions) != {
        "entry",
        "batch",
        "currentHead",
        "limits",
    }:
        raise SourceContractError
    for definition in definitions.values():
        if (
            type(definition) is not dict
            or definition.get("type") != "object"
            or definition.get("additionalProperties") is not False
            or type(definition.get("required")) is not list
            or type(definition.get("properties")) is not dict
            or set(definition["required"]) != set(definition["properties"])
        ):
            raise SourceContractError


def _load_composed_source() -> tuple[Any, str, LoadedPrivateCatalog]:
    """Freeze public and private source bytes before a database connection."""

    try:
        public_loaded = public_replay._load_current_catalog()
        scaffold = public_replay._load_historical_compatibility_scaffold()
    except Exception as exc:
        raise SourceContractError from exc
    if (
        len(public_loaded.migrations) != HISTORICAL_COUNT
        or public_loaded.digest_sha256 != HISTORICAL_DIGEST_SHA256
        or public_loaded.migrations[-1].name != HISTORICAL_LAST_BASENAME
        or any(item.scope is not None for item in public_loaded.migrations)
    ):
        raise SourceContractError

    try:
        # Re-run the private closed-head checks with the already authenticated
        # module objects.  The source verifier is intentionally not imported
        # here: its historical compatibility imports are not part of this
        # runner's pinned execution surface.
        _validate_private_schema(
            private_catalog.read_json(private_catalog.SCHEMA_PATH)
        )
        head = private_catalog.read_json(private_catalog.HEAD_PATH)
        scanned = private_catalog.scan_directory(private_catalog.MIGRATIONS_DIR)
        entries = private_catalog.validate_head(head, scanned_entries=scanned)
    except Exception as exc:
        raise SourceContractError from exc
    if (
        head.get("historical_public_migration_count") != HISTORICAL_COUNT
        or head.get("historical_public_catalog_digest_sha256")
        != HISTORICAL_DIGEST_SHA256
        or head.get("historical_public_last_basename")
        != HISTORICAL_LAST_BASENAME
        or head.get("current_head", {}).get("private_migration_count")
        != len(entries)
        or not entries
    ):
        raise SourceContractError

    loaded_private: list[LoadedPrivateMigration] = []
    for expected_position, entry in enumerate(entries):
        if entry["position"] != expected_position:
            raise SourceContractError
        try:
            content = private_catalog.read_file(
                private_catalog.MIGRATIONS_DIR / entry["name"]
            )
            candidate = private_adapter.validate_private_runtime_candidate(
                content,
                basename=entry["name"],
                expected_sha=None,
            )
            sql = content.decode("utf-8", errors="strict")
        except Exception as exc:
            raise SourceContractError from exc
        if (
            candidate.content_sha256 != entry["sha256"]
            or len(content) != entry["size_bytes"]
            or candidate.intent.get("scope") != "PRIVATE_RUNTIME"
        ):
            raise SourceContractError
        loaded_private.append(
            LoadedPrivateMigration(
                position=expected_position,
                name=entry["name"],
                sha256=entry["sha256"],
                sql=sql,
                intent=candidate.intent,
            )
        )
    if private_catalog.private_digest([dict(entry) for entry in entries]) != head[
        "current_head"
    ]["private_digest_sha256"]:
        raise SourceContractError
    return (
        public_loaded,
        scaffold,
        LoadedPrivateCatalog(
            digest_sha256=head["current_head"]["private_digest_sha256"],
            migrations=tuple(loaded_private),
        ),
    )


def _read_disposable_url() -> tuple[str, str]:
    raw = os.environ.get(DATABASE_URL_ENV)
    if (
        raw is None
        or not raw
        or raw != raw.strip()
        or len(raw) > 4096
        or any(ord(character) < 0x20 for character in raw)
    ):
        raise TargetGuardError
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port
        address = ipaddress.ip_address(host) if host is not None else None
    except (ValueError, UnicodeError) as exc:
        raise TargetGuardError from exc
    if (
        parsed.scheme not in {"postgresql", "postgres"}
        or address is None
        or not address.is_loopback
        or parsed.path != f"/{DISPOSABLE_DATABASE}"
        or parsed.query
        or parsed.fragment
        or parsed.username != "postgres"
        or not parsed.password
        or port is None
        or port < 1024
        or port > 65535
    ):
        raise TargetGuardError
    return raw, DISPOSABLE_DATABASE


def _rows_map(cursor: Any, sql: str, *, width: int) -> dict[str, tuple[object, ...]]:
    try:
        cursor.execute(sql)
        rows = cursor.fetchall()
    except Exception as exc:
        raise DatabaseContractError from exc
    if type(rows) is not list:
        raise DatabaseContractError
    result: dict[str, tuple[object, ...]] = {}
    for row in rows:
        if type(row) not in {tuple, list} or len(row) != width:
            raise DatabaseContractError
        key = row[0]
        if type(key) is not str or not key or key in result:
            raise DatabaseContractError
        result[key] = tuple(row[1:])
    return result


def _capture_catalog_surface(cursor: Any) -> CatalogSurface:
    try:
        cursor.execute("select current_user")
        current_row = cursor.fetchone()
    except Exception as exc:
        raise DatabaseContractError from exc
    if (
        type(current_row) not in {tuple, list}
        or len(current_row) != 1
        or type(current_row[0]) is not str
        or not current_row[0]
    ):
        raise DatabaseContractError
    roles = _rows_map(
        cursor,
        """
        select role.rolname,
               role.rolcanlogin,
               role.rolinherit,
               role.rolsuper,
               role.rolbypassrls,
               role.rolcreatedb,
               role.rolcreaterole,
               role.rolreplication,
               role.rolconnlimit,
               role.rolvaliduntil is null,
               coalesce(role.rolconfig, array[]::text[]),
               exists (
                 select 1 from pg_catalog.pg_auth_members membership
                 where membership.member = role.oid
                     or membership.roleid = role.oid
               ),
               pg_catalog.md5(coalesce(credential.rolpassword, ''))
          from pg_catalog.pg_roles role
          join pg_catalog.pg_authid credential on credential.oid = role.oid
         order by role.rolname
        """,
        width=13,
    )
    memberships = _rows_map(
        cursor,
        """
        select member_role.rolname || ':' || granted_role.rolname,
               membership.admin_option,
               membership.grantor::pg_catalog.regrole::text
          from pg_catalog.pg_auth_members membership
          join pg_catalog.pg_roles member_role on member_role.oid = membership.member
          join pg_catalog.pg_roles granted_role on granted_role.oid = membership.roleid
         order by member_role.rolname, granted_role.rolname
        """,
        width=3,
    )
    schemas = _rows_map(
        cursor,
        """
        select namespace.nspname,
               namespace.nspowner::pg_catalog.regrole::text,
               namespace.nspacl::text
          from pg_catalog.pg_namespace namespace
         where namespace.nspname not in ('pg_catalog', 'information_schema')
         order by namespace.nspname
        """,
        width=3,
    )
    relations = _rows_map(
        cursor,
        """
        select namespace.nspname || '.' || relation.relname,
               relation.relkind,
               relation.relowner::pg_catalog.regrole::text,
               relation.relacl::text,
               relation.relrowsecurity,
               relation.relforcerowsecurity
          from pg_catalog.pg_class relation
          join pg_catalog.pg_namespace namespace
            on namespace.oid = relation.relnamespace
         where namespace.nspname not in ('pg_catalog', 'information_schema')
           and relation.relkind in ('r', 'p', 'v', 'm', 'S', 'f', 'c')
         order by namespace.nspname, relation.relname
        """,
        width=6,
    )
    columns = _rows_map(
        cursor,
        """
        select namespace.nspname || '.' || relation.relname || '.' || attribute.attname,
               attribute.atttypid::pg_catalog.regtype::text,
               attribute.atttypmod,
               attribute.attnotnull,
               pg_catalog.pg_get_expr(defaults.adbin, defaults.adrelid),
               attribute.attidentity,
               attribute.attgenerated,
               attribute.attacl::text
          from pg_catalog.pg_attribute attribute
          join pg_catalog.pg_class relation on relation.oid = attribute.attrelid
          join pg_catalog.pg_namespace namespace
            on namespace.oid = relation.relnamespace
          left join pg_catalog.pg_attrdef defaults
            on defaults.adrelid = attribute.attrelid
           and defaults.adnum = attribute.attnum
         where namespace.nspname not in ('pg_catalog', 'information_schema')
           and attribute.attnum > 0
           and not attribute.attisdropped
         order by namespace.nspname, relation.relname, attribute.attnum
        """,
        width=8,
    )
    functions = _rows_map(
        cursor,
        """
        select namespace.nspname || '.' || procedure.proname || '('
               || coalesce(
                    pg_catalog.array_to_string(
                      ARRAY(
                        select pg_catalog.format_type(argument_item.argtype, null)
                          from pg_catalog.unnest(
                            procedure.proargtypes::pg_catalog.oid[]
                          ) argument_item(argtype)
                      ),
                      ', '
                    ),
                    ''
                  )
               || ')',
               procedure.proowner::pg_catalog.regrole::text,
               language.lanname,
               procedure.prorettype::pg_catalog.regtype::text,
               procedure.pronargs,
               procedure.proretset,
               procedure.prosecdef,
               procedure.provolatile,
               procedure.proisstrict,
               coalesce(procedure.proconfig, array[]::text[]),
               (
                 select coalesce(
                   pg_catalog.jsonb_agg(
                     pg_catalog.jsonb_build_array(
                       coalesce(grantee.rolname, 'PUBLIC'),
                       privilege.privilege_type,
                       privilege.is_grantable,
                       grantor.rolname
                     )
                     order by privilege.grantee,
                              privilege.privilege_type,
                              privilege.is_grantable,
                              privilege.grantor
                   ),
                   '[]'::pg_catalog.jsonb
                 )
                   from pg_catalog.aclexplode(
                     coalesce(
                       procedure.proacl,
                       pg_catalog.acldefault('f', procedure.proowner)
                     )
                   ) privilege
                   left join pg_catalog.pg_roles grantee
                     on grantee.oid = privilege.grantee
                   join pg_catalog.pg_roles grantor
                     on grantor.oid = privilege.grantor
               ),
               pg_catalog.pg_get_function_result(procedure.oid),
               procedure.prosrc
          from pg_catalog.pg_proc procedure
          join pg_catalog.pg_namespace namespace
            on namespace.oid = procedure.pronamespace
          join pg_catalog.pg_language language on language.oid = procedure.prolang
         where namespace.nspname not in ('pg_catalog', 'information_schema')
         order by namespace.nspname, procedure.proname,
                  pg_catalog.oidvectortypes(procedure.proargtypes)
        """,
        width=13,
    )
    policies = _rows_map(
        cursor,
        """
        select namespace.nspname || '.' || relation.relname || '.' || policy.polname,
               policy.polcmd,
               policy.polpermissive,
               policy.polroles::text,
               pg_catalog.pg_get_expr(policy.polqual, policy.polrelid),
               pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid)
          from pg_catalog.pg_policy policy
          join pg_catalog.pg_class relation on relation.oid = policy.polrelid
          join pg_catalog.pg_namespace namespace
            on namespace.oid = relation.relnamespace
         where namespace.nspname not in ('pg_catalog', 'information_schema')
         order by namespace.nspname, relation.relname, policy.polname
        """,
        width=6,
    )
    defaults = _rows_map(
        cursor,
        """
        select role.rolname || ':' || coalesce(namespace.nspname, '') || ':'
               || defaults.defaclobjtype::text,
               defaults.defaclacl::text
          from pg_catalog.pg_default_acl defaults
          join pg_catalog.pg_roles role on role.oid = defaults.defaclrole
          left join pg_catalog.pg_namespace namespace
            on namespace.oid = defaults.defaclnamespace
         order by role.rolname, namespace.nspname, defaults.defaclobjtype
        """,
        width=2,
    )
    types = _rows_map(
        cursor,
        """
        select namespace.nspname || '.' || type.typname,
               type.typtype,
               type.typcategory,
               type.typrelid::text,
               type.typnotnull,
               type.typacl::text
          from pg_catalog.pg_type type
          join pg_catalog.pg_namespace namespace
            on namespace.oid = type.typnamespace
         where namespace.nspname not in ('pg_catalog', 'information_schema')
           and type.typtype in ('b', 'e', 'c', 'd', 'm')
         order by namespace.nspname, type.typname
        """,
        width=6,
    )
    constraints = _rows_map(
        cursor,
        """
        select namespace.nspname || '.' || relation.relname || '.' || constraint_record.conname,
               constraint_record.contype,
               constraint_record.convalidated,
               constraint_record.condeferrable,
               constraint_record.condeferred,
               pg_catalog.pg_get_constraintdef(constraint_record.oid, true)
          from pg_catalog.pg_constraint constraint_record
          join pg_catalog.pg_class relation on relation.oid = constraint_record.conrelid
          join pg_catalog.pg_namespace namespace
            on namespace.oid = relation.relnamespace
         where namespace.nspname not in ('pg_catalog', 'information_schema')
         order by namespace.nspname, relation.relname, constraint_record.conname
        """,
        width=6,
    )
    triggers = _rows_map(
        cursor,
        """
        select namespace.nspname || '.' || relation.relname || '.' || trigger_record.tgname,
               trigger_record.tgenabled,
               trigger_record.tgtype,
               trigger_record.tgdeferrable,
               trigger_record.tginitdeferred,
               pg_catalog.pg_get_triggerdef(trigger_record.oid, true)
          from pg_catalog.pg_trigger trigger_record
          join pg_catalog.pg_class relation on relation.oid = trigger_record.tgrelid
          join pg_catalog.pg_namespace namespace
            on namespace.oid = relation.relnamespace
         where namespace.nspname not in ('pg_catalog', 'information_schema')
           and not trigger_record.tgisinternal
         order by namespace.nspname, relation.relname, trigger_record.tgname
        """,
        width=6,
    )
    return CatalogSurface(
        current_role=current_row[0],
        roles=roles,
        memberships=memberships,
        schemas=schemas,
        relations=relations,
        columns=columns,
        functions=functions,
        policies=policies,
        defaults=defaults,
        types=types,
        constraints=constraints,
        triggers=triggers,
    )


def _changed_keys(
    before: dict[str, tuple[object, ...]], after: dict[str, tuple[object, ...]]
) -> set[str]:
    return {
        key
        for key in set(before) | set(after)
        if before.get(key) != after.get(key)
    }


def _normalise_function_acl(value: object) -> frozenset[tuple[str, str, bool, str]]:
    """Return a strict, structured function ACL snapshot.

    The capture query builds this value from ``pg_catalog.aclexplode``.  Keep
    the validation closed here as well so a fake or malformed catalog surface
    cannot turn an ACL text fragment into an accepted authorization change.
    """

    if type(value) not in {list, tuple}:
        raise DatabaseContractError
    entries: list[tuple[str, str, bool, str]] = []
    for item in value:
        if type(item) not in {list, tuple} or len(item) != 4:
            raise DatabaseContractError
        grantee, privilege, grantable, grantor = item
        if (
            type(grantee) is not str
            or not grantee
            or type(privilege) is not str
            or not privilege
            or type(grantable) is not bool
            or type(grantor) is not str
            or not grantor
        ):
            raise DatabaseContractError
        entries.append((grantee, privilege, grantable, grantor))
    result = frozenset(entries)
    if len(result) != len(entries):
        raise DatabaseContractError
    return result


def _validate_public_helper_delta(
    before: CatalogSurface, after: CatalogSurface
) -> None:
    """Allow exactly the declared non-grantable EXECUTE grant on the web helper."""

    key = "public.current_igreja_id()"
    prior = before.functions.get(key)
    current = after.functions.get(key)
    if (
        type(prior) is not tuple
        or type(current) is not tuple
        or len(prior) != 12
        or len(current) != 12
    ):
        raise DatabaseContractError

    # The ACL is the ninth value after the dictionary key.  Every other
    # function property (owner, language, signature, volatility, config,
    # result and body) is immutable across this private append.
    if prior[:9] + prior[10:] != current[:9] + current[10:]:
        raise DatabaseContractError
    prior_acl = _normalise_function_acl(prior[9])
    current_acl = _normalise_function_acl(current[9])
    added = current_acl - prior_acl
    removed = prior_acl - current_acl
    if removed or added != {
        ("agent_projection_owner", "EXECUTE", False, before.current_role)
    }:
        raise DatabaseContractError


def _validate_column_delta(before: CatalogSurface, after: CatalogSurface) -> None:
    """Permit only the declared source-column ACL fields to change."""

    if set(before.columns) != set(after.columns):
        raise DatabaseContractError
    for key, prior in before.columns.items():
        current = after.columns[key]
        if (
            type(prior) is not tuple
            or type(current) is not tuple
            or len(prior) != 7
            or len(current) != 7
        ):
            raise DatabaseContractError
        if key in PRIVATE_COLUMNS:
            # The final value is attacl. Type/modifier, nullability, default,
            # identity and generation metadata remain byte-for-byte equal.
            if prior[:6] != current[:6]:
                raise DatabaseContractError
        elif prior != current:
            raise DatabaseContractError


def _validate_catalog_delta(
    before: CatalogSurface,
    after: CatalogSurface,
    intent: Mapping[str, object],
) -> None:
    if before.current_role != after.current_role:
        raise DatabaseContractError
    declared = intent.get("affected_objects")
    if (
        type(declared) is not list
        or any(type(item) is not str for item in declared)
        or set(declared) != {
        "agent_private",
        "agent_private.current_tenant_id()",
        "agent_private.load_turn_context(uuid)",
        "agent_projection_owner",
        "agent_runtime",
        "public.conversations",
        "public.current_igreja_id()",
        "public.pessoas",
        }
    ):
        raise DatabaseContractError
    if before.relations != after.relations:
        raise DatabaseContractError
    _validate_column_delta(before, after)
    _validate_public_helper_delta(before, after)
    checks: tuple[tuple[str, dict[str, tuple[object, ...]], dict[str, tuple[object, ...]], Callable[[str], bool]], ...] = (
        (
            "roles",
            before.roles,
            after.roles,
            lambda key: key == PRIVATE_OWNER_ROLE,
        ),
        (
            "memberships",
            before.memberships,
            after.memberships,
            lambda _key: False,
        ),
        (
            "schemas",
            before.schemas,
            after.schemas,
            lambda key: key == PRIVATE_SCHEMA,
        ),
        (
            "relations",
            before.relations,
            after.relations,
            lambda key: key in PRIVATE_RELATIONS,
        ),
        (
            "columns",
            before.columns,
            after.columns,
            lambda key: key in PRIVATE_COLUMNS,
        ),
        (
            "functions",
            before.functions,
            after.functions,
            lambda key: key in PRIVATE_FUNCTIONS,
        ),
        (
            "policies",
            before.policies,
            after.policies,
            lambda key: key in PRIVATE_POLICIES,
        ),
        (
            "defaults",
            before.defaults,
            after.defaults,
            lambda key: (
                key.startswith(before.current_role + ":agent_private:")
                and key.rsplit(":", 1)[-1] in {"r", "S", "f"}
            ),
        ),
        ("types", before.types, after.types, lambda _key: False),
        ("constraints", before.constraints, after.constraints, lambda _key: False),
        ("triggers", before.triggers, after.triggers, lambda _key: False),
    )
    for _name, prior, current, allowed in checks:
        changed = _changed_keys(prior, current)
        if any(not allowed(key) for key in changed):
            raise DatabaseContractError


def _one(cursor: Any, sql: str, parameters: tuple[object, ...] = ()) -> tuple[object, ...]:
    try:
        cursor.execute(sql, parameters)
        row = cursor.fetchone()
    except Exception as exc:
        raise DatabaseContractError from exc
    if type(row) not in {tuple, list}:
        raise DatabaseContractError
    return tuple(row)


def _normalise_sql(value: object) -> str:
    if type(value) is not str:
        raise DatabaseContractError
    # PostgreSQL exposes function bodies with formatting chosen by the DDL
    # parser.  Remove insignificant whitespace/case only outside quoted SQL
    # literals; changing text inside a literal must remain a contract change.
    result: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(value):
        character = value[index]
        if quote is None:
            if character.isspace():
                index += 1
                continue
            if character in {"'", '"'}:
                quote = character
                result.append(character)
            else:
                result.append(character.casefold())
            index += 1
            continue
        result.append(character)
        if character == quote:
            if index + 1 < len(value) and value[index + 1] == quote:
                result.append(value[index + 1])
                index += 2
                continue
            quote = None
        index += 1
    return "".join(result)


def _validate_role_and_schema(cursor: Any) -> tuple[int, int]:
    owner_row = _one(
        cursor,
        """
        select oid from pg_catalog.pg_roles where rolname = %s
        """,
        (PRIVATE_OWNER_ROLE,),
    )
    runtime_row = _one(
        cursor,
        """
        select oid from pg_catalog.pg_roles where rolname = %s
        """,
        (PRIVATE_RUNTIME_ROLE,),
    )
    if (
        len(owner_row) != 1
        or len(runtime_row) != 1
        or type(owner_row[0]) is not int
        or type(runtime_row[0]) is not int
    ):
        raise DatabaseContractError
    owner_oid = owner_row[0]
    runtime_oid = runtime_row[0]
    role = _one(
        cursor,
        """
        select role.rolcanlogin,
               role.rolinherit,
               role.rolsuper,
               role.rolbypassrls,
               role.rolcreatedb,
               role.rolcreaterole,
               role.rolreplication,
               role.rolconnlimit,
               role.rolvaliduntil is null,
               coalesce(role.rolconfig, array[]::text[]),
               credential.rolpassword is null,
               exists (
                 select 1 from pg_catalog.pg_auth_members membership
                  where membership.member = role.oid
                     or membership.roleid = role.oid
               )
          from pg_catalog.pg_roles role
          join pg_catalog.pg_authid credential on credential.oid = role.oid
         where role.oid = %s
        """,
        (owner_oid,),
    )
    if (
        len(role) != 12
        or role[:7] != (False, False, False, False, False, False, False)
        or role[7] != -1
        or role[8] is not True
        or tuple(role[9] or ()) != PRIVATE_ROLE_CONFIG
        or role[10] is not True
        or role[11] is not False
    ):
        raise DatabaseContractError
    runtime = _one(
        cursor,
        """
        select role.rolcanlogin,
               role.rolinherit,
               role.rolsuper,
               role.rolbypassrls,
               role.rolcreatedb,
               role.rolcreaterole,
               role.rolreplication,
               role.rolconnlimit,
               role.rolvaliduntil is null,
               coalesce(role.rolconfig, array[]::text[]),
               credential.rolpassword is null,
               exists (
                 select 1 from pg_catalog.pg_auth_members membership
                  where membership.member = role.oid
                     or membership.roleid = role.oid
               )
          from pg_catalog.pg_roles role
          join pg_catalog.pg_authid credential on credential.oid = role.oid
         where role.oid = %s
        """,
        (runtime_oid,),
    )
    if (
        len(runtime) != 12
        or runtime[:7] != (False, False, False, False, False, False, False)
        or runtime[7] != -1
        or runtime[8] is not True
        or tuple(runtime[9] or ()) != PRIVATE_ROLE_CONFIG
        or runtime[10] is not True
        or runtime[11] is not False
    ):
        raise DatabaseContractError
    schema = _one(
        cursor,
        """
        select namespace.nspowner,
               pg_catalog.has_schema_privilege(%s, 'agent_private', 'USAGE'),
               pg_catalog.has_schema_privilege(%s, 'agent_private', 'CREATE'),
               pg_catalog.has_schema_privilege(%s, 'agent_private', 'USAGE')
          from pg_catalog.pg_namespace namespace
         where namespace.nspname = 'agent_private'
        """,
        (PRIVATE_RUNTIME_ROLE, PRIVATE_OWNER_ROLE, PRIVATE_OWNER_ROLE),
    )
    if (
        len(schema) != 4
        or type(schema[0]) is not int
        or schema[1] is not True
        or schema[2] is not False
        or schema[3] is not True
    ):
        raise DatabaseContractError
    migration_owner = _one(
        cursor,
        "select pg_catalog.to_regrole(current_user)::oid",
    )
    if (
        len(migration_owner) != 1
        or type(migration_owner[0]) is not int
        or schema[0] != migration_owner[0]
    ):
        raise DatabaseContractError
    cursor.execute(
        """
        select privilege.grantee,
               privilege.privilege_type,
               privilege.is_grantable
          from pg_catalog.pg_namespace namespace
          left join lateral pg_catalog.aclexplode(
            coalesce(
              namespace.nspacl,
              pg_catalog.acldefault('n', namespace.nspowner)
            )
          ) privilege on true
         where namespace.nspname = 'agent_private'
         order by privilege.grantee, privilege.privilege_type
        """
    )
    acl_rows = cursor.fetchall()
    if type(acl_rows) is not list:
        raise DatabaseContractError
    expected_acl = {
        (migration_owner[0], "USAGE", False),
        (migration_owner[0], "CREATE", False),
        (runtime_oid, "USAGE", False),
        (owner_oid, "USAGE", False),
    }
    actual_acl = {
        (row[0], row[1], row[2])
        for row in acl_rows
        if type(row) in {tuple, list} and len(row) == 3 and row[0] is not None
    }
    if (
        len(actual_acl) != len(acl_rows)
        or actual_acl != expected_acl
        or any(
            type(row) not in {tuple, list}
            or len(row) != 3
            or type(row[0]) is not int
            or type(row[1]) is not str
            or type(row[2]) is not bool
            for row in acl_rows
        )
    ):
        raise DatabaseContractError
    return owner_oid, runtime_oid


def _validate_projection_function(
    cursor: Any,
    *,
    owner_oid: int,
    runtime_oid: int,
    private: LoadedPrivateMigration,
) -> None:
    row = _one(
        cursor,
        """
        select procedure.proowner,
               language.lanname,
               procedure.prorettype::pg_catalog.regtype::text,
               procedure.pronargs,
               pg_catalog.oidvectortypes(procedure.proargtypes),
               procedure.proretset,
               procedure.prosecdef,
               procedure.provolatile,
               procedure.proisstrict,
               coalesce(procedure.proconfig, array[]::text[]),
               procedure.prosrc,
               pg_catalog.pg_get_function_result(procedure.oid),
               procedure.proacl::text
          from pg_catalog.pg_proc procedure
          join pg_catalog.pg_namespace namespace
            on namespace.oid = procedure.pronamespace
          join pg_catalog.pg_language language on language.oid = procedure.prolang
         where namespace.nspname = 'agent_private'
           and procedure.proname = 'load_turn_context'
           and procedure.pronargs = 1
        """,
    )
    if len(row) != 13:
        raise DatabaseContractError
    expected_columns = private.intent["private_runtime_controls"]["projection_function"][
        "return_columns"
    ]
    if type(expected_columns) is not list:
        raise DatabaseContractError
    expected_result = "TABLE(" + ", ".join(
        f"{column['name']} {column['type']}" for column in expected_columns
    ) + ")"
    if (
        row[0] != owner_oid
        or row[1] != "plpgsql"
        or row[2] != "record"
        or row[3] != 1
        or row[4] != "uuid"
        or row[5] is not True
        or row[6] is not True
        or row[7] != "s"
        or row[8] is not True
        or set(row[9] or ()) != PRIVATE_FUNCTION_CONFIG
        or type(row[10]) is not str
        or "agent_private.current_tenant_id()" not in row[10]
        or "public.conversations" not in row[10]
        or "public.pessoas" not in row[10]
        or "jsonb" in row[10].casefold()
        or _normalise_sql(row[11]) != _normalise_sql(expected_result)
    ):
        raise DatabaseContractError
    acl = _one(
        cursor,
        """
        select pg_catalog.has_function_privilege(%s, 'agent_private.load_turn_context(uuid)', 'EXECUTE'),
               pg_catalog.has_function_privilege(%s, 'agent_private.load_turn_context(uuid)', 'EXECUTE'),
               exists (
                 select 1
                   from pg_catalog.aclexplode(
                     coalesce(
                       procedure.proacl,
                       pg_catalog.acldefault('f', procedure.proowner)
                     )
                   ) privilege
                  where privilege.grantee = 0
                    and privilege.privilege_type = 'EXECUTE'
               ),
               exists (
                 select 1
                   from pg_catalog.aclexplode(
                     coalesce(
                       procedure.proacl,
                       pg_catalog.acldefault('f', procedure.proowner)
                     )
                   ) privilege
                     where privilege.grantee not in (%s, %s)
                     or privilege.privilege_type <> 'EXECUTE'
                     or privilege.is_grantable
               )
          from pg_catalog.pg_proc procedure
         where procedure.oid = pg_catalog.to_regprocedure(
           'agent_private.load_turn_context(uuid)'
         )
        """,
        (PRIVATE_OWNER_ROLE, PRIVATE_RUNTIME_ROLE, owner_oid, runtime_oid),
    )
    if acl != (True, True, False, False):
        raise DatabaseContractError


def _validate_tenant_helper(cursor: Any, *, runtime_oid: int, owner_oid: int) -> None:
    """Prove V1 helper immutability plus the one explicit owner grant."""

    row = _one(
        cursor,
        """
        select procedure.proowner,
               language.lanname,
               procedure.prorettype::pg_catalog.regtype::text,
               procedure.pronargs,
               procedure.proretset,
               procedure.prosecdef,
               procedure.provolatile,
               procedure.proisstrict,
               procedure.proleakproof,
               coalesce(procedure.proconfig, array[]::text[]),
               procedure.prosrc,
               procedure.proacl::text
          from pg_catalog.pg_proc procedure
          join pg_catalog.pg_namespace namespace
            on namespace.oid = procedure.pronamespace
          join pg_catalog.pg_language language on language.oid = procedure.prolang
         where procedure.oid = pg_catalog.to_regprocedure(
           'agent_private.current_tenant_id()'
         )
        """,
    )
    expected_source = (
        "select nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), "
        "'')::pg_catalog.uuid"
    )
    if (
        len(row) != 12
        or type(row[0]) is not int
        or row[1] != "sql"
        or row[2] != "uuid"
        or row[3] != 0
        or row[4] is not False
        or row[5] is not False
        or row[6] != "s"
        or row[7] is not False
        or row[8] is not False
        or tuple(row[9] or ()) != ("search_path=pg_catalog",)
        or _normalise_sql(row[10]) != _normalise_sql(expected_source)
    ):
        raise DatabaseContractError
    helper_oid = row[0]
    current_owner = _one(
        cursor,
        "select pg_catalog.to_regrole(current_user)::oid",
    )
    if len(current_owner) != 1 or type(current_owner[0]) is not int:
        raise DatabaseContractError
    migration_owner_oid = current_owner[0]
    if helper_oid != migration_owner_oid:
        raise DatabaseContractError
    acl = _one(
        cursor,
        """
        select pg_catalog.has_function_privilege(
                 %s, 'agent_private.current_tenant_id()', 'EXECUTE'
               ),
               pg_catalog.has_function_privilege(
                 %s, 'agent_private.current_tenant_id()', 'EXECUTE'
               ),
               pg_catalog.has_function_privilege(
                 %s, 'agent_private.current_tenant_id()', 'EXECUTE'
               ),
               pg_catalog.has_function_privilege(
                 'public', 'agent_private.current_tenant_id()', 'EXECUTE'
               ),
               exists (
                 select 1
                   from pg_catalog.aclexplode(
                     coalesce(
                       procedure.proacl,
                       pg_catalog.acldefault('f', procedure.proowner)
                     )
                   ) privilege
                  where privilege.grantee not in (%s, %s, %s)
                     or privilege.privilege_type <> 'EXECUTE'
                     or privilege.is_grantable
               )
          from pg_catalog.pg_proc procedure
         where procedure.oid = pg_catalog.to_regprocedure(
           'agent_private.current_tenant_id()'
         )
        """,
        (
            PRIVATE_RUNTIME_ROLE,
            PRIVATE_OWNER_ROLE,
            migration_owner_oid,
            runtime_oid,
            owner_oid,
            migration_owner_oid,
        ),
    )
    if acl != (True, True, True, False, False):
        raise DatabaseContractError


def _validate_default_acl(
    cursor: Any, *, runtime_oid: int, owner_oid: int
) -> None:
    """Reject PUBLIC/restricted-role privileges in private default ACLs."""

    migration_owner = _one(
        cursor,
        "select pg_catalog.to_regrole(current_user)::oid",
    )
    if len(migration_owner) != 1 or type(migration_owner[0]) is not int:
        raise DatabaseContractError
    migration_owner_oid = migration_owner[0]
    cursor.execute(
        """
        select defaults.defaclrole,
               defaults.defaclobjtype,
               privilege.grantee,
               privilege.privilege_type,
               privilege.is_grantable
          from pg_catalog.pg_default_acl defaults
          join pg_catalog.pg_namespace namespace
            on namespace.oid = defaults.defaclnamespace
          cross join lateral pg_catalog.aclexplode(defaults.defaclacl) privilege
         where namespace.nspname = 'agent_private'
           and defaults.defaclobjtype in ('r', 'S', 'f')
         order by defaults.defaclrole, defaults.defaclobjtype,
                  privilege.grantee, privilege.privilege_type
        """
    )
    rows = cursor.fetchall()
    if type(rows) is not list:
        raise DatabaseContractError
    for row in rows:
        if (
            type(row) not in {tuple, list}
            or len(row) != 5
            or type(row[0]) is not int
            or type(row[1]) is not str
            or type(row[2]) is not int
            or type(row[3]) is not str
            or type(row[4]) is not bool
            or row[1] not in {"r", "S", "f"}
            or row[2] in {0, runtime_oid, owner_oid}
            or row[4]
        ):
            raise DatabaseContractError
        if row[0] == migration_owner_oid and row[2] != migration_owner_oid:
            raise DatabaseContractError


def _validate_public_relation_contract(
    cursor: Any,
    *,
    owner_oid: int,
    runtime_oid: int,
) -> None:
    for relation in sorted(PRIVATE_RELATIONS):
        schema_name, relation_name = relation.split(".", 1)
        metadata = _one(
            cursor,
            """
            select relation.relrowsecurity,
                   relation.relforcerowsecurity,
                   pg_catalog.has_table_privilege(%s, %s, 'SELECT'),
                   pg_catalog.has_table_privilege(%s, %s, 'SELECT')
              from pg_catalog.pg_class relation
              join pg_catalog.pg_namespace namespace
                on namespace.oid = relation.relnamespace
             where namespace.nspname = %s and relation.relname = %s
            """,
            (
                PRIVATE_RUNTIME_ROLE,
                relation,
                PRIVATE_OWNER_ROLE,
                relation,
                schema_name,
                relation_name,
            ),
        )
        if metadata != (True, False, False, False):
            raise DatabaseContractError
        expected_columns = (
            ("igreja_id", "id", "optout", "sem_interesse")
            if relation == "public.pessoas"
            else ("igreja_id", "id", "pessoa_id", "estado")
        )
        cursor.execute(
            """
            select attribute.attname,
                   pg_catalog.has_column_privilege(%s, %s, attribute.attname, 'SELECT'),
                   pg_catalog.has_column_privilege(%s, %s, attribute.attname, 'SELECT'),
                   exists (
                     select 1
                       from pg_catalog.aclexplode(attribute.attacl) privilege
                      where privilege.grantee = %s
                        and privilege.privilege_type = 'SELECT'
                        and privilege.is_grantable
                   )
              from pg_catalog.pg_attribute attribute
              join pg_catalog.pg_class relation_record
                on relation_record.oid = attribute.attrelid
              join pg_catalog.pg_namespace namespace
                on namespace.oid = relation_record.relnamespace
             where namespace.nspname = %s
               and relation_record.relname = %s
               and attribute.attnum > 0
               and not attribute.attisdropped
             order by attribute.attnum
            """,
            (
                PRIVATE_OWNER_ROLE,
                relation,
                PRIVATE_RUNTIME_ROLE,
                relation,
                owner_oid,
                schema_name,
                relation_name,
            ),
        )
        rows = cursor.fetchall()
        if type(rows) is not list or not rows:
            raise DatabaseContractError
        known = {row[0] for row in rows if type(row) in {tuple, list} and len(row) == 4}
        if not set(expected_columns).issubset(known):
            raise DatabaseContractError
        for row in rows:
            if type(row) not in {tuple, list} or len(row) != 4:
                raise DatabaseContractError
            if row[0] in expected_columns:
                if row[1] is not True or row[2] is not False or row[3] is not False:
                    raise DatabaseContractError
            elif row[1] is not False or row[2] is not False:
                raise DatabaseContractError

        cursor.execute(
            """
            select attribute.attname,
                   privilege.grantee,
                   privilege.privilege_type,
                   privilege.is_grantable
              from pg_catalog.pg_attribute attribute
              join pg_catalog.pg_class relation_record
                on relation_record.oid = attribute.attrelid
              join pg_catalog.pg_namespace namespace
                on namespace.oid = relation_record.relnamespace
              left join lateral pg_catalog.aclexplode(attribute.attacl)
                privilege on true
             where namespace.nspname = %s
               and relation_record.relname = %s
               and attribute.attnum > 0
               and not attribute.attisdropped
             order by attribute.attnum, privilege.grantee,
                      privilege.privilege_type
            """,
            (schema_name, relation_name),
        )
        acl_rows = cursor.fetchall()
        if type(acl_rows) is not list:
            raise DatabaseContractError
        direct_acl: dict[str, set[tuple[object, ...]]] = {}
        for row in acl_rows:
            if type(row) not in {tuple, list} or len(row) != 4:
                raise DatabaseContractError
            column_name = row[0]
            if type(column_name) is not str:
                raise DatabaseContractError
            entries = direct_acl.setdefault(column_name, set())
            if row[1] is not None:
                if (
                    type(row[1]) is not int
                    or type(row[2]) is not str
                    or type(row[3]) is not bool
                ):
                    raise DatabaseContractError
                entries.add((row[1], row[2], row[3]))
        for column_name in direct_acl:
            expected_acl = (
                {(owner_oid, "SELECT", False)}
                if column_name in expected_columns
                else set()
            )
            if direct_acl[column_name] != expected_acl:
                raise DatabaseContractError

        cursor.execute(
            """
            select pg_catalog.has_column_privilege(%s, %s, %s, 'SELECT'),
                   pg_catalog.has_column_privilege(%s, %s, %s, 'SELECT')
            """,
            (
                PRIVATE_RUNTIME_ROLE,
                relation,
                expected_columns[0],
                PRIVATE_OWNER_ROLE,
                relation,
                expected_columns[0],
            ),
        )
        if cursor.fetchone() != (False, True):
            raise DatabaseContractError

    cursor.execute(
        """
        select namespace.nspname || '.' || relation.relname,
               relation.relrowsecurity,
               relation.relforcerowsecurity
          from pg_catalog.pg_class relation
          join pg_catalog.pg_namespace namespace
            on namespace.oid = relation.relnamespace
         where namespace.nspname = 'public'
           and relation.relname in ('pessoas', 'conversations')
         order by relation.relname
        """
    )
    if cursor.fetchall() != [
        ("public.conversations", True, False),
        ("public.pessoas", True, False),
    ]:
        raise DatabaseContractError


def _tenant_policy_expression(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        normalized = public_replay._normalize_policy_expression(value)
        if normalized is None:
            return False
        while public_replay._has_one_outer_parenthesis_pair(normalized):
            normalized = normalized[1:-1]
    except Exception:
        return False
    return normalized in {
        "igreja_id=agent_private.current_tenant_id()",
        "agent_private.current_tenant_id()=igreja_id",
    }


def _validate_owner_policies(cursor: Any, owner_oid: int) -> None:
    cursor.execute(
        """
        select namespace.nspname || '.' || relation.relname || '.' || policy.polname,
               policy.polcmd,
               policy.polpermissive,
               policy.polroles,
               pg_catalog.pg_get_expr(policy.polqual, policy.polrelid),
               pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid)
          from pg_catalog.pg_policy policy
          join pg_catalog.pg_class relation on relation.oid = policy.polrelid
          join pg_catalog.pg_namespace namespace
            on namespace.oid = relation.relnamespace
         where namespace.nspname = 'public'
           and relation.relname in ('pessoas', 'conversations')
         order by namespace.nspname, relation.relname, policy.polname
        """
    )
    rows = cursor.fetchall()
    if type(rows) is not list:
        raise DatabaseContractError
    owner_rows: dict[str, tuple[object, ...]] = {}
    owner_policy_keys: set[str] = set()
    for row in rows:
        if type(row) not in {tuple, list} or len(row) != 6:
            raise DatabaseContractError
        key = row[0]
        if type(key) is not str:
            raise DatabaseContractError
        if ".agent_projection_owner_" in key:
            owner_policy_keys.add(key)
        if key in PRIVATE_POLICIES:
            owner_rows[key] = tuple(row[1:])
    if owner_policy_keys != set(PRIVATE_POLICIES) or set(owner_rows) != set(PRIVATE_POLICIES):
        raise DatabaseContractError
    for key, row in owner_rows.items():
        command, permissive, roles, using, check = row
        if type(roles) not in {list, tuple} or tuple(roles) != (owner_oid,):
            raise DatabaseContractError
        if key.endswith("select_pessoas") or key.endswith("select_conversations"):
            if command != "r" or permissive is not True or not _tenant_policy_expression(using) or check is not None:
                raise DatabaseContractError
        else:
            if command != "r" or permissive is not False or not _tenant_policy_expression(using) or check is not None:
                raise DatabaseContractError


def _rollback_sql_and_require_clean(
    connection: Any,
    *,
    original_error: BaseException | None = None,
) -> None:
    """End an explicit transaction and prove the local role/context reset.

    The runner deliberately uses ``autocommit`` while issuing explicit SQL
    ``BEGIN`` statements.  Psycopg's ``connection.rollback()`` is allowed to
    be a no-op in that mode, so cleanup must travel through the server.
    """

    try:
        status_getter = getattr(connection, "get_transaction_status", None)
        if not callable(status_getter):
            raise DatabaseContractError
        if status_getter() != TRANSACTION_STATUS_IDLE:
            with connection.cursor() as cursor:
                cursor.execute("ROLLBACK")
        if status_getter() != TRANSACTION_STATUS_IDLE:
            raise DatabaseContractError

        with connection.cursor() as cursor:
            cursor.execute(
                "select current_user, session_user, "
                "pg_catalog.current_setting(%s, true)",
                (TENANT_GUC,),
            )
            session = cursor.fetchone()
        if (
            type(session) not in {tuple, list}
            or len(session) != 3
            or type(session[0]) is not str
            or type(session[1]) is not str
            or session[0] != session[1]
            or session[0] in {PRIVATE_RUNTIME_ROLE, PRIVATE_OWNER_ROLE}
            or session[2] not in {None, ""}
        ):
            raise DatabaseContractError

        # A non-autocommit test double, or a driver that implicitly starts a
        # transaction for the verification SELECT, must also end cleanly.
        if status_getter() != TRANSACTION_STATUS_IDLE:
            with connection.cursor() as cursor:
                cursor.execute("ROLLBACK")
        if status_getter() != TRANSACTION_STATUS_IDLE:
            raise DatabaseContractError
    except Exception as cleanup_error:
        if original_error is not None:
            raise original_error from cleanup_error
        raise DatabaseContractError from cleanup_error


def _expect_privilege_denied(
    connection: Any,
    *,
    role: str = PRIVATE_RUNTIME_ROLE,
    sql: str,
    parameters: tuple[object, ...] = (),
    tenant: str,
) -> None:
    if role not in {PRIVATE_RUNTIME_ROLE, PRIVATE_OWNER_ROLE}:
        raise DatabaseContractError
    try:
        with connection.cursor() as cursor:
            cursor.execute("begin")
            cursor.execute(f"set local role {role}")
            cursor.execute("select pg_catalog.set_config(%s, %s, true)", (TENANT_GUC, tenant))
            cursor.execute(sql, parameters)
    except Exception as exc:
        _rollback_sql_and_require_clean(connection, original_error=exc)
        if getattr(exc, "pgcode", None) != "42501":
            raise DatabaseContractError from exc
        return
    _rollback_sql_and_require_clean(connection)
    raise DatabaseContractError


def _select_projection(
    connection: Any,
    *,
    role: str,
    tenant: str | None,
    conversation_id: str,
) -> list[tuple[object, ...]]:
    if role not in {PRIVATE_RUNTIME_ROLE, PRIVATE_OWNER_ROLE}:
        raise DatabaseContractError
    try:
        with connection.cursor() as cursor:
            cursor.execute("begin")
            cursor.execute(f"set local role {role}")
            if tenant is None:
                cursor.execute(f"set local {TENANT_GUC} to default")
            else:
                cursor.execute(
                    "select pg_catalog.set_config(%s, %s, true)",
                    (TENANT_GUC, tenant),
                )
            cursor.execute(
                "select * from agent_private.load_turn_context(%s)",
                (conversation_id,),
            )
            rows = cursor.fetchall()
    except Exception as exc:
        _rollback_sql_and_require_clean(connection, original_error=exc)
        raise
    _rollback_sql_and_require_clean(connection)
    if type(rows) is not list or any(type(row) not in {tuple, list} or len(row) != 6 for row in rows):
        raise DatabaseContractError
    return [tuple(row) for row in rows]


def _validate_runtime_behaviour(connection: Any) -> tuple[bool, bool]:
    """Exercise A/B, absent/invalid tenant context, direct SELECT and DML."""

    tenant_a = "11111111-1111-4111-8111-111111111111"
    tenant_b = "22222222-2222-4222-8222-222222222222"
    pessoa_a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    pessoa_b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    conversation_a = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    conversation_b = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    absent = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    if not all(UUID_RE.fullmatch(value) for value in (tenant_a, tenant_b, pessoa_a, pessoa_b, conversation_a, conversation_b, absent)):
        raise DatabaseContractError

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "insert into public.igrejas (id, nome) values (%s, %s), (%s, %s)",
                (tenant_a, "synthetic-a", tenant_b, "synthetic-b"),
            )
            cursor.execute(
                """
                insert into public.pessoas
                  (id, igreja_id, nome, telefone, optout, sem_interesse)
                values (%s, %s, %s, %s, false, true),
                       (%s, %s, %s, %s, true, false)
                """,
                (pessoa_a, tenant_a, "synthetic-a", "+55000000001", pessoa_b, tenant_b, "synthetic-b", "+55000000002"),
            )
            cursor.execute(
                """
                insert into public.conversations
                  (id, igreja_id, pessoa_id, telefone, estado)
                values (%s, %s, %s, %s, 'ia'),
                       (%s, %s, %s, %s, 'humano')
                """,
                (conversation_a, tenant_a, pessoa_a, "+55000000001", conversation_b, tenant_b, pessoa_b, "+55000000002"),
            )

        a_rows = _select_projection(
            connection, role=PRIVATE_RUNTIME_ROLE, tenant=tenant_a, conversation_id=conversation_a
        )
        if (
            len(a_rows) != 1
            or str(a_rows[0][0]) != tenant_a
            or str(a_rows[0][1]) != conversation_a
            or str(a_rows[0][2]) != pessoa_a
            or a_rows[0][3] != "ia"
            or a_rows[0][4:] != (False, True)
        ):
            raise DatabaseContractError
        if _select_projection(connection, role=PRIVATE_RUNTIME_ROLE, tenant=tenant_a, conversation_id=conversation_b):
            raise DatabaseContractError
        b_rows = _select_projection(
            connection, role=PRIVATE_RUNTIME_ROLE, tenant=tenant_b, conversation_id=conversation_b
        )
        if (
            len(b_rows) != 1
            or str(b_rows[0][0]) != tenant_b
            or b_rows[0][3] != "humano"
            or b_rows[0][4:] != (True, False)
        ):
            raise DatabaseContractError
        if _select_projection(connection, role=PRIVATE_RUNTIME_ROLE, tenant=tenant_a, conversation_id=absent):
            raise DatabaseContractError
        if _select_projection(connection, role=PRIVATE_RUNTIME_ROLE, tenant=None, conversation_id=conversation_a):
            raise DatabaseContractError

        try:
            with connection.cursor() as cursor:
                cursor.execute("begin")
                cursor.execute(f"set local role {PRIVATE_RUNTIME_ROLE}")
                cursor.execute("select pg_catalog.set_config(%s, %s, true)", (TENANT_GUC, "not-a-uuid"))
                cursor.execute("select * from agent_private.load_turn_context(%s)", (conversation_a,))
        except Exception as exc:
            _rollback_sql_and_require_clean(connection, original_error=exc)
            if getattr(exc, "pgcode", None) != "22023" or "invalid tenant context" not in str(exc):
                raise DatabaseContractError from exc
        else:
            _rollback_sql_and_require_clean(connection)
            raise DatabaseContractError

        _expect_privilege_denied(
            connection,
            tenant=tenant_a,
            sql="select igreja_id from public.pessoas",
        )
        _expect_privilege_denied(
            connection,
            tenant=tenant_a,
            sql="insert into public.pessoas (id, igreja_id, nome, telefone) values (%s, %s, %s, %s)",
            parameters=(absent, tenant_a, "denied", "+55000000003"),
        )
        _expect_privilege_denied(
            connection,
            tenant=tenant_a,
            sql="update public.pessoas set nome = %s where id = %s",
            parameters=("denied", pessoa_a),
        )
        _expect_privilege_denied(
            connection,
            tenant=tenant_a,
            sql="delete from public.pessoas where id = %s",
            parameters=(pessoa_a,),
        )

        owner_rows = _select_projection(
            connection, role=PRIVATE_OWNER_ROLE, tenant=tenant_a, conversation_id=conversation_a
        )
        if len(owner_rows) != 1:
            raise DatabaseContractError
        _expect_privilege_denied(
            connection,
            role=PRIVATE_OWNER_ROLE,
            tenant=tenant_a,
            sql="select nome from public.pessoas",
        )
    finally:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "delete from public.conversations where id in (%s, %s)",
                    (conversation_a, conversation_b),
                )
                cursor.execute(
                    "delete from public.pessoas where id in (%s, %s)",
                    (pessoa_a, pessoa_b),
                )
                cursor.execute(
                    "delete from public.igrejas where id in (%s, %s)",
                    (tenant_a, tenant_b),
                )
        except Exception as exc:
            _rollback_sql_and_require_clean(connection, original_error=exc)
            raise DatabaseContractError from exc
    return True, True


def replay_private_runtime_catalog_pg17(
    connect: Callable[..., Any] | None = None,
) -> ReplayResult:
    public_loaded, scaffold, private_loaded = _load_composed_source()
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
            application_name="pastorai-private-runtime-catalog-pg17-replay",
        )
        connection.autocommit = True
        with connection.cursor() as cursor:
            version_num = public_replay._validate_fresh_database(cursor, database_name)
            cursor.execute("set statement_timeout = '120s'")
            cursor.execute("set lock_timeout = '10s'")
            cursor.execute("set idle_in_transaction_session_timeout = '30s'")
            public_replay._require_idle_transaction(connection)
            try:
                cursor.execute(scaffold)
            except Exception as exc:
                raise MigrationReplayError from exc
            public_replay._require_idle_transaction(connection)
            public_replay._ensure_ledgers_absent(cursor)
            for migration in public_loaded.migrations:
                try:
                    cursor.execute(migration.sql)
                except Exception as exc:
                    raise MigrationReplayError from exc
                public_replay._require_idle_transaction(connection)
                public_replay._ensure_ledgers_absent(cursor)

            delta_verified = True
            for migration in private_loaded.migrations:
                before = _capture_catalog_surface(cursor)
                try:
                    cursor.execute(migration.sql)
                except Exception as exc:
                    try:
                        _rollback_sql_and_require_clean(connection, original_error=exc)
                    except Exception:
                        raise MigrationReplayError from exc
                    raise MigrationReplayError from exc
                public_replay._require_idle_transaction(connection)
                public_replay._ensure_ledgers_absent(cursor)
                after = _capture_catalog_surface(cursor)
                _validate_catalog_delta(before, after, migration.intent)
                delta_verified = True

            owner_oid, runtime_oid = _validate_role_and_schema(cursor)
            _validate_tenant_helper(
                cursor,
                owner_oid=owner_oid,
                runtime_oid=runtime_oid,
            )
            _validate_projection_function(
                cursor,
                owner_oid=owner_oid,
                runtime_oid=runtime_oid,
                private=private_loaded.migrations[-1],
            )
            _validate_default_acl(
                cursor,
                owner_oid=owner_oid,
                runtime_oid=runtime_oid,
            )
            _validate_public_relation_contract(
                cursor,
                owner_oid=owner_oid,
                runtime_oid=runtime_oid,
            )
            _validate_owner_policies(cursor, owner_oid)
            cross_tenant, dml_denied = _validate_runtime_behaviour(connection)
            direct_select_denied = True
    except ReplayError:
        raise
    except Exception as exc:
        raise DatabaseContractError from exc
    finally:
        if connection is not None:
            connection.close()
    return ReplayResult(
        public_migration_count=len(public_loaded.migrations),
        public_digest_sha256=public_loaded.digest_sha256,
        private_migration_count=len(private_loaded.migrations),
        private_digest_sha256=private_loaded.digest_sha256,
        private_last_basename=private_loaded.migrations[-1].name,
        private_last_sha256=private_loaded.migrations[-1].sha256,
        combined_migration_count=len(public_loaded.migrations) + len(private_loaded.migrations),
        postgres_version_num=version_num,
        cross_tenant_evidence=cross_tenant,
        direct_select_denied=direct_select_denied,
        dml_denied=dml_denied,
        catalog_delta_verified=delta_verified,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = SanitizedArgumentParser(add_help=False)
    parser.add_argument("--catalog-head", required=True)
    parser.add_argument("--private-directory", required=True)
    parser.add_argument("--confirmation", required=True, choices=[CONFIRMATION])
    return parser


def main(argv: list[str] | None = None) -> int:
    print(OPERATIONAL_BLOCK)
    print(NEXT_STAGE_BLOCK)
    print(ENVIRONMENT_BLOCK)
    try:
        args = build_parser().parse_args(argv)
        if args.catalog_head != "docs/governance/migrations/private-runtime-catalog-head-v1.json" or args.private_directory != "backend/migrations/private_runtime":
            raise CliUsageError
        result = replay_private_runtime_catalog_pg17()
    except ReplayError as exc:
        print(f"PRIVATE_RUNTIME_REPLAY_BLOCKED:{exc.reason}", file=sys.stderr)
        return exc.exit_code
    except Exception:
        print("PRIVATE_RUNTIME_REPLAY_BLOCKED:INTERNAL_ERROR", file=sys.stderr)
        return 10
    print(SUCCESS)
    print(f"PUBLIC_CATALOG_MIGRATION_COUNT={result.public_migration_count}")
    print(f"PUBLIC_CATALOG_DIGEST_SHA256={result.public_digest_sha256}")
    print(f"PRIVATE_CATALOG_MIGRATION_COUNT={result.private_migration_count}")
    print(f"PRIVATE_CATALOG_DIGEST_SHA256={result.private_digest_sha256}")
    print(f"PRIVATE_CATALOG_LAST_BASENAME={result.private_last_basename}")
    print(f"PRIVATE_CATALOG_LAST_SHA256={result.private_last_sha256}")
    print(f"COMBINED_CATALOG_MIGRATION_COUNT={result.combined_migration_count}")
    print(f"POSTGRESQL_MAJOR={result.postgres_version_num // 10_000}")
    print(f"PG17_REPLAY_EXECUTED=true")
    print(f"CROSS_TENANT_EVIDENCE={str(result.cross_tenant_evidence).lower()}")
    print(f"DIRECT_SELECT_DENIED={str(result.direct_select_denied).lower()}")
    print(f"DML_DENIED={str(result.dml_denied).lower()}")
    print(f"CATALOG_DELTA_VERIFIED={str(result.catalog_delta_verified).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
