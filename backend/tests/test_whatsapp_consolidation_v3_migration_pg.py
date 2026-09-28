"""PostgreSQL 17 proof for the V3 consolidation WhatsApp migration."""

from __future__ import annotations

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
    / "20260928_080000_whatsapp_consolidation_v3.sql"
)
_EXACT_URL_ENV = "V3_MIGRATION_EXACT_DATABASE_URL"
_ACTIVATION = "consolidation_whatsapp_activation"


def _exact_database_url() -> str:
    url = os.environ.get(_EXACT_URL_ENV, "").strip()
    if not url:
        pytest.skip(f"{_EXACT_URL_ENV} não definida")
    assert_disposable_database(url)
    parsed = urlsplit(url)
    database_name = parsed.path.rsplit("/", 1)[-1].lower()
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or database_name != "v3_migration_exact_test"
    ):
        raise RuntimeError("banco exato V3 não está explicitamente identificado")
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
def v3_database(rls_database_url: str) -> Engine:
    """Build only the post-V2b parent shape used by this migration."""

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
                  status text not null default 'ativa'
                );
                create table public.pessoas (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  telefone text not null,
                  optout boolean not null default false,
                  arquivada_em timestamptz,
                  unique (igreja_id, id)
                );
                create table public.app_users (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  pessoa_id uuid references public.pessoas(id) on delete set null,
                  clerk_user_id text unique,
                  status text not null default 'ativo',
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
                  unique (igreja_id, id)
                );
                create table public.celula_reuniao (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  unique (igreja_id, id)
                );
                create table public.agenda_alert_recipients (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  unique (igreja_id, id)
                );
                create table public.agenda_reminder_subscriptions (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  unique (igreja_id, id)
                );
                create table public.decisions (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  pessoa_id uuid not null references public.pessoas(id) on delete cascade,
                  origem text,
                  vinculo text not null,
                  celula_id uuid,
                  responsavel_id uuid references public.app_users(id) on delete set null,
                  prazo_conexao timestamptz,
                  created_at timestamptz not null default now()
                );
                create table public.consolidacoes (
                  id uuid primary key default gen_random_uuid(),
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  pessoa_id uuid not null references public.pessoas(id) on delete cascade,
                  tipo text,
                  responsavel_id uuid references public.app_users(id) on delete set null,
                  progresso integer not null default 0,
                  concluida boolean not null default false,
                  prazo_conexao timestamptz,
                  abandonada_em timestamptz,
                  abandonada_motivo text,
                  created_at timestamptz not null default now()
                );
                create unique index uq_consolidacoes_pessoa_aberta
                  on public.consolidacoes(pessoa_id)
                  where concluida = false and abandonada_em is null;
                create table public.consolidacao_etapas (
                  id uuid primary key default gen_random_uuid(),
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  consolidacao_id uuid not null references public.consolidacoes(id) on delete cascade,
                  etapa text,
                  concluida boolean not null default false,
                  confirmada_por uuid references public.app_users(id) on delete set null,
                  confirmada_em timestamptz
                );
                create table public.work_queue_items (
                  id uuid primary key default gen_random_uuid(),
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  tipo text not null,
                  titulo text not null,
                  contexto text,
                  pessoa_id uuid references public.pessoas(id) on delete set null,
                  responsavel_id uuid references public.app_users(id) on delete set null,
                  status text,
                  prazo timestamptz,
                  prioridade integer,
                  created_at timestamptz not null default now()
                );
                create table public.whatsapp_reminder_preferences (
                  id uuid primary key default gen_random_uuid(),
                  igreja_id uuid not null,
                  pessoa_id uuid not null,
                  reminder_kind text not null,
                  state text not null,
                  term_version text,
                  accepted_at timestamptz,
                  changed_at timestamptz not null,
                  unique (igreja_id, id),
                  unique (igreja_id, pessoa_id, reminder_kind),
                  constraint whatsapp_reminder_preferences_tenant_pessoa_fkey
                    foreign key (igreja_id, pessoa_id)
                    references public.pessoas(igreja_id, id) on delete cascade,
                  constraint whatsapp_reminder_preferences_state_closed
                    check (state in ('active', 'disabled')),
                  constraint whatsapp_reminder_preferences_kind_closed
                    check (reminder_kind in ('agenda', 'cell_report')),
                  constraint whatsapp_reminder_preferences_active_term_chk check (
                    (state = 'active' and term_version is not null
                      and length(btrim(term_version)) > 0 and accepted_at is not null)
                    or (state = 'disabled' and term_version is null and accepted_at is null)
                  )
                );
                create table public.notification_outbox (
                  id uuid primary key default gen_random_uuid(),
                  igreja_id uuid not null,
                  pessoa_id uuid not null,
                  agenda_alert_recipient_id uuid,
                  event_id uuid,
                  reuniao_id uuid,
                  agenda_subscription_id uuid,
                  origin_kind text not null,
                  origin_id uuid not null,
                  occurrence_at timestamptz not null,
                  origin_fingerprint text not null,
                  purpose text not null,
                  state text not null,
                  due_at timestamptz not null,
                  delivery_reservation_day date,
                  claim_token uuid,
                  claimed_until timestamptz,
                  claimed_by text,
                  attempts integer not null default 0,
                  transport_started_at timestamptz,
                  sent_at timestamptz,
                  terminal_reason text,
                  created_at timestamptz not null default now(),
                  updated_at timestamptz not null,
                  constraint notification_outbox_tenant_id_key unique (igreja_id, id),
                  constraint notification_outbox_recipient_origin_occurrence_purpose_key
                    unique (igreja_id,pessoa_id,origin_kind,origin_id,occurrence_at,purpose),
                  constraint notification_outbox_tenant_pessoa_fkey
                    foreign key (igreja_id,pessoa_id)
                    references public.pessoas(igreja_id,id) on delete cascade,
                  constraint notification_outbox_tenant_event_fkey
                    foreign key (igreja_id,event_id)
                    references public.events(igreja_id,id) on delete set null (event_id),
                  constraint notification_outbox_tenant_reuniao_fkey
                    foreign key (igreja_id,reuniao_id)
                    references public.celula_reuniao(igreja_id,id) on delete set null (reuniao_id),
                  constraint notification_outbox_tenant_alert_recipient_fkey
                    foreign key (igreja_id,agenda_alert_recipient_id)
                    references public.agenda_alert_recipients(igreja_id,id)
                    on delete set null (agenda_alert_recipient_id),
                  constraint notification_outbox_tenant_subscription_fkey
                    foreign key (igreja_id,agenda_subscription_id)
                    references public.agenda_reminder_subscriptions(igreja_id,id)
                    on delete set null (agenda_subscription_id),
                  constraint notification_outbox_purpose_closed
                    check (purpose in ('agenda_reminder','agenda_evt7','cell_report_reminder')),
                  constraint notification_outbox_state_closed
                    check (state in ('pendente','em_envio','retry','enviado','ambiguo','cancelado','obsoleto','fenced')),
                  constraint notification_outbox_attempts_range check (attempts between 0 and 2),
                  constraint notification_outbox_reference_shape_chk check (
                    (purpose = 'agenda_reminder' and origin_kind = 'event'
                      and reuniao_id is null and agenda_alert_recipient_id is null)
                    or (purpose = 'agenda_evt7' and origin_kind = 'event'
                      and reuniao_id is null and agenda_subscription_id is null)
                    or (purpose = 'cell_report_reminder' and origin_kind = 'meeting'
                      and event_id is null and agenda_subscription_id is null
                      and agenda_alert_recipient_id is null)
                  ),
                  constraint notification_outbox_origin_kind_closed
                    check (origin_kind in ('event','meeting')),
                  constraint notification_outbox_live_origin_identity_chk check (
                    (event_id is null or (origin_kind = 'event' and origin_id = event_id))
                    and (reuniao_id is null or (origin_kind = 'meeting' and origin_id = reuniao_id))
                  ),
                  constraint notification_outbox_origin_fingerprint_shape
                    check (origin_fingerprint ~ '^[0-9a-f]{64}$')
                );
                create table public.agent_action_proposals (
                  id uuid primary key,
                  igreja_id uuid not null references public.igrejas(id) on delete cascade,
                  action text not null,
                  target_kind text not null,
                  unique (igreja_id, id),
                  constraint agent_action_proposals_action_closed check (
                    action in ('registrar_decisao','marcar_presenca',
                               'enviar_relatorio_celula','configurar_lembrete_agenda')
                  ),
                  constraint agent_action_proposals_target_kind_closed check (
                    (action in ('registrar_decisao','marcar_presenca') and target_kind = 'pessoa')
                    or (action = 'enviar_relatorio_celula' and target_kind = 'reuniao')
                    or (action = 'configurar_lembrete_agenda' and target_kind = 'evento')
                  )
                );
                create table public.agent_action_receipts (
                  id uuid primary key,
                  receipt_text text not null,
                  constraint agent_action_receipts_receipt_text_closed check (
                    receipt_text in ('Registro confirmado.','Relatório confirmado.','Lembrete confirmado.')
                  )
                );
                create function public.current_igreja_id() returns uuid
                  language sql stable as $$
                    select nullif(current_setting('app.tenant_igreja_id', true), '')::uuid
                  $$;
                create function public.fn_decision_opens_consolidation() returns trigger
                  language plpgsql as $$
                  declare v_consolidacao_id uuid;
                  begin
                    insert into public.consolidacoes(
                      igreja_id,pessoa_id,tipo,responsavel_id,progresso,concluida,prazo_conexao
                    ) values (
                      new.igreja_id,new.pessoa_id,'individual',new.responsavel_id,0,false,new.prazo_conexao
                    ) returning id into v_consolidacao_id;
                    insert into public.consolidacao_etapas(igreja_id,consolidacao_id,etapa,concluida)
                      values(new.igreja_id,v_consolidacao_id,'aceitou_jesus',true);
                    if new.vinculo = 'visitante' then
                      insert into public.work_queue_items(
                        igreja_id,tipo,titulo,contexto,pessoa_id,responsavel_id,status,prazo,prioridade
                      ) values (
                        new.igreja_id,'conectar_celula','Conectar nova decisao a uma celula',
                        'legado',new.pessoa_id,new.responsavel_id,'aberto',now() + interval '24 hours',1
                      );
                    end if;
                    return new;
                  end;
                  $$;
                create trigger trg_decision_opens_consolidation
                  after insert on public.decisions
                  for each row execute function public.fn_decision_opens_consolidation();
                """
            )
            for table in (
                "pessoas",
                "app_users",
                "user_roles",
                "decisions",
                "consolidacoes",
                "consolidacao_etapas",
                "work_queue_items",
                "whatsapp_reminder_preferences",
                "notification_outbox",
            ):
                connection.exec_driver_sql(
                    f"alter table public.{table} enable row level security"
                )
                connection.exec_driver_sql(
                    f"create policy tenant_isolation on public.{table} for all "
                    "using (igreja_id = public.current_igreja_id()) "
                    "with check (igreja_id = public.current_igreja_id())"
                )
            connection.exec_driver_sql(
                "grant usage on schema public to authenticated, anon, service_role, agent_runtime;"
                "grant select, insert, update, delete on all tables in schema public to authenticated;"
            )
        yield engine
    finally:
        with engine.begin() as cleanup:
            cleanup.exec_driver_sql("drop schema public cascade; create schema public;")
        engine.dispose()


def _worker(connection, tenant: uuid.UUID) -> None:
    connection.exec_driver_sql("set local role authenticated")
    connection.execute(
        text("select set_config('app.tenant_igreja_id',:tenant,true)"),
        {"tenant": str(tenant)},
    )
    connection.execute(text("select set_config('request.jwt.claims','',true)"))
    connection.execute(text("select set_config('request.jwt.claim.sub','',true)"))
    assert connection.execute(
        text("select rolbypassrls from pg_catalog.pg_roles where rolname=current_user")
    ).scalar_one() is False


def _human(connection, tenant: uuid.UUID, clerk_user_id: str) -> None:
    connection.exec_driver_sql("set local role authenticated")
    connection.execute(
        text("select set_config('app.tenant_igreja_id',:tenant,true)"),
        {"tenant": str(tenant)},
    )
    connection.execute(
        text("select set_config('request.jwt.claims',:claims,true)"),
        {"claims": f'{{"sub":"{clerk_user_id}"}}'},
    )
    connection.execute(text("select set_config('request.jwt.claim.sub','',true)"))


def _seed_tenant(connection, *, clerk_user_id: str = "clerk-sintetico") -> dict[str, uuid.UUID]:
    values = {
        "tenant": uuid.uuid4(),
        "person": uuid.uuid4(),
        "user": uuid.uuid4(),
    }
    connection.execute(
        text("insert into public.igrejas(id,status) values(:tenant,'ativa')"), values
    )
    connection.execute(
        text("insert into public.pessoas(id,igreja_id,telefone) values(:person,:tenant,'5500000000000')"),
        values,
    )
    connection.execute(
        text("""insert into public.app_users(id,igreja_id,pessoa_id,clerk_user_id,status)
            values(:user,:tenant,:person,:clerk_user_id,'ativo')"""),
        dict(values, clerk_user_id=clerk_user_id),
    )
    return values


def _insert_decision(connection, values: dict[str, uuid.UUID], *, vinculo: str = "visitante") -> uuid.UUID:
    decision_id = uuid.uuid4()
    connection.execute(
        text("""insert into public.decisions(
            id,igreja_id,pessoa_id,vinculo,responsavel_id,prazo_conexao
        ) values(:decision,:tenant,:person,:vinculo,:user,now() + interval '24 hours')"""),
        dict(values, decision=decision_id, vinculo=vinculo),
    )
    return decision_id


def _outbox_fonovisita(connection, values: dict[str, uuid.UUID], *, consolidacao_id: uuid.UUID | None, queue_id: uuid.UUID) -> uuid.UUID:
    outbox_id = uuid.uuid4()
    connection.execute(
        text("""insert into public.notification_outbox(
            id,igreja_id,pessoa_id,consolidacao_id,work_queue_item_id,
            origin_kind,origin_id,occurrence_at,origin_fingerprint,purpose,state,due_at,
            delivery_reservation_day,updated_at
        ) values(
            :id,:tenant,:person,:consolidacao,:queue,'work_queue',:queue,now(),repeat('a',64),
            'consolidation_fonovisita','ambiguo',now(),current_date,now()
        )"""),
        dict(values, id=outbox_id, consolidacao=consolidacao_id, queue=queue_id),
    )
    return outbox_id


def test_v3_migration_applies_twice_without_backfill_and_restores_activation_acl(
    v3_database: Engine,
) -> None:
    sql = _MIGRATION.read_text()
    assert not re.search(r"\bdelete\s+from\b", sql, flags=re.IGNORECASE)
    _apply(v3_database, sql)
    with v3_database.begin() as connection:
        oid = connection.execute(
            text("select 'public.consolidation_whatsapp_activation'::regclass::oid")
        ).scalar_one()
        assert connection.execute(
            text("select count(*) from public.consolidation_whatsapp_activation")
        ).scalar_one() == 0
        connection.exec_driver_sql(
            "grant delete on public.consolidation_whatsapp_activation to authenticated"
        )
    _apply(v3_database, sql)
    with v3_database.connect() as connection:
        assert connection.execute(
            text("select 'public.consolidation_whatsapp_activation'::regclass::oid")
        ).scalar_one() == oid
        assert not connection.execute(
            text("select has_table_privilege('authenticated',:table,'DELETE')"),
            {"table": f"public.{_ACTIVATION}"},
        ).scalar_one()
        assert connection.execute(
            text("""select relrowsecurity and relforcerowsecurity
                from pg_catalog.pg_class where oid=cast(:table as regclass)"""),
            {"table": f"public.{_ACTIVATION}"},
        ).scalar_one() is True
        for role in ("anon", "service_role", "agent_runtime"):
            assert not connection.execute(
                text("select has_table_privilege(:role,:table,'SELECT')"),
                {"role": role, "table": f"public.{_ACTIVATION}"},
            ).scalar_one()


def test_v3_decision_trigger_creates_one_linked_fonovisita_and_preserves_visitor_deadline(
    v3_database: Engine,
) -> None:
    _apply(v3_database, _MIGRATION.read_text())
    with v3_database.begin() as connection:
        values = _seed_tenant(connection)
        decision_id = _insert_decision(connection, values)
        track = connection.execute(
            text("""select id, origin_decision_id, assignment_revision
                from public.consolidacoes where igreja_id=:tenant"""), values
        ).one()
        assert track.origin_decision_id == decision_id
        assert track.assignment_revision == 0
        queue = connection.execute(
            text("""select id,tipo,consolidacao_id,prazo
                from public.work_queue_items where igreja_id=:tenant order by tipo"""), values
        ).all()
        assert len(queue) == 2
        by_type = {row.tipo: row for row in queue}
        assert set(by_type) == {"conectar_celula", "fonovisita"}
        assert by_type["conectar_celula"].consolidacao_id == track.id
        assert by_type["conectar_celula"].prazo is not None
        assert by_type["fonovisita"].consolidacao_id == track.id
        assert by_type["fonovisita"].prazo is None
        assert connection.execute(
            text("""select count(*) from public.consolidacao_etapas
                where igreja_id=:tenant and consolidacao_id=:track and etapa='aceitou_jesus'
                  and concluida"""),
            dict(values, track=track.id),
        ).scalar_one() == 1
        connection.execute(
            text("update public.work_queue_items set status='resolvido' where id=:id"),
            {"id": by_type["fonovisita"].id},
        )
        with pytest.raises(DBAPIError) as duplicate_fonovisita:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into public.work_queue_items(
                        igreja_id,consolidacao_id,tipo,titulo,pessoa_id,status
                    ) values(:tenant,:track,'fonovisita','duplicada',:person,'aberto')"""),
                    dict(values, track=track.id),
                )
        assert duplicate_fonovisita.value.orig.pgcode == "23505"
        replay_person = uuid.uuid4()
        connection.execute(
            text("""insert into public.pessoas(id,igreja_id,telefone)
                values(:person,:tenant,'5500000000008')"""),
            dict(values, person=replay_person),
        )
        with pytest.raises(DBAPIError) as duplicate_decision_origin:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into public.consolidacoes(
                        igreja_id,pessoa_id,origin_decision_id,tipo
                    ) values(:tenant,:person,:decision,'individual')"""),
                    dict(values, person=replay_person, decision=decision_id),
                )
        assert duplicate_decision_origin.value.orig.pgcode == "23505"

    _apply(v3_database, _MIGRATION.read_text())
    with v3_database.begin() as connection:
        direct_person = uuid.uuid4()
        connection.execute(
            text("""insert into public.pessoas(id,igreja_id,telefone)
                values(:person,:tenant,'5500000000007')"""),
            dict(values, person=direct_person),
        )
        direct_track = connection.execute(
            text("""insert into public.consolidacoes(igreja_id,pessoa_id,tipo)
                values(:tenant,:person,'individual') returning id"""),
            dict(values, person=direct_person),
        ).scalar_one()
        assert connection.execute(
            text("""select count(*) from public.work_queue_items
                where igreja_id=:tenant and consolidacao_id=:track and tipo='fonovisita'"""),
            dict(values, track=direct_track),
        ).scalar_one() == 1
    with v3_database.connect() as connection:
        assert connection.execute(
            text("select count(*) from public.work_queue_items where tipo='fonovisita'")
        ).scalar_one() == 2


def test_v3_tenant_foreign_keys_and_origin_decision_source_removal(
    v3_database: Engine,
) -> None:
    _apply(v3_database, _MIGRATION.read_text())
    with v3_database.begin() as connection:
        own = _seed_tenant(connection, clerk_user_id="clerk-own")
        other = _seed_tenant(connection, clerk_user_id="clerk-other")
        own_decision = _insert_decision(connection, own, vinculo="membro")
        other_decision = _insert_decision(connection, other, vinculo="membro")
        own_track = connection.execute(
            text("select id from public.consolidacoes where origin_decision_id=:id"),
            {"id": own_decision},
        ).scalar_one()
        other_track = connection.execute(
            text("select id from public.consolidacoes where origin_decision_id=:id"),
            {"id": other_decision},
        ).scalar_one()
        second_person = uuid.uuid4()
        connection.execute(
            text("""insert into public.pessoas(id,igreja_id,telefone)
                values(:person,:tenant,'5500000000009')"""),
            dict(own, person=second_person),
        )
        with pytest.raises(DBAPIError) as foreign_origin:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into public.consolidacoes(
                        id,igreja_id,pessoa_id,origin_decision_id,tipo
                    ) values(gen_random_uuid(),:tenant,:person,:foreign,'individual')"""),
                    dict(own, person=second_person, foreign=other_decision),
                )
        assert foreign_origin.value.orig.pgcode == "23503"
        with pytest.raises(DBAPIError) as foreign_queue:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into public.work_queue_items(
                        igreja_id,consolidacao_id,tipo,titulo,pessoa_id,status
                    ) values(:tenant,:foreign,'atendimento','fora do tenant',:person,'aberto')"""),
                    dict(own, foreign=other_track),
                )
        assert foreign_queue.value.orig.pgcode == "23503"
        with pytest.raises(DBAPIError) as foreign_outbox:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into public.notification_outbox(
                        igreja_id,pessoa_id,consolidacao_id,origin_kind,origin_id,
                        occurrence_at,origin_fingerprint,purpose,state,due_at,updated_at
                    ) values(:tenant,:person,:foreign,'consolidacao',:foreign,now(),repeat('b',64),
                        'consolidation_connection_open','pendente',now(),now())"""),
                    dict(own, foreign=other_track),
                )
        assert foreign_outbox.value.orig.pgcode == "23503"

        connection.execute(text("delete from public.decisions where id=:id"), {"id": own_decision})
        assert connection.execute(
            text("""select origin_decision_id is null and igreja_id=:tenant
                from public.consolidacoes where id=:track"""),
            dict(own, track=own_track),
        ).scalar_one()


