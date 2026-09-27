-- V1a relatório de célula por WhatsApp: coleção privada, outbox e orçamento.
-- A migration é aditiva. Ações S3 já existentes ganham somente o terceiro
-- catálogo fechado; confirmação/TTL continuam na mesma proposal S3.

begin;
set local lock_timeout = '2s';

alter table public.agent_action_proposals
  drop constraint if exists agent_action_proposals_action_closed,
  drop constraint if exists agent_action_proposals_target_kind_closed;
alter table public.agent_action_proposals
  add constraint agent_action_proposals_action_closed
    check (action in ('registrar_decisao', 'marcar_presenca',
                      'enviar_relatorio_celula')),
  add constraint agent_action_proposals_target_kind_closed
    check (
      (action in ('registrar_decisao', 'marcar_presenca') and target_kind = 'pessoa')
      or (action = 'enviar_relatorio_celula' and target_kind = 'reuniao')
    );

alter table public.agent_action_receipts
  drop constraint if exists agent_action_receipts_receipt_text_closed;
alter table public.agent_action_receipts
  add constraint agent_action_receipts_receipt_text_closed
    check (receipt_text in ('Registro confirmado.', 'Relatório confirmado.'));

-- The legacy meeting primary key is global, but V1a references it through the
-- tenant boundary.  The pair is intentionally unique so a known UUID from a
-- different tenant cannot satisfy either private child foreign key.
do $$
begin
  if not exists (
    select 1
    from pg_catalog.pg_constraint
    where conrelid = 'public.celula_reuniao'::regclass
      and conname = 'celula_reuniao_igreja_id_id_key'
      and contype = 'u'
  ) then
    alter table public.celula_reuniao
      add constraint celula_reuniao_igreja_id_id_key unique (igreja_id, id);
  end if;
end
$$;

create table if not exists public.cell_report_drafts (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  conversation_id uuid not null,
  reuniao_id uuid not null,
  actor_pessoa_id uuid not null,
  source_message_id uuid not null,
  state text not null,
  revision integer not null,
  candidate_json jsonb,
  candidate_sha256 text,
  started_at timestamptz not null,
  expires_at timestamptz not null,
  updated_at timestamptz not null,
  terminal_at timestamptz,
  content_purged_at timestamptz,
  constraint cell_report_drafts_tenant_id_key unique (igreja_id, id),
  constraint cell_report_drafts_source_once_key unique (igreja_id, source_message_id),
  constraint cell_report_drafts_tenant_conversation_fkey
    foreign key (igreja_id, conversation_id)
    references public.conversations (igreja_id, id) on delete cascade,
  constraint cell_report_drafts_tenant_actor_pessoa_fkey
    foreign key (igreja_id, actor_pessoa_id)
    references public.pessoas (igreja_id, id) on delete cascade,
  constraint cell_report_drafts_source_anchor_fkey
    foreign key (igreja_id, conversation_id, source_message_id)
    references public.messages (igreja_id, conversation_id, id) on delete cascade,
  constraint cell_report_drafts_reuniao_fkey
    foreign key (igreja_id, reuniao_id)
    references public.celula_reuniao (igreja_id, id) on delete cascade,
  constraint cell_report_drafts_state_closed
    check (state in ('coletando', 'pronto', 'concluido', 'cancelado', 'expirado')),
  constraint cell_report_drafts_revision_positive check (revision > 0),
  constraint cell_report_drafts_candidate_object_chk
    check (candidate_json is null or jsonb_typeof(candidate_json) = 'object'),
  constraint cell_report_drafts_candidate_digest_shape
    check (candidate_sha256 is null or candidate_sha256 ~ '^[0-9a-f]{64}$'),
  constraint cell_report_drafts_expiry_window
    check (expires_at > started_at and expires_at <= started_at + interval '24 hours')
);

create unique index if not exists cell_report_drafts_one_active_conversation_idx
  on public.cell_report_drafts (igreja_id, conversation_id)
  where state in ('coletando', 'pronto');
create index if not exists cell_report_drafts_reuniao_state_idx
  on public.cell_report_drafts (igreja_id, reuniao_id, state);

create table if not exists public.cell_report_reminder_preferences (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  pessoa_id uuid not null,
  disabled_at timestamptz not null,
  updated_at timestamptz not null,
  constraint cell_report_reminder_preferences_once_key unique (igreja_id, pessoa_id),
  constraint cell_report_reminder_preferences_tenant_pessoa_fkey
    foreign key (igreja_id, pessoa_id)
    references public.pessoas (igreja_id, id) on delete cascade
);

