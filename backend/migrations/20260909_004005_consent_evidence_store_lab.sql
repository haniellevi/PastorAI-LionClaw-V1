-- PASTORAI_MIGRATION_INTENT_V1={"affected_relations":["public.consentimento_desafio","public.consentimento_evidencia","public.consentimento_recibo"],"artifact_id":"migration-authoring-intent-v1","base_repository_sha":"2ae100c30ed29cac32c3fd14e09a3f6002b8c2df","cross_tenant_test_nodeids":["backend/tests/test_consent_evidence_store_pg17.py::test_evidence_store_pg17_role_and_guc_fail_closed","backend/tests/test_consent_evidence_store_pg17.py::test_evidence_store_pg17_cross_tenant_fk_and_dml_isolation","backend/tests/test_consent_evidence_store_pg17.py::test_evidence_store_pg17_person_cascade_preserves_tenant_boundaries","backend/tests/test_consent_evidence_store_canonical_pg17.py::test_canonical_pg17_person_cascade_two_tenants","backend/tests/test_consent_evidence_store_canonical_pg17.py::test_historical_pg17_person_cascade_preserves_two_tenants_and_ledger"],"decision_refs":["docs/decisions/2026-09-09-consent-evidence-store-lab.md"],"global_justification":null,"migration_basename":"20260909_004005_consent_evidence_store_lab.sql","next_stage_authorized":false,"operational_authorization":false,"pg17_test_nodeids":["backend/tests/test_consent_evidence_store_pg17.py::test_evidence_store_pg17_migration_and_acl_contract","backend/tests/test_consent_evidence_store_pg17.py::test_evidence_store_pg17_role_and_guc_fail_closed","backend/tests/test_consent_evidence_store_pg17.py::test_evidence_store_pg17_cross_tenant_fk_and_dml_isolation","backend/tests/test_consent_evidence_store_pg17.py::test_evidence_store_pg17_event_constraints_and_receipt_binding","backend/tests/test_consent_evidence_store_pg17.py::test_evidence_store_pg17_person_cascade_preserves_tenant_boundaries","backend/tests/test_consent_evidence_store_pg17.py::test_evidence_store_pg17_same_challenge_different_keys_one_fresh_one_conflict","backend/tests/test_consent_evidence_store_pg17.py::test_evidence_store_pg17_concurrent_same_intent_has_one_winner","backend/tests/test_consent_evidence_store_pg17.py::test_evidence_store_pg17_rollback_and_reconnect_replay_are_not_success","backend/tests/test_consent_evidence_store_pg17.py::test_evidence_store_pg17_restart_reconnect_keeps_committed_receipt","backend/tests/test_consent_evidence_store_canonical_pg17.py::test_canonical_pg17_uow_commit_and_readonly_observation","backend/tests/test_consent_evidence_store_canonical_pg17.py::test_canonical_pg17_uow_rollback_and_ambiguous_commit","backend/tests/test_consent_evidence_store_canonical_pg17.py::test_canonical_pg17_uow_concurrent_replay","backend/tests/test_consent_evidence_store_canonical_pg17.py::test_canonical_pg17_person_cascade_two_tenants","backend/tests/test_consent_evidence_store_canonical_pg17.py::test_canonical_pg17_historical_ledger_writer_remains_permission_denied","backend/tests/test_consent_evidence_store_canonical_pg17.py::test_historical_pg17_refusal_before_withdrawal_barrier","backend/tests/test_consent_evidence_store_canonical_pg17.py::test_historical_pg17_withdrawal_before_refusal_barrier","backend/tests/test_consent_evidence_store_canonical_pg17.py::test_historical_pg17_person_cascade_preserves_two_tenants_and_ledger","backend/tests/test_consent_evidence_store_canonical_pg17.py::test_historical_pg17_concurrent_delete_new_challenge_cascades_chain","backend/tests/test_consent_evidence_store_canonical_pg17.py::test_historical_pg17_concurrent_delete_existing_challenge_cascades_chain"],"recovery":{"kind":"FORWARD_COMPENSATION","reference":"docs/decisions/2026-09-09-consent-evidence-store-lab.md"},"scope":"TENANT","tenant_controls":{"acl_review":"EXPLICIT_GRANTS_AND_REVOKES","enable_rls":true,"force_rls":true,"igreja_id_column":"igreja_id","policy_context":"app.tenant_igreja_id"}}
-- OPERATIONAL_AUTHORIZATION=BLOCKED
-- NEXT_STAGE_AUTHORIZED=false
-- ==========================================================================
-- PastorAI evidence store (E1/E3 laboratory candidate).
--
-- This migration owns exactly three new tenant relations.  It deliberately
-- does not alter or write the existing purpose-consent ledger.  The migration
-- is source-only until a separately authorized catalog/replay/application
-- gate; it must never be run against a shared environment by hand.
--
-- The first writer slice persists PRESENTATION and REFUSE_INITIAL only.  A
-- future writer must still prove the source, actor, session and eligibility;
-- these tables do not grant consent merely because an insert is possible.
-- ==========================================================================

