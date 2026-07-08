"""Teste do guard de producao (PR1). Unit puro — roda SEMPRE (sem DB).

Prova que uma RLS_TEST_DATABASE_URL apontando para DEV/PROD faz a suite FALHAR
(raise), nao skip: `assert_disposable_database` levanta RlsProductionGuardError.
Este teste NAO e marcado `rls_integration`, entao roda mesmo offline, garantindo
que o guard seja sempre exercitado.
"""

from __future__ import annotations

import pytest

from tests.conftest_rls import (
    RlsProductionGuardError,
    assert_disposable_database,
)


@pytest.mark.parametrize(
    "prod_like_url",
    [
        # Projeto PROD real (SPEC).
        "postgresql://u:p@db.pffafnchtxbimpwyaczq.supabase.co:5432/postgres",
        # Projeto DEV real (SPEC).
        "postgresql://u:p@db.cxmjojnocigekgcxhubi.supabase.co:5432/postgres",
        # Qualquer host Supabase gerenciado.
        "postgresql://u:p@qualquer.supabase.co:5432/db",
        # Nome sugerindo producao.
        "postgresql://u:p@my-prod-db:5432/app",
    ],
)
def test_guard_aborts_on_dev_or_prod_url(prod_like_url: str) -> None:
    # Levanta (nao skip): a suite ABORTA se mirar DEV/PROD.
    with pytest.raises(RlsProductionGuardError):
        assert_disposable_database(prod_like_url)


@pytest.mark.parametrize(
    "disposable_url",
    [
        "postgresql+psycopg2://postgres:postgres@localhost:5432/rls_disposable",
        "postgresql://postgres:postgres@127.0.0.1:5432/pastorai_rls_test",
    ],
)
def test_guard_allows_disposable_url(disposable_url: str) -> None:
    # Nao levanta para um Postgres descartavel/efemero.
    assert_disposable_database(disposable_url)
