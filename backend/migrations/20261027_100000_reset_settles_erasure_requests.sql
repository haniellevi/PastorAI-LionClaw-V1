-- Manual person reset fulfills pending requests using the existing approved state.
-- IDs-only audit shares the deletion transaction, tenant barrier and receipt.
begin;
set local lock_timeout='2s';
create or replace function public.private_delete_scope(p_tenant uuid,p_scope text,p_target uuid,p_operation uuid) returns uuid
language plpgsql security definer set search_path=pg_catalog,public as $$
declare rid uuid; replay boolean; actor uuid;
begin
 if p_tenant is distinct from public.current_igreja_id() or not public.private_deletion_admin() then
  raise exception 'Exclusão não autorizada' using errcode='42501';
 end if;
 perform pg_advisory_xact_lock(hashtextextended('private-content:'||p_tenant::text,0));
 select exists(select 1 from public.private_deletion_receipts where igreja_id=p_tenant
  and scope=p_scope and target_id=p_target and operation_id=p_operation) into replay;
 rid:=public.private_delete_content(p_tenant,p_scope,p_target,p_operation);
 -- A replay must never fulfill a newer request without deleting its content.
 if rid is not null and p_scope='pessoa' and not replay then
  select id into actor from public.app_users where igreja_id=p_tenant
   and clerk_user_id=public.prayer_jwt_sub() and status='ativo';
  update public.private_erasure_requests set state='aprovado',decided_at=now(),
   decided_by=actor,receipt_id=rid
   where igreja_id=p_tenant and pessoa_id=p_target and state='pendente';
 end if;
 return rid;
end $$;
-- Existing FORCE RLS/read policies remain intact; no direct ledger write grant.
revoke all on function public.private_delete_scope(uuid,text,uuid,uuid) from public,anon,service_role;
grant execute on function public.private_delete_scope(uuid,text,uuid,uuid) to authenticated;
commit;
-- Rollback: stop consumers first; preserve approved requests and linked receipts.
-- Restores the previous wrapper, without reopening fulfilled requests:
-- CREATE OR REPLACE FUNCTION public.private_delete_scope(p_tenant uuid,p_scope text,p_target uuid,p_operation uuid) RETURNS uuid
-- LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $rollback$
-- BEGIN
--  IF p_tenant IS DISTINCT FROM public.current_igreja_id() OR NOT public.private_deletion_admin() THEN
--   RAISE EXCEPTION 'Exclusão não autorizada' USING errcode='42501';
--  END IF;
--  RETURN public.private_delete_content(p_tenant,p_scope,p_target,p_operation);
-- END $rollback$;
