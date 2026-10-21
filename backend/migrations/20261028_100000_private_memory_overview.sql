-- Admin-only inventory. No content access, activation, deadline or automatic action.
begin;
set local lock_timeout='2s';

-- Existing policies deliberately hide summary tasks and suspended summaries
-- from web readers. This definer exposes only counters, with its own live
-- authorization and tenant predicates on every source. It never grants SELECT.
-- row_security=off raises if a misconfigured owner would silently filter counts;
-- it does not bypass RLS. The caller remains authenticated/NOBYPASSRLS.
create or replace function public.private_memory_overview(p_tenant uuid) returns jsonb
language plpgsql stable security definer set search_path=pg_catalog,public set row_security=off as $$
declare result jsonb;
begin
 if p_tenant is distinct from public.current_igreja_id()
 or session_user in ('authenticator','authenticated','anon')
 or not exists(
  select 1 from public.app_users a
  join public.user_roles r on r.igreja_id=a.igreja_id and r.user_id=a.id
  where a.igreja_id=p_tenant and a.clerk_user_id=public.prayer_jwt_sub()
  and a.status='ativo' and r.papel='admin'
  and (a.pessoa_id is null or exists(select 1 from public.pessoas p
   where p.igreja_id=p_tenant and p.id=a.pessoa_id and p.arquivada_em is null))
 ) then
  raise exception 'Active web admin required' using errcode='42501';
 end if;

 select jsonb_build_object(
  'pedidos_exclusao', (
   select jsonb_build_object(
    'pendentes',count(*) filter(where state='pendente'),
    -- Approved is a recorded decision, even while external cleanup is pending.
    'atendidos',count(*) filter(where state='aprovado'),
    'recusados',count(*) filter(where state='recusado'),
    'mais_antigo_segundos',case when count(*) filter(where state='pendente')>0
     then greatest(0,floor(extract(epoch from now()-min(created_at) filter(where state='pendente'))))::bigint end,
    'faixas_idade',jsonb_build_object(
     'menos_24h',count(*) filter(where state='pendente' and created_at>now()-interval '24 hours'),
     'de_1_a_3_dias',count(*) filter(where state='pendente' and created_at<=now()-interval '24 hours' and created_at>=now()-interval '3 days'),
     'mais_3_dias',count(*) filter(where state='pendente' and created_at<now()-interval '3 days')))
   from public.private_erasure_requests where igreja_id=p_tenant),
  -- Stored available/corrected states, excluding pending erasure suspensions.
  -- This is inventory, not evidence that runtime gates or origin checks pass.
  'resumos_ativos',(select count(*) from public.private_conversation_summaries s
   where s.igreja_id=p_tenant and s.state in ('available','corrected')
   and not exists(select 1 from public.private_erasure_requests r
    where r.igreja_id=p_tenant and r.pessoa_id=s.pessoa_id and r.state='pendente')),
  'retomadas_entregues',(select count(*) from public.messages
   where igreja_id=p_tenant and direcao='out' and autor='ia' and agent_reply_state='ia'
   and agent_privilege_context->>'kind'='private_resume'),
  'tarefas_resumo',(
   select jsonb_build_object('queued',count(*) filter(where state='queued'),
    'running',count(*) filter(where state='running'),'done',count(*) filter(where state='done'),
    'refused',count(*) filter(where state='refused'))
   from public.private_summary_tasks where igreja_id=p_tenant),
  'limpezas_privadas',(
   select jsonb_build_object('pendente',count(*) filter(where state='pendente'),
    'concluida',count(*) filter(where state='concluida'))
   from public.private_deletion_tasks where igreja_id=p_tenant)
 ) into result;
 return result;
end $$;
revoke all on function public.private_memory_overview(uuid) from public,anon,authenticated,service_role;
grant execute on function public.private_memory_overview(uuid) to authenticated;
commit;

-- Rollback (no data is removed; existing RLS and grants remain unchanged):
-- BEGIN;
-- DROP FUNCTION IF EXISTS public.private_memory_overview(uuid);
-- COMMIT;
