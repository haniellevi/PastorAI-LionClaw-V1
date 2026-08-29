#!/usr/bin/env python3
"""Derive a canonical schema fingerprint in an isolated PostgreSQL 17 lab.

This tool is separate from ``apply_migrations.py``. It accepts one dedicated
database environment variable, connects only to an allowlisted loopback
database, replays the exact catalog, and emits a sanitized artifact. It never
creates either migration ledger and never attests DEV or PROD.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, NoReturn, Sequence
from urllib.parse import unquote, urlsplit

try:
    from scripts import (
        verify_migration_history_schema_expectation_manifest as source_manifest,
    )
except ModuleNotFoundError:  # direct execution from backend/scripts
    import verify_migration_history_schema_expectation_manifest as source_manifest


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "backend" / "migrations"
MANIFEST_PATH = (
    REPO_ROOT / "docs" / "governance" / "migrations" / source_manifest.MANIFEST_BASENAME
)
SCAFFOLD_RELATIVE_PATH = (
    "docs/governance/migrations/"
    "migration-history-canonical-schema-scaffold-v1.sql"
)
SCAFFOLD_PATH = REPO_ROOT / SCAFFOLD_RELATIVE_PATH
SCAFFOLD_SHA256 = (
    "9dcf654790e9787d218ec93f59c04d46d1aaab214f223b8ac5f4b2dd502ef3cc"
)
SCHEMA_RELATIVE_PATH = (
    "docs/governance/migrations/"
    "migration-history-canonical-schema-derivation.schema.json"
)
SCHEMA_PATH = REPO_ROOT / SCHEMA_RELATIVE_PATH
SCHEMA_SHA256 = (
    "1033463518b5655f495118b458e6ae7056d3fa92ed325df0278cf851ec89be83"
)
OUTPUT_BASENAME = "migration-history-canonical-schema-derivation-v1.json"
DATABASE_URL_ENV = "CANONICAL_SCHEMA_DERIVATION_DATABASE_URL"
CONFIRMATION = "DERIVE_CANONICAL_SCHEMA_OFFLINE"
CATALOG_DIGEST_SHA256 = (
    "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f"
)
POSTGRES_IMAGE = (
    "postgres:17.6-trixie@"
    "sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929"
)
ALLOWED_DATABASES = {
    "canonical_schema_disposable_a",
    "canonical_schema_disposable_b",
    "canonical_schema_disposable_test",
}
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
APPLICATION_ROLES = ("anon", "authenticated", "service_role", "agent_runtime")
REQUIRED_DOMAINS = tuple(source_manifest.REQUIRED_DOMAINS)
DATA_INVARIANTS = tuple(source_manifest.DATA_INVARIANTS)
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
SUCCESS = "CANONICAL_SCHEMA_DERIVATION_COMPLETE_OFFLINE_ONLY"
MAX_OUTPUT_BYTES = 16_777_216
MAX_CONTRACT_BYTES = 262_144


class DerivationError(RuntimeError):
    exit_code = 10
    reason = "INTERNAL_ERROR"


class CliUsageError(DerivationError):
    exit_code = 2
    reason = "USAGE"


class LayoutError(DerivationError):
    exit_code = 3
    reason = "LOCAL_LAYOUT_INVALID"


class SourceContractError(DerivationError):
    exit_code = 4
    reason = "SOURCE_CONTRACT_INVALID"


class TargetGuardError(DerivationError):
    exit_code = 5
    reason = "DISPOSABLE_TARGET_REQUIRED"


class DatabaseContractError(DerivationError):
    exit_code = 6
    reason = "DATABASE_CONTRACT_INVALID"


class ReplayBlockedError(DerivationError):
    exit_code = 7
    reason = "MIGRATION_REPLAY_BLOCKED"


class FingerprintError(DerivationError):
    exit_code = 8
    reason = "FINGERPRINT_INVALID"


class OutputError(DerivationError):
    exit_code = 9
    reason = "OUTPUT_INVALID"


class SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise CliUsageError


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _domain_sha256(name: str, entries: list[dict[str, Any]]) -> str:
    material = b"PASTORAI-CANONICAL-SCHEMA-DOMAIN\x00\x01"
    material += len(name).to_bytes(4, "big") + name.encode("ascii")
    return hashlib.sha256(material + _canonical_bytes(entries)).hexdigest()


def _artifact_sha256(domains: list[dict[str, Any]]) -> str:
    projection = {
        "catalog_digest_sha256": CATALOG_DIGEST_SHA256,
        "domains": [
            {
                "entry_count": domain["entry_count"],
                "name": domain["name"],
                "sha256": domain["sha256"],
            }
            for domain in domains
        ],
        "scaffold_sha256": SCAFFOLD_SHA256,
    }
    material = b"PASTORAI-CANONICAL-SCHEMA-ARTIFACT\x00\x01"
    return hashlib.sha256(material + _canonical_bytes(projection)).hexdigest()


def _safe_regular_file(path: Path, maximum_bytes: int) -> bytes:
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise LayoutError
        if before.st_size <= 0 or before.st_size > maximum_bytes:
            raise LayoutError
        content = path.read_bytes()
        after = path.lstat()
    except OSError as exc:
        raise LayoutError from exc
    before_identity = (
        before.st_dev, before.st_ino, before.st_mode, before.st_nlink,
        before.st_uid, before.st_gid, before.st_size, before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_identity = (
        after.st_dev, after.st_ino, after.st_mode, after.st_nlink,
        after.st_uid, after.st_gid, after.st_size, after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if len(content) != before.st_size or before_identity != after_identity:
        raise LayoutError
    return content


def _load_source_catalog() -> list[bytes]:
    try:
        source_manifest.verify_manifest(MANIFEST_PATH)
        catalog, _capabilities = source_manifest._scan_catalog()
        manifest = source_manifest._load_manifest(MANIFEST_PATH)
    except source_manifest.ManifestError as exc:
        raise SourceContractError from exc
    if len(catalog) != 75:
        raise SourceContractError
    repository = manifest.get("repository")
    if type(repository) is not dict:
        raise SourceContractError
    if repository.get("catalog_digest_sha256") != CATALOG_DIGEST_SHA256:
        raise SourceContractError
    result: list[bytes] = []
    for expected_position, entry in enumerate(catalog):
        if entry["position"] != expected_position:
            raise SourceContractError
        content = _safe_regular_file(
            MIGRATIONS_DIR / entry["name"], source_manifest.MAX_MIGRATION_BYTES
        )
        if len(content) != entry["size_bytes"]:
            raise SourceContractError
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise SourceContractError
        try:
            content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise SourceContractError from exc
        result.append(content)
    return result


def _load_scaffold() -> bytes:
    scaffold = _safe_regular_file(SCAFFOLD_PATH, MAX_CONTRACT_BYTES)
    schema = _safe_regular_file(SCHEMA_PATH, MAX_CONTRACT_BYTES)
    if hashlib.sha256(scaffold).hexdigest() != SCAFFOLD_SHA256:
        raise SourceContractError
    if hashlib.sha256(schema).hexdigest() != SCHEMA_SHA256:
        raise SourceContractError
    try:
        scaffold.decode("utf-8", errors="strict")
        json.loads(schema.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceContractError from exc
    return scaffold


def _read_disposable_url() -> tuple[str, str]:
    raw = os.environ.get(DATABASE_URL_ENV)
    if raw is None or raw == "" or raw != raw.strip() or len(raw) > 4096:
        raise TargetGuardError
    try:
        parsed = urlsplit(raw)
        database_name = unquote(parsed.path.removeprefix("/"))
        host = parsed.hostname
        port = parsed.port
    except (ValueError, UnicodeError) as exc:
        raise TargetGuardError from exc
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise TargetGuardError
    if host is None or host.casefold() not in ALLOWED_HOSTS:
        raise TargetGuardError
    if database_name not in ALLOWED_DATABASES:
        raise TargetGuardError
    if parsed.fragment or parsed.query or parsed.path.count("/") != 1:
        raise TargetGuardError
    if parsed.username is None or parsed.password is None:
        raise TargetGuardError
    if port is None or port < 1024 or port > 65535:
        raise TargetGuardError
    return raw, database_name


def _normalize_owner(value: str, derivation_owner: str) -> str:
    if value in {derivation_owner, "DERIVATION_OWNER"}:
        return "DERIVATION_OWNER"
    if value in APPLICATION_ROLES or value == "PUBLIC":
        return value
    raise FingerprintError


def _normalize_rows(
    columns: Sequence[str], rows: Sequence[Sequence[Any]]
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for row in rows:
        if len(row) != len(columns):
            raise FingerprintError
        entry: dict[str, Any] = {}
        for column, value in zip(columns, row, strict=True):
            if value is None or type(value) in {bool, int, str}:
                entry[column] = value
            elif isinstance(value, (list, tuple)):
                if not all(item is None or type(item) in {bool, int, str} for item in value):
                    raise FingerprintError
                entry[column] = list(value)
            else:
                entry[column] = str(value)
        entries.append(entry)
    entries.sort(key=_canonical_bytes)
    if len({_canonical_bytes(entry) for entry in entries}) != len(entries):
        raise FingerprintError
    return entries


DOMAIN_QUERIES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "EXTENSIONS",
        ("name", "observed_version", "schema"),
        """
        select e.extname, e.extversion, n.nspname
          from pg_catalog.pg_extension e
          join pg_catalog.pg_namespace n on n.oid = e.extnamespace
         order by e.extname collate "C"
        """,
    ),
    (
        "ENUM_TYPES_AND_VALUES",
        ("schema", "type", "label", "sort_order"),
        """
        select n.nspname, t.typname, e.enumlabel, e.enumsortorder::text
          from pg_catalog.pg_type t
          join pg_catalog.pg_namespace n on n.oid = t.typnamespace
          join pg_catalog.pg_enum e on e.enumtypid = t.oid
         where n.nspname in ('public', 'agent_private')
         order by n.nspname collate "C", t.typname collate "C", e.enumsortorder
        """,
    ),
    (
        "SCHEMAS_AND_OWNERS",
        ("schema", "owner"),
        """
        select n.nspname,
               case when pg_catalog.pg_get_userbyid(n.nspowner) = current_user
                 then 'DERIVATION_OWNER'
                 else pg_catalog.pg_get_userbyid(n.nspowner) end
          from pg_catalog.pg_namespace n
         where n.nspname in ('public', 'agent_private')
         order by n.nspname collate "C"
        """,
    ),
    (
        "RELATIONS_AND_PERSISTENCE",
        ("schema", "relation", "kind", "persistence", "owner"),
        """
        select n.nspname, c.relname, c.relkind::text, c.relpersistence::text,
               case when pg_catalog.pg_get_userbyid(c.relowner) = current_user
                 then 'DERIVATION_OWNER'
                 else pg_catalog.pg_get_userbyid(c.relowner) end
          from pg_catalog.pg_class c
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
         where n.nspname in ('public', 'agent_private')
           and c.relkind in ('r', 'p', 'v', 'm', 'S', 'f')
           and not exists (
             select 1 from pg_catalog.pg_depend d
              where d.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
                and d.objid = c.oid and d.deptype = 'e'
           )
         order by n.nspname collate "C", c.relname collate "C"
        """,
    ),
    (
        "COLUMNS_TYPES_DEFAULTS_IDENTITY_GENERATED",
        (
            "schema", "relation", "position", "column", "type", "not_null",
            "default", "identity", "generated",
        ),
        """
        select n.nspname, c.relname, a.attnum::integer, a.attname,
               pg_catalog.format_type(a.atttypid, a.atttypmod), a.attnotnull,
               pg_catalog.pg_get_expr(ad.adbin, ad.adrelid, true),
               a.attidentity::text, a.attgenerated::text
          from pg_catalog.pg_attribute a
          join pg_catalog.pg_class c on c.oid = a.attrelid
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
          left join pg_catalog.pg_attrdef ad
            on ad.adrelid = a.attrelid and ad.adnum = a.attnum
         where n.nspname in ('public', 'agent_private')
           and c.relkind in ('r', 'p', 'v', 'm', 'f')
           and a.attnum > 0 and not a.attisdropped
           and not exists (
             select 1 from pg_catalog.pg_depend d
              where d.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
                and d.objid = c.oid and d.deptype = 'e'
           )
         order by n.nspname collate "C", c.relname collate "C", a.attnum
        """,
    ),
    (
        "CONSTRAINTS_AND_VALIDATION_STATE",
        (
            "schema", "relation", "constraint", "type", "validated",
            "deferrable", "initially_deferred", "definition",
        ),
        """
        select n.nspname, c.relname, k.conname, k.contype::text,
               k.convalidated, k.condeferrable, k.condeferred,
               pg_catalog.pg_get_constraintdef(k.oid, true)
          from pg_catalog.pg_constraint k
          join pg_catalog.pg_class c on c.oid = k.conrelid
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
         where n.nspname in ('public', 'agent_private')
         order by n.nspname collate "C", c.relname collate "C",
                  k.conname collate "C"
        """,
    ),
    (
        "INDEXES_DEFINITIONS_AND_VALIDITY",
        (
            "schema", "table", "index", "unique", "primary", "exclusion",
            "valid", "ready", "live", "definition",
        ),
        """
        select n.nspname, t.relname, i.relname, x.indisunique, x.indisprimary,
               x.indisexclusion, x.indisvalid, x.indisready, x.indislive,
               pg_catalog.pg_get_indexdef(i.oid, 0, true)
          from pg_catalog.pg_index x
          join pg_catalog.pg_class i on i.oid = x.indexrelid
          join pg_catalog.pg_class t on t.oid = x.indrelid
          join pg_catalog.pg_namespace n on n.oid = t.relnamespace
         where n.nspname in ('public', 'agent_private')
         order by n.nspname collate "C", t.relname collate "C",
                  i.relname collate "C"
        """,
    ),
    (
        "RLS_ENABLE_FORCE_FLAGS",
        ("schema", "relation", "enabled", "forced"),
        """
        select n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity
          from pg_catalog.pg_class c
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
         where n.nspname in ('public', 'agent_private')
           and c.relkind in ('r', 'p')
         order by n.nspname collate "C", c.relname collate "C"
        """,
    ),
    (
        "POLICIES_COMMAND_ROLES_USING_WITH_CHECK",
        (
            "schema", "relation", "policy", "permissive", "command", "roles",
            "using", "with_check",
        ),
        """
        select n.nspname, c.relname, p.polname, p.polpermissive, p.polcmd::text,
               coalesce((
                 select pg_catalog.array_agg(
                   case r when 0 then 'PUBLIC' else pg_catalog.pg_get_userbyid(r) end
                   order by case r when 0 then 'PUBLIC'
                     else pg_catalog.pg_get_userbyid(r) end collate "C"
                 ) from pg_catalog.unnest(p.polroles) r
               ), array[]::text[]),
               pg_catalog.pg_get_expr(p.polqual, p.polrelid, true),
               pg_catalog.pg_get_expr(p.polwithcheck, p.polrelid, true)
          from pg_catalog.pg_policy p
          join pg_catalog.pg_class c on c.oid = p.polrelid
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
         where n.nspname in ('public', 'agent_private')
         order by n.nspname collate "C", c.relname collate "C",
                  p.polname collate "C"
        """,
    ),
    (
        "FUNCTIONS_SIGNATURE_LANGUAGE_VOLATILITY_SECURITY_SEARCH_PATH",
        (
            "schema", "function", "kind", "identity_arguments", "result",
            "language", "volatility", "parallel", "strict",
            "security_definer", "leakproof", "configuration", "definition",
            "owner",
        ),
        """
        select n.nspname, p.proname, p.prokind::text,
               pg_catalog.pg_get_function_identity_arguments(p.oid),
               pg_catalog.pg_get_function_result(p.oid), l.lanname,
               p.provolatile::text, p.proparallel::text, p.proisstrict,
               p.prosecdef, p.proleakproof,
               coalesce(p.proconfig, array[]::text[]),
               pg_catalog.pg_get_functiondef(p.oid),
               case when pg_catalog.pg_get_userbyid(p.proowner) = current_user
                 then 'DERIVATION_OWNER'
                 else pg_catalog.pg_get_userbyid(p.proowner) end
          from pg_catalog.pg_proc p
          join pg_catalog.pg_namespace n on n.oid = p.pronamespace
          join pg_catalog.pg_language l on l.oid = p.prolang
         where n.nspname in ('public', 'agent_private')
           and not exists (
             select 1 from pg_catalog.pg_depend d
              where d.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
                and d.objid = p.oid and d.deptype = 'e'
           )
         order by n.nspname collate "C", p.proname collate "C",
                  pg_catalog.pg_get_function_identity_arguments(p.oid) collate "C"
        """,
    ),
    (
        "TRIGGERS_AND_REWRITE_RULES",
        ("object_type", "schema", "relation", "name", "enabled", "definition"),
        """
        select 'TRIGGER', n.nspname, c.relname, t.tgname, t.tgenabled::text,
               pg_catalog.pg_get_triggerdef(t.oid, true)
          from pg_catalog.pg_trigger t
          join pg_catalog.pg_class c on c.oid = t.tgrelid
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
         where n.nspname in ('public', 'agent_private') and not t.tgisinternal
        union all
        select 'REWRITE_RULE', n.nspname, c.relname, r.rulename,
               r.ev_enabled::text, pg_catalog.pg_get_ruledef(r.oid, true)
          from pg_catalog.pg_rewrite r
          join pg_catalog.pg_class c on c.oid = r.ev_class
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
         where n.nspname in ('public', 'agent_private') and r.rulename <> '_RETURN'
         order by 1, 2, 3, 4
        """,
    ),
)


ROLE_COLUMNS = (
    "record_type", "role", "superuser", "inherit", "create_role",
    "create_database", "login", "replication", "bypass_rls", "configuration",
    "parent_role", "member_role", "admin_option", "inherit_option", "set_option",
)
ROLE_QUERY = """
select 'ROLE',
       case when r.rolname = current_user then 'DERIVATION_OWNER' else r.rolname end,
       r.rolsuper, r.rolinherit, r.rolcreaterole, r.rolcreatedb, r.rolcanlogin,
       r.rolreplication, r.rolbypassrls, coalesce(r.rolconfig, array[]::text[]),
       null::text, null::text, null::boolean, null::boolean, null::boolean
  from pg_catalog.pg_roles r
 where r.rolname = current_user
    or r.rolname in ('anon', 'authenticated', 'service_role', 'agent_runtime')
