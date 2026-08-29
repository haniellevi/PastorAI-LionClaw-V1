-- Compatibility scaffold for the isolated canonical-schema derivation lab.
--
-- This file is not a PastorAI migration and must never be copied into
-- backend/migrations.  It supplies only the three Supabase application roles
-- required by the versioned catalog.  The database connection role remains
-- the derived owner of every object created by the replay.  Realtime, Auth,
-- Storage, Data API objects and both migration ledgers are deliberately absent.

begin;

set local search_path = pg_catalog;

do $canonical_schema_roles$
begin
  if pg_catalog.to_regrole('anon') is not null
     or pg_catalog.to_regrole('authenticated') is not null
     or pg_catalog.to_regrole('service_role') is not null
     or pg_catalog.to_regrole('agent_runtime') is not null
  then
    raise exception using
      errcode = 'P0001',
      message = 'canonical schema scaffold requires fresh application roles';
  end if;

  create role anon
    nologin noinherit nosuperuser nobypassrls
    nocreatedb nocreaterole noreplication;

  create role authenticated
    nologin noinherit nosuperuser nobypassrls
    nocreatedb nocreaterole noreplication;

  create role service_role
    nologin noinherit nosuperuser bypassrls
    nocreatedb nocreaterole noreplication;
end
$canonical_schema_roles$;

alter schema public owner to current_user;
revoke create on schema public from public;
grant usage on schema public to public;

commit;
