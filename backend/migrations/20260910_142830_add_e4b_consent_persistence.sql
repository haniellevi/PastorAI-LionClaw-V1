-- PASTORAI_MIGRATION_INTENT_V1={"affected_relations":["public.e4b_consent_hold_events","public.e4b_consent_holds","public.e4b_consent_operations","public.e4b_consent_receipts","public.e4b_consent_retentions","public.e4b_consent_streams"],"artifact_id":"migration-authoring-intent-v1","base_repository_sha":"c151c73c2768c7af9193c17b2707d47a42ffb7cc","cross_tenant_test_nodeids":["backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_rls_001_enforces_force_and_tenant_policies","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_guc_001_exercises_positive_and_negative_tenant_matrix","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_chain_002_rejects_invalid_withdraw_origins_and_streams","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_replay_001_rehydrates_exact_and_conflicts_tenant_scoped","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_lock_001_orders_tenant_scoped_advisory_locks","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_commit_001_reconciles_precommit_and_uncertain_commit"],"decision_refs":["docs/decisions/2026-08-28-d2b2b1-consent-security-boundary.md","docs/decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md"],"global_justification":null,"migration_basename":"20260910_142830_add_e4b_consent_persistence.sql","next_stage_authorized":false,"operational_authorization":false,"pg17_test_nodeids":["backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_catalog_001_matches_r4_manifest","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_parent_001_requires_synthetic_parent_anchors","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_rls_001_enforces_force_and_tenant_policies","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_guc_001_exercises_positive_and_negative_tenant_matrix","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_acl_001_verifies_revokes_and_ephemeral_memberships","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_dataapi_001_denies_known_roles_without_guc","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_chain_001_commits_complete_chain_and_rejects_partial","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_chain_002_rejects_invalid_withdraw_origins_and_streams","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_replay_001_rehydrates_exact_and_conflicts_tenant_scoped","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_imm_001_rejects_immutable_updates_and_deletes","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_imm_002_allows_only_stream_hold_retention_transitions","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_auth_001_validates_historical_operator_role_links","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_ret_001_validates_confirmed_at_and_utc_retention","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_hold_001_projects_holds_and_serializes_subject","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_lock_001_orders_tenant_scoped_advisory_locks","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_rollback_001_removes_partial_state_and_releases_locks","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_commit_001_reconciles_precommit_and_uncertain_commit","backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_noskip_001_collects_exact_oracle_manifest"],"recovery":{"kind":"FORWARD_COMPENSATION","reference":"docs/decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md"},"scope":"TENANT","tenant_controls":{"acl_review":"EXPLICIT_GRANTS_AND_REVOKES","enable_rls":true,"force_rls":true,"igreja_id_column":"igreja_id","policy_context":"app.tenant_igreja_id"}}
-- OPERATIONAL_AUTHORIZATION=BLOCKED
-- NEXT_STAGE_AUTHORIZED=false
-- ===========================================================================
-- E4b C3 persistence candidate. It owns only the six relations below and
-- never reads, writes, converts, or infers an outcome from the legacy ledger.
-- ===========================================================================

begin;

do $e4b_preflight$
begin
  if pg_catalog.to_regclass('public.igrejas') is null
     or pg_catalog.to_regclass('public.pessoas') is null
     or pg_catalog.to_regclass('public.app_users') is null
  then
    raise exception using errcode = '42P01',
      message = 'e4b persistence preflight: required parent relation is absent';
  end if;

  if not exists (
    select 1 from pg_catalog.pg_constraint root_key
     where root_key.conrelid = 'public.igrejas'::pg_catalog.regclass
       and root_key.contype in ('p', 'u')
       and root_key.convalidated
       and root_key.conkey = array[
         (
           select attribute_row.attnum
             from pg_catalog.pg_attribute attribute_row
            where attribute_row.attrelid = 'public.igrejas'::pg_catalog.regclass
              and attribute_row.attname = 'id'
              and attribute_row.attnum > 0
              and not attribute_row.attisdropped
         )
       ]::smallint[]
  ) or not exists (
    select 1
      from pg_catalog.pg_attribute root_attribute
     where root_attribute.attrelid = 'public.igrejas'::pg_catalog.regclass
       and root_attribute.attname = 'id'
       and root_attribute.attnum > 0
       and not root_attribute.attisdropped
       and root_attribute.atttypid = 'uuid'::pg_catalog.regtype
  ) then
    raise exception using errcode = 'P0001',
      message = 'e4b persistence preflight: required root parent key is absent';
  end if;

  if not exists (
    select 1 from pg_catalog.pg_constraint
     where conrelid = 'public.pessoas'::pg_catalog.regclass
       and conname = 'pessoas_igreja_id_id_key'
       and contype = 'u' and convalidated
       and pg_catalog.pg_get_constraintdef(oid, true) = 'UNIQUE (igreja_id, id)'
  ) or not exists (
    select 1 from pg_catalog.pg_constraint
     where conrelid = 'public.app_users'::pg_catalog.regclass
       and conname = 'app_users_igreja_id_id_key'
       and contype = 'u' and convalidated
       and pg_catalog.pg_get_constraintdef(oid, true) = 'UNIQUE (igreja_id, id)'
  ) then
    raise exception using errcode = 'P0001',
      message = 'e4b persistence preflight: required tenant parent key is absent';
  end if;

  if pg_catalog.to_regclass('public.e4b_consent_operations') is not null
     or pg_catalog.to_regclass('public.e4b_consent_streams') is not null
     or pg_catalog.to_regclass('public.e4b_consent_receipts') is not null
     or pg_catalog.to_regclass('public.e4b_consent_retentions') is not null
     or pg_catalog.to_regclass('public.e4b_consent_holds') is not null
     or pg_catalog.to_regclass('public.e4b_consent_hold_events') is not null
  then
    raise exception using errcode = '42P07',
      message = 'e4b persistence preflight: target relation already exists';
  end if;

  if pg_catalog.to_regprocedure('public.e4b_consent_immutable_guard_fn()') is not null
     or pg_catalog.to_regprocedure('public.e4b_consent_historical_authority_guard_fn()') is not null
     or pg_catalog.to_regprocedure('public.e4b_consent_stream_transition_guard_fn()') is not null
     or pg_catalog.to_regprocedure('public.e4b_consent_hold_projection_guard_fn()') is not null
     or pg_catalog.to_regprocedure('public.e4b_consent_chain_completeness_guard_fn()') is not null
  then
    raise exception using errcode = '42710',
      message = 'e4b persistence preflight: internal guard function already exists';
  end if;