begin;

set transaction isolation level serializable;
set local search_path = pg_catalog;
set local lock_timeout = '5s';
set local statement_timeout = '120s';

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(
    '20260908_175522_consent_evidence_store_lab',
    0
  )
);

do $preflight$
declare
  authenticated_role pg_catalog.pg_roles%rowtype;
begin
  if pg_catalog.to_regrole('anon') is null
     or pg_catalog.to_regrole('authenticated') is null
     or pg_catalog.to_regrole('service_role') is null
  then
    raise exception using
      errcode = 'P0001',
      message = 'consent evidence preflight: required roles are absent';
  end if;

  select * into strict authenticated_role
    from pg_catalog.pg_roles
   where rolname = 'authenticated';
  if authenticated_role.rolsuper
     or authenticated_role.rolbypassrls
     or exists (
       select 1 from pg_catalog.pg_roles dangerous_role
        where (dangerous_role.rolsuper or dangerous_role.rolbypassrls
          or dangerous_role.rolname in (
          'pg_read_all_data', 'pg_write_all_data', 'service_role',
          'pg_database_owner', 'pg_maintain'
        ))
          and pg_catalog.pg_has_role(
            authenticated_role.oid, dangerous_role.oid, 'MEMBER'
          )
     )
     or pg_catalog.pg_has_role(
       pg_catalog.to_regrole('authenticated'),
       pg_catalog.to_regrole(current_user),
       'MEMBER'
     )
  then
    raise exception using
      errcode = 'P0001',
      message = 'consent evidence preflight: authenticated can bypass RLS';
  end if;

  if pg_catalog.to_regclass('public.igrejas') is null
     or pg_catalog.to_regclass('public.pessoas') is null
  then
    raise exception using
      errcode = '42P01',
      message = 'consent evidence preflight: required parent tables are absent';
  end if;

  if pg_catalog.to_regclass('public.consentimento_desafio') is not null
     or pg_catalog.to_regclass('public.consentimento_evidencia') is not null
     or pg_catalog.to_regclass('public.consentimento_recibo') is not null
  then
    raise exception using
      errcode = '42P07',
      message = 'consent evidence preflight: target relation already exists';
  end if;

  if pg_catalog.to_regprocedure(
       'public.consentimento_desafio_validate_write()'
     ) is not null
     or pg_catalog.to_regprocedure(
       'public.consentimento_evidencia_validate_insert()'
     ) is not null
     or pg_catalog.to_regprocedure(
       'public.consentimento_evidencia_append_only()'
     ) is not null
     or pg_catalog.to_regprocedure(
       'public.consentimento_recibo_validate_insert()'
     ) is not null
     or pg_catalog.to_regprocedure(
       'public.consentimento_recibo_append_only()'
     ) is not null
  then
    raise exception using
      errcode = '42710',
      message = 'consent evidence preflight: trigger function already exists';
  end if;

  if not exists (
    select 1
      from pg_catalog.pg_constraint
     where conrelid = 'public.pessoas'::pg_catalog.regclass
       and conname = 'pessoas_igreja_id_id_key'
       and contype = 'u'
       and convalidated
       and pg_catalog.pg_get_constraintdef(oid, true) =
           'UNIQUE (igreja_id, id)'
  ) then
    raise exception using
      errcode = 'P0001',
      message = 'consent evidence preflight: Pessoa tenant key is absent';
  end if;
end
$preflight$;

