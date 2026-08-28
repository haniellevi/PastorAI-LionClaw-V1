"""Testes do executor fail-closed de migrations da M06.

Os testes unitários não conectam a banco algum. Os cenários marcados como
``rls_integration`` usam somente ``RLS_TEST_DATABASE_URL``, cujo guard comum
recusa DEV/PROD e deve apontar para PostgreSQL descartável.
"""

from __future__ import annotations

import argparse
import builtins
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import psycopg2
import pytest
from psycopg2 import sql as pgsql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from scripts import apply_migrations
from tests.conftest_rls import rls_database_url  # noqa: F401


EXECUTOR_DATABASE = "m06_executor_disposable"
CLOSED_TABLES = (
    "password_reset_tokens",
    "platform_admins",
    "platform_audit_log",
    "platform_orchestrator",
)
LEDGER_TEST_ROLES = (
    "m06_ledger_writer",
    "m06_ledger_admin_writer",
    "m06_ledger_safe",
    "m06_ledger_bypass",
)
CURRENT_M06_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260810_031050_explicit_deny_policies_for_closed_tables.sql"
)
SENSITIVE_DSN = (
    "postgresql://user%20synthetic:pass%2Fwith%20space@host.invalid/app"
    "?token=query-token-secret&api_key=query-api-key&unicode=%E2%9C%93"
)
SENSITIVE_TOKEN = 'token synthetic with spaces/quotes"\\slashes|✓'
SENSITIVE_DSN_COMPONENTS = (
    SENSITIVE_DSN,
    "user%20synthetic",
    "pass%2Fwith%20space",
    "host.invalid",
    "query-token-secret",
    "query-api-key",
    "%E2%9C%93",
)
SENSITIVE_TOKEN_COMPONENTS = (
    SENSITIVE_TOKEN,
    "spaces",
    'quotes"',
    "\\slashes",
    "|",
    "✓",
)


def _run_cli_subprocess(argv: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """Executa a CLI isolada e falha se o parser alcançar I/O ou banco."""
    program = f"""
import sys
from scripts import apply_migrations

def forbidden_side_effect(*_args, **_kwargs):
    raise RuntimeError("FORBIDDEN_SIDE_EFFECT")

apply_migrations.discover_migrations = forbidden_side_effect
apply_migrations._connect = forbidden_side_effect
raise SystemExit(apply_migrations.main({['runner', *argv]!r}))
"""
    return subprocess.run(
        [sys.executable, "-c", program],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, apply_migrations.DATABASE_URL_ENV: SENSITIVE_DSN},
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


def _assert_sanitized_usage_error(
    result: subprocess.CompletedProcess[str], sensitive_values: tuple[str, ...]
) -> None:
    output = result.stdout + result.stderr

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == f"{apply_migrations.USAGE_ERROR_MESSAGE}\n"
    assert "FORBIDDEN_SIDE_EFFECT" not in output
    for value in sensitive_values:
        assert value not in output


def _run_valid_status_subprocess() -> subprocess.CompletedProcess[str]:
    """Prova que a única URL aceita vem do ambiente, nunca de argv."""
    program = """
import os
import sys
from scripts import apply_migrations

class Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args, **_kwargs):
        pass

class Connection:
    def cursor(self):
        return Cursor()

    def rollback(self):
        pass

    def close(self):
        pass

def fake_connect(url):
    if url != os.environ[apply_migrations.DATABASE_URL_ENV]:
        raise RuntimeError("WRONG_CONNECTION_SOURCE")
    return Connection()

apply_migrations.discover_migrations = lambda: []
apply_migrations._connect = fake_connect
apply_migrations._inspect_ledger_fail_closed = lambda *_args, **_kwargs: (
    apply_migrations.LedgerState(relation_oid=1, applied_names=())
)
raise SystemExit(apply_migrations.main(["runner", "status"]))
"""
    return subprocess.run(
        [sys.executable, "-c", program],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, apply_migrations.DATABASE_URL_ENV: SENSITIVE_DSN},
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


def _args(
    *,
    database_url: str = "postgresql://operator:private-test-value@db.invalid/app",
    migration: str | None = None,
    sha256: str | None = None,
    confirm: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        _database_url_for_test=database_url,
        migration=migration,
        sha256=sha256,
        confirm=confirm,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_migration(root: Path, name: str, sql: str) -> Path:
    path = root / name
    path.write_text(sql, encoding="utf-8")
    return path


@pytest.fixture
def migration_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "migrations"
    root.mkdir()
    monkeypatch.setattr(apply_migrations, "MIGRATIONS_DIR", root)
    return root


def test_missing_psycopg2_points_to_hashed_runtime_lock(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real_import = builtins.__import__

    def import_without_psycopg2(name: str, *args: Any, **kwargs: Any):
        if name == "psycopg2":
            raise ImportError("simulated missing driver")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_psycopg2)

    with pytest.raises(SystemExit) as exc_info:
        apply_migrations._connect("postgresql://unused")

    assert exc_info.value.code == 3
    message = capsys.readouterr().err
    assert "python -m pip install --require-hashes -r requirements.lock" in message
    assert "pip install -r requirements.txt" not in message
    assert "requirements.txt" not in message
    assert not any(
        forbidden in message.lower()
        for forbidden in ("compile", "upgrade", "update", "atualiz", "regener", "uvx")
    )


def test_generic_apply_is_blocked_before_any_database_connection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        apply_migrations,
        "_connect",
        lambda _url: pytest.fail("generic apply must not connect"),
    )

    assert apply_migrations.cmd_apply(_args()) == 4
    assert "aplicação genérica está bloqueada" in capsys.readouterr().err


def test_harden_ledger_requires_its_own_confirmation_before_connection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        apply_migrations,
        "_connect",
        lambda _url: pytest.fail("ledger hardening must not connect without confirmation"),
    )

    assert apply_migrations.cmd_harden_ledger(_args(confirm="APPLY")) == 4
    assert "HARDEN_LEDGER" in capsys.readouterr().err


def test_bootstrap_ledger_requires_its_own_confirmation_before_connection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        apply_migrations,
        "_connect",
        lambda _url: pytest.fail("ledger bootstrap must not connect without confirmation"),
    )

    assert apply_migrations.cmd_bootstrap_ledger(_args(confirm="APPLY")) == 4
    assert "BOOTSTRAP_LEDGER" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    (
        ("status", "--database-url", "postgresql://operator:should-not-be-argv@db.invalid/app"),
        ("status", "--database-url=postgresql://operator:should-not-be-argv@db.invalid/app"),
    ),
)
def test_cli_never_accepts_or_echoes_database_url_in_argv(
    argv: tuple[str, ...], capsys: pytest.CaptureFixture[str]
) -> None:
    secret_url = "postgresql://operator:should-not-be-argv@db.invalid/app"

    assert apply_migrations.main(["runner", *argv]) == 2

    captured = capsys.readouterr()
    assert secret_url not in captured.out
    assert secret_url not in captured.err