def test_v3_outbox_shape_and_source_removal_preserve_terminal_reservation(
    v3_database: Engine,
) -> None:
    _apply(v3_database, _MIGRATION.read_text())
    with v3_database.begin() as connection:
        values = _seed_tenant(connection)
        decision_id = _insert_decision(connection, values, vinculo="membro")
        track = connection.execute(
            text("select id from public.consolidacoes where origin_decision_id=:id"),
            {"id": decision_id},
        ).scalar_one()
        queue_id = connection.execute(
            text("""select id from public.work_queue_items
                where igreja_id=:tenant and consolidacao_id=:track and tipo='fonovisita'"""),
            dict(values, track=track),
        ).scalar_one()
        outbox_id = _outbox_fonovisita(
            connection, values, consolidacao_id=None, queue_id=queue_id
        )
        with pytest.raises(DBAPIError) as wrong_connection_shape:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into public.notification_outbox(
                        igreja_id,pessoa_id,work_queue_item_id,origin_kind,origin_id,
                        occurrence_at,origin_fingerprint,purpose,state,due_at,updated_at
                    ) values(:tenant,:person,:queue,'work_queue',:queue,now(),repeat('c',64),
                        'consolidation_connection_open','pendente',now(),now())"""),
                    dict(values, queue=queue_id),
                )
        assert wrong_connection_shape.value.orig.pgcode == "23514"
        with pytest.raises(DBAPIError) as wrong_fonovisita_shape:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into public.notification_outbox(
                        igreja_id,pessoa_id,consolidacao_id,origin_kind,origin_id,
                        occurrence_at,origin_fingerprint,purpose,state,due_at,updated_at
                    ) values(:tenant,:person,:track,'consolidacao',:track,now(),repeat('d',64),
                        'consolidation_fonovisita','pendente',now(),now())"""),
                    dict(values, track=track),
                )
        assert wrong_fonovisita_shape.value.orig.pgcode == "23514"
        connection.execute(text("delete from public.consolidacoes where id=:track"), {"track": track})
        assert connection.execute(
            text("select count(*) from public.work_queue_items where id=:queue"),
            {"queue": queue_id},
        ).scalar_one() == 0
        preserved = connection.execute(
            text("""select consolidacao_id is null, work_queue_item_id is null,
                origin_id=:queue, state='ambiguo', delivery_reservation_day=current_date
                from public.notification_outbox where id=:id"""),
            {"id": outbox_id, "queue": queue_id},
        ).one()
        assert preserved == (True, True, True, True, True)


