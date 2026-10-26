-- Real SQL identity for private Storage maintenance (deletion tasks and audio
-- upload ownership only). Synthetic PG first; apply with consumers contained,
-- after backup, before publishing the code that uses PRIVATE_STORAGE_DATABASE_URL.
-- The role is created NOLOGIN without password: LOGIN/credential provisioning is
-- a separate nominal operation. Sends, event fences and summary tasks keep the
-- previous trusted-server pattern; this migration does not change them.
-- Not a defence against the database owner/superuser or operators holding
-- CREATEROLE/ADMIN on this role, who can still change or act as it.
-- Not idempotent by itself: re-running is refused (the role then has this
-- database's grants); reapply only after the commented rollback, via migrate.py.
begin;
set local lock_timeout='2s';

do $$
declare r pg_catalog.pg_roles%rowtype;
begin
 select * into r from pg_catalog.pg_roles where rolname='private_storage_runtime';
 if not found then
  create role private_storage_runtime nologin noinherit nosuperuser nobypassrls
   nocreatedb nocreaterole noreplication;
 elsif r.rolsuper or r.rolbypassrls or r.rolinherit or r.rolcreatedb or r.rolcreaterole
  or r.rolreplication or exists(select 1 from pg_catalog.pg_auth_members m where m.member=r.oid) then
  -- An existing LOGIN is a provisioned credential and is kept; anything that
  -- widens the identity is refused instead of silently repaired.
  raise exception 'private_storage_runtime preexistente com atributos inseguros' using errcode='42501';
 elsif exists(select 1 from pg_catalog.pg_shdepend d
  where d.refclassid='pg_catalog.pg_authid'::pg_catalog.regclass and d.refobjid=r.oid
   and (d.dbid=(select oid from pg_catalog.pg_database where datname=pg_catalog.current_database())
    or (d.dbid=0 and (d.deptype='o'
     or (d.classid='pg_catalog.pg_database'::pg_catalog.regclass
      and d.objid=(select oid from pg_catalog.pg_database where datname=pg_catalog.current_database()))
     or d.classid in ('pg_catalog.pg_parameter_acl'::pg_catalog.regclass,
                      'pg_catalog.pg_tablespace'::pg_catalog.regclass))))) then
  -- Attributes alone do not prove least privilege: objects owned, grants,
  -- policies or default ACLs here, grants on this database itself (e.g.
  -- CREATE), cluster-wide parameter or tablespace ACLs, and shared objects
  -- owned are refused too. Default CONNECT/TEMP come from PUBLIC, not the role.
  -- Objects and grants inside other databases belong to them and are ignored;
  -- they are never altered from here.
  raise exception 'private_storage_runtime preexistente com objetos ou privilégios no banco' using errcode='42501';
 end if;
end $$;
grant usage on schema public to private_storage_runtime;

-- The login itself is the identity: session_user, never SET ROLE or a GUC.
-- Inside SECURITY DEFINER current_user is the owner, so only session_user and
-- the login's own attributes are checked here; clients also prove
-- current_user=session_user before calling. Invoker, so policies can use it.
-- rolcanlogin is read live: an already open connection is refused after NOLOGIN
-- (NOLOGIN does not end that connection; containment stays operational).
create function public.private_storage_runtime_session() returns boolean
language sql stable set search_path=pg_catalog,public,pg_temp as $$
 select session_user='private_storage_runtime' and exists(
  select 1 from pg_catalog.pg_roles r where r.rolname=session_user and r.rolcanlogin
   and not r.rolsuper and not r.rolbypassrls and not r.rolinherit and not r.rolcreatedb
   and not r.rolcreaterole and not r.rolreplication
   and not exists(select 1 from pg_catalog.pg_auth_members m where m.member=r.oid))
$$;
revoke all on function public.private_storage_runtime_session() from public,anon,authenticated,service_role;
grant execute on function public.private_storage_runtime_session() to private_storage_runtime;

-- Tasks: the runtime reads/updates only its tenant's rows. Web admins keep the
-- existing column SELECT + task_admin_read for receipt progress, never paths.
drop policy task_worker on public.private_deletion_tasks;
revoke update on public.private_deletion_tasks from authenticated;
create policy task_private_storage on public.private_deletion_tasks for all to private_storage_runtime
 using(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
  and public.private_storage_runtime_session())
 with check(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
  and public.private_storage_runtime_session());
grant select(id,igreja_id,receipt_id,source_id,state,attempts,error_code,next_attempt_at),
 update(state,storage_path,attempts,error_code,next_attempt_at)
 on public.private_deletion_tasks to private_storage_runtime;

-- Uploads: ownership is created only by the begin function below; the runtime
-- reads and releases it in its tenant. No other session reaches this table.
drop policy upload_worker on public.private_deletion_uploads;
revoke all on public.private_deletion_uploads from public,anon,authenticated,service_role;
create policy upload_private_storage on public.private_deletion_uploads for all to private_storage_runtime
 using(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
  and public.private_storage_runtime_session())
 with check(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
  and public.private_storage_runtime_session());
grant select,delete on public.private_deletion_uploads to private_storage_runtime;

-- Paths stay behind a function; tenant comes only from the transaction GUC.
-- row_security=off raises if a misconfigured owner would silently filter rows.
create or replace function public.private_deletion_task_path(p_task uuid) returns text
language plpgsql stable security definer set search_path=pg_catalog,public,pg_temp set row_security=off as $$
begin
 if not public.private_storage_runtime_session() then
  raise exception 'Runtime de Storage privado obrigatório' using errcode='42501';
 end if;
 return (select storage_path from public.private_deletion_tasks where id=p_task
  and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid);
end $$;
revoke all on function public.private_deletion_task_path(uuid) from public,anon,authenticated,service_role;
grant execute on function public.private_deletion_task_path(uuid) to private_storage_runtime;

-- Cross-tenant discovery returns IDs and receipt only, for bounded batches.
create function public.private_storage_due_tasks(p_now timestamptz,p_limit integer)
returns table(id uuid,igreja_id uuid,receipt_id uuid)
language plpgsql stable security definer set search_path=pg_catalog,public,pg_temp set row_security=off as $$
begin
 if not public.private_storage_runtime_session() then
  raise exception 'Runtime de Storage privado obrigatório' using errcode='42501';
 end if;
 if p_now is null or not isfinite(p_now) or p_limit is null or p_limit not between 1 and 500 then
  raise exception 'Parâmetros de descoberta inválidos' using errcode='22023';
 end if;
 return query select t.id,t.igreja_id,t.receipt_id from public.private_deletion_tasks t
  where t.state='pendente' and t.next_attempt_at<=p_now and not exists(
   select 1 from public.private_deletion_uploads u where u.igreja_id=t.igreja_id and u.source_id=t.source_id)
  order by t.next_attempt_at,t.id limit p_limit;
end $$;
revoke all on function public.private_storage_due_tasks(timestamptz,integer) from public,anon,authenticated,service_role;
grant execute on function public.private_storage_due_tasks(timestamptz,integer) to private_storage_runtime;

-- Ownership is committed under the same conversation generation lock that
-- deletion takes, without granting the runtime any access to conversations.
create function public.private_storage_begin_upload(p_tenant uuid,p_source uuid,p_conversation uuid,p_generation bigint)
returns boolean
language plpgsql security definer set search_path=pg_catalog,public,pg_temp set row_security=off as $$
declare v_generation bigint;
begin
 if not public.private_storage_runtime_session() then
  raise exception 'Runtime de Storage privado obrigatório' using errcode='42501';
 end if;
 if p_tenant is null or p_tenant is distinct from nullif(current_setting('app.tenant_igreja_id',true),'')::uuid then
  raise exception 'Igreja fora do escopo' using errcode='42501';
 end if;
 if p_source is null or p_conversation is null or p_generation is null then
  raise exception 'Ownership de upload incompleta' using errcode='22004';
 end if;
 select deletion_generation into v_generation from public.conversations
  where igreja_id=p_tenant and id=p_conversation for update;
 if not found or v_generation is distinct from p_generation then
  return false;
 end if;
 insert into public.private_deletion_uploads(igreja_id,source_id,conversation_id,generation)
 values(p_tenant,p_source,p_conversation,p_generation) on conflict(igreja_id,source_id) do nothing;
 return found;
end $$;
revoke all on function public.private_storage_begin_upload(uuid,uuid,uuid,bigint) from public,anon,authenticated,service_role;
grant execute on function public.private_storage_begin_upload(uuid,uuid,uuid,bigint) to private_storage_runtime;
commit;

-- Rollback: contain the new cron/audio consumers, drain upload ownership and
-- preserve receipts/tasks first. A provisioned LOGIN aborts it: revoke the
-- credential by nominal decision first. The role is dropped only when no other
-- database still depends on it; their grants are never dropped from here.
-- BEGIN;
-- DO $$ BEGIN
--  IF EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='private_storage_runtime' AND rolcanlogin) THEN
--   RAISE EXCEPTION 'private_storage_runtime tem LOGIN provisionado; rollback interrompido' USING errcode='55000';
--  END IF;
-- END $$;
-- DROP FUNCTION public.private_storage_begin_upload(uuid,uuid,uuid,bigint);
-- DROP FUNCTION public.private_storage_due_tasks(timestamptz,integer);
-- CREATE OR REPLACE FUNCTION public.private_deletion_task_path(p_task uuid) RETURNS text
-- LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
-- BEGIN
--  IF session_user IN ('authenticator','authenticated','anon') OR
--   coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')<>'' THEN
--   RAISE EXCEPTION 'Worker obrigatório' USING errcode='42501';
--  END IF;
--  RETURN (SELECT storage_path FROM public.private_deletion_tasks WHERE id=p_task AND igreja_id=public.current_igreja_id());
-- END $$;
-- REVOKE ALL ON FUNCTION public.private_deletion_task_path(uuid) FROM public,anon,service_role,private_storage_runtime;
-- GRANT EXECUTE ON FUNCTION public.private_deletion_task_path(uuid) TO authenticated;
-- DROP POLICY upload_private_storage ON public.private_deletion_uploads;
-- DROP POLICY task_private_storage ON public.private_deletion_tasks;
-- REVOKE ALL ON public.private_deletion_uploads, public.private_deletion_tasks FROM private_storage_runtime;
-- CREATE POLICY upload_worker ON public.private_deletion_uploads FOR ALL TO authenticated
--  USING(igreja_id=public.current_igreja_id() AND session_user NOT IN ('authenticator','authenticated','anon') AND
--   coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='')
--  WITH CHECK(igreja_id=public.current_igreja_id() AND session_user NOT IN ('authenticator','authenticated','anon') AND
--   coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='');
-- GRANT SELECT,INSERT,DELETE ON public.private_deletion_uploads TO authenticated;
-- CREATE POLICY task_worker ON public.private_deletion_tasks FOR ALL TO authenticated
--  USING(igreja_id=public.current_igreja_id() AND session_user NOT IN ('authenticator','authenticated','anon') AND
--   coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='')
--  WITH CHECK(igreja_id=public.current_igreja_id() AND session_user NOT IN ('authenticator','authenticated','anon') AND
--   coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='');
-- GRANT UPDATE(state,storage_path,attempts,error_code,next_attempt_at) ON public.private_deletion_tasks TO authenticated;
-- DROP FUNCTION public.private_storage_runtime_session();
-- REVOKE USAGE ON SCHEMA public FROM private_storage_runtime;
-- DO $$ BEGIN
--  IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_shdepend d JOIN pg_catalog.pg_roles r ON r.oid=d.refobjid
--   WHERE d.refclassid='pg_catalog.pg_authid'::pg_catalog.regclass AND r.rolname='private_storage_runtime') THEN
--   DROP ROLE private_storage_runtime;
--  END IF;
-- END $$;
-- DELETE FROM public.schema_migrations WHERE name='20261030_100000_private_storage_worker_identity.sql';
-- COMMIT;
