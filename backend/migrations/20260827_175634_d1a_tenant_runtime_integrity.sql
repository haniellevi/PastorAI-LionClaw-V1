-- PastorAI D1A: integridade estrutural do runtime multi-tenant.
--
-- Objetivos:
--   * uma instance Evolution não pode resolver duas igrejas;
--   * relações críticas carregam igreja_id na própria FK;
--   * dados incompatíveis abortam antes de qualquer mudança, sem expor IDs;
--   * as FKs simples históricas permanecem para preservar SET NULL/CASCADE.
--
-- Esta migration não cria tabela, coluna ou função exposta e, portanto, não
-- amplia grants nem a Data API. Constraints e índices não possuem ACL própria.
-- Em falha de preflight, catálogo ou validação, a transação inteira reverte.
-- Em rollback do aplicativo, mantenha as constraints: elas são compatíveis com
-- os writers antigos. Remoção exige migration compensatória separada e auditada.

begin;

set transaction isolation level serializable;
set local search_path = pg_catalog, public;
set local lock_timeout = '5s';
set local statement_timeout = '120s';

-- Bloqueia writers durante preflight + DDL, eliminando a janela TOCTOU entre a
-- contagem sanitizada e a validação das constraints. lock_timeout faz a
-- migration falhar e liberar a transação em vez de aguardar indefinidamente;
-- statement_timeout limita também criação de índices e VALIDATE.
lock table
  public.pessoas,
  public.app_users,
  public.user_roles,
  public.conversations,
  public.messages,
  public.consent_records,
  public.whatsapp_connections
in share row exclusive mode;

do $preflight$
declare
  violations bigint;
begin
  select count(*) into violations
    from (
      select instance
        from public.whatsapp_connections
       where instance is not null
       group by instance
      having count(*) > 1
    ) duplicates;
  if violations > 0 then
    raise exception using
      errcode = '23505',
      message = 'D1A preflight: duplicate Evolution instances',
      detail = format('duplicate_groups=%s', violations);
  end if;

  select count(*) into violations
    from public.pessoas child
    left join public.pessoas parent on parent.id = child.lider_id
   where child.lider_id is not null
     and (
       parent.id is null
       or child.igreja_id is distinct from parent.igreja_id
     );
  if violations > 0 then
    raise exception using
      errcode = '23503',
      message = 'D1A preflight: pessoas.lider_id tenant mismatch',
      detail = format('rows=%s', violations);
  end if;

  select count(*) into violations
    from public.pessoas child
    left join public.app_users parent on parent.id = child.arquivada_por
   where child.arquivada_por is not null
     and (
       parent.id is null
       or child.igreja_id is distinct from parent.igreja_id
     );
  if violations > 0 then
    raise exception using
      errcode = '23503',
      message = 'D1A preflight: pessoas.arquivada_por tenant mismatch',
      detail = format('rows=%s', violations);
  end if;

  select count(*) into violations
    from public.app_users child
    left join public.pessoas parent on parent.id = child.pessoa_id
   where child.pessoa_id is not null
     and (
       parent.id is null
       or child.igreja_id is distinct from parent.igreja_id
     );
  if violations > 0 then
    raise exception using
      errcode = '23503',
      message = 'D1A preflight: app_users.pessoa_id tenant mismatch',
      detail = format('rows=%s', violations);
  end if;

  select count(*) into violations
    from public.user_roles child
    left join public.app_users parent on parent.id = child.user_id
   where parent.id is null
      or child.igreja_id is distinct from parent.igreja_id;
  if violations > 0 then
    raise exception using
      errcode = '23503',
      message = 'D1A preflight: user_roles.user_id tenant mismatch',
      detail = format('rows=%s', violations);
  end if;

  select count(*) into violations
    from public.conversations child
    left join public.pessoas parent on parent.id = child.pessoa_id
   where child.pessoa_id is not null
     and (
       parent.id is null
       or child.igreja_id is distinct from parent.igreja_id
     );
  if violations > 0 then
    raise exception using
      errcode = '23503',
      message = 'D1A preflight: conversations.pessoa_id tenant mismatch',
      detail = format('rows=%s', violations);
  end if;

  select count(*) into violations
    from public.conversations child
    left join public.app_users parent on parent.id = child.assumido_por
   where child.assumido_por is not null
     and (
       parent.id is null
       or child.igreja_id is distinct from parent.igreja_id
     );
  if violations > 0 then
    raise exception using
      errcode = '23503',
      message = 'D1A preflight: conversations.assumido_por tenant mismatch',
      detail = format('rows=%s', violations);
  end if;

  select count(*) into violations
    from public.messages child
    left join public.conversations parent on parent.id = child.conversation_id
   where parent.id is null
      or child.igreja_id is distinct from parent.igreja_id;
  if violations > 0 then
    raise exception using
      errcode = '23503',
      message = 'D1A preflight: messages.conversation_id tenant mismatch',
      detail = format('rows=%s', violations);
  end if;

  select count(*) into violations
    from public.messages child
    left join public.app_users parent on parent.id = child.enviado_por
   where child.enviado_por is not null
     and (
       parent.id is null
       or child.igreja_id is distinct from parent.igreja_id
     );
  if violations > 0 then
    raise exception using
      errcode = '23503',
      message = 'D1A preflight: messages.enviado_por tenant mismatch',
      detail = format('rows=%s', violations);
  end if;

  select count(*) into violations
    from public.consent_records child
    left join public.pessoas parent on parent.id = child.pessoa_id
   where parent.id is null
      or child.igreja_id is distinct from parent.igreja_id;
  if violations > 0 then
    raise exception using
      errcode = '23503',
      message = 'D1A preflight: consent_records.pessoa_id tenant mismatch',
      detail = format('rows=%s', violations);
  end if;

  select count(*) into violations
    from public.consent_records child
    left join public.app_users parent on parent.id = child.ator_id
   where child.ator_id is not null
     and (
       parent.id is null
       or child.igreja_id is distinct from parent.igreja_id
     );
  if violations > 0 then
    raise exception using
      errcode = '23503',
      message = 'D1A preflight: consent_records.ator_id tenant mismatch',
      detail = format('rows=%s', violations);
  end if;
