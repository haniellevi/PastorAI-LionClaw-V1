"""Cortesia nunca pode virar alvo do auto-upgrade de billing.

Os testes estáticos ficam sempre ativos. O teste marcado executa a migration
forward-only REAL, duas vezes, em um schema isolado de PostgreSQL descartável;
o guard compartilhado impede qualquer URL DEV/PROD.
"""

from __future__ import annotations

import pathlib
import threading
import time

import pytest
from sqlalchemy.engine import Engine

from tests.conftest_rls import rls_database_url, rls_engine  # noqa: F401

_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade.sql"
)
_HISTORICAL = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260808_001059_billing_count_active_members.sql"
)
_SCHEMA = "billing_complimentary_migration"

_DDL = f"""
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin;
  end if;
end $$;

drop schema if exists {_SCHEMA} cascade;
create schema {_SCHEMA};

create table {_SCHEMA}.igrejas (
  id uuid primary key,
  plano text
);

create table {_SCHEMA}.planos (
  codigo text primary key,
  ativo boolean not null,
  preco_mensal numeric(10,2) not null,
  limite_pessoas integer
);

create table {_SCHEMA}.subscriptions (
  id uuid primary key,
  igreja_id uuid not null unique,
  plano text not null,
  pessoas integer,
  limite integer,
  asaas_subscription_id text
);

create table {_SCHEMA}.pessoas (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  arquivada_em timestamptz,
  sem_interesse boolean not null default false,
  tipo text
);

create table {_SCHEMA}.billing_plan_change_operations (
  id uuid primary key default gen_random_uuid(),
  subscription_id uuid not null,
  asaas_subscription_id text not null,
  from_plano text not null,
  to_plano text not null,
  to_preco numeric(10,2) not null,
  to_limite integer,
  to_descricao text,
  origin text not null default 'manual',
  status text not null default 'prepared',
  notify_status text not null default 'skipped',
  error text,
  attempt_started_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index billing_plan_change_operations_open_uq
  on {_SCHEMA}.billing_plan_change_operations (subscription_id)
  where status in ('prepared','processing','reconciling');

create function {_SCHEMA}.fn_subscription_autoupgrade()
returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then return old; else return new; end if;
end;
$$;

create trigger trg_subscription_autoupgrade
after insert or update or delete on {_SCHEMA}.pessoas
for each row execute function {_SCHEMA}.fn_subscription_autoupgrade();
"""


def _sql() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def _schema_sql() -> str:
    return _sql().replace("public.", f"{_SCHEMA}.").replace(
        "set search_path = public, pg_temp",
        f"set search_path = {_SCHEMA}, pg_temp",
    )


def _apply_real_migration(engine: Engine) -> None:
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute(_schema_sql())
            raw.commit()
        finally:
            cursor.close()
    finally:
        raw.close()


def test_forward_migration_is_reviewable_and_does_not_replace_history() -> None:
    sql = " ".join(_sql().lower().split())
    historical = " ".join(_HISTORICAL.read_text(encoding="utf-8").lower().split())

    assert "create or replace function public.fn_subscription_autoupgrade()" in sql
    assert "p.preco_mensal > 0" in sql
    assert "for update of p" in sql
    assert "o.origin = 'autoupgrade'" in sql
    assert "o.status = 'prepared'" in sql
    assert "status in ('processing','reconciling')" not in sql
    assert "preco_mensal > 0" not in historical


