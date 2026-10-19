-- Pastoral policy is provisional: active pastor; confirmed nominal leader only.
-- No release/tenant activation. Legacy history is conservatively protected from
-- its first prayer source onward: terminal timestamps were not persisted in V4.
begin;
set local lock_timeout = '2s';
create unique index if not exists prayer_proposal_tenant_conversation_id
 on public.pedido_oracao_proposta(igreja_id,conversation_id,id);
create table if not exists public.pedido_oracao_mensagem (
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 conversation_id uuid not null,
 -- Keep a content-free fence when request-only offboarding removes the proposal.
 proposal_id uuid,
 message_id uuid not null,
 primary key(igreja_id,message_id),
 foreign key(igreja_id,conversation_id,proposal_id)
  references public.pedido_oracao_proposta(igreja_id,conversation_id,id) on delete set null (proposal_id),
 foreign key(igreja_id,conversation_id,message_id)
  references public.messages(igreja_id,conversation_id,id) on delete cascade
);
create index if not exists prayer_message_proposal_idx on public.pedido_oracao_mensagem(igreja_id,proposal_id);
alter table public.pedido_oracao_mensagem enable row level security;
alter table public.pedido_oracao_mensagem force row level security;
revoke all on public.pedido_oracao_mensagem from public,anon,service_role,authenticated;
-- Association is trigger-owned. Panel cannot remove its privacy fence.
grant select on public.pedido_oracao_mensagem to authenticated;
create policy prayer_message_worker on public.pedido_oracao_mensagem for select to authenticated
 using(igreja_id=public.current_igreja_id() and public.prayer_jwt_sub() is null);

create function public.prayer_message_readable(tenant uuid, message uuid) returns boolean
language sql stable security definer set search_path=pg_catalog,public as $$
 select tenant=public.current_igreja_id() and (
  public.prayer_jwt_sub() is null or not exists (
   select 1 from public.pedido_oracao_mensagem pm
   left join public.pedido_oracao_proposta p on p.igreja_id=pm.igreja_id and p.id=pm.proposal_id
   where pm.igreja_id=tenant and pm.message_id=message
   and not (
    public.prayer_is_reader(tenant,null,'pastoral',null,null)
    or exists(select 1 from public.pedido_oracao r
      where r.igreja_id=tenant and r.proposal_id=p.id
      and public.prayer_is_reader(tenant,r.pessoa_id,r.audience,r.cell_id,r.leader_id))
   )
  )
 )
$$;
revoke all on function public.prayer_message_readable(uuid,uuid) from public,anon,service_role;
grant execute on function public.prayer_message_readable(uuid,uuid) to authenticated;
alter table public.messages enable row level security;
alter table public.messages force row level security;
-- Restrictive: cannot be bypassed by any existing permissive tenant policy.
create policy prayer_message_privacy on public.messages as restrictive for select to authenticated
 using(public.prayer_message_readable(igreja_id,id));

-- Capture new text/media only within the live collection window. Existing
-- associations survive cancellation/expiry. Ingestion takes the parent first;
-- metadata updates already hold Message, so never acquire its parent here.
create function public.prayer_bind_message() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
declare pid uuid; reply_pid uuid;
begin
 -- Human attendance is outside pastoral collection. Ordinary agent replies
 -- also remain outside it; only contact inbounds and prayer replies bind.
 if not ((new.direcao='in' and new.autor='contato') or
         (new.direcao='out' and new.autor='ia' and
          coalesce(new.agent_privilege_context->>'kind','')='prayer')) then
  return new;
 end if;
 if tg_op='INSERT' then
  perform 1 from public.conversations where igreja_id=new.igreja_id and id=new.conversation_id for update;
 end if;
 select p.id into pid from public.pedido_oracao_proposta p
  where p.igreja_id=new.igreja_id and p.conversation_id=new.conversation_id
  and p.state in ('collecting','pending') and p.expires_at>clock_timestamp() limit 1;
 if new.agent_privilege_context->>'kind'='prayer' then
  select p.id into reply_pid from public.pedido_oracao_proposta p
   where p.igreja_id=new.igreja_id and p.conversation_id=new.conversation_id
   and p.id::text=new.agent_privilege_context->>'proposal_id';
  if found then pid := reply_pid; end if;
 end if;
 if pid is not null then
  insert into public.pedido_oracao_mensagem values(new.igreja_id,new.conversation_id,pid,new.id)
   on conflict do nothing;
 end if;
 return new;
end $$;
revoke all on function public.prayer_bind_message() from public,anon,service_role;
create trigger prayer_bind_message after insert or update of agent_privilege_context on public.messages
 for each row execute function public.prayer_bind_message();

create function public.prayer_bind_source() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
begin
 insert into public.pedido_oracao_mensagem values(new.igreja_id,new.conversation_id,new.id,new.source_message_id)
  on conflict do nothing;
 update public.conversations set ultima_mensagem='Mensagem pastoral protegida'
  where igreja_id=new.igreja_id and id=new.conversation_id;
 return new;
end $$;
revoke all on function public.prayer_bind_source() from public,anon,service_role;
create trigger prayer_bind_source after insert on public.pedido_oracao_proposta
 for each row execute function public.prayer_bind_source();

