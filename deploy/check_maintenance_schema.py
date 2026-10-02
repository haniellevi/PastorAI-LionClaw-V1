"""Read-only compatibility check for the pinned legacy API maintenance release.

This checks the supported legacy schema, not the current main migration list.
It neither reconciles the ledger nor authorizes migrations or feature activation.
The caller supplies the reviewed public profile; credentials stay in the runtime.
"""

from __future__ import annotations

import json
import os
import re
import sys


def sql_tokens(source: str) -> list[str]:
    """Ignore formatting/comments, preserving quoted SQL values exactly."""
    tokens = re.findall(r"'(?:''|[^'])*'|--[^\n]*|[A-Za-z_][A-Za-z0-9_]*|->>|::|[^\s]", source)
    return [t if t.startswith("'") else t.lower() for t in tokens if not t.startswith("--")]


def collect(connection, tables: list[str]) -> dict:
    connection.set_session(readonly=True, isolation_level="REPEATABLE READ")
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL statement_timeout = '5s'")
        cursor.execute("SELECT current_database(), current_user, current_setting('transaction_read_only')")
        database, role, readonly = cursor.fetchone()
        if readonly != "on":
            raise ValueError("read-only transaction required")
        cursor.execute("SELECT name FROM public.schema_migrations ORDER BY name")
        ledger = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            "SELECT c.relname, a.attname, CASE WHEN t.typtype = 'e' THEN 'enum' "
            "ELSE format_type(a.atttypid, NULL) END "
            "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_type t ON t.oid = a.atttypid "
            "WHERE n.nspname = 'public' AND c.relname = ANY(%s) "
            "AND a.attnum > 0 AND NOT a.attisdropped", (tables,)
        )
        columns = {name: [] for name in tables}
        column_types = {name: {} for name in tables}
        for table, column, datatype in cursor.fetchall():
            columns[table].append(column)
            column_types[table][column] = datatype
        cursor.execute(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
            "has_table_privilege('authenticated', c.oid, 'SELECT'), "
            "pg_has_role('authenticated', c.relowner, 'MEMBER') "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = ANY(%s) ORDER BY c.relname", (tables,)
        )
        relations = [list(row) for row in cursor.fetchall()]
        cursor.execute(
            "SELECT c.relname, p.polname, p.polcmd, p.polpermissive, p.polroles::oid[], "
            "pg_get_expr(p.polqual, p.polrelid), pg_get_expr(p.polwithcheck, p.polrelid) "
            "FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = ANY(%s) ORDER BY c.relname, p.polname", (tables,)
        )
        policies = [list(row) for row in cursor.fetchall()]
        cursor.execute("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = 'authenticated'")
        authenticated = cursor.fetchone()
        cursor.execute(
            "SELECT p.prosrc, p.prosecdef, p.provolatile, p.proconfig, "
            "has_function_privilege('authenticated', p.oid, 'EXECUTE'), l.lanname "
            "FROM pg_proc p JOIN pg_language l ON l.oid = p.prolang "
            "WHERE p.oid = 'public.current_igreja_id()'::regprocedure"
        )
        function = cursor.fetchone()
    connection.rollback()
    return {"database": database, "role": role, "ledger": ledger, "columns": columns,
            "column_types": column_types,
            "relations": relations, "policies": policies,
            "authenticated": list(authenticated) if authenticated else None,
            "function": list(function) if function else None}


def validate(observed: dict, profile: dict) -> None:
    schema = profile["schema"]
    expected = schema["ledger"]
    if (not expected or len(expected) != len(set(expected)) or
            any(not isinstance(n, str) or not re.fullmatch(r"[A-Za-z0-9_]+\.sql", n) for n in expected)):
        raise ValueError("invalid reviewed ledger")
    if observed["database"] != schema["database"]["name"] or observed["role"] != schema["database"]["role"]:
        raise ValueError("database identity mismatch")
    if sorted(observed["ledger"]) != sorted(expected):
        raise ValueError("migration ledger differs from reviewed legacy contract")
    expected_types = schema.get("column_types", {})
    if set(expected_types) != set(schema["columns"]):
        raise ValueError("invalid reviewed column types")
    for table, required in schema["columns"].items():
        if not set(required).issubset(observed["columns"].get(table, ())):
            raise ValueError("required legacy column missing")
        if set(expected_types[table]) != set(required):
            raise ValueError("invalid reviewed column types")
        for column, allowed in expected_types[table].items():
            if not isinstance(allowed, list) or not allowed or any(not isinstance(t, str) for t in allowed):
                raise ValueError("invalid reviewed column types")
            if observed.get("column_types", {}).get(table, {}).get(column) not in allowed:
                raise ValueError("required legacy column type mismatch")
    if observed["relations"] != schema["relations"]:
        raise ValueError("RLS, ownership or SELECT ACL mismatch")
    if observed["policies"] != schema["policies"]:
        raise ValueError("tenant policy set mismatch")
    if observed["authenticated"] != [False, False]:
        raise ValueError("authenticated role can bypass RLS")
    actual_function = observed["function"]
    if (not actual_function or actual_function[1:] != schema["tenant_function"][1:] or
            sql_tokens(actual_function[0]) != sql_tokens(schema["tenant_function"][0])):
        raise ValueError("tenant resolver mismatch")


def main() -> int:
    connection = None
    try:
        import psycopg2
        from sqlalchemy.engine import make_url

        profile = json.loads(os.environ["MAINTENANCE_SCHEMA_PROFILE"])
        if profile["version"] != 1:
            raise ValueError("unsupported profile")
        target = profile["schema"]["database"]
        url = make_url(os.environ["DATABASE_URL"])
        if ((url.host, url.port or 5432, url.database, url.username) !=
                (target["host"], target["port"], target["name"], target["username"])):
            raise ValueError("runtime database target mismatch")
        connection = psycopg2.connect(
            host=url.host, port=url.port or 5432, dbname=url.database,
            user=url.username, password=url.password, sslmode="require", connect_timeout=5,
            application_name="igreja12_maintenance_schema_readonly",
        )
        observed = collect(connection, sorted(profile["schema"]["columns"]))
        validate(observed, profile)
        print(json.dumps({"schema_compatible": True, "read_only": True,
                          "ledger_count": len(observed["ledger"]),
                          "checked_tables": len(observed["columns"])}))
        return 0
    except Exception as exc:
        # Database exception text can include SQL values or connection strings.
        print("maintenance schema rejected: " + type(exc).__name__, file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