union all
select 'MEMBERSHIP', null::text, null::boolean, null::boolean, null::boolean,
       null::boolean, null::boolean, null::boolean, null::boolean, array[]::text[],
       case when parent.rolname = current_user then 'DERIVATION_OWNER'
            else parent.rolname end,
       case when member.rolname = current_user then 'DERIVATION_OWNER'
            else member.rolname end,
       m.admin_option, m.inherit_option, m.set_option
  from pg_catalog.pg_auth_members m
  join pg_catalog.pg_roles parent on parent.oid = m.roleid
  join pg_catalog.pg_roles member on member.oid = m.member
 where (parent.rolname = current_user
        or parent.rolname in ('anon', 'authenticated', 'service_role', 'agent_runtime'))
   and (member.rolname = current_user
        or member.rolname in ('anon', 'authenticated', 'service_role', 'agent_runtime'))
order by 1, 2 nulls last, 11 nulls last, 12 nulls last
"""


PRIVILEGE_COLUMNS = (
    "object_type", "schema", "object", "column", "grantor", "grantee",
    "privilege", "grantable",
)
PRIVILEGE_QUERY = """
with schema_acl as (
  select 'SCHEMA'::text object_type, n.nspname schema_name,
         n.nspname object_identity, null::text column_name, n.nspowner owner_id,
         pg_catalog.aclexplode(coalesce(n.nspacl, pg_catalog.acldefault('n', n.nspowner))) acl
    from pg_catalog.pg_namespace n where n.nspname in ('public', 'agent_private')
), relation_acl as (
  select 'RELATION'::text, n.nspname, c.relname, null::text, c.relowner,
         pg_catalog.aclexplode(
           coalesce(
             c.relacl,
             pg_catalog.acldefault(
               case when c.relkind = 'S' then 's'::"char" else 'r'::"char" end,
               c.relowner
             )
           )
         )
    from pg_catalog.pg_class c
    join pg_catalog.pg_namespace n on n.oid = c.relnamespace
   where n.nspname in ('public', 'agent_private')
     and c.relkind in ('r', 'p', 'v', 'm', 'S', 'f')
     and not exists (
       select 1 from pg_catalog.pg_depend d
        where d.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
          and d.objid = c.oid and d.deptype = 'e'
     )
), column_acl as (
  select 'COLUMN'::text, n.nspname, c.relname, a.attname, c.relowner,
         pg_catalog.aclexplode(a.attacl)
    from pg_catalog.pg_attribute a
    join pg_catalog.pg_class c on c.oid = a.attrelid
    join pg_catalog.pg_namespace n on n.oid = c.relnamespace
   where n.nspname in ('public', 'agent_private')
     and a.attnum > 0 and not a.attisdropped and a.attacl is not null
), function_acl as (
  select 'FUNCTION'::text, n.nspname,
         p.proname || '(' || pg_catalog.pg_get_function_identity_arguments(p.oid) || ')',
         null::text, p.proowner,
         pg_catalog.aclexplode(coalesce(p.proacl, pg_catalog.acldefault('f', p.proowner)))
    from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace n on n.oid = p.pronamespace
   where n.nspname in ('public', 'agent_private')
     and not exists (
       select 1 from pg_catalog.pg_depend d
        where d.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
          and d.objid = p.oid and d.deptype = 'e'
     )
), combined as (
  select * from schema_acl union all select * from relation_acl
  union all select * from column_acl union all select * from function_acl
)
select object_type, schema_name, object_identity, column_name,
       case when (acl).grantor = owner_id then 'DERIVATION_OWNER'
            else pg_catalog.pg_get_userbyid((acl).grantor) end,
       case when (acl).grantee = 0 then 'PUBLIC'
            when (acl).grantee = owner_id then 'DERIVATION_OWNER'
            else pg_catalog.pg_get_userbyid((acl).grantee) end,
       (acl).privilege_type, (acl).is_grantable
  from combined
 order by object_type collate "C", schema_name collate "C",
          object_identity collate "C", column_name collate "C" nulls first,
          5, 6, 7, 8
