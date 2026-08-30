-- transaction-open-begin
begin transaction isolation level repeatable read read only;

select pg_catalog.set_config('search_path', 'pg_catalog, public, agent_private', true);
select pg_catalog.set_config('statement_timeout', '30000', true);
select pg_catalog.set_config('lock_timeout', '1000', true);
select pg_catalog.set_config('idle_in_transaction_session_timeout', '30000', true);
select pg_catalog.set_config('row_security', 'off', true);
-- transaction-open-end

-- session-proof-begin
select pg_catalog.json_build_object(
  'system_identifier',control.system_identifier::pg_catalog.text,
  'database_name',pg_catalog.current_database(),
  'backend_pid',pg_catalog.pg_backend_pid(),
  'snapshot',pg_catalog.pg_current_snapshot()::pg_catalog.text,
  'server_version_num',pg_catalog.current_setting('server_version_num')::pg_catalog.int8,
  'current_user_matches_session_user',current_user=session_user,
  'tls',coalesce((select ssl from pg_catalog.pg_stat_ssl
    where pid=pg_catalog.pg_backend_pid()),false),
  'isolation_level',pg_catalog.current_setting('transaction_isolation'),
  'read_only',pg_catalog.current_setting('transaction_read_only'),
  'full_visibility',coalesce((select r.rolsuper or r.rolbypassrls
    from pg_catalog.pg_roles r where r.rolname=current_user),false)
) from pg_catalog.pg_control_system() control;
-- session-proof-end

