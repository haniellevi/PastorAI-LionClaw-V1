-- Faixa B/2: responsabilidade operacional; não concede papel ou acesso.
set lock_timeout='2s';
create extension if not exists btree_gist;
create table public.responsabilidades_setor (
 id uuid primary key default gen_random_uuid(),
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 pessoa_id uuid not null,
 setor text not null check(setor in ('atendimento','consolidacao','central_celulas','universidade_vida','capacitacao_destino','agenda','conhecimento_oficial')),
 inicio date not null,
 fim date,
 atribuida_por uuid not null,
 criada_em timestamptz not null default clock_timestamp(),
 encerrada_por uuid,
 encerrada_em timestamptz,
 check(fim is null or fim > inicio),
 check((encerrada_por is null and encerrada_em is null) or (encerrada_por is not null and encerrada_em is not null and fim is not null)),
 -- Exclusão física aprovada acompanha Pessoa; autores preservam NO ACTION.
 foreign key(igreja_id,pessoa_id) references public.pessoas(igreja_id,id) on delete cascade,
 foreign key(igreja_id,atribuida_por) references public.app_users(igreja_id,id),
 foreign key(igreja_id,encerrada_por) references public.app_users(igreja_id,id),
 exclude using gist (igreja_id with =, setor with =, daterange(inicio,fim,'[)') with &&)
);
create function public.responsabilidade_preservar_historico() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if (new.id,new.igreja_id,new.pessoa_id,new.setor,new.inicio,new.atribuida_por,new.criada_em)
    is distinct from (old.id,old.igreja_id,old.pessoa_id,old.setor,old.inicio,old.atribuida_por,old.criada_em)
    or old.encerrada_em is not null or new.encerrada_em is null or new.encerrada_por is null
    or new.fim is null or (old.fim is not null and new.fim > old.fim) then
  raise exception 'Responsabilidade admite somente encerramento único' using errcode='23514';
 end if;
 return new;
end $$;
create trigger responsabilidade_historico before update on public.responsabilidades_setor
 for each row execute function public.responsabilidade_preservar_historico();
revoke all on function public.responsabilidade_preservar_historico() from public,anon,authenticated,service_role;
alter table public.responsabilidades_setor enable row level security;
alter table public.responsabilidades_setor force row level security;
create policy tenant_isolation on public.responsabilidades_setor for all to authenticated
 using(igreja_id=public.current_igreja_id() and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and session_user not in ('authenticator','authenticated','anon'))
 with check(igreja_id=public.current_igreja_id() and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and session_user not in ('authenticator','authenticated','anon'));
revoke all on public.responsabilidades_setor from public,anon,authenticated,service_role;
grant select on public.responsabilidades_setor to authenticated;
grant insert(igreja_id,pessoa_id,setor,inicio,fim,atribuida_por) on public.responsabilidades_setor to authenticated;
grant update(fim,encerrada_por,encerrada_em) on public.responsabilidades_setor to authenticated;
-- Rollback: restaurar callers anteriores e preservar histórico sob procedimento
-- de privacidade aprovado antes de remover o schema. Não apagar automaticamente.
-- drop table public.responsabilidades_setor;
-- drop function public.responsabilidade_preservar_historico();
-- btree_gist pode ser compartilhada: não remover a extensão.