@pytest.mark.parametrize(
    ("argv", "sensitive_values"),
    (
        (
            ("status", "--database-ur1", SENSITIVE_DSN),
            SENSITIVE_DSN_COMPONENTS,
        ),
        (
            ("status", "--database-url", SENSITIVE_DSN),
            SENSITIVE_DSN_COMPONENTS,
        ),
        (
            ("status", f"--database-ur1={SENSITIVE_DSN}"),
            SENSITIVE_DSN_COMPONENTS,
        ),
        (
            ("status", "--unknown-option", SENSITIVE_DSN),
            SENSITIVE_DSN_COMPONENTS,
        ),
        (
            ("status", SENSITIVE_DSN),
            SENSITIVE_DSN_COMPONENTS,
        ),
        (
            ("apply", "--migration", SENSITIVE_DSN),
            SENSITIVE_DSN_COMPONENTS,
        ),
        (
            ("apply", "--sha256", SENSITIVE_DSN),
            SENSITIVE_DSN_COMPONENTS,
        ),
        (
            (
                "apply",
                "--migration",
                "valid.sql",
                "--sha256",
                "0" * 64,
                "--confirm",
                SENSITIVE_TOKEN,
            ),
            SENSITIVE_TOKEN_COMPONENTS,
        ),
        (
            ("harden-ledger", "--confirm", SENSITIVE_TOKEN),
            SENSITIVE_TOKEN_COMPONENTS,
        ),
        (
            ("bootstrap-ledger", "--confirm", SENSITIVE_TOKEN),
            SENSITIVE_TOKEN_COMPONENTS,
        ),
        (
            ("apply", "--migration", "--confirm", SENSITIVE_DSN),
            SENSITIVE_DSN_COMPONENTS,
        ),
        (
            (
                "status",
                "--unknown-one",
                SENSITIVE_DSN,
                "--unknown-two",
                SENSITIVE_TOKEN,
            ),
            (*SENSITIVE_DSN_COMPONENTS, *SENSITIVE_TOKEN_COMPONENTS),
        ),
        (
            ("apply", "--migr", SENSITIVE_DSN),
            SENSITIVE_DSN_COMPONENTS,
        ),
    ),
    ids=(
        "database-url-typo",
        "legacy-database-url",
        "database-url-typo-with-attached-dsn",
        "unknown-option-followed-by-dsn",
        "dsn-as-unexpected-positional",
        "migration-value-is-dsn",
        "sha256-value-is-dsn",
        "confirmation-followed-by-token",
        "hardening-confirmation-followed-by-token",
        "bootstrap-confirmation-followed-by-token",
        "option-without-value-followed-by-dsn",
        "multiple-unknown-values",
        "abbreviation-is-disabled",
    ),
)
def test_cli_parser_never_echoes_sensitive_argv_or_reaches_side_effects(
    argv: tuple[str, ...], sensitive_values: tuple[str, ...]
) -> None:
    _assert_sanitized_usage_error(_run_cli_subprocess(argv), sensitive_values)


def test_valid_cli_status_uses_environment_without_putting_dsn_in_argv() -> None:
    result = _run_valid_status_subprocess()
    output = result.stdout + result.stderr

    assert result.returncode == 0
    assert "Ledger seguro: 0 registradas | 0 pendente(s)." in result.stdout
    assert result.stderr == ""
    assert SENSITIVE_DSN not in output
    assert "WRONG_CONNECTION_SOURCE" not in output


def test_resolve_database_url_uses_approved_environment_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = argparse.Namespace()
    monkeypatch.setenv(
        apply_migrations.DATABASE_URL_ENV,
        "postgresql+psycopg2://operator:private-test-value@db.invalid/app",
    )

    assert apply_migrations.resolve_database_url(args) == (
        "postgresql://operator:private-test-value@db.invalid/app"
    )


