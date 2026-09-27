-- S3 WhatsApp: confirmação local de identidade e propostas tipadas de ação.
-- Relações tenant-scoped, sem transporte, sem credencial e sem dado textual.
-- Depende de 20260927_120000_church_cell_public_data.sql para a chave tripla
-- de messages usada pelas âncoras de conversa.

begin;

set local lock_timeout = '2s';

alter table public.messages
  add column if not exists agent_privilege_context jsonb;

alter table public.messages
  drop constraint if exists messages_agent_privilege_context_object_chk;

alter table public.messages
  add constraint messages_agent_privilege_context_object_chk
  check (
    agent_privilege_context is null
    or jsonb_typeof(agent_privilege_context) = 'object'
  ) not valid;

alter table public.messages
  validate constraint messages_agent_privilege_context_object_chk;

create table if not exists public.agent_identity_challenges (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  conversation_id uuid not null,
  pessoa_id uuid not null,
  issued_from_message_id uuid not null,
  issued_at timestamptz not null,
  challenge_expires_at timestamptz not null,
  sequence bigint not null,
  constraint agent_identity_challenges_tenant_id_key unique (igreja_id, id),
  constraint agent_identity_challenges_inbound_once_key
    unique (igreja_id, issued_from_message_id),
  constraint agent_identity_challenges_conversation_sequence_key
    unique (igreja_id, conversation_id, sequence),
  constraint agent_identity_challenges_tenant_conversation_fkey
    foreign key (igreja_id, conversation_id)
    references public.conversations (igreja_id, id) on delete cascade,
  constraint agent_identity_challenges_tenant_pessoa_fkey
    foreign key (igreja_id, pessoa_id)
    references public.pessoas (igreja_id, id) on delete cascade,
  constraint agent_identity_challenges_inbound_anchor_fkey
    foreign key (igreja_id, conversation_id, issued_from_message_id)
    references public.messages (igreja_id, conversation_id, id) on delete cascade,
  constraint agent_identity_challenges_sequence_positive check (sequence > 0),
  constraint agent_identity_challenges_expiry_window
    check (
      challenge_expires_at > issued_at
      and challenge_expires_at <= issued_at + interval '5 minutes'
    )
);

create index if not exists agent_identity_challenges_conversation_latest_idx
  on public.agent_identity_challenges (igreja_id, conversation_id, sequence desc);

create table if not exists public.agent_identity_proofs (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  challenge_id uuid not null,
  conversation_id uuid not null,
  pessoa_id uuid not null,
  confirmed_by_app_user_id uuid not null,
  confirmed_at timestamptz not null,
  confirmed_until timestamptz not null,
  credential_fingerprint text not null,
  roles_fingerprint text not null,
  integrity_hmac text not null,
  constraint agent_identity_proofs_tenant_id_key unique (igreja_id, id),
  constraint agent_identity_proofs_challenge_once_key unique (challenge_id),
  constraint agent_identity_proofs_tenant_challenge_fkey
    foreign key (igreja_id, challenge_id)
    references public.agent_identity_challenges (igreja_id, id) on delete cascade,
  constraint agent_identity_proofs_tenant_conversation_fkey
    foreign key (igreja_id, conversation_id)
    references public.conversations (igreja_id, id) on delete cascade,
  constraint agent_identity_proofs_tenant_pessoa_fkey
    foreign key (igreja_id, pessoa_id)
    references public.pessoas (igreja_id, id) on delete cascade,
  constraint agent_identity_proofs_tenant_app_user_fkey
    foreign key (igreja_id, confirmed_by_app_user_id)
    references public.app_users (igreja_id, id) on delete cascade,
  constraint agent_identity_proofs_expiry_window
    check (confirmed_until = confirmed_at + interval '15 minutes'),
  constraint agent_identity_proofs_credential_fingerprint_shape
    check (credential_fingerprint ~ '^[0-9a-f]{64}$'),
  constraint agent_identity_proofs_roles_fingerprint_shape
    check (roles_fingerprint ~ '^[0-9a-f]{64}$'),
  constraint agent_identity_proofs_integrity_hmac_shape
    check (integrity_hmac ~ '^[0-9a-f]{64}$')
);

