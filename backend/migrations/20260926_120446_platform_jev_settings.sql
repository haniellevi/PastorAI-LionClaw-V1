-- Configuração da triagem Jev (TypeSafe) editável no Console da Plataforma.
-- Processo simples do MVP: aplicação transacional por scripts/migrate.py, com
-- backup antes e revisão da Sarah em PROD.
--
-- Linha única (id = 1), plano de plataforma sem igreja_id, como
-- platform_orchestrator: só o backend com papel de serviço (BYPASSRLS) lê e
-- grava. A chave fica cifrada (Fernet, SECRETS_ENCRYPTION_KEY) e nunca volta à
-- tela. Campo nulo cai no valor do ambiente. ALLOW_REAL_SENDS e a URL da API
-- continuam só no ambiente, de propósito. Idempotente.

create table if not exists public.platform_jev_settings (
  id                 smallint primary key default 1 check (id = 1),
  api_key_encrypted  text,
  api_key_updated_at timestamptz,
  modelo             text check (modelo is null or modelo ~ '^jev-[a-z0-9.-]{1,40}$'),
  timeout_seconds    numeric(4, 1)
    check (timeout_seconds is null or (timeout_seconds > 0 and timeout_seconds <= 10)),
  igreja_ids         uuid[] not null default '{}',
  dpa_assinado_em    date,
  updated_at         timestamptz not null default now(),
  updated_by         uuid,
  -- Igreja em modo sombra envia texto pastoral a processador terceiro: exige
  -- DPA registrado (AGENTS.md).
  constraint platform_jev_settings_igrejas_exigem_dpa
    check (cardinality(igreja_ids) = 0 or dpa_assinado_em is not null)
);

alter table public.platform_jev_settings enable row level security;

drop policy if exists service_role_bypass_only on public.platform_jev_settings;
create policy service_role_bypass_only on public.platform_jev_settings
  as restrictive for all to public
  using (false) with check (false);

revoke all on table public.platform_jev_settings from public;
do $$ begin
  revoke all on table public.platform_jev_settings from anon;
exception when undefined_object then null; end $$;
do $$ begin
  revoke all on table public.platform_jev_settings from authenticated;
exception when undefined_object then null; end $$;

-- Rollback:
-- drop table if exists public.platform_jev_settings;
