-- PastorAI D2B2b3A: rascunhos governados por finalidade no Console Master.
--
-- Uma linha por igreja contém exatamente quatro rascunhos. Esta migration não
-- cria aprovações, digest, catálogo, evidence store, writer, caller de runtime
-- ou backfill. O único status possível é DRAFT_NOT_APPROVED. A tabela fica no
-- schema public para entrar no backup lógico existente, mas sem Data API: RLS
-- habilitada e forçada, nenhuma policy e nenhuma ACL fora do owner.
--
-- Rollback exige migration compensatória. Enquanto não houver conteúdo, ela
-- pode provar a tabela vazia antes de remover os objetos. Depois do uso, o
-- rollback do aplicativo deve preservar os rascunhos e sua proveniência.

begin;

set transaction isolation level serializable;
set local search_path = pg_catalog;
set local lock_timeout = '5s';
set local statement_timeout = '120s';

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(
    '20260828_094914_d2b2b3_purpose_consent_governance_drafts',
    0
  )
);

do $preflight$
begin
  if not exists (
       select 1
         from pg_catalog.pg_roles role_row
        where role_row.rolname = current_user
          and (role_row.rolsuper or role_row.rolbypassrls)
     )
  then
    raise exception using
      errcode = '42501',
      message = 'D2B2b3A preflight: executor cannot bypass forced RLS';
  end if;
  if exists (
       select 1
         from pg_catalog.unnest(array[
           'anon', 'authenticated', 'service_role', 'agent_runtime'
         ]::text[]) role_name(name)
         join pg_catalog.pg_roles application_role
           on application_role.rolname = role_name.name
        where pg_catalog.pg_has_role(
          application_role.oid,
          pg_catalog.to_regrole(current_user),
          'MEMBER'
        )
     )
  then
    raise exception using
      errcode = '42501',
      message = 'D2B2b3A preflight: application role reaches executor';
  end if;
  if pg_catalog.to_regclass('public.igrejas') is null
     or pg_catalog.to_regclass('public.app_users') is null
  then
    raise exception using
      errcode = '42P01',
      message = 'D2B2b3A preflight: required parent tables are absent';
  end if;
end
$preflight$;

lock table public.igrejas, public.app_users in share row exclusive mode;

create temporary table d2b2b3_migration_state (
  table_was_absent boolean not null,
  function_was_absent boolean not null
) on commit drop;

insert into pg_temp.d2b2b3_migration_state values (
  pg_catalog.to_regclass(
    'public.purpose_consent_governance_envelope'
  ) is null,
  pg_catalog.to_regprocedure(
    'public.purpose_consent_governance_draft_valid(jsonb)'
  ) is null
);

create or replace function pg_temp.d2b2b3_normalize(value text)
returns text
language sql
immutable
strict
set search_path = pg_catalog
as $normalize$
  select pg_catalog.regexp_replace(
    value,
    '[[:space:]()";]',
    '',
    'g'
  );
$normalize$;

-- Pure validator used only by the CHECK constraint. A homonymous function is
-- never replaced: exact definition, ownership and ACL are proved first.
do $function_guard$
declare
  validator_oid oid := pg_catalog.to_regprocedure(
    'public.purpose_consent_governance_draft_valid(jsonb)'
  );
  validator pg_catalog.pg_proc%rowtype;
  table_was_absent boolean;
  function_was_absent boolean;
  expected_body constant text := $expected_body$
declare
  expected_fields constant text[] := array[
    'real_processing_agents',
    'operations_and_minimum_data',
    'data_sensitivity_assessment',
    'operational_need',
    'systems_and_recipients',
    'retention_and_disposal_inventory',
    'operator_instructions',
    'open_questions'
  ];
  field_name text;
  field_kind text;
  field_value text;
  character_position integer;
  character_code integer;
  total_length integer := 0;
  trim_characters constant text :=
    pg_catalog.chr(9) || pg_catalog.chr(10) ||
    pg_catalog.chr(11) || pg_catalog.chr(12) ||
    pg_catalog.chr(13) || pg_catalog.chr(28) ||
    pg_catalog.chr(29) || pg_catalog.chr(30) ||
    pg_catalog.chr(31) || pg_catalog.chr(32) ||
    pg_catalog.chr(133) || pg_catalog.chr(160) ||
    pg_catalog.chr(5760) || pg_catalog.chr(8192) ||
    pg_catalog.chr(8193) || pg_catalog.chr(8194) ||
    pg_catalog.chr(8195) || pg_catalog.chr(8196) ||
    pg_catalog.chr(8197) || pg_catalog.chr(8198) ||
    pg_catalog.chr(8199) || pg_catalog.chr(8200) ||
    pg_catalog.chr(8201) || pg_catalog.chr(8202) ||
    pg_catalog.chr(8232) || pg_catalog.chr(8233) ||
    pg_catalog.chr(8239) || pg_catalog.chr(8287) ||
    pg_catalog.chr(12288);