end
$e4b_preflight$;

create table public.e4b_consent_operations (
  igreja_id uuid not null,
  operation_id uuid not null,
  idempotency_key text not null,
  correlation_id uuid not null,
  action text not null,
  origin text not null default 'E4B',
  origin_accept_operation_id uuid,
  origin_action text,
  titular_pessoa_id uuid not null,
  manifestante_pessoa_id uuid not null,
  responsavel_pessoa_id uuid,
  manifestant_role text not null,
  manifestant_relation_valid boolean not null default true,
  operator_id uuid not null,
  operator_kind text not null,
  operator_role_links text[] not null default array[]::text[],
  server_resolved boolean not null default true,
  finalidade_id text not null,
  contract_version text not null,
  policy_version text not null,
  term_version text not null,
  content_digest text not null,
  fingerprint_version text not null default 'e4b-fingerprint:v1',
  fingerprint text not null,
  concession_state text not null,
  operation_state text not null default 'CONFIRMED',
  confirmed_at timestamp with time zone not null,

  constraint e4b_consent_operations_pkey primary key (igreja_id, operation_id),
  constraint e4b_consent_operations_igreja_fkey
    foreign key (igreja_id) references public.igrejas (id)
    on update restrict on delete restrict,
  constraint e4b_consent_operations_titular_fkey
    foreign key (igreja_id, titular_pessoa_id)
    references public.pessoas (igreja_id, id)
    on update restrict on delete restrict,
  constraint e4b_consent_operations_manifestante_fkey
    foreign key (igreja_id, manifestante_pessoa_id)
    references public.pessoas (igreja_id, id)
    on update restrict on delete restrict,
  constraint e4b_consent_operations_responsavel_fkey
    foreign key (igreja_id, responsavel_pessoa_id)
    references public.pessoas (igreja_id, id)
    on update restrict on delete restrict,
  constraint e4b_consent_operations_origin_accept_fkey
    foreign key (igreja_id, origin_accept_operation_id, origin_action,
                 titular_pessoa_id, finalidade_id)
    references public.e4b_consent_operations
      (igreja_id, operation_id, action, titular_pessoa_id, finalidade_id)
    on update restrict on delete restrict,
  constraint e4b_consent_operations_tenant_k_key
    unique (igreja_id, idempotency_key),
  constraint e4b_consent_operations_tenant_c_key
    unique (igreja_id, correlation_id),
  constraint e4b_consent_operations_stream_action_key
    unique (igreja_id, operation_id, action, titular_pessoa_id, finalidade_id),
  constraint e4b_consent_operations_confirmation_key
    unique (igreja_id, operation_id, confirmed_at),
  constraint e4b_consent_operations_receipt_projection_key
    unique (igreja_id, operation_id, correlation_id, action, origin,
            manifestant_role, concession_state, confirmed_at, contract_version,
            policy_version, term_version, content_digest, fingerprint_version,
            fingerprint),
  constraint e4b_consent_operations_action_check
    check (action in ('ACCEPT', 'WITHDRAW')),
  constraint e4b_consent_operations_origin_check
    check (
      origin = 'E4B' and (
        (action = 'ACCEPT' and origin_accept_operation_id is null
         and origin_action is null and concession_state = 'ACTIVE')
        or
        (action = 'WITHDRAW' and origin_accept_operation_id is not null
         and origin_accept_operation_id <> operation_id
         and origin_action = 'ACCEPT' and concession_state = 'WITHDRAWN')
      )
    ),
  constraint e4b_consent_operations_manifestation_check
    check (
      manifestant_relation_valid and server_resolved and (
        (manifestant_role = 'TITULAR'
         and manifestante_pessoa_id = titular_pessoa_id
         and responsavel_pessoa_id is null)
        or
        (manifestant_role = 'RESPONSAVEL'
         and manifestante_pessoa_id <> titular_pessoa_id
         and responsavel_pessoa_id = manifestante_pessoa_id)
      )
    ),
  constraint e4b_consent_operations_operator_check
    check (
      operator_kind in ('HUMAN', 'TECHNICAL') and operator_role_links in (
        array[]::text[], array['TITULAR']::text[],
        array['MANIFESTANTE']::text[], array['RESPONSAVEL']::text[],
        array['TITULAR', 'MANIFESTANTE']::text[],
        array['TITULAR', 'RESPONSAVEL']::text[],
        array['MANIFESTANTE', 'RESPONSAVEL']::text[],
        array['TITULAR', 'MANIFESTANTE', 'RESPONSAVEL']::text[]
      )
    ),
  constraint e4b_consent_operations_fixed_values_check
    check (
      fingerprint_version = 'e4b-fingerprint:v1'
      and operation_state = 'CONFIRMED' and origin = 'E4B'
      and finalidade_id = pg_catalog.btrim(finalidade_id)
      and pg_catalog.char_length(finalidade_id) between 1 and 128
      and contract_version ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'
      and policy_version ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'
      and term_version ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'
      and idempotency_key ~ '^e4b:consent-operation:v1:[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$'
    ),
  constraint e4b_consent_operations_digest_check
    check (content_digest ~ '^[0-9a-f]{64}$'
           and fingerprint ~ '^[0-9a-f]{64}$')
);

