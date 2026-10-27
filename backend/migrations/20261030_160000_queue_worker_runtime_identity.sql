-- Real SQL identity for the normal queue worker (QUEUE_WORKER_DATABASE_MODE=dedicated).
-- Synthetic PG first; apply after backup. The code keeps the legacy mode by
-- default and never reads this migration's objects there, so it may be applied
-- before or after the code. The role is created NOLOGIN without password:
-- LOGIN/credential provisioning and switching the mode are separate nominal
-- steps. The login gets exactly one membership, the builtin `authenticated`
-- (INHERIT FALSE, SET TRUE, no ADMIN): every scoped transaction keeps today's
-- `authenticated` grants and policies through the existing tenant seam; before
-- the seam it has no table privilege, only the instance lookup below.
-- Nothing is granted on domain tables, no policy changes and `authenticated`
-- is validated, never repaired. Membership is cluster-global and survives in
-- other databases: a preexisting role is accepted only NOLOGIN, with safe
-- attributes, no member able to SET or inherit it, at most that safe
-- membership and no object or privilege in this database. Not a defence
-- against the database owner/superuser/BYPASSRLS sessions, operators with
-- CREATEROLE/ADMIN, the main login (unchanged), nor a compromised worker
-- holding this credential (it still chooses the church GUC and may set JWT
-- claims, as the main login can). PostgreSQL 16+ grants with explicit options;
-- PostgreSQL 15 has no options and relies on the NOINHERIT login (PG15 path
-- checked only on a local image, not by the test suite).
-- Not idempotent by itself: re-running is refused (the role then has this
-- database's grants); reapply only after the commented rollback, via migrate.py.
begin;
set local lock_timeout='2s';

do $$
declare r pg_catalog.pg_roles%rowtype; a pg_catalog.pg_roles%rowtype;
begin
 select * into a from pg_catalog.pg_roles where rolname='authenticated';
 if not found then
  raise exception 'papel authenticated ausente' using errcode='42704';
 end if;
 -- The effective role of every scoped transaction: refuse, never repair.
 if a.rolsuper or a.rolbypassrls or a.rolcreaterole or a.rolcreatedb or a.rolreplication
  or exists(select 1 from pg_catalog.pg_auth_members m where m.member=a.oid)
  or exists(select 1 from pg_catalog.pg_class c where c.relowner=a.oid
   and c.relkind in ('r','p','f','m') and not c.relforcerowsecurity) then
  raise exception 'authenticated com atributos, memberships ou tabelas inseguros' using errcode='42501';
 end if;
 select * into r from pg_catalog.pg_roles where rolname='queue_worker_runtime';
 if not found then
  create role queue_worker_runtime nologin noinherit nosuperuser nobypassrls
   nocreatedb nocreaterole noreplication;
 elsif r.rolcanlogin or r.rolsuper or r.rolbypassrls or r.rolinherit or r.rolcreatedb
  or r.rolcreaterole or r.rolreplication
  or exists(select 1 from pg_catalog.pg_auth_members m where m.roleid=r.oid
   and (coalesce((pg_catalog.to_jsonb(m)->>'inherit_option')::boolean,true)
    or coalesce((pg_catalog.to_jsonb(m)->>'set_option')::boolean,true)))
  or exists(select 1 from pg_catalog.pg_auth_members m where m.member=r.oid
   and (m.roleid<>a.oid or m.admin_option
    or coalesce((pg_catalog.to_jsonb(m)->>'inherit_option')::boolean,false)
    or not coalesce((pg_catalog.to_jsonb(m)->>'set_option')::boolean,true))) then
  -- An unknown LOGIN or anything that widens the identity is refused.
  raise exception 'queue_worker_runtime preexistente com atributos inseguros' using errcode='42501';
 elsif exists(select 1 from pg_catalog.pg_shdepend d
  where d.refclassid='pg_catalog.pg_authid'::pg_catalog.regclass and d.refobjid=r.oid
   and (d.dbid=(select oid from pg_catalog.pg_database where datname=pg_catalog.current_database())
    or (d.dbid=0 and (d.deptype='o'
     or (d.classid='pg_catalog.pg_database'::pg_catalog.regclass
      and d.objid=(select oid from pg_catalog.pg_database where datname=pg_catalog.current_database()))
     or d.classid in ('pg_catalog.pg_parameter_acl'::pg_catalog.regclass,
                      'pg_catalog.pg_tablespace'::pg_catalog.regclass))))) then
  raise exception 'queue_worker_runtime preexistente com objetos ou privilégios no banco' using errcode='42501';
 end if;
 -- The single membership already created from another database is kept as is.
 if not exists(select 1 from pg_catalog.pg_auth_members m join pg_catalog.pg_roles q on q.oid=m.member
  where q.rolname='queue_worker_runtime') then
  if pg_catalog.current_setting('server_version_num')::integer >= 160000 then
   execute 'grant authenticated to queue_worker_runtime with inherit false, set true';
  else
   execute 'grant authenticated to queue_worker_runtime';
  end if;
 end if;
end $$;
grant usage on schema public to queue_worker_runtime;

-- The login itself is the identity (session_user), never SET ROLE or a GUC.
-- Attributes, the membership and the effective role are read live: NOLOGIN or
-- any drift refuses an already open connection too.
create function public.queue_worker_runtime_session() returns boolean
language sql stable set search_path=pg_catalog,public,pg_temp as $$
 select session_user='queue_worker_runtime' and exists(
  select 1 from pg_catalog.pg_roles r, pg_catalog.pg_roles a, pg_catalog.pg_database db
  where r.rolname=session_user and a.rolname='authenticated' and db.datname=pg_catalog.current_database()
   and r.rolcanlogin and not r.rolsuper and not r.rolbypassrls and not r.rolinherit
   and not r.rolcreatedb and not r.rolcreaterole and not r.rolreplication
   and exists(select 1 from pg_catalog.pg_auth_members m where m.member=r.oid)
   and not exists(select 1 from pg_catalog.pg_auth_members m where m.member=r.oid
    and (m.roleid<>a.oid or m.admin_option
     or coalesce((pg_catalog.to_jsonb(m)->>'inherit_option')::boolean,false)
     or not coalesce((pg_catalog.to_jsonb(m)->>'set_option')::boolean,true)))
   -- No member may SET or inherit the login. PostgreSQL 16+ gives a
   -- non-superuser creator ADMIN with INHERIT/SET FALSE: accepted as operator
   -- authority, outside the covered threat (it can still change grants).
   and not exists(select 1 from pg_catalog.pg_auth_members m where m.roleid=r.oid
    and (coalesce((pg_catalog.to_jsonb(m)->>'inherit_option')::boolean,true)
     or coalesce((pg_catalog.to_jsonb(m)->>'set_option')::boolean,true)))
   -- Nothing owned or granted directly in this database (or on shared objects)
   -- beyond USAGE on schema public and EXECUTE on the two queue functions,
   -- neither with GRANT OPTION. Privileges reached through PUBLIC are not this check.
   and not exists(select 1 from pg_catalog.pg_shdepend d
    where d.refclassid='pg_catalog.pg_authid'::pg_catalog.regclass and d.refobjid=r.oid
     and (d.dbid=db.oid or (d.dbid=0 and (d.deptype='o'
      or (d.classid='pg_catalog.pg_database'::pg_catalog.regclass and d.objid=db.oid)
      or d.classid in ('pg_catalog.pg_parameter_acl'::pg_catalog.regclass,
                       'pg_catalog.pg_tablespace'::pg_catalog.regclass))))
     -- IS NOT TRUE: an absent queue function makes to_regprocedure() NULL,
     -- and NOT(NULL) would silently hide any other dependency.
     and (d.deptype='a' and (
      (d.classid='pg_catalog.pg_namespace'::pg_catalog.regclass and d.objid=pg_catalog.to_regnamespace('public'))
      or (d.classid='pg_catalog.pg_proc'::pg_catalog.regclass and d.objid in (
       pg_catalog.to_regprocedure('public.queue_worker_runtime_session()'),
       pg_catalog.to_regprocedure('public.queue_resolve_instance(text)'))))) is not true)
   and not exists(select 1 from pg_catalog.pg_namespace n, pg_catalog.aclexplode(n.nspacl) x
    where n.nspname='public' and x.grantee=r.oid and (x.privilege_type<>'USAGE' or x.is_grantable))
   and not exists(select 1 from pg_catalog.pg_proc p, pg_catalog.aclexplode(p.proacl) x
    where p.oid in (pg_catalog.to_regprocedure('public.queue_worker_runtime_session()'),
     pg_catalog.to_regprocedure('public.queue_resolve_instance(text)'))
     and x.grantee=r.oid and (x.privilege_type<>'EXECUTE' or x.is_grantable))
   and not a.rolsuper and not a.rolbypassrls and not a.rolcreatedb and not a.rolcreaterole
   and not a.rolreplication
   and not exists(select 1 from pg_catalog.pg_auth_members m where m.member=a.oid)
   and not exists(select 1 from pg_catalog.pg_class c where c.relowner=a.oid
    and c.relkind in ('r','p','f','m') and not c.relforcerowsecurity))
$$;
revoke all on function public.queue_worker_runtime_session() from public,anon,authenticated,service_role;
grant execute on function public.queue_worker_runtime_session() to queue_worker_runtime;

-- Church discovery for ingestion: the Redis envelope carries only the raw
-- Evolution payload. Only the login itself, before the seam (role none, no
-- church GUC), in the ingestion transaction. Exact text match as the legacy
-- ORM lookup (no normalization or length limit: instances may come from
-- outside the panel); the partial unique index allows at most one row.
-- whatsapp_connections has no FORCE RLS: its owner reads it without BYPASSRLS.
create function public.queue_resolve_instance(p_instance text)
returns table(igreja_id uuid,numero text)
language plpgsql stable security definer set search_path=pg_catalog,public,pg_temp set row_security=off as $$
declare r record; n integer:=0;
begin
 if not public.queue_worker_runtime_session() or pg_catalog.current_setting('role')<>'none'
  or nullif(pg_catalog.current_setting('app.tenant_igreja_id',true),'') is not null then
  raise exception 'Runtime da fila obrigatório' using errcode='42501';
 end if;
 for r in select w.igreja_id,w.numero from public.whatsapp_connections w where w.instance=p_instance loop
  n:=n+1;
  if n>1 then
   raise exception 'Instância ambígua' using errcode='21000';
  end if;
  igreja_id:=r.igreja_id;
  numero:=r.numero;
  return next;
 end loop;
end $$;
revoke all on function public.queue_resolve_instance(text) from public,anon,authenticated,service_role;
grant execute on function public.queue_resolve_instance(text) to queue_worker_runtime;
commit;

-- Rollback: return the queue worker to QUEUE_WORKER_DATABASE_MODE=legacy (or
-- contain it) first; no domain data is touched. A provisioned LOGIN aborts it:
-- revoke the credential by nominal decision first. The role, and with it its
-- single membership, is dropped only when no other database depends on it;
-- then a NOTICE says it was kept. Anything else the role still owns or holds
-- in this database is drift: the rollback stops instead of looking clean.
-- BEGIN;
-- DO $$ BEGIN
--  IF EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='queue_worker_runtime' AND rolcanlogin) THEN
--   RAISE EXCEPTION 'queue_worker_runtime tem LOGIN provisionado; rollback interrompido' USING errcode='55000';
--  END IF;
-- END $$;
-- DROP FUNCTION public.queue_resolve_instance(text);
-- DROP FUNCTION public.queue_worker_runtime_session();
-- REVOKE USAGE ON SCHEMA public FROM queue_worker_runtime;
-- DO $$ BEGIN
--  IF EXISTS(SELECT 1 FROM pg_catalog.pg_shdepend d JOIN pg_catalog.pg_roles r ON r.oid=d.refobjid
--   WHERE d.refclassid='pg_catalog.pg_authid'::pg_catalog.regclass AND r.rolname='queue_worker_runtime'
--    AND d.dbid=(SELECT oid FROM pg_catalog.pg_database WHERE datname=pg_catalog.current_database())) THEN
--   RAISE EXCEPTION 'queue_worker_runtime ainda tem objetos ou privilégios neste banco; rollback interrompido' USING errcode='55000';
--  END IF;
--  IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_shdepend d JOIN pg_catalog.pg_roles r ON r.oid=d.refobjid
--   WHERE d.refclassid='pg_catalog.pg_authid'::pg_catalog.regclass AND r.rolname='queue_worker_runtime') THEN
--   DROP ROLE queue_worker_runtime;
--  ELSE
--   RAISE NOTICE 'queue_worker_runtime mantido (e sua membership): outro banco ou objeto compartilhado depende dele';
--  END IF;
-- END $$;
-- DELETE FROM public.schema_migrations WHERE name='20261030_160000_queue_worker_runtime_identity.sql';
-- COMMIT;
