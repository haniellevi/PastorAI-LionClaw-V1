"""Real PostgreSQL proof for the V2b shared notification outbox migration."""

from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from tests.conftest_rls import assert_disposable_database


pytestmark = pytest.mark.rls_integration

_MIGRATION = (
    Path(__file__).parents[1]
    / "migrations"
    / "20260927_220000_notification_outbox_v2b.sql"
)
_EXACT_URL_ENV = "V2B_MIGRATION_EXACT_DATABASE_URL"
_TABLES = (
    "whatsapp_reminder_preferences",
    "agenda_reminder_subscriptions",
    "notification_outbox",
)


def _exact_database_url() -> str:
    url = os.environ.get(_EXACT_URL_ENV, "").strip()
    if not url:
        pytest.skip(f"{_EXACT_URL_ENV} não definida")
    assert_disposable_database(url)
    parsed = urlsplit(url)
    database_name = parsed.path.rsplit("/", 1)[-1].lower()
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or database_name != "v2b_migration_exact_test":
        raise RuntimeError("banco exato V2b não está explicitamente identificado")
    return url


def _apply(engine: Engine, sql: str) -> None:
    raw = engine.raw_connection()
    try:
        raw.autocommit = True
        with raw.cursor() as cursor:
            cursor.execute(sql)
    finally:
        raw.close()


@pytest.fixture
def rls_database_url() -> str:
    return _exact_database_url()


