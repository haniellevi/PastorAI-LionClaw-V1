-- Conversation privacy deletion. Apply before publishing the new writers/cron.
begin;
set local lock_timeout = '2s';
alter table public.conversations add column if not exists deletion_generation bigint not null default 0;

-- Deliberately no FK to igreja/conversation: cleanup and minimal tombstones must
-- survive source/tenant deletion. No text, phone, transcript or content hash here.
create table public.private_deletion_receipts (
 id uuid primary key default gen_random_uuid(),
 igreja_id uuid not null,
 scope text not null check(scope in ('conversa')),
 target_id uuid not null,
 generation bigint not null check(generation > 0),
 counts jsonb not null,
 created_at timestamptz not null default now(),
 unique(igreja_id,id), unique(igreja_id,scope,target_id)
);
create table public.private_deletion_tasks (
 id uuid primary key default gen_random_uuid(),
 igreja_id uuid not null,
 receipt_id uuid not null,
 source_id uuid not null,
 storage_path text,
 state text not null default 'pendente' check(state in ('pendente','concluida')),
 attempts integer not null default 0 check(attempts >= 0),
 error_code text check(error_code is null or error_code='storage_unavailable'),
 next_attempt_at timestamptz not null default now(),
 unique(igreja_id,receipt_id,source_id),
 foreign key(igreja_id,receipt_id) references public.private_deletion_receipts(igreja_id,id),
 check((state='concluida') = (storage_path is null)),
 check(storage_path is null or starts_with(storage_path,igreja_id::text||'/'))
);
create index private_deletion_tasks_pending on public.private_deletion_tasks(next_attempt_at,igreja_id) where state='pendente';

-- In-flight upload ownership survives lease expiry/process loss. Never conclude
-- its cleanup while an external call may still return. No content/path here.
create table public.private_deletion_uploads (
 igreja_id uuid not null,
 source_id uuid not null,
 conversation_id uuid not null,
 generation bigint not null,
 started_at timestamptz not null default now(),
 primary key(igreja_id,source_id)
);
-- Outbound ownership is committed with ia_em_transporte and survives deletion.
-- No payload/phone. A 60s no-resend window bounds lost-worker ownership.
create table public.private_deletion_sends (
 igreja_id uuid not null,
 source_id uuid not null,
 conversation_id uuid not null,
 generation bigint not null,
 started_at timestamptz not null default now(),
 expires_at timestamptz not null default (now()+interval '60 seconds'),
 primary key(igreja_id,source_id)
);
-- An opaque event revocation token prevents webhook replay. This is derived
-- solely from provider event identity, never text/media/transcript/content hash.
-- It is not a credential or authorization grant and carries no phone/provider ID.
create table public.private_deletion_event_fences (
 igreja_id uuid not null,
 event_token uuid not null,
 receipt_id uuid not null,
 primary key(igreja_id,event_token),
 foreign key(igreja_id,receipt_id) references public.private_deletion_receipts(igreja_id,id)
);
-- Only trusted backend sessions can use these tables. Workers have no JWT sub;
-- HTTP readers additionally need a current active admin binding in the database.
create function public.private_deletion_admin() returns boolean
language sql stable security definer set search_path=pg_catalog,public as $$
 select session_user not in ('authenticator','authenticated','anon') and exists(
  select 1 from public.app_users u join public.user_roles r on r.user_id=u.id and r.igreja_id=u.igreja_id
  where u.igreja_id=public.current_igreja_id() and u.status='ativo' and r.papel='admin'
   and u.clerk_user_id=coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',
                              nullif(current_setting('request.jwt.claim.sub',true),'')))
