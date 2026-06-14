-- ============================================================================
-- PastorAI 1.0 — Migration 0003: RLS por tenant + current_igreja_id()
-- SPEC secao 2.2 / F1 / F4 (delta-033). Isolamento por tenant em nivel de banco.
--
-- current_igreja_id() deriva o tenant de app_users a partir do clerk_user_id
-- presente no JWT (claim "sub" do Clerk, exposto pelo PostgREST/Supabase em
-- request.jwt.claims). A funcao e SECURITY DEFINER para conseguir ler app_users
-- ignorando a propria RLS (evita recursao na avaliacao das policies).
-- ============================================================================

begin;

-- ----------------------------------------------------------------------------
-- Funcao de contexto: igreja_id do usuario autenticado
-- ----------------------------------------------------------------------------
create or replace function current_igreja_id()
returns uuid
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select au.igreja_id
  from public.app_users au
  where au.clerk_user_id = nullif(
    coalesce(
      current_setting('request.jwt.claims', true)::jsonb ->> 'sub',
      current_setting('request.jwt.claim.sub', true)
    ),
    ''
  )
  limit 1;
$$;

comment on function current_igreja_id() is
  'Retorna o igreja_id do app_user correspondente ao clerk_user_id (claim sub) do JWT autenticado. Base do isolamento multi-tenant (F1).';

-- ----------------------------------------------------------------------------
-- Helper para aplicar a policy padrao de tenant em massa.
-- Habilita RLS, forca RLS e cria policy USING/WITH CHECK por igreja_id.
-- ----------------------------------------------------------------------------
do $$
declare
  t text;
  tenant_tables text[] := array[
    'pessoas', 'app_users', 'user_roles', 'role_permissions', 'celulas',
    'cell_alerts', 'conversations', 'messages', 'work_queue_items', 'reports',
    'broadcasts', 'events', 'whatsapp_connections', 'agent_configs',
    'llm_credentials', 'crons', 'subscriptions', 'system_managers',
    'consolidacoes', 'consolidacao_etapas', 'decisions', 'multiplicacoes',
    'consent_records', 'ai_usage_logs', 'agent_conversation_logs'
  ];
begin
  foreach t in array tenant_tables loop
    execute format('alter table %I enable row level security;', t);

    -- Policy unica abrangendo SELECT/INSERT/UPDATE/DELETE (FOR ALL).
    execute format('drop policy if exists tenant_isolation on %I;', t);
    execute format($f$
      create policy tenant_isolation on %I
        for all
        using (igreja_id = current_igreja_id())
        with check (igreja_id = current_igreja_id());
    $f$, t);
  end loop;
end $$;

-- ----------------------------------------------------------------------------
-- igrejas: RLS especifica — usuario so enxerga o proprio tenant.
-- INSERT/UPDATE/DELETE (gestao global) somente via service role (bypassa RLS).
-- ----------------------------------------------------------------------------
alter table igrejas enable row level security;

drop policy if exists igrejas_self_select on igrejas;
create policy igrejas_self_select on igrejas
  for select
  using (id = current_igreja_id());

commit;
