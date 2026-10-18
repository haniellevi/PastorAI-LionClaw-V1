-- Enviar PR 2: decisões humanas e eventos privados, sem backfill ou promoção.
set lock_timeout='2s';
create unique index if not exists enviar_solicitacao_tenant_id on public.celula_solicitacao(igreja_id,id);
create table public.enviar_avaliacoes (
 id uuid primary key,
 igreja_id uuid not null references public.igrejas(id),
 pessoa_id uuid not null,
 decisao text not null check(decisao in ('apto','nao_apto')),
 origem text not null check(origem in ('avaliacao','legado','csim')),
 motivo text not null check(length(btrim(motivo)) between 1 and 300),
 autor_id uuid not null,
 solicitacao_id uuid,
 solicitante_id uuid,
 evidencias jsonb not null check(jsonb_typeof(evidencias)='object'),
 versao_regras text not null check(length(btrim(versao_regras))>0),
 criada_em timestamptz not null default clock_timestamp(),
 check(origem<>'csim' or decisao='nao_apto'),
 check(solicitacao_id is not null or solicitante_id is null),
 unique(igreja_id,id),
 foreign key(igreja_id,pessoa_id) references public.pessoas(igreja_id,id) on delete cascade,
 foreign key(igreja_id,autor_id) references public.app_users(igreja_id,id),
 foreign key(igreja_id,solicitante_id) references public.pessoas(igreja_id,id),
 foreign key(igreja_id,solicitacao_id) references public.celula_solicitacao(igreja_id,id)
);
create index enviar_avaliacoes_pessoa on public.enviar_avaliacoes(igreja_id,pessoa_id,criada_em desc,id);
create table public.enviar_eventos (
 id uuid primary key default gen_random_uuid(),
 igreja_id uuid not null references public.igrejas(id),
 avaliacao_id uuid not null,
 tipo text not null check(tipo in ('decisao_humana','sistema_csim')),
 criada_em timestamptz not null default clock_timestamp(),
 unique(igreja_id,avaliacao_id),
 foreign key(igreja_id,avaliacao_id) references public.enviar_avaliacoes(igreja_id,id) on delete cascade
);
create function public.enviar_preservar_registro() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 -- Only the existing privileged parent-deletion flow may remove private data.
 -- Direct UPDATE/DELETE remains forbidden, including by the owner. No tenant
 -- role or GUC alone can authorize this exception.
 if TG_OP='DELETE' and pg_trigger_depth()>1
    and session_user not in ('authenticated','anon','authenticator')
    and coalesce(current_setting('role',true),'none') not in ('authenticated','anon','authenticator') then
  if TG_TABLE_NAME='enviar_avaliacoes' then
   if not exists(select 1 from public.pessoas p where p.igreja_id=old.igreja_id and p.id=old.pessoa_id) then
    return old;
   end if;
  elsif TG_TABLE_NAME='enviar_eventos' then
   if not exists(select 1 from public.enviar_avaliacoes a where a.igreja_id=old.igreja_id and a.id=old.avaliacao_id) then
    return old;
   end if;
  end if;
 end if;
 raise exception 'Registro de Enviar imutável' using errcode='23514';
end $$;
-- The trigger alone creates events; HTTP/database tenant roles cannot forge them.
create function public.enviar_registrar_evento() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
begin
 insert into public.enviar_eventos(igreja_id,avaliacao_id,tipo)
 values(new.igreja_id,new.id,case when new.origem='csim' then 'sistema_csim' else 'decisao_humana' end);
 return new;
end $$;
revoke all on function public.enviar_preservar_registro(),public.enviar_registrar_evento() from public,anon,authenticated,service_role;
create trigger enviar_avaliacao_evento after insert on public.enviar_avaliacoes
 for each row execute function public.enviar_registrar_evento();
do $$ declare t text; begin
 foreach t in array array['enviar_avaliacoes','enviar_eventos'] loop
  execute format('create trigger enviar_imutavel before update or delete on public.%I for each row execute function public.enviar_preservar_registro()',t);
  execute format('alter table public.%I enable row level security',t);
  execute format('alter table public.%I force row level security',t);
  execute format('create policy tenant_isolation on public.%I for all to authenticated using(igreja_id=public.current_igreja_id() and igreja_id=nullif(current_setting(''app.tenant_igreja_id'',true),'''')::uuid and session_user not in (''authenticator'',''authenticated'',''anon'')) with check(igreja_id=public.current_igreja_id() and igreja_id=nullif(current_setting(''app.tenant_igreja_id'',true),'''')::uuid and session_user not in (''authenticator'',''authenticated'',''anon''))',t);
  execute format('revoke all on public.%I from public,anon,authenticated,service_role',t);
  execute format('grant select on public.%I to authenticated',t);
 end loop;
end $$;
grant insert(id,igreja_id,pessoa_id,decisao,origem,motivo,autor_id,solicitacao_id,solicitante_id,evidencias,versao_regras) on public.enviar_avaliacoes to authenticated;
-- Rollback: restore previous callers first; preserve decisions/events under the
-- approved privacy procedure before removing this schema. No automatic rollback.
-- drop table public.enviar_eventos;
-- drop trigger enviar_avaliacao_evento on public.enviar_avaliacoes;
-- drop table public.enviar_avaliacoes;
-- drop function public.enviar_registrar_evento(),public.enviar_preservar_registro();
-- drop index public.enviar_solicitacao_tenant_id;
