-- PastorAI D2A: fundacao privada e inativa do runtime do agente.
--
-- Esta fatia cria somente a identidade PostgreSQL sem LOGIN, o schema privado
-- e o helper transacional de tenant. Ela nao cria tabelas, nao instala o
-- checkpointer, nao provisiona credencial e nao conecta o worker ao novo papel.
-- Qualquer tabela futura neste schema exige migration propria com igreja_id,
-- ENABLE/FORCE RLS, policies e grants minimos.

begin;

set transaction isolation level serializable;
set local search_path = pg_catalog;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- Serializa aplicacoes concorrentes sem bloquear tabelas de dominio.
select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('pastorai:d2a:agent-runtime-private-context', 0)
);

do $role_guard$
declare
  runtime_role pg_catalog.pg_roles%rowtype;
  runtime_role_oid oid;
  executor_role_oid oid := pg_catalog.to_regrole(current_user)::oid;
  expected_settings text[] := array[
    'row_security=on',
    'search_path=pg_catalog, agent_private'
  ];
begin
  select * into runtime_role
    from pg_catalog.pg_roles
   where rolname = 'agent_runtime';

  if not found then
    create role agent_runtime
      nologin
      noinherit
      nosuperuser
      nobypassrls
      nocreatedb
      nocreaterole
      noreplication;

    alter role agent_runtime set row_security = on;
    alter role agent_runtime set search_path = pg_catalog, agent_private;

  elsif runtime_role.rolcanlogin then
    raise exception using
      errcode = 'P0001',
      message = 'D2A replay blocked: role agent_runtime is already provisioned';

  end if;

  -- Credencial pertence a um gate operacional posterior. Enquanto a role esta
  -- inativa, a migration garante NOLOGIN e remove qualquer senha latente sem
  -- ler o catalogo restrito de hashes. Uma role ja provisionada aborta antes
  -- deste ponto para que replay de migration nunca cause indisponibilidade.
  -- Se outro atributo ou membership for inseguro, a excecao abaixo reverte
  -- tambem este ALTER ROLE e preserva a atomicidade.
  alter role agent_runtime nologin password null;

  select * into strict runtime_role
    from pg_catalog.pg_roles
   where rolname = 'agent_runtime';

  runtime_role_oid := runtime_role.oid;

  if runtime_role.rolcanlogin
     or runtime_role.rolinherit
     or runtime_role.rolsuper
     or runtime_role.rolbypassrls
     or runtime_role.rolcreatedb
     or runtime_role.rolcreaterole
     or runtime_role.rolreplication
     or runtime_role.rolconnlimit <> -1
     or runtime_role.rolvaliduntil is not null
     or coalesce(pg_catalog.cardinality(runtime_role.rolconfig), 0)
        <> pg_catalog.cardinality(expected_settings)
     or not coalesce(runtime_role.rolconfig, array[]::text[])
        @> expected_settings
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2A catalog conflict: role agent_runtime has unsafe attributes';
  end if;

  if exists (
    select 1
      from pg_catalog.pg_auth_members membership
     where membership.member = runtime_role_oid
        or (
          membership.roleid = runtime_role_oid
          and not (
            membership.member = executor_role_oid
            and membership.admin_option
            and not membership.inherit_option
            and not membership.set_option
          )
        )
  ) then
    raise exception using
      errcode = 'P0001',
      message = 'D2A catalog conflict: role agent_runtime has unsafe memberships';
  end if;
end
$role_guard$;

do $schema_guard$
declare
  private_schema pg_catalog.pg_namespace%rowtype;
  owner_oid oid := pg_catalog.to_regrole(current_user)::oid;
  runtime_oid oid := pg_catalog.to_regrole('agent_runtime')::oid;