-- Never store pastoral previews in the broadly accessible conversation row.
-- Deliberately conservative for conversations with protected history; the panel
-- uses the same neutral preview for every role.
create function public.prayer_safe_preview() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
begin
 if exists(select 1 from public.pedido_oracao_proposta p
  where p.igreja_id=new.igreja_id and p.conversation_id=new.id) then
  new.ultima_mensagem := 'Mensagem pastoral protegida';
 end if;
 return new;
end $$;
revoke all on function public.prayer_safe_preview() from public,anon,service_role;
create trigger prayer_safe_preview before update of ultima_mensagem on public.conversations
 for each row execute function public.prayer_safe_preview();

-- Uncertain legacy boundaries are pastor-only (NULL proposal); never infer
-- a leader share from chronology. Only explicit source/summary/SIM/context
-- evidence may inherit an existing confirmed audience.
insert into public.pedido_oracao_mensagem(igreja_id,conversation_id,proposal_id,message_id)
 select distinct on (m.igreja_id,m.id) m.igreja_id,m.conversation_id,
  case when m.id in (p.source_message_id,p.summary_message_id)
    or exists(select 1 from public.pedido_oracao r where r.igreja_id=p.igreja_id and r.proposal_id=p.id and r.confirmation_message_id=m.id)
    or (m.agent_privilege_context->>'kind'='prayer' and m.agent_privilege_context->>'proposal_id'=p.id::text)
   then p.id else null end,m.id
 from public.pedido_oracao_proposta p
 join public.messages source on source.igreja_id=p.igreja_id and source.conversation_id=p.conversation_id and source.id=p.source_message_id
 join public.messages m on m.igreja_id=p.igreja_id and m.conversation_id=p.conversation_id and m.criado_em>=source.criado_em
 order by m.igreja_id,m.id,source.criado_em desc
 on conflict do nothing;
update public.conversations c set ultima_mensagem='Mensagem pastoral protegida'
 where exists(select 1 from public.pedido_oracao_proposta p where p.igreja_id=c.igreja_id and p.conversation_id=c.id);

-- Content-free row allowlist for nonrecipients. The definer is required to
-- return placeholders for rows hidden by messages RLS. It never returns a
-- cross-tenant row or accepts a caller-supplied identity/recipient.
create function public.prayer_inbox_messages(conversation uuid) returns setof public.messages
language plpgsql stable security definer set search_path=pg_catalog,public as $$
declare m public.messages;
begin
 for m in select * from public.messages where igreja_id=public.current_igreja_id() and conversation_id=conversation loop
  if not public.prayer_message_readable(m.igreja_id,m.id) then
   m := jsonb_populate_record(null::public.messages,jsonb_build_object(
    'id',m.id,'igreja_id',m.igreja_id,'conversation_id',m.conversation_id,
    'direcao',m.direcao,'autor',m.autor,'criado_em',m.criado_em,
    'agent_reply_state',m.agent_reply_state,'tipo','texto','texto','Mensagem pastoral protegida'));
  end if;
  return next m;
 end loop;
end $$;
revoke all on function public.prayer_inbox_messages(uuid) from public,anon,service_role;
grant execute on function public.prayer_inbox_messages(uuid) to authenticated;
-- Preserve #509 receipts, authorization, generation fences and durable cleanup.
create or replace function public.private_delete_conversation(p_tenant uuid,p_conversation uuid) returns uuid
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
 -- Explicit child deletion also supports tenant-composite NO ACTION FKs.
 -- SECURITY DEFINER sees protected media for the durable queue above.
 delete from public.messages where igreja_id=p_tenant and conversation_id=p_conversation;
 delete from public.conversations where igreja_id=p_tenant and id=p_conversation;
 return v_id;
end $$;
revoke all on function public.private_delete_conversation(uuid,uuid) from public,anon,service_role;
grant execute on function public.private_delete_conversation(uuid,uuid) to authenticated;

commit;

-- ROLLBACK: roll back backend history query together with this schema.
-- Restore private_delete_conversation from 20261018_090000_exclusao_privada.sql
-- only after removing these associations; preserve #509 receipts/tasks.
-- Keep gates closed. Removing privacy
-- re-exposes history; require explicit privacy approval and retain associations until content is erased.
-- DROP FUNCTION public.prayer_inbox_messages(uuid);
-- DROP POLICY prayer_message_privacy ON public.messages;
-- DROP TRIGGER prayer_bind_message ON public.messages;
-- DROP TRIGGER prayer_bind_source ON public.pedido_oracao_proposta;
-- DROP TRIGGER prayer_safe_preview ON public.conversations;
-- DROP FUNCTION public.prayer_bind_message();
-- DROP FUNCTION public.prayer_bind_source();
-- DROP FUNCTION public.prayer_safe_preview();
-- DROP FUNCTION public.prayer_message_readable(uuid,uuid);
-- DROP TABLE public.pedido_oracao_mensagem;
-- DROP INDEX public.prayer_proposal_tenant_conversation_id;
-- Do not disable existing RLS or reconstruct old previews.
