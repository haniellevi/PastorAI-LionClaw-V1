"""Exercise catalog checks against a dedicated, synthetic PostgreSQL 17 database."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import unittest
from urllib.parse import urlparse

DEPLOY = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("maintenance_schema_pg", DEPLOY / "check_maintenance_schema.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
DSN = os.environ.get("MAINTENANCE_SCHEMA_TEST_DATABASE_URL")


def validated_fixture_dsn(dsn):
    from psycopg2.extensions import parse_dsn

    try:
        parsed = urlparse(dsn)
        port = parsed.port if parsed.port is not None else 5432
        if (parsed.scheme not in ("postgresql", "postgres") or
                parsed.hostname not in ("127.0.0.1", "::1") or
                parsed.path != "/maintenance_schema_disposable" or
                "?" in dsn or "#" in dsn or not 1 <= port <= 65535):
            raise ValueError("unsafe fixture target")
        effective = parse_dsn(dsn)
        if (effective.get("host") != parsed.hostname or
                effective.get("dbname") != "maintenance_schema_disposable" or
                int(effective.get("port", 5432)) != port):
            raise ValueError("unsafe effective fixture target")
    except Exception:
        raise RuntimeError("only the named literal loopback fixture is accepted") from None
    return dsn


@unittest.skipUnless(DSN, "dedicated disposable PostgreSQL database required")
class MaintenanceSchemaPgTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        from psycopg2 import sql
        validated_fixture_dsn(DSN)
        cls.psycopg2 = psycopg2
        cls.profile = json.loads((DEPLOY / "maintenance-profile.json").read_text())
        cls.profile["schema"]["database"]["name"] = "maintenance_schema_disposable"
        with psycopg2.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SHOW server_version_num")
                if int(cur.fetchone()[0]) // 10000 != 17:
                    raise RuntimeError("PostgreSQL 17 required")
                cur.execute("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated')")
                if not cur.fetchone()[0]: cur.execute("CREATE ROLE authenticated NOLOGIN NOSUPERUSER NOBYPASSRLS")
                cur.execute("CREATE TABLE public.schema_migrations(name text PRIMARY KEY)")
                cur.executemany("INSERT INTO public.schema_migrations VALUES (%s)", [(n,) for n in cls.profile["schema"]["ledger"]])
                forced_tables = {row[0] for row in cls.profile["schema"]["relations"] if row[2]}
                for table, columns in cls.profile["schema"]["columns"].items():
                    fields = [sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(cls.profile["schema"]["column_types"][table][c][0])) for c in columns]
                    cur.execute(sql.SQL("CREATE TABLE public.{} ({})").format(sql.Identifier(table), sql.SQL(",").join(fields)))
                    cur.execute(sql.SQL("GRANT SELECT ON public.{} TO authenticated").format(sql.Identifier(table)))
                    cur.execute(sql.SQL("ALTER TABLE public.{} ENABLE ROW LEVEL SECURITY").format(sql.Identifier(table)))
                    if table in forced_tables:
                        cur.execute(sql.SQL("ALTER TABLE public.{} FORCE ROW LEVEL SECURITY").format(sql.Identifier(table)))
                cur.execute("CREATE FUNCTION public.current_igreja_id() RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS %s", (cls.profile["schema"]["tenant_function"][0],))
                commands = {"*": "ALL", "r": "SELECT", "w": "UPDATE"}
                for table, name, command, _, _, using, check in cls.profile["schema"]["policies"]:
                    statement = sql.SQL("CREATE POLICY {} ON public.{} FOR {} USING ({})").format(sql.Identifier(name), sql.Identifier(table), sql.SQL(commands[command]), sql.SQL(using))
                    if check: statement += sql.SQL(" WITH CHECK ({})").format(sql.SQL(check))
                    cur.execute(statement)

    @classmethod
    def tearDownClass(cls):
        with cls.psycopg2.connect(DSN) as conn:
            with conn.cursor() as cur:
                # Only the fixture database selected by the strict guard above.
                cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")

    def observe(self):
        conn = self.psycopg2.connect(DSN)
        try: return checker.collect(conn, sorted(self.profile["schema"]["columns"]))
        finally: conn.close()

    def mutate(self, statement):
        with self.psycopg2.connect(DSN) as conn:
            with conn.cursor() as cur: cur.execute(statement)

    def test_actual_postgres_catalog_matches_reviewed_contract(self):
        checker.validate(self.observe(), self.profile)

    def test_disabled_rls_rejects_before_application_start(self):
        self.mutate("ALTER TABLE public.messages DISABLE ROW LEVEL SECURITY")
        try:
            with self.assertRaisesRegex(ValueError, "RLS"): checker.validate(self.observe(), self.profile)
        finally: self.mutate("ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY")

    def test_extra_permissive_policy_rejects_even_with_tenant_policy_present(self):
        self.mutate("CREATE POLICY accidentally_open ON public.pessoas USING (true)")
        try:
            with self.assertRaisesRegex(ValueError, "policy"): checker.validate(self.observe(), self.profile)
        finally: self.mutate("DROP POLICY accidentally_open ON public.pessoas")

    def test_missing_ledger_entry_rejects(self):
        self.mutate("DELETE FROM public.schema_migrations WHERE name='0001_extensions_and_enums.sql'")
        try:
            with self.assertRaisesRegex(ValueError, "ledger"): checker.validate(self.observe(), self.profile)
        finally: self.mutate("INSERT INTO public.schema_migrations VALUES ('0001_extensions_and_enums.sql')")

    def test_required_timestamp_type_drift_rejects(self):
        self.mutate("ALTER TABLE public.messages ALTER COLUMN criado_em TYPE integer USING NULL")
        try:
            with self.assertRaisesRegex(ValueError, "type"):
                checker.validate(self.observe(), self.profile)
        finally:
            self.mutate("ALTER TABLE public.messages ALTER COLUMN criado_em TYPE timestamp with time zone USING NULL")

    def test_timezone_drift_rejects(self):
        self.mutate("ALTER TABLE public.messages ALTER COLUMN criado_em TYPE timestamp without time zone USING NULL")
        try:
            with self.assertRaisesRegex(ValueError, "type"):
                checker.validate(self.observe(), self.profile)
        finally:
            self.mutate("ALTER TABLE public.messages ALTER COLUMN criado_em TYPE timestamp with time zone USING NULL")

    def test_old_string_columns_allow_varchar_and_enum_types(self):
        self.mutate("CREATE TYPE public.fixture_kind AS ENUM ('membro', 'visitante')")
        self.mutate("ALTER TABLE public.pessoas ALTER COLUMN tipo TYPE public.fixture_kind USING tipo::public.fixture_kind")
        self.mutate("ALTER TABLE public.pessoas ALTER COLUMN nome TYPE varchar(255)")
        try:
            checker.validate(self.observe(), self.profile)
        finally:
            self.mutate("ALTER TABLE public.pessoas ALTER COLUMN tipo TYPE text USING tipo::text")
            self.mutate("ALTER TABLE public.pessoas ALTER COLUMN nome TYPE text")
            self.mutate("DROP TYPE public.fixture_kind")

    def test_resolver_language_drift_rejects_with_identical_body(self):
        body = self.profile["schema"]["tenant_function"][0]
        with self.psycopg2.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SET check_function_bodies=off")
                cur.execute("CREATE OR REPLACE FUNCTION public.current_igreja_id() RETURNS uuid LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS %s", (body,))
        try:
            with self.assertRaisesRegex(ValueError, "resolver"):
                checker.validate(self.observe(), self.profile)
        finally:
            with self.psycopg2.connect(DSN) as conn:
                with conn.cursor() as cur:
                    cur.execute("CREATE OR REPLACE FUNCTION public.current_igreja_id() RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS %s", (body,))


if __name__ == "__main__": unittest.main()
