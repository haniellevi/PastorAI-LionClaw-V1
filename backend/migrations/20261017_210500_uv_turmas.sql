-- UV PR 2. Local synthetic PostgreSQL first; no deployment/activation implied.
set local lock_timeout = '2s';

create table public.uv_turmas (
  id uuid primary key,
  igreja_id uuid not null references public.igrejas(id) on delete cascade,
  nome text not null check (length(trim(nome)) between 1 and 120),
  encerrada boolean not null default false,
  encerrada_por uuid,
  encerrada_em timestamptz,
  reaberta_por uuid,
  reaberta_em timestamptz,
  foreign key (igreja_id,encerrada_por) references public.app_users(igreja_id,id),
  foreign key (igreja_id,reaberta_por) references public.app_users(igreja_id,id),
  criada_por uuid,
  foreign key (igreja_id,criada_por) references public.app_users(igreja_id,id),
  criada_em timestamptz not null default now(),
  unique (igreja_id, id)
);
create table public.uv_atividades (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null references public.igrejas(id) on delete cascade,
  turma_id uuid not null,
  ordem integer not null check (ordem between 1 and 9),
  aula integer check (aula between 1 and 8),
  tipo text not null check (tipo in ('aula','encontro')),
  data date not null,
  criada_por uuid,
  foreign key (igreja_id,criada_por) references public.app_users(igreja_id,id),
  check ((tipo='aula' and aula is not null) or (tipo='encontro' and aula is null)),
  unique (igreja_id, id),
  unique (igreja_id, turma_id, ordem),
  unique (igreja_id, turma_id, aula),
  foreign key (igreja_id, turma_id) references public.uv_turmas(igreja_id,id) on delete cascade
);
create unique index uv_um_encontro on public.uv_atividades(igreja_id,turma_id) where tipo='encontro';
create table public.uv_responsaveis (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null references public.igrejas(id) on delete cascade,
  turma_id uuid not null,
  usuario_id uuid not null,
  ativo boolean not null default true,
  atribuido_por uuid,
  removido_por uuid,
  atribuida_em timestamptz not null default now(),
  removida_em timestamptz,
  foreign key (igreja_id,atribuido_por) references public.app_users(igreja_id,id),
  foreign key (igreja_id,removido_por) references public.app_users(igreja_id,id),
  unique (igreja_id, id),
  unique (igreja_id, turma_id, usuario_id),
  foreign key (igreja_id,turma_id) references public.uv_turmas(igreja_id,id) on delete cascade,
  foreign key (igreja_id,usuario_id) references public.app_users(igreja_id,id)
);
create table public.uv_matriculas (
  id uuid primary key,
  igreja_id uuid not null references public.igrejas(id) on delete cascade,
  turma_id uuid not null,
  pessoa_id uuid not null,
  ativa boolean not null default true,
  criada_por uuid,
  foreign key (igreja_id,criada_por) references public.app_users(igreja_id,id),
  criada_em timestamptz not null default now(),
  unique (igreja_id,id),
  foreign key (igreja_id,turma_id) references public.uv_turmas(igreja_id,id) on delete cascade,
  foreign key (igreja_id,pessoa_id) references public.pessoas(igreja_id,id) on delete cascade
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
    execute format('grant select, insert on public.%I to authenticated', t);
  end loop;
end $$;
grant update(encerrada,encerrada_por,encerrada_em,reaberta_por,reaberta_em) on public.uv_turmas to authenticated;
grant update(ativo,atribuido_por,atribuida_em,removido_por,removida_em) on public.uv_responsaveis to authenticated;
grant update(data) on public.uv_atividades to authenticated;
grant update(ativa) on public.uv_matriculas to authenticated;
-- Rollback (only after reverting callers and preserving formation records):
-- drop table public.uv_matriculas, public.uv_responsaveis,
--   public.uv_atividades, public.uv_turmas;
