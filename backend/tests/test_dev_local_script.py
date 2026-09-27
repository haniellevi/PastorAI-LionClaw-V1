"""scripts/dev_local.py: o banco local de desenvolvimento só roda no Supabase local."""

from __future__ import annotations

import datetime as dt

import pytest

from app.domain.phone import normalize_phone
from scripts import dev_local

LOCAL = "postgresql://postgres:postgres@supabase_db_pastorai-local:5432/postgres"


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "development")


@pytest.mark.parametrize(
    "url",
    [
        LOCAL,
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:54322/postgres",
        "postgresql://postgres:postgres@localhost:54322/postgres",
    ],
)
def test_aceita_supabase_local(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    assert dev_local.local_database_url() == url


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
