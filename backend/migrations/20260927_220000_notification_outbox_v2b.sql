-- V2b: agenda, EVT-7 e V1a passam a usar uma única outbox durável.
--
-- Corte: esta migration não reencaminha histórico. Linhas V1a pendentes ou
-- retry são terminalizadas; uma linha em transporte fica ambígua. Eventos
-- EVT-7 históricos ganham marcador de fence separado do recibo. O gatilho
-- compatível impede que processos legados reativem consumo sem lançar erro.

begin;
set local lock_timeout = '2s';

-- S3 continua sendo a única confirmação de alto impacto. A nova ação só
-- aceita evento como alvo e o receipt não carrega conteúdo da Agenda.
alter table public.agent_action_proposals
  drop constraint if exists agent_action_proposals_action_closed,
  drop constraint if exists agent_action_proposals_target_kind_closed;
alter table public.agent_action_proposals
  add constraint agent_action_proposals_action_closed
    check (action in ('registrar_decisao', 'marcar_presenca',
                      'enviar_relatorio_celula', 'configurar_lembrete_agenda')),
  add constraint agent_action_proposals_target_kind_closed
    check (
      (action in ('registrar_decisao', 'marcar_presenca') and target_kind = 'pessoa')
      or (action = 'enviar_relatorio_celula' and target_kind = 'reuniao')
      or (action = 'configurar_lembrete_agenda' and target_kind = 'evento')
    );

alter table public.agent_action_receipts
  drop constraint if exists agent_action_receipts_receipt_text_closed;
alter table public.agent_action_receipts
  add constraint agent_action_receipts_receipt_text_closed
    check (receipt_text in ('Registro confirmado.', 'Relatório confirmado.',
                            'Lembrete confirmado.'));

-- Composite tenant keys support every V2b FK. The primary keys remain intact
-- for legacy paths that still address rows only by id.
alter table public.agenda_alert_recipients
  add column if not exists pessoa_id uuid;

do $keys$
begin
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.events'::regclass
      and conname = 'events_igreja_id_id_key' and contype = 'u'
  ) then
    alter table public.events
      add constraint events_igreja_id_id_key unique (igreja_id, id);
  end if;
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.agenda_alert_recipients'::regclass
      and conname = 'agenda_alert_recipients_tenant_id_key' and contype = 'u'
  ) then
    alter table public.agenda_alert_recipients
      add constraint agenda_alert_recipients_tenant_id_key unique (igreja_id, id);
  end if;
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.agenda_alert_recipients'::regclass
      and conname = 'agenda_alert_recipients_tenant_pessoa_fkey' and contype = 'f'
  ) then
    alter table public.agenda_alert_recipients
      add constraint agenda_alert_recipients_tenant_pessoa_fkey
        foreign key (igreja_id, pessoa_id)
        references public.pessoas (igreja_id, id)
        on delete set null (pessoa_id);
  end if;
end
$keys$;

create unique index if not exists agenda_alert_recipients_igreja_pessoa_active_uq
  on public.agenda_alert_recipients (igreja_id, pessoa_id)
  where ativo and pessoa_id is not null;

alter table public.events
  add column if not exists notification_outbox_fenced_at timestamptz,
  add column if not exists notification_outbox_fence_reason text;

-- A tenant owns its cutover instant. Historical tenants are stamped exactly
-- once here; a DEFAULT stamps every later onboarding INSERT in the same
-- statement, without a trigger or a second cutover representation.
alter table public.igrejas
  add column if not exists notification_outbox_cutover_at timestamptz;
update public.igrejas
set notification_outbox_cutover_at = transaction_timestamp()
where notification_outbox_cutover_at is null;
alter table public.igrejas
  alter column notification_outbox_cutover_at set default transaction_timestamp(),
  alter column notification_outbox_cutover_at set not null;

