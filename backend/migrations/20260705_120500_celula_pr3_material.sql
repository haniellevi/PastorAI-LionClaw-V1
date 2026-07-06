-- ============================================================================
-- PastorAI — Migration 20260705_120500 — Células PR3-PR9 (f): tabela
-- `celula_material` (materiais de apoio da Central).
-- Fontes: docs/sprints.json (feat-001.f / feat-012 materiais somente-leitura).
--
-- Material de apoio publicado pela Central (link/metadados; SEM upload real de
-- arquivo). Líder e discípulo veem em leitura (E14). igreja_id PRÓPRIO + policy
-- própria. Validação de URL http/https e limites de texto ficam na app (E2).
--
--   autor_id ON DELETE SET NULL (FK de autor)
--
-- `ativo=false` = inativado (sem edição no MVP). `updated_at` gerenciado pela
-- app. CREATE/índices transacionais + idempotentes. Não aplicada
-- automaticamente: rodar manualmente no Supabase (DEV primeiro).
-- ============================================================================

begin;

create table if not exists celula_material (
  id           uuid primary key default gen_random_uuid(),
  igreja_id    uuid not null references igrejas(id) on delete cascade,
  autor_id     uuid references pessoas(id) on delete set null,
  titulo       text not null,
  descricao    text,
  url          text,
  tipo         text,
  ativo        boolean not null default true,
  publicado_em timestamptz not null default now(),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz
);

comment on table celula_material is
  'Material de apoio publicado pela Central (link/metadados, sem upload real). Leitura p/ líder e discípulo (E14). igreja_id próprio + RLS própria. autor_id SET NULL.';

-- Índice exigido pela SPEC 2.1.7 (bate exatamente): feed de materiais ativos,
-- mais recentes primeiro. igreja_id é a coluna líder (cobre filtros por tenant).
create index if not exists idx_celula_material_feed
  on celula_material (igreja_id, ativo, publicado_em desc);

alter table celula_material enable row level security;
drop policy if exists tenant_isolation on celula_material;
create policy tenant_isolation on celula_material
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

commit;