end
$preflight$;

-- Retorna as colunas de uma constraint na ordem declarada. Vive apenas no
-- pg_temp da sessão que aplica a migration.
create or replace function pg_temp.d1a_constraint_columns(
  relation_oid oid,
  key_attnums smallint[]
)
returns text[]
language sql
stable
strict
as $function$
  select coalesce(array_agg(attribute.attname order by key_position.ordinality), array[]::text[])
    from unnest(key_attnums) with ordinality as key_position(attnum, ordinality)
    join pg_attribute attribute
      on attribute.attrelid = relation_oid
     and attribute.attnum = key_position.attnum;
$function$;

-- Cria uma constraint ausente e falha fechado se o mesmo nome já representar
-- outro contrato. Isto evita que idempotência esconda drift de catálogo.
create or replace function pg_temp.d1a_ensure_constraint(
  target_table regclass,
  target_name text,
  target_type "char",
  target_columns text[],
  referenced_table regclass,
  referenced_columns text[],
  ddl text
)
returns void
language plpgsql
as $function$
declare
  existing pg_constraint%rowtype;
begin
  select * into existing
    from pg_constraint
   where conrelid = target_table
     and conname = target_name;

  if not found then
    execute ddl;
    select * into strict existing
      from pg_constraint
     where conrelid = target_table
       and conname = target_name;
  end if;

  if existing.contype is distinct from target_type
     or existing.condeferrable
     or existing.condeferred
     or not existing.conislocal
     or existing.coninhcount <> 0
     or pg_temp.d1a_constraint_columns(existing.conrelid, existing.conkey)
        is distinct from target_columns
     or existing.confrelid is distinct from coalesce(referenced_table::oid, 0::oid)
     or (
       referenced_table is not null
       and pg_temp.d1a_constraint_columns(existing.confrelid, existing.confkey)
           is distinct from referenced_columns
     )
     or (
       target_type = 'f'
       and (
         existing.confdeltype <> 'a'
         or existing.confupdtype <> 'a'
         or existing.confmatchtype <> 's'
       )
     )
  then
    raise exception using
      errcode = 'P0001',
      message = format(
        'D1A catalog conflict: constraint %I on %s has an unexpected definition',
        target_name,
        target_table
      );
  end if;
