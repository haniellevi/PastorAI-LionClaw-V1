-- PastorAI D2B2A: ledger oficial, append-only, de consentimento por finalidade.
--
-- Esta fatia e deliberadamente inativa. Ela cria somente o contrato de dados,
-- ACL e RLS. Nao faz backfill do consent_records legado, nao conecta runtime ou
-- worker e nao altera opt-out, flags, credenciais ou integracoes externas.
--
-- Rollback exige migration compensatoria. Antes do wiring, ela so pode remover
-- estes objetos depois de provar tabela vazia e ausencia de dependencias. Depois
-- do wiring, rollback do aplicativo deve preservar este ledger probatorio.

begin;

set transaction isolation level serializable;
set local search_path = pg_catalog;
set local lock_timeout = '5s';
set local statement_timeout = '120s';

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(
    '20260828_045213_d2b2_consentimento_finalidade_evento',
    0
  )
);

lock table public.igrejas, public.pessoas, public.app_users
  in share row exclusive mode;

do $preflight$
declare
  authenticated_role pg_catalog.pg_roles%rowtype;
  helper pg_catalog.pg_proc%rowtype;
  pessoas_key pg_catalog.pg_constraint%rowtype;
  app_users_key pg_catalog.pg_constraint%rowtype;
begin
  if pg_catalog.to_regrole('anon') is null
     or pg_catalog.to_regrole('authenticated') is null
     or pg_catalog.to_regrole('service_role') is null
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2A preflight: required Supabase roles are absent';
  end if;

  select * into strict authenticated_role
    from pg_catalog.pg_roles
   where rolname = 'authenticated';

  if authenticated_role.rolsuper
     or authenticated_role.rolbypassrls
     or pg_catalog.pg_has_role(
       pg_catalog.to_regrole('authenticated'),
       pg_catalog.to_regrole(current_user),
       'MEMBER'
     )
     or exists (
       select 1
         from pg_catalog.pg_roles privileged
        where (
          privileged.rolsuper
          or privileged.rolbypassrls
          or privileged.rolname in (
            'pg_read_all_data',
            'pg_write_all_data',
            'pg_maintain',
            'pg_database_owner'
          )
        )
          and pg_catalog.pg_has_role(
            pg_catalog.to_regrole('authenticated'),
            privileged.oid,
            'MEMBER'
          )
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2A preflight: authenticated can bypass the tenant boundary';
  end if;

  if pg_catalog.to_regclass('public.igrejas') is null
     or pg_catalog.to_regclass('public.pessoas') is null
     or pg_catalog.to_regclass('public.app_users') is null
  then
    raise exception using
      errcode = '42P01',
      message = 'D2B2A preflight: required parent tables are absent';
  end if;

  select * into pessoas_key
    from pg_catalog.pg_constraint
   where conrelid = 'public.pessoas'::pg_catalog.regclass
     and conname = 'pessoas_igreja_id_id_key'
     and contype = 'u'
     and convalidated;
  select * into app_users_key
    from pg_catalog.pg_constraint
   where conrelid = 'public.app_users'::pg_catalog.regclass
     and conname = 'app_users_igreja_id_id_key'
     and contype = 'u'
     and convalidated;
  if pessoas_key.oid is null or app_users_key.oid is null then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2A preflight: D1A tenant keys are absent';
  end if;

  if pg_catalog.to_regprocedure('public.current_igreja_id()') is null then
    raise exception using
      errcode = '42883',
      message = 'D2B2A preflight: public.current_igreja_id() is absent';
  end if;
  select * into strict helper
    from pg_catalog.pg_proc
   where oid = 'public.current_igreja_id()'::pg_catalog.regprocedure;
  if helper.pronargs <> 0
     or helper.prorettype <> 'pg_catalog.uuid'::pg_catalog.regtype
     or not helper.prosecdef
     or helper.provolatile <> 's'
     or not pg_catalog.has_function_privilege(
       'authenticated', helper.oid, 'EXECUTE'
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2A preflight: current_igreja_id has an incompatible contract';
  end if;
end
$preflight$;

create or replace function pg_temp.d2b2_constraint_columns(
  relation_oid oid,
  key_attnums smallint[]
)
returns text[]
language sql
stable
strict
set search_path = pg_catalog
as $function$
  select coalesce(
    array_agg(attribute.attname order by key_position.ordinality),
    array[]::text[]
  )
    from pg_catalog.unnest(key_attnums)
         with ordinality as key_position(attnum, ordinality)
    join pg_catalog.pg_attribute attribute
      on attribute.attrelid = relation_oid
     and attribute.attnum = key_position.attnum;
$function$;

create or replace function pg_temp.d2b2_normalize(value text)
returns text
language sql
immutable
strict
set search_path = pg_catalog
as $function$
  select pg_catalog.regexp_replace(
    pg_catalog.regexp_replace(
      pg_catalog.regexp_replace(
        pg_catalog.lower(value),
        '::(pg_catalog\\.)?(text|uuid)',
        '',
        'g'
      ),
      '[[:space:]()\"]',
      '',
      'g'
    ),
    'as(current_igreja_id|nullif)',
    '',
    'g'
  );
$function$;

do $table_guard$
declare
  target_oid oid := pg_catalog.to_regclass(
    'public.consentimento_finalidade_evento'
  );
  target pg_catalog.pg_class%rowtype;
  actual_columns text[];
  expected_columns constant text[] := array[
    'id', 'igreja_id', 'pessoa_id', 'finalidade', 'estado', 'versao_termo',
    'fonte', 'registrado_por_app_user_id', 'chave_idempotencia', 'sequencia',
    'registrado_em'
  ];
begin
  if target_oid is null then
    create table public.consentimento_finalidade_evento (
      id uuid not null default pg_catalog.gen_random_uuid(),
      igreja_id uuid not null,
      pessoa_id uuid not null,
      finalidade text not null,
      estado text not null,
      versao_termo text not null,
      fonte text not null,
      registrado_por_app_user_id uuid,
      chave_idempotencia text not null,
      sequencia bigint not null,
      registrado_em timestamptz not null default pg_catalog.clock_timestamp(),

      constraint consentimento_finalidade_evento_pkey primary key (id),
      constraint consentimento_finalidade_evento_igreja_fkey
        foreign key (igreja_id)
        references public.igrejas (id) on delete cascade,
      constraint consentimento_finalidade_evento_tenant_id_key
        unique (igreja_id, id),
      constraint consentimento_finalidade_evento_idempotencia_key
        unique (igreja_id, chave_idempotencia),
      constraint consentimento_finalidade_evento_stream_seq_key
        unique (igreja_id, pessoa_id, finalidade, sequencia),
      constraint consentimento_finalidade_evento_tenant_pessoa_fkey
        foreign key (igreja_id, pessoa_id)
        references public.pessoas (igreja_id, id) on delete cascade,
      constraint consentimento_finalidade_evento_registrado_por_fkey
        foreign key (registrado_por_app_user_id)
        references public.app_users (id) on delete set null,
      constraint consentimento_finalidade_evento_tenant_registrado_por_fkey
        foreign key (igreja_id, registrado_por_app_user_id)
        references public.app_users (igreja_id, id),
      constraint consentimento_finalidade_evento_finalidade_check
        check (finalidade in (
          'atendimento_solicitado', 'cuidado_pastoral',
          'tarefas_operacionais', 'comunicados'
        )),
      constraint consentimento_finalidade_evento_estado_check
        check (estado in ('concedido', 'retirado')),
      constraint consentimento_finalidade_evento_fonte_check
        check (fonte in ('whatsapp_inbound', 'painel_autenticado')),
      constraint consentimento_finalidade_evento_versao_termo_check
        check (
          versao_termo = pg_catalog.btrim(versao_termo)
          and pg_catalog.char_length(versao_termo) between 1 and 128
          and versao_termo !~ '[[:cntrl:]]'
        ),
      constraint consentimento_finalidade_evento_chave_idempotencia_check
        check (
          chave_idempotencia = pg_catalog.btrim(chave_idempotencia)
          and pg_catalog.char_length(chave_idempotencia) between 1 and 128
          and chave_idempotencia ~ '^[a-z0-9][a-z0-9:._-]{0,127}$'
        )
    );
    target_oid := pg_catalog.to_regclass(
      'public.consentimento_finalidade_evento'
    );

    create index consentimento_finalidade_evento_registrado_por_idx
      on public.consentimento_finalidade_evento
        (registrado_por_app_user_id, igreja_id)
      where registrado_por_app_user_id is not null;

    alter table public.consentimento_finalidade_evento
      enable row level security;
    alter table public.consentimento_finalidade_evento
      force row level security;

    revoke all privileges on table public.consentimento_finalidade_evento
      from public, anon, authenticated, service_role;
    if pg_catalog.to_regrole('agent_runtime') is not null then
      revoke all privileges on table public.consentimento_finalidade_evento
        from agent_runtime;
    end if;
    grant select on table public.consentimento_finalidade_evento
      to authenticated;
    grant insert (
      igreja_id, pessoa_id, finalidade, estado, versao_termo, fonte,
      registrado_por_app_user_id, chave_idempotencia
    ) on public.consentimento_finalidade_evento to authenticated;
  end if;

  select * into strict target
    from pg_catalog.pg_class
   where oid = target_oid;
  select pg_catalog.array_agg(attribute.attname order by attribute.attnum)
    into actual_columns
    from pg_catalog.pg_attribute attribute
   where attribute.attrelid = target_oid
     and attribute.attnum > 0
     and not attribute.attisdropped;

  if target.relkind <> 'r'
     or target.relpersistence <> 'p'
     or target.relispartition
     or not target.relrowsecurity
     or not target.relforcerowsecurity
     or actual_columns is distinct from expected_columns
     or pg_catalog.pg_has_role(
       pg_catalog.to_regrole('authenticated'), target.relowner, 'MEMBER'
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2A catalog conflict: target relation differs or is unsafe';
  end if;
end
$table_guard$;

do $function_guard$
declare
  prepare_oid oid := pg_catalog.to_regprocedure(
    'public.consentimento_finalidade_evento_prepare_insert()'
  );
  append_oid oid := pg_catalog.to_regprocedure(
    'public.consentimento_finalidade_evento_append_only()'
  );
begin
  if exists (
    select 1 from pg_catalog.pg_proc procedure
     where procedure.pronamespace = (
       select relation.relnamespace
         from pg_catalog.pg_class relation
        where relation.oid =
          'public.consentimento_finalidade_evento'::pg_catalog.regclass
     )
       and procedure.proname in (
         'consentimento_finalidade_evento_prepare_insert',
         'consentimento_finalidade_evento_append_only'
       )
       and procedure.pronargs <> 0
  ) then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2A catalog conflict: homonymous function overload';
  end if;

  if prepare_oid is null then
    create function public.consentimento_finalidade_evento_prepare_insert()
    returns trigger
    language plpgsql
    volatile
    security invoker
    set search_path = pg_catalog
    as $body$
    declare
      expected_sequence bigint;
    begin
      if (new.fonte = 'painel_autenticado'
          and new.registrado_por_app_user_id is null)
         or (new.fonte = 'whatsapp_inbound'
             and new.registrado_por_app_user_id is not null)
      then
        raise exception using
          errcode = '23514',
          message = 'D2B2A source and initial actor are inconsistent';
      end if;

      perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
          new.igreja_id::text || ':' || new.pessoa_id::text || ':' || new.finalidade,
          0
        )
      );
      select coalesce(max(evento.sequencia), 0) + 1
        into expected_sequence
        from public.consentimento_finalidade_evento evento
       where evento.igreja_id = new.igreja_id
         and evento.pessoa_id = new.pessoa_id
         and evento.finalidade = new.finalidade;
      if new.sequencia is null then
        new.sequencia := expected_sequence;
      elsif new.sequencia <> expected_sequence then
        raise exception using
          errcode = '23514',
          message = 'D2B2A sequence must be the next value in its tenant stream';
      end if;
      new.registrado_em := pg_catalog.clock_timestamp();
      return new;
    end
    $body$;
    revoke all privileges on function
      public.consentimento_finalidade_evento_prepare_insert()
      from public, anon, authenticated, service_role;
    if pg_catalog.to_regrole('agent_runtime') is not null then
      revoke all privileges on function
        public.consentimento_finalidade_evento_prepare_insert()
        from agent_runtime;
    end if;
  end if;

  if append_oid is null then
    create function public.consentimento_finalidade_evento_append_only()
    returns trigger
    language plpgsql
    volatile
    security invoker
    set search_path = pg_catalog
    as $body$
    begin
      if pg_catalog.pg_trigger_depth() > 1 then
        return case when tg_op = 'DELETE' then old else new end;
      end if;
      raise exception using
        errcode = '55000',
        message = 'D2B2A consent ledger is append-only';
    end
    $body$;
    revoke all privileges on function
      public.consentimento_finalidade_evento_append_only()
      from public, anon, authenticated, service_role;
    if pg_catalog.to_regrole('agent_runtime') is not null then
      revoke all privileges on function
        public.consentimento_finalidade_evento_append_only()
        from agent_runtime;
    end if;
  end if;
end
$function_guard$;

do $trigger_guard$
declare
  target_oid oid := 'public.consentimento_finalidade_evento'::pg_catalog.regclass;
begin
  if not exists (
    select 1 from pg_catalog.pg_trigger
     where tgrelid = target_oid
       and tgname = 'trg_consentimento_finalidade_evento_prepare_insert'
       and not tgisinternal
  ) then
    create trigger trg_consentimento_finalidade_evento_prepare_insert
      before insert on public.consentimento_finalidade_evento
      for each row execute function
        public.consentimento_finalidade_evento_prepare_insert();
  end if;
  if not exists (
    select 1 from pg_catalog.pg_trigger
     where tgrelid = target_oid
       and tgname = 'trg_consentimento_finalidade_evento_append_only'
       and not tgisinternal
  ) then
    create trigger trg_consentimento_finalidade_evento_append_only
      before update or delete on public.consentimento_finalidade_evento
      for each row execute function
        public.consentimento_finalidade_evento_append_only();
  end if;
end
$trigger_guard$;

do $policy_guard$
declare
  target_oid oid := 'public.consentimento_finalidade_evento'::pg_catalog.regclass;
begin
  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = target_oid
       and polname = 'consentimento_finalidade_evento_select_tenant'
  ) then
    create policy consentimento_finalidade_evento_select_tenant
      on public.consentimento_finalidade_evento
      as permissive for select to authenticated
      using (igreja_id = (select public.current_igreja_id()));
  end if;
  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = target_oid
       and polname = 'consentimento_finalidade_evento_insert_tenant'
  ) then
    create policy consentimento_finalidade_evento_insert_tenant
      on public.consentimento_finalidade_evento
      as permissive for insert to authenticated
      with check (igreja_id = (select public.current_igreja_id()));
  end if;
  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = target_oid
       and polname = 'consentimento_finalidade_evento_tenant_context_barrier'
  ) then
    create policy consentimento_finalidade_evento_tenant_context_barrier
      on public.consentimento_finalidade_evento
      as restrictive for all to public
      using (
        igreja_id = (
          select nullif(
            pg_catalog.current_setting('app.tenant_igreja_id', true), ''
          )::pg_catalog.uuid
        )
      )
      with check (
        igreja_id = (
          select nullif(
            pg_catalog.current_setting('app.tenant_igreja_id', true), ''
          )::pg_catalog.uuid
        )
      );
  end if;
