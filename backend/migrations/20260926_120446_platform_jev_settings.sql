-- Configuração da triagem Jev (TypeSafe) editável no Console da Plataforma.
-- Processo simples do MVP: aplicação transacional por scripts/migrate.py, com
-- backup antes e revisão da Sarah em PROD.
--
-- Linha única (id = 1), plano de plataforma sem igreja_id, como
-- platform_orchestrator: só o backend com papel de serviço (BYPASSRLS) lê e
-- grava. A chave fica cifrada (Fernet, SECRETS_ENCRYPTION_KEY) e nunca volta à
-- tela. Campo nulo cai no valor do ambiente. ALLOW_REAL_SENDS e a URL da API
-- continuam só no ambiente, de propósito. Idempotente e fail-closed: a
-- pós-condição no fim aborta a transação se a tabela não ficar como esperado.

create table if not exists public.platform_jev_settings (
  id                 smallint primary key default 1,
  api_key_encrypted  text,
  api_key_updated_at timestamptz,
  modelo             text,
  timeout_seconds    numeric(4, 1),
  igreja_ids         uuid[] not null default '{}',
  dpa_assinado_em    date,
  updated_at         timestamptz not null default now(),
  updated_by         uuid,
  constraint platform_jev_settings_linha_unica check (id = 1),
  constraint platform_jev_settings_modelo_valido
    check (modelo is null or modelo ~ '^jev-[a-z0-9.-]{1,40}$'),
  constraint platform_jev_settings_timeout_valido
    check (timeout_seconds is null or (timeout_seconds > 0 and timeout_seconds <= 10)),
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

-- Pós-condição: uma tabela pré-existente com outro formato passaria calada
-- pelo `if not exists` acima; aqui a transação inteira aborta.
do $$
declare
  alvo constant regclass := 'public.platform_jev_settings'::regclass;
  papel text;
  privilegio text;
  faltando text[];
begin
  if not (select relrowsecurity from pg_class where oid = alvo) then
    raise exception 'platform_jev_settings: RLS desligada';
  end if;
  if (select count(*) from pg_policy where polrelid = alvo) <> 1
     or not exists (
       select 1 from pg_policy
       where polrelid = alvo
         and polname = 'service_role_bypass_only'
         and not polpermissive
         and polcmd = '*'
         and polroles = array[0::oid]
         and pg_get_expr(polqual, polrelid) = 'false'
         and pg_get_expr(polwithcheck, polrelid) = 'false'
     ) then
    raise exception 'platform_jev_settings: policy diferente da esperada';
  end if;
  select array_agg(nome) into faltando
  from unnest(array[
    'platform_jev_settings_linha_unica',
    'platform_jev_settings_modelo_valido',
    'platform_jev_settings_timeout_valido',
    'platform_jev_settings_igrejas_exigem_dpa'
  ]) as nome
  where not exists (
    select 1 from pg_constraint
    where conrelid = alvo and conname = nome and contype = 'c'
  );
  if faltando is not null then
    raise exception 'platform_jev_settings: CHECK ausente: %', faltando;
  end if;
  foreach papel in array array['anon', 'authenticated'] loop
    continue when not exists (select 1 from pg_roles where rolname = papel);
    foreach privilegio in array array['SELECT', 'INSERT', 'UPDATE', 'DELETE'] loop
      if has_table_privilege(papel, alvo, privilegio) then
        raise exception 'platform_jev_settings: % ainda tem %', papel, privilegio;
      end if;
    end loop;
  end loop;
end $$;

-- Rollback:
-- drop table if exists public.platform_jev_settings;
