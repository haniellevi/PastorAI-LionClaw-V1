-- UV PR4. Apply locally first via migrate.py; no remote/deploy authorization.
set local lock_timeout = '2s';

-- Provenance belongs to the existing eligibility, not to a fabricated UV record.
alter table public.pessoas add column origem_aptidao_cd text
  check (origem_aptidao_cd in ('legado','conclusao_uv'));
update public.pessoas set origem_aptidao_cd='legado' where apto_proxima_cd;
-- Preserve provenance also when an older caller grants eligibility later.
create function public.uv_origem_aptidao() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
  if new.apto_proxima_cd and new.origem_aptidao_cd is null then
    new.origem_aptidao_cd := 'legado';
  elsif not new.apto_proxima_cd then
    new.origem_aptidao_cd := null;
  end if;
  return new;
end $$;
revoke all on function public.uv_origem_aptidao() from public,anon,authenticated;
create trigger uv_origem_aptidao before insert or update on public.pessoas
  for each row execute function public.uv_origem_aptidao();

alter table public.pessoas add constraint uv_aptidao_origem_coerente
  check (apto_proxima_cd = (origem_aptidao_cd is not null));

alter table public.uv_matriculas add constraint uv_matricula_pessoa_key unique(igreja_id,turma_id,id,pessoa_id);
create table public.uv_marcos (
  id uuid primary key,
  igreja_id uuid not null references public.igrejas(id) on delete cascade,
  pessoa_id uuid not null,
  turma_id uuid not null,
  matricula_id uuid not null,
  tipo text not null check(tipo in ('encontro','batismo')),
  data date not null,
  anterior_turma boolean not null,
  validada_por uuid not null,
  validada_em timestamptz not null default clock_timestamp(),
  unique(igreja_id,id),
  unique(igreja_id,pessoa_id,tipo),
  foreign key(igreja_id,pessoa_id) references public.pessoas(igreja_id,id) on delete cascade,
  foreign key(igreja_id,turma_id,matricula_id,pessoa_id) references public.uv_matriculas(igreja_id,turma_id,id,pessoa_id) on delete cascade,
  foreign key(igreja_id,validada_por) references public.app_users(igreja_id,id)
);
create table public.uv_conclusoes (
  id uuid primary key,
  igreja_id uuid not null references public.igrejas(id) on delete cascade,
  pessoa_id uuid not null,
  turma_id uuid not null,
  matricula_id uuid not null,
  confirmada_por uuid not null,
  confirmada_em timestamptz not null default clock_timestamp(),
  etapa_anterior public.pessoa_etapa,
  etapa_resultante public.pessoa_etapa not null,
  origem_aptidao text not null check(origem_aptidao in ('legado','conclusao_uv')),
  unique(igreja_id,id),
  unique(igreja_id,pessoa_id),
  unique(igreja_id,matricula_id),
  foreign key(igreja_id,pessoa_id) references public.pessoas(igreja_id,id) on delete cascade,
  foreign key(igreja_id,turma_id,matricula_id,pessoa_id) references public.uv_matriculas(igreja_id,turma_id,id,pessoa_id) on delete cascade,
  foreign key(igreja_id,confirmada_por) references public.app_users(igreja_id,id)
);
do $$ declare t text; begin
  foreach t in array array['uv_marcos','uv_conclusoes'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('create policy tenant_isolation on public.%I for all to authenticated using(igreja_id=public.current_igreja_id()) with check(igreja_id=public.current_igreja_id())',t);
    execute format('revoke all on public.%I from public,anon,authenticated',t);
    execute format('grant select on public.%I to authenticated',t);
  end loop;
end $$;
-- Append-only records: no UPDATE/DELETE or caller-supplied timestamps.
grant insert(id,igreja_id,pessoa_id,turma_id,matricula_id,tipo,data,anterior_turma,validada_por) on public.uv_marcos to authenticated;
grant insert(id,igreja_id,pessoa_id,turma_id,matricula_id,confirmada_por,etapa_anterior,etapa_resultante,origem_aptidao) on public.uv_conclusoes to authenticated;
-- Rollback: revert callers and preserve person milestones/completion histories first.
-- drop table public.uv_conclusoes,public.uv_marcos;
-- alter table public.uv_matriculas drop constraint uv_matricula_pessoa_key;
-- drop trigger uv_origem_aptidao on public.pessoas;
-- drop function public.uv_origem_aptidao();
-- alter table public.pessoas drop constraint uv_aptidao_origem_coerente;
-- alter table public.pessoas drop column origem_aptidao_cd;
