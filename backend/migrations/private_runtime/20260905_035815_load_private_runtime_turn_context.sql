-- PASTORAI_MIGRATION_INTENT_V2={"affected_objects":["agent_private","agent_private.current_tenant_id()","agent_private.load_turn_context(uuid)","agent_projection_owner","agent_runtime","public.conversations","public.current_igreja_id()","public.pessoas"],"artifact_id":"migration-authoring-intent-v2","base_repository_sha":"64838cd3f1c6604ef091a940e19f704616d500b3","cross_tenant_test_nodeids":["backend/tests/test_private_runtime_projection_pg17.py::test_private_runtime_projection_pg17","backend/tests/test_private_runtime_projection_pg17.py::test_private_runtime_projection_security_adversaries"],"decision_refs":["docs/decisions/2026-09-05-private-runtime-projection-catalog.md"],"migration_basename":"20260905_035815_load_private_runtime_turn_context.sql","next_stage_authorized":false,"operational_authorization":false,"pg17_test_nodeids":["backend/tests/test_private_runtime_projection_pg17.py::test_private_runtime_projection_pg17","backend/tests/test_private_runtime_projection_pg17.py::test_private_runtime_projection_security_adversaries","backend/tests/test_private_runtime_projection_pg17.py::test_private_runtime_projection_rollback_atomicity"],"private_runtime_controls":{"acl":{"direct_projection_owner_grants":[{"grantable":false,"grantee":"agent_projection_owner","object":"agent_private","privilege":"USAGE"},{"grantable":false,"grantee":"agent_projection_owner","object":"agent_private.current_tenant_id()","privilege":"EXECUTE"},{"grantable":false,"grantee":"agent_projection_owner","object":"public.current_igreja_id()","privilege":"EXECUTE"},{"grantable":false,"grantee":"agent_projection_owner","object":"public.pessoas","privilege":"SELECT(igreja_id,id,optout,sem_interesse)"},{"grantable":false,"grantee":"agent_projection_owner","object":"public.conversations","privilege":"SELECT(igreja_id,id,pessoa_id,estado)"}],"direct_public_grants":[],"direct_runtime_grants":[{"grantable":false,"grantee":"agent_runtime","object":"agent_private","privilege":"USAGE"},{"grantable":false,"grantee":"agent_runtime","object":"agent_private.current_tenant_id()","privilege":"EXECUTE"},{"grantable":false,"grantee":"agent_runtime","object":"agent_private.load_turn_context(uuid)","privilege":"EXECUTE"}],"function_execute":["agent_runtime"],"relation_select":[],"schema_usage":["agent_runtime","agent_projection_owner"]},"config":{"default_acl_policy":"NO_RUNTIME_OR_PROJECTION_OWNER_DEFAULT_PRIVILEGES","gates":{"next_stage_authorized":false,"operational_authorization":false},"read_only_boundary":true,"role_config":["row_security=on","search_path=pg_catalog, agent_private"],"runtime_database_url_env":"AGENT_RUNTIME_DATABASE_URL","tenant_guc":"app.tenant_igreja_id"},"functions":[{"execute_grantees":["agent_runtime"],"identity":"agent_private.current_tenant_id()","lifecycle":"EXISTING_HELPER","name":"current_tenant_id","owner":"CURRENT_MIGRATION_ROLE","public_execute":false,"read_only":true,"return_columns":[],"returns":"uuid","schema":"agent_private","search_path":["pg_catalog"],"security_definer":false,"strict":false,"volatility":"STABLE","writes_allowed":false}],"projection_function":{"execute_grantees":["agent_runtime"],"identity":"agent_private.load_turn_context(uuid)","lifecycle":"FUTURE_PROJECTION_CONTRACT","name":"load_turn_context","owner":"agent_projection_owner","public_execute":false,"read_only":true,"return_columns":[{"name":"igreja_id","type":"uuid"},{"name":"conversation_id","type":"uuid"},{"name":"pessoa_id","type":"uuid"},{"name":"conversation_state","type":"text"},{"name":"pessoa_optout","type":"boolean"},{"name":"pessoa_sem_interesse","type":"boolean"}],"returns":"TABLE","schema":"agent_private","search_path":["pg_catalog","agent_private"],"security_definer":true,"strict":true,"volatility":"STABLE","writes_allowed":false},"projection_owner_role":{"bypassrls":false,"createdb":false,"createrole":false,"inherit":false,"login":false,"memberships":[],"name":"agent_projection_owner","replication":false,"superuser":false},"relations":[],"runtime_role":{"bypassrls":false,"createdb":false,"createrole":false,"inherit":false,"login":false,"memberships":[],"name":"agent_runtime","replication":false,"superuser":false},"schema":{"name":"agent_private","owner":"CURRENT_MIGRATION_ROLE","public_usage":false,"runtime_usage":true},"tenant_context":{"guc":"app.tenant_igreja_id","name":"current_tenant_id","null_behavior":"NULL_WHEN_UNSET","returns":"uuid","schema":"agent_private","source":"current_setting('app.tenant_igreja_id', true)"}},"recovery":{"kind":"REVERSIBLE","reference":"docs/decisions/2026-09-05-private-runtime-projection-catalog.md"},"scope":"PRIVATE_RUNTIME"}
-- PastorAI PRIVATE_RUNTIME: bounded read-only turn-context projection.
--
-- This file belongs to the separate V2 private-runtime stream.  It is not
-- part of the byte-pinned public TENANT catalog and must never be wrapped by
-- the V1 migration verifier.

