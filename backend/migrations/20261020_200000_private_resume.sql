begin;
set local lock_timeout='2s';

create or replace function public.private_summary_origin_valid(t uuid,c uuid,p uuid,sources_only boolean) returns boolean
language sql stable security definer set search_path=pg_catalog,public as $$
 -- Generation validates the complete conversation. Resume validates the saved
 -- source set; its caller separately fences the command/reservation/history.
 with origin_messages as (
  select m.* from public.messages m where m.igreja_id=t and m.conversation_id=c
  and (not sources_only or exists(select 1 from public.private_summary_sources src
   where src.igreja_id=t and src.conversation_id=c and src.message_id=m.id))
 )
 select t=public.current_igreja_id() and (not sources_only or public.private_summary_worker()) and (public.private_summary_worker() or public.private_summary_reader(t,c)) and exists(
 select 1 from public.conversations cv join public.pessoas person on person.igreja_id=cv.igreja_id and person.id=cv.pessoa_id
 where cv.igreja_id=t and cv.id=c and cv.pessoa_id=p and person.arquivada_em is null and not person.optout
 and public.private_deletion_phone_key(cv.telefone)<>''
 and public.private_deletion_phone_key(cv.telefone)=public.private_deletion_phone_key(person.telefone)
 and (select count(*) from public.pessoas peers where peers.igreja_id=t and peers.arquivada_em is null
  and public.private_deletion_phone_key(peers.telefone)=public.private_deletion_phone_key(cv.telefone))=1
 and (select count(*) from origin_messages) between 1 and 40
 and not exists(select 1 from origin_messages m where (
   m.direcao<>'in' or m.autor<>'contato' or coalesce(m.tipo,'texto')<>'texto' or m.media_path is not null
   or m.agent_privilege_context is not null or public.private_summary_topic(m.texto) is null))
 and not exists(select 1 from public.pedido_oracao_mensagem pm where pm.igreja_id=t and pm.conversation_id=c)
 and not exists(select 1 from public.pedido_oracao_proposta pr where pr.igreja_id=t and pr.conversation_id=c)
 and not exists(select 1 from public.cell_report_audio_inputs ai where ai.igreja_id=t and (ai.conversation_id=c or ai.live_conversation_id=c))
 )
$$;
-- Keep all existing callers strict and preserve the original function ACL.
create or replace function public.private_summary_origin_valid(t uuid,c uuid,p uuid) returns boolean
language sql stable security definer set search_path=pg_catalog,public as $$
 select public.private_summary_origin_valid(t,c,p,false)
$$;
-- The source-only variant is private to the trusted worker / original validator.
revoke all on function public.private_summary_origin_valid(uuid,uuid,uuid,boolean) from public,anon,authenticated,service_role;
grant execute on function public.private_summary_origin_valid(uuid,uuid,uuid,boolean) to authenticated;

-- Explicit, private reconstruction only. Default closed; no activation API.
-- Existing igreja_id policies remain unchanged and FORCE RLS stays mandatory.
alter table public.private_summary_settings add column resume_enabled boolean not null default false;
alter table public.private_summary_settings enable row level security;
alter table public.private_summary_settings force row level security;

create or replace function public.private_summary_source_changed() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
declare t uuid; c uuid; destructive boolean:=false;
begin
 -- Retomada is an explicit read, not a new summary source. A reservation
 -- carries no content. All updates, ordinary inputs and protection still
 -- invalidate normally; no suspended summary is revived here.
 if tg_table_name='messages' and tg_op='INSERT' then
  if coalesce(new.tipo,'texto')='texto' and new.media_path is null
   and new.agent_privilege_context is null
   and exists(select 1 from public.private_summary_settings cfg where cfg.igreja_id=new.igreja_id and cfg.enabled and cfg.resume_enabled)
   and ((new.direcao='in' and new.autor='contato' and new.texto='retomar conversa')
     or (new.direcao='out' and new.autor='ia' and new.texto is null and new.agent_reply_state='ia_reservada'))
  then return new; end if;
 end if;
 if tg_op='DELETE' then t:=old.igreja_id; c:=old.conversation_id; destructive:=true;
 else t:=new.igreja_id; c:=new.conversation_id; end if;
 if tg_table_name in ('pedido_oracao_mensagem','pedido_oracao_proposta','cell_report_audio_inputs') then destructive:=true; end if;
 if tg_table_name='messages' and tg_op<>'DELETE' then
  destructive:=destructive or coalesce(new.tipo,'texto')<>'texto' or new.media_path is not null;
 end if;
 update public.conversations set private_summary_revision=private_summary_revision+1 where igreja_id=t and id=c;
 if destructive then delete from public.private_conversation_summaries where igreja_id=t and conversation_id=c;
 else
 update public.private_conversation_summaries set summary=null,state=case when state='incorrect' then state else 'suspended' end
 where igreja_id=t and conversation_id=c;
 end if;
 delete from public.private_summary_tasks where igreja_id=t and conversation_id=c;
 if tg_table_name='cell_report_audio_inputs' then
  -- Retained origin and live anchor can both carry private derivatives.
  update public.conversations set private_summary_revision=private_summary_revision+1
   where igreja_id=t and id=new.live_conversation_id and id<>c;
  delete from public.private_conversation_summaries where igreja_id=t and conversation_id=new.live_conversation_id;
  delete from public.private_summary_tasks where igreja_id=t and conversation_id=new.live_conversation_id;
 end if;
 if tg_op='DELETE' then return old; end if; return new;
end $$;

commit;

-- Rollback: contain consumers first; restore the previous invalidation function.
-- create or replace function public.private_summary_source_changed() returns trigger
-- language plpgsql security definer set search_path=pg_catalog,public as $$
-- declare t uuid; c uuid; destructive boolean:=false;
-- begin
--  if tg_op='DELETE' then t:=old.igreja_id; c:=old.conversation_id; destructive:=true;
--  else t:=new.igreja_id; c:=new.conversation_id; end if;
--  if tg_table_name in ('pedido_oracao_mensagem','pedido_oracao_proposta','cell_report_audio_inputs') then destructive:=true; end if;
--  if tg_table_name='messages' and tg_op<>'DELETE' then
--   destructive:=destructive or coalesce(new.tipo,'texto')<>'texto' or new.media_path is not null;
--  end if;
--  update public.conversations set private_summary_revision=private_summary_revision+1 where igreja_id=t and id=c;
--  if destructive then delete from public.private_conversation_summaries where igreja_id=t and conversation_id=c;
--  else
--  update public.private_conversation_summaries set summary=null,state=case when state='incorrect' then state else 'suspended' end
--  where igreja_id=t and conversation_id=c;
--  end if;
--  delete from public.private_summary_tasks where igreja_id=t and conversation_id=c;
--  if tg_table_name='cell_report_audio_inputs' then
--   -- Retained origin and live anchor can both carry private derivatives.
--   update public.conversations set private_summary_revision=private_summary_revision+1
--    where igreja_id=t and id=new.live_conversation_id and id<>c;
--   delete from public.private_conversation_summaries where igreja_id=t and conversation_id=new.live_conversation_id;
--   delete from public.private_summary_tasks where igreja_id=t and conversation_id=new.live_conversation_id;
--  end if;
--  if tg_op='DELETE' then return old; end if; return new;
-- end $$;
-- ALTER TABLE public.private_summary_settings DROP COLUMN resume_enabled;

-- Restore private_summary_origin_valid(uuid,uuid,uuid) from migration
-- 20261019_120001_private_conversation_summaries.sql before dropping the overload:
-- DROP FUNCTION public.private_summary_origin_valid(uuid,uuid,uuid,boolean);