create table if not exists public.whatsapp_reminder_preferences (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  pessoa_id uuid not null,
  reminder_kind text not null,
  state text not null,
  term_version text,
  accepted_at timestamptz,
  changed_at timestamptz not null,
  constraint whatsapp_reminder_preferences_tenant_id_key unique (igreja_id, id),
  constraint whatsapp_reminder_preferences_once_key
    unique (igreja_id, pessoa_id, reminder_kind),
  constraint whatsapp_reminder_preferences_tenant_pessoa_fkey
    foreign key (igreja_id, pessoa_id)
    references public.pessoas (igreja_id, id) on delete cascade,
  constraint whatsapp_reminder_preferences_state_closed
    check (state in ('active', 'disabled')),
  constraint whatsapp_reminder_preferences_kind_closed
    check (reminder_kind in ('agenda', 'cell_report')),
  constraint whatsapp_reminder_preferences_active_term_chk
    check ((state = 'active' and term_version is not null
            and length(btrim(term_version)) > 0 and accepted_at is not null)
           or state = 'disabled')
);

-- The legacy V1a refusal remains immutable there and is copied into the
-- canonical purpose-scoped preference. No legacy row is removed or replayed.
insert into public.whatsapp_reminder_preferences (
  igreja_id, pessoa_id, reminder_kind, state, term_version, accepted_at, changed_at
)
select igreja_id, pessoa_id, 'cell_report', 'disabled', null, null, updated_at
from public.cell_report_reminder_preferences
on conflict (igreja_id, pessoa_id, reminder_kind) do nothing;

create table if not exists public.agenda_reminder_subscriptions (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  pessoa_id uuid not null,
  event_id uuid not null,
  occurrence_at timestamptz not null,
  proposal_id uuid not null,
  state text not null,
  term_version text not null,
  confirmed_at timestamptz not null,
  updated_at timestamptz not null,
  constraint agenda_reminder_subscriptions_tenant_id_key unique (igreja_id, id),
  constraint agenda_reminder_subscriptions_once_key
    unique (igreja_id, pessoa_id, event_id, occurrence_at),
  constraint agenda_reminder_subscriptions_tenant_pessoa_fkey
    foreign key (igreja_id, pessoa_id)
    references public.pessoas (igreja_id, id) on delete cascade,
  constraint agenda_reminder_subscriptions_tenant_event_fkey
    foreign key (igreja_id, event_id)
    references public.events (igreja_id, id) on delete cascade,
  constraint agenda_reminder_subscriptions_tenant_proposal_fkey
    foreign key (igreja_id, proposal_id)
    references public.agent_action_proposals (igreja_id, id) on delete cascade,
  constraint agenda_reminder_subscriptions_state_closed
    check (state in ('active', 'cancelled')),
  constraint agenda_reminder_subscriptions_term_version_chk
    check (length(btrim(term_version)) > 0)
);

-- ``origin_id`` plus ``occurrence_at`` is the canonical occurrence identity.
-- Live source FKs can be nulled when the origin is removed; the opaque source
-- identity and the recipient reservation remain for quota and receipt safety.
create table if not exists public.notification_outbox (
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
    unique (igreja_id, pessoa_id, origin_kind, origin_id, occurrence_at, purpose),
  constraint notification_outbox_tenant_pessoa_fkey
    foreign key (igreja_id, pessoa_id)
    references public.pessoas (igreja_id, id) on delete cascade,
  constraint notification_outbox_tenant_event_fkey
    foreign key (igreja_id, event_id)
    references public.events (igreja_id, id) on delete set null (event_id),
  constraint notification_outbox_tenant_reuniao_fkey
    foreign key (igreja_id, reuniao_id)
    references public.celula_reuniao (igreja_id, id) on delete set null (reuniao_id),
  constraint notification_outbox_tenant_alert_recipient_fkey
    foreign key (igreja_id, agenda_alert_recipient_id)
    references public.agenda_alert_recipients (igreja_id, id)
    on delete set null (agenda_alert_recipient_id),
  constraint notification_outbox_tenant_subscription_fkey
    foreign key (igreja_id, agenda_subscription_id)
    references public.agenda_reminder_subscriptions (igreja_id, id)
    on delete set null (agenda_subscription_id),
  constraint notification_outbox_purpose_closed
    check (purpose in ('agenda_reminder', 'agenda_evt7', 'cell_report_reminder')),
  constraint notification_outbox_state_closed
    check (state in ('pendente', 'em_envio', 'retry', 'enviado', 'ambiguo',
                     'cancelado', 'obsoleto', 'fenced')),
  constraint notification_outbox_attempts_range
    check (attempts >= 0 and attempts <= 2),
  constraint notification_outbox_reference_shape_chk
    check (
      (purpose = 'agenda_reminder' and origin_kind = 'event'
       and reuniao_id is null and agenda_alert_recipient_id is null)
      or (purpose = 'agenda_evt7' and origin_kind = 'event'
          and reuniao_id is null and agenda_subscription_id is null)
      or (purpose = 'cell_report_reminder' and origin_kind = 'meeting'
          and event_id is null and agenda_subscription_id is null
          and agenda_alert_recipient_id is null)
    ),
  constraint notification_outbox_origin_kind_closed
    check (origin_kind in ('event', 'meeting')),
  constraint notification_outbox_live_origin_identity_chk
    check (
      (event_id is null or (origin_kind = 'event' and origin_id = event_id))
      and (reuniao_id is null or (origin_kind = 'meeting' and origin_id = reuniao_id))
    ),
  constraint notification_outbox_origin_fingerprint_shape
    check (origin_fingerprint ~ '^[0-9a-f]{64}$')
);