-- OPERATIONAL_AUTHORIZATION=BLOCKED
-- NEXT_STAGE_AUTHORIZED=false

begin;

set transaction isolation level serializable;
set local search_path = pg_catalog;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(
    'pastorai:private-runtime:load-turn-context:v1',
    0
  )
);

-- The two runtime identities are closed before any grant is made.  Existing
-- role drift is a conflict, not a reason for this migration to repair or
-- conceal credentials/memberships.
do $role_guard$
declare
  runtime_role pg_catalog.pg_roles%rowtype;
  projection_role pg_catalog.pg_roles%rowtype;
  expected_config text[] := array[
    'row_security=on',
    'search_path=pg_catalog, agent_private'
  ];
  runtime_oid oid;
  projection_oid oid;
begin
  select * into runtime_role
    from pg_catalog.pg_roles
   where rolname = 'agent_runtime';
  if not found then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime conflict: agent_runtime is missing';
  end if;

  if runtime_role.rolcanlogin
     or runtime_role.rolinherit
     or runtime_role.rolsuper
     or runtime_role.rolbypassrls
     or runtime_role.rolcreatedb
     or runtime_role.rolcreaterole
     or runtime_role.rolreplication
     or runtime_role.rolconnlimit <> -1
     or runtime_role.rolvaliduntil is not null
     or exists (
       select 1
         from pg_catalog.pg_authid credential
        where credential.oid = runtime_role.oid
          and credential.rolpassword is not null
     )
     or coalesce(runtime_role.rolconfig, array[]::text[])
          <> expected_config
  then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime conflict: agent_runtime attributes';
  end if;

  runtime_oid := runtime_role.oid;
  if exists (
    select 1
      from pg_catalog.pg_auth_members membership
     where membership.member = runtime_oid
        or membership.roleid = runtime_oid
  ) then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime conflict: agent_runtime memberships';
  end if;

  select * into projection_role
    from pg_catalog.pg_roles
   where rolname = 'agent_projection_owner';
  if not found then
    create role agent_projection_owner
      nologin
      noinherit
      nosuperuser
      nobypassrls
      nocreatedb
      nocreaterole
      noreplication;
  else
    if projection_role.rolcanlogin
       or projection_role.rolinherit
       or projection_role.rolsuper
       or projection_role.rolbypassrls
       or projection_role.rolcreatedb
       or projection_role.rolcreaterole
       or projection_role.rolreplication
       or projection_role.rolconnlimit <> -1
       or projection_role.rolvaliduntil is not null
       or exists (
         select 1
           from pg_catalog.pg_authid credential
          where credential.oid = projection_role.oid
            and credential.rolpassword is not null
       )
       or coalesce(projection_role.rolconfig, array[]::text[])
            <> expected_config
    then
      raise exception using
        errcode = 'P0001',
        message = 'private runtime conflict: projection owner attributes';
    end if;
  end if;

  projection_oid := pg_catalog.to_regrole('agent_projection_owner')::oid;
  if projection_oid is null
     or exists (
       select 1
         from pg_catalog.pg_auth_members membership
        where membership.member = projection_oid
           or membership.roleid = projection_oid
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime conflict: projection owner memberships';
  end if;

  alter role agent_projection_owner set row_security = on;
  alter role agent_projection_owner
    set search_path = pg_catalog, agent_private;

  select * into strict projection_role
    from pg_catalog.pg_roles
   where rolname = 'agent_projection_owner';
  if projection_role.rolcanlogin
     or projection_role.rolinherit
     or projection_role.rolsuper
     or projection_role.rolbypassrls
     or projection_role.rolcreatedb
     or projection_role.rolcreaterole
     or projection_role.rolreplication
     or projection_role.rolconnlimit <> -1
     or projection_role.rolvaliduntil is not null
     or exists (
       select 1
         from pg_catalog.pg_authid credential
        where credential.oid = projection_role.oid
          and credential.rolpassword is not null
     )
     or coalesce(projection_role.rolconfig, array[]::text[])
          <> expected_config
  then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime conflict: projection owner configuration';
  end if;
end
$role_guard$;

-- Keep the D2A schema owner and its existing web/runtime boundary.  The only
-- new schema ACL is non-grantable USAGE for the dedicated function owner.
do $schema_guard$
declare
  private_schema pg_catalog.pg_namespace%rowtype;
  owner_oid oid := pg_catalog.to_regrole(current_user)::oid;
  runtime_oid oid := pg_catalog.to_regrole('agent_runtime')::oid;
  projection_oid oid := pg_catalog.to_regrole('agent_projection_owner')::oid;
begin
  select * into private_schema
    from pg_catalog.pg_namespace
   where nspname = 'agent_private';
  if not found
     or private_schema.nspowner <> owner_oid
     or runtime_oid is null
     or projection_oid is null
  then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime conflict: schema owner';
  end if;

  if exists (
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
       or (
         acl.grantee = projection_oid
         and acl.privilege_type = 'USAGE'
         and not acl.is_grantable
       )
     )
  ) then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime conflict: schema ACL';
  end if;

  grant usage on schema agent_private to agent_projection_owner;
  select * into strict private_schema
    from pg_catalog.pg_namespace
   where nspname = 'agent_private';

  if exists (
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
       or (
         acl.grantee = projection_oid
         and acl.privilege_type = 'USAGE'
         and not acl.is_grantable
       )
     )
  ) then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime conflict: schema ACL after grant';
  end if;