$$;
revoke all on function public.private_deletion_admin() from public,anon,service_role;
grant execute on function public.private_deletion_admin() to authenticated;
alter table public.private_deletion_receipts enable row level security;
alter table public.private_deletion_receipts force row level security;
alter table public.private_deletion_tasks enable row level security;
alter table public.private_deletion_tasks force row level security;
create policy receipt_read on public.private_deletion_receipts for select to authenticated
 using(igreja_id=public.current_igreja_id() and session_user not in ('authenticator','authenticated','anon') and
  (public.private_deletion_admin() or coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')=''));
create policy task_worker on public.private_deletion_tasks for all to authenticated
 using(igreja_id=public.current_igreja_id() and session_user not in ('authenticator','authenticated','anon') and
  coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='')
 with check(igreja_id=public.current_igreja_id() and session_user not in ('authenticator','authenticated','anon') and
  coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='');
alter table public.private_deletion_uploads enable row level security;
alter table public.private_deletion_uploads force row level security;
alter table public.private_deletion_event_fences enable row level security;
alter table public.private_deletion_event_fences force row level security;
create policy upload_worker on public.private_deletion_uploads for all to authenticated
 using(igreja_id=public.current_igreja_id() and session_user not in ('authenticator','authenticated','anon') and
  coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='')
 with check(igreja_id=public.current_igreja_id() and session_user not in ('authenticator','authenticated','anon') and
  coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='');
alter table public.private_deletion_sends enable row level security;
alter table public.private_deletion_sends force row level security;
create policy send_worker on public.private_deletion_sends for all to authenticated
 using(igreja_id=public.current_igreja_id() and session_user not in ('authenticator','authenticated','anon') and
  coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='')
 with check(igreja_id=public.current_igreja_id() and session_user not in ('authenticator','authenticated','anon') and
  coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='');
create policy send_admin_read on public.private_deletion_sends for select to authenticated
 using(igreja_id=public.current_igreja_id() and public.private_deletion_admin());
revoke all on public.private_deletion_sends from public,anon,authenticated,service_role;
grant select,insert,delete,update(expires_at) on public.private_deletion_sends to authenticated;
create policy fence_worker on public.private_deletion_event_fences for select to authenticated
 using(igreja_id=public.current_igreja_id() and session_user not in ('authenticator','authenticated','anon') and
  coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')='');
revoke all on public.private_deletion_uploads,public.private_deletion_event_fences from public,anon,authenticated,service_role;
grant select,insert,delete on public.private_deletion_uploads to authenticated;
grant select on public.private_deletion_event_fences to authenticated;
-- Admins may read progress, never the Storage path.
create policy task_admin_read on public.private_deletion_tasks for select to authenticated
 using(igreja_id=public.current_igreja_id() and public.private_deletion_admin());
revoke all on public.private_deletion_receipts,public.private_deletion_tasks from public,anon,authenticated,service_role;
grant select on public.private_deletion_receipts to authenticated;
grant select(id,igreja_id,receipt_id,source_id,state,attempts,error_code,next_attempt_at),
 update(state,storage_path,attempts,error_code,next_attempt_at) on public.private_deletion_tasks to authenticated;
-- The worker needs paths, exposed only through a worker-only function below.

create function public.private_delete_conversation(p_tenant uuid,p_conversation uuid) returns uuid
language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_id uuid; v_generation bigint; v_messages integer; v_audio integer; v_media integer; v_logs integer; v_sends integer;
begin
 if p_tenant is distinct from public.current_igreja_id() or not public.private_deletion_admin() then
  raise exception 'Exclusão não autorizada' using errcode='42501';
 end if;
 -- Shared lock order with inbox writers and V1b: conversation before audio.
 select deletion_generation+1 into v_generation from public.conversations
  where igreja_id=p_tenant and id=p_conversation for update;
 if not found then
  select id into v_id from public.private_deletion_receipts
   where igreja_id=p_tenant and scope='conversa' and target_id=p_conversation;
  return v_id;
 end if;
 update public.conversations set deletion_generation=v_generation where igreja_id=p_tenant and id=p_conversation;
 -- This row lock plus removal invalidates leases, including nullable live anchors.
 perform id from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
  (a.conversation_id=p_conversation or a.live_conversation_id=p_conversation or
   a.inbound_message_id in(select id from public.messages where igreja_id=p_tenant and conversation_id=p_conversation) or
   a.live_message_id in(select id from public.messages where igreja_id=p_tenant and conversation_id=p_conversation)) for update;
 select count(*) into v_messages from public.messages where igreja_id=p_tenant and conversation_id=p_conversation;
 select count(*) into v_audio from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
  (a.conversation_id=p_conversation or a.live_conversation_id=p_conversation or
   a.inbound_message_id in(select id from public.messages where igreja_id=p_tenant and conversation_id=p_conversation) or
   a.live_message_id in(select id from public.messages where igreja_id=p_tenant and conversation_id=p_conversation));
 delete from public.agent_conversation_logs where igreja_id=p_tenant and conversation_id=p_conversation;
 get diagnostics v_logs = row_count;
 select count(*) into v_sends from public.private_deletion_sends where igreja_id=p_tenant and conversation_id=p_conversation;
 insert into public.private_deletion_receipts(igreja_id,scope,target_id,generation,counts)
 values(p_tenant,'conversa',p_conversation,v_generation,jsonb_build_object('mensagens',v_messages,'transcricoes',v_audio,'resumos',0,'checkpoints',0,'vetores',0,'logs_agente',v_logs,'envios',v_sends)) returning id into v_id;
 insert into public.private_deletion_event_fences(igreja_id,event_token,receipt_id)
 select p_tenant,md5(p_tenant::text||':'||event_digest)::uuid,v_id from (
  select encode(sha256(convert_to(provider_message_id,'UTF8')),'hex') event_digest from public.messages
   where igreja_id=p_tenant and conversation_id=p_conversation and provider_message_id is not null
  union
  select provider_message_sha256 from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
   (a.conversation_id=p_conversation or a.live_conversation_id=p_conversation or
    a.inbound_message_id in(select id from public.messages where igreja_id=p_tenant and conversation_id=p_conversation) or
    a.live_message_id in(select id from public.messages where igreja_id=p_tenant and conversation_id=p_conversation))
 ) events on conflict(igreja_id,event_token) do nothing;
 -- Persist external work before deleting any source references. Prefer the V1b
 -- source id on shared paths so late-upload recovery finds the same task.
 insert into public.private_deletion_tasks(igreja_id,receipt_id,source_id,storage_path,next_attempt_at)
 select p_tenant,v_id,id,storage_path,ready_at from (
  select distinct on(storage_path) id,storage_path,ready_at from (
   select a.id,a.storage_path,coalesce(a.lease_until,now()) as ready_at,0 priority
    from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
    (a.conversation_id=p_conversation or a.live_conversation_id=p_conversation or
     a.inbound_message_id in(select id from public.messages where igreja_id=p_tenant and conversation_id=p_conversation) or
     a.live_message_id in(select id from public.messages where igreja_id=p_tenant and conversation_id=p_conversation))
   union all
   select id,media_path,now(),1 from public.messages where igreja_id=p_tenant and conversation_id=p_conversation and media_path is not null
  ) paths where storage_path is not null order by storage_path,priority
 ) objects;
 get diagnostics v_media = row_count;
 update public.private_deletion_receipts set counts=counts||jsonb_build_object('midias',v_media) where id=v_id;
 delete from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
  (a.conversation_id=p_conversation or a.live_conversation_id=p_conversation or
   a.inbound_message_id in(select id from public.messages where igreja_id=p_tenant and conversation_id=p_conversation) or
   a.live_message_id in(select id from public.messages where igreja_id=p_tenant and conversation_id=p_conversation));
 delete from public.conversations where igreja_id=p_tenant and id=p_conversation;
 return v_id;
end $$;
revoke all on function public.private_delete_conversation(uuid,uuid) from public,anon,service_role;
grant execute on function public.private_delete_conversation(uuid,uuid) to authenticated;

create function public.private_deletion_task_path(p_task uuid) returns text
language plpgsql stable security definer set search_path=pg_catalog,public as $$
begin
 if session_user in ('authenticator','authenticated','anon') or
  coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',nullif(current_setting('request.jwt.claim.sub',true),''),'')<>'' then
  raise exception 'Worker obrigatório' using errcode='42501';
 end if;
 return (select storage_path from public.private_deletion_tasks where id=p_task and igreja_id=public.current_igreja_id());
end $$;
revoke all on function public.private_deletion_task_path(uuid) from public,anon,service_role;
grant execute on function public.private_deletion_task_path(uuid) to authenticated;

-- Rollback: stop the new consumers, drain all tasks and preserve receipts first.
-- Never roll back after restoring private data without reapplying tombstones.
-- drop function public.private_deletion_task_path(uuid);
-- drop function public.private_delete_conversation(uuid,uuid);
-- drop table public.private_deletion_sends;
-- drop table public.private_deletion_uploads,public.private_deletion_event_fences;
-- drop table public.private_deletion_tasks;
-- drop table public.private_deletion_receipts;
-- drop function public.private_deletion_admin();
-- alter table public.conversations drop column deletion_generation;
commit;