begin
  select * into private_schema
    from pg_catalog.pg_namespace
   where nspname = 'agent_private';

  if not found then
    create schema agent_private authorization current_user;
    revoke all privileges on schema agent_private
      from public, anon, authenticated, service_role;
    revoke create on schema agent_private from agent_runtime;
    grant usage on schema agent_private to agent_runtime;

    select * into strict private_schema
      from pg_catalog.pg_namespace
     where nspname = 'agent_private';
  end if;

  if private_schema.nspowner <> owner_oid
     or not pg_catalog.has_schema_privilege(
       'agent_runtime', 'agent_private', 'USAGE'
     )
     or pg_catalog.has_schema_privilege(
       'agent_runtime', 'agent_private', 'CREATE'
     )
     or pg_catalog.has_schema_privilege('anon', 'agent_private', 'USAGE')
     or pg_catalog.has_schema_privilege(
       'authenticated', 'agent_private', 'USAGE'
     )
     or pg_catalog.has_schema_privilege(
       'service_role', 'agent_private', 'USAGE'
     )
     or exists (
       select 1
         from pg_catalog.aclexplode(
           coalesce(
             private_schema.nspacl,
             pg_catalog.acldefault('n', private_schema.nspowner)
           )
         ) acl
        where not (
          (
            acl.grantee = owner_oid
            and acl.privilege_type in ('USAGE', 'CREATE')
          )
          or (
            acl.grantee = runtime_oid
            and acl.privilege_type = 'USAGE'
            and not acl.is_grantable
          )
        )
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2A catalog conflict: schema agent_private has unsafe ownership or ACL';
  end if;

end
$schema_guard$;

do $function_guard$
declare
  tenant_function pg_catalog.pg_proc%rowtype;
  function_oid oid;
  owner_oid oid := pg_catalog.to_regrole(current_user)::oid;
  runtime_oid oid := pg_catalog.to_regrole('agent_runtime')::oid;
  sql_language_oid oid := (
    select oid from pg_catalog.pg_language where lanname = 'sql'
  );
  expected_source text := $expected_source$
    select nullif(
      pg_catalog.current_setting('app.tenant_igreja_id', true),
      ''
    )::pg_catalog.uuid
  $expected_source$;
begin
  function_oid := pg_catalog.to_regprocedure(
    'agent_private.current_tenant_id()'
  );

  if function_oid is null then
    execute $create_function$
      create function agent_private.current_tenant_id()
      returns uuid
      language sql
      stable
      security invoker
      set search_path = pg_catalog
      as $body$
        select nullif(
          pg_catalog.current_setting('app.tenant_igreja_id', true),
          ''
        )::pg_catalog.uuid
      $body$
    $create_function$;

    revoke all privileges on function agent_private.current_tenant_id()
      from public, anon, authenticated, service_role;
    grant execute on function agent_private.current_tenant_id()
      to agent_runtime;

    function_oid := pg_catalog.to_regprocedure(
      'agent_private.current_tenant_id()'
    );
  end if;

  select * into strict tenant_function
    from pg_catalog.pg_proc
   where oid = function_oid;

  if tenant_function.proowner <> owner_oid
     or tenant_function.prolang <> sql_language_oid
     or tenant_function.prorettype <> 'pg_catalog.uuid'::pg_catalog.regtype
     or tenant_function.pronargs <> 0
     or tenant_function.provolatile <> 's'
     or tenant_function.prosecdef
     or tenant_function.proleakproof
     or tenant_function.proconfig is distinct from array['search_path=pg_catalog']
     or pg_catalog.regexp_replace(
       tenant_function.prosrc, '[[:space:]]+', '', 'g'
     ) <> pg_catalog.regexp_replace(
       expected_source, '[[:space:]]+', '', 'g'
     )
     or not pg_catalog.has_function_privilege(
       'agent_runtime', function_oid, 'EXECUTE'
     )
     or pg_catalog.has_function_privilege('anon', function_oid, 'EXECUTE')
     or pg_catalog.has_function_privilege(
       'authenticated', function_oid, 'EXECUTE'
     )
     or pg_catalog.has_function_privilege(
       'service_role', function_oid, 'EXECUTE'
     )
     or exists (
       select 1
         from pg_catalog.aclexplode(
           coalesce(
             tenant_function.proacl,
             pg_catalog.acldefault('f', tenant_function.proowner)
           )
         ) acl
        where not (
          (
            acl.grantee = owner_oid
            and acl.privilege_type = 'EXECUTE'
          )
          or (
            acl.grantee = runtime_oid
            and acl.privilege_type = 'EXECUTE'
            and not acl.is_grantable
          )
        )
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2A catalog conflict: function agent_private.current_tenant_id has an unsafe definition or ACL';
  end if;
end
$function_guard$;

-- Postcondicoes independentes dos blocos de criacao. Nao ha credencial,
-- tabela, privilegio CREATE nem associacao que conceda privilegios ao runtime
-- no contrato desta migration.
do $postconditions$
declare
  runtime_oid oid := pg_catalog.to_regrole('agent_runtime')::oid;
  executor_role_oid oid := pg_catalog.to_regrole(current_user)::oid;
begin
  if runtime_oid is null
     or pg_catalog.to_regnamespace('agent_private') is null
     or pg_catalog.to_regprocedure(
       'agent_private.current_tenant_id()'
     ) is null
     or exists (
       select 1
         from pg_catalog.pg_auth_members membership
        where membership.member = runtime_oid
           or (
             membership.roleid = runtime_oid
             and not (
               membership.member = executor_role_oid
               and membership.admin_option
               and not membership.inherit_option
               and not membership.set_option
             )
           )
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2A postcondition failed: private runtime foundation incomplete';
  end if;
end
$postconditions$;

commit;