end
$schema_guard$;

-- The helper is an immutable V1/D2A dependency.  This block verifies its
-- definition before adding the one explicit EXECUTE grant needed by the
-- DEFINER owner; no CREATE OR REPLACE is used.
do $helper_guard$
declare
  helper pg_catalog.pg_proc%rowtype;
  helper_oid oid;
  owner_oid oid := pg_catalog.to_regrole(current_user)::oid;
  runtime_oid oid := pg_catalog.to_regrole('agent_runtime')::oid;
  projection_oid oid := pg_catalog.to_regrole('agent_projection_owner')::oid;
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
  helper_oid := pg_catalog.to_regprocedure(
    'agent_private.current_tenant_id()'
  );
  if helper_oid is null then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime conflict: tenant helper missing';
  end if;

  select * into strict helper
    from pg_catalog.pg_proc
   where oid = helper_oid;
  if helper.proowner <> owner_oid
     or helper.prolang <> sql_language_oid
     or helper.prorettype <> 'pg_catalog.uuid'::pg_catalog.regtype
     or helper.pronargs <> 0
     or helper.provolatile <> 's'
     or helper.prosecdef
     or helper.proleakproof
     or helper.proretset
     or helper.proconfig is distinct from array['search_path=pg_catalog']
     or pg_catalog.regexp_replace(
       helper.prosrc, '[[:space:]]+', '', 'g'
     ) <> pg_catalog.regexp_replace(
       expected_source, '[[:space:]]+', '', 'g'
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime conflict: tenant helper definition';
  end if;

  grant execute on function agent_private.current_tenant_id()
    to agent_projection_owner;
  -- The historical PUBLIC tenant_isolation policy is evaluated for every
  -- role.  Its SECURITY DEFINER helper remains untouched, but the projection
  -- owner needs the same narrow EXECUTE privilege for PostgreSQL to evaluate
  -- that preserved policy without a permission error.
  if pg_catalog.to_regprocedure('public.current_igreja_id()') is null then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime conflict: web tenant helper missing';
  end if;
  grant execute on function public.current_igreja_id()
    to agent_projection_owner;

  if exists (
    select 1
      from pg_catalog.aclexplode(
        coalesce(helper.proacl, pg_catalog.acldefault('f', helper.proowner))
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
       or (
         acl.grantee = projection_oid
         and acl.privilege_type = 'EXECUTE'
         and not acl.is_grantable
       )
     )
  ) then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime conflict: tenant helper ACL';
  end if;
end
$helper_guard$;

-- Public tables remain owned and governed by the web path.  Only the exact
-- source columns are granted to the non-login projection owner; the runtime
-- role receives no table or column privilege.
do $relation_guard$
declare
  owner_oid oid := pg_catalog.to_regrole(current_user)::oid;
  runtime_oid oid := pg_catalog.to_regrole('agent_runtime')::oid;
  projection_oid oid := pg_catalog.to_regrole('agent_projection_owner')::oid;
  relation_oid oid;
  relation_name text;
  required_column text;
  required_columns text[];
  policy_count bigint;
  policy_names text[];
  policy_rec record;
  policy_expr text;
  acl_rec record;
  expected_web_policy_expr text :=
    '(igreja_id=public.current_igreja_id())';
  expected_owner_policy_expr text :=
    '(igreja_id=agent_private.current_tenant_id())';
begin
  foreach relation_name in array array[
    'public.pessoas',
    'public.conversations'
  ] loop
    required_columns := case relation_name
      when 'public.pessoas' then pg_catalog.string_to_array(
        'igreja_id,id,optout,sem_interesse', ','
      )
      when 'public.conversations' then pg_catalog.string_to_array(
        'igreja_id,id,pessoa_id,estado', ','
      )
    end;
    relation_oid := pg_catalog.to_regclass(relation_name)::oid;
    if relation_oid is null
       or not exists (
         select 1 from pg_catalog.pg_class
          where oid = relation_oid
            and relkind in ('r', 'p')
            and relrowsecurity
            and not relforcerowsecurity
       )
    then
      raise exception using
        errcode = 'P0001',
        message = 'private runtime conflict: public relation security';
    end if;

    -- An effective PUBLIC grant would also reach the runtime role; reject it
    -- rather than attempting to rewrite web ACLs.
    if pg_catalog.has_table_privilege(
         'agent_runtime', relation_oid, 'SELECT'
       )
       or exists (
         select 1
           from pg_catalog.aclexplode(
             coalesce(
               (select relacl from pg_catalog.pg_class where oid = relation_oid),
               pg_catalog.acldefault(
                 'r',
                 (select relowner from pg_catalog.pg_class where oid = relation_oid)
               )
             )
           ) acl
          where acl.grantee in (runtime_oid, 0)
       )
    then
      raise exception using
        errcode = 'P0001',
        message = 'private runtime conflict: public relation ACL';
    end if;

    -- Table-wide owner grants would widen the projection beyond the exact
    -- source-column contract; reject them before any replay grant is made.
    if exists (
      select 1
        from pg_catalog.aclexplode(
          coalesce(
            (select relacl from pg_catalog.pg_class where oid = relation_oid),
            pg_catalog.acldefault(
              'r',
              (select relowner from pg_catalog.pg_class where oid = relation_oid)
            )
          )
        ) acl
       where acl.grantee = projection_oid
    ) then
      raise exception using
        errcode = 'P0001',
        message = 'private runtime conflict: projection table ACL';
    end if;

    -- A pre-existing runtime/PUBLIC privilege is drift.  An existing owner
    -- column grant is allowed only when it is exactly one of the four source
    -- columns; this is what makes the fixture safely idempotent.
    if exists (
      select 1
        from pg_catalog.pg_attribute attribute
       where attribute.attrelid = relation_oid
         and attribute.attnum > 0
         and not attribute.attisdropped
         and attribute.attacl is not null
         and exists (
           select 1
             from pg_catalog.aclexplode(attribute.attacl) acl
            where acl.grantee in (runtime_oid, 0)
         )
    ) then
      raise exception using
        errcode = 'P0001',
        message = 'private runtime conflict: public column ACL';
    end if;

    for acl_rec in
      select attribute.attname, acl.*
        from pg_catalog.pg_attribute attribute
        cross join lateral pg_catalog.aclexplode(attribute.attacl) acl
       where attribute.attrelid = relation_oid
         and attribute.attnum > 0
         and not attribute.attisdropped
    loop
      if acl_rec.grantee = projection_oid
         and (
           acl_rec.privilege_type <> 'SELECT'
           or acl_rec.is_grantable
           or acl_rec.attname <> all(required_columns)
         )
      then
        raise exception using
          errcode = 'P0001',
          message = 'private runtime conflict: projection column ACL';
      elsif acl_rec.grantee = runtime_oid or acl_rec.grantee = 0 then
        raise exception using
          errcode = 'P0001',
          message = 'private runtime conflict: runtime column ACL';
      end if;
    end loop;

    foreach required_column in array required_columns loop
      if not exists (
        select 1
          from pg_catalog.pg_attribute attribute
         where attribute.attrelid = relation_oid
           and attribute.attname = required_column
           and attribute.attnum > 0
           and not attribute.attisdropped
      ) then
        raise exception using
          errcode = 'P0001',
          message = 'private runtime conflict: projection column missing';
      end if;
    end loop;

    select count(*), pg_catalog.array_agg(polname order by polname)
      into policy_count, policy_names
      from pg_catalog.pg_policy
     where polrelid = relation_oid;
    if policy_names not in (
      array['tenant_isolation']::text[],
      array[
        case relation_name
          when 'public.pessoas' then 'agent_projection_owner_select_pessoas'
          else 'agent_projection_owner_select_conversations'
        end,
        case relation_name
          when 'public.pessoas' then 'agent_projection_owner_tenant_barrier_pessoas'
          else 'agent_projection_owner_tenant_barrier_conversations'
        end,
        'tenant_isolation'
      ]::text[]
    ) then
      raise exception using
        errcode = 'P0001',
        message = 'private runtime conflict: policy set';
    end if;

    select p.* into strict policy_rec
      from pg_catalog.pg_policy p
     where p.polrelid = relation_oid
       and p.polname = 'tenant_isolation';
    policy_expr := pg_catalog.regexp_replace(
      pg_catalog.lower(
        coalesce(pg_catalog.pg_get_expr(policy_rec.polqual, relation_oid), '')
      ),
      '[[:space:]]+', '', 'g'
    );
    if not policy_rec.polpermissive
       or policy_rec.polcmd <> '*'
       or policy_rec.polroles is distinct from array[0::oid]
       or policy_rec.polqual is null
       or policy_rec.polwithcheck is null
       or policy_expr <> expected_web_policy_expr
    then
      raise exception using
        errcode = 'P0001',
        message = 'private runtime conflict: web policy';
    end if;

    if policy_count = 3 then
      for policy_rec in
        select p.*
          from pg_catalog.pg_policy p
         where p.polrelid = relation_oid
           and p.polname <> 'tenant_isolation'
         order by p.polname
      loop
        policy_expr := pg_catalog.regexp_replace(
          pg_catalog.lower(
            coalesce(pg_catalog.pg_get_expr(policy_rec.polqual, relation_oid), '')
          ),
          '[[:space:]]+', '', 'g'
        );
        if policy_rec.polcmd <> 'r'
           or policy_rec.polroles is distinct from array[projection_oid]
           or policy_rec.polqual is null
           or policy_rec.polwithcheck is not null
           or policy_expr <> expected_owner_policy_expr
           or (
             policy_rec.polname like '%select%'
             and not policy_rec.polpermissive
           )
           or (
             policy_rec.polname like '%barrier%'
             and policy_rec.polpermissive
           )
        then
          raise exception using
            errcode = 'P0001',
            message = 'private runtime conflict: owner policy';
        end if;
      end loop;
    end if;
  end loop;
end
$relation_guard$;

grant select (igreja_id, id, optout, sem_interesse)
  on table public.pessoas to agent_projection_owner;
grant select (igreja_id, id, pessoa_id, estado)
  on table public.conversations to agent_projection_owner;

-- Role-specific permissive policies provide the owner path; restrictive
-- policies force the same tenant predicate even while the historical PUBLIC
-- policy remains in place for the web roles.  No ALTER TABLE ... FORCE is
-- issued, so the global web semantics are unchanged.
do $policy_create$
begin
  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = 'public.pessoas'::pg_catalog.regclass
       and polname = 'agent_projection_owner_select_pessoas'
  ) then
    create policy agent_projection_owner_select_pessoas
      on public.pessoas
      as permissive
      for select
      to agent_projection_owner
      using (igreja_id = agent_private.current_tenant_id());
  end if;

  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = 'public.pessoas'::pg_catalog.regclass
       and polname = 'agent_projection_owner_tenant_barrier_pessoas'
  ) then
    create policy agent_projection_owner_tenant_barrier_pessoas
      on public.pessoas
      as restrictive
      for select
      to agent_projection_owner
      using (igreja_id = agent_private.current_tenant_id());
  end if;

  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = 'public.conversations'::pg_catalog.regclass
       and polname = 'agent_projection_owner_select_conversations'
  ) then
    create policy agent_projection_owner_select_conversations
      on public.conversations
      as permissive
      for select
      to agent_projection_owner
      using (igreja_id = agent_private.current_tenant_id());
  end if;

  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = 'public.conversations'::pg_catalog.regclass
       and polname = 'agent_projection_owner_tenant_barrier_conversations'
  ) then
    create policy agent_projection_owner_tenant_barrier_conversations
      on public.conversations
      as restrictive
      for select
      to agent_projection_owner
      using (igreja_id = agent_private.current_tenant_id());
  end if;