create unique index e4b_consent_operations_one_accept_per_stream_key
  on public.e4b_consent_operations (igreja_id, titular_pessoa_id, finalidade_id)
  where action = 'ACCEPT';
create index e4b_consent_operations_origin_lookup_idx
  on public.e4b_consent_operations (igreja_id, origin_accept_operation_id);
create index e4b_consent_operations_subject_timeline_idx
  on public.e4b_consent_operations (igreja_id, titular_pessoa_id, confirmed_at desc);
create index e4b_consent_operations_tenant_action_idx
  on public.e4b_consent_operations (igreja_id, action, confirmed_at desc);

create table public.e4b_consent_streams (
  igreja_id uuid not null,
  titular_pessoa_id uuid not null,
  finalidade_id text not null,
  accept_operation_id uuid not null,
  accept_action text not null default 'ACCEPT',
  stream_state text not null default 'ACTIVE',
  withdraw_operation_id uuid,
  withdraw_action text,
  state_changed_at timestamp with time zone not null,

  constraint e4b_consent_streams_pkey
    primary key (igreja_id, titular_pessoa_id, finalidade_id),
  constraint e4b_consent_streams_igreja_fkey
    foreign key (igreja_id) references public.igrejas (id)
    on update restrict on delete restrict,
  constraint e4b_consent_streams_titular_fkey
    foreign key (igreja_id, titular_pessoa_id)
    references public.pessoas (igreja_id, id)
    on update restrict on delete restrict,
  constraint e4b_consent_streams_accept_fkey
    foreign key (igreja_id, accept_operation_id, accept_action,
                 titular_pessoa_id, finalidade_id)
    references public.e4b_consent_operations
      (igreja_id, operation_id, action, titular_pessoa_id, finalidade_id)
    on update restrict on delete restrict,
  constraint e4b_consent_streams_withdraw_fkey
    foreign key (igreja_id, withdraw_operation_id, withdraw_action,
                 titular_pessoa_id, finalidade_id)
    references public.e4b_consent_operations
      (igreja_id, operation_id, action, titular_pessoa_id, finalidade_id)
    on update restrict on delete restrict,
  constraint e4b_consent_streams_state_check
    check (
      (stream_state = 'ACTIVE' and withdraw_operation_id is null
       and withdraw_action is null)
      or
      (stream_state = 'WITHDRAWN' and withdraw_operation_id is not null
       and withdraw_action = 'WITHDRAW')
    ),
  constraint e4b_consent_streams_accept_check
    check (accept_action = 'ACCEPT'
           and finalidade_id = pg_catalog.btrim(finalidade_id)
           and pg_catalog.char_length(finalidade_id) between 1 and 128)
);

create index e4b_consent_streams_active_lookup_idx
  on public.e4b_consent_streams (igreja_id, finalidade_id, titular_pessoa_id)
  where stream_state = 'ACTIVE';

create table public.e4b_consent_receipts (
  igreja_id uuid not null,
  receipt_id uuid not null,
  operation_id uuid not null,
  correlation_id uuid not null,
  action text not null,
  origin text not null default 'E4B',
  manifestant_role text not null,
  concession_state text not null,
  confirmed_at timestamp with time zone not null,
  contract_version text not null,
  policy_version text not null,
  term_version text not null,
  content_digest text not null,
  fingerprint_version text not null,
  fingerprint text not null,

  constraint e4b_consent_receipts_pkey primary key (igreja_id, receipt_id),
  constraint e4b_consent_receipts_tenant_operation_key
    unique (igreja_id, operation_id),
  constraint e4b_consent_receipts_igreja_fkey
    foreign key (igreja_id) references public.igrejas (id)
    on update restrict on delete restrict,
  constraint e4b_consent_receipts_operation_fkey
    foreign key (igreja_id, operation_id)
    references public.e4b_consent_operations (igreja_id, operation_id)
    on update restrict on delete restrict,
  constraint e4b_consent_receipts_projection_fkey
    foreign key (igreja_id, operation_id, correlation_id, action, origin,
                 manifestant_role, concession_state, confirmed_at,
                 contract_version, policy_version, term_version, content_digest,
                 fingerprint_version, fingerprint)
    references public.e4b_consent_operations
      (igreja_id, operation_id, correlation_id, action, origin,
       manifestant_role, concession_state, confirmed_at, contract_version,
       policy_version, term_version, content_digest, fingerprint_version,
       fingerprint)
    on update restrict on delete restrict,
  constraint e4b_consent_receipts_fixed_values_check
    check (origin = 'E4B' and action in ('ACCEPT', 'WITHDRAW')
           and manifestant_role in ('TITULAR', 'RESPONSAVEL')
           and concession_state in ('ACTIVE', 'WITHDRAWN')
           and fingerprint_version = 'e4b-fingerprint:v1'),
  constraint e4b_consent_receipts_digest_check
    check (content_digest ~ '^[0-9a-f]{64}$'
           and fingerprint ~ '^[0-9a-f]{64}$')
);

create index e4b_consent_receipts_tenant_c_idx
  on public.e4b_consent_receipts (igreja_id, correlation_id);

