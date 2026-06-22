-- ============================================================================
-- PastorAI 1.0 — Migration 0012: catálogo de planos (definido pelo master)
-- "O master pode definir os planos." Até aqui os preços eram hardcoded no
-- backend (PLANO_PRECOS = 199/299/399). Esta tabela torna o catálogo editável
-- pelo console de plataforma (CRUD em /admin/planos) e a fonte única do preço
-- para MRR, detalhe da igreja e a tela de Assinatura do tenant.
--
-- planos é uma tabela de REFERÊNCIA GLOBAL (sem igreja_id), no mesmo espírito
-- de `igrejas`: definida pelo provedor do SaaS, mas LIDA por todos os tenants
-- (cada igreja precisa ver os planos disponíveis). Por isso a RLS aqui é
-- diferente das tabelas por tenant:
--   - SELECT: liberado (qualquer autenticado vê os planos ATIVOS).
--   - INSERT/UPDATE/DELETE: nenhuma policy => só o service role (BYPASSRLS) —
--     ou seja, só o master via get_platform_admin (que NÃO aplica tenant
--     context). Defense in depth: revoke explícito do DML em authenticated.
--
-- Idempotente. Roda como service role (postgres), igual aos seeds 0005/0007.
-- ============================================================================

begin;

create table if not exists planos (
  id             uuid primary key default gen_random_uuid(),
  codigo         text not null unique,          -- slug estável (igrejas.plano referencia isto)
  nome           text not null,
  limite_pessoas int,                            -- null = ilimitado
  preco_mensal   numeric(10,2) not null default 0,
  ativo          boolean not null default true,  -- desativar esconde do tenant sem apagar
  ordem          int not null default 0,         -- ordem de exibição
  created_at     timestamptz not null default now()
);

-- Leitura liberada; escrita só via service role.
alter table planos enable row level security;

-- Tenant enxerga apenas planos ATIVOS (defense in depth: um plano desativado
-- some da tela de Assinatura mesmo via API). O master lê todos via BYPASSRLS,
-- ignorando esta policy. Sem `to <role>` para casar com o estilo da 0003.
do $$ begin
  create policy planos_select_ativos on planos
    for select
    using (ativo = true);
exception when duplicate_object then null; end $$;

-- Escrita global somente via service role: revoga DML herdado pelos roles de
-- aplicação (protegido p/ ambientes onde os roles do Supabase não existam).
do $$ begin
  revoke insert, update, delete on table planos from authenticated;
exception when undefined_object then null; end $$;
do $$ begin
  revoke insert, update, delete on table planos from anon;
exception when undefined_object then null; end $$;

-- Seed dos planos atuais (PRD: até 100=199; 101-200=299; acima 201=399).
-- Idempotente por codigo: re-rodar não duplica nem sobrescreve preços já
-- editados pelo master.
insert into planos (codigo, nome, limite_pessoas, preco_mensal, ordem) values
  ('ate_100',   'Até 100 pessoas',   100,  199, 1),
  ('101_200',   '101 a 200 pessoas', 200,  299, 2),
  ('acima_201', '201+ pessoas',      null, 399, 3)
on conflict (codigo) do nothing;

comment on table planos is
  'Catálogo de planos do SaaS (preço mensal por porte). Definido pelo master (console de plataforma, /admin/planos); lido por todos os tenants (tela de Assinatura). Escrita só via service role (BYPASSRLS). Ver migration 0012.';

commit;