create index if not exists agent_identity_proofs_conversation_lookup_idx
  on public.agent_identity_proofs (igreja_id, conversation_id);

create table if not exists public.agent_action_proposals (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  conversation_id uuid not null,
  actor_pessoa_id uuid not null,
  actor_app_user_id uuid not null,
  source_message_id uuid not null,
  action text not null,
  target_kind text not null,
  target_id uuid not null,
  arguments_json jsonb not null,
  arguments_sha256 text not null,
  scope_fingerprint text not null,
  summary_sha256 text not null,
  state text not null,
  summary_message_id uuid,
  confirmation_message_id uuid,
  delivered_at timestamptz,
  expires_at timestamptz,
  executed_at timestamptz,
  terminal_reason text,
  created_at timestamptz not null default now(),
  constraint agent_action_proposals_tenant_id_key unique (igreja_id, id),
  constraint agent_action_proposals_source_once_key
    unique (igreja_id, source_message_id),
  constraint agent_action_proposals_summary_once_key
    unique (igreja_id, summary_message_id),
  constraint agent_action_proposals_confirmation_once_key
    unique (igreja_id, confirmation_message_id),
  constraint agent_action_proposals_tenant_conversation_fkey
    foreign key (igreja_id, conversation_id)
    references public.conversations (igreja_id, id) on delete cascade,
  constraint agent_action_proposals_tenant_actor_pessoa_fkey
    foreign key (igreja_id, actor_pessoa_id)
    references public.pessoas (igreja_id, id) on delete cascade,
  constraint agent_action_proposals_tenant_actor_app_user_fkey
    foreign key (igreja_id, actor_app_user_id)
    references public.app_users (igreja_id, id) on delete cascade,
  constraint agent_action_proposals_source_anchor_fkey
    foreign key (igreja_id, conversation_id, source_message_id)
    references public.messages (igreja_id, conversation_id, id) on delete cascade,
  constraint agent_action_proposals_summary_anchor_fkey
    foreign key (igreja_id, conversation_id, summary_message_id)
    references public.messages (igreja_id, conversation_id, id) on delete cascade,
  constraint agent_action_proposals_confirmation_anchor_fkey
    foreign key (igreja_id, conversation_id, confirmation_message_id)
    references public.messages (igreja_id, conversation_id, id) on delete cascade,
  constraint agent_action_proposals_action_closed
    check (action in ('registrar_decisao', 'marcar_presenca')),
  constraint agent_action_proposals_target_kind_closed
    check (target_kind = 'pessoa'),
  constraint agent_action_proposals_state_closed
    check (state in ('preparada', 'pendente', 'executada', 'rejeitada',
                     'cancelada', 'expirada', 'falha')),
  constraint agent_action_proposals_arguments_digest_shape
    check (arguments_sha256 ~ '^[0-9a-f]{64}$'),
  constraint agent_action_proposals_scope_fingerprint_shape
    check (scope_fingerprint ~ '^[0-9a-f]{64}$'),
  constraint agent_action_proposals_summary_digest_shape
    check (summary_sha256 ~ '^[0-9a-f]{64}$'),
  constraint agent_action_proposals_expiry_requires_delivery
    check (expires_at is null or delivered_at is not null)
);

create unique index if not exists agent_action_proposals_one_active_conversation_idx
  on public.agent_action_proposals (igreja_id, conversation_id)
  where state in ('preparada', 'pendente');
create index if not exists agent_action_proposals_conversation_state_idx
  on public.agent_action_proposals (igreja_id, conversation_id, state);

