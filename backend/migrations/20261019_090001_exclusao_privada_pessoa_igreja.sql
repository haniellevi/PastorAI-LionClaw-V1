-- Private content erasure, not cadastral offboarding. Synthetic PG first.
begin;
set local lock_timeout='2s';
alter table public.private_deletion_receipts drop constraint private_deletion_receipts_scope_check;
alter table public.private_deletion_receipts add constraint private_deletion_receipts_scope_check check(scope in ('conversa','pessoa','igreja'));
alter table public.private_deletion_receipts add column operation_id uuid;
alter table public.private_deletion_receipts add column person_id uuid;
update public.private_deletion_receipts set operation_id=target_id;
alter table public.private_deletion_receipts alter column operation_id set not null;
alter table public.private_deletion_receipts drop constraint private_deletion_receipts_igreja_id_scope_target_id_key;
alter table public.private_deletion_receipts add unique(igreja_id,scope,target_id,operation_id);
create unique index private_deletion_conversation_once on public.private_deletion_receipts(igreja_id,target_id) where scope='conversa';
create table public.private_deletion_members(
 igreja_id uuid not null, receipt_id uuid not null, conversation_id uuid not null,
 primary key(igreja_id,receipt_id,conversation_id),
 foreign key(igreja_id,receipt_id) references public.private_deletion_receipts(igreja_id,id)
);
insert into public.private_deletion_members select igreja_id,id,target_id from public.private_deletion_receipts where scope='conversa';
alter table public.private_deletion_members enable row level security;
alter table public.private_deletion_members force row level security;
create policy member_read on public.private_deletion_members for select to authenticated
 using(igreja_id=public.current_igreja_id() and (public.private_deletion_admin() or
 (session_user not in ('authenticator','authenticated','anon') and public.prayer_jwt_sub() is null)));
revoke all on public.private_deletion_members from public,anon,authenticated,service_role;
grant select on public.private_deletion_members to authenticated;
-- Minimal links keep earlier cleanup in a later bulk receipt, without paths.
create table public.private_deletion_dependencies(
 igreja_id uuid not null, receipt_id uuid not null, dependency_id uuid not null,
 primary key(igreja_id,receipt_id,dependency_id), check(receipt_id<>dependency_id),
 foreign key(igreja_id,receipt_id) references public.private_deletion_receipts(igreja_id,id),
 foreign key(igreja_id,dependency_id) references public.private_deletion_receipts(igreja_id,id)
);
alter table public.private_deletion_dependencies enable row level security;
alter table public.private_deletion_dependencies force row level security;
create policy dependency_read on public.private_deletion_dependencies for select to authenticated
 using(igreja_id=public.current_igreja_id() and (public.private_deletion_admin() or
 (session_user not in ('authenticator','authenticated','anon') and public.prayer_jwt_sub() is null)));
revoke all on public.private_deletion_dependencies from public,anon,authenticated,service_role;
grant select on public.private_deletion_dependencies to authenticated;
-- Same canonical rules as app.domain.phone.normalize_phone: country prefix,
-- then the Brazilian mobile ninth digit. Never match only the last 8 digits.
create function public.private_deletion_phone_key(raw text) returns text
language sql immutable parallel safe set search_path=pg_catalog,public as $$
 with digits as (select regexp_replace(coalesce(raw,''),'\D','','g') as value),
 local_phone as (select case when length(value)>11 and starts_with(value,'55') then substr(value,3) else value end as value from digits)
 select case when length(value)=10 then substr(value,1,2)||'9'||substr(value,3) else value end from local_phone
$$;
revoke all on function public.private_deletion_phone_key(text) from public,anon,authenticated,service_role;
-- Internal entry point: SQL owner only. Both web wrapper and platform reset
-- call the same transaction, never a subject-less impersonation of an admin.
create function public.private_delete_content(p_tenant uuid,p_scope text,p_target uuid,p_operation uuid) returns uuid
language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_id uuid; v_generation bigint := 1; v_messages integer; v_audio integer; v_media integer; v_logs integer; v_sends integer;
 v_conversations uuid[]; v_inputs uuid[]; v_counts jsonb; v_table text; v_count integer;
