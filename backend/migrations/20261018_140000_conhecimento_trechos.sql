-- PR3: lexical only; no external provider, ingestion or activation.
set local lock_timeout='2s';
do $$ begin
 if exists(select 1 from pg_available_extensions where name='unaccent') then
   create extension if not exists unaccent;
 end if;
end $$;
create text search configuration public.conhecimento_portuguese (copy=pg_catalog.portuguese);
do $$ declare dictionary_name text; begin
 select format('%I.%I',n.nspname,d.dictname) into dictionary_name
 from pg_ts_dict d join pg_namespace n on n.oid=d.dictnamespace
 where d.dictname='unaccent' order by n.nspname limit 1;
 if dictionary_name is not null then
   execute 'alter text search configuration public.conhecimento_portuguese alter mapping for hword, hword_part, word with '
     || dictionary_name || ', pg_catalog.portuguese_stem';
 end if;
end $$;
create table public.conhecimento_trechos (
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 versao_id uuid not null,
 ordem integer not null check(ordem>0),
 secao text not null,
 texto text not null check(length(texto) between 1 and 2000),
 busca tsvector not null,
 primary key(igreja_id,versao_id,ordem),
 foreign key(igreja_id,versao_id) references public.conhecimento_versoes(igreja_id,id) on delete cascade
);
create index conhecimento_trechos_lexical on public.conhecimento_trechos using gin(busca);
alter table public.conhecimento_trechos enable row level security;
alter table public.conhecimento_trechos force row level security;
create policy tenant_isolation on public.conhecimento_trechos for all to authenticated
 using(igreja_id=public.current_igreja_id()
   and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
   and session_user not in ('authenticator','authenticated','anon'))
 with check(igreja_id=public.current_igreja_id()
   and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
   and session_user not in ('authenticator','authenticated','anon'));
revoke all on public.conhecimento_trechos from public,anon,authenticated,service_role;
grant select,insert on public.conhecimento_trechos to authenticated;

-- Preserve word boundaries and every character. Oversized individual tokens
-- are split only when no whitespace boundary exists within the section limit.
create function public.conhecimento_dividir(conteudo text)
returns table(ordem integer,texto text) language plpgsql immutable
set search_path=pg_catalog as $$
declare restante text:=conteudo; parte text; corte text;
begin
 ordem:=0;
 while length(restante)>0 loop
   parte:=substring(restante from 1 for 2000);
   if length(restante)>2000 then
     corte:=regexp_replace(parte,E'\\S+$','');
     if length(corte)>0 then parte:=corte; end if;
   end if;
   ordem:=ordem+1; texto:=parte; return next;
   restante:=substring(restante from length(parte)+1);
 end loop;
end $$;
revoke all on function public.conhecimento_dividir(text) from public,anon,authenticated,service_role;
grant execute on function public.conhecimento_dividir(text) to authenticated;
-- Invoker rights: the existing tenant scope applies to the trigger too.
create function public.conhecimento_gerar_trechos() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if new.estado='publicada' and old.estado is distinct from 'publicada' then
   insert into public.conhecimento_trechos(igreja_id,versao_id,ordem,secao,texto,busca)
   select new.igreja_id,new.id,c.ordem,'Trecho '||c.ordem,c.texto,
     to_tsvector('public.conhecimento_portuguese',c.texto)
   from public.conhecimento_dividir(new.conteudo) c;
 end if;
 return new;
end $$;
revoke all on function public.conhecimento_gerar_trechos() from public,anon,authenticated,service_role;
create trigger conhecimento_publicacao_trechos after update of estado on public.conhecimento_versoes
 for each row execute function public.conhecimento_gerar_trechos();
-- Existing approved snapshots also become searchable atomically with this migration.
insert into public.conhecimento_trechos(igreja_id,versao_id,ordem,secao,texto,busca)
 select v.igreja_id,v.id,c.ordem,'Trecho '||c.ordem,c.texto,
 to_tsvector('public.conhecimento_portuguese',c.texto)
 from public.conhecimento_versoes v cross join lateral public.conhecimento_dividir(v.conteudo) c
 where v.estado='publicada';
-- Revocation/replacement excludes rows via the live version join, without deleting history.
-- Rollback: stop new callers first; preserve approved snapshots and citations.
-- drop trigger conhecimento_publicacao_trechos on public.conhecimento_versoes;
-- drop function public.conhecimento_gerar_trechos();
-- drop table public.conhecimento_trechos;
-- drop text search configuration public.conhecimento_portuguese;
-- drop function public.conhecimento_dividir(text);
-- unaccent may be shared: do not remove its extension.