create table if not exists public.agent_action_receipts (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null,
  proposal_id uuid not null,
  conversation_id uuid not null,
  confirmation_message_id uuid not null,
  outcome text not null default 'executada',
  effect_reference text not null,
  receipt_text text not null,
  created_at timestamptz not null default now(),
  constraint agent_action_receipts_tenant_id_key unique (igreja_id, id),
  constraint agent_action_proposals_receipt_once_key
    unique (igreja_id, proposal_id),
  constraint agent_action_receipts_tenant_proposal_fkey
    foreign key (igreja_id, proposal_id)
    references public.agent_action_proposals (igreja_id, id) on delete cascade,
  constraint agent_action_receipts_tenant_conversation_fkey
    foreign key (igreja_id, conversation_id)
    references public.conversations (igreja_id, id) on delete cascade,
  constraint agent_action_receipts_confirmation_anchor_fkey
    foreign key (igreja_id, conversation_id, confirmation_message_id)
    references public.messages (igreja_id, conversation_id, id) on delete cascade,
  constraint agent_action_receipts_outcome_closed check (outcome = 'executada'),
  constraint agent_action_receipts_effect_reference_shape
    check (effect_reference ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  constraint agent_action_receipts_receipt_text_closed
    check (receipt_text = 'Registro confirmado.')
);

create index if not exists agent_action_receipts_conversation_idx
  on public.agent_action_receipts (igreja_id, conversation_id);

alter table public.agent_identity_challenges enable row level security;
alter table public.agent_identity_challenges force row level security;
alter table public.agent_identity_proofs enable row level security;
alter table public.agent_identity_proofs force row level security;
alter table public.agent_action_proposals enable row level security;
alter table public.agent_action_proposals force row level security;
alter table public.agent_action_receipts enable row level security;
alter table public.agent_action_receipts force row level security;

-- Panel reads only its own challenge/proof.  A worker has no JWT subject but
-- must still correlate its tenant-scoped inbound after the backend set its GUC.
drop policy if exists agent_identity_challenges_select
  on public.agent_identity_challenges;
create policy agent_identity_challenges_select
  on public.agent_identity_challenges for select to authenticated
  using (
    igreja_id = public.current_igreja_id()
    and (
      nullif(coalesce(
        nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
        pg_catalog.current_setting('request.jwt.claim.sub', true)
      ), '') is null
      or exists (
        select 1
        from public.app_users au
        where au.igreja_id = agent_identity_challenges.igreja_id
          and au.pessoa_id = agent_identity_challenges.pessoa_id
          and au.status = 'ativo'
          and au.clerk_user_id = nullif(coalesce(
            nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
            pg_catalog.current_setting('request.jwt.claim.sub', true)
          ), '')
      )
    )
  );

-- Challenges are issued only by the inbound worker. The panel only confirms.
drop policy if exists agent_identity_challenges_insert
  on public.agent_identity_challenges;
create policy agent_identity_challenges_insert
  on public.agent_identity_challenges for insert to authenticated
  with check (
    igreja_id = public.current_igreja_id()
    and exists (
      select 1 from public.messages m
      where m.igreja_id = agent_identity_challenges.igreja_id
        and m.conversation_id = agent_identity_challenges.conversation_id
        and m.id = agent_identity_challenges.issued_from_message_id
        and m.direcao = 'in'
    )
    and nullif(coalesce(
      nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)
    ), '') is null
  );

drop policy if exists agent_identity_proofs_select
  on public.agent_identity_proofs;
create policy agent_identity_proofs_select
  on public.agent_identity_proofs for select to authenticated
  using (
    igreja_id = public.current_igreja_id()
    and (
      nullif(coalesce(
        nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
        pg_catalog.current_setting('request.jwt.claim.sub', true)
      ), '') is null
      or exists (
        select 1 from public.app_users au
        where au.igreja_id = agent_identity_proofs.igreja_id
          and au.id = agent_identity_proofs.confirmed_by_app_user_id
          and au.status = 'ativo'
          and au.clerk_user_id = nullif(coalesce(
            nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
            pg_catalog.current_setting('request.jwt.claim.sub', true)
          ), '')
      )
    )
  );

-- Only a locally verified panel subject can insert its own proof.  Worker
-- sessions deliberately have no matching policy, even with a tenant GUC.
drop policy if exists agent_identity_proofs_insert
  on public.agent_identity_proofs;