create index if not exists notification_outbox_due_idx
  on public.notification_outbox (igreja_id, state, due_at);
create index if not exists notification_outbox_recipient_claim_idx
  on public.notification_outbox (igreja_id, pessoa_id, state);
create index if not exists notification_outbox_delivery_reservation_idx
  on public.notification_outbox (igreja_id, pessoa_id, delivery_reservation_day);

alter table public.whatsapp_reminder_preferences enable row level security;
alter table public.whatsapp_reminder_preferences force row level security;
alter table public.agenda_reminder_subscriptions enable row level security;
alter table public.agenda_reminder_subscriptions force row level security;
alter table public.notification_outbox enable row level security;
alter table public.notification_outbox force row level security;

drop policy if exists whatsapp_reminder_preferences_worker_only
  on public.whatsapp_reminder_preferences;
create policy whatsapp_reminder_preferences_worker_only
  on public.whatsapp_reminder_preferences for all to authenticated
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

-- A pastor/admin route may consult only a live agenda preference while
-- confirming an event. The Clerk claim identifies a principal but never grants
-- by itself: the active tenant app_user and accumulated role are rechecked.
-- S3/worker remains the only preference writer.
drop policy if exists whatsapp_reminder_preferences_human_agenda_select
  on public.whatsapp_reminder_preferences;
create policy whatsapp_reminder_preferences_human_agenda_select
  on public.whatsapp_reminder_preferences for select to authenticated
  using (
    igreja_id = public.current_igreja_id()
    and reminder_kind = 'agenda'
    and state = 'active'
    and term_version is not null
    and length(btrim(term_version)) > 0
    and accepted_at is not null
    and accepted_at <= clock_timestamp()
    and exists (
      select 1
      from public.app_users as principal
      join public.user_roles as principal_role
        on principal_role.igreja_id = principal.igreja_id
       and principal_role.user_id = principal.id
      where principal.igreja_id = whatsapp_reminder_preferences.igreja_id
        and principal.status = 'ativo'
        and principal.clerk_user_id = nullif(coalesce(
          nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
          pg_catalog.current_setting('request.jwt.claim.sub', true)
        ), '')
        and principal_role.papel in ('pastor', 'admin')
    )
  );

drop policy if exists agenda_reminder_subscriptions_worker_only
  on public.agenda_reminder_subscriptions;
create policy agenda_reminder_subscriptions_worker_only
  on public.agenda_reminder_subscriptions for all to authenticated
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

drop policy if exists notification_outbox_worker_only on public.notification_outbox;
create policy notification_outbox_worker_only on public.notification_outbox
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

-- The human event-confirmation transaction can enqueue only the initial EVT-7
-- notice. It never sees agenda/cell-report reminders and never changes a
-- claim, retry, fence, transport, or terminal result.
drop policy if exists notification_outbox_human_evt7_select on public.notification_outbox;
create policy notification_outbox_human_evt7_select on public.notification_outbox
  for select to authenticated
  using (
    igreja_id = public.current_igreja_id()
    and purpose = 'agenda_evt7'
    and exists (
      select 1
      from public.app_users as principal
      join public.user_roles as principal_role
        on principal_role.igreja_id = principal.igreja_id
       and principal_role.user_id = principal.id
      where principal.igreja_id = notification_outbox.igreja_id
        and principal.status = 'ativo'
        and principal.clerk_user_id = nullif(coalesce(
          nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
          pg_catalog.current_setting('request.jwt.claim.sub', true)
        ), '')
        and principal_role.papel in ('pastor', 'admin')
    )
  );