-- metadata-capture-begin
with database_context as (
    select d.datdba as database_owner_oid,
           coalesce(
             (select r.oid from pg_catalog.pg_roles r
               where r.rolname = 'pg_database_owner'), 0::pg_catalog.oid
           ) as database_owner_alias_oid
      from pg_catalog.pg_database d
     where d.datname = pg_catalog.current_database()
),
extension_entries as (
    select pg_catalog.jsonb_build_object('name', e.extname, 'state', 'PRESENT') entry
      from pg_catalog.pg_extension e
     where e.extname in ('pgcrypto', 'plpgsql')
),
enum_entries as (
    select pg_catalog.jsonb_build_object(
      'schema', n.nspname, 'type', t.typname, 'label', e.enumlabel,
      'sort_order', e.enumsortorder::pg_catalog.text) entry
      from pg_catalog.pg_type t
      join pg_catalog.pg_namespace n on n.oid = t.typnamespace
      join pg_catalog.pg_enum e on e.enumtypid = t.oid
     where n.nspname in ('public', 'agent_private')
),
role_entries as (
    select pg_catalog.jsonb_build_object(
      'record_type', 'ROLE',
      'role', case when r.oid = dc.database_owner_oid then 'DERIVATION_OWNER' else r.rolname end,
      'superuser', r.rolsuper, 'inherit', r.rolinherit,
      'create_role', r.rolcreaterole, 'create_database', r.rolcreatedb,
      'login', r.rolcanlogin, 'replication', r.rolreplication,
      'bypass_rls', r.rolbypassrls,
      'configuration', coalesce(r.rolconfig, array[]::pg_catalog.text[]),
      'parent_role', null, 'member_role', null, 'admin_option', null,
      'inherit_option', null, 'set_option', null) entry
      from pg_catalog.pg_roles r cross join database_context dc
     where r.oid = dc.database_owner_oid
        or r.rolname in ('anon', 'authenticated', 'service_role', 'agent_runtime')
    union all
    select pg_catalog.jsonb_build_object(
      'record_type', 'MEMBERSHIP', 'role', null, 'superuser', null,
      'inherit', null, 'create_role', null, 'create_database', null,
      'login', null, 'replication', null, 'bypass_rls', null,
      'configuration', array[]::pg_catalog.text[], 'parent_role',
      case when parent.oid = dc.database_owner_oid then 'DERIVATION_OWNER' else parent.rolname end,
      'member_role',
      case when member.oid = dc.database_owner_oid then 'DERIVATION_OWNER' else member.rolname end,
      'admin_option', m.admin_option, 'inherit_option', m.inherit_option,
      'set_option', m.set_option) entry
      from pg_catalog.pg_auth_members m
      join pg_catalog.pg_roles parent on parent.oid = m.roleid
      join pg_catalog.pg_roles member on member.oid = m.member
      cross join database_context dc
     where (parent.oid = dc.database_owner_oid or parent.rolname in ('anon','authenticated','service_role','agent_runtime'))
       and (member.oid = dc.database_owner_oid or member.rolname in ('anon','authenticated','service_role','agent_runtime'))
),
schema_entries as (
    select pg_catalog.jsonb_build_object(
      'schema', n.nspname,
      'owner', case
        when n.nspowner in (dc.database_owner_oid, dc.database_owner_alias_oid)
          then 'DERIVATION_OWNER'
        when owner_role.rolname in ('anon','authenticated','service_role','agent_runtime')
          then owner_role.rolname
        else 'UNKNOWN_OWNER' end) entry
      from pg_catalog.pg_namespace n
      join pg_catalog.pg_roles owner_role on owner_role.oid = n.nspowner
      cross join database_context dc
     where n.nspname in ('public', 'agent_private')
),
relation_entries as (
    select pg_catalog.jsonb_build_object(
      'schema', n.nspname, 'relation', c.relname, 'kind', c.relkind::pg_catalog.text,
      'persistence', c.relpersistence::pg_catalog.text,
      'owner', case
        when c.relowner in (dc.database_owner_oid, dc.database_owner_alias_oid)
          then 'DERIVATION_OWNER'
        when owner_role.rolname in ('anon','authenticated','service_role','agent_runtime')
          then owner_role.rolname
        else 'UNKNOWN_OWNER' end) entry
      from pg_catalog.pg_class c
      join pg_catalog.pg_namespace n on n.oid = c.relnamespace
      join pg_catalog.pg_roles owner_role on owner_role.oid = c.relowner
      cross join database_context dc
     where n.nspname in ('public', 'agent_private')
       and c.relkind in ('r','p','v','m','S','f')
       and not exists (
         select 1 from pg_catalog.pg_depend d
          where d.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
            and d.objid = c.oid and d.deptype = 'e')
),
column_entries as (
    select pg_catalog.jsonb_build_object(
      'schema', n.nspname, 'relation', c.relname, 'position', a.attnum::pg_catalog.int4,
      'column', a.attname, 'type', pg_catalog.format_type(a.atttypid, a.atttypmod),
      'not_null', a.attnotnull, 'default', pg_catalog.pg_get_expr(ad.adbin, ad.adrelid, true),
      'identity', a.attidentity::pg_catalog.text, 'generated', a.attgenerated::pg_catalog.text) entry
      from pg_catalog.pg_attribute a
      join pg_catalog.pg_class c on c.oid = a.attrelid
      join pg_catalog.pg_namespace n on n.oid = c.relnamespace
      left join pg_catalog.pg_attrdef ad on ad.adrelid = a.attrelid and ad.adnum = a.attnum
     where n.nspname in ('public','agent_private') and c.relkind in ('r','p','v','m','f')
       and a.attnum > 0 and not a.attisdropped
       and not exists (
         select 1 from pg_catalog.pg_depend d
          where d.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
            and d.objid = c.oid and d.deptype = 'e')
),
constraint_entries as (
    select pg_catalog.jsonb_build_object(
      'schema', n.nspname, 'relation', c.relname, 'constraint', k.conname,
      'type', k.contype::pg_catalog.text, 'validated', k.convalidated,
      'deferrable', k.condeferrable, 'initially_deferred', k.condeferred,
      'definition', pg_catalog.pg_get_constraintdef(k.oid, true)) entry
      from pg_catalog.pg_constraint k
      join pg_catalog.pg_class c on c.oid = k.conrelid
      join pg_catalog.pg_namespace n on n.oid = c.relnamespace
     where n.nspname in ('public','agent_private')
),
index_entries as (
    select pg_catalog.jsonb_build_object(
      'schema', n.nspname, 'table', t.relname, 'index', i.relname,
      'unique', x.indisunique, 'primary', x.indisprimary,
      'exclusion', x.indisexclusion, 'valid', x.indisvalid,
      'ready', x.indisready, 'live', x.indislive,
      'definition', pg_catalog.pg_get_indexdef(i.oid, 0, true)) entry
      from pg_catalog.pg_index x
      join pg_catalog.pg_class i on i.oid = x.indexrelid
      join pg_catalog.pg_class t on t.oid = x.indrelid
      join pg_catalog.pg_namespace n on n.oid = t.relnamespace
     where n.nspname in ('public','agent_private')
),
function_entries as (
    select pg_catalog.jsonb_build_object(
      'schema', n.nspname, 'function', p.proname, 'kind', p.prokind::pg_catalog.text,
      'identity_arguments', pg_catalog.pg_get_function_identity_arguments(p.oid),
      'result', pg_catalog.pg_get_function_result(p.oid), 'language', l.lanname,
      'volatility', p.provolatile::pg_catalog.text, 'parallel', p.proparallel::pg_catalog.text,
      'strict', p.proisstrict, 'security_definer', p.prosecdef, 'leakproof', p.proleakproof,
      'configuration', coalesce(p.proconfig, array[]::pg_catalog.text[]),
      'definition', pg_catalog.pg_get_functiondef(p.oid),
      'owner', case
        when p.proowner in (dc.database_owner_oid, dc.database_owner_alias_oid)
          then 'DERIVATION_OWNER'
        when owner_role.rolname in ('anon','authenticated','service_role','agent_runtime')
          then owner_role.rolname
        else 'UNKNOWN_OWNER' end) entry
      from pg_catalog.pg_proc p
      join pg_catalog.pg_namespace n on n.oid = p.pronamespace
      join pg_catalog.pg_language l on l.oid = p.prolang
      join pg_catalog.pg_roles owner_role on owner_role.oid = p.proowner
      cross join database_context dc
     where n.nspname in ('public','agent_private')
       and not exists (
         select 1 from pg_catalog.pg_depend d
          where d.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
            and d.objid = p.oid and d.deptype = 'e')
),
trigger_rule_entries as (
    select pg_catalog.jsonb_build_object(
      'object_type','TRIGGER','schema',n.nspname,'relation',c.relname,
      'name',t.tgname,'enabled',t.tgenabled::pg_catalog.text,
      'definition',pg_catalog.pg_get_triggerdef(t.oid,true)) entry
      from pg_catalog.pg_trigger t
      join pg_catalog.pg_class c on c.oid=t.tgrelid
      join pg_catalog.pg_namespace n on n.oid=c.relnamespace
     where n.nspname in ('public','agent_private') and not t.tgisinternal
    union all
    select pg_catalog.jsonb_build_object(
      'object_type','REWRITE_RULE','schema',n.nspname,'relation',c.relname,
      'name',r.rulename,'enabled',r.ev_enabled::pg_catalog.text,
      'definition',pg_catalog.pg_get_ruledef(r.oid,true)) entry
      from pg_catalog.pg_rewrite r
      join pg_catalog.pg_class c on c.oid=r.ev_class
      join pg_catalog.pg_namespace n on n.oid=c.relnamespace
     where n.nspname in ('public','agent_private') and r.rulename <> '_RETURN'
),
rls_entries as (
    select pg_catalog.jsonb_build_object(
      'schema',n.nspname,'relation',c.relname,
      'enabled',c.relrowsecurity,'forced',c.relforcerowsecurity) entry
      from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid=c.relnamespace
     where n.nspname in ('public','agent_private') and c.relkind in ('r','p')
),
policy_entries as (
    select pg_catalog.jsonb_build_object(
      'schema',n.nspname,'relation',c.relname,'policy',p.polname,
      'permissive',p.polpermissive,'command',p.polcmd::pg_catalog.text,
      'roles',coalesce((select pg_catalog.array_agg(
        case when role_oid=0 then 'PUBLIC'
          when role_oid in (dc.database_owner_oid,dc.database_owner_alias_oid) then 'DERIVATION_OWNER'
          when pg_catalog.pg_get_userbyid(role_oid) in ('anon','authenticated','service_role','agent_runtime')
            then pg_catalog.pg_get_userbyid(role_oid)
          else 'UNKNOWN_OWNER' end
        order by case when role_oid=0 then 'PUBLIC'
          when role_oid in (dc.database_owner_oid,dc.database_owner_alias_oid) then 'DERIVATION_OWNER'
          when pg_catalog.pg_get_userbyid(role_oid) in ('anon','authenticated','service_role','agent_runtime')
            then pg_catalog.pg_get_userbyid(role_oid)
          else 'UNKNOWN_OWNER' end collate "C")
        from pg_catalog.unnest(p.polroles) role_oid),array[]::pg_catalog.text[]),
      'using',pg_catalog.pg_get_expr(p.polqual,p.polrelid,true),
      'with_check',pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid,true)) entry
      from pg_catalog.pg_policy p
      join pg_catalog.pg_class c on c.oid=p.polrelid
      join pg_catalog.pg_namespace n on n.oid=c.relnamespace
      cross join database_context dc
     where n.nspname in ('public','agent_private')
),
schema_acl as (
    select 'SCHEMA'::pg_catalog.text object_type,n.nspname schema_name,n.nspname object_identity,
      null::pg_catalog.text column_name,n.nspowner owner_id,
      pg_catalog.aclexplode(coalesce(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) acl
      from pg_catalog.pg_namespace n where n.nspname in ('public','agent_private')
),
relation_acl as (
    select 'RELATION'::pg_catalog.text,n.nspname,c.relname,null::pg_catalog.text,c.relowner,
      pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault(
        case when c.relkind='S' then 's'::"char" else 'r'::"char" end,c.relowner))) acl
      from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid=c.relnamespace
     where n.nspname in ('public','agent_private') and c.relkind in ('r','p','v','m','S','f')
       and not exists (select 1 from pg_catalog.pg_depend d
         where d.classid='pg_catalog.pg_class'::pg_catalog.regclass and d.objid=c.oid and d.deptype='e')
),
column_acl as (
    select 'COLUMN'::pg_catalog.text,n.nspname,c.relname,a.attname,c.relowner,
      pg_catalog.aclexplode(a.attacl) acl
      from pg_catalog.pg_attribute a join pg_catalog.pg_class c on c.oid=a.attrelid
      join pg_catalog.pg_namespace n on n.oid=c.relnamespace
     where n.nspname in ('public','agent_private') and a.attnum>0 and not a.attisdropped and a.attacl is not null
),
function_acl as (
    select 'FUNCTION'::pg_catalog.text,n.nspname,
      p.proname||'('||pg_catalog.pg_get_function_identity_arguments(p.oid)||')',
      null::pg_catalog.text,p.proowner,
      pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) acl
      from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
     where n.nspname in ('public','agent_private')
       and not exists (select 1 from pg_catalog.pg_depend d
         where d.classid='pg_catalog.pg_proc'::pg_catalog.regclass and d.objid=p.oid and d.deptype='e')
),
privilege_entries as (
    select pg_catalog.jsonb_build_object(
      'object_type',object_type,'schema',schema_name,'object',object_identity,'column',column_name,
      'grantor',case when (acl).grantor=owner_id then 'DERIVATION_OWNER'
        when pg_catalog.pg_get_userbyid((acl).grantor) in ('anon','authenticated','service_role','agent_runtime')
          then pg_catalog.pg_get_userbyid((acl).grantor) else 'UNKNOWN_OWNER' end,
      'grantee',case when (acl).grantee=0 then 'PUBLIC' when (acl).grantee=owner_id then 'DERIVATION_OWNER'
        when pg_catalog.pg_get_userbyid((acl).grantee) in ('anon','authenticated','service_role','agent_runtime')
          then pg_catalog.pg_get_userbyid((acl).grantee) else 'UNKNOWN_OWNER' end,
      'privilege',(acl).privilege_type,'grantable',(acl).is_grantable) entry
      from (select * from schema_acl union all select * from relation_acl
            union all select * from column_acl union all select * from function_acl) combined
),
default_privilege_entries as (
    select pg_catalog.jsonb_build_object(
      'object_type',case d.defaclobjtype when 'r' then 'RELATION' when 'S' then 'SEQUENCE'
        when 'f' then 'FUNCTION' when 'T' then 'TYPE' when 'n' then 'SCHEMA'
        else d.defaclobjtype::pg_catalog.text end,
      'schema',coalesce(n.nspname,'GLOBAL'),'owner',
      case when d.defaclrole=dc.database_owner_oid then 'DERIVATION_OWNER'
        when owner_role.rolname in ('anon','authenticated','service_role','agent_runtime') then owner_role.rolname
        else 'UNKNOWN_OWNER' end,
      'grantor',case when (acl).grantor=d.defaclrole then 'DERIVATION_OWNER'
        when pg_catalog.pg_get_userbyid((acl).grantor) in ('anon','authenticated','service_role','agent_runtime')
          then pg_catalog.pg_get_userbyid((acl).grantor) else 'UNKNOWN_OWNER' end,
      'grantee',case when (acl).grantee=0 then 'PUBLIC' when (acl).grantee=d.defaclrole then 'DERIVATION_OWNER'
        when pg_catalog.pg_get_userbyid((acl).grantee) in ('anon','authenticated','service_role','agent_runtime')
          then pg_catalog.pg_get_userbyid((acl).grantee) else 'UNKNOWN_OWNER' end,
      'privilege',(acl).privilege_type,'grantable',(acl).is_grantable) entry
      from pg_catalog.pg_default_acl d
      join pg_catalog.pg_roles owner_role on owner_role.oid=d.defaclrole
      left join pg_catalog.pg_namespace n on n.oid=d.defaclnamespace
      cross join lateral pg_catalog.aclexplode(d.defaclacl) acl
      cross join database_context dc
     where d.defaclrole=dc.database_owner_oid
        or owner_role.rolname in ('anon','authenticated','service_role','agent_runtime')
),
domain_rows as (
    select 'EXTENSIONS'::pg_catalog.text name, entry from extension_entries union all
    select 'ENUM_TYPES_AND_VALUES', entry from enum_entries union all
    select 'ROLES_AND_MEMBERSHIPS', entry from role_entries union all
    select 'SCHEMAS_AND_OWNERS', entry from schema_entries union all
    select 'RELATIONS_AND_PERSISTENCE', entry from relation_entries union all
    select 'COLUMNS_TYPES_DEFAULTS_IDENTITY_GENERATED', entry from column_entries union all
    select 'CONSTRAINTS_AND_VALIDATION_STATE', entry from constraint_entries union all
    select 'INDEXES_DEFINITIONS_AND_VALIDITY', entry from index_entries union all
    select 'FUNCTIONS_SIGNATURE_LANGUAGE_VOLATILITY_SECURITY_SEARCH_PATH', entry from function_entries union all
    select 'TRIGGERS_AND_REWRITE_RULES', entry from trigger_rule_entries union all
    select 'RLS_ENABLE_FORCE_FLAGS', entry from rls_entries union all
    select 'POLICIES_COMMAND_ROLES_USING_WITH_CHECK', entry from policy_entries union all
    select 'TABLE_COLUMN_FUNCTION_SCHEMA_PRIVILEGES', entry from privilege_entries union all
    select 'DEFAULT_PRIVILEGES', entry from default_privilege_entries
),
required_domains(name) as (values
  ('EXTENSIONS'),('ENUM_TYPES_AND_VALUES'),('ROLES_AND_MEMBERSHIPS'),
  ('SCHEMAS_AND_OWNERS'),('RELATIONS_AND_PERSISTENCE'),
  ('COLUMNS_TYPES_DEFAULTS_IDENTITY_GENERATED'),('CONSTRAINTS_AND_VALIDATION_STATE'),
  ('INDEXES_DEFINITIONS_AND_VALIDITY'),
  ('FUNCTIONS_SIGNATURE_LANGUAGE_VOLATILITY_SECURITY_SEARCH_PATH'),
  ('TRIGGERS_AND_REWRITE_RULES'),('RLS_ENABLE_FORCE_FLAGS'),
  ('POLICIES_COMMAND_ROLES_USING_WITH_CHECK'),
  ('TABLE_COLUMN_FUNCTION_SCHEMA_PRIVILEGES'),('DEFAULT_PRIVILEGES')
),
domain_documents as (
    select rd.name, coalesce(
      pg_catalog.jsonb_agg(dr.entry order by dr.entry::pg_catalog.text)
        filter (where dr.entry is not null), '[]'::pg_catalog.jsonb) entries
      from required_domains rd left join domain_rows dr on dr.name=rd.name
     group by rd.name
),
ledger_metadata as (
    select
      case when pg_catalog.to_regclass('public.schema_migrations') is null then 'ABSENT'
        when exists (select 1 from pg_catalog.pg_class c
          where c.oid=pg_catalog.to_regclass('public.schema_migrations') and c.relkind='r')
          then 'PRESENT' else 'INVALID' end public_state,
      case when pg_catalog.to_regclass('supabase_migrations.schema_migrations') is null then 'ABSENT'
        when exists (select 1 from pg_catalog.pg_class c
          where c.oid=pg_catalog.to_regclass('supabase_migrations.schema_migrations') and c.relkind='r')
          then 'PRESENT' else 'INVALID' end native_state
)
select pg_catalog.json_build_object(
  'capture_contract','MIGRATION_HISTORY_ENVIRONMENT_ATTESTATION_CAPTURE_V1',
  'system_identifier',control.system_identifier::pg_catalog.text,
  'database_name',pg_catalog.current_database(),
  'server_version_num',pg_catalog.current_setting('server_version_num')::pg_catalog.int8,
  'current_user_matches_session_user',current_user=session_user,
  'tls',coalesce((select ssl from pg_catalog.pg_stat_ssl
    where pid=pg_catalog.pg_backend_pid()),false),
  'isolation_level',pg_catalog.current_setting('transaction_isolation'),
  'read_only',pg_catalog.current_setting('transaction_read_only'),
  'full_visibility',coalesce((select r.rolsuper or r.rolbypassrls
    from pg_catalog.pg_roles r where r.rolname=current_user),false),
  'domains',(select pg_catalog.json_agg(pg_catalog.json_build_object(
    'name',name,'entries',entries) order by name collate "C") from domain_documents),
  'ledgers',pg_catalog.json_build_object('public',lm.public_state,'native',lm.native_state)
) as transient_private_capture
from pg_catalog.pg_control_system() control cross join ledger_metadata lm;
-- metadata-capture-end

