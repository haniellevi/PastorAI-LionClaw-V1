-- Pending self erasure suspends memory; only a live web admin decides.
-- No content, phone, hashes or free-form reason in this audit ledger.
begin;
set local lock_timeout='2s';
create table public.private_erasure_request_settings (
 igreja_id uuid primary key references public.igrejas(id) on delete cascade,
 enabled boolean not null default false
);
-- No source FKs: approval deletes conversations; audit must survive that deletion.
create table public.private_erasure_requests (
 id uuid primary key default gen_random_uuid(),
 igreja_id uuid not null,
 pessoa_id uuid not null,
 conversation_id uuid not null,
 inbound_id uuid not null,
 state text not null default 'pendente' check(state in ('pendente','aprovado','recusado')),
 created_at timestamptz not null default now(),
 decided_at timestamptz,
 decided_by uuid,
 receipt_id uuid,
 unique(igreja_id,id),unique(igreja_id,inbound_id),
 check((state='pendente')=(decided_at is null)),
 check((state='pendente')=(decided_by is null)),
 check((state='aprovado')=(receipt_id is not null))
);
-- Every accepted inbound stays idempotent, including commands coalesced into
-- an already pending request, even after that request is refused.
create table public.private_erasure_request_inbounds (
 igreja_id uuid not null,
 inbound_id uuid not null,
 request_id uuid not null,
 primary key(igreja_id,inbound_id),
 foreign key(igreja_id,request_id) references public.private_erasure_requests(igreja_id,id)
);
alter table public.private_erasure_request_inbounds enable row level security;
alter table public.private_erasure_request_inbounds force row level security;
revoke all on public.private_erasure_request_inbounds from public,anon,authenticated,service_role;
grant select on public.private_erasure_request_inbounds to authenticated;
create unique index private_erasure_one_pending on public.private_erasure_requests(igreja_id,pessoa_id) where state='pendente';
alter table public.private_erasure_requests enable row level security;
alter table public.private_erasure_requests force row level security;
alter table public.private_erasure_request_settings enable row level security;
alter table public.private_erasure_request_settings force row level security;
revoke all on public.private_erasure_requests,public.private_erasure_request_settings from public,anon,authenticated,service_role;
grant select on public.private_erasure_requests,public.private_erasure_request_settings to authenticated;
create function public.private_erasure_admin() returns boolean
language sql stable security definer set search_path=pg_catalog,public as $$
 select public.private_deletion_admin() and exists(select 1 from public.app_users a
 where a.igreja_id=public.current_igreja_id() and a.clerk_user_id=public.prayer_jwt_sub()
 and a.status='ativo' and (a.pessoa_id is null or exists(select 1 from public.pessoas p
 where p.igreja_id=a.igreja_id and p.id=a.pessoa_id and p.arquivada_em is null)))
$$;
revoke all on function public.private_erasure_admin() from public,anon,authenticated,service_role;
grant execute on function public.private_erasure_admin() to authenticated;
create policy request_reader on public.private_erasure_requests for select to authenticated using(
 igreja_id=public.current_igreja_id() and (public.private_summary_worker() or public.private_erasure_admin()));
create policy request_inbound_reader on public.private_erasure_request_inbounds for select to authenticated using(
 igreja_id=public.current_igreja_id() and (public.private_summary_worker() or public.private_erasure_admin()));
create policy request_settings_reader on public.private_erasure_request_settings for select to authenticated using(igreja_id=public.current_igreja_id());

create function public.private_memory_pending(t uuid,p uuid) returns boolean
language sql stable security definer set search_path=pg_catalog,public as $$
 select t=public.current_igreja_id() and exists(select 1 from public.private_erasure_requests
 where igreja_id=t and pessoa_id=p and state='pendente')
