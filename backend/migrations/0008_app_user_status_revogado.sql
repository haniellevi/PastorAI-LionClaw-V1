-- ============================================================================
-- PastorAI 1.0 — Migration 0008: status "revogado" para app_users
-- RF-04 / US-03 / SPEC S3 — revogacao de acesso de usuarios da igreja.
--
-- Acrescenta o valor 'revogado' ao enum app_user_status (antes: 'ativo',
-- 'convidado'). A revogacao e soft: o app_user permanece na tabela com
-- status='revogado' para preservar auditoria/historico; o bloqueio efetivo
-- de acesso e aplicado no backend (get_current_user + login).
--
-- Idempotente: ADD VALUE IF NOT EXISTS — re-executar e no-op.
-- PG 12+ permite ADD VALUE dentro de transacao desde que o valor nao seja
-- usado na mesma transacao (aqui so e adicionado). Supabase roda PG 15.
-- ============================================================================

begin;

alter type app_user_status add value if not exists 'revogado';

commit;
