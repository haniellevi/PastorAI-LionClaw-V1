#!/usr/bin/env python3
"""Executa o harness corrente com traço estrutural opaco por migration.

O harness importado continua sendo o executor de referência: este invólucro
somente intercepta seu cursor após cada SQL validado e calcula deltas de
metadados em memória. O arquivo produzido contém posições, hashes de migration,
hashes de chave e contagens, sem identificadores brutos de catálogo.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path("/repo")
SCRIPT_PATH = REPO_ROOT / "backend/scripts/replay_migration_catalog_current_head_pg17.py"
TARGET_DATABASE = "migration_catalog_current_head_disposable"
TARGET_DSN = (
    "postgresql://postgres:postgres@127.0.0.1:5432/"
    + TARGET_DATABASE
)
ADMIN_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
TRACE_TYPES = (
    "CATALOG_SCHEMA",
    "CATALOG_RELATION",
    "CATALOG_COLUMN",
    "CATALOG_CONSTRAINT",
    "CATALOG_INDEX",
    "CATALOG_RLS_POLICY",
    "CATALOG_FUNCTION",
    "CATALOG_TRIGGER",
    "CATALOG_TYPE",
)
TRACE_PHASE = "BOOTSTRAP"


def _safe_key(record_type: str, schema_ref: str, relation_ref: str, object_ref: str, occurrence: int = 1) -> str:
    hasher = hashlib.sha256()
    hasher.update(b"F1-SAFE-KEY-v1\0")
    for value in (record_type, schema_ref, relation_ref, object_ref, str(occurrence)):
        hasher.update(value.encode("utf-8", "strict"))
        hasher.update(b"\x1f")
    return hasher.hexdigest()


def _payload(fields: tuple[str, ...]) -> str:
    hasher = hashlib.sha256()
    hasher.update(b"F1-SAFE-PAYLOAD-v1\0")
    for value in fields:
        hasher.update(value.encode("utf-8", "strict"))
        hasher.update(b"\x1f")
    return hasher.hexdigest()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if value is True:
        return "t"
    if value is False:
        return "f"
    return str(value)


def _masked_relation(schema: str, name: str) -> str:
    if schema == "recovery" or name.startswith("_clerk"):
        return "OPAQUE_RELATION_" + hashlib.md5(name.encode("utf-8")).hexdigest()
    return name


def _masked_object(prefix: str, schema: str, relation: str, name: str) -> str:
    if schema == "recovery" or relation.startswith("_clerk"):
        return prefix + hashlib.md5(name.encode("utf-8")).hexdigest()
    return name


def _schema_ref(schema: str) -> str:
    return "RECOVERY_SCHEMA_OPAQUE" if schema == "recovery" else schema


def _rows(cursor: Any, query: str) -> list[tuple[Any, ...]]:
    cursor.execute(query)
    rows = cursor.fetchall()
    if not isinstance(rows, list):
        raise RuntimeError("catalog snapshot shape invalid")
    return rows


def _snapshot(cursor: Any) -> dict[str, tuple[str, str]]:
    records: list[tuple[str, str, str, str, tuple[str, ...]]] = []
    for schema, acl_present in _rows(
        cursor,
        """
        select n.nspname, n.nspacl is not null
          from pg_catalog.pg_namespace n
         where n.nspname in ('public','agent_private','recovery')
         order by n.nspname
        """,
    ):
        ref = _schema_ref(_text(schema))
        records.append(("CATALOG_SCHEMA", ref, "-", "SCHEMA", ("CATALOG_SCHEMA", ref, "DIRECT_NSPACL_PRESENT" if acl_present else "NO_DIRECT_NSPACL")))

    for schema, relation, kind, persistence, rls, forced, replident, acl_present in _rows(
        cursor,
        """
        select n.nspname, c.relname, c.relkind, c.relpersistence,
               c.relrowsecurity, c.relforcerowsecurity, c.relreplident,
               c.relacl is not null
          from pg_catalog.pg_class c
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
         where n.nspname in ('public','agent_private','recovery')
           and c.relkind in ('r','p','v','m','S','f')
         order by n.nspname, c.relname
        """,
    ):
        schema_text, relation_text = _text(schema), _text(relation)
        schema_ref, relation_ref = _schema_ref(schema_text), _masked_relation(schema_text, relation_text)
        fields = tuple(_text(value) for value in ("CATALOG_RELATION", schema_ref, relation_ref, kind, persistence, rls, forced, replident)) + ("DIRECT_RELACL_PRESENT" if acl_present else "NO_DIRECT_RELACL",)
        records.append(("CATALOG_RELATION", schema_ref, relation_ref, "RELATION", fields))

    for row in _rows(
        cursor,
        """
        select n.nspname, c.relname, a.attnum, a.attname,
               pg_catalog.format_type(a.atttypid,a.atttypmod), a.attnotnull,
               a.attidentity, a.attgenerated,
               case when d.oid is null then 'NO_DEFAULT'
                    else pg_catalog.md5(pg_catalog.pg_get_expr(d.adbin,d.adrelid,true)) end
          from pg_catalog.pg_attribute a
          join pg_catalog.pg_class c on c.oid = a.attrelid
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
          left join pg_catalog.pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
         where n.nspname in ('public','agent_private','recovery')
           and c.relkind in ('r','p') and a.attnum > 0 and not a.attisdropped
         order by n.nspname,c.relname,a.attnum
        """,
    ):
        schema, relation, ordinal, column, *tail = row
        schema_text, relation_text, column_text = _text(schema), _text(relation), _text(column)
        schema_ref, relation_ref = _schema_ref(schema_text), _masked_relation(schema_text, relation_text)
        column_ref = _masked_object("OPAQUE_COLUMN_", schema_text, relation_text, column_text)
        fields = ("CATALOG_COLUMN", schema_ref, relation_ref, _text(ordinal), column_ref, *( _text(value) for value in tail))
        records.append(("CATALOG_COLUMN", schema_ref, relation_ref, _text(ordinal), fields))

    for row in _rows(
        cursor,
        """
        select n.nspname,c.relname,k.conname,k.contype,k.convalidated,
               k.condeferrable,k.condeferred,
               pg_catalog.md5(pg_catalog.pg_get_constraintdef(k.oid,true))
          from pg_catalog.pg_constraint k
          join pg_catalog.pg_class c on c.oid = k.conrelid
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
         where n.nspname in ('public','agent_private','recovery')
         order by n.nspname,c.relname,k.conname
        """,
    ):
        schema, relation, name, *tail = row
        schema_text, relation_text, name_text = _text(schema), _text(relation), _text(name)
        schema_ref, relation_ref = _schema_ref(schema_text), _masked_relation(schema_text, relation_text)
        object_ref = _masked_object("OPAQUE_CONSTRAINT_", schema_text, relation_text, name_text)
        fields = ("CATALOG_CONSTRAINT", schema_ref, relation_ref, object_ref, *( _text(value) for value in tail))
        records.append(("CATALOG_CONSTRAINT", schema_ref, relation_ref, object_ref, fields))

    for row in _rows(
        cursor,
        """
        select n.nspname,c.relname,i.relname,x.indisunique,x.indisprimary,
               x.indisvalid,x.indisready,x.indislive,
               pg_catalog.md5(pg_catalog.pg_get_indexdef(i.oid,0,true)),
               case when x.indpred is null then 'NO_PREDICATE'
                    else pg_catalog.md5(pg_catalog.pg_get_expr(x.indpred,x.indrelid,true)) end
          from pg_catalog.pg_index x
          join pg_catalog.pg_class c on c.oid = x.indrelid
          join pg_catalog.pg_class i on i.oid = x.indexrelid
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
         where n.nspname in ('public','agent_private','recovery')
         order by n.nspname,c.relname,i.relname
        """,
    ):
        schema, relation, name, *tail = row
        schema_text, relation_text, name_text = _text(schema), _text(relation), _text(name)
        schema_ref, relation_ref = _schema_ref(schema_text), _masked_relation(schema_text, relation_text)
        object_ref = _masked_object("OPAQUE_INDEX_", schema_text, relation_text, name_text)
        fields = ("CATALOG_INDEX", schema_ref, relation_ref, object_ref, *( _text(value) for value in tail))
        records.append(("CATALOG_INDEX", schema_ref, relation_ref, object_ref, fields))

    for row in _rows(
        cursor,
        """
        select n.nspname,c.relname,c.relrowsecurity,c.relforcerowsecurity,
               p.oid,p.polname,p.polpermissive,p.polcmd,p.polroles,
               case when p.oid is null or p.polqual is null then 'NO_USING_EXPRESSION'
                    else pg_catalog.md5(pg_catalog.pg_get_expr(p.polqual,p.polrelid,true)) end,
               case when p.oid is null or p.polwithcheck is null then 'NO_CHECK_EXPRESSION'
                    else pg_catalog.md5(pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid,true)) end,
               case when p.oid is null then false else pg_catalog.strpos(
                    coalesce(pg_catalog.pg_get_expr(p.polqual,p.polrelid,true),'') ||
                    coalesce(pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid,true),''),
                    'app.tenant_igreja_id') > 0 end
          from pg_catalog.pg_class c
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
          left join pg_catalog.pg_policy p on p.polrelid = c.oid
         where n.nspname in ('public','agent_private','recovery') and c.relkind in ('r','p')
         order by n.nspname,c.relname,p.polname nulls first
        """,
    ):
        schema, relation, rls, forced, policy_oid, policy_name, permissive, command, roles, using_md5, check_md5, mentions = row
        schema_text, relation_text = _text(schema), _text(relation)
        schema_ref, relation_ref = _schema_ref(schema_text), _masked_relation(schema_text, relation_text)
        if policy_oid is None:
            policy_ref, role_scope = "POLICY_ABSENT", "NO_POLICY"
        else:
            policy_ref = _masked_object("OPAQUE_POLICY_", schema_text, relation_text, _text(policy_name))
            role_values = tuple(roles)
            role_scope = "PUBLIC_ONLY" if role_values == (0,) else ("PUBLIC_PLUS_NAMED" if 0 in role_values else "NAMED_ROLES_ONLY")
        fields = ("CATALOG_RLS_POLICY", schema_ref, relation_ref, _text(rls), _text(forced), policy_ref, _text(permissive), _text(command), role_scope, _text(using_md5), _text(check_md5), _text(mentions))
        records.append(("CATALOG_RLS_POLICY", schema_ref, relation_ref, policy_ref, fields))

    for row in _rows(
        cursor,
        """
        select n.nspname,p.proname,p.prokind,l.lanname,p.provolatile,p.prosecdef,
               p.proleakproof,
               pg_catalog.md5(coalesce(pg_catalog.array_to_string(p.proconfig,',','<NULL>'),'<NO_CONFIG>')),
               pg_catalog.md5(pg_catalog.pg_get_functiondef(p.oid))
          from pg_catalog.pg_proc p
          join pg_catalog.pg_namespace n on n.oid = p.pronamespace
          join pg_catalog.pg_language l on l.oid = p.prolang
         where n.nspname in ('public','agent_private','recovery')
         order by n.nspname,p.proname,p.oid
        """,
    ):
        schema, name, *tail = row
        schema_text, name_text = _text(schema), _text(name)
        schema_ref = _schema_ref(schema_text)
        object_ref = "OPAQUE_FUNCTION_" + hashlib.md5(name_text.encode("utf-8")).hexdigest() if schema_text == "recovery" else name_text
        fields = ("CATALOG_FUNCTION", schema_ref, object_ref, *( _text(value) for value in tail))
        records.append(("CATALOG_FUNCTION", schema_ref, "-", object_ref, fields))

    for row in _rows(
        cursor,
        """
        select n.nspname,c.relname,t.tgname,t.tgenabled,fn.nspname,f.proname,
               pg_catalog.md5(pg_catalog.pg_get_triggerdef(t.oid,true))
          from pg_catalog.pg_trigger t
          join pg_catalog.pg_class c on c.oid = t.tgrelid
          join pg_catalog.pg_namespace n on n.oid = c.relnamespace
          join pg_catalog.pg_proc f on f.oid = t.tgfoid
          join pg_catalog.pg_namespace fn on fn.oid = f.pronamespace
         where n.nspname in ('public','agent_private','recovery') and not t.tgisinternal
         order by n.nspname,c.relname,t.tgname
        """,
    ):
        schema, relation, name, enabled, function_schema, function_name, definition_md5 = row
        schema_text, relation_text, name_text = _text(schema), _text(relation), _text(name)
        schema_ref, relation_ref = _schema_ref(schema_text), _masked_relation(schema_text, relation_text)
        opaque = schema_text == "recovery" or relation_text.startswith("_clerk") or _text(function_schema) == "recovery"
        trigger_ref = "OPAQUE_TRIGGER_" + hashlib.md5(name_text.encode("utf-8")).hexdigest() if opaque else name_text
        function_ref = "OPAQUE_FUNCTION_" + hashlib.md5(_text(function_name).encode("utf-8")).hexdigest() if opaque else _text(function_schema) + "." + _text(function_name)
        fields = ("CATALOG_TRIGGER", schema_ref, relation_ref, trigger_ref, _text(enabled), function_ref, _text(definition_md5))
        records.append(("CATALOG_TRIGGER", schema_ref, relation_ref, trigger_ref, fields))

    for schema, name, kind, enum_count, enum_md5 in _rows(
        cursor,
        """
        select n.nspname,t.typname,t.typtype,
               coalesce((select count(*) from pg_catalog.pg_enum e where e.enumtypid=t.oid),0),
               coalesce((select pg_catalog.md5(pg_catalog.string_agg(e.enumlabel,pg_catalog.chr(31) order by e.enumsortorder)) from pg_catalog.pg_enum e where e.enumtypid=t.oid),'NO_ENUM_LABELS')
          from pg_catalog.pg_type t
          join pg_catalog.pg_namespace n on n.oid = t.typnamespace
         where n.nspname in ('public','agent_private') and t.typtype in ('e','d')
         order by n.nspname,t.typname
        """,
    ):
        schema_ref, name_text = _schema_ref(_text(schema)), _text(name)
        fields = ("CATALOG_TYPE", schema_ref, name_text, _text(kind), _text(enum_count), _text(enum_md5))
        records.append(("CATALOG_TYPE", schema_ref, "-", name_text, fields))

    grouped: dict[tuple[str, str, str, str], list[tuple[str, ...]]] = {}
    for record_type, schema_ref, relation_ref, object_ref, fields in records:
        grouped.setdefault((record_type, schema_ref, relation_ref, object_ref), []).append(fields)
    result: dict[str, tuple[str, str]] = {}
    for base_key, grouped_fields in grouped.items():
        for occurrence, fields in enumerate(sorted(grouped_fields), start=1):
            key = _safe_key(*base_key, occurrence)
            if key in result:
                raise RuntimeError("duplicate structural safe key")
            result[key] = (base_key[0], _payload(fields))
    return result


def _load_replay() -> Any:
    spec = importlib.util.spec_from_file_location("f1_reference_harness", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("harness unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _reset_database() -> None:
    import psycopg2

    connection = psycopg2.connect(ADMIN_DSN, connect_timeout=5)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("select current_database(), current_setting('server_version_num')::integer")
            if cursor.fetchone() != ("postgres", 170006):
                raise RuntimeError("local PG17.6 required")
            cursor.execute("drop database if exists migration_catalog_current_head_disposable with (force)")
            cursor.execute("create database migration_catalog_current_head_disposable")
    finally:
        connection.close()


def _probe_fresh_database(replay: Any) -> None:
    import psycopg2

    connection = psycopg2.connect(TARGET_DSN, connect_timeout=5)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            replay._validate_fresh_database(cursor, TARGET_DATABASE)
    finally:
        connection.close()


class _ProxyCursor:
    def __init__(self, cursor: Any, trace: dict[int, dict[str, object]], migration_by_sql: dict[str, Any], scaffold: str) -> None:
        self._cursor = cursor
        self._trace = trace
        self._migration_by_sql = migration_by_sql
        self._scaffold = scaffold
        self._prior: dict[str, tuple[str, str]] | None = None

    def execute(self, query: Any, params: Any = None) -> Any:
        global TRACE_PHASE
        normalized = " ".join(query.split()).lower() if isinstance(query, str) else ""
        if "current_database()" in normalized:
            TRACE_PHASE = "REPLAY_FRESH_IDENTITY"
        elif "to_regclass('public.schema_migrations')" in normalized:
            TRACE_PHASE = "REPLAY_LEDGER_GUARD"
        elif "select count(*)::integer from pg_catalog.pg_roles" in normalized:
            TRACE_PHASE = "REPLAY_FRESH_ROLE_GUARD"
        elif "select count(*)::integer" in normalized and "n.nspname = 'public'" in normalized:
            TRACE_PHASE = "REPLAY_FRESH_PUBLIC_GUARD"
        elif "select 'public.' || c.relname" in normalized:
            TRACE_PHASE = "REPLAY_TENANT_SURFACE"
        elif "select c.relrowsecurity" in normalized:
            TRACE_PHASE = "REPLAY_TENANT_RELATION"
        elif "select policy.polname" in normalized:
            TRACE_PHASE = "REPLAY_TENANT_POLICY"
        elif normalized.startswith("set "):
            TRACE_PHASE = "REPLAY_TIMEOUT_SETUP"
        else:
            TRACE_PHASE = "REPLAY_HARNESS_QUERY"
        result = self._cursor.execute(query, params)
        if params is None and query == self._scaffold:
            TRACE_PHASE = "REPLAY_SCAFFOLD_SNAPSHOT"
            self._prior = _snapshot(self._cursor)
        elif params is None and isinstance(query, str) and query in self._migration_by_sql:
            if self._prior is None:
                raise RuntimeError("baseline catalog snapshot missing")
            TRACE_PHASE = "REPLAY_MIGRATION_SNAPSHOT"
            current = _snapshot(self._cursor)
            migration = self._migration_by_sql[query]
            changed = sorted(
                key for key in set(self._prior) | set(current)
                if self._prior.get(key) != current.get(key)
            )
            type_counts: dict[str, int] = {}
            for key in changed:
                record_type = (current.get(key) or self._prior.get(key))[0]
                type_counts[record_type] = type_counts.get(record_type, 0) + 1
            self._trace[migration.position] = {
                "migration_sha256": migration.sha256,
                "safe_key_sha256": changed,
                "record_type_counts": dict(sorted(type_counts.items())),
            }
            self._prior = current
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)

    def __enter__(self) -> "_ProxyCursor":
        self._cursor.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self._cursor.__exit__(*args)


class _ProxyConnection:
    def __init__(self, connection: Any, trace: dict[int, dict[str, object]], migration_by_sql: dict[str, Any], scaffold: str) -> None:
        object.__setattr__(self, "_connection", connection)
        object.__setattr__(self, "_trace", trace)
        object.__setattr__(self, "_migration_by_sql", migration_by_sql)
        object.__setattr__(self, "_scaffold", scaffold)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "autocommit":
            setattr(self._connection, name, value)
            return
        object.__setattr__(self, name, value)

    def cursor(self, *args: Any, **kwargs: Any) -> _ProxyCursor:
        return _ProxyCursor(self._connection.cursor(*args, **kwargs), self._trace, self._migration_by_sql, self._scaffold)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def main() -> int:
    global TRACE_PHASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if not output.is_absolute() or output.parent != output.parent.resolve():
        raise SystemExit("FAIL=TRACE_OUTPUT_PATH")
    TRACE_PHASE = "LOAD_SOURCE"
    replay = _load_replay()
    loaded = replay._load_current_catalog()
    if len(loaded.migrations) != 77:
        raise SystemExit("FAIL=CATALOG_COUNT_NOT_77")
    scaffold = replay._load_historical_compatibility_scaffold()
    migration_by_sql = {migration.sql: migration for migration in loaded.migrations}
    if len(migration_by_sql) != len(loaded.migrations):
        raise SystemExit("FAIL=DUPLICATE_MIGRATION_SQL")
    TRACE_PHASE = "RESET_DATABASE"
    _reset_database()
    TRACE_PHASE = "RESET_PROBE"
    _probe_fresh_database(replay)
    trace: dict[int, dict[str, object]] = {}

    def connect_proxy(*_args: Any, **_kwargs: Any) -> _ProxyConnection:
        import psycopg2

        global TRACE_PHASE
        TRACE_PHASE = "REPLAY_CONNECT"
        connection = psycopg2.connect(TARGET_DSN, connect_timeout=5)
        return _ProxyConnection(connection, trace, migration_by_sql, scaffold)

    previous_dsn = os.environ.get(replay.DATABASE_URL_ENV)
    os.environ[replay.DATABASE_URL_ENV] = TARGET_DSN
    TRACE_PHASE = "REPLAY"
    try:
        result = replay.replay_current_head_pg17(connect=connect_proxy)
    finally:
        if previous_dsn is None:
            os.environ.pop(replay.DATABASE_URL_ENV, None)
        else:
            os.environ[replay.DATABASE_URL_ENV] = previous_dsn
    TRACE_PHASE = "VALIDATE_TRACE"
    if result.migration_count != 77 or len(trace) != 77:
        raise SystemExit("FAIL=TRACE_INCOMPLETE")
    document = {
        "format": "F1_REFERENCE_STRUCTURAL_TRACE_V1",
        "catalog_digest_sha256": result.catalog_digest_sha256,
        "migration_count": result.migration_count,
        "postgres_version_num": result.postgres_version_num,
        "migrations": [
            {"position": position, **trace[position]}
            for position in sorted(trace)
        ],
    }
    TRACE_PHASE = "WRITE_TRACE"
    output.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n", encoding="ascii")
    print("RESULT=PASS_F1_REFERENCE_STRUCTURAL_TRACE")
    print("CATALOG_MIGRATION_COUNT=77")
    print("POSTGRESQL_MAJOR=17")
    print("TRACE_SHA256=" + hashlib.sha256(output.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print("FAIL=TRACE_INTERNAL_" + TRACE_PHASE + "_" + type(exc).__name__.upper())
        raise SystemExit(1)