"""


DEFAULT_PRIVILEGE_COLUMNS = (
    "object_type", "schema", "owner", "grantor", "grantee", "privilege",
    "grantable",
)
DEFAULT_PRIVILEGE_QUERY = """
select case d.defaclobjtype when 'r' then 'RELATION' when 'S' then 'SEQUENCE'
         when 'f' then 'FUNCTION' when 'T' then 'TYPE' when 'n' then 'SCHEMA'
         else d.defaclobjtype::text end,
       coalesce(n.nspname, 'GLOBAL'),
       case when owner_role.rolname = current_user then 'DERIVATION_OWNER'
            else owner_role.rolname end,
       case when (acl).grantor = d.defaclrole then 'DERIVATION_OWNER'
            else pg_catalog.pg_get_userbyid((acl).grantor) end,
       case when (acl).grantee = 0 then 'PUBLIC'
            when (acl).grantee = d.defaclrole then 'DERIVATION_OWNER'
            else pg_catalog.pg_get_userbyid((acl).grantee) end,
       (acl).privilege_type, (acl).is_grantable
  from pg_catalog.pg_default_acl d
  join pg_catalog.pg_roles owner_role on owner_role.oid = d.defaclrole
  left join pg_catalog.pg_namespace n on n.oid = d.defaclnamespace
  cross join lateral pg_catalog.aclexplode(d.defaclacl) acl
 where owner_role.rolname = current_user
    or owner_role.rolname in ('anon', 'authenticated', 'service_role', 'agent_runtime')
 order by 1, 2, 3, 4, 5, 6, 7
