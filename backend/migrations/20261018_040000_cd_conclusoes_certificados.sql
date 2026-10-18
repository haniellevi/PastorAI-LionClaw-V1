-- CD PR 5: provisional pastoral rules, no leadership/Enviar effects.
-- Triggers usam SECURITY INVOKER (padrão), preservando o papel do chamador e a RLS.
-- O backend já possui os grants necessários; SECURITY DEFINER elevaria privilégios
-- e permitiria que as consultas dos guards contornassem o isolamento por igreja.
set local lock_timeout = '2s';
alter table public.cd_matriculas add constraint cd_matricula_conclusao_key unique(igreja_id,turma_id,id,pessoa_id,modulo_id);
create table public.cd_conclusoes (
 id uuid primary key,
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 pessoa_id uuid not null,
 curriculo_id uuid not null,
 modulo_id uuid not null,
 turma_id uuid not null,
 matricula_id uuid not null,
 origem text not null check(origem in ('frequencia','equivalencia')),
 evidencia text,
 origem_equivalencia text,
 confirmada_por uuid not null,
 confirmada_em timestamptz not null default clock_timestamp(),
 check((origem='frequencia' and evidencia is null and origem_equivalencia is null) or
       (origem='equivalencia' and evidencia is not null and length(btrim(evidencia)) between 1 and 300
        and origem_equivalencia is not null and length(btrim(origem_equivalencia)) between 1 and 120)),
 unique(igreja_id,id),
 unique(igreja_id,matricula_id),
 unique(igreja_id,pessoa_id,curriculo_id,modulo_id),
 unique(igreja_id,id,pessoa_id,curriculo_id),
 foreign key(igreja_id,pessoa_id) references public.pessoas(igreja_id,id) on delete cascade,
 foreign key(igreja_id,modulo_id,curriculo_id) references public.cd_modulos(igreja_id,id,curriculo_id),
 foreign key(igreja_id,turma_id,matricula_id,pessoa_id,modulo_id) references public.cd_matriculas(igreja_id,turma_id,id,pessoa_id,modulo_id) on delete cascade,
 foreign key(igreja_id,confirmada_por) references public.app_users(igreja_id,id)
);
create table public.cd_certificados (
 id uuid primary key,
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 pessoa_id uuid not null,
 curriculo_id uuid not null,
 codigo uuid not null default gen_random_uuid(),
 nome_pessoa text not null check(length(btrim(nome_pessoa))>0),
 nome_curriculo text not null check(length(btrim(nome_curriculo))>0),
 versao_curriculo text not null check(length(btrim(versao_curriculo))>0),
 emitida_por uuid not null,
 emitida_em timestamptz not null default clock_timestamp(),
 revogada boolean not null default false,
 revogada_por uuid,
 revogada_em timestamptz,
 motivo_revogacao text,
 check((not revogada and revogada_por is null and revogada_em is null and motivo_revogacao is null) or
       (revogada and revogada_por is not null and revogada_em is not null and revogada_em>=emitida_em
        and motivo_revogacao is not null and length(btrim(motivo_revogacao)) between 1 and 300)),
 unique(igreja_id,id),
 unique(igreja_id,codigo),
 unique(igreja_id,id,pessoa_id,curriculo_id),
 foreign key(igreja_id,pessoa_id) references public.pessoas(igreja_id,id) on delete cascade,
 foreign key(igreja_id,curriculo_id) references public.cd_curriculos(igreja_id,id),
 foreign key(igreja_id,emitida_por) references public.app_users(igreja_id,id),
 foreign key(igreja_id,revogada_por) references public.app_users(igreja_id,id)
);
create unique index cd_certificado_ativo on public.cd_certificados(igreja_id,pessoa_id,curriculo_id) where not revogada;
create table public.cd_certificado_conclusoes (
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 certificado_id uuid not null,
 conclusao_id uuid not null,
 pessoa_id uuid not null,
 curriculo_id uuid not null,
 primary key(igreja_id,certificado_id,conclusao_id),
 foreign key(igreja_id,certificado_id,pessoa_id,curriculo_id) references public.cd_certificados(igreja_id,id,pessoa_id,curriculo_id) on delete cascade,
 foreign key(igreja_id,conclusao_id,pessoa_id,curriculo_id) references public.cd_conclusoes(igreja_id,id,pessoa_id,curriculo_id)
);
-- Only revocation can change a certificate; its author/time/reason are final.
create function public.cd_revogar_certificado() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if old.revogada or not new.revogada then
   raise exception 'Certificado permite somente revogação definitiva' using errcode='23514';
 end if;
 new.revogada_em := clock_timestamp();
 return new;
