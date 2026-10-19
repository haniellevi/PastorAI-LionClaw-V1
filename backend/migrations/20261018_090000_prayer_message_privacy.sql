-- Pastoral policy is provisional: active pastor; confirmed nominal leader only.
-- No release/tenant activation. Legacy history is conservatively protected from
-- its first prayer source onward: terminal timestamps were not persisted in V4.
begin;
set local lock_timeout = '2s';
create unique index if not exists prayer_proposal_tenant_conversation_id
 on public.pedido_oracao_proposta(igreja_id,conversation_id,id);
create table public.pedido_oracao_mensagem (
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
create index prayer_message_proposal_idx on public.pedido_oracao_mensagem(igreja_id,proposal_id);
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

-- Captures incoming text/media before ingestion commits, including ignored,
-- corrected, cancelled and timed-out turns. Lock order matches the worker.
create function public.prayer_bind_message() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
declare pid uuid;
begin
 perform 1 from public.conversations where igreja_id=new.igreja_id and id=new.conversation_id for update;
 select p.id into pid from public.pedido_oracao_proposta p
  where p.igreja_id=new.igreja_id and p.conversation_id=new.conversation_id
  and p.state in ('collecting','pending') limit 1;
 if new.agent_privilege_context->>'kind'='prayer' then
  select p.id into pid from public.pedido_oracao_proposta p
   where p.igreja_id=new.igreja_id and p.conversation_id=new.conversation_id
   and p.id::text=new.agent_privilege_context->>'proposal_id';
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
-- Admin erases without reading pastoral content. Paths are returned internally
-- only after deletion, for the existing post-commit Storage cleanup; never URLs.
create function public.delete_prayer_inbox_conversation(tenant uuid, conversation uuid)
returns text[] language plpgsql security definer set search_path=pg_catalog,public as $$
declare paths text[];
begin
 if tenant is null or tenant is distinct from public.current_igreja_id() or not exists(
  select 1 from public.app_users a join public.user_roles r on r.igreja_id=a.igreja_id and r.user_id=a.id
  where a.igreja_id=tenant and a.status='ativo' and a.clerk_user_id=public.prayer_jwt_sub() and r.papel='admin'
  and (a.pessoa_id is null or exists(select 1 from public.pessoas p where p.igreja_id=tenant and p.id=a.pessoa_id and p.arquivada_em is null))
 ) then raise exception 'conversation deletion denied' using errcode='42501'; end if;
 perform 1 from public.conversations where igreja_id=tenant and id=conversation for update;
 if not found then raise exception 'conversation not found' using errcode='42501'; end if;
 select coalesce(array_agg(media_path) filter(where media_path is not null),array[]::text[])
  into paths from public.messages where igreja_id=tenant and conversation_id=conversation;
 delete from public.conversations where igreja_id=tenant and id=conversation;
 return paths;
end $$;
revoke all on function public.delete_prayer_inbox_conversation(uuid,uuid) from public,anon,service_role;
grant execute on function public.delete_prayer_inbox_conversation(uuid,uuid) to authenticated;

commit;

-- ROLLBACK: keep gates closed. Removing privacy re-exposes history; require
-- explicit privacy approval and retain associations until content is erased.
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

-- DROP FUNCTION public.delete_prayer_inbox_conversation(uuid,uuid);