"""


def _check_loopback_address(value: Any) -> None:
    if value is None:
        return
    try:
        address = ipaddress.ip_address(str(value))
        # A loopback-published Docker port terminates on the private bridge
        # address inside PostgreSQL. The URL guard above remains strictly
        # loopback; this server-side check rejects only public routing.
        if not (address.is_loopback or address.is_private or address.is_link_local):
            raise DatabaseContractError
    except ValueError as exc:
        raise DatabaseContractError from exc


def _ensure_ledgers_absent(cursor: Any) -> None:
    cursor.execute(
        """
        select pg_catalog.to_regclass('public.schema_migrations') is null,
               pg_catalog.to_regnamespace('supabase_migrations') is null
        """
    )
    if cursor.fetchone() != (True, True):
        raise DatabaseContractError


def _validate_fresh_database(cursor: Any, expected_database: str) -> str:
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
    database_name, version_num, server_address, owner, session_owner, read_only = row
    if database_name != expected_database or version_num // 10000 != 17:
        raise DatabaseContractError
    _check_loopback_address(server_address)
    if owner != session_owner or read_only != "off":
        raise DatabaseContractError
    cursor.execute(
        """
        select count(*)::integer
          from pg_catalog.pg_class c
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public' and c.relkind in ('r', 'p', 'v', 'm', 'S', 'f')
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
    return str(owner)


