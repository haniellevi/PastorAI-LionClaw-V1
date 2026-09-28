-- V1b: durable, private audio intake for the WhatsApp cell-report flow.
-- New relations only.  Existing S3 and V1a migrations remain immutable.

begin;

set local lock_timeout = '2s';

create table if not exists public.cell_report_audio_notices (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  pessoa_id uuid not null,
  conversation_id uuid not null,
  notice_message_id uuid not null,
  version text not null,
  state text not null,
  created_at timestamptz not null,
  delivered_at timestamptz,
  terminal_at timestamptz,
  constraint cell_report_audio_notices_tenant_id_key unique (igreja_id, id),
  constraint cell_report_audio_notices_message_once_key
    unique (igreja_id, notice_message_id),
  constraint cell_report_audio_notices_tenant_pessoa_fkey
    foreign key (igreja_id, pessoa_id)
    references public.pessoas (igreja_id, id) on delete cascade,
  constraint cell_report_audio_notices_tenant_conversation_fkey
    foreign key (igreja_id, conversation_id)
    references public.conversations (igreja_id, id) on delete cascade,
  constraint cell_report_audio_notices_message_anchor_fkey
    foreign key (igreja_id, conversation_id, notice_message_id)
    references public.messages (igreja_id, conversation_id, id) on delete cascade,
  constraint cell_report_audio_notices_state_closed
    check (state in ('preparado', 'entregue', 'cancelado')),
  constraint cell_report_audio_notices_version_bounded
    check (length(version) > 0 and length(version) <= 64),
  constraint cell_report_audio_notices_delivery_state_chk
    check ((state = 'entregue') = (delivered_at is not null))
);

create index if not exists cell_report_audio_notices_pessoa_version_idx
  on public.cell_report_audio_notices (igreja_id, pessoa_id, version, delivered_at);

create table if not exists public.cell_report_audio_consent_events (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  pessoa_id uuid not null,
  conversation_id uuid not null,
  source_message_id uuid not null,
  notice_id uuid,
  command text not null,
  version text not null,
  occurred_at timestamptz not null,
  constraint cell_report_audio_consent_events_tenant_id_key unique (igreja_id, id),
  constraint cell_report_audio_consent_events_source_once_key
    unique (igreja_id, source_message_id),
  constraint cell_report_audio_consent_events_tenant_pessoa_fkey
    foreign key (igreja_id, pessoa_id)
    references public.pessoas (igreja_id, id) on delete cascade,
  constraint cell_report_audio_consent_events_tenant_conversation_fkey
    foreign key (igreja_id, conversation_id)
    references public.conversations (igreja_id, id) on delete cascade,
  constraint cell_report_audio_consent_events_source_anchor_fkey
    foreign key (igreja_id, conversation_id, source_message_id)
    references public.messages (igreja_id, conversation_id, id) on delete cascade,
  constraint cell_report_audio_consent_events_notice_fkey
    foreign key (igreja_id, notice_id)
    references public.cell_report_audio_notices (igreja_id, id) on delete cascade,
  constraint cell_report_audio_consent_events_command_closed
    check (command in ('aceito', 'revogado')),
  constraint cell_report_audio_consent_events_version_bounded
    check (length(version) > 0 and length(version) <= 64),
  constraint cell_report_audio_consent_events_notice_required
    check (
      (command = 'aceito' and notice_id is not null)
      or (command = 'revogado' and notice_id is null)
    )
);

create index if not exists cell_report_audio_consent_events_latest_idx
  on public.cell_report_audio_consent_events (igreja_id, pessoa_id, occurred_at, id);