def test_v3_assignment_revision_is_server_managed_and_detects_changes(
    v3_database: Engine,
) -> None:
    _apply(v3_database, _MIGRATION.read_text())
    with v3_database.begin() as connection:
        values = _seed_tenant(connection)
        alternate_user = uuid.uuid4()
        connection.execute(
            text("""insert into public.app_users(id,igreja_id,pessoa_id,clerk_user_id,status)
                values(:id,:tenant,:person,'clerk-alternativo','ativo')"""),
            dict(values, id=alternate_user),
        )
        decision_id = _insert_decision(connection, values, vinculo="membro")
        track = connection.execute(
            text("select id from public.consolidacoes where origin_decision_id=:id"),
            {"id": decision_id},
        ).scalar_one()
        with pytest.raises(DBAPIError) as client_override:
            with connection.begin_nested():
                connection.execute(
                    text("update public.consolidacoes set assignment_revision=99 where id=:id"),
                    {"id": track},
                )
        assert client_override.value.orig.pgcode == "22023"
        connection.execute(
            text("""update public.consolidacoes set responsavel_id=:user,assignment_revision=99
                where id=:track"""),
            {"user": alternate_user, "track": track},
        )
        assert connection.execute(
            text("select assignment_revision from public.consolidacoes where id=:id"),
            {"id": track},
        ).scalar_one() == 1
        connection.execute(
            text("update public.consolidacoes set progresso=1 where id=:id"), {"id": track}
        )
        assert connection.execute(
            text("select assignment_revision from public.consolidacoes where id=:id"),
            {"id": track},
        ).scalar_one() == 1