def _query_entries(
    cursor: Any, columns: Sequence[str], query: str
) -> list[dict[str, Any]]:
    cursor.execute(query)
    return _normalize_rows(columns, cursor.fetchall())


def _collect_domains(cursor: Any, derivation_owner: str) -> list[dict[str, Any]]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for name, columns, query in DOMAIN_QUERIES:
        by_name[name] = _query_entries(cursor, columns, query)

    role_entries = _query_entries(cursor, ROLE_COLUMNS, ROLE_QUERY)
    for entry in role_entries:
        for key in ("role", "parent_role", "member_role"):
            if entry[key] is not None:
                entry[key] = _normalize_owner(entry[key], derivation_owner)
    by_name["ROLES_AND_MEMBERSHIPS"] = role_entries

    privilege_entries = _query_entries(cursor, PRIVILEGE_COLUMNS, PRIVILEGE_QUERY)
    for entry in privilege_entries:
        entry["grantor"] = _normalize_owner(entry["grantor"], derivation_owner)
        entry["grantee"] = _normalize_owner(entry["grantee"], derivation_owner)
    by_name["TABLE_COLUMN_FUNCTION_SCHEMA_PRIVILEGES"] = privilege_entries

    default_entries = _query_entries(
        cursor, DEFAULT_PRIVILEGE_COLUMNS, DEFAULT_PRIVILEGE_QUERY
    )
    for entry in default_entries:
        for key in ("owner", "grantor", "grantee"):
            entry[key] = _normalize_owner(entry[key], derivation_owner)
    by_name["DEFAULT_PRIVILEGES"] = default_entries

    by_name["DATA_INVARIANTS"] = [
        {
            "id": invariant,
            "state": "DEFINED_FOR_SEPARATE_READ_ONLY_ENVIRONMENT_ATTESTATION",
        }
        for invariant in DATA_INVARIANTS
    ]
    if set(by_name) != set(REQUIRED_DOMAINS):
        raise FingerprintError

    domains: list[dict[str, Any]] = []
    for name in REQUIRED_DOMAINS:
        entries = by_name[name]
        entries.sort(key=_canonical_bytes)
        domains.append(
            {
                "entry_count": len(entries),
                "entries": entries,
                "name": name,
                "sha256": _domain_sha256(name, entries),
            }
        )
    return domains


