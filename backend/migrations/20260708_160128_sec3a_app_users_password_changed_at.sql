-- ============================================================================
-- PastorAI — Migration 20260708_160128_sec3a_app_users_password_changed_at
-- SEC-3A · MEDIO-002 · docs/security/2026-07-08-seg-igreja12-remediation-plan.md
--
-- Adiciona `app_users.password_changed_at` (timestamptz null) — carimbo usado
-- pra invalidar sessões (JWT próprio do PastorAI) emitidas ANTES da última
-- troca/reset de senha. NULL = usuário nunca teve o campo marcado (compat:
-- sessões existentes continuam válidas, ninguém é deslogado no deploy). A
-- partir da próxima troca/reset de senha o campo é preenchido com now() e todo
-- JWT com `iat` anterior a esse timestamp passa a ser rejeitado (ver
-- app/deps.py / app/services/clerk.py).
--
-- Só uma coluna nullable (sem ALTER TYPE) => roda em transação. Idempotente via
-- IF NOT EXISTS. A RLS de `app_users` já cobre a coluna nova — policy é por
-- linha, não por coluna. Não toca BYPASSRLS / set_tenant_context.
--
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

begin;

alter table app_users add column if not exists password_changed_at timestamptz;

commit;
