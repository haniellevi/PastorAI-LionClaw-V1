"""scripts/migrate.py: aplicador simples de migrations do MVP (sem banco real)."""

from __future__ import annotations

import argparse

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
        # Número da transação: muda a cada commit/rollback.
        self.conn.transacoes.append(self.conn.commits + self.conn.rollbacks)
        if sql.startswith("SELECT to_regclass"):
            self._rows = [("public.schema_migrations",)]
        elif sql.startswith("SELECT name FROM"):
            self._rows = [(n,) for n in self.conn.applied]
        elif sql.startswith("INSERT INTO"):
            self.conn.applied.add(params[0])
        elif sql == "SET LOCAL lock_timeout = %s":
            if not self.conn.ignora_set_local:
                self.conn.lock_ms = int(params[0].removesuffix("ms"))
        elif sql == "SHOW lock_timeout":
            self._rows = [(f"{self.conn.lock_ms}ms",)]
        elif self.conn.fail_on and self.conn.fail_on in sql:
            raise RuntimeError("falha simulada")
        elif self.conn.lock_da_migration is not None:
            self.conn.lock_ms = self.conn.lock_da_migration  # SET da própria migration

    def fetchone(self):
        return self._rows[0]

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, applied=(), fail_on=None, ignora_set_local=False, lock_da_migration=None) -> None:
        self.applied = set(applied)
        self.executed: list[str] = []
        self.transacoes: list[int] = []
        self.fail_on = fail_on
        self.commits = self.rollbacks = 0
        self.autocommit = False
        self.lock_ms = 0
        self.ignora_set_local = ignora_set_local
        self.lock_da_migration = lock_da_migration

    def cursor(self):
        return _Cur(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


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


@pytest.mark.parametrize("wrapped", [False, True])
def test_falha_faz_rollback_e_nao_registra(tmp_path, monkeypatch, wrapped) -> None:
    name = "20261020_200000_failure.sql"
    sql = "select migration_failure();\n"
    if wrapped:
        sql = f"begin;\n{sql}commit;\n"
    (tmp_path / name).write_text(sql, encoding="utf-8")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    conn = _Conn(fail_on="select migration_failure();")
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


@pytest.mark.parametrize("name", [
    "20261023_100001_ai_usage_tenant_created_idx.sql",
    "20261028_100001_private_erasure_requests_overview_idx.sql",
    "20261028_100002_private_resume_delivered_overview_idx.sql",
])
def test_cli_no_transaction_separa_timeout_do_indice(monkeypatch, name) -> None:
    conn = _Conn()
    monkeypatch.setattr(migrate, "_connect", lambda: conn)
    assert migrate.main(["apply", name, "--yes", "--no-transaction"]) == 0
    assert conn.autocommit and conn.closed
    timeout, ddl = conn.executed[2:4]
    assert "SET lock_timeout = '2s';" in timeout
    assert "CREATE INDEX" not in timeout
    assert ddl.lstrip().startswith("CREATE INDEX CONCURRENTLY")
    assert conn.executed[4].startswith("INSERT INTO public.schema_migrations")
    assert name in conn.applied


@pytest.mark.parametrize("failure", ["SET lock_timeout", "CREATE INDEX CONCURRENTLY"])
def test_falha_sem_transacao_nao_registra_e_permite_retentativa(failure) -> None:
    name = "20261023_100001_ai_usage_tenant_created_idx.sql"
    conn = _Conn(fail_on=failure)
    with pytest.raises(RuntimeError):
        migrate.cmd_apply(conn, name, transactional=False)
    assert name not in conn.applied
    assert conn.rollbacks == 0
    conn.fail_on = None
    assert migrate.cmd_apply(conn, name, transactional=False) == 0
    assert name in conn.applied


def test_timeout_transacional_permanece_no_mesmo_comando(tmp_path, monkeypatch) -> None:
    name = "20261023_100000_timeout_test.sql"
    sql = "SET LOCAL lock_timeout = '2s';\nCREATE TABLE synthetic (igreja_id uuid);\n"
    (tmp_path / name).write_text(sql, encoding="utf-8")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    conn = _Conn()
    migrate.cmd_apply(conn, name, transactional=True)
    assert conn.autocommit is False
    assert conn.executed[2] == sql


# --lock-timeout ------------------------------------------------------------


def test_lock_timeout_aceita_ms_s_e_zero() -> None:
    assert migrate.lock_timeout_ms("500ms") == 500
    assert migrate.lock_timeout_ms("2s") == 2000
    assert migrate.lock_timeout_ms(" 5s ") == 5000
    assert migrate.lock_timeout_ms("60s") == 60_000
    assert migrate.lock_timeout_ms("0") == 0


@pytest.mark.parametrize("valor", ["", "2", "2m", "1min", "-1s", "01s", "0s", "abc", "61s", "60001ms", "2s;"])
def test_lock_timeout_recusa_valor_invalido(valor) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        migrate.lock_timeout_ms(valor)


def test_apply_fixa_lock_timeout_na_mesma_transacao_da_migration() -> None:
    name = migrate.migration_files()[-1]
    conn = _Conn()
    assert migrate.cmd_apply(conn, name, transactional=True, lock_timeout=2000) == 0
    assert name in conn.applied
    assert conn.rollbacks == 0
    i_set = next(i for i, s in enumerate(conn.executed) if s.startswith("SET LOCAL lock_timeout"))
    i_ins = next(i for i, s in enumerate(conn.executed) if s.startswith("INSERT INTO"))
    # SET LOCAL, conferência, migration, conferência e ledger: nenhum commit no meio
    assert len(set(conn.transacoes[i_set:i_ins + 1])) == 1
    assert i_ins - i_set == 4
    assert conn.commits == 2  # fim da leitura do ledger e fim da migration


def test_apply_sem_lock_timeout_nao_mexe_no_limite() -> None:
    name = migrate.migration_files()[-1]
    conn = _Conn()
    migrate.cmd_apply(conn, name, transactional=True)
    assert not any("lock_timeout" in s for s in conn.executed[:2] + conn.executed[3:])


def test_apply_desfaz_se_o_limite_nao_ficar_ativo() -> None:
    name = migrate.migration_files()[-1]
    sql = (migrate.MIGRATIONS_DIR / name).read_text(encoding="utf-8")
    conn = _Conn(ignora_set_local=True)
    with pytest.raises(RuntimeError, match="não ficou ativo"):
        migrate.cmd_apply(conn, name, transactional=True, lock_timeout=2000)
    assert conn.rollbacks == 1
    assert name not in conn.applied
    assert not any(sql[:40] in s for s in conn.executed)  # a migration nem rodou


def test_apply_desfaz_se_a_migration_afrouxar_o_limite() -> None:
    name = migrate.migration_files()[-1]
    conn = _Conn(lock_da_migration=10_000)
    with pytest.raises(RuntimeError, match="10000ms"):
        migrate.cmd_apply(conn, name, transactional=True, lock_timeout=2000)
    assert conn.rollbacks == 1
    assert name not in conn.applied


def test_apply_desfaz_se_a_migration_desligar_o_limite() -> None:
    name = migrate.migration_files()[-1]
    conn = _Conn(lock_da_migration=0)
    with pytest.raises(RuntimeError, match="0ms"):
        migrate.cmd_apply(conn, name, transactional=True, lock_timeout=2000)
    assert conn.rollbacks == 1
    assert name not in conn.applied


def test_apply_aceita_migration_que_aperta_o_limite() -> None:
    name = migrate.migration_files()[-1]
    conn = _Conn(lock_da_migration=1000)
    assert migrate.cmd_apply(conn, name, transactional=True, lock_timeout=5000) == 0
    assert name in conn.applied


def test_apply_recusa_lock_timeout_fora_de_transacao() -> None:
    name = migrate.migration_files()[-1]
    conn = _Conn()
    with pytest.raises(SystemExit):
        migrate.cmd_apply(conn, name, transactional=False, lock_timeout=2000)
    assert conn.executed == []


@pytest.mark.parametrize(
    ("extra", "transacao", "limite"),
    [
        ([], True, 2000),
        (["--lock-timeout", "5s"], True, 5000),
        (["--lock-timeout", "0"], True, 0),
        (["--no-transaction"], False, 0),
        (["--no-transaction", "--lock-timeout", "0"], False, 0),
    ],
)
def test_cli_padrao_de_2s_e_valores_repassados(monkeypatch, extra, transacao, limite) -> None:
    chamadas: list[dict] = []
    monkeypatch.setattr(migrate, "_connect", _Conn)
    monkeypatch.setattr(migrate, "cmd_apply", lambda conn, name, **kw: chamadas.append(kw) or 0)
    name = migrate.migration_files()[-1]
    assert migrate.main(["apply", name, "--yes", *extra]) == 0
    assert chamadas == [{"transactional": transacao, "lock_timeout": limite}]


@pytest.mark.parametrize("extra", [["--no-transaction", "--lock-timeout", "2s"], ["--lock-timeout", "2m"]])
def test_cli_recusa_antes_de_conectar(monkeypatch, extra) -> None:
    def _nao_conecta():
        raise AssertionError("não devia conectar")

    monkeypatch.setattr(migrate, "_connect", _nao_conecta)
    with pytest.raises(SystemExit):
        migrate.main(["apply", migrate.migration_files()[-1], "--yes", *extra])