def _build_artifact(domains: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "artifact_id": "migration-history-canonical-schema-derivation-v1",
        "artifact_state": "OFFLINE_CANONICAL_SCHEMA_DERIVED_ENVIRONMENTS_UNATTESTED",
        "canonical_schema_fingerprint_sha256": _artifact_sha256(domains),
        "contract_version": "1.0",
        "data_api": {"exposure_inferred": False, "state": "NOT_EVALUATED_OFFLINE"},
        "derivation_target": {
            "container_image": POSTGRES_IMAGE,
            "disposable_database_required": True,
            "loopback_required": True,
            "postgresql_major": 17,
            "realtime_scaffolded": False,
        },
        "domains": domains,
        "environment_attestation_complete": False,
        "extension_version_semantics": "OBSERVATIONAL_NOT_PINNED_OR_OPERATIONAL",
        "operational_authorization": False,
        "replay": {
            "autocommit_per_file": True,
            "complete": True,
            "migration_count": 75,
            "native_ledger_absent": True,
            "public_ledger_absent": True,
            "raw_bytes_preserved": True,
        },
        "scaffold": {
            "owner_identity": "DERIVATION_OWNER",
            "path": SCAFFOLD_RELATIVE_PATH,
            "roles": ["anon", "authenticated", "service_role"],
            "sha256": SCAFFOLD_SHA256,
        },
        "source_catalog": {
            "algorithm": source_manifest.CATALOG_ALGORITHM,
            "digest_sha256": CATALOG_DIGEST_SHA256,
            "migration_count": 75,
            "path": "backend/migrations",
        },
    }


