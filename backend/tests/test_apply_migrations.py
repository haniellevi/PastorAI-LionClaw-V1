"""Testes do executor fail-closed de migrations da M06.

Os testes unitários não conectam a banco algum. Os cenários marcados como
``rls_integration`` usam somente ``RLS_TEST_DATABASE_URL``, cujo guard comum
recusa DEV/PROD e deve apontar para PostgreSQL descartável.
"""

from __future__ import annotations

import argparse
import builtins
import hashlib
from pathlib import Path
from typing import Any

import psycopg2
import pytest
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
CURRENT_M06_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260810_031050_explicit_deny_policies_for_closed_tables.sql"
)


def _args(
    *,
    database_url: str = "postgresql://operator:private-test-value@db.invalid/app",
    migration: str | None = None,
    sha256: str | None = None,
    confirm: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        database_url=database_url,
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
        cur.execute(
            """
            create table public.schema_migrations (
              name text primary key,
              applied_at timestamptz not null default now()
            )
            """
        )
        cur.execute("alter table public.schema_migrations enable row level security")
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


def _table_exists(url: str, table: str) -> bool:
    with _test_connection(url) as conn, conn.cursor() as cur:
        cur.execute("select to_regclass(%s)", (f"public.{table}",))
        return cur.fetchone()[0] is not None


def _ledger_names(url: str) -> tuple[str, ...]:
    with _test_connection(url) as conn, conn.cursor() as cur:
        cur.execute("select name from public.schema_migrations order by applied_at, name")
        return tuple(row[0] for row in cur.fetchall())


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
        ((), "múltiplas"),
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
def test_single_apply_runs_only_selected_file_and_reapply_is_safe(
    executor_database_url: str, migration_root: Path
) -> None:
    target = _write_migration(
        migration_root,
        "0001_target.sql",
        """begin;
set transaction isolation level serializable;
create table public.executor_target (id integer primary key);
commit;
""",
    )
    _write_migration(
        migration_root,
        "0002_neighbor.sql",
        "create table public.executor_neighbor (id integer primary key);",
    )
    _reset_secure_ledger(executor_database_url)
    args = _args(
        database_url=executor_database_url,
        migration=target.name,
        sha256=_sha256(target),
        confirm="APPLY",
    )

    assert apply_migrations.cmd_apply(args) == 0
    assert _table_exists(executor_database_url, "executor_target")
    assert not _table_exists(executor_database_url, "executor_neighbor")
    assert _ledger_names(executor_database_url) == (target.name,)

    with _test_connection(executor_database_url) as conn, conn.cursor() as cur:
        cur.execute("drop table public.executor_target")
    assert apply_migrations.cmd_apply(args) == 0
    assert not _table_exists(executor_database_url, "executor_target")
    assert _ledger_names(executor_database_url) == (target.name,)


@pytest.mark.rls_integration
def test_current_m06_migration_runs_as_one_verified_file(
    executor_database_url: str,
) -> None:
    """O arquivo aprovado mantém DDL e ledger no mesmo commit do executor."""
    _reset_secure_ledger(executor_database_url)
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
                migration=CURRENT_M06_MIGRATION.name,
                sha256=_sha256(CURRENT_M06_MIGRATION),
                confirm="APPLY",
            )
        )
        == 0
    )
    assert _ledger_names(executor_database_url) == (CURRENT_M06_MIGRATION.name,)
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
    target = _write_migration(
        migration_root,
        "0001_failing.sql",
        """begin;
create table public.executor_partial (id integer primary key);
select 1 / 0;
commit;
""",
    )
    _reset_secure_ledger(executor_database_url)

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
    assert _ledger_names(executor_database_url) == ()


@pytest.mark.rls_integration
def test_service_role_bypass_and_ledger_access_are_preserved(
    executor_database_url: str, migration_root: Path
) -> None:
    target = _write_migration(
        migration_root,
        "0001_service_role.sql",
        "create table public.executor_service_role (id integer primary key);",
    )
    _reset_secure_ledger(executor_database_url)

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
        assert cur.fetchall() == [(target.name,)]