/*
 * ALLOWLISTED INVARIANT QUERY BUNDLE
 *
 * Never send this bundle to PostgreSQL as one unit. A future, separately
 * authorized executor must first compare the metadata capture to the canonical
 * profile. It then selects exact blocks by repository marker and digest. All
 * eligible blocks run, as separate statements, on the same connection between
 * the transaction markers below. A failed shape/visibility preflight emits
 * UNKNOWN without preparing the affected DATA block. Only a recoverable SQL
 * statement failure under its per-invariant savepoint, including permission,
 * timeout, parse or concurrent-DDL failure, emits ERROR without SQLERRM after
 * rollback to that savepoint and session-proof revalidation. Session or
 * transport loss, savepoint rollback failure, proof drift or final ROLLBACK
 * failure aborts the complete capture without materializing an artifact.
 */

-- invariant-data-begin:TENANT_FOREIGN_KEY_CONSISTENCY
with violations as (
  select 1 from public.pessoas c left join public.pessoas p on p.id=c.lider_id
   where c.lider_id is not null and (p.id is null or c.igreja_id is distinct from p.igreja_id)
  union all select 1 from public.pessoas c left join public.app_users p on p.id=c.arquivada_por
   where c.arquivada_por is not null and (p.id is null or c.igreja_id is distinct from p.igreja_id)
  union all select 1 from public.app_users c left join public.pessoas p on p.id=c.pessoa_id
   where p.id is null or c.igreja_id is distinct from p.igreja_id
  union all select 1 from public.user_roles c left join public.app_users p on p.id=c.user_id
   where p.id is null or c.igreja_id is distinct from p.igreja_id
  union all select 1 from public.conversations c left join public.pessoas p on p.id=c.pessoa_id
   where c.pessoa_id is not null and (p.id is null or c.igreja_id is distinct from p.igreja_id)
  union all select 1 from public.conversations c left join public.app_users p on p.id=c.assumido_por
   where c.assumido_por is not null and (p.id is null or c.igreja_id is distinct from p.igreja_id)
  union all select 1 from public.messages c left join public.conversations p on p.id=c.conversation_id
   where p.id is null or c.igreja_id is distinct from p.igreja_id
  union all select 1 from public.messages c left join public.app_users p on p.id=c.enviado_por
   where c.enviado_por is not null and (p.id is null or c.igreja_id is distinct from p.igreja_id)
  union all select 1 from public.consent_records c left join public.pessoas p on p.id=c.pessoa_id
   where p.id is null or c.igreja_id is distinct from p.igreja_id
  union all select 1 from public.consent_records c left join public.app_users p on p.id=c.ator_id
   where c.ator_id is not null and (p.id is null or c.igreja_id is distinct from p.igreja_id)
  union all select 1 from public.consentimento_finalidade_evento c left join public.pessoas p on p.id=c.pessoa_id
   where p.id is null or c.igreja_id is distinct from p.igreja_id
  union all select 1 from public.consentimento_finalidade_evento c left join public.app_users p on p.id=c.registrado_por_app_user_id
   where c.registrado_por_app_user_id is not null and (p.id is null or c.igreja_id is distinct from p.igreja_id)
), result as (select pg_catalog.count(*)::pg_catalog.int8 violation_count from violations)
select pg_catalog.json_build_object('id','TENANT_FOREIGN_KEY_CONSISTENCY',
 'state',case when violation_count=0 then 'PASS' else 'FAIL' end,
 'checks_executed',12,'violation_count',violation_count) from result;
