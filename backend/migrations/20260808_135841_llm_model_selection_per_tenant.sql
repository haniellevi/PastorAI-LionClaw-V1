-- ============================================================================
-- PastorAI — seleção de modelo OpenAI por tenant (US-27 / RNF-20)
--
-- A escolha fica na mesma linha 1:1 da credencial BYO da igreja. O default
-- econômico evita aumento silencioso de custo em tenants já existentes.
-- ============================================================================

begin;

alter table llm_credentials
  add column if not exists modelo text;

update llm_credentials
   set modelo = 'gpt-5.6-luna'
 where modelo is null
    or modelo not in ('gpt-5.6-luna', 'gpt-5.6-terra', 'gpt-5.6-sol');

alter table llm_credentials
  alter column modelo set default 'gpt-5.6-luna',
  alter column modelo set not null;

alter table llm_credentials
  drop constraint if exists llm_credentials_modelo_check;

alter table llm_credentials
  add constraint llm_credentials_modelo_check
  check (modelo in ('gpt-5.6-luna', 'gpt-5.6-terra', 'gpt-5.6-sol'));

comment on column llm_credentials.modelo is
  'Modelo OpenAI permitido para a igreja; chave BYO permanece cifrada.';

commit;
