-- Church private reset fulfills every pending request covered by its receipt.
set local lock_timeout='2s';

-- Keep the existing tenant boundary and policies in force for the audit ledger.
alter table public.private_erasure_requests enable row level security;
alter table public.private_erasure_requests force row level security;

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
 if rid is not null and p_scope in ('pessoa','igreja') and not replay then
  select id into actor from public.app_users where igreja_id=p_tenant
   and clerk_user_id=public.prayer_jwt_sub() and status='ativo';
  if p_scope='pessoa' then
   update public.private_erasure_requests set state='aprovado',decided_at=now(),
    decided_by=actor,receipt_id=rid
    where igreja_id=p_tenant and pessoa_id=p_target and state='pendente';
  else
   update public.private_erasure_requests set state='aprovado',decided_at=now(),
    decided_by=actor,receipt_id=rid
    where igreja_id=p_tenant and state='pendente';
  end if;
 end if;
 return rid;
end $$;
-- Preserve the existing SECURITY DEFINER grant boundary; callers get no table write grant.
revoke all on function public.private_delete_scope(uuid,text,uuid,uuid) from public,anon,service_role;
grant execute on function public.private_delete_scope(uuid,text,uuid,uuid) to authenticated;

-- Rollback: restore the 20261027 wrapper, which fulfills person requests only.
-- CREATE OR REPLACE FUNCTION public.private_delete_scope(p_tenant uuid,p_scope text,p_target uuid,p_operation uuid) RETURNS uuid
-- LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $rollback$
-- DECLARE rid uuid; replay boolean; actor uuid;
-- BEGIN
--  IF p_tenant IS DISTINCT FROM public.current_igreja_id() OR NOT public.private_deletion_admin() THEN
--   RAISE EXCEPTION 'Exclusão não autorizada' USING errcode='42501';
--  END IF;
--  PERFORM pg_advisory_xact_lock(hashtextextended('private-content:'||p_tenant::text,0));
--  SELECT EXISTS(SELECT 1 FROM public.private_deletion_receipts WHERE igreja_id=p_tenant
--   AND scope=p_scope AND target_id=p_target AND operation_id=p_operation) INTO replay;
--  rid:=public.private_delete_content(p_tenant,p_scope,p_target,p_operation);
--  IF rid IS NOT NULL AND p_scope='pessoa' AND NOT replay THEN
--   SELECT id INTO actor FROM public.app_users WHERE igreja_id=p_tenant
--    AND clerk_user_id=public.prayer_jwt_sub() AND status='ativo';
--   UPDATE public.private_erasure_requests SET state='aprovado',decided_at=now(),
--    decided_by=actor,receipt_id=rid
--    WHERE igreja_id=p_tenant AND pessoa_id=p_target AND state='pendente';
--  END IF;
--  RETURN rid;
-- END $rollback$;
-- REVOKE ALL ON FUNCTION public.private_delete_scope(uuid,text,uuid,uuid) FROM public,anon,service_role;
-- GRANT EXECUTE ON FUNCTION public.private_delete_scope(uuid,text,uuid,uuid) TO authenticated;