create table if not exists public.cell_report_reminders (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  reuniao_id uuid not null,
  leader_pessoa_id uuid not null,
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
  updated_at timestamptz not null,
  constraint cell_report_reminders_tenant_id_key unique (igreja_id, id),
  constraint cell_report_reminders_meeting_leader_once_key
    unique (igreja_id, reuniao_id, leader_pessoa_id),
  constraint cell_report_reminders_tenant_leader_fkey
    foreign key (igreja_id, leader_pessoa_id)
    references public.pessoas (igreja_id, id) on delete cascade,
  constraint cell_report_reminders_reuniao_fkey
    foreign key (igreja_id, reuniao_id)
    references public.celula_reuniao (igreja_id, id) on delete cascade,
  constraint cell_report_reminders_state_closed
    check (state in ('pendente', 'em_envio', 'retry', 'enviado', 'ambiguo',
                     'cancelado', 'obsoleto')),
  constraint cell_report_reminders_attempts_range check (attempts >= 0 and attempts <= 2),
  constraint cell_report_reminders_text_digest_shape
    check (text_sha256 ~ '^[0-9a-f]{64}$')
);

create index if not exists cell_report_reminders_due_idx
  on public.cell_report_reminders (igreja_id, state, due_at);
create index if not exists cell_report_reminders_leader_created_idx
  on public.cell_report_reminders (igreja_id, leader_pessoa_id, created_at);

create table if not exists public.cell_report_ai_daily_budgets (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  budget_day date not null,
  cost_version text not null,
  reserved_microusd bigint not null,
  settled_microusd bigint not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null,
  constraint cell_report_ai_daily_budgets_tenant_id_key unique (igreja_id, id),
  constraint cell_report_ai_daily_budgets_once_key unique (igreja_id, budget_day),
  constraint cell_report_ai_daily_budgets_igreja_fkey
    foreign key (igreja_id) references public.igrejas (id) on delete cascade,
  constraint cell_report_ai_daily_budgets_totals_nonnegative
    check (reserved_microusd >= 0 and settled_microusd >= 0)
);

create table if not exists public.cell_report_ai_reservations (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  draft_id uuid not null,
  budget_id uuid not null,
  call_number integer not null,
  budget_day date not null,
  cost_version text not null,
  state text not null,
  estimated_microusd bigint not null,
  actual_microusd bigint,
  created_at timestamptz not null,
  settled_at timestamptz,
  constraint cell_report_ai_reservations_tenant_id_key unique (igreja_id, id),
  constraint cell_report_ai_reservations_draft_call_once_key
    unique (igreja_id, draft_id, call_number),
  constraint cell_report_ai_reservations_tenant_draft_fkey
    foreign key (igreja_id, draft_id)
    references public.cell_report_drafts (igreja_id, id) on delete cascade,
  constraint cell_report_ai_reservations_tenant_budget_fkey
    foreign key (igreja_id, budget_id)
    references public.cell_report_ai_daily_budgets (igreja_id, id) on delete cascade,
  constraint cell_report_ai_reservations_state_closed
    check (state in ('reservada', 'liquidada', 'cancelada')),
  constraint cell_report_ai_reservations_call_number_range
    check (call_number >= 1 and call_number <= 4),
  constraint cell_report_ai_reservations_cost_nonnegative
    check (estimated_microusd > 0 and (actual_microusd is null or actual_microusd >= 0))
);

create index if not exists cell_report_ai_reservations_daily_idx
  on public.cell_report_ai_reservations (igreja_id, budget_day, state);

alter table public.cell_report_drafts enable row level security;
alter table public.cell_report_drafts force row level security;
alter table public.cell_report_reminder_preferences enable row level security;
alter table public.cell_report_reminder_preferences force row level security;
alter table public.cell_report_reminders enable row level security;
alter table public.cell_report_reminders force row level security;
alter table public.cell_report_ai_daily_budgets enable row level security;
alter table public.cell_report_ai_daily_budgets force row level security;
alter table public.cell_report_ai_reservations enable row level security;
alter table public.cell_report_ai_reservations force row level security;

drop policy if exists cell_report_drafts_worker_only on public.cell_report_drafts;
create policy cell_report_drafts_worker_only on public.cell_report_drafts
  for all to authenticated
  using (
    igreja_id = public.current_igreja_id()
    and nullif(coalesce(
      nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)
    ), '') is null
  )
  with check (
    igreja_id = public.current_igreja_id()
    and nullif(coalesce(
      nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)
    ), '') is null
  );

drop policy if exists cell_report_reminder_preferences_worker_only on public.cell_report_reminder_preferences;
create policy cell_report_reminder_preferences_worker_only on public.cell_report_reminder_preferences
  for all to authenticated
  using (igreja_id = public.current_igreja_id()
    and nullif(coalesce(nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)), '') is null)
  with check (igreja_id = public.current_igreja_id()
    and nullif(coalesce(nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)), '') is null);

