-- Audio prayer collections are pastor-only, including legacy leader shares.
-- No gate, TTL, new storage table, transcription or external effect.
begin;
set local lock_timeout = '2s';
alter table public.messages enable row level security;
alter table public.messages force row level security;
alter table public.pedido_oracao_mensagem enable row level security;
alter table public.pedido_oracao_mensagem force row level security;
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
      and not exists (
       select 1 from public.pedido_oracao_mensagem audio_pm
       join public.messages audio_m on audio_m.igreja_id=audio_pm.igreja_id and audio_m.id=audio_pm.message_id
       where audio_pm.igreja_id=tenant and audio_pm.proposal_id=p.id and audio_m.tipo='audio'
      ))
   )
  )
 )
$$;
revoke all on function public.prayer_message_readable(uuid,uuid) from public,anon,service_role;
grant execute on function public.prayer_message_readable(uuid,uuid) to authenticated;
commit;

-- Rollback: restore prayer_message_readable(uuid,uuid) from
-- 20261018_120000_prayer_message_privacy.sql only after pastoral approval.
-- This restores legacy leader reads; never remove associations or audio files.