create policy agent_identity_proofs_insert
  on public.agent_identity_proofs for insert to authenticated
  with check (
    igreja_id = public.current_igreja_id()
    and nullif(coalesce(
      nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)
    ), '') is not null
    and exists (
      select 1
      from public.agent_identity_challenges c
      join public.conversations cv
        on cv.igreja_id = c.igreja_id and cv.id = c.conversation_id
      join public.app_users au
        on au.igreja_id = c.igreja_id and au.pessoa_id = c.pessoa_id
      where c.igreja_id = agent_identity_proofs.igreja_id
        and c.id = agent_identity_proofs.challenge_id
        and c.conversation_id = agent_identity_proofs.conversation_id
        and c.pessoa_id = agent_identity_proofs.pessoa_id
        and cv.pessoa_id = c.pessoa_id
        and au.id = agent_identity_proofs.confirmed_by_app_user_id
        and au.status = 'ativo'
        and au.clerk_user_id = nullif(coalesce(
          nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
          pg_catalog.current_setting('request.jwt.claim.sub', true)
        ), '')
        and c.challenge_expires_at > clock_timestamp()
        and not exists (
          select 1 from public.agent_identity_challenges newer
          where newer.igreja_id = c.igreja_id
            and newer.conversation_id = c.conversation_id
            and newer.sequence > c.sequence
        )
    )
  );

-- Proposals and receipts are backend worker artifacts. A panel JWT may read
-- neither tenant-wide operational context nor create a writer intent directly.
drop policy if exists agent_action_proposals_worker_only
  on public.agent_action_proposals;
create policy agent_action_proposals_worker_only
  on public.agent_action_proposals for all to authenticated
  using (
    igreja_id = public.current_igreja_id()
    and nullif(coalesce(
      nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)
    ), '') is null
  )
  with check (
    igreja_id = public.current_igreja_id()
    and nullif(coalesce(
      nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)
    ), '') is null
  );

drop policy if exists agent_action_receipts_worker_only
  on public.agent_action_receipts;
create policy agent_action_receipts_worker_only
  on public.agent_action_receipts for all to authenticated
  using (
    igreja_id = public.current_igreja_id()
    and nullif(coalesce(
      nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)
    ), '') is null
  )
  with check (
    igreja_id = public.current_igreja_id()
    and nullif(coalesce(
      nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)
    ), '') is null
  );

revoke all privileges on table public.agent_identity_challenges,
  public.agent_identity_proofs, public.agent_action_proposals,
  public.agent_action_receipts from public;

do $s3_privilege_acl$
declare
  target_role text;
begin
  foreach target_role in array array['anon', 'service_role', 'agent_runtime'] loop
    if pg_catalog.to_regrole(target_role) is not null then
      execute format(
        'revoke all privileges on table public.agent_identity_challenges, public.agent_identity_proofs, public.agent_action_proposals, public.agent_action_receipts from %I',
        target_role
      );
    end if;
  end loop;
  if pg_catalog.to_regrole('authenticated') is not null then
    execute 'grant select, insert on table public.agent_identity_challenges, public.agent_identity_proofs to authenticated';
    execute 'grant select, insert, update on table public.agent_action_proposals to authenticated';
    execute 'grant select, insert on table public.agent_action_receipts to authenticated';
  end if;
end
$s3_privilege_acl$;

do $s3_privilege_rls$
declare
  target_table regclass;
begin
  foreach target_table in array array[
    'public.agent_identity_challenges'::regclass,
    'public.agent_identity_proofs'::regclass,
    'public.agent_action_proposals'::regclass,
    'public.agent_action_receipts'::regclass,
    'public.messages'::regclass
  ] loop
    if not (select relrowsecurity from pg_catalog.pg_class where oid = target_table) then
      raise exception 'RLS desligada para %', target_table;
    end if;
  end loop;
  if not exists (
    select 1 from pg_catalog.pg_policy
    where polrelid = 'public.messages'::regclass
      and polname = 'tenant_isolation' and polcmd = '*'
  ) then
    raise exception 'policy tenant_isolation ausente em messages';
  end if;
end
$s3_privilege_rls$;

-- Rollback manual, somente após desligar runtime e rota. A remoção descarta
-- provas e propostas privadas, portanto não é uma compensação de efeitos de
-- domínio já executados. Ordem: receipts, proposals, proofs, challenges;
-- então a coluna/constraint de messages. Revogar grants antes dos DROPs se a
-- ferramenta de rollback exigir ACL explícita.
-- drop table public.agent_action_receipts;
-- drop table public.agent_action_proposals;
-- drop table public.agent_identity_proofs;
-- drop table public.agent_identity_challenges;
-- alter table public.messages
--   drop constraint if exists messages_agent_privilege_context_object_chk,
--   drop column if exists agent_privilege_context;

commit;