create table public.e4b_consent_retentions (
  igreja_id uuid not null,
  operation_id uuid not null,
  retention_state text not null default 'RETENTION_RUNNING',
  retention_anchor_at timestamp with time zone not null,
  retention_due_at timestamp with time zone not null,
  active_hold_count integer not null default 0,
  suspension_started_at timestamp with time zone,
  last_hold_event_at timestamp with time zone,
  state_changed_at timestamp with time zone not null,

  constraint e4b_consent_retentions_pkey primary key (igreja_id, operation_id),
  constraint e4b_consent_retentions_igreja_fkey
    foreign key (igreja_id) references public.igrejas (id)
    on update restrict on delete restrict,
  constraint e4b_consent_retentions_operation_fkey
    foreign key (igreja_id, operation_id)
    references public.e4b_consent_operations (igreja_id, operation_id)
    on update restrict on delete restrict,
  constraint e4b_consent_retentions_anchor_fkey
    foreign key (igreja_id, operation_id, retention_anchor_at)
    references public.e4b_consent_operations
      (igreja_id, operation_id, confirmed_at)
    on update restrict on delete restrict,
  constraint e4b_consent_retentions_count_check
    check (active_hold_count >= 0),
  constraint e4b_consent_retentions_due_check
    check (retention_due_at >= retention_anchor_at),
  constraint e4b_consent_retentions_state_check
    check (
      (retention_state = 'RETENTION_RUNNING'
       and active_hold_count = 0 and suspension_started_at is null)
      or
      (retention_state = 'RETENTION_HELD'
       and active_hold_count > 0 and suspension_started_at is not null)
    )
);

create index e4b_consent_retentions_due_idx
  on public.e4b_consent_retentions
  (igreja_id, retention_state, retention_due_at);

