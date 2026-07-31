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
-- expõe nem recupera até um novo ciclo válido limpar o motivo. O MOTIVO
-- importa: 'deleted' permite restaurar a MESMA cobrança no Asaas; 'refunded'
-- exige uma cobrança avulsa de recuperação (nunca outra assinatura).
alter table subscriptions
  add column if not exists asaas_invoice_reversal text null
    check (asaas_invoice_reversal in ('deleted', 'refunded'));

-- Operações duráveis de cobrança avulsa (setup e recuperação de mensalidade):
-- a operation_key é persistida ANTES do POST /payments e vira a
-- externalReference exclusiva da cobrança — retry reconcilia pela chave em vez
-- de repetir o POST às cegas (resposta perdida nunca duplica cobrança).
create table if not exists billing_payment_operations (
  id                uuid primary key default gen_random_uuid(),
  subscription_id   uuid not null references subscriptions(id) on delete cascade,
  purpose           text not null check (purpose in ('setup', 'monthly_recovery')),
  operation_key     text not null unique,
  source_payment_id text null,
  asaas_payment_id  text null,
  status            text not null default 'prepared'
    check (status in ('prepared','creating','reconciling','created','paid','reversed','failed')),
  valor             numeric(10,2) not null,
  invoice_url       text null,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create unique index if not exists billing_payment_operations_asaas_payment_id_uidx
  on billing_payment_operations (asaas_payment_id)
  where asaas_payment_id is not null;

-- Claim atômico: no máximo UMA operação em andamento por assinatura+propósito
-- (dois requests concorrentes não criam duas cobranças).
create unique index if not exists billing_payment_operations_open_uidx
  on billing_payment_operations (subscription_id, purpose)
  where status in ('prepared','creating','reconciling','created');

-- Criação INICIAL de assinatura retry-safe (CORRECTIVE-6): a intenção é
-- persistida ANTES do POST /subscriptions e a operation_key vira a
-- externalReference da assinatura. Resposta perdida → `reconciling`; o retry
-- procura GET /subscriptions?externalReference= e ADOTA somente a assinatura
-- que corresponda a customer/valor/ciclo/descrição congelados — nunca repete
-- o POST às cegas (a externalReference NÃO é garantia de idempotência do
-- POST no Asaas; serve para localizar e reconciliar).
create table if not exists billing_subscription_operations (
  id                    uuid primary key default gen_random_uuid(),
  subscription_id       uuid not null references subscriptions(id) on delete cascade,
  operation_key         text not null unique,
  customer_id           text null,
  plano                 text not null,
  valor                 numeric(10,2) not null,
  ciclo                 text not null default 'MONTHLY',
  descricao             text not null,
  asaas_subscription_id text null,
  status                text not null default 'prepared'
    check (status in ('prepared','creating','reconciling','created','failed')),
  error                 text null,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

-- Claim atômico: no máximo UMA criação de assinatura em andamento por
-- Subscription local.
create unique index if not exists billing_subscription_operations_open_uidx
  on billing_subscription_operations (subscription_id)
  where status in ('prepared','creating','reconciling');

create unique index if not exists billing_subscription_operations_asaas_id_uidx
  on billing_subscription_operations (asaas_subscription_id)
  where asaas_subscription_id is not null;

alter table billing_subscription_operations enable row level security;

do $$ begin
  create policy billing_subscription_operations_tenant on billing_subscription_operations
    for all
    using (
      subscription_id in (
        select s.id from subscriptions s where s.igreja_id = current_igreja_id()
      )
    )
    with check (
      subscription_id in (
        select s.id from subscriptions s where s.igreja_id = current_igreja_id()
      )
    );
exception when duplicate_object then null; end $$;

comment on table billing_subscription_operations is
  'Intenções duráveis de criação de assinatura: operation_key persistida antes do POST /subscriptions vira externalReference — retry reconcilia por busca, nunca repete o POST às cegas.';

-- Troca de plano (decisão do dono, PLAN-CHANGE-SAFETY-1): atualiza a
-- assinatura Asaas EXISTENTE (PUT, updatePendingPayments=false, vigência no
-- próximo ciclo) — nunca cria segunda recorrência. A operação congela o alvo
-- antes do PUT; retry reconcilia por GET /subscriptions/{id}. `origin`
-- reserva o mesmo trilho para o auto-upgrade quando houver worker de billing.
-- `notify_status` separa a conclusão FINANCEIRA da entrega da notificação:
-- 'pending' fica descobrível pelo cron-worker até o envio ('sent'); operações
-- manuais nascem 'skipped' (não notificam).
create table if not exists billing_plan_change_operations (
  id                    uuid primary key default gen_random_uuid(),
  subscription_id       uuid not null references subscriptions(id) on delete cascade,
  asaas_subscription_id text not null,
  from_plano            text not null,
  to_plano              text not null,
  to_preco              numeric(10,2) not null,
  to_limite             integer null,
  origin                text not null default 'manual'
    check (origin in ('manual', 'autoupgrade')),
  status                text not null default 'prepared'
    check (status in ('prepared','processing','reconciling','completed','failed')),
  notify_status         text not null default 'skipped'
    check (notify_status in ('pending','sent','skipped')),
  error                 text null,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

-- Claim atômico: no máximo UMA troca em andamento por assinatura.
create unique index if not exists billing_plan_change_operations_open_uidx
  on billing_plan_change_operations (subscription_id)
  where status in ('prepared','processing','reconciling');

alter table billing_plan_change_operations enable row level security;

do $$ begin
  create policy billing_plan_change_operations_tenant on billing_plan_change_operations
    for all
    using (
      subscription_id in (
        select s.id from subscriptions s where s.igreja_id = current_igreja_id()
      )
    )
    with check (
      subscription_id in (
        select s.id from subscriptions s where s.igreja_id = current_igreja_id()
      )
    );
exception when duplicate_object then null; end $$;

comment on table billing_plan_change_operations is
  'Trocas de plano duráveis: PUT na assinatura Asaas existente (nunca nova recorrência), vigência no próximo ciclo, retry por reconciliação.';

-- ----------------------------------------------------------------------------
-- Auto-upgrade sincronizado (AUTOUPGRADE-BILLING-WORKER-1): o trigger deixa de
-- promover o plano local diretamente quando há assinatura Asaas rastreada — em
-- vez disso registra UMA operação durável (origin='autoupgrade') que o
-- cron-worker processa via PUT /subscriptions/{id} com
-- updatePendingPayments=false. O trigger NUNCA chama rede, NUNCA cria segunda
-- recorrência nem setup, e plano/limite/rótulo locais só mudam após a
-- confirmação remota (feita pelo worker). Sem vínculo Asaas não existe
-- recorrência a sincronizar: o upgrade local imediato é preservado.
-- Escada e thresholds preservados de 0004; preço alvo congelado do catálogo
-- `planos` (fonte única editada pelo master) no momento do gatilho.
-- ----------------------------------------------------------------------------
create or replace function fn_subscription_autoupgrade()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
declare
  v_total int;
  v_sub   subscriptions%rowtype;
  v_novo_plano  text;
  v_novo_limite int;
  v_novo_preco  numeric(10,2);
begin
  select * into v_sub from subscriptions where igreja_id = new.igreja_id;
  if not found then
    return new;
  end if;

  select count(*) into v_total from pessoas where igreja_id = new.igreja_id;

  -- atualiza contagem corrente de pessoas
  update subscriptions set pessoas = v_total where igreja_id = new.igreja_id;

  if v_sub.limite is not null and v_total > v_sub.limite then
    -- promove plano em escada
    if v_sub.plano = 'ate_100' then
      v_novo_plano := '101_200';
      v_novo_limite := 200;
    elsif v_sub.plano = '101_200' then
      v_novo_plano := 'acima_201';
      v_novo_limite := 999999;
    else
      v_novo_plano := v_sub.plano;
      v_novo_limite := v_sub.limite;
    end if;

    if v_novo_plano <> v_sub.plano then
      if v_sub.asaas_subscription_id is null then
        -- Sem assinatura Asaas rastreada não há recorrência remota: o
        -- upgrade local imediato (comportamento original de 0004) permanece.
        update subscriptions
          set plano = v_novo_plano,
              limite = v_novo_limite
          where igreja_id = new.igreja_id;
        update igrejas set plano = v_novo_plano where id = new.igreja_id;
      else
        -- Preço alvo do catálogo do master. Plano fora do catálogo não gera
        -- operação (nunca escrever um preço inventado no Asaas); o gatilho
        -- reavalia no próximo INSERT/UPDATE de pessoas.
        select p.preco_mensal into v_novo_preco
          from planos p
          where p.codigo = v_novo_plano;

        if v_novo_preco is not null then
          -- Repetições do gatilho coalescem na operação aberta, e uma troca
          -- MANUAL em andamento tem precedência: o índice único parcial
          -- (subscription_id | status aberto) faz o ON CONFLICT ignorar o
          -- insert em vez de duplicar ou sobrescrever.
          insert into billing_plan_change_operations
            (subscription_id, asaas_subscription_id, from_plano, to_plano,
             to_preco, to_limite, origin, status, notify_status)
          values
            (v_sub.id, v_sub.asaas_subscription_id, v_sub.plano, v_novo_plano,
             v_novo_preco, v_novo_limite, 'autoupgrade', 'prepared', 'pending')
          on conflict (subscription_id)
            where status in ('prepared','processing','reconciling')
            do nothing;
        end if;
      end if;
    end if;
  end if;

  return new;
end;
$$;

alter table billing_payment_operations enable row level security;

do $$ begin
  create policy billing_payment_operations_tenant on billing_payment_operations
    for all
    using (
      subscription_id in (
        select s.id from subscriptions s where s.igreja_id = current_igreja_id()
      )
    )
    with check (
      subscription_id in (
        select s.id from subscriptions s where s.igreja_id = current_igreja_id()
      )
    );
exception when duplicate_object then null; end $$;

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
comment on column subscriptions.asaas_invoice_reversal is
  'Motivo da reversão da cobrança mensal corrente (deleted|refunded); bloqueia exposição/recovery do link até o próximo ciclo válido ou recuperação explícita.';
comment on table billing_payment_operations is
  'Operações duráveis de cobrança avulsa (setup/monthly_recovery): operation_key persistida antes do POST vira externalReference exclusiva — retry reconcilia, nunca repete POST às cegas.';

commit;