-- invariant-data-end:TENANT_FOREIGN_KEY_CONSISTENCY

-- invariant-data-begin:TENANT_UNIQUENESS_GUARDS
with duplicate_groups as (
  select 1 from public.whatsapp_connections where instance is not null group by instance having count(*)>1
  union all select 1 from public.whatsapp_connections group by igreja_id having count(*)>1
  union all select 1 from public.agent_configs group by igreja_id having count(*)>1
  union all select 1 from public.llm_credentials group by igreja_id having count(*)>1
  union all select 1 from public.subscriptions group by igreja_id having count(*)>1
  union all select 1 from public.purpose_consent_governance_envelope group by igreja_id having count(*)>1
  union all select 1 from public.pessoas where arquivada_em is null group by igreja_id,telefone having count(*)>1
  union all select 1 from public.agenda_alert_recipients where ativo group by igreja_id,telefone having count(*)>1
  union all select 1 from public.celula_membro where ativo group by igreja_id,pessoa_id having count(*)>1
  union all select 1 from public.celula_solicitacao
   where status in ('aguardando','ajuste_solicitado') and pessoa_id is null
   group by igreja_id,celula_id,tipo having count(*)>1
  union all select 1 from public.celula_solicitacao
   where status in ('aguardando','ajuste_solicitado') and pessoa_id is not null
   group by igreja_id,celula_id,pessoa_id having count(*)>1
  union all select 1 from public.consolidacoes where concluida=false and abandonada_em is null
   group by pessoa_id having count(*)>1
  union all select 1 from public.celula_reuniao
   group by igreja_id,celula_id,data,coalesce(hora,'') having count(*)>1
  union all select 1 from public.celula_presenca group by igreja_id,reuniao_id,pessoa_id having count(*)>1
), result as (select pg_catalog.count(*)::pg_catalog.int8 violation_count from duplicate_groups)
select pg_catalog.json_build_object('id','TENANT_UNIQUENESS_GUARDS',
 'state',case when violation_count=0 then 'PASS' else 'FAIL' end,
 'checks_executed',14,'violation_count',violation_count) from result;