drop policy if exists notification_outbox_human_evt7_insert on public.notification_outbox;
create policy notification_outbox_human_evt7_insert on public.notification_outbox
  for insert to authenticated
  with check (
    igreja_id = public.current_igreja_id()
    and purpose = 'agenda_evt7'
    and origin_kind = 'event'
    and event_id is not null
    and agenda_alert_recipient_id is not null
    and reuniao_id is null
    and agenda_subscription_id is null
    and origin_id = event_id
    and state = 'pendente'
    and claim_token is null
    and claimed_until is null
    and claimed_by is null
    and attempts = 0
    and transport_started_at is null
    and sent_at is null
    and terminal_reason is null
    and delivery_reservation_day is null
    and (event_id, igreja_id) in (
      select source_event.id, source_event.igreja_id
      from public.events as source_event
      where source_event.status = 'confirmado'
        and source_event.notification_outbox_fenced_at is null
        and source_event.notificado_em is null
    )
    and (agenda_alert_recipient_id, pessoa_id, igreja_id) in (
      select recipient.id, recipient.pessoa_id, recipient.igreja_id
      from public.agenda_alert_recipients as recipient
      where recipient.ativo is true and recipient.pessoa_id is not null
    )
    and exists (
      select 1
      from public.whatsapp_reminder_preferences as preference
      where preference.igreja_id = notification_outbox.igreja_id
        and preference.pessoa_id = notification_outbox.pessoa_id
        and preference.reminder_kind = 'agenda'
        and preference.state = 'active'
        and preference.term_version is not null
        and length(btrim(preference.term_version)) > 0
        and preference.accepted_at is not null
        and preference.accepted_at <= clock_timestamp()
    )
    and exists (
      select 1
      from public.app_users as principal
      join public.user_roles as principal_role
        on principal_role.igreja_id = principal.igreja_id
       and principal_role.user_id = principal.id
      where principal.igreja_id = notification_outbox.igreja_id
        and principal.status = 'ativo'
        and principal.clerk_user_id = nullif(coalesce(
          nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
          pg_catalog.current_setting('request.jwt.claim.sub', true)
        ), '')
        and principal_role.papel in ('pastor', 'admin')
    )
  );

revoke all privileges on table public.whatsapp_reminder_preferences,
  public.agenda_reminder_subscriptions,
  public.notification_outbox from public;

do $acl$
declare
  target_role text;
begin
  foreach target_role in array array['anon', 'service_role', 'agent_runtime'] loop
    if pg_catalog.to_regrole(target_role) is not null then
      execute format(
        'revoke all privileges on table public.whatsapp_reminder_preferences, public.agenda_reminder_subscriptions, public.notification_outbox from %I',
        target_role
      );
    end if;
  end loop;
  if pg_catalog.to_regrole('authenticated') is not null then
    execute 'revoke delete on table public.whatsapp_reminder_preferences, public.agenda_reminder_subscriptions, public.notification_outbox from authenticated';
    execute 'grant select, insert, update on table public.whatsapp_reminder_preferences, public.agenda_reminder_subscriptions, public.notification_outbox to authenticated';
    if pg_catalog.has_table_privilege('authenticated', 'public.whatsapp_reminder_preferences', 'delete')
      or pg_catalog.has_table_privilege('authenticated', 'public.agenda_reminder_subscriptions', 'delete')
      or pg_catalog.has_table_privilege('authenticated', 'public.notification_outbox', 'delete') then
      raise exception 'DELETE permanece concedido em tabela V2b';
    end if;
  end if;
end
$acl$;

-- V1a cutover: no old row can become eligible after this point. A process
-- already inside HTTP remains the documented quiescence boundary; its old row
-- is retained as ambiguous and is never replayed by the new dispatcher.
update public.cell_report_reminders
set state = case
      when state = 'em_envio' then 'ambiguo'
      else 'cancelado'
    end,
    claim_token = null,
    claimed_until = null,
    terminal_reason = case
      when state = 'em_envio' then 'outbox_unificada_cutover_ambiguo'
      else 'outbox_unificada_cutover'
    end,
    updated_at = clock_timestamp()