create table if not exists public.cell_report_audio_inputs (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  conversation_id uuid not null,
  pessoa_id uuid not null,
  inbound_message_id uuid not null,
  live_conversation_id uuid,
  live_pessoa_id uuid,
  live_message_id uuid,
  provider_message_sha256 text not null,
  storage_path text not null,
  declared_mime text,
  measured_mime text,
  byte_size integer,
  duration_seconds numeric(8,3),
  content_sha256 text,
  consent_version text,
  consent_event_id uuid,
  state text not null,
  lease_token uuid,
  lease_until timestamptz,
  transcription_attempts integer not null,
  external_started_at timestamptz,
  transcript_text text,
  transcript_sha256 text,
  transcribed_at timestamptz,
  terminal_reason text,
  terminal_at timestamptz,
  purge_state text not null,
  purge_attempts integer not null,
  purge_error_code text,
  content_purged_at timestamptz,
  received_at timestamptz not null,
  expires_at timestamptz not null,
  updated_at timestamptz not null,
  constraint cell_report_audio_inputs_tenant_id_key unique (igreja_id, id),
  constraint cell_report_audio_inputs_inbound_once_key
    unique (igreja_id, inbound_message_id),
  constraint cell_report_audio_inputs_provider_once_key
    unique (igreja_id, provider_message_sha256),
  constraint cell_report_audio_inputs_igreja_fkey
    foreign key (igreja_id) references public.igrejas (id) on delete cascade,
  constraint cell_report_audio_inputs_live_pessoa_fkey
    foreign key (igreja_id, live_pessoa_id)
    references public.pessoas (igreja_id, id) on delete set null (live_pessoa_id),
  constraint cell_report_audio_inputs_live_conversation_fkey
    foreign key (igreja_id, live_conversation_id)
    references public.conversations (igreja_id, id) on delete set null (live_conversation_id),
  constraint cell_report_audio_inputs_live_message_fkey
    foreign key (igreja_id, live_conversation_id, live_message_id)
    references public.messages (igreja_id, conversation_id, id)
    on delete set null (live_message_id),
  constraint cell_report_audio_inputs_state_closed
    check (state in ('aguardando_aceite', 'pendente', 'processando',
                     'transcrita', 'ambigua', 'cancelada', 'purgada')),
  constraint cell_report_audio_inputs_purge_state_closed
    check (purge_state in ('ativa', 'pendente', 'purgada')),
  constraint cell_report_audio_inputs_provider_digest_shape
    check (provider_message_sha256 ~ '^[0-9a-f]{64}$'),
  constraint cell_report_audio_inputs_content_digest_shape
    check (content_sha256 is null or content_sha256 ~ '^[0-9a-f]{64}$'),
  constraint cell_report_audio_inputs_expiry_window
    check (expires_at > received_at and expires_at <= received_at + interval '24 hours'),
  constraint cell_report_audio_inputs_one_transcription_chk
    check (transcription_attempts >= 0 and transcription_attempts <= 1),
  constraint cell_report_audio_inputs_purge_attempts_nonnegative
    check (purge_attempts >= 0)
);

do $v1b_audio_input_provider_once$
declare
  actual_definition text;
begin
  select pg_catalog.pg_get_constraintdef(constraint_row.oid, true)
    into actual_definition
  from pg_catalog.pg_constraint constraint_row
  where constraint_row.conrelid = 'public.cell_report_audio_inputs'::regclass
    and constraint_row.conname = 'cell_report_audio_inputs_provider_once_key';

  if actual_definition is null then
    alter table public.cell_report_audio_inputs
      add constraint cell_report_audio_inputs_provider_once_key
      unique (igreja_id, provider_message_sha256);
  elsif actual_definition <> 'UNIQUE (igreja_id, provider_message_sha256)' then
    raise exception 'unicidade de áudio V1b por provider divergente';
  end if;
end
$v1b_audio_input_provider_once$;

create index if not exists cell_report_audio_inputs_claim_idx
  on public.cell_report_audio_inputs (igreja_id, state, expires_at, received_at);
create index if not exists cell_report_audio_inputs_purge_idx
  on public.cell_report_audio_inputs (igreja_id, purge_state, expires_at, received_at);

create table if not exists public.cell_report_audio_reservations (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  audio_input_id uuid not null,
  reuniao_id uuid not null,
  budget_id uuid not null,
  audio_number integer not null,
  budget_day date not null,
  cost_version text not null,
  state text not null,
  estimated_microusd bigint not null,
  actual_microusd bigint,
  created_at timestamptz not null,
  settled_at timestamptz,
  constraint cell_report_audio_reservations_tenant_id_key unique (igreja_id, id),
  constraint cell_report_audio_reservations_input_once_key
    unique (igreja_id, audio_input_id),
  constraint cell_report_audio_reservations_meeting_audio_number_key
    unique (igreja_id, reuniao_id, audio_number),
  constraint cell_report_audio_reservations_tenant_input_fkey
    foreign key (igreja_id, audio_input_id)
    references public.cell_report_audio_inputs (igreja_id, id) on delete cascade,
  constraint cell_report_audio_reservations_tenant_meeting_fkey
    foreign key (igreja_id, reuniao_id)
    references public.celula_reuniao (igreja_id, id) on delete cascade,
  constraint cell_report_audio_reservations_tenant_budget_fkey
    foreign key (igreja_id, budget_id)
    references public.cell_report_ai_daily_budgets (igreja_id, id) on delete cascade,
  constraint cell_report_audio_reservations_state_closed
    check (state in ('reservada', 'liquidada', 'cancelada')),
  constraint cell_report_audio_reservations_audio_number_range
    check (audio_number >= 1 and audio_number <= 3),
  constraint cell_report_audio_reservations_cost_nonnegative
    check (estimated_microusd > 0 and (actual_microusd is null or actual_microusd >= 0))
);

do $v1b_audio_reservation_number$
declare
  actual_definition text;
