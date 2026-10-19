-- Conhecimento oficial PR1. Sem ingestão, busca, canal ou ativação.
set local lock_timeout = '2s';
create table public.conhecimento_documentos (
 id uuid primary key,
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 titulo text not null check(length(trim(titulo)) between 1 and 200),
 assunto text not null check(length(trim(assunto)) between 1 and 120),
 responsavel_id uuid not null,
 autor_id uuid not null,
 criada_em timestamptz not null default now(),
 rascunho_id uuid,
 vigente_id uuid,
 unique(igreja_id,id),
 foreign key(igreja_id,responsavel_id) references public.app_users(igreja_id,id),
 foreign key(igreja_id,autor_id) references public.app_users(igreja_id,id)
);
create table public.conhecimento_versoes (
 id uuid primary key,
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 documento_id uuid not null,
 anterior_id uuid,
 conteudo text not null check(length(trim(conteudo)) between 1 and 100000),
 hash text not null,
 origem text not null check(length(trim(origem)) between 1 and 500),
 autor_id uuid not null,
 criada_em timestamptz not null default now(),
 -- Snapshot do público: vazio durante elaboração; publicação exige escolha.
 publicos text[] not null default '{}',
 estado text not null default 'rascunho' check(estado in
   ('rascunho','em_revisao','publicada','substituida','revogada')),
 revisada_por uuid, revisada_em timestamptz,
 aprovador_id uuid, aprovada_em timestamptz, publicada_em timestamptz,
 revogador_id uuid, revogada_em timestamptz,
 unique(igreja_id,id), unique(igreja_id,documento_id,id),
 foreign key(igreja_id,documento_id) references public.conhecimento_documentos(igreja_id,id) on delete cascade,
 foreign key(igreja_id,documento_id,anterior_id) references public.conhecimento_versoes(igreja_id,documento_id,id),
 foreign key(igreja_id,autor_id) references public.app_users(igreja_id,id),
 foreign key(igreja_id,revisada_por) references public.app_users(igreja_id,id),
 foreign key(igreja_id,aprovador_id) references public.app_users(igreja_id,id),
 foreign key(igreja_id,revogador_id) references public.app_users(igreja_id,id),
 check(array_position(publicos,null) is null and publicos <@ array[
   'institucional_publico','membros','papel:admin','papel:pastor',
   'papel:lider_g12','papel:lider_consol','papel:lider_celula','papel:lider_mult',
   'papel:operador','papel:membro']::text[]),
 check ((revisada_por is null)=(revisada_em is null)),
 check ((aprovador_id is null)=(aprovada_em is null)),
 check ((revogador_id is null)=(revogada_em is null)),
 check (estado <> 'publicada' or cardinality(publicos)>0),
 check (estado <> 'publicada' or (aprovador_id is not null and publicada_em is not null)),
 check (estado <> 'revogada' or revogador_id is not null)
);
create unique index conhecimento_uma_publicada on public.conhecimento_versoes(igreja_id,documento_id)
 where estado='publicada';
alter table public.conhecimento_documentos
 add foreign key(igreja_id,id,vigente_id) references public.conhecimento_versoes(igreja_id,documento_id,id),
 add foreign key(igreja_id,id,rascunho_id) references public.conhecimento_versoes(igreja_id,documento_id,id);

-- Mesmo o owner não altera um snapshot. Edição cria outra versão, sem DELETE.
create function public.conhecimento_preservar_snapshot() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if TG_OP='INSERT' then
   new.hash := encode(sha256(convert_to(new.conteudo,'UTF8')),'hex');
   return new;
 end if;
 if new.hash is distinct from old.hash then
   raise exception 'Hash imutável' using errcode='23514';
 end if;
 if (new.id,new.igreja_id,new.documento_id,new.anterior_id,new.conteudo,new.origem,
     new.autor_id,new.criada_em,new.publicos) is distinct from
    (old.id,old.igreja_id,old.documento_id,old.anterior_id,old.conteudo,old.origem,
     old.autor_id,old.criada_em,old.publicos) then
   raise exception 'Snapshot imutável' using errcode='23514';
 end if;
 if (old.aprovador_id is not null and (new.aprovador_id,new.aprovada_em,new.publicada_em)
       is distinct from (old.aprovador_id,old.aprovada_em,old.publicada_em))
    or (old.revisada_por is not null and (new.revisada_por,new.revisada_em)
       is distinct from (old.revisada_por,old.revisada_em))
    or (old.revogador_id is not null and (new.revogador_id,new.revogada_em)
       is distinct from (old.revogador_id,old.revogada_em)) then
   raise exception 'Proveniência imutável' using errcode='23514';
 end if;
 if old.estado<>new.estado and not (
    (old.estado='rascunho' and new.estado in ('em_revisao','substituida','revogada')) or
    (old.estado='em_revisao' and new.estado in ('publicada','substituida','revogada')) or
    (old.estado='publicada' and new.estado in ('substituida','revogada')) or
    (old.estado='substituida' and new.estado='revogada')) then
   raise exception 'Transição inválida' using errcode='23514';
 end if;
 return new;
end $$;
revoke all on function public.conhecimento_preservar_snapshot() from public,anon,authenticated,service_role;
create trigger conhecimento_snapshot before insert or update on public.conhecimento_versoes
 for each row execute function public.conhecimento_preservar_snapshot();

do $$ declare t text; begin
 foreach t in array array['conhecimento_documentos','conhecimento_versoes'] loop
 execute format('alter table public.%I enable row level security',t);
 execute format('alter table public.%I force row level security',t);
 -- Somente backend com escopo confiável; não expor conteúdo via PostgREST.
 execute format($policy$create policy tenant_isolation on public.%I for all to authenticated
 using(igreja_id=public.current_igreja_id()
   and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
   and session_user not in ('authenticator','authenticated','anon'))
 with check(igreja_id=public.current_igreja_id()
   and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
   and session_user not in ('authenticator','authenticated','anon'))$policy$,t);
 execute format('revoke all on public.%I from public,anon,authenticated,service_role',t);
 execute format('grant select on public.%I to authenticated',t);
 end loop;
end $$;
grant insert(id,igreja_id,titulo,assunto,responsavel_id,autor_id) on public.conhecimento_documentos to authenticated;
grant update(rascunho_id,vigente_id) on public.conhecimento_documentos to authenticated;
grant insert(id,igreja_id,documento_id,anterior_id,conteudo,origem,autor_id,publicos) on public.conhecimento_versoes to authenticated;
grant update(estado,revisada_por,revisada_em,aprovador_id,aprovada_em,publicada_em,revogador_id,revogada_em) on public.conhecimento_versoes to authenticated;

-- Rollback manual: interromper callers antes; recusar se houver documentos.
-- begin;
-- set local lock_timeout='2s';
-- lock table public.conhecimento_documentos,public.conhecimento_versoes in access exclusive mode;
-- do $$ begin if exists(select 1 from public.conhecimento_documentos) then
--   raise exception 'Preservar documentos e versões; rollback indisponível';
-- end if; end $$;
-- alter table public.conhecimento_documentos drop constraint conhecimento_documentos_igreja_id_id_vigente_id_fkey,
--   drop constraint conhecimento_documentos_igreja_id_id_rascunho_id_fkey;
-- drop table public.conhecimento_versoes,public.conhecimento_documentos;
-- drop function public.conhecimento_preservar_snapshot();
-- commit;
