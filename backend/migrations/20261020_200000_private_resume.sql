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
   and exists(select 1 from public.private_summary_settings cfg where cfg.igreja_id=new.igreja_id and cfg.resume_enabled)
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
