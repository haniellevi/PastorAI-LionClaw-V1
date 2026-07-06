-- ============================================================================
-- PastorAI — Migration 20260705_120300 — Células PR3-PR9 (d): tabelas
-- `celula_solicitacao` + `celula_solicitacao_evento` (auditoria append-only).
-- Fontes: docs/sprints.json (feat-001.d / feat-008 / feat-009 / feat-010) +
--         docs/design/PRD-CELULAS-SOLICITACOES-APROVACAO.md (§3/4/6/8) +
--         docs/design/CELULAS-DECISOES-FINAIS.md (3.6).
--
-- Entidade Solicitação genérica, extensível por `tipo`, com payload JSONB
-- tipado (validado na app) e trilha de auditoria append-only. A Central NÃO
-- edita o payload; se precisa mudar, pede ajuste (devolve ao líder). Aprovação
-- aplica a mudança de forma transacional (na app, na MESMA transação do evento).
--
--   (1) celula_solicitacao        — a solicitação e seu estado
--   (2) celula_solicitacao_evento — trilha append-only (blindada por trigger)
--
-- Ambas com igreja_id PRÓPRIO + policy tenant_isolation dedicada. FKs de
-- autor/pessoa ON DELETE SET NULL; estruturais (igreja/célula/solicitacao)
-- ON DELETE CASCADE. `updated_at` só em celula_solicitacao (a de evento é
-- append-only: só created_at, sem updated_at e sem trigger de updated_at).
--
-- CREATE/índices/trigger transacionais + idempotentes. Não aplicada
-- automaticamente: rodar manualmente no Supabase (DEV primeiro).
-- ============================================================================

begin;

-- ----------------------------------------------------------------------------
-- (1) celula_solicitacao
-- ----------------------------------------------------------------------------
create table if not exists celula_solicitacao (
  id                 uuid primary key default gen_random_uuid(),
  igreja_id          uuid not null references igrejas(id) on delete cascade,
  celula_id          uuid not null references celulas(id) on delete cascade,
  solicitante_id     uuid references pessoas(id) on delete set null,
  pessoa_id          uuid references pessoas(id) on delete set null,
  tipo               text not null,
  status             text not null default 'aguardando',
  payload_proposto   jsonb not null default '{}'::jsonb,
  payload_atual      jsonb,
  motivo             text,
  observacao_central text,
  decidido_por       uuid references pessoas(id) on delete set null,
  decidido_em        timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz,
  constraint celula_solicitacao_tipo_chk check (tipo in (
    'alterar_dia', 'alterar_horario', 'alterar_endereco', 'alterar_anfitriao',
    'alterar_auxiliar', 'transferir_membro', 'remover_membro', 'multiplicacao')),
  constraint celula_solicitacao_status_chk check (status in (
    'aguardando', 'aprovada', 'rejeitada', 'ajuste_solicitado', 'cancelada'))
);

comment on table celula_solicitacao is
  'Solicitação de alteração sensível / multiplicação, extensível por tipo, com payload JSONB tipado (Células PR3-PR9). igreja_id próprio + RLS própria. solicitante_id/pessoa_id/decidida_por SET NULL; celula_id CASCADE. A Central não edita o payload (3.6).';

create index if not exists idx_celula_solicitacao_igreja
  on celula_solicitacao (igreja_id);
create index if not exists idx_celula_solicitacao_celula
  on celula_solicitacao (igreja_id, celula_id);
create index if not exists idx_celula_solicitacao_status
  on celula_solicitacao (igreja_id, status);

alter table celula_solicitacao enable row level security;
drop policy if exists tenant_isolation on celula_solicitacao;
create policy tenant_isolation on celula_solicitacao
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

-- ----------------------------------------------------------------------------
-- (2) celula_solicitacao_evento — trilha append-only
-- ----------------------------------------------------------------------------
-- Sem updated_at: cada transição é uma linha imutável (quem, de->para, quando,
-- texto). tipo do evento = a transição registrada.
create table if not exists celula_solicitacao_evento (
  id             uuid primary key default gen_random_uuid(),
  igreja_id      uuid not null references igrejas(id) on delete cascade,
  solicitacao_id uuid not null references celula_solicitacao(id) on delete cascade,
  acao           text not null,
  autor_id       uuid references pessoas(id) on delete set null,
  payload_snapshot jsonb not null default '{}'::jsonb,
  de_status      text,
  para_status    text,
  observacao     text,
  created_at     timestamptz not null default now(),
  constraint celula_solicitacao_evento_acao_chk check (acao in (
    'criada', 'reenviada', 'aprovada', 'rejeitada', 'ajuste_solicitado', 'cancelada'))
);

comment on table celula_solicitacao_evento is
  'Trilha de auditoria APPEND-ONLY das transições de uma solicitação (Células PR3-PR9). Blindada pelo trigger trg_celula_solicitacao_evento_append_only: UPDATE/DELETE levantam exceção. igreja_id próprio + RLS própria. Sem updated_at.';

create index if not exists idx_celula_solicitacao_evento_igreja
  on celula_solicitacao_evento (igreja_id);
create index if not exists idx_celula_solicitacao_evento_solicitacao
  on celula_solicitacao_evento (igreja_id, solicitacao_id, created_at);

alter table celula_solicitacao_evento enable row level security;
drop policy if exists tenant_isolation on celula_solicitacao_evento;
create policy tenant_isolation on celula_solicitacao_evento
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

-- ----------------------------------------------------------------------------
-- Trigger append-only: bloqueia UPDATE e DELETE DIRETOS (feitos pela app) na
-- trilha de auditoria. search_path fixado (hardening, mesmo padrão de 0006).
--
-- IMPORTANTE: só bloqueia a operação de TOPO (pg_trigger_depth() = 1). As ações
-- referenciais aninhadas — DELETE em CASCADE ao apagar a solicitação/igreja pai
-- (igreja_id/solicitacao_id ON DELETE CASCADE) e o UPDATE de autor_id via
-- ON DELETE SET NULL ao apagar a pessoa autora — rodam dentro do trigger de RI
-- (depth > 1) e são PERMITIDAS. Sem esse carve-out, um DELETE /igrejas legítimo
-- (ou remover uma pessoa) abortaria com 'append-only'. A imutabilidade que
-- importa (a app nunca reescreve/remove a trilha) continua garantida.
-- ----------------------------------------------------------------------------
create or replace function trg_celula_solicitacao_evento_append_only()
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

drop trigger if exists trg_celula_solicitacao_evento_append_only
  on celula_solicitacao_evento;
create trigger trg_celula_solicitacao_evento_append_only
  before update or delete on celula_solicitacao_evento
  for each row execute function trg_celula_solicitacao_evento_append_only();

commit;