create table public.consentimento_desafio (
  id uuid not null default pg_catalog.gen_random_uuid(),
  igreja_id uuid not null,
  pessoa_id uuid not null,
  finalidade text not null,
  package_id uuid not null,
  package_version text not null,
  content_digest text not null,
  catalog_entry_digest text not null,
  notice_text_digest text not null,
  binding_id uuid not null,
  interaction_id uuid not null,
  canal text not null,
  idioma text not null,
  criado_em timestamptz not null default pg_catalog.clock_timestamp(),
  expira_em timestamptz not null,
  estado text not null default 'OPEN',
  encerrado_em timestamptz,

  constraint consentimento_desafio_pkey primary key (id),
  constraint consentimento_desafio_igreja_fkey
    foreign key (igreja_id)
    references public.igrejas (id)
    on delete cascade,
  constraint consentimento_desafio_tenant_id_key
    unique (igreja_id, id),
  constraint consentimento_desafio_tenant_pessoa_fkey
    foreign key (igreja_id, pessoa_id)
    references public.pessoas (igreja_id, id)
    on delete cascade,
  constraint consentimento_desafio_interaction_key
    unique (igreja_id, binding_id, interaction_id),
  constraint consentimento_desafio_finalidade_check
    check (
      finalidade in (
        'atendimento_solicitado', 'cuidado_pastoral',
        'tarefas_operacionais', 'comunicados'
      )
    ),
  constraint consentimento_desafio_package_version_check
    check (
      package_version = pg_catalog.btrim(package_version)
      and pg_catalog.char_length(package_version) between 1 and 128
      and package_version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
    ),
  constraint consentimento_desafio_content_digest_check
    check (content_digest ~ '^[0-9a-f]{64}$'),
  constraint consentimento_desafio_catalog_entry_digest_check
    check (catalog_entry_digest ~ '^[0-9a-f]{64}$'),
  constraint consentimento_desafio_notice_text_digest_check
    check (notice_text_digest ~ '^[0-9a-f]{64}$'),
  constraint consentimento_desafio_canal_check
    check (canal in ('WHATSAPP', 'PANEL')),
  constraint consentimento_desafio_idioma_check
    check (idioma = 'pt-BR'),
  constraint consentimento_desafio_expiracao_check
    check (
      expira_em > criado_em
      and expira_em <= criado_em + pg_catalog.make_interval(mins => 30)
    ),
  constraint consentimento_desafio_estado_check
    check (estado in ('OPEN', 'CONSUMED', 'EXPIRED', 'CANCELLED')),
  constraint consentimento_desafio_encerramento_check
    check (
      (estado = 'OPEN' and encerrado_em is null)
      or (
        estado = 'CONSUMED'
        and encerrado_em >= criado_em
        and encerrado_em <= expira_em
      )
      or (estado = 'EXPIRED' and encerrado_em >= expira_em)
      or (estado = 'CANCELLED' and encerrado_em >= criado_em)
    )
);

create table public.consentimento_evidencia (
  id uuid not null default pg_catalog.gen_random_uuid(),
  igreja_id uuid not null,
  desafio_id uuid not null,
  tipo text not null,
  apresentacao_id uuid,
  acao text,
  chave_idempotencia text not null,
  registrado_em timestamptz not null default pg_catalog.clock_timestamp(),
  evidence_digest text not null,

  constraint consentimento_evidencia_pkey primary key (id),
  constraint consentimento_evidencia_tenant_id_key
    unique (igreja_id, id),
  constraint consentimento_evidencia_desafio_fkey
    foreign key (igreja_id, desafio_id)
    references public.consentimento_desafio (igreja_id, id)
    on delete cascade,
  constraint consentimento_evidencia_desafio_tipo_key
    unique (igreja_id, desafio_id, tipo),
  constraint consentimento_evidencia_desafio_id_key
    unique (igreja_id, desafio_id, id),
  constraint consentimento_evidencia_apresentacao_fkey
    foreign key (igreja_id, desafio_id, apresentacao_id)
    references public.consentimento_evidencia (
      igreja_id, desafio_id, id
    )
    on delete cascade,
  constraint consentimento_evidencia_idempotencia_key
    unique (igreja_id, chave_idempotencia),
  constraint consentimento_evidencia_tipo_check
    check (tipo in ('PRESENTATION', 'MANIFESTATION')),
  constraint consentimento_evidencia_acao_check
    check (acao is null or acao = 'REFUSE_INITIAL'),
  constraint consentimento_evidencia_shape_check
    check (
      (
        tipo = 'PRESENTATION'
        and apresentacao_id is null
        and acao is null
      )
      or (
        tipo = 'MANIFESTATION'
        and apresentacao_id is not null
        and acao = 'REFUSE_INITIAL'
      )
    ),
  constraint consentimento_evidencia_digest_check
    check (evidence_digest ~ '^[0-9a-f]{64}$'),
  constraint consentimento_evidencia_key_check
    check (
      chave_idempotencia = pg_catalog.btrim(chave_idempotencia)
      and pg_catalog.char_length(chave_idempotencia) = 70
      and chave_idempotencia ~ '^ce:v1:[0-9a-f]{64}$'
    )
);

