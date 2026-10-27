-- Real SQL identity for the private summary generation cycle of the cron.
-- Synthetic PG first; apply with the cron worker contained, after backup,
-- before publishing the code that uses PRIVATE_SUMMARY_DATABASE_URL. The role
-- is created NOLOGIN without password: LOGIN/credential provisioning is a
-- separate nominal step. Generation stays off (release None, empty list).
-- Discovery, claim, reservation, projections and publication run on this
-- login; orchestration, ordering (barrier -> conversation -> task), the HTTP
-- boundary without a session and every revalidation stay in Python.
-- Nothing is revoked from `authenticated`: web enqueue/correction/reading,
-- resume and erasure requests keep their paths, and the main login keeps its
-- old capabilities (declared limit). Not a defence against the database
-- owner/superuser/BYPASSRLS sessions, operators with CREATEROLE/ADMIN on this
-- role, nor a compromised worker holding this credential (it can still write
-- summaries/sources of its pinned church, as the main login already can).
-- Not idempotent by itself: re-running is refused (the role then has this
-- database's grants); reapply only after the commented rollback, via migrate.py.
begin;
set local lock_timeout='2s';

do $$
declare r pg_catalog.pg_roles%rowtype;
begin
 select * into r from pg_catalog.pg_roles where rolname='private_summary_runtime';
 if not found then
  create role private_summary_runtime nologin noinherit nosuperuser nobypassrls
   nocreatedb nocreaterole noreplication;
 elsif r.rolsuper or r.rolbypassrls or r.rolinherit or r.rolcreatedb or r.rolcreaterole
  or r.rolreplication or exists(select 1 from pg_catalog.pg_auth_members m where m.member=r.oid) then
  -- Same preexisting-role guard as 20261030_120000: a provisioned LOGIN is
  -- kept; anything that widens the identity is refused, never repaired.
  raise exception 'private_summary_runtime preexistente com atributos inseguros' using errcode='42501';
 elsif exists(select 1 from pg_catalog.pg_shdepend d
  where d.refclassid='pg_catalog.pg_authid'::pg_catalog.regclass and d.refobjid=r.oid
   and (d.dbid=(select oid from pg_catalog.pg_database where datname=pg_catalog.current_database())
    or (d.dbid=0 and (d.deptype='o'
     or (d.classid='pg_catalog.pg_database'::pg_catalog.regclass
      and d.objid=(select oid from pg_catalog.pg_database where datname=pg_catalog.current_database()))
     or d.classid in ('pg_catalog.pg_parameter_acl'::pg_catalog.regclass,
                      'pg_catalog.pg_tablespace'::pg_catalog.regclass))))) then
  raise exception 'private_summary_runtime preexistente com objetos ou privilégios no banco' using errcode='42501';
 end if;
end $$;
grant usage on schema public to private_summary_runtime;

-- The login itself is the identity (session_user), never SET ROLE or a GUC.
-- rolcanlogin is read live, so NOLOGIN refuses an already open connection.
create function public.private_summary_runtime_session() returns boolean
language sql stable set search_path=pg_catalog,public,pg_temp as $$
 select session_user='private_summary_runtime' and exists(
  select 1 from pg_catalog.pg_roles r where r.rolname=session_user and r.rolcanlogin
   and not r.rolsuper and not r.rolbypassrls and not r.rolinherit and not r.rolcreatedb
   and not r.rolcreaterole and not r.rolreplication
   and not exists(select 1 from pg_catalog.pg_auth_members m where m.member=r.oid))
$$;
revoke all on function public.private_summary_runtime_session() from public,anon,authenticated,service_role;
grant execute on function public.private_summary_runtime_session() to private_summary_runtime;

-- Minimal grants on the four private tables only; no central table, no budget.
-- Policies need the live session check AND the transaction tenant GUC; the GUC
-- scopes rows, it never authenticates. FK checks run as the table owner.
grant select on public.private_summary_settings to private_summary_runtime;
create policy summary_runtime_select on public.private_summary_settings for select to private_summary_runtime
 using(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and public.private_summary_runtime_session());

-- Only queued/running rows are visible to UPDATE/FOR UPDATE and they can only
-- become running/done/refused: never re-queued (an abandoned call is never repeated).
grant select on public.private_summary_tasks to private_summary_runtime;
grant update(state,started_at,error_code) on public.private_summary_tasks to private_summary_runtime;
create policy summary_runtime_select on public.private_summary_tasks for select to private_summary_runtime
 using(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and public.private_summary_runtime_session());
create policy summary_runtime_update on public.private_summary_tasks for update to private_summary_runtime
 using(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and public.private_summary_runtime_session()
  and state in ('queued','running'))
 with check(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and public.private_summary_runtime_session()
  and state in ('running','done','refused'));

-- Exactly the columns of the service's upsert; human_correction is never updated.
grant select on public.private_conversation_summaries to private_summary_runtime;
grant insert(igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation,state,summary,human_correction)
 on public.private_conversation_summaries to private_summary_runtime;
grant update(source_revision,deletion_generation,state,summary,version,updated_at)
 on public.private_conversation_summaries to private_summary_runtime;
create policy summary_runtime_select on public.private_conversation_summaries for select to private_summary_runtime
 using(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and public.private_summary_runtime_session());
create policy summary_runtime_insert on public.private_conversation_summaries for insert to private_summary_runtime
 with check(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and public.private_summary_runtime_session());
create policy summary_runtime_update on public.private_conversation_summaries for update to private_summary_runtime
 using(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and public.private_summary_runtime_session())
 with check(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and public.private_summary_runtime_session());

grant select,insert,delete on public.private_summary_sources to private_summary_runtime;
create policy summary_runtime_select on public.private_summary_sources for select to private_summary_runtime
 using(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and public.private_summary_runtime_session());
create policy summary_runtime_insert on public.private_summary_sources for insert to private_summary_runtime
 with check(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and public.private_summary_runtime_session());
create policy summary_runtime_delete on public.private_summary_sources for delete to private_summary_runtime
 using(igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and public.private_summary_runtime_session());

-- Typed projections for central tables and the budget. Each checks the live
-- session first and, with a tenant, that it equals the transaction GUC.
-- row_security=off raises if a misconfigured owner would silently filter rows.

-- Discovery: IDs only, approved churches only (same predicate and order as before).
create function public.private_summary_runtime_due_tasks(p_tenants text[],p_limit integer)
returns table(igreja_id uuid,id uuid,conversation_id uuid)
language plpgsql stable security definer set search_path=pg_catalog,public,pg_temp set row_security=off as $$
begin
 if not public.private_summary_runtime_session() then
  raise exception 'Runtime de resumo privado obrigatório' using errcode='42501';
 end if;
 if p_tenants is null or cardinality(p_tenants) not between 1 and 100 or p_limit is null or p_limit not between 1 and 100 then
  raise exception 'Parâmetros de descoberta inválidos' using errcode='22023';
 end if;
 return query select t.igreja_id,t.id,t.conversation_id from public.private_summary_tasks t
  where t.igreja_id::text=any(p_tenants) and (t.state='queued' or (t.state='running' and t.started_at<now()-interval '2 minutes'))
  order by t.created_at,t.id limit p_limit;
end $$;

-- Same lock ordering as private_delete_content/enqueue: shared tenant barrier,
-- then the conversation row lock, both held until the caller's COMMIT.
create function public.private_summary_runtime_snapshot(p_tenant uuid,p_conversation uuid)
returns table(id uuid,pessoa_id uuid,private_summary_revision bigint,deletion_generation bigint)
language plpgsql security definer set search_path=pg_catalog,public,pg_temp set row_security=off as $$
declare r record;
begin
 if not public.private_summary_runtime_session() then
  raise exception 'Runtime de resumo privado obrigatório' using errcode='42501';
 end if;
 if p_tenant is null or p_tenant is distinct from nullif(current_setting('app.tenant_igreja_id',true),'')::uuid then
  raise exception 'Igreja fora do escopo' using errcode='42501';
 end if;
 if p_conversation is null then
  raise exception 'Conversa obrigatória' using errcode='22004';
 end if;
 perform pg_advisory_xact_lock_shared(hashtextextended('private-content:'||p_tenant::text,0));
 select c.id,c.pessoa_id,c.private_summary_revision,c.deletion_generation into r
  from public.conversations c where c.igreja_id=p_tenant and c.id=p_conversation for update;
 if not found then
  return;
 end if;
 if not public.private_summary_origin_valid(p_tenant,p_conversation,r.pessoa_id) then
  return;
 end if;
 return query select r.id,r.pessoa_id,r.private_summary_revision,r.deletion_generation;
end $$;

-- Message ids and closed operational codes only; never message text. The
-- whole conversation must still be a valid origin under the same locks.
create function public.private_summary_runtime_sources(p_tenant uuid,p_conversation uuid)
returns table(message_id uuid,topic text)
language plpgsql security definer set search_path=pg_catalog,public,pg_temp set row_security=off as $$
declare v_person uuid;
begin
 if not public.private_summary_runtime_session() then
  raise exception 'Runtime de resumo privado obrigatório' using errcode='42501';
 end if;
 if p_tenant is null or p_tenant is distinct from nullif(current_setting('app.tenant_igreja_id',true),'')::uuid then
  raise exception 'Igreja fora do escopo' using errcode='42501';
 end if;
 if p_conversation is null then
  raise exception 'Conversa obrigatória' using errcode='22004';
 end if;
 perform pg_advisory_xact_lock_shared(hashtextextended('private-content:'||p_tenant::text,0));
 select c.pessoa_id into v_person from public.conversations c
  where c.igreja_id=p_tenant and c.id=p_conversation for update;
 if not found or not public.private_summary_origin_valid(p_tenant,p_conversation,v_person) then
  raise exception 'Origem do resumo inválida' using errcode='55000';
 end if;
 return query select m.id,public.private_summary_topic(m.texto) from public.messages m
  where m.igreja_id=p_tenant and m.conversation_id=p_conversation order by m.criado_em,m.id;
end $$;

-- Literal transcription of the service rule: a NULL requester is the trusted
-- scheduled backend; otherwise an active admin/pastor with inbox access.
create function public.private_summary_runtime_requester(p_tenant uuid,p_user uuid) returns boolean
language plpgsql stable security definer set search_path=pg_catalog,public,pg_temp set row_security=off as $$
begin
 if not public.private_summary_runtime_session() then
  raise exception 'Runtime de resumo privado obrigatório' using errcode='42501';
 end if;
 if p_tenant is null or p_tenant is distinct from nullif(current_setting('app.tenant_igreja_id',true),'')::uuid then
  raise exception 'Igreja fora do escopo' using errcode='42501';
 end if;
 if p_user is null then
  return true;
 end if;
 return exists(select 1 from public.app_users a join public.user_roles r
  on r.igreja_id=a.igreja_id and r.user_id=a.id where a.igreja_id=p_tenant and a.id=p_user
  and a.status='ativo' and r.papel in ('admin','pastor')
  and (a.pessoa_id is null or exists(select 1 from public.pessoas p where p.igreja_id=p_tenant and p.id=a.pessoa_id and p.arquivada_em is null))
  and (r.papel='admin' or not exists(select 1 from public.role_permissions rp where rp.igreja_id=p_tenant and rp.papel::text=r.papel::text)
  or exists(select 1 from public.role_permissions rp where rp.igreja_id=p_tenant and rp.papel::text=r.papel::text and rp.tela='inbox')));
end $$;

-- Same filter as before; every matching row is returned so the caller keeps
-- its cardinality check. The model allowlist stays in Python.
create function public.private_summary_runtime_credential(p_tenant uuid)
returns table(id uuid,igreja_id uuid,modelo text,api_key_encrypted text)
language plpgsql stable security definer set search_path=pg_catalog,public,pg_temp set row_security=off as $$
begin
 if not public.private_summary_runtime_session() then
  raise exception 'Runtime de resumo privado obrigatório' using errcode='42501';
 end if;
 if p_tenant is null or p_tenant is distinct from nullif(current_setting('app.tenant_igreja_id',true),'')::uuid then
  raise exception 'Igreja fora do escopo' using errcode='42501';
 end if;
 return query select l.id,l.igreja_id,l.modelo,l.api_key_encrypted from public.llm_credentials l
  where l.igreja_id=p_tenant and l.ativo and l.validado and l.provedor='openai';
end $$;

-- Literal transcription of reserve_budget with the fixed conservative cost
-- (100,000 microdollars). No cost argument, no reset, no refund.
create function public.private_summary_runtime_reserve(p_tenant uuid) returns boolean
language plpgsql security definer set search_path=pg_catalog,public,pg_temp set row_security=off as $$
declare v_reserved bigint;
begin
 if not public.private_summary_runtime_session() then
  raise exception 'Runtime de resumo privado obrigatório' using errcode='42501';
 end if;
 if p_tenant is null or p_tenant is distinct from nullif(current_setting('app.tenant_igreja_id',true),'')::uuid then
  raise exception 'Igreja fora do escopo' using errcode='42501';
 end if;
 insert into public.private_summary_budget(igreja_id,month,reserved_microusd)
 select p_tenant,date_trunc('month',now())::date,100000 from public.private_summary_settings
 where igreja_id=p_tenant and enabled and monthly_limit_microusd>=100000
 on conflict(igreja_id,month) do update set reserved_microusd=private_summary_budget.reserved_microusd+100000
 where private_summary_budget.reserved_microusd+100000 <=
  (select monthly_limit_microusd from public.private_summary_settings where igreja_id=p_tenant and enabled)
 returning reserved_microusd into v_reserved;
 return v_reserved is not null;
end $$;

do $$ declare sig text; begin
 foreach sig in array array['private_summary_runtime_due_tasks(text[],integer)','private_summary_runtime_snapshot(uuid,uuid)',
  'private_summary_runtime_sources(uuid,uuid)','private_summary_runtime_requester(uuid,uuid)',
  'private_summary_runtime_credential(uuid)','private_summary_runtime_reserve(uuid)'] loop
  execute 'revoke all on function public.'||sig||' from public,anon,authenticated,service_role';
  execute 'grant execute on function public.'||sig||' to private_summary_runtime';
 end loop;
end $$;
commit;

-- Rollback: contain the cron worker first; summaries, sources, tasks and the
-- budget are preserved (the main login's old path stays intact). A provisioned
-- LOGIN aborts it: revoke the credential by nominal decision first. The role is
-- dropped only when no other database still depends on it.
-- BEGIN;
-- DO $$ BEGIN
--  IF EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='private_summary_runtime' AND rolcanlogin) THEN
--   RAISE EXCEPTION 'private_summary_runtime tem LOGIN provisionado; rollback interrompido' USING errcode='55000';
--  END IF;
-- END $$;
-- DROP FUNCTION public.private_summary_runtime_reserve(uuid);
-- DROP FUNCTION public.private_summary_runtime_credential(uuid);
-- DROP FUNCTION public.private_summary_runtime_requester(uuid,uuid);
-- DROP FUNCTION public.private_summary_runtime_sources(uuid,uuid);
-- DROP FUNCTION public.private_summary_runtime_snapshot(uuid,uuid);
-- DROP FUNCTION public.private_summary_runtime_due_tasks(text[],integer);
-- DROP POLICY summary_runtime_delete ON public.private_summary_sources;
-- DROP POLICY summary_runtime_insert ON public.private_summary_sources;
-- DROP POLICY summary_runtime_select ON public.private_summary_sources;
-- DROP POLICY summary_runtime_update ON public.private_conversation_summaries;
-- DROP POLICY summary_runtime_insert ON public.private_conversation_summaries;
-- DROP POLICY summary_runtime_select ON public.private_conversation_summaries;
-- DROP POLICY summary_runtime_update ON public.private_summary_tasks;
-- DROP POLICY summary_runtime_select ON public.private_summary_tasks;
-- DROP POLICY summary_runtime_select ON public.private_summary_settings;
-- REVOKE ALL ON public.private_summary_sources FROM private_summary_runtime;
-- REVOKE ALL ON public.private_conversation_summaries FROM private_summary_runtime;
-- REVOKE ALL ON public.private_summary_tasks FROM private_summary_runtime;
-- REVOKE ALL ON public.private_summary_settings FROM private_summary_runtime;
-- DROP FUNCTION public.private_summary_runtime_session();
-- REVOKE USAGE ON SCHEMA public FROM private_summary_runtime;
-- DO $$ BEGIN
--  IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_shdepend d JOIN pg_catalog.pg_roles r ON r.oid=d.refobjid
--   WHERE d.refclassid='pg_catalog.pg_authid'::pg_catalog.regclass AND r.rolname='private_summary_runtime') THEN
--   DROP ROLE private_summary_runtime;
--  END IF;
-- END $$;
-- DELETE FROM public.schema_migrations WHERE name='20261030_140000_private_summary_runtime_identity.sql';
-- COMMIT;