def test_v3_s3_checks_and_consolidation_preference_are_closed(
    v3_database: Engine,
) -> None:
    _apply(v3_database, _MIGRATION.read_text())
    with v3_database.begin() as connection:
        tenant = _seed_tenant(connection)
        action_targets = (
            ("configurar_lembrete_consolidacao", "pessoa"),
            ("marcar_fonovisita_feita", "pendencia_consolidacao"),
            ("atribuir_consolidacao", "consolidacao"),
        )
        for action, target_kind in action_targets:
            connection.execute(
                text("""insert into public.agent_action_proposals(id,igreja_id,action,target_kind)
                    values(gen_random_uuid(),:tenant,:action,:target)"""),
                dict(tenant, action=action, target=target_kind),
            )
        with pytest.raises(DBAPIError) as wrong_target:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into public.agent_action_proposals(id,igreja_id,action,target_kind)
                        values(gen_random_uuid(),:tenant,'marcar_fonovisita_feita','pessoa')"""),
                    tenant,
                )
        assert wrong_target.value.orig.pgcode == "23514"
        for receipt in (
            "Fonovisita confirmada.",
            "Consolidação atribuída.",
            "Lembretes de consolidação ativados.",
        ):
            connection.execute(
                text("insert into public.agent_action_receipts(id,receipt_text) values(gen_random_uuid(),:receipt)"),
                {"receipt": receipt},
            )
        connection.execute(
            text("""insert into public.whatsapp_reminder_preferences(
                igreja_id,pessoa_id,reminder_kind,state,term_version,accepted_at,changed_at
            ) values(:tenant,:person,'consolidation','active','termo-v3',now(),now())"""),
            tenant,
        )
        with pytest.raises(DBAPIError) as invalid_kind:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into public.whatsapp_reminder_preferences(
                        igreja_id,pessoa_id,reminder_kind,state,term_version,accepted_at,changed_at
                    ) values(:tenant,:person,'arbitrario','active','termo-v3-2',now(),now())"""),
                    tenant,
                )
        assert invalid_kind.value.orig.pgcode == "23514"


