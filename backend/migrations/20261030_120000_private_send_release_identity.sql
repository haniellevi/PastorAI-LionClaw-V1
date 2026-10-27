-- Real SQL identity for releasing agent send ownership (private_deletion_sends).
-- Synthetic PG first; apply with the queue worker and any reply delivery
-- contained, after backup, before publishing the code that uses
-- PRIVATE_SEND_DATABASE_URL. Old code against this schema fails its release
-- (DELETE denied), so containment is mandatory. The role is created NOLOGIN
-- without password: LOGIN/credential provisioning is a separate nominal step.
-- INSERT, renewal and generation checks stay in the queue's domain
-- transactions on the main login; only the subject-less DELETE path moves.
-- Scope of the protection: the `authenticated` path (tenant-scoped sessions of
-- API, cron and queue) can no longer erase ownership and turn a receipt green.
-- Not a defence against the database owner/superuser/BYPASSRLS sessions (a
-- main login used without SET ROLE, e.g. cross-tenant mode) or operators with
-- CREATEROLE/ADMIN on this role, who can still change or act as it.
-- Not idempotent by itself: re-running is refused (the role then has this
-- database's grants); reapply only after the commented rollback, via migrate.py.
begin;
set local lock_timeout='2s';

do $$
declare r pg_catalog.pg_roles%rowtype;
begin
 select * into r from pg_catalog.pg_roles where rolname='private_send_runtime';
 if not found then
  create role private_send_runtime nologin noinherit nosuperuser nobypassrls
   nocreatedb nocreaterole noreplication;
 elsif r.rolsuper or r.rolbypassrls or r.rolinherit or r.rolcreatedb or r.rolcreaterole
  or r.rolreplication or exists(select 1 from pg_catalog.pg_auth_members m where m.member=r.oid) then
  -- Same preexisting-role guard as 20261030_100000: a provisioned LOGIN is
  -- kept; anything that widens the identity is refused, never repaired.
  raise exception 'private_send_runtime preexistente com atributos inseguros' using errcode='42501';
 elsif exists(select 1 from pg_catalog.pg_shdepend d
  where d.refclassid='pg_catalog.pg_authid'::pg_catalog.regclass and d.refobjid=r.oid
   and (d.dbid=(select oid from pg_catalog.pg_database where datname=pg_catalog.current_database())
    or (d.dbid=0 and (d.deptype='o'
     or (d.classid='pg_catalog.pg_database'::pg_catalog.regclass
      and d.objid=(select oid from pg_catalog.pg_database where datname=pg_catalog.current_database()))
     or d.classid in ('pg_catalog.pg_parameter_acl'::pg_catalog.regclass,
                      'pg_catalog.pg_tablespace'::pg_catalog.regclass))))) then
  -- Objects, grants, policies or default ACLs here, grants on this database,
  -- parameter/tablespace ACLs and owned shared objects are refused; other
  -- databases' grants are theirs and never altered from here.
  raise exception 'private_send_runtime preexistente com objetos ou privilégios no banco' using errcode='42501';
 end if;
end $$;
grant usage on schema public to private_send_runtime;

-- The login itself is the identity (session_user), never SET ROLE or a GUC.
-- rolcanlogin is read live, so NOLOGIN refuses an already open connection.
create function public.private_send_runtime_session() returns boolean
language sql stable set search_path=pg_catalog,public,pg_temp as $$
 select session_user='private_send_runtime' and exists(
  select 1 from pg_catalog.pg_roles r where r.rolname=session_user and r.rolcanlogin
   and not r.rolsuper and not r.rolbypassrls and not r.rolinherit and not r.rolcreatedb
   and not r.rolcreaterole and not r.rolreplication
   and not exists(select 1 from pg_catalog.pg_auth_members m where m.member=r.oid))
$$;
revoke all on function public.private_send_runtime_session() from public,anon,authenticated,service_role;
grant execute on function public.private_send_runtime_session() to private_send_runtime;

-- Main login keeps SELECT, INSERT and UPDATE(expires_at) under the same
-- subject-less expressions as before; DELETE has no grant and no policy.
-- send_admin_read (receipt counter) is unchanged.
drop policy send_worker on public.private_deletion_sends;
create policy send_worker_select on public.private_deletion_sends for select to authenticated
 using(igreja_id=public.current_igreja_id() and session_user not in ('authenticator','authenticated','anon') and
  coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='');
create policy send_worker_insert on public.private_deletion_sends for insert to authenticated
 with check(igreja_id=public.current_igreja_id() and session_user not in ('authenticator','authenticated','anon') and
  coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='');
create policy send_worker_update on public.private_deletion_sends for update to authenticated
 using(igreja_id=public.current_igreja_id() and session_user not in ('authenticator','authenticated','anon') and
  coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='')
 with check(igreja_id=public.current_igreja_id() and session_user not in ('authenticator','authenticated','anon') and
  coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='');
revoke delete on public.private_deletion_sends from authenticated;

-- Release by key only: no table grant, no SELECT, no generation check (it must
-- also release after deletion moved the generation, as before). The tenant
-- GUC scopes the call; it never authorizes by itself. row_security=off raises
-- if a misconfigured owner would silently filter rows.
create function public.private_send_release(p_tenant uuid,p_source uuid) returns boolean
language plpgsql security definer set search_path=pg_catalog,public,pg_temp set row_security=off as $$
begin
 if not public.private_send_runtime_session() then
  raise exception 'Runtime de liberação de envio obrigatório' using errcode='42501';
 end if;
 if p_tenant is null or p_tenant is distinct from nullif(current_setting('app.tenant_igreja_id',true),'')::uuid then
  raise exception 'Igreja fora do escopo' using errcode='42501';
 end if;
 if p_source is null then
  raise exception 'Ownership de envio incompleta' using errcode='22004';
 end if;
 delete from public.private_deletion_sends where igreja_id=p_tenant and source_id=p_source;
 return found;
end $$;
revoke all on function public.private_send_release(uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.private_send_release(uuid,uuid) to private_send_runtime;
commit;

-- Rollback: contain the queue worker and reply delivery first; rows in
-- private_deletion_sends are preserved (ownership retained during failure
-- windows needs explicit reconciliation, never a blind DELETE). A provisioned
-- LOGIN aborts it: revoke the credential by nominal decision first. The role is
-- dropped only when no other database still depends on it.
-- BEGIN;
-- DO $$ BEGIN
--  IF EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='private_send_runtime' AND rolcanlogin) THEN
--   RAISE EXCEPTION 'private_send_runtime tem LOGIN provisionado; rollback interrompido' USING errcode='55000';
--  END IF;
-- END $$;
-- DROP FUNCTION public.private_send_release(uuid,uuid);
-- DROP POLICY send_worker_update ON public.private_deletion_sends;
-- DROP POLICY send_worker_insert ON public.private_deletion_sends;
-- DROP POLICY send_worker_select ON public.private_deletion_sends;
-- CREATE POLICY send_worker ON public.private_deletion_sends FOR ALL TO authenticated
--  USING(igreja_id=public.current_igreja_id() AND session_user NOT IN ('authenticator','authenticated','anon') AND
--   coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='')
--  WITH CHECK(igreja_id=public.current_igreja_id() AND session_user NOT IN ('authenticator','authenticated','anon') AND
--   coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='');
-- GRANT DELETE ON public.private_deletion_sends TO authenticated;
-- DROP FUNCTION public.private_send_runtime_session();
-- REVOKE USAGE ON SCHEMA public FROM private_send_runtime;
-- DO $$ BEGIN
--  IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_shdepend d JOIN pg_catalog.pg_roles r ON r.oid=d.refobjid
--   WHERE d.refclassid='pg_catalog.pg_authid'::pg_catalog.regclass AND r.rolname='private_send_runtime') THEN
--   DROP ROLE private_send_runtime;
--  END IF;
-- END $$;
-- DELETE FROM public.schema_migrations WHERE name='20261030_120000_private_send_release_identity.sql';
-- COMMIT;
