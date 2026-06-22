-- ============================================================================
-- 0008 (Fase 1, etapa 1): aceitar o papel 'operador' nos enums de papel.
--
-- Unificacao de gerente_sistema em user_roles: 'operador' vira papel normal;
-- 'admin_sistema' mapeia para 'admin' (ja existe no enum, nao precisa de ADD).
--
-- IMPORTANTE (PostgreSQL): ALTER TYPE ... ADD VALUE NAO pode ser referenciado
-- na MESMA transacao em que e adicionado, e em PG<12 nem roda dentro de
-- BEGIN/COMMIT. Por isso esta migration NAO abre transacao: cada statement
-- auto-commita. O seed e a migracao de dados que USAM 'operador' ficam na 0009
-- (arquivo separado, transacional, executado depois desta committar).
-- IF NOT EXISTS => idempotente (re-rodar e no-op).
-- ============================================================================

-- user_roles.papel passa a aceitar 'operador'
ALTER TYPE user_role_papel ADD VALUE IF NOT EXISTS 'operador';

-- role_permissions.papel passa a aceitar 'operador' (telas configuraveis na matriz)
ALTER TYPE role_perm_papel ADD VALUE IF NOT EXISTS 'operador';