-- invariant-data-end:TENANT_UNIQUENESS_GUARDS

-- invariant-data-begin:APPEND_ONLY_AUDIT_INTEGRITY
select pg_catalog.json_build_object('id','APPEND_ONLY_AUDIT_INTEGRITY',
 'state','UNKNOWN','checks_executed',5,'violation_count',0);
-- invariant-data-end:APPEND_ONLY_AUDIT_INTEGRITY

-- invariant-data-begin:IDEMPOTENCY_UNIQUENESS
with duplicate_groups as (
  select 1 from public.events where google_event_id is not null group by igreja_id,google_event_id having count(*)>1
  union all select 1 from public.messages where direcao='in' and provider_message_id is not null group by igreja_id,provider_message_id having count(*)>1
  union all select 1 from public.messages where direcao='out' and provider_message_id is not null group by igreja_id,provider_message_id having count(*)>1
  union all select 1 from public.agent_conversation_logs
   where (evento like 'sla\_%' escape '\' or evento like 'subscription\_upgrade:%' escape '\')
   group by igreja_id,evento having count(*)>1
  union all select 1 from public.multiplicacoes where solicitacao_id is not null group by solicitacao_id having count(*)>1
  union all select 1 from public.multiplicacoes where idempotency_key is not null group by igreja_id,idempotency_key having count(*)>1
  union all select 1 from public.broadcasts where idempotency_key is not null group by igreja_id,idempotency_key having count(*)>1
  union all select 1 from public.broadcast_execucoes group by broadcast_id,seq having count(*)>1
  union all select 1 from public.broadcast_execucoes group by igreja_id,broadcast_id,data_nominal,coalesce(hora_nominal,'') having count(*)>1
  union all select 1 from public.broadcast_entregas group by execucao_id,telefone having count(*)>1
  union all select 1 from public.broadcast_entregas where pessoa_id is not null group by execucao_id,pessoa_id having count(*)>1
  union all select 1 from public.calendar_oauth_flows group by state_hash having count(*)>1
  union all select 1 from public.calendar_oauth_flows group by flow_secret_hash having count(*)>1
  union all select 1 from public.password_reset_tokens group by jti having count(*)>1
  union all select 1 from public.billing_payment_operations group by operation_key having count(*)>1
  union all select 1 from public.billing_payment_operations where asaas_payment_id is not null group by asaas_payment_id having count(*)>1
  union all select 1 from public.billing_payment_operations where status in ('prepared','creating','reconciling','created') group by subscription_id,purpose,coalesce(source_payment_id,'') having count(*)>1
  union all select 1 from public.billing_subscription_operations group by operation_key having count(*)>1
  union all select 1 from public.billing_subscription_operations where status in ('prepared','creating','reconciling') group by subscription_id having count(*)>1
  union all select 1 from public.billing_subscription_operations where asaas_subscription_id is not null group by asaas_subscription_id having count(*)>1
  union all select 1 from public.billing_plan_change_operations where status in ('prepared','processing','reconciling') group by subscription_id having count(*)>1
  union all select 1 from public.asaas_webhook_receipts group by event_id having count(*)>1
  union all select 1 from public.consentimento_finalidade_evento group by igreja_id,chave_idempotencia having count(*)>1
  union all select 1 from public.consentimento_finalidade_evento group by igreja_id,pessoa_id,finalidade,sequencia having count(*)>1
), result as (select pg_catalog.count(*)::pg_catalog.int8 violation_count from duplicate_groups)
select pg_catalog.json_build_object('id','IDEMPOTENCY_UNIQUENESS',
 'state',case when violation_count=0 then 'PASS' else 'FAIL' end,
 'checks_executed',24,'violation_count',violation_count) from result;
-- invariant-data-end:IDEMPOTENCY_UNIQUENESS

-- invariant-data-begin:CONSENT_LEDGER_INTEGRITY
with row_v as (
  select 1 from public.consentimento_finalidade_evento e
  left join public.pessoas p on p.id=e.pessoa_id
  left join public.app_users a on a.id=e.registrado_por_app_user_id
  where p.id is null or p.igreja_id is distinct from e.igreja_id
    or (e.registrado_por_app_user_id is not null and (a.id is null or a.igreja_id is distinct from e.igreja_id))
    or e.finalidade not in ('atendimento_solicitado','cuidado_pastoral','tarefas_operacionais','comunicados')
    or e.estado not in ('concedido','retirado')
    or e.fonte not in ('whatsapp_inbound','painel_autenticado')
    or (e.fonte='painel_autenticado' and e.registrado_por_app_user_id is null)
    or (e.fonte='whatsapp_inbound' and e.registrado_por_app_user_id is not null)
    or e.versao_termo is distinct from pg_catalog.btrim(e.versao_termo)
    or pg_catalog.char_length(e.versao_termo) not between 1 and 128
    or e.versao_termo ~ '[[:cntrl:]]'
    or e.chave_idempotencia is distinct from pg_catalog.btrim(e.chave_idempotencia)
    or pg_catalog.char_length(e.chave_idempotencia) not between 1 and 128
    or e.chave_idempotencia !~ '^[a-z0-9][a-z0-9:._-]{0,127}$'
    or e.sequencia<1
), stream_v as (
  select 1 from public.consentimento_finalidade_evento
   group by igreja_id,pessoa_id,finalidade
  having min(sequencia)<>1 or max(sequencia)<>count(*) or count(distinct sequencia)<>count(*)
), idem_v as (
  select 1 from public.consentimento_finalidade_evento
   group by igreja_id,chave_idempotencia having count(*)>1
), violations as (select * from row_v union all select * from stream_v union all select * from idem_v),
result as (select pg_catalog.count(*)::pg_catalog.int8 violation_count from violations)
select pg_catalog.json_build_object('id','CONSENT_LEDGER_INTEGRITY',
 'state',case when violation_count=0 then 'PASS' else 'FAIL' end,
 'checks_executed',3,'violation_count',violation_count) from result;
-- invariant-data-end:CONSENT_LEDGER_INTEGRITY

-- invariant-data-begin:BILLING_ISOLATION_INTEGRITY
with violations as (
  select 1 from public.subscriptions where asaas_customer_external_reference is not null and asaas_customer_external_reference not like 'pastorai-%'
  union all select 1 from public.subscriptions where asaas_subscription_external_reference is not null and asaas_subscription_external_reference not like 'pastorai-%'
  union all select 1 from public.subscriptions where asaas_customer_id is not null and asaas_customer_id<>'sandbox' group by asaas_customer_id having count(*)>1
  union all select 1 from public.subscriptions where asaas_subscription_id is not null and asaas_subscription_id<>'sandbox' group by asaas_subscription_id having count(*)>1
  union all select 1 from public.subscriptions where asaas_customer_external_reference is not null group by asaas_customer_external_reference having count(*)>1
  union all select 1 from public.subscriptions where asaas_subscription_external_reference is not null group by asaas_subscription_external_reference having count(*)>1
  union all select 1 from public.subscriptions where asaas_setup_charge_id is not null group by asaas_setup_charge_id having count(*)>1
  union all select 1 from public.billing_payment_operations group by operation_key having count(*)>1
  union all select 1 from public.billing_payment_operations where asaas_payment_id is not null group by asaas_payment_id having count(*)>1
  union all select 1 from public.billing_payment_operations where status in ('prepared','creating','reconciling','created') group by subscription_id,purpose,coalesce(source_payment_id,'') having count(*)>1
  union all select 1 from public.billing_subscription_operations group by operation_key having count(*)>1
  union all select 1 from public.billing_subscription_operations where asaas_subscription_id is not null group by asaas_subscription_id having count(*)>1
  union all select 1 from public.billing_subscription_operations where status in ('prepared','creating','reconciling') group by subscription_id having count(*)>1
  union all select 1 from public.billing_plan_change_operations where status in ('prepared','processing','reconciling') group by subscription_id having count(*)>1
  union all select 1 from public.billing_payment_operations o left join public.subscriptions s on s.id=o.subscription_id where s.id is null
  union all select 1 from public.billing_subscription_operations o left join public.subscriptions s on s.id=o.subscription_id where s.id is null
  union all select 1 from public.billing_plan_change_operations o left join public.subscriptions s on s.id=o.subscription_id where s.id is null
  union all select 1 from public.billing_plan_change_operations o join public.subscriptions s on s.id=o.subscription_id
   where o.status in ('prepared','processing','reconciling') and o.asaas_subscription_id is distinct from s.asaas_subscription_id
  union all select 1 from public.asaas_webhook_receipts group by event_id having count(*)>1
), result as (select pg_catalog.count(*)::pg_catalog.int8 violation_count from violations)
select pg_catalog.json_build_object('id','BILLING_ISOLATION_INTEGRITY',
 'state',case when violation_count=0 then 'PASS' else 'FAIL' end,
 'checks_executed',19,'violation_count',violation_count) from result;
-- invariant-data-end:BILLING_ISOLATION_INTEGRITY

-- invariant-data-begin:RECOVERY_ARTIFACT_RETENTION
select pg_catalog.set_config('statement_timeout','5000',true);
with expected(schema_name,table_name,review_date,close_service_role) as (values
 ('public'::text,'_clerk_migration_rollback_20260823_032220'::text,'2026-11-21'::text,false),
 ('recovery'::text,'encrypted_credentials_backup_20260805'::text,'2026-11-03'::text,true)
), objects as (
 select e.*,n.oid namespace_oid,c.oid relation_oid,c.relkind,c.relrowsecurity,
   pg_catalog.obj_description(c.oid,'pg_class') comment_text
 from expected e left join pg_catalog.pg_namespace n on n.nspname=e.schema_name
 left join pg_catalog.pg_class c on c.relnamespace=n.oid and c.relname=e.table_name
), evaluated as (
 select o.*,
   case when relation_oid is null then false else
     relkind in ('r','p') and relrowsecurity and position(review_date in coalesce(comment_text,''))>0
     and (select count(*)=1 from pg_catalog.pg_policy p where p.polrelid=relation_oid
       and p.polname='recovery_artifact_deny_all' and p.polcmd='*' and not p.polpermissive
       and p.polroles=array[0::oid]
       and coalesce(pg_catalog.pg_get_expr(p.polqual,p.polrelid,true),'')='false'
       and coalesce(pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid,true),'')='false')
     and not pg_catalog.has_table_privilege('anon',relation_oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
     and not pg_catalog.has_table_privilege('authenticated',relation_oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
     and not pg_catalog.has_any_column_privilege('anon',relation_oid,'SELECT,INSERT,UPDATE,REFERENCES')
     and not pg_catalog.has_any_column_privilege('authenticated',relation_oid,'SELECT,INSERT,UPDATE,REFERENCES')
     and (not close_service_role or (
       not pg_catalog.has_table_privilege('service_role',relation_oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
       and not pg_catalog.has_any_column_privilege('service_role',relation_oid,'SELECT,INSERT,UPDATE,REFERENCES')))
     and (schema_name<>'recovery' or (
       not pg_catalog.has_schema_privilege('anon',namespace_oid,'USAGE,CREATE')
       and not pg_catalog.has_schema_privilege('authenticated',namespace_oid,'USAGE,CREATE')
       and not pg_catalog.has_schema_privilege('service_role',namespace_oid,'USAGE,CREATE')))
   end hardened
 from objects o
), result as materialized (
 select count(*) filter (where relation_oid is null)::int8 missing_count,
        count(*) filter (where relation_oid is not null and not hardened)::int8 violation_count
 from evaluated
), reset_timeout as materialized (
 select result.*,pg_catalog.set_config('statement_timeout','30000',true) reset_value
 from result
)
select pg_catalog.json_build_object('id','RECOVERY_ARTIFACT_RETENTION',
 'state',case when violation_count>0 then 'FAIL' when missing_count>0 then 'UNKNOWN' else 'PASS' end,
 'checks_executed',2,'violation_count',violation_count) from reset_timeout;
-- invariant-data-end:RECOVERY_ARTIFACT_RETENTION

-- invariant-data-begin:GOVERNANCE_DRAFT_INTEGRITY
with purposes(value) as (values
 ('atendimento_solicitado'::text),('cuidado_pastoral'),('tarefas_operacionais'),('comunicados')
), fields(value) as (values
 ('real_processing_agents'::text),('operations_and_minimum_data'),('data_sensitivity_assessment'),
 ('operational_need'),('systems_and_recipients'),('retention_and_disposal_inventory'),
 ('operator_instructions'),('open_questions')
), base as (
 select e.*,
   pg_catalog.jsonb_typeof(e.drafts)='object' drafts_object,
   pg_catalog.jsonb_typeof(e.draft_revisions)='object' revisions_object
 from public.purpose_consent_governance_envelope e
), revision_parts as (
 select b.id,p.value purpose,b.draft_revisions->>p.value revision_text
 from base b cross join purposes p
), revision_sums as (
 select id,sum(revision_text::bigint) revision_sum
 from revision_parts
 where revision_text ~ '^[1-9][0-9]{0,17}$'
 group by id having count(*)=4
), row_v as (
 select 1 from base b left join revision_sums rs on rs.id=b.id
 left join public.app_users c on c.id=b.created_by_app_user_id
 left join public.app_users u on u.id=b.updated_by_app_user_id
 where b.schema_version<>'d2b2b3a/governance-draft/v1'
    or b.status<>'DRAFT_NOT_APPROVED' or b.revision<1
    or not b.drafts_object or not b.revisions_object
    or case when b.drafts_object then
      (select pg_catalog.array_agg(k order by k collate "C") from pg_catalog.jsonb_object_keys(b.drafts) k)
       is distinct from array['atendimento_solicitado','comunicados','cuidado_pastoral','tarefas_operacionais']::text[]
      else true end
    or case when b.revisions_object then
      (select pg_catalog.array_agg(k order by k collate "C") from pg_catalog.jsonb_object_keys(b.draft_revisions) k)
       is distinct from array['atendimento_solicitado','comunicados','cuidado_pastoral','tarefas_operacionais']::text[]
      else true end
    or exists (select 1 from purposes p where pg_catalog.jsonb_typeof(b.draft_revisions->p.value)<>'number'
       or b.draft_revisions->>p.value !~ '^[1-9][0-9]{0,17}$')
    or rs.id is null or b.revision<>rs.revision_sum-3
    or (b.created_by_app_user_id is not null and c.id is null)
    or (b.updated_by_app_user_id is not null and u.id is null)
    or b.created_at>b.updated_at
), draft_v as (
 select distinct 1 from base b cross join purposes p
 where pg_catalog.jsonb_typeof(b.drafts->p.value) is distinct from 'object'
    or case when pg_catalog.jsonb_typeof(b.drafts->p.value)='object' then
      (select pg_catalog.array_agg(k order by k collate "C") from pg_catalog.jsonb_object_keys(b.drafts->p.value) k)
       is distinct from array['data_sensitivity_assessment','open_questions','operational_need','operations_and_minimum_data','operator_instructions','real_processing_agents','retention_and_disposal_inventory','systems_and_recipients']::text[]
      else true end
    or exists (select 1 from fields f
      where (pg_catalog.jsonb_typeof(b.drafts->p.value->f.value) is distinct from 'null'
        and pg_catalog.jsonb_typeof(b.drafts->p.value->f.value) is distinct from 'string')
       or (pg_catalog.jsonb_typeof(b.drafts->p.value->f.value)='string' and (
         b.drafts->p.value->>f.value is distinct from pg_catalog.btrim(b.drafts->p.value->>f.value,E' \t\n\r\f\v\u00a0')
         or pg_catalog.char_length(b.drafts->p.value->>f.value) not between 1 and 4000
         or b.drafts->p.value->>f.value ~ '[\x01-\x08\x0B-\x1F\x7F-\x9F]')))
    or (select coalesce(sum(pg_catalog.char_length(b.drafts->p.value->>f.value)),0)
        from fields f where pg_catalog.jsonb_typeof(b.drafts->p.value->f.value)='string')>16000
), violations as (select * from row_v union all select * from draft_v),
result as (select pg_catalog.count(*)::pg_catalog.int8 violation_count from violations)
select pg_catalog.json_build_object('id','GOVERNANCE_DRAFT_INTEGRITY',
 'state',case when violation_count=0 then 'PASS' else 'FAIL' end,
 'checks_executed',2,'violation_count',violation_count) from result;
-- invariant-data-end:GOVERNANCE_DRAFT_INTEGRITY

-- transaction-close-begin
rollback;
-- transaction-close-end