def _validate_output_dir(output_dir: Path) -> None:
    try:
        directory_info = output_dir.lstat()
    except OSError as exc:
        raise OutputError from exc
    if not stat.S_ISDIR(directory_info.st_mode):
        raise OutputError
    if (
        directory_info.st_uid != os.geteuid()
        or stat.S_IMODE(directory_info.st_mode) != 0o700
    ):
        raise OutputError
    target = output_dir / OUTPUT_BASENAME
    temporary = output_dir / f".{OUTPUT_BASENAME}.partial"
    try:
        if target.exists() or target.is_symlink():
            raise OutputError
        if temporary.exists() or temporary.is_symlink():
            raise OutputError
    except OSError as exc:
        raise OutputError from exc


def _write_atomic(output_dir: Path, artifact: dict[str, Any]) -> Path:
    _validate_output_dir(output_dir)
    target = output_dir / OUTPUT_BASENAME
    temporary = output_dir / f".{OUTPUT_BASENAME}.partial"
    try:
        payload = _canonical_bytes(artifact) + b"\n"
        if len(payload) > MAX_OUTPUT_BYTES:
            raise OutputError
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, target, follow_symlinks=False)
            temporary.unlink()
            directory_descriptor = os.open(output_dir, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        final = target.lstat()
        if (
            not stat.S_ISREG(final.st_mode)
            or final.st_nlink != 1
            or stat.S_IMODE(final.st_mode) != 0o600
            or final.st_uid != os.geteuid()
            or final.st_size != len(payload)
        ):
            raise OutputError
    except (OSError, ValueError) as exc:
        raise OutputError from exc
    return target


def derive(output_dir: Path) -> Path:
    # Reject a public, pre-populated, or attacker-controlled destination before
    # reading connection material or opening any database socket. The writer
    # validates it again immediately before the atomic create to close races.
    _validate_output_dir(output_dir)
    database_url, database_name = _read_disposable_url()
    catalog = _load_source_catalog()
    scaffold = _load_scaffold()
    try:
        import psycopg2
    except ImportError as exc:
        raise DatabaseContractError from exc

    connection = None
    try:
        connection = psycopg2.connect(database_url, connect_timeout=5)
        connection.autocommit = True
        with connection.cursor() as cursor:
            derivation_owner = _validate_fresh_database(cursor, database_name)
            try:
                cursor.execute(scaffold.decode("utf-8", errors="strict"))
            except Exception as exc:
                raise ReplayBlockedError from exc
            _ensure_ledgers_absent(cursor)
            for raw_bytes in catalog:
                try:
                    cursor.execute(raw_bytes.decode("utf-8", errors="strict"))
                except Exception as exc:
                    raise ReplayBlockedError from exc
                _ensure_ledgers_absent(cursor)

        connection.autocommit = False
        connection.set_session(
            isolation_level="REPEATABLE READ", readonly=True, autocommit=False
        )
        with connection.cursor() as cursor:
            _ensure_ledgers_absent(cursor)
            domains = _collect_domains(cursor, derivation_owner)
            artifact = _build_artifact(domains)
        connection.rollback()
    except DerivationError:
        raise
    except Exception as exc:
        raise DatabaseContractError from exc
    finally:
        if connection is not None:
            connection.close()
    return _write_atomic(output_dir, artifact)


def build_parser() -> argparse.ArgumentParser:
    parser = SanitizedArgumentParser(add_help=False)
    parser.add_argument("--confirmation", required=True, choices=[CONFIRMATION])
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    print(OPERATIONAL_BLOCK)
    try:
        args = build_parser().parse_args(argv)
        derive(args.output_dir)
    except DerivationError as exc:
        print(f"CANONICAL_SCHEMA_DERIVATION_BLOCKED:{exc.reason}", file=sys.stderr)
        return exc.exit_code
    except Exception:
        print("CANONICAL_SCHEMA_DERIVATION_BLOCKED:INTERNAL_ERROR", file=sys.stderr)
        return 10
    print("ENVIRONMENT_ATTESTATION_COMPLETE=false")
    print(SUCCESS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
