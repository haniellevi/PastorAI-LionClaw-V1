-- Audio prayer collections are pastor-only, including legacy leader shares.
-- No gate, TTL, new storage table, transcription or external effect.
begin;
set local lock_timeout = '2s';
-- Inspect associations as the function owner: caller RLS deliberately hides
-- these messages/proposals, so an invoker subquery would authorize by absence.
create or replace function public.prayer_proposal_has_audio(tenant uuid, proposal uuid)
returns boolean language sql stable security definer set search_path=pg_catalog,public as $$
 select tenant is distinct from public.current_igreja_id() or exists (
  select 1 from public.messages m
  where m.igreja_id=tenant and m.tipo='audio' and (
   exists(select 1 from public.pedido_oracao_mensagem pm
    where pm.igreja_id=tenant and pm.proposal_id=proposal and pm.message_id=m.id)
   or exists(select 1 from public.pedido_oracao_proposta p
    where p.igreja_id=tenant and p.id=proposal and p.source_message_id=m.id)
  )
 )
$$;
revoke all on function public.prayer_proposal_has_audio(uuid,uuid) from public,anon,service_role;
grant execute on function public.prayer_proposal_has_audio(uuid,uuid) to authenticated;

drop policy if exists prayer_request_read on public.pedido_oracao;
create policy prayer_request_read on public.pedido_oracao for select to authenticated
 using(igreja_id=public.current_igreja_id() and (public.prayer_jwt_sub() is null
  or (public.prayer_is_reader(igreja_id,pessoa_id,audience,cell_id,leader_id)
   and (public.prayer_is_reader(igreja_id,null,'pastoral',null,null)
    or not public.prayer_proposal_has_audio(igreja_id,proposal_id)))));

drop policy if exists prayer_request_update on public.pedido_oracao;
create policy prayer_request_update on public.pedido_oracao for update to authenticated
 using(igreja_id=public.current_igreja_id()
  and public.prayer_is_reader(igreja_id,pessoa_id,audience,cell_id,leader_id)
  and (public.prayer_is_reader(igreja_id,null,'pastoral',null,null)
   or not public.prayer_proposal_has_audio(igreja_id,proposal_id)))
 with check(igreja_id=public.current_igreja_id()
  and public.prayer_is_reader(igreja_id,pessoa_id,audience,cell_id,leader_id)
  and (public.prayer_is_reader(igreja_id,null,'pastoral',null,null)
   or not public.prayer_proposal_has_audio(igreja_id,proposal_id)));

create or replace function public.prayer_message_readable(tenant uuid, message uuid) returns boolean
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
      and public.prayer_is_reader(tenant,r.pessoa_id,r.audience,r.cell_id,r.leader_id)
      and not public.prayer_proposal_has_audio(tenant,p.id))
   )
  )
 )
$$;
revoke all on function public.prayer_message_readable(uuid,uuid) from public,anon,service_role;
grant execute on function public.prayer_message_readable(uuid,uuid) to authenticated;
commit;

-- Rollback: restore prayer_request_read and prayer_request_update from
-- 20261016_180000_prayer_requests.sql,
-- then restore prayer_message_readable(uuid,uuid) from
-- 20261018_120000_prayer_message_privacy.sql only after pastoral approval.
-- This restores legacy leader reads/updates; never remove associations or audio files.

-- After restoring all callers, drop prayer_proposal_has_audio(uuid,uuid).
