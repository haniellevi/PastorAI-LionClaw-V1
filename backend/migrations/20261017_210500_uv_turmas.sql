-- UV PR 2. Local synthetic PostgreSQL first; no deployment/activation implied.
set lock_timeout = '2s';

create table public.uv_turmas (
  id uuid primary key,
  igreja_id uuid not null references public.igrejas(id),
  nome text not null check (length(trim(nome)) between 1 and 120),
  encerrada boolean not null default false,
  criada_em timestamptz not null default now(),
  unique (igreja_id, id)
);
create table public.uv_atividades (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null references public.igrejas(id),
  turma_id uuid not null,
  ordem integer not null check (ordem between 1 and 9),
  aula integer check (aula between 1 and 8),
  tipo text not null check (tipo in ('aula','encontro')),
  data date not null,
  check ((tipo='aula' and aula is not null) or (tipo='encontro' and aula is null)),
  unique (igreja_id, id),
  unique (igreja_id, turma_id, ordem),
  unique (igreja_id, turma_id, aula),
  foreign key (igreja_id, turma_id) references public.uv_turmas(igreja_id,id)
);
create unique index uv_um_encontro on public.uv_atividades(igreja_id,turma_id) where tipo='encontro';
create table public.uv_responsaveis (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null references public.igrejas(id),
  turma_id uuid not null,
  usuario_id uuid not null,
  ativo boolean not null default true,
  unique (igreja_id, id),
  unique (igreja_id, turma_id, usuario_id),
  foreign key (igreja_id,turma_id) references public.uv_turmas(igreja_id,id),
  foreign key (igreja_id,usuario_id) references public.app_users(igreja_id,id)
);
create table public.uv_matriculas (
  id uuid primary key,
  igreja_id uuid not null references public.igrejas(id),
  turma_id uuid not null,
  pessoa_id uuid not null,
  ativa boolean not null default true,
  criada_em timestamptz not null default now(),
  unique (igreja_id,id),
  foreign key (igreja_id,turma_id) references public.uv_turmas(igreja_id,id),
  foreign key (igreja_id,pessoa_id) references public.pessoas(igreja_id,id)
);
create unique index uv_matricula_ativa on public.uv_matriculas(igreja_id,turma_id,pessoa_id) where ativa;

-- Domain capabilities are revalidated by the server. RLS is the independent
-- tenant boundary, including direct SQL with the authenticated role.
do $$
declare t text;
begin
  foreach t in array array['uv_turmas','uv_atividades','uv_responsaveis','uv_matriculas'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('create policy tenant_isolation on public.%I for all to authenticated using (igreja_id = public.current_igreja_id()) with check (igreja_id = public.current_igreja_id())', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select, insert, update on public.%I to authenticated', t);
  end loop;
end $$;
-- Rollback (only after reverting callers and preserving formation records):
-- drop table public.uv_matriculas, public.uv_responsaveis,
--   public.uv_atividades, public.uv_turmas;
