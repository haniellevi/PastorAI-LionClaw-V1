-- CD PR 2: synthetic local proof first; release must apply before new callers.
set local lock_timeout = '2s';
create table public.cd_curriculos (
 id uuid primary key,
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 versao text not null check(length(trim(versao)) between 1 and 80),
 nome text not null check(length(trim(nome)) between 1 and 120),
 criada_por uuid not null,
 criada_em timestamptz not null default now(),
 unique(igreja_id,id), unique(igreja_id,versao),
 foreign key(igreja_id,criada_por) references public.app_users(igreja_id,id)
);
create table public.cd_niveis (
 id uuid primary key default gen_random_uuid(),
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 curriculo_id uuid not null,
 numero integer not null check(numero>0),
 nome text not null check(length(trim(nome)) between 1 and 120),
 unique(igreja_id,id), unique(igreja_id,curriculo_id,id), unique(igreja_id,curriculo_id,numero),
 foreign key(igreja_id,curriculo_id) references public.cd_curriculos(igreja_id,id) on delete cascade
);
create table public.cd_modulos (
 id uuid primary key default gen_random_uuid(),
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 curriculo_id uuid not null,
 nivel_id uuid,
 numero integer not null check(numero>0),
 nome text not null check(length(trim(nome)) between 1 and 120),
 unique(igreja_id,id), unique(igreja_id,curriculo_id,id), unique(igreja_id,curriculo_id,numero),
 foreign key(igreja_id,curriculo_id) references public.cd_curriculos(igreja_id,id) on delete cascade,
 foreign key(igreja_id,curriculo_id,nivel_id) references public.cd_niveis(igreja_id,curriculo_id,id)
);
create table public.cd_aulas (
 id uuid primary key default gen_random_uuid(),
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 modulo_id uuid not null,
 numero integer not null check(numero>0),
 nome text not null check(length(trim(nome)) between 1 and 120),
 unique(igreja_id,id), unique(igreja_id,modulo_id,id), unique(igreja_id,modulo_id,numero),
 foreign key(igreja_id,modulo_id) references public.cd_modulos(igreja_id,id) on delete cascade
);
create table public.cd_turmas (
 id uuid primary key,
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 curriculo_id uuid not null,
 modulo_id uuid not null,
 nome text not null check(length(trim(nome)) between 1 and 120),
 encerrada boolean not null default false,
 criada_por uuid not null,
 criada_em timestamptz not null default now(),
 encerrada_por uuid, encerrada_em timestamptz,
 reaberta_por uuid, reaberta_em timestamptz,
 unique(igreja_id,id), unique(igreja_id,id,modulo_id),
 foreign key(igreja_id,curriculo_id,modulo_id) references public.cd_modulos(igreja_id,curriculo_id,id),
 foreign key(igreja_id,criada_por) references public.app_users(igreja_id,id),
 foreign key(igreja_id,encerrada_por) references public.app_users(igreja_id,id),
 foreign key(igreja_id,reaberta_por) references public.app_users(igreja_id,id)
);
create table public.cd_calendario (
 id uuid primary key default gen_random_uuid(),
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 turma_id uuid not null, modulo_id uuid not null, aula_id uuid not null,
 data date not null,
 criada_por uuid not null,
 unique(igreja_id,id), unique(igreja_id,turma_id,aula_id),
 foreign key(igreja_id,turma_id,modulo_id) references public.cd_turmas(igreja_id,id,modulo_id) on delete cascade,
 foreign key(igreja_id,modulo_id,aula_id) references public.cd_aulas(igreja_id,modulo_id,id),
 foreign key(igreja_id,criada_por) references public.app_users(igreja_id,id)
);
create table public.cd_responsaveis (
 id uuid primary key default gen_random_uuid(),
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 turma_id uuid not null, usuario_id uuid not null,
 ativo boolean not null default true,
 atribuido_por uuid not null, atribuida_em timestamptz not null default now(),
 removido_por uuid, removida_em timestamptz,
 unique(igreja_id,id), unique(igreja_id,turma_id,usuario_id),
 foreign key(igreja_id,turma_id) references public.cd_turmas(igreja_id,id) on delete cascade,
 foreign key(igreja_id,usuario_id) references public.app_users(igreja_id,id),
 foreign key(igreja_id,atribuido_por) references public.app_users(igreja_id,id),
 foreign key(igreja_id,removido_por) references public.app_users(igreja_id,id)
);
do $$ declare t text; begin
 foreach t in array array['cd_curriculos','cd_niveis','cd_modulos','cd_aulas','cd_turmas','cd_calendario','cd_responsaveis'] loop
 execute format('alter table public.%I enable row level security',t);
 execute format('alter table public.%I force row level security',t);
 execute format('create policy tenant_isolation on public.%I for all to authenticated using(igreja_id=public.current_igreja_id()) with check(igreja_id=public.current_igreja_id())',t);
 execute format('revoke all on public.%I from public,anon,authenticated',t);
 execute format('grant select on public.%I to authenticated',t);
 end loop;
end $$;
grant insert(id,igreja_id,versao,nome,criada_por) on public.cd_curriculos to authenticated;
grant insert(igreja_id,curriculo_id,numero,nome) on public.cd_niveis to authenticated;
grant insert(igreja_id,curriculo_id,nivel_id,numero,nome) on public.cd_modulos to authenticated;
grant insert(igreja_id,modulo_id,numero,nome) on public.cd_aulas to authenticated;
grant insert(id,igreja_id,curriculo_id,modulo_id,nome,criada_por) on public.cd_turmas to authenticated;
grant insert(igreja_id,turma_id,modulo_id,aula_id,data,criada_por) on public.cd_calendario to authenticated;
grant insert(igreja_id,turma_id,usuario_id,atribuido_por) on public.cd_responsaveis to authenticated;
grant update(nome) on public.cd_curriculos,public.cd_niveis,public.cd_modulos,public.cd_aulas to authenticated;
grant update(nome,encerrada,encerrada_por,encerrada_em,reaberta_por,reaberta_em) on public.cd_turmas to authenticated;
grant update(data) on public.cd_calendario to authenticated;
grant update(ativo,atribuido_por,atribuida_em,removido_por,removida_em) on public.cd_responsaveis to authenticated;
-- Rollback: revert callers and preserve catalog/calendar/responsibility records first.
-- drop table public.cd_responsaveis,public.cd_calendario,public.cd_turmas,
-- public.cd_aulas,public.cd_modulos,public.cd_niveis,public.cd_curriculos;
