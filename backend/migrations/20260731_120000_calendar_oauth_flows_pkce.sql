-- ============================================================================
-- PastorAI — Migration 20260731_120000_calendar_oauth_flows_pkce
-- OAUTH-CALENDAR-V1 — fluxos OAuth do Google Calendar em voo (PKCE S256).
--
-- Substitui o `state` JWT auto-contido por um fluxo com estado no servidor. O
-- callback público (`GET /calendar/callback`) deixa de trocar o `code` e passa
-- a apenas ESTACIONÁ-LO nesta tabela; quem troca é `POST /calendar/connect/
-- finish`, autenticado por Bearer, que compara app_user_id + igreja_id e
-- consome a linha atomicamente antes de falar com o Google.
--
-- DOIS segredos distintos, ambos guardados só como sha256 hex:
--   * `state_hash`       — chave que o callback PÚBLICO apresenta. O `state`
--                          viaja para o Google e cai no access log.
--   * `flow_secret_hash` — chave que o `finish` AUTENTICADO apresenta. O
--                          `flowSecret` nunca sai das origens do painel
--                          (sessionStorage, particionado por origem).
-- Nunca persistir os valores brutos: um dump/backup não pode permitir concluir
-- nem queimar fluxo alheio.
--
-- `verifier_encrypted` (PKCE) e `code_encrypted` são anulados no mesmo UPDATE
-- do consumo — retenção certa é zero. O purge do cron-worker apaga expirados.
--
-- PRIVILÉGIOS: base determinística. `REVOKE ... FROM PUBLIC` NÃO remove o que
-- foi concedido a `authenticated` ou a `anon` (são concessões distintas), e o
-- bootstrap do Supabase concede a esses roles via ALTER DEFAULT PRIVILEGES. Por
-- isso cada role tem a própria linha. DELETE fica de fora POR DESENHO: só o
-- cron-worker, que roda no papel de conexão (BYPASSRLS), apaga. A policy RLS
-- `FOR ALL` é PERMISSIVA — ela não nega nada que o GRANT já permitiu, então não
-- substitui a ausência do privilégio DELETE.
--
-- ATENÇÃO: o callback público é anônimo e usa `get_db`, que não aplica tenant
-- context; ele roda no papel de conexão com BYPASSRLS. A RLS abaixo protege os
-- caminhos AUTENTICADOS (`connect` e `finish`), NUNCA o callback — a única
-- autorização dele é o `state` inadivinhável mais as condições do WHERE.
--
-- Tabela nova, sem dado a migrar => idempotente via IF NOT EXISTS.
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

begin;

create table if not exists calendar_oauth_flows (
    id uuid primary key default gen_random_uuid(),
    state_hash text not null,
    flow_secret_hash text not null,
    igreja_id uuid not null references igrejas(id) on delete cascade,
    app_user_id uuid not null references app_users(id) on delete cascade,
    return_origin text not null,
    verifier_encrypted text,
    code_encrypted text,
    expires_at timestamptz not null,
    consumed_at timestamptz,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now(),
    constraint calendar_oauth_flows_state_hash_key unique (state_hash),
    constraint calendar_oauth_flows_flow_secret_hash_key unique (flow_secret_hash)
);

comment on table calendar_oauth_flows is
    'Fluxos OAuth do Google Calendar em voo (PKCE S256, uso unico, TTL curto).';

-- Sem índice em expires_at: uma linha por clique em "Conectar", purgada a cada
-- tick do cron-worker. Seq scan sobre dezenas de linhas é mais barato que
-- manter índice em todo INSERT. Reavaliar acima de ~10k linhas vivas.

-- RLS por tenant, mesmo padrão de calendar_sync (20260623_122044).
alter table calendar_oauth_flows enable row level security;
drop policy if exists tenant_isolation on calendar_oauth_flows;
create policy tenant_isolation on calendar_oauth_flows
    for all
    using (igreja_id = current_igreja_id())
    with check (igreja_id = current_igreja_id());

-- Base determinística de privilégios (ver cabeçalho).
revoke all privileges on table calendar_oauth_flows from public;
revoke all privileges on table calendar_oauth_flows from authenticated;
revoke all privileges on table calendar_oauth_flows from anon;

-- Superfície autenticada: connect (INSERT), finish (SELECT + UPDATE).
grant select, insert, update on table calendar_oauth_flows to authenticated;

commit;