create table public.consentimento_recibo (
  id uuid not null default pg_catalog.gen_random_uuid(),
  igreja_id uuid not null,
  evidencia_id uuid not null,
  chave_idempotencia text not null,
  registrado_em timestamptz not null,
  acao text not null,
  schema_version text not null,

  constraint consentimento_recibo_pkey primary key (id),
  constraint consentimento_recibo_tenant_id_key
    unique (igreja_id, id),
  constraint consentimento_recibo_evidencia_fkey
    foreign key (igreja_id, evidencia_id)
    references public.consentimento_evidencia (igreja_id, id)
    on delete cascade,
  constraint consentimento_recibo_evidencia_key
    unique (igreja_id, evidencia_id),
  constraint consentimento_recibo_idempotencia_key
    unique (igreja_id, chave_idempotencia),
  constraint consentimento_recibo_key_check
    check (
      chave_idempotencia = pg_catalog.btrim(chave_idempotencia)
      and pg_catalog.char_length(chave_idempotencia) = 70
      and chave_idempotencia ~ '^ce:v1:[0-9a-f]{64}$'
    ),
  constraint consentimento_recibo_acao_check
    check (acao = 'REFUSE_INITIAL'),
  constraint consentimento_recibo_schema_version_check
    check (schema_version = 'consent-receipt/lab-v1')
);

create index consentimento_desafio_tenant_pessoa_idx
  on public.consentimento_desafio (igreja_id, pessoa_id);
create index consentimento_evidencia_tenant_desafio_apresentacao_idx
  on public.consentimento_evidencia (
    igreja_id, desafio_id, apresentacao_id
  );

