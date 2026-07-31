-- ============================================================================
-- PastorAI — BILLING-SANDBOX-1: origem de preço controlada pelo master.
--
-- - `planos.preco_mensal` continua sendo a fonte da mensalidade.
-- - `billing_settings.setup_fee_default` guarda a taxa padrão de setup.
-- - `igrejas.setup_fee_override` permite exceção por igreja (NULL = padrão).
-- - `subscriptions.asaas_setup_charge_id` identifica a cobrança avulsa no
--   webhook, separando-a da mensalidade recorrente.
--
-- A linha inicial de billing_settings usa NULL para preservar o valor legado
-- de ambiente até o master salvar explicitamente a taxa no painel.
-- Aplicar manualmente no Supabase, conforme backend/migrations/README.md.
-- ============================================================================

begin;

-- Regra canônica da taxa de setup: R$ 0,00 (isenta) ou pelo menos R$ 5,00 —
-- o Asaas rejeita cobranças avulsas entre R$ 0,01 e R$ 4,99.
alter table igrejas
  add column if not exists setup_fee_override numeric(10,2) null
    check (setup_fee_override = 0 or setup_fee_override >= 5);

alter table subscriptions
  add column if not exists asaas_setup_charge_id text null;

-- Links públicos de pagamento (mensalidade e setup) devolvidos pelo checkout.
-- Persistidos para a tela de Assinatura recuperá-los após reload.
alter table subscriptions
  add column if not exists asaas_invoice_url text null;

alter table subscriptions
  add column if not exists asaas_setup_invoice_url text null;

-- Cobrança mensal do ciclo corrente: cada webhook de fatura atualiza id + URL,
-- para o link nunca apontar para uma mensalidade já quitada de ciclo anterior.
alter table subscriptions
  add column if not exists asaas_invoice_payment_id text null;

-- Estorno/exclusão da cobrança mensal corrente: link inutilizável — o GET não
-- expõe nem recupera até um novo ciclo válido zerar a flag.
alter table subscriptions
  add column if not exists asaas_invoice_reversed boolean not null default false;

create unique index if not exists subscriptions_asaas_setup_charge_id_uidx
  on subscriptions (asaas_setup_charge_id)
  where asaas_setup_charge_id is not null;

create table if not exists billing_settings (
  id                integer primary key check (id = 1),
  setup_fee_default numeric(10,2) null
    check (setup_fee_default = 0 or setup_fee_default >= 5),
  updated_at        timestamptz not null default now()
);

alter table billing_settings enable row level security;

do $$ begin
  create policy billing_settings_select on billing_settings
    for select
    using (true);
exception when duplicate_object then null; end $$;

do $$ begin
  revoke insert, update, delete on table billing_settings from authenticated;
exception when undefined_object then null; end $$;
do $$ begin
  revoke insert, update, delete on table billing_settings from anon;
exception when undefined_object then null; end $$;

insert into billing_settings (id, setup_fee_default)
values (1, null)
on conflict (id) do nothing;

comment on table billing_settings is
  'Taxa padrão de setup da plataforma. Editada apenas pelo console master; NULL preserva o fallback legado de ambiente.';
comment on column igrejas.setup_fee_override is
  'Taxa de setup específica da igreja definida pelo master. NULL usa billing_settings.setup_fee_default.';
comment on column subscriptions.asaas_setup_charge_id is
  'ID Asaas da cobrança avulsa de setup, usado para distinguir seu webhook da mensalidade.';
comment on column subscriptions.asaas_invoice_url is
  'Link público da primeira fatura da mensalidade, persistido para sobreviver a reload.';
comment on column subscriptions.asaas_setup_invoice_url is
  'Link público da cobrança avulsa de setup, persistido para sobreviver a reload.';
comment on column subscriptions.asaas_invoice_payment_id is
  'ID Asaas da cobrança mensal do ciclo corrente, atualizado a cada webhook de fatura.';
comment on column subscriptions.asaas_invoice_reversed is
  'True quando a cobrança mensal corrente foi estornada/excluída; bloqueia exposição e recovery do link até o próximo ciclo.';

commit;
