-- ============================================================================
-- PastorAI — Migration 20260705_120200 — Células PR3-PR9 (c): tabela
-- `celula_visitante` (visitante presente numa reunião).
-- Fontes: docs/sprints.json (feat-001.c / feat-006 "POST visitors persiste em
--         celula_visitante podendo vincular expectativa_id").
--
-- Visitante que efetivamente compareceu a uma reunião (celula_reuniao, PR2).
-- Pode, opcionalmente, referenciar a expectativa que o antecedeu
-- (celula_expectativa_visitante, PR2). igreja_id PRÓPRIO + policy própria.
--
--   reuniao_id     ON DELETE CASCADE (parte da ocorrência — DB-DEC-04)
--   expectativa_id ON DELETE SET NULL (link opcional; apagar a expectativa NÃO
--                  pode apagar o registro real de comparecimento)
--
-- SEM UNIQUE: a mesma reunião pode receber vários visitantes. `updated_at`
-- gerenciado pela aplicação. CREATE/índices transacionais + idempotentes.
-- Não aplicada automaticamente.
-- ============================================================================

begin;

create table if not exists celula_visitante (
  id             uuid primary key default gen_random_uuid(),
  igreja_id      uuid not null references igrejas(id) on delete cascade,
  reuniao_id     uuid not null references celula_reuniao(id) on delete cascade,
  expectativa_id uuid references celula_expectativa_visitante(id) on delete set null,
  nome_visitante text not null,
  telefone       text,
  observacao     text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz
);

comment on table celula_visitante is
  'Visitante presente numa reunião de célula (Células PR3-PR9). Sem UNIQUE. igreja_id próprio + RLS própria. reuniao_id CASCADE; expectativa_id SET NULL (link opcional à expectativa que o antecedeu).';

create index if not exists idx_celula_visitante_igreja
  on celula_visitante (igreja_id);
create index if not exists idx_celula_visitante_reuniao
  on celula_visitante (igreja_id, reuniao_id);

alter table celula_visitante enable row level security;
drop policy if exists tenant_isolation on celula_visitante;
create policy tenant_isolation on celula_visitante
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

commit;