do $function_guard$
begin
  if pg_catalog.to_regprocedure(
       'public.consentimento_desafio_validate_write()'
     ) is null
  then
    create function public.consentimento_desafio_validate_write()
    returns trigger
    language plpgsql
    volatile
    security invoker
    set search_path = pg_catalog
    as $body$
    begin
      if tg_op = 'INSERT' then
        if new.estado <> 'OPEN' or new.encerrado_em is not null then
          raise exception using
            errcode = '23514',
            message = 'consent challenge must start OPEN';
        end if;
        return new;
      end if;

      if new.id is distinct from old.id
         or new.igreja_id is distinct from old.igreja_id
         or new.pessoa_id is distinct from old.pessoa_id
         or new.finalidade is distinct from old.finalidade
         or new.package_id is distinct from old.package_id
         or new.package_version is distinct from old.package_version
         or new.content_digest is distinct from old.content_digest
         or new.catalog_entry_digest is distinct from old.catalog_entry_digest
         or new.notice_text_digest is distinct from old.notice_text_digest
         or new.binding_id is distinct from old.binding_id
         or new.interaction_id is distinct from old.interaction_id
         or new.canal is distinct from old.canal
         or new.idioma is distinct from old.idioma
         or new.criado_em is distinct from old.criado_em
         or new.expira_em is distinct from old.expira_em
      then
        raise exception using
          errcode = '55000',
          message = 'consent challenge content is immutable';
      end if;

      if old.estado <> 'OPEN'
         or old.encerrado_em is not null
         or new.estado not in ('CONSUMED', 'EXPIRED', 'CANCELLED')
         or new.encerrado_em is null
         or new.encerrado_em < new.criado_em
         or (
           new.estado = 'CONSUMED'
           and new.encerrado_em > new.expira_em
         )
         or (
           new.estado = 'EXPIRED'
           and new.encerrado_em < new.expira_em
         )
      then
        raise exception using
          errcode = '55000',
          message = 'consent challenge transition is invalid';
      end if;
      return new;
    end
    $body$;
  end if;

  if pg_catalog.to_regprocedure(
       'public.consentimento_evidencia_validate_insert()'
     ) is null
  then
    create function public.consentimento_evidencia_validate_insert()
    returns trigger
    language plpgsql
    volatile
    security invoker
    set search_path = pg_catalog
    as $body$
    declare
      challenge public.consentimento_desafio%rowtype;
      presentation public.consentimento_evidencia%rowtype;
    begin
      select * into challenge
        from public.consentimento_desafio
       where igreja_id = new.igreja_id
         and id = new.desafio_id
       for update;
      if not found
         or challenge.estado <> 'OPEN'
         or new.registrado_em < challenge.criado_em
         or new.registrado_em >= challenge.expira_em
      then
        raise exception using
          errcode = '23514',
          message = 'evidence timestamp or challenge state is invalid';
      end if;
      if new.tipo = 'PRESENTATION' then
        if new.apresentacao_id is not null or new.acao is not null then
          raise exception using
            errcode = '23514',
            message = 'presentation cannot carry an action';
        end if;
      elsif new.tipo = 'MANIFESTATION' then
        if new.apresentacao_id is null or new.acao <> 'REFUSE_INITIAL' then
          raise exception using
            errcode = '23514',
            message = 'manifestation must be REFUSE_INITIAL';
        end if;
        select * into presentation
          from public.consentimento_evidencia presentation_row
         where presentation_row.igreja_id = new.igreja_id
           and presentation_row.desafio_id = new.desafio_id
           and presentation_row.id = new.apresentacao_id
           and presentation_row.tipo = 'PRESENTATION';
        if not found or new.registrado_em < presentation.registrado_em then
          raise exception using
            errcode = '23503',
            message = 'manifestation presentation does not match challenge';
        end if;
      end if;
      return new;
    end
    $body$;
  end if;

  if pg_catalog.to_regprocedure(
       'public.consentimento_recibo_validate_insert()'
     ) is null
  then
    create function public.consentimento_recibo_validate_insert()
    returns trigger
    language plpgsql
    volatile
    security invoker
    set search_path = pg_catalog
    as $body$
    declare
      manifestation public.consentimento_evidencia%rowtype;
    begin
      select * into manifestation
        from public.consentimento_evidencia evidence
       where evidence.igreja_id = new.igreja_id
         and evidence.id = new.evidencia_id;
      if not found
         or manifestation.tipo <> 'MANIFESTATION'
         or new.acao is distinct from manifestation.acao
         or new.chave_idempotencia is distinct from manifestation.chave_idempotencia
         or new.registrado_em is distinct from manifestation.registrado_em
      then
        raise exception using
          errcode = '23514',
          message = 'receipt does not exactly match manifestation';
      end if;
      return new;
    end
    $body$;
  end if;

  if pg_catalog.to_regprocedure(
       'public.consentimento_evidencia_append_only()'
     ) is null
  then
    create function public.consentimento_evidencia_append_only()
    returns trigger
    language plpgsql
    volatile
    security invoker
    set search_path = pg_catalog
    as $body$
    begin
      if tg_op = 'DELETE' and pg_catalog.pg_trigger_depth() > 1 then
        return old;
      end if;
      raise exception using
        errcode = '55000',
        message = 'consent evidence is append-only';
    end
    $body$;
  end if;

  if pg_catalog.to_regprocedure(
       'public.consentimento_recibo_append_only()'
     ) is null
  then
    create function public.consentimento_recibo_append_only()
    returns trigger
    language plpgsql
    volatile
    security invoker
    set search_path = pg_catalog
    as $body$
    begin
      if tg_op = 'DELETE' and pg_catalog.pg_trigger_depth() > 1 then
        return old;
      end if;
      raise exception using
        errcode = '55000',
        message = 'consent receipt is append-only';
    end
    $body$;
  end if;
end
$function_guard$;

