-- ============================================================================
-- 0009 (Fase 1, etapa 2): seed das telas do papel 'operador' + migracao dos
-- registros de system_managers para o RBAC unificado (app_users + user_roles).
--
-- Pre-requisito: a 0008 ja committada (os enums ja aceitam 'operador').
-- Roda como service role (postgres, BYPASSRLS) — igual aos seeds 0005/0007 —
-- portanto insere igreja_id explicito e NAO depende de current_igreja_id().
-- Idempotente: ON CONFLICT DO NOTHING + WHERE NOT EXISTS.
--
-- NAO dropa a tabela system_managers nem o enum system_manager_papel: mantidos
-- para rollback. A remocao definitiva fica para uma migration posterior, apos
-- validar que os dados foram migrados e que a tela/rotas #gerentes sairam.
-- ============================================================================

begin;

-- (1) Telas padrao do papel 'operador' (atendimento + cadastros, sem
--     Configuracao), semeadas para TODAS as igrejas existentes. O admin pode
--     ajustar depois na tela #permissoes (matriz papel x tela).
insert into role_permissions (igreja_id, papel, tela)
select i.id, 'operador'::role_perm_papel, t.tela
from igrejas i
cross join (values
  ('dashboard'), ('inbox'), ('contatos'), ('ganhar'),
  ('celulas'), ('relatorios'), ('comunicados'), ('calendario')
) as t(tela)
on conflict (igreja_id, papel, tela) do nothing;

-- (2) Migrar system_managers -> app_users + user_roles.
--     (2a) cria o app_user (convidado, sem clerk_user_id/pessoa_id) por
--          (igreja_id, email), deduplicando contra app_users ja existente do
--          mesmo tenant (lower(email)). clerk_user_id fica NULL (UNIQUE permite
--          multiplos NULL no Postgres).
insert into app_users (igreja_id, nome, email, status)
select sm.igreja_id, sm.nome, lower(sm.email), 'convidado'
from system_managers sm
where not exists (
  select 1 from app_users au
  where au.igreja_id = sm.igreja_id
    and lower(au.email) = lower(sm.email)
);

--     (2b) garante o papel mapeado em user_roles:
--          admin_sistema -> 'admin' ; operador -> 'operador' ;
--          papel_operacional NULL -> 'operador' (seguranca).
insert into user_roles (igreja_id, user_id, papel)
select au.igreja_id, au.id,
       (case sm.papel_operacional
          when 'admin_sistema' then 'admin'
          when 'operador'      then 'operador'
          else 'operador'
        end)::user_role_papel
from system_managers sm
join app_users au
  on au.igreja_id = sm.igreja_id
 and lower(au.email) = lower(sm.email)
on conflict (user_id, papel) do nothing;

commit;