end
$policy_guard$;

comment on table public.consentimento_finalidade_evento is
  'D2B2A: ledger oficial append-only de consentimento por finalidade; sem backfill ou wiring.';

-- Validacao fail-closed de colunas, constraints, indices, funcoes, triggers,
-- policies e ACL e executada abaixo antes do commit.

do $column_guard$
declare
  target_oid oid := 'public.consentimento_finalidade_evento'::pg_catalog.regclass;
  mismatches integer;
begin
  with expected(name, type_oid, required, has_default) as (
    values
      ('id', 'pg_catalog.uuid'::pg_catalog.regtype, true, true),
      ('igreja_id', 'pg_catalog.uuid'::pg_catalog.regtype, true, false),
      ('pessoa_id', 'pg_catalog.uuid'::pg_catalog.regtype, true, false),
      ('finalidade', 'pg_catalog.text'::pg_catalog.regtype, true, false),
      ('estado', 'pg_catalog.text'::pg_catalog.regtype, true, false),
      ('versao_termo', 'pg_catalog.text'::pg_catalog.regtype, true, false),
      ('fonte', 'pg_catalog.text'::pg_catalog.regtype, true, false),
      ('registrado_por_app_user_id', 'pg_catalog.uuid'::pg_catalog.regtype, false, false),
      ('chave_idempotencia', 'pg_catalog.text'::pg_catalog.regtype, true, false),
      ('sequencia', 'pg_catalog.int8'::pg_catalog.regtype, true, false),
      ('registrado_em', 'pg_catalog.timestamptz'::pg_catalog.regtype, true, true)
  )
  select count(*) into mismatches
    from expected
    left join pg_catalog.pg_attribute attribute
      on attribute.attrelid = target_oid
     and attribute.attname = expected.name
     and attribute.attnum > 0
     and not attribute.attisdropped
   where attribute.attnum is null
      or attribute.atttypid <> expected.type_oid
      or attribute.attnotnull is distinct from expected.required
      or attribute.atthasdef is distinct from expected.has_default
      or attribute.attgenerated <> ''
      or attribute.attidentity <> '';

  if mismatches <> 0 then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2A catalog conflict: column attributes differ';
  end if;

  if pg_temp.d2b2_normalize(
       pg_catalog.pg_get_expr(
         (select adbin from pg_catalog.pg_attrdef
           where adrelid = target_oid
             and adnum = (
               select attnum from pg_catalog.pg_attribute
                where attrelid = target_oid and attname = 'id'
             )),
         target_oid
       )
     ) not in ('gen_random_uuid', 'pg_catalog.gen_random_uuid')
     or pg_temp.d2b2_normalize(
       pg_catalog.pg_get_expr(
         (select adbin from pg_catalog.pg_attrdef
           where adrelid = target_oid
             and adnum = (
               select attnum from pg_catalog.pg_attribute
                where attrelid = target_oid and attname = 'registrado_em'
             )),
         target_oid
       )
     ) not in ('clock_timestamp', 'pg_catalog.clock_timestamp')
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2A catalog conflict: server defaults differ';
  end if;