end
$function$;

-- Índices usam a mesma disciplina fail-closed das constraints. IF NOT EXISTS
-- sozinho aceitaria silenciosamente um índice homônimo com outra definição.
create or replace function pg_temp.d1a_ensure_index(
  target_table regclass,
  target_name text,
  target_columns text[],
  target_unique boolean,
  target_predicate text,
  ddl text
)
returns void
language plpgsql
as $function$
declare
  index_oid oid;
  index_state pg_index%rowtype;
  index_method text;
  actual_predicate text;
  nondefault_key_options integer;
begin
  select index_relation.oid into index_oid
    from pg_class index_relation
   where index_relation.relname = target_name
     and index_relation.relnamespace = (
       select relnamespace from pg_class where oid = target_table
     );

  if not found then
    execute ddl;
    select index_relation.oid into strict index_oid
      from pg_class index_relation
     where index_relation.relname = target_name
       and index_relation.relnamespace = (
         select relnamespace from pg_class where oid = target_table
       );
  end if;

  select * into strict index_state
    from pg_index catalog_index
   where catalog_index.indexrelid = index_oid;

  select access_method.amname into strict index_method
    from pg_index catalog_index
    join pg_class index_relation
      on index_relation.oid = catalog_index.indexrelid
    join pg_am access_method
      on access_method.oid = index_relation.relam
   where catalog_index.indexrelid = index_oid;

  actual_predicate := coalesce(
    regexp_replace(
      lower(pg_get_expr(index_state.indpred, index_state.indrelid)),
      '[^a-z0-9_]',
      '',
      'g'
    ),
    ''
  );

  select count(*) into nondefault_key_options
    from unnest(index_state.indkey::smallint[]) with ordinality
           key_column(attnum, position)
    join unnest(index_state.indclass::oid[]) with ordinality
           operator_class(opclass_oid, position) using (position)
    join unnest(index_state.indcollation::oid[]) with ordinality
           key_collation(collation_oid, position) using (position)
    join unnest(index_state.indoption::smallint[]) with ordinality
           key_option(option_bits, position) using (position)
    join pg_attribute attribute
      on attribute.attrelid = index_state.indrelid
     and attribute.attnum = key_column.attnum
    join pg_opclass operator_class_catalog
      on operator_class_catalog.oid = operator_class.opclass_oid
   where key_column.position <= index_state.indnkeyatts
     and (
       key_option.option_bits <> 0
       or not operator_class_catalog.opcdefault
       or operator_class_catalog.opcmethod <> (
         select oid from pg_am where amname = 'btree'
       )
       or operator_class_catalog.opcintype <> attribute.atttypid
       or key_collation.collation_oid is distinct from attribute.attcollation
     );

  if index_state.indrelid is distinct from target_table::oid
     or index_method <> 'btree'
     or not index_state.indisvalid
     or not index_state.indisready
     or not index_state.indislive
     or index_state.indisunique is distinct from target_unique
     or index_state.indisprimary
     or index_state.indnkeyatts <> coalesce(array_length(target_columns, 1), 0)
     or index_state.indnatts <> coalesce(array_length(target_columns, 1), 0)
     or index_state.indexprs is not null
     or pg_temp.d1a_constraint_columns(
          index_state.indrelid,
          index_state.indkey::smallint[]
        ) is distinct from target_columns
     or actual_predicate is distinct from coalesce(target_predicate, '')
     or nondefault_key_options <> 0
  then
    raise exception using
      errcode = 'P0001',
      message = format(
        'D1A catalog conflict: index %I on %s has an unexpected definition',
        target_name,
        target_table
      );
  end if;
end
$function$;