$$;
revoke all on function public.private_memory_pending(uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.private_memory_pending(uuid,uuid) to authenticated;
-- Defense in depth for direct worker/admin SELECT and for future consumers.
create policy request_suspends_summary on public.private_conversation_summaries as restrictive for select to authenticated
 using(not public.private_memory_pending(igreja_id,pessoa_id));
create policy request_suspends_sources on public.private_summary_sources as restrictive for select to authenticated
 using(not exists(select 1 from public.conversations c where c.igreja_id=private_summary_sources.igreja_id
 and c.id=private_summary_sources.conversation_id and public.private_memory_pending(c.igreja_id,c.pessoa_id)));

create function public.private_erasure_request(t uuid,p uuid,c uuid,m uuid) returns uuid
language plpgsql security definer set search_path=pg_catalog,public as $$
declare result uuid;
begin
 if t is distinct from public.current_igreja_id() or not public.private_summary_worker()
 or not exists(select 1 from public.private_erasure_request_settings where igreja_id=t and enabled) then
  raise exception 'Request unavailable' using errcode='42501';
 end if;
 perform pg_advisory_xact_lock(hashtextextended('private-content:'||t::text,0));
 -- A worker passes IDs revalidated from inbound, never identity from a model.
 if not exists(select 1 from public.conversations cv join public.pessoas person on person.igreja_id=t and person.id=cv.pessoa_id
 join public.messages msg on msg.igreja_id=t and msg.conversation_id=cv.id and msg.id=m
 where cv.igreja_id=t and cv.id=c and cv.pessoa_id=p and cv.numero_oficial and cv.estado='ia'
 and person.arquivada_em is null and not person.optout and not person.sem_interesse
 and public.private_deletion_phone_key(cv.telefone)<>''
 and public.private_deletion_phone_key(cv.telefone)=public.private_deletion_phone_key(person.telefone)
 and (select count(*) from public.pessoas peers where peers.igreja_id=t and peers.arquivada_em is null
 and public.private_deletion_phone_key(peers.telefone)=public.private_deletion_phone_key(cv.telefone))=1
 and msg.direcao='in' and msg.autor='contato' and coalesce(msg.tipo,'texto')='texto' and msg.media_path is null
 and msg.media_mime is null and msg.media_nome is null and msg.media_tamanho is null
 and msg.texto='QUERO SOLICITAR EXCLUSAO DO MEU CONTEUDO PRIVADO') then
  raise exception 'Request identity invalid' using errcode='42501';
 end if;
 select request_id into result from public.private_erasure_request_inbounds where igreja_id=t and inbound_id=m;
 if found then return result; end if;
 select id into result from public.private_erasure_requests where igreja_id=t and pessoa_id=p and state='pendente';
 if not found then
  insert into public.private_erasure_requests(igreja_id,pessoa_id,conversation_id,inbound_id) values(t,p,c,m) returning id into result;
 end if;
 insert into public.private_erasure_request_inbounds(igreja_id,inbound_id,request_id) values(t,m,result);
 return result;
end $$;

create function public.private_erasure_decide(r uuid,decision text) returns uuid
language plpgsql security definer set search_path=pg_catalog,public as $$
declare t uuid:=public.current_igreja_id(); row public.private_erasure_requests; actor uuid; rid uuid;
begin
 if decision not in ('aprovado','recusado') then raise exception 'Invalid decision' using errcode='22023'; end if;
 perform pg_advisory_xact_lock(hashtextextended('private-content:'||t::text,0));
 if not public.private_erasure_admin() then raise exception 'Web admin required' using errcode='42501'; end if;
 select * into row from public.private_erasure_requests where igreja_id=t and id=r for update;
 if not found then return null; end if;
 if row.state<>'pendente' then
  if row.state<>decision then raise exception 'Decision conflict' using errcode='22023'; end if;
  return row.id;
 end if;
 select id into actor from public.app_users where igreja_id=t and clerk_user_id=public.prayer_jwt_sub() and status='ativo';
 if actor is null then raise exception 'Active web admin required' using errcode='42501'; end if;
 if decision='aprovado' then
  rid:=public.private_delete_scope(t,'pessoa',row.pessoa_id,row.id);
  if rid is null then raise exception 'Erasure target unavailable' using errcode='22023'; end if;
 end if;
 update public.private_erasure_requests set state=decision,decided_at=now(),decided_by=actor,receipt_id=rid where igreja_id=t and id=r;
 return r;
end $$;
revoke all on function public.private_erasure_request(uuid,uuid,uuid,uuid),public.private_erasure_decide(uuid,text) from public,anon,authenticated,service_role;
grant execute on function public.private_erasure_request(uuid,uuid,uuid,uuid),public.private_erasure_decide(uuid,text) to authenticated;

create or replace function public.private_summary_origin_valid(t uuid,c uuid,p uuid) returns boolean
language sql stable security definer set search_path=pg_catalog,public as $$
 select not public.private_memory_pending(t,p) and t=public.current_igreja_id() and (public.private_summary_worker() or public.private_summary_reader(t,c)) and exists(
 select 1 from public.conversations cv join public.pessoas person on person.igreja_id=cv.igreja_id and person.id=cv.pessoa_id
 where cv.igreja_id=t and cv.id=c and cv.pessoa_id=p and person.arquivada_em is null and not person.optout
 and public.private_deletion_phone_key(cv.telefone)<>''
 and public.private_deletion_phone_key(cv.telefone)=public.private_deletion_phone_key(person.telefone)
 and (select count(*) from public.pessoas peers where peers.igreja_id=t and peers.arquivada_em is null
  and public.private_deletion_phone_key(peers.telefone)=public.private_deletion_phone_key(cv.telefone))=1
 and (select count(*) from public.messages m where m.igreja_id=t and m.conversation_id=c) between 1 and 40
 and not exists(select 1 from public.messages m where m.igreja_id=t and m.conversation_id=c and (
   m.direcao<>'in' or m.autor<>'contato' or coalesce(m.tipo,'texto')<>'texto' or m.media_path is not null
   or m.agent_privilege_context is not null or public.private_summary_topic(m.texto) is null))
 and not exists(select 1 from public.pedido_oracao_mensagem pm where pm.igreja_id=t and pm.conversation_id=c)
 and not exists(select 1 from public.pedido_oracao_proposta pr where pr.igreja_id=t and pr.conversation_id=c)
 and not exists(select 1 from public.cell_report_audio_inputs ai where ai.igreja_id=t and (ai.conversation_id=c or ai.live_conversation_id=c))
 )
$$;

commit;
-- Rollback: close feature gates and stop consumers first. Preserve requests,
-- decisions and deletion receipts; never drop a pending suspension silently.
-- Refuse rollback while any request is pending; complete/reconcile media tasks.
-- Restore private_summary_origin_valid from 20261019_120001 only after that.
-- DROP POLICY request_suspends_sources ON public.private_summary_sources;
-- DROP POLICY request_suspends_summary ON public.private_conversation_summaries;
-- DROP FUNCTION public.private_erasure_decide(uuid,text),public.private_erasure_request(uuid,uuid,uuid,uuid);
-- DROP TABLE public.private_erasure_request_inbounds,public.private_erasure_requests,public.private_erasure_request_settings;
-- DROP FUNCTION public.private_memory_pending(uuid,uuid),public.private_erasure_admin();