do $trigger_guard$
begin
  if not exists (
    select 1 from pg_catalog.pg_trigger
     where tgrelid = 'public.consentimento_desafio'::pg_catalog.regclass
       and tgname = 'trg_consentimento_desafio_validate_write'
       and not tgisinternal
  ) then
    create trigger trg_consentimento_desafio_validate_write
      before insert or update on public.consentimento_desafio
      for each row execute function
        public.consentimento_desafio_validate_write();
  end if;

  if not exists (
    select 1 from pg_catalog.pg_trigger
     where tgrelid = 'public.consentimento_evidencia'::pg_catalog.regclass
       and tgname = 'trg_consentimento_evidencia_validate_insert'
       and not tgisinternal
  ) then
    create trigger trg_consentimento_evidencia_validate_insert
      before insert on public.consentimento_evidencia
      for each row execute function
        public.consentimento_evidencia_validate_insert();
  end if;

  if not exists (
    select 1 from pg_catalog.pg_trigger
     where tgrelid = 'public.consentimento_evidencia'::pg_catalog.regclass
       and tgname = 'trg_consentimento_evidencia_append_only'
       and not tgisinternal
  ) then
    create trigger trg_consentimento_evidencia_append_only
      before update or delete on public.consentimento_evidencia
      for each row execute function
        public.consentimento_evidencia_append_only();
  end if;

  if not exists (
    select 1 from pg_catalog.pg_trigger
     where tgrelid = 'public.consentimento_recibo'::pg_catalog.regclass
       and tgname = 'trg_consentimento_recibo_validate_insert'
       and not tgisinternal
  ) then
    create trigger trg_consentimento_recibo_validate_insert
      before insert on public.consentimento_recibo
      for each row execute function
        public.consentimento_recibo_validate_insert();
  end if;

  if not exists (
    select 1 from pg_catalog.pg_trigger
     where tgrelid = 'public.consentimento_recibo'::pg_catalog.regclass
       and tgname = 'trg_consentimento_recibo_append_only'
       and not tgisinternal
  ) then
    create trigger trg_consentimento_recibo_append_only
      before update or delete on public.consentimento_recibo
      for each row execute function
        public.consentimento_recibo_append_only();
  end if;
end
$trigger_guard$;

alter table public.consentimento_desafio enable row level security;
alter table public.consentimento_desafio force row level security;
alter table public.consentimento_evidencia enable row level security;
alter table public.consentimento_evidencia force row level security;
alter table public.consentimento_recibo enable row level security;
alter table public.consentimento_recibo force row level security;

revoke all privileges on table public.consentimento_desafio
  from public, anon, authenticated, service_role;
revoke all privileges on table public.consentimento_evidencia
  from public, anon, authenticated, service_role;
revoke all privileges on table public.consentimento_recibo
  from public, anon, authenticated, service_role;
do $agent_acl$
begin
  if pg_catalog.to_regrole('agent_runtime') is not null then
    revoke all privileges on table public.consentimento_desafio from agent_runtime;
    revoke all privileges on table public.consentimento_evidencia from agent_runtime;
    revoke all privileges on table public.consentimento_recibo from agent_runtime;
  end if;
end
$agent_acl$;

grant select (
  id, igreja_id, pessoa_id, finalidade, package_id, package_version,
  content_digest, catalog_entry_digest, notice_text_digest, binding_id,
  interaction_id, canal, idioma, criado_em, expira_em, estado, encerrado_em
) on table public.consentimento_desafio to authenticated;
grant insert (
  id, igreja_id, pessoa_id, finalidade, package_id, package_version,
  content_digest, catalog_entry_digest, notice_text_digest, binding_id,
  interaction_id, canal, idioma, criado_em, expira_em, estado, encerrado_em
) on table public.consentimento_desafio to authenticated;
grant update (estado, encerrado_em)
  on table public.consentimento_desafio to authenticated;

grant select (
  id, igreja_id, desafio_id, tipo, apresentacao_id, acao,
  chave_idempotencia, registrado_em, evidence_digest
) on table public.consentimento_evidencia to authenticated;
grant insert (
  id, igreja_id, desafio_id, tipo, apresentacao_id, acao,
  chave_idempotencia, registrado_em, evidence_digest
) on table public.consentimento_evidencia to authenticated;

grant select (
  id, igreja_id, evidencia_id, chave_idempotencia, registrado_em,
  acao, schema_version
) on table public.consentimento_recibo to authenticated;
grant insert (
  id, igreja_id, evidencia_id, chave_idempotencia, registrado_em,
  acao, schema_version
) on table public.consentimento_recibo to authenticated;