do $constraints$
begin
  perform pg_temp.d1a_ensure_constraint(
    'public.pessoas'::regclass,
    'pessoas_igreja_id_id_key',
    'u',
    array['igreja_id', 'id'],
    null,
    null,
    'alter table public.pessoas add constraint pessoas_igreja_id_id_key unique (igreja_id, id)'
  );
  perform pg_temp.d1a_ensure_constraint(
    'public.app_users'::regclass,
    'app_users_igreja_id_id_key',
    'u',
    array['igreja_id', 'id'],
    null,
    null,
    'alter table public.app_users add constraint app_users_igreja_id_id_key unique (igreja_id, id)'
  );
  perform pg_temp.d1a_ensure_constraint(
    'public.conversations'::regclass,
    'conversations_igreja_id_id_key',
    'u',
    array['igreja_id', 'id'],
    null,
    null,
    'alter table public.conversations add constraint conversations_igreja_id_id_key unique (igreja_id, id)'
  );

  perform pg_temp.d1a_ensure_constraint(
    'public.pessoas'::regclass,
    'pessoas_tenant_lider_fkey',
    'f',
    array['igreja_id', 'lider_id'],
    'public.pessoas'::regclass,
    array['igreja_id', 'id'],
    'alter table public.pessoas add constraint pessoas_tenant_lider_fkey foreign key (igreja_id, lider_id) references public.pessoas (igreja_id, id) not valid'
  );
  perform pg_temp.d1a_ensure_constraint(
    'public.pessoas'::regclass,
    'pessoas_tenant_arquivada_por_fkey',
    'f',
    array['igreja_id', 'arquivada_por'],
    'public.app_users'::regclass,
    array['igreja_id', 'id'],
    'alter table public.pessoas add constraint pessoas_tenant_arquivada_por_fkey foreign key (igreja_id, arquivada_por) references public.app_users (igreja_id, id) not valid'
  );
  perform pg_temp.d1a_ensure_constraint(
    'public.app_users'::regclass,
    'app_users_tenant_pessoa_fkey',
    'f',
    array['igreja_id', 'pessoa_id'],
    'public.pessoas'::regclass,
    array['igreja_id', 'id'],
    'alter table public.app_users add constraint app_users_tenant_pessoa_fkey foreign key (igreja_id, pessoa_id) references public.pessoas (igreja_id, id) not valid'
  );
  perform pg_temp.d1a_ensure_constraint(
    'public.user_roles'::regclass,
    'user_roles_tenant_user_fkey',
    'f',
    array['igreja_id', 'user_id'],
    'public.app_users'::regclass,
    array['igreja_id', 'id'],
    'alter table public.user_roles add constraint user_roles_tenant_user_fkey foreign key (igreja_id, user_id) references public.app_users (igreja_id, id) not valid'
  );
  perform pg_temp.d1a_ensure_constraint(
    'public.conversations'::regclass,
    'conversations_tenant_pessoa_fkey',
    'f',
    array['igreja_id', 'pessoa_id'],
    'public.pessoas'::regclass,
    array['igreja_id', 'id'],
    'alter table public.conversations add constraint conversations_tenant_pessoa_fkey foreign key (igreja_id, pessoa_id) references public.pessoas (igreja_id, id) not valid'
  );
  perform pg_temp.d1a_ensure_constraint(
    'public.conversations'::regclass,
    'conversations_tenant_assumido_por_fkey',
    'f',
    array['igreja_id', 'assumido_por'],
    'public.app_users'::regclass,
    array['igreja_id', 'id'],
    'alter table public.conversations add constraint conversations_tenant_assumido_por_fkey foreign key (igreja_id, assumido_por) references public.app_users (igreja_id, id) not valid'
  );
  perform pg_temp.d1a_ensure_constraint(
    'public.messages'::regclass,
    'messages_tenant_conversation_fkey',
    'f',
    array['igreja_id', 'conversation_id'],
    'public.conversations'::regclass,
    array['igreja_id', 'id'],
    'alter table public.messages add constraint messages_tenant_conversation_fkey foreign key (igreja_id, conversation_id) references public.conversations (igreja_id, id) not valid'
  );
  perform pg_temp.d1a_ensure_constraint(
    'public.messages'::regclass,
    'messages_tenant_enviado_por_fkey',
    'f',
    array['igreja_id', 'enviado_por'],
    'public.app_users'::regclass,
    array['igreja_id', 'id'],
    'alter table public.messages add constraint messages_tenant_enviado_por_fkey foreign key (igreja_id, enviado_por) references public.app_users (igreja_id, id) not valid'
  );
  perform pg_temp.d1a_ensure_constraint(
    'public.consent_records'::regclass,
    'consent_records_tenant_pessoa_fkey',
    'f',
    array['igreja_id', 'pessoa_id'],
    'public.pessoas'::regclass,
    array['igreja_id', 'id'],
    'alter table public.consent_records add constraint consent_records_tenant_pessoa_fkey foreign key (igreja_id, pessoa_id) references public.pessoas (igreja_id, id) not valid'
  );
  perform pg_temp.d1a_ensure_constraint(
    'public.consent_records'::regclass,
    'consent_records_tenant_ator_fkey',
    'f',
    array['igreja_id', 'ator_id'],
    'public.app_users'::regclass,
    array['igreja_id', 'id'],
    'alter table public.consent_records add constraint consent_records_tenant_ator_fkey foreign key (igreja_id, ator_id) references public.app_users (igreja_id, id) not valid'
  );
