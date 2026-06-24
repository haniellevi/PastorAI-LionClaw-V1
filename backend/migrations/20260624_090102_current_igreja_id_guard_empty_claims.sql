-- ============================================================================
-- PastorAI — Migration 20260624_090102 — current_igreja_id() robusto a claim vazio
-- #10b Fase 0 (HOTFIX): no caminho do worker, request.jwt.claims pode vir como
-- string VAZIA ('') numa conexão do pool — e '::jsonb' de '' FALHA
-- ("invalid input syntax for type json: The input string ended unexpectedly"),
-- derrubando a RLS de pessoas e, com ela, o ingest do WhatsApp (mensagem vai
-- pra dead-letter). Guardamos o cast com nullif(..., '') para '' virar NULL
-- (seguro). O HTTP segue idêntico (claims é JSON válido ou ausente/NULL).
-- create or replace idempotente; aplicar no Supabase em ordem de nome.
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
    --    nullif(claims, '') evita '::jsonb' sobre string vazia no worker.
    (
      select au.igreja_id
      from public.app_users au
      where au.clerk_user_id = nullif(
        coalesce(
          nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
          current_setting('request.jwt.claim.sub', true)
        ),
        ''
      )
      limit 1
    )
  );
$$;

comment on function current_igreja_id() is
  'Retorna o igreja_id do tenant ativo: 1) GUC app.tenant_igreja_id (worker/async, sem JWT); senao 2) o app_user do clerk_user_id (claim sub do JWT). Robusto a request.jwt.claims vazio (F1 / #10b Fase 0).';

commit;