end
$column_guard$;

create or replace function pg_temp.d2b2_assert_constraint(
  target_table regclass,
  target_name text,
  target_type "char",
  target_columns text[],
  referenced_table regclass,
  referenced_columns text[],
  delete_action "char"
)
returns void
language plpgsql
set search_path = pg_catalog
as $function$
declare
  existing pg_catalog.pg_constraint%rowtype;
begin
  select * into strict existing
    from pg_catalog.pg_constraint
   where conrelid = target_table
     and conname = target_name;

  if existing.contype <> target_type
     or existing.condeferrable
     or existing.condeferred
     or not existing.convalidated
     or not existing.conislocal
     or existing.coninhcount <> 0
     or pg_temp.d2b2_constraint_columns(existing.conrelid, existing.conkey)
        is distinct from target_columns
     or existing.confrelid <> coalesce(referenced_table::oid, 0::oid)
     or (
       referenced_table is not null
       and pg_temp.d2b2_constraint_columns(
         existing.confrelid, existing.confkey
       ) is distinct from referenced_columns
     )
     or (
       target_type = 'f'
       and (
         existing.confdeltype <> delete_action
         or existing.confupdtype <> 'a'
         or existing.confmatchtype <> 's'
       )
     )
  then
    raise exception using
      errcode = 'P0001',
      message = pg_catalog.format(
        'D2B2A catalog conflict: constraint %I differs', target_name
      );
  end if;