def test_v3_activation_is_worker_only_tenant_scoped_and_never_backfilled(
    v3_database: Engine,
) -> None:
    _apply(v3_database, _MIGRATION.read_text())
    with v3_database.begin() as connection:
        own = _seed_tenant(connection, clerk_user_id="clerk-own")
        other = _seed_tenant(connection, clerk_user_id="clerk-other")
        assert connection.execute(
            text("select count(*) from public.consolidation_whatsapp_activation")
        ).scalar_one() == 0

    with v3_database.begin() as connection:
        _worker(connection, own["tenant"])
        connection.execute(
            text("""insert into public.consolidation_whatsapp_activation(
                igreja_id,activated_at,gate_open
            ) values(:tenant,transaction_timestamp(),true)"""),
            own,
        )
        assert connection.execute(
            text("select gate_open and activated_at is not null from public.consolidation_whatsapp_activation")
        ).scalar_one()
        assert connection.execute(
            text("""update public.consolidation_whatsapp_activation
                set gate_open=false where igreja_id=:tenant"""),
            own,
        ).rowcount == 1
        assert connection.execute(
            text("""update public.consolidation_whatsapp_activation
                set gate_open=true, activated_at=clock_timestamp()
                where igreja_id=:tenant"""),
            own,
        ).rowcount == 1
        with pytest.raises(DBAPIError) as active_without_cutover:
            with connection.begin_nested():
                connection.execute(
                    text("""update public.consolidation_whatsapp_activation
                        set activated_at=null where igreja_id=:tenant"""),
                    own,
                )
        assert active_without_cutover.value.orig.pgcode == "23514"
        assert connection.execute(
            text("select count(*) from public.consolidation_whatsapp_activation where igreja_id=:tenant"),
            other,
        ).scalar_one() == 0
        with pytest.raises(DBAPIError) as cross_tenant_write:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into public.consolidation_whatsapp_activation(
                        igreja_id,activated_at,gate_open
                    ) values(:tenant,transaction_timestamp(),true)"""),
                    other,
                )
        assert cross_tenant_write.value.orig.pgcode == "42501"
        with pytest.raises(DBAPIError) as delete_denied:
            with connection.begin_nested():
                connection.execute(
                    text("delete from public.consolidation_whatsapp_activation where igreja_id=:tenant"),
                    own,
                )
        assert delete_denied.value.orig.pgcode == "42501"

    with v3_database.begin() as connection:
        _human(connection, own["tenant"], "clerk-own")
        assert connection.execute(
            text("select count(*) from public.consolidation_whatsapp_activation")
        ).scalar_one() == 0
        with pytest.raises(DBAPIError) as human_insert:
            with connection.begin_nested():
                connection.execute(
                    text("""insert into public.consolidation_whatsapp_activation(
                        igreja_id,activated_at,gate_open
                    ) values(:tenant,transaction_timestamp(),true)"""),
                    own,
                )
        assert human_insert.value.orig.pgcode == "42501"


@pytest.mark.parametrize("transition", ["open", "closing", "closed", "backdated_reopen"])
def test_v3_activation_rejects_cutover_rewrite(v3_database: Engine, transition: str) -> None:
    _apply(v3_database, _MIGRATION.read_text())
    with v3_database.begin() as connection:
        own = _seed_tenant(connection)
        _worker(connection, own["tenant"])
        connection.execute(text("""insert into public.consolidation_whatsapp_activation
            (igreja_id,activated_at,gate_open) values(:tenant,now(),true)"""), own)
        if transition in {"closed", "backdated_reopen"}:
            connection.execute(text("""update public.consolidation_whatsapp_activation
                set gate_open=false where igreja_id=:tenant"""), own)
        clauses = {
            "open": "activated_at=activated_at + interval '1 hour'",
            "closing": "gate_open=false, activated_at=null",
            "closed": "activated_at=activated_at + interval '1 hour'",
            "backdated_reopen": "gate_open=true, activated_at=activated_at - interval '1 hour'",
        }
        with pytest.raises(DBAPIError) as rejected:
            with connection.begin_nested():
                connection.execute(text("update public.consolidation_whatsapp_activation set "
                    + clauses[transition] + " where igreja_id=:tenant"), own)
        assert rejected.value.orig.pgcode == "23514"


def test_v3_activation_reopens_with_later_cutover_across_transactions(v3_database: Engine) -> None:
    _apply(v3_database, _MIGRATION.read_text())
    with v3_database.begin() as connection:
        own = _seed_tenant(connection)
        _worker(connection, own["tenant"])
        initial = connection.execute(text("""insert into public.consolidation_whatsapp_activation
            (igreja_id,activated_at,gate_open) values(:tenant,clock_timestamp(),true)
            returning activated_at"""), own).scalar_one()
    with v3_database.begin() as connection:
        _worker(connection, own["tenant"])
        closed = connection.execute(text("""update public.consolidation_whatsapp_activation
            set gate_open=false where igreja_id=:tenant returning activated_at"""), own).scalar_one()
        assert closed == initial
    with v3_database.begin() as connection:
        _worker(connection, own["tenant"])
        reopened = connection.execute(text("""update public.consolidation_whatsapp_activation
            set gate_open=true, activated_at=clock_timestamp()
            where igreja_id=:tenant returning activated_at"""), own).scalar_one()
        assert reopened > initial


def test_v3_fonovisita_outbox_rejects_redundant_parent_from_other_consolidation(v3_database: Engine) -> None:
    _apply(v3_database, _MIGRATION.read_text())
    with v3_database.begin() as connection:
        own = _seed_tenant(connection)
        first = _insert_decision(connection, own)
        connection.execute(text("update public.consolidacoes set concluida=true where origin_decision_id=:id"), {"id": first})
        second = _insert_decision(connection, own)
        queue = connection.execute(text("""select w.id from public.work_queue_items w
            join public.consolidacoes c on c.id=w.consolidacao_id
            where c.origin_decision_id=:id and w.tipo='fonovisita'"""), {"id": first}).scalar_one()
        wrong_parent = connection.execute(text("select id from public.consolidacoes where origin_decision_id=:id"),
            {"id": second}).scalar_one()
        with pytest.raises(DBAPIError) as rejected:
            with connection.begin_nested():
                _outbox_fonovisita(connection, own, consolidacao_id=wrong_parent, queue_id=queue)
        assert rejected.value.orig.pgcode == "23514"


@pytest.mark.parametrize("purpose", ["consolidation_connection_open", "consolidation_connection_deadline"])
def test_v3_connection_source_removal_preserves_terminal_reservation(v3_database: Engine, purpose: str) -> None:
    _apply(v3_database, _MIGRATION.read_text())
    with v3_database.begin() as connection:
        own = _seed_tenant(connection)
        decision_id = _insert_decision(connection, own)
        track_id = connection.execute(text("select id from public.consolidacoes where origin_decision_id=:id"),
            {"id": decision_id}).scalar_one()
        outbox_id = connection.execute(text("""insert into public.notification_outbox(
            igreja_id,pessoa_id,consolidacao_id,origin_kind,origin_id,occurrence_at,
            origin_fingerprint,purpose,state,due_at,delivery_reservation_day,updated_at
        ) values(:tenant,:person,:track,'consolidacao',:track,now(),repeat('f',64),
            :purpose,'ambiguo',now(),current_date,now()) returning id"""),
            dict(own, track=track_id, purpose=purpose)).scalar_one()
        connection.execute(text("delete from public.consolidacoes where id=:id"), {"id": track_id})
        preserved = connection.execute(text("""select consolidacao_id is null,
            origin_id=:track, state='ambiguo', delivery_reservation_day=current_date
            from public.notification_outbox where id=:id"""),
            {"track": track_id, "id": outbox_id}).one()
        assert preserved == (True, True, True, True)