@pytest.mark.rls_integration
def test_real_migration_is_idempotent_and_never_selects_zero_plan(
    rls_engine: Engine,
) -> None:
    with rls_engine.begin() as conn:
        conn.exec_driver_sql(_DDL)
        conn.exec_driver_sql(
            f"""
            insert into {_SCHEMA}.planos
              (codigo, ativo, preco_mensal, limite_pessoas)
            values
              ('ate_100', true, 199, 100),
              ('101_200', true, 0, 200),
              ('acima_201', true, 399, null),
              ('piloto', true, 0, 50);

            insert into {_SCHEMA}.igrejas (id, plano)
            values ('10000000-0000-0000-0000-000000000001', 'ate_100');
            insert into {_SCHEMA}.subscriptions
              (id, igreja_id, plano, pessoas, limite, asaas_subscription_id)
            values (
              '20000000-0000-0000-0000-000000000001',
              '10000000-0000-0000-0000-000000000001',
              'ate_100', 150, 100, 'asaas-existing'
            );
            insert into {_SCHEMA}.pessoas
              (igreja_id, tipo)
            select '10000000-0000-0000-0000-000000000001', 'membro'
              from generate_series(1, 150);
            insert into {_SCHEMA}.billing_plan_change_operations
              (subscription_id, asaas_subscription_id, from_plano, to_plano,
               to_preco, to_limite, to_descricao, origin, status, notify_status)
            values (
              '20000000-0000-0000-0000-000000000001', 'asaas-existing',
              'ate_100', '101_200', 0, 200, 'alvo antigo',
              'autoupgrade', 'prepared', 'pending'
            );

            -- Regressão: a Igreja já recebeu cortesia, mas a Subscription
            -- histórica ainda aponta para o tier pago anterior.
            insert into {_SCHEMA}.igrejas (id, plano)
            values ('10000000-0000-0000-0000-000000000005', 'piloto');
            insert into {_SCHEMA}.subscriptions
              (id, igreja_id, plano, pessoas, limite, asaas_subscription_id)
            values (
              '20000000-0000-0000-0000-000000000005',
              '10000000-0000-0000-0000-000000000005',
              'ate_100', 100, 100, null
            );
            insert into {_SCHEMA}.pessoas (igreja_id, tipo)
            select '10000000-0000-0000-0000-000000000005', 'membro'
              from generate_series(1, 100);
            """
        )

    try:
        _apply_real_migration(rls_engine)
        _apply_real_migration(rls_engine)

        with rls_engine.begin() as conn:
            conn.exec_driver_sql(
                f"""
                insert into {_SCHEMA}.pessoas (igreja_id, tipo)
                values ('10000000-0000-0000-0000-000000000005', 'membro')
                """
            )
            complimentary_state = conn.exec_driver_sql(
                f"""
                select i.plano, s.plano, s.limite, s.pessoas
                  from {_SCHEMA}.igrejas i
                  join {_SCHEMA}.subscriptions s on s.igreja_id = i.id
                 where i.id = '10000000-0000-0000-0000-000000000005'
                """
            ).one()
            assert complimentary_state == ("piloto", "piloto", 50, 101)
            complimentary_ops = conn.exec_driver_sql(
                f"""
                select count(*)
                  from {_SCHEMA}.billing_plan_change_operations
                 where subscription_id =
                       '20000000-0000-0000-0000-000000000005'
                """
            ).scalar_one()
            assert complimentary_ops == 0

            old_status = conn.exec_driver_sql(
                f"""
                select status from {_SCHEMA}.billing_plan_change_operations
                 where to_plano = '101_200'
                """
            ).scalar_one()
            replacement = conn.exec_driver_sql(
                f"""
                select to_plano, to_preco
                  from {_SCHEMA}.billing_plan_change_operations
                 where status = 'prepared'
                """
            ).one()
            assert old_status == "failed"
            assert replacement == ("acima_201", 399)

            # Trigger real: assinatura local muda de plano, mas nunca para o
            # degrau intermediário de preço zero.
            conn.exec_driver_sql(
                f"""
                insert into {_SCHEMA}.igrejas (id, plano)
                values ('10000000-0000-0000-0000-000000000002', 'ate_100');
                insert into {_SCHEMA}.subscriptions
                  (id, igreja_id, plano, pessoas, limite, asaas_subscription_id)
                values (
                  '20000000-0000-0000-0000-000000000002',
                  '10000000-0000-0000-0000-000000000002',
                  'ate_100', 0, 100, null
                );
                insert into {_SCHEMA}.pessoas (igreja_id, tipo)
                select '10000000-0000-0000-0000-000000000002', 'membro'
                  from generate_series(1, 101);
                """
            )
            local_plan = conn.exec_driver_sql(
                f"""
                select plano from {_SCHEMA}.subscriptions
                 where id = '20000000-0000-0000-0000-000000000002'
                """
            ).scalar_one()
            assert local_plan == "acima_201"

            # Fluxo remoto: cria uma única intenção paga; zero nunca aparece.
            conn.exec_driver_sql(
                f"""
                insert into {_SCHEMA}.igrejas (id, plano)
                values ('10000000-0000-0000-0000-000000000003', 'ate_100');
                insert into {_SCHEMA}.subscriptions
                  (id, igreja_id, plano, pessoas, limite, asaas_subscription_id)
                values (
                  '20000000-0000-0000-0000-000000000003',
                  '10000000-0000-0000-0000-000000000003',
                  'ate_100', 0, 100, 'asaas-fresh'
                );
                insert into {_SCHEMA}.pessoas (igreja_id, tipo)
                select '10000000-0000-0000-0000-000000000003', 'membro'
                  from generate_series(1, 101);
                """
            )
            fresh_targets = conn.exec_driver_sql(
                f"""
                select to_plano, to_preco
                  from {_SCHEMA}.billing_plan_change_operations
                 where subscription_id =
                       '20000000-0000-0000-0000-000000000003'
                """
            ).all()
            assert fresh_targets == [("acima_201", 399)]
            zero_targets = conn.exec_driver_sql(
                f"""
                select count(*)
                  from {_SCHEMA}.billing_plan_change_operations
                 where to_preco <= 0 or to_plano = '101_200'
                """
            ).scalar_one()
            assert zero_targets == 1  # somente a intenção histórica já fechada

            # Sem próximo plano pago, nada local/remoto é inventado.
            conn.exec_driver_sql(
                f"""
                update {_SCHEMA}.planos set preco_mensal = 0
                 where codigo = 'acima_201';
                insert into {_SCHEMA}.igrejas (id, plano)
                values ('10000000-0000-0000-0000-000000000004', 'ate_100');
                insert into {_SCHEMA}.subscriptions
                  (id, igreja_id, plano, pessoas, limite, asaas_subscription_id)
                values (
                  '20000000-0000-0000-0000-000000000004',
                  '10000000-0000-0000-0000-000000000004',
                  'ate_100', 0, 100, 'asaas-no-paid-target'
                );
                insert into {_SCHEMA}.pessoas (igreja_id, tipo)
                select '10000000-0000-0000-0000-000000000004', 'membro'
                  from generate_series(1, 101);
                """
            )
            no_target_count = conn.exec_driver_sql(
                f"""
                select count(*)
                  from {_SCHEMA}.billing_plan_change_operations
                 where subscription_id =
                       '20000000-0000-0000-0000-000000000004'
                """
            ).scalar_one()
            assert no_target_count == 0
    finally:
        with rls_engine.begin() as conn:
            conn.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade;")


