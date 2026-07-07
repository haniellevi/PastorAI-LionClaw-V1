"""Fixtures opt-in da suite de integracao RLS (PR1 — estritamente aditivo).

Esta suite so faz sentido contra um Postgres REAL: a RLS do PastorAI depende de
policies + do papel `authenticated` (NOBYPASSRLS) e nao pode ser exercitada com
SQLite/PGLite/FakeSession. Por isso ela e opt-in via `RLS_TEST_DATABASE_URL`:

  * Sem a env var  -> `pytest.skip` LIMPO (dev/CI offline seguem verdes).
  * Com a env var  -> um guard OBRIGATORIO (D5.1) ABORTA a suite (fail, NAO skip)
    se a URL aparentar apontar para DEV/PROD (denylist dos projetos reais do
    SPEC). E melhor falhar barulhento do que rodar DDL/seed contra producao.

O modulo tem nome `conftest_rls.py` (e NAO `conftest.py`) de proposito: assim
ele NAO e auto-carregado pelo pytest para a suite inteira; os testes de RLS o
importam explicitamente (`from tests.conftest_rls import ...`).

Este arquivo NAO toca nenhum runtime de producao (deps.py/session.py/routers/
workers). Ele apenas provisiona, num Postgres DESCARTAVEL, o minimo necessario
para provar a invariante: o papel `authenticated`, a funcao current_igreja_id(),
tabelas tenant-scoped e 2 igrejas (A, B) com uma linha cada.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

# UUIDs fixos das duas igrejas de teste (A e B). Valores estaveis para asserts.
IGREJA_A = "0a0a0a0a-0000-0000-0000-00000000000a"
IGREJA_B = "0b0b0b0b-0000-0000-0000-00000000000b"

# Subjects Clerk fixos, mapeados 1:1 a cada igreja via app_users (seed). O
# caminho HTTP (set_tenant_context) deriva o tenant deste `sub`.
CLERK_A = "clerk-user-a"
CLERK_B = "clerk-user-b"


# ---------------------------------------------------------------------------
# Guard de producao (OBRIGATORIO — D5.1)
# ---------------------------------------------------------------------------
class RlsProductionGuardError(RuntimeError):
    """RLS_TEST_DATABASE_URL aparenta apontar para DEV/PROD.

    Erro de SEGURANCA: a suite provisiona role/tabelas/seed e roda DDL. Deixar
    isso mirar um banco real seria destrutivo. Levantamos (nao skip) para
    ABORTAR a suite bem alto.
    """


# Denylist explicita: identificadores de projeto reais do SPEC + substrings que
# so aparecem em bancos gerenciados/producao. Um Postgres descartavel (localhost,
# container efemero do CI) nao casa com nenhum destes.
_PROD_DENYLIST: tuple[str, ...] = (
    "pffafnchtxbimpwyaczq",  # projeto PROD (Supabase) — SPEC
    "cxmjojnocigekgcxhubi",  # projeto DEV (Supabase) — SPEC
    "supabase.co",  # qualquer host Supabase gerenciado (DEV/PROD)
    "prod",  # nome/host sugerindo producao
)


def assert_disposable_database(url: str) -> None:
    """Aborta (raise) se a URL aparentar DEV/PROD. Nao retorna nada se OK.

    Usado tanto pelas fixtures quanto pelo passo de guard do CI (feat-005), para
    que a denylist viva num unico lugar.
    """
    lowered = url.lower()
    for needle in _PROD_DENYLIST:
        if needle in lowered:
            raise RlsProductionGuardError(
                "RLS_TEST_DATABASE_URL parece apontar para DEV/PROD "
                f"(contem {needle!r}). Use um Postgres DESCARTAVEL/efemero — "
                "NUNCA DEV/PROD. Abortando a suite por seguranca (D5.1)."
            )


# ---------------------------------------------------------------------------
# DDL minima do banco descartavel
# ---------------------------------------------------------------------------
# Provisiona SOMENTE o que os testes exercitam: role `authenticated`
# NOBYPASSRLS, a funcao current_igreja_id() (replica fiel da migration
# 20260624_090102, honrando o GUC app.tenant_igreja_id), tabelas tenant-scoped
# (igrejas/app_users/pessoas), policies RLS no padrao 0003, grants ao tenant e o
# seed das 2 igrejas A/B com uma pessoa cada. Idempotente (if not exists /
# create or replace / on conflict). UUIDs sao constantes do modulo (sem injecao).
_SCHEMA_SQL = f"""
-- Papel de tenant: NOBYPASSRLS, exatamente como o `authenticated` do Supabase.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin noinherit nobypassrls;
  end if;