where state in ('pendente', 'retry', 'em_envio');

create or replace function public.notification_outbox_fence_legacy_cell_report_reminder()
returns trigger
language plpgsql
as $fence_v1a$
begin
  if tg_op = 'INSERT' then
    if new.state in ('pendente', 'retry', 'em_envio', 'enviado') then
      new.state := 'cancelado';
      new.claim_token := null;
      new.claimed_until := null;
      new.terminal_reason := 'outbox_unificada_cutover';
    end if;
  elsif old.state in ('cancelado', 'obsoleto', 'ambiguo', 'enviado') then
    -- A stale ORM instance can only preserve the terminal DB state.
    new.state := old.state;
    new.claim_token := null;
    new.claimed_until := null;
    new.terminal_reason := old.terminal_reason;
  elsif new.state in ('pendente', 'retry', 'em_envio', 'enviado') then
    new.state := case when old.state = 'em_envio' then 'ambiguo' else 'cancelado' end;
    new.claim_token := null;
    new.claimed_until := null;
    new.terminal_reason := case
      when old.state = 'em_envio' then 'outbox_unificada_cutover_ambiguo'
      else 'outbox_unificada_cutover'
    end;
  end if;
  return new;
end
$fence_v1a$;

drop trigger if exists notification_outbox_fence_legacy_cell_report_reminder
  on public.cell_report_reminders;
create trigger notification_outbox_fence_legacy_cell_report_reminder
  before insert or update on public.cell_report_reminders
  for each row execute function public.notification_outbox_fence_legacy_cell_report_reminder();

-- A separate reason records that notificado_em was written only to stop old
-- code. New dispatch always reads the shared outbox receipt instead.
update public.events
set notification_outbox_fenced_at = clock_timestamp(),
    notification_outbox_fence_reason = case
      when notificado_em is null then 'legacy_evt7_sem_recibo'
      else 'legacy_evt7_recibo_preservado'
    end,
    notificado_em = coalesce(notificado_em, clock_timestamp())
from public.igrejas as igreja
where events.igreja_id = igreja.id
  and events.status = 'confirmado'
  and events.notification_outbox_fenced_at is null
  and coalesce(events.created_at, '-infinity'::timestamptz) < igreja.notification_outbox_cutover_at;

create or replace function public.notification_outbox_fence_legacy_evt7()
returns trigger
language plpgsql
as $fence_evt7$
begin
  -- New code sets this transaction-local marker before its ORM flush. Legacy
  -- confirmation does not, so its following refresh observes notificado_em.
  if old.status = 'a_confirmar' and new.status = 'confirmado'
     and current_setting('app.notification_outbox_v2b', true) is distinct from '1' then
    new.notification_outbox_fenced_at := clock_timestamp();
    new.notification_outbox_fence_reason := 'legacy_evt7_cutover';
    new.notificado_em := coalesce(new.notificado_em, new.notification_outbox_fenced_at);
  end if;
  return new;
end
$fence_evt7$;

drop trigger if exists notification_outbox_fence_legacy_evt7 on public.events;
create trigger notification_outbox_fence_legacy_evt7
  before update of status on public.events
  for each row execute function public.notification_outbox_fence_legacy_evt7();

do $rls$
declare
  target_table regclass;
begin
  foreach target_table in array array[
    'public.whatsapp_reminder_preferences'::regclass,
    'public.agenda_reminder_subscriptions'::regclass,
    'public.notification_outbox'::regclass
  ] loop
    if not (
      select relrowsecurity and relforcerowsecurity
      from pg_catalog.pg_class where oid = target_table
    ) then
      raise exception 'RLS/force ausente para %', target_table;
    end if;
  end loop;
end
$rls$;

-- Rollback manual somente após fechar gates, drenar claims e preservar os
-- recibos. Revogue grants antes de remover as relações e remova primeiro as
-- referências da outbox; não transforme estados ambíguos em nova tentativa.
-- Alterações em checks S3 exigem restaurar a lista V1a, e os gatilhos de
-- compatibilidade só podem sair depois da quiescência de todos os processos
-- legados. As chaves compostas podem permanecer sem efeito funcional.

commit;