begin
  if pg_catalog.jsonb_typeof(payload) <> 'object'
     or not payload ?& expected_fields
     or payload
          - 'real_processing_agents'
          - 'operations_and_minimum_data'
          - 'data_sensitivity_assessment'
          - 'operational_need'
          - 'systems_and_recipients'
          - 'retention_and_disposal_inventory'
          - 'operator_instructions'
          - 'open_questions' <> '{}'::jsonb
  then
    return false;
  end if;

  foreach field_name in array expected_fields loop
    field_kind := pg_catalog.jsonb_typeof(payload -> field_name);
    if field_kind = 'null' then
      continue;
    end if;
    if field_kind <> 'string' then
      return false;
    end if;

    field_value := payload ->> field_name;
    if field_value = ''
       or field_value <> pg_catalog.btrim(field_value, trim_characters)
       or pg_catalog.char_length(field_value) > 4000
    then
      return false;
    end if;
    for character_position in 1..pg_catalog.char_length(field_value) loop
      character_code := pg_catalog.ascii(
        pg_catalog.substr(field_value, character_position, 1)
      );
      if character_code between 1 and 8
         or character_code between 11 and 31
         or character_code between 127 and 159
      then
        return false;
      end if;
    end loop;
    total_length := total_length + pg_catalog.char_length(field_value);
  end loop;

  return total_length <= 16000;
end
$expected_body$;
begin
  select state.table_was_absent, state.function_was_absent
    into strict table_was_absent, function_was_absent
    from pg_temp.d2b2b3_migration_state state;

  if validator_oid is null then
    if not table_was_absent or not function_was_absent then
      raise exception using
        errcode = 'P0001',
        message = 'D2B2b3A guard: validator is absent from an existing contract';
    end if;
    execute $ddl$
      create function public.purpose_consent_governance_draft_valid(
        payload jsonb
      )
      returns boolean
      language plpgsql
      immutable
      strict
      parallel safe
      security invoker
      set search_path = pg_catalog
      as $function$
declare
  expected_fields constant text[] := array[
    'real_processing_agents',
    'operations_and_minimum_data',
    'data_sensitivity_assessment',
    'operational_need',
    'systems_and_recipients',
    'retention_and_disposal_inventory',
    'operator_instructions',
    'open_questions'
  ];
  field_name text;
  field_kind text;
  field_value text;
  character_position integer;
  character_code integer;
  total_length integer := 0;
  trim_characters constant text :=
    pg_catalog.chr(9) || pg_catalog.chr(10) ||
    pg_catalog.chr(11) || pg_catalog.chr(12) ||
    pg_catalog.chr(13) || pg_catalog.chr(28) ||
    pg_catalog.chr(29) || pg_catalog.chr(30) ||
    pg_catalog.chr(31) || pg_catalog.chr(32) ||
    pg_catalog.chr(133) || pg_catalog.chr(160) ||
    pg_catalog.chr(5760) || pg_catalog.chr(8192) ||
    pg_catalog.chr(8193) || pg_catalog.chr(8194) ||
    pg_catalog.chr(8195) || pg_catalog.chr(8196) ||
    pg_catalog.chr(8197) || pg_catalog.chr(8198) ||
    pg_catalog.chr(8199) || pg_catalog.chr(8200) ||
    pg_catalog.chr(8201) || pg_catalog.chr(8202) ||
    pg_catalog.chr(8232) || pg_catalog.chr(8233) ||
    pg_catalog.chr(8239) || pg_catalog.chr(8287) ||
    pg_catalog.chr(12288);
begin
  if pg_catalog.jsonb_typeof(payload) <> 'object'
     or not payload ?& expected_fields
     or payload
          - 'real_processing_agents'
          - 'operations_and_minimum_data'
          - 'data_sensitivity_assessment'
          - 'operational_need'
          - 'systems_and_recipients'
          - 'retention_and_disposal_inventory'
          - 'operator_instructions'
          - 'open_questions' <> '{}'::jsonb
  then
    return false;
  end if;

  foreach field_name in array expected_fields loop
    field_kind := pg_catalog.jsonb_typeof(payload -> field_name);
    if field_kind = 'null' then
      continue;
    end if;
    if field_kind <> 'string' then
      return false;
    end if;

    field_value := payload ->> field_name;
    if field_value = ''
       or field_value <> pg_catalog.btrim(field_value, trim_characters)
       or pg_catalog.char_length(field_value) > 4000
    then
      return false;
    end if;
    for character_position in 1..pg_catalog.char_length(field_value) loop
      character_code := pg_catalog.ascii(
        pg_catalog.substr(field_value, character_position, 1)
      );
      if character_code between 1 and 8
         or character_code between 11 and 31
         or character_code between 127 and 159
      then
        return false;
      end if;
    end loop;
    total_length := total_length + pg_catalog.char_length(field_value);
  end loop;

  return total_length <= 16000;