create table public.e4b_consent_holds (
  igreja_id uuid not null,
  hold_id uuid not null,
  operation_id uuid not null,
  hold_state text not null default 'ACTIVE',
  policy_version text not null,
  applied_at timestamp with time zone not null,
  resolved_at timestamp with time zone,

  constraint e4b_consent_holds_pkey primary key (igreja_id, hold_id),
  constraint e4b_consent_holds_identity_key
    unique (igreja_id, hold_id, operation_id),
  constraint e4b_consent_holds_igreja_fkey
    foreign key (igreja_id) references public.igrejas (id)
    on update restrict on delete restrict,
  constraint e4b_consent_holds_operation_fkey
    foreign key (igreja_id, operation_id)
    references public.e4b_consent_retentions (igreja_id, operation_id)
    on update restrict on delete restrict,
  constraint e4b_consent_holds_state_check
    check ((hold_state = 'ACTIVE' and resolved_at is null)
           or (hold_state = 'RESOLVED' and resolved_at >= applied_at)),
  constraint e4b_consent_holds_policy_version_check
    check (policy_version ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$')
);

create index e4b_consent_holds_active_operation_idx
  on public.e4b_consent_holds (igreja_id, operation_id, applied_at)
  where hold_state = 'ACTIVE';

create table public.e4b_consent_hold_events (
  igreja_id uuid not null,
  hold_event_id uuid not null,
  hold_id uuid not null,
  operation_id uuid not null,
  event_kind text not null,
  event_sequence smallint not null,
  authority_app_user_id uuid not null,
  authority_resolution_version text not null,
  authority_resolution_sha256 bytea not null,
  policy_version text not null,
  occurred_at timestamp with time zone not null,

  constraint e4b_consent_hold_events_pkey
    primary key (igreja_id, hold_event_id),
  constraint e4b_consent_hold_events_igreja_fkey
    foreign key (igreja_id) references public.igrejas (id)
    on update restrict on delete restrict,
  constraint e4b_consent_hold_events_hold_fkey
    foreign key (igreja_id, hold_id, operation_id)
    references public.e4b_consent_holds (igreja_id, hold_id, operation_id)
    on update restrict on delete restrict,
  constraint e4b_consent_hold_events_authority_fkey
    foreign key (igreja_id, authority_app_user_id)
    references public.app_users (igreja_id, id)
    on update restrict on delete restrict,
  constraint e4b_consent_hold_events_kind_key
    unique (igreja_id, hold_id, event_kind),
  constraint e4b_consent_hold_events_sequence_key
    unique (igreja_id, hold_id, event_sequence),
  constraint e4b_consent_hold_events_kind_sequence_check
    check ((event_kind = 'HOLD_APPLIED' and event_sequence = 1)
           or (event_kind = 'HOLD_RESOLVED' and event_sequence = 2)),
  constraint e4b_consent_hold_events_digest_check
    check (pg_catalog.octet_length(authority_resolution_sha256) = 32),
  constraint e4b_consent_hold_events_versions_check
    check (authority_resolution_version ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'
           and policy_version ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$')
);

create index e4b_consent_hold_events_timeline_idx
  on public.e4b_consent_hold_events (igreja_id, hold_id, occurred_at);

create function public.e4b_consent_immutable_guard_fn()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog, public
as $e4b_immutable$
begin
  if tg_op = 'DELETE' then
    raise exception using errcode = 'P0001',
      message = 'e4b immutable guard rejected deletion';
  end if;

  if tg_table_name in
    ('e4b_consent_operations', 'e4b_consent_receipts', 'e4b_consent_hold_events')
  then
    raise exception using errcode = 'P0001',
      message = 'e4b immutable guard rejected update';
  end if;

  if tg_table_name = 'e4b_consent_streams' then
    if new.igreja_id is distinct from old.igreja_id
       or new.titular_pessoa_id is distinct from old.titular_pessoa_id
       or new.finalidade_id is distinct from old.finalidade_id
       or new.accept_operation_id is distinct from old.accept_operation_id
       or new.accept_action is distinct from old.accept_action
    then
      raise exception using errcode = 'P0001',
        message = 'e4b immutable guard rejected stream identity change';
    end if;
    return new;
  end if;

  if tg_table_name = 'e4b_consent_retentions' then
    if new.retention_state = 'RETENTION_ELIGIBLE' then
      raise exception using errcode = 'P0001',
        message = 'e4b immutable guard rejected retention eligibility in C3';
    end if;
    if new.igreja_id is distinct from old.igreja_id
       or new.operation_id is distinct from old.operation_id
       or new.retention_anchor_at is distinct from old.retention_anchor_at
    then
      raise exception using errcode = 'P0001',
        message = 'e4b immutable guard rejected retention identity change';
    end if;
    return new;
  end if;

  if tg_table_name = 'e4b_consent_holds' then
    if new.igreja_id is distinct from old.igreja_id
       or new.hold_id is distinct from old.hold_id
       or new.operation_id is distinct from old.operation_id
       or new.policy_version is distinct from old.policy_version
       or new.applied_at is distinct from old.applied_at
       or old.hold_state <> 'ACTIVE'
       or new.hold_state <> 'RESOLVED'
       or new.resolved_at is null
    then
      raise exception using errcode = 'P0001',
        message = 'e4b immutable guard rejected hold transition';
    end if;
    return new;
  end if;

  raise exception using errcode = 'P0001',
    message = 'e4b immutable guard received unknown relation';
end
$e4b_immutable$;

create function public.e4b_consent_historical_authority_guard_fn()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog, public
as $e4b_historical_authority$
declare
  expected_links text[];
begin
  expected_links := pg_catalog.array_remove(
    array[
      case when new.operator_id = new.titular_pessoa_id then 'TITULAR' end,
      case when new.operator_id = new.manifestante_pessoa_id then 'MANIFESTANTE' end,
      case when new.responsavel_pessoa_id is not null
                and new.operator_id = new.responsavel_pessoa_id
           then 'RESPONSAVEL' end
    ]::text[],
    null
  );
  if new.operator_role_links is distinct from expected_links then
    raise exception using errcode = 'P0001',
      message = 'e4b historical authority guard rejected operator links';
  end if;
  return new;
end
$e4b_historical_authority$;

create function public.e4b_consent_stream_transition_guard_fn()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog, public
as $e4b_stream_transition$
declare
  operation_confirmed_at timestamp with time zone;
begin
  if tg_op = 'INSERT' then
    if new.stream_state <> 'ACTIVE'
       or new.withdraw_operation_id is not null
       or new.withdraw_action is not null
       or new.accept_action <> 'ACCEPT'
    then
      raise exception using errcode = 'P0001',
        message = 'e4b stream guard rejected initial stream state';
    end if;
    select operation.confirmed_at into operation_confirmed_at
      from public.e4b_consent_operations operation
     where operation.igreja_id = new.igreja_id
       and operation.operation_id = new.accept_operation_id
       and operation.action = 'ACCEPT'
       and operation.titular_pessoa_id = new.titular_pessoa_id
       and operation.finalidade_id = new.finalidade_id;
    if not found or new.state_changed_at is distinct from operation_confirmed_at then
      raise exception using errcode = 'P0001',
        message = 'e4b stream guard rejected accept confirmation timestamp';
    end if;
    return new;
  end if;

  if old.stream_state <> 'ACTIVE'
     or new.stream_state <> 'WITHDRAWN'
     or new.igreja_id is distinct from old.igreja_id
     or new.titular_pessoa_id is distinct from old.titular_pessoa_id
     or new.finalidade_id is distinct from old.finalidade_id
     or new.accept_operation_id is distinct from old.accept_operation_id
     or new.accept_action is distinct from old.accept_action
     or new.withdraw_operation_id is null
     or new.withdraw_action <> 'WITHDRAW'
  then
    raise exception using errcode = 'P0001',
      message = 'e4b stream guard rejected transition';
  end if;
  select operation.confirmed_at into operation_confirmed_at
    from public.e4b_consent_operations operation
   where operation.igreja_id = new.igreja_id
     and operation.operation_id = new.withdraw_operation_id
     and operation.action = 'WITHDRAW'
     and operation.titular_pessoa_id = new.titular_pessoa_id
     and operation.finalidade_id = new.finalidade_id
     and operation.origin_accept_operation_id = new.accept_operation_id;
  if not found or new.state_changed_at is distinct from operation_confirmed_at then
    raise exception using errcode = 'P0001',
      message = 'e4b stream guard rejected withdraw confirmation timestamp';
  end if;
  return new;
end
$e4b_stream_transition$;

create function public.e4b_consent_hold_projection_guard_fn()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog, public
as $e4b_hold_projection$
declare
  target_tenant uuid := new.igreja_id;
  target_operation uuid := new.operation_id;
  retention_row public.e4b_consent_retentions%rowtype;
  operation_confirmed_at timestamp with time zone;
  hold_row public.e4b_consent_holds%rowtype;
  applied_count integer;
  resolved_count integer;
  event_count integer;
  applied_at_event timestamp with time zone;
  applied_policy text;
  resolved_at_event timestamp with time zone;
  active_count integer;
  last_event_at timestamp with time zone;
  open_component_at timestamp with time zone;
  finite_pause interval;
  anchor_utc timestamp without time zone;
  target_year integer;
  target_month integer;
  target_day integer;
  target_hour integer;
  target_minute integer;
  target_second double precision;
  target_last_day integer;
  base_due_at timestamp with time zone;
  expected_due_at timestamp with time zone;
  expected_state text;
  expected_changed_at timestamp with time zone;
begin
  select * into retention_row
    from public.e4b_consent_retentions retention
   where retention.igreja_id = target_tenant
     and retention.operation_id = target_operation;
  if not found then
    raise exception using errcode = 'P0001',
      message = 'e4b hold projection guard requires retention';
  end if;

  select operation.confirmed_at into operation_confirmed_at
    from public.e4b_consent_operations operation
   where operation.igreja_id = target_tenant
     and operation.operation_id = target_operation;
  if not found
     or retention_row.retention_anchor_at is distinct from operation_confirmed_at
  then
    raise exception using errcode = 'P0001',
      message = 'e4b hold projection guard rejected retention anchor';
  end if;

  for hold_row in
    select * from public.e4b_consent_holds hold
     where hold.igreja_id = target_tenant
       and hold.operation_id = target_operation
  loop
    select
      count(*) filter (where event.event_kind = 'HOLD_APPLIED'),
      count(*) filter (where event.event_kind = 'HOLD_RESOLVED'),
      count(*),
      max(event.occurred_at) filter (where event.event_kind = 'HOLD_APPLIED'),
      max(event.policy_version) filter (where event.event_kind = 'HOLD_APPLIED'),
      max(event.occurred_at) filter (where event.event_kind = 'HOLD_RESOLVED')
      into applied_count, resolved_count, event_count, applied_at_event,
           applied_policy, resolved_at_event
      from public.e4b_consent_hold_events event
     where event.igreja_id = target_tenant
       and event.hold_id = hold_row.hold_id
       and event.operation_id = target_operation;
    if applied_count <> 1
       or applied_at_event is distinct from hold_row.applied_at
       or applied_policy is distinct from hold_row.policy_version
       or (hold_row.hold_state = 'ACTIVE'
           and (resolved_count <> 0 or event_count <> 1
                or hold_row.resolved_at is not null))
       or (hold_row.hold_state = 'RESOLVED'
           and (resolved_count <> 1 or event_count <> 2
                or resolved_at_event is distinct from hold_row.resolved_at))
    then
      raise exception using errcode = 'P0001',
        message = 'e4b hold projection guard rejected hold event equality';
    end if;
  end loop;

  select count(*) filter (where hold.hold_state = 'ACTIVE'),
         max(event.occurred_at)
    into active_count, last_event_at
    from public.e4b_consent_holds hold
    left join public.e4b_consent_hold_events event
      on event.igreja_id = hold.igreja_id
     and event.hold_id = hold.hold_id
     and event.operation_id = hold.operation_id
   where hold.igreja_id = target_tenant
     and hold.operation_id = target_operation;
  active_count := coalesce(active_count, 0);

  with merged as (
    select pg_catalog.unnest(
      pg_catalog.range_agg(
        pg_catalog.tstzrange(
          hold.applied_at,
          case when hold.hold_state = 'ACTIVE' then null else hold.resolved_at end,
          case when hold.hold_state = 'ACTIVE' then '[)' else '[]' end
        )
      )
    ) as span
      from public.e4b_consent_holds hold
     where hold.igreja_id = target_tenant
       and hold.operation_id = target_operation
  )
  select coalesce(
           sum(pg_catalog.upper(span) - pg_catalog.lower(span))
             filter (where not pg_catalog.upper_inf(span)),
           interval '0'
         ),
         min(pg_catalog.lower(span)) filter (where pg_catalog.upper_inf(span))
    into finite_pause, open_component_at
    from merged;

  anchor_utc := pg_catalog.timezone('UTC', retention_row.retention_anchor_at);
  target_year := extract(year from anchor_utc)::integer + 2;
  target_month := extract(month from anchor_utc)::integer;
  target_day := extract(day from anchor_utc)::integer;
  target_hour := extract(hour from anchor_utc)::integer;
  target_minute := extract(minute from anchor_utc)::integer;
  target_second := extract(second from anchor_utc)::double precision;
  target_last_day := extract(day from (
    pg_catalog.make_date(target_year, target_month, 1)
    + interval '1 month - 1 day'
  ))::integer;
  base_due_at := pg_catalog.make_timestamptz(
    target_year, target_month, least(target_day, target_last_day),
    target_hour, target_minute, target_second, 'UTC'
  );
  expected_due_at := base_due_at + finite_pause;
  expected_state := case when active_count > 0 then 'RETENTION_HELD'
    else 'RETENTION_RUNNING'
  end;
  expected_changed_at := coalesce(last_event_at, retention_row.retention_anchor_at);

  if retention_row.active_hold_count <> active_count
     or retention_row.retention_state is distinct from expected_state
     or retention_row.suspension_started_at is distinct from open_component_at
     or retention_row.last_hold_event_at is distinct from last_event_at
     or retention_row.retention_due_at is distinct from expected_due_at
     or retention_row.state_changed_at is distinct from expected_changed_at
  then
    raise exception using errcode = 'P0001',
      message = 'e4b hold projection guard rejected retention projection';
  end if;
  return new;
end
$e4b_hold_projection$;

create function public.e4b_consent_chain_completeness_guard_fn()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog, public
as $e4b_chain_completeness$
declare
  target_tenant uuid := new.igreja_id;
  operation_ids uuid[] := array[]::uuid[];
  target_operation uuid;
  operation_row public.e4b_consent_operations%rowtype;
  stream_row public.e4b_consent_streams%rowtype;
  link_count integer;
begin
  if tg_table_name = 'e4b_consent_operations' then
    operation_ids := array[new.operation_id];
  elsif tg_table_name = 'e4b_consent_streams' then
    operation_ids := array[new.accept_operation_id];
    if new.withdraw_operation_id is not null then
      operation_ids := operation_ids || new.withdraw_operation_id;
    end if;
  elsif tg_table_name in ('e4b_consent_receipts', 'e4b_consent_retentions') then
    operation_ids := array[new.operation_id];
  else
    raise exception using errcode = 'P0001',
      message = 'e4b chain guard received unknown relation';
  end if;

  foreach target_operation in array operation_ids loop
    select * into operation_row
      from public.e4b_consent_operations operation
     where operation.igreja_id = target_tenant
       and operation.operation_id = target_operation;
    if not found then
      raise exception using errcode = 'P0001',
        message = 'e4b chain guard requires operation';
    end if;
    select count(*) into link_count
      from public.e4b_consent_receipts receipt
     where receipt.igreja_id = target_tenant
       and receipt.operation_id = target_operation;
    if link_count <> 1 then
      raise exception using errcode = 'P0001',
        message = 'e4b chain guard requires one receipt';
    end if;
    select count(*) into link_count
      from public.e4b_consent_retentions retention
     where retention.igreja_id = target_tenant
       and retention.operation_id = target_operation;
    if link_count <> 1 then
      raise exception using errcode = 'P0001',
        message = 'e4b chain guard requires one retention';
    end if;
    select * into stream_row
      from public.e4b_consent_streams stream
     where stream.igreja_id = target_tenant
       and stream.titular_pessoa_id = operation_row.titular_pessoa_id
       and stream.finalidade_id = operation_row.finalidade_id;
    if not found or stream_row.accept_operation_id is null then
      raise exception using errcode = 'P0001',
        message = 'e4b chain guard requires stream';
    end if;
    if operation_row.action = 'ACCEPT' then
      if stream_row.accept_operation_id <> target_operation
         or stream_row.accept_action <> 'ACCEPT'
         or (stream_row.stream_state = 'WITHDRAWN'
             and (stream_row.withdraw_operation_id is null
                  or stream_row.withdraw_action <> 'WITHDRAW'))
      then
        raise exception using errcode = 'P0001',
          message = 'e4b chain guard rejected accept stream';
      end if;
    elsif operation_row.action = 'WITHDRAW' then
      if stream_row.stream_state <> 'WITHDRAWN'
         or stream_row.withdraw_operation_id <> target_operation
         or stream_row.withdraw_action <> 'WITHDRAW'
         or stream_row.accept_operation_id <> operation_row.origin_accept_operation_id
      then
        raise exception using errcode = 'P0001',
          message = 'e4b chain guard rejected withdraw stream';
      end if;
    else
      raise exception using errcode = 'P0001',
        message = 'e4b chain guard rejected action';
    end if;
  end loop;
  return new;
end
$e4b_chain_completeness$;

create trigger e4b_operations_immutable_guard_trg
before update or delete on public.e4b_consent_operations
for each row execute function public.e4b_consent_immutable_guard_fn();
create trigger e4b_streams_immutable_guard_trg
before update or delete on public.e4b_consent_streams
for each row execute function public.e4b_consent_immutable_guard_fn();
create trigger e4b_receipts_immutable_guard_trg
before update or delete on public.e4b_consent_receipts
for each row execute function public.e4b_consent_immutable_guard_fn();
create trigger e4b_retentions_immutable_guard_trg
before update or delete on public.e4b_consent_retentions
for each row execute function public.e4b_consent_immutable_guard_fn();
create trigger e4b_holds_immutable_guard_trg
before update or delete on public.e4b_consent_holds
for each row execute function public.e4b_consent_immutable_guard_fn();
create trigger e4b_hold_events_immutable_guard_trg
before update or delete on public.e4b_consent_hold_events
for each row execute function public.e4b_consent_immutable_guard_fn();

create trigger e4b_operations_historical_authority_guard_trg
before insert on public.e4b_consent_operations
for each row execute function public.e4b_consent_historical_authority_guard_fn();
create trigger e4b_streams_transition_guard_trg
before insert or update on public.e4b_consent_streams
for each row execute function public.e4b_consent_stream_transition_guard_fn();

create constraint trigger e4b_retentions_hold_projection_guard_ctrg
after insert or update on public.e4b_consent_retentions
deferrable initially deferred
for each row execute function public.e4b_consent_hold_projection_guard_fn();
create constraint trigger e4b_holds_hold_projection_guard_ctrg
after insert or update on public.e4b_consent_holds
deferrable initially deferred
for each row execute function public.e4b_consent_hold_projection_guard_fn();
create constraint trigger e4b_hold_events_hold_projection_guard_ctrg
after insert on public.e4b_consent_hold_events
deferrable initially deferred
for each row execute function public.e4b_consent_hold_projection_guard_fn();
create constraint trigger e4b_operations_chain_completeness_guard_ctrg
after insert on public.e4b_consent_operations
deferrable initially deferred
for each row execute function public.e4b_consent_chain_completeness_guard_fn();
create constraint trigger e4b_streams_chain_completeness_guard_ctrg
after insert or update on public.e4b_consent_streams
deferrable initially deferred
for each row execute function public.e4b_consent_chain_completeness_guard_fn();
create constraint trigger e4b_receipts_chain_completeness_guard_ctrg
after insert on public.e4b_consent_receipts
deferrable initially deferred
for each row execute function public.e4b_consent_chain_completeness_guard_fn();
create constraint trigger e4b_retentions_chain_completeness_guard_ctrg
after insert on public.e4b_consent_retentions
deferrable initially deferred
for each row execute function public.e4b_consent_chain_completeness_guard_fn();

alter table public.e4b_consent_operations enable row level security;
alter table public.e4b_consent_operations force row level security;
alter table public.e4b_consent_streams enable row level security;
alter table public.e4b_consent_streams force row level security;
alter table public.e4b_consent_receipts enable row level security;
alter table public.e4b_consent_receipts force row level security;
alter table public.e4b_consent_retentions enable row level security;
alter table public.e4b_consent_retentions force row level security;
alter table public.e4b_consent_holds enable row level security;
alter table public.e4b_consent_holds force row level security;
alter table public.e4b_consent_hold_events enable row level security;
alter table public.e4b_consent_hold_events force row level security;

create policy e4b_operations_tenant_permissive
  on public.e4b_consent_operations as permissive for all to public
  using (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid)
  with check (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid);
create policy e4b_operations_tenant_restrictive
  on public.e4b_consent_operations as restrictive for all to public
  using (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid)
  with check (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid);
create policy e4b_streams_tenant_permissive
  on public.e4b_consent_streams as permissive for all to public
  using (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid)
  with check (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid);
create policy e4b_streams_tenant_restrictive
  on public.e4b_consent_streams as restrictive for all to public
  using (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid)
  with check (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid);
create policy e4b_receipts_tenant_permissive
  on public.e4b_consent_receipts as permissive for all to public
  using (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid)
  with check (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid);
create policy e4b_receipts_tenant_restrictive
  on public.e4b_consent_receipts as restrictive for all to public
  using (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid)
  with check (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid);
create policy e4b_retentions_tenant_permissive
  on public.e4b_consent_retentions as permissive for all to public
  using (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid)
  with check (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid);
create policy e4b_retentions_tenant_restrictive
  on public.e4b_consent_retentions as restrictive for all to public
  using (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid)
  with check (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid);
create policy e4b_holds_tenant_permissive
  on public.e4b_consent_holds as permissive for all to public
  using (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid)
  with check (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid);
create policy e4b_holds_tenant_restrictive
  on public.e4b_consent_holds as restrictive for all to public
  using (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid)
  with check (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid);
create policy e4b_hold_events_tenant_permissive
  on public.e4b_consent_hold_events as permissive for all to public
  using (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid)
  with check (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid);
create policy e4b_hold_events_tenant_restrictive
  on public.e4b_consent_hold_events as restrictive for all to public
  using (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid)
  with check (igreja_id = nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::uuid);

-- PUBLIC is always addressable. Named roles are conditional so the catalog
-- replay remains executable from its intentionally role-free fresh database.
-- The dedicated C3 bootstrap requires its synthetic role baseline before its
-- own oracle run and proves the revocations for every named role there.
revoke all privileges on table
  public.e4b_consent_operations,
  public.e4b_consent_streams,
  public.e4b_consent_receipts,
  public.e4b_consent_retentions,
  public.e4b_consent_holds,
  public.e4b_consent_hold_events
  from public;
revoke select, insert, update, delete, truncate, references, trigger on table
  public.e4b_consent_operations,
  public.e4b_consent_streams,
  public.e4b_consent_receipts,
  public.e4b_consent_retentions,
  public.e4b_consent_holds,
  public.e4b_consent_hold_events
  from public;
revoke all privileges on function public.e4b_consent_immutable_guard_fn() from public;
revoke all privileges on function public.e4b_consent_historical_authority_guard_fn() from public;
revoke all privileges on function public.e4b_consent_stream_transition_guard_fn() from public;
revoke all privileges on function public.e4b_consent_hold_projection_guard_fn() from public;
revoke all privileges on function public.e4b_consent_chain_completeness_guard_fn() from public;
revoke execute on function public.e4b_consent_immutable_guard_fn() from public;
revoke execute on function public.e4b_consent_historical_authority_guard_fn() from public;
revoke execute on function public.e4b_consent_stream_transition_guard_fn() from public;
revoke execute on function public.e4b_consent_hold_projection_guard_fn() from public;
revoke execute on function public.e4b_consent_chain_completeness_guard_fn() from public;

do $e4b_conditional_revoke$
declare
  target_role text;
begin
  foreach target_role in array array[
    'anon', 'authenticated', 'service_role', 'agent_runtime'
  ] loop
    if pg_catalog.to_regrole(target_role) is not null then
      execute format(
        'revoke all privileges on table public.e4b_consent_operations, public.e4b_consent_streams, public.e4b_consent_receipts, public.e4b_consent_retentions, public.e4b_consent_holds, public.e4b_consent_hold_events from %I',
        target_role
      );
      execute format(
        'revoke select, insert, update, delete, truncate, references, trigger on table public.e4b_consent_operations, public.e4b_consent_streams, public.e4b_consent_receipts, public.e4b_consent_retentions, public.e4b_consent_holds, public.e4b_consent_hold_events from %I',
        target_role
      );
      execute format('revoke all privileges on function public.e4b_consent_immutable_guard_fn() from %I', target_role);
      execute format('revoke all privileges on function public.e4b_consent_historical_authority_guard_fn() from %I', target_role);
      execute format('revoke all privileges on function public.e4b_consent_stream_transition_guard_fn() from %I', target_role);
      execute format('revoke all privileges on function public.e4b_consent_hold_projection_guard_fn() from %I', target_role);
      execute format('revoke all privileges on function public.e4b_consent_chain_completeness_guard_fn() from %I', target_role);
      execute format('revoke execute on function public.e4b_consent_immutable_guard_fn() from %I', target_role);
      execute format('revoke execute on function public.e4b_consent_historical_authority_guard_fn() from %I', target_role);
      execute format('revoke execute on function public.e4b_consent_stream_transition_guard_fn() from %I', target_role);
      execute format('revoke execute on function public.e4b_consent_hold_projection_guard_fn() from %I', target_role);
      execute format('revoke execute on function public.e4b_consent_chain_completeness_guard_fn() from %I', target_role);
    end if;
  end loop;
end
$e4b_conditional_revoke$;

commit;
