-- Preserva identidades de platform_admins quando a igreja e seus dados são excluídos.
-- Processo simples do MVP: aplicação transacional por scripts/migrate.py.
-- A aplicação em qualquer ambiente compartilhado pertence a uma operação futura.
-- O serviço desassocia apenas usuários presentes na allowlist platform_admins;
-- backend e RLS continuam recusando contexto tenant para igreja_id NULL.

alter table public.app_users alter column igreja_id drop not null;
alter table public.app_users enable row level security;
alter table public.app_users force row level security;
revoke all on table public.app_users from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    revoke all on table public.app_users from anon;
  end if;
end $$;
-- Os grants explícitos já existentes para authenticated e service_role ficam
-- preservados; não se concede acesso novo a identidades sem tenant.
-- tenant_isolation permanece usando igreja_id = current_igreja_id(), com
-- USING e WITH CHECK: NULL não satisfaz a policy e não concede acesso global.
-- Rollback, somente depois de reassociar/remover identidades sem tenant:
-- ALTER TABLE public.app_users ALTER COLUMN igreja_id SET NOT NULL;
-- O PostgreSQL recusa esse rollback se ainda existir qualquer igreja_id NULL.
