-- CD PR 3. Apply with migrate.py in a synthetic local chain before release.
set local lock_timeout = '2s';
-- Module number is the canonical module identity across curriculum versions.
alter table public.cd_modulos add constraint cd_modulos_numero_key unique(igreja_id,id,numero);
create table public.cd_matriculas (
 id uuid primary key,
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 turma_id uuid not null,
 modulo_id uuid not null,
 modulo_numero integer not null,
 pessoa_id uuid not null,
 origem_aptidao text not null check(origem_aptidao in ('legado','conclusao_uv')),
 ativa boolean not null default true,
 criada_por uuid not null,
 criada_em timestamptz not null default clock_timestamp(),
 cancelada_por uuid,
 cancelada_em timestamptz,
 check ((ativa and cancelada_por is null and cancelada_em is null)
     or (not ativa and cancelada_por is not null and cancelada_em is not null)),
 unique(igreja_id,id),
 unique(igreja_id,turma_id,pessoa_id),
 foreign key(igreja_id,pessoa_id) references public.pessoas(igreja_id,id) on delete cascade,
 foreign key(igreja_id,turma_id,modulo_id) references public.cd_turmas(igreja_id,id,modulo_id) on delete cascade,
 foreign key(igreja_id,modulo_id,modulo_numero) references public.cd_modulos(igreja_id,id,numero),
 foreign key(igreja_id,criada_por) references public.app_users(igreja_id,id),
 foreign key(igreja_id,cancelada_por) references public.app_users(igreja_id,id)
);
create unique index cd_matriculas_ativa_modulo on public.cd_matriculas(igreja_id,pessoa_id,modulo_numero) where ativa;
-- Immutable snapshots preserve every explicit transition before state is reused.
create table public.cd_matricula_eventos (
 id uuid primary key default gen_random_uuid(),
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 matricula_id uuid not null,
 tipo text not null check(tipo in ('matricula','cancelamento','reativacao')),
 autor_id uuid not null,
 registrada_em timestamptz not null default clock_timestamp(),
 origem_aptidao text not null check(origem_aptidao in ('legado','conclusao_uv')),
 foreign key(igreja_id,matricula_id) references public.cd_matriculas(igreja_id,id) on delete cascade,
 foreign key(igreja_id,autor_id) references public.app_users(igreja_id,id)
);
create function public.cd_matricula_evento() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
declare evento text;
begin
 if tg_op='INSERT' then evento := 'matricula';
 elsif old.ativa is distinct from new.ativa then
   evento := case when new.ativa then 'reativacao' else 'cancelamento' end;
 else return new;
 end if;
 insert into public.cd_matricula_eventos(igreja_id,matricula_id,tipo,autor_id,origem_aptidao)
 values(new.igreja_id,new.id,evento,
   case when new.ativa then new.criada_por else new.cancelada_por end,new.origem_aptidao);
 return new;
end $$;
revoke all on function public.cd_matricula_evento() from public,anon,authenticated,service_role;
create trigger cd_matricula_evento after insert or update on public.cd_matriculas
 for each row execute function public.cd_matricula_evento();
alter table public.cd_matriculas enable row level security;
alter table public.cd_matriculas force row level security;
create policy tenant_isolation on public.cd_matriculas for all to authenticated
 using(igreja_id=public.current_igreja_id()
   and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
   and session_user not in ('authenticator','authenticated','anon'))
 with check(igreja_id=public.current_igreja_id()
   and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
   and session_user not in ('authenticator','authenticated','anon'));
revoke all on public.cd_matriculas from public,anon,authenticated,service_role;
grant select on public.cd_matriculas to authenticated;
grant insert(id,igreja_id,turma_id,modulo_id,modulo_numero,pessoa_id,origem_aptidao,criada_por) on public.cd_matriculas to authenticated;
grant update(ativa,origem_aptidao,criada_por,criada_em,cancelada_por,cancelada_em) on public.cd_matriculas to authenticated;
alter table public.cd_matricula_eventos enable row level security;
alter table public.cd_matricula_eventos force row level security;
create policy tenant_isolation on public.cd_matricula_eventos for all to authenticated
 using(igreja_id=public.current_igreja_id()
   and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
   and session_user not in ('authenticator','authenticated','anon'))
 with check(igreja_id=public.current_igreja_id()
   and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
   and session_user not in ('authenticator','authenticated','anon'));
revoke all on public.cd_matricula_eventos from public,anon,authenticated,service_role;
grant select on public.cd_matricula_eventos to authenticated;
-- Only the trigger writes events; backend can read, never edit/delete history.
-- Rollback: revert callers and preserve all enrollment/event records first.
-- drop table public.cd_matricula_eventos;
-- drop trigger cd_matricula_evento on public.cd_matriculas;
-- drop function public.cd_matricula_evento();
-- drop table public.cd_matriculas;
-- alter table public.cd_modulos drop constraint cd_modulos_numero_key;