end
$function$;

do $constraint_guard$
declare
  target_oid regclass := 'public.consentimento_finalidade_evento'::regclass;
  check_row pg_catalog.pg_constraint%rowtype;
  normalized text;
begin
  if (
    select count(*) from pg_catalog.pg_constraint where conrelid = target_oid
  ) <> 13
     or exists (
       select 1 from pg_catalog.pg_constraint
        where conrelid = target_oid
          and conname not in (
            'consentimento_finalidade_evento_pkey',
            'consentimento_finalidade_evento_igreja_fkey',
            'consentimento_finalidade_evento_tenant_id_key',
            'consentimento_finalidade_evento_idempotencia_key',
            'consentimento_finalidade_evento_stream_seq_key',
            'consentimento_finalidade_evento_tenant_pessoa_fkey',
            'consentimento_finalidade_evento_registrado_por_fkey',
            'consentimento_finalidade_evento_tenant_registrado_por_fkey',
            'consentimento_finalidade_evento_finalidade_check',
            'consentimento_finalidade_evento_estado_check',
            'consentimento_finalidade_evento_fonte_check',
            'consentimento_finalidade_evento_versao_termo_check',
            'consentimento_finalidade_evento_chave_idempotencia_check'
          )
     )
  then
    raise exception 'D2B2A catalog conflict: unexpected constraints';
  end if;

  perform pg_temp.d2b2_assert_constraint(
    target_oid, 'consentimento_finalidade_evento_pkey', 'p', array['id'],
    null, null, null
  );
  perform pg_temp.d2b2_assert_constraint(
    target_oid, 'consentimento_finalidade_evento_tenant_id_key', 'u',
    array['igreja_id', 'id'], null, null, null
  );
  perform pg_temp.d2b2_assert_constraint(
    target_oid, 'consentimento_finalidade_evento_idempotencia_key', 'u',
    array['igreja_id', 'chave_idempotencia'], null, null, null
  );
  perform pg_temp.d2b2_assert_constraint(
    target_oid, 'consentimento_finalidade_evento_stream_seq_key', 'u',
    array['igreja_id', 'pessoa_id', 'finalidade', 'sequencia'],
    null, null, null
  );
  perform pg_temp.d2b2_assert_constraint(
    target_oid, 'consentimento_finalidade_evento_igreja_fkey', 'f',
    array['igreja_id'], 'public.igrejas'::regclass, array['id'], 'c'
  );
  perform pg_temp.d2b2_assert_constraint(
    target_oid, 'consentimento_finalidade_evento_tenant_pessoa_fkey', 'f',
    array['igreja_id', 'pessoa_id'], 'public.pessoas'::regclass,
    array['igreja_id', 'id'], 'c'
  );
  perform pg_temp.d2b2_assert_constraint(
    target_oid, 'consentimento_finalidade_evento_registrado_por_fkey', 'f',
    array['registrado_por_app_user_id'], 'public.app_users'::regclass,
    array['id'], 'n'
  );
  perform pg_temp.d2b2_assert_constraint(
    target_oid, 'consentimento_finalidade_evento_tenant_registrado_por_fkey', 'f',
    array['igreja_id', 'registrado_por_app_user_id'],
    'public.app_users'::regclass, array['igreja_id', 'id'], 'a'
  );

  select * into strict check_row from pg_catalog.pg_constraint
   where conrelid = target_oid
     and conname = 'consentimento_finalidade_evento_finalidade_check';
  normalized := pg_temp.d2b2_normalize(
    pg_catalog.pg_get_constraintdef(check_row.oid, true)
  );
  if normalized <>
     $$checkfinalidade=anyarray['atendimento_solicitado','cuidado_pastoral','tarefas_operacionais','comunicados']$$
  then raise exception 'D2B2A catalog conflict: finalidade CHECK'; end if;

  select * into strict check_row from pg_catalog.pg_constraint
   where conrelid = target_oid
     and conname = 'consentimento_finalidade_evento_estado_check';
  normalized := pg_temp.d2b2_normalize(
    pg_catalog.pg_get_constraintdef(check_row.oid, true)
  );
  if normalized <> $$checkestado=anyarray['concedido','retirado']$$
  then raise exception 'D2B2A catalog conflict: estado CHECK'; end if;

  select * into strict check_row from pg_catalog.pg_constraint
   where conrelid = target_oid
     and conname = 'consentimento_finalidade_evento_fonte_check';
  normalized := pg_temp.d2b2_normalize(
    pg_catalog.pg_get_constraintdef(check_row.oid, true)
  );
  if normalized <>
     $$checkfonte=anyarray['whatsapp_inbound','painel_autenticado']$$
  then raise exception 'D2B2A catalog conflict: fonte CHECK'; end if;

  select * into strict check_row from pg_catalog.pg_constraint
   where conrelid = target_oid
     and conname = 'consentimento_finalidade_evento_versao_termo_check';
  normalized := pg_temp.d2b2_normalize(
    pg_catalog.pg_get_constraintdef(check_row.oid, true)
  );
  if normalized <>
     $$checkversao_termo=btrimversao_termoandchar_lengthversao_termo>=1andchar_lengthversao_termo<=128andversao_termo!~'[[:cntrl:]]'$$
  then raise exception 'D2B2A catalog conflict: versao_termo CHECK'; end if;

  select * into strict check_row from pg_catalog.pg_constraint
   where conrelid = target_oid
     and conname = 'consentimento_finalidade_evento_chave_idempotencia_check';
  normalized := pg_temp.d2b2_normalize(
    pg_catalog.pg_get_constraintdef(check_row.oid, true)
  );
  if normalized <>
     $$checkchave_idempotencia=btrimchave_idempotenciaandchar_lengthchave_idempotencia>=1andchar_lengthchave_idempotencia<=128andchave_idempotencia~'^[a-z0-9][a-z0-9:._-]{0,127}$'$$
  then raise exception 'D2B2A catalog conflict: idempotency CHECK'; end if;