end
$policy_create$;

-- The function returns exactly the six server-owned fields.  All identifiers
-- are schema-qualified; the fixed path and row_security setting defend this
-- SECURITY DEFINER body against search_path and owner-policy surprises.
-- An existing function is authenticated, never replaced, so a body/ACL drift
-- aborts the transaction instead of being silently repaired.
do $function_guard$
declare
  owner_oid oid := pg_catalog.to_regrole('agent_projection_owner')::oid;
  runtime_oid oid := pg_catalog.to_regrole('agent_runtime')::oid;
  function_oid oid := pg_catalog.to_regprocedure(
    'agent_private.load_turn_context(uuid)'
  );
  function_rec pg_catalog.pg_proc%rowtype;
  acl_rec record;
  expected_source text := $expected_source$
    declare
      requested_tenant pg_catalog.uuid;
    begin
      begin
        requested_tenant := agent_private.current_tenant_id();
      exception
        when others then
          raise exception using
            errcode = '22023',
            message = 'invalid tenant context';
      end;

      if requested_tenant is null then
        return;
      end if;

      return query
        select
          conversation.igreja_id,
          conversation.id,
          conversation.pessoa_id,
          conversation.estado::text,
          person.optout,
          person.sem_interesse
          from public.conversations as conversation
          join public.pessoas as person
            on person.id = conversation.pessoa_id
           and person.igreja_id = conversation.igreja_id
         where conversation.id = p_conversation_id
           and conversation.igreja_id = requested_tenant;
    end
  $expected_source$;
