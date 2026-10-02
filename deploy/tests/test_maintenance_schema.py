"""Legacy schema compatibility must reject drift before an API replacement."""

import copy
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

DEPLOY = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("maintenance_schema", DEPLOY / "check_maintenance_schema.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
pg_spec = importlib.util.spec_from_file_location("maintenance_schema_fixture", DEPLOY / "tests/test_maintenance_schema_pg.py")
pg_fixture = importlib.util.module_from_spec(pg_spec)
pg_spec.loader.exec_module(pg_fixture)


class MaintenanceSchemaTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((DEPLOY / "maintenance-profile.json").read_text())
        schema = self.profile["schema"]
        self.observed = copy.deepcopy({
            "database": "postgres", "role": "postgres", "ledger": schema["ledger"],
            "columns": schema["columns"], "relations": schema["relations"],
            "column_types": {table: {column: allowed[0] for column, allowed in columns.items()}
                             for table, columns in schema["column_types"].items()},
            "policies": schema["policies"], "authenticated": [False, False],
            "function": schema["tenant_function"],
        })

    def test_reviewed_legacy_contract_accepts_existing_schema_without_new_migrations(self):
        self.assertEqual(len(self.observed["ledger"]), 70)
        checker.validate(self.observed, self.profile)

    def test_missing_extra_and_duplicate_ledger_are_rejected(self):
        for ledger in (self.observed["ledger"][:-1], self.observed["ledger"] + ["unexpected.sql"],
                       self.observed["ledger"] + [self.observed["ledger"][0]]):
            with self.subTest(ledger_count=len(ledger)), self.assertRaises(ValueError):
                checker.validate({**self.observed, "ledger": ledger}, self.profile)

    def test_missing_orm_column_is_rejected(self):
        self.observed["columns"]["messages"].remove("igreja_id")
        with self.assertRaisesRegex(ValueError, "column"):
            checker.validate(self.observed, self.profile)

    def test_disabled_rls_table_ownership_and_lost_select_grant_are_rejected(self):
        for field, value in ((1, False), (3, False), (4, True)):
            observed = copy.deepcopy(self.observed)
            observed["relations"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                checker.validate(observed, self.profile)

    def test_missing_extra_or_permissive_policy_is_rejected(self):
        variants = [self.observed["policies"][:-1], self.observed["policies"] + [
            ["messages", "unbounded", "*", True, [0], "true", "true"]]]
        changed = copy.deepcopy(self.observed["policies"])
        changed[0][5] = "true"
        variants.append(changed)
        for policies in variants:
            with self.subTest(policy_count=len(policies)), self.assertRaises(ValueError):
                checker.validate({**self.observed, "policies": policies}, self.profile)

    def test_authenticated_cannot_be_superuser_or_bypassrls(self):
        for attributes in ([True, False], [False, True], None):
            with self.subTest(attributes=attributes), self.assertRaises(ValueError):
                checker.validate({**self.observed, "authenticated": attributes}, self.profile)

    def test_tenant_function_body_security_and_search_path_are_pinned(self):
        for field, value in ((0, "select null::uuid"), (1, False), (3, ["search_path=public"]), (4, False), (5, "plpgsql")):
            observed = copy.deepcopy(self.observed)
            observed["function"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                checker.validate(observed, self.profile)

    def test_sql_formatting_is_ignored_but_quoted_values_remain_case_sensitive(self):
        self.assertEqual(checker.sql_tokens("SELECT -- comment\n 'a b'::text"), checker.sql_tokens("select 'a b' :: text"))
        self.assertNotEqual(checker.sql_tokens("select 'A'"), checker.sql_tokens("select 'a'"))

    def test_wrong_database_or_role_is_rejected(self):
        for field in ("database", "role"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                checker.validate({**self.observed, field: "unexpected"}, self.profile)

    def test_connection_collect_is_readonly_and_rolled_back(self):
        class Cursor:
            def __init__(self):
                self.queries = []
                self.results = iter([
                    ("postgres", "postgres", "on"), [], [], [], [], (False, False),
                    ("select null", True, "s", ["search_path=public, pg_temp"], True, "sql"),
                ])
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def execute(self, statement, params=None): self.queries.append(statement)
            def fetchone(self): return next(self.results)
            def fetchall(self): return next(self.results)
        class Connection:
            def __init__(self): self.cur = Cursor(); self.rolled_back = False
            def set_session(self, **kwargs): self.session = kwargs
            def cursor(self): return self.cur
            def rollback(self): self.rolled_back = True
        conn = Connection()
        checker.collect(conn, ["messages"])
        self.assertEqual(conn.session, {"readonly": True, "isolation_level": "REPEATABLE READ"})
        self.assertTrue(conn.rolled_back)
        self.assertTrue(all(q.startswith(("SELECT", "SET LOCAL")) for q in conn.cur.queries))
        self.assertNotIn("FROM public.messages", " ".join(conn.cur.queries))

    def test_fixture_guard_rejects_libpq_target_overrides_before_connect(self):
        base = "postgresql://postgres:fixture@127.0.0.1:32773/maintenance_schema_disposable"
        for suffix in ("?host=remote.example.invalid", "?dbname=other_database", "#fragment"):
            with self.subTest(suffix=suffix), self.assertRaises(RuntimeError):
                pg_fixture.validated_fixture_dsn(base + suffix)

    def test_fixture_guard_accepts_only_one_literal_loopback_database(self):
        for base in ("postgresql://postgres:fixture@127.0.0.1:32773/maintenance_schema_disposable",
                     "postgresql://postgres:fixture@[::1]:5432/maintenance_schema_disposable"):
            self.assertEqual(pg_fixture.validated_fixture_dsn(base), base)
        for dsn in ("postgresql://127.0.0.1/other_database",
                    "postgresql://remote.example.invalid/maintenance_schema_disposable",
                    "postgresql://127.0.0.1,127.0.0.2/maintenance_schema_disposable",
                    "postgresql:///maintenance_schema_disposable",
                    "postgresql://127.0.0.1:65536/maintenance_schema_disposable",
                    "postgresql://127.0.0.1:0/maintenance_schema_disposable",
                    "postgresql://127.0.0.1/maintenance_schema_disposable?",
                    "postgresql://127.0.0.1/maintenance_schema_disposable#"):
            with self.subTest(dsn=dsn), self.assertRaises(RuntimeError):
                pg_fixture.validated_fixture_dsn(dsn)

    def test_required_types_keep_numeric_uuid_json_array_and_timezone_boundaries(self):
        for table, column, datatype in (
            ("messages", "criado_em", "timestamp without time zone"),
            ("pessoas", "id", "text"),
            ("pessoas", "presencas_celula", "boolean"),
            ("agent_configs", "informacoes_publicas", "text"),
            ("subscriptions", "proxima_cobranca", "timestamp with time zone"),
            ("igrejas", "setup_fee_override", "integer"),
            ("agent_configs", "acessos", "text"),
        ):
            observed = copy.deepcopy(self.observed)
            observed["column_types"][table][column] = datatype
            with self.subTest(table=table, column=column), self.assertRaisesRegex(ValueError, "type"):
                checker.validate(observed, self.profile)

    def test_string_columns_accept_text_varchar_and_postgres_enum(self):
        for datatype in ("text", "character varying", "enum"):
            observed = copy.deepcopy(self.observed)
            observed["column_types"]["pessoas"]["tipo"] = datatype
            checker.validate(observed, self.profile)

    def test_missing_type_contract_or_observation_fails_closed(self):
        profile = copy.deepcopy(self.profile)
        profile["schema"]["column_types"].pop("messages")
        with self.assertRaisesRegex(ValueError, "type"):
            checker.validate(self.observed, profile)
        observed = copy.deepcopy(self.observed)
        observed["column_types"]["messages"].pop("criado_em")
        with self.assertRaisesRegex(ValueError, "type"):
            checker.validate(observed, self.profile)

    def test_connection_errors_never_print_credentials_or_exception_text(self):
        from sqlalchemy.engine import URL
        target = self.profile["schema"]["database"]
        url = URL.create("postgresql", username=target["username"], password="synthetic-secret",
                         host=target["host"], port=target["port"], database=target["name"])
        output, error = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"MAINTENANCE_SCHEMA_PROFILE": json.dumps(self.profile),
                                     "DATABASE_URL": url.render_as_string(hide_password=False)}), \
                patch("psycopg2.connect", side_effect=RuntimeError("synthetic-secret private details")), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            self.assertEqual(checker.main(), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(error.getvalue(), "maintenance schema rejected: RuntimeError\n")


if __name__ == "__main__":
    unittest.main()