end
$constraint_guard$;

do $index_guard$
declare
  target_oid oid := 'public.consentimento_finalidade_evento'::regclass;
  actor_index pg_catalog.pg_index%rowtype;
begin
  if (
    select count(*) from pg_catalog.pg_index where indrelid = target_oid
  ) <> 5
     or exists (
       select 1
         from pg_catalog.pg_index catalog_index
         join pg_catalog.pg_class index_relation
           on index_relation.oid = catalog_index.indexrelid
        where catalog_index.indrelid = target_oid
          and index_relation.relname not in (
            'consentimento_finalidade_evento_pkey',
            'consentimento_finalidade_evento_tenant_id_key',
            'consentimento_finalidade_evento_idempotencia_key',
            'consentimento_finalidade_evento_stream_seq_key',
            'consentimento_finalidade_evento_registrado_por_idx'
          )
     )
  then raise exception 'D2B2A catalog conflict: unexpected indexes'; end if;

  select catalog_index.* into strict actor_index
    from pg_catalog.pg_index catalog_index
    join pg_catalog.pg_class index_relation
      on index_relation.oid = catalog_index.indexrelid
   where catalog_index.indrelid = target_oid
     and index_relation.relname =
       'consentimento_finalidade_evento_registrado_por_idx';
  if actor_index.indisunique
     or actor_index.indisprimary
     or actor_index.indnkeyatts <> 2
     or actor_index.indnatts <> 2
     or not actor_index.indisvalid
     or not actor_index.indisready
     or not actor_index.indislive
     or (
       select access_method.amname
         from pg_catalog.pg_class index_relation
         join pg_catalog.pg_am access_method
           on access_method.oid = index_relation.relam
        where index_relation.oid = actor_index.indexrelid
     ) <> 'btree'
     or actor_index.indexprs is not null
     or pg_temp.d2b2_constraint_columns(
       target_oid, actor_index.indkey::smallint[]
     ) is distinct from array['registrado_por_app_user_id', 'igreja_id']
     or pg_temp.d2b2_normalize(
       pg_catalog.pg_get_expr(actor_index.indpred, target_oid)
     ) <> 'registrado_por_app_user_idisnotnull'
  then raise exception 'D2B2A catalog conflict: operator index'; end if;
