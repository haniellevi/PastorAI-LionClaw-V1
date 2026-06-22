-- ============================================================================
-- PastorAI 1.0 — Migration 0010: platform_admins (console Super-Admin / Onda 1)
-- US-42/US-43, RF-48/RF-49. Plano de PLATAFORMA, fora do conjunto multi-tenant:
-- o Super-Admin (provedor do SaaS) administra TODAS as igrejas, portanto NAO
-- pode estar sujeito a RLS por igreja_id.
--
-- Modelo de acesso: o Super-Admin tambem e um app_user (tem login via Clerk em
-- alguma igreja). platform_admins e a allowlist que eleva esse app_user ao plano
-- de plataforma. O gate get_platform_admin (app/deps.py) resolve o app_user pelo
-- clerk_user_id do token e exige uma linha aqui — SEM aplicar tenant context, de
-- modo que a sessao roda como o role de conexao (postgres, BYPASSRLS) e enxerga
-- todas as igrejas. A escrita global em `igrejas` ja so e possivel via service
-- role: a 0003 habilita RLS em igrejas e cria apenas policy de SELECT (nenhuma
-- de INSERT/UPDATE/DELETE), logo o role authenticated nao cria/altera igrejas.
--
-- Seguranca: RLS habilitada e SEM policy => nenhum tenant (role authenticated)
-- enxerga esta tabela; apenas o service role (BYPASSRLS). Revoke explicito em
-- authenticated/anon como defesa em profundidade (caso a RLS seja desabilitada).
-- Idempotente. Roda como service role (postgres), igual aos seeds 0005/0007/0009.
-- ============================================================================

begin;

create table if not exists platform_admins (
  id           uuid primary key default gen_random_uuid(),
  app_user_id  uuid not null unique references app_users(id) on delete cascade,
  email        text not null,                 -- cache p/ auditoria/legibilidade
  created_at   timestamptz not null default now()
);

create index if not exists idx_platform_admins_app_user
  on platform_admins (app_user_id);

-- Isolamento: somente service role (BYPASSRLS). RLS habilitada e SEM policy =>
-- nega leitura/escrita a qualquer outro role, mesmo que ele tenha GRANT.
alter table platform_admins enable row level security;

-- Defesa em profundidade: revoga qualquer DML herdado pelos roles de aplicacao.
-- Protegido contra ambientes onde os roles do Supabase nao existam (local).
do $$ begin
  revoke all on table platform_admins from authenticated;
exception when undefined_object then null; end $$;
do $$ begin
  revoke all on table platform_admins from anon;
exception when undefined_object then null; end $$;

comment on table platform_admins is
  'Allowlist do console Super-Admin (Onda 1 / US-42/43). Plano de plataforma, fora do RLS por tenant: eleva um app_user a administrador global. Acesso somente via service role (BYPASSRLS); ver get_platform_admin (app/deps.py).';

commit;
