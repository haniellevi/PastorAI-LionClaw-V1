"""Byte-exact PostgreSQL proof for the S3 migration in an explicit disposable DB."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine

from tests.conftest_rls import assert_disposable_database


pytestmark = pytest.mark.rls_integration

_MIGRATION = Path(__file__).parents[1] / "migrations" / (
    "20260927_170000_whatsapp_privilege_actions.sql"
)
_MIGRATION_SHA256 = "d087013e0da83c7d80a1e3df05307861314eaaf2195bcd83149fe8927c2a50cc"
_EXACT_URL_ENV = "S3_MIGRATION_EXACT_DATABASE_URL"


def _exact_database_url() -> str:
    """Require a separately named disposable database before destructive setup."""

    url = os.environ.get(_EXACT_URL_ENV, "").strip()
    if not url:
        pytest.skip(f"{_EXACT_URL_ENV} não definida")
    assert_disposable_database(url)
    parsed = urlsplit(url)
    database_name = parsed.path.rsplit("/", 1)[-1].lower()
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or database_name != "s3_migration_exact_test":
        raise RuntimeError("banco exato S3 não está explicitamente identificado")
    return url


@pytest.fixture
def rls_database_url() -> str:
    """Local guard fixture name keeps the RLS collection contract intact."""

    return _exact_database_url()


@pytest.fixture
def exact_s3_database(rls_database_url: str):
    """Rebuild only the explicitly named disposable public schema baseline."""

    engine = create_engine(rls_database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("drop schema public cascade; create schema public;")
            connection.exec_driver_sql("create extension if not exists pgcrypto;")
            connection.exec_driver_sql(
                "do $$ begin "
                "if not exists (select 1 from pg_roles where rolname = 'authenticated') then "
                "create role authenticated nologin noinherit nobypassrls; end if; "
                "if not exists (select 1 from pg_roles where rolname = 'anon') then "
                "create role anon nologin noinherit nobypassrls; end if; "
                "if not exists (select 1 from pg_roles where rolname = 'agent_runtime') then "
                "create role agent_runtime nologin noinherit nobypassrls; end if; "
                "end $$;"
            )
            connection.exec_driver_sql(
                """
                create table public.igrejas (id uuid primary key, status text not null);
                create table public.pessoas (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  telefone text not null,
                  arquivada_em timestamptz,
                  optout boolean not null default false,
                  sem_interesse boolean not null default false,
                  unique (igreja_id, id)
                );
                create table public.app_users (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  pessoa_id uuid references public.pessoas(id) on delete set null,
                  clerk_user_id text unique,
                  status text,
                  password_changed_at timestamptz,
                  unique (igreja_id, id)
                );
                create table public.user_roles (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  user_id uuid not null references public.app_users(id) on delete cascade,
                  papel text not null,
                  unique (user_id, papel)
                );
                create table public.celulas (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  lider_id uuid references public.pessoas(id) on delete set null,
                  ativo boolean not null default true
                );
                create table public.conversations (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  pessoa_id uuid references public.pessoas(id) on delete set null,
                  telefone text not null,
                  estado text,
                  assumido_por uuid,
                  unique (igreja_id, id)
                );
                create table public.messages (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  conversation_id uuid not null references public.conversations(id) on delete cascade,
                  direcao text not null,
                  autor text not null,
                  agent_reply_state text,
                  texto text,
                  criado_em timestamptz not null default now(),
                  unique (igreja_id, conversation_id, id)
                );
                create table public.agent_configs (
                  id uuid primary key,
                  igreja_id uuid not null unique references public.igrejas(id) on delete cascade,
                  comportamento text not null,
                  ativo boolean not null
                );
                create table public.consent_records (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  pessoa_id uuid not null references public.pessoas(id) on delete cascade,
                  termo_versao text,
                  aceite_em timestamptz
                );
                create function public.current_igreja_id() returns uuid
                  language sql stable as $$
                    select nullif(current_setting('app.tenant_igreja_id', true), '')::uuid
                  $$;
                """
            )
            for table in (
                "pessoas",
                "app_users",
                "user_roles",
                "celulas",
                "conversations",
                "messages",
                "agent_configs",
                "consent_records",
            ):
                connection.exec_driver_sql(f"alter table public.{table} enable row level security")
                connection.exec_driver_sql(
                    f"create policy tenant_isolation on public.{table} for all "
                    "using (igreja_id = public.current_igreja_id()) "
                    "with check (igreja_id = public.current_igreja_id())"
                )
            connection.exec_driver_sql("alter table public.igrejas enable row level security")
            connection.exec_driver_sql(
                "create policy igrejas_self_select on public.igrejas for select "
                "using (id = public.current_igreja_id())"
            )
            connection.exec_driver_sql(
                "grant usage on schema public to authenticated, anon, agent_runtime; "
                "grant select, insert, update, delete on all tables in schema public to authenticated;"
            )
        yield engine
    finally:
        # Roles are cluster-wide. Leave no ACL dependency in this second DB:
        # other disposable tests deliberately recreate agent_runtime.
        with engine.begin() as cleanup:
            cleanup.exec_driver_sql('drop schema public cascade; create schema public;')
        engine.dispose()


def test_s3_migration_applies_exact_bytes_without_schema_rewrite(exact_s3_database) -> None:
    migration_bytes = _MIGRATION.read_bytes()
    assert hashlib.sha256(migration_bytes).hexdigest() == _MIGRATION_SHA256
    migration_sql = migration_bytes.decode("utf-8")
    assert ".replace(" not in migration_sql

    # The migration owns its explicit BEGIN/COMMIT, so do not nest it in an
    # Engine.begin() context that would retain a stale SQLAlchemy transaction.
    with exact_s3_database.connect() as connection:
        before = connection.exec_driver_sql(
            "select count(*) from pg_class where relnamespace = 'public'::regnamespace "
            "and relname in ('agent_identity_challenges', 'agent_identity_proofs', "
            "'agent_action_proposals', 'agent_action_receipts')"
        ).scalar_one()
        assert before == 0
        assert connection.exec_driver_sql(
            "select count(*) from pg_attribute where attrelid = 'public.messages'::regclass "
            "and attname = 'agent_privilege_context' and not attisdropped"
        ).scalar_one() == 0
        connection.commit()
        with connection.connection.cursor() as cursor:
            cursor.execute(migration_sql)

        tables = connection.exec_driver_sql(
            "select relname from pg_class where relnamespace = 'public'::regnamespace "
            "and relname in ('agent_identity_challenges', 'agent_identity_proofs', "
            "'agent_action_proposals', 'agent_action_receipts') order by relname"
        ).scalars().all()
        assert tables == [
            "agent_action_proposals",
            "agent_action_receipts",
            "agent_identity_challenges",
            "agent_identity_proofs",
        ]
        assert connection.exec_driver_sql(
            "select count(*) from pg_attribute where attrelid = 'public.messages'::regclass "
            "and attname = 'agent_privilege_context' and not attisdropped"
        ).scalar_one() == 1
        for table in tables:
            assert connection.exec_driver_sql(
                "select relrowsecurity and relforcerowsecurity from pg_class "
                "where oid = %s::regclass",
                (f"public.{table}",),
            ).scalar_one() is True
        assert connection.exec_driver_sql(
            "select count(*) from pg_policy where polrelid = 'public.messages'::regclass "
            "and polname = 'tenant_isolation' and polcmd = '*'"
        ).scalar_one() == 1
