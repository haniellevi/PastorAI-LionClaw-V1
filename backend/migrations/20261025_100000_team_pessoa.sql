-- Vínculo de identidade: falha sem alterar dados se houver duplicidade legada.
set local lock_timeout = '2s';
create unique index app_users_pessoa_unica_por_igreja
  on public.app_users(igreja_id,pessoa_id) where pessoa_id is not null;

-- Auditoria técnica, sem nomes, e-mails, telefone ou conteúdo pastoral.
create table public.team_pessoa_eventos (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null references public.igrejas(id) on delete cascade,
  actor_id uuid not null,
  usuario_id uuid not null,
  operacao text not null check (operacao in ('vincular','desvincular')),
  criado_em timestamptz not null default clock_timestamp(),
  foreign key(igreja_id,actor_id) references public.app_users(igreja_id,id) on delete cascade,
  foreign key(igreja_id,usuario_id) references public.app_users(igreja_id,id) on delete cascade
);
alter table public.team_pessoa_eventos enable row level security;
alter table public.team_pessoa_eventos force row level security;
create policy tenant_isolation on public.team_pessoa_eventos to authenticated
  using (igreja_id=public.current_igreja_id()
    and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
    and session_user not in ('authenticator','authenticated','anon'))
  with check (igreja_id=public.current_igreja_id()
    and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
    and session_user not in ('authenticator','authenticated','anon'));
revoke all on public.team_pessoa_eventos from public,anon,authenticated,service_role;
grant select,insert on public.team_pessoa_eventos to authenticated;
-- Rollback: reverter callers e preservar auditoria aprovada antes de remover.
-- drop table public.team_pessoa_eventos;
-- drop index public.app_users_pessoa_unica_por_igreja;
