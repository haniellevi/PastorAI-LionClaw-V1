-- ============================================================================
-- PastorAI — Migration 20260708_172106_sec3b_password_reset_tokens_single_use
-- SEC-3B · MEDIO-003 · docs/security/2026-07-08-seg-igreja12-remediation-plan.md
--
-- Cria `password_reset_tokens`: registro de cada link de "esqueci a senha"
-- emitido, pra impedir que o mesmo token seja resgatado mais de uma vez. O
-- JWT do link (ver app/services/clerk.py) já prova autenticidade/validade/
-- prazo (assinatura + `exp`); esta tabela guarda só o `jti` (identificador
-- aleatório do token, não o token em si) + prazo + carimbo de uso, pra
-- responder "esse jti específico já foi resgatado?" — algo que o JWT sozinho
-- não sabe dizer.
--
-- `jti` não é segredo (sem a assinatura HMAC ele não abre nada) — não precisa
-- de hash, só de unicidade. `used_at` nulo = ainda não resgatado. Ao redefinir
-- a senha, o backend faz `SELECT ... FOR UPDATE` nesta linha antes de marcar
-- `used_at`, fechando a corrida de duas requisições com o mesmo token (ver
-- app/routers/auth.py::reset_password).
--
-- Tabela nova, sem dado a migrar => idempotente via IF NOT EXISTS. Sem
-- igreja_id: é artefato de auth pré-login (mesma categoria de invite/session
-- tokens), não dado de tenant — RLS não se aplica.
--
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

begin;

create table if not exists password_reset_tokens (
    id uuid primary key default gen_random_uuid(),
    jti uuid not null,
    clerk_user_id text not null,
    expires_at timestamptz not null,
    used_at timestamptz,
    created_at timestamptz not null default now(),
    constraint password_reset_tokens_jti_key unique (jti)
);

create index if not exists idx_password_reset_tokens_clerk_user_id
    on password_reset_tokens (clerk_user_id);

commit;
