-- CD PR 4: one current attendance per enrollment/lesson, immutable revisions.
set local lock_timeout = '2s';
alter table public.cd_matriculas add constraint cd_matricula_turma_key unique(igreja_id,turma_id,id);
create table public.cd_presencas (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null references public.igrejas(id) on delete cascade,
  turma_id uuid not null,
  matricula_id uuid not null,
  aula_id uuid not null,
  presente boolean not null,
  modalidade text not null check(modalidade in ('regular','reposicao')),
  check(modalidade <> 'reposicao' or presente),
  registro_id uuid not null unique,
  anterior_id uuid,
  registrada_por uuid not null,
  registrada_em timestamptz not null default clock_timestamp(),
  unique(igreja_id,id),
  unique(igreja_id,matricula_id,aula_id),
  foreign key(igreja_id,turma_id) references public.cd_turmas(igreja_id,id) on delete cascade,
  foreign key(igreja_id,turma_id,matricula_id) references public.cd_matriculas(igreja_id,turma_id,id) on delete cascade,
  foreign key(igreja_id,turma_id,aula_id) references public.cd_calendario(igreja_id,turma_id,aula_id),
  foreign key(igreja_id,registrada_por) references public.app_users(igreja_id,id)
);
create table public.cd_presencas_historico (
  registro_id uuid primary key,
  igreja_id uuid not null references public.igrejas(id) on delete cascade,
  presenca_id uuid not null,
  anterior_id uuid,
  presente boolean not null,
  modalidade text not null check(modalidade in ('regular','reposicao')),
  registrada_por uuid not null,
  registrada_em timestamptz not null,
  unique(igreja_id,registro_id),
  foreign key(igreja_id,presenca_id) references public.cd_presencas(igreja_id,id) on delete cascade,
  foreign key(igreja_id,registrada_por) references public.app_users(igreja_id,id),
  foreign key(igreja_id,anterior_id) references public.cd_presencas_historico(igreja_id,registro_id)
);
-- Database clock owns both the current record and the immutable revision.
create function public.cd_horario_presenca() returns trigger
language plpgsql set search_path = pg_catalog, public as $$
begin
  new.registrada_em := clock_timestamp();
  return new;
end $$;
revoke all on function public.cd_horario_presenca() from public,anon,authenticated,service_role;
create trigger cd_presenca_horario before insert or update on public.cd_presencas
  for each row execute function public.cd_horario_presenca();

-- Trigger is the sole history writer; no caller can omit or rewrite a revision.
create function public.cd_auditar_presenca() returns trigger
language plpgsql security definer set search_path = pg_catalog, public as $$
begin
  if TG_OP='UPDATE' then
    if (new.id,new.igreja_id,new.turma_id,new.matricula_id,new.aula_id)
       is distinct from (old.id,old.igreja_id,old.turma_id,old.matricula_id,old.aula_id)
       or new.anterior_id is distinct from old.registro_id then
      raise exception 'Identidade imutável ou revisão divergente' using errcode='23514';
    end if;
  elsif new.anterior_id is not null then
    raise exception 'Registro inicial sem revisão anterior' using errcode='23514';
  end if;
  insert into public.cd_presencas_historico(registro_id,igreja_id,presenca_id,anterior_id,presente,modalidade,registrada_por,registrada_em)
    values(new.registro_id,new.igreja_id,new.id,new.anterior_id,new.presente,new.modalidade,new.registrada_por,new.registrada_em);
  return new;
end $$;
revoke all on function public.cd_auditar_presenca() from public,anon,authenticated,service_role;
create trigger cd_presenca_auditoria after insert or update on public.cd_presencas
  for each row execute function public.cd_auditar_presenca();

do $$ declare t text; begin
  foreach t in array array['cd_presencas','cd_presencas_historico'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('create policy tenant_isolation on public.%I for all to authenticated using (igreja_id=public.current_igreja_id() and igreja_id=nullif(current_setting(''app.tenant_igreja_id'',true),'''')::uuid and session_user not in (''authenticator'',''authenticated'',''anon'')) with check(igreja_id=public.current_igreja_id() and igreja_id=nullif(current_setting(''app.tenant_igreja_id'',true),'''')::uuid and session_user not in (''authenticator'',''authenticated'',''anon''))',t);
    execute format('revoke all on public.%I from public,anon,authenticated,service_role',t);
    execute format('grant select on public.%I to authenticated',t);
  end loop;
end $$;
grant insert(igreja_id,turma_id,matricula_id,aula_id,presente,modalidade,registro_id,registrada_por) on public.cd_presencas to authenticated;
grant update(presente,modalidade,registro_id,anterior_id,registrada_por) on public.cd_presencas to authenticated;
-- Rollback: revert callers and preserve attendance/history before removing schema.
-- drop table public.cd_presencas_historico;
-- drop trigger cd_presenca_auditoria on public.cd_presencas;
-- drop function public.cd_auditar_presenca();
-- drop trigger cd_presenca_horario on public.cd_presencas;
-- drop function public.cd_horario_presenca();
-- drop table public.cd_presencas;
-- alter table public.cd_matriculas drop constraint cd_matricula_turma_key;
