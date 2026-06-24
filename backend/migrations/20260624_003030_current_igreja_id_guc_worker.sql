-- ============================================================================
-- PastorAI — Migration 20260624_003030 — current_igreja_id() honra o GUC do worker
-- #10b Fase 0: isolamento por igreja no caminho ASSÍNCRONO (worker do WhatsApp).
--
-- O worker não tem JWT do Clerk (o contato do WhatsApp não tem login), então
-- set_tenant_context() — que injeta request.jwt.claims->>'sub' — não se aplica.
-- Estendemos current_igreja_id() para honrar TAMBÉM um GUC direto
-- 'app.tenant_igreja_id', setado por set_tenant_context_for_igreja() (rls.py),
-- caindo no papel `authenticated` para a RLS valer também fora do HTTP.
--
-- O caminho HTTP NÃO seta esse GUC → continua resolvendo pelo claim do Clerk
-- (comportamento 100% inalterado). É apenas um CREATE OR REPLACE idempotente da
-- função. Aplicar no Supabase em ordem de nome de arquivo.
-- ============================================================================

begin;

create or replace function current_igreja_id()
returns uuid
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select coalesce(
    -- 1) Worker/async: tenant injetado diretamente (sem JWT do Clerk).
    nullif(current_setting('app.tenant_igreja_id', true), '')::uuid,
    -- 2) HTTP: igreja_id derivada do clerk_user_id (claim "sub" do JWT).
    (
      select au.igreja_id
      from public.app_users au
      where au.clerk_user_id = nullif(
        coalesce(
          current_setting('request.jwt.claims', true)::jsonb ->> 'sub',
          current_setting('request.jwt.claim.sub', true)
        ),
        ''
      )
      limit 1
    )
  );
$$;

comment on function current_igreja_id() is
  'Retorna o igreja_id do tenant ativo: 1) GUC app.tenant_igreja_id (worker/async, sem JWT); senão 2) o app_user do clerk_user_id (claim sub do JWT). Base do isolamento multi-tenant (F1 / #10b Fase 0).';

commit;