begin
  if function_oid is null then
    return;
  end if;

  select * into strict function_rec
    from pg_catalog.pg_proc where oid = function_oid;
  if function_rec.proowner <> owner_oid
     or function_rec.prolang <> (
       select oid from pg_catalog.pg_language where lanname = 'plpgsql'
     )
     or function_rec.prorettype <> 'record'::pg_catalog.regtype
     or function_rec.pronargs <> 1
     or function_rec.proargtypes <> array['uuid'::regtype]::oidvector
     or function_rec.proallargtypes is distinct from array[
       'uuid'::regtype,
       'uuid'::regtype,
       'uuid'::regtype,
       'uuid'::regtype,
       'text'::regtype,
       'boolean'::regtype,
       'boolean'::regtype
     ]::oid[]
     or pg_catalog.array_to_string(function_rec.proargmodes, '')
          <> 'itttttt'
     or function_rec.proargnames is distinct from array[
       'p_conversation_id',
       'igreja_id',
       'conversation_id',
       'pessoa_id',
       'conversation_state',
       'pessoa_optout',
       'pessoa_sem_interesse'
     ]::text[]
     or function_rec.provolatile <> 's'
     or not function_rec.proisstrict
     or not function_rec.prosecdef
     or function_rec.proleakproof
     or function_rec.proconfig is distinct from array[
       'search_path=pg_catalog, agent_private',
       'row_security=on'
     ]
     or pg_catalog.regexp_replace(
          function_rec.prosrc, '[[:space:]]+', '', 'g'
        ) <> pg_catalog.regexp_replace(
          expected_source, '[[:space:]]+', '', 'g'
        )
  then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime conflict: projection definition';
  end if;

  for acl_rec in
    select *
      from pg_catalog.aclexplode(
        coalesce(
          function_rec.proacl,
          pg_catalog.acldefault('f', function_rec.proowner)
        )
      )
  loop
    if acl_rec.privilege_type <> 'EXECUTE'
       or acl_rec.is_grantable
       or acl_rec.grantee not in (owner_oid, runtime_oid)
    then
      raise exception using
        errcode = 'P0001',
        message = 'private runtime conflict: projection ACL';
    end if;
  end loop;