end
$constraints$;

do $indexes$
begin
  perform pg_temp.d1a_ensure_index(
    'public.whatsapp_connections'::regclass,
    'whatsapp_connections_instance_uidx',
    array['instance'],
    true,
    'instanceisnotnull',
    'create unique index whatsapp_connections_instance_uidx on public.whatsapp_connections (instance) where instance is not null'
  );
  perform pg_temp.d1a_ensure_index(
    'public.pessoas'::regclass,
    'pessoas_igreja_id_lider_id_idx',
    array['igreja_id', 'lider_id'],
    false,
    'lider_idisnotnull',
    'create index pessoas_igreja_id_lider_id_idx on public.pessoas (igreja_id, lider_id) where lider_id is not null'
  );
  perform pg_temp.d1a_ensure_index(
    'public.pessoas'::regclass,
    'pessoas_igreja_id_arquivada_por_idx',
    array['igreja_id', 'arquivada_por'],
    false,
    'arquivada_porisnotnull',
    'create index pessoas_igreja_id_arquivada_por_idx on public.pessoas (igreja_id, arquivada_por) where arquivada_por is not null'
  );
  perform pg_temp.d1a_ensure_index(
    'public.app_users'::regclass,
    'app_users_igreja_id_pessoa_id_idx',
    array['igreja_id', 'pessoa_id'],
    false,
    'pessoa_idisnotnull',
    'create index app_users_igreja_id_pessoa_id_idx on public.app_users (igreja_id, pessoa_id) where pessoa_id is not null'
  );
  perform pg_temp.d1a_ensure_index(
    'public.user_roles'::regclass,
    'user_roles_igreja_id_user_id_idx',
    array['igreja_id', 'user_id'],
    false,
    '',
    'create index user_roles_igreja_id_user_id_idx on public.user_roles (igreja_id, user_id)'
  );
  perform pg_temp.d1a_ensure_index(
    'public.conversations'::regclass,
    'conversations_igreja_id_pessoa_id_idx',
    array['igreja_id', 'pessoa_id'],
    false,
    'pessoa_idisnotnull',
    'create index conversations_igreja_id_pessoa_id_idx on public.conversations (igreja_id, pessoa_id) where pessoa_id is not null'
  );
  perform pg_temp.d1a_ensure_index(
    'public.conversations'::regclass,
    'conversations_igreja_id_assumido_por_idx',
    array['igreja_id', 'assumido_por'],
    false,
    'assumido_porisnotnull',
    'create index conversations_igreja_id_assumido_por_idx on public.conversations (igreja_id, assumido_por) where assumido_por is not null'
  );
  perform pg_temp.d1a_ensure_index(
    'public.messages'::regclass,
    'messages_igreja_id_conversation_id_idx',
    array['igreja_id', 'conversation_id'],
    false,
    '',
    'create index messages_igreja_id_conversation_id_idx on public.messages (igreja_id, conversation_id)'
  );
  perform pg_temp.d1a_ensure_index(
    'public.messages'::regclass,
    'messages_igreja_id_enviado_por_idx',
    array['igreja_id', 'enviado_por'],
    false,
    'enviado_porisnotnull',
    'create index messages_igreja_id_enviado_por_idx on public.messages (igreja_id, enviado_por) where enviado_por is not null'
  );
  perform pg_temp.d1a_ensure_index(
    'public.consent_records'::regclass,
    'consent_records_igreja_id_pessoa_id_idx',
    array['igreja_id', 'pessoa_id'],
    false,
    '',
    'create index consent_records_igreja_id_pessoa_id_idx on public.consent_records (igreja_id, pessoa_id)'
  );
  perform pg_temp.d1a_ensure_index(
    'public.consent_records'::regclass,
    'consent_records_igreja_id_ator_id_idx',
    array['igreja_id', 'ator_id'],
    false,
    'ator_idisnotnull',
    'create index consent_records_igreja_id_ator_id_idx on public.consent_records (igreja_id, ator_id) where ator_id is not null'
  );