do $policy_guard$
begin
  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = 'public.consentimento_desafio'::pg_catalog.regclass
       and polname = 'consentimento_desafio_tenant_context_barrier'
  ) then
    create policy consentimento_desafio_tenant_context_barrier
      on public.consentimento_desafio
      as restrictive for all to public
      using (
        igreja_id = nullif(
          current_setting('app.tenant_igreja_id', true), ''
        )::uuid
      )
      with check (
        igreja_id = nullif(
          current_setting('app.tenant_igreja_id', true), ''
        )::uuid
      );
  end if;

  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = 'public.consentimento_desafio'::pg_catalog.regclass
       and polname = 'consentimento_desafio_select_authenticated'
  ) then
    create policy consentimento_desafio_select_authenticated
      on public.consentimento_desafio
      as permissive for select to authenticated using (true);
  end if;

  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = 'public.consentimento_desafio'::pg_catalog.regclass
       and polname = 'consentimento_desafio_insert_authenticated'
  ) then
    create policy consentimento_desafio_insert_authenticated
      on public.consentimento_desafio
      as permissive for insert to authenticated with check (true);
  end if;

  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = 'public.consentimento_desafio'::pg_catalog.regclass
       and polname = 'consentimento_desafio_update_authenticated'
  ) then
    create policy consentimento_desafio_update_authenticated
      on public.consentimento_desafio
      as permissive for update to authenticated
      using (estado = 'OPEN' and encerrado_em is null)
      with check (
        estado in ('CONSUMED', 'EXPIRED', 'CANCELLED')
        and encerrado_em is not null
      );
  end if;

  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = 'public.consentimento_evidencia'::pg_catalog.regclass
       and polname = 'consentimento_evidencia_tenant_context_barrier'
  ) then
    create policy consentimento_evidencia_tenant_context_barrier
      on public.consentimento_evidencia
      as restrictive for all to public
      using (
        igreja_id = nullif(
          current_setting('app.tenant_igreja_id', true), ''
        )::uuid
      )
      with check (
        igreja_id = nullif(
          current_setting('app.tenant_igreja_id', true), ''
        )::uuid
      );
  end if;

  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = 'public.consentimento_evidencia'::pg_catalog.regclass
       and polname = 'consentimento_evidencia_select_authenticated'
  ) then
    create policy consentimento_evidencia_select_authenticated
      on public.consentimento_evidencia
      as permissive for select to authenticated using (true);
  end if;

  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = 'public.consentimento_evidencia'::pg_catalog.regclass
       and polname = 'consentimento_evidencia_insert_authenticated'
  ) then
    create policy consentimento_evidencia_insert_authenticated
      on public.consentimento_evidencia
      as permissive for insert to authenticated with check (true);
  end if;

  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = 'public.consentimento_recibo'::pg_catalog.regclass
       and polname = 'consentimento_recibo_tenant_context_barrier'
  ) then
    create policy consentimento_recibo_tenant_context_barrier
      on public.consentimento_recibo
      as restrictive for all to public
      using (
        igreja_id = nullif(
          current_setting('app.tenant_igreja_id', true), ''
        )::uuid
      )
      with check (
        igreja_id = nullif(
          current_setting('app.tenant_igreja_id', true), ''
        )::uuid
      );
  end if;

  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = 'public.consentimento_recibo'::pg_catalog.regclass
       and polname = 'consentimento_recibo_select_authenticated'
  ) then
    create policy consentimento_recibo_select_authenticated
      on public.consentimento_recibo
      as permissive for select to authenticated using (true);
  end if;

  if not exists (
    select 1 from pg_catalog.pg_policy
     where polrelid = 'public.consentimento_recibo'::pg_catalog.regclass
       and polname = 'consentimento_recibo_insert_authenticated'
  ) then
    create policy consentimento_recibo_insert_authenticated
      on public.consentimento_recibo
      as permissive for insert to authenticated with check (true);
  end if;
end
$policy_guard$;

revoke all privileges on function public.consentimento_desafio_validate_write()
  from public, anon, authenticated, service_role;
revoke all privileges on function public.consentimento_evidencia_validate_insert()
  from public, anon, authenticated, service_role;
revoke all privileges on function public.consentimento_evidencia_append_only()
  from public, anon, authenticated, service_role;
revoke all privileges on function public.consentimento_recibo_validate_insert()
  from public, anon, authenticated, service_role;
revoke all privileges on function public.consentimento_recibo_append_only()
  from public, anon, authenticated, service_role;
do $function_acl$
begin
  if pg_catalog.to_regrole('agent_runtime') is not null then
    revoke all privileges on function
      public.consentimento_desafio_validate_write()
      from agent_runtime;
    revoke all privileges on function
      public.consentimento_evidencia_validate_insert()
      from agent_runtime;
    revoke all privileges on function
      public.consentimento_evidencia_append_only()
      from agent_runtime;
    revoke all privileges on function
      public.consentimento_recibo_validate_insert()
      from agent_runtime;
    revoke all privileges on function
      public.consentimento_recibo_append_only()
      from agent_runtime;
  end if;
end
$function_acl$;

do $catalog_guard$
declare
  target pg_catalog.pg_class%rowtype;
  actual_columns text[];
