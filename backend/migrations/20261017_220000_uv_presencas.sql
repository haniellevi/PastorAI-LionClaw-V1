-- UV PR 3: one current attendance per enrollment/lesson, immutable revisions.
set local lock_timeout = '2s';
alter table public.uv_matriculas add constraint uv_matricula_turma_key unique(igreja_id,turma_id,id);
alter table public.uv_atividades add constraint uv_atividade_aula_key unique(igreja_id,turma_id,id,aula);
create table public.uv_presencas (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null references public.igrejas(id) on delete cascade,
  turma_id uuid not null,
  matricula_id uuid not null,
  atividade_id uuid not null,
  aula integer not null check(aula between 1 and 8),
  presente boolean not null,
  modalidade text not null check(modalidade in ('regular','reposicao')),
  registro_id uuid not null unique,
  anterior_id uuid,
  registrada_por uuid not null,
  registrada_em timestamptz not null default clock_timestamp(),
  unique(igreja_id,id),
  unique(igreja_id,matricula_id,aula),
  foreign key(igreja_id,turma_id) references public.uv_turmas(igreja_id,id) on delete cascade,
  foreign key(igreja_id,turma_id,matricula_id) references public.uv_matriculas(igreja_id,turma_id,id) on delete cascade,
  -- Encontro has aula NULL, so it can never satisfy this non-null composite FK.
  foreign key(igreja_id,turma_id,atividade_id,aula) references public.uv_atividades(igreja_id,turma_id,id,aula) on delete cascade,
  foreign key(igreja_id,registrada_por) references public.app_users(igreja_id,id)
);
create table public.uv_presencas_historico (
  registro_id uuid primary key,
  igreja_id uuid not null references public.igrejas(id) on delete cascade,
  presenca_id uuid not null,
  anterior_id uuid,
  presente boolean not null,
  modalidade text not null check(modalidade in ('regular','reposicao')),
  registrada_por uuid not null,
  registrada_em timestamptz not null,
  unique(igreja_id,registro_id),
  foreign key(igreja_id,presenca_id) references public.uv_presencas(igreja_id,id) on delete cascade,
  foreign key(igreja_id,registrada_por) references public.app_users(igreja_id,id),
  foreign key(igreja_id,anterior_id) references public.uv_presencas_historico(igreja_id,registro_id)
);
-- Trigger is the sole history writer; no caller can omit or rewrite a revision.
create function public.uv_auditar_presenca() returns trigger
language plpgsql security definer set search_path = pg_catalog, public as $$
begin
  if TG_OP='UPDATE' then
    if (new.id,new.igreja_id,new.turma_id,new.matricula_id,new.atividade_id,new.aula)
       is distinct from (old.id,old.igreja_id,old.turma_id,old.matricula_id,old.atividade_id,old.aula)
       or new.anterior_id is distinct from old.registro_id then
      raise exception 'Identidade imutável ou revisão divergente' using errcode='23514';
    end if;
  elsif new.anterior_id is not null then
    raise exception 'Registro inicial sem revisão anterior' using errcode='23514';
  end if;
  insert into public.uv_presencas_historico(registro_id,igreja_id,presenca_id,anterior_id,presente,modalidade,registrada_por,registrada_em)
    values(new.registro_id,new.igreja_id,new.id,new.anterior_id,new.presente,new.modalidade,new.registrada_por,new.registrada_em);
  return new;
end $$;
revoke all on function public.uv_auditar_presenca() from public,anon,authenticated;
create trigger uv_presenca_auditoria after insert or update on public.uv_presencas
  for each row execute function public.uv_auditar_presenca();

do $$ declare t text; begin
  foreach t in array array['uv_presencas','uv_presencas_historico'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('create policy tenant_isolation on public.%I for all to authenticated using (igreja_id=public.current_igreja_id()) with check(igreja_id=public.current_igreja_id())',t);
    execute format('revoke all on public.%I from public,anon,authenticated',t);
    execute format('grant select on public.%I to authenticated',t);
  end loop;
end $$;
grant insert(igreja_id,turma_id,matricula_id,atividade_id,aula,presente,modalidade,registro_id,registrada_por) on public.uv_presencas to authenticated;
grant update(presente,modalidade,registro_id,anterior_id,registrada_por,registrada_em) on public.uv_presencas to authenticated;
-- Rollback: revert callers and preserve attendance/history before removing schema.
-- drop table public.uv_presencas_historico;
-- drop trigger uv_presenca_auditoria on public.uv_presencas;
-- drop function public.uv_auditar_presenca();
-- drop table public.uv_presencas;
-- alter table public.uv_atividades drop constraint uv_atividade_aula_key;
-- alter table public.uv_matriculas drop constraint uv_matricula_turma_key;