end $$;
revoke all on function public.cd_revogar_certificado() from public,anon,authenticated,service_role;
create trigger cd_certificado_revogacao before update on public.cd_certificados
 for each row execute function public.cd_revogar_certificado();
-- Completed enrollments remain active historical identities, frozen for writes.
create function public.cd_preservar_conclusao() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
declare mid uuid;
begin
 if TG_TABLE_NAME='cd_matriculas' then mid := new.id; else mid := new.matricula_id; end if;
 if exists(select 1 from public.cd_conclusoes c where c.igreja_id=new.igreja_id
     and c.matricula_id=mid) then
   raise exception 'Matrícula concluída' using errcode='23514';
 end if;
 return new;
end $$;
revoke all on function public.cd_preservar_conclusao() from public,anon,authenticated,service_role;
create trigger cd_matricula_concluida before update on public.cd_matriculas
 for each row execute function public.cd_preservar_conclusao();
create trigger cd_presenca_concluida before insert or update on public.cd_presencas
 for each row execute function public.cd_preservar_conclusao();
do $$ declare t text; begin
 foreach t in array array['cd_conclusoes','cd_certificados','cd_certificado_conclusoes'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('alter table public.%I force row level security',t);
  execute format('create policy tenant_isolation on public.%I for all to authenticated using(igreja_id=public.current_igreja_id() and igreja_id=nullif(current_setting(''app.tenant_igreja_id'',true),'''')::uuid and session_user not in (''authenticator'',''authenticated'',''anon'')) with check(igreja_id=public.current_igreja_id() and igreja_id=nullif(current_setting(''app.tenant_igreja_id'',true),'''')::uuid and session_user not in (''authenticator'',''authenticated'',''anon''))',t);
  execute format('revoke all on public.%I from public,anon,authenticated,service_role',t);
  execute format('grant select on public.%I to authenticated',t);
 end loop;
end $$;
grant insert(id,igreja_id,pessoa_id,curriculo_id,modulo_id,turma_id,matricula_id,origem,evidencia,origem_equivalencia,confirmada_por) on public.cd_conclusoes to authenticated;
grant insert(id,igreja_id,pessoa_id,curriculo_id,nome_pessoa,nome_curriculo,versao_curriculo,emitida_por) on public.cd_certificados to authenticated;
grant update(revogada,revogada_por,motivo_revogacao) on public.cd_certificados to authenticated;
grant insert(igreja_id,certificado_id,conclusao_id,pessoa_id,curriculo_id) on public.cd_certificado_conclusoes to authenticated;
-- Rollback: revert callers, preserve all conclusions/certificates/revocations first.
-- drop trigger cd_presenca_concluida on public.cd_presencas;
-- drop trigger cd_matricula_concluida on public.cd_matriculas;
-- drop function public.cd_preservar_conclusao();
-- drop table public.cd_certificado_conclusoes;
-- drop trigger cd_certificado_revogacao on public.cd_certificados;
-- drop function public.cd_revogar_certificado();
-- drop table public.cd_certificados,public.cd_conclusoes;
-- alter table public.cd_matriculas drop constraint cd_matricula_conclusao_key;