end
$function_guard$;

do $function_create$
declare
  function_oid oid := pg_catalog.to_regprocedure(
    'agent_private.load_turn_context(uuid)'
  );
  role_name text;
begin
  if function_oid is null then
    execute $function$
      create function agent_private.load_turn_context(
        p_conversation_id uuid
      )
      returns table (
        igreja_id uuid,
        conversation_id uuid,
        pessoa_id uuid,
        conversation_state text,
        pessoa_optout boolean,
        pessoa_sem_interesse boolean
      )
      language plpgsql
      stable
      strict
      security definer
      set search_path = pg_catalog, agent_private
      set row_security = on
      as $body$
      declare
        requested_tenant pg_catalog.uuid;
      begin
        begin
          requested_tenant := agent_private.current_tenant_id();
        exception
          when others then
            raise exception using
              errcode = '22023',
              message = 'invalid tenant context';
        end;

        if requested_tenant is null then
          return;
        end if;

        return query
          select
            conversation.igreja_id,
            conversation.id,
            conversation.pessoa_id,
            conversation.estado::text,
            person.optout,
            person.sem_interesse
            from public.conversations as conversation
            join public.pessoas as person
              on person.id = conversation.pessoa_id
             and person.igreja_id = conversation.igreja_id
           where conversation.id = p_conversation_id
             and conversation.igreja_id = requested_tenant;
      end
      $body$
    $function$;

    execute 'alter function agent_private.load_turn_context(uuid) '
      || 'owner to agent_projection_owner';

    execute 'revoke all privileges on function '
      || 'agent_private.load_turn_context(uuid) from public';
    for role_name in
      select rolname
        from pg_catalog.pg_roles
       where rolname in ('anon', 'authenticated', 'service_role')
    loop
      execute pg_catalog.format(
        'revoke all privileges on function '
        || 'agent_private.load_turn_context(uuid) from %I',
        role_name
      );
    end loop;
  end if;

  grant execute on function agent_private.load_turn_context(uuid)
    to agent_runtime;
end
$function_create$;

-- Keep future objects in the private namespace closed to both restricted
-- roles and PUBLIC.  This is schema-scoped default ACL hardening only.
alter default privileges in schema agent_private
  revoke all on tables from public, agent_runtime, agent_projection_owner;
alter default privileges in schema agent_private
  revoke all on sequences from public, agent_runtime, agent_projection_owner;
alter default privileges in schema agent_private
  revoke all on functions from public, agent_runtime, agent_projection_owner;

-- Postconditions reject a partial or adulterated replay before commit.
do $postconditions$
declare
  owner_oid oid := pg_catalog.to_regrole('agent_projection_owner')::oid;
  runtime_oid oid := pg_catalog.to_regrole('agent_runtime')::oid;
  helper_oid oid := pg_catalog.to_regprocedure(
    'agent_private.current_tenant_id()'
  );
  projection_oid oid := pg_catalog.to_regprocedure(
    'agent_private.load_turn_context(uuid)'
  );
  function_record pg_catalog.pg_proc%rowtype;
  relation_oid oid;
  relation_name text;
  required_column text;
  required_columns text[];
  required_column_count integer;
  role_record pg_catalog.pg_roles%rowtype;
  policy_record pg_catalog.pg_policy%rowtype;
  policy_item record;
  expected_policy record;
  policy_expr text;
  table_policy_count integer;
  expected_web_policy_expr text :=
    '(igreja_id=public.current_igreja_id())';
  expected_owner_policy_expr text :=
    '(igreja_id=agent_private.current_tenant_id())';
  expected_config text[] := array[
    'row_security=on',
    'search_path=pg_catalog, agent_private'
  ];
  web_helper_oid oid := pg_catalog.to_regprocedure(
    'public.current_igreja_id()'
  );
  web_helper_owner_oid oid;
  authenticated_oid oid := pg_catalog.to_regrole('authenticated')::oid;
  service_role_oid oid := pg_catalog.to_regrole('service_role')::oid;
  expected_result text := 'TABLE(igreja_id uuid, conversation_id uuid, pessoa_id uuid, conversation_state text, pessoa_optout boolean, pessoa_sem_interesse boolean)';