end
$index_guard$;

do $function_contract_guard$
declare
  prepare_oid oid := 'public.consentimento_finalidade_evento_prepare_insert()'::regprocedure;
  append_oid oid := 'public.consentimento_finalidade_evento_append_only()'::regprocedure;
  procedure pg_catalog.pg_proc%rowtype;
  expected_prepare constant text := $source$
declare
  expected_sequence bigint;
begin
  if (new.fonte = 'painel_autenticado'
      and new.registrado_por_app_user_id is null)
     or (new.fonte = 'whatsapp_inbound'
         and new.registrado_por_app_user_id is not null)
  then
    raise exception using
      errcode = '23514',
      message = 'D2B2A source and initial actor are inconsistent';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      new.igreja_id::text || ':' || new.pessoa_id::text || ':' || new.finalidade,
      0
    )
  );
  select coalesce(max(evento.sequencia), 0) + 1
    into expected_sequence
    from public.consentimento_finalidade_evento evento
   where evento.igreja_id = new.igreja_id
     and evento.pessoa_id = new.pessoa_id
     and evento.finalidade = new.finalidade;
  if new.sequencia is null then
    new.sequencia := expected_sequence;
  elsif new.sequencia <> expected_sequence then
    raise exception using
      errcode = '23514',
      message = 'D2B2A sequence must be the next value in its tenant stream';
  end if;
  new.registrado_em := pg_catalog.clock_timestamp();
  return new;
end
  $source$;
  expected_append constant text := $source$
begin
  if pg_catalog.pg_trigger_depth() > 1 then
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  raise exception using
    errcode = '55000',
    message = 'D2B2A consent ledger is append-only';
end
  $source$;