begin
 if p_scope not in ('conversa','pessoa','igreja') or (p_scope='igreja' and p_target<>p_tenant) then
  raise exception 'Escopo inválido' using errcode='22023';
 end if;
 -- Ingestion takes the shared tenant barrier before touching Pessoa/conversa.
 -- Take this before any parent/child row lock, including from platform reset.
 perform pg_advisory_xact_lock(hashtextextended('private-content:'||p_tenant::text,0));
 -- Serialize retries and concurrent erasures of this target. No network in TX.
 perform pg_advisory_xact_lock(hashtextextended(p_tenant::text||p_scope||p_target::text,0));
 select id into v_id from public.private_deletion_receipts where igreja_id=p_tenant
  and scope=p_scope and target_id=p_target and operation_id=p_operation;
 if found then return v_id; end if;
 if p_scope='pessoa' then
  perform id from public.pessoas where igreja_id=p_tenant and id=p_target for key share;
 elsif p_scope='igreja' then
  perform id from public.igrejas where id=p_tenant for key share;
 else
  select deletion_generation+1 into v_generation from public.conversations
   where igreja_id=p_tenant and id=p_target for update;
 end if;
 if not found then
  if p_scope='conversa' then
   select id into v_id from public.private_deletion_receipts where igreja_id=p_tenant and scope=p_scope and target_id=p_target;
  end if;
  return v_id;
 end if;
 -- Shared ingestion barrier prevents new conversations during the snapshot.
 -- Parent KEY SHARE prevents cadastral removal without inverting worker locks.
 select coalesce(array_agg(id),'{}'::uuid[]) into v_conversations from public.conversations c where c.igreja_id=p_tenant and
  (p_scope='igreja' or (p_scope='conversa' and c.id=p_target) or (p_scope='pessoa' and (
   c.pessoa_id=p_target or c.id in(
    select conversation_id from public.pedido_oracao_proposta where igreja_id=p_tenant and pessoa_id=p_target
    union select conversation_id from public.pedido_oracao where igreja_id=p_tenant and pessoa_id=p_target
    union select conversation_id from public.agent_identity_challenges where igreja_id=p_tenant and pessoa_id=p_target
    union select conversation_id from public.agent_identity_proofs where igreja_id=p_tenant and pessoa_id=p_target
    union select conversation_id from public.agent_action_proposals where igreja_id=p_tenant and actor_pessoa_id=p_target
    union select conversation_id from public.cell_report_drafts where igreja_id=p_tenant and actor_pessoa_id=p_target
    union select conversation_id from public.cell_report_audio_inputs where igreja_id=p_tenant and (pessoa_id=p_target or live_pessoa_id=p_target)
    union select live_conversation_id from public.cell_report_audio_inputs where igreja_id=p_tenant and (pessoa_id=p_target or live_pessoa_id=p_target)
    union select conversation_id from public.cell_report_audio_notices where igreja_id=p_tenant and pessoa_id=p_target
    union select conversation_id from public.cell_report_audio_consent_events where igreja_id=p_tenant and pessoa_id=p_target
   ) or (c.pessoa_id is null and public.private_deletion_phone_key(c.telefone)<>'' and public.private_deletion_phone_key(c.telefone)=(
     select public.private_deletion_phone_key(telefone) from public.pessoas where igreja_id=p_tenant and id=p_target))
  )));
 perform id from public.conversations where igreja_id=p_tenant and id=any(v_conversations) order by id for update;
 update public.conversations set deletion_generation=deletion_generation+1 where igreja_id=p_tenant and id=any(v_conversations);
 select coalesce(array_agg(a.id),'{}'::uuid[]) into v_inputs from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
  (p_scope='igreja' or (p_scope='pessoa' and (a.pessoa_id=p_target or a.live_pessoa_id=p_target)) or
   a.conversation_id=any(v_conversations) or a.live_conversation_id=any(v_conversations) or
   a.inbound_message_id in(select id from public.messages where igreja_id=p_tenant and conversation_id=any(v_conversations)) or
   a.live_message_id in(select id from public.messages where igreja_id=p_tenant and conversation_id=any(v_conversations)));
 -- This row lock plus removal invalidates leases, including nullable live anchors.
 perform id from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
  a.id=any(v_inputs) for update;
 select count(*) into v_messages from public.messages where igreja_id=p_tenant and conversation_id=any(v_conversations);
 select count(*) filter(where a.transcript_text is not null) into v_audio from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
  a.id=any(v_inputs);
 delete from public.agent_conversation_logs where igreja_id=p_tenant and conversation_id=any(v_conversations);
 get diagnostics v_logs = row_count;
 select count(*) into v_sends from public.private_deletion_sends where igreja_id=p_tenant and conversation_id=any(v_conversations);
 insert into public.private_deletion_receipts(igreja_id,scope,target_id,generation,operation_id,counts)
 values(p_tenant,p_scope,p_target,v_generation,p_operation,jsonb_build_object('mensagens',v_messages,'transcricoes',v_audio,'resumos',0,'checkpoints',0,'vetores',0,'logs_agente',v_logs,'envios',v_sends)) returning id into v_id;
 update public.private_deletion_receipts set person_id=case when p_scope='pessoa' then p_target
  when p_scope='conversa' then (select pessoa_id from public.conversations where igreja_id=p_tenant and id=p_target) end where id=v_id;
 if p_scope<>'conversa' then
  -- Old conversation receipts predate person provenance: conservatively include
  -- their outstanding cleanup, rather than claim a complete erasure without it.
  insert into public.private_deletion_dependencies(igreja_id,receipt_id,dependency_id)
  select p_tenant,v_id,r.id from public.private_deletion_receipts r where r.igreja_id=p_tenant and r.id<>v_id
   and (p_scope='igreja' or r.person_id=p_target or r.person_id is null);
 end if;
 insert into public.private_deletion_members(igreja_id,receipt_id,conversation_id)
 select p_tenant,v_id,unnest(v_conversations);
 -- Enumerate all installed cascades before deleting their source anchors.
 v_counts := '{}'::jsonb;
 foreach v_table in array array['agent_identity_challenges','agent_identity_proofs','agent_action_proposals',
  'agent_action_receipts','cell_report_drafts','cell_report_audio_notices','cell_report_audio_consent_events',
  'pedido_oracao','pedido_oracao_proposta','pedido_oracao_mensagem'] loop
  if to_regclass('public.'||v_table) is null then continue; end if;
  execute format('select count(*) from public.%I where igreja_id=$1 and conversation_id=any($2)',v_table)
   into v_count using p_tenant,v_conversations;
  v_counts := v_counts || jsonb_build_object(v_table,v_count);
 end loop;
 select count(*) into v_count from public.cell_report_audio_inputs where igreja_id=p_tenant and id=any(v_inputs);
 v_counts := v_counts || jsonb_build_object('entradas_audio',v_count);
 -- Unanchored logs cannot prove personal ownership. Scrub payloads, retaining
 -- operational dedupe markers so deletion cannot cause a real-send retry.
 if p_scope in ('pessoa','igreja') then
  update public.agent_conversation_logs set payload=null where igreja_id=p_tenant and conversation_id is null and payload is not null;
  get diagnostics v_count = row_count;
  v_counts := v_counts || jsonb_build_object('logs_sem_ancora',v_count);
 end if;
 update public.private_deletion_receipts set counts=counts||v_counts where id=v_id;
 insert into public.private_deletion_event_fences(igreja_id,event_token,receipt_id)
 select p_tenant,md5(p_tenant::text||':'||event_digest)::uuid,v_id from (
  select encode(sha256(convert_to(provider_message_id,'UTF8')),'hex') event_digest from public.messages
   where igreja_id=p_tenant and conversation_id=any(v_conversations) and provider_message_id is not null
  union
  select provider_message_sha256 from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
   a.id=any(v_inputs)
 ) events on conflict(igreja_id,event_token) do nothing;
 -- Persist external work before deleting any source references. Prefer the V1b
 -- source id on shared paths so late-upload recovery finds the same task.
 insert into public.private_deletion_tasks(igreja_id,receipt_id,source_id,storage_path,next_attempt_at)
 select p_tenant,v_id,id,storage_path,ready_at from (
  select distinct on(storage_path) id,storage_path,ready_at from (
   select a.id,a.storage_path,coalesce(a.lease_until,now()) as ready_at,0 priority
    from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
    a.id=any(v_inputs)
   union all
   select id,media_path,now(),1 from public.messages where igreja_id=p_tenant and conversation_id=any(v_conversations) and media_path is not null
  ) paths where storage_path is not null order by storage_path,priority
 ) objects;
 get diagnostics v_media = row_count;
 update public.private_deletion_receipts set counts=counts||jsonb_build_object('midias',v_media) where id=v_id;
 delete from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
  a.id=any(v_inputs);
 -- Clear the entire offer state atomically to satisfy its CHECK and both
 -- tenant-composite NO ACTION message FKs, independently of fallback triggers.
 update public.conversations set secretaria_oferta_estado=null,
  secretaria_oferta_message_id=null, secretaria_oferta_expira_em=null,
  secretaria_oferta_resposta_message_id=null
 where igreja_id=p_tenant and id=any(v_conversations);
 -- Explicit deletion also supports protected inbox composite NO ACTION FKs.
 delete from public.messages where igreja_id=p_tenant and conversation_id=any(v_conversations);
 delete from public.conversations where igreja_id=p_tenant and id=any(v_conversations);
 return v_id;
