-- ============================================================================
-- PastorAI — Migration 20260801_031500_calendar_account_identity_binding
-- ACCOUNT_IDENTITY_RISK — amarra a INTENÇÃO do admin a uma identidade Google
-- VERIFICADA antes de persistir qualquer token.
--
-- Problema fechado: até aqui nada no fluxo dizia QUAL conta Google consentiu.
-- `state`, `flowSecret` e PKCE falam todos do lado PastorAI — PKCE, em
-- particular, NÃO impede que alguém abra a URL de autorização ORIGINAL noutro
-- navegador e consinta com outra conta (o code sai amarrado ao MESMO
-- code_challenge, então a troca sucede).
--
-- Desenho: o admin declara o e-mail Google exato ANTES do redirect
-- (`calendar_oauth_flows.expected_email`); o `finish` troca o code, lê o
-- endpoint OIDC de userinfo e só persiste se o e-mail VERIFICADO bater. A
-- identidade aceita fica registrada em `calendar_sync`.
--
-- `google_account_sub` é o identificador ESTÁVEL da conta e é ele que decide
-- continuidade: preservar refresh token e a agenda escolhida só quando o sub
-- não muda. O e-mail muda de dono ao longo do tempo; o sub não.
--
-- NULL nas colunas novas de `calendar_sync` = conexão LEGADA, feita antes deste
-- binding. Sem backfill: não existe fonte de verdade retroativa sobre qual conta
-- autorizou, e inventar uma seria pior que registrar a ausência. O painel mostra
-- "Conta Google não registrada" e oferece registrar sem desconectar.
--
-- `expected_email` é nullable no schema pelo mesmo motivo — fluxos criados antes
-- desta migration. A APLICAÇÃO sempre grava, e um NULL falha fechado no `finish`.
--
-- PRIVILÉGIOS/RLS: `ADD COLUMN` herda os GRANTs e as policies da tabela. Esta
-- migration NÃO concede, revoga nem cria policy — de propósito. `calendar_sync`
-- e `calendar_oauth_flows` mantêm exatamente a superfície que já tinham.
--
-- Aditiva e idempotente (`IF NOT EXISTS`). Não altera
-- 20260731_120000_calendar_oauth_flows_pkce.sql.
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

begin;

-- ---- calendar_oauth_flows: a intenção declarada antes do redirect ----------
alter table calendar_oauth_flows
  add column if not exists expected_email text null;

-- Resultado durável para reconciliar resposta HTTP perdida sem inferir
-- sucesso pela conexão anterior. consumed_at preenchido + result NULL é
-- processamento em curso; o replay devolve 202 e preserva o flowSecret.
alter table calendar_oauth_flows
  add column if not exists finish_result text null
    constraint ck_calendar_oauth_flows_finish_result
    check (finish_result in ('connected', 'failed'));

alter table calendar_oauth_flows
  add column if not exists finished_at timestamptz null;

comment on column calendar_oauth_flows.expected_email is
  'Conta Google que o admin declarou antes do consentimento, normalizada '
  '(trim + lowercase). O finish compara o e-mail verificado no userinfo contra '
  'este valor. NULL = fluxo legado anterior ao binding; falha fechado no finish.';

comment on column calendar_oauth_flows.finish_result is
  'Resultado durável do finish (connected|failed). NULL após consumo significa '
  'processamento em curso; permite replay idempotente após resposta perdida.';

comment on column calendar_oauth_flows.finished_at is
  'Versão da conexão produzida por este fluxo; coincide com '
  'calendar_sync.connected_em quando finish_result=connected.';

-- ---- calendar_sync: a identidade que de fato autorizou ---------------------
alter table calendar_sync
  add column if not exists google_account_email text null;

alter table calendar_sync
  add column if not exists google_account_sub text null;

alter table calendar_sync
  add column if not exists connected_by_app_user_id uuid null
    references app_users(id) on delete set null;

alter table calendar_sync
  add column if not exists connected_em timestamptz null;

comment on column calendar_sync.google_account_email is
  'E-mail VERIFICADO (userinfo, email_verified=true) da conta Google conectada. '
  'NULL = conexão legada, anterior ao binding de identidade.';

comment on column calendar_sync.google_account_sub is
  'Identificador estável (OIDC sub) da conta Google conectada. É ele que decide '
  'continuidade: preservar refresh token e a agenda escolhida só quando não '
  'muda. NULL = conexão legada; nesse caso a reconexão exige refresh_token novo.';

comment on column calendar_sync.connected_by_app_user_id is
  'App_user que concluiu a conexão. ON DELETE SET NULL — apagar o usuário não '
  'pode derrubar a integração da igreja.';

comment on column calendar_sync.connected_em is
  'Quando a identidade Google atual foi aceita pelo finish.';

commit;
