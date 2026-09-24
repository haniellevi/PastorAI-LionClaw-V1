"""scripts/migrate.py: aplicador simples de migrations do MVP (sem banco real)."""

from __future__ import annotations

import pytest

from scripts import migrate


class _Cur:
    def __init__(self, conn) -> None:
        self.conn = conn
        self._rows: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        pass

    def execute(self, sql, params=None) -> None:
        self.conn.executed.append(sql)
        if sql.startswith("SELECT to_regclass"):
            self._rows = [("public.schema_migrations",)]
        elif sql.startswith("SELECT name FROM"):
            self._rows = [(n,) for n in self.conn.applied]
        elif sql.startswith("INSERT INTO"):
            self.conn.applied.add(params[0])
        elif self.conn.fail_on and self.conn.fail_on in sql:
            raise RuntimeError("falha simulada")

    def fetchone(self):
        return self._rows[0]

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, applied=(), fail_on=None) -> None:
        self.applied = set(applied)
        self.executed: list[str] = []
        self.fail_on = fail_on
        self.commits = self.rollbacks = 0
        self.autocommit = False

    def cursor(self):
        return _Cur(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_pendentes_em_ordem_de_nome() -> None:
    files = ["0001_a.sql", "20260101_000000_b.sql", "20260201_000000_c.sql"]
    assert migrate.pending(files, {"0001_a.sql"}) == files[1:]


def test_lista_so_sql_do_topo_da_pasta() -> None:
    files = migrate.migration_files()
    assert files == sorted(files)
    assert all(name.endswith(".sql") and "/" not in name for name in files)
    assert "0001_extensions_and_enums.sql" in files


def test_apply_exige_yes() -> None:
    with pytest.raises(SystemExit):
        migrate.main(["apply", "0001_extensions_and_enums.sql"])


def test_apply_registra_no_ledger_na_mesma_transacao() -> None:
    name = migrate.migration_files()[-1]
    conn = _Conn()
    assert migrate.cmd_apply(conn, name, transactional=True) == 0
    assert name in conn.applied
    assert conn.autocommit is False
    assert conn.rollbacks == 0


def test_apply_recusa_migration_ja_aplicada() -> None:
    name = migrate.migration_files()[0]
    with pytest.raises(SystemExit):
        migrate.cmd_apply(_Conn(applied={name}), name, transactional=True)


def test_apply_recusa_caminho_fora_da_pasta() -> None:
    with pytest.raises(SystemExit):
        migrate.cmd_apply(_Conn(), "../README.md", transactional=True)


def test_falha_faz_rollback_e_nao_registra() -> None:
    name = migrate.migration_files()[-1]
    sql = (migrate.MIGRATIONS_DIR / name).read_text(encoding="utf-8")
    conn = _Conn(fail_on=sql[:40])
    with pytest.raises(RuntimeError):
        migrate.cmd_apply(conn, name, transactional=True)
    assert conn.rollbacks == 1
    assert name not in conn.applied


def test_remove_so_o_begin_commit_externo() -> None:
    sql = "-- cabeçalho\nbegin;\ncreate table t (id int);\ncommit;\n-- fim\n"
    out = migrate.strip_outer_transaction(sql)
    assert "begin;" not in out.lower() and "commit;" not in out.lower()
    assert "create table t" in out


def test_sem_wrapper_fica_igual() -> None:
    sql = "create index concurrently i on t (id);\n"
    assert migrate.strip_outer_transaction(sql).strip() == sql.strip()


def test_recusa_commit_no_meio() -> None:
    with pytest.raises(ValueError):
        migrate.strip_outer_transaction("begin;\nselect 1;\ncommit;\nselect 2;\n")


def test_todas_as_migrations_do_catalogo_sao_executaveis_pelo_runner() -> None:
    for name in migrate.migration_files():
        migrate.strip_outer_transaction(
            (migrate.MIGRATIONS_DIR / name).read_text(encoding="utf-8")
        )


def test_migrations_pausadas_ficam_fora_e_sao_recusadas() -> None:
    pausadas = [
        p.name for p in migrate.MIGRATIONS_DIR.glob("*.sql") if migrate.is_paused(p)
    ]
    assert pausadas, "esperava as migrations E4B/consentimento marcadas"
    assert not set(pausadas) & set(migrate.migration_files())
    with pytest.raises(SystemExit):
        migrate.cmd_apply(_Conn(), pausadas[0], transactional=True)


def test_apply_executa_sem_o_wrapper_externo() -> None:
    name = next(
        n
        for n in migrate.migration_files()
        if (migrate.MIGRATIONS_DIR / n).read_text(encoding="utf-8").lower().count("begin;")
    )
    conn = _Conn()
    migrate.cmd_apply(conn, name, transactional=True)
    executed_sql = conn.executed[2]  # to_regclass, select ledger, migration
    assert not any(
        line.strip().lower() in {"begin;", "commit;"} for line in executed_sql.splitlines()
    )