end $$;

create table if not exists igrejas (
  id   uuid primary key,
  nome text not null
);

create table if not exists app_users (
  id            uuid primary key default gen_random_uuid(),
  igreja_id     uuid not null references igrejas(id) on delete cascade,
  clerk_user_id text unique
);

create table if not exists pessoas (
  id        uuid primary key default gen_random_uuid(),
  igreja_id uuid not null references igrejas(id) on delete cascade,
  nome      text not null
);

-- Replica fiel de current_igreja_id() (migration 20260624_090102): 1) GUC do
-- worker/async; senao 2) app_user do claim `sub`. SECURITY DEFINER para ler
-- app_users ignorando a propria RLS (evita recursao nas policies).
create or replace function current_igreja_id()
returns uuid
language sql
stable
security definer
set search_path = public, pg_temp
as $fn$
  select coalesce(
    nullif(current_setting('app.tenant_igreja_id', true), '')::uuid,
    (
      select au.igreja_id
      from public.app_users au
      where au.clerk_user_id = nullif(
        coalesce(
          nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
          current_setting('request.jwt.claim.sub', true)
        ),
        ''
      )
      limit 1
    )
  );
$fn$;

-- RLS tenant-scoped (padrao 0003) em pessoas.
alter table pessoas enable row level security;
drop policy if exists tenant_isolation on pessoas;
create policy tenant_isolation on pessoas
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

-- igrejas: cada tenant so enxerga o proprio registro.
alter table igrejas enable row level security;
drop policy if exists igrejas_self_select on igrejas;
create policy igrejas_self_select on igrejas
  for select
  using (id = current_igreja_id());

-- Grants ao papel de tenant (o owner/conexao segue com BYPASSRLS para o seed).
grant usage on schema public to authenticated;
grant select, insert, update, delete on pessoas to authenticated;
grant select on igrejas to authenticated;
grant select on app_users to authenticated;

-- Seed: 2 igrejas + 1 pessoa cada. Roda como owner (BYPASSRLS), fora da RLS.
insert into igrejas (id, nome) values
  ('{IGREJA_A}', 'Igreja A'),
  ('{IGREJA_B}', 'Igreja B')
on conflict (id) do nothing;

insert into pessoas (igreja_id, nome)
select '{IGREJA_A}', 'Pessoa A1'
where not exists (select 1 from pessoas where igreja_id = '{IGREJA_A}');

insert into pessoas (igreja_id, nome)
select '{IGREJA_B}', 'Pessoa B1'
where not exists (select 1 from pessoas where igreja_id = '{IGREJA_B}');

-- app_users por igreja: o caminho HTTP (set_tenant_context) resolve o tenant via
-- current_igreja_id() a partir do clerk_user_id do claim. Necessário para provar
-- o seam no caminho HTTP (claim Clerk) coexistindo com o GUC do seam (PR2).
insert into app_users (igreja_id, clerk_user_id) values
  ('{IGREJA_A}', '{CLERK_A}'),
  ('{IGREJA_B}', '{CLERK_B}')
on conflict (clerk_user_id) do nothing;
"""


def _provision_schema(engine: Engine) -> None:
    """Aplica a DDL minima + seed no banco descartavel (idempotente)."""
    with engine.begin() as conn:
        # exec_driver_sql envia o script inteiro ao psycopg2, que executa os
        # statements em sequencia (incluindo DO blocks e o corpo da funcao).
        conn.exec_driver_sql(_SCHEMA_SQL)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def rls_database_url() -> str:
    """URL do Postgres descartavel, ou skip LIMPO se ausente.

    Guard de producao aplicado ANTES de qualquer conexao/DDL.
    """
    url = os.environ.get("RLS_TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip(
            "RLS_TEST_DATABASE_URL nao definida — suite de integracao RLS "
            "pulada (dev/CI offline seguem verdes). Defina-a apontando para um "
            "Postgres DESCARTAVEL para exercitar T1-T6."
        )
    assert_disposable_database(url)
    return url


@pytest.fixture(scope="session")
def rls_engine(rls_database_url: str) -> Iterator[Engine]:
    """Engine SQLAlchemy contra o Postgres descartavel."""
    engine = create_engine(rls_database_url, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def rls_seeded(rls_engine: Engine) -> dict[str, str]:
    """Garante schema + seed aplicados uma vez; retorna os ids das igrejas."""
    _provision_schema(rls_engine)
    return {"A": IGREJA_A, "B": IGREJA_B}