begin
  for target in
    select *
      from pg_catalog.pg_class
     where oid in (
       'public.consentimento_desafio'::pg_catalog.regclass,
       'public.consentimento_evidencia'::pg_catalog.regclass,
       'public.consentimento_recibo'::pg_catalog.regclass
     )
  loop
    if target.relkind <> 'r'
       or target.relpersistence <> 'p'
       or target.relispartition
       or not target.relrowsecurity
       or not target.relforcerowsecurity
    then
      raise exception using
        errcode = 'P0001',
        message = 'consent evidence catalog conflict: relation boundary';
    end if;
  end loop;

  select pg_catalog.array_agg(attribute.attname order by attribute.attnum)
    into actual_columns
    from pg_catalog.pg_attribute attribute
   where attribute.attrelid =
         'public.consentimento_desafio'::pg_catalog.regclass
     and attribute.attnum > 0
     and not attribute.attisdropped;
  if actual_columns is distinct from array[
    'id', 'igreja_id', 'pessoa_id', 'finalidade', 'package_id',
    'package_version', 'content_digest', 'catalog_entry_digest',
    'notice_text_digest', 'binding_id', 'interaction_id', 'canal', 'idioma',
    'criado_em', 'expira_em', 'estado', 'encerrado_em'
  ] then
    raise exception using
      errcode = 'P0001',
      message = 'consent evidence catalog conflict: challenge columns';
  end if;

  select pg_catalog.array_agg(attribute.attname order by attribute.attnum)
    into actual_columns
    from pg_catalog.pg_attribute attribute
   where attribute.attrelid =
         'public.consentimento_evidencia'::pg_catalog.regclass
     and attribute.attnum > 0
     and not attribute.attisdropped;
  if actual_columns is distinct from array[
    'id', 'igreja_id', 'desafio_id', 'tipo', 'apresentacao_id', 'acao',
    'chave_idempotencia', 'registrado_em', 'evidence_digest'
  ] then
    raise exception using
      errcode = 'P0001',
      message = 'consent evidence catalog conflict: evidence columns';
  end if;

  select pg_catalog.array_agg(attribute.attname order by attribute.attnum)
    into actual_columns
    from pg_catalog.pg_attribute attribute
   where attribute.attrelid =
         'public.consentimento_recibo'::pg_catalog.regclass
     and attribute.attnum > 0
     and not attribute.attisdropped;
  if actual_columns is distinct from array[
    'id', 'igreja_id', 'evidencia_id', 'chave_idempotencia', 'registrado_em',
    'acao', 'schema_version'
  ] then
    raise exception using
      errcode = 'P0001',
      message = 'consent evidence catalog conflict: receipt columns';
  end if;

  if (
    select count(*) from pg_catalog.pg_policy
     where polrelid = 'public.consentimento_desafio'::pg_catalog.regclass
  ) <> 4
     or (
       select count(*) from pg_catalog.pg_policy
        where polrelid = 'public.consentimento_evidencia'::pg_catalog.regclass
     ) <> 3
     or (
       select count(*) from pg_catalog.pg_policy
        where polrelid = 'public.consentimento_recibo'::pg_catalog.regclass
     ) <> 3
  then
    raise exception using
      errcode = 'P0001',
      message = 'consent evidence catalog conflict: RLS policy count';
  end if;

  if (
    select count(*) from pg_catalog.pg_trigger
     where tgrelid = 'public.consentimento_desafio'::pg_catalog.regclass
       and not tgisinternal
  ) <> 1
     or (
       select count(*) from pg_catalog.pg_trigger
        where tgrelid = 'public.consentimento_evidencia'::pg_catalog.regclass
          and not tgisinternal
     ) <> 2
     or (
       select count(*) from pg_catalog.pg_trigger
        where tgrelid = 'public.consentimento_recibo'::pg_catalog.regclass
          and not tgisinternal
     ) <> 2
  then
    raise exception using
      errcode = 'P0001',
      message = 'consent evidence catalog conflict: trigger count';
  end if;
end
$catalog_guard$;

comment on table public.consentimento_desafio is
  'E1/E3 laboratory: tenant-bound immutable consent challenge; no writer authorization.';
comment on table public.consentimento_evidencia is
  'E1/E3 laboratory: append-only presentation or REFUSE_INITIAL evidence.';
comment on table public.consentimento_recibo is
  'E1/E3 laboratory: append-only receipt bound exactly to manifestation evidence.';

commit;