begin
  if (
    select count(*) from pg_catalog.pg_proc
     where pronamespace = (
       select relation.relnamespace
         from pg_catalog.pg_class relation
        where relation.oid =
          'public.consentimento_finalidade_evento'::pg_catalog.regclass
     )
       and proname in (
         'consentimento_finalidade_evento_prepare_insert',
         'consentimento_finalidade_evento_append_only'
       )
  ) <> 2 then
    raise exception 'D2B2A catalog conflict: trigger function count';
  end if;

  select * into strict procedure from pg_catalog.pg_proc where oid = prepare_oid;
  if procedure.prorettype <> 'trigger'::regtype
     or procedure.pronargs <> 0
     or procedure.prolang <> (
       select oid from pg_catalog.pg_language where lanname = 'plpgsql'
     )
     or procedure.provolatile <> 'v'
     or procedure.prosecdef
     or procedure.proleakproof
     or procedure.proowner <> (
       select relowner from pg_catalog.pg_class
        where oid = 'public.consentimento_finalidade_evento'::regclass
     )
     or procedure.proconfig is distinct from array['search_path=pg_catalog']
     or pg_catalog.regexp_replace(
       procedure.prosrc, '[[:space:]]+', '', 'g'
     ) <> pg_catalog.regexp_replace(
       expected_prepare, '[[:space:]]+', '', 'g'
     )
  then raise exception 'D2B2A catalog conflict: prepare function'; end if;

  select * into strict procedure from pg_catalog.pg_proc where oid = append_oid;
  if procedure.prorettype <> 'trigger'::regtype
     or procedure.pronargs <> 0
     or procedure.prolang <> (
       select oid from pg_catalog.pg_language where lanname = 'plpgsql'
     )
     or procedure.provolatile <> 'v'
     or procedure.prosecdef
     or procedure.proleakproof
     or procedure.proowner <> (
       select relowner from pg_catalog.pg_class
        where oid = 'public.consentimento_finalidade_evento'::regclass
     )
     or procedure.proconfig is distinct from array['search_path=pg_catalog']
     or pg_catalog.regexp_replace(
       procedure.prosrc, '[[:space:]]+', '', 'g'
     ) <> pg_catalog.regexp_replace(
       expected_append, '[[:space:]]+', '', 'g'
     )
  then raise exception 'D2B2A catalog conflict: append function'; end if;

  if exists (
    select 1
      from pg_catalog.pg_proc candidate
      cross join lateral pg_catalog.aclexplode(
        coalesce(
          candidate.proacl,
          pg_catalog.acldefault('f', candidate.proowner)
        )
      ) acl
     where candidate.oid in (prepare_oid, append_oid)
       and not (
         acl.grantee = candidate.proowner
         and acl.privilege_type = 'EXECUTE'
         and not acl.is_grantable
       )
  ) then
    raise exception 'D2B2A catalog conflict: trigger function ACL';
  end if;
end
$function_contract_guard$;

do $trigger_contract_guard$
declare
  target_oid oid := 'public.consentimento_finalidade_evento'::regclass;
  trigger_row pg_catalog.pg_trigger%rowtype;
begin
  if (
    select count(*) from pg_catalog.pg_trigger
     where tgrelid = target_oid and not tgisinternal
  ) <> 2 then
    raise exception 'D2B2A catalog conflict: unexpected user trigger';
  end if;

  select * into strict trigger_row from pg_catalog.pg_trigger
   where tgrelid = target_oid
     and tgname = 'trg_consentimento_finalidade_evento_prepare_insert'
     and not tgisinternal;
  if trigger_row.tgfoid <>
       'public.consentimento_finalidade_evento_prepare_insert()'::regprocedure
     or trigger_row.tgtype <> 7
     or trigger_row.tgenabled <> 'O'
     or trigger_row.tgconstraint <> 0
     or trigger_row.tgnargs <> 0
  then raise exception 'D2B2A catalog conflict: prepare trigger'; end if;

  select * into strict trigger_row from pg_catalog.pg_trigger
   where tgrelid = target_oid
     and tgname = 'trg_consentimento_finalidade_evento_append_only'
     and not tgisinternal;
  if trigger_row.tgfoid <>
       'public.consentimento_finalidade_evento_append_only()'::regprocedure
     or trigger_row.tgtype <> 27
     or trigger_row.tgenabled <> 'O'
     or trigger_row.tgconstraint <> 0
     or trigger_row.tgnargs <> 0
  then raise exception 'D2B2A catalog conflict: append trigger'; end if;
end
$trigger_contract_guard$;

do $policy_contract_guard$
declare
  target_oid oid := 'public.consentimento_finalidade_evento'::regclass;
  authenticated_oid oid := pg_catalog.to_regrole('authenticated')::oid;
  policy_row pg_catalog.pg_policy%rowtype;
  normalized text;
begin
  if (
    select count(*) from pg_catalog.pg_policy where polrelid = target_oid
  ) <> 3 then
    raise exception 'D2B2A catalog conflict: unexpected RLS policy';
  end if;

  select * into strict policy_row from pg_catalog.pg_policy
   where polrelid = target_oid
     and polname = 'consentimento_finalidade_evento_select_tenant';
  normalized := pg_temp.d2b2_normalize(
    pg_catalog.pg_get_expr(policy_row.polqual, target_oid)
  );
  if not policy_row.polpermissive
     or policy_row.polcmd <> 'r'
     or policy_row.polroles is distinct from array[authenticated_oid]
     or policy_row.polwithcheck is not null
     or normalized <> 'igreja_id=selectpublic.current_igreja_id'
  then raise exception 'D2B2A catalog conflict: SELECT policy'; end if;

  select * into strict policy_row from pg_catalog.pg_policy
   where polrelid = target_oid
     and polname = 'consentimento_finalidade_evento_insert_tenant';
  normalized := pg_temp.d2b2_normalize(
    pg_catalog.pg_get_expr(policy_row.polwithcheck, target_oid)
  );
  if not policy_row.polpermissive
     or policy_row.polcmd <> 'a'
     or policy_row.polroles is distinct from array[authenticated_oid]
     or policy_row.polqual is not null
     or normalized <> 'igreja_id=selectpublic.current_igreja_id'
  then raise exception 'D2B2A catalog conflict: INSERT policy'; end if;

  select * into strict policy_row from pg_catalog.pg_policy
   where polrelid = target_oid
     and polname = 'consentimento_finalidade_evento_tenant_context_barrier';
  normalized := pg_temp.d2b2_normalize(
    pg_catalog.pg_get_expr(policy_row.polqual, target_oid)
  );
  if policy_row.polpermissive
     or policy_row.polcmd <> '*'
     or policy_row.polroles is distinct from array[0::oid]
     or normalized <>
       $$igreja_id=selectnullifcurrent_setting'app.tenant_igreja_id',true,''$$
     or pg_temp.d2b2_normalize(
       pg_catalog.pg_get_expr(policy_row.polwithcheck, target_oid)
     ) <> normalized
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2A catalog conflict: restrictive GUC policy',
      detail = normalized;
  end if;