def test_migration_root_symlink_is_rejected_before_catalog_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_root = tmp_path / "real-migrations"
    real_root.mkdir()
    linked_root = tmp_path / "linked-migrations"
    try:
        linked_root.symlink_to(real_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink indisponível neste host: {exc}")
    monkeypatch.setattr(apply_migrations, "MIGRATIONS_DIR", linked_root)

    with pytest.raises(apply_migrations.MigrationRunnerError, match="symlink"):
        apply_migrations.discover_migrations()


@pytest.mark.parametrize(
    "selected_name",
    (
        "../20260810_031050.sql",
        "/tmp/20260810_031050.sql",
        r"C:\\temp\\20260810_031050.sql",
        "20260810_031050.sql/extra",
    ),
)
def test_rejects_non_basename_selection_before_database_connection(
    migration_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    selected_name: str,
) -> None:
    target = _write_migration(migration_root, "20260810_031050_valid.sql", "select 1;")
    monkeypatch.setattr(
        apply_migrations,
        "_connect",
        lambda _url: pytest.fail("invalid selector must not connect"),
    )

    assert (
        apply_migrations.cmd_apply(
            _args(migration=selected_name, sha256=_sha256(target), confirm="APPLY")
        )
        == 4
    )


def test_rejects_hash_mismatch_before_database_connection(
    migration_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write_migration(migration_root, "20260810_031050_valid.sql", "select 1;")
    monkeypatch.setattr(
        apply_migrations,
        "_connect",
        lambda _url: pytest.fail("bad hash must not connect"),
    )

    assert (
        apply_migrations.cmd_apply(
            _args(migration=target.name, sha256="0" * 64, confirm="APPLY")
        )
        == 4
    )


def test_rejects_missing_basename_before_database_connection(
    migration_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_migration(migration_root, "20260810_031050_valid.sql", "select 1;")
    monkeypatch.setattr(
        apply_migrations,
        "_connect",
        lambda _url: pytest.fail("missing migration must not connect"),
    )

    assert (
        apply_migrations.cmd_apply(
            _args(
                migration="20260810_031050_missing.sql",
                sha256="1" * 64,
                confirm="APPLY",
            )
        )
        == 4
    )


def test_rejects_wrong_confirmation_before_database_connection(
    migration_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write_migration(migration_root, "20260810_031050_valid.sql", "select 1;")
    monkeypatch.setattr(
        apply_migrations,
        "_connect",
        lambda _url: pytest.fail("wrong confirmation must not connect"),
    )

    assert (
        apply_migrations.cmd_apply(
            _args(migration=target.name, sha256=_sha256(target), confirm="NO")
        )
        == 4
    )


def test_rejects_symlink_outside_catalog_before_database_connection(
    migration_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    external = _write_migration(tmp_path, "outside.sql", "select 1;")
    linked = migration_root / "20260810_031050_link.sql"
    try:
        linked.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"symlink indisponível neste host: {exc}")
    monkeypatch.setattr(
        apply_migrations,
        "_connect",
        lambda _url: pytest.fail("symlink must not connect"),
    )

    assert (
        apply_migrations.cmd_apply(
            _args(migration=linked.name, sha256=_sha256(external), confirm="APPLY")
        )
        == 4
    )


def test_rejects_regular_file_swap_after_catalog_before_verified_read(
    migration_root: Path, tmp_path: Path
) -> None:
    target = _write_migration(migration_root, "20260810_031050_target.sql", "select 1;")
    selected = apply_migrations.resolve_selected_migration(
        target.name, apply_migrations.discover_migrations()
    )
    replacement = _write_migration(tmp_path, "replacement.sql", "select 2;")
    expected_hash = _sha256(replacement)
    os.replace(replacement, target)

    with pytest.raises(apply_migrations.MigrationSelectionError, match="mudou"):
        apply_migrations._read_verified_migration(selected, expected_hash)


def test_rejects_symlink_swap_after_catalog_before_verified_read(
    migration_root: Path, tmp_path: Path
) -> None:
    target = _write_migration(migration_root, "20260810_031050_target.sql", "select 1;")
    selected = apply_migrations.resolve_selected_migration(
        target.name, apply_migrations.discover_migrations()
    )
    replacement = _write_migration(tmp_path, "replacement.sql", "select 2;")
    target.unlink()
    try:
        target.symlink_to(replacement)
    except OSError as exc:
        pytest.skip(f"symlink indisponível neste host: {exc}")

    with pytest.raises(apply_migrations.MigrationSelectionError, match="mudou"):
        apply_migrations._read_verified_migration(selected, _sha256(replacement))


def test_rejects_duplicate_catalog_name(tmp_path: Path) -> None:
    path = _write_migration(tmp_path, "20260810_031050_valid.sql", "select 1;")
    with pytest.raises(apply_migrations.MigrationSelectionError, match="duplicado"):
        apply_migrations._validate_catalog([path, path], path.parent)


def test_prepare_transactional_sql_removes_only_safe_outer_wrapper() -> None:
    sql = """-- comentario
begin;
set transaction isolation level serializable;
create table public.executor_probe (id integer);
commit;
"""

    prepared = apply_migrations.prepare_transactional_sql(sql)

    assert "create table public.executor_probe" in prepared.lower()
    assert "begin;" not in prepared.lower()
    assert "commit;" not in prepared.lower()
    assert "set transaction" not in prepared.lower()


def test_rejects_ambiguous_transaction_control() -> None:
    sql = "begin;\nselect 1;\ncommit;\ncommit;\n"
    with pytest.raises(apply_migrations.MigrationSelectionError, match="não suportado"):
        apply_migrations.prepare_transactional_sql(sql)


@pytest.mark.parametrize(
    "sql",
    (
        "select 1; commit /* inline comment */;",
        "begin; select 1; rollback;",
        "start transaction; select 1; commit;",
        "select 1; savepoint unexpected;",
    ),
)
def test_rejects_inline_or_non_wrapper_transaction_controls(sql: str) -> None:
    with pytest.raises(apply_migrations.MigrationSelectionError, match="controle transacional"):
        apply_migrations.prepare_transactional_sql(sql)


def test_safe_outer_wrapper_with_decorated_commit_is_removed() -> None:
    prepared = apply_migrations.prepare_transactional_sql(
        "begin; select 1; commit /* inline comment */;"
    )

    assert prepared.strip() == "select 1;"


def test_transaction_words_in_comments_or_literals_do_not_trigger_rejection() -> None:
    sql = """-- COMMIT; ROLLBACK; BEGIN;
select 'COMMIT; ROLLBACK; BEGIN;' as note;
do $body$
begin
  perform 'COMMIT;';
end
$body$;
"""

    assert apply_migrations.prepare_transactional_sql(sql) == sql


def test_rejections_do_not_echo_database_secret(
    migration_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = _write_migration(migration_root, "20260810_031050_valid.sql", "select 1;")
    secret_url = "postgresql://operator:never-print-this-secret@db.invalid/app"

    assert (
        apply_migrations.cmd_apply(
            _args(
                database_url=secret_url,
                migration=target.name,
                sha256="not-a-hash",
                confirm="APPLY",
            )
        )
        == 4
    )
    captured = capsys.readouterr()
    assert "never-print-this-secret" not in captured.out
    assert "never-print-this-secret" not in captured.err


def _drop_and_create_database(admin_url: object, database: str) -> None:
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f"drop database if exists {database} with (force)")
            conn.exec_driver_sql(f"create database {database}")
    finally:
        admin.dispose()


@pytest.fixture(scope="module")
def executor_database_url(rls_database_url: str) -> str:  # noqa: F811
    """Banco PostgreSQL descartável exclusivo para o executor M06."""
    base = make_url(rls_database_url)
    admin_url = base.set(database="postgres")
    _drop_and_create_database(admin_url, EXECUTOR_DATABASE)
    target_url = base.set(database=EXECUTOR_DATABASE).render_as_string(
        hide_password=False
    )
    try:
        yield target_url
    finally:
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
        try:
            with admin.connect() as conn:
                conn.exec_driver_sql(
                    f"drop database if exists {EXECUTOR_DATABASE} with (force)"
                )
        finally:
            admin.dispose()


def _test_connection(url: str):
    return psycopg2.connect(apply_migrations.normalize_url(url))


def _ensure_test_roles(cur) -> None:
    cur.execute(
        """
        do $roles$
        begin
          if not exists (select 1 from pg_roles where rolname = 'anon') then
            create role anon nologin noinherit nobypassrls nocreaterole;
          end if;
          if not exists (
            select 1 from pg_roles where rolname = 'authenticated'
          ) then
            create role authenticated nologin noinherit nobypassrls nocreaterole;
          end if;
          if not exists (select 1 from pg_roles where rolname = 'service_role') then
            create role service_role nologin bypassrls nocreaterole;
          end if;
        end
        $roles$;
        """
    )
    cur.execute("alter role anon noinherit nobypassrls nocreaterole")
    cur.execute("alter role authenticated noinherit nobypassrls nocreaterole")
    cur.execute("alter role service_role noinherit bypassrls nocreaterole")


def _reset_secure_ledger(url: str, entries: tuple[str, ...] = ()) -> None:
    with _test_connection(url) as conn, conn.cursor() as cur:
        _ensure_test_roles(cur)
        cur.execute("drop table if exists public.schema_migrations cascade")
        cur.execute("drop function if exists public.executor_reject_ledger_insert()")
        for role in LEDGER_TEST_ROLES:
            cur.execute("select 1 from pg_roles where rolname = %s", (role,))
            if cur.fetchone() is not None:
                cur.execute(f"revoke {role} from anon, authenticated")
                cur.execute(f"drop role {role}")
        cur.execute(
            """
            create table public.schema_migrations (
              name text primary key,
              applied_at timestamptz not null default now()
            )
            """
        )
        cur.execute("alter table public.schema_migrations enable row level security")
        cur.execute(
            "create policy migration_ledger_service_role_bypass_only "
            "on public.schema_migrations as restrictive for all to public "
            "using (false) with check (false)"
        )
        cur.execute("revoke all privileges on schema public from public, anon, authenticated")
        cur.execute("grant usage on schema public to service_role")
        cur.execute(
            "revoke all privileges on table public.schema_migrations "
            "from public, anon, authenticated"
        )
        cur.execute(
            "revoke select (name, applied_at), insert (name, applied_at), "
            "update (name, applied_at), references (name, applied_at) "
            "on public.schema_migrations from public, anon, authenticated"
        )
        cur.execute(
            "grant select, insert, update, delete, truncate, references, trigger "
            "on public.schema_migrations to service_role"
        )
        for position, name in enumerate(entries, 1):
            cur.execute(
                "insert into public.schema_migrations(name, applied_at) "
                "values (%s, to_timestamp(%s))",
                (name, position),
            )


def _reset_insecure_ledger(url: str, entries: tuple[str, ...] = ()) -> None:
    _reset_secure_ledger(url, entries)
    with _test_connection(url) as conn, conn.cursor() as cur:
        cur.execute("alter table public.schema_migrations disable row level security")
        cur.execute(
            "drop policy migration_ledger_service_role_bypass_only "
            "on public.schema_migrations"
        )


def _ledger_rls_and_policy_state(url: str) -> tuple[bool, tuple[tuple[str, bool], ...]]:
    with _test_connection(url) as conn, conn.cursor() as cur:
        cur.execute(
            "select relrowsecurity from pg_catalog.pg_class "
            "where oid = 'public.schema_migrations'::regclass"
        )
        rls_enabled = bool(cur.fetchone()[0])
        cur.execute(
            "select polname, polpermissive from pg_catalog.pg_policy "
            "where polrelid = 'public.schema_migrations'::regclass order by polname"
        )
        policies = tuple((str(name), bool(permissive)) for name, permissive in cur.fetchall())
    return rls_enabled, policies


def _table_exists(url: str, table: str) -> bool:
    with _test_connection(url) as conn, conn.cursor() as cur:
        cur.execute("select to_regclass(%s)", (f"public.{table}",))
        return cur.fetchone()[0] is not None


def _ledger_names(url: str) -> tuple[str, ...]:
    with _test_connection(url) as conn, conn.cursor() as cur:
        cur.execute("select name from public.schema_migrations order by applied_at, name")
        return tuple(row[0] for row in cur.fetchall())


def _prepare_bootstrap_absent(url: str) -> None:
    with _test_connection(url) as conn, conn.cursor() as cur:
        _ensure_test_roles(cur)
        cur.execute(
            """
            select c.relkind
            from pg_catalog.pg_class c
            join pg_catalog.pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relname = 'schema_migrations'
            """
        )
        row = cur.fetchone()
        if row is not None:
            statement = {
                "r": "drop table public.schema_migrations cascade",
                "p": "drop table public.schema_migrations cascade",
                "v": "drop view public.schema_migrations cascade",
                "m": "drop materialized view public.schema_migrations cascade",
                "S": "drop sequence public.schema_migrations cascade",
            }.get(str(row[0]))
            if statement is None:
                pytest.fail(f"unsupported test homonym relkind: {row[0]}")
            cur.execute(statement)
        cur.execute("drop type if exists public.schema_migrations cascade")
        cur.execute(
            "revoke create on schema public "
            "from public, anon, authenticated, service_role"
        )
        cur.execute(
            "alter default privileges in schema public "
            "revoke all privileges on tables "
            "from public, anon, authenticated, service_role"
        )
        cur.execute(
            "alter default privileges revoke all privileges on tables "
            "from public, anon, authenticated, service_role"
        )
        cur.execute("select 1 from pg_catalog.pg_roles where rolname = 'agent_runtime'")
        if cur.fetchone() is not None:
            cur.execute("revoke create on schema public from agent_runtime")
            cur.execute(
                "alter default privileges in schema public "
                "revoke all privileges on tables from agent_runtime"
            )
            cur.execute(
                "alter default privileges revoke all privileges on tables "
                "from agent_runtime"
            )


def _bootstrap_snapshot(url: str) -> tuple[object, ...]:
    with _test_connection(url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select relation.oid, relation.relfilenode, relation.xmin::text,
                   relation.relacl::text, relation.relrowsecurity,
                   relation.relforcerowsecurity,
                   owner.rolname, current_user, session_user,
                   (select count(*) from public.schema_migrations),
                   (select count(*) from pg_catalog.pg_trigger
                    where tgrelid = relation.oid and not tgisinternal),
                   (select count(*) from pg_catalog.pg_rewrite
                    where ev_class = relation.oid)
            from pg_catalog.pg_class relation
            join pg_catalog.pg_roles owner on owner.oid = relation.relowner
            where relation.oid = 'public.schema_migrations'::regclass
            """
        )
        relation = tuple(cur.fetchone())
        cur.execute(
            """
            select policy.oid, policy.polname, policy.polpermissive,
                   policy.polcmd, policy.polroles,
                   pg_catalog.pg_get_expr(policy.polqual, policy.polrelid),
                   pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid)
            from pg_catalog.pg_policy policy
            where policy.polrelid = 'public.schema_migrations'::regclass
            order by policy.oid
            """
        )
        policies = tuple(tuple(row) for row in cur.fetchall())
        return (*relation, policies)


@pytest.mark.rls_integration
def test_bootstrap_ledger_creates_exact_owner_only_contract_and_rerun_is_noop(
    executor_database_url: str,
    migration_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _prepare_bootstrap_absent(executor_database_url)
    monkeypatch.setattr(
        apply_migrations,
        "discover_migrations",
        lambda: pytest.fail("bootstrap must not inspect migration history"),
    )
    args = _args(
        database_url=executor_database_url,
        confirm=apply_migrations.LEDGER_BOOTSTRAP_CONFIRMATION,
    )

    assert apply_migrations.cmd_bootstrap_ledger(args) == 0
    first = _bootstrap_snapshot(executor_database_url)
    assert first[4:9] == (True, False, first[6], first[6], first[6])
    assert first[9:12] == (0, 0, 0)
    assert len(first[12]) == 1
    policy = first[12][0]
    assert policy[1:] == (
        apply_migrations.LEDGER_DENY_POLICY_NAME,
        False,
        "*",
        [0],
        "false",
        "false",
    )
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        for role in ("anon", "authenticated", "service_role"):
            for privilege in (*apply_migrations.TABLE_PRIVILEGES, "MAINTAIN"):
                cur.execute(
                    "select pg_catalog.has_table_privilege(%s, %s, %s)",
                    (role, "public.schema_migrations", privilege),
                )
                assert cur.fetchone()[0] is False

    assert apply_migrations.cmd_bootstrap_ledger(args) == 0
    assert _bootstrap_snapshot(executor_database_url) == first


@pytest.mark.rls_integration
def test_bootstrap_rejects_relational_homonym_without_replacing_it(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _prepare_bootstrap_absent(executor_database_url)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("create view public.schema_migrations as select 1 as name")

    assert (
        apply_migrations.cmd_bootstrap_ledger(
            _args(
                database_url=executor_database_url,
                confirm=apply_migrations.LEDGER_BOOTSTRAP_CONFIRMATION,
            )
        )
        == 7
    )
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "select relkind from pg_catalog.pg_class "
            "where oid = 'public.schema_migrations'::regclass"
        )
        assert cur.fetchone() == ("v",)


@pytest.mark.rls_integration
def test_bootstrap_rejects_dangerous_default_privilege_without_creating_table(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _prepare_bootstrap_absent(executor_database_url)
    try:
        with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "alter default privileges in schema public "
                "grant select on tables to anon"
            )
        assert (
            apply_migrations.cmd_bootstrap_ledger(
                _args(
                    database_url=executor_database_url,
                    confirm=apply_migrations.LEDGER_BOOTSTRAP_CONFIRMATION,
                )
            )
            == 7
        )
        assert not _table_exists(executor_database_url, "schema_migrations")
    finally:
        with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "alter default privileges in schema public "
                "revoke select on tables from anon"
            )


@pytest.mark.rls_integration
def test_bootstrap_rejects_schema_create_grant_without_creating_table(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _prepare_bootstrap_absent(executor_database_url)
    try:
        with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
            cur.execute("grant create on schema public to anon")
        assert (
            apply_migrations.cmd_bootstrap_ledger(
                _args(
                    database_url=executor_database_url,
                    confirm=apply_migrations.LEDGER_BOOTSTRAP_CONFIRMATION,
                )
            )
            == 7
        )
        assert not _table_exists(executor_database_url, "schema_migrations")
    finally:
        with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
            cur.execute("revoke create on schema public from anon")


@pytest.mark.rls_integration
def test_bootstrap_membership_failure_rolls_back_created_ledger(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _prepare_bootstrap_absent(executor_database_url)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("select current_user")
        owner = str(cur.fetchone()[0])
        cur.execute(
            pgsql.SQL("grant {} to anon with inherit false, set true, admin false").format(
                pgsql.Identifier(owner)
            )
        )
    try:
        assert (
            apply_migrations.cmd_bootstrap_ledger(
                _args(
                    database_url=executor_database_url,
                    confirm=apply_migrations.LEDGER_BOOTSTRAP_CONFIRMATION,
                )
            )
            == 7
        )
        assert not _table_exists(executor_database_url, "schema_migrations")
    finally:
        with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
            cur.execute(
                pgsql.SQL("revoke {} from anon").format(pgsql.Identifier(owner))
            )


@pytest.mark.rls_integration
def test_bootstrap_empty_ledger_keeps_status_and_apply_blocked(
    executor_database_url: str, migration_root: Path
) -> None:
    target = _write_migration(
        migration_root,
        "0001_target.sql",
        "create table public.bootstrap_must_not_apply (id integer);",
    )
    _write_migration(migration_root, "0002_later.sql", "select 1;")
    _prepare_bootstrap_absent(executor_database_url)
    assert (
        apply_migrations.cmd_bootstrap_ledger(
            _args(
                database_url=executor_database_url,
                confirm=apply_migrations.LEDGER_BOOTSTRAP_CONFIRMATION,
            )
        )
        == 0
    )

    assert apply_migrations.cmd_status(_args(database_url=executor_database_url)) == 7
    assert (
        apply_migrations.cmd_apply(
            _args(
                database_url=executor_database_url,
                migration=target.name,
                sha256=_sha256(target),
                confirm="APPLY",
            )
        )
        == 7
    )
    assert not _table_exists(executor_database_url, "bootstrap_must_not_apply")


@pytest.mark.rls_integration
def test_bootstrap_rerun_rejects_index_drift_without_mutating_it(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _prepare_bootstrap_absent(executor_database_url)
    args = _args(
        database_url=executor_database_url,
        confirm=apply_migrations.LEDGER_BOOTSTRAP_CONFIRMATION,
    )
    assert apply_migrations.cmd_bootstrap_ledger(args) == 0
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "create index schema_migrations_applied_at_extra "
            "on public.schema_migrations(applied_at)"
        )
        cur.execute(
            "select oid from pg_catalog.pg_class "
            "where relname = 'schema_migrations_applied_at_extra'"
        )
        drift_oid = int(cur.fetchone()[0])

    assert apply_migrations.cmd_bootstrap_ledger(args) == 7
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "select oid from pg_catalog.pg_class "
            "where relname = 'schema_migrations_applied_at_extra'"
        )
        assert cur.fetchone() == (drift_oid,)


@pytest.mark.rls_integration
def test_bootstrap_never_reads_or_mutates_supabase_migration_history(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _prepare_bootstrap_absent(executor_database_url)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("create schema if not exists supabase_migrations")
        cur.execute(
            "create table if not exists supabase_migrations.schema_migrations "
            "(version text primary key)"
        )
        cur.execute("truncate supabase_migrations.schema_migrations")
        cur.execute(
            "insert into supabase_migrations.schema_migrations(version) "
            "values ('synthetic-sentinel')"
        )
        cur.execute(
            "select relation.oid, relation.relfilenode, relation.xmin::text, "
            "relation.relacl::text, count(history.*) "
            "from pg_catalog.pg_class relation "
            "cross join supabase_migrations.schema_migrations history "
            "where relation.oid = "
            "'supabase_migrations.schema_migrations'::regclass "
            "group by relation.oid, relation.relfilenode, relation.xmin, relation.relacl"
        )
        before = tuple(cur.fetchone())

    assert (
        apply_migrations.cmd_bootstrap_ledger(
            _args(
                database_url=executor_database_url,
                confirm=apply_migrations.LEDGER_BOOTSTRAP_CONFIRMATION,
            )
        )
        == 0
    )
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "select relation.oid, relation.relfilenode, relation.xmin::text, "
            "relation.relacl::text, count(history.*) "
            "from pg_catalog.pg_class relation "
            "cross join supabase_migrations.schema_migrations history "
            "where relation.oid = "
            "'supabase_migrations.schema_migrations'::regclass "
            "group by relation.oid, relation.relfilenode, relation.xmin, relation.relacl"
        )
        assert tuple(cur.fetchone()) == before
        cur.execute("select version from supabase_migrations.schema_migrations")
        assert cur.fetchall() == [("synthetic-sentinel",)]


@pytest.mark.rls_integration
def test_bootstrap_rolls_back_create_when_final_validation_fails(
    executor_database_url: str,
    migration_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _prepare_bootstrap_absent(executor_database_url)
    original = apply_migrations._validate_bootstrap_final_contract

    def fail_after_real_validation(cur, relation_oid: int, executor_oid: int) -> None:
        original(cur, relation_oid, executor_oid)
        raise apply_migrations.MigrationRunnerError("synthetic post-create failure")

    monkeypatch.setattr(
        apply_migrations,
        "_validate_bootstrap_final_contract",
        fail_after_real_validation,
    )

    assert (
        apply_migrations.cmd_bootstrap_ledger(
            _args(
                database_url=executor_database_url,
                confirm=apply_migrations.LEDGER_BOOTSTRAP_CONFIRMATION,
            )
        )
        == 7
    )
    assert not _table_exists(executor_database_url, "schema_migrations")


@pytest.mark.rls_integration
def test_bootstrap_rejects_standalone_type_homonym_without_dropping_it(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _prepare_bootstrap_absent(executor_database_url)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("create domain public.schema_migrations as text")

    assert (
        apply_migrations.cmd_bootstrap_ledger(
            _args(
                database_url=executor_database_url,
                confirm=apply_migrations.LEDGER_BOOTSTRAP_CONFIRMATION,
            )
        )
        == 7
    )
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "select typtype from pg_catalog.pg_type "
            "where typnamespace = 'public'::regnamespace "
            "and typname = 'schema_migrations'"
        )
        assert cur.fetchone() == ("d",)


@pytest.mark.rls_integration
def test_bootstrap_rejects_optional_agent_runtime_schema_create(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _prepare_bootstrap_absent(executor_database_url)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "do $role$ begin "
            "if to_regrole('agent_runtime') is null then "
            "create role agent_runtime nologin noinherit nobypassrls nocreaterole; "
            "end if; end $role$"
        )
        cur.execute("grant create on schema public to agent_runtime")
    try:
        assert (
            apply_migrations.cmd_bootstrap_ledger(
                _args(
                    database_url=executor_database_url,
                    confirm=apply_migrations.LEDGER_BOOTSTRAP_CONFIRMATION,
                )
            )
            == 7
        )
        assert not _table_exists(executor_database_url, "schema_migrations")
    finally:
        with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
            cur.execute("revoke create on schema public from agent_runtime")


@pytest.mark.rls_integration
def test_apply_rejects_nonempty_prefix_with_multiple_pending_before_sql(
    executor_database_url: str, migration_root: Path
) -> None:
    prefix = _write_migration(migration_root, "0001_prefix.sql", "select 1;")
    target = _write_migration(
        migration_root,
        "0002_target.sql",
        "create table public.apply_multiple_pending_block (id integer);",
    )
    _write_migration(migration_root, "0003_later.sql", "select 1;")
    _reset_secure_ledger(executor_database_url, (prefix.name,))

    assert (
        apply_migrations.cmd_apply(
            _args(
                database_url=executor_database_url,
                migration=target.name,
                sha256=_sha256(target),
                confirm="APPLY",
            )
        )
        == 7
    )
    assert not _table_exists(executor_database_url, "apply_multiple_pending_block")
    assert _ledger_names(executor_database_url) == (prefix.name,)


@pytest.mark.rls_integration
@pytest.mark.parametrize(
    "ledger_drift_sql",
    (
        "drop policy migration_ledger_service_role_bypass_only "
        "on public.schema_migrations",
        "alter table public.schema_migrations owner to service_role",
        """
        create function public.synthetic_ledger_trigger()
        returns trigger language plpgsql as $body$
        begin return new; end
        $body$;
        create trigger synthetic_ledger_trigger
        before insert on public.schema_migrations
        for each row execute function public.synthetic_ledger_trigger()
        """,
        "create rule synthetic_ledger_rule as on insert "
        "to public.schema_migrations do instead nothing",
        "grant select (name) on public.schema_migrations to anon",
        "alter table public.schema_migrations set unlogged",
        "alter table public.schema_migrations "
        "add constraint synthetic_name_nonempty check (name <> '')",
        "update public.schema_migrations "
        "set applied_at = applied_at + interval '1 second'",
    ),
    ids=(
        "policy",
        "owner",
        "trigger",
        "rule",
        "column-acl",
        "unlogged",
        "constraint",
        "applied-at",
    ),
)
def test_apply_postcheck_rolls_back_domain_sql_and_ledger_drift(
    executor_database_url: str,
    migration_root: Path,
    ledger_drift_sql: str,
) -> None:
    prefix = _write_migration(migration_root, "0001_prefix.sql", "select 1;")
    target = _write_migration(
        migration_root,
        "0002_drift.sql",
        "create table public.apply_postcheck_domain (id integer);\n"
        + ledger_drift_sql
        + ";\n",
    )
    _reset_secure_ledger(executor_database_url, (prefix.name,))

    assert (
        apply_migrations.cmd_apply(
            _args(
                database_url=executor_database_url,
                migration=target.name,
                sha256=_sha256(target),
                confirm="APPLY",
            )
        )
        == 7
    )
    assert not _table_exists(executor_database_url, "apply_postcheck_domain")
    assert _ledger_names(executor_database_url) == (prefix.name,)


@pytest.mark.rls_integration
def test_status_rejects_absent_ledger_without_creating_it(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_first.sql", "select 1;")
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("drop table if exists public.schema_migrations cascade")

    assert apply_migrations.cmd_status(_args(database_url=executor_database_url)) == 7
    assert not _table_exists(executor_database_url, "schema_migrations")


@pytest.mark.rls_integration
def test_status_never_echoes_destination_or_query_secret(
    executor_database_url: str,
    migration_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_migration(migration_root, "0001_first.sql", "select 1;")
    _reset_secure_ledger(executor_database_url, ("0001_first.sql",))
    guarded_url = f"{executor_database_url}?application_name=never-print-query-secret"

    assert apply_migrations.cmd_status(_args(database_url=guarded_url)) == 0

    captured = capsys.readouterr()
    assert "never-print-query-secret" not in captured.out
    assert "never-print-query-secret" not in captured.err
    assert "Destino:" not in captured.out


@pytest.mark.rls_integration
def test_status_rejects_incompatible_or_duplicate_ledger_without_writes(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_first.sql", "select 1;")
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        _ensure_test_roles(cur)
        cur.execute("drop table if exists public.schema_migrations cascade")
        cur.execute(
            "create table public.schema_migrations "
            "(name text not null, applied_at timestamptz not null default now())"
        )
        cur.execute("alter table public.schema_migrations enable row level security")
        cur.execute(
            "insert into public.schema_migrations(name) values ('0001_first.sql'), "
            "('0001_first.sql')"
        )

    assert apply_migrations.cmd_status(_args(database_url=executor_database_url)) == 7
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("select count(*) from public.schema_migrations")
        assert cur.fetchone()[0] == 2


@pytest.mark.rls_integration
@pytest.mark.parametrize(
    ("entries", "expected_fragment"),
    (
        (("unknown.sql",), "desconhecida"),
        (("0001_first.sql", "0003_third.sql"), "ordem"),
        ((), "vazio"),
    ),
)
def test_generic_status_rejects_drift_without_writes(
    executor_database_url: str,
    migration_root: Path,
    entries: tuple[str, ...],
    expected_fragment: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    names = ("0001_first.sql", "0002_second.sql", "0003_third.sql")
    for name in names:
        _write_migration(migration_root, name, "select 1;")
    _reset_secure_ledger(executor_database_url, entries)

    assert apply_migrations.cmd_status(_args(database_url=executor_database_url)) == 7
    assert expected_fragment in capsys.readouterr().err
    assert _ledger_names(executor_database_url) == entries


@pytest.mark.rls_integration
def test_generic_status_rejects_66_local_files_vs_31_ledger_entries_without_writes(
    executor_database_url: str, migration_root: Path
) -> None:
    names = tuple(f"{index:04d}_migration.sql" for index in range(1, 67))
    for name in names:
        _write_migration(migration_root, name, "select 1;")
    applied = names[:31]
    _reset_secure_ledger(executor_database_url, applied)

    assert apply_migrations.cmd_status(_args(database_url=executor_database_url)) == 7
    assert _ledger_names(executor_database_url) == applied


@pytest.mark.rls_integration
def test_single_apply_requires_secure_ledger_and_preserves_it_on_failure(
    executor_database_url: str, migration_root: Path
) -> None:
    target = _write_migration(
        migration_root,
        "0001_target.sql",
        "create table public.executor_insecure_block (id integer);",
    )
    _reset_secure_ledger(executor_database_url)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("grant select on public.schema_migrations to public")

    assert (
        apply_migrations.cmd_apply(
            _args(
                database_url=executor_database_url,
                migration=target.name,
                sha256=_sha256(target),
                confirm="APPLY",
            )
        )
        == 7
    )
    assert not _table_exists(executor_database_url, "executor_insecure_block")
    assert _ledger_names(executor_database_url) == ()


@pytest.mark.rls_integration
def test_single_apply_rejects_public_column_acl_without_writes(
    executor_database_url: str, migration_root: Path
) -> None:
    target = _write_migration(
        migration_root,
        "0001_column_acl.sql",
        "create table public.executor_column_acl_block (id integer);",
    )
    _reset_secure_ledger(executor_database_url)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("grant select (name) on public.schema_migrations to public")

    assert (
        apply_migrations.cmd_apply(
            _args(
                database_url=executor_database_url,
                migration=target.name,
                sha256=_sha256(target),
                confirm="APPLY",
            )
        )
        == 7
    )
    assert not _table_exists(executor_database_url, "executor_column_acl_block")
    assert _ledger_names(executor_database_url) == ()


@pytest.mark.rls_integration
@pytest.mark.parametrize(
    ("member", "role", "membership_options"),
    (
        ("anon", "m06_ledger_writer", "inherit false, set true, admin false"),
        (
            "authenticated",
            "m06_ledger_admin_writer",
            "inherit false, set false, admin true",
        ),
        ("anon", "m06_ledger_bypass", "inherit false, set true, admin false"),
    ),
)
def test_single_apply_rejects_reachable_membership_with_ledger_capability(
    executor_database_url: str,
    migration_root: Path,
    member: str,
    role: str,
    membership_options: str,
) -> None:
    target = _write_migration(
        migration_root,
        "0001_membership_block.sql",
        "create table public.executor_membership_block (id integer);",
    )
    _reset_secure_ledger(executor_database_url)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        if role == "m06_ledger_bypass":
            cur.execute(f"create role {role} nologin bypassrls nocreaterole")
        else:
            cur.execute(f"create role {role} nologin nobypassrls nocreaterole")
            cur.execute(f"grant insert on public.schema_migrations to {role}")
        cur.execute(f"grant {role} to {member} with {membership_options}")
        cur.execute(
            "select pg_has_role(%s, %s, 'set')",
            (member, role),
        )
        if "set true" in membership_options:
            assert cur.fetchone()[0] is True
            cur.execute(f"set session authorization {member}")
            cur.execute(f"set role {role}")
            cur.execute("select current_user")
            assert cur.fetchone()[0] == role

    assert (
        apply_migrations.cmd_apply(
            _args(
                database_url=executor_database_url,
                migration=target.name,
                sha256=_sha256(target),
                confirm="APPLY",
            )
        )
        == 7
    )
    assert not _table_exists(executor_database_url, "executor_membership_block")
    assert _ledger_names(executor_database_url) == ()


@pytest.mark.rls_integration
def test_single_apply_allows_safe_set_membership_without_ledger_access(
    executor_database_url: str, migration_root: Path
) -> None:
    prefix = _write_migration(migration_root, "0001_prefix.sql", "select 1;")
    target = _write_migration(
        migration_root,
        "0002_membership_safe.sql",
        "create table public.executor_membership_safe (id integer);",
    )
    _reset_secure_ledger(executor_database_url, (prefix.name,))
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("create role m06_ledger_safe nologin nobypassrls nocreaterole")
        cur.execute(
            "grant m06_ledger_safe to anon with inherit false, set true, admin false"
        )
        cur.execute("select pg_has_role('anon', 'm06_ledger_safe', 'set')")
        assert cur.fetchone()[0] is True

    assert (
        apply_migrations.cmd_apply(
            _args(
                database_url=executor_database_url,
                migration=target.name,
                sha256=_sha256(target),
                confirm="APPLY",
            )
        )
        == 0
    )
    assert _table_exists(executor_database_url, "executor_membership_safe")
    assert _ledger_names(executor_database_url) == (prefix.name, target.name)


@pytest.mark.rls_integration
def test_single_apply_rejects_ledger_without_rls_without_writes(
    executor_database_url: str, migration_root: Path
) -> None:
    target = _write_migration(
        migration_root,
        "0001_rls_required.sql",
        "create table public.executor_rls_block (id integer);",
    )
    _reset_secure_ledger(executor_database_url)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("alter table public.schema_migrations disable row level security")

    assert (
        apply_migrations.cmd_apply(
            _args(
                database_url=executor_database_url,
                migration=target.name,
                sha256=_sha256(target),
                confirm="APPLY",
            )
        )
        == 7
    )
    assert not _table_exists(executor_database_url, "executor_rls_block")
    assert _ledger_names(executor_database_url) == ()


@pytest.mark.rls_integration
def test_harden_ledger_secures_drifted_history_and_preserves_single_file_apply(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_first.sql", "select 1;")
    drifted = _write_migration(migration_root, "0002_drifted.sql", "select 1;")
    target = _write_migration(
        migration_root,
        "0003_selected.sql",
        "create table public.executor_after_ledger_hardening (id integer primary key);",
    )
    _reset_insecure_ledger(
        executor_database_url, ("0001_first.sql", drifted.name)
    )
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "grant select, insert, update, delete, truncate, references, trigger "
            "on public.schema_migrations to public, anon, authenticated"
        )
        cur.execute(
            "grant select (name), insert (name), update (name), references (name) "
            "on public.schema_migrations to public"
        )

    harden_args = _args(
        database_url=executor_database_url,
        confirm=apply_migrations.LEDGER_HARDEN_CONFIRMATION,
    )
    assert apply_migrations.cmd_harden_ledger(harden_args) == 0

    rls_enabled, policies = _ledger_rls_and_policy_state(executor_database_url)
    assert rls_enabled is True
    assert policies == ((apply_migrations.LEDGER_DENY_POLICY_NAME, False),)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("select 'public.schema_migrations'::regclass::oid")
        relation_oid = int(cur.fetchone()[0])
        assert apply_migrations._ledger_deny_policy_state(cur, relation_oid) == (1, 1)
        for role in ("anon", "authenticated"):
            for privilege in (*apply_migrations.TABLE_PRIVILEGES, "MAINTAIN"):
                cur.execute(
                    "select has_table_privilege(%s, 'public.schema_migrations', %s)",
                    (role, privilege),
                )
                assert cur.fetchone()[0] is False
            for column in ("name", "applied_at"):
                for privilege in apply_migrations.COLUMN_PRIVILEGES:
                    cur.execute(
                        "select has_column_privilege(%s, 'public.schema_migrations', %s, %s)",
                        (role, column, privilege),
                    )
                    assert cur.fetchone()[0] is False
        cur.execute(
            "select has_table_privilege('service_role', 'public.schema_migrations', 'select')"
        )
        assert cur.fetchone()[0] is True

    assert (
        apply_migrations.cmd_apply(
            _args(
                database_url=executor_database_url,
                migration=target.name,
                sha256=_sha256(target),
                confirm="APPLY",
            )
        )
        == 0
    )
    assert _table_exists(executor_database_url, "executor_after_ledger_hardening")
    assert _ledger_names(executor_database_url) == (
        "0001_first.sql",
        drifted.name,
        target.name,
    )
    assert apply_migrations.cmd_harden_ledger(harden_args) == 0


@pytest.mark.rls_integration
def test_harden_ledger_rejects_unknown_history_without_writes(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _reset_insecure_ledger(executor_database_url, ("0000_unknown.sql",))

    assert (
        apply_migrations.cmd_harden_ledger(
            _args(
                database_url=executor_database_url,
                confirm=apply_migrations.LEDGER_HARDEN_CONFIRMATION,
            )
        )
        == 7
    )
    assert _ledger_rls_and_policy_state(executor_database_url) == (False, ())
    assert _ledger_names(executor_database_url) == ("0000_unknown.sql",)


@pytest.mark.rls_integration
def test_harden_ledger_rejects_missing_applied_at_default_without_writes(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _reset_insecure_ledger(executor_database_url)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("alter table public.schema_migrations alter column applied_at drop default")

    assert (
        apply_migrations.cmd_harden_ledger(
            _args(
                database_url=executor_database_url,
                confirm=apply_migrations.LEDGER_HARDEN_CONFIRMATION,
            )
        )
        == 7
    )
    assert _ledger_rls_and_policy_state(executor_database_url) == (False, ())


@pytest.mark.rls_integration
def test_harden_ledger_rejects_unexpected_policy_without_writes(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _reset_insecure_ledger(executor_database_url)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "create policy unexpected_ledger_policy on public.schema_migrations "
            "for select to public using (true)"
        )

    assert (
        apply_migrations.cmd_harden_ledger(
            _args(
                database_url=executor_database_url,
                confirm=apply_migrations.LEDGER_HARDEN_CONFIRMATION,
            )
        )
        == 7
    )
    assert _ledger_rls_and_policy_state(executor_database_url) == (
        False,
        (("unexpected_ledger_policy", True),),
    )


@pytest.mark.rls_integration
def test_harden_ledger_rolls_back_if_service_role_would_lose_access(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _reset_insecure_ledger(executor_database_url)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("revoke all privileges on public.schema_migrations from service_role")
        cur.execute("grant select on public.schema_migrations to public")

    assert (
        apply_migrations.cmd_harden_ledger(
            _args(
                database_url=executor_database_url,
                confirm=apply_migrations.LEDGER_HARDEN_CONFIRMATION,
            )
        )
        == 7
    )
    assert _ledger_rls_and_policy_state(executor_database_url) == (False, ())
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "select has_table_privilege('service_role', 'public.schema_migrations', 'select')"
        )
        assert cur.fetchone()[0] is True


@pytest.mark.rls_integration
def test_harden_ledger_rejects_reachable_privileged_membership(
    executor_database_url: str, migration_root: Path
) -> None:
    _write_migration(migration_root, "0001_known.sql", "select 1;")
    _reset_insecure_ledger(executor_database_url)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("create role m06_ledger_writer nologin nobypassrls nocreaterole")
        cur.execute("grant select on public.schema_migrations to m06_ledger_writer")
        cur.execute(
            "grant m06_ledger_writer to anon with inherit false, set true, admin false"
        )

    assert (
        apply_migrations.cmd_harden_ledger(
            _args(
                database_url=executor_database_url,
                confirm=apply_migrations.LEDGER_HARDEN_CONFIRMATION,
            )
        )
        == 7
    )
    assert _ledger_rls_and_policy_state(executor_database_url) == (False, ())


@pytest.mark.rls_integration
def test_single_apply_runs_only_selected_file_and_reapply_is_safe(
    executor_database_url: str, migration_root: Path
) -> None:
    neighbor = _write_migration(
        migration_root,
        "0001_neighbor.sql",
        "create table public.executor_neighbor (id integer primary key);",
    )
    target = _write_migration(
        migration_root,
        "0002_target.sql",
        """begin;
set transaction isolation level serializable;
create table public.executor_target (id integer primary key);
commit;
""",
    )
    _reset_secure_ledger(executor_database_url, (neighbor.name,))
    args = _args(
        database_url=executor_database_url,
        migration=target.name,
        sha256=_sha256(target),
        confirm="APPLY",
    )

    assert apply_migrations.cmd_apply(args) == 0
    assert _table_exists(executor_database_url, "executor_target")
    assert not _table_exists(executor_database_url, "executor_neighbor")
    assert _ledger_names(executor_database_url) == (neighbor.name, target.name)

    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("drop table public.executor_target")
    assert apply_migrations.cmd_apply(args) == 0
    assert not _table_exists(executor_database_url, "executor_target")
    assert _ledger_names(executor_database_url) == (neighbor.name, target.name)


@pytest.mark.rls_integration
def test_current_m06_migration_runs_as_one_verified_file(
    executor_database_url: str,
    migration_root: Path,
) -> None:
    """O arquivo aprovado mantém DDL e ledger no mesmo commit do executor."""
    prefix = _write_migration(migration_root, "0001_prefix.sql", "select 1;")
    target = migration_root / CURRENT_M06_MIGRATION.name
    target.write_bytes(CURRENT_M06_MIGRATION.read_bytes())
    _reset_secure_ledger(executor_database_url, (prefix.name,))
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        for table in CLOSED_TABLES:
            cur.execute(f"drop table if exists public.{table} cascade")
            cur.execute(
                f"create table public.{table} (id integer primary key, payload text)"
            )
            cur.execute(
                f"grant all privileges on table public.{table} "
                "to anon, authenticated, service_role"
            )

    assert (
        apply_migrations.cmd_apply(
            _args(
                database_url=executor_database_url,
                migration=target.name,
                sha256=_sha256(target),
                confirm="APPLY",
            )
        )
        == 0
    )
    assert _ledger_names(executor_database_url) == (prefix.name, target.name)
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        for table in CLOSED_TABLES:
            cur.execute(
                "select relrowsecurity from pg_class "
                "where oid = %s::regclass",
                (f"public.{table}",),
            )
            assert cur.fetchone()[0] is True
            for role in ("anon", "authenticated"):
                cur.execute(
                    "select has_table_privilege(%s, %s, 'select')",
                    (role, f"public.{table}"),
                )
                assert cur.fetchone()[0] is False


@pytest.mark.rls_integration
def test_single_apply_rolls_back_sql_and_ledger_together(
    executor_database_url: str, migration_root: Path
) -> None:
    prefix = _write_migration(migration_root, "0001_prefix.sql", "select 1;")
    target = _write_migration(
        migration_root,
        "0002_failing.sql",
        """begin;
create table public.executor_partial (id integer primary key);
select 1 / 0;
commit;
""",
    )
    _reset_secure_ledger(executor_database_url, (prefix.name,))

    assert (
        apply_migrations.cmd_apply(
            _args(
                database_url=executor_database_url,
                migration=target.name,
                sha256=_sha256(target),
                confirm="APPLY",
            )
        )
        == 5
    )
    assert not _table_exists(executor_database_url, "executor_partial")
    assert _ledger_names(executor_database_url) == (prefix.name,)


@pytest.mark.rls_integration
def test_preexisting_ledger_trigger_blocks_before_migration_sql(
    executor_database_url: str, migration_root: Path
) -> None:
    prefix = _write_migration(migration_root, "0001_prefix.sql", "select 1;")
    target = _write_migration(
        migration_root,
        "0002_ledger_atomic.sql",
        "create table public.executor_ledger_atomic (id integer primary key);",
    )
    _reset_secure_ledger(executor_database_url, (prefix.name,))
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            create function public.executor_reject_ledger_insert()
            returns trigger language plpgsql as $function$
            begin
              raise exception 'force ledger insert failure';
            end
            $function$
            """
        )
        cur.execute(
            """
            create trigger executor_reject_ledger_insert
            before insert on public.schema_migrations
            for each row execute function public.executor_reject_ledger_insert()
            """
        )

    assert (
        apply_migrations.cmd_apply(
            _args(
                database_url=executor_database_url,
                migration=target.name,
                sha256=_sha256(target),
                confirm="APPLY",
            )
        )
        == 7
    )
    assert not _table_exists(executor_database_url, "executor_ledger_atomic")
    assert _ledger_names(executor_database_url) == (prefix.name,)


@pytest.mark.rls_integration
def test_service_role_bypass_and_ledger_access_are_preserved(
    executor_database_url: str, migration_root: Path
) -> None:
    prefix = _write_migration(migration_root, "0001_prefix.sql", "select 1;")
    target = _write_migration(
        migration_root,
        "0002_service_role.sql",
        "create table public.executor_service_role (id integer primary key);",
    )
    _reset_secure_ledger(executor_database_url, (prefix.name,))

    assert (
        apply_migrations.cmd_apply(
            _args(
                database_url=executor_database_url,
                migration=target.name,
                sha256=_sha256(target),
                confirm="APPLY",
            )
        )
        == 0
    )
    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("select rolbypassrls from pg_roles where rolname = 'service_role'")
        assert cur.fetchone()[0] is True
        cur.execute("set local role service_role")
        cur.execute("select name from public.schema_migrations")
        assert cur.fetchall() == [(prefix.name,), (target.name,)]