end
$function$;
    $ddl$;
    return;
  end if;

  select * into strict validator
    from pg_catalog.pg_proc
   where oid = validator_oid;
  if validator.pronamespace <> (
       select parent.relnamespace
         from pg_catalog.pg_class parent
        where parent.oid = 'public.igrejas'::regclass
     )
     or validator.proowner <> pg_catalog.to_regrole(current_user)
     or validator.prokind <> 'f'
     or validator.prolang <>
       (select language_row.oid from pg_catalog.pg_language language_row
         where language_row.lanname = 'plpgsql')
     or validator.prorettype <> 'boolean'::regtype
     or validator.pronargs <> 1
     or validator.proargtypes[0] <> 'jsonb'::regtype
     or validator.prosecdef
     or not validator.proisstrict
     or validator.provolatile <> 'i'
     or validator.proparallel <> 's'
     or validator.proconfig is distinct from
       array['search_path=pg_catalog']::text[]
     or validator.prosrc is distinct from expected_body
     or pg_catalog.obj_description(validator.oid, 'pg_proc') is distinct from
       'Validador puro e fechado do JSONB D2B2b3A; sem leitura de dados e sem EXECUTE para roles de aplicação.'
     or (
       select pg_catalog.array_agg(
         acl.privilege_type order by acl.privilege_type
       )
         from pg_catalog.aclexplode(
           coalesce(
             validator.proacl,
             pg_catalog.acldefault('f', validator.proowner)
           )
         ) acl
        where acl.grantee = validator.proowner
     ) is distinct from array['EXECUTE']::text[]
     or exists (
       select 1
         from pg_catalog.aclexplode(
           coalesce(
             validator.proacl,
             pg_catalog.acldefault('f', validator.proowner)
           )
         ) acl
        where acl.grantee <> validator.proowner
           or acl.grantor <> validator.proowner
           or acl.is_grantable
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2b3A guard: validator definition or ACL drifted',
      detail = pg_catalog.format(
        'namespace=%s owner=%s kind=%s lang=%s return=%s nargs=%s arg0=%s '
        'secdef=%s strict=%s volatile=%s parallel=%s config=%s body_md5=%s '
        'expected_md5=%s',
        validator.pronamespace = (
          select parent.relnamespace
            from pg_catalog.pg_class parent
           where parent.oid = 'public.igrejas'::regclass
        ),
        validator.proowner = pg_catalog.to_regrole(current_user),
        validator.prokind,
        validator.prolang = (
          select language_row.oid from pg_catalog.pg_language language_row
           where language_row.lanname = 'plpgsql'
        ),
        validator.prorettype = 'boolean'::regtype,
        validator.pronargs,
        validator.proargtypes[0] = 'jsonb'::regtype,
        validator.prosecdef,
        validator.proisstrict,
        validator.provolatile,
        validator.proparallel,
        validator.proconfig,
        pg_catalog.md5(validator.prosrc),
        pg_catalog.md5(expected_body)
      );
  end if;
end
$function_guard$;

create or replace function pg_temp.d2b2b3_key_columns(
  relation_oid oid,
  key_attnums smallint[]
)
returns text[]
language sql
stable
strict
set search_path = pg_catalog
as $columns$
  select coalesce(
    pg_catalog.array_agg(attribute.attname order by key_position.ordinality),
    array[]::text[]
  )
    from pg_catalog.unnest(key_attnums)
         with ordinality as key_position(attnum, ordinality)
    join pg_catalog.pg_attribute attribute
      on attribute.attrelid = relation_oid
     and attribute.attnum = key_position.attnum;
$columns$;

create or replace function pg_temp.d2b2b3_assert_envelope_contract(
  target_oid oid,
  require_security boolean,
  require_indexes boolean
)
returns void
language plpgsql
set search_path = pg_catalog
as $assertion$
declare
  target pg_catalog.pg_class%rowtype;
  parent_namespace oid;
  namespace_name text;
  actual_columns text[];
  actual_types text[];
  actual_not_null boolean[];
  actual_defaults text[];
  actual_identity text[];
  actual_generated text[];
  constraint_row pg_catalog.pg_constraint%rowtype;
  constraint_count integer := 0;
  constraint_hash text;
  expected_hash text;
  expected_type "char";
  expected_columns text[];
  expected_referenced_columns text[];
  expected_parent oid;
  expected_delete "char";
  index_contract record;
  index_count integer := 0;
  index_hash text;
  expected_index_hash text;
  expected_index_column text;
  expected_predicate text;
  expected_unique boolean;
  expected_primary boolean;
begin
  select * into strict target
    from pg_catalog.pg_class relation_row
   where relation_row.oid = target_oid;
  select parent.relnamespace into strict parent_namespace
    from pg_catalog.pg_class parent
   where parent.oid = 'public.igrejas'::regclass;
  select namespace_row.nspname into strict namespace_name
    from pg_catalog.pg_namespace namespace_row
   where namespace_row.oid = parent_namespace;

  if target.relkind <> 'r'
     or target.relpersistence <> 'p'
     or target.relnamespace <> parent_namespace
     or target.relowner <> pg_catalog.to_regrole(current_user)
     or not exists (
       select 1
         from pg_catalog.pg_roles owner_role
        where owner_role.rolname = pg_catalog.pg_get_userbyid(target.relowner)
          and (owner_role.rolsuper or owner_role.rolbypassrls)
     )
     or exists (
       select 1
         from pg_catalog.unnest(array[
           'anon', 'authenticated', 'service_role', 'agent_runtime'
         ]::text[]) role_name(name)
         join pg_catalog.pg_roles application_role
           on application_role.rolname = role_name.name
        where pg_catalog.pg_has_role(
          application_role.oid,
          target.relowner,
          'MEMBER'
        )
     )
     or target.relam <> (
       select access_method.oid from pg_catalog.pg_am access_method
        where access_method.amname = 'heap'
     )
  then
    raise exception 'D2B2b3A guard: relation identity drifted';
  end if;

  select
    pg_catalog.array_agg(attribute.attname order by attribute.attnum),
    pg_catalog.array_agg(
      pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
      order by attribute.attnum
    ),
    pg_catalog.array_agg(attribute.attnotnull order by attribute.attnum),
    pg_catalog.array_agg(
      coalesce(
        pg_temp.d2b2b3_normalize(
          pg_catalog.pg_get_expr(default_row.adbin, default_row.adrelid)
        ),
        ''
      ) order by attribute.attnum
    ),
    pg_catalog.array_agg(attribute.attidentity::text order by attribute.attnum),
    pg_catalog.array_agg(attribute.attgenerated::text order by attribute.attnum)
  into
    actual_columns,
    actual_types,
    actual_not_null,
    actual_defaults,
    actual_identity,
    actual_generated
  from pg_catalog.pg_attribute attribute
  left join pg_catalog.pg_attrdef default_row
    on default_row.adrelid = attribute.attrelid
   and default_row.adnum = attribute.attnum
  where attribute.attrelid = target_oid
    and attribute.attnum > 0
    and not attribute.attisdropped;

  if actual_columns is distinct from array[
       'id', 'igreja_id', 'schema_version', 'status', 'drafts',
       'draft_revisions', 'revision', 'created_by_app_user_id',
       'updated_by_app_user_id', 'created_at', 'updated_at'
     ]::text[]
     or actual_types is distinct from array[
       'uuid', 'uuid', 'text', 'text', 'jsonb', 'jsonb', 'bigint',
       'uuid', 'uuid', 'timestamp with time zone',
       'timestamp with time zone'
     ]::text[]
     or actual_not_null is distinct from array[
       true, true, true, true, true, true, true, false, false, true, true
     ]::boolean[]
     or actual_defaults is distinct from array[
       pg_temp.d2b2b3_normalize('gen_random_uuid()'),
       '',
       pg_temp.d2b2b3_normalize(
         '''d2b2b3a/governance-draft/v1''::text'
       ),
       pg_temp.d2b2b3_normalize('''DRAFT_NOT_APPROVED''::text'),
       '', '',
       pg_temp.d2b2b3_normalize('1'),
       '', '',
       pg_temp.d2b2b3_normalize('clock_timestamp()'),
       pg_temp.d2b2b3_normalize('clock_timestamp()')
     ]::text[]
     or actual_identity is distinct from array_fill(''::text, array[11])
     or actual_generated is distinct from array_fill(''::text, array[11])
  then
    raise exception 'D2B2b3A guard: column/default contract drifted';
  end if;

  for constraint_row in
    select * from pg_catalog.pg_constraint persisted_constraint
     where persisted_constraint.conrelid = target_oid
  loop
    constraint_count := constraint_count + 1;
    expected_referenced_columns := null;
    expected_parent := 0;
    expected_delete := ' ';
    case constraint_row.conname
      when 'purpose_consent_governance_envelope_pkey' then
        expected_type := 'p'; expected_columns := array['id'];
        expected_hash := '1d1603045c83dcedb4eae1d49a940e7e';
      when 'purpose_consent_governance_envelope_igreja_key' then
        expected_type := 'u'; expected_columns := array['igreja_id'];
        expected_hash := 'f1ab5bb5cdd700ad1fccbb4baf43ea42';
      when 'purpose_consent_governance_envelope_igreja_fkey' then
        expected_type := 'f'; expected_columns := array['igreja_id'];
        expected_referenced_columns := array['id'];
        expected_parent := 'public.igrejas'::regclass; expected_delete := 'c';
        expected_hash := '686aa6839fdf904f9ac0a932998e5041';
      when 'purpose_consent_governance_envelope_created_by_fkey' then
        expected_type := 'f'; expected_columns := array['created_by_app_user_id'];
        expected_referenced_columns := array['id'];
        expected_parent := 'public.app_users'::regclass; expected_delete := 'n';
        expected_hash := '7a790823eb21417ae8dbd832d5f42dfb';
      when 'purpose_consent_governance_envelope_updated_by_fkey' then
        expected_type := 'f'; expected_columns := array['updated_by_app_user_id'];
        expected_referenced_columns := array['id'];
        expected_parent := 'public.app_users'::regclass; expected_delete := 'n';
        expected_hash := 'c7cd9511c128969e314480605a14678f';
      when 'purpose_consent_governance_envelope_schema_version_check' then
        expected_type := 'c'; expected_columns := array['schema_version'];
        expected_hash := 'f8bfe986d6b42cc73948883bf056e0d1';
      when 'purpose_consent_governance_envelope_status_check' then
        expected_type := 'c'; expected_columns := array['status'];
        expected_hash := '6d708a1c11386189a1f59d78a04bc203';
      when 'purpose_consent_governance_envelope_revision_check' then
        expected_type := 'c'; expected_columns := array['revision'];
        expected_hash := '567275d0ec8259a8cfe7fe84bdd19241';
      when 'purpose_consent_governance_envelope_drafts_check' then
        expected_type := 'c'; expected_columns := array['drafts'];
        expected_hash := '04677b92eb0b1a99abed1b2c2541fab1';
      when 'purpose_consent_governance_envelope_draft_revisions_check' then
        expected_type := 'c'; expected_columns := array['draft_revisions'];
        expected_hash := 'd3cad7c04391b434e319e1cebb5cc4a4';
      else
        raise exception 'D2B2b3A guard: unexpected constraint %',
          constraint_row.conname;
    end case;

    constraint_hash := pg_catalog.md5(
      pg_catalog.replace(
        pg_temp.d2b2b3_normalize(
          pg_catalog.pg_get_constraintdef(constraint_row.oid)
        ),
        pg_catalog.lower(namespace_name) || '.',
        ''
      )
    );
    if constraint_row.contype <> expected_type
       or not constraint_row.convalidated
       or constraint_row.condeferrable
       or constraint_row.condeferred
       or constraint_row.conparentid <> 0
       or pg_temp.d2b2b3_key_columns(
         target_oid, constraint_row.conkey
       ) is distinct from expected_columns
       or constraint_hash <> expected_hash
    then
      raise exception 'D2B2b3A guard: constraint % drifted',
        constraint_row.conname;
    end if;

    if expected_type = 'f' and (
      constraint_row.confrelid <> expected_parent
      or pg_temp.d2b2b3_key_columns(
        constraint_row.confrelid, constraint_row.confkey
      ) is distinct from expected_referenced_columns
      or constraint_row.confupdtype <> 'a'
      or constraint_row.confdeltype <> expected_delete
      or constraint_row.confmatchtype <> 's'
    ) then
      raise exception 'D2B2b3A guard: foreign key % drifted',
        constraint_row.conname;
    end if;
  end loop;
  if constraint_count <> 10 then
    raise exception 'D2B2b3A guard: constraint cardinality drifted';
  end if;

  if require_indexes then
    for index_contract in
      select
        index_meta.*,
        index_row.oid as index_oid,
        index_row.relname as index_name,
        index_row.relnamespace as index_namespace,
        index_row.relowner as index_owner,
        access_method.amname as access_method_name,
        pg_catalog.pg_get_expr(
          index_meta.indpred, index_meta.indrelid
        ) as predicate
      from pg_catalog.pg_index index_meta
      join pg_catalog.pg_class index_row
        on index_row.oid = index_meta.indexrelid
      join pg_catalog.pg_am access_method
        on access_method.oid = index_row.relam
      where index_meta.indrelid = target_oid
    loop
      index_count := index_count + 1;
      case index_contract.index_name
        when 'purpose_consent_governance_envelope_pkey' then
          expected_index_column := 'id'; expected_predicate := null;
          expected_unique := true; expected_primary := true;
          expected_index_hash := '90815e867598eb9fc0203d2790da715f';
        when 'purpose_consent_governance_envelope_igreja_key' then
          expected_index_column := 'igreja_id'; expected_predicate := null;
          expected_unique := true; expected_primary := false;
          expected_index_hash := '72c3d60a961491fb509f9ba5f4b93822';
        when 'purpose_consent_governance_envelope_created_by_idx' then
          expected_index_column := 'created_by_app_user_id';
          expected_predicate := 'created_by_app_user_idISNOTNULL';
          expected_unique := false; expected_primary := false;
          expected_index_hash := '6ea17382a8282427132bae216f7562b7';
        when 'purpose_consent_governance_envelope_updated_by_idx' then
          expected_index_column := 'updated_by_app_user_id';
          expected_predicate := 'updated_by_app_user_idISNOTNULL';
          expected_unique := false; expected_primary := false;
          expected_index_hash := '0b999e1c6adc55ee13e4375b86d2a7b6';
        else
          raise exception 'D2B2b3A guard: unexpected index %',
            index_contract.index_name;
      end case;
      index_hash := pg_catalog.md5(
        pg_catalog.replace(
          pg_temp.d2b2b3_normalize(
            pg_catalog.pg_get_indexdef(index_contract.index_oid)
          ),
          pg_catalog.lower(namespace_name) || '.',
          ''
        )
      );
      if index_contract.index_namespace <> parent_namespace
         or index_contract.index_owner <> target.relowner
         or index_contract.access_method_name <> 'btree'
         or index_contract.indnkeyatts <> 1
         or index_contract.indnatts <> 1
         or index_contract.indexprs is not null
         or not index_contract.indisvalid
         or not index_contract.indisready
         or not index_contract.indislive
         or index_contract.indisunique <> expected_unique
         or index_contract.indisprimary <> expected_primary
         or not index_contract.indimmediate
         or index_contract.indisexclusion
         or index_contract.indnullsnotdistinct
         or pg_temp.d2b2b3_key_columns(
           target_oid, index_contract.indkey::smallint[]
         ) is distinct from array[expected_index_column]
         or pg_temp.d2b2b3_normalize(
           coalesce(index_contract.predicate, '')
         ) is distinct from coalesce(expected_predicate, '')
         or index_hash <> expected_index_hash
      then
        raise exception 'D2B2b3A guard: index % drifted',
          index_contract.index_name;
      end if;
    end loop;
    if index_count <> 4 then
      raise exception 'D2B2b3A guard: index cardinality drifted';
    end if;
  end if;

  if require_security and (
    not target.relrowsecurity
    or not target.relforcerowsecurity
    or exists (
      select 1 from pg_catalog.pg_policy policy_row
       where policy_row.polrelid = target_oid
    )
    or exists (
      select 1
        from pg_catalog.pg_attribute attribute
       where attribute.attrelid = target_oid
         and attribute.attnum > 0
         and not attribute.attisdropped
         and attribute.attacl is not null
    )
    or exists (
      select 1
        from pg_catalog.pg_trigger trigger_row
       where trigger_row.tgrelid = target_oid
         and not trigger_row.tgisinternal
    )
    or exists (
      select 1
        from pg_catalog.pg_rewrite rewrite_row
       where rewrite_row.ev_class = target_oid
    )
    or exists (
      select 1
        from pg_catalog.aclexplode(
          coalesce(
            target.relacl,
            pg_catalog.acldefault('r', target.relowner)
          )
        ) acl
       where acl.grantee <> target.relowner
          or acl.grantor <> target.relowner
          or acl.is_grantable
    )
    or (
      select pg_catalog.array_agg(
        acl.privilege_type order by acl.privilege_type
      )
        from pg_catalog.aclexplode(
          coalesce(
            target.relacl,
            pg_catalog.acldefault('r', target.relowner)
          )
        ) acl
       where acl.grantee = target.relowner
    ) is distinct from array[
      'DELETE', 'INSERT', 'MAINTAIN', 'REFERENCES', 'SELECT',
      'TRIGGER', 'TRUNCATE', 'UPDATE'
    ]::text[]
  ) then
    raise exception
      'D2B2b3A guard: RLS, policy, ACL, trigger or rule drifted';
  end if;

  if require_security and pg_catalog.obj_description(target_oid, 'pg_class')
       is distinct from
       'D2B2b3A draft-only: um envelope por igreja, quatro rascunhos operacionais; sem aprovação, digest, catálogo, writer, policy RLS ou autoridade de runtime.'
  then
    raise exception 'D2B2b3A guard: table comment drifted';
  end if;
end
$assertion$;

do $table_guard$
declare
  target_oid oid := pg_catalog.to_regclass(
    'public.purpose_consent_governance_envelope'
  );
  target pg_catalog.pg_class%rowtype;
begin
  if target_oid is null then
    create table public.purpose_consent_governance_envelope (
      id uuid not null default pg_catalog.gen_random_uuid(),
      igreja_id uuid not null,
      schema_version text not null
        default 'd2b2b3a/governance-draft/v1',
      status text not null default 'DRAFT_NOT_APPROVED',
      drafts jsonb not null,
      draft_revisions jsonb not null,
      revision bigint not null default 1,
      created_by_app_user_id uuid,
      updated_by_app_user_id uuid,
      created_at timestamptz not null default pg_catalog.clock_timestamp(),
      updated_at timestamptz not null default pg_catalog.clock_timestamp(),

      constraint purpose_consent_governance_envelope_pkey
        primary key (id),
      constraint purpose_consent_governance_envelope_igreja_key
        unique (igreja_id),
      constraint purpose_consent_governance_envelope_igreja_fkey
        foreign key (igreja_id)
        references public.igrejas (id) on delete cascade,
      constraint purpose_consent_governance_envelope_created_by_fkey
        foreign key (created_by_app_user_id)
        references public.app_users (id) on delete set null,
      constraint purpose_consent_governance_envelope_updated_by_fkey
        foreign key (updated_by_app_user_id)
        references public.app_users (id) on delete set null,
      constraint purpose_consent_governance_envelope_schema_version_check
        check (schema_version = 'd2b2b3a/governance-draft/v1'),
      constraint purpose_consent_governance_envelope_status_check
        check (status = 'DRAFT_NOT_APPROVED'),
      constraint purpose_consent_governance_envelope_revision_check
        check (revision >= 1),
      constraint purpose_consent_governance_envelope_drafts_check
        check (
          pg_catalog.jsonb_typeof(drafts) = 'object'
          and drafts ?& array[
            'atendimento_solicitado',
            'cuidado_pastoral',
            'tarefas_operacionais',
            'comunicados'
          ]::text[]
          and drafts
                - 'atendimento_solicitado'
                - 'cuidado_pastoral'
                - 'tarefas_operacionais'
                - 'comunicados' = '{}'::jsonb
          and public.purpose_consent_governance_draft_valid(
            drafts -> 'atendimento_solicitado'
          )
          and public.purpose_consent_governance_draft_valid(
            drafts -> 'cuidado_pastoral'
          )
          and public.purpose_consent_governance_draft_valid(
            drafts -> 'tarefas_operacionais'
          )
          and public.purpose_consent_governance_draft_valid(
            drafts -> 'comunicados'
          )
        ),
      constraint purpose_consent_governance_envelope_draft_revisions_check
        check (
          pg_catalog.jsonb_typeof(draft_revisions) = 'object'
          and draft_revisions ?& array[
            'atendimento_solicitado',
            'cuidado_pastoral',
            'tarefas_operacionais',
            'comunicados'
          ]::text[]
          and draft_revisions
                - 'atendimento_solicitado'
                - 'cuidado_pastoral'
                - 'tarefas_operacionais'
                - 'comunicados' = '{}'::jsonb
          and pg_catalog.jsonb_typeof(
            draft_revisions -> 'atendimento_solicitado'
          ) = 'number'
          and (draft_revisions ->> 'atendimento_solicitado')
                ~ '^[1-9][0-9]{0,17}$'
          and pg_catalog.jsonb_typeof(
            draft_revisions -> 'cuidado_pastoral'
          ) = 'number'
          and (draft_revisions ->> 'cuidado_pastoral')
                ~ '^[1-9][0-9]{0,17}$'
          and pg_catalog.jsonb_typeof(
            draft_revisions -> 'tarefas_operacionais'
          ) = 'number'
          and (draft_revisions ->> 'tarefas_operacionais')
                ~ '^[1-9][0-9]{0,17}$'
          and pg_catalog.jsonb_typeof(
            draft_revisions -> 'comunicados'
          ) = 'number'
          and (draft_revisions ->> 'comunicados')
                ~ '^[1-9][0-9]{0,17}$'
        )
    );
    target_oid := 'public.purpose_consent_governance_envelope'::regclass;
    perform pg_temp.d2b2b3_assert_envelope_contract(
      target_oid,
      false,
      false
    );
  else
    perform pg_temp.d2b2b3_assert_envelope_contract(
      target_oid,
      true,
      true
    );
  end if;
end
$table_guard$;

do $configure_new_contract$
declare
  role_name text;
  table_was_absent boolean;
begin
  select state.table_was_absent into strict table_was_absent
    from pg_temp.d2b2b3_migration_state state;
  if not table_was_absent then
    return;
  end if;

  if pg_catalog.to_regclass(
       'public.purpose_consent_governance_envelope_created_by_idx'
     ) is not null
     or pg_catalog.to_regclass(
       'public.purpose_consent_governance_envelope_updated_by_idx'
     ) is not null
  then
    raise exception using
      errcode = '42P07',
      message = 'D2B2b3A guard: homonymous actor index already exists';
  end if;

  create index purpose_consent_governance_envelope_created_by_idx
    on public.purpose_consent_governance_envelope (created_by_app_user_id)
    where created_by_app_user_id is not null;
  create index purpose_consent_governance_envelope_updated_by_idx
    on public.purpose_consent_governance_envelope (updated_by_app_user_id)
    where updated_by_app_user_id is not null;

  alter table public.purpose_consent_governance_envelope
    enable row level security;
  alter table public.purpose_consent_governance_envelope
    force row level security;

  revoke all privileges
    on table public.purpose_consent_governance_envelope from public;
  revoke all privileges
    on function public.purpose_consent_governance_draft_valid(jsonb) from public;

  foreach role_name in array array[
    'anon', 'authenticated', 'service_role', 'agent_runtime'
  ] loop
    if pg_catalog.to_regrole(role_name) is not null then
      execute pg_catalog.format(
        'revoke all privileges on table '
        'public.purpose_consent_governance_envelope from %I',
        role_name
      );
      execute pg_catalog.format(
        'revoke all privileges on function '
        'public.purpose_consent_governance_draft_valid(jsonb) from %I',
        role_name
      );
    end if;
  end loop;

  comment on table public.purpose_consent_governance_envelope is
    'D2B2b3A draft-only: um envelope por igreja, quatro rascunhos operacionais; sem aprovação, digest, catálogo, writer, policy RLS ou autoridade de runtime.';
  comment on function public.purpose_consent_governance_draft_valid(jsonb) is
    'Validador puro e fechado do JSONB D2B2b3A; sem leitura de dados e sem EXECUTE para roles de aplicação.';
end
$configure_new_contract$;

do $postconditions$
declare
  target_oid oid := 'public.purpose_consent_governance_envelope'::regclass;
  target pg_catalog.pg_class%rowtype;
  actual_columns text[];
  actual_types text[];
  actual_not_null boolean[];
  constraint_names text[];
  index_names text[];
  foreign_contract record;
  validator pg_catalog.pg_proc%rowtype;
  validator_owner oid;
begin
  perform pg_temp.d2b2b3_assert_envelope_contract(
    target_oid,
    true,
    true
  );
  select * into strict target
    from pg_catalog.pg_class
   where oid = target_oid;
  if target.relkind <> 'r'
     or not target.relrowsecurity
     or not target.relforcerowsecurity
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2b3A postcondition: RLS relation contract mismatch';
  end if;

  select
    pg_catalog.array_agg(attribute.attname order by attribute.attnum),
    pg_catalog.array_agg(
      pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
      order by attribute.attnum
    ),
    pg_catalog.array_agg(attribute.attnotnull order by attribute.attnum)
  into actual_columns, actual_types, actual_not_null
  from pg_catalog.pg_attribute attribute
  where attribute.attrelid = target_oid
    and attribute.attnum > 0
    and not attribute.attisdropped;

  if actual_columns is distinct from array[
       'id', 'igreja_id', 'schema_version', 'status', 'drafts',
       'draft_revisions', 'revision', 'created_by_app_user_id',
       'updated_by_app_user_id', 'created_at', 'updated_at'
     ]::text[]
     or actual_types is distinct from array[
       'uuid', 'uuid', 'text', 'text', 'jsonb', 'jsonb', 'bigint',
       'uuid', 'uuid', 'timestamp with time zone',
       'timestamp with time zone'
     ]::text[]
     or actual_not_null is distinct from array[
       true, true, true, true, true, true, true, false, false, true, true
     ]::boolean[]
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2b3A postcondition: column contract mismatch';
  end if;

  select pg_catalog.array_agg(constraint_row.conname order by constraint_row.conname)
    into constraint_names
    from pg_catalog.pg_constraint constraint_row
   where constraint_row.conrelid = target_oid;
  if constraint_names is distinct from array[
       'purpose_consent_governance_envelope_created_by_fkey',
       'purpose_consent_governance_envelope_draft_revisions_check',
       'purpose_consent_governance_envelope_drafts_check',
       'purpose_consent_governance_envelope_igreja_fkey',
       'purpose_consent_governance_envelope_igreja_key',
       'purpose_consent_governance_envelope_pkey',
       'purpose_consent_governance_envelope_revision_check',
       'purpose_consent_governance_envelope_schema_version_check',
       'purpose_consent_governance_envelope_status_check',
       'purpose_consent_governance_envelope_updated_by_fkey'
     ]::text[]
     or exists (
       select 1
         from pg_catalog.pg_constraint constraint_row
        where constraint_row.conrelid = target_oid
          and not constraint_row.convalidated
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2b3A postcondition: constraint contract mismatch';
  end if;

  for foreign_contract in
    select
      constraint_row.conname,
      constraint_row.confrelid,
      constraint_row.confdeltype
    from pg_catalog.pg_constraint constraint_row
    where constraint_row.conrelid = target_oid
      and constraint_row.contype = 'f'
  loop
    if foreign_contract.conname =
         'purpose_consent_governance_envelope_igreja_fkey'
       and (
         foreign_contract.confrelid <> 'public.igrejas'::regclass
         or foreign_contract.confdeltype <> 'c'
       )
    then
      raise exception 'D2B2b3A postcondition: igreja FK mismatch';
    elsif foreign_contract.conname in (
      'purpose_consent_governance_envelope_created_by_fkey',
      'purpose_consent_governance_envelope_updated_by_fkey'
    ) and (
      foreign_contract.confrelid <> 'public.app_users'::regclass
      or foreign_contract.confdeltype <> 'n'
    ) then
      raise exception 'D2B2b3A postcondition: actor FK mismatch';
    end if;
  end loop;

  select pg_catalog.array_agg(index_row.relname order by index_row.relname)
    into index_names
    from pg_catalog.pg_index index_meta
    join pg_catalog.pg_class index_row on index_row.oid = index_meta.indexrelid
   where index_meta.indrelid = target_oid
     and index_meta.indisvalid
     and index_meta.indisready
     and index_meta.indislive;
  if index_names is distinct from array[
       'purpose_consent_governance_envelope_created_by_idx',
       'purpose_consent_governance_envelope_igreja_key',
       'purpose_consent_governance_envelope_pkey',
       'purpose_consent_governance_envelope_updated_by_idx'
     ]::text[]
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2b3A postcondition: index contract mismatch';
  end if;

  if exists (
       select 1 from pg_catalog.pg_policy policy_row
        where policy_row.polrelid = target_oid
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2b3A postcondition: table must have zero RLS policies';
  end if;

  if exists (
       select 1
         from pg_catalog.aclexplode(
           coalesce(
             target.relacl,
             pg_catalog.acldefault('r', target.relowner)
           )
         ) acl
        where acl.grantee <> target.relowner
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2b3A postcondition: non-owner table ACL remains';
  end if;

  select * into strict validator
    from pg_catalog.pg_proc
   where oid =
     'public.purpose_consent_governance_draft_valid(jsonb)'::regprocedure;
  validator_owner := validator.proowner;
  if validator.prosecdef
     or validator.provolatile <> 'i'
     or validator.proparallel <> 's'
     or validator.prorettype <> 'boolean'::regtype
     or validator.pronargs <> 1
     or validator.proconfig is distinct from array['search_path=pg_catalog']::text[]
     or (
       select pg_catalog.array_agg(
         acl.privilege_type order by acl.privilege_type
       )
         from pg_catalog.aclexplode(
           coalesce(
             validator.proacl,
             pg_catalog.acldefault('f', validator_owner)
           )
         ) acl
        where acl.grantee = validator_owner
     ) is distinct from array['EXECUTE']::text[]
     or exists (
       select 1
         from pg_catalog.aclexplode(
           coalesce(
             validator.proacl,
             pg_catalog.acldefault('f', validator_owner)
           )
         ) acl
        where acl.grantee <> validator_owner
           or acl.grantor <> validator_owner
           or acl.is_grantable
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2b3A postcondition: validator contract mismatch';
  end if;
end
$postconditions$;

commit;
