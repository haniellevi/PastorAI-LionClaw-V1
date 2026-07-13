-- ============================================================================
-- PastorAI — Migration 20260713_032015 — M7B-W3.2A: preflight + arquivamento
-- seguro de Pessoa.
--
-- Duas peças, ambas aditivas:
--
--   (1) consolidacoes.abandonada_em / abandonada_motivo — a única exceção
--       aprovada de encerramento automático no arquivamento (mission W3.2A):
--       uma consolidação ABERTA (concluida=false AND abandonada_em IS NULL) da
--       Pessoa que está sendo arquivada é marcada "abandonada" NA MESMA
--       transação do archive. O domínio `consolidacoes` não tinha nenhuma
--       coluna de status (só `concluida boolean` + `progresso int`) — sem enum
--       a estender, este par de colunas nullable espelha exatamente o padrão
--       `pessoas.arquivada_em/motivo` da migration 20260713_013054 (W3.1), sem
--       inventar enum/estado novo.
--
--   (2) pessoa_arquivamento_evento — trilha de auditoria APPEND-ONLY dos
--       eventos de arquivamento de Pessoa. `platform_audit_log` NÃO serve:
--       é do plano de plataforma (sem igreja_id, sem RLS de tenant — console
--       master cross-tenant). Esta tabela é tenant-aware, no mesmo padrão de
--       `celula_solicitacao_evento` (migration 20260705_120300): igreja_id
--       próprio + RLS própria + trigger que bloqueia UPDATE/DELETE diretos.
--       `acao` já inclui 'reativada' no CHECK (schema-only — o endpoint de
--       reativação fica para PR posterior) para a trilha aceitar esse evento
--       futuro sem precisar de outra migration alterando o CHECK.
--
-- CREATE/ALTER/índices/trigger transacionais + idempotentes. Não aplicada
-- automaticamente: rodar manualmente no Supabase (DEV primeiro).
-- ============================================================================

begin;

-- ----------------------------------------------------------------------------
-- (1) consolidacoes — encerramento "abandonada" (exceção aprovada do archive)
-- ----------------------------------------------------------------------------
alter table consolidacoes
  add column if not exists abandonada_em timestamptz,
  add column if not exists abandonada_motivo text;

comment on column consolidacoes.abandonada_em is
  'W3.2A: consolidação encerrada como abandonada (efeito automático do arquivamento de Pessoa). NULL = não abandonada. Independente de concluida.';
comment on column consolidacoes.abandonada_motivo is
  'W3.2A: motivo técnico do abandono (ex.: arquivamento da Pessoa).';

-- ----------------------------------------------------------------------------
-- (2) pessoa_arquivamento_evento — trilha append-only
-- ----------------------------------------------------------------------------
create table if not exists pessoa_arquivamento_evento (
  id         uuid primary key default gen_random_uuid(),
  igreja_id  uuid not null references igrejas(id) on delete cascade,
  pessoa_id  uuid not null references pessoas(id) on delete cascade,
  ator_id    uuid references app_users(id) on delete set null,
  acao       text not null,
  motivo     text not null,
  created_at timestamptz not null default now(),
  constraint pessoa_arquivamento_evento_acao_chk check (acao in (
    'arquivada', 'reativada'))
);

comment on table pessoa_arquivamento_evento is
  'W3.2A: trilha de auditoria APPEND-ONLY do arquivamento/reativação de Pessoa. Blindada pelo trigger trg_pessoa_arquivamento_evento_append_only: UPDATE/DELETE diretos levantam exceção. igreja_id próprio + RLS própria. NÃO é platform_audit_log (aquele é do plano de plataforma, sem tenant). "reativada" no CHECK é headroom de schema para PR futuro — não implementado aqui.';

create index if not exists idx_pessoa_arquivamento_evento_igreja
  on pessoa_arquivamento_evento (igreja_id);
create index if not exists idx_pessoa_arquivamento_evento_pessoa
  on pessoa_arquivamento_evento (igreja_id, pessoa_id, created_at);

alter table pessoa_arquivamento_evento enable row level security;
drop policy if exists tenant_isolation on pessoa_arquivamento_evento;
create policy tenant_isolation on pessoa_arquivamento_evento
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

-- ----------------------------------------------------------------------------
-- Trigger append-only (mesmo padrão de trg_celula_solicitacao_evento_append_only,
-- migration 20260705_120300): só bloqueia a operação de TOPO
-- (pg_trigger_depth() = 1). DELETE em CASCADE (igreja/pessoa pai apagados) e o
-- UPDATE de ator_id via ON DELETE SET NULL (app_user apagado) rodam dentro do
-- trigger de RI referencial (depth > 1) e são PERMITIDOS — sem esse carve-out,
-- um DELETE legítimo em cascata abortaria com 'append-only'.
-- ----------------------------------------------------------------------------
create or replace function trg_pessoa_arquivamento_evento_append_only()
returns trigger
language plpgsql
set search_path = pg_catalog, pg_temp
as $$
begin
  if pg_trigger_depth() > 1 then
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  raise exception 'append-only';
end;
$$;

drop trigger if exists trg_pessoa_arquivamento_evento_append_only
  on pessoa_arquivamento_evento;
create trigger trg_pessoa_arquivamento_evento_append_only
  before update or delete on pessoa_arquivamento_evento
  for each row execute function trg_pessoa_arquivamento_evento_append_only();

commit;