@pytest.fixture
def v2b_database(rls_database_url: str) -> Engine:
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
                "if not exists (select 1 from pg_roles where rolname = 'service_role') then "
                "create role service_role nologin noinherit nobypassrls; end if; "
                "if not exists (select 1 from pg_roles where rolname = 'agent_runtime') then "
                "create role agent_runtime nologin noinherit nobypassrls; end if; "
                "end $$;"
            )
            connection.exec_driver_sql(
                """
                create table public.igrejas (
                  id uuid primary key,
                  status text not null
                );
                create table public.pessoas (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  telefone text not null,
                  arquivada_em timestamptz,
                  optout boolean not null default false,
                  unique (igreja_id, id)
                );
                create table public.app_users (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  clerk_user_id text not null unique,
                  status text not null,
                  unique (igreja_id, id)
                );
                create table public.user_roles (
                  id uuid primary key default gen_random_uuid(),
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  user_id uuid not null,
                  papel text not null,
                  unique (igreja_id, user_id, papel),
                  foreign key (igreja_id, user_id)
                    references public.app_users(igreja_id, id) on delete cascade
                );
                create table public.events (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  status text not null,
                  notificado_em timestamptz,
                  titulo text not null default 'evento sintético',
                  data date,
                  hora text,
                  notificar_em timestamptz,
                  antecedencia_horas integer,
                  canal text,
                  created_at timestamptz not null default now()
                );
                create table public.agenda_alert_recipients (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  nome text not null,
                  telefone text not null,
                  ativo boolean not null default true
                );
                create table public.celula_reuniao (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  unique (igreja_id, id)
                );
                create table public.agent_action_proposals (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  action text not null,
                  target_kind text not null,
                  unique (igreja_id, id),
                  constraint agent_action_proposals_action_closed
                    check (action in ('registrar_decisao','marcar_presenca','enviar_relatorio_celula')),
                  constraint agent_action_proposals_target_kind_closed
                    check ((action in ('registrar_decisao','marcar_presenca') and target_kind = 'pessoa')
                      or (action = 'enviar_relatorio_celula' and target_kind = 'reuniao'))
                );
                create table public.agent_action_receipts (
                  id uuid primary key,
                  receipt_text text not null,
                  constraint agent_action_receipts_receipt_text_closed
                    check (receipt_text in ('Registro confirmado.','Relatório confirmado.'))
                );
                create table public.cell_report_reminders (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  reuniao_id uuid not null references public.celula_reuniao(id) on delete cascade,
                  leader_pessoa_id uuid not null references public.pessoas(id) on delete cascade,
                  state text not null,
                  due_at timestamptz not null,
                  claim_token uuid,
                  claimed_until timestamptz,
                  attempts integer not null default 0,
                  notice_recorded_at timestamptz,
                  sent_at timestamptz,
                  text_sha256 text not null,
                  terminal_reason text,
                  created_at timestamptz not null default now(),
                  updated_at timestamptz not null default now()
                );
                create table public.cell_report_reminder_preferences (
                  id uuid primary key default gen_random_uuid(),
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  pessoa_id uuid not null references public.pessoas(id) on delete cascade,
                  disabled_at timestamptz not null,
                  updated_at timestamptz not null,
                  unique (igreja_id, pessoa_id)
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
                "events",
                "agenda_alert_recipients",
                "celula_reuniao",
                "agent_action_proposals",
                "cell_report_reminders",
            ):
                connection.exec_driver_sql(f"alter table public.{table} enable row level security")
                connection.exec_driver_sql(
                    f"create policy tenant_isolation on public.{table} for all "
                    "using (igreja_id = public.current_igreja_id()) "
                    "with check (igreja_id = public.current_igreja_id())"
                )
            connection.exec_driver_sql("grant usage on schema public to authenticated, anon, service_role, agent_runtime")
            connection.exec_driver_sql("grant select, insert, update, delete on all tables in schema public to authenticated")
        yield engine
    finally:
        with engine.begin() as cleanup:
            cleanup.exec_driver_sql("drop schema public cascade; create schema public;")
        engine.dispose()


def _seed(connection, *, legacy_states: tuple[str, ...] = ()) -> dict[str, uuid.UUID]:
    ids = {name: uuid.uuid4() for name in ("tenant", "person", "event", "alert", "meeting", "proposal")}
    connection.execute(text("insert into igrejas(id,status) values(:tenant,'ativa')"), ids)
    connection.execute(
        text("insert into pessoas(id,igreja_id,telefone) values(:person,:tenant,'5500000000000')"),
        ids,
    )
    connection.execute(
        text("insert into events(id,igreja_id,status) values(:event,:tenant,'confirmado')"),
        ids,
    )
    connection.execute(
        text("insert into agenda_alert_recipients(id,igreja_id,nome,telefone) values(:alert,:tenant,'destinatário sintético','5500000000000')"),
        ids,
    )
    connection.execute(
        text("insert into celula_reuniao(id,igreja_id) values(:meeting,:tenant)"),
        ids,
    )
    connection.execute(
        text("""insert into agent_action_proposals(id,igreja_id,action,target_kind)
            values(:proposal,:tenant,'enviar_relatorio_celula','reuniao')"""),
        ids,
    )
    for state in legacy_states:
        reminder_id = uuid.uuid4()
        connection.execute(
            text("""insert into cell_report_reminders(
                id,igreja_id,reuniao_id,leader_pessoa_id,state,due_at,text_sha256
            ) values(:id,:tenant,:meeting,:person,:state,now(),repeat('a',64))"""),
            dict(ids, id=reminder_id, state=state),
        )
        ids[f"legacy_{state}"] = reminder_id
    return ids


def _worker(connection, tenant: uuid.UUID) -> None:
    connection.exec_driver_sql("set local role authenticated")
    connection.execute(text("select set_config('app.tenant_igreja_id',:v,true)"), {"v": str(tenant)})
    connection.execute(text("select set_config('request.jwt.claims','',true)"))
    connection.execute(text("select set_config('request.jwt.claim.sub','',true)"))


def _human(connection, tenant: uuid.UUID, clerk_user_id: str) -> None:
    """Emula ``deps.set_tenant_context`` depois da resolução segura do tenant."""
    connection.exec_driver_sql("set local role authenticated")
    connection.execute(text("select set_config('app.tenant_igreja_id',:v,true)"), {"v": str(tenant)})
    connection.execute(
        text("select set_config('request.jwt.claims',:claims,true)"),
        {"claims": f'{{"sub":"{clerk_user_id}"}}'},
    )
    connection.execute(text("select set_config('request.jwt.claim.sub','',true)"))
    assert connection.execute(
        text("select rolbypassrls from pg_catalog.pg_roles where rolname = current_user")
    ).scalar_one() is False


def _principal(
    connection,
    *,
    tenant: uuid.UUID,
    clerk_user_id: str,
    papel: str,
    status: str = "ativo",
) -> uuid.UUID:
    user_id = uuid.uuid4()
    connection.execute(
        text("""insert into public.app_users(id,igreja_id,clerk_user_id,status)
            values(:user_id,:tenant,:clerk_user_id,:status)"""),
        {
            "user_id": user_id,
            "tenant": tenant,
            "clerk_user_id": clerk_user_id,
            "status": status,
        },
    )
    connection.execute(
        text("""insert into public.user_roles(igreja_id,user_id,papel)
            values(:tenant,:user_id,:papel)"""),
        {"tenant": tenant, "user_id": user_id, "papel": papel},
    )
    return user_id


def _insert_evt7(
    connection,
    *,
    tenant: uuid.UUID,
    pessoa_id: uuid.UUID,
    recipient_id: uuid.UUID,
    event_id: uuid.UUID,
    delivery_reservation_day: date | None = None,
) -> None:
    connection.execute(
        text("""insert into public.notification_outbox(
            igreja_id,pessoa_id,agenda_alert_recipient_id,event_id,origin_kind,origin_id,
            occurrence_at,origin_fingerprint,purpose,state,due_at,delivery_reservation_day,updated_at
        ) values(:tenant,:pessoa_id,:recipient_id,:event_id,'event',:event_id,now(),repeat('c',64),
            'agenda_evt7','pendente',now(),:delivery_reservation_day,now())"""),
        {
            "tenant": tenant,
            "pessoa_id": pessoa_id,
            "recipient_id": recipient_id,
            "event_id": event_id,
            "delivery_reservation_day": delivery_reservation_day,
        },
    )


def _active_evt7_target(connection) -> dict[str, uuid.UUID]:
    ids = _seed(connection)
    connection.execute(
        text("update public.agenda_alert_recipients set pessoa_id=:person where id=:alert"),
        ids,
    )
    connection.execute(
        text("""insert into public.whatsapp_reminder_preferences(
            igreja_id,pessoa_id,reminder_kind,state,term_version,accepted_at,changed_at
        ) values(:tenant,:person,'agenda','active','termo-sintetico',now(),now())"""),
        ids,
    )
    return ids


def _additional_active_evt7_target(
    connection,
    *,
    tenant: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID]:
    pessoa_id = uuid.uuid4()
    recipient_id = uuid.uuid4()
    connection.execute(
        text("""insert into public.pessoas(id,igreja_id,telefone)
            values(:pessoa_id,:tenant,'5500000000002')"""),
        {"pessoa_id": pessoa_id, "tenant": tenant},
    )
    connection.execute(
        text("""insert into public.agenda_alert_recipients(
            id,igreja_id,nome,telefone,ativo,pessoa_id
        ) values(:recipient_id,:tenant,'destinatário sintético 2','5500000000002',true,:pessoa_id)"""),
        {"recipient_id": recipient_id, "tenant": tenant, "pessoa_id": pessoa_id},
    )
    connection.execute(
        text("""insert into public.whatsapp_reminder_preferences(
            igreja_id,pessoa_id,reminder_kind,state,term_version,accepted_at,changed_at
        ) values(:tenant,:pessoa_id,'agenda','active','termo-sintetico',now(),now())"""),
        {"tenant": tenant, "pessoa_id": pessoa_id},
    )
    return pessoa_id, recipient_id


def test_v2b_migration_applies_real_sql_twice_and_reapplies_acl(v2b_database: Engine) -> None:
    sql = _MIGRATION.read_text()
    assert not re.search(r"\bdelete\s+from\b", sql, flags=re.IGNORECASE)
    with v2b_database.begin() as connection:
        ids = _seed(connection)
    _apply(v2b_database, sql)
    with v2b_database.begin() as connection:
        oids = {
            table: connection.execute(text("select cast(:t as regclass)::oid"), {"t": table}).scalar_one()
            for table in _TABLES
        }
        for table in _TABLES:
            connection.exec_driver_sql(f"grant delete on public.{table} to authenticated")
    _apply(v2b_database, sql)
    with v2b_database.connect() as connection:
        for table in _TABLES:
            assert connection.execute(text("select cast(:t as regclass)::oid"), {"t": table}).scalar_one() == oids[table]
            assert not connection.execute(
                text("select has_table_privilege('authenticated',:t,'DELETE')"), {"t": table}
            ).scalar_one()
        assert connection.execute(text("select count(*) from notification_outbox")).scalar_one() == 0
        assert connection.execute(
            text("select notification_outbox_fenced_at is not null from events where id=:event"), ids
        ).scalar_one()
        assert connection.execute(
            text("select pg_catalog.to_regclass('public.notification_outbox_cutovers')")
        ).scalar_one() is None


def test_v2b_cutover_fences_legacy_paths_without_replay(v2b_database: Engine) -> None:
    with v2b_database.begin() as connection:
        ids = _seed(connection, legacy_states=("pendente", "retry", "em_envio", "enviado", "ambiguo"))
        connection.execute(
            text("""insert into cell_report_reminder_preferences(
                igreja_id,pessoa_id,disabled_at,updated_at
            ) values(:tenant,:person,now(),now())"""),
            ids,
        )
    _apply(v2b_database, _MIGRATION.read_text())
    with v2b_database.begin() as connection:
        assert connection.execute(
            text("select notificado_em is not null and notification_outbox_fenced_at is not null from events where id=:event"),
            ids,
        ).scalar_one()
        states = dict(connection.execute(text("select state, count(*) from cell_report_reminders group by state")).all())
        assert states == {"ambiguo": 2, "cancelado": 2, "enviado": 1}
        assert connection.execute(
            text("""select state from whatsapp_reminder_preferences
                where igreja_id=:tenant and pessoa_id=:person and reminder_kind='cell_report'"""),
            ids,
        ).scalar_one() == "disabled"
        assert connection.execute(text("select count(*) from notification_outbox")).scalar_one() == 0
        connection.execute(
            text("""insert into cell_report_reminders(
                id,igreja_id,reuniao_id,leader_pessoa_id,state,due_at,text_sha256
            ) values(:id,:tenant,:meeting,:person,'pendente',now(),repeat('a',64))"""),
            dict(ids, id=uuid.uuid4()),
        )
        assert connection.execute(text("select state from cell_report_reminders order by created_at desc limit 1")).scalar_one() == "cancelado"


def test_v2b_new_outbox_is_tenant_isolated_and_source_removal_keeps_receipt(v2b_database: Engine) -> None:
    _apply(v2b_database, _MIGRATION.read_text())
    with v2b_database.begin() as connection:
        own, other = _seed(connection), _seed(connection)
        connection.execute(
            text("""insert into notification_outbox(
                igreja_id,pessoa_id,event_id,origin_kind,origin_id,occurrence_at,
                origin_fingerprint,purpose,state,due_at,updated_at
            ) values(:tenant,:person,:event,'event',:event,now(),repeat('a',64),
                'agenda_reminder','pendente',now(),now())"""),
            own,
        )
        with pytest.raises(DBAPIError) as mismatch:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into notification_outbox(
                        igreja_id,pessoa_id,event_id,origin_kind,origin_id,occurrence_at,
                        origin_fingerprint,purpose,state,due_at,updated_at
                    ) values(:tenant,:person,:event,'event',:origin,now()+interval '1 minute',
                        repeat('c',64),'agenda_reminder','pendente',now(),now())"""),
                    dict(own, origin=uuid.uuid4()),
                )
        assert mismatch.value.orig.pgcode == "23514"
        with pytest.raises(DBAPIError) as missing_acceptance:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into whatsapp_reminder_preferences(
                        igreja_id,pessoa_id,reminder_kind,state,term_version,changed_at
                    ) values(:tenant,:person,'agenda','active','termo-sintetico',now())"""),
                    own,
                )
        assert missing_acceptance.value.orig.pgcode == "23514"
        connection.execute(text("delete from events where id=:event"), own)
        row = connection.execute(text("""select event_id is null, origin_id, state
            from notification_outbox where igreja_id=:tenant"""), own).one()
        assert row == (True, own["event"], "pendente")
        _worker(connection, own["tenant"])
        assert connection.execute(text("select count(*) from notification_outbox")).scalar_one() == 1
        assert connection.execute(
            text("select count(*) from notification_outbox where igreja_id=:tenant"), other
        ).scalar_one() == 0
        with pytest.raises(DBAPIError) as error:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into notification_outbox(
                        igreja_id,pessoa_id,event_id,origin_kind,origin_id,occurrence_at,
                        origin_fingerprint,purpose,state,due_at,updated_at
                    ) values(:tenant,:person,:event,'event',:event,now(),repeat('b',64),
                        'agenda_reminder','pendente',now(),now())"""),
                    dict(own, event=other["event"]),
                )
        assert error.value.orig.pgcode == "23503"