drop policy if exists cell_report_reminders_worker_only on public.cell_report_reminders;
create policy cell_report_reminders_worker_only on public.cell_report_reminders
  for all to authenticated
  using (igreja_id = public.current_igreja_id()
    and nullif(coalesce(nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)), '') is null)
  with check (igreja_id = public.current_igreja_id()
    and nullif(coalesce(nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)), '') is null);

drop policy if exists cell_report_ai_daily_budgets_worker_only on public.cell_report_ai_daily_budgets;
create policy cell_report_ai_daily_budgets_worker_only on public.cell_report_ai_daily_budgets
  for all to authenticated
  using (igreja_id = public.current_igreja_id()
    and nullif(coalesce(nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)), '') is null)
  with check (igreja_id = public.current_igreja_id()
    and nullif(coalesce(nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)), '') is null);

drop policy if exists cell_report_ai_reservations_worker_only on public.cell_report_ai_reservations;
create policy cell_report_ai_reservations_worker_only on public.cell_report_ai_reservations
  for all to authenticated
  using (igreja_id = public.current_igreja_id()
    and nullif(coalesce(nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)), '') is null)
  with check (igreja_id = public.current_igreja_id()
    and nullif(coalesce(nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)), '') is null);

revoke all privileges on table public.cell_report_drafts,
  public.cell_report_reminder_preferences, public.cell_report_reminders,
  public.cell_report_ai_daily_budgets, public.cell_report_ai_reservations from public;

do $v1a_acl$
declare
  target_role text;
begin
  foreach target_role in array array['anon', 'service_role', 'agent_runtime'] loop
    if pg_catalog.to_regrole(target_role) is not null then
      execute format(
        'revoke all privileges on table public.cell_report_drafts, public.cell_report_reminder_preferences, public.cell_report_reminders, public.cell_report_ai_daily_budgets, public.cell_report_ai_reservations from %I',
        target_role
      );
    end if;
  end loop;
  if pg_catalog.to_regrole('authenticated') is not null then
    execute 'grant select, insert, update, delete on table public.cell_report_drafts, public.cell_report_reminder_preferences, public.cell_report_reminders, public.cell_report_ai_daily_budgets, public.cell_report_ai_reservations to authenticated';
  end if;
end
$v1a_acl$;

do $v1a_rls$
declare
  target_table regclass;
begin
  foreach target_table in array array[
    'public.cell_report_drafts'::regclass,
    'public.cell_report_reminder_preferences'::regclass,
    'public.cell_report_reminders'::regclass,
    'public.cell_report_ai_daily_budgets'::regclass,
    'public.cell_report_ai_reservations'::regclass,
    'public.messages'::regclass
  ] loop
    if not (select relrowsecurity from pg_catalog.pg_class where oid = target_table) then
      raise exception 'RLS desligada para %', target_table;
    end if;
  end loop;
  if not exists (
    select 1 from pg_catalog.pg_policy
    where polrelid = 'public.messages'::regclass
      and polname = 'tenant_isolation' and polcmd = '*'
  ) then
    raise exception 'policy tenant_isolation ausente em messages';
  end if;
end
$v1a_rls$;

-- Rollback manual depois de desligar o fluxo V1a e drenar intenções ativas.
-- Revogue os grants antes dos DROPs; receipts/proposals S3 e relatórios já
-- confirmados não são compensados. Ordem segura: reservas, budget, reminders,
-- preferências, rascunhos, chave composta de reunião; então restabeleça os
-- checks S3 anteriores.
-- revoke all privileges on table public.cell_report_ai_reservations,
--   public.cell_report_ai_daily_budgets, public.cell_report_reminders,
--   public.cell_report_reminder_preferences, public.cell_report_drafts from authenticated;
-- drop table public.cell_report_ai_reservations;
-- drop table public.cell_report_ai_daily_budgets;
-- drop table public.cell_report_reminders;
-- drop table public.cell_report_reminder_preferences;
-- drop table public.cell_report_drafts;
-- alter table public.celula_reuniao
--   drop constraint if exists celula_reuniao_igreja_id_id_key;
-- alter table public.agent_action_receipts
--   drop constraint if exists agent_action_receipts_receipt_text_closed,
--   add constraint agent_action_receipts_receipt_text_closed
--     check (receipt_text = 'Registro confirmado.');
-- alter table public.agent_action_proposals
--   drop constraint if exists agent_action_proposals_action_closed,
--   drop constraint if exists agent_action_proposals_target_kind_closed,
--   add constraint agent_action_proposals_action_closed
--     check (action in ('registrar_decisao', 'marcar_presenca')),
--   add constraint agent_action_proposals_target_kind_closed
--     check (target_kind = 'pessoa');

commit;