begin
  select pg_catalog.pg_get_constraintdef(constraint_row.oid, true)
    into actual_definition
  from pg_catalog.pg_constraint constraint_row
  where constraint_row.conrelid = 'public.cell_report_audio_reservations'::regclass
    and constraint_row.conname = 'cell_report_audio_reservations_meeting_audio_number_key';

  if actual_definition is null then
    alter table public.cell_report_audio_reservations
      add constraint cell_report_audio_reservations_meeting_audio_number_key
      unique (igreja_id, reuniao_id, audio_number);
  elsif actual_definition <> 'UNIQUE (igreja_id, reuniao_id, audio_number)' then
    raise exception 'unicidade de número de áudio V1b divergente';
  end if;
end
$v1b_audio_reservation_number$;

create index if not exists cell_report_audio_reservations_meeting_idx
  on public.cell_report_audio_reservations (igreja_id, reuniao_id, state);

alter table public.cell_report_audio_notices enable row level security;
alter table public.cell_report_audio_notices force row level security;
alter table public.cell_report_audio_consent_events enable row level security;
alter table public.cell_report_audio_consent_events force row level security;
alter table public.cell_report_audio_inputs enable row level security;
alter table public.cell_report_audio_inputs force row level security;
alter table public.cell_report_audio_reservations enable row level security;
alter table public.cell_report_audio_reservations force row level security;

drop policy if exists cell_report_audio_notices_worker_only on public.cell_report_audio_notices;
create policy cell_report_audio_notices_worker_only on public.cell_report_audio_notices
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

drop policy if exists cell_report_audio_consent_events_worker_only on public.cell_report_audio_consent_events;
create policy cell_report_audio_consent_events_worker_only on public.cell_report_audio_consent_events
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

drop policy if exists cell_report_audio_inputs_worker_only on public.cell_report_audio_inputs;
create policy cell_report_audio_inputs_worker_only on public.cell_report_audio_inputs
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

drop policy if exists cell_report_audio_reservations_worker_only on public.cell_report_audio_reservations;
create policy cell_report_audio_reservations_worker_only on public.cell_report_audio_reservations
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

revoke all privileges on table public.cell_report_audio_notices,
  public.cell_report_audio_consent_events, public.cell_report_audio_inputs,
  public.cell_report_audio_reservations from public;

do $v1b_audio_acl$
declare
  target_role text;
begin
  foreach target_role in array array['anon', 'service_role', 'agent_runtime'] loop
    if pg_catalog.to_regrole(target_role) is not null then
      execute format(
        'revoke all privileges on table public.cell_report_audio_notices, public.cell_report_audio_consent_events, public.cell_report_audio_inputs, public.cell_report_audio_reservations from %I',
        target_role
      );
    end if;
  end loop;
  if pg_catalog.to_regrole('authenticated') is not null then
    execute 'revoke delete on table public.cell_report_audio_notices, public.cell_report_audio_consent_events, public.cell_report_audio_inputs, public.cell_report_audio_reservations from authenticated';
    execute 'grant select, insert, update on table public.cell_report_audio_notices, public.cell_report_audio_consent_events, public.cell_report_audio_inputs, public.cell_report_audio_reservations to authenticated';
    if pg_catalog.has_table_privilege('authenticated', 'public.cell_report_audio_notices', 'delete')
      or pg_catalog.has_table_privilege('authenticated', 'public.cell_report_audio_consent_events', 'delete')
      or pg_catalog.has_table_privilege('authenticated', 'public.cell_report_audio_inputs', 'delete')
      or pg_catalog.has_table_privilege('authenticated', 'public.cell_report_audio_reservations', 'delete') then
      raise exception 'DELETE permanece concedido em tabela V1b áudio';
    end if;
  end if;
end
$v1b_audio_acl$;

do $v1b_audio_rls$
declare
  target_table regclass;
begin
  foreach target_table in array array[
    'public.cell_report_audio_notices'::regclass,
    'public.cell_report_audio_consent_events'::regclass,
    'public.cell_report_audio_inputs'::regclass,
    'public.cell_report_audio_reservations'::regclass
  ] loop
    if not (select relrowsecurity from pg_catalog.pg_class where oid = target_table) then
      raise exception 'RLS desligada para %', target_table;
    end if;
  end loop;
end
$v1b_audio_rls$;

-- Rollback manual somente após desligar V1b e drenar purgas pendentes.  Revogue
-- privilégios antes dos DROPs. Não apague relatório oficial nem tabelas S3/V1a.
-- revoke all privileges on table public.cell_report_audio_reservations,
--   public.cell_report_audio_inputs, public.cell_report_audio_consent_events,
--   public.cell_report_audio_notices from authenticated;
-- drop table public.cell_report_audio_reservations;
-- drop table public.cell_report_audio_inputs;
-- drop table public.cell_report_audio_consent_events;
-- drop table public.cell_report_audio_notices;

commit;