end
$policy_contract_guard$;

do $acl_guard$
declare
  target_oid oid := 'public.consentimento_finalidade_evento'::regclass;
  target pg_catalog.pg_class%rowtype;
  authenticated_oid oid := pg_catalog.to_regrole('authenticated')::oid;
  allowed_insert_columns constant text[] := array[
    'igreja_id', 'pessoa_id', 'finalidade', 'estado', 'versao_termo', 'fonte',
    'registrado_por_app_user_id', 'chave_idempotencia'
  ];
  all_columns constant text[] := array[
    'id', 'igreja_id', 'pessoa_id', 'finalidade', 'estado', 'versao_termo',
    'fonte', 'registrado_por_app_user_id', 'chave_idempotencia', 'sequencia',
    'registrado_em'
  ];
  role_name text;
  column_name text;
begin
  select * into strict target from pg_catalog.pg_class where oid = target_oid;

  if not pg_catalog.has_table_privilege('authenticated', target_oid, 'SELECT')
     or pg_catalog.has_table_privilege(
       'authenticated', target_oid,
       'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN'
     )
  then raise exception 'D2B2A catalog conflict: authenticated table ACL'; end if;

  foreach column_name in array all_columns loop
    if pg_catalog.has_column_privilege(
         'authenticated', target_oid, column_name, 'INSERT'
       ) is distinct from (column_name = any(allowed_insert_columns))
       or pg_catalog.has_column_privilege(
         'authenticated', target_oid, column_name, 'UPDATE,REFERENCES'
       )
    then raise exception 'D2B2A catalog conflict: authenticated column ACL'; end if;
  end loop;

  foreach role_name in array array['anon', 'service_role'] loop
    if pg_catalog.has_table_privilege(
         role_name, target_oid,
         'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN'
       )
       or pg_catalog.has_any_column_privilege(
         role_name, target_oid, 'SELECT,INSERT,UPDATE,REFERENCES'
       )
    then raise exception 'D2B2A catalog conflict: denied role has ACL'; end if;
  end loop;

  if pg_catalog.to_regrole('agent_runtime') is not null
     and (
       pg_catalog.has_table_privilege(
         'agent_runtime', target_oid,
         'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN'
       )
       or pg_catalog.has_any_column_privilege(
         'agent_runtime', target_oid, 'SELECT,INSERT,UPDATE,REFERENCES'
       )
     )
  then raise exception 'D2B2A catalog conflict: agent_runtime has ACL'; end if;

  if exists (
    select 1
      from pg_catalog.aclexplode(
        coalesce(target.relacl, pg_catalog.acldefault('r', target.relowner))
      ) acl
     where not (
       acl.grantee = target.relowner
       or (
         acl.grantee = authenticated_oid
         and acl.privilege_type = 'SELECT'
         and not acl.is_grantable
       )
     )
  ) or exists (
    select 1
      from pg_catalog.pg_attribute attribute
      cross join lateral pg_catalog.aclexplode(attribute.attacl) acl
     where attribute.attrelid = target_oid
       and attribute.attnum > 0
       and not attribute.attisdropped
       and not (
         acl.grantee = target.relowner
         or (
           acl.grantee = authenticated_oid
           and acl.privilege_type = 'INSERT'
           and not acl.is_grantable
           and attribute.attname = any(allowed_insert_columns)
         )
       )
  ) then raise exception 'D2B2A catalog conflict: unexpected ACL grantee'; end if;
end
$acl_guard$;

do $postconditions$
declare
  target pg_catalog.pg_class%rowtype;
begin
  select * into strict target
    from pg_catalog.pg_class
   where oid = 'public.consentimento_finalidade_evento'::regclass;
  if not target.relrowsecurity
     or not target.relforcerowsecurity
     or (select count(*) from pg_catalog.pg_policy where polrelid = target.oid) <> 3
     or (
       select count(*) from pg_catalog.pg_trigger
        where tgrelid = target.oid and not tgisinternal
     ) <> 2
  then
    raise exception using
      errcode = 'P0001',
      message = 'D2B2A postcondition: ledger boundary is incomplete';
  end if;
end
$postconditions$;

commit;
