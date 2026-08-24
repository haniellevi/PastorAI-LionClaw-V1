-- PastorAI: isolamento formal na conta Asaas compartilhada.
--
-- A integração só pode mutar recursos cuja externalReference pertença ao
-- namespace `pastorai-`. Recursos já existentes sem esse marcador continuam
-- intocados. A migration também fecha duplicidade local de IDs remotos e cria
-- o ledger de idempotência recomendado pelo Asaas para webhooks at-least-once.

begin;

alter table subscriptions
  add column if not exists asaas_customer_external_reference text null,
  add column if not exists asaas_subscription_external_reference text null;

do $constraints$
begin
  if not exists (
    select 1 from pg_constraint
     where conrelid = 'subscriptions'::regclass
       and conname = 'subscriptions_asaas_customer_external_reference_ck'
  ) then
    alter table subscriptions
      add constraint subscriptions_asaas_customer_external_reference_ck
      check (
        asaas_customer_external_reference is null
        or asaas_customer_external_reference like 'pastorai-%'
      );
  end if;

  if not exists (
    select 1 from pg_constraint
     where conrelid = 'subscriptions'::regclass
       and conname = 'subscriptions_asaas_subscription_external_reference_ck'
  ) then
    alter table subscriptions
      add constraint subscriptions_asaas_subscription_external_reference_ck
      check (
        asaas_subscription_external_reference is null
        or asaas_subscription_external_reference like 'pastorai-%'
      );
  end if;
end
$constraints$;

do $preflight$
begin
  if exists (
    select 1
      from subscriptions
     where asaas_customer_id is not null
       and asaas_customer_id <> 'sandbox'
     group by asaas_customer_id
    having count(*) > 1
  ) then
    raise exception 'Asaas isolation preflight: duplicate customer ids';
  end if;

  if exists (
    select 1
      from subscriptions
     where asaas_subscription_id is not null
       and asaas_subscription_id <> 'sandbox'
     group by asaas_subscription_id
    having count(*) > 1
  ) then
    raise exception 'Asaas isolation preflight: duplicate subscription ids';
  end if;

  if exists (
    select 1
      from subscriptions
     where asaas_customer_external_reference is not null
     group by asaas_customer_external_reference
    having count(*) > 1
  ) then
    raise exception 'Asaas isolation preflight: duplicate customer references';
  end if;

  if exists (
    select 1
      from subscriptions
     where asaas_subscription_external_reference is not null
     group by asaas_subscription_external_reference
    having count(*) > 1
  ) then
    raise exception 'Asaas isolation preflight: duplicate subscription references';
  end if;
end
$preflight$;

create unique index if not exists subscriptions_asaas_customer_id_uidx
  on subscriptions (asaas_customer_id)
  where asaas_customer_id is not null and asaas_customer_id <> 'sandbox';

create unique index if not exists subscriptions_asaas_subscription_id_uidx
  on subscriptions (asaas_subscription_id)
  where asaas_subscription_id is not null and asaas_subscription_id <> 'sandbox';

create unique index if not exists subscriptions_asaas_customer_reference_uidx
  on subscriptions (asaas_customer_external_reference)
  where asaas_customer_external_reference is not null;

create unique index if not exists subscriptions_asaas_subscription_reference_uidx
  on subscriptions (asaas_subscription_external_reference)
  where asaas_subscription_external_reference is not null;

create index if not exists billing_payment_operations_stale_idx
  on billing_payment_operations (
    (coalesce(attempt_started_at, updated_at, created_at))
  )
  where status in ('creating', 'reconciling');

create index if not exists billing_subscription_operations_stale_idx
  on billing_subscription_operations (
    (coalesce(attempt_started_at, updated_at, created_at))
  )
  where status in ('creating', 'reconciling');

create table if not exists asaas_webhook_receipts (
  id            uuid primary key default gen_random_uuid(),
  event_id      text not null unique,
  event_type    text not null,
  resource_type text null check (resource_type in ('payment', 'subscription')),
  resource_id   text null,
  received_at   timestamptz not null default now()
);

create index if not exists asaas_webhook_receipts_received_at_idx
  on asaas_webhook_receipts (received_at);

alter table asaas_webhook_receipts enable row level security;

do $policy$
begin
  if not exists (
    select 1 from pg_policy
     where polrelid = 'asaas_webhook_receipts'::regclass
       and polname = 'service_role_bypass_only'
  ) then
    create policy service_role_bypass_only on asaas_webhook_receipts
      as restrictive for all to public
      using (false) with check (false);
  end if;
end
$policy$;

revoke all privileges on table asaas_webhook_receipts from public;
do $roles$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    revoke all privileges on table asaas_webhook_receipts from anon;
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    revoke all privileges on table asaas_webhook_receipts from authenticated;
  end if;
end
$roles$;

comment on column subscriptions.asaas_customer_external_reference is
  'Marcador de propriedade do customer na conta Asaas compartilhada; deve usar o namespace pastorai-.';
comment on column subscriptions.asaas_subscription_external_reference is
  'Marcador de propriedade da assinatura na conta Asaas compartilhada; deve usar o namespace pastorai-.';
comment on table asaas_webhook_receipts is
  'Ledger fechado de IDs de eventos Asaas para processamento idempotente de entregas at-least-once.';

commit;
