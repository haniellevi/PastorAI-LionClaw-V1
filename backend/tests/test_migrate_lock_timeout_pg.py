"""migrate.py --lock-timeout against a real, disposable local PostgreSQL (synthetic tables only)."""
from __future__ import annotations

import os
import time
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from scripts import migrate
from tests.conftest_rls import assert_disposable_database

pytestmark = pytest.mark.rls_integration
DATABASE_ENV = "MIGRATE_TEST_DATABASE_URL"


@pytest.fixture(scope="module")
def rls_database_url():
    url = os.environ.get(DATABASE_ENV, "").strip()
    if not url:
        pytest.skip(f"{DATABASE_ENV} não definida para PostgreSQL descartável")
    assert_disposable_database(url)
    parsed = urlsplit(url)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.path != "/migrate_lock_test":
        raise RuntimeError("exige banco local descartável exclusivo migrate_lock_test")
    import psycopg2

    url = url.replace("postgresql+psycopg2:", "postgresql:", 1)  # libpq não entende o dialeto
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS public.schema_migrations (name text PRIMARY KEY)")
    return url


@pytest.fixture
def connect(rls_database_url):
    import psycopg2

    opened = []

    def _connect():
        conn = psycopg2.connect(rls_database_url)
        opened.append(conn)
        return conn

    yield _connect
    for conn in opened:
        conn.close()


@pytest.fixture
def migration(tmp_path, monkeypatch):
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)

    def _write(sql: str) -> str:
        name = f"20991231_{uuid4().hex[:6]}_lock_timeout_test.sql"
        (tmp_path / name).write_text(sql, encoding="utf-8")
        return name

    return _write


def _one(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone() if cur.description else None
    conn.commit()
    return row[0] if row else None


def _ledger(conn, name) -> bool:
    return bool(_one(conn, "SELECT count(*) FROM public.schema_migrations WHERE name = %s", (name,)))


def test_lock_real_desiste_e_desfaz_ddl_e_ledger(connect, migration):
    import psycopg2.errors

    table = f"lock_{uuid4().hex[:8]}"
    setup = connect()
    _one(setup, f"CREATE TABLE {table} (id int)")
    holder = connect()
    with holder.cursor() as cur:
        cur.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")  # transação aberta
    name = migration(f"ALTER TABLE {table} ADD COLUMN extra int;\n")
    applicant = connect()
    _one(applicant, "SET statement_timeout = '3s'")  # falha finita se a proteção regredir
    started = time.monotonic()
    with pytest.raises(psycopg2.errors.LockNotAvailable) as exc:
        migrate.cmd_apply(applicant, name, transactional=True, lock_timeout=300)
    assert time.monotonic() - started < 3
    assert exc.value.pgcode == "55P03"
    holder.rollback()
    assert not _ledger(setup, name)
    assert not _one(setup, "SELECT count(*) FROM information_schema.columns "
                           "WHERE table_name = %s AND column_name = 'extra'", (table,))


@pytest.mark.parametrize(("limite", "mostrado"), [(300, "300ms"), (2000, "2s"), (60_000, "1min")])
def test_limite_vale_durante_o_sql_e_some_apos_o_commit(connect, migration, limite, mostrado):
    table = f"guc_{uuid4().hex[:8]}"
    name = migration(f"CREATE TABLE {table} AS SELECT current_setting('lock_timeout') AS valor;\n")
    conn = connect()
    before = _one(conn, "SHOW lock_timeout")
    assert migrate.cmd_apply(conn, name, transactional=True, lock_timeout=limite) == 0
    assert _one(conn, f"SELECT valor FROM {table}") == mostrado
    assert _one(conn, "SHOW lock_timeout") == before  # SET LOCAL não vaza para a sessão
    assert _ledger(conn, name)


@pytest.mark.parametrize("isolation", ["SERIALIZABLE", "REPEATABLE READ"])
def test_cli_preserva_isolamento_solicitado_pela_migration(connect, migration, monkeypatch, isolation):
    table = f"isolation_{uuid4().hex[:8]}"
    name = migration(
        f"BEGIN;\nSET TRANSACTION ISOLATION LEVEL {isolation};\n"
        f"CREATE TABLE {table} AS SELECT current_setting('transaction_isolation') AS nivel, "
        "current_setting('lock_timeout') AS limite;\nCOMMIT;\n"
    )
    monkeypatch.setattr(migrate, "_connect", connect)
    assert migrate.main(["apply", name, "--yes"]) == 0
    check = connect()
    assert _one(check, f"SELECT nivel FROM {table}") == isolation.lower()
    assert _one(check, f"SELECT limite FROM {table}") == "2s"
    assert _ledger(check, name)


@pytest.mark.parametrize(
    ("pedido", "da_migration"),
    [(2000, "5s"), (1000, "2s"), (2000, "1min"), (2000, "1h"), (2000, "1d"), (2000, "0")],
)
def test_migration_que_afrouxa_o_limite_e_recusada_com_rollback(connect, migration, pedido, da_migration):
    table = f"loose_{uuid4().hex[:8]}"
    name = migration(f"SET lock_timeout = '{da_migration}';\nCREATE TABLE {table} (id int);\n")
    conn = connect()
    with pytest.raises(RuntimeError, match="reaplique com --lock-timeout explícito"):
        migrate.cmd_apply(conn, name, transactional=True, lock_timeout=pedido)
    check = connect()
    assert not _ledger(check, name)
    assert _one(check, "SELECT to_regclass(%s)", (table,)) is None


def test_limite_explicito_igual_ao_da_migration_passa(connect, migration):
    table = f"five_{uuid4().hex[:8]}"
    name = migration(f"SET lock_timeout = '5s';\nCREATE TABLE {table} (id int);\n")
    conn = connect()
    assert migrate.cmd_apply(conn, name, transactional=True, lock_timeout=5000) == 0
    assert _ledger(conn, name)
    assert _one(conn, "SELECT to_regclass(%s)", (table,)) is not None


def test_no_transaction_mantem_indice_concorrente_isolado(connect, migration):
    table = f"conc_{uuid4().hex[:8]}"
    setup = connect()
    _one(setup, f"CREATE TABLE {table} (id int)")
    index = f"{table}_id_idx"
    name = migration(f"SET lock_timeout = '2s';\nCREATE INDEX CONCURRENTLY {index} ON {table} (id);\n")
    conn = connect()
    assert migrate.cmd_apply(conn, name, transactional=False) == 0
    assert conn.autocommit
    assert _one(setup, "SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(%s)", (index,)) is True
    assert _ledger(setup, name)
