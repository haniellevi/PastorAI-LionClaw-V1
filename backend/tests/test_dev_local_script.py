"""scripts/dev_local.py: o banco local de desenvolvimento só roda no Supabase local."""

from __future__ import annotations

import datetime as dt
import json
import sys
import types
from pathlib import Path

import pytest

from app.domain.phone import normalize_phone
from scripts import dev_local

LOCAL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LOCAL_DATABASE_IDENTITY_RECEIPT", raising=False)
    for name in ("PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "development")


@pytest.mark.parametrize(
    "url",
    [
        LOCAL,
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:54322/postgres",
    ],
)
def test_aceita_supabase_local(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    assert dev_local.local_database_url() == url


@pytest.mark.parametrize(
    "url",
    [
        "mysql://postgres:postgres@127.0.0.1:54322/postgres",
        "postgresql://postgres:postgres@localhost:54322/postgres",
        "postgresql://postgres:postgres@127.0.0.1:5432/postgres",
        "postgresql://postgres:postgres@127.0.0.1:54322/other_database",
        "postgresql://postgres:postgres@127.0.0.1:54322/postgres?host=other-host",
    ],
)
def test_recusa_url_fora_do_endpoint_local_canonico(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", url)

    with pytest.raises(SystemExit, match="Supabase local"):
        dev_local.local_database_url()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres.ref:x@aws-0-us-west-2.pooler.supabase.com:6543/postgres",
        "postgresql://postgres:x@db.ref.supabase.co:5432/postgres",
        "postgresql://postgres:x@10.0.0.5:5432/postgres",
    ],
)
def test_recusa_banco_que_nao_e_local(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(SystemExit):
        dev_local.local_database_url()


def test_recusa_sem_url() -> None:
    with pytest.raises(SystemExit):
        dev_local.local_database_url()


def test_recusa_app_env_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", LOCAL)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(SystemExit):
        dev_local.local_database_url()


@pytest.mark.parametrize(
    "name",
    ["PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"],
)
def test_recusa_redirecionamento_libpq_antes_de_conectar(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", LOCAL)
    monkeypatch.setenv(name, "synthetic-remote.invalid")
    module = types.ModuleType("psycopg2")
    module.connect = lambda _url: pytest.fail("não deve abrir conexão")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psycopg2", module)

    with pytest.raises(SystemExit, match="libpq"):
        dev_local.cmd_migrate()


class _Cursor:
    def __init__(self, connection: "_Connection") -> None:
        self.connection = connection
        self.statement = ""

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.statement = statement
        self.connection.statements.append(statement)

    def fetchone(self) -> tuple[object, ...]:
        if "system_identifier" in self.statement:
            return (self.connection.system_identifier,)
        if "to_regclass" in self.statement:
            return (True,)
        raise AssertionError(f"consulta inesperada: {self.statement}")


class _Connection:
    def __init__(self, system_identifier: str) -> None:
        self.system_identifier = system_identifier
        self.statements: list[str] = []
        self.autocommit = False
        self.closed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def close(self) -> None:
        self.closed = True


def _recibo_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, system_identifier: str
) -> None:
    receipt = tmp_path / ".dev" / "local-db-identity.json"
    receipt.parent.mkdir()
    receipt.write_text(
        json.dumps(
            {
                "schema": "pastorai-local-db-identity-v1",
                "host": "127.0.0.1",
                "port": 54322,
                "database": "postgres",
                "system_identifier": system_identifier,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dev_local, "_BACKEND_ROOT", tmp_path / "backend")


def _psycopg2_sintetico(
    monkeypatch: pytest.MonkeyPatch, connections: list[_Connection]
) -> None:
    def connect(_url: str) -> _Connection:
        return connections.pop(0)

    module = types.ModuleType("psycopg2")
    module.connect = connect  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psycopg2", module)


def test_migrate_recusa_tunel_loopback_com_instancia_errada_antes_de_ddl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts import migrate

    _recibo_local(monkeypatch, tmp_path, "111")
    connection = _Connection("999")
    _psycopg2_sintetico(monkeypatch, [connection])
    monkeypatch.setenv("DATABASE_URL", LOCAL)
    monkeypatch.setattr(migrate, "_applied", lambda _cursor: [])
    monkeypatch.setattr(migrate, "pending", lambda *_args: [])

    with pytest.raises(SystemExit, match="instância local"):
        dev_local.cmd_migrate()

    assert not any(
        statement.lstrip().upper().startswith(("ALTER", "CREATE", "DELETE", "INSERT", "UPDATE"))
        for statement in connection.statements
    )


def test_migrate_recusa_endpoint_canonico_sem_recibo_antes_de_ddl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts import migrate

    connection = _Connection("111")
    _psycopg2_sintetico(monkeypatch, [connection])
    monkeypatch.setenv("DATABASE_URL", LOCAL)
    monkeypatch.setattr(dev_local, "_BACKEND_ROOT", tmp_path / "backend")
    monkeypatch.setattr(migrate, "_applied", lambda _cursor: [])
    monkeypatch.setattr(migrate, "pending", lambda *_args: [])

    with pytest.raises(SystemExit, match="recibo"):
        dev_local.cmd_migrate()

    assert connection.statements == []


def test_migrate_recusa_recibo_indicado_somente_por_env_antes_de_ddl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts import migrate

    forged_receipt = tmp_path / "forged-receipt.json"
    forged_receipt.write_text(
        json.dumps(
            {
                "schema": "pastorai-local-db-identity-v1",
                "host": "127.0.0.1",
                "port": 54322,
                "database": "postgres",
                "system_identifier": "111",
            }
        ),
        encoding="utf-8",
    )
    connection = _Connection("111")
    _psycopg2_sintetico(monkeypatch, [connection])
    monkeypatch.setenv("DATABASE_URL", LOCAL)
    monkeypatch.setenv("LOCAL_DATABASE_IDENTITY_RECEIPT", str(forged_receipt))
    monkeypatch.setattr(dev_local, "_BACKEND_ROOT", tmp_path / "backend")
    monkeypatch.setattr(migrate, "_applied", lambda _cursor: [])
    monkeypatch.setattr(migrate, "pending", lambda *_args: [])

    with pytest.raises(SystemExit, match="recibo"):
        dev_local.cmd_migrate()

    assert connection.statements == []


def test_migrate_confere_recibo_em_cada_conexao_antes_de_aplicar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts import migrate

    _recibo_local(monkeypatch, tmp_path, "111")
    first_connection = _Connection("111")
    second_connection = _Connection("999")
    _psycopg2_sintetico(monkeypatch, [first_connection, second_connection])
    monkeypatch.setenv("DATABASE_URL", LOCAL)
    (tmp_path / "fixture.sql").write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    monkeypatch.setattr(migrate, "_applied", lambda _cursor: [])
    monkeypatch.setattr(migrate, "pending", lambda *_args: ["fixture.sql"])
    applied: list[str] = []
    monkeypatch.setattr(
        migrate,
        "cmd_apply",
        lambda _connection, name, **_kwargs: applied.append(name),
    )

    with pytest.raises(SystemExit, match="instância local"):
        dev_local.cmd_migrate()

    assert applied == []
    assert second_connection.statements == [
        "SELECT system_identifier FROM pg_control_system()"
    ]


def test_migrate_aceita_recibo_da_mesma_instancia_em_todas_as_conexoes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts import migrate

    _recibo_local(monkeypatch, tmp_path, "111")
    _psycopg2_sintetico(monkeypatch, [_Connection("111"), _Connection("111")])
    monkeypatch.setenv("DATABASE_URL", LOCAL)
    (tmp_path / "fixture.sql").write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    monkeypatch.setattr(migrate, "_applied", lambda _cursor: [])
    monkeypatch.setattr(migrate, "pending", lambda *_args: ["fixture.sql"])
    applied: list[str] = []
    monkeypatch.setattr(
        migrate,
        "cmd_apply",
        lambda _connection, name, **_kwargs: applied.append(name),
    )

    assert dev_local.cmd_migrate() == 0
    assert applied == ["fixture.sql"]


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value

    def scalar_one(self) -> object:
        return self.value


class _SessionConnection:
    def __init__(self, system_identifier: str) -> None:
        self.system_identifier = system_identifier
        self.statements: list[str] = []

    def exec_driver_sql(self, statement: str) -> _ScalarResult:
        self.statements.append(statement)
        return _ScalarResult(self.system_identifier)


class _SeedSession:
    def __init__(self, _engine: object, connection: _SessionConnection) -> None:
        self.connection_to_write = connection

    def __enter__(self) -> "_SeedSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def connection(self) -> _SessionConnection:
        return self.connection_to_write

    def execute(self, _statement: object) -> _ScalarResult:
        return _ScalarResult(None)

    def commit(self) -> None:
        return None


class _SeedEngine:
    def dispose(self) -> None:
        return None


def test_seed_usa_url_validada_e_recusa_instancia_errada_antes_de_dml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sqlalchemy
    import sqlalchemy.orm
    from app.db import session as db_session

    _recibo_local(monkeypatch, tmp_path, "111")
    monkeypatch.setenv("DATABASE_URL", LOCAL)
    connection = _SessionConnection("999")
    engine = _SeedEngine()
    captured_urls: list[str] = []
    writes: list[str] = []

    def create_engine(url: str) -> _SeedEngine:
        captured_urls.append(url)
        return engine

    monkeypatch.setattr(sqlalchemy, "create_engine", create_engine)
    monkeypatch.setattr(
        sqlalchemy.orm,
        "Session",
        lambda bound_engine: _SeedSession(bound_engine, connection),
    )
    monkeypatch.setattr(db_session, "get_engine", lambda: object())
    monkeypatch.setattr(
        dev_local,
        "_criar_dados",
        lambda *_args: writes.append("insert"),
    )
    monkeypatch.setattr(dev_local, "_ligar_contas_de_teste", lambda _db: [])
    monkeypatch.setattr(dev_local, "_resumo", lambda _db: [])

    with pytest.raises(SystemExit, match="instância local"):
        dev_local.cmd_seed()

    assert captured_urls == [LOCAL]
    assert connection.statements == [
        "SELECT system_identifier FROM pg_control_system()"
    ]
    assert writes == []


def test_telefone_ficticio_usa_ddd_inexistente() -> None:
    telefone = dev_local.fone(60)
    assert telefone.startswith("55")
    assert normalize_phone(telefone) == "00900000060"


def test_ids_do_seed_sao_estaveis() -> None:
    assert dev_local._id("pessoa:ana") == dev_local._id("pessoa:ana")
    assert dev_local._id("pessoa:ana") != dev_local._id("pessoa:carla")


def test_reuniao_passada_cai_no_dia_da_celula() -> None:
    quarta = dt.date(2026, 9, 30)
    assert dev_local._ultima(quarta, 2, 1) == dt.date(2026, 9, 23)
    assert dev_local._ultima(quarta, 5, 1) == dt.date(2026, 9, 26)
    assert dev_local._ultima(quarta, 5, 3) == dt.date(2026, 9, 12)
    assert dev_local._proxima(quarta, 2) == dt.date(2026, 10, 7)