end $$;

revoke all on function public.private_delete_content(uuid,text,uuid,uuid) from public,anon,authenticated,service_role;
create function public.private_delete_scope(p_tenant uuid,p_scope text,p_target uuid,p_operation uuid) returns uuid
language plpgsql security definer set search_path=pg_catalog,public as $$
begin
 if p_tenant is distinct from public.current_igreja_id() or not public.private_deletion_admin() then
  raise exception 'Exclusão não autorizada' using errcode='42501';
 end if;
 return public.private_delete_content(p_tenant,p_scope,p_target,p_operation);
end $$;
revoke all on function public.private_delete_scope(uuid,text,uuid,uuid) from public,anon,service_role;
grant execute on function public.private_delete_scope(uuid,text,uuid,uuid) to authenticated;
create or replace function public.private_delete_conversation(p_tenant uuid,p_conversation uuid) returns uuid
language sql security definer set search_path=pg_catalog,public as $$
 select public.private_delete_scope(p_tenant,'conversa',p_conversation,p_conversation)
$$;
-- Rollback: contain consumers; preserve receipts/fences and drain work first.
-- Cannot restore erased content. Reverse 20261019_090001 first: restore
-- private_delete_conversation from 20261018_120000_prayer_message_privacy.sql
-- while the prayer associations/RLS remain installed (not the #509 version).
-- Only when subsequently reversing 120000, follow its privacy rollback and
-- restore 20261018_090000_exclusao_privada.sql after removing associations.
-- Never replay 090000 over 120000 or this migration in the forward chain.
-- then DROP FUNCTION private_delete_scope(uuid,text,uuid,uuid);
-- DROP FUNCTION private_delete_content(uuid,text,uuid,uuid);
-- DROP FUNCTION private_deletion_phone_key(text);
-- DROP TABLE private_deletion_dependencies, private_deletion_members;
-- Retain bulk receipts; do not narrow scope/operation constraints until archived
-- under an approved retention procedure. No automatic tombstone expiry.
commit;