def test_v2b_new_tenant_has_creation_cutover_before_reapply_without_bypass(
    v2b_database: Engine,
) -> None:
    _apply(v2b_database, _MIGRATION.read_text())
    tenant = uuid.uuid4()
    with v2b_database.begin() as connection:
        connection.exec_driver_sql("alter table public.igrejas owner to authenticated")
        connection.exec_driver_sql("set local role authenticated")
        assert connection.execute(
            text("select rolbypassrls from pg_catalog.pg_roles where rolname = current_user")
        ).scalar_one() is False
        connection.execute(
            text("insert into public.igrejas(id,status) values(:tenant,'ativa')"),
            {"tenant": tenant},
        )
        assert connection.execute(
            text("select notification_outbox_cutover_at is not null from public.igrejas where id=:tenant"),
            {"tenant": tenant},
        ).scalar_one()

    ids = {"tenant": tenant, "person": uuid.uuid4(), "event": uuid.uuid4()}
    with v2b_database.begin() as connection:
        connection.execute(
            text("insert into public.pessoas(id,igreja_id,telefone) values(:person,:tenant,'5500000000001')"),
            ids,
        )
        connection.execute(
            text("insert into public.events(id,igreja_id,status) values(:event,:tenant,'a_confirmar')"),
            ids,
        )
        connection.execute(text("select set_config('app.notification_outbox_v2b','1',true)"))
        connection.execute(
            text("update public.events set status='confirmado' where id=:event"),
            ids,
        )

    _apply(v2b_database, _MIGRATION.read_text())
    with v2b_database.connect() as connection:
        assert connection.execute(
            text("""select notification_outbox_fenced_at is null and notificado_em is null
                from public.events where id=:event"""),
            ids,
        ).scalar_one()


