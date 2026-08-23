-- ============================================================================
-- PastorAI — Migration 20260822_225752 — Células pós-V1: trilha de auditoria
-- APPEND-ONLY `celula_membro_evento` para transferência/remoção direta de membros.
--
-- A Central de Células gerencia membros por execução DIRETA (não por solicitação):
-- POST /cells/{id}/membros/transferir e POST /cells/{id}/membros/remover. Cada
-- operação grava uma linha imutável aqui, na MESMA transação SQL que aplica os
-- efeitos de domínio (desativar vínculo origem, criar vínculo destino, atualizar
-- espelho pessoas.celula_id). Falha parcial → rollback total (domínio + auditoria).
--
-- `acao` ∈ {transferido, removido}. `celula_origem_id` é sempre a célula de onde
-- a pessoa sai; `celula_destino_id` é NULL para remoção e preenchida para
-- transferência. `actor_id` é a Pessoa da Central que executou. `motivo` é
-- opcional (texto livre, limite 1000 chars). `payload_snapshot` guarda a foto
-- do contexto no momento da operação.
--
-- igreja_id PRÓPRIO + RLS própria. FKs de actor/pessoa ON DELETE SET NULL;
-- estruturais (igreja/celula_origem/celula_destino) ON DELETE CASCADE.
-- Sem updated_at (append-only: só created_at, sem trigger de updated_at).
--
-- CREATE/índices/trigger transacionais + idempotentes. Aplicar manualmente no
-- Supabase, em ordem de nome de arquivo (DEV primeiro).
-- ============================================================================

begin;

-- ----------------------------------------------------------------------------
-- celula_membro_evento — trilha append-only de mudanças de membresia
-- ----------------------------------------------------------------------------
create table if not exists celula_membro_evento (
  id                 uuid primary key default gen_random_uuid(),
  igreja_id          uuid not null references igrejas(id) on delete cascade,
  pessoa_id          uuid not null references pessoas(id) on delete set null,
  celula_origem_id   uuid not null references celulas(id) on delete cascade,
  celula_destino_id  uuid references celulas(id) on delete cascade,
  acao               text not null,
  actor_id           uuid references pessoas(id) on delete set null,
  motivo             text,
  payload_snapshot   jsonb not null default '{}'::jsonb,
  created_at         timestamptz not null default now(),
  constraint celula_membro_evento_acao_chk check (acao in (
    'transferido', 'removido'
  ))
);

comment on table celula_membro_evento is
  'Trilha de auditoria APPEND-ONLY de transferência/remoção direta de membros (Células pós-V1). Blindada pelo trigger trg_celula_membro_evento_append_only: UPDATE/DELETE levantam exceção. igreja_id próprio + RLS própria. Sem updated_at.';

create index if not exists idx_celula_membro_evento_igreja
  on celula_membro_evento (igreja_id);
create index if not exists idx_celula_membro_evento_pessoa
  on celula_membro_evento (igreja_id, pessoa_id, created_at);
create index if not exists idx_celula_membro_evento_origem
  on celula_membro_evento (igreja_id, celula_origem_id, created_at);

alter table celula_membro_evento enable row level security;
drop policy if exists tenant_isolation on celula_membro_evento;
create policy tenant_isolation on celula_membro_evento
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

-- ----------------------------------------------------------------------------
-- Trigger append-only: bloqueia UPDATE e DELETE DIRETOS (feitos pela app) na
-- trilha de auditoria. search_path fixado (hardening, mesmo padrão de 0006).
--
-- IMPORTANTE: só bloqueia a operação de TOPO (pg_trigger_depth() = 1). As ações
-- referenciais aninhadas — DELETE em CASCADE ao apagar igreja/célula/pessoa pai
-- — rodam dentro do trigger de RI (depth > 1) e são PERMITIDAS. Mesmo carve-out
-- de trg_celula_solicitacao_evento_append_only.
-- ----------------------------------------------------------------------------
create or replace function trg_celula_membro_evento_append_only()
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

drop trigger if exists trg_celula_membro_evento_append_only
  on celula_membro_evento;
create trigger trg_celula_membro_evento_append_only
  before update or delete on celula_membro_evento
  for each row execute function trg_celula_membro_evento_append_only();

commit;
