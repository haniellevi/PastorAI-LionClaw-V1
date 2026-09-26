-- Preserva identidades de platform_admins quando a igreja e seus dados são excluídos.
-- Processo simples do MVP: aplicação transacional por scripts/migrate.py.
-- A aplicação em qualquer ambiente compartilhado pertence a uma operação futura.
-- O serviço desassocia apenas usuários presentes na allowlist platform_admins;
-- backend e RLS continuam recusando contexto tenant para igreja_id NULL.

alter table public.app_users alter column igreja_id drop not null;
alter table public.app_users enable row level security;
revoke all on table public.app_users from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    revoke all on table public.app_users from anon;
  end if;
end $$;
-- Preserva o bypass do owner usado pelo helper SECURITY DEFINER
-- current_igreja_id(); não acrescenta FORCE RLS à tabela consultada pelo helper.
-- A allowlist continua sendo a única exceção ao vínculo tenant obrigatório.
-- Ambos os lados travam a linha consultada: snapshots REPEATABLE READ antigos
-- não podem aceitar membership já removido. NOWAIT evita o ciclo de espera;
-- disputas podem causar 55P03/40001.
-- após rollback, repetir a transação inteira e revalidar o estado.
create or replace function public.require_tenant_or_platform_admin()
returns trigger language plpgsql security definer set search_path = pg_catalog
as $$
begin
  if new.igreja_id is null then
    perform 1 from public.platform_admins
      where app_user_id = new.id for key share;
    if not found then
      raise exception 'igreja_id NULL exige platform_admin'
        using errcode = '23514';
    end if;
  end if;
  return new;
end;
$$;
revoke all on function public.require_tenant_or_platform_admin() from public;
drop trigger if exists require_tenant_or_platform_admin on public.app_users;
create trigger require_tenant_or_platform_admin
before insert or update of igreja_id, id on public.app_users
for each row execute function public.require_tenant_or_platform_admin();

create or replace function public.preserve_detached_platform_admin()
returns trigger language plpgsql security definer set search_path = pg_catalog
as $$
declare
  tenant_id uuid;
begin
  if tg_op = 'TRUNCATE' then
    raise exception 'TRUNCATE de platform_admins não é permitido; use DELETE validado'
      using errcode = '23514';
  end if;
  if tg_op = 'UPDATE' and new.app_user_id = old.app_user_id then
    return new;
  end if;
  select igreja_id into tenant_id from public.app_users
    where id = old.app_user_id for update nowait;
  if found and tenant_id is null then
    raise exception 'Reassocie a igreja antes de remover o platform_admin destacado'
      using errcode = '23514';
  end if;
  if tg_op = 'DELETE' then
    return old;
  end if;
  return new;
end;
$$;
revoke all on function public.preserve_detached_platform_admin() from public;
drop trigger if exists preserve_detached_platform_admin on public.platform_admins;
create trigger preserve_detached_platform_admin
before delete or update of app_user_id on public.platform_admins
for each row execute function public.preserve_detached_platform_admin();
drop trigger if exists preserve_detached_platform_admin_truncate on public.platform_admins;
create trigger preserve_detached_platform_admin_truncate
before truncate on public.platform_admins
for each statement execute function public.preserve_detached_platform_admin();

-- Não aceitar identidades órfãs que já existam antes desta aplicação.
do $$
begin
  if exists (
    select 1 from public.app_users u
    where u.igreja_id is null and not exists (
      select 1 from public.platform_admins a where a.app_user_id = u.id
    )
  ) then
    raise exception 'Existe app_user sem igreja fora de platform_admins'
      using errcode = '23514';
  end if;
end $$;
-- Os grants explícitos já existentes para authenticated e service_role ficam
-- preservados; não se concede acesso novo a identidades sem tenant.
-- tenant_isolation permanece usando igreja_id = current_igreja_id(), com
-- USING e WITH CHECK: NULL não satisfaz a policy e não concede acesso global.
-- Rollback, somente depois de reassociar/remover identidades sem tenant:
-- ALTER TABLE public.app_users ALTER COLUMN igreja_id SET NOT NULL;
-- O PostgreSQL recusa esse rollback se ainda existir qualquer igreja_id NULL.
-- Depois do SET NOT NULL acima, remover somente os guards desta migration:
-- DROP TRIGGER require_tenant_or_platform_admin ON public.app_users;
-- DROP TRIGGER preserve_detached_platform_admin ON public.platform_admins;
-- DROP TRIGGER preserve_detached_platform_admin_truncate ON public.platform_admins;
-- DROP FUNCTION public.require_tenant_or_platform_admin();
-- DROP FUNCTION public.preserve_detached_platform_admin();
