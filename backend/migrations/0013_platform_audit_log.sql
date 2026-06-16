-- ============================================================================
-- PastorAI 1.0 — Migration 0013: platform_audit_log (M3 / auditoria do console)
-- Registra as AÇÕES cross-tenant do master no console (US-42/43): quem provisionou,
-- aprovou, suspendeu, editou ou excluiu qual igreja/plano. Plano de PLATAFORMA,
-- sem igreja_id (igual a platform_admins): o master atua sobre TODAS as igrejas.
--
-- Sem FK em actor_id/alvo_id de propósito: é um LOG HISTÓRICO imutável — excluir
-- a igreja (ou o app_user do admin) NÃO apaga o rastro do que aconteceu. Os
-- e-mails/nomes ficam cacheados para legibilidade mesmo após o alvo sumir.
--
-- Segurança: RLS habilitada e SEM policy => só o service role (BYPASSRLS) lê/grava
-- (o master via get_platform_admin, que não aplica tenant context). Revoke
-- explícito de authenticated/anon como defesa em profundidade. Idempotente.
-- ============================================================================

begin;

create table if not exists platform_audit_log (
  id           uuid primary key default gen_random_uuid(),
  actor_id     uuid,                 -- app_user id do platform admin (sem FK: histórico)
  actor_email  text,                 -- cache p/ legibilidade
  acao         text not null,        -- provisionar | aprovar | editar | excluir | plano_criar | plano_editar | plano_excluir
  alvo_tipo    text not null,        -- 'igreja' | 'plano'
  alvo_id      uuid,                 -- sem FK: o alvo pode ter sido excluído
  alvo_nome    text,
  detalhe      jsonb,                -- {de:.., para:..} etc.
  created_at   timestamptz not null default now()
);

create index if not exists idx_platform_audit_log_created
  on platform_audit_log (created_at desc);

alter table platform_audit_log enable row level security;

do $$ begin
  revoke all on table platform_audit_log from authenticated;
exception when undefined_object then null; end $$;
do $$ begin
  revoke all on table platform_audit_log from anon;
exception when undefined_object then null; end $$;

comment on table platform_audit_log is
  'Log de auditoria das ações cross-tenant do console master (M3 / US-42/43). Plano de plataforma, sem igreja_id; histórico imutável (sem FK no alvo). Acesso só via service role (BYPASSRLS). Ver migration 0013.';

commit;