def test_v2b_human_preference_requires_active_pastor_or_admin(
    v2b_database: Engine,
) -> None:
    _apply(v2b_database, _MIGRATION.read_text())
    with v2b_database.begin() as connection:
        ids = _active_evt7_target(connection)
        disabled_person, _ = _additional_active_evt7_target(
            connection, tenant=ids["tenant"]
        )
        connection.execute(
            text("""update public.whatsapp_reminder_preferences
                set state='disabled', term_version=null, accepted_at=null
                where igreja_id=:tenant and pessoa_id=:pessoa_id and reminder_kind='agenda'"""),
            {"tenant": ids["tenant"], "pessoa_id": disabled_person},
        )
        _principal(
            connection,
            tenant=ids["tenant"],
            clerk_user_id="clerk-pastor-synthetic",
            papel="pastor",
        )
        _principal(
            connection,
            tenant=ids["tenant"],
            clerk_user_id="clerk-admin-synthetic",
            papel="admin",
        )
        _principal(
            connection,
            tenant=ids["tenant"],
            clerk_user_id="clerk-membro-synthetic",
            papel="membro",
        )
        _principal(
            connection,
            tenant=ids["tenant"],
            clerk_user_id="clerk-convidado-synthetic",
            papel="pastor",
            status="convidado",
        )

    for clerk_user_id in ("clerk-pastor-synthetic", "clerk-admin-synthetic"):
        with v2b_database.begin() as connection:
            _human(connection, ids["tenant"], clerk_user_id)
            assert connection.execute(
                text("""select reminder_kind, state from public.whatsapp_reminder_preferences
                    order by reminder_kind, state"""),
            ).all() == [("agenda", "active")]

    for clerk_user_id in ("clerk-membro-synthetic", "clerk-convidado-synthetic"):
        with v2b_database.begin() as connection:
            _human(connection, ids["tenant"], clerk_user_id)
            assert connection.execute(
                text("select count(*) from public.whatsapp_reminder_preferences")
            ).scalar_one() == 0
            with pytest.raises(DBAPIError) as evt7_write:
                with connection.begin_nested():
                    _insert_evt7(
                        connection,
                        tenant=ids["tenant"],
                        pessoa_id=ids["person"],
                        recipient_id=ids["alert"],
                        event_id=ids["event"],
                    )
            assert evt7_write.value.orig.pgcode == "42501"

    with v2b_database.begin() as connection:
        _human(connection, ids["tenant"], "clerk-pastor-synthetic")
        with pytest.raises(DBAPIError) as preference_write:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into public.whatsapp_reminder_preferences(
                        igreja_id,pessoa_id,reminder_kind,state,term_version,accepted_at,changed_at
                    ) values(:tenant,:person,'agenda','active','termo-sintetico-2',now(),now())"""),
                    ids,
                )
        assert preference_write.value.orig.pgcode == "42501"


def test_v2b_human_evt7_allows_active_pastor_and_admin_only(
    v2b_database: Engine,
) -> None:
    _apply(v2b_database, _MIGRATION.read_text())
    with v2b_database.begin() as connection:
        ids = _active_evt7_target(connection)
        second_person, second_alert = _additional_active_evt7_target(
            connection, tenant=ids["tenant"]
        )
        _principal(
            connection,
            tenant=ids["tenant"],
            clerk_user_id="clerk-pastor-synthetic",
            papel="pastor",
        )
        _principal(
            connection,
            tenant=ids["tenant"],
            clerk_user_id="clerk-admin-synthetic",
            papel="admin",
        )
        connection.execute(
            text("""insert into public.notification_outbox(
                igreja_id,pessoa_id,event_id,origin_kind,origin_id,occurrence_at,
                origin_fingerprint,purpose,state,due_at,delivery_reservation_day,updated_at
            ) values(:tenant,:person,:event,'event',:event,now(),repeat('a',64),
                'agenda_reminder','pendente',now(),null,now())"""),
            ids,
        )
        connection.execute(
            text("""insert into public.notification_outbox(
                igreja_id,pessoa_id,reuniao_id,origin_kind,origin_id,occurrence_at,
                origin_fingerprint,purpose,state,due_at,delivery_reservation_day,updated_at
            ) values(:tenant,:person,:meeting,'meeting',:meeting,now(),repeat('b',64),
                'cell_report_reminder','pendente',now(),null,now())"""),
            ids,
        )

    with v2b_database.begin() as connection:
        _human(connection, ids["tenant"], "clerk-pastor-synthetic")
        _insert_evt7(
            connection,
            tenant=ids["tenant"],
            pessoa_id=ids["person"],
            recipient_id=ids["alert"],
            event_id=ids["event"],
        )
        assert connection.execute(
            text("select distinct purpose from public.notification_outbox order by purpose")
        ).scalars().all() == ["agenda_evt7"]
        assert connection.execute(
            text("""update public.notification_outbox set state='enviado'
                where purpose='agenda_evt7'"""),
        ).rowcount == 0
        with pytest.raises(DBAPIError) as reserved_initially:
            with connection.begin_nested():
                _insert_evt7(
                    connection,
                    tenant=ids["tenant"],
                    pessoa_id=ids["person"],
                    recipient_id=ids["alert"],
                    event_id=ids["event"],
                    delivery_reservation_day=date(2026, 9, 27),
                )
        assert reserved_initially.value.orig.pgcode == "42501"

    with v2b_database.begin() as connection:
        _human(connection, ids["tenant"], "clerk-admin-synthetic")
        _insert_evt7(
            connection,
            tenant=ids["tenant"],
            pessoa_id=second_person,
            recipient_id=second_alert,
            event_id=ids["event"],
        )
        assert connection.execute(
            text("select count(*) from public.notification_outbox where purpose='agenda_evt7'")
        ).scalar_one() == 2


def test_v2b_human_evt7_rejects_missing_or_not_yet_effective_opt_in(
    v2b_database: Engine,
) -> None:
    _apply(v2b_database, _MIGRATION.read_text())
    with v2b_database.begin() as connection:
        ids = _seed(connection)
        connection.execute(
            text("update public.agenda_alert_recipients set pessoa_id=:person where id=:alert"),
            ids,
        )
        _principal(
            connection,
            tenant=ids["tenant"],
            clerk_user_id="clerk-pastor-synthetic",
            papel="pastor",
        )

    with v2b_database.begin() as connection:
        _human(connection, ids["tenant"], "clerk-pastor-synthetic")
        with pytest.raises(DBAPIError) as missing_opt_in:
            with connection.begin_nested():
                _insert_evt7(
                    connection,
                    tenant=ids["tenant"],
                    pessoa_id=ids["person"],
                    recipient_id=ids["alert"],
                    event_id=ids["event"],
                )
        assert missing_opt_in.value.orig.pgcode == "42501"

    with v2b_database.begin() as connection:
        connection.execute(
            text("""insert into public.whatsapp_reminder_preferences(
                igreja_id,pessoa_id,reminder_kind,state,term_version,accepted_at,changed_at
            ) values(:tenant,:person,'agenda','active','termo-sintetico',
                now() + interval '1 minute',now())"""),
            ids,
        )
    with v2b_database.begin() as connection:
        _human(connection, ids["tenant"], "clerk-pastor-synthetic")
        assert connection.execute(
            text("select count(*) from public.whatsapp_reminder_preferences")
        ).scalar_one() == 0
        with pytest.raises(DBAPIError) as future_opt_in:
            with connection.begin_nested():
                _insert_evt7(
                    connection,
                    tenant=ids["tenant"],
                    pessoa_id=ids["person"],
                    recipient_id=ids["alert"],
                    event_id=ids["event"],
                )
        assert future_opt_in.value.orig.pgcode == "42501"


def test_v2b_human_evt7_rejects_adulterated_recipient_and_invalid_event(
    v2b_database: Engine,
) -> None:
    _apply(v2b_database, _MIGRATION.read_text())
    with v2b_database.begin() as connection:
        ids = _active_evt7_target(connection)
        other_person, _ = _additional_active_evt7_target(connection, tenant=ids["tenant"])
        _principal(
            connection,
            tenant=ids["tenant"],
            clerk_user_id="clerk-pastor-synthetic",
            papel="pastor",
        )

    with v2b_database.begin() as connection:
        _human(connection, ids["tenant"], "clerk-pastor-synthetic")
        with pytest.raises(DBAPIError) as adulterated_recipient:
            with connection.begin_nested():
                _insert_evt7(
                    connection,
                    tenant=ids["tenant"],
                    pessoa_id=other_person,
                    recipient_id=ids["alert"],
                    event_id=ids["event"],
                )
        assert adulterated_recipient.value.orig.pgcode == "42501"
        with pytest.raises(DBAPIError) as unconfirmed_event:
            with connection.begin_nested():
                connection.execute(
                    text("update public.events set status='a_confirmar' where id=:event"), ids
                )
                _insert_evt7(
                    connection,
                    tenant=ids["tenant"],
                    pessoa_id=ids["person"],
                    recipient_id=ids["alert"],
                    event_id=ids["event"],
                )
        assert unconfirmed_event.value.orig.pgcode == "42501"
        with pytest.raises(DBAPIError) as receipt_event:
            with connection.begin_nested():
                connection.execute(
                    text("update public.events set notificado_em=now() where id=:event"), ids
                )
                _insert_evt7(
                    connection,
                    tenant=ids["tenant"],
                    pessoa_id=ids["person"],
                    recipient_id=ids["alert"],
                    event_id=ids["event"],
                )
        assert receipt_event.value.orig.pgcode == "42501"
        with pytest.raises(DBAPIError) as fenced_event:
            with connection.begin_nested():
                connection.execute(
                    text("""update public.events set notification_outbox_fenced_at=now()
                        where id=:event"""),
                    ids,
                )
                _insert_evt7(
                    connection,
                    tenant=ids["tenant"],
                    pessoa_id=ids["person"],
                    recipient_id=ids["alert"],
                    event_id=ids["event"],
                )
        assert fenced_event.value.orig.pgcode == "42501"


def test_v2b_delivery_reservation_survives_retry_ambiguity_and_origin_removal(
    v2b_database: Engine,
) -> None:
    _apply(v2b_database, _MIGRATION.read_text())
    with v2b_database.begin() as connection:
        ids = _seed(connection)
        connection.execute(
            text("""insert into public.notification_outbox(
                igreja_id,pessoa_id,event_id,origin_kind,origin_id,occurrence_at,
                origin_fingerprint,purpose,state,due_at,delivery_reservation_day,updated_at
            ) values(:tenant,:person,:event,'event',:event,now(),repeat('a',64),
                'agenda_reminder','retry',now(),current_date - 1,now())"""),
            ids,
        )
        _worker(connection, ids["tenant"])
        connection.execute(
            text("""update public.notification_outbox
                set delivery_reservation_day=current_date, due_at=now() + interval '1 day'
                where igreja_id=:tenant and purpose='agenda_reminder'"""),
            ids,
        )
        connection.execute(
            text("""update public.notification_outbox set state='ambiguo'
                where igreja_id=:tenant and purpose='agenda_reminder'"""),
            ids,
        )
        connection.execute(text("delete from public.events where id=:event"), ids)
        assert connection.execute(
            text("""select delivery_reservation_day = current_date,
                event_id is null, state = 'ambiguo'
                from public.notification_outbox where igreja_id=:tenant"""),
            ids,
        ).scalar_one()