begin
  if owner_oid is null
     or runtime_oid is null
     or helper_oid is null
     or projection_oid is null
     or web_helper_oid is null
     or authenticated_oid is null
     or service_role_oid is null
  then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime postcondition: identity missing';
  end if;

  select proowner into strict web_helper_owner_oid
    from pg_catalog.pg_proc
   where oid = web_helper_oid;

  select * into strict role_record
    from pg_catalog.pg_roles
   where oid = owner_oid;
  if role_record.rolcanlogin
     or role_record.rolinherit
     or role_record.rolsuper
     or role_record.rolbypassrls
     or role_record.rolcreatedb
     or role_record.rolcreaterole
     or role_record.rolreplication
     or role_record.rolconnlimit <> -1
     or role_record.rolvaliduntil is not null
     or exists (
       select 1
         from pg_catalog.pg_authid credential
        where credential.oid = role_record.oid
          and credential.rolpassword is not null
     )
     or coalesce(role_record.rolconfig, array[]::text[]) <> expected_config
     or exists (
       select 1 from pg_catalog.pg_auth_members
        where member = owner_oid or roleid = owner_oid
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime postcondition: owner role drift';
  end if;

  select * into strict function_record
    from pg_catalog.pg_proc
   where oid = projection_oid;
  if function_record.proowner <> owner_oid
     or function_record.prolang <> (
       select oid from pg_catalog.pg_language where lanname = 'plpgsql'
     )
     or function_record.prorettype <> 'record'::pg_catalog.regtype
     or function_record.pronargs <> 1
     or function_record.proargtypes[0] <> 'pg_catalog.uuid'::pg_catalog.regtype
     or function_record.proretset is not true
     or function_record.prosecdef is not true
     or function_record.provolatile <> 's'
     or function_record.proisstrict is not true
     or function_record.proconfig is distinct from array[
       'search_path=pg_catalog, agent_private',
       'row_security=on'
     ]
     or pg_catalog.pg_get_function_result(projection_oid)
          <> expected_result
  then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime postcondition: projection definition';
  end if;

  if exists (
    select 1
      from pg_catalog.aclexplode(
        coalesce(
          function_record.proacl,
          pg_catalog.acldefault('f', function_record.proowner)
        )
      ) acl
     where not (
       acl.grantee = owner_oid
       and acl.privilege_type = 'EXECUTE'
       or (
         acl.grantee = runtime_oid
         and acl.privilege_type = 'EXECUTE'
         and not acl.is_grantable
       )
     )
  )
  or not pg_catalog.has_function_privilege(
    'agent_runtime', projection_oid, 'EXECUTE'
  )
  or pg_catalog.has_function_privilege(
    'public', projection_oid, 'EXECUTE'
  )
  then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime postcondition: projection ACL';
  end if;

  -- The historical web helper is preserved.  Its existing web grants remain
  -- valid, and the only new grant is non-grantable EXECUTE for the projection
  -- owner so the preserved PUBLIC tenant policy can be evaluated.  PUBLIC,
  -- anon and agent_runtime must never gain this capability.
  if exists (
    select 1
      from pg_catalog.aclexplode(
        coalesce(
          (select proacl from pg_catalog.pg_proc where oid = web_helper_oid),
          pg_catalog.acldefault('f', web_helper_owner_oid)
        )
      ) acl
     where acl.privilege_type <> 'EXECUTE'
        or acl.is_grantable
        or acl.grantee not in (
          web_helper_owner_oid,
          authenticated_oid,
          service_role_oid,
          owner_oid
        )
  )
  or not pg_catalog.has_function_privilege(
    'authenticated', web_helper_oid, 'EXECUTE'
  )
  or not pg_catalog.has_function_privilege(
    'service_role', web_helper_oid, 'EXECUTE'
  )
  or not pg_catalog.has_function_privilege(
    'agent_projection_owner', web_helper_oid, 'EXECUTE'
  )
  or pg_catalog.has_function_privilege(
    'public', web_helper_oid, 'EXECUTE'
  )
  or pg_catalog.has_function_privilege(
    'anon', web_helper_oid, 'EXECUTE'
  )
  or pg_catalog.has_function_privilege(
    'agent_runtime', web_helper_oid, 'EXECUTE'
  )
  then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime postcondition: web tenant helper ACL';
  end if;

  foreach relation_name in array array[
    'public.pessoas',
    'public.conversations'
  ] loop
    required_columns := case relation_name
      when 'public.pessoas' then pg_catalog.string_to_array(
        'igreja_id,id,optout,sem_interesse', ','
      )
      when 'public.conversations' then pg_catalog.string_to_array(
        'igreja_id,id,pessoa_id,estado', ','
      )
    end;
    relation_oid := pg_catalog.to_regclass(relation_name)::oid;
    if not exists (
      select 1
        from pg_catalog.pg_class
       where oid = relation_oid
         and relrowsecurity
         and not relforcerowsecurity
    ) then
      raise exception using
        errcode = 'P0001',
        message = 'private runtime postcondition: RLS boundary';
    end if;

    required_column_count := 0;
    foreach required_column in array required_columns loop
      required_column_count := required_column_count + 1;
      if not exists (
        select 1
          from pg_catalog.pg_attribute attribute
         where attribute.attrelid = relation_oid
           and attribute.attname = required_column
           and attribute.attnum > 0
           and not attribute.attisdropped
           and attribute.attacl is not null
           and (
             select count(*)
               from pg_catalog.aclexplode(attribute.attacl) acl
              where acl.grantee = owner_oid
                and acl.privilege_type = 'SELECT'
                and not acl.is_grantable
           ) = 1
      ) then
        raise exception using
          errcode = 'P0001',
          message = 'private runtime postcondition: projection column ACL';
      end if;
    end loop;

    if exists (
      select 1
        from pg_catalog.pg_attribute attribute
       where attribute.attrelid = relation_oid
         and attribute.attnum > 0
         and not attribute.attisdropped
         and attribute.attacl is not null
         and exists (
           select 1
             from pg_catalog.aclexplode(attribute.attacl) acl
            where acl.grantee in (runtime_oid, 0)
               or (
                 acl.grantee = owner_oid
                 and acl.privilege_type <> 'SELECT'
               )
         )
    ) then
      raise exception using
        errcode = 'P0001',
        message = 'private runtime postcondition: public column widening';
    end if;

    if exists (
      select 1
        from pg_catalog.aclexplode(
          coalesce(
            (select relacl from pg_catalog.pg_class where oid = relation_oid),
            pg_catalog.acldefault(
              'r',
              (select relowner from pg_catalog.pg_class where oid = relation_oid)
            )
          )
        ) acl
       where acl.grantee = owner_oid
    ) then
      raise exception using
        errcode = 'P0001',
        message = 'private runtime postcondition: projection table ACL';
    end if;
  end loop;

  -- Exactly the historical PUBLIC policy plus the two owner-only SELECT
  -- policies must exist on each source table.  Checking only EXISTS here would
  -- allow one of the four owner barriers to disappear or become FOR ALL.
  for policy_item in
    select * from (values
      ('public.pessoas'::text, 'tenant_isolation'::text, true, '*'::text, 0::oid),
      ('public.pessoas'::text, 'agent_projection_owner_select_pessoas'::text, true, 'r'::text, owner_oid),
      ('public.pessoas'::text, 'agent_projection_owner_tenant_barrier_pessoas'::text, false, 'r'::text, owner_oid),
      ('public.conversations'::text, 'tenant_isolation'::text, true, '*'::text, 0::oid),
      ('public.conversations'::text, 'agent_projection_owner_select_conversations'::text, true, 'r'::text, owner_oid),
      ('public.conversations'::text, 'agent_projection_owner_tenant_barrier_conversations'::text, false, 'r'::text, owner_oid)
    ) v(relation_name, policy_name, permissive, command, grantee)
  loop
    select count(*) into table_policy_count
      from pg_catalog.pg_policy p
      where p.polrelid = pg_catalog.to_regclass(policy_item.relation_name);
    if table_policy_count <> 3 then
      raise exception using
        errcode = 'P0001',
        message = 'private runtime postcondition: policy cardinality';
    end if;

    select p.* into strict policy_record
      from pg_catalog.pg_policy p
     where p.polrelid = pg_catalog.to_regclass(policy_item.relation_name)
       and p.polname = policy_item.policy_name;
    policy_expr := pg_catalog.regexp_replace(
      pg_catalog.lower(
        coalesce(
          pg_catalog.pg_get_expr(
            policy_record.polqual,
            pg_catalog.to_regclass(policy_item.relation_name)
          ),
          ''
        )
      ),
      '[[:space:]]+', '', 'g'
    );
    if policy_record.polpermissive is distinct from policy_item.permissive
       or policy_record.polcmd <> policy_item.command
       or policy_record.polroles is distinct from array[policy_item.grantee]
       or policy_record.polqual is null
       or (
         policy_item.policy_name = 'tenant_isolation'
         and policy_record.polwithcheck is null
       )
       or (
         policy_item.policy_name <> 'tenant_isolation'
         and policy_record.polwithcheck is not null
       )
       or policy_expr <> (
         case
           when policy_item.policy_name = 'tenant_isolation'
             then expected_web_policy_expr
           else expected_owner_policy_expr
         end
       )
    then
      raise exception using
        errcode = 'P0001',
        message = 'private runtime postcondition: policy definition';
    end if;
  end loop;

  if exists (
    select 1
      from pg_catalog.pg_default_acl defaults
      join pg_catalog.pg_namespace schema
        on schema.oid = defaults.defaclnamespace
      cross join lateral pg_catalog.aclexplode(defaults.defaclacl) acl
     where defaults.defaclrole = owner_oid
       and schema.nspname = 'agent_private'
       and acl.grantee in (0, runtime_oid, owner_oid)
  ) then
    raise exception using
      errcode = 'P0001',
      message = 'private runtime postcondition: default ACL';
  end if;
end
$postconditions$;

commit;