@pytest.mark.rls_integration
def test_trigger_and_master_use_church_before_plan_lock_order(
    rls_engine: Engine,
) -> None:
    """O insert espera a Igreja antes de tocar o plano-alvo, sem deadlock."""
    igreja_id = "10000000-0000-0000-0000-000000000010"
    sub_id = "20000000-0000-0000-0000-000000000010"
    worker_started = threading.Event()
    worker_errors: list[BaseException] = []

    with rls_engine.begin() as conn:
        conn.exec_driver_sql(_DDL)
        conn.exec_driver_sql(
            f"""
            insert into {_SCHEMA}.planos
              (codigo, ativo, preco_mensal, limite_pessoas)
            values
              ('ate_100', true, 199, 100),
              ('101_200', true, 299, 200),
              ('acima_201', true, 399, null);
            insert into {_SCHEMA}.igrejas (id, plano)
            values ('{igreja_id}', 'ate_100');
            insert into {_SCHEMA}.subscriptions
              (id, igreja_id, plano, pessoas, limite, asaas_subscription_id)
            values ('{sub_id}', '{igreja_id}', 'ate_100', 100, 100, null);
            insert into {_SCHEMA}.pessoas (igreja_id, tipo)
            select '{igreja_id}', 'membro' from generate_series(1, 100);
            """
        )

    try:
        _apply_real_migration(rls_engine)

        def add_101st_member() -> None:
            try:
                with rls_engine.begin() as conn:
                    conn.exec_driver_sql(
                        "set local application_name = "
                        "'billing-autoupgrade-lock-order'"
                    )
                    worker_started.set()
                    conn.exec_driver_sql(
                        f"""
                        insert into {_SCHEMA}.pessoas (igreja_id, tipo)
                        values ('{igreja_id}', 'membro')
                        """
                    )
            except BaseException as exc:  # noqa: BLE001 - transporta da thread
                worker_errors.append(exc)

        master = rls_engine.connect()
        master_tx = master.begin()
        worker = threading.Thread(target=add_101st_member)
        try:
            master.exec_driver_sql(
                f"select 1 from {_SCHEMA}.igrejas "
                f"where id = '{igreja_id}' for update"
            )
            worker.start()
            assert worker_started.wait(timeout=5)

            deadline = time.monotonic() + 5
            blocked_on_lock = False
            while time.monotonic() < deadline:
                with rls_engine.connect() as observer:
                    wait_type = observer.exec_driver_sql(
                        "select wait_event_type from pg_stat_activity "
                        "where application_name = "
                        "'billing-autoupgrade-lock-order' "
                        "and pid <> pg_backend_pid()"
                    ).scalar_one_or_none()
                if wait_type == "Lock":
                    blocked_on_lock = True
                    break
                time.sleep(0.05)
            assert blocked_on_lock, "trigger não aguardou o lock da Igreja"

            # Na implementação antiga, o trigger já segurava este Plano e a
            # linha abaixo formava o ciclo Plano -> Igreja. Agora ela conclui.
            master.exec_driver_sql(
                f"select 1 from {_SCHEMA}.planos "
                "where codigo = '101_200' for update"
            )
            master_tx.commit()
        finally:
            if master_tx.is_active:
                master_tx.rollback()
            master.close()
            worker.join(timeout=10)

        assert not worker.is_alive(), "trigger ficou preso após liberar a Igreja"
        assert worker_errors == []
        with rls_engine.begin() as conn:
            state = conn.exec_driver_sql(
                f"""
                select i.plano, s.plano, s.pessoas
                  from {_SCHEMA}.igrejas i
                  join {_SCHEMA}.subscriptions s on s.igreja_id = i.id
                 where i.id = '{igreja_id}'
                """
            ).one()
        assert state == ("101_200", "101_200", 101)
    finally:
        with rls_engine.begin() as conn:
            conn.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade;")
