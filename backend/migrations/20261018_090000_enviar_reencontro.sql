-- Enviar PR3: extend official person milestones, never project leadership.
set local lock_timeout = '2s';
alter table public.uv_marcos drop constraint uv_marcos_tipo_check;
alter table public.uv_marcos add constraint uv_marcos_tipo_check
  check(tipo in ('encontro','batismo','reencontro'));
alter table public.uv_marcos
  add column revogada boolean not null default false,
  add column revogada_por uuid,
  add column revogada_em timestamptz,
  add column motivo_revogacao text,
  add constraint uv_marco_revogador_fk foreign key(igreja_id,revogada_por)
    references public.app_users(igreja_id,id),
  add constraint uv_marco_revogacao_coerente check (
    (not revogada and revogada_por is null and revogada_em is null and motivo_revogacao is null) or
    (tipo='reencontro' and revogada and revogada_por is not null and revogada_em>=validada_em
      and revogada_em is not null and motivo_revogacao is not null and length(btrim(motivo_revogacao)) between 1 and 1000));
create function public.uv_revogar_reencontro() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
  if old.tipo <> 'reencontro' or old.revogada or not new.revogada
    or (to_jsonb(new)-array['revogada','revogada_por','revogada_em','motivo_revogacao'])
      is distinct from (to_jsonb(old)-array['revogada','revogada_por','revogada_em','motivo_revogacao']) then
    raise exception 'Marco permite somente revogação definitiva de Reencontro' using errcode='23514';
  end if;
  new.revogada_em := clock_timestamp();
  return new;
end $$;
revoke all on function public.uv_revogar_reencontro() from public,anon,authenticated,service_role;
create trigger uv_reencontro_revogacao before update on public.uv_marcos
  for each row execute function public.uv_revogar_reencontro();
alter table public.uv_marcos enable row level security;
alter table public.uv_marcos force row level security;
-- Official evidence is written exclusively through authorized backend services.
-- JWT-only/PostgREST sessions must not forge validators or revocations.
do $$ declare t text; begin
  foreach t in array array['uv_marcos','uv_conclusoes'] loop
    execute format('drop policy tenant_isolation on public.%I',t);
  execute format('create policy tenant_isolation on public.%I for all to authenticated using(igreja_id=public.current_igreja_id() and igreja_id=nullif(current_setting(''app.tenant_igreja_id'',true),'''')::uuid and session_user not in (''authenticator'',''authenticated'',''anon'')) with check(igreja_id=public.current_igreja_id() and igreja_id=nullif(current_setting(''app.tenant_igreja_id'',true),'''')::uuid and session_user not in (''authenticator'',''authenticated'',''anon''))',t);
  end loop;
end $$;
revoke all on public.uv_marcos from public,anon,authenticated,service_role;
grant select on public.uv_marcos to authenticated;
grant insert(id,igreja_id,pessoa_id,turma_id,matricula_id,tipo,data,anterior_turma,validada_por)
  on public.uv_marcos to authenticated;
grant update(revogada,revogada_por,motivo_revogacao) on public.uv_marcos to authenticated;
-- Official completion must not inherit broad Supabase service-role grants.
revoke all on public.uv_conclusoes from public,anon,service_role;
-- Rollback: restore callers, preserve official Reencontro/revocation records first.
-- Do not remove Reencontro rows to satisfy the former check without approved deletion.
-- drop trigger uv_reencontro_revogacao on public.uv_marcos;
-- drop function public.uv_revogar_reencontro();
-- revoke update(revogada,revogada_por,motivo_revogacao) on public.uv_marcos from authenticated;
-- alter table public.uv_marcos drop constraint uv_marco_revogacao_coerente,
--   drop constraint uv_marco_revogador_fk, drop column revogada, drop column revogada_por,
--   drop column revogada_em, drop column motivo_revogacao;
-- alter table public.uv_marcos drop constraint uv_marcos_tipo_check;
-- alter table public.uv_marcos add constraint uv_marcos_tipo_check check(tipo in ('encontro','batismo'));
-- Keep backend-only policies and service_role revocations during rollback;
-- reopening direct JWT writes to official evidence is not a safe rollback.