end
$indexes$;

alter table public.pessoas validate constraint pessoas_tenant_lider_fkey;
alter table public.pessoas validate constraint pessoas_tenant_arquivada_por_fkey;
alter table public.app_users validate constraint app_users_tenant_pessoa_fkey;
alter table public.user_roles validate constraint user_roles_tenant_user_fkey;
alter table public.conversations validate constraint conversations_tenant_pessoa_fkey;
alter table public.conversations validate constraint conversations_tenant_assumido_por_fkey;
alter table public.messages validate constraint messages_tenant_conversation_fkey;
alter table public.messages validate constraint messages_tenant_enviado_por_fkey;
alter table public.consent_records validate constraint consent_records_tenant_pessoa_fkey;
alter table public.consent_records validate constraint consent_records_tenant_ator_fkey;

do $postcondition$
declare
  invalid_constraints integer;
begin
  select count(*) into invalid_constraints
    from (values
      ('public.pessoas'::regclass, 'pessoas_tenant_lider_fkey'),
      ('public.pessoas'::regclass, 'pessoas_tenant_arquivada_por_fkey'),
      ('public.app_users'::regclass, 'app_users_tenant_pessoa_fkey'),
      ('public.user_roles'::regclass, 'user_roles_tenant_user_fkey'),
      ('public.conversations'::regclass, 'conversations_tenant_pessoa_fkey'),
      ('public.conversations'::regclass, 'conversations_tenant_assumido_por_fkey'),
      ('public.messages'::regclass, 'messages_tenant_conversation_fkey'),
      ('public.messages'::regclass, 'messages_tenant_enviado_por_fkey'),
      ('public.consent_records'::regclass, 'consent_records_tenant_pessoa_fkey'),
      ('public.consent_records'::regclass, 'consent_records_tenant_ator_fkey')
    ) expected(conrelid, conname)
    left join pg_constraint existing
      on existing.conrelid = expected.conrelid
     and existing.conname = expected.conname
   where existing.oid is null
      or not existing.convalidated;
  if invalid_constraints <> 0 then
    raise exception 'D1A postcondition: unvalidated tenant constraints';
  end if;

  if not exists (
    select 1
      from pg_index index_state
      join pg_class index_relation
        on index_relation.oid = index_state.indexrelid
     where index_relation.relname = 'whatsapp_connections_instance_uidx'
       and index_relation.relnamespace = (
         select relnamespace
           from pg_class
          where oid = 'public.whatsapp_connections'::regclass
       )
       and index_state.indrelid = 'public.whatsapp_connections'::regclass
       and index_state.indisunique
       and index_state.indisvalid
       and index_state.indnkeyatts = 1
       and pg_get_indexdef(index_state.indexrelid, 1, true) = 'instance'
       and regexp_replace(
         lower(pg_get_expr(index_state.indpred, index_state.indrelid)),
         '[^a-z_]',
         '',
         'g'
       ) = 'instanceisnotnull'
  ) then
    raise exception 'D1A postcondition: Evolution instance unique index drift';
  end if;
end
$postcondition$;

comment on index public.whatsapp_connections_instance_uidx is
  'D1A: uma instance Evolution resolve no máximo uma igreja; NULL permanece permitido.';

commit;
