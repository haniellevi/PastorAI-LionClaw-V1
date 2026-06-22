-- ============================================================================
-- PastorAI 1.0 — Migration 0017: status "revogado" para app_users
-- RF-04 / US-03 / SPEC S3 — revogacao de acesso de usuarios da igreja.
--
-- Acrescenta o valor 'revogado' ao enum app_user_status (antes: 'ativo',
-- 'convidado'). A revogacao e soft: o app_user permanece na tabela com
-- status='revogado' para preservar auditoria/historico; o bloqueio efetivo
-- de acesso e aplicado no backend (get_current_user + login).
--
-- IMPORTANTE (PostgreSQL): ALTER TYPE ... ADD VALUE NAO pode ser referenciado
-- na MESMA transacao em que e adicionado, e em PG<12 nem roda dentro de
-- BEGIN/COMMIT. Por isso esta migration NAO abre transacao: o statement
-- auto-commita. IF NOT EXISTS => idempotente (re-rodar e no-op).
-- ============================================================================

alter type app_user_status add value if not exists 'revogado';
