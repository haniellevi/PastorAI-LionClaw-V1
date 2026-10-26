-- Positive witness of a committed audio upload whose response was lost.
-- Depends on 20261030_100000 (dedicated private_storage_runtime login).
-- Synthetic PG first; apply with consumers contained, after backup, before
-- publishing the code that calls private_storage_begin_upload_attempt.
-- Every new attempt gets a random token, committed with its ownership before
-- the POST and sent as Storage user metadata. Only Storage info returning that
-- exact token proves the attempt committed; absence, errors or elapsed time
-- never release ownership. Legacy ownership (token NULL) stays retained and is
-- never discovered for reconciliation. No path, content or pastoral data here.
begin;
set local lock_timeout='2s';

-- witness_* only schedule the next read (bounded backoff); they never expire
-- ownership. The runtime may change only these two columns, never the token.
alter table public.private_deletion_uploads
 add column attempt_token uuid,
 add column witness_check_at timestamptz,
 add column witness_attempts integer not null default 0 check(witness_attempts >= 0);
grant update(witness_check_at,witness_attempts) on public.private_deletion_uploads to private_storage_runtime;

-- Same generation lock and checks as the boolean begin, which stays for
-- consumers still running the previous release (their rows remain legacy).
create function public.private_storage_begin_upload_attempt(p_tenant uuid,p_source uuid,p_conversation uuid,p_generation bigint)
returns uuid
language plpgsql security definer set search_path=pg_catalog,public,pg_temp set row_security=off as $$
declare v_token uuid;
begin
 if not public.private_storage_begin_upload(p_tenant,p_source,p_conversation,p_generation) then
  return null;
 end if;
 update public.private_deletion_uploads set attempt_token=pg_catalog.gen_random_uuid()
  where igreja_id=p_tenant and source_id=p_source and attempt_token is null
  returning attempt_token into v_token;
 if v_token is null then
  raise exception 'Ownership de upload sem tentativa' using errcode='55000';
 end if;
 return v_token;
end $$;
revoke all on function public.private_storage_begin_upload_attempt(uuid,uuid,uuid,bigint) from public,anon,authenticated,service_role;
grant execute on function public.private_storage_begin_upload_attempt(uuid,uuid,uuid,bigint) to private_storage_runtime;

-- Cross-tenant discovery of tokened ownership that blocks a pending cleanup
-- task, due for a witness read. IDs only; token and path are read afterwards
-- in the tenant-scoped transaction. One row per ownership, bounded batch.
create function public.private_storage_upload_witness_due(p_now timestamptz,p_limit integer)
returns table(task_id uuid,igreja_id uuid,receipt_id uuid,source_id uuid)
language plpgsql stable security definer set search_path=pg_catalog,public,pg_temp set row_security=off as $$
begin
 if not public.private_storage_runtime_session() then
  raise exception 'Runtime de Storage privado obrigatório' using errcode='42501';
 end if;
 if p_now is null or not isfinite(p_now) or p_limit is null or p_limit not between 1 and 100 then
  raise exception 'Parâmetros de descoberta inválidos' using errcode='22023';
 end if;
 return query select d.id,d.igreja_id,d.receipt_id,d.source_id from (
  select distinct on (u.igreja_id,u.source_id) t.id,t.igreja_id,t.receipt_id,t.source_id,u.witness_check_at
   from public.private_deletion_uploads u join public.private_deletion_tasks t
    on t.igreja_id=u.igreja_id and t.source_id=u.source_id
   where u.attempt_token is not null and t.state='pendente' and t.storage_path is not null
    and (u.witness_check_at is null or u.witness_check_at<=p_now)
   order by u.igreja_id,u.source_id,t.id) d
  order by d.witness_check_at nulls first,d.igreja_id,d.source_id limit p_limit;
end $$;
revoke all on function public.private_storage_upload_witness_due(timestamptz,integer) from public,anon,authenticated,service_role;
grant execute on function public.private_storage_upload_witness_due(timestamptz,integer) to private_storage_runtime;
commit;

-- Rollback: contain the new cron/audio consumers first. Ownership rows keep
-- blocking their tasks without the token (they become legacy and stay retained
-- until the previous release's finish or a nominal decision); never delete
-- them to complete receipts. Roll this back before 20261030_100000.
-- BEGIN;
-- DROP FUNCTION public.private_storage_upload_witness_due(timestamptz,integer);
-- DROP FUNCTION public.private_storage_begin_upload_attempt(uuid,uuid,uuid,bigint);
-- REVOKE UPDATE(witness_check_at,witness_attempts) ON public.private_deletion_uploads FROM private_storage_runtime;
-- ALTER TABLE public.private_deletion_uploads DROP COLUMN witness_attempts, DROP COLUMN witness_check_at, DROP COLUMN attempt_token;
-- DELETE FROM public.schema_migrations WHERE name='20261030_110000_private_upload_attempt_witness.sql';
-- COMMIT;
